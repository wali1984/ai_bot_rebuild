"""Reconcile generation 5 and build its serving-compatible dataset artifacts."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    default_ledger_path,
)
from v2.backend.app.services.native_trainer.gen5_backfill_reconciliation_v1 import (
    REJECTION_SEQUENCE_EVIDENCE_FILENAME,
    reconcile_gen5_backfill,
)
from v2.backend.app.services.native_trainer.gen5_pit_regime_coverage_v1 import (
    build_pit_regime_coverage_v1,
)
from v2.backend.app.services.native_trainer.gen5_rejection_reconciliation_v1 import (
    build_gen5_rejection_sequence_evidence,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    DEFAULT_COST_STORE_ROOT,
    DEFAULT_LABEL_ARCHIVE_PATH,
    DEFAULT_STATE_ROOT,
    Gen5BackfillConfig,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (
    build_serving_dataset_v2,
)

BASELINE_RICH_ROWS = 215
MINIMUM_MATERIAL_ROWS = 323
MINIMUM_DISTINCT_UTC_DATES = 3
MINIMUM_COVERAGE_SPAN_DAYS = 4.0
BASELINE_LATEST_UTC_DATE = "2026-07-23"


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("DATASET_DECISION_TIME_NOT_UTC_AWARE")
    return parsed.astimezone(UTC)


def _coverage_report(
    dataset: Mapping[str, Any],
    manifest: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    *,
    reproducible: bool,
) -> dict[str, Any]:
    rows = dataset.get("rows")
    ordered_names = dataset.get("ordered_feature_names")
    if not isinstance(rows, list) or not isinstance(ordered_names, list) or not rows:
        raise ValueError("GEN5_DATASET_ROWS_MISSING")
    decision_times = [_parse_utc(str(row["decision_time"])) for row in rows]
    dates = sorted({value.date().isoformat() for value in decision_times})
    span_days = (max(decision_times) - min(decision_times)).total_seconds() / 86_400.0
    symbols = Counter(str(row["symbol"]) for row in rows)
    timeframes = Counter(str(row["timeframe"]) for row in rows)
    actions = Counter(str(row["target_action"]) for row in rows)
    splits = Counter(str(row["split"]) for row in rows)
    missing_counts = {str(name): 0 for name in ordered_names}
    for row in rows:
        mask = row.get("missing_mask")
        if not isinstance(mask, list) or len(mask) != len(ordered_names):
            raise ValueError("GEN5_DATASET_MISSING_MASK_INVALID")
        for index, missing in enumerate(mask):
            if bool(missing):
                missing_counts[str(ordered_names[index])] += 1
    missingness = {
        name: {
            "missing_rows": count,
            "missing_rate": count / len(rows),
        }
        for name, count in missing_counts.items()
    }
    regime_coverage = build_pit_regime_coverage_v1(dataset)
    regime_coverage_proven = regime_coverage.get("regime_coverage_proven") is True
    materially_wider_time_coverage = (
        int(reconciliation["imported_rich_binding_rows"]) >= MINIMUM_MATERIAL_ROWS
        and len(dates) >= MINIMUM_DISTINCT_UTC_DATES
        and span_days >= MINIMUM_COVERAGE_SPAN_DAYS
        and dates[-1] > BASELINE_LATEST_UTC_DATE
    )
    split_groups = {
        split: {str(row["decision_time"]) for row in rows if str(row["split"]) == split}
        for split in ("train", "validation", "holdout")
    }
    split_group_overlap = bool(
        split_groups["train"] & split_groups["validation"]
        or split_groups["train"] & split_groups["holdout"]
        or split_groups["validation"] & split_groups["holdout"]
    )
    cost_complete_rows = sum(
        isinstance(row.get("cost_evidence_sha256"), str) and len(row["cost_evidence_sha256"]) == 64
        for row in rows
    )
    champion_training_authorized = (
        reconciliation.get("accepted") is True
        and reproducible
        and materially_wider_time_coverage
        and regime_coverage_proven
        and not split_group_overlap
        and cost_complete_rows == len(rows)
        and all(value["missing_rows"] == 0 for value in missingness.values())
    )
    return {
        "schema_version": "gen5_dataset_coverage_report_v1",
        "dataset_id": dataset.get("dataset_id"),
        "dataset_sha256": dataset.get("dataset_sha256"),
        "manifest_id": manifest.get("manifest_id"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "total_rich_bound_rows": reconciliation["imported_rich_binding_rows"],
        "dataset_rows_after_embargo": len(rows),
        "symbols": dict(sorted(symbols.items())),
        "timeframes": dict(sorted(timeframes.items())),
        "action_distribution": dict(sorted(actions.items())),
        "split_distribution": dict(sorted(splits.items())),
        "earliest_decision_time": min(decision_times).isoformat().replace("+00:00", "Z"),
        "latest_decision_time": max(decision_times).isoformat().replace("+00:00", "Z"),
        "distinct_utc_dates": dates,
        "distinct_utc_date_count": len(dates),
        "coverage_span_days": span_days,
        "effective_independent_sample_size": len({str(row["decision_time"]) for row in rows}),
        "effective_independent_sample_definition": ("DISTINCT_DECISION_TIME_GROUPS_CONSERVATIVE"),
        "feature_missingness": missingness,
        "cost_complete_rows": cost_complete_rows,
        "cost_completeness_rate": cost_complete_rows / len(rows),
        "regime_coverage_evidence_sha256": regime_coverage["evidence_sha256"],
        "regime_coverage": regime_coverage,
        "regime_coverage_proven": regime_coverage_proven,
        "regime_coverage_status": (
            "PROVEN_PIT_TRAIN_FIT_COVERAGE_EVALUATION"
            if regime_coverage_proven
            else "UNPROVEN_PIT_REGIME_COVERAGE_INSUFFICIENT"
        ),
        "decision_time_group_overlap_across_splits": split_group_overlap,
        "dataset_reproducible": reproducible,
        "baseline_rich_rows": BASELINE_RICH_ROWS,
        "minimum_material_rows": MINIMUM_MATERIAL_ROWS,
        "minimum_distinct_utc_dates": MINIMUM_DISTINCT_UTC_DATES,
        "minimum_coverage_span_days": MINIMUM_COVERAGE_SPAN_DAYS,
        "baseline_latest_utc_date": BASELINE_LATEST_UTC_DATE,
        "materially_wider_time_coverage": materially_wider_time_coverage,
        "champion_training_authorized": champion_training_authorized,
        "training_blockers": [
            reason
            for reason, blocked in (
                ("BACKFILL_RECONCILIATION_FAILED", reconciliation.get("accepted") is not True),
                ("DATASET_NOT_REPRODUCIBLE", not reproducible),
                ("TIME_COVERAGE_NOT_MATERIALLY_WIDER", not materially_wider_time_coverage),
                ("REGIME_COVERAGE_UNPROVEN", not regime_coverage_proven),
                ("DECISION_TIME_GROUP_SPLIT_OVERLAP", split_group_overlap),
                ("COST_EVIDENCE_INCOMPLETE", cost_complete_rows != len(rows)),
                (
                    "REQUIRED_FEATURE_MISSINGNESS_NONZERO",
                    any(value["missing_rows"] for value in missingness.values()),
                ),
            )
            if blocked
        ],
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ledger", type=Path, default=default_ledger_path())
    parser.add_argument("--source-label-archive", type=Path, default=DEFAULT_LABEL_ARCHIVE_PATH)
    parser.add_argument("--cost-store-root", type=Path, default=DEFAULT_COST_STORE_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--output-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    config = Gen5BackfillConfig(
        source_ledger_path=arguments.source_ledger,
        source_label_archive_path=arguments.source_label_archive,
        cost_store_root=arguments.cost_store_root,
        state_root=arguments.state_root,
    )
    output_root = arguments.output_root or config.state_root / "evidence"
    rejection_evidence = build_gen5_rejection_sequence_evidence(config)
    _write_json_atomic(
        config.state_root / REJECTION_SEQUENCE_EVIDENCE_FILENAME,
        rejection_evidence,
    )
    reconciliation, identity = reconcile_gen5_backfill(config)
    _write_json_atomic(output_root / "gen5_backfill_reconciliation.json", reconciliation)
    if reconciliation.get("accepted") is not True:
        print(json.dumps(reconciliation, indent=2, sort_keys=True), flush=True)
        return 2
    identity_path = output_root / "gen5_reconciled_identity_manifest.json"
    _write_json_atomic(identity_path, identity)
    first = build_serving_dataset_v2(
        identity_manifest_path=identity_path,
        archive_root=config.challenger_archive_root,
    )
    second = build_serving_dataset_v2(
        identity_manifest_path=identity_path,
        archive_root=config.challenger_archive_root,
    )
    reproducible = json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    if not reproducible:
        raise RuntimeError("GEN5_DATASET_REPRODUCIBILITY_FAILED")
    dataset, dataset_manifest, parity = first
    coverage = _coverage_report(
        dataset,
        dataset_manifest,
        reconciliation,
        reproducible=reproducible,
    )
    _write_json_atomic(output_root / "serving_compatible_dataset_gen5.json", dataset)
    _write_json_atomic(
        output_root / "serving_compatible_dataset_manifest_gen5.json",
        dataset_manifest,
    )
    _write_json_atomic(output_root / "train_serve_feature_parity_report_gen5.json", parity)
    _write_json_atomic(
        output_root / "gen5_pit_regime_coverage_report.json",
        coverage["regime_coverage"],
    )
    _write_json_atomic(output_root / "gen5_dataset_coverage_report.json", coverage)
    print(json.dumps(coverage, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
