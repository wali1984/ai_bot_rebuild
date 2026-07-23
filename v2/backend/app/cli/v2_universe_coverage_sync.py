"""V2 adaptive-universe end-to-end coverage guarantee (Lane D).

The symbol universe (``v2_symbol_runtime_universe.resolve_symbols``) is
adaptive: symbols rotate in and out with the market. New entrants arrive
with no closed-candle history, no OI/orderbook coverage, and 0% feature
coverage until someone runs a manual backfill. This CLI closes that gap
permanently:

Each run it
  1. resolves the current universe,
  2. builds a per-symbol per-family coverage census over the six core
     families the decision pipeline needs:
       - ohlcv_closed  (v2:market:ohlcv_closed:binance:{sym}:{tf},
                        all 5 decision TFs, exact canonical schema,
                        latest finalized close, and a contiguous suffix meeting
                        the 71-row core-TA minimum coverage invariant)
       - prices        (v2:market:prices:{sym})
       - orderbook     (v2:market:orderbook:{sym})
       - open_interest (v2:market:open_interest:{sym})
       - ta_full       (v2:features:ta_full:{sym}:{tf})
       - feature_snapshot (v2:features:latest:{sym}:{tf} + FEATURE_SPEC
                        coverage of the trainer tensor)
  3. actively heals closed-candle gaps by invoking the parameterized
     Binance kline backfill (direct import; every REST request goes
     through ``require_binance_rest_fallback`` so the shared host-wide
     budget is respected — REST_FALLBACK_BUDGET_EXHAUSTED means
     skip-this-cycle, never hammer),
  4. verifies (does not duplicate) the ingestor-owned families:
     prices/orderbook/open_interest/ta_full/feature_snapshot heal on the
     next ingestor/TA/feature cycles because those loops re-resolve the
     same universe every cycle; the census records the heal path and the
     next run proves the heal happened,
  5. publishes the census to Redis ``v2:universe:coverage_census``
     (with ``generated_utc``) for the dashboard / Monitor Center.

Safety: read-only public market data plus bounded atomic Redis writes to exact
closed-window keys and the census key. No orders. No credentials. Never live.
Runs as a 15-minute systemd user timer
(``ai-bot-v2-universe-coverage-sync.timer``).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import redis  # noqa: E402

from v2.backend.app.cli.v2_binance_kline_rest_backfill import (  # noqa: E402
    REST_BUDGET_EXHAUSTED_ERROR_CODE,
    TERMINAL_REST_RECOVERY_ERROR_CODES,
    KlineBackfillRestBudgetDeferred,
    _backfill_symbol_tf,
    _consume_factory_issued_rest_budget_deferral,
    _stable_error_code,
)
from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    binance_rest_fallback_allowed,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    REQUIRED_DECISION_TIMEFRAMES,
    TIMEFRAME_SECONDS,
    closed_candle_key,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (  # noqa: E402
    MAX_SOURCE_PAYLOAD_BYTES,
    AtomicRedisSourceReadError,
    RawRedisSourceClient,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (  # noqa: E402
    CORE_TA_MINIMUM_SOURCE_ROWS,
    FeatureWindowContractError,
    inspect_canonical_contiguous_suffix,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (  # noqa: E402
    FEATURE_SPEC,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (  # noqa: E402
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    is_valid_runtime_symbol,
    resolve_symbols_with_provenance,
)

WORKER_ID = "v2_universe_coverage_sync"
SCHEMA_VERSION = "v2_universe_coverage_census_v2"
CENSUS_REDIS_KEY = "v2:universe:coverage_census"
# Publisher runs every 15 min; 2h TTL keeps a dead timer visible without
# leaving a permanently stale census behind (champion/challenger lesson).
CENSUS_TTL_SECONDS = 7200
# Cache-echo freshness gate: this worker reads its own previous census
# only to report deltas; anything older than this is treated as absent.
PREVIOUS_CENSUS_MAX_AGE_SECONDS = 86400

FAMILIES = (
    "ohlcv_closed",
    "prices",
    "orderbook",
    "open_interest",
    "ta_full",
    "feature_snapshot",
)

# Heal ownership: which loop closes a gap in each family. ohlcv_closed is
# the only family this CLI heals directly (parameterized backfill); the
# rest re-resolve the universe every cycle and pick new symbols up
# automatically once candles exist.
FAMILY_HEAL_PATH = {
    "ohlcv_closed": "v2_universe_coverage_sync_backfill",
    "prices": "v2_native_ingestors_live_loop_next_cycle",
    "orderbook": "v2_native_ingestors_live_loop_next_cycle",
    "open_interest": "v2_native_ingestors_live_loop_next_cycle",
    "ta_full": "v2_full_talib_ta_loop_next_cycle",
    "feature_snapshot": "v2_feature_pipeline_native_loop_next_cycle",
}


# Freshness gates (seconds), env-overridable. Symbol-keyed families use a
# flat max age; non-OHLCV timeframe-keyed families use tf period + grace
# because a 4h family legitimately only refreshes every 4 hours. OHLCV uses
# exact end-exclusive finality and tail-continuity evidence instead of an age
# threshold.
def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


PRICES_MAX_AGE_S = _env_int("V2_UNIVERSE_SYNC_PRICES_MAX_AGE_S", 300)
# Orderbook/OI keys are written by v2_native_ingestors_live_loop with a
# 600s TTL; the freshness contract is therefore "present implies <=600s
# old". A tighter gate just re-flags symbols the writer is already
# maintaining at its budget-achievable cadence.
ORDERBOOK_MAX_AGE_S = _env_int("V2_UNIVERSE_SYNC_ORDERBOOK_MAX_AGE_S", 600)
OPEN_INTEREST_MAX_AGE_S = _env_int("V2_UNIVERSE_SYNC_OPEN_INTEREST_MAX_AGE_S", 900)
TA_FULL_GRACE_S = _env_int("V2_UNIVERSE_SYNC_TA_FULL_GRACE_S", 1800)
SNAPSHOT_GRACE_S = _env_int("V2_UNIVERSE_SYNC_SNAPSHOT_GRACE_S", 1800)
SECONDARY_MAX_AGE_S = _env_int("V2_UNIVERSE_SYNC_SECONDARY_MAX_AGE_S", 1800)
# Budget guard: hard cap on backfill (symbol, timeframe) pairs per run so
# a large rotation cannot blow the shared per-minute REST budget or the
# 15-minute timer window.
MAX_BACKFILL_PAIRS_DEFAULT = _env_int("V2_UNIVERSE_SYNC_MAX_BACKFILL_PAIRS", 120)
MAX_COVERAGE_BACKFILL_PAIRS_PER_RUN = 4096
BACKFILL_SLEEP_SECONDS = 0.15

# Resource-reporting bound only. The exact schema parser and transport enforce
# their own fixed row/byte ABI limits; this merely prevents a large universe
# census from repeating every gap index in its published JSON.
MAX_REPORTED_OHLCV_GAPS = 32
OHLCV_COVERAGE_SEMANTICS = (
    "CORE_TA_MINIMUM_COVERAGE_FLOOR_NOT_EXACT_DEPENDENCY_LENGTH_"
    "NOT_MARKET_SELECTION_OR_TRAINER_ADMISSION"
)
# The contiguous suffix inspector is source evidence only. The current feature
# worker still supplies whole lists to several transforms, so this census must
# not turn source readiness into end-to-end consumer readiness.
OHLCV_CONSUMER_SELECTION_BOUND = False
OHLCV_CONSUMER_HOLD_REASON = "FULL_CONTIGUOUS_SUFFIX_SELECTION_NOT_WIRED"

# Feature snapshots currently require a durable postcommit publication receipt
# before any trainer/prediction/paper consumer flag can be trusted. The receipt
# validator is intentionally not wired into this census yet.
FEATURE_PUBLICATION_RECEIPT_VALIDATOR_BOUND = False
FEATURE_CONSUMER_HOLD_REASON = "FEATURE_PUBLICATION_RECEIPT_VALIDATOR_NOT_BOUND"
TA_FINALITY_CONSUMER_BOUND = False
TA_CONSUMER_HOLD_REASON = "TA_FULL_FINALIZED_INPUT_RECEIPT_NOT_BOUND"

# Immutable resource bounds; neither value selects markets or grants admission.
MAX_CENSUS_JSON_SOURCE_BYTES = 1024 * 1024
MAX_CENSUS_JSON_DEPTH = 64
MAX_CENSUS_JSON_NODES = 65_536
MAX_CENSUS_JSON_CONTAINER_ITEMS = 16_384
MAX_CENSUS_JSON_STRING_BYTES = 256 * 1024
MAX_CENSUS_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_CENSUS_SYMBOLS = 4096
MAX_CENSUS_SYMBOL_ENTRY_BYTES = 64 * 1024
MAX_CENSUS_SYMBOL_ENTRIES_AGGREGATE_BYTES = 12 * 1024 * 1024
MAX_REPORTED_SECONDARY_FAMILIES = 32
MAX_SECONDARY_FAMILY_COUNT = 1024
MAX_SECONDARY_FAMILY_NAME_BYTES = 64
MAX_REPORTED_FEATURE_COUNT = 10_000
MAX_CENSUS_METADATA_TOKEN_BYTES = 256

STATUS_FILE = (
    _repo / "v2/frontend/public/operator_runtime/v2_universe_coverage_sync/latest/"
    "v2_universe_coverage_sync_status.json"
)
STATUS_FILE_ENV_VAR = "V2_UNIVERSE_COVERAGE_SYNC_STATUS_FILE"


def _absolute_status_file(value: str) -> Path:
    """Require an explicit external status target for immutable releases."""

    path = Path(value)
    if not path.is_absolute() or not path.name or "\x00" in value:
        raise argparse.ArgumentTypeError("status file must be an absolute file path")
    return path


def _utc_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, tz=UTC) if ts else datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


def _ohlcv_binary_redis_client() -> redis.Redis:
    """Return the dedicated raw client required for exact OHLCV bytes."""

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=False)


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("nonfinite_json_constant")


def _bounded_canonical_json(
    value: Any,
    *,
    max_bytes: int,
    error_code: str,
) -> str:
    """Serialize canonical JSON without first materializing an unbounded payload."""

    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("universe_coverage_json_resource_bound_invalid")
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    buffer = io.StringIO()
    byte_count = 0
    for chunk in encoder.iterencode(value):
        # ensure_ascii=True guarantees the encoded chunk is ASCII. Count bytes
        # before retaining the chunk so the aggregate string never crosses the
        # caller's immutable resource limit.
        chunk_bytes = len(chunk.encode("ascii"))
        if byte_count + chunk_bytes > max_bytes:
            raise ValueError(error_code)
        buffer.write(chunk)
        byte_count += chunk_bytes
    return buffer.getvalue()


def _bounded_metadata_token(value: Any) -> str | None:
    """Retain only short printable ASCII provenance/status tokens."""

    if not isinstance(value, str) or not value:
        return None
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return "UNTRUSTED_METADATA_TOKEN"
    if len(encoded) > MAX_CENSUS_METADATA_TOKEN_BYTES or any(
        character < " " or character == "\x7f" for character in value
    ):
        return "UNTRUSTED_METADATA_TOKEN"
    return value


def _json_shape_within_resource_bounds(value: Any) -> bool:
    """Validate decoded JSON iteratively so hostile depth cannot recurse."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    node_count = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        if depth > MAX_CENSUS_JSON_DEPTH or node_count > MAX_CENSUS_JSON_NODES:
            return False
        if isinstance(current, dict):
            if len(current) > MAX_CENSUS_JSON_CONTAINER_ITEMS:
                return False
            for key, child in current.items():
                if type(key) is not str:
                    return False
                try:
                    if len(key.encode("utf-8", errors="strict")) > MAX_CENSUS_JSON_STRING_BYTES:
                        return False
                except UnicodeError:
                    return False
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > MAX_CENSUS_JSON_CONTAINER_ITEMS:
                return False
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            try:
                if len(current.encode("utf-8", errors="strict")) > MAX_CENSUS_JSON_STRING_BYTES:
                    return False
            except UnicodeError:
                return False
        elif type(current) in (int, float):
            try:
                if not math.isfinite(float(current)):
                    return False
            except (OverflowError, ValueError):
                return False
        elif current is not None and type(current) not in (bool, int, float):
            return False
    return True


