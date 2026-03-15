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

        # Update internal states
        self._update_internal_states(speaker_id, target_agent)

        # Axis tracking
        if focus_axis:
            self.recent_axes.append(focus_axis)
        if len(self.recent_axes) > 8:
            self.recent_axes.pop(0)

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

    def to_dict(self) -> dict:
        return {
            "anger": {f"{k[0]}\x00{k[1]}": v for k, v in self.anger.items()},
            "retaliation_queue": self.retaliation_queue,
            "recent_axes": self.recent_axes,
            "internal_states": self.internal_states,
            "arsenal_cooldowns": self.arsenal_cooldowns,
            "recent_functions": self.recent_functions,
            "stance_history": self.stance_history,
            "used_arsenal_ids": {k: list(v) for k, v in self.used_arsenal_ids.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DebateState":
        instance = cls()
        for key_str, v in data.get("anger", {}).items():
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
        return instance
