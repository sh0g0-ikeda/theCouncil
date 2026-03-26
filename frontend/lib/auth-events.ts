import { extractHandleFromProfile, isConfiguredAdmin } from "@/lib/admin-identities";
import { resolveAuthSubject } from "@/lib/auth-subject";
import { syncAppUser } from "@/lib/app-user";

export const authEvents = {
  async signIn(message: any) {
    const { user, profile } = message;
    const subject = resolveAuthSubject({
      userId: user.id ?? null,
      email: user.email ?? null,
    });
    if (!subject) {
      return;
    }
    try {
      await syncAppUser({
        xId: subject,
        email: user.email ?? null,
        role: isConfiguredAdmin({
          email: user.email ?? null,
          handle: extractHandleFromProfile(profile),
        })
          ? "admin"
          : "user",
      });
    } catch {
      // non-fatal
    }
  },
};
