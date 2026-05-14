"""V2 CoinAnk and liquidation bridge service — legacy-baseline-anchored.

Ports the responsibilities of the legacy startup-baseline ingestors
(``live_coinank.py``, ``live_coinank_global_aggregator.py``,
``live_binance_liquidations.py``, ``liquidation_bridge.py``,
``liquidation_levels_engine.py``) into a single V2 service. See
``claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_coinank_and_liquidation_bridge_from_legacy_baseline_LEGACY_BASELINE_ANALYSIS.md``
for the SHA-cited mapping.

Hard rules:
  - NEVER writes any legacy Redis key. The V2 worker writes only V2-namespaced
    data-plane entries (``v2:coinank:*``, ``v2:liquidations:*``) into an
    in-process dict that the CLI persists to a file.
  - NEVER calls any exchange-mutating method. No order/cancel/leverage/margin.
  - NEVER synthesizes liquidation events when an upstream endpoint is
    unavailable. The worker labels ``missing_api_blockers`` instead.
  - Public REST GETs only (CoinAnk Plan-3 endpoints). No API credentials.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterable, List, Mapping, Optional, Tuple


V2_COINANK_PREFIX = "v2:coinank"
V2_LIQUIDATIONS_PREFIX = "v2:liquidations"


# ---------------------------------------------------------------------------
# Plan-3 contracts — preserved verbatim from legacy live_coinank.py
# ---------------------------------------------------------------------------

# Maximum days back allowed per interval. Preserved from
# v2/legacy_preserved/startup_baseline/ingest/live_coinank.py L576-580.
PLAN3_INTERVAL_LIMITS: Dict[str, int] = {
    "1m": 7, "3m": 15, "5m": 30, "15m": 60, "30m": 120,
    "1h": 180, "2h": 180, "4h": 360, "6h": 360, "8h": 360,
    "12h": 360, "1d": 360, "1w": 360, "1M": 360,
}

# Maximum data points per interval to avoid error code 7. Preserved from
# v2/legacy_preserved/startup_baseline/ingest/live_coinank.py L583-598.
MAX_SIZE_LIMITS: Dict[str, int] = {
    "1m": 10080, "3m": 7200, "5m": 8640, "15m": 5760, "30m": 5760,
    "1h": 4320, "2h": 2160, "4h": 2160, "6h": 1440, "8h": 1080,
    "12h": 720, "1d": 360, "1w": 51, "1M": 12,
}

# Default required CoinAnk TFs for derivatives intelligence. Preserved from
# v2/legacy_preserved/startup_baseline/ingest/live_coinank.py L606-610. The
# env var name is also preserved.
REQUIRED_COINANK_TFS: Tuple[str, ...] = tuple(
    x.strip()
    for x in os.getenv("COINANK_TFS", "5m,15m,30m,1h,4h,1d").split(",")
    if x.strip()
)

# Default historical lookback for liquidation_orders (no interval). Preserved
# from v2/legacy_preserved/startup_baseline/ingest/live_coinank.py L915-927.
PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT = 30

# Interval-to-seconds map — preserved from
# v2/legacy_preserved/startup_baseline/ingest/live_coinank.py L935-939.
INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "1w": 604800, "1M": 2592000,
}


# ---------------------------------------------------------------------------
# Liquidation levels engine contracts — preserved verbatim from legacy
# liquidation_levels_engine.py.
# ---------------------------------------------------------------------------

# Per-TF bucket width as a percentage of price. Preserved from
# v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py L51-58.
BUCKET_WIDTH_PCT: Dict[str, float] = {
    "1m": 0.0010, "5m": 0.0010, "15m": 0.0015,
    "1h": 0.0020, "4h": 0.0020, "1d": 0.0025,
}

# Preserved from
# v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py L45-46.
STALENESS_WARNING_MS = 5 * 60 * 1000   # 5 minutes
STALENESS_STALE_MS = 15 * 60 * 1000    # 15 minutes
MAX_RETENTION_SECONDS = 7 * 24 * 3600  # 7 days safety cap


# ---------------------------------------------------------------------------
# Binance forced-order aggregation windows — preserved verbatim from
# v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py
# L225-231. The legacy keys are kept ONLY as a read-only reference; the V2
# worker writes its own V2-prefixed roll-ups.
# ---------------------------------------------------------------------------

AGG_WINDOWS_SECONDS: Tuple[int, ...] = (60, 300, 900, 1800, 3600)
AGG_WINDOW_LABELS: Dict[int, str] = {
    60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h",
}


# ---------------------------------------------------------------------------
# Global 11-key contract — preserved verbatim from
# v2/legacy_preserved/startup_baseline/ingest/live_coinank_global_aggregator.py
# docstring (L7-19) and writers (L275-285). These names are the canonical
# contract consumed by rl/hybrid_trainer.py::_load_global_features and must
# not be renamed.
# ---------------------------------------------------------------------------

GLOBAL_11_KEY_CONTRACT: Tuple[str, ...] = (
    "features:global_coinank:total_oi:latest",
    "features:global_coinank:total_volume:latest",
    "features:global_coinank:total_liquidations:latest",
    "features:global_coinank:long_short_ratio:latest",
    "features:global_coinank:funding_rate_avg:latest",
    "features:global_coinank:btc_dominance:latest",
    "features:global_coinank:eth_dominance:latest",
    "features:global_coinank:alt_season_index:latest",
    "features:global_coinank:fear_greed:latest",
    "features:global_coinank:market_sentiment:latest",
    "features:global_coinank:volatility_index:latest",
)


# ---------------------------------------------------------------------------
# WS reconnect / delegation policy — explicit contract that this CLI does NOT
# open WS sessions; the legacy WS consumer in
# live_binance_liquidations.consume_force_orders (L315+) is owned by a
# separate V2 worker.
# ---------------------------------------------------------------------------

LEGACY_BINANCE_FORCE_WS_DELEGATION: Dict[str, Any] = {
    "legacy_function": "consume_force_orders",
    "baseline_path": "v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py",
    "legacy_stream_url": "wss://fstream.binance.com/stream?streams=!forceOrder@arr",
    "v2_bridge_mode": "in_memory_event_intake_only",
    "v2_owner": "separate_v2_ws_worker",
    "missing_api_blocker_when_unbound": "binance_force_order_ws_owner_unbound",
}


HttpGetCallable = Callable[[str], Tuple[int, Any]]
ClockCallable = Callable[[], float]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GlobalAggregateResult:
    """Result of the 11-key global aggregator. Mirrors the legacy
    ``live_coinank_global_aggregator.compute_and_persist`` return shape.
    """

    total_oi: float = 0.0
    total_volume: float = 0.0
    total_liquidations: float = 0.0
    long_short_ratio: float = 0.0
    funding_rate_avg: float = 0.0
    btc_dominance: float = 0.0
    eth_dominance: float = 0.0
    alt_season_index: float = 0.0
    fear_greed: float = 0.0
    market_sentiment: float = 0.0
    volatility_index: float = 0.0
    n_symbols_observed: int = 0
    v2_keys_written: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class LiquidationEvent:
    """V2 canonical liquidation event. Mirrors the legacy schema published by
    liquidation_bridge.publish.
    """

    ts: int
    symbol: str
    side: str  # "LONG_LIQ" | "SHORT_LIQ"
    price: float
    qty: float
    notional: float
    source: str  # "binance" | "coinank"
    src_key: str
    src_id: str
    ingest_ts: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class MissingApiBlocker:
    category: str
    detail: str
    ts: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CoinankBridgeService:
    """V2 CoinAnk and liquidation bridge service.

    All persistence is into the in-memory ``data_plane`` dict, keyed by
    V2-namespaced strings (``v2:coinank:*`` / ``v2:liquidations:*``). The
    CLI snapshots this dict to a JSON file. No legacy Redis key is ever
    written.
    """

    PLAN3_INTERVAL_LIMITS = PLAN3_INTERVAL_LIMITS
    MAX_SIZE_LIMITS = MAX_SIZE_LIMITS
    REQUIRED_COINANK_TFS = REQUIRED_COINANK_TFS
    PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT = PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT
    INTERVAL_SECONDS = INTERVAL_SECONDS
    BUCKET_WIDTH_PCT = BUCKET_WIDTH_PCT
    STALENESS_WARNING_MS = STALENESS_WARNING_MS
    STALENESS_STALE_MS = STALENESS_STALE_MS
    MAX_RETENTION_SECONDS = MAX_RETENTION_SECONDS
    GLOBAL_11_KEY_CONTRACT = GLOBAL_11_KEY_CONTRACT
    AGG_WINDOWS_SECONDS = AGG_WINDOWS_SECONDS
    AGG_WINDOW_LABELS = AGG_WINDOW_LABELS
    LEGACY_BINANCE_FORCE_WS_DELEGATION = LEGACY_BINANCE_FORCE_WS_DELEGATION

    def __init__(
        self,
        *,
        http_get: Optional[HttpGetCallable] = None,
        clock: Optional[ClockCallable] = None,
        data_plane: Optional[Dict[str, Any]] = None,
        dedup_ttl_sec: int = 600,
    ) -> None:
        self._http_get = http_get
        self._clock = clock if clock is not None else time.time
        self.data_plane: Dict[str, Any] = data_plane if data_plane is not None else {}
        self._dedup_ttl_sec = max(1, int(dedup_ttl_sec))
        self._dedup_index: Dict[str, int] = {}
        self._events: List[LiquidationEvent] = []
        self._liquidations_persisted_total = 0
        self._missing_blockers: List[MissingApiBlocker] = []
        self._endpoint_freshness_ms: Dict[str, int] = {}
        # Per-(symbol, tf) deques of events (legacy LevelEngine.state).
        self._per_sym_tf: Dict[Tuple[str, str], Deque[LiquidationEvent]] = defaultdict(deque)

    # ------------------------------------------------------------------
    # public properties
    # ------------------------------------------------------------------

    @property
    def liquidations_persisted_total(self) -> int:
        return self._liquidations_persisted_total

    @property
    def missing_api_blockers(self) -> List[Dict[str, Any]]:
        return [b.to_dict() for b in self._missing_blockers]

    @property
    def endpoint_freshness_ms(self) -> Dict[str, int]:
        return dict(self._endpoint_freshness_ms)

    # ------------------------------------------------------------------
    # Plan-3 contracts (preserved)
    # ------------------------------------------------------------------

    def now_ms(self) -> int:
        return int(self._clock() * 1000)

    def align_end_time(self, end_time_ms: int, interval: str) -> int:
        """Align endTime to the start of the current interval. Preserved from
        legacy live_coinank._align_end_time (L929-946).
        """
        seconds_per_interval = self.INTERVAL_SECONDS.get(interval, 3600)
        end_time_s = end_time_ms // 1000
        aligned_time_s = (end_time_s // seconds_per_interval) * seconds_per_interval
        return aligned_time_s * 1000

    def plan3_endtime_for_interval(self, interval: str) -> int:
        """Compute Plan-3 endTime for an interval. Preserved from legacy
        live_coinank._plan3_endtime_for_interval (L970-993).
        """
        now_ms = self.now_ms()
        max_days = self.PLAN3_INTERVAL_LIMITS.get(interval, 7)
        # Use a safe recent time (1 hour ago) to avoid edge cases with very
        # recent data.
        safe_end_time_ms = now_ms - (60 * 60 * 1000)
        # Ensure we don't exceed historical limits.
        max_lookback_ms = max_days * 24 * 60 * 60 * 1000
        earliest_allowed_ms = now_ms - max_lookback_ms
        final_end_time_ms = max(
            safe_end_time_ms, earliest_allowed_ms + (60 * 60 * 1000)
        )
        return self.align_end_time(final_end_time_ms, interval)

    def plan3_historical_endtime(
        self, days_back: Optional[int] = None
    ) -> int:
        """Historical endTime for liquidation_orders. Preserved from legacy
        live_coinank._plan3_historical_endtime (L915-927).
        """
        days = int(days_back) if days_back is not None else self.PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT
        now_ms = self.now_ms()
        return now_ms - days * 24 * 60 * 60 * 1000

    def plan3_max_size(self, interval: str, requested_size: int = 100) -> int:
        """Bound the requested size by the Plan-3 max for the interval.
        Preserved from legacy live_coinank._get_max_size (L965-968).
        """
        max_allowed = self.MAX_SIZE_LIMITS.get(interval, 100)
        return min(requested_size, max_allowed)

    # ------------------------------------------------------------------
    # Endpoint persistence (V2 namespace only)
    # ------------------------------------------------------------------

    def persist_endpoint_into_v2_namespace(
        self,
        endpoint: str,
        payload: Any,
        *,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        interval: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a single Plan-3 endpoint payload into the V2 data plane.

        Preserves the legacy persist() responsibility from
        live_coinank.py L1527-2158 — namely producing a per-endpoint latest
        snapshot — while writing only into the V2 namespace. NEVER writes
        any legacy key like ``coinank:*`` or ``features:coinank:*``.
        """
        if not endpoint:
            return {"status": "skipped_empty_endpoint", "v2_key": None}
        now_ms = self.now_ms()
        key_parts = [f"{V2_COINANK_PREFIX}:endpoint", endpoint]
        if symbol:
            key_parts.append(symbol.upper())
        if exchange:
            key_parts.append(exchange)
        if interval:
            key_parts.append(interval)
        key_parts.append("latest")
        v2_key = ":".join(key_parts)
        record = {
            "endpoint": endpoint,
            "symbol": symbol.upper() if symbol else None,
            "exchange": exchange,
            "interval": interval,
            "ts_ms": now_ms,
            "payload": payload,
            "source": "v2_coinank_and_liquidation_bridge",
        }
        self.data_plane[v2_key] = record
        self._endpoint_freshness_ms[endpoint] = now_ms
        return {"status": "ok", "v2_key": v2_key, "ts_ms": now_ms}

    def endpoint_manifest_snapshot(self, endpoints: Iterable[str], version: str = "3.0.0") -> Dict[str, Any]:
        """V2 mirror of legacy _publish_endpoint_manifest (L2159-2195)."""
        endpoint_list = sorted({str(e) for e in endpoints if e})
        manifest = {
            "ts_ms": self.now_ms(),
            "version": version,
            "endpoint_count": len(endpoint_list),
            "endpoints": endpoint_list,
            "required_tfs": list(self.REQUIRED_COINANK_TFS),
        }
        self.data_plane[f"{V2_COINANK_PREFIX}:endpoint_manifest"] = manifest
        return manifest

    def cycle_complete_snapshot(self, cycle_id: int, duration_ms: int, endpoints_active: int) -> Dict[str, Any]:
        """V2 mirror of legacy _publish_cycle_complete (L2196-2228)."""
        runtime = {
            "ts_ms": self.now_ms(),
            "cycle_id": int(cycle_id),
            "duration_ms": int(duration_ms),
            "endpoints_active": int(endpoints_active),
            "manifest_version": "3.0.0",
            "required_tfs": list(self.REQUIRED_COINANK_TFS),
        }
        self.data_plane[f"{V2_COINANK_PREFIX}:cycle_runtime"] = runtime
        return runtime

    # ------------------------------------------------------------------
    # Global 11-key aggregator (preserved)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(x: Any, default: Optional[float] = 0.0) -> Optional[float]:
        try:
            if x is None:
                return default
            if isinstance(x, (bytes, bytearray)):
                x = x.decode("utf-8", errors="ignore")
            return float(x)
        except Exception:
            return default

    @classmethod
    def _first_float(cls, h: Mapping[str, Any], keys: Iterable[str]) -> Optional[float]:
        for k in keys:
            if k in h:
                v = cls._safe_float(h.get(k), None)
                if v is not None:
                    return v
        return None

    def compute_global_11_keys(
        self,
        unified_features_by_symbol: Mapping[str, Mapping[str, Any]],
        *,
        tf: str = "15m",
    ) -> GlobalAggregateResult:
        """V2 mirror of legacy live_coinank_global_aggregator.compute_and_persist
        (L116-306). Writes 11 V2-namespaced mirrors, never the legacy
        ``features:global_coinank:*`` keys.

        The aggregation logic preserves the legacy field-name preference order
        verbatim. If the input is empty, all values are zero — but the
        worker does NOT label this as missing_api_blockers; absence of
        unified-feature data is a separate observation handled at the CLI
        layer.
        """
        now_ms = self.now_ms()
        feats = {sym: dict(h) for sym, h in unified_features_by_symbol.items()}

        # --- Open interest (universe-level) ---
        oi_by_sym: Dict[str, float] = {}
        for sym, h in feats.items():
            oi = self._first_float(
                h,
                (
                    "open_interest",
                    "coinank_openInterest_kline_data_0_close",
                    "coinank_openInterest_symbol_Chart_data_0_close",
                    "coinank_openInterest_v2_chart_data_0_close",
                ),
            )
            if oi is None or oi <= 0:
                continue
            oi_by_sym[sym] = float(oi)
        total_oi = float(sum(oi_by_sym.values()))
        btc_oi = float(oi_by_sym.get("BTCUSDT", 0.0))
        eth_oi = float(oi_by_sym.get("ETHUSDT", 0.0))
        btc_dom = (btc_oi / total_oi * 100.0) if total_oi > 0 else 0.0
        eth_dom = (eth_oi / total_oi * 100.0) if total_oi > 0 else 0.0

        # --- Funding (avg across universe) ---
        funding_vals: List[float] = []
        for _, h in feats.items():
            fr = self._first_float(
                h,
                (
                    "funding_rate",
                    "coinank_fundingRate_kline_data_0_close",
                    "coinank_fundingRate_kline_data_0_open",
                    "coinank_fundingRate_indicator_data_0_fundingRate",
                    "coinank_fundingRate_indicator_data_0_fr",
                    "coinank_fundingRate_getWeiFr_data_0_weightedFundingRate",
                    "coinank_fundingRate_getWeiFr_data_0_fr",
                ),
            )
            if fr is None:
                continue
            funding_vals.append(float(fr))
        funding_avg = (sum(funding_vals) / len(funding_vals)) if funding_vals else 0.0

        # --- Long/short ratio (avg across universe) ---
        lsr_vals: List[float] = []
        for _, h in feats.items():
            lsr = self._first_float(
                h,
                (
                    "coinank_ls_global_account_ratio_longShortRatio_mean",
                    "coinank_ls_toptrader_accounts_longShortRatio_first",
                    "coinank_ls_toptrader_accounts_longShortRatio_mean",
                    "coinank_ls_toptrader_positions_longShortRatio_first",
                    "coinank_ls_toptrader_positions_longShortRatio_mean",
                    "coinank_ls_buy_sell_data_0_longShortRatio",
                    "coinank_ls_buy_sell_data_0_longRatio",
                ),
            )
            if lsr is None or lsr <= 0:
                continue
            lsr_vals.append(float(lsr))
        long_short_ratio = (sum(lsr_vals) / len(lsr_vals)) if lsr_vals else 0.0

        # --- Liquidations (universe total) ---
        liq_total = 0.0
        for _, h in feats.items():
            long_turn = self._first_float(
                h,
                ("coinank_liquidation_history_data_0_longTurnover", "liq_long_usd"),
            )
            short_turn = self._first_float(
                h,
                ("coinank_liquidation_history_data_0_shortTurnover", "liq_short_usd"),
            )
            if long_turn is None and short_turn is None:
                continue
            liq_total += float(long_turn or 0.0) + float(short_turn or 0.0)

        # --- Volume (universe total) ---
        buy_total = 0.0
        sell_total = 0.0
        for _, h in feats.items():
            buy_v = self._first_float(
                h,
                (
                    "coinank_marketOrder_getBuySellValue_data_col1_last",
                    "coinank_marketOrder_getBuySellValue_data_col1_mean",
                    "coinank_marketOrder_getAggBuySellValue_data_col1_last",
                    "coinank_marketOrder_getAggBuySellValue_data_col1_mean",
                    "coinank_marketOrder_getCvd_data_col1_last",
                    "coinank_marketOrder_getAggCvd_data_col1_last",
                ),
            )
            sell_v = self._first_float(
                h,
                (
                    "coinank_marketOrder_getBuySellValue_data_col2_last",
                    "coinank_marketOrder_getBuySellValue_data_col2_mean",
                    "coinank_marketOrder_getAggBuySellValue_data_col2_last",
                    "coinank_marketOrder_getAggBuySellValue_data_col2_mean",
                ),
            )
            if buy_v is None and sell_v is None:
                continue
            buy_total += float(buy_v or 0.0)
            sell_total += float(sell_v or 0.0)
        total_volume = float(buy_total + sell_total)
        denom = max(1e-9, buy_total + sell_total)
        market_sentiment = float((buy_total - sell_total) / denom)

        # --- Volatility index ---
        natr_vals: List[float] = []
        for _, h in feats.items():
            natr = self._first_float(h, ("ind_ta_NATR_28_15m", "ind_ta_NATR_21_15m"))
            if natr is None:
                continue
            natr_vals.append(float(natr))
        volatility_index = (sum(natr_vals) / len(natr_vals) * 100.0) if natr_vals else 0.0

        # --- Fear/Greed ---
        rsi_vals: List[float] = []
        for _, h in feats.items():
            rsi = self._first_float(
                h, ("ind_ta_RSI_14_15m", "ind_ta_RSI_21_15m", "ind_ta_RSI_28_15m"),
            )
            if rsi is None:
                continue
            rsi_vals.append(float(rsi))
        fear_greed = (sum(rsi_vals) / len(rsi_vals)) if rsi_vals else 0.0

        # --- Alt season index ---
        btc_ret = self._safe_float(
            feats.get("BTCUSDT", {}).get("ccxt_price_change_15m_pct"), 0.0
        ) or 0.0
        alts = [s for s in feats.keys() if s not in ("BTCUSDT",)]
        outperf = 0
        outperf_n = 0
        for sym in alts:
            ret = self._safe_float(feats.get(sym, {}).get("ccxt_price_change_15m_pct"), None)
            if ret is None:
                continue
            outperf_n += 1
            if float(ret) > float(btc_ret):
                outperf += 1
        alt_season_index = (outperf / outperf_n * 100.0) if outperf_n > 0 else 0.0

        # Persist into V2 namespace only.
        keys_written: List[str] = []
        for legacy_name, value in (
            ("total_oi", total_oi),
            ("total_volume", total_volume),
            ("total_liquidations", liq_total),
            ("long_short_ratio", long_short_ratio),
            ("funding_rate_avg", funding_avg),
            ("btc_dominance", btc_dom),
            ("eth_dominance", eth_dom),
            ("alt_season_index", alt_season_index),
            ("fear_greed", fear_greed),
            ("market_sentiment", market_sentiment),
            ("volatility_index", volatility_index),
        ):
            v2_key = f"{V2_COINANK_PREFIX}:global:{legacy_name}:latest"
            self.data_plane[v2_key] = {
                "ts_ms": now_ms,
                "timestamp": now_ms,
                "value": float(value),
                "trainer_contract_key": f"features:global_coinank:{legacy_name}:latest",
                "source": "v2_coinank_and_liquidation_bridge",
            }
            keys_written.append(v2_key)

        # Record freshness against tf so the CLI can compute funding/oi/lsr ages.
        self._endpoint_freshness_ms["global_aggregator"] = now_ms
        self._endpoint_freshness_ms["funding_rate_avg"] = now_ms if funding_vals else self._endpoint_freshness_ms.get("funding_rate_avg", 0)
        self._endpoint_freshness_ms["total_oi"] = now_ms if oi_by_sym else self._endpoint_freshness_ms.get("total_oi", 0)
        self._endpoint_freshness_ms["long_short_ratio"] = now_ms if lsr_vals else self._endpoint_freshness_ms.get("long_short_ratio", 0)

        return GlobalAggregateResult(
            total_oi=total_oi,
            total_volume=total_volume,
            total_liquidations=liq_total,
            long_short_ratio=long_short_ratio,
            funding_rate_avg=funding_avg,
            btc_dominance=btc_dom,
            eth_dominance=eth_dom,
            alt_season_index=alt_season_index,
            fear_greed=fear_greed,
            market_sentiment=market_sentiment,
            volatility_index=volatility_index,
            n_symbols_observed=len(feats),
            v2_keys_written=keys_written,
        )

    # ------------------------------------------------------------------
    # Missing-API-blocker labelling (NEVER synthesize)
    # ------------------------------------------------------------------

    def record_missing_api_blocker(self, category: str, detail: str = "") -> Dict[str, Any]:
        """Label a missing-API blocker. The worker MUST NOT replace
        unavailable upstream data with synthetic events. See
        v2/legacy_preserved/startup_baseline/ingest/liquidation_bridge.py
        L51-126 (dedup-then-publish) for the legacy contract this preserves
        by NOT publishing when no source data exists.
        """
        blocker = MissingApiBlocker(
            category=str(category),
            detail=str(detail),
            ts=self.now_ms(),
        )
        self._missing_blockers.append(blocker)
        # Persist into V2 namespace.
        existing = self.data_plane.setdefault(
            f"{V2_LIQUIDATIONS_PREFIX}:missing_api_blockers", []
        )
        existing.append(blocker.to_dict())
        return blocker.to_dict()

    # ------------------------------------------------------------------
    # Liquidation event intake (NEVER synthesizes)
    # ------------------------------------------------------------------

    def _dedup_check(self, source: str, src_id: str) -> bool:
        key = f"{source}:{src_id}"
        now_ms = self.now_ms()
        # Sweep stale entries (cheap; the in-memory map is small).
        ttl_ms = self._dedup_ttl_sec * 1000
        for k in list(self._dedup_index.keys()):
            if now_ms - self._dedup_index[k] > ttl_ms:
                del self._dedup_index[k]
        if key in self._dedup_index:
            return False
        self._dedup_index[key] = now_ms
        # Persist a stable record in the V2 data plane.
        self.data_plane[f"{V2_LIQUIDATIONS_PREFIX}:dedup_index"] = dict(self._dedup_index)
        return True

    def _dedup_set(self, source: str, src_id: str) -> bool:
        """Public surface preserved from legacy liquidation_bridge._set_dedup
        (L51-53) for callers that want explicit dedup semantics. Returns True
        if the (source, src_id) pair was previously unseen.
        """
        return self._dedup_check(source, src_id)

    def _publish_event(self, ev: LiquidationEvent) -> None:
        self._events.append(ev)
        events_key = f"{V2_LIQUIDATIONS_PREFIX}:events"
        bucket: List[Dict[str, Any]] = self.data_plane.setdefault(events_key, [])
        bucket.append(ev.to_dict())
        self._liquidations_persisted_total += 1
        # Update per-(symbol, tf) deques for the levels engine.
        for tf in self.BUCKET_WIDTH_PCT.keys():
            self._per_sym_tf[(ev.symbol, tf)].append(ev)

    def parse_v2_liquidation_event(self, fields: Mapping[str, Any]) -> Optional[LiquidationEvent]:
        """Preserved from legacy liquidation_levels_engine.LevelEngine._parse_event
        (L267-295). Returns ``None`` if the event is malformed.
        """
        try:
            symbol = str(fields.get("symbol", "")).upper()
            if not symbol:
                return None
            ts = int(fields.get("ts") or 0)
            ingest_ts = int(fields.get("ingest_ts") or 0)
            price = float(fields.get("price") or 0)
            qty = float(fields.get("qty") or 0)
            notional = float(fields.get("notional") or 0)
            side = str(fields.get("side", "")).upper()
        except Exception:
            return None

        now_ms = self.now_ms()
        if ts > 0 and (now_ms - ts) > 24 * 3600 * 1000 and ingest_ts > 0:
            ts = ingest_ts
        if ts <= 0 or price <= 0 or qty <= 0 or notional <= 0 or side not in {"LONG_LIQ", "SHORT_LIQ"}:
            return None
        return LiquidationEvent(
            ts=ts,
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            notional=notional,
            source=str(fields.get("source") or "unknown"),
            src_key=str(fields.get("src_key") or ""),
            src_id=str(fields.get("src_id") or ""),
            ingest_ts=int(fields.get("ingest_ts") or now_ms),
        )

    def accept_binance_force_event(self, raw: Mapping[str, Any]) -> Optional[LiquidationEvent]:
        """Preserved from legacy live_binance_liquidations.consume_force_orders
        per-event handling (file L223-231 plus the side mapping at
        liquidation_bridge.process_binance_force L101 — BUY=>SHORT_LIQ,
        SELL=>LONG_LIQ). Accepts an in-memory event dict; never opens WS.
        """
        try:
            symbol = str(raw.get("symbol", "")).upper()
            ts = int(raw.get("ts") or 0)
            price = float(raw.get("price") or 0)
            qty = float(raw.get("qty") or 0)
            side_raw = str(raw.get("side", "")).upper()
        except Exception:
            return None
        if not symbol or ts <= 0 or price <= 0 or qty <= 0:
            return None
        if side_raw == "BUY":
            side = "SHORT_LIQ"
        elif side_raw == "SELL":
            side = "LONG_LIQ"
        else:
            return None
        notional = float(raw.get("notional") or price * qty)
        src_id = f"{symbol}:{ts}:{side_raw}:{price}:{qty}"
        if not self._dedup_check("binance", src_id):
            return None
        ev = LiquidationEvent(
            ts=ts, symbol=symbol, side=side, price=price, qty=qty, notional=notional,
            source="binance",
            src_key="binance:force:raw",
            src_id=src_id,
            ingest_ts=self.now_ms(),
        )
        self._publish_event(ev)
        return ev

    def accept_coinank_liquidation_order(self, item: Mapping[str, Any]) -> Optional[LiquidationEvent]:
        """Preserved from legacy liquidation_bridge.process_coinank_orders
        per-item handling (L149-189). Accepts a single CoinAnk order item.
        """
        try:
            ts = int(item.get("ts") or 0)
        except Exception:
            return None
        symbol = str(item.get("contractCode") or item.get("baseCoin") or "").upper()
        pos_side = str(item.get("posSide", "")).lower()
        if pos_side == "long":
            side = "LONG_LIQ"
        elif pos_side == "short":
            side = "SHORT_LIQ"
        else:
            return None
        try:
            price = float(item.get("price") or 0)
            qty = float(item.get("amount") or 0)
        except Exception:
            return None
        if not symbol or ts <= 0 or price <= 0 or qty <= 0:
            return None
        notional = float(item.get("tradeTurnover") or price * qty)
        src_id = f"{symbol}:{ts}:{side}:{price}:{qty}"
        if not self._dedup_check("coinank", src_id):
            return None
        ev = LiquidationEvent(
            ts=ts, symbol=symbol, side=side, price=price, qty=qty, notional=notional,
            source="coinank",
            src_key="raw:coinank:liquidation_orders:global",
            src_id=src_id,
            ingest_ts=self.now_ms(),
        )
        self._publish_event(ev)
        return ev

    def bridge_binance_force_into_v2_events(
        self,
        force_events: Iterable[Mapping[str, Any]],
    ) -> List[LiquidationEvent]:
        """Bulk wrapper around accept_binance_force_event. Preserves the
        legacy liquidation_bridge.process_binance_force (L63-126) batching
        semantics. If the iterable is empty AND the WS owner is unbound,
        the caller should call ``record_missing_api_blocker`` to label the
        gap (this method never synthesizes events).
        """
        out: List[LiquidationEvent] = []
        for raw in force_events or ():
            ev = self.accept_binance_force_event(raw)
            if ev is not None:
                out.append(ev)
        return out

    def bridge_coinank_orders_into_v2_events(
        self,
        items: Iterable[Mapping[str, Any]],
    ) -> List[LiquidationEvent]:
        """Bulk wrapper around accept_coinank_liquidation_order. Preserves
        legacy liquidation_bridge.process_coinank_orders (L129-196) semantics.
        """
        out: List[LiquidationEvent] = []
        for item in items or ():
            ev = self.accept_coinank_liquidation_order(item)
            if ev is not None:
                out.append(ev)
        return out

    # ------------------------------------------------------------------
    # Aggregation windows (preserved from live_binance_liquidations.AGG_WINDOWS)
    # ------------------------------------------------------------------

    def aggregate_force_window(self, window_seconds: int) -> Dict[str, Any]:
        """Compute a per-window aggregation over the in-memory event list.
        Mirrors live_binance_liquidations.py L225-231 (AGG_WINDOWS) but
        writes only into the V2 namespace.
        """
        if window_seconds not in self.AGG_WINDOW_LABELS:
            return {"status": "unknown_window", "window_seconds": window_seconds}
        now_ms = self.now_ms()
        window_ms = window_seconds * 1000
        cutoff = now_ms - window_ms
        in_window = [e for e in self._events if e.ts >= cutoff]
        count_buy = sum(1 for e in in_window if e.side == "SHORT_LIQ")
        count_sell = sum(1 for e in in_window if e.side == "LONG_LIQ")
        notional_buy = sum(e.notional for e in in_window if e.side == "SHORT_LIQ")
        notional_sell = sum(e.notional for e in in_window if e.side == "LONG_LIQ")
        total_notional = notional_buy + notional_sell
        pressure = (
            (notional_sell - notional_buy) / total_notional
            if total_notional > 0
            else 0.0
        )
        agg = {
            "window_ms": window_ms,
            "updated": now_ms,
            "count_total": count_buy + count_sell,
            "count_buy": count_buy,
            "count_sell": count_sell,
            "notional_buy": notional_buy,
            "notional_sell": notional_sell,
            "net_imbalance": notional_sell - notional_buy,
            "pressure": pressure,
        }
        label = self.AGG_WINDOW_LABELS[window_seconds]
        v2_key = f"{V2_LIQUIDATIONS_PREFIX}:stats:{label}"
        self.data_plane[v2_key] = agg
        return agg

    # ------------------------------------------------------------------
    # Liquidation levels engine (preserved deque algorithm)
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket_step(price: float, tf: str) -> float:
        pct = BUCKET_WIDTH_PCT.get(tf, 0.002)
        step = price * pct
        return max(step, 1e-8)

    @staticmethod
    def _decay_weight(notional: float, age_ms: float, window_ms: float) -> float:
        tau = max(window_ms / 2.0, 1.0)
        return notional * math.exp(-age_ms / tau)

    @staticmethod
    def _top_bucket(heat: Mapping[int, float]) -> Tuple[Optional[int], float, List[Tuple[int, float]]]:
        if not heat:
            return None, 0.0, []
        top_items = sorted(heat.items(), key=lambda kv: kv[1], reverse=True)
        bucket, strength = top_items[0]
        return bucket, strength, top_items[:3]

    @staticmethod
    def _tf_to_seconds(tf: str) -> int:
        tf = tf.strip().lower()
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400
        raise ValueError(f"Unknown timeframe: {tf}")

    def compute_liquidation_levels_mapping(
        self,
        symbol: str,
        tf: str,
        *,
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """Preserved from legacy liquidation_levels_engine.LevelEngine._compute_mapping
        (L341-460). Returns the unified-feature mapping dict for the
        (symbol, tf) pair. The CLI writes this into
        ``v2:liquidations:levels:{symbol}:{tf}`` — NOT into
        ``unified_features:{symbol}:{tf}``.
        """
        symbol = symbol.upper()
        window_seconds = max(self._tf_to_seconds(tf) * 20, 2 * 3600)
        window_seconds = min(window_seconds, self.MAX_RETENTION_SECONDS)
        window_ms = window_seconds * 1000
        now_ms = self.now_ms()

        dq = self._per_sym_tf.get((symbol, tf)) or deque()
        # Prune oldest beyond window.
        while dq and (now_ms - dq[0].ts) > window_ms:
            dq.popleft()

        if not dq:
            if current_price <= 0:
                return None
            step = self._bucket_step(current_price, tf)
            mapping = {
                "liquidation_long_level": 0.0,
                "liquidation_short_level": 0.0,
                "liquidation_long_strength": 0.0,
                "liquidation_short_strength": 0.0,
                "liquidation_long_distance_pct": 100.0,
                "liquidation_short_distance_pct": 100.0,
                "liquidation_volume": 0.0,
                "liquidation_levels_json": json.dumps(
                    {"step": step, "top_long": [], "top_short": []}
                ),
                "liquidation_updated_ts": now_ms,
                "liquidation_last_event_ts": 0,
                "liquidation_staleness_ms": self.MAX_RETENTION_SECONDS * 1000,
                "liquidation_is_stale": 1,
                "liquidation_current_price": current_price,
                "liquidation_source": "binance",
            }
            self.data_plane[f"{V2_LIQUIDATIONS_PREFIX}:levels:{symbol}:{tf}"] = mapping
            return mapping

        mid_price = dq[-1].price
        ref_price = current_price if current_price > 0 else mid_price
        step = self._bucket_step(mid_price, tf)

        heat_long: Dict[int, float] = defaultdict(float)
        heat_short: Dict[int, float] = defaultdict(float)
        liq_volume = 0.0
        for ev in dq:
            age_ms = max(0, now_ms - ev.ts)
            weight = self._decay_weight(ev.notional, age_ms, window_ms)
            bucket = int(ev.price / step)
            if ev.side == "LONG_LIQ":
                heat_long[bucket] += weight
            else:
                heat_short[bucket] += weight
            liq_volume += ev.notional

        long_bucket, long_strength, long_top = self._top_bucket(heat_long)
        short_bucket, short_strength, short_top = self._top_bucket(heat_short)
        long_level = (long_bucket * step) if long_bucket is not None else 0.0
        short_level = (short_bucket * step) if short_bucket is not None else 0.0
        last_event_ts = dq[-1].ts

        if long_level > 0 and ref_price > 0:
            long_distance_pct = abs(ref_price - long_level) / ref_price * 100
        else:
            long_distance_pct = 100.0
        if short_level > 0 and ref_price > 0:
            short_distance_pct = abs(short_level - ref_price) / ref_price * 100
        else:
            short_distance_pct = 100.0

        staleness_ms = now_ms - last_event_ts
        is_stale = 1 if staleness_ms > self.STALENESS_STALE_MS else 0
        levels_json = json.dumps(
            {
                "step": step,
                "top_long": [{"price": b * step, "strength": v} for b, v in long_top],
                "top_short": [{"price": b * step, "strength": v} for b, v in short_top],
            }
        )
        mapping = {
            "liquidation_long_level": long_level,
            "liquidation_short_level": short_level,
            "liquidation_long_strength": long_strength or 0.0,
            "liquidation_short_strength": short_strength or 0.0,
            "liquidation_long_distance_pct": round(long_distance_pct, 4),
            "liquidation_short_distance_pct": round(short_distance_pct, 4),
            "liquidation_volume": liq_volume,
            "liquidation_levels_json": levels_json,
            "liquidation_updated_ts": now_ms,
            "liquidation_last_event_ts": last_event_ts,
            "liquidation_staleness_ms": staleness_ms,
            "liquidation_is_stale": is_stale,
            "liquidation_current_price": ref_price,
            "liquidation_source": "binance",
        }
        self.data_plane[f"{V2_LIQUIDATIONS_PREFIX}:levels:{symbol}:{tf}"] = mapping
        return mapping
