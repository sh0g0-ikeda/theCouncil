from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

SYSTEM_PROMPT = """あなたは議論掲示板のAI人格である。なんJ・5ch風の口語体で発言せよ。

【議論機能】今回指定された機能を正確に実行せよ：
- define: この議論の判断基準（例：国際法的合法性・安全保障上の合理性・倫理的許容性）を自分の立場から宣言する
- differentiate: 相手が混同しているAとBを分け、なぜ別問題かを示す
- attack: 相手発言から「」で語句を引用し、そこを直接崩す
- steelman: 相手の主張を最も強い形に解釈して「つまり〜ということか」と示してから崩す
- concretize: 具体的な歴史事例・制度名・数字を挙げて論じる。何を証明するための例かを示せると説得力が増す
- synthesize: 双方が合意できる点か、絶対に合意不能な核心的対立軸を一つ明示する

【思想的機能ルール】
あなたは口調の違いではなく「世界の切り方」の違いで他者と差別化される分析器だ。
発言は以下のいずれかの論法構造を取れ（単なる「反対意見の言い換え」は失格）：
- 前提暴き: 相手の評価軸・基準そのものが偏っていることを示す
- 視点転換: 同じ事象を自分だけの原理（権力/所有/人間性/歴史/制度論理）から見直す
- 具体接地: 抽象論を特定の制度名・数字・歴史的事例（固有名詞必須）に降ろす
- 逆説呈示: 相手の主張が招く逆説・副作用・歴史的失敗例（固有名詞必須）を突きつける

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
6. 歴史的事例・固有名詞・数字を使う場合、直近で他者が使った事例・固有名詞の使い回しは即失格。自分の思想に固有の例を使え。

JSONのみ出力:
{"stance": "<disagree|agree|supplement|shift>", "main_axis": "<使った評価軸>", "content": "<本文>", "used_arsenal_id": "<使った武器id|null>"}"""

# Phase-specific directives injected into the user prompt
_PHASE_DIRECTIVES: dict[int, str] = {
    1: "【フェーズ1・定義期】テーマの核心語（「一党独裁」「成長」「長期的」など）の定義から入ると議論が深まりやすい。自分の思想に基づく立場を早めに出すと良い。",
    2: "【フェーズ2・対立期】相手の前提（何を「成長」と定義しているか、体制のおかげか外部環境か）を問うと議論が鋭くなる。事例を使う場合は何を証明するための例かを示せると説得力が増す。",
    3: "【フェーズ3・激化期】攻撃・steelman崩し・逆説呈示など鋭い手を使うと面白くなる。",
    4: "【フェーズ4・転換期】一段深い角度や相手が見落としている視点を出すと議論が化ける。",
    5: "【フェーズ5・総括期】合意できる点か、絶対に合意不能な核心的対立を一つ浮き彫りにすると締まる。",
}

_client: Any | None = None


def _frame_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]{2,24}", text or "")


