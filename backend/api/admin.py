from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import RequestUser, require_admin
from db.client import DatabaseClient, get_db
from engine.discussion import refresh_runtime_agent
from engine.rag import clear_chunk_cache
from rate_limit import limiter

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ThreadActionRequest(BaseModel):
    action: str = Field(pattern="^(hide|delete|lock|force_complete|set_public|set_private)$")


class PostActionRequest(BaseModel):
    action: str = Field(pattern="^(hide|delete|warn)$")


class ReportActionRequest(BaseModel):
    action: str = Field(pattern="^(resolved|dismissed|delete_post)$")


class UserActionRequest(BaseModel):
    action: str = Field(pattern="^(ban|unban|plan)$")
    plan: str | None = None


class AgentActionRequest(BaseModel):
    enabled: bool | None = None
    persona_json: dict[str, Any] | None = None
    refresh_rag: bool = False


@router.get("/dashboard")
@limiter.limit("30/minute")
async def dashboard(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, int]:
    return await db.dashboard_stats()


@router.get("/threads")
@limiter.limit("30/minute")
async def list_threads(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.admin_list_threads()


@router.post("/threads/{thread_id}")
@limiter.limit("30/minute")
async def thread_action(
    request: Request,
    thread_id: str,
    req: ThreadActionRequest,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    ok = await db.admin_thread_action(thread_id, req.action)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True}


@router.get("/posts")
@limiter.limit("30/minute")
async def list_posts(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.admin_list_posts()


@router.post("/posts/{thread_id}/{post_id}")
@limiter.limit("30/minute")
async def post_action(
    request: Request,
    thread_id: str,
    post_id: int,
    req: PostActionRequest,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    ok = await db.admin_post_action(thread_id, post_id, req.action)
    if not ok:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"ok": True}


@router.get("/reports")
@limiter.limit("30/minute")
async def list_reports(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.admin_list_reports()


@router.post("/reports/{report_id}")
@limiter.limit("30/minute")
async def report_action(
    request: Request,
    report_id: int,
    req: ReportActionRequest,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    ok = await db.admin_report_action(report_id, req.action)
    if not ok:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"ok": True}


@router.get("/users")
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.admin_list_users()


@router.post("/users/{user_id}")
@limiter.limit("30/minute")
async def user_action(
    request: Request,
    user_id: str,
    req: UserActionRequest,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    ok = await db.admin_user_action(user_id, req.action, req.plan)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@router.get("/agents")
@limiter.limit("30/minute")
async def list_agents(
    request: Request,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.admin_list_agents()


@router.post("/agents/{agent_id}")
@limiter.limit("30/minute")
async def update_agent(
    request: Request,
    agent_id: str,
    req: AgentActionRequest,
    _: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, bool]:
    ok = await db.admin_update_agent(agent_id, req.enabled, req.persona_json)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    await refresh_runtime_agent(agent_id, db)
    if req.refresh_rag:
        clear_chunk_cache(agent_id)
    return {"ok": True}
