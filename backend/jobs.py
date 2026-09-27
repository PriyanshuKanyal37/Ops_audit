"""Background jobs (PRD §10), in Python instead of n8n: the 48-hour follow-up email (§10.1) and the 24-hour
Slack alert to Shiv (§10.3). A loop inside the backend runs both every 10 minutes when JOBS_ENABLED is on.

ponytail: one loop per backend process. The database claims stop double sends even with two instances, but move
this to a Railway cron job if the backend is ever scaled out.
"""

import asyncio
import logging

import config
import db
import guard
import notify

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 600


def _links(audit_id: str) -> tuple[str, str]:
    return f"{config.FRONTEND_URL}/audit/r/{audit_id}", f"{config.FRONTEND_URL}/audit/book?audit={audit_id}"


async def send_followups() -> int:
    if not config.RESEND_API_KEY:
        return 0  # nothing can be sent, so claim nothing: the rows wait until email is configured
    sent = 0
    for row in await db.claim_followups():
        report_link, book_link = _links(row["id"])
        subject, html_body, text_body = notify.followup_email(row["report"], report_link, book_link)
        if await notify.email(row["report_email"], subject, html_body, text_body):
            sent += 1
        else:
            await db.release_followup(row["id"])  # retried on the next run, for up to 7 days
    return sent


async def send_slack_alerts() -> int:
    if not config.SLACK_WEBHOOK_URL:
        return 0
    sent = 0
    for row in await db.claim_slack_alerts():
        report_link, _ = _links(row["id"])
        text = notify.slack_lead_alert(row["report"], row["report_email"], row["clicked_cta"], row["visited_ce_page"],
                                       report_link, guard.feedback_link(row["id"]))
        if await notify.slack(text):
            sent += 1
        else:
            await db.release_slack_alert(row["id"])
    return sent


async def run_once() -> dict:
    return {"followups": await send_followups(), "slack_alerts": await send_slack_alerts()}


async def run_forever() -> None:
    while True:
        try:
            result = await run_once()
            if any(result.values()):
                log.info("Background jobs sent: %s", result)
        except Exception:  # a bad run must never kill the loop
            log.exception("Background jobs failed")
        await asyncio.sleep(INTERVAL_SECONDS)
