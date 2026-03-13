from engine.discussion import _build_conversation_summary, _get_phase, _role_for_phase, _should_facilitate


def test_phase_transitions() -> None:
    assert _get_phase(0) == 1
    assert _get_phase(8) == 2
    assert _get_phase(23) == 3
    assert _get_phase(38) == 4
    assert _get_phase(45) == 5


def test_role_for_phase() -> None:
    assert _role_for_phase(1) == "supplement"
    assert _role_for_phase(4) == "shift"


def test_facilitator_inserts_once_per_ten_posts() -> None:
    plain_posts = [{"id": i, "is_facilitator": False} for i in range(1, 11)]
    assert _should_facilitate(plain_posts) is True

    facilitator_tail = plain_posts[:-1] + [{"id": 10, "is_facilitator": True}]
    assert _should_facilitate(facilitator_tail) is False


def test_conversation_summary_prefers_compressed_history_when_present() -> None:
    recent_posts = [{"display_name": "ソクラテス", "content": "定義を先に揃えよう。"}]
    summary = _build_conversation_summary("過去の対立は分配と自由に集中した。", recent_posts)

    assert "圧縮履歴" in summary
    assert "直近" in summary
