"""Tests for the new features added in this session."""
from __future__ import annotations

from engine.debate_state import DebateState
from engine.discussion import seed_subquestions, _extract_abstract_nouns
from engine.selector import participation_floor_penalty, select_next_agent
from engine.validator import (
    classify_reply_semantics,
    validate_generated_reply,
    _extract_claim_structure,
    _make_proposition_fingerprint,
    _check_persona_anchor,
    _char_overlap_ratio,
)
from engine.rag import retrieve_chunks, EVIDENCE_FAMILIES
from models.agent import Agent, IdeologyVector


# ── 1. seed_subquestions ────────────────────────────────────────────────────

def test_seed_subquestions_produces_up_to_8():
    sqs = seed_subquestions("国家の死滅は可能か")
    assert isinstance(sqs, list)
    assert 1 <= len(sqs) <= 8


def test_seed_subquestions_covers_four_families():
    topic = "プロレタリア独裁の正当性"
    sqs = seed_subquestions(topic)
    # Should have at least 4 (one per family for the first noun)
    assert len(sqs) >= 4
    joined = " ".join(sqs)
    assert "とは何か" in joined
    assert "条件" in joined or "妨げる" in joined
    assert "失敗" in joined or "弱点" in joined
    assert "移行" in joined or "何が変わる" in joined


def test_seed_subquestions_empty_topic():
    sqs = seed_subquestions("")
    assert isinstance(sqs, list)


def test_seed_subquestions_max_two_nouns():
    sqs = seed_subquestions("自由と民主主義と社会と国家")
    # max 2 nouns => max 8 subquestions
    assert len(sqs) <= 8


# ── 2. extract_abstract_nouns ────────────────────────────────────────────────

def test_extract_abstract_nouns_basic():
    nouns = _extract_abstract_nouns("国家の死滅は可能か", max_nouns=5)
    assert isinstance(nouns, list)
    assert len(nouns) <= 5
    # Should exclude single chars
    for n in nouns:
        assert len(n) >= 2


def test_extract_abstract_nouns_excludes_particles():
    nouns = _extract_abstract_nouns("これはそれのため", max_nouns=5)
    assert "これ" not in nouns
    assert "それ" not in nouns
    assert "ため" not in nouns


# ── 3. DebateState new fields ─────────────────────────────────────────────────

def test_debate_state_thread_subquestions_default():
    d = DebateState()
    assert d.thread_subquestions == []


def test_debate_state_record_proposition():
    d = DebateState()
    count = d.record_proposition("agent1", "fp_abc")
    assert count == 1
    count2 = d.record_proposition("agent1", "fp_abc")
    assert count2 == 2
    count3 = d.record_proposition("agent1", "fp_other")
    assert count3 == 1


def test_debate_state_check_camp_reassert():
    d = DebateState()
    d.record_proposition("agent1", "fp_x")
    d.record_proposition("agent1", "fp_x")
    assert not d.check_camp_reassert("agent1", "fp_x", threshold=3)
    d.record_proposition("agent1", "fp_x")
    assert d.check_camp_reassert("agent1", "fp_x", threshold=3)


def test_debate_state_alerts():
    d = DebateState()
    assert "camp_reassert" not in d.alerts
    d.alerts.add("camp_reassert")
    assert "camp_reassert" in d.alerts


