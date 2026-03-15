from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class IdeologyVector:
    tech_optimism: int
    state_intervention: int
    market_trust: int
    order_preference: int
    individualism: int
    rationalism: int
    power_affirmation: int
    moral_universalism: int
    strategic_aggression: int
    future_orientation: int

    def as_list(self) -> list[int]:
        return [
            self.tech_optimism,
            self.state_intervention,
            self.market_trust,
            self.order_preference,
            self.individualism,
            self.rationalism,
            self.power_affirmation,
            self.moral_universalism,
            self.strategic_aggression,
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
                    "前回の出力はJSON要件を満たさなかった。JSONのみを返し、reply_to, stance, "
                    "main_axis, content を必ず含めよ。"
                )
                continue

            if validate_reply_length(reply["content"]):
                return reply

            last_issue = f"invalid_length:{len(reply['content'])}"
            current_retry_hint = (
                f"前回の本文は{len(reply['content'])}文字だった。本文を40〜120文字に収め、"
                "JSON以外を出さず、対象レスへの反応を一論点に絞れ。"
            )

        raise LLMGenerationError(
            f"Failed after {max_attempts} attempts for agent={self.id}: {last_issue}"
        )
