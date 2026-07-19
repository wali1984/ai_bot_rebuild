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
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import redis  # noqa: E402

from v2.backend.app.cli.v2_binance_kline_rest_backfill import (  # noqa: E402
    _backfill_symbol_tf,
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
BACKFILL_SLEEP_SECONDS = 0.15

# Resource-reporting bound only. The exact schema parser and transport enforce
# their own fixed row/byte ABI limits; this merely prevents a large universe
# census from repeating every gap index in its published JSON.
MAX_REPORTED_OHLCV_GAPS = 32
OHLCV_COVERAGE_SEMANTICS = (
    "CORE_TA_MINIMUM_COVERAGE_FLOOR_NOT_EXACT_DEPENDENCY_LENGTH_"
    "NOT_MARKET_SELECTION_OR_TRAINER_ADMISSION"
)

STATUS_FILE = (
    _repo / "v2/frontend/public/operator_runtime/v2_universe_coverage_sync/latest/"
    "v2_universe_coverage_sync_status.json"
)


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


def _read_json(r: redis.Redis, key: str) -> Any:
    try:
        raw = cast(str | bytes | bytearray | None, r.get(key))
    except redis.RedisError:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _parse_ts_seconds(value: Any) -> float | None:
    """Parse epoch s/ms or ISO-8601 (Z or offset) into epoch seconds."""
    if value is None:
        return None
    if isinstance(value, int | float):
        v = float(value)
        if v <= 0:
            return None
        # Heuristic: epoch ms vs s.
        return v / 1000.0 if v > 1e11 else v
    text = str(value).strip()
    if not text:
        return None
    try:
        v = float(text)
        return v / 1000.0 if v > 1e11 else v
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except ValueError:
        return None


def _payload_age_seconds(payload: Any, *fields: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for field in fields:
        ts = _parse_ts_seconds(payload.get(field))
        if ts is not None:
            return max(0.0, time.time() - ts)
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

        if inspection.tail_missing_interval_count != 0:
            status = "tail_stale"
        elif inspection.contiguous_suffix_count < CORE_TA_MINIMUM_SOURCE_ROWS:
            status = "contiguous_suffix_short"
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
        )
        if status == "ok":
            ok_count += 1
        tfs[tf] = entry
    status = (
        "ok"
        if ok_count == len(REQUIRED_DECISION_TIMEFRAMES)
        else ("partial" if ok_count else "missing")
    )
    return {
        "status": status,
        "ok_tfs": ok_count,
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "coverage_semantics": OHLCV_COVERAGE_SEMANTICS,
        "market_selection_threshold": False,
        "tfs": tfs,
    }


def _check_symbol_keyed(
    r: redis.Redis,
    key: str,
    *,
    max_age_s: int,
    ts_fields: tuple[str, ...],
) -> dict[str, Any]:
    payload = _read_json(r, key)
    if payload is None:
        return {"status": "missing", "key": key}
    age_s = _payload_age_seconds(payload, *ts_fields)
    if age_s is None:
        return {"status": "no_timestamp", "key": key}
    if age_s > max_age_s:
        return {"status": "stale", "age_s": int(age_s), "key": key}
    return {"status": "ok", "age_s": int(age_s)}


def _check_tf_keyed(
    r: redis.Redis,
    key_template: str,
    symbol: str,
    *,
    grace_s: int,
    ts_fields: tuple[str, ...],
) -> dict[str, Any]:
    tfs: dict[str, Any] = {}
    ok_count = 0
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
        elif age_s > max_age:
            tfs[tf] = {"ok": False, "reason": "stale", "age_s": int(age_s)}
        else:
            tfs[tf] = {"ok": True, "age_s": int(age_s)}
            ok_count += 1
    status = (
        "ok"
        if ok_count == len(REQUIRED_DECISION_TIMEFRAMES)
        else ("partial" if ok_count else "missing")
    )
    return {"status": status, "ok_tfs": ok_count, "tfs": tfs}


def _finite(value: Any) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return v == v and v not in (float("inf"), float("-inf"))


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
    result = _check_tf_keyed(
        r,
        "v2:features:latest:{symbol}:{timeframe}",
        symbol,
        grace_s=SNAPSHOT_GRACE_S,
        ts_fields=("generated_utc", "generated_at", "available_at"),
    )
    primary = _read_json(r, f"v2:features:latest:{symbol}:1m")
    coverage = _feature_spec_coverage_pct(primary)
    result["feature_spec_total"] = len(FEATURE_SPEC)
    result["feature_spec_coverage_pct"] = coverage
    if isinstance(primary, dict):
        result["snapshot_feature_count"] = primary.get("feature_count")
        result["snapshot_freshness_state"] = primary.get("feature_freshness_state")
    return result


def _check_secondary_sources(r: redis.Redis, symbol: str) -> dict[str, Any]:
    """Provider backups (CoinAnk/KuCoin) as fresh secondary evidence when a
    primary family is degraded. Informational only — never flips a primary
    family to ok."""
    out: dict[str, Any] = {}
    coinank = _read_json(r, f"v2:features:coinank:{symbol}:1h")
    if isinstance(coinank, dict):
        age_s = _payload_age_seconds(coinank, "generated_utc")
        out["coinank_1h"] = {
            "fresh": age_s is not None and age_s <= SECONDARY_MAX_AGE_S,
            "age_s": None if age_s is None else int(age_s),
            "families_present": coinank.get("families_present"),
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
) -> dict[str, Any]:
    families: dict[str, Any] = {
        "ohlcv_closed": _check_ohlcv_closed(ohlcv_r, symbol),
        "prices": _check_symbol_keyed(
            r,
            f"v2:market:prices:{symbol}",
            max_age_s=PRICES_MAX_AGE_S,
            ts_fields=("fetched_utc", "generated_utc", "timestamp"),
        ),
        "orderbook": _check_symbol_keyed(
            r,
            f"v2:market:orderbook:{symbol}",
            max_age_s=ORDERBOOK_MAX_AGE_S,
            ts_fields=("E", "T", "fetched_utc", "generated_utc", "timestamp"),
        ),
        "open_interest": _check_symbol_keyed(
            r,
            f"v2:market:open_interest:{symbol}",
            max_age_s=OPEN_INTEREST_MAX_AGE_S,
            ts_fields=("binance_time_ms", "fetched_utc", "generated_utc", "timestamp"),
        ),
        "ta_full": _check_tf_keyed(
            r,
            "v2:features:ta_full:{symbol}:{timeframe}",
            symbol,
            grace_s=TA_FULL_GRACE_S,
            ts_fields=("generated_utc",),
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
    per_symbol: dict[str, Any] = {}
    for symbol in symbols:
        per_symbol[symbol] = _census_symbol(r, symbol, ohlcv_r=ohlcv_r)

    family_summary: dict[str, dict[str, int]] = {
        fam: {"ok": 0, "partial": 0, "missing": 0, "stale": 0, "no_timestamp": 0}
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
        "universe_count": len(symbols),
        "universe_source": provenance.get("source_path"),
        "universe_profile": provenance.get("symbol_profile"),
        "timeframes": list(REQUIRED_DECISION_TIMEFRAMES),
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "ohlcv_coverage_semantics": OHLCV_COVERAGE_SEMANTICS,
        "ohlcv_market_selection_threshold": False,
        "feature_spec_total": len(FEATURE_SPEC),
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
            "symbols_fully_covered": len(symbols) - len(gap_symbols),
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
    pairs: list[tuple[str, str]] = []
    for symbol, entry in census["symbols"].items():
        tfs = entry["families"]["ohlcv_closed"]["tfs"]
        for tf, tf_entry in tfs.items():
            if not tf_entry.get("ok"):
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
            error_code = _stable_error_code(exc)
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
            if error_code in {
                "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION",
                "REST_FALLBACK_COOLDOWN_BAN_PROTECTION",
                "REST_FALLBACK_COOLDOWN_PERSISTENT_KEY_FAIL_CLOSED",
                "REST_FALLBACK_SHARED_BUDGET_UNAVAILABLE",
                "kline_backfill_http_rate_or_ban_limit",
            }:
                # Shared host-wide budget spent: skip the rest of this
                # cycle; the 15-minute timer retries with a fresh window.
                result["rest_budget_exhausted"] = True
                result["skipped_pairs"] = len(pairs) - result["attempted"]
                break
        time.sleep(BACKFILL_SLEEP_SECONDS)
    return result


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def _load_previous_summary(r: redis.Redis) -> dict[str, Any] | None:
    previous = _read_json(r, CENSUS_REDIS_KEY)
    if not isinstance(previous, dict):
        return None
    age_s = _payload_age_seconds(previous, "generated_utc")
    if age_s is None or age_s > PREVIOUS_CENSUS_MAX_AGE_SECONDS:
        # Cache-echo gate: never trust our own stale output.
        return None
    return {
        "generated_utc": previous.get("generated_utc"),
        "age_s": int(age_s),
        "summary": previous.get("summary"),
    }


def publish_census(r: redis.Redis, census: dict[str, Any]) -> None:
    r.set(CENSUS_REDIS_KEY, json.dumps(census, sort_keys=True, default=str), ex=CENSUS_TTL_SECONDS)


def write_status_file(census: dict[str, Any], heal: dict[str, Any]) -> None:
    """Compact operator status (summary only; full census lives in Redis)."""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
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
        STATUS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    except OSError as exc:
        print(f"[{WORKER_ID}] WARN status file write failed: {exc}")


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
        max_pairs=max(0, int(args.max_backfill_pairs)),
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
        f"budget_exhausted={heal['rest_budget_exhausted']}"
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
    write_status_file(census_after, heal)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
