from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from db.client import DatabaseClient, get_db

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    db: DatabaseClient = Depends(get_db),
) -> dict[str, str]:
    try:
        is_ready = await db.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if not is_ready:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
