"""Recommendation agent — synthesize ranked top-3 with explicit trade-offs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.exceptions import LLMError, RecommendationError
from src.llm.prompts.recommendation import RECOMMENDATION_SYSTEM_PROMPT
from src.schemas.agents import (
    AgentTraceEvent,
    ListingCandidate,
    RankedListing,
    RecommendationOutput,
)

logger = structlog.get_logger(__name__)

_HARD_CONSTRAINT_SCORE_CAP = 0.5

_SUBMIT_RECOMMENDATION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_recommendation",
        "description": (
            "Submit the ranked top listings and trade-off narrative. "
            "If violates_hard_constraints is non-empty for a candidate, "
            "score must be <= 0.5 and rationale must name the violation "
            "(use the word 'exceeds' for commute/budget violations)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ranked_listings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "listing_id": {"type": "string"},
                            "rank": {"type": "integer"},
                            "score": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["listing_id", "rank", "score", "rationale"],
                    },
                },
                "trade_off_narrative": {"type": "string"},
            },
            "required": ["ranked_listings", "trade_off_narrative"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_recommendation"},
}


def compute_hard_constraint_violations(
    state: AgentState, candidate: ListingCandidate
) -> list[str]:
    """Code-level hard-constraint checks — not LLM judgment."""
    req = state["user_request"]
    lid = candidate.id
    violations: list[str] = []

    commute = state["commute_results"].get(lid)
    if commute is not None and not commute.meets_constraint:
        limit = req.max_commute_minutes
        if limit is not None:
            over_by = max(0.0, float(commute.walk_minutes) - float(limit))
            violations.append(
                f"exceeds your {limit}-minute commute limit by "
                f"{over_by:.0f} minutes "
                f"(Commute agent: walk_minutes={commute.walk_minutes:.1f})"
            )
        else:
            violations.append(
                f"exceeds commute constraint "
                f"(Commute agent: walk_minutes={commute.walk_minutes:.1f}, "
                f"meets_constraint=False)"
            )

    budget = state["budget_analysis"].get(lid)
    if budget is not None and not budget.is_affordable:
        violations.append(
            f"exceeds your ${req.budget_max:.0f} budget "
            f"(Budget agent: monthly_cost=${budget.monthly_cost:.0f}, "
            f"pct_of_budget={budget.pct_of_budget:.0f}%)"
        )

    # Defensive: Listing Search should already filter these, but double-check.
    if req.requires_laundry and not candidate.has_laundry:
        violations.append("requires laundry but listing has no laundry")
    if req.requires_pet_friendly and not candidate.is_pet_friendly:
        violations.append("requires pet-friendly but listing is not pet-friendly")

    return violations


def _candidate_summary(state: AgentState, candidate: ListingCandidate) -> str:
    """Build a per-candidate summary using only findings from agents that ran."""
    lid = candidate.id
    violations = compute_hard_constraint_violations(state, candidate)
    lines = [
        f"listing_id: {lid}  (use this exact listing_id string in your output)",
        f"title: {candidate.title}",
        f"neighborhood: {candidate.neighborhood}",
        f"price_monthly: ${candidate.price_monthly:.0f}",
        f"beds: {candidate.beds}",
        f"has_laundry: {candidate.has_laundry}",
        f"is_pet_friendly: {candidate.is_pet_friendly}",
        f"violates_hard_constraints: {violations}",
    ]

    nb = state["neighborhood_findings"].get(lid)
    if nb is not None:
        lines.append(
            f"Neighborhood agent: safety={nb.safety_score}/5 "
            f"noise={nb.noise_score}/5 summary={nb.summary!r}"
        )

    commute = state["commute_results"].get(lid)
    if commute is not None:
        lines.append(
            f"Commute agent: walk_minutes={commute.walk_minutes:.1f} "
            f"meets_constraint={commute.meets_constraint}"
        )

    budget = state["budget_analysis"].get(lid)
    if budget is not None:
        lines.append(
            f"Budget agent: monthly_cost=${budget.monthly_cost:.0f} "
            f"pct_of_budget={budget.pct_of_budget:.0f}% "
            f"is_affordable={budget.is_affordable} "
            f"explanation={budget.explanation!r}"
        )

    risk = state["risk_flags"].get(lid)
    if risk is not None:
        lines.append(
            f"Risk agent: risk_level={risk.risk_level} "
            f"flags={risk.flags} reasoning={risk.reasoning!r}"
        )

    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    req = state["user_request"]
    parts = [
        "USER REQUEST:",
        f"  budget_max={req.budget_max}",
        f"  anchor={req.anchor_address}",
        f"  max_commute_minutes={req.max_commute_minutes}",
        f"  requires_laundry={req.requires_laundry}",
        f"  requires_pet_friendly={req.requires_pet_friendly}",
        f"  free_text={req.free_text!r}",
        "",
    ]
    if state["critic_notes"] is not None:
        notes = state["critic_notes"]
        parts.append(
            f"Critic: approved={notes.approved} issues={notes.issues}"
        )
        parts.append("")

    candidates = state["candidates"]
    n = min(3, len(candidates))
    parts.append(
        f"Rank up to {n} of the following {len(candidates)} candidate(s):"
    )
    parts.append("")
    for candidate in candidates:
        parts.append(_candidate_summary(state, candidate))
        parts.append("---")
    return "\n".join(parts)


def _violations_by_listing_id(state: AgentState) -> dict[str, list[str]]:
    return {
        c.id: compute_hard_constraint_violations(state, c)
        for c in state["candidates"]
    }


def _clamp_score_for_violations(
    listing_id: str,
    score: float,
    violations_map: dict[str, list[str]],
) -> float:
    """Python-level enforcement: hard-constraint violators cannot score above 0.5."""
    clamped = min(1.0, max(0.0, float(score)))
    if violations_map.get(listing_id):
        return min(clamped, _HARD_CONSTRAINT_SCORE_CAP)
    return clamped


def _fallback_recommendation(state: AgentState) -> RecommendationOutput:
    """Deterministic fallback when the LLM returns unusable output."""
    violations_map = _violations_by_listing_id(state)
    # Prefer non-violating candidates, then ascending price.
    sorted_candidates = sorted(
        state["candidates"],
        key=lambda c: (1 if violations_map.get(c.id) else 0, c.price_monthly),
    )
    top = sorted_candidates[:3]
    ranked = [
        RankedListing(
            listing_id=c.id,
            rank=i,
            score=_clamp_score_for_violations(
                c.id, max(0.0, 1.0 - (i - 1) * 0.15), violations_map
            ),
            rationale=(
                (
                    f"Note: this {violations_map[c.id][0]}. "
                    if violations_map.get(c.id)
                    else ""
                )
                + (
                    f"Listing Search agent returned this candidate at "
                    f"${c.price_monthly:.0f}/mo in {c.neighborhood}."
                )
            ),
        )
        for i, c in enumerate(top, start=1)
    ]
    narrative = (
        "Fallback ranking by ascending price because the synthesis model "
        "did not return a valid RecommendationOutput."
    )
    return RecommendationOutput(ranked_listings=ranked, trade_off_narrative=narrative)


async def run_recommendation(state: AgentState) -> AgentState:
    """Synthesize a ranked top-3 with scores, rationales, and trade-off narrative."""
    started_at = datetime.now(tz=UTC)

    if not state["candidates"]:
        empty = RecommendationOutput(
            ranked_listings=[],
            trade_off_narrative="No candidates available to recommend.",
        )
        finished_at = datetime.now(tz=UTC)
        trace_event = AgentTraceEvent(
            agent_name="recommendation",
            started_at=started_at,
            finished_at=finished_at,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        return AgentState(
            **{
                **state,
                "recommendation": empty,
                "trace": [*state["trace"], trace_event],
            }
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": RECOMMENDATION_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(state)},
    ]

    try:
        response = await complete(
            messages=messages,
            model=settings.planner_model,
            tools=[_SUBMIT_RECOMMENDATION_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
    except LLMError as exc:
        raise RecommendationError(
            f"LLM call failed in recommendation agent: {exc}", cause=exc
        ) from exc

    if not response.tool_calls:
        raise RecommendationError("Recommendation agent returned no tool calls")

    tool_call = response.tool_calls[0]
    fn_name = getattr(getattr(tool_call, "function", None), "name", None)
    if fn_name != "submit_recommendation":
        raise RecommendationError(
            f"Recommendation agent called unexpected tool: {fn_name!r}"
        )

    raw_args = getattr(tool_call.function, "arguments", "{}")
    violations_map = _violations_by_listing_id(state)
    recommendation: RecommendationOutput | None = None
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            raise ValueError("Recommendation payload is not an object")
        listings_raw = args.get("ranked_listings", [])
        if not isinstance(listings_raw, list):
            raise ValueError("ranked_listings is not a list")
        coerced: list[dict[str, Any]] = []
        for item in listings_raw:
            if not isinstance(item, dict):
                continue
            listing_id = item.get("listing_id") or item.get("id")
            if listing_id is None:
                continue
            coerced.append(
                {
                    "listing_id": str(listing_id),
                    "rank": int(item.get("rank", len(coerced) + 1)),
                    "score": float(item.get("score", 0.5)),
                    "rationale": str(item.get("rationale") or ""),
                }
            )
        narrative = str(
            args.get("trade_off_narrative") or args.get("tradeoff_narrative") or ""
        )
        if not coerced:
            raise ValueError(f"No ranked_listings parsed from: {raw_args[:300]}")
        recommendation = RecommendationOutput.model_validate(
            {
                "ranked_listings": coerced,
                "trade_off_narrative": narrative
                or "No trade-off narrative provided.",
            }
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "recommendation_parse_failed",
            error=str(exc),
            raw_args=str(raw_args)[:800],
            request_id=state["request_id"],
        )
    except Exception as exc:
        logger.warning(
            "recommendation_parse_failed",
            error=str(exc),
            raw_args=str(raw_args)[:800],
            request_id=state["request_id"],
        )

    if recommendation is None:
        recommendation = _fallback_recommendation(state)
    else:
        # Clamp to available candidates and at most 3; resolve truncated IDs.
        valid_ids = {c.id for c in state["candidates"]}
        candidate_list = list(state["candidates"])

        def _resolve_listing_id(raw_id: str) -> str | None:
            if raw_id in valid_ids:
                return raw_id
            matches = [
                lid
                for lid in valid_ids
                if lid.startswith(raw_id) or raw_id.startswith(lid[:8])
            ]
            if len(matches) == 1:
                return matches[0]
            if len(candidate_list) == 1:
                return candidate_list[0].id
            return None

        cleaned: list[RankedListing] = []
        for item in recommendation.ranked_listings:
            resolved = _resolve_listing_id(item.listing_id)
            if resolved is None:
                logger.warning(
                    "recommendation_unresolved_listing_id",
                    raw_id=item.listing_id,
                    request_id=state["request_id"],
                )
                continue
            if any(c.listing_id == resolved for c in cleaned):
                continue
            score = _clamp_score_for_violations(resolved, item.score, violations_map)
            rationale = item.rationale.strip()
            if not rationale:
                continue
            cleaned.append(
                RankedListing(
                    listing_id=resolved,
                    rank=item.rank,
                    score=score,
                    rationale=rationale,
                )
            )
            if len(cleaned) >= 3:
                break

        if not cleaned and len(candidate_list) == 1 and recommendation.ranked_listings:
            top = recommendation.ranked_listings[0]
            only_id = candidate_list[0].id
            cleaned = [
                RankedListing(
                    listing_id=only_id,
                    rank=1,
                    score=_clamp_score_for_violations(
                        only_id, float(top.score), violations_map
                    ),
                    rationale=top.rationale
                    or (
                        f"Listing Search agent returned this candidate at "
                        f"${candidate_list[0].price_monthly:.0f}/mo."
                    ),
                )
            ]

        if not cleaned:
            recommendation = _fallback_recommendation(state)
        else:
            cleaned = [
                RankedListing(
                    listing_id=item.listing_id,
                    rank=i,
                    score=item.score,
                    rationale=item.rationale,
                )
                for i, item in enumerate(cleaned, start=1)
            ]
            narrative = recommendation.trade_off_narrative.strip()
            if not narrative or narrative == "No trade-off narrative provided.":
                narrative = " ".join(item.rationale for item in cleaned)
            recommendation = RecommendationOutput(
                ranked_listings=cleaned,
                trade_off_narrative=narrative,
            )

    finished_at = datetime.now(tz=UTC)
    trace_event = AgentTraceEvent(
        agent_name="recommendation",
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )

    logger.info(
        "recommendation_done",
        request_id=state["request_id"],
        ranked=len(recommendation.ranked_listings),
        cost_usd=round(response.cost_usd, 6),
    )

    return AgentState(
        **{
            **state,
            "recommendation": recommendation,
            "trace": [*state["trace"], trace_event],
        }
    )
