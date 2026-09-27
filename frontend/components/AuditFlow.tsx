"use client";

// The audit flow (PRD §4): one screen at a time, Q1 → website → Q2 → Q3 → Q4 → Q5 → email → report.
// Single-choice questions move on as soon as one is picked; multi-choice ones have a Next button; every screen
// after the first has Back, and answers are kept. Work happens in the background: the website read starts when
// they leave the website screen, and the report starts generating the moment they press "See my report", so it's
// being written (~30s) while they type their email. The email is required and gets a copy of the report link
// (user's call, 27 Sept; PRD §1 said "no email gate", so this needs Shiv's OK). Copy comes from lib/content.json.

import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { useRouter } from "next/navigation";
import content from "@/lib/content.json";
import { ApiError, emailReport, funnel, runAudit, startScrape, type Answers, type FunnelStep } from "@/lib/api";
import Turnstile, { turnstileEnabled } from "./Turnstile";

type Screen = (typeof content.screens)[number];
const screens: Screen[] = content.screens;
const numberedKeys = screens.filter((s) => s.key !== "url").map((s) => s.key);
const URL_STEP = screens.findIndex((s) => s.key === "url");
const Q4_STEP = screens.findIndex((s) => s.key === "q4");
const NETWORK_ERROR = "We couldn't reach the server. Check your connection and try again.";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/; // the same check the server makes

