from __future__ import annotations

import random
from collections import Counter
from typing import Any


class DebateStateQueryMixin:
    # Internal state and arsenal queries.
    def get_internal_state(self, speaker_id: str) -> str:
        return self.internal_states.get(speaker_id, "neutral")

    def is_stance_drifting(self, speaker_id: str) -> bool:
        history = self.stance_history.get(speaker_id, [])
        if len(history) < 3:
            return False
        soft_stances = {"agree", "supplement"}
        return all(s in soft_stances for s in history[-3:])

    def has_unused_arsenal(self, speaker_id: str, persona: dict[str, Any]) -> bool:
        all_ids = {a["id"] for a in persona.get("argument_arsenal", [])}
        used = self.used_arsenal_ids.get(speaker_id, set())
        return bool(all_ids - used)

    def get_available_arsenal(self, speaker_id: str, persona: dict[str, Any]) -> list[dict[str, Any]]:
        arsenal: list[dict[str, Any]] = persona.get("argument_arsenal", [])
        cooldowns = self.arsenal_cooldowns.get(speaker_id, {})
        return [a for a in arsenal if cooldowns.get(a["id"], 0) == 0]

    def get_arsenal_cooldown_for_id(self, persona: dict[str, Any], arg_id: str) -> int:
        for a in persona.get("argument_arsenal", []):
            if a["id"] == arg_id:
                return int(a.get("cooldown", 3))
        return 3

    def is_function_overused(self, fn: str) -> bool:
        if len(self.recent_functions) < 4:
            return False
        return self.recent_functions[-5:].count(fn) >= 3

    def is_function_stagnating(self) -> bool:
        if len(self.recent_functions) < 4:
            return False
        counts = Counter(self.recent_functions[-5:])
        return counts.most_common(1)[0][1] >= 4

    def get_anger(self, attacker_id: str, target_id: str) -> int:
        return self.anger.get((attacker_id, target_id), 0)

    def total_anger(self, attacker_id: str) -> int:
        return sum(v for (a, _), v in self.anger.items() if a == attacker_id)

    def get_aggression_boost(self, speaker_id: str, target_id: str | None) -> str | None:
        if not target_id:
            return None
        anger = self.get_anger(speaker_id, target_id)
        state = self.get_internal_state(speaker_id)
        if anger >= 3 or state == "anger":
            return random.choice(["attack", "attack", "steelman"])
        if anger >= 2 or state == "contempt":
            return random.choice(["attack", "steelman", "concretize"])
        return None

    def is_echo_chamber(self) -> bool:
        if len(self.recent_axes) < 5:
            return False
        return len(set(self.recent_axes[-5:])) == 1

    def get_agent_recent_axes(self, agent_id: str) -> list[str]:
        return self.agent_axis_usage.get(agent_id, [])

    def get_uncovered_axes(self) -> list[str]:
        recent_global = set(self.recent_axes[-10:])
        return [a for a in self.topic_axes if a not in recent_global]

    def axes_initialized(self) -> bool:
        return bool(self.topic_axes)

    def get_debate_role(self, agent_id: str) -> str:
        return self.debate_roles.get(agent_id, "")

    def roles_initialized(self) -> bool:
        return bool(self.debate_roles)

    def get_debate_frame(self) -> dict[str, Any]:
        return dict(self.debate_frame)

    def get_agent_side(self, agent_id: str | None) -> str:
        if not agent_id:
            return ""
        return self.agent_sides.get(agent_id, "")

    def get_side_contract(self, agent_id: str) -> dict[str, Any]:
        return dict(self.side_contracts.get(agent_id, {}))

    def get_camp_function(self, agent_id: str | None) -> str:
        if not agent_id:
            return ""
        return self.camp_functions.get(agent_id, "")

    def get_opposing_side(self, agent_id: str) -> str:
        side = self.get_agent_side(agent_id)
        if side == "support":
            return "oppose"
        if side == "oppose":
            return "support"
        return ""

    # Directive and attack queries.
    def peek_forced_axis(self, agent_id: str) -> str | None:
        for aid, axis in self.forced_axis_queue:
            if aid == agent_id:
                return axis
        return None

    def has_directive(self, agent_id: str) -> bool:
        return bool(self.agent_directives.get(agent_id))

    def peek_directive(self, agent_id: str) -> str | None:
        queue = self.agent_directives.get(agent_id)
        return queue[0] if queue else None

    def has_open_attack_against(self, agent_id: str) -> bool:
        return any(t == agent_id for (_, _, t) in self.open_attacks)

    def has_any_open_attacks(self) -> bool:
        return bool(self.open_attacks)

    def get_strongest_open_attack(self, agent_id: str) -> tuple[str, str] | None:
        for attacker_id, snippet, target in reversed(self.open_attacks):
            if target == agent_id:
                return (attacker_id, snippet)
        return None

    def count_open_claims(self) -> int:
        return sum(1 for claim in self.claims.values() if claim.get("status") == "open")

    # Claim, definition, and subquestion queries.
    def _open_definition_requests_for(self, agent_id: str) -> list[dict[str, Any]]:
        return [
            request for request in self.definition_requests.values()
            if request.get("status") == "open"
            and request.get("requested_by") != agent_id
            and request.get("target_agent_id") in {None, "", agent_id}
        ]

    def _open_claims_for(self, agent_id: str) -> list[dict[str, Any]]:
        open_claims: list[dict[str, Any]] = []
        for claim_id in reversed(self.claim_order):
            claim = self.claims.get(claim_id)
            if not claim:
                continue
            if claim.get("status") == "open" and claim.get("target_agent_id") == agent_id:
                open_claims.append(claim)
        return open_claims

    def get_definition_priority_post_id_for(self, agent_id: str) -> int | None:
        open_requests = self._open_definition_requests_for(agent_id)
        if not open_requests:
            return None
        latest = max(open_requests, key=lambda item: int(item.get("requested_post_id") or 0))
        requested_post_id = latest.get("requested_post_id")
        return int(requested_post_id) if requested_post_id is not None else None

    def has_pending_definition_response(self, agent_id: str) -> bool:
        return self.get_definition_priority_post_id_for(agent_id) is not None

    def get_priority_post_id_for(self, agent_id: str) -> int | None:
        priority_subquestion_post_id = self.get_priority_subquestion_post_id_for(agent_id)
        if priority_subquestion_post_id is not None:
            return priority_subquestion_post_id
        open_claims = self._open_claims_for(agent_id)
        if open_claims:
            opposing_side = self.get_opposing_side(agent_id)
            if opposing_side:
                for claim in open_claims:
                    if self.get_agent_side(str(claim.get("speaker_id", ""))) == opposing_side:
                        return int(claim["post_id"])
            return int(open_claims[0]["post_id"])
        return self.get_definition_priority_post_id_for(agent_id)

    def get_priority_subquestion_for(self, agent_id: str) -> dict[str, Any] | None:
        for item in reversed(self.followup_assignments):
            if item.get("status") != "open" or item.get("agent_id") != agent_id:
                continue
            subquestion = self.subquestions.get(str(item.get("subquestion_id", "")))
            if subquestion and subquestion.get("status") == "open":
                return dict(subquestion)
        for subquestion_id in reversed(self.subquestion_order):
            subquestion = self.subquestions.get(subquestion_id)
            if not subquestion or subquestion.get("status") != "open":
                continue
            if subquestion.get("target_agent_id") == agent_id:
                return dict(subquestion)
        return None

    def get_priority_subquestion_post_id_for(self, agent_id: str) -> int | None:
        subquestion = self.get_priority_subquestion_for(agent_id)
        if not subquestion:
            return None
        post_id = subquestion.get("post_id")
        return int(post_id) if post_id is not None else None

    def get_claim_units_for_post(self, post_id: int | None) -> list[dict[str, Any]]:
        if post_id is None:
            return []
        units: list[dict[str, Any]] = []
        for claim_id in self.claim_order:
            claim = self.claims.get(claim_id)
            if not claim or int(claim.get("parent_post_id") or -1) != int(post_id):
                continue
            units.append(
                {
                    "claim_id": claim_id,
                    "claim_key": str(claim.get("claim_key", "")),
                    "text": str(claim.get("claim_text", "") or claim.get("snippet", "")),
                    "terms": [str(term) for term in claim.get("terms", [])],
                }
            )
        return units

    def get_subquestion_for_post(self, post_id: int | None) -> dict[str, Any]:
        if post_id is None:
            return {}
        for subquestion_id in reversed(self.subquestion_order):
            subquestion = self.subquestions.get(subquestion_id)
            if not subquestion:
                continue
            if int(subquestion.get("post_id") or -1) == int(post_id):
                return dict(subquestion)
        return {}

    def get_unresolved_terms(self) -> list[str]:
        open_terms = [
            term for term, payload in self.definition_requests.items()
            if payload.get("status") == "open"
        ]
        return sorted(open_terms)

    def get_shallow_axes(self) -> list[str]:
        discussed = {axis for axes in self.agent_axis_usage.values() for axis in axes}
        return [
            axis for axis in self.topic_axes
            if axis in discussed and self.axis_depth.get(axis, "introduced") == "introduced"
        ]

    # Constraint and anchor queries.
    def peek_constraint_kind(self) -> str:
        return self.active_constraint_kind if self.constraint_turns > 0 else ""

    def peek_constraint(self) -> tuple[str, str]:
        if not self.active_constraint or self.constraint_turns <= 0:
            return ("", "")
        return (self.active_constraint, self.active_constraint_kind)

    def peek_constraint_schema(self) -> dict[str, Any]:
        if not self.active_constraint or self.constraint_turns <= 0:
            return {}
        return dict(self.active_constraint_schema)

    def get_position_anchor(self, agent_id: str) -> dict[str, Any]:
        return dict(self.position_anchors.get(agent_id, {}))

    def check_camp_reassert(self, agent_id: str, prop_fp: str, threshold: int = 3) -> bool:
        propositions = self.camp_proposition_map.get(agent_id, [])
        return propositions.count(prop_fp) >= threshold
