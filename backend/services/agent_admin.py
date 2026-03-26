from __future__ import annotations

from typing import Any, Protocol


class AgentAdminRepository(Protocol):
    async def admin_update_agent(
        self,
        agent_id: str,
        enabled: bool | None,
        persona_json: dict[str, Any] | None,
    ) -> bool: ...


async def _refresh_runtime_agent(agent_id: str, db: AgentAdminRepository) -> None:
    from engine.discussion import refresh_runtime_agent

    await refresh_runtime_agent(agent_id, db)


def _clear_agent_rag_cache(agent_id: str) -> None:
    from engine.rag import clear_chunk_cache

    clear_chunk_cache(agent_id)


async def update_agent_settings(
    *,
    db: AgentAdminRepository,
    agent_id: str,
    enabled: bool | None,
    persona_json: dict[str, Any] | None,
    refresh_rag: bool,
) -> bool:
    ok = await db.admin_update_agent(agent_id, enabled, persona_json)
    if not ok:
        return False
    await _refresh_runtime_agent(agent_id, db)
    if refresh_rag:
        _clear_agent_rag_cache(agent_id)
    return True
