"use client";

import { useState, type FormEvent } from "react";
import { ApiError, emailReport } from "@/lib/api";

// PRD §7.10 "email this to me": framed as a convenience, and it is NOT a newsletter sign-up.
export default function EmailReportForm({ auditId }: { auditId: string }) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<{ text: string; ok: boolean } | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSending(true);
    setStatus(null);
    try {
      await emailReport(auditId, email);
      setStatus({ text: "Sent. Check your inbox (and your spam folder, just in case).", ok: true });
    } catch (error) {
      setStatus({
        text: error instanceof ApiError ? error.message : "We couldn't reach the server. Please try again.",
        ok: false,
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-6">
      <label htmlFor="report-email" className="block text-sm font-medium">
        Email me this report
      </label>
      <p id="report-email-hint" className="mt-1 text-sm text-muted">
        We&apos;ll send you the link and a short summary. Nothing else.
      </p>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row">
        <input
          id="report-email"
          name="email"
          type="email"
          required
          autoComplete="email"
          enterKeyHint="send"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-describedby="report-email-hint"
          className="min-h-12 min-w-0 flex-1 rounded-xl border border-line bg-surface px-4 text-base"
        />
        <button
          type="submit"
          disabled={sending}
          className="min-h-12 shrink-0 rounded-full bg-ink px-6 font-medium text-white hover:opacity-85 disabled:opacity-60"
        >
          {sending ? "Sending…" : "Email it to me"}
        </button>
      </div>
      <p role="status" className={`mt-3 min-h-5 text-sm font-medium ${status?.ok === false ? "text-bad" : "text-good"}`}>
        {status?.text}
      </p>
    </form>
  );
}
