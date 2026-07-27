"use client";

import { useEffect, useMemo, useState } from "react";

import {
  AGENT_LABELS,
  PIPELINE_AGENTS,
  isPipelineAgent,
  isSpecialistAgent,
  type PipelineAgent,
} from "@/lib/agents";
import type { AgentProgressEvent, AgentVisualState } from "@/lib/stream-types";
import { cn } from "@/lib/utils";

type AgentGraphProps = {
  events: AgentProgressEvent[];
  selectedAgents: string[] | null;
};

const RUNNING_HOLD_MS = 450;

function initialVisualState(): AgentVisualState {
  return Object.fromEntries(
    PIPELINE_AGENTS.map((agent) => [agent, { state: "idle" as const }])
  ) as AgentVisualState;
}

export function AgentGraph({ events, selectedAgents }: AgentGraphProps) {
  const [visual, setVisual] = useState<AgentVisualState>(initialVisualState);

  // Derive plan-based skips as soon as selectedAgents arrives.
  useEffect(() => {
    if (!selectedAgents) return;
    setVisual((prev) => {
      const next = { ...prev };
      for (const agent of PIPELINE_AGENTS) {
        if (!isSpecialistAgent(agent)) continue;
        if (!selectedAgents.includes(agent) && prev[agent].state === "idle") {
          next[agent] = { state: "pending-skip" };
        } else if (
          selectedAgents.includes(agent) &&
          prev[agent].state === "idle"
        ) {
          next[agent] = { state: "queued" };
        }
      }
      return next;
    });
  }, [selectedAgents]);

  // Drive running → done transitions from completion events.
  useEffect(() => {
    const last = events[events.length - 1];
    if (!last || last.event !== "agent_complete") return;
    if (!isPipelineAgent(last.agent)) return;
    const agent = last.agent as PipelineAgent;
    const summary = last.summary;

    setVisual((prev) => ({
      ...prev,
      [agent]: { state: "running", summary: prev[agent].summary },
    }));

    const timer = window.setTimeout(() => {
      setVisual((prev) => ({
        ...prev,
        [agent]: { state: "done", summary },
      }));
    }, RUNNING_HOLD_MS);

    return () => window.clearTimeout(timer);
  }, [events]);

  const ordered = useMemo(() => PIPELINE_AGENTS, []);

  return (
    <div className="flex flex-col gap-4">
      <AgentCard agent="planner" visual={visual.planner} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {ordered
          .filter((a) => isSpecialistAgent(a))
          .map((agent) => (
            <AgentCard key={agent} agent={agent} visual={visual[agent]} />
          ))}
      </div>

      <AgentCard agent="critic" visual={visual.critic} />
      <AgentCard agent="recommendation" visual={visual.recommendation} />
    </div>
  );
}

function AgentCard({
  agent,
  visual,
}: {
  agent: PipelineAgent;
  visual: { state: string; summary?: string };
}) {
  const state = visual.state;
  return (
    <div
      className={cn(
        "relative rounded-xl border px-4 py-3 transition-all duration-300",
        state === "idle" && "border-border/60 bg-background/40 opacity-45",
        state === "queued" && "border-[#0f5444]/40 bg-[#0f5444]/5 opacity-80",
        state === "running" &&
          "border-sky-500/70 bg-sky-50 shadow-sm shadow-sky-200/60 animate-pulse",
        state === "done" && "border-emerald-600/50 bg-emerald-50/80",
        state === "pending-skip" &&
          "border-dashed border-border bg-muted/40 opacity-60"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-foreground">{AGENT_LABELS[agent]}</p>
        <StatusBadge state={state} />
      </div>
      {state === "done" && visual.summary ? (
        <p className="mt-2 text-sm text-muted-foreground">{visual.summary}</p>
      ) : null}
      {state === "pending-skip" ? (
        <p className="mt-2 text-xs uppercase tracking-wide text-muted-foreground">
          Skipped by Planner
        </p>
      ) : null}
      {state === "running" ? (
        <p className="mt-2 text-sm text-sky-700">Working…</p>
      ) : null}
    </div>
  );
}

function StatusBadge({ state }: { state: string }) {
  if (state === "done") {
    return (
      <span className="rounded-full bg-emerald-600/15 px-2 py-0.5 text-xs font-medium text-emerald-800">
        Done
      </span>
    );
  }
  if (state === "running") {
    return (
      <span className="rounded-full bg-sky-600/15 px-2 py-0.5 text-xs font-medium text-sky-800">
        Running
      </span>
    );
  }
  if (state === "pending-skip") {
    return (
      <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
        Skipped
      </span>
    );
  }
  if (state === "queued") {
    return (
      <span className="rounded-full bg-[#0f5444]/10 px-2 py-0.5 text-xs font-medium text-[#0f5444]">
        Queued
      </span>
    );
  }
  return (
    <span className="rounded-full bg-muted/80 px-2 py-0.5 text-xs text-muted-foreground">
      Idle
    </span>
  );
}
