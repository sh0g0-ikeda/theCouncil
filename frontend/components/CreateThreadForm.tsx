"use client";

import { useEffect, useMemo, useState } from "react";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

import { AgentSelector } from "@/components/AgentSelector";
import { apiFetch, type AgentSummary, type ThreadSummary } from "@/lib/api";

type Quota = { plan: string; used: number; limit: number | null; remaining: number | null };

export function CreateThreadForm({ agents }: { agents: AgentSummary[] }) {
  const router = useRouter();
  const { data: session } = useSession();
  const [topic, setTopic] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [selectedIds, setSelectedIds] = useState<string[]>(agents.slice(0, 2).map((agent) => agent.id));
  const [quota, setQuota] = useState<Quota | null>(null);

  useEffect(() => {
    if (!session?.user) return;
    apiFetch<Quota>("/api/threads/quota", {}, session.user)
      .then(setQuota)
      .catch(() => {});
  }, [session]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const maxAgents = quota?.plan === "pro" || quota?.plan === "ultra" ? 8 : 4;
  const canSubmit = topic.trim().length >= 3 && selectedIds.length >= 2 && selectedIds.length <= maxAgents;
  const chosenLabels = useMemo(
    () =>
      agents
        .filter((agent) => selectedIds.includes(agent.id))
        .map((agent) => agent.display_name)
        .join(" / "),
    [agents, selectedIds]
  );

  const toggleAgent = (agentId: string) => {
    setSelectedIds((current) => {
      if (current.includes(agentId)) {
        return current.length > 2 ? current.filter((id) => id !== agentId) : current;
      }
      if (current.length >= maxAgents) {
        return current;
      }
      return [...current, agentId];
    });
  };

  const submit = async () => {
    if (!session?.user) {
      await signIn();
      return;
    }

    if (!canSubmit) {
      setError(`テーマ3文字以上、人格は2〜${maxAgents}体で選択してください。`);
      return;
    }

    try {
      setSubmitting(true);
      setError("");
      const thread = await apiFetch<ThreadSummary>(
        "/api/threads/",
        {
          method: "POST",
          body: JSON.stringify({
            topic,
            agent_ids: selectedIds,
            visibility
          })
        },
        session.user
      );
      router.push(`/thread/${thread.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "スレッド作成に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
      <div className="mb-5">
        <label className="mb-2 block text-sm font-semibold text-board-ink">スレテーマ</label>
        <textarea
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="例: AIによる雇用代替に国家はどこまで介入すべきか"
          className="h-28 w-full rounded-2xl border border-board-border bg-white px-4 py-3 text-sm leading-7 text-board-ink outline-none ring-0 transition focus:border-board-accent"
          maxLength={500}
        />
        <div className="mt-2 flex items-center justify-between text-xs text-board-muted">
          <span>{topic.length} / 500</span>
          <span>{chosenLabels || `人格を2〜${maxAgents}体選択`}</span>
        </div>
      </div>

      <div className="mb-5 flex flex-wrap gap-2">
        {(["public", "private"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setVisibility(option)}
            className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${
              visibility === option
                ? "border-board-accent bg-board-accent text-white"
                : "border-board-border bg-white text-board-ink"
            }`}
          >
            {option}
          </button>
        ))}
      </div>

      <AgentSelector agents={agents} selectedIds={selectedIds} onToggle={toggleAgent} />

      {error ? <p className="mt-4 text-sm text-board-warn">{error}</p> : null}

      <div className="mt-6 flex items-center justify-between">
        <div className="text-xs leading-6 text-board-muted">
          <p>テーマとユーザー投稿は OpenAI モデレーションで審査されます。</p>
          {quota && (
            <p className="mt-0.5">
              今月のスレッド作成:{" "}
              {quota.limit === null ? (
                <span className="font-semibold text-board-ink">{quota.used} 本（無制限）</span>
              ) : (
                <span className={`font-semibold ${quota.remaining === 0 ? "text-board-warn" : "text-board-ink"}`}>
                  残り {quota.remaining} / {quota.limit} 本
                </span>
              )}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="rounded-full bg-board-accent px-5 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "作成中..." : "スレッドを立てる"}
        </button>
      </div>
    </div>
  );
}

