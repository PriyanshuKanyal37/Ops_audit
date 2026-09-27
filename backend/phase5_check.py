"""Phase 5 check: the follow-up email and Slack alert jobs, the "call booked" message, Shiv's feedback links and
funnel tracking, against the real database with fake Slack and fake Resend servers. Never contacts anyone real
and never calls Claude. Test rows are deleted afterwards.

Usage:  python phase5_check.py        (port 8100 must be free)
"""

import asyncio
import json
import re
import threading
from http.server import HTTPServer

import httpx

import capture_check
import config
import db
import funnel_report
import guard
import jobs
from capture_check import FakeResend
from protection_check import API, SLACK_PORT, Backend, FakeSlack, slack_posts

SAMPLE = "y-Coy4Ov2DoW"  # a saved report to copy; real rows are never changed
PREFIX = "p5test_"
VISITOR = "p5test-visitor-0001"
passed = 0


def check(name: str, condition: bool) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAILED: {name}")
    passed += 1
    print(f"  ✅ {name}")


async def add_row(name: str, hours_ago: float, band: str = "200k_350k", url_type: str = "full",
                  email: str | None = None, **flags) -> str:
    audit_id = PREFIX + name
    await db._pool.execute(
        """insert into audits (id, submitted_at, ip_hash, website_url, url_type, q1, q2, q3, mrr_band, q5, report,
             top_leak_pillar, total_leakage_low, total_leakage_high, cta_route, report_email)
           select $1, now() - make_interval(secs => $2), ip_hash, website_url, $3, q1, q2, q3, $4, q5,
                  jsonb_set(report, '{display_name}', '"Acme <&> Co"'), top_leak_pillar, total_leakage_low,
                  total_leakage_high, cta_route, $5
           from audits where id = $6""", audit_id, hours_ago * 3600, url_type, band, email, SAMPLE)
    for column, value in flags.items():
        await db._pool.execute(f"update audits set {column} = $2 where id = $1", audit_id, value)
    return audit_id


async def row(audit_id: str) -> dict:
    return dict(await db._pool.fetchrow("select * from audits where id = $1", audit_id))


async def jobs_checks() -> None:
    real_due = await db._pool.fetchval(
        """select count(*) from audits where id not like 'p5test_%' and submitted_at < now() - interval '24 hours'
           and submitted_at > now() - interval '7 days' and (not followup_email_sent or not slack_alert_sent)""")
    if real_due:
        raise SystemExit(f"{real_due} real audits are due for a job; not running, so they aren't marked as sent.")
    config.RESEND_API_KEY, config.RESEND_API_URL = "re_test_key", f"http://127.0.0.1:{capture_check.RESEND_PORT}/emails"
    config.SLACK_WEBHOOK_URL, config.FRONTEND_URL = f"http://127.0.0.1:{SLACK_PORT}/hook", "http://localhost:3100"

    print("\n48-hour follow-up email (PRD §10.1) and 24-hour Slack alert (PRD §10.3)")
    due = await add_row("followup_due", 50, band="50k_100k", email="founder@example.com")
    await add_row("followup_clicked", 50, band="50k_100k", email="a@example.com", clicked_cta=True)
    await add_row("followup_ce_visit", 50, band="50k_100k", email="b@example.com", visited_ce_page=True)
    await add_row("followup_too_soon", 30, band="50k_100k", email="c@example.com")
    await add_row("followup_too_old", 24 * 8, band="50k_100k", email="d@example.com")
    alert = await add_row("alert_due", 26)
    await add_row("alert_small_firm", 26, band="50k_100k")
    await add_row("alert_booked", 26, call_booked=True)
    await add_row("alert_unreachable", 26, url_type="none")
    alert_email = await add_row("alert_no_site_email", 26, url_type="none", email="e@example.com")
    await add_row("alert_too_soon", 20)

    result = await jobs.run_once()
    check("One follow-up sent (48h+, emailed report, no click / Client Engine visit / booking, under 7 days)",
          result["followups"] == 1 and len(capture_check.emails) == 1
          and capture_check.emails[0]["to"] == ["founder@example.com"])
    mail = capture_check.emails[0]
    check("Follow-up names the top gap, what we'd fix first, and links the report and the booking page",
          "Your biggest gap was" in mail["text"] and "What we'd fix first:" in mail["text"]
          and f"http://localhost:3100/audit/r/{due}" in mail["text"]
          and f"http://localhost:3100/audit/book?audit={due}" in mail["text"]
          and "only follow-up" in mail["text"])
    check("Follow-up escapes the company name in HTML", "Acme &lt;&amp;&gt; Co" in mail["html"])
    check("Two Slack alerts ($100K+, 24h+, not booked, reachable) and the unreachable one skipped",
          result["slack_alerts"] == 2 and len(slack_posts) == 2)
    by_id = {aid: next(p for p in slack_posts if f"/audit/r/{aid}|" in p) for aid in (alert, alert_email)}
    post = by_id[alert]
    band = (await db.get_report(SAMPLE))["band_label"]
    check("Alert has revenue, total, top gap, the 3 gaps and how to reach them",
          f"Revenue: {band} a month" in post and "Losing an estimated $" in post and "Top gap:" in post
          and post.count(" · ") >= 2 and "Reach them through their website" in post)
    check("Alert escapes Slack control characters in the company name", "Acme &lt;&amp;&gt; Co" in post)
    check("Alert carries a signed feedback link", guard.feedback_link(alert) in post)
    check("No website but an email → the alert shows the email", "Email: e@example.com" in by_id[alert_email])
    flags = {r["id"][len(PREFIX):]: (r["followup_email_sent"], r["slack_alert_sent"]) for r in
             await db._pool.fetch("select id, followup_email_sent, slack_alert_sent from audits where id like 'p5test_%'")}
    check("Only the sent rows are flagged", {k for k, v in flags.items() if v[0]} == {"followup_due"}
          and {k for k, v in flags.items() if v[1]} == {"alert_due", "alert_no_site_email"})
    check("Running again sends nothing twice", await jobs.run_once() == {"followups": 0, "slack_alerts": 0})

    capture_check.resend_should_fail = True
    retry = await add_row("followup_retry", 50, band="50k_100k", email="f@example.com")
    check("Resend down → nothing counted as sent", (await jobs.run_once())["followups"] == 0)
    check("…and the row is released for the next run", (await row(retry))["followup_email_sent"] is False)
    capture_check.resend_should_fail = False
    check("Next run sends it", (await jobs.run_once())["followups"] == 1)

    config.SLACK_WEBHOOK_URL = ""
    late = await add_row("alert_no_webhook", 26)
    check("No Slack webhook → no alert claimed, the row waits",
          (await jobs.run_once())["slack_alerts"] == 0 and (await row(late))["slack_alert_sent"] is False)


