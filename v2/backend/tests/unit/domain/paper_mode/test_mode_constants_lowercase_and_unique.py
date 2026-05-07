from v2.backend.app.domain.paper_mode import PAPER_MODE_LIVE_BLOCKED, PAPER_MODE_PAPER


def test_mode_constants_lowercase_and_unique() -> None:
    modes = (PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED)
    assert PAPER_MODE_PAPER == PAPER_MODE_PAPER.lower()
    assert PAPER_MODE_LIVE_BLOCKED == PAPER_MODE_LIVE_BLOCKED.lower()
    assert isinstance(PAPER_MODE_PAPER, str)
    assert isinstance(PAPER_MODE_LIVE_BLOCKED, str)
    assert PAPER_MODE_PAPER != ""
    assert PAPER_MODE_LIVE_BLOCKED != ""
    assert len(set(modes)) == 2
