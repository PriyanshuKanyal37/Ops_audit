"use client";

// Calendly inline booking widget (PRD §9.3 /audit/book). When Calendly reports a booking, we record
// call_booked (PRD §10.1/§10.3 depend on it). Needs NEXT_PUBLIC_CALENDLY_URL; without it a placeholder shows.

import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/api";

type CalendlyApi = { initInlineWidget: (options: { url: string; parentElement: HTMLElement }) => void };
declare global {
  interface Window {
    Calendly?: CalendlyApi;
  }
}

const CALENDLY_URL = process.env.NEXT_PUBLIC_CALENDLY_URL ?? "";
const SCRIPT_URL = "https://assets.calendly.com/assets/external/widget.js";

export default function CalendlyEmbed({ auditId }: { auditId: string | null }) {
  const box = useRef<HTMLDivElement>(null);
  const [booked, setBooked] = useState(false);

  // Calendly tells the page about bookings with a postMessage from calendly.com.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== "https://calendly.com" || event.data?.event !== "calendly.event_scheduled") return;
      setBooked(true);
      if (auditId) track(auditId, "booked");
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [auditId]);

  useEffect(() => {
    if (!CALENDLY_URL || !box.current) return;
    const url = new URL(CALENDLY_URL);
    url.searchParams.set("hide_gdpr_banner", "1");
    url.searchParams.set("utm_source", "ops_clarity_audit");
    if (auditId) url.searchParams.set("utm_content", auditId); // lets a Calendly webhook match the booking later
    const init = () => window.Calendly?.initInlineWidget({ url: url.toString(), parentElement: box.current! });
    if (window.Calendly) return init();
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = init;
    document.head.appendChild(script);
  }, [auditId]);

  return (
    <div>
      <p role="status" className={booked ? "mb-4 rounded-xl bg-accent-soft px-4 py-3 font-medium" : "sr-only"}>
        {booked ? "You're booked. A confirmation is on its way to your inbox." : ""}
      </p>
      {CALENDLY_URL ? (
        <div ref={box} className="h-[720px] min-w-0 overflow-hidden rounded-2xl border border-line bg-surface" />
      ) : (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-dashed border-line bg-surface p-6 text-center text-muted">
          Booking calendar not configured yet. Set NEXT_PUBLIC_CALENDLY_URL in frontend/.env.local.
        </div>
      )}
    </div>
  );
}
