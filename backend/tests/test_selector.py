from backend.engine.selector import select_conflict_axis, select_next_agent, select_target_post
from backend.models.agent import Agent, IdeologyVector


def make_agent(agent_id: str, values: list[int], beliefs: list[str] | None = None) -> Agent:
    vector = IdeologyVector(*values)
    persona = {
        "core_beliefs": beliefs or [],
        "values": beliefs or [],
    }
    return Agent(id=agent_id, display_name=agent_id, label=agent_id, persona=persona, vector=vector)


def test_select_next_agent_prefers_opposition_and_diversity() -> None:
    agents = {
        "a": make_agent("a", [5, 1, 1, 1, 1, 5, 1, 0, 2, 5], ["制度設計"]),
        "b": make_agent("b", [-5, -1, -1, -1, -1, -5, -1, 0, -2, -5], ["制度設計"]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], ["価値観"]),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": ["制度設計"]}
    posts = [
        {"id": 1, "agent_id": "a", "content": "..."},
        {"id": 2, "agent_id": "c", "content": "..."},
        {"id": 3, "agent_id": "a", "content": "..."},
    ]

    assert select_next_agent(thread, agents, posts) == "b"


def test_select_target_post_picks_most_distant_recent_agent() -> None:
    agents = {
        "a": make_agent("a", [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]),
        "b": make_agent("b", [-5, -5, -5, -5, -5, -5, -5, -5, -5, -5]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    }
    posts = [
        {"id": 1, "agent_id": "c", "content": "..."},
        {"id": 2, "agent_id": "b", "content": "..."},
    ]

    assert select_target_post(posts, "a", agents)["id"] == 2


def test_select_conflict_axis_returns_max_difference_axis() -> None:
    agents = {
        "a": make_agent("a", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        "b": make_agent("b", [0, 4, 0, 0, 0, 0, 0, 0, 0, 0]),
    }

    assert select_conflict_axis("a", "b", agents) == "state_intervention"


def test_select_next_agent_skips_temporarily_failed_agents() -> None:
    agents = {
        "a": make_agent("a", [5, 1, 1, 1, 1, 5, 1, 0, 2, 5], ["制度設計"]),
        "b": make_agent("b", [-5, -1, -1, -1, -1, -5, -1, 0, -2, -5], ["制度設計"]),
        "c": make_agent("c", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], ["制度設計"]),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": ["制度設計"]}
    posts = [
        {"id": 1, "agent_id": "a", "content": "..."},
        {"id": 2, "agent_id": "c", "content": "..."},
        {"id": 3, "agent_id": "a", "content": "..."},
    ]

    assert select_next_agent(thread, agents, posts, excluded_agent_ids={"b"}) == "c"