def _bounded_secondary_family_summary(value: Any) -> dict[str, Any]:
    """Summarize untrusted provider family names without echoing the list."""

    if type(value) is int:
        count_valid = 0 <= value <= MAX_SECONDARY_FAMILY_COUNT
        return {
            "valid": count_valid,
            "reason": "ok" if count_valid else "SECONDARY_FAMILY_COUNT_RESOURCE_LIMIT",
            "representation": "count_only",
            "family_count": value if value >= 0 else 0,
            "reported_family_count": 0,
            "families_truncated": value > 0,
            "reported_families": [],
            "all_families_sha256": None,
        }
    if not isinstance(value, list):
        return {
            "valid": False,
            "reason": "SECONDARY_FAMILY_LIST_REQUIRED",
            "representation": "invalid",
            "family_count": 0,
            "reported_family_count": 0,
            "families_truncated": False,
            "reported_families": [],
            "all_families_sha256": None,
        }
    family_count = len(value)
    if family_count > MAX_SECONDARY_FAMILY_COUNT:
        return {
            "valid": False,
            "reason": "SECONDARY_FAMILY_COUNT_RESOURCE_LIMIT",
            "representation": "named_list",
            "family_count": family_count,
            "reported_family_count": 0,
            "families_truncated": family_count > 0,
            "reported_families": [],
            "all_families_sha256": None,
        }

    validated: list[str] = []
    for family in value:
        if (
            not isinstance(family, str)
            or not family
            or not family.isascii()
            or len(family.encode("ascii")) > MAX_SECONDARY_FAMILY_NAME_BYTES
            or any(not (character.isalnum() or character in "_-.:") for character in family)
        ):
            return {
                "valid": False,
                "reason": "SECONDARY_FAMILY_NAME_INVALID",
                "representation": "named_list",
                "family_count": family_count,
                "reported_family_count": 0,
                "families_truncated": family_count > 0,
                "reported_families": [],
                "all_families_sha256": None,
            }
        validated.append(family)

    material = _bounded_canonical_json(
        validated,
        max_bytes=(MAX_SECONDARY_FAMILY_COUNT * (MAX_SECONDARY_FAMILY_NAME_BYTES + 3)) + 2,
        error_code="universe_coverage_secondary_family_material_resource_limit",
    )
    reported = validated[:MAX_REPORTED_SECONDARY_FAMILIES]
    return {
        "valid": True,
        "reason": "ok",
        "representation": "named_list",
        "family_count": family_count,
        "reported_family_count": len(reported),
        "families_truncated": len(reported) != family_count,
        "reported_families": reported,
        "all_families_sha256": hashlib.sha256(material.encode("ascii")).hexdigest(),
    }


