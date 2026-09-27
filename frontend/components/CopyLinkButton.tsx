"use client";

import { useRef, useState, useSyncExternalStore } from "react";

const noop = () => () => {};

// PRD §7.10: permalink + copy button. "Email this to me" is added in Phase 4.
export default function CopyLinkButton() {
  const url = useSyncExternalStore(noop, () => window.location.href.split("#")[0], () => "");
  const [status, setStatus] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setStatus("Link copied.");
    } catch {
      inputRef.current?.select(); // clipboard blocked: select the text so Ctrl+C works
      setStatus("Press Ctrl+C (or ⌘C) to copy the selected link.");
    }
  }

  return (
    <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
      <label htmlFor="permalink" className="sr-only">
        Report link
      </label>
      <input
        id="permalink"
        ref={inputRef}
        readOnly
        value={url}
        onFocus={(e) => e.target.select()}
        className="min-h-12 min-w-0 flex-1 rounded-xl border border-line bg-surface px-4 font-mono text-sm"
      />
      <button
        type="button"
        onClick={copy}
        className="min-h-12 shrink-0 rounded-full bg-ink px-6 font-medium text-white hover:opacity-85"
      >
        Copy link
      </button>
      <p role="status" className="min-h-5 text-sm text-muted">
        {status}
      </p>
    </div>
  );
}
