import operator
from typing import Annotated, TypedDict

from src.schemas.agents import (
    AgentName,
    AgentTraceEvent,
    BudgetAnalysis,
    CommuteResult,
    CriticReview,
    ExecutionPlan,
    ListingCandidate,
    NeighborhoodAssessment,
    RecommendationOutput,
    RiskAssessment,
    UserHousingRequest,
)

__all__ = [
    "AgentState",
    "AgentName",
    "AgentTraceEvent",
    "BudgetAnalysis",
    "CommuteResult",
    "CriticReview",
    "ExecutionPlan",
    "ListingCandidate",
    "NeighborhoodAssessment",
    "RecommendationOutput",
    "RiskAssessment",
    "UserHousingRequest",
]


class AgentState(TypedDict):
    request_id: str
    user_request: UserHousingRequest
    execution_plan: ExecutionPlan | None
    candidates: list[ListingCandidate]
    neighborhood_findings: dict[str, NeighborhoodAssessment]
    commute_results: dict[str, CommuteResult]
    budget_analysis: dict[str, BudgetAnalysis]
    risk_flags: dict[str, RiskAssessment]
    critic_notes: CriticReview | None
    retry_count: int
    recommendation: RecommendationOutput | None
    # Reducer required for parallel specialist fan-out (each node appends events)
    trace: Annotated[list[AgentTraceEvent], operator.add]
