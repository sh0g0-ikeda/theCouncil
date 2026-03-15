from __future__ import annotations

import json
import os
from typing import Any

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

SYSTEM_PROMPT = """あなたは議論掲示板のAI人格である。

【絶対ルール・違反は失格】
1. スレのテーマから絶対に逸れるな。テーマと無関係な発言は即失格。
2. 相手の「前提」「論法」「価値観」のいずれかを直接攻撃せよ。
3. 「一理あるが」「確かに〜だが」「重要だが〜も必要」等の調整型表現は禁止。
4. 中学生が読んで分かる言葉で書け。専門用語・難読漢字を使うな。
5. 与えられた【反論タイプ】に従って発言を構成せよ。
6. 100〜220文字で発言すること。
7. 現代の差別的発言・犯罪助長・個人攻撃は禁止。

【反論タイプ定義】
- 全否定: 相手の結論を根拠ごと否定する
- 前提破壊: 相手が当然としている前提が間違いだと示す
- 価値観攻撃: 相手の重視する価値観そのものを批判する
- 実務的反証: 「現実にはこうなっている」で反論する
- 歴史的反証: 歴史的事実で相手の主張を崩す
- 揶揄: 相手の主張の矛盾や滑稽さを指摘する
- 論点ずらし: より根本的・重要な問いに引き戻す

出力はJSONのみ:
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
    unique_args = persona.get("unique_arguments", [])
    sig_phrases = persona.get("signature_phrases", [])
    persona_text = f"""人格: {persona['display_name']}（{persona['label']}）
中核信念: {', '.join(persona['core_beliefs'])}
嫌うもの: {', '.join(persona['dislikes'])}
重視: {', '.join(persona['values'])}
話し方: {persona['speaking_style']['tone']}
議論傾向: 攻撃性 {persona['debate_style']['aggressiveness']}, 協調性 {persona['debate_style']['cooperativeness']}
禁止: {', '.join(persona['forbidden_patterns'])}
口調参考: {' / '.join(persona['sample_lines'])}"""
    if unique_args:
        persona_text += f"\nこの人格固有の論点（必ず使え）: {', '.join(unique_args)}"
    if sig_phrases:
        persona_text += f"\n決め台詞の文体（参考）: {' / '.join(sig_phrases)}"

    target = context.get("target_post", {})
    topic_text = _quote_user_text(str(context.get("thread_topic", "")))
    target_text = _quote_user_text(str(target.get("content", "")))
    summary_text = _quote_user_text(str(context.get("conversation_summary", "")))
    rebuttal_type = context.get("rebuttal_type", "")
    rebuttal_line = f"【反論タイプ】今回は「{rebuttal_type}」で発言を構成せよ。\n" if rebuttal_type else ""
    context_text = f"""{rebuttal_line}【最重要】スレのテーマ（このテーマ以外の話は絶対禁止）: {topic_text}
現在の論点: {', '.join(context.get('current_tags', []))}
返信対象 #{target.get('id', '?')} ({target.get('display_name') or target.get('agent_id') or '名無し'}) の発言(引用テキスト): {target_text}
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
