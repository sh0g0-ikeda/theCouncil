from __future__ import annotations

from typing import Any


SYSTEM_PROMPT = """あなたは議論掲示板のAI人格である。なんJ・5ch風の口語体で発言せよ。

ルール:
- 役割に応じて define / differentiate / attack / steelman / concretize / synthesize を使い分ける
- 相手の主張に直接触れずに一般論へ逃げない
- 人格設定、non_negotiable、forbidden_patterns に反する発言をしない
- 60〜200文字程度で、短くても芯のある返答にする
- 罵倒や扇動ではなく、相手の前提・定義・因果・条件を攻める
- JSON以外を返さない
"""

_PHASE_DIRECTIVES: dict[int, str] = {
    1: "フェーズ1: 定義フェーズ。語の意味、評価軸、条件の切り分けを優先し、いきなり結論を断言しすぎない。",
    2: "フェーズ2: 対立フェーズ。相手の一番強い主張に刺し込み、論点を広げすぎずに前提を崩す。",
    3: "フェーズ3: 深掘りフェーズ。因果、反例、具体例、代償を詰める。",
    4: "フェーズ4: 統合フェーズ。対立点を整理し、どこが条件依存かを明示する。",
    5: "フェーズ5: 収束フェーズ。残る争点と暫定結論を短くまとめる。",
}

_SCRIPT_POST_SYSTEM_PROMPT = """あなたは議論掲示板のAI人格だ。なんJ・5ch風の口語体で発言せよ。

ルール:
- 指定された directive / move_type / target を優先する
- target の中心命題に答える
- 人格設定、assigned_side、side_contract を破らない
- JSONのみ返す
- Output JSON only with keys: stance, local_stance_to_target, proposition_stance, camp_function, main_axis, subquestion_id, shift_reason, content, used_arsenal_id.
"""

_PHASE_SCRIPT_HINTS: dict[int, str] = {
    1: "定義と論点整理を優先",
    2: "対立点に切り込む",
    3: "条件と代償を詰める",
    4: "論点を再整理する",
    5: "残る争点を絞る",
}


def _quote_user_text(text: str) -> str:
    normalized = str(text or "").replace("'''", "\\'\\'\\'")
    return f"'''{normalized}'''"


def _join_items(values: list[str], *, separator: str = ", ") -> str:
    return separator.join(v for v in values if v)


