import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch, type AgentSummary } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminAgent = AgentSummary & { enabled?: boolean };

const CATEGORY_ORDER = ["哲学者", "政治家", "軍人", "経済学者", "科学者", "作家", "起業家"];

const CATEGORY_COLORS: Record<string, string> = {
  哲学者:  "bg-violet-100 text-violet-700 border-violet-200",
  政治家:  "bg-blue-100 text-blue-700 border-blue-200",
  軍人:    "bg-red-100 text-red-700 border-red-200",
  経済学者: "bg-amber-100 text-amber-700 border-amber-200",
  科学者:  "bg-emerald-100 text-emerald-700 border-emerald-200",
  作家:    "bg-pink-100 text-pink-700 border-pink-200",
  起業家:  "bg-orange-100 text-orange-700 border-orange-200",
};

function AgentCategoryBadge({ cat }: { cat: string }) {
  const cls = CATEGORY_COLORS[cat] ?? "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {cat}
    </span>
  );
}

export default async function AdminAgentsPage() {
  const user = await requireAdminUser();
  let agents: AdminAgent[] = [];

  try {
    agents = await apiFetch<AdminAgent[]>("/api/admin/agents", {}, user);
  } catch {
    agents = [];
  }

  // Group agents by primary category (first category), ungrouped last
  const grouped: Record<string, AdminAgent[]> = {};
  const uncategorized: AdminAgent[] = [];

  for (const cat of CATEGORY_ORDER) {
    grouped[cat] = [];
  }
  for (const agent of agents) {
    const cats: string[] = agent.persona_json?.categories ?? [];
    if (cats.length === 0) {
      uncategorized.push(agent);
    } else {
      // Place agent under their first-listed category
      const primary = cats[0];
      if (primary in grouped) {
        grouped[primary].push(agent);
      } else {
        uncategorized.push(agent);
      }
    }
  }

  const sections = CATEGORY_ORDER.filter((cat) => grouped[cat].length > 0);
  if (uncategorized.length > 0) sections.push("未分類");

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="flex items-center justify-between border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">AI人格管理</h1>
        <span className="text-sm text-board-muted">{agents.length} 人格</span>
      </div>

      {sections.map((cat) => {
        const list = cat === "未分類" ? uncategorized : grouped[cat];
        return (
          <section key={cat}>
            <div className="flex items-center gap-2 border-t border-board-border bg-board-bg/40 px-5 py-2">
              <AgentCategoryBadge cat={cat} />
              <span className="text-xs text-board-muted">{list.length}名</span>
            </div>
            {list.map((agent) => {
              const cats: string[] = agent.persona_json?.categories ?? [];
              const worldview = agent.persona_json?.worldview ?? agent.persona_json?.core_beliefs ?? [];
              return (
                <article key={agent.id} className="border-t border-board-border/40 px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-board-ink">{agent.display_name}</span>
                        <span className="text-sm text-board-accent">{agent.label}</span>
                        {!agent.enabled && (
                          <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-600">
                            OFF
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {cats.map((c) => (
                          <AgentCategoryBadge key={c} cat={c} />
                        ))}
                      </div>
                      <p className="mt-1 text-xs text-board-muted">
                        {worldview.slice(0, 2).join(" / ") || "-"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <AdminActionButton
                        path={`/api/admin/agents/${agent.id}`}
                        body={{ enabled: !agent.enabled }}
                        label={agent.enabled ? "OFF" : "ON"}
                        className="border-board-border hover:bg-white"
                      />
                      <AdminActionButton
                        path={`/api/admin/agents/${agent.id}`}
                        body={{ refresh_rag: true }}
                        label="RAG更新"
                        className="border-board-border hover:bg-white"
                      />
                    </div>
                  </div>
                </article>
              );
            })}
          </section>
        );
      })}
    </main>
  );
}
