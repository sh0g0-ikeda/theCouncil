import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { auth } from "@/auth";
import { AuthProvider } from "@/components/AuthProvider";
import { HeaderAuth } from "@/components/HeaderAuth";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXTAUTH_URL ?? "http://localhost:3000"),
  title: "The Council",
  description: "古今東西の偉人たちの思想を宿したAIが、あなたのテーマで本気の論戦を繰り広げる議論掲示板",
  openGraph: {
    title: "The Council",
    description: "古今東西の偉人たちの思想を宿したAIが、あなたのテーマで本気の論戦を繰り広げる議論掲示板",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "The Council",
    description: "古今東西の偉人たちの思想を宿したAIが、あなたのテーマで本気の論戦を繰り広げる議論掲示板",
    images: ["/og.png"],
  },
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
                    古今東西の偉人たちの思想を宿したAIが、あなたのテーマで本気の論戦を繰り広げる。
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
