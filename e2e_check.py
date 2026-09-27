"""Browser check for the founder flow and report page (Phase 2+), using the Edge already on Windows.

Needs the backend on :8100 and the frontend on :3100 (`npm run build && npm run start`), both with Cloudflare's
Turnstile TEST keys (real keys block automated browsers) and the fake Resend on :8198:
  frontend: NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA npm run build   (the env var beats .env.local)
  backend:  TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA RESEND_API_KEY=re_test
            RESEND_API_URL=http://127.0.0.1:8198/emails uvicorn main:app --port 8100
The question flow holds back /api/audit, so no Claude call is made unless --live.
Usage:  backend\\.venv\\Scripts\\python.exe e2e_check.py            report pages + flow, no Claude call
        backend\\.venv\\Scripts\\python.exe e2e_check.py --live     also runs one real audit (~$0.03)
        backend\\.venv\\Scripts\\python.exe e2e_check.py --blocked  submit refused by the rate limit
                                                                  (start the backend with RATE_LIMIT_PER_HOUR=0)
Dev-only dependency: pip install playwright (not in requirements.txt).
Screenshots go to e2e_out/.
"""

import asyncio
import json
import pathlib
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent / "backend"))
import db  # type: ignore  # noqa: E402  (backend module on the path added above; checks/resets tracking flags)

WEB = "http://localhost:3100"
CE_REPORT, BOOKING_REPORT = "y-Coy4Ov2DoW", "igJjugSt29iu"  # saved in Phase 1 (one per CTA route)
OUT = pathlib.Path(__file__).parent / "e2e_out"
passed: list[str] = []


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"FAILED: {name}")
    passed.append(name)
    print(f"  ✅ {name}")


