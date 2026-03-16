from __future__ import annotations

from engine import rag


def test_retrieve_chunks_prefers_definition_mode() -> None:
    rag._chunk_cache["tester"] = [
        {
            "topic": "democracy",
            "tags": ["rationalism", "definition"],
            "text": "民主主義とは公開された討議と法的正当化を通じて権力を拘束する制度のことや",
        },
        {
            "topic": "democracy",
            "tags": ["rationalism", "history"],
            "text": "イラク戦争の事例は民主主義の外政判断の失敗例として語られる",
        },
    ]

    chunks = rag.retrieve_chunks(
        "tester",
        {
            "thread_topic": "民主主義は最善か",
            "target_post": {"content": "そもそも民主主義って何や"},
            "pending_definition_terms": ["民主主義"],
            "debate_function": "define",
            "retrieval_mode": "definition",
            "current_tags": ["rationalism"],
        },
    )

    assert chunks
    assert "民主主義とは" in chunks[0]


def test_retrieve_chunks_penalizes_recent_examples() -> None:
    rag._chunk_cache["tester_penalty"] = [
        {
            "topic": "war",
            "tags": ["rationalism", "history"],
            "text": "For example, the Iraq war shows how legitimacy can collapse under false premises.",
        },
        {
            "topic": "war",
            "tags": ["rationalism", "history"],
            "text": "The Cuban missile crisis shows how deterrence can avoid direct escalation.",
        },
    ]

    chunks = rag.retrieve_chunks(
        "tester_penalty",
        {
            "thread_topic": "war and democracy",
            "target_post": {"content": "Iraq war still matters"},
            "debate_function": "attack",
            "retrieval_mode": "counterexample",
            "forbidden_example_keys": ["iraq war"],
            "current_tags": ["rationalism"],
        },
    )

    assert chunks
    assert "cuban missile crisis" in chunks[0].lower()
