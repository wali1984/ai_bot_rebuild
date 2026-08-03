#!/usr/bin/env python3
"""Gen-4 diagnostic: single-pass import over the FULL ledger to capture the
exact rejection_reasons Counter (why authenticated rows aren't reaching
training). Paper-only, read-only on ledger; writes sparse records to a
throwaway diag archive only."""
from __future__ import annotations

import json
import sys
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
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    import_profiled_training_ledger_to_challenger_archive_v1,
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
DIAG_ROOT = Path("/home/wali/ai_bot_local_data/gen4_diag_archive")


def main() -> int:
    observed = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    ledger = DurableFeatureSnapshotLedger(LEDGER_PATH)
    label_archive = DurableCanonical5mLabelArchive(LABEL_ARCHIVE_PATH)
    DIAG_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = import_profiled_training_ledger_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=COST_STORE_ROOT,
        label_archive=label_archive,
        challenger_archive_root=DIAG_ROOT,
        training_observed_at=observed,
        page_size=32,
    )
    summary = {
        "training_observed_at": result.training_observed_at,
        "source_scanned_record_count": result.source_scanned_record_count,
        "source_admitted_sample_count": result.source_admitted_sample_count,
        "source_exclusion_count": result.source_exclusion_count,
        "label_paths_verified": result.label_paths_verified,
        "imported_rows": result.imported_rows,
        "duplicate_rows": result.duplicate_rows,
        "rejected_rows": result.rejected_rows,
        "rejection_reasons": result.rejection_reasons,
    }
    print("DIAG_RESULT", json.dumps(summary, indent=2, sort_keys=True), flush=True)
    out = REPO_ROOT / ".local_models/paper_provisional/gen4/diag_import_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("WROTE", str(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
