from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    Gen5BackfillConfig,
    load_or_create_fixed_snapshot,
    run_snapshot_backfill,
)


def _feature_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE feature_snapshot_records (
                sequence INTEGER PRIMARY KEY,
                strict_training_eligible INTEGER NOT NULL
            );
            CREATE TABLE feature_snapshot_ledger_heads (
                head_sequence INTEGER PRIMARY KEY,
                total_unique_rows INTEGER NOT NULL,
                archive_chain_sha256 TEXT NOT NULL,
                head_sha256 TEXT NOT NULL,
                commit_prepared_at TEXT NOT NULL
            );
            INSERT INTO feature_snapshot_records VALUES (1, 1);
            INSERT INTO feature_snapshot_ledger_heads VALUES (
                1, 1,
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                '2026-07-27T19:00:00.000000Z'
            );
            """
        )


def _label_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE canonical_5m_candles (
                sequence INTEGER PRIMARY KEY,
                candle_id TEXT NOT NULL
            );
            CREATE TABLE canonical_5m_append_receipts (
                total_unique_rows INTEGER NOT NULL,
                archive_chain_sha256 TEXT NOT NULL,
                commit_prepared_at TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL
            );
            INSERT INTO canonical_5m_candles VALUES (1, 'candle-1');
            INSERT INTO canonical_5m_append_receipts VALUES (
                1,
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                '2026-07-27T19:00:01.000000Z',
                'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
            );
            """
        )


def _config(tmp_path: Path) -> Gen5BackfillConfig:
    ledger = tmp_path / "live-feature.sqlite3"
    labels = tmp_path / "live-label.sqlite3"
    cost_store = tmp_path / "cost-store"
    cost_store.mkdir()
    _feature_database(ledger)
    _label_database(labels)
    return Gen5BackfillConfig(
        source_ledger_path=ledger,
        source_label_archive_path=labels,
        cost_store_root=cost_store,
        state_root=tmp_path / "state",
        shard_size=1,
    )


def test_fixed_snapshot_is_reused_after_live_source_advances(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manifest = load_or_create_fixed_snapshot(config)

    with sqlite3.connect(config.source_ledger_path) as connection:
        connection.execute("INSERT INTO feature_snapshot_records VALUES (2, 1)")
        connection.execute(
            """
            INSERT INTO feature_snapshot_ledger_heads VALUES (
                2, 2,
                'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
                '2026-07-27T19:01:00.000000Z'
            )
            """
        )

    reused = load_or_create_fixed_snapshot(config)
    with sqlite3.connect(
        f"{config.snapshot_ledger_path.resolve().as_uri()}?mode=ro", uri=True
    ) as connection:
        snapshot_rows = connection.execute(
            "SELECT COUNT(*) FROM feature_snapshot_records"
        ).fetchone()[0]

    assert reused == manifest
    assert snapshot_rows == 1
    assert manifest["databases"]["feature"]["snapshot_high_water"]["high_water_sequence"] == 1
    assert manifest["paper_only"] is True
    assert manifest["routes_to_live"] is False


def test_runner_persists_each_shard_and_completes_from_frozen_high_water(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    calls: list[int] = []

    def importer(**kwargs: Any) -> dict[str, Any]:
        calls.append(len(calls) + 1)
        root = Path(kwargs["challenger_archive_root"])
        root.mkdir(parents=True, exist_ok=True)
        blob_dir = root / "blobs" / "aa" / "bb"
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"row-{calls[-1]}.json"
        blob_path.write_text(
            json.dumps({"profiled_ledger_sequence": calls[-1]}) + "\n",
            encoding="utf-8",
        )
        with (root / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "snapshot_id": f"candidate-{calls[-1]}",
                        "blob_path": str(blob_path.relative_to(root)),
                    }
                )
                + "\n"
            )
        completed = len(calls) == 2
        checkpoint = {
            "completed_shards": len(calls),
            "next_after_sequence": len(calls),
            "completed": completed,
        }
        Path(kwargs["checkpoint_path"]).write_text(json.dumps(checkpoint) + "\n", encoding="utf-8")
        report = {
            "shard_number": len(calls),
            "imported_rows": 1,
            "duplicate_rows": 0,
            "rejections_by_reason": ({"LABEL_HORIZON_NOT_MATURED": 1} if len(calls) == 1 else {}),
        }
        return {"completed": completed, "shards": [report]}

    status = run_snapshot_backfill(config, importer=importer)

    progress = [
        json.loads(line) for line in config.progress_path.read_text(encoding="utf-8").splitlines()
    ]
    terminal = json.loads(config.terminal_receipt_path.read_text(encoding="utf-8"))
    assert calls == [1, 2]
    assert len(progress) == 2
    assert progress[-1]["next_after_sequence"] == 2
    assert status["completed"] is True
    assert status["completed_shards"] == 2
    assert status["imported_rows"] == 2
    assert status["rejected_rows"] == 1
    assert status["last_candidate_id"] == "candidate-2"
    assert status["last_ledger_sequence"] == 2
    assert terminal["exit_reason"] == "COMPLETED"
    assert terminal["exit_code"] == 0
    assert terminal["exchange_action_taken"] is False


