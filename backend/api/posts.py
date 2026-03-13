from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.deps import RequestUser, require_user
from backend.db.client import DatabaseClient, get_db
from backend.engine.llm import moderate_text, validate_reply_length
from backend.rate_limit import limiter
from backend.realtime import connection_manager

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
    user: Annotated[RequestUser, Depends(require_user)],
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> dict[str, Any]:
    thread = await db.fetch_thread(thread_id)
    if not thread or thread.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.get("locked_at"):
        raise HTTPException(status_code=423, detail="Thread is locked")
    if not validate_reply_length(req.content):
        raise HTTPException(status_code=422, detail="投稿は100〜220文字で入力してください")
    if await moderate_text(req.content):
        raise HTTPException(status_code=422, detail="投稿がモデレーションにより拒否されました")

    await db.ensure_user_from_request(user.id, user.email)
    post = await db.save_post(
        thread_id=thread_id,
        agent_id=None,
        post_data={
            "content": req.content,
            "reply_to": req.reply_to,
            "stance": None,
            "focus_axis": None,
            "user_id": user.id,
        },
        user_id=user.id,
        is_facilitator=False,
        token_usage=0,
    )
    await connection_manager.broadcast(thread_id, post)
    return post
