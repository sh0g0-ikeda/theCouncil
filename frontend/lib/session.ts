import { redirect } from "next/navigation";

import { auth } from "@/auth";

export type SessionUser = {
  id: string;
  email?: string | null;
  role?: string;
  backendToken?: string;
};

export function sessionHeaders(user: SessionUser | null | undefined): HeadersInit {
  if (user?.backendToken) {
    return {
      Authorization: `Bearer ${user.backendToken}`
    };
  }
  if (!user?.id) {
    return {};
  }
  return {
    "x-user-id": user.id,
    "x-user-email": user.email ?? ""
  };
}

export async function getSessionUser() {
  const session = await auth();
  return session?.user ?? null;
}

export async function requireAdminUser() {
  const user = await getSessionUser();
  if (!user || user.role !== "admin") {
    redirect("/");
  }
  return user;
}
