from __future__ import annotations

import asyncio

from engine.debate_state import DebateState
from engine.script_runtime import ScriptedDiscussionRunner
import engine.script_runtime as runtime_module
from engine.validator import validate_generated_reply
from models.agent import Agent, IdeologyVector


class _FakeDb:
    async def load_debate_state(self, thread_id: str) -> dict | None:
        return None

    async def save_debate_state(self, thread_id: str, payload: dict) -> None:
        return None


def _make_agent(agent_id: str, display_name: str) -> Agent:
    persona = {
        "id": agent_id,
        "display_name": display_name,
        "label": display_name,
        "worldview": [f"{display_name} worldview"],
        "combat_doctrine": [],
        "speech_constraints": {},
        "argument_arsenal": [],
    }
    return Agent(
        id=agent_id,
        display_name=display_name,
        label=display_name,
        persona=persona,
        vector=IdeologyVector(0, 0, 0, 0, 0, 0, 0),
    )


def test_build_generation_context_derives_turn_contract_from_priority_subquestion() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={"caesar": _make_agent("caesar", "Caesar")},
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    debate = DebateState()
    debate.subquestions["sq:10:0"] = {
        "subquestion_id": "sq:10:0",
        "text": "Who should decide when war is unavoidable?",
        "post_id": 10,
        "target_agent_id": "caesar",
        "status": "open",
        "created_post_id": 10,
    }
    debate.subquestion_order.append("sq:10:0")

    context = runner._build_generation_context(
        {"topic": "When is war justified?", "topic_tags": [], "agent_ids": ["caesar"]},
        [{"id": 10, "agent_id": "einstein", "content": "War cannot be justified without explicit criteria."}],
        runtime_module.ResolvedTurn(
            speaker_id="caesar",
            target_post={"id": 10, "content": "War cannot be justified without explicit criteria."},
            directive="",
            move_type="attack",
            phase=2,
            assigned_side="support",
            is_user_reply_turn=False,
        ),
        debate,
    )

    assert context["turn_contract"]["must_answer_subquestion_id"] == "sq:10:0"
    assert context["turn_contract"]["forbid_question_only"] is True
    assert "結論" in context["turn_contract"]["required_labels"]
    assert "判断主体" in context["turn_contract"]["required_labels"]
    assert "判断基準" in context["turn_contract"]["required_labels"]


def test_build_generation_context_does_not_require_definition_label_for_seed_turn() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={"caesar": _make_agent("caesar", "Caesar")},
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    debate = DebateState()
    debate.definition_requests["war"] = {
        "status": "open",
        "requested_post_id": 0,
        "requested_by": "thread_seed",
        "target_agent_id": None,
        "created_post_id": 0,
        "answered_post_id": None,
        "answered_by": None,
    }

    context = runner._build_generation_context(
        {"topic": "When is war justified?", "topic_tags": [], "agent_ids": ["caesar"]},
        [],
        runtime_module.ResolvedTurn(
            speaker_id="caesar",
            target_post={},
            directive="",
            move_type="opening_statement",
            phase=1,
            assigned_side="support",
            is_user_reply_turn=False,
        ),
        debate,
    )

    assert context["required_response_kind"] == "define"
    assert "war" in context["turn_contract"]["must_define_terms"]
    assert "定義" not in context["turn_contract"]["required_labels"]


def test_resolve_turn_resets_script_state_when_opening_turns_all_fail() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={"caesar": _make_agent("caesar", "Caesar")},
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    runner.state.cached_script = {
        "turns": [
            {"agent_id": "caesar", "move_type": "opening_statement"},
        ]
    }
    runner.state.script_turn_index = 1
    runner.state.turn_fail_counts = {0: 3}
    runner.state.debate_state = DebateState()

    resolved = asyncio.run(
        runner._resolve_turn(
            {"topic": "When is war justified?", "topic_tags": [], "agent_ids": ["caesar"]},
            [],
        )
    )

    assert resolved is None
    assert runner.state.cached_script is None
    assert runner.state.script_turn_index == 0
    assert runner.state.turn_fail_counts == {}


def test_validate_generated_reply_requires_turn_contract_labels() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "war ethics",
            "content": "War may become unavoidable in a narrow emergency, but that does not remove the need for strict limits.",
            "stance": "disagree",
            "local_stance_to_target": "disagree",
            "proposition_stance": "oppose",
            "camp_function": "ethics",
            "subquestion_id": "sq:1:0",
        },
        {
            "target_post": {"id": 3, "content": "Who should decide when war is unavoidable?"},
            "conflict_axis": "war ethics",
            "assigned_side": "oppose",
            "assigned_camp_function": "ethics",
            "required_subquestion_id": "sq:1:0",
            "target_claim_units": [
                {
                    "claim_id": "claim:3:0",
                    "text": "Who should decide when war is unavoidable?",
                    "terms": ["war", "decide", "unavoidable"],
                }
            ],
            "turn_contract": {
                "must_answer_subquestion_id": "sq:1:0",
                "required_labels": ["結論", "判断主体", "判断基準"],
                "forbid_question_only": True,
            },
        },
    )

    assert result.ok is False
    assert "labels" in result.retry_hint.lower()


def test_validate_generated_reply_accepts_structured_turn_contract_answer() -> None:
    result = validate_generated_reply(
        {
            "main_axis": "war ethics",
            "content": (
                "結論: 戦争開始は限定条件でのみ許される。"
                "判断主体: 主権国家だけでなく議会と国際機関の共同判断が必要だ。"
                "判断基準: 継続的侵略、外交の失敗、市民保護の必要性が揃う場合に限る。"
                "制約条件: 期限、事後審査、撤退条件を明示する。"
            ),
            "stance": "disagree",
            "local_stance_to_target": "disagree",
            "proposition_stance": "oppose",
            "camp_function": "ethics",
            "subquestion_id": "sq:1:0",
        },
        {
            "target_post": {"id": 3, "content": "Who should decide when war is unavoidable?"},
            "conflict_axis": "war ethics",
            "assigned_side": "oppose",
            "assigned_camp_function": "ethics",
            "required_subquestion_id": "sq:1:0",
            "target_claim_units": [
                {
                    "claim_id": "claim:3:0",
                    "text": "Who should decide when war is unavoidable?",
                    "terms": ["war", "decide", "unavoidable"],
                }
            ],
            "turn_contract": {
                "must_answer_subquestion_id": "sq:1:0",
                "required_labels": ["結論", "判断主体", "判断基準"],
                "forbid_question_only": True,
            },
        },
    )

    assert result.ok is True
