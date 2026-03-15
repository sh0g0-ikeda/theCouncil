from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from db.client import get_db
from engine.facilitator import make_facilitate
from engine.llm import LLMGenerationError, compress_history
from engine.debate_state import DebateState
from engine.selector import select_conflict_axis, select_next_agent, select_silent_agent, select_target_post
from models.agent import Agent, IdeologyVector

logger = logging.getLogger(__name__)

agents: dict[str, Agent] = {}
_discussion_tasks: dict[str, asyncio.Task[None]] = {}

SPEED = {"slow": 10.0, "normal": 5.0, "fast": 1.5, "instant": 0.1, "paused": 999.0}


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
    user_reply_pending = 0
    last_user_post_id: int | None = None
    try:
        saved_state = await db.load_debate_state(thread_id)
    except Exception:
        logger.warning("load_debate_state failed (table may not exist yet)", exc_info=True)
        saved_state = None
    debate = DebateState.from_dict(saved_state) if saved_state else DebateState()
    last_speaker_id: str | None = None
    event_counter = 0

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

            # Detect new user posts and queue 3 agent replies
            for p in posts:
                if (
                    p.get("agent_id") is None
                    and not p.get("is_facilitator")
                    and p.get("user_id") is not None
                    and (last_user_post_id is None or p["id"] > last_user_post_id)
                ):
                    last_user_post_id = p["id"]
                    user_reply_pending = 3

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

            # ── Speaker selection ──────────────────────────────────────────
            # Priority: user-reply > retaliation > random-event > normal
            newcomer_hint = False
            if user_reply_pending > 0:
                try:
                    speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=debate)
                except ValueError:
                    failed_agents.clear()
                    await asyncio.sleep(0.5)
                    continue
            else:
                retaliator = debate.pop_retaliator(
                    thread["agent_ids"], failed_agents, last_speaker_id or ""
                )
                if retaliator:
                    speaker_id = retaliator
                else:
                    stagnating = _detect_stagnation(posts, debate)
                    if stagnating and event_counter % 2 == 0:
                        silent = select_silent_agent(thread, agents, posts, excluded_agent_ids=failed_agents)
                        speaker_id = silent if silent else _fallback_speaker(thread, agents, posts, failed_agents)
                        newcomer_hint = True
                    else:
                        try:
                            speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=debate)
                        except ValueError:
                            failed_agents.clear()
                            await asyncio.sleep(0.5)
                            continue

            # ── Target selection ───────────────────────────────────────────
            if user_reply_pending > 0:
                target = next((p for p in reversed(posts) if p["id"] == last_user_post_id), None)
                if target is None:
                    user_reply_pending = 0
                    target = select_target_post(posts, speaker_id, agents)
            else:
                target = select_target_post(posts, speaker_id, agents)
            target_id = target["agent_id"] if target and target.get("agent_id") else None
            axis = select_conflict_axis(speaker_id, target_id, agents) if target_id else "rationalism"

            # ── Debate function selection ───────────────────────────────────
            stagnating = _detect_stagnation(posts, debate)
            anger_override = debate.get_aggression_boost(speaker_id, target_id)
            if anger_override:
                debate_fn = anger_override
            elif stagnating:
                debate_fn = random.choice(["concretize", "differentiate", "attack"])
            else:
                debate_fn = _select_debate_function(speaker_id, phase, agents, debate)

            # ── Build context ──────────────────────────────────────────────
            recent_posts = posts[compressed_upto:]
            # Expand self-history to 4 for novelty detection
            recent_self = [p["content"] for p in posts[-8:] if p.get("agent_id") == speaker_id][-4:]
            recent_others = [
                p["content"] for p in posts[-6:]
                if p.get("agent_id") and p.get("agent_id") != speaker_id
            ]
            available_arsenal = debate.get_available_arsenal(speaker_id, agents[speaker_id].persona)
            stance_drift = debate.is_stance_drifting(speaker_id)
            arsenal_novelty = debate.has_unused_arsenal(speaker_id, agents[speaker_id].persona)
            context = {
                "thread_topic": thread["topic"],
                "current_tags": thread["topic_tags"],
                "target_post": target or {},
                "conflict_axis": axis,
                "role": _role_for_phase(phase),
                "phase": phase,
                "conversation_summary": _build_conversation_summary(compressed_summary, recent_posts),
                "debate_function": debate_fn,
                "available_arsenal": available_arsenal,
                "internal_state": debate.get_internal_state(speaker_id),
                "recent_self_contents": recent_self,
                "recent_other_contents": recent_others,
                "stagnation": stagnating,
                "newcomer_event": newcomer_hint,
                "stance_drift_warning": stance_drift,
                "arsenal_novelty_push": arsenal_novelty,
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

            focus_axis = reply.get("main_axis", axis)
            used_arsenal_id = reply.get("used_arsenal_id")
            arsenal_cooldown = debate.get_arsenal_cooldown_for_id(agents[speaker_id].persona, used_arsenal_id or "")
            stance = reply.get("stance", "disagree")
            post = await db.save_post(
                thread_id,
                speaker_id,
                {
                    "reply_to": target["id"] if target else None,
                    "content": reply["content"],
                    "stance": stance,
                    "focus_axis": focus_axis,
                },
                token_usage=int(reply.get("_token_usage", 0)),
            )
            failed_agents.clear()
            last_speaker_id = speaker_id
            event_counter += 1
            debate.record_post(
                speaker_id,
                target or {},
                focus_axis,
                debate_function=debate_fn,
                used_arsenal_id=used_arsenal_id,
                arsenal_cooldown=arsenal_cooldown,
                stance=stance,
            )
            if user_reply_pending > 0:
                user_reply_pending -= 1
            await push_fn(thread_id, post)
            if event_counter % 5 == 0:
                try:
                    await db.save_debate_state(thread_id, debate.to_dict())
                except Exception:
                    logger.warning("save_debate_state failed (table may not exist yet)", exc_info=True)
            await asyncio.sleep(SPEED.get(thread["speed_mode"], 5.0))
    finally:
        _discussion_tasks.pop(thread_id, None)


def _fallback_speaker(
    thread: dict[str, Any],
    agents: dict[str, Agent],
    posts: list[dict[str, Any]],
    failed_agents: set[str],
) -> str:
    """Fallback speaker selection ignoring stagnation heuristics."""
    try:
        return select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=None)
    except ValueError:
        # All agents excluded — clear failures and pick any eligible
        participant_ids: list[str] = thread["agent_ids"]
        candidates = [a for a in participant_ids if a in agents]
        if not candidates:
            raise
        return random.choice(candidates)


