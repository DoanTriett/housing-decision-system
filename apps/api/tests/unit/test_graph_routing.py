"""Unit tests for LangGraph routing — all agents mocked."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.graph import Providers, build_graph
from src.agents.state import AgentState
from src.schemas.agents import (
    AgentName,
    AgentTraceEvent,
    CriticReview,
    ExecutionPlan,
    ListingCandidate,
    RankedListing,
    RecommendationOutput,
    UserHousingRequest,
)
from src.tools.listings_repo import ListingsProvider
from src.tools.maps import CommuteProvider
from src.tools.vector_search import VectorSearchProvider


class _DummyListings(ListingsProvider):
    async def search(self, filters: Any) -> list[ListingCandidate]:  # noqa: ARG002
        return []


class _DummyVector(VectorSearchProvider):
    async def search(self, query: str, top_k: int) -> list[Any]:  # noqa: ARG002
        return []


class _DummyCommute(CommuteProvider):
    async def get_walk_minutes(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> float:  # noqa: ARG002
        return 10.0


def _providers() -> Providers:
    return Providers(
        listings=_DummyListings(),
        vector=_DummyVector(),
        commute=_DummyCommute(),
    )


def _trace(name: str) -> AgentTraceEvent:
    now = datetime.now(tz=UTC)
    return AgentTraceEvent(
        agent_name=name,
        started_at=now,
        finished_at=now,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )


def _candidate() -> ListingCandidate:
    return ListingCandidate(
        id="listing-1",
        title="Test",
        address="1 Main",
        neighborhood="Hyde Park",
        price_monthly=1000,
        beds=1,
        has_laundry=True,
        is_pet_friendly=False,
        lat=30.3,
        lon=-97.7,
    )


def _base_state() -> AgentState:
    return AgentState(
        request_id="unit-graph-001",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="Austin, TX",
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


def _plan(*names: AgentName) -> ExecutionPlan:
    return ExecutionPlan(
        selected_agents=list(names),
        reasoning="unit test plan",
        per_agent_goals={n: f"goal for {n.value}" for n in names},
    )


async def _passthrough_planner(state: AgentState, plan: ExecutionPlan) -> AgentState:
    return AgentState(
        **{**state, "execution_plan": plan, "trace": [*state["trace"], _trace("planner")]}
    )


async def _passthrough_listing(state: AgentState, *_args: Any) -> AgentState:
    return AgentState(
        **{
            **state,
            "candidates": [_candidate()],
            "trace": [*state["trace"], _trace("listing_search")],
        }
    )


async def _passthrough_budget(state: AgentState) -> AgentState:
    return AgentState(
        **{**state, "budget_analysis": {}, "trace": [*state["trace"], _trace("budget")]}
    )


async def _passthrough_neighborhood(state: AgentState, *_args: Any) -> AgentState:
    return AgentState(
        **{
            **state,
            "neighborhood_findings": {},
            "trace": [*state["trace"], _trace("neighborhood")],
        }
    )


async def _passthrough_commute(state: AgentState, *_args: Any) -> AgentState:
    return AgentState(
        **{**state, "commute_results": {}, "trace": [*state["trace"], _trace("commute")]}
    )


async def _passthrough_risk(state: AgentState) -> AgentState:
    return AgentState(**{**state, "risk_flags": {}, "trace": [*state["trace"], _trace("risk")]})


async def _passthrough_recommendation(state: AgentState) -> AgentState:
    rec = RecommendationOutput(
        ranked_listings=[
            RankedListing(listing_id="listing-1", rank=1, score=0.0, rationale="stub")
        ],
        trade_off_narrative="Recommendation agent not yet implemented",
    )
    return AgentState(
        **{
            **state,
            "recommendation": rec,
            "trace": [*state["trace"], _trace("recommendation")],
        }
    )


@pytest.mark.asyncio
async def test_only_selected_specialists_appear_in_trace() -> None:
    """Planner selecting listing_search + budget must not run neighborhood/risk/etc."""
    plan = _plan(AgentName.listing_search, AgentName.budget)

    async def planner(state: AgentState) -> AgentState:
        return await _passthrough_planner(state, plan)

    async def critic(state: AgentState) -> AgentState:
        review = CriticReview(approved=True, issues=[], retry_agent=None)
        return AgentState(
            **{
                **state,
                "critic_notes": review,
                "trace": [*state["trace"], _trace("critic")],
            }
        )

    graph = build_graph(_providers())

    with (
        patch("src.agents.graph.run_planner", new=planner),
        patch("src.agents.graph.run_listing_search", new=_passthrough_listing),
        patch("src.agents.graph.run_budget", new=_passthrough_budget),
        patch(
            "src.agents.graph.run_neighborhood",
            new=AsyncMock(side_effect=AssertionError("neighborhood must not run")),
        ),
        patch(
            "src.agents.graph.run_commute",
            new=AsyncMock(side_effect=AssertionError("commute must not run")),
        ),
        patch(
            "src.agents.graph.run_risk",
            new=AsyncMock(side_effect=AssertionError("risk must not run")),
        ),
        patch("src.agents.graph.run_critic", new=critic),
        patch("src.agents.graph.run_recommendation", new=_passthrough_recommendation),
    ):
        result = await graph.ainvoke(_base_state())

    names = [e.agent_name for e in result["trace"]]
    assert names == [
        "planner",
        "listing_search",
        "budget",
        "critic",
        "recommendation",
    ]


@pytest.mark.asyncio
async def test_critic_rejection_reruns_named_agent() -> None:
    """approved=False + retry_agent=neighborhood + retry_count=0 re-runs neighborhood."""
    plan = _plan(AgentName.listing_search, AgentName.neighborhood)
    neighborhood_calls = {"n": 0}
    critic_calls = {"n": 0}

    async def planner(state: AgentState) -> AgentState:
        return await _passthrough_planner(state, plan)

    async def neighborhood(state: AgentState, *_args: Any) -> AgentState:
        neighborhood_calls["n"] += 1
        return await _passthrough_neighborhood(state)

    async def critic(state: AgentState) -> AgentState:
        critic_calls["n"] += 1
        if critic_calls["n"] == 1:
            review = CriticReview(
                approved=False,
                issues=["Need better neighborhood coverage"],
                retry_agent=AgentName.neighborhood,
            )
        else:
            review = CriticReview(approved=True, issues=[], retry_agent=None)
        return AgentState(
            **{
                **state,
                "critic_notes": review,
                "trace": [*state["trace"], _trace("critic")],
            }
        )

    graph = build_graph(_providers())

    with (
        patch("src.agents.graph.run_planner", new=planner),
        patch("src.agents.graph.run_listing_search", new=_passthrough_listing),
        patch("src.agents.graph.run_neighborhood", new=neighborhood),
        patch("src.agents.graph.run_critic", new=critic),
        patch("src.agents.graph.run_recommendation", new=_passthrough_recommendation),
    ):
        result = await graph.ainvoke(_base_state())

    assert neighborhood_calls["n"] == 2
    assert critic_calls["n"] == 2
    assert result["retry_count"] == 1
    names = [e.agent_name for e in result["trace"]]
    assert names.count("neighborhood") == 2
    assert names[-1] == "recommendation"


@pytest.mark.asyncio
async def test_retry_cap_proceeds_to_recommendation() -> None:
    """When retry_count is already 1, graph proceeds to recommendation even if
    Critic returns approved=False (router cap — does not loop).
    """
    plan = _plan(AgentName.listing_search, AgentName.budget)
    budget_calls = {"n": 0}

    async def planner(state: AgentState) -> AgentState:
        return await _passthrough_planner(state, plan)

    async def budget(state: AgentState) -> AgentState:
        budget_calls["n"] += 1
        return await _passthrough_budget(state)

    async def critic(state: AgentState) -> AgentState:
        # Intentionally reject even at retry_count=1 to prove the *router* caps.
        review = CriticReview(
            approved=False,
            issues=["still unhappy"],
            retry_agent=AgentName.budget,
        )
        return AgentState(
            **{
                **state,
                "critic_notes": review,
                "trace": [*state["trace"], _trace("critic")],
            }
        )

    graph = build_graph(_providers())
    initial = AgentState(**{**_base_state(), "retry_count": 1})

    with (
        patch("src.agents.graph.run_planner", new=planner),
        patch("src.agents.graph.run_listing_search", new=_passthrough_listing),
        patch("src.agents.graph.run_budget", new=budget),
        patch("src.agents.graph.run_critic", new=critic),
        patch("src.agents.graph.run_recommendation", new=_passthrough_recommendation),
    ):
        result = await graph.ainvoke(initial)

    assert budget_calls["n"] == 1  # no second budget run
    assert result["retry_count"] == 1
    assert [e.agent_name for e in result["trace"]][-1] == "recommendation"


@pytest.mark.asyncio
async def test_retry_then_cap_when_critic_keeps_rejecting() -> None:
    """First reject triggers one budget retry; second critic still rejecting is capped
    by prepare_retry bumping retry_count so route_after_critic goes to recommendation.

    Note: run_critic itself force-approves at retry_count>=1; this test uses a mock
    critic that ignores that to prove the *graph router* also caps retries.
    """
    plan = _plan(AgentName.listing_search, AgentName.budget)
    budget_calls = {"n": 0}
    critic_calls = {"n": 0}

    async def planner(state: AgentState) -> AgentState:
        return await _passthrough_planner(state, plan)

    async def budget(state: AgentState) -> AgentState:
        budget_calls["n"] += 1
        return await _passthrough_budget(state)

    async def critic(state: AgentState) -> AgentState:
        critic_calls["n"] += 1
        review = CriticReview(
            approved=False,
            issues=["always reject"],
            retry_agent=AgentName.budget,
        )
        return AgentState(
            **{
                **state,
                "critic_notes": review,
                "trace": [*state["trace"], _trace("critic")],
            }
        )

    graph = build_graph(_providers())

    with (
        patch("src.agents.graph.run_planner", new=planner),
        patch("src.agents.graph.run_listing_search", new=_passthrough_listing),
        patch("src.agents.graph.run_budget", new=budget),
        patch("src.agents.graph.run_critic", new=critic),
        patch("src.agents.graph.run_recommendation", new=_passthrough_recommendation),
    ):
        result = await graph.ainvoke(_base_state())

    assert budget_calls["n"] == 2
    assert critic_calls["n"] == 2
    assert result["retry_count"] == 1
    assert [e.agent_name for e in result["trace"]][-1] == "recommendation"
