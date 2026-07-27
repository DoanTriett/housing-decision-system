"use client";

/**
 * SSE client for `/api/requests/{id}/stream`.
 *
 * Auth approach: `@microsoft/fetch-event-source` with Clerk Bearer token
 * (native EventSource cannot set Authorization headers).
 */

import { useAuth } from "@clerk/nextjs";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useRef, useState } from "react";

import { API_BASE_URL } from "@/lib/config";
import type { RecommendationOutput } from "@/lib/types";
import type { AgentProgressEvent, StreamStatus } from "@/lib/stream-types";

type UseRequestStreamResult = {
  events: AgentProgressEvent[];
  status: StreamStatus;
  recommendation: RecommendationOutput | null;
  error: string | null;
  plannerReasoning: string | null;
  selectedAgents: string[] | null;
};

function parseEvent(eventName: string, raw: string): AgentProgressEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const obj = data as Record<string, unknown>;
  const kind = (obj.event as string | undefined) ?? eventName;

  if (kind === "agent_complete") {
    return {
      event: "agent_complete",
      agent: String(obj.agent ?? ""),
      summary: typeof obj.summary === "string" ? obj.summary : undefined,
      tokens: typeof obj.tokens === "number" ? obj.tokens : undefined,
      cost_usd: typeof obj.cost_usd === "number" ? obj.cost_usd : undefined,
      selected_agents: Array.isArray(obj.selected_agents)
        ? obj.selected_agents.map(String)
        : undefined,
      reasoning: typeof obj.reasoning === "string" ? obj.reasoning : undefined,
    };
  }
  if (kind === "done") {
    return {
      event: "done",
      recommendation: (obj.recommendation as RecommendationOutput | null) ?? null,
    };
  }
  if (kind === "error") {
    return {
      event: "error",
      detail: String(obj.detail ?? "Request failed"),
    };
  }
  if (kind === "status") {
    return { event: "status", status: String(obj.status ?? "") };
  }
  return null;
}

export function useRequestStream(requestId: string): UseRequestStreamResult {
  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;
  const [events, setEvents] = useState<AgentProgressEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [recommendation, setRecommendation] =
    useState<RecommendationOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plannerReasoning, setPlannerReasoning] = useState<string | null>(null);
  const [selectedAgents, setSelectedAgents] = useState<string[] | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!requestId) return;

    const controller = new AbortController();
    abortRef.current = controller;
    let settled = false;

    const append = (evt: AgentProgressEvent) => {
      setEvents((prev) => [...prev, evt]);
      if (evt.event === "agent_complete") {
        if (evt.agent === "planner") {
          if (evt.reasoning) setPlannerReasoning(evt.reasoning);
          if (evt.selected_agents) setSelectedAgents(evt.selected_agents);
        }
      }
      if (evt.event === "done") {
        settled = true;
        setRecommendation(evt.recommendation);
        setStatus("done");
      }
      if (evt.event === "error") {
        settled = true;
        setError(evt.detail);
        setStatus("error");
      }
      if (evt.event === "status" || evt.event === "agent_complete") {
        setStatus((prev) => (prev === "connecting" ? "streaming" : prev));
      }
    };

    (async () => {
      try {
        const token = await getTokenRef.current();
        if (!token) {
          setError("No Clerk session token available. Sign in and try again.");
          setStatus("error");
          return;
        }

        await fetchEventSource(
          `${API_BASE_URL}/api/requests/${requestId}/stream`,
          {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
              Accept: "text/event-stream",
            },
            signal: controller.signal,
            openWhenHidden: true,
            async onopen(response) {
              if (response.ok) {
                setStatus("streaming");
                return;
              }
              const text = await response.text().catch(() => response.statusText);
              throw new Error(
                `SSE open failed (${response.status}): ${text || response.statusText}`
              );
            },
            onmessage(msg) {
              if (!msg.data) return;
              const parsed = parseEvent(msg.event || "message", msg.data);
              if (parsed) append(parsed);
            },
            onclose() {
              if (!settled) {
                setStatus((prev) =>
                  prev === "error" || prev === "done" ? prev : "done"
                );
              }
            },
            onerror(err) {
              if (controller.signal.aborted) throw err;
              const message =
                err instanceof Error ? err.message : "SSE connection failed";
              setError(message);
              setStatus("error");
              throw err;
            },
          }
        );
      } catch (err) {
        if (controller.signal.aborted) return;
        if (!settled) {
          setError(err instanceof Error ? err.message : "Stream failed");
          setStatus("error");
        }
      }
    })();

    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [requestId]);

  return {
    events,
    status,
    recommendation,
    error,
    plannerReasoning,
    selectedAgents,
  };
}
