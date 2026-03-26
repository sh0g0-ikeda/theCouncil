from __future__ import annotations

from typing import Any, Protocol

from services.request_users import RequestUserLike, UserRequestRepository, resolve_internal_user_id


class ReportingRepository(UserRequestRepository, Protocol):
    async def create_report(
        self,
        *,
        thread_id: str,
        reporter_id: str,
        reason: str,
        post_id: int | None = None,
    ) -> dict[str, Any]: ...

    async def fetch_post(self, thread_id: str, post_id: int) -> dict[str, Any] | None: ...


async def submit_thread_report(
    *,
    db: ReportingRepository,
    thread: dict[str, Any],
    user: RequestUserLike,
    actor_internal_user_id: str | None,
    reason: str,
) -> dict[str, Any]:
    reporter_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=actor_internal_user_id,
    )
    return await db.create_report(
        thread_id=thread["id"],
        reporter_id=reporter_id,
        reason=reason,
        post_id=None,
    )


async def submit_post_report(
    *,
    db: ReportingRepository,
    thread: dict[str, Any],
    thread_id: str,
    post_id: int,
    user: RequestUserLike,
    actor_internal_user_id: str | None,
    reason: str,
) -> dict[str, Any] | None:
    post = await db.fetch_post(thread_id, post_id)
    if not post:
        return None
    reporter_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=actor_internal_user_id,
    )
    return await db.create_report(
        thread_id=thread["id"],
        post_id=post_id,
        reporter_id=reporter_id,
        reason=reason,
    )
