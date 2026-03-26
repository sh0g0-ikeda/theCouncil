from __future__ import annotations

from typing import Protocol


class RequestUserLike(Protocol):
    id: str
    email: str | None


class UserRequestRepository(Protocol):
    async def ensure_user_from_request(self, subject: str, email: str | None) -> str: ...


async def resolve_internal_user_id(
    db: UserRequestRepository,
    user: RequestUserLike,
    *,
    preferred_internal_user_id: str | None = None,
) -> str:
    if preferred_internal_user_id:
        return preferred_internal_user_id
    return await db.ensure_user_from_request(user.id, user.email)
