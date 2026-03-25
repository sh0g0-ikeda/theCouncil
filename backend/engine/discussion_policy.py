from __future__ import annotations

import random
import re
from collections import Counter
from typing import Any

from engine.debate_state import DebateState
from engine.selector import select_next_agent
from models.agent import Agent

_TOKEN_PATTERN = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)
_JP_PARTICLES = {
    "は", "が", "に", "で", "と", "の", "へ", "を", "な", "だ",
    "て", "である", "する", "した", "その", "これ", "ため", "よう",
}
_META_SUMMARY_PATTERNS = (
    re.compile(r"(?:結局|要するに).*(?:論点|争点)"),
    re.compile(r"(?:まとめ|整理).*(?:して|くれ|してくれ)"),
    re.compile(r"(?:何が争点|論点は何)"),
    re.compile(r"(?:要約して|要点だけ)"),
)
_MORAL_KEYWORDS = {
    "倫理",
    "道徳",
    "善悪",
    "正義",
    "人権",
    "べき",
    "絶対",
    "許されない",
    "悪",
}
_DEBATE_FUNCTIONS = ["define", "differentiate", "attack", "steelman", "concretize", "synthesize"]


def _extract_abstract_nouns(topic: str, max_nouns: int = 5) -> list[str]:
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
    nouns = _extract_abstract_nouns(topic, max_nouns=2)
    subquestions: list[str] = []
    for noun in nouns:
        subquestions.append(f"「{noun}」とは何か、どのように定義されるか")
        subquestions.append(f"「{noun}」がどのような条件で実現するか、その条件は妥当か")
        subquestions.append(f"「{noun}」が失敗するとしたら何が原因か")
        subquestions.append(f"現実から「{noun}」へ至る移行のメカニズムは何か")
    return subquestions[:8]


def _is_moral_suction(content: str) -> bool:
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


def _run_director(
    thread: dict[str, Any],
    debate: DebateState,
    agents_dict: dict[str, Any],
    posts: list[dict[str, Any]] | None = None,
) -> None:
    participant_ids: list[str] = thread.get("agent_ids", [])
    recent_posts: list[dict[str, Any]] = posts or []
    uncovered_axes = debate.get_uncovered_axes()

    for agent_id in participant_ids:
        if agent_id not in agents_dict or debate.has_directive(agent_id):
            continue

        agent = agents_dict[agent_id]
        persona = agent.persona
        non_neg = persona.get("speech_constraints", {}).get("non_negotiable", "")

        open_attack = debate.get_strongest_open_attack(agent_id)
        if open_attack:
            attacker_id, snippet = open_attack
            attacker_name = agents_dict[attacker_id].display_name if attacker_id in agents_dict else attacker_id
            conclusion_hint = ""
            for claim_entry in reversed(getattr(debate, "open_claim_structures", [])[-10:]):
                if claim_entry.get("agent_id") == attacker_id:
                    conclusion = claim_entry.get("structure", {}).get("conclusion", "")
                    if conclusion:
                        conclusion_hint = f" Conclusion={conclusion[:40]}"
                    break
            debate.push_directive(
                agent_id,
                (
                    f"MISSION:rebut_core_claim Opponent={attacker_name} Snippet={snippet[:50]}."
                    f"{conclusion_hint} Rebut the core claim directly."
                ),
            )
            continue

        streak = debate.agreement_streak.get(agent_id, 0)
        if streak >= 2 and non_neg:
            debate.push_directive(
                agent_id,
                (
                    f"MISSION:defend_self_consistency Streak={streak}. "
                    f"Re-anchor to non_negotiable={non_neg[:55]}. Use disagreement or shift only with explicit reason."
                ),
            )
            continue

        if debate.is_echo_chamber():
            agent_recent = set(debate.get_agent_recent_axes(agent_id))
            candidates = [axis for axis in uncovered_axes if axis not in agent_recent]
            if candidates:
                debate.push_directive(
                    agent_id,
                    f"MISSION:echo_break Use axis={candidates[0]}. Break the current repetition.",
                )
                continue

        shallow = debate.get_shallow_axes()
        if shallow:
            axis_to_contest = shallow[0]
            introducer = next(
                (aid for aid, axes in debate.agent_axis_usage.items() if axis_to_contest in axes),
                None,
            )
            if agent_id != introducer:
                claim_post = next(
                    (
                        post for post in reversed(recent_posts[-20:])
                        if post.get("focus_axis") == axis_to_contest
                        and post.get("agent_id")
                        and post.get("agent_id") != agent_id
                    ),
                    None,
                )
                claim_hint = ""
                if claim_post:
                    speaker = claim_post.get("display_name") or claim_post.get("agent_id") or "opponent"
                    claim_hint = f" Target={speaker}:{claim_post['content'][:45]}."
                debate.push_directive(
                    agent_id,
                    f"MISSION:deepen_axis Axis={axis_to_contest}.{claim_hint} Contest the weak point on that axis.",
                )
                continue

        if not shallow and uncovered_axes:
            agent_recent = set(debate.get_agent_recent_axes(agent_id))
            candidates = [axis for axis in uncovered_axes if axis not in agent_recent]
            if candidates:
                debate.push_directive(
                    agent_id,
                    f"MISSION:introduce_new_axis Axis={candidates[0]}. Introduce it explicitly.",
                )
                continue

        if debate.has_unused_arsenal(agent_id, persona):
            available = debate.get_available_arsenal(agent_id, persona)
            used = debate.used_arsenal_ids.get(agent_id, set())
            unused = [item for item in available if item["id"] not in used]
            if unused:
                debate.push_directive(
                    agent_id,
                    f"MISSION:use_weapon Arsenal={unused[0]['desc'][:45]}. Use this move explicitly.",
                )


