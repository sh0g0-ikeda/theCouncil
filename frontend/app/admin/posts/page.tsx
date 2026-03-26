import Link from "next/link";

import { AdminActionButton } from "@/components/AdminActionButton";
import { apiFetch } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type AdminPost = {
  thread_id: string;
  id: number;
  topic?: string;
  display_name?: string | null;
  content: string;
  created_at: string;
  report_count?: number;
  pending_report_count?: number;
};

export default async function AdminPostsPage() {
  const user = await requireAdminUser();
  let posts: AdminPost[] = [];

  try {
    posts = await apiFetch<AdminPost[]>("/api/admin/posts", {}, user);
  } catch {
    posts = [];
  }

  return (
    <main className="rounded-3xl border border-board-border bg-board-paper shadow-board">
      <div className="border-b border-board-border px-5 py-4">
        <h1 className="text-lg font-bold text-board-ink">Post Moderation</h1>
      </div>
      <div className="space-y-0">
        {posts.map((post) => (
          <article key={`${post.thread_id}-${post.id}`} className="border-t border-board-border/60 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="font-semibold text-board-ink">
                  #{post.id} {post.display_name ?? "User"}
                </div>
                <div className="text-xs text-board-muted">
                  {post.topic ?? "-"} / pending {post.pending_report_count ?? 0} / total {post.report_count ?? 0}
                </div>
                <div className="mt-1 text-xs text-board-muted">
                  <Link href={`/thread/${post.thread_id}`} className="hover:underline">
                    Open thread
                  </Link>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <AdminActionButton
                  path={`/api/admin/posts/${post.thread_id}/${post.id}`}
                  body={{ action: "hide" }}
                  label="Hide"
                  className="border-board-border hover:bg-white"
                />
                <AdminActionButton
                  path={`/api/admin/posts/${post.thread_id}/${post.id}`}
                  body={{ action: "warn" }}
                  label="Warn"
                  className="border-board-border hover:bg-white"
                />
                <AdminActionButton
                  path={`/api/admin/posts/${post.thread_id}/${post.id}`}
                  body={{ action: "delete" }}
                  label="Delete"
                  className="border-board-warn text-board-warn hover:bg-rose-50"
                />
              </div>
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-board-ink">{post.content}</p>
          </article>
        ))}
      </div>
    </main>
  );
}
