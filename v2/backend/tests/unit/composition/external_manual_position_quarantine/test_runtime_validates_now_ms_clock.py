import pytest

from v2.backend.app.composition.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineRuntimeCompositionError,
    build_external_position_quarantine_runtime,
)


def test_runtime_validates_now_ms_clock() -> None:
    with pytest.raises(ExternalManualPositionQuarantineRuntimeCompositionError):
        build_external_position_quarantine_runtime(now_ms_clock=object())  # type: ignore[arg-type]
