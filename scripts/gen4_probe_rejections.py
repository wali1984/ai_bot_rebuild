#!/usr/bin/env python3
"""Bounded probe: why don't authenticated ledger rows reach training?

Reuses the cached label-integrity proof (no OOM-prone re-verify) and reads ONE
ledger page, then reports loader exclusions + canonical-label-path rejection
reasons for the admitted samples. Read-only; no writes."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    default_ledger_path,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    load_profiled_training_ledger_v1,
)

LEDGER_PATH = default_ledger_path().resolve()
COST_STORE_ROOT = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
LABEL_ARCHIVE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "canonical_finalized_5m_label_archive.sqlite3"
)
INTEGRITY_CK = Path(
    "/home/wali/ai_bot_local_data/gen4_challenger_archive/"
    "profiled_training_challenger_label_integrity_checkpoint_v1.json"
)


def main() -> int:
    observed = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    ledger = DurableFeatureSnapshotLedger(LEDGER_PATH)
    label_archive = DurableCanonical5mLabelArchive(LABEL_ARCHIVE_PATH)
    integrity = json.load(open(INTEGRITY_CK))["integrity_proof"]

    result = {"pages": [], "loader_exclusions": {}, "label_path_status": {}, "label_rejection_reasons": {}}
    excl: Counter[str] = Counter()
    status: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    admitted_total = 0

    after_sequence = 0
    cursor = None
    src_cache: dict = {}
    txn_cache: set = set()
    for page_i in range(3):  # first 3 pages (~96 scanned records) is representative
        batch = load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=COST_STORE_ROOT,
            training_observed_at=observed,
            scan_limit=32,
            after_sequence=after_sequence,
            page_cursor=cursor,
            _verified_source_entries_cache=src_cache,
        )
        admitted_total += len(batch.samples)
        for ex in batch.exclusions:
            excl[str(ex.reason)] += 1
        for sample in batch.samples:
            label_rows, label_proof = label_archive.verified_label_path(
                symbol=sample.symbol,
                decision_time=sample.decision_time,
                training_observed_at=observed,
                horizon_seconds=sample.expected_holding_horizon_seconds,
                archive_integrity_proof=integrity,
                require_receipt_committed_by_observation=True,
                _verified_transaction_cache=txn_cache,
            )
            st = label_proof.get("status")
            status[str(st)] += 1
            if st != "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH":
                for r in (label_proof.get("rejection_reasons") or ["CANONICAL_LABEL_PATH_UNVERIFIED"]):
                    reasons[str(r)] += 1
        result["pages"].append({
            "page": page_i,
            "scanned_record_count": batch.scanned_record_count,
            "admitted_samples": len(batch.samples),
            "exclusions": len(batch.exclusions),
            "next_after_sequence": batch.next_after_sequence,
        })
        after_sequence = batch.next_after_sequence
        cursor = batch.next_cursor
        if cursor is None:
            break

    result["admitted_sample_total"] = admitted_total
    result["loader_exclusions"] = dict(sorted(excl.items()))
    result["label_path_status"] = dict(sorted(status.items()))
    result["label_rejection_reasons"] = dict(sorted(reasons.items()))
    print("PROBE_RESULT", json.dumps(result, indent=2, sort_keys=True), flush=True)
    out = REPO_ROOT / ".local_models/paper_provisional/gen4/probe_rejections.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("WROTE", str(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
