from __future__ import annotations

from typing import Any

from engine.debate_state_control import DebateStateControlMixin
from engine.debate_state_queries import DebateStateQueryMixin
from engine.debate_state_serialization import DebateStateSerializationMixin
from engine.debate_state_support import CONTRACT_TOKEN_PATTERN


class DebateState(DebateStateSerializationMixin, DebateStateControlMixin, DebateStateQueryMixin):
    """In-memory debate dynamics container with semantic state tracking."""

    def __init__(self) -> None:
        self.anger: dict[tuple[str, str], int] = {}
        self.retaliation_queue: list[str] = []
        self.recent_axes: list[str] = []
        self.internal_states: dict[str, str] = {}
        self.arsenal_cooldowns: dict[str, dict[str, int]] = {}
        self.recent_functions: list[str] = []
        self.stance_history: dict[str, list[str]] = {}
        self.used_arsenal_ids: dict[str, set[str]] = {}
        self.debate_roles: dict[str, str] = {}
        self.debate_frame: dict[str, Any] = {}
        self.agent_sides: dict[str, str] = {}
        self.camp_functions: dict[str, str] = {}
        self.side_contracts: dict[str, dict[str, Any]] = {}
        self.shift_history: dict[str, list[dict[str, Any]]] = {}
        self.forced_axis_queue: list[tuple[str, str]] = []
        self.topic_axes: list[str] = []
        self.agent_axis_usage: dict[str, list[str]] = {}
        self.agent_directives: dict[str, list[str]] = {}
        self.open_attacks: list[tuple[str, str, str]] = []
        self.agreement_streak: dict[str, int] = {}
        self.axis_depth: dict[str, str] = {}
        self.axis_attack_count: dict[str, int] = {}
        self.active_constraint: str = ""
        self.active_constraint_kind: str = ""
        self.active_constraint_schema: dict[str, Any] = {}
        self.constraint_turns: int = 0
        self.claims: dict[str, dict[str, Any]] = {}
        self.claim_order: list[str] = []
        self.definition_requests: dict[str, dict[str, Any]] = {}
        self.subquestions: dict[str, dict[str, Any]] = {}
        self.subquestion_order: list[str] = []
        self.followup_assignments: list[dict[str, Any]] = []
        self.recent_argument_fingerprints: list[str] = []
        self.recent_example_keys: list[str] = []
        self.position_anchors: dict[str, dict[str, Any]] = {}
        self.last_seen_post_id: int = 0
        self.thread_subquestions: list[str] = []
        self.camp_proposition_map: dict[str, list[str]] = {}
        self.alerts: set[str] = set()
        self.abstract_terms: list[str] = []
        self.open_claim_structures: list[dict[str, Any]] = []

    def record_post(
        self,
        speaker_id: str,
        target_post: dict[str, Any],
        focus_axis: str,
        debate_function: str = "attack",
        used_arsenal_id: str | None = None,
        arsenal_cooldown: int = 3,
        stance: str = "disagree",
        post_id: int | None = None,
        analysis: dict[str, Any] | None = None,
        content: str = "",
    ) -> None:
        target_agent = target_post.get("agent_id")
        if target_agent and target_agent != speaker_id:
            key = (speaker_id, target_agent)
            self.anger[key] = self.anger.get(key, 0) + 1
            if target_agent not in self.retaliation_queue:
                self.retaliation_queue.append(target_agent)
            if len(self.retaliation_queue) > 6:
                self.retaliation_queue.pop(0)

        self._update_internal_states(speaker_id, target_agent)

        if stance in {"agree", "supplement"}:
            self.agreement_streak[speaker_id] = self.agreement_streak.get(speaker_id, 0) + 1
        else:
            self.agreement_streak[speaker_id] = 0

        if focus_axis:
            self.recent_axes.append(focus_axis)
            self._deepen_axis(focus_axis, debate_function, stance)
        if len(self.recent_axes) > 8:
            self.recent_axes.pop(0)

        if focus_axis and speaker_id:
            agent_axes = self.agent_axis_usage.setdefault(speaker_id, [])
            agent_axes.append(focus_axis)
            if len(agent_axes) > 4:
                agent_axes.pop(0)

        if debate_function:
            self.recent_functions.append(debate_function)
        if len(self.recent_functions) > 6:
            self.recent_functions.pop(0)

        if stance and speaker_id:
            history = self.stance_history.setdefault(speaker_id, [])
            history.append(stance)
            if len(history) > 5:
                history.pop(0)

        for agent_cooldowns in self.arsenal_cooldowns.values():
            for arg_id in list(agent_cooldowns):
                if agent_cooldowns[arg_id] > 0:
                    agent_cooldowns[arg_id] -= 1

        if used_arsenal_id and speaker_id:
            if speaker_id not in self.arsenal_cooldowns:
                self.arsenal_cooldowns[speaker_id] = {}
            self.arsenal_cooldowns[speaker_id][used_arsenal_id] = arsenal_cooldown
            self.used_arsenal_ids.setdefault(speaker_id, set()).add(used_arsenal_id)

        if post_id is not None:
            self._register_semantic_state(
                post_id=post_id,
                speaker_id=speaker_id,
                target_post=target_post,
                debate_function=debate_function,
                stance=stance,
                analysis=analysis or {},
                content=content,
            )

    def _register_semantic_state(
        self,
        *,
        post_id: int,
        speaker_id: str,
        target_post: dict[str, Any],
        debate_function: str,
        stance: str,
        analysis: dict[str, Any],
        content: str,
    ) -> None:
        self.last_seen_post_id = max(self.last_seen_post_id, int(post_id))
        fingerprint = str(analysis.get("argument_fingerprint", "")).strip()
        proposition_fingerprint = str(analysis.get("proposition_fingerprint", "")).strip()
        if fingerprint:
            self.recent_argument_fingerprints.append(fingerprint)
            if len(self.recent_argument_fingerprints) > 12:
                self.recent_argument_fingerprints.pop(0)
        if speaker_id and proposition_fingerprint:
            proposition_count = self.record_proposition(speaker_id, proposition_fingerprint)
            if proposition_count >= 3:
                self.alerts.add("camp_reassert")

        for example_key in [str(value).strip() for value in analysis.get("example_keys", [])]:
            if not example_key:
                continue
            self.recent_example_keys.append(example_key)
            if len(self.recent_example_keys) > 12:
                self.recent_example_keys.pop(0)

        for term in [str(value).strip() for value in analysis.get("definition_requests", [])]:
            if not term:
                continue
            existing = self.definition_requests.get(term, {})
            target_agent_id = target_post.get("agent_id") if target_post.get("agent_id") != speaker_id else existing.get("target_agent_id")
            self.definition_requests[term] = {
                "status": "open",
                "requested_post_id": post_id,
                "requested_by": speaker_id,
                "target_agent_id": target_agent_id,
                "created_post_id": post_id,
                "answered_post_id": existing.get("answered_post_id"),
                "answered_by": existing.get("answered_by"),
            }

        for term in [str(value).strip() for value in analysis.get("definition_terms", [])]:
            if not term:
                continue
            existing = self.definition_requests.get(term, {})
            self.definition_requests[term] = {
                "status": "answered",
                "requested_post_id": existing.get("requested_post_id"),
                "requested_by": existing.get("requested_by"),
                "target_agent_id": existing.get("target_agent_id"),
                "created_post_id": existing.get("created_post_id"),
                "answered_post_id": post_id,
                "answered_by": speaker_id,
            }

        for answered_claim_id in [str(value).strip() for value in analysis.get("answered_claim_ids", [])]:
            self._mark_claim_answered(answered_claim_id, post_id)
        for answered_post_id in [int(value) for value in analysis.get("answered_post_ids", [])]:
            for claim_id, claim in self.claims.items():
                if int(claim.get("parent_post_id") or claim.get("post_id") or -1) == answered_post_id:
                    self._mark_claim_answered(claim_id, post_id)

        subquestion_id = str(analysis.get("subquestion_id", "")).strip()
        if subquestion_id:
            subquestion = self.subquestions.get(subquestion_id, {})
            if subquestion and subquestion.get("target_agent_id") == speaker_id:
                subquestion["status"] = "answered"
                subquestion["answered_post_id"] = post_id
                subquestion["answered_by"] = speaker_id
                for item in self.followup_assignments:
                    if item.get("status") == "open" and item.get("subquestion_id") == subquestion_id and item.get("agent_id") == speaker_id:
                        item["status"] = "resolved"

        target_agent = target_post.get("agent_id")
        if target_agent and target_agent != speaker_id and debate_function in {"attack", "steelman"}:
            claim_units = [
                dict(unit) for unit in analysis.get("claim_units", [])
                if isinstance(unit, dict)
            ]
            if not claim_units:
                claim_units = [{
                    "claim_key": str(analysis.get("argument_fingerprint", "")) or f"claim:{post_id}:0",
                    "text": str(content).strip()[:120],
                    "terms": [],
                }]
            for index, unit in enumerate(claim_units):
                claim_id = f"claim:{post_id}:{index}"
                self.claims[claim_id] = {
                    "claim_id": claim_id,
                    "claim_key": str(unit.get("claim_key", "")) or f"claim:{post_id}:{index}",
                    "claim_text": str(unit.get("text", ""))[:120],
                    "terms": [str(term) for term in unit.get("terms", [])][:5],
                    "post_id": post_id,
                    "parent_post_id": post_id,
                    "speaker_id": speaker_id,
                    "target_agent_id": target_agent,
                    "status": "open",
                    "focus_axis": analysis.get("effective_axis", ""),
                    "stance": stance,
                    "snippet": str(content).strip()[:60],
                    "created_post_id": post_id,
                }
                self.claim_order.append(claim_id)
                if len(self.claim_order) > 40:
                    old_claim_id = self.claim_order.pop(0)
                    self.claims.pop(old_claim_id, None)

        if target_agent and target_agent != speaker_id and debate_function in {"attack", "steelman", "differentiate", "concretize"}:
            claim_units = [
                dict(unit) for unit in analysis.get("claim_units", [])
                if isinstance(unit, dict)
            ]
            camp_function = str(analysis.get("camp_function", "")).strip() or self.get_camp_function(speaker_id)
            side = str(analysis.get("proposition_stance", "")).strip() or self.get_agent_side(speaker_id)
            for index, unit in enumerate(claim_units[:2]):
                text = str(unit.get("text", ""))[:120] or str(content).strip()[:120]
                terms = [str(term) for term in unit.get("terms", [])][:5]
                duplicate_subquestion_id = self._find_matching_open_subquestion(
                    target_agent_id=target_agent,
                    text=text,
                    terms=terms,
                )
                if duplicate_subquestion_id:
                    existing = self.subquestions.get(duplicate_subquestion_id)
                    if existing:
                        existing["duplicate_count"] = int(existing.get("duplicate_count") or 1) + 1
                        existing["last_referenced_post_id"] = post_id
                        if camp_function and not existing.get("camp_function"):
                            existing["camp_function"] = camp_function
                        if side and not existing.get("side"):
                            existing["side"] = side
                        if int(existing.get("duplicate_count") or 1) >= 2:
                            self.alerts.add("camp_reassert")
                    continue
                subquestion_id = f"sq:{post_id}:{index}"
                self.subquestions[subquestion_id] = {
                    "subquestion_id": subquestion_id,
                    "text": text,
                    "terms": terms,
                    "post_id": post_id,
                    "target_agent_id": target_agent,
                    "speaker_id": speaker_id,
                    "camp_function": camp_function,
                    "side": side,
                    "status": "open",
                    "created_post_id": post_id,
                    "duplicate_count": 1,
                }
                self.subquestion_order.append(subquestion_id)
                if len(self.subquestion_order) > 40:
                    stale_id = self.subquestion_order.pop(0)
                    self.subquestions.pop(stale_id, None)

        if speaker_id and (
            speaker_id not in self.position_anchors
            or int(self.position_anchors.get(speaker_id, {}).get("post_id") or 0) <= 0
        ):
            referenced_terms = [str(term) for term in analysis.get("referenced_terms", []) if str(term).strip()]
            self.position_anchors[speaker_id] = {
                "post_id": post_id,
                "summary": str(content).strip()[:140],
                "fingerprint": fingerprint,
                "terms": referenced_terms[:6],
                "axis": str(analysis.get("effective_axis", "")),
                "role": self.debate_roles.get(speaker_id, ""),
                "side": self.agent_sides.get(speaker_id, ""),
                "source": "post",
            }

        claim_structure = dict(analysis.get("claim_structure") or {})
        if speaker_id and claim_structure:
            self.open_claim_structures.append(
                {
                    "agent_id": speaker_id,
                    "post_id": post_id,
                    "structure": claim_structure,
                    "proposition_fingerprint": proposition_fingerprint,
                }
            )
            if len(self.open_claim_structures) > 20:
                self.open_claim_structures.pop(0)

        aligned_side = str(analysis.get("aligned_side", "")).strip()
        if stance == "shift" and aligned_side and aligned_side != self.agent_sides.get(speaker_id, ""):
            self.register_shift(
                speaker_id,
                aligned_side,
                post_id=post_id,
                summary=str(content).strip(),
            )

        self._sync_open_attacks_from_claims()

    def _mark_claim_answered(self, claim_id: str, answered_by_post_id: int) -> None:
        claim = self.claims.get(claim_id)
        if not claim:
            return
        claim["status"] = "answered"
        claim["answered_by_post_id"] = answered_by_post_id

    def _sync_open_attacks_from_claims(self) -> None:
        mirrored: list[tuple[str, str, str]] = []
        for claim_id in self.claim_order:
            claim = self.claims.get(claim_id)
            if not claim or claim.get("status") != "open":
                continue
            attacker_id = str(claim.get("speaker_id", "")).strip()
            target_agent_id = str(claim.get("target_agent_id", "")).strip()
            if not attacker_id or not target_agent_id:
                continue
            mirrored.append((attacker_id, str(claim.get("snippet", ""))[:60], target_agent_id))
        self.open_attacks = mirrored[-8:]

    def _normalize_subquestion_terms(self, text: str, terms: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in [*terms, *CONTRACT_TOKEN_PATTERN.findall(text or "")]:
            token = str(raw).strip().lower()
            if len(token) < 2 or token in normalized:
                continue
            normalized.append(token)
        return normalized[:6]

    def _find_matching_open_subquestion(
        self,
        *,
        target_agent_id: str,
        text: str,
        terms: list[str],
    ) -> str | None:
        candidate_terms = set(self._normalize_subquestion_terms(text, terms))
        candidate_text = str(text).strip()
        if not candidate_terms and not candidate_text:
            return None

        for subquestion_id in reversed(self.subquestion_order[-12:]):
            subquestion = self.subquestions.get(subquestion_id)
            if not subquestion or subquestion.get("status") != "open":
                continue
            if str(subquestion.get("target_agent_id", "")).strip() != target_agent_id:
                continue

            existing_terms = set(
                self._normalize_subquestion_terms(
                    str(subquestion.get("text", "")),
                    [str(term) for term in subquestion.get("terms", [])],
                )
            )
            if candidate_terms and existing_terms:
                overlap = len(candidate_terms & existing_terms) / max(min(len(candidate_terms), len(existing_terms)), 1)
                if overlap >= 0.6:
                    return subquestion_id

            existing_text = str(subquestion.get("text", "")).strip()
            if candidate_text and existing_text and candidate_text[:80] == existing_text[:80]:
                return subquestion_id
        return None

    def _update_internal_states(self, speaker_id: str, target_id: str | None) -> None:
        if not target_id:
            return
        anger_out = self.anger.get((speaker_id, target_id), 0)
        anger_in = self.anger.get((target_id, speaker_id), 0)
        if anger_out >= 3:
            self.internal_states[speaker_id] = "anger"
        elif anger_in >= 3:
            self.internal_states[speaker_id] = "contempt"
        elif anger_out >= 2 and self.internal_states.get(speaker_id) == "neutral":
            self.internal_states[speaker_id] = "obsession"


__all__ = ["DebateState"]
