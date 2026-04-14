from __future__ import annotations

import asyncio
from unittest.mock import patch

from engine.llm import generate_debate_script
from engine.script_runtime import ScriptedDiscussionRunner


class _FakeDb:
    def __init__(self) -> None:
        self.saved_scripts: list[tuple[str, dict]] = []

    async def save_thread_script(self, thread_id: str, script: dict) -> None:
        self.saved_scripts.append((thread_id, script))


def test_generate_debate_script_reports_missing_openai_key():
    with patch.dict("os.environ", {}, clear=True):
        payload = asyncio.run(generate_debate_script("test topic", [{"id": "a"}], 10))

    assert payload["status"] == "error"
    assert payload["error"]["stage"] == "script_generation"
    assert payload["error"]["reason"] == "openai_disabled"


def test_script_runtime_persists_script_generation_error():
    db = _FakeDb()
    runner = ScriptedDiscussionRunner(
        thread_id="thread-1",
        db=db,  # type: ignore[arg-type]
        agents={},
        push_fn=lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    thread = {
        "topic": "test topic",
        "agent_ids": ["missing-agent"],
        "max_posts": 20,
    }

    with patch.dict("os.environ", {"OPENAI_API_KEY": "dummy-key"}, clear=True):
        result = asyncio.run(runner._ensure_script(thread))

    assert result is False
    assert len(db.saved_scripts) == 1
    saved_thread_id, script = db.saved_scripts[0]
    assert saved_thread_id == "thread-1"
    assert script["status"] == "error"
    assert script["error"]["reason"] == "no_agents"
