from __future__ import annotations

import random
from typing import Any


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
        # Facilitator active constraint: declared "next N posts must X"
        self.active_constraint: str = ""
        self.constraint_turns: int = 0

    def record_post(
        self,
        speaker_id: str,
        target_post: dict[str, Any],
        focus_axis: str,
        debate_function: str = "attack",
        used_arsenal_id: str | None = None,
        arsenal_cooldown: int = 3,
        stance: str = "disagree",
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
        if debate_function in {"attack", "steelman"} and target_agent and target_agent != speaker_id:
            snippet = str(target_post.get("content", ""))[:60]
            self.open_attacks.append((speaker_id, snippet, target_agent))
            if len(self.open_attacks) > 8:
                self.open_attacks.pop(0)

        # Resolve open attacks: a disagree/shift response clears attacks against the speaker
        if stance in {"disagree", "shift"} and target_agent:
            self.open_attacks = [
                (a, c, t) for (a, c, t) in self.open_attacks if t != speaker_id
            ]

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

    # ── Open attacks (unanswered) ─────────────────────────────────────────────

    def has_open_attack_against(self, agent_id: str) -> bool:
        return any(t == agent_id for (_, _, t) in self.open_attacks)

    def get_strongest_open_attack(self, agent_id: str) -> tuple[str, str] | None:
        """Return (attacker_id, content_snippet) of the most recent unanswered attack against agent_id."""
        for attacker_id, snippet, target in reversed(self.open_attacks):
            if target == agent_id:
                return (attacker_id, snippet)
        return None

    # ── Axis depth (introduced → contested → rebutted → synthesized) ─────────

    def _deepen_axis(self, axis: str, debate_fn: str, stance: str) -> None:
        current = self.axis_depth.get(axis, "introduced")
        if current == "synthesized":
            return
        if debate_fn in {"attack", "steelman"}:
            if current == "introduced":
                self.axis_depth[axis] = "contested"
            elif current == "contested":
                self.axis_depth[axis] = "rebutted"
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

    def set_facilitator_constraint(self, constraint: str, turns: int = 2) -> None:
        self.active_constraint = constraint
        self.constraint_turns = turns

    def consume_constraint(self) -> str:
        """Return active constraint text and decrement counter. Returns '' if none."""
        if not self.active_constraint or self.constraint_turns <= 0:
            return ""
        result = self.active_constraint
        self.constraint_turns -= 1
        if self.constraint_turns <= 0:
            self.active_constraint = ""
            self.constraint_turns = 0
        return result

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
            "forced_axis_queue": self.forced_axis_queue,
            "topic_axes": self.topic_axes,
            "agent_axis_usage": self.agent_axis_usage,
            "agent_directives": self.agent_directives,
            "open_attacks": [list(t) for t in self.open_attacks],
            "agreement_streak": self.agreement_streak,
            "axis_depth": self.axis_depth,
            "active_constraint": self.active_constraint,
            "constraint_turns": self.constraint_turns,
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
        instance.active_constraint = str(data.get("active_constraint", ""))
        instance.constraint_turns = int(data.get("constraint_turns", 0))
        return instance
