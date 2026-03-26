type AuthSubjectInput = {
  userId?: string | null;
  email?: string | null;
};

export function resolveAuthSubject(input: AuthSubjectInput): string {
  const userId = (input.userId ?? "").trim();
  if (userId) {
    return userId;
  }
  const email = (input.email ?? "").trim().toLowerCase();
  if (email) {
    return `email:${email}`;
  }
  return "";
}
