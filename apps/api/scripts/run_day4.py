"""Day 4 smoke-test: Listing Search (real DB) + Budget (real OpenAI).

Run from apps/api/:
    uv run python scripts/run_day4.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.budget import run_budget
from src.agents.listing_search import run_listing_search
from src.agents.state import AgentState
from src.db.session import AsyncSessionLocal
from src.schemas.agents import UserHousingRequest
from src.tools.listings_repo import DBListingsProvider


def _make_state() -> AgentState:
    return AgentState(
        request_id="day4-smoke",
        user_request=UserHousingRequest(
            budget_max=900,
            anchor_address="2400 Whitis Ave, Austin TX (UT Austin main entrance)",
            max_commute_minutes=20,
            requires_laundry=True,
            requires_pet_friendly=True,
            free_text="I want a safe, quiet neighborhood.",
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
    print("Day 4 smoke-test — Listing Search + Budget")
    print("=" * 70)

    state = _make_state()

    async with AsyncSessionLocal() as session:
        provider = DBListingsProvider(session)

        print("\n[1] Listing Search")
        print("-" * 70)
        state = await run_listing_search(state, provider)

        print(f"candidates found : {len(state['candidates'])}")
        print("top 3:")
        for c in state["candidates"][:3]:
            print(
                f"  - {c.id[:8]}… | ${c.price_monthly:.0f}/mo | "
                f"{c.neighborhood} | laundry={c.has_laundry} | pet={c.is_pet_friendly}"
            )
            print(f"    {c.title} @ {c.address}")

        print("\n[2] Budget Analysis")
        print("-" * 70)
        state = await run_budget(state)

        for listing_id, analysis in list(state["budget_analysis"].items())[:5]:
            print(
                f"  {listing_id[:8]}… | ${analysis.monthly_cost:.0f}/mo | "
                f"{analysis.pct_of_budget:.1f}% of budget | "
                f"affordable={analysis.is_affordable}"
            )
            print(f"    {analysis.explanation}")

        budget_trace = next(t for t in state["trace"] if t.agent_name == "budget")
        print("\n[3] Budget AgentTraceEvent")
        print("-" * 70)
        print(f"  input_tokens  : {budget_trace.input_tokens}")
        print(f"  output_tokens : {budget_trace.output_tokens}")
        print(f"  cost_usd      : ${budget_trace.cost_usd:.6f}")

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
