import pytest

from v2.backend.app.composition.external_manual_position_quarantine import (
    build_external_position_quarantine_runtime,
)


def test_runtime_now_keyword_only_params() -> None:
    runtime = build_external_position_quarantine_runtime(now_ms_clock=lambda: 1)

    with pytest.raises(TypeError):
        runtime.external_manual_position_quarantine_now(object())  # type: ignore[misc]
