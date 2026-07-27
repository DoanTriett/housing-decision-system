"""Reproduce Day 12 carry-over: clamp with max_commute_minutes=20.

Confirms that when walk_minutes > 20, recommendation score is <= 0.5.
Also documents that Day 12's 24.9 / score=1.0 case used max=25 (not a regression).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as aioredis
from langgraph.checkpoint.memory import MemorySaver
from qdrant_client import QdrantClient

from src.agents.graph import Providers, build_graph
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal, engine
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider, ListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider

UT_LAT = 30.2849
UT_LON = -97.7341


class _CappedListingsProvider(ListingsProvider):
    def __init__(self, inner: ListingsProvider, limit: int = 8) -> None:
        self._inner = inner
        self._limit = limit

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        widened = filters.model_copy(update={"limit": max(filters.limit, 100)})
        pool = await self._inner.search(widened)

        def dist(c: ListingCandidate) -> float:
            return (c.lat - UT_LAT) ** 2 + (c.lon - UT_LON) ** 2

        return sorted(pool, key=dist)[: self._limit]


def _initial(req: UserHousingRequest) -> AgentState:
    return AgentState(
        request_id=str(uuid.uuid4()),
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


async def main() -> None:
    req = UserHousingRequest(
        budget_max=1400,
        anchor_address="University of Texas at Austin, Austin, TX",
        max_commute_minutes=20,
        requires_laundry=True,
        free_text=None,
    )
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    try:
        await engine.dispose()
        async with AsyncSessionLocal() as session:
            providers = Providers(
                listings=_CappedListingsProvider(DBListingsProvider(session)),
                vector=QdrantVectorSearchProvider(
                    client=qdrant, collection=settings.qdrant_collection
                ),
                commute=GoogleMapsCommuteProvider(
                    api_key=settings.google_maps_api_key,
                    redis_client=redis_client,
                ),
            )
            graph = build_graph(providers, checkpointer=MemorySaver())
            state = await graph.ainvoke(
                _initial(req),
                config={"configurable": {"thread_id": str(uuid.uuid4())}},
            )

        print(
            "selected_agents",
            [a.value for a in (state["execution_plan"].selected_agents or [])]
            if state.get("execution_plan")
            else None,
        )
        print("commute_results:")
        for lid, row in (state.get("commute_results") or {}).items():
            print(f"  {lid[:8]}… walk={row.walk_minutes} meets={row.meets_constraint}")

        rec = state.get("recommendation")
        assert rec is not None, "No recommendation produced"
        print("ranked:")
        for item in rec.ranked_listings:
            commute = (state.get("commute_results") or {}).get(item.listing_id)
            walk = commute.walk_minutes if commute else None
            meets = commute.meets_constraint if commute else None
            print(
                json.dumps(
                    {
                        "rank": item.rank,
                        "score": item.score,
                        "walk_minutes": walk,
                        "meets_constraint": meets,
                        "constraint_flag": item.score <= 0.5,
                        "rationale_snip": item.rationale[:120],
                    }
                )
            )

        violators = [
            item
            for item in rec.ranked_listings
            if (state.get("commute_results") or {}).get(item.listing_id) is not None
            and not state["commute_results"][item.listing_id].meets_constraint
        ]
        assert violators, "Expected at least one commute violator with max=20"
        for item in violators:
            assert item.score <= 0.5, f"Clamp failed for {item.listing_id}: score={item.score}"
        print("CLAMP_OK: all commute violators have score <= 0.5")
        print(
            "DAY12_NOTE: walk=24.9 with max_commute=25 was correctly non-violating "
            "(not a regression)."
        )
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
