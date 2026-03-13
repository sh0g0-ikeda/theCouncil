from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "backend" / "agents"


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")

    client = AsyncOpenAI()
    conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
    try:
        for chunk_path in sorted(AGENTS_DIR.glob("*/chunks.jsonl")):
            agent_id = chunk_path.parent.name
            await conn.execute("DELETE FROM chunks WHERE agent_id = $1", agent_id)
            rows = [json.loads(line) for line in chunk_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for row in rows:
                embedding = await client.embeddings.create(
                    model="text-embedding-3-small",
                    input=row["text"],
                )
                vec = embedding.data[0].embedding
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                await conn.execute(
                    """
                    INSERT INTO chunks (agent_id, topic, tags, text, embedding)
                    VALUES ($1, $2, $3, $4, $5::vector)
                    """,
                    agent_id,
                    row["topic"],
                    row["tags"],
                    row["text"],
                    vec_str,
                )
            print(f"embedded {agent_id}: {len(rows)} chunks")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
