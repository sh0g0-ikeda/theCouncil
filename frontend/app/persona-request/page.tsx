"use client";

import { useState } from "react";
import { getApiBaseUrl } from "@/lib/api";

type Status = "idle" | "loading" | "success" | "error";

export default function PersonaRequestPage() {
  const [personName, setPersonName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("loading");
    setError("");
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/persona-requests/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_name: personName, description }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail ?? "送信に失敗しました");
      }
      setStatus("success");
      setPersonName("");
      setDescription("");
    } catch (e: any) {
      setError(e.message ?? "エラーが発生しました");
      setStatus("error");
    }
  }

  return (
    <main className="space-y-6 max-w-xl mx-auto">
      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <h1 className="text-xl font-black text-board-ink">人格リクエスト・提案</h1>
        <p className="mt-2 text-sm leading-6 text-board-muted">
          追加してほしい人物を提案してください。誰でも投稿できます。
          運営が内容を確認の上、実装を検討します。
        </p>
      </section>

      {status === "success" ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 text-center">
          <div className="text-2xl mb-2">✓</div>
          <p className="font-bold text-board-ink">リクエストを送信しました！</p>
          <p className="mt-1 text-sm text-board-muted">ご提案ありがとうございます。確認後、実装を検討します。</p>
          <button
            type="button"
            onClick={() => setStatus("idle")}
            className="mt-4 rounded-full border border-board-border px-4 py-1.5 text-sm text-board-ink hover:bg-board-paper"
          >
            続けて提案する
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board space-y-4">
          <div>
            <label className="block text-sm font-semibold text-board-ink mb-1">
              人物名 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
              placeholder="例：カール・マルクス、孫子、スティーブ・ジョブズ"
              maxLength={100}
              required
              className="w-full rounded-xl border border-board-border bg-white px-3 py-2 text-sm text-board-ink placeholder:text-board-muted focus:outline-none focus:ring-2 focus:ring-board-accent"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-board-ink mb-1">
              どんな人物か・なぜ追加してほしいか <span className="text-red-500">*</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例：古代中国の兵法家。「孫子の兵法」の著者。戦略・リスク管理・情報収集の観点から現代の議論に独自の切り口を持ち込めると思います。"
              minLength={10}
              maxLength={1000}
              required
              rows={5}
              className="w-full rounded-xl border border-board-border bg-white px-3 py-2 text-sm text-board-ink placeholder:text-board-muted focus:outline-none focus:ring-2 focus:ring-board-accent resize-none"
            />
            <p className="mt-1 text-xs text-board-muted text-right">{description.length}/1000</p>
          </div>
          {status === "error" && (
            <p className="text-sm text-red-600">{error}</p>
          )}
          <button
            type="submit"
            disabled={status === "loading"}
            className="w-full rounded-full bg-board-accent py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {status === "loading" ? "送信中…" : "リクエストを送信する"}
          </button>
        </form>
      )}

      <section className="rounded-2xl border border-board-border bg-board-paper p-4 text-sm text-board-muted">
        <p className="font-semibold text-board-ink mb-1">提案のコツ</p>
        <ul className="space-y-1 list-disc list-inside">
          <li>その人物の思想的な特徴・強みを具体的に書くと採用されやすいです</li>
          <li>すでに実装済みの人物は<a href="/create" className="text-board-accent underline">スレッド作成ページ</a>で確認できます</li>
          <li>著名人・歴史上の人物であれば基本的に検討します</li>
        </ul>
      </section>
    </main>
  );
}
