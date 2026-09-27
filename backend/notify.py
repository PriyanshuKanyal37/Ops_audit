"""Outgoing messages: Slack alerts (Phase 3, 5) and emails through Resend (Phase 4, 5)."""

import html
import logging

import httpx

import config

log = logging.getLogger(__name__)


async def slack(text: str) -> bool:
    """Post to Shiv's Slack channel. Never raises: a failed alert must not break an audit."""
    if not config.SLACK_WEBHOOK_URL:
        log.warning("SLACK_WEBHOOK_URL not set; skipped Slack message: %s", text.splitlines()[0])
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # No link previews: Slack's preview bot would otherwise open the links, feedback link included.
            response = await client.post(config.SLACK_WEBHOOK_URL,
                                         json={"text": text, "unfurl_links": False, "unfurl_media": False})
            response.raise_for_status()
        return True
    except Exception as error:
        log.warning("Slack message failed: %s", error)
        return False


async def email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send one email through Resend. Never raises; returns False if it wasn't sent."""
    if not config.RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set; email to %s not sent", to)
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                config.RESEND_API_URL,
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                json={"from": config.EMAIL_FROM, "to": [to], "subject": subject, "html": html_body,
                      "text": text_body},
            )
            response.raise_for_status()
        return True
    except Exception as error:
        log.warning("Email to %s failed: %s", to, error)
        return False


def report_email(report: dict, link: str) -> tuple[str, str, str]:
    """PRD §7.10 "email this to me": the permalink plus a short summary. (subject, html, text)"""
    name = report["display_name"]
    total = f"${report['total_low']:,}–{report['total_high']:,}"
    gaps = [f"{leak['name']} (${leak['monthly_low']:,}–{leak['monthly_high']:,} a month)" for leak in report["leaks"]]
    subject = f"Your Ops Clarity Audit: {name}"
    footer = ("You're getting this because you asked for your report. We won't email you anything else "
              "unless you sign up for it.")
    text = "\n".join([
        "Here's your Ops Clarity Audit.", "",
        f"{name} is losing an estimated {total} a month.", "",
        "Your three biggest gaps:", *[f"{i}. {gap}" for i, gap in enumerate(gaps, 1)], "",
        f"Read the full report any time: {link}", "", footer,
    ])
    e = html.escape  # names and gaps come from Claude and the founder's website
    html_body = f"""<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#111316;max-width:560px">
<p>Here's your Ops Clarity Audit.</p>
<p style="font-size:20px"><strong>{e(name)} is losing an estimated {e(total)} a month.</strong></p>
<p>Your three biggest gaps:</p>
<ol>{"".join(f"<li>{e(gap)}</li>" for gap in gaps)}</ol>
<p><a href="{e(link)}" style="display:inline-block;background:#111316;color:#ffffff;padding:12px 22px;border-radius:999px;text-decoration:none">Read your full report</a></p>
<p style="font-size:13px;color:#5b6370">{e(footer)}</p>
</div>"""
    return subject, html_body, text


def followup_email(report: dict, report_link: str, book_link: str) -> tuple[str, str, str]:
    """PRD §10.1, the one follow-up: their permalink, their top gap in a sentence, and what we'd fix first.
    Built from the saved report, so it costs no Claude call. (subject, html, text)"""
    top = report["leaks"][0]
    name = report["display_name"]
    gap = f"{top['name']}, costing an estimated ${top['monthly_low']:,}–{top['monthly_high']:,} a month"
    fix = f"{top['fix_name']}: {top['fix_what_it_does'].rstrip('.')}."
    subject = f"{name}: the gap we'd fix first"
    footer = "This is the only follow-up we'll send about your audit."
    text = "\n".join([
        f"Two days ago you ran an Ops Clarity Audit for {name}.", "",
        f"Your biggest gap was {gap}.", "",
        f"What we'd fix first: {fix}", f"Time to stand up: {top['fix_time_to_live']}.", "",
        f"Your full report: {report_link}", f"Book 30 minutes to talk it through: {book_link}", "", footer,
    ])
    e = html.escape
    button = ("display:inline-block;padding:12px 22px;border-radius:999px;text-decoration:none;margin:0 8px 8px 0;"
              "border:1px solid #111316;")
    html_body = f"""<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#111316;max-width:560px">
<p>Two days ago you ran an Ops Clarity Audit for {e(name)}.</p>
<p>Your biggest gap was <strong>{e(gap)}</strong>.</p>
<p><strong>What we'd fix first:</strong> {e(fix)}<br>Time to stand up: {e(top['fix_time_to_live'])}.</p>
<p><a href="{e(report_link)}" style="{button}background:#111316;color:#ffffff">Read your full report</a><a href="{e(book_link)}" style="{button}color:#111316">Book 30 minutes</a></p>
<p style="font-size:13px;color:#5b6370">{e(footer)}</p>
</div>"""
    return subject, html_body, text


def _slack_escape(text: str) -> str:
    """Slack's message format treats &, < and > as control characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lead_lines(report: dict, email: str | None) -> list[str]:
    s = _slack_escape
    band = report["band_label"] + " a month" + (" (assumed: they chose \"rather not say\")" if report["mrr_inferred"] else "")
    top = report["leaks"][0]
    where = f" ({s(report['domain'])})" if report.get("domain") and report["display_name"] != report["domain"] else ""
    if email:
        contact = f"Email: {s(email)} (they asked for their report by email)"
    elif report.get("website_url"):
        contact = f"No email given. Reach them through their website: {s(report['website_url'])}"
    else:
        contact = "No email and no website given."
    return [
        f"*{s(report['display_name'])}*{where}",
        f"Revenue: {s(band)}",
        f"Losing an estimated ${report['total_low']:,}–{report['total_high']:,} a month. "
        f"Top gap: {s(top['name'])} ({top['pillar']})",
        "Gaps: " + " · ".join(s(leak["name"]) for leak in report["leaks"]),
        contact,
    ]


def slack_lead_alert(report: dict, email: str | None, clicked: bool, ce_visit: bool, report_link: str,
                     feedback_link: str) -> str:
    """PRD §10.3: a $100K+ founder ran the audit 24h ago and hasn't booked."""
    yes = lambda flag: "yes" if flag else "no"
    return "\n".join([
        ":mag: *Audit lead: $100K+ founder, no call booked 24h after their report*",
        *_lead_lines(report, email),
        f"Since then: clicked the report's button: {yes(clicked)} · visited the Client Engine page: {yes(ce_visit)}",
        f"<{report_link}|Open their report>  ·  If you get a call: <{feedback_link}|was the top gap right?>",
    ])


def slack_call_booked(report: dict, email: str | None, report_link: str, feedback_link: str) -> str:
    """A founder booked from /audit/book. Calendly has the time and their details; this links the call to the
    report, and gives Shiv the one-click feedback for after the call (PRD §12.4)."""
    return "\n".join([
        ":calendar: *Call booked from the Ops Clarity Audit*",
        *_lead_lines(report, email),
        "Calendly has the time and their contact details.",
        f"<{report_link}|Open their report>  ·  After the call: <{feedback_link}|was the top gap right?>",
    ])
