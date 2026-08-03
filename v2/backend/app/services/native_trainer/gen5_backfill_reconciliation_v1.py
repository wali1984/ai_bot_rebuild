"""Exact reconciliation for the fixed-observation generation-5 backfill."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    load_snapshot,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    Gen5BackfillConfig,
    validate_existing_fixed_snapshot,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import _build_row

RECONCILIATION_SCHEMA_VERSION = "gen5_backfill_reconciliation_v1"
IDENTITY_MANIFEST_SCHEMA_VERSION = "gen5_reconciled_identity_manifest_v1"
_GENERIC_REJECTION_MARKERS = ("UNVERIFIED", "UNKNOWN", "UNEXPLAINED", "OTHER")
REJECTION_SEQUENCE_EVIDENCE_FILENAME = "gen5_rejection_sequence_evidence.json"


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class Gen5BackfillReconciliationError(RuntimeError):
    """Raised when reconciliation evidence is malformed rather than merely red."""


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise Gen5BackfillReconciliationError(f"JSON_OBJECT_PATH_UNSAFE:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gen5BackfillReconciliationError(f"JSON_OBJECT_INVALID:{path}") from exc
    if not isinstance(payload, dict):
        raise Gen5BackfillReconciliationError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def _progress_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise Gen5BackfillReconciliationError("PROGRESS_LEDGER_PATH_UNSAFE")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise Gen5BackfillReconciliationError(
                    f"PROGRESS_ROW_INVALID:{line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise Gen5BackfillReconciliationError(f"PROGRESS_ROW_NOT_OBJECT:{line_number}")
            rows.append(row)
    return rows


def _observation_epoch_us(value: Any) -> int:
    if not isinstance(value, str) or not value:
        raise Gen5BackfillReconciliationError("TRAINING_OBSERVATION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Gen5BackfillReconciliationError("TRAINING_OBSERVATION_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Gen5BackfillReconciliationError("TRAINING_OBSERVATION_TIME_INVALID")
    return int(parsed.astimezone(UTC).timestamp() * 1_000_000)


def _strict_source_sequences(
    ledger_path: Path,
    *,
    training_observed_at: str,
) -> tuple[int, ...]:
    observed_us = _observation_epoch_us(training_observed_at)
    uri = f"{ledger_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=60.0) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]) != "ok":
            raise Gen5BackfillReconciliationError("SOURCE_LEDGER_QUICK_CHECK_FAILED")
        rows = connection.execute(
            """
            SELECT sequence
            FROM feature_snapshot_records
            WHERE strict_training_eligible = 1
              AND ppo_decision_time_us <= ?
            ORDER BY sequence
            """,
            (observed_us,),
        ).fetchall()
    sequences = tuple(int(row[0]) for row in rows)
    if sequences != tuple(sorted(set(sequences))):
        raise Gen5BackfillReconciliationError("SOURCE_SEQUENCE_IDENTITY_INVALID")
    return sequences


def _archive_identities(
    archive_root: Path,
) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    manifest_path = archive_root / "manifest.jsonl"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise Gen5BackfillReconciliationError("CHALLENGER_MANIFEST_PATH_UNSAFE")
    identities: dict[str, dict[str, Any]] = {}
    raw_lines: dict[str, bytes] = {}
    duplicate_rows = 0
    duplicate_conflicts = 0
    conflict_ids: list[str] = []
    with manifest_path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith(b"\n"):
                raise Gen5BackfillReconciliationError(
                    f"CHALLENGER_MANIFEST_PARTIAL_ROW:{line_number}"
                )
            try:
                identity = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise Gen5BackfillReconciliationError(
                    f"CHALLENGER_MANIFEST_INVALID_ROW:{line_number}"
                ) from exc
            if not isinstance(identity, dict):
                raise Gen5BackfillReconciliationError(
                    f"CHALLENGER_MANIFEST_ROW_NOT_OBJECT:{line_number}"
                )
            snapshot_id = identity.get("snapshot_id")
            content_sha256 = identity.get("content_sha256")
            if not isinstance(snapshot_id, str) or not snapshot_id:
                raise Gen5BackfillReconciliationError(
                    f"CHALLENGER_SNAPSHOT_ID_INVALID:{line_number}"
                )
            if not isinstance(content_sha256, str) or len(content_sha256) != 64:
                raise Gen5BackfillReconciliationError(
                    f"CHALLENGER_CONTENT_SHA256_INVALID:{line_number}"
                )
            if snapshot_id in identities:
                duplicate_rows += 1
                if raw != raw_lines[snapshot_id]:
                    duplicate_conflicts += 1
                    conflict_ids.append(snapshot_id)
                continue
            identities[snapshot_id] = identity
            raw_lines[snapshot_id] = raw
    ordered = [identities[key] for key in sorted(identities)]
    return ordered, duplicate_rows, duplicate_conflicts, sorted(set(conflict_ids))


def _reconcile_verified_snapshot(
    config: Gen5BackfillConfig,
    manifest: Mapping[str, Any],
    *,
    snapshot_loader: Callable[..., Mapping[str, Any] | None] = load_snapshot,
    row_builder: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]] = _build_row,
) -> tuple[dict[str, Any], dict[str, Any]]:
    status = _read_object(config.status_path)
    checkpoint = _read_object(config.importer_checkpoint_path)
    progress = _progress_rows(config.progress_path)
    snapshot_id = manifest.get("snapshot_id")
    feature_state = manifest.get("databases", {}).get("feature", {}).get("snapshot_high_water", {})
    frozen_high_water = feature_state.get("high_water_sequence")
    if type(frozen_high_water) is not int or frozen_high_water < 1:
        raise Gen5BackfillReconciliationError("FROZEN_HIGH_WATER_INVALID")
    training_observed_at = manifest.get("training_observed_at")
    source_sequences = _strict_source_sequences(
        config.snapshot_ledger_path,
        training_observed_at=str(training_observed_at),
    )
    identities, duplicate_rows, duplicate_conflicts, conflict_ids = _archive_identities(
        config.challenger_archive_root
    )

    progress_sequence_monotonic = True
    prior_sequence = -1
    prior_shard = 0
    for row in progress:
        shard = row.get("completed_shards")
        sequence = row.get("next_after_sequence")
        if (
            row.get("snapshot_id") != snapshot_id
            or type(shard) is not int
            or shard != prior_shard + 1
            or type(sequence) is not int
            or sequence <= prior_sequence
        ):
            progress_sequence_monotonic = False
            break
        prior_shard = shard
        prior_sequence = sequence

    imported_sequences: set[int] = set()
    build_failures: Counter[str] = Counter()
    verified_records = 0
    identity_rows: list[dict[str, Any]] = []
    content_mismatches = 0
    for identity in identities:
        snapshot_identity = str(identity["snapshot_id"])
        try:
            record = snapshot_loader(
                snapshot_identity,
                root=config.challenger_archive_root,
                verify=True,
            )
            if not isinstance(record, Mapping):
                raise SnapshotArchiveError("AUTHENTICATED_ARCHIVE_RECORD_MISSING")
            if record.get("content_sha256") != identity["content_sha256"]:
                content_mismatches += 1
                continue
            sequence = record.get("profiled_ledger_sequence")
            if type(sequence) is not int or sequence < 1:
                build_failures["PROFILED_LEDGER_SEQUENCE_INVALID"] += 1
                continue
            if sequence in imported_sequences:
                build_failures["DUPLICATE_PROFILED_LEDGER_SEQUENCE"] += 1
                continue
            imported_sequences.add(sequence)
            row_identity = f"gen5:{snapshot_identity}"
            discovery = {
                "row_identity": row_identity,
                "snapshot_id": snapshot_identity,
                "content_sha256": identity["content_sha256"],
            }
            row_builder(discovery, record)
            identity_rows.append(discovery)
            verified_records += 1
        except (OSError, ValueError, SnapshotArchiveError) as exc:
            build_failures[str(exc) or type(exc).__name__] += 1

    source_set = set(source_sequences)
    missing_sequences = tuple(sorted(source_set - imported_sequences))
    unexpected_sequences = tuple(sorted(imported_sequences - source_set))
    rejections = status.get("rejections_by_reason")
    if not isinstance(rejections, dict) or any(
        type(reason) is not str or not reason or type(count) is not int or count < 0
        for reason, count in rejections.items()
    ):
        raise Gen5BackfillReconciliationError("REJECTION_EVIDENCE_INVALID")
    rejected_rows = status.get("rejected_rows")
    if type(rejected_rows) is not int or rejected_rows < 0:
        raise Gen5BackfillReconciliationError("REJECTED_ROW_COUNT_INVALID")
    generic_rejections = sorted(
        reason
        for reason in rejections
        if any(marker in reason.upper() for marker in _GENERIC_REJECTION_MARKERS)
    )
    sequence_reasons = status.get("rejected_sequence_reasons")
    sequence_evidence_path = config.state_root / REJECTION_SEQUENCE_EVIDENCE_FILENAME
    sequence_evidence: dict[str, Any] | None = None
    sequence_evidence_valid = False
    primary_rejections: dict[str, int] = {}
    label_snapshot_high_water = (
        manifest.get("databases", {}).get("label", {}).get("snapshot_high_water", {})
    )
    expected_label_snapshot_receipt = (
        label_snapshot_high_water.get("receipt_sha256")
        if isinstance(label_snapshot_high_water, Mapping)
        else None
    )
    if sequence_evidence_path.exists():
        sequence_evidence = _read_object(sequence_evidence_path)
        evidence_sha256 = sequence_evidence.get("evidence_sha256")
        evidence_material = dict(sequence_evidence)
        evidence_material.pop("evidence_sha256", None)
        evidence_rows = sequence_evidence.get("rejected_sequence_reasons")
        evidence_mapping = (
            {
                str(row.get("sequence")): row.get("primary_reason")
                for row in evidence_rows
                if isinstance(row, dict)
            }
            if isinstance(evidence_rows, list)
            else {}
        )
        sequence_evidence_valid = (
            sequence_evidence.get("schema_version") == "gen5_rejection_sequence_evidence_v1"
            and sequence_evidence.get("snapshot_id") == snapshot_id
            and sequence_evidence.get("snapshot_manifest_sha256") == manifest.get("manifest_sha256")
            and evidence_sha256 == _canonical_sha256(evidence_material)
            and sequence_evidence.get("imported_sequence_count") == len(imported_sequences)
            and sequence_evidence.get("rejected_sequence_count") == len(missing_sequences)
            and isinstance(evidence_rows, list)
            and len(evidence_rows) == len(missing_sequences)
            and sequence_evidence.get("imported_sequences_sha256")
            == _canonical_sha256(tuple(sorted(imported_sequences)))
            and sequence_evidence.get("rejected_sequences_sha256")
            == _canonical_sha256(missing_sequences)
            and _valid_sha256(sequence_evidence.get("label_archive_receipt_sha256"))
            and sequence_evidence.get("label_archive_receipt_sha256")
            == expected_label_snapshot_receipt
            and _valid_sha256(sequence_evidence.get("label_fixed_observation_high_water_sha256"))
            and set(evidence_mapping) == {str(value) for value in missing_sequences}
            and all(
                isinstance(reason, str)
                and reason
                and not any(marker in reason.upper() for marker in _GENERIC_REJECTION_MARKERS)
                for reason in evidence_mapping.values()
            )
            and sequence_evidence.get("all_source_sequences_accounted") is True
            and sequence_evidence.get("one_primary_reason_per_rejected_sequence") is True
            and sequence_evidence.get("paper_only") is True
            and sequence_evidence.get("live_gate") == "blocked_human_only"
            and sequence_evidence.get("routes_to_live") is False
            and sequence_evidence.get("places_real_order") is False
            and sequence_evidence.get("exchange_action_taken") is False
        )
        if sequence_evidence_valid:
            sequence_reasons = evidence_mapping
    reconciled_rejected_rows = len(missing_sequences)
    if reconciled_rejected_rows == 0:
        exact_rejection_sequence_mapping = not missing_sequences
    else:
        exact_rejection_sequence_mapping = (
            isinstance(sequence_reasons, dict)
            and {int(key) for key in sequence_reasons} == set(missing_sequences)
            and all(
                isinstance(reason, str) and reason in rejections
                for reason in sequence_reasons.values()
            )
        )
    if exact_rejection_sequence_mapping and isinstance(sequence_reasons, dict):
        primary_rejections = dict(
            sorted(Counter(str(reason) for reason in sequence_reasons.values()).items())
        )
    source_reconciled = (
        len(source_sequences) == len(identities) + reconciled_rejected_rows
        and len(missing_sequences) == reconciled_rejected_rows
        and not unexpected_sequences
    )
    checkpoint_complete = (
        checkpoint.get("completed") is True
        and checkpoint.get("next_after_sequence") == frozen_high_water
        and checkpoint.get("last_completed_sequence", frozen_high_water) == frozen_high_water
    )
    progress_complete = (
        progress_sequence_monotonic
        and len(progress) == checkpoint.get("completed_shards")
        and bool(progress)
        and progress[-1].get("completed") is True
        and progress[-1].get("next_after_sequence") == frozen_high_water
    )
    acceptance_checks = {
        "checkpoint_complete_at_frozen_high_water": checkpoint_complete,
        "status_completed": status.get("completed") is True,
        "progress_ledger_complete_and_monotonic": progress_complete,
        "source_strict_rows_reconciled": source_reconciled,
        "exact_rejection_sequence_mapping": exact_rejection_sequence_mapping,
        "legacy_aggregate_rejection_count_is_non_authoritative": True,
        "no_generic_rejection_bucket": not generic_rejections,
        "no_duplicate_content_conflicts": duplicate_conflicts == 0,
        "no_unexpected_source_sequences": not unexpected_sequences,
        "all_imported_records_verify": verified_records == len(identities),
        "all_imported_rows_build_with_serving_builder": not build_failures,
        "identity_count_matches_imported_rows": len(identity_rows) == len(identities),
        "manifest_content_matches_blobs": content_mismatches == 0,
        "paper_only": status.get("paper_only") is True,
        "live_gate_blocked": status.get("live_gate") == "blocked_human_only",
        "no_live_authority": (
            status.get("routes_to_live") is False
            and status.get("places_real_order") is False
            and status.get("exchange_action_taken") is False
        ),
    }
    report = {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": manifest.get("manifest_sha256"),
        "training_observed_at": training_observed_at,
        "frozen_ledger_high_water": frozen_high_water,
        "completed_shards": checkpoint.get("completed_shards"),
        "source_strict_eligible_rows": len(source_sequences),
        "imported_rich_binding_rows": len(identities),
        "verified_and_serving_buildable_rows": len(identity_rows),
        "rejected_rows": reconciled_rejected_rows,
        "rejections_by_reason": primary_rejections if missing_sequences else {},
        "legacy_aggregate_rejection_reason_count": rejected_rows,
        "legacy_aggregate_rejections_by_reason": dict(sorted(rejections.items())),
        "rejected_sequence_reasons": dict(sorted((sequence_reasons or {}).items())),
        "rejection_sequence_evidence_sha256": (
            sequence_evidence.get("evidence_sha256")
            if sequence_evidence_valid and sequence_evidence
            else None
        ),
        "missing_source_sequences": list(missing_sequences),
        "unexpected_source_sequences": list(unexpected_sequences),
        "duplicate_manifest_rows": duplicate_rows,
        "duplicate_content_conflicts": duplicate_conflicts,
        "duplicate_conflict_snapshot_ids": conflict_ids,
        "manifest_blob_content_mismatches": content_mismatches,
        "build_failures_by_reason": dict(sorted(build_failures.items())),
        "generic_rejection_reasons": generic_rejections,
        "progress_rows": len(progress),
        "acceptance_checks": acceptance_checks,
        "accepted": all(acceptance_checks.values()),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    identity_manifest = {
        "schema_version": IDENTITY_MANIFEST_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": manifest.get("manifest_sha256"),
        "training_observed_at": training_observed_at,
        "source_strict_eligible_rows": len(source_sequences),
        "rows": sorted(identity_rows, key=lambda row: row["row_identity"]),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return report, identity_manifest


def reconcile_gen5_backfill(
    config: Gen5BackfillConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = validate_existing_fixed_snapshot(config)
    return _reconcile_verified_snapshot(config, manifest)


__all__ = [
    "Gen5BackfillReconciliationError",
    "IDENTITY_MANIFEST_SCHEMA_VERSION",
    "RECONCILIATION_SCHEMA_VERSION",
    "reconcile_gen5_backfill",
]
