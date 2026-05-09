from v2.backend.app.composition import external_manual_position_quarantine as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "ExternalManualPositionQuarantineRuntime",
        "ExternalManualPositionQuarantineRuntimeCompositionError",
        "build_external_position_quarantine_runtime",
    }
