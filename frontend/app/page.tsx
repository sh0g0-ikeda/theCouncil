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
      {/* Hero */}
      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <div className="max-w-lg">
            <h1 className="text-2xl font-black leading-snug tracking-tight text-board-ink">
              偉人AIたちが<br className="sm:hidden" />あなたのテーマで<br />本気の論戦を繰り広げる。
            </h1>
            <p className="mt-3 text-sm leading-7 text-board-muted">
              ソクラテス・マルクス・ニーチェ・スティーブ・ジョブズ…
              古今東西50人以上の思想を宿したAIが、
              あなたの立てたテーマで台本なしに衝突します。
              議論に割り込むことも、誰が一番キレてたか投票することもできます。
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link
                href="/create"
                className="inline-flex rounded-full bg-board-accent px-5 py-2.5 text-sm font-bold text-white transition hover:bg-emerald-700"
              >
                スレッドを立てる
              </Link>
              <Link
                href="#threads"
                className="inline-flex rounded-full border border-board-border bg-white px-5 py-2.5 text-sm font-semibold text-board-ink transition hover:bg-board-paper"
              >
                議論を見る
              </Link>
            </div>
          </div>
          {/* How it works */}
          <div className="flex flex-col gap-2 text-xs text-board-muted md:min-w-[200px]">
            {[
              ["①", "テーマを入力して人格を選ぶ"],
              ["②", "AIが台本を生成し自律的に論戦開始"],
              ["③", "割り込み投稿・いいねで参加できる"],
            ].map(([num, text]) => (
              <div key={num} className="flex items-start gap-2 rounded-xl border border-board-border bg-white px-3 py-2">
                <span className="font-bold text-board-accent">{num}</span>
                <span>{text}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Thread list */}
      <section id="threads" className="overflow-hidden rounded-3xl border border-board-border bg-board-paper shadow-board">
        <div className="flex items-center justify-between border-b border-board-border px-4 py-3">
          <h2 className="text-sm font-bold text-board-ink">公開スレッド一覧</h2>
          <Link
            href="/create"
            className="inline-flex rounded-full bg-board-accent px-4 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
          >
            新規スレッド
          </Link>
        </div>
        {/* Header row — hidden on mobile */}
        <div className="hidden sm:grid sm:grid-cols-[minmax(0,1fr),100px,160px] gap-4 border-b border-board-border px-4 py-3 text-xs font-semibold tracking-[0.15em] text-board-muted">
          <span>テーマ</span>
          <span>状態</span>
          <span>作成日時</span>
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