def _read_json(r: redis.Redis, key: str) -> Any:
    try:
        raw = cast(
            str | bytes | bytearray | None,
            r.getrange(key, 0, MAX_CENSUS_JSON_SOURCE_BYTES),
        )
    except (redis.RedisError, UnicodeError):
        return None
    if not raw:
        return None
    try:
        raw_byte_count = (
            len(raw.encode("utf-8", errors="strict")) if isinstance(raw, str) else len(raw)
        )
    except (TypeError, UnicodeError):
        return None
    if raw_byte_count > MAX_CENSUS_JSON_SOURCE_BYTES:
        return None
    try:
        decoded = json.loads(raw, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None
    return decoded if _json_shape_within_resource_bounds(decoded) else None


def _parse_ts_seconds(value: Any) -> float | None:
    """Parse epoch s/ms or ISO-8601 (Z or offset) into epoch seconds."""
    if value is None:
        return None
    if type(value) in (int, float):
        v = float(value)
        if not math.isfinite(v) or v <= 0:
            return None
        # Heuristic: epoch ms vs s.
        return v / 1000.0 if v > 1e11 else v
    text = str(value).strip()
    if not text:
        return None
    try:
        v = float(text)
        if not math.isfinite(v) or v <= 0:
            return None
        return v / 1000.0 if v > 1e11 else v
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return None
        parsed = dt.timestamp()
        return parsed if math.isfinite(parsed) and parsed > 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def _explicit_iso_epoch_us(value: Any) -> int | None:
    """Parse one timezone-explicit ISO clock without float precision loss."""

    if type(value) is not str or not value or value != value.strip():
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    utc_value = parsed.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = utc_value - epoch
    epoch_us = ((delta.days * 86_400) + delta.seconds) * 1_000_000 + delta.microseconds
    return epoch_us if epoch_us > 0 else None


def _payload_age_seconds(payload: Any, *fields: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for field in fields:
        ts = _parse_ts_seconds(payload.get(field))
        if ts is not None:
            return time.time() - ts
    return None


def _consumer_observed_at_ms() -> int:
    """Local instant after the exact transport result is possessed."""

    return time.time_ns() // 1_000_000


def _ohlcv_base_entry(*, key: str, status: str) -> dict[str, Any]:
    return {
        "ok": status == "ok",
        "reason": status,
        "coverage_status": status,
        "source_key": key,
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "coverage_semantics": OHLCV_COVERAGE_SEMANTICS,
        "market_selection_threshold": False,
        "source_window_recovery_ready": False,
        "consumer_selection_bound": OHLCV_CONSUMER_SELECTION_BOUND,
        "consumer_hold_reason": OHLCV_CONSUMER_HOLD_REASON,
        "trainer_consumption_ready": False,
        "source_schema_validated": False,
        "producer_finality_contract_validated": False,
        "end_exclusive_consumer_finality_validated": False,
    }


def _bounded_gap_evidence(
    gap_indices: tuple[int, ...],
    gap_missing_interval_counts: tuple[int, ...],
) -> dict[str, Any]:
    pairs = list(zip(gap_indices, gap_missing_interval_counts, strict=True))
    material = json.dumps(
        pairs,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    reported = pairs[:MAX_REPORTED_OHLCV_GAPS]
    return {
        "gap_count": len(pairs),
        "reported_gap_count": len(reported),
        "gaps_truncated": len(reported) != len(pairs),
        "gap_indices": [index for index, _missing in reported],
        "gap_missing_interval_counts": [missing for _index, missing in reported],
        "all_gaps_sha256": hashlib.sha256(material.encode("ascii")).hexdigest(),
    }


def _strict_window_evidence(
    validated: ValidatedOHLCVClosedWindow,
) -> dict[str, Any]:
    gaps = _bounded_gap_evidence(
        validated.gap_indices,
        validated.gap_missing_interval_counts,
    )
    return {
        "source_schema_version": validated.schema_version,
        "exact_payload_byte_count": validated.exact_payload_byte_count,
        "exact_payload_sha256": validated.exact_payload_sha256,
        "rows": validated.row_count,
        "row_count": validated.row_count,
        "first_economic_close_time": validated.first_economic_close_time,
        "latest_economic_close_time": validated.latest_economic_close_time,
        "max_available_at": validated.max_available_at,
        "missing_interval_count": validated.missing_interval_count,
        **gaps,
    }


# ---------------------------------------------------------------------------
# Per-family checks
# ---------------------------------------------------------------------------


def _check_ohlcv_closed(
    r: RawRedisSourceClient,
    symbol: str,
) -> dict[str, Any]:
    tfs: dict[str, Any] = {}
    ok_count = 0
    source_ready_count = 0
    for tf in REQUIRED_DECISION_TIMEFRAMES:
        key = closed_candle_key("binance", symbol, tf)
        try:
            batch = read_atomic_redis_sources(r, (key,))
            # This local clock is intentionally captured immediately after the
            # exact bounded transport returns. Redis TIME is a server clock,
            # not when this consumer possessed the bytes.
            consumer_observed_at_ms = _consumer_observed_at_ms()
        except AtomicRedisSourceReadError as exc:
            error_code = _stable_error_code(exc)
            status = (
                "oversized"
                if error_code == "atomic_redis_source_read_payload_bytes_exceeded"
                else "transport_invalid"
            )
            entry = _ohlcv_base_entry(key=key, status=status)
            entry["transport_error_code"] = error_code
            if status == "oversized":
                entry.update(
                    max_exact_payload_bytes=MAX_SOURCE_PAYLOAD_BYTES,
                    payload_byte_count_lower_bound=MAX_SOURCE_PAYLOAD_BYTES + 1,
                )
            tfs[tf] = entry
            continue

        result = batch.results[0]
        if not result.present:
            tfs[tf] = _ohlcv_base_entry(key=key, status="missing")
            continue
        exact_payload = result.exact_payload_bytes
        try:
            validated = validate_ohlcv_closed_window(
                exact_payload,
                symbol=symbol,
                timeframe=tf,
            )
        except OHLCVClosedWindowValidationError as exc:
            entry = _ohlcv_base_entry(key=key, status="schema_invalid")
            entry.update(
                exact_payload_byte_count=result.payload_byte_count,
                exact_payload_sha256=result.payload_sha256,
                schema_error_code=_stable_error_code(exc),
                validation_stage="exact_source_schema",
            )
            tfs[tf] = entry
            continue

        duration_ms = TIMEFRAME_DURATION_MS[tf]
        expected_latest_close = ((consumer_observed_at_ms // duration_ms) * duration_ms) - 1
        projection = tuple(
            {
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "candle_id": row.candle_id,
                "candle_open_time": row.candle_open_time,
                "candle_close_time": row.candle_close_time,
                "available_at": row.available_at,
            }
            for row in validated.rows
        )
        try:
            inspection = inspect_canonical_contiguous_suffix(
                projection,
                expected_symbol=symbol,
                timeframe=tf,
                consumer_observed_at_ms=consumer_observed_at_ms,
                expected_latest_finalized_close_time=expected_latest_close,
            )
        except FeatureWindowContractError as exc:
            entry = _ohlcv_base_entry(key=key, status="schema_invalid")
            entry.update(_strict_window_evidence(validated))
            entry.update(
                source_schema_validated=True,
                producer_finality_contract_validated=True,
                consumer_contract_error_code=_stable_error_code(exc),
                validation_stage="consumer_finality_and_continuity",
                consumer_observed_at_ms=consumer_observed_at_ms,
                expected_latest_finalized_close_time=expected_latest_close,
            )
            tfs[tf] = entry
            continue

        source_window_recovery_ready = inspection.core_ta_minimum_coverage_ready
        trainer_consumption_ready = source_window_recovery_ready and OHLCV_CONSUMER_SELECTION_BOUND
        if inspection.tail_missing_interval_count != 0:
            status = "tail_stale"
        elif inspection.contiguous_suffix_count < CORE_TA_MINIMUM_SOURCE_ROWS:
            status = "contiguous_suffix_short"
        elif not OHLCV_CONSUMER_SELECTION_BOUND:
            status = "source_ready_consumer_unbound"
        else:
            status = "ok"

        entry = _ohlcv_base_entry(key=key, status=status)
        entry.update(_strict_window_evidence(validated))
        entry.update(
            ok=status == "ok",
            source_schema_validated=True,
            producer_finality_contract_validated=True,
            end_exclusive_consumer_finality_validated=True,
            continuity_inspection_version=inspection.schema_version,
            minimum_coverage_contract_sha256=inspection.contract_sha256,
            consumer_observed_at_ms=inspection.consumer_observed_at_ms,
            expected_latest_finalized_close_time=(inspection.expected_latest_finalized_close_time),
            latest_candle_matches_expected_cutoff=(
                inspection.latest_candle_matches_expected_cutoff
            ),
            tail_missing_interval_count=inspection.tail_missing_interval_count,
            contiguous_suffix_start_index=inspection.contiguous_suffix_start_index,
            contiguous_suffix_count=inspection.contiguous_suffix_count,
            full_contiguous_suffix_candle_id_chain_sha256=(
                inspection.selected_candle_id_chain_sha256
            ),
            core_ta_minimum_coverage_ready=(inspection.core_ta_minimum_coverage_ready),
            source_window_recovery_ready=source_window_recovery_ready,
            consumer_selection_bound=OHLCV_CONSUMER_SELECTION_BOUND,
            consumer_hold_reason=OHLCV_CONSUMER_HOLD_REASON,
            trainer_consumption_ready=trainer_consumption_ready,
        )
        if source_window_recovery_ready:
            source_ready_count += 1
        if status == "ok":
            ok_count += 1
        tfs[tf] = entry
    if ok_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "ok"
    elif source_ready_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "source_ready_consumer_unbound"
    else:
        status = "partial" if source_ready_count else "missing"
    return {
        "status": status,
        "ok_tfs": ok_count,
        "source_ready_tfs": source_ready_count,
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "coverage_semantics": OHLCV_COVERAGE_SEMANTICS,
        "market_selection_threshold": False,
        "source_windows_ready": all(
            entry.get("source_window_recovery_ready") is True for entry in tfs.values()
        ),
        "consumer_selection_bound": OHLCV_CONSUMER_SELECTION_BOUND,
        "consumer_hold_reason": OHLCV_CONSUMER_HOLD_REASON,
        "trainer_consumption_ready": False,
        "tfs": tfs,
    }


def _price_content_rejections(payload: Any, symbol: str) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("PRICE_PAYLOAD_OBJECT_REQUIRED",)
    reasons: list[str] = []
    if payload.get("symbol") != symbol:
        reasons.append("PRICE_SYMBOL_IDENTITY_INVALID")
    ticker = payload.get("ticker_24hr")
    candidate = ticker if isinstance(ticker, dict) else payload
    last_price = candidate.get("lastPrice", candidate.get("price"))
    if not _finite(last_price) or float(last_price) <= 0:
        reasons.append("PRICE_VALUE_INVALID")
    if not isinstance(payload.get("source"), str) or not payload.get("source"):
        reasons.append("PRICE_SOURCE_IDENTITY_REQUIRED")
    return tuple(sorted(set(reasons)))


def _book_level(payload: Any, field: str, fallback: str) -> tuple[float, float] | None:
    levels = payload.get(field) if isinstance(payload, dict) else None
    if isinstance(levels, list) and levels:
        first = levels[0]
        if isinstance(first, list | tuple) and len(first) >= 2:
            price, quantity = first[0], first[1]
            if _finite(price) and _finite(quantity):
                return float(price), float(quantity)
    price = payload.get(fallback) if isinstance(payload, dict) else None
    side = fallback.removeprefix("best_")
    quantity = None
    if isinstance(payload, dict):
        quantity = next(
            (
                payload.get(quantity_field)
                for quantity_field in (
                    f"{fallback}_qty",
                    f"{fallback}_size",
                    f"{side}_qty",
                    f"{side}_size",
                )
                if payload.get(quantity_field) is not None
            ),
            None,
        )
    if _finite(price) and _finite(quantity):
        return float(price), float(quantity)
    return None


def _orderbook_content_rejections(payload: Any, symbol: str) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("ORDERBOOK_PAYLOAD_OBJECT_REQUIRED",)
    reasons: list[str] = []
    if payload.get("symbol") != symbol:
        reasons.append("ORDERBOOK_SYMBOL_IDENTITY_INVALID")
    bid = _book_level(payload, "bids", "best_bid")
    ask = _book_level(payload, "asks", "best_ask")
    if bid is None or bid[0] <= 0 or bid[1] < 0:
        reasons.append("ORDERBOOK_BID_INVALID")
    if ask is None or ask[0] <= 0 or ask[1] < 0:
        reasons.append("ORDERBOOK_ASK_INVALID")
    if bid is not None and ask is not None and bid[0] >= ask[0]:
        reasons.append("ORDERBOOK_CROSSED_OR_LOCKED")
    return tuple(sorted(set(reasons)))


def _open_interest_content_rejections(payload: Any, symbol: str) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("OPEN_INTEREST_PAYLOAD_OBJECT_REQUIRED",)
    reasons: list[str] = []
    if payload.get("symbol") != symbol:
        reasons.append("OPEN_INTEREST_SYMBOL_IDENTITY_INVALID")
    value = next(
        (
            payload.get(field)
            for field in ("open_interest", "openInterest", "sumOpenInterest")
            if payload.get(field) is not None
        ),
        None,
    )
    numeric_value = float(cast(Any, value)) if _finite(value) else None
    if numeric_value is None or numeric_value < 0:
        reasons.append("OPEN_INTEREST_VALUE_INVALID")
    return tuple(sorted(set(reasons)))


def _ta_content_rejections(
    payload: Any,
    symbol: str,
    timeframe: str,
    *,
    census_as_of_ns: int | None = None,
) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("TA_PAYLOAD_OBJECT_REQUIRED",)
    reasons: list[str] = []
    if payload.get("schema_version") != "v2_full_talib_ta_closed_candidate_v1":
        reasons.append("TA_SCHEMA_IDENTITY_INVALID")
    if payload.get("symbol") != symbol or payload.get("timeframe") != timeframe:
        reasons.append("TA_MARKET_IDENTITY_INVALID")
    expected_candidate_key = f"v2:features:ta_closed:{symbol}:{timeframe}"
    expected_publication_key = f"v2:features:ta_full:{symbol}:{timeframe}"
    if (
        payload.get("compatibility_view") is not True
        or payload.get("compatibility_unsafe_for_trainer") is not True
        or payload.get("canonical_candidate_key") != expected_candidate_key
        or payload.get("publication_key") != expected_publication_key
        or payload.get("source_label") != "V2_FULL_TALIB_TA_CLOSED_COMPATIBILITY_VIEW"
    ):
        reasons.append("TA_COMPATIBILITY_VIEW_IDENTITY_INVALID")
    if payload.get("classification") != "V2_FULL_TALIB_TA_CLOSED_CANDIDATE_NONCONSUMABLE":
        reasons.append("TA_CLASSIFICATION_INVALID")
    if (
        payload.get("computation_classification") != "V2_FULL_TALIB_TA_OK"
        or payload.get("source_schema_version") != "trainer_ohlcv_closed_window_v1"
    ):
        reasons.append("TA_COMPUTATION_CLASSIFICATION_INVALID")
    for field_name in (
        "exact_source_schema_validated",
        "producer_finality_contract_validated",
        "closed_candles_only",
        "candle_closed_confirmed",
        "v2_only",
        "no_zero_fill",
    ):
        if payload.get(field_name) is not True:
            reasons.append("TA_FINALIZED_SOURCE_CONTRACT_INVALID")
            break
    for field_name in (
        "publication_committed",
        "consumer_eligible",
        "trainer_consumable",
        "trainer_admission_granted",
        "immutable_cas_captured",
        "redis_read_receipt_emitted",
        "live_execution_authorized",
        "exchange_action_taken",
        "places_real_order",
        "writes_legacy_redis",
    ):
        if payload.get(field_name) is not False:
            reasons.append("TA_NONCONSUMABLE_AUTHORITY_INVALID")
            break
    for field_name in (
        "publication_authority",
        "trainer_authority",
        "prediction_authority",
        "risk_authority",
        "orchestrator_authority",
        "allocator_authority",
        "paper_authority",
        "live_authority",
        "valid_for_trainer",
        "valid_for_prediction",
        "valid_for_risk",
        "valid_for_orchestrator",
        "valid_for_allocator",
        "valid_for_paper",
        "valid_for_live",
    ):
        # The current producer does not emit these optional authority fields.
        # Their absence is fail-closed; if a future or hostile payload adds
        # one, only an explicit false value preserves the nonconsumable ABI.
        if field_name in payload and payload.get(field_name) is not False:
            reasons.append("TA_NONCONSUMABLE_AUTHORITY_INVALID")
            break
    if (
        payload.get("available_at") is not None
        or payload.get("publication_observed_at") is not None
    ):
        reasons.append("TA_UNAUTHENTICATED_AVAILABLE_AT_FORBIDDEN")
    if payload.get("live_gate") != "blocked_human_only" or payload.get("live_symbols") != []:
        reasons.append("TA_NONCONSUMABLE_AUTHORITY_INVALID")
    indicators = payload.get("indicators")
    indicator_mapping = indicators if isinstance(indicators, dict) else {}
    indicator_count = payload.get("indicator_count")
    field_count = payload.get("field_count")
    if (
        not indicator_mapping
        or type(indicator_count) is not int
        or type(field_count) is not int
        or indicator_count != len(indicator_mapping)
        or field_count != indicator_count
        # Producer completeness invariant, not a market-selection threshold.
        or indicator_count < 150
        or any(type(name) is not str or not name for name in indicator_mapping)
        or any(not _finite(value) for value in indicator_mapping.values())
    ):
        reasons.append("TA_INDICATOR_VALUES_INVALID")
    last_candle_ts_ms = payload.get("last_candle_ts_ms")
    if type(last_candle_ts_ms) is not int or last_candle_ts_ms <= 0:
        reasons.append("TA_SOURCE_CANDLE_CLOCK_INVALID")
    source_key = payload.get("source_ohlcv_key")
    if source_key != f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}":
        reasons.append("TA_SOURCE_KEY_IDENTITY_INVALID")
    duration_ms = TIMEFRAME_DURATION_MS.get(timeframe)
    latest_open_ms = payload.get("latest_closed_candle_open_ts_ms")
    latest_close_ms = payload.get("latest_closed_candle_close_ts_ms")
    if (
        type(duration_ms) is not int
        or type(latest_open_ms) is not int
        or type(latest_close_ms) is not int
        or latest_open_ms <= 0
        or latest_close_ms != latest_open_ms + duration_ms - 1
        or last_candle_ts_ms != latest_open_ms
    ):
        reasons.append("TA_SOURCE_CANDLE_CLOCK_INVALID")
    else:
        observed_ns = time.time_ns() if census_as_of_ns is None else census_as_of_ns
        if type(observed_ns) is not int or observed_ns <= 0:
            reasons.append("TA_CENSUS_AS_OF_CLOCK_INVALID")
        else:
            expected_latest_close_ms = ((observed_ns // 1_000_000) // duration_ms) * duration_ms - 1
            if latest_close_ms != expected_latest_close_ms:
                reasons.append("TA_LATEST_FINALIZED_CANDLE_UNAVAILABLE")

        cutoff_us = _explicit_iso_epoch_us(payload.get("feature_cutoff"))
        event_us = _explicit_iso_epoch_us(payload.get("source_economic_event_time"))
        source_event_us = _explicit_iso_epoch_us(payload.get("source_event_time"))
        producer_us = _explicit_iso_epoch_us(payload.get("source_producer_event_time"))
        available_us = _explicit_iso_epoch_us(payload.get("source_available_at"))
        ingested_us = _explicit_iso_epoch_us(payload.get("source_ingested_at"))
        generated_us = _explicit_iso_epoch_us(payload.get("generated_at"))
        generated_utc_us = _explicit_iso_epoch_us(payload.get("generated_utc"))
        exact_close_us = latest_close_ms * 1_000
        latest_producer_ms = payload.get("latest_candle_producer_event_time_ms")
        latest_ingested_ms = payload.get("latest_candle_ingested_at_ms")
        latest_available_ms = payload.get("latest_candle_available_at_ms")
        clock_aliases = {
            "source_economic_event_time_ms": latest_close_ms,
            "source_producer_event_time_ms": (
                None if producer_us is None or producer_us % 1_000 else producer_us // 1_000
            ),
            "source_ingested_at_ms": (
                None if ingested_us is None or ingested_us % 1_000 else ingested_us // 1_000
            ),
            "source_available_at_ms": (
                None if available_us is None or available_us % 1_000 else available_us // 1_000
            ),
        }
        if (
            cutoff_us != exact_close_us
            or event_us != exact_close_us
            or source_event_us != exact_close_us
            or producer_us is None
            or ingested_us is None
            or available_us is None
            or generated_us is None
            or generated_utc_us != generated_us
            or payload.get("generated_utc") != payload.get("generated_at")
            or not (event_us <= producer_us <= ingested_us <= available_us <= generated_us)
            or type(latest_producer_ms) is not int
            or type(latest_ingested_ms) is not int
            or type(latest_available_ms) is not int
            or not (
                exact_close_us
                <= latest_producer_ms * 1_000
                <= latest_ingested_ms * 1_000
                <= latest_available_ms * 1_000
                <= generated_us
            )
            # The source clocks are full-window maxima. They may legitimately
            # exceed the latest candle's clocks when an older row was ingested
            # late, but they may never precede their latest-row counterpart.
            or latest_producer_ms * 1_000 > producer_us
            or latest_ingested_ms * 1_000 > ingested_us
            or latest_available_ms * 1_000 > available_us
            or generated_us * 1_000 > observed_ns
            or any(
                expected is None
                or type(payload.get(alias)) is not int
                or payload.get(alias) != expected
                for alias, expected in clock_aliases.items()
            )
        ):
            reasons.append("TA_CAUSAL_CLOCK_ORDER_INVALID")
    source_payload_byte_count = payload.get("source_exact_payload_byte_count")
    source_payload_sha256 = payload.get("source_exact_payload_sha256")
    if (
        type(source_payload_byte_count) is not int
        or source_payload_byte_count <= 0
        or source_payload_byte_count > MAX_SOURCE_PAYLOAD_BYTES
        or type(source_payload_sha256) is not str
        or len(source_payload_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_payload_sha256)
    ):
        reasons.append("TA_EXACT_SOURCE_PAYLOAD_IDENTITY_INVALID")
    return tuple(sorted(set(reasons)))


def _check_symbol_keyed(
    r: redis.Redis,
    key: str,
    *,
    max_age_s: int,
    ts_fields: tuple[str, ...],
    content_rejections: Callable[[Any], tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    payload = _read_json(r, key)
    if payload is None:
        return {"status": "missing", "key": key}
    age_s = _payload_age_seconds(payload, *ts_fields)
    if age_s is None:
        return {"status": "no_timestamp", "key": key}
    if age_s < 0:
        return {"status": "future_timestamp", "key": key}
    if age_s > max_age_s:
        return {"status": "stale", "age_s": int(age_s), "key": key}
    rejections = content_rejections(payload) if content_rejections is not None else ()
    if rejections:
        return {
            "status": "invalid_content",
            "age_s": int(age_s),
            "key": key,
            "content_rejection_reasons": list(rejections),
        }
    return {"status": "ok", "age_s": int(age_s)}


def _check_tf_keyed(
    r: redis.Redis,
    key_template: str,
    symbol: str,
    *,
    grace_s: int,
    ts_fields: tuple[str, ...],
    content_rejections: Callable[[Any, str], tuple[str, ...]] | None = None,
    consumer_bound: bool = True,
    consumer_hold_reason: str | None = None,
) -> dict[str, Any]:
    tfs: dict[str, Any] = {}
    ok_count = 0
    held_count = 0
    for tf in REQUIRED_DECISION_TIMEFRAMES:
        key = key_template.format(symbol=symbol, timeframe=tf)
        payload = _read_json(r, key)
        if payload is None:
            tfs[tf] = {"ok": False, "reason": "missing"}
            continue
        age_s = _payload_age_seconds(payload, *ts_fields)
        max_age = TIMEFRAME_SECONDS.get(tf, 3600) + grace_s
        if age_s is None:
            tfs[tf] = {"ok": False, "reason": "no_timestamp"}
        elif age_s < 0:
            tfs[tf] = {"ok": False, "reason": "future_timestamp"}
        elif age_s > max_age:
            tfs[tf] = {"ok": False, "reason": "stale", "age_s": int(age_s)}
        else:
            rejections = content_rejections(payload, tf) if content_rejections is not None else ()
            if rejections:
                tfs[tf] = {
                    "ok": False,
                    "reason": "invalid_content",
                    "age_s": int(age_s),
                    "content_rejection_reasons": list(rejections),
                }
            elif not consumer_bound:
                held_count += 1
                tfs[tf] = {
                    "ok": False,
                    "reason": "consumer_held",
                    "age_s": int(age_s),
                    "consumer_hold_reason": consumer_hold_reason,
                }
            else:
                tfs[tf] = {"ok": True, "age_s": int(age_s)}
                ok_count += 1
    if ok_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "ok"
    elif held_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "consumer_held"
    else:
        status = "partial" if ok_count or held_count else "missing"
    return {
        "status": status,
        "ok_tfs": ok_count,
        "held_tfs": held_count,
        "tfs": tfs,
    }


def _finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(v)


def _feature_spec_coverage_pct(snapshot: Any) -> float | None:
    """Signal-coverage proxy: FEATURE_SPEC names present with finite values
    in the symbol's latest feature snapshot, as a percent of the trainer
    tensor spec (see hybrid_cuda_trainer/tensor_builder.FEATURE_SPEC)."""
    if not isinstance(snapshot, dict):
        return None
    features = snapshot.get("features")
    if not isinstance(features, dict):
        return None
    spec_names = [name for name, _source in FEATURE_SPEC]
    if not spec_names:
        return None
    available = sum(1 for name in spec_names if _finite(features.get(name)))
    return round(100.0 * available / len(spec_names), 2)


def _check_feature_snapshot(r: redis.Redis, symbol: str) -> dict[str, Any]:
    tfs: dict[str, Any] = {}
    held_count = 0
    ok_count = 0
    primary: dict[str, Any] | None = None
    for tf in REQUIRED_DECISION_TIMEFRAMES:
        key = f"v2:features:latest:{symbol}:{tf}"
        snapshot = _read_json(r, key)
        if not isinstance(snapshot, dict):
            tfs[tf] = {"ok": False, "reason": "missing", "key": key}
            continue
        if tf == "1m":
            primary = snapshot
        age_s = _payload_age_seconds(
            snapshot,
            "generated_utc",
            "generated_at",
            "available_at",
        )
        max_age = TIMEFRAME_SECONDS.get(tf, 3600) + SNAPSHOT_GRACE_S
        if age_s is None:
            tfs[tf] = {"ok": False, "reason": "no_timestamp", "key": key}
            continue
        if age_s < 0:
            tfs[tf] = {"ok": False, "reason": "future_timestamp", "key": key}
            continue
        if age_s > max_age:
            tfs[tf] = {
                "ok": False,
                "reason": "stale",
                "age_s": int(age_s),
                "key": key,
            }
            continue

        features = snapshot.get("features")
        feature_mapping = features if isinstance(features, dict) else {}
        finite_feature_count = sum(_finite(value) for value in feature_mapping.values())
        hold_reasons: list[str] = []
        if snapshot.get("schema_version") != "v2_native_feature_snapshot_v2":
            hold_reasons.append("FEATURE_SNAPSHOT_V2_SCHEMA_REQUIRED")
        if snapshot.get("worker_id") != "v2_feature_pipeline_native_loop":
            hold_reasons.append("FEATURE_SNAPSHOT_WORKER_IDENTITY_INVALID")
        if not isinstance(features, dict) or not features or finite_feature_count == 0:
            hold_reasons.append("FEATURE_VALUES_MISSING")
        if type(snapshot.get("feature_count")) is not int or snapshot.get("feature_count") != len(
            feature_mapping
        ):
            hold_reasons.append("FEATURE_COUNT_CONTRACT_INVALID")
        if not isinstance(snapshot.get("feature_snapshot_id"), str) or not snapshot.get(
            "feature_snapshot_id"
        ):
            hold_reasons.append("FEATURE_SNAPSHOT_ID_REQUIRED")
        for field_name, reason in (
            (
                "required_model_feature_value_contract_valid",
                "REQUIRED_MODEL_FEATURE_VALUE_CONTRACT_INVALID",
            ),
            (
                "required_model_feature_pit_coverage_valid",
                "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED",
            ),
            (
                "ohlcv_history_payload_receipts_valid",
                "IMMUTABLE_OHLCV_HISTORY_PAYLOAD_RECEIPTS_REQUIRED",
            ),
            (
                "exact_feature_availability_valid",
                "FEATURE_PUBLICATION_RECEIPT_REQUIRED",
            ),
            ("trainer_consumable", "TRAINER_CONSUMABLE_FALSE"),
            ("valid_for_prediction", "PREDICTION_CONSUMABLE_FALSE"),
            ("valid_for_paper", "PAPER_CONSUMABLE_FALSE"),
        ):
            if snapshot.get(field_name) is not True:
                hold_reasons.append(reason)
        if not FEATURE_PUBLICATION_RECEIPT_VALIDATOR_BOUND:
            hold_reasons.append(FEATURE_CONSUMER_HOLD_REASON)

        hold_reasons = sorted(set(hold_reasons))
        consumer_ready = not hold_reasons
        if consumer_ready:
            ok_count += 1
            reason = "ok"
        else:
            held_count += 1
            reason = "consumer_held"
        tfs[tf] = {
            "ok": consumer_ready,
            "reason": reason,
            "age_s": int(age_s),
            "key": key,
            "finite_feature_count": finite_feature_count,
            "feature_spec_coverage_pct": _feature_spec_coverage_pct(snapshot),
            "consumer_hold_reasons": hold_reasons,
            "publication_receipt_validator_bound": (FEATURE_PUBLICATION_RECEIPT_VALIDATOR_BOUND),
        }

    if ok_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "ok"
    elif held_count == len(REQUIRED_DECISION_TIMEFRAMES):
        status = "consumer_held"
    else:
        status = "partial" if held_count or ok_count else "missing"
    coverage = _feature_spec_coverage_pct(primary)
    result: dict[str, Any] = {
        "status": status,
        "ok_tfs": ok_count,
        "held_tfs": held_count,
        "tfs": tfs,
        "feature_spec_total": len(FEATURE_SPEC),
        "feature_spec_coverage_pct": coverage,
        "publication_receipt_validator_bound": (FEATURE_PUBLICATION_RECEIPT_VALIDATOR_BOUND),
        "consumer_hold_reason": FEATURE_CONSUMER_HOLD_REASON,
    }
    if isinstance(primary, dict):
        feature_count = primary.get("feature_count")
        feature_count_valid = (
            type(feature_count) is int and 0 <= feature_count <= MAX_REPORTED_FEATURE_COUNT
        )
        result["snapshot_feature_count"] = feature_count if feature_count_valid else None
        result["snapshot_feature_count_valid"] = feature_count_valid
        result["snapshot_freshness_state"] = _bounded_metadata_token(
            primary.get("feature_freshness_state")
        )
    return result


def _check_secondary_sources(r: redis.Redis, symbol: str) -> dict[str, Any]:
    """Provider backups (CoinAnk/KuCoin) as fresh secondary evidence when a
    primary family is degraded. Informational only — never flips a primary
    family to ok."""
    out: dict[str, Any] = {}
    coinank = _read_json(r, f"v2:features:coinank:{symbol}:1h")
    if isinstance(coinank, dict):
        wrapper_age_s = _payload_age_seconds(coinank, "generated_utc")
        source_freshness_value = coinank.get("source_freshness_seconds")
        source_age_s: float | None = None
        if isinstance(source_freshness_value, int | float) and not isinstance(
            source_freshness_value, bool
        ):
            candidate_source_age_s = float(source_freshness_value)
            if math.isfinite(candidate_source_age_s) and candidate_source_age_s >= 0:
                source_age_s = candidate_source_age_s
        out["coinank_1h"] = {
            "fresh": (
                wrapper_age_s is not None
                and 0 <= wrapper_age_s <= SECONDARY_MAX_AGE_S
                and source_age_s is not None
                and source_age_s <= SECONDARY_MAX_AGE_S
            ),
            "age_s": None if source_age_s is None else int(source_age_s),
            "source_freshness_valid": source_age_s is not None,
            "wrapper_age_s": None if wrapper_age_s is None else int(wrapper_age_s),
            "families_present_summary": _bounded_secondary_family_summary(
                coinank.get("families_present")
            ),
        }
    kucoin = _read_json(r, f"v2:features:kucoin:{symbol}:latest")
    if isinstance(kucoin, dict):
        out["kucoin_latest"] = {
            "data_available": bool(kucoin.get("data_available")),
            "orderbook20_present": bool(kucoin.get("orderbook20_present")),
            "klines_present": bool(kucoin.get("klines_present")),
        }
    return out


def _census_symbol(
    r: redis.Redis,
    symbol: str,
    *,
    ohlcv_r: RawRedisSourceClient,
    census_as_of_ns: int,
) -> dict[str, Any]:
    families: dict[str, Any] = {
        "ohlcv_closed": _check_ohlcv_closed(ohlcv_r, symbol),
        "prices": _check_symbol_keyed(
            r,
            f"v2:market:prices:{symbol}",
            max_age_s=PRICES_MAX_AGE_S,
            ts_fields=("fetched_utc", "generated_utc", "timestamp"),
            content_rejections=lambda payload: _price_content_rejections(
                payload,
                symbol,
            ),
        ),
        "orderbook": _check_symbol_keyed(
            r,
            f"v2:market:orderbook:{symbol}",
            max_age_s=ORDERBOOK_MAX_AGE_S,
            ts_fields=("E", "T", "fetched_utc", "generated_utc", "timestamp"),
            content_rejections=lambda payload: _orderbook_content_rejections(
                payload,
                symbol,
            ),
        ),
        "open_interest": _check_symbol_keyed(
            r,
            f"v2:market:open_interest:{symbol}",
            max_age_s=OPEN_INTEREST_MAX_AGE_S,
            ts_fields=("binance_time_ms", "fetched_utc", "generated_utc", "timestamp"),
            content_rejections=lambda payload: _open_interest_content_rejections(
                payload,
                symbol,
            ),
        ),
        "ta_full": _check_tf_keyed(
            r,
            "v2:features:ta_full:{symbol}:{timeframe}",
            symbol,
            grace_s=TA_FULL_GRACE_S,
            ts_fields=("generated_utc",),
            content_rejections=lambda payload, timeframe: _ta_content_rejections(
                payload,
                symbol,
                timeframe,
                census_as_of_ns=census_as_of_ns,
            ),
            consumer_bound=TA_FINALITY_CONSUMER_BOUND,
            consumer_hold_reason=TA_CONSUMER_HOLD_REASON,
        ),
        "feature_snapshot": _check_feature_snapshot(r, symbol),
    }
    families_ok = sum(1 for fam in FAMILIES if families[fam]["status"] == "ok")
    gaps = {
        fam: {
            "status": families[fam]["status"],
            "heal_path": FAMILY_HEAL_PATH[fam],
        }
        for fam in FAMILIES
        if families[fam]["status"] != "ok"
    }
    entry: dict[str, Any] = {
        "families": families,
        "families_ok": families_ok,
        "families_total": len(FAMILIES),
        "fully_covered": families_ok == len(FAMILIES),
    }
    if gaps:
        entry["gaps"] = gaps
        secondary = _check_secondary_sources(r, symbol)
        if secondary:
            entry["secondary_sources"] = secondary
    return entry


def build_census(
    r: redis.Redis,
    symbols: list[str],
    provenance: dict[str, Any],
    *,
    ohlcv_r: RawRedisSourceClient,
) -> dict[str, Any]:
    census_as_of_ns = time.time_ns()
    symbol_snapshot = tuple(symbols[: MAX_CENSUS_SYMBOLS + 1])
    if not 1 <= len(symbol_snapshot) <= MAX_CENSUS_SYMBOLS:
        raise ValueError("universe_coverage_symbol_count_resource_limit")
    if len(set(symbol_snapshot)) != len(symbol_snapshot) or any(
        type(symbol) is not str or not is_valid_runtime_symbol(symbol) for symbol in symbol_snapshot
    ):
        raise ValueError("universe_coverage_symbol_identity_invalid")
    per_symbol: dict[str, Any] = {}
    aggregate_entry_bytes = 0
    for symbol in symbol_snapshot:
        entry = _census_symbol(
            r,
            symbol,
            ohlcv_r=ohlcv_r,
            census_as_of_ns=census_as_of_ns,
        )
        serialized_entry = _bounded_canonical_json(
            entry,
            max_bytes=MAX_CENSUS_SYMBOL_ENTRY_BYTES,
            error_code="universe_coverage_symbol_entry_resource_limit",
        )
        aggregate_entry_bytes += len(serialized_entry.encode("ascii"))
        if aggregate_entry_bytes > MAX_CENSUS_SYMBOL_ENTRIES_AGGREGATE_BYTES:
            raise ValueError("universe_coverage_symbol_entries_aggregate_resource_limit")
        per_symbol[symbol] = entry

    family_summary: dict[str, dict[str, int]] = {
        fam: {
            "ok": 0,
            "partial": 0,
            "missing": 0,
            "stale": 0,
            "no_timestamp": 0,
            "future_timestamp": 0,
            "source_ready_consumer_unbound": 0,
            "consumer_held": 0,
        }
        for fam in FAMILIES
    }
    for entry in per_symbol.values():
        for fam in FAMILIES:
            status = entry["families"][fam]["status"]
            family_summary[fam][status] = family_summary[fam].get(status, 0) + 1

    gap_symbols = sorted(sym for sym, entry in per_symbol.items() if not entry["fully_covered"])
    coverages = [
        entry["families"]["feature_snapshot"].get("feature_spec_coverage_pct")
        for entry in per_symbol.values()
    ]
    coverages = [c for c in coverages if isinstance(c, int | float)]
    return {
        "schema_version": SCHEMA_VERSION,
        "worker_id": WORKER_ID,
        "generated_utc": _utc_iso(),
        "census_as_of_utc": _utc_iso(census_as_of_ns / 1_000_000_000),
        "universe_count": len(symbol_snapshot),
        "universe_source": _bounded_metadata_token(provenance.get("source_path")),
        "universe_profile": _bounded_metadata_token(provenance.get("symbol_profile")),
        "timeframes": list(REQUIRED_DECISION_TIMEFRAMES),
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "ohlcv_coverage_semantics": OHLCV_COVERAGE_SEMANTICS,
        "ohlcv_market_selection_threshold": False,
        "ohlcv_consumer_selection_bound": OHLCV_CONSUMER_SELECTION_BOUND,
        "ohlcv_consumer_hold_reason": OHLCV_CONSUMER_HOLD_REASON,
        "feature_spec_total": len(FEATURE_SPEC),
        "feature_publication_receipt_validator_bound": (
            FEATURE_PUBLICATION_RECEIPT_VALIDATOR_BOUND
        ),
        "feature_consumer_hold_reason": FEATURE_CONSUMER_HOLD_REASON,
        "ta_finality_consumer_bound": TA_FINALITY_CONSUMER_BOUND,
        "ta_consumer_hold_reason": TA_CONSUMER_HOLD_REASON,
        "feature_spec_coverage_method": (
            "snapshot_features_only: FEATURE_SPEC names with finite values in "
            "v2:features:latest:{sym}:1m features dict. Lower bound — the "
            "trainer tensor builder merges ~25 additional payload families "
            "at build time, so true tensor coverage is >= this value."
        ),
        "thresholds": {
            "prices_max_age_s": PRICES_MAX_AGE_S,
            "orderbook_max_age_s": ORDERBOOK_MAX_AGE_S,
            "open_interest_max_age_s": OPEN_INTEREST_MAX_AGE_S,
            "ta_full_grace_s": TA_FULL_GRACE_S,
            "snapshot_grace_s": SNAPSHOT_GRACE_S,
        },
        "summary": {
            "families": family_summary,
            "symbols_fully_covered": len(symbol_snapshot) - len(gap_symbols),
            "symbols_with_gaps": len(gap_symbols),
            "gap_symbols": gap_symbols,
            "feature_spec_coverage_pct_avg": (
                round(sum(coverages) / len(coverages), 2) if coverages else None
            ),
        },
        "heal_paths": dict(FAMILY_HEAL_PATH),
        "symbols": per_symbol,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
    }


# ---------------------------------------------------------------------------
# Healing: closed-candle backfill (budget-aware)
# ---------------------------------------------------------------------------


def heal_ohlcv_gaps(
    ohlcv_r: RawRedisSourceClient,
    census: dict[str, Any],
    *,
    max_pairs: int,
    dry_run: bool = False,
    replace_invalid_existing: bool = False,
) -> dict[str, Any]:
    if type(dry_run) is not bool or type(replace_invalid_existing) is not bool:
        raise ValueError("universe_coverage_heal_authority_flags_invalid")
    if type(max_pairs) is not int or not 0 <= max_pairs <= MAX_COVERAGE_BACKFILL_PAIRS_PER_RUN:
        raise ValueError("universe_coverage_max_backfill_pairs_resource_limit")
    if not dry_run and max_pairs == 0:
        raise ValueError("universe_coverage_max_backfill_pairs_zero_requires_no_backfill")
    pairs: list[tuple[str, str]] = []
    for symbol, entry in census["symbols"].items():
        tfs = entry["families"]["ohlcv_closed"]["tfs"]
        for tf, tf_entry in tfs.items():
            if tf_entry.get("source_window_recovery_ready") is not True:
                pairs.append((symbol, tf))

    result: dict[str, Any] = {
        "gap_pairs_found": len(pairs),
        "max_pairs_per_run": max_pairs,
        "attempted": 0,
        "writes_committed": 0,
        "cache_ready_after": 0,
        "unresolved_after_attempt": 0,
        "errors": 0,
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_budget_exhausted": False,
        # Number of otherwise-eligible pairs left for a later timer window,
        # including the pair rejected by the pre-request budget guard.
        "deferred_due_to_budget": 0,
        "completion_status": "dry_run" if dry_run else "complete",
        "terminal_error_code": None,
        "skipped_pairs": max(0, len(pairs) - max_pairs),
        "dry_run": dry_run,
        "replace_invalid_existing_authorized": replace_invalid_existing,
        "details": [],
    }
    if dry_run or not pairs:
        return result

    for symbol, tf in pairs[:max_pairs]:
        result["attempted"] += 1
        try:
            outcome = _backfill_symbol_tf(
                ohlcv_r,
                symbol,
                tf,
                replace_invalid_existing=replace_invalid_existing,
            )
            write_committed = outcome.get("write_committed") is True
            cache_ready_after = outcome.get("cache_ready_after") is True
            if write_committed:
                result["writes_committed"] += 1
            if cache_ready_after:
                result["cache_ready_after"] += 1
            else:
                result["unresolved_after_attempt"] += 1
            if write_committed and cache_ready_after:
                status = "write_committed_cache_ready"
            elif write_committed:
                status = "write_committed_cache_still_nonready"
            elif cache_ready_after:
                status = "cache_ready_no_write"
            else:
                status = "unresolved_no_write"
            result["details"].append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "status": status,
                    "recovery_status": outcome.get("recovery_status"),
                    "write_committed": write_committed,
                    "cache_ready_after": cache_ready_after,
                    "rows_submitted": outcome.get("rows_submitted"),
                    "total_in_key": outcome.get("total_in_key"),
                    "transport": outcome.get("transport"),
                    "invalid_existing_replaced": outcome.get("invalid_existing_replaced"),
                }
            )
        except Exception as exc:  # noqa: BLE001 — census must survive any pair failure
            if type(
                exc
            ) is KlineBackfillRestBudgetDeferred and _consume_factory_issued_rest_budget_deferral(
                exc
            ):
                eligible_pair_count = min(len(pairs), max_pairs)
                result["rest_budget_exhausted"] = True
                result["deferred_due_to_budget"] = max(
                    1,
                    eligible_pair_count - result["attempted"] + 1,
                )
                result["completion_status"] = "partial_deferred_budget"
                result["details"].append(
                    {
                        "symbol": symbol,
                        "tf": tf,
                        "status": "deferred_rest_budget",
                        "error_code": REST_BUDGET_EXHAUSTED_ERROR_CODE,
                        "write_committed": False,
                        "cache_ready_after": False,
                    }
                )
                # The current pair reached the shared guard but performed no
                # REST work. Do not call the backfill for later pairs in this
                # window; the timer will resume from fresh source evidence.
                result["skipped_pairs"] = len(pairs) - result["attempted"]
                break
            # A typed-but-unregistered/replayed/mutated capability is an
            # internal integrity failure. Never render its attacker-mutable
            # BaseException.args while producing operator-safe status.
            typed_integrity_failure = isinstance(exc, KlineBackfillRestBudgetDeferred)
            error_code = (
                "kline_backfill_internal_error"
                if typed_integrity_failure
                else _stable_error_code(exc)
            )
            result["errors"] += 1
            result["details"].append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "status": "error",
                    "error_code": error_code,
                    "write_committed": False,
                    "cache_ready_after": False,
                }
            )
            if typed_integrity_failure or error_code in TERMINAL_REST_RECOVERY_ERROR_CODES:
                # Authority/cooldown persistence failures are terminal for
                # this run and must remain visible as process failures.
                result["terminal_error_code"] = error_code
                result["skipped_pairs"] = len(pairs) - result["attempted"]
                break
        time.sleep(BACKFILL_SLEEP_SECONDS)
    if result["errors"] or result["unresolved_after_attempt"]:
        result["completion_status"] = "failed"
    elif result["rest_budget_exhausted"]:
        result["completion_status"] = "partial_deferred_budget"
    elif result["skipped_pairs"]:
        result["completion_status"] = "partial_pair_cap"
    return result


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def _load_previous_summary(r: redis.Redis) -> dict[str, Any] | None:
    previous = _read_json(r, CENSUS_REDIS_KEY)
    if not isinstance(previous, dict):
        return None
    age_s = _payload_age_seconds(previous, "generated_utc")
    if age_s is None or age_s < 0 or age_s > PREVIOUS_CENSUS_MAX_AGE_SECONDS:
        # Cache-echo gate: never trust our own stale output.
        return None
    return {
        "generated_utc": previous.get("generated_utc"),
        "age_s": int(age_s),
        "summary": previous.get("summary"),
    }


def publish_census(r: redis.Redis, census: dict[str, Any]) -> None:
    payload = _bounded_canonical_json(
        census,
        max_bytes=MAX_CENSUS_PAYLOAD_BYTES,
        error_code="universe_coverage_census_payload_resource_limit",
    )
    r.set(CENSUS_REDIS_KEY, payload, ex=CENSUS_TTL_SECONDS)


def write_status_file(
    census: dict[str, Any],
    heal: dict[str, Any],
    *,
    status_file: Path | None = None,
) -> None:
    """Compact operator status (summary only; full census lives in Redis)."""
    target = STATUS_FILE if status_file is None else status_file
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "v2_universe_coverage_sync_status_v1",
            "worker_id": WORKER_ID,
            "generated_utc": census["generated_utc"],
            "universe_count": census["universe_count"],
            "summary": census["summary"],
            "backfill": {k: v for k, v in heal.items() if k != "details"},
            "census_redis_key": CENSUS_REDIS_KEY,
            "live_gate": "blocked_human_only",
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    except OSError as exc:
        print(f"[{WORKER_ID}] WARN status file write failed: {exc}")


def _coverage_run_exit_code(heal: dict[str, Any]) -> int:
    return 1 if heal.get("errors", 0) or heal.get("unresolved_after_attempt", 0) else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated explicit symbols (default: resolved runtime universe).",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="Census only; do not invoke the closed-candle backfill.",
    )
    parser.add_argument(
        "--max-backfill-pairs",
        type=int,
        default=MAX_BACKFILL_PAIRS_DEFAULT,
        help="Cap on (symbol, timeframe) backfill pairs per run (default: %(default)s).",
    )
    parser.add_argument(
        "--replace-invalid-existing",
        action="store_true",
        help=(
            "Explicitly authorize atomic replacement of invalid existing "
            "closed-window values. Default healing fails closed."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full after-census JSON to stdout.",
    )
    parser.add_argument(
        "--status-file",
        type=_absolute_status_file,
        default=os.environ.get(STATUS_FILE_ENV_VAR) or str(STATUS_FILE),
        help=(
            "Absolute operator-status output path (default: "
            f"${STATUS_FILE_ENV_VAR} or the repository public path)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    r = _redis_client()
    ohlcv_r = _ohlcv_binary_redis_client()

    explicit = None
    if args.symbols:
        explicit = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    provenance = resolve_symbols_with_provenance(explicit=explicit)
    symbols = list(provenance["symbols"])
    print(
        f"[{WORKER_ID}] universe={len(symbols)} symbols "
        f"(profile={provenance.get('symbol_profile')}) "
        f"rest_fallback_allowed={binance_rest_fallback_allowed()}"
    )

    previous = _load_previous_summary(r)

    census_before = build_census(r, symbols, provenance, ohlcv_r=ohlcv_r)
    before_summary = census_before["summary"]
    print(
        f"[{WORKER_ID}] BEFORE: fully_covered="
        f"{before_summary['symbols_fully_covered']}/{len(symbols)} "
        f"gaps={before_summary['symbols_with_gaps']}"
    )
    for fam in FAMILIES:
        print(f"  {fam}: {before_summary['families'][fam]}")

    heal = heal_ohlcv_gaps(
        ohlcv_r,
        census_before,
        max_pairs=int(args.max_backfill_pairs),
        dry_run=bool(args.no_backfill),
        replace_invalid_existing=bool(args.replace_invalid_existing),
    )
    print(
        f"[{WORKER_ID}] backfill: pairs_found={heal['gap_pairs_found']} "
        f"attempted={heal['attempted']} "
        f"writes_committed={heal['writes_committed']} "
        f"cache_ready_after={heal['cache_ready_after']} "
        f"unresolved={heal['unresolved_after_attempt']} "
        f"errors={heal['errors']} "
        f"budget_exhausted={heal['rest_budget_exhausted']} "
        f"deferred_due_to_budget={heal['deferred_due_to_budget']} "
        f"status={heal['completion_status']}"
    )

    # After-census re-reads Redis only (cheap) so the published census
    # reflects the post-heal state within the same run.
    census_after = build_census(r, symbols, provenance, ohlcv_r=ohlcv_r)
    census_after["backfill"] = {k: v for k, v in heal.items() if k != "details"}
    census_after["backfill_details"] = heal["details"][:200]
    census_after["previous_run"] = previous
    census_after["before_this_run"] = {
        "generated_utc": census_before["generated_utc"],
        "summary": before_summary,
    }

    publish_census(r, census_after)
    write_status_file(census_after, heal, status_file=args.status_file)

    after_summary = census_after["summary"]
    print(
        f"[{WORKER_ID}] AFTER: fully_covered="
        f"{after_summary['symbols_fully_covered']}/{len(symbols)} "
        f"gaps={after_summary['symbols_with_gaps']}"
    )
    for fam in FAMILIES:
        print(f"  {fam}: {after_summary['families'][fam]}")
    print(f"[{WORKER_ID}] census published to {CENSUS_REDIS_KEY} (ttl={CENSUS_TTL_SECONDS}s)")

    if args.json:
        print(json.dumps(census_after, indent=2, sort_keys=True, default=str))
    return _coverage_run_exit_code(heal)


if __name__ == "__main__":
    raise SystemExit(main())
