"""Admin observability aggregates over AgentRun rows (Day 12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import CurrentUserId
from src.api.observability_constants import (
    OBSERVABILITY_RECENT_REQUEST_LIMIT,
    STALE_PENDING_SECONDS,
)
from src.api.schemas import (
    AgentCostLatencyStat,
    ObservabilitySummaryResponse,
    StaleRequestItem,
)
from src.db.session import get_db
from src.models.agent_run import AgentRun
from src.models.user_request import UserRequest

router = APIRouter(prefix="/api/admin/observability", tags=["admin"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/summary",
    response_model=ObservabilitySummaryResponse,
    summary="Aggregate latency/cost and stale pending requests",
    description=(
        "Authenticated endpoint (no admin role gate yet — Day 12 judgment). "
        f"Aggregates AgentRun rows for the most recent "
        f"{OBSERVABILITY_RECENT_REQUEST_LIMIT} requests system-wide, plus any "
        f"pending requests older than {STALE_PENDING_SECONDS}s."
    ),
)
async def observability_summary(
    session: DbSession,
    user_id: CurrentUserId,
    recent_limit: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Override for how many recent requests to include",
        ),
    ] = OBSERVABILITY_RECENT_REQUEST_LIMIT,
) -> ObservabilitySummaryResponse:
    # Auth required; role gating is explicitly out of scope for Day 12.
    _ = user_id

    recent_ids_result = await session.execute(
        select(UserRequest.id)
        .order_by(UserRequest.created_at.desc())
        .limit(recent_limit)
    )
    recent_ids = list(recent_ids_result.scalars().all())

    per_agent_map: dict[str, dict[str, float | int]] = {}
    total_cost = 0.0

    if recent_ids:
        runs_result = await session.execute(
            select(AgentRun).where(AgentRun.request_id.in_(recent_ids))
        )
        runs = runs_result.scalars().all()
        for run in runs:
            cost = float(run.cost_usd or 0.0)
            total_cost += cost
            latency_ms = 0.0
            if run.started_at is not None and run.finished_at is not None:
                delta = run.finished_at - run.started_at
                latency_ms = delta.total_seconds() * 1000.0

            bucket = per_agent_map.setdefault(
                run.agent_name,
                {
                    "call_count": 0,
                    "latency_sum": 0.0,
                    "cost_sum": 0.0,
                },
            )
            bucket["call_count"] = int(bucket["call_count"]) + 1
            bucket["latency_sum"] = float(bucket["latency_sum"]) + latency_ms
            bucket["cost_sum"] = float(bucket["cost_sum"]) + cost

    per_agent: list[AgentCostLatencyStat] = []
    for name, bucket in sorted(per_agent_map.items()):
        count = int(bucket["call_count"])
        per_agent.append(
            AgentCostLatencyStat(
                agent_name=name,
                call_count=count,
                avg_latency_ms=(
                    float(bucket["latency_sum"]) / count if count else 0.0
                ),
                avg_cost_usd=(float(bucket["cost_sum"]) / count if count else 0.0),
                total_cost_usd=float(bucket["cost_sum"]),
            )
        )

    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(seconds=STALE_PENDING_SECONDS)
    stale_result = await session.execute(
        select(UserRequest)
        .where(UserRequest.status == "pending")
        .where(UserRequest.created_at <= cutoff)
        .order_by(UserRequest.created_at.asc())
    )
    stale_rows = stale_result.scalars().all()
    stale_pending = [
        StaleRequestItem(
            request_id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            pending_seconds=(now - row.created_at).total_seconds(),
        )
        for row in stale_rows
        if row.created_at is not None
    ]

    return ObservabilitySummaryResponse(
        recent_request_limit=recent_limit,
        stale_pending_seconds=STALE_PENDING_SECONDS,
        request_count=len(recent_ids),
        total_cost_usd=round(total_cost, 6),
        per_agent=per_agent,
        stale_pending=stale_pending,
    )
