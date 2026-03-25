from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from api.deps import RequestUser, resolve_user_record
from db.client import DatabaseClient


@dataclass(slots=True)
class RequestActor:
    user: RequestUser | None
    record: dict[str, Any] | None
    internal_user_id: str | None
    is_admin: bool


@dataclass(slots=True)
class ThreadAccess:
    thread: dict[str, Any]
    actor: RequestActor

    @property
    def is_owner(self) -> bool:
        owner_id = self.thread.get("user_id")
        return bool(owner_id and self.actor.internal_user_id == owner_id)


def _thread_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Thread not found")


async def resolve_request_actor(
    user: RequestUser | None,
    db: DatabaseClient,
) -> RequestActor:
    if user is None:
        return RequestActor(user=None, record=None, internal_user_id=None, is_admin=False)
    record = await resolve_user_record(user, db)
    internal_user_id = str(record["id"]) if record else None
    is_admin = bool(record and record.get("role") == "admin")
    return RequestActor(
        user=user,
        record=record,
        internal_user_id=internal_user_id,
        is_admin=is_admin,
    )


async def require_thread_access(
    thread_id: str,
    db: DatabaseClient,
    user: RequestUser | None = None,
) -> ThreadAccess:
    thread = await db.fetch_thread(thread_id)
    if not thread or thread.get("deleted_at"):
        raise _thread_not_found()

    actor = await resolve_request_actor(user, db)
    access = ThreadAccess(thread=thread, actor=actor)

    if thread.get("hidden_at") and not (actor.is_admin or access.is_owner):
        raise _thread_not_found()
    if thread.get("visibility") == "private" and not (access.is_owner or actor.is_admin):
        raise _thread_not_found()
    return access


def ensure_thread_writable(thread: dict[str, Any]) -> None:
    if thread.get("locked_at"):
        raise HTTPException(status_code=423, detail="Thread is locked")
