from __future__ import annotations

from datetime import date
from typing import Any

from db.shared import row_to_dict


class UserRepositoryMixin:
    async def fetch_user(self, user_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id::text = $1", user_id)
        return row_to_dict(row)

    async def fetch_user_by_x_id(self, x_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE x_id = $1", x_id)
        return row_to_dict(row)

    async def resolve_request_user(self, subject: str, email: str | None) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id::text = $1", subject)
            if row is None:
                row = await conn.fetchrow("SELECT * FROM users WHERE x_id = $1", subject)
            if row is None and email:
                row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        return row_to_dict(row)

    async def fetch_user_normalized(self, user_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._normalize_thread_quota(conn, user_id)

    async def ensure_user_from_request(self, x_id: str, email: str | None) -> str:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow("SELECT id FROM users WHERE id::text = $1", x_id)
            if existing is not None:
                if email:
                    await conn.execute("UPDATE users SET email = COALESCE($2, email) WHERE id::text = $1", x_id, email)
                return str(existing["id"])
            existing = await conn.fetchrow("SELECT id FROM users WHERE x_id = $1", x_id)
            if existing is not None:
                if email:
                    await conn.execute("UPDATE users SET email = COALESCE($2, email) WHERE id = $1", existing["id"], email)
                return str(existing["id"])
            if email:
                existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
                if existing is not None:
                    await conn.execute(
                        """
                        UPDATE users
                        SET x_id = COALESCE(x_id, $2),
                            email = COALESCE($1, email)
                        WHERE id = $3
                        """,
                        email,
                        x_id,
                        existing["id"],
                    )
                    return str(existing["id"])
            row = await conn.fetchrow(
                """
                INSERT INTO users (x_id, email)
                VALUES ($1, $2)
                ON CONFLICT (x_id) DO UPDATE
                SET email = COALESCE(EXCLUDED.email, users.email)
                RETURNING id
                """,
                x_id,
                email,
            )
        return str(row["id"])

    async def update_user_plan(self, user_id: str, plan: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET plan = $2 WHERE id::text = $1",
                user_id,
                plan,
            )

    async def update_user_stripe_customer(self, user_id: str, stripe_customer_id: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET stripe_customer_id = $2 WHERE id::text = $1",
                user_id,
                stripe_customer_id,
            )

    async def _normalize_thread_quota(self, conn: Any, user_id: str) -> dict[str, Any]:
        current_month = date.today().replace(day=1)
        row = await conn.fetchrow(
            """
            UPDATE users
            SET monthly_thread_count = CASE
                    WHEN thread_usage_month < $2 THEN 0
                    ELSE monthly_thread_count
                END,
                thread_usage_month = CASE
                    WHEN thread_usage_month < $2 THEN $2
                    ELSE thread_usage_month
                END
            WHERE id = $1
            RETURNING *
            """,
            user_id,
            current_month,
        )
        if row is None:
            raise ValueError("user_not_found")
        return row_to_dict(row) or {}
