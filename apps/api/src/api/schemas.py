"""Pydantic request/response models for the requests API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Basic defense-in-depth against prompt injection in free_text — not a complete solution.
_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system prompt",
)


class CreateHousingRequestBody(BaseModel):
    """POST /api/requests body — user_id comes from the verified JWT, not the body."""

    budget_max: float = Field(..., gt=0, lt=100_000)
    anchor_address: str = Field(..., min_length=3, max_length=200)
    max_commute_minutes: int | None = Field(default=None, ge=1, le=180)
    requires_laundry: bool = False
    requires_pet_friendly: bool = False
    free_text: str | None = Field(default=None, max_length=500)

    @field_validator("free_text")
    @classmethod
    def sanitize_free_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()
        lowered = cleaned.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in lowered:
                raise ValueError(f"free_text contains disallowed content (matched: {pattern!r})")
        return cleaned or None

    @field_validator("anchor_address")
    @classmethod
    def strip_anchor(cls, value: str) -> str:
        return value.strip()


class CreateHousingRequestResponse(BaseModel):
    request_id: uuid.UUID


class RankedListingDetail(BaseModel):
    """Ranked listing plus Day 12 comparison/map fields (extra keys optional for legacy rows)."""

    listing_id: str
    rank: int
    score: float
    rationale: str
    title: str | None = None
    address: str | None = None
    neighborhood: str | None = None
    price_monthly: float | None = None
    lat: float | None = None
    lon: float | None = None
    walk_minutes: float | None = None
    safety_score: int | None = None
    risk_level: str | None = None
    is_affordable: bool | None = None
    pct_of_budget: float | None = None


class EnrichedRecommendation(BaseModel):
    ranked_listings: list[RankedListingDetail]
    trade_off_narrative: str


class RequestStatusResponse(BaseModel):
    request_id: uuid.UUID
    status: str
    recommendation: EnrichedRecommendation | None = None
    detail: str | None = None
    anchor_address: str | None = None
    anchor_lat: float | None = None
    anchor_lon: float | None = None
    budget_max: int | None = None
    created_at: datetime | None = None


class RequestListItem(BaseModel):
    request_id: uuid.UUID
    status: str
    budget_max: int | None = None
    anchor_address: str | None = None
    created_at: datetime | None = None
    is_stale: bool = False
    pending_seconds: float | None = None


class RequestListResponse(BaseModel):
    items: list[RequestListItem]
    limit: int
    offset: int
    total: int


class AgentCostLatencyStat(BaseModel):
    agent_name: str
    call_count: int
    avg_latency_ms: float
    avg_cost_usd: float
    total_cost_usd: float


class StaleRequestItem(BaseModel):
    request_id: uuid.UUID
    user_id: str
    created_at: datetime
    pending_seconds: float


class ObservabilitySummaryResponse(BaseModel):
    recent_request_limit: int
    stale_pending_seconds: int
    request_count: int
    total_cost_usd: float
    per_agent: list[AgentCostLatencyStat]
    stale_pending: list[StaleRequestItem]


class StreamEvent(BaseModel):
    """Loose shape for SSE payloads (documented for clients)."""

    event: str
    request_id: str | None = None
    agent: str | None = None
    recommendation: dict[str, Any] | None = None
    detail: str | None = None
    cost_usd: float | None = Field(default=None)
