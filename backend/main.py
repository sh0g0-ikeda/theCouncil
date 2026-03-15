from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from auth import AuthError, verify_backend_token
from api.admin import router as admin_router
from api.agents import router as agents_router
from api.posts import router as posts_router
from api.threads import router as threads_router
from db.client import get_db
from environment import is_production_environment
from engine.discussion import agents, load_agents
from rate_limit import limiter
from realtime import connection_manager

logger = logging.getLogger(__name__)


def _load_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS")
    if not raw:
        return ["http://localhost:3000"]
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise RuntimeError("Wildcard CORS_ORIGINS is not allowed")
    return origins


app = FastAPI(title="The Council API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_cors_origins(),
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(agents_router)
app.include_router(threads_router)
app.include_router(posts_router)
app.include_router(admin_router)


@app.middleware("http")
async def bearer_auth_middleware(request: Request, call_next):
    request.state.auth_user = None
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"detail": "Invalid authorization header"}, status_code=401)
        try:
            request.state.auth_user = verify_backend_token(token)
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


async def _ws_keepalive(websocket: WebSocket, interval: int = 25) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await websocket.send_json({"type": "ping"})
    except Exception:
        pass


@app.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str) -> None:
    await connection_manager.connect(thread_id, websocket)
    keepalive = asyncio.create_task(_ws_keepalive(websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("client disconnected from thread %s", thread_id)
    except Exception:
        logger.warning("unexpected error in ws_endpoint thread=%s", thread_id, exc_info=True)
    finally:
        keepalive.cancel()
        connection_manager.disconnect(thread_id, websocket)


@app.on_event("startup")
async def startup() -> None:
    if is_production_environment() and os.getenv("ALLOW_INSECURE_DEV_AUTH") == "1":
        raise RuntimeError("ALLOW_INSECURE_DEV_AUTH must not be enabled in production")
    await get_db().connect()
    load_agents()
    try:
        await get_db().sync_agents_from_disk([a.persona for a in agents.values()])
    except Exception:
        logger.warning("agent DB sync failed at startup", exc_info=True)


@app.on_event("shutdown")
async def shutdown() -> None:
    await get_db().close()
