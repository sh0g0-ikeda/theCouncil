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
from engine.llm import LLMGenerationError, assign_debate_frame, compress_history, decompose_topic_axes
from engine.debate_state import DebateState
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
    meta_reply_pending = 0
    last_user_post_id: int | None = None
    meta_target_post_id: int | None = None
    meta_intervention_kind = ""
    try:
        saved_state = await db.load_debate_state(thread_id)
    except Exception as exc:
        if _is_missing_debate_state_error(exc):
            logger.warning("load_debate_state skipped because debate state storage is unavailable", exc_info=True)
            saved_state = None
        else:
            raise
    debate = DebateState.from_dict(saved_state) if saved_state else DebateState()
    last_speaker_id: str | None = None
    event_counter = 0
    roles_initialized = debate.roles_initialized() and bool(debate.get_debate_frame())
    moral_suction_active = 0  # countdown: resist moral framing for N more posts

    try:
        while True:
          try:
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
                    debate_frame, axes = await asyncio.gather(
                        assign_debate_frame(thread["topic"], agent_list),
                        decompose_topic_axes(thread["topic"]),
                    )
                    frame_payload = debate_frame.get("frame", {}) if isinstance(debate_frame, dict) else {}
                    assignments = debate_frame.get("assignments", {}) if isinstance(debate_frame, dict) else {}
                    debate.set_debate_frame(frame_payload, assignments)
                    debate.set_topic_axes(_sanitize_topic_axes(axes, thread["topic"], thread.get("topic_tags", [])))
                    roles_initialized = True
                    logger.info(
                        "frame=%s assignments=%s axes=%s thread=%s",
                        frame_payload,
                        {k: v.get('side') for k, v in assignments.items()},
                        axes,
                        thread_id,
                    )
                except Exception:
                    logger.warning("role/axis init failed", exc_info=True)
                    roles_initialized = True  # don't retry on error

            posts = await db.fetch_posts(thread_id)
            latest_post_id = max((int(post.get("id") or 0) for post in posts), default=0)
            debate.age_obligations(latest_post_id)
            if len(posts) != last_post_count:
                failed_agents.clear()
                last_post_count = len(posts)

            # ── Seed subquestions at thread start (once, no existing posts) ──
            ai_posts_count = sum(1 for p in posts if p.get("agent_id"))
            if not debate.thread_subquestions and ai_posts_count == 0:
                debate.thread_subquestions = seed_subquestions(thread["topic"])
            # ── Extract abstract terms for Phase 1 definitions ───────────────
            if not debate.abstract_terms and ai_posts_count == 0:
                debate.abstract_terms = _extract_abstract_nouns(thread["topic"], max_nouns=5)
                # Register abstract terms as definition obligations if not already present
                for term in debate.abstract_terms:
                    if term not in debate.definition_requests:
                        debate.definition_requests[term] = {
                            "status": "open",
                            "requested_post_id": 0,
                            "requested_by": "system",
                            "target_agent_id": None,
                            "created_post_id": 0,
                            "answered_post_id": None,
                            "answered_by": None,
                        }

            # Detect new user posts and queue 3 agent replies
            for p in posts:
                if (
                    p.get("agent_id") is None
                    and not p.get("is_facilitator")
                    and p.get("user_id") is not None
                    and (last_user_post_id is None or p["id"] > last_user_post_id)
                ):
                    last_user_post_id = p["id"]
                    meta_kind = _classify_user_intervention(p.get("content", ""))
                    if meta_kind:
                        meta_reply_pending = 1
                        meta_target_post_id = p["id"]
                        meta_intervention_kind = meta_kind
                        user_reply_pending = 0
                    else:
                        user_reply_pending = 3
                        meta_reply_pending = 0
                        meta_target_post_id = None
                        meta_intervention_kind = ""
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

            # ── Silent director (rule-based, event-driven, no visible post) ──
            if _needs_director(posts, debate):
                _run_director(thread, debate, agents, posts)

            if _should_facilitate(posts, debate):
                agent_display_names = {
                    aid: agents[aid].display_name
                    for aid in thread["agent_ids"] if aid in agents
                }
                facilitate = await make_facilitate(thread, posts, agent_display_names, debate)
                if facilitate and facilitate.get("content"):
                    # Store axis assignments from rerail into DebateState
                    ax_assignments = facilitate.get("axis_assignments", [])
                    if ax_assignments:
                        debate.push_axis_assignments(ax_assignments)
                    followup_assignments = facilitate.get("followup_assignments", [])
                    if followup_assignments:
                        debate.push_followup_assignments([dict(item) for item in followup_assignments if isinstance(item, dict)])
                    # Store facilitator constraint (next N posts must...)
                    constraint_text = str(facilitate.get("constraint", "")).strip()
                    if constraint_text:
                        debate.set_facilitator_constraint(
                            constraint_text,
                            int(facilitate.get("constraint_turns", 2)),
                            str(facilitate.get("constraint_kind", "")),
                            dict(facilitate.get("constraint_schema") or {}),
                        )
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
                    debate.alerts.discard("camp_reassert")
                    await push_fn(thread_id, post)
                    continue

            # ── Speaker selection ──────────────────────────────────────────
            # Priority: user-reply > score-based > normal
            newcomer_hint = False
            # Hard-exclude agents who spoke in the last 3 AI posts (prevents 2-bot loop)
            recent_ai_speakers = {p["agent_id"] for p in posts[-3:] if p.get("agent_id")}
            if meta_reply_pending > 0:
                try:
                    speaker_id = _select_meta_speaker(thread["agent_ids"], posts, agents, failed_agents)
                except ValueError:
                    failed_agents.clear()
                    await asyncio.sleep(0.5)
                    continue
            elif user_reply_pending > 0:
                try:
                    speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=debate)
                except ValueError:
                    failed_agents.clear()
                    await asyncio.sleep(0.5)
                    continue
            else:
                hard_excluded = failed_agents | recent_ai_speakers
                stagnating = _detect_stagnation(posts, debate)
                # Score-based priority: open attacks + agreement streak take precedence
                priority = _prioritize_speaker(
                    thread["agent_ids"], posts, debate, agents, hard_excluded
                )
                if priority:
                    speaker_id = priority
                elif stagnating:
                    silent = select_silent_agent(thread, agents, posts, excluded_agent_ids=hard_excluded)
                    speaker_id = silent if silent else _fallback_speaker(thread, agents, posts, hard_excluded)
                    newcomer_hint = True
                else:
                    try:
                        speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=hard_excluded, debate_state=debate)
                    except ValueError:
                        try:
                            speaker_id = select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=debate)
                        except ValueError:
                            failed_agents.clear()
                            await asyncio.sleep(0.5)
                            continue

            # ── Target selection ───────────────────────────────────────────
            if meta_reply_pending > 0:
                target = next((p for p in reversed(posts) if p["id"] == meta_target_post_id), None)
                if target is None:
                    meta_reply_pending = 0
                    meta_target_post_id = None
                    meta_intervention_kind = ""
                    target = select_target_post(posts, speaker_id, agents, debate_state=debate)
            elif user_reply_pending > 0:
                target = next((p for p in reversed(posts) if p["id"] == last_user_post_id), None)
                if target is None:
                    user_reply_pending = 0
                    target = select_target_post(posts, speaker_id, agents, debate_state=debate)
            else:
                target = select_target_post(posts, speaker_id, agents, debate_state=debate)
            target_id = target["agent_id"] if target and target.get("agent_id") else None
            axis = select_conflict_axis(speaker_id, target_id, agents) if target_id else "rationalism"

            # ── Debate function selection ───────────────────────────────────
            # Emotions (anger/contempt) affect prompt style only — not function selection
            stagnating = _detect_stagnation(posts, debate)
            next_directive = debate.peek_directive(speaker_id) or ""
            next_constraint_kind = debate.peek_constraint_kind()
            if meta_reply_pending > 0 and meta_intervention_kind:
                debate_fn = "synthesize"
            elif (
                stagnating
                and not debate.has_open_attack_against(speaker_id)
                and not debate.has_pending_definition_response(speaker_id)
                and not next_directive
            ):
                debate_fn = random.choice(["concretize", "differentiate", "attack"])
            else:
                debate_fn = _select_debate_function(
                    speaker_id,
                    phase,
                    agents,
                    debate,
                    target=target,
                    directive=next_directive,
                    constraint_kind=next_constraint_kind,
                )

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
            assigned_side = debate.get_agent_side(speaker_id)
            assigned_camp_function = debate.get_camp_function(speaker_id)
            debate_frame = debate.get_debate_frame()
            side_contract = debate.get_side_contract(speaker_id)
            forced_axis = debate.peek_forced_axis(speaker_id)
            private_directive = debate.peek_directive(speaker_id)
            active_constraint, active_constraint_kind = debate.peek_constraint()
            active_constraint_schema = debate.peek_constraint_schema()
            agent_recent_axes = debate.get_agent_recent_axes(speaker_id)
            uncovered_axes = debate.get_uncovered_axes()
            pending_definition_terms = debate.get_unresolved_terms()
            target_claim_units = debate.get_claim_units_for_post(target.get("id") if target else None)
            priority_subquestion = debate.get_priority_subquestion_for(speaker_id)
            position_anchor = debate.get_position_anchor(speaker_id)
            retrieval_mode = _determine_retrieval_mode(debate_fn, pending_definition_terms, active_constraint_kind)
            is_user_post_reply = ((user_reply_pending > 0 or meta_reply_pending > 0) and target is not None and target.get("user_id") is not None)
            target_is_moral = is_user_post_reply and _is_moral_suction(target.get("content", "") if target else "")
            required_local_stance = ""
            target_side = debate.get_agent_side(target_id) if target_id else ""
            if target_side and assigned_side in {"support", "oppose"} and target_side in {"support", "oppose"}:
                required_local_stance = "disagree" if target_side != assigned_side else ""
            camp_map_summary = " / ".join(
                f"{aid}:{debate.get_agent_side(aid)}:{debate.get_camp_function(aid)}"
                for aid in thread["agent_ids"]
                if aid in agents
            )
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
                "assigned_side": assigned_side,
                "assigned_side_label": debate_frame.get(f"{assigned_side}_label", "") if assigned_side else "",
                "opposing_side_label": debate_frame.get(f"{debate.get_opposing_side(speaker_id)}_label", ""),
                "side_contract": str(side_contract.get("thesis", "")),
                "assigned_camp_function": assigned_camp_function,
                "frame_proposition": debate_frame.get("proposition", ""),
                "support_label": debate_frame.get("support_label", ""),
                "oppose_label": debate_frame.get("oppose_label", ""),
                "conditional_label": debate_frame.get("conditional_label", ""),
                "support_thesis": debate_frame.get("support_thesis", ""),
                "oppose_thesis": debate_frame.get("oppose_thesis", ""),
                "forced_axis": forced_axis or "",
                "private_directive": private_directive or "",
                "active_constraint": active_constraint or "",
                "active_constraint_kind": active_constraint_kind or "",
                "active_constraint_schema": active_constraint_schema,
                "topic_axes": debate.topic_axes,
                "agent_recent_axes": agent_recent_axes,
                "uncovered_axes": uncovered_axes,
                "stance_drift_warning": stance_drift,
                "arsenal_novelty_push": arsenal_novelty,
                "is_first_post": is_first_post,
                "user_post_reply": is_user_post_reply,
                "moral_suction_warning": target_is_moral or moral_suction_active > 0,
                "target_claim_summary": summarize_target_claim(target or {}, axis),
                "target_claim_units": target_claim_units,
                "target_debate_role": debate.get_debate_role(target_id) if target_id else "",
                "target_side": target_side,
                "pending_definition_terms": pending_definition_terms,
                "recent_argument_fingerprints": debate.recent_argument_fingerprints[-6:],
                "forbidden_example_keys": debate.recent_example_keys[-4:],
                "required_response_kind": debate_fn,
                "required_proposition_stance": assigned_side if assigned_side in {"support", "oppose"} else "",
                "required_local_stance": required_local_stance,
                "required_subquestion_id": str(priority_subquestion.get("subquestion_id", "")) if priority_subquestion else "",
                "required_subquestion_text": str(priority_subquestion.get("text", "")) if priority_subquestion else "",
                "camp_map_summary": camp_map_summary,
                "retrieval_mode": retrieval_mode,
                "meta_intervention_kind": meta_intervention_kind if meta_reply_pending > 0 else "",
                "position_anchor_summary": str(position_anchor.get("summary", "")),
                "position_anchor_terms": list(position_anchor.get("terms", [])),
                "position_anchor_side": str(position_anchor.get("side", "")),
                "thread_subquestions": debate.thread_subquestions,
                "debate_post_count": len(posts),
                "abstract_terms": debate.abstract_terms,
                "resolved_abstract_terms": [
                    t for t, v in debate.definition_requests.items()
                    if v.get("status") == "answered"
                ],
                "recent_agent_conclusions": [
                    cs["structure"]["conclusion"]
                    for cs in debate.open_claim_structures[-10:]
                    if cs.get("agent_id") == speaker_id and cs.get("structure", {}).get("conclusion")
                ],
                "persona": agents[speaker_id].persona,
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

            semantic_payload = reply.get("_semantic_analysis") or {}
            semantic_analysis = SemanticPostAnalysis.from_dict(semantic_payload)
            focus_axis = semantic_analysis.effective_axis or reply.get("main_axis", axis)
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
                post_id=post["id"],
                analysis=semantic_analysis.as_dict(),
                content=reply["content"],
            )
            # Record proposition fingerprint for camp reassertion detection
            prop_fp = semantic_analysis.proposition_fingerprint
            if prop_fp:
                debate.record_proposition(speaker_id, prop_fp)
                if debate.check_camp_reassert(speaker_id, prop_fp):
                    debate.alerts.add("camp_reassert")
            # Track open claim structures for director
            claim_structure = semantic_analysis.claim_structure
            if claim_structure and claim_structure.get("conclusion"):
                debate.open_claim_structures.append({
                    "agent_id": speaker_id,
                    "post_id": post["id"],
                    "structure": claim_structure,
                })
                if len(debate.open_claim_structures) > 20:
                    debate.open_claim_structures.pop(0)
            if forced_axis:
                debate.pop_forced_axis(speaker_id)
            if private_directive:
                debate.pop_directive(speaker_id)
            if active_constraint:
                debate.consume_constraint()
            if meta_reply_pending > 0:
                meta_reply_pending -= 1
                if meta_reply_pending <= 0:
                    meta_target_post_id = None
                    meta_intervention_kind = ""
            elif user_reply_pending > 0:
                user_reply_pending -= 1
            if moral_suction_active > 0:
                moral_suction_active -= 1
            await push_fn(thread_id, post)
            if event_counter % 5 == 0:
                try:
                    await db.save_debate_state(thread_id, debate.to_dict())
                except Exception:
                    logger.warning("save_debate_state failed (table may not exist yet)", exc_info=True)
          except asyncio.CancelledError:
              raise
          except Exception:
              logger.exception("debate loop iteration failed for thread=%s, retrying in 5s", thread_id)
              await asyncio.sleep(5)
    finally:
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
