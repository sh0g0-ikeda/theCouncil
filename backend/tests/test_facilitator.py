from __future__ import annotations

from engine.facilitator import _select_facilitator_function


class DebateStub:
    def __init__(
        self,
        *,
        unresolved_terms: list[str] | None = None,
        open_claims: int = 0,
        axis_depth: dict[str, str] | None = None,
        agent_sides: dict[str, str] | None = None,
        followup_assignments: list[dict[str, object]] | None = None,
    ) -> None:
        self._unresolved_terms = unresolved_terms or []
        self._open_claims = open_claims
        self.axis_depth = axis_depth or {}
        self.agent_sides = agent_sides or {}
        self.followup_assignments = followup_assignments or []

    def get_unresolved_terms(self) -> list[str]:
        return list(self._unresolved_terms)

    def count_open_claims(self) -> int:
        return self._open_claims


def test_select_facilitator_function_prioritizes_unresolved_terms() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "focus_axis": "rationalism"},
        {"id": 2, "agent_id": "b", "focus_axis": "rationalism"},
        {"id": 3, "agent_id": "c", "focus_axis": "rationalism"},
        {"id": 4, "agent_id": "a", "focus_axis": "rationalism"},
    ]

    assert _select_facilitator_function(posts, DebateStub(unresolved_terms=["民主主義"])) == "define"


def test_select_facilitator_function_uses_open_claim_pressure() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "focus_axis": "rationalism", "reply_to": None},
        {"id": 2, "agent_id": "b", "focus_axis": "rationalism", "reply_to": None},
        {"id": 3, "agent_id": "c", "focus_axis": "order", "reply_to": None},
        {"id": 4, "agent_id": "a", "focus_axis": "order", "reply_to": None},
        {"id": 5, "agent_id": "b", "focus_axis": "rationalism", "reply_to": None},
        {"id": 6, "agent_id": "c", "focus_axis": "order", "reply_to": None},
    ]

    assert _select_facilitator_function(posts, DebateStub(open_claims=4, axis_depth={"order": "contested"})) == "refocus"


def test_force_tradeoff_not_selected_without_contested_axis() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "focus_axis": "rationalism", "reply_to": None},
        {"id": 2, "agent_id": "b", "focus_axis": "rationalism", "reply_to": None},
        {"id": 3, "agent_id": "c", "focus_axis": "order", "reply_to": None},
        {"id": 4, "agent_id": "a", "focus_axis": "order", "reply_to": None},
        {"id": 5, "agent_id": "b", "focus_axis": "rationalism", "reply_to": None},
        {"id": 6, "agent_id": "c", "focus_axis": "order", "reply_to": None},
    ]

    assert _select_facilitator_function(posts, DebateStub(open_claims=2, axis_depth={})) != "force_tradeoff"


def test_select_facilitator_function_can_reassert_camps() -> None:
    posts = [
        {"id": 1, "agent_id": "a", "focus_axis": "innovation", "reply_to": 1},
        {"id": 2, "agent_id": "b", "focus_axis": "innovation", "reply_to": 1},
        {"id": 3, "agent_id": "c", "focus_axis": "power", "reply_to": 2},
        {"id": 4, "agent_id": "d", "focus_axis": "power", "reply_to": 2},
        {"id": 5, "agent_id": "a", "focus_axis": "innovation", "reply_to": 3},
        {"id": 6, "agent_id": "b", "focus_axis": "innovation", "reply_to": 4},
    ]

    debate = DebateStub(
        open_claims=3,
        axis_depth={"innovation": "contested"},
        agent_sides={"a": "support", "b": "support", "c": "oppose", "d": "oppose"},
    )

    assert _select_facilitator_function(posts, debate) == "camp_reassert"
