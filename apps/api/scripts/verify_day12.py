"""Day 12 live verification: submit request, poll results, check observability/history/stale."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import redis
from sqlalchemy import text

from src.api.observability_constants import STALE_PENDING_SECONDS
from src.db.session import AsyncSessionLocal
from src.models.user_request import UserRequest

API = "http://127.0.0.1:8000"
WEB_ENV = Path(r"D:\housing-decision-system\apps\web\.env.local")


def load_clerk_secret() -> str:
    env: dict[str, str] = {}
    for line in WEB_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env["CLERK_SECRET_KEY"]


def clerk_jwt(secret: str) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    stamp = int(time.time())
    with httpx.Client(timeout=30) as client:
        user = client.post(
            "https://api.clerk.com/v1/users",
            headers=headers,
            json={
                "email_address": [f"d12v{stamp}+clerk_test@example.com"],
                "password": f"L{stamp}!Aa1",
                "skip_password_checks": True,
            },
        ).json()
        session = client.post(
            "https://api.clerk.com/v1/sessions",
            headers=headers,
            json={"user_id": user["id"]},
        ).json()
        jwt = client.post(
            f"https://api.clerk.com/v1/sessions/{session['id']}/tokens",
            headers=headers,
            json={},
        ).json()["jwt"]
    return user["id"], jwt


def wait_done(request_id: str, auth: dict[str, str], timeout_s: int = 300) -> dict:
    """Prefer GET polling; also peek Redis so we print agent events when available."""
    client = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    ps = client.pubsub()
    ps.subscribe(f"run_progress:{request_id}")
    start = time.time()
    last_status = None
    with httpx.Client(timeout=30) as http:
        while time.time() - start < timeout_s:
            # Drain any pubsub messages without blocking forever
            msg = ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
            while msg is not None:
                if msg.get("type") == "message":
                    ev = json.loads(msg["data"])
                    print("EVENT", ev.get("event"), ev.get("agent"), ev.get("summary"))
                    if ev.get("event") in ("done", "error"):
                        return ev
                msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.01)

            resp = http.get(f"{API}/api/requests/{request_id}", headers=auth)
            if resp.status_code == 200:
                body = resp.json()
                status = body.get("status")
                if status != last_status:
                    print("STATUS", status)
                    last_status = status
                if status == "completed":
                    return {"event": "done", "via": "poll"}
                if status == "failed":
                    return {"event": "error", "via": "poll", "detail": body.get("detail")}
            time.sleep(1.5)
    raise TimeoutError(f"pipeline timeout after {timeout_s}s")


def main() -> None:
    secret = load_clerk_secret()
    user_id, jwt = clerk_jwt(secret)
    auth = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    print("AUTH_OK", user_id)

    with httpx.Client(timeout=60) as client:
        # Full request that typically routes all agents
        submit = client.post(
            f"{API}/api/requests",
            headers=auth,
            json={
                "budget_max": 1400,
                "anchor_address": "University of Texas at Austin, Austin, TX",
                "max_commute_minutes": 25,
                "requires_laundry": True,
                "free_text": "safe quiet near campus, worried about scams",
            },
        )
        print("SUBMIT", submit.status_code, submit.text)
        submit.raise_for_status()
        rid = submit.json()["request_id"]

    done = wait_done(rid, auth, timeout_s=300)
    print("DONE_EVENT", json.dumps({k: done.get(k) for k in ("event", "detail")}, default=str))

    with httpx.Client(timeout=60) as client:
        result = client.get(f"{API}/api/requests/{rid}", headers=auth)
        print("GET_RESULT_STATUS", result.status_code)
        payload = result.json()
        # Trim rationale for readable paste
        rec = payload.get("recommendation") or {}
        listings = rec.get("ranked_listings") or []
        summary = {
            "request_id": payload.get("request_id"),
            "status": payload.get("status"),
            "anchor_address": payload.get("anchor_address"),
            "anchor_lat": payload.get("anchor_lat"),
            "anchor_lon": payload.get("anchor_lon"),
            "budget_max": payload.get("budget_max"),
            "trade_off_narrative": (rec.get("trade_off_narrative") or "")[:400],
            "ranked": [
                {
                    "rank": x.get("rank"),
                    "score": x.get("score"),
                    "title": x.get("title"),
                    "address": x.get("address"),
                    "price_monthly": x.get("price_monthly"),
                    "lat": x.get("lat"),
                    "lon": x.get("lon"),
                    "walk_minutes": x.get("walk_minutes"),
                    "safety_score": x.get("safety_score"),
                    "risk_level": x.get("risk_level"),
                    "is_affordable": x.get("is_affordable"),
                    "pct_of_budget": x.get("pct_of_budget"),
                    "rationale_snip": (x.get("rationale") or "")[:160],
                    "constraint_flag": (x.get("score") or 1) <= 0.5,
                }
                for x in listings[:3]
            ],
        }
        print("GET_RESULT_SUMMARY")
        print(json.dumps(summary, indent=2, default=str))

        hist = client.get(f"{API}/api/requests?limit=5&offset=0", headers=auth)
        print("HISTORY", hist.status_code, json.dumps(hist.json(), indent=2, default=str)[:2000])

        obs = client.get(f"{API}/api/admin/observability/summary", headers=auth)
        print("OBSERVABILITY_RAW")
        print(json.dumps(obs.json(), indent=2, default=str)[:4000])

        # Stale pending: insert directly so Celery never picks it up.
        stale_id = uuid.uuid4()
        created = datetime.now(tz=UTC) - timedelta(seconds=STALE_PENDING_SECONDS + 45)

        async def _insert_stale() -> None:
            async with AsyncSessionLocal() as session:
                session.add(
                    UserRequest(
                        id=stale_id,
                        user_id=user_id,
                        raw_text="stale verification",
                        budget_max=1100,
                        anchor_address="Downtown Austin, TX",
                        max_commute_minutes=15,
                        status="pending",
                    )
                )
                await session.flush()
                await session.execute(
                    text(
                        "UPDATE user_requests SET created_at = :created WHERE id = :id"
                    ),
                    {"created": created, "id": stale_id},
                )
                await session.commit()

        import asyncio

        asyncio.run(_insert_stale())
        print("STALE_INSERTED", str(stale_id))

    with httpx.Client(timeout=60) as client:
        obs2 = client.get(f"{API}/api/admin/observability/summary", headers=auth)
        obs2_json = obs2.json()
        stale_ids = [s["request_id"] for s in obs2_json.get("stale_pending", [])]
        print("STALE_PANEL_SNIPPET")
        print(
            json.dumps(
                [s for s in obs2_json.get("stale_pending", []) if s["request_id"] == str(stale_id)],
                indent=2,
                default=str,
            )
        )
        print("STALE_IN_OBS", str(stale_id) in stale_ids, str(stale_id))
        hist2 = client.get(f"{API}/api/requests?limit=10&offset=0", headers=auth)
        hist_items = hist2.json().get("items", [])
        stale_item = next(
            (i for i in hist_items if i["request_id"] == str(stale_id)), None
        )
        print("STALE_IN_HISTORY", json.dumps(stale_item, indent=2, default=str))


if __name__ == "__main__":
    main()
