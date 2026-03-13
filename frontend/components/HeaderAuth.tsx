"use client";

import Link from "next/link";
import { signIn, signOut, useSession } from "next-auth/react";

export function HeaderAuth() {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return <div className="text-xs text-board-muted">認証確認中...</div>;
  }

  if (!session?.user) {
    return (
      <button
        type="button"
        onClick={() => signIn()}
        className="rounded border border-board-border bg-board-paper px-3 py-1 text-xs font-semibold text-board-ink hover:bg-white"
      >
        サインイン
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-board-muted">
      <span>{session.user.email ?? "ログイン中"}</span>
      {session.user.role === "admin" ? (
        <Link
          href="/admin"
          className="rounded border border-board-accent/50 px-2 py-1 text-board-accent hover:bg-board-accent hover:text-white"
        >
          Admin
        </Link>
      ) : null}
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/" })}
        className="rounded border border-board-border bg-board-paper px-3 py-1 font-semibold text-board-ink hover:bg-white"
      >
        サインアウト
      </button>
    </div>
  );
}

