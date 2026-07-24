"""Commute agent — geocode once, then walking times via CommuteProvider."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from src.agents.state import AgentState
from src.llm.exceptions import CommuteError, GeocodingError
from src.schemas.agents import AgentTraceEvent, CommuteResult
from src.tools.geocoding import geocode_address
from src.tools.maps import CommuteProvider

logger = structlog.get_logger(__name__)


async def run_commute(state: AgentState, provider: CommuteProvider) -> AgentState:
    """Compute walk minutes from the anchor address to each candidate.

    No LLM call — pure geocoding + Directions API + deterministic constraint check.
    """
    if not state["candidates"]:
        raise CommuteError("Commute agent requires candidates; listing_search must run first")

    started_at = datetime.now(tz=UTC)
    anchor = state["user_request"].anchor_address
    max_minutes = state["user_request"].max_commute_minutes

    try:
        anchor_lat, anchor_lon = await geocode_address(anchor)
    except GeocodingError as exc:
        raise CommuteError(f"Failed to geocode anchor address: {exc}", cause=exc) from exc

    results: dict[str, CommuteResult] = {}
    for candidate in state["candidates"]:
        walk_minutes = await provider.get_walk_minutes(
            anchor_lat, anchor_lon, candidate.lat, candidate.lon
        )
        meets = True if max_minutes is None else walk_minutes <= max_minutes
        results[candidate.id] = CommuteResult(
            listing_id=candidate.id,
            walk_minutes=round(walk_minutes, 1),
            meets_constraint=meets,
        )

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="commute",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )

    logger.info(
        "commute_done",
        request_id=state["request_id"],
        candidates=len(results),
        anchor_lat=anchor_lat,
        anchor_lon=anchor_lon,
        meeting_constraint=sum(1 for r in results.values() if r.meets_constraint),
    )

    return AgentState(
        **{
            **state,
            "commute_results": results,
            "trace": [*state["trace"], trace_event],
        }
    )
