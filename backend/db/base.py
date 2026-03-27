from __future__ import annotations

from typing import Any

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    asyncpg = None  # type: ignore[assignment]


class BaseDatabaseClient:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any | None = None

    async def connect(self) -> None:
        if asyncpg is None:
            raise RuntimeError("asyncpg is required to connect to the database")
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=5, statement_cache_size=0)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        return self._pool

    async def ping(self) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            value = await conn.fetchval("SELECT 1")
        return value == 1
