import AuditFlow from "@/components/AuditFlow";

// Landing page with the questions embedded (PRD §9.3). Mock frontend: all questions on one scrolling page.
export default function AuditPage() {
  return (
    <main className="flex-1">
      <AuditFlow intro={<Intro />} />
    </main>
  );
}

// Placeholder landing copy: Shiv owns the final wording (PRD §4 fixes only the Q1 text).
function Intro() {
  return (
    <header className="mb-2">
      <p className="text-sm font-semibold uppercase tracking-[0.14em] text-accent">Ops Clarity Audit</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        Find the three places your business is losing money every month.
      </h1>
      <p className="mt-4 text-lg text-pretty text-muted">
        Answer five questions and share your website. In about three minutes you get a report that names your three
        biggest gaps, sizes each one in dollars against your revenue, and names the fix.
      </p>
      <p className="mt-4 text-sm text-muted">Free · No email needed · The full report is yours</p>
    </header>
  );
}
