from __future__ import annotations

import json
import re
from pathlib import Path

_chunk_cache: dict[str, list[dict]] = {}
_token_pattern = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)
_definition_markers = ("定義", "意味", "とは", "概念", "指す")
_history_markers = ("戦争", "危機", "革命", "条約", "選挙", "事例", "歴史", "帝国")
_tradeoff_markers = ("コスト", "代償", "副作用", "tradeoff", "trade-off", "vs", "versus")
_synthesis_markers = ("一方", "ただし", "しかし", "両立", "統合", "同時に")

EVIDENCE_FAMILIES: dict[str, list[str]] = {
    "state_withering": ["国家の死滅", "エンゲルス", "段階的消滅", "行政の社会への吸収"],
    "dictatorship_of_proletariat": ["プロレタリア独裁", "移行期", "人民民主独裁", "レーニン"],
    "mass_line": ["群衆路線", "毛沢東", "大衆から学ぶ", "継続革命"],
    "gulag_terror": ["強制収容所", "スターリン粛清", "大テロル", "政治的弾圧"],
    "public_plurality": ["公共空間", "アーレント", "多元性", "自発性"],
    "language_corruption": ["言語腐敗", "オーウェル", "プロパガンダ", "ニュースピーク"],
    "authoritarian_capture": ["権威主義的支配", "制度的腐敗", "権力集中", "強権"],
}

_SECURITY_KEYWORDS = {"安全保障", "テロ", "治安", "国防", "軍事", "terrorism", "security", "defense"}


def _agents_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agents"


def clear_chunk_cache(agent_id: str | None = None) -> None:
    if agent_id is None:
        _chunk_cache.clear()
        return
    _chunk_cache.pop(agent_id, None)


def load_chunks(agent_id: str) -> list[dict]:
    if agent_id not in _chunk_cache:
        path = _agents_dir() / agent_id / "chunks.jsonl"
        if path.exists():
            _chunk_cache[agent_id] = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            _chunk_cache[agent_id] = []
    return _chunk_cache[agent_id]


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _token_pattern.findall(text or "")}


def _derive_retrieval_mode(context: dict) -> str:
    mode = str(context.get("retrieval_mode", "")).strip()
    if mode:
        return mode
    debate_function = str(context.get("debate_function", ""))
    if debate_function in {"define", "differentiate"}:
        return "definition"
    if debate_function in {"attack", "steelman"}:
        return "counterexample"
    if debate_function == "concretize":
        return "concrete"
    if debate_function == "synthesize":
        return "synthesis"
    return "default"


def _mode_bonus(mode: str, chunk: dict, pending_terms: list[str], focus_axis: str) -> float:
    text = str(chunk.get("text", ""))
    tags = {str(tag).lower() for tag in chunk.get("tags", [])}
    lowered = text.lower()

    if mode == "definition":
        pending_bonus = 0.35 if any(term and term in text for term in pending_terms) else 0.0
        marker_bonus = 0.3 if any(marker in text for marker in _definition_markers) else 0.0
        return pending_bonus + marker_bonus
    if mode == "counterexample":
        history_bonus = 0.25 if any(marker in text for marker in _history_markers) else 0.0
        axis_bonus = 0.2 if focus_axis and focus_axis.lower() in tags else 0.0
        return history_bonus + axis_bonus
    if mode == "concrete":
        return 0.3 if any(marker in text for marker in _history_markers) or "example" in lowered else 0.0
    if mode == "tradeoff":
        return 0.35 if any(marker.lower() in lowered for marker in _tradeoff_markers) else 0.0
    if mode == "synthesis":
        return 0.3 if any(marker in text for marker in _synthesis_markers) else 0.0
    return 0.0


def retrieve_chunks(agent_id: str, context: dict, top_k: int = 4) -> list[str]:
    chunks = load_chunks(agent_id)
    if not chunks:
        return []

    mode = _derive_retrieval_mode(context)
    query_tags = {str(tag).lower() for tag in context.get("current_tags", [])}
    focus_axis = str(context.get("conflict_axis", "")).strip()
    if focus_axis:
        query_tags.add(focus_axis.lower())
    query_text = " ".join(
        [
            str(context.get("thread_topic", "")),
            str(context.get("target_post", {}).get("content", "")),
            str(context.get("target_claim_summary", "")),
            " ".join(str(term) for term in context.get("pending_definition_terms", [])),
        ]
    )
    query_words = _tokenize(query_text)
    pending_terms = [str(term) for term in context.get("pending_definition_terms", []) if str(term).strip()]
    forbidden_example_keys = {str(v).lower() for v in context.get("forbidden_example_keys", []) if str(v).strip()}

    # Precompute which evidence families are relevant to the thread topic
    topic_lower = query_text.lower()
    relevant_families: set[str] = set()
    for family_name, keywords in EVIDENCE_FAMILIES.items():
        if any(kw.lower() in topic_lower for kw in keywords):
            relevant_families.add(family_name)
    topic_has_security = any(kw.lower() in topic_lower for kw in _SECURITY_KEYWORDS)

    def score(chunk: dict) -> float:
        tags = {str(tag).lower() for tag in chunk.get("tags", [])}
        text = str(chunk.get("text", ""))
        words = _tokenize(text)
        tag_score = len(tags & query_tags) / max(len(query_tags), 1)
        keyword_score = len(words & query_words) / max(len(query_words), 1) if query_words else 0.0
        topic_score = 0.15 if str(chunk.get("topic", "")).lower() in query_text.lower() else 0.0
        mode_score = _mode_bonus(mode, chunk, pending_terms, focus_axis)
        repeated_example_penalty = 0.0
        lowered = text.lower()
        if any(key and key in lowered for key in forbidden_example_keys):
            repeated_example_penalty = 0.45

        # Evidence family bonus/penalty
        family_bonus = 0.0
        for family_name, keywords in EVIDENCE_FAMILIES.items():
            if any(kw.lower() in lowered for kw in keywords):
                if family_name in relevant_families:
                    family_bonus += 0.25
                elif family_name == "authoritarian_capture" and not topic_has_security:
                    family_bonus -= 0.3

        return tag_score * 0.4 + keyword_score * 0.3 + topic_score + mode_score - repeated_example_penalty + family_bonus

    ranked = sorted(chunks, key=score, reverse=True)
    return [str(chunk.get("text", "")) for chunk in ranked[:top_k] if str(chunk.get("text", "")).strip()]
