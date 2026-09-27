"use client";

import type { ReactNode } from "react";
import { track } from "@/lib/api";

// A report CTA link that records the click (clicked_cta) before the browser leaves the page (PRD §10.1).
export default function TrackedLink({
  href,
  auditId,
  className,
  children,
}: {
  href: string;
  auditId: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a href={href} className={className} onClick={() => track(auditId, "cta_click")}>
      {children}
    </a>
  );
}