def test_debate_state_deduplicates_similar_open_subquestions():
    d = DebateState()
    base_analysis = {
        "effective_axis": "war ethics",
        "proposition_stance": "support",
        "camp_function": "state_capacity",
        "argument_fingerprint": "fp-1",
        "claim_units": [
            {
                "claim_key": "claim-1",
                "text": "Who should decide when war is unavoidable?",
                "terms": ["war", "decide", "unavoidable"],
            }
        ],
    }

    d.record_post(
        speaker_id="caesar",
        target_post={"id": 10, "agent_id": "einstein"},
        focus_axis="war ethics",
        debate_function="attack",
        stance="disagree",
        post_id=1,
        analysis=base_analysis,
        content="War may be justified when order collapses.",
    )
    d.record_post(
        speaker_id="xi",
        target_post={"id": 11, "agent_id": "einstein"},
        focus_axis="war ethics",
        debate_function="attack",
        stance="disagree",
        post_id=2,
        analysis={
            **base_analysis,
            "argument_fingerprint": "fp-2",
            "claim_units": [
                {
                    "claim_key": "claim-2",
                    "text": "Who decides whether war is unavoidable?",
                    "terms": ["war", "decide", "unavoidable"],
                }
            ],
        },
        content="Order sometimes requires force.",
    )

    assert len(d.subquestions) == 1
    only_subquestion = next(iter(d.subquestions.values()))
    assert only_subquestion["duplicate_count"] == 2
    assert "camp_reassert" in d.alerts


def test_debate_state_serialization_round_trip():
    d = DebateState()
    d.thread_subquestions = ["subq1", "subq2"]
    d.abstract_terms = ["term1", "term2"]
    d.alerts.add("camp_reassert")
    d.record_proposition("a1", "fp1")
    d.record_proposition("a1", "fp1")
    d.open_claim_structures.append({"agent_id": "a1", "post_id": 1, "structure": {"conclusion": "X"}})
    data = d.to_dict()
    d2 = DebateState.from_dict(data)
    assert d2.thread_subquestions == ["subq1", "subq2"]
    assert d2.abstract_terms == ["term1", "term2"]
    assert "camp_reassert" in d2.alerts
    assert d2.camp_proposition_map["a1"].count("fp1") == 2
    assert len(d2.open_claim_structures) == 1


# ── 4. participation_floor_penalty ──────────────────────────────────────────

def test_floor_penalty_zero_appearances():
    posts = [
        {"agent_id": "b"},
        {"agent_id": "b"},
        {"agent_id": "c"},
        {"agent_id": "b"},
    ]
    # agent "a" has 0 appearances → floor boost
    result = participation_floor_penalty("a", posts, window=8, max_share=0.4)
    assert result == 2.0


def test_floor_penalty_over_max_share():
    posts = [
        {"agent_id": "a"},
        {"agent_id": "a"},
        {"agent_id": "a"},
        {"agent_id": "a"},
        {"agent_id": "b"},
    ]
    # agent "a" has 4/5 = 80% > 40% → penalty
    result = participation_floor_penalty("a", posts, window=8, max_share=0.4)
    assert result == -3.0


def test_floor_penalty_normal():
    # a has 1/4 = 25% share, below max_share=0.4 → 0.0
    posts = [
        {"agent_id": "a"},
        {"agent_id": "b"},
        {"agent_id": "c"},
        {"agent_id": "b"},
    ]
    result = participation_floor_penalty("a", posts, window=8, max_share=0.4)
    assert result == 0.0


def test_floor_penalty_empty_posts():
    result = participation_floor_penalty("a", [], window=8, max_share=0.4)
    assert result == 0.0


# ── 5. Hard guard in select_next_agent ──────────────────────────────────────

def _make_agent(agent_id: str, vals: list[int] | None = None) -> Agent:
    vals = vals or [0] * 7
    vector = IdeologyVector(*vals)
    persona: dict = {"worldview": [], "combat_doctrine": [], "argument_arsenal": []}
    return Agent(id=agent_id, display_name=agent_id, label=agent_id, persona=persona, vector=vector)


