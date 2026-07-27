#!/usr/bin/env python3
"""Durable, restart-safe gen-5 rich-binding backfill (FINAL PASS Phase 7).

Runs the REPAIRED ledger->rich-binding importer against transactionally
consistent SQLite SNAPSHOTS of the live ledger + canonical label archive (SQLite
online backup API), so the live producers keep writing while the historical
import sees one immutable point-in-time corpus.

Restart-safe: the importer checkpoints per shard and resumes from
next_after_sequence; the fixed training_observed_at is persisted once and reused
across restarts. On ANY exit (normal, exception, or SIGTERM/SIGINT) a terminal
receipt is written with exit_reason / exception / signal / last sequence / RSS /
open FDs / elapsed / checkpoint_path / safe_resume_command.

Paper-only. No trading, no live authority. Reads live DBs read-only for the
snapshot, then imports only from the snapshot copies.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATA = Path("/home/wali/ai_bot_local_data/v2_native_trainer")
LIVE_LEDGER = DATA / "durable_feature_snapshot_ledger.sqlite3"
LIVE_LABELS = DATA / "canonical_finalized_5m_label_archive.sqlite3"
COST_STORE_ROOT = DATA / "profiled_base_publisher_v1" / "profiled-training-enrichment-cas"

SNAP_DIR = Path("/home/wali/ai_bot_local_data/gen5_backfill_snapshots")
SNAP_LEDGER = SNAP_DIR / "ledger_snapshot.sqlite3"
SNAP_LABELS = SNAP_DIR / "labels_snapshot.sqlite3"
SNAP_META = SNAP_DIR / "snapshot_manifest.json"
OBSERVED_AT_FILE = SNAP_DIR / "training_observed_at.txt"

CHALLENGER_ROOT = Path("/home/wali/ai_bot_local_data/gen5_challenger_archive")
RECEIPT = CHALLENGER_ROOT / "backfill_terminal_receipt.json"
HEARTBEAT = CHALLENGER_ROOT / "backfill_heartbeat.json"
CHECKPOINT = CHALLENGER_ROOT / "profiled_training_challenger_import_checkpoint_v1.json"

_started = time.monotonic()


def _utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0, 2)
    except Exception:
        pass
    return -1.0


def _open_fds() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except Exception:
        return -1


def _last_checkpoint() -> dict:
    try:
        return json.loads(CHECKPOINT.read_text())
    except Exception:
        return {}


def _write_receipt(exit_reason: str, *, exception_type=None, exception_message=None,
                   signal_number=None) -> None:
    cp = _last_checkpoint()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps({
        "schema_version": "gen5_backfill_terminal_receipt_v1",
        "generated_utc": _utc(),
        "exit_reason": exit_reason,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "signal_number": signal_number,
        "last_completed_shard": cp.get("completed_shards"),
        "last_completed_sequence": cp.get("next_after_sequence"),
        "checkpoint_completed": cp.get("completed"),
        "checkpoint_path": str(CHECKPOINT),
        "rss_mb": _rss_mb(),
        "open_fds": _open_fds(),
        "elapsed_seconds": round(time.monotonic() - _started, 2),
        "safe_resume_command": "systemctl --user restart ai-bot-v2-gen5-backfill.service",
        "paper_only": True, "live_gate": "blocked_human_only", "places_real_order": False,
    }, indent=2, sort_keys=True) + "\n")


def _signal_handler(signum, _frame):
    _write_receipt("SIGNAL", signal_number=int(signum))
    # re-raise default behaviour so the service records the signal exit
    raise SystemExit(128 + int(signum))


def _sqlite_snapshot(source: Path, destination: Path) -> dict:
    started = _utc()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(str(tmp)) as dst:
        src.backup(dst)  # transactionally consistent online backup (applies WAL)
    tmp.replace(destination)
    import hashlib
    sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {"source": str(source), "snapshot": str(destination), "sha256": sha,
            "snapshot_started_at": started, "snapshot_completed_at": _utc(),
            "bytes": destination.stat().st_size}


def _ensure_snapshots() -> dict:
    """Create immutable snapshots once; reuse on restart (idempotent)."""
    if SNAP_META.exists() and SNAP_LEDGER.exists() and SNAP_LABELS.exists():
        return json.loads(SNAP_META.read_text())
    print("SNAPSHOT creating transactionally-consistent copies...", flush=True)
    ledger_meta = _sqlite_snapshot(LIVE_LEDGER, SNAP_LEDGER)
    labels_meta = _sqlite_snapshot(LIVE_LABELS, SNAP_LABELS)
    # record high-water / row counts from the snapshots
    with sqlite3.connect(f"file:{SNAP_LEDGER}?mode=ro", uri=True) as c:
        n, hw = c.execute("SELECT COUNT(*), MAX(sequence) FROM feature_snapshot_records").fetchone()
        strict = c.execute("SELECT COUNT(*) FROM feature_snapshot_records WHERE strict_training_eligible=1").fetchone()[0]
    ledger_meta.update({"ledger_rows": n, "ledger_high_water_sequence": hw, "strict_eligible_rows": strict})
    with sqlite3.connect(f"file:{SNAP_LABELS}?mode=ro", uri=True) as c:
        labels_meta["canonical_5m_candles"] = c.execute("SELECT COUNT(*) FROM canonical_5m_candles").fetchone()[0]
    meta = {"schema_version": "gen5_backfill_snapshot_manifest_v1", "generated_utc": _utc(),
            "ledger": ledger_meta, "labels": labels_meta}
    SNAP_META.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print("SNAPSHOT done:", json.dumps({"ledger_rows": n, "strict_eligible": strict,
          "labels_candles": labels_meta["canonical_5m_candles"]}), flush=True)
    return meta


def _fixed_observed_at() -> str:
    if OBSERVED_AT_FILE.exists():
        return OBSERVED_AT_FILE.read_text().strip()
    observed = _utc()
    OBSERVED_AT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OBSERVED_AT_FILE.write_text(observed)
    return observed


def main() -> int:
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
        DurableCanonical5mLabelArchive,
    )
    from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
        DurableFeatureSnapshotLedger,
    )
    from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
        import_profiled_training_ledger_shards_to_challenger_archive_v1,
    )

    try:
        meta = _ensure_snapshots()
        observed = _fixed_observed_at()
        print("WIRING", json.dumps({
            "snapshot_ledger": str(SNAP_LEDGER), "snapshot_labels": str(SNAP_LABELS),
            "cost_store_root": str(COST_STORE_ROOT), "challenger_root": str(CHALLENGER_ROOT),
            "training_observed_at": observed,
            "frozen_high_water": meta["ledger"].get("ledger_high_water_sequence"),
            "strict_eligible_source_rows": meta["ledger"].get("strict_eligible_rows"),
        }, indent=2), flush=True)

        ledger = DurableFeatureSnapshotLedger(SNAP_LEDGER)
        labels = DurableCanonical5mLabelArchive(SNAP_LABELS)

        def progress(report: dict) -> None:
            cp = _last_checkpoint()
            hb = {"utc": _utc(), "shard_number": report.get("shard_number"),
                  "imported_rows": report.get("imported_rows"),
                  "duplicate_rows": report.get("duplicate_rows"),
                  "shards_remaining": report.get("shards_remaining"),
                  "next_after_sequence": cp.get("next_after_sequence"),
                  "rss_mb": _rss_mb(), "open_fds": _open_fds(),
                  "elapsed_seconds": round(time.monotonic() - _started, 2)}
            HEARTBEAT.write_text(json.dumps(hb, sort_keys=True) + "\n")
            print("SHARD", json.dumps(hb), flush=True)

        result = import_profiled_training_ledger_shards_to_challenger_archive_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=COST_STORE_ROOT,
            label_archive=labels,
            challenger_archive_root=CHALLENGER_ROOT,
            training_observed_at=observed,
            shard_size=32,
            max_shards=100000,
            progress_consumer=progress,
        )
        summary = {k: v for k, v in result.items() if k != "shards"}
        print("IMPORTER_RESULT", json.dumps(summary, indent=2, sort_keys=True), flush=True)
        _write_receipt("COMPLETED" if result.get("completed") else "STOPPED_NOT_COMPLETE")
        return 0
    except Exception as exc:  # noqa: BLE001 — record ANY exception in the receipt
        _write_receipt("EXCEPTION", exception_type=type(exc).__name__,
                       exception_message=str(exc)[:2000])
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
