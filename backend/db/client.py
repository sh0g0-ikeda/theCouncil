from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    asyncpg = None  # type: ignore[assignment]


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "persona_json" in data and isinstance(data["persona_json"], str):
        data["persona_json"] = json.loads(data["persona_json"])
    return data


class DatabaseClient:
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

    async def fetch_user(self, user_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return _row_to_dict(row)

    async def ensure_user_from_request(self, x_id: str, email: str | None) -> str:
        """Upsert user by x_id (Twitter ID), return internal UUID."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
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
        return _row_to_dict(row) or {}

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
                if user["plan"] == "free" and user["monthly_thread_count"] >= 5:
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
        return _row_to_dict(row) or {}

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
            LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL
            WHERE t.visibility = 'public' AND t.deleted_at IS NULL
            GROUP BY t.id
            ORDER BY {order_clause}
            LIMIT $1
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
        return [_row_to_dict(row) or {} for row in rows]

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
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.id = $1
                GROUP BY t.id, u.x_id
                """,
                thread_id,
            )
        return _row_to_dict(row)

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
                WHERE p.thread_id = $1 AND p.deleted_at IS NULL
                ORDER BY p.id ASC
                """,
                thread_id,
            )
        return [_row_to_dict(row) or {} for row in rows]

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
        return _row_to_dict(row) or {}

    async def update_thread_state(self, thread_id: str, state: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET state = $2 WHERE id = $1", thread_id, state)

    async def update_thread_phase(self, thread_id: str, phase: int) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET current_phase = $2 WHERE id = $1", thread_id, phase)

    async def update_thread_speed(self, thread_id: str, mode: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE threads SET speed_mode = $2 WHERE id = $1", thread_id, mode)

    async def dashboard_stats(self) -> dict[str, int]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*)::int FROM threads WHERE created_at >= CURRENT_DATE) AS threads_today,
                    (SELECT COUNT(*)::int FROM posts WHERE created_at >= CURRENT_DATE) AS posts_today,
                    (SELECT COUNT(*)::int FROM reports WHERE created_at >= CURRENT_DATE) AS reports_today,
                    (SELECT COALESCE(SUM(token_usage), 0)::int FROM posts WHERE created_at >= CURRENT_DATE) AS tokens_today
                """
            )
        return _row_to_dict(row) or {
            "threads_today": 0,
            "posts_today": 0,
            "reports_today": 0,
            "tokens_today": 0,
        }

    async def admin_list_threads(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    t.*,
                    u.email AS owner_email,
                    COALESCE(COUNT(p.id), 0)::int AS post_count
                    u.x_id AS owner_x_id
                FROM threads t
                LEFT JOIN users u ON u.id = t.user_id
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL
                GROUP BY t.id, u.email
                ORDER BY t.created_at DESC
                LIMIT 100
                """
            )
        return [_row_to_dict(row) or {} for row in rows]

    async def admin_thread_action(self, thread_id: str, action: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if action == "hide":
                result = await conn.execute("UPDATE threads SET hidden_at = NOW() WHERE id = $1", thread_id)
            elif action == "delete":
                result = await conn.execute("UPDATE threads SET deleted_at = NOW() WHERE id = $1", thread_id)
            elif action == "lock":
                result = await conn.execute("UPDATE threads SET locked_at = NOW() WHERE id = $1", thread_id)
            elif action == "force_complete":
                result = await conn.execute("UPDATE threads SET state = 'completed' WHERE id = $1", thread_id)
            elif action == "set_public":
                result = await conn.execute("UPDATE threads SET visibility = 'public' WHERE id = $1", thread_id)
            elif action == "set_private":
                result = await conn.execute("UPDATE threads SET visibility = 'private' WHERE id = $1", thread_id)
            else:  # pragma: no cover - guarded by API validation
                raise ValueError("invalid_thread_action")
        return not result.endswith(" 0")

    async def admin_list_posts(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    p.*,
                    a.display_name,
                    a.label,
                    t.topic
                FROM posts p
                LEFT JOIN agents a ON a.id = p.agent_id
                LEFT JOIN threads t ON t.id = p.thread_id
                ORDER BY p.created_at DESC
                LIMIT 200
                """
            )
        return [_row_to_dict(row) or {} for row in rows]

    async def admin_post_action(self, thread_id: str, post_id: int, action: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if action == "warn":
                row = await conn.fetchrow(
                    "SELECT user_id FROM posts WHERE thread_id = $1 AND id = $2",
                    thread_id,
                    post_id,
                )
                if row is None or row["user_id"] is None:
                    return False
                result = await conn.execute(
                    "UPDATE users SET warning_count = warning_count + 1 WHERE id = $1",
                    row["user_id"],
                )
                return not result.endswith(" 0")
            if action == "hide":
                result = await conn.execute(
                    "UPDATE posts SET hidden_at = NOW() WHERE thread_id = $1 AND id = $2",
                    thread_id,
                    post_id,
                )
            elif action == "delete":
                result = await conn.execute(
                    "UPDATE posts SET deleted_at = NOW() WHERE thread_id = $1 AND id = $2",
                    thread_id,
                    post_id,
                )
            else:  # pragma: no cover - guarded by API validation
                raise ValueError("invalid_post_action")
        return not result.endswith(" 0")

    async def admin_list_reports(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.*, p.content AS post_content, t.topic
                FROM reports r
                LEFT JOIN posts p ON p.thread_id = r.thread_id AND p.id = r.post_id
                LEFT JOIN threads t ON t.id = r.thread_id
                ORDER BY r.created_at DESC
                LIMIT 200
                """
            )
        return [_row_to_dict(row) or {} for row in rows]

    async def admin_report_action(self, report_id: int, action: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if action == "delete_post":
                    row = await conn.fetchrow(
                        "SELECT thread_id, post_id FROM reports WHERE id = $1",
                        report_id,
                    )
                    if row is None:
                        return False
                    await conn.execute(
                        "UPDATE posts SET deleted_at = NOW() WHERE thread_id = $1 AND id = $2",
                        row["thread_id"],
                        row["post_id"],
                    )
                    result = await conn.execute(
                        "UPDATE reports SET status = 'resolved' WHERE id = $1",
                        report_id,
                    )
                    return not result.endswith(" 0")
                result = await conn.execute(
                    "UPDATE reports SET status = $2 WHERE id = $1",
                    report_id,
                    "resolved" if action == "resolved" else "dismissed",
                )
        return not result.endswith(" 0")

    async def admin_list_users(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC LIMIT 200")
        return [_row_to_dict(row) or {} for row in rows]

    async def admin_user_action(self, user_id: str, action: str, plan: str | None) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if action == "plan":
                if plan not in {"free", "pro", "ultra"}:
                    raise ValueError("invalid_plan")
                result = await conn.execute(
                    "UPDATE users SET plan = $2 WHERE id = $1",
                    user_id,
                    plan,
                )
                return not result.endswith(" 0")
            result = await conn.execute(
                "UPDATE users SET is_banned = $2 WHERE id = $1",
                user_id,
                action == "ban",
            )
        return not result.endswith(" 0")

    async def admin_list_agents(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM agents ORDER BY display_name ASC")
        return [_row_to_dict(row) or {} for row in rows]

    async def list_public_agents(self) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, display_name, label, persona_json, vector
                FROM agents
                WHERE enabled = TRUE
                ORDER BY display_name ASC
                """
            )
        return [_row_to_dict(row) or {} for row in rows]

    async def sync_agents_from_disk(self, agents_data: list[dict[str, Any]]) -> None:
        """Upsert agents from persona.json files; preserves existing enabled flag."""
        _VECTOR_KEYS = [
            "state_control", "tech_optimism", "rationalism", "power_realism",
            "individualism", "moral_universalism", "future_orientation",
        ]
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for agent in agents_data:
                persona_str = json.dumps(agent, ensure_ascii=False)
                iv = agent.get("ideology_vector", {})
                vector = [iv.get(k, 0) for k in _VECTOR_KEYS]
                await conn.execute(
                    """
                    INSERT INTO agents (id, display_name, label, persona_json, vector, enabled)
                    VALUES ($1, $2, $3, $4::jsonb, $5::integer[], TRUE)
                    ON CONFLICT (id) DO UPDATE
                        SET display_name = EXCLUDED.display_name,
                            label = EXCLUDED.label,
                            persona_json = EXCLUDED.persona_json,
                            vector = EXCLUDED.vector,
                            updated_at = NOW()
                    """,
                    agent["id"],
                    agent["display_name"],
                    agent["label"],
                    persona_str,
                    vector,
                )

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

    async def admin_update_agent(
        self,
        agent_id: str,
        enabled: bool | None,
        persona_json: dict[str, Any] | None,
    ) -> bool:
        assignments: list[str] = ["updated_at = NOW()"]
        args: list[Any] = [agent_id]
        if enabled is not None:
            assignments.append(f"enabled = ${len(args) + 1}")
            args.append(enabled)
        if persona_json is not None:
            idx = len(args) + 1
            args.append(json.dumps(persona_json, ensure_ascii=False))
            assignments.append(f"persona_json = ${idx}::jsonb")
            assignments.append(f"display_name = (${idx}::jsonb ->> 'display_name')")
            assignments.append(f"label = (${idx}::jsonb ->> 'label')")
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE agents SET {', '.join(assignments)} WHERE id = $1",
                *args,
            )
        return not result.endswith(" 0")


_db: DatabaseClient | None = None


def get_db() -> DatabaseClient:
    global _db
    if _db is None:
        dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/the_council")
        _db = DatabaseClient(dsn=dsn)
    return _db