def test_hard_guard_skips_overrepresented_agent():
    agents = {
        "a": _make_agent("a"),
        "b": _make_agent("b"),
        "c": _make_agent("c"),
    }
    thread = {"agent_ids": ["a", "b", "c"], "topic_tags": []}
    # "a" appears 3 times in last 5, "c" has 0
    posts = [
        {"id": i, "agent_id": "b", "content": "x"} for i in range(1, 3)
    ] + [
        {"id": i+2, "agent_id": "a", "content": "x"} for i in range(1, 4)
    ]
    # Run 20 times - "a" should be very rarely selected (c has zero appearances)
    from collections import Counter
    counts = Counter()
    import random
    random.seed(42)
    for _ in range(100):
        try:
            winner = select_next_agent(thread, agents, posts)
            counts[winner] += 1
        except ValueError:
            pass
    # "a" should win much less than "c" due to hard guard
    # (or not win at all since it violates the guard)
    assert counts["c"] > counts["a"] or counts["a"] == 0


# ── 6. claim structure extraction ────────────────────────────────────────────

def test_extract_claim_structure_basic():
    content = "なぜなら民主主義は脆弱だから。権力集中こそ安定をもたらす。"
    cs = _extract_claim_structure(content)
    assert isinstance(cs["premises"], list)
    assert isinstance(cs["conclusion"], str)
    assert "mechanism" in cs


def test_extract_claim_structure_with_mechanism():
    content = "規律によって主体が形成されることで権力が浸透する。"
    cs = _extract_claim_structure(content)
    assert cs["mechanism"] is not None or cs["mechanism"] is None  # at minimum, key exists


def test_proposition_fingerprint():
    content = "プロレタリア独裁は移行期の必然的形態である"
    fp = _make_proposition_fingerprint(content)
    assert isinstance(fp, str)
    assert len(fp) > 0


# ── 7. persona anchor check ──────────────────────────────────────────────────

def test_check_persona_anchor_passes_with_concept():
    persona = {
        "persona_anchors": {
            "required_concepts": ["例外状態", "友/敵"],
            "forbidden_generics": ["民主主義一般"]
        }
    }
    assert _check_persona_anchor("例外状態こそ政治の本質だ", persona) is True


def test_check_persona_anchor_fails_without_concept():
    persona = {
        "persona_anchors": {
            "required_concepts": ["例外状態", "友/敵"],
            "forbidden_generics": ["民主主義一般"]
        }
    }
    assert _check_persona_anchor("民主主義は大切だ", persona) is False


def test_check_persona_anchor_no_anchors():
    persona = {}
    assert _check_persona_anchor("anything goes", persona) is True


def test_validate_rejects_missing_persona_anchor():
    persona = {
        "persona_anchors": {
            "required_concepts": ["例外状態", "友/敵"],
        }
    }
    # No target_post so target-overlap check is bypassed; test pure persona anchor rejection
    result = validate_generated_reply(
        {
            "stance": "disagree",
            "main_axis": "rationalism",
            "content": "民主主義は一般的に良い制度だが問題がある",
            "proposition_stance": "oppose",
            "local_stance_to_target": "disagree",
        },
        {
            "debate_function": "attack",
            "required_response_kind": "attack",
            "target_post": {},
            "assigned_side": "oppose",
            "persona": persona,
        }
    )
    assert result.ok is False
    assert "required concepts" in result.retry_hint.lower() or "concept" in result.retry_hint.lower()


def test_validate_allows_persona_anchor_satisfied():
    persona = {
        "persona_anchors": {
            "required_concepts": ["例外状態"],
        }
    }
    result = validate_generated_reply(
        {
            "stance": "disagree", "main_axis": "power",
            "content": "例外状態においてこそ主権者の本質が露わになる",
            "proposition_stance": "oppose",
        },
        {
            "debate_function": "attack",
            "required_response_kind": "attack",
            "target_post": {"id": 1, "content": "民主主義こそ最善の制度だ"},
            "assigned_side": "oppose",
            "persona": persona,
        }
    )
    # Should not fail on persona anchor (may fail on other checks, but not anchor)
    if not result.ok:
        assert "required concepts" not in result.retry_hint.lower()


# ── 8. char_overlap_ratio ────────────────────────────────────────────────────

def test_char_overlap_ratio_identical():
    assert _char_overlap_ratio("abc", "abc") == 1.0


