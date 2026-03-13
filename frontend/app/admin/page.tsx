import { apiFetch } from "@/lib/api";
import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function AdminDashboardPage() {
  const user = await requireAdminUser();
  let stats = {
    threads_today: 0,
    posts_today: 0,
    reports_today: 0,
    tokens_today: 0
  };

  try {
    stats = await apiFetch<typeof stats>("/api/admin/dashboard", {}, user);
  } catch {
    stats = {
      threads_today: 0,
      posts_today: 0,
      reports_today: 0,
      tokens_today: 0
    };
  }

  const cards = [
    { label: "今日のスレ数", value: stats.threads_today },
    { label: "今日のレス数", value: stats.posts_today },
    { label: "通報件数", value: stats.reports_today },
    { label: "生成トークン量", value: stats.tokens_today }
  ];

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
        <h1 className="text-xl font-bold text-board-ink">管理ダッシュボード</h1>
        <p className="mt-2 text-sm text-board-muted">当日集計。バックエンド未接続時は 0 表示になります。</p>
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <article key={card.label} className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
            <div className="text-xs uppercase tracking-[0.2em] text-board-muted">{card.label}</div>
            <div className="mt-3 text-3xl font-black text-board-ink">{card.value}</div>
          </article>
        ))}
      </section>
    </main>
  );
}
