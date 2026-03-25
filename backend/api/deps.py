import os
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from db.client import DatabaseClient, get_db
from environment import is_production_environment


@dataclass(slots=True)
class RequestUser:
    id: str
    email: str | None = None
    role: str = "user"


def _build_request_user(auth_user: dict[str, Any]) -> RequestUser:
    return RequestUser(
        id=str(auth_user["sub"]),
        email=auth_user.get("email"),
        role=str(auth_user.get("role", "user")),
    )


async def optional_user(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
    x_user_email: str | None = Header(default=None, alias="x-user-email"),
) -> RequestUser | None:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user:
        return _build_request_user(auth_user)

    if os.getenv("ALLOW_INSECURE_DEV_AUTH") == "1" and x_user_id:
        if is_production_environment():
            raise HTTPException(status_code=500, detail="Insecure development auth is forbidden in production")
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=403, detail="Insecure development auth is localhost-only")
        return RequestUser(id=x_user_id, email=x_user_email)
    return None


async def require_user(
    user: RequestUser | None = Depends(optional_user),
) -> RequestUser:
    if user is not None:
        return user
    raise HTTPException(status_code=401, detail="Authentication required")


async def resolve_user_record(
    user: RequestUser,
    db: DatabaseClient,
) -> dict[str, Any] | None:
    return await db.resolve_request_user(user.id, user.email)


async def require_admin(
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> RequestUser:
    record = await resolve_user_record(user, db)
    if not record or record.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
