from __future__ import annotations

from typing import Any

from engine.debate_state_support import (
    CLAIM_STALE_AFTER_POSTS,
    CONTRACT_TOKEN_PATTERN,
    DEFINITION_STALE_AFTER_POSTS,
)


class DebateStateControlMixin:
    def pop_retaliator(self, participant_ids: list[str], excluded: set[str], last_speaker: str) -> str | None:
        for agent_id in reversed(self.retaliation_queue):
            if agent_id in participant_ids and agent_id not in excluded and agent_id != last_speaker:
                self.retaliation_queue.remove(agent_id)
                return agent_id
        return None

    def set_topic_axes(self, axes: list[str]) -> None:
        self.topic_axes = axes

    def set_debate_roles(self, roles: dict[str, str]) -> None:
        self.debate_roles = roles

    def set_debate_frame(self, frame: dict[str, Any], assignments: dict[str, dict[str, Any]]) -> None:
        self.debate_frame = {
            "proposition": str(frame.get("proposition", "")),
            "support_label": str(frame.get("support_label", "")),
            "oppose_label": str(frame.get("oppose_label", "")),
            "conditional_label": str(frame.get("conditional_label", "")),
            "support_thesis": str(frame.get("support_thesis", "")),
            "oppose_thesis": str(frame.get("oppose_thesis", "")),
        }
        self.agent_sides = {}
        self.camp_functions = {}
        self.side_contracts = {}
        for agent_id, payload in assignments.items():
            side = str(payload.get("side", "")).strip()
            if side not in {"support", "oppose", "conditional"}:
                continue
            self.agent_sides[str(agent_id)] = side
            role = str(payload.get("role") or {"support": "pro", "oppose": "con", "conditional": "neutral"}[side])
            self.debate_roles[str(agent_id)] = role
            thesis = str(payload.get("thesis", "")).strip()
            camp_function = str(payload.get("camp_function", "")).strip()
            keywords = [str(term).strip() for term in payload.get("keywords", []) if str(term).strip()]
            if not keywords:
                keywords = CONTRACT_TOKEN_PATTERN.findall(thesis)[:8]
            self.side_contracts[str(agent_id)] = {
                "side": side,
                "role": role,
                "thesis": thesis,
                "keywords": keywords[:8],
                "camp_function": camp_function,
            }
            if camp_function:
                self.camp_functions[str(agent_id)] = camp_function
            existing_anchor = self.position_anchors.get(str(agent_id), {})
            if not existing_anchor:
                self.position_anchors[str(agent_id)] = {
                    "post_id": 0,
                    "summary": thesis[:140],
                    "fingerprint": "",
                    "terms": keywords[:6],
                    "axis": "",
                    "role": role,
                    "side": side,
                    "source": "contract",
                }

    def register_shift(self, agent_id: str, new_side: str, *, post_id: int, summary: str) -> None:
        if new_side not in {"support", "oppose", "conditional"}:
            return
        history = self.shift_history.setdefault(agent_id, [])
        history.append(
            {"post_id": int(post_id), "from": self.agent_sides.get(agent_id, ""), "to": new_side, "summary": summary[:140]}
        )
        if len(history) > 5:
            history.pop(0)
        self.agent_sides[agent_id] = new_side
        role = {"support": "pro", "oppose": "con", "conditional": "neutral"}[new_side]
        self.debate_roles[agent_id] = role
        contract = self.side_contracts.setdefault(agent_id, {})
        contract["side"] = new_side
        contract["role"] = role

    def push_axis_assignments(self, assignments: list[tuple[str, str]]) -> None:
        self.forced_axis_queue.extend(assignments)
        if len(self.forced_axis_queue) > 10:
            self.forced_axis_queue = self.forced_axis_queue[-10:]

    def pop_forced_axis(self, agent_id: str) -> str | None:
        for index, (assigned_agent_id, axis) in enumerate(self.forced_axis_queue):
            if assigned_agent_id == agent_id:
                self.forced_axis_queue.pop(index)
                return axis
        return None

    def push_directive(self, agent_id: str, directive: str) -> None:
        queue = self.agent_directives.setdefault(agent_id, [])
        if len(queue) < 3:
            queue.append(directive)

    def pop_directive(self, agent_id: str) -> str | None:
        queue = self.agent_directives.get(agent_id)
        return queue.pop(0) if queue else None

    def push_followup_assignments(self, assignments: list[dict[str, Any]]) -> None:
        for item in assignments:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id", "")).strip()
            subquestion_id = str(item.get("subquestion_id", "")).strip()
            if not agent_id or not subquestion_id:
                continue
            self.followup_assignments.append(
                {
                    "agent_id": agent_id,
                    "subquestion_id": subquestion_id,
                    "text": str(item.get("text", "")).strip(),
                    "camp_function": str(item.get("camp_function", "")).strip(),
                    "status": "open",
                }
            )
        if len(self.followup_assignments) > 20:
            self.followup_assignments = self.followup_assignments[-20:]

    def age_obligations(self, current_post_id: int) -> None:
        if current_post_id <= 0:
            return
        self.last_seen_post_id = max(self.last_seen_post_id, int(current_post_id))
        for claim in self.claims.values():
            if claim.get("status") != "open":
                continue
            created = int(claim.get("created_post_id") or claim.get("post_id") or current_post_id)
            if current_post_id - created > CLAIM_STALE_AFTER_POSTS:
                claim["status"] = "stale"
        for payload in self.definition_requests.values():
            if payload.get("status") != "open":
                continue
            created = int(payload.get("created_post_id") or payload.get("requested_post_id") or current_post_id)
            if current_post_id - created > DEFINITION_STALE_AFTER_POSTS:
                payload["status"] = "stale"
        for subquestion in self.subquestions.values():
            if subquestion.get("status") != "open":
                continue
            created = int(subquestion.get("created_post_id") or subquestion.get("post_id") or current_post_id)
            if current_post_id - created > CLAIM_STALE_AFTER_POSTS:
                subquestion["status"] = "stale"
        for item in self.followup_assignments:
            subquestion = self.subquestions.get(str(item.get("subquestion_id", "")))
            if item.get("status") != "open":
                continue
            if not subquestion or subquestion.get("status") != "open":
                item["status"] = "resolved"
        self._sync_open_attacks_from_claims()

    def _deepen_axis(self, axis: str, debate_fn: str, stance: str) -> None:
        current = self.axis_depth.get(axis, "introduced")
        if current == "synthesized":
            return
        if debate_fn == "attack":
            if current == "introduced":
                self.axis_depth[axis] = "contested"
            elif current == "contested":
                count = self.axis_attack_count.get(axis, 0) + 1
                self.axis_attack_count[axis] = count
                if count >= 2:
                    self.axis_depth[axis] = "rebutted"
        elif debate_fn == "steelman":
            if current == "introduced":
                self.axis_depth[axis] = "contested"
        elif debate_fn == "synthesize" and current in {"contested", "rebutted"}:
            self.axis_depth[axis] = "synthesized"

    def set_facilitator_constraint(
        self,
        constraint: str,
        turns: int = 2,
        kind: str = "",
        schema: dict[str, Any] | None = None,
    ) -> None:
        self.active_constraint = constraint
        self.active_constraint_kind = kind
        self.active_constraint_schema = dict(schema or {})
        self.constraint_turns = turns

    def consume_constraint(self) -> tuple[str, str]:
        result, kind = self.peek_constraint()
        if not result:
            return ("", "")
        self.constraint_turns -= 1
        if self.constraint_turns <= 0:
            self.active_constraint = ""
            self.active_constraint_kind = ""
            self.active_constraint_schema = {}
            self.constraint_turns = 0
        return (result, kind)

    def record_proposition(self, agent_id: str, prop_fp: str) -> int:
        propositions = self.camp_proposition_map.setdefault(agent_id, [])
        propositions.append(prop_fp)
        return propositions.count(prop_fp)
