"use client";

import { useMemo, useState } from "react";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

import { AgentSelector } from "@/components/AgentSelector";
import { apiFetch, type AgentSummary, type ThreadSummary } from "@/lib/api";

export function CreateThreadForm({ agents }: { agents: AgentSummary[] }) {
  const router = useRouter();
  const { data: session } = useSession();
  const [topic, setTopic] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [selectedIds, setSelectedIds] = useState<string[]>(agents.slice(0, 2).map((agent) => agent.id));
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = topic.trim().length >= 3 && selectedIds.length >= 2 && selectedIds.length <= 5;
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
      if (current.length >= 5) {
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
      setError("テーマ3文字以上、人格は2〜5体で選択してください。");
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
          <span>{chosenLabels || "人格を2〜5体選択"}</span>
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
        <p className="text-xs leading-6 text-board-muted">
          無料プランは月5スレッド。テーマとユーザー投稿は OpenAI モデレーションで審査されます。
        </p>
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

