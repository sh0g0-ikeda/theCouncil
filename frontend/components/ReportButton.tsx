"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";

import { apiFetch } from "@/lib/api";
import type { SessionUser } from "@/lib/session-user";

const REPORT_REASONS = [
  { value: "hate", label: "Hate" },
  { value: "violence", label: "Violence" },
  { value: "defamation", label: "Defamation" },
  { value: "crime", label: "Crime" },
  { value: "other", label: "Other" }
] as const;

type ReportButtonProps = {
  path: string;
  user?: SessionUser | null;
  compact?: boolean;
};

export function ReportButton({ path, user, compact = false }: ReportButtonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<(typeof REPORT_REASONS)[number]["value"]>("other");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState("");

  const submit = async () => {
    if (!user) {
      await signIn(undefined, { callbackUrl: window.location.href });
      return;
    }

    try {
      setSending(true);
      setMessage("");
      const result = await apiFetch<{ duplicate?: boolean }>(
        path,
        {
          method: "POST",
          body: JSON.stringify({ reason })
        },
        user
      );
      setDone(true);
      setOpen(false);
      setMessage(result.duplicate ? "Already reported" : "Report submitted");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to submit report");
    } finally {
      setSending(false);
    }
  };

  if (done) {
    return <span className="text-xs text-board-muted">{message || "Reported"}</span>;
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setMessage("");
          setOpen(true);
        }}
        className={`rounded border border-board-border px-2 py-1 text-xs text-board-muted hover:bg-white ${compact ? "" : "font-medium"}`}
      >
        Report
      </button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={reason}
        onChange={(event) => setReason(event.target.value as typeof reason)}
        className="rounded border border-board-border bg-board-paper px-2 py-1 text-xs text-board-ink"
      >
        {REPORT_REASONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={submit}
        disabled={sending}
        className="rounded border border-board-warn px-2 py-1 text-xs font-medium text-board-warn hover:bg-rose-50 disabled:opacity-50"
      >
        {sending ? "Sending..." : "Submit"}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded border border-board-border px-2 py-1 text-xs text-board-muted hover:bg-white"
      >
        Close
      </button>
      {message ? <span className="text-xs text-board-muted">{message}</span> : null}
    </div>
  );
}
