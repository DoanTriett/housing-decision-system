"""Housing request API — enqueue pipeline runs and stream live progress."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.api.auth import CurrentUserId
from src.api.rate_limit import limiter
from src.api.request_response import (
    build_status_response,
    is_stale_pending,
    pending_age_seconds,
)
from src.api.schemas import (
    CreateHousingRequestBody,
    CreateHousingRequestResponse,
    RequestListItem,
    RequestListResponse,
    RequestStatusResponse,
)
from src.config import settings
from src.db.session import get_db
from src.models.recommendation import Recommendation
from src.models.user_request import UserRequest
from src.worker.progress import subscribe_progress
from src.worker.tasks import run_pipeline_task

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/requests", tags=["requests"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _get_owned_request(
    request_id: uuid.UUID,
    user_id: str,
    session: AsyncSession,
) -> UserRequest:
    """Load a UserRequest and enforce ownership (404 if missing, 403 if not owner)."""
    result = await session.execute(
        select(UserRequest).where(UserRequest.id == request_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this request",
        )
    return row


@router.post(
    "",
    response_model=CreateHousingRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a housing decision request",
    description=(
        "Authenticate with a Clerk Bearer token, persist a pending UserRequest "
        "owned by the verified user_id, enqueue the Celery pipeline, and return "
        "the request_id immediately (202)."
    ),
)
@limiter.limit(f"{settings.rate_limit_per_user_per_hour}/hour")
async def create_request(
    request: Request,
    body: CreateHousingRequestBody,
    session: DbSession,
    user_id: CurrentUserId,
) -> CreateHousingRequestResponse:
    """Validate input, persist a pending UserRequest, enqueue Celery, return immediately."""
    # `request` is required by slowapi for rate-limit key extraction.
    _ = request
    row = UserRequest(
        user_id=user_id,
        raw_text=body.free_text or "",
        budget_max=int(body.budget_max) if body.budget_max is not None else None,
        anchor_address=body.anchor_address,
        max_commute_minutes=body.max_commute_minutes,
        requires_laundry=body.requires_laundry,
        requires_pet_friendly=body.requires_pet_friendly,
        status="pending",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    user_request_dict = {
        "budget_max": body.budget_max,
        "anchor_address": body.anchor_address,
        "max_commute_minutes": body.max_commute_minutes,
        "requires_laundry": body.requires_laundry,
        "requires_pet_friendly": body.requires_pet_friendly,
        "free_text": body.free_text,
    }
    run_pipeline_task.delay(str(row.id), user_request_dict)
    logger.info("request_enqueued", request_id=str(row.id), user_id=user_id)
    return CreateHousingRequestResponse(request_id=row.id)


@router.get(
    "",
    response_model=RequestListResponse,
    summary="List my housing requests",
    description=(
        "Return paginated housing requests belonging to the authenticated user "
        "(newest first). Uses limit/offset query params."
    ),
)
async def list_requests(
    session: DbSession,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RequestListResponse:
    total_result = await session.execute(
        select(func.count())
        .select_from(UserRequest)
        .where(UserRequest.user_id == user_id)
    )
    total = int(total_result.scalar_one())

    result = await session.execute(
        select(UserRequest)
        .where(UserRequest.user_id == user_id)
        .order_by(UserRequest.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    items = [
        RequestListItem(
            request_id=row.id,
            status=row.status,
            budget_max=row.budget_max,
            anchor_address=row.anchor_address,
            created_at=row.created_at,
            is_stale=is_stale_pending(row.status, row.created_at),
            pending_seconds=pending_age_seconds(row.created_at)
            if row.status == "pending"
            else None,
        )
        for row in rows
    ]
    return RequestListResponse(items=items, limit=limit, offset=offset, total=total)


@router.get(
    "/{request_id}/stream",
    summary="Stream live request progress (SSE)",
    description=(
        "Server-Sent Events stream of pipeline progress for a request you own. "
        "Returns 403 if the request belongs to another user."
    ),
)
async def stream_request_progress(
    request_id: uuid.UUID,
    session: DbSession,
    user_id: CurrentUserId,
) -> EventSourceResponse:
    """SSE stream of Redis pub/sub progress events for this request."""
    row = await _get_owned_request(request_id, user_id, session)

    current_status = row.status
    terminal_payload: dict[str, Any] | None = None
    if current_status == "completed":
        rec_result = await session.execute(
            select(Recommendation).where(Recommendation.request_id == request_id)
        )
        rec_row = rec_result.scalar_one_or_none()
        recommendation = None
        if rec_row is not None:
            recommendation = {
                "ranked_listings": rec_row.ranked_listings,
                "trade_off_narrative": rec_row.trade_off_narrative,
            }
        terminal_payload = {
            "event": "done",
            "request_id": str(request_id),
            "recommendation": recommendation,
        }
    elif current_status == "failed":
        terminal_payload = {
            "event": "error",
            "request_id": str(request_id),
            "detail": "Request failed",
        }

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        if terminal_payload is not None:
            yield {
                "event": terminal_payload["event"],
                "data": json.dumps(terminal_payload, default=str),
            }
            return

        async for event in subscribe_progress(str(request_id)):
            yield {
                "event": str(event.get("event", "message")),
                "data": json.dumps(event, default=str),
            }

    return EventSourceResponse(event_generator())


@router.get(
    "/{request_id}",
    response_model=RequestStatusResponse,
    summary="Get request status and recommendation",
    description=(
        "Return current status and, when complete, the persisted RecommendationOutput. "
        "Returns 403 if the request belongs to another user."
    ),
)
async def get_request(
    request_id: uuid.UUID,
    session: DbSession,
    user_id: CurrentUserId,
) -> RequestStatusResponse:
    """Return current status and, when complete, the enriched recommendation + map context."""
    row = await _get_owned_request(request_id, user_id, session)
    return await build_status_response(row, session)
