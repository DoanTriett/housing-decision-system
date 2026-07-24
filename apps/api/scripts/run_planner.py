"""Smoke-test: run the Planner against 3 real requests using the live OpenAI API.

Run from apps/api/:
    uv run python scripts/run_planner.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.planner import run_planner
from src.agents.state import AgentState
from src.schemas.agents import UserHousingRequest

REQUESTS = [
    (
        "Request A — full constraints",
        UserHousingRequest(
            budget_max=900,
            anchor_address="2400 Whitis Ave, Austin TX (UT Austin main entrance)",
            max_commute_minutes=20,
            requires_laundry=True,
            requires_pet_friendly=True,
            free_text="I want a safe, quiet neighborhood.",
        ),
        "Expected: all 5 agents",
    ),
    (
        "Request B — minimal",
        UserHousingRequest(
            budget_max=1200,
            anchor_address="Downtown Austin, TX",
            free_text="Show me anything under $1,200 near downtown, no other preferences.",
        ),
        "Expected: listing_search + budget only",
    ),
    (
        "Request C — safety focus, no commute",
        UserHousingRequest(
            budget_max=850,
            anchor_address="Austin, TX",
            free_text=(
                "I want a quiet neighborhood. I'm concerned about safety and "
                "whether some listings that look too cheap might be scams. "
                "No commute constraint — I work from home."
            ),
        ),
        "Expected: listing_search + neighborhood + risk",
    ),
]


def _make_state(req: UserHousingRequest, idx: int) -> AgentState:
    return AgentState(
        request_id=f"smoke-{idx}",
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
    print("=" * 70)
    print("Planner smoke-test — 3 real OpenAI requests")
    print("=" * 70)

    for idx, (label, req, expectation) in enumerate(REQUESTS, 1):
        print(f"\n{'-' * 70}")
        print(f"[{idx}] {label}")
        print(f"    {expectation}")
        print("-" * 70)

        state = _make_state(req, idx)
        result = await run_planner(state)

        plan = result["execution_plan"]
        trace = result["trace"][0]

        assert plan is not None

        print(f"selected_agents : {[a.value for a in plan.selected_agents]}")
        print(f"reasoning       : {plan.reasoning}")
        print("per_agent_goals :")
        for agent, goal in plan.per_agent_goals.items():
            print(f"  {agent:<18}: {goal}")
        print(
            f"trace           : input_tokens={trace.input_tokens}  "
            f"output_tokens={trace.output_tokens}  "
            f"cost_usd=${trace.cost_usd:.6f}  "
            f"latency_ms={trace.finished_at.timestamp() - trace.started_at.timestamp():.0f}s"
        )

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
