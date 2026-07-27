"""LLM-as-judge for recommendation quality (Day 13)."""

from __future__ import annotations

import json
from typing import Any

from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import LLMError
from src.schemas.agents import RecommendationOutput, UserHousingRequest

JUDGE_SYSTEM_PROMPT = """\
You are an exacting evaluation judge for a multi-agent housing recommender.

Score the recommendation from 0–5 using BOTH criteria below. Your score must \
reflect the weaker of the two (a vivid narrative that invents facts is still low).

## Criteria
(a) Explanation quality (0–5): Is the trade-off narrative clear, specific, and \
useful for deciding between the ranked listings? Vague praise without concrete \
trade-offs scores low.
(b) Faithfulness (0–5): Every concrete claim in the ranked rationales and \
trade-off narrative must be supported by the provided raw agent findings \
(commute minutes, safety scores, budget %, risk flags, listing attributes). \
Invented numbers, agents that did not run, or contradictions score low.

## Rules
- Check specific claims against the raw findings JSON — do not grade on vibes.
- If an agent did not run, the recommendation must not invent that agent's \
findings.
- Return ONLY via the submit_judge_score tool.
"""

_SUBMIT_JUDGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_judge_score",
        "description": "Submit the 0–5 quality score and short reasoning.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5,
                    "description": "Overall quality score (weaker of explanation vs faithfulness).",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "2–5 sentences citing specific claims checked against raw findings."
                    ),
                },
            },
            "required": ["score", "reasoning"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_judge_score"},
}


def _findings_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Serialize specialist findings for the judge (no LLM-invented fields)."""

    def dump_map(mapping: dict[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in (mapping or {}).items():
            if hasattr(value, "model_dump"):
                out[key] = value.model_dump(mode="json")
            else:
                out[key] = value
        return out

    candidates = state.get("candidates") or []
    return {
        "candidates": [
            c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in candidates
        ],
        "commute_results": dump_map(state.get("commute_results")),
        "neighborhood_findings": dump_map(state.get("neighborhood_findings")),
        "budget_analysis": dump_map(state.get("budget_analysis")),
        "risk_flags": dump_map(state.get("risk_flags")),
        "execution_plan": (
            state["execution_plan"].model_dump(mode="json")
            if state.get("execution_plan") is not None
            and hasattr(state["execution_plan"], "model_dump")
            else None
        ),
    }


async def judge_recommendation(
    request: UserHousingRequest,
    recommendation: RecommendationOutput,
    state: dict[str, Any],
) -> tuple[int, str, float]:
    """Return (score, reasoning, cost_usd)."""
    user_payload = {
        "user_request": request.model_dump(mode="json"),
        "recommendation": recommendation.model_dump(mode="json"),
        "raw_agent_findings": _findings_payload(state),
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Evaluate this housing recommendation. Check faithfulness against "
                "raw_agent_findings only.\n\n" + json.dumps(user_payload, indent=2, default=str)
            ),
        },
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.planner_model,
            tools=[_SUBMIT_JUDGE_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        return 0, f"judge_failed: {exc}", 0.0

    if not response.tool_calls:
        return 0, "judge_failed: no tool call", response.cost_usd

    raw_args = getattr(response.tool_calls[0].function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
        score = int(args["score"])
        reasoning = str(args.get("reasoning") or "")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return 0, f"judge_failed: parse error {exc}", response.cost_usd

    score = max(0, min(5, score))
    return score, reasoning, float(response.cost_usd)
