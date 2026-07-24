"""Typed exceptions for the LLM abstraction layer."""


class LLMError(Exception):
    """Base class for all LLM client errors."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class LLMRateLimitError(LLMError):
    """Raised when all retry attempts are exhausted due to rate-limiting."""


class LLMTimeoutError(LLMError):
    """Raised when the LLM call times out after all retries."""


class LLMServiceError(LLMError):
    """Raised for upstream service errors (5xx, provider outage)."""


class PlannerError(LLMError):
    """Raised when the Planner agent fails to produce a valid ExecutionPlan."""


class ListingSearchError(Exception):
    """Raised when Listing Search finds zero matching candidates."""


class BudgetError(LLMError):
    """Raised when the Budget agent fails to produce valid analyses."""


class NeighborhoodError(LLMError):
    """Raised when the Neighborhood agent fails to assess candidates."""


class CommuteError(Exception):
    """Raised when Google Maps / commute calculation fails."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class GeocodingError(Exception):
    """Raised when an address cannot be geocoded."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class RiskError(LLMError):
    """Raised when the Risk agent fails to assess candidates."""


class CriticError(LLMError):
    """Raised when the Critic agent fails to produce a review."""


class RecommendationError(LLMError):
    """Raised when the Recommendation agent fails to produce a ranking."""
