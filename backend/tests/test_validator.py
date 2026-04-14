from __future__ import annotations

from engine.debate_state import DebateState
from engine.validator import classify_reply_semantics, validate_generated_reply


def test_validate_generated_reply_rejects_target_mismatch() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "rationalism",
            "content": "Mars factories matter because engineering speed matters more than institutions.",
        },
        {
            "target_post": {"id": 3, "content": "Democracy needs legal legitimacy and accountability."},
            "conflict_axis": "rationalism",
        },
    )

    assert result.ok is False
    assert result.retry_hint


def test_validate_generated_reply_allows_meta_summary_without_target_overlap() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "rationalism",
            "content": "The deeper issue is how institutions decay once public judgment becomes passive.",
        },
        {
            "target_post": {"id": 3, "content": "Democracy needs legal legitimacy and accountability."},
            "conflict_axis": "rationalism",
            "required_response_kind": "synthesize",
            "meta_intervention_kind": "summarize",
        },
    )

    assert result.ok is True


def test_validate_generated_reply_rejects_reused_examples() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "rationalism",
            "content": "For example, the Iraq war shows how democratic rhetoric can turn into a cover for violence.",
        },
        {
            "target_post": {"id": 3, "content": "The Iraq war was an exception, not the rule."},
            "conflict_axis": "rationalism",
            "forbidden_example_keys": ["iraq war"],
            "required_response_kind": "synthesize",
        },
    )

    assert result.ok is False
    assert "iraq war" in result.retry_hint.lower()


def test_validate_generated_reply_enforces_tradeoff_constraint() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "market_trust",
            "content": "Growth matters because speed matters more than distributive caution.",
            "stance": "disagree",
        },
        {
            "target_post": {"id": 3, "content": "Speed matters most in policy."},
            "conflict_axis": "market_trust",
            "required_response_kind": "concretize",
            "active_constraint_kind": "tradeoff",
        },
    )

    assert result.ok is False


def test_validate_generated_reply_enforces_structured_allowed_axes() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "security",
            "content": "Costs matter because inflation risk and debt rollover both hit later.",
            "stance": "disagree",
        },
        {
            "target_post": {"id": 3, "content": "Speed matters most in fiscal policy."},
            "conflict_axis": "fiscal sustainability",
            "active_constraint_schema": {"allowed_axes": ["fiscal sustainability"]},
        },
    )

    assert result.ok is False


def test_validate_generated_reply_rejects_alignment_with_opposite_role() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "fiscal sustainability",
            "content": "I agree that aggressive stimulus is necessary because growth comes first.",
            "stance": "agree",
        },
        {
            "target_post": {"id": 3, "content": "Aggressive stimulus is necessary to support demand."},
            "conflict_axis": "fiscal sustainability",
            "debate_role": "con",
            "target_debate_role": "pro",
            "position_anchor_terms": ["credit", "risk", "debt"],
        },
    )

    assert result.ok is False


def test_validate_generated_reply_rejects_opening_post_that_breaks_assigned_side() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "capitalism",
            "content": "Capitalism survives because every crisis only makes it more adaptive and resilient.",
            "stance": "disagree",
            "proposition_stance": "oppose",
        },
        {
            "target_post": {},
            "conflict_axis": "capitalism",
            "is_first_post": True,
            "assigned_side": "support",
            "assigned_side_label": "capitalism will end",
            "frame_proposition": "Capitalism will eventually end.",
            "support_label": "end",
            "oppose_label": "survive",
            "support_thesis": "Capitalism will end because contradiction and breakdown accumulate.",
            "oppose_thesis": "Capitalism survives by adaptation and recomposition.",
            "position_anchor_terms": ["capitalism", "end", "contradiction", "breakdown"],
        },
    )

    assert result.ok is False


