"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useTransition } from "react";

import { apiFetch } from "@/lib/api";

export function AdminActionButton({
  path,
  body,
  label,
  className = "",
  confirmMessage
}: {
  path: string;
  body: Record<string, unknown>;
  label: string;
  className?: string;
  confirmMessage?: string;
}) {
  const router = useRouter();
  const { data: session } = useSession();
  const [isPending, startTransition] = useTransition();

  return (
    <button
      type="button"
      disabled={isPending}
      onClick={() => {
        if (confirmMessage && !window.confirm(confirmMessage)) {
          return;
        }
        startTransition(async () => {
          try {
            await apiFetch(
              path,
              {
                method: "POST",
                body: JSON.stringify(body)
              },
              session?.user
            );
            router.refresh();
          } catch (error) {
            window.alert(error instanceof Error ? error.message : "操作に失敗しました");
          }
        });
      }}
      className={`rounded border px-2 py-1 text-xs font-semibold transition ${className}`}
    >
      {isPending ? "..." : label}
    </button>
  );
}

