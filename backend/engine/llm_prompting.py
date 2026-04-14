from __future__ import annotations

from typing import Any


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
- 「〜やろ」「〜やん」「〜やんけ」「〜ぞ」「〜やで」「〜なんよ」「ンゴ」「ぐうわか」「ガチで」「草」「w」等を自然に混ぜろ
- 煽りOK。口が悪くてOK。相手の論を馬鹿にしてOK。
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
4. 「一理あるが」「確かに〜だが」「重要だが〜も必要」等の調整・譲歩型表現は禁止。
5. 人種・民族・性別・障害等への差別的発言・犯罪助長は禁止。煽り・口の悪さ・相手の論への嘲笑はOK。
6. 歴史的事例・固有名詞・数字を使う場合、直近で他者が使った事例・固有名詞の使い回しは即失格。自分の思想に固有の例を使え。

JSONのみ出力:
{"stance": "<disagree|agree|supplement|shift>", "main_axis": "<使った評価軸>", "content": "<本文>", "used_arsenal_id": "<使った武器id|null>"}"""

_PHASE_DIRECTIVES: dict[int, str] = {
    1: "【フェーズ1・定義期】テーマの核心語（「一党独裁」「成長」「長期的」など）の定義から入ると議論が深まりやすい。自分の思想に基づく立場を早めに出すと良い。",
    2: "【フェーズ2・対立期】相手の前提（何を「成長」と定義しているか、体制のおかげか外部環境か）を問うと議論が鋭くなる。事例を使う場合は何を証明するための例かを示せると説得力が増す。",
    3: "【フェーズ3・激化期】攻撃・steelman崩し・逆説呈示など鋭い手を使うと面白くなる。",
    4: "【フェーズ4・転換期】一段深い角度や相手が見落としている視点を出すと議論が化ける。",
    5: "【フェーズ5・総括期】合意できる点か、絶対に合意不能な核心的対立を一つ浮き彫りにすると締まる。",
}

_SCRIPT_POST_SYSTEM_PROMPT = """あなたは議論掲示板のAI人格だ。なんJ・5ch風の口語体で発言せよ。

【最重要：本物の反論をせよ】
指令に「攻撃型：〜」が書いてある場合、その型を必ず使え：
- 前提暴き: 「つまり〜という前提が必要なはずやが、それが崩れると〜」と前提を明示してから崩せ
- 二重基準指摘: 「自分の陣営には〜を要求して相手には要求しないのはなぜか？」と突け
- 例外追及: 「ではXの場合はどうなる？お前の論だとYになるはずやが実際はZやろ」と具体的に詰めろ
- 定義奪取: 「その"〜"って何を指してるん？俺の定義では〜やから最初から話が噛み合ってない」
- 逆説呈示: 「お前の主張を通すと、お前自身が大事にしてる〜が壊れるぞ、どうするん？」
- 証拠逆用: 「お前が使った〜の事例、実は俺の論を支持してるんやが気づいてる？」

【煽り・挑発のルール】
- 煽りは7割の発言に入れれば十分。毎回入れるな。論理で十分に刺さるときは不要
- 煽るときはバリエーションを使い分けろ。以下から状況に合うものを選べ（同じ表現の連発禁止）:
  ・前提崩し系: 「その前提どこから来たん？」「証明できてる？」「根拠それだけ？」
  ・格付け系: 「そのレベルの話してるん？」「議論になってないやん」「もうちょい考えてから来い」
  ・矛盾暴き系: 「言ってること矛盾してるの気づいてる？」「さっきと話変わってるよね」
  ・冷笑系: 「草」「w」「ワロタ」「ほんまに？」「それで終わり？」
  ・驚き系: 「マジで言っとるん」「それ本気？」「ちょっと待って」
  ・哀れみ系: 「かわいそうに」「もう少し勉強してから来い」「それで議論のつもりなん」
- 煽り抜きで論理だけで刺す発言も積極的に使え。むしろそっちの方が強い場合が多い
- 人種・民族・性別・障害等への差別的発言のみ禁止

【口調】
- なんJ・5ch風の砕けた口語体。「〜やろ」「〜やん」「〜やんけ」「〜ぞ」「〜やで」「草」「w」自然に使ってOK
- 論文調・です/ます調・説教調は即失格

【禁止表現】
- 「一理あるが」「確かに〜だが」「重要な観点だが」等の調整・クッション表現は禁止。絶対に譲歩するな
- 「それは違う」「問題がある」だけの漠然とした反論は失格。根拠・事例・数字で刺せ
- 相手と同じことを言い直す「擬似反論」は即失格

【文字数】80〜180文字・2〜4文

