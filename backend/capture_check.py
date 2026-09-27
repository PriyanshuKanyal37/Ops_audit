"""Phase 4 check: "email this to me" and click/booking tracking, against the real backend and database,
with a fake Resend server that records what would be emailed. Never calls Claude or the real Resend.

Usage:  python capture_check.py        (port 8100 must be free; uses a temporary copy of a saved report)
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

import config
import db
from protection_check import API, Backend

RESEND_PORT = 8198
SAMPLE, TEST_ID = "y-Coy4Ov2DoW", "capture_test_1"  # the test copies a saved report so real rows stay untouched
emails: list[dict] = []
resend_should_fail = False
passed = 0


def check(name: str, condition: bool) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAILED: {name}")
    passed += 1
    print(f"  ✅ {name}")


class FakeResend(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body["auth"] = self.headers.get("Authorization")
        if resend_should_fail:
            self.send_response(500)
        else:
            emails.append(body)
            self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"id":"fake"}')

    def log_message(self, *args):
        pass


def send(email: str, audit_id: str = TEST_ID) -> httpx.Response:
    return httpx.post(f"{API}/api/email-report", json={"id": audit_id, "email": email}, timeout=30)


async def flags() -> dict:
    row = await db._pool.fetchrow("select report_email, report_emails_sent, clicked_cta, visited_ce_page, call_booked"
                                  " from audits where id = $1", TEST_ID)
    return dict(row)


async def main() -> None:
    global resend_should_fail
    server = HTTPServer(("127.0.0.1", RESEND_PORT), FakeResend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    await db.init()
    # A copy of a saved report, with a name that would break HTML if it weren't escaped.
    await db._pool.execute(
        """insert into audits (id, ip_hash, url_type, q1, q2, q3, mrr_band, q5, report, top_leak_pillar,
             total_leakage_low, total_leakage_high, cta_route)
           select $1, ip_hash, url_type, q1, q2, q3, mrr_band, q5,
                  jsonb_set(report, '{display_name}', '"Pilot <b>&</b> Co"'), top_leak_pillar,
                  total_leakage_low, total_leakage_high, cta_route
           from audits where id = $2""", TEST_ID, SAMPLE)
    try:
        env = {"RESEND_API_KEY": "re_test_key", "RESEND_API_URL": f"http://127.0.0.1:{RESEND_PORT}/emails",
               "FRONTEND_URL": "http://localhost:3100", "TURNSTILE_SECRET_KEY": ""}
        print("\nEmail this report to me")
        with Backend(**env):
            check("/health reports email switched on", httpx.get(f"{API}/health").json()["email"] is True)
            check("Bad address → 422 friendly message", send("not-an-email").status_code == 422)
            check("Unknown report → 404", send("founder@example.com", "nope-nope").status_code == 404)

            response = send("  founder@example.com ")
            check("Valid request → 200 sent", response.status_code == 200 and response.json() == {"sent": True})
            sent = emails[-1]
            check("Sent to the right address, from EMAIL_FROM in .env, with the API key",
                  sent["to"] == ["founder@example.com"] and sent["from"] == config.EMAIL_FROM
                  and sent["auth"] == "Bearer re_test_key")
            print(f"     (from: {sent['from']})")
            check("Email contains the permalink, total and all 3 gaps",
                  f"http://localhost:3100/audit/r/{TEST_ID}" in sent["text"] and "$10,100–11,700" in sent["text"]
                  and sent["text"].count(" a month)") == 3)
            check("Company name is HTML-escaped (no injected markup)",
                  "Pilot &lt;b&gt;&amp;&lt;/b&gt; Co" in sent["html"] and "<b>&</b>" not in sent["html"])
            check("Says it's not a newsletter sign-up", "won't email you anything else" in sent["text"])
            row = await flags()
            check("report_email saved, 1 send counted", row["report_email"] == "founder@example.com"
                  and row["report_emails_sent"] == 1)

            resend_should_fail = True
            response = send("founder@example.com")
            resend_should_fail = False
            check("Resend down → 502 friendly message", response.status_code == 502 and "copy the link" in
                  response.json()["detail"])
            check("…and the failed send doesn't use up the limit", (await flags())["report_emails_sent"] == 1)
            send("founder@example.com")
            send("founder@example.com")
            response = send("founder@example.com")
            check("4th send → 429 'already been emailed 3 times'", response.status_code == 429
                  and "3 times" in response.json()["detail"])
            check("Exactly 3 emails went out", len(emails) == 3)

        with Backend(**{**env, "RESEND_API_KEY": ""}):
            await db._pool.execute("update audits set report_emails_sent = 0 where id = $1", TEST_ID)
            check("No Resend key → /health says so", httpx.get(f"{API}/health").json()["email"] is False)
            check("No Resend key → 502 friendly message, nothing counted",
                  send("founder@example.com").status_code == 502 and (await flags())["report_emails_sent"] == 0)

            print("\nClick and booking tracking")
            track = lambda body: httpx.post(f"{API}/api/track", content=body, timeout=10,
                                            headers={"Content-Type": "text/plain"})
            before = await flags()
            check("Flags start false", not (before["clicked_cta"] or before["visited_ce_page"] or before["call_booked"]))
            for event, column in [("cta_click", "clicked_cta"), ("ce_visit", "visited_ce_page"),
                                  ("booked", "call_booked")]:
                response = track(json.dumps({"id": TEST_ID, "event": event}))
                check(f"'{event}' (text/plain, as sendBeacon sends it) → 204 and {column} = true",
                      response.status_code == 204 and (await flags())[column] is True)
            check("Unknown event → 400", track(json.dumps({"id": TEST_ID, "event": "hack"})).status_code == 400)
            check("Garbage body → 400", track("not json").status_code == 400)
            check("Unknown report id → 204 (reveals nothing)",
                  track(json.dumps({"id": "nope", "event": "booked"})).status_code == 204)
    finally:
        await db._pool.execute("delete from audits where id = $1", TEST_ID)
        print(f"\nCleanup: test report {TEST_ID} deleted")
        await db.close()
        server.shutdown()
    print(f"All {passed} capture checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
