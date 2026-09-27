# Ops Clarity Audit v2

A free diagnostic for founder-led B2B service firms: five questions plus their website, and a report naming the three
biggest monthly revenue leaks, sized in dollars, with the fix for each. Built from Ladder's PRD; the full plan,
decisions and test logs are in [PLAN.md](PLAN.md).

| Part | Stack | Folder |
|---|---|---|
| API | Python 3.11, FastAPI, Neon Postgres (asyncpg), Claude (Anthropic SDK), Jina/Firecrawl, Resend | [`backend/`](backend/) |
| Web | Next.js 16, React 19, Tailwind 4 | [`frontend/`](frontend/) |

## Run locally

```bash
# API on :8100
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env        # fill it in; every variable is explained there
psql "$DATABASE_URL" -f schema.sql   # once; safe to re-run
.venv/Scripts/uvicorn main:app --port 8100

# Web on :3100
cd frontend
cp .env.example .env.local
npm ci && npm run dev
```

## Environment variables

- API: [`backend/.env.example`](backend/.env.example). Required: `DATABASE_URL`, `SESSION_SECRET`, `IP_HASH_SALT`.
- Web: [`frontend/.env.example`](frontend/.env.example). `NEXT_PUBLIC_*` values are baked in at build time, so
  rebuild after changing them.
- Production also needs `JOBS_ENABLED=true` (follow-up email + Slack alert loop), `PUBLIC_API_URL`, `FRONTEND_URL`
  and `ALLOWED_ORIGINS` pointing at the deployed URLs, and real Cloudflare Turnstile keys whose widget lists the
  web domain.

## Tests

From `backend/`: `python test_rules.py`, `python test_scrape.py` (offline), and `protection_check.py`,
`capture_check.py`, `phase5_check.py` (real database, fake Slack/Resend, port 8100 free). None of them call Claude.
`python funnel_report.py` prints the PRD §12 funnel against its targets.