def no_sideways_scroll(page: Page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def report_pages(page: Page, width: int) -> None:
    print(f"\nReport pages at {width}px")
    page.goto(f"{WEB}/audit/r/{CE_REPORT}")
    h1 = page.locator("h1").inner_text()
    check("CE report: verdict sentence", "is losing an estimated" in h1 and re.search(r"\$[\d,]+–[\d,]+", h1) is not None)
    check("CE report: 3 leak cards", page.locator("ol > li").count() == 3)
    scorecard = page.locator("section", has=page.get_by_role("heading", name="Scorecard", exact=True))
    check("CE report: 4 scores in PRD order", scorecard.locator("h3").all_inner_texts()
          == ["Credibility", "Pipeline", "Conversion", "Delivery"])
    cta = page.get_by_role("link", name="Here's how it works. →")
    check("CE report: main button goes to the Client Engine page with the audit id",
          (cta.get_attribute("href") or "").endswith(f"/client-engine?audit={CE_REPORT}"))
    check("CE report: secondary link books a call",
          page.get_by_role("link", name=re.compile("Book a call")).get_attribute("href") == f"/audit/book?audit={CE_REPORT}")
    check("CE report: noindex", "noindex" in (page.locator('meta[name="robots"]').get_attribute("content") or ""))
    details = page.locator("details")
    check("'How we calculated this' is collapsed by default", not details.evaluate("d => d.open"))
    page.get_by_text("How we calculated this").click()
    check("…and opens on click", details.evaluate("d => d.open"))
    check(f"CE report: no sideways scroll at {width}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"report-client-engine-{width}.png", full_page=True)

    page.goto(f"{WEB}/audit/r/{BOOKING_REPORT}")
    book = page.get_by_role("link", name="Book 30 minutes →")
    check("Booking report: main button books a call", book.get_attribute("href") == f"/audit/book?audit={BOOKING_REPORT}")
    check("Booking report: no Client Engine button", page.get_by_role("link", name="Here's how it works. →").count() == 0)
    proof = page.locator("section", has=page.get_by_role("heading", name="Proof"))
    check("Booking report: Archaius proof card", "Archaius" in proof.inner_text())
    check("Proof card has no outbound link (Archaius rule 3)", proof.locator("a").count() == 0)
    check(f"Booking report: no sideways scroll at {width}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"report-booking-{width}.png", full_page=True)


def copy_and_404(page: Page) -> None:
    print("\nCopy link + unknown report")
    page.goto(f"{WEB}/audit/r/{CE_REPORT}")
    check("Permalink box shows this page's URL", page.locator("#permalink").input_value() == f"{WEB}/audit/r/{CE_REPORT}")
    page.get_by_role("button", name="Copy link").click()
    expect(page.get_by_text("Link copied.")).to_be_visible()
    check("Copy link copies the permalink", page.evaluate("navigator.clipboard.readText()") == f"{WEB}/audit/r/{CE_REPORT}")
    response = page.goto(f"{WEB}/audit/r/does-not-exist")
    check("Unknown report → 404 page", response.status == 404 and page.get_by_text("We couldn't find that report").is_visible())


RESEND_PORT = 8198  # start the backend with RESEND_API_KEY=re_test and RESEND_API_URL=http://127.0.0.1:8198/emails
emails: list[dict] = []


class FakeResend(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        emails.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"id":"fake"}')

    def log_message(self, *args):
        pass


def sql(query: str, *args):
    async def run():
        await db.init()
        try:
            return await db._pool.fetchrow(query, *args)
        finally:
            await db.close()
    # Playwright's sync API owns this thread's event loop, so the query runs on its own thread.
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, run()).result()


def sql_all(query: str, *args) -> list:
    async def run():
        await db.init()
        try:
            return await db._pool.fetch(query, *args)
        finally:
            await db.close()
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, run()).result()


def reset_sample_flags() -> None:
    sql("""update audits set clicked_cta = false, call_booked = false, visited_ce_page = false,
           report_emails_sent = 0, report_email = null where id = any($1)""", [CE_REPORT, BOOKING_REPORT])


def capture(page: Page) -> None:
    print("\nCapture: email me this report, tracking, booking page")
    reset_sample_flags()
    sent_before = len(emails)  # the desktop run has already sent one when the phone run starts
    # Playwright can't read a sendBeacon body, so we count beacons and check the database flags instead.
    beacons: list[str] = []
    page.on("request", lambda r: beacons.append(r.url) if r.url.endswith("/api/track") else None)
    flag = lambda column, audit_id=CE_REPORT: sql(f"select {column} from audits where id = $1", audit_id)[column]

    page.goto(f"{WEB}/audit/r/{CE_REPORT}")
    page.fill("#report-email", "founder@example.com")
    page.get_by_role("button", name="Email it to me").click()
    expect(page.get_by_text("Sent. Check your inbox")).to_be_visible()
    check("'Email it to me' → confirmation shown", True)
    check("…and the email really went out with the report link",
          emails and emails[-1]["to"] == ["founder@example.com"] and f"/audit/r/{CE_REPORT}" in emails[-1]["text"])
    page.fill("#report-email", "not-an-email")
    page.get_by_role("button", name="Email it to me").click()
    check("Invalid address is caught by the browser before sending",
          page.locator("#report-email").evaluate("el => !el.validity.valid") and len(emails) == sent_before + 1)
    page.screenshot(path=OUT / f"report-save-{page.viewport_size['width']}.png", full_page=True)

    page.get_by_role("link", name=re.compile("Book a call")).click()
    page.wait_for_url(re.compile(r"/audit/book\?audit="))
    page.wait_for_timeout(500)
    check("Secondary CTA sends a beacon before leaving and clicked_cta is saved",
          len(beacons) == 1 and flag("clicked_cta"))
    check("Booking page shows their report alongside",
          page.get_by_text("is losing an estimated").is_visible() and page.locator("aside li").count() == 3)
    check("No Calendly link yet → clear placeholder", page.get_by_text("Booking calendar not configured").is_visible())
    fire = "o => window.dispatchEvent(new MessageEvent('message', {origin: o, data: {event: 'calendly.event_scheduled'}}))"
    page.evaluate(fire, "https://evil.example")
    page.wait_for_timeout(500)
    check("A fake 'booked' message from another site is ignored",
          len(beacons) == 1 and not flag("call_booked") and page.get_by_text("You're booked").count() == 0)
    page.evaluate(fire, "https://calendly.com")
    expect(page.get_by_text("You're booked")).to_be_visible()
    page.wait_for_timeout(500)
    check("Calendly's booked message → 'You're booked' + call_booked saved", len(beacons) == 2 and flag("call_booked"))
    check(f"Booking page: no sideways scroll at {page.viewport_size['width']}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"book-{page.viewport_size['width']}.png", full_page=True)
    row = sql("select report_email, report_emails_sent from audits where id = $1", CE_REPORT)
    check("Database recorded the report email (1 send)",
          row["report_email"] == "founder@example.com" and row["report_emails_sent"] == 1)

    page.goto(f"{WEB}/audit/r/{BOOKING_REPORT}")
    page.get_by_role("link", name="Book 30 minutes →").click()
    page.wait_for_url(re.compile(rf"/audit/book\?audit={BOOKING_REPORT}"))
    page.wait_for_timeout(500)
    check("Delivery report: 'Book 30 minutes' is tracked and opens the booking page",
          flag("clicked_cta", BOOKING_REPORT))
    page.goto(f"{WEB}/audit/book")
    check("Booking page without a report still works", page.get_by_role("heading", level=1).is_visible()
          and page.locator("aside").count() == 0)
    reset_sample_flags()


PENDING: list = []  # /api/audit requests held back by the test, released when it decides the report is "ready"
FUNNEL_STEPS = {"landing_view", "q1_answered", "url_given", "q2_answered", "q3_answered", "q4_reached",
                "q4_answered", "q5_answered", "submitted", "email_given"}


def hold_audit(route) -> None:
    PENDING.append(route)


def release_audit(report_id: str = CE_REPORT) -> None:
    PENDING.pop().fulfill(status=200, content_type="application/json", body=json.dumps({"id": report_id}))


def answer_questions(page: Page) -> None:
    """Q1 → Q5 the quick way (the step-by-step checks are in flow)."""
    page.get_by_role("button", name="Getting consistent leads and bookings").click()
    page.fill("#website", "pilot.com")
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Question 2 of 5")).to_be_visible(timeout=20_000)
    page.get_by_label("Paid ads").check()
    page.get_by_role("button", name="Next").click()
    page.get_by_label("Chasing status updates on active projects").check()
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="I'd rather not say").click()
    page.get_by_role("button", name="A decent website, but no case studies or proof").click()


def flow(page: Page, live: bool) -> None:
    width = page.viewport_size["width"]
    print(f"\nQuestion flow: one screen at a time, then the email screen ({width}px)")
    reset_sample_flags()
    sent_before = len(emails)
    page.goto(WEB)
    check("/ redirects to /audit", page.url.endswith("/audit"))
    check("First screen: intro + Question 1 of 5 only (no website field, no other questions)",
          page.get_by_role("heading", level=1).is_visible() and page.get_by_text("Question 1 of 5").is_visible()
          and page.locator("#website").count() == 0 and page.get_by_text("Pick one to continue").is_visible())
    check(f"Q1 screen: no sideways scroll at {width}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"flow-1-q1-{width}.png", full_page=True)

    page.get_by_role("button", name="Getting consistent leads and bookings").click()
    expect(page.locator("#website")).to_be_visible()
    check("Picking a Q1 answer moves on to the website screen by itself",
          page.get_by_text("Your website", exact=True).is_visible())
    page.get_by_role("button", name="← Back").click()
    check("Back → Q1 with the answer still picked, and a Next button",
          page.get_by_role("button", name="Getting consistent leads and bookings").get_attribute("aria-pressed") == "true"
          and page.get_by_role("button", name="Next").is_visible())
    page.get_by_role("button", name="Next").click()

    page.get_by_role("button", name="Continue").click()
    check("Empty website → asks for it", "Enter your website" in page.locator("#step-error").inner_text())
    scrape_bodies: list[str] = []
    page.on("request", lambda r: scrape_bodies.append(r.post_data or "")
            if r.method == "POST" and r.url.endswith("/api/scrape") else None)
    page.fill("#website", "hello")
    page.get_by_role("button", name="Continue").click()
    # Up to ~5s for Cloudflare's token on a fresh page load, then the server call.
    expect(page.locator("#step-error")).to_have_text("That doesn't look like a website address.", timeout=15_000)
    check("Junk website → the server's friendly error, and it stays on the website screen",
          page.locator("#website").is_visible())
    page.screenshot(path=OUT / f"flow-2-website-error-{width}.png", full_page=True)
    page.fill("#website", "pilot.com")
    with page.expect_response(lambda r: r.url.endswith("/api/scrape") and r.request.method == "POST") as response:
        page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Question 2 of 5")).to_be_visible()
    check("Real website → the background site read starts (200) and Q2 shows", response.value.status == 200)
    check("…and the request carried Cloudflare's Turnstile token",
          '"turnstile_token":"XXXX.DUMMY.TOKEN.XXXX"' in scrape_bodies[-1].replace(" ", ""))

    page.get_by_role("button", name="Next").click()
    check("Multi-choice Next with nothing ticked → 'Pick at least one option.'",
          page.locator("#step-error").inner_text() == "Pick at least one option.")
    page.get_by_label("Inbound through our website").check()
    page.get_by_label("Paid ads").check()
    check("Ticking an option clears the message", page.locator("#step-error").inner_text() == "")
    page.screenshot(path=OUT / f"flow-3-q2-{width}.png", full_page=True)
    page.get_by_role("button", name="Next").click()
    page.get_by_label("Chasing status updates on active projects").check()
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_text("Question 4 of 5")).to_be_visible()
    page.get_by_role("button", name="I'd rather not say").click()
    expect(page.get_by_text("Question 5 of 5")).to_be_visible()
    check("Picking a Q4 answer moves on to Q5 by itself", True)
    page.get_by_role("button", name="← Back").click()
    check("Back from Q5 → Q4 still answered",
          page.get_by_role("button", name="I'd rather not say").get_attribute("aria-pressed") == "true")
    page.get_by_role("button", name="← Back").click()
    page.get_by_role("button", name="← Back").click()
    check("…and Q2's ticks are kept", page.get_by_label("Paid ads").is_checked())
    for _ in range(3):
        page.get_by_role("button", name="Next").click()  # Q2 → Q3 → Q4 → Q5
    expect(page.get_by_text("Question 5 of 5")).to_be_visible()

    if "--blocked" in sys.argv:  # backend started with RATE_LIMIT_PER_HOUR=0: the audit is refused before Claude
        page.get_by_role("button", name="A decent website, but no case studies or proof").click()
        page.get_by_role("button", name="See my report").click()
        page.fill("#email", "founder@example.com")
        page.get_by_role("button", name="Show my report").click()
        expect(page.get_by_role("heading", name="We hit a problem")).to_be_visible()
        check("Rate-limited founder sees the friendly limit message + Try again",
              "audits an hour" in page.locator("main").inner_text()
              and page.get_by_role("button", name="Try again").is_visible())
        check("No second site read at the end (the website screen's one is reused)", len(scrape_bodies) == 2)
        page.screenshot(path=OUT / "flow-blocked.png", full_page=True)
        return

    audit_bodies: list[str] = []
    page.on("request", lambda r: audit_bodies.append(r.post_data or "") if r.url.endswith("/api/audit") else None)
    if not live:
        page.route("**/api/audit", hold_audit)
    page.get_by_role("button", name="See my report").click()
    check("See my report with no Q5 answer → 'Pick one option.'",
          page.locator("#step-error").inner_text() == "Pick one option.")
    page.get_by_role("button", name="A decent website, but no case studies or proof").click()
    check("Q5 doesn't jump ahead: it waits for See my report", page.get_by_text("Question 5 of 5").is_visible())
    page.get_by_role("button", name="See my report").click()
    expect(page.get_by_role("heading", name="Where should we send your report?")).to_be_visible()
    check("See my report → email screen, and the report starts generating straight away",
          len(audit_bodies) == 1 and '"q4":"rather_not_say"' in audit_bodies[0].replace(" ", ""))
    check("Email screen shows the report being built for their site",
          page.get_by_text("Building your report for pilot.com…").is_visible())
    check("…with the cursor already in the email box", page.evaluate("document.activeElement.id") == "email")
    check(f"Email screen: no sideways scroll at {width}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"flow-4-email-{width}.png", full_page=True)
    page.get_by_role("button", name="Show my report").click()
    check("No email → asked for one (it's required)", "Enter your email address" in page.locator("#step-error").inner_text())
    page.fill("#email", "not-an-email")
    page.get_by_role("button", name="Show my report").click()
    check("Bad email → asked again, nothing sent", "Enter your email address" in page.locator("#step-error").inner_text()
          and len(emails) == sent_before)
    page.fill("#email", "founder@example.com")
    page.get_by_role("button", name="Show my report").click()
    expect(page.get_by_role("heading", name="Building your report")).to_be_visible()

    if live:
        page.wait_for_url(re.compile(r"/audit/r/[\w-]+$"), timeout=150_000)
        check("Live audit lands on its report page", "is losing an estimated" in page.locator("h1").inner_text())
        check("…with the inferred band", "(assumed)" in page.locator("section").first.inner_text())
        page.wait_for_timeout(1000)
        check("…and a copy of the link went to their inbox",
              emails and emails[-1]["to"] == ["founder@example.com"] and page.url.split("/")[-1] in emails[-1]["text"])
        print(f"  ↳ new report: {page.url}")
        page.screenshot(path=OUT / "flow-5-live-report.png", full_page=True)
        return

    check("Email given before the report is ready → the building screen, lines timed from See my report",
          page.get_by_text("Reading pilot.com…").is_visible())
    page.screenshot(path=OUT / f"flow-5-building-{width}.png", full_page=True)
    release_audit()
    page.wait_for_url(re.compile(rf"/audit/r/{CE_REPORT}$"), timeout=15_000)
    check("Report ready → their report opens", "is losing an estimated" in page.locator("h1").inner_text())
    page.wait_for_timeout(1000)
    check("…a copy of the report link was emailed to them", len(emails) == sent_before + 1
          and emails[-1]["to"] == ["founder@example.com"] and f"/audit/r/{CE_REPORT}" in emails[-1]["text"])
    check("…and their email is saved on the report",
          sql("select report_email from audits where id = $1", CE_REPORT)["report_email"] == "founder@example.com")
    visitor = page.evaluate("localStorage.getItem('audit_visitor')")
    steps = {row["event"] for row in sql_all("select event from funnel_events where visitor_id = $1", visitor)}
    check("Every funnel step was recorded, including the email", steps == FUNNEL_STEPS)

    if width == 1280:  # the other order: the report is ready before they type their email
        page.goto(f"{WEB}/audit")
        answer_questions(page)
        page.get_by_role("button", name="See my report").click()
        expect(page.get_by_role("heading", name="Where should we send your report?")).to_be_visible()
        release_audit()
        expect(page.get_by_text("Your report is ready")).to_be_visible()
        check("Report finishes while they're on the email screen → 'Your report is ready'", True)
        page.fill("#email", "founder@example.com")
        page.get_by_role("button", name="Show my report").click()
        page.wait_for_url(re.compile(rf"/audit/r/{CE_REPORT}$"), timeout=15_000)
        check("…and Show my report opens it straight away", "is losing an estimated" in page.locator("h1").inner_text())
    page.unroute("**/api/audit")
    sql("delete from funnel_events where visitor_id = $1 returning 1", visitor)  # test visits out of the funnel
    reset_sample_flags()


def main() -> None:
    live = "--live" in sys.argv
    OUT.mkdir(exist_ok=True)
    resend = HTTPServer(("127.0.0.1", RESEND_PORT), FakeResend)
    threading.Thread(target=resend.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for width, height in [(1280, 900), (390, 844)]:
            context = browser.new_context(viewport={"width": width, "height": height},
                                          permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            report_pages(page, width)
            if width == 1280:
                copy_and_404(page)
                capture(page)
                flow(page, live)
            else:
                capture(page)
                flow(page, live=False)  # mobile: layout + interactions, no second paid run
            context.close()
        browser.close()
    resend.shutdown()
    print(f"\nAll {len(passed)} checks passed. Screenshots in {OUT}")


if __name__ == "__main__":
    main()
