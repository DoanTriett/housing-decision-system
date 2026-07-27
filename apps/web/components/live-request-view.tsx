"use client";

import Link from "next/link";

import { AgentGraph } from "@/components/agent-graph";
import { useRequestStream } from "@/hooks/use-request-stream";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type LiveRequestViewProps = {
  requestId: string;
};

export function LiveRequestView({ requestId }: LiveRequestViewProps) {
  const {
    events,
    status,
    recommendation,
    error,
    plannerReasoning,
    selectedAgents,
  } = useRequestStream(requestId);

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-wide text-muted-foreground">
            Live pipeline
          </p>
          <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[#0f5444] sm:text-4xl">
            Agents at work
          </h1>
          <p className="mt-2 font-mono text-xs text-muted-foreground sm:text-sm">
            {requestId}
          </p>
        </div>
        <StatusPill status={status} />
      </div>

      {status === "connecting" ? (
        <p className="mb-6 animate-pulse text-muted-foreground">
          Connecting to live progress stream…
        </p>
      ) : null}

      {plannerReasoning ? (
        <div className="mb-6 rounded-xl border border-[#0f5444]/20 bg-[#0f5444]/5 px-4 py-3">
          <p className="text-sm font-medium text-[#0f5444]">Planner&apos;s reasoning</p>
          <p className="mt-1 text-sm leading-relaxed text-foreground/90">
            {plannerReasoning}
          </p>
          {selectedAgents && selectedAgents.length > 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Selected: {selectedAgents.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {status === "done" &&
      events.filter((e) => e.event === "agent_complete").length === 0 ? (
        <p className="mb-6 rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          This run had already finished when the live view connected, so step-by-step
          agent animation wasn&apos;t replayed. The final recommendation is below.
        </p>
      ) : null}

      {status === "streaming" &&
      events.filter((e) => e.event === "agent_complete").length === 0 ? (
        <p className="mb-6 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Waiting for the first agent event. If this stalls past ~90 seconds, the
          Celery worker may be down — check the Observability page for stale
          pending requests (detection only; restart the worker to clear them).
        </p>
      ) : null}

      <AgentGraph events={events} selectedAgents={selectedAgents} />

      {status === "error" ? (
        <div className="mt-8 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-destructive">
          <p className="font-medium">Pipeline error</p>
          <p className="mt-1 text-sm">{error ?? "Unknown error"}</p>
        </div>
      ) : null}

      {status === "done" ? (
        <div className="mt-8 space-y-4 rounded-xl border border-emerald-600/30 bg-emerald-50/70 px-4 py-4">
          <p className="font-medium text-emerald-900">Run complete</p>
          <Link
            href={`/request/${requestId}/results`}
            className={cn(buttonVariants({ size: "lg" }))}
          >
            View full results
          </Link>
          {recommendation ? (
            <details className="text-sm text-muted-foreground">
              <summary className="cursor-pointer text-foreground">
                Show raw recommendation JSON
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-background/80 p-3 text-xs">
                {JSON.stringify(recommendation, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const label =
    status === "connecting"
      ? "Connecting"
      : status === "streaming"
        ? "Streaming"
        : status === "done"
          ? "Done"
          : status === "error"
            ? "Error"
            : status;
  return (
    <span
      className={cn(
        "rounded-full px-3 py-1 text-xs font-medium",
        status === "streaming" && "bg-sky-100 text-sky-800 animate-pulse",
        status === "done" && "bg-emerald-100 text-emerald-800",
        status === "error" && "bg-destructive/15 text-destructive",
        status === "connecting" && "bg-muted text-muted-foreground"
      )}
    >
      {label}
    </span>
  );
}
