"""Listing Search agent — pure DB filtering, no LLM call."""

import time
from datetime import UTC, datetime

import structlog

from src.agents.state import AgentState
from src.llm.exceptions import ListingSearchError
from src.schemas.agents import AgentTraceEvent, ListingFilters
from src.tools.listings_repo import ListingsProvider

logger = structlog.get_logger(__name__)


async def run_listing_search(state: AgentState, provider: ListingsProvider) -> AgentState:
    """Filter listings by hard constraints from the user request.

    Raises ListingSearchError when zero candidates match.
    Appends an AgentTraceEvent with tokens=0 / cost_usd=0.0 (no LLM call).
    """
    started_at = datetime.now(tz=UTC)
    t0 = time.perf_counter()

    req = state["user_request"]
    filters = ListingFilters(
        max_price=req.budget_max,
        requires_laundry=True if req.requires_laundry else None,
        requires_pet_friendly=True if req.requires_pet_friendly else None,
        limit=100,
    )

    candidates = await provider.search(filters)

    if not candidates:
        raise ListingSearchError(
            f"No listings found matching filters: "
            f"max_price={filters.max_price}, "
            f"laundry={filters.requires_laundry}, "
            f"pet={filters.requires_pet_friendly}"
        )

    finished_at = datetime.now(tz=UTC)
    latency_ms = (time.perf_counter() - t0) * 1000

    trace_event = AgentTraceEvent(
        agent_name="listing_search",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )

    logger.info(
        "listing_search_done",
        request_id=state["request_id"],
        candidates=len(candidates),
        latency_ms=round(latency_ms, 1),
    )

    return AgentState(
        **{
            **state,
            "candidates": candidates,
            "trace": [*state["trace"], trace_event],
        }
    )
