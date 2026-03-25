from typing import Any

from fastapi import APIRouter, Depends, Request

from db.client import DatabaseClient, get_db
from rate_limit import limiter

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/")
@limiter.limit("60/minute")
async def list_public_agents(
    request: Request,
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.list_public_agents()
