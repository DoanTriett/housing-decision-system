"""Metric helpers for the Day 13 evaluation harness."""

from __future__ import annotations

from typing import Any

from src.agents.recommendation import compute_hard_constraint_violations
from src.agents.state import AgentState
from src.schemas.agents import AgentName, ListingCandidate


def routing_prf(
    predicted: list[str],
    expected: list[str],
) -> tuple[float, float, float]:
    """Precision, recall, F1 over agent-name sets."""
    pred = set(predicted)
    exp = set(expected)
    if not pred and not exp:
        return 1.0, 1.0, 1.0
    if not pred or not exp:
        return 0.0, 0.0, 0.0
    tp = len(pred & exp)
    precision = tp / len(pred)
    recall = tp / len(exp)
    if precision + recall == 0:
        return 0.0, 0.0, 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def top_listing(state: AgentState) -> ListingCandidate | None:
    rec = state.get("recommendation")
    if rec is None or not rec.ranked_listings:
        return None
    ranked = sorted(rec.ranked_listings, key=lambda r: r.rank)
    top_id = ranked[0].listing_id
    for candidate in state.get("candidates") or []:
        if candidate.id == top_id:
            return candidate
    return None


def top_satisfies_hard_constraints(state: AgentState) -> bool | None:
    """Whether the #1 ranked listing satisfies all stated hard constraints.

    Returns None when there is no recommendation / no candidates (pipeline failure).
    """
    candidate = top_listing(state)
    if candidate is None:
        return None
    violations = compute_hard_constraint_violations(state, candidate)
    # Also enforce budget from the listing itself even if budget agent skipped.
    req = state["user_request"]
    if candidate.price_monthly > req.budget_max:
        return False
    return len(violations) == 0


def constraint_match(
    actual_satisfied: bool | None,
    expects_satisfied: bool,
) -> bool:
    """Match system behavior to labeled expectation.

    - expects True → actual must be True
    - expects False → actual must be False or None (honest empty/failure is OK)
    """
    if expects_satisfied:
        return actual_satisfied is True
    return actual_satisfied is not True


def agent_names_from_plan(state: AgentState) -> list[str]:
    plan = state.get("execution_plan")
    if plan is None:
        return []
    return [a.value if isinstance(a, AgentName) else str(a) for a in plan.selected_agents]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_example_row(row: dict[str, Any]) -> dict[str, Any]:
    """Compact view for reports."""
    return {
        "id": row.get("id"),
        "routing_f1": row.get("routing_f1"),
        "constraint_match": row.get("constraint_match"),
        "judge_score": row.get("judge_score"),
        "error": row.get("error"),
    }
