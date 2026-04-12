from __future__ import annotations

import asyncio

try:
    from fastapi import HTTPException

    from api.access import require_thread_access
    from api.deps import RequestUser, require_admin
    from api.threads import CreateThreadRequest
except Exception:  # pragma: no cover - local env may miss binary deps for FastAPI/Pydantic
    HTTPException = None  # type: ignore[assignment]
    require_thread_access = None  # type: ignore[assignment]
    require_admin = None  # type: ignore[assignment]
    RequestUser = None  # type: ignore[assignment]
    CreateThreadRequest = None  # type: ignore[assignment]

from engine.discussion import agents, refresh_runtime_agent, refresh_runtime_agents
from models.agent import Agent, IdeologyVector


class FakeDB:
    def __init__(self, *, thread=None, user_record=None, agent_record=None, public_agents=None) -> None:
        self.thread = thread
        self.user_record = user_record
        self.agent_record = agent_record
        self.public_agents = public_agents if public_agents is not None else []

    async def fetch_thread(self, _thread_id: str):
        return self.thread

    async def resolve_request_user(self, _subject: str, _email: str | None):
        return self.user_record

    async def fetch_agent(self, _agent_id: str):
        return self.agent_record

    async def list_public_agents(self):
        return self.public_agents


def _make_persona(agent_id: str, display_name: str) -> dict:
    return {
        "id": agent_id,
        "display_name": display_name,
        "label": display_name,
        "ideology_vector": {
            "state_control": 1,
            "tech_optimism": 1,
            "rationalism": 1,
            "power_realism": 1,
            "individualism": 1,
            "moral_universalism": 1,
            "future_orientation": 1,
        },
    }


def test_require_thread_access_blocks_private_thread_for_non_owner() -> None:
    if require_thread_access is None or HTTPException is None or RequestUser is None:
        return

    async def run() -> None:
        db = FakeDB(
            thread={"id": "t1", "visibility": "private", "user_id": "owner", "deleted_at": None, "hidden_at": None},
            user_record={"id": "other", "role": "user"},
        )
        try:
            await require_thread_access("t1", db, RequestUser(id="x-user"))
        except HTTPException as exc:
            assert exc.status_code == 404
            return
        raise AssertionError("expected private thread access to be denied")

    asyncio.run(run())


def test_require_thread_access_allows_private_thread_owner() -> None:
    if require_thread_access is None or RequestUser is None:
        return

    async def run() -> None:
        db = FakeDB(
            thread={"id": "t1", "visibility": "private", "user_id": "owner", "deleted_at": None, "hidden_at": None},
            user_record={"id": "owner", "role": "user"},
        )
        access = await require_thread_access("t1", db, RequestUser(id="owner-x"))
        assert access.is_owner is True

    asyncio.run(run())


def test_require_thread_access_hides_hidden_thread_from_non_admin() -> None:
    if require_thread_access is None or HTTPException is None or RequestUser is None:
        return

    async def run() -> None:
        db = FakeDB(
            thread={"id": "t1", "visibility": "public", "user_id": "owner", "deleted_at": None, "hidden_at": "now"},
            user_record={"id": "other", "role": "user"},
        )
        try:
            await require_thread_access("t1", db, RequestUser(id="other-x"))
        except HTTPException as exc:
            assert exc.status_code == 404
            return
        raise AssertionError("expected hidden thread access to be denied")

    asyncio.run(run())


def test_require_admin_resolves_external_subject_via_db_lookup() -> None:
    if require_admin is None or RequestUser is None:
        return

    async def run() -> None:
        user = RequestUser(id="external-x-id", email="admin@example.com")
        db = FakeDB(user_record={"id": "uuid-1", "x_id": "external-x-id", "role": "admin"})
        resolved = await require_admin(user=user, db=db)
        assert resolved.id == "external-x-id"

    asyncio.run(run())


def test_create_thread_request_accepts_plan_ceiling_values() -> None:
    if CreateThreadRequest is None:
        return

    req = CreateThreadRequest(topic="test topic", agent_ids=["a", "b"], max_posts=200)
    assert req.max_posts == 200


def test_create_thread_request_tracks_when_max_posts_is_omitted() -> None:
    if CreateThreadRequest is None:
        return

    req = CreateThreadRequest(topic="test topic", agent_ids=["a", "b"])
    assert req.max_posts == 20
    assert "max_posts" not in req.model_fields_set


def test_refresh_runtime_agent_removes_disabled_agent() -> None:
    agents["disabled-agent"] = Agent(
        id="disabled-agent",
        display_name="disabled-agent",
        label="disabled-agent",
        persona=_make_persona("disabled-agent", "disabled-agent"),
        vector=IdeologyVector(1, 1, 1, 1, 1, 1, 1),
    )

    async def run() -> None:
        db = FakeDB(agent_record={"id": "disabled-agent", "enabled": False})
        await refresh_runtime_agent("disabled-agent", db)
        assert "disabled-agent" not in agents

    try:
        asyncio.run(run())
    finally:
        agents.pop("disabled-agent", None)


def test_refresh_runtime_agent_applies_db_persona_override() -> None:
    async def run() -> None:
        db = FakeDB(
            agent_record={
                "id": "override-agent",
                "enabled": True,
                "persona_json": _make_persona("override-agent", "override-name"),
            }
        )
        await refresh_runtime_agent("override-agent", db)
        assert agents["override-agent"].display_name == "override-name"

    try:
        asyncio.run(run())
    finally:
        agents.pop("override-agent", None)


def test_refresh_runtime_agents_clears_runtime_when_db_has_no_enabled_agents() -> None:
    agents["stale-agent"] = Agent(
        id="stale-agent",
        display_name="stale-agent",
        label="stale-agent",
        persona=_make_persona("stale-agent", "stale-agent"),
        vector=IdeologyVector(1, 1, 1, 1, 1, 1, 1),
    )

    async def run() -> None:
        db = FakeDB(public_agents=[])
        await refresh_runtime_agents(db)
        assert agents == {}

    try:
        asyncio.run(run())
    finally:
        agents.clear()
