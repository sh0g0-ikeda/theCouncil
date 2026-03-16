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


@dataclass(slots=True)
class SemanticPostAnalysis:
    effective_axis: str
    effective_function: str
    addresses_target: bool
    target_overlap: float
    answered_post_ids: list[int]
    answered_claim_ids: list[str]
    definition_requests: list[str]
    definition_terms: list[str]
    argument_fingerprint: str
    example_keys: list[str]
    referenced_terms: list[str]
    claim_units: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "effective_axis": self.effective_axis,
            "effective_function": self.effective_function,
            "addresses_target": self.addresses_target,
            "target_overlap": self.target_overlap,
            "answered_post_ids": self.answered_post_ids,
            "answered_claim_ids": self.answered_claim_ids,
            "definition_requests": self.definition_requests,
            "definition_terms": self.definition_terms,
            "argument_fingerprint": self.argument_fingerprint,
            "example_keys": self.example_keys,
            "referenced_terms": self.referenced_terms,
            "claim_units": self.claim_units,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticPostAnalysis":
        return cls(
            effective_axis=str(payload.get("effective_axis", "")),
            effective_function=str(payload.get("effective_function", "")),
            addresses_target=bool(payload.get("addresses_target", False)),
            target_overlap=float(payload.get("target_overlap", 0.0)),
            answered_post_ids=[int(v) for v in payload.get("answered_post_ids", [])],
            answered_claim_ids=[str(v) for v in payload.get("answered_claim_ids", [])],
            definition_requests=[str(v) for v in payload.get("definition_requests", [])],
            definition_terms=[str(v) for v in payload.get("definition_terms", [])],
            argument_fingerprint=str(payload.get("argument_fingerprint", "")),
            example_keys=[str(v) for v in payload.get("example_keys", [])],
            referenced_terms=[str(v) for v in payload.get("referenced_terms", [])],
            claim_units=[dict(v) for v in payload.get("claim_units", []) if isinstance(v, dict)],
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
        addresses_target=addresses_target,
        target_overlap=overlap_score,
        answered_post_ids=answered_post_ids,
        answered_claim_ids=answered_claim_ids,
        definition_requests=definition_requests,
        definition_terms=definition_terms,
        argument_fingerprint=argument_fingerprint,
        example_keys=example_keys,
        referenced_terms=referenced_terms[:6],
        claim_units=claim_units,
    )


def validate_generated_reply(reply: dict[str, Any], context: dict[str, Any]) -> ValidationResult:
    analysis = classify_reply_semantics(reply, context)
    directive_type = _extract_directive_type(str(context.get("private_directive", "")))
    constraint_kind = str(context.get("active_constraint_kind", "")).strip()
    constraint_schema = dict(context.get("active_constraint_schema") or {})
    meta_intervention_kind = str(context.get("meta_intervention_kind", "")).strip()
    stance = str(reply.get("stance", "disagree"))
    recent_axes = [str(axis) for axis in context.get("agent_recent_axes", [])]
    target_post = context.get("target_post", {}) or {}

    forced_axis = str(context.get("forced_axis", "")).strip()
    if forced_axis and analysis.effective_axis != forced_axis:
        return ValidationResult(False, f"Use {forced_axis} as the main axis.", analysis)

    if target_post.get("content") and not analysis.addresses_target and not meta_intervention_kind:
        return ValidationResult(False, "Answer the target post's core claim directly.", analysis)

    if directive_type in {"rebut_core_claim", "deepen_axis"} and target_post.get("content") and not analysis.addresses_target:
        return ValidationResult(False, "Follow the mission and address the target claim.", analysis)

    if directive_type in {"rebut_core_claim", "defend_self_consistency"} and stance not in {"disagree", "shift"}:
        return ValidationResult(False, "Use disagree or shift stance for this mission.", analysis)

    if directive_type in {"echo_break", "introduce_new_axis"} and analysis.effective_axis in recent_axes[-2:]:
        return ValidationResult(False, "Move to an axis you have not used recently.", analysis)

    if directive_type == "use_weapon" and context.get("available_arsenal") and not reply.get("used_arsenal_id"):
        return ValidationResult(False, "Use one available arsenal item and set used_arsenal_id.", analysis)

    pending_terms = [str(term) for term in context.get("pending_definition_terms", []) if str(term).strip()]
    required_kind = str(context.get("required_response_kind", ""))
    if pending_terms and required_kind in {"define", "differentiate"} and not analysis.definition_terms:
        return ValidationResult(False, f"Resolve at least one pending term: {' / '.join(pending_terms[:2])}.", analysis)

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

    if constraint_schema.get("must_address_target") and target_post.get("content") and not analysis.addresses_target:
        return ValidationResult(False, "Address the current target directly.", analysis)

    if constraint_schema.get("must_include_tradeoff") and not _has_tradeoff_markers(str(reply.get("content", ""))):
        return ValidationResult(False, "State a concrete tradeoff or cost.", analysis)

    if constraint_kind == "tradeoff" and not _has_tradeoff_markers(str(reply.get("content", ""))):
        return ValidationResult(False, "State a concrete tradeoff or cost.", analysis)

    if constraint_kind == "refocus" and target_post.get("content") and analysis.target_overlap <= 0.0 and not analysis.definition_terms:
        return ValidationResult(False, "Refocus on the target claim instead of drifting away.", analysis)

    debate_role = str(context.get("debate_role", "")).strip()
    target_role = str(context.get("target_debate_role", "")).strip()
    position_anchor_terms = {
        str(term) for term in context.get("position_anchor_terms", [])
        if str(term).strip()
    }
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

    return ValidationResult(True, "", analysis)