def _normalize_list(values: list[Any] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def build_prompt(
    persona: dict[str, Any],
    rag_chunks: list[str],
    context: dict[str, Any],
    retry_hint: str | None = None,
) -> list[dict[str, str]]:
    worldview = _normalize_list(persona.get("worldview", []))
    combat = _normalize_list(persona.get("combat_doctrine", []))
    blindspots = _normalize_list(persona.get("blindspots", []))
    forbidden = _normalize_list(persona.get("forbidden_patterns", []))
    speech_constraints = dict(persona.get("speech_constraints", {}) or {})
    must_distinguish_from = dict(persona.get("must_distinguish_from", {}) or {})

    debate_role = str(context.get("debate_role", "")).strip()
    thread_topic = str(context.get("thread_topic", "")).strip()
    target = dict(context.get("target_post", {}) or {})
    target_content = str(target.get("content", "")).strip()
    conversation_summary = str(context.get("conversation_summary", "")).strip()
    phase = int(context.get("phase", 2) or 2)
    debate_function = str(context.get("debate_function", "attack")).strip() or "attack"

    assigned_side = str(context.get("assigned_side", "")).strip()
    assigned_side_label = str(context.get("assigned_side_label", "")).strip()
    opposing_side_label = str(context.get("opposing_side_label", "")).strip()
    side_contract = str(context.get("side_contract", "")).strip()
    frame_proposition = str(context.get("frame_proposition", "")).strip()
    assigned_camp_function = str(context.get("assigned_camp_function", "")).strip()
    required_proposition_stance = str(context.get("required_proposition_stance", "")).strip()
    required_local_stance = str(context.get("required_local_stance", "")).strip()
    required_subquestion_id = str(context.get("required_subquestion_id", "")).strip()
    required_subquestion_text = str(context.get("required_subquestion_text", "")).strip()
    target_claim_summary = str(context.get("target_claim_summary", "")).strip()
    position_anchor_summary = str(context.get("position_anchor_summary", "")).strip()
    camp_map_summary = str(context.get("camp_map_summary", "")).strip()
    required_response_kind = str(context.get("required_response_kind", "")).strip()
    forced_axis = str(context.get("forced_axis", "")).strip()
    active_constraint = str(context.get("active_constraint", "")).strip()
    private_directive = str(context.get("private_directive", "")).strip()
    meta_intervention_kind = str(context.get("meta_intervention_kind", "")).strip()

    thread_subquestions = _normalize_list(context.get("thread_subquestions", []))
    topic_axes = _normalize_list(context.get("topic_axes", []))
    agent_recent_axes = _normalize_list(context.get("agent_recent_axes", []))
    uncovered_axes = _normalize_list(context.get("uncovered_axes", []))
    pending_definition_terms = _normalize_list(context.get("pending_definition_terms", []))
    recent_argument_fingerprints = _normalize_list(context.get("recent_argument_fingerprints", []))
    forbidden_example_keys = _normalize_list(context.get("forbidden_example_keys", []))
    recent_agent_conclusions = _normalize_list(context.get("recent_agent_conclusions", []))
    current_tags = _normalize_list(context.get("current_tags", []))
    required_concepts = _normalize_list(
        (persona.get("persona_anchors", {}) or {}).get("required_concepts", [])
    )

    persona_lines = [
        f"人格: {persona.get('display_name', '?')} ({persona.get('label', '')})",
        f"世界観: {_join_items(worldview[:4]) or '未設定'}",
    ]
    if combat:
        persona_lines.append(f"主な論法: {_join_items(combat[:3])}")
    if blindspots:
        persona_lines.append(f"弱点: {_join_items(blindspots[:2])}")
    if speech_constraints.get("tone"):
        persona_lines.append(f"口調: {speech_constraints['tone']}")
    if speech_constraints.get("non_negotiable"):
        persona_lines.append(f"絶対条件: {speech_constraints['non_negotiable']}")
    if forbidden:
        persona_lines.append(f"禁止表現: {_join_items(forbidden[:4])}")
    if must_distinguish_from:
        diff_text = _join_items(
            [f"{name}とは{note}" for name, note in list(must_distinguish_from.items())[:2]],
            separator=" / ",
        )
        persona_lines.append(f"区別すべき相手: {diff_text}")
    if debate_role:
        persona_lines.append(f"debate_role: {debate_role}")
    if assigned_side:
        side_line = f"assigned_side: {assigned_side}"
        if assigned_side_label:
            side_line += f" ({assigned_side_label})"
        persona_lines.append(side_line)
    if opposing_side_label:
        persona_lines.append(f"opposing_side_label: {opposing_side_label}")
    if frame_proposition:
        persona_lines.append(f"frame_proposition: {frame_proposition}")
    if side_contract:
        persona_lines.append(f"side_contract: {side_contract}")
    if assigned_camp_function:
        persona_lines.append(f"camp_function: {assigned_camp_function}")

    context_lines = [
        f"phase: {phase} / debate_function: {debate_function}",
        _PHASE_DIRECTIVES.get(phase, ""),
        f"thread_topic: {_quote_user_text(thread_topic)}",
        f"target_post: {_quote_user_text(target_content)}",
        f"conversation_summary: {_quote_user_text(conversation_summary)}",
    ]
    if current_tags:
        context_lines.append(f"current_tags: {_join_items(current_tags[:6], separator=' / ')}")
    if thread_subquestions:
        context_lines.append("thread_subquestions:\n- " + "\n- ".join(thread_subquestions[:6]))
    if topic_axes:
        context_lines.append(f"topic_axes: {_join_items(topic_axes[:6], separator=' / ')}")
    if agent_recent_axes:
        context_lines.append(f"agent_recent_axes: {_join_items(agent_recent_axes[-3:], separator=' / ')}")
    if uncovered_axes:
        context_lines.append(f"uncovered_axes: {_join_items(uncovered_axes[:3], separator=' / ')}")
    if target_claim_summary:
        context_lines.append(f"target_claim_summary: {target_claim_summary}")
    if pending_definition_terms:
        context_lines.append(f"pending_definition_terms: {_join_items(pending_definition_terms[:4], separator=' / ')}")
    if required_concepts:
        context_lines.append(f"required_concepts: {_join_items(required_concepts[:5])}")
    if recent_argument_fingerprints:
        context_lines.append(
            f"recent_argument_fingerprints: {_join_items(recent_argument_fingerprints[:4], separator=' / ')}"
        )
    if forbidden_example_keys:
        context_lines.append(f"forbidden_example_keys: {_join_items(forbidden_example_keys[:4], separator=' / ')}")
    if recent_agent_conclusions:
        context_lines.append(
            f"recent_agent_conclusions: {_join_items(recent_agent_conclusions[:3], separator=' / ')}"
        )
    if position_anchor_summary:
        context_lines.append(f"position_anchor_summary: {position_anchor_summary}")
    if camp_map_summary:
        context_lines.append(f"camp_map_summary: {camp_map_summary}")
    if required_proposition_stance:
        context_lines.append(f"required_proposition_stance: {required_proposition_stance}")
    if required_local_stance:
        context_lines.append(f"required_local_stance: {required_local_stance}")
    if required_subquestion_id:
        context_lines.append(f"required_subquestion_id: {required_subquestion_id}")
    if required_subquestion_text:
        context_lines.append(f"required_subquestion_text: {required_subquestion_text}")
    if required_response_kind:
        context_lines.append(f"required_response_kind: {required_response_kind}")
    if forced_axis:
        context_lines.append(f"forced_axis: {forced_axis}")
    if active_constraint:
        context_lines.append(f"active_constraint: {active_constraint}")
    if private_directive:
        context_lines.append(f"private_directive: {private_directive}")
    if meta_intervention_kind:
        context_lines.append(f"meta_intervention_kind: {meta_intervention_kind}")
    if retry_hint:
        context_lines.append(f"retry_hint: {retry_hint}")

    rag_lines = ["rag_chunks:"] + [f"- {chunk}" for chunk in rag_chunks[:4]] if rag_chunks else ["rag_chunks: なし"]

    behavioral_lines = [
        "出力はJSONのみ。",
        "Output JSON only with keys: stance, local_stance_to_target, proposition_stance, camp_function, main_axis, subquestion_id, shift_reason, content, used_arsenal_id.",
        "stance は disagree / agree / supplement / shift のいずれか。",
        "相手の主張に直接触れてから返答する。",
        "60〜200文字程度に収める。",
    ]
    if debate_function in {"attack", "steelman"} and target_content:
        behavioral_lines.append("target_post の中心命題を一つ選んで、それを正面から扱う。")
    if required_response_kind in {"define", "differentiate"} and pending_definition_terms:
        behavioral_lines.append(
            "required_response_kind が define / differentiate のときは、pending_definition_terms から少なくとも一語を取り、まず定義か定義差分を明示する。"
        )
    if assigned_side in {"support", "oppose"} and opposing_side_label:
        behavioral_lines.append(
            f"assigned_side を勝手に跨がない。反対側({opposing_side_label})へ移る場合だけ stance=shift と shift_reason を使う。"
        )
    if required_concepts:
        behavioral_lines.append("required_concepts のうち少なくとも一つを本文で使う。")

    user_content = "\n".join(
        persona_lines
        + [""]
        + context_lines
        + [""]
        + rag_lines
        + [""]
        + behavioral_lines
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Output JSON only with keys: stance, local_stance_to_target, proposition_stance, "
                "camp_function, main_axis, subquestion_id, shift_reason, content, used_arsenal_id."
            ),
        },
        {"role": "user", "content": user_content},
    ]


