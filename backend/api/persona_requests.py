from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import RequestUser, optional_user, require_admin
from db.client import DatabaseClient, get_db
from rate_limit import limiter

router = APIRouter(prefix="/api/persona-requests", tags=["persona_requests"])


class CreatePersonaRequest(BaseModel):
    person_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=10, max_length=1000)


class UpdatePersonaRequestStatus(BaseModel):
    status: str
    admin_note: str | None = None


@router.post("/")
@limiter.limit("5/minute")
async def create_persona_request(
    request: Request,
    body: CreatePersonaRequest,
    user: RequestUser | None = Depends(optional_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    row = await db.create_persona_request(
        requester_id=user.id if user else None,
        person_name=body.person_name,
        description=body.description,
    )
    return row


@router.get("/")
@limiter.limit("30/minute")
async def list_persona_requests(
    request: Request,
    db: DatabaseClient = Depends(get_db),
) -> list[dict[str, Any]]:
    return await db.list_persona_requests()


@router.patch("/{request_id}")
async def update_persona_request(
    request_id: int,
    body: UpdatePersonaRequestStatus,
    _admin: RequestUser = Depends(require_admin),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    if body.status not in {"pending", "in_progress", "done", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    row = await db.update_persona_request(request_id, body.status, body.admin_note)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row
