import { createHash, randomInt } from "node:crypto";

import nodemailer from "nodemailer";

import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";
import { getSupabaseAdminClient } from "@/lib/supabase";

const EMAIL_CODE_TTL_MS = 15 * 60 * 1000;
const EMAIL_REQUEST_COOLDOWN_MS = 60 * 1000;
const EMAIL_CODE_MAX_ATTEMPTS = 5;

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function isValidEmail(email: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function getEmailAuthSecret() {
  const secret = process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET;
  if (!secret) {
    throw new Error("NEXTAUTH_SECRET is required for email auth");
  }
  return secret;
}

function hashCode(email: string, code: string) {
  return createHash("sha256")
    .update(`${getEmailAuthSecret()}:${email}:${code}`)
    .digest("hex");
}

function getEmailTransport() {
  if (!process.env.EMAIL_SERVER || !process.env.EMAIL_FROM) {
    throw new Error("Email transport is not configured");
  }
  return nodemailer.createTransport(process.env.EMAIL_SERVER);
}

function getSupabase() {
  const supabase = getSupabaseAdminClient();
  if (!supabase) {
    throw new Error("Supabase admin client is not configured");
  }
  return supabase;
}

type EmailLoginTokenRow = {
  email: string;
  token_hash: string;
  expires_at: string;
  created_at: string;
  attempt_count: number;
};

function getEmailAuthStoreError() {
  return new Error("Email login store is not ready. Run the latest database schema.");
}

export function isEmailAuthConfigured() {
  return isEmailAuthConfiguredFromEnv();
}

async function loadActiveEmailToken(email: string): Promise<EmailLoginTokenRow | null> {
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

async function purgeEmailTokens(email: string) {
  const supabase = getSupabase();
  const { error } = await (supabase.from("email_login_tokens") as any).delete().eq("email", email);
  if (error) {
    throw getEmailAuthStoreError();
  }
}

async function storeEmailToken(email: string, code: string) {
  const supabase = getSupabase();
  const expiresAt = new Date(Date.now() + EMAIL_CODE_TTL_MS).toISOString();
  const { error } = await (supabase.from("email_login_tokens") as any).insert({
    email,
    token_hash: hashCode(email, code),
    expires_at: expiresAt,
    attempt_count: 0
  });
  if (error) {
    throw getEmailAuthStoreError();
  }
}

async function updateAttemptCount(email: string, tokenHash: string, attemptCount: number) {
  const supabase = getSupabase();
  const { error } = await (supabase.from("email_login_tokens") as any)
    .update({ attempt_count: attemptCount })
    .eq("email", email)
    .eq("token_hash", tokenHash);
  if (error) {
    throw getEmailAuthStoreError();
  }
}

export async function requestEmailLoginCode(emailInput: string) {
  const email = normalizeEmail(emailInput);
  if (!isValidEmail(email)) {
    throw new Error("Invalid email address");
  }

  const recentToken = await loadActiveEmailToken(email);

  if (recentToken?.created_at) {
    const createdAt = new Date(recentToken.created_at).getTime();
    if (Date.now() - createdAt < EMAIL_REQUEST_COOLDOWN_MS) {
      throw new Error("Please wait a minute before requesting another code.");
    }
  }

  await purgeEmailTokens(email);

  const code = String(randomInt(0, 1000000)).padStart(6, "0");
  await storeEmailToken(email, code);

  const transport = getEmailTransport();
  await transport.sendMail({
    from: process.env.EMAIL_FROM,
    to: email,
    subject: "The Council sign-in code",
    text: [
      "Use this code to sign in to The Council:",
      "",
      code,
      "",
      "This code expires in 15 minutes."
    ].join("\n")
  });
}

export async function consumeEmailLoginCode(emailInput: string, codeInput: string) {
  const email = normalizeEmail(emailInput);
  const code = codeInput.trim();
  if (!isValidEmail(email) || !/^\d{6}$/.test(code)) {
    return null;
  }

  const activeToken = await loadActiveEmailToken(email);
  if (!activeToken) {
    return null;
  }

  if ((activeToken.attempt_count ?? 0) >= EMAIL_CODE_MAX_ATTEMPTS) {
    await purgeEmailTokens(email);
    return null;
  }

  const tokenHash = hashCode(email, code);
  if (activeToken.token_hash != tokenHash) {
    const nextAttempts = (activeToken.attempt_count ?? 0) + 1;
    if (nextAttempts >= EMAIL_CODE_MAX_ATTEMPTS) {
      await purgeEmailTokens(email);
    } else {
      await updateAttemptCount(email, activeToken.token_hash, nextAttempts);
    }
    return null;
  }

  await purgeEmailTokens(email);

  return {
    id: `email:${email}`,
    email
  };
}
