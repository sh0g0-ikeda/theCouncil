"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { signIn, useSession } from "next-auth/react";
import { useParams } from "next/navigation";

import { PostList } from "@/components/PostList";
import { apiFetch, type PostRecord, type ThreadSummary } from "@/lib/api";
import { createThreadSocket } from "@/lib/websocket";

const LOADING_TELOPS = [
  "エージェントを呼び出しています",
  "エージェントがタイムマシンに乗りました",
  "まもなくエージェントが現代へ到着します",
  "エージェントが席に着きました",
];

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
  const [shared, setShared] = useState(false);
  const [quota, setQuota] = useState<{ remaining: number | null; limit: number | null } | null>(null);
  const [telopIndex, setTelopIndex] = useState(0);
  const [votes, setVotes] = useState<Record<string, number>>({});
  const [myVote, setMyVote] = useState<string | null>(null);

  useEffect(() => {
    if (!session?.user) return;
    apiFetch<{ remaining: number | null; limit: number | null }>("/api/threads/quota", {}, session.user)
      .then(setQuota)
      .catch(() => {});
  }, [session, shared]);
  const aiPostCount = posts.filter((p) => p.agent_id).length;
  const showTelop = aiPostCount === 0 && thread?.state === "running";
  const showVotes = aiPostCount >= 3;

  useEffect(() => {
    if (!showTelop) return;
    const id = setInterval(() => {
      setTelopIndex((i) => (i + 1) % LOADING_TELOPS.length);
    }, 8000);
    return () => clearInterval(id);
  }, [showTelop]);

  // Load votes (counts public, my_vote requires auth)
  useEffect(() => {
    apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
      `/api/threads/${threadId}/votes`
    ).then((r) => setVotes(r.counts)).catch(() => {});
  }, [threadId]);

  useEffect(() => {
    if (!session?.user) return;
    apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
      `/api/threads/${threadId}/votes/me`,
      {},
      session.user
    ).then((r) => { setVotes(r.counts); setMyVote(r.my_vote); }).catch(() => {});
  }, [threadId, session]);

  const castVote = async (agentId: string) => {
    if (!session?.user) { await signIn(); return; }
    const prev = { ...votes };
    const prevMy = myVote;
    // optimistic update
    setMyVote(agentId);
    setVotes((v) => {
      const next = { ...v };
      if (prevMy && prevMy !== agentId) next[prevMy] = Math.max(0, (next[prevMy] ?? 1) - 1);
      if (!prevMy || prevMy !== agentId) next[agentId] = (next[agentId] ?? 0) + 1;
      return next;
    });
    try {
      const r = await apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
        `/api/threads/${threadId}/votes`,
        { method: "POST", body: JSON.stringify({ agent_id: agentId }) },
        session.user
      );
      setVotes(r.counts);
      setMyVote(r.my_vote);
    } catch {
      setVotes(prev);
      setMyVote(prevMy);
    }
  };

  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeRef = useRef(true);
  const atBottomRef = useRef(true);
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
    const onScroll = () => {
      atBottomRef.current = window.innerHeight + window.scrollY >= document.body.scrollHeight - 200;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (atBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
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

  const shareOnX = async () => {
    const url = `${window.location.origin}/thread/${threadId}`;
    // Collect up to 2 unique agent display names from posts
    const agentNames: string[] = [];
    for (const p of posts) {
      if (p.agent_id && p.display_name && !agentNames.includes(p.display_name)) {
        agentNames.push(p.display_name);
        if (agentNames.length >= 2) break;
      }
    }
    const castLine = agentNames.length >= 2
      ? `${agentNames[0]}と${agentNames[1]}が\n`
      : agentNames.length === 1
      ? `${agentNames[0]}が\n`
      : "";
    const topic = thread?.topic ?? "";
    const text = `${castLine}「${topic}」について徹底討論！\n\nみんなの疑問を偉人AIが議論する掲示板！The Council`;
    const xUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
    window.open(xUrl, "_blank", "noopener,noreferrer");
    if (session?.user && !shared) {
      try {
        await apiFetch(`/api/threads/${threadId}/share`, { method: "POST" }, session.user);
        setShared(true);
      } catch {
        // bonus grant failure is non-critical
      }
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
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold text-board-ink">{thread.topic}</h1>
            <p className="mt-2 text-sm leading-6 text-board-muted">
              <span className="hidden sm:inline">{thread.agent_ids.join(" / ")} ・ </span>
              <span className="inline sm:hidden">{thread.agent_ids.length}人格 ・ </span>
              {posts.length} レス ・ {thread.state}
              {thread.current_phase != null && (
                <span className="ml-2 rounded-full bg-board-accent/10 px-2 py-0.5 text-xs font-medium text-board-accent">
                  {PHASE_LABELS[thread.current_phase] ?? `P${thread.current_phase}`}フェーズ
                </span>
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={shareOnX}
            className="flex shrink-0 items-center gap-1.5 rounded-full border border-board-border bg-white px-3 py-1.5 text-xs font-semibold text-board-ink transition hover:bg-black hover:text-white"
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.746l7.73-8.835L1.254 2.25H8.08l4.258 5.63 5.906-5.63Zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
            {shared ? "共有済み ✓" : (
              <>
                Xで共有するとスレッド作成回数+5！
                {quota && (
                  <span className="ml-1 opacity-70">
                    （今月残り{quota.remaining === null ? "∞" : quota.remaining}本）
                  </span>
                )}
              </>
            )}
          </button>
        </div>
      </section>

      {showTelop && (
        <div className="flex items-center gap-3 rounded-2xl border border-board-border bg-board-paper px-5 py-4 text-sm text-board-muted">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-board-accent border-t-transparent" />
          <span key={telopIndex} className="animate-pulse">{LOADING_TELOPS[telopIndex]}</span>
        </div>
      )}

      <PostList posts={posts} />

      {/* Vote panel — who was the sharpest? */}
      {showVotes && (() => {
        const agents = Array.from(
          new Map(
            posts
              .filter((p) => p.agent_id)
              .map((p) => [p.agent_id!, { id: p.agent_id!, name: p.display_name ?? p.agent_id! }])
          ).values()
        ).sort((a, b) => (votes[b.id] ?? 0) - (votes[a.id] ?? 0));
        return (
          <div className="rounded-2xl border border-board-border bg-board-paper p-4 shadow-board">
            <p className="mb-3 text-xs font-semibold text-board-muted tracking-wide">
              誰が一番キレてた？
            </p>
            <div className="flex flex-wrap gap-2">
              {agents.map((agent, i) => {
                const count = votes[agent.id] ?? 0;
                const isVoted = myVote === agent.id;
                const isTop = i === 0 && count > 0;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => castVote(agent.id)}
                    className={[
                      "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                      isVoted
                        ? "border-board-accent bg-board-accent text-white"
                        : "border-board-border bg-white text-board-ink hover:border-board-accent hover:text-board-accent",
                    ].join(" ")}
                  >
                    {isTop && <span>👑</span>}
                    <span>{agent.name}</span>
                    <span className="opacity-70">♡</span>
                    <span>{count}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Ad placeholder */}
      <div className="flex h-16 items-center justify-center rounded-2xl border border-dashed border-board-border bg-board-paper/50 text-xs text-board-muted">
        広告スペース
      </div>

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
