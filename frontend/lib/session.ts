import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { getSupabaseAdminClient } from "@/lib/supabase";

export type SessionUser = {
  id: string;
  email?: string | null;
  role?: string;
  backendToken?: string;
};

export function sessionHeaders(user: SessionUser | null | undefined): HeadersInit {
  if (user?.backendToken) {
    return {
      Authorization: `Bearer ${user.backendToken}`
    };
  }
  if (!user?.id) {
    return {};
  }
  return {
    "x-user-id": user.id,
    "x-user-email": user.email ?? ""
  };
}

export async function getSessionUser() {
  const session = await auth();
  return session?.user ?? null;
}

export async function requireAdminUser() {
  const user = await getSessionUser();
  if (!user) redirect("/");

  if (user.role === "admin") return user;

  // Fallback: check Supabase directly (JWT role may not reflect manual DB changes)
  const supabase = getSupabaseAdminClient();
  if (supabase && user.id) {
    const { data } = await (supabase.from("users") as any)
      .select("role")
      .or(`id.eq.${user.id},x_id.eq.${user.id}`)
      .eq("role", "admin")
      .limit(1);
    if (data && data.length > 0) return user;
  }

  redirect("/");
}
