import type { PostRecord } from "@/lib/api";

export function PostItem({ post }: { post: PostRecord }) {
  const time = new Date(post.created_at).toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit"
  });

  if (post.is_facilitator) {
    return (
      <div className="border-t border-board-border/70 bg-amber-50 px-4 py-3 text-sm italic text-board-muted">
        ── {post.content} ──
      </div>
    );
  }

  return (
    <article className="border-t border-board-border/70 px-4 py-3 transition hover:bg-white/60">
      <div className="mb-1 flex flex-wrap gap-3 text-sm text-board-muted">
        <span className="font-bold text-board-ink">{post.id}</span>
        <span className="font-bold text-board-accent">
          {post.display_name ?? "名無し"}
          {post.label ? <span className="ml-1 font-normal text-board-muted">（{post.label}）</span> : null}
        </span>
        <span>{time}</span>
        {post.focus_axis ? <span className="rounded bg-stone-200 px-2 py-0.5 text-xs">{post.focus_axis}</span> : null}
      </div>
      {post.reply_to ? (
        <div className="mb-1 text-sm text-sky-700 transition hover:underline">&gt;&gt;{post.reply_to}</div>
      ) : null}
      <p className="whitespace-pre-wrap text-sm leading-7 text-board-ink">{post.content}</p>
    </article>
  );
}

