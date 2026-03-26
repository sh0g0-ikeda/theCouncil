import { extractHandleFromProfile, isConfiguredAdmin } from "@/lib/admin-identities";
import { resolveAuthSubject } from "@/lib/auth-subject";
import { createBackendToken } from "@/lib/backend-token";

export const authCallbacks = {
  async jwt({ token, user, profile }: any) {
    if (user) {
      const handle = extractHandleFromProfile(profile);
      token.sub = resolveAuthSubject({
        userId: user.id ?? null,
        email: user.email ?? null,
      });
      token.role = isConfiguredAdmin({
        email: user.email ?? null,
        handle,
      })
        ? "admin"
        : "user";
    }
    return token;
  },
  async session({ session, token }: any) {
    if (session.user) {
      session.user.id = String(token.sub ?? "");
      session.user.role = String(token.role ?? "user");
      if (token.sub) {
        try {
          session.user.backendToken = await createBackendToken({
            sub: String(token.sub),
            email: session.user.email ?? null,
            role: String(token.role ?? "user"),
          });
        } catch {
          // non-fatal: backendToken will be undefined
        }
      }
    }
    return session;
  },
};