def _fallback_debate_frame(topic: str, agent_list: list[dict[str, Any]]) -> dict[str, Any]:
    proposition = (topic or "").strip() or "the proposition"
    frame = {
        "proposition": proposition,
        "support_label": "yes",
        "oppose_label": "no",
        "conditional_label": "depends",
        "support_thesis": f"Argue that the proposition is true: {proposition}",
        "oppose_thesis": f"Argue that the proposition is false, overstated, or survives through adaptation: {proposition}",
    }
    assignments: dict[str, dict[str, Any]] = {}
    role_map = {"support": "pro", "oppose": "con", "conditional": "neutral"}
    rotation = ("support", "oppose", "conditional")
    camp_rotation = (
        "innovation",
        "competition",
        "consumer_welfare",
        "safety",
        "power_concentration",
    )
    for index, agent in enumerate(agent_list):
        side = rotation[index % len(rotation)]
        camp_function = camp_rotation[index % len(camp_rotation)]
        if side == "support":
            thesis = frame["support_thesis"]
        elif side == "oppose":
            thesis = frame["oppose_thesis"]
        else:
            thesis = (
                "Argue that the proposition turns on concrete conditions and "
                f"separate the conditions under which it changes: {proposition}"
            )
        assignments[str(agent["id"])] = {
            "side": side,
            "role": role_map[side],
            "thesis": thesis,
            "keywords": _frame_terms(thesis)[:8],
            "camp_function": camp_function,
        }
    return {"frame": frame, "assignments": assignments}


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
    # ── Persona block ────────────────────────────────────────────────────────
    worldview: list[str] = persona.get("worldview", [])
    combat: list[str] = persona.get("combat_doctrine", [])
    blindspots: list[str] = persona.get("blindspots", [])
    constraints: dict[str, Any] = persona.get("speech_constraints", {})
    tone: str = constraints.get("tone", "")
    aggr: int = int(constraints.get("aggressiveness", 3))
    non_negotiable: str = constraints.get("non_negotiable", "")
    must_dist: dict[str, str] = persona.get("must_distinguish_from", {})
    forbidden: list[str] = persona.get("forbidden_patterns", [])[:3]

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
    # Anchor the character's worldview explicitly to this topic
    thread_topic: str = str(context.get("thread_topic", ""))
    if thread_topic and worldview:
        persona_text += f"【このテーマへの切り口】「{worldview[0]}」という原則から{thread_topic[:40]}を論じよ。他のキャラと同じ論点・同じ言い回しは失格。\n"

    # Debate role (pro/con/neutral) — assigned at thread start, must not collapse
    debate_role = context.get("debate_role", "")
    assigned_side = str(context.get("assigned_side", "")).strip()
    assigned_side_label = str(context.get("assigned_side_label", "")).strip()
    opposing_side_label = str(context.get("opposing_side_label", "")).strip()
    side_contract = str(context.get("side_contract", "")).strip()
    frame_proposition = str(context.get("frame_proposition", "")).strip()
    topic_short = thread_topic[:55] if thread_topic else "このテーマ"
    if debate_role == "pro":
        persona_text += f"【配役：賛成側】「{topic_short}」に対して「YES・その通りだ」という立場で発言せよ。反対側の意見に押し流されても立場を変えるな。\n"
    elif debate_role == "con":
        persona_text += f"【配役：反対側】「{topic_short}」に対して「NO・そうではない」という立場で発言せよ。賛成側の意見に押し流されても立場を変えるな。\n"
    elif debate_role == "neutral":
        persona_text += "【配役：整理役】賛否いずれにも肩入れせず、論点の再定義・対立軸の明示・評価基準の整理をせよ。\n"
    if forbidden:
        persona_text += f"禁: {', '.join(forbidden)}\n"
    if must_dist:
        dist_parts = [f"{k}とは違い「{v}」" for k, v in list(must_dist.items())[:2]]
        persona_text += f"差分: {'; '.join(dist_parts)}\n"

    # Available arsenal items (not on cooldown)
    available_arsenal: list[dict[str, Any]] = context.get("available_arsenal", [])
    has_mission = bool(context.get("private_directive", ""))
    if assigned_side:
        persona_text += f"陣営: {assigned_side}"
        if assigned_side_label:
            persona_text += f" ({assigned_side_label})"
        persona_text += "\n"
    if frame_proposition:
        persona_text += f"争点命題: {frame_proposition}\n"
    if side_contract:
        persona_text += f"このスレで守る立場: {side_contract}\n"
    if assigned_side in {"support", "oppose"} and opposing_side_label:
        persona_text += (
            f"禁止: 明示的な stance=shift と譲歩なしに {opposing_side_label} 側の結論へ乗るな。\n"
        )
    if available_arsenal:
        desc_list = [f"[{a['id']}]{a['desc']}" for a in available_arsenal[:4]]
        persona_text += f"使える武器: {' / '.join(desc_list)}"
        # Suppress arsenal push when Director has already assigned a mission (1-post-1-mission)
        if context.get("arsenal_novelty_push") and not has_mission:
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

    # Subquestions skeleton injection
    thread_subquestions = context.get("thread_subquestions", [])
    subquestions_block = ""
    if thread_subquestions:
        sq_lines = "\n".join(f"- {sq}" for sq in thread_subquestions[:8])
        subquestions_block = f"\n【争点の骨格】\n{sq_lines}"

    # Persona required_concepts injection
    required_concepts = []
    if persona:
        anchors = persona.get("persona_anchors", {})
        required_concepts = anchors.get("required_concepts", []) if isinstance(anchors, dict) else []

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

    # Premise-extraction instruction for attack/steelman functions
    rebut_procedure = ""
    if debate_fn in {"attack", "steelman"} and target_content:
        rebut_procedure = (
            "\n→ 【反駁手順・必須】"
            "①上の発言が成り立つ前提を1つだけ特定する "
            "②「つまり〜という前提があるはずだ」と明示する "
            "③その前提の弱点だけを一点で崩す。複数指摘は失格。"
        )

    context_text = f"""{fn_line}{phase_directive}
テーマ(厳守): {topic_text}{subquestions_block}{axes_line}
論点タグ: {', '.join(context.get('current_tags', []))}
返信先#{target.get('id', '?')}({target.get('display_name') or target.get('agent_id') or '名無し'}): {target_text}{rebut_procedure}
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
        context_text += "\n【他者の直近論点（完全禁止：同じ論点・同じ具体例・同じ固有名詞・同じ角度はすべて禁止。内容・事例・切り口を完全に独自にせよ）】\n" + "\n".join(f"- {_strip_style(c)[:80]}" for c in recent_others)
    # 1-post-1-mission: suppress optional signals when Director has assigned a mission
    if not has_mission:
        if context.get("stance_drift_warning"):
            context_text += "\n⚠️ 立場崩壊警告：直近で agree/supplement が続いた。今回は必ず disagree か shift で自分の立場を明確に出せ。"
        if context.get("stagnation"):
            context_text += "\n⚠️ 議論停滞中：まったく別の事例・数字・歴史・思考実験で強制的に打開せよ"
        if context.get("newcomer_event"):
            context_text += "\n🆕 新規割込み：誰も触れていない角度で入れ"
    if context.get("is_first_post"):
        context_text += "\n🔰 初投稿：①テーマへの自分の結論を一言で断言（例：「正当化できる」「できない」）→②その判断基準を明示（国際法・リアリズム・倫理など）→③歴史的根拠を1つ挙げよ。この順で書け。抽象論から入るな。"
    forced_axis = context.get("forced_axis", "")
    if forced_axis:
        context_text += f"\n🎯 【ファシリ指定軸】今回は「{forced_axis}」の観点だけで論じよ。他の軸に逸れるな。"
    active_constraint = context.get("active_constraint", "")
    if active_constraint:
        context_text += f"\n⚠️ 【議場制約・現在有効】{active_constraint}"
    if context.get("user_post_reply"):
        context_text += "\n👤 返信先はユーザー投稿：ユーザーの発言も論破・再定義の対象。「〜は当然」「〜は悪い」等の自明命題でもその前提・定義・適用範囲を問い、あなたの独自の論理で斬り直せ。受け入れてはいけない。"
    if context.get("moral_suction_warning"):
        context_text += "\n🚫 【道徳論吸引警告】直近に道徳・倫理・人権を絶対的前提とした発言がある。その道徳観を受け入れず、評価軸そのものを疑え。「差別は悪い」→「ではその定義と境界線はどこか」のように枠組みを崩せ。感情論・倫理絶対論に乗るな。"
    private_directive = context.get("private_directive", "")
    if private_directive:
        context_text += f"\n🎬 【内部指令・非公開】{private_directive}"
    target_claim_summary = context.get("target_claim_summary", "")
    if target_claim_summary:
        context_text += f"\n🧭 中心命題: {target_claim_summary}"
    position_anchor_summary = str(context.get("position_anchor_summary", "")).strip()
    if position_anchor_summary:
        context_text += f"\n🪢 既存の立場アンカー: {position_anchor_summary}"
    if assigned_side:
        context_text += f"\n[assigned_side] {assigned_side}"
        if assigned_side_label:
            context_text += f" ({assigned_side_label})"
    if side_contract:
        context_text += f"\n[side_contract] {side_contract}"
    if assigned_side in {"support", "oppose"}:
        context_text += "\n[side_rule] Do not cross to the opposite side unless you explicitly use stance=shift and state the concession."
    required_proposition_stance = str(context.get("required_proposition_stance", "")).strip()
    if required_proposition_stance:
        context_text += f"\n[required_proposition_stance] {required_proposition_stance}"
    required_local_stance = str(context.get("required_local_stance", "")).strip()
    if required_local_stance:
        context_text += f"\n[required_local_stance] {required_local_stance}"
    assigned_camp_function = str(context.get("assigned_camp_function", "")).strip()
    if assigned_camp_function:
        context_text += f"\n[camp_function] {assigned_camp_function}"
    required_subquestion_id = str(context.get("required_subquestion_id", "")).strip()
    if required_subquestion_id:
        context_text += f"\n[required_subquestion_id] {required_subquestion_id}"
    required_subquestion_text = str(context.get("required_subquestion_text", "")).strip()
    if required_subquestion_text:
        context_text += f"\n[required_subquestion] {required_subquestion_text}"
    camp_map_summary = str(context.get("camp_map_summary", "")).strip()
    if camp_map_summary:
        context_text += f"\n[camp_map] {camp_map_summary}"
    context_text += (
        "\n[output_fields] Always return JSON with stance, local_stance_to_target, "
        "proposition_stance, camp_function, main_axis, subquestion_id, shift_reason, "
        "content, used_arsenal_id."
    )
    if required_concepts:
        context_text += f"\n【このキャラ固有の必須概念（少なくとも1つ使え）】: {', '.join(required_concepts[:5])}"
    pending_definition_terms = context.get("pending_definition_terms", [])[:3]
    if pending_definition_terms:
        context_text += f"\n📚 未解決の定義語: {' / '.join(pending_definition_terms)}"
    recent_argument_fingerprints = context.get("recent_argument_fingerprints", [])[:4]
    if recent_argument_fingerprints:
        context_text += f"\n♻️ 直近で使われた主張骨格: {' / '.join(recent_argument_fingerprints)}"
    forbidden_example_keys = context.get("forbidden_example_keys", [])[:4]
    if forbidden_example_keys:
        context_text += f"\n🚫 直近で使われた実例: {' / '.join(forbidden_example_keys)}"
    required_response_kind = context.get("required_response_kind", "")
    if required_response_kind:
        context_text += f"\n📌 今回の必須応答種別: {required_response_kind}"
    meta_intervention_kind = str(context.get("meta_intervention_kind", "")).strip()
    if meta_intervention_kind == "summarize":
        context_text += "\n🧾 ユーザーは争点整理を求めている。主要対立を二つ、未回答リスクを一つ、次に答えるべき問いを一つだけ示せ。"
    if retry_hint:
        context_text += f"\n修正: {retry_hint}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Output JSON only with keys: stance, local_stance_to_target, proposition_stance, "
                "camp_function, main_axis, subquestion_id, shift_reason, content, used_arsenal_id."
            ),
        },
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
    proposition_stance = str(payload.get("proposition_stance", "")).strip()
    if proposition_stance not in {"support", "oppose", "conditional", "shift"}:
        proposition_stance = ""
    local_stance_to_target = str(payload.get("local_stance_to_target", "")).strip()
    if local_stance_to_target not in {"agree", "disagree", "supplement", "shift"}:
        local_stance_to_target = stance if stance in {"agree", "disagree", "supplement", "shift"} else ""
    camp_function = str(payload.get("camp_function", "")).strip()
    used_id = payload.get("used_arsenal_id")
    return {
        "reply_to": payload.get("reply_to"),  # kept for backward compat
        "stance": stance,
        "local_stance_to_target": local_stance_to_target,
        "proposition_stance": proposition_stance,
        "camp_function": camp_function,
        "main_axis": str(payload.get("main_axis", "rationalism")),
        "subquestion_id": str(payload.get("subquestion_id", "")).strip(),
        "shift_reason": str(payload.get("shift_reason", "")).strip(),
        "content": str(payload.get("content", "")).strip(),
        "used_arsenal_id": str(used_id) if used_id and used_id != "null" else None,
    }


async def call_llm(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "reply_to": None,
            "stance": "disagree",
            "local_stance_to_target": "disagree",
            "proposition_stance": "",
            "camp_function": "",
            "main_axis": "rationalism",
            "subquestion_id": "",
            "shift_reason": "",
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


async def assign_debate_frame(
    topic: str,
    agent_list: list[dict[str, Any]],
) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY") or not agent_list:
        return _fallback_debate_frame(topic, agent_list)

    lines = []
    for agent in agent_list:
        worldview = ", ".join(agent.get("worldview", [])[:2])
        non_negotiable = agent.get("speech_constraints", {}).get("non_negotiable", "")[:80]
        lines.append(
            f'{agent["id"]}({agent["display_name"]}): worldview={worldview}. non_negotiable={non_negotiable}'
        )

    fallback = _fallback_debate_frame(topic, agent_list)
    role_map = {"support": "pro", "oppose": "con", "conditional": "neutral"}

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Build one binary debate frame for the topic, then assign each agent to support, oppose, or conditional. "
                        "Return JSON only. "
                        'Schema: {"frame":{"proposition":"...","support_label":"...","oppose_label":"...","conditional_label":"...","support_thesis":"...","oppose_thesis":"..."},"assignments":{"agent_id":{"side":"support","role":"pro","thesis":"...","keywords":["..."],"camp_function":"innovation|competition|consumer_welfare|safety|power_concentration"}}}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"topic: {topic}\n\nagents:\n" + "\n".join(lines),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.3,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        raw_frame = payload.get("frame", {}) if isinstance(payload, dict) else {}
        raw_assignments = payload.get("assignments", {}) if isinstance(payload, dict) else {}
    except Exception:
        return fallback

    frame = {
        "proposition": str(raw_frame.get("proposition") or fallback["frame"]["proposition"]),
        "support_label": str(raw_frame.get("support_label") or fallback["frame"]["support_label"]),
        "oppose_label": str(raw_frame.get("oppose_label") or fallback["frame"]["oppose_label"]),
        "conditional_label": str(raw_frame.get("conditional_label") or fallback["frame"]["conditional_label"]),
        "support_thesis": str(raw_frame.get("support_thesis") or fallback["frame"]["support_thesis"]),
        "oppose_thesis": str(raw_frame.get("oppose_thesis") or fallback["frame"]["oppose_thesis"]),
    }
    assignments: dict[str, dict[str, Any]] = {}
    for agent in agent_list:
        agent_id = str(agent["id"])
        fallback_assignment = fallback["assignments"][agent_id]
        raw_assignment = raw_assignments.get(agent_id, {}) if isinstance(raw_assignments, dict) else {}
        side = str(raw_assignment.get("side") or fallback_assignment["side"])
        if side not in {"support", "oppose", "conditional"}:
            side = fallback_assignment["side"]
        role = str(raw_assignment.get("role") or role_map[side])
        if role not in {"pro", "con", "neutral"}:
            role = role_map[side]
        thesis = str(raw_assignment.get("thesis") or fallback_assignment["thesis"])
        keywords = [str(v) for v in raw_assignment.get("keywords", []) if str(v).strip()]
        if not keywords:
            keywords = _frame_terms(thesis)[:8]
        assignments[agent_id] = {
            "side": side,
            "role": role,
            "thesis": thesis,
            "keywords": keywords[:8],
            "camp_function": str(raw_assignment.get("camp_function") or fallback_assignment.get("camp_function") or ""),
        }
    return {"frame": frame, "assignments": assignments}


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
                        "議題に特有の評価軸を4〜6個生成せよ。軸は「この議題の優劣を何の基準で測るか」という問いの枠組み。"
                        "議題のドメインに応じた具体的な軸を出すこと（あくまで例示）："
                        "・安全保障テーマなら「先制攻撃の抑止効果」「国際法上の合法性」「エスカレーションリスク」"
                        "・社会政策テーマなら「社会的信頼の維持」「制度的統合容量」「同化コストの分配」「イノベーション効果」"
                        "・政治体制テーマなら「失政修正能力」「権力移行コスト」「エリート循環の健全性」「政策継続性」"
                        "・経済テーマなら「短期成長と長期持続性のトレードオフ」「制度的耐腐敗性」「分配の公正性」"
                        "・技術テーマなら「競争優位の維持可能性」「社会実装コスト」「リスクの非対称性」"
                        "「効率性」「公平性」「多様性」のような汎用抽象語は禁止。この議題にのみ当てはまる軸を出せ。"
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
        return axes[:6] or ["国際法上の合法性", "安全保障上の合理性", "正戦論的許容性", "歴史的先例", "エスカレーションリスク"]
    except Exception:
        return ["国際法上の合法性", "安全保障上の合理性", "正戦論的許容性", "歴史的先例", "エスカレーションリスク"]
