from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_TOKEN_PATTERN = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)
_CLAIM_SPLIT_PATTERN = re.compile(
    r"(?:[。.!?！？\n;；]+|\bbut\b|\bhowever\b|\bwhile\b|ただし|だが|しかし|一方で|つまり)"
)
_ENGLISH_EXAMPLE_ENTITY_PATTERN = re.compile(
    r"\b([A-Za-z]{2,24}\s+(?:war|crisis|revolution|treaty|law|election|empire))\b",
    re.IGNORECASE,
)
_JP_EXAMPLE_ENTITY_PATTERN = re.compile(
    r"([A-Za-z\u30a1-\u30f6\u4e00-\u9fff]{2,24}(?:戦争|危機|革命|条約|選挙|帝国|法|事件))"
)
_DEFINITION_REQUEST_PATTERNS = (
    re.compile(r"[「\"](?P<term>[^」\"]{1,24})[」\"].{0,16}?(?:って何|とは何|の定義|を明示|何を指)"),
    re.compile(r"(?P<term>民主主義|民意|自由|主権|公共性|正義|秩序).{0,10}?(?:って何|とは何|の定義|を明示|何を指)"),
    re.compile(r"(?P<term>[^\s「」\"']{2,12})(?:[がはも]|って).*?(?:って何|とは何|何を指|の定義|を明示)"),
)
_DEFINITION_MARKERS = ("とは", "定義", "意味", "要するに", "ここでは")
_EXAMPLE_MARKERS = ("例えば", "たとえば", "具体例", "for example", "case")
_EXAMPLE_SUFFIXES = ("戦争", "危機", "革命", "条約", "選挙", "帝国", "法", "事件")
_TRADEOFF_MARKERS = ("tradeoff", "trade-off", "cost", "コスト", "代償", "副作用", "vs", "versus")
_TOPIC_STOPWORDS = {
    "これ",
    "それ",
    "あれ",
    "ここ",
    "そこ",
    "もの",
    "こと",
    "ため",
    "よう",
    "民主主義",
    "民意",
    "政府",
    "国家",
    "制度",
    "政策",
    "社会",
    "経済",
    "権力",
    "成長",
    "自由",
    "公共",
    "代表",
    "people",
    "state",
    "government",
    "system",
    "institution",
    "institutions",
    "policy",
    "policies",
    "power",
    "growth",
    "society",
    "economy",
    "democracy",
    "public",
    "representation",
    "for",
    "example",
    "the",
    "and",
    "that",
    "this",
}
_PHASE1_DEFINITION_POST_LIMIT = 3


@dataclass(slots=True)
class SemanticPostAnalysis:
    effective_axis: str
    effective_function: str
    aligned_side: str
    proposition_stance: str
    local_stance_to_target: str
    camp_function: str
    subquestion_id: str
    addresses_target: bool
    target_overlap: float
    answered_post_ids: list[int]
    answered_claim_ids: list[str]
    definition_requests: list[str]
    definition_terms: list[str]
    argument_fingerprint: str
    proposition_fingerprint: str
    example_keys: list[str]
    referenced_terms: list[str]
    claim_units: list[dict[str, Any]]
    claim_structure: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "effective_axis": self.effective_axis,
            "effective_function": self.effective_function,
            "aligned_side": self.aligned_side,
            "proposition_stance": self.proposition_stance,
            "local_stance_to_target": self.local_stance_to_target,
            "camp_function": self.camp_function,
            "subquestion_id": self.subquestion_id,
            "addresses_target": self.addresses_target,
            "target_overlap": self.target_overlap,
            "answered_post_ids": self.answered_post_ids,
            "answered_claim_ids": self.answered_claim_ids,
            "definition_requests": self.definition_requests,
            "definition_terms": self.definition_terms,
            "argument_fingerprint": self.argument_fingerprint,
            "proposition_fingerprint": self.proposition_fingerprint,
            "example_keys": self.example_keys,
            "referenced_terms": self.referenced_terms,
            "claim_units": self.claim_units,
            "claim_structure": self.claim_structure,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticPostAnalysis":
        return cls(
            effective_axis=str(payload.get("effective_axis", "")),
            effective_function=str(payload.get("effective_function", "")),
            aligned_side=str(payload.get("aligned_side", "")),
            proposition_stance=str(payload.get("proposition_stance", "")),
            local_stance_to_target=str(payload.get("local_stance_to_target", "")),
            camp_function=str(payload.get("camp_function", "")),
            subquestion_id=str(payload.get("subquestion_id", "")),
            addresses_target=bool(payload.get("addresses_target", False)),
            target_overlap=float(payload.get("target_overlap", 0.0)),
            answered_post_ids=[int(v) for v in payload.get("answered_post_ids", [])],
            answered_claim_ids=[str(v) for v in payload.get("answered_claim_ids", [])],
            definition_requests=[str(v) for v in payload.get("definition_requests", [])],
            definition_terms=[str(v) for v in payload.get("definition_terms", [])],
            argument_fingerprint=str(payload.get("argument_fingerprint", "")),
            proposition_fingerprint=str(payload.get("proposition_fingerprint", "")),
            example_keys=[str(v) for v in payload.get("example_keys", [])],
            referenced_terms=[str(v) for v in payload.get("referenced_terms", [])],
            claim_units=[dict(v) for v in payload.get("claim_units", []) if isinstance(v, dict)],
            claim_structure=dict(payload.get("claim_structure") or {}),
        )


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    retry_hint: str
    analysis: SemanticPostAnalysis


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_PATTERN.findall(text or "")]


