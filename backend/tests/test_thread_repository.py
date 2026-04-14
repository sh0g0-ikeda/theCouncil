from __future__ import annotations

from db.thread_repository import _coerce_state_json


def test_coerce_state_json_accepts_dicts() -> None:
    payload = {"turn": 1, "phase": "opening"}
    assert _coerce_state_json(payload) == payload


def test_coerce_state_json_parses_json_strings() -> None:
    assert _coerce_state_json('{"turn": 1, "phase": "opening"}') == {
        "turn": 1,
        "phase": "opening",
    }


def test_coerce_state_json_rejects_invalid_shapes() -> None:
    assert _coerce_state_json("[1, 2, 3]") is None
    assert _coerce_state_json("not-json") is None
