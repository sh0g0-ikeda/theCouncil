from __future__ import annotations

import json
from typing import Any

_VECTOR_KEYS = [
    "state_control",
    "tech_optimism",
    "rationalism",
    "power_realism",
    "individualism",
    "moral_universalism",
    "future_orientation",
]


def row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "persona_json" in data and isinstance(data["persona_json"], str):
        data["persona_json"] = json.loads(data["persona_json"])
    if "script_json" in data and isinstance(data["script_json"], str):
        data["script_json"] = json.loads(data["script_json"])
    return data


def persona_to_vector(persona: dict[str, Any]) -> list[int]:
    ideology = persona.get("ideology_vector", {})
    return [int(ideology.get(key, 0)) for key in _VECTOR_KEYS]
