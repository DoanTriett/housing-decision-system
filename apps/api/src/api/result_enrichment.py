"""Helpers for enriching recommendation payloads for the results UI (Day 12)."""

from __future__ import annotations

from typing import Any

import structlog

from src.agents.state import AgentState
from src.tools.geocoding import geocode_address

logger = structlog.get_logger(__name__)


def enrich_ranked_listings(state: AgentState) -> list[dict[str, Any]]:
    """Merge RankedListing with candidate + specialist findings for the results UI."""
    rec = state.get("recommendation")
    if rec is None:
        return []

    candidates_by_id = {c.id: c for c in state.get("candidates") or []}
    commute = state.get("commute_results") or {}
    neighborhoods = state.get("neighborhood_findings") or {}
    budgets = state.get("budget_analysis") or {}
    risks = state.get("risk_flags") or {}

    enriched: list[dict[str, Any]] = []
    for item in rec.ranked_listings:
        base = item.model_dump(mode="json")
        candidate = candidates_by_id.get(item.listing_id)
        commute_row = commute.get(item.listing_id)
        nb_row = neighborhoods.get(item.listing_id)
        budget_row = budgets.get(item.listing_id)
        risk_row = risks.get(item.listing_id)

        if candidate is not None:
            base.update(
                {
                    "title": candidate.title,
                    "address": candidate.address,
                    "neighborhood": candidate.neighborhood,
                    "price_monthly": candidate.price_monthly,
                    "lat": candidate.lat,
                    "lon": candidate.lon,
                }
            )
        if commute_row is not None:
            base["walk_minutes"] = commute_row.walk_minutes
        if nb_row is not None:
            base["safety_score"] = nb_row.safety_score
        if budget_row is not None:
            base["is_affordable"] = budget_row.is_affordable
            base["pct_of_budget"] = budget_row.pct_of_budget
        elif candidate is not None:
            # Fallback when planner skipped the budget agent — still useful for the table.
            budget_max = state["user_request"].budget_max
            if budget_max > 0:
                pct = round((candidate.price_monthly / budget_max) * 100, 2)
                base["pct_of_budget"] = pct
                base["is_affordable"] = candidate.price_monthly <= budget_max
        if risk_row is not None:
            base["risk_level"] = risk_row.risk_level

        enriched.append(base)

    return enriched


async def build_result_context(state: AgentState) -> dict[str, Any]:
    """Geocode the anchor once at persist time for the map view."""
    anchor = state["user_request"].anchor_address
    context: dict[str, Any] = {"anchor_address": anchor}
    try:
        lat, lon = await geocode_address(anchor)
        context["anchor_lat"] = lat
        context["anchor_lon"] = lon
    except Exception as exc:
        logger.warning(
            "anchor_geocode_failed_at_persist",
            anchor=anchor,
            error=str(exc),
        )
    return context
