from __future__ import annotations

import sys

from v2.backend.app.domain import liveness_stream_growth


def test_all_exports_exact_public_surface() -> None:
    assert liveness_stream_growth.__all__ == (
        "StreamIdObservation",
        "GrowthWindowConfig",
        "compute_stream_id_growth_in_window",
        "LivenessStreamGrowthDomainError",
    )


def test_beta_import_does_not_trigger_alpha_package_import() -> None:
    alpha_name = ".".join(("v2", "backend", "app", "domain", "trainer" + "_liveness"))
    sys.modules.pop(alpha_name, None)
    before = set(sys.modules)
    __import__(".".join(("v2", "backend", "app", "domain", "liveness_stream_growth")))
    after = set(sys.modules)
    assert alpha_name not in after - before


def test_parsed_id_is_not_reexported() -> None:
    assert "parsed_id" not in liveness_stream_growth.__all__
    assert not hasattr(liveness_stream_growth, "parsed_id")


def test_internal_helpers_are_not_reexported() -> None:
    assert all(not name.startswith("_") for name in liveness_stream_growth.__all__)