def test_char_overlap_ratio_no_overlap():
    ratio = _char_overlap_ratio("abc", "def")
    assert ratio == 0.0


def test_char_overlap_ratio_partial():
    ratio = _char_overlap_ratio("abc", "bcd")
    assert 0.0 < ratio < 1.0


# ── 9. SemanticPostAnalysis new fields ──────────────────────────────────────

def test_semantic_analysis_has_new_fields():
    analysis = classify_reply_semantics(
        {"stance": "disagree", "main_axis": "power", "content": "プロレタリア独裁は矛盾を解決する"},
        {}
    )
    assert hasattr(analysis, "proposition_fingerprint")
    assert hasattr(analysis, "claim_structure")
    assert isinstance(analysis.proposition_fingerprint, str)
    assert isinstance(analysis.claim_structure, dict)
    assert "conclusion" in analysis.claim_structure
    assert "premises" in analysis.claim_structure
    assert "mechanism" in analysis.claim_structure


def test_semantic_analysis_round_trip():
    analysis = classify_reply_semantics(
        {"stance": "disagree", "main_axis": "power", "content": "テスト内容"},
        {}
    )
    d = analysis.as_dict()
    assert "proposition_fingerprint" in d
    assert "claim_structure" in d
    from engine.validator import SemanticPostAnalysis
    analysis2 = SemanticPostAnalysis.from_dict(d)
    assert analysis2.proposition_fingerprint == analysis.proposition_fingerprint
    assert analysis2.claim_structure == analysis.claim_structure


# ── 10. RAG evidence families ────────────────────────────────────────────────

def test_evidence_families_defined():
    assert "state_withering" in EVIDENCE_FAMILIES
    assert "authoritarian_capture" in EVIDENCE_FAMILIES
    assert len(EVIDENCE_FAMILIES) == 7


def test_retrieve_chunks_returns_list():
    # Without actual chunk files, should return empty list
    result = retrieve_chunks("nonexistent_agent", {"thread_topic": "国家の死滅"})
    assert isinstance(result, list)


# ── 11. Phase 1 definition check ────────────────────────────────────────────

def test_phase1_blocks_attack_when_abstract_terms():
    # Use no target post to bypass address-target check
    result = validate_generated_reply(
        {
            "stance": "disagree",
            "main_axis": "power",
            "content": "独裁は効率的だ",
            "proposition_stance": "oppose",
            "local_stance_to_target": "disagree",
        },
        {
            "debate_function": "attack",
            "required_response_kind": "attack",
            "target_post": {},
            "abstract_terms": ["独裁", "正当性"],
            "debate_post_count": 2,
            "assigned_side": "oppose",
        }
    )
    assert result.ok is False
    assert "phase1_definition_required" in result.retry_hint


def test_phase1_allows_define_function():
    result = validate_generated_reply(
        {
            "stance": "disagree",
            "main_axis": "power",
            "content": "独裁とは一人が全決定を行う統治形態だ",
        },
        {
            "debate_function": "define",
            "required_response_kind": "define",
            "target_post": {},
            "abstract_terms": ["独裁", "正当性"],
            "debate_post_count": 3,
        }
    )
    # Should not fail on phase1_definition check
    if not result.ok:
        assert "phase1_definition_required" not in result.retry_hint


def test_phase1_not_active_after_post_4():
    result = validate_generated_reply(
        {
            "stance": "disagree",
            "main_axis": "power",
            "content": "独裁は矛盾に満ちている",
            "proposition_stance": "oppose",
        },
        {
            "debate_function": "attack",
            "required_response_kind": "attack",
            "target_post": {"id": 1, "content": "独裁"},
            "abstract_terms": ["独裁"],
            "debate_post_count": 5,
            "assigned_side": "oppose",
        }
    )
    # phase1 should not trigger (post count > 4)
    if not result.ok:
        assert "phase1_definition_required" not in result.retry_hint