def _needs_director(posts: list[dict[str, Any]], debate: DebateState) -> bool:
    ai_posts = [post for post in posts if post.get("agent_id")]
    if len(ai_posts) < 3:
        return False
    if debate.has_any_open_attacks():
        return True
    if any(value >= 2 for value in debate.agreement_streak.values()):
        return True
    if debate.is_echo_chamber():
        return True
    recent_axes = [post.get("focus_axis") for post in ai_posts[-2:] if post.get("focus_axis")]
    if len(recent_axes) == 2 and recent_axes[0] == recent_axes[1]:
        return True
    n = len(ai_posts)
    if n >= 4 and n % 4 == 0 and debate.get_uncovered_axes():
        return True
    return False


def _should_facilitate(posts: list[dict[str, Any]], debate: DebateState | None = None) -> bool:
    if not posts or posts[-1].get("is_facilitator", False):
        return False
    if debate is not None and "camp_reassert" in getattr(debate, "alerts", set()):
        return True
    structural_posts = [post for post in posts if post.get("agent_id") or post.get("is_facilitator")]
    for post in structural_posts[-5:]:
        if post.get("is_facilitator"):
            return False
    ai_posts = [post for post in posts if post.get("agent_id")]
    n_ai = len(ai_posts)
    if len(posts) == 3:
        return True
    if n_ai < 4:
        return False
    recent_axes = [post.get("focus_axis") for post in ai_posts[-3:] if post.get("focus_axis")]
    if len(recent_axes) == 3 and len(set(recent_axes)) == 1:
        return True
    recent_stances = [post.get("stance") for post in ai_posts[-5:] if post.get("stance") and post["stance"] != "facilitate"]
    if len(recent_stances) >= 4 and sum(1 for stance in recent_stances if stance in {"agree", "supplement"}) >= 4:
        return True
    if n_ai >= 5:
        no_replies = sum(1 for post in ai_posts[-5:] if not post.get("reply_to"))
        if no_replies >= 4:
            return True
    return False


def _prioritize_speaker(
    participant_ids: list[str],
    posts: list[dict[str, Any]],
    debate: DebateState,
    agents_dict: dict[str, Any],
    excluded: set[str],
) -> str | None:
    last_2 = {post["agent_id"] for post in posts[-2:] if post.get("agent_id")}
    last_ai_speaker = next((post.get("agent_id") for post in reversed(posts) if post.get("agent_id")), None)
    last_side = debate.get_agent_side(last_ai_speaker) if last_ai_speaker else ""
    post_counts = {
        agent_id: sum(1 for post in posts if post.get("agent_id") == agent_id)
        for agent_id in participant_ids
    }
    ranked: list[tuple[tuple[int, int, int, int, int, int, str], str]] = []

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
        repeated_axis_penalty = 1 if recent_axis_window and Counter(recent_axis_window).most_common(1)[0][1] >= 2 else 0
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
    try:
        return select_next_agent(thread, agents, posts, excluded_agent_ids=failed_agents, debate_state=None)
    except ValueError:
        participant_ids: list[str] = thread["agent_ids"]
        candidates = [agent_id for agent_id in participant_ids if agent_id in agents]
        if not candidates:
            raise
        return random.choice(candidates)


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
    agent = agents_dict.get(speaker_id)
    aggressiveness = 3
    preference = ""
    if agent:
        constraints = agent.persona.get("speech_constraints", {})
        aggressiveness = constraints.get("aggressiveness") or agent.persona.get("debate_style", {}).get("aggressiveness", 3)
        preference = agent.persona.get("debate_function_preference", "")

    has_target = bool(target and target.get("content"))
    directive_type = _extract_directive_type(directive)

    if debate.has_pending_definition_response(speaker_id):
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

    if phase <= 1:
        weights = [8, 4, 0, 0, 0, 0]
    elif phase == 2:
        weights = [1, 2, 4, 1, 4, 1]
    elif phase == 3:
        weights = [0, 1, 5, 3, 3, 1]
    elif phase == 4:
        weights = [1, 1, 2, 2, 3, 5]
    else:
        weights = [0, 0, 3, 1, 2, 4]

    if aggressiveness >= 4:
        weights[2] += 2
        weights[3] += 1
    elif aggressiveness <= 2:
        weights[0] += 1
        weights[4] += 2

    if preference in _DEBATE_FUNCTIONS:
        weights[_DEBATE_FUNCTIONS.index(preference)] += 3

    unresolved_terms = debate.get_unresolved_terms()
    if unresolved_terms:
        weights[0] += 4
        weights[1] += 4
        weights[2] = max(0, weights[2] - 2)
    if debate.has_open_attack_against(speaker_id) and has_target:
        weights[2] += 3
        weights[3] += 1

    for index, fn in enumerate(_DEBATE_FUNCTIONS):
        if debate.is_function_overused(fn):
            weights[index] = max(0, weights[index] - 2)

    return random.choices(_DEBATE_FUNCTIONS, weights=weights)[0]


def _detect_stagnation(posts: list[dict[str, Any]], debate: DebateState | None = None) -> bool:
    ai_posts = [post for post in posts[-6:] if post.get("agent_id")]
    if len(ai_posts) < 4:
        return False
    if len({post["agent_id"] for post in ai_posts}) <= 2:
        return True
    axes = [post.get("focus_axis") for post in ai_posts[-5:] if post.get("focus_axis")]
    if len(axes) >= 4 and len(set(axes)) == 1:
        return True
    if debate and debate.is_function_stagnating():
        return True
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
        return f"圧縮要約: {compressed_summary} / 直近: {recent_summary}"
    return compressed_summary or recent_summary
