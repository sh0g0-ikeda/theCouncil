import type { NextAuthConfig } from "next-auth";

import { authCallbacks } from "@/lib/auth-callbacks";
import { authEvents } from "@/lib/auth-events";
import { buildAuthProviders } from "@/lib/auth-provider-factory";

export const authOptions = {
  providers: buildAuthProviders(),
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
  },
  trustHost: true,
  callbacks: authCallbacks,
  events: authEvents,
} satisfies NextAuthConfig;
