from __future__ import annotations

import asyncio

from db.thread_repository import (
    ThreadRepositoryMixin,
    _coerce_state_json,
    _is_missing_relation_error,
)


def test_coerce_state_json_accepts_dicts() -> None:
    payload = {"turn": 1, "phase": "opening"}
    assert _coerce_state_json(payload) == payload


def test_coerce_state_json_parses_json_strings() -> None:
    assert _coerce_state_json('{"turn": 1, "phase": "opening"}') == {
        "turn": 1,
        "phase": "opening",
    }


def test_coerce_state_json_rejects_invalid_shapes() -> None:
    assert _coerce_state_json("[1, 2, 3]") is None
    assert _coerce_state_json("not-json") is None


def test_is_missing_relation_error_detects_thread_votes_table() -> None:
    assert _is_missing_relation_error(
        RuntimeError('relation "thread_votes" does not exist'),
        "thread_votes",
    ) is True
    assert _is_missing_relation_error(RuntimeError("42P01: relation missing"), "thread_votes") is True
    assert _is_missing_relation_error(RuntimeError("connection reset"), "thread_votes") is False


class _AcquireContext:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _MissingVotesConn:
    async def fetch(self, *args, **kwargs):
        raise RuntimeError('relation "thread_votes" does not exist')

    async def fetchval(self, *args, **kwargs):
        raise RuntimeError('relation "thread_votes" does not exist')

    async def execute(self, *args, **kwargs):
        raise RuntimeError('relation "thread_votes" does not exist')


class _Pool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return _AcquireContext(self._conn)


class _Repo(ThreadRepositoryMixin):
    def __init__(self, conn) -> None:
        self._pool = _Pool(conn)

    async def _ensure_pool(self):
        return self._pool


def test_fetch_thread_votes_returns_empty_when_table_is_missing() -> None:
    async def run() -> None:
        repo = _Repo(_MissingVotesConn())
        assert await repo.fetch_thread_votes("thread-1") == {}

    asyncio.run(run())


def test_fetch_user_thread_vote_returns_none_when_table_is_missing() -> None:
    async def run() -> None:
        repo = _Repo(_MissingVotesConn())
        assert await repo.fetch_user_thread_vote("thread-1", "user-1") is None

    asyncio.run(run())


def test_upsert_thread_vote_raises_controlled_error_when_table_is_missing() -> None:
    async def run() -> None:
        repo = _Repo(_MissingVotesConn())
        try:
            await repo.upsert_thread_vote("thread-1", "user-1", "agent-1")
        except ValueError as exc:
            assert str(exc) == "thread_votes_unavailable"
            return
        raise AssertionError("expected controlled missing table error")

    asyncio.run(run())
