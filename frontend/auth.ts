import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import TwitterProvider from "next-auth/providers/twitter";

import { extractHandleFromProfile, isConfiguredAdmin } from "@/lib/admin-identities";
import { resolveAuthSubject } from "@/lib/auth-subject";
import { createBackendToken } from "@/lib/backend-token";
import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";
import { consumeEmailLoginCode } from "@/lib/email-auth";
import { syncAppUser } from "@/lib/app-user";

const providers: any[] = [];

if (process.env.TWITTER_CLIENT_ID && process.env.TWITTER_CLIENT_SECRET) {
    providers.push(
        TwitterProvider({
            clientId: process.env.TWITTER_CLIENT_ID,
            clientSecret: process.env.TWITTER_CLIENT_SECRET
        })
    );
}

if (isEmailAuthConfiguredFromEnv()) {
  providers.push(
    CredentialsProvider({
      id: "email-code",
      name: "Email code",
      credentials: {
        email: { label: "Email", type: "email" },
        code: { label: "Code", type: "text" }
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.code) {
          return null;
        }
        return consumeEmailLoginCode(String(credentials.email), String(credentials.code));
      }
    })
  );
}


export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  pages: {
    signIn: "/login"
  },
  session: {
    strategy: "jwt"
  },
  trustHost: true,
  callbacks: {
    async jwt({ token, user, profile }) {
      if (user) {
        const handle = extractHandleFromProfile(profile);
        token.sub = resolveAuthSubject({
          userId: user.id ?? null,
          email: user.email ?? null
        });
        const isAdmin = isConfiguredAdmin({
          email: user.email ?? null,
          handle
        });
        token.role = isAdmin ? "admin" : "user";
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
    async signIn(message: any) {
      const { user, profile } = message;
      const subject = resolveAuthSubject({
        userId: user.id ?? null,
        email: user.email ?? null
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
            handle: extractHandleFromProfile(profile)
          })
            ? "admin"
            : "user"
        });
      } catch {
        // non-fatal
      }
    }
  }
});
