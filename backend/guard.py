"""Request guards (PRD §9.4): signed session tokens, IP hashing, Turnstile, the per-IP rate limit
and the daily spend cap with Slack alerts.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Request

import config
import db
import notify

log = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 30 * 60
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


# --- Session tokens: carry the founder's URL from the website screen to the audit ---

def _sign(payload: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(data: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({**data, "exp": int(time.time()) + SESSION_TTL_SECONDS}).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session(token: str) -> dict:
    """Raises ValueError if the token was tampered with or has expired."""
    payload, _, signature = token.partition(".")
    if not signature or not hmac.compare_digest(signature, _sign(payload)):
        raise ValueError("invalid session")
    data = json.loads(base64.urlsafe_b64decode(payload))
    if data["exp"] < time.time():
        raise ValueError("session expired")
    return data


# --- Shiv's feedback links (PRD §12.4): signed per audit, no expiry (the call can be weeks after booking) ---

def feedback_signature(audit_id: str) -> str:
    return _sign(f"feedback:{audit_id}")[:32]


def feedback_ok(audit_id: str, signature: str) -> bool:
    return hmac.compare_digest(signature or "", feedback_signature(audit_id))


def feedback_link(audit_id: str) -> str:
    return f"{config.PUBLIC_API_URL}/api/feedback/{audit_id}?sig={feedback_signature(audit_id)}"


# --- Who is asking ---

def client_ip(request: Request) -> str:
    # Railway's proxy appends the real client IP as the LAST X-Forwarded-For entry; earlier entries can be forged.
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    return forwarded[-1] if forwarded else (request.client.host if request.client else "unknown")


def ip_hash(ip: str) -> str:
    return hashlib.sha256(f"{config.IP_HASH_SALT}:{ip}".encode()).hexdigest()


# --- Turnstile: the "are you human?" check on the website screen ---

async def verify_turnstile(token: str | None, ip: str) -> bool:
    if not config.TURNSTILE_SECRET_KEY:
        return True  # not configured (local dev); /health reports "turnstile": false so it can't go unnoticed
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data={
                "secret": config.TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip})
            return bool(response.json().get("success"))
    except Exception as error:  # fail closed: an unverifiable request never reaches the paid APIs
        log.warning("Turnstile verification failed: %s", error)
        return False


# --- Rate limit: 3 audits per hour and 10 per day per IP ---

# ponytail: per-process count of audits still running, so parallel requests can't slip past the DB count.
# Fine for one Railway instance; move to the database if the backend is ever scaled out.
_running: dict[str, int] = {}


@contextmanager
def running(ip_digest: str):
    _running[ip_digest] = _running.get(ip_digest, 0) + 1
    try:
        yield
    finally:
        _running[ip_digest] -= 1


async def rate_limit_message(ip_digest: str) -> str | None:
    """None if this IP may run another audit, otherwise the message to show."""
    last_hour, last_day = await db.count_recent_audits(ip_digest)
    busy = _running.get(ip_digest, 0)
    if last_day + busy >= config.RATE_LIMIT_PER_DAY:
        return f"You've reached the limit of {config.RATE_LIMIT_PER_DAY} audits a day. Please come back tomorrow."
    if last_hour + busy >= config.RATE_LIMIT_PER_HOUR:
        return f"You've reached the limit of {config.RATE_LIMIT_PER_HOUR} audits an hour. Please try again a little later."
    return None


# --- Daily spend cap, with a Slack alert at 80% and at 100% ---

_alerts_sent: set[tuple[str, int]] = set()  # (UTC date, level); ponytail: resets on restart, so at most one repeat


def spend_alert_level(spent: float, cap: float) -> int | None:
    if spent >= cap:
        return 100
    if spent >= 0.8 * cap:
        return 80
    return None


async def check_spend() -> bool:
    """True if today's Claude spend is under the cap. Sends the Slack alert the first time a level is crossed."""
    spent = await db.spend_today()
    level = spend_alert_level(spent, config.DAILY_SPEND_CAP_USD)
    key = (datetime.now(timezone.utc).date().isoformat(), level or 0)
    if level and key not in _alerts_sent:
        _alerts_sent.add(key)
        what = "reached — new audits are paused until midnight UTC" if level == 100 else "passed 80%"
        await notify.slack(f":warning: Ops Clarity Audit: today's Claude spend is ${spent:.2f}, "
                           f"cap ${config.DAILY_SPEND_CAP_USD:.2f} ({what}).")
    return spent < config.DAILY_SPEND_CAP_USD
