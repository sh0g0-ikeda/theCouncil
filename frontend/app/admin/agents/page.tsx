import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch, type AgentSummary } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminAgent = AgentSummary & {
  enabled?: boolean;
};

export default async function AdminAgentsPage() {
  const user = await requireAdminUser();
  let agents: AdminAgent[] = [];

  try {
    agents = await apiFetch<AdminAgent[]>("/api/admin/agents", {}, user);
  } catch {
    agents = [];
  }

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">AI人格管理</h1>
      </div>
      {agents.map((agent) => (
        <article key={agent.id} className="border-t border-board-border/60 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-board-ink">
                {agent.display_name} <span className="text-board-accent">({agent.label})</span>
              </div>
              <div className="text-xs text-board-muted">
                {agent.persona_json?.core_beliefs?.slice(0, 2).join(" / ") ?? "-"}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <AdminActionButton
                path={`/api/admin/agents/${agent.id}`}
                body={{ enabled: !(agent as AdminAgent).enabled }}
                label={(agent as AdminAgent).enabled ? "OFF" : "ON"}
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
      ))}
    </main>
  );
}
