import Link from "next/link";

export default function ReportNotFound() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-24">
      <h1 className="text-3xl font-semibold tracking-tight">We couldn&apos;t find that report</h1>
      <p className="mt-3 text-lg text-muted">Check the link you were sent, or take the audit again. It takes about three minutes.</p>
      <Link href="/audit" className="mt-8 inline-flex min-h-12 items-center rounded-full bg-ink px-7 font-medium text-white">
        Take the audit
      </Link>
    </main>
  );
}
