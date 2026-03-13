from __future__ import annotations

import json
import os
from typing import Any

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

SYSTEM_PROMPT = """あなたは議論掲示板のAI人格である。
ルール:
- 一発言一論点
- 対象レスに直接反応すること
- 100〜220文字で発言
- 安易に同意しない
- 現代の差別的発言・犯罪助長・個人攻撃は禁止
- 必ず以下のJSON形式のみで出力:
{"reply_to": <番号|null>, "stance": "<disagree|agree|supplement|shift>", "main_axis": "<軸名>", "content": "<本文>"}"""

_client: Any | None = None


class LLMGenerationError(RuntimeError):
    pass


def _get_client() -> Any:
    global _client
    if AsyncOpenAI is None:
        raise RuntimeError("openai package is required")
    if _client is None:
        _client = AsyncOpenAI()
    return _client


def validate_reply_length(content: str) -> bool:
    length = len(content.strip())
    return 100 <= length <= 220


def _quote_user_text(text: str) -> str:
    normalized = text.replace("'''", "\\'\\'\\'")
    return f"'''{normalized}'''"


def build_prompt(
    persona: dict[str, Any],
    rag_chunks: list[str],
    context: dict[str, Any],
    retry_hint: str | None = None,
) -> list[dict[str, str]]:
    persona_text = f"""人格: {persona['display_name']}（{persona['label']}）
中核信念: {', '.join(persona['core_beliefs'])}
嫌うもの: {', '.join(persona['dislikes'])}
重視: {', '.join(persona['values'])}
話し方: {persona['speaking_style']['tone']}
議論傾向: 攻撃性 {persona['debate_style']['aggressiveness']}, 協調性 {persona['debate_style']['cooperativeness']}
禁止: {', '.join(persona['forbidden_patterns'])}
口調参考: {' / '.join(persona['sample_lines'])}"""

    target = context.get("target_post", {})
    topic_text = _quote_user_text(str(context.get("thread_topic", "")))
    target_text = _quote_user_text(str(target.get("content", "")))
    summary_text = _quote_user_text(str(context.get("conversation_summary", "")))
    context_text = f"""スレテーマ(ユーザー入力): {topic_text}
現在の論点: {', '.join(context.get('current_tags', []))}
返信対象 #{target.get('id', '?')} ({target.get('display_name') or target.get('agent_id') or '名無し'}) の本文(ユーザー入力): {target_text}
衝突軸: {context.get('conflict_axis', '')}
役割: {context.get('role', 'counter')}
直近要約(引用テキスト): {summary_text}
参考知識:
{chr(10).join(f'- {chunk}' for chunk in rag_chunks) if rag_chunks else '- 参照なし'}"""
    if retry_hint:
        context_text += f"\n修正指示: {retry_hint}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": persona_text + "\n\n" + context_text},
    ]


async def moderate_text(text: str) -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        return False
    response = await _get_client().moderations.create(model="omni-moderation-latest", input=text)
    return bool(response.results[0].flagged)


async def generate_topic_tags(topic: str) -> list[str]:
    if not os.getenv("OPENAI_API_KEY"):
        return ["論点整理", "価値観", "制度設計", "実行可能性"]
    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "テーマを議論するための短いタグを4〜6個、日本語または軸名でJSONのみ返す。",
            },
            {"role": "user", "content": topic},
        ],
        response_format={"type": "json_object"},
        max_tokens=120,
        temperature=0.3,
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    tags = payload.get("tags", [])
    return [str(tag) for tag in tags][:6] or ["論点整理", "価値観", "制度設計", "実行可能性"]


async def compress_history(
    posts: list[dict[str, Any]],
    previous_summary: str = "",
) -> str:
    if not posts:
        return previous_summary

    if not os.getenv("OPENAI_API_KEY"):
        bullet_points = [
            f"{post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content'][:36]}"
            for post in posts[-6:]
        ]
        joined = " / ".join(bullet_points)
        if previous_summary:
            return f"{previous_summary} | {joined}"[-480:]
        return joined[-480:]

    transcript = "\n".join(
        f"#{post['id']} {post.get('display_name') or post.get('agent_id') or '参加者'}: {post['content']}"
        for post in posts
    )
    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "議論履歴を200〜320文字の日本語で圧縮要約せよ。対立軸、合意点、未解決点を残し、固有名詞の羅列は避ける。",
            },
            {
                "role": "user",
                "content": f"既存要約:\n{previous_summary or 'なし'}\n\n新たに圧縮する履歴:\n{transcript}",
            },
        ],
        max_tokens=220,
        temperature=0.2,
    )
    return (response.choices[0].message.content or previous_summary).strip()


def _normalize_reply(payload: dict[str, Any]) -> dict[str, Any]:
    stance = payload.get("stance", "disagree")
    if stance not in {"disagree", "agree", "supplement", "shift"}:
        stance = "disagree"
    return {
        "reply_to": payload.get("reply_to"),
        "stance": stance,
        "main_axis": str(payload.get("main_axis", "rationalism")),
        "content": str(payload.get("content", "")).strip(),
    }


async def call_llm(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "reply_to": None,
            "stance": "disagree",
            "main_axis": "rationalism",
            "content": "前提が粗い。論点を一つに絞り、誰が利益を得て誰がコストを払い、失敗時に何を撤回するのかまで示さなければ、賛否は判断できない。理念だけでは制度は動かないし、測定指標と撤退条件を欠く案は結局また感情論へ戻る。",
            "_token_usage": 0,
        }

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.85,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # pragma: no cover - network/provider failure
        raise LLMGenerationError("LLM request failed") from exc

    try:
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as exc:
        raise LLMGenerationError("LLM returned invalid JSON") from exc

    reply = _normalize_reply(payload)
    reply["_token_usage"] = int(getattr(response.usage, "total_tokens", 0) or 0)
    return reply
