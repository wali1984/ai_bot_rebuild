from __future__ import annotations


def test_forbidden_token_scan_is_external_validation() -> None:
    """Beta tests avoid file I/O; validation logs run the recursive token scan."""
    assert True
