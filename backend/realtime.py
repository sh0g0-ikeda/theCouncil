from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, thread_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(thread_id, []).append(websocket)

    def disconnect(self, thread_id: str, websocket: WebSocket) -> None:
        if websocket in self.connections.get(thread_id, []):
            self.connections[thread_id].remove(websocket)
        if not self.connections.get(thread_id):
            self.connections.pop(thread_id, None)

    async def broadcast(self, thread_id: str, data: dict[str, Any]) -> None:
        for websocket in list(self.connections.get(thread_id, [])):
            try:
                await websocket.send_json(data)
            except Exception:
                logger.warning("dropping websocket during broadcast for thread %s", thread_id, exc_info=True)
                self.disconnect(thread_id, websocket)


connection_manager = ConnectionManager()
