from __future__ import annotations

from engine.debate_state import DebateState


def test_debate_state_facade_exposes_query_and_control_methods() -> None:
    debate = DebateState()

    assert hasattr(debate, "set_debate_frame")
    assert hasattr(debate, "push_directive")
    assert hasattr(debate, "age_obligations")
    assert hasattr(debate, "get_priority_post_id_for")
    assert hasattr(debate, "peek_constraint_schema")
