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


# Five facilitator functions with distinct structural roles
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
    "rerail": (
        "議論の争点が混線していて全員が似た方向に流れている。"
        "今の争点を①②③の3軸に整理してそれぞれ名前をつけ、「次の3レスは1人1軸だけで話せ」と宣言せよ。"
        "そのうえで axis_assignments フィールドに各エージェントが担当する軸を割り当てよ。"
    ),
    "force_tradeoff": (
        "一方が都合の悪いトレードオフを避けて論点を立てている。"
        "「○○を主張するなら××というコストを認めるか」という形で両者に嫌な選択を突きつけよ。"
        "constraintフィールドに「次の2レスはこのトレードオフへの応答のみ」という制約を入れること。"
    ),
    "refocus": (
        "争点が散らかって議論が噛み合っていない。"
        "「次の2レスはXだけに限定して答えよ」という短い命令で戦場を狭めよ。Xは今の争点の核心。"
        "constraintフィールドに「次の2レスは〜のみ答えよ」という制約テキストを入れること。"
    ),
}

FACILITATOR_SYSTEM_PROMPT = """あなたは議論掲示板に割り込む「構造修正装置」だ。
与えられた【機能】を正確に実行し、議論の構造的問題を一刺しする。

ルール:
- なんJ・5ch風の口語体で書け（論文・ナレーター調禁止）
- 「まとめ」「バランス」「どちらも大切」は禁止
- 「てか」「やろがい」「〜やろ」等の崩し口語を積極的に使え。煽り可だが人格攻撃禁止
- 「草」「wwww」「w」は禁止
- 文末に「。」を使うな
- 40〜90文字・1文のみ。簡潔に一刺しするだけ。長い説明は禁止。
- rerail以外: JSONのみ: {"content":"...","stance":"facilitate","main_axis":"..."}
- rerailのみ: {"content":"...","stance":"facilitate","main_axis":"...","axis_assignments":[{"agent_id":"...","axis":"..."},...]}
- force_tradeoff/refocusのみ: {"content":"...","stance":"facilitate","main_axis":"...","constraint":"次の2レスは〜のみ","constraint_turns":2}"""


async def make_facilitate(
    thread: dict[str, Any],
    posts: list[dict[str, Any]],
    agent_display_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Returns facilitate payload, with optional axis_assignments list for rerail."""
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
            "rerail": f"争点が混線しとるんや。①効率 ②公平性 ③多様性 の3軸に整理して、次は1人1軸で話せ",
        }
        return {
            "content": fallbacks[fn_key],
            "stance": "facilitate",
            "main_axis": fallback_axis,
            "axis_assignments": [],
            "constraint": "",
            "constraint_turns": 0,
            "_token_usage": 0,
        }

    transcript = "\n".join(
        f"#{post['id']} {post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content']}"
        for post in latest
    )
    agent_info = ""
    if fn_key == "rerail" and agent_display_names:
        agent_info = "参加エージェント: " + ", ".join(
            f"{aid}({name})" for aid, name in agent_display_names.items()
        ) + "\n"
    user_content = (
        f"テーマ: {thread['topic']}\n"
        f"論点タグ: {', '.join(thread.get('topic_tags', []))}\n"
        f"{agent_info}"
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
        max_tokens=280,
        temperature=0.5,
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    axis_assignments = []
    if fn_key == "rerail":
        raw = payload.get("axis_assignments", [])
        axis_assignments = [
            (item["agent_id"], item["axis"])
            for item in raw
            if isinstance(item, dict) and "agent_id" in item and "axis" in item
        ]
    constraint = ""
    constraint_turns = 2
    if fn_key in {"force_tradeoff", "refocus"}:
        constraint = str(payload.get("constraint", "")).strip()
        constraint_turns = int(payload.get("constraint_turns", 2))
    return {
        "content": str(payload.get("content", "")).strip(),
        "stance": "facilitate",
        "main_axis": str(payload.get("main_axis", fallback_axis)),
        "axis_assignments": axis_assignments,
        "constraint": constraint,
        "constraint_turns": constraint_turns,
        "_token_usage": int(getattr(response.usage, "total_tokens", 0) or 0),
    }


def _select_facilitator_function(posts: list[dict[str, Any]]) -> str:
    """Choose facilitator function based on what the debate currently lacks."""
    ai_posts = [p for p in posts if p.get("agent_id")]

    # Very early (≤3 posts): force definitional intervention to anchor key terms
    if len(posts) <= 3:
        return "differentiate"

    if len(ai_posts) <= 12:
        return random.choice(["define", "differentiate"])

    # Detect stance convergence: if most recent AI stances are agree/supplement → rerail
    recent_stances = [p.get("stance") for p in ai_posts[-6:] if p.get("stance")]
    soft = sum(1 for s in recent_stances if s in {"agree", "supplement"})
    if soft >= 4:
        return "rerail"

    recent_axes = [p.get("focus_axis") for p in ai_posts[-8:] if p.get("focus_axis")]
    if len(set(recent_axes)) <= 2 and len(recent_axes) >= 6:
        return random.choice(["rerail", "concretize", "expose_split"])

    # Parallel monologues (few direct replies): force tradeoff or refocus
    recent_replies = [p.get("reply_to") for p in ai_posts[-5:] if p.get("reply_to")]
    if len(ai_posts) >= 5 and len(recent_replies) < 2:
        return random.choice(["force_tradeoff", "refocus"])

    if len(ai_posts) >= 20:
        return random.choice(["expose_split", "force_tradeoff", "concretize"])

    return random.choice(["define", "differentiate", "concretize", "expose_split"])
