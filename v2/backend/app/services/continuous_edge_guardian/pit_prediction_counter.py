"""PIT-valid prediction coverage counter for guardian holdout progress.

This module counts current prediction rows as Phase 3 holdout prediction
coverage only. It deliberately does not create A-grade economic evidence.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v2.backend.app.services.durable_paper_evidence_archive import (
    canonical_json as archive_canonical_json,
)
from v2.backend.app.services.durable_paper_evidence_archive import (
    stable_sha256 as archive_stable_sha256,
)

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")
REQUIRED_ACTIONS: tuple[str, ...] = ("LONG", "SHORT", "NO_TRADE")
MINIMUM_PIT_VALID_PREDICTIONS = 50_000
MINIMUM_SYMBOL_COUNT = 100
REDIS_STATUS_KEY = "v2:guardian:pit_prediction_growth_status"
REDIS_HOT_CACHE_OBSERVATION_KEY = "v2:guardian:pit_prediction_observations"
MAX_HOT_CACHE_OBSERVATIONS_PER_CYCLE = 100_000
GUARDIAN_PIT_ARCHIVE_STREAM_ID = "v2_guardian_pit_prediction_observations_unique_v1"
GUARDIAN_PIT_ARCHIVE_RECORD_SCHEMA_VERSION = (
    "v2_guardian_pit_prediction_observation_append_v1"
)
GUARDIAN_PIT_ARCHIVE_CONSUMER_ID = "guardian_pit_prediction_counter_v1"
GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY = (
    "consumer_cursor:guardian_pit_prediction_counter_v1"
)
GUARDIAN_PIT_ARCHIVE_STATUS_METADATA_KEY = (
    "consumer_status:guardian_pit_prediction_counter_v1"
)
GUARDIAN_PIT_ARCHIVE_CURSOR_SCHEMA_VERSION = (
    "guardian_pit_archive_consumer_cursor_v1"
)
GUARDIAN_PIT_ARCHIVE_STATUS_SCHEMA_VERSION = (
    "guardian_pit_archive_consumer_status_v1"
)
DEFAULT_GUARDIAN_PIT_ARCHIVE_CONSUMER_BATCH_ROWS = 10_000
EMPTY_ARCHIVE_CHAIN_SHA256 = hashlib.sha256(b"").hexdigest()
_ARCHIVE_REQUIRED_FALSE_FLAGS: tuple[str, ...] = (
    "future_labels_used_as_features",
    "counts_as_a_grade_evidence",
    "counts_as_a_plus",
    "counts_as_live_ready",
    "places_real_order",
    "routes_to_live",
    "test_order_submitted",
    "leverage_mutation",
    "margin_mode_mutation",
)
_QUARANTINE_REQUIRED_FALSE_FLAGS: tuple[str, ...] = (
    "counts_as_a_grade_evidence",
    "counts_as_a_plus",
    "counts_as_live_ready",
    "places_real_order",
    "routes_to_live",
)
_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
# Deprecated source-compatibility aliases.  The Redis list is not durable or
# append-only once archive-gated compaction is enabled.
REDIS_APPEND_ONLY_OBSERVATION_KEY = REDIS_HOT_CACHE_OBSERVATION_KEY
MAX_APPEND_ONLY_OBSERVATIONS_PER_CYCLE = MAX_HOT_CACHE_OBSERVATIONS_PER_CYCLE


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def canonical_utc(value: Any) -> str | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def guardian_pit_archive_record_id(payload: Mapping[str, Any]) -> str:
    """Rebuild the publisher's immutable Guardian archive identity."""

    identity = {
        "prediction_id": payload.get("prediction_id"),
        "source_redis_key": payload.get("source_redis_key") or payload.get("redis_key"),
    }
    if not identity["prediction_id"] or not identity["source_redis_key"]:
        raise ValueError("guardian_pit_stable_identity_missing")
    return "guardian_pit:" + archive_stable_sha256(identity)


def _raise_non_finite_json(value: str) -> None:
    raise ValueError(f"non_finite_json_constant:{value}")


def _strict_json_object(raw: str) -> dict[str, Any]:
    payload = json.loads(raw, parse_constant=_raise_non_finite_json)
    if not isinstance(payload, dict):
        raise ValueError("json_payload_not_object")
    return payload


def _timeframe_close_is_final(feature_cutoff: datetime, timeframe: str) -> bool:
    """Accept an exact boundary or the final represented second/millisecond."""

    interval_seconds = _TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return False
    epoch_milliseconds = int(feature_cutoff.timestamp() * 1_000)
    interval_milliseconds = interval_seconds * 1_000
    remainder = epoch_milliseconds % interval_milliseconds
    return remainder == 0 or remainder >= interval_milliseconds - 1_000


def _parse_explicit_utc(value: Any) -> tuple[datetime | None, str | None]:
    if value is None or not str(value).strip():
        return None, "MISSING"
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None, "INVALID"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "NAIVE"
    if parsed.utcoffset() != timedelta(0):
        return None, "NOT_UTC"
    return parsed.astimezone(UTC), None