def test_validate_generated_reply_allows_explicit_shift_to_opposite_side() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "capitalism",
            "content": "I shift here: capitalism may survive longer than I said because adaptation can absorb some crises.",
            "stance": "shift",
            "proposition_stance": "shift",
            "shift_reason": "I concede that adaptive recomposition can delay collapse.",
        },
        {
            "target_post": {},
            "conflict_axis": "capitalism",
            "assigned_side": "support",
            "assigned_side_label": "capitalism will end",
            "frame_proposition": "Capitalism will eventually end.",
            "support_label": "end",
            "oppose_label": "survive",
            "support_thesis": "Capitalism will end because contradiction and breakdown accumulate.",
            "oppose_thesis": "Capitalism survives by adaptation and recomposition.",
            "position_anchor_terms": ["capitalism", "end", "contradiction", "breakdown"],
        },
    )

    assert result.ok is True


def test_validate_generated_reply_requires_explicit_proposition_stance() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "ai monopoly",
            "content": "Concentrated capital is dangerous because one actor can set the boundary of frontier research and the whole field.",
            "stance": "disagree",
        },
        {
            "target_post": {"id": 3, "content": "Concentrated capital can accelerate frontier research."},
            "conflict_axis": "ai monopoly",
            "assigned_side": "support",
            "assigned_side_label": "monopoly is bad",
            "assigned_camp_function": "power_concentration",
        },
    )

    assert result.ok is False
    assert "proposition_stance" in result.retry_hint


def test_validate_generated_reply_rejects_wrong_camp_function() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "ai monopoly",
            "content": "Monopoly hurts consumer welfare because the same central platforms foreclose alternatives and reduce choice.",
            "stance": "disagree",
            "local_stance_to_target": "disagree",
            "proposition_stance": "support",
            "camp_function": "innovation",
        },
        {
            "target_post": {"id": 3, "content": "Monopoly lets labs invest at frontier scale."},
            "conflict_axis": "ai monopoly",
            "assigned_side": "support",
            "assigned_side_label": "monopoly is bad",
            "assigned_camp_function": "consumer_welfare",
        },
    )

    assert result.ok is False
    assert "camp_function" in result.retry_hint


def test_validate_generated_reply_requires_subquestion_when_assigned() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "ai monopoly",
            "content": "Scale can accelerate safety research, but concentrated compute narrows who gets to shape the stack.",
            "stance": "disagree",
            "local_stance_to_target": "disagree",
            "proposition_stance": "support",
            "camp_function": "power_concentration",
            "subquestion_id": "sq:other",
        },
        {
            "target_post": {"id": 3, "content": "Scale can accelerate safety research."},
            "conflict_axis": "ai monopoly",
            "assigned_side": "support",
            "assigned_camp_function": "power_concentration",
            "required_subquestion_id": "sq:1:0",
        },
    )

    assert result.ok is False
    assert "subquestion" in result.retry_hint.lower()


def test_validate_generated_reply_enforces_rebut_directive_stance() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "rationalism",
            "content": "I agree that legal legitimacy matters, but institutions still drift.",
            "stance": "agree",
        },
        {
            "target_post": {"id": 3, "content": "Democracy needs legal legitimacy and accountability."},
            "conflict_axis": "rationalism",
            "required_response_kind": "attack",
            "private_directive": "MISSION:rebut_core_claim answer it",
        },
    )

    assert result.ok is False


def test_classify_reply_semantics_extracts_definition_terms() -> None:
    analysis = classify_reply_semantics(
        {
            "main_axis": "rationalism",
            "content": "民主主義とは、権力を公開の討議で拘束する制度のことや",
        },
        {
            "target_post": {"id": 8, "content": "そもそも民主主義って何を指してるんや"},
            "pending_definition_terms": ["民主主義"],
            "required_response_kind": "define",
            "conflict_axis": "rationalism",
        },
    )

    assert analysis.addresses_target is True
    assert "民主主義" in analysis.definition_terms


def test_definition_terms_do_not_count_as_target_address_for_attack() -> None:
    analysis = classify_reply_semantics(
        {
            "main_axis": "rationalism",
            "content": "民主主義とは何かをまず定義しよう",
        },
        {
            "target_post": {"id": 8, "content": "民主主義は選挙の正当性を必要とする"},
            "pending_definition_terms": ["民主主義"],
            "required_response_kind": "attack",
            "conflict_axis": "rationalism",
        },
    )

    assert analysis.definition_terms == ["民主主義"]
    assert analysis.addresses_target is False


