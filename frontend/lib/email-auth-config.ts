const REQUIRED_EMAIL_AUTH_ENV_KEYS = [
  "EMAIL_SERVER",
  "EMAIL_FROM",
  "NEXT_PUBLIC_SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY"
] as const;

export function isEmailAuthConfiguredFromEnv() {
  const hasTransport = REQUIRED_EMAIL_AUTH_ENV_KEYS.every((key) => Boolean(process.env[key]));
  const hasSecret = Boolean(process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET);
  return hasTransport && hasSecret;
}

