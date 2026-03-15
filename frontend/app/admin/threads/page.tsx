import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch, type ThreadSummary } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminThread = ThreadSummary & {
  owner_email?: string | null;
  hidden_at?: string | null;
  locked_at?: string | null;
  deleted_at?: string | null;
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
              <th className="px-4 py-3">State / Visibility</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {threads.map((thread) => (
              <tr
                key={thread.id}
                className={`border-t border-board-border/60 align-top ${thread.deleted_at ? "opacity-40" : ""}`}
              >
                <td className="px-4 py-4">
                  <div className="font-semibold text-board-ink">{thread.topic}</div>
                  <div className="mt-1 text-xs text-board-muted">{thread.agent_ids.join(" / ")}</div>
                  <div className="mt-1 text-xs text-board-muted">{thread.id}</div>
                </td>
                <td className="px-4 py-4 text-board-muted">{thread.owner_email ?? "-"}</td>
                <td className="px-4 py-4 text-board-muted">
                  <div>{thread.state}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                      thread.visibility === "public"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-stone-200 text-stone-600"
                    }`}>
                      {thread.visibility}
                    </span>
                    {thread.hidden_at && <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-xs text-yellow-700">hidden</span>}
                    {thread.locked_at && <span className="rounded bg-orange-100 px-1.5 py-0.5 text-xs text-orange-700">locked</span>}
                    {thread.deleted_at && <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">deleted</span>}
                  </div>
                </td>
                <td className="px-4 py-4">
                  <div className="flex flex-wrap gap-2">
                    {thread.visibility === "private" ? (
                      <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "set_public" }} label="公開にする" className="border-emerald-300 text-emerald-700 hover:bg-emerald-50" />
                    ) : (
                      <AdminActionButton path={`/api/admin/threads/${thread.id}`} body={{ action: "set_private" }} label="非公開にする" className="border-board-border hover:bg-white" />
                    )}
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

