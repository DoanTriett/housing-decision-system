"""Unit tests for Budget agent — LLM client is mocked, no real API calls."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.budget import run_budget
from src.agents.state import AgentState
from src.llm.client import LLMResponse
from src.schemas.agents import ListingCandidate, UserHousingRequest


def _candidate(id: str, price: float) -> ListingCandidate:
    return ListingCandidate(
        id=id,
        title=f"Apt {id}",
        address=f"{id} Oak St",
        neighborhood="Hyde Park",
        price_monthly=price,
        beds=1.0,
        has_laundry=True,
        is_pet_friendly=False,
        lat=30.30,
        lon=-97.73,
    )


def _make_state(budget_max: float, prices: list[tuple[str, float]]) -> AgentState:
    return AgentState(
        request_id="unit-budget-001",
        user_request=UserHousingRequest(
            budget_max=budget_max,
            anchor_address="Austin, TX",
        ),
        execution_plan=None,
        candidates=[_candidate(i, p) for i, p in prices],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


def _mock_llm_response(explanations: list[dict[str, str]]) -> LLMResponse:
    fn = SimpleNamespace(
        name="submit_budget_explanations",
        arguments=json.dumps({"explanations": explanations}),
    )
    tool_call = SimpleNamespace(function=fn)
    return LLMResponse(
        content=None,
        tool_calls=[tool_call],
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0003,
        latency_ms=400.0,
        raw=None,
    )


@pytest.mark.asyncio
async def test_budget_pct_of_budget_computed_correctly() -> None:
    """pct_of_budget is correct for three different price/budget pairs."""
    # budget=1000 → 500=50%, 1000=100%, 750=75%
    state = _make_state(1000, [("a", 500), ("b", 1000), ("c", 750)])
    explanations = [
        {"listing_id": "a", "explanation": "Half your budget."},
        {"listing_id": "b", "explanation": "Exactly at budget."},
        {"listing_id": "c", "explanation": "Three quarters of budget."},
    ]

    with patch(
        "src.agents.budget.complete",
        new=AsyncMock(return_value=_mock_llm_response(explanations)),
    ):
        result = await run_budget(state)

    assert result["budget_analysis"]["a"].pct_of_budget == 50.0
    assert result["budget_analysis"]["b"].pct_of_budget == 100.0
    assert result["budget_analysis"]["c"].pct_of_budget == 75.0


@pytest.mark.asyncio
async def test_budget_is_affordable_false_when_over_budget() -> None:
    """is_affordable=False when price exceeds budget."""
    state = _make_state(900, [("x", 950)])
    explanations = [{"listing_id": "x", "explanation": "Over budget by $50."}]

    with patch(
        "src.agents.budget.complete",
        new=AsyncMock(return_value=_mock_llm_response(explanations)),
    ):
        result = await run_budget(state)

    assert result["budget_analysis"]["x"].is_affordable is False
    assert result["budget_analysis"]["x"].pct_of_budget == pytest.approx(105.56, abs=0.01)


@pytest.mark.asyncio
async def test_budget_explanation_populated_from_llm() -> None:
    """explanation field comes from the mocked tool-call response."""
    state = _make_state(900, [("y", 850)])
    explanations = [
        {
            "listing_id": "y",
            "explanation": (
                "At $850/mo this is 94% of your $900 budget, leaving $50/month of breathing room."
            ),
        }
    ]

    with patch(
        "src.agents.budget.complete",
        new=AsyncMock(return_value=_mock_llm_response(explanations)),
    ):
        result = await run_budget(state)

    assert "94%" in result["budget_analysis"]["y"].explanation
    assert result["budget_analysis"]["y"].explanation != ""


@pytest.mark.asyncio
async def test_budget_appends_trace_event() -> None:
    """AgentTraceEvent is appended with agent_name='budget'."""
    state = _make_state(1000, [("z", 800)])
    explanations = [{"listing_id": "z", "explanation": "Affordable."}]

    with patch(
        "src.agents.budget.complete",
        new=AsyncMock(return_value=_mock_llm_response(explanations)),
    ):
        result = await run_budget(state)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "budget"
    assert result["trace"][0].input_tokens == 200
    assert result["trace"][0].output_tokens == 100
    assert result["trace"][0].cost_usd == 0.0003
