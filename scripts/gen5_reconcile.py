#!/usr/bin/env python3
"""Reconcile the completed gen-5 snapshot backfill (FINAL PASS Phase 7 step 1).

Proves, against the FROZEN snapshot:
  strict_eligible_source_sequences == imported + rejected  (+ not-yet-processed)
  every imported row is unique (no conflicting duplicate content)
  imported sequences are a subset of strict-eligible (no spurious rows)
  every strict-eligible sequence is imported OR has an exact rejection reason
  every imported row passes load_snapshot(verify=True) AND
    build_serving_dataset_v2._build_row (i.e. is training-admissible)

Reads only; writes reconciliation_report.json into the backfill state root.
Run after the service reports completed=true (or ad hoc for a partial view).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STATE = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1")
SNAP_LEDGER = STATE / "snapshots" / "durable_feature_snapshot_ledger.sqlite3"
ARCHIVE = STATE / "challenger_archive"
STATUS = STATE / "status.json"
REPORT = STATE / "reconciliation_report.json"


def _strict_eligible_sequences() -> set[int]:
    with sqlite3.connect(f"file:{SNAP_LEDGER}?mode=ro", uri=True) as c:
        rows = c.execute(
            "SELECT sequence FROM feature_snapshot_records WHERE strict_training_eligible=1"
        ).fetchall()
    return {int(r[0]) for r in rows}


def main() -> int:
    from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
        iter_index_records,
        load_snapshot,
    )
    from v2.backend.app.services.prediction_serving.serving_dataset_v2 import _build_row

    status = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    strict = _strict_eligible_sequences()

    # Enumerate imported records from the challenger archive and re-verify each.
    imported_ids: set[str] = set()
    content_by_id: dict[str, str] = {}
    verify_failures: list[dict] = []
    build_row_failures: list[dict] = []
    imported_sequences: set[int] = set()
    n = 0
    for ix in iter_index_records(ARCHIVE):
        sid = ix.get("snapshot_id")
        if not sid:
            continue
        n += 1
        if sid in imported_ids:
            # duplicate snapshot_id — check content conflict
            if content_by_id.get(sid) != ix.get("content_sha256"):
                verify_failures.append({"snapshot_id": sid, "reason": "CONFLICTING_DUPLICATE_CONTENT"})
            continue
        imported_ids.add(sid)
        content_by_id[sid] = ix.get("content_sha256")
        rec = load_snapshot(sid, root=ARCHIVE, verify=True)
        if not isinstance(rec, dict):
            verify_failures.append({"snapshot_id": sid, "reason": "LOAD_SNAPSHOT_VERIFY_FALSE"})
            continue
        seq = rec.get("profiled_ledger_sequence")
        if isinstance(seq, int):
            imported_sequences.add(seq)
        try:
            row = _build_row({"snapshot_id": sid, "content_sha256": rec.get("content_sha256")}, rec)
            if sum(row.get("missing_mask") or []) != 0:
                build_row_failures.append({"snapshot_id": sid, "reason": "REQUIRED_FEATURE_MISSING"})
        except Exception as exc:  # noqa: BLE001
            build_row_failures.append({"snapshot_id": sid, "reason": str(exc)[:120]})

    imported = len(imported_ids)
    rejected = int(status.get("rejected_rows") or 0)
    rejections_by_reason = status.get("rejections_by_reason") or {}
    completed = bool(status.get("completed"))
    next_seq = int(status.get("next_after_sequence") or 0)

    imported_not_strict = sorted(imported_sequences - strict)
    strict_not_processed = sorted(s for s in strict if s > next_seq) if not completed else []
    # strict-eligible sequences that were passed (<= next_seq) but neither imported nor (countable) rejected
    processed_strict = {s for s in strict if s <= next_seq}
    strict_unaccounted = sorted(processed_strict - imported_sequences) if completed else []

    report = {
        "schema_version": "gen5_backfill_reconciliation_v1",
        "generated_utc": status.get("generated_at"),
        "snapshot_id": status.get("snapshot_id"),
        "backfill_completed": completed,
        "frozen_strict_eligible_count": len(strict),
        "imported_unique_rows": imported,
        "rejected_rows": rejected,
        "rejections_by_reason": rejections_by_reason,
        "generic_unverified_reasons": [r for r in rejections_by_reason if "UNVERIFIED" in str(r).upper() or str(r).upper() == "OTHER"],
        "reconciliation_identity": f"{len(strict)} strict == {imported} imported + {rejected} rejected + {len(strict_not_processed)} not_yet_processed",
        "reconciles": completed and (imported + rejected == len(strict)),
        "imported_sequences_not_strict_eligible": imported_not_strict,
        "strict_eligible_not_yet_processed": len(strict_not_processed),
        "strict_eligible_processed_but_unaccounted": strict_unaccounted,
        "no_conflicting_duplicates": all(f["reason"] != "CONFLICTING_DUPLICATE_CONTENT" for f in verify_failures),
        "all_imported_pass_verify_true": len([f for f in verify_failures if f["reason"] != "CONFLICTING_DUPLICATE_CONTENT"]) == 0,
        "verify_failures": verify_failures[:50],
        "all_imported_pass_build_row": not build_row_failures,
        "build_row_failures": build_row_failures[:50],
        "paper_only": True, "live_gate": "blocked_human_only",
    }
    report["reconciliation_pass"] = bool(
        report["reconciles"]
        and report["all_imported_pass_verify_true"]
        and report["all_imported_pass_build_row"]
        and report["no_conflicting_duplicates"]
        and not report["imported_sequences_not_strict_eligible"]
        and not report["strict_eligible_processed_but_unaccounted"]
        and not report["generic_unverified_reasons"]
    )
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in (
        "backfill_completed", "frozen_strict_eligible_count", "imported_unique_rows",
        "rejected_rows", "reconciles", "all_imported_pass_verify_true",
        "all_imported_pass_build_row", "reconciliation_pass")}, indent=2))
    return 0 if report["reconciliation_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
