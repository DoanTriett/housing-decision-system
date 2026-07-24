"""Per-agent Pydantic I/O schemas shared across all agents and AgentState."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AgentName(StrEnum):
    listing_search = "listing_search"
    neighborhood = "neighborhood"
    commute = "commute"
    budget = "budget"
    risk = "risk"


class UserHousingRequest(BaseModel):
    budget_max: float
    anchor_address: str
    max_commute_minutes: int | None = None
    requires_laundry: bool = False
    requires_pet_friendly: bool = False
    free_text: str | None = None


class ExecutionPlan(BaseModel):
    selected_agents: list[AgentName]
    reasoning: str
    per_agent_goals: dict[AgentName, str]


class ListingCandidate(BaseModel):
    id: str
    title: str
    address: str
    neighborhood: str
    price_monthly: float
    beds: float
    has_laundry: bool
    is_pet_friendly: bool
    lat: float
    lon: float
    description: str = ""


class ListingFilters(BaseModel):
    max_price: float
    requires_laundry: bool | None = None
    requires_pet_friendly: bool | None = None
    neighborhood: str | None = None
    limit: int = 20


class NeighborhoodDoc(BaseModel):
    neighborhood: str
    content: str
    score: float


class NeighborhoodAssessment(BaseModel):
    listing_id: str
    summary: str
    safety_score: int = Field(ge=1, le=5)
    noise_score: int = Field(ge=1, le=5)
    source_docs: list[str]


class CommuteResult(BaseModel):
    listing_id: str
    walk_minutes: float
    meets_constraint: bool


class BudgetAnalysis(BaseModel):
    listing_id: str
    monthly_cost: float
    pct_of_budget: float
    is_affordable: bool
    explanation: str


class RiskAssessment(BaseModel):
    listing_id: str
    risk_level: Literal["low", "medium", "high"]
    flags: list[str]
    reasoning: str


class CriticReview(BaseModel):
    approved: bool
    issues: list[str]
    retry_agent: AgentName | None = None


class RankedListing(BaseModel):
    listing_id: str
    rank: int
    score: float
    rationale: str


class RecommendationOutput(BaseModel):
    ranked_listings: list[RankedListing]
    trade_off_narrative: str


class AgentTraceEvent(BaseModel):
    agent_name: str
    started_at: datetime
    finished_at: datetime
    input_tokens: int
    output_tokens: int
    cost_usd: float
