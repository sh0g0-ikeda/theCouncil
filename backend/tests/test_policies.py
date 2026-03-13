from policies import clamp_max_posts


def test_clamp_max_posts_respects_plan_limits() -> None:
    assert clamp_max_posts("free", 200) == 50
    assert clamp_max_posts("pro", 200) == 100
    assert clamp_max_posts("ultra", 200) == 200
