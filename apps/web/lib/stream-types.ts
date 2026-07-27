import type { RecommendationOutput } from "@/lib/types";
import type { PipelineAgent } from "@/lib/agents";

export type AgentProgressEvent =
  | {
      event: "agent_complete";
      agent: string;
      summary?: string;
      tokens?: number;
      cost_usd?: number;
      selected_agents?: string[];
      reasoning?: string;
    }
  | { event: "done"; recommendation: RecommendationOutput | null }
  | { event: "error"; detail: string }
  | { event: "status"; status?: string };

export type StreamStatus = "connecting" | "streaming" | "done" | "error";

export type AgentCardState =
  | "idle"
  | "queued"
  | "running"
  | "done"
  | "pending-skip";

export type AgentVisualState = Record<
  PipelineAgent,
  { state: AgentCardState; summary?: string }
>;
