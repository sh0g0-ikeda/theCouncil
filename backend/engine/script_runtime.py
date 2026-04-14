from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from db.client import DatabaseClient
from engine.debate_state import DebateState
from engine.discussion_policy import (
    _build_conversation_summary,
    _determine_retrieval_mode,
    _extract_abstract_nouns,
    _get_phase,
    _is_missing_debate_state_error,
    _sanitize_topic_axes,
    seed_subquestions,
)
from engine.llm import (
    LLMGenerationError,
    assign_debate_frame,
    build_script_post_messages,
    call_llm,
    decompose_topic_axes,
    generate_debate_script,
    validate_reply_length,
)
from engine.rag import retrieve_chunks
from engine.validator import summarize_target_claim, validate_generated_reply
from models.agent import Agent

logger = logging.getLogger(__name__)

_TURN_FAIL_LIMIT = 3
_TURN_DELAYS = {
    "instant": 0.0,
    "fast": 0.4,
    "normal": 2.0,
    "slow": 5.0,
}
_RETRY_DELAYS = {
    "instant": 0.0,
    "fast": 0.2,
    "normal": 1.0,
    "slow": 2.0,
}
_QUESTION_LABEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"誰|だれ"), "判断主体"),
    (re.compile(r"基準|条件|要件|どのよう|どうやって|どう判断|いつ"), "判断基準"),
    (re.compile(r"撤退|歯止め|制約|例外|監視|安全装置|どう防ぐ"), "制約条件"),
)

_QUESTION_LABEL_PATTERNS = (
    (re.compile(r"(誰|だれ|who)", re.IGNORECASE), "判断主体"),
    (
        re.compile(r"(基準|条件|要件|どうやって|どう判断|いつ|when|whether|criteria|condition|threshold)", re.IGNORECASE),
        "判断基準",
    ),
    (
        re.compile(r"(制約|歯止め|撤退|例外|監視|安全装置|safeguard|constraint|limit)", re.IGNORECASE),
        "制約条件",
    ),
)


def _merge_unique_labels(*groups: list[str]) -> list[str]:
    labels: list[str] = []
    for group in groups:
        for label in group:
            cleaned = str(label).strip()
            if cleaned and cleaned not in labels:
                labels.append(cleaned)
    return labels


def _normalize_turn_contract(raw_contract: Any) -> dict[str, Any]:
    if not isinstance(raw_contract, dict):
        return {}
    return {
        "must_answer_subquestion_id": str(raw_contract.get("must_answer_subquestion_id", "")).strip(),
        "must_answer_subquestion_text": str(raw_contract.get("must_answer_subquestion_text", "")).strip(),
        "must_define_terms": [
            str(term).strip()
            for term in raw_contract.get("must_define_terms", [])
            if str(term).strip()
        ][:3],
        "required_labels": _merge_unique_labels([
            str(label).strip()
            for label in raw_contract.get("required_labels", [])
            if str(label).strip()
        ]),
        "forbid_question_only": bool(raw_contract.get("forbid_question_only")),
        "resolution_target": str(raw_contract.get("resolution_target", "")).strip(),
    }


def _required_labels_from_subquestion(text: str) -> list[str]:
    labels = ["結論"] if str(text).strip() else []
    for pattern, label in _QUESTION_LABEL_PATTERNS:
        if pattern.search(text or ""):
            labels.append(label)
    return _merge_unique_labels(labels)


def _turn_delay_seconds(speed_mode: str) -> float:
    return _TURN_DELAYS.get(str(speed_mode or "").strip(), _TURN_DELAYS["normal"])


def _retry_delay_seconds(speed_mode: str) -> float:
    return _RETRY_DELAYS.get(str(speed_mode or "").strip(), _RETRY_DELAYS["normal"])


@dataclass(slots=True)
class ResolvedTurn:
    speaker_id: str
    target_post: dict[str, Any] | None
    directive: str
    move_type: str
    phase: int
    assigned_side: str
    is_user_reply_turn: bool
    turn_contract: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScriptRuntimeState:
    event_counter: int = 0
    user_reply_pending: int = 0
    last_user_post_id: int | None = None
    cached_script: dict[str, Any] | None = None
    script_turn_index: int = 0
    turn_fail_counts: dict[int, int] = field(default_factory=dict)
    initial_load_done: bool = False
    debate_state: DebateState | None = None


