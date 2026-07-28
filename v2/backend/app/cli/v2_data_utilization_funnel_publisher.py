"""Publish an authenticated, identity-scoped FINAL PASS data-utilization report.

This is evidence-only.  It reads the frozen generation-5 stores, the verified
candidate-outcome archive status, and the paper model registry.  It cannot
train, activate, authorize, route, or submit any order.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis

from v2.backend.app.contracts.runtime_v2.contracts import CheckpointBundleV2
from v2.backend.app.services.adaptive_system.data_utilization_funnel_v2 import REDIS_KEY
from v2.backend.app.services.adaptive_system.data_utilization_report_v3 import (
    DataUtilizationReportError,
    build_data_utilization_report_v3,
)
from v2.backend.app.services.native_trainer.gen5_backfill_reconciliation_v1 import (
    reconcile_gen5_backfill,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    DEFAULT_COST_STORE_ROOT,
    DEFAULT_LABEL_ARCHIVE_PATH,
    DEFAULT_STATE_ROOT,
    Gen5BackfillConfig,
    validate_existing_fixed_snapshot,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (
    build_serving_dataset_v2,
)

CANDIDATE_STATUS_KEY = "v2:adaptive_system:candidate_outcomes:status"
ACTIVE_REGISTRY_KEY = "v2:model_registry:paper:active"
REPORT_RELATIVE_PATH = Path("goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/data_utilization_report.json")
EXPECTED_COST_LABELS = frozenset(
    {
        "causal_cost:auxiliary:expected_funding_bps",
        "causal_cost:auxiliary:expected_slippage_bps",
        "causal_cost:auxiliary:fee_bps",
        "causal_cost:auxiliary:spread_bps",
    }
)
EXPECTED_MICROSTRUCTURE_LABELS = frozenset(
    {
        "causal_cost:auxiliary:expected_slippage_bps",
        "causal_cost:auxiliary:spread_bps",
    }
)


class DataUtilizationCollectorError(RuntimeError):
    """Raised when a supposedly authenticated source cannot be proven."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_json(value: object, *, pretty: bool = False) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=None if pretty else (",", ":"),
            indent=2 if pretty else None,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DataUtilizationCollectorError("STRICT_JSON_REQUIRED") from exc


