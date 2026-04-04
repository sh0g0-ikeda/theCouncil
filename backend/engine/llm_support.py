from __future__ import annotations

import re
from typing import Any


def _frame_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]{2,24}", text or "")


def _fallback_debate_frame(topic: str, agent_list: list[dict[str, Any]]) -> dict[str, Any]:
    proposition = (topic or "").strip() or "the proposition"
    frame = {
        "proposition": proposition,
        "support_label": "yes",
        "oppose_label": "no",
        "conditional_label": "depends",
        "support_thesis": f"Argue that the proposition is true: {proposition}",
        "oppose_thesis": f"Argue that the proposition is false, overstated, or survives through adaptation: {proposition}",
    }
    assignments: dict[str, dict[str, Any]] = {}
    role_map = {"support": "pro", "oppose": "con", "conditional": "neutral"}
    rotation = ("support", "oppose", "conditional")
    camp_rotation = (
        "innovation",
        "competition",
        "consumer_welfare",
        "safety",
        "power_concentration",
    )
    for index, agent in enumerate(agent_list):
        side = rotation[index % len(rotation)]
        camp_function = camp_rotation[index % len(camp_rotation)]
        if side == "support":
            thesis = frame["support_thesis"]
        elif side == "oppose":
            thesis = frame["oppose_thesis"]
        else:
            thesis = (
                "Argue that the proposition turns on concrete conditions and "
                f"separate the conditions under which it changes: {proposition}"
            )
        assignments[str(agent["id"])] = {
            "side": side,
            "role": role_map[side],
            "thesis": thesis,
            "keywords": _frame_terms(thesis)[:8],
            "camp_function": camp_function,
        }
    return {"frame": frame, "assignments": assignments}


def validate_reply_length(content: str) -> bool:
    length = len(content.strip())
    return 60 <= length <= 200


def _normalize_reply(payload: dict[str, Any]) -> dict[str, Any]:
    stance = payload.get("stance", "disagree")
    if stance not in {"disagree", "agree", "supplement", "shift"}:
        stance = "disagree"

    proposition_stance = str(payload.get("proposition_stance", "")).strip()
    if proposition_stance not in {"support", "oppose", "conditional", "shift"}:
        proposition_stance = ""

    local_stance_to_target = str(payload.get("local_stance_to_target", "")).strip()
    if local_stance_to_target not in {"agree", "disagree", "supplement", "shift"}:
        local_stance_to_target = stance if stance in {"agree", "disagree", "supplement", "shift"} else ""

    camp_function = str(payload.get("camp_function", "")).strip()
    used_id = payload.get("used_arsenal_id")
    return {
        "reply_to": payload.get("reply_to"),
        "stance": stance,
        "local_stance_to_target": local_stance_to_target,
        "proposition_stance": proposition_stance,
        "camp_function": camp_function,
        "main_axis": str(payload.get("main_axis", "rationalism")),
        "subquestion_id": str(payload.get("subquestion_id", "")).strip(),
        "shift_reason": str(payload.get("shift_reason", "")).strip(),
        "content": str(payload.get("content", "")).strip(),
        "used_arsenal_id": str(used_id) if used_id and used_id != "null" else None,
    }
