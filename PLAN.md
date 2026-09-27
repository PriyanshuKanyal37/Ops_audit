# 🛠️ Ops Clarity Audit v2: Build Plan

> The end-to-end plan for rebuilding the audit from the new PRD ([ladder_ops_audit_prd.md](../ladder_ops_audit_prd.md), explained in [PRD_EXPLAINED.md](../PRD_EXPLAINED.md)).
> Everything new lives in **`audit-app/`**. The old [`backend/`](../backend/) folder is **not touched**. It's only kept for reference.
> **How we work:** one phase at a time → build → test thoroughly → report → mark it ✅ here. Details of each finished phase are in the [🧾 Phase log](#-phase-log) at the bottom.
> 💰 **Anthropic budget for the whole build: under $1.00. Spent so far: $0.78** (itemised in the Phase 1, 2, 4 and live-QA logs).
> 🚀 **Deployed on Render (27 Sept, at the user's request)** from [github.com/PriyanshuKanyal37/Ops_audit](https://github.com/PriyanshuKanyal37/Ops_audit) (public repo, `main`, auto-deploy on push). Web: https://ops-audit-web.onrender.com · API: https://ops-audit-api.onrender.com (Singapore, next to the Neon database; free plan). Details are in the phase log.

## 📍 Progress

| Phase | Status | Finished |
|---|---|---|
| 0 · Setup | ✅ Done | 25 Sept 2026 |
| 1 · Engine (website reading + Claude + rules) | ✅ Done. Gate 2 reports are ready for **Shiv to read** in `backend/fixtures/out/` | 25 Sept 2026 |
| 2 · Founder flow (frontend) | ✅ Done | 25 Sept 2026 |
| 3 · Protection (Turnstile, rate limit, spend cap) | ✅ Done, tested with Cloudflare's test keys. **Remaining: the real Turnstile keys and Slack webhook** (§12) | 25 Sept 2026 |
| 4 · Capture (email, tracking, booking page) + crawl QA + single-page form | ✅ Done locally. **Deploy skipped on purpose.** **Remaining: Resend key + DNS, Calendly link** (§12) | 26 Sept 2026 |
| 4b · Code scoring + reading linked pages (after live QA) | ✅ Done. **Differs from the PRD: needs Shiv's OK** (§11 gaps 14–19) | 26 Sept 2026 |
| 5 · Jobs, feedback loop, funnel tracking (Framer bar still to do) | ✅ Built and tested (37 checks). **Remaining: the Client Engine bar (needs Framer + the live Client Engine page)** | 26 Sept 2026 |

---

## 0. Decisions already made

| Topic | Decision | Different from the PRD? |
|---|---|---|
| Backend | **Python + FastAPI**, new folder `audit-app/backend`, deployed on **Railway** | Yes. The PRD says Next.js API routes |
| Frontend | **Next.js + Tailwind**, `audit-app/frontend`, deployed on **Vercel** | Same stack, but a **separate app**, because theladder.ai is a Framer site |
| Database | **New Neon Postgres project** | Yes. The PRD says Airtable |
| Automations | **Done in Python** (a background job inside the backend) | Yes. The PRD says n8n |
| Email sending | **Resend** | Not specified in the PRD |
| Newsletter | **Not built now.** Waiting on the newsletter setup | The PRD includes it (§7.11, §10.2) |
| Who builds | **You build both backend and frontend** | The PRD says Rishabh |
| Deadline approach | **Full plan, core first** | — |

> 📣 **Tell Shivam about every "Yes" in the last column**, especially Neon instead of Airtable and Python instead of n8n.

---

## 1. How it all fits together

```
                    ┌──────────────────────────────────────────┐
  Founder's  ─────► │  FRONTEND  (Next.js on Vercel)           │
  browser           │  /audit          questions + URL         │
                    │  /audit/r/[id]   the report              │
                    │  /audit/book     Calendly + report       │
                    └───────────────┬──────────────────────────┘
                                    │ HTTPS (JSON)
                    ┌───────────────▼──────────────────────────┐
                    │  BACKEND  (FastAPI on Railway)           │
                    │  POST /api/scrape        start site read │
                    │  POST /api/audit         Claude → save   │
                    │  GET  /api/report/{id}   report JSON     │
                    │  POST /api/email-report  Resend          │
                    │  POST /api/track         clicks/bookings │
                    │  GET  /api/feedback/{id} Shiv's verdict  │
                    │  ⏱️ job loop every 10 min:              │
                    │     48h follow-up email, 24h Slack alert │
                    └──┬────────┬─────────┬────────┬─────────┬─┘
                       │        │         │        │         │
                    Neon DB  Jina /    Claude   Resend    Slack
                             Firecrawl  API     (email)  (alerts)

  Framer site (theladder.ai/client-engine) ── small code component ──► GET /api/report/{id}/summary
```

---

## 2. Folder structure

The backend is deliberately **flat and small**: plain functions, no LangGraph, no ORM.

```
audit-app/
├── PLAN.md
├── backend/                      Python 3.11 · FastAPI · Railway
│   ├── main.py                   app, all routes, CORS, starts the job loop
│   ├── config.py                 reads env vars
│   ├── schema.sql                the 2 tables (run once)
│   ├── db.py                     asyncpg pool + every SQL query
│   ├── library.py                ⭐ single source of truth: 12 leaks, pillars, weights,
│   │                                band table, non-dollar lines, case studies, copy
│   ├── rules.py                  dollar clamping, ranking, cross-pillar check,
│   │                                totals, CTA route, bridge sentence
│   ├── prompt.py                 builds the system prompt + user message from library.py
│   ├── generate.py               Claude call + validation + one retry
│   ├── scrape.py                 Jina → Firecrawl, trimming, yes/no flags, 30-day cache
│   ├── guard.py                  Turnstile check, session token, rate limit, spend cap
│   ├── notify.py                 Resend emails + Slack messages
│   ├── jobs.py                   10-minute loop: follow-up emails, Slack alerts
│   ├── test_rules.py             checks for rules.py + library data (money/routing logic)
│   ├── test_scrape.py            checks for URL normalising, page trimming, session tokens
│   ├── fixtures/inputs.json      15 fake founders (Week 2 gate)
│   ├── run_fixtures.py           runs the 15 → fixtures/out/*.md for Shiv to read
│   ├── scrape_check.py           runs 30 real sites through scrape.py (Week 1 gate)
│   ├── protection_check.py       every PRD §9.4 protection path against the real backend (no Claude spend)
│   ├── capture_check.py          email-this-report + tracking against the real backend, fake Resend (no spend)
│   ├── requirements.txt          fastapi, uvicorn, anthropic, asyncpg, httpx, python-dotenv
│   └── .env.example
├── e2e_check.py                  browser test of the whole founder flow (Edge + Playwright, dev only)
└── frontend/                     Next.js 16 (App Router) · TypeScript · Tailwind 4 · Vercel
    ├── app/page.tsx                     "/" redirects to /audit
    ├── app/audit/page.tsx               landing intro + question flow
    ├── app/audit/r/[id]/page.tsx        report page (noindex) + not-found.tsx
    ├── app/audit/book/page.tsx          Calendly + report summary
    ├── components/CalendlyEmbed.tsx     Calendly widget + "booked" listener (only trusts calendly.com)
    ├── components/EmailReportForm.tsx   "Email me this report"
    ├── components/TrackedLink.tsx       CTA links that record the click (sendBeacon)
    ├── app/globals.css                  design tokens: change colors here to rebrand
    ├── components/AuditFlow.tsx         the 6 question screens + generating screen
    ├── components/Report.tsx            every report section, in PRD §7 order
    ├── components/CopyLinkButton.tsx    permalink box + copy button
    ├── components/Turnstile.tsx         Cloudflare human check on the website screen
    ├── lib/content.json                 questions + CTA copy, GENERATED from backend/library.py
    ├── lib/api.ts                       calls to the backend + the report's type
    ├── framer/ClientEngineBar.tsx       code component to paste into Framer (Phase 5)
    └── .env.example
```

> 🔌 **Local ports: backend 8100, frontend 3100.** LadderFlow already uses 8000/3000 on this machine. `npm run dev` / `npm run start` use 3100 automatically.

Only 6 backend packages. Jina, Firecrawl, Resend, Slack and Turnstile are all plain HTTP calls through `httpx`, so they need no extra SDKs.

> ⚠️ **Next.js 16 note:** the frontend's `AGENTS.md` warns that Next 16 has breaking changes. Before writing frontend code (Phase 2), read the matching guide in `frontend/node_modules/next/dist/docs/`, not memory or old tutorials.

---

## 3. The database (Neon Postgres)

Neon project **`ops-audit`** (ID `green-frost-09121452`), database `neondb`, region **Singapore** (`aws-ap-southeast-1`), Postgres 18. The exact table definitions live in [`backend/schema.sql`](backend/schema.sql).
> 🌏 Because the database is in Singapore, deploy the Railway backend in **Singapore** too, so every query doesn't cross the Pacific.

### Table `audits`: one row per completed audit
| Column | Type | From / purpose |
|---|---|---|
| `id` | text PK | **Random, unguessable** (`secrets.token_urlsafe(9)`, e.g. `k3Jd9xQ2mP1a`). Used in `/audit/r/{id}` |
| `submitted_at` | timestamptz | When the report was generated |
| `ip_hash` | text | SHA-256 of IP + salt. Used for rate limiting (the raw IP is never stored) |
| `website_url`, `url_type` | text | URL screen: `full` / `social` / `none` |
| `q1` | text | A–E |
| `q2`, `q3` | text[] | Multi-select answers |
| `mrr_band`, `mrr_inferred` | text, bool | Q4 |
| `q5` | text | Q5 option |
| `score_credibility` … `score_delivery` | int | From the report |
| `leak_1_id`, `leak_2_id`, `leak_3_id` | text | e.g. `L4` |
| `top_leak_pillar`, `cta_route` | text | Computed in code |
| `total_leakage_low`, `total_leakage_high` | int | Computed in code |
| `report` | jsonb | **The full report.** Powers the report page |
| `specificity_degraded` | bool | The website read failed |
| `cost_usd` | numeric | Claude cost of this audit. Used for the daily spend cap |
| `report_email` | text | From "email this to me". **Not** newsletter consent |
| `report_emails_sent` | smallint | Counts "email this to me" sends (max 3 per report) |
| `newsletter_opted_in` | bool | Column kept for later; no UI yet |
| `clicked_cta`, `visited_ce_page`, `call_booked` | bool | Set by `/api/track` |
| `followup_email_sent`, `slack_alert_sent` | bool | Stop the jobs sending twice |
| `top_leak_was_correct` | text | `yes` / `no` / `partly`, set by Shiv |

### Table `scrape_cache`: one row per website domain
| Column | Purpose |
|---|---|
| `domain` (PK) | e.g. `acme.com` |
| `context` | The trimmed ~300-word text sent to Claude |
| `has_case_studies`, `has_testimonials`, `has_blog` | Yes/no flags |
| `word_count` | Used to decide Jina vs Firecrawl vs unavailable |
| `fetched_at` | Entries older than 30 days get read again |

> 🔍 **How Shiv updates "was the top leak correct?":** when a call is booked, Shiv gets a Slack message with the report link and three one-click links (✅ yes · 🟡 partly · ❌ no). Each link is signed so nobody else can use it. Shiv can also edit the row directly in Neon's table editor.

---

## 4. The main flow, step by step

```
Q1 ─► URL screen ─► Q2 ─► Q3 ─► Q4 ─► Q5 ─► Generating ─► /audit/r/{id}
          │                                     │
          │ POST /api/scrape                    │ POST /api/audit
          ▼                                     ▼
   verify Turnstile                      check session + rate limit + spend cap
   normalise URL, url_type               get website text (wait ≤ 4s if still reading)
   start site read in background         Claude → validate → compute → save
   return signed session token           return { id }
```

### 4.1 `POST /api/scrape` (URL screen)
**Input:** `{ url | null, no_website: bool, turnstile_token }`
1. **Verify Turnstile** with Cloudflare. Reject the request if it fails.
2. **Normalise the URL:** add `https://` if it's missing, lower-case the domain, strip `www.`
3. **Set `url_type`:**
   - `none` if they clicked "I don't have one yet"
   - `social` if the domain is linkedin.com, x.com, twitter.com, instagram.com or facebook.com
   - otherwise `full`
4. **Start reading the site in the background** (skipped for `none`, or when the domain was cached in the last 30 days).
5. **Return a signed session token** (valid 30 minutes) containing `url`, `url_type` and `domain`.

> 💡 **Why a session token:** a Turnstile token can only be checked **once** and expires in 5 minutes, but the founder takes about 3 minutes to finish the questions. So the backend checks Turnstile once here and gives back its own signed token, which `/api/audit` then requires. Anyone without a real session can't trigger a Claude call.

### 4.2 Reading the website (`scrape.py`)
1. **Jina:** `GET https://r.jina.ai/<url>` with `Accept: application/json` to get the title, description and content. *(Check the exact response fields in Week 1.)*
2. If Jina returns **under 200 words**, try **Firecrawl**: `POST /v1/scrape` with `formats: ["markdown"]` and **`onlyMainContent: false`**. **Social URLs skip Firecrawl**, because profile pages usually hide behind a login.
   - ⚠️ *This differs from PRD §9.2, which says `true`.* Testing showed "main content only" strips the navigation, which is where the *Case Studies* and *Blog* links live (the yes/no flags need them), and on some sites it leaves under 100 words (edgarallan.com: 70 words vs 370).
   - If Jina hits its rate limit (429), it **waits 3 seconds and retries once** before falling back. Without a key, Jina allows about 20 reads a minute across all founders, so a free Jina key is worth getting before launch.
3. **Yes/no flags** come from keyword checks on the **full** text before trimming:
   - case studies: "case study", "case studies", "results", "our work"
   - testimonials: "testimonial", "what our clients say", quote patterns
   - blog: "blog", "insights", "articles"
   - *(These are simple keyword guesses. Tune them against the 30-site check.)*
4. **Trim to about 300 words:** title, meta description, H1, the first two content sections, plus the three flags.
5. **Save to `scrape_cache`.** If the result is still under 200 words, the site counts as **unavailable**.

### 4.3 `POST /api/audit` (after Q5)
**Input:** `{ session, answers: { q1, q2[], q3[], mrr_band, q5 } }`
1. **Check the session token** and **validate the answers** (every value must be one of the fixed options; Q2 and Q3 need at least one each).
2. **Rate limit:** at most **3 audits per IP per hour and 10 per day** (counted from `audits.ip_hash`).
3. **Spend cap:** if today's `sum(cost_usd)` ≥ `DAILY_SPEND_CAP_USD`, return a friendly "try again tomorrow" message. Post to Slack **once a day** when spend passes 80%.
4. **Website text:** if the read is still running, **wait up to 4 seconds**, then use the cache, or `"UNAVAILABLE"`.
5. **"I'd rather not say"** → `mrr_band = "$100K–200K"`, `mrr_inferred = true`.
6. **Call Claude** (§5), **validate and fix up** (§6), **compute the remaining fields** (§6).
7. **Save** the row and **return `{ id }`**. The frontend then opens `/audit/r/{id}`.

### 4.4 Other endpoints
| Endpoint | What it does |
|---|---|
| `GET /api/report/{id}` | Returns the `report` JSON. Returns 404 if not found |
| `GET /api/report/{id}/summary` | Just the total, the 3 leak names and the route, for the Client Engine bar on Framer |
| `POST /api/email-report` | `{id, email}` → check the email format → send the report link through Resend → save `report_email`. Max 3 sends per report |
| `POST /api/track` | `{id, event}`, where event is `cta_click`, `ce_visit` or `booked`. Sets the matching flag. On `booked` it also sends Shiv a **"📅 Call booked"** Slack message with the report link and the feedback links |
| `GET /api/feedback/{id}?v=yes\|partly\|no&sig=…` | Shiv's one-click verdict. Checks the signature, saves the value, and shows a "Saved ✅" page |
| `GET /health` | Health check for Railway |

---

## 5. The Claude call (`prompt.py` + `generate.py`)

### 5.1 Settings
| Setting | Value | Note |
|---|---|---|
| SDK | `anthropic` (official Python SDK) | |
| Model | `claude-sonnet-5` | As the PRD says |
| Output | **Structured outputs**: `client.messages.parse()` with a Pydantic model (or `output_config.format` on `messages.create`) | Check the exact SDK signature when coding |
| Thinking | Leave it at the default (adaptive) | |
| Effort | **`low`** (the tested choice) | `medium` measured **60s and $0.07** per report; `low` measured **19–45s and $0.02–0.05** with no visible drop in quality |
| `temperature` | **Don't send it.** Sonnet 5 rejects sampling settings with a 400 error | The old backend used 0.3. Don't copy that |
| `max_tokens` | ~8,000 | Enough for the report plus thinking |
| Prompt caching | `cache_control` on the system prompt | ✅ **Verified:** back-to-back audits read **6,287 cached tokens** each. The cache lasts ~5 minutes, and the "website unreadable" prompt caches separately |
| Stop reasons | If `refusal` or `max_tokens` → **retry once**, then return an error | |

### 5.2 System prompt (built from `library.py`)
Contains everything §8.1 of the PRD requires:
1. **Role:** a senior operator diagnosing a founder-led B2B service business. Direct, specific, never salesy.
2. **The 12-leak library**, word for word. Library changes (§11) are made in `library.py` so the prompt and the code never drift apart.
3. **The band table** and the **money rules** (ranges only, round to $100, stay inside the cell, stronger evidence goes higher in the cell, no confidence percentages).
4. **Selection steps:** score all 12 → top two by dollars → cross-pillar rule for slot 3 → output in dollar order.
5. **Specificity:** mention at least **2 details from the website** and use their own words.
6. **Scoring:** 1–10; a pillar with a selected leak scores ≤ 5; a pillar with no evidence of failure scores 7–9; never score all four low.
7. **Tone:** no hedging, no "it seems", no "consider", no "!", "revenue leak" at most once, and **never mention Ladder, pricing or the Client Engine**.
8. **Prohibitions:** no figures outside the cells, no single numbers, no invented client names, no confidence percentages.
9. **Degraded block** (only when the website is `UNAVAILABLE`): drop the website-details rule, get specificity from Q1, Q5 and the band instead, and keep descriptions to 50–70 words.

### 5.3 User message
Exactly the PRD §8.2 template: URL, URL type, website text (or `UNAVAILABLE`), then Q1–Q5 as full text, with `(inferred: true/false)` after the band.

### 5.4 What Claude returns (smaller than the PRD's schema)
Claude writes **only the text and judgement calls**. Anything that's a lookup or a sum is done in code (§6), so Claude has fewer ways to get it wrong.

```json
{
  "company_name": "string",
  "business_descriptor": "string",
  "the_read": "string",
  "scores": {
    "credibility": {"score": 0, "rationale": "string"},
    "pipeline":    {"score": 0, "rationale": "string"},
    "conversion":  {"score": 0, "rationale": "string"},
    "delivery":    {"score": 0, "rationale": "string"}
  },
  "leaks": [
    {
      "leak_id": "L1|L2|…|L12",
      "description": "string",
      "monthly_low": 0,
      "monthly_high": 0,
      "non_dollar_cost": "string",
      "fix_what_it_does": "string",
      "fix_what_changes": "string",
      "fix_time_to_live": "string"
    }
  ],
  "proof_tie_in": "string",
  "cant_see_item": "string"
}
```

| PRD field | Where it comes from now |
|---|---|
| `leaks[].name`, `pillar`, `fix_name` | `library.py`, looked up by `leak_id` |
| `leaks[].rank` | Order after sorting in code |
| `total_leakage_low/high` | Sum in code |
| `top_leak_pillar` | Pillar of leak #1 |
| `proof_case_study` | Looked up from `top_leak_pillar` |
| `cta_route` | Code (as the PRD already says) |
| `cta_bridge_sentence` | **Template in code.** This removes the PRD's contradiction, where Claude is told never to mention the Client Engine but is also asked to write this sentence |

---

## 6. Validation and computed fields (`rules.py`)

The API guarantees the JSON **shape**, but **not the values**, so code checks them after every call:

| # | Check | If it fails |
|---|---|---|
| 1 | Exactly 3 leaks, valid and different `leak_id`s | Retry once, then return an error |
| 2 | Each leak's range sits **inside its cell** (band × weight) | **Clamp** to the cell edges, round to $100, and keep `low < high` |
| 3 | Sort leaks by **range midpoint** (the PRD doesn't define this, so midpoint is my choice) | — |
| 4 | Cross-pillar rule: if leaks #1 and #2 share a pillar, #3 must be from a different one | Retry once. If it still fails, keep the report and log it |
| 5 | Scores are 1–10; a pillar with a selected leak is ≤ 5 | Clamp |

Then compute:
- **Totals** = sum of the lows and sum of the highs.
- **Top pillar** = the pillar of leak #1.
- **CTA route** = `booking` if the top pillar is Delivery, otherwise `client_engine`.
- **Case study** = Credibility → Athereal · Pipeline → Hot Inbox · Conversion → Storata · Delivery → Archaius.
- **Bridge sentence** (only on the Client Engine route), based on how many of the 3 leaks Client Engine can fix:
  - 3 → *"All three of your gaps — A, B and C — are exactly what the Client Engine is built to fix."*
  - 2 → *"Two of your three gaps — A and B — are exactly what the Client Engine is built to fix."*
  - 1 → *"Your biggest gap — A — is exactly what the Client Engine is built to fix."*
  - The Delivery route uses the PRD's fixed wording.
- **Cost** = input and output tokens × Sonnet 5 prices, saved to `cost_usd`.

`test_rules.py` covers all of this with plain `assert`s: clamping, sorting, cross-pillar, totals, routing, case study and bridge wording.

---

## 7. Background jobs (`jobs.py`) instead of n8n

A loop starts with the backend and runs **every 10 minutes**:

| Job | Picks rows where… | Does | Then sets |
|---|---|---|---|
| 📧 **Follow-up email** (PRD §10.1) | `submitted_at` older than 48h, `report_email` is set, **not** `clicked_cta`, **not** `visited_ce_page`, **not** `followup_email_sent` | Sends **one** email: their report link, the top leak in one sentence, and what Ladder would fix first | `followup_email_sent` |
| 🔔 **Slack alert** (PRD §10.3) | `submitted_at` older than 24h, band **$100K–200K or higher**, **not** `call_booked`, **not** `slack_alert_sent` | Posts the domain, band (marked "inferred" if they didn't say), 3 leak names, total and report link | `slack_alert_sent` |

> ✅ **Built 26 Sept (`jobs.py`).** Changes from the table above:
> - Both jobs skip audits **older than 7 days**.
> - The Slack alert **skips founders we can't reach**: no website and no email.
> - The loop only runs with **`JOBS_ENABLED=true`**, so a local backend never emails anyone or posts test audits.
> - A row is claimed before sending, so nothing is sent twice; a failed send is retried on the next run.
> - The follow-up's second button books a call.
> - A "call booked" Slack message goes out the moment someone books on `/audit/book`, with Shiv's one-click feedback link.

> ⚠️ **Limitation:** the loop runs inside the single Railway server. If you ever run 2+ server instances, move it to a Railway cron job so it doesn't run twice.

> 💡 **Why these can ship a day after launch:** the follow-up only fires after 48 hours and the Slack alert after 24 hours. As long as `report_email` and the tracking flags are saved **from day one**, nothing is lost if the jobs arrive a day or two later.

---

## 8. Frontend

### 8.1 `/audit`: landing page + questions (`AuditFlow.tsx`)
> 🔁 **Changed 26 Sept at the user's request: this is a MOCK frontend, with every question on ONE scrolling page** (not the PRD's one-question-per-screen flow). The real frontend comes later.
- One form, in PRD order: **Q1 → website → Q2 → Q3 → Q4 → Q5 → "See my report"**. Each question is labelled "Question n of 5"; the website block is unnumbered.
- **The website read still starts early**, as the PRD intends: when the founder leaves the website field, `/api/scrape` runs (with the Turnstile token) and reads the site in the background while they answer the rest. On submit, that session is reused, so there's no second read. If the website changed or was never read, it's read on submit.
- **"I don't have a website yet"** checkbox disables the field.
- **Validation on submit:** every unanswered question shows its own message, and focus jumps to the first one. Answering clears that question's message. A junk website shows the server's message as soon as they leave the field.
- **Q4** shows the sub-line *"We use this to size the dollar impact of each leak."*
- All question and option text lives in **`backend/library.py`** (exact PRD wording) and is exported to `frontend/lib/content.json` with `python library.py`. `test_rules.py` fails if the two ever drift apart.

### 8.2 Generating screen
- Shows the 5 status lines one after another (about 1.5 seconds each), using **their** domain and **their** band:
  `Reading acme.com…` → `Checking positioning, proof, and case studies…` → `Matching against 12 revenue leak patterns…` → `Sizing impact against $200K–350K MRR…` → `Ranking by monthly cost…`
- If Claude is still working after the last line, that line **stays on screen with a subtle animation** until the report is ready.
- ⚠️ **Measured in Phase 1: a report takes 19–45 seconds, not the PRD's 6–8.** The generating screen must hold attention for up to ~45s, e.g. by adding more status lines or a progress indicator. Tell Shiv, because this changes the feel of the PRD's generating screen.
- On success → go to `/audit/r/{id}`. On error → a friendly retry button that keeps their answers.

### 8.3 `/audit/r/[id]`: report page
Loads the report on the server (`GET /api/report/{id}`) and renders one component per section:

| # | Component | Notes |
|---|---|---|
| 7.1 | `VerdictBanner` | The total is the **largest text on the page** |
| 7.2 | `TheRead` | |
| 7.3 | `Scorecard` | 4 bars, each out of 10, with a reason |
| 7.4 | `LeakCards` | **Card #1 visibly heavier** |
| 7.5 | `BuildCards` | What it does / what changes / time to go live |
| 7.6 | `ProofCard` | Case study numbers from `library.py`. **Archaius has no outbound link** |
| 7.7 | `HowCalculated` | A `<details>` element, **collapsed by default** |
| 7.8 | `CantSee` | 2 fixed items + 1 written by Claude |
| 7.9 | `PrimaryCta` | Bridge sentence + button. The click is tracked (`cta_click`) before leaving the page |
| 7.10 | `SaveReport` | Copy-link button + "email this to me" form |
| 7.11 | *(Newsletter)* | **Waiting for the newsletter decision** |
| 7.12 | `Footer` | Date, *"based on your five answers and a read of {domain}"*, report ID |

The report page gets `noindex` so reports never show up in Google.

### 8.4 `/audit/book?audit={id}`
- **Calendly inline embed** on one side and a **summary of their report** (total + 3 leaks) on the other.
- When Calendly reports a booking (its `calendly.event_scheduled` browser event), call `/api/track` with `booked`.
- The audit ID goes into Calendly's `utm_content`, so the booking can be matched later if you add Calendly webhooks (those need a paid Calendly plan).

### 8.5 The Client Engine bar (on the Framer site)
- `framer/ClientEngineBar.tsx`: a small **Framer code component** to add to the Client Engine page.
- It reads `?audit=` from the URL, calls `GET /api/report/{id}/summary`, and shows a slim bar: **total · 3 leak names · "from your Ops Clarity Audit"**. It also sends `ce_visit`.
- **Needs someone with Framer edit access** to add it.

---

## 9. Build order (core first)

> 📅 Today is **25 Sept**, and launch is **30 Sept**. The PRD's 4 weeks are squeezed into the phases below. **Phases 0–4 are the launch set.** Phase 5 follows straight after launch.

| Phase | What | Done when… |
|---|---|---|
| ✅ **0 · Setup** *(Day 1)* | Create the `audit-app/backend` and `audit-app/frontend` projects · new Neon project + `schema.sql` · `.env.example` files | ✅ Both apps start locally and the backend connects to Neon |
| **1 · Engine** *(Days 1–2)* | `library.py` (all of PRD §5 and §6 plus the case studies) · `rules.py` + `test_rules.py` · `scrape.py` + cache · `prompt.py` + `generate.py` · `/api/scrape`, `/api/audit`, `/api/report` | ✅ **Gate 1 PASSED:** `scrape_check.py` on **30 real B2B sites (5+ on Framer or Webflow)** gets **95%+ with 200+ words** → **39/39 reachable (100%), 13 Framer/Webflow** · 🟡 **Gate 2:** 8 live reports generated (7 fixtures + 2 via the real API, #14 twice) and all automatic checks pass except 4 short descriptions. **Waiting for Shiv to read them** in `fixtures/out/`. The other 7 fixtures (3–8, 10) were skipped to stay in budget (~$0.28 to run) |
| ✅ **2 · Founder flow** *(Day 3)* | `AuditFlow` (all 6 screens + generating) · report page with all sections except the newsletter · CTA routing | ✅ A full audit works end to end locally (62 browser checks, desktop and phone) |
| ✅ **3 · Protection** *(Day 4)* | Turnstile + session token · rate limit · spend cap + 80% Slack post | ✅ Going over the limits returns friendly errors (15 protection checks + 63 browser checks). Real Cloudflare keys and Slack webhook still to add |
| ✅ **4 · Capture + launch** *(Day 4–5)* | Email-this-report (Resend) · `/api/track` · `/audit/book` · ~~deploy to Railway + Vercel~~ *(skipped for now, by request)* · **Gate 3:** Shiv reads **10 reports**: do any two feel the same? · **soft launch to 10 known founders** | ✅ Built + tested locally (22 capture checks, 79–83 browser checks). ⏳ Deploy, Gate 3 and soft launch wait for your local testing |
| **5 · After launch** *(Days 6–7)* | `jobs.py` (follow-up email + Slack alert) · "call booked" Slack message with feedback links · Framer Client Engine bar | The jobs send correctly on test rows |
| **Later** | Newsletter · Calendly webhook (if the plan allows) · quarterly re-run (PRD §10.4: don't build it now, but `report` jsonb + `id` already make it possible) | — |

---

## 10. Environment variables

**Backend (`audit-app/backend/.env`)**
| Name | What |
|---|---|
| `ANTHROPIC_API_KEY` | Claude |
| `DATABASE_URL` | The new Neon project |
| `FIRECRAWL_API_KEY` | Backup website reader (the old key can be reused) |
| `RESEND_API_KEY`, `EMAIL_FROM` | e.g. `Ladder <audit@theladder.ai>` |
| `SLACK_WEBHOOK_URL` | Shiv's alert channel |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile |
| `SESSION_SECRET` | Signs session tokens and feedback links (any long random string) |
| `IP_HASH_SALT` | For `ip_hash` |
| `FRONTEND_URL` | Used to build report links in emails and Slack |
| `ALLOWED_ORIGINS` | The frontend domain + the Framer site (for the bar) |
| `DAILY_SPEND_CAP_USD` | e.g. `20` |

**Frontend (`audit-app/frontend/.env.local`)**
| Name | What |
|---|---|
| `NEXT_PUBLIC_API_URL` | The backend URL |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Cloudflare Turnstile (public key) |
| `NEXT_PUBLIC_CALENDLY_URL` | The booking link |
| `NEXT_PUBLIC_CLIENT_ENGINE_URL` | e.g. `https://theladder.ai/client-engine` |

---

## 11. PRD gaps: the defaults I'll use (confirm with Shivam)

| # | PRD gap | Default in this plan |
|---|---|---|
| 1 | "Rank by dollars" isn't defined when ranges overlap | Rank by **midpoint** |
| 2 | Contradiction: *never mention the Client Engine* vs `cta_bridge_sentence` | The bridge sentence is a **code template**; Claude never mentions the Client Engine |
| 3 | "Two of your three gaps…" is wrong when only one leak is Client Engine-fixable | **3 wording variants** (§6) |
| 4 | §7.7 says the ranges come from *"Ladder's delivery experience"*, but they actually come from benchmarks | Use *"based on published benchmarks for firms your size, deliberately conservative"*. **Needs Shiv's approval** |
| 5 | L6 and L12 have no non-dollar cost line | L6 uses the **pipeline** line (missed conversations); L12 uses the **time** line (hours spent fixing work) |
| 6 | The Q5 "referral" answer should point to L2 but isn't in L2's trigger list | Add it to L2's triggers in `library.py` |
| 7 | The scorecard says routing follows the "worst score", but the output uses `top_leak_pillar` | Route by **`top_leak_pillar`** |
| 8 | Nothing sets `call_booked` | The Calendly browser event on `/audit/book` (webhook later) |
| 9 | Report links are public | **Random, unguessable IDs** + `noindex` |
| 10 | "I'd rather not say" always triggers the Slack alert | Keep it, but mark the band as **"inferred"** in the Slack message |
| 11 | Shiv's feedback field has no easy input without Airtable | **One-click signed links** in the "call booked" Slack message |
| 12 | PRD §9.2 says Firecrawl `onlyMainContent: true` | **`false`**, because "main content" drops the nav links the flags depend on (see §4.2) |
| 13 | PRD §7.8 doesn't say which of its three "can't see" examples are fixed | Fixed: **team structure** and **close rate**. Claude writes the third from the founder's answers. **Needs Shiv to approve the wording** in `library.py` |
| 14 | PRD §8.1: Claude picks and sizes the 3 gaps | **Code does it** (`rules.pick_gaps`): the same answers + website always give the same gaps, ranges and scores. Claude only writes the words. Live QA showed Claude picking differently for identical answers and ignoring its own selection steps |
| 15 | "Score all twelve against the evidence" has no scoring method | Points from the PRD's own wording: "strongly triggered" = 2 · a Q3 tick = 1.5 ("maps directly to a leak") · other triggers = 1 · "no inbound ticked" = 0.5 (only "a signal") · Q1 = 0.5 · case studies + testimonials on the site = −1 against No Proof Layer. A gap needs one of its **defining** signals to be eligible (Q1 alone never qualifies). Range position: 1 point = bottom of the cell, 2 = middle, 3+ = top; width 40% of the cell |
| 16 | "Rank by dollar impact" lets a heavy gap with one weak signal win | Rank by **expected** cost = range midpoint × evidence (1 point counts ⅓, 3+ count fully). Pure dollars put "No Systematic Outbound" in 16 of 19 test reports, because not ticking outbound is true for almost everyone |
| 17 | PRD §9.2: read the homepage only, ~300 words | Also read the **case studies, services and about pages** linked from the menu (one each), ~700 words total. The homepage alone missed BMV's case studies and Digital Boardwalk's Case Studies page |
| 18 | "No website → Credibility 1–2" vs "never score all four low" | The specific rule wins: a founder with no website can see four low scores |
| 19 | Known limits of the scoring | Light gaps (Manual Onboarding, Fragmented Visibility) rarely make the top 3, because the PRD's light cells are small. L1's website-wording trigger ("generic or dated positioning") isn't checked. Recalibrate after 20 calls (PRD §12.4) |

---

## 12. What I need from you (before or during the build)

| # | Item | Needed by |
|---|---|---|
| 1 | ~~OK to create the new Neon project~~ ✅ **Done.** You created `ops-audit`, and the tables are in it | Phase 0 |
| 2 | ~~Anthropic API key~~ ✅ **Added** (25 Sept). Budget: **under $1 for the whole build** | Phase 1 |
| 2b | ~~Jina API key~~ ✅ **Added**, together with your own Firecrawl key | Before launch |
| 2c | 👀 **Shiv reads the Gate 2 reports** in `backend/fixtures/out/` and decides on the weighting question (see the Phase 1 log) | Before Gate 3 |
| 2d | 🔐 **Rotate the API keys after the build.** The Anthropic, Firecrawl, Jina and Neon keys were visible in this build session | Before launch |
| 3 | 🌐 **Where the site lives:** `audit.theladder.ai` or another domain? (The main site is on Framer and currently shows "Site Not Found") | Phase 4 |
| 4 | ⏳ **REMAINING: Resend API key** → `backend/.env` `RESEND_API_KEY`, **plus DNS access to theladder.ai** to verify the sending domain (Resend gives you the records to add). `EMAIL_FROM` is already set to `Ladder <priyanshu@theladder.ai>`. Without it, "email me this report" shows a polite error, and `/health` says `"email": false` | Before launch |
| 5 | ⏳ **REMAINING: Cloudflare Turnstile** site key + secret key (free, from the Cloudflare dashboard → Turnstile → add the site's domain). Replace the **test keys** in `frontend/.env.local` (`NEXT_PUBLIC_TURNSTILE_SITE_KEY`, then rebuild) and `backend/.env` (`TURNSTILE_SECRET_KEY`). ⚠️ The test keys let *anyone* through, so **never launch with them** | Before launch |
| 6 | ⏳ **REMAINING: Slack webhook URL** for Shiv's channel → `backend/.env` `SLACK_WEBHOOK_URL`. Without it, alerts are only logged. Check with `GET /health` → `"slack": true` | Before launch |
| 7 | ⏳ **REMAINING: Calendly booking link** → `frontend/.env.local` `NEXT_PUBLIC_CALENDLY_URL` (then rebuild). Until then `/audit/book` shows a placeholder where the calendar goes. Also say whether the Calendly plan is paid: webhooks (to catch bookings made outside our page) need a paid plan | Before launch |
| 8 | ☁️ **Railway + Vercel accounts** (whose accounts?) | Phase 4 |
| 9 | 🎨 **Framer access** for the Client Engine bar | Phase 5 |
| 10 | ✍️ **From Shiv:** Archaius card wording, the §7.7 wording, and a yes to the §11 defaults | Before Gate 3 |
| 11 | 📣 **Shivam's OK** on the choices that differ from the PRD (§0) | As soon as possible |

---

## 🧾 Phase log

### ✅ Phase 0 · Setup (finished 25 Sept 2026)

**What was built**
| File / thing | What it is |
|---|---|
| `backend/schema.sql` | The two tables: `audits` (34 columns, with checks on answers, scores, routes and feedback values, plus an index for the rate limit) and `scrape_cache` (7 columns). Safe to re-run |
| Neon `ops-audit` | `schema.sql` applied. Both tables exist and are empty |
| `backend/config.py` | Reads settings from `.env`. Stops immediately with a clear message if `DATABASE_URL` is missing |
| `backend/db.py` | One connection pool to Neon, plus `ping()`. Set up for Neon's pooled connection (`statement_cache_size=0`) |
| `backend/main.py` | The FastAPI app: opens and closes the database pool, CORS for the frontend, and `GET /health` |
| `backend/requirements.txt` | 6 pinned packages: fastapi 0.141.1, uvicorn 0.54.0, anthropic 1.8.0, asyncpg 0.31.0, httpx 0.28.1, python-dotenv 1.2.3 |
| `backend/.venv` | Python 3.11 virtual environment with the packages installed |
| `backend/.env` | Real local settings (the database URL is filled in). **Never commit it** |
| `backend/.env.example`, `frontend/.env.example` | Every variable the apps will need, labelled by phase |
| `frontend/` | Next.js 16.3.6 + React 19.2 + Tailwind 4 + TypeScript (App Router), from `create-next-app` |
| `frontend/next.config.ts` | Pins the project root. A stray `pnpm-workspace.yaml` in `C:\Users\priya` was confusing Next.js |
| `audit-app/.gitignore` | Keeps `.env`, `.venv`, `node_modules`, `.next` and fixture outputs out of git |

**Tests run, all passed ✅**
| # | Test | Result |
|---|---|---|
| 1 | Database: connect + `select 1` | ✅ Connected to PostgreSQL 18.6 |
| 2 | Valid row goes into `audits`, and the defaults are right | ✅ `mrr_inferred=false`, `cost_usd=0`, `call_booked=false`, JSON report stored |
| 3 | Bad data gets rejected | ✅ Wrong revenue band, score 11, wrong url_type and duplicate ID were all rejected |
| 4 | `scrape_cache` insert | ✅ Works |
| 5 | Tests leave no data behind | ✅ Everything ran in a rolled-back transaction, and both tables are still empty |
| 6 | Backend server: `GET /health` | ✅ `200 {"status":"ok","db":true}` |
| 7 | CORS | ✅ `localhost:3000` is allowed; a random origin gets no CORS header |
| 8 | Missing `DATABASE_URL` | ✅ Stops with *"Missing required env var DATABASE_URL…"* |
| 9 | Frontend lint | ✅ No errors |
| 10 | Frontend production build | ✅ Compiles, no warnings |
| 11 | Frontend server | ✅ `GET /` returns 200 |

**Notes**
- `create-next-app` made its own git repo inside `frontend/`. I removed it so `audit-app/` can become one repo later (it only held the scaffold's first commit).
- The frontend's default `.gitignore` also ignored `.env.example`. That's fixed, so the example file can be committed.
- **How to run locally:**
  - Backend: `cd audit-app/backend` → `.venv\Scripts\activate` → `uvicorn main:app --reload --port 8100` → open `http://localhost:8100/health`
  - Frontend: `cd audit-app/frontend` → `npm run dev` → open `http://localhost:3100`
  - *(Ports changed from 8000/3000 in Phase 2, because LadderFlow runs there.)*

**Needed from you for Phase 1:** an **Anthropic API key** (goes in `backend/.env` as `ANTHROPIC_API_KEY`). The Firecrawl key from the old project can be reused.

---

### ✅ Phase 1 · Engine (finished 25 Sept 2026)

**What was built** (all in `backend/`)
| File | What it does |
|---|---|
| `library.py` | ⭐ **Single source of truth.** The question options (exact PRD wording), **all 12 leaks word for word from PRD §5**, the band table (§6.1), non-dollar lines (§6.4), the 4 case studies and how Claude should frame each (Archaius = *consistency*), and all fixed report copy (CTA text, "can't see" items, "how we calculated", verdict subline). PRD-gap defaults are marked `PRD gap:` in comments |
| `rules.py` | Everything that's a lookup or a sum. It checks Claude's answer (exactly 3 different leaks, valid IDs, not all from one pillar), **clamps each dollar range into its band×weight cell**, rounds to $100, sorts by midpoint, caps selected pillars' scores at 5, adds up totals, and picks the CTA route, case study, bridge sentence (3 variants), banner fallbacks, "how we calculated" text and cost in $ |
| `prompt.py` | Builds Claude's system prompt from `library.py` (all 8 required contents from PRD §8.1, plus the Q2 signal rules, the case studies, and the degraded-mode block when the site can't be read). About 3,400 tokens, prompt-cached. Also builds the PRD §8.2 user message |
| `generate.py` | The Claude call: `claude-sonnet-5`, structured outputs (`messages.parse` with a Pydantic model), effort `medium`, no temperature. **One retry**, with the problems fed back if the answer breaks a rule, gets cut off, or doesn't parse. Clear error if the key is missing. `build_report()` = website read → Claude → finished report |
| `scrape.py` | URL normalising (bare domains, `www.`, social profiles, rejects junk and `user@host` tricks). Jina reader (one retry on rate limit) → Firecrawl fallback. Trims to about 300 words: title, meta description, H1 (or first heading), first two sections, **client names from logo walls**, and yes/no flags for case studies, testimonials and blog. Background reads, 30-day cache, and a 4-second wait at audit time |
| `guard.py` | Signed session tokens (30 min) carrying the URL from the URL screen to the audit. IP hashing (the raw IP is never stored; the real IP is taken from the *last* X-Forwarded-For entry so it can't be faked) |
| `db.py` | Added: read/save the website cache, save an audit (the full report + 23 flattened columns), load a report |
| `main.py` | Added `POST /api/scrape`, `POST /api/audit` and `GET /api/report/{id}`, with strict answer validation (only the exact option keys from `library.py` are accepted) and friendly error messages |
| `test_rules.py`, `test_scrape.py` | Offline checks: run `python test_rules.py` and `python test_scrape.py` |
| `scrape_check.py` | Gate 1: reads real sites live and writes `fixtures/out/scrape_check.md` |
| `fixtures/inputs.json` + `run_fixtures.py` | Gate 2: 15 fake founders covering every Q1 option, all 7 revenue answers, normal/LinkedIn/no-website/unreadable sites, and a deliberate "twin" of fixture 1 to test that two similar firms get different reports. Writes one Markdown report per founder, plus `SUMMARY.md` with automatic checks (word counts, banned phrases like "it seems", "Ladder" or "!", "revenue leak" used twice, all-low scores) |

**Tests run**
| # | Test | Result |
|---|---|---|
| 1 | `test_rules.py`: library matches the PRD (12 leaks, 3/3/2/4 per pillar, band cells valid and increasing), band/rounding/clamping edge cases, retry triggers, **PRD_EXPLAINED Example A** (→ L4, L5, L2 · $22,000–29,200 · Client Engine · Hot Inbox) and **Example B** (→ Delivery · booking · Archaius · $12,000–16,600), all 3 bridge-sentence variants, score caps, midpoint ordering, banner fallbacks, cost maths | ✅ all passed |
| 2 | `test_scrape.py`: URL normalising (8 good, 6 bad inputs), page trimming, logo names, flags, ≤300 words; session tokens (valid, 4 forged, expired); IP hashing | ✅ all passed. **It caught a real bug** (`mailto:x@acme.com` was accepted as acme.com), now fixed |
| 3 | **Gate 1** (`scrape_check.py`, 42 real sites) | ✅ **39/39 reachable sites (100%) returned 200+ words**, including **13 Framer/Webflow** (3 Framer, 10 Webflow). Firecrawl rescued 10 sites Jina couldn't read on its own. 3 sites were down or blocking even a normal browser |
| 4 | API: `/api/scrape` with a real site, junk ("hello"), no website, LinkedIn | ✅ 200 / 422 with a friendly message / 200 `none` / 200 `social` |
| 5 | API: `/api/audit` with a forged session, bad answers, and valid answers without a Claude key | ✅ 401 / 422 naming `q1`, `q2` / 502 friendly message. The log now says clearly that the key is missing |
| 6 | Background read → cache | ✅ The kalungi.com read was saved while the endpoint had already returned (2,173 words, all 3 flags) |
| 7 | Save + load a full report | ✅ Identical round-trip; flattened columns correct. Test rows deleted afterwards (both tables empty) |
| 8 | Claude output schema (offline) | ✅ Valid. Leak IDs become a strict L1–L12 list, and every object is locked (`additionalProperties: false`) |

**Fixes made along the way:** rejected `user@host` URLs · Jina rate-limit retry · Firecrawl reads the full page (`onlyMainContent: false`) · the missing-key error is no longer hidden inside the retry loop · the fixture runner's concurrency limit was being re-created per fixture.

**Live tests with Claude (after the key was added)**
| # | Founder | Leaks picked (rank order) | Total / month | Route · proof | Cost | Time |
|---|---|---|---|---|---|---|
| F1 | animalz.co, content agency, referral-heavy (effort *medium*) | L4, L5, L2 | $22,300–26,500 | Client Engine · Hot Inbox | $0.070 | 60s |
| F2 | thoughtbot.com, dev shop, delivery strain | L9, L2, L12 | $30,000–35,800 | **booking · Archaius** | $0.042 | 30s |
| F12 | no website | L4, L2, L5 | $14,400–16,600 | Client Engine · Hot Inbox | $0.038 | 25s |
| F13 | LinkedIn page only, under $50K | L4, L2, L3 | $2,900–3,900 | Client Engine · Hot Inbox | $0.017 | 19s |
| F14 | website unreadable → degraded path (run twice, see fix below) | L4, L2, L12 | $20,500–25,500 | Client Engine · Hot Inbox | $0.034 ×2 | 21–24s |
| F15 | "twin" of F1: same answers, a different content agency | L4, L5, **L8** | $21,400–25,800 | Client Engine · Hot Inbox | $0.047 | 36s |
| API 1 | **real API end to end:** pilot.com, "I'd rather not say" | L5, L2, L6 | $10,100–11,700 (band inferred ✓) | Client Engine · Hot Inbox | $0.034 | 36s |
| API 2 | **real API end to end:** bairesdev.com, $500K+, delivery | L9, L12, L8 | $41,700–46,800 | **booking · Archaius** | $0.043 | 45s |

- ✅ **The end-to-end API works:** `/api/scrape` → site read in the background → `/api/audit` → row saved in Neon with every column correct → `/api/report/{id}` returns it. **Both rows are kept** (IDs `y-Coy4Ov2DoW` and `igJjugSt29iu`) as sample data for building the frontend, one per CTA route, so Phase 2 needs no extra Claude spend. **Delete them before launch.**
- ✅ **Prompt caching works** (6,287 cached tokens per call).
- ✅ **The twin test (F1 vs F15) passes:** identical answers, clearly different reports. Each quotes its own positioning ("intelligent content for compounding growth" vs "Pain Point SEO"), the slot-3 leak differs, and credibility scores 5 vs 8.
- ✅ **The degraded path (F14) works**, after a fix. The first run guessed an industry from the domain ("growth marketing agency") and wrote "your site looks credible" without having read the site. **Fixed in two layers:** the code forces "your **firm**" whenever the site wasn't read, and the prompt forbids describing an unseen site. Re-run confirmed ✅.
- ✅ **Reading LinkedIn works.** F13 called "ThoughtBot" an IT staffing firm. That's correct: `linkedin.com/company/thoughtbot` is a *different* company from thoughtbot.com (my fixture chose the wrong LinkedIn address).
- 🔧 **Other fixes from the live runs:** no question numbers in the text ("Q2 shows…" was banned and added to the automatic checks) · capitalisation of Claude's fields · the word-count instruction made explicit · effort set to `low` (60s → about 30s, $0.07 → about $0.04).
- ⚠️ **Short descriptions:** the automatic checks flagged 4 of the 18 leak descriptions they cover (F1 ×1, F13 ×2, F15 ×1) at 52–59 words (target 70–90). The two API runs aren't auto-checked. Minor. Left for Shiv to judge before spending on more prompt tuning.

**👀 For Shiv (Gate 2): the weighting question.** Heavy leaks win almost every time, even with weaker evidence:
- **F1:** picked *No Proof Layer* for slot 3 although Animalz **has** case studies ("you do have case studies, but…"), while *Proposal Bottleneck* had two direct triggers.
- **API 1 (pilot.com):** the founder said their main breakdown is **"understanding what's happening across the business"** (Q1 E), yet the top leak is *No Systematic Outbound*. Its only trigger is that "cold outbound" wasn't ticked, and it wins because it's Heavy.
- This is PRD_EXPLAINED gap #5 showing up in real output. **Shiv decides:** keep the PRD weights as they are, or let strong evidence outrank weight (a one-paragraph prompt change, re-tested on a few fixtures).

**💰 Anthropic spend ledger (budget: under $1 for the whole build)**
| Step | Cost |
|---|---|
| F1 at effort medium | $0.070 |
| F2 + F12 + F15 | $0.127 |
| API end-to-end ×2 | $0.077 |
| F13 + F14 | $0.053 |
| F14 re-run after the fix | $0.034 |
| **Total** | **$0.361** |

Remaining: about $0.64. Running the other 7 fixtures (3–8, 10) would cost about $0.28 (`python run_fixtures.py 3 4 5 6 7 8 10`). Worth doing once Shiv has decided the weighting question, so the money isn't spent twice.

**Data now in Neon:** 2 sample audits (keep for Phase 2, delete before launch) and 6 cached website reads (harmless; they expire after 30 days).

---

### ✅ Phase 2 · Founder flow (finished 25 Sept 2026)

**What was built** (in `frontend/`, plus two backend additions)
| File | What it does |
|---|---|
| `app/audit/page.tsx` | Landing page: a short intro (placeholder copy for **Shiv to rewrite**) with **Q1 right underneath**, as PRD §9.3 wants ("landing page with embedded question widget") |
| `components/AuditFlow.tsx` | The whole flow: **Q1 → website → Q2 → Q3 → Q4 → Q5 → generating → report**. "Question n of 5" with a 5-step bar (hidden on the website screen, PRD §4). Back button on every screen, answers kept. **Taps auto-advance on single-choice questions; arrow keys don't** (keyboard users press Enter), so keyboard users aren't thrown to the next question. Re-tapping an already-chosen answer advances too. Focus moves to each new question's heading for screen readers. Friendly errors: nothing picked, empty or junk website (the server's message), network down. An expired session sends the founder back to the website screen. "I don't have one yet" works |
| Generating screen (inside `AuditFlow`) | The 5 PRD status lines with **their real domain and band** ("Reading pilot.com…", "Sizing impact against $100K–$200K MRR…"), then 3 honest "still working" lines, because a report takes 20–45s. Announced to screen readers. If it fails: "Try again" without re-entering anything |
| `app/audit/r/[id]/page.tsx` + `components/Report.tsx` | The report, all PRD §7 sections in order: **7.1** dark verdict banner with the **total as the largest element** (fits phones), subline, "3 gaps · band (assumed)". **7.2** the read. **7.3** 4 scores as number + bar + reason (colour is never the only cue). **7.4** 3 leak cards, **#1 visibly heavier**, each with "Also costing you". **7.5** what we'd build (does / changes / time). **7.6** proof card, **no outbound links**. **7.7** "How we calculated this", **collapsed**. **7.8** can't-see list. **7.9** routed CTA: Client Engine page `?audit=id` + "Book a call" link, **or** "Book 30 minutes". **7.10** permalink + copy button. **7.12** footer with date, source and report ID. `noindex` so reports never reach Google |
| `app/audit/r/[id]/not-found.tsx` | Friendly 404 for a wrong or old report link |
| `components/CopyLinkButton.tsx` | Copies the permalink. If the clipboard is blocked, it selects the link so Ctrl+C works |
| `app/globals.css` | Design tokens: ink on a cool off-white, deep green for selections and focus, red only for money lost. **Rebrand by editing this one file** |
| `lib/api.ts` | Backend calls + the report's TypeScript type |
| `backend/library.py` → `frontend/lib/content.json` | Question screens and CTA button text now come from `library.py` (`python library.py` regenerates the JSON). `test_rules.py` fails if they drift |
| `e2e_check.py` | Browser test using the Edge already on Windows (Playwright, dev-only). Clicks through everything at 1280px and 390px, with screenshots in `e2e_out/` |

**Also changed:** local ports moved to **8100 / 3100** because LadderFlow is running on 8000 / 3000. Updated in `package.json`, `.env`, `.env.example`, `config.py` and `lib/api.ts`.

**Tests: 62/62 browser checks passed ✅** (`python e2e_check.py --live`)
| Area | Checks |
|---|---|
| Report pages (both routes, desktop + phone) | Verdict sentence, 3 leak cards, 4 scores in PRD order, CTA → Client Engine `?audit=id`, secondary → booking, booking route → "Book 30 minutes" and no Client Engine button, Archaius card with **no outbound link**, `noindex`, "How we calculated" collapsed then opens, **no sideways scrolling at 390px** |
| Copy link + 404 | Permalink box shows the right URL, copy puts it on the clipboard, an unknown ID shows the 404 page |
| Question flow (desktop + phone) | `/` → `/audit`, intro + Q1 on landing, counter "1 of 5", **arrow keys don't auto-advance**, Enter continues, focus moves to the heading, no counter on the website screen, empty and junk website errors, real site → Q2, nothing ticked → error, **Back keeps ticks**, a tap auto-advances Q4 → Q5 |
| **Live audit through the browser** | Generating screen shows the real domain and band → landed on the new report after **33s**, "(assumed)" band shown |
| Also | `npm run lint` clean, production build + TypeScript pass, backend tests still pass |

**Screens reviewed by eye:** landing + Q1 (desktop), Q5 (phone), full report (desktop), report top (phone), generating screen. One polish made from that review: "The read" is one size smaller on phones.

**💰 Spend this phase:** 1 live audit = **$0.044** → **build total $0.405** (budget $1.00).

**Data now in Neon:** 3 sample audits (`y-Coy4Ov2DoW`, `igJjugSt29iu`, `QXDRPVqEMZpv`). **Delete all before launch.**

**Not in Phase 2, on purpose:** `/audit/book` (Phase 4, so the booking links 404 until then) · "email this to me" (Phase 4) · click tracking (Phase 4) · newsletter checkbox (on hold) · Turnstile on the website screen (Phase 3).

**For Shiv:** the landing intro copy is a placeholder · the generating screen now has 8 lines instead of the PRD's 5, because reports take 20–45s.

---

### ✅ Phase 3 · Protection (finished 25 Sept 2026): real Cloudflare keys + Slack webhook still to add

**What was built** (PRD §9.4, "non-negotiable before launch")
| Protection | How it works | Where |
|---|---|---|
| 🤖 **Turnstile human check** | A Cloudflare widget on the website screen, **invisible unless Cloudflare needs a click**. `/api/scrape` refuses with a **403** without a valid token. Tokens are single-use, so the widget resets after every attempt, and the flow **waits up to 5s** for the token instead of erroring. If Cloudflare is unreachable, the backend **fails closed**. If the widget never loads (e.g. an ad blocker), the founder sees a clear message | `components/Turnstile.tsx`, `AuditFlow.tsx`, `guard.verify_turnstile` |
| 🚦 **Rate limit** | **3 audits an hour, 10 a day per IP** (rolling), counted in Neon *before* any money is spent → **429**: "You've reached the limit of 3 audits an hour…". Audits still in progress count too, so firing parallel requests can't slip past. Limits are configurable (`RATE_LIMIT_PER_HOUR` / `_PER_DAY`) | `guard.rate_limit_message`, `db.count_recent_audits` |
| 💳 **Daily spend cap** | Before each audit: if today's Claude spend (UTC day, from `audits.cost_usd`) ≥ `DAILY_SPEND_CAP_USD` ($20) → **503** "The audit is paused for the rest of today". Claude is never called | `guard.check_spend`, `db.spend_today` |
| 🔔 **Slack alerts** | **At 80% and at 100%** of the cap, once per level per day. Checked before and after each audit, so the alert fires as soon as it's crossed | `notify.slack`, `guard.check_spend` |
| 🩺 **/health** | Now reports `"turnstile"` and `"slack"` as true/false, so a deploy with protection switched off is obvious | `main.py` |

**Tests, all passed ✅** (none of it spent anything on Claude)
| Suite | Result |
|---|---|
| `protection_check.py` (real backend + Neon + Cloudflare's official test keys + a fake Slack webhook) | ✅ **15/15**: no token → 403 · empty token → 403 · valid → 200 · Cloudflare "fail" key → 403 · Turnstile off shows in /health · 4th audit in an hour → 429 · 11th in a day → 429 · over the cap → 503 + **one** Slack alert · 85% → allowed + **one** "80%" alert · a running audit counts towards the limit. Its 10 temporary rows were deleted afterwards |
| `e2e_check.py` (Edge, desktop + phone) | ✅ **59/59** normal flow through Turnstile, **plus** the website request proven to carry Cloudflare's token · ✅ **63/63** with `--blocked` (limit set to 0): the founder sees the friendly limit message + "Try again" |
| `test_rules.py`, `test_scrape.py` (+ spend-alert levels), `npm run lint`, `npm run build` | ✅ all pass |

**Found and fixed while testing:**
- Cloudflare's *always-pass* test secret accepts **any** token, so the "Cloudflare rejects it" path is tested with the *always-fail* secret instead. Worth knowing: **the test keys protect nothing.**
- The limit message showed the configured number ("You've run 0 audits…" when the limit was 0). It now reads "You've reached the limit of 3 audits an hour."

**Known limits** (fine at launch volume, marked `ponytail:` in the code):
- The "still running" count and the "alert already sent" memory live in the one Railway server, so a restart can repeat an alert once.
- The spend cap counts saved audits only. A failed Claude call's cost isn't counted, and neither are Firecrawl credits.

**⏳ Remaining (needs you):**
1. The **real Turnstile site key + secret key**, replacing the test keys in `frontend/.env.local` + `backend/.env`.
2. The **Slack webhook URL**.

Both are in §12.

**💰 Spend this phase: $0.00** → build total **$0.405**.

---

### ✅ Phase 4 · Capture + crawl QA + single-page form (finished locally 26 Sept 2026): not deployed, by request

#### A. Crawl quality check ("does the website read really work?")
Gate 1 had only counted words. This time I read **what Claude actually receives** for every site (`fixtures/out/scrape_contexts.md`) and found real problems:
| Problem found | Example | Fix |
|---|---|---|
| **Cookie popup read instead of the site** | stxnext.com "passed" with 2,626 words, all of them cookie-consent text | Consent and cookie lines are dropped. Content words are counted **after** cleaning, so a cookie-only page counts as *unread* and **Firecrawl takes over**. STX Next now reads correctly: *"Engineered for what's next: We turn isolated AI experiments into resilient operational systems…"* |
| **Menus and banners before the real content** | thoughtbot's headline is on line 52; growandconvert's on line 34 | Content is read **from the main headline (H1) down**. Menu items, "Skip to main content" and similar are dropped |
| Leftover codes | `&amp;`, `**bold**`, `PYTHON\_` | Decoded and stripped |
| Old reads cached with the messy cleaning | 5 cached sites | A `CLEANING_VERSION` date makes older cache rows get re-read automatically (no deletes needed). Bump it whenever cleaning changes |

The yes/no flags (case studies, testimonials, blog) and client-logo names still read the **whole** page, because nav links like "Case Studies" are real evidence.
**Result: 39/39 reachable sites (100%) pass with the stricter real-content count**, including 13 Framer/Webflow. Jina key confirmed working (reads now take 1–8s). Main content now opens with each firm's real positioning (reviewed for all 39).

#### B. Capture features (PRD §7.10, §9.3, §10.1)
| Feature | How it works | Where |
|---|---|---|
| 📧 **Email me this report** | A form in the report's Save section → `POST /api/email-report` → Resend email with the report link, the total and the 3 gaps. HTML is escaped, and it states plainly that it's not a newsletter sign-up. Max **3 sends per report**; a failed send doesn't count. Saves `report_email` (**not** newsletter consent) | `EmailReportForm.tsx`, `notify.report_email/email`, `main.py` |
| 👆 **Click tracking** | Both CTA links send a `sendBeacon` (survives leaving the page) → `POST /api/track` → `clicked_cta`. Unknown events → 400; unknown report → 204 (reveals nothing) | `TrackedLink.tsx`, `db.set_flag` |
| 📅 **Booking page** `/audit/book?audit=id` | The report summary (total + 3 gaps + link back) next to the **Calendly** widget. When Calendly reports a booking, `call_booked` is set and "You're booked" shows. **Only messages from calendly.com are trusted.** No Calendly link yet → a clear placeholder. `noindex` | `app/audit/book/page.tsx`, `CalendlyEmbed.tsx` |
| 🩺 `/health` | Now also reports `"email"` on/off | `main.py` |

#### C. All questions on one page (user's request, 26 Sept: "mock frontend")
The step-by-step flow was replaced by **one scrolling form** (details in §8.1). The PRD's key behaviour is kept: **the website read starts as soon as the website field is left**, in the background, and is reused on submit.

#### D. Robustness fixes found while testing
- **This machine's DNS intermittently fails to look up the Neon database address**, which crashed the backend on startup twice. `db.init()` now **retries 5 times, 2 seconds apart**. Seen working in the final run: *"Database not reachable… retrying in 2s (1/5)"*, then it recovered.
- Cloudflare's token takes **~3–5s** after page load (measured), so the form waits **up to 10s** for it instead of 5.

#### Tests: all passed ✅
| Suite | Result |
|---|---|
| `capture_check.py` (real backend + Neon + fake Resend) | ✅ **22/22**: health, bad address 422, unknown 404, valid send (right recipient, sender from `.env`, API key), link + total + 3 gaps in the email, **HTML-escaped company name**, "not a newsletter" line, `report_email` saved, Resend down → 502 **without using up a send**, 4th send → 429, exactly 3 emails, no key → 502, all 3 tracking events set their flags, bad event/body → 400, unknown id → 204. Temporary report deleted |
| `scrape_check.py` | ✅ 39/39 reachable, with the new real-content counting |
| `e2e_check.py` (Edge, desktop + phone, fake Resend) | ✅ **79/79** normal · ✅ **83/83** `--blocked` · ✅ **82/82** `--live` (a real audit through the new form: generating screen → report in 36s) |
| `test_scrape.py` (new cases built from the real thoughtbot/stxnext junk), `test_rules.py`, `protection_check.py`, lint, build | ✅ all pass |

**💰 Spend this phase:** 1 live audit = **$0.046** → build total **$0.451**.

**Data now in Neon:** 4 sample audits (`y-Coy4Ov2DoW`, `igJjugSt29iu`, `QXDRPVqEMZpv`, `yuRwXXfTp5B3`) and a few cached site reads. **Delete the audits before launch.** The browser test resets the sample rows' tracking flags after itself.

**⏳ Remaining from this phase:** a Resend key + DNS for theladder.ai · the Calendly link · deploy (on hold) · Gate 3 (Shiv reads 10 reports) and the soft launch, after your local testing.

---

### 🧪 Live QA in the user's Chrome (26 Sept 2026)
4 real firms filled in through the UI, one tab each (answers were a realistic guess from each firm's public info):
| Tab | Firm | Report | Result |
|---|---|---|---|
| 1 | beantownmv.com (B2B tech PR) | `QT_LoQ-c6xgR` | $13,000–15,300 · L4, L5, L2 · Client Engine · Hot Inbox |
| 2 | digitalboardwalk.com (MSP) | `JJGQu3Smbxq3` | $19,100–22,300 · L9, L2, L12 · **booking · Archaius** |
| 3 | captivatetalent.com (SaaS recruiting) | `jjsIz3qGBn2c` | $21,800–26,100 · L7, L5, L8 · Client Engine · **Storata** |
| 4 | zeritaz.com (fractional CFO, "rather not say") | `1jh9qchGzxwS` | $8,300–10,200 (assumed band) · L4, L9, L10 · Client Engine · Hot Inbox |
Cost $0.116 (runs 2–4 read the prompt cache), 23–36s each. The local rate limit was raised to 10/hour for testing: **set it back to 3 before launch.**

**✅ Good:** all routing correct (all 4 pillars' case studies behave as specified); every dollar range inside its cell; every specific fact Claude cited really is on the firm's site (verified against the stored context: "CMMC/HIPAA", "money back", "Bloomberg", "frontier labs", "full-stack", "Babbel"); the 4 reports are clearly different; the tone rules held.
**❌ Found (to fix):**
1. **False absence claims (serious).** BMV's homepage has 4 client testimonials and ~50 unlabelled logo images, but the report said "no client logos or testimonials… not a single named client". Cause: keyword flags said "no", and Claude treated that as fact.
2. **Garbled sentence** when revenue is "rather not say" (Zeritaz: "the $100K–$200K band you told us falls to inferred rather than confirmed").
3. **A $100-wide range** ($3,500–3,600, Zeritaz L9) after clamping: looks like false precision.
4. **Descriptions run short:** 12/12 were 49–68 words (target 70–90).
5. The self-logo bug (Zeritaz's own logo counted as a client) was found **before** the run and fixed.

**🔧 Fixed, then the same 4 founders were re-run in tabs 5–8:**
- `scrape.py`: quoted blockquotes (`> "…`) count as testimonials. Context lines now say "detected on the homepage (automated check, can miss things)" and "Client logos named on the homepage: none detected (unlabelled logo images cannot be read)". `CLEANING_VERSION` bumped, so every site is re-read.
- `prompt.py`: a new section says the context is a homepage snapshot, so "no" never means "doesn't exist". It bans "anywhere", "not a single" and "zero", gives exact wording for "rather not say" ("Without a revenue figure, we've sized this against a typical $100K–$200K firm"), asks for descriptions of 4–5 sentences / 70–90 words, and asks for single quotes when quoting a site.
- `rules.place_in_cell`: a minimum range width of max($500, ¼ of the cell), widened around the range's middle and staying inside the cell.
- `rules.problems`: **new, found in the re-run.** If the read, a description or a tie-in doesn't end like a sentence, the answer is retried. Zeritaz's re-run read ended "…Your homepage still presents a generic": a double quote closed the text early. Across all 12 saved reports this check fires only on that real cut-off.

| Tab | Firm | Report | Before → after |
|---|---|---|---|
| 5 | BMV | `VYv4jT16xTZ5` | Testimonials now detected, so the false "no testimonials / not a single client" claim is gone. L2 No Proof Layer was replaced by L3/L8. $13,000–15,300 → $7,900–11,800 |
| 6 | Digital Boardwalk | `FaTlU9x6caEA` | "no case study… anywhere… zero visible proof" → "your homepage doesn't put named results… in front of a cold visitor". $19,100–22,300 → $15,500–24,000 |
| 7 | Captivate | `NREeQhyEoIqj` | Same diagnosis; descriptions 53–60 → 68–82 words |
| 8 | Zeritaz | `q_35WgOGkcBd` | Inferred sentence fixed word-for-word; $3,500–3,600 sliver → $3,500–5,500; **the read was cut off (guard added after this run)** |

Descriptions of 70+ words: 0/12 before → 8/12 after (the other 4 are 66–68). Narrowest range: $100 → $1,000. Cost $0.105.
**Open (now fixed by 4b below):** Digital Boardwalk L9 came back as the whole cell ($5,900–10,200). A cap at about half the cell would keep the placement meaningful (not applied yet). The local daily limit is now raised to 20 for testing: **set it back to 10 (and hourly back to 3) before launch.**

### ✅ 4b · Code scoring + reading linked pages (finished 26 Sept 2026): differs from the PRD, see §11 gaps 14–19
**Why:** live QA showed that (a) Claude picked different gaps for identical answers and sometimes broke its own selection steps (BMV run 2 dropped a 3-signal heavy gap for a 1-signal one), and (b) reading only the homepage missed real proof pages.

**What changed**
- `scrape.py`:
  - Reads the homepage, then the **case studies, services and about pages** it links to, in parallel with the same reader (15s cap each; failures are skipped).
  - Links come from Jina's link summary, which includes menus the markdown drops (Digital Boardwalk's markdown had zero links).
  - If a site has no case-study index, one case study in a `/portfolio/…`-style folder stands in (BMV).
  - Other additions: bot-check pages and pages under 20 words are dropped; social icons don't count as client logos; a quote on its own line counts as a testimonial.
  - The context says which pages were read. The audit waits up to 8s (was 4s) for a read still running.
- `rules.py`:
  - `signals` → `pick_gaps` → `size_range` → `pillar_scores` (method in §11 gaps 14–16). Claude gets the 3 gaps, their ranges, the evidence behind each and the scores.
  - `problems` now only checks that Claude wrote about exactly those 3 and didn't cut a sentence off.
  - `finalize` takes every number from the diagnosis.
- `prompt.py`: the dollar table and selection steps are removed. It adds "how this audit works", a DIAGNOSIS block in the user message, a rule for when answers and site disagree, and score rationales (words only).
- `library.py` "How we calculated": one sentence added on how evidence sets the position in the range.
- Report page: a **"Why we flagged this"** list under each gap (the signals, e.g. "Your week goes to writing proposals one at a time").
- Bug found and fixed: `CLEANING_VERSION` had been set in the future again, which silently turned the cache off. `test_scrape.py` now fails if it's ever in the future.

**Tests**
- `test_rules.py` checks:
  - fixed cases (BMV, Digital Boardwalk, many-channels, thin evidence, no website);
  - **3,000 random founders**: always 3 different gaps, never one pillar, inside the cells, dollar order, scores in range.
- `test_scrape.py` covers link finding and the linked pages.
- An offline simulation of the 15 fixtures + 4 live founders showed a sensible diagnosis for each (it caught the "No Systematic Outbound for a founder who ticked outbound" bug, fixed with the defining-signal rule).
- e2e: all 17 report-page checks pass. The email step fails only because Resend rejects the sender until theladder.ai is verified (422).

**Live re-run, tabs 9–12:**

| Tab | Firm | Report | Result |
|---|---|---|---|
| 9 | BMV | `2IZyOCZRIuLA` | L4, L5, L8 · $12,800–15,500 · reads the Boson AI case study and the services page; no false "no proof" |
| 10 | Digital Boardwalk | `kapsrUmN-1uO` | L9, L5, L12 · $19,100–23,700 · booking · finds its case studies + testimonials pages, so Credibility is 9 |
| 11 | Captivate | `rigLnYYTcBNG` | L5, L7, L8 · $21,700–26,300 · names Firefly, Harmonya, Salus, Magic from its clients page |
| 12 | Zeritaz | `Sr3smPpwv48u` | L4, L9, L6 · $11,000–13,700 · cites its Series A/Seed clients at $1M–6M run-rate |

- All 4 saved reports **recompute identically** from the cached site read: same gaps, ranges and scores.
- No dollar figures outside the diagnosis.
- Descriptions are 69–95 words.
- Cost $0.104 (about 2–4 cents each); about 28s of generation per report.

### ✅ Phase 5 · Follow-up, Slack alerts, feedback loop, funnel tracking (finished 26 Sept 2026): Framer bar still to do
**Built**
- `jobs.py`: the 48-hour follow-up email (PRD §10.1) and the 24-hour Slack alert (§10.3), every 10 minutes when `JOBS_ENABLED=true`. Details are in §7.
  - The follow-up email is built from the saved report, so there's no Claude cost. It has the top gap and its monthly cost, "what we'd fix first" and time to stand up, then **Read your full report** and **Book 30 minutes** buttons. It closes with "This is the only follow-up we'll send."
  - Slack alert: company, website, revenue band (marked "assumed" for "rather not say"), total, top gap, the 3 gaps, how to reach them (email if given, otherwise their website), whether they clicked since, a report link and a feedback link.
- "Call booked" Slack message: sent once, the moment `/audit/book` records a booking. It links the report and the feedback page.
- **Feedback loop (PRD §12.4):** `GET /api/feedback/{id}?sig=…`
  - It's a signed link with no expiry, and a page showing the company, the top gap and three buttons: yes, partly, no.
  - Only pressing a button (a POST) saves `top_leak_was_correct`, so Slack's preview bot can't answer by opening the link. Link previews are also switched off.
- **Funnel tracking (PRD §12.1):**
  - A new table `funnel_events` holds one row per browser per step, with no personal data.
  - `POST /api/funnel` accepts: landing, Q1–Q5 answered, website given, Q4 reached (the revenue question scrolled into view), submitted. Steps after the report come from the `audits` flags.
  - `python funnel_report.py [days]` prints every PRD step against its target, plus the watch items: Q4 drop-off under 85%, unreadable websites over 10%, Delivery as top gap over 35%, and feedback count.
- New env vars: `JOBS_ENABLED`, `PUBLIC_API_URL` (`.env.example` updated). `/health` shows `"jobs"`.

**Tests**
- `phase5_check.py`: **37 checks**, against the real database with fake Slack and Resend.
  - Due and not-due rows for every rule (clicked, Client Engine visit, booked, too soon, too old, small firm, unreachable), nothing sent twice, a failed send retried, no webhook means nothing claimed.
  - Escaping in email and Slack.
  - The booked message sent only once.
  - Feedback: a signed link, no save on open, bad signature → 403, bad answer → 422.
  - Funnel: steps deduplicated, bad input rejected, and the report's contents.
- The existing suites still pass (rules, website reading, 15 protection, 22 capture). `protection_check.py` now sets the PRD's rate limits itself instead of reading the raised `.env` values.
- In a real Edge window, 8 of the 9 funnel steps reached the database. The 9th, "gave website", depends on Turnstile.

**Turnstile with the real keys:** a Playwright-driven browser never gets a token. Cloudflare starts its check but doesn't pass automated browsers, which is the point of it. **Needs one manual check by the user in a normal browser** (enter a website, click away: no "human check" error = working). Automated browser tests need the Cloudflare test keys.

**Still to do:** the Client Engine bar (PRD §7.9/§9.3), which needs the live Client Engine page and Framer access. No Claude spend this phase.

### 🚀 Deployed to Render (27 Sept 2026, at the user's request)
- **GitHub:** [PriyanshuKanyal37/Ops_audit](https://github.com/PriyanshuKanyal37/Ops_audit). It's **public**, so the prompt, scoring and this plan are visible to anyone.
  - Before the push, all 60 files were checked against every real secret value in both env files plus 10 key patterns: clean. `.env` / `.env.local` are git-ignored.
  - If you make the repo private, Render needs GitHub access to it, or auto-deploy stops.
- **Render** ("Priyanshu's workspace", **Singapore** next to the Neon database, **free plan**, auto-deploy on every push to `main`):

  | Service | URL | Setup |
  |---|---|---|
  | `ops-audit-api` (srv-dasihk0473hc738eunrg) | https://ops-audit-api.onrender.com | `backend/`, `pip install -r requirements.txt`, `uvicorn main:app --host 0.0.0.0 --port $PORT`, health check `/health`, Python 3.11.11 |
  | `ops-audit-web` (srv-dasihl97lnhs739be00g) | https://ops-audit-web.onrender.com | `frontend/`, `npm ci && npm run build`, `npx next start -p $PORT`, Node 22 |

- **Env:**
  - API: everything in `backend/.env` except `RENDER_API_KEY`, plus `FRONTEND_URL` and `ALLOWED_ORIGINS` set to the web URL, `PUBLIC_API_URL` set to the API URL, and **`JOBS_ENABLED=false`**. Jobs stay off until the test audits are deleted, or they would alert and email about them.
  - Web: `NEXT_PUBLIC_API_URL` set to the API URL, plus the Turnstile site key and the Client Engine URL.
- **Smoke test:**
  - API health is OK: database connected, Turnstile and email configured, jobs off.
  - The question page renders.
  - A saved report renders through web → API → database, including "Why we flagged this".
  - CORS allows the web origin.
- **Blocker:** Turnstile error **110200** on `ops-audit-web.onrender.com`. The widget doesn't list that hostname yet, so the live form can't start a website read. Fix: Cloudflare → Turnstile → the widget → Hostname Management → add `ops-audit-web.onrender.com`.
- **Notes:**
  - Free instances sleep after 15 idle minutes, so the first visit takes about a minute. The jobs loop also sleeps with them, so production needs a paid instance or a cron.
  - The rate limits were deployed at 10/20 for testing; set 3/10 before sharing.
  - The Render key had been pasted as a second `RESEND_API_KEY` line, which broke email; it was renamed to `RENDER_API_KEY`.
