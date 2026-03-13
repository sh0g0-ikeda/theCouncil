import { CreateThreadForm } from "@/components/CreateThreadForm";
import { apiFetch, type AgentSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function CreatePage() {
  let agents: AgentSummary[] = [];

  try {
    agents = await apiFetch<AgentSummary[]>("/api/agents/");
  } catch {
    agents = [];
  }

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
        <h1 className="text-xl font-bold text-board-ink">スレッド作成</h1>
        <p className="mt-2 text-sm leading-6 text-board-muted">
          参加人格は3〜8体。テーマは作成時にモデレーションとタグ抽出が走り、以後は議論制御エンジンが発言順を決めます。
        </p>
      </section>
      <CreateThreadForm agents={agents} />
    </main>
  );
}

