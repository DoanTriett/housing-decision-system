"""Day 6 smoke-test: full LangGraph run for two contrasting requests.

Run from apps/api/:
    uv run python scripts/run_day6.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as aioredis
from qdrant_client import QdrantClient

from src.agents.graph import Providers, build_graph
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider, ListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider

SMOKE_CANDIDATE_LIMIT = 5
UT_LAT = 30.2849
UT_LON = -97.7341


def _closest_to_ut(candidates: list[ListingCandidate]) -> list[ListingCandidate]:
    def dist(c: ListingCandidate) -> float:
        return (c.lat - UT_LAT) ** 2 + (c.lon - UT_LON) ** 2

    return sorted(candidates, key=dist)[:SMOKE_CANDIDATE_LIMIT]


class _SmokeListingsProvider(ListingsProvider):
    """Wrap DB provider: limit=100 pool, then keep ~5 closest to UT for cost control."""

    def __init__(self, inner: ListingsProvider) -> None:
        self._inner = inner

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        widened = ListingFilters(
            max_price=filters.max_price,
            requires_laundry=filters.requires_laundry,
            requires_pet_friendly=filters.requires_pet_friendly,
            neighborhood=filters.neighborhood,
            limit=max(filters.limit, 100),
        )
        pool = await self._inner.search(widened)
        return _closest_to_ut(pool)


def _initial_state(request_id: str, req: UserHousingRequest) -> AgentState:
    return AgentState(
        request_id=request_id,
        user_request=req,
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


def _print_run(label: str, state: AgentState) -> None:
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)

    plan = state["execution_plan"]
    selected = [a.value for a in plan.selected_agents] if plan else []
    print(f"\nPlanner selected : {selected}")
    if plan:
        print(f"Planner reasoning: {plan.reasoning}")

    trace_names = [e.agent_name for e in state["trace"]]
    print(f"\nTrace agent order: {trace_names}")
    print("\nFull trace:")
    for i, event in enumerate(state["trace"], start=1):
        print(
            f"  [{i}] {event.agent_name:16s}  "
            f"tokens_in={event.input_tokens}  tokens_out={event.output_tokens}  "
            f"cost=${event.cost_usd:.6f}  "
            f"{event.started_at.isoformat()} -> {event.finished_at.isoformat()}"
        )

    notes = state["critic_notes"]
    if notes is None:
        print("\nCritic: (none)")
    else:
        print(f"\nCritic approved={notes.approved}")
        print(f"Critic issues={notes.issues}")
        print(
            f"Critic retry_agent="
            f"{notes.retry_agent.value if notes.retry_agent else None}"
        )
        critic_passes = trace_names.count("critic")
        if critic_passes > 1:
            print(f"Critic passes   : {critic_passes} (retry was triggered)")
        else:
            print("Critic passes   : 1 (first-pass decision)")

    print(f"retry_count      : {state['retry_count']}")

    rec = state["recommendation"]
    print("\nStub recommendation:")
    if rec is None:
        print("  (none)")
    else:
        print(f"  narrative: {rec.trade_off_narrative}")
        for ranked in rec.ranked_listings:
            print(
                f"  rank={ranked.rank} listing={ranked.listing_id[:8]}… "
                f"score={ranked.score} rationale={ranked.rationale!r}"
            )

    total_cost = sum(e.cost_usd for e in state["trace"])
    print(f"\nTotal cost across all agents: ${total_cost:.6f}")


async def main() -> None:
    request_a = UserHousingRequest(
        budget_max=1200,
        anchor_address="University of Texas at Austin, Austin, TX",
        max_commute_minutes=20,
        requires_laundry=False,
        requires_pet_friendly=False,
        free_text="safe and quiet neighborhood, worried about scams",
    )
    request_b = UserHousingRequest(
        budget_max=1200,
        anchor_address="University of Texas at Austin, Austin, TX",
        free_text="just show me options under budget",
    )

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(url=settings.qdrant_url)
    vector_provider = QdrantVectorSearchProvider(
        client=qdrant, collection=settings.qdrant_collection
    )
    commute_provider = GoogleMapsCommuteProvider(
        api_key=settings.google_maps_api_key,
        redis_client=redis_client,
    )

    try:
        async with AsyncSessionLocal() as session:
            providers = Providers(
                listings=_SmokeListingsProvider(DBListingsProvider(session)),
                vector=vector_provider,
                commute=commute_provider,
            )
            graph = build_graph(providers)

            print("Day 6 smoke-test — full LangGraph (Risk + Critic + wiring)")
            state_a = await graph.ainvoke(_initial_state("day6-req-a", request_a))
            _print_run("REQUEST A — commute + quiet + scams", state_a)

            state_b = await graph.ainvoke(_initial_state("day6-req-b", request_b))
            _print_run("REQUEST B — under budget only", state_b)
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
