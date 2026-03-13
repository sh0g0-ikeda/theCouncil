from __future__ import annotations

import json
import re
from pathlib import Path

_chunk_cache: dict[str, list[dict]] = {}
_token_pattern = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)


def _agents_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agents"


def clear_chunk_cache(agent_id: str | None = None) -> None:
    if agent_id is None:
        _chunk_cache.clear()
        return
    _chunk_cache.pop(agent_id, None)


def load_chunks(agent_id: str) -> list[dict]:
    if agent_id not in _chunk_cache:
        path = _agents_dir() / agent_id / "chunks.jsonl"
        if path.exists():
            _chunk_cache[agent_id] = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            _chunk_cache[agent_id] = []
    return _chunk_cache[agent_id]


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _token_pattern.findall(text)}


def retrieve_chunks(agent_id: str, context: dict, top_k: int = 4) -> list[str]:
    chunks = load_chunks(agent_id)
    if not chunks:
        return []

    query_tags = set(context.get("current_tags", []))
    query_text = f"{context.get('thread_topic', '')} {context.get('target_post', {}).get('content', '')}"
    query_words = _tokenize(query_text)

    def score(chunk: dict) -> float:
        tag_score = len(set(chunk.get("tags", [])) & query_tags) / max(len(query_tags), 1)
        kw_score = len(_tokenize(chunk.get("text", "")) & query_words) / max(len(query_words), 1)
        return tag_score * 0.6 + kw_score * 0.4

    ranked = sorted(chunks, key=score, reverse=True)
    return [chunk["text"] for chunk in ranked[:top_k]]

