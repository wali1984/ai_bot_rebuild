"""Append-only evidence producers for the live-grade reverify gate.

This module intentionally lives outside the frozen selector/status publisher
manifest. It imports the frozen selector helpers as read-only code, writes local
evidence artifacts only, and never submits orders, mutates exchange leverage, or
writes Redis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_adaptive_capital_productivity_status as status_module


SCHEMA_VERSION = "v2_out_of_sample_reverify_evidence_producer_v1"
EXPECTED_SELECTOR_POLICY_FINGERPRINT = (
    "c4b8fb1ed12aabcb87224723f1758563eefff10de90288be09866d2bf3fa74b5"
)
REPLAY_EXPECTANCY_AFTER_COST_BPS = 41.76153327
MIN_REALTIME_EXPECTANCY_AFTER_COST_BPS = 20.88076664

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_adaptive_capital_productivity/latest"
)
DEFAULT_BUCKET_MATRIX_PATH = DEFAULT_OUT_DIR / "a_grade_bucket_performance_matrix.json"
DEFAULT_HOLDOUT_SOURCE_JSONL = DEFAULT_OUT_DIR / "closed_candle_replay_evidence_rows.jsonl"
DEFAULT_HOLDOUT_ROWS_PATH = DEFAULT_OUT_DIR / "out_of_sample_holdout_reverify_rows.jsonl"
DEFAULT_REALTIME_ROWS_PATH = DEFAULT_OUT_DIR / "out_of_sample_realtime_paper_reverify_rows.jsonl"
DEFAULT_HOLDOUT_REGISTRY_PATH = DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry.json"
DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_window_registry_preflight.json"
)
DEFAULT_PAPER_LIVE_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest"
    / "v2_trade_management_paper_live_status.json"
)
DEFAULT_PAPER_LEDGER_TAIL_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_ledger_tail.json"
)
DEFAULT_PAPER_EVENTS_PATH = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_events.jsonl"
)
DEFAULT_INTEGRITY_STATUS_PATH = DEFAULT_OUT_DIR / "out_of_sample_evidence_integrity_status.json"
_CHAIN_LAST_HASH_BY_PATH: dict[Path, str] = {}

PENDING_ELIGIBLE_SOURCE_KINDS = {
    "filesystem_runtime_snapshot",
    "redis_paper_intent",
    "redis_paper_signal",
    "redis_prediction",
}
HISTORICAL_REDIS_SOURCE_KINDS = {
    "redis_paper_ledger_accepted",
    "redis_paper_ledger_open",
}

OUTCOME_FIELDS = {
    "after_cost_return_bps",
    "realized_after_cost_return_bps",
    "realized_pnl_bps",
    "paper_exit_pnl_bps",
    "outcome_after_cost_usd",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "future_label_close_time",
    "future_label_horizon_candles",
    "closed_at",
    "exit_time",
    "exit_price",
    "mfe_bps",
    "mae_bps",
    "drawdown_bps",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_payload(payload: Any) -> str:
    return _sha256_text(_stable_json(payload))


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def _sidecar_manifest_path(rows_path: Path) -> Path:
    return rows_path.with_suffix(rows_path.suffix + ".manifest.json")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=False, separators=(",", ":")) + "\n")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def _iter_jsonl(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    scanned = 0
    if not path.exists():
        return rows, {
            "path": str(path),
            "exists": False,
            "scanned_line_count": 0,
            "parse_error_count": 0,
            "parse_error_sample": [],
            "sha256": None,
        }
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            scanned += 1
            try:
                payload = json.loads(stripped)
            except Exception as exc:  # noqa: BLE001
                if len(parse_errors) < 20:
                    parse_errors.append({"line_number": line_number, "error": str(exc)})
                continue
            if isinstance(payload, dict):
                payload.setdefault("_source_line_number", line_number)
                rows.append(payload)
    return rows, {
        "path": str(path),
        "exists": True,
        "scanned_line_count": scanned,
        "parse_error_count": len(parse_errors),
        "parse_error_sample": parse_errors,
        "sha256": _file_sha256(path),
    }


def _rows_from_json(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = _load_json(path)
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("rows", "items", "entries", "closed_trades", "accepted", "open_positions"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(dict(row) for row in value if isinstance(row, dict))
        if not rows:
            observations = payload.get("shadow_observations")
            if isinstance(observations, list):
                rows.extend(dict(row) for row in observations if isinstance(row, dict))
    elif isinstance(payload, list):
        rows.extend(dict(row) for row in payload if isinstance(row, dict))
    return rows, {
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "sha256": _file_sha256(path),
    }


def _existing_identities(path: Path) -> set[str]:
    rows, _status = _iter_jsonl(path)
    identities: set[str] = set()
    for row in rows:
        identity = str(row.get("candidate_identity") or row.get("position_identity") or "")
        if identity:
            identities.add(identity)
    return identities


def _existing_rows_by_identity(path: Path) -> dict[str, dict[str, Any]]:
    rows, _status = _iter_jsonl(path)
    by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get("candidate_identity") or row.get("position_identity") or "")
        if identity and identity not in by_identity:
            by_identity[identity] = row
    return by_identity


def _last_chain_hash(path: Path) -> str:
    if not path.exists():
        return "GENESIS"
    last_hash = "GENESIS"
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("chain_hash"):
                last_hash = str(payload["chain_hash"])
    return last_hash


def _append_chain(
    *,
    chain_path: Path,
    event_type: str,
    sidecar_path: Path,
    identity: str,
    payload: dict[str, Any],
    generated_utc: str,
) -> dict[str, str]:
    record_hash = _sha256_payload(payload)
    if chain_path not in _CHAIN_LAST_HASH_BY_PATH:
        _CHAIN_LAST_HASH_BY_PATH[chain_path] = _last_chain_hash(chain_path)
    previous_hash = _CHAIN_LAST_HASH_BY_PATH[chain_path]
    chain_record = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "event_type": event_type,
        "sidecar_path": str(sidecar_path),
        "identity": identity,
        "previous_hash": previous_hash,
        "record_hash": record_hash,
    }
    chain_hash = _sha256_payload(chain_record)
    chain_record["chain_hash"] = chain_hash
    _append_jsonl(chain_path, chain_record)
    _CHAIN_LAST_HASH_BY_PATH[chain_path] = chain_hash
    return {
        "record_hash": record_hash,
        "previous_hash": previous_hash,
        "chain_hash": chain_hash,
    }


def _payload_without_chain_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    stripped = dict(payload)
    stripped.pop("producer_hash_chain", None)
    return stripped


def _possible_sidecar_hashes(row: dict[str, Any]) -> set[str]:
    stripped = _payload_without_chain_metadata(row)
    hashes = {_sha256_payload(stripped)}
    if "_source_line_number" in stripped:
        without_line = dict(stripped)
        without_line.pop("_source_line_number", None)
        hashes.add(_sha256_payload(without_line))
    return hashes


def _sidecar_hash_index(paths: list[Path]) -> tuple[dict[str, dict[str, list[int]]], dict[str, int], dict[str, Any]]:
    hash_index: dict[str, dict[str, list[int]]] = {}
    row_counts: dict[str, int] = {}
    statuses: dict[str, Any] = {}
    for path in paths:
        rows, source_status = _iter_jsonl(path)
        path_key = str(path)
        row_counts[path_key] = len(rows)
        statuses[path_key] = {
            **source_status,
            "row_count": len(rows),
        }
        indexed: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            for row_hash in _possible_sidecar_hashes(row):
                indexed.setdefault(row_hash, []).append(index)
        hash_index[path_key] = indexed
    return hash_index, row_counts, statuses


def verify_hash_chain(
    *,
    chain_path: Path,
    sidecar_paths: list[Path],
    generated_utc: str,
) -> dict[str, Any]:
    chain_rows, chain_status = _iter_jsonl(chain_path)
    hash_index, sidecar_row_counts, sidecar_statuses = _sidecar_hash_index(sidecar_paths)
    consumed_indices: dict[str, set[int]] = {path: set() for path in sidecar_row_counts}
    failures: list[dict[str, Any]] = []
    previous_hash = "GENESIS"
    verified_records = 0
    event_type_counts: dict[str, int] = {}

    for index, chain_record in enumerate(chain_rows):
        event_type = str(chain_record.get("event_type") or "UNKNOWN")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        chain_hash = str(chain_record.get("chain_hash") or "")
        chain_without_hash = dict(chain_record)
        chain_without_hash.pop("chain_hash", None)
        chain_without_hash.pop("_source_line_number", None)
        expected_chain_hash = _sha256_payload(chain_without_hash)
        if chain_record.get("previous_hash") != previous_hash:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_PREVIOUS_HASH_MISMATCH",
                "expected_previous_hash": previous_hash,
                "actual_previous_hash": chain_record.get("previous_hash"),
            })
        if chain_hash != expected_chain_hash:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_HASH_MISMATCH",
                "expected_chain_hash": expected_chain_hash,
                "actual_chain_hash": chain_hash,
            })
        sidecar_path = str(chain_record.get("sidecar_path") or "")
        record_hash = str(chain_record.get("record_hash") or "")
        sidecar_index = hash_index.get(sidecar_path)
        if sidecar_index is None:
            failures.append({
                "index": index,
                "identity": chain_record.get("identity"),
                "reason": "CHAIN_REFERENCES_UNEXPECTED_SIDECAR_PATH",
                "sidecar_path": sidecar_path,
            })
        else:
            candidate_indices = sidecar_index.get(record_hash, [])
            consumed = consumed_indices.setdefault(sidecar_path, set())
            matched_index = next(
                (candidate_index for candidate_index in candidate_indices if candidate_index not in consumed),
                None,
            )
            if matched_index is None:
                failures.append({
                    "index": index,
                    "identity": chain_record.get("identity"),
                    "reason": "CHAIN_RECORD_HASH_NOT_FOUND_IN_SIDECAR",
                    "sidecar_path": sidecar_path,
                    "record_hash": record_hash,
                })
            else:
                consumed.add(matched_index)
                verified_records += 1
        previous_hash = chain_hash

    unchained_sidecar_rows = {
        path: max(0, sidecar_row_counts.get(path, 0) - len(consumed_indices.get(path, set())))
        for path in sidecar_row_counts
    }
    for path, count in sorted(unchained_sidecar_rows.items()):
        if count > 0:
            failures.append({
                "reason": "SIDECAR_ROWS_WITHOUT_CHAIN_RECORD",
                "sidecar_path": path,
                "unchained_row_count": count,
            })

    status = "PASSED_HASH_CHAIN_INTEGRITY" if not failures else "NO_GO_HASH_CHAIN_INTEGRITY_FAILED"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "chain_path": str(chain_path),
        "chain_status": chain_status,
        "sidecar_statuses": sidecar_statuses,
        "chain_record_count": len(chain_rows),
        "verified_sidecar_record_count": verified_records,
        "event_type_counts": {
            key: event_type_counts[key]
            for key in sorted(event_type_counts)
        },
        "unchained_sidecar_row_counts": {
            path: count
            for path, count in sorted(unchained_sidecar_rows.items())
            if count > 0
        },
        "failure_count": len(failures),
        "failure_sample": failures[:50],
    }


def verify_evidence_integrity(
    *,
    holdout_rows: Path,
    realtime_rows: Path,
    out_dir: Path,
    generated_utc: str,
) -> dict[str, Any]:
    holdout_pending = holdout_rows.with_name("out_of_sample_holdout_reverify_pending.jsonl")
    holdout_rejected = holdout_rows.with_name("out_of_sample_holdout_reverify_rejected.jsonl")
    realtime_pending = realtime_rows.with_name("out_of_sample_realtime_paper_reverify_pending.jsonl")
    realtime_rejected = realtime_rows.with_name("out_of_sample_realtime_paper_reverify_rejected.jsonl")
    holdout = verify_hash_chain(
        chain_path=holdout_rows.with_suffix(holdout_rows.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[holdout_rows, holdout_pending, holdout_rejected],
        generated_utc=generated_utc,
    )
    realtime = verify_hash_chain(
        chain_path=realtime_rows.with_suffix(realtime_rows.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[realtime_rows, realtime_pending, realtime_rejected],
        generated_utc=generated_utc,
    )
    status = (
        "PASSED_EVIDENCE_INTEGRITY"
        if holdout.get("status") == "PASSED_HASH_CHAIN_INTEGRITY"
        and realtime.get("status") == "PASSED_HASH_CHAIN_INTEGRITY"
        else "NO_GO_EVIDENCE_INTEGRITY_FAILED"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "verify",
        "status": status,
        "selector_policy_fingerprint": EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "holdout": holdout,
        "realtime": realtime,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(out_dir / DEFAULT_INTEGRITY_STATUS_PATH.name, summary)
    return summary


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _row_identity(row: dict[str, Any]) -> str:
    explicit = status_module._first_present(
        row.get("candidate_identity"),
        row.get("position_identity"),
        row.get("row_id"),
        row.get("intent_id"),
        row.get("paper_intent_id"),
        row.get("prediction_id"),
        row.get("entry_prediction_id"),
        row.get("source_prediction_id"),
        row.get("signal_id"),
        row.get("entry_signal_id"),
        row.get("source_signal_id"),
        row.get("fill_id"),
        row.get("source_redis_key"),
    )
    if explicit not in {None, ""}:
        return str(explicit)
    return "|".join(
        str(value or "")
        for value in (
            status_module._normalized_symbol(row),
            status_module._row_value(row, "timeframe") or row.get("timeframe"),
            status_module._directional_side(row),
            row.get("decision_time") or row.get("entry_feature_decision_time"),
        )
    )


def _candidate_identity(row: dict[str, Any], *, scope: str) -> str:
    raw = f"{scope}|{_row_identity(row)}"
    return _sha256_text(raw)


def _row_identity_alias_values(row: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for field in (
        "row_id",
        "intent_id",
        "source_intent_id",
        "paper_intent_id",
        "paper_fill_intent_id",
        "prediction_id",
        "entry_prediction_id",
        "source_prediction_id",
        "signal_id",
        "entry_signal_id",
        "source_signal_id",
        "fill_id",
        "ledger_row_id",
        "position_id",
        "close_id",
        "outcome_label_id",
    ):
        value = row.get(field)
        if value not in {None, ""}:
            aliases.add(str(value))
    for field in (
        "source_fill_ids",
        "accepted_fill_policy_reconciliation_ids",
    ):
        values = row.get(field)
        if isinstance(values, list):
            aliases.update(str(value) for value in values if value not in {None, ""})
    lineage = row.get("lineage_ids")
    if isinstance(lineage, dict):
        aliases.update(str(value) for value in lineage.values() if value not in {None, ""})
    fallback = _row_identity(row)
    if fallback:
        aliases.add(fallback)
    return aliases


def _candidate_identity_aliases(row: dict[str, Any], *, scope: str) -> set[str]:
    return {
        _sha256_text(f"{scope}|{alias}")
        for alias in _row_identity_alias_values(row)
    }


def _candidate_identity_alias_index(
    rows_by_identity: dict[str, dict[str, Any]],
    *,
    scope: str,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for identity, row in rows_by_identity.items():
        index[identity] = identity
        for alias_identity in _candidate_identity_aliases(row, scope=scope):
            index.setdefault(alias_identity, identity)
    return index


def _resolve_candidate_identity(
    row: dict[str, Any],
    *,
    scope: str,
    alias_index: dict[str, str],
) -> str:
    primary = _candidate_identity(row, scope=scope)
    if primary in alias_index:
        return alias_index[primary]
    for alias_identity in _candidate_identity_aliases(row, scope=scope):
        if alias_identity in alias_index:
            return alias_index[alias_identity]
    return primary


def _without_outcome_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in OUTCOME_FIELDS}


def _setdefault_first(row: dict[str, Any], field: str, *values: Any) -> None:
    if row.get(field) not in {None, ""}:
        return
    value = status_module._first_present(*values)
    if value not in {None, ""}:
        row[field] = value


def _has_realtime_outcome(row: dict[str, Any]) -> bool:
    return (
        status_module._outcome_after_cost_bps(row) is not None
        or status_module._trade_outcome_pnl(row) is not None
    )


def _row_with_outcome_fields(
    selection_row: dict[str, Any],
    outcome_row: dict[str, Any],
) -> dict[str, Any]:
    combined = dict(selection_row)
    for field in OUTCOME_FIELDS:
        if field in outcome_row:
            combined[field] = outcome_row[field]
    return combined


def _normalize_realtime_source_row(
    row: dict[str, Any],
    *,
    source_kind: str,
    source_label: str,
) -> dict[str, Any]:
    normalized = dict(row)
    normalized.setdefault("_producer_source_kind", source_kind)
    normalized.setdefault("_producer_source_path", source_label)
    _setdefault_first(
        normalized,
        "decision_time",
        normalized.get("decision_time"),
        normalized.get("entry_feature_decision_time"),
        normalized.get("strategy_decision_time"),
        normalized.get("entry_price_utc"),
        normalized.get("generated_at"),
        normalized.get("generated_utc"),
    )
    _setdefault_first(
        normalized,
        "generated_at",
        normalized.get("generated_at"),
        normalized.get("entry_feature_generated_at"),
        normalized.get("generated_utc"),
    )
    _setdefault_first(
        normalized,
        "available_at",
        normalized.get("available_at"),
        normalized.get("entry_feature_available_at"),
    )
    _setdefault_first(
        normalized,
        "feature_cutoff",
        normalized.get("feature_cutoff"),
        normalized.get("entry_feature_cutoff"),
        normalized.get("strategy_feature_cutoff"),
    )
    return normalized


def _eligible_bucket_keys(bucket_matrix_path: Path) -> set[tuple[str, ...]]:
    matrix = _load_json(bucket_matrix_path)
    if not isinstance(matrix, dict):
        return set()
    return status_module._eligible_bucket_keys_from_matrix(matrix)


def _selector_reject_reasons(
    row: dict[str, Any],
    *,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> list[str]:
    reasons: list[str] = []
    key = tuple(str(value) for value in status_module._a_grade_bucket_key(row))
    edge = status_module._expected_edge_bps(row)
    side = status_module._directional_side(row)
    if key not in eligible_bucket_keys:
        reasons.append("DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE")
    if edge is None or edge <= 0.0:
        reasons.append("NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE")
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_SIDE")
    if status_module._allocator_decision(row).startswith("BLOCK_"):
        reasons.append("ALLOCATOR_BLOCKED_CANDIDATE")
    reasons.extend(status_module._pre_submit_temporal_reasons(row))
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    return sorted(set(reasons))


def _accounting_reject_reasons(row: dict[str, Any]) -> list[str]:
    coverage = status_module._accelerated_replay_simulation_accounting_coverage([row])
    if coverage.get("status") == "PASSED":
        return []
    missing = coverage.get("missing_field_group_counts") or {}
    return [f"MISSING_ACCOUNTING_{key.upper()}" for key in sorted(missing)]


def _fingerprint_reject_reasons(row: dict[str, Any], *, expected_fingerprint: str) -> list[str]:
    source_fingerprint = status_module._first_present(
        row.get("selector_policy_fingerprint"),
        row.get("frozen_selector_fingerprint"),
        row.get("policy_fingerprint"),
    )
    source_fingerprint = str(source_fingerprint) if source_fingerprint not in {None, ""} else ""
    if source_fingerprint and source_fingerprint != expected_fingerprint:
        return ["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISMATCH"]
    return []


def _post_outcome_selection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("candidate_selected_before_outcome") is False or row.get("selected_before_outcome") is False:
        reasons.append("CANDIDATE_SELECTION_MARKED_AFTER_OUTCOME")
    selected_at = status_module._parse_utc(row.get("candidate_selected_at") or row.get("selected_at"))
    outcome_at = status_module._parse_utc(
        status_module._first_present(row.get("future_label_close_time"), row.get("closed_at"), row.get("exit_time"))
    )
    if selected_at is not None and outcome_at is not None and selected_at >= outcome_at:
        reasons.append("CANDIDATE_SELECTED_AT_OR_AFTER_OUTCOME_TIME")
    return reasons


def _load_holdout_registry(
    *,
    registry_path: Path,
    source_path: Path,
    generated_utc: str,
) -> dict[str, Any]:
    registry = _load_json(registry_path)
    if isinstance(registry, dict):
        return registry
    rows, source_status = _iter_jsonl(source_path)
    symbols = sorted({status_module._normalized_symbol(row) for row in rows if status_module._normalized_symbol(row) != "UNKNOWN"})
    timeframes = sorted({
        str(status_module._row_value(row, "timeframe") or row.get("timeframe"))
        for row in rows
        if status_module._row_value(row, "timeframe") or row.get("timeframe")
    })
    decisions = [
        status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
        for row in rows
    ]
    decisions = [value for value in decisions if value is not None]
    registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": "NO_ELIGIBLE_HOLDOUT_WINDOWS_REGISTERED",
        "selector_policy_fingerprint": EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "source_path": str(source_path),
        "source_sha256": source_status.get("sha256"),
        "source_row_count": len(rows),
        "registered_window_count": 0,
        "source_symbols_sample": symbols[:100],
        "source_symbol_count": len(symbols),
        "source_timeframes": timeframes,
        "source_decision_time_min": (
            min(decisions).isoformat().replace("+00:00", "Z") if decisions else None
        ),
        "source_decision_time_max": (
            max(decisions).isoformat().replace("+00:00", "Z") if decisions else None
        ),
        "windows": [],
        "exclusion_proof": {
            "status": "SOURCE_EXCLUDED_FROM_HOLDOUT_BY_DEFAULT",
            "reason": (
                "The available closed-candle replay source is the accelerated replay "
                "coverage source used by the adaptive-capital replay gate; no window is "
                "countable until explicitly pre-registered with untouched-data proof."
            ),
        },
    }
    _write_json(registry_path, registry)
    return registry


def _row_overlap_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("used_for_dynamic_a_grade_bucket_construction") is True:
        reasons.append("HOLDOUT_OVERLAPS_DYNAMIC_BUCKET_CONSTRUCTION")
    if row.get("used_for_229_candidate_subset") is True:
        reasons.append("HOLDOUT_OVERLAPS_229_CANDIDATE_SUBSET")
    if row.get("selector_training_window_overlap") is True:
        reasons.append("HOLDOUT_OVERLAPS_SELECTOR_TRAINING_WINDOW")
    return reasons


def _window_static_reasons(window: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    start = status_module._parse_utc(window.get("start_decision_time"))
    end = status_module._parse_utc(window.get("end_decision_time"))
    if start is None or end is None:
        reasons.append("HOLDOUT_WINDOW_MISSING_DECISION_TIME_RANGE")
    elif start >= end:
        reasons.append("HOLDOUT_WINDOW_INVALID_DECISION_TIME_RANGE")
    proof = window.get("exclusion_proof") if isinstance(window.get("exclusion_proof"), dict) else {}
    if window.get("eligible_for_holdout") is not True:
        reasons.append("HOLDOUT_WINDOW_NOT_MARKED_ELIGIBLE")
    if proof.get("status") != "PASSED_UNTOUCHED":
        reasons.append("HOLDOUT_EXCLUSION_PROOF_NOT_PASSED")
    return reasons


def _decision_time_holdout_reject_reasons(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> list[str]:
    selection_row = _without_outcome_fields(row)
    reasons: list[str] = []
    reasons.extend(_fingerprint_reject_reasons(selection_row, expected_fingerprint=expected_fingerprint))
    reasons.extend(_row_overlap_reasons(selection_row))
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(selection_row))
    return sorted(set(reasons))


def _holdout_registry_preflight(
    *,
    registry_path: Path,
    registry: dict[str, Any],
    source_path: Path,
    source_status: dict[str, Any],
    source_rows: list[dict[str, Any]],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    generated_utc: str,
) -> dict[str, Any]:
    windows = [window for window in registry.get("windows") or [] if isinstance(window, dict)]
    registry_fingerprint = str(registry.get("selector_policy_fingerprint") or "")
    source_sha256 = source_status.get("sha256")
    registry_source_sha256 = registry.get("source_sha256")
    source_symbols = sorted({
        status_module._normalized_symbol(row)
        for row in source_rows
        if status_module._normalized_symbol(row) != "UNKNOWN"
    })
    source_timeframes = sorted({
        str(status_module._row_value(row, "timeframe") or row.get("timeframe"))
        for row in source_rows
        if status_module._row_value(row, "timeframe") or row.get("timeframe")
    })
    decision_times = [
        status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
        for row in source_rows
    ]
    decision_times = [value for value in decision_times if value is not None]
    global_reasons: list[str] = []
    if registry_fingerprint and registry_fingerprint != expected_fingerprint:
        global_reasons.append("HOLDOUT_REGISTRY_SELECTOR_POLICY_FINGERPRINT_MISMATCH")
    if registry_source_sha256 not in {None, ""} and registry_source_sha256 != source_sha256:
        global_reasons.append("HOLDOUT_REGISTRY_SOURCE_SHA256_MISMATCH")
    if source_status.get("parse_error_count"):
        global_reasons.append("HOLDOUT_SOURCE_PARSE_ERRORS_PRESENT")
    if not windows:
        global_reasons.append("NO_REGISTERED_HOLDOUT_WINDOWS")

    matched_source_identities: set[str] = set()
    total_matching_rows = 0
    total_decision_time_candidate_ready = 0
    total_countable_after_label = 0
    total_overlap_rows = 0
    total_static_eligible_windows = 0
    window_summaries: list[dict[str, Any]] = []

    for window in windows:
        window_registry = {"windows": [window]}
        static_reasons = _window_static_reasons(window)
        if not static_reasons:
            total_static_eligible_windows += 1
        matching_rows = [
            row
            for row in source_rows
            if _window_for_row(row, window_registry) is not None
        ]
        reason_counts: dict[str, int] = {}
        decision_time_candidate_ready = 0
        countable_after_label = 0
        overlap_row_count = 0
        for row in matching_rows:
            matched_source_identities.add(_row_identity(row))
            row_reasons = list(static_reasons)
            row_reasons.extend(_decision_time_holdout_reject_reasons(
                row,
                expected_fingerprint=expected_fingerprint,
                eligible_bucket_keys=eligible_bucket_keys,
            ))
            row_reasons = sorted(set(row_reasons))
            if _row_overlap_reasons(row):
                overlap_row_count += 1
            if row_reasons:
                for reason in row_reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            else:
                decision_time_candidate_ready += 1
                if status_module._outcome_after_cost_bps(row) is not None or status_module._trade_outcome_pnl(row) is not None:
                    countable_after_label += 1
        total_matching_rows += len(matching_rows)
        total_decision_time_candidate_ready += decision_time_candidate_ready
        total_countable_after_label += countable_after_label
        total_overlap_rows += overlap_row_count
        window_summaries.append({
            "window_id": window.get("window_id"),
            "start_decision_time": window.get("start_decision_time"),
            "end_decision_time": window.get("end_decision_time"),
            "eligible_for_holdout": window.get("eligible_for_holdout") is True,
            "exclusion_proof_status": (
                window.get("exclusion_proof", {}).get("status")
                if isinstance(window.get("exclusion_proof"), dict)
                else None
            ),
            "symbols": window.get("symbols") if isinstance(window.get("symbols"), list) else [],
            "timeframes": window.get("timeframes") if isinstance(window.get("timeframes"), list) else [],
            "matching_source_row_count": len(matching_rows),
            "decision_time_candidate_ready_count": decision_time_candidate_ready,
            "countable_after_label_count": countable_after_label,
            "overlap_row_count": overlap_row_count,
            "static_reasons": static_reasons,
            "decision_time_reject_reason_counts": {
                key: reason_counts[key] for key in sorted(reason_counts)
            },
            "status": (
                "READY_HOLDOUT_WINDOW_HAS_DECISION_TIME_CANDIDATES"
                if decision_time_candidate_ready > 0 and not static_reasons
                else "NO_GO_HOLDOUT_WINDOW_NO_DECISION_TIME_CANDIDATES"
                if not static_reasons
                else "NO_GO_HOLDOUT_WINDOW_PREFLIGHT_FAILED"
            ),
        })

    unmatched_source_rows = max(0, len(source_rows) - len(matched_source_identities))
    if windows and total_static_eligible_windows == 0:
        global_reasons.append("NO_STATICALLY_ELIGIBLE_HOLDOUT_WINDOWS")
    if windows and total_matching_rows == 0:
        global_reasons.append("REGISTERED_HOLDOUT_WINDOWS_MATCH_NO_SOURCE_ROWS")
    if total_matching_rows > 0 and total_decision_time_candidate_ready == 0:
        global_reasons.append("NO_DECISION_TIME_A_GRADE_HOLDOUT_CANDIDATES")
    if total_decision_time_candidate_ready > 0 and total_countable_after_label == 0:
        global_reasons.append("NO_LABEL_OUTCOMES_FOR_DECISION_TIME_HOLDOUT_CANDIDATES")
    if total_overlap_rows > 0:
        global_reasons.append("HOLDOUT_REGISTRY_MATCHES_OVERLAPPING_SOURCE_ROWS")

    status = (
        "READY_HOLDOUT_REGISTRY_PREFLIGHT"
        if not global_reasons
        else "NO_GO_NO_REGISTERED_HOLDOUT_WINDOWS"
        if global_reasons == ["NO_REGISTERED_HOLDOUT_WINDOWS"]
        else "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "selector_policy_fingerprint": expected_fingerprint,
        "registry_path": str(registry_path),
        "registry_sha256": _file_sha256(registry_path),
        "registry_status": registry.get("status"),
        "registry_selector_policy_fingerprint": registry.get("selector_policy_fingerprint"),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "registry_source_sha256": registry_source_sha256,
        "source_hash_match": (
            registry_source_sha256 == source_sha256
            if registry_source_sha256 not in {None, ""}
            else None
        ),
        "source_row_count": len(source_rows),
        "source_symbol_count": len(source_symbols),
        "source_symbols_sample": source_symbols[:100],
        "source_timeframes": source_timeframes,
        "source_decision_time_min": (
            min(decision_times).isoformat().replace("+00:00", "Z") if decision_times else None
        ),
        "source_decision_time_max": (
            max(decision_times).isoformat().replace("+00:00", "Z") if decision_times else None
        ),
        "registered_window_count": len(windows),
        "statically_eligible_window_count": total_static_eligible_windows,
        "matching_source_row_count": total_matching_rows,
        "unmatched_source_row_count": unmatched_source_rows,
        "decision_time_candidate_ready_count": total_decision_time_candidate_ready,
        "countable_after_label_count": total_countable_after_label,
        "overlap_row_count": total_overlap_rows,
        "global_reasons": global_reasons,
        "windows": window_summaries,
        "candidate_selection_preflight": {
            "selection_fields_freeze": "decision_time_features_only",
            "outcome_fields_excluded_before_selection": sorted(OUTCOME_FIELDS),
            "future_labels_used_as_features_allowed": False,
            "selection_does_not_filter_by_outcome": True,
        },
    }


def _window_for_row(row: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    decision = status_module._parse_utc(row.get("decision_time") or row.get("entry_feature_decision_time"))
    symbol = status_module._normalized_symbol(row)
    timeframe = str(status_module._row_value(row, "timeframe") or row.get("timeframe") or "")
    if decision is None:
        return None
    for window in registry.get("windows") or []:
        if not isinstance(window, dict):
            continue
        start = status_module._parse_utc(window.get("start_decision_time"))
        end = status_module._parse_utc(window.get("end_decision_time"))
        if start is None or end is None or not (start <= decision <= end):
            continue
        symbols = window.get("symbols")
        timeframes = window.get("timeframes")
        if isinstance(symbols, list) and symbols and symbol not in {str(item).upper() for item in symbols}:
            continue
        if isinstance(timeframes, list) and timeframes and timeframe not in {str(item) for item in timeframes}:
            continue
        return window
    return None


def _holdout_reject_reasons(
    row: dict[str, Any],
    *,
    registry: dict[str, Any],
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_fingerprint_reject_reasons(row, expected_fingerprint=expected_fingerprint))
    reasons.extend(_post_outcome_selection_reasons(row))
    reasons.extend(_row_overlap_reasons(row))
    window = _window_for_row(row, registry)
    if not window:
        reasons.append("NO_PRE_REGISTERED_HOLDOUT_WINDOW")
    else:
        reasons.extend(_window_static_reasons(window))
    selection_row = _without_outcome_fields(row)
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(row))
    if status_module._outcome_after_cost_bps(row) is None and status_module._trade_outcome_pnl(row) is None:
        reasons.append("MISSING_LABEL_OUTCOME")
    return sorted(set(reasons))


def _candidate_record(
    row: dict[str, Any],
    *,
    scope: str,
    expected_fingerprint: str,
    generated_utc: str,
) -> dict[str, Any]:
    candidate = _without_outcome_fields(dict(row))
    identity = _candidate_identity(row, scope=scope)
    candidate.update({
        "schema_version": SCHEMA_VERSION,
        "candidate_identity": identity,
        "selector_policy_fingerprint": expected_fingerprint,
        "candidate_selection_tier": "A_GRADE_EXECUTION_PAPER",
        "out_of_sample_reverify_candidate": True,
        "selected_before_outcome": True,
        "candidate_selected_before_outcome": True,
        "candidate_selected_at": generated_utc,
        "future_labels_used_as_features": False,
        "future_label_used_as_outcome_only": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": status_module.LIVE_GATE,
    })
    return candidate


def _final_holdout_record(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    final = _payload_without_chain_metadata(candidate)
    for field in OUTCOME_FIELDS:
        if field in row:
            final[field] = row[field]
    window = _window_for_row(row, registry) or {}
    final.update({
        "holdout_window_id": window.get("window_id"),
        "untouched_holdout_window": True,
        "out_of_sample_holdout": True,
        "used_for_dynamic_a_grade_bucket_construction": False,
        "used_for_229_candidate_subset": False,
        "selector_training_window_overlap": False,
    })
    return final


def _metric_values(rows: list[dict[str, Any]]) -> list[float]:
    values = [
        value
        for row in rows
        for value in [status_module._outcome_after_cost_bps(row)]
        if value is not None
    ]
    if values:
        return values
    return [
        value
        for row in rows
        for value in [status_module._trade_outcome_pnl(row)]
        if value is not None
    ]


def _profit_concentration(rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    positive: dict[str, float] = {}
    for row in rows:
        metric = status_module._outcome_after_cost_bps(row)
        if metric is None:
            metric = status_module._trade_outcome_pnl(row)
        if metric is None or metric <= 0.0:
            continue
        if dimension == "symbol":
            key = status_module._normalized_symbol(row)
        elif dimension == "timeframe":
            key = str(status_module._row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        elif dimension == "regime":
            key = status_module._market_regime_bucket(row)
        elif dimension == "strategy":
            key = status_module._row_strategy(row)
        else:
            key = "UNKNOWN"
        positive[key] = positive.get(key, 0.0) + metric
    total = sum(positive.values())
    if total <= 0.0:
        return {"dimension": dimension, "top_profit_share": None, "status": "NO_GROSS_PROFIT"}
    top_key, top_value = max(positive.items(), key=lambda item: item[1])
    share = top_value / total
    return {
        "dimension": dimension,
        "status": "PASSED" if share <= 0.35 else "PROFIT_CONCENTRATION_RISK",
        "top_key": top_key,
        "top_profit_share": round(share, 8),
        "maximum_allowed_top_profit_share": 0.35,
    }


def _sidecar_summary(rows_path: Path) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(rows_path)
    values = _metric_values(rows)
    profit_factor, profit_factor_numeric = status_module._profit_factor_from_values(values)
    expectancy = sum(values) / len(values) if values else None
    symbols = sorted({status_module._normalized_symbol(row) for row in rows if status_module._normalized_symbol(row) != "UNKNOWN"})
    side_counts: dict[str, int] = {}
    for row in rows:
        side = status_module._directional_side(row)
        if side:
            side_counts[side] = side_counts.get(side, 0) + 1
    concentration = {
        dimension: _profit_concentration(rows, dimension)
        for dimension in ("symbol", "timeframe", "regime", "strategy")
    }
    return {
        "source_status": source_status,
        "row_count": len(rows),
        "symbol_count": len(symbols),
        "symbols_sample": symbols[:100],
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "expectancy_metric": round(expectancy, 8) if expectancy is not None else None,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            "inf" if profit_factor_numeric == float("inf") else round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None else None
        ),
        "profit_concentration_status": concentration,
    }


def _rejection_ledger_summary(rejected_path: Path) -> dict[str, Any]:
    rows, source_status = _iter_jsonl(rejected_path)
    reason_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    source_kind_reason_counts: dict[str, dict[str, int]] = {}
    combination_counts: dict[str, int] = {}
    samples_by_reason: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        raw_reasons = row.get("reasons")
        reasons = sorted({
            str(reason)
            for reason in raw_reasons
            if reason not in {None, ""}
        }) if isinstance(raw_reasons, list) else []
        if not reasons:
            reasons = ["NO_REASONS_RECORDED"]
        source_kind = str(row.get("source_kind") or row.get("scope") or "UNKNOWN")
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        source_reasons = source_kind_reason_counts.setdefault(source_kind, {})
        combination_key = "|".join(reasons)
        combination_counts[combination_key] = combination_counts.get(combination_key, 0) + 1
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            source_reasons[reason] = source_reasons.get(reason, 0) + 1
            samples = samples_by_reason.setdefault(reason, [])
            if len(samples) < 3:
                samples.append({
                    "candidate_identity": row.get("candidate_identity"),
                    "source_kind": row.get("source_kind"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "side": row.get("side"),
                    "decision_time": row.get("decision_time"),
                })

    top_combinations = sorted(
        (
            {"reasons": key.split("|"), "row_count": count}
            for key, count in combination_counts.items()
        ),
        key=lambda item: (-int(item["row_count"]), item["reasons"]),
    )[:20]
    return {
        "source_status": source_status,
        "row_count": len(rows),
        "reason_counts": {
            key: reason_counts[key]
            for key in sorted(reason_counts)
        },
        "source_kind_counts": {
            key: source_kind_counts[key]
            for key in sorted(source_kind_counts)
        },
        "source_kind_reason_counts": {
            source_kind: {
                reason: reason_counts_by_source[reason]
                for reason in sorted(reason_counts_by_source)
            }
            for source_kind, reason_counts_by_source in sorted(source_kind_reason_counts.items())
        },
        "top_reason_combinations": top_combinations,
        "samples_by_reason": {
            key: samples_by_reason[key]
            for key in sorted(samples_by_reason)
        },
    }


def _rejection_reason_category(reason: str) -> str:
    if reason.startswith("MISSING_ACCOUNTING_"):
        return "accounting"
    if reason in {
        "DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE",
        "NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE",
        "NON_DIRECTIONAL_SIDE",
        "ALLOCATOR_BLOCKED_CANDIDATE",
    }:
        return "frozen_selector"
    if (
        reason.startswith("MISSING_")
        or "_AFTER_" in reason
        or reason in {"FUTURE_LABELS_USED_AS_FEATURES"}
    ):
        return "point_in_time_lineage"
    if "FINGERPRINT" in reason:
        return "fingerprint"
    if reason.startswith("REALTIME_SOURCE_"):
        return "safety"
    if (
        "PENDING_SELECTION" in reason
        or "HISTORICAL_SOURCE" in reason
        or "CLOSED_OUTCOME" in reason
        or "SOURCE_KIND_NOT_ELIGIBLE" in reason
        or "CANDIDATE_SELECTED" in reason
        or "CANDIDATE_SELECTION" in reason
        or reason.startswith("HOLDOUT_")
        or reason.startswith("NO_PRE_REGISTERED_HOLDOUT")
    ):
        return "evidence_protocol"
    return "other"


def _new_source_gate_breakdown(*, processed_source_row_count: int) -> dict[str, Any]:
    return {
        "processed_source_row_count": processed_source_row_count,
        "existing_final_duplicate_count": 0,
        "candidate_ready_source_row_count": 0,
        "rejected_source_row_count": 0,
        "category_counts": {},
        "reason_counts": {},
        "_combination_counts": {},
    }


def _record_source_gate_result(
    breakdown: dict[str, Any],
    *,
    reasons: list[str],
) -> None:
    if not reasons:
        breakdown["candidate_ready_source_row_count"] += 1
        return
    breakdown["rejected_source_row_count"] += 1
    category_counts = breakdown["category_counts"]
    reason_counts = breakdown["reason_counts"]
    for reason in reasons:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        category = _rejection_reason_category(reason)
        category_counts[category] = category_counts.get(category, 0) + 1
    combination_key = "|".join(sorted(reasons))
    combinations = breakdown["_combination_counts"]
    combinations[combination_key] = combinations.get(combination_key, 0) + 1


def _finalize_source_gate_breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    combinations = breakdown.pop("_combination_counts", {})
    breakdown["category_counts"] = {
        key: breakdown["category_counts"][key]
        for key in sorted(breakdown["category_counts"])
    }
    breakdown["reason_counts"] = {
        key: breakdown["reason_counts"][key]
        for key in sorted(breakdown["reason_counts"])
    }
    breakdown["top_reason_combinations"] = sorted(
        (
            {"reasons": key.split("|"), "row_count": count}
            for key, count in combinations.items()
        ),
        key=lambda item: (-int(item["row_count"]), item["reasons"]),
    )[:20]
    return breakdown


def produce_holdout(
    *,
    source_jsonl: Path,
    rows_path: Path,
    registry_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    max_rows: int | None,
    generated_utc: str,
) -> dict[str, Any]:
    _touch(rows_path)
    pending_path = rows_path.with_name("out_of_sample_holdout_reverify_pending.jsonl")
    rejected_path = rows_path.with_name("out_of_sample_holdout_reverify_rejected.jsonl")
    chain_path = rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl")
    manifest_path = rows_path.with_suffix(rows_path.suffix + ".manifest.json")
    registry = _load_holdout_registry(
        registry_path=registry_path,
        source_path=source_jsonl,
        generated_utc=generated_utc,
    )
    rows, source_status = _iter_jsonl(source_jsonl)
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    existing_final = _existing_identities(rows_path)
    pending_by_identity = _existing_rows_by_identity(pending_path)
    preexisting_pending = set(pending_by_identity)
    existing_pending = set(pending_by_identity)
    existing_rejected = _existing_identities(rejected_path)
    accepted = 0
    rejected = 0
    duplicate = 0
    pending = 0
    reason_counts: dict[str, int] = {}
    source_rows = rows[:max_rows] if max_rows is not None else rows
    preflight_path = registry_path.with_name(DEFAULT_HOLDOUT_REGISTRY_PREFLIGHT_PATH.name)
    registry_preflight = _holdout_registry_preflight(
        registry_path=registry_path,
        registry=registry,
        source_path=source_jsonl,
        source_status=source_status,
        source_rows=source_rows,
        expected_fingerprint=expected_fingerprint,
        eligible_bucket_keys=eligible_keys,
        generated_utc=generated_utc,
    )
    _write_json(preflight_path, registry_preflight)
    source_gate_breakdown = _new_source_gate_breakdown(
        processed_source_row_count=len(source_rows),
    )
    for source_row in source_rows:
        identity = _candidate_identity(source_row, scope="holdout")
        if identity in existing_final:
            duplicate += 1
            source_gate_breakdown["existing_final_duplicate_count"] += 1
            continue
        reasons = _holdout_reject_reasons(
            source_row,
            registry=registry,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
        )
        _record_source_gate_result(source_gate_breakdown, reasons=reasons)
        if reasons:
            if identity in existing_rejected:
                duplicate += 1
                continue
            rejected += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            rejection = {
                "schema_version": SCHEMA_VERSION,
                "generated_utc": generated_utc,
                "scope": "holdout",
                "candidate_identity": identity,
                "source_row_identity": _row_identity(source_row),
                "symbol": status_module._normalized_symbol(source_row),
                "timeframe": status_module._row_value(source_row, "timeframe") or source_row.get("timeframe"),
                "side": status_module._directional_side(source_row),
                "decision_time": source_row.get("decision_time") or source_row.get("entry_feature_decision_time"),
                "reasons": reasons,
            }
            chain = _append_chain(
                chain_path=chain_path,
                event_type="holdout_rejected",
                sidecar_path=rejected_path,
                identity=identity,
                payload=rejection,
                generated_utc=generated_utc,
            )
            rejection["producer_hash_chain"] = chain
            _append_jsonl(rejected_path, rejection)
            existing_rejected.add(identity)
            continue
        candidate = pending_by_identity.get(identity)
        if candidate is None:
            candidate = _candidate_record(
                source_row,
                scope="holdout",
                expected_fingerprint=expected_fingerprint,
                generated_utc=generated_utc,
            )
        if identity not in existing_pending:
            pending_chain = _append_chain(
                chain_path=chain_path,
                event_type="holdout_candidate_selected_before_label",
                sidecar_path=pending_path,
                identity=identity,
                payload=candidate,
                generated_utc=generated_utc,
            )
            candidate["producer_hash_chain"] = pending_chain
            _append_jsonl(pending_path, candidate)
            existing_pending.add(identity)
            pending_by_identity[identity] = candidate
            pending += 1
            continue
        if identity not in preexisting_pending:
            duplicate += 1
            continue
        final = _final_holdout_record(source_row, candidate=candidate, registry=registry)
        final_chain = _append_chain(
            chain_path=chain_path,
            event_type="holdout_labeled",
            sidecar_path=rows_path,
            identity=identity,
            payload=final,
            generated_utc=generated_utc,
        )
        final["producer_hash_chain"] = final_chain
        _append_jsonl(rows_path, final)
        existing_final.add(identity)
        accepted += 1
    sidecar = _sidecar_summary(rows_path)
    rejection_ledger = _rejection_ledger_summary(rejected_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "holdout",
        "status": (
            "READY"
            if accepted > 0
            else "READY_HOLDOUT_PENDING_SELECTIONS_APPENDED"
            if pending > 0
            else "NO_COUNTABLE_HOLDOUT_ROWS_APPENDED"
        ),
        "selector_policy_fingerprint": expected_fingerprint,
        "holdout_labeling_policy": "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD",
        "labeled_from_preexisting_pending_count": accepted,
        "same_run_pending_rows_not_labeled_count": pending,
        "source_status": source_status,
        "bucket_matrix_path": str(bucket_matrix_path),
        "eligible_bucket_count": len(eligible_keys),
        "registry_path": str(registry_path),
        "registry_status": registry.get("status"),
        "holdout_registry_preflight_path": str(preflight_path),
        "holdout_registry_preflight": registry_preflight,
        "registered_window_count": len(registry.get("windows") or []),
        "processed_source_row_count": len(source_rows),
        "accepted_appended_count": accepted,
        "pending_appended_count": pending,
        "rejected_appended_count": rejected,
        "duplicate_skipped_count": duplicate,
        "rejection_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "source_gate_breakdown": _finalize_source_gate_breakdown(source_gate_breakdown),
        "rejection_ledger_summary": rejection_ledger,
        "sidecar_summary": sidecar,
        "hash_chain_path": str(chain_path),
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    return manifest


def _realtime_rows_from_redis(*, scan_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = status_module._connect_redis()
    if client is None:
        return [], {
            "source": "redis",
            "status": "REDIS_UNAVAILABLE",
            "row_count": 0,
            "read_only": True,
        }
    ledger = status_module._redis_json(client, "v2:paper:ledger") or {}
    paper_signals = status_module._scan_redis_json_rows(
        client,
        "v2:signals:paper:*",
        limit=scan_limit,
    )
    prediction_rows = status_module._scan_redis_json_rows(
        client,
        "v2:prediction:*",
        limit=scan_limit,
    )
    latest_feature_rows = status_module._scan_redis_json_rows(
        client,
        "v2:features:latest:*",
        limit=scan_limit,
    )
    archived_feature_rows = status_module._read_archived_feature_rows_from_redis(
        client,
        prediction_rows + paper_signals,
        limit=scan_limit,
    )
    feature_rows = latest_feature_rows + archived_feature_rows
    prediction_rows = status_module._prediction_rows_with_pit_feature_market_cost_context(
        prediction_rows,
        feature_rows,
    )
    paper_intents = status_module._read_paper_intents_from_redis(
        client,
        fallback_ledger=ledger if isinstance(ledger, dict) else None,
    )
    counterfactual_paper_signals = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
    )
    accepted_rows = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "accepted")
    raw_closed_trades = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "closed_trades")
    closed_trades, accepted_reconciliation = status_module._reconcile_closed_trades_with_accepted_fills(
        closed_trades=raw_closed_trades,
        accepted_rows=accepted_rows,
    )
    open_positions = status_module._safe_rows(ledger if isinstance(ledger, dict) else {}, "open_positions")
    durable_accepted_rows, durable_accepted_evidence = status_module._paper_ledger_accepted_counterfactual_rows(
        ledger_payload=ledger if isinstance(ledger, dict) else {},
        base_source_rows=[*counterfactual_paper_signals, *paper_intents],
    )

    source_groups: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("redis_paper_intent", "v2:paper:intents+held", paper_intents),
        ("redis_paper_signal", "v2:signals:paper:*", counterfactual_paper_signals),
        ("redis_prediction", "v2:prediction:*", prediction_rows),
        ("redis_paper_ledger_accepted", "v2:paper:ledger.accepted", durable_accepted_rows),
        ("redis_paper_ledger_open", "v2:paper:ledger.open_positions", open_positions),
        ("redis_paper_ledger_closed", "v2:paper:ledger.closed_trades", closed_trades),
    ]
    rows: list[dict[str, Any]] = []
    group_counts: dict[str, int] = {}
    for source_kind, source_label, source_rows in source_groups:
        normalized_rows = [
            _normalize_realtime_source_row(
                row,
                source_kind=source_kind,
                source_label=source_label,
            )
            for row in source_rows
            if isinstance(row, dict)
        ]
        rows.extend(normalized_rows)
        group_counts[source_kind] = len(normalized_rows)
    return rows, {
        "source": "redis",
        "status": "READY_READ_ONLY_REDIS_SOURCE",
        "row_count": len(rows),
        "read_only": True,
        "scan_limit": scan_limit,
        "source_group_counts": group_counts,
        "paper_signal_row_count": len(paper_signals),
        "prediction_row_count": len(prediction_rows),
        "latest_feature_row_count": len(latest_feature_rows),
        "archived_feature_row_count": len(archived_feature_rows),
        "accepted_fill_reconciliation": accepted_reconciliation,
        "durable_accepted_counterfactual_evidence": durable_accepted_evidence,
    }


def _realtime_source_rows(
    json_sources: list[Path],
    jsonl_sources: list[Path],
    *,
    include_redis: bool,
    redis_scan_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for path in json_sources:
        source_rows, source_status = _rows_from_json(path)
        rows.extend(
            _normalize_realtime_source_row(
                row,
                source_kind="filesystem_runtime_snapshot",
                source_label=str(path),
            )
            for row in source_rows
        )
        statuses.append(source_status)
    for path in jsonl_sources:
        source_rows, source_status = _iter_jsonl(path)
        rows.extend(
            _normalize_realtime_source_row(
                row,
                source_kind="filesystem_runtime_snapshot",
                source_label=str(path),
            )
            for row in source_rows
        )
        statuses.append(source_status)
    if include_redis:
        redis_rows, redis_status = _realtime_rows_from_redis(scan_limit=redis_scan_limit)
        rows.extend(redis_rows)
        statuses.append(redis_status)
    return rows, statuses


def _realtime_reject_reasons(
    row: dict[str, Any],
    *,
    expected_fingerprint: str,
    eligible_bucket_keys: set[tuple[str, ...]],
    require_pending_for_closed: bool,
    pending_by_identity: dict[str, dict[str, Any]],
    resolved_identity: str,
    closed_outcome_identities: set[str],
) -> list[str]:
    reasons: list[str] = []
    identity = resolved_identity
    has_outcome = _has_realtime_outcome(row)
    pending_selection = pending_by_identity.get(identity)
    validation_selection = pending_selection if has_outcome and pending_selection is not None else row
    accounting_row = (
        _row_with_outcome_fields(validation_selection, row)
        if has_outcome and pending_selection is not None
        else row
    )
    reasons.extend(_fingerprint_reject_reasons(validation_selection, expected_fingerprint=expected_fingerprint))
    reasons.extend(_post_outcome_selection_reasons(validation_selection))
    selection_row = _without_outcome_fields(validation_selection)
    reasons.extend(_selector_reject_reasons(selection_row, eligible_bucket_keys=eligible_bucket_keys))
    reasons.extend(_accounting_reject_reasons(accounting_row))
    if validation_selection.get("paper_only") is False or row.get("paper_only") is False:
        reasons.append("REALTIME_SOURCE_NOT_PAPER_ONLY")
    if (
        validation_selection.get("places_real_order") is True
        or validation_selection.get("live_order") is True
        or row.get("places_real_order") is True
        or row.get("live_order") is True
    ):
        reasons.append("REALTIME_SOURCE_REAL_ORDER_FLAG_TRUE")
    if (
        validation_selection.get("legacy_redis_write") is True
        or validation_selection.get("writes_legacy_redis") is True
        or row.get("legacy_redis_write") is True
        or row.get("writes_legacy_redis") is True
    ):
        reasons.append("REALTIME_SOURCE_OLD_REDIS_WRITE_TRUE")
    if has_outcome and require_pending_for_closed and pending_selection is None:
        reasons.append("MISSING_PENDING_SELECTION_RECORD_FOR_CLOSED_OUTCOME")
    source_kind = str(row.get("_producer_source_kind") or "")
    if (
        not has_outcome
        and pending_selection is None
        and source_kind in HISTORICAL_REDIS_SOURCE_KINDS
    ):
        reasons.append("HISTORICAL_SOURCE_CANNOT_CREATE_NEW_PENDING_RECORD")
    if (
        not has_outcome
        and pending_selection is None
        and (
            identity in closed_outcome_identities
            or bool(_candidate_identity_aliases(row, scope="realtime") & closed_outcome_identities)
        )
    ):
        reasons.append("HISTORICAL_ACCEPTED_ROW_ALREADY_HAS_CLOSED_OUTCOME_NO_PRIOR_PENDING_RECORD")
    if (
        not has_outcome
        and pending_selection is None
        and source_kind
        and source_kind not in PENDING_ELIGIBLE_SOURCE_KINDS
    ):
        reasons.append("SOURCE_KIND_NOT_ELIGIBLE_TO_CREATE_PENDING_RECORD")
    return sorted(set(reasons))


def _final_realtime_record(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    final = _payload_without_chain_metadata(candidate)
    for field in OUTCOME_FIELDS:
        if field in row:
            final[field] = row[field]
    final.update({
        "realtime_paper_reverify": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": status_module.LIVE_GATE,
    })
    return final


def produce_realtime(
    *,
    rows_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    json_sources: list[Path],
    jsonl_sources: list[Path],
    include_redis: bool,
    redis_scan_limit: int,
    require_pending_for_closed: bool,
    max_rows: int | None,
    generated_utc: str,
) -> dict[str, Any]:
    _touch(rows_path)
    pending_path = rows_path.with_name("out_of_sample_realtime_paper_reverify_pending.jsonl")
    rejected_path = rows_path.with_name("out_of_sample_realtime_paper_reverify_rejected.jsonl")
    chain_path = rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl")
    manifest_path = rows_path.with_suffix(rows_path.suffix + ".manifest.json")
    source_rows, source_statuses = _realtime_source_rows(
        json_sources,
        jsonl_sources,
        include_redis=include_redis,
        redis_scan_limit=redis_scan_limit,
    )
    source_rows = source_rows[:max_rows] if max_rows is not None else source_rows
    source_gate_breakdown = _new_source_gate_breakdown(
        processed_source_row_count=len(source_rows),
    )
    eligible_keys = _eligible_bucket_keys(bucket_matrix_path)
    existing_final = _existing_identities(rows_path)
    pending_by_identity = _existing_rows_by_identity(pending_path)
    pending_alias_index = _candidate_identity_alias_index(pending_by_identity, scope="realtime")
    existing_pending = set(pending_by_identity)
    existing_rejected = _existing_identities(rejected_path)
    closed_outcome_identities = {
        alias_identity
        for row in source_rows
        if _has_realtime_outcome(row)
        for alias_identity in _candidate_identity_aliases(row, scope="realtime")
    }
    accepted = 0
    pending = 0
    rejected = 0
    duplicate = 0
    reason_counts: dict[str, int] = {}
    for source_row in source_rows:
        identity = _resolve_candidate_identity(
            source_row,
            scope="realtime",
            alias_index=pending_alias_index,
        )
        if identity in existing_final:
            duplicate += 1
            source_gate_breakdown["existing_final_duplicate_count"] += 1
            continue
        reasons = _realtime_reject_reasons(
            source_row,
            expected_fingerprint=expected_fingerprint,
            eligible_bucket_keys=eligible_keys,
            require_pending_for_closed=require_pending_for_closed,
            pending_by_identity=pending_by_identity,
            resolved_identity=identity,
            closed_outcome_identities=closed_outcome_identities,
        )
        _record_source_gate_result(source_gate_breakdown, reasons=reasons)
        if reasons:
            if identity in existing_rejected:
                duplicate += 1
                continue
            rejected += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            rejection = {
                "schema_version": SCHEMA_VERSION,
                "generated_utc": generated_utc,
                "scope": "realtime",
                "candidate_identity": identity,
                "source_row_identity": _row_identity(source_row),
                "source_path": source_row.get("_producer_source_path"),
                "source_kind": source_row.get("_producer_source_kind"),
                "symbol": status_module._normalized_symbol(source_row),
                "timeframe": status_module._row_value(source_row, "timeframe") or source_row.get("timeframe"),
                "side": status_module._directional_side(source_row),
                "decision_time": source_row.get("decision_time") or source_row.get("entry_feature_decision_time"),
                "reasons": reasons,
            }
            chain = _append_chain(
                chain_path=chain_path,
                event_type="realtime_rejected",
                sidecar_path=rejected_path,
                identity=identity,
                payload=rejection,
                generated_utc=generated_utc,
            )
            rejection["producer_hash_chain"] = chain
            _append_jsonl(rejected_path, rejection)
            existing_rejected.add(identity)
            continue
        has_outcome = _has_realtime_outcome(source_row)
        candidate = pending_by_identity.get(identity)
        if candidate is None:
            candidate = _candidate_record(
                source_row,
                scope="realtime",
                expected_fingerprint=expected_fingerprint,
                generated_utc=generated_utc,
            )
        if identity not in existing_pending:
            pending_chain = _append_chain(
                chain_path=chain_path,
                event_type="realtime_candidate_pending",
                sidecar_path=pending_path,
                identity=identity,
                payload=candidate,
                generated_utc=generated_utc,
            )
            candidate["producer_hash_chain"] = pending_chain
            _append_jsonl(pending_path, candidate)
            existing_pending.add(identity)
            pending_by_identity[identity] = candidate
            for alias_identity in _candidate_identity_aliases(candidate, scope="realtime"):
                pending_alias_index.setdefault(alias_identity, identity)
            pending += 1
        if not has_outcome:
            continue
        final = _final_realtime_record(source_row, candidate=candidate)
        final_chain = _append_chain(
            chain_path=chain_path,
            event_type="realtime_closed_outcome_labeled",
            sidecar_path=rows_path,
            identity=identity,
            payload=final,
            generated_utc=generated_utc,
        )
        final["producer_hash_chain"] = final_chain
        _append_jsonl(rows_path, final)
        existing_final.add(identity)
        accepted += 1
    sidecar = _sidecar_summary(rows_path)
    rejection_ledger = _rejection_ledger_summary(rejected_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "producer": "realtime",
        "status": "READY" if accepted > 0 else "NO_COUNTABLE_REALTIME_ROWS_APPENDED",
        "selector_policy_fingerprint": expected_fingerprint,
        "source_statuses": source_statuses,
        "bucket_matrix_path": str(bucket_matrix_path),
        "eligible_bucket_count": len(eligible_keys),
        "processed_source_row_count": len(source_rows),
        "include_redis": include_redis,
        "redis_scan_limit": redis_scan_limit,
        "accepted_appended_count": accepted,
        "pending_appended_count": pending,
        "rejected_appended_count": rejected,
        "duplicate_skipped_count": duplicate,
        "rejection_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "source_gate_breakdown": _finalize_source_gate_breakdown(source_gate_breakdown),
        "rejection_ledger_summary": rejection_ledger,
        "sidecar_summary": sidecar,
        "hash_chain_path": str(chain_path),
        "replay_projection_expectancy_after_cost_bps": REPLAY_EXPECTANCY_AFTER_COST_BPS,
        "minimum_realtime_expectancy_after_cost_bps": MIN_REALTIME_EXPECTANCY_AFTER_COST_BPS,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    _write_json(manifest_path, manifest)
    return manifest


def produce_realtime_watch(
    *,
    rows_path: Path,
    bucket_matrix_path: Path,
    expected_fingerprint: str,
    json_sources: list[Path],
    jsonl_sources: list[Path],
    include_redis: bool,
    redis_scan_limit: int,
    require_pending_for_closed: bool,
    max_rows: int | None,
    cycles: int,
    poll_seconds: float,
) -> dict[str, Any]:
    cycles = max(1, cycles)
    cycle_summaries: list[dict[str, Any]] = []
    totals = {
        "accepted_appended_count": 0,
        "pending_appended_count": 0,
        "rejected_appended_count": 0,
        "duplicate_skipped_count": 0,
    }
    for cycle_index in range(cycles):
        cycle_generated_utc = _utc_iso()
        manifest = produce_realtime(
            rows_path=rows_path,
            bucket_matrix_path=bucket_matrix_path,
            expected_fingerprint=expected_fingerprint,
            json_sources=json_sources,
            jsonl_sources=jsonl_sources,
            include_redis=include_redis,
            redis_scan_limit=redis_scan_limit,
            require_pending_for_closed=require_pending_for_closed,
            max_rows=max_rows,
            generated_utc=cycle_generated_utc,
        )
        cycle_summary = {
            "cycle_index": cycle_index,
            "generated_utc": cycle_generated_utc,
            "status": manifest.get("status"),
            "processed_source_row_count": manifest.get("processed_source_row_count"),
            "accepted_appended_count": manifest.get("accepted_appended_count"),
            "pending_appended_count": manifest.get("pending_appended_count"),
            "rejected_appended_count": manifest.get("rejected_appended_count"),
            "duplicate_skipped_count": manifest.get("duplicate_skipped_count"),
            "rejection_reason_counts": manifest.get("rejection_reason_counts"),
        }
        cycle_summaries.append(cycle_summary)
        for key in totals:
            totals[key] += int(manifest.get(key) or 0)
        if cycle_index < cycles - 1 and poll_seconds > 0.0:
            time.sleep(poll_seconds)

    last_manifest = cycle_summaries[-1] if cycle_summaries else {}
    status = (
        "READY_REALTIME_WATCH_CAPTURED_COUNTABLE_ROWS"
        if totals["accepted_appended_count"] > 0
        else "READY_REALTIME_WATCH_CAPTURED_PENDING_ROWS"
        if totals["pending_appended_count"] > 0
        else "NO_COUNTABLE_REALTIME_ROWS_APPENDED"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_iso(),
        "producer": "realtime_watch",
        "status": status,
        "cycles_requested": cycles,
        "cycles_completed": len(cycle_summaries),
        "poll_seconds": poll_seconds,
        "include_redis": include_redis,
        "redis_scan_limit": redis_scan_limit,
        "selector_policy_fingerprint": expected_fingerprint,
        "totals": totals,
        "last_cycle": last_manifest,
        "cycle_summaries": cycle_summaries,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
        "notes": (
            "Bounded local watcher for genuine realtime paper evidence. It polls read-only sources "
            "and appends only immutable sidecar/hash-chain records through produce_realtime."
        ),
    }


def regenerate_status(*, horizon_years: float) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "v2.backend.app.cli.v2_adaptive_capital_productivity_status",
        "--horizon-years",
        str(horizon_years),
    ]
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    log_path = DEFAULT_OUT_DIR / "out_of_sample_evidence_producer_status_regeneration.log"
    log_path.write_text(completed.stdout + completed.stderr)
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 8),
        "log_path": str(log_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("producer", choices=("holdout", "realtime", "both", "verify"))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--bucket-matrix", type=Path, default=DEFAULT_BUCKET_MATRIX_PATH)
    parser.add_argument("--holdout-source-jsonl", type=Path, default=DEFAULT_HOLDOUT_SOURCE_JSONL)
    parser.add_argument("--holdout-registry", type=Path, default=DEFAULT_HOLDOUT_REGISTRY_PATH)
    parser.add_argument("--holdout-rows", type=Path, default=DEFAULT_HOLDOUT_ROWS_PATH)
    parser.add_argument("--realtime-rows", type=Path, default=DEFAULT_REALTIME_ROWS_PATH)
    parser.add_argument("--paper-status-json", type=Path, default=DEFAULT_PAPER_LIVE_STATUS_PATH)
    parser.add_argument("--paper-ledger-json", type=Path, default=DEFAULT_PAPER_LEDGER_TAIL_PATH)
    parser.add_argument("--paper-events-jsonl", type=Path, default=DEFAULT_PAPER_EVENTS_PATH)
    parser.add_argument("--selector-policy-fingerprint", default=EXPECTED_SELECTOR_POLICY_FINGERPRINT)
    parser.add_argument("--read-redis", action="store_true")
    parser.add_argument("--redis-scan-limit", type=int, default=5000)
    parser.add_argument("--realtime-redis-only", action="store_true")
    parser.add_argument("--realtime-watch-cycles", type=int, default=1)
    parser.add_argument("--realtime-watch-poll-seconds", type=float, default=0.0)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--allow-closed-without-pending", action="store_true")
    parser.add_argument("--verify-integrity", action="store_true")
    parser.add_argument("--regenerate-status", action="store_true")
    parser.add_argument("--horizon-years", type=float, default=5.0)
    args = parser.parse_args(argv)

    generated_utc = _utc_iso()
    summary_path = args.out_dir / "out_of_sample_evidence_producer_summary.json"
    previous_summary = _load_json(summary_path)
    previous_summary = previous_summary if isinstance(previous_summary, dict) else {}
    summaries: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "selector_policy_fingerprint": args.selector_policy_fingerprint,
        "producer": args.producer,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    realtime_json_sources = [] if args.realtime_redis_only else [args.paper_status_json, args.paper_ledger_json]
    realtime_jsonl_sources = [] if args.realtime_redis_only else [args.paper_events_jsonl]
    if args.producer in {"holdout", "both"}:
        summaries["holdout"] = produce_holdout(
            source_jsonl=args.holdout_source_jsonl,
            rows_path=args.holdout_rows,
            registry_path=args.holdout_registry,
            bucket_matrix_path=args.bucket_matrix,
            expected_fingerprint=args.selector_policy_fingerprint,
            max_rows=args.max_rows,
            generated_utc=generated_utc,
        )
    if args.producer in {"realtime", "both"}:
        if args.realtime_watch_cycles > 1:
            watch_summary = produce_realtime_watch(
                rows_path=args.realtime_rows,
                bucket_matrix_path=args.bucket_matrix,
                expected_fingerprint=args.selector_policy_fingerprint,
                json_sources=realtime_json_sources,
                jsonl_sources=realtime_jsonl_sources,
                include_redis=args.read_redis,
                redis_scan_limit=args.redis_scan_limit,
                require_pending_for_closed=not args.allow_closed_without_pending,
                max_rows=args.max_rows,
                cycles=args.realtime_watch_cycles,
                poll_seconds=args.realtime_watch_poll_seconds,
            )
            summaries["realtime_watch"] = watch_summary
            summaries["realtime"] = _load_json(_sidecar_manifest_path(args.realtime_rows)) or {}
        else:
            summaries["realtime"] = produce_realtime(
                rows_path=args.realtime_rows,
                bucket_matrix_path=args.bucket_matrix,
                expected_fingerprint=args.selector_policy_fingerprint,
                json_sources=realtime_json_sources,
                jsonl_sources=realtime_jsonl_sources,
                include_redis=args.read_redis,
                redis_scan_limit=args.redis_scan_limit,
                require_pending_for_closed=not args.allow_closed_without_pending,
                max_rows=args.max_rows,
                generated_utc=generated_utc,
            )
    if args.producer == "verify" or args.verify_integrity:
        summaries.setdefault("holdout", _load_json(_sidecar_manifest_path(args.holdout_rows)) or {})
        summaries.setdefault("realtime", _load_json(_sidecar_manifest_path(args.realtime_rows)) or {})
        if "realtime_watch" in previous_summary:
            summaries.setdefault("realtime_watch", previous_summary["realtime_watch"])
        summaries["integrity"] = verify_evidence_integrity(
            holdout_rows=args.holdout_rows,
            realtime_rows=args.realtime_rows,
            out_dir=args.out_dir,
            generated_utc=generated_utc,
        )
    if args.regenerate_status:
        summaries["status_regeneration"] = regenerate_status(horizon_years=args.horizon_years)
    _write_json(summary_path, summaries)
    print(json.dumps(summaries, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
