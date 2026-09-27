"use client";

// The audit form (mock frontend): every question on ONE scrolling page, then the generating screen, then the
// report. PRD §4's step-by-step flow was swapped for a single page at the user's request (26 Sept).
// The PRD behaviour that matters is kept: the website read starts as soon as the website is entered, and runs
// in the background while the founder answers the rest. Question text comes from lib/content.json.

import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { useRouter } from "next/navigation";
import content from "@/lib/content.json";
import { ApiError, funnel, runAudit, startScrape, type Answers, type FunnelStep } from "@/lib/api";
import Turnstile, { turnstileEnabled } from "./Turnstile";

type Screen = (typeof content.screens)[number];
const screens: Screen[] = content.screens;
const numberedKeys = screens.filter((s) => s.key !== "url").map((s) => s.key);
const NETWORK_ERROR = "We couldn't reach the server. Check your connection and try again.";

const domainOf = (text: string) =>
  text.trim().replace(/^https?:\/\//i, "").replace(/^www\./i, "").split(/[/?#]/)[0].toLowerCase();

export default function AuditFlow({ intro }: { intro: ReactNode }) {
  const router = useRouter();
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({ q2: [], q3: [] });
  const [website, setWebsite] = useState("");
  const [noWebsite, setNoWebsite] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState("");
  const [attempt, setAttempt] = useState(0); // remounts the generating screen on "Try again"
  const [busy, setBusy] = useState(false);
  const [site, setSite] = useState<string | null>(null);
  const [turnstileReset, setTurnstileReset] = useState(0);
  const session = useRef<{ token: string; forUrl: string } | null>(null); // forUrl "" = no website
  const pending = useRef<{ forUrl: string; promise: Promise<boolean> } | null>(null);
  const humanToken = useRef<string | null>(null); // Turnstile token, single-use
  const headingRef = useRef<HTMLHeadingElement>(null);
  const q4Ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (generating) headingRef.current?.focus();
  }, [generating, attempt]);

  // Funnel (PRD §12.1): the landing view, and "reached Q4" once half the revenue question is on screen.
  // On this single page, "reached" means scrolled to; in a one-question-per-screen flow it'd be the screen showing.
  useEffect(() => {
    funnel("landing_view");
    const q4 = q4Ref.current;
    if (!q4) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          funnel("q4_reached");
          observer.disconnect();
        }
      },
      { threshold: 0.5 },
    );
    observer.observe(q4);
    return () => observer.disconnect();
  }, []);

  const setFieldError = (key: string, message: string) => setErrors((e) => ({ ...e, [key]: message }));
  const clearFieldError = (key: string) =>
    setErrors((e) => {
      const next = { ...e };
      delete next[key];
      return next;
    });

  /** Get a session for the current website (starting the background read). Deduplicates parallel calls. */
  function ensureSession(): Promise<boolean> {
    const target = noWebsite ? "" : website.trim();
    if (session.current?.forUrl === target) return Promise.resolve(true);
    if (pending.current?.forUrl === target) return pending.current.promise;
    const promise: Promise<boolean> = createSession(target).finally(() => {
      if (pending.current?.promise === promise) pending.current = null;
    });
    pending.current = { forUrl: target, promise };
    return promise;
  }

  async function createSession(target: string): Promise<boolean> {
    // The human check takes ~3–5s after page load (measured), usually done before they reach this field;
    // otherwise wait up to 10 seconds for it.
    for (let i = 0; turnstileEnabled && !humanToken.current && i < 100; i++) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (turnstileEnabled && !humanToken.current) {
      setFieldError("url", "We couldn't run the quick human check. If you use an ad or script blocker, allow this page and try again.");
      return false;
    }
    const token = humanToken.current;
    humanToken.current = null; // tokens are single-use: fetch a fresh one for the next attempt
    setTurnstileReset((n) => n + 1);
    try {
      const result = await startScrape(target || null, token);
      session.current = { token: result.session, forUrl: target };
      setSite(target ? domainOf(target) : null);
      clearFieldError("url");
      funnel("url_given"); // a website the server accepted, or "I don't have a website yet"
      return true;
    } catch (e) {
      session.current = null;
      setFieldError("url", e instanceof ApiError ? e.message : NETWORK_ERROR);
      return false;
    }
  }

  function validate() {
    const found: Record<string, string> = {};
    for (const screen of screens) {
      if (screen.key === "url") {
        if (!noWebsite && !website.trim()) found.url = "Enter your website, or tick “I don't have a website yet”.";
        continue;
      }
      const value = answers[screen.key];
      if (screen.multi ? !(value as string[]).length : !value) {
        found[screen.key] = screen.multi ? "Pick at least one option." : "Pick one option.";
      }
    }
    return found;
  }

  function focusField(key: string) {
    const target = document.querySelector<HTMLElement>(key === "url" ? "#website" : `input[name="${key}"]`);
    target?.focus();
    target?.scrollIntoView({ block: "center" });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const found = validate();
    setErrors(found);
    const first = screens.find((s) => found[s.key]);
    if (first) return focusField(first.key);
    funnel("submitted");
    setBusy(true);
    const ready = await ensureSession();
    setBusy(false);
    if (!ready) return focusField("url");
    await generate();
  }

  async function generate() {
    setGenerationError("");
    setAttempt((n) => n + 1);
    setGenerating(true);
    window.scrollTo({ top: 0 });
    try {
      const { id } = await runAudit(session.current?.token ?? "", answers as Answers);
      router.push(`/audit/r/${id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        session.current = null; // expired: back to the form with the website field flagged
        setGenerating(false);
        setFieldError("url", e.message);
        setTimeout(() => focusField("url"), 0);
        return;
      }
      setGenerationError(e instanceof ApiError ? e.message : NETWORK_ERROR);
    }
  }

  if (generating) {
    const band =
      answers.q4 === "rather_not_say"
        ? content.rather_not_say_band
        : (screens.find((s) => s.key === "q4")?.options?.find((o) => o.value === answers.q4)?.label ?? "");
    return (
      <Generating
        key={attempt}
        headingRef={headingRef}
        site={site}
        band={band}
        error={generationError}
        onRetry={() => void generate()}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-20 pt-8 sm:pt-12">
      {intro}
      <form noValidate onSubmit={submit} className="grid gap-12">
        {screens.map((screen) =>
          screen.key === "url" ? (
            <section key="url" aria-labelledby="url-title" className="border-t border-line pt-10">
              <p className="text-sm font-medium text-muted">Your website</p>
              {/* Single-page mock: the PRD's "One quick thing before we continue" line suits the step-by-step flow */}
              <h2 id="url-title" className="mt-1 text-2xl font-semibold tracking-tight text-balance">
                What&apos;s your website?
              </h2>
              <p className="mt-2 text-lg text-muted">We&apos;ll read your public positioning while you answer the rest.</p>
              <label htmlFor="website" className="mt-6 block text-sm font-medium">
                Website address
              </label>
              <input
                id="website"
                name="website"
                type="text"
                inputMode="url"
                autoComplete="url"
                placeholder="yourcompany.com"
                value={website}
                disabled={noWebsite}
                onChange={(e) => {
                  setWebsite(e.target.value);
                  clearFieldError("url");
                }}
                onBlur={() => {
                  if (website.trim()) void ensureSession(); // start reading their site straight away
                }}
                aria-describedby={errors.url ? "url-error" : undefined}
                aria-invalid={errors.url ? true : undefined}
                className="mt-2 min-h-12 w-full rounded-xl border border-line bg-surface px-4 text-base disabled:opacity-50"
              />
              <label className="mt-4 flex min-h-12 cursor-pointer items-center gap-3 text-base">
                <input
                  type="checkbox"
                  checked={noWebsite}
                  onChange={(e) => {
                    setNoWebsite(e.target.checked);
                    clearFieldError("url");
                  }}
                  className="size-4"
                />
                I don&apos;t have a website yet
              </label>
              {turnstileEnabled && (
                <Turnstile onToken={(token) => (humanToken.current = token)} resetKey={turnstileReset} />
              )}
              <FieldError id="url-error" text={errors.url} />
            </section>
          ) : (
            <div key={screen.key} ref={screen.key === "q4" ? q4Ref : undefined} className="border-t border-line pt-10">
              <fieldset aria-describedby={errors[screen.key] ? `${screen.key}-error` : undefined}>
                <legend className="w-full">
                  <span className="block text-sm font-medium text-muted">
                    Question {numberedKeys.indexOf(screen.key) + 1} of 5
                  </span>
                  <span className="mt-1 block text-2xl font-semibold tracking-tight text-balance">{screen.title}</span>
                </legend>
                {screen.sub && <p className="mt-2 text-lg text-muted">{screen.sub}</p>}
                <div className="mt-6 grid gap-3">
                  {screen.options?.map((option) => {
                    const multi = screen.multi ?? false;
                    const current = answers[screen.key];
                    const selected = multi ? (current as string[]).includes(option.value) : current === option.value;
                    return (
                      <label
                        key={option.value}
                        className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-base transition-colors hover:border-ink/40 has-checked:border-accent has-checked:bg-accent-soft"
                      >
                        <input
                          type={multi ? "checkbox" : "radio"}
                          name={screen.key}
                          value={option.value}
                          checked={selected}
                          onChange={() => {
                            setAnswers((a) => ({
                              ...a,
                              [screen.key]: multi ? toggle(a[screen.key] as string[], option.value) : option.value,
                            }));
                            clearFieldError(screen.key);
                            funnel(`${screen.key}_answered` as FunnelStep);
                          }}
                          className="size-4 shrink-0"
                        />
                        <span>{option.label}</span>
                      </label>
                    );
                  })}
                </div>
                <FieldError id={`${screen.key}-error`} text={errors[screen.key]} />
              </fieldset>
            </div>
          ),
        )}
        <div className="border-t border-line pt-10">
          <button
            type="submit"
            disabled={busy}
            className="min-h-12 rounded-full bg-ink px-8 text-lg font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-60"
          >
            {busy ? "Checking…" : "See my report"}
          </button>
          {Object.keys(errors).length > 0 && (
            <p className="mt-3 text-sm font-medium text-bad">Please answer the questions marked above.</p>
          )}
        </div>
      </form>
    </div>
  );
}

function toggle(list: string[], value: string) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function FieldError({ id, text }: { id: string; text?: string }) {
  return (
    <p id={id} className="mt-3 min-h-5 text-sm font-medium text-bad">
      {text}
    </p>
  );
}

// PRD §4 generating screen: status lines that reference their real inputs, then honest "still working" lines,
// because a report takes 20–45 seconds, not the PRD's 6–8.
const LINE_DELAYS_MS = [1600, 3200, 4800, 6400, 11000, 20000, 32000]; // when lines 2–8 appear

function Generating({
  headingRef,
  site,
  band,
  error,
  onRetry,
}: {
  headingRef: RefObject<HTMLHeadingElement | null>;
  site: string | null;
  band: string;
  error: string;
  onRetry: () => void;
}) {
  const lines = [
    site ? `Reading ${site}…` : "Reviewing your answers…",
    "Checking positioning, proof, and case studies…",
    "Matching against 12 revenue leak patterns…",
    `Sizing impact against ${band} MRR…`,
    "Ranking by monthly cost…",
    "Writing your report…",
    "Checking every figure against your revenue band…",
    "Almost there. Reports usually take 20–45 seconds.",
  ];
  const [shown, setShown] = useState(1);

  useEffect(() => {
    const timers = LINE_DELAYS_MS.map((delay, i) => setTimeout(() => setShown(i + 2), delay));
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-20 pt-16">
      <h2 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight sm:text-3xl">
        {error ? "We hit a problem" : "Building your report"}
      </h2>
      {error ? (
        <div className="mt-6">
          <p role="alert" className="text-base font-medium text-bad">
            {error}
          </p>
          <p className="mt-2 text-muted">Your answers are still here, so nothing needs re-entering.</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-6 min-h-12 rounded-full bg-ink px-7 font-medium text-white hover:opacity-85"
          >
            Try again
          </button>
        </div>
      ) : (
        <ol aria-live="polite" className="mt-8 grid gap-3 text-lg">
          {lines.slice(0, shown).map((line, i) => {
            const done = i < shown - 1;
            return (
              <li key={line} className={`flex items-center gap-3 ${done ? "text-muted" : "text-ink"}`}>
                <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center">
                  {done ? (
                    <span className="text-accent">✓</span>
                  ) : (
                    <span className="size-2.5 animate-pulse rounded-full bg-accent" />
                  )}
                </span>
                {line}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
