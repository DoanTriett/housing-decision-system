"""Integration tests for Day 8 requests API.

Judgment: instead of Celery ``task_always_eager`` (which nests ``asyncio.run``
inside FastAPI's loop and breaks SQLAlchemy async engines across loops), we
patch ``run_pipeline_task.delay`` to schedule a fast async stub on the same
event loop. That still proves POST → Postgres → progress/result wiring without
a worker process or LLM calls.

Auth is overridden to a fixed demo user so Day 8 coverage stays independent of
Clerk JWKS (Day 9 isolation tests cover real multi-user auth behavior).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.api import auth as auth_module
from src.db.session import AsyncSessionLocal, engine
from src.main import app
from src.models.recommendation import Recommendation
from src.models.user_request import UserRequest
from src.worker.progress import publish_progress

pytestmark = pytest.mark.integration

_DEMO_USER = "demo_user"
_AUTH_HEADERS = {"Authorization": "Bearer demo-test-token"}


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> Any:
    """Drop pooled asyncpg connections so the next test gets a fresh event loop."""
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _mock_auth() -> Any:
    async def _verify() -> str:
        return _DEMO_USER

    app.dependency_overrides[auth_module.verify_clerk_token] = _verify
    yield
    app.dependency_overrides.pop(auth_module.verify_clerk_token, None)


async def _fake_execute_pipeline(
    request_id: str, user_request_dict: dict[str, Any]
) -> dict[str, Any] | None:
    """Minimal stand-in for the LangGraph pipeline used only in this test."""
    del user_request_dict
    req_uuid = uuid.UUID(request_id)

    publish_progress(
        request_id, {"event": "status", "status": "running", "request_id": request_id}
    )
    publish_progress(
        request_id,
        {"event": "agent_complete", "agent": "planner", "request_id": request_id},
    )
    publish_progress(
        request_id,
        {
            "event": "agent_complete",
            "agent": "recommendation",
            "request_id": request_id,
        },
    )

    recommendation = {
        "ranked_listings": [
            {
                "listing_id": "listing-test-1",
                "rank": 1,
                "score": 0.9,
                "rationale": "Commute agent confirmed a short walk (test stub).",
            }
        ],
        "trade_off_narrative": "Test stub trade-off narrative.",
    }

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserRequest).where(UserRequest.id == req_uuid)
        )
        row = result.scalar_one()
        session.add(
            Recommendation(
                request_id=req_uuid,
                ranked_listings=recommendation["ranked_listings"],
                trade_off_narrative=recommendation["trade_off_narrative"],
            )
        )
        row.status = "completed"
        await session.commit()

    publish_progress(
        request_id,
        {
            "event": "done",
            "request_id": request_id,
            "recommendation": recommendation,
        },
    )
    return recommendation


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task[Any]]:
    """Replace Celery .delay with an in-loop async stub; return scheduled tasks."""
    scheduled: list[asyncio.Task[Any]] = []

    def fake_delay(request_id: str, user_request_dict: dict[str, Any]) -> None:
        scheduled.append(
            asyncio.create_task(_fake_execute_pipeline(request_id, user_request_dict))
        )

    monkeypatch.setattr(
        "src.api.routes.requests.run_pipeline_task.delay", fake_delay
    )
    return scheduled


@pytest.mark.asyncio
async def test_create_request_returns_202(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/requests",
            headers=_AUTH_HEADERS,
            json={
                "budget_max": 1200,
                "anchor_address": "University of Texas at Austin, Austin, TX",
                "max_commute_minutes": 20,
                "requires_laundry": False,
                "requires_pet_friendly": False,
                "free_text": "just show me options under budget",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert "request_id" in body
        uuid.UUID(body["request_id"])
        assert patch_pipeline
        await patch_pipeline[0]


@pytest.mark.asyncio
async def test_get_request_returns_completed_recommendation(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        create = await client.post(
            "/api/requests",
            headers=_AUTH_HEADERS,
            json={
                "budget_max": 1200,
                "anchor_address": "Austin, TX",
                "free_text": "under budget",
            },
        )
        assert create.status_code == 202
        request_id = create.json()["request_id"]
        await patch_pipeline[0]

        got = await client.get(
            f"/api/requests/{request_id}", headers=_AUTH_HEADERS
        )
        assert got.status_code == 200
        status_body = got.json()

    assert status_body["status"] == "completed"
    assert status_body["recommendation"] is not None
    assert status_body["recommendation"]["trade_off_narrative"]
    assert len(status_body["recommendation"]["ranked_listings"]) >= 1


@pytest.mark.asyncio
async def test_get_request_unknown_id_returns_404(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    del patch_pipeline
    bad_id = uuid.uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/requests/{bad_id}", headers=_AUTH_HEADERS
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_completed_request_emits_done(
    patch_pipeline: list[asyncio.Task[Any]],
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        create = await client.post(
            "/api/requests",
            headers=_AUTH_HEADERS,
            json={
                "budget_max": 900,
                "anchor_address": "Austin, TX",
                "free_text": "quiet",
            },
        )
        request_id = create.json()["request_id"]
        await patch_pipeline[0]

        async with client.stream(
            "GET", f"/api/requests/{request_id}/stream", headers=_AUTH_HEADERS
        ) as stream:
            assert stream.status_code == 200
            chunks: list[str] = []
            payload: dict[str, Any] | None = None
            async for line in stream.aiter_lines():
                chunks.append(line)
                if line.startswith("data:"):
                    payload = json.loads(line.removeprefix("data:").strip())
                    if payload.get("event") in ("done", "error"):
                        break

    assert payload is not None
    assert payload["event"] == "done"
    assert payload["recommendation"] is not None
