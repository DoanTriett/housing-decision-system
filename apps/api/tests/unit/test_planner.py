"""Unit tests for the Planner agent.

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.planner import run_planner
from src.agents.state import AgentState
from src.schemas.agents import AgentName, ExecutionPlan, UserHousingRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    budget_max: float,
    anchor_address: str,
    max_commute_minutes: int | None = None,
    requires_laundry: bool = False,
    requires_pet_friendly: bool = False,
    free_text: str | None = None,
) -> AgentState:
    return AgentState(
        request_id="test-req-001",
        user_request=UserHousingRequest(
            budget_max=budget_max,
            anchor_address=anchor_address,
            max_commute_minutes=max_commute_minutes,
            requires_laundry=requires_laundry,
            requires_pet_friendly=requires_pet_friendly,
            free_text=free_text,
        ),
        execution_plan=None,
        candidates=[],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=0,
        recommendation=None,
        trace=[],
    )


def _mock_tool_response(plan: ExecutionPlan) -> Any:
    """Build a fake LLMResponse that looks like a tool-calling reply."""
    from src.llm.client import LLMResponse

    fn = SimpleNamespace(
        name="submit_execution_plan",
        arguments=json.dumps(plan.model_dump()),
    )
    tool_call = SimpleNamespace(function=fn)

    return LLMResponse(
        content=None,
        tool_calls=[tool_call],
        input_tokens=120,
        output_tokens=80,
        cost_usd=0.0004,
        latency_ms=540.0,
        raw=None,
    )


# ---------------------------------------------------------------------------
# Scenario 1: Full request → all 5 agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_full_request_selects_all_agents() -> None:
    """Budget + commute + safety + pet-friendly + laundry → all 5 agents."""
    plan = ExecutionPlan(
        selected_agents=[
            AgentName.listing_search,
            AgentName.neighborhood,
            AgentName.commute,
            AgentName.budget,
            AgentName.risk,
        ],
        reasoning=(
            "All five constraints are present: budget → budget, commute → commute, "
            "safety/quiet → neighborhood, price caution → risk, laundry+pet → listing_search."
        ),
        per_agent_goals={
            AgentName.listing_search: "Find listings under $900 that allow pets and have laundry.",
            AgentName.neighborhood: "Assess safety and noise levels for each candidate.",
            AgentName.commute: "Verify each listing is within 20 minutes walking of UT Austin.",
            AgentName.budget: "Compute affordability at $900 budget for each candidate.",
            AgentName.risk: "Flag any listings with suspicious below-market pricing.",
        },
    )

    state = _make_state(
        budget_max=900,
        anchor_address="2400 Whitis Ave, Austin TX (UT Austin)",
        max_commute_minutes=20,
        requires_laundry=True,
        requires_pet_friendly=True,
        free_text="I want a safe, quiet neighborhood.",
    )

    with patch(
        "src.agents.planner.complete", new=AsyncMock(return_value=_mock_tool_response(plan))
    ):
        result = await run_planner(state)

    ep = result["execution_plan"]
    assert ep is not None
    assert set(ep.selected_agents) == {
        AgentName.listing_search,
        AgentName.neighborhood,
        AgentName.commute,
        AgentName.budget,
        AgentName.risk,
    }
    for agent in ep.selected_agents:
        assert agent in ep.per_agent_goals, f"{agent} missing from per_agent_goals"
    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "planner"
    assert result["trace"][0].input_tokens == 120
    assert result["trace"][0].output_tokens == 80


# ---------------------------------------------------------------------------
# Scenario 2: Minimal request → only listing_search + budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_minimal_request_selects_two_agents() -> None:
    """'Show me anything under $1,200 near downtown' → listing_search + budget only."""
    plan = ExecutionPlan(
        selected_agents=[
            AgentName.listing_search,
            AgentName.budget,
        ],
        reasoning=(
            "The user has only a price constraint. listing_search fetches candidates "
            "and budget confirms affordability. No commute, safety, or amenity constraints "
            "mentioned, so neighborhood, commute, and risk are skipped."
        ),
        per_agent_goals={
            AgentName.listing_search: "Find all listings under $1,200 near downtown Austin.",
            AgentName.budget: "Verify each listing is within the $1,200 monthly budget.",
        },
    )

    state = _make_state(
        budget_max=1200,
        anchor_address="Downtown Austin, TX",
        free_text="Show me anything under $1,200 near downtown, no other preferences.",
    )

    with patch(
        "src.agents.planner.complete", new=AsyncMock(return_value=_mock_tool_response(plan))
    ):
        result = await run_planner(state)

    ep = result["execution_plan"]
    assert ep is not None
    assert set(ep.selected_agents) == {AgentName.listing_search, AgentName.budget}
    for agent in ep.selected_agents:
        assert agent in ep.per_agent_goals
    assert len(result["trace"]) == 1


# ---------------------------------------------------------------------------
# Scenario 3: Partial request → listing_search + neighborhood + risk (not commute/budget)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_partial_request_selects_safety_agents() -> None:
    """Budget + safety concern, no commute/amenities → listing_search + neighborhood + risk."""
    plan = ExecutionPlan(
        selected_agents=[
            AgentName.listing_search,
            AgentName.neighborhood,
            AgentName.risk,
        ],
        reasoning=(
            "The user has a budget and safety concerns but no commute or amenity constraints. "
            "neighborhood assesses area safety, risk flags suspicious pricing. "
            "commute is skipped (no time constraint), budget is skipped (no affordability analysis "
            "requested beyond the listing_search price filter)."
        ),
        per_agent_goals={
            AgentName.listing_search: "Retrieve listings under $850 in Austin.",
            AgentName.neighborhood: "Evaluate safety and noise for each candidate.",
            AgentName.risk: "Identify any listings with unusual pricing or risk signals.",
        },
    )

    state = _make_state(
        budget_max=850,
        anchor_address="Austin, TX",
        free_text="I'm concerned about safety and want a quiet area. No commute constraints.",
    )

    with patch(
        "src.agents.planner.complete", new=AsyncMock(return_value=_mock_tool_response(plan))
    ):
        result = await run_planner(state)

    ep = result["execution_plan"]
    assert ep is not None
    assert set(ep.selected_agents) == {
        AgentName.listing_search,
        AgentName.neighborhood,
        AgentName.risk,
    }
    assert AgentName.commute not in ep.selected_agents
    assert AgentName.budget not in ep.selected_agents
    for agent in ep.selected_agents:
        assert agent in ep.per_agent_goals
    assert len(result["trace"]) == 1
