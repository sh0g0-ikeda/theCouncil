from __future__ import annotations

import json
import os
from typing import Any

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

_client: Any | None = None


def _get_client() -> Any:
    global _client
    if AsyncOpenAI is None:
        raise RuntimeError("openai package is required")
    if _client is None:
        _client = AsyncOpenAI()
    return _client

FACILITATOR_SYSTEM_PROMPT = """あなたは議論掲示板に現れる「的外れな空気を変える参加者」だ。議論が煮詰まったら割り込んで刺す。

ルール:
- 議論が噛み合っていない点や全員がスルーしている核心を1行で突く
- 掲示板の口語体で書け（論文・ナレーター口調禁止）
- 「まとめ」「どちらも大切」「バランス」は禁止
- 煽り可だが人格攻撃禁止
- 60〜120文字
- JSONのみ: {"content":"...", "stance":"facilitate", "main_axis":"..."}

良い例:
- 「結局〜ってことじゃないの。誰も答えてないけど」
- 「〜と〜、同じこと言ってるのに気づいてないの草」
- 「〜の前提がそもそも間違ってる気がするんだが」
- 「てかこれ〜の話なのに〜の話になってね？」
- 「〜で一番重要なのって〜じゃなくて〜では？」"""


async def make_facilitate(thread: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not posts:
        return None

    latest = posts[-6:]
    fallback_axis = next(
        (post.get("focus_axis") for post in reversed(latest) if post.get("focus_axis")),
        "rationalism",
    )
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "content": f"「{fallback_axis}」の対立が続いているが、問うべきは誰がその仕組みを所有・設計するかだ。制度の善悪より先に、その設計者は誰で、誰の利益を反映するかを答えよ。",
            "stance": "facilitate",
            "main_axis": fallback_axis,
            "_token_usage": 0,
        }

    transcript = "\n".join(
        f"#{post['id']} {post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content']}"
        for post in latest
    )
    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": FACILITATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"テーマ: {thread['topic']}\n論点タグ: {', '.join(thread.get('topic_tags', []))}\n最近の発言:\n{transcript}",
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=220,
        temperature=0.4,
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return {
        "content": str(payload.get("content", "")).strip(),
        "stance": "facilitate",
        "main_axis": str(payload.get("main_axis", fallback_axis)),
        "_token_usage": int(getattr(response.usage, "total_tokens", 0) or 0),
    }
