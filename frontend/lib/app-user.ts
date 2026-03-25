import { getSupabaseAdminClient } from "@/lib/supabase";

type SyncUserInput = {
  xId: string;
  email: string | null;
  role: "user" | "admin";
};

export async function syncAppUser(input: SyncUserInput) {
  const supabase = getSupabaseAdminClient();
  if (!supabase) {
    return;
  }

  await (supabase.from("users") as any).upsert(
    {
      x_id: input.xId,
      email: input.email,
      role: input.role
    },
    {
      onConflict: "x_id"
    }
  );
}
