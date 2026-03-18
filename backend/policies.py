from __future__ import annotations

PLAN_MAX_POSTS = {
    "free": 20,
    "pro": 40,
    "ultra": 40,
}

PLAN_MAX_AGENTS = {
    "free": 4,
    "pro": 8,
    "ultra": 8,
}

# None = unlimited
PLAN_MONTHLY_THREADS: dict[str, int | None] = {
    "free": 3,
    "pro": 30,
    "ultra": None,
}


def clamp_max_posts(plan: str, requested: int) -> int:
    return min(requested, PLAN_MAX_POSTS.get(plan, PLAN_MAX_POSTS["free"]))


def max_agents(plan: str) -> int:
    return PLAN_MAX_AGENTS.get(plan, PLAN_MAX_AGENTS["free"])


def monthly_thread_limit(plan: str) -> int | None:
    return PLAN_MONTHLY_THREADS.get(plan, PLAN_MONTHLY_THREADS["free"])