def test_runner_writes_terminal_exception_receipt(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def importer(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("fixture-import-failure")

    with pytest.raises(RuntimeError, match="fixture-import-failure"):
        run_snapshot_backfill(config, importer=importer)

    terminal = json.loads(config.terminal_receipt_path.read_text(encoding="utf-8"))
    assert terminal["exit_reason"] == "EXCEPTION"
    assert terminal["exception_type"] == "RuntimeError"
    assert terminal["exception_message"] == "fixture-import-failure"
    assert terminal["safe_resume_command"].startswith("systemctl --user start")
    assert terminal["places_real_order"] is False


def test_runner_recovers_progress_when_checkpoint_was_fsynced_before_status(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    load_or_create_fixed_snapshot(config)
    config.challenger_archive_root.mkdir(parents=True)
    blob = config.challenger_archive_root / "blobs" / "aa" / "bb" / "row-1.json"
    blob.parent.mkdir(parents=True)
    blob.write_text('{"profiled_ledger_sequence":1}\n', encoding="utf-8")
    (config.challenger_archive_root / "manifest.jsonl").write_text(
        json.dumps(
            {
                "snapshot_id": "candidate-1",
                "blob_path": str(blob.relative_to(config.challenger_archive_root)),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config.importer_checkpoint_path.write_text(
        json.dumps(
            {
                "completed_shards": 1,
                "next_after_sequence": 1,
                "completed": False,
                "cumulative_imported_rows": 1,
                "cumulative_duplicate_rows": 0,
                "cumulative_rejected_rows": 2,
                "cumulative_rejections_by_reason": {"LABEL_HORIZON_NOT_MATURED": 2},
                "last_candidate_id": "source-candidate-1",
                "last_completed_sequence": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def importer(**kwargs: Any) -> dict[str, Any]:
        recovered = json.loads(config.status_path.read_text(encoding="utf-8"))
        assert recovered["recovered_from_checkpoint"] is True
        assert recovered["rejected_rows"] == 2
        assert recovered["last_candidate_id"] == "source-candidate-1"
        checkpoint = json.loads(config.importer_checkpoint_path.read_text())
        checkpoint.update(
            {
                "completed_shards": 2,
                "next_after_sequence": 2,
                "completed": True,
                "cumulative_imported_rows": 1,
                "cumulative_rejected_rows": 3,
                "cumulative_rejections_by_reason": {"LABEL_HORIZON_NOT_MATURED": 3},
                "last_candidate_id": "source-candidate-2",
                "last_completed_sequence": 2,
            }
        )
        config.importer_checkpoint_path.write_text(json.dumps(checkpoint) + "\n")
        return {
            "completed": True,
            "shards": [
                {
                    "shard_number": 2,
                    "imported_rows": 0,
                    "duplicate_rows": 0,
                    "rejections_by_reason": {"LABEL_HORIZON_NOT_MATURED": 1},
                }
            ],
        }

    status = run_snapshot_backfill(config, importer=importer)

    assert status["completed"] is True
    assert status["completed_shards"] == 2
    assert status["rejected_rows"] == 3
    assert status["rejections_by_reason"] == {"LABEL_HORIZON_NOT_MATURED": 3}
    assert status["last_candidate_id"] == "source-candidate-2"