class ScriptedDiscussionRunner:
    def __init__(
        self,
        *,
        thread_id: str,
        db: DatabaseClient,
        agents: dict[str, Agent],
        push_fn: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.thread_id = thread_id
        self.db = db
        self.agents = agents
        self.push_fn = push_fn
        self.state = ScriptRuntimeState()
        self._debate_state_table_missing = False

    async def run(self) -> None:
        logger.info("run_discussion started for thread=%s", self.thread_id)
        try:
            while True:
                thread = await self._load_thread()
                if not thread or thread.get("deleted_at"):
                    logger.info("run_discussion: thread=%s gone/deleted, stopping", self.thread_id)
                    break
                if thread["state"] == "completed":
                    logger.info("run_discussion: thread=%s completed, stopping", self.thread_id)
                    break
                if thread["state"] != "running":
                    await asyncio.sleep(2)
                    continue
                if thread.get("speed_mode") == "paused":
                    await asyncio.sleep(5)
                    continue

                if not await self._ensure_script(thread):
                    continue
                posts = await self.db.fetch_posts(self.thread_id)

                if len(posts) >= thread["max_posts"]:
                    await self.db.update_thread_state(self.thread_id, "completed")
                    break

                self._refresh_user_reply_state(posts)
                resolved = await self._resolve_turn(thread, posts)
                if resolved is None:
                    continue

                reply = await self._generate_reply(thread, posts, resolved)
                if reply is None:
                    continue

                await self._persist_reply(thread, posts, resolved, reply)
                await asyncio.sleep(_turn_delay_seconds(str(thread.get("speed_mode", "normal"))))
        except Exception:
            logger.exception("run_discussion crashed for thread=%s", self.thread_id)

    async def _load_thread(self) -> dict[str, Any] | None:
        if not self.state.initial_load_done:
            thread = await self.db.fetch_thread(self.thread_id)
            if thread:
                self.state.cached_script = thread.get("script_json") or None
            self.state.initial_load_done = True
            return thread
        return await self.db.fetch_thread_state(self.thread_id)

    async def _ensure_script(self, thread: dict[str, Any]) -> bool:
        cached_script = self.state.cached_script or {}
        if isinstance(cached_script.get("turns"), list) and cached_script["turns"]:
            self.state.cached_script = cached_script
            return True

        agent_list = [self.agents[aid].persona for aid in thread["agent_ids"] if aid in self.agents]
        logger.info("Generating debate script for thread=%s", self.thread_id)
        generated = await generate_debate_script(thread["topic"], agent_list, thread["max_posts"])
        if generated.get("turns"):
            self.state.cached_script = generated
            await self.db.save_thread_script(self.thread_id, generated)
            logger.info("Script generated: %d turns for thread=%s", len(generated["turns"]), self.thread_id)
            return True

        logger.warning("Script generation failed for thread=%s, retrying in 5s", self.thread_id)
        await asyncio.sleep(_retry_delay_seconds(str(thread.get("speed_mode", "normal"))))
        return False

    async def _ensure_debate_state(self, thread: dict[str, Any]) -> DebateState:
        if self.state.debate_state is not None:
            return self.state.debate_state

        saved_state: dict[str, Any] | None = None
        if not self._debate_state_table_missing:
            try:
                saved_state = await self.db.load_debate_state(self.thread_id)
            except Exception as exc:
                if _is_missing_debate_state_error(exc):
                    self._debate_state_table_missing = True
                else:
                    raise

        if saved_state:
            self.state.debate_state = DebateState.from_dict(saved_state)
            return self.state.debate_state

        debate = DebateState()
        topic_axes = _sanitize_topic_axes(
            await decompose_topic_axes(thread["topic"]),
            thread["topic"],
            thread.get("topic_tags", []),
        )
        debate.set_topic_axes(topic_axes)
        debate.thread_subquestions = seed_subquestions(thread["topic"])
        debate.abstract_terms = _extract_abstract_nouns(thread["topic"], max_nouns=6)
        for term in debate.abstract_terms:
            debate.definition_requests.setdefault(
                term,
                {
                    "status": "open",
                    "requested_post_id": 0,
                    "requested_by": "thread_seed",
                    "target_agent_id": None,
                    "created_post_id": 0,
                    "answered_post_id": None,
                    "answered_by": None,
                },
            )

        agent_list = [self.agents[aid].persona for aid in thread["agent_ids"] if aid in self.agents]
        frame_payload = await assign_debate_frame(thread["topic"], agent_list)
        debate.set_debate_frame(
            dict(frame_payload.get("frame") or {}),
            {str(agent_id): dict(payload) for agent_id, payload in dict(frame_payload.get("assignments") or {}).items()},
        )
        self.state.debate_state = debate
        await self._save_debate_state_if_possible(debate)
        return debate

    async def _save_debate_state_if_possible(self, debate: DebateState) -> None:
        if self._debate_state_table_missing:
            return
        try:
            await self.db.save_debate_state(self.thread_id, debate.to_dict())
        except Exception as exc:
            if _is_missing_debate_state_error(exc):
                self._debate_state_table_missing = True
                return
            raise

    def _refresh_user_reply_state(self, posts: list[dict[str, Any]]) -> None:
        for post in posts:
            if (
                post.get("agent_id") is None
                and not post.get("is_facilitator")
                and post.get("user_id") is not None
                and (self.state.last_user_post_id is None or post["id"] > self.state.last_user_post_id)
            ):
                self.state.last_user_post_id = post["id"]
                self.state.user_reply_pending = 2

    def _find_post_by_id(self, posts: list[dict[str, Any]], post_id: Any) -> dict[str, Any] | None:
        try:
            target_id = int(post_id)
        except (TypeError, ValueError):
            return None
        return next((post for post in reversed(posts) if int(post.get("id") or -1) == target_id), None)

    def _select_subquestion_obligation(
        self,
        thread: dict[str, Any],
        debate: DebateState,
    ) -> tuple[str, dict[str, Any]] | None:
        best: tuple[str, dict[str, Any]] | None = None
        best_post_id = -1
        for agent_id in thread["agent_ids"]:
            if agent_id not in self.agents:
                continue
            subquestion = debate.get_priority_subquestion_for(agent_id)
            if not subquestion:
                continue
            post_id = int(subquestion.get("post_id") or subquestion.get("created_post_id") or -1)
            if post_id >= best_post_id:
                best = (agent_id, subquestion)
                best_post_id = post_id
        return best

    async def _resolve_turn(self, thread: dict[str, Any], posts: list[dict[str, Any]]) -> ResolvedTurn | None:
        debate = await self._ensure_debate_state(thread)
        ai_posts = [post for post in posts if post.get("agent_id")]
        is_user_reply_turn = self.state.user_reply_pending > 0

        if is_user_reply_turn:
            last_ai_id = ai_posts[-1].get("agent_id") if ai_posts else None
            candidates = [
                agent_id for agent_id in thread["agent_ids"]
                if agent_id in self.agents and agent_id != last_ai_id
            ]
            if not candidates:
                candidates = [agent_id for agent_id in thread["agent_ids"] if agent_id in self.agents]
            if not candidates:
                self.state.user_reply_pending = 0
                return None
            speaker_id = random.choice(candidates)
            target_post = next((post for post in reversed(posts) if post["id"] == self.state.last_user_post_id), None)
            self.state.user_reply_pending -= 1
            return ResolvedTurn(
                speaker_id=speaker_id,
                target_post=target_post,
                directive="Respond to the user directly, answer the strongest confusion, and summarize the current fault line.",
                move_type="counter",
                phase=_get_phase(len(posts)),
                assigned_side=debate.get_agent_side(speaker_id),
                is_user_reply_turn=True,
            )

        turns: list[dict[str, Any]] = (self.state.cached_script or {}).get("turns", [])
        while (
            self.state.script_turn_index < len(turns)
            and self.state.turn_fail_counts.get(self.state.script_turn_index, 0) >= _TURN_FAIL_LIMIT
        ):
            logger.warning(
                "Skipping turn=%d after %d failures for thread=%s",
                self.state.script_turn_index,
                _TURN_FAIL_LIMIT,
                self.thread_id,
            )
            self.state.script_turn_index += 1

        if self.state.script_turn_index >= len(turns):
            if not ai_posts:
                logger.warning(
                    "All script turns exhausted before any AI post was saved for thread=%s; resetting script state",
                    self.thread_id,
                )
                self.state.cached_script = None
                self.state.script_turn_index = 0
                self.state.turn_fail_counts.clear()
            return None

        turn = turns[self.state.script_turn_index]
        speaker_id = str(turn.get("agent_id", ""))
        if speaker_id not in self.agents:
            candidates = [agent_id for agent_id in thread["agent_ids"] if agent_id in self.agents]
            if not candidates:
                raise RuntimeError(f"No agents available for thread={self.thread_id}")
            speaker_id = random.choice(candidates)

        reply_to_turn = turn.get("reply_to_turn")
        if reply_to_turn is not None and isinstance(reply_to_turn, int) and reply_to_turn < len(ai_posts):
            target_post = ai_posts[reply_to_turn]
        elif ai_posts:
            target_post = ai_posts[-1]
        else:
            target_post = None

        subquestion_obligation = self._select_subquestion_obligation(thread, debate)
        if subquestion_obligation:
            obligated_speaker_id, obligated_subquestion = subquestion_obligation
            if obligated_speaker_id != speaker_id:
                speaker_id = obligated_speaker_id
            obligated_target = self._find_post_by_id(posts, obligated_subquestion.get("post_id"))
            if obligated_target is not None:
                target_post = obligated_target

        assigned_side = str(turn.get("assigned_side", "")).strip() or debate.get_agent_side(speaker_id)
        return ResolvedTurn(
            speaker_id=speaker_id,
            target_post=target_post,
            directive=str(turn.get("directive", "Answer the core claim directly and move the debate forward.")),
            move_type=str(turn.get("move_type", "attack")),
            phase=int(turn.get("phase", _get_phase(len(posts)))),
            assigned_side=assigned_side,
            is_user_reply_turn=False,
            turn_contract=_normalize_turn_contract(turn.get("turn_contract", {})),
        )

    def _required_response_kind(self, move_type: str, is_user_reply_turn: bool) -> str:
        if is_user_reply_turn:
            return "synthesize"
        mapping = {
            "opening_statement": "define",
            "counter_definition": "differentiate",
            "definition_rewrite": "define",
            "attack": "attack",
            "counter": "attack",
            "expose_contradiction": "attack",
            "condition_squeeze": "attack",
            "reframe": "differentiate",
            "steelman_and_break": "steelman",
            "concretize": "concretize",
            "new_evidence": "concretize",
            "compression": "synthesize",
            "final_verdict": "synthesize",
        }
        return mapping.get(move_type, "attack")

    def _definition_seed_required_kind(
        self,
        posts: list[dict[str, Any]],
        debate: DebateState,
        speaker_id: str,
        is_user_reply_turn: bool,
        target_post: dict[str, Any] | None,
    ) -> str:
        if is_user_reply_turn:
            return ""
        ai_post_count = len([post for post in posts if post.get("agent_id")])
        if ai_post_count >= 4:
            return ""
        if not debate.get_unresolved_terms():
            return ""
        if debate.has_pending_definition_response(speaker_id) and target_post and target_post.get("content"):
            return "differentiate"
        return "define"

    def _resolve_required_response_kind(
        self,
        posts: list[dict[str, Any]],
        debate: DebateState,
        resolved: ResolvedTurn,
    ) -> str:
        definition_seed_kind = self._definition_seed_required_kind(
            posts,
            debate,
            resolved.speaker_id,
            resolved.is_user_reply_turn,
            resolved.target_post,
        )
        if definition_seed_kind:
            return definition_seed_kind
        return self._required_response_kind(resolved.move_type, resolved.is_user_reply_turn)

    def _resolved_abstract_terms(self, debate: DebateState) -> list[str]:
        return sorted(
            term for term, payload in debate.definition_requests.items()
            if payload.get("status") == "answered"
        )

    def _build_turn_contract(
        self,
        debate: DebateState,
        resolved: ResolvedTurn,
        required_kind: str,
        priority_subquestion: dict[str, Any],
    ) -> dict[str, Any]:
        contract = _normalize_turn_contract(resolved.turn_contract)
        required_labels = list(contract.get("required_labels", []))

        if required_kind in {"define", "differentiate"}:
            pending_terms = debate.get_unresolved_terms()
            if pending_terms:
                existing_terms = list(contract.get("must_define_terms", []))
                contract["must_define_terms"] = _merge_unique_labels(existing_terms, pending_terms[:2])
                required_labels = _merge_unique_labels(required_labels, ["定義"])

        subquestion_id = str(priority_subquestion.get("subquestion_id", "")).strip()
        subquestion_text = str(priority_subquestion.get("text", "")).strip()
        if subquestion_id:
            contract["must_answer_subquestion_id"] = subquestion_id
            contract["must_answer_subquestion_text"] = subquestion_text
            contract["forbid_question_only"] = True
            contract["resolution_target"] = contract.get("resolution_target") or "answered"
            required_labels = _merge_unique_labels(required_labels, _required_labels_from_subquestion(subquestion_text))
        elif required_kind in {"define", "differentiate"}:
            required_labels = [label for label in required_labels if label != "定義"]

        if resolved.move_type in {"compression", "final_verdict"}:
            required_labels = _merge_unique_labels(required_labels, ["結論"])

        contract["required_labels"] = required_labels
        return contract

    def _camp_map_summary(self, thread: dict[str, Any], debate: DebateState) -> str:
        parts: list[str] = []
        for agent_id in thread["agent_ids"]:
            if agent_id not in self.agents:
                continue
            side = debate.get_agent_side(agent_id) or "unassigned"
            camp_function = debate.get_camp_function(agent_id) or "general"
            parts.append(f"{self.agents[agent_id].display_name}:{side}/{camp_function}")
        return " | ".join(parts[:8])

    def _recent_agent_conclusions(self, debate: DebateState, speaker_id: str) -> list[str]:
        conclusions: list[str] = []
        for entry in reversed(debate.open_claim_structures[-12:]):
            if entry.get("agent_id") != speaker_id:
                continue
            structure = dict(entry.get("structure") or {})
            conclusion = str(structure.get("conclusion", "")).strip()
            if conclusion:
                conclusions.append(conclusion)
            if len(conclusions) >= 3:
                break
        conclusions.reverse()
        return conclusions

    def _build_generation_context(
        self,
        thread: dict[str, Any],
        posts: list[dict[str, Any]],
        resolved: ResolvedTurn,
        debate: DebateState,
    ) -> dict[str, Any]:
        persona = self.agents[resolved.speaker_id].persona
        target_post = resolved.target_post or {}
        debate_frame = debate.get_debate_frame()
        assigned_side = resolved.assigned_side or debate.get_agent_side(resolved.speaker_id)
        assigned_side = "conditional" if assigned_side == "neutral" else assigned_side
        assigned_side_label = str(
            debate_frame.get(f"{assigned_side}_label", "") if assigned_side else ""
        ).strip() or assigned_side
        opposing_side = debate.get_opposing_side(resolved.speaker_id)
        opposing_side_label = str(
            debate_frame.get(f"{opposing_side}_label", "") if opposing_side else ""
        ).strip()
        required_kind = self._resolve_required_response_kind(posts, debate, resolved)
        priority_subquestion = debate.get_priority_subquestion_for(resolved.speaker_id) or {}
        turn_contract = self._build_turn_contract(debate, resolved, required_kind, priority_subquestion)
        focus_axis = str(target_post.get("focus_axis", "")).strip()
        if not focus_axis:
            axes = debate.topic_axes or thread.get("topic_tags", [])
            focus_axis = str(axes[0] if axes else "rationalism")
        position_anchor = debate.get_position_anchor(resolved.speaker_id)

        return {
            "persona": persona,
            "thread_topic": thread["topic"],
            "conversation_summary": _build_conversation_summary("", posts[-10:]),
            "target_post": target_post,
            "target_debate_role": debate.get_debate_role(target_post.get("agent_id")),
            "target_side": debate.get_agent_side(target_post.get("agent_id")),
            "current_tags": thread.get("topic_tags", []),
            "topic_axes": debate.topic_axes or thread.get("topic_tags", []),
            "thread_subquestions": list(debate.thread_subquestions),
            "abstract_terms": list(debate.abstract_terms),
            "resolved_abstract_terms": self._resolved_abstract_terms(debate),
            "conflict_axis": focus_axis,
            "debate_function": required_kind,
            "required_response_kind": required_kind,
            "assigned_side": assigned_side,
            "assigned_side_label": assigned_side_label,
            "opposing_side_label": opposing_side_label,
            "side_contract": debate.get_side_contract(resolved.speaker_id).get("thesis", ""),
            "frame_proposition": str(debate_frame.get("proposition", "")).strip(),
            "support_label": str(debate_frame.get("support_label", "")).strip(),
            "oppose_label": str(debate_frame.get("oppose_label", "")).strip(),
            "support_thesis": str(debate_frame.get("support_thesis", "")).strip(),
            "oppose_thesis": str(debate_frame.get("oppose_thesis", "")).strip(),
            "assigned_camp_function": debate.get_camp_function(resolved.speaker_id),
            "required_subquestion_id": str(priority_subquestion.get("subquestion_id", "")).strip(),
            "required_subquestion_text": str(priority_subquestion.get("text", "")).strip(),
            "turn_contract": turn_contract,
            "pending_definition_terms": debate.get_unresolved_terms(),
            "recent_argument_fingerprints": list(debate.recent_argument_fingerprints[-6:]),
            "forbidden_example_keys": list(debate.recent_example_keys[-4:]),
            "required_concepts": list((persona.get("persona_anchors") or {}).get("required_concepts", [])),
            "position_anchor_summary": str(position_anchor.get("summary", "")).strip(),
            "position_anchor_terms": list(position_anchor.get("terms", [])),
            "camp_map_summary": self._camp_map_summary(thread, debate),
            "target_claim_summary": summarize_target_claim(target_post, focus_axis),
            "target_claim_units": debate.get_claim_units_for_post(target_post.get("id")),
            "recent_agent_conclusions": self._recent_agent_conclusions(debate, resolved.speaker_id),
            "agent_recent_axes": debate.get_agent_recent_axes(resolved.speaker_id),
            "debate_role": debate.get_debate_role(resolved.speaker_id),
            "available_arsenal": debate.get_available_arsenal(resolved.speaker_id, persona),
            "debate_post_count": len([post for post in posts if post.get("agent_id")]),
            "is_first_post": not any(post.get("agent_id") == resolved.speaker_id for post in posts),
            "role": debate.get_debate_role(resolved.speaker_id),
            "meta_intervention_kind": "summarize" if resolved.is_user_reply_turn else "",
        }

    async def _generate_reply(
        self,
        thread: dict[str, Any],
        posts: list[dict[str, Any]],
        resolved: ResolvedTurn,
    ) -> dict[str, Any] | None:
        debate = await self._ensure_debate_state(thread)
        context = self._build_generation_context(thread, posts, resolved, debate)
        rag_mode = _determine_retrieval_mode(
            str(context.get("debate_function", "")),
            list(context.get("pending_definition_terms", [])),
            "",
        )
        rag_context = {
            "thread_topic": thread["topic"],
            "conflict_axis": str(context.get("conflict_axis", resolved.directive[:40])),
            "current_tags": thread.get("topic_tags", []),
            "target_post": resolved.target_post or {},
            "debate_function": str(context.get("debate_function", "")),
            "retrieval_mode": rag_mode,
        }
        rag_chunks = retrieve_chunks(resolved.speaker_id, rag_context, retrieval_mode=rag_mode)

        retry_hint: str | None = None
        for _attempt in range(2):
            messages = build_script_post_messages(
                persona=self.agents[resolved.speaker_id].persona,
                directive=resolved.directive,
                move_type=resolved.move_type,
                target_post=resolved.target_post or {},
                recent_posts=posts[-6:],
                rag_chunks=rag_chunks,
                thread_topic=thread["topic"],
                phase=resolved.phase,
                assigned_side=resolved.assigned_side,
                assigned_side_label=str(context.get("assigned_side_label", "")),
                opposing_side_label=str(context.get("opposing_side_label", "")),
                side_contract=str(context.get("side_contract", "")),
                frame_proposition=str(context.get("frame_proposition", "")),
                assigned_camp_function=str(context.get("assigned_camp_function", "")),
                required_subquestion_id=str(context.get("required_subquestion_id", "")),
                required_subquestion_text=str(context.get("required_subquestion_text", "")),
                turn_contract=dict(context.get("turn_contract") or {}),
                pending_definition_terms=list(context.get("pending_definition_terms", [])),
                topic_axes=list(context.get("topic_axes", [])),
                recent_argument_fingerprints=list(context.get("recent_argument_fingerprints", [])),
                forbidden_example_keys=list(context.get("forbidden_example_keys", [])),
                required_concepts=list(context.get("required_concepts", [])),
                required_response_kind=str(context.get("required_response_kind", "")),
                retry_hint=retry_hint,
                target_claim_summary=str(context.get("target_claim_summary", "")),
                camp_map_summary=str(context.get("camp_map_summary", "")),
                abstract_terms=list(context.get("abstract_terms", [])),
                resolved_abstract_terms=list(context.get("resolved_abstract_terms", [])),
                recent_agent_conclusions=list(context.get("recent_agent_conclusions", [])),
                position_anchor_summary=str(context.get("position_anchor_summary", "")),
            )
            try:
                reply = await call_llm(messages)
            except LLMGenerationError:
                retry_hint = "Return valid JSON with the requested stance and semantic fields."
                continue

            if not validate_reply_length(reply.get("content", "")):
                retry_hint = "Keep the reply between 100 and 220 Japanese characters."
                continue

            validation = validate_generated_reply(reply, context)
            if validation.ok:
                reply["_semantic_analysis"] = validation.analysis.as_dict()
                return reply
            retry_hint = validation.retry_hint

        logger.warning(
            "LLM failed for thread=%s turn=%d speaker=%s",
            self.thread_id,
            self.state.script_turn_index,
            resolved.speaker_id,
        )
        if not resolved.is_user_reply_turn:
            self.state.turn_fail_counts[self.state.script_turn_index] = (
                self.state.turn_fail_counts.get(self.state.script_turn_index, 0) + 1
            )
        await asyncio.sleep(_retry_delay_seconds(str(thread.get("speed_mode", "normal"))))
        return None

    async def _persist_reply(
        self,
        thread: dict[str, Any],
        posts: list[dict[str, Any]],
        resolved: ResolvedTurn,
        reply: dict[str, Any],
    ) -> None:
        debate = await self._ensure_debate_state(thread)
        phase_for_db = _get_phase(len(posts))
        if phase_for_db != thread.get("current_phase"):
            await self.db.update_thread_phase(self.thread_id, phase_for_db)

        post = await self.db.save_post(
            self.thread_id,
            resolved.speaker_id,
            {
                "reply_to": resolved.target_post["id"] if resolved.target_post else None,
                "content": reply["content"],
                "stance": reply.get("local_stance_to_target") or reply.get("stance", "disagree"),
                "focus_axis": reply.get("main_axis", "rationalism"),
            },
            token_usage=int(reply.get("_token_usage", 0)),
        )
        analysis = dict(reply.get("_semantic_analysis") or {})
        effective_debate_function = self._resolve_required_response_kind(posts, debate, resolved)
        debate.record_post(
            resolved.speaker_id,
            resolved.target_post or {},
            str(reply.get("main_axis", "")).strip() or str((resolved.target_post or {}).get("focus_axis", "")),
            debate_function=effective_debate_function,
            used_arsenal_id=reply.get("used_arsenal_id"),
            stance=str(reply.get("local_stance_to_target") or reply.get("stance") or "disagree"),
            post_id=int(post.get("id") or 0),
            analysis=analysis,
            content=str(reply.get("content", "")),
        )
        debate.age_obligations(int(post.get("id") or 0))
        await self._save_debate_state_if_possible(debate)
        self.state.event_counter += 1
        await self.push_fn(self.thread_id, post)

        if not resolved.is_user_reply_turn:
            self.state.script_turn_index += 1
            self.state.turn_fail_counts.pop(self.state.script_turn_index - 1, None)
