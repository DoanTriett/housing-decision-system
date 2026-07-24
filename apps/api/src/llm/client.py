"""Async LLM client wrapping LiteLLM with retry, cost tracking, and structured errors."""

import asyncio
import time
from typing import Any

import litellm
import structlog

from src.config import settings
from src.llm.exceptions import LLMError, LLMRateLimitError, LLMServiceError, LLMTimeoutError

logger = structlog.get_logger(__name__)

# Tell litellm to suppress its own verbose logging
litellm.suppress_debug_info = True


class LLMResponse:
    """Parsed response from a single LLM completion call."""

    def __init__(
        self,
        content: str | None,
        tool_calls: list[Any] | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: float,
        raw: Any,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd
        self.latency_ms = latency_ms
        self.raw = raw


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors that are worth retrying."""
    msg = str(exc).lower()
    retryable_signals = ("rate limit", "ratelimit", "timeout", "timed out", "503", "502", "529")
    return any(s in msg for s in retryable_signals)


async def complete(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> LLMResponse:
    """Single async completion call with retry, cost tracking, and structured errors.

    Retries up to ``settings.llm_max_retries`` times on transient failures
    with exponential backoff (1 s, 2 s, …).
    """
    last_exc: Exception | None = None

    for attempt in range(settings.llm_max_retries + 1):
        t0 = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "timeout": settings.llm_timeout_seconds,
                "api_key": settings.openai_api_key,
            }
            if tools is not None:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

            response = await litellm.acompletion(**kwargs)

            latency_ms = (time.perf_counter() - t0) * 1000

            # Token counts
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            # Cost via litellm utility (imported directly to avoid attr-defined issue)
            try:
                from litellm import completion_cost  # type: ignore[attr-defined]

                cost_usd = completion_cost(completion_response=response)
            except Exception:
                cost_usd = 0.0

            # Extract content and tool calls from first choice
            choice = response.choices[0]
            msg = choice.message
            content: str | None = getattr(msg, "content", None)
            raw_tool_calls = getattr(msg, "tool_calls", None)
            tool_calls: list[Any] | None = list(raw_tool_calls) if raw_tool_calls else None

            logger.debug(
                "llm_call",
                model=model,
                attempt=attempt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost_usd, 6),
                latency_ms=round(latency_ms, 1),
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                raw=response,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            last_exc = exc

            if _is_retryable(exc) and attempt < settings.llm_max_retries:
                backoff = 2**attempt  # 1 s, 2 s, …
                logger.warning(
                    "llm_retrying",
                    model=model,
                    attempt=attempt,
                    backoff_s=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
                continue

            # Non-retryable or exhausted retries — raise typed error
            err_msg = str(exc)
            if "rate limit" in err_msg.lower() or "ratelimit" in err_msg.lower():
                raise LLMRateLimitError(err_msg, cause=exc) from exc
            if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                raise LLMTimeoutError(err_msg, cause=exc) from exc
            raise LLMServiceError(err_msg, cause=exc) from exc

    # Should not reach here, but satisfy type checker
    raise LLMError("Unexpected retry loop exit", cause=last_exc)