def build_script_post_messages(
    persona: dict[str, Any],
    directive: str,
    move_type: str,
    target_post: dict[str, Any],
    recent_posts: list[dict[str, Any]],
    rag_chunks: list[str],
    thread_topic: str,
    phase: int = 2,
    assigned_side: str = "",
    *,
    assigned_side_label: str = "",
    opposing_side_label: str = "",
    side_contract: str = "",
    frame_proposition: str = "",
    assigned_camp_function: str = "",
    required_subquestion_id: str = "",
    required_subquestion_text: str = "",
    turn_contract: dict[str, Any] | None = None,
    pending_definition_terms: list[str] | None = None,
    topic_axes: list[str] | None = None,
    recent_argument_fingerprints: list[str] | None = None,
    forbidden_example_keys: list[str] | None = None,
    required_concepts: list[str] | None = None,
    required_response_kind: str = "",
    retry_hint: str | None = None,
    target_claim_summary: str = "",
    camp_map_summary: str = "",
    abstract_terms: list[str] | None = None,
    resolved_abstract_terms: list[str] | None = None,
    recent_agent_conclusions: list[str] | None = None,
    position_anchor_summary: str = "",
) -> list[dict[str, str]]:
    worldview = _normalize_list(persona.get("worldview", []))
    combat = _normalize_list(persona.get("combat_doctrine", []))
    must_distinguish_from = dict(persona.get("must_distinguish_from", {}) or {})
    tone = str((persona.get("speech_constraints", {}) or {}).get("tone", "")).strip()
    non_negotiable = str((persona.get("speech_constraints", {}) or {}).get("non_negotiable", "")).strip()

    target_content = str(target_post.get("content", "")).strip()
    target_name = str(target_post.get("display_name") or target_post.get("agent_id") or "unknown")
    target_id = target_post.get("id", "?")
    recent_lines = "\n".join(
        f"#{post.get('id', '?')} {post.get('display_name') or post.get('agent_id') or '?'}: {str(post.get('content', ''))[:80]}"
        for post in recent_posts[-5:]
    ) or "なし"
    rag_text = "\n".join(f"- {chunk}" for chunk in rag_chunks[:3]) if rag_chunks else "なし"

    pending_definition_terms = _normalize_list(pending_definition_terms)
    topic_axes = _normalize_list(topic_axes)
    recent_argument_fingerprints = _normalize_list(recent_argument_fingerprints)
    forbidden_example_keys = _normalize_list(forbidden_example_keys)
    required_concepts = _normalize_list(required_concepts)
    abstract_terms = _normalize_list(abstract_terms)
    resolved_abstract_terms = _normalize_list(resolved_abstract_terms)
    recent_agent_conclusions = _normalize_list(recent_agent_conclusions)
    turn_contract = dict(turn_contract or {})
    contract_required_labels = _normalize_list(turn_contract.get("required_labels", []))
    contract_define_terms = _normalize_list(turn_contract.get("must_define_terms", []))
    contract_resolution_target = str(turn_contract.get("resolution_target", "")).strip()
    contract_forbid_question_only = bool(turn_contract.get("forbid_question_only"))

    persona_lines = [
        f"人格: {persona.get('display_name', '?')} ({persona.get('label', '')})",
        f"世界観: {_join_items(worldview[:3]) or '未設定'}",
    ]
    if combat:
        persona_lines.append(f"主な論法: {_join_items(combat[:2], separator=' / ')}")
    if non_negotiable:
        persona_lines.append(f"絶対条件: {non_negotiable}")
    if must_distinguish_from:
        persona_lines.append(
            "区別すべき相手: "
            + _join_items(
                [f"{name}とは{note}" for name, note in list(must_distinguish_from.items())[:2]],
                separator=" / ",
            )
        )
    if tone:
        persona_lines.append(f"口調: {tone}")
    if assigned_side:
        side_line = f"assigned_side: {assigned_side}"
        if assigned_side_label:
            side_line += f" ({assigned_side_label})"
        persona_lines.append(side_line)
    if opposing_side_label:
        persona_lines.append(f"opposing_side_label: {opposing_side_label}")
    if frame_proposition:
        persona_lines.append(f"frame_proposition: {frame_proposition}")
    if side_contract:
        persona_lines.append(f"side_contract: {side_contract}")
    if assigned_camp_function:
        persona_lines.append(f"camp_function: {assigned_camp_function}")

    semantic_lines: list[str] = []
    if target_claim_summary:
        semantic_lines.append(f"target_claim_summary: {target_claim_summary}")
    if required_subquestion_id:
        semantic_lines.append(f"required_subquestion_id: {required_subquestion_id}")
    if required_subquestion_text:
        semantic_lines.append(f"required_subquestion_text: {required_subquestion_text}")
    if contract_required_labels:
        semantic_lines.append(f"turn_contract_required_labels: {_join_items(contract_required_labels, separator=' / ')}")
    if contract_define_terms:
        semantic_lines.append(f"turn_contract_must_define_terms: {_join_items(contract_define_terms, separator=' / ')}")
    if contract_resolution_target:
        semantic_lines.append(f"turn_contract_resolution_target: {contract_resolution_target}")
    if contract_forbid_question_only:
        semantic_lines.append("turn_contract_forbid_question_only: true")
    if required_response_kind:
        semantic_lines.append(f"required_response_kind: {required_response_kind}")
    if topic_axes:
        semantic_lines.append(f"topic_axes: {_join_items(topic_axes[:6], separator=' / ')}")
    if pending_definition_terms:
        semantic_lines.append(f"pending_definition_terms: {_join_items(pending_definition_terms[:4], separator=' / ')}")
    if required_response_kind in {"define", "differentiate"} and pending_definition_terms:
        semantic_lines.append("Open with a definition move before broader evaluation.")
    if abstract_terms:
        semantic_lines.append(f"abstract_terms: {_join_items(abstract_terms[:4], separator=' / ')}")
    if resolved_abstract_terms:
        semantic_lines.append(f"resolved_abstract_terms: {_join_items(resolved_abstract_terms[:4], separator=' / ')}")
    if recent_argument_fingerprints:
        semantic_lines.append(
            f"recent_argument_fingerprints: {_join_items(recent_argument_fingerprints[:4], separator=' / ')}"
        )
    if forbidden_example_keys:
        semantic_lines.append(f"forbidden_example_keys: {_join_items(forbidden_example_keys[:4], separator=' / ')}")
    if required_concepts:
        semantic_lines.append(f"required_concepts: {_join_items(required_concepts[:5])}")
    if recent_agent_conclusions:
        semantic_lines.append(f"recent_agent_conclusions: {_join_items(recent_agent_conclusions[:3], separator=' / ')}")
    if position_anchor_summary:
        semantic_lines.append(f"position_anchor_summary: {position_anchor_summary}")
    if camp_map_summary:
        semantic_lines.append(f"camp_map_summary: {camp_map_summary}")
    if retry_hint:
        semantic_lines.append(f"retry_hint: {retry_hint}")

    user_lines = [
        f"thread_topic: {thread_topic}",
        *persona_lines,
        "",
        f"directive: {directive}",
        f"move_type: {move_type}",
        f"phase_hint: {_PHASE_SCRIPT_HINTS.get(phase, '')}",
        "",
        f"target_post: #{target_id} {target_name}: {target_content[:140]}",
        "",
        "recent_posts:",
        recent_lines,
        "",
        "rag_chunks:",
        rag_text,
    ]
    if semantic_lines:
        user_lines.extend(["", "semantic_context:"] + semantic_lines)
    user_lines.extend(
        [
            "",
            "ルール:",
            "- Output JSON only with keys: stance, local_stance_to_target, proposition_stance, camp_function, main_axis, subquestion_id, shift_reason, content, used_arsenal_id.",
            "- target_post の中心命題に答える。",
            "- assigned_side と side_contract を勝手に破らない。",
            "- 60〜200文字程度に収める。",
        ]
    )

    if contract_required_labels:
        user_lines.append(
            "- If turn_contract_required_labels is present, include each label literally in the body, for example 結論: ... / 判断主体: ... / 判断基準: ... ."
        )
        user_lines.append(
            "- Start the body with the required labels in order. Put the direct answer under 結論 before any criticism or qualification."
        )
    if contract_define_terms:
        user_lines.append(
            "- If turn_contract_must_define_terms is present, define at least one of those terms explicitly in the body."
        )
    if contract_forbid_question_only:
        user_lines.append(
            "- Do not only restate the assigned question. Answer first, then criticize or qualify."
        )

    return [
        {"role": "system", "content": _SCRIPT_POST_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]
