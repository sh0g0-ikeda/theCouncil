from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class IdeologyVector:
    state_control: int        # -5=自由市場/無政府 ↔ +5=国家統制
    tech_optimism: int        # -5=技術悲観 ↔ +5=テクノ楽観
    rationalism: int          # -5=直感/神秘 ↔ +5=純粋理性/実証
    power_realism: int        # -5=理想主義/平和主義 ↔ +5=現実政治/武力
    individualism: int        # -5=急進的集団主義 ↔ +5=急進的個人主義
    moral_universalism: int   # -5=ニヒリズム/相対主義 ↔ +5=普遍道徳
    future_orientation: int   # -5=保守/伝統回帰 ↔ +5=急進的進歩主義

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
                f"前回の本文は{len(reply['content'])}文字だった。本文を80〜180文字に収め、"
                "JSONのみ出力し、used_arsenal_idも含めよ。"
            )

        raise LLMGenerationError(
            f"Failed after {max_attempts} attempts for agent={self.id}: {last_issue}"
        )
