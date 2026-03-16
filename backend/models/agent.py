from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class IdeologyVector:
    state_control: int
    tech_optimism: int
    rationalism: int
    power_realism: int
    individualism: int
    moral_universalism: int
    future_orientation: int

    def as_list(self) -> list[int]:
        return [
            self.state_control,
            self.tech_optimism,
            self.rationalism,
            self.power_realism,
            self.individualism,
            self.moral_universalism,
            self.future_orientation,
        ]

    def manhattan_distance(self, other: "IdeologyVector") -> int:
        return sum(abs(a - b) for a, b in zip(self.as_list(), other.as_list()))


@dataclass(slots=True)
class Agent:
    id: str
    display_name: str
    label: str
    persona: dict[str, Any]
    vector: IdeologyVector

    async def generate_reply(
        self,
        context: dict[str, Any],
        retry_hint: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        from engine.llm import LLMGenerationError, build_prompt, call_llm, validate_reply_length
        from engine.rag import retrieve_chunks
        from engine.validator import validate_generated_reply

        chunks = retrieve_chunks(self.id, context)
        current_retry_hint = retry_hint
        last_issue = "unknown"

        for attempt in range(1, max_attempts + 1):
            prompt = build_prompt(self.persona, chunks, context, retry_hint=current_retry_hint)
            try:
                reply = await call_llm(prompt)
            except LLMGenerationError as exc:
                last_issue = str(exc)
                current_retry_hint = (
                    "前回はJSON形式が崩れた。reply_to, stance, main_axis, content を含むJSONだけを返せ。"
                )
                continue

            if not validate_reply_length(reply["content"]):
                last_issue = f"invalid_length:{len(reply['content'])}"
                current_retry_hint = (
                    f"本文が {len(reply['content'])} 文字や。80〜180文字に収めて、JSONだけを返せ。"
                )
                continue

            main_axis = str(reply.get("main_axis", ""))
            recent_axes = [str(axis) for axis in context.get("agent_recent_axes", [])]
            if main_axis and recent_axes.count(main_axis) >= 2 and attempt < max_attempts:
                last_issue = f"axis_repeat:{main_axis}"
                current_retry_hint = f"{main_axis} は直近で使いすぎや。別の軸で言い直せ。"
                continue

            validation = validate_generated_reply(reply, context)
            if not validation.ok:
                last_issue = validation.retry_hint or "semantic_validation_failed"
                current_retry_hint = validation.retry_hint
                if attempt < max_attempts:
                    continue
                break

            reply["_semantic_analysis"] = validation.analysis.as_dict()
            return reply

        raise LLMGenerationError(
            f"Failed after {max_attempts} attempts for agent={self.id}: {last_issue}"
        )
