from __future__ import annotations

import json
import os
from typing import Any

from engine.llm_prompting import SYSTEM_PROMPT, build_prompt, build_script_post_messages
from engine.llm_support import (
    _fallback_debate_frame,
    _frame_terms,
    _normalize_reply,
    validate_reply_length,
)

__all__ = [
    "LLMGenerationError",
    "SYSTEM_PROMPT",
    "assign_debate_frame",
    "assign_debate_roles",
    "build_prompt",
    "build_script_post_messages",
    "call_llm",
    "compress_history",
    "decompose_topic_axes",
    "generate_debate_script",
    "generate_topic_tags",
    "moderate_text",
    "validate_reply_length",
]

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:  # pragma: no cover - optional for offline logic tests
    AsyncOpenAI = None  # type: ignore[assignment]

_client: Any | None = None
_ROUND_ROBIN_ROLES = ("pro", "con", "neutral")


class LLMGenerationError(RuntimeError):
    pass


def _openai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _parse_json_payload(raw_content: str | None) -> dict[str, Any]:
    if not raw_content:
        return {}
    payload = json.loads(raw_content)
    return payload if isinstance(payload, dict) else {}


def _fallback_role_assignments(agent_list: list[dict[str, Any]]) -> dict[str, str]:
    return {
        agent["id"]: _ROUND_ROBIN_ROLES[index % len(_ROUND_ROBIN_ROLES)]
        for index, agent in enumerate(agent_list)
    }


def _get_client() -> Any:
    global _client
    if AsyncOpenAI is None:
        raise RuntimeError("openai package is required")
    if _client is None:
        _client = AsyncOpenAI(timeout=60.0)
    return _client


async def moderate_text(text: str) -> bool:
    if not _openai_enabled():
        return False
    response = await _get_client().moderations.create(model="omni-moderation-latest", input=text)
    return bool(response.results[0].flagged)


async def generate_topic_tags(topic: str) -> list[str]:
    if not _openai_enabled():
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
    payload = _parse_json_payload(response.choices[0].message.content)
    tags = payload.get("tags", [])
    return [str(tag) for tag in tags][:6] or ["論点整理", "価値観", "制度設計", "実行可能性"]


async def compress_history(
    posts: list[dict[str, Any]],
    previous_summary: str = "",
) -> str:
    if not posts:
        return previous_summary

    if not _openai_enabled():
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

