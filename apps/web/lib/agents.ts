/** Single source of truth for pipeline agent names (Day 11 live graph). */

export const PIPELINE_AGENTS = [
  "planner",
  "listing_search",
  "neighborhood",
  "commute",
  "budget",
  "risk",
  "critic",
  "recommendation",
] as const;

export type PipelineAgent = (typeof PIPELINE_AGENTS)[number];

/** Specialists the Planner may select or skip. Always-run nodes are excluded. */
export const SPECIALIST_AGENTS = [
  "listing_search",
  "neighborhood",
  "commute",
  "budget",
  "risk",
] as const;

export type SpecialistAgent = (typeof SPECIALIST_AGENTS)[number];

export const AGENT_LABELS: Record<PipelineAgent, string> = {
  planner: "Planner",
  listing_search: "Listing Search",
  neighborhood: "Neighborhood",
  commute: "Commute",
  budget: "Budget",
  risk: "Risk",
  critic: "Critic",
  recommendation: "Recommendation",
};

export function isPipelineAgent(value: string): value is PipelineAgent {
  return (PIPELINE_AGENTS as readonly string[]).includes(value);
}

export function isSpecialistAgent(value: string): value is SpecialistAgent {
  return (SPECIALIST_AGENTS as readonly string[]).includes(value);
}
