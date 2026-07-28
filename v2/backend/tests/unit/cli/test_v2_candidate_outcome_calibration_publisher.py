from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.cli import v2_candidate_outcome_calibration_publisher as publisher
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_archive_v2 import (
    _revision_pair,
    _writer,
)
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


def test_runtime_streams_only_matured_revisions_after_full_archive_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, ...]] = []

    class _Reader:
        def copy_locked_snapshot(self, path: Path):
            path.write_text("snapshot")
            return {"source_size_bytes": 8, "snapshot_sha256": "a" * 64}

        def read_verified_projections_by_sequence_with_verification(
            self,
            *,
            archive_sequences: tuple[int, ...],
            projector,
        ):
            calls.append(archive_sequences)
            return (
                SimpleNamespace(
                    verified=True,
                    terminal_chain_sha256="c" * 64,
                    matured_revision_count=0,
                ),
                (),
            )

    class _Client:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def get(self, key: str) -> str:
            assert key == publisher.ACTIVE_REGISTRY_KEY
            return json.dumps(_registry())

        def set(self, key: str, value: str) -> None:
            self.values[key] = value

    monkeypatch.setattr(publisher, "_archive_reader", lambda _path: _Reader())
    client = _Client()

    status = publisher.process_once(
        client=client,
        archive_path=tmp_path / "candidate-outcomes.jsonl",
        state_root=tmp_path / "calibration",
        generated_at_ms=3_000_000,
    )

    assert calls == [(2,)]
    assert status["status"] == "BLOCKED_INSUFFICIENT_OR_INVALID_MATURED_EVIDENCE"
    assert status["source_matured_revision_count"] == 0
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False


def test_archive_reader_rejects_self_signed_alternate_writer_key(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    writer, _, _ = _writer(path)
    first, second = _revision_pair()
    writer.append(first, signed_at_ms=first.record_available_at_ms)
    writer.append(second, signed_at_ms=second.record_available_at_ms)

    with pytest.raises(
        publisher.CandidateCalibrationPublisherError,
        match="public_key_untrusted",
    ):
        publisher._archive_reader(path)
