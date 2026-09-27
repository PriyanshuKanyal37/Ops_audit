"""Settings, read from environment variables (.env locally, Railway variables in production)."""

import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var {name}. Copy .env.example to .env and fill it in.")
    return value


DATABASE_URL = _required("DATABASE_URL")
SESSION_SECRET = _required("SESSION_SECRET")
IP_HASH_SALT = _required("IP_HASH_SALT")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3100").split(",")
    if origin.strip()
]

# Optional at startup. The audit endpoint reports a clear error if the Anthropic key is missing.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5").strip()
# low: ~20–45s and ~$0.02–0.05 per report. medium measured 60s and $0.07 with similar quality (PLAN §5.1).
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "low").strip()
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()  # without it, no fallback reader
JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()  # optional: Jina works keyless at lower rate limits

# Protection (PRD §9.4). Empty Turnstile/Slack values switch those features off; /health shows which are on.
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
DAILY_SPEND_CAP_USD = float(os.environ.get("DAILY_SPEND_CAP_USD", "20") or 20)
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "3") or 3)
RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "10") or 10)

# Capture (Phase 4). Without RESEND_API_KEY, "email this to me" answers with a friendly error.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails").strip()  # tests point it elsewhere
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Ladder <audit@theladder.ai>").strip()
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3100").strip().rstrip("/")  # builds report links
MAX_REPORT_EMAILS = 3  # "email this to me" sends per report

# Background jobs (Phase 5, PRD §10): the 48-hour follow-up email and the 24-hour Slack alert. OFF unless switched
# on, so a local backend never emails founders or posts test audits to Shiv's Slack. Production: JOBS_ENABLED=true.
JOBS_ENABLED = os.environ.get("JOBS_ENABLED", "").strip().lower() in ("1", "true", "yes")
# This backend's public address: Shiv's one-click feedback links in Slack point here.
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:8100").strip().rstrip("/")
