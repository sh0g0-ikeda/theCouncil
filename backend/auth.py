from __future__ import annotations

import os
from typing import Any

try:
    from jose import JWTError, jwt
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    JWTError = Exception  # type: ignore[assignment]
    jwt = None  # type: ignore[assignment]

TOKEN_ISSUER = "the-council-frontend"
TOKEN_AUDIENCE = "the-council-backend"


class AuthError(ValueError):
    pass


def _get_secret() -> str:
    secret = os.getenv("NEXTAUTH_SECRET")
    if not secret:
        raise AuthError("NEXTAUTH_SECRET is required for bearer token verification")
    return secret


def verify_backend_token(token: str) -> dict[str, Any]:
    if jwt is None:
        raise AuthError("python-jose is required for bearer token verification")
    try:
        payload = jwt.decode(
            token,
            _get_secret(),
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
        )
    except JWTError as exc:
        raise AuthError("Invalid bearer token") from exc

    if not payload.get("sub"):
        raise AuthError("Bearer token missing subject")
    return payload

