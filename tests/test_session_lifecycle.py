from agent.session import is_session_expired


def test_active_session_within_idle_window_is_reused():
    now = 1_000_000.0
    assert (
        is_session_expired(
            last_active_at=now - 29 * 60,
            status="active",
            idle_seconds=30 * 60,
            now=now,
        )
        is False
    )


def test_session_expires_after_idle_window():
    now = 1_000_000.0
    assert (
        is_session_expired(
            last_active_at=now - 31 * 60,
            status="active",
            idle_seconds=30 * 60,
            now=now,
        )
        is True
    )


def test_closed_session_is_always_expired():
    now = 1_000_000.0
    assert (
        is_session_expired(
            last_active_at=now,
            status="closed",
            idle_seconds=30 * 60,
            now=now,
        )
        is True
    )
