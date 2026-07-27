"""Critic agent — reviews full state; may request one bounded specialist retry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import CriticError, LLMError
from src.llm.prompts.critic import CRITIC_SYSTEM_PROMPT
from src.schemas.agents import AgentName, AgentTraceEvent, CriticReview

logger = structlog.get_logger(__name__)

_SUBMIT_CRITIC_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_critic_review",
        "description": "Submit the critic approval decision and optional retry target.",
        "parameters": {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
                "retry_agent": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": [a.value for a in AgentName],
                        },
                        {"type": "null"},
                    ],
                },
            },
            "required": ["approved", "issues"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_critic_review"},
}


def _summarize_state(state: AgentState) -> str:
    req = state["user_request"]
    lines = [
        "USER REQUEST:",
        f"  budget_max={req.budget_max}",
        f"  anchor={req.anchor_address}",
        f"  max_commute_minutes={req.max_commute_minutes}",
        f"  requires_laundry={req.requires_laundry}",
        f"  requires_pet_friendly={req.requires_pet_friendly}",
        f"  free_text={req.free_text!r}",
        f"retry_count={state['retry_count']}",
        "",
        "SPECIALIST OUTPUTS:",
        f"  candidates={len(state['candidates'])}",
    ]
    if state["execution_plan"]:
        lines.append(
            "  selected_agents=" + str([a.value for a in state["execution_plan"].selected_agents])
        )
    if state["budget_analysis"]:
        affordable = sum(1 for a in state["budget_analysis"].values() if a.is_affordable)
        lines.append(f"  budget: {len(state['budget_analysis'])} analyses, {affordable} affordable")
    if state["neighborhood_findings"]:
        lines.append(f"  neighborhood: {len(state['neighborhood_findings'])} assessments")
        for lid, nb in list(state["neighborhood_findings"].items())[:3]:
            lines.append(f"    {lid[:8]}… safety={nb.safety_score} noise={nb.noise_score}")
    if state["commute_results"]:
        meeting = sum(1 for c in state["commute_results"].values() if c.meets_constraint)
        lines.append(
            f"  commute: {len(state['commute_results'])} results, {meeting} meet constraint"
        )
    if state["risk_flags"]:
        high = sum(1 for r in state["risk_flags"].values() if r.risk_level == "high")
        lines.append(f"  risk: {len(state['risk_flags'])} assessments, {high} high")
    return "\n".join(lines)


async def run_critic(state: AgentState) -> AgentState:
    """Review accumulated specialist output; enforce retry cap in code."""
    started_at = datetime.now(tz=UTC)

    # Bounded retry: if we already used our one retry, always approve.
    if state["retry_count"] >= 1:
        review = CriticReview(
            approved=True,
            issues=["Retry limit reached; proceeding with current state."],
            retry_agent=None,
        )
        finished_at = datetime.now(tz=UTC)
        trace_event = AgentTraceEvent(
            agent_name="critic",
            started_at=started_at,
            finished_at=finished_at,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        logger.info(
            "critic_forced_approve",
            request_id=state["request_id"],
            retry_count=state["retry_count"],
        )
        return AgentState(
            **{
                **state,
                "critic_notes": review,
                "trace": [*state["trace"], trace_event],
            }
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": _summarize_state(state)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.planner_model,
            tools=[_SUBMIT_CRITIC_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise CriticError(f"LLM call failed in critic: {exc}", cause=exc) from exc

    if not response.tool_calls:
        raise CriticError("Critic returned no tool calls")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_critic_review":
        raise CriticError(f"Critic called unexpected tool: {fn_name!r}")

    raw_args = getattr(tool_call.function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise CriticError(f"Critic returned invalid JSON: {exc}") from exc

    # Normalize null retry_agent
    if args.get("retry_agent") in ("", "null", None):
        args["retry_agent"] = None

    try:
        review = CriticReview.model_validate(args)
    except Exception as exc:
        raise CriticError(f"CriticReview validation failed: {exc}") from exc

    if not review.approved and review.retry_agent is None:
        # Can't retry without a target — treat as approve to avoid stalling
        review = CriticReview(
            approved=True,
            issues=[*review.issues, "No retry_agent provided; approving."],
            retry_agent=None,
        )

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="critic",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )

    logger.info(
        "critic_done",
        request_id=state["request_id"],
        approved=review.approved,
        retry_agent=review.retry_agent.value if review.retry_agent else None,
        issues=len(review.issues),
        cost_usd=round(response.cost_usd, 6),
    )

    return AgentState(
        **{
            **state,
            "critic_notes": review,
            "trace": [*state["trace"], trace_event],
        }
    )
