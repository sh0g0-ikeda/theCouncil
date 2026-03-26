import Link from "next/link";

import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminReport = {
  id: number;
  thread_id?: string | null;
  post_id?: number | null;
  target_type: "thread" | "post";
  topic?: string | null;
  post_content?: string | null;
  reporter_email?: string | null;
  reporter_x_id?: string | null;
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
        <h1 className="text-lg font-bold text-board-ink">Report Queue</h1>
      </div>
      {reports.map((report) => (
        <article key={report.id} className="border-t border-board-border/60 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-board-ink">Report #{report.id}</div>
              <div className="text-xs text-board-muted">
                {report.target_type} / {report.reason} / {report.status} /{" "}
                {new Date(report.created_at).toLocaleString("ja-JP")}
              </div>
              <div className="mt-1 text-xs text-board-muted">
                reporter: {report.reporter_email ?? report.reporter_x_id ?? "-"}
              </div>
              <div className="mt-1 text-xs text-board-muted">
                thread: {report.thread_id ?? "-"}
                {report.post_id != null ? <> / post: #{report.post_id}</> : null}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <AdminActionButton
                path={`/api/admin/reports/${report.id}`}
                body={{ action: "resolved" }}
                label="Resolve"
                className="border-board-border hover:bg-white"
              />
              <AdminActionButton
                path={`/api/admin/reports/${report.id}`}
                body={{ action: "dismissed" }}
                label="Dismiss"
                className="border-board-border hover:bg-white"
              />
              {report.target_type === "post" ? (
                <AdminActionButton
                  path={`/api/admin/reports/${report.id}`}
                  body={{ action: "delete_post" }}
                  label="Delete post"
                  className="border-board-warn text-board-warn hover:bg-rose-50"
                />
              ) : (
                <>
                  <AdminActionButton
                    path={`/api/admin/reports/${report.id}`}
                    body={{ action: "hide_thread" }}
                    label="Hide thread"
                    className="border-board-border hover:bg-white"
                  />
                  <AdminActionButton
                    path={`/api/admin/reports/${report.id}`}
                    body={{ action: "delete_thread" }}
                    label="Delete thread"
                    className="border-board-warn text-board-warn hover:bg-rose-50"
                  />
                </>
              )}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-board-muted">
            {report.thread_id ? (
              <Link href={`/thread/${report.thread_id}`} className="hover:underline">
                Open thread
              </Link>
            ) : null}
            <span>{report.topic ?? "-"}</span>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-board-ink">
            {report.post_content ?? "Thread-level report"}
          </p>
        </article>
      ))}
    </main>
  );
}
