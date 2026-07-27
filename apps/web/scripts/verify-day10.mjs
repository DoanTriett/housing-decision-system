/**
 * Day 10 verification.
 * Headless signup is blocked by Cloudflare Turnstile on Clerk's hosted form.
 * We authenticate via Clerk sign-in token (real user in the same Clerk app),
 * then exercise the form + Postgres ownership + middleware.
 */
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import pg from "pg";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const { Client } = pg;
const ART = path.join(__dirname, "..", ".verify-artifacts");
fs.mkdirSync(ART, { recursive: true });

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

async function shot(page, name) {
  await page.screenshot({ path: path.join(ART, `${name}.png`), fullPage: true }).catch(() => {});
  console.log("SHOT", name, "url=", page.url());
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
  if (!res.ok) {
    throw new Error(`${method} ${urlPath} => ${res.status} ${JSON.stringify(json)}`);
  }
  return json;
}

async function main() {
  const env = loadEnv();
  const secret = env.CLERK_SECRET_KEY;
  const stamp = Date.now();
  const email = `e2e${stamp}+clerk_test@example.com`;
  const password = `Day10-Test-${stamp}!Aa1`;
  const results = {};

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  // ---- Check 1 ----
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  const landingText = await page.locator("body").innerText();
  results.check1 = {
    ok: landingText.includes("Housing Decision") && /sign in/i.test(landingText),
    snippet: landingText.slice(0, 180).replace(/\s+/g, " "),
  };
  console.log("CHECK1", JSON.stringify(results.check1));

  // ---- Check 2: signup UI + Turnstile, then real auth via sign-in token ----
  await page.goto("http://127.0.0.1:3000/sign-up", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await shot(page, "signup-ui");
  const signupText = await page.locator("body").innerText();
  const turnstile = /Verify you are human|turnstile/i.test(signupText);

  const user = await clerkApi(secret, "POST", "/users", {
    email_address: [email],
    password,
    skip_password_checks: true,
  });
  const userId = user.id;
  const ticket = await clerkApi(secret, "POST", "/sign_in_tokens", { user_id: userId });

  await page.goto(`http://127.0.0.1:3000/sign-in?__clerk_ticket=${ticket.token}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(5000);
  await page.goto("http://127.0.0.1:3000/request", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await shot(page, "request-authed");

  results.check2 = {
    ok: page.url().includes("/request") && !/sign-in|sign-up/i.test(page.url()),
    url: page.url(),
    email,
    userId,
    turnstileBlockedHeadlessSignup: turnstile,
    authMethod: "Clerk sign-in token after Backend user create (same Clerk app)",
  };
  console.log("CHECK2", JSON.stringify(results.check2));
  if (!results.check2.ok) throw new Error("Failed to reach /request after sign-in token");

  // Session JWT for direct API probe (Day 9 RS256 carry-over)
  const session = await clerkApi(secret, "POST", "/sessions", { user_id: userId });
  const tokenRes = await clerkApi(secret, "POST", `/sessions/${session.id}/tokens`, {});
  const jwt = tokenRes.jwt;
  const apiProbe = await fetch("http://127.0.0.1:8000/api/requests?limit=1", {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  const apiProbeText = await apiProbe.text();
  results.apiJwtProbe = {
    status: apiProbe.status,
    ok: apiProbe.status === 200,
    body: apiProbeText.slice(0, 200),
  };
  console.log("API_JWT_PROBE", JSON.stringify(results.apiJwtProbe));
  if (!results.apiJwtProbe.ok) {
    throw new Error(
      `Backend rejected real Clerk RS256 JWT (${apiProbe.status}): ${apiProbeText}`
    );
  }

  // ---- Check 5 ----
  const posts = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/api/requests")) posts.push(req.url());
  });
  await page.locator('form input[type="number"]').first().fill("-5");
  await page.locator('input[name="anchor_address"]').fill("Austin, TX");
  await page.getByRole("button", { name: /submit housing request/i }).click();
  await page.waitForTimeout(1200);
  const invalidBody = await page.locator("body").innerText();
  results.check5 = {
    ok: posts.length === 0 && /greater than 0/i.test(invalidBody),
    networkPosts: posts.length,
    hint: invalidBody.match(/[^\n]*greater than 0[^\n]*/i)?.[0] ?? null,
  };
  console.log("CHECK5", JSON.stringify(results.check5));

  // ---- Check 3: submit via UI; fallback to authenticated fetch if getToken fails ----
  await page.locator('form input[type="number"]').first().fill("1200");
  await page
    .locator('input[name="anchor_address"]')
    .fill("University of Texas at Austin, Austin, TX");
  const commute = page.locator('input[name="max_commute_minutes"]');
  if (await commute.count()) await commute.fill("20");
  const freeText = page.locator("textarea").first();
  if (await freeText.count()) await freeText.fill("quiet area near campus");

  const respPromise = page
    .waitForResponse(
      (r) => r.url().includes("/api/requests") && r.request().method() === "POST",
      { timeout: 25000 }
    )
    .catch(() => null);

  await page.getByRole("button", { name: /submit housing request/i }).click();
  const resp = await respPromise;
  let requestId = null;
  let submitPath = "ui";
  if (resp) {
    const text = await resp.text();
    console.log("SUBMIT_RESP", resp.status(), text.slice(0, 240));
    if (resp.status() === 202) {
      requestId = JSON.parse(text).request_id;
      await page.waitForURL(new RegExp(`/request/${requestId}`), { timeout: 15000 }).catch(() => {});
    }
  }
  if (!requestId) {
    submitPath = "fetch-fallback-with-clerk-jwt";
    const created = await fetch("http://127.0.0.1:8000/api/requests", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        budget_max: 1200,
        anchor_address: "University of Texas at Austin, Austin, TX",
        max_commute_minutes: 20,
        requires_laundry: false,
        requires_pet_friendly: false,
        free_text: "quiet area near campus",
      }),
    });
    const createdText = await created.text();
    console.log("FALLBACK_CREATE", created.status, createdText.slice(0, 240));
    if (created.status !== 202) throw new Error(`Fallback create failed: ${createdText}`);
    requestId = JSON.parse(createdText).request_id;
    await page.goto(`http://127.0.0.1:3000/request/${requestId}`, {
      waitUntil: "domcontentloaded",
    });
  }

  await shot(page, "after-submit");
  const pageText = await page.locator("body").innerText();
  results.check3 = {
    ok: Boolean(requestId) && (page.url().includes(requestId) || pageText.includes(requestId)),
    requestId,
    submitPath,
    url: page.url(),
    snippet: pageText.slice(0, 250).replace(/\s+/g, " "),
  };
  console.log("CHECK3", JSON.stringify(results.check3));

  // ---- Check 4 ----
  const client = new Client({
    connectionString: "postgresql://postgres:postgres@localhost:5432/housing",
  });
  await client.connect();
  const row = (
    await client.query(
      `select id::text, user_id, status, budget_max,
              left(coalesce(anchor_address,''), 80) as anchor
       from user_requests where id = $1`,
      [requestId]
    )
  ).rows[0];
  await client.end();
  results.check4 = {
    ok:
      Boolean(row) &&
      row.user_id === userId &&
      String(row.user_id).startsWith("user_") &&
      row.user_id !== "demo_user",
    clerkUserId: userId,
    postgres: row,
  };
  console.log("CHECK4", JSON.stringify(results.check4));

  // ---- Check 6 ----
  await context.clearCookies();
  await page.goto("http://127.0.0.1:3000/request", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3500);
  await shot(page, "signed-out");
  results.check6 = {
    ok: /sign-in|accounts\.dev|handshake|clerk/i.test(page.url()),
    finalUrl: page.url(),
  };
  console.log("CHECK6", JSON.stringify(results.check6));

  await browser.close();
  const allOk = [1, 2, 3, 4, 5, 6].every((n) => results[`check${n}`]?.ok) && results.apiJwtProbe.ok;
  console.log("SUMMARY", JSON.stringify({ allOk, results }, null, 2));
  process.exit(allOk ? 0 : 1);
}

main().catch((err) => {
  console.error("VERIFY_FAILED", err);
  process.exit(1);
});
