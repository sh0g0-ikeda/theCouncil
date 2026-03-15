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
from engine.llm import LLMGenerationError, assign_debate_roles, compress_history, decompose_topic_axes
from engine.debate_state import DebateState
from engine.selector import select_conflict_axis, select_next_agent, select_silent_agent, select_target_post
from models.agent import Agent, IdeologyVector

logger = logging.getLogger(__name__)

agents: dict[str, Agent] = {}
_discussion_tasks: dict[str, asyncio.Task[None]] = {}

# Keywords that indicate a moralistic/discussion-stopping post
_MORAL_KEYWORDS = {"差別", "倫理", "道徳", "人権", "正義", "に決まって", "絶対悪", "許されない", "当然", "べきでない"}


def _is_moral_suction(content: str) -> bool:
    """Return True if a post is likely to pull agents into unproductive moral discourse."""
    return sum(1 for kw in _MORAL_KEYWORDS if kw in content) >= 2

SPEED = {"slow": 8.5, "normal": 3.5, "fast": 0.3, "instant": 0.1, "paused": 999.0}


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


def _run_director(
    thread: dict[str, Any],
    debate: "DebateState",
    agents_dict: dict[str, Any],
) -> None:
    """Assign hidden per-agent directives based on debate state (no LLM, rule-based)."""
    participant_ids: list[str] = thread.get("agent_ids", [])
    uncovered_axes = debate.get_uncovered_axes()

    for agent_id in participant_ids:
        if agent_id not in agents_dict:
            continue
        # Don't overwrite an existing pending directive
        if debate.has_directive(agent_id):
            continue

        agent = agents_dict[agent_id]
        persona = agent.persona

        # Priority 1: Cover topic axes no one has touched yet
        if uncovered_axes:
            agent_recent = set(debate.get_agent_recent_axes(agent_id))
            candidates = [a for a in uncovered_axes if a not in agent_recent]
            if candidates:
                debate.push_directive(
                    agent_id,
                    f"「{candidates[0]}」の観点はまだ誰も触れていない。次の発言でこの軸から独自に切り込め。",
                )
                continue

        # Priority 2: Character drift — restore core position
        stance_hist = debate.stance_history.get(agent_id, [])
        if len(stance_hist) >= 3 and all(s in {"agree", "supplement"} for s in stance_hist[-3:]):
            non_neg = persona.get("speech_constraints", {}).get("non_negotiable", "")
            if non_neg:
                debate.push_directive(
                    agent_id,
                    f"直近3投が同意・補足続き。「{non_neg[:60]}」という核心に立ち返り、明確に反論せよ。",
                )
                continue

        # Priority 3: Push unused arsenal items the character hasn't deployed yet
        if debate.has_unused_arsenal(agent_id, persona):
            available = debate.get_available_arsenal(agent_id, persona)
            used = debate.used_arsenal_ids.get(agent_id, set())
            unused = [a for a in available if a["id"] not in used]
            if unused:
                debate.push_directive(
                    agent_id,
                    f"まだ使っていない固有の論点「{unused[0]['desc'][:45]}」を今回の論拠に使え。",
                )


def _should_direct(posts: list[dict[str, Any]]) -> bool:
    """Fire director every 4 posts, but not on the same turn as facilitator."""
    if not posts:
        return False
    n = len(posts)
    return n >= 4 and n % 4 == 0 and n % 7 != 0


