import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminUser = {
  id: string;
  email?: string | null;
  plan: string;
  role: string;
  is_banned: boolean;
  warning_count: number;
};

export default async function AdminUsersPage() {
  const user = await requireAdminUser();
  let users: AdminUser[] = [];

  try {
    users = await apiFetch<AdminUser[]>("/api/admin/users", {}, user);
  } catch {
    users = [];
  }

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">ユーザー管理</h1>
      </div>
      {users.map((entry) => (
        <article key={entry.id} className="border-t border-board-border/60 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-board-ink">{entry.email ?? entry.id}</div>
              <div className="text-xs text-board-muted">
                role={entry.role} / plan={entry.plan} / warnings={entry.warning_count} / banned={String(entry.is_banned)}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <AdminActionButton path={`/api/admin/users/${entry.id}`} body={{ action: "ban" }} label="BAN" className="border-board-warn text-board-warn hover:bg-rose-50" />
              <AdminActionButton path={`/api/admin/users/${entry.id}`} body={{ action: "unban" }} label="解除" className="border-board-border hover:bg-white" />
              <AdminActionButton path={`/api/admin/users/${entry.id}`} body={{ action: "plan", plan: "free" }} label="free" className="border-board-border hover:bg-white" />
              <AdminActionButton path={`/api/admin/users/${entry.id}`} body={{ action: "plan", plan: "pro" }} label="pro" className="border-board-border hover:bg-white" />
              <AdminActionButton path={`/api/admin/users/${entry.id}`} body={{ action: "plan", plan: "ultra" }} label="ultra" className="border-board-border hover:bg-white" />
            </div>
          </div>
        </article>
      ))}
    </main>
  );
}

