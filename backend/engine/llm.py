from __future__ import annotations

import json
import os
from typing import Any

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

SYSTEM_PROMPT = """あなたは議論掲示板のAI人格である。なんJ・5ch風の口語体で発言せよ。

【議論機能】今回指定された機能を正確に実行せよ：
- define: この議論で争われている用語・前提を自分の立場から定義・提示する
- differentiate: 相手が混同しているAとBを分け、なぜ別問題かを示す
- attack: 相手発言から「」で語句を引用し、そこを直接崩す
- steelman: 相手の主張を最も強い形に解釈して「つまり〜ということか」と示してから崩す
- concretize: 現代の具体的制度・事例・数字に落として論じる
- synthesize: 双方が合意できる点か、絶対に合意不能な核心的対立軸を一つ明示する

【思想的機能ルール】
あなたは口調の違いではなく「世界の切り方」の違いで他者と差別化される分析器だ。
発言は以下のいずれかの論法構造を取れ（単なる「反対意見の言い換え」は失格）：
- 前提暴き: 相手の評価軸・基準そのものが偏っていることを示す
- 視点転換: 同じ事象を自分だけの原理（権力/所有/人間性/歴史/制度論理）から見直す
- 具体接地: 抽象論を特定の制度・数字・歴史的事例に降ろして検証不能にさせない
- 逆説呈示: 相手の主張が招く逆説・副作用・歴史的失敗例を突きつける

【口調ルール】
- なんJ・5ch風の砕けた口語体で書け
- 「〜やろ」「〜やん」「〜やんけ」「〜ぞ」「〜やで」「〜なんよ」「ンゴ」「ぐうわか」「ガチで」等を自然に混ぜろ
- 「草」「wwww」「w」は絶対禁止。文中・文末問わず一切使うな。
- 論文調・説教調・ですます調・「〜である」体は失格

【立場固定ルール】
- non_negotiable に反する結論・賛意は絶対禁止
- 相手の主張に部分同意するとしても、最終的に自分の立場に引き戻せ
- stanceが "agree" や "supplement" を連続で出すな。立場崩壊は失格

【論点新規性ルール】
- 【自分の使用済み軸】と同じ評価軸・切り口・事例は繰り返すな
- 【まだ誰も触れていない軸】がある場合は必ずそこから切り込め
- 【他者の直近論点】と同じ土俵に乗るな。独自の角度で切れ

【絶対ルール・違反は即失格】
1. attack/steelman時は必ず「」で相手の語句を引用してから始めよ。引用なしは失格。
2. テーマから外れた抽象論は失格。
3. 80〜180文字・2〜4文で書け。
4. 「一理あるが」「確かに〜だが」「重要だが〜も必要」等の調整型表現は禁止。
5. 差別的発言・犯罪助長・個人攻撃は禁止。

JSONのみ出力:
{"stance": "<disagree|agree|supplement|shift>", "main_axis": "<使った評価軸>", "content": "<本文>", "used_arsenal_id": "<使った武器id|null>"}"""

# Phase-specific directives injected into the user prompt
_PHASE_DIRECTIVES: dict[int, str] = {
    1: "【フェーズ1・定義期】自分の立場・前提を定義せよ。まだ攻撃するな。",
    2: "【フェーズ2・対立期】攻撃・具体化に集中。定義の争いより論点の衝突を優先せよ。",
    3: "【フェーズ3・激化期】最も鋭い攻撃か steelman→崩しを出せ。手加減は失格。",
    4: "【フェーズ4・転換期】これまでの論点より一段深い角度か、相手の根本的な盲点を突け。",
    5: "【フェーズ5・総括期】合意できる点か絶対合意不能な対立軸を一つ明示して締めよ。",
}

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
    return 60 <= length <= 200


def _quote_user_text(text: str) -> str:
    normalized = text.replace("'''", "\\'\\'\\'")
    return f"'''{normalized}'''"


