"""Neighborhood agent — Qdrant RAG + LLM synthesis per candidate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import LLMError, NeighborhoodError
from src.llm.prompts.neighborhood import NEIGHBORHOOD_SYSTEM_PROMPT
from src.schemas.agents import (
    AgentTraceEvent,
    ListingCandidate,
    NeighborhoodAssessment,
    NeighborhoodDoc,
)
from src.tools.vector_search import VectorSearchProvider

logger = structlog.get_logger(__name__)

_SUBMIT_ASSESSMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_neighborhood_assessment",
        "description": "Submit the neighborhood assessment for one listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "string"},
                "summary": {"type": "string"},
                "safety_score": {"type": "integer", "minimum": 1, "maximum": 5},
                "noise_score": {"type": "integer", "minimum": 1, "maximum": 5},
                "source_docs": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "listing_id",
                "summary",
                "safety_score",
                "noise_score",
                "source_docs",
            ],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_neighborhood_assessment"},
}


def _build_query(state: AgentState) -> str:
    free_text = (state["user_request"].free_text or "").strip()
    if free_text:
        return free_text
    return "safe quiet neighborhood"


def _select_docs_for_candidate(
    docs: list[NeighborhoodDoc], candidate: ListingCandidate
) -> list[NeighborhoodDoc]:
    """Prefer docs matching the candidate neighborhood; else keep top result."""
    target = candidate.neighborhood.casefold()
    matched = [d for d in docs if d.neighborhood.casefold() == target]
    if matched:
        return matched
    return docs[:1] if docs else []


def _build_user_message(candidate: ListingCandidate, docs: list[NeighborhoodDoc]) -> str:
    lines = [
        f"listing_id: {candidate.id}",
        f"candidate neighborhood: {candidate.neighborhood}",
        f"address: {candidate.address}",
        "",
        "Retrieved neighborhood documents:",
    ]
    if not docs:
        lines.append("(none retrieved)")
    else:
        for i, doc in enumerate(docs, 1):
            lines.append(f"--- doc {i}: {doc.neighborhood} (score={doc.score:.3f}) ---")
            lines.append(doc.content)
    return "\n".join(lines)


async def _assess_candidate(
    candidate: ListingCandidate,
    docs: list[NeighborhoodDoc],
) -> tuple[NeighborhoodAssessment, int, int, float]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": NEIGHBORHOOD_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(candidate, docs)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.specialist_model,
            tools=[_SUBMIT_ASSESSMENT_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise NeighborhoodError(
            f"LLM call failed for listing {candidate.id}: {exc}", cause=exc
        ) from exc

    if not response.tool_calls:
        raise NeighborhoodError("Neighborhood agent returned no tool calls")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_neighborhood_assessment":
        raise NeighborhoodError(f"Unexpected tool: {fn_name!r}")

    raw_args = getattr(tool_call.function, "arguments", "{}")
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise NeighborhoodError(f"Invalid JSON from neighborhood LLM: {exc}") from exc

    # Force listing_id to the candidate we are assessing
    args["listing_id"] = candidate.id
    # LLMs occasionally emit 0; clamp into the schema's 1–5 range.
    for score_key in ("safety_score", "noise_score"):
        if score_key in args and args[score_key] is not None:
            try:
                args[score_key] = max(1, min(5, int(args[score_key])))
            except (TypeError, ValueError):
                args[score_key] = 3
    try:
        assessment = NeighborhoodAssessment.model_validate(args)
    except Exception as exc:
        raise NeighborhoodError(f"NeighborhoodAssessment validation failed: {exc}") from exc

    return (
        assessment,
        response.input_tokens,
        response.output_tokens,
        response.cost_usd,
    )


async def run_neighborhood(state: AgentState, provider: VectorSearchProvider) -> AgentState:
    """RAG + LLM assessment for each candidate listing.

    Appends one AgentTraceEvent with summed tokens/cost across all LLM calls.
    """
    if not state["candidates"]:
        raise NeighborhoodError(
            "Neighborhood agent requires candidates; listing_search must run first"
        )

    started_at = datetime.now(tz=UTC)
    query = _build_query(state)
    findings: dict[str, NeighborhoodAssessment] = {}
    total_in = 0
    total_out = 0
    total_cost = 0.0

    for candidate in state["candidates"]:
        retrieved = await provider.search(query, top_k=settings.neighborhood_top_k)
        docs = _select_docs_for_candidate(retrieved, candidate)
        assessment, tin, tout, cost = await _assess_candidate(candidate, docs)
        findings[candidate.id] = assessment
        total_in += tin
        total_out += tout
        total_cost += cost

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="neighborhood",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=total_cost,
    )

    logger.info(
        "neighborhood_done",
        request_id=state["request_id"],
        candidates=len(findings),
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=round(total_cost, 6),
    )

    return AgentState(
        **{
            **state,
            "neighborhood_findings": findings,
            "trace": [*state["trace"], trace_event],
        }
    )
