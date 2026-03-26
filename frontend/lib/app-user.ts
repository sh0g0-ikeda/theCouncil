import { getSupabaseAdminClient } from "@/lib/supabase";

type SyncUserInput = {
  xId: string;
  email: string | null;
  role: "user" | "admin";
};

type StoredUser = {
  id: string;
  x_id: string | null;
  email: string | null;
  role: "user" | "admin";
};

async function findUserByXId(supabase: NonNullable<ReturnType<typeof getSupabaseAdminClient>>, xId: string) {
  const result = await (supabase.from("users") as any)
    .select("id, x_id, email, role")
    .eq("x_id", xId)
    .limit(1)
    .maybeSingle();
  if (result.error && result.error.code !== "PGRST116") {
    throw result.error;
  }
  return (result.data as StoredUser | null) ?? null;
}

async function findUserByEmail(supabase: NonNullable<ReturnType<typeof getSupabaseAdminClient>>, email: string) {
  const result = await (supabase.from("users") as any)
    .select("id, x_id, email, role")
    .eq("email", email)
    .limit(1)
    .maybeSingle();
  if (result.error && result.error.code !== "PGRST116") {
    throw result.error;
  }
  return (result.data as StoredUser | null) ?? null;
}

async function updateUser(
  supabase: NonNullable<ReturnType<typeof getSupabaseAdminClient>>,
  id: string,
  patch: Partial<StoredUser>
) {
  const { error } = await (supabase.from("users") as any).update(patch).eq("id", id);
  if (error) {
    throw error;
  }
}

async function insertUser(
  supabase: NonNullable<ReturnType<typeof getSupabaseAdminClient>>,
  user: Pick<StoredUser, "x_id" | "email" | "role">
) {
  const { error } = await (supabase.from("users") as any).insert(user);
  if (error) {
    throw error;
  }
}

export async function syncAppUser(input: SyncUserInput) {
  const supabase = getSupabaseAdminClient();
  if (!supabase) {
    return;
  }

  const userByXId = await findUserByXId(supabase, input.xId);
  if (userByXId?.id) {
    await updateUser(supabase, userByXId.id, {
      email: input.email ?? userByXId.email,
      role: input.role
    });
    return;
  }

  if (input.email) {
    const userByEmail = await findUserByEmail(supabase, input.email);
    if (userByEmail?.id) {
      await updateUser(supabase, userByEmail.id, {
        x_id: userByEmail.x_id ?? input.xId,
        email: input.email,
        role: input.role
      });
      return;
    }
  }

  await insertUser(supabase, {
    x_id: input.xId,
    email: input.email,
    role: input.role
  });
}
