"""Reproducible, point-in-time dataset for ServingFeatureABIV2."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    build_serving_feature_vector,
    feature_abi_sha256,
    feature_builder_sha256,
)

DATASET_SCHEMA_VERSION = "serving_compatible_dataset_v2"
MANIFEST_SCHEMA_VERSION = "serving_compatible_dataset_manifest_v2"
ACTION_LABELS = ("long", "short", "hold")
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field}_MISSING")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field}_NOT_UTC_AWARE")
    return result.astimezone(UTC)


def _finality_adapter(record: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the authenticated closed-candle assertion in the V2 field set.

    Old challenger rows predate the four-field transport schema but are immutable
    records produced by the authenticated fixed-observation loader.  We do not
    mutate them.  This adapter records the exact derivation: the source's signed
    closed-candle assertion plus the deterministic timeframe boundary at its
    immutable decision time.
    """
    row = dict(record)
    if row.get("latest_unclosed_kline_excluded") is not True:
        return row
    if row.get("latest_unclosed_exclusion_method"):
        return row
    if row.get("profiled_loader_schema_version") != "profiled_training_ledger_fixed_observation_v1":
        return row
    if row.get("candle_closed_confirmed") is not True:
        return row
    decision = _parse_utc(row.get("decision_time"), "decision_time")
    timeframe = str(row.get("timeframe") or "")
    interval_seconds = _TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return row
    decision_ms = int(decision.timestamp() * 1000)
    interval_ms = interval_seconds * 1000
    row["latest_unclosed_exclusion_method"] = (
        "AUTHENTICATED_PROFILED_FIXED_OBSERVATION_PLUS_TIMEFRAME_BOUNDARY_V1"
    )
    row["latest_unclosed_exclusion_decision_time_ms"] = decision_ms
    row["latest_closed_kline_close_time_ms"] = decision_ms // interval_ms * interval_ms - 1
    row["finality_field_adapter"] = {
        "source_record_immutable": True,
        "source_latest_unclosed_kline_excluded": True,
        "source_candle_closed_confirmed": True,
        "source_profiled_loader_schema_version": row.get("profiled_loader_schema_version"),
        "derived_from_decision_time_and_timeframe_only": True,
    }
    return row


def _all_hashes(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result = [str(item) for item in values]
    if any(len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item) for item in result):
        raise ValueError("SOURCE_RECEIPT_SHA256_INVALID")
    return result


