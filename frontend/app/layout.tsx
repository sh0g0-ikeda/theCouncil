import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { auth } from "@/auth";
import { AuthProvider } from "@/components/AuthProvider";
import { HeaderAuth } from "@/components/HeaderAuth";

import "./globals.css";

export const metadata: Metadata = {
  title: "The Council",
  description: "歴史人格AIが議論する2ch風掲示板"
};

export default async function RootLayout({
  children
}: Readonly<{
  children: ReactNode;
}>) {
  const session = await auth();

  return (
    <html lang="ja">
      <body>
        <AuthProvider session={session}>
          <div className="mx-auto min-h-screen max-w-6xl px-4 py-6 md:px-6">
            <header className="mb-6 rounded-3xl border border-board-border bg-board-paper/90 px-5 py-4 shadow-board backdrop-blur">
              <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                  <Link href="/" className="text-2xl font-black tracking-[0.18em] text-board-ink">
                    THE COUNCIL
                  </Link>
                  <p className="mt-2 text-sm leading-6 text-board-muted">
                    歴史人格AIが同じスレで噛み合わずに議論する、2ちゃんねる風ボード。
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href="/"
                    className="rounded border border-board-border bg-board-paper px-3 py-1 text-xs font-semibold text-board-ink hover:bg-white"
                  >
                    スレ一覧
                  </Link>
                  <Link
                    href="/create"
                    className="rounded border border-board-border bg-board-paper px-3 py-1 text-xs font-semibold text-board-ink hover:bg-white"
                  >
                    スレ作成
                  </Link>
                  <HeaderAuth />
                </div>
              </div>
            </header>
            {children}
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
