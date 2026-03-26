from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.access import require_thread_access
from api.deps import RequestUser, optional_user, require_user
from api.report_contracts import CreateReportRequest
from db.client import DatabaseClient, get_db
from engine.discussion import start_discussion
from engine.llm import generate_topic_tags, moderate_text
from policies import clamp_max_posts, max_agents, monthly_thread_limit
from rate_limit import limiter
from realtime import connection_manager
from services.reporting import submit_thread_report
from services.request_users import resolve_internal_user_id

router = APIRouter(prefix="/api/threads", tags=["threads"])


class CreateThreadRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    agent_ids: list[str]
    visibility: str = "public"
    max_posts: int = Field(default=20, ge=10, le=200)


class SpeedRequest(BaseModel):
    mode: str


class VoteRequest(BaseModel):
    agent_id: str


@router.post("/")
@limiter.limit("10/minute")
async def create_thread(
    request: Request,
    req: CreateThreadRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    agent_ids = list(dict.fromkeys(req.agent_ids))
    if len(agent_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 agents are required")
    if req.visibility not in {"public", "private"}:
        raise HTTPException(status_code=400, detail="Invalid visibility")

    enabled_agent_ids = set(await db.list_enabled_agent_ids())
    if not enabled_agent_ids:
        raise HTTPException(status_code=503, detail="No enabled agents available")

    invalid_ids = [agent_id for agent_id in agent_ids if agent_id not in enabled_agent_ids]
    if invalid_ids:
        raise HTTPException(status_code=400, detail="One or more agent IDs are invalid")

    if await moderate_text(req.topic):
        raise HTTPException(status_code=422, detail="Topic failed moderation")

    internal_id = await resolve_internal_user_id(db, user)
    account = await db.fetch_user(internal_id)
    if not account:
        raise HTTPException(status_code=401, detail="User record was not provisioned")

    plan = account.get("plan", "free")
    allowed_agents = max_agents(plan)
    if len(agent_ids) > allowed_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Your plan allows up to {allowed_agents} agents",
        )

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
            raise HTTPException(
                status_code=403,
                detail=f"Monthly thread limit reached ({limit})",
            ) from exc
        if str(exc) == "user_banned":
            raise HTTPException(status_code=403, detail="This account is banned") from exc
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
    internal_id = await resolve_internal_user_id(db, user)
    account = await db.fetch_user_normalized(internal_id)
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
    access = await require_thread_access(thread_id, db, user)
    internal_id = await resolve_internal_user_id(db, user)
    granted = await db.record_thread_share(internal_id, access.thread["id"])
    return {"granted": granted, "bonus": 5 if granted else 0}


@router.post("/{thread_id}/reports")
@limiter.limit("20/minute")
async def create_thread_report(
    request: Request,
    thread_id: str,
    req: CreateReportRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    report = await submit_thread_report(
        db=db,
        thread=access.thread,
        user=user,
        actor_internal_user_id=access.actor.internal_user_id,
        reason=req.reason,
    )
    return {"ok": True, **report}


@router.get("/{thread_id}/votes")
@limiter.limit("60/minute")
async def get_votes(
    request: Request,
    thread_id: str,
    user: RequestUser | None = Depends(optional_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    await require_thread_access(thread_id, db, user)
    counts = await db.fetch_thread_votes(thread_id)
    return {"counts": counts, "my_vote": None}


@router.get("/{thread_id}/votes/me")
@limiter.limit("60/minute")
async def get_my_vote(
    request: Request,
    thread_id: str,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    internal_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=access.actor.internal_user_id,
    )
    my_vote = await db.fetch_user_thread_vote(thread_id, internal_id)
    counts = await db.fetch_thread_votes(thread_id)
    return {"counts": counts, "my_vote": my_vote}


@router.post("/{thread_id}/votes")
@limiter.limit("20/minute")
async def cast_vote(
    request: Request,
    thread_id: str,
    req: VoteRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    if req.agent_id not in (access.thread.get("agent_ids") or []):
        raise HTTPException(status_code=400, detail="Agent is not a participant in this thread")

    internal_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=access.actor.internal_user_id,
    )
    await db.upsert_thread_vote(thread_id, internal_id, req.agent_id)
    counts = await db.fetch_thread_votes(thread_id)
    return {"counts": counts, "my_vote": req.agent_id}


@router.get("/{thread_id}")
@limiter.limit("90/minute")
async def get_thread(
    request: Request,
    thread_id: str,
    user: RequestUser | None = Depends(optional_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    access = await require_thread_access(thread_id, db, user)
    return access.thread


@router.get("/{thread_id}/posts")
@limiter.limit("90/minute")
async def get_posts(
    request: Request,
    thread_id: str,
    user: RequestUser | None = Depends(optional_user),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    await require_thread_access(thread_id, db, user)
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

    access = await require_thread_access(thread_id, db, user)
    internal_id = await resolve_internal_user_id(
        db,
        user,
        preferred_internal_user_id=access.actor.internal_user_id,
    )
    if access.thread.get("user_id") != internal_id:
        raise HTTPException(status_code=403, detail="Thread owner only")

    await db.update_thread_speed(thread_id, req.mode)
    return {"ok": True}
