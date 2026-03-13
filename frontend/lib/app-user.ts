import { getSupabaseAdminClient } from "@/lib/supabase";

type SyncUserInput = {
  id: string;
  email: string | null;
  role: "user" | "admin";
};

export async function syncAppUser(input: SyncUserInput) {
  const supabase = getSupabaseAdminClient();
  if (!supabase) {
    return;
  }

  await supabase.from("users").upsert(
    {
      id: input.id,
      email: input.email,
      role: input.role
    },
    {
      onConflict: "id"
    }
  );
}

