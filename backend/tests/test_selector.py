from __future__ import annotations

import random

from engine.selector import select_conflict_axis, select_next_agent, select_target_post
from models.agent import Agent, IdeologyVector


def make_agent(agent_id: str, values: list[int], worldview: list[str] | None = None) -> Agent:
    vector = IdeologyVector(*values)
    persona = {
        "worldview": worldview or [],
        "combat_doctrine": worldview or [],
    }
    return Agent(id=agent_id, display_name=agent_id, label=agent_id, persona=persona, vector=vector)


def test_select_next_agent_prefers_opposition_and_diversity() -> None:
    agents = {
        "a": make_agent("a", [5, 1, 1, 1, 1, 1, 1], ["security"]),
        "b": make_agent("b", [-5, -1, -1, -5, -1, -1, -1], ["security"]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0], ["economy"]),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": ["security"]}
    posts = [
        {"id": 1, "agent_id": "a", "content": "..."},
        {"id": 2, "agent_id": "c", "content": "..."},
        {"id": 3, "agent_id": "a", "content": "..."},
    ]

    original_choices = random.choices
    random.choices = lambda candidates, weights: [candidates[weights.index(max(weights))]]
    try:
        assert select_next_agent(thread, agents, posts) == "b"
    finally:
        random.choices = original_choices


def test_select_target_post_uses_priority_post_when_present() -> None:
    agents = {
        "a": make_agent("a", [5, 5, 5, 5, 5, 5, 5]),
        "b": make_agent("b", [-5, -5, -5, -5, -5, -5, -5]),
    }
    posts = [
        {"id": 1, "agent_id": "b", "content": "..."},
        {"id": 2, "agent_id": "b", "content": "..."},
    ]

    class DebateStub:
        @staticmethod
        def get_priority_post_id_for(_agent_id: str) -> int | None:
            return 1

    assert select_target_post(posts, "a", agents, debate_state=DebateStub())["id"] == 1


def test_select_target_post_uses_priority_subquestion_post_when_present() -> None:
    agents = {
        "a": make_agent("a", [5, 5, 5, 5, 5, 5, 5]),
        "b": make_agent("b", [-5, -5, -5, -5, -5, -5, -5]),
    }
    posts = [
        {"id": 1, "agent_id": "b", "content": "..."},
        {"id": 2, "agent_id": "b", "content": "..."},
    ]

    class DebateStub:
        @staticmethod
        def get_priority_subquestion_post_id_for(_agent_id: str) -> int | None:
            return 2

        @staticmethod
        def get_priority_post_id_for(_agent_id: str) -> int | None:
            return 1

    assert select_target_post(posts, "a", agents, debate_state=DebateStub())["id"] == 2


def test_select_target_post_prefers_opposing_side_when_available() -> None:
    agents = {
        "a": make_agent("a", [5, 5, 5, 5, 5, 5, 5]),
        "b": make_agent("b", [-5, -5, -5, -5, -5, -5, -5]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0]),
    }
    posts = [
        {"id": 1, "agent_id": "c", "content": "..."},
        {"id": 2, "agent_id": "b", "content": "..."},
    ]

    class DebateStub:
        @staticmethod
        def get_priority_post_id_for(_agent_id: str) -> int | None:
            return None

        @staticmethod
        def get_agent_side(agent_id: str) -> str:
            return {"a": "support", "b": "oppose", "c": "support"}.get(agent_id, "")

        @staticmethod
        def get_opposing_side(_agent_id: str) -> str:
            return "oppose"

    original_choices = random.choices
    random.choices = lambda candidates, weights: [candidates[weights.index(max(weights))]]
    try:
        assert select_target_post(posts, "a", agents, debate_state=DebateStub())["id"] == 2
    finally:
        random.choices = original_choices


def test_select_conflict_axis_returns_max_difference_axis() -> None:
    agents = {
        "a": make_agent("a", [0, 0, 0, 0, 0, 0, 0]),
        "b": make_agent("b", [0, 4, 0, 0, 0, 0, 0]),
    }

    assert select_conflict_axis("a", "b", agents) == "tech_optimism"


def test_select_next_agent_skips_temporarily_failed_agents() -> None:
    agents = {
        "a": make_agent("a", [5, 1, 1, 1, 1, 1, 1], ["security"]),
        "b": make_agent("b", [-5, -1, -1, -5, -1, -1, -1], ["security"]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0], ["security"]),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": ["security"]}
    posts = [
        {"id": 1, "agent_id": "a", "content": "..."},
        {"id": 2, "agent_id": "c", "content": "..."},
        {"id": 3, "agent_id": "a", "content": "..."},
    ]

    original_choices = random.choices
    random.choices = lambda candidates, weights: [candidates[weights.index(max(weights))]]
    try:
        assert select_next_agent(thread, agents, posts, excluded_agent_ids={"b"}) == "c"
    finally:
        random.choices = original_choices


def test_select_next_agent_penalizes_same_side_same_camp_function() -> None:
    agents = {
        "a": make_agent("a", [5, 1, 1, 1, 1, 1, 1], ["innovation"]),
        "b": make_agent("b", [4, 1, 1, 1, 1, 1, 1], ["innovation"]),
        "c": make_agent("c", [4, 1, 1, 1, 1, 1, 1], ["consumer"]),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": ["innovation"]}
    posts = [
        {"id": 1, "agent_id": "a", "content": "..."},
        {"id": 2, "agent_id": "a", "content": "..."},
    ]

    class DebateStub:
        @staticmethod
        def has_unused_arsenal(_agent_id: str, _persona: dict[str, object]) -> bool:
            return False

        @staticmethod
        def get_agent_side(agent_id: str) -> str:
            return {"a": "support", "b": "support", "c": "support"}.get(agent_id, "")

        @staticmethod
        def get_camp_function(agent_id: str) -> str:
            return {"a": "innovation", "b": "innovation", "c": "consumer_welfare"}.get(agent_id, "")

    original_choices = random.choices
    random.choices = lambda candidates, weights: [candidates[weights.index(max(weights))]]
    try:
        assert select_next_agent(thread, agents, posts, debate_state=DebateStub()) == "c"
    finally:
        random.choices = original_choices
