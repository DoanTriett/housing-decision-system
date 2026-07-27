"""Day 5 smoke-test: Listing Search + Neighborhood + Commute.

Run from apps/api/:
    uv run python scripts/run_day5.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis.asyncio as aioredis
from qdrant_client import QdrantClient

from src.agents.commute import run_commute
from src.agents.listing_search import run_listing_search
from src.agents.neighborhood import run_neighborhood
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider

# Cap candidates so Neighborhood LLM calls stay affordable for a smoke run.
# Prefer listings geographically closest to UT so the 20-min walk check is meaningful.
SMOKE_CANDIDATE_LIMIT = 5
UT_LAT = 30.2849
UT_LON = -97.7341


def _closest_to_ut(candidates: list[ListingCandidate]) -> list[ListingCandidate]:
    def dist(c: ListingCandidate) -> float:
        return (c.lat - UT_LAT) ** 2 + (c.lon - UT_LON) ** 2

    return sorted(candidates, key=dist)[:SMOKE_CANDIDATE_LIMIT]


def _make_state() -> AgentState:
    return AgentState(
        request_id="day5-smoke",
        user_request=UserHousingRequest(
            budget_max=1200,
            anchor_address="University of Texas at Austin, Austin, TX",
            max_commute_minutes=20,
            free_text="safe and quiet neighborhood",
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


async def main() -> None:
    print("=" * 70)
    print("Day 5 smoke-test — Listing Search + Neighborhood + Commute")
    print("=" * 70)

    state = _make_state()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    vector_provider = QdrantVectorSearchProvider(
        client=qdrant, collection=settings.qdrant_collection
    )
    commute_provider = GoogleMapsCommuteProvider(
        api_key=settings.google_maps_api_key,
        redis_client=redis_client,
    )

    try:
        async with AsyncSessionLocal() as session:
            listings_provider = DBListingsProvider(session)

            print("\n[1] Listing Search")
            print("-" * 70)
            state = await run_listing_search(state, listings_provider)
            # Widen the pool beyond the default top-20-by-price so we can pick
            # listings that are actually walkable to UT for the commute check.
            wide_pool = await listings_provider.search(ListingFilters(max_price=1200, limit=100))
            state = AgentState(**{**state, "candidates": _closest_to_ut(wide_pool)})
            print(
                f"candidates used : {len(state['candidates'])} "
                f"(closest to UT from {len(wide_pool)} under $1200)"
            )
            for c in state["candidates"]:
                print(f"  - {c.id[:8]}… | ${c.price_monthly:.0f}/mo | {c.neighborhood}")

            print("\n[2] Neighborhood")
            print("-" * 70)
            state = await run_neighborhood(state, vector_provider)
            for listing_id, assessment in state["neighborhood_findings"].items():
                print(
                    f"  {listing_id[:8]}… | safety={assessment.safety_score} "
                    f"noise={assessment.noise_score} | sources={assessment.source_docs}"
                )
                print(f"    {assessment.summary}")

            print("\n[3] Commute (first pass — may populate Redis cache)")
            print("-" * 70)
            state = await run_commute(state, commute_provider)
            for listing_id, result in state["commute_results"].items():
                print(
                    f"  {listing_id[:8]}… | walk={result.walk_minutes:.1f} min | "
                    f"meets_constraint={result.meets_constraint}"
                )

            meets = any(r.meets_constraint for r in state["commute_results"].values())
            print(f"\n  any meets 20-min constraint: {meets}")

            nbhd_trace = next(t for t in state["trace"] if t.agent_name == "neighborhood")
            print("\n[4] Neighborhood AgentTraceEvent")
            print("-" * 70)
            print(f"  input_tokens  : {nbhd_trace.input_tokens}")
            print(f"  output_tokens : {nbhd_trace.output_tokens}")
            print(f"  cost_usd      : ${nbhd_trace.cost_usd:.6f}")

            print("\n[5] Commute second pass (should hit Redis cache)")
            print("-" * 70)
            # Reset commute results / last commute trace for a clean second run
            state2 = AgentState(
                **{
                    **state,
                    "commute_results": {},
                    "trace": [t for t in state["trace"] if t.agent_name != "commute"],
                }
            )
            state2 = await run_commute(state2, commute_provider)
            for listing_id, result in state2["commute_results"].items():
                print(
                    f"  {listing_id[:8]}… | walk={result.walk_minutes:.1f} min | "
                    f"meets_constraint={result.meets_constraint}"
                )
            print("  (check logs above for commute_cache_hit messages)")

    finally:
        await redis_client.aclose()

    print(f"\n{'=' * 70}")
    print("Done. Google Maps Directions on free tier ~ $0 for this smoke volume.")


if __name__ == "__main__":
    asyncio.run(main())
