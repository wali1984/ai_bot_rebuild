from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.gen5_backfill_reconciliation_v1 import (
    _reconcile_verified_snapshot,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    Gen5BackfillConfig,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Gen5BackfillConfig, dict[str, Any], dict[str, Any]]:
    state = tmp_path / "state"
    ledger = state / "snapshots" / "durable_feature_snapshot_ledger.sqlite3"
    ledger.parent.mkdir(parents=True)
    observed = "2026-07-27T20:00:00.000000Z"
    observed_us = 1_785_182_400_000_000
    with sqlite3.connect(ledger) as connection:
        connection.execute(
            """
            CREATE TABLE feature_snapshot_records (
                sequence INTEGER PRIMARY KEY,
                strict_training_eligible INTEGER NOT NULL,
                ppo_decision_time_us INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO feature_snapshot_records VALUES (?, 1, ?)",
            [(1, observed_us - 2), (2, observed_us - 1)],
        )
    labels = state / "snapshots" / "canonical_finalized_5m_label_archive.sqlite3"
    labels.touch()
    cost_store = tmp_path / "cost-store"
    cost_store.mkdir()
    config = Gen5BackfillConfig(
        source_ledger_path=tmp_path / "unused-live-ledger.sqlite3",
        source_label_archive_path=tmp_path / "unused-live-labels.sqlite3",
        cost_store_root=cost_store,
        state_root=state,
    )
    manifest = {
        "snapshot_id": "fixed-snapshot-1",
        "manifest_sha256": "a" * 64,
        "training_observed_at": observed,
        "databases": {"feature": {"snapshot_high_water": {"high_water_sequence": 2}}},
    }
    records = {
        "snapshot-1": {"content_sha256": "1" * 64, "profiled_ledger_sequence": 1},
        "snapshot-2": {"content_sha256": "2" * 64, "profiled_ledger_sequence": 2},
    }
    archive = config.challenger_archive_root
    archive.mkdir(parents=True)
    (archive / "manifest.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "snapshot_id": snapshot_id,
                    "content_sha256": record["content_sha256"],
                },
                sort_keys=True,
            )
            + "\n"
            for snapshot_id, record in records.items()
        ),
        encoding="utf-8",
    )
    _write_json(
        config.status_path,
        {
            "completed": True,
            "rejected_rows": 0,
            "rejections_by_reason": {},
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
    )
    _write_json(
        config.importer_checkpoint_path,
        {
            "completed": True,
            "completed_shards": 1,
            "next_after_sequence": 2,
            "last_completed_sequence": 2,
        },
    )
    config.progress_path.write_text(
        json.dumps(
            {
                "snapshot_id": manifest["snapshot_id"],
                "completed_shards": 1,
                "next_after_sequence": 2,
                "completed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return config, manifest, records


def test_reconciliation_accepts_exact_complete_zero_rejection_corpus(
    tmp_path: Path,
) -> None:
    config, manifest, records = _fixture(tmp_path)

    def loader(snapshot_id: str, **_kwargs: Any) -> dict[str, Any]:
        return records[snapshot_id]

    report, identity = _reconcile_verified_snapshot(
        config,
        manifest,
        snapshot_loader=loader,
        row_builder=lambda _identity, record: dict(record),
    )

    assert report["accepted"] is True
    assert report["source_strict_eligible_rows"] == 2
    assert report["imported_rich_binding_rows"] == 2
    assert report["rejected_rows"] == 0
    assert report["missing_source_sequences"] == []
    assert len(identity["rows"]) == 2
    assert identity["exchange_action_taken"] is False


def test_reconciliation_rejects_missing_row_without_exact_sequence_reason(
    tmp_path: Path,
) -> None:
    config, manifest, records = _fixture(tmp_path)
    records.pop("snapshot-2")
    first_line = (
        config.challenger_archive_root.joinpath("manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    config.challenger_archive_root.joinpath("manifest.jsonl").write_text(
        first_line + "\n", encoding="utf-8"
    )
    status = json.loads(config.status_path.read_text(encoding="utf-8"))
    status["rejected_rows"] = 1
    status["rejections_by_reason"] = {"LABEL_HORIZON_NOT_MATURED": 1}
    _write_json(config.status_path, status)

    report, _ = _reconcile_verified_snapshot(
        config,
        manifest,
        snapshot_loader=lambda snapshot_id, **_kwargs: records[snapshot_id],
        row_builder=lambda _identity, record: dict(record),
    )

    assert report["accepted"] is False
    assert report["missing_source_sequences"] == [2]
    assert report["acceptance_checks"]["source_strict_rows_reconciled"] is True
    assert report["acceptance_checks"]["exact_rejection_sequence_mapping"] is False