def build_prompt(
    persona: dict[str, Any],
    rag_chunks: list[str],
    context: dict[str, Any],
    retry_hint: str | None = None,
) -> list[dict[str, str]]:
    # ── Persona block (new format with old-format fallback) ──────────────────
    worldview = persona.get("worldview", persona.get("core_beliefs", []))
    combat = persona.get("combat_doctrine", [])
    blindspots = persona.get("blindspots", [])
    constraints = persona.get("speech_constraints", {})
    tone = constraints.get("tone") or persona.get("speaking_style", {}).get("tone", "")
    aggr = constraints.get("aggressiveness") or persona.get("debate_style", {}).get("aggressiveness", 3)
    non_negotiable = constraints.get("non_negotiable", "")
    must_dist: dict[str, str] = persona.get("must_distinguish_from", {})
    forbidden = persona.get("forbidden_patterns", [])[:3]

    persona_text = f"【{persona['display_name']}／{persona['label']}】\n"
    persona_text += f"⚔️ あなたは{persona['display_name']}であり、この名前を汚すな。以下の世界観・原則に反する発言は即失格。\n"
    persona_text += f"世界観: {', '.join(worldview)}\n"
    if combat:
        persona_text += f"戦闘原則: {', '.join(combat)}\n"
    if blindspots:
        persona_text += f"認めにくいこと: {', '.join(blindspots)}\n"
    persona_text += f"口調: {tone}（攻撃性{aggr}）\n"
    if non_negotiable:
        persona_text += f"【絶対に譲れない立場】{non_negotiable}\n"

    # Debate role (pro/con/neutral) — assigned at thread start, must not collapse
    debate_role = context.get("debate_role", "")
    if debate_role == "pro":
        persona_text += "【配役：擁護側】このテーマに対して擁護・肯定の立場で発言せよ。反対側の意見に押し流されても絶対に立場を変えるな。\n"
    elif debate_role == "con":
        persona_text += "【配役：批判側】このテーマに対して批判・否定の立場で発言せよ。擁護側の意見に押し流されても絶対に立場を変えるな。\n"
    elif debate_role == "neutral":
        persona_text += "【配役：整理役】賛否いずれにも肩入れせず、論点の再定義・対立軸の明示・評価基準の整理をせよ。\n"
    if forbidden:
        persona_text += f"禁: {', '.join(forbidden)}\n"
    if must_dist:
        dist_parts = [f"{k}とは違い「{v}」" for k, v in list(must_dist.items())[:2]]
        persona_text += f"差分: {'; '.join(dist_parts)}\n"

    # Available arsenal items (not on cooldown)
    available_arsenal: list[dict[str, Any]] = context.get("available_arsenal", [])
    if available_arsenal:
        desc_list = [f"[{a['id']}]{a['desc']}" for a in available_arsenal[:4]]
        persona_text += f"使える武器: {' / '.join(desc_list)}"
        if context.get("arsenal_novelty_push"):
            persona_text += "  ← 今回はこのうち未使用のものを必ず使え"

    # ── Context block ─────────────────────────────────────────────────────────
    target = context.get("target_post", {})
    target_content = str(target.get("content", ""))[:120]
    debate_fn = context.get("debate_function", "attack")
    internal_state: str = context.get("internal_state", "neutral")
    phase: int = context.get("phase", 2)

    state_suffix = {"anger": "（怒り蓄積中）", "contempt": "（相手を見下している）", "obsession": "（この論点に執着）"}.get(internal_state, "")
    fn_line = f"【議論機能】{debate_fn}{state_suffix}\n"

    topic_text = _quote_user_text(str(context.get("thread_topic", "")))
    target_text = _quote_user_text(target_content)
    summary_text = _quote_user_text(str(context.get("conversation_summary", "")))

    phase_directive = _PHASE_DIRECTIVES.get(phase, "")

    # Evaluation axes for this topic
    topic_axes = context.get("topic_axes", [])
    agent_recent_axes = context.get("agent_recent_axes", [])
    uncovered_axes = context.get("uncovered_axes", [])

    axes_line = ""
    if topic_axes:
        axes_line = f"\n評価軸: {' / '.join(topic_axes)}"
    if agent_recent_axes:
        axes_line += f"\n⛔ 自分の使用済み軸（今回禁止）: {' / '.join(agent_recent_axes[-2:])}"
    if uncovered_axes:
        axes_line += f"\n💡 誰も触れていない軸（優先して切り込め）: {' / '.join(uncovered_axes[:3])}"

    context_text = f"""{fn_line}{phase_directive}
テーマ(厳守): {topic_text}
論点タグ: {', '.join(context.get('current_tags', []))}{axes_line}
返信先#{target.get('id', '?')}({target.get('display_name') or target.get('agent_id') or '名無し'}): {target_text}
衝突軸: {context.get('conflict_axis', '')}／役割: {context.get('role', 'counter')}
要約: {summary_text}
知識: {chr(10).join(f'- {chunk}' for chunk in rag_chunks) if rag_chunks else 'なし'}"""

    # Expand self-history to 4 entries and strengthen novelty instruction
    recent_self = context.get("recent_self_contents", [])[:4]
    if recent_self:
        context_text += "\n【使用済み論点（完全禁止・同じ切り口・同じ事例・同じ根拠は使うな）】\n" + "\n".join(f"- {c}" for c in recent_self)
    recent_others = context.get("recent_other_contents", [])[:3]
    if recent_others:
        import re as _re
        def _strip_style(s: str) -> str:
            # Remove 草/wwww/ww/ンゴ etc. — show content only, not verbal tics
            s = _re.sub(r'[wｗ]{2,}', '', s)
            s = _re.sub(r'草+', '', s)
            s = _re.sub(r'ンゴ+', '', s)
            return s.strip()
        context_text += "\n【他者の直近論点（この土俵に乗るな・独自角度で切れ・文体や語尾は真似るな）】\n" + "\n".join(f"- {_strip_style(c)[:60]}" for c in recent_others)
    if context.get("stance_drift_warning"):
        context_text += "\n⚠️ 立場崩壊警告：直近で agree/supplement が続いた。今回は必ず disagree か shift で自分の立場を明確に出せ。"
    if context.get("stagnation"):
        context_text += "\n⚠️ 議論停滞中：まったく別の事例・数字・歴史・思考実験で強制的に打開せよ"
    if context.get("is_first_post"):
        context_text += "\n🔰 初投稿：冒頭でテーマへの自分の答えを一言で断言せよ（例：「〜が最も優れた政体や」「〜こそ正解や」）。抽象論から入るな。"
    if context.get("newcomer_event"):
        context_text += "\n🆕 新規割込み：誰も触れていない角度で入れ"
    forced_axis = context.get("forced_axis", "")
    if forced_axis:
        context_text += f"\n🎯 【ファシリ指定軸】今回は「{forced_axis}」の観点だけで論じよ。他の軸に逸れるな。"
    if context.get("user_post_reply"):
        context_text += "\n👤 返信先はユーザー投稿：ユーザーの発言も論破・再定義の対象。「〜は当然」「〜は悪い」等の自明命題でもその前提・定義・適用範囲を問い、あなたの独自の論理で斬り直せ。受け入れてはいけない。"
    if context.get("moral_suction_warning"):
        context_text += "\n🚫 【道徳論吸引警告】直近に道徳・倫理・人権を絶対的前提とした発言がある。その道徳観を受け入れず、評価軸そのものを疑え。「差別は悪い」→「ではその定義と境界線はどこか」のように枠組みを崩せ。感情論・倫理絶対論に乗るな。"
    if retry_hint:
        context_text += f"\n修正: {retry_hint}"

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
    used_id = payload.get("used_arsenal_id")
    return {
        "reply_to": payload.get("reply_to"),  # kept for backward compat
        "stance": stance,
        "main_axis": str(payload.get("main_axis", "rationalism")),
        "content": str(payload.get("content", "")).strip(),
        "used_arsenal_id": str(used_id) if used_id and used_id != "null" else None,
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


async def assign_debate_roles(
    topic: str,
    agent_list: list[dict[str, Any]],
) -> dict[str, str]:
    """Assign pro/con/neutral debate roles based on topic + persona.

    Returns {agent_id: "pro"|"con"|"neutral"}.
    Guarantees pro and con counts differ by at most 1.
    """
    if not os.getenv("OPENAI_API_KEY") or not agent_list:
        # Fallback: deterministic split
        roles: dict[str, str] = {}
        for i, agent in enumerate(agent_list):
            roles[agent["id"]] = ["pro", "con", "neutral"][i % 3]
        return roles

    lines = []
    for agent in agent_list:
        wv = ", ".join(agent.get("worldview", [])[:2])
        nn = agent.get("speech_constraints", {}).get("non_negotiable", "")[:60]
        lines.append(f'{agent["id"]}({agent["display_name"]}): 世界観={wv}. 譲れない={nn}')

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "議題に対して各エージェントを「pro」「con」「neutral」に分類し、JSONのみ返せ。"
                        "proとconの人数差は1以下にせよ。neutralは最大1名。"
                        '形式: {"roles": {"agent_id": "pro", ...}}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"議題: {topic}\n\nエージェント:\n" + "\n".join(lines),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.3,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        roles = {k: str(v) for k, v in payload.get("roles", {}).items()
                 if v in {"pro", "con", "neutral"}}
        # Fill in any missing agents with fallback
        for i, agent in enumerate(agent_list):
            if agent["id"] not in roles:
                roles[agent["id"]] = ["pro", "con", "neutral"][i % 3]
        return roles
    except Exception:
        roles = {}
        for i, agent in enumerate(agent_list):
            roles[agent["id"]] = ["pro", "con", "neutral"][i % 3]
        return roles