def test_classify_reply_semantics_detects_unquoted_definition_request() -> None:
    analysis = classify_reply_semantics(
        {
            "main_axis": "rationalism",
            "content": "そもそも民主主義って何やねん、定義を先に出せや",
        },
        {
            "target_post": {"id": 8, "content": "民主主義は重要や"},
            "conflict_axis": "rationalism",
        },
    )

    assert "民主主義" in analysis.definition_requests


def test_classify_reply_semantics_extracts_claim_units() -> None:
    analysis = classify_reply_semantics(
        {
            "main_axis": "rationalism",
            "content": "民主主義は法で権力を縛るべきや。だが非常時には例外も必要や",
        },
        {
            "target_post": {"id": 8, "content": "民主主義は万能や"},
            "conflict_axis": "rationalism",
            "required_response_kind": "attack",
        },
    )

    assert len(analysis.claim_units) >= 1
    assert analysis.claim_units[0]["claim_key"].startswith("rationalism:")


def test_classify_reply_semantics_normalizes_axis_to_topic_candidates() -> None:
    analysis = classify_reply_semantics(
        {
            "main_axis": "正戦論的許容性",
            "content": "Fiscal credibility matters because inflation expectations can spiral.",
        },
        {
            "thread_topic": "日本の責任ある積極財政は正しいか",
            "current_tags": ["財政持続性", "インフレリスク", "雇用"],
            "topic_axes": ["財政持続性", "インフレリスク"],
            "conflict_axis": "財政持続性",
            "target_post": {"id": 8, "content": "積極財政は需要を支える"},
            "required_response_kind": "attack",
        },
    )

    assert analysis.effective_axis in {"財政持続性", "インフレリスク", "雇用"}
    assert analysis.effective_axis != "正戦論的許容性"


def test_debate_state_tracks_open_claims_and_definition_requests() -> None:
    debate = DebateState()
    debate.record_post(
        "a",
        {"id": 2, "agent_id": "b", "content": "What does democracy mean?"},
        "rationalism",
        debate_function="attack",
        stance="disagree",
        post_id=11,
        analysis={
            "effective_axis": "rationalism",
            "argument_fingerprint": "rationalism:democracy|law",
            "definition_requests": ["民主主義"],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [],
            "example_keys": ["iraq war"],
            "claim_units": [
                {"claim_key": "rationalism:law|legitimacy", "text": "definition first", "terms": ["law", "legitimacy"]}
            ],
        },
        content="定義が曖昧なまま進めるな",
    )

    assert debate.get_priority_post_id_for("b") == 11
    assert debate.get_unresolved_terms() == ["民主主義"]
    assert "rationalism:democracy|law" in debate.recent_argument_fingerprints
    assert debate.get_claim_units_for_post(11)


def test_debate_state_registers_binary_frame_and_shift() -> None:
    debate = DebateState()
    debate.set_debate_frame(
        {
            "proposition": "Capitalism will eventually end.",
            "support_label": "end",
            "oppose_label": "survive",
            "conditional_label": "depends",
            "support_thesis": "Capitalism ends through contradiction.",
            "oppose_thesis": "Capitalism survives through adaptation.",
        },
        {
            "elon": {
                "side": "oppose",
                "role": "con",
                "thesis": "Capitalism survives through adaptation.",
                "keywords": ["capitalism", "survives", "adaptation"],
                "camp_function": "innovation",
            }
        },
    )

    debate.record_post(
        "elon",
        {"id": 2, "agent_id": "marx", "content": "Capitalism ends."},
        "capitalism",
        debate_function="attack",
        stance="shift",
        post_id=12,
        analysis={
            "effective_axis": "capitalism",
            "effective_function": "attack",
            "aligned_side": "support",
            "argument_fingerprint": "capitalism:end|contradiction",
            "definition_requests": [],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [],
            "example_keys": [],
            "referenced_terms": ["capitalism", "end", "contradiction"],
            "claim_units": [{"claim_key": "capitalism:end", "text": "capitalism ends", "terms": ["capitalism", "end"]}],
        },
        content="I shift: capitalism may actually end through contradiction.",
    )

    assert debate.get_agent_side("elon") == "support"
    assert debate.shift_history["elon"][-1]["to"] == "support"
    assert debate.get_camp_function("elon") == "innovation"


