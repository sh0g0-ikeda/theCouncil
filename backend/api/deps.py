from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from db.client import DatabaseClient, get_db
from environment import is_production_environment


@dataclass(slots=True)
class RequestUser:
    id: str
    email: str | None = None
    role: str = "user"


async def require_user(
    request: Request,
    x_user_id: Annotated[str | None, Header(alias="x-user-id")] = None,
    x_user_email: Annotated[str | None, Header(alias="x-user-email")] = None,
) -> RequestUser:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user:
        return RequestUser(
            id=str(auth_user["sub"]),
            email=auth_user.get("email"),
            role=str(auth_user.get("role", "user")),
        )

    if os.getenv("ALLOW_INSECURE_DEV_AUTH") == "1" and x_user_id:
        if is_production_environment():
            raise HTTPException(status_code=500, detail="Insecure development auth is forbidden in production")
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=403, detail="Insecure development auth is localhost-only")
        return RequestUser(id=x_user_id, email=x_user_email)
    raise HTTPException(status_code=401, detail="Authentication required")


async def require_admin(
    user: Annotated[RequestUser, Depends(require_user)],
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> RequestUser:
    record = await db.fetch_user(user.id)
    if not record or record.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
