"""V2 native feature pipeline live loop (paper/shadow, V2 namespace).

Consumes v2:market:prices:* / v2:market:funding:* /
v2:market:open_interest:* / v2:market:long_short:*
and emits v2:features:latest:{symbol}:{tf} + v2:features:snapshots
and the on-disk trainer-candidate snapshot (admission remains fail-closed
until immutable publication evidence is validated).

Writes V2 namespace ONLY. No legacy Redis. No exchange mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.adaptive_capital_allocator.contracts import AllocationInput
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _atr as _ta_atr,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _ema as _ta_ema,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _macd as _ta_macd,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _orderbook_imbalance as _ta_orderbook_imbalance,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _rsi as _ta_rsi,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _sma as _ta_sma,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
)
from v2.backend.app.services.market_structure import (
    compute_cvd_features,
    compute_fvg,
    compute_liquidity_zones,
    compute_structure,
    compute_volume_profile,
    compute_vwap_features,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    AtomicRedisSourceReadError,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    feature_requirement_classes_for_names,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    CANDLE_ID_CHAIN_VERSION,
    FeatureWindowContractError,
    bind_full_contiguous_core_ta_input,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    OHLCVClosedWindowValidationError,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

V2_REDIS_PREFIX = "v2:"
DEFAULT_TF = "1m"
DEFAULT_TIMEFRAMES = REQUIRED_DECISION_TIMEFRAMES
OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION = "v2_feature_ohlcv_consumer_selection_v1"
LEGACY_RL_OBSERVATION_CORE_FIELDS = (
    "ret_pct",
    "log_return",
    "range_pct",
    "body_pct",
    "true_range_pct",
    "gap_pct",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_width_pct",
    "htf_ret_pct",
    "htf_rsi_14",
    "bid_ask_spread_bps",
    "depth_imbalance",
    "micro_price",
    "toxicity_proxy",
    "funding_rate",
    "oi_change_pct",
    "last_liq_bps_24h",
    "paper_position_present",
)
_ORDERED_TRAINER_FEATURE_NAMES = tuple(name for name, _source in FEATURE_SPEC)
_ORDERED_TRAINER_FEATURE_REQUIREMENTS = feature_requirement_classes_for_names(
    _ORDERED_TRAINER_FEATURE_NAMES
)
TRAINER_REQUIRED_FEATURE_FIELDS = tuple(
    name
    for name, requirement in zip(
        _ORDERED_TRAINER_FEATURE_NAMES,
        _ORDERED_TRAINER_FEATURE_REQUIREMENTS,
        strict=True,
    )
    if requirement == "REQUIRED"
)
TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS = tuple(
    name
    for name, requirement in zip(
        _ORDERED_TRAINER_FEATURE_NAMES,
        _ORDERED_TRAINER_FEATURE_REQUIREMENTS,
        strict=True,
    )
    if requirement == "OPTIONAL_EVENT_DEPENDENT"
)
CORE_MARKET_COST_EVIDENCE_FIELDS = (
    "fee_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
    "actual_observed_spread_entry_bps",
    "bid_depth_usd",
    "ask_depth_usd",
    "orderbook_depth_usd",
    "_fee_bps_source",
    "_expected_slippage_source",
)
# Enrichment must never replace the legacy core values computed from the exact
# market inputs selected for this snapshot or its market-cost evidence.  This
# protection list is intentionally separate from the 446-slot tensor ABI:
# many other required/optional slots are assembled from their own V2 sources,
# but none is trainer-consumable until the immutable PIT ledger binds it.
EXTERNAL_ENRICHMENT_RESERVED_FIELDS = frozenset(
    (*LEGACY_RL_OBSERVATION_CORE_FIELDS, *CORE_MARKET_COST_EVIDENCE_FIELDS)
)
FEATURE_LATEST_TTL_SECONDS = 600
PAPER_POSITIONS_SOURCE_KEY = f"{V2_REDIS_PREFIX}paper:positions"
# 12h default. Audit found ~644K resident snapshot keys (prior OOM was at ~370K)
# because a legacy 30d TTL backlog was still draining and 24h steady-state sat near
# the OOM threshold. Trust reconstruction has a self-contained fallback for expired
# snapshots, so a shorter TTL is safe and bounds memory well below OOM. Env-tunable.
FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS = int(
    os.getenv("V2_FEATURE_SNAPSHOT_TTL_SECONDS", str(12 * 60 * 60)) or 12 * 60 * 60
)
CONFIGURED_FEE_BPS_SOURCE = (
    "CONFIGURED_PAPER_FEE_SCHEDULE:"
    "adaptive_capital_allocator.AllocationInput.fee_bps"
)
DIRECT_ORDERBOOK_ALIASES = (
    ("ob_best_bid", ("ob_best_bid", "best_bid", "bid")),
    ("ob_best_ask", ("ob_best_ask", "best_ask", "ask")),
    ("ob_mid_price", ("ob_mid_price", "bid_ask_mid", "mid", "mid_price")),
    ("bid_ask_mid", ("bid_ask_mid", "mid", "mid_price")),
    ("best_bid_size", ("best_bid_size", "bid_size")),
    ("best_ask_size", ("best_ask_size", "ask_size")),
    ("ob_spread_bps", ("ob_spread_bps", "spread_bps", "bid_ask_spread_bps")),
    ("spread_bps", ("spread_bps", "bid_ask_spread_bps", "ob_spread_bps")),
    ("orderbook_spread_bps", ("orderbook_spread_bps", "spread_bps", "bid_ask_spread_bps")),
    ("ob_imbalance", ("ob_imbalance", "orderbook_imbalance", "depth_imbalance")),
    ("orderbook_depth_imbalance", ("orderbook_depth_imbalance", "depth_imbalance", "orderbook_imbalance")),
    (
        "depth_imbalance",
        (
            "depth_imbalance",
            "ob_imbalance",
            "orderbook_depth_imbalance",
            "orderbook_imbalance",
        ),
    ),
    ("bid_depth_usd", ("bid_depth_usd", "depth_5_bid_usd")),
    ("ask_depth_usd", ("ask_depth_usd", "depth_5_ask_usd")),
    ("orderbook_depth_usd", ("orderbook_depth_usd", "depth_total_usd", "depth_usd")),
    ("depth_total_usd", ("depth_total_usd", "orderbook_depth_usd", "depth_usd")),
    ("depth_usd", ("depth_usd", "depth_total_usd", "orderbook_depth_usd")),
    ("depth_5_bid_usd", ("depth_5_bid_usd",)),
    ("depth_5_ask_usd", ("depth_5_ask_usd",)),
    ("depth_20_bid_usd", ("depth_20_bid_usd",)),
    ("depth_20_ask_usd", ("depth_20_ask_usd",)),
    ("depth_slope", ("depth_slope",)),
    ("estimated_price_impact_bps", ("estimated_price_impact_bps", "price_impact_bps")),
    ("update_age_ms", ("update_age_ms",)),
    ("sequence_gap_flag", ("sequence_gap_flag", "sequence_gap")),
    ("source_latency_ms", ("source_latency_ms", "feed_speed_ms")),
    ("microstructure_liquidity_depth", ("microstructure_liquidity_depth", "depth_total_usd", "orderbook_depth_usd")),
    ("microprice", ("microprice", "bid_ask_mid", "mid", "mid_price")),
)
MICROSTRUCTURE_FEATURE_FIELDS = (
    "microstructure_trust_score",
    "orderbook_trust_score",
    "feed_latency_ms",
    "orderbook_latency_ms",
    "spread_instability",
    "depth_persistence",
    "book_depth_persistence_score",
    "cancel_pressure",
    "book_cancel_pressure_score",
    "book_trade_divergence",
    "cross_venue_confirmation",
    "cross_venue_confirmation_score",
    "sweep_risk",
    "sweep_risk_score",
    "post_sweep_reversal_probability",
    "realized_slippage_error",
    "liquidation_cascade_risk",
    "liquidation_zone_risk_score",
)
ALTDATA_SYMBOL_SCORE_FIELDS = (
    "altdata_symbol_score",
    "provider_availability_score",
    "altdata_freshness_score",
    "coingecko_discovery_score",
    "coingecko_liquidity_score",
    "coingecko_momentum_score",
    "surf_market_price_signal_score",
    "coinglass_derivatives_score",
    "public_intel_score",
    "defillama_liquidity_score",
    "defillama_tvl_momentum_score",
    "fear_greed_score",
    "btc_mempool_pressure_score",
    "news_attention_score",
    "news_sentiment_score",
    "whale_wall_score",
    "whale_bid_pressure_score",
    "whale_ask_pressure_score",
    "whale_wall_imbalance_score",
    "whale_wall_count_score",
    "whale_wall_event_count",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "whale_total_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
)
PUBLIC_INTEL_FEATURE_FIELDS = (
    "public_intel_score",
    "defillama_liquidity_score",
    "defillama_tvl_momentum_score",
    "fear_greed_score",
    "btc_mempool_pressure_score",
    "news_attention_score",
    "news_sentiment_score",
)
WHALE_WALL_FEATURE_FIELDS = (
    "whale_wall_score",
    "whale_bid_pressure_score",
    "whale_ask_pressure_score",
    "whale_wall_imbalance_score",
    "whale_wall_count_score",
    "whale_wall_event_count",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "whale_total_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
)
DERIVED_ALTDATA_ALIASES = (
    ("coingecko_score", ("coingecko_score", "coingecko_discovery_score")),
    ("surf_score", ("surf_score", "surf_market_price_signal_score")),
    ("defillama_score", ("defillama_score", "defillama_liquidity_score")),
    ("fear_greed_context", ("fear_greed_context", "fear_greed_score")),
    ("mempool_context", ("mempool_context", "btc_mempool_pressure_score")),
)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json"
)
SNAPSHOT_PATH = REPO_ROOT / "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ms_to_utc_iso(value: int | float) -> str:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _parse_time_ms(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            numeric = int(value)
        except (OSError, OverflowError, ValueError):
            return None
        resolved = numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        try:
            _ms_to_utc_iso(resolved)
        except (OSError, OverflowError, ValueError):
            return None
        return resolved
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = int(float(text))
            resolved = (
                numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
            )
            _ms_to_utc_iso(resolved)
            return resolved
        except (OSError, OverflowError, ValueError):
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
            except (OSError, OverflowError, ValueError):
                return None
    return None


def _timeframe_ms(value: str) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 60_000
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return 60_000
    if unit == "m":
        return amount * 60_000
    if unit == "h":
        return amount * 3_600_000
    if unit == "d":
        return amount * 86_400_000
    return 60_000


def _closed_candle_is_stale(*, close_ms: int | None, decision_ms: int, timeframe: str) -> bool:
    if close_ms is None:
        return True
    max_age_ms = _timeframe_ms(timeframe) + 120_000
    return int(decision_ms) - int(close_ms) > max_age_ms


def _expected_latest_finalized_close_ms(*, decision_ms: int, timeframe: str) -> int:
    interval_ms = _timeframe_ms(timeframe)
    return (int(decision_ms) // interval_ms) * interval_ms - 1


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _connect_ohlcv_binary_redis():
    """Return the raw Redis client required by the exact OHLCV transport."""

    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        return redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=False,
        )
    except Exception:
        return None


def _ohlcv_binary_client_for(redis_client):
    """Reuse an already-raw client, otherwise create a dedicated binary view."""

    if redis_client is None:
        return None
    if redis_client is not None:
        try:
            connection_kwargs = redis_client.get_connection_kwargs()
        except Exception:
            connection_kwargs = None
        if (
            type(connection_kwargs) is dict
            and connection_kwargs.get("decode_responses") is False
        ):
            return redis_client
    return _connect_ohlcv_binary_redis()


def _safe_write(r, key: str, value: str, ex: int | None = None) -> bool:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


def _valid_paper_position_symbol(value: object) -> bool:
    return (
        type(value) is str
        and 3 <= len(value) <= 32
        and value.isascii()
        and value.isalnum()
        and value == value.upper()
    )


def _read_paper_position_presence(
    r,
    symbols: tuple[str, ...],
) -> tuple[dict[str, int] | None, str, int | None]:
    """Read the canonical paper position list once and derive binary presence.

    This validates only the payload's value contract. It does not establish
    when the mutable Redis value became available and therefore cannot satisfy
    the required-model-feature PIT ledger.
    """
    if any(not _valid_paper_position_symbol(symbol) for symbol in symbols):
        return None, "INVALID_REQUESTED_SYMBOL", None
    if r is None:
        return None, "REDIS_UNAVAILABLE", None
    try:
        raw = r.get(PAPER_POSITIONS_SOURCE_KEY)
    except Exception:
        return None, "READ_ERROR", None
    if raw is None:
        return None, "SOURCE_MISSING", None
    if type(raw) is bytes:
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, "INVALID_UTF8", None
    elif type(raw) is str:
        text = raw
    else:
        return None, "INVALID_PAYLOAD_TYPE", None
    if not text:
        return None, "SOURCE_EMPTY", None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return None, "INVALID_JSON", None
    if type(payload) is not list:
        return None, "PAYLOAD_NOT_LIST", None

    open_symbols: set[str] = set()
    for row in payload:
        if type(row) is not dict:
            return None, "ROW_NOT_MAPPING", None
        symbol = row.get("symbol")
        if not _valid_paper_position_symbol(symbol):
            return None, "ROW_SYMBOL_INVALID", None
        open_symbols.add(symbol)
    status = "VALID_EMPTY_LIST" if not payload else "VALID_POSITION_LIST"
    return (
        {symbol: int(symbol in open_symbols) for symbol in symbols},
        status,
        len(payload),
    )


def _read_market(r, symbol: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _market_from_closed_klines(klines: list | None) -> dict | None:
    if not isinstance(klines, list) or not klines:
        return None
    latest = klines[-1]
    try:
        if isinstance(latest, dict):
            close = float(latest.get("close"))
            open_price = float(latest.get("open", close))
            high = float(latest.get("high", close))
            low = float(latest.get("low", close))
            quote_volume = float(latest.get("quote_volume") or latest.get("quoteVolume") or 0.0)
        elif isinstance(latest, (list, tuple)) and len(latest) >= 7:
            open_price = float(latest[1])
            high = float(latest[2])
            low = float(latest[3])
            close = float(latest[4])
            quote_volume = float(latest[7]) if len(latest) > 7 else 0.0
        else:
            return None
    except (TypeError, ValueError):
        return None
    return {
        "price": close,
        "last_price": close,
        "ticker_24hr": {
            "lastPrice": close,
            "openPrice": open_price,
            "highPrice": high,
            "lowPrice": low,
            "prevClosePrice": open_price,
            "quoteVolume": quote_volume,
        },
        "funding": {},
        "open_interest": {},
        "source": "v2:market:ohlcv_closed:binance",
    }


def _load_json_list_key(r, key: str) -> list | None:
    raw = r.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except (ValueError, TypeError):
        return None


def _kline_close_ms(row: object) -> int | None:
    try:
        if isinstance(row, dict):
            numeric = float(
                row.get("candle_close_time") or row.get("close_time")
            )
        elif isinstance(row, (list, tuple)) and len(row) >= 7:
            numeric = float(row[6])
        else:
            return None
        if not math.isfinite(numeric) or numeric <= 0:
            return None
        resolved = int(numeric)
        _ms_to_utc_iso(resolved)
        return resolved
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _exact_epoch_ms(value: object) -> int | None:
    """Accept the canonical candle ABI only: a positive built-in ms integer."""

    if type(value) is not int or value <= 0:
        return None
    try:
        _ms_to_utc_iso(value)
    except (OSError, OverflowError, ValueError):
        return None
    return value


def _exact_sha256(value: object) -> str | None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        return None
    return value


def _canonical_json_sha256(value: object) -> str | None:
    try:
        material = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, ValueError):
        return None
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def _exact_model_feature_value(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _latest_closed_close_ms(klines: list | None, *, decision_ms: int) -> int | None:
    latest: int | None = None
    closed, _ = _closed_klines(klines, decision_ms=decision_ms)
    for row in closed:
        close_ms = _kline_close_ms(row)
        if close_ms is None:
            continue
        latest = close_ms if latest is None else max(latest, close_ms)
    return latest


def _read_klines_with_lineage(
    r,
    symbol: str,
    interval: str = "1m",
) -> tuple[list | None, dict]:
    closed_key = f"{V2_REDIS_PREFIX}market:ohlcv_closed:binance:{symbol}:{interval}"
    observation_cutoff_ms: int | None = None
    lineage: dict = {
        "schema_version": OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION,
        "selection_mode": "ATOMIC_CANONICAL_CLOSED_SELECTION_HELD",
        "selected_source_keys": [],
        "legacy_raw_key_considered": False,
        "closed_key": closed_key,
        "raw_key_row_count": 0,
        "closed_key_row_count": 0,
        "selected_row_count": 0,
        "consumer_observation_cutoff_ms": None,
        "consumer_observation_clock_source": None,
        "expected_latest_finalized_close_time": None,
        "atomic_source_read_succeeded": False,
        "atomic_batch_id": None,
        "atomic_batch_material_json": None,
        "atomic_batch_material_sha256": None,
        "atomic_server_observed_at": None,
        "exact_payload_sha256": None,
        "exact_payload_byte_count": 0,
        "exact_source_schema_validated": False,
        "entire_contiguous_suffix_bound": False,
        "selected_source_start_index": None,
        "selected_source_end_index_exclusive": None,
        "selected_candle_ids": None,
        "selected_first_candle_id": None,
        "selected_latest_candle_id": None,
        "selected_identity_storage": "HASH_CHAIN_AND_BOUNDARIES_ONLY",
        "selected_candle_id_chain_sha256": None,
        "selected_rows_material_sha256": None,
        "source_gap_indices": [],
        "source_gap_missing_interval_counts": [],
        "selected_source_provenance_counts": {},
        "selected_backfilled_row_count": 0,
        "binding_selection_material_json": None,
        "binding_selection_sha256": None,
        "consumer_selection_material_json": None,
        "consumer_selection_sha256": None,
        "selection_material_retained_in_snapshot": False,
        "selection_rejection_reasons": [],
        # This slice binds exact input selection only. It is not a durable
        # source receipt, feature publication, or trainer admission.
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }

    def _record_observation_clock(*, local_clock_source: str) -> int:
        nonlocal observation_cutoff_ms
        if observation_cutoff_ms is None:
            observation_cutoff_ms = int(time.time() * 1000)
            lineage["consumer_observation_clock_source"] = local_clock_source
        lineage["consumer_observation_cutoff_ms"] = observation_cutoff_ms
        lineage["expected_latest_finalized_close_time"] = (
            _expected_latest_finalized_close_ms(
                decision_ms=observation_cutoff_ms,
                timeframe=interval,
            )
            if interval in DEFAULT_TIMEFRAMES
            else None
        )
        return observation_cutoff_ms

    def _held(reason: str) -> tuple[None, dict]:
        _record_observation_clock(
            local_clock_source="LOCAL_CLOCK_AT_HOLD_EVALUATION"
        )
        lineage["selection_rejection_reasons"] = [reason]
        return None, lineage

    if r is None:
        return _held("ATOMIC_OHLCV_RAW_REDIS_CLIENT_UNAVAILABLE")
    if interval not in DEFAULT_TIMEFRAMES:
        return _held("ATOMIC_OHLCV_TIMEFRAME_NOT_REQUIRED")

    try:
        batch = read_atomic_redis_sources(r, (closed_key,))
    except AtomicRedisSourceReadError as exc:
        return _held(str(exc))

    # This is the earliest local clock at which the exact transaction result
    # is possessed by this process. Redis TIME is a server-side command clock,
    # not the consumer-observation clock, and a pre-read request clock cannot
    # truthfully substitute for it.
    current_decision_ms = _record_observation_clock(
        local_clock_source="LOCAL_CLOCK_AFTER_ATOMIC_RESPONSE"
    )

    lineage.update(
        {
            "atomic_source_read_succeeded": True,
            "atomic_batch_id": batch.batch_id,
            # Full material stays transient. Recurring latest/archive
            # snapshots retain its hash only to avoid per-cycle Redis
            # amplification.
            "atomic_batch_material_json": None,
            "atomic_batch_material_sha256": batch.batch_material_sha256,
            "atomic_server_observed_at": batch.server_observed_at,
        }
    )
    if len(batch.results) != 1 or batch.results[0].source_key != closed_key:
        return _held("ATOMIC_OHLCV_SOURCE_RESULT_BINDING_INVALID")
    source_result = batch.results[0]
    if not source_result.present or source_result.exact_payload_bytes is None:
        return _held("ATOMIC_OHLCV_CLOSED_SOURCE_KEY_MISSING")

    lineage.update(
        {
            "exact_payload_sha256": source_result.payload_sha256,
            "exact_payload_byte_count": source_result.payload_byte_count,
        }
    )
    try:
        validated = validate_ohlcv_closed_window(
            source_result.exact_payload_bytes,
            symbol=symbol,
            timeframe=interval,
        )
        identity_rows = [asdict(row) for row in validated.rows]
        binding = bind_full_contiguous_core_ta_input(
            identity_rows,
            expected_symbol=symbol,
            timeframe=interval,
            consumer_observed_at_ms=current_decision_ms,
            expected_latest_finalized_close_time=(
                lineage["expected_latest_finalized_close_time"]
            ),
        )
    except (OHLCVClosedWindowValidationError, FeatureWindowContractError) as exc:
        return _held(str(exc))

    if (
        validated.source_key != closed_key
        or validated.exact_payload_sha256 != source_result.payload_sha256
        or validated.exact_payload_byte_count != source_result.payload_byte_count
    ):
        return _held("ATOMIC_OHLCV_EXACT_PAYLOAD_BINDING_INVALID")

    selected_validated_rows = validated.rows[
        binding.selected_source_start_index : binding.selected_source_end_index_exclusive
    ]
    if (
        len(selected_validated_rows) != binding.selected_row_count
        or tuple(row.candle_id for row in selected_validated_rows)
        != binding.selected_candle_ids
    ):
        return _held("ATOMIC_OHLCV_SELECTED_ROW_BINDING_INVALID")

    selected_rows = [asdict(row) for row in selected_validated_rows]
    selected_rows_material_sha256 = _canonical_json_sha256(selected_rows)
    if selected_rows_material_sha256 is None:
        return _held("ATOMIC_OHLCV_SELECTED_ROWS_MATERIAL_INVALID")
    provenance_counts = {
        source: sum(row.source == source for row in selected_validated_rows)
        for source in ("binance_rest", "binance_wss")
        if any(row.source == source for row in selected_validated_rows)
    }
    selection_material = {
        "schema_version": OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION,
        "source_key": closed_key,
        "atomic_batch_id": batch.batch_id,
        "atomic_batch_material_sha256": batch.batch_material_sha256,
        "exact_payload_sha256": validated.exact_payload_sha256,
        "exact_payload_byte_count": validated.exact_payload_byte_count,
        "consumer_observation_cutoff_ms": current_decision_ms,
        "expected_latest_finalized_close_time": (
            binding.expected_latest_finalized_close_time
        ),
        "binding_selection_sha256": binding.selection_sha256,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (
            binding.selected_source_end_index_exclusive
        ),
        "selected_row_count": binding.selected_row_count,
        "selected_candle_ids": list(binding.selected_candle_ids),
        "selected_candle_id_chain_sha256": (
            binding.selected_candle_id_chain_sha256
        ),
        "selected_rows_material_sha256": selected_rows_material_sha256,
        "selected_raw_payload_hashes": [
            row.raw_payload_hash for row in selected_validated_rows
        ],
        "selected_source_provenance": [
            {
                "candle_id": row.candle_id,
                "source": row.source,
                "is_backfilled": row.is_backfilled,
                "source_sequence_id": row.source_sequence_id,
                "raw_payload_hash": row.raw_payload_hash,
            }
            for row in selected_validated_rows
        ],
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    selection_material_json = json.dumps(
        selection_material,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    selection_sha256 = hashlib.sha256(
        selection_material_json.encode("ascii")
    ).hexdigest()
    lineage.update(
        {
            "selection_mode": "ATOMIC_CANONICAL_CLOSED_FULL_CONTIGUOUS_SUFFIX_BOUND",
            "selected_source_keys": [closed_key],
            "closed_key_row_count": validated.row_count,
            "selected_row_count": binding.selected_row_count,
            "exact_source_schema_validated": True,
            "entire_contiguous_suffix_bound": True,
            "selected_source_start_index": binding.selected_source_start_index,
            "selected_source_end_index_exclusive": (
                binding.selected_source_end_index_exclusive
            ),
            "selected_candle_ids": None,
            "selected_first_candle_id": binding.selected_candle_ids[0],
            "selected_latest_candle_id": binding.selected_candle_ids[-1],
            "selected_candle_id_chain_sha256": (
                binding.selected_candle_id_chain_sha256
            ),
            "selected_rows_material_sha256": selected_rows_material_sha256,
            "source_gap_indices": list(binding.gap_indices),
            "source_gap_missing_interval_counts": list(
                binding.gap_missing_interval_counts
            ),
            "selected_source_provenance_counts": provenance_counts,
            "selected_backfilled_row_count": sum(
                row.is_backfilled for row in selected_validated_rows
            ),
            "binding_selection_material_json": None,
            "binding_selection_sha256": binding.selection_sha256,
            "consumer_selection_material_json": None,
            "consumer_selection_sha256": selection_sha256,
            "selection_rejection_reasons": [],
        }
    )
    return selected_rows, lineage


def _read_klines(
    r,
    symbol: str,
    interval: str = "1m",
) -> list | None:
    rows, _lineage = _read_klines_with_lineage(
        r,
        symbol,
        interval,
    )
    return rows


def _closed_klines_with_evidence(
    klines: list | None,
    *,
    decision_ms: int,
) -> tuple[list, list | None, dict[str, int]]:
    closed: list = []
    evidence = {
        "unfinished_kline_excluded_count": 0,
        "future_close_kline_excluded_count": 0,
        "future_available_finalized_kline_excluded_count": 0,
        "malformed_kline_excluded_count": 0,
    }
    if not isinstance(klines, list):
        return closed, None, evidence
    for row in klines:
        if isinstance(row, dict):
            if row.get("is_closed") is not True and row.get("closed_candle") is not True and row.get("candle_closed_confirmed") is not True:
                evidence["unfinished_kline_excluded_count"] += 1
                continue
            close_ms = _kline_close_ms(row)
            if close_ms is None:
                evidence["malformed_kline_excluded_count"] += 1
                continue
            available_raw = row.get("available_at") or row.get("source_available_time") or row.get("ingested_at")
            available_ms = _parse_time_ms(available_raw) if available_raw not in (None, "") else None
            if available_raw not in (None, "") and available_ms is None:
                evidence["malformed_kline_excluded_count"] += 1
                continue
            if available_ms is not None and available_ms > decision_ms:
                evidence["future_available_finalized_kline_excluded_count"] += 1
                continue
        elif isinstance(row, (list, tuple)) and len(row) >= 7:
            close_ms = _kline_close_ms(row)
            if close_ms is None:
                evidence["malformed_kline_excluded_count"] += 1
                continue
        else:
            evidence["malformed_kline_excluded_count"] += 1
            continue
        if close_ms > decision_ms:
            if isinstance(row, dict):
                evidence["future_close_kline_excluded_count"] += 1
            else:
                evidence["unfinished_kline_excluded_count"] += 1
            continue
        closed.append(row)
    return closed, closed[-1] if closed else None, evidence


def _closed_klines(klines: list | None, *, decision_ms: int) -> tuple[list, list | None]:
    closed, latest, _evidence = _closed_klines_with_evidence(
        klines,
        decision_ms=decision_ms,
    )
    return closed, latest


def _exact_candle_temporal_lineage(
    row: object,
    *,
    feature_generated_ms: int | None,
    expected_symbol: str,
    expected_timeframe: str,
    atomic_canonical_selection_bound: bool = False,
) -> tuple[dict[str, str | bool | None], list[str]]:
    """Retain only producer-owned exact clocks; aliases never qualify."""

    lineage: dict[str, str | bool | None] = {
        "candle_open_time": None,
        "candle_close_time": None,
        "event_time": None,
        "ingested_at": None,
        "source_available_at": None,
        "source": None,
        "is_backfilled": None,
        "source_sequence_id": None,
        "raw_payload_hash": None,
        "exact_source_clock_valid": False,
    }
    if not isinstance(row, dict):
        return lineage, ["EXACT_CANDLE_CLOCK_PAYLOAD_REQUIRED"]

    raw_clocks = {
        "candle_open_time": row.get("candle_open_time"),
        "candle_close_time": row.get("candle_close_time"),
        "event_time": row.get("event_time"),
        "ingested_at": row.get("ingested_at"),
        "source_available_at": row.get("available_at"),
    }
    clocks = {name: _exact_epoch_ms(value) for name, value in raw_clocks.items()}
    reasons = [
        f"EXACT_{name.upper()}_MISSING_OR_INVALID"
        for name in (
            "candle_open_time",
            "candle_close_time",
            "event_time",
            "ingested_at",
            "source_available_at",
        )
        if clocks[name] is None
    ]
    for output_name in (
        "candle_open_time",
        "candle_close_time",
        "event_time",
        "ingested_at",
        "source_available_at",
    ):
        value_ms = clocks[output_name]
        if value_ms is not None:
            lineage[output_name] = _ms_to_utc_iso(value_ms)
    source = row.get("source")
    is_backfilled = row.get("is_backfilled")
    source_sequence_id = row.get("source_sequence_id")
    raw_payload_hash = _exact_sha256(row.get("raw_payload_hash"))
    if type(source) is str:
        lineage["source"] = source
    if type(is_backfilled) is bool:
        lineage["is_backfilled"] = is_backfilled
    if type(source_sequence_id) is str:
        lineage["source_sequence_id"] = source_sequence_id
    if raw_payload_hash is not None:
        lineage["raw_payload_hash"] = raw_payload_hash
    if row.get("symbol") != str(expected_symbol).upper():
        reasons.append("CANDLE_SYMBOL_BINDING_MISMATCH")
    if row.get("exchange") != "binance":
        reasons.append("CANDLE_EXCHANGE_BINDING_MISMATCH")
    if row.get("timeframe") != expected_timeframe:
        reasons.append("CANDLE_TIMEFRAME_BINDING_MISMATCH")
    atomic_schema_bound_rest = (
        source == "binance_rest"
        and is_backfilled is True
        and atomic_canonical_selection_bound is True
    )
    if source != "binance_wss" and not atomic_schema_bound_rest:
        reasons.append("LIVE_CANDLE_SOURCE_NOT_EXACT_BINANCE_WSS")
    if type(is_backfilled) is not bool:
        reasons.append("LIVE_CANDLE_BACKFILL_FLAG_MISSING_OR_INVALID")
    elif is_backfilled and not atomic_schema_bound_rest:
        reasons.append("LIVE_CANDLE_BACKFILL_NOT_EXACT_OBSERVATION")
    if row.get("is_closed") is not True:
        reasons.append("EXACT_CANDLE_FINALITY_FLAG_INVALID")
    if row.get("feature_eligible") is not True:
        reasons.append("EXACT_CANDLE_FEATURE_ELIGIBILITY_INVALID")
    if raw_payload_hash is None:
        reasons.append("EXACT_CANDLE_RAW_PAYLOAD_HASH_INVALID")
    event_ms = clocks["event_time"]
    if event_ms is not None and source_sequence_id != str(event_ms):
        reasons.append("EXACT_CANDLE_EVENT_SEQUENCE_BINDING_INVALID")
    if reasons:
        return lineage, reasons

    candle_open_ms = clocks["candle_open_time"]
    candle_close_ms = clocks["candle_close_time"]
    event_ms = clocks["event_time"]
    ingested_ms = clocks["ingested_at"]
    source_available_ms = clocks["source_available_at"]
    assert candle_open_ms is not None
    assert candle_close_ms is not None
    assert event_ms is not None
    assert ingested_ms is not None
    assert source_available_ms is not None

    if candle_open_ms >= candle_close_ms:
        reasons.append("CANDLE_OPEN_NOT_BEFORE_CLOSE")
    timeframe_ms = _timeframe_ms(expected_timeframe)
    if expected_timeframe not in DEFAULT_TIMEFRAMES:
        reasons.append("EXACT_CANDLE_TIMEFRAME_UNSUPPORTED")
    elif (
        candle_open_ms % timeframe_ms != 0
        or candle_close_ms != candle_open_ms + timeframe_ms - 1
    ):
        reasons.append("CANDLE_INTERVAL_OR_ALIGNMENT_INVALID")
    if not candle_close_ms <= event_ms <= ingested_ms:
        reasons.append("CANDLE_CLOSE_EVENT_INGEST_ORDER_INVALID")
    canonical_source_available_ms = max(
        candle_close_ms,
        event_ms,
        ingested_ms,
    )
    if source_available_ms != canonical_source_available_ms:
        reasons.append("SOURCE_AVAILABLE_AT_NOT_CANONICAL_MAX")
    if feature_generated_ms is None:
        reasons.append("FEATURE_GENERATED_AT_MISSING_OR_INVALID")
    elif source_available_ms > feature_generated_ms:
        reasons.append("SOURCE_AVAILABLE_AT_AFTER_FEATURE_GENERATED_AT")

    lineage["exact_source_clock_valid"] = not reasons
    return lineage, reasons


def _read_orderbook(r, symbol: str) -> dict | None:
    if r is None:
        return None
    for key in (
        f"{V2_REDIS_PREFIX}market:orderbook:{symbol}",
        f"{V2_REDIS_PREFIX}market:orderbook:binance:{symbol}",
        f"{V2_REDIS_PREFIX}orderbook:features:binance:{symbol}",
        f"{V2_REDIS_PREFIX}orderbook:features:kucoin:{symbol}",
    ):
        raw = r.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _read_oi_hist(r, symbol: str) -> list | None:
    """Open-interest history rows written by the native ingestor loop."""
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:open_interest_hist:{symbol}:5m")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) and data else None
    except (ValueError, TypeError):
        return None


def _read_long_short(r, symbol: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:long_short:{symbol}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _read_json_key(r, key: str) -> dict | list | None:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, (dict, list)) else None


def _read_hash_key(r, key: str) -> dict | None:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        data = r.hgetall(key) or {}
    except Exception:
        return None
    return dict(data) if isinstance(data, dict) and data else None


def _coerce_numeric(value):
    if isinstance(value, bool):
        return int(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _merge_numeric_features(target: dict, source: dict | None, *, prefix: str | None = None) -> int:
    if not isinstance(source, dict):
        return 0
    ignored = {
        "schema_version",
        "worker_id",
        "source",
        "source_label",
        "symbol",
        "timeframe",
        "generated_at",
        "generated_utc",
        "generated_est",
        "timestamp",
        "live_gate",
        "live_symbols",
        "approves_live",
        "approves_canary",
        "writes_legacy_redis",
        "exchange_action_taken",
        "places_real_order",
        "no_zero_fill",
        "classification",
    }
    merged = 0
    for raw_name, raw_value in source.items():
        name = str(raw_name)
        if name in ignored:
            continue
        value = _coerce_numeric(raw_value)
        if value is None:
            continue
        out_name = f"{prefix}{name}" if prefix else name
        if out_name in EXTERNAL_ENRICHMENT_RESERVED_FIELDS:
            continue
        if target.get(out_name) is None:
            target[out_name] = value
            merged += 1
    return merged


def _merge_selected_numeric_features(target: dict, source: dict | None, fields: tuple[str, ...]) -> int:
    if not isinstance(source, dict):
        return 0
    merged = 0
    for name in fields:
        if name in EXTERNAL_ENRICHMENT_RESERVED_FIELDS:
            continue
        if target.get(name) is not None:
            continue
        value = _coerce_numeric(source.get(name))
        if value is None:
            continue
        target[name] = value
        merged += 1
    return merged


def _merge_numeric_aliases(target: dict, source: dict | None, aliases: tuple[tuple[str, tuple[str, ...]], ...]) -> int:
    if not isinstance(source, dict):
        return 0
    merged = 0
    for out_name, source_names in aliases:
        if out_name in EXTERNAL_ENRICHMENT_RESERVED_FIELDS:
            continue
        if target.get(out_name) is not None:
            continue
        for source_name in source_names:
            value = _coerce_numeric(source.get(source_name))
            if value is None:
                continue
            target[out_name] = value
            merged += 1
            break
    return merged


def _read_first_json_key(r, *keys: str) -> tuple[dict | None, str | None]:
    for key in keys:
        value = _read_json_key(r, key)
        if isinstance(value, dict):
            return value, key
    return None, None


_DIRECTION_CODES = {"UP": 1.0, "DOWN": -1.0, "FLAT": 0.0, "UNKNOWN": 0.0}
_RSI_ZONE_CODES = {"OVERSOLD": -2.0, "BEARISH": -1.0, "NEUTRAL": 0.0, "BULLISH": 1.0, "OVERBOUGHT": 2.0}
_MACD_STATE_CODES = {
    "BEARISH": -2.0,
    "BEARISH_FADING": -1.0,
    "NEUTRAL": 0.0,
    "BULLISH_FADING": 1.0,
    "BULLISH": 2.0,
}
_DELTA_TREND_CODES = {"FALLING": -1.0, "FLAT": 0.0, "RISING": 1.0}
_REGIME_ONE_HOT_FIELDS = {
    "TRENDING_UP": "regime_trending_up",
    "TRENDING_DOWN": "regime_trending_down",
    "RANGING": "regime_ranging",
    "VOLATILE_EXPANSION": "regime_volatile_expansion",
    "LIQUIDITY_SWEEP": "regime_liquidity_sweep",
    "FAKEOUT_RISK": "regime_fakeout_risk",
    "NO_TRADE": "regime_no_trade",
}


def _encoded(mapping: dict, value) -> float | None:
    if value is None:
        return None
    return mapping.get(str(value).strip().upper())


def _merge_a_plus_context_features(r, symbol: str, timeframe: str, features: dict) -> tuple[int, list[str]]:
    """A+ goal Phases 4/5/6: HTF + cross-asset + regime + trade-tape context.

    Merging here puts these fields into the decision-time snapshot, so trainer
    tensors, risk/orchestrator envelopes, and replay archives all carry the
    higher-timeframe and order-flow picture with point-in-time lineage.
    """
    sources_present: list[str] = []
    fields_merged = 0

    htf = _read_json_key(r, f"v2:context:htf:{symbol}")
    if isinstance(htf, dict):
        merged = _merge_numeric_features(
            features,
            {k: v for k, v in htf.items() if k.startswith(("htf_", "mtf_"))},
        )
        merged += _merge_numeric_features(
            features,
            {
                "htf_4h_trend_code": _encoded(_DIRECTION_CODES, htf.get("htf_4h_trend")),
                "htf_1d_ema_direction_code": _encoded(_DIRECTION_CODES, htf.get("htf_1d_ema_direction")),
                "htf_4h_rsi_zone_code": _encoded(_RSI_ZONE_CODES, htf.get("htf_4h_rsi_zone")),
                "htf_1d_rsi_zone_code": _encoded(_RSI_ZONE_CODES, htf.get("htf_1d_rsi_zone")),
                "htf_4h_macd_state_code": _encoded(_MACD_STATE_CODES, htf.get("htf_4h_macd_state")),
            },
        )
        if merged:
            fields_merged += merged
            sources_present.append("v2:context:htf")

    cross_asset = _read_json_key(r, "v2:context:cross_asset")
    if isinstance(cross_asset, dict):
        merged = _merge_numeric_features(
            features,
            {
                "cross_btc_rsi_4h": cross_asset.get("btc_rsi_4h"),
                "cross_btc_ret_4h_pct": cross_asset.get("btc_ret_4h_pct"),
                "cross_btc_direction_1h_code": _encoded(_DIRECTION_CODES, cross_asset.get("btc_direction_1h")),
                "cross_btc_direction_4h_code": _encoded(_DIRECTION_CODES, cross_asset.get("btc_direction_4h")),
                "cross_eth_btc_direction_4h_code": _encoded(_DIRECTION_CODES, cross_asset.get("eth_btc_direction_4h")),
                "cross_risk_off_proxy": 1.0 if cross_asset.get("risk_off_proxy") is True else 0.0,
            },
        )
        if merged:
            fields_merged += merged
            sources_present.append("v2:context:cross_asset")

    regime_gate = _read_json_key(r, f"v2:regime:gate:{symbol}:{timeframe}")
    if isinstance(regime_gate, dict):
        regime_label = str(regime_gate.get("regime") or "").strip().upper()
        one_hot = {
            field: (1.0 if label == regime_label else 0.0)
            for label, field in _REGIME_ONE_HOT_FIELDS.items()
        }
        one_hot["regime_confidence"] = regime_gate.get("confidence")
        merged = _merge_numeric_features(features, one_hot)
        if merged:
            fields_merged += merged
            sources_present.append("v2:regime:gate")

    tape = _read_json_key(r, f"v2:market:trade_tape_features:{symbol}")
    if isinstance(tape, dict):
        merged = _merge_numeric_features(
            features,
            {
                "taker_buy_pct_1m": tape.get("taker_buy_pct_1m"),
                "tape_delta_1m_usd": tape.get("delta_1m"),
                "tape_cumulative_delta_trend_code": _encoded(
                    _DELTA_TREND_CODES, tape.get("cumulative_delta_trend_5m")
                ),
                "tape_large_trade_flag": 1.0 if tape.get("large_trade_flag") else 0.0,
                "aggressive_buy_volume": tape.get("aggressive_buy_volume"),
                "aggressive_sell_volume": tape.get("aggressive_sell_volume"),
                "tape_volume_acceleration": tape.get("volume_acceleration"),
                "trade_tape_confirmation_score": tape.get("trade_tape_confirmation_score"),
            },
        )
        if merged:
            fields_merged += merged
            sources_present.append("v2:market:trade_tape_features")

    return fields_merged, sources_present


def _maybe_poll_moralis_smart_money(r) -> None:
    """Hourly, CU-budget-guarded Moralis smart-money poll.

    Runs inside the always-on pipeline loop; fires only when the last poll is
    older than ~1h and MORALIS_API_KEY is present. The poller enforces the
    2,000,000 CU/month budget (80% daily safety factor) and skips honestly
    when the day's allowance is spent.
    """
    import os
    import time as _time

    try:
        last = float(r.get("meta:moralis:last_update") or 0) / 1000.0
        if _time.time() - last < 3500:
            return
        api_key = os.environ.get("MORALIS_API_KEY", "").strip()
        if not api_key:
            return
        from v2.backend.app.services.smart_money_wallets.poller import (
            poll_token_transfers,
        )

        poll_token_transfers(r, api_key)
    except Exception:  # noqa: BLE001 - never poison the feature cycle
        return


def _bound_market_structure_candles(
    selected_closed_klines: object,
    ohlcv_selection_lineage: object,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[list[dict], dict]:
    """Detach the exact selected rows or return an explicit fail-closed hold."""

    rejection_reasons: list[str] = []
    rows = selected_closed_klines if isinstance(selected_closed_klines, list) else []
    lineage = ohlcv_selection_lineage if isinstance(ohlcv_selection_lineage, dict) else {}
    if lineage.get("exact_source_schema_validated") is not True:
        rejection_reasons.append("EXACT_SOURCE_SCHEMA_NOT_VALIDATED")
    if lineage.get("entire_contiguous_suffix_bound") is not True:
        rejection_reasons.append("ENTIRE_CONTIGUOUS_SUFFIX_NOT_BOUND")
    if lineage.get("selection_rejection_reasons") not in ([], ()):
        rejection_reasons.append("OHLCV_SELECTION_REJECTED")
    if _exact_epoch_ms(lineage.get("consumer_observation_cutoff_ms")) is None:
        rejection_reasons.append("CONSUMER_OBSERVATION_CUTOFF_INVALID")
    if (
        lineage.get("consumer_observation_clock_source")
        != "LOCAL_CLOCK_AFTER_ATOMIC_RESPONSE"
    ):
        rejection_reasons.append("CONSUMER_OBSERVATION_CLOCK_SOURCE_INVALID")
    selected_row_count = lineage.get("selected_row_count")
    if type(selected_row_count) is not int or selected_row_count <= 0:
        rejection_reasons.append("SELECTED_ROW_COUNT_INVALID")
    elif selected_row_count != len(rows):
        rejection_reasons.append("SELECTED_ROW_COUNT_MISMATCH")
    if not rows or any(not isinstance(row, dict) for row in rows):
        rejection_reasons.append("SELECTED_ROWS_INVALID")

    required_hash_fields = (
        "exact_payload_sha256",
        "binding_selection_sha256",
        "consumer_selection_sha256",
        "selected_candle_id_chain_sha256",
        "selected_rows_material_sha256",
    )
    for field in required_hash_fields:
        if _exact_sha256(lineage.get(field)) is None:
            rejection_reasons.append(f"{field.upper()}_INVALID")

    candle_ids: list[str] = []
    if not rejection_reasons:
        for row in rows:
            candle_id = row.get("candle_id")
            if (
                type(candle_id) is not str
                or not candle_id
                or row.get("symbol") != symbol
                or row.get("timeframe") != timeframe
            ):
                rejection_reasons.append("SELECTED_ROW_IDENTITY_MISMATCH")
                break
            candle_ids.append(candle_id)

    if not rejection_reasons:
        if _canonical_json_sha256(rows) != lineage.get(
            "selected_rows_material_sha256"
        ):
            rejection_reasons.append("SELECTED_ROWS_MATERIAL_MISMATCH")
        chain_material = {
            "schema_version": CANDLE_ID_CHAIN_VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "selected_count": len(candle_ids),
            "candle_ids": candle_ids,
        }
        chain_material_json = json.dumps(
            chain_material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        chain_sha256 = hashlib.sha256(
            chain_material_json.encode("ascii")
        ).hexdigest()
        if chain_sha256 != lineage.get("selected_candle_id_chain_sha256"):
            rejection_reasons.append("SELECTED_CANDLE_ID_CHAIN_MISMATCH")
        if (
            lineage.get("selected_first_candle_id") != candle_ids[0]
            or lineage.get("selected_latest_candle_id") != candle_ids[-1]
        ):
            rejection_reasons.append("SELECTED_CANDLE_BOUNDARY_MISMATCH")

    binding = {
        "schema_version": "v2_market_structure_ohlcv_binding_v1",
        "status": (
            "BOUND_TO_ATOMIC_CANONICAL_SELECTION"
            if not rejection_reasons
            else "HELD_UNBOUND_OHLCV_SELECTION"
        ),
        "selection_rejection_reasons": sorted(set(rejection_reasons)),
        "selected_row_count": len(rows) if not rejection_reasons else 0,
        "selected_first_candle_id": (
            candle_ids[0] if candle_ids and not rejection_reasons else None
        ),
        "selected_latest_candle_id": (
            candle_ids[-1] if candle_ids and not rejection_reasons else None
        ),
        "selected_candle_id_chain_sha256": (
            lineage.get("selected_candle_id_chain_sha256")
            if not rejection_reasons
            else None
        ),
        "selected_rows_material_sha256": (
            lineage.get("selected_rows_material_sha256")
            if not rejection_reasons
            else None
        ),
        "consumer_selection_sha256": (
            lineage.get("consumer_selection_sha256")
            if not rejection_reasons
            else None
        ),
        "consumer_observation_cutoff_ms": lineage.get(
            "consumer_observation_cutoff_ms"
        ),
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    if rejection_reasons:
        return [], binding
    return [dict(row) for row in rows], binding


def _merge_external_v2_features(
    r,
    symbol: str,
    timeframe: str,
    features: dict,
    *,
    selected_closed_klines: list,
    ohlcv_selection_lineage: dict,
) -> dict:
    """Merge real V2 feature surfaces into the live feature mirror."""
    sources_present: list[str] = []
    fields_merged = 0
    if symbol == "BTCUSDT" and timeframe == "1h":
        _maybe_poll_moralis_smart_money(r)

    a_plus_merged, a_plus_sources = _merge_a_plus_context_features(r, symbol, timeframe, features)
    fields_merged += a_plus_merged
    sources_present.extend(a_plus_sources)

    ta_full = _read_json_key(r, f"v2:features:ta_full:{symbol}:{timeframe}")
    if isinstance(ta_full, dict):
        indicators = ta_full.get("indicators")
        if isinstance(indicators, dict):
            fields_merged += _merge_numeric_features(features, indicators)
            sources_present.append("v2:features:ta_full")

    liq = _read_hash_key(r, f"v2:liquidations:levels:{symbol}:{timeframe}")
    if isinstance(liq, dict):
        fields_merged += _merge_numeric_features(features, liq)
        sources_present.append("v2:liquidations:levels")

    unified = _read_hash_key(r, f"v2:unified_features:{symbol}:{timeframe}")
    if isinstance(unified, dict):
        fields_merged += _merge_numeric_features(features, unified)
        sources_present.append("v2:unified_features")

    direct_orderbook, direct_orderbook_key = _read_first_json_key(
        r,
        f"v2:orderbook:features:binance:{symbol}",
        f"v2:orderbook:features:kucoin:{symbol}",
        f"v2:market:orderbook:{symbol}",
        f"v2:market:orderbook:binance:{symbol}",
    )
    if isinstance(direct_orderbook, dict):
        fields_merged += _merge_numeric_aliases(features, direct_orderbook, DIRECT_ORDERBOOK_ALIASES)
        sources_present.append(
            "v2:orderbook:features"
            if direct_orderbook_key and "orderbook:features" in direct_orderbook_key
            else "v2:market:orderbook"
        )

    wsds = _read_json_key(r, f"v2:market:coinapi:wsds:{symbol}")
    if isinstance(wsds, dict):
        wsds_features = {
            "microprice": wsds.get("microprice"),
            "spread": wsds.get("spread"),
            "coinapi_mid_px": wsds.get("mid_px"),
            "coinapi_best_bid_px": wsds.get("best_bid_px"),
            "coinapi_best_ask_px": wsds.get("best_ask_px"),
            "coinapi_book_bid_sum_5": wsds.get("book_bid_sum_5"),
            "coinapi_book_ask_sum_5": wsds.get("book_ask_sum_5"),
            "coinapi_imbalance_5": wsds.get("imbalance_5"),
        }
        imbalance = _coerce_numeric(wsds.get("imbalance_5"))
        if imbalance is not None:
            wsds_features["toxicity_proxy"] = abs(float(imbalance))
        fields_merged += _merge_numeric_features(features, wsds_features)
        sources_present.append("v2:market:coinapi:wsds")

    microfeat = _read_json_key(r, f"v2:features:microfeat:{symbol}:{timeframe}")
    if isinstance(microfeat, dict) and isinstance(microfeat.get("features"), dict):
        merged = _merge_numeric_features(features, microfeat.get("features"))
        if merged:
            fields_merged += merged
            sources_present.append("v2:features:microfeat")

    microstructure_sources = (
        ("v2:microstructure:trust_score", f"v2:microstructure:trust_score:{symbol}:{timeframe}"),
        ("v2:microstructure:feed_quality", f"v2:microstructure:feed_quality:binance:{symbol}"),
        ("v2:microstructure:adversarial_features", f"v2:microstructure:adversarial_features:binance:{symbol}"),
        ("v2:microstructure:trade_tape_confirmation", f"v2:microstructure:trade_tape_confirmation:{symbol}"),
        ("v2:microstructure:cross_venue_confirmation", f"v2:microstructure:cross_venue_confirmation:{symbol}"),
        ("v2:microstructure:sweep_risk", f"v2:microstructure:sweep_risk:{symbol}:{timeframe}"),
    )
    for source_label, key in microstructure_sources:
        payload = _read_json_key(r, key)
        if not isinstance(payload, dict):
            continue
        fields_merged += _merge_selected_numeric_features(features, payload, MICROSTRUCTURE_FEATURE_FIELDS)
        fields_merged += _merge_numeric_aliases(
            features,
            payload,
            (
                ("microstructure_trust_score", ("microstructure_trust_score", "orderbook_trust_score")),
                ("feed_latency_ms", ("feed_latency_ms", "orderbook_latency_ms", "latency_ms", "local_latency_ms")),
                ("spread_instability", ("spread_instability", "spread_expansion_rate")),
                ("depth_persistence", ("depth_persistence", "book_depth_persistence_score", "depth_persistence_ms")),
                ("cancel_pressure", ("cancel_pressure", "book_cancel_pressure_score", "cancel_burst_score")),
                ("book_trade_divergence", ("book_trade_divergence", "book_trade_divergence_score")),
                ("depth_vs_tape_divergence", ("depth_vs_tape_divergence", "book_trade_divergence_score")),
                ("cross_venue_confirmation", ("cross_venue_confirmation", "cross_venue_confirmation_score")),
                ("sweep_risk", ("sweep_risk", "sweep_risk_score")),
                ("liquidation_cascade_risk", ("liquidation_cascade_risk", "liquidation_zone_risk_score")),
                ("tape_imbalance", ("tape_imbalance", "trade_imbalance")),
                ("order_flow_imbalance", ("order_flow_imbalance", "trade_imbalance")),
            ),
        )
        sources_present.append(source_label)

    symbol_score = _read_json_key(r, f"v2:altdata:symbol_score:{symbol}")
    if isinstance(symbol_score, dict):
        fields_merged += _merge_selected_numeric_features(features, symbol_score, ALTDATA_SYMBOL_SCORE_FIELDS)
        fields_merged += _merge_numeric_aliases(features, symbol_score, DERIVED_ALTDATA_ALIASES)
        sources_present.append("v2:altdata:symbol_score")

    public_intel = _read_json_key(r, f"v2:altdata:public_intel:symbol:{symbol}")
    if isinstance(public_intel, dict):
        fields_merged += _merge_selected_numeric_features(features, public_intel, PUBLIC_INTEL_FEATURE_FIELDS)
        fields_merged += _merge_numeric_aliases(features, public_intel, DERIVED_ALTDATA_ALIASES)
        sources_present.append("v2:altdata:public_intel")

    whale_walls = _read_json_key(r, f"v2:altdata:whale_walls:symbol:{symbol}")
    if isinstance(whale_walls, dict):
        fields_merged += _merge_selected_numeric_features(features, whale_walls, WHALE_WALL_FEATURE_FIELDS)
        sources_present.append("v2:altdata:whale_walls")

    fields_merged += _merge_numeric_aliases(features, features, DERIVED_ALTDATA_ALIASES)

    # Market structure: liquidity zones (tensor-spec fields), FVG, and
    # BOS/CHOCH structure. Computed from V2-owned closed candles + book +
    # liquidation + tape evidence and published for risk/orchestrator/paper
    # consumption. Missing candles yield explicit missing_evidence payloads.
    structure_candles, structure_ohlcv_binding = _bound_market_structure_candles(
        selected_closed_klines,
        ohlcv_selection_lineage,
        symbol=symbol,
        timeframe=timeframe,
    )
    try:
        reference_price = None
        if structure_candles:
            last = structure_candles[-1]
            for price_field in ("close", "c"):
                candidate = _coerce_numeric(last.get(price_field))
                if candidate is not None and math.isfinite(candidate) and candidate > 0:
                    reference_price = float(candidate)
                    break
        zones = compute_liquidity_zones(
            symbol=symbol,
            timeframe=timeframe,
            candles=structure_candles,
            price=reference_price,
            orderbook_features=_read_json_key(
                r, f"v2:orderbook:features:binance:{symbol}"
            ),
            liquidation_levels=_read_json_key(
                r, f"v2:market:liquidation_levels:{symbol}"
            ),
            trade_tape=_read_json_key(
                r, f"v2:microstructure:trade_tape_confirmation:{symbol}"
            ),
        )
        zones["ohlcv_selection_binding"] = dict(structure_ohlcv_binding)
        r.set(
            f"v2:market:liquidity_zones:{symbol}",
            json.dumps(zones, default=str),
            ex=3600,
        )
        fields_merged += _merge_selected_numeric_features(
            features,
            zones,
            (
                "liquidity_zone_above",
                "liquidity_zone_below",
                "distance_to_liquidity_zone_bps",
                "liquidity_sweep_risk",
            ),
        )
        structure = compute_structure(
            symbol=symbol,
            timeframe=timeframe,
            candles=structure_candles,
            price=reference_price,
        )
        structure["ohlcv_selection_binding"] = dict(structure_ohlcv_binding)
        r.set(
            f"v2:market:structure:{symbol}:{timeframe}",
            json.dumps(structure, default=str),
            ex=3600,
        )
        htf_fvg_payload = None
        if timeframe not in ("4h", "1d"):
            htf_fvg_payload = _read_json_key(r, f"v2:market:fvg:{symbol}:4h")
        # The adversarial-features payload never carried a composite trust
        # field, so fvg_orderbook_trust_confluence was None on every symbol.
        # The real trust producer is v2:microstructure:trust_score:{sym}:{tf}
        # (feed-quality monitor); keep adversarial as the fallback.
        trust_score = None
        for trust_key in (
            f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            f"v2:microstructure:adversarial_features:binance:{symbol}",
        ):
            trust_payload = _read_json_key(r, trust_key)
            if not isinstance(trust_payload, dict):
                continue
            for tf_field in (
                "microstructure_trust_score",
                "composite_trust_score",
                "trust_score",
                "orderbook_trust_score",
            ):
                try:
                    trust_score = float(trust_payload.get(tf_field))
                    break
                except (TypeError, ValueError):
                    continue
            if trust_score is not None:
                break
        fvg = compute_fvg(
            symbol=symbol,
            timeframe=timeframe,
            candles=structure_candles,
            price=reference_price,
            htf_fvg=htf_fvg_payload if isinstance(htf_fvg_payload, dict) else None,
            liquidity_zones=zones,
            orderbook_trust_score=trust_score,
            trade_tape=_read_json_key(
                r, f"v2:microstructure:trade_tape_confirmation:{symbol}"
            ),
        )
        fvg["ohlcv_selection_binding"] = dict(structure_ohlcv_binding)
        r.set(
            f"v2:market:fvg:{symbol}:{timeframe}",
            json.dumps(fvg, default=str),
            ex=3600,
        )
        fields_merged += _merge_selected_numeric_features(
            features,
            fvg,
            ("fvg_size_bps", "distance_to_fvg_bps", "fvg_fill_percent"),
        )
        # VWAP / volume-profile / CVD / sweep-risk families. These keys were
        # only ever written by the paper loop's advanced-indicator path, which
        # stopped publishing on 2026-07-15 (frozen no-TTL payloads, null POC
        # from 4-candle inputs) — 13+ tensor features stale-or-missing on
        # every symbol. This pipeline already owns the closed-candle series
        # (~100 rows/TF, whole universe), so compute them here every cycle
        # exactly like the sibling structure/fvg/zones families.
        for market_key, market_payload in (
            (
                f"v2:market:vwap:{symbol}:{timeframe}",
                compute_vwap_features(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=structure_candles,
                    price=reference_price,
                ),
            ),
            (
                f"v2:market:volume_profile:{symbol}:{timeframe}",
                compute_volume_profile(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=structure_candles,
                    price=reference_price,
                ),
            ),
            (
                f"v2:market:cvd:{symbol}:{timeframe}",
                compute_cvd_features(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=structure_candles,
                    price=reference_price,
                ),
            ),
            # The paper loop published the liquidity-zone payload under
            # sweep_risk (same shape: sweep_risk_long_side/short_side,
            # fake_breakout/breakdown_risk, cascade_continuation_probability).
            (f"v2:market:sweep_risk:{symbol}:{timeframe}", zones),
        ):
            market_payload["ohlcv_selection_binding"] = dict(
                structure_ohlcv_binding
            )
            r.set(market_key, json.dumps(market_payload, default=str), ex=3600)
        sources_present.append("v2:market:structure_computed")
    except Exception as exc:  # noqa: BLE001 - never poison the feature cycle
        sources_present.append(f"market_structure_error:{type(exc).__name__}")

    return {
        "sources_present": sorted(set(sources_present)),
        "fields_merged": fields_merged,
        "market_structure_ohlcv_binding": structure_ohlcv_binding,
    }


def _read_liq_notional_24h(r, symbol: str) -> float | None:
    """Resolve 24h liquidation notional (USD) for ``symbol``.

    Source priority:
      1. ``v2:market:liquidations:aggregate:{symbol}`` (rolling aggregate from
         the WSS client) — authoritative when present.
      2. ``v2:liquidations:events`` stream scanned over the last 24h — used when
         no aggregate exists but the stream is live (present even if empty).
    Returns 0.0 when a live source exists but reports no liquidations (a real
    zero), or ``None`` when no liquidation source is observable at all.
    """
    if r is None:
        return None
    agg_raw = r.get(f"{V2_REDIS_PREFIX}market:liquidations:aggregate:{symbol}")
    if agg_raw:
        try:
            agg = json.loads(agg_raw)
            if isinstance(agg, dict) and "notional_24h" in agg:
                return float(agg.get("notional_24h") or 0.0)
        except (ValueError, TypeError):
            pass
    # Fall back to the global events stream if it exists at all.
    try:
        if not r.exists(f"{V2_REDIS_PREFIX}liquidations:events"):
            return None
        entries = r.xrange(f"{V2_REDIS_PREFIX}liquidations:events", min="-", max="+")
    except Exception:
        return None
    total = 0.0
    for _eid, fields in entries or []:
        if (fields.get("symbol") or "").upper() != symbol.upper():
            continue
        try:
            total += float(fields.get("notional") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def _klines_to_ohlc_series(klines: list) -> tuple[list[float], list[float], list[float], list[float]]:
    """Binance kline row: [open_time, open, high, low, close, volume, ...]."""
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for row in klines:
        try:
            if isinstance(row, dict):
                opens.append(float(row["open"]))
                highs.append(float(row["high"]))
                lows.append(float(row["low"]))
                closes.append(float(row["close"]))
            elif isinstance(row, (list, tuple)) and len(row) >= 5:
                opens.append(float(row[1]))
                highs.append(float(row[2]))
                lows.append(float(row[3]))
                closes.append(float(row[4]))
        except (TypeError, ValueError):
            continue
    return opens, highs, lows, closes


def _atr_pct_series_from_ohlc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    period: int = 14,
) -> list[float]:
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return []
    limit = min(len(highs), len(lows), len(closes))
    trs: list[float] = []
    for i in range(1, limit):
        high = float(highs[i])
        low = float(lows[i])
        previous_close = float(closes[i - 1])
        trs.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    out: list[float] = []
    for end in range(period, len(trs) + 1):
        close = float(closes[end])
        if close <= 0.0:
            continue
        out.append((sum(trs[end - period:end]) / period) / close)
    return out


def _percentile_rank(values: list[float], current: float) -> float | None:
    if not values:
        return None
    below = sum(1 for value in values if value < current)
    equal = sum(1 for value in values if value == current)
    return max(0.0, min(1.0, (below + 0.5 * equal) / len(values)))


def _atr_percentile_from_ohlc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    period: int = 14,
    min_samples: int = 20,
) -> float | None:
    series = _atr_pct_series_from_ohlc(highs, lows, closes, period=period)
    if len(series) < min_samples:
        return None
    return _percentile_rank(series, series[-1])


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _first_numeric(*values) -> float | None:
    for value in values:
        parsed = _coerce_numeric(value)
        if parsed is not None:
            return float(parsed)
    return None


def _first_numeric_field(*items: tuple[str, object]) -> tuple[float | None, str | None]:
    for source, value in items:
        parsed = _coerce_numeric(value)
        if parsed is not None:
            return float(parsed), source
    return None, None


def _configured_fee_bps() -> float:
    return float(AllocationInput.__dataclass_fields__["fee_bps"].default)


def _model_expected_slippage_bps(
    *,
    spread_bps: float,
    volatility_bps: float | None = None,
    liquidity_score: float | None = None,
) -> float:
    volatility_component = max(0.0, float(volatility_bps or 0.0)) * 0.015
    modeled = max(0.25, abs(float(spread_bps)) * 0.50 + volatility_component)
    if liquidity_score is not None:
        if liquidity_score < 0.25:
            modeled *= 2.0
        elif liquidity_score < 0.50:
            modeled *= 1.4
    return round(min(50.0, modeled), 6)


def _top_depth_notional_usd(levels, *, depth: int = 5) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    seen = 0
    for row in levels[:depth]:
        price = None
        qty = None
        if isinstance(row, (list, tuple)) and len(row) > 1:
            price = _coerce_numeric(row[0])
            qty = _coerce_numeric(row[1])
        elif isinstance(row, dict):
            price = _coerce_numeric(row.get("price") or row.get("p"))
            qty = _coerce_numeric(row.get("quantity") or row.get("qty") or row.get("q"))
        if price is None or qty is None or price <= 0 or qty <= 0:
            continue
        total += float(price) * float(qty)
        seen += 1
    return total if seen else None


def _features_from_market(market: dict) -> dict:
    """Build a feature record. Pure-computed values from real OHLCV when present.

    For each TA field, either return a real computation result, or return
    ``None`` (which the caller will record as MISSING in
    ``missing_feature_flags`` so the trainer never sees a silent zero).
    """
    t = market.get("ticker_24hr") or {}
    f = market.get("funding") or {}
    oi = market.get("open_interest") or {}
    last = _f(t.get("lastPrice"))
    raw_funding_rate = _first_numeric(f.get("lastFundingRate"), f.get("fundingRate"))
    # Absence is not a zero-rate observation.  The missing mask must carry it.
    funding_rate = raw_funding_rate
    open_interest = _first_numeric(
        oi.get("open_interest"),
        oi.get("openInterest"),
        oi.get("sumOpenInterest"),
    )
    mark_price = _coerce_numeric(f.get("markPrice") or f.get("mark_price") or last)
    index_price = _coerce_numeric(f.get("indexPrice") or f.get("index_price") or last)
    basis_pct = None
    if mark_price is not None and index_price not in (None, 0.0):
        basis_pct = (float(mark_price) - float(index_price)) / float(index_price)
    long_short = market.get("_long_short") or {}
    long_short_ratio = None
    long_account_ratio = None
    short_account_ratio = None
    if isinstance(long_short, dict):
        long_short_ratio = _coerce_numeric(
            long_short.get("long_short_ratio", long_short.get("longShortRatio"))
        )
        long_account_ratio = _coerce_numeric(
            long_short.get("long_account_ratio", long_short.get("longAccount"))
        )
        short_account_ratio = _coerce_numeric(
            long_short.get("short_account_ratio", long_short.get("shortAccount"))
        )

    klines = market.get("_klines") or []
    orderbook = market.get("_orderbook") or {}
    opens, highs, lows, closes = _klines_to_ohlc_series(klines)
    latest_kline = klines[-1] if isinstance(klines, list) and klines else None
    k_open = k_high = k_low = k_close = k_volume = k_quote_volume = None
    k_num_trades = k_taker_buy_base = k_taker_buy_quote = None
    k_taker_sell_base = k_taker_sell_quote = None
    taker_buy_ratio = taker_sell_ratio = None
    if isinstance(latest_kline, dict):
        k_open = _coerce_numeric(latest_kline.get("open"))
        k_high = _coerce_numeric(latest_kline.get("high"))
        k_low = _coerce_numeric(latest_kline.get("low"))
        k_close = _coerce_numeric(latest_kline.get("close"))
        k_volume = _coerce_numeric(latest_kline.get("volume"))
        k_quote_volume = _coerce_numeric(latest_kline.get("quote_volume") or latest_kline.get("quoteVolume"))
        k_num_trades = _coerce_numeric(latest_kline.get("num_trades") or latest_kline.get("number_of_trades"))
        k_taker_buy_base = _coerce_numeric(latest_kline.get("taker_buy_base_vol") or latest_kline.get("taker_buy_base_volume"))
        k_taker_buy_quote = _coerce_numeric(latest_kline.get("taker_buy_quote_vol") or latest_kline.get("taker_buy_quote_volume"))
    elif isinstance(latest_kline, (list, tuple)) and len(latest_kline) >= 11:
        k_open = _coerce_numeric(latest_kline[1])
        k_high = _coerce_numeric(latest_kline[2])
        k_low = _coerce_numeric(latest_kline[3])
        k_close = _coerce_numeric(latest_kline[4])
        k_volume = _coerce_numeric(latest_kline[5])
        k_quote_volume = _coerce_numeric(latest_kline[7])
        k_num_trades = _coerce_numeric(latest_kline[8])
        k_taker_buy_base = _coerce_numeric(latest_kline[9])
        k_taker_buy_quote = _coerce_numeric(latest_kline[10])
    if k_volume is not None and k_taker_buy_base is not None:
        k_taker_sell_base = max(0.0, float(k_volume) - float(k_taker_buy_base))
        if float(k_volume) > 0.0:
            taker_buy_ratio = float(k_taker_buy_base) / float(k_volume)
            taker_sell_ratio = k_taker_sell_base / float(k_volume)
    if k_quote_volume is not None and k_taker_buy_quote is not None:
        k_taker_sell_quote = max(0.0, float(k_quote_volume) - float(k_taker_buy_quote))

    # Required candle-return fields are defined over the exact finalized OHLCV
    # window, never over the unrelated rolling 24h ticker.  Missing history
    # remains ``None`` so it cannot silently become a valid zero-valued sample.
    ret_pct: float | None = None
    log_return: float | None = None
    range_pct: float | None = None
    body_pct: float | None = None
    gap_pct: float | None = None
    if len(closes) >= 2 and closes[-2] > 0.0 and closes[-1] > 0.0:
        ret_pct = (closes[-1] - closes[-2]) / closes[-2]
        log_return = math.log(closes[-1] / closes[-2])
        if opens and opens[-1] > 0.0:
            gap_pct = (opens[-1] - closes[-2]) / closes[-2]
    if (
        k_close is not None
        and k_close > 0.0
        and k_high is not None
        and k_low is not None
    ):
        range_pct = (k_high - k_low) / k_close
        if k_open is not None:
            body_pct = (k_close - k_open) / k_close

    rsi_14 = _ta_rsi(closes, 14) if closes else None
    macd_line, macd_signal_v, macd_hist = (None, None, None)
    if closes:
        macd_line, macd_signal_v, macd_hist = _ta_macd(closes, 12, 26, 9)
    ema_12 = _ta_ema(closes, 12) if closes else None
    ema_26 = _ta_ema(closes, 26) if closes else None
    sma_20 = _ta_sma(closes, 20) if closes else None
    atr_14 = _ta_atr(highs, lows, closes, 14) if (highs and lows and closes) else None
    true_range_pct = (
        float(atr_14) / float(k_close)
        if atr_14 is not None and k_close is not None and k_close > 0.0
        else None
    )
    atr_percentile = (
        _atr_percentile_from_ohlc(highs, lows, closes)
        if (highs and lows and closes)
        else None
    )

    # Bollinger band width (sigma over 20-period closes / mean) — only
    # if we have at least 20 closes; otherwise None.
    bb_width_pct: float | None = None
    if len(closes) >= 20 and sma_20 and sma_20 > 0:
        window = closes[-20:]
        mean = sma_20
        var = sum((c - mean) ** 2 for c in window) / 20.0
        std = var ** 0.5
        bb_width_pct = (2.0 * std) / mean

    htf_rsi_14: float | None = None
    if len(closes) >= 60:
        # 5x downsampled higher-timeframe RSI proxy from the 1m series
        htf_closes = closes[::5]
        htf_rsi_14 = _ta_rsi(htf_closes, 14)
    htf_ret_pct = (closes[-1] / closes[-5] - 1.0) if len(closes) >= 5 and closes[-5] > 0 else None

    # Use only the orderbook payload selected once by ``_read_orderbook`` for
    # required book evidence.  The native recorder publishes an explicit
    # ``depth_imbalance`` without necessarily carrying book levels, so accept
    # that field before deriving the same statistic from bids/asks.
    depth_imbalance = None
    if isinstance(orderbook, dict) and orderbook:
        explicit_depth_imbalance = _coerce_numeric(
            orderbook.get("depth_imbalance")
        )
        if (
            explicit_depth_imbalance is not None
            and -1.0 <= explicit_depth_imbalance <= 1.0
        ):
            depth_imbalance = explicit_depth_imbalance
        if depth_imbalance is None:
            depth_imbalance = _ta_orderbook_imbalance(orderbook)

    # A microprice is a book statistic, not the ticker last price.  Prefer the
    # size-weighted top of book; when sizes are unavailable the observable mid
    # is the only honest fallback.  No book means no microprice.
    micro_price: float | None = None
    if isinstance(orderbook, dict) and orderbook:
        bids = orderbook.get("bids") or []
        asks = orderbook.get("asks") or []
        bid_price = _first_numeric(
            orderbook.get("best_bid"),
            orderbook.get("ob_best_bid"),
            orderbook.get("bid"),
            bids[0][0]
            if bids and isinstance(bids[0], (list, tuple)) and bids[0]
            else None,
        )
        ask_price = _first_numeric(
            orderbook.get("best_ask"),
            orderbook.get("ob_best_ask"),
            orderbook.get("ask"),
            asks[0][0]
            if asks and isinstance(asks[0], (list, tuple)) and asks[0]
            else None,
        )
        bid_size = _first_numeric(
            orderbook.get("best_bid_size"),
            orderbook.get("bid_size"),
            bids[0][1]
            if bids and isinstance(bids[0], (list, tuple)) and len(bids[0]) > 1
            else None,
        )
        ask_size = _first_numeric(
            orderbook.get("best_ask_size"),
            orderbook.get("ask_size"),
            asks[0][1]
            if asks and isinstance(asks[0], (list, tuple)) and len(asks[0]) > 1
            else None,
        )
        if (
            bid_price is not None
            and ask_price is not None
            and bid_price > 0.0
            and ask_price >= bid_price
        ):
            if (
                bid_size is not None
                and ask_size is not None
                and bid_size >= 0.0
                and ask_size >= 0.0
                and bid_size + ask_size > 0.0
            ):
                micro_price = (
                    bid_price * ask_size + ask_price * bid_size
                ) / (bid_size + ask_size)
            else:
                micro_price = (bid_price + ask_price) / 2.0

    # toxicity_proxy: directional order-flow toxicity from book imbalance.
    # depth_imbalance is signed (bid-ask)/(bid+ask) in [-1, 1]; its magnitude is
    # the toxicity proxy: 0.0 = perfectly balanced book (benign flow), 1.0 =
    # fully one-sided (toxic / adverse-selection risk). Real only with a book.
    toxicity_proxy: float | None = None
    if depth_imbalance is not None:
        toxicity_proxy = abs(depth_imbalance)

    # oi_change_pct: 1h open-interest change from Binance public OI history.
    oi_change_pct: float | None = None
    oi_hist = market.get("_oi_hist") or []
    if isinstance(oi_hist, list) and len(oi_hist) >= 2:
        try:
            first_oi = float(oi_hist[0].get("sumOpenInterest"))
            last_oi = float(oi_hist[-1].get("sumOpenInterest"))
            if first_oi > 0:
                oi_change_pct = (last_oi - first_oi) / first_oi
        except (TypeError, ValueError, AttributeError):
            oi_change_pct = None

    # last_liq_bps_24h: 24h liquidation notional as bps of 24h quote volume.
    last_liq_bps_24h: float | None = None
    liq_notional_24h = market.get("_liq_notional_24h")
    quote_vol_24h = _f(t.get("quoteVolume"))
    if liq_notional_24h is not None and quote_vol_24h > 0:
        last_liq_bps_24h = (float(liq_notional_24h) / quote_vol_24h) * 10000.0

    # Market-cost evidence from explicit V2 market inputs. Missing upstream
    # evidence stays None so replay remains fail-closed instead of defaulted.
    bid_ask_spread_bps: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    orderbook_depth_usd: float | None = None
    if orderbook:
        bid_ask_spread_bps = _first_numeric(
            orderbook.get("actual_observed_spread_entry_bps"),
            orderbook.get("bid_ask_spread_bps"),
            orderbook.get("ob_spread_bps"),
            orderbook.get("orderbook_spread_bps"),
            orderbook.get("spread_bps"),
        )
        bids = orderbook.get("bids") or []
        asks = orderbook.get("asks") or []
        if (
            bid_ask_spread_bps is None
            and bids and asks
            and isinstance(bids[0], (list, tuple)) and isinstance(asks[0], (list, tuple))
        ):
            try:
                bid_p = float(bids[0][0])
                ask_p = float(asks[0][0])
                if bid_p > 0 and ask_p > 0:
                    mid = (bid_p + ask_p) / 2.0
                    bid_ask_spread_bps = ((ask_p - bid_p) / mid) * 10000.0
            except (TypeError, ValueError):
                bid_ask_spread_bps = None
        bid_depth_usd = _first_numeric(
            orderbook.get("bid_depth_usd"),
            orderbook.get("book_bid_depth_usd"),
            orderbook.get("depth_5_bid_usd"),
        )
        ask_depth_usd = _first_numeric(
            orderbook.get("ask_depth_usd"),
            orderbook.get("book_ask_depth_usd"),
            orderbook.get("depth_5_ask_usd"),
        )
        if bid_depth_usd is None:
            bid_depth_usd = _top_depth_notional_usd(bids)
        if ask_depth_usd is None:
            ask_depth_usd = _top_depth_notional_usd(asks)
        orderbook_depth_usd = _first_numeric(
            orderbook.get("orderbook_depth_usd"),
            orderbook.get("market_depth_usd"),
            orderbook.get("depth_usd"),
            orderbook.get("depth_total_usd"),
            orderbook.get("available_depth_usd"),
            orderbook.get("top_of_book_depth_usd"),
        )
        if orderbook_depth_usd is None and bid_depth_usd is not None and ask_depth_usd is not None:
            orderbook_depth_usd = min(bid_depth_usd, ask_depth_usd)
    fee_bps, fee_bps_source = _first_numeric_field(
        ("market.fee_bps", market.get("fee_bps")),
        ("market.taker_fee_bps", market.get("taker_fee_bps")),
        ("market.expected_fee_bps", market.get("expected_fee_bps")),
        ("ticker_24hr.fee_bps", t.get("fee_bps")),
        ("ticker_24hr.taker_fee_bps", t.get("taker_fee_bps")),
        ("orderbook.fee_bps", orderbook.get("fee_bps") if isinstance(orderbook, dict) else None),
        ("orderbook.taker_fee_bps", orderbook.get("taker_fee_bps") if isinstance(orderbook, dict) else None),
    )
    if fee_bps is None:
        fee_bps = _configured_fee_bps()
        fee_bps_source = CONFIGURED_FEE_BPS_SOURCE
    expected_slippage_bps, expected_slippage_source = _first_numeric_field(
        ("market.expected_slippage_bps", market.get("expected_slippage_bps")),
        ("market.actual_observed_slippage_bps", market.get("actual_observed_slippage_bps")),
        ("market.actual_slippage_bps", market.get("actual_slippage_bps")),
        ("market.realized_slippage_bps", market.get("realized_slippage_bps")),
        ("market.slippage_bps", market.get("slippage_bps")),
        ("ticker_24hr.expected_slippage_bps", t.get("expected_slippage_bps")),
        ("ticker_24hr.slippage_bps", t.get("slippage_bps")),
        (
            "orderbook.expected_slippage_bps",
            orderbook.get("expected_slippage_bps") if isinstance(orderbook, dict) else None,
        ),
        ("orderbook.slippage_bps", orderbook.get("slippage_bps") if isinstance(orderbook, dict) else None),
    )
    if expected_slippage_bps is None and bid_ask_spread_bps is not None:
        expected_slippage_bps = _model_expected_slippage_bps(spread_bps=bid_ask_spread_bps)
        expected_slippage_source = "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY(bid_ask_spread_bps)"
    expected_funding_bps = _first_numeric(
        market.get("expected_funding_bps"),
        market.get("funding_bps"),
        f.get("expected_funding_bps"),
        f.get("funding_bps"),
        f.get("funding_rate_bps"),
    )
    if expected_funding_bps is None and raw_funding_rate is not None:
        expected_funding_bps = float(raw_funding_rate) * 10000.0

    raw_paper_position_present = market.get("_paper_position_present")
    if type(raw_paper_position_present) is bool:
        paper_position_present: int | None = int(raw_paper_position_present)
    elif type(raw_paper_position_present) is int and raw_paper_position_present in {0, 1}:
        paper_position_present = raw_paper_position_present
    else:
        # An unread paper-position state is unknown, not proof of an empty book.
        paper_position_present = None

    return {
        "open": k_open,
        "high": k_high,
        "low": k_low,
        "close": k_close,
        "last_price": last if last > 0 else k_close,
        "mark_price": mark_price,
        "index_price": index_price,
        "basis_pct": basis_pct,
        "volume": k_volume,
        "quote_volume": k_quote_volume,
        "num_trades": k_num_trades,
        "taker_buy_base_vol": k_taker_buy_base,
        "taker_buy_quote_vol": k_taker_buy_quote,
        "ret_pct": ret_pct,
        "log_return": log_return,
        "range_pct": range_pct,
        "body_pct": body_pct,
        "true_range_pct": true_range_pct,
        "gap_pct": gap_pct,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "sma_20": sma_20,
        "rsi_14": rsi_14,
        "macd": macd_line,
        "macd_signal": macd_signal_v,
        "macd_hist": macd_hist,
        "atr_14": atr_14,
        "atr_percentile": atr_percentile,
        "bb_width_pct": bb_width_pct,
        "htf_ret_pct": htf_ret_pct,
        "htf_rsi_14": htf_rsi_14,
        "bid_ask_spread_bps": bid_ask_spread_bps,
        "actual_observed_spread_entry_bps": bid_ask_spread_bps,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "orderbook_depth_usd": orderbook_depth_usd,
        "fee_bps": fee_bps,
        "_fee_bps_source": fee_bps_source,
        "expected_slippage_bps": expected_slippage_bps,
        "_expected_slippage_source": expected_slippage_source,
        "expected_funding_bps": expected_funding_bps,
        "depth_imbalance": depth_imbalance,
        "micro_price": micro_price,
        "toxicity_proxy": toxicity_proxy,
        "funding_rate": funding_rate,
        "open_interest": open_interest,
        "long_short_ratio": long_short_ratio,
        "long_account_ratio": long_account_ratio,
        "short_account_ratio": short_account_ratio,
        "taker_sell_base_vol": k_taker_sell_base,
        "taker_sell_quote_vol": k_taker_sell_quote,
        "taker_buy_ratio": taker_buy_ratio,
        "taker_sell_ratio": taker_sell_ratio,
        "oi_change_pct": oi_change_pct,
        "last_liq_bps_24h": last_liq_bps_24h,
        "paper_position_present": paper_position_present,
    }


def _snapshot_id(payload: dict) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"v2_fsnap_{h}"


def _feature_snapshot_archive_key(snapshot_id: str) -> str:
    return f"{V2_REDIS_PREFIX}features:snapshot:{snapshot_id}"


def run_once(symbols: tuple[str, ...], timeframe: str, *, write_trainer_snapshot: bool = True) -> dict:
    started_at = _utc_iso()
    r = _connect_redis()
    ohlcv_binary_r = _ohlcv_binary_client_for(r)
    (
        paper_position_presence,
        paper_position_value_source_status,
        paper_position_source_row_count,
    ) = _read_paper_position_presence(r, symbols)
    keys_written: list[str] = []
    snapshots: list[dict] = []
    missing: list[str] = []
    for sym in symbols:
        # Attach klines + orderbook + OI history + liquidation notional so the
        # feature builder can compute real TA (no silent zeros).
        raw_klines, ohlcv_selection_lineage = _read_klines_with_lineage(
            ohlcv_binary_r,
            sym,
            timeframe,
        )
        observed_cutoff = ohlcv_selection_lineage.get(
            "consumer_observation_cutoff_ms"
        )
        decision_ms = (
            observed_cutoff
            if type(observed_cutoff) is int
            else int(time.time() * 1000)
        )
        selected_ohlcv_source_keys = [
            str(key)
            for key in ohlcv_selection_lineage.get(
                "selected_source_keys",
                [],
            )
            if isinstance(key, str) and key
        ]
        ohlcv_history_payload_receipts_valid = False
        ohlcv_history_payload_receipt_rejection_reasons = [
            "IMMUTABLE_OHLCV_HISTORY_PAYLOAD_RECEIPTS_REQUIRED"
        ]
        closed_klines, latest_closed_kline, kline_exclusion_evidence = (
            _closed_klines_with_evidence(
                raw_klines,
                decision_ms=decision_ms,
            )
        )
        m = _read_market(r, sym) or _market_from_closed_klines(closed_klines)
        if not m:
            missing.append(sym)
            continue
        m["_klines"] = closed_klines
        m["_orderbook"] = _read_orderbook(r, sym)
        m["_oi_hist"] = _read_oi_hist(r, sym)
        m["_long_short"] = _read_long_short(r, sym)
        m["_liq_notional_24h"] = _read_liq_notional_24h(r, sym)
        m["_paper_position_present"] = (
            paper_position_presence.get(sym) if paper_position_presence is not None else None
        )
        feats = _features_from_market(m)
        external = _merge_external_v2_features(
            r,
            sym,
            timeframe,
            feats,
            selected_closed_klines=closed_klines,
            ohlcv_selection_lineage=ohlcv_selection_lineage,
        )
        market_cost_sources = {
            "fee_bps": feats.pop("_fee_bps_source", None),
            "expected_slippage_bps": feats.pop("_expected_slippage_source", None),
        }
        market_cost_missing_fields = [
            field
            for field in ("fee_bps", "expected_slippage_bps", "expected_funding_bps")
            if feats.get(field) is None
        ]
        missing_feature_flags = sorted(k for k, v in feats.items() if v is None)
        candle_open_time = None
        candle_close_time = None
        candle_close_ms = None
        closed_candle_available = latest_closed_kline is not None
        candle_closed_confirmed = (
            isinstance(latest_closed_kline, dict)
            and latest_closed_kline.get("is_closed") is True
        )
        if isinstance(latest_closed_kline, dict):
            candle_open_ms = _parse_time_ms(
                latest_closed_kline.get("candle_open_time")
                or latest_closed_kline.get("open_time")
            )
            candle_close_ms = _parse_time_ms(
                latest_closed_kline.get("candle_close_time")
                or latest_closed_kline.get("close_time")
            )
            if candle_open_ms is not None:
                candle_open_time = _ms_to_utc_iso(candle_open_ms)
            if candle_close_ms is not None:
                candle_close_time = _ms_to_utc_iso(candle_close_ms)
        elif isinstance(latest_closed_kline, (list, tuple)) and len(latest_closed_kline) >= 7:
            candle_open_ms = _parse_time_ms(latest_closed_kline[0])
            candle_close_ms = _parse_time_ms(latest_closed_kline[6])
            if candle_open_ms is not None:
                candle_open_time = _ms_to_utc_iso(candle_open_ms)
            if candle_close_ms is not None:
                candle_close_time = _ms_to_utc_iso(candle_close_ms)
        closed_candle_stale = (
            closed_candle_available
            and _closed_candle_is_stale(
                close_ms=candle_close_ms,
                decision_ms=decision_ms,
                timeframe=timeframe,
            )
        )
        if not candle_closed_confirmed:
            missing_feature_flags = sorted(set(missing_feature_flags) | {
                "candle_closed_confirmed",
            })
        if not closed_candle_available:
            missing_feature_flags = sorted(set(missing_feature_flags) | {
                "ohlcv_closed_window",
                "feature_cutoff",
            })
        if closed_candle_stale:
            missing_feature_flags = sorted(set(missing_feature_flags) | {
                "ohlcv_closed_window_stale",
            })
        generated_at = _utc_iso()
        generated_ms = _parse_time_ms(generated_at)
        exact_candle_lineage, exact_clock_rejection_reasons = (
            _exact_candle_temporal_lineage(
                latest_closed_kline,
                feature_generated_ms=generated_ms,
                expected_symbol=sym,
                expected_timeframe=timeframe,
                atomic_canonical_selection_bound=bool(
                    ohlcv_selection_lineage.get("exact_source_schema_validated") is True
                    and ohlcv_selection_lineage.get("entire_contiguous_suffix_bound") is True
                ),
            )
        )
        expected_finalized_close_ms = (
            _expected_latest_finalized_close_ms(
                decision_ms=generated_ms,
                timeframe=timeframe,
            )
            if generated_ms is not None
            else None
        )
        latest_finalized_candle_available = (
            candle_closed_confirmed
            and exact_candle_lineage["exact_source_clock_valid"] is True
            and candle_close_ms is not None
            and expected_finalized_close_ms is not None
            and candle_close_ms == expected_finalized_close_ms
        )
        temporal_rejection_reasons = list(exact_clock_rejection_reasons)
        if closed_candle_available and exact_clock_rejection_reasons:
            missing_feature_flags = sorted(
                set(missing_feature_flags)
                | {"exact_source_clock_lineage", "feature_cutoff"}
            )
        if closed_candle_available and not latest_finalized_candle_available:
            temporal_rejection_reasons.append(
                "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
            )
            missing_feature_flags = sorted(
                set(missing_feature_flags)
                | {"latest_finalized_candle_at_decision"}
            )
        required_model_feature_missing_fields = sorted(
            name
            for name in TRAINER_REQUIRED_FEATURE_FIELDS
            if not _exact_model_feature_value(feats.get(name))
        )
        required_model_feature_value_contract_valid = (
            not required_model_feature_missing_fields
        )
        optional_event_dependent_feature_missing_fields = sorted(
            name
            for name in TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS
            if not _exact_model_feature_value(feats.get(name))
        )
        optional_event_dependent_feature_present_fields = sorted(
            set(TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS)
            - set(optional_event_dependent_feature_missing_fields)
        )
        if required_model_feature_missing_fields:
            missing_feature_flags = sorted(
                set(missing_feature_flags)
                | set(required_model_feature_missing_fields)
            )
        # Finite values alone do not prove that every non-candle feature was
        # available before this decision. OI, liquidation, order-book, and
        # provider inputs still require immutable per-input PIT receipts.
        required_model_feature_pit_coverage_valid = False
        required_model_feature_pit_rejection_reasons = [
            "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED"
        ]
        missing_feature_flags = sorted(
            set(missing_feature_flags)
            | {"required_model_feature_pit_coverage"}
        )
        latest_candle_temporally_valid = (
            closed_candle_available
            and candle_closed_confirmed
            and not closed_candle_stale
            and latest_finalized_candle_available
            and exact_candle_lineage["exact_source_clock_valid"] is True
        )
        # ``generated_at`` is captured before provider enrichment, hashing,
        # Redis publication, and readback. It is a generation clock, not proof
        # that this exact snapshot was available to a consumer. Until the
        # immutable publication ledger supplies a postcommit receipt, every
        # active-consumer flag must remain fail-closed.
        exact_feature_availability_valid = False
        exact_feature_availability_rejection_reasons = [
            "FEATURE_PUBLICATION_RECEIPT_REQUIRED"
        ]
        missing_feature_flags = sorted(
            set(missing_feature_flags) | {"exact_feature_availability"}
        )
        trainer_consumable = (
            latest_candle_temporally_valid
            and required_model_feature_value_contract_valid
            and required_model_feature_pit_coverage_valid
            and exact_feature_availability_valid
        )
        if not closed_candle_available:
            feature_freshness_state = "MISSING_CLOSED_OHLCV"
        elif closed_candle_stale:
            feature_freshness_state = "STALE_CLOSED_OHLCV"
        elif exact_candle_lineage["exact_source_clock_valid"] is not True:
            feature_freshness_state = "EXACT_SOURCE_CLOCK_INVALID"
        elif not latest_finalized_candle_available:
            feature_freshness_state = "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
        elif not exact_feature_availability_valid:
            feature_freshness_state = "FEATURE_AVAILABILITY_UNVERIFIED"
        else:
            feature_freshness_state = "CURRENT"
        snap = {
            "schema_version": "v2_native_feature_snapshot_v2",
            "worker_id": "v2_feature_pipeline_native_loop",
            "symbol": sym,
            "timeframe": timeframe,
            "features": feats,
            "feature_count": len(feats),
            "real_feature_count": sum(1 for v in feats.values() if v is not None),
            "placeholder_feature_count": 0,
            "missing_feature_count": len(missing_feature_flags),
            "categories_present": [
                "ohlcv_derived", "ta_indicators", "multi_timeframe",
                "microstructure", "funding_oi_liquidation", "portfolio_aware", "freshness",
            ],
            "missing_feature_flags": missing_feature_flags,
            "stale_feature_flags": ["ohlcv_closed_window"] if closed_candle_stale else [],
            "feature_freshness_state": feature_freshness_state,
            "latest_candle_temporally_valid": (
                latest_candle_temporally_valid
            ),
            "required_model_feature_value_contract_valid": (
                required_model_feature_value_contract_valid
            ),
            "feature_requirement_policy_id": (
                FEATURE_REQUIREMENT_POLICY_ID
            ),
            "model_feature_abi_slot_count": len(
                _ORDERED_TRAINER_FEATURE_NAMES
            ),
            "required_model_feature_count": len(
                TRAINER_REQUIRED_FEATURE_FIELDS
            ),
            "required_model_feature_fields": list(
                TRAINER_REQUIRED_FEATURE_FIELDS
            ),
            "required_model_feature_missing_fields": (
                required_model_feature_missing_fields
            ),
            "optional_event_dependent_feature_count": len(
                TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS
            ),
            "optional_event_dependent_feature_fields": list(
                TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS
            ),
            "optional_event_dependent_feature_present_fields": (
                optional_event_dependent_feature_present_fields
            ),
            "optional_event_dependent_feature_missing_fields": (
                optional_event_dependent_feature_missing_fields
            ),
            "required_model_feature_pit_coverage_valid": (
                required_model_feature_pit_coverage_valid
            ),
            "required_model_feature_pit_rejection_reasons": (
                required_model_feature_pit_rejection_reasons
            ),
            "paper_position_source_key": PAPER_POSITIONS_SOURCE_KEY,
            "paper_position_value_source_status": (paper_position_value_source_status),
            "paper_position_source_row_count": (paper_position_source_row_count),
            "paper_position_value_contract_valid": (paper_position_presence is not None),
            "trainer_consumable": trainer_consumable,
            "valid_for_prediction": trainer_consumable,
            "valid_for_paper": trainer_consumable,
            "candle_closed_confirmed": candle_closed_confirmed,
            "candle_open_time": exact_candle_lineage["candle_open_time"],
            "candle_close_time": exact_candle_lineage["candle_close_time"],
            "event_time": exact_candle_lineage["event_time"],
            "ingested_at": exact_candle_lineage["ingested_at"],
            "source_available_at": exact_candle_lineage["source_available_at"],
            "source": exact_candle_lineage["source"],
            "is_backfilled": exact_candle_lineage["is_backfilled"],
            "source_sequence_id": exact_candle_lineage["source_sequence_id"],
            "raw_payload_hash": exact_candle_lineage["raw_payload_hash"],
            "exact_source_clock_valid": exact_candle_lineage[
                "exact_source_clock_valid"
            ],
            "exact_source_clock_rejection_reasons": (
                exact_clock_rejection_reasons
            ),
            "candle_open_time_est": candle_open_time,
            "candle_close_time_est": candle_close_time,
            "source_event_time_est": candle_close_time,
            "source_received_time_est": generated_at,
            "source_available_time": exact_candle_lineage[
                "source_available_at"
            ],
            "available_at": None,
            "available_at_est": generated_at,
            "feature_available_at": None,
            "exact_feature_availability_valid": (
                exact_feature_availability_valid
            ),
            "exact_feature_availability_rejection_reasons": (
                exact_feature_availability_rejection_reasons
            ),
            "feature_cutoff": exact_candle_lineage["candle_close_time"],
            "feature_cutoff_est": candle_close_time,
            "decision_time_est": generated_at,
            "decision_cutoff_time_est": generated_at,
            "source_observation_time": _ms_to_utc_iso(decision_ms),
            "expected_latest_finalized_candle_close_time": (
                _ms_to_utc_iso(expected_finalized_close_ms)
                if expected_finalized_close_ms is not None
                else None
            ),
            "latest_finalized_candle_available_at_decision": (
                latest_finalized_candle_available
            ),
            "temporal_rejection_reasons": temporal_rejection_reasons,
            "source_ohlcv_key": (
                selected_ohlcv_source_keys[-1]
                if selected_ohlcv_source_keys
                else None
            ),
            "source_ohlcv_keys": selected_ohlcv_source_keys,
            "ohlcv_history_payload_receipts_valid": (
                ohlcv_history_payload_receipts_valid
            ),
            "ohlcv_history_payload_receipt_rejection_reasons": (
                ohlcv_history_payload_receipt_rejection_reasons
            ),
            "ohlcv_selection_mode": ohlcv_selection_lineage[
                "selection_mode"
            ],
            "ohlcv_consumer_selection": ohlcv_selection_lineage,
            "external_v2_sources_present": external["sources_present"],
            "external_v2_feature_fields_merged": external["fields_merged"],
            "market_structure_ohlcv_binding": external[
                "market_structure_ohlcv_binding"
            ],
            "market_cost_evidence_source_fields": {
                key: value for key, value in market_cost_sources.items() if value
            },
            "market_cost_evidence_missing_fields": market_cost_missing_fields,
            "market_cost_evidence_status": (
                "COMPLETE_MARKET_COST_EVIDENCE"
                if not market_cost_missing_fields
                else "PARTIAL_MARKET_COST_EVIDENCE"
            ),
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "ohlcv_history_present": bool(closed_klines),
            "ohlcv_raw_row_count": ohlcv_selection_lineage[
                "raw_key_row_count"
            ],
            "ohlcv_closed_key_row_count": ohlcv_selection_lineage[
                "closed_key_row_count"
            ],
            "ohlcv_selected_row_count": ohlcv_selection_lineage[
                "selected_row_count"
            ],
            "ohlcv_closed_row_count": len(closed_klines),
            "ohlcv_closed_age_seconds": (
                None if candle_close_ms is None else max(0, int((decision_ms - candle_close_ms) / 1000))
            ),
            "latest_unclosed_kline_excluded": bool(
                kline_exclusion_evidence["unfinished_kline_excluded_count"]
            ),
            **kline_exclusion_evidence,
            "orderbook_present": bool(m.get("_orderbook")),
            "long_short_present": bool(m.get("_long_short")),
            "generated_at": generated_at,
            "generated_utc": generated_at,
        }
        # Embed the point-in-time-checked provider bridge context (CoinGlass
        # etc.) so the trainer data_loader/tensor_builder — which read
        # snapshot["provider_feature_context"] — actually consume provider
        # features. Without this the tensor's provider slots always read
        # missing even while the provider keys are green.
        try:
            from v2.backend.app.services.provider_features import (
                build_provider_consumer_context,
            )

            provider_ctx = build_provider_consumer_context(
                r,
                role="trainer",
                symbol=sym,
                timeframe=timeframe,
                decision_time=generated_at,
            )
            provider_feats = provider_ctx.get("provider_features")
            if isinstance(provider_feats, dict) and provider_feats:
                snap["provider_feature_context"] = provider_ctx
                snap["provider_features"] = provider_feats
        except Exception:
            pass  # optional providers must never block core snapshots
        snap["feature_snapshot_id"] = _snapshot_id(snap)
        snapshots.append(snap)
        if r is not None:
            k = f"{V2_REDIS_PREFIX}features:latest:{sym}:{timeframe}"
            snap_payload = json.dumps(snap)
            if _safe_write(r, k, snap_payload, ex=FEATURE_LATEST_TTL_SECONDS):
                keys_written.append(k)
            archive_key = _feature_snapshot_archive_key(str(snap["feature_snapshot_id"]))
            if _safe_write(r, archive_key, snap_payload, ex=FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS):
                keys_written.append(archive_key)
            # Also write v2:technical_analysis:{sym}:{tf} so the TA page has fresh
            # live values with proper TTL. Mirrors the TA subset from features.
            ta_families: list[str] = []
            ta_indicators: dict = {}
            f = feats
            if f.get("rsi_14") is not None:
                ta_indicators["ta_RSI_14"] = f["rsi_14"]
                ta_families.append("RSI")
            if f.get("macd") is not None:
                ta_indicators["ta_MACD_12_26_9_macd"] = f["macd"]
                ta_indicators["ta_MACD_12_26_9_signal"] = f.get("macd_signal")
                ta_indicators["ta_MACD_12_26_9_hist"] = f.get("macd_hist")
                ta_indicators["ta_MACDhist_12_26_9"] = f.get("macd_hist")
                ta_families.append("MACD")
            if f.get("atr_14") is not None:
                ta_indicators["ta_ATR_14"] = f["atr_14"]
                ta_families.append("ATR")
            if f.get("sma_20") is not None:
                ta_indicators["ta_SMA_20"] = f["sma_20"]
                ta_families.append("SMA")
            if f.get("ema_12") is not None:
                ta_indicators["ta_EMA_12"] = f["ema_12"]
                ta_families.append("EMA")
            if f.get("ema_26") is not None:
                ta_indicators["ta_EMA_26"] = f["ema_26"]
            if f.get("bb_width_pct") is not None:
                ta_indicators["ta_BB_width_pct"] = f["bb_width_pct"]
                ta_families.append("BB")
            if f.get("htf_rsi_14") is not None:
                ta_indicators["ta_HTF_RSI_14"] = f["htf_rsi_14"]
            ta_indicators["timestamp"] = generated_ms or decision_ms
            ta_payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "generated_utc": _utc_iso(),
                "schema_version": "v2_native_feature_pipeline_ta_v2",
                "source_label": "V2_NATIVE_FEATURE_PIPELINE_LIVE",
                "source_ohlcv_key": (
                    selected_ohlcv_source_keys[-1]
                    if selected_ohlcv_source_keys
                    else None
                ),
                "source_ohlcv_keys": selected_ohlcv_source_keys,
                "ohlcv_selection_mode": ohlcv_selection_lineage[
                    "selection_mode"
                ],
                "families_present": list(dict.fromkeys(ta_families)),
                "indicators": ta_indicators,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "no_zero_fill": True,
            }
            ta_key = f"{V2_REDIS_PREFIX}technical_analysis:{sym}:{timeframe}"
            if _safe_write(r, ta_key, json.dumps(ta_payload), ex=600):
                keys_written.append(ta_key)
            # Keep the legacy-compatible flat TA hashes and the unified
            # feature payload (TA + provider features, e.g. CoinGlass) fresh
            # every cycle — consumers read v2:ta_flat / v2:features:unified
            # and both carry TTLs shorter than ad-hoc backfills.
            try:
                from v2.backend.app.services.feature_pipeline.ta_flat_hash_adapter import (
                    publish_flat_ta,
                )
                from v2.backend.app.services.feature_pipeline.unified_feature_bridge import (
                    build_unified_feature_payload,
                )

                flat_record = publish_flat_ta(r, symbol=sym, timeframe=timeframe)
                if flat_record.get("published"):
                    keys_written.append(f"v2:ta_flat:{sym}:{timeframe}")
                unified = build_unified_feature_payload(
                    r, symbol=sym, timeframe=timeframe, publish=True
                )
                if unified.get("published_key"):
                    keys_written.append(unified["published_key"])
            except Exception:
                pass  # optional enrichment must never block core snapshots
    if r is not None and snapshots:
        ids_payload = json.dumps([s["feature_snapshot_id"] for s in snapshots])
        if _safe_write(r, f"{V2_REDIS_PREFIX}features:snapshots", ids_payload, ex=FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS):
            keys_written.append(f"{V2_REDIS_PREFIX}features:snapshots")
    # On-disk trainer-candidate snapshot mirrors the first symbol's record.
    # Its active-consumer flags remain false until an immutable postcommit
    # publication receipt is validated.
    if snapshots and write_trainer_snapshot:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snapshots[0], indent=2, sort_keys=True) + "\n")
    latest_candle_temporally_valid_count = sum(
        snapshot.get("latest_candle_temporally_valid") is True
        for snapshot in snapshots
    )
    required_model_feature_value_contract_valid_count = sum(
        snapshot.get("required_model_feature_value_contract_valid") is True
        for snapshot in snapshots
    )
    required_model_feature_pit_coverage_valid_count = sum(
        snapshot.get("required_model_feature_pit_coverage_valid") is True
        for snapshot in snapshots
    )
    exact_feature_availability_valid_count = sum(
        snapshot.get("exact_feature_availability_valid") is True
        for snapshot in snapshots
    )
    trainer_consumable_count = sum(
        snapshot.get("trainer_consumable") is True for snapshot in snapshots
    )
    publication_receipt_held_count = sum(
        "FEATURE_PUBLICATION_RECEIPT_REQUIRED"
        in (
            snapshot.get(
                "exact_feature_availability_rejection_reasons"
            )
            or []
        )
        for snapshot in snapshots
    )
    if snapshots and trainer_consumable_count == len(snapshots):
        classification = "NATIVE_V2_ACTIVE_CONSUMERS_READY"
    elif snapshots:
        classification = "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD"
    elif missing:
        classification = "BLOCKED_BY_MISSING_MARKET_INPUTS"
    else:
        classification = "BLOCKED_BY_REDIS_UNAVAILABLE"
    hb = {
        "worker_id": "v2_feature_pipeline_native_loop",
        "schema_version": "v2_feature_pipeline_native_live_v1",
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "timeframe": timeframe,
        "snapshots_built": len(snapshots),
        "latest_candle_temporally_valid_count": (
            latest_candle_temporally_valid_count
        ),
        "required_model_feature_value_contract_valid_count": (
            required_model_feature_value_contract_valid_count
        ),
        "required_model_feature_pit_coverage_valid_count": (
            required_model_feature_pit_coverage_valid_count
        ),
        "paper_position_source_key": PAPER_POSITIONS_SOURCE_KEY,
        "paper_position_value_source_status": (paper_position_value_source_status),
        "paper_position_source_row_count": paper_position_source_row_count,
        "paper_position_value_contract_valid": (paper_position_presence is not None),
        "exact_feature_availability_valid_count": (
            exact_feature_availability_valid_count
        ),
        "trainer_consumable_count": trainer_consumable_count,
        "prediction_eligible_count": sum(
            snapshot.get("valid_for_prediction") is True
            for snapshot in snapshots
        ),
        "paper_eligible_count": sum(
            snapshot.get("valid_for_paper") is True
            for snapshot in snapshots
        ),
        "publication_receipt_held_count": publication_receipt_held_count,
        "active_consumer_readiness": (
            "READY"
            if trainer_consumable_count == len(snapshots) and snapshots
            else "HELD"
        ),
        "trainer_release_ready": bool(
            snapshots and trainer_consumable_count == len(snapshots)
        ),
        "missing_symbols": missing,
        "v2_features_keys_written": keys_written,
        "v2_features_keys_written_count": len(keys_written),
        "classification": classification,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
    }
    if r is not None:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            json.dumps(hb),
            ex=300,
        )
    return hb


def run_timeframes(symbols: tuple[str, ...], timeframes: tuple[str, ...]) -> dict:
    per_timeframe: list[dict] = []
    aggregate_keys: list[str] = []
    write_trainer_snapshot = True
    for timeframe in timeframes:
        hb = run_once(
            symbols,
            timeframe,
            write_trainer_snapshot=write_trainer_snapshot,
        )
        write_trainer_snapshot = False
        per_timeframe.append(hb)
        aggregate_keys.extend(hb.get("v2_features_keys_written") or [])
    snapshots_built = sum(int(row.get("snapshots_built") or 0) for row in per_timeframe)
    missing_symbols = sorted({
        symbol
        for row in per_timeframe
        for symbol in (row.get("missing_symbols") or [])
    })
    trainer_consumable_count = sum(
        int(row.get("trainer_consumable_count") or 0)
        for row in per_timeframe
    )
    if per_timeframe and all(
        row.get("classification") == "NATIVE_V2_ACTIVE_CONSUMERS_READY"
        for row in per_timeframe
    ):
        classification = "NATIVE_V2_ACTIVE_CONSUMERS_READY"
    elif snapshots_built:
        classification = "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD"
    else:
        classification = "BLOCKED_BY_MISSING_MARKET_INPUTS"
    aggregate = {
        "worker_id": "v2_feature_pipeline_native_loop",
        "schema_version": "v2_feature_pipeline_native_live_v2",
        "started_at": per_timeframe[0]["started_at"] if per_timeframe else _utc_iso(),
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "timeframe": ",".join(timeframes),
        "timeframes": list(timeframes),
        "snapshots_built": snapshots_built,
        "latest_candle_temporally_valid_count": sum(
            int(row.get("latest_candle_temporally_valid_count") or 0)
            for row in per_timeframe
        ),
        "required_model_feature_value_contract_valid_count": sum(
            int(
                row.get(
                    "required_model_feature_value_contract_valid_count"
                )
                or 0
            )
            for row in per_timeframe
        ),
        "required_model_feature_pit_coverage_valid_count": sum(
            int(
                row.get(
                    "required_model_feature_pit_coverage_valid_count"
                )
                or 0
            )
            for row in per_timeframe
        ),
        "exact_feature_availability_valid_count": sum(
            int(row.get("exact_feature_availability_valid_count") or 0)
            for row in per_timeframe
        ),
        "trainer_consumable_count": trainer_consumable_count,
        "prediction_eligible_count": sum(
            int(row.get("prediction_eligible_count") or 0)
            for row in per_timeframe
        ),
        "paper_eligible_count": sum(
            int(row.get("paper_eligible_count") or 0)
            for row in per_timeframe
        ),
        "publication_receipt_held_count": sum(
            int(row.get("publication_receipt_held_count") or 0)
            for row in per_timeframe
        ),
        "active_consumer_readiness": (
            "READY"
            if snapshots_built and trainer_consumable_count == snapshots_built
            else "HELD"
        ),
        "trainer_release_ready": bool(
            snapshots_built and trainer_consumable_count == snapshots_built
        ),
        "snapshots_built_by_timeframe": {
            row.get("timeframe"): row.get("snapshots_built") for row in per_timeframe
        },
        "missing_symbols": missing_symbols,
        "v2_features_keys_written": aggregate_keys,
        "v2_features_keys_written_count": len(aggregate_keys),
        "per_timeframe": per_timeframe,
        "classification": classification,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
    }
    r = _connect_redis()
    if r is not None:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            json.dumps(aggregate),
            ex=300,
        )
    return aggregate


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _resolve_runtime_symbols(raw_symbols: str | None, *, smoke_test: bool) -> tuple[str, ...]:
    return tuple(
        resolve_symbols(
            explicit=raw_symbols,
            smoke_test=smoke_test,
            include_baseline=True,
        )
    )


def _parse_timeframes(raw_timeframe: str | None, raw_timeframes: str | None) -> tuple[str, ...]:
    raw = raw_timeframes or raw_timeframe
    if not raw:
        return DEFAULT_TIMEFRAMES
    out: list[str] = []
    for part in raw.split(","):
        timeframe = part.strip()
        if timeframe and timeframe not in out:
            out.append(timeframe)
    return tuple(out or DEFAULT_TIMEFRAMES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_feature_pipeline_native_loop")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Explicit comma-separated symbols. Omit for dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set; never the default.",
    )
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--timeframes", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
            hb = run_timeframes(symbols, _parse_timeframes(args.timeframe, args.timeframes))
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
    hb = run_timeframes(symbols, _parse_timeframes(args.timeframe, args.timeframes))
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "snapshots_built": hb["snapshots_built"],
        "v2_features_keys_written_count": hb["v2_features_keys_written_count"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
