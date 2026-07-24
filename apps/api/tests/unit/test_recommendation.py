"""Unit tests for Recommendation agent — LLM client is mocked."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.recommendation import run_recommendation
from src.agents.state import AgentState
from src.llm.client import LLMResponse
from src.schemas.agents import (
    BudgetAnalysis,
    CommuteResult,
    ListingCandidate,
    NeighborhoodAssessment,
    RiskAssessment,
    UserHousingRequest,
)


def _candidate(id: str, price: float) -> ListingCandidate:
    return ListingCandidate(
        id=id,
        title=f"Apt {id}",
        address=f"{id} Oak St",
        neighborhood="Hyde Park",
        price_monthly=price,
        beds=1.0,
        has_laundry=True,
        is_pet_friendly=True,
        lat=30.30,
        lon=-97.73,
    )


def _make_state(candidates: list[ListingCandidate]) -> AgentState:
    state = AgentState(
        request_id="unit-rec-001",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="Austin, TX",
            max_commute_minutes=20,
            free_text="safe and quiet, worried about scams",
        ),
        execution_plan=None,
        candidates=candidates,
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )
    for c in candidates:
        state["neighborhood_findings"][c.id] = NeighborhoodAssessment(
            listing_id=c.id,
            summary="Quiet residential streets.",
            safety_score=4,
            noise_score=2,
            source_docs=["hyde-park"],
        )
        state["commute_results"][c.id] = CommuteResult(
            listing_id=c.id,
            walk_minutes=15.0,
            meets_constraint=True,
        )
        state["budget_analysis"][c.id] = BudgetAnalysis(
            listing_id=c.id,
            monthly_cost=c.price_monthly,
            pct_of_budget=c.price_monthly / 12.0,
            is_affordable=c.price_monthly <= 1200,
            explanation="Within budget.",
        )
        state["risk_flags"][c.id] = RiskAssessment(
            listing_id=c.id,
            risk_level="low",
            flags=[],
            reasoning="No scam signals.",
        )
    return state


def _mock_llm_response(payload: dict) -> LLMResponse:
    fn = SimpleNamespace(
        name="submit_recommendation",
        arguments=json.dumps(payload),
    )
    tool_call = SimpleNamespace(function=fn)
    return LLMResponse(
        content=None,
        tool_calls=[tool_call],
        input_tokens=300,
        output_tokens=200,
        cost_usd=0.0005,
        latency_ms=500.0,
        raw=None,
    )


@pytest.mark.asyncio
async def test_recommendation_ranks_top_three_with_agent_citations() -> None:
    state = _make_state([_candidate("a", 900), _candidate("b", 1000), _candidate("c", 1100)])
    payload = {
        "ranked_listings": [
            {
                "listing_id": "a",
                "rank": 1,
                "score": 0.92,
                "rationale": (
                    "Commute agent confirmed a 15-min walk and "
                    "Neighborhood agent rated safety 4/5."
                ),
            },
            {
                "listing_id": "b",
                "rank": 2,
                "score": 0.81,
                "rationale": "Budget agent shows 83% of budget with no Risk agent flags.",
            },
            {
                "listing_id": "c",
                "rank": 3,
                "score": 0.70,
                "rationale": "Risk agent found no scam signals but price is highest.",
            },
        ],
        "trade_off_narrative": (
            "Apartment A is cheapest with a Commute agent 15-min walk; "
            "B costs more but Budget agent still marks it affordable; "
            "C is furthest from ideal on price despite clean Risk agent findings."
        ),
    }

    with patch(
        "src.agents.recommendation.complete",
        new=AsyncMock(return_value=_mock_llm_response(payload)),
    ):
        result = await run_recommendation(state)

    rec = result["recommendation"]
    assert rec is not None
    assert len(rec.ranked_listings) == 3
    assert [r.rank for r in rec.ranked_listings] == [1, 2, 3]
    assert all(0.0 <= r.score <= 1.0 for r in rec.ranked_listings)
    assert "Commute agent" in rec.ranked_listings[0].rationale
    assert "Budget agent" in rec.ranked_listings[1].rationale
    assert "Risk agent" in rec.ranked_listings[2].rationale
    assert rec.trade_off_narrative
    assert "stub" not in rec.trade_off_narrative.lower()


@pytest.mark.asyncio
async def test_recommendation_appends_trace_event() -> None:
    state = _make_state([_candidate("a", 900), _candidate("b", 950), _candidate("c", 980)])
    payload = {
        "ranked_listings": [
            {
                "listing_id": "a",
                "rank": 1,
                "score": 0.9,
                "rationale": "Neighborhood agent rated this area 4/5 for safety.",
            },
            {
                "listing_id": "b",
                "rank": 2,
                "score": 0.8,
                "rationale": "Commute agent confirmed under 20 minutes.",
            },
            {
                "listing_id": "c",
                "rank": 3,
                "score": 0.7,
                "rationale": "Budget agent marks this as affordable.",
            },
        ],
        "trade_off_narrative": "A wins on Neighborhood agent safety; B on commute.",
    }

    with patch(
        "src.agents.recommendation.complete",
        new=AsyncMock(return_value=_mock_llm_response(payload)),
    ):
        result = await run_recommendation(state)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "recommendation"
    assert result["trace"][0].cost_usd == 0.0005


@pytest.mark.asyncio
async def test_recommendation_handles_fewer_than_three_candidates() -> None:
    state = _make_state([_candidate("only", 850), _candidate("two", 880)])
    payload = {
        "ranked_listings": [
            {
                "listing_id": "only",
                "rank": 1,
                "score": 0.95,
                "rationale": "Commute agent confirmed a short walk to campus.",
            },
            {
                "listing_id": "two",
                "rank": 2,
                "score": 0.85,
                "rationale": "Risk agent reported low risk with no flags.",
            },
        ],
        "trade_off_narrative": (
            "Only two candidates available; only edges two on Commute agent time."
        ),
    }

    with patch(
        "src.agents.recommendation.complete",
        new=AsyncMock(return_value=_mock_llm_response(payload)),
    ):
        result = await run_recommendation(state)

    rec = result["recommendation"]
    assert rec is not None
    assert len(rec.ranked_listings) == 2
    assert [r.rank for r in rec.ranked_listings] == [1, 2]


@pytest.mark.asyncio
async def test_recommendation_empty_candidates_returns_empty_list() -> None:
    state = _make_state([])
    result = await run_recommendation(state)
    rec = result["recommendation"]
    assert rec is not None
    assert rec.ranked_listings == []
    assert result["trace"][0].agent_name == "recommendation"