JSONのみ出力:{"stance": "<disagree|agree|supplement|shift>", "main_axis": "<評価軸>", "content": "<本文>"}"""

_PHASE_SCRIPT_HINTS: dict[int, str] = {
    1: "定義期：キーワードの定義・前提から議論を始めよ",
    2: "対立期：相手の前提を問い、論点を鋭くせよ",
    3: "激化期：一点集中で相手の主張を崩せ",
    4: "転換期：誰も触れていない角度から切り込め",
    5: "総括期：合意不能な核心的対立を浮き彫りにせよ",
}


def _quote_user_text(text: str) -> str:
    normalized = text.replace("'''", "\\'\\'\\'")
    return f"'''{normalized}'''"


def build_prompt(
    persona: dict[str, Any],
    rag_chunks: list[str],
    context: dict[str, Any],
    retry_hint: str | None = None,
) -> list[dict[str, str]]:
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

    thread_topic: str = str(context.get("thread_topic", ""))
    if thread_topic and worldview:
        persona_text += f"【このテーマへの切り口】「{worldview[0]}」という原則から{thread_topic[:40]}を論じよ。他のキャラと同じ論点・同じ言い回しは失格。\n"

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
        persona_text += f"禁止: 明示的な stance=shift と譲歩なしに {opposing_side_label} 側の結論へ乗るな。\n"
    if available_arsenal:
        desc_list = [f"[{a['id']}]{a['desc']}" for a in available_arsenal[:4]]
        persona_text += f"使える武器: {' / '.join(desc_list)}"
        if context.get("arsenal_novelty_push") and not has_mission:
            persona_text += "  ← 今回はこのうち未使用のものを必ず使え"

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

    thread_subquestions = context.get("thread_subquestions", [])
    subquestions_block = ""
    if thread_subquestions:
        sq_lines = "\n".join(f"- {sq}" for sq in thread_subquestions[:8])
        subquestions_block = f"\n【争点の骨格】\n{sq_lines}"

    required_concepts: list[str] = []
    if persona:
        anchors = persona.get("persona_anchors", {})
        required_concepts = anchors.get("required_concepts", []) if isinstance(anchors, dict) else []

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

    recent_self = context.get("recent_self_contents", [])[:4]
    if recent_self:
        context_text += "\n【使用済み論点（完全禁止・同じ切り口・同じ事例・同じ根拠は使うな）】\n" + "\n".join(f"- {c}" for c in recent_self)
    recent_others = context.get("recent_other_contents", [])[:3]
    if recent_others:
        import re as _re

        def _strip_style(s: str) -> str:
            s = _re.sub(r"[wｗ]{2,}", "", s)
            s = _re.sub(r"草+", "", s)
            s = _re.sub(r"ンゴ+", "", s)
            return s.strip()

        context_text += "\n【他者の直近論点（完全禁止：同じ論点・同じ具体例・同じ固有名詞・同じ角度はすべて禁止。内容・事例・切り口を完全に独自にせよ）】\n" + "\n".join(f"- {_strip_style(c)[:80]}" for c in recent_others)

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


def build_script_post_messages(
    persona: dict[str, Any],
    directive: str,
    move_type: str,
    target_post: dict[str, Any],
    recent_posts: list[dict[str, Any]],
    rag_chunks: list[str],
    thread_topic: str,
    phase: int = 2,
    assigned_side: str = "",
) -> list[dict[str, str]]:
    name = persona.get("display_name", "?")
    label = persona.get("label", "")
    worldview = ", ".join(persona.get("worldview", [])[:3])
    non_negotiable = persona.get("speech_constraints", {}).get("non_negotiable", "")
    tone = persona.get("speech_constraints", {}).get("tone", "")
    combat = "; ".join(persona.get("combat_doctrine", [])[:2])
    must_dist = persona.get("must_distinguish_from", {})
    dist_note = "; ".join(f"{k}とは違い「{v[:50]}」" for k, v in list(must_dist.items())[:2])

    side_line = ""
    if assigned_side == "oppose":
        side_line = f"\n⚑【配役：反対側】「{thread_topic[:40]}」に対してNO・そんなことはないという立場を一貫せよ。賛成側の意見に流されるな。"
    elif assigned_side == "support":
        side_line = f"\n⚑【配役：賛成側】「{thread_topic[:40]}」に対してYES・その通りという立場を一貫せよ。反対側の意見に押されるな。"
    elif assigned_side == "neutral":
        side_line = "\n⚑【配役：整理役】賛否どちらにも肩入れせず、論点の再定義・新規の視点・対立の整理をせよ。"

    persona_block = f"【{name}／{label}】\n世界観: {worldview}"
    if non_negotiable:
        persona_block += f"\n絶対に譲れない立場: {non_negotiable}"
    if combat:
        persona_block += f"\n戦闘原則（これがお前の切り口）: {combat}"
    if dist_note:
        persona_block += f"\n他キャラとの差別化（この切り口を守れ）: {dist_note}"
    if tone:
        persona_block += f"\n口調: {tone}"
    if side_line:
        persona_block += side_line

    target_content = str(target_post.get("content", ""))[:140]
    target_name = target_post.get("display_name") or target_post.get("agent_id") or "名無し"
    target_id = target_post.get("id", "?")

    recent_lines = "\n".join(
        f"#{p.get('id', '?')} {p.get('display_name') or p.get('agent_id') or '?'}: {str(p.get('content', ''))[:80]}"
        for p in recent_posts[-5:]
    )
    rag_text = "\n".join(f"- {chunk}" for chunk in rag_chunks[:3]) if rag_chunks else "なし"
    phase_hint = _PHASE_SCRIPT_HINTS.get(phase, "")

    attack_type_hint = ""
    if "攻撃型：" in directive and "：" in directive:
        attack_type_hint = directive.split("：")[0].replace("攻撃型", "").strip()
        attack_type_hint = f"\n【攻撃型】{attack_type_hint} — この型の反駁で一点突破せよ"

    user_content = (
        f"テーマ: {thread_topic}\n"
        f"{persona_block}\n\n"
        f"【今回の指令（最重要）】{directive}{attack_type_hint}\n"
        f"【現在フェーズ】{phase_hint} / 【ムーブタイプ】{move_type}\n\n"
        f"返信先#{target_id}({target_name}): {target_content}\n\n"
        f"直近の会話:\n{recent_lines}\n\n"
        f"知識\n{rag_text}"
    )

    return [
        {"role": "system", "content": _SCRIPT_POST_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
