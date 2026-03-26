"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";

type LoginCardProps = {
  emailEnabled: boolean;
  xEnabled: boolean;
};

export function LoginCard({ emailEnabled, xEnabled }: LoginCardProps) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  const requestEmailCode = async () => {
    if (!email.trim()) {
      setError("Enter your email address");
      return;
    }

    try {
      setRequesting(true);
      setError("");
      const response = await fetch("/api/auth/email/request", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ email: email.trim() })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(payload.detail ?? "Failed to send email");
        return;
      }
      setSubmitted(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to send email");
    } finally {
      setRequesting(false);
    }
  };

  const signInWithEmail = async () => {
    if (!submitted) {
      await requestEmailCode();
      return;
    }
    if (!code.trim()) {
      setError("Enter the 6-digit code");
      return;
    }

    try {
      setVerifying(true);
      setError("");
      const result = await signIn("email-code", {
        email: email.trim(),
        code: code.trim(),
        callbackUrl: "/",
        redirect: false
      });
      if (result?.error) {
        setError(result.error);
        return;
      }
      if (result?.url) {
        window.location.href = result.url;
      }
    } catch (verifyError) {
      setError(verifyError instanceof Error ? verifyError.message : "Failed to sign in");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
      <h1 className="text-xl font-bold text-board-ink">Sign in</h1>
      <p className="mt-2 text-sm leading-6 text-board-muted">
        Use X or a one-time code sent to your email address.
      </p>

      <div className="mt-6 space-y-4">
        <button
          type="button"
          onClick={() => signIn("twitter", { callbackUrl: "/" })}
          disabled={!xEnabled}
          className="w-full rounded-2xl border border-board-border bg-white px-4 py-3 text-sm font-semibold text-board-ink hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Continue with X
        </button>

        <div className="rounded-2xl border border-board-border bg-white p-4">
          <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-board-muted">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-xl border border-board-border px-3 py-2 text-sm text-board-ink outline-none focus:border-board-accent"
            disabled={!emailEnabled || verifying}
          />
          {submitted ? (
            <input
              type="text"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="123456"
              className="mt-3 w-full rounded-xl border border-board-border px-3 py-2 text-sm text-board-ink outline-none focus:border-board-accent"
              inputMode="numeric"
              maxLength={6}
              disabled={verifying}
            />
          ) : null}
          <button
            type="button"
            onClick={signInWithEmail}
            disabled={!emailEnabled || requesting || verifying}
            className="mt-3 w-full rounded-xl bg-board-accent px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {requesting ? "Sending..." : verifying ? "Signing in..." : submitted ? "Sign in with code" : "Send code"}
          </button>
          {!emailEnabled ? (
            <p className="mt-2 text-xs text-board-muted">Email sign-in is not configured yet.</p>
          ) : null}
          {submitted ? (
            <p className="mt-2 text-xs text-board-muted">A 6-digit code was sent to your email address.</p>
          ) : null}
          {error ? <p className="mt-2 text-xs text-board-warn">{error}</p> : null}
        </div>
      </div>
    </div>
  );
}