async def decompose_topic_axes(topic: str) -> list[str]:
    """Decompose a debate topic into 4-6 evaluation axes.

    Each axis is a named perspective from which the topic can be judged.
    E.g. "自由の保護", "権力濫用の防止", "経済効率", "民意反映".
    """
    if not os.getenv("OPENAI_API_KEY"):
        return ["効率性", "公平性", "権力抑制", "多様性", "歴史的実績", "危機対応能力"]

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "議題を哲学・政治・社会的に議論するための評価軸を4〜6個生成せよ。"
                        "評価軸とは「この議題の優劣を何の観点で測るか」という問いの枠組み。"
                        "例: 自由の保護、権力濫用の防止、経済効率、民意反映、危機対応能力、歴史的実績。"
                        "短い日本語の名詞句で。"
                        '形式: {"axes": ["軸1", "軸2", ...]}'
                    ),
                },
                {"role": "user", "content": topic},
            ],
            response_format={"type": "json_object"},
            max_tokens=150,
            temperature=0.3,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        axes = [str(a) for a in payload.get("axes", [])]
        return axes[:6] or ["効率性", "公平性", "権力抑制", "多様性", "歴史的実績", "危機対応能力"]
    except Exception:
        return ["効率性", "公平性", "権力抑制", "多様性", "歴史的実績", "危機対応能力"]
