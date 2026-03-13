import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch, type ThreadSummary } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminThread = ThreadSummary & {
  owner_email?: string | null;
  hidden_at?: string | null;
  locked_at?: string | null;
};

export default async function AdminThreadsPage() {
  const user = await requireAdminUser();
  let threads: AdminThread[] = [];

  try {
    threads = await apiFetch<AdminThread[]>("/api/admin/threads", {}, user);
  } catch {
    threads = [];
  }

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">スレッド管理</h1>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-100 text-left text-xs uppercase tracking-[0.2em] text-board-muted">
            <tr>
              <th className="px-4 py-3">Thread</th>
              <th className="px-4 py-3">Owner</th>
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {threads.map((thread) => (
              <tr key={thread.id} className="border-t border-board-border/60 align-top">
                <td className="px-4 py-4">
                  <div className="font-semibold text-board-ink">{thread.topic}</div>
                  <div className="mt-1 text-xs text-board-muted">{thread.agent_ids.join(" / ")}</div>
                </td>
                <td className="px-4 py-4 text-board-muted">{thread.owner_email ?? "-"}</td>
                <td className="px-4 py-4 text-board-muted">
                  {thread.state}
                  {thread.hidden_at ? " / hidden" : ""}
                  {thread.locked_at ? " / locked" : ""}
                </td>
                <td className="px-4 py-4">
                  <div className="flex flex-wrap gap-2">
                    <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "hide" }} label="非表示" className="border-board-border hover:bg-white" />
                    <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "lock" }} label="ロック" className="border-board-border hover:bg-white" />
                    <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "force_complete" }} label="終了" className="border-board-border hover:bg-white" />
                    <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "delete" }} label="削除" className="border-board-warn text-board-warn hover:bg-rose-50" confirmMessage="スレッドを削除しますか?" />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

