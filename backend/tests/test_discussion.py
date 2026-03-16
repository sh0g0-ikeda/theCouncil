from __future__ import annotations

import random

from engine.debate_state import DebateState
from engine.discussion import (
    _classify_user_intervention,
    _build_conversation_summary,
    _get_phase,
    _prioritize_speaker,
    _role_for_phase,
    _select_debate_function,
    _sanitize_topic_axes,
    _should_facilitate,
)
from models.agent import Agent, IdeologyVector


def make_agent(agent_id: str, aggressiveness: int = 3) -> Agent:
    return Agent(
        id=agent_id,
        display_name=agent_id,
        label=agent_id,
        persona={
            "speech_constraints": {"aggressiveness": aggressiveness},
            "debate_style": {"aggressiveness": aggressiveness},
        },
        vector=IdeologyVector(0, 0, 0, 0, 0, 0, 0),
    )


def test_phase_transitions() -> None:
    assert _get_phase(0) == 1
    assert _get_phase(8) == 2
    assert _get_phase(23) == 3
    assert _get_phase(38) == 4
    assert _get_phase(45) == 5


def test_role_for_phase() -> None:
    assert _role_for_phase(1) == "counter"
    assert _role_for_phase(4) == "shift"


def test_should_facilitate_on_early_definition_point() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "is_facilitator": False},
        {"id": 2, "agent_id": "b", "is_facilitator": False},
        {"id": 3, "agent_id": "c", "is_facilitator": False},
    ]
    assert _should_facilitate(posts) is True


def test_should_facilitate_ignores_user_posts_when_checking_recent_facilitator_gap() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "is_facilitator": False},
        {"id": 2, "agent_id": None, "is_facilitator": False, "user_id": "u1"},
        {"id": 3, "agent_id": None, "is_facilitator": True},
        {"id": 4, "agent_id": "b", "is_facilitator": False, "focus_axis": "rationalism"},
        {"id": 5, "agent_id": None, "is_facilitator": False, "user_id": "u1"},
        {"id": 6, "agent_id": "c", "is_facilitator": False, "focus_axis": "rationalism"},
        {"id": 7, "agent_id": "a", "is_facilitator": False, "focus_axis": "rationalism"},
        {"id": 8, "agent_id": "b", "is_facilitator": False, "focus_axis": "rationalism"},
    ]

    assert _should_facilitate(posts) is False


def test_conversation_summary_prefers_compressed_history_when_present() -> None:
    recent_posts = [{"display_name": "socrates", "content": "define the regime first"}]
    summary = _build_conversation_summary("older summary", recent_posts)

    assert "older summary" in summary
    assert "socrates" in summary


def test_classify_user_intervention_detects_summary_request() -> None:
    assert _classify_user_intervention("結局論点はなんや。まとめてくれ。") == "summarize"


def test_sanitize_topic_axes_prefers_topic_tags_when_generated_axes_are_off_topic() -> None:
    axes = _sanitize_topic_axes(
        ["国際法上の合法性", "正戦論的許容性"],
        "日本の責任ある積極財政は正しいか",
        ["財政持続性", "インフレリスク", "雇用"],
    )

    assert axes[:2] == ["財政持続性", "インフレリスク"]


def test_prioritize_speaker_prefers_priority_claims() -> None:
    debate = DebateState()
    debate.claims["post:10"] = {
        "post_id": 10,
        "speaker_id": "a",
        "target_agent_id": "b",
        "status": "open",
    }
    debate.claim_order.append("post:10")
    posts = [{"id": 1, "agent_id": "a"}, {"id": 2, "agent_id": "c"}]
    agents = {aid: make_agent(aid) for aid in ("a", "b", "c")}

    assert _prioritize_speaker(["a", "b", "c"], posts, debate, agents, {"a"}) == "b"


def test_prioritize_speaker_prefers_definition_duty_over_other_obligations() -> None:
    debate = DebateState()
    debate.claims["post:10"] = {
        "post_id": 10,
        "speaker_id": "a",
        "target_agent_id": "b",
        "status": "open",
    }
    debate.claim_order.append("post:10")
    debate.definition_requests["democracy"] = {
        "status": "open",
        "requested_post_id": 12,
        "requested_by": "c",
    }
    posts = [{"id": 1, "agent_id": "a"}, {"id": 2, "agent_id": "b"}]
    agents = {aid: make_agent(aid) for aid in ("a", "b", "c")}

    assert _prioritize_speaker(["a", "b", "c"], posts, debate, agents, {"a"}) == "b"


def test_prioritize_speaker_penalizes_axis_repetition_across_last_three_axes() -> None:
    debate = DebateState()
    debate.agreement_streak["b"] = 2
    debate.agreement_streak["c"] = 2
    debate.agent_axis_usage["b"] = ["state_control", "state_control", "tech_optimism"]
    debate.agent_axis_usage["c"] = ["state_control", "rationalism", "future_orientation"]
    agents = {aid: make_agent(aid) for aid in ("b", "c")}

    assert _prioritize_speaker(["b", "c"], [], debate, agents, set()) == "c"


def test_select_debate_function_biases_define_when_terms_are_unresolved() -> None:
    debate = DebateState()
    debate.definition_requests["democracy"] = {
        "status": "open",
        "requested_post_id": 9,
        "requested_by": "a",
    }
    agents = {"a": make_agent("a", aggressiveness=2)}

    original_choices = random.choices
    random.choices = lambda candidates, weights: [candidates[weights.index(max(weights))]]
    try:
        assert _select_debate_function("a", 2, agents, debate) in {"define", "differentiate"}
    finally:
        random.choices = original_choices


def test_select_debate_function_respects_directive_and_constraint() -> None:
    debate = DebateState()
    agents = {"a": make_agent("a", aggressiveness=4)}

    rebut = _select_debate_function(
        "a",
        3,
        agents,
        debate,
        target={"id": 5, "content": "Answer this claim"},
        directive="MISSION:rebut_core_claim do it",
    )
    tradeoff = _select_debate_function(
        "a",
        3,
        agents,
        debate,
        target={"id": 5, "content": "Answer this claim"},
        constraint_kind="tradeoff",
    )

    assert rebut == "attack"
    assert tradeoff == "concretize"
