"""Phase 3 check: every protection path in PRD §9.4, against the real backend and database, with
Cloudflare's official Turnstile test keys and a fake Slack webhook. Never calls Claude.

Usage:  python protection_check.py        (port 8100 must be free; test rows are deleted afterwards)
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

import config
import db
import guard

API = "http://127.0.0.1:8100"
SLACK_PORT = 8199
PASS_SECRET, FAIL_SECRET = "1x0000000000000000000000000000000AA", "2x0000000000000000000000000000000AA"
DUMMY_TOKEN = "XXXX.DUMMY.TOKEN.XXXX"  # what Cloudflare's test site keys hand the browser
LIMITED_IP, FRESH_IP = "198.51.100.7", "198.51.100.8"  # documentation-only addresses (RFC 5737)
ANSWERS = {"q1": "A", "q2": ["referrals"], "q3": ["chasing_new_business"], "q4": "200k_350k", "q5": "dont_know"}
slack_posts: list[str] = []
passed = 0


def check(name: str, condition: bool) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAILED: {name}")
    passed += 1
    print(f"  ✅ {name}")


class FakeSlack(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server naming)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        slack_posts.append(json.loads(body)["text"])
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class Backend:
    """Runs uvicorn with overridden env vars (the real .env still supplies everything else)."""

    def __init__(self, **env):
        self.env = {**os.environ, "SLACK_WEBHOOK_URL": f"http://127.0.0.1:{SLACK_PORT}/hook", **env}

    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", "8100"], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                httpx.get(f"{API}/health", timeout=2)
                return self
            except httpx.HTTPError:
                time.sleep(0.5)
        raise RuntimeError("backend did not start")

    def __exit__(self, *exc):
        self.proc.terminate()
        self.proc.wait(10)


def scrape(token: str | None, ip: str = FRESH_IP) -> httpx.Response:
    return httpx.post(f"{API}/api/scrape", json={"url": "kalungi.com", "turnstile_token": token},
                      headers={"X-Forwarded-For": ip}, timeout=30)


def audit(session: str, ip: str) -> httpx.Response:
    return httpx.post(f"{API}/api/audit", json={"session": session, "answers": ANSWERS},
                      headers={"X-Forwarded-For": ip}, timeout=60)


async def add_rows(ip: str, count: int, hours_ago: float) -> None:
    for i in range(count):
        await db._pool.execute(
            """insert into audits (id, submitted_at, ip_hash, url_type, q1, q2, q3, mrr_band, q5, report)
               values ($1, now() - make_interval(secs => $2), $3, 'full', 'A', '{}', '{}', '100k_200k', 'x', '{}')""",
            f"ratelimit_test_{hours_ago}_{i}", hours_ago * 3600, guard.ip_hash(ip))


async def main() -> None:
    server = HTTPServer(("127.0.0.1", SLACK_PORT), FakeSlack)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    await db.init()
    try:
        print("\nTurnstile (Cloudflare test keys)")
        with Backend(TURNSTILE_SECRET_KEY=PASS_SECRET):
            health = httpx.get(f"{API}/health").json()
            check("/health reports turnstile and slack switched on", health["turnstile"] and health["slack"])
            response = scrape(None)
            check("No human-check token → 403 with a friendly message",
                  response.status_code == 403 and "human check" in response.json()["detail"])
            # (Cloudflare's always-pass test secret accepts ANY token, so "Cloudflare rejects it" is tested with the
            # always-fail secret below.)
            check("Empty token → 403 without asking Cloudflare", scrape("").status_code == 403)
            response = scrape(DUMMY_TOKEN)
            check("Valid token (Cloudflare's test pass) → 200 + session", response.status_code == 200
                  and "session" in response.json())
            session = response.json()["session"]
        with Backend(TURNSTILE_SECRET_KEY=FAIL_SECRET):
            check("Cloudflare says 'fail' → 403", scrape(DUMMY_TOKEN).status_code == 403)
        with Backend(TURNSTILE_SECRET_KEY=""):
            check("Turnstile not configured → /health says so", httpx.get(f"{API}/health").json()["turnstile"] is False)

        print("\nRate limit (3 an hour, 10 a day, per IP)")
        await add_rows(LIMITED_IP, 3, hours_ago=0.2)
        # The PRD's launch limits, whatever .env says (it's raised while testing locally).
        with Backend(TURNSTILE_SECRET_KEY=PASS_SECRET, RATE_LIMIT_PER_HOUR="3", RATE_LIMIT_PER_DAY="10"):
            response = audit(session, LIMITED_IP)
            check("4th audit within an hour → 429 'limit of 3 audits an hour'",
                  response.status_code == 429 and "limit of 3 audits an hour" in response.json()["detail"])
            await add_rows(LIMITED_IP, 7, hours_ago=5)
            response = audit(session, LIMITED_IP)
            check("11th audit within a day → 429 'limit of 10 audits a day'",
                  response.status_code == 429 and "limit of 10 audits a day" in response.json()["detail"])

        print("\nDaily spend cap + Slack alerts")
        spent = await db.spend_today()
        print(f"  (today's real spend so far: ${spent:.4f})")
        slack_posts.clear()
        with Backend(TURNSTILE_SECRET_KEY=PASS_SECRET, DAILY_SPEND_CAP_USD=str(spent / 2)):
            response = audit(session, FRESH_IP)
            check("Over the cap → 503 'paused for the rest of today' (Claude never called)",
                  response.status_code == 503 and "paused" in response.json()["detail"])
            audit(session, FRESH_IP)
            check("Cap alert posted to Slack exactly once", len(slack_posts) == 1 and "reached" in slack_posts[0])
            print(f"  ↳ Slack message: {slack_posts[0]}")

        # 80% level, in-process (a real 80–99% run would call Claude).
        slack_posts.clear()
        config.SLACK_WEBHOOK_URL = f"http://127.0.0.1:{SLACK_PORT}/hook"
        config.DAILY_SPEND_CAP_USD = spent / 0.85
        check("At 85% of the cap audits are still allowed", await guard.check_spend())
        await guard.check_spend()
        check("80% alert posted to Slack exactly once", len(slack_posts) == 1 and "passed 80%" in slack_posts[0])

        # Parallel requests: an audit still running counts towards the limit.
        config.RATE_LIMIT_PER_HOUR = 1
        fresh = guard.ip_hash(FRESH_IP)
        check("Fresh IP is allowed", await guard.rate_limit_message(fresh) is None)
        with guard.running(fresh):
            check("…but not while its first audit is still running", await guard.rate_limit_message(fresh) is not None)
        check("…and allowed again once it finishes", await guard.rate_limit_message(fresh) is None)
    finally:
        removed = await db._pool.execute("delete from audits where id like 'ratelimit_test_%'")
        print(f"\nCleanup: {removed.split()[-1]} test rows deleted")
        await db.close()
        server.shutdown()
    print(f"All {passed} protection checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
