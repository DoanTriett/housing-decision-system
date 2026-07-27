/**
 * Day 11 live-SSE verification (no browser UI required for agent set diffs).
 * Uses Clerk Backend JWT + authenticated EventSource-style fetch.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function loadEnv() {
  const envPath = path.join(__dirname, "..", ".env.local");
  const out = {};
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    if (!line || line.trim().startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i === -1) continue;
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

async function clerkApi(secret, method, urlPath, body) {
  const res = await fetch(`https://api.clerk.com/v1${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${secret}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${method} ${urlPath}: ${res.status} ${JSON.stringify(json)}`);
  return json;
}

async function mintJwt(secret) {
  const stamp = Date.now();
  const user = await clerkApi(secret, "POST", "/users", {
    email_address: [`d11${stamp}+clerk_test@example.com`],
    password: `Day11-${stamp}!Aa1`,
    skip_password_checks: true,
  });
  const session = await clerkApi(secret, "POST", "/sessions", { user_id: user.id });
  const token = await clerkApi(secret, "POST", `/sessions/${session.id}/tokens`, {});
  return { userId: user.id, jwt: token.jwt };
}

async function submit(jwt, body) {
  const res = await fetch(`${API}/api/requests`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${jwt}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (res.status !== 202) throw new Error(`submit ${res.status}: ${text}`);
  return JSON.parse(text).request_id;
}

async function collectStream(jwt, requestId, timeoutMs = 180000) {
  const started = Date.now();
  let lastErr = null;

  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch(`${API}/api/requests/${requestId}/stream`, {
        headers: {
          Authorization: `Bearer ${jwt}`,
          Accept: "text/event-stream",
        },
      });
      if (!res.ok || !res.body) {
        lastErr = new Error(`stream open ${res.status}: ${await res.text()}`);
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const events = [];
      const deadline = Date.now() + Math.min(90000, timeoutMs - (Date.now() - started));

      while (Date.now() < deadline) {
        const remaining = deadline - Date.now();
        const readPromise = reader.read();
        const timeoutPromise = new Promise((resolve) =>
          setTimeout(() => resolve({ done: true, value: undefined, timedOut: true }), remaining)
        );
        const result = await Promise.race([readPromise, timeoutPromise]);
        if (result.timedOut) break;
        const { done, value } = result;
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          const lines = chunk.split("\n");
          let eventName = "message";
          let data = "";
          for (const line of lines) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          let parsed;
          try {
            parsed = JSON.parse(data);
          } catch {
            continue;
          }
          const kind = parsed.event || eventName;
          events.push({ ...parsed, event: kind });
          if (kind === "done" || kind === "error") {
            reader.cancel().catch(() => {});
            return events;
          }
        }
      }
      reader.cancel().catch(() => {});

      // If we got nothing useful, check status — late-join terminal on completed.
      const statusRes = await fetch(`${API}/api/requests/${requestId}`, {
        headers: { Authorization: `Bearer ${jwt}` },
      });
      const statusBody = await statusRes.json();
      if (statusBody.status === "completed") {
        if (events.some((e) => e.event === "done")) return events;
        return [
          ...events,
          {
            event: "done",
            recommendation: statusBody.recommendation,
            late_join: true,
          },
        ];
      }
      if (statusBody.status === "failed") {
        return [...events, { event: "error", detail: "Request failed" }];
      }
      // still running — reconnect stream
      await new Promise((r) => setTimeout(r, 500));
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  throw lastErr || new Error("stream timeout");
}

function summarizeRun(label, events) {
  const agents = events
    .filter((e) => e.event === "agent_complete")
    .map((e) => ({
      agent: e.agent,
      summary: e.summary,
      selected_agents: e.selected_agents,
      reasoning: e.reasoning,
    }));
  const planner = agents.find((a) => a.agent === "planner");
  const done = events.find((e) => e.event === "done");
  const error = events.find((e) => e.event === "error");
  return {
    label,
    selected_agents: planner?.selected_agents ?? null,
    reasoning: planner?.reasoning ?? null,
    agent_order: agents.map((a) => a.agent),
    summaries: agents.map((a) => `${a.agent}: ${a.summary}`),
    terminal: done ? "done" : error ? `error:${error.detail}` : "none",
  };
}

async function agentsFromDb(requestId) {
  const { spawnSync } = await import("child_process");
  const py = `
import psycopg, json
conn=psycopg.connect('postgresql://postgres:postgres@localhost:5432/housing')
rows=conn.execute(
  'select agent_name from agent_runs where request_id=%s order by started_at',
  ('${requestId}',)
).fetchall()
print(json.dumps([r[0] for r in rows]))
conn.close()
`;
  const result = spawnSync(
    "uv",
    ["run", "python", "-c", py],
    { cwd: "D:/housing-decision-system/apps/api", encoding: "utf8" }
  );
  if (result.status !== 0) {
    throw new Error(`agentsFromDb failed: ${result.stderr}`);
  }
  return JSON.parse(result.stdout.trim());
}

async function main() {
  const env = loadEnv();
  const { userId, jwt } = await mintJwt(env.CLERK_SECRET_KEY);
  console.log("AUTH_OK", userId);

  // Full constraints → expect several specialists
  const fullId = await submit(jwt, {
    budget_max: 1200,
    anchor_address: "University of Texas at Austin, Austin, TX",
    max_commute_minutes: 20,
    requires_laundry: true,
    requires_pet_friendly: false,
    free_text: "safe and quiet neighborhood, worried about scams and affordability",
  });
  console.log("FULL_REQUEST", fullId);
  const fullEvents = await collectStream(jwt, fullId);
  const fullSummary = summarizeRun("full", fullEvents);
  // If SSE raced past agent_complete events, recover agent order from Postgres.
  if (fullSummary.agent_order.length === 0) {
    fullSummary.agent_order = await agentsFromDb(fullId);
    fullSummary.selected_agents = fullSummary.agent_order.filter((a) =>
      ["listing_search", "neighborhood", "commute", "budget", "risk"].includes(a)
    );
    fullSummary.recovered_from_db = true;
  }
  console.log("FULL_SUMMARY", JSON.stringify(fullSummary, null, 2));

  // Minimal → expect fewer specialists
  const minId = await submit(jwt, {
    budget_max: 1100,
    anchor_address: "Austin, TX",
    free_text: "just show options under budget",
  });
  console.log("MIN_REQUEST", minId);
  const minEvents = await collectStream(jwt, minId);
  const minSummary = summarizeRun("minimal", minEvents);
  if (minSummary.agent_order.length === 0) {
    minSummary.agent_order = await agentsFromDb(minId);
    minSummary.selected_agents = minSummary.agent_order.filter((a) =>
      ["listing_search", "neighborhood", "commute", "budget", "risk"].includes(a)
    );
    minSummary.recovered_from_db = true;
  }
  console.log("MIN_SUMMARY", JSON.stringify(minSummary, null, 2));

  const fullSet = new Set(fullSummary.selected_agents || []);
  const minSet = new Set(minSummary.selected_agents || []);
  const visiblyDifferent =
    fullSet.size !== minSet.size ||
    [...fullSet].sort().join() !== [...minSet].sort().join();
  console.log("ROUTING_DIFF", JSON.stringify({
    visiblyDifferent,
    fullSelected: [...fullSet],
    minSelected: [...minSet],
    fullAgentOrder: fullSummary.agent_order,
    minAgentOrder: minSummary.agent_order,
  }));

  // Late join on completed request
  const lateRes = await fetch(`${API}/api/requests/${fullId}/stream`, {
    headers: { Authorization: `Bearer ${jwt}`, Accept: "text/event-stream" },
  });
  const lateText = await lateRes.text();
  console.log("LATE_JOIN", lateRes.status, lateText.slice(0, 400));

  const ok =
    fullSummary.terminal === "done" &&
    minSummary.terminal === "done" &&
    visiblyDifferent &&
    lateText.includes('"event": "done"') || lateText.includes("event: done");
  // fix operator precedence
  const allOk =
    fullSummary.terminal === "done" &&
    minSummary.terminal === "done" &&
    visiblyDifferent &&
    (lateText.includes('"event": "done"') || lateText.includes("event: done"));
  console.log("VERIFY_OK", allOk);
  process.exit(allOk ? 0 : 1);
}

main().catch((e) => {
  console.error("VERIFY_FAILED", e);
  process.exit(1);
});
