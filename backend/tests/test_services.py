from __future__ import annotations

import asyncio

from services import agent_admin as agent_admin_service
from services.reporting import submit_post_report, submit_thread_report
from services.request_users import resolve_internal_user_id


class FakeDB:
    def __init__(self) -> None:
        self.ensure_calls: list[tuple[str, str | None]] = []
        self.report_calls: list[dict] = []
        self.post_lookup: dict[tuple[str, int], dict] = {}
        self.agent_update_result = True

    async def ensure_user_from_request(self, subject: str, email: str | None) -> str:
        self.ensure_calls.append((subject, email))
        return "internal-user-id"

    async def create_report(self, **kwargs):
        self.report_calls.append(kwargs)
        return {"id": 1, "duplicate": False, "status": "pending"}

    async def fetch_post(self, thread_id: str, post_id: int):
        return self.post_lookup.get((thread_id, post_id))

    async def admin_update_agent(self, agent_id: str, enabled, persona_json):
        return self.agent_update_result


class FakeUser:
    def __init__(self, user_id: str, email: str | None = None) -> None:
        self.id = user_id
        self.email = email


def test_resolve_internal_user_id_prefers_existing_actor_id() -> None:
    async def run() -> None:
        db = FakeDB()
        user = FakeUser("external", "user@example.com")
        resolved = await resolve_internal_user_id(
            db,
            user,
            preferred_internal_user_id="already-internal",
        )
        assert resolved == "already-internal"
        assert db.ensure_calls == []

    asyncio.run(run())


def test_submit_thread_report_uses_common_user_resolution() -> None:
    async def run() -> None:
        db = FakeDB()
        user = FakeUser("external", "user@example.com")
        thread = {"id": "thread-1"}
        report = await submit_thread_report(
            db=db,
            thread=thread,
            user=user,
            actor_internal_user_id=None,
            reason="other",
        )
        assert report["status"] == "pending"
        assert db.ensure_calls == [("external", "user@example.com")]
        assert db.report_calls == [
            {
                "thread_id": "thread-1",
                "reporter_id": "internal-user-id",
                "reason": "other",
                "post_id": None,
            }
        ]

    asyncio.run(run())


def test_submit_post_report_returns_none_for_missing_post() -> None:
    async def run() -> None:
        db = FakeDB()
        user = FakeUser("external", "user@example.com")
        report = await submit_post_report(
            db=db,
            thread={"id": "thread-1"},
            thread_id="thread-1",
            post_id=99,
            user=user,
            actor_internal_user_id=None,
            reason="other",
        )
        assert report is None
        assert db.report_calls == []

    asyncio.run(run())


def test_update_agent_settings_refreshes_runtime_after_db_write() -> None:
    async def run() -> None:
        db = FakeDB()
        calls: list[tuple[str, str]] = []
        original_refresh = agent_admin_service._refresh_runtime_agent
        original_clear = agent_admin_service._clear_agent_rag_cache

        async def fake_refresh(agent_id: str, _db) -> None:
            calls.append(("refresh", agent_id))

        def fake_clear(agent_id: str) -> None:
            calls.append(("clear", agent_id))

        agent_admin_service._refresh_runtime_agent = fake_refresh  # type: ignore[assignment]
        agent_admin_service._clear_agent_rag_cache = fake_clear  # type: ignore[assignment]
        try:
            ok = await agent_admin_service.update_agent_settings(
                db=db,
                agent_id="agent-1",
                enabled=True,
                persona_json=None,
                refresh_rag=True,
            )
            assert ok is True
            assert calls == [("refresh", "agent-1"), ("clear", "agent-1")]
        finally:
            agent_admin_service._refresh_runtime_agent = original_refresh
            agent_admin_service._clear_agent_rag_cache = original_clear

    asyncio.run(run())
