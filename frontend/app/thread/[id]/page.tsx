"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { signIn, useSession } from "next-auth/react";
import { useParams } from "next/navigation";

import { PostList } from "@/components/PostList";
import { SpeedControl } from "@/components/SpeedControl";
import { apiFetch, type PostRecord, type ThreadSummary } from "@/lib/api";
import { createThreadSocket } from "@/lib/websocket";

function mergePost(current: PostRecord[], incoming: PostRecord) {
  if (current.some((post) => post.id === incoming.id && post.created_at === incoming.created_at)) {
    return current;
  }
  return [...current, incoming];
}

export default function ThreadPage() {
  const params = useParams<{ id: string }>();
  const { data: session } = useSession();
  const [thread, setThread] = useState<ThreadSummary | null>(null);
  const isOwner = !!session?.user?.id && !!thread?.owner_x_id && session.user.id === thread.owner_x_id;
  const PHASE_LABELS: Record<number, string> = { 1: "定義", 2: "対立", 3: "深化", 4: "転換", 5: "収束" };
  const [posts, setPosts] = useState<PostRecord[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeRef = useRef(true);
  const threadId = useMemo(() => params.id, [params.id]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [nextThread, nextPosts] = await Promise.all([
          apiFetch<ThreadSummary>(`/api/threads/${threadId}`),
          apiFetch<PostRecord[]>(`/api/threads/${threadId}/posts`)
        ]);
        if (!active) {
          return;
        }
        setThread(nextThread);
        setPosts(nextPosts);
      } catch (err) {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : "読み込みに失敗しました");
      }
    };

    load();

    // Always poll every 2s — primary delivery mechanism
    pollRef.current = setInterval(async () => {
      if (!active) return;
      try {
        const np = await apiFetch<PostRecord[]>(`/api/threads/${threadId}/posts`);
        if (active) setPosts(np);
      } catch {}
    }, 2000);

    // WebSocket as bonus (instant delivery when it works)
    const socket = createThreadSocket(threadId);
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data && typeof data === "object" && "id" in data) {
          setPosts((current) => mergePost(current, data as PostRecord));
        }
      } catch {}
    };

    return () => {
      active = false;
      activeRef.current = false;
      socket.close();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [threadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [posts]);

  const submitPost = async () => {
    if (!session?.user) {
      await signIn();
      return;
    }
    if (!input.trim()) {
      return;
    }

    try {
      setSending(true);
      setError("");
      const newPost = await apiFetch<PostRecord>(
        `/api/threads/${threadId}/posts`,
        {
          method: "POST",
          body: JSON.stringify({
            content: input
          })
        },
        session.user
      );
      setPosts((current) => mergePost(current, newPost));
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "投稿に失敗しました");
    } finally {
      setSending(false);
    }
  };

  const updateSpeed = async (mode: string) => {
    if (!session?.user) {
      await signIn();
      return;
    }
    try {
      await apiFetch(
        `/api/threads/${threadId}/speed`,
        {
          method: "PATCH",
          body: JSON.stringify({ mode })
        },
        session.user
      );
      setThread((current) => (current ? { ...current, speed_mode: mode } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : "速度変更に失敗しました");
    }
  };

  if (!thread) {
    return (
      <main className="rounded-3xl border border-board-border bg-board-paper p-6 text-sm text-board-muted shadow-board">
        {error || "読み込み中..."}
      </main>
    );
  }

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <h1 className="text-xl font-bold text-board-ink">{thread.topic}</h1>
            <p className="mt-2 text-sm leading-6 text-board-muted">
              {thread.agent_ids.join(" / ")} ・ {posts.length} レス ・ 状態 {thread.state}
              {thread.current_phase != null && (
                <span className="ml-2 rounded-full bg-board-accent/10 px-2 py-0.5 text-xs font-medium text-board-accent">
                  {PHASE_LABELS[thread.current_phase] ?? `P${thread.current_phase}`}フェーズ
                </span>
              )}
            </p>
          </div>
          <SpeedControl value={thread.speed_mode ?? "normal"} onChange={updateSpeed} />
        </div>
      </section>

      <PostList posts={posts} />
      <div ref={bottomRef} />

      <section className="sticky bottom-4 rounded-3xl border border-board-border bg-board-paper/95 p-4 shadow-board backdrop-blur">
        <textarea
          className="h-28 w-full rounded-2xl border border-board-border bg-white px-4 py-3 text-sm leading-7 text-board-ink outline-none transition focus:border-board-accent"
          placeholder="議論に参加（100〜220文字）"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={400}
        />
        <div className="mt-3 flex items-center justify-between gap-4">
          <div className="text-xs text-board-muted">
            {input.length} / 220 {input.length < 30 && !isOwner ? "・30文字以上必要" : ""}
            {error ? <span className="ml-3 text-board-warn">{error}</span> : null}
          </div>
          <button
            type="button"
            onClick={submitPost}
            disabled={sending}
            className="rounded-full bg-board-accent px-5 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {sending ? "送信中..." : "書き込む"}
          </button>
        </div>
      </section>
    </main>
  );
}