def _publisher_iso_utc(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    parsed = parsed.astimezone(UTC)
    timespec = "milliseconds" if parsed.microsecond else "seconds"
    return parsed.isoformat(timespec=timespec).replace("+00:00", "Z")


def _validate_quarantined_legacy_payload(
    payload: Mapping[str, Any],
    *,
    record_id: str,
    sort_key: str,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("schema_version") != "guardian_pit_invalid_legacy_redis_record_archive_v1":
        return ["ARCHIVE_QUARANTINE_SCHEMA_INVALID"]
    if payload.get("valid_guardian_observation") is not False:
        reasons.append("ARCHIVE_QUARANTINE_VALID_FLAG_NOT_FALSE")
    if payload.get("source_redis_key") != REDIS_HOT_CACHE_OBSERVATION_KEY:
        reasons.append("ARCHIVE_QUARANTINE_SOURCE_KEY_INVALID")
    for field in _QUARANTINE_REQUIRED_FALSE_FLAGS:
        if payload.get(field) is not False:
            reasons.append(f"ARCHIVE_QUARANTINE_SAFETY_FLAG_NOT_FALSE:{field}")
    list_index = payload.get("legacy_list_index")
    if isinstance(list_index, bool) or not isinstance(list_index, int) or list_index < 0:
        reasons.append("ARCHIVE_QUARANTINE_LIST_INDEX_INVALID")
        list_index = 0
    raw_utf8 = payload.get("raw_redis_value_utf8")
    raw_base64 = payload.get("raw_redis_value_base64")
    raw_bytes: bytes | None = None
    if isinstance(raw_utf8, str) and raw_base64 is None:
        raw_bytes = raw_utf8.encode("utf-8")
    elif raw_utf8 is None and isinstance(raw_base64, str):
        try:
            raw_bytes = base64.b64decode(raw_base64, validate=True)
        except (binascii.Error, ValueError):
            reasons.append("ARCHIVE_QUARANTINE_RAW_BASE64_INVALID")
    else:
        reasons.append("ARCHIVE_QUARANTINE_RAW_REPRESENTATION_INVALID")
    if raw_bytes is not None:
        expected_raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        if payload.get("raw_redis_value_sha256") != expected_raw_hash:
            reasons.append("ARCHIVE_QUARANTINE_RAW_SHA256_MISMATCH")
    wrapper_hash = archive_stable_sha256(payload)
    expected_record_id = f"guardian_pit_invalid:{int(list_index):020d}:{wrapper_hash}"
    if record_id != expected_record_id:
        reasons.append("ARCHIVE_QUARANTINE_RECORD_ID_MISMATCH")
    expected_sort_key = (
        f"0000-00-00T00:00:00.000Z|{int(list_index):020d}|{wrapper_hash}"
    )
    if sort_key != expected_sort_key:
        reasons.append("ARCHIVE_QUARANTINE_SORT_KEY_MISMATCH")
    return sorted(set(reasons))


def _validate_durable_archive_payload(
    payload: Mapping[str, Any],
    *,
    record_id: str,
    allowed_timeframes: Sequence[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if payload.get("schema_version") != GUARDIAN_PIT_ARCHIVE_RECORD_SCHEMA_VERSION:
        reasons.append("ARCHIVE_RECORD_SCHEMA_VERSION_INVALID")
    if payload.get("producer") != "v2_all_timeframe_prediction_signal_price_target_publisher":
        reasons.append("ARCHIVE_RECORD_PRODUCER_INVALID")
    if payload.get("source") != "all_timeframe_prediction_signal_price_target_publisher":
        reasons.append("ARCHIVE_RECORD_SOURCE_INVALID")
    for field in _ARCHIVE_REQUIRED_FALSE_FLAGS:
        if field not in payload:
            reasons.append(f"ARCHIVE_REQUIRED_SAFETY_FLAG_MISSING:{field}")
        elif payload.get(field) is not False:
            reasons.append(f"ARCHIVE_REQUIRED_SAFETY_FLAG_NOT_FALSE:{field}")

    source_redis_key = str(payload.get("source_redis_key") or "").strip()
    if not source_redis_key:
        reasons.append("ARCHIVE_SOURCE_REDIS_KEY_MISSING")
    normalized, row_reasons = validate_prediction_row(
        payload,
        redis_key=source_redis_key or REDIS_HOT_CACHE_OBSERVATION_KEY,
        allowed_timeframes=allowed_timeframes,
    )
    reasons.extend(row_reasons)

    parsed_clocks: dict[str, datetime | None] = {}
    for field in (
        "candle_close_time",
        "feature_cutoff",
        "available_at",
        "decision_time",
        "generated_at",
    ):
        parsed_clock, clock_reason = _parse_explicit_utc(payload.get(field))
        parsed_clocks[field] = parsed_clock
        if clock_reason is not None:
            reasons.append(f"ARCHIVE_{field.upper()}_{clock_reason}")
    candle_close_dt = parsed_clocks["candle_close_time"]
    feature_dt = parsed_clocks["feature_cutoff"]
    available_dt = parsed_clocks["available_at"]
    decision_dt = parsed_clocks["decision_time"]
    generated_dt = parsed_clocks["generated_at"]
    timeframe = str(payload.get("timeframe") or "").strip()
    selected_action = str(payload.get("selected_action") or "").strip().lower()
    if selected_action not in {"long", "short", "hold", "no_trade", "flat", "none"}:
        reasons.append("ARCHIVE_SELECTED_ACTION_SCHEMA_INVALID")
    if payload.get("candle_closed_confirmed") is not True:
        reasons.append("ARCHIVE_CANDLE_CLOSED_CONFIRMED_NOT_TRUE")
    if candle_close_dt is not None and feature_dt is not None and candle_close_dt != feature_dt:
        reasons.append("ARCHIVE_CANDLE_CLOSE_TIME_NOT_FEATURE_CUTOFF")
    if feature_dt is not None and available_dt is not None and feature_dt > available_dt:
        reasons.append("ARCHIVE_FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if feature_dt is not None and decision_dt is not None and feature_dt >= decision_dt:
        reasons.append("ARCHIVE_FEATURE_CUTOFF_NOT_STRICTLY_BEFORE_DECISION_TIME")
    if decision_dt is not None and generated_dt is not None and decision_dt > generated_dt:
        reasons.append("ARCHIVE_DECISION_TIME_AFTER_GENERATED_AT")
    if candle_close_dt is not None and decision_dt is not None and candle_close_dt >= decision_dt:
        reasons.append("ARCHIVE_CANDLE_CLOSE_NOT_STRICTLY_BEFORE_DECISION_TIME")
    if candle_close_dt is not None and not _timeframe_close_is_final(
        candle_close_dt,
        timeframe,
    ):
        reasons.append("ARCHIVE_CANDLE_CLOSE_NOT_FINAL_TIMEFRAME_BOUNDARY")

    if reasons or normalized is None:
        return None, sorted(set(reasons))
    normalized.update(
        {
            "durable_archive_record_id": record_id,
            "durable_archive_record_schema_version": payload.get("schema_version"),
            "durable_archive_content_verified": True,
            "durable_archive_identity_verified": True,
            "pit_clock_chain_verified": True,
            "candle_finality_verified": True,
            "candle_finality_contract": (
                "EXPLICIT_CLOSED_CANDLE_FINAL_BOUNDARY_STRICTLY_BEFORE_DECISION"
            ),
            "counts_as_a_grade_evidence": False,
            "counts_as_a_plus": False,
            "counts_as_live_ready": False,
        }
    )
    return normalized, []


def normalized_action(row: Mapping[str, Any]) -> str:
    raw = (
        row.get("selected_policy_action")
        or row.get("selected_action")
        or row.get("action")
        or row.get("side")
        or row.get("prediction_direction")
    )
    action = str(raw or "").strip().lower()
    if action in {"long", "buy", "bull", "up"}:
        return "LONG"
    if action in {"short", "sell", "bear", "down"}:
        return "SHORT"
    if action in {"hold", "flat", "none", "no_trade", "no-trade", "no trade", "0"}:
        return "NO_TRADE"
    return "UNKNOWN"


def _prediction_identity(row: Mapping[str, Any], *, redis_key: str) -> str:
    prediction_id = str(row.get("prediction_id") or "").strip()
    if prediction_id:
        return prediction_id
    return "pit_" + stable_hash(
        {
            "redis_key": redis_key,
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "feature_cutoff": row.get("feature_cutoff"),
            "selected_action": row.get("selected_action") or row.get("action"),
        }
    )[:24]


def validate_prediction_row(
    row: Mapping[str, Any],
    *,
    redis_key: str,
    allowed_timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
) -> tuple[dict[str, Any] | None, list[str]]:
    symbol = str(row.get("symbol") or "").strip().upper()
    timeframe = str(row.get("timeframe") or "").strip()
    action = normalized_action(row)
    feature_cutoff = canonical_utc(row.get("feature_cutoff") or row.get("ppo_feature_cutoff"))
    decision_time = canonical_utc(
        row.get("decision_time")
        or row.get("ppo_observation_time")
        or row.get("generated_at")
        or row.get("generated_est")
    )
    available_at = canonical_utc(row.get("available_at") or row.get("source_available_at"))
    generated_at = canonical_utc(row.get("generated_at") or row.get("generated_est"))
    prediction_id = _prediction_identity(row, redis_key=redis_key)

    reasons: list[str] = []
    if not symbol:
        reasons.append("MISSING_SYMBOL")
    if not timeframe:
        reasons.append("MISSING_TIMEFRAME")
    elif timeframe not in set(allowed_timeframes):
        reasons.append("UNSUPPORTED_TIMEFRAME")
    if not str(row.get("prediction_id") or "").strip():
        reasons.append("MISSING_PREDICTION_ID")
    if action == "UNKNOWN":
        reasons.append("UNKNOWN_SELECTED_POLICY_ACTION")
    if feature_cutoff is None:
        reasons.append("MISSING_FEATURE_CUTOFF")
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME")

    feature_dt = parse_utc(feature_cutoff)
    decision_dt = parse_utc(decision_time)
    available_dt = parse_utc(available_at)
    if feature_dt is not None and decision_dt is not None and feature_dt > decision_dt:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_dt is not None and decision_dt is not None and available_dt > decision_dt:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    if row.get("stale_prediction") is True:
        reasons.append("STALE_PREDICTION")

    if reasons:
        return None, sorted(set(reasons))

    record = {
        "schema_version": "guardian_pit_prediction_observation_v1",
        "prediction_id": prediction_id,
        "redis_key": redis_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_policy_action": action,
        "decision_time": decision_time,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "generated_at": generated_at,
        "feature_cutoff_before_or_at_decision_time": True,
        "available_at_before_or_at_decision_time": available_at is not None,
        "future_labels_used_as_features": False,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_no_trade_as_win": False,
        "source_hash": stable_hash(
            {
                "prediction_id": prediction_id,
                "redis_key": redis_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "decision_time": decision_time,
                "feature_cutoff": feature_cutoff,
                "selected_policy_action": action,
            }
        ),
    }
    return record, []


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    if not materialized:
        return 0
    with path.open("a", encoding="utf-8") as handle:
        for row in materialized:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return len(materialized)


def _advance_coverage_archive_chain(chain_hash: str, row: Mapping[str, Any]) -> str:
    row_sha256 = hashlib.sha256(archive_canonical_json(dict(row)).encode()).hexdigest()
    return hashlib.sha256(f"{chain_hash}|{row_sha256}".encode()).hexdigest()


def _inspect_coverage_archive(
    path: Path,
    *,
    prefix_rows: int,
    max_extra_rows: int,
) -> tuple[dict[str, Any], list[str]]:
    expected_prefix = max(0, int(prefix_rows))
    allowed_extra = max(0, int(max_extra_rows))
    chain_hash = EMPTY_ARCHIVE_CHAIN_SHA256
    prefix_chain = EMPTY_ARCHIVE_CHAIN_SHA256 if expected_prefix == 0 else None
    extra_row_hashes: list[str] = []
    row_count = 0
    reasons: list[str] = []
    if not path.exists():
        if expected_prefix > 0:
            reasons.append("GUARDIAN_COVERAGE_ARCHIVE_MISSING")
        return {
            "row_count": 0,
            "chain_sha256": chain_hash,
            "prefix_chain_sha256": prefix_chain,
            "extra_row_hashes": extra_row_hashes,
        }, reasons
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = _strict_json_object(line)
                    row_canonical = archive_canonical_json(row)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    reasons.append(
                        "GUARDIAN_COVERAGE_ARCHIVE_JSON_INVALID:"
                        f"line={line_number}:{type(exc).__name__}"
                    )
                    break
                row_hash = hashlib.sha256(row_canonical.encode()).hexdigest()
                chain_hash = hashlib.sha256(f"{chain_hash}|{row_hash}".encode()).hexdigest()
                row_count += 1
                if row_count == expected_prefix:
                    prefix_chain = chain_hash
                elif row_count > expected_prefix:
                    if len(extra_row_hashes) < allowed_extra:
                        extra_row_hashes.append(row_hash)
                    else:
                        reasons.append("GUARDIAN_COVERAGE_ARCHIVE_UNEXPECTED_EXTRA_ROWS")
                        break
    except (OSError, UnicodeError) as exc:
        reasons.append(f"GUARDIAN_COVERAGE_ARCHIVE_READ_FAILED:{type(exc).__name__}")
    if row_count < expected_prefix:
        reasons.append("GUARDIAN_COVERAGE_ARCHIVE_TRUNCATED_BEFORE_CURSOR")
    return {
        "row_count": row_count,
        "chain_sha256": chain_hash,
        "prefix_chain_sha256": prefix_chain,
        "extra_row_hashes": extra_row_hashes,
    }, sorted(set(reasons))


def _archive_metadata_value(
    connection: sqlite3.Connection,
    key: str,
    default: str = "",
) -> str:
    row = connection.execute(
        """
        SELECT metadata_value
        FROM archive_metadata
        WHERE stream_id = ? AND metadata_key = ?
        """,
        (GUARDIAN_PIT_ARCHIVE_STREAM_ID, key),
    ).fetchone()
    return default if row is None else str(row[0])


def _set_archive_metadata(
    connection: sqlite3.Connection,
    key: str,
    value: Mapping[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO archive_metadata(stream_id, metadata_key, metadata_value, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(stream_id, metadata_key) DO UPDATE SET
            metadata_value = excluded.metadata_value,
            updated_at = excluded.updated_at
        """,
        (
            GUARDIAN_PIT_ARCHIVE_STREAM_ID,
            key,
            archive_canonical_json(dict(value)),
            utc_now(),
        ),
    )


def _archive_contract_reasons(connection: sqlite3.Connection) -> list[str]:
    required_columns = {
        "sequence",
        "stream_id",
        "record_id",
        "sort_key",
        "content_sha256",
        "semantic_sha256",
        "semantic_payload_json",
        "payload_json",
        "archived_at",
        "occurrence_count",
    }
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    tables = {str(row[0]) for row in table_rows}
    reasons: list[str] = []
    if "evidence_records" not in tables:
        reasons.append("DURABLE_ARCHIVE_EVIDENCE_RECORDS_TABLE_MISSING")
    if "archive_metadata" not in tables:
        reasons.append("DURABLE_ARCHIVE_METADATA_TABLE_MISSING")
    if "hot_cache_delivery_outbox" not in tables:
        reasons.append("DURABLE_ARCHIVE_HOT_CACHE_OUTBOX_TABLE_MISSING")
    if reasons:
        return reasons
    actual_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(evidence_records)").fetchall()
    }
    missing_columns = sorted(required_columns - actual_columns)
    reasons.extend(f"DURABLE_ARCHIVE_COLUMN_MISSING:{field}" for field in missing_columns)
    return reasons


def _empty_archive_cursor() -> dict[str, Any]:
    return {
        "schema_version": GUARDIAN_PIT_ARCHIVE_CURSOR_SCHEMA_VERSION,
        "consumer_id": GUARDIAN_PIT_ARCHIVE_CONSUMER_ID,
        "stream_id": GUARDIAN_PIT_ARCHIVE_STREAM_ID,
        "last_consumed_sequence": 0,
        "last_consumed_record_id": None,
        "last_consumed_content_sha256": None,
        "consumed_unique_rows": 0,
        "coverage_eligible_unique_rows": 0,
        "coverage_archive_path": None,
        "coverage_archive_row_count": 0,
        "coverage_archive_chain_sha256": EMPTY_ARCHIVE_CHAIN_SHA256,
        "quarantined_unique_rows": 0,
        "quarantine_reason_counts": {},
        "verified_archive_chain_sha256": EMPTY_ARCHIVE_CHAIN_SHA256,
        "selected_policy_action_counts": {
            action: 0 for action in REQUIRED_ACTIONS
        },
        "symbols": [],
        "timeframes": [],
        "last_successful_consumer_run_utc": None,
    }


def _load_archive_cursor(
    connection: sqlite3.Connection,
) -> tuple[dict[str, Any], list[str], bool]:
    raw = _archive_metadata_value(
        connection,
        GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY,
        "",
    )
    if not raw:
        return _empty_archive_cursor(), [], False
    try:
        cursor = _strict_json_object(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            _empty_archive_cursor(),
            [f"ARCHIVE_CONSUMER_CURSOR_INVALID:{type(exc).__name__}"],
            True,
        )
    reasons: list[str] = []
    if cursor.get("schema_version") != GUARDIAN_PIT_ARCHIVE_CURSOR_SCHEMA_VERSION:
        reasons.append("ARCHIVE_CONSUMER_CURSOR_SCHEMA_INVALID")
    if cursor.get("consumer_id") != GUARDIAN_PIT_ARCHIVE_CONSUMER_ID:
        reasons.append("ARCHIVE_CONSUMER_CURSOR_ID_INVALID")
    if cursor.get("stream_id") != GUARDIAN_PIT_ARCHIVE_STREAM_ID:
        reasons.append("ARCHIVE_CONSUMER_CURSOR_STREAM_INVALID")
    for field in (
        "last_consumed_sequence",
        "consumed_unique_rows",
        "coverage_eligible_unique_rows",
        "quarantined_unique_rows",
        "coverage_archive_row_count",
    ):
        value = cursor.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append(f"ARCHIVE_CONSUMER_CURSOR_FIELD_INVALID:{field}")
    chain_hash = str(cursor.get("verified_archive_chain_sha256") or "")
    if len(chain_hash) != 64 or any(
        character not in "0123456789abcdef" for character in chain_hash
    ):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_CHAIN_HASH_INVALID")
    action_counts = cursor.get("selected_policy_action_counts")
    if not isinstance(action_counts, Mapping):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_ACTION_COUNTS_INVALID")
    else:
        for action in REQUIRED_ACTIONS:
            value = action_counts.get(action)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reasons.append(f"ARCHIVE_CONSUMER_CURSOR_ACTION_COUNT_INVALID:{action}")
    for field in ("symbols", "timeframes"):
        value = cursor.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            reasons.append(f"ARCHIVE_CONSUMER_CURSOR_FIELD_INVALID:{field}")
    quarantine_counts = cursor.get("quarantine_reason_counts")
    if not isinstance(quarantine_counts, Mapping):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_QUARANTINE_COUNTS_INVALID")
    else:
        for reason, value in quarantine_counts.items():
            invalid_value = (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            )
            if not isinstance(reason, str) or invalid_value:
                reasons.append("ARCHIVE_CONSUMER_CURSOR_QUARANTINE_COUNT_INVALID")
                break
    coverage_path = cursor.get("coverage_archive_path")
    if coverage_path is not None and (
        not isinstance(coverage_path, str) or not coverage_path.strip()
    ):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_COVERAGE_PATH_INVALID")
    coverage_chain = str(cursor.get("coverage_archive_chain_sha256") or "")
    if len(coverage_chain) != 64 or any(
        character not in "0123456789abcdef" for character in coverage_chain
    ):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_COVERAGE_CHAIN_INVALID")
    if int(cursor.get("coverage_archive_row_count") or 0) != int(
        cursor.get("coverage_eligible_unique_rows") or 0
    ):
        reasons.append("ARCHIVE_CONSUMER_CURSOR_COVERAGE_COUNT_MISMATCH")
    return cursor, sorted(set(reasons)), True


def _archive_snapshot(
    connection: sqlite3.Connection,
) -> tuple[dict[str, Any], list[str]]:
    actual_count, max_sequence = connection.execute(
        """
        SELECT COUNT(*), COALESCE(MAX(sequence), 0)
        FROM evidence_records
        WHERE stream_id = ?
        """,
        (GUARDIAN_PIT_ARCHIVE_STREAM_ID,),
    ).fetchone()
    reasons: list[str] = []
    raw_total = _archive_metadata_value(
        connection,
        "archive_total_unique_rows",
        "",
    )
    try:
        metadata_total = int(raw_total)
    except ValueError:
        metadata_total = -1
        reasons.append("DURABLE_ARCHIVE_TOTAL_UNIQUE_ROWS_METADATA_INVALID")
    if metadata_total != int(actual_count):
        reasons.append("DURABLE_ARCHIVE_TOTAL_UNIQUE_ROWS_MISMATCH")
    source_chain = _archive_metadata_value(
        connection,
        "archive_chain_sha256",
        "",
    )
    if int(actual_count) == 0 and not source_chain:
        source_chain = EMPTY_ARCHIVE_CHAIN_SHA256
    if len(source_chain) != 64 or any(
        character not in "0123456789abcdef" for character in source_chain
    ):
        reasons.append("DURABLE_ARCHIVE_CHAIN_SHA256_INVALID")
    migration_complete = (
        _archive_metadata_value(
            connection,
            "redis_legacy_migration_complete",
            "false",
        )
        == "true"
    )
    try:
        migration_cursor = int(
            _archive_metadata_value(
                connection,
                "redis_legacy_migration_cursor",
                "0",
            )
        )
        migration_observed_length = int(
            _archive_metadata_value(
                connection,
                "redis_legacy_migration_observed_length",
                "0",
            )
        )
    except ValueError:
        migration_cursor = -1
        migration_observed_length = -1
        reasons.append("DURABLE_ARCHIVE_LEGACY_MIGRATION_METADATA_INVALID")
    if migration_cursor < 0 or migration_observed_length < 0:
        reasons.append("DURABLE_ARCHIVE_LEGACY_MIGRATION_BOUNDS_INVALID")
    if migration_complete and migration_cursor < migration_observed_length:
        reasons.append("DURABLE_ARCHIVE_LEGACY_MIGRATION_FALSE_COMPLETE")
    pending_outbox = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM hot_cache_delivery_outbox
            WHERE stream_id = ?
            """,
            (GUARDIAN_PIT_ARCHIVE_STREAM_ID,),
        ).fetchone()[0]
    )
    return {
        "actual_unique_rows": int(actual_count),
        "max_sequence": int(max_sequence),
        "metadata_unique_rows": metadata_total,
        "archive_chain_sha256": source_chain,
        "legacy_migration_complete": migration_complete,
        "legacy_migration_cursor": migration_cursor,
        "legacy_migration_observed_length": migration_observed_length,
        "pending_hot_cache_deliveries": pending_outbox,
    }, sorted(set(reasons))


def _cursor_alignment_reasons(
    connection: sqlite3.Connection,
    cursor: Mapping[str, Any],
    *,
    allow_sink_extra_rows: int = 0,
) -> list[str]:
    last_sequence = int(cursor.get("last_consumed_sequence") or 0)
    consumed_unique_rows = int(cursor.get("consumed_unique_rows") or 0)
    actual_consumed = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM evidence_records
            WHERE stream_id = ? AND sequence <= ?
            """,
            (GUARDIAN_PIT_ARCHIVE_STREAM_ID, last_sequence),
        ).fetchone()[0]
    )
    reasons: list[str] = []
    if actual_consumed != consumed_unique_rows:
        reasons.append("ARCHIVE_CONSUMER_CURSOR_COUNT_MISMATCH")
    coverage_row_count = int(cursor.get("coverage_archive_row_count") or 0)
    coverage_path_raw = cursor.get("coverage_archive_path")
    if coverage_path_raw is None:
        if coverage_row_count != 0:
            reasons.append("ARCHIVE_CONSUMER_CURSOR_COVERAGE_PATH_MISSING")
    else:
        coverage_path = Path(str(coverage_path_raw))
        sink, sink_reasons = _inspect_coverage_archive(
            coverage_path,
            prefix_rows=coverage_row_count,
            max_extra_rows=allow_sink_extra_rows,
        )
        reasons.extend(sink_reasons)
        if sink.get("prefix_chain_sha256") != cursor.get(
            "coverage_archive_chain_sha256"
        ):
            reasons.append("GUARDIAN_COVERAGE_ARCHIVE_CURSOR_CHAIN_MISMATCH")
        extra_count = int(sink.get("row_count") or 0) - coverage_row_count
        if extra_count > allow_sink_extra_rows:
            reasons.append("GUARDIAN_COVERAGE_ARCHIVE_ROWS_AHEAD_OF_CURSOR")
    if last_sequence == 0:
        if consumed_unique_rows != 0:
            reasons.append("ARCHIVE_CONSUMER_ZERO_CURSOR_WITH_NONZERO_COUNT")
        if cursor.get("verified_archive_chain_sha256") != EMPTY_ARCHIVE_CHAIN_SHA256:
            reasons.append("ARCHIVE_CONSUMER_ZERO_CURSOR_CHAIN_MISMATCH")
        return sorted(set(reasons))
    anchor = connection.execute(
        """
        SELECT record_id, content_sha256
        FROM evidence_records
        WHERE stream_id = ? AND sequence = ?
        """,
        (GUARDIAN_PIT_ARCHIVE_STREAM_ID, last_sequence),
    ).fetchone()
    if anchor is None:
        reasons.append("ARCHIVE_CONSUMER_CURSOR_ANCHOR_MISSING")
    else:
        if str(anchor[0]) != str(cursor.get("last_consumed_record_id") or ""):
            reasons.append("ARCHIVE_CONSUMER_CURSOR_RECORD_ID_MISMATCH")
        if str(anchor[1]) != str(cursor.get("last_consumed_content_sha256") or ""):
            reasons.append("ARCHIVE_CONSUMER_CURSOR_CONTENT_HASH_MISMATCH")
    return sorted(set(reasons))


def _consumer_status_payload(
    *,
    archive_path: Path,
    cursor: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    status: str,
    block_reasons: Sequence[str],
    generated_utc: str,
    cursor_preexisted: bool,
    batch_limit: int | None = None,
    rows_read: int = 0,
    rows_ingested: int = 0,
) -> dict[str, Any]:
    source_count = int((snapshot or {}).get("actual_unique_rows") or 0)
    cursor_count = int(cursor.get("consumed_unique_rows") or 0)
    caught_up = (
        status == "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED"
        and not block_reasons
        and cursor_count == source_count
        and cursor.get("verified_archive_chain_sha256")
        == (snapshot or {}).get("archive_chain_sha256")
    )
    migration_complete = (snapshot or {}).get("legacy_migration_complete") is True
    migration_cursor = int((snapshot or {}).get("legacy_migration_cursor") or 0)
    migration_observed_length = int(
        (snapshot or {}).get("legacy_migration_observed_length") or 0
    )
    pending_hot_cache_deliveries = int(
        (snapshot or {}).get("pending_hot_cache_deliveries") or 0
    )
    trim_safe = (
        caught_up
        and migration_complete
        and migration_cursor >= migration_observed_length
        and pending_hot_cache_deliveries == 0
    )
    return {
        "schema_version": GUARDIAN_PIT_ARCHIVE_STATUS_SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "status": status,
        "block_reasons": sorted(set(str(reason) for reason in block_reasons if reason)),
        "consumer_id": GUARDIAN_PIT_ARCHIVE_CONSUMER_ID,
        "durable_archive_path": str(archive_path),
        "durable_archive_stream_id": GUARDIAN_PIT_ARCHIVE_STREAM_ID,
        "consumer_cursor_metadata_key": GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY,
        "consumer_status_metadata_key": GUARDIAN_PIT_ARCHIVE_STATUS_METADATA_KEY,
        "consumer_cursor_preexisted": cursor_preexisted,
        "consumer_cursor_sequence": int(cursor.get("last_consumed_sequence") or 0),
        "consumer_cursor_record_id": cursor.get("last_consumed_record_id"),
        "consumer_consumed_unique_rows": cursor_count,
        "source_archive_actual_unique_rows": source_count,
        "source_archive_max_sequence": int((snapshot or {}).get("max_sequence") or 0),
        "source_archive_metadata_unique_rows": (snapshot or {}).get("metadata_unique_rows"),
        "source_archive_chain_sha256": (snapshot or {}).get("archive_chain_sha256"),
        "consumer_verified_archive_chain_sha256": cursor.get(
            "verified_archive_chain_sha256"
        ),
        "archive_unconsumed_unique_rows": max(0, source_count - cursor_count),
        "archive_consumption_complete_verified": caught_up,
        "archive_consumer_caught_up_verified": caught_up,
        "publisher_legacy_migration_complete": migration_complete,
        "publisher_legacy_migration_cursor": migration_cursor,
        "publisher_legacy_migration_observed_length": migration_observed_length,
        "publisher_pending_hot_cache_deliveries": pending_hot_cache_deliveries,
        "redis_hot_cache_trim_safe": trim_safe,
        "redis_hot_cache_trim_gate": (
            "SAFE_DURABLE_ARCHIVE_FULLY_CONSUMED_AND_HASH_VERIFIED"
            if trim_safe
            else (
                "BLOCKED_PUBLISHER_LEGACY_MIGRATION_OR_OUTBOX_NOT_COMPLETE"
                if caught_up
                else "BLOCKED_DURABLE_ARCHIVE_NOT_FULLY_CONSUMED_AND_VERIFIED"
            )
        ),
        "bounded_batch_limit": batch_limit,
        "archive_rows_read_this_cycle": rows_read,
        "archive_rows_ingested_this_cycle": rows_ingested,
        "coverage_eligible_unique_rows": int(
            cursor.get("coverage_eligible_unique_rows") or 0
        ),
        "coverage_archive_path": cursor.get("coverage_archive_path"),
        "coverage_archive_row_count": int(
            cursor.get("coverage_archive_row_count") or 0
        ),
        "coverage_archive_chain_sha256": cursor.get(
            "coverage_archive_chain_sha256"
        ),
        "coverage_archive_durable_before_cursor_commit": True,
        "coverage_archive_revalidated_by_trim_status_probe": True,
        "quarantined_unique_rows": int(cursor.get("quarantined_unique_rows") or 0),
        "quarantine_reason_counts": dict(cursor.get("quarantine_reason_counts") or {}),
        "selected_policy_action_counts": dict(
            cursor.get("selected_policy_action_counts") or {}
        ),
        "symbol_count": len(cursor.get("symbols") or []),
        "timeframe_count": len(cursor.get("timeframes") or []),
        "symbols": list(cursor.get("symbols") or []),
        "timeframes": list(cursor.get("timeframes") or []),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    }


def _persist_consumer_status(
    connection: sqlite3.Connection,
    status: Mapping[str, Any],
) -> None:
    _set_archive_metadata(
        connection,
        GUARDIAN_PIT_ARCHIVE_STATUS_METADATA_KEY,
        status,
    )


def guardian_pit_archive_consumption_status(
    archive_path: Path,
    *,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Return the live cursor/archive relation used to gate Redis trimming."""

    path = Path(archive_path)
    now = generated_utc or utc_now()
    empty_cursor = _empty_archive_cursor()
    if not path.is_file():
        return _consumer_status_payload(
            archive_path=path,
            cursor=empty_cursor,
            snapshot=None,
            status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
            block_reasons=("DURABLE_GUARDIAN_PIT_ARCHIVE_MISSING",),
            generated_utc=now,
            cursor_preexisted=False,
        )
    try:
        with sqlite3.connect(str(path), timeout=60.0) as connection:
            reasons = _archive_contract_reasons(connection)
            if reasons:
                return _consumer_status_payload(
                    archive_path=path,
                    cursor=empty_cursor,
                    snapshot=None,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=reasons,
                    generated_utc=now,
                    cursor_preexisted=False,
                )
            cursor, cursor_reasons, cursor_preexisted = _load_archive_cursor(connection)
            snapshot, snapshot_reasons = _archive_snapshot(connection)
            alignment_reasons = _cursor_alignment_reasons(connection, cursor)
            reasons = [*cursor_reasons, *snapshot_reasons, *alignment_reasons]
            persisted_raw = _archive_metadata_value(
                connection,
                GUARDIAN_PIT_ARCHIVE_STATUS_METADATA_KEY,
                "",
            )
            if not persisted_raw:
                reasons.append("ARCHIVE_CONSUMER_PERSISTED_STATUS_MISSING")
            else:
                try:
                    persisted = _strict_json_object(persisted_raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    reasons.append("ARCHIVE_CONSUMER_PERSISTED_STATUS_INVALID")
                else:
                    if (
                        persisted.get("schema_version")
                        != GUARDIAN_PIT_ARCHIVE_STATUS_SCHEMA_VERSION
                    ):
                        reasons.append("ARCHIVE_CONSUMER_PERSISTED_STATUS_SCHEMA_INVALID")
                    if persisted.get("consumer_id") != GUARDIAN_PIT_ARCHIVE_CONSUMER_ID:
                        reasons.append("ARCHIVE_CONSUMER_PERSISTED_STATUS_ID_INVALID")
                    persisted_status = str(persisted.get("status") or "")
                    if persisted_status.startswith("BLOCKED_"):
                        reasons.append("ARCHIVE_CONSUMER_LAST_RUN_BLOCKED")
                    elif persisted_status not in {
                        "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_IN_PROGRESS",
                        "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED",
                    }:
                        reasons.append("ARCHIVE_CONSUMER_PERSISTED_STATUS_STATE_INVALID")
            complete = (
                not reasons
                and cursor_preexisted
                and cursor.get("last_successful_consumer_run_utc")
                and int(cursor.get("consumed_unique_rows") or 0)
                == int(snapshot["actual_unique_rows"])
                and cursor.get("verified_archive_chain_sha256")
                == snapshot.get("archive_chain_sha256")
            )
            status_name = (
                "BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION"
                if reasons
                else (
                    "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED"
                    if complete
                    else "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_IN_PROGRESS"
                )
            )
            return _consumer_status_payload(
                archive_path=path,
                cursor=cursor,
                snapshot=snapshot,
                status=status_name,
                block_reasons=reasons,
                generated_utc=now,
                cursor_preexisted=cursor_preexisted,
            )
    except (OSError, sqlite3.DatabaseError) as exc:
        return _consumer_status_payload(
            archive_path=path,
            cursor=empty_cursor,
            snapshot=None,
            status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
            block_reasons=(f"DURABLE_ARCHIVE_READ_FAILED:{type(exc).__name__}",),
            generated_utc=now,
            cursor_preexisted=False,
        )


def consume_durable_guardian_pit_archive(
    *,
    source_archive_path: Path,
    guardian_coverage_archive_path: Path,
    allowed_timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    batch_rows: int = DEFAULT_GUARDIAN_PIT_ARCHIVE_CONSUMER_BATCH_ROWS,
    generated_utc: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Consume one bounded, fully verified SQLite batch into Guardian coverage."""

    source_path = Path(source_archive_path)
    destination_path = Path(guardian_coverage_archive_path)
    now = generated_utc or utc_now()
    bounded_limit = max(1, int(batch_rows))
    if not source_path.is_file():
        status = _consumer_status_payload(
            archive_path=source_path,
            cursor=_empty_archive_cursor(),
            snapshot=None,
            status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
            block_reasons=("DURABLE_GUARDIAN_PIT_ARCHIVE_MISSING",),
            generated_utc=now,
            cursor_preexisted=False,
            batch_limit=bounded_limit,
        )
        return [], status

    cursor = _empty_archive_cursor()
    cursor_preexisted = False
    snapshot: dict[str, Any] | None = None
    try:
        with sqlite3.connect(str(source_path), timeout=60.0) as connection:
            reasons = _archive_contract_reasons(connection)
            if not reasons:
                cursor, cursor_reasons, cursor_preexisted = _load_archive_cursor(connection)
                snapshot, snapshot_reasons = _archive_snapshot(connection)
                reasons.extend(cursor_reasons)
                reasons.extend(snapshot_reasons)
                reasons.extend(
                    _cursor_alignment_reasons(
                        connection,
                        cursor,
                        allow_sink_extra_rows=bounded_limit,
                    )
                )
            if reasons:
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=reasons,
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                )
                if "DURABLE_ARCHIVE_METADATA_TABLE_MISSING" not in reasons:
                    try:
                        _persist_consumer_status(connection, status)
                        connection.commit()
                    except sqlite3.DatabaseError:
                        pass
                return [], status

            last_sequence = int(cursor.get("last_consumed_sequence") or 0)
            source_rows = connection.execute(
                """
                SELECT sequence, record_id, sort_key, content_sha256,
                       semantic_sha256, semantic_payload_json, payload_json
                FROM evidence_records
                WHERE stream_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (GUARDIAN_PIT_ARCHIVE_STREAM_ID, last_sequence, bounded_limit),
            ).fetchall()

            verified_rows: list[dict[str, Any]] = []
            verified_source_rows: list[tuple[int, str, str]] = []
            quarantined_this_cycle = 0
            quarantine_reasons_this_cycle: Counter[str] = Counter()
            next_chain = str(cursor.get("verified_archive_chain_sha256"))
            invalid_reasons: list[str] = []
            first_invalid_sequence: int | None = None
            previous_sequence = last_sequence
            for source_row in source_rows:
                sequence = int(source_row[0])
                record_id = str(source_row[1])
                sort_key = str(source_row[2])
                content_sha256 = str(source_row[3])
                semantic_sha256 = str(source_row[4])
                semantic_payload_json = (
                    None if source_row[5] is None else str(source_row[5])
                )
                payload_json = str(source_row[6])
                row_reasons: list[str] = []
                if sequence <= previous_sequence:
                    row_reasons.append("ARCHIVE_SEQUENCE_NOT_STRICTLY_INCREASING")
                previous_sequence = sequence
                try:
                    payload = _strict_json_object(payload_json)
                    canonical_payload = archive_canonical_json(payload)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    payload = {}
                    canonical_payload = ""
                    row_reasons.append(f"ARCHIVE_PAYLOAD_JSON_INVALID:{type(exc).__name__}")
                calculated_content_sha256 = hashlib.sha256(
                    canonical_payload.encode("utf-8")
                ).hexdigest()
                if calculated_content_sha256 != content_sha256:
                    row_reasons.append("ARCHIVE_CONTENT_SHA256_MISMATCH")
                try:
                    semantic_payload = (
                        _strict_json_object(semantic_payload_json)
                        if semantic_payload_json is not None
                        else None
                    )
                    canonical_semantic_payload = (
                        archive_canonical_json(semantic_payload)
                        if semantic_payload is not None
                        else ""
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    canonical_semantic_payload = ""
                    row_reasons.append(
                        f"ARCHIVE_SEMANTIC_PAYLOAD_JSON_INVALID:{type(exc).__name__}"
                    )
                calculated_semantic_sha256 = hashlib.sha256(
                    canonical_semantic_payload.encode()
                ).hexdigest()
                if calculated_semantic_sha256 != semantic_sha256:
                    row_reasons.append("ARCHIVE_SEMANTIC_SHA256_MISMATCH")
                normalized: dict[str, Any] | None = None
                semantic_quarantine_reasons: list[str] = []
                is_quarantine_wrapper = (
                    payload.get("schema_version")
                    == "guardian_pit_invalid_legacy_redis_record_archive_v1"
                )
                if is_quarantine_wrapper:
                    row_reasons.extend(
                        _validate_quarantined_legacy_payload(
                            payload,
                            record_id=record_id,
                            sort_key=sort_key,
                        )
                    )
                    if not row_reasons:
                        semantic_quarantine_reasons.append(
                            "LEGACY_INVALID_REDIS_RECORD_QUARANTINED"
                        )
                else:
                    try:
                        expected_record_id = guardian_pit_archive_record_id(payload)
                    except ValueError:
                        expected_record_id = ""
                        row_reasons.append("ARCHIVE_STABLE_IDENTITY_MISSING")
                    if record_id != expected_record_id:
                        row_reasons.append("ARCHIVE_RECORD_IDENTITY_HASH_MISMATCH")
                    sort_time = _publisher_iso_utc(
                        payload.get("decision_time")
                        or payload.get("generated_at")
                        or payload.get("feature_cutoff")
                    )
                    expected_sort_key = (
                        None if sort_time is None else f"{sort_time}|{record_id}"
                    )
                    if expected_sort_key is None or sort_key != expected_sort_key:
                        row_reasons.append("ARCHIVE_SORT_KEY_MISMATCH")
                    normalized, semantic_quarantine_reasons = (
                        _validate_durable_archive_payload(
                            payload,
                            record_id=record_id,
                            allowed_timeframes=allowed_timeframes,
                        )
                    )
                if row_reasons:
                    first_invalid_sequence = sequence
                    invalid_reasons.extend(
                        f"sequence={sequence}:{reason}" for reason in row_reasons
                    )
                    break
                next_chain = hashlib.sha256(
                    f"{next_chain}|{record_id}|{content_sha256}".encode()
                ).hexdigest()
                verified_source_rows.append((sequence, record_id, content_sha256))
                if normalized is None:
                    quarantined_this_cycle += 1
                    quarantine_reasons_this_cycle.update(
                        semantic_quarantine_reasons
                        or ("ARCHIVE_SEMANTICALLY_DIRTY_ROW_QUARANTINED",)
                    )
                    continue
                normalized["durable_archive_sequence"] = sequence
                normalized["durable_archive_content_sha256"] = content_sha256
                normalized["durable_archive_semantic_sha256"] = semantic_sha256
                normalized["durable_archive_chain_sha256_through_record"] = next_chain
                verified_rows.append(normalized)

            if invalid_reasons:
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=invalid_reasons,
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                    rows_read=len(source_rows),
                )
                status["first_invalid_archive_sequence"] = first_invalid_sequence
                _persist_consumer_status(connection, status)
                connection.commit()
                return [], status

            projected_count = int(cursor.get("consumed_unique_rows") or 0) + len(
                verified_source_rows
            )
            if projected_count == int((snapshot or {}).get("actual_unique_rows") or 0):
                if next_chain != (snapshot or {}).get("archive_chain_sha256"):
                    status = _consumer_status_payload(
                        archive_path=source_path,
                        cursor=cursor,
                        snapshot=snapshot,
                        status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                        block_reasons=("DURABLE_ARCHIVE_CHAIN_SHA256_MISMATCH",),
                        generated_utc=now,
                        cursor_preexisted=cursor_preexisted,
                        batch_limit=bounded_limit,
                        rows_read=len(source_rows),
                    )
                    _persist_consumer_status(connection, status)
                    connection.commit()
                    return [], status

            requested_destination = destination_path.resolve()
            cursor_destination_raw = cursor.get("coverage_archive_path")
            if cursor_destination_raw is not None and Path(
                str(cursor_destination_raw)
            ).resolve() != requested_destination:
                destination_errors = ["GUARDIAN_COVERAGE_ARCHIVE_PATH_CHANGED"]
                sink_before: dict[str, Any] = {}
            else:
                sink_before, destination_errors = _inspect_coverage_archive(
                    requested_destination,
                    prefix_rows=int(cursor.get("coverage_archive_row_count") or 0),
                    max_extra_rows=len(verified_rows),
                )
            expected_row_hashes = [
                hashlib.sha256(archive_canonical_json(row).encode()).hexdigest()
                for row in verified_rows
            ]
            sink_extra_hashes = list(sink_before.get("extra_row_hashes") or [])
            if sink_extra_hashes != expected_row_hashes[: len(sink_extra_hashes)]:
                destination_errors.append(
                    "GUARDIAN_COVERAGE_ARCHIVE_AHEAD_ROWS_DO_NOT_MATCH_REPLAY_BATCH"
                )
            if destination_errors:
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=destination_errors,
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                    rows_read=len(source_rows),
                )
                _persist_consumer_status(connection, status)
                connection.commit()
                return [], status
            rows_to_append = verified_rows[len(sink_extra_hashes) :]
            appended = append_jsonl(destination_path, rows_to_append)
            if appended != len(rows_to_append):
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=("GUARDIAN_COVERAGE_ARCHIVE_APPEND_COUNT_MISMATCH",),
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                    rows_read=len(source_rows),
                )
                _persist_consumer_status(connection, status)
                connection.commit()
                return [], status
            expected_coverage_chain = str(
                cursor.get("coverage_archive_chain_sha256")
                or EMPTY_ARCHIVE_CHAIN_SHA256
            )
            for row in verified_rows:
                expected_coverage_chain = _advance_coverage_archive_chain(
                    expected_coverage_chain,
                    row,
                )
            expected_coverage_rows = int(
                cursor.get("coverage_archive_row_count") or 0
            ) + len(verified_rows)
            sink_after, readback_errors = _inspect_coverage_archive(
                requested_destination,
                prefix_rows=expected_coverage_rows,
                max_extra_rows=0,
            )
            if (
                readback_errors
                or int(sink_after.get("row_count") or 0) != expected_coverage_rows
                or sink_after.get("chain_sha256") != expected_coverage_chain
            ):
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=(
                        *readback_errors,
                        "GUARDIAN_COVERAGE_ARCHIVE_DURABLE_READBACK_MISMATCH",
                    ),
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                    rows_read=len(source_rows),
                )
                _persist_consumer_status(connection, status)
                connection.commit()
                return [], status

            next_cursor = dict(cursor)
            if verified_source_rows:
                last_verified = verified_source_rows[-1]
                next_cursor["last_consumed_sequence"] = last_verified[0]
                next_cursor["last_consumed_record_id"] = last_verified[1]
                next_cursor["last_consumed_content_sha256"] = last_verified[2]
                next_cursor["consumed_unique_rows"] = projected_count
                next_cursor["coverage_eligible_unique_rows"] = int(
                    cursor.get("coverage_eligible_unique_rows") or 0
                ) + len(verified_rows)
                next_cursor["coverage_archive_path"] = str(requested_destination)
                next_cursor["coverage_archive_row_count"] = expected_coverage_rows
                next_cursor["coverage_archive_chain_sha256"] = expected_coverage_chain
                next_cursor["quarantined_unique_rows"] = int(
                    cursor.get("quarantined_unique_rows") or 0
                ) + quarantined_this_cycle
                quarantine_counts = Counter(
                    {
                        str(reason): int(count)
                        for reason, count in (
                            cursor.get("quarantine_reason_counts") or {}
                        ).items()
                    }
                )
                quarantine_counts.update(quarantine_reasons_this_cycle)
                next_cursor["quarantine_reason_counts"] = dict(
                    sorted(quarantine_counts.items())
                )
                next_cursor["verified_archive_chain_sha256"] = next_chain
                action_counts = Counter(
                    {
                        action: int(
                            (cursor.get("selected_policy_action_counts") or {}).get(
                                action,
                                0,
                            )
                        )
                        for action in REQUIRED_ACTIONS
                    }
                )
                action_counts.update(
                    str(row.get("selected_policy_action")) for row in verified_rows
                )
                next_cursor["selected_policy_action_counts"] = {
                    action: int(action_counts.get(action, 0))
                    for action in REQUIRED_ACTIONS
                }
                next_cursor["symbols"] = sorted(
                    {
                        *(str(item) for item in cursor.get("symbols") or []),
                        *(str(row.get("symbol")) for row in verified_rows),
                    }
                )
                next_cursor["timeframes"] = sorted(
                    {
                        *(str(item) for item in cursor.get("timeframes") or []),
                        *(str(row.get("timeframe")) for row in verified_rows),
                    }
                )
            next_cursor["schema_version"] = GUARDIAN_PIT_ARCHIVE_CURSOR_SCHEMA_VERSION
            next_cursor["consumer_id"] = GUARDIAN_PIT_ARCHIVE_CONSUMER_ID
            next_cursor["stream_id"] = GUARDIAN_PIT_ARCHIVE_STREAM_ID
            next_cursor["last_successful_consumer_run_utc"] = now

            latest_snapshot, latest_snapshot_reasons = _archive_snapshot(connection)
            if latest_snapshot_reasons:
                status = _consumer_status_payload(
                    archive_path=source_path,
                    cursor=cursor,
                    snapshot=latest_snapshot,
                    status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
                    block_reasons=latest_snapshot_reasons,
                    generated_utc=now,
                    cursor_preexisted=cursor_preexisted,
                    batch_limit=bounded_limit,
                    rows_read=len(source_rows),
                    rows_ingested=len(verified_source_rows),
                )
                _persist_consumer_status(connection, status)
                connection.commit()
                return [], status
            complete = (
                int(next_cursor.get("consumed_unique_rows") or 0)
                == int(latest_snapshot["actual_unique_rows"])
                and next_cursor.get("verified_archive_chain_sha256")
                == latest_snapshot.get("archive_chain_sha256")
            )
            status_name = (
                "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED"
                if complete
                else "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_IN_PROGRESS"
            )
            status = _consumer_status_payload(
                archive_path=source_path,
                cursor=next_cursor,
                snapshot=latest_snapshot,
                status=status_name,
                block_reasons=(),
                generated_utc=now,
                cursor_preexisted=cursor_preexisted,
                batch_limit=bounded_limit,
                rows_read=len(source_rows),
                rows_ingested=len(verified_source_rows),
            )
            status["guardian_coverage_archive_rows_appended_this_cycle"] = appended
            status["coverage_eligible_rows_this_cycle"] = len(verified_rows)
            status["quarantined_rows_this_cycle"] = quarantined_this_cycle
            status["quarantine_reason_counts_this_cycle"] = dict(
                sorted(quarantine_reasons_this_cycle.items())
            )
            _set_archive_metadata(
                connection,
                GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY,
                next_cursor,
            )
            _persist_consumer_status(connection, status)
            connection.commit()
            return verified_rows, status
    except (OSError, sqlite3.DatabaseError) as exc:
        status = _consumer_status_payload(
            archive_path=source_path,
            cursor=cursor,
            snapshot=snapshot,
            status="BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION",
            block_reasons=(f"DURABLE_ARCHIVE_CONSUMPTION_FAILED:{type(exc).__name__}",),
            generated_utc=now,
            cursor_preexisted=cursor_preexisted,
            batch_limit=bounded_limit,
        )
        return [], status


def collect_prediction_rows(
    client: Any,
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for symbol in sorted({str(item).strip().upper() for item in symbols if str(item).strip()}):
        for timeframe in timeframes:
            redis_key = f"v2:prediction:{symbol}:{timeframe}"
            try:
                raw = client.get(redis_key)
            except Exception as exc:  # noqa: BLE001
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": [f"REDIS_GET_FAILED:{type(exc).__name__}"],
                    }
                )
                continue
            if raw is None:
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": ["MISSING_PREDICTION_KEY"],
                    }
                )
                continue
            try:
                row = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": [f"PREDICTION_JSON_INVALID:{type(exc).__name__}"],
                    }
                )
                continue
            if not isinstance(row, dict):
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": ["PREDICTION_PAYLOAD_NOT_OBJECT"],
                    }
                )
                continue
            record, reasons = validate_prediction_row(row, redis_key=redis_key, allowed_timeframes=timeframes)
            if record is None:
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol or str(row.get("symbol") or "").upper(),
                        "timeframe": timeframe or str(row.get("timeframe") or ""),
                        "prediction_id": row.get("prediction_id"),
                        "decision_time": row.get("decision_time"),
                        "feature_cutoff": row.get("feature_cutoff"),
                        "selected_policy_action": normalized_action(row),
                        "reasons": reasons,
                    }
                )
                continue
            valid.append(record)
    return valid, rejected


