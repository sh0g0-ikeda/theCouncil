from __future__ import annotations

PLAN_MAX_POSTS = {
    "free": 50,
    "pro": 100,
    "ultra": 200,
}

PLAN_MAX_AGENTS = {
    "free": 4,
    "pro": 8,
    "ultra": 8,
}

# None = unlimited
PLAN_MONTHLY_THREADS: dict[str, int | None] = {
    "free": 3,
    "pro": 20,
    "ultra": None,
}

# None = unlimited; 0 = not allowed
PLAN_MONTHLY_PRIVATE_THREADS: dict[str, int | None] = {
    "free": 0,
    "pro": 5,
    "ultra": None,
}

# Lower number = higher priority (1=ultra, 2=pro, 3=free)
PLAN_QUEUE_PRIORITY: dict[str, int] = {
    "free": 3,
    "pro": 2,
    "ultra": 1,
}


def clamp_max_posts(plan: str, requested: int) -> int:
    return min(requested, PLAN_MAX_POSTS.get(plan, PLAN_MAX_POSTS["free"]))


def max_agents(plan: str) -> int:
    return PLAN_MAX_AGENTS.get(plan, PLAN_MAX_AGENTS["free"])


def monthly_thread_limit(plan: str) -> int | None:
    return PLAN_MONTHLY_THREADS.get(plan, PLAN_MONTHLY_THREADS["free"])


def monthly_private_thread_limit(plan: str) -> int | None:
    return PLAN_MONTHLY_PRIVATE_THREADS.get(plan, 0)


def queue_priority(plan: str) -> int:
    return PLAN_QUEUE_PRIORITY.get(plan, PLAN_QUEUE_PRIORITY["free"])
