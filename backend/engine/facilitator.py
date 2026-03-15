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

FACILITATOR_SYSTEM_PROMPT = """あなたは議論のファシリテーターである。役割は「要約」ではなく「次の争点を設計すること」。

ルール:
- 今の対立がどこでズレているかを一言で断言する
- 次に掘り下げるべき問いか切り口を1つ鋭く投げかける
- 「まとめ」「どちらも大切」「バランスが必要」等の調整発言は禁止
- 対話の熱を上げる煽り型でよい（ただし中立の立場から）
- 120〜180文字
- JSONのみで返す
{"content":"...", "stance":"facilitate", "main_axis":"..."}

例の切り口:
- 「この議論は〜の問いにまで遡らないと解けない」
- 「〜と〜は対立しているように見えるが、実は〜という前提で一致している。そこを突け」
- 「〜はまだ誰も答えていない。次はそこを」
- 「問題の核心は〜ではなく〜だ。論点を移せ」"""


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
