from __future__ import annotations

import json
from typing import Any

from db.shared import persona_to_vector, row_to_dict


class AdminRepositoryMixin:
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
        return row_to_dict(row) or {
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
                    COALESCE(COUNT(p.id), 0)::int AS post_count,
                    (
                        SELECT COUNT(*)::int
                        FROM reports r
                        WHERE r.thread_id = t.id AND r.post_id IS NULL
                    ) AS report_count,
                    (
                        SELECT COUNT(*)::int
                        FROM reports r
                        WHERE r.thread_id = t.id AND r.post_id IS NULL AND r.status = 'pending'
                    ) AS pending_report_count
                FROM threads t
                LEFT JOIN users u ON u.id = t.user_id
                LEFT JOIN posts p ON p.thread_id = t.id AND p.deleted_at IS NULL
                GROUP BY t.id, u.email, u.x_id
                ORDER BY t.created_at DESC
                LIMIT 100
                """
            )
        return [row_to_dict(row) or {} for row in rows]

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
                    t.topic,
                    (
                        SELECT COUNT(*)::int
                        FROM reports r
                        WHERE r.thread_id = p.thread_id AND r.post_id = p.id
                    ) AS report_count,
                    (
                        SELECT COUNT(*)::int
                        FROM reports r
                        WHERE r.thread_id = p.thread_id AND r.post_id = p.id AND r.status = 'pending'
                    ) AS pending_report_count
                FROM posts p
                LEFT JOIN agents a ON a.id = p.agent_id
                LEFT JOIN threads t ON t.id = p.thread_id
                ORDER BY p.created_at DESC
                LIMIT 200
                """
            )
        return [row_to_dict(row) or {} for row in rows]

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
                SELECT
                    r.*,
                    p.content AS post_content,
                    t.topic,
                    reporter.email AS reporter_email,
                    reporter.x_id AS reporter_x_id,
                    CASE WHEN r.post_id IS NULL THEN 'thread' ELSE 'post' END AS target_type
                FROM reports r
                LEFT JOIN posts p ON p.thread_id = r.thread_id AND p.id = r.post_id
                LEFT JOIN threads t ON t.id = r.thread_id
                LEFT JOIN users reporter ON reporter.id = r.reporter_id
                ORDER BY r.created_at DESC
                LIMIT 200
                """
            )
        return [row_to_dict(row) or {} for row in rows]

    async def admin_report_action(self, report_id: int, action: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if action == "delete_post":
                    row = await conn.fetchrow("SELECT thread_id, post_id FROM reports WHERE id = $1", report_id)
                    if row is None:
                        return False
                    await conn.execute(
                        "UPDATE posts SET deleted_at = NOW() WHERE thread_id = $1 AND id = $2",
                        row["thread_id"],
                        row["post_id"],
                    )
                    result = await conn.execute("UPDATE reports SET status = 'resolved' WHERE id = $1", report_id)
                    return not result.endswith(" 0")
                if action == "hide_thread":
                    row = await conn.fetchrow("SELECT thread_id FROM reports WHERE id = $1", report_id)
                    if row is None or row["thread_id"] is None:
                        return False
                    await conn.execute("UPDATE threads SET hidden_at = NOW() WHERE id = $1", row["thread_id"])
                    result = await conn.execute("UPDATE reports SET status = 'resolved' WHERE id = $1", report_id)
                    return not result.endswith(" 0")
                if action == "delete_thread":
                    row = await conn.fetchrow("SELECT thread_id FROM reports WHERE id = $1", report_id)
                    if row is None or row["thread_id"] is None:
                        return False
                    await conn.execute("UPDATE threads SET deleted_at = NOW() WHERE id = $1", row["thread_id"])
                    result = await conn.execute("UPDATE reports SET status = 'resolved' WHERE id = $1", report_id)
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
        return [row_to_dict(row) or {} for row in rows]

    async def admin_user_action(self, user_id: str, action: str, plan: str | None) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if action == "plan":
                if plan not in {"free", "pro", "ultra"}:
                    raise ValueError("invalid_plan")
                result = await conn.execute("UPDATE users SET plan = $2 WHERE id = $1", user_id, plan)
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
        return [row_to_dict(row) or {} for row in rows]

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
        return [row_to_dict(row) or {} for row in rows]

    async def list_enabled_agent_ids(self) -> list[str]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM agents WHERE enabled = TRUE")
        return [str(row["id"]) for row in rows]

    async def fetch_agent(self, agent_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
        return row_to_dict(row)

    async def sync_agents_from_disk(self, agents_data: list[dict[str, Any]]) -> None:
        pool = await self._ensure_pool()
        disk_ids = {agent["id"] for agent in agents_data}
        async with pool.acquire() as conn:
            for agent in agents_data:
                persona_str = json.dumps(agent, ensure_ascii=False)
                vector = persona_to_vector(agent)
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
            await conn.execute(
                "UPDATE agents SET enabled = FALSE WHERE id <> ALL($1::text[])",
                list(disk_ids),
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
            args.append(persona_to_vector(persona_json))
            assignments.append(f"vector = ${vector_idx}::integer[]")
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE agents SET {', '.join(assignments)} WHERE id = $1",
                *args,
            )
        return not result.endswith(" 0")
