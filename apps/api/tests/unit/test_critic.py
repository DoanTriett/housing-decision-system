"""Unit tests for Critic agent — LLM client is mocked; retry cap enforced in code."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.critic import run_critic
from src.agents.state import AgentState
from src.llm.client import LLMResponse
from src.schemas.agents import (
    AgentName,
    ExecutionPlan,
    ListingCandidate,
    UserHousingRequest,
)


def _make_state(*, retry_count: int = 0) -> AgentState:
    return AgentState(
        request_id="unit-critic-001",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="Austin, TX",
            requires_laundry=True,
        ),
        execution_plan=ExecutionPlan(
            selected_agents=[AgentName.listing_search, AgentName.budget],
            reasoning="test",
            per_agent_goals={
                AgentName.listing_search: "find listings",
                AgentName.budget: "check affordability",
            },
        ),
        candidates=[
            ListingCandidate(
                id="a",
                title="A",
                address="1 Main",
                neighborhood="Hyde Park",
                price_monthly=1000,
                beds=1,
                has_laundry=True,
                is_pet_friendly=False,
                lat=30.3,
                lon=-97.7,
            )
        ],
        neighborhood_findings={},
        commute_results={},
        budget_analysis={},
        risk_flags={},
        critic_notes=None,
        retry_count=retry_count,
        recommendation=None,
        trace=[],
    )


def _mock_llm_response(
    *,
    approved: bool,
    issues: list[str],
    retry_agent: str | None,
) -> LLMResponse:
    fn = SimpleNamespace(
        name="submit_critic_review",
        arguments=json.dumps(
            {
                "approved": approved,
                "issues": issues,
                "retry_agent": retry_agent,
            }
        ),
    )
    tool_call = SimpleNamespace(function=fn)
    return LLMResponse(
        content=None,
        tool_calls=[tool_call],
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0001,
        latency_ms=200.0,
        raw=None,
    )


@pytest.mark.asyncio
async def test_critic_approves_when_llm_says_satisfied() -> None:
    state = _make_state()
    with patch(
        "src.agents.critic.complete",
        new=AsyncMock(
            return_value=_mock_llm_response(
                approved=True, issues=[], retry_agent=None
            )
        ),
    ):
        result = await run_critic(state)

    assert result["critic_notes"] is not None
    assert result["critic_notes"].approved is True
    assert result["critic_notes"].retry_agent is None


@pytest.mark.asyncio
async def test_critic_requests_retry_when_llm_finds_gap() -> None:
    state = _make_state()
    with patch(
        "src.agents.critic.complete",
        new=AsyncMock(
            return_value=_mock_llm_response(
                approved=False,
                issues=["Budget analysis missing"],
                retry_agent="budget",
            )
        ),
    ):
        result = await run_critic(state)

    assert result["critic_notes"] is not None
    assert result["critic_notes"].approved is False
    assert result["critic_notes"].retry_agent == AgentName.budget
    assert "Budget analysis missing" in result["critic_notes"].issues


@pytest.mark.asyncio
async def test_critic_force_approves_when_retry_count_is_one() -> None:
    """retry_count=1 always yields approved=True even if LLM would reject."""
    state = _make_state(retry_count=1)
    mock_complete = AsyncMock(
        return_value=_mock_llm_response(
            approved=False,
            issues=["still broken"],
            retry_agent="budget",
        )
    )

    with patch("src.agents.critic.complete", new=mock_complete):
        result = await run_critic(state)

    assert result["critic_notes"] is not None
    assert result["critic_notes"].approved is True
    assert result["critic_notes"].retry_agent is None
    mock_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_trace_event_appended_for_critic() -> None:
    state = _make_state()
    with patch(
        "src.agents.critic.complete",
        new=AsyncMock(
            return_value=_mock_llm_response(
                approved=True, issues=[], retry_agent=None
            )
        ),
    ):
        result = await run_critic(state)

    assert len(result["trace"]) == 1
    assert result["trace"][0].agent_name == "critic"
