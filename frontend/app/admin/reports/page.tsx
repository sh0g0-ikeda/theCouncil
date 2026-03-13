import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminReport = {
  id: number;
  topic?: string | null;
  post_content?: string | null;
  reason: string;
  status: string;
  created_at: string;
};

export default async function AdminReportsPage() {
  const user = await requireAdminUser();
  let reports: AdminReport[] = [];

  try {
    reports = await apiFetch<AdminReport[]>("/api/admin/reports", {}, user);
  } catch {
    reports = [];
  }

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">通報管理</h1>
      </div>
      {reports.map((report) => (
        <article key={report.id} className="border-t border-board-border/60 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-board-ink">Report #{report.id}</div>
              <div className="text-xs text-board-muted">
                {report.reason} / {report.status} / {new Date(report.created_at).toLocaleString("ja-JP")}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <AdminActionButton path={`/api/admin/reports/${report.id}`} body={{ action: "resolved" }} label="対応済" className="border-board-border hover:bg-white" />
              <AdminActionButton path={`/api/admin/reports/${report.id}`} body={{ action: "dismissed" }} label="無効" className="border-board-border hover:bg-white" />
              <AdminActionButton path={`/api/admin/reports/${report.id}`} body={{ action: "delete_post" }} label="投稿削除" className="border-board-warn text-board-warn hover:bg-rose-50" />
            </div>
          </div>
          <div className="mt-3 text-xs text-board-muted">{report.topic ?? "-"}</div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-board-ink">{report.post_content ?? "対象投稿なし"}</p>
        </article>
      ))}
    </main>
  );
}

