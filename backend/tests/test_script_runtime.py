from __future__ import annotations

import asyncio

from engine.debate_state import DebateState
from engine.script_runtime import ScriptedDiscussionRunner
import engine.script_runtime as runtime_module
from models.agent import Agent, IdeologyVector


class _FakeDb:
    def __init__(self) -> None:
        self.saved_state: dict | None = None

    async def load_debate_state(self, thread_id: str) -> dict | None:
        return None

    async def save_debate_state(self, thread_id: str, payload: dict) -> None:
        self.saved_state = payload


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


def test_ensure_debate_state_seeds_definition_requests_and_frame() -> None:
    async def _run() -> None:
        original_decompose = runtime_module.decompose_topic_axes
        original_assign_frame = runtime_module.assign_debate_frame

        async def _fake_decompose_topic_axes(topic: str) -> list[str]:
            return ["自由", "安定", "権力"]

        async def _fake_assign_debate_frame(topic: str, agent_list: list[dict]) -> dict:
            return {
                "frame": {
                    "proposition": topic,
                    "support_label": "許容される",
                    "oppose_label": "許容されない",
                    "conditional_label": "条件次第",
                    "support_thesis": "危機下では強い統治が必要",
                    "oppose_thesis": "自由と公共性が先に壊れる",
                },
                "assignments": {
                    "erdogan_fan": {
                        "side": "support",
                        "role": "pro",
                        "thesis": "危機下では強い統治が必要",
                        "keywords": ["統治", "安定"],
                        "camp_function": "state_capacity",
                    },
                    "arendt": {
                        "side": "oppose",
                        "role": "con",
                        "thesis": "自由と公共性が先に壊れる",
                        "keywords": ["自由", "公共性"],
                        "camp_function": "plurality",
                    },
                },
            }

        runtime_module.decompose_topic_axes = _fake_decompose_topic_axes
        runtime_module.assign_debate_frame = _fake_assign_debate_frame
        try:
            db = _FakeDb()
            runner = ScriptedDiscussionRunner(
                thread_id="thread-1",
                db=db,  # type: ignore[arg-type]
                agents={
                    "erdogan_fan": _make_agent("erdogan_fan", "エルドアン"),
                    "arendt": _make_agent("arendt", "アーレント"),
                },
                push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
            )
            debate = await runner._ensure_debate_state(
                {
                    "topic": "全体主義は自由と発展のために許容されるか",
                    "topic_tags": ["自由", "安定"],
                    "agent_ids": ["erdogan_fan", "arendt"],
                }
            )
        finally:
            runtime_module.decompose_topic_axes = original_decompose
            runtime_module.assign_debate_frame = original_assign_frame

        assert debate.abstract_terms
        assert debate.thread_subquestions
        assert debate.definition_requests
        assert all(payload.get("status") == "open" for payload in debate.definition_requests.values())
        assert debate.get_agent_side("erdogan_fan") == "support"
        assert debate.get_agent_side("arendt") == "oppose"
        assert db.saved_state is not None

    asyncio.run(_run())


def test_register_semantic_state_flags_camp_reassert_after_third_same_proposition() -> None:
    debate = DebateState()

    for post_id in range(1, 4):
        debate.record_post(
            speaker_id="mao",
            target_post={"id": 99, "agent_id": "arendt"},
            focus_axis="state_control",
            debate_function="attack",
            stance="disagree",
            post_id=post_id,
            analysis={
                "argument_fingerprint": f"arg-{post_id}",
                "proposition_fingerprint": "prop:centralized-order-is-necessary",
                "claim_structure": {
                    "premises": ["危機には統治集中が必要"],
                    "conclusion": "強い中央権力は必要",
                    "mechanism": "動員速度が上がる",
                },
                "effective_axis": "state_control",
                "claim_units": [
                    {
                        "claim_key": f"claim-{post_id}",
                        "text": "強い中央権力は必要",
                        "terms": ["統治", "権力"],
                    }
                ],
            },
            content="強い中央権力は必要や。",
        )

    assert "camp_reassert" in debate.alerts
    assert any(
        entry.get("proposition_fingerprint") == "prop:centralized-order-is-necessary"
        for entry in debate.open_claim_structures
    )


def test_required_response_kind_prefers_definition_seed_in_opening_turns() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={"arendt": _make_agent("arendt", "アーレント")},
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    debate = DebateState()
    debate.definition_requests["自由"] = {
        "status": "open",
        "requested_post_id": 0,
        "requested_by": "thread_seed",
        "target_agent_id": None,
        "created_post_id": 0,
        "answered_post_id": None,
        "answered_by": None,
    }
    resolved = runtime_module.ResolvedTurn(
        speaker_id="arendt",
        target_post=None,
        directive="",
        move_type="attack",
        phase=1,
        assigned_side="oppose",
        is_user_reply_turn=False,
    )

    required_kind = runner._resolve_required_response_kind([], debate, resolved)

    assert required_kind == "define"


def test_build_generation_context_includes_position_anchor_terms() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={"arendt": _make_agent("arendt", "アーレント")},
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    debate = DebateState()
    debate.position_anchors["arendt"] = {
        "post_id": 1,
        "summary": "公共空間を守るべきだ",
        "terms": ["公共空間", "複数性"],
    }
    resolved = runtime_module.ResolvedTurn(
        speaker_id="arendt",
        target_post=None,
        directive="",
        move_type="attack",
        phase=1,
        assigned_side="oppose",
        is_user_reply_turn=False,
    )

    context = runner._build_generation_context(
        {"topic": "自由は守られるべきか", "topic_tags": [], "agent_ids": ["arendt"]},
        [],
        resolved,
        debate,
    )

    assert context["position_anchor_terms"] == ["公共空間", "複数性"]


def test_turn_delay_seconds_follows_speed_mode() -> None:
    assert runtime_module._turn_delay_seconds("instant") == 0.0
    assert runtime_module._turn_delay_seconds("fast") == 0.4
    assert runtime_module._turn_delay_seconds("normal") == 2.0
    assert runtime_module._turn_delay_seconds("slow") == 5.0
    assert runtime_module._turn_delay_seconds("unknown") == 2.0


def test_resolve_turn_prioritizes_open_subquestion_target_agent() -> None:
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=_FakeDb(),  # type: ignore[arg-type]
        agents={
            "caesar": _make_agent("caesar", "カエサル"),
            "xi": _make_agent("xi", "習近平"),
        },
        push_fn=lambda _thread_id, _payload: asyncio.sleep(0),
    )
    runner.state.cached_script = {
        "turns": [
            {"agent_id": "xi", "move_type": "attack", "assigned_side": "support"},
        ]
    }
    runner.state.debate_state = DebateState()
    runner.state.debate_state.subquestions["sq:10:0"] = {
        "subquestion_id": "sq:10:0",
        "text": "Who should decide when war is unavoidable?",
        "post_id": 10,
        "target_agent_id": "caesar",
        "status": "open",
        "created_post_id": 10,
    }
    runner.state.debate_state.subquestion_order.append("sq:10:0")

    resolved = asyncio.run(
        runner._resolve_turn(
            {"topic": "When is war justified?", "topic_tags": [], "agent_ids": ["caesar", "xi"]},
            [
                {"id": 10, "agent_id": "einstein", "content": "Who should decide when war is unavoidable?"},
                {"id": 11, "agent_id": "xi", "content": "Who decides that in practice?"},
            ],
        )
    )

    assert resolved is not None
    assert resolved.speaker_id == "caesar"
    assert resolved.target_post is not None
    assert resolved.target_post["id"] == 10