_DEBATE_FUNCTIONS = ["define", "differentiate", "attack", "steelman", "concretize", "synthesize"]


def _select_debate_function(speaker_id: str, phase: int, agents_dict: dict[str, Any], debate: Any) -> str:
    """Select a debate function based on phase, persona preference, and overuse avoidance."""
    agent = agents_dict.get(speaker_id)
    aggressiveness = 3
    preference = ""
    if agent:
        constraints = agent.persona.get("speech_constraints", {})
        aggressiveness = constraints.get("aggressiveness") or agent.persona.get("debate_style", {}).get("aggressiveness", 3)
        preference = agent.persona.get("debate_function_preference", "")

    # Phase weights: [define, differentiate, attack, steelman, concretize, synthesize]
    if phase <= 1:
        weights = [5, 5, 1, 0, 1, 0]   # early: define/differentiate only
    elif phase == 2:
        weights = [1, 2, 4, 1, 4, 1]   # mid: attack + concretize
    elif phase == 3:
        weights = [0, 1, 5, 3, 3, 1]   # heat: heavy attack + steelman
    elif phase == 4:
        weights = [1, 1, 2, 2, 3, 5]   # late: synthesize and concretize
    else:
        weights = [0, 0, 3, 1, 2, 4]   # final: synthesize/show splits

    if aggressiveness >= 4:
        weights[2] += 2   # attack
        weights[3] += 1   # steelman
    elif aggressiveness <= 2:
        weights[0] += 1   # define
        weights[4] += 2   # concretize

    if preference in _DEBATE_FUNCTIONS:
        weights[_DEBATE_FUNCTIONS.index(preference)] += 3

    # Penalize overused functions
    for i, fn in enumerate(_DEBATE_FUNCTIONS):
        if debate.is_function_overused(fn):
            weights[i] = max(0, weights[i] - 2)

    return random.choices(_DEBATE_FUNCTIONS, weights=weights)[0]


def _detect_stagnation(posts: list[dict[str, Any]], debate: DebateState | None = None) -> bool:
    """3-dimensional stagnation: speaker / axis / function diversity."""
    ai_posts = [p for p in posts[-6:] if p.get("agent_id")]
    if len(ai_posts) < 4:
        return False

    # 1. Speaker stagnation: ≤2 unique speakers in last 6 AI posts
    if len({p["agent_id"] for p in ai_posts}) <= 2:
        return True

    # 2. Axis stagnation: all same focus_axis in last 5 AI posts
    axes = [p.get("focus_axis") for p in ai_posts[-5:] if p.get("focus_axis")]
    if len(axes) >= 4 and len(set(axes)) == 1:
        return True

    # 3. Function stagnation: same debate function dominates (via DebateState)
    if debate and debate.is_function_stagnating():
        return True

    # 4. Echo chamber (same axis across 5 recent_axes in DebateState)
    if debate and debate.is_echo_chamber():
        return True

    return False


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
    return {1: "counter", 2: "counter", 3: "counter", 4: "shift", 5: "counter"}[phase]


def _build_conversation_summary(compressed_summary: str, recent_posts: list[dict[str, Any]]) -> str:
    recent_window = recent_posts if len(recent_posts) <= 10 else recent_posts[-5:]
    recent_summary = " / ".join(
        f"{post.get('display_name') or post.get('agent_id') or '?'}: {post['content'][:50]}"
        for post in recent_window
    )
    if compressed_summary and recent_summary:
        return f"圧縮履歴: {compressed_summary} / 直近: {recent_summary}"
    return compressed_summary or recent_summary
