"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getObservabilitySummary, ApiError } from "@/lib/api-client";
import type { ObservabilitySummary } from "@/lib/types";

export default function ObservabilityPage() {
  const { getToken, isLoaded } = useAuth();
  const [data, setData] = useState<ObservabilitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const summary = await getObservabilitySummary(() => getToken());
        if (!cancelled) setData(summary);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Failed to load observability summary"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [getToken, isLoaded]);

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-10 sm:px-6">
      <header className="space-y-2">
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[#0f5444]">
          Observability
        </h1>
        <p className="text-muted-foreground">
          Latency and cost aggregates from recent AgentRun rows. No admin role
          gate yet — any signed-in user can open this page.
        </p>
      </header>

      {loading ? <p className="text-muted-foreground">Loading summary…</p> : null}
      {error ? <p className="text-destructive">{error}</p> : null}

      {data && data.request_count === 0 && data.per_agent.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
          <p className="text-foreground">No AgentRun data yet</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Submit a housing request and wait for it to complete — latency and
            cost aggregates will appear here.
          </p>
          <Link
            href="/request"
            className="mt-4 inline-block text-sm font-medium text-[#0f5444] underline-offset-4 hover:underline"
          >
            New request
          </Link>
        </div>
      ) : null}

      {data && (data.request_count > 0 || data.per_agent.length > 0) ? (
        <>
          <section className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-card/80 p-5">
              <p className="text-sm text-muted-foreground">Total cost (window)</p>
              <p className="mt-1 font-[family-name:var(--font-display)] text-3xl text-foreground">
                ${data.total_cost_usd.toFixed(4)}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-card/80 p-5">
              <p className="text-sm text-muted-foreground">Requests in window</p>
              <p className="mt-1 font-[family-name:var(--font-display)] text-3xl text-foreground">
                {data.request_count}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Limit constant: {data.recent_request_limit}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-card/80 p-5">
              <p className="text-sm text-muted-foreground">Stale pending</p>
              <p className="mt-1 font-[family-name:var(--font-display)] text-3xl text-foreground">
                {data.stale_pending.length}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Threshold: {data.stale_pending_seconds}s
              </p>
            </div>
          </section>

          {data.stale_pending.length > 0 ? (
            <section className="rounded-xl border border-amber-300 bg-amber-50 p-5">
              <h2 className="font-semibold text-amber-950">
                Stale pending requests
              </h2>
              <p className="mt-1 text-sm text-amber-900/80">
                Detection only — these may be stuck if the Celery worker is down.
                Auto-fail / task time limits are still future work.
              </p>
              <ul className="mt-3 space-y-2 text-sm">
                {data.stale_pending.map((item) => (
                  <li key={item.request_id} className="flex flex-wrap gap-x-3 gap-y-1">
                    <Link
                      href={`/request/${item.request_id}`}
                      className="font-mono text-[#0f5444] underline-offset-2 hover:underline"
                    >
                      {item.request_id}
                    </Link>
                    <span className="text-amber-900/80">
                      pending {Math.round(item.pending_seconds)}s
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="space-y-3 rounded-xl border border-border bg-card/70 p-5">
            <h2 className="font-[family-name:var(--font-display)] text-xl">
              Average latency by agent
            </h2>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.per_agent}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="agent_name" tick={{ fontSize: 12 }} />
                  <YAxis
                    tick={{ fontSize: 12 }}
                    label={{
                      value: "ms",
                      angle: -90,
                      position: "insideLeft",
                      style: { fontSize: 12 },
                    }}
                  />
                  <Tooltip
                    formatter={(value) => [
                      `${Number(value).toFixed(1)} ms`,
                      "avg latency",
                    ]}
                  />
                  <Bar dataKey="avg_latency_ms" fill="#0f5444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="space-y-3 rounded-xl border border-border bg-card/70 p-5">
            <h2 className="font-[family-name:var(--font-display)] text-xl">
              Average cost by agent
            </h2>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.per_agent}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="agent_name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    formatter={(value) => [
                      `$${Number(value).toFixed(6)}`,
                      "avg cost",
                    ]}
                  />
                  <Bar dataKey="avg_cost_usd" fill="#1d6b9a" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-border text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Agent</th>
                    <th className="py-2 pr-4 font-medium">Calls</th>
                    <th className="py-2 pr-4 font-medium">Avg latency</th>
                    <th className="py-2 pr-4 font-medium">Avg cost</th>
                    <th className="py-2 font-medium">Total cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_agent.map((row) => (
                    <tr key={row.agent_name} className="border-b border-border/60">
                      <td className="py-2 pr-4 font-medium">{row.agent_name}</td>
                      <td className="py-2 pr-4">{row.call_count}</td>
                      <td className="py-2 pr-4">
                        {row.avg_latency_ms.toFixed(1)} ms
                      </td>
                      <td className="py-2 pr-4">
                        ${row.avg_cost_usd.toFixed(6)}
                      </td>
                      <td className="py-2">${row.total_cost_usd.toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
