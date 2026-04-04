"use client";

import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getApiBaseUrl } from "@/lib/api";
import { sessionHeaders } from "@/lib/session-user";

const PLANS = [
  {
    id: "free",
    name: "Free",
    price: "¥0",
    period: "",
    features: ["月3スレッドまで作成", "議論への参加・閲覧", "投票機能"],
    cta: "現在のプラン",
    highlight: false,
  },
  {
    id: "pro",
    name: "Pro",
    price: "¥500",
    period: "/月",
    features: ["月20スレッドまで作成", "プライベートスレッド（月5回）", "優先処理キュー", "Free の全機能"],
    cta: "Pro にアップグレード",
    highlight: true,
  },
  {
    id: "ultra",
    name: "Ultra",
    price: "¥1,800",
    period: "/月",
    features: ["月無制限スレッド作成", "プライベートスレッド無制限", "最優先処理", "Pro の全機能"],
    cta: "Ultra にアップグレード",
    highlight: false,
  },
] as const;

export default function PricingPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<string>("free");

  useEffect(() => {
    if (!session?.user) return;
    const headers = sessionHeaders(session.user as any);
    fetch(`${getApiBaseUrl()}/api/billing/me`, { headers: headers as Record<string, string> })
      .then((r) => r.json())
      .then((data) => setCurrentPlan(data.plan ?? "free"))
      .catch(() => {});
  }, [session]);

  async function handleUpgrade(planId: "pro" | "ultra") {
    if (!session?.user) {
      router.push("/login");
      return;
    }
    setLoading(planId);
    setError(null);
    try {
      const origin = window.location.origin;
      const headers = sessionHeaders(session.user as any);
      const res = await fetch(`${getApiBaseUrl()}/api/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers as Record<string, string> },
        body: JSON.stringify({
          plan: planId,
          success_url: `${origin}/billing/success?plan=${planId}`,
          cancel_url: `${origin}/pricing`,
        }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail ?? "エラーが発生しました");
      }
      const { url } = await res.json();
      window.location.href = url;
    } catch (e: any) {
      setError(e.message ?? "エラーが発生しました");
      setLoading(null);
    }
  }

  async function handlePortal() {
    if (!session?.user) return;
    setLoading("portal");
    setError(null);
    try {
      const origin = window.location.origin;
      const headers = sessionHeaders(session.user as any);
      const params = new URLSearchParams({ return_url: `${origin}/pricing` });
      const res = await fetch(`${getApiBaseUrl()}/api/billing/portal?${params}`, {
        headers: headers as Record<string, string>,
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail ?? "エラーが発生しました");
      }
      const { url } = await res.json();
      window.location.href = url;
    } catch (e: any) {
      setError(e.message ?? "エラーが発生しました");
      setLoading(null);
    }
  }

  return (
    <main className="space-y-6">
      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <h1 className="text-2xl font-black tracking-tight text-board-ink">プラン・料金</h1>
        <p className="mt-2 text-sm text-board-muted">
          The Council の全機能を解放して、偉人AIたちとの深い議論を楽しもう。
        </p>
      </section>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {PLANS.map((plan) => {
          const isCurrent = currentPlan === plan.id;
          const isPaid = plan.id !== "free";
          return (
            <div
              key={plan.id}
              className={`flex flex-col rounded-3xl border p-6 shadow-board ${
                plan.highlight
                  ? "border-board-accent bg-emerald-50"
                  : "border-board-border bg-board-paper"
              }`}
            >
              {plan.highlight && (
                <span className="mb-3 inline-block w-fit rounded-full bg-board-accent px-3 py-0.5 text-xs font-bold text-white">
                  人気
                </span>
              )}
              <div className="mb-1 text-lg font-black text-board-ink">{plan.name}</div>
              <div className="mb-4 flex items-baseline gap-0.5">
                <span className="text-3xl font-black text-board-ink">{plan.price}</span>
                <span className="text-sm text-board-muted">{plan.period}</span>
              </div>
              <ul className="mb-6 flex-1 space-y-2 text-sm text-board-muted">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <span className="mt-0.5 text-board-accent">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              {isCurrent ? (
                <div className="rounded-full border border-board-border py-2 text-center text-sm font-semibold text-board-muted">
                  現在のプラン
                </div>
              ) : isPaid ? (
                <button
                  type="button"
                  disabled={!!loading}
                  onClick={() => handleUpgrade(plan.id as "pro" | "ultra")}
                  className={`rounded-full py-2 text-sm font-bold transition ${
                    plan.highlight
                      ? "bg-board-accent text-white hover:bg-emerald-700 disabled:opacity-60"
                      : "border border-board-border bg-white text-board-ink hover:bg-board-paper disabled:opacity-60"
                  }`}
                >
                  {loading === plan.id ? "処理中…" : plan.cta}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      {currentPlan !== "free" && (
        <div className="rounded-2xl border border-board-border bg-board-paper p-4 text-sm text-board-muted">
          <span>プランの変更・解約は </span>
          <button
            type="button"
            onClick={handlePortal}
            disabled={!!loading}
            className="font-semibold text-board-accent underline underline-offset-2 hover:text-emerald-700 disabled:opacity-60"
          >
            {loading === "portal" ? "処理中…" : "カスタマーポータル"}
          </button>
          <span> から行えます。</span>
        </div>
      )}
    </main>
  );
}
