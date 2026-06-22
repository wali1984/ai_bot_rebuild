"""V2 native trainer baseline evaluator CLI.

Reads the V2-native dataset rows written by the dataset builder,
evaluates baseline strategies (hold, contract-only, simple EMA/RSI,
legacy-mirror) and a small trained logistic baseline. If the trained
baseline is publishable (positive after-cost expectancy on the
held-out validation set, beats hold) the CLI also publishes shadow
predictions to ``v2:prediction:{symbol}:{tf}`` under a strict
paper/shadow contract:

* trainer_source = V2_NATIVE_BASELINE_PAPER_SHADOW
* model_source = BASELINE_NOT_PRODUCTION
* model_readiness = NOT_PRODUCTION_READY
* paper_fill_allowed = False (paper-fill gate stays the source of truth)
* live_gate = blocked_human_only
* live_symbols = []

Then it consolidates the dashboard payload, GO_NO_GO marker, and
report under the packet directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))


from v2.backend.app.services.native_trainer.baseline_model import (  # noqa: E402
    V2BaselinePublisher,
    evaluate_all_baselines,
    publish_baseline_predictions,
)
from v2.backend.app.services.native_trainer.dataset_builder import (  # noqa: E402
    DatasetBuildResult,
    DatasetRow,
    V2OnlyReader,
    build_dataset_for_universe,
    build_quality_report,
    build_rows_from_replay_bundles,
    default_dataset_paths,
    default_replay_bundles_path,
    load_label_rows,
    _extract_feature_vector,  # noqa: F401  (used by row reconstruction tests)
    _index_labels_by_snapshot,
)
from v2.backend.app.services.native_trainer.packet import (  # noqa: E402
    default_packet_paths,
    emit_packet,
)


def _try_localhost_reader() -> V2OnlyReader:
    try:
        import redis  # type: ignore
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=2.0)
        client.ping()
        return V2OnlyReader(client=client)
    except Exception:
        return V2OnlyReader(client=None)


def _try_localhost_publisher() -> V2BaselinePublisher:
    try:
        import redis  # type: ignore
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=2.0)
        client.ping()
        return V2BaselinePublisher(client=client)
    except Exception:
        return V2BaselinePublisher(client=None)


def _row_from_dict(d: dict[str, Any]) -> DatasetRow:
    return DatasetRow(
        row_id=str(d.get("row_id") or ""),
        symbol=str(d.get("symbol") or ""),
        timeframe=str(d.get("timeframe") or "1m"),
        feature_snapshot_id=str(d.get("feature_snapshot_id") or ""),
        generated_at=str(d.get("generated_at") or ""),
        feature_vector=dict(d.get("feature_vector") or {}),
        missing_feature_flags=list(d.get("missing_feature_flags") or []),
        stale_feature_flags=list(d.get("stale_feature_flags") or []),
        feature_freshness_state=str(d.get("feature_freshness_state") or ""),
        label=str(d.get("label") or "label_missing"),
        after_cost_return_bps=d.get("after_cost_return_bps"),
        max_favorable_bps=d.get("max_favorable_bps"),
        max_adverse_bps=d.get("max_adverse_bps"),
        paper_gate_status=d.get("paper_gate_status"),
        paper_gate_block_reasons=list(d.get("paper_gate_block_reasons") or []),
        risk_decision_context=d.get("risk_decision_context"),
        altdata_context=d.get("altdata_context"),
        legacy_reference_action=d.get("legacy_reference_action"),
        classification=str(d.get("classification") or "INSUFFICIENT_EVIDENCE"),
        source_lineage=list(d.get("source_lineage") or []),
        feature_cutoff=d.get("feature_cutoff"),
        available_at=d.get("available_at"),
        decision_time_est=d.get("decision_time_est"),
        candle_closed_confirmed=d.get("candle_closed_confirmed"),
        candle_open_time=d.get("candle_open_time"),
        candle_close_time=d.get("candle_close_time"),
        masa_feature_cutoff=d.get("masa_feature_cutoff"),
        ppo_feature_cutoff=d.get("ppo_feature_cutoff"),
        market_state_integrity_score=d.get("market_state_integrity_score"),
        accepted_for_training=d.get("accepted_for_training"),
        training_reject_reasons=list(d.get("training_reject_reasons") or []),
        side=d.get("side"),
        action=d.get("action"),
        decision_time=d.get("decision_time"),
        entry_feature_available_at=d.get("entry_feature_available_at"),
        entry_feature_generated_at=d.get("entry_feature_generated_at"),
        prediction_generated_at=d.get("prediction_generated_at"),
        entry_feature_cutoff=d.get("entry_feature_cutoff"),
        entry_feature_candle_closed_confirmed=d.get(
            "entry_feature_candle_closed_confirmed"
        ),
        bundle_generated_at=d.get("bundle_generated_at"),
        source_event_time=d.get("source_event_time"),
    )


def _load_dataset_rows_from_disk(path: Path) -> list[DatasetRow]:
    rows: list[DatasetRow] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(_row_from_dict(json.loads(line)))
            except (TypeError, ValueError):
                continue
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate V2-native baseline strategies and a small trained "
            "logistic baseline. Optionally publish shadow predictions to "
            "v2:prediction:* (paper/shadow only, paper_fill_allowed=False)."
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
        help="Do not connect to Redis (audit-only).",
    )
    parser.add_argument(
        "--rebuild-dataset",
        action="store_true",
        help=(
            "Rebuild the dataset from V2-owned evidence before evaluating "
            "(otherwise read the existing rows JSONL on disk)."
        ),
    )
    parser.add_argument(
        "--max-label-rows",
        type=int,
        default=None,
        help="Cap on replay-outcome bundles loaded when --rebuild-dataset is set.",
    )
    parser.add_argument(
        "--minimum-train-rows",
        type=int,
        default=64,
        help=(
            "Minimum number of TRAINABLE rows required before a logistic "
            "baseline is trained. Default 64 so that an unseeded dataset "
            "does not pretend to be ready."
        ),
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help=(
            "Do not publish baseline predictions even when publishable. "
            "Useful for evaluation-only runs."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    dataset_paths = default_dataset_paths(repo_root)
    packet_paths = default_packet_paths(repo_root)
    replay_bundles_path = default_replay_bundles_path(repo_root)

    if args.rebuild_dataset:
        reader = V2OnlyReader(client=None) if args.no_redis else _try_localhost_reader()
        labels = load_label_rows(replay_bundles_path, max_rows=args.max_label_rows)
        label_index = _index_labels_by_snapshot(labels)
        build_result = build_dataset_for_universe(
            reader=reader,
            label_rows_by_snapshot=label_index,
        )
        replay_rows = build_rows_from_replay_bundles(
            replay_bundles_path, max_rows=args.max_label_rows,
        )
        build_result.rows.extend(replay_rows)
        quality = build_quality_report(build_result.rows)
        from v2.backend.app.services.native_trainer.dataset_builder import (
            emit_dataset_artifacts,
        )
        emit_dataset_artifacts(
            paths=dataset_paths,
            result=build_result,
            quality=quality,
        )
    else:
        rows_path = (
            dataset_paths.packet_dir / "v2_native_trainer_dataset_rows.jsonl"
        )
        rows = _load_dataset_rows_from_disk(rows_path)
        build_result = DatasetBuildResult(rows=rows)
        quality = build_quality_report(rows)

    eval_result = evaluate_all_baselines(
        build_result.rows,
        minimum_train_rows=args.minimum_train_rows,
    )

    publisher_result: dict[str, Any] | None = None
    if (
        not args.no_publish
        and eval_result.publishable_baseline_available
        and eval_result.trained_model is not None
    ):
        publisher = (
            V2BaselinePublisher(client=None)
            if args.no_redis
            else _try_localhost_publisher()
        )
        publisher_result = publish_baseline_predictions(
            rows=build_result.rows,
            model=eval_result.trained_model,
            publisher=publisher,
        )

    packet_result = emit_packet(
        paths=packet_paths,
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=publisher_result,
    )

    print(json.dumps({
        "go_no_go": packet_result.go_no_go,
        "train_count": eval_result.train_count,
        "validation_count": eval_result.validation_count,
        "publishable_baseline_available": (
            eval_result.publishable_baseline_available
        ),
        "publisher_published_count": (
            publisher_result["published_count"] if publisher_result else 0
        ),
        "publisher_old_redis_write_attempts": (
            publisher_result["old_redis_write_attempts"]
            if publisher_result else 0
        ),
        "paths_written": [str(p) for p in packet_result.paths_written],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
