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

    scores: dict[str, float] = {}
    for agent_id in participant_ids:
        if agent_id == last_agent_id or agent_id in excluded_agent_ids:
            continue
        agent = agents[agent_id]
        opposition = (agent.vector.manhattan_distance(last_vector) / 70.0) if last_vector else 0.5
        silence_bonus = max(0.0, (avg_count - post_counts[agent_id]) / avg_count) if avg_count > 0 else 0.0
        persona_text = " ".join(
            agent.persona.get("worldview", agent.persona.get("core_beliefs", []))
            + agent.persona.get("combat_doctrine", agent.persona.get("values", []))
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
        score = (
            ALPHA * opposition
            + BETA * silence_bonus
            + GAMMA * topic_match
            + DELTA * diversity
            + arsenal_boost
        )
        # Floor weight: everyone gets at least 0.15 to prevent complete lock-out
        scores[agent_id] = max(score, 0.15)

    if not scores:
        raise ValueError("No eligible agents available")

    # Weighted random sampling: preserves signal but prevents deterministic lock-in
    candidates = list(scores.keys())
    weights = [scores[a] for a in candidates]
    return random.choices(candidates, weights=weights)[0]


def select_target_post(posts: list[dict[str, Any]], speaker_id: str, agents: dict[str, Any]) -> dict[str, Any] | None:
    """Weighted-random target selection: ideological distance as weight.

    Uses recency-deduplication so the same post is not targeted by consecutive
    speakers, and adds a recency bonus so recent posts are more likely targets.
    """
    speaker_vector = agents[speaker_id].vector

    # Find the post that was just targeted by the previous AI speaker (to avoid pile-on)
    last_target_id: int | None = None
    for p in reversed(posts[-3:]):
        if p.get("agent_id") and p["agent_id"] != speaker_id and p.get("reply_to"):
            last_target_id = p["reply_to"]
            break

    candidates: list[dict[str, Any]] = []
    weights: list[float] = []

    seen_agents: set[str] = set()
    for i, post in enumerate(reversed(posts[-20:])):
        agent_id = post.get("agent_id")
        if not agent_id or agent_id == speaker_id or agent_id not in agents:
            continue
        # One candidate per agent (most recent post wins — reversed order)
        if agent_id in seen_agents:
            continue
        seen_agents.add(agent_id)

        distance = agents[agent_id].vector.manhattan_distance(speaker_vector)
        # Recency bonus: first 5 in reversed order get +10
        recency = max(0.0, (5 - i) * 2.0)
        weight = max(distance + recency, 1.0)
        # Halve weight if this post was just targeted by the previous speaker
        if post.get("id") == last_target_id:
            weight *= 0.3
        candidates.append(post)
        weights.append(weight)

    if not candidates:
        return None
    return random.choices(candidates, weights=weights)[0]


def select_conflict_axis(speaker_id: str, target_id: str, agents: dict[str, Any]) -> str:
    speaker_vector = agents[speaker_id].vector.as_list()
    target_vector = agents[target_id].vector.as_list()
    diffs = [abs(s - t) for s, t in zip(speaker_vector, target_vector)]
    return AXES[diffs.index(max(diffs))]
