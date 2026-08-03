"""Run the paper-only generation-5 fixed-observation corpus backfill."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    default_ledger_path,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    DEFAULT_COST_STORE_ROOT,
    DEFAULT_LABEL_ARCHIVE_PATH,
    DEFAULT_STATE_ROOT,
    Gen5BackfillConfig,
    run_snapshot_backfill,
)


def _path_env(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else fallback


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the live corpus with SQLite online backup and resume the "
            "authenticated generation-5 importer against immutable snapshots."
        )
    )
    parser.add_argument(
        "--source-ledger",
        type=Path,
        default=_path_env("GEN5_SOURCE_LEDGER_PATH", default_ledger_path()),
    )
    parser.add_argument(
        "--source-label-archive",
        type=Path,
        default=_path_env("GEN5_SOURCE_LABEL_ARCHIVE_PATH", DEFAULT_LABEL_ARCHIVE_PATH),
    )
    parser.add_argument(
        "--cost-store-root",
        type=Path,
        default=_path_env("GEN5_COST_STORE_ROOT", DEFAULT_COST_STORE_ROOT),
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=_path_env("GEN5_BACKFILL_STATE_ROOT", DEFAULT_STATE_ROOT),
    )
    parser.add_argument("--shard-size", type=int, default=32)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    config = Gen5BackfillConfig(
        source_ledger_path=arguments.source_ledger,
        source_label_archive_path=arguments.source_label_archive,
        cost_store_root=arguments.cost_store_root,
        state_root=arguments.state_root,
        shard_size=arguments.shard_size,
    )
    status = run_snapshot_backfill(config)
    print("GEN5_BACKFILL_COMPLETE", json.dumps(status, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
