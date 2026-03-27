from __future__ import annotations

import json
from typing import Any

from db.shared import row_to_dict


class ThreadRepositoryMixin:
    async def create_thread(
        self,
        user_id: str,
        topic: str,
        topic_tags: list[str],
        agent_ids: list[str],
        visibility: str,
        max_posts: int,
    ) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                user = await self._normalize_thread_quota(conn, user_id)
                if user["is_banned"]:
                    raise ValueError("user_banned")
                from policies import monthly_thread_limit

                _limit = monthly_thread_limit(user.get("plan", "free"))
                if _limit is not None and user["monthly_thread_count"] >= _limit:
                    raise ValueError("free_plan_limit")

                row = await conn.fetchrow(
                    """
                    INSERT INTO threads (user_id, topic, topic_tags, agent_ids, visibility, max_posts)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    user_id,
                    topic,
                    topic_tags,
                    agent_ids,
                    visibility,
                    max_posts,
                )
                await conn.execute(
                    "UPDATE users SET monthly_thread_count = monthly_thread_count + 1 WHERE id = $1",
                    user_id,
                )
                await conn.execute(
                    """
                    DELETE FROM threads
                    WHERE id IN (
                        SELECT id FROM threads
                        WHERE deleted_at IS NULL
                        ORDER BY created_at DESC
                        OFFSET 200
                    )
                    """
                )
        return row_to_dict(row) or {}

    async def list_threads(self, sort: str, limit: int) -> list[dict[str, Any]]:
        sort_columns = {
            "created_at": "t.created_at DESC",
            "posts": "post_count DESC, t.created_at DESC",
        }
        order_clause = sort_columns.get(sort, sort_columns["created_at"])
        query = f"""
            SELECT
                t.*,
                COALESCE(COUNT(p.id), 0)::int AS post_count
            FROM threads t
            LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL AND p.hidden_at IS NULL
            WHERE t.visibility = 'public' AND t.deleted_at IS NULL AND t.hidden_at IS NULL
            GROUP BY t.id
            ORDER BY {order_clause}
            LIMIT $1
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
        return [row_to_dict(row) or {} for row in rows]

    async def fetch_thread(self, thread_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    t.*,
                    COALESCE(COUNT(p.id), 0)::int AS post_count,
                    u.x_id AS owner_x_id
                FROM threads t
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL AND p.hidden_at IS NULL
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.id = $1
                GROUP BY t.id, u.x_id
                """,
                thread_id,
            )
        return row_to_dict(row)

    async def fetch_thread_state(self, thread_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, state, speed_mode, max_posts, current_phase,
                       agent_ids, topic, topic_tags,
                       user_id, visibility, hidden_at, locked_at, deleted_at, created_at
                FROM threads
                WHERE id = $1
                """,
                thread_id,
            )
        return row_to_dict(row)

    async def fetch_posts(self, thread_id: str) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    p.*,
                    a.display_name,
                    a.label
                FROM posts p
                LEFT JOIN agents a ON a.id = p.agent_id
                WHERE p.thread_id = $1 AND p.deleted_at IS NULL AND p.hidden_at IS NULL
                ORDER BY p.id ASC
                """,
                thread_id,
            )
        return [row_to_dict(row) or {} for row in rows]

    async def fetch_post(self, thread_id: str, post_id: int) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    p.*,
                    a.display_name,
                    a.label
                FROM posts p
                LEFT JOIN agents a ON a.id = p.agent_id
                WHERE p.thread_id = $1
                  AND p.id = $2
                  AND p.deleted_at IS NULL
                """,
                thread_id,
                post_id,
            )
        return row_to_dict(row)

    async def save_post(
        self,
        thread_id: str,
        agent_id: str | None,
        post_data: dict[str, Any],
        *,
        user_id: str | None = None,
        is_facilitator: bool = False,
        token_usage: int = 0,
    ) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH inserted AS (
                    INSERT INTO posts (
                        thread_id, agent_id, user_id, reply_to, content, stance,
                        focus_axis, is_facilitator, token_usage
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING *
                )
                SELECT inserted.*, a.display_name, a.label
                FROM inserted
                LEFT JOIN agents a ON a.id = inserted.agent_id
                """,
                thread_id,
                agent_id,
                user_id or post_data.get("user_id"),
                post_data.get("reply_to"),
                post_data["content"],
                post_data.get("stance"),
                post_data.get("focus_axis"),
                is_facilitator,
                token_usage,
            )
        return row_to_dict(row) or {}

    async def record_thread_share(self, user_id: str, thread_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval(
                    "SELECT 1 FROM thread_shares WHERE user_id = $1 AND thread_id = $2",
                    user_id,
                    thread_id,
                )
                if existing:
                    return False
                await conn.execute(
                    "INSERT INTO thread_shares (user_id, thread_id) VALUES ($1, $2)",
                    user_id,
                    thread_id,
                )
                await conn.execute(
                    """
                    UPDATE users
                    SET monthly_thread_count = GREATEST(0, monthly_thread_count - 5)
                    WHERE id = $1
                    """,
                    user_id,
                )
        return True

    async def create_report(
        self,
        *,
        thread_id: str,
        reporter_id: str,
        reason: str,
        post_id: int | None = None,
    ) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """
                    SELECT id, status
                    FROM reports
                    WHERE thread_id = $1
                      AND reporter_id = $2
                      AND (
                        ($3::int IS NULL AND post_id IS NULL)
                        OR post_id = $3
                      )
                      AND status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    thread_id,
                    reporter_id,
                    post_id,
                )
                if existing is not None:
                    return {
                        "id": int(existing["id"]),
                        "duplicate": True,
                        "status": str(existing["status"]),
                    }

                row = await conn.fetchrow(
                    """
                    INSERT INTO reports (thread_id, post_id, reporter_id, reason)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, status
                    """,
                    thread_id,
                    post_id,
                    reporter_id,
                    reason,
                )
        return {
            "id": int(row["id"]),
            "duplicate": False,
            "status": str(row["status"]),
        }

    async def has_shared_thread(self, user_id: str, thread_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM thread_shares WHERE user_id = $1 AND thread_id = $2",
                user_id,
                thread_id,
            )
        return bool(row)

    async def list_running_thread_ids(self) -> list[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM threads WHERE state = 'running' AND deleted_at IS NULL")
        return [str(row["id"]) for row in rows]

    async def save_thread_script(self, thread_id: str, script: dict[str, Any]) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE threads SET script_json = $2::jsonb WHERE id = $1",
                thread_id,
                json.dumps(script),
            )

    async def update_thread_state(self, thread_id: str, state: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET state = $2 WHERE id = $1", thread_id, state)

    async def update_thread_phase(self, thread_id: str, phase: int) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET current_phase = $2 WHERE id = $1", thread_id, phase)

    async def fetch_thread_votes(self, thread_id: str) -> dict[str, Any]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT agent_id, COUNT(*) AS cnt FROM thread_votes WHERE thread_id = $1 GROUP BY agent_id",
                thread_id,
            )
        return {str(row["agent_id"]): int(row["cnt"]) for row in rows}

    async def fetch_user_thread_vote(self, thread_id: str, user_id: str) -> str | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT agent_id FROM thread_votes WHERE thread_id = $1 AND user_id = $2",
                thread_id,
                user_id,
            )
        return str(val) if val else None

    async def upsert_thread_vote(self, thread_id: str, user_id: str, agent_id: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO thread_votes (thread_id, user_id, agent_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (thread_id, user_id) DO UPDATE SET agent_id = EXCLUDED.agent_id, created_at = NOW()
                """,
                thread_id,
                user_id,
                agent_id,
            )

    async def update_thread_speed(self, thread_id: str, mode: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET speed_mode = $2 WHERE id = $1", thread_id, mode)

    async def load_debate_state(self, thread_id: str) -> dict | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM thread_debate_states WHERE thread_id = $1",
                thread_id,
            )
        if row is None:
            return None
        raw = row["state_json"]
        return dict(raw) if raw else None

    async def save_debate_state(self, thread_id: str, state: dict) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO thread_debate_states (thread_id, state_json)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (thread_id) DO UPDATE
                    SET state_json = EXCLUDED.state_json,
                        updated_at = NOW()
                """,
                thread_id,
                json.dumps(state, ensure_ascii=False),
            )
