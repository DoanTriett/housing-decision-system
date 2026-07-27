"""Multi-user isolation tests for Clerk JWT auth on /api/requests."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import HTTPException, Request, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.api import auth as auth_module
from src.db.session import AsyncSessionLocal, engine
from src.main import app
from src.models.user_request import UserRequest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> Any:
    yield
    await engine.dispose()


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task[Any]]:
    scheduled: list[asyncio.Task[Any]] = []

    def fake_delay(request_id: str, user_request_dict: dict[str, Any]) -> None:
        del request_id, user_request_dict

        async def _noop() -> None:
            return None

        scheduled.append(asyncio.create_task(_noop()))

    monkeypatch.setattr("src.api.routes.requests.run_pipeline_task.delay", fake_delay)
    return scheduled


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer fake-token-for-{user_id}"}


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    del patch_pipeline
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/requests",
            json={
                "budget_max": 1200,
                "anchor_address": "Austin, TX",
                "free_text": "hello",
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_b_cannot_see_or_access_user_a_request(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    user_a = "user_a_isolation"
    user_b = "user_b_isolation"

    async def override_verify(request: Request) -> str:
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        token = auth.split(" ", 1)[1].strip()
        if token == f"fake-token-for-{user_a}":
            return user_a
        if token == f"fake-token-for-{user_b}":
            return user_b
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    app.dependency_overrides[auth_module.verify_clerk_token] = override_verify
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            create = await client.post(
                "/api/requests",
                headers=_auth_headers(user_a),
                json={
                    "budget_max": 1200,
                    "anchor_address": "Austin, TX",
                    "free_text": "user a request",
                },
            )
            assert create.status_code == 202
            request_id = create.json()["request_id"]
            assert patch_pipeline
            await patch_pipeline[0]

            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(UserRequest).where(UserRequest.id == uuid.UUID(request_id))
                    )
                ).scalar_one()
                assert row.user_id == user_a

            listed = await client.get("/api/requests", headers=_auth_headers(user_b))
            assert listed.status_code == 200
            body = listed.json()
            ids = {item["request_id"] for item in body["items"]}
            assert request_id not in ids

            forbidden = await client.get(
                f"/api/requests/{request_id}",
                headers=_auth_headers(user_b),
            )
            assert forbidden.status_code == 403
    finally:
        app.dependency_overrides.pop(auth_module.verify_clerk_token, None)
