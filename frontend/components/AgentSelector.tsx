"use client";

import type { AgentSummary } from "@/lib/api";

export function AgentSelector({
  agents,
  selectedIds,
  onToggle
}: {
  agents: AgentSummary[];
  selectedIds: string[];
  onToggle: (agentId: string) => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {agents.map((agent) => {
        const selected = selectedIds.includes(agent.id);
        const beliefs = agent.persona_json?.core_beliefs ?? [];
        return (
          <button
            key={agent.id}
            type="button"
            onClick={() => onToggle(agent.id)}
            className={`rounded-2xl border p-4 text-left transition ${
              selected
                ? "border-board-accent bg-emerald-50 shadow-board"
                : "border-board-border bg-board-paper hover:bg-white"
            }`}
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold text-board-ink">{agent.display_name}</span>
              <span className="rounded-full border border-board-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-board-muted">
                {selected ? "選択中" : "未選択"}
              </span>
            </div>
            <div className="text-sm text-board-accent">{agent.label}</div>
            <p className="mt-2 text-xs leading-6 text-board-muted">{beliefs.slice(0, 2).join(" / ")}</p>
          </button>
        );
      })}
    </div>
  );
}

