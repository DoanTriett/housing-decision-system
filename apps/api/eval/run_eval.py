"""Day 13 evaluation harness.

Usage (from apps/api/):
    uv run python eval/run_eval.py
    uv run python eval/run_eval.py --subset eval/ci_subset.txt
    uv run python eval/run_eval.py --ci
    uv run python eval/run_eval.py --limit 5 --skip-judge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import redis.asyncio as aioredis
from langgraph.checkpoint.memory import MemorySaver
from qdrant_client import QdrantClient

from eval.judges import judge_recommendation
from eval.metrics import (
    agent_names_from_plan,
    constraint_match,
    mean,
    routing_prf,
    summarize_example_row,
    top_satisfies_hard_constraints,
)
from src.agents.graph import Providers, build_graph
from src.agents.planner import run_planner
from src.agents.state import AgentState
from src.config import settings
from src.db.session import AsyncSessionLocal, engine
from src.schemas.agents import ListingCandidate, ListingFilters, UserHousingRequest
from src.tools.listings_repo import DBListingsProvider, ListingsProvider
from src.tools.maps import GoogleMapsCommuteProvider
from src.tools.vector_search import QdrantVectorSearchProvider

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "golden_dataset.jsonl"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"
CI_SUBSET_FILE = EVAL_DIR / "ci_subset.txt"

# CI quality gates (tunable). Judgment after first full run: routing is strong (~0.78);
# constraint labels are sensitive to seed geography — start at 0.65, raise as seed improves.
CI_MIN_ROUTING_F1 = 0.70
CI_MIN_CONSTRAINT_MATCH = 0.65

UT_LAT = 30.2849
UT_LON = -97.7341
EVAL_CANDIDATE_LIMIT = 6


class _EvalListingsProvider(ListingsProvider):
    def __init__(self, inner: ListingsProvider, limit: int = EVAL_CANDIDATE_LIMIT) -> None:
        self._inner = inner
        self._limit = limit

    async def search(self, filters: ListingFilters) -> list[ListingCandidate]:
        widened = filters.model_copy(update={"limit": max(filters.limit, 100)})
        pool = await self._inner.search(widened)

        def dist(c: ListingCandidate) -> float:
            return (c.lat - UT_LAT) ** 2 + (c.lon - UT_LON) ** 2

        return sorted(pool, key=dist)[: self._limit]


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _filter_subset(
    rows: list[dict[str, Any]],
    subset_path: Path | None,
    ids: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    if subset_path is not None:
        wanted = {
            line.strip()
            for line in subset_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        rows = [r for r in rows if r["id"] in wanted]
    if ids:
        wanted_ids = set(ids)
        rows = [r for r in rows if r["id"] in wanted_ids]
    if limit is not None:
        rows = rows[:limit]
    return rows


def _initial_state(req: UserHousingRequest) -> AgentState:
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


def _request_from_example(example: dict[str, Any]) -> UserHousingRequest:
    return UserHousingRequest(
        budget_max=float(example["budget_max"]),
        anchor_address=str(example["anchor_address"]),
        max_commute_minutes=example.get("max_commute_minutes"),
        requires_laundry=bool(example.get("requires_laundry", False)),
        requires_pet_friendly=bool(example.get("requires_pet_friendly", False)),
        free_text=example.get("free_text"),
    )


async def _run_one(
    example: dict[str, Any],
    *,
    redis_client: Any,
    qdrant: QdrantClient,
    skip_judge: bool,
) -> dict[str, Any]:
    req = _request_from_example(example)
    row: dict[str, Any] = {
        "id": example["id"],
        "expected_agents": example["expected_agents"],
        "expects_hard_constraint_satisfied": example["expects_hard_constraint_satisfied"],
    }
    cost = 0.0
    try:
        await engine.dispose()
        async with AsyncSessionLocal() as session:
            providers = Providers(
                listings=_EvalListingsProvider(DBListingsProvider(session)),
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
                _initial_state(req),
                config={"configurable": {"thread_id": str(uuid.uuid4())}},
            )

        for event in state.get("trace") or []:
            cost += float(getattr(event, "cost_usd", 0.0) or 0.0)

        predicted = agent_names_from_plan(state)
        precision, recall, f1 = routing_prf(predicted, list(example["expected_agents"]))
        actual_ok = top_satisfies_hard_constraints(state)
        matched = constraint_match(actual_ok, bool(example["expects_hard_constraint_satisfied"]))

        judge_score: int | None = None
        judge_reasoning: str | None = None
        if not skip_judge and state.get("recommendation") is not None:
            judge_score, judge_reasoning, judge_cost = await judge_recommendation(
                req,
                state["recommendation"],
                state,
            )
            cost += judge_cost

        row.update(
            {
                "predicted_agents": predicted,
                "routing_precision": precision,
                "routing_recall": recall,
                "routing_f1": f1,
                "actual_constraint_satisfied": actual_ok,
                "constraint_match": matched,
                "judge_score": judge_score,
                "judge_reasoning": judge_reasoning,
                "recommendation": (
                    state["recommendation"].model_dump(mode="json")
                    if state.get("recommendation") is not None
                    else None
                ),
                "cost_usd": round(cost, 6),
                "error": None,
            }
        )
    except Exception as exc:
        # Still score routing via a planner-only call when the full graph fails
        # (e.g. empty listing search on impossible budgets).
        predicted: list[str] = []
        precision = recall = f1 = 0.0
        try:
            plan_state = await run_planner(_initial_state(req))
            predicted = agent_names_from_plan(plan_state)
            precision, recall, f1 = routing_prf(predicted, list(example["expected_agents"]))
            for event in plan_state.get("trace") or []:
                cost += float(getattr(event, "cost_usd", 0.0) or 0.0)
        except Exception:
            pass

        row.update(
            {
                "predicted_agents": predicted,
                "routing_precision": precision,
                "routing_recall": recall,
                "routing_f1": f1,
                "actual_constraint_satisfied": None,
                "constraint_match": constraint_match(
                    None, bool(example["expects_hard_constraint_satisfied"])
                ),
                "judge_score": None,
                "judge_reasoning": None,
                "recommendation": None,
                "cost_usd": round(cost, 6),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    return row


def _print_report(summary: dict[str, Any], examples: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("EVAL REPORT")
    print("=" * 72)
    print(f"examples:              {summary['n_examples']}")
    print(f"routing F1 (mean):     {summary['routing_f1']:.4f}")
    print(f"constraint match rate: {summary['constraint_match_rate']:.4f}")
    print(f"judge score (mean):    {summary['judge_score_mean']}")
    print(f"total cost USD:        {summary['total_cost_usd']:.6f}")
    print(f"wall clock seconds:    {summary['wall_clock_seconds']:.1f}")
    print("-" * 72)
    for row in examples:
        print(json.dumps(summarize_example_row(row), default=str))
    print("=" * 72)


def _write_github_summary(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Eval summary",
        "",
        f"- Examples: **{summary['n_examples']}**",
        f"- Routing F1: **{summary['routing_f1']:.4f}** (gate ≥ {CI_MIN_ROUTING_F1})",
        f"- Constraint match: **{summary['constraint_match_rate']:.4f}** "
        f"(gate ≥ {CI_MIN_CONSTRAINT_MATCH})",
        f"- Judge mean: **{summary['judge_score_mean']}**",
        f"- Cost USD: **{summary['total_cost_usd']}**",
        f"- Wall clock: **{summary['wall_clock_seconds']}s**",
        "",
        "| id | routing_f1 | constraint_match | judge | error |",
        "|---|---:|:---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['routing_f1']:.3f} | {r['constraint_match']} | "
            f"{r.get('judge_score')} | {r.get('error') or ''} |"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_eval(
    dataset_path: Path,
    results_dir: Path,
    *,
    subset_path: Path | None,
    ids: list[str] | None,
    limit: int | None,
    skip_judge: bool,
    fail_under: bool,
) -> int:
    examples = _filter_subset(_load_dataset(dataset_path), subset_path, ids, limit)
    if not examples:
        print("No examples selected.", file=sys.stderr)
        return 2

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    qdrant = QdrantClient(url=settings.qdrant_url)

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    try:
        for example in examples:
            print(f"\n>>> running {example['id']} …")
            row = await _run_one(
                example,
                redis_client=redis_client,
                qdrant=qdrant,
                skip_judge=skip_judge,
            )
            rows.append(row)
            print(
                f"    f1={row['routing_f1']:.3f} "
                f"constraint_match={row['constraint_match']} "
                f"judge={row['judge_score']} err={row['error']}"
            )
    finally:
        await redis_client.aclose()
        await engine.dispose()

    elapsed = time.perf_counter() - started
    f1s = [float(r["routing_f1"]) for r in rows]
    matches = [1.0 if r["constraint_match"] else 0.0 for r in rows]
    judge_scores = [float(r["judge_score"]) for r in rows if r.get("judge_score") is not None]
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in rows)

    summary = {
        "n_examples": len(rows),
        "routing_f1": mean(f1s),
        "constraint_match_rate": mean(matches),
        "judge_score_mean": round(mean(judge_scores), 3) if judge_scores else None,
        "total_cost_usd": round(total_cost, 6),
        "wall_clock_seconds": round(elapsed, 2),
        "ci_min_routing_f1": CI_MIN_ROUTING_F1,
        "ci_min_constraint_match": CI_MIN_CONSTRAINT_MATCH,
        "dataset": str(dataset_path),
        "skip_judge": skip_judge,
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = results_dir / f"{stamp}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "examples": rows}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nWrote {out_path}")
    _print_report(summary, rows)
    _write_github_summary(summary, rows)

    if fail_under:
        if summary["routing_f1"] < CI_MIN_ROUTING_F1:
            print(
                f"FAIL: routing F1 {summary['routing_f1']:.4f} < {CI_MIN_ROUTING_F1}",
                file=sys.stderr,
            )
            return 1
        if summary["constraint_match_rate"] < CI_MIN_CONSTRAINT_MATCH:
            print(
                f"FAIL: constraint match {summary['constraint_match_rate']:.4f} "
                f"< {CI_MIN_CONSTRAINT_MATCH}",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run housing-decision golden eval")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--subset", type=Path, default=None)
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--fail-under", action="store_true")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Shorthand: --subset eval/ci_subset.txt --fail-under",
    )
    args = parser.parse_args()

    subset = args.subset
    fail_under = args.fail_under
    if args.ci:
        subset = CI_SUBSET_FILE
        fail_under = True

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    code = asyncio.run(
        run_eval(
            args.dataset,
            args.results_dir,
            subset_path=subset,
            ids=args.ids,
            limit=args.limit,
            skip_judge=args.skip_judge,
            fail_under=fail_under,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
