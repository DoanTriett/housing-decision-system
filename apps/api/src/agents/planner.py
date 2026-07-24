"""Planner agent — routes a UserHousingRequest to the appropriate specialist agents."""

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import LLMError, PlannerError
from src.llm.prompts.planner import PLANNER_SYSTEM_PROMPT
from src.schemas.agents import AgentName, AgentTraceEvent, ExecutionPlan

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool definition sent to the model
# ---------------------------------------------------------------------------
_SUBMIT_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_execution_plan",
        "description": (
            "Submit the execution plan specifying which specialist agents to run "
            "and the per-agent goals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "selected_agents": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [a.value for a in AgentName],
                    },
                    "description": "List of agent names to execute.",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "2–4 sentence explanation of which agents were selected "
                        "and which were skipped, and why."
                    ),
                },
                "per_agent_goals": {
                    "type": "object",
                    "description": (
                        "One tight action-oriented sentence per selected agent "
                        "describing what it should accomplish."
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["selected_agents", "reasoning", "per_agent_goals"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_execution_plan"},
}


def _build_user_message(state: AgentState) -> str:
    req = state["user_request"]
    parts = [
        f"Structured max_price filter (listing_search only): ${req.budget_max:.0f}",
        f"Anchor address: {req.anchor_address}",
    ]
    if req.max_commute_minutes is not None:
        parts.append(f"Max walking commute: {req.max_commute_minutes} minutes")
    if req.requires_laundry:
        parts.append("Laundry: required")
    if req.requires_pet_friendly:
        parts.append("Pet-friendly: required")
    if req.free_text:
        parts.append(f"User free text (primary signal for agent selection): {req.free_text}")
    else:
        parts.append("User free text: (none)")
    parts.append(
        "Reminder: select budget only if free text discusses a budget/affordability limit; "
        "select commute only if free text or max_commute_minutes states a travel-time constraint."
    )
    return "\n".join(parts)


async def run_planner(state: AgentState) -> AgentState:
    """Call the Planner LLM, parse the ExecutionPlan, and return updated state.

    Appends one AgentTraceEvent to state['trace'] on success.
    Raises PlannerError on any failure to produce a valid plan.
    """
    started_at = datetime.now(tz=UTC)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(state)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.planner_model,
            tools=[_SUBMIT_PLAN_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise PlannerError(f"LLM call failed in planner: {exc}", cause=exc) from exc

    # --- Parse tool call ---
    if not response.tool_calls:
        raise PlannerError("Planner returned no tool calls — expected submit_execution_plan")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_execution_plan":
        raise PlannerError(f"Planner called unexpected tool: {fn_name!r}")

    raw_args = getattr(tool_call.function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Planner returned invalid JSON arguments: {exc}") from exc

    try:
        plan = ExecutionPlan.model_validate(args)
    except Exception as exc:
        raise PlannerError(f"ExecutionPlan validation failed: {exc}") from exc

    finished_at = datetime.now(tz=UTC)

    trace_event = AgentTraceEvent(
        agent_name="planner",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )

    logger.info(
        "planner_done",
        request_id=state["request_id"],
        selected_agents=[a.value for a in plan.selected_agents],
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=round(response.cost_usd, 6),
        latency_ms=round(response.latency_ms, 1),
    )

    return AgentState(**{**state, "execution_plan": plan, "trace": [*state["trace"], trace_event]})
