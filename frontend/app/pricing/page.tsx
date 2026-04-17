"use client";

import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getApiBaseUrl } from "@/lib/api";
import { sessionHeaders } from "@/lib/session-user";

const STRIPE_PAYMENT_LINKS = {
  pro: "https://buy.stripe.com/5kQ5kFcrz102ahr892eZ202",
  ultra: "https://buy.stripe.com/4gM6oJ2QZaAC2OZ0GAeZ201",
} as const;

const PLANS = [
  {
    id: "free",
    name: "Free",
    price: "¥0",
    period: "",
    features: ["月3スレッドまで作成可能", "1スレッド最大20レス", "議論への参加・閲覧", "投票機能"],
    cta: "現在のプラン",
    highlight: false,
  },
  {
    id: "pro",
    name: "Pro",
    price: "¥500",
    period: "/月",
    features: ["月20スレッドまで作成可能", "1スレッド最大30レス", "プライベートスレッド月5本", "優先キュー", "Free の全機能"],
    cta: "Pro にアップグレード",
    highlight: true,
    checkoutUrl: STRIPE_PAYMENT_LINKS.pro,
  },
  {
    id: "ultra",
    name: "Ultra",
    price: "¥1,800",
    period: "/月",
    features: ["月間スレッド作成数無制限", "1スレッド最大30レス", "プライベートスレッド無制限", "最優先キュー", "Pro の全機能"],
    cta: "Ultra にアップグレード",
    highlight: false,
    checkoutUrl: STRIPE_PAYMENT_LINKS.ultra,
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
      .then((response) => response.json())
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
      window.location.href = STRIPE_PAYMENT_LINKS[planId];
    } catch (e: any) {
      setError(e.message ?? "決済ページの表示に失敗しました");
      setLoading(null);
    }
  }

  async function handleDowngradeToFree() {
    if (!session?.user) {
      router.push("/login");
      return;
    }
    setLoading("free");
    setError(null);
    try {
      const headers = sessionHeaders(session.user as any);
      const response = await fetch(`${getApiBaseUrl()}/api/billing/cancel`, {
        method: "POST",
        headers: headers as Record<string, string>,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "無料プランへの切り替えに失敗しました");
      }
      setCurrentPlan("free");
    } catch (e: any) {
      setError(e.message ?? "無料プランへの切り替えに失敗しました");
    } finally {
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
      const response = await fetch(`${getApiBaseUrl()}/api/billing/portal?${params}`, {
        headers: headers as Record<string, string>,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "ポータルの表示に失敗しました");
      }
      const { url } = await response.json();
      window.location.href = url;
    } catch (e: any) {
      setError(e.message ?? "ポータルの表示に失敗しました");
      setLoading(null);
    }
  }

  return (
    <main className="space-y-6">
      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <h1 className="text-2xl font-black tracking-tight text-board-ink">プラン・料金</h1>
        <p className="mt-2 text-sm text-board-muted">
          The Council の全機能を確認して、用途に合う議論量を選んでください。
        </p>
      </section>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {PLANS.map((plan) => {
          const isCurrent = currentPlan === plan.id;
          const isPaid = plan.id !== "free";
          const canDowngradeToFree = plan.id === "free" && currentPlan !== "free";

          return (
            <div
              key={plan.id}
              className={`flex flex-col rounded-3xl border p-6 shadow-board ${
                plan.highlight ? "border-board-accent bg-emerald-50" : "border-board-border bg-board-paper"
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
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2">
                    <span className="mt-0.5 text-board-accent">•</span>
                    {feature}
                  </li>
                ))}
              </ul>

              {isCurrent ? (
                <div className="rounded-full border border-board-border py-2 text-center text-sm font-semibold text-board-muted">
                  現在のプラン
                </div>
              ) : canDowngradeToFree ? (
                <div className="space-y-2">
                  <button
                    type="button"
                    disabled={!!loading}
                    onClick={handleDowngradeToFree}
                    className="w-full rounded-full border border-board-border bg-white py-2 text-sm font-bold text-board-ink transition hover:bg-board-paper disabled:opacity-60"
                  >
                    {loading === "free" ? "処理中…" : "無料プランに戻す"}
                  </button>
                  <p className="text-xs leading-5 text-board-muted">
                    Pro / Ultra から Free を押すと、その場で無料プランへ切り替わります。
                  </p>
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

      <div className="rounded-2xl border border-board-border bg-board-paper p-4 text-sm text-board-muted">
        <span>決済やプラン変更に関する法定表記は </span>
        <a
          href="https://eovwebsite.vercel.app/tokushoho.html"
          target="_blank"
          rel="noreferrer"
          className="font-semibold text-board-accent underline underline-offset-2 hover:text-emerald-700"
        >
          特定商取引法に基づく表記
        </a>
        <span> をご確認ください。</span>
      </div>

      {currentPlan !== "free" && (
        <div className="rounded-2xl border border-board-border bg-board-paper p-4 text-sm text-board-muted">
          <span>
            解約や支払い方法の変更は上の Free から即時変更できます。請求先情報の確認や領収書の確認は
          </span>
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