def test_debate_state_keeps_open_attack_until_answered_claim_is_marked() -> None:
    debate = DebateState()
    debate.record_post(
        "a",
        {"id": 2, "agent_id": "b", "content": "Democracy is enough"},
        "rationalism",
        debate_function="attack",
        stance="disagree",
        post_id=11,
        analysis={
            "effective_axis": "rationalism",
            "argument_fingerprint": "rationalism:democracy|legitimacy",
            "definition_requests": [],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [],
            "example_keys": [],
            "claim_units": [
                {"claim_key": "rationalism:democracy|legitimacy", "text": "You ignore legitimacy", "terms": ["democracy", "legitimacy"]}
            ],
        },
        content="You are ignoring legitimacy",
    )
    debate.record_post(
        "b",
        {"id": 9, "agent_id": "c", "content": "Talk about another thing"},
        "order",
        debate_function="attack",
        stance="disagree",
        post_id=12,
        analysis={
            "effective_axis": "order",
            "argument_fingerprint": "order:security|state",
            "definition_requests": [],
            "definition_terms": [],
            "answered_post_ids": [9],
            "answered_claim_ids": [],
            "example_keys": [],
            "claim_units": [
                {"claim_key": "order:security|state", "text": "State collapse matters", "terms": ["security", "state"]}
            ],
        },
        content="State collapse matters more",
    )

    assert debate.has_open_attack_against("b") is True


def test_debate_state_can_answer_one_claim_unit_without_closing_all() -> None:
    debate = DebateState()
    debate.record_post(
        "a",
        {"id": 2, "agent_id": "b", "content": "Claim bundle"},
        "rationalism",
        debate_function="attack",
        stance="disagree",
        post_id=20,
        analysis={
            "effective_axis": "rationalism",
            "argument_fingerprint": "rationalism:law|order",
            "definition_requests": [],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [],
            "example_keys": [],
            "claim_units": [
                {"claim_key": "rationalism:law|order", "text": "law matters", "terms": ["law", "order"]},
                {"claim_key": "rationalism:trust|voice", "text": "voice matters", "terms": ["trust", "voice"]},
            ],
        },
        content="law matters. voice matters.",
    )
    claim_units = debate.get_claim_units_for_post(20)
    debate.record_post(
        "b",
        {"id": 20, "agent_id": "a", "content": "law matters. voice matters."},
        "rationalism",
        debate_function="attack",
        stance="disagree",
        post_id=21,
        analysis={
            "effective_axis": "rationalism",
            "argument_fingerprint": "rationalism:law|risk",
            "definition_requests": [],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [claim_units[0]["claim_id"]],
            "example_keys": [],
            "claim_units": [
                {"claim_key": "rationalism:law|risk", "text": "law creates paralysis", "terms": ["law", "risk"]}
            ],
        },
        content="law creates paralysis",
    )

    open_claims = [claim for claim in debate.claims.values() if claim.get("status") == "open" and claim.get("target_agent_id") == "b"]
    assert len(open_claims) == 1


def test_debate_state_ages_stale_claims_and_definition_requests() -> None:
    debate = DebateState()
    debate.record_post(
        "a",
        {"id": 2, "agent_id": "b", "content": "What does democracy mean?"},
        "rationalism",
        debate_function="attack",
        stance="disagree",
        post_id=11,
        analysis={
            "effective_axis": "rationalism",
            "argument_fingerprint": "rationalism:democracy|law",
            "definition_requests": ["民主主義"],
            "definition_terms": [],
            "answered_post_ids": [],
            "answered_claim_ids": [],
            "example_keys": [],
            "claim_units": [
                {"claim_key": "rationalism:democracy|law", "text": "law matters", "terms": ["democracy", "law"]}
            ],
        },
        content="law matters",
    )

    debate.age_obligations(30)

    assert debate.count_open_claims() == 0
    assert debate.get_unresolved_terms() == []