def _keywords(text: str, *, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for token in _tokenize(text):
        if len(token) < 2 or token in _TOPIC_STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [token for token, _ in ordered[:limit]]


def _extract_definition_requests(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _DEFINITION_REQUEST_PATTERNS:
        for match in pattern.finditer(text or ""):
            term = match.group("term").strip()
            if term and term not in found:
                found.append(term)
    return found[:3]


def _extract_definition_terms(text: str, pending_terms: list[str]) -> list[str]:
    if not pending_terms or not any(marker in (text or "") for marker in _DEFINITION_MARKERS):
        return []
    resolved: list[str] = []
    for term in pending_terms:
        if term and term in text and term not in resolved:
            resolved.append(term)
    return resolved[:3]


def _normalize_turn_contract(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    required_labels: list[str] = []
    for value in payload.get("required_labels", []):
        label = str(value).strip()
        if label and label not in required_labels:
            required_labels.append(label)
    must_define_terms: list[str] = []
    for value in payload.get("must_define_terms", []):
        term = str(value).strip()
        if term and term not in must_define_terms:
            must_define_terms.append(term)
    return {
        "must_answer_subquestion_id": str(payload.get("must_answer_subquestion_id", "")).strip(),
        "must_answer_subquestion_text": str(payload.get("must_answer_subquestion_text", "")).strip(),
        "must_define_terms": must_define_terms[:3],
        "required_labels": required_labels[:4],
        "forbid_question_only": bool(payload.get("forbid_question_only")),
        "resolution_target": str(payload.get("resolution_target", "")).strip(),
    }


def _content_has_required_labels(text: str, labels: list[str]) -> bool:
    content = text or ""
    return all(f"{label}:" in content or f"{label}：" in content for label in labels)


def _looks_like_question_only_reply(text: str, labels: list[str]) -> bool:
    if labels and _content_has_required_labels(text, labels):
        return False
    question_marks = (text or "").count("?") + (text or "").count("？")
    if question_marks <= 0:
        return False
    answer_markers = ("結論:", "結論：", "判断主体:", "判断主体：", "判断基準:", "判断基準：", "定義:", "定義：")
    return not any(marker in (text or "") for marker in answer_markers)


def _looks_like_mirrored_subquestion_reply(text: str, subquestion_text: str, labels: list[str]) -> bool:
    content = text or ""
    prompt_text = subquestion_text or ""
    if not content or not prompt_text:
        return False
    if labels and _content_has_required_labels(content, labels):
        return False
    if not _looks_like_question_only_reply(content, labels):
        return False
    prompt_keywords = set(_keywords(prompt_text, limit=8))
    content_keywords = set(_keywords(content, limit=10))
    keyword_overlap = len(prompt_keywords & content_keywords) / max(len(prompt_keywords), 1) if prompt_keywords else 0.0
    char_overlap = _char_overlap_ratio(content, prompt_text)
    return keyword_overlap >= 0.6 or char_overlap >= 0.75


def _extract_directive_type(text: str) -> str:
    match = re.search(r"MISSION:([a-z_]+)", text or "")
    return match.group(1) if match else ""


def _has_tradeoff_markers(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in _TRADEOFF_MARKERS)


def _normalize_example_token(token: str) -> str:
    lowered = token.lower().strip()
    for suffix in _EXAMPLE_SUFFIXES:
        idx = lowered.find(suffix.lower())
        if idx >= 0:
            return lowered[: idx + len(suffix)]
    return lowered


def _looks_like_named_example(token: str) -> bool:
    if any(suffix.lower() in token.lower() for suffix in _EXAMPLE_SUFFIXES):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
        return True
    if re.fullmatch(r"[\u30a1-\u30f6]{3,}", token):
        return True
    return False


def _extract_example_keys(text: str) -> list[str]:
    keys: list[str] = []
    lowered = (text or "").lower()
    if any(marker in (text or "") for marker in _EXAMPLE_MARKERS) or "for example" in lowered:
        for match in _JP_EXAMPLE_ENTITY_PATTERN.findall(text or ""):
            normalized = _normalize_example_token(match)
            if normalized and normalized not in keys:
                keys.append(normalized)
            if len(keys) >= 3:
                return keys
        for match in _ENGLISH_EXAMPLE_ENTITY_PATTERN.findall(text or ""):
            normalized = match.lower().strip()
            if normalized and normalized not in keys:
                keys.append(normalized)
            if len(keys) >= 3:
                return keys
        for token in _keywords(text, limit=10):
            normalized = _normalize_example_token(token)
            if normalized in keys:
                continue
            if _looks_like_named_example(normalized):
                keys.append(normalized)
            if len(keys) >= 3:
                return keys
    return keys


def _make_claim_key(axis: str, claim_terms: list[str]) -> str:
    if not claim_terms:
        return axis or "rationalism"
    return f"{axis or 'rationalism'}:{'|'.join(sorted(claim_terms[:4]))}"


def _make_argument_fingerprint(main_axis: str, referenced_terms: list[str], content: str) -> str:
    claim_terms = referenced_terms[:6] or _keywords(content, limit=6)
    if not claim_terms:
        return main_axis or "rationalism"
    return f"{main_axis or 'rationalism'}:{'|'.join(sorted(claim_terms))}"


def _extract_claim_units(text: str, main_axis: str, *, limit: int = 2) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    segments = [segment.strip(" 　'\"") for segment in _CLAIM_SPLIT_PATTERN.split(text or "") if segment.strip()]
    if not segments and (text or "").strip():
        segments = [(text or "").strip()]
    for segment in segments:
        terms = _keywords(segment, limit=5)
        if not terms:
            continue
        claim_key = _make_claim_key(main_axis, terms)
        if claim_key in seen:
            continue
        seen.add(claim_key)
        units.append({"claim_key": claim_key, "text": segment[:120], "terms": terms[:5]})
        if len(units) >= limit:
            break
    return units


_PREMISE_MARKERS = ("なぜなら", "だから", "なので", "理由は")
_MECHANISM_MARKERS = ("ことで", "によって", "通じて")
_SENTENCE_END = re.compile(r"[。.!?！？\n]")


def _extract_claim_structure(content: str) -> dict[str, Any]:
    """Heuristic extraction of {premises, conclusion, mechanism} from content."""
    sentences = [s.strip() for s in _SENTENCE_END.split(content or "") if s.strip()]
    conclusion = ""
    for sent in reversed(sentences):
        if sent.endswith(("。", "だ", "である")) or len(sent) > 0:
            if len(sent) <= 60:
                conclusion = sent
                break
    if not conclusion and sentences:
        conclusion = sentences[-1][:60]

    premises: list[str] = []
    for sent in sentences[:-1] if sentences else []:
        if any(marker in sent for marker in _PREMISE_MARKERS):
            premises.append(sent[:80])
        if len(premises) >= 2:
            break

    mechanism = ""
    for sent in sentences:
        if any(marker in sent for marker in _MECHANISM_MARKERS):
            mechanism = sent[:60]
            break

    return {"premises": premises, "conclusion": conclusion, "mechanism": mechanism or None}


def _make_proposition_fingerprint(content: str) -> str:
    """Create a short fingerprint of the proposition from the content."""
    kws = _keywords(content, limit=8)
    return "|".join(sorted(kws[:6])) if kws else ""


def _char_overlap_ratio(a: str, b: str) -> float:
    """Simple character-level overlap ratio between two strings."""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    return len(set_a & set_b) / max(len(set_a), len(set_b))


def _check_persona_anchor(content: str, persona: dict[str, Any]) -> bool:
    """Return True if content satisfies persona_anchors required_concepts (if present)."""
    anchors = persona.get("persona_anchors")
    if not anchors:
        return True
    required = anchors.get("required_concepts", [])
    if not required:
        return True
    return any(concept in content for concept in required)


def summarize_target_claim(target_post: dict[str, Any], conflict_axis: str) -> str:
    content = str(target_post.get("content", "")).strip()
    if not content:
        return ""
    speaker = str(target_post.get("display_name") or target_post.get("agent_id") or "unknown")
    return f"{speaker} claim on {conflict_axis}: {content.replace(chr(10), ' ')[:90]}"


def _axis_candidates(context: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for raw in (
        list(context.get("current_tags", []))
        + list(context.get("topic_axes", []))
        + [context.get("forced_axis", ""), context.get("conflict_axis", "")]
    ):
        axis = str(raw or "").strip()
        if axis and axis not in candidates:
            candidates.append(axis)
    return candidates


def _axis_similarity(raw_axis: str, candidate: str, context: dict[str, Any]) -> float:
    raw_terms = set(_keywords(raw_axis, limit=6)) | set(_tokenize(raw_axis))
    candidate_terms = set(_keywords(candidate, limit=6)) | set(_tokenize(candidate))
    topic_text = " ".join(
        [
            str(context.get("thread_topic", "")),
            " ".join(str(tag) for tag in context.get("current_tags", [])),
            str(context.get("target_post", {}).get("content", "")),
        ]
    )
    topic_terms = set(_keywords(topic_text, limit=12)) | set(_tokenize(topic_text))
    raw_topic_overlap = len(raw_terms & topic_terms)
    candidate_topic_overlap = len(candidate_terms & topic_terms)
    raw_candidate_overlap = len(raw_terms & candidate_terms)
    return raw_candidate_overlap * 2.0 + candidate_topic_overlap - raw_topic_overlap * 0.5


def _normalize_axis_label(raw_axis: str, context: dict[str, Any]) -> str:
    axis = str(raw_axis or "").strip()
    candidates = _axis_candidates(context)
    if not candidates:
        return axis or str(context.get("conflict_axis", "") or "rationalism")
    if not axis:
        return candidates[0]
    for candidate in candidates:
        if axis == candidate or axis.lower() == candidate.lower():
            return candidate
    best = max(candidates, key=lambda candidate: (_axis_similarity(axis, candidate, context), -len(candidate)))
    return best


def _target_claim_units_from_text(target_content: str, effective_axis: str) -> list[dict[str, Any]]:
    units = _extract_claim_units(target_content, effective_axis, limit=2)
    normalized: list[dict[str, Any]] = []
    for idx, unit in enumerate(units):
        normalized.append(
            {
                "claim_id": f"target:{idx}",
                "claim_key": str(unit.get("claim_key", "")),
                "text": str(unit.get("text", "")),
                "terms": [str(term) for term in unit.get("terms", [])],
            }
        )
    return normalized


def _frame_side_terms(context: dict[str, Any], side: str) -> set[str]:
    if side not in {"support", "oppose", "conditional"}:
        return set()
    text = " ".join(
        [
            str(context.get("frame_proposition", "")),
            str(context.get(f"{side}_thesis", "")),
            str(context.get(f"{side}_label", "")),
        ]
    )
    return set(_keywords(text, limit=12)) | set(_tokenize(text))


def _infer_aligned_side(reply: dict[str, Any], context: dict[str, Any], reply_keywords: set[str]) -> str:
    support_terms = _frame_side_terms(context, "support")
    oppose_terms = _frame_side_terms(context, "oppose")
    if not support_terms and not oppose_terms:
        return ""

    stance = str(reply.get("stance", "disagree"))
    target_side = str(context.get("target_side", "")).strip()
    shared_terms = support_terms & oppose_terms
    support_unique = support_terms - shared_terms
    oppose_unique = oppose_terms - shared_terms
    support_score = float(len(reply_keywords & support_unique) * 2 + len(reply_keywords & support_terms) * 0.25)
    oppose_score = float(len(reply_keywords & oppose_unique) * 2 + len(reply_keywords & oppose_terms) * 0.25)
    lowered = str(reply.get("content", "")).lower()
    support_label = str(context.get("support_label", "")).strip().lower()
    oppose_label = str(context.get("oppose_label", "")).strip().lower()
    if support_label and support_label in lowered:
        support_score += 2.5
    if oppose_label and oppose_label in lowered:
        oppose_score += 2.5
    if target_side in {"support", "oppose"}:
        if stance in {"agree", "supplement"}:
            if target_side == "support":
                support_score += 1.5
            else:
                oppose_score += 1.5
        elif stance in {"disagree", "shift"}:
            if target_side == "support":
                oppose_score += 1.5
            else:
                support_score += 1.5
    if support_score <= 0.0 and oppose_score <= 0.0:
        return ""
    if support_score == oppose_score:
        return ""
    return "support" if support_score > oppose_score else "oppose"


def classify_reply_semantics(reply: dict[str, Any], context: dict[str, Any]) -> SemanticPostAnalysis:
    target_post = context.get("target_post", {}) or {}
    target_content = str(target_post.get("content", "")).strip()
    reply_content = str(reply.get("content", "")).strip()
    pending_terms = [str(term) for term in context.get("pending_definition_terms", []) if str(term).strip()]
    effective_function = str(context.get("required_response_kind") or context.get("debate_function") or "attack")
    meta_intervention_kind = str(context.get("meta_intervention_kind", "")).strip()
    effective_axis = _normalize_axis_label(
        str(reply.get("main_axis") or context.get("forced_axis") or context.get("conflict_axis") or "rationalism"),
        context,
    )

    target_keywords = set(_keywords(target_content, limit=6))
    reply_keywords = set(_keywords(reply_content, limit=10))
    overlap_terms = sorted(target_keywords & reply_keywords)
    overlap_score = len(overlap_terms) / max(len(target_keywords), 1) if target_keywords else 0.0
    proposition_stance = str(reply.get("proposition_stance", "")).strip()
    if proposition_stance not in {"support", "oppose", "conditional", "shift"}:
        proposition_stance = ""
    local_stance_to_target = str(reply.get("local_stance_to_target", "")).strip()
    if local_stance_to_target not in {"agree", "disagree", "supplement", "shift"}:
        fallback_local_stance = str(reply.get("stance", "disagree")).strip()
        local_stance_to_target = fallback_local_stance if fallback_local_stance in {"agree", "disagree", "supplement", "shift"} else ""
    assigned_camp_function = str(context.get("assigned_camp_function", "")).strip()
    camp_function = str(reply.get("camp_function", "")).strip() or assigned_camp_function
    required_subquestion_id = str(context.get("required_subquestion_id", "")).strip()
    subquestion_id = str(reply.get("subquestion_id", "")).strip() or required_subquestion_id
    aligned_side = proposition_stance if proposition_stance in {"support", "oppose"} else _infer_aligned_side(reply, context, reply_keywords)

    definition_requests = _extract_definition_requests(reply_content)
    definition_terms = _extract_definition_terms(reply_content, pending_terms)
    definition_response_mode = effective_function in {"define", "differentiate"}

    target_claim_units = [dict(unit) for unit in context.get("target_claim_units", []) if isinstance(unit, dict)]
    if not target_claim_units and target_content:
        target_claim_units = _target_claim_units_from_text(target_content, effective_axis)
    answered_claim_ids: list[str] = []
    best_claim_overlap = 0.0
    for unit in target_claim_units:
        claim_id = str(unit.get("claim_id") or unit.get("claim_key") or "").strip()
        terms = {str(term) for term in unit.get("terms", []) if str(term).strip()}
        if not terms:
            terms = set(_keywords(str(unit.get("text", "")), limit=6))
        unit_overlap = len(terms & reply_keywords) / max(len(terms), 1) if terms else 0.0
        best_claim_overlap = max(best_claim_overlap, unit_overlap)
        if unit_overlap > 0.0 or (
            definition_response_mode
            and any(term in str(unit.get("text", "")) for term in definition_terms)
        ):
            if claim_id:
                answered_claim_ids.append(claim_id)

    requires_strict_targeting = bool(target_content) and not meta_intervention_kind
    definition_only_pass = definition_response_mode and bool(definition_terms)
    target_match_score = max(overlap_score, best_claim_overlap)
    addresses_target = (
        not target_content
        or not requires_strict_targeting
        or target_match_score > 0.0
        or definition_only_pass
        or bool(answered_claim_ids)
    )

    referenced_terms = _keywords(reply_content, limit=10)
    for term in definition_terms:
        if term not in referenced_terms:
            referenced_terms.insert(0, term)
    referenced_terms = referenced_terms[:8]
    argument_fingerprint = _make_argument_fingerprint(effective_axis, referenced_terms, reply_content)
    proposition_fingerprint = _make_proposition_fingerprint(reply_content)
    claim_structure = _extract_claim_structure(reply_content)
    example_keys = _extract_example_keys(reply_content)
    claim_units = _extract_claim_units(
        reply_content,
        effective_axis,
        limit=2 if effective_function in {"attack", "steelman", "differentiate"} else 1,
    )
    answered_post_ids: list[int] = []
    if addresses_target and target_post.get("id") is not None and not answered_claim_ids:
        answered_post_ids.append(int(target_post["id"]))

    return SemanticPostAnalysis(
        effective_axis=effective_axis,
        effective_function=effective_function,
        aligned_side=aligned_side,
        proposition_stance=proposition_stance,
        local_stance_to_target=local_stance_to_target,
        camp_function=camp_function,
        subquestion_id=subquestion_id,
        addresses_target=addresses_target,
        target_overlap=overlap_score,
        answered_post_ids=answered_post_ids,
        answered_claim_ids=answered_claim_ids,
        definition_requests=definition_requests,
        definition_terms=definition_terms,
        argument_fingerprint=argument_fingerprint,
        proposition_fingerprint=proposition_fingerprint,
        example_keys=example_keys,
        referenced_terms=referenced_terms[:6],
        claim_units=claim_units,
        claim_structure=claim_structure,
    )


def validate_generated_reply(reply: dict[str, Any], context: dict[str, Any]) -> ValidationResult:
    analysis = classify_reply_semantics(reply, context)
    directive_type = _extract_directive_type(str(context.get("private_directive", "")))
    constraint_kind = str(context.get("active_constraint_kind", "")).strip()
    constraint_schema = dict(context.get("active_constraint_schema") or {})
    turn_contract = _normalize_turn_contract(context.get("turn_contract"))
    meta_intervention_kind = str(context.get("meta_intervention_kind", "")).strip()
    stance = str(reply.get("stance", "disagree"))
    recent_axes = [str(axis) for axis in context.get("agent_recent_axes", [])]
    target_post = context.get("target_post", {}) or {}
    debate_post_count = int(context.get("debate_post_count", 999))
    is_first_post = bool(context.get("is_first_post"))
    abstract_terms = [str(t) for t in context.get("abstract_terms", []) if str(t).strip()]
    pending_abstract = [t for t in abstract_terms if t not in {str(v) for v in context.get("resolved_abstract_terms", [])}]

    if (
        debate_post_count <= _PHASE1_DEFINITION_POST_LIMIT
        and analysis.effective_function not in {"define", "differentiate", "facilitate"}
        and pending_abstract
    ):
        return ValidationResult(False, f"phase1_definition_required: define {' / '.join(pending_abstract[:2])} first.", analysis)

    forced_axis = str(context.get("forced_axis", "")).strip()
    if forced_axis and analysis.effective_axis != forced_axis:
        return ValidationResult(False, f"Use {forced_axis} as the main axis.", analysis)

    contract_subquestion_id = str(turn_contract.get("must_answer_subquestion_id", "")).strip()
    contract_subquestion_text = str(turn_contract.get("must_answer_subquestion_text", "")).strip()
    contract_required_labels = [str(label) for label in turn_contract.get("required_labels", []) if str(label).strip()]
    contract_answer_satisfied = False

    if contract_subquestion_id and analysis.subquestion_id != contract_subquestion_id:
        return ValidationResult(False, f"Answer subquestion {contract_subquestion_id} directly.", analysis)
    if contract_required_labels and not _content_has_required_labels(str(reply.get("content", "")), contract_required_labels):
        return ValidationResult(False, f"Use these labels explicitly: {' / '.join(contract_required_labels[:3])}.", analysis)
    if turn_contract.get("forbid_question_only") and _looks_like_question_only_reply(str(reply.get("content", "")), contract_required_labels):
        return ValidationResult(False, "Answer the assigned question directly instead of only repeating it.", analysis)
    if contract_subquestion_text and _looks_like_mirrored_subquestion_reply(
        str(reply.get("content", "")),
        contract_subquestion_text,
        contract_required_labels,
    ):
        return ValidationResult(False, "Do not mirror the same subquestion back. Give a concrete answer.", analysis)
    if contract_subquestion_id:
        contract_answer_satisfied = True

    addresses_current_target = analysis.addresses_target or contract_answer_satisfied

    if target_post.get("content") and not addresses_current_target and not meta_intervention_kind:
        return ValidationResult(False, "Answer the target post's core claim directly.", analysis)

    if directive_type in {"rebut_core_claim", "deepen_axis"} and target_post.get("content") and not addresses_current_target:
        return ValidationResult(False, "Follow the mission and address the target claim.", analysis)

    if directive_type in {"rebut_core_claim", "defend_self_consistency"} and stance not in {"disagree", "shift"}:
        return ValidationResult(False, "Use disagree or shift stance for this mission.", analysis)

    if directive_type in {"echo_break", "introduce_new_axis"} and analysis.effective_axis in recent_axes[-2:]:
        return ValidationResult(False, "Move to an axis you have not used recently.", analysis)

    if directive_type == "use_weapon" and context.get("available_arsenal") and not reply.get("used_arsenal_id"):
        return ValidationResult(False, "Use one available arsenal item and set used_arsenal_id.", analysis)

    pending_terms = [str(term) for term in context.get("pending_definition_terms", []) if str(term).strip()]
    required_kind = str(context.get("required_response_kind", ""))
    if (
        pending_terms
        and required_kind in {"define", "differentiate"}
        and not analysis.definition_terms
        and not is_first_post
    ):
        return ValidationResult(False, f"Resolve at least one pending term: {' / '.join(pending_terms[:2])}.", analysis)
    contract_define_terms = [str(term) for term in turn_contract.get("must_define_terms", []) if str(term).strip()]
    if contract_define_terms and not ({*analysis.definition_terms} & {*contract_define_terms}) and not is_first_post:
        return ValidationResult(False, f"Define at least one required term: {' / '.join(contract_define_terms[:2])}.", analysis)

    assigned_side = str(context.get("assigned_side", "")).strip()
    assigned_side_label = str(context.get("assigned_side_label", "")).strip() or assigned_side
    if stance == "shift" and assigned_side in {"support", "oppose"} and not str(reply.get("shift_reason", "")).strip():
        return ValidationResult(False, "When shifting sides, explain the concession in shift_reason.", analysis)
    if (
        not meta_intervention_kind
        and assigned_side in {"support", "oppose"}
        and stance != "shift"
        and analysis.proposition_stance != assigned_side
    ):
        if not analysis.proposition_stance:
            return ValidationResult(False, f"State proposition_stance explicitly as {assigned_side}.", analysis)
        return ValidationResult(False, f"Stay on the {assigned_side_label} side unless you explicitly use shift.", analysis)

    if target_post.get("content") and not meta_intervention_kind and not analysis.local_stance_to_target:
        return ValidationResult(False, "Set local_stance_to_target explicitly for this reply.", analysis)

    assigned_camp_function = str(context.get("assigned_camp_function", "")).strip()
    if assigned_camp_function and not analysis.camp_function:
        return ValidationResult(False, f"State camp_function explicitly as {assigned_camp_function}.", analysis)
    if assigned_camp_function and analysis.camp_function and analysis.camp_function != assigned_camp_function:
        return ValidationResult(False, f"Stay within your camp_function: {assigned_camp_function}.", analysis)

    required_subquestion_id = str(context.get("required_subquestion_id", "")).strip()
    if required_subquestion_id and analysis.subquestion_id != required_subquestion_id:
        return ValidationResult(False, f"Answer subquestion {required_subquestion_id} directly.", analysis)

    recent_fingerprints = {str(v) for v in context.get("recent_argument_fingerprints", []) if str(v).strip()}
    if analysis.argument_fingerprint and analysis.argument_fingerprint in recent_fingerprints:
        return ValidationResult(False, "Use a genuinely different argument structure.", analysis)

    forbidden_example_keys = {str(v).lower() for v in context.get("forbidden_example_keys", []) if str(v).strip()}
    repeated_examples = sorted({example.lower() for example in analysis.example_keys} & forbidden_example_keys)
    if repeated_examples:
        return ValidationResult(False, f"Do not reuse { ' / '.join(repeated_examples[:2]) } again right now.", analysis)

    allowed_axes = [str(axis) for axis in constraint_schema.get("allowed_axes", []) if str(axis).strip()]
    if allowed_axes and analysis.effective_axis not in allowed_axes:
        return ValidationResult(False, f"Stay on one of these axes only: {' / '.join(allowed_axes[:2])}.", analysis)

    if constraint_schema.get("must_address_target") and target_post.get("content") and not addresses_current_target:
        return ValidationResult(False, "Address the current target directly.", analysis)

    if constraint_schema.get("must_include_tradeoff") and not _has_tradeoff_markers(str(reply.get("content", ""))):
        return ValidationResult(False, "State a concrete tradeoff or cost.", analysis)

    if constraint_kind == "tradeoff" and not _has_tradeoff_markers(str(reply.get("content", ""))):
        return ValidationResult(False, "State a concrete tradeoff or cost.", analysis)

    if constraint_kind == "refocus" and target_post.get("content") and not addresses_current_target and not analysis.definition_terms:
        return ValidationResult(False, "Refocus on the target claim instead of drifting away.", analysis)

    # Persona anchor check: for attack/steelman/supplement, at least one required_concept must appear
    persona = context.get("persona") or {}
    if analysis.effective_function in {"attack", "steelman", "supplement"} and persona:
        if not _check_persona_anchor(str(reply.get("content", "")), persona):
            req = persona.get("persona_anchors", {}).get("required_concepts", [])
            return ValidationResult(False, f"Use at least one of your required concepts: {', '.join(req[:3])}.", analysis)

    # Conclusion repetition check: if current conclusion >= 80% similar to last 3 conclusions from same agent
    current_conclusion = str(analysis.claim_structure.get("conclusion", "")).strip()
    recent_conclusions = [str(c) for c in context.get("recent_agent_conclusions", []) if str(c).strip()]
    if current_conclusion and recent_conclusions:
        for prev_conclusion in recent_conclusions[-3:]:
            if _char_overlap_ratio(current_conclusion, prev_conclusion) >= 0.8:
                return ValidationResult(False, "Use a genuinely different argument structure.", analysis)

    debate_role = str(context.get("debate_role", "")).strip()
    target_role = str(context.get("target_debate_role", "")).strip()
    target_side = str(context.get("target_side", "")).strip()
    position_anchor_terms = {
        str(term) for term in context.get("position_anchor_terms", [])
        if str(term).strip()
    }
    if (
        not meta_intervention_kind
        and assigned_side in {"support", "oppose"}
        and analysis.aligned_side
        and analysis.aligned_side != assigned_side
        and stance != "shift"
    ):
        return ValidationResult(
            False,
            f"Stay on the {assigned_side_label} side unless you explicitly use shift.",
            analysis,
        )
    if (
        not meta_intervention_kind
        and context.get("is_first_post")
        and assigned_side in {"support", "oppose"}
        and stance != "shift"
        and not analysis.aligned_side
        and not (position_anchor_terms & set(analysis.referenced_terms))
    ):
        return ValidationResult(False, "State your assigned side's thesis explicitly in the opening post.", analysis)
    if (
        not meta_intervention_kind
        and debate_role in {"pro", "con"}
        and target_role in {"pro", "con"}
        and target_role != debate_role
        and stance in {"agree", "supplement"}
    ):
        reply_terms = set(analysis.referenced_terms)
        if not position_anchor_terms or not (position_anchor_terms & reply_terms):
            return ValidationResult(False, "Do not align with the opposite side without an explicit shift.", analysis)
    if (
        not meta_intervention_kind
        and assigned_side in {"support", "oppose"}
        and target_side in {"support", "oppose"}
        and target_side != assigned_side
        and stance in {"agree", "supplement"}
    ):
        return ValidationResult(False, "Do not endorse the opposite camp without an explicit shift.", analysis)

    return ValidationResult(True, "", analysis)
