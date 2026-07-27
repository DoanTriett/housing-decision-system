"""Shared helpers for request status/list responses (Day 12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.observability_constants import STALE_PENDING_SECONDS
from src.api.schemas import (
    EnrichedRecommendation,
    RankedListingDetail,
    RequestStatusResponse,
)
from src.models.listing import Listing
from src.models.recommendation import Recommendation
from src.models.user_request import UserRequest


def pending_age_seconds(created_at: datetime | None, now: datetime | None = None) -> float | None:
    if created_at is None:
        return None
    clock = now or datetime.now(tz=UTC)
    # Normalize naive datetimes from older rows / SQLite tests.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0.0, (clock - created_at).total_seconds())


def is_stale_pending(status: str, created_at: datetime | None, now: datetime | None = None) -> bool:
    if status != "pending":
        return False
    age = pending_age_seconds(created_at, now)
    return age is not None and age >= STALE_PENDING_SECONDS


async def build_status_response(
    row: UserRequest,
    session: AsyncSession,
) -> RequestStatusResponse:
    """Build enriched RequestStatusResponse, joining Listing for legacy rows."""
    recommendation: EnrichedRecommendation | None = None
    anchor_lat: float | None = None
    anchor_lon: float | None = None

    if row.status == "completed":
        rec_result = await session.execute(
            select(Recommendation).where(Recommendation.request_id == row.id)
        )
        rec_row = rec_result.scalar_one_or_none()
        if rec_row is not None:
            raw_items = list(rec_row.ranked_listings or [])
            enriched_items = await _hydrate_ranked_from_listings(session, raw_items)
            if row.budget_max is not None:
                for item in enriched_items:
                    if item.get("is_affordable") is None and item.get("price_monthly") is not None:
                        price = float(item["price_monthly"])
                        budget = float(row.budget_max)
                        if budget > 0:
                            item["pct_of_budget"] = round((price / budget) * 100, 2)
                            item["is_affordable"] = price <= budget
            recommendation = EnrichedRecommendation(
                ranked_listings=[
                    RankedListingDetail.model_validate(item) for item in enriched_items
                ],
                trade_off_narrative=rec_row.trade_off_narrative or "",
            )
            ctx = rec_row.result_context or {}
            if isinstance(ctx, dict):
                lat = ctx.get("anchor_lat")
                lon = ctx.get("anchor_lon")
                if isinstance(lat, (int, float)):
                    anchor_lat = float(lat)
                if isinstance(lon, (int, float)):
                    anchor_lon = float(lon)

    return RequestStatusResponse(
        request_id=row.id,
        status=row.status,
        recommendation=recommendation,
        detail=None,
        anchor_address=row.anchor_address,
        anchor_lat=anchor_lat,
        anchor_lon=anchor_lon,
        budget_max=row.budget_max,
        created_at=row.created_at,
    )


async def _hydrate_ranked_from_listings(
    session: AsyncSession,
    raw_items: list[Any],
) -> list[dict[str, Any]]:
    """Fill missing title/address/coords from Listing rows when possible."""
    missing_ids: list[uuid.UUID] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if item.get("title") and item.get("lat") is not None:
            continue
        listing_id = item.get("listing_id")
        if not listing_id:
            continue
        try:
            missing_ids.append(uuid.UUID(str(listing_id)))
        except ValueError:
            continue

    by_id: dict[str, Listing] = {}
    if missing_ids:
        result = await session.execute(select(Listing).where(Listing.id.in_(missing_ids)))
        for row in result.scalars().all():
            by_id[str(row.id)] = row

    hydrated: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        merged = dict(item)
        listing_id = str(merged.get("listing_id") or "")
        listing = by_id.get(listing_id)
        if listing is not None:
            merged.setdefault("title", listing.title)
            merged.setdefault("address", listing.address)
            merged.setdefault("neighborhood", listing.neighborhood)
            merged.setdefault("price_monthly", float(listing.price_monthly))
            merged.setdefault("lat", float(listing.lat))
            merged.setdefault("lon", float(listing.lon))
        hydrated.append(merged)
    return hydrated
