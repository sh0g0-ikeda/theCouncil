from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from db.client import get_db
from engine.facilitator import make_facilitate
from engine.llm import LLMGenerationError, assign_debate_frame, build_script_post_messages, call_llm, compress_history, decompose_topic_axes, generate_debate_script
from engine.debate_state import DebateState
from engine.rag import retrieve_chunks
from engine.selector import select_conflict_axis, select_next_agent, select_silent_agent, select_target_post
from engine.validator import SemanticPostAnalysis, summarize_target_claim
from models.agent import Agent, IdeologyVector

logger = logging.getLogger(__name__)

agents: dict[str, Agent] = {}
_discussion_tasks: dict[str, asyncio.Task[None]] = {}
_TOKEN_PATTERN = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)

# Particles and common short verbs to exclude from noun extraction
_JP_PARTICLES = {
    "は", "が", "を", "に", "で", "と", "も", "の", "へ", "や", "な", "か",
    "て", "し", "れ", "せ", "ず", "ない", "する", "ある", "いる", "なる",
    "これ", "それ", "あれ", "ここ", "そこ", "もの", "こと", "ため", "よう",
}
_META_SUMMARY_PATTERNS = (
    re.compile(r"(?:結局|要するに).*(?:論点|争点)"),
    re.compile(r"(?:論点|争点).*(?:何|どこ)"),
    re.compile(r"(?:まとめ|整理|要約)"),
    re.compile(r"(?:止まった|続けて)"),
)

# Keywords that indicate a moralistic/discussion-stopping post
_MORAL_KEYWORDS = {"差別", "倫理", "道徳", "人権", "正義", "に決まって", "絶対悪", "許されない", "当然", "べきでない"}


def _extract_abstract_nouns(topic: str, max_nouns: int = 5) -> list[str]:
    """Extract 2+ char noun-like tokens from topic, excluding common particles/verbs."""
    tokens = _TOKEN_PATTERN.findall(topic or "")
    seen: list[str] = []
    for token in tokens:
        if len(token) < 2:
            continue
        if token in _JP_PARTICLES:
            continue
        if token not in seen:
            seen.append(token)
        if len(seen) >= max_nouns:
            break
    return seen


def seed_subquestions(topic: str) -> list[str]:
    """Pure function (no LLM): extract subquestions from the topic using keyword heuristics.

    Generates 4 families of subquestions:
    - 定義系
    - 実現条件系
    - 失敗条件系
    - 移行メカニズム系
    """
    nouns = _extract_abstract_nouns(topic, max_nouns=2)
    subquestions: list[str] = []
    for noun in nouns:
        subquestions.append(f"「{noun}」とは何か、どのように定義されるか")
        subquestions.append(f"「{noun}」はいかなる条件で実現するか、それを妨げる要因は何か")
        subquestions.append(f"「{noun}」が失敗するとしたらなぜか、その弱点は何か")
        subquestions.append(f"現状から「{noun}」への移行はどう起きるか、その過程で何が変わるか")
    return subquestions[:8]


def _is_moral_suction(content: str) -> bool:
    """Return True if a post is likely to pull agents into unproductive moral discourse."""
    return sum(1 for kw in _MORAL_KEYWORDS if kw in content) >= 2


def _is_missing_debate_state_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "42p01" in text or "relation" in text or "does not exist" in text


def _extract_directive_type(text: str) -> str:
    match = re.search(r"MISSION:([a-z_]+)", text or "")
    return match.group(1) if match else ""


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}


