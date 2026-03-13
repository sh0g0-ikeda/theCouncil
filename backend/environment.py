from __future__ import annotations

import os


def is_production_environment() -> bool:
    values = {
        (os.getenv("ENVIRONMENT") or "").lower(),
        (os.getenv("APP_ENV") or "").lower(),
        (os.getenv("VERCEL_ENV") or "").lower(),
    }
    return any(value in {"production", "prod"} for value in values)

