from v2.backend.app.services import external_manual_position_quarantine as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "ExternalManualPositionQuarantineServiceError",
        "assemble_external_position_quarantine_record",
    }
