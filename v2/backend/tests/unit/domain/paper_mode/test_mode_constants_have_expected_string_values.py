from v2.backend.app.domain.paper_mode import PAPER_MODE_LIVE_BLOCKED, PAPER_MODE_PAPER


def test_mode_constants_have_expected_string_values() -> None:
    assert PAPER_MODE_PAPER == "paper"
    assert PAPER_MODE_LIVE_BLOCKED == "live_blocked"
