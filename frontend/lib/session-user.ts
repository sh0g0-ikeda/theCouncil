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
