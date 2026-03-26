import { LoginCard } from "@/components/LoginCard";
import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <main className="mx-auto max-w-xl">
      <LoginCard
        emailEnabled={isEmailAuthConfiguredFromEnv()}
        xEnabled={Boolean(process.env.TWITTER_CLIENT_ID && process.env.TWITTER_CLIENT_SECRET)}
      />
    </main>
  );
}
