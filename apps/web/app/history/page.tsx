"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";

import { listRequests, ApiError } from "@/lib/api-client";
import type { RequestSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function HistoryPage() {
  const { getToken, isLoaded } = useAuth();
  const [items, setItems] = useState<RequestSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (nextOffset: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listRequests(() => getToken(), PAGE_SIZE, nextOffset);
        setItems(data.items);
        setTotal(data.total);
        setOffset(data.offset);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load history");
      } finally {
        setLoading(false);
      }
    },
    [getToken]
  );

  useEffect(() => {
    if (!isLoaded) return;
    void load(0);
  }, [isLoaded, load]);

  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-10 sm:px-6">
      <header className="space-y-2">
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[#0f5444]">
          Request history
        </h1>
        <p className="text-muted-foreground">
          Past housing requests for your account, newest first.
        </p>
      </header>

      {loading ? (
        <p className="text-muted-foreground">Loading requests…</p>
      ) : null}

      {error ? <p className="text-destructive">{error}</p> : null}

      {!loading && !error && items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-12 text-center">
          <p className="text-foreground">No requests yet — submit your first one</p>
          <Link
            href="/request"
            className="mt-4 inline-block text-sm font-medium text-[#0f5444] underline-offset-4 hover:underline"
          >
            New request
          </Link>
        </div>
      ) : null}

      {!loading && items.length > 0 ? (
        <>
          <div className="overflow-x-auto rounded-xl border border-border bg-card/70">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-border bg-secondary/40 text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Submitted</th>
                  <th className="px-4 py-3 font-medium">Budget</th>
                  <th className="px-4 py-3 font-medium">Anchor</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Results</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.request_id}
                    className="border-b border-border/70 last:border-0"
                  >
                    <td className="px-4 py-3 whitespace-nowrap">
                      {formatDate(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {item.budget_max != null
                        ? `$${item.budget_max.toLocaleString()}`
                        : "—"}
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-3">
                      {item.anchor_address ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className="capitalize">{item.status}</span>
                      {item.is_stale ? (
                        <span
                          className={cn(
                            "ml-2 inline-flex rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-300"
                          )}
                          title={
                            item.pending_seconds != null
                              ? `Pending for ${Math.round(item.pending_seconds)}s`
                              : "Pending too long"
                          }
                        >
                          Stale
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      {item.status === "completed" ? (
                        <Link
                          href={`/request/${item.request_id}/results`}
                          className="font-medium text-[#0f5444] underline-offset-4 hover:underline"
                        >
                          View results
                        </Link>
                      ) : item.status === "pending" || item.status === "running" ? (
                        <Link
                          href={`/request/${item.request_id}`}
                          className="text-muted-foreground underline-offset-4 hover:underline"
                        >
                          Live view
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              Showing {offset + 1}–{Math.min(offset + items.length, total)} of{" "}
              {total}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!canPrev}
                onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!canNext}
                onClick={() => void load(offset + PAGE_SIZE)}
                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
