#!/usr/bin/env python3
"""Gen-4 scratch: import the FULL profiled training ledger into a fresh,
isolated challenger archive. Paper-only, no activation, no Redis, no live."""
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
    import_profiled_training_ledger_shards_to_challenger_archive_v1,
)

# default_ledger_path() returns the .local_data (symlinked) path; the ledger
# read guard forbids symlinked parent components, so resolve to the real path
# under /home/wali/ai_bot_local_data (identical file).
LEDGER_PATH = default_ledger_path().resolve()
COST_STORE_ROOT = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
LABEL_ARCHIVE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "canonical_finalized_5m_label_archive.sqlite3"
)
# NOTE: /home/wali/ai_bot_local_data/v2_native_trainer is read-only (mode 555),
# so the fresh isolated archive goes at the writable .local_data root instead
# (== /home/wali/ai_bot_local_data/gen4_challenger_archive), which is the path
# explicitly allowed by the task write constraints.
CHALLENGER_ROOT = Path(
    "/home/wali/ai_bot_local_data/gen4_challenger_archive"
)


def main() -> int:
    observed = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    print("WIRING", json.dumps({
        "ledger_path": str(LEDGER_PATH),
        "ledger_exists": LEDGER_PATH.is_file(),
        "cost_store_root": str(COST_STORE_ROOT),
        "cost_store_exists": COST_STORE_ROOT.is_dir(),
        "label_archive_path": str(LABEL_ARCHIVE_PATH),
        "label_archive_exists": LABEL_ARCHIVE_PATH.is_file(),
        "challenger_root": str(CHALLENGER_ROOT),
        "training_observed_at": observed,
    }, indent=2), flush=True)

    ledger = DurableFeatureSnapshotLedger(LEDGER_PATH)
    label_archive = DurableCanonical5mLabelArchive(LABEL_ARCHIVE_PATH)

    def progress(report):
        print("SHARD", json.dumps({
            k: report.get(k) for k in (
                "shard_number", "source_scanned_record_count",
                "source_admitted_sample_count", "source_exclusion_count",
                "imported_rows", "duplicate_rows", "label_paths_verified",
                "minimums_met", "post_purge_counts",
            )
        }), flush=True)

    result = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=COST_STORE_ROOT,
        label_archive=label_archive,
        challenger_archive_root=CHALLENGER_ROOT,
        training_observed_at=observed,
        shard_size=32,          # MAX_IMPORT_PAGE_SIZE == 32 (64 is rejected)
        max_shards=100000,      # "process all" -> break happens on completed
    )
    # Drop the potentially huge shard list before dumping
    summary = {k: v for k, v in result.items() if k != "shards"}
    summary["num_shard_reports"] = len(result.get("shards", []))
    print("IMPORTER_RESULT", json.dumps(summary, indent=2, sort_keys=True), flush=True)
    out = REPO_ROOT / ".local_models/paper_provisional/gen4/importer_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("WROTE", str(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
