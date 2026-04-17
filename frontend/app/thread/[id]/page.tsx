"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { signIn, useSession } from "next-auth/react";
import { useParams } from "next/navigation";

import { PostList } from "@/components/PostList";
import { ReportButton } from "@/components/ReportButton";
import { apiFetch, type PostRecord, type ThreadSummary } from "@/lib/api";
import { createThreadSocket } from "@/lib/websocket";

const LOADING_TELOPS = [
  "AIたちが議論の準備をしています",
  "AIたちが論点を整理しています",
  "発言の生成を待っています",
  "AIたちが本気で考えています",
];

const PHASE_LABELS: Record<number, string> = {
  1: "定義",
  2: "対立",
  3: "深掘り",
  4: "収束",
  5: "結論",
};

const THREAD_STATE_LABELS: Record<string, string> = {
  running: "進行中",
  paused: "一時停止",
  completed: "完了",
};

function mergePost(current: PostRecord[], incoming: PostRecord) {
  if (current.some((post) => post.id === incoming.id && post.created_at === incoming.created_at)) {
    return current;
  }
  return [...current, incoming];
}

function buildShareText(topic: string, names: string[]) {
  const castLine =
    names.length >= 2 ? `${names[0]} と ${names[1]}` : names.length === 1 ? `${names[0]}` : "";
  return `${castLine}\n「${topic}」について徹底討論！\n\nみんなの疑問を偉人AIが議論する掲示板 | The Council`;
}

function getShareButtonLabel(shared: boolean, shareBonusAvailable: boolean | undefined) {
  if (shared) return "共有済み ✓";
  if (shareBonusAvailable === false) return "Xでシェアする";
  return "Xでシェアして残り+5";
}

function getCompletedShareText() {
  return "議論をXでシェアすると、初回のみスレッド作成回数が5回分増えます。";
}

