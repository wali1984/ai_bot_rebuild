"""Causal in-process TA input for strategy supply.

Strategy supply must not consume the published ``v2:features:ta*``
compatibility views: those documents intentionally carry
``consumer_eligible=false`` and have no post-commit availability receipt.
This module instead performs one exact binary read of the canonical closed
OHLCV window, validates its source ABI/finality/identity/continuity, and
computes TA in the same process that will make the strategy decision.

The returned mapping is scoped to this in-process strategy calculation.  It
does not claim a Redis read receipt, immutable CAS capture, trainer admission,
or live-execution authority.  Missing or invalid input is represented by an
explicit masked status and never by zero-filled indicators.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.full_talib_ta.service import (
    FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS,
    build_full_talib_ta_closed_candidate,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    validate_ohlcv_closed_window,
)

STRATEGY_NATIVE_TA_SCHEMA_VERSION = "strategy_supply_native_closed_ta_v1"
STRATEGY_NATIVE_TA_STATUS_SCHEMA_VERSION = "strategy_supply_native_closed_ta_status_v1"


def _now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _epoch_ms_text(value: int) -> str:
    return _utc_text(datetime.fromtimestamp(value / 1000.0, tz=UTC))


def _content_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _source_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"


def _masked_status(
    *,
    source_key: str,
    reason: str,
    read_observed_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": STRATEGY_NATIVE_TA_STATUS_SCHEMA_VERSION,
        "state": "MASKED",
        "rejection_reason": reason,
        "source_ohlcv_key": source_key,
        "read_observed_at": read_observed_at,
        "cached_ta_compatibility_consumed": False,
        "latest_feature_snapshot_consumed": False,
        "zero_fill_used": False,
        "strategy_in_process_causal_input": False,
        "redis_read_receipt_emitted": False,
        "immutable_cas_captured": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }


def _read_exact_bytes(client: Any, key: str) -> tuple[bytes | None, datetime]:
    """Read one key and record the local observation immediately afterward."""

    try:
        raw = client.get(key) if client is not None else None
    except Exception:  # Redis/source absence is an optional-input mask.
        raw = None
    observed_at = _now()
    # Re-encoding a decode_responses=True string would not preserve proof of
    # the exact stored bytes.  Only a binary Redis response crosses this gate.
    return (raw if type(raw) is bytes and raw else None), observed_at


def load_causal_native_ta(
    client: Any,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return an in-process causal TA mapping and its explicit input status.

    Freshness is a protocol identity check, not a market-selection threshold:
    the final row must be the most recently completed interval for the requested
    timeframe at the read-observation clock.
    """

    key = _source_key(symbol, timeframe)
    exact_bytes, read_observed = _read_exact_bytes(client, key)
    read_observed_text = _utc_text(read_observed)
    if exact_bytes is None:
        return None, _masked_status(
            source_key=key,
            reason="EXACT_BINARY_CLOSED_OHLCV_UNAVAILABLE",
            read_observed_at=read_observed_text,
        )

    try:
        validated = validate_ohlcv_closed_window(
            exact_bytes,
            symbol=symbol,
            timeframe=timeframe,
            required_contiguous_lookback=FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS,
        )
    except OHLCVClosedWindowValidationError as exc:
        return None, _masked_status(
            source_key=key,
            reason=f"CANONICAL_CLOSED_OHLCV_INVALID:{exc}",
            read_observed_at=read_observed_text,
        )

    observed_ms = int(read_observed.timestamp() * 1000)
    if validated.max_available_at > observed_ms:
        return None, _masked_status(
            source_key=key,
            reason="CANONICAL_CLOSED_OHLCV_AVAILABLE_AFTER_READ_OBSERVATION",
            read_observed_at=read_observed_text,
        )
    if validated.latest_economic_close_time > observed_ms:
        return None, _masked_status(
            source_key=key,
            reason="CANONICAL_CLOSED_OHLCV_UNFINISHED_AT_READ_OBSERVATION",
            read_observed_at=read_observed_text,
        )

    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    expected_latest_close_ms = (observed_ms // duration_ms) * duration_ms - 1
    if validated.latest_economic_close_time != expected_latest_close_ms:
        return None, _masked_status(
            source_key=key,
            reason="CANONICAL_CLOSED_OHLCV_LATEST_COMPLETED_INTERVAL_MISMATCH",
            read_observed_at=read_observed_text,
        )

    try:
        candidate = build_full_talib_ta_closed_candidate(
            validated_window=validated,
        )
    except ValueError as exc:
        return None, _masked_status(
            source_key=key,
            reason=f"IN_PROCESS_TA_CONTRACT_REJECTED:{exc}",
            read_observed_at=read_observed_text,
        )

    indicators = candidate.get("indicators")
    if not isinstance(indicators, Mapping) or not indicators:
        return None, _masked_status(
            source_key=key,
            reason="IN_PROCESS_TA_NO_FINITE_INDICATORS",
            read_observed_at=read_observed_text,
        )
    if any(
        type(name) is not str
        or not name
        or type(value) not in (int, float)
        or not math.isfinite(float(value))
        for name, value in indicators.items()
    ):
        return None, _masked_status(
            source_key=key,
            reason="IN_PROCESS_TA_INDICATOR_CONTRACT_INVALID",
            read_observed_at=read_observed_text,
        )
    if (
        candidate.get("symbol") != symbol
        or candidate.get("timeframe") != timeframe
        or candidate.get("source_ohlcv_key") != validated.source_key
        or candidate.get("source_exact_payload_sha256") != validated.exact_payload_sha256
        or candidate.get("source_exact_payload_byte_count") != validated.exact_payload_byte_count
        or candidate.get("calculation_row_count") != FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS
        or candidate.get("latest_closed_candle_close_ts_ms") != validated.latest_economic_close_time
        or candidate.get("candle_closed_confirmed") is not True
        or candidate.get("closed_candles_only") is not True
    ):
        return None, _masked_status(
            source_key=key,
            reason="IN_PROCESS_TA_SOURCE_IDENTITY_MISMATCH",
            read_observed_at=read_observed_text,
        )
    if (
        candidate.get("consumer_eligible") is not False
        or candidate.get("trainer_consumable") is not False
        or candidate.get("trainer_admission_granted") is not False
        or candidate.get("live_execution_authorized") is not False
    ):
        return None, _masked_status(
            source_key=key,
            reason="IN_PROCESS_TA_AUTHORITY_ESCALATION_REJECTED",
            read_observed_at=read_observed_text,
        )

    feature_cutoff = _epoch_ms_text(validated.latest_economic_close_time)
    source_available_at = _epoch_ms_text(validated.max_available_at)
    latest_completed_interval_valid_before = _epoch_ms_text(
        validated.latest_economic_close_time + duration_ms + 1
    )
    semantic_payload = {
        "schema_version": STRATEGY_NATIVE_TA_SCHEMA_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "indicators": dict(indicators),
        "feature_cutoff": feature_cutoff,
        "read_observed_at": read_observed_text,
        "source_available_at": source_available_at,
        "latest_completed_interval_valid_before": (
            latest_completed_interval_valid_before
        ),
        "source_ohlcv_key": key,
        "source_exact_payload_sha256": validated.exact_payload_sha256,
        "source_exact_payload_byte_count": validated.exact_payload_byte_count,
        "source_row_count": validated.row_count,
        "source_contiguous_suffix_count": validated.contiguous_suffix_count,
        "calculation_row_count": candidate.get("calculation_row_count"),
        "calculation_window_candle_ids_sha256": candidate.get(
            "calculation_window_candle_ids_sha256"
        ),
        "latest_candle_id": candidate.get("latest_candle_id"),
        "latest_candle_raw_payload_hash": candidate.get("latest_candle_raw_payload_hash"),
        "last_closed_candle_open_ts_ms": validated.rows[-1].candle_open_time,
        "last_closed_candle_close_ts_ms": validated.latest_economic_close_time,
        "candle_closed_confirmed": True,
        "closed_candles_only": True,
        "exact_source_schema_validated": True,
        "producer_finality_contract_validated": True,
        "latest_completed_interval_verified": True,
        "cached_ta_compatibility_consumed": False,
        "latest_feature_snapshot_consumed": False,
        "zero_fill_used": False,
        "strategy_in_process_causal_input": True,
        "consumer_scope": "strategy_supply_same_process_decision_only",
        "redis_read_receipt_emitted": False,
        "immutable_cas_captured": False,
        "generic_consumer_eligible": False,
        "trainer_consumable": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    semantic_content_sha256 = _content_hash(semantic_payload)
    # Capture availability only after all source/indicator/authority checks and
    # the final semantic identity have completed.  The derived feature did not
    # exist at the source candle's earlier availability clock.
    computed_available = _now()
    computed_available_ms = int(computed_available.timestamp() * 1000)
    expected_close_at_computation = (
        (computed_available_ms // duration_ms) * duration_ms - 1
    )
    if validated.latest_economic_close_time != expected_close_at_computation:
        return None, _masked_status(
            source_key=key,
            reason="CANONICAL_CLOSED_OHLCV_BECAME_STALE_DURING_COMPUTATION",
            read_observed_at=read_observed_text,
        )
    computed_available_text = _utc_text(computed_available)
    payload = {
        **semantic_payload,
        "available_at": computed_available_text,
        "computed_available_at": computed_available_text,
        "in_process_ta_content_sha256": semantic_content_sha256,
        "in_process_ta_content_hash_role": ("deterministic_content_identity_not_authentication"),
    }
    status = {
        "schema_version": STRATEGY_NATIVE_TA_STATUS_SCHEMA_VERSION,
        "state": "PRESENT",
        "rejection_reason": None,
        "source_ohlcv_key": key,
        "source_exact_payload_sha256": validated.exact_payload_sha256,
        "in_process_ta_content_sha256": semantic_content_sha256,
        "feature_cutoff": feature_cutoff,
        "source_available_at": source_available_at,
        "read_observed_at": read_observed_text,
        "computed_available_at": computed_available_text,
        "latest_completed_interval_valid_before": (
            latest_completed_interval_valid_before
        ),
        "cached_ta_compatibility_consumed": False,
        "latest_feature_snapshot_consumed": False,
        "zero_fill_used": False,
        "strategy_in_process_causal_input": True,
        "redis_read_receipt_emitted": False,
        "immutable_cas_captured": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    return payload, status
