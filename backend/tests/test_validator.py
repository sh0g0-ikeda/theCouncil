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


def test_validate_generated_reply_allows_non_attack_without_overlap() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "rationalism",
            "content": "The deeper issue is how institutions decay once public judgment becomes passive.",
        },
        {
            "target_post": {"id": 3, "content": "Democracy needs legal legitimacy and accountability."},
            "conflict_axis": "rationalism",
            "required_response_kind": "synthesize",
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
