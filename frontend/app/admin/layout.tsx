import Link from "next/link";
import type { ReactNode } from "react";

import { requireAdminUser } from "@/lib/session";

export const dynamic = "force-dynamic";

const links = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/threads", label: "Threads" },
  { href: "/admin/posts", label: "Posts" },
  { href: "/admin/reports", label: "Reports" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/agents", label: "Agents" }
];

export default async function AdminLayout({
  children
}: {
  children: ReactNode;
}) {
  await requireAdminUser();

  return (
    <div className="grid gap-4 lg:grid-cols-[220px,minmax(0,1fr)]">
      <aside className="h-fit rounded-3xl border border-board-border bg-board-paper p-4 shadow-board">
        <div className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-board-muted">
          Admin Console
        </div>
        <nav className="space-y-2">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="block rounded-2xl border border-transparent px-3 py-2 text-sm text-board-ink transition hover:border-board-border hover:bg-white"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div>{children}</div>
    </div>
  );
}
