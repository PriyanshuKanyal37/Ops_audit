"""Neon Postgres access: one asyncpg connection pool. Every SQL query in the app lives in this file."""

import asyncio
import json
import logging
from datetime import datetime

import asyncpg

import config

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _setup_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init(attempts: int = 5) -> None:
    global _pool
    # Retry: a DNS or network blip while starting shouldn't crash the server (seen on this machine in Phase 4).
    for attempt in range(1, attempts + 1):
        try:
            # statement_cache_size=0: Neon's pooled endpoint runs PgBouncer in transaction mode,
            # where asyncpg's named prepared-statement cache can break.
            _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5, statement_cache_size=0,
                                              init=_setup_connection)
            return
        except OSError as error:  # includes DNS failures (socket.gaierror) and refused connections
            if attempt == attempts:
                raise
            log.warning("Database not reachable (%s); retrying in 2s (%d/%d)", error, attempt, attempts)
            await asyncio.sleep(2)


async def close() -> None:
    if _pool:
        await _pool.close()


async def ping() -> bool:
    return await _pool.fetchval("select 1") == 1


# --- Website reads (scrape_cache) ---

async def get_site(key: str):
    """A cached website read younger than 30 days and made with the current cleaning rules, or None."""
    from scrape import CLEANING_VERSION, Site  # local import: scrape imports db

    row = await _pool.fetchrow(
        "select context, has_case_studies, has_testimonials, has_blog, word_count from scrape_cache"
        " where domain = $1 and fetched_at > greatest(now() - interval '30 days', $2::timestamptz)",
        key, datetime.fromisoformat(CLEANING_VERSION))
    return Site(**dict(row)) if row else None


async def save_site(key: str, site) -> None:
    await _pool.execute(
        """insert into scrape_cache (domain, context, has_case_studies, has_testimonials, has_blog, word_count)
           values ($1, $2, $3, $4, $5, $6)
           on conflict (domain) do update set context = excluded.context,
             has_case_studies = excluded.has_case_studies, has_testimonials = excluded.has_testimonials,
             has_blog = excluded.has_blog, word_count = excluded.word_count, fetched_at = now()""",
        key, site.context, site.has_case_studies, site.has_testimonials, site.has_blog, site.word_count)


# --- Audits ---

async def insert_audit(audit_id: str, ip_hash: str, answers: dict, report: dict, cost_usd: float) -> None:
    scores, leaks = report["scores"], report["leaks"]
    await _pool.execute(
        """insert into audits (id, ip_hash, website_url, url_type, q1, q2, q3, mrr_band, mrr_inferred, q5,
             score_credibility, score_pipeline, score_conversion, score_delivery, leak_1_id, leak_2_id, leak_3_id,
             top_leak_pillar, total_leakage_low, total_leakage_high, cta_route, report, specificity_degraded, cost_usd)
           values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
             $22, $23, $24)""",
        audit_id, ip_hash, report["website_url"], report["url_type"], answers["q1"], answers["q2"], answers["q3"],
        report["band"], report["mrr_inferred"], answers["q5"],
        scores["credibility"]["score"], scores["pipeline"]["score"], scores["conversion"]["score"],
        scores["delivery"]["score"], leaks[0]["leak_id"], leaks[1]["leak_id"], leaks[2]["leak_id"],
        report["top_leak_pillar"], report["total_low"], report["total_high"], report["cta_route"], report,
        report["specificity_degraded"], round(cost_usd, 4))


async def get_report(audit_id: str) -> dict | None:
    return await _pool.fetchval("select report from audits where id = $1", audit_id)


# --- Capture (Phase 4) ---

async def claim_report_email(audit_id: str, email: str, max_sends: int) -> dict | None:
    """Record the address and count one send, atomically, unless the report is at its send limit.
    Returns the report, or None if the report doesn't exist or has hit the limit."""
    return await _pool.fetchval(
        """update audits set report_email = $2, report_emails_sent = report_emails_sent + 1
           where id = $1 and report_emails_sent < $3 returning report""", audit_id, email, max_sends)


async def release_report_email(audit_id: str) -> None:
    """Undo a claimed send that didn't go out, so it doesn't count against the limit."""
    await _pool.execute("update audits set report_emails_sent = greatest(report_emails_sent - 1, 0) where id = $1",
                        audit_id)


TRACKED_FLAGS = {"cta_click": "clicked_cta", "ce_visit": "visited_ce_page", "booked": "call_booked"}


async def set_flag(audit_id: str, event: str) -> None:
    column = TRACKED_FLAGS[event]  # whitelisted, so safe to put in the SQL
    await _pool.execute(f"update audits set {column} = true where id = $1", audit_id)


async def report_exists(audit_id: str) -> bool:
    return bool(await _pool.fetchval("select 1 from audits where id = $1", audit_id))