def _read_object(path: Path, field: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DataUtilizationCollectorError(f"{field}:REGULAR_FILE_REQUIRED")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataUtilizationCollectorError(f"{field}:INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise DataUtilizationCollectorError(f"{field}:OBJECT_REQUIRED")
    return value


def _redis_object(client: Any, key: str) -> dict[str, Any]:
    raw = client.get(key)
    if not isinstance(raw, str) or not raw:
        raise DataUtilizationCollectorError(f"{key}:MISSING")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUtilizationCollectorError(f"{key}:INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise DataUtilizationCollectorError(f"{key}:OBJECT_REQUIRED")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload, pretty=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise DataUtilizationCollectorError(f"SQLITE_PATH_UNSAFE:{path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=60.0)
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if quick_check is None or str(quick_check[0]) != "ok":
        connection.close()
        raise DataUtilizationCollectorError(f"SQLITE_QUICK_CHECK_FAILED:{path}")
    return connection


def _feature_profile(path: Path) -> dict[str, Any]:
    with _read_only_connection(path) as connection:
        total, strict = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(strict_training_eligible), 0) "
            "FROM feature_snapshot_records"
        ).fetchone()
        finality = connection.execute(
            """
            SELECT COUNT(*)
            FROM feature_snapshot_records AS record
            WHERE NOT EXISTS (
                SELECT 1
                FROM json_each(
                    record.record_json,
                    '$.frozen_envelope.source_read_receipts'
                ) AS receipt
                WHERE json_extract(
                    receipt.value,
                    '$.finality_evidence.event_final'
                ) IS NOT 1
            )
            """
        ).fetchone()[0]
        receipt_rows = connection.execute(
            """
            SELECT record.sequence, json_extract(receipt.value, '$.source_label')
            FROM feature_snapshot_records AS record,
                 json_each(
                     record.record_json,
                     '$.frozen_envelope.source_read_receipts'
                 ) AS receipt
            """
        ).fetchall()
        reasons = connection.execute(
            """
            SELECT json_extract(
                       record_json,
                       '$.frozen_envelope.strict_training_ineligibility_reasons'
                   ), COUNT(*)
            FROM feature_snapshot_records
            GROUP BY 1
            """
        ).fetchall()
        temporal_reasons = connection.execute(
            """
            SELECT reason.value, COUNT(*)
            FROM feature_snapshot_records AS record,
                 json_each(
                     record.record_json,
                     '$.frozen_envelope.temporal_rejection_reasons'
                 ) AS reason
            GROUP BY reason.value
            """
        ).fetchall()
    labels_by_sequence: dict[int, set[str]] = {}
    for sequence, label in receipt_rows:
        if isinstance(label, str):
            labels_by_sequence.setdefault(int(sequence), set()).add(label)
    cost_complete = sum(EXPECTED_COST_LABELS <= labels for labels in labels_by_sequence.values())
    microstructure_complete = sum(
        EXPECTED_MICROSTRUCTURE_LABELS <= labels for labels in labels_by_sequence.values()
    )
    reason_counts: dict[str, int] = {}
    for raw_reasons, count in reasons:
        try:
            parsed = json.loads(raw_reasons)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DataUtilizationCollectorError("FEATURE_INELIGIBILITY_REASONS_INVALID") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise DataUtilizationCollectorError("FEATURE_INELIGIBILITY_REASONS_INVALID")
        for reason in parsed:
            reason_counts[reason] = reason_counts.get(reason, 0) + int(count)
    temporal_reason_counts = {
        str(reason): int(count) for reason, count in temporal_reasons
    }
    return {
        "feature_snapshots": int(total),
        "strict_training_eligible_snapshots": int(strict),
        "finality_proven_snapshots": int(finality),
        "cost_complete_snapshots": int(cost_complete),
        "microstructure_complete_snapshots": int(microstructure_complete),
        "ineligibility_reasons": dict(sorted(reason_counts.items())),
        "temporal_rejection_reasons": dict(sorted(temporal_reason_counts.items())),
    }


def _label_profile(path: Path) -> dict[str, int]:
    with _read_only_connection(path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*),
                   COUNT(DISTINCT raw_payload_hash),
                   COUNT(DISTINCT market_fact_sha256),
                   COUNT(DISTINCT content_sha256)
            FROM canonical_5m_candles
            """
        ).fetchone()
    names = ("canonical_events", "raw_events", "market_facts", "unique_contents")
    result = {name: int(value) for name, value in zip(names, row, strict=True)}
    if len(set(result.values())) != 1:
        raise DataUtilizationCollectorError("RAW_CANONICAL_ONE_TO_ONE_IDENTITY_UNPROVEN")
    return result


def _decision_key(row: Mapping[str, Any]) -> tuple[str, str, int]:
    symbol = row.get("symbol")
    timeframe = row.get("timeframe")
    decision_time = row.get("decision_time_ms")
    if (
        not isinstance(symbol, str)
        or not symbol
        or not isinstance(timeframe, str)
        or not timeframe
        or not isinstance(decision_time, int)
        or isinstance(decision_time, bool)
        or decision_time < 1
    ):
        raise DataUtilizationCollectorError("CANDIDATE_DECISION_IDENTITY_INVALID")
    return symbol, timeframe, decision_time


def _dataset_decision_keys(dataset: Mapping[str, Any]) -> set[tuple[str, str, int]]:
    rows = dataset.get("rows")
    if not isinstance(rows, list):
        raise DataUtilizationCollectorError("DATASET_ROWS_ARRAY_REQUIRED")
    result: set[tuple[str, str, int]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DataUtilizationCollectorError("DATASET_ROW_OBJECT_REQUIRED")
        value = row.get("decision_time")
        if not isinstance(value, str):
            raise DataUtilizationCollectorError("DATASET_DECISION_TIME_INVALID")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataUtilizationCollectorError("DATASET_DECISION_TIME_INVALID") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DataUtilizationCollectorError("DATASET_DECISION_TIME_INVALID")
        result.add(
            (
                str(row.get("symbol")),
                str(row.get("timeframe")),
                int(parsed.timestamp() * 1_000),
            )
        )
    if len(result) != len(rows):
        raise DataUtilizationCollectorError("DATASET_DECISION_IDENTITY_DUPLICATED")
    return result


def _candidate_profile(
    status: Mapping[str, Any],
    dataset_keys: set[tuple[str, str, int]],
) -> dict[str, Any]:
    archive = status.get("archive")
    maturation = status.get("maturation")
    if not isinstance(archive, Mapping) or not isinstance(maturation, Mapping):
        raise DataUtilizationCollectorError("CANDIDATE_STATUS_EVIDENCE_MISSING")
    archive_path_raw = archive.get("archive_path")
    if not isinstance(archive_path_raw, str) or not archive_path_raw:
        raise DataUtilizationCollectorError("CANDIDATE_ARCHIVE_PATH_MISSING")
    archive_path = Path(archive_path_raw)
    if not archive_path.is_file() or archive_path.is_symlink():
        raise DataUtilizationCollectorError("CANDIDATE_ARCHIVE_PATH_UNSAFE")
    candidates: dict[str, tuple[str, str, int]] = {}
    matured_ids: set[str] = set()
    archive_rows = 0
    with archive_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                outer = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataUtilizationCollectorError(
                    f"CANDIDATE_ARCHIVE_ROW_INVALID:{line_number}"
                ) from exc
            record = outer.get("record") if isinstance(outer, Mapping) else None
            decision = record.get("decision") if isinstance(record, Mapping) else None
            if not isinstance(decision, Mapping):
                raise DataUtilizationCollectorError(
                    f"CANDIDATE_ARCHIVE_DECISION_MISSING:{line_number}"
                )
            candidate_id = decision.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise DataUtilizationCollectorError(
                    f"CANDIDATE_ARCHIVE_ID_INVALID:{line_number}"
                )
            key = _decision_key(decision)
            prior = candidates.setdefault(candidate_id, key)
            if prior != key:
                raise DataUtilizationCollectorError(
                    f"CANDIDATE_ARCHIVE_IDENTITY_CONFLICT:{candidate_id}"
                )
            labels = record.get("matured_labels")
            if isinstance(labels, Mapping) and labels.get("matured") is True:
                matured_ids.add(candidate_id)
            if (
                outer.get("paper_only") is not True
                or outer.get("live_gate") != "blocked_human_only"
                or outer.get("routes_to_live") is not False
                or outer.get("places_real_order") is not False
                or outer.get("exchange_action_taken") is not False
            ):
                raise DataUtilizationCollectorError(
                    f"CANDIDATE_ARCHIVE_AUTHORITY_INVALID:{line_number}"
                )
            archive_rows += 1
    expected = {
        "row_count": archive_rows,
        "candidate_count": len(candidates),
        "matured_revision_count": len(matured_ids),
    }
    for field, value in expected.items():
        if archive.get(field) != value:
            raise DataUtilizationCollectorError(f"CANDIDATE_ARCHIVE_{field.upper()}_MISMATCH")
    unmatured = len(candidates) - len(matured_ids)
    if maturation.get("unmatured_candidate_count") != unmatured:
        raise DataUtilizationCollectorError("CANDIDATE_UNMATURED_COUNT_MISMATCH")
    raw_pending = maturation.get("pending_reason_counts")
    if not isinstance(raw_pending, Mapping):
        raise DataUtilizationCollectorError("CANDIDATE_PENDING_REASONS_MISSING")
    pending: dict[str, int] = {}
    for reason, count in raw_pending.items():
        if (
            not isinstance(reason, str)
            or not reason
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise DataUtilizationCollectorError("CANDIDATE_PENDING_REASON_INVALID")
        if count:
            pending[reason] = count
    remainder = unmatured - sum(pending.values())
    if remainder < 0:
        raise DataUtilizationCollectorError("CANDIDATE_PENDING_REASONS_OVERCOUNT")
    if remainder:
        pending["HORIZON_NOT_YET_DUE"] = remainder
    candidate_keys = set(candidates.values())
    return {
        "candidate_outcome_rows": len(candidates),
        "matured_candidate_outcome_rows": len(matured_ids),
        "pending_reasons": dict(sorted(pending.items())),
        "gen5_exact_identity_overlap_rows": len(candidate_keys & dataset_keys),
        "archive_verified": bool(
            archive.get("verified") is True
            and archive.get("invalid_row_count") == 0
            and archive.get("duplicate_archive_record_count") == 0
            and maturation.get("unexplained_maturation_drops") == 0
            and maturation.get("counterfactual_counts_as_paper_profit") is False
        ),
        "archive_path": str(archive_path.resolve()),
        "archive_terminal_chain_sha256": archive.get("terminal_chain_sha256"),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _checkpoint_bundle_row(
    payload: Mapping[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    constructor_fields = {field.name for field in fields(CheckpointBundleV2)}
    try:
        bundle = CheckpointBundleV2(
            **{name: payload[name] for name in constructor_fields}
        )
    except (KeyError, TypeError) as exc:
        raise DataUtilizationCollectorError("CHECKPOINT_BUNDLE_CONTRACT_INVALID") from exc
    if payload.get("content_sha256") != bundle.content_sha256():
        raise DataUtilizationCollectorError(
            f"CHECKPOINT_BUNDLE_CONTENT_HASH_INVALID:{bundle.checkpoint_id}"
        )
    validation_reasons = bundle.validate()
    if validation_reasons:
        raise DataUtilizationCollectorError(
            f"CHECKPOINT_BUNDLE_INVALID:{bundle.checkpoint_id}:{','.join(validation_reasons)}"
        )
    if payload.get("live_eligible") is not False or bundle.live_eligible is not False:
        raise DataUtilizationCollectorError("CHECKPOINT_LIVE_ELIGIBILITY_INVALID")
    return {
        "checkpoint_id": bundle.checkpoint_id,
        "content_sha256": bundle.content_sha256(),
        "training_manifest_id": bundle.training_manifest_id,
        "training_manifest_sha256": bundle.training_manifest_sha256,
        "training_rows": bundle.training_rows,
        "validation_rows": bundle.validation_rows,
        "holdout_rows": bundle.holdout_rows,
        "source_paths": [source_path],
    }


def _checkpoint_rows(
    active_registry: Mapping[str, Any],
    state_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_bundle = active_registry.get("checkpoint_bundle")
    if not isinstance(active_bundle, Mapping):
        raise DataUtilizationCollectorError("ACTIVE_CHECKPOINT_BUNDLE_MISSING")
    checkpoint_id = active_registry.get("checkpoint_id")
    generation = active_registry.get("registry_generation")
    if (
        not isinstance(checkpoint_id, str)
        or not checkpoint_id
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
        or active_bundle.get("checkpoint_id") != checkpoint_id
    ):
        raise DataUtilizationCollectorError("ACTIVE_REGISTRY_IDENTITY_INVALID")
    if active_registry.get("paper_only") is not True or active_registry.get("live_eligible") is not False:
        raise DataUtilizationCollectorError("ACTIVE_REGISTRY_AUTHORITY_INVALID")
    rows = [
        _checkpoint_bundle_row(
            active_bundle,
            source_path=f"redis:{ACTIVE_REGISTRY_KEY}",
        )
    ]
    for path in sorted(state_root.rglob("*checkpoint_bundle*.json")):
        rows.append(_checkpoint_bundle_row(_read_object(path, "checkpoint_bundle"), source_path=str(path)))
    normalized = {
        "checkpoint_id": checkpoint_id,
        "registry_generation": generation,
        "registry_binding_verified": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return rows, normalized


def _frozen_corpus_profile(
    config: Gen5BackfillConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = validate_existing_fixed_snapshot(config)
    reconciliation, identity = reconcile_gen5_backfill(config)
    if reconciliation.get("accepted") is not True:
        raise DataUtilizationCollectorError("GEN5_RECONCILIATION_NOT_ACCEPTED")
    evidence_root = config.state_root / "evidence"
    identity_path = evidence_root / "gen5_reconciled_identity_manifest.json"
    if _read_object(identity_path, "identity_manifest") != identity:
        raise DataUtilizationCollectorError("GEN5_IDENTITY_MANIFEST_CHANGED")
    rebuilt = build_serving_dataset_v2(
        identity_manifest_path=identity_path,
        archive_root=config.challenger_archive_root,
    )
    dataset, dataset_manifest, parity = rebuilt
    saved_dataset = _read_object(
        evidence_root / "serving_compatible_dataset_gen5.json",
        "gen5_dataset",
    )
    saved_manifest = _read_object(
        evidence_root / "serving_compatible_dataset_manifest_gen5.json",
        "gen5_dataset_manifest",
    )
    saved_parity = _read_object(
        evidence_root / "train_serve_feature_parity_report_gen5.json",
        "gen5_parity",
    )
    if (dataset, dataset_manifest, parity) != (saved_dataset, saved_manifest, saved_parity):
        raise DataUtilizationCollectorError("GEN5_DATASET_REPRODUCIBILITY_FAILED")

    feature_path = Path(manifest["databases"]["feature"]["snapshot_path"])
    label_path = Path(manifest["databases"]["label"]["snapshot_path"])
    feature = _feature_profile(feature_path)
    label = _label_profile(label_path)
    feature_high_water = manifest["databases"]["feature"]["snapshot_high_water"]
    label_high_water = manifest["databases"]["label"]["snapshot_high_water"]
    if (
        feature["feature_snapshots"] != feature_high_water.get("record_count")
        or feature["strict_training_eligible_snapshots"]
        != feature_high_water.get("strict_eligible_rows")
        or label["canonical_events"] != label_high_water.get("record_count")
    ):
        raise DataUtilizationCollectorError("GEN5_SNAPSHOT_HIGH_WATER_COUNT_MISMATCH")
    if feature["cost_complete_snapshots"] != reconciliation.get("source_strict_eligible_rows"):
        raise DataUtilizationCollectorError("GEN5_COST_COMPLETE_COUNT_MISMATCH")
    if feature["microstructure_complete_snapshots"] != feature["cost_complete_snapshots"]:
        raise DataUtilizationCollectorError("GEN5_MICROSTRUCTURE_COMPLETE_COUNT_MISMATCH")
    if feature["ineligibility_reasons"] != {
        "TEMPORAL_REJECTION_REASONS_PRESENT": (
            feature["feature_snapshots"] - feature["cost_complete_snapshots"]
        )
    }:
        raise DataUtilizationCollectorError("GEN5_FEATURE_EXCLUSION_REASONS_CHANGED")
    if feature["temporal_rejection_reasons"] != {
        "PROFILED_MODEL_RECORD_RUNTIME_UNWIRED_NO_CONSUMER_AUTHORITY": (
            feature["feature_snapshots"] - feature["cost_complete_snapshots"]
        )
    }:
        raise DataUtilizationCollectorError("GEN5_TEMPORAL_EXCLUSION_REASONS_CHANGED")
    dataset_rows = len(dataset.get("rows", []))
    split_total = sum(
        int(dataset_manifest.get(field, -1))
        for field in ("training_rows", "validation_rows", "holdout_rows")
    )
    embargo_count = len(dataset_manifest.get("embargo_row_ids", []))
    imported = int(reconciliation["imported_rich_binding_rows"])
    if dataset_rows != split_total or imported - dataset_rows != embargo_count:
        raise DataUtilizationCollectorError("GEN5_DATASET_ROW_RECONCILIATION_FAILED")

    historical_exclusions: dict[str, dict[str, int]] = {
        "finality_proven_snapshots": {
            "CAUSAL_COST_RECEIPTS_ABSENT:"
            "PROFILED_MODEL_RECORD_RUNTIME_UNWIRED_NO_CONSUMER_AUTHORITY": (
                feature["finality_proven_snapshots"] - feature["cost_complete_snapshots"]
            )
        },
        "microstructure_complete_snapshots": dict(
            sorted(reconciliation["rejections_by_reason"].items())
        ),
        "labeled_snapshots": {"PREDECLARED_PURGE_EMBARGO_ROW": embargo_count},
    }
    profile = {
        "snapshot_id": manifest["snapshot_id"],
        "snapshot_manifest_sha256": manifest["manifest_sha256"],
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset["dataset_sha256"],
        "dataset_manifest_id": dataset_manifest["manifest_id"],
        "dataset_manifest_sha256": dataset_manifest["manifest_sha256"],
        "raw_events": label["raw_events"],
        "canonical_events": label["canonical_events"],
        "feature_snapshots": feature["feature_snapshots"],
        "finality_proven_snapshots": feature["finality_proven_snapshots"],
        "cost_complete_snapshots": feature["cost_complete_snapshots"],
        "microstructure_complete_snapshots": feature[
            "microstructure_complete_snapshots"
        ],
        "labeled_snapshots": imported,
        "training_eligible_rows": dataset_rows,
        "historical_exclusions_by_stage": historical_exclusions,
        "source_integrity_verified": True,
        # This fixed observation proves its own canonical 5m/raw-payload scope.
        # The larger legacy/paid-source inventories do not yet have a common,
        # authenticated identity transform into this frozen corpus.
        "complete_paid_source_inventory_bound": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return profile, dataset


def collect_report(
    *,
    config: Gen5BackfillConfig,
    candidate_status: Mapping[str, Any],
    active_registry: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    frozen_corpus, dataset = _frozen_corpus_profile(config)
    candidate_outcomes = _candidate_profile(
        candidate_status,
        _dataset_decision_keys(dataset),
    )
    checkpoint_rows, normalized_registry = _checkpoint_rows(active_registry, config.state_root)
    try:
        return build_data_utilization_report_v3(
            generated_at=generated_at or _utc_now(),
            frozen_corpus=frozen_corpus,
            candidate_outcomes=candidate_outcomes,
            checkpoint_rows=checkpoint_rows,
            active_registry=normalized_registry,
        )
    except DataUtilizationReportError as exc:
        raise DataUtilizationCollectorError(str(exc)) from exc


def _parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--source-ledger", type=Path)
    parser.add_argument("--source-label-archive", type=Path, default=DEFAULT_LABEL_ARCHIVE_PATH)
    parser.add_argument("--cost-store-root", type=Path, default=DEFAULT_COST_STORE_ROOT)
    parser.add_argument("--output", type=Path, default=repository_root / REPORT_RELATIVE_PATH)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    state_root = arguments.state_root.resolve()
    source_ledger = arguments.source_ledger or (
        state_root / "snapshots/durable_feature_snapshot_ledger.sqlite3"
    )
    config = Gen5BackfillConfig(
        source_ledger_path=source_ledger,
        source_label_archive_path=arguments.source_label_archive,
        cost_store_root=arguments.cost_store_root,
        state_root=state_root,
    )
    client = redis.Redis.from_url(
        arguments.redis_url,
        decode_responses=True,
        socket_connect_timeout=3.0,
        socket_timeout=30.0,
    )
    candidate_status = _redis_object(client, CANDIDATE_STATUS_KEY)
    active_registry = _redis_object(client, ACTIVE_REGISTRY_KEY)
    report = collect_report(
        config=config,
        candidate_status=candidate_status,
        active_registry=active_registry,
    )
    if not arguments.no_write_report:
        _write_json_atomic(arguments.output.resolve(), report)
    if not arguments.no_publish:
        client.set(REDIS_KEY, _canonical_json(report))
    print(_canonical_json(report, pretty=True), flush=True)
    return 0 if report.get("paths_consistent") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
