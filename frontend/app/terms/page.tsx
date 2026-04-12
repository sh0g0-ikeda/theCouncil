import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

async function loadTermsText() {
  const filePath = path.join(process.cwd(), "..", "rule.md");
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return "利用規約を読み込めませんでした。";
  }
}

export default async function TermsPage() {
  const termsText = await loadTermsText();

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <h1 className="text-xl font-bold text-board-ink">利用規約</h1>
        <p className="mt-2 text-sm leading-6 text-board-muted">
          このページはリポジトリ直下の <code>rule.md</code> を表示しています。
        </p>
      </section>

      <section className="rounded-3xl border border-board-border bg-board-paper p-6 shadow-board">
        <pre className="whitespace-pre-wrap break-words text-sm leading-7 text-board-ink">{termsText}</pre>
      </section>
    </main>
  );
}