export default function ThreadPage() {
  const params = useParams<{ id: string }>();
  const { data: session } = useSession();
  const threadId = useMemo(() => params.id, [params.id]);
  const [thread, setThread] = useState<ThreadSummary | null>(null);
  const [posts, setPosts] = useState<PostRecord[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [shared, setShared] = useState(false);
  const [quota, setQuota] = useState<{
    remaining: number | null;
    limit: number | null;
    base_limit?: number | null;
    bonus?: number;
    share_bonus_available?: boolean;
  } | null>(null);
  const [telopIndex, setTelopIndex] = useState(0);
  const [votes, setVotes] = useState<Record<string, number>>({});
  const [myVote, setMyVote] = useState<string | null>(null);
  const [voteError, setVoteError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const atBottomRef = useRef(true);

  const isOwner = !!session?.user?.id && !!thread?.owner_x_id && session.user.id === thread.owner_x_id;
  const aiPostCount = posts.filter((post) => post.agent_id).length;
  const showTelop = aiPostCount === 0 && thread?.state === "running";
  const showVotes = aiPostCount >= 3;

  useEffect(() => {
    if (!session?.user) return;
    apiFetch<{
      remaining: number | null;
      limit: number | null;
      base_limit?: number | null;
      bonus?: number;
      share_bonus_available?: boolean;
    }>(
      "/api/threads/quota",
      {},
      session.user
    )
      .then(setQuota)
      .catch(() => {});
  }, [session, shared]);

  useEffect(() => {
    if (!showTelop) return;
    const id = setInterval(() => {
      setTelopIndex((index) => (index + 1) % LOADING_TELOPS.length);
    }, 8000);
    return () => clearInterval(id);
  }, [showTelop]);

  useEffect(() => {
    apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
      `/api/threads/${threadId}/votes`,
      {},
      session?.user
    )
      .then((result) => {
        setVotes(result.counts);
        setVoteError("");
      })
      .catch(() => {});
  }, [threadId, session?.user]);

  useEffect(() => {
    if (!session?.user) return;
    apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
      `/api/threads/${threadId}/votes/me`,
      {},
      session.user
    )
      .then((result) => {
        setVotes(result.counts);
        setMyVote(result.my_vote);
        setVoteError("");
      })
      .catch((loadError) => {
        setVoteError(loadError instanceof Error ? loadError.message : "投票情報の取得に失敗しました");
      });
  }, [threadId, session]);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const [nextThread, nextPosts] = await Promise.all([
          apiFetch<ThreadSummary>(`/api/threads/${threadId}`, {}, session?.user),
          apiFetch<PostRecord[]>(`/api/threads/${threadId}/posts`, {}, session?.user)
        ]);
        if (!active) return;
        setThread(nextThread);
        setPosts(nextPosts);
      } catch (loadError) {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "Failed to load thread");
      }
    };

    load();

    pollRef.current = setInterval(async () => {
      if (!active) return;
      try {
        const nextPosts = await apiFetch<PostRecord[]>(`/api/threads/${threadId}/posts`, {}, session?.user);
        if (active) setPosts(nextPosts);
      } catch {
        // non-fatal
      }
    }, 2000);

    const socket = createThreadSocket(threadId, session?.user?.backendToken);
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data && typeof data === "object" && "id" in data) {
          setPosts((current) => mergePost(current, data as PostRecord));
        }
      } catch {
        // ignore malformed realtime payload
      }
    };

    return () => {
      active = false;
      socket.close();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [threadId, session?.user]);

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

  const castVote = async (agentId: string) => {
    if (!session?.user) {
      await signIn(undefined, { callbackUrl: window.location.href });
      return;
    }

    const prevVotes = { ...votes };
    const prevMyVote = myVote;
    setVoteError("");
    setMyVote(agentId);
    setVotes((current) => {
      const next = { ...current };
      if (prevMyVote && prevMyVote !== agentId) {
        next[prevMyVote] = Math.max(0, (next[prevMyVote] ?? 1) - 1);
      }
      if (!prevMyVote || prevMyVote !== agentId) {
        next[agentId] = (next[agentId] ?? 0) + 1;
      }
      return next;
    });

    try {
      const result = await apiFetch<{ counts: Record<string, number>; my_vote: string | null }>(
        `/api/threads/${threadId}/votes`,
        {
          method: "POST",
          body: JSON.stringify({ agent_id: agentId })
        },
        session.user
      );
      setVotes(result.counts);
      setMyVote(result.my_vote);
      setVoteError("");
    } catch (voteSubmitError) {
      setVotes(prevVotes);
      setMyVote(prevMyVote);
      setVoteError(
        voteSubmitError instanceof Error ? voteSubmitError.message : "投票の送信に失敗しました"
      );
    }
  };

  const submitPost = async () => {
    if (!session?.user) {
      await signIn(undefined, { callbackUrl: window.location.href });
      return;
    }
    if (!input.trim()) return;

    try {
      setSending(true);
      setError("");
      const newPost = await apiFetch<PostRecord>(
        `/api/threads/${threadId}/posts`,
        {
          method: "POST",
          body: JSON.stringify({ content: input })
        },
        session.user
      );
      setPosts((current) => mergePost(current, newPost));
      setInput("");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to send post");
    } finally {
      setSending(false);
    }
  };

  const shareOnX = async () => {
    const url = `${window.location.origin}/thread/${threadId}`;
    const agentNames: string[] = [];
    for (const post of posts) {
      if (post.agent_id && post.display_name && !agentNames.includes(post.display_name)) {
        agentNames.push(post.display_name);
        if (agentNames.length >= 2) break;
      }
    }
    const text = buildShareText(thread?.topic ?? "", agentNames);
    const xUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
    window.open(xUrl, "_blank", "noopener,noreferrer");

    if (session?.user && !shared) {
      try {
        const result = await apiFetch<{
          granted: boolean;
          bonus: number;
          quota?: {
            remaining: number | null;
            limit: number | null;
            base_limit?: number | null;
            bonus?: number;
            share_bonus_available?: boolean;
          };
        }>(
          `/api/threads/${threadId}/share`,
          { method: "POST" },
          session.user
        );
        setShared(true);
        setQuota((current) => {
          if (result.quota) {
            return result.quota;
          }
          if (!current) return current;
          return {
            ...current,
            share_bonus_available: false,
            remaining:
              result.granted && current.remaining !== null
                ? current.remaining + result.bonus
                : current.remaining,
          };
        });
      } catch {
        // bonus failure is non-fatal
      }
    }
  };

  if (!thread) {
    return (
      <main className="rounded-3xl border border-board-border bg-board-paper p-6 text-sm text-board-muted shadow-board">
        {error || "スレッドを読み込み中..."}
      </main>
    );
  }

  const voteCandidates = thread.agent_ids
    .map((agentId) => {
      const latestPost = [...posts]
        .reverse()
        .find((post) => post.agent_id === agentId && post.display_name);
      return { id: agentId, name: latestPost?.display_name ?? agentId };
    })
    .sort((a, b) => (votes[b.id] ?? 0) - (votes[a.id] ?? 0));

  return (
    <main className="space-y-4">
      <section className="rounded-3xl border border-board-border bg-board-paper p-5 shadow-board">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold text-board-ink">{thread.topic}</h1>
            <p className="mt-2 text-sm leading-6 text-board-muted">
              <span className="hidden sm:inline">{thread.agent_ids.join(" / ")} / </span>
              <span className="inline sm:hidden">{thread.agent_ids.length} agents / </span>
              {posts.length} レス / {THREAD_STATE_LABELS[thread.state] ?? thread.state}
              {thread.current_phase != null ? (
                <span className="ml-2 rounded-full bg-board-accent/10 px-2 py-0.5 text-xs font-medium text-board-accent">
                  {PHASE_LABELS[thread.current_phase] ?? `P${thread.current_phase}`}フェーズ
                </span>
              ) : null}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ReportButton path={`/api/threads/${threadId}/reports`} user={session?.user} />
            <button
              type="button"
              onClick={shareOnX}
              className="flex shrink-0 items-center gap-1.5 rounded-full border border-board-border bg-white px-3 py-1.5 text-xs font-semibold text-board-ink transition hover:bg-black hover:text-white"
            >
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.746l7.73-8.835L1.254 2.25H8.08l4.258 5.63 5.906-5.63Zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
              {getShareButtonLabel(shared, quota?.share_bonus_available)}
              {!shared && quota ? <span className="ml-1 opacity-70">残り{quota.remaining === null ? "?" : quota.remaining}回</span> : null}
            </button>
          </div>
        </div>
      </section>

      {showTelop ? (
        <div className="flex items-center gap-3 rounded-2xl border border-board-border bg-board-paper px-5 py-4 text-sm text-board-muted">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-board-accent border-t-transparent" />
          <span key={telopIndex} className="animate-pulse">
            {LOADING_TELOPS[telopIndex]}
          </span>
        </div>
      ) : null}

      <PostList
        posts={posts}
        renderActions={(post) =>
          post.is_facilitator ? null : (
            <ReportButton path={`/api/threads/${threadId}/posts/${post.id}/reports`} user={session?.user} compact />
          )
        }
      />

      {thread.state === "completed" && (
        <div className="rounded-2xl border border-board-accent/30 bg-emerald-50 p-5">
          <p className="mb-1 text-sm font-bold text-board-ink">議論が完了しました</p>
          <p className="mb-4 text-xs text-board-muted">{getCompletedShareText()}</p>
          <button
            type="button"
            onClick={shareOnX}
            className="flex items-center gap-1.5 rounded-full bg-black px-4 py-2 text-xs font-semibold text-white transition hover:bg-zinc-700"
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-current" aria-hidden="true">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.746l7.73-8.835L1.254 2.25H8.08l4.258 5.63 5.906-5.63Zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
            {shared ? "共有済み ✓" : "Xでシェアする"}
          </button>
        </div>
      )}

      {showVotes
        ? (() => {
            return (
              <div className="rounded-2xl border border-board-border bg-board-paper p-4 shadow-board">
                <p className="mb-3 text-xs font-semibold tracking-wide text-board-muted">みんなの投票</p>
                <div className="flex flex-wrap gap-2">
                  {voteCandidates.map((agent, index) => {
                    const count = votes[agent.id] ?? 0;
                    const isVoted = myVote === agent.id;
                    const isTop = index === 0 && count > 0;
                    return (
                      <button
                        key={agent.id}
                        type="button"
                        onClick={() => castVote(agent.id)}
                        className={[
                          "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                          isVoted
                            ? "border-rose-400 bg-rose-50 text-rose-600"
                            : "border-board-border bg-white text-board-ink hover:border-rose-300 hover:text-rose-500"
                        ].join(" ")}
                      >
                        {isTop ? <span>TOP</span> : null}
                        <span>{agent.name}</span>
                        <span className={isVoted ? "text-rose-400" : "text-board-muted"}>・</span>
                        <span className="font-bold">{count}</span>
                      </button>
                    );
                  })}
                </div>
                {voteError ? <p className="mt-3 text-xs text-board-warn">{voteError}</p> : null}
              </div>
            );
          })()
        : null}

      <div className="flex h-16 items-center justify-center rounded-2xl border border-dashed border-board-border bg-board-paper/50 text-xs text-board-muted">
        ここまで
      </div>

      <div ref={bottomRef} />

      <section className="sticky bottom-4 rounded-3xl border border-board-border bg-board-paper/95 p-4 shadow-board backdrop-blur">
        <textarea
          className="h-28 w-full rounded-2xl border border-board-border bg-white px-4 py-3 text-sm leading-7 text-board-ink outline-none transition focus:border-board-accent"
          placeholder="意見を書き込む（30〜220文字）"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={220}
        />
        <div className="mt-3 flex items-center justify-between gap-4">
          <div className="text-xs text-board-muted">
            {input.length} / 220
            {input.length < 30 && !isOwner ? <span className="ml-2">※30文字以上必要です</span> : null}
            {error ? <span className="ml-3 text-board-warn">{error}</span> : null}
          </div>
          <button
            type="button"
            onClick={submitPost}
            disabled={sending}
            className="rounded-full bg-board-accent px-5 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {sending ? "送信中..." : "投稿する"}
          </button>
        </div>
      </section>
    </main>
  );
}
