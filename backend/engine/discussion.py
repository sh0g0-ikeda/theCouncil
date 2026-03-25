from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from db.client import DatabaseClient, get_db
from engine.discussion_policy import (
    _build_conversation_summary,
    _classify_user_intervention,
    _detect_stagnation,
    _determine_retrieval_mode,
    _extract_abstract_nouns,
    _extract_directive_type,
    _fallback_speaker,
    _get_phase,
    _is_missing_debate_state_error,
    _is_moral_suction,
    _needs_director,
    _prioritize_speaker,
    _role_for_phase,
    _run_director,
    _sanitize_topic_axes,
    _select_debate_function,
    _select_meta_speaker,
    _should_facilitate,
    _tokenize,
    seed_subquestions,
)
from engine.script_runtime import ScriptedDiscussionRunner
from models.agent import Agent, IdeologyVector

agents: dict[str, Agent] = {}
_discussion_tasks: dict[str, asyncio.Task[None]] = {}


def _agent_from_persona(payload: dict[str, object]) -> Agent:
    vector = IdeologyVector(**payload["ideology_vector"])
    return Agent(
        id=payload["id"],
        display_name=payload["display_name"],
        label=payload["label"],
        persona=payload,
        vector=vector,
    )


def _upsert_runtime_agent(payload: dict[str, object]) -> None:
    agent = _agent_from_persona(payload)
    agents[agent.id] = agent


def load_disk_agents() -> list[dict[str, object]]:
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    payloads: list[dict[str, object]] = []
    for path in agents_dir.glob("*/persona.json"):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


def replace_runtime_agents(payloads: list[dict[str, object]]) -> None:
    agents.clear()
    for payload in payloads:
        _upsert_runtime_agent(payload)


def load_agents() -> None:
    replace_runtime_agents(load_disk_agents())


async def refresh_runtime_agents(db: DatabaseClient | None = None) -> None:
    database = db or get_db()
    rows = await database.list_public_agents()

    enabled_ids: set[str] = set()
    for row in rows:
        persona = row.get("persona_json")
        if not isinstance(persona, dict):
            continue
        _upsert_runtime_agent(persona)
        enabled_ids.add(str(row["id"]))

    for agent_id in list(agents):
        if agent_id not in enabled_ids:
            agents.pop(agent_id, None)


async def refresh_runtime_agent(agent_id: str, db: DatabaseClient | None = None) -> None:
    database = db or get_db()
    record = await database.fetch_agent(agent_id)
    if not record or not record.get("enabled"):
        agents.pop(agent_id, None)
        return
    persona = record.get("persona_json")
    if isinstance(persona, dict):
        _upsert_runtime_agent(persona)


async def run_discussion(
    thread_id: str,
    push_fn: Callable[[str, dict[str, object]], Awaitable[None]],
) -> None:
    runner = ScriptedDiscussionRunner(
        thread_id=thread_id,
        db=get_db(),
        agents=agents,
        push_fn=push_fn,
    )
    await runner.run()


async def start_discussion(
    thread_id: str,
    push_fn: Callable[[str, dict[str, object]], Awaitable[None]],
) -> None:
    task = _discussion_tasks.get(thread_id)
    if task and not task.done():
        return
    task = asyncio.create_task(run_discussion(thread_id, push_fn))
    task.add_done_callback(lambda _: _discussion_tasks.pop(thread_id, None))
    _discussion_tasks[thread_id] = task
