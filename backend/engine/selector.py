from __future__ import annotations

import random
from typing import Any

ALPHA = 0.4
BETA = 0.2
GAMMA = 0.25
DELTA = 0.15

AXES = [
    "tech_optimism",
    "state_intervention",
    "market_trust",
    "order_preference",
    "individualism",
    "rationalism",
    "power_affirmation",
    "moral_universalism",
    "strategic_aggression",
    "future_orientation",
]


def _eligible_participants(participant_ids: list[str], excluded_agent_ids: set[str]) -> list[str]:
    return [agent_id for agent_id in participant_ids if agent_id not in excluded_agent_ids]


def select_next_agent(
    thread: dict[str, Any],
    agents: dict[str, Any],
    posts: list[dict[str, Any]],
    excluded_agent_ids: set[str] | None = None,
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
    recent_agents = [post["agent_id"] for post in posts[-3:] if post.get("agent_id")]
    current_tags = thread.get("topic_tags", [])
    last_vector = agents[last_agent_id].vector if last_agent_id in agents else None

    scores: dict[str, float] = {}
    for agent_id in participant_ids:
        if agent_id == last_agent_id or agent_id in excluded_agent_ids:
            continue
        agent = agents[agent_id]
        opposition = (agent.vector.manhattan_distance(last_vector) / 50.0) if last_vector else 0.5
        silence_bonus = max(0.0, (avg_count - post_counts[agent_id]) / avg_count) if avg_count > 0 else 0.0
        persona_text = " ".join(agent.persona.get("core_beliefs", []) + agent.persona.get("values", []))
        topic_match = sum(1 for tag in current_tags if tag in persona_text) / max(len(current_tags), 1)
        diversity = 0.0 if agent_id in recent_agents else 1.0
        scores[agent_id] = (
            ALPHA * opposition
            + BETA * silence_bonus
            + GAMMA * topic_match
            + DELTA * diversity
        )

    if not scores:
        raise ValueError("No eligible agents available")
    return max(scores, key=scores.__getitem__)


def select_target_post(posts: list[dict[str, Any]], speaker_id: str, agents: dict[str, Any]) -> dict[str, Any] | None:
    speaker_vector = agents[speaker_id].vector
    best_post: dict[str, Any] | None = None
    best_distance = -1
    for post in reversed(posts[-20:]):
        agent_id = post.get("agent_id")
        if not agent_id or agent_id == speaker_id or agent_id not in agents:
            continue
        distance = agents[agent_id].vector.manhattan_distance(speaker_vector)
        if distance > best_distance:
            best_distance = distance
            best_post = post
    return best_post


def select_conflict_axis(speaker_id: str, target_id: str, agents: dict[str, Any]) -> str:
    speaker_vector = agents[speaker_id].vector.as_list()
    target_vector = agents[target_id].vector.as_list()
    diffs = [abs(s - t) for s, t in zip(speaker_vector, target_vector)]
    return AXES[diffs.index(max(diffs))]
