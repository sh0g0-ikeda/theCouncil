import asyncio

from engine.llm import LLMGenerationError
from models.agent import Agent, IdeologyVector


def test_generate_reply_raises_after_retries_and_uses_retry_hint() -> None:
    agent = Agent(
        id="nietzsche",
        display_name="ニーチェ",
        label="反道徳・強者肯定",
        persona={
            "display_name": "ニーチェ",
            "label": "反道徳・強者肯定",
            "core_beliefs": ["既存の道徳や価値体系を疑う"],
            "dislikes": ["群れの道徳"],
            "values": ["個人の卓越"],
            "speaking_style": {"tone": "挑発的"},
            "debate_style": {"aggressiveness": 4, "cooperativeness": 1},
            "forbidden_patterns": ["犯罪の助長"],
            "sample_lines": ["前提を疑え。"],
        },
        vector=IdeologyVector(0, -2, 0, -4, 5, -1, 3, -5, 3, 2),
    )

    async def run() -> None:
        from engine import llm as llm_module
        from engine import rag as rag_module

        original_call_llm = llm_module.call_llm
        original_retrieve_chunks = rag_module.retrieve_chunks
        prompts: list[list[dict[str, str]]] = []

        async def fake_call_llm(messages: list[dict[str, str]]) -> dict:
            prompts.append(messages)
            return {
                "reply_to": None,
                "stance": "disagree",
                "main_axis": "rationalism",
                "content": "短い",
                "_token_usage": 0,
            }

        rag_module.retrieve_chunks = lambda *_args, **_kwargs: []
        llm_module.call_llm = fake_call_llm
        try:
            try:
                await agent.generate_reply({"thread_topic": "AIと国家"}, max_attempts=3)
            except LLMGenerationError:
                assert len(prompts) == 3
                assert "前回の本文は" in prompts[-1][-1]["content"]
            else:  # pragma: no cover - defensive
                raise AssertionError("LLMGenerationError was not raised")
        finally:
            llm_module.call_llm = original_call_llm
            rag_module.retrieve_chunks = original_retrieve_chunks

    asyncio.run(run())
