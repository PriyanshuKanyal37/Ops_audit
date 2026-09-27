// Calls to the FastAPI backend, and the shape of a finished report (built by backend/rules.py finalize()).

// Local dev runs on 8100/3100 because 8000/3000 are taken by LadderFlow on this machine.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

export type Pillar = "credibility" | "pipeline" | "conversion" | "delivery";

export type Answers = { q1: string; q2: string[]; q3: string[]; q4: string; q5: string };

export type Leak = {
  rank: number;
  leak_id: string;
  name: string;
  pillar: Pillar;
  weight: "light" | "medium" | "heavy";
  description: string;
  monthly_low: number;
  monthly_high: number;
  non_dollar_cost: string;
  signals?: string[]; // the evidence behind the gap; reports made before 26 Sept don't have it
  fix_name: string;
  fix_what_it_does: string;
  fix_what_changes: string;
  fix_time_to_live: string;
};

export type Report = {
  id: string;
  generated_at: string;
  display_name: string;
  verdict_subline: string;
  domain: string | null;
  url_type: "full" | "social" | "none";
  band_label: string;
  mrr_inferred: boolean;
  total_low: number;
  total_high: number;
  gap_count: number;
  the_read: string;
  scores: Record<Pillar, { score: number; rationale: string }>;
  leaks: Leak[];
  top_leak_pillar: Pillar;
  cta_route: "client_engine" | "booking";
  cta_bridge: string;
  proof: { key: string; name: string; headline: string[]; tie_in: string };
  how_calculated: string[];
  cant_see: string[];
  specificity_degraded: boolean;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.";
    throw new ApiError(response.status, message);
  }
  return data as T;
}

/** URL screen: pass the human check, normalise the site, start reading it, get a session token. */
export const startScrape = (url: string | null, turnstileToken: string | null) =>
  post<{ session: string; url_type: string }>("/api/scrape", {
    ...(url ? { url } : { no_website: true }),
    turnstile_token: turnstileToken,
  });

/** After Q5: generate and save the report. Takes 20–45 seconds. */
export const runAudit = (session: string, answers: Answers) =>
  post<{ id: string }>("/api/audit", { session, answers });

/** "Email this to me" (PRD §7.10). Not newsletter consent. */
export const emailReport = (id: string, email: string) => post<{ sent: boolean }>("/api/email-report", { id, email });

/** Fire-and-forget POST. sendBeacon survives the page navigating away; text/plain avoids a CORS preflight. */
function beacon(path: string, data: object) {
  const body = JSON.stringify(data);
  const url = `${API_URL}${path}`;
  if (navigator.sendBeacon?.(url, new Blob([body], { type: "text/plain" }))) return;
  void fetch(url, { method: "POST", body, keepalive: true, headers: { "Content-Type": "text/plain" } }).catch(() => {});
}

/** Record a click or booking on a report. */
export function track(id: string, event: "cta_click" | "ce_visit" | "booked") {
  beacon("/api/track", { id, event });
}

export type FunnelStep =
  | "landing_view"
  | "q1_answered"
  | "url_given"
  | "q2_answered"
  | "q3_answered"
  | "q4_reached"
  | "q4_answered"
  | "q5_answered"
  | "submitted" // pressed "See my report" (reached the email screen)
  | "email_given";

// A random id per browser, so each funnel step counts once per visitor. Not personal data; if storage is
// blocked (private mode), it lasts for this page only.
let visitorId = "";
const sentSteps = new Set<FunnelStep>();

function visitor() {
  if (visitorId) return visitorId;
  try {
    visitorId = localStorage.getItem("audit_visitor") ?? "";
  } catch {}
  if (!visitorId) {
    visitorId = crypto.randomUUID?.() ?? `v-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try {
      localStorage.setItem("audit_visitor", visitorId);
    } catch {}
  }
  return visitorId;
}

/** One funnel step (PRD §12.1), sent once per page load; the server also ignores repeats per visitor. */
export function funnel(step: FunnelStep) {
  if (sentSteps.has(step)) return;
  sentSteps.add(step);
  beacon("/api/funnel", { visitor: visitor(), event: step });
}

/** Server-side: load a saved report, or null if the id doesn't exist. */
export async function getReport(id: string): Promise<Report | null> {
  const response = await fetch(`${API_URL}/api/report/${encodeURIComponent(id)}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Report API returned ${response.status}`);
  return response.json();
}

export const dollars = (low: number, high: number) =>
  `$${low.toLocaleString("en-US")}–${high.toLocaleString("en-US")}`;
