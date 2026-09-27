-- Ops Clarity Audit v2: database schema (Neon Postgres).
-- Safe to re-run: every statement uses IF NOT EXISTS.
-- Run once:  psql "$DATABASE_URL" -f schema.sql

-- One row per completed audit (PRD §9.5, adapted from Airtable to Postgres).
create table if not exists audits (
  id                    text primary key,                      -- random, unguessable; used in /audit/r/{id}
  submitted_at          timestamptz not null default now(),
  ip_hash               text not null,                         -- sha256(ip + salt); the raw IP is never stored

  -- Answers
  website_url           text,
  url_type              text not null check (url_type in ('full', 'social', 'none')),
  q1                    text not null check (q1 in ('A', 'B', 'C', 'D', 'E')),
  q2                    text[] not null,                       -- option keys, validated by the app
  q3                    text[] not null,
  mrr_band              text not null check (mrr_band in
                          ('under_50k', '50k_100k', '100k_200k', '200k_350k', '350k_500k', '500k_plus')),
  mrr_inferred          boolean not null default false,        -- true when they picked "I'd rather not say"
  q5                    text not null,

  -- Results (flattened copies of fields inside `report`, kept for querying)
  score_credibility     smallint check (score_credibility between 1 and 10),
  score_pipeline        smallint check (score_pipeline between 1 and 10),
  score_conversion      smallint check (score_conversion between 1 and 10),
  score_delivery        smallint check (score_delivery between 1 and 10),
  leak_1_id             text,
  leak_2_id             text,
  leak_3_id             text,
  top_leak_pillar       text check (top_leak_pillar in ('credibility', 'pipeline', 'conversion', 'delivery')),
  total_leakage_low     integer,
  total_leakage_high    integer,
  cta_route             text check (cta_route in ('client_engine', 'booking')),
  report                jsonb not null,                        -- the full report; powers the report page
  specificity_degraded  boolean not null default false,        -- the website read failed
  cost_usd              numeric(8, 4) not null default 0,      -- Claude cost; feeds the daily spend cap

  -- Contact and consent
  report_email          text,                                  -- from "email this to me"; NOT newsletter consent
  report_emails_sent    smallint not null default 0,           -- capped at 3 per report
  newsletter_opted_in   boolean not null default false,        -- kept for later; no UI yet

  -- Tracking and follow-up
  clicked_cta           boolean not null default false,
  visited_ce_page       boolean not null default false,
  call_booked           boolean not null default false,
  followup_email_sent   boolean not null default false,
  slack_alert_sent      boolean not null default false,
  top_leak_was_correct  text check (top_leak_was_correct in ('yes', 'no', 'partly'))
);

-- The rate limit counts audits per IP in the last hour/day on every request.
-- ponytail: the jobs and spend-cap queries scan by submitted_at without an index; fine for thousands of rows,
-- add an index on submitted_at if the table grows past ~100k.
create index if not exists audits_ip_hash_submitted_at on audits (ip_hash, submitted_at);

-- One row per website domain; rows older than 30 days are re-read.
create table if not exists scrape_cache (
  domain            text primary key,                          -- e.g. acme.com
  context           text,                                      -- the ~700-word trimmed text sent to Claude
  has_case_studies  boolean not null default false,
  has_testimonials  boolean not null default false,
  has_blog          boolean not null default false,
  word_count        integer not null default 0,
  fetched_at        timestamptz not null default now()
);

-- Funnel steps before a report exists (PRD §12.1): landing, Q1, website, Q4 reached/answered, submit.
-- Steps after it (button click, Client Engine visit, booking) are the flags on `audits`.
-- One row per browser per step, so reloads and double clicks count once. No personal data.
create table if not exists funnel_events (
  visitor_id  text not null,                                   -- random id kept in the browser's localStorage
  event       text not null,
  created_at  timestamptz not null default now(),
  primary key (visitor_id, event)
);
create index if not exists funnel_events_created_at on funnel_events (created_at);
