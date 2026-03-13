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
        <h1 className="text-lg font-bold text-board-ink">レス管理</h1>
      </div>
      <div className="space-y-0">
        {posts.map((post) => (
          <article key={`${post.thread_id}-${post.id}`} className="border-t border-board-border/60 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="font-semibold text-board-ink">
                  #{post.id} {post.display_name ?? "ユーザー"}
                </div>
                <div className="text-xs text-board-muted">{post.topic ?? "-"}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <AdminActionButton path={`/api/admin/posts/${post.thread_id}/${post.id}`} body={{ action: "hide" }} label="非表示" className="border-board-border hover:bg-white" />
                <AdminActionButton path={`/api/admin/posts/${post.thread_id}/${post.id}`} body={{ action: "warn" }} label="警告" className="border-board-border hover:bg-white" />
                <AdminActionButton path={`/api/admin/posts/${post.thread_id}/${post.id}`} body={{ action: "delete" }} label="削除" className="border-board-warn text-board-warn hover:bg-rose-50" />
              </div>
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-board-ink">{post.content}</p>
          </article>
        ))}
      </div>
    </main>
  );
}

