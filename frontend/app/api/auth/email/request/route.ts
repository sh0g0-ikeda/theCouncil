import { NextResponse } from "next/server";

import { isEmailAuthConfiguredFromEnv } from "@/lib/email-auth-config";
import { requestEmailLoginCode } from "@/lib/email-auth";

export async function POST(request: Request) {
  if (!isEmailAuthConfiguredFromEnv()) {
    return NextResponse.json({ detail: "Email auth is not configured" }, { status: 503 });
  }

  try {
    const payload = (await request.json()) as { email?: string };
    if (!payload.email) {
      return NextResponse.json({ detail: "Email is required" }, { status: 400 });
    }
    await requestEmailLoginCode(payload.email);
    return NextResponse.json({ ok: true });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Failed to send email";
    return NextResponse.json({ detail }, { status: 400 });
  }
}
