"""Fail-closed loader for authenticated adaptive serving-training artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.contracts.runtime_v2.contracts import canonical_sha256
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    ARCHIVE_VERIFICATION_SCHEMA_VERSION,
    PINNED_PRODUCTION_WRITER_ID,
    PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    target_action_from_net_edges,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import ACTION_LABELS
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)

DATASET_SCHEMA_VERSION = "adaptive_serving_compatible_dataset_v2"
MANIFEST_SCHEMA_VERSION = "adaptive_serving_compatible_dataset_manifest_v2"
PARITY_SCHEMA_VERSION = "adaptive_train_serve_feature_parity_report_v2"
RECEIPT_SCHEMA_VERSION = "candidate_outcome_dataset_build_receipt_v2"
PINNED_BASE_DATASET_FILE_SHA256 = (
    "416a25c61e147af30b2ab45fb8c8e08d6348467a42045d0944cf6f1a0d785156"
)
PINNED_BUILD_RECEIPT_FILE_SHA256 = (
    "16614dafa9732f8373ab7a398d8648841ca62a89b2a7e59fbed9aecdf9a96023"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")
_TIMEFRAMES = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"})
_SPLITS = ("train", "validation", "holdout")
_SOURCE_KINDS = frozenset(
    {"CANDIDATE_DECISION_OUTCOME_V2", "GEN5_AUTHENTICATED_PROFILED_OBSERVATION"}
)
_DATASET_KEYS = frozenset(
    {
        "schema_version",
        "feature_abi_sha256",
        "feature_builder_sha256",
        "ordered_feature_names",
        "action_labels",
        "rows",
        "dataset_id",
        "dataset_sha256",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "admitted_finality_violations",
        "admitted_future_time_violations",
        "admitted_missing_cost_evidence",
        "admitted_missing_label_evidence",
        "candidate_exclusion_reasons",
        "candidate_matured_records_considered",
        "candidate_records_considered",
        "candidate_records_fully_accounted",
        "candidate_records_loaded_for_dataset",
        "candidate_rejection_count",
        "candidate_rows_before_split_purge",
        "counterfactual_counts_as_realized_paper_profit",
        "dataset_id",
        "dataset_sha256",
        "duplicate_rows",
        "earliest_decision_time",
        "embargo_groups",
        "embargo_row_count",
        "embargo_row_ids",
        "feature_abi_sha256",
        "feature_builder_sha256",
        "feature_group_count",
        "finality_unproven",
        "future_time_rejections",
        "holdout_rows",
        "latest_decision_time",
        "live_eligible",
        "manifest_id",
        "manifest_sha256",
        "maximum_rows_per_feature_group",
        "missing_cost_evidence",
        "missing_label_evidence",
        "ordered_feature_names",
        "paper_only",
        "purge_policy",
        "purge_reason_counts",
        "purged_row_ids",
        "reused_feature_group_count",
        "schema_version",
        "source_high_watermark",
        "source_receipt_sha256_count",
        "source_receipt_sha256s",
        "source_row_counts",
        "source_split_counts",
        "split_boundaries",
        "symbol_count",
        "symbol_counts",
        "target_action_counts",
        "timeframe_count",
        "timeframe_counts",
        "training_rows",
        "validation_rows",
    }
)
_PARITY_KEYS = frozenset(
    {
        "activation_block_reason",
        "activation_eligible",
        "builder_match",
        "feature_abi_sha256",
        "holdout_rows",
        "live_eligible",
        "ordered_feature_names_match",
        "paper_only",
        "required_feature_missing_rate",
        "schema_version",
        "serving_feature_builder_sha256",
        "training_feature_builder_sha256",
        "training_rows",
        "validation_rows",
    }
)
_RECEIPT_KEYS = frozenset(
    {
        "artifact_file_sha256s",
        "base_dataset_file_sha256",
        "base_dataset_path",
        "candidate_archive_verification",
        "candidate_exclusion_reasons",
        "candidate_records_fully_accounted",
        "counterfactual_counts_as_realized_paper_profit",
        "dataset_id",
        "dataset_sha256",
        "exchange_action_taken",
        "feature_archive_root",
        "generated_at",
        "holdout_rows",
        "live_gate",
        "manifest_id",
        "manifest_sha256",
        "paper_only",
        "places_real_order",
        "routes_to_live",
        "schema_version",
        "status",
        "training_rows",
        "trusted_base_dataset_file_sha256",
        "trusted_writer_id",
        "trusted_writer_public_key_hex",
        "validation_rows",
    }
)
_COMMON_ROW_KEYS = frozenset(
    {
        "actual_paper_outcome_present",
        "cost_evidence_sha256",
        "counterfactual_counts_as_realized_paper_profit",
        "decision_time",
        "feature_abi_sha256",
        "feature_builder_sha256",
        "feature_cutoff",
        "feature_group_id",
        "feature_values",
        "label_available_at",
        "label_binding_sha256",
        "latest_closed_kline_close_time_ms",
        "latest_unclosed_exclusion_decision_time_ms",
        "latest_unclosed_exclusion_method",
        "latest_unclosed_kline_excluded",
        "long_net_bps",
        "missing_mask",
        "record_available_at",
        "row_id",
        "short_net_bps",
        "snapshot_id",
        "source_content_sha256",
        "source_hashes",
        "source_kind",
        "source_receipt_sha256s",
        "split",
        "symbol",
        "target_action",
        "target_action_index",
        "timeframe",
    }
)
_GEN5_ROW_KEYS = _COMMON_ROW_KEYS | frozenset(
    {
        "discovery_inventory_content_matches_current",
        "discovery_inventory_content_sha256",
        "profiled_ledger_sequence",
    }
)
_CANDIDATE_ROW_KEYS = _COMMON_ROW_KEYS | frozenset(
    {
        "candidate_id",
        "checkpoint_generation",
        "checkpoint_id",
        "decision_disposition",
        "directional_label_derivation",
        "eventual_disposition",
        "prediction_id",
    }
)
_ZERO_ADMISSION_COUNTERS = (
    "duplicate_rows",
    "future_time_rejections",
    "finality_unproven",
    "missing_cost_evidence",
    "missing_label_evidence",
    "admitted_future_time_violations",
    "admitted_finality_violations",
    "admitted_missing_cost_evidence",
    "admitted_missing_label_evidence",
)


class ServingTrainingArtifactError(ValueError):
    """Raised before training when one artifact or row is not exact and safe."""


def _fail(reason: str, field: str) -> None:
    raise ServingTrainingArtifactError(f"{field}:{reason}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_object(path: Path, field: str) -> tuple[dict[str, Any], str]:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        _fail("ABSOLUTE_PATH_WITHOUT_TRAVERSAL_REQUIRED", field)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ServingTrainingArtifactError(f"{field}:REGULAR_FILE_REQUIRED") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            _fail("REGULAR_FILE_REQUIRED", field)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read()
    finally:
        os.close(descriptor)
    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite_json_constant:{value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_json_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ServingTrainingArtifactError(f"{field}:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        _fail("OBJECT_REQUIRED", field)
    return value, _sha256_bytes(raw)


def _sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail("LOWERCASE_SHA256_REQUIRED", field)
    return value


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        _fail("NONEMPTY_TEXT_REQUIRED", field)
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        _fail("NONNEGATIVE_INT_REQUIRED", field)
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail("FINITE_NUMBER_REQUIRED", field)
    parsed = float(value)
    if not math.isfinite(parsed):
        _fail("FINITE_NUMBER_REQUIRED", field)
    return parsed


def _utc(value: object, field: str) -> datetime:
    if type(value) is not str or not value:
        _fail("UTC_TIMESTAMP_REQUIRED", field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServingTrainingArtifactError(f"{field}:UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("UTC_TIMESTAMP_REQUIRED", field)
    return parsed.astimezone(UTC)


def _counter(value: object, field: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", field)
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        name = _text(key, f"{field}.key")
        result[name] = _nonnegative_int(raw_count, f"{field}.{name}")
    return dict(sorted(result.items()))


def _validate_row(row: object, index: int) -> dict[str, Any]:
    field = f"dataset.rows[{index}]"
    if type(row) is not dict:
        _fail("OBJECT_REQUIRED", field)
    source_kind = row.get("source_kind")
    expected_keys = (
        _CANDIDATE_ROW_KEYS
        if source_kind == "CANDIDATE_DECISION_OUTCOME_V2"
        else _GEN5_ROW_KEYS
        if source_kind == "GEN5_AUTHENTICATED_PROFILED_OBSERVATION"
        else frozenset()
    )
    if not expected_keys or set(row) != expected_keys:
        _fail("EXACT_SOURCE_ROW_SCHEMA_REQUIRED", field)
    _text(row.get("row_id"), f"{field}.row_id")
    _text(row.get("snapshot_id"), f"{field}.snapshot_id")
    _text(row.get("feature_group_id"), f"{field}.feature_group_id")
    symbol = row.get("symbol")
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _fail("CANONICAL_SYMBOL_REQUIRED", f"{field}.symbol")
    if row.get("timeframe") not in _TIMEFRAMES:
        _fail("SUPPORTED_TIMEFRAME_REQUIRED", f"{field}.timeframe")
    split = row.get("split")
    if split not in _SPLITS:
        _fail("KNOWN_SPLIT_REQUIRED", f"{field}.split")
    if (
        row.get("feature_abi_sha256") != feature_abi_sha256()
        or row.get("feature_builder_sha256") != feature_builder_sha256()
    ):
        _fail("CURRENT_FEATURE_CONTRACT_REQUIRED", field)
    values = row.get("feature_values")
    mask = row.get("missing_mask")
    if type(values) is not list or len(values) != len(ORDERED_FEATURE_NAMES):
        _fail("FEATURE_WIDTH_MISMATCH", f"{field}.feature_values")
    if type(mask) is not list or len(mask) != len(ORDERED_FEATURE_NAMES):
        _fail("MISSING_MASK_WIDTH_MISMATCH", f"{field}.missing_mask")
    for offset, value in enumerate(values):
        _finite(value, f"{field}.feature_values[{offset}]")
    if any(not (value is False or type(value) is int and value == 0) for value in mask):
        _fail("REQUIRED_FEATURE_MISSING", f"{field}.missing_mask")
    action = row.get("target_action")
    if action not in ACTION_LABELS:
        _fail("ACTION_LABEL_REQUIRED", f"{field}.target_action")
    if row.get("target_action_index") != ACTION_LABELS.index(action):
        _fail("ACTION_INDEX_MISMATCH", f"{field}.target_action_index")
    long_net = _finite(row.get("long_net_bps"), f"{field}.long_net_bps")
    short_net = _finite(row.get("short_net_bps"), f"{field}.short_net_bps")
    if target_action_from_net_edges(
        long_net_bps=long_net,
        short_net_bps=short_net,
    ) != action:
        _fail("ACTION_NET_EDGE_MISMATCH", f"{field}.target_action")
    cutoff = _utc(row.get("feature_cutoff"), f"{field}.feature_cutoff")
    available = _utc(row.get("record_available_at"), f"{field}.record_available_at")
    decision = _utc(row.get("decision_time"), f"{field}.decision_time")
    label = _utc(row.get("label_available_at"), f"{field}.label_available_at")
    if not cutoff <= available <= decision < label:
        _fail("POINT_IN_TIME_CLOCK_ORDER_INVALID", field)
    if row.get("latest_unclosed_kline_excluded") is not True:
        _fail("LATEST_UNCLOSED_KLINE_EXCLUSION_REQUIRED", field)
    _text(
        row.get("latest_unclosed_exclusion_method"),
        f"{field}.latest_unclosed_exclusion_method",
    )
    closed_ms = _nonnegative_int(
        row.get("latest_closed_kline_close_time_ms"),
        f"{field}.latest_closed_kline_close_time_ms",
    )
    exclusion_ms = _nonnegative_int(
        row.get("latest_unclosed_exclusion_decision_time_ms"),
        f"{field}.latest_unclosed_exclusion_decision_time_ms",
    )
    cutoff_ms = int(cutoff.timestamp() * 1_000)
    decision_ms = int(decision.timestamp() * 1_000)
    if not closed_ms <= cutoff_ms <= exclusion_ms <= decision_ms:
        _fail("FINALITY_CLOCK_ORDER_INVALID", field)
    for name in ("cost_evidence_sha256", "label_binding_sha256", "source_content_sha256"):
        _sha256(row.get(name), f"{field}.{name}")
    source_hashes = row.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        _fail("NONEMPTY_SOURCE_HASHES_REQUIRED", f"{field}.source_hashes")
    for name, value in source_hashes.items():
        _text(name, f"{field}.source_hashes.key")
        _sha256(value, f"{field}.source_hashes.{name}")
    receipts = row.get("source_receipt_sha256s")
    if type(receipts) is not list or not receipts:
        _fail("NONEMPTY_SOURCE_RECEIPTS_REQUIRED", f"{field}.source_receipt_sha256s")
    if receipts != sorted(set(receipts)):
        _fail("CANONICAL_UNIQUE_SOURCE_RECEIPTS_REQUIRED", f"{field}.source_receipt_sha256s")
    for receipt_index, receipt in enumerate(receipts):
        _sha256(receipt, f"{field}.source_receipt_sha256s[{receipt_index}]")
    if row.get("counterfactual_counts_as_realized_paper_profit") is not False:
        _fail("COUNTERFACTUAL_REALIZED_PROFIT_FORBIDDEN", field)
    if type(row.get("actual_paper_outcome_present")) is not bool:
        _fail("EXACT_BOOL_REQUIRED", f"{field}.actual_paper_outcome_present")
    if source_kind == "CANDIDATE_DECISION_OUTCOME_V2":
        for name in ("candidate_id", "prediction_id", "checkpoint_id"):
            _text(row.get(name), f"{field}.{name}")
        if _nonnegative_int(
            row.get("checkpoint_generation"), f"{field}.checkpoint_generation"
        ) < 1:
            _fail("POSITIVE_INT_REQUIRED", f"{field}.checkpoint_generation")
        derivation = row.get("directional_label_derivation")
        if not isinstance(derivation, Mapping):
            _fail("OBJECT_REQUIRED", f"{field}.directional_label_derivation")
        scenario_fields = (
            "alternative_side_scenario_sha256s",
            "unhedged_scenario_sha256s",
        )
        if (
            set(derivation)
            != {
                "actual_accounting_effect",
                "alternative_side_scenario_sha256s",
                "candidate_id",
                "counterfactual_counts_as_realized_paper_profit",
                "derivation_method",
                "derivation_sha256",
                "long_net_bps",
                "proposed_action",
                "schema_version",
                "short_net_bps",
                "target_action",
                "unhedged_scenario_sha256s",
            }
            or derivation.get("schema_version")
            != "candidate_directional_label_derivation_v2"
            or derivation.get("candidate_id") != row.get("candidate_id")
            or derivation.get("actual_accounting_effect") is not False
            or derivation.get("counterfactual_counts_as_realized_paper_profit")
            is not False
            or derivation.get("target_action") != action
            or _finite(derivation.get("long_net_bps"), f"{field}.derivation.long_net_bps")
            != long_net
            or _finite(derivation.get("short_net_bps"), f"{field}.derivation.short_net_bps")
            != short_net
            or derivation.get("derivation_sha256") != row.get("cost_evidence_sha256")
        ):
            _fail("DIRECTIONAL_LABEL_DERIVATION_MISMATCH", field)
        for scenario_field in scenario_fields:
            scenarios = derivation.get(scenario_field)
            if type(scenarios) is not list or len(scenarios) != len(set(scenarios)):
                _fail("DIRECTIONAL_SCENARIO_HASHES_INVALID", field)
            for scenario_index, scenario_sha in enumerate(scenarios):
                _sha256(
                    scenario_sha,
                    f"{field}.directional_label_derivation.{scenario_field}"
                    f"[{scenario_index}]",
                )
    else:
        if (
            row.get("discovery_inventory_content_matches_current") is not True
            or _nonnegative_int(
                row.get("profiled_ledger_sequence"),
                f"{field}.profiled_ledger_sequence",
            )
            < 1
        ):
            _fail("AUTHENTICATED_GEN5_SOURCE_REQUIRED", field)
        _sha256(
            row.get("discovery_inventory_content_sha256"),
            f"{field}.discovery_inventory_content_sha256",
        )
    return row


def load_validated_training_artifacts(
    *,
    dataset_path: Path,
    manifest_path: Path,
    parity_path: Path,
    build_receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read once and authenticate every artifact and admitted training row."""

    dataset, dataset_file_sha = _read_regular_object(dataset_path, "dataset_path")
    manifest, manifest_file_sha = _read_regular_object(manifest_path, "manifest_path")
    parity, parity_file_sha = _read_regular_object(parity_path, "parity_path")
    receipt, receipt_file_sha = _read_regular_object(
        build_receipt_path, "build_receipt_path"
    )
    if set(dataset) != _DATASET_KEYS or dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        _fail("SCHEMA_MISMATCH", "dataset")
    if set(manifest) != _MANIFEST_KEYS or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        _fail("SCHEMA_MISMATCH", "manifest")
    if set(parity) != _PARITY_KEYS or parity.get("schema_version") != PARITY_SCHEMA_VERSION:
        _fail("SCHEMA_MISMATCH", "parity")
    if (
        set(receipt) != _RECEIPT_KEYS
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt_file_sha != PINNED_BUILD_RECEIPT_FILE_SHA256
    ):
        _fail("SCHEMA_MISMATCH", "build_receipt")
    dataset_sha = _sha256(dataset.get("dataset_sha256"), "dataset.dataset_sha256")
    dataset_material = {
        key: value for key, value in dataset.items() if key not in {"dataset_id", "dataset_sha256"}
    }
    if canonical_sha256(dataset_material) != dataset_sha:
        _fail("CONTENT_SHA256_MISMATCH", "dataset")
    if dataset.get("dataset_id") != f"adaptive_serving_dataset_v2_{dataset_sha[:24]}":
        _fail("ID_CONTENT_MISMATCH", "dataset")
    manifest_sha = _sha256(manifest.get("manifest_sha256"), "manifest.manifest_sha256")
    manifest_material = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifest_id", "manifest_sha256"}
    }
    if canonical_sha256(manifest_material) != manifest_sha:
        _fail("CONTENT_SHA256_MISMATCH", "manifest")
    if manifest.get("manifest_id") != f"adaptive_serving_manifest_v2_{manifest_sha[:24]}":
        _fail("ID_CONTENT_MISMATCH", "manifest")
    if (
        manifest.get("dataset_id") != dataset.get("dataset_id")
        or manifest.get("dataset_sha256") != dataset_sha
        or dataset.get("feature_abi_sha256") != feature_abi_sha256()
        or manifest.get("feature_abi_sha256") != feature_abi_sha256()
        or dataset.get("feature_builder_sha256") != feature_builder_sha256()
        or manifest.get("feature_builder_sha256") != feature_builder_sha256()
        or tuple(dataset.get("ordered_feature_names") or ()) != ORDERED_FEATURE_NAMES
        or tuple(manifest.get("ordered_feature_names") or ()) != ORDERED_FEATURE_NAMES
        or tuple(dataset.get("action_labels") or ()) != ACTION_LABELS
    ):
        _fail("DATASET_MANIFEST_FEATURE_BINDING_MISMATCH", "artifacts")
    artifact_hashes = receipt.get("artifact_file_sha256s")
    if not isinstance(artifact_hashes, Mapping) or artifact_hashes != {
        dataset_path.name: dataset_file_sha,
        manifest_path.name: manifest_file_sha,
        parity_path.name: parity_file_sha,
    }:
        _fail("ARTIFACT_FILE_SHA256_BINDING_MISMATCH", "build_receipt")
    if (
        receipt.get("base_dataset_file_sha256") != PINNED_BASE_DATASET_FILE_SHA256
        or receipt.get("trusted_base_dataset_file_sha256")
        != PINNED_BASE_DATASET_FILE_SHA256
        or receipt.get("trusted_writer_id") != PINNED_PRODUCTION_WRITER_ID
        or receipt.get("trusted_writer_public_key_hex")
        != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX
        or receipt.get("status") != "PASS"
        or receipt.get("paper_only") is not True
        or receipt.get("live_gate") != "blocked_human_only"
        or receipt.get("routes_to_live") is not False
        or receipt.get("places_real_order") is not False
        or receipt.get("exchange_action_taken") is not False
        or receipt.get("counterfactual_counts_as_realized_paper_profit") is not False
        or receipt.get("candidate_records_fully_accounted") is not True
        or _utc(receipt.get("generated_at"), "build_receipt.generated_at")
        < _utc(manifest.get("latest_decision_time"), "manifest.latest_decision_time")
    ):
        _fail("UNTRUSTED_OR_UNSAFE_BUILD_RECEIPT", "build_receipt")
    archive = receipt.get("candidate_archive_verification")
    high_water = manifest.get("source_high_watermark")
    if not isinstance(archive, Mapping) or not isinstance(high_water, Mapping):
        _fail("SOURCE_HIGH_WATERMARK_REQUIRED", "artifacts")
    archive_path = archive.get("archive_path")
    if (
        archive.get("schema_version") != ARCHIVE_VERIFICATION_SCHEMA_VERSION
        or archive.get("writer_id") != PINNED_PRODUCTION_WRITER_ID
        or archive.get("writer_public_key_hex") != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX
        or type(archive_path) is not str
        or not Path(archive_path).is_absolute()
        or ".." in Path(archive_path).parts
        or archive.get("verified") is not True
        or _nonnegative_int(archive.get("invalid_row_count"), "archive.invalid_row_count") != 0
        or _nonnegative_int(
            archive.get("duplicate_archive_record_count"),
            "archive.duplicate_archive_record_count",
        )
        != 0
        or archive.get("paper_only") is not True
        or archive.get("live_gate") != "blocked_human_only"
        or archive.get("routes_to_live") is not False
        or archive.get("places_real_order") is not False
        or archive.get("exchange_action_taken") is not False
    ):
        _fail("UNTRUSTED_OR_UNSAFE_ARCHIVE_RECEIPT", "build_receipt")
    archive_terminal_sha = _sha256(
        archive.get("terminal_chain_sha256"),
        "build_receipt.candidate_archive_verification.terminal_chain_sha256",
    )
    archive_row_count = _nonnegative_int(
        archive.get("row_count"), "archive.row_count"
    )
    archive_candidate_count = _nonnegative_int(
        archive.get("candidate_count"), "archive.candidate_count"
    )
    archive_decision_count = _nonnegative_int(
        archive.get("decision_revision_count"), "archive.decision_revision_count"
    )
    archive_matured_count = _nonnegative_int(
        archive.get("matured_revision_count"), "archive.matured_revision_count"
    )
    if (
        archive_terminal_sha == "0" * 64
        or archive_row_count != archive_decision_count + archive_matured_count
        or archive_candidate_count != archive_decision_count
        or archive_matured_count > archive_candidate_count
    ):
        _fail("ARCHIVE_COUNT_OR_CHAIN_INVALID", "build_receipt")
    archive_bindings = {
        "candidate_archive_path": "archive_path",
        "candidate_archive_writer_id": "writer_id",
        "candidate_archive_writer_public_key_hex": "writer_public_key_hex",
        "candidate_archive_terminal_chain_sha256": "terminal_chain_sha256",
        "candidate_archive_row_count": "row_count",
        "candidate_archive_candidate_count": "candidate_count",
        "candidate_archive_decision_revision_count": "decision_revision_count",
        "candidate_archive_matured_revision_count": "matured_revision_count",
    }
    if any(high_water.get(target) != archive.get(source) for target, source in archive_bindings.items()):
        _fail("ARCHIVE_HIGH_WATERMARK_MISMATCH", "artifacts")
    if (
        receipt.get("dataset_id") != dataset.get("dataset_id")
        or receipt.get("dataset_sha256") != dataset_sha
        or receipt.get("manifest_id") != manifest.get("manifest_id")
        or receipt.get("manifest_sha256") != manifest_sha
        or receipt.get("candidate_exclusion_reasons")
        != manifest.get("candidate_exclusion_reasons")
    ):
        _fail("RECEIPT_ARTIFACT_IDENTITY_MISMATCH", "build_receipt")
    rows_raw = dataset.get("rows")
    if type(rows_raw) is not list or not rows_raw:
        _fail("NONEMPTY_ROWS_REQUIRED", "dataset")
    rows = [_validate_row(row, index) for index, row in enumerate(rows_raw)]
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        _fail("DUPLICATE_ROW_ID", "dataset.rows")
    split_counts = Counter(row["split"] for row in rows)
    action_counts = Counter(row["target_action"] for row in rows)
    symbol_counts = Counter(row["symbol"] for row in rows)
    timeframe_counts = Counter(row["timeframe"] for row in rows)
    source_counts = Counter(row["source_kind"] for row in rows)
    source_split_counts = {
        source: {split: 0 for split in _SPLITS} for source in sorted(_SOURCE_KINDS)
    }
    feature_group_splits: defaultdict[str, set[str]] = defaultdict(set)
    admitted_receipts: set[str] = set()
    for row in rows:
        source_split_counts[row["source_kind"]][row["split"]] += 1
        feature_group_splits[row["feature_group_id"]].add(row["split"])
        admitted_receipts.update(row["source_receipt_sha256s"])
    if any(len(splits) != 1 for splits in feature_group_splits.values()):
        _fail("FEATURE_GROUP_CROSSES_SPLIT", "dataset.rows")
    split_fields = {
        "train": "training_rows",
        "validation": "validation_rows",
        "holdout": "holdout_rows",
    }
    for split, field in split_fields.items():
        if _nonnegative_int(manifest.get(field), f"manifest.{field}") != split_counts[split]:
            _fail("SPLIT_COUNT_MISMATCH", f"manifest.{field}")
    if (
        manifest.get("target_action_counts")
        != {action: action_counts[action] for action in ACTION_LABELS}
        or manifest.get("symbol_counts") != dict(sorted(symbol_counts.items()))
        or manifest.get("timeframe_counts") != dict(sorted(timeframe_counts.items()))
        or manifest.get("source_row_counts") != dict(sorted(source_counts.items()))
        or manifest.get("source_split_counts") != source_split_counts
        or manifest.get("symbol_count") != len(symbol_counts)
        or manifest.get("timeframe_count") != len(timeframe_counts)
    ):
        _fail("MANIFEST_ROW_COUNTER_MISMATCH", "manifest")
    if (
        manifest.get("earliest_decision_time") != min(row["decision_time"] for row in rows)
        or manifest.get("latest_decision_time") != max(row["decision_time"] for row in rows)
        or manifest.get("source_receipt_sha256s") != sorted(admitted_receipts)
        or manifest.get("source_receipt_sha256_count") != len(admitted_receipts)
    ):
        _fail("MANIFEST_ROW_EVIDENCE_MISMATCH", "manifest")
    for field in _ZERO_ADMISSION_COUNTERS:
        if _nonnegative_int(manifest.get(field), f"manifest.{field}") != 0:
            _fail("ZERO_ADMISSION_COUNTER_REQUIRED", f"manifest.{field}")
    if (
        manifest.get("candidate_records_fully_accounted") is not True
        or manifest.get("counterfactual_counts_as_realized_paper_profit") is not False
        or manifest.get("paper_only") is not True
        or manifest.get("live_eligible") is not False
    ):
        _fail("MANIFEST_AUTHORITY_OR_ACCOUNTING_INVALID", "manifest")
    purge_counts = _counter(manifest.get("purge_reason_counts"), "manifest.purge_reason_counts")
    rejection_counts = _counter(
        manifest.get("candidate_exclusion_reasons"),
        "manifest.candidate_exclusion_reasons",
    )
    candidate_matured = _nonnegative_int(
        manifest.get("candidate_matured_records_considered"),
        "manifest.candidate_matured_records_considered",
    )
    candidate_eligible = _nonnegative_int(
        manifest.get("candidate_rows_before_split_purge"),
        "manifest.candidate_rows_before_split_purge",
    )
    admitted_candidate = source_counts["CANDIDATE_DECISION_OUTCOME_V2"]
    candidate_considered = _nonnegative_int(
        manifest.get("candidate_records_considered"),
        "manifest.candidate_records_considered",
    )
    candidate_loaded = _nonnegative_int(
        manifest.get("candidate_records_loaded_for_dataset"),
        "manifest.candidate_records_loaded_for_dataset",
    )
    if (
        candidate_considered != archive_candidate_count
        or candidate_loaded != archive_matured_count
        or candidate_matured != archive_matured_count
        or candidate_eligible + sum(rejection_counts.values()) != candidate_matured
        or admitted_candidate > candidate_eligible
        or manifest.get("candidate_rejection_count") != sum(rejection_counts.values())
    ):
        _fail("CANDIDATE_ACCOUNTING_MISMATCH", "manifest")
    purged_ids = manifest.get("purged_row_ids")
    embargo_ids = manifest.get("embargo_row_ids")
    if (
        type(purged_ids) is not list
        or type(embargo_ids) is not list
        or len(purged_ids) != len(set(purged_ids))
        or len(embargo_ids) != len(set(embargo_ids))
        or len(purged_ids) != sum(purge_counts.values())
        or not set(embargo_ids) <= set(purged_ids)
        or set(row_ids) & set(purged_ids)
        or manifest.get("embargo_row_count") != len(embargo_ids)
    ):
        _fail("PURGE_EMBARGO_ACCOUNTING_MISMATCH", "manifest")
    train_rows = [row for row in rows if row["split"] == "train"]
    validation_rows = [row for row in rows if row["split"] == "validation"]
    holdout_rows = [row for row in rows if row["split"] == "holdout"]
    if not train_rows or not validation_rows or not holdout_rows:
        _fail("NONEMPTY_SPLITS_REQUIRED", "dataset")
    if max(_utc(row["label_available_at"], "label_available_at") for row in train_rows) >= min(
        _utc(row["decision_time"], "decision_time") for row in validation_rows
    ):
        _fail("TRAIN_LABEL_OVERLAPS_VALIDATION", "dataset")
    if max(
        _utc(row["label_available_at"], "label_available_at") for row in validation_rows
    ) >= min(_utc(row["decision_time"], "decision_time") for row in holdout_rows):
        _fail("VALIDATION_LABEL_OVERLAPS_HOLDOUT", "dataset")
    if (
        parity.get("feature_abi_sha256") != feature_abi_sha256()
        or parity.get("training_feature_builder_sha256") != feature_builder_sha256()
        or parity.get("serving_feature_builder_sha256") != feature_builder_sha256()
        or parity.get("builder_match") is not True
        or parity.get("ordered_feature_names_match") is not True
        or parity.get("required_feature_missing_rate") != 0.0
        or parity.get("activation_eligible") is not False
        or parity.get("paper_only") is not True
        or parity.get("live_eligible") is not False
        or any(parity.get(field) != split_counts[split] for split, field in split_fields.items())
    ):
        _fail("TRAIN_SERVE_PARITY_INVALID", "parity")
    for field in split_fields.values():
        if receipt.get(field) != manifest.get(field):
            _fail("RECEIPT_SPLIT_COUNT_MISMATCH", f"build_receipt.{field}")
    return dataset, manifest, parity, receipt


__all__ = [
    "ServingTrainingArtifactError",
    "load_validated_training_artifacts",
]
