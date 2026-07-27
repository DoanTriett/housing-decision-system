"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { useParams } from "next/navigation";

import { getRequest, ApiError } from "@/lib/api-client";
import type { RankedListingDetail, RequestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const ResultsMap = dynamic(
  () =>
    import("@/components/results-map").then((mod) => mod.ResultsMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[360px] items-center justify-center rounded-xl border border-border bg-card/50 text-sm text-muted-foreground">
        Loading map…
      </div>
    ),
  }
);

function formatMoney(value: number | null | undefined) {
  if (value == null) return "—";
  return `$${Math.round(value).toLocaleString()}`;
}

function ConstraintBadge({ score }: { score: number }) {
  if (score > 0.5) return null;
  return (
    <span className="rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-300">
      Constraint risk (score ≤ 0.5)
    </span>
  );
}

function RankedCard({ listing }: { listing: RankedListingDetail }) {
  const [open, setOpen] = useState(listing.rank === 1);
  return (
    <article className="rounded-xl border border-border bg-card/80 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-xs font-bold text-white",
                listing.rank === 1 && "bg-[#0f5444]",
                listing.rank === 2 && "bg-[#1d6b9a]",
                listing.rank === 3 && "bg-[#b45309]",
                listing.rank > 3 && "bg-slate-500"
              )}
            >
              #{listing.rank}
            </span>
            <h2 className="font-[family-name:var(--font-display)] text-xl text-foreground">
              {listing.title ?? `Listing ${listing.listing_id.slice(0, 8)}`}
            </h2>
          </div>
          <p className="text-sm text-muted-foreground">
            {listing.address ?? "Address unavailable"}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-sm font-medium">
              {formatMoney(listing.price_monthly)}
              <span className="font-normal text-muted-foreground"> / mo</span>
            </span>
            <span className="text-sm text-muted-foreground">
              Score {listing.score.toFixed(2)}
            </span>
            <ConstraintBadge score={listing.score} />
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-sm font-medium text-[#0f5444] underline-offset-4 hover:underline"
        >
          {open ? "Hide rationale" : "Show rationale"}
        </button>
      </div>
      {open ? (
        <p className="mt-4 border-t border-border/70 pt-4 text-sm leading-relaxed text-foreground/90">
          {listing.rationale}
        </p>
      ) : null}
    </article>
  );
}

export default function ResultsPage() {
  const params = useParams<{ id: string }>();
  const { getToken, isLoaded } = useAuth();
  const [data, setData] = useState<RequestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isLoaded || !params.id) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await getRequest(params.id, () => getToken());
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Failed to load results"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [getToken, isLoaded, params.id]);

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
        <p className="text-muted-foreground">Loading results…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
        <p className="text-destructive">{error ?? "Results unavailable"}</p>
        <Link href="/history" className="mt-4 inline-block text-sm text-[#0f5444]">
          Back to history
        </Link>
      </div>
    );
  }

  if (data.status !== "completed" || !data.recommendation) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 px-4 py-12 sm:px-6">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-[#0f5444]">
          Results not ready
        </h1>
        <p className="text-muted-foreground">
          Status: <span className="font-medium text-foreground">{data.status}</span>
        </p>
        <Link
          href={`/request/${data.request_id}`}
          className="inline-block text-sm font-medium text-[#0f5444] underline-offset-4 hover:underline"
        >
          Open live pipeline view
        </Link>
      </div>
    );
  }

  const top3 = [...data.recommendation.ranked_listings]
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 3);

  if (top3.length === 0) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 px-4 py-12 sm:px-6">
        <h1 className="font-[family-name:var(--font-display)] text-3xl text-[#0f5444]">
          No ranked listings
        </h1>
        <p className="text-muted-foreground">
          This run completed but produced an empty recommendation — often because
          no listings matched the hard filters (budget / laundry / pets).
        </p>
        <Link
          href="/request"
          className="inline-block text-sm font-medium text-[#0f5444] underline-offset-4 hover:underline"
        >
          Try a new request
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-10 px-4 py-10 sm:px-6">
      <header className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Request {data.request_id}
        </p>
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[#0f5444] sm:text-4xl">
          Top recommendations
        </h1>
        {data.anchor_address ? (
          <p className="text-muted-foreground">
            Anchor: {data.anchor_address}
            {data.budget_max != null
              ? ` · Budget ${formatMoney(data.budget_max)}`
              : null}
          </p>
        ) : null}
      </header>

      <section className="space-y-4">
        {top3.map((listing) => (
          <RankedCard key={listing.listing_id} listing={listing} />
        ))}
      </section>

      <section className="space-y-3">
        <h2 className="font-[family-name:var(--font-display)] text-2xl text-foreground">
          Trade-offs
        </h2>
        <p className="max-w-3xl text-base leading-relaxed text-foreground/90">
          {data.recommendation.trade_off_narrative}
        </p>
        <div className="overflow-x-auto rounded-xl border border-border bg-card/70">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-border bg-secondary/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Candidate</th>
                <th className="px-4 py-3 font-medium">Price</th>
                <th className="px-4 py-3 font-medium">Commute</th>
                <th className="px-4 py-3 font-medium">Safety</th>
                <th className="px-4 py-3 font-medium">Risk</th>
                <th className="px-4 py-3 font-medium">Affordable</th>
              </tr>
            </thead>
            <tbody>
              {top3.map((listing) => (
                <tr
                  key={listing.listing_id}
                  className="border-b border-border/70 last:border-0"
                >
                  <td className="px-4 py-3">
                    <span className="font-medium">#{listing.rank}</span>{" "}
                    {listing.title ?? listing.listing_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3">
                    {formatMoney(listing.price_monthly)}
                  </td>
                  <td className="px-4 py-3">
                    {listing.walk_minutes != null
                      ? `${listing.walk_minutes} min`
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {listing.safety_score != null
                      ? `${listing.safety_score}/5`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 capitalize">
                    {listing.risk_level ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    {listing.is_affordable == null
                      ? "—"
                      : listing.is_affordable
                        ? "Yes"
                        : "No"}
                    {listing.pct_of_budget != null
                      ? ` (${Math.round(listing.pct_of_budget)}%)`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-[family-name:var(--font-display)] text-2xl text-foreground">
          Map
        </h2>
        <p className="text-sm text-muted-foreground">
          Red circle is the commute anchor; numbered pins are the top candidates.
        </p>
        <ResultsMap
          anchorAddress={data.anchor_address}
          anchorLat={data.anchor_lat}
          anchorLon={data.anchor_lon}
          listings={top3}
        />
      </section>
    </div>
  );
}
