"""Unit tests for Day 11 SSE agent summary helpers."""

from __future__ import annotations

from src.schemas.agents import (
    AgentName,
    CriticReview,
    ExecutionPlan,
    ListingCandidate,
    RankedListing,
    RecommendationOutput,
)
from src.worker.tasks import _agent_summary, _enrich_progress_payload


def _candidate(i: int) -> ListingCandidate:
    return ListingCandidate(
        id=f"c{i}",
        title=f"Apt {i}",
        address=f"{i} Main",
        neighborhood="Hyde Park",
        price_monthly=1000,
        beds=1,
        has_laundry=True,
        is_pet_friendly=True,
        lat=30.3,
        lon=-97.7,
    )


def test_listing_search_summary_counts_candidates() -> None:
    summary = _agent_summary(
        "listing_search", {"candidates": [_candidate(1), _candidate(2)]}
    )
    assert summary == "Found 2 candidates"


def test_planner_payload_includes_selected_agents_and_reasoning() -> None:
    plan = ExecutionPlan(
        selected_agents=[AgentName.listing_search, AgentName.budget],
        reasoning="Budget-only request.",
        per_agent_goals={
            AgentName.listing_search: "find",
            AgentName.budget: "check",
        },
    )
    payload = _enrich_progress_payload(
        "planner", {"execution_plan": plan}, "req-1"
    )
    assert payload["event"] == "agent_complete"
    assert payload["agent"] == "planner"
    assert payload["selected_agents"] == ["listing_search", "budget"]
    assert payload["reasoning"] == "Budget-only request."
    assert "specialist" in payload["summary"].lower()


def test_listing_search_retry_maps_to_listing_search_agent() -> None:
    payload = _enrich_progress_payload(
        "listing_search_retry",
        {"candidates": [_candidate(1)]},
        "req-2",
    )
    assert payload["agent"] == "listing_search"
    assert payload["summary"] == "Found 1 candidates"


def test_critic_and_recommendation_summaries() -> None:
    assert (
        _agent_summary(
            "critic",
            {"critic_notes": CriticReview(approved=True, issues=[], retry_agent=None)},
        )
        == "Approved — proceed to recommendation"
    )
    rec = RecommendationOutput(
        ranked_listings=[
            RankedListing(listing_id="a", rank=1, score=0.9, rationale="ok")
        ],
        trade_off_narrative="n",
    )
    assert _agent_summary("recommendation", {"recommendation": rec}) == "Ranked top 1"
