from __future__ import annotations

from types import SimpleNamespace

import pytest

from v2.backend.app.cli import v2_candidate_outcome_calibration_publisher as publisher
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_calibration_v2 import (
    _observation,
)


def _registry() -> dict[str, object]:
    return {
        "registry_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_bundle_sha256": "a" * 64,
        "paper_only": True,
        "live_eligible": False,
    }


def test_fits_only_active_authenticated_matured_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        SimpleNamespace(
            archive_sequence=2,
            matured_labels=object(),
            decision=SimpleNamespace(
                checkpoint_generation=3,
                checkpoint_id="checkpoint-3",
                checkpoint_sha256="a" * 64,
            ),
            observation_index=index,
        )
        for index in range(60)
    ]
    records.append(
        SimpleNamespace(
            archive_sequence=2,
            matured_labels=object(),
            decision=SimpleNamespace(
                checkpoint_generation=4,
                checkpoint_id="checkpoint-4",
                checkpoint_sha256="b" * 64,
            ),
            observation_index=999,
        )
    )
    monkeypatch.setattr(
        publisher,
        "extract_calibration_observation",
        lambda record: _observation(record.observation_index),
    )

    artifact = publisher.fit_active_candidate_calibration(
        records,  # type: ignore[arg-type]
        active_registry=_registry(),
        source_archive_chain_sha256="c" * 64,
        generated_at_ms=3_000_000,
    )

    assert artifact["fit_sample_count"] == 48
    assert artifact["validation_sample_count"] == 12
    assert artifact["checkpoint_generation"] == 3
    assert artifact["counterfactual_counts_as_realized_paper_profit"] is False


def test_live_eligible_registry_is_rejected() -> None:
    registry = _registry()
    registry["live_eligible"] = True

    with pytest.raises(
        publisher.CandidateCalibrationPublisherError,
        match="live_eligible_forbidden",
    ):
        publisher.fit_active_candidate_calibration(
            [],
            active_registry=registry,
            source_archive_chain_sha256="c" * 64,
            generated_at_ms=3_000_000,
        )

