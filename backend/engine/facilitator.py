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

FACILITATOR_SYSTEM_PROMPT = """あなたは議論のファシリテーターである。
- 争点を1つに絞って整理する
- 120〜180文字
- 誰かを裁定しない
- JSONのみで返す
{"content":"...", "stance":"facilitate", "main_axis":"..."}"""


async def make_facilitate(thread: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not posts:
        return None

    latest = posts[-6:]
    fallback_axis = next(
        (post.get("focus_axis") for post in reversed(latest) if post.get("focus_axis")),
        "rationalism",
    )
    if not os.getenv("OPENAI_API_KEY"):
        summary_bits = " / ".join(
            f"{post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content'][:28]}"
            for post in latest[-3:]
        )
        return {
            "content": f"ここまでの対立は「{fallback_axis}」に集約できる。{summary_bits} を踏まえ、次は理想論ではなく、実装条件と副作用を同じ尺度で比べてほしい。",
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
