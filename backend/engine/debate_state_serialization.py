from __future__ import annotations


class DebateStateSerializationMixin:
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
    def from_dict(cls, data: dict) -> "DebateStateSerializationMixin":
        instance = cls()
        anger_raw = data.get("anger", [])
        if isinstance(anger_raw, list):
            for item in anger_raw:
                if isinstance(item, (list, tuple)) and len(item) == 3:
                    instance.anger[(str(item[0]), str(item[1]))] = int(item[2])
        elif isinstance(anger_raw, dict):
            for key_str, value in anger_raw.items():
                parts = key_str.split("\x00", 1)
                if len(parts) == 2:
                    instance.anger[(parts[0], parts[1])] = value

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
            str(k): [dict(item) for item in value if isinstance(item, dict)]
            for k, value in data.get("shift_history", {}).items()
            if isinstance(value, list)
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
