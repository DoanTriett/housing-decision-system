"""Unit tests for Risk agent — LLM client is mocked, no real API calls."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.risk import run_risk
from src.agents.state import AgentState
from src.llm.client import LLMResponse
from src.schemas.agents import ListingCandidate, UserHousingRequest


def _candidate(id: str, price: float, description: str = "") -> ListingCandidate:
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
        description=description,
    )


def _make_state(prices: list[tuple[str, float]]) -> AgentState:
    return AgentState(
        request_id="unit-risk-001",
        user_request=UserHousingRequest(
            budget_max=1500,
            anchor_address="Austin, TX",
            free_text="worried about scams",
        ),
        execution_plan=None,
        candidates=[_candidate(i, p, description=f"Nice place {i}") for i, p in prices],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


def _mock_llm_response(assessments: list[dict[str, str]]) -> LLMResponse:
    fn = SimpleNamespace(
        name="submit_risk_assessments",
        arguments=json.dumps({"assessments": assessments}),
    )
    tool_call = SimpleNamespace(function=fn)
    return LLMResponse(
        content=None,
        tool_calls=[tool_call],
        input_tokens=150,
        output_tokens=80,
        cost_usd=0.0002,
        latency_ms=300.0,
        raw=None,
    )


@pytest.mark.asyncio
async def test_below_market_flag_when_more_than_25_pct_below_median() -> None:
    """below_market flag fires when price is >25% below the candidate-set median."""
    # prices 1000, 1000, 500 → median 1000; 500 is 50% below
    state = _make_state([("a", 1000), ("b", 1000), ("cheap", 500)])
    assessments = [
        {"listing_id": "a", "risk_level": "low", "reasoning": "Normal."},
        {"listing_id": "b", "risk_level": "low", "reasoning": "Normal."},
        {
            "listing_id": "cheap",
            "risk_level": "high",
            "reasoning": "Suspiciously cheap.",
        },
    ]

    with patch(
        "src.agents.risk.complete",
        new=AsyncMock(return_value=_mock_llm_response(assessments)),
    ):
        result = await run_risk(state)

    cheap = result["risk_flags"]["cheap"]
    assert any("below market median" in f for f in cheap.flags)
    assert cheap.risk_level == "high"
    assert "Suspiciously cheap" in cheap.reasoning
    assert result["risk_flags"]["a"].flags == []


@pytest.mark.asyncio
async def test_risk_level_populated_from_mocked_llm() -> None:
    """risk_level comes from the mocked LLM tool payload."""
    state = _make_state([("x", 900), ("y", 950)])
    assessments = [
        {"listing_id": "x", "risk_level": "medium", "reasoning": "Vague landlord."},
        {"listing_id": "y", "risk_level": "low", "reasoning": "Clean listing."},
    ]

    with patch(
        "src.agents.risk.complete",
        new=AsyncMock(return_value=_mock_llm_response(assessments)),
    ):
        result = await run_risk(state)

    assert result["risk_flags"]["x"].risk_level == "medium"
    assert result["risk_flags"]["y"].risk_level == "low"


@pytest.mark.asyncio
async def test_trace_event_appended_for_risk() -> None:
    """AgentTraceEvent is appended with agent_name='risk'."""
    state = _make_state([("a", 800), ("b", 820)])
    assessments = [
        {"listing_id": "a", "risk_level": "low", "reasoning": "ok"},
        {"listing_id": "b", "risk_level": "low", "reasoning": "ok"},
    ]

    with patch(
        "src.agents.risk.complete",
        new=AsyncMock(return_value=_mock_llm_response(assessments)),
    ):
        result = await run_risk(state)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "risk"
    assert result["trace"][0].cost_usd == 0.0002
