"""Week 1 end-to-end CLI — multi-turn session with checkpointer + UserProfile.

Run from apps/api/:
    uv run python scripts/run_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as aioredis
from qdrant_client import QdrantClient

from src.agents.graph import Providers, build_graph
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal
from src.memory.checkpointer import get_checkpointer
from src.memory.long_term import update_user_profile
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider, ListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider

SMOKE_CANDIDATE_LIMIT = 5
UT_LAT = 30.2849
UT_LON = -97.7341
DEMO_USER_ID = "demo_user"


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


def _print_recommendation(label: str, state: AgentState) -> None:
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)

    plan = state["execution_plan"]
    if plan:
        print(f"Planner selected: {[a.value for a in plan.selected_agents]}")

    print(f"Candidates this turn: {len(state['candidates'])}")
    for c in state["candidates"]:
        print(
            f"  - {c.id[:8]}... ${c.price_monthly:.0f}/mo | {c.neighborhood} | "
            f"laundry={c.has_laundry} pet={c.is_pet_friendly}"
        )

    rec = state["recommendation"]
    print("\nRanked recommendation:")
    if rec is None:
        print("  (none)")
    else:
        for item in rec.ranked_listings:
            print(f"  #{item.rank}  score={item.score:.2f}  listing={item.listing_id[:8]}...")
            print(f"       rationale: {item.rationale}")
        print(f"\nTrade-off narrative:\n  {rec.trade_off_narrative}")

    print("\nPer-agent costs:")
    # Show only events from this turn: after the previous recommendation, if any.
    events = list(state["trace"])
    turn_start = 0
    rec_idxs = [i for i, e in enumerate(events) if e.agent_name == "recommendation"]
    if len(rec_idxs) >= 2:
        turn_start = rec_idxs[-2] + 1
    turn_events = events[turn_start:]
    for event in turn_events:
        print(
            f"  {event.agent_name:16s}  "
            f"in={event.input_tokens} out={event.output_tokens}  "
            f"cost=${event.cost_usd:.6f}"
        )
    turn_cost = sum(e.cost_usd for e in turn_events)
    total_cost = sum(e.cost_usd for e in events)
    print(f"\nTurn cost:  ${turn_cost:.6f}")
    print(f"Session cost (all turns): ${total_cost:.6f}")


async def main() -> None:
    thread_id = str(uuid.uuid4())
    turn1_request_id = str(uuid.uuid4())
    turn2_request_id = str(uuid.uuid4())

    turn1 = UserHousingRequest(
        budget_max=900,
        anchor_address="University of Texas at Austin, Austin, TX",
        max_commute_minutes=20,
        requires_laundry=True,
        requires_pet_friendly=True,
        free_text="safe and quiet neighborhood, worried about scams",
    )
    turn2 = UserHousingRequest(
        budget_max=1200,
        anchor_address="University of Texas at Austin, Austin, TX",
        max_commute_minutes=20,
        requires_laundry=False,
        requires_pet_friendly=False,
        free_text=("actually open to a bigger budget, drop the pet and laundry requirements"),
    )

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    config = {"configurable": {"thread_id": thread_id}}

    print("Week 1 pipeline — Recommendation + session memory + UserProfile")
    print(f"thread_id={thread_id}")

    try:
        async with get_checkpointer() as checkpointer:
            await checkpointer.setup()

            async with AsyncSessionLocal() as session:
                providers = Providers(
                    listings=_SmokeListingsProvider(DBListingsProvider(session)),
                    vector=QdrantVectorSearchProvider(
                        client=qdrant, collection=settings.qdrant_collection
                    ),
                    commute=GoogleMapsCommuteProvider(
                        api_key=settings.google_maps_api_key,
                        redis_client=redis_client,
                    ),
                )
                graph = build_graph(providers, checkpointer=checkpointer)

                print("\n--- TURN 1 ---")
                state1 = await graph.ainvoke(
                    _initial_state(turn1_request_id, turn1),
                    config=config,
                )
                _print_recommendation("TURN 1 — $900, laundry+pet, quiet, scams", state1)

                print("\n--- TURN 2 (same session) ---")
                print(f"Session continued from thread_id={thread_id}")
                state2 = await graph.ainvoke(
                    _initial_state(turn2_request_id, turn2),
                    config=config,
                )
                _print_recommendation(
                    "TURN 2 — $1200, no laundry/pet req, same thread",
                    state2,
                )

                prefs = await update_user_profile(DEMO_USER_ID, state2, session)
                print("\n" + "=" * 70)
                print(f"UserProfile preferences for {DEMO_USER_ID!r}:")
                print(json.dumps(prefs or {}, indent=2))
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    # psycopg async requires SelectorEventLoop on Windows (not ProactorEventLoop).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
