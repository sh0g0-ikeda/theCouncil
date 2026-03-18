from __future__ import annotations

import random
from typing import Any

ALPHA = 0.35   # opposition (ideological distance)
BETA  = 0.25   # silence bonus (equity)
GAMMA = 0.15   # topic match  ← 0.25から下げる：特定2人への偏りを防ぐ
DELTA = 0.25   # diversity    ← 0.15から上げる：直近発言者を強く排除

AXES = [
    "state_control",
    "tech_optimism",
    "rationalism",
    "power_realism",
    "individualism",
    "moral_universalism",
    "future_orientation",
]


def _eligible_participants(participant_ids: list[str], excluded_agent_ids: set[str]) -> list[str]:
    return [agent_id for agent_id in participant_ids if agent_id not in excluded_agent_ids]


def participation_floor_penalty(
    agent_id: str,
    recent_ai_posts: list[dict],
    window: int = 8,
    max_share: float = 0.4,
) -> float:
    """Return score adjustment based on recent participation share.

    - If agent has > max_share of the last window AI posts: -3.0
    - If agent has zero appearances in the last window posts: +2.0 (floor boost)
    - Otherwise: 0.0
    """
    if not recent_ai_posts:
        return 0.0
    window_posts = recent_ai_posts[-window:]
    total = len(window_posts)
    if total == 0:
        return 0.0
    count = sum(1 for p in window_posts if p.get("agent_id") == agent_id)
    share = count / total
    if share > max_share:
        return -3.0
    if count == 0:
        return 2.0
    return 0.0


def select_silent_agent(
    thread: dict[str, Any],
    agents: dict[str, Any],
    posts: list[dict[str, Any]],
    excluded_agent_ids: set[str] | None = None,
) -> str | None:
    """Return the participant who has spoken least (for newcomer events)."""
    participant_ids: list[str] = thread["agent_ids"]
    excluded = (excluded_agent_ids or set()) | {
        p["agent_id"] for p in posts[-2:] if p.get("agent_id")
    }
    post_counts = {a: sum(1 for p in posts if p.get("agent_id") == a) for a in participant_ids}
    candidates = [(a, post_counts.get(a, 0)) for a in participant_ids if a not in excluded and a in agents]
    if not candidates:
        return None
    return min(candidates, key=lambda x: x[1])[0]


def select_next_agent(
    thread: dict[str, Any],
    agents: dict[str, Any],
    posts: list[dict[str, Any]],
    excluded_agent_ids: set[str] | None = None,
    debate_state: Any = None,
) -> str:
    participant_ids: list[str] = thread["agent_ids"]
    excluded_agent_ids = excluded_agent_ids or set()

    if not posts:
        candidates = _eligible_participants(participant_ids, excluded_agent_ids)
        if not candidates:
            raise ValueError("No eligible agents available")
        return random.choice(candidates)

    last_agent_id = next((post["agent_id"] for post in reversed(posts) if post.get("agent_id")), None)
    if not last_agent_id:
        candidates = _eligible_participants(participant_ids, excluded_agent_ids)
        if not candidates:
            raise ValueError("No eligible agents available")
        return random.choice(candidates)

    post_counts = {
        agent_id: sum(1 for post in posts if post.get("agent_id") == agent_id)
        for agent_id in participant_ids
    }
    avg_count = sum(post_counts.values()) / len(participant_ids)
    # Expand window to 6 to better detect loops between 2 agents
    recent_agents = {post["agent_id"] for post in posts[-6:] if post.get("agent_id")}
    current_tags = thread.get("topic_tags", [])
    last_vector = agents[last_agent_id].vector if last_agent_id in agents else None
    last_side = debate_state.get_agent_side(last_agent_id) if debate_state is not None else ""
    last_camp_function = debate_state.get_camp_function(last_agent_id) if debate_state is not None else ""

    # Participation floor: recent AI posts for floor/ceiling calculations
    recent_ai_posts = [p for p in posts if p.get("agent_id")][-8:]
    # Hard guard: agents in last 5 AI posts >= 2 times are skipped if others have 0
    last5_ai = [p for p in posts if p.get("agent_id")][-5:]
    agents_zero_in_last5 = {
        aid for aid in participant_ids
        if aid not in excluded_agent_ids
        and aid != last_agent_id
        and sum(1 for p in last5_ai if p.get("agent_id") == aid) == 0
        and aid in agents
    }

    scores: dict[str, float] = {}
    for agent_id in participant_ids:
        if agent_id == last_agent_id or agent_id in excluded_agent_ids:
            continue
        if agent_id not in agents:
            continue
        agent = agents[agent_id]

        # Hard guard: if this agent appeared >= 2 of last 5 AI posts and others have 0, skip
        agent_last5_count = sum(1 for p in last5_ai if p.get("agent_id") == agent_id)
        if agent_last5_count >= 2 and agents_zero_in_last5:
            scores[agent_id] = -99.0
            continue

        opposition = (agent.vector.manhattan_distance(last_vector) / 70.0) if last_vector else 0.5
        silence_bonus = max(0.0, (avg_count - post_counts[agent_id]) / avg_count) if avg_count > 0 else 0.0
        persona_text = " ".join(
            agent.persona.get("worldview", [])
            + agent.persona.get("combat_doctrine", [])
        )
        topic_match = sum(1 for tag in current_tags if tag in persona_text) / max(len(current_tags), 1)
        # Diversity: 0 if spoke in last 6, 0.5 if spoke in last 3, 1 if not recent
        if agent_id in {p["agent_id"] for p in posts[-3:] if p.get("agent_id")}:
            diversity = 0.0
        elif agent_id in recent_agents:
            diversity = 0.5
        else:
            diversity = 1.0
        # Arsenal novelty boost: agents with unused unique arguments get +0.15
        arsenal_boost = 0.15 if (
            debate_state is not None
            and debate_state.has_unused_arsenal(agent_id, agent.persona)
        ) else 0.0
        side_diversity = 0.12 if (
            debate_state is not None
            and last_side
            and debate_state.get_agent_side(agent_id)
            and debate_state.get_agent_side(agent_id) != last_side
        ) else 0.0
        camp_function_penalty = 0.0
        if (
            debate_state is not None
            and last_side
            and last_camp_function
            and debate_state.get_agent_side(agent_id) == last_side
            and debate_state.get_camp_function(agent_id) == last_camp_function
        ):
            camp_function_penalty = 0.18
        # Participation floor penalty/boost
        floor_adj = participation_floor_penalty(agent_id, recent_ai_posts)
        score = (
            ALPHA * opposition
            + BETA * silence_bonus
            + GAMMA * topic_match
            + DELTA * diversity
            + arsenal_boost
            + side_diversity
            - camp_function_penalty
            + floor_adj
        )
        # Floor weight: everyone gets at least 0.15 to prevent complete lock-out
        # (but not if hard-guarded with -99)
        scores[agent_id] = max(score, 0.15)

    if not scores:
        raise ValueError("No eligible agents available")

    # Weighted random sampling: preserves signal but prevents deterministic lock-in
    # Filter out hard-guarded agents (score == -99)
    eligible = [(a, s) for a, s in scores.items() if s > -50.0]
    if not eligible:
        eligible = list(scores.items())  # fallback: use all
    candidates = [a for a, _ in eligible]
    weights = [s for _, s in eligible]
    return random.choices(candidates, weights=weights)[0]


