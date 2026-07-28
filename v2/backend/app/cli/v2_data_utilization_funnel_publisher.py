"""Publish an authenticated, identity-scoped FINAL PASS data-utilization report.

This is evidence-only.  It reads the frozen generation-5 stores, the verified
candidate-outcome archive status, and the paper model registry.  It cannot
train, activate, authorize, route, or submit any order.
"""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_ADAPTIVE_DATASET_ROOT = Path(
    "/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v2"
)
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_nonnegative_int(source: Mapping[str, Any], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DataUtilizationCollectorError(f"{field}:NONNEGATIVE_INT_REQUIRED")
    return value


def _required_sha256(source: Mapping[str, Any], field: str) -> str:
    value = source.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DataUtilizationCollectorError(f"{field}:SHA256_REQUIRED")
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


def _counter_map(value: object, field: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise DataUtilizationCollectorError(f"{field}:OBJECT_REQUIRED")
    result: dict[str, int] = {}
    for raw_key, raw_count in value.items():
        if not isinstance(raw_key, str) or not raw_key or raw_key.strip() != raw_key:
            raise DataUtilizationCollectorError(f"{field}:KEY_INVALID")
        if (
            not isinstance(raw_count, int)
            or isinstance(raw_count, bool)
            or raw_count < 0
        ):
            raise DataUtilizationCollectorError(f"{field}:COUNT_INVALID")
        if raw_count:
            result[raw_key] = raw_count
    return dict(sorted(result.items()))


def _candidate_training_profile(
    root: Path,
    *,
    frozen_corpus: Mapping[str, Any],
    candidate_outcomes: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the immutable enlarged-dataset evidence and exact row accounting."""

    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_ROOT_UNSAFE")
    filenames = {
        "dataset": "adaptive_serving_compatible_dataset_v2.json",
        "manifest": "adaptive_serving_compatible_dataset_manifest_v2.json",
        "parity": "adaptive_train_serve_feature_parity_report_v2.json",
        "receipt": "candidate_outcome_dataset_build_receipt_v2.json",
    }
    paths = {name: root / filename for name, filename in filenames.items()}
    dataset = _read_object(paths["dataset"], "adaptive_dataset")
    manifest = _read_object(paths["manifest"], "adaptive_manifest")
    parity = _read_object(paths["parity"], "adaptive_parity")
    receipt = _read_object(paths["receipt"], "adaptive_build_receipt")

    if (
        dataset.get("schema_version") != "adaptive_serving_compatible_dataset_v2"
        or manifest.get("schema_version")
        != "adaptive_serving_compatible_dataset_manifest_v2"
        or parity.get("schema_version") != "adaptive_train_serve_feature_parity_report_v2"
        or receipt.get("schema_version") != "candidate_outcome_dataset_build_receipt_v2"
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_SCHEMA_MISMATCH")

    artifact_hashes = receipt.get("artifact_file_sha256s")
    if not isinstance(artifact_hashes, Mapping):
        raise DataUtilizationCollectorError("ADAPTIVE_ARTIFACT_HASHES_MISSING")
    for name in ("dataset", "manifest", "parity"):
        filename = filenames[name]
        if artifact_hashes.get(filename) != _file_sha256(paths[name]):
            raise DataUtilizationCollectorError(
                f"ADAPTIVE_ARTIFACT_FILE_HASH_MISMATCH:{filename}"
            )

    dataset_sha = _required_sha256(dataset, "dataset_sha256")
    dataset_material = {
        key: value
        for key, value in dataset.items()
        if key not in {"dataset_id", "dataset_sha256"}
    }
    if _object_sha256(dataset_material) != dataset_sha:
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_CONTENT_HASH_INVALID")
    manifest_sha = _required_sha256(manifest, "manifest_sha256")
    manifest_material = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifest_id", "manifest_sha256"}
    }
    if _object_sha256(manifest_material) != manifest_sha:
        raise DataUtilizationCollectorError("ADAPTIVE_MANIFEST_CONTENT_HASH_INVALID")

    identity_fields = (
        "dataset_id",
        "dataset_sha256",
        "manifest_id",
        "manifest_sha256",
    )
    for field in identity_fields:
        expected = manifest.get(field) if field.startswith("dataset_") else manifest.get(field)
        if receipt.get(field) != expected:
            raise DataUtilizationCollectorError(
                f"ADAPTIVE_RECEIPT_IDENTITY_MISMATCH:{field}"
            )
    if dataset.get("dataset_id") != manifest.get("dataset_id"):
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_MANIFEST_ID_MISMATCH")
    if dataset_sha != manifest.get("dataset_sha256"):
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_MANIFEST_HASH_MISMATCH")

    feature_abi = _required_sha256(dataset, "feature_abi_sha256")
    feature_builder = _required_sha256(dataset, "feature_builder_sha256")
    if (
        manifest.get("feature_abi_sha256") != feature_abi
        or manifest.get("feature_builder_sha256") != feature_builder
        or parity.get("feature_abi_sha256") != feature_abi
        or parity.get("training_feature_builder_sha256") != feature_builder
        or parity.get("serving_feature_builder_sha256") != feature_builder
        or parity.get("builder_match") is not True
        or parity.get("ordered_feature_names_match") is not True
        or parity.get("required_feature_missing_rate") != 0.0
        or parity.get("activation_eligible") is not False
        or parity.get("live_eligible") is not False
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_TRAIN_SERVE_PARITY_INVALID")
    if dataset.get("ordered_feature_names") != manifest.get("ordered_feature_names"):
        raise DataUtilizationCollectorError("ADAPTIVE_FEATURE_ORDER_MISMATCH")

    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows:
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_ROWS_REQUIRED")
    row_ids: set[str] = set()
    source_counts: dict[str, int] = {}
    source_split_counts: dict[str, dict[str, int]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise DataUtilizationCollectorError(
                f"ADAPTIVE_DATASET_ROW_INVALID:{index}"
            )
        row_id = row.get("row_id")
        source_kind = row.get("source_kind")
        split = row.get("split")
        if (
            not isinstance(row_id, str)
            or not row_id
            or row_id in row_ids
            or source_kind
            not in {
                "CANDIDATE_DECISION_OUTCOME_V2",
                "GEN5_AUTHENTICATED_PROFILED_OBSERVATION",
            }
            or split not in {"train", "validation", "holdout"}
        ):
            raise DataUtilizationCollectorError(
                f"ADAPTIVE_DATASET_ROW_IDENTITY_INVALID:{index}"
            )
        row_ids.add(row_id)
        source_counts[source_kind] = source_counts.get(source_kind, 0) + 1
        by_split = source_split_counts.setdefault(
            source_kind, {"train": 0, "validation": 0, "holdout": 0}
        )
        by_split[split] += 1
        if source_kind == "CANDIDATE_DECISION_OUTCOME_V2":
            if (
                not isinstance(row.get("candidate_id"), str)
                or not row.get("candidate_id")
                or not isinstance(row.get("snapshot_id"), str)
                or not row.get("snapshot_id")
                or row.get("counterfactual_counts_as_realized_paper_profit") is not False
            ):
                raise DataUtilizationCollectorError(
                    f"ADAPTIVE_CANDIDATE_LINEAGE_INVALID:{index}"
                )

    expected_source_counts = _counter_map(
        manifest.get("source_row_counts"), "source_row_counts"
    )
    if dict(sorted(source_counts.items())) != expected_source_counts:
        raise DataUtilizationCollectorError("ADAPTIVE_SOURCE_ROW_COUNTS_MISMATCH")
    if source_split_counts != manifest.get("source_split_counts"):
        raise DataUtilizationCollectorError("ADAPTIVE_SOURCE_SPLIT_COUNTS_MISMATCH")
    split_totals = {
        split: sum(counts[split] for counts in source_split_counts.values())
        for split in ("train", "validation", "holdout")
    }
    for split, manifest_field in (
        ("train", "training_rows"),
        ("validation", "validation_rows"),
        ("holdout", "holdout_rows"),
    ):
        expected = _required_nonnegative_int(manifest, manifest_field)
        if split_totals[split] != expected or parity.get(manifest_field) != expected:
            raise DataUtilizationCollectorError(
                f"ADAPTIVE_SPLIT_COUNT_MISMATCH:{split}"
            )

    high_water = manifest.get("source_high_watermark")
    archive_verification = receipt.get("candidate_archive_verification")
    if not isinstance(high_water, Mapping) or not isinstance(archive_verification, Mapping):
        raise DataUtilizationCollectorError("ADAPTIVE_SOURCE_HIGH_WATER_MISSING")
    candidate_count = _required_nonnegative_int(
        candidate_outcomes, "candidate_outcome_rows"
    )
    matured_count = _required_nonnegative_int(
        candidate_outcomes, "matured_candidate_outcome_rows"
    )
    archive_terminal = _required_sha256(
        candidate_outcomes, "archive_terminal_chain_sha256"
    )
    if (
        high_water.get("base_dataset_sha256") != frozen_corpus.get("dataset_sha256")
        or high_water.get("candidate_archive_candidate_count") != candidate_count
        or high_water.get("candidate_archive_matured_revision_count") != matured_count
        or high_water.get("candidate_archive_terminal_chain_sha256") != archive_terminal
        or archive_verification.get("candidate_count") != candidate_count
        or archive_verification.get("matured_revision_count") != matured_count
        or archive_verification.get("terminal_chain_sha256") != archive_terminal
        or archive_verification.get("verified") is not True
        or archive_verification.get("invalid_row_count") != 0
        or archive_verification.get("duplicate_archive_record_count") != 0
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_ARCHIVE_BINDING_INVALID")

    serving_rejections = _counter_map(
        manifest.get("candidate_exclusion_reasons"),
        "candidate_exclusion_reasons",
    )
    split_purge_reasons = _counter_map(
        manifest.get("purge_reason_counts"), "purge_reason_counts"
    )
    considered = _required_nonnegative_int(manifest, "candidate_records_considered")
    matured_considered = _required_nonnegative_int(
        manifest, "candidate_matured_records_considered"
    )
    eligible = _required_nonnegative_int(
        manifest, "candidate_rows_before_split_purge"
    )
    candidate_split = source_split_counts["CANDIDATE_DECISION_OUTCOME_V2"]
    admitted = sum(candidate_split.values())
    if (
        considered != candidate_count
        or matured_considered != matured_count
        or eligible + sum(serving_rejections.values()) != matured_count
        or admitted + sum(split_purge_reasons.values()) != eligible
        or manifest.get("candidate_records_fully_accounted") is not True
        or manifest.get("counterfactual_counts_as_realized_paper_profit") is not False
        or receipt.get("candidate_records_fully_accounted") is not True
        or receipt.get("counterfactual_counts_as_realized_paper_profit") is not False
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_CANDIDATE_ACCOUNTING_INVALID")

    base_split = source_split_counts["GEN5_AUTHENTICATED_PROFILED_OBSERVATION"]
    base_rows = sum(base_split.values())
    if (
        base_rows != frozen_corpus.get("training_eligible_rows")
        or base_split != {"train": base_rows, "validation": 0, "holdout": 0}
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_BASE_DATASET_BINDING_INVALID")
    if (
        receipt.get("status") != "PASS"
        or receipt.get("paper_only") is not True
        or receipt.get("live_gate") != "blocked_human_only"
        or receipt.get("routes_to_live") is not False
        or receipt.get("places_real_order") is not False
        or receipt.get("exchange_action_taken") is not False
        or manifest.get("paper_only") is not True
        or manifest.get("live_eligible") is not False
    ):
        raise DataUtilizationCollectorError("ADAPTIVE_DATASET_AUTHORITY_INVALID")

    return {
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha,
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest_sha,
        "feature_abi_sha256": feature_abi,
        "feature_builder_sha256": feature_builder,
        "base_dataset_sha256": high_water["base_dataset_sha256"],
        "base_dataset_rows": base_rows,
        "serving_eligible_candidate_rows": eligible,
        "dataset_admitted_candidate_rows": admitted,
        "candidate_training_rows": candidate_split["train"],
        "candidate_validation_rows": candidate_split["validation"],
        "candidate_holdout_rows": candidate_split["holdout"],
        "serving_rejections_by_reason": serving_rejections,
        "split_purge_reasons": split_purge_reasons,
        "candidate_records_fully_accounted": True,
        "counterfactual_counts_as_realized_paper_profit": False,
        "artifact_verified": True,
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
    adaptive_dataset_root: Path = DEFAULT_ADAPTIVE_DATASET_ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    frozen_corpus, dataset = _frozen_corpus_profile(config)
    candidate_outcomes = _candidate_profile(
        candidate_status,
        _dataset_decision_keys(dataset),
    )
    candidate_training = _candidate_training_profile(
        adaptive_dataset_root,
        frozen_corpus=frozen_corpus,
        candidate_outcomes=candidate_outcomes,
    )
    checkpoint_rows, normalized_registry = _checkpoint_rows(active_registry, config.state_root)
    try:
        return build_data_utilization_report_v3(
            generated_at=generated_at or _utc_now(),
            frozen_corpus=frozen_corpus,
            candidate_outcomes=candidate_outcomes,
            candidate_training=candidate_training,
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
    parser.add_argument(
        "--adaptive-dataset-root",
        type=Path,
        default=DEFAULT_ADAPTIVE_DATASET_ROOT,
    )
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
        adaptive_dataset_root=arguments.adaptive_dataset_root,
    )
    if not arguments.no_write_report:
        _write_json_atomic(arguments.output.resolve(), report)
    if not arguments.no_publish:
        client.set(REDIS_KEY, _canonical_json(report))
    print(_canonical_json(report, pretty=True), flush=True)
    return 0 if report.get("paths_consistent") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
