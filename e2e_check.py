"""Browser check for the founder flow and report page (Phase 2+), using the Edge already on Windows.

Needs the backend on :8100 and the frontend on :3100 (`npm run build && npm run start`).
Usage:  backend\\.venv\\Scripts\\python.exe e2e_check.py            report pages + flow, no Claude call
        backend\\.venv\\Scripts\\python.exe e2e_check.py --live     also submits one real audit (~$0.04)
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


def flow(page: Page, live: bool) -> None:
    print("\nQuestion form (all questions on one page)")
    page.goto(WEB)
    check("/ redirects to /audit", page.url.endswith("/audit"))
    check("Intro, all 5 questions and the website field are on one page",
          page.get_by_role("heading", level=1).is_visible() and page.locator("fieldset").count() == 5
          and page.locator("#website").is_visible())
    check("Questions are numbered 1–5 of 5", all(page.get_by_text(f"Question {n} of 5").count() == 1 for n in range(1, 6)))
    page.screenshot(path=OUT / f"form-empty-{page.viewport_size['width']}.png", full_page=True)

    page.get_by_role("button", name="See my report").click()
    check("Empty submit flags every question",
          page.get_by_text("Pick one option.").count() == 3 and page.get_by_text("Pick at least one option.").count() == 2
          and "Enter your website" in page.locator("#url-error").inner_text())
    check("…and moves focus to the first unanswered question", page.evaluate("document.activeElement.name") == "q1")
    page.screenshot(path=OUT / f"form-errors-{page.viewport_size['width']}.png", full_page=True)
    page.get_by_label("Getting consistent leads and bookings").check()
    check("Answering a question clears its error", page.locator("#q1-error").inner_text() == "")

    scrape_bodies: list[str] = []
    page.on("request", lambda r: scrape_bodies.append(r.post_data or "")
            if r.method == "POST" and r.url.endswith("/api/scrape") else None)
    page.fill("#website", "hello")
    page.locator("#website").blur()
    # Up to ~5s for Cloudflare's token on a fresh page load, then the server call.
    expect(page.locator("#url-error")).to_have_text("That doesn't look like a website address.", timeout=15_000)
    check("Junk website → the server's friendly error as soon as they leave the field", True)
    page.fill("#website", "pilot.com")
    with page.expect_response(lambda r: r.url.endswith("/api/scrape") and r.request.method == "POST") as response:
        page.locator("#website").blur()
    check("Real website → the background site read starts straight away (200)", response.value.status == 200
          and page.locator("#url-error").inner_text() == "")
    check("…and the request carried Cloudflare's Turnstile token",
          '"turnstile_token":"XXXX.DUMMY.TOKEN.XXXX"' in scrape_bodies[-1].replace(" ", ""))
    page.get_by_label("I don't have a website yet").check()
    check("'I don't have a website yet' disables the website field", page.locator("#website").is_disabled())
    page.get_by_label("I don't have a website yet").uncheck()

    page.get_by_label("Inbound through our website").check()
    page.get_by_label("Paid ads").check()
    page.get_by_label("Chasing status updates on active projects").check()
    page.get_by_label("I'd rather not say").check()
    page.get_by_label("A decent website, but no case studies or proof").check()
    check("Answers stay selected (radio + checkboxes)", page.get_by_label("Paid ads").is_checked()
          and page.get_by_label("I'd rather not say").is_checked())
    check(f"Form: no sideways scroll at {page.viewport_size['width']}px", no_sideways_scroll(page))
    page.screenshot(path=OUT / f"form-filled-{page.viewport_size['width']}.png", full_page=True)
    if "--blocked" in sys.argv:  # backend started with RATE_LIMIT_PER_HOUR=0: the audit is refused before Claude
        page.get_by_role("button", name="See my report").click()
        expect(page.get_by_role("heading", name="We hit a problem")).to_be_visible()
        check("Rate-limited founder sees the friendly limit message + Try again",
              "audits an hour" in page.locator("main").inner_text()
              and page.get_by_role("button", name="Try again").is_visible())
        check("No second site read on submit (the one from the website field is reused)", len(scrape_bodies) == 2)
        page.screenshot(path=OUT / "flow-blocked.png", full_page=True)
        return
    if not live:
        return

    page.get_by_role("button", name="See my report").click()
    expect(page.get_by_role("heading", name="Building your report")).to_be_visible()
    expect(page.get_by_text("Reading pilot.com…")).to_be_visible()
    page.wait_for_timeout(7000)
    check("Generating screen shows the PRD status lines with their real band",
          page.get_by_text("Sizing impact against $100K–$200K MRR…").is_visible())
    page.screenshot(path=OUT / "flow-4-generating.png", full_page=True)
    page.wait_for_url(re.compile(r"/audit/r/[\w-]+$"), timeout=120_000)
    check("Live audit lands on its report page", "is losing an estimated" in page.locator("h1").inner_text())
    check("Live report shows the inferred band", "(assumed)" in page.locator("section").first.inner_text())
    print(f"  ↳ new report: {page.url}")
    page.screenshot(path=OUT / "flow-5-live-report.png", full_page=True)


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
