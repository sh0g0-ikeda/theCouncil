from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.deps import RequestUser, require_user
from db.client import DatabaseClient, get_db
from engine.discussion import agents, start_discussion
from engine.llm import generate_topic_tags, moderate_text
from policies import clamp_max_posts, max_agents, monthly_thread_limit
from rate_limit import limiter
from realtime import connection_manager

router = APIRouter(prefix="/api/threads", tags=["threads"])


class CreateThreadRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    agent_ids: list[str]
    visibility: str = "public"
    max_posts: int = Field(default=20, ge=10, le=40)


class SpeedRequest(BaseModel):
    mode: str


@router.post("/")
@limiter.limit("10/minute")
async def create_thread(
    request: Request,
    req: CreateThreadRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    agent_ids = list(dict.fromkeys(req.agent_ids))
    if not (2 <= len(agent_ids)):
        raise HTTPException(status_code=400, detail="参加人格は2体以上です")
    if req.visibility not in {"public", "private"}:
        raise HTTPException(status_code=400, detail="Invalid visibility")

    invalid_ids = [agent_id for agent_id in agent_ids if agent_id not in agents]
    if invalid_ids:
        raise HTTPException(status_code=400, detail="無効な人格IDが含まれています")

    if await moderate_text(req.topic):
        raise HTTPException(status_code=422, detail="テーマがモデレーションにより拒否されました")

    internal_id = await db.ensure_user_from_request(user.id, user.email)
    account = await db.fetch_user(internal_id)
    if not account:
        raise HTTPException(status_code=401, detail="User record was not provisioned")
    plan = account.get("plan", "free")
    if len(agent_ids) > max_agents(plan):
        raise HTTPException(status_code=400, detail=f"このプランで選択できる人格は最大{max_agents(plan)}体です")
    max_posts = clamp_max_posts(plan, req.max_posts)
    try:
        topic_tags = await generate_topic_tags(req.topic)
        thread = await db.create_thread(
            user_id=internal_id,
            topic=req.topic,
            topic_tags=topic_tags,
            agent_ids=agent_ids,
            visibility=req.visibility,
            max_posts=max_posts,
        )
    except ValueError as exc:
        if str(exc) == "free_plan_limit":
            limit = monthly_thread_limit(plan)
            raise HTTPException(status_code=403, detail=f"月間スレッド作成数の上限（{limit}本）に達しました") from exc
        if str(exc) == "user_banned":
            raise HTTPException(status_code=403, detail="BANされたユーザーです") from exc
        raise

    async def push(thread_id: str, post: dict[str, Any]) -> None:
        await connection_manager.broadcast(thread_id, post)

    await start_discussion(thread["id"], push)
    return thread


@router.get("/quota")
@limiter.limit("60/minute")
async def get_quota(
    request: Request,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    internal_id = await db.ensure_user_from_request(user.id, user.email)
    account = await db.fetch_user(internal_id)
    if not account:
        raise HTTPException(status_code=401, detail="User record was not provisioned")
    plan = account.get("plan", "free")
    used = account.get("monthly_thread_count", 0)
    limit = monthly_thread_limit(plan)
    return {
        "plan": plan,
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else max(0, limit - used),
    }


@router.get("/")
@limiter.limit("60/minute")
async def list_threads(
    request: Request,
    db: DatabaseClient = Depends(get_db),
    sort: str = Query(default="created_at"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await db.list_threads(sort=sort, limit=limit)


@router.post("/{thread_id}/share")
@limiter.limit("10/minute")
async def share_thread(
    request: Request,
    thread_id: str,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    thread = await db.fetch_thread(thread_id)
    if not thread or thread.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Thread not found")
    internal_id = await db.ensure_user_from_request(user.id, user.email)
    granted = await db.record_thread_share(internal_id, thread_id)
    return {"granted": granted, "bonus": 5 if granted else 0}


@router.get("/{thread_id}")
@limiter.limit("90/minute")
async def get_thread(
    request: Request,
    thread_id: str,
    db: DatabaseClient = Depends(get_db),
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
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.fetch_posts(thread_id)


@router.patch("/{thread_id}/speed")
@limiter.limit("30/minute")
async def set_speed(
    request: Request,
    thread_id: str,
    req: SpeedRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    if req.mode not in {"slow", "normal", "fast", "instant", "paused"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    thread = await db.fetch_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    internal_id = await db.ensure_user_from_request(user.id, user.email)
    if thread.get("user_id") != internal_id:
        raise HTTPException(status_code=403, detail="Thread owner only")

    await db.update_thread_speed(thread_id, req.mode)
    return {"ok": True}
