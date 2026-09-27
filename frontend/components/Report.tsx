// The report page's sections, in PRD §7 order. Everything shown comes from the saved report JSON
// (backend/rules.py finalize()); fixed copy comes from lib/content.json (backend/library.py).

import type { ReactNode } from "react";
import content from "@/lib/content.json";
import { dollars, type Pillar, type Report as ReportData } from "@/lib/api";
import CopyLinkButton from "./CopyLinkButton";
import EmailReportForm from "./EmailReportForm";
import TrackedLink from "./TrackedLink";

const CLIENT_ENGINE_URL = process.env.NEXT_PUBLIC_CLIENT_ENGINE_URL ?? "https://theladder.ai/client-engine";
const PILLARS: { key: Pillar; label: string }[] = [
  { key: "credibility", label: "Credibility" },
  { key: "pipeline", label: "Pipeline" },
  { key: "conversion", label: "Conversion" },
  { key: "delivery", label: "Delivery" },
];
const pillarLabel = (key: Pillar) => PILLARS.find((p) => p.key === key)?.label ?? key;

export default function Report({ report }: { report: ReportData }) {
  const { copy } = content;
  const bookUrl = `/audit/book?audit=${encodeURIComponent(report.id)}`;
  const generated = new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(new Date(report.generated_at));
  const source =
    report.url_type === "none"
      ? ""
      : report.specificity_degraded
        ? ` (we couldn't read ${report.domain})`
        : ` and a read of ${report.domain}`;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-20 pt-8 sm:pt-12">
      {/* 7.1 Verdict banner: the total is the largest element on the page */}
      <section className="rounded-3xl bg-ink px-6 py-10 text-white sm:px-10 sm:py-14">
        <p className="text-sm font-semibold uppercase tracking-[0.14em] text-white/60">Ops Clarity Audit</p>
        <h1 className="mt-4">
          <span className="block text-xl font-medium text-white/85 sm:text-2xl">
            {report.display_name} is losing an estimated
          </span>
          <span className="mt-2 block text-[clamp(2.25rem,9vw,4.5rem)] font-semibold leading-none tracking-tight tabular-nums text-loss">
            {dollars(report.total_low, report.total_high)}
          </span>
          <span className="mt-3 block text-xl font-medium text-white/85 sm:text-2xl">a month.</span>
        </h1>
        <p className="mt-6 max-w-xl text-lg text-pretty text-white/80">{report.verdict_subline}</p>
        <p className="mt-6 inline-flex rounded-full border border-white/20 px-3 py-1 text-sm text-white/75">
          {report.gap_count} gaps · {report.band_label} a month{report.mrr_inferred ? " (assumed)" : ""}
        </p>
      </section>

      {/* 7.2 The read */}
      <Section label="The read">
        <p className="text-lg leading-relaxed text-pretty sm:text-xl">{report.the_read}</p>
      </Section>

      {/* 7.3 Scorecard: number and bar, so the score never relies on color alone */}
      <Section label="Scorecard">
        <ul className="grid gap-3 sm:grid-cols-2">
          {PILLARS.map(({ key, label }) => {
            const { score, rationale } = report.scores[key];
            const tone = score <= 4 ? "bad" : score <= 6 ? "warn" : "good";
            return (
              <li key={key} className="rounded-2xl border border-line bg-surface p-5">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="font-semibold">{label}</h3>
                  <p className={`text-2xl font-semibold tabular-nums ${TEXT_TONE[tone]}`}>
                    {score}
                    <span className="text-base font-normal text-muted">/10</span>
                  </p>
                </div>
                <div aria-hidden="true" className="mt-3 h-2 rounded-full bg-paper">
                  <div className={`h-2 rounded-full ${BG_TONE[tone]}`} style={{ width: `${score * 10}%` }} />
                </div>
                <p className="mt-3 text-sm text-muted">{rationale}</p>
              </li>
            );
          })}
        </ul>
      </Section>

      {/* 7.4 Top three leaks: card one carries visibly more weight */}
      <Section label="Your three biggest gaps">
        <ol className="grid gap-4">
          {report.leaks.map((leak) => {
            const first = leak.rank === 1;
            return (
              <li
                key={leak.leak_id}
                className={`rounded-2xl bg-surface ${first ? "border-2 border-ink p-6 sm:p-8" : "border border-line p-5 sm:p-6"}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
                  <div>
                    <p className="text-sm text-muted">
                      #{leak.rank} · {pillarLabel(leak.pillar)}
                    </p>
                    <h3 className={`mt-1 font-semibold tracking-tight ${first ? "text-2xl sm:text-3xl" : "text-xl"}`}>
                      {leak.name}
                    </h3>
                  </div>
                  <p className="sm:text-right">
                    <span className={`block font-semibold tabular-nums ${first ? "text-2xl text-bad" : "text-lg"}`}>
                      {dollars(leak.monthly_low, leak.monthly_high)}
                    </span>
                    <span className="text-sm text-muted">a month</span>
                  </p>
                </div>
                <p className="mt-4 leading-relaxed">{leak.description}</p>
                {leak.signals?.length ? (
                  <div className="mt-4 text-sm">
                    <p className="font-medium">Why we flagged this</p>
                    <ul className="mt-1 grid list-disc gap-1 pl-5 text-muted">
                      {leak.signals.map((signal) => (
                        <li key={signal}>{signal}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <p className="mt-4 rounded-xl bg-paper px-4 py-3 text-sm">
                  <span className="font-medium">Also costing you:</span> {leak.non_dollar_cost}
                </p>
              </li>
            );
          })}
        </ol>
      </Section>

      {/* 7.5 What we'd build */}
      <Section label="What we'd build">
        <div className="grid gap-4">
          {report.leaks.map((leak) => (
            <article key={leak.leak_id} className="rounded-2xl border border-line bg-surface p-5 sm:p-6">
              <h3 className="text-lg font-semibold">{leak.fix_name}</h3>
              <p className="text-sm text-muted">Fixes: {leak.name}</p>
              <dl className="mt-4 grid gap-3 sm:grid-cols-[10rem_1fr] sm:gap-x-6">
                <dt className="text-sm font-medium">What it does</dt>
                <dd className="text-muted">{leak.fix_what_it_does}</dd>
                <dt className="text-sm font-medium">What changes in your week</dt>
                <dd className="text-muted">{leak.fix_what_changes}</dd>
                <dt className="text-sm font-medium">Time to stand up</dt>
                <dd className="text-muted">{leak.fix_time_to_live}</dd>
              </dl>
            </article>
          ))}
        </div>
      </Section>

      {/* 7.6 Proof: one case study matched to the top leak; never an outbound link (Archaius rule 3) */}
      <Section label="Proof">
        <div className="rounded-2xl bg-accent-soft p-6 sm:p-8">
          <h3 className="text-2xl font-semibold tracking-tight">{report.proof.name}</h3>
          <ul className="mt-4 grid gap-3 sm:grid-cols-3">
            {report.proof.headline.map((item) => (
              <li key={item} className="rounded-xl bg-surface px-4 py-3 text-sm font-medium">
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-5 text-lg text-pretty">{report.proof.tie_in}</p>
        </div>
      </Section>

      {/* 7.7 How we calculated this: collapsed by default */}
      <details className="mt-12 rounded-2xl border border-line bg-surface p-5 sm:p-6">
        <summary className="cursor-pointer font-semibold">How we calculated this</summary>
        <div className="mt-3 grid gap-3 text-muted">
          {report.how_calculated.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </details>

      {/* 7.8 What this report can't see */}
      <Section label="What this report can't see">
        <ul className="grid list-disc gap-2 pl-5">
          {report.cant_see.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Section>

      {/* 7.9 Primary CTA, routed by the top leak's pillar (PRD §2.1) */}
      <section className="mt-12 rounded-3xl bg-ink px-6 py-10 text-white sm:px-10">
        <p className="text-xl leading-relaxed text-pretty sm:text-2xl">{report.cta_bridge}</p>
        <TrackedLink
          auditId={report.id}
          href={
            report.cta_route === "client_engine"
              ? `${CLIENT_ENGINE_URL}?audit=${encodeURIComponent(report.id)}`
              : bookUrl
          }
          className="mt-8 inline-flex min-h-12 items-center rounded-full bg-white px-7 font-semibold text-ink hover:bg-white/85"
        >
          {report.cta_route === "client_engine" ? copy.cta_client_engine_button : copy.cta_booking_button}
        </TrackedLink>
        {report.cta_route === "client_engine" && (
          <p className="mt-5">
            <TrackedLink
              auditId={report.id}
              href={bookUrl}
              className="text-white/80 underline underline-offset-4 hover:text-white"
            >
              {copy.cta_secondary}
            </TrackedLink>
          </p>
        )}
      </section>

      {/* 7.10 Save this report (7.11 newsletter is on hold) */}
      <Section label="Save this report">
        <p className="text-muted">This link is permanent. Bookmark it or share it with your team.</p>
        <CopyLinkButton />
        <EmailReportForm auditId={report.id} />
      </Section>

      {/* 7.12 Metadata footer */}
      <footer className="mt-16 border-t border-line pt-6 text-sm text-muted">
        <p>
          Generated {generated}. Based on your five answers{source}.
        </p>
        <p className="mt-1">
          Report ID: <span className="font-mono">{report.id}</span>
        </p>
      </footer>
    </main>
  );
}

const TEXT_TONE = { good: "text-good", warn: "text-warn", bad: "text-bad" };
const BG_TONE = { good: "bg-good", warn: "bg-warn", bad: "bg-bad" };

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="mt-12">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.14em] text-muted">{label}</h2>
      {children}
    </section>
  );
}
