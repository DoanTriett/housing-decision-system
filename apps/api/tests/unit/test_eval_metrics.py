"""Unit tests for Day 13 eval metrics."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.metrics import (
    constraint_match,
    routing_prf,
    top_satisfies_hard_constraints,
)
from src.agents.state import AgentState
from src.schemas.agents import (
    CommuteResult,
    ListingCandidate,
    RankedListing,
    RecommendationOutput,
    UserHousingRequest,
)


def test_routing_prf_perfect() -> None:
    p, r, f1 = routing_prf(
        ["listing_search", "commute"],
        ["commute", "listing_search"],
    )
    assert p == 1.0 and r == 1.0 and f1 == 1.0


def test_routing_prf_partial() -> None:
    p, r, f1 = routing_prf(
        ["listing_search", "commute", "risk"],
        ["listing_search", "commute"],
    )
    assert p == 2 / 3
    assert r == 1.0
    assert 0.7 < f1 < 0.9


def test_constraint_match_impossible_ok_on_failure() -> None:
    assert constraint_match(None, False) is True
    assert constraint_match(False, False) is True
    assert constraint_match(True, False) is False
    assert constraint_match(True, True) is True
    assert constraint_match(False, True) is False


def test_top_satisfies_uses_commute_meets_flag() -> None:
    candidate = ListingCandidate(
        id="a",
        title="A",
        address="1 Main",
        neighborhood="Hyde Park",
        price_monthly=1000,
        beds=1,
        has_laundry=True,
        is_pet_friendly=True,
        lat=30.3,
        lon=-97.7,
    )
    state = AgentState(
        request_id="t",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="Austin, TX",
            max_commute_minutes=20,
        ),
        execution_plan=None,
        candidates=[candidate],
        neighborhood_findings={},
        commute_results={
            "a": CommuteResult(listing_id="a", walk_minutes=35.0, meets_constraint=False)
        },
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=RecommendationOutput(
            ranked_listings=[RankedListing(listing_id="a", rank=1, score=0.4, rationale="far")],
            trade_off_narrative="Far.",
        ),
        trace=[],
    )
    assert top_satisfies_hard_constraints(state) is False
