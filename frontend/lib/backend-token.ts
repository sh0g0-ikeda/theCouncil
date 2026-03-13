import { SignJWT } from "jose";

const TOKEN_ISSUER = "the-council-frontend";
const TOKEN_AUDIENCE = "the-council-backend";

function getSecret() {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    throw new Error("NEXTAUTH_SECRET is required for backend bearer tokens");
  }
  return new TextEncoder().encode(secret);
}

export async function createBackendToken(input: {
  sub: string;
  email?: string | null;
  role: string;
}) {
  return new SignJWT({
    email: input.email ?? null,
    role: input.role
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(input.sub)
    .setIssuer(TOKEN_ISSUER)
    .setAudience(TOKEN_AUDIENCE)
    .setIssuedAt()
    .setExpirationTime("15m")
    .sign(getSecret());
}
