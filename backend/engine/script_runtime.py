from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Awaitable, Callable

from db.client import DatabaseClient
from engine.discussion_policy import _get_phase
from engine.llm import LLMGenerationError, build_script_post_messages, call_llm, generate_debate_script
from engine.rag import retrieve_chunks
from models.agent import Agent

logger = logging.getLogger(__name__)

_TURN_FAIL_LIMIT = 3


@dataclass(slots=True)
class ResolvedTurn:
    speaker_id: str
    target_post: dict[str, Any] | None
    directive: str
    move_type: str
    phase: int
    assigned_side: str
    is_user_reply_turn: bool


@dataclass(slots=True)
class ScriptRuntimeState:
    event_counter: int = 0
    user_reply_pending: int = 0
    last_user_post_id: int | None = None
    cached_script: dict[str, Any] | None = None
    script_turn_index: int = 0
    turn_fail_counts: dict[int, int] = field(default_factory=dict)
    initial_load_done: bool = False


class ScriptedDiscussionRunner:
    def __init__(
        self,
        *,
        thread_id: str,
        db: DatabaseClient,
        agents: dict[str, Agent],
        push_fn: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.thread_id = thread_id
        self.db = db
        self.agents = agents
        self.push_fn = push_fn
        self.state = ScriptRuntimeState()

    async def run(self) -> None:
        logger.info("run_discussion started for thread=%s", self.thread_id)
        try:
            while True:
                thread = await self._load_thread()
                if not thread or thread.get("deleted_at"):
                    logger.info("run_discussion: thread=%s gone/deleted, stopping", self.thread_id)
                    break
                if thread["state"] == "completed":
                    logger.info("run_discussion: thread=%s completed, stopping", self.thread_id)
                    break
                if thread["state"] != "running":
                    await asyncio.sleep(2)
                    continue
                if thread.get("speed_mode") == "paused":
                    await asyncio.sleep(5)
                    continue

                if not await self._ensure_script(thread):
                    continue
                posts = await self.db.fetch_posts(self.thread_id)

                if len(posts) >= thread["max_posts"]:
                    await self.db.update_thread_state(self.thread_id, "completed")
                    break

                self._refresh_user_reply_state(posts)
                resolved = self._resolve_turn(thread, posts)
                if resolved is None:
                    continue

                reply = await self._generate_reply(thread, posts, resolved)
                if reply is None:
                    continue

                await self._persist_reply(thread, posts, resolved, reply)
                await asyncio.sleep(2.0)
        except Exception:
            logger.exception("run_discussion crashed for thread=%s", self.thread_id)

    async def _load_thread(self) -> dict[str, Any] | None:
        if not self.state.initial_load_done:
            thread = await self.db.fetch_thread(self.thread_id)
            if thread:
                self.state.cached_script = thread.get("script_json") or None
            self.state.initial_load_done = True
            return thread
        return await self.db.fetch_thread_state(self.thread_id)

    async def _ensure_script(self, thread: dict[str, Any]) -> bool:
        cached_script = self.state.cached_script or {}
        if isinstance(cached_script.get("turns"), list) and cached_script["turns"]:
            self.state.cached_script = cached_script
            return True

        agent_list = [self.agents[aid].persona for aid in thread["agent_ids"] if aid in self.agents]
        logger.info("Generating debate script for thread=%s", self.thread_id)
        generated = await generate_debate_script(thread["topic"], agent_list, thread["max_posts"])
        if generated.get("turns"):
            self.state.cached_script = generated
            await self.db.save_thread_script(self.thread_id, generated)
            logger.info("Script generated: %d turns for thread=%s", len(generated["turns"]), self.thread_id)
            return True

        logger.warning("Script generation failed for thread=%s, retrying in 5s", self.thread_id)
        await asyncio.sleep(5)
        return False

    def _refresh_user_reply_state(self, posts: list[dict[str, Any]]) -> None:
        for post in posts:
            if (
                post.get("agent_id") is None
                and not post.get("is_facilitator")
                and post.get("user_id") is not None
                and (self.state.last_user_post_id is None or post["id"] > self.state.last_user_post_id)
            ):
                self.state.last_user_post_id = post["id"]
                self.state.user_reply_pending = 2

    def _resolve_turn(self, thread: dict[str, Any], posts: list[dict[str, Any]]) -> ResolvedTurn | None:
        ai_posts = [post for post in posts if post.get("agent_id")]
        is_user_reply_turn = self.state.user_reply_pending > 0

        if is_user_reply_turn:
            last_ai_id = ai_posts[-1].get("agent_id") if ai_posts else None
            candidates = [
                agent_id for agent_id in thread["agent_ids"]
                if agent_id in self.agents and agent_id != last_ai_id
            ]
            if not candidates:
                candidates = [agent_id for agent_id in thread["agent_ids"] if agent_id in self.agents]
            if not candidates:
                self.state.user_reply_pending = 0
                return None
            speaker_id = random.choice(candidates)
            target_post = next((post for post in reversed(posts) if post["id"] == self.state.last_user_post_id), None)
            self.state.user_reply_pending -= 1
            return ResolvedTurn(
                speaker_id=speaker_id,
                target_post=target_post,
                directive="繝ｦ繝ｼ繧ｶ繝ｼ縺ｮ逋ｺ險縺ｫ蟇ｾ縺励※縲√≠縺ｪ縺溘・遶句ｴ縺九ｉ謖醍匱逧・↓蜿崎ｫ悶○繧医ら嶌謇九・蜑肴署繧貞ｴｩ縺励∬ｫ也せ繧帝強縺冗ｵ槭ｊ霎ｼ繧・",
                move_type="counter",
                phase=_get_phase(len(posts)),
                assigned_side="",
                is_user_reply_turn=True,
            )

        turns: list[dict[str, Any]] = (self.state.cached_script or {}).get("turns", [])
        while (
            self.state.script_turn_index < len(turns)
            and self.state.turn_fail_counts.get(self.state.script_turn_index, 0) >= _TURN_FAIL_LIMIT
        ):
            logger.warning(
                "Skipping turn=%d after %d failures for thread=%s",
                self.state.script_turn_index,
                _TURN_FAIL_LIMIT,
                self.thread_id,
            )
            self.state.script_turn_index += 1

        if self.state.script_turn_index >= len(turns):
            return None

        turn = turns[self.state.script_turn_index]
        speaker_id = str(turn.get("agent_id", ""))
        if speaker_id not in self.agents:
            candidates = [agent_id for agent_id in thread["agent_ids"] if agent_id in self.agents]
            if not candidates:
                raise RuntimeError(f"No agents available for thread={self.thread_id}")
            speaker_id = random.choice(candidates)

        reply_to_turn = turn.get("reply_to_turn")
        if reply_to_turn is not None and isinstance(reply_to_turn, int) and reply_to_turn < len(ai_posts):
            target_post = ai_posts[reply_to_turn]
        elif ai_posts:
            target_post = ai_posts[-1]
        else:
            target_post = None

        return ResolvedTurn(
            speaker_id=speaker_id,
            target_post=target_post,
            directive=str(turn.get("directive", "逶ｸ謇九・荳ｻ蠑ｵ縺ｫ謖醍匱逧・↓蜿崎ｫ悶○繧医ょ燕謠舌・蠑ｱ轤ｹ繧剃ｸ轤ｹ縺縺醍ｪ√￠")),
            move_type=str(turn.get("move_type", "attack")),
            phase=int(turn.get("phase", _get_phase(len(posts)))),
            assigned_side=str(turn.get("assigned_side", "")),
            is_user_reply_turn=False,
        )

    async def _generate_reply(
        self,
        thread: dict[str, Any],
        posts: list[dict[str, Any]],
        resolved: ResolvedTurn,
    ) -> dict[str, Any] | None:
        rag_context = {
            "thread_topic": thread["topic"],
            "conflict_axis": resolved.directive[:40],
            "current_tags": thread.get("topic_tags", []),
            "target_post": resolved.target_post or {},
        }
        rag_chunks = retrieve_chunks(resolved.speaker_id, rag_context)
        messages = build_script_post_messages(
            persona=self.agents[resolved.speaker_id].persona,
            directive=resolved.directive,
            move_type=resolved.move_type,
            target_post=resolved.target_post or {},
            recent_posts=posts[-6:],
            rag_chunks=rag_chunks,
            thread_topic=thread["topic"],
            phase=resolved.phase,
            assigned_side=resolved.assigned_side,
        )
        try:
            return await call_llm(messages)
        except LLMGenerationError:
            logger.warning(
                "LLM failed for thread=%s turn=%d speaker=%s",
                self.thread_id,
                self.state.script_turn_index,
                resolved.speaker_id,
            )
            if not resolved.is_user_reply_turn:
                self.state.turn_fail_counts[self.state.script_turn_index] = (
                    self.state.turn_fail_counts.get(self.state.script_turn_index, 0) + 1
                )
            await asyncio.sleep(1)
            return None

    async def _persist_reply(
        self,
        thread: dict[str, Any],
        posts: list[dict[str, Any]],
        resolved: ResolvedTurn,
        reply: dict[str, Any],
    ) -> None:
        phase_for_db = _get_phase(len(posts))
        if phase_for_db != thread.get("current_phase"):
            await self.db.update_thread_phase(self.thread_id, phase_for_db)

        post = await self.db.save_post(
            self.thread_id,
            resolved.speaker_id,
            {
                "reply_to": resolved.target_post["id"] if resolved.target_post else None,
                "content": reply["content"],
                "stance": reply.get("stance", "disagree"),
                "focus_axis": reply.get("main_axis", "rationalism"),
            },
            token_usage=int(reply.get("_token_usage", 0)),
        )
        self.state.event_counter += 1
        await self.push_fn(self.thread_id, post)

        if not resolved.is_user_reply_turn:
            self.state.script_turn_index += 1
            self.state.turn_fail_counts.pop(self.state.script_turn_index - 1, None)
