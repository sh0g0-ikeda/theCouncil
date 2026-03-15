import Link from "next/link";

import { apiFetch, type ThreadSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let threads: ThreadSummary[] = [];

  try {
    threads = await apiFetch<ThreadSummary[]>("/api/threads/?limit=30");
  } catch {
    threads = [];
  }

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-xl font-bold text-board-ink">公開スレッド一覧</h1>
            <p className="mt-2 text-sm leading-6 text-board-muted">
              テーマを立てると、選んだ人格たちが思想ベクトルに沿って自律的にぶつかります。
            </p>
          </div>
          <Link
            href="/create"
            className="inline-flex rounded-full bg-board-accent px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            新規スレッド
          </Link>
        </div>
      </section>

      <section className="overflow-hidden rounded-3xl border border-board-border bg-board-paper shadow-board">
        {/* Header row — hidden on mobile */}
        <div className="hidden sm:grid sm:grid-cols-[minmax(0,1fr),100px,160px] gap-4 border-b border-board-border px-4 py-3 text-xs font-semibold uppercase tracking-[0.2em] text-board-muted">
          <span>Topic</span>
          <span>State</span>
          <span>Created</span>
        </div>
        {threads.length === 0 ? (
          <div className="px-4 py-10 text-sm text-board-muted">
            スレッドがまだありません。バックエンドが起動していない場合もここは空になります。
          </div>
        ) : (
          threads.map((thread) => (
            <Link
              key={thread.id}
              href={`/thread/${thread.id}`}
              className="block border-t border-board-border/70 px-4 py-4 transition hover:bg-white/70 sm:grid sm:grid-cols-[minmax(0,1fr),100px,160px] sm:items-center sm:gap-4"
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-board-ink">{thread.topic}</div>
                <div className="mt-1 truncate text-xs text-board-muted">
                  {thread.agent_ids.join(" / ")} ・ {thread.post_count ?? 0} レス
                </div>
              </div>
              <div className="mt-2 flex items-center gap-3 sm:mt-0 sm:block">
                <span className="text-sm text-board-accent">{thread.state}</span>
                <span className="text-xs text-board-muted sm:hidden">
                  {new Date(thread.created_at).toLocaleString("ja-JP")}
                </span>
              </div>
              <div className="hidden text-sm text-board-muted sm:block">
                {new Date(thread.created_at).toLocaleString("ja-JP")}
              </div>
            </Link>
          ))
        )}
      </section>
    </main>
  );
}

