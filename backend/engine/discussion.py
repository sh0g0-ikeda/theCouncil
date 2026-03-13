from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from db.client import get_db
from engine.facilitator import make_facilitate
from engine.llm import LLMGenerationError, compress_history
from engine.selector import select_conflict_axis, select_next_agent, select_target_post
from models.agent import Agent, IdeologyVector

logger = logging.getLogger(__name__)

agents: dict[str, Agent] = {}
_discussion_tasks: dict[str, asyncio.Task[None]] = {}

SPEED = {"normal": 5.0, "fast": 1.5, "instant": 0.1, "paused": 999.0}


def load_agents() -> None:
    agents.clear()
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    for path in agents_dir.glob("*/persona.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        vector = IdeologyVector(**payload["ideology_vector"])
        agents[payload["id"]] = Agent(
            id=payload["id"],
            display_name=payload["display_name"],
            label=payload["label"],
            persona=payload,
            vector=vector,
        )


async def start_discussion(
    thread_id: str,
    push_fn: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    task = _discussion_tasks.get(thread_id)
    if task and not task.done():
        return
    _discussion_tasks[thread_id] = asyncio.create_task(run_discussion(thread_id, push_fn))


def _should_facilitate(posts: list[dict[str, Any]]) -> bool:
    if not posts or len(posts) % 10 != 0:
        return False
    return not posts[-1].get("is_facilitator", False)


async def run_discussion(
    thread_id: str,
    push_fn: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    db = get_db()
    compressed_summary = ""
    compressed_upto = 0
    failed_agents: set[str] = set()
    last_post_count = -1

    try:
        while True:
            thread = await db.fetch_thread(thread_id)
            if not thread or thread.get("deleted_at"):
                break
            if thread["state"] == "completed":
                break
            if thread["state"] != "running":
                await asyncio.sleep(2)
                continue

            posts = await db.fetch_posts(thread_id)
            if len(posts) != last_post_count:
                failed_agents.clear()
                last_post_count = len(posts)

            if len(posts) >= thread["max_posts"]:
                await db.update_thread_state(thread_id, "completed")
                break

            compressible_upto = max(0, len(posts) - 5)
            while compressible_upto - compressed_upto >= 10:
                batch = posts[compressed_upto:compressed_upto + 10]
                compressed_summary = await compress_history(batch, compressed_summary)
                compressed_upto += 10

            phase = _get_phase(len(posts))
            if phase != thread["current_phase"]:
                await db.update_thread_phase(thread_id, phase)

            if _should_facilitate(posts):
                facilitate = await make_facilitate(thread, posts)
                if facilitate and facilitate.get("content"):
                    post = await db.save_post(
                        thread_id,
                        None,
                        {
                            "reply_to": None,
                            "content": facilitate["content"],
                            "stance": "facilitate",
                            "focus_axis": facilitate.get("main_axis", "rationalism"),
                        },
                        is_facilitator=True,
                        token_usage=int(facilitate.get("_token_usage", 0)),
                    )
                    failed_agents.clear()
                    await push_fn(thread_id, post)
                    await asyncio.sleep(SPEED.get(thread["speed_mode"], 5.0))
                    continue

            try:
                speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents)
            except ValueError:
                failed_agents.clear()
                await asyncio.sleep(0.5)
                continue

            target = select_target_post(posts, speaker_id, agents)
            target_id = target["agent_id"] if target and target.get("agent_id") else None
            axis = select_conflict_axis(speaker_id, target_id, agents) if target_id else "rationalism"

            recent_posts = posts[compressed_upto:]
            context = {
                "thread_topic": thread["topic"],
                "current_tags": thread["topic_tags"],
                "target_post": target or {},
                "conflict_axis": axis,
                "role": _role_for_phase(phase),
                "conversation_summary": _build_conversation_summary(compressed_summary, recent_posts),
            }

            try:
                reply = await agents[speaker_id].generate_reply(context)
            except LLMGenerationError:
                failed_agents.add(speaker_id)
                logger.warning(
                    "agent generation failed for thread=%s speaker=%s",
                    thread_id,
                    speaker_id,
                    exc_info=True,
                )
                await asyncio.sleep(0.1)
                continue

            post = await db.save_post(
                thread_id,
                speaker_id,
                {
                    "reply_to": target["id"] if target else None,
                    "content": reply["content"],
                    "stance": reply.get("stance", "disagree"),
                    "focus_axis": reply.get("main_axis", axis),
                },
                token_usage=int(reply.get("_token_usage", 0)),
            )
            failed_agents.clear()
            await push_fn(thread_id, post)
            await asyncio.sleep(SPEED.get(thread["speed_mode"], 5.0))
    finally:
        _discussion_tasks.pop(thread_id, None)


def _get_phase(post_count: int) -> int:
    if post_count < 8:
        return 1
    if post_count < 23:
        return 2
    if post_count < 38:
        return 3
    if post_count < 45:
        return 4
    return 5


def _role_for_phase(phase: int) -> str:
    return {1: "supplement", 2: "counter", 3: "counter", 4: "shift", 5: "supplement"}[phase]


def _build_conversation_summary(compressed_summary: str, recent_posts: list[dict[str, Any]]) -> str:
    recent_window = recent_posts if len(recent_posts) <= 10 else recent_posts[-5:]
    recent_summary = " / ".join(
        f"{post.get('display_name') or post.get('agent_id') or '?'}: {post['content'][:50]}"
        for post in recent_window
    )
    if compressed_summary and recent_summary:
        return f"圧縮履歴: {compressed_summary} / 直近: {recent_summary}"
    return compressed_summary or recent_summary