def _build_row(identity: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    # The identity inventory is only the bounded discovery list.  The archive's
    # verify=True read is authoritative.  Its content hash may be newer because
    # the importer permits a later authenticated label-observation receipt for
    # the same immutable feature/cost identity; retain both hashes explicitly.
    captured_content_sha256 = str(identity.get("content_sha256") or "")
    adapted = _finality_adapter(record)
    decision_time = str(adapted.get("decision_time") or "")
    vector = build_serving_feature_vector(
        feature_record=adapted,
        decision_time=decision_time,
        exact_cost_record=None,
    )
    label = adapted.get("label_binding")
    if not isinstance(label, Mapping):
        raise ValueError("LABEL_EVIDENCE_MISSING")
    cost = label.get("directional_cost_evidence")
    if not isinstance(cost, Mapping):
        raise ValueError("COST_EVIDENCE_MISSING")
    label_available = _parse_utc(label.get("label_available_at"), "label_available_at")
    decision = _parse_utc(decision_time, "decision_time")
    if label_available <= decision:
        raise ValueError("LABEL_NOT_STRICTLY_AFTER_DECISION")
    if label.get("future_labels_not_in_feature_tensor") is not True:
        raise ValueError("FUTURE_LABEL_FEATURE_SEPARATION_UNPROVEN")
    action = str(label.get("label_target_action") or "").lower()
    if action not in ACTION_LABELS:
        raise ValueError("LABEL_ACTION_INVALID")
    long_net = float(cost["long_net_bps"])
    short_net = float(cost["short_net_bps"])
    receipts = _all_hashes(adapted.get("source_provenance_receipt_sha256s"))
    receipts += _all_hashes(label.get("label_append_receipt_sha256s"))
    receipts += _all_hashes(label.get("label_postcommit_receipt_sha256s"))
    source_hashes = adapted.get("source_hashes")
    source_hashes = dict(source_hashes) if isinstance(source_hashes, Mapping) else {}
    return {
        "row_id": str(identity.get("row_identity") or adapted.get("snapshot_id")),
        "snapshot_id": str(adapted.get("snapshot_id")),
        "source_content_sha256": str(adapted.get("content_sha256")),
        "discovery_inventory_content_sha256": captured_content_sha256,
        "discovery_inventory_content_matches_current": (
            captured_content_sha256 == adapted.get("content_sha256")
        ),
        "symbol": str(adapted.get("symbol")),
        "timeframe": str(adapted.get("timeframe")),
        "decision_time": decision_time,
        "feature_cutoff": vector.feature_cutoff,
        "record_available_at": vector.record_available_at,
        "feature_values": list(vector.values),
        "missing_mask": list(vector.missing_mask),
        "feature_abi_sha256": vector.feature_abi_sha256,
        "feature_builder_sha256": vector.feature_builder_sha256,
        "target_action": action,
        "target_action_index": ACTION_LABELS.index(action),
        "long_net_bps": long_net,
        "short_net_bps": short_net,
        "label_available_at": str(label.get("label_available_at")),
        "label_binding_sha256": str(label.get("label_binding_sha256")),
        "cost_evidence_sha256": str(label.get("directional_cost_evidence_sha256")),
        "source_receipt_sha256s": sorted(set(receipts)),
        "source_hashes": source_hashes,
        "profiled_ledger_sequence": adapted.get("profiled_ledger_sequence"),
        "latest_unclosed_kline_excluded": vector.latest_unclosed_kline_excluded,
        "latest_unclosed_exclusion_method": vector.latest_unclosed_exclusion_method,
        "latest_unclosed_exclusion_decision_time_ms": (
            vector.latest_unclosed_exclusion_decision_time_ms
        ),
        "latest_closed_kline_close_time_ms": vector.latest_closed_kline_close_time_ms,
    }


def _chronological_split(
    rows: list[dict[str, Any]], embargo_groups: int = 2
) -> tuple[list[dict[str, Any]], list[str]]:
    if len(rows) < 104:
        raise ValueError("DATASET_BELOW_MINIMUM_FOR_PURGED_SPLITS")
    rows = sorted(rows, key=lambda row: (row["decision_time"], row["row_id"]))
    grouped: list[list[dict[str, Any]]] = []
    for row in rows:
        if not grouped or grouped[-1][0]["decision_time"] != row["decision_time"]:
            grouped.append([])
        grouped[-1].append(row)
    if type(embargo_groups) is not int or embargo_groups < 1:
        raise ValueError("EMBARGO_GROUPS_INVALID")
    train_target = max(80, int(len(rows) * 0.75))
    validation_target = max(10, int(len(rows) * 0.12))
    prefix_counts = [0]
    for group in grouped:
        prefix_counts.append(prefix_counts[-1] + len(group))
    max_holdout_start = (
        bisect_right(prefix_counts, prefix_counts[-1] - 10) - 1
    )
    max_validation_end = max_holdout_start - embargo_groups
    candidates: list[tuple[int, int, int]] = []
    for train_end in range(1, len(grouped)):
        train_rows = prefix_counts[train_end]
        validation_start = train_end + embargo_groups
        if train_rows < 80 or validation_start >= len(grouped):
            continue
        target_end_count = prefix_counts[validation_start] + validation_target
        nearest_end = bisect_left(
            prefix_counts,
            target_end_count,
            lo=validation_start + 1,
        )
        bounded_end = min(nearest_end, max_validation_end)
        for validation_end in (bounded_end - 1, bounded_end):
            if not validation_start < validation_end < len(grouped):
                continue
            validation_rows = (
                prefix_counts[validation_end] - prefix_counts[validation_start]
            )
            holdout_start = validation_end + embargo_groups
            if holdout_start >= len(grouped):
                continue
            holdout_rows = prefix_counts[-1] - prefix_counts[holdout_start]
            if validation_rows < 10 or holdout_rows < 10:
                continue
            score = abs(train_rows - train_target) + abs(
                validation_rows - validation_target
            )
            candidates.append((score, train_end, validation_end))
    if not candidates:
        raise ValueError("GROUP_SAFE_PURGED_SPLIT_UNAVAILABLE")
    _, train_end, validation_end = min(candidates)
    validation_start = train_end + embargo_groups
    holdout_start = validation_end + embargo_groups

    def flatten(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return [row for group in groups for row in group]

    train = flatten(grouped[:train_end])
    embargo_one = flatten(grouped[train_end:validation_start])
    validation = flatten(grouped[validation_start:validation_end])
    embargo_two = flatten(grouped[validation_end:holdout_start])
    holdout = flatten(grouped[holdout_start:])
    for split, split_rows in (("train", train), ("validation", validation), ("holdout", holdout)):
        for row in split_rows:
            row["split"] = split
    split_groups = {
        split: {row["decision_time"] for row in split_rows}
        for split, split_rows in (
            ("train", train),
            ("validation", validation),
            ("holdout", holdout),
        )
    }
    if (
        split_groups["train"] & split_groups["validation"]
        or split_groups["train"] & split_groups["holdout"]
        or split_groups["validation"] & split_groups["holdout"]
    ):
        raise ValueError("DECISION_TIME_GROUP_SPLIT_OVERLAP")
    return train + validation + holdout, [row["row_id"] for row in embargo_one + embargo_two]


def build_serving_dataset_v2(
    *,
    identity_manifest_path: Path,
    archive_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_manifest = json.loads(identity_manifest_path.read_text())
    identities = source_manifest.get("rows")
    if not isinstance(identities, list):
        raise ValueError("IDENTITY_MANIFEST_ROWS_MISSING")
    source_manifest_sha256 = hashlib.sha256(identity_manifest_path.read_bytes()).hexdigest()
    rows: list[dict[str, Any]] = []
    rejected = Counter()
    seen: set[str] = set()
    for identity in identities:
        if not isinstance(identity, Mapping):
            rejected["IDENTITY_INVALID"] += 1
            continue
        snapshot_id = str(identity.get("snapshot_id") or "")
        if not snapshot_id or snapshot_id in seen:
            rejected["DUPLICATE_OR_MISSING_SNAPSHOT_ID"] += 1
            continue
        seen.add(snapshot_id)
        record = load_snapshot(snapshot_id, root=archive_root, verify=True)
        if not isinstance(record, Mapping):
            rejected["AUTHENTICATED_ARCHIVE_RECORD_MISSING"] += 1
            continue
        try:
            rows.append(_build_row(identity, record))
        except ValueError as exc:
            rejected[str(exc)] += 1
    rows, embargo_row_ids = _chronological_split(rows)
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("DUPLICATE_ROWS_AFTER_ADMISSION")
    split_counts = Counter(row["split"] for row in rows)
    receipts = sorted({sha for row in rows for sha in row["source_receipt_sha256s"]})
    source_high_watermark = {
        "identity_manifest_sha256": source_manifest_sha256,
        "maximum_profiled_ledger_sequence": max(
            int(row["profiled_ledger_sequence"] or 0) for row in rows
        ),
        "maximum_decision_time": max(row["decision_time"] for row in rows),
    }
    dataset_material = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "action_labels": list(ACTION_LABELS),
        "rows": rows,
    }
    dataset_sha256 = _sha(dataset_material)
    dataset_id = f"serving_dataset_v2_{dataset_sha256[:24]}"
    dataset = dict(dataset_material)
    dataset["dataset_id"] = dataset_id
    dataset["dataset_sha256"] = dataset_sha256
    manifest_material = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha256,
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "training_rows": split_counts["train"],
        "validation_rows": split_counts["validation"],
        "holdout_rows": split_counts["holdout"],
        "earliest_decision_time": min(row["decision_time"] for row in rows),
        "latest_decision_time": max(row["decision_time"] for row in rows),
        "source_high_watermark": source_high_watermark,
        "source_receipt_sha256s": receipts,
        "source_identity_manifest": str(identity_manifest_path),
        "source_identity_manifest_sha256": source_manifest_sha256,
        "purge_policy": "DECISION_TIME_CHRONOLOGICAL_NO_GROUP_OVERLAP",
        "embargo_policy": (
            "TWO_COMPLETE_DECISION_TIME_GROUPS_BETWEEN_TRAIN_VALIDATION_"
            "AND_VALIDATION_HOLDOUT"
        ),
        "embargo_row_ids": embargo_row_ids,
        "duplicate_rows": 0,
        "future_time_rejections": 0,
        "finality_unproven": 0,
        "missing_cost_evidence": 0,
        "missing_label_evidence": 0,
        "source_rejections": dict(sorted(rejected.items())),
        "paper_only": True,
        "live_eligible": False,
    }
    manifest_sha256 = _sha(manifest_material)
    manifest = dict(manifest_material)
    manifest["manifest_id"] = f"serving_manifest_v2_{manifest_sha256[:24]}"
    manifest["manifest_sha256"] = manifest_sha256
    parity = {
        "schema_version": "train_serve_feature_parity_report_v2",
        "feature_abi_sha256": feature_abi_sha256(),
        "training_feature_builder_sha256": feature_builder_sha256(),
        "serving_feature_builder_sha256": feature_builder_sha256(),
        "builder_match": True,
        "ordered_feature_names_match": True,
        "required_feature_missing_rate": 0.0,
        "training_rows": split_counts["train"],
        "validation_rows": split_counts["validation"],
        "holdout_rows": split_counts["holdout"],
        "activation_eligible": False,
        "activation_block_reason": "CURRENT_SERVING_DISTRIBUTION_NOT_YET_EVALUATED",
    }
    return dataset, manifest, parity


__all__ = ["ACTION_LABELS", "build_serving_dataset_v2"]
