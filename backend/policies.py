from __future__ import annotations

PLAN_MAX_POSTS = {
    "free": 20,
    "pro": 20,
    "ultra": 20,
}


def clamp_max_posts(plan: str, requested: int) -> int:
    return min(requested, PLAN_MAX_POSTS.get(plan, PLAN_MAX_POSTS["free"]))
