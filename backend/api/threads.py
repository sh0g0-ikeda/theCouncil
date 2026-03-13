from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.api.deps import RequestUser, require_user
from backend.db.client import DatabaseClient, get_db
from backend.engine.discussion import agents, start_discussion
from backend.engine.llm import generate_topic_tags, moderate_text
from backend.policies import clamp_max_posts
from backend.rate_limit import limiter
from backend.realtime import connection_manager

router = APIRouter(prefix="/api/threads", tags=["threads"])


class CreateThreadRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    agent_ids: list[str]
    visibility: str = "public"
    max_posts: int = Field(default=50, ge=10, le=200)


class SpeedRequest(BaseModel):
    mode: str


@router.post("/")
@limiter.limit("10/minute")
async def create_thread(
    request: Request,
    req: CreateThreadRequest,
    user: Annotated[RequestUser, Depends(require_user)],
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> dict[str, Any]:
    agent_ids = list(dict.fromkeys(req.agent_ids))
    if not (3 <= len(agent_ids) <= 8):
        raise HTTPException(status_code=400, detail="参加人格は3〜8体です")
    if req.visibility not in {"public", "private"}:
        raise HTTPException(status_code=400, detail="Invalid visibility")

    invalid_ids = [agent_id for agent_id in agent_ids if agent_id not in agents]
    if invalid_ids:
        raise HTTPException(status_code=400, detail="無効な人格IDが含まれています")

    if await moderate_text(req.topic):
        raise HTTPException(status_code=422, detail="テーマがモデレーションにより拒否されました")

    await db.ensure_user_from_request(user.id, user.email)
    account = await db.fetch_user(user.id)
    if not account:
        raise HTTPException(status_code=401, detail="User record was not provisioned")
    max_posts = clamp_max_posts(account.get("plan", "free"), req.max_posts)
    try:
        topic_tags = await generate_topic_tags(req.topic)
        thread = await db.create_thread(
            user_id=user.id,
            topic=req.topic,
            topic_tags=topic_tags,
            agent_ids=agent_ids,
            visibility=req.visibility,
            max_posts=max_posts,
        )
    except ValueError as exc:
        if str(exc) == "free_plan_limit":
            raise HTTPException(status_code=403, detail="無料プランは月5スレッドまでです") from exc
        if str(exc) == "user_banned":
            raise HTTPException(status_code=403, detail="BANされたユーザーです") from exc
        raise

    async def push(thread_id: str, post: dict[str, Any]) -> None:
        await connection_manager.broadcast(thread_id, post)

    await start_discussion(thread["id"], push)
    return thread


@router.get("/")
@limiter.limit("60/minute")
async def list_threads(
    request: Request,
    db: Annotated[DatabaseClient, Depends(get_db)],
    sort: str = Query(default="created_at"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await db.list_threads(sort=sort, limit=limit)


@router.get("/{thread_id}")
@limiter.limit("90/minute")
async def get_thread(
    request: Request,
    thread_id: str,
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> dict[str, Any]:
    thread = await db.fetch_thread(thread_id)
    if not thread or thread.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/{thread_id}/posts")
@limiter.limit("90/minute")
async def get_posts(
    request: Request,
    thread_id: str,
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> list[dict[str, Any]]:
    return await db.fetch_posts(thread_id)


@router.patch("/{thread_id}/speed")
@limiter.limit("30/minute")
async def set_speed(
    request: Request,
    thread_id: str,
    req: SpeedRequest,
    user: Annotated[RequestUser, Depends(require_user)],
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> dict[str, bool]:
    if req.mode not in {"normal", "fast", "instant", "paused"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    thread = await db.fetch_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Thread owner only")

    await db.update_thread_speed(thread_id, req.mode)
    return {"ok": True}
