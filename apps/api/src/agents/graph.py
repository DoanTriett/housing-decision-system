"""LangGraph StateGraph wiring for the multi-agent housing decision flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.budget import run_budget
from src.agents.commute import run_commute
from src.agents.critic import run_critic
from src.agents.listing_search import run_listing_search
from src.agents.neighborhood import run_neighborhood
from src.agents.planner import run_planner
from src.agents.recommendation import run_recommendation
from src.agents.risk import run_risk
from src.agents.state import AgentState
from src.tools.listings_repo import ListingsProvider
from src.tools.maps import CommuteProvider
from src.tools.vector_search import VectorSearchProvider

# Specialist agents that can run in parallel after listing_search (or alone).
_PARALLEL_SPECIALISTS = ("neighborhood", "commute", "budget", "risk")


@dataclass(frozen=True)
class Providers:
    """Injectable tool providers for graph nodes (keeps the graph testable)."""

    listings: ListingsProvider
    vector: VectorSearchProvider
    commute: CommuteProvider


def _trace_delta(result: AgentState) -> list[Any]:
    """Return only the newest trace event so the Annotated reducer does not duplicate."""
    return [result["trace"][-1]]


def _selected_agent_names(state: AgentState) -> list[str]:
    plan = state["execution_plan"]
    if plan is None:
        return []
    return [agent.value for agent in plan.selected_agents]


def route_after_planner(state: AgentState) -> str | list[str]:
    """Send listing_search first when selected; otherwise fan-out parallel specialists.

    Listing Search must populate ``candidates`` before other specialists run. Agents
    not in ``execution_plan.selected_agents`` are never routed to.
    """
    selected = _selected_agent_names(state)
    if "listing_search" in selected:
        return "listing_search"
    parallel = [name for name in selected if name in _PARALLEL_SPECIALISTS]
    if not parallel:
        return "critic"
    return parallel


def route_after_listing_search(state: AgentState) -> str | list[str]:
    """Fan-out remaining selected specialists, or go straight to critic if none."""
    selected = _selected_agent_names(state)
    parallel = [name for name in selected if name in _PARALLEL_SPECIALISTS]
    if not parallel:
        return "critic"
    return parallel


def route_after_critic(state: AgentState) -> str:
    """Approve → recommendation; else one bounded retry of the named specialist."""
    notes = state["critic_notes"]
    if notes is not None and notes.approved:
        return "recommendation"
    if state["retry_count"] < 1 and notes is not None and notes.retry_agent is not None:
        return "prepare_retry"
    return "recommendation"


def route_retry_target(state: AgentState) -> str:
    """Route to the single specialist named by the Critic (dynamic, not hardcoded).

    ``listing_search`` retries use a dedicated node that edges only to ``critic``,
    so a retry does not re-fan-out the other specialists.
    """
    notes = state["critic_notes"]
    assert notes is not None and notes.retry_agent is not None
    name = notes.retry_agent.value
    if name == "listing_search":
        return "listing_search_retry"
    return name


def build_graph(
    providers: Providers,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile the housing decision graph with providers (+ optional checkpointer)."""
    listings_provider = providers.listings
    vector_provider = providers.vector
    commute_provider = providers.commute

    async def planner_node(state: AgentState) -> dict[str, Any]:
        result = await run_planner(state)
        return {
            "execution_plan": result["execution_plan"],
            "trace": _trace_delta(result),
        }

    async def listing_search_node(state: AgentState) -> dict[str, Any]:
        result = await run_listing_search(state, listings_provider)
        return {
            "candidates": result["candidates"],
            "trace": _trace_delta(result),
        }

    async def neighborhood_node(state: AgentState) -> dict[str, Any]:
        result = await run_neighborhood(state, vector_provider)
        return {
            "neighborhood_findings": result["neighborhood_findings"],
            "trace": _trace_delta(result),
        }

    async def commute_node(state: AgentState) -> dict[str, Any]:
        result = await run_commute(state, commute_provider)
        return {
            "commute_results": result["commute_results"],
            "trace": _trace_delta(result),
        }

    async def budget_node(state: AgentState) -> dict[str, Any]:
        result = await run_budget(state)
        return {
            "budget_analysis": result["budget_analysis"],
            "trace": _trace_delta(result),
        }

    async def risk_node(state: AgentState) -> dict[str, Any]:
        result = await run_risk(state)
        return {
            "risk_flags": result["risk_flags"],
            "trace": _trace_delta(result),
        }

    async def critic_node(state: AgentState) -> dict[str, Any]:
        result = await run_critic(state)
        return {
            "critic_notes": result["critic_notes"],
            "trace": _trace_delta(result),
        }

    async def prepare_retry_node(state: AgentState) -> dict[str, Any]:
        # Increment before the specialist re-runs so the next Critic sees retry_count=1.
        return {"retry_count": state["retry_count"] + 1}

    async def recommendation_node(state: AgentState) -> dict[str, Any]:
        result = await run_recommendation(state)
        return {
            "recommendation": result["recommendation"],
            "trace": _trace_delta(result),
        }

    builder: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(
        AgentState
    )

    builder.add_node("planner", planner_node)
    builder.add_node("listing_search", listing_search_node)
    # Same runner as listing_search, but edges only to critic (bounded retry path).
    builder.add_node("listing_search_retry", listing_search_node)
    builder.add_node("neighborhood", neighborhood_node)
    builder.add_node("commute", commute_node)
    builder.add_node("budget", budget_node)
    builder.add_node("risk", risk_node)
    builder.add_node("critic", critic_node)
    builder.add_node("prepare_retry", prepare_retry_node)
    builder.add_node("recommendation", recommendation_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_after_planner)
    builder.add_conditional_edges("listing_search", route_after_listing_search)
    builder.add_edge("listing_search_retry", "critic")

    for name in _PARALLEL_SPECIALISTS:
        builder.add_edge(name, "critic")

    builder.add_conditional_edges("critic", route_after_critic)
    builder.add_conditional_edges("prepare_retry", route_retry_target)
    builder.add_edge("recommendation", END)

    return builder.compile(checkpointer=checkpointer)