def _sanitize_topic_axes(raw_axes: list[str], thread_topic: str, topic_tags: list[str]) -> list[str]:
    candidates: list[str] = []
    for axis in raw_axes:
        value = str(axis or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    tag_axes = [str(tag).strip() for tag in topic_tags if str(tag).strip()]
    if not candidates:
        return tag_axes[:6] or ["rationalism"]

    topic_terms = _tokenize(" ".join([thread_topic, *tag_axes]))

    def relevance(axis: str) -> int:
        return len(_tokenize(axis) & topic_terms)

    relevant = [axis for axis in candidates if relevance(axis) > 0]
    if relevant:
        merged = relevant + [tag for tag in tag_axes if tag not in relevant]
        return merged[:6]
    if tag_axes:
        merged: list[str] = []
        for axis in tag_axes + candidates:
            if axis and axis not in merged:
                merged.append(axis)
        return merged[:6]
    return candidates[:6]


def _classify_user_intervention(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    for pattern in _META_SUMMARY_PATTERNS:
        if pattern.search(text):
            return "summarize"
    return ""


def _select_meta_speaker(
    participant_ids: list[str],
    posts: list[dict[str, Any]],
    agents_dict: dict[str, Agent],
    excluded: set[str],
) -> str:
    post_counts = {
        agent_id: sum(1 for post in posts if post.get("agent_id") == agent_id)
        for agent_id in participant_ids
    }
    last_2 = {post["agent_id"] for post in posts[-2:] if post.get("agent_id")}

    def preference_rank(agent_id: str) -> int:
        preference = str(agents_dict[agent_id].persona.get("debate_function_preference", ""))
        if preference == "synthesize":
            return 0
        if preference == "differentiate":
            return 1
        if preference == "concretize":
            return 2
        return 3

    ranked: list[tuple[tuple[int, int, int, str], str]] = []
    for agent_id in participant_ids:
        if agent_id not in agents_dict or agent_id in excluded:
            continue
        rank = (
            1 if agent_id in last_2 else 0,
            preference_rank(agent_id),
            post_counts.get(agent_id, 0),
            agent_id,
        )
        ranked.append((rank, agent_id))
    if not ranked:
        raise ValueError("No eligible agents available")
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _determine_retrieval_mode(
    debate_function: str,
    pending_definition_terms: list[str],
    constraint_kind: str,
) -> str:
    if constraint_kind == "tradeoff":
        return "tradeoff"
    if constraint_kind == "refocus":
        return "counterexample"
    if pending_definition_terms and debate_function in {"define", "differentiate"}:
        return "definition"
    if debate_function in {"attack", "steelman"}:
        return "counterexample"
    if debate_function == "concretize":
        return "concrete"
    if debate_function == "synthesize":
        return "synthesis"
    return "default"



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
    posts: list[dict[str, Any]] | None = None,
) -> None:
    """Assign structured MISSION directives per agent (no LLM, rule-based).

    Priority order:
      1. rebut_core_claim  — unanswered attack against this agent
      2. defend_self_consistency — agreement streak >= 2 (restore non_negotiable)
      3. echo_break        — echo chamber: force a different axis
      4. deepen_shallow_axis — contest introduced-but-unrebutted axes (with specific claim)
      5. introduce_new_axis — only when no shallow axes exist
      6. use_weapon        — unused arsenal items
    """
    participant_ids: list[str] = thread.get("agent_ids", [])
    recent_posts: list[dict[str, Any]] = posts or []
    uncovered_axes = debate.get_uncovered_axes()

    for agent_id in participant_ids:
        if agent_id not in agents_dict:
            continue
        if debate.has_directive(agent_id):
            continue

        agent = agents_dict[agent_id]
        persona = agent.persona
        non_neg = persona.get("speech_constraints", {}).get("non_negotiable", "")

        # Priority 1: rebut_core_claim — unanswered attack against this agent
        open_attack = debate.get_strongest_open_attack(agent_id)
        if open_attack:
            attacker_id, snippet = open_attack
            attacker_name = agents_dict[attacker_id].display_name if attacker_id in agents_dict else attacker_id
            # Include claim conclusion if available
            conclusion_hint = ""
            if hasattr(debate, "open_claim_structures"):
                for cs_entry in reversed(debate.open_claim_structures[-10:]):
                    if cs_entry.get("agent_id") == attacker_id:
                        conclusion = cs_entry.get("structure", {}).get("conclusion", "")
                        if conclusion:
                            conclusion_hint = f"結論「{conclusion[:40]}」を崩せ。"
                        break
            debate.push_directive(
                agent_id,
                f"MISSION:rebut_core_claim｜{attacker_name}の「{snippet[:50]}」が未反論のまま残っている。"
                f"{conclusion_hint}前提・定義・証拠の弱点を一点だけ選んで直接崩せ。迂回や言い換えは失格。",
            )
            continue

        # Priority 2: defend_self_consistency — agreement streak
        streak = debate.agreement_streak.get(agent_id, 0)
        if streak >= 2 and non_neg:
            debate.push_directive(
                agent_id,
                f"MISSION:defend_self_consistency｜直近{streak}投が同意・補足続き。"
                f"「{non_neg[:55]}」という核心に立ち返り、今回は必ず disagree か shift で切り返せ。",
            )
            continue

        # Priority 3: echo_break — break echo chamber axis
        if debate.is_echo_chamber():
            agent_recent = set(debate.get_agent_recent_axes(agent_id))
            candidates = [a for a in uncovered_axes if a not in agent_recent]
            if candidates:
                debate.push_directive(
                    agent_id,
                    f"MISSION:echo_break｜同じ軸での議論が続いている。「{candidates[0]}」の観点だけで斬り込め。他の軸に触れるな。",
                )
                continue

        # Priority 4: deepen_shallow_axis — contest an introduced-but-unrebutted axis
        shallow = debate.get_shallow_axes()
        if shallow:
            axis_to_contest = shallow[0]
            # Prefer bots that did NOT introduce this axis (someone else contests it)
            introducer = next(
                (aid for aid, axes in debate.agent_axis_usage.items() if axis_to_contest in axes),
                None,
            )
            if agent_id != introducer:
                # Find the most recent specific claim about this axis (for targeted rebuttal)
                claim_post = next(
                    (
                        p for p in reversed(recent_posts[-20:])
                        if p.get("focus_axis") == axis_to_contest
                        and p.get("agent_id")
                        and p.get("agent_id") != agent_id
                    ),
                    None,
                )
                claim_hint = ""
                if claim_post:
                    who = claim_post.get("display_name") or claim_post.get("agent_id") or "相手"
                    claim_hint = f"特に{who}の「{claim_post['content'][:45]}」を標的にせよ。"
                debate.push_directive(
                    agent_id,
                    f"MISSION:deepen_axis｜「{axis_to_contest}」軸がまだ真に反論されていない。"
                    f"{claim_hint}この主張の根幹前提を1つだけ特定し、その前提の弱点を一点で崩せ。",
                )
                continue

        # Priority 5: introduce_new_axis — only if no shallow axes exist
        if not shallow and uncovered_axes:
            agent_recent = set(debate.get_agent_recent_axes(agent_id))
            candidates = [a for a in uncovered_axes if a not in agent_recent]
            if candidates:
                debate.push_directive(
                    agent_id,
                    f"MISSION:introduce_new_axis｜「{candidates[0]}」の観点はまだ誰も触れていない。この軸だけで切り込め。",
                )
                continue

        # Priority 6: use_weapon — deploy unused arsenal item
        if debate.has_unused_arsenal(agent_id, persona):
            available = debate.get_available_arsenal(agent_id, persona)
            used = debate.used_arsenal_ids.get(agent_id, set())
            unused = [a for a in available if a["id"] not in used]
            if unused:
                debate.push_directive(
                    agent_id,
                    f"MISSION:use_weapon｜「{unused[0]['desc'][:45]}」という固有の論拠をまだ使っていない。今回これを核心に据えて論じよ。",
                )


def _needs_director(posts: list[dict[str, Any]], debate: "DebateState") -> bool:
    """Fire director when debate conditions require intervention (event-driven)."""
    ai_posts = [p for p in posts if p.get("agent_id")]
    if len(ai_posts) < 3:
        return False
    # Always fire when unanswered attacks exist
    if debate.has_any_open_attacks():
        return True
    # Any agent has agreement streak >= 2
    if any(v >= 2 for v in debate.agreement_streak.values()):
        return True
    # Echo chamber detected
    if debate.is_echo_chamber():
        return True
    # Same axis repeated in last 2 AI posts
    recent_axes = [p.get("focus_axis") for p in ai_posts[-2:] if p.get("focus_axis")]
    if len(recent_axes) == 2 and recent_axes[0] == recent_axes[1]:
        return True
    # Periodic sweep for uncovered axes (every 4 posts, as baseline)
    n = len(ai_posts)
    if n >= 4 and n % 4 == 0 and debate.get_uncovered_axes():
        return True
    return False


def _should_facilitate(posts: list[dict[str, Any]], debate: "DebateState | None" = None) -> bool:
    """Event-driven facilitator: fires only when structural problems are detected."""
    if not posts or posts[-1].get("is_facilitator", False):
        return False
    # Camp reassert alert: trigger facilitation immediately
    if debate is not None and "camp_reassert" in getattr(debate, "alerts", set()):
        return True
    # Minimum gap: 5 posts since last facilitation
    structural_posts = [p for p in posts if p.get("agent_id") or p.get("is_facilitator")]
    for p in structural_posts[-5:]:
        if p.get("is_facilitator"):
            return False
    ai_posts = [p for p in posts if p.get("agent_id")]
    n_ai = len(ai_posts)
    # Early definitional: once at post 3 only
    if len(posts) == 3:
        return True
    if n_ai < 4:
        return False
    # Condition 1: Same axis 3 consecutive (echo chamber forming)
    recent_axes = [p.get("focus_axis") for p in ai_posts[-3:] if p.get("focus_axis")]
    if len(recent_axes) == 3 and len(set(recent_axes)) == 1:
        return True
    # Condition 2: Soft-stance domination (4+ agree/supplement in last 5 AI posts)
    recent_stances = [p.get("stance") for p in ai_posts[-5:] if p.get("stance") and p["stance"] != "facilitate"]
    if len(recent_stances) >= 4 and sum(1 for s in recent_stances if s in {"agree", "supplement"}) >= 4:
        return True
    # Condition 3: Parallel monologues (no cross-targeting for 5 posts)
    if n_ai >= 5:
        no_replies = sum(1 for p in ai_posts[-5:] if not p.get("reply_to"))
        if no_replies >= 4:
            return True
    return False


_TURN_FAIL_LIMIT = 3  # skip a script turn after this many consecutive LLM failures


async def run_discussion(
    thread_id: str,
    push_fn: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> None:
    logger.info("run_discussion started for thread=%s", thread_id)
    db = get_db()
    event_counter = 0
    user_reply_pending = 0
    last_user_post_id: int | None = None
    # ③ script cached outside loop — only (re)fetched when None
    cached_script: dict[str, Any] | None = None
    # ① separate counter: only advances on script turns, not user-reply turns
    script_turn_index = 0
    # ④ per-(script)turn failure counter
    turn_fail_counts: dict[int, int] = {}
    # initial_load_done: True after first full fetch_thread (which includes script_json)
    initial_load_done = False

    try:
        while True:
            if not initial_load_done:
                # First iteration: full fetch (includes script_json for cache priming)
                thread = await db.fetch_thread(thread_id)
                if thread:
                    cached_script = thread.get("script_json") or None
                initial_load_done = True
            else:
                # Subsequent iterations: lightweight fetch (no script_json ~20KB JSONB)
                thread = await db.fetch_thread_state(thread_id)

            if not thread or thread.get("deleted_at"):
                logger.info("run_discussion: thread=%s gone/deleted, stopping", thread_id)
                break
            if thread["state"] == "completed":
                logger.info("run_discussion: thread=%s completed, stopping", thread_id)
                break
            if thread["state"] != "running":
                await asyncio.sleep(2)
                continue

            # paused check — before any LLM work
            if thread.get("speed_mode") == "paused":
                await asyncio.sleep(5)
                continue

            # ── Generate or load script (③ use cache, avoid per-iter DB traffic) ──
            if cached_script is None:
                cached_script = {}
            if not cached_script or not isinstance(cached_script.get("turns"), list) or not cached_script["turns"]:
                agent_list = [agents[aid].persona for aid in thread["agent_ids"] if aid in agents]
                logger.info("Generating debate script for thread=%s", thread_id)
                generated = await generate_debate_script(thread["topic"], agent_list, thread["max_posts"])
                if generated.get("turns"):
                    cached_script = generated
                    await db.save_thread_script(thread_id, cached_script)
                    logger.info("Script generated: %d turns for thread=%s", len(cached_script["turns"]), thread_id)
                else:
                    logger.warning("Script generation failed for thread=%s, retrying in 5s", thread_id)
                    await asyncio.sleep(5)
                    continue

            turns: list[dict[str, Any]] = cached_script.get("turns", [])
            posts = await db.fetch_posts(thread_id)

            if len(posts) >= thread["max_posts"]:
                await db.update_thread_state(thread_id, "completed")
                break

            # ── Detect new user posts → queue 2 AI replies ─────────────────
            for p in posts:
                if (
                    p.get("agent_id") is None
                    and not p.get("is_facilitator")
                    and p.get("user_id") is not None
                    and (last_user_post_id is None or p["id"] > last_user_post_id)
                ):
                    last_user_post_id = p["id"]
                    user_reply_pending = 2

            # ── Determine speaker + target + directive ─────────────────────
            ai_posts = [p for p in posts if p.get("agent_id")]
            is_user_reply_turn = user_reply_pending > 0

            if is_user_reply_turn:
                # ① user-reply posts do NOT advance script_turn_index
                last_ai_id = ai_posts[-1].get("agent_id") if ai_posts else None
                candidates = [
                    aid for aid in thread["agent_ids"]
                    if aid in agents and aid != last_ai_id
                ]
                if not candidates:
                    candidates = [aid for aid in thread["agent_ids"] if aid in agents]
                if not candidates:
                    user_reply_pending = 0
                    continue
                speaker_id = random.choice(candidates)
                target_post = next((p for p in reversed(posts) if p["id"] == last_user_post_id), None)
                directive = "ユーザーの発言に対して、あなたの立場から挑発的に反論せよ。相手の前提を崩し、論点を鋭く絞り込め"
                move_type = "counter"
                phase = _get_phase(len(posts))
                assigned_side = ""
                user_reply_pending -= 1
            else:
                # ④ skip turns that have exceeded failure limit
                while (
                    script_turn_index < len(turns)
                    and turn_fail_counts.get(script_turn_index, 0) >= _TURN_FAIL_LIMIT
                ):
                    logger.warning(
                        "Skipping turn=%d after %d failures for thread=%s",
                        script_turn_index, _TURN_FAIL_LIMIT, thread_id,
                    )
                    script_turn_index += 1

                if script_turn_index >= len(turns):
                    await db.update_thread_state(thread_id, "completed")
                    break

                turn = turns[script_turn_index]
                speaker_id = str(turn.get("agent_id", ""))
                if speaker_id not in agents:
                    candidates = [aid for aid in thread["agent_ids"] if aid in agents]
                    if not candidates:
                        logger.error("No agents available for thread=%s, stopping", thread_id)
                        break
                    speaker_id = random.choice(candidates)

                reply_to_turn = turn.get("reply_to_turn")
                if reply_to_turn is not None and isinstance(reply_to_turn, int) and reply_to_turn < len(ai_posts):
                    target_post = ai_posts[reply_to_turn]
                elif ai_posts:
                    target_post = ai_posts[-1]
                else:
                    target_post = None

                directive = str(turn.get("directive", "相手の主張に挑発的に反論せよ。前提の弱点を一点だけ突け"))
                move_type = str(turn.get("move_type", "attack"))
                phase = int(turn.get("phase", _get_phase(len(posts))))
                assigned_side = str(turn.get("assigned_side", ""))

            # ── RAG retrieval ──────────────────────────────────────────────
            rag_context = {
                "thread_topic": thread["topic"],
                "conflict_axis": directive[:40],
                "current_tags": thread.get("topic_tags", []),
                "target_post": target_post or {},
            }
            rag_chunks = retrieve_chunks(speaker_id, rag_context)

            # ── Build prompt and call LLM ──────────────────────────────────
            messages = build_script_post_messages(
                persona=agents[speaker_id].persona,
                directive=directive,
                move_type=move_type,
                target_post=target_post or {},
                recent_posts=posts[-6:],
                rag_chunks=rag_chunks,
                thread_topic=thread["topic"],
                phase=phase,
                assigned_side=assigned_side,
            )

            try:
                reply = await call_llm(messages)
            except LLMGenerationError:
                logger.warning(
                    "LLM failed for thread=%s turn=%d speaker=%s", thread_id, script_turn_index, speaker_id
                )
                if not is_user_reply_turn:
                    # ④ count failures per script turn
                    turn_fail_counts[script_turn_index] = turn_fail_counts.get(script_turn_index, 0) + 1
                await asyncio.sleep(1)
                continue

            phase_for_db = _get_phase(len(posts))
            if phase_for_db != thread.get("current_phase"):
                await db.update_thread_phase(thread_id, phase_for_db)

            post = await db.save_post(
                thread_id,
                speaker_id,
                {
                    "reply_to": target_post["id"] if target_post else None,
                    "content": reply["content"],
                    "stance": reply.get("stance", "disagree"),
                    "focus_axis": reply.get("main_axis", "rationalism"),
                },
                token_usage=int(reply.get("_token_usage", 0)),
            )
            event_counter += 1
            await push_fn(thread_id, post)

            # ① advance script turn only when this was a script turn
            if not is_user_reply_turn:
                script_turn_index += 1
                turn_fail_counts.pop(script_turn_index - 1, None)  # clean up on success

            await asyncio.sleep(0.3)

    except Exception:
        logger.exception("run_discussion crashed for thread=%s", thread_id)
        raise
    finally:
        logger.info("run_discussion ended for thread=%s posts_generated=%d", thread_id, event_counter)
        _discussion_tasks.pop(thread_id, None)





def _prioritize_speaker(
    participant_ids: list[str],
    posts: list[dict[str, Any]],
    debate: DebateState,
    agents_dict: dict[str, Any],
    excluded: set[str],
) -> str | None:
    """Return a deterministic obligation-first speaker, or None."""
    last_2 = {p["agent_id"] for p in posts[-2:] if p.get("agent_id")}
    last_ai_speaker = next((p.get("agent_id") for p in reversed(posts) if p.get("agent_id")), None)
    last_side = debate.get_agent_side(last_ai_speaker) if last_ai_speaker else ""
    post_counts = {
        agent_id: sum(1 for post in posts if post.get("agent_id") == agent_id)
        for agent_id in participant_ids
    }
    ranked: list[tuple[tuple[int, int, int, int, str], str]] = []
    for agent_id in participant_ids:
        if agent_id not in agents_dict or agent_id in excluded:
            continue

        if debate.get_priority_subquestion_for(agent_id):
            obligation = 6
        elif debate.has_pending_definition_response(agent_id):
            obligation = 5
        elif debate.has_open_attack_against(agent_id):
            obligation = 4
        elif debate.peek_directive(agent_id):
            obligation = 3
        elif debate.get_priority_post_id_for(agent_id) is not None:
            obligation = 2
        elif debate.agreement_streak.get(agent_id, 0) >= 2:
            obligation = 1
        elif debate.has_unused_arsenal(agent_id, agents_dict[agent_id].persona):
            obligation = 1
        else:
            obligation = 0

        if obligation <= 0:
            continue

        own_axes = debate.get_agent_recent_axes(agent_id)
        recent_axis_window = own_axes[-3:]
        if recent_axis_window:
            from collections import Counter
            repeated_axis_penalty = 1 if Counter(recent_axis_window).most_common(1)[0][1] >= 2 else 0
        else:
            repeated_axis_penalty = 0
        recent_speaker_penalty = 1 if agent_id in last_2 else 0
        same_side_penalty = 1 if last_side and debate.get_agent_side(agent_id) == last_side else 0
        same_camp_penalty = 1 if (
            last_side
            and debate.get_agent_side(agent_id) == last_side
            and debate.get_camp_function(agent_id)
            and debate.get_camp_function(agent_id) == debate.get_camp_function(last_ai_speaker)
        ) else 0
        rank = (
            -obligation,
            recent_speaker_penalty,
            same_side_penalty,
            same_camp_penalty,
            repeated_axis_penalty,
            post_counts.get(agent_id, 0),
            agent_id,
        )
        ranked.append((rank, agent_id))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


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


def _select_debate_function(
    speaker_id: str,
    phase: int,
    agents_dict: dict[str, Any],
    debate: Any,
    *,
    target: dict[str, Any] | None = None,
    directive: str = "",
    constraint_kind: str = "",
) -> str:
    """Select a debate function with obligation-first overrides."""
    agent = agents_dict.get(speaker_id)
    aggressiveness = 3
    preference = ""
    if agent:
        constraints = agent.persona.get("speech_constraints", {})
        aggressiveness = constraints.get("aggressiveness") or agent.persona.get("debate_style", {}).get("aggressiveness", 3)
        preference = agent.persona.get("debate_function_preference", "")
    has_target = bool(target and target.get("content"))
    directive_type = _extract_directive_type(directive)

    if getattr(debate, "has_pending_definition_response", None) and debate.has_pending_definition_response(speaker_id):
        return "differentiate" if phase >= 2 or aggressiveness >= 4 else "define"

    if directive_type == "rebut_core_claim":
        return "attack" if phase >= 2 and has_target else "differentiate"
    if directive_type == "defend_self_consistency":
        return "differentiate" if has_target else "define"
    if directive_type == "deepen_axis":
        return "attack" if phase >= 2 and has_target else "differentiate"
    if directive_type == "echo_break":
        return "differentiate"
    if directive_type == "introduce_new_axis":
        return "differentiate" if phase >= 2 else "define"
    if directive_type == "use_weapon":
        if has_target and aggressiveness >= 4 and phase >= 2:
            return "attack"
        return "concretize"

    if constraint_kind == "tradeoff":
        return "concretize"
    if constraint_kind == "refocus":
        return "attack" if has_target and phase >= 2 else "differentiate"
    if not has_target and phase <= 2:
        return "define"

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

    if getattr(debate, "get_unresolved_terms", None):
        unresolved_terms = debate.get_unresolved_terms()
        if unresolved_terms:
            weights[0] += 4   # define
            weights[1] += 4   # differentiate
            weights[2] = max(0, weights[2] - 2)
    if getattr(debate, "has_open_attack_against", None) and debate.has_open_attack_against(speaker_id) and has_target:
        weights[2] += 3
        weights[3] += 1

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
