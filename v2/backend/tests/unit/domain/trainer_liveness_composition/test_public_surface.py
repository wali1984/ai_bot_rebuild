from __future__ import annotations

import v2.backend.app.domain.trainer_liveness_composition as surface


def test_public_surface_exports_exact_names() -> None:
    assert surface.__all__ == (
        "LivenessSnapshotBaseInputs",
        "compose_liveness_snapshot_with_growth",
        "TrainerLivenessCompositionError",
    )