const domainOf = (text: string) =>
  text.trim().replace(/^https?:\/\//i, "").replace(/^www\./i, "").split(/[/?#]/)[0].toLowerCase();

type Run = { startedAt: number; promise: Promise<string> }; // resolves to the new report's id

export default function AuditFlow({ intro }: { intro: ReactNode }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [phase, setPhase] = useState<"questions" | "email" | "waiting">("questions");
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({ q2: [], q3: [] });
  const [website, setWebsite] = useState("");
  const [noWebsite, setNoWebsite] = useState(false);
  const [email, setEmail] = useState("");
  const [error, setError] = useState(""); // the message for the screen on show
  const [busy, setBusy] = useState(false);
  const [site, setSite] = useState<string | null>(null);
  const [reportState, setReportState] = useState<"running" | "ready" | "failed">("running");
  const [generationError, setGenerationError] = useState("");
  const [attempt, setAttempt] = useState(0); // remounts the generating screen on "Try again"
  const [turnstileReset, setTurnstileReset] = useState(0);
  const session = useRef<{ token: string; forUrl: string } | null>(null); // forUrl "" = no website
  const pending = useRef<{ forUrl: string; promise: Promise<boolean> } | null>(null);
  const humanToken = useRef<string | null>(null); // Turnstile token, single-use
  const run = useRef<Run | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  const screen = screens[step];

  useEffect(() => {
    funnel("landing_view");
  }, []);

  // Each new screen: move focus to it (screen readers announce the question) and record the Q4 funnel step.
  // The landing screen keeps the page's natural focus.
  useEffect(() => {
    if (phase === "email") emailRef.current?.focus();
    else if (phase === "waiting" || step > 0) headingRef.current?.focus();
    if (phase === "questions" && step === Q4_STEP) funnel("q4_reached");
  }, [step, phase, attempt]);

  function goTo(next: number) {
    setError("");
    setStep(next);
  }

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
    // The human check takes ~3–5s after page load (measured), usually done while they answer Q1;
    // otherwise wait up to 10 seconds for it.
    for (let i = 0; turnstileEnabled && !humanToken.current && i < 100; i++) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (turnstileEnabled && !humanToken.current) {
      setError("We couldn't run the quick human check. If you use an ad or script blocker, allow this page and try again.");
      return false;
    }
    const token = humanToken.current;
    humanToken.current = null; // tokens are single-use: fetch a fresh one for the next attempt
    setTurnstileReset((n) => n + 1);
    try {
      const result = await startScrape(target || null, token);
      session.current = { token: result.session, forUrl: target };
      setSite(target ? domainOf(target) : null);
      funnel("url_given"); // a website the server accepted, or "I don't have a website yet"
      return true;
    } catch (e) {
      session.current = null;
      setError(e instanceof ApiError ? e.message : NETWORK_ERROR);
      return false;
    }
  }

  function pickOne(key: string, value: string) {
    setAnswers((a) => ({ ...a, [key]: value }));
    setError("");
    funnel(`${key}_answered` as FunnelStep);
    if (key === "q5") return; // the last question has "See my report" instead
    const at = step;
    window.setTimeout(() => setStep((s) => (s === at ? s + 1 : s)), 220); // a beat to see the pick; no double skips
  }

  function toggleMany(key: string, value: string) {
    setAnswers((a) => {
      const list = a[key] as string[];
      return { ...a, [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] };
    });
    setError("");
    funnel(`${key}_answered` as FunnelStep);
  }

  function nextFromMany() {
    if (!(answers[screen.key] as string[]).length) return setError("Pick at least one option.");
    goTo(step + 1);
  }

  async function continueFromWebsite(e: FormEvent) {
    e.preventDefault();
    if (!noWebsite && !website.trim()) return setError("Enter your website, or tick “I don't have a website yet”.");
    setBusy(true);
    const ok = await ensureSession();
    setBusy(false);
    if (ok) goTo(step + 1);
  }

  async function seeMyReport() {
    if (!answers.q5) return setError("Pick one option.");
    funnel("submitted");
    setBusy(true);
    const ok = await ensureSession(); // already done on the website screen, unless it expired
    setBusy(false);
    if (!ok) return setStep(URL_STEP);
    startReport();
    setError("");
    setPhase("email");
  }

  /** Start generating the report now; the email screen and the waiting screen pick up the same run. */
  function startReport() {
    const current: Run = {
      startedAt: Date.now(),
      promise: runAudit(session.current?.token ?? "", answers as Answers).then((r) => r.id),
    };
    run.current = current;
    setReportState("running");
    current.promise.then(
      () => run.current === current && setReportState("ready"),
      () => run.current === current && setReportState("failed"),
    );
  }

  async function submitEmail(e: FormEvent) {
    e.preventDefault();
    if (!EMAIL_RE.test(email.trim())) return setError("Enter your email address so we can send you a copy.");
    funnel("email_given");
    setError("");
    setPhase("waiting");
    await finish();
  }

  async function finish() {
    setGenerationError("");
    try {
      const id = await run.current!.promise;
      // Saves their address and sends the report link. A failed send must never hide the report: they can
      // still use "Email me this report" on the report page.
      await emailReport(id, email.trim()).catch(() => {});
      router.push(`/audit/r/${id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        session.current = null; // expired (30 min): back to the website screen, answers and email kept
        setPhase("questions");
        setStep(URL_STEP);
        setError(e.message);
        return;
      }
      setGenerationError(e instanceof ApiError ? e.message : NETWORK_ERROR);
    }
  }

  function retry() {
    startReport();
    setAttempt((n) => n + 1);
    void finish();
  }

  if (phase === "waiting") {
    const band =
      answers.q4 === "rather_not_say"
        ? content.rather_not_say_band
        : (screens.find((s) => s.key === "q4")?.options?.find((o) => o.value === answers.q4)?.label ?? "");
    return (
      <Generating
        key={attempt}
        startedAt={run.current?.startedAt ?? Date.now()}
        headingRef={headingRef}
        site={site}
        band={band}
        error={generationError}
        onRetry={retry}
      />
    );
  }

  const label =
    phase === "email" ? "Last step" : screen.key === "url" ? "Your website" : `Question ${numberedKeys.indexOf(screen.key) + 1} of 5`;
  const position = phase === "email" ? screens.length : step; // 0…6 of 7 screens
  const back =
    phase === "questions" && step > 0 ? (
      <button type="button" onClick={() => goTo(step - 1)} className="min-h-12 px-1 font-medium text-muted hover:text-ink">
        ← Back
      </button>
    ) : (
      <span />
    );

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-20 pt-8 sm:pt-12">
      {phase === "questions" && step === 0 && intro}
      <div className="mt-8">
        <p className="text-sm font-medium text-muted">{label}</p>
        <div aria-hidden="true" className="mt-2 h-1.5 rounded-full bg-line">
          <div
            className="h-1.5 rounded-full bg-accent transition-[width] duration-300"
            style={{ width: `${((position + 1) / (screens.length + 1)) * 100}%` }}
          />
        </div>
      </div>

      {phase === "email" ? (
        <form noValidate onSubmit={submitEmail} className="mt-8">
          <h2 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight text-balance outline-none sm:text-3xl">
            Where should we send your report?
          </h2>
          <p className="mt-2 text-lg text-muted">
            Your report opens here straight away, and we email you a copy of the link. This isn&apos;t a newsletter
            sign-up.
          </p>
          <p aria-live="polite" className="mt-6 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-sm">
            {reportState === "ready" ? (
              <>
                <span className="text-accent">✓</span> Your report is ready
              </>
            ) : (
              <>
                <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-accent" />
                {site ? `Building your report for ${site}…` : "Building your report…"}
              </>
            )}
          </p>
          <label htmlFor="email" className="mt-6 block text-sm font-medium">
            Your email
          </label>
          <input
            ref={emailRef}
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            enterKeyHint="go"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError("");
            }}
            aria-describedby="step-error"
            aria-invalid={error ? true : undefined}
            className="mt-2 min-h-12 w-full rounded-xl border border-line bg-surface px-4 text-base"
          />
          <StepError text={error} />
          <div className="mt-6 flex justify-end">
            <PrimaryButton type="submit">Show my report</PrimaryButton>
          </div>
        </form>
      ) : screen.key === "url" ? (
        <form noValidate onSubmit={continueFromWebsite} className="mt-8">
          <h2 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight text-balance outline-none sm:text-3xl">
            {screen.title}
          </h2>
          <p className="mt-2 text-lg text-muted">{screen.sub}</p>
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
              setError("");
            }}
            aria-describedby="step-error"
            aria-invalid={error ? true : undefined}
            className="mt-2 min-h-12 w-full rounded-xl border border-line bg-surface px-4 text-base disabled:opacity-50"
          />
          <label className="mt-4 flex min-h-12 cursor-pointer items-center gap-3 text-base">
            <input
              type="checkbox"
              checked={noWebsite}
              onChange={(e) => {
                setNoWebsite(e.target.checked);
                setError("");
              }}
              className="size-4"
            />
            I don&apos;t have a website yet
          </label>
          <StepError text={error} />
          <div className="mt-6 flex items-center justify-between gap-4">
            {back}
            <PrimaryButton type="submit" disabled={busy}>
              {busy ? "Checking…" : "Continue"}
            </PrimaryButton>
          </div>
        </form>
      ) : (
        <div className="mt-8">
          <h2 id="step-title" ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight text-balance outline-none sm:text-3xl">
            {screen.title}
          </h2>
          {screen.sub && <p className="mt-2 text-lg text-muted">{screen.sub}</p>}
          <div role="group" aria-labelledby="step-title" aria-describedby="step-error" className="mt-6 grid gap-3">
            {screen.options?.map((option) => {
              const current = answers[screen.key];
              if (screen.multi) {
                return (
                  <label
                    key={option.value}
                    className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-base transition-colors hover:border-ink/40 has-checked:border-accent has-checked:bg-accent-soft"
                  >
                    <input
                      type="checkbox"
                      name={screen.key}
                      value={option.value}
                      checked={(current as string[]).includes(option.value)}
                      onChange={() => toggleMany(screen.key, option.value)}
                      className="size-4 shrink-0"
                    />
                    <span>{option.label}</span>
                  </label>
                );
              }
              // Single choice: buttons, not radios, so arrow keys can't jump to the next screen by accident.
              return (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={current === option.value}
                  onClick={() => pickOne(screen.key, option.value)}
                  className="flex min-h-12 items-center rounded-xl border border-line bg-surface px-4 py-3 text-left text-base transition-colors hover:border-ink/40 aria-pressed:border-accent aria-pressed:bg-accent-soft"
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          <StepError text={error} />
          <div className="mt-6 flex items-center justify-between gap-4">
            {back}
            {screen.key === "q5" ? (
              <PrimaryButton onClick={() => void seeMyReport()} disabled={busy}>
                {busy ? "Checking…" : "See my report"}
              </PrimaryButton>
            ) : screen.multi || answers[screen.key] ? (
              <PrimaryButton onClick={screen.multi ? nextFromMany : () => goTo(step + 1)}>Next</PrimaryButton>
            ) : (
              <span className="text-sm text-muted">Pick one to continue</span>
            )}
          </div>
        </div>
      )}

      {/* Fetched from the first screen so a token is ready by the website screen; invisible unless Cloudflare
          needs a click. Unmounted once the questions are done. */}
      {phase === "questions" && turnstileEnabled && (
        <Turnstile onToken={(token) => (humanToken.current = token)} resetKey={turnstileReset} />
      )}
    </div>
  );
}

function PrimaryButton({
  children,
  type = "button",
  disabled,
  onClick,
}: {
  children: ReactNode;
  type?: "button" | "submit";
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className="min-h-12 rounded-full bg-ink px-8 text-lg font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-60"
    >
      {children}
    </button>
  );
}

function StepError({ text }: { text?: string }) {
  return (
    <p id="step-error" aria-live="polite" className="mt-3 min-h-5 text-sm font-medium text-bad">
      {text}
    </p>
  );
}

// PRD §4 generating screen: status lines that reference their real inputs, then honest "still working" lines,
// because a report takes 20–45 seconds, not the PRD's 6–8. Lines are timed from when generation STARTED (the
// "See my report" press), so time spent typing the email isn't shown twice.
const LINE_DELAYS_MS = [1600, 3200, 4800, 6400, 11000, 20000, 32000]; // when lines 2–8 appear

function Generating({
  startedAt,
  headingRef,
  site,
  band,
  error,
  onRetry,
}: {
  startedAt: number;
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
  const [shown, setShown] = useState(() => 1 + LINE_DELAYS_MS.filter((d) => d <= Date.now() - startedAt).length);

  useEffect(() => {
    const elapsed = Date.now() - startedAt;
    const timers = LINE_DELAYS_MS.map((delay, i) =>
      delay > elapsed ? setTimeout(() => setShown(i + 2), delay - elapsed) : undefined,
    );
    return () => timers.forEach((t) => t && clearTimeout(t));
  }, [startedAt]);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-20 pt-16">
      <h2 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold tracking-tight outline-none sm:text-3xl">
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