def collect_hot_cache_prediction_rows(
    client: Any,
    *,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    redis_key: str = REDIS_HOT_CACHE_OBSERVATION_KEY,
    max_rows: int = MAX_HOT_CACHE_OBSERVATIONS_PER_CYCLE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if not hasattr(client, "lrange"):
        return valid, rejected
    start = -max(1, int(max_rows))
    try:
        raw_rows = client.lrange(redis_key, start, -1)
    except Exception as exc:  # noqa: BLE001
        return [], [{"redis_key": redis_key, "reasons": [f"REDIS_LRANGE_FAILED:{type(exc).__name__}"]}]
    for index, raw in enumerate(raw_rows or []):
        try:
            row = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            rejected.append(
                {
                    "redis_key": redis_key,
                    "list_index": index,
                    "reasons": [f"HOT_CACHE_PREDICTION_JSON_INVALID:{type(exc).__name__}"],
                }
            )
            continue
        if not isinstance(row, dict):
            rejected.append(
                {
                    "redis_key": redis_key,
                    "list_index": index,
                    "reasons": ["HOT_CACHE_PREDICTION_PAYLOAD_NOT_OBJECT"],
                }
            )
            continue
        source_key = str(row.get("source_redis_key") or row.get("redis_key") or redis_key)
        record, reasons = validate_prediction_row(row, redis_key=source_key, allowed_timeframes=timeframes)
        if record is None:
            rejected.append(
                {
                    "redis_key": redis_key,
                    "source_redis_key": source_key,
                    "list_index": index,
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "prediction_id": row.get("prediction_id"),
                    "decision_time": row.get("decision_time"),
                    "feature_cutoff": row.get("feature_cutoff"),
                    "selected_policy_action": normalized_action(row),
                    "reasons": reasons,
                }
            )
            continue
        record["redis_hot_cache_key"] = redis_key
        valid.append(record)
    return valid, rejected


def collect_append_only_prediction_rows(
    client: Any,
    *,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    redis_key: str = REDIS_HOT_CACHE_OBSERVATION_KEY,
    max_rows: int = MAX_HOT_CACHE_OBSERVATIONS_PER_CYCLE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deprecated compatibility wrapper; Redis is a bounded hot cache."""

    return collect_hot_cache_prediction_rows(
        client,
        timeframes=timeframes,
        redis_key=redis_key,
        max_rows=max_rows,
    )


def dedupe_records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("source_hash") or row.get("prediction_id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduped.append(dict(row))
    return deduped


def dedupe_new_records(existing_rows: Sequence[Mapping[str, Any]], current_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(row.get("source_hash") or row.get("prediction_id") or "") for row in existing_rows}
    new_rows: list[dict[str, Any]] = []
    for row in current_rows:
        identity = str(row.get("source_hash") or row.get("prediction_id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        new_rows.append(dict(row))
    return new_rows


def coverage_status(
    *,
    archive_rows: Sequence[Mapping[str, Any]],
    current_valid_rows: Sequence[Mapping[str, Any]],
    rejected_rows: Sequence[Mapping[str, Any]],
    new_rows_appended: int,
    generated_utc: str,
) -> dict[str, Any]:
    action_counts = Counter(
        str(row.get("selected_policy_action") or "UNKNOWN")
        for row in archive_rows
    )
    symbols = sorted(
        {str(row.get("symbol") or "") for row in archive_rows if row.get("symbol")}
    )
    timeframes = sorted(
        {
            str(row.get("timeframe") or "")
            for row in archive_rows
            if row.get("timeframe")
        }
    )
    return _coverage_status_from_aggregates(
        valid_count=len(archive_rows),
        action_counts=action_counts,
        symbols=symbols,
        timeframes=timeframes,
        current_valid_rows=current_valid_rows,
        rejected_rows=rejected_rows,
        new_rows_appended=new_rows_appended,
        generated_utc=generated_utc,
    )


def coverage_status_from_archive_consumer(
    *,
    archive_consumer_status: Mapping[str, Any],
    current_valid_rows: Sequence[Mapping[str, Any]],
    rejected_rows: Sequence[Mapping[str, Any]],
    new_rows_appended: int,
    generated_utc: str,
) -> dict[str, Any]:
    """Build exact coverage without materializing the append-only JSONL."""

    return _coverage_status_from_aggregates(
        valid_count=int(
            archive_consumer_status.get("coverage_eligible_unique_rows") or 0
        ),
        action_counts=Counter(
            {
                str(action): int(count)
                for action, count in (
                    archive_consumer_status.get("selected_policy_action_counts") or {}
                ).items()
            }
        ),
        symbols=sorted(
            str(symbol) for symbol in archive_consumer_status.get("symbols") or []
        ),
        timeframes=sorted(
            str(timeframe)
            for timeframe in archive_consumer_status.get("timeframes") or []
        ),
        current_valid_rows=current_valid_rows,
        rejected_rows=rejected_rows,
        new_rows_appended=new_rows_appended,
        generated_utc=generated_utc,
    )


def _coverage_status_from_aggregates(
    *,
    valid_count: int,
    action_counts: Counter[str],
    symbols: Sequence[str],
    timeframes: Sequence[str],
    current_valid_rows: Sequence[Mapping[str, Any]],
    rejected_rows: Sequence[Mapping[str, Any]],
    new_rows_appended: int,
    generated_utc: str,
) -> dict[str, Any]:
    rejection_counts: Counter[str] = Counter()
    for row in rejected_rows:
        rejection_counts.update(str(reason) for reason in row.get("reasons") or [])
    missing_timeframes = [
        timeframe for timeframe in DEFAULT_TIMEFRAMES if timeframe not in set(timeframes)
    ]
    missing_actions = [action for action in REQUIRED_ACTIONS if action_counts.get(action, 0) <= 0]
    return {
        "schema_version": "guardian_pit_prediction_growth_status_v1",
        "generated_utc": generated_utc,
        "status": (
            "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE"
            if valid_count > 0
            else "BLOCKED_NO_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"
        ),
        "policy": (
            "Counts point-in-time-valid current prediction observations as guardian holdout "
            "prediction coverage only. This never counts as A-grade economic evidence and "
            "never counts NO_TRADE as an economic win."
        ),
        "point_in_time_valid_prediction_count": valid_count,
        "current_cycle_valid_prediction_count": len(current_valid_rows),
        "current_cycle_rejected_prediction_count": len(rejected_rows),
        "new_rows_appended": new_rows_appended,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "selected_policy_action_counts": {
            action: int(action_counts.get(action, 0)) for action in REQUIRED_ACTIONS
        },
        "unknown_action_count": int(action_counts.get("UNKNOWN", 0)),
        "symbols": symbols,
        "timeframes": timeframes,
        "missing_timeframes": missing_timeframes,
        "missing_selected_policy_actions": missing_actions,
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "sample_valid_predictions": [dict(row) for row in list(current_valid_rows)[:20]],
        "sample_rejected_predictions": [dict(row) for row in list(rejected_rows)[:20]],
        "required_point_in_time_valid_prediction_count": MINIMUM_PIT_VALID_PREDICTIONS,
        "required_symbol_count": MINIMUM_SYMBOL_COUNT,
        "required_timeframes": list(DEFAULT_TIMEFRAMES),
        "required_selected_policy_actions": list(REQUIRED_ACTIONS),
        "remaining_point_in_time_valid_predictions": max(0, MINIMUM_PIT_VALID_PREDICTIONS - valid_count),
        "remaining_symbol_count": max(0, MINIMUM_SYMBOL_COUNT - len(symbols)),
        "cycles_to_minimum_at_current_append_rate": (
            None
            if new_rows_appended <= 0
            else int((max(0, MINIMUM_PIT_VALID_PREDICTIONS - valid_count) + new_rows_appended - 1) // new_rows_appended)
        ),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_no_trade_as_win": False,
        "no_trade_counted_as_economic_win": False,
    }


def update_holdout_manifest(manifest_path: Path, status: Mapping[str, Any], *, generated_utc: str) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except json.JSONDecodeError:
            existing = {}
    updated = dict(existing)
    updated.setdefault("schema_version", "out_of_sample_holdout_reverify_manifest_v1")
    updated.setdefault("producer", "holdout")
    updated.setdefault("status", "NO_COUNTABLE_HOLDOUT_ROWS_APPENDED")
    updated["generated_utc"] = generated_utc
    updated["holdout_prediction_coverage_status"] = dict(status)
    updated["point_in_time_valid_prediction_count"] = status.get("point_in_time_valid_prediction_count")
    updated["counts_as_a_grade_evidence"] = False
    updated["counts_as_a_plus"] = False
    updated["counts_as_live_ready"] = False
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(updated, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return updated


def maturity_queue(status: Mapping[str, Any], *, archive_path: Path, generated_utc: str) -> dict[str, Any]:
    return {
        "schema_version": "guardian_holdout_maturity_queue_v1",
        "generated_utc": generated_utc,
        "status": (
            "PIT_PREDICTION_COVERAGE_GROWING"
            if int(status.get("new_rows_appended") or 0) > 0
            else "PIT_PREDICTION_COVERAGE_NO_NEW_ROWS_THIS_CYCLE"
        ),
        "archive_path": str(archive_path),
        "pending_prediction_coverage_rows": int(status.get("point_in_time_valid_prediction_count") or 0),
        "matured_economic_rows": 0,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "next_required_step": "Run future-label maturation only after label windows close; do not use future labels as features.",
    }


def blocker_projection(status: Mapping[str, Any], *, generated_utc: str) -> dict[str, Any]:
    remaining = int(status.get("remaining_point_in_time_valid_predictions") or 0)
    return {
        "schema_version": "guardian_holdout_blocker_projection_v1",
        "generated_utc": generated_utc,
        "status": (
            "GUARDIAN_PIT_PREDICTION_GROWTH_IN_PROGRESS"
            if remaining > 0
            else "GUARDIAN_PIT_PREDICTION_MINIMUM_REACHED"
        ),
        "exact_blocker": "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS" if remaining > 0 else None,
        "observed": int(status.get("point_in_time_valid_prediction_count") or 0),
        "required": MINIMUM_PIT_VALID_PREDICTIONS,
        "remaining": remaining,
        "cycles_to_minimum_at_current_append_rate": status.get("cycles_to_minimum_at_current_append_rate"),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
    }
