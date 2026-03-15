from __future__ import annotations

import json
import os
import random
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


# Four facilitator functions with distinct structural roles
_FACILITATOR_FUNCTIONS = {
    "define": (
        "議論で使われている中心的な用語の定義が揺れているか曖昧になっている。"
        "「その『○○』って何の○○？」という形で定義を要求・指摘せよ。"
    ),
    "differentiate": (
        "参加者がAとBを混同して議論が噛み合っていない。"
        "「○○と○○は別問題じゃないか」という形で議論を分断・整理せよ。"
    ),
    "concretize": (
        "抽象的な主張が続いて具体性がない。"
        "「それ今の○○（制度/企業/事例）で言うと何になるの？」という形で現代の具体例を要求せよ。"
    ),
    "expose_split": (
        "双方の根本的な対立軸がまだ明示されていない。"
        "「結局これって○○を目的と見るか手段と見るかの対立だろ」という形で合意不能な核心を一つ指摘せよ。"
    ),
}

FACILITATOR_SYSTEM_PROMPT = """あなたは議論掲示板に割り込む「構造修正装置」だ。
与えられた【機能】を正確に実行し、議論の構造的問題を一刺しする。

ルール:
- 掲示板の口語体で書け（論文・ナレーター調禁止）
- 「まとめ」「バランス」「どちらも大切」は禁止
- 「てか」「草」等の崩し口語OK。煽り可だが人格攻撃禁止
- 60〜120文字・1〜2文
- JSONのみ: {"content":"...","stance":"facilitate","main_axis":"..."}"""


async def make_facilitate(thread: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not posts:
        return None

    latest = posts[-6:]
    fallback_axis = next(
        (post.get("focus_axis") for post in reversed(latest) if post.get("focus_axis")),
        "rationalism",
    )

    fn_key = _select_facilitator_function(posts)
    fn_instruction = _FACILITATOR_FUNCTIONS[fn_key]

    if not os.getenv("OPENAI_API_KEY"):
        fallbacks = {
            "define": f"てかこの議論で言う「{fallback_axis}」って具体的に何を指してるの？全員バラバラな定義で話してない？",
            "differentiate": f"「{fallback_axis}」の話と制度設計の話、ごっちゃになってない？切り分けて話せよ。",
            "concretize": "抽象論ばっかだけど、これ今の具体的な制度や事例で言うと何になるの？",
            "expose_split": f"結局これって「{fallback_axis}」を目的と見るか手段と見るかの対立でしょ。そこが合意できてない。",
        }
        return {
            "content": fallbacks[fn_key],
            "stance": "facilitate",
            "main_axis": fallback_axis,
            "_token_usage": 0,
        }

    transcript = "\n".join(
        f"#{post['id']} {post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content']}"
        for post in latest
    )
    user_content = (
        f"テーマ: {thread['topic']}\n"
        f"論点タグ: {', '.join(thread.get('topic_tags', []))}\n"
        f"【機能】{fn_instruction}\n"
        f"最近の発言:\n{transcript}"
    )
    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": FACILITATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=180,
        temperature=0.5,
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return {
        "content": str(payload.get("content", "")).strip(),
        "stance": "facilitate",
        "main_axis": str(payload.get("main_axis", fallback_axis)),
        "_token_usage": int(getattr(response.usage, "total_tokens", 0) or 0),
    }


def _select_facilitator_function(posts: list[dict[str, Any]]) -> str:
    """Choose facilitator function based on what the debate currently lacks."""
    ai_posts = [p for p in posts if p.get("agent_id")]

    if len(ai_posts) <= 12:
        return random.choice(["define", "differentiate"])

    recent_axes = [p.get("focus_axis") for p in ai_posts[-8:] if p.get("focus_axis")]
    if len(set(recent_axes)) <= 2 and len(recent_axes) >= 6:
        return random.choice(["concretize", "expose_split"])

    if len(ai_posts) >= 20:
        return random.choice(["expose_split", "concretize"])

    return random.choice(list(_FACILITATOR_FUNCTIONS.keys()))
