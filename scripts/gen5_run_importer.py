#!/usr/bin/env python3
"""Gen-5 backfill: run the REPAIRED shards importer (rich finalized_label_
binding_v1) over the FULL feature-snapshot ledger into a fresh, isolated
challenger archive. Paper-only; no activation, no Redis, no live."""
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

LEDGER_PATH = default_ledger_path().resolve()
COST_STORE_ROOT = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
LABEL_ARCHIVE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "canonical_finalized_5m_label_archive.sqlite3"
)
CHALLENGER_ROOT = Path("/home/wali/ai_bot_local_data/gen5_challenger_archive")
OUT = REPO_ROOT / ".local_models/paper_provisional/gen5/importer_result.json"


def main() -> int:
    observed = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    ledger = DurableFeatureSnapshotLedger(LEDGER_PATH)
    label_archive = DurableCanonical5mLabelArchive(LABEL_ARCHIVE_PATH)
    print("WIRING", json.dumps({
        "ledger_path": str(LEDGER_PATH),
        "cost_store_root": str(COST_STORE_ROOT),
        "label_archive_path": str(LABEL_ARCHIVE_PATH),
        "challenger_root": str(CHALLENGER_ROOT),
        "training_observed_at": observed,
    }, indent=2), flush=True)

    def progress(report):
        print("SHARD", json.dumps({
            k: report.get(k) for k in (
                "shard_number", "source_scanned_record_count",
                "source_admitted_sample_count", "source_exclusion_count",
                "imported_rows", "duplicate_rows", "label_paths_verified",
                "shards_remaining", "elapsed_seconds", "post_purge_counts",
            )
        }), flush=True)

    result = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=COST_STORE_ROOT,
        label_archive=label_archive,
        challenger_archive_root=CHALLENGER_ROOT,
        training_observed_at=observed,
        shard_size=32,
        max_shards=100000,
    )
    summary = {k: v for k, v in result.items() if k != "shards"}
    summary["num_shard_reports"] = len(result.get("shards", []))
    print("IMPORTER_RESULT", json.dumps(summary, indent=2, sort_keys=True), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("WROTE", str(OUT), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
