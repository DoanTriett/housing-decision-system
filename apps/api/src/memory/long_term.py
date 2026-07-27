"""Long-term UserProfile memory — extract and upsert durable preferences."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.state import AgentState
from src.config import settings
from src.llm.client import complete
from src.llm.prompts.profile import PROFILE_EXTRACTION_SYSTEM_PROMPT
from src.models.user_profile import UserProfile

logger = structlog.get_logger(__name__)

_SUBMIT_PREFERENCES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_preferences",
        "description": "Submit durable housing preferences as a flat JSON object.",
        "parameters": {
            "type": "object",
            "properties": {
                "preferences": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Durable preference key/value pairs.",
                },
            },
            "required": ["preferences"],
        },
    },
}

_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "submit_preferences"},
}


def _build_user_message(state: AgentState) -> str:
    req = state["user_request"]
    rec = state["recommendation"]
    lines = [
        "USER REQUEST:",
        f"  budget_max={req.budget_max}",
        f"  max_commute_minutes={req.max_commute_minutes}",
        f"  requires_laundry={req.requires_laundry}",
        f"  requires_pet_friendly={req.requires_pet_friendly}",
        f"  free_text={req.free_text!r}",
        "",
        "RECOMMENDATION:",
    ]
    if rec is None:
        lines.append("  (none)")
    else:
        lines.append(f"  trade_off_narrative={rec.trade_off_narrative!r}")
        for item in rec.ranked_listings:
            lines.append(
                f"  rank={item.rank} listing_id={item.listing_id} "
                f"score={item.score} rationale={item.rationale!r}"
            )
    return "\n".join(lines)


async def update_user_profile(
    user_id: str, state: AgentState, session: AsyncSession
) -> dict[str, Any] | None:
    """Extract durable preferences via LLM and upsert into ``user_profiles``.

    Best-effort: logs and returns None on failure instead of raising.
    """
    try:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": PROFILE_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(state)},
        ]
        response = await complete(
            messages=messages,
            model=settings.specialist_model,
            tools=[_SUBMIT_PREFERENCES_TOOL],
            tool_choice=_TOOL_CHOICE,
        )
        if not response.tool_calls:
            logger.warning("profile_no_tool_calls", user_id=user_id)
            return None

        tool_call = response.tool_calls[0]
        raw_args = getattr(tool_call.function, "arguments", "{}")
        args = json.loads(raw_args)
        new_prefs = args.get("preferences")
        if not isinstance(new_prefs, dict):
            logger.warning("profile_invalid_preferences", user_id=user_id)
            return None

        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = UserProfile(user_id=user_id, preferences_json={})
            session.add(profile)

        merged = dict(profile.preferences_json or {})
        merged.update({k: v for k, v in new_prefs.items() if v is not None})
        profile.preferences_json = merged
        await session.commit()

        logger.info(
            "user_profile_updated",
            user_id=user_id,
            keys=list(merged.keys()),
            cost_usd=round(response.cost_usd, 6),
        )
        return merged
    except Exception as exc:
        logger.warning(
            "user_profile_update_failed",
            user_id=user_id,
            error=str(exc),
        )
        with suppress(Exception):
            await session.rollback()
        return None
