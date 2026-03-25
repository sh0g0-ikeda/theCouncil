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
    if "script_json" in data and isinstance(data["script_json"], str):
        data["script_json"] = json.loads(data["script_json"])
    return data


_VECTOR_KEYS = [
    "state_control",
    "tech_optimism",
    "rationalism",
    "power_realism",
    "individualism",
    "moral_universalism",
    "future_orientation",
]


def _persona_to_vector(persona: dict[str, Any]) -> list[int]:
    ideology = persona.get("ideology_vector", {})
    return [int(ideology.get(key, 0)) for key in _VECTOR_KEYS]


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
            row = await conn.fetchrow("SELECT * FROM users WHERE id::text = $1", user_id)
        return _row_to_dict(row)

    async def fetch_user_by_x_id(self, x_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE x_id = $1", x_id)
        return _row_to_dict(row)

    async def resolve_request_user(self, subject: str, email: str | None) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id::text = $1", subject)
            if row is None:
                row = await conn.fetchrow("SELECT * FROM users WHERE x_id = $1", subject)
            if row is None and email:
                row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        return _row_to_dict(row)

    async def fetch_user_normalized(self, user_id: str) -> dict[str, Any] | None:
        """fetch_user with monthly quota reset applied."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._normalize_thread_quota(conn, user_id)

    async def ensure_user_from_request(self, x_id: str, email: str | None) -> str:
        """Resolve a request subject to an internal UUID, creating by x_id if needed."""
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
                # Enforce global thread cap: delete oldest threads beyond 200
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
            LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL AND p.hidden_at IS NULL
            WHERE t.visibility = 'public' AND t.deleted_at IS NULL AND t.hidden_at IS NULL
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
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL AND p.hidden_at IS NULL
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.id = $1
                GROUP BY t.id, u.x_id
                """,
                thread_id,
            )
        return _row_to_dict(row)

    async def fetch_thread_state(self, thread_id: str) -> dict[str, Any] | None:
        """Lightweight per-loop poll: returns all thread fields except script_json (~20KB JSONB).

        Use this inside the discussion loop. Use fetch_thread only for the initial script load.
        """
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
                WHERE p.thread_id = $1 AND p.deleted_at IS NULL AND p.hidden_at IS NULL
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

    async def record_thread_share(self, user_id: str, thread_id: str) -> bool:
        """Record an X share and grant +5 thread quota. Returns False if already shared."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchval(
                    "SELECT 1 FROM thread_shares WHERE user_id = $1 AND thread_id = $2",
                    user_id, thread_id,
                )
                if existing:
                    return False
                await conn.execute(
                    "INSERT INTO thread_shares (user_id, thread_id) VALUES ($1, $2)",
                    user_id, thread_id,
                )
                # Grant +5 bonus by reducing used count (floor at 0)
                await conn.execute(
                    """UPDATE users
                       SET monthly_thread_count = GREATEST(0, monthly_thread_count - 5)
                       WHERE id = $1""",
                    user_id,
                )
        return True

    async def has_shared_thread(self, user_id: str, thread_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM thread_shares WHERE user_id = $1 AND thread_id = $2",
                user_id, thread_id,
            )
        return bool(row)

    async def list_running_thread_ids(self) -> list[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM threads WHERE state = 'running' AND deleted_at IS NULL"
            )
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
        """Return {counts: {agent_id: int}, my_vote: None} — caller adds my_vote."""
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
                thread_id, user_id,
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
                thread_id, user_id, agent_id,
            )

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
                    u.x_id AS owner_x_id,
                    COALESCE(COUNT(p.id), 0)::int AS post_count
                FROM threads t
                LEFT JOIN users u ON u.id = t.user_id
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL
                GROUP BY t.id, u.email, u.x_id
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

    async def list_enabled_agent_ids(self) -> list[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM agents WHERE enabled = TRUE")
        return [str(row["id"]) for row in rows]

    async def fetch_agent(self, agent_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
        return _row_to_dict(row)

    async def sync_agents_from_disk(self, agents_data: list[dict[str, Any]]) -> None:
        """Seed missing agents from disk; keep DB edits authoritative for existing rows."""
        pool = await self._ensure_pool()
        disk_ids = {agent["id"] for agent in agents_data}
        async with pool.acquire() as conn:
            for agent in agents_data:
                persona_str = json.dumps(agent, ensure_ascii=False)
                vector = _persona_to_vector(agent)
                await conn.execute(
                    """
                    INSERT INTO agents (id, display_name, label, persona_json, vector, enabled)
                    VALUES ($1, $2, $3, $4::jsonb, $5::integer[], TRUE)
                    ON CONFLICT (id) DO UPDATE
                        SET updated_at = NOW()
                    """,
                    agent["id"],
                    agent["display_name"],
                    agent["label"],
                    persona_str,
                    vector,
                )
            # Disable any DB agents whose persona.json no longer exists on disk
            await conn.execute(
                "UPDATE agents SET enabled = FALSE WHERE id <> ALL($1::text[])",
                list(disk_ids),
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
            vector_idx = len(args) + 1
            args.append(_persona_to_vector(persona_json))
            assignments.append(f"vector = ${vector_idx}::integer[]")
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
