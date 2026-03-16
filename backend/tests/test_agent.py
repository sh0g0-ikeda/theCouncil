from __future__ import annotations

import asyncio

from engine.llm import LLMGenerationError
from models.agent import Agent, IdeologyVector


def make_agent() -> Agent:
    return Agent(
        id="orwell",
        display_name="Orwell",
        label="language honesty",
        persona={
            "display_name": "Orwell",
            "label": "language honesty",
            "worldview": ["political language corrupts reality"],
            "combat_doctrine": ["attack one premise directly"],
            "blindspots": ["over-indexes on propaganda"],
            "speech_constraints": {"tone": "direct", "aggressiveness": 3},
            "forbidden_patterns": ["personal attacks"],
        },
        vector=IdeologyVector(0, 0, 4, -2, 1, 3, 0),
    )


def test_generate_reply_retries_with_semantic_hint_and_raises() -> None:
    agent = make_agent()

    async def run() -> None:
        from engine import llm as llm_module
        from engine import rag as rag_module

        original_call_llm = llm_module.call_llm
        original_retrieve_chunks = rag_module.retrieve_chunks
        prompts: list[list[dict[str, str]]] = []

        async def fake_call_llm(messages: list[dict[str, str]]) -> dict[str, object]:
            prompts.append(messages)
            return {
                "reply_to": None,
                "stance": "disagree",
                "main_axis": "rationalism",
                "content": "Solar rockets and Mars colonies matter because engineering speed matters more than politics.",
                "_token_usage": 0,
            }

        rag_module.retrieve_chunks = lambda *_args, **_kwargs: []
        llm_module.call_llm = fake_call_llm
        try:
            try:
                await agent.generate_reply(
                    {
                        "thread_topic": "Is democracy the best regime?",
                        "target_post": {"id": 10, "content": "Democracy needs legal legitimacy and public accountability."},
                        "agent_recent_axes": [],
                    },
                    max_attempts=3,
                )
            except LLMGenerationError:
                assert len(prompts) == 3
                assert "Answer the target post's core claim directly." in prompts[-1][-1]["content"]
            else:  # pragma: no cover - defensive
                raise AssertionError("LLMGenerationError was not raised")
        finally:
            llm_module.call_llm = original_call_llm
            rag_module.retrieve_chunks = original_retrieve_chunks

    asyncio.run(run())


def test_generate_reply_attaches_semantic_analysis() -> None:
    agent = make_agent()

    async def run() -> None:
        from engine import llm as llm_module
        from engine import rag as rag_module

        original_call_llm = llm_module.call_llm
        original_retrieve_chunks = rag_module.retrieve_chunks

        async def fake_call_llm(_messages: list[dict[str, str]]) -> dict[str, object]:
            return {
                "reply_to": None,
                "stance": "disagree",
                "main_axis": "rationalism",
                "content": "Democracy still needs legal accountability. If public power escapes the law, the regime rots from inside.",
                "_token_usage": 0,
            }

        rag_module.retrieve_chunks = lambda *_args, **_kwargs: []
        llm_module.call_llm = fake_call_llm
        try:
            reply = await agent.generate_reply(
                {
                    "thread_topic": "Is democracy the best regime?",
                    "target_post": {"id": 10, "content": "Democracy needs legal legitimacy and public accountability."},
                    "agent_recent_axes": [],
                },
                max_attempts=1,
            )
            assert "_semantic_analysis" in reply
            assert reply["_semantic_analysis"]["addresses_target"] is True
            assert reply["_semantic_analysis"]["claim_units"]
        finally:
            llm_module.call_llm = original_call_llm
            rag_module.retrieve_chunks = original_retrieve_chunks

    asyncio.run(run())
