from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.access import ensure_thread_writable, require_thread_access
from api.deps import RequestUser, require_user
from api.report_contracts import CreateReportRequest
from db.client import DatabaseClient, get_db
from engine.discussion import start_discussion
from engine.llm import moderate_text
from rate_limit import limiter
from realtime import connection_manager
from services.reporting import submit_post_report
from services.request_users import resolve_internal_user_id

router = APIRouter(prefix="/api/threads", tags=["posts"])


class CreatePostRequest(BaseModel):
    content: str = Field(min_length=1, max_length=220)
    reply_to: int | None = None


@router.post("/{thread_id}/posts")
@limiter.limit("20/minute")
async def create_post(
    request: Request,
    thread_id: str,
    req: CreatePostRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    ensure_thread_writable(access.thread)

    internal_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=access.actor.internal_user_id,
    )
    is_owner = access.thread.get("user_id") == internal_id
    if not is_owner and len(req.content.strip()) < 30:
        raise HTTPException(status_code=422, detail="Replies from non-owners must be at least 30 characters")

    if await moderate_text(req.content):
        raise HTTPException(status_code=422, detail="Post failed moderation")

    post = await db.save_post(
        thread_id=thread_id,
        agent_id=None,
        post_data={
            "content": req.content,
            "reply_to": req.reply_to,
            "stance": None,
            "focus_axis": None,
            "user_id": internal_id,
        },
        user_id=internal_id,
        is_facilitator=False,
        token_usage=0,
    )
    await connection_manager.broadcast(thread_id, post)

    if access.thread.get("state") == "running":

        async def push(tid: str, p: dict[str, Any]) -> None:
            await connection_manager.broadcast(tid, p)

        await start_discussion(thread_id, push)

    return post


@router.post("/{thread_id}/posts/{post_id}/reports")
@limiter.limit("20/minute")
async def create_post_report(
    request: Request,
    thread_id: str,
    post_id: int,
    req: CreateReportRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    report = await submit_post_report(
        db=db,
        thread=access.thread,
        thread_id=thread_id,
        post_id=post_id,
        user=user,
        actor_internal_user_id=access.actor.internal_user_id,
        reason=req.reason,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"ok": True, **report}
