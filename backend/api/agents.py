from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from db.client import DatabaseClient, get_db
from engine.discussion import agents
from rate_limit import limiter

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/")
@limiter.limit("60/minute")
async def list_public_agents(
    request: Request,
    db: Annotated[DatabaseClient, Depends(get_db)],
) -> list[dict[str, Any]]:
    rows = await db.list_public_agents()
    if rows:
        return rows
    return [
        {
            "id": agent.id,
            "display_name": agent.display_name,
            "label": agent.label,
            "persona_json": agent.persona,
            "vector": agent.vector.as_list(),
        }
        for agent in agents.values()
    ]
