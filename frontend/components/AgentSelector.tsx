"use client";

import { useState } from "react";
import type { AgentSummary } from "@/lib/api";

const CATEGORY_ORDER = ["全て", "哲学者", "政治家", "軍人", "経済学者", "科学者", "作家", "起業家"];

const CATEGORY_COLORS: Record<string, string> = {
  哲学者: "bg-violet-100 text-violet-700 border-violet-200",
  政治家: "bg-blue-100 text-blue-700 border-blue-200",
  軍人:   "bg-red-100 text-red-700 border-red-200",
  経済学者: "bg-amber-100 text-amber-700 border-amber-200",
  科学者: "bg-emerald-100 text-emerald-700 border-emerald-200",
  作家:   "bg-pink-100 text-pink-700 border-pink-200",
  起業家: "bg-orange-100 text-orange-700 border-orange-200",
};

function getCategories(agent: AgentSummary): string[] {
  return agent.persona_json?.categories ?? [];
}

export function AgentSelector({
  agents,
  selectedIds,
  onToggle,
}: {
  agents: AgentSummary[];
  selectedIds: string[];
  onToggle: (agentId: string) => void;
}) {
  const [activeCategory, setActiveCategory] = useState("全て");

  // Collect only categories that actually exist in the agent list
  const presentCategories = CATEGORY_ORDER.filter((cat) => {
    if (cat === "全て") return true;
    return agents.some((a) => getCategories(a).includes(cat));
  });

  const filtered =
    activeCategory === "全て"
      ? agents
      : agents.filter((a) => getCategories(a).includes(activeCategory));

  return (
    <div className="space-y-3">
      {/* Category filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {presentCategories.map((cat) => {
          const isActive = activeCategory === cat;
          const colorClass =
            cat === "全て"
              ? isActive
                ? "bg-board-ink text-white border-board-ink"
                : "border-board-border text-board-muted hover:bg-board-paper"
              : isActive
                ? `${CATEGORY_COLORS[cat] ?? "bg-board-accent/10 text-board-accent border-board-accent"} border`
                : "border-board-border text-board-muted hover:bg-board-paper";
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setActiveCategory(cat)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition ${colorClass}`}
            >
              {cat}
              {cat !== "全て" && (
                <span className="ml-1 opacity-60">
                  {agents.filter((a) => getCategories(a).includes(cat)).length}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Agent grid */}
      <div className="grid gap-3 md:grid-cols-2">
        {filtered.map((agent) => {
          const selected = selectedIds.includes(agent.id);
          const cats = getCategories(agent);
          const worldview = agent.persona_json?.worldview ?? agent.persona_json?.core_beliefs ?? [];
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
              <div className="mb-1 flex items-start justify-between gap-2">
                <span className="font-semibold text-board-ink">{agent.display_name}</span>
                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                    selected
                      ? "border-board-accent bg-emerald-100 text-board-accent"
                      : "border-board-border text-board-muted"
                  }`}
                >
                  {selected ? "選択中" : "未選択"}
                </span>
              </div>
              <div className="mb-2 text-sm text-board-accent">{agent.label}</div>
              {/* Category badges */}
              {cats.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {cats.map((cat) => (
                    <span
                      key={cat}
                      className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                        CATEGORY_COLORS[cat] ?? "bg-gray-100 text-gray-600 border-gray-200"
                      }`}
                    >
                      {cat}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-xs leading-5 text-board-muted">
                {worldview.slice(0, 2).join(" / ")}
              </p>
            </button>
          );
        })}
      </div>

      {filtered.length === 0 && (
        <p className="py-6 text-center text-sm text-board-muted">
          このカテゴリには該当するエージェントがいません
        </p>
      )}
    </div>
  );
}
