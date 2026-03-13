import NextAuth from "next-auth";
import TwitterProvider from "next-auth/providers/twitter";

import { createBackendToken } from "@/lib/backend-token";
import { syncAppUser } from "@/lib/app-user";

const adminEmails = new Set(
  (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
);

const providers: any[] = [];

if (process.env.TWITTER_CLIENT_ID && process.env.TWITTER_CLIENT_SECRET) {
  providers.push(
    TwitterProvider({
      clientId: process.env.TWITTER_CLIENT_ID,
      clientSecret: process.env.TWITTER_CLIENT_SECRET
    })
  );
}


export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  session: {
    strategy: "jwt"
  },
  trustHost: true,
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role = adminEmails.has((user.email ?? "").toLowerCase()) ? "admin" : "user";
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.id = String(token.sub ?? "");
        session.user.role = String(token.role ?? "user");
        if (token.sub) {
          try {
            session.user.backendToken = await createBackendToken({
              sub: String(token.sub),
              email: session.user.email ?? null,
              role: String(token.role ?? "user")
            });
          } catch {
            // non-fatal: backendToken will be undefined
          }
        }
      }
      return session;
    }
  },
  events: {
    async signIn({ user }) {
      if (!user.id) {
        return;
      }
      try {
        await syncAppUser({
          id: user.id,
          email: user.email ?? null,
          role: adminEmails.has((user.email ?? "").toLowerCase()) ? "admin" : "user"
        });
      } catch {
        // non-fatal
      }
    }
  }
});
