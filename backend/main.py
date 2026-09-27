"""Ops Clarity Audit v2: FastAPI app.

Run locally:  uvicorn main:app --reload --port 8100   (8000 is used by LadderFlow on this machine)
"""

import asyncio
import html
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import config
import db
import generate
import guard
import jobs
import library
import notify
import scrape

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("audit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    # Follow-up email + Slack alert loop (PRD §10). Off by default so a local backend never contacts anyone.
    background = asyncio.create_task(jobs.run_forever()) if config.JOBS_ENABLED else None
    log.info("Background jobs %s", "ON (every 10 minutes)" if background else "OFF (set JOBS_ENABLED=true to run them)")
    yield
    if background:
        background.cancel()
    await db.close()


app = FastAPI(title="Ops Clarity Audit", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    # "turnstile"/"slack" false means that protection is switched off (fine locally, never in production).
    return {"status": "ok", "db": await db.ping(), "turnstile": bool(config.TURNSTILE_SECRET_KEY),
            "slack": bool(config.SLACK_WEBHOOK_URL), "email": bool(config.RESEND_API_KEY), "jobs": config.JOBS_ENABLED}


# --- URL screen: human check, normalise the URL, start reading the site, hand back a session (PLAN §4.1) ---

class ScrapeRequest(BaseModel):
    url: str | None = Field(default=None, max_length=300)
    no_website: bool = False
    turnstile_token: str | None = Field(default=None, max_length=4096)


@app.post("/api/scrape")
async def start_scrape(body: ScrapeRequest, request: Request):
    if not await guard.verify_turnstile(body.turnstile_token, guard.client_ip(request)):
        raise HTTPException(403, "Please complete the quick human check, then try again.")
    if body.no_website:
        url, key, url_type = None, None, "none"
    else:
        try:
            url, key, url_type = scrape.normalize(body.url or "")
        except ValueError as error:
            raise HTTPException(422, str(error))
        await scrape.start(url, key, url_type)
    return {"session": guard.make_session({"url": url, "key": key, "url_type": url_type}), "url_type": url_type}


# --- After Q5: run the audit and save it (PLAN §4.3) ---

class Answers(BaseModel):  # allowed values come from library.py (type checkers can't read dynamic Literals)
    q1: Literal[tuple(library.Q1)]  # type: ignore
    q2: list[Literal[tuple(library.Q2)]] = Field(min_length=1)  # type: ignore
    q3: list[Literal[tuple(library.Q3)]] = Field(min_length=1)  # type: ignore
    q4: Literal[tuple(library.Q4)]  # type: ignore
    q5: Literal[tuple(library.Q5)]  # type: ignore


class AuditRequest(BaseModel):
    session: str
    answers: Answers


@app.post("/api/audit")
async def run_audit(body: AuditRequest, request: Request):
    try:
        session = guard.read_session(body.session)
    except (ValueError, KeyError):
        raise HTTPException(401, "Your session expired. Please enter your website again.")
    answers = body.answers.model_dump()
    answers["q2"] = list(dict.fromkeys(answers["q2"]))  # drop duplicate ticks, keep order
    answers["q3"] = list(dict.fromkeys(answers["q3"]))

    # Protection (PRD §9.4), checked before anything costs money.
    ip_digest = guard.ip_hash(guard.client_ip(request))
    limit_message = await guard.rate_limit_message(ip_digest)
    if limit_message:
        raise HTTPException(429, limit_message)
    if not await guard.check_spend():
        raise HTTPException(503, "The audit is paused for the rest of today. Please try again tomorrow.")

    with guard.running(ip_digest):
        try:
            report, stats = await generate.build_report(session["url"], session["key"], session["url_type"], answers)
        except generate.GenerationError as error:
            log.error("Audit failed: %s", error)
            raise HTTPException(502, "We couldn't generate your report just now. Please try again.")
        audit_id = secrets.token_urlsafe(9)
        report["id"] = audit_id
        await db.insert_audit(audit_id, ip_digest, answers, report, stats["cost_usd"])
    await guard.check_spend()  # alert straight away if this audit pushed spend past 80% or the cap
    log.info("Audit %s saved: %s, $%d-%d, route=%s, cost=$%.4f, %ss, tokens in/out=%d/%d, cache write/read=%d/%d",
             audit_id, report["domain"], report["total_low"], report["total_high"], report["cta_route"],
             stats["cost_usd"], stats.get("seconds"), stats["input_tokens"], stats["output_tokens"],
             stats["cache_write_tokens"], stats["cache_read_tokens"])
    return {"id": audit_id}


@app.get("/api/report/{audit_id}")
async def get_report(audit_id: str):
    report = await db.get_report(audit_id)
    if report is None:
        raise HTTPException(404, "Report not found.")
    return report


# --- Capture (Phase 4) ---

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailReportRequest(BaseModel):
    id: str = Field(max_length=40)
    email: str = Field(max_length=254)


@app.post("/api/email-report")
async def email_report(body: EmailReportRequest):
    """PRD §7.10 "email this to me": sends the permalink. Saves report_email; NOT newsletter consent."""
    address = body.email.strip()
    if not EMAIL_RE.match(address):
        raise HTTPException(422, "That email address doesn't look right. Please check it and try again.")
    if not await db.report_exists(body.id):
        raise HTTPException(404, "Report not found.")
    report = await db.claim_report_email(body.id, address, config.MAX_REPORT_EMAILS)
    if report is None:
        raise HTTPException(429, f"This report has already been emailed {config.MAX_REPORT_EMAILS} times. "
                                 "You can copy the link above instead.")
    subject, html_body, text_body = notify.report_email(report, f"{config.FRONTEND_URL}/audit/r/{body.id}")
    if not await notify.email(address, subject, html_body, text_body):
        await db.release_report_email(body.id)
        raise HTTPException(502, "We couldn't send the email just now. Please try again, or copy the link above.")
    return {"sent": True}


@app.post("/api/track", status_code=204)
async def track(request: Request):
    """Click and booking tracking (PRD §10.1 needs clicked_cta / visited_ce_page / call_booked).
    Accepts a text/plain JSON body so the browser can send it with navigator.sendBeacon while leaving the page."""
    try:
        data = json.loads(await request.body())
        audit_id, event = str(data["id"])[:40], data["event"]
        if event not in db.TRACKED_FLAGS:
            raise ValueError(event)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Bad tracking event.")
    if event == "booked":
        row = await db.mark_booked(audit_id)  # only the first booking of a report returns a row
        if row:
            await notify.slack(notify.slack_call_booked(row["report"], row["report_email"],
                                                        f"{config.FRONTEND_URL}/audit/r/{audit_id}",
                                                        guard.feedback_link(audit_id)))
    else:
        await db.set_flag(audit_id, event)  # an unknown id updates nothing, and we don't say so
    return Response(status_code=204)


# --- Funnel (PRD §12.1): steps before a report exists; the audits table covers the rest ---

VISITOR_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


@app.post("/api/funnel", status_code=204)
async def funnel(request: Request):
    """One funnel step from the question page, as text/plain JSON (sendBeacon, no CORS preflight)."""
    try:
        data = json.loads(await request.body())
        visitor, event = str(data["visitor"]), data["event"]
        if not VISITOR_RE.match(visitor) or event not in db.FUNNEL_EVENTS:
            raise ValueError(event)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Bad funnel event.")
    await db.record_funnel(visitor, event)  # a repeat of the same step by the same browser is ignored
    return Response(status_code=204)


# --- Shiv's call feedback (PRD §12.4): one signed link per report, from the Slack messages ---
# Opening the link only shows the question; the answer is saved by pressing a button (a POST), so a link
# preview bot can never record an answer by itself.

FEEDBACK_ANSWERS = {"yes": "Yes, it was the real problem", "partly": "Partly", "no": "No, it was something else"}


def _feedback_page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(status_code=status, content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Audit call feedback</title></head>
<body style="font-family:Arial,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;line-height:1.5;color:#111316">
{body}</body></html>""")


async def _feedback_report(audit_id: str, sig: str):
    if not guard.feedback_ok(audit_id, sig):
        return None, _feedback_page("<h1>Link not valid</h1><p>Use the link from the Slack message.</p>", 403)
    row = await db.get_feedback(audit_id)
    if row is None:
        return None, _feedback_page("<h1>Report not found</h1>", 404)
    return row, None


@app.get("/api/feedback/{audit_id}", response_class=HTMLResponse)
async def feedback_form(audit_id: str, sig: str = ""):
    row, error = await _feedback_report(audit_id, sig)
    if error:
        return error
    report, e = row["report"], html.escape
    top = report["leaks"][0]["name"]
    current = (f"<p>Recorded so far: <strong>{e(FEEDBACK_ANSWERS[row['top_leak_was_correct']])}</strong>. "
               "Pressing another button changes it.</p>") if row["top_leak_was_correct"] else ""
    buttons = "".join(
        f'<form method="post" action="/api/feedback/{e(audit_id)}?sig={e(sig)}&amp;answer={key}" style="margin:0 0 10px">'
        f'<button style="font-size:16px;padding:12px 20px;border-radius:999px;border:1px solid #111316;'
        f'background:#fff;cursor:pointer;min-width:280px">{e(label)}</button></form>'
        for key, label in FEEDBACK_ANSWERS.items())
    gaps = "".join(f"<li>{e(leak['name'])}</li>" for leak in report["leaks"])
    return _feedback_page(f"""<p style="color:#5b6370">Ops Clarity Audit · call feedback</p>
<h1 style="font-size:24px">{e(report['display_name'])}</h1>
<p>The report said their biggest gap was <strong>{e(top)}</strong>. Their three gaps:</p><ol>{gaps}</ol>
<p>After the call: <strong>was the top gap the real problem?</strong></p>{current}{buttons}
<p style="font-size:13px;color:#5b6370">After 20 answers these show which gaps the audit over-picks (PRD §12.4).</p>""")


@app.post("/api/feedback/{audit_id}", response_class=HTMLResponse)
async def feedback_save(audit_id: str, sig: str = "", answer: str = ""):
    row, error = await _feedback_report(audit_id, sig)
    if error:
        return error
    if answer not in FEEDBACK_ANSWERS:
        return _feedback_page("<h1>Pick one of the three answers</h1>", 422)
    await db.set_feedback(audit_id, answer)
    back = f"/api/feedback/{html.escape(audit_id)}?sig={html.escape(sig)}"
    return _feedback_page(f"""<h1>Saved ✓</h1><p>{html.escape(row['report']['display_name'])}: top gap correct =
<strong>{html.escape(FEEDBACK_ANSWERS[answer])}</strong>.</p><p><a href="{back}">Change the answer</a></p>""")