async def http_checks() -> None:
    booked = await add_row("booked", 1)
    track = lambda event, audit_id=booked: httpx.post(f"{API}/api/track", headers={"Content-Type": "text/plain"},
                                                      content=json.dumps({"id": audit_id, "event": event}), timeout=10)
    with Backend(TURNSTILE_SECRET_KEY="", JOBS_ENABLED=""):
        check("/health shows jobs switched off by default", httpx.get(f"{API}/health").json()["jobs"] is False)

        print("\n\"Call booked\" Slack message")
        before = len(slack_posts)
        check("Booking → 204, call_booked set", track("booked").status_code == 204 and (await row(booked))["call_booked"])
        post = slack_posts[-1] if len(slack_posts) > before else ""
        check("…and one 'Call booked' message with the report and feedback links",
              "Call booked from the Ops Clarity Audit" in post and f"/audit/r/{booked}|" in post
              and guard.feedback_link(booked) in post)
        track("booked")
        check("A second booking event sends no second message", len(slack_posts) == before + 1)

        print("\nShiv's feedback links (PRD §12.4)")
        link = guard.feedback_link(booked).replace(config.PUBLIC_API_URL, API)
        page = httpx.get(link, timeout=10)
        check("Signed link → page with the company, top gap and 3 answer buttons",
              page.status_code == 200 and "Acme &lt;&amp;&gt; Co" in page.text and page.text.count("<button") == 3)
        check("Opening the link records nothing (safe from link previews)", (await row(booked))["top_leak_was_correct"] is None)
        check("Tampered signature → 403", httpx.get(link[:-2] + "00", timeout=10).status_code == 403)
        other = guard.feedback_link(PREFIX + "missing").replace(config.PUBLIC_API_URL, API)
        check("Valid signature, unknown report → 404", httpx.get(other, timeout=10).status_code == 404)
        saved = httpx.post(link + "&answer=partly", timeout=10)
        check("Pressing 'Partly' → saved", saved.status_code == 200 and "Saved" in saved.text
              and (await row(booked))["top_leak_was_correct"] == "partly")
        check("Page then shows the recorded answer", "Recorded so far" in httpx.get(link, timeout=10).text)
        check("Unknown answer → 422", httpx.post(link + "&answer=maybe", timeout=10).status_code == 422)
        check("Tampered signature can't save", httpx.post(link[:-2] + "00&answer=no", timeout=10).status_code == 403
              and (await row(booked))["top_leak_was_correct"] == "partly")

        print("\nFunnel tracking (PRD §12.1)")
        send = lambda body: httpx.post(f"{API}/api/funnel", content=body, headers={"Content-Type": "text/plain"},
                                       timeout=10)
        for step in ("landing_view", "q1_answered", "url_given", "q4_reached", "q4_answered"):
            check(f"'{step}' → 204", send(json.dumps({"visitor": VISITOR, "event": step})).status_code == 204)
        send(json.dumps({"visitor": VISITOR, "event": "q1_answered"}))
        stored = await db._pool.fetch("select event from funnel_events where visitor_id = $1", VISITOR)
        check("Stored once per visitor per step (a repeat is ignored)", len(stored) == 5)
        check("Unknown step → 400", send(json.dumps({"visitor": VISITOR, "event": "hack"})).status_code == 400)
        check("Bad visitor id → 400", send(json.dumps({"visitor": "<script>", "event": "q1_answered"})).status_code == 400)
        check("Garbage → 400", send("not json").status_code == 400)

    text = funnel_report.report(await db.funnel_counts(1), 1)
    check("Funnel report lists every PRD step with its target",
          all(s in text for s in ("Landing → started Q1", "Q4 → Q5", "Report → button click", "45%", "90%")))
    check("…and the watch items", "Q4 drop-off" in text and "Website unreadable" in text and "call feedback" in text)


async def main() -> None:
    servers = [HTTPServer(("127.0.0.1", capture_check.RESEND_PORT), FakeResend),
               HTTPServer(("127.0.0.1", SLACK_PORT), FakeSlack)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    await db.init()
    try:
        await jobs_checks()
        await http_checks()
    finally:
        deleted = await db._pool.execute("delete from audits where id like 'p5test_%'")
        await db._pool.execute("delete from funnel_events where visitor_id = $1", VISITOR)
        print(f"\nCleanup: {re.sub(r'DELETE ', '', deleted)} test audits and the test visitor deleted")
        await db.close()
        for server in servers:
            server.shutdown()
    print(f"All {passed} Phase 5 checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
