"""V2 native trainer dataset builder CLI.

Reads V2-owned evidence ONLY (``v2:*`` Redis keys and the V2 post-hoc
replay-outcome JSONL store) and writes the typed dataset rows,
manifest, status, and quality report under
``claude_worklog/final_readiness/v2_native_trainer_dataset_and_baseline_model/latest/``.

The CLI never writes any non-``v2:*`` Redis key, never calls the
exchange, never modifies legacy, never enables live or canary, and
never weakens the paper-fill gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))


from v2.backend.app.services.native_trainer.dataset_builder import (  # noqa: E402
    V2OnlyReader,
    _index_labels_by_snapshot,
    build_dataset_for_universe,
    build_quality_report,
    build_rows_from_replay_bundles,
    default_dataset_paths,
    default_replay_bundles_path,
    emit_dataset_artifacts,
    load_label_rows,
)


def _try_localhost_reader() -> V2OnlyReader:
    try:
        import redis  # type: ignore
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=2.0)
        client.ping()
        return V2OnlyReader(client=client)
    except Exception:
        return V2OnlyReader(client=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a V2-native training / evaluation dataset from V2-owned "
            "evidence (features, TA, predictions, replay-outcome bundles). "
            "Paper / shadow only. Never claims native trainer readiness."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help=(
            "Do not connect to Redis. Useful for hermetic dry-runs and CI."
        ),
    )
    parser.add_argument(
        "--max-label-rows",
        type=int,
        default=None,
        help=(
            "Cap the number of replay-outcome bundles loaded for labels. "
            "Default: load all available bundles."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_dataset_paths(repo_root)
    replay_bundles_path = default_replay_bundles_path(repo_root)
    training_observed_at = datetime.now(timezone.utc)

    reader = V2OnlyReader(client=None) if args.no_redis else _try_localhost_reader()
    labels = load_label_rows(
        replay_bundles_path,
        max_rows=args.max_label_rows,
        training_observed_at=training_observed_at,
    )
    label_index = _index_labels_by_snapshot(labels)
    build_result = build_dataset_for_universe(
        reader=reader,
        label_rows_by_snapshot=label_index,
        training_observed_at=training_observed_at,
    )
    # Augment with rows derived directly from V2 replay-outcome bundles
    # (which carry orchestrator-decision features + after-cost labels).
    replay_rows = build_rows_from_replay_bundles(
        replay_bundles_path,
        max_rows=args.max_label_rows,
        training_observed_at=training_observed_at,
    )
    build_result.rows.extend(replay_rows)
    quality = build_quality_report(build_result.rows)
    written = emit_dataset_artifacts(
        paths=paths,
        result=build_result,
        quality=quality,
    )
    summary: dict[str, Any] = {
        "go_no_go_local": "V2_NATIVE_TRAINER_DATASET_PHASE_OK",
        "row_count": len(build_result.rows),
        "train_rows": quality.train_rows,
        "validation_rows": quality.validation_rows,
        "labels_loaded": build_result.labels_loaded,
        "minimum_sample_satisfied": quality.minimum_sample_satisfied,
        "non_v2_read_attempts": build_result.non_v2_read_attempts,
        "read_errors": build_result.read_errors,
        "paths_written": [str(p) for p in written],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
