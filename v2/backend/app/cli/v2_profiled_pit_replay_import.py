"""Import one bounded authenticated profiled PIT replay shard for the challenger."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.profiled_pit_replay_importer_v1 import (
    import_next_profiled_pit_replay_shard_v1,
)

DEFAULT_RUNTIME_ROOT = Path("/home/wali/ai_bot_local_data/v2_native_trainer")
DEFAULT_FEATURE_LEDGER_PATH = DEFAULT_RUNTIME_ROOT / "durable_feature_snapshot_ledger.sqlite3"
DEFAULT_LABEL_ARCHIVE_PATH = DEFAULT_RUNTIME_ROOT / "canonical_finalized_5m_label_archive.sqlite3"
DEFAULT_COST_STORE_ROOT = (
    DEFAULT_RUNTIME_ROOT
    / "profiled_base_publisher_v1"
    / "profiled-training-enrichment-cas"
)
DEFAULT_CHALLENGER_ARCHIVE_ROOT = DEFAULT_RUNTIME_ROOT / "durable_feature_snapshot_archive"
DEFAULT_CHECKPOINT_ROOT = DEFAULT_RUNTIME_ROOT / "profiled_pit_replay_importer_v1"


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-ledger-path", type=Path, default=DEFAULT_FEATURE_LEDGER_PATH)
    parser.add_argument("--label-archive-path", type=Path, default=DEFAULT_LABEL_ARCHIVE_PATH)
    parser.add_argument("--cost-store-root", type=Path, default=DEFAULT_COST_STORE_ROOT)
    parser.add_argument(
        "--challenger-archive-root",
        type=Path,
        default=DEFAULT_CHALLENGER_ARCHIVE_ROOT,
    )
    parser.add_argument("--checkpoint-root", type=Path, default=DEFAULT_CHECKPOINT_ROOT)
    parser.add_argument("--source-shard-rows", type=int, default=1)
    parser.add_argument("--training-observed-at", default=None)
    args = parser.parse_args(argv)
    result = import_next_profiled_pit_replay_shard_v1(
        ledger=DurableFeatureSnapshotLedger(args.feature_ledger_path),
        trusted_immutable_cost_store_root=args.cost_store_root,
        label_archive=DurableCanonical5mLabelArchive(args.label_archive_path),
        challenger_archive_root=args.challenger_archive_root,
        checkpoint_root=args.checkpoint_root,
        training_observed_at=args.training_observed_at or _utc_now(),
        source_shard_rows=args.source_shard_rows,
    )
    print(json.dumps(asdict(result), allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
