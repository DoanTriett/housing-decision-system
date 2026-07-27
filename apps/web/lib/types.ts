/**
 * Types mirroring apps/api/src/api/schemas.py — keep field names in sync.
 */

export type UserHousingRequestPayload = {
  budget_max: number;
  anchor_address: string;
  max_commute_minutes?: number | null;
  requires_laundry?: boolean;
  requires_pet_friendly?: boolean;
  free_text?: string | null;
};

export type CreateHousingRequestResponse = {
  request_id: string;
};

export type RankedListingDetail = {
  listing_id: string;
  rank: number;
  score: number;
  rationale: string;
  title?: string | null;
  address?: string | null;
  neighborhood?: string | null;
  price_monthly?: number | null;
  lat?: number | null;
  lon?: number | null;
  walk_minutes?: number | null;
  safety_score?: number | null;
  risk_level?: string | null;
  is_affordable?: boolean | null;
  pct_of_budget?: number | null;
};

export type EnrichedRecommendation = {
  ranked_listings: RankedListingDetail[];
  trade_off_narrative: string;
};

/** Alias for SSE / live view payloads that still use the Day 11 name. */
export type RecommendationOutput = EnrichedRecommendation;

/** GET /api/requests/{id} — RequestStatusResponse */
export type RequestResult = {
  request_id: string;
  status: string;
  recommendation: EnrichedRecommendation | null;
  detail: string | null;
  anchor_address?: string | null;
  anchor_lat?: number | null;
  anchor_lon?: number | null;
  budget_max?: number | null;
  created_at?: string | null;
};

/** One item from GET /api/requests — RequestListItem */
export type RequestSummary = {
  request_id: string;
  status: string;
  budget_max: number | null;
  anchor_address: string | null;
  created_at: string | null;
  is_stale?: boolean;
  pending_seconds?: number | null;
};

/** Full list payload — RequestListResponse */
export type RequestListResponse = {
  items: RequestSummary[];
  limit: number;
  offset: number;
  total: number;
};

export type AgentCostLatencyStat = {
  agent_name: string;
  call_count: number;
  avg_latency_ms: number;
  avg_cost_usd: number;
  total_cost_usd: number;
};

export type StaleRequestItem = {
  request_id: string;
  user_id: string;
  created_at: string;
  pending_seconds: number;
};

export type ObservabilitySummary = {
  recent_request_limit: number;
  stale_pending_seconds: number;
  request_count: number;
  total_cost_usd: number;
  per_agent: AgentCostLatencyStat[];
  stale_pending: StaleRequestItem[];
};
