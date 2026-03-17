from __future__ import annotations

import random
import re
from typing import Any

_CLAIM_STALE_AFTER_POSTS = 8
_DEFINITION_STALE_AFTER_POSTS = 10
_CONTRACT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]{2,24}", re.UNICODE)


class DebateState:
    """In-memory debate dynamics: anger/contempt/obsession, retaliation, arsenal cooldowns."""

    def __init__(self) -> None:
        # (attacker_id, target_id) -> number of attacks
        self.anger: dict[tuple[str, str], int] = {}
        # Recently attacked agent_ids queued for retaliation (oldest first)
        self.retaliation_queue: list[str] = []
        # Tracks recent axes for echo chamber detection
        self.recent_axes: list[str] = []
        # Per-agent internal state: "neutral" | "anger" | "contempt" | "obsession"
        self.internal_states: dict[str, str] = {}
        # arsenal_cooldowns[speaker_id][arg_id] = remaining posts until usable
        self.arsenal_cooldowns: dict[str, dict[str, int]] = {}
        # Recent debate functions used (last 6), for overuse detection
        self.recent_functions: list[str] = []
        # Per-agent stance history: last 5 stances (agree/disagree/supplement/shift)
        self.stance_history: dict[str, list[str]] = {}
        # Per-agent set of used arsenal IDs (ever used, for novelty boost)
        self.used_arsenal_ids: dict[str, set[str]] = {}
        # Debate role assignment: agent_id -> "pro" | "con" | "neutral"
        self.debate_roles: dict[str, str] = {}
        # Binary frame for the thread and per-agent side assignment
        self.debate_frame: dict[str, Any] = {}
        self.agent_sides: dict[str, str] = {}
        self.camp_functions: dict[str, str] = {}
        self.side_contracts: dict[str, dict[str, Any]] = {}
        self.shift_history: dict[str, list[dict[str, Any]]] = {}
        # Facilitator-assigned forced axis queue: [(agent_id, axis), ...]
        self.forced_axis_queue: list[tuple[str, str]] = []
        # Evaluation axes decomposed from thread topic (set once at start)
        self.topic_axes: list[str] = []
        # Per-agent axis usage history (last 4 axes per agent)
        self.agent_axis_usage: dict[str, list[str]] = {}
        # Hidden director: per-agent private directive queue (not shown to frontend)
        self.agent_directives: dict[str, list[str]] = {}
        # Open attacks: unanswered attacks — (attacker_id, content_snippet, target_id)
        self.open_attacks: list[tuple[str, str, str]] = []
        # Per-agent agreement streak (consecutive agree/supplement count)
        self.agreement_streak: dict[str, int] = {}
        # Axis depth: axis -> "introduced"|"contested"|"rebutted"|"synthesized"
        self.axis_depth: dict[str, str] = {}
        # Per-axis attack count (increments only on "attack" function, not steelman)
        self.axis_attack_count: dict[str, int] = {}
        # Facilitator active constraint: declared "next N posts must X"
        self.active_constraint: str = ""
        self.active_constraint_kind: str = ""
        self.active_constraint_schema: dict[str, Any] = {}
        self.constraint_turns: int = 0
        # Semantic control: open claims / definition requests / novelty memory
        self.claims: dict[str, dict[str, Any]] = {}
        self.claim_order: list[str] = []
        self.definition_requests: dict[str, dict[str, Any]] = {}
        self.subquestions: dict[str, dict[str, Any]] = {}
        self.subquestion_order: list[str] = []
        self.followup_assignments: list[dict[str, Any]] = []
        self.recent_argument_fingerprints: list[str] = []
        self.recent_example_keys: list[str] = []
        # Per-agent first committed line in this thread, used to resist silent stance inversion
        self.position_anchors: dict[str, dict[str, Any]] = {}
        self.last_seen_post_id: int = 0
        # Subquestions seeded at thread start (list of strings)
        self.thread_subquestions: list[str] = []
        # Camp reassertion tracking: agent_id -> list of proposition fingerprints used
        self.camp_proposition_map: dict[str, list[str]] = {}
        # Active alerts (e.g. "camp_reassert")
        self.alerts: set[str] = set()
        # Abstract terms extracted from topic for Phase 1 definitions
        self.abstract_terms: list[str] = []
        # Open claim structures: list of {agent_id, post_id, structure}
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

        # Update internal states (style only — not used for content control)
        self._update_internal_states(speaker_id, target_agent)

        # Track open attacks: attack/steelman directed at another agent → unanswered
        # Track agreement streak (for stance drift scoring)
        if stance in {"agree", "supplement"}:
            self.agreement_streak[speaker_id] = self.agreement_streak.get(speaker_id, 0) + 1
        else:
            self.agreement_streak[speaker_id] = 0

        # Global axis tracking
        if focus_axis:
            self.recent_axes.append(focus_axis)
            self._deepen_axis(focus_axis, debate_function, stance)
        if len(self.recent_axes) > 8:
            self.recent_axes.pop(0)

        # Per-agent axis tracking
        if focus_axis and speaker_id:
            agent_axes = self.agent_axis_usage.setdefault(speaker_id, [])
            agent_axes.append(focus_axis)
            if len(agent_axes) > 4:
                agent_axes.pop(0)

        # Debate function tracking
        if debate_function:
            self.recent_functions.append(debate_function)
        if len(self.recent_functions) > 6:
            self.recent_functions.pop(0)

        # Stance history tracking
        if stance and speaker_id:
            history = self.stance_history.setdefault(speaker_id, [])
            history.append(stance)
            if len(history) > 5:
                history.pop(0)

        # Decrement all active cooldowns
        for agent_cooldowns in self.arsenal_cooldowns.values():
            for arg_id in list(agent_cooldowns):
                if agent_cooldowns[arg_id] > 0:
                    agent_cooldowns[arg_id] -= 1

        # Apply cooldown for the arsenal item that was just used
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
        if fingerprint:
            self.recent_argument_fingerprints.append(fingerprint)
            if len(self.recent_argument_fingerprints) > 12:
                self.recent_argument_fingerprints.pop(0)

        for example_key in [str(v).strip() for v in analysis.get("example_keys", [])]:
            if not example_key:
                continue
            self.recent_example_keys.append(example_key)
            if len(self.recent_example_keys) > 12:
                self.recent_example_keys.pop(0)

        for term in [str(v).strip() for v in analysis.get("definition_requests", [])]:
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

        for term in [str(v).strip() for v in analysis.get("definition_terms", [])]:
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

        for answered_claim_id in [str(v).strip() for v in analysis.get("answered_claim_ids", [])]:
            self._mark_claim_answered(answered_claim_id, post_id)
        for answered_post_id in [int(v) for v in analysis.get("answered_post_ids", [])]:
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
            for idx, unit in enumerate(claim_units):
                claim_id = f"claim:{post_id}:{idx}"
                self.claims[claim_id] = {
                    "claim_id": claim_id,
                    "claim_key": str(unit.get("claim_key", "")) or f"claim:{post_id}:{idx}",
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
            for idx, unit in enumerate(claim_units[:2]):
                subquestion_id = f"sq:{post_id}:{idx}"
                self.subquestions[subquestion_id] = {
                    "subquestion_id": subquestion_id,
                    "text": str(unit.get("text", ""))[:120] or str(content).strip()[:120],
                    "terms": [str(term) for term in unit.get("terms", [])][:5],
                    "post_id": post_id,
                    "target_agent_id": target_agent,
                    "speaker_id": speaker_id,
                    "camp_function": camp_function,
                    "side": side,
                    "status": "open",
                    "created_post_id": post_id,
                }
                self.subquestion_order.append(subquestion_id)
                if len(self.subquestion_order) > 40:
                    stale_id = self.subquestion_order.pop(0)
                    self.subquestions.pop(stale_id, None)

        if speaker_id and (
            speaker_id not in self.position_anchors
            or int(self.position_anchors.get(speaker_id, {}).get("post_id") or 0) <= 0
        ):
            referenced_terms = [
                str(term) for term in analysis.get("referenced_terms", [])
                if str(term).strip()
            ]
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

    def _update_internal_states(self, speaker_id: str, target_id: str | None) -> None:
        if not target_id:
            return
        anger_out = self.anger.get((speaker_id, target_id), 0)
        anger_in = self.anger.get((target_id, speaker_id), 0)
        if anger_out >= 3:
            self.internal_states[speaker_id] = "anger"
        elif anger_in >= 3:
            # Being repeatedly attacked → speaker develops contempt
            self.internal_states[speaker_id] = "contempt"
        elif anger_out >= 2 and self.internal_states.get(speaker_id) == "neutral":
            self.internal_states[speaker_id] = "obsession"

    def get_internal_state(self, speaker_id: str) -> str:
        return self.internal_states.get(speaker_id, "neutral")

    def is_stance_drifting(self, speaker_id: str) -> bool:
        """True if the agent has been agreeing/supplementing too much recently."""
        history = self.stance_history.get(speaker_id, [])
        if len(history) < 3:
            return False
        soft_stances = {"agree", "supplement"}
        return all(s in soft_stances for s in history[-3:])

    def has_unused_arsenal(self, speaker_id: str, persona: dict[str, Any]) -> bool:
        """True if the agent has arsenal items they have never used."""
        all_ids = {a["id"] for a in persona.get("argument_arsenal", [])}
        used = self.used_arsenal_ids.get(speaker_id, set())
        return bool(all_ids - used)

    def get_available_arsenal(self, speaker_id: str, persona: dict[str, Any]) -> list[dict[str, Any]]:
        """Return arsenal items not currently on cooldown."""
        arsenal: list[dict[str, Any]] = persona.get("argument_arsenal", [])
        cooldowns = self.arsenal_cooldowns.get(speaker_id, {})
        return [a for a in arsenal if cooldowns.get(a["id"], 0) == 0]

    def get_arsenal_cooldown_for_id(self, persona: dict[str, Any], arg_id: str) -> int:
        """Look up the configured cooldown for an arsenal item."""
        for a in persona.get("argument_arsenal", []):
            if a["id"] == arg_id:
                return int(a.get("cooldown", 3))
        return 3

    def is_function_overused(self, fn: str) -> bool:
        """True if this debate function appeared 3+ times in the last 5 posts."""
        if len(self.recent_functions) < 4:
            return False
        return self.recent_functions[-5:].count(fn) >= 3

    def is_function_stagnating(self) -> bool:
        """True if the same debate function dominates the last 5 posts."""
        if len(self.recent_functions) < 4:
            return False
        from collections import Counter
        counts = Counter(self.recent_functions[-5:])
        return counts.most_common(1)[0][1] >= 4

    def get_anger(self, attacker_id: str, target_id: str) -> int:
        return self.anger.get((attacker_id, target_id), 0)

    def total_anger(self, attacker_id: str) -> int:
        return sum(v for (a, _), v in self.anger.items() if a == attacker_id)

    def pop_retaliator(self, participant_ids: list[str], excluded: set[str], last_speaker: str) -> str | None:
        for agent_id in reversed(self.retaliation_queue):
            if agent_id in participant_ids and agent_id not in excluded and agent_id != last_speaker:
                self.retaliation_queue.remove(agent_id)
                return agent_id
        return None

    def get_aggression_boost(self, speaker_id: str, target_id: str | None) -> str | None:
        """Return a debate_function override based on anger level, or None."""
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

    # ── Topic axes ───────────────────────────────────────────────────────────

    def set_topic_axes(self, axes: list[str]) -> None:
        self.topic_axes = axes

    def get_agent_recent_axes(self, agent_id: str) -> list[str]:
        return self.agent_axis_usage.get(agent_id, [])

    def get_uncovered_axes(self) -> list[str]:
        """Return topic axes not recently argued by anyone (last ~10 posts)."""
        recent_global = set(self.recent_axes[-10:])
        return [a for a in self.topic_axes if a not in recent_global]

    def axes_initialized(self) -> bool:
        return bool(self.topic_axes)

    # ── Role assignment ──────────────────────────────────────────────────────

    def set_debate_roles(self, roles: dict[str, str]) -> None:
        self.debate_roles = roles

    def get_debate_role(self, agent_id: str) -> str:
        return self.debate_roles.get(agent_id, "")

    def roles_initialized(self) -> bool:
        return bool(self.debate_roles)

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
            keywords = [
                str(term).strip()
                for term in payload.get("keywords", [])
                if str(term).strip()
            ]
            if not keywords:
                keywords = _CONTRACT_TOKEN_PATTERN.findall(thesis)[:8]
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

    def register_shift(self, agent_id: str, new_side: str, *, post_id: int, summary: str) -> None:
        if new_side not in {"support", "oppose", "conditional"}:
            return
        history = self.shift_history.setdefault(agent_id, [])
        history.append({"post_id": int(post_id), "from": self.agent_sides.get(agent_id, ""), "to": new_side, "summary": summary[:140]})
        if len(history) > 5:
            history.pop(0)
        self.agent_sides[agent_id] = new_side
        role = {"support": "pro", "oppose": "con", "conditional": "neutral"}[new_side]
        self.debate_roles[agent_id] = role
        contract = self.side_contracts.setdefault(agent_id, {})
        contract["side"] = new_side
        contract["role"] = role

    # ── Forced axis queue (set by facilitator rerail) ────────────────────────

    def push_axis_assignments(self, assignments: list[tuple[str, str]]) -> None:
        """Queue [(agent_id, axis), ...] from facilitator rerail."""
        self.forced_axis_queue.extend(assignments)
        if len(self.forced_axis_queue) > 10:
            self.forced_axis_queue = self.forced_axis_queue[-10:]

    def pop_forced_axis(self, agent_id: str) -> str | None:
        """Return and remove the next forced axis for this agent, if any."""
        for i, (aid, axis) in enumerate(self.forced_axis_queue):
            if aid == agent_id:
                self.forced_axis_queue.pop(i)
                return axis
        return None

    def peek_forced_axis(self, agent_id: str) -> str | None:
        for aid, axis in self.forced_axis_queue:
            if aid == agent_id:
                return axis
        return None

    # ── Hidden director directives ───────────────────────────────────────────

    def push_directive(self, agent_id: str, directive: str) -> None:
        """Queue a private instruction for an agent (not shown to frontend)."""
        queue = self.agent_directives.setdefault(agent_id, [])
        if len(queue) < 3:  # cap to prevent stale pile-up
            queue.append(directive)

    def pop_directive(self, agent_id: str) -> str | None:
        """Return and remove the next private directive for this agent."""
        queue = self.agent_directives.get(agent_id)
        return queue.pop(0) if queue else None

    def has_directive(self, agent_id: str) -> bool:
        return bool(self.agent_directives.get(agent_id))

    def peek_directive(self, agent_id: str) -> str | None:
        queue = self.agent_directives.get(agent_id)
        return queue[0] if queue else None

    # ── Open attacks (unanswered) ─────────────────────────────────────────────

    def has_open_attack_against(self, agent_id: str) -> bool:
        return any(t == agent_id for (_, _, t) in self.open_attacks)

    def has_any_open_attacks(self) -> bool:
        return bool(self.open_attacks)

    def get_strongest_open_attack(self, agent_id: str) -> tuple[str, str] | None:
        """Return (attacker_id, content_snippet) of the most recent unanswered attack against agent_id."""
        for attacker_id, snippet, target in reversed(self.open_attacks):
            if target == agent_id:
                return (attacker_id, snippet)
        return None

    def count_open_claims(self) -> int:
        return sum(1 for claim in self.claims.values() if claim.get("status") == "open")

    def get_definition_priority_post_id_for(self, agent_id: str) -> int | None:
        open_requests = [
            request for request in self.definition_requests.values()
            if request.get("status") == "open"
            and request.get("requested_by") != agent_id
            and request.get("target_agent_id") in {None, "", agent_id}
        ]
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
        open_claims: list[dict[str, Any]] = []
        for claim_id in reversed(self.claim_order):
            claim = self.claims.get(claim_id)
            if not claim:
                continue
            if claim.get("status") == "open" and claim.get("target_agent_id") == agent_id:
                open_claims.append(claim)
        if open_claims:
            opposing_side = self.get_opposing_side(agent_id)
            if opposing_side:
                for claim in open_claims:
                    if self.get_agent_side(str(claim.get("speaker_id", ""))) == opposing_side:
                        return int(claim["post_id"])
            return int(open_claims[0]["post_id"])
        return self.get_definition_priority_post_id_for(agent_id)

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

    def age_obligations(self, current_post_id: int) -> None:
        if current_post_id <= 0:
            return
        self.last_seen_post_id = max(self.last_seen_post_id, int(current_post_id))
        for claim in self.claims.values():
            if claim.get("status") != "open":
                continue
            created = int(claim.get("created_post_id") or claim.get("post_id") or current_post_id)
            if current_post_id - created > _CLAIM_STALE_AFTER_POSTS:
                claim["status"] = "stale"
        for payload in self.definition_requests.values():
            if payload.get("status") != "open":
                continue
            created = int(payload.get("created_post_id") or payload.get("requested_post_id") or current_post_id)
            if current_post_id - created > _DEFINITION_STALE_AFTER_POSTS:
                payload["status"] = "stale"
        for subquestion in self.subquestions.values():
            if subquestion.get("status") != "open":
                continue
            created = int(subquestion.get("created_post_id") or subquestion.get("post_id") or current_post_id)
            if current_post_id - created > _CLAIM_STALE_AFTER_POSTS:
                subquestion["status"] = "stale"
        for item in self.followup_assignments:
            subquestion = self.subquestions.get(str(item.get("subquestion_id", "")))
            if item.get("status") != "open":
                continue
            if not subquestion or subquestion.get("status") != "open":
                item["status"] = "resolved"
        self._sync_open_attacks_from_claims()

    # ── Axis depth (introduced → contested → rebutted → synthesized) ─────────

    def _deepen_axis(self, axis: str, debate_fn: str, stance: str) -> None:
        current = self.axis_depth.get(axis, "introduced")
        if current == "synthesized":
            return
        if debate_fn == "attack":
            if current == "introduced":
                self.axis_depth[axis] = "contested"
            elif current == "contested":
                # Require 2+ distinct attacks to mark as genuinely rebutted
                cnt = self.axis_attack_count.get(axis, 0) + 1
                self.axis_attack_count[axis] = cnt
                if cnt >= 2:
                    self.axis_depth[axis] = "rebutted"
        elif debate_fn == "steelman":
            # steelman contributes to "contested" depth only — not to "rebutted"
            if current == "introduced":
                self.axis_depth[axis] = "contested"
        elif debate_fn == "synthesize" and current in {"contested", "rebutted"}:
            self.axis_depth[axis] = "synthesized"

    def get_shallow_axes(self) -> list[str]:
        """Return topic axes used by at least one agent but not yet contested."""
        discussed = {a for axes in self.agent_axis_usage.values() for a in axes}
        return [
            a for a in self.topic_axes
            if a in discussed and self.axis_depth.get(a, "introduced") == "introduced"
        ]

    # ── Facilitator active constraint ─────────────────────────────────────────

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

    def consume_constraint(self) -> tuple[str, str]:
        """Return active constraint text/kind and decrement counter. Returns ('','') if none."""
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

    def get_position_anchor(self, agent_id: str) -> dict[str, Any]:
        return dict(self.position_anchors.get(agent_id, {}))

    def record_proposition(self, agent_id: str, prop_fp: str) -> int:
        """Record a proposition fingerprint for an agent; return the count of this fp."""
        lst = self.camp_proposition_map.setdefault(agent_id, [])
        lst.append(prop_fp)
        return lst.count(prop_fp)

    def check_camp_reassert(self, agent_id: str, prop_fp: str, threshold: int = 3) -> bool:
        """Return True if this agent has used this prop_fp >= threshold times."""
        lst = self.camp_proposition_map.get(agent_id, [])
        return lst.count(prop_fp) >= threshold

    def to_dict(self) -> dict:
        return {
            "anger": [[k[0], k[1], v] for k, v in self.anger.items()],
            "retaliation_queue": self.retaliation_queue,
            "recent_axes": self.recent_axes,
            "internal_states": self.internal_states,
            "arsenal_cooldowns": self.arsenal_cooldowns,
            "recent_functions": self.recent_functions,
            "stance_history": self.stance_history,
            "used_arsenal_ids": {k: list(v) for k, v in self.used_arsenal_ids.items()},
            "debate_roles": self.debate_roles,
            "debate_frame": self.debate_frame,
            "agent_sides": self.agent_sides,
            "camp_functions": self.camp_functions,
            "side_contracts": self.side_contracts,
            "shift_history": self.shift_history,
            "forced_axis_queue": self.forced_axis_queue,
            "topic_axes": self.topic_axes,
            "agent_axis_usage": self.agent_axis_usage,
            "agent_directives": self.agent_directives,
            "open_attacks": [list(t) for t in self.open_attacks],
            "agreement_streak": self.agreement_streak,
            "axis_depth": self.axis_depth,
            "axis_attack_count": self.axis_attack_count,
            "active_constraint": self.active_constraint,
            "active_constraint_kind": self.active_constraint_kind,
            "active_constraint_schema": self.active_constraint_schema,
            "constraint_turns": self.constraint_turns,
            "claims": self.claims,
            "claim_order": self.claim_order,
            "definition_requests": self.definition_requests,
            "subquestions": self.subquestions,
            "subquestion_order": self.subquestion_order,
            "followup_assignments": self.followup_assignments,
            "recent_argument_fingerprints": self.recent_argument_fingerprints,
            "recent_example_keys": self.recent_example_keys,
            "position_anchors": self.position_anchors,
            "last_seen_post_id": self.last_seen_post_id,
            "thread_subquestions": self.thread_subquestions,
            "camp_proposition_map": self.camp_proposition_map,
            "alerts": list(self.alerts),
            "abstract_terms": self.abstract_terms,
            "open_claim_structures": self.open_claim_structures,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DebateState":
        instance = cls()
        anger_raw = data.get("anger", [])
        if isinstance(anger_raw, list):
            # New format: [[attacker_id, target_id, count], ...]
            for item in anger_raw:
                if isinstance(item, (list, tuple)) and len(item) == 3:
                    instance.anger[(str(item[0]), str(item[1]))] = int(item[2])
        elif isinstance(anger_raw, dict):
            # Legacy format: {"attacker\x00target": count}
            for key_str, v in anger_raw.items():
                parts = key_str.split("\x00", 1)
                if len(parts) == 2:
                    instance.anger[(parts[0], parts[1])] = v
        instance.retaliation_queue = data.get("retaliation_queue", [])
        instance.recent_axes = data.get("recent_axes", [])
        instance.internal_states = data.get("internal_states", {})
        instance.arsenal_cooldowns = {
            agent: dict(cooldowns)
            for agent, cooldowns in data.get("arsenal_cooldowns", {}).items()
        }
        instance.recent_functions = data.get("recent_functions", [])
        instance.stance_history = {k: list(v) for k, v in data.get("stance_history", {}).items()}
        instance.used_arsenal_ids = {
            k: set(v) for k, v in data.get("used_arsenal_ids", {}).items()
        }
        instance.debate_roles = data.get("debate_roles", {})
        instance.debate_frame = {
            str(k): str(v) for k, v in data.get("debate_frame", {}).items()
        }
        instance.agent_sides = {
            str(k): str(v) for k, v in data.get("agent_sides", {}).items()
        }
        instance.camp_functions = {
            str(k): str(v) for k, v in data.get("camp_functions", {}).items()
        }
        instance.side_contracts = {
            str(k): dict(v) for k, v in data.get("side_contracts", {}).items()
            if isinstance(v, dict)
        }
        instance.shift_history = {
            str(k): [dict(item) for item in v if isinstance(item, dict)]
            for k, v in data.get("shift_history", {}).items()
            if isinstance(v, list)
        }
        instance.topic_axes = data.get("topic_axes", [])
        instance.agent_axis_usage = {k: list(v) for k, v in data.get("agent_axis_usage", {}).items()}
        instance.forced_axis_queue = [
            (item[0], item[1]) for item in data.get("forced_axis_queue", [])
            if isinstance(item, (list, tuple)) and len(item) == 2
        ]
        instance.agent_directives = {
            k: list(v) for k, v in data.get("agent_directives", {}).items()
        }
        instance.open_attacks = [
            (str(item[0]), str(item[1]), str(item[2]))
            for item in data.get("open_attacks", [])
            if isinstance(item, (list, tuple)) and len(item) == 3
        ]
        instance.agreement_streak = {k: int(v) for k, v in data.get("agreement_streak", {}).items()}
        instance.axis_depth = {str(k): str(v) for k, v in data.get("axis_depth", {}).items()}
        instance.axis_attack_count = {str(k): int(v) for k, v in data.get("axis_attack_count", {}).items()}
        instance.active_constraint = str(data.get("active_constraint", ""))
        instance.active_constraint_kind = str(data.get("active_constraint_kind", ""))
        instance.active_constraint_schema = {
            str(k): v for k, v in data.get("active_constraint_schema", {}).items()
        }
        instance.constraint_turns = int(data.get("constraint_turns", 0))
        instance.claims = {
            str(k): dict(v) for k, v in data.get("claims", {}).items()
            if isinstance(v, dict)
        }
        instance.claim_order = [str(v) for v in data.get("claim_order", [])]
        instance.definition_requests = {
            str(k): dict(v) for k, v in data.get("definition_requests", {}).items()
            if isinstance(v, dict)
        }
        instance.subquestions = {
            str(k): dict(v) for k, v in data.get("subquestions", {}).items()
            if isinstance(v, dict)
        }
        instance.subquestion_order = [str(v) for v in data.get("subquestion_order", [])]
        instance.followup_assignments = [
            dict(v) for v in data.get("followup_assignments", []) if isinstance(v, dict)
        ]
        instance.recent_argument_fingerprints = [
            str(v) for v in data.get("recent_argument_fingerprints", [])
        ]
        instance.recent_example_keys = [
            str(v) for v in data.get("recent_example_keys", [])
        ]
        instance.position_anchors = {
            str(k): dict(v) for k, v in data.get("position_anchors", {}).items()
            if isinstance(v, dict)
        }
        instance.last_seen_post_id = int(data.get("last_seen_post_id", 0))
        instance.thread_subquestions = [str(v) for v in data.get("thread_subquestions", [])]
        instance.camp_proposition_map = {
            str(k): [str(v) for v in lst]
            for k, lst in data.get("camp_proposition_map", {}).items()
            if isinstance(lst, list)
        }
        instance.alerts = set(str(v) for v in data.get("alerts", []))
        instance.abstract_terms = [str(v) for v in data.get("abstract_terms", [])]
        instance.open_claim_structures = [
            dict(v) for v in data.get("open_claim_structures", []) if isinstance(v, dict)
        ]
        if instance.claims:
            instance._sync_open_attacks_from_claims()
        return instance
