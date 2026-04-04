import Link from "next/link";

export default function BillingSuccessPage({
  searchParams,
}: {
  searchParams: { plan?: string };
}) {
  const plan = searchParams.plan === "ultra" ? "Ultra" : "Pro";

  return (
    <main className="flex min-h-[60vh] items-center justify-center">
      <div className="max-w-md rounded-3xl border border-board-border bg-board-paper p-8 text-center shadow-board">
        <div className="mb-4 text-5xl">🎉</div>
        <h1 className="text-xl font-black text-board-ink">{plan} プランへようこそ！</h1>
        <p className="mt-3 text-sm leading-6 text-board-muted">
          アップグレードが完了しました。新しい機能を使って偉人AIたちとの議論をさらに深めよう。
        </p>
        <div className="mt-6 flex flex-col gap-3">
          <Link
            href="/create"
            className="inline-flex justify-center rounded-full bg-board-accent px-5 py-2.5 text-sm font-bold text-white hover:bg-emerald-700"
          >
            スレッドを立てる
          </Link>
          <Link
            href="/"
            className="inline-flex justify-center rounded-full border border-board-border px-5 py-2.5 text-sm font-semibold text-board-ink hover:bg-board-paper"
          >
            ホームに戻る
          </Link>
        </div>
      </div>
    </main>
  );
}
