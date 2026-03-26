import "server-only";

import { getSupabaseAdminClient } from "@/lib/supabase";

export type EmailLoginTokenRow = {
  email: string;
  token_hash: string;
  expires_at: string;
  created_at: string;
  attempt_count: number;
};

function getSupabase() {
  const supabase = getSupabaseAdminClient();
  if (!supabase) {
    throw new Error("Supabase admin client is not configured");
  }
  return supabase;
}

function getEmailAuthStoreError() {
  return new Error("Email login store is not ready. Run the latest database schema.");
}

export async function loadActiveEmailToken(email: string): Promise<EmailLoginTokenRow | null> {
  const supabase = getSupabase();
  const nowIso = new Date().toISOString();
  const { data, error } = await (supabase.from("email_login_tokens") as any)
    .select("email, token_hash, expires_at, created_at, attempt_count")
    .eq("email", email)
    .gt("expires_at", nowIso)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error && error.code !== "PGRST116") {
    throw getEmailAuthStoreError();
  }
  return (data as EmailLoginTokenRow | null) ?? null;
}

export async function purgeEmailTokens(email: string) {
  const supabase = getSupabase();
  const { error } = await (supabase.from("email_login_tokens") as any).delete().eq("email", email);
  if (error) {
    throw getEmailAuthStoreError();
  }
}

export async function storeEmailToken(email: string, tokenHash: string, expiresAt: string) {
  const supabase = getSupabase();
  const { error } = await (supabase.from("email_login_tokens") as any).insert({
    email,
    token_hash: tokenHash,
    expires_at: expiresAt,
    attempt_count: 0,
  });
  if (error) {
    throw getEmailAuthStoreError();
  }
}

export async function updateAttemptCount(email: string, tokenHash: string, attemptCount: number) {
  const supabase = getSupabase();
  const { error } = await (supabase.from("email_login_tokens") as any)
    .update({ attempt_count: attemptCount })
    .eq("email", email)
    .eq("token_hash", tokenHash);
  if (error) {
    throw getEmailAuthStoreError();
  }
}
