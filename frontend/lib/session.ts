import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { getSupabaseAdminClient } from "@/lib/supabase";

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
