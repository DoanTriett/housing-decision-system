"""Integration tests for GET /api/admin/observability/summary (Day 12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api import auth as auth_module
from src.api.observability_constants import (
    OBSERVABILITY_RECENT_REQUEST_LIMIT,
    STALE_PENDING_SECONDS,
)
from src.db.session import AsyncSessionLocal, engine
from src.main import app
from src.models.agent_run import AgentRun
from src.models.user_request import UserRequest

pytestmark = pytest.mark.integration

_DEMO_USER = "obs_demo_user"
_AUTH_HEADERS = {"Authorization": "Bearer demo-test-token"}


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> Any:
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _mock_auth() -> Any:
    async def _verify() -> str:
        return _DEMO_USER

    app.dependency_overrides[auth_module.verify_clerk_token] = _verify
    yield
    app.dependency_overrides.pop(auth_module.verify_clerk_token, None)


@pytest.mark.asyncio
async def test_observability_summary_aggregates_and_flags_stale() -> None:
    request_id = uuid.uuid4()
    stale_id = uuid.uuid4()
    started = datetime.now(tz=UTC) - timedelta(seconds=5)
    finished = started + timedelta(milliseconds=250)
    stale_created = datetime.now(tz=UTC) - timedelta(
        seconds=STALE_PENDING_SECONDS + 30
    )

    async with AsyncSessionLocal() as session:
        session.add(
            UserRequest(
                id=request_id,
                user_id=_DEMO_USER,
                raw_text="",
                budget_max=2000,
                anchor_address="123 Congress Ave, Austin, TX",
                status="completed",
            )
        )
        session.add(
            UserRequest(
                id=stale_id,
                user_id=_DEMO_USER,
                raw_text="",
                budget_max=1800,
                anchor_address="456 Guadalupe St, Austin, TX",
                status="pending",
                created_at=stale_created,
            )
        )
        # Force created_at for the stale row (TimestampMixin may override on insert).
        await session.flush()
        await session.execute(
            text(
                "UPDATE user_requests SET created_at = :created WHERE id = :id"
            ),
            {"created": stale_created, "id": stale_id},
        )
        session.add(
            AgentRun(
                request_id=request_id,
                agent_name="planner",
                started_at=started,
                finished_at=finished,
                tokens_used=100,
                cost_usd=0.012345,
                output_json={"input_tokens": 60, "output_tokens": 40},
            )
        )
        session.add(
            AgentRun(
                request_id=request_id,
                agent_name="budget",
                started_at=started,
                finished_at=finished,
                tokens_used=50,
                cost_usd=0.004321,
                output_json={"input_tokens": 30, "output_tokens": 20},
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/admin/observability/summary",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["recent_request_limit"] == OBSERVABILITY_RECENT_REQUEST_LIMIT
    assert payload["stale_pending_seconds"] == STALE_PENDING_SECONDS
    assert payload["total_cost_usd"] >= 0.016
    agent_names = {row["agent_name"] for row in payload["per_agent"]}
    assert "planner" in agent_names
    assert "budget" in agent_names
    stale_ids = {item["request_id"] for item in payload["stale_pending"]}
    assert str(stale_id) in stale_ids
