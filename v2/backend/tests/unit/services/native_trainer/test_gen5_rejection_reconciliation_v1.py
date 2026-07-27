from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.services.native_trainer import gen5_rejection_reconciliation_v1 as subject
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    Gen5BackfillConfig,
)


def _config(tmp_path: Path) -> Gen5BackfillConfig:
    return Gen5BackfillConfig(
        source_ledger_path=tmp_path / "source.sqlite3",
        source_label_archive_path=tmp_path / "labels.sqlite3",
        cost_store_root=tmp_path / "cost",
        state_root=tmp_path / "state",
    )


@pytest.fixture
def fixed_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Gen5BackfillConfig:
    config = _config(tmp_path)
    config.cost_store_root.mkdir()
    monkeypatch.setattr(
        subject,
        "validate_existing_fixed_snapshot",
        lambda _config: {
            "snapshot_id": "fixed-snapshot",
            "manifest_sha256": "a" * 64,
            "training_observed_at": "2026-07-27T20:00:00.000000Z",
            "databases": {"label": {"snapshot_high_water": {"receipt_sha256": "c" * 64}}},
        },
    )
    monkeypatch.setattr(subject, "_imported_sequences", lambda _config: (1,))
    monkeypatch.setattr(subject, "DurableFeatureSnapshotLedger", lambda _path: object())
    monkeypatch.setattr(subject, "DurableCanonical5mLabelArchive", lambda _path: object())
    monkeypatch.setattr(
        subject,
        "derive_label_archive_fixed_observation_proof_v1",
        lambda **_kwargs: (
            {"archive_chain_sha256": "b" * 64},
            {"high_water_sha256": "e" * 64},
        ),
    )
    return config


def test_rebuild_assigns_one_deterministic_primary_reason_per_sequence(
    fixed_sources: Gen5BackfillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def scan(**kwargs: object) -> object:
        kwargs["observation_consumer"]({"high_water_sha256": "d" * 64})  # type: ignore[operator]
        kwargs["page_consumer"](  # type: ignore[operator]
            (
                SimpleNamespace(sequence=1, durable_snapshot_id="imported"),
                SimpleNamespace(sequence=2, durable_snapshot_id="rejected"),
            ),
            (),
        )
        return SimpleNamespace(high_water_sha256="d" * 64)

    monkeypatch.setattr(subject, "load_profiled_training_ledger_fixed_observation_v1", scan)
    monkeypatch.setattr(
        subject,
        "build_finalized_label_binding_v1",
        lambda **_kwargs: (
            None,
            (
                "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH",
                "LABEL_ARCHIVE_RANGE_END_MISSING",
            ),
        ),
    )

    evidence = subject.build_gen5_rejection_sequence_evidence(fixed_sources)

    assert evidence["source_strict_eligible_count"] == 2
    assert evidence["imported_sequence_count"] == 1
    assert evidence["rejected_sequence_count"] == 1
    assert evidence["rejected_sequence_reasons"] == [
        {
            "sequence": 2,
            "durable_snapshot_id": "rejected",
            "primary_reason": "LABEL_ARCHIVE_RANGE_END_MISSING",
            "supporting_reasons": [
                "LABEL_ARCHIVE_RANGE_END_MISSING",
                "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH",
            ],
        }
    ]
    assert evidence["one_primary_reason_per_rejected_sequence"] is True
    assert evidence["label_archive_receipt_sha256"] == "c" * 64
    assert evidence["label_fixed_observation_high_water_sha256"] == "e" * 64
    assert evidence["exchange_action_taken"] is False


def test_rebuild_marks_a_buildable_missing_row_unexplained_and_fail_closed(
    fixed_sources: Gen5BackfillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def scan(**kwargs: object) -> object:
        kwargs["observation_consumer"]({"high_water_sha256": "d" * 64})  # type: ignore[operator]
        kwargs["page_consumer"](  # type: ignore[operator]
            (
                SimpleNamespace(sequence=1, durable_snapshot_id="imported"),
                SimpleNamespace(sequence=2, durable_snapshot_id="missing"),
            ),
            (),
        )
        return SimpleNamespace(high_water_sha256="d" * 64)

    monkeypatch.setattr(subject, "load_profiled_training_ledger_fixed_observation_v1", scan)
    monkeypatch.setattr(
        subject,
        "build_finalized_label_binding_v1",
        lambda **_kwargs: ({"binding": True}, ()),
    )
    monkeypatch.setattr(
        subject,
        "_reconstructed_record_from_verified_label_binding",
        lambda **_kwargs: {"snapshot_id": "row", "content_sha256": "e" * 64},
    )
    monkeypatch.setattr(subject, "_build_row", lambda *_args: {})

    evidence = subject.build_gen5_rejection_sequence_evidence(fixed_sources)

    assert evidence["rejected_sequence_reasons"][0]["primary_reason"] == ("UNEXPLAINED_IMPORT_DROP")
    assert evidence["one_primary_reason_per_rejected_sequence"] is False
