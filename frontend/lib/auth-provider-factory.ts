import CredentialsProvider from "next-auth/providers/credentials";
import TwitterProvider from "next-auth/providers/twitter";

import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";
import { consumeEmailLoginCode } from "@/lib/email-auth";

export function buildAuthProviders() {
  const providers: any[] = [];

  if (process.env.TWITTER_CLIENT_ID && process.env.TWITTER_CLIENT_SECRET) {
    providers.push(
      TwitterProvider({
        clientId: process.env.TWITTER_CLIENT_ID,
        clientSecret: process.env.TWITTER_CLIENT_SECRET,
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
          code: { label: "Code", type: "text" },
        },
        async authorize(credentials) {
          if (!credentials?.email || !credentials?.code) {
            return null;
          }
          return consumeEmailLoginCode(String(credentials.email), String(credentials.code));
        },
      })
    );
  }

  return providers;
}
