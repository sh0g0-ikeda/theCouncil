function normalizeEmail(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function normalizeHandle(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase().replace(/^@/, "");
}

const adminEmails = new Set(
  (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((value) => normalizeEmail(value))
    .filter(Boolean)
);

const adminHandles = new Set(
  (process.env.ADMIN_X_HANDLES ?? "")
    .split(",")
    .map((value) => normalizeHandle(value))
    .filter(Boolean)
);

export function extractHandleFromProfile(profile: unknown): string {
  const candidate =
    (profile as any)?.data?.username ??
    (profile as any)?.screen_name ??
    "";
  return normalizeHandle(String(candidate));
}

export function isConfiguredAdmin(input: {
  email?: string | null;
  handle?: string | null;
}): boolean {
  return (
    adminEmails.has(normalizeEmail(input.email)) ||
    adminHandles.has(normalizeHandle(input.handle))
  );
}
