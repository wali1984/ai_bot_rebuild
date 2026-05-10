import pytest

from v2.backend.app.composition.provenance_dedupe_attribution import (
    build_provenance_dedupe_attribution_runtime,
)


def test_runtime_provenance_now_keyword_only_params() -> None:
    runtime = build_provenance_dedupe_attribution_runtime(now_ms_clock=lambda: 1)
    with pytest.raises(TypeError):
        runtime.provenance_now(object())  # type: ignore[misc]