async def call_llm(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not _openai_enabled():
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
        payload = _parse_json_payload(response.choices[0].message.content)
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
    if not _openai_enabled() or not agent_list:
        return _fallback_role_assignments(agent_list)

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
        payload = _parse_json_payload(response.choices[0].message.content)
        roles = {k: str(v) for k, v in payload.get("roles", {}).items()
                 if v in {"pro", "con", "neutral"}}
        # Fill in any missing agents with fallback
        for i, agent in enumerate(agent_list):
            if agent["id"] not in roles:
                roles[agent["id"]] = _ROUND_ROBIN_ROLES[i % len(_ROUND_ROBIN_ROLES)]
        return roles
    except Exception:
        return _fallback_role_assignments(agent_list)


async def assign_debate_frame(
    topic: str,
    agent_list: list[dict[str, Any]],
) -> dict[str, Any]:
    if not _openai_enabled() or not agent_list:
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
        payload = _parse_json_payload(response.choices[0].message.content)
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


async def generate_debate_script(
    topic: str,
    agent_list: list[dict[str, Any]],
    max_posts: int = 20,
) -> dict[str, Any]:
    """Generate a per-turn debate script using GPT-4o. Returns {} on failure."""
    if not _openai_enabled() or not agent_list:
        return {}

    agent_lines = []
    for agent in agent_list:
        wv = ", ".join(agent.get("worldview", [])[:3])
        nn = agent.get("speech_constraints", {}).get("non_negotiable", "")[:100]
        combat = "; ".join(agent.get("combat_doctrine", [])[:2])
        must_dist = agent.get("must_distinguish_from", {})
        dist_note = "; ".join(f"{k}とは違い「{v[:50]}」" for k, v in list(must_dist.items())[:2])

        line = (
            f'{agent["id"]}({agent["display_name"]}): '
            f'世界観={wv}. '
            f'絶対に譲れない立場={nn}. '
            f'戦闘原則={combat}.'
        )
        if dist_note:
            line += f' 差別化={dist_note}.'
        agent_lines.append(line)

    act3_start = max(3, max_posts // 3)
    act4_start = max(act3_start + 2, max_posts * 2 // 3)
    act5_start = max(act4_start + 2, max_posts * 85 // 100)

    system_msg = (
        "あなたは「哲学バトル漫画」の脚本家だ。以下を全て満たした台本を生成せよ。\n"
        "\n"
        "【ステップ0：陣営割り当て（最重要・台本生成の前に必ず完了せよ）】\n"
        "以下の3ステップで各エージェントのassigned_sideを決定せよ。\n"
        "\n"
        "  ▶ ステップ0-A：議題の価値前提を3つ抽出する\n"
        "    議題が「正しい」とするためには何を肯定しなければならないか？\n"
        "    例：「強権的リーダーシップの有効性」「個人の自由より集団の安定を優先」「民意より専門的判断を優先」\n"
        "    これらを price_of_support（支持コスト）として明示的にリストアップせよ。\n"
        "\n"
        "  ▶ ステップ0-B：各エージェントのnon_negotiableとworldviewを price_of_support と照合する\n"
        "    照合ルール:\n"
        "    - non_negotiableが price_of_support のどれかと「合致する」→ support 候補\n"
        "    - non_negotiableが price_of_support のどれかと「直接矛盾する」→ oppose 候補\n"
        "    - どちらとも明確に言えない → neutral 候補\n"
        "    worldviewは補助情報として使い、non_negotiableと矛盾する場合はnon_negotiableを優先する。\n"
        "\n"
        "  ▶ ステップ0-C：対立が成立するよう調整する\n"
        "    - support と oppose が最低1名ずつ存在することを確認する\n"
        "    - 全員が同じsideに偏る場合は、最も「条件付き」な者だけをneutralに変更する\n"
        "    - 一度決定したassigned_sideは全turnで絶対に変えない\n"
        "\n"
        "  ✗ 絶対禁止: 順番・インデックス・名前のアルファベット順でsideを機械的に割り当てる\n"
        "\n"
        "【絶対条件1：真の対立】\n"
        "最低1名を否定派（oppose）として配置せよ。議題の前提そのものを「そんなことはない・前提が間違っている」と否定する側。\n"
        "全員がほぼ同じことを言う台本は即失格。賛成派と否定派が真正面から衝突する構図を作れ。\n"
        "\n"
        "【絶対条件2：同陣営でも独自性を持たせよ】\n"
        "同じ陣営に複数キャラがいる場合、それぞれ完全に異なる論理・評価軸・具体例の種類を使わせよ。\n"
        "  ✗ 失格: 賛成派2人が共に「秩序が大事・安定が重要」を繰り返す\n"
        "  ✓ 合格: 賛成派Aは「歴史的制度論（ローマ共和政の崩壊過程）」で攻め、賛成派Bは「経済指標と成果の実証（GDP・インフラ整備率・政策継続性）」で攻める\n"
        "各キャラのworldviewとnon_negotiableを読み込み、そのキャラだけが使える思想的固有性でdirectiveを書け。\n"
        "\n"
        "【絶対条件3：directiveには攻撃型を必ず指定せよ】\n"
        "各directiveは以下の攻撃型を明記し、その型に沿った具体的指示を書け:\n"
        "  ▶ 前提暴き: 相手の主張が成り立つ「暗黙の前提」を特定し、その前提を崩す\n"
        "  ▶ 二重基準指摘: 相手が自陣と敵陣で異なる基準を使っていることを暴く\n"
        "  ▶ 例外追及: 相手の主張が機能しない「具体的な例外ケース」を突きつける\n"
        "  ▶ 定義奪取: 相手が使う重要語を再定義し、相手の論そのものを無効化する\n"
        "  ▶ 逆説呈示: 相手の主張を実現すると相手自身の価値観が損なわれることを示す\n"
        "  ▶ 証拠逆用: 相手が使った事例・数字が実は自分の主張を支持することを示す\n"
        "  ▶ 立場宣言（ACT1のみ）: テーマのキーワードを独自定義し立場を断言\n"
        "\n"
        "  ✗ 失格なdirective: 「独裁の危険性を主張せよ」「自分の立場を述べよ」\n"
        "  ✓ 合格なdirective: 「攻撃型：前提暴き｜turn3のカエサルの『非常時限定』という前提を崩せ。\n"
        "    『非常時』を誰が宣言するかが問われておらず、宣言権限が独裁者自身にある以上、\n"
        "    非常時は永続化する構造的矛盾を突け。オーウェルの思想として『言葉の腐食』ではなく\n"
        "    『制度的自己強化』の観点から論じよ」\n"
        "\n"
        "【絶対条件4：5段階の論点エスカレーション】\n"
        f"  第1段（turn 0〜2）: 立場宣言・定義衝突。各キャラがテーマのキーワードを独自定義し衝突させよ\n"
        f"  第2段（turn 3〜{act3_start - 1}）: 評価軸攻撃。相手の評価基準そのものを攻撃。「なぜその軸で測るのか」を問え\n"
        f"  第3段（turn {act3_start}〜{act4_start - 1}）: 具体事件投入。歴史的数字・制度的事実・極論で既存論を否定する「事件」を起こせ\n"
        f"  第4段（turn {act4_start}〜{act5_start - 1}）: 条件詰め。「では非常時なら？」「期限付きなら？」「誰が判断するのか？」「成果が出なければ撤退するのか？」で追い込め\n"
        f"  第5段（turn {act5_start}〜）: 定義再構築。「〜とは何か」を再定義しながら核心的対立を1点に収束させよ\n"
        "\n"
        "【テーマの条件分解（必須）】\n"
        "テーマのキーワードを分解し、以下の問いが台本内で明示的に論争されるよう設計せよ:\n"
        "- 「手段として〜」: いつ・誰が・どんな条件下で許容されるのか\n"
        "- 「許容」: 誰にとっての許容か（統治者？市民？国際社会？歴史的評価？）\n"
        "- 終了条件・撤退基準は存在するのか\n"
        "- 「成果」を誰がどの指標で測るのか\n"
        "これらをdiscussion_topicsに含め、台本内で順番に詰めさせよ。\n"
        "\n"
        "【証拠の論証機能指定（必須）】\n"
        "directiveで歴史的事例・数字を使う場合、必ず「この例がXを証明し、turn〇のYという主張を崩す」という接続を明記せよ。\n"
        "  ✗ 失格: 「ソ連の崩壊を使え」\n"
        "  ✓ 合格: 「ソ連の農業集産化（1932〜33年のホロドモール・餓死者数百万）を使い、"
        "turn2の『強い指導力が生産性を上げる』という前提を崩せ。測定装置が権力に汚染された体制では"
        "失敗が『失敗』と認識されず政策修正が不可能であることを示せ」\n"
        "\n"
        "【争点圧縮・決着形成アルゴリズム（必須）】\n"
        "第4段以降に「圧縮ターン」を最低1回設計せよ。圧縮ターンのdirectiveには以下を含めよ:\n"
        "- それまでの議論で相手が答えられなかった問いを2〜3個列挙する\n"
        "- そのうち最も致命的な1問を「これに答えられなければ負けだ」として相手に突きつける\n"
        "- 相手が逃げた定義・崩された前提を証拠として参照する\n"
        "第5段の最終ターンは必ず「決裂確認か残存争点の明示」で終わらせよ。\n"
        "  例: 「〜という問いに相手は20レス一度も答えなかった。つまりこの議論の本質は〜であることが確定した」\n"
        "\n"
        "【同陣営差別化の役割分担（必須）】\n"
        "同陣営に複数いる場合、それぞれに異なる「武器ドメイン」を割り当て、directiveで一貫させよ:\n"
        "  武器ドメイン例: 歴史的制度論 / 経済指標・数字 / 哲学・定義論 / 制度設計論 / 倫理・規範論 / 現場論・実態論\n"
        "同じドメインを2人に割り当てることは禁止。ドメインをJSONの各turnにimplicit_domain（省略可）として記録せよ。\n"
        "\n"
        "【その他ルール】\n"
        "- 同じエージェントが連続しないこと\n"
        "- reply_to_turn: 反論時は必ず相手のturn番号を指定（議論が噛み合うこと）\n"
        "- target_claim: 反論時に攻撃対象を30字以内で明記\n"
        "- 同一エージェントが同一論点・同一評価軸を2回使うことは禁止\n"
        "\n"
        'JSONのみ出力: {"proposition": "...", "discussion_topics": ["論点1", ...], "turns": ['
        '{"turn": 0, "agent_id": "...", "assigned_side": "support|oppose|neutral", "phase": 1, '
        '"move_type": "opening_statement|counter_definition|attack|steelman_and_break|concretize|reframe|new_evidence|expose_contradiction|condition_squeeze|definition_rewrite|compression|final_verdict", '
        '"directive": "攻撃型：〜｜...", "reply_to_turn": null, "target_claim": null}]}'
    )
    user_msg = (
        f"議題: {topic}\n\n"
        "参加エージェント:\n" + "\n".join(agent_lines) + "\n\n"
        f"台本のターン数: {max_posts}\n\n"
        "上記の仕様で台本を生成せよ。"
    )

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            max_tokens=4000,
            temperature=0.75,
        )
        payload = _parse_json_payload(response.choices[0].message.content)
        if not isinstance(payload.get("turns"), list) or not payload["turns"]:
            return {}
        return payload
    except Exception:
        return {}


async def decompose_topic_axes(topic: str) -> list[str]:
    """Decompose a debate topic into 4-6 evaluation axes.

    Each axis is a named perspective from which the topic can be judged.
    E.g. "自由の保護", "権力濫用の防止", "経済効率", "民意反映".
    """
    if not _openai_enabled():
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
        payload = _parse_json_payload(response.choices[0].message.content)
        axes = [str(a) for a in payload.get("axes", [])]
        return axes[:6] or ["国際法上の合法性", "安全保障上の合理性", "正戦論的許容性", "歴史的先例", "エスカレーションリスク"]
    except Exception:
        return ["国際法上の合法性", "安全保障上の合理性", "正戦論的許容性", "歴史的先例", "エスカレーションリスク"]
