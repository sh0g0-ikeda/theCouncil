from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "backend" / "agents"


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")

    conn = await asyncpg.connect(dsn=dsn)
    try:
        for persona_path in sorted(AGENTS_DIR.glob("*/persona.json")):
            persona = json.loads(persona_path.read_text(encoding="utf-8"))
            vector = list(persona["ideology_vector"].values())
            await conn.execute(
                """
                INSERT INTO agents (id, display_name, label, persona_json, vector)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                ON CONFLICT (id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    label = EXCLUDED.label,
                    persona_json = EXCLUDED.persona_json,
                    vector = EXCLUDED.vector,
                    updated_at = NOW()
                """,
                persona["id"],
                persona["display_name"],
                persona["label"],
                json.dumps(persona, ensure_ascii=False),
                vector,
            )
            print(f"seeded {persona['id']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

