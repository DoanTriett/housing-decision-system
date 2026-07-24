"""Risk agent — rule-based below-market flags + batched LLM risk reasoning."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import LLMError, RiskError
from src.llm.prompts.risk import RISK_SYSTEM_PROMPT
from src.schemas.agents import AgentTraceEvent, ListingCandidate, RiskAssessment

logger = structlog.get_logger(__name__)

_SUBMIT_RISK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_risk_assessments",
        "description": "Submit risk level and reasoning for each listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "assessments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "listing_id": {"type": "string"},
                            "risk_level": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "reasoning": {"type": "string"},
                        },
                        "required": ["listing_id", "risk_level", "reasoning"],
                    },
                },
            },
            "required": ["assessments"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_risk_assessments"},
}


def _rule_flags(candidates: list[ListingCandidate]) -> dict[str, list[str]]:
    """Step 1 — deterministic below-market flags vs median of the candidate set."""
    flags: dict[str, list[str]] = {c.id: [] for c in candidates}
    if len(candidates) < 2:
        return flags

    prices = [c.price_monthly for c in candidates]
    median = statistics.median(prices)
    if median <= 0:
        return flags

    for candidate in candidates:
        pct_below = (median - candidate.price_monthly) / median * 100
        if pct_below > 25:
            flags[candidate.id].append(
                f"price {pct_below:.0f}% below market median"
            )
    return flags


def _build_user_message(
    candidates: list[ListingCandidate], flags: dict[str, list[str]]
) -> str:
    lines = ["Assess risk for each listing:", ""]
    for candidate in candidates:
        lines.append(f"listing_id: {candidate.id}")
        lines.append(f"title: {candidate.title}")
        lines.append(f"price_monthly: ${candidate.price_monthly:.0f}")
        lines.append(f"rule_flags: {flags.get(candidate.id, [])}")
        lines.append(f"description: {candidate.description or '(none)'}")
        lines.append("---")
    return "\n".join(lines)


async def run_risk(state: AgentState) -> AgentState:
    """Flag below-market listings and score scam risk via one batched LLM call."""
    if not state["candidates"]:
        raise RiskError("Risk agent requires candidates; listing_search must run first")

    started_at = datetime.now(tz=UTC)
    candidates = state["candidates"]
    flags = _rule_flags(candidates)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": RISK_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(candidates, flags)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.specialist_model,
            tools=[_SUBMIT_RISK_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise RiskError(f"LLM call failed in risk agent: {exc}", cause=exc) from exc

    if not response.tool_calls:
        raise RiskError("Risk agent returned no tool calls")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_risk_assessments":
        raise RiskError(f"Risk agent called unexpected tool: {fn_name!r}")

    raw_args = getattr(tool_call.function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise RiskError(f"Risk agent returned invalid JSON: {exc}") from exc

    assessments_raw = args.get("assessments", [])
    if not isinstance(assessments_raw, list):
        raise RiskError("Risk assessments payload is not a list")

    by_id: dict[str, dict[str, Any]] = {
        item["listing_id"]: item
        for item in assessments_raw
        if isinstance(item, dict) and "listing_id" in item
    }

    risk_flags: dict[str, RiskAssessment] = {}
    for candidate in candidates:
        item = by_id.get(candidate.id, {})
        raw_level = item.get("risk_level", "low")
        level: Literal["low", "medium", "high"] = (
            raw_level if raw_level in ("low", "medium", "high") else "low"
        )
        # Promote to at least medium when below-market flag fired and LLM said low
        candidate_flags = flags.get(candidate.id, [])
        if candidate_flags and level == "low":
            level = "medium"
        risk_flags[candidate.id] = RiskAssessment(
            listing_id=candidate.id,
            risk_level=level,
            flags=candidate_flags,
            reasoning=str(item.get("reasoning") or "No additional risk signals found."),
        )

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="risk",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )

    logger.info(
        "risk_done",
        request_id=state["request_id"],
        candidates=len(risk_flags),
        flagged=sum(1 for a in risk_flags.values() if a.flags),
        cost_usd=round(response.cost_usd, 6),
    )

    return AgentState(
        **{
            **state,
            "risk_flags": risk_flags,
            "trace": [*state["trace"], trace_event],
        }
    )