def select_target_post(
    posts: list[dict[str, Any]],
    speaker_id: str,
    agents: dict[str, Any],
    debate_state: Any = None,
) -> dict[str, Any] | None:
    """Weighted-random target selection: ideological distance as weight.

    Uses recency-deduplication so the same post is not targeted by consecutive
    speakers, and adds a recency bonus so recent posts are more likely targets.
    """
    speaker_vector = agents[speaker_id].vector if speaker_id in agents else None

    if debate_state is not None:
        priority_subquestion_post_id = getattr(debate_state, "get_priority_subquestion_post_id_for", lambda _aid: None)(speaker_id)
        if priority_subquestion_post_id is not None:
            target = next((post for post in reversed(posts) if post.get("id") == priority_subquestion_post_id), None)
            if target is not None:
                return target
        priority_post_id = debate_state.get_priority_post_id_for(speaker_id)
        if priority_post_id is not None:
            target = next((post for post in reversed(posts) if post.get("id") == priority_post_id), None)
            if target is not None:
                return target

    # Find the post that was just targeted by the previous AI speaker (to avoid pile-on)
    last_target_id: int | None = None
    for p in reversed(posts[-3:]):
        if p.get("agent_id") and p["agent_id"] != speaker_id and p.get("reply_to"):
            last_target_id = p["reply_to"]
            break

    candidates: list[dict[str, Any]] = []
    weights: list[float] = []
    preferred_side = ""
    if debate_state is not None:
        speaker_side = debate_state.get_agent_side(speaker_id)
        if speaker_side in {"support", "oppose"}:
            preferred_side = debate_state.get_opposing_side(speaker_id)

    seen_agents: set[str] = set()
    for i, post in enumerate(reversed(posts[-20:])):
        agent_id = post.get("agent_id")
        if not agent_id or agent_id == speaker_id or agent_id not in agents:
            continue
        # One candidate per agent (most recent post wins — reversed order)
        if agent_id in seen_agents:
            continue
        seen_agents.add(agent_id)

        distance = agents[agent_id].vector.manhattan_distance(speaker_vector) if speaker_vector else 0.5
        # Recency bonus: first 5 in reversed order get +10
        recency = max(0.0, (5 - i) * 2.0)
        weight = max(distance + recency, 1.0)
        # Halve weight if this post was just targeted by the previous speaker
        if post.get("id") == last_target_id:
            weight *= 0.3
        if preferred_side:
            target_side = debate_state.get_agent_side(agent_id)
            if target_side == preferred_side:
                weight *= 1.35
            elif target_side and target_side == debate_state.get_agent_side(speaker_id):
                weight *= 0.7
        candidates.append(post)
        weights.append(weight)

    if not candidates:
        return None
    if preferred_side:
        preferred_pairs = [
            (post, weight)
            for post, weight in zip(candidates, weights)
            if debate_state.get_agent_side(post.get("agent_id")) == preferred_side
        ]
        if preferred_pairs:
            candidates = [post for post, _ in preferred_pairs]
            weights = [weight for _, weight in preferred_pairs]
    return random.choices(candidates, weights=weights)[0]


def select_conflict_axis(speaker_id: str, target_id: str, agents: dict[str, Any]) -> str:
    if speaker_id not in agents or target_id not in agents:
        return "rationalism"
    speaker_vector = agents[speaker_id].vector.as_list()
    target_vector = agents[target_id].vector.as_list()
    diffs = [abs(s - t) for s, t in zip(speaker_vector, target_vector)]
    return AXES[diffs.index(max(diffs))]
