import "server-only";

import { createHash, randomInt } from "node:crypto";

import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";
import {
  loadActiveEmailToken,
  purgeEmailTokens,
  storeEmailToken,
  updateAttemptCount,
} from "@/lib/email-auth-store";
import { sendEmailLoginCode } from "@/lib/email-auth-mailer";

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

export function isEmailAuthConfigured() {
  return isEmailAuthConfiguredFromEnv();
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
  await storeEmailToken(email, hashCode(email, code), new Date(Date.now() + EMAIL_CODE_TTL_MS).toISOString());
  await sendEmailLoginCode({ email, code });
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