def _should_facilitate(posts: list[dict[str, Any]]) -> bool:
    if not posts:
        return False
    if posts[-1].get("is_facilitator", False):
        return False
    n = len(posts)
    # Early definitional intervention: fire at post 3 to anchor key terms
    if n == 3:
        return True
    return n % 7 == 0


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
    roles_initialized = debate.roles_initialized()
    moral_suction_active = 0  # countdown: resist moral framing for N more posts

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

            # ── Role + axis initialization (once per thread) ───────────────
            if not roles_initialized:
                agent_list = [
                    agents[aid].persona
                    for aid in thread["agent_ids"]
                    if aid in agents
                ]
                try:
                    roles, axes = await asyncio.gather(
                        assign_debate_roles(thread["topic"], agent_list),
                        decompose_topic_axes(thread["topic"]),
                    )
                    debate.set_debate_roles(roles)
                    debate.set_topic_axes(axes)
                    roles_initialized = True
                    logger.info("roles=%s axes=%s thread=%s", roles, axes, thread_id)
                except Exception:
                    logger.warning("role/axis init failed", exc_info=True)
                    roles_initialized = True  # don't retry on error

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
                    # If user post contains moralizing language, arm the suction guard
                    if _is_moral_suction(p.get("content", "")):
                        moral_suction_active = 5  # next 5 AI posts get resistance directive

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

            # ── Silent director (rule-based, every 4 posts, no visible post) ──
            if _should_direct(posts):
                _run_director(thread, debate, agents)

            if _should_facilitate(posts):
                agent_display_names = {
                    aid: agents[aid].display_name
                    for aid in thread["agent_ids"] if aid in agents
                }
                facilitate = await make_facilitate(thread, posts, agent_display_names)
                if facilitate and facilitate.get("content"):
                    # Store axis assignments from rerail into DebateState
                    ax_assignments = facilitate.get("axis_assignments", [])
                    if ax_assignments:
                        debate.push_axis_assignments(ax_assignments)
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
            # Hard-exclude agents who spoke in the last 3 AI posts (prevents 2-bot loop)
            recent_ai_speakers = {p["agent_id"] for p in posts[-3:] if p.get("agent_id")}
            if user_reply_pending > 0:
                try:
                    speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=debate)
                except ValueError:
                    failed_agents.clear()
                    await asyncio.sleep(0.5)
                    continue
            else:
                retaliator = debate.pop_retaliator(
                    thread["agent_ids"], failed_agents | recent_ai_speakers, last_speaker_id or ""
                )
                if retaliator:
                    speaker_id = retaliator
                else:
                    stagnating = _detect_stagnation(posts, debate)
                    hard_excluded = failed_agents | recent_ai_speakers
                    if stagnating:
                        silent = select_silent_agent(thread, agents, posts, excluded_agent_ids=hard_excluded)
                        speaker_id = silent if silent else _fallback_speaker(thread, agents, posts, hard_excluded)
                        newcomer_hint = True
                    else:
                        try:
                            speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=hard_excluded, debate_state=debate)
                        except ValueError:
                            # Relax exclusion if no candidates (small thread)
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
            is_first_post = not any(p.get("agent_id") == speaker_id for p in posts)
            recent_others = [
                p["content"] for p in posts[-6:]
                if p.get("agent_id") and p.get("agent_id") != speaker_id
            ]
            available_arsenal = debate.get_available_arsenal(speaker_id, agents[speaker_id].persona)
            stance_drift = debate.is_stance_drifting(speaker_id)
            arsenal_novelty = debate.has_unused_arsenal(speaker_id, agents[speaker_id].persona)
            debate_role = debate.get_debate_role(speaker_id)
            forced_axis = debate.pop_forced_axis(speaker_id)
            private_directive = debate.pop_directive(speaker_id)
            agent_recent_axes = debate.get_agent_recent_axes(speaker_id)
            uncovered_axes = debate.get_uncovered_axes()
            is_user_post_reply = (user_reply_pending > 0 and target is not None and target.get("user_id") is not None)
            target_is_moral = is_user_post_reply and _is_moral_suction(target.get("content", "") if target else "")
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
                "debate_role": debate_role,
                "forced_axis": forced_axis or "",
                "private_directive": private_directive or "",
                "topic_axes": debate.topic_axes,
                "agent_recent_axes": agent_recent_axes,
                "uncovered_axes": uncovered_axes,
                "stance_drift_warning": stance_drift,
                "arsenal_novelty_push": arsenal_novelty,
                "is_first_post": is_first_post,
                "user_post_reply": is_user_post_reply,
                "moral_suction_warning": target_is_moral or moral_suction_active > 0,
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
            if moral_suction_active > 0:
                moral_suction_active -= 1
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
        weights = [8, 4, 0, 0, 0, 0]   # early: define/differentiate ONLY — no attack yet
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
