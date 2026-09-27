import type { Metadata } from "next";
import Link from "next/link";
import CalendlyEmbed from "@/components/CalendlyEmbed";
import { dollars, getReport } from "@/lib/api";

export const metadata: Metadata = {
  title: "Book your call: Ops Clarity Audit",
  robots: { index: false, follow: false },
};

type Props = { searchParams: Promise<{ audit?: string | string[] }> };

// PRD §9.3: the booking calendar with the founder's report rendered alongside.
export default async function BookPage({ searchParams }: Props) {
  const { audit } = await searchParams;
  const auditId = typeof audit === "string" ? audit : null;
  const report = auditId ? await getReport(auditId) : null;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-20 pt-8 sm:pt-12">
      <p className="text-sm font-semibold uppercase tracking-[0.14em] text-accent">Ops Clarity Audit</p>
      {/* Placeholder copy: Shiv owns the final wording */}
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Book your 30-minute call</h1>
      <p className="mt-3 max-w-2xl text-lg text-pretty text-muted">
        We&apos;ll walk through your report together: what we&apos;d fix first, and whether we&apos;re the right people
        to fix it.
      </p>

      <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        {report && (
          <aside className="h-fit rounded-2xl bg-ink p-6 text-white">
            <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-white/60">Your report</h2>
            <p className="mt-3 text-white/85">{report.display_name} is losing an estimated</p>
            <p className="text-3xl font-semibold tracking-tight tabular-nums text-loss">
              {dollars(report.total_low, report.total_high)}
            </p>
            <p className="text-white/85">a month.</p>
            <ol className="mt-5 grid gap-3">
              {report.leaks.map((leak) => (
                <li key={leak.leak_id} className="rounded-xl bg-white/10 px-4 py-3">
                  <p className="font-medium">
                    #{leak.rank} {leak.name}
                  </p>
                  <p className="text-sm tabular-nums text-white/70">
                    {dollars(leak.monthly_low, leak.monthly_high)} a month
                  </p>
                </li>
              ))}
            </ol>
            <Link
              href={`/audit/r/${encodeURIComponent(report.id)}`}
              className="mt-5 inline-block text-sm text-white/80 underline underline-offset-4 hover:text-white"
            >
              Back to the full report
            </Link>
          </aside>
        )}
        <CalendlyEmbed auditId={report ? report.id : null} />
      </div>
    </main>
  );
}
