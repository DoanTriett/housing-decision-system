"""Budget agent — deterministic affordability math + batched LLM explanations."""

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import BudgetError, LLMError
from src.llm.prompts.budget import BUDGET_SYSTEM_PROMPT
from src.schemas.agents import AgentTraceEvent, BudgetAnalysis

logger = structlog.get_logger(__name__)

_SUBMIT_EXPLANATIONS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_budget_explanations",
        "description": ("Submit one plain-language affordability explanation per listing."),
        "parameters": {
            "type": "object",
            "properties": {
                "explanations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "listing_id": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["listing_id", "explanation"],
                    },
                },
            },
            "required": ["explanations"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_budget_explanations"},
}


def _compute_analyses(state: AgentState) -> dict[str, BudgetAnalysis]:
    """Step 1 — pure Python affordability math for every candidate."""
    budget_max = state["user_request"].budget_max
    analyses: dict[str, BudgetAnalysis] = {}

    for candidate in state["candidates"]:
        pct = (candidate.price_monthly / budget_max) * 100
        analyses[candidate.id] = BudgetAnalysis(
            listing_id=candidate.id,
            monthly_cost=candidate.price_monthly,
            pct_of_budget=round(pct, 2),
            is_affordable=candidate.price_monthly <= budget_max,
            explanation="",
        )

    return analyses


def _build_user_message(state: AgentState, analyses: dict[str, BudgetAnalysis]) -> str:
    budget_max = state["user_request"].budget_max
    lines = [f"User monthly budget: ${budget_max:.0f}", "", "Candidates:"]
    for candidate in state["candidates"]:
        analysis = analyses[candidate.id]
        lines.append(
            f"- listing_id={candidate.id} | {candidate.title} | "
            f"${analysis.monthly_cost:.0f}/mo | "
            f"{analysis.pct_of_budget:.1f}% of budget | "
            f"affordable={analysis.is_affordable}"
        )
    return "\n".join(lines)


async def run_budget(state: AgentState) -> AgentState:
    """Compute affordability for each candidate and fill LLM explanations.

    Raises BudgetError if there are no candidates or the LLM call/parsing fails.
    """
    if not state["candidates"]:
        raise BudgetError("Budget agent requires candidates; listing_search must run first")

    started_at = datetime.now(tz=UTC)
    analyses = _compute_analyses(state)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(state, analyses)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.specialist_model,
            tools=[_SUBMIT_EXPLANATIONS_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise BudgetError(f"LLM call failed in budget agent: {exc}", cause=exc) from exc

    if not response.tool_calls:
        raise BudgetError("Budget agent returned no tool calls")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_budget_explanations":
        raise BudgetError(f"Budget agent called unexpected tool: {fn_name!r}")

    raw_args = getattr(tool_call.function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise BudgetError(f"Budget agent returned invalid JSON: {exc}") from exc

    explanations = args.get("explanations", [])
    if not isinstance(explanations, list):
        raise BudgetError("Budget explanations payload is not a list")

    by_id = {
        item["listing_id"]: item["explanation"]
        for item in explanations
        if isinstance(item, dict) and "listing_id" in item and "explanation" in item
    }

    for listing_id, analysis in analyses.items():
        explanation = by_id.get(listing_id)
        if explanation:
            analyses[listing_id] = analysis.model_copy(update={"explanation": explanation})
        else:
            # Fallback so the field is never left empty if the model omits one id
            room = state["user_request"].budget_max - analysis.monthly_cost
            if analysis.is_affordable:
                fallback = (
                    f"At ${analysis.monthly_cost:.0f}/mo this is "
                    f"{analysis.pct_of_budget:.0f}% of your "
                    f"${state['user_request'].budget_max:.0f} budget, "
                    f"leaving ${room:.0f}/month of breathing room."
                )
            else:
                fallback = (
                    f"At ${analysis.monthly_cost:.0f}/mo this is "
                    f"{analysis.pct_of_budget:.0f}% of your "
                    f"${state['user_request'].budget_max:.0f} budget "
                    f"(${abs(room):.0f} over)."
                )
            analyses[listing_id] = analysis.model_copy(update={"explanation": fallback})

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="budget",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )

    logger.info(
        "budget_done",
        request_id=state["request_id"],
        candidates=len(analyses),
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=round(response.cost_usd, 6),
        latency_ms=round(response.latency_ms, 1),
    )

    return AgentState(
        **{
            **state,
            "budget_analysis": analyses,
            "trace": [*state["trace"], trace_event],
        }
    )