async def mark_booked(audit_id: str):
    """Set call_booked. Returns the row only the first time, so the "call booked" Slack message goes out once."""
    return await _pool.fetchrow("update audits set call_booked = true where id = $1 and not call_booked"
                                " returning id, report, report_email", audit_id)


# --- Background jobs (Phase 5, PRD §10) ---
# A row is claimed by setting its flag BEFORE sending, in one statement, so two job runs can never send twice.
# A failed send releases the claim and the next run (10 minutes later) retries. Audits older than 7 days are
# never picked up: a week-old alert isn't actionable, and it keeps old test audits out.
PAID_BANDS = ["100k_200k", "200k_350k", "350k_500k", "500k_plus"]  # PRD §10.3: "$100K–200K or higher"


async def claim_followups(limit: int = 20) -> list:
    """PRD §10.1: 48h on, they emailed themselves the report but never clicked through or booked."""
    return await _pool.fetch(
        """update audits set followup_email_sent = true where id in (
             select id from audits
             where submitted_at < now() - interval '48 hours' and submitted_at > now() - interval '7 days'
               and report_email is not null and not clicked_cta and not visited_ce_page and not call_booked
               and not followup_email_sent
             order by submitted_at limit $1 for update skip locked)
           returning id, report_email, report""", limit)


async def release_followup(audit_id: str) -> None:
    await _pool.execute("update audits set followup_email_sent = false where id = $1", audit_id)


async def claim_slack_alerts(limit: int = 20) -> list:
    """PRD §10.3: 24h on, $100K+ a month and no call booked. Skips founders we can't reach at all (no website
    and no email): an alert Shiv can't act on is noise."""
    return await _pool.fetch(
        """update audits set slack_alert_sent = true where id in (
             select id from audits
             where submitted_at < now() - interval '24 hours' and submitted_at > now() - interval '7 days'
               and mrr_band = any($2::text[]) and not call_booked and not slack_alert_sent
               and (url_type <> 'none' or report_email is not null)
             order by submitted_at limit $1 for update skip locked)
           returning id, report, report_email, clicked_cta, visited_ce_page""", limit, PAID_BANDS)


async def release_slack_alert(audit_id: str) -> None:
    await _pool.execute("update audits set slack_alert_sent = false where id = $1", audit_id)


# --- Shiv's call feedback (PRD §12.4) ---

async def get_feedback(audit_id: str):
    return await _pool.fetchrow("select report, top_leak_was_correct from audits where id = $1", audit_id)


async def set_feedback(audit_id: str, answer: str) -> bool:
    return await _pool.fetchval("update audits set top_leak_was_correct = $2 where id = $1 returning true",
                                audit_id, answer) or False


# --- Funnel (PRD §12.1) ---

FUNNEL_EVENTS = ("landing_view", "q1_answered", "url_given", "q2_answered", "q3_answered", "q4_reached",
                 "q4_answered", "q5_answered", "submitted")


async def record_funnel(visitor_id: str, event: str) -> None:
    await _pool.execute("insert into funnel_events (visitor_id, event) values ($1, $2) on conflict do nothing",
                        visitor_id, event)


async def funnel_counts(days: int) -> dict:
    """Visitors per funnel step, plus what happened after the report, over the last `days` days."""
    steps = await _pool.fetch("select event, count(*) as n from funnel_events"
                              " where created_at > now() - make_interval(days => $1) group by event", days)
    after = await _pool.fetchrow(
        """select count(*) as audits, count(*) filter (where clicked_cta) as clicked,
                  count(*) filter (where visited_ce_page) as ce_visits, count(*) filter (where call_booked) as booked,
                  count(*) filter (where specificity_degraded) as degraded,
                  count(*) filter (where top_leak_pillar = 'delivery') as delivery_top,
                  count(*) filter (where top_leak_was_correct is not null) as feedback,
                  count(*) filter (where top_leak_was_correct = 'yes') as feedback_yes
           from audits where submitted_at > now() - make_interval(days => $1)""", days)
    return {**{event: 0 for event in FUNNEL_EVENTS}, **{row["event"]: row["n"] for row in steps}, **dict(after)}


# --- Protection (guard.py) ---

async def count_recent_audits(ip_hash: str) -> tuple[int, int]:
    """Audits from this IP in the last hour and the last 24 hours."""
    row = await _pool.fetchrow(
        """select count(*) filter (where submitted_at > now() - interval '1 hour') as last_hour,
                  count(*) as last_day
           from audits where ip_hash = $1 and submitted_at > now() - interval '24 hours'""", ip_hash)
    return row["last_hour"], row["last_day"]


async def spend_today() -> float:
    """Claude spend on saved audits since midnight UTC."""
    total = await _pool.fetchval(
        "select coalesce(sum(cost_usd), 0) from audits"
        " where submitted_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'")
    return float(total)
