"""V2 feature pipeline and TA worker — legacy-baseline-anchored service.

Ports the responsibilities of the legacy startup-baseline files
(`feature_pipeline.py`, `ohlcv_resampler_hotfix.py`,
`ingest/live_technical_analysis.py`, `scripts/validate_symbol_universe_data.py`,
`scripts/paralysis_detectors.py`) into a single V2-only service. The CLI worker
(``v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py``) snapshots this
service's outputs into a V2-namespaced data-plane file plus a public status
payload. See the LEGACY_BASELINE_ANALYSIS sibling document for SHA-anchored
mappings.

Hard rules (asserted by tests):
  - NEVER writes any legacy Redis key. The V2 worker writes only V2-namespaced
    data-plane entries with the ``v2:features:`` prefix into an in-process dict
    that the CLI persists to a file.
  - NEVER calls any exchange mutating method (no order/cancel/leverage/margin).
  - Public REST GETs only (used only by the CLI helper; the service is
    pure/in-memory).
  - Live gate is permanently ``blocked_human_only``; the service has no
    codepath that can unblock it.
  - Paralysis-detector alerts route into the V2 worker public payload; the
    legacy Redis stream is NOT re-emitted.
"""
from __future__ import annotations

import dataclasses
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


V2_KEY_PREFIX = "v2:features"


# ----------------------------------------------------------------------
# legacy-anchored constants (citations live in the LEGACY_BASELINE_ANALYSIS)
# ----------------------------------------------------------------------

# Lane configuration preserved verbatim from
# legacy_preserved/startup_baseline/feature_pipeline.py
# DualSpeedFeaturePipeline.__init__ (L666-684):
#     self.fast_timeframes = ['1m', '5m']
#     self.slow_timeframes = ['15m', '1h', '4h']
#     self.fast_lane_interval = 10
#     self.slow_lane_interval = 300
FAST_TIMEFRAMES: Tuple[str, ...] = ("1m", "5m")
SLOW_TIMEFRAMES: Tuple[str, ...] = ("15m", "1h", "4h")
FAST_LANE_INTERVAL_SEC = 10
SLOW_LANE_INTERVAL_SEC = 300

# OHLCV resampler TF-aware expiry map preserved verbatim from
# legacy_preserved/startup_baseline/ohlcv_resampler_hotfix.py
# OHLCVResampler.process_combination (L150-152):
#     expiry_map = {'5m': 600, '15m': 1800, '1h': 7200, '4h': 28800}
OHLCV_RESAMPLER_TF_EXPIRY_SEC: Dict[str, int] = {
    "5m": 600,
    "15m": 1800,
    "1h": 7200,
    "4h": 28800,
}
OHLCV_RESAMPLER_DEFAULT_EXPIRY_SEC = 3600
OHLCV_RESAMPLER_INTERVAL_SEC = 12  # legacy UPDATE_INTERVAL = 12

# Live TA service cadence preserved from
# legacy_preserved/startup_baseline/ingest/live_technical_analysis.py
# LiveTechnicalAnalysisService.__init__(update_interval=60) (L34-41) and
# main() (L154).
TA_UPDATE_INTERVAL_SEC = 60

# Universe-validation default thresholds preserved from
# legacy_preserved/startup_baseline/scripts/validate_symbol_universe_data.py
# main() (L70-76):
#     VALIDATE_ORDERBOOK_STALE_SEC = 10
#     VALIDATE_FAST_TF_MAX_AGE_SEC = 90
#     VALIDATE_SLOW_TF_MAX_AGE_SEC = 600
#     VALIDATE_MIN_CANDLES = 50
VALIDATE_ORDERBOOK_STALE_SEC = 10.0
VALIDATE_FAST_TF_MAX_AGE_SEC = 90.0
VALIDATE_SLOW_TF_MAX_AGE_SEC = 600.0
VALIDATE_MIN_CANDLES = 50

# Universe-validation retry window preserved from the legacy startup script
# legacy_reference/scripts/start_all_services_production.sh (L646-647):
#     STARTUP_VALIDATE_RETRIES = 10
#     STARTUP_VALIDATE_SLEEP_SEC = 15
STARTUP_VALIDATE_RETRIES = 10
STARTUP_VALIDATE_SLEEP_SEC = 15

# Paralysis-detector window default preserved from
# legacy_preserved/startup_baseline/scripts/paralysis_detectors.py
# main() (L138):
#     ap.add_argument("--minutes", type=float, default=5.0)
PARALYSIS_DETECTOR_DEFAULT_MINUTES = 5.0

# TA library actually used by the legacy ingest/technical_analysis.py engine:
# `talib` (TA-Lib Python bindings). Not `ta`, not `pandas-ta`. The V2 worker
# preserves the *indicator naming convention* the legacy publishes via
# ta:{symbol}:{tf} hashes (e.g. `ta_RSI_14`, `ta_MACD_12_26_9_*`,
# `ta_ATR_14`), but computes them with a stdlib pure-Python fallback so the
# worker stays installable in a lightweight V2 control-plane venv.
LEGACY_TA_LIBRARY = "talib"
LEGACY_TA_INDICATOR_FAMILIES_PRESERVED: Tuple[str, ...] = (
    "RSI",
    "MACD",
    "ATR",
    "SMA",
    "EMA",
)
LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON: Dict[str, str] = {
    "AD": "requires full TA-Lib accumulation/distribution parity pass",
    "ADX": "requires directional-movement parity against legacy TA-Lib output",
    "AROON": "requires full TA-Lib parity fixture before production use",
    "BOP": "requires candlestick-body parity fixture before production use",
    "CCI": "requires typical-price parity fixture before production use",
    "HT_TRENDMODE": "requires Hilbert-transform TA-Lib parity fixture",
    "MINUS_DI": "requires directional-index parity against legacy TA-Lib output",
    "MOM": "requires momentum-window parity fixture before production use",
    "NATR": "requires normalized-ATR parity against legacy TA-Lib output",
    "OBV": "requires volume-series parity fixture before production use",
    "PLUS_DI": "requires directional-index parity against legacy TA-Lib output",
    "STOCHRSI": "requires stochastic-RSI parity fixture before production use",
    "TRIX": "requires triple-EMA parity fixture before production use",
    "ULTOSC": "requires multi-window oscillator parity fixture before production use",
    "WILLR": "requires Williams-R parity fixture before production use",
    "CDL_PATTERNS": "requires selected candlestick-pattern parity fixtures",
}

LEGACY_FEATURE_FAMILIES_PRESERVED: Tuple[str, ...] = (
    "ohlcv",
    "orderbook_top",
    "mark_funding",
    "ta_passthrough",
    "pressure",
    "volatility",
)
LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON: Dict[str, str] = {
    "binance_tape": "owned by the V2 market-ingestor market-intelligence data plane",
    "btc_correlation": "deferred to a dedicated V2 BTC-correlation feature module",
    "coinank_endpoint_family": "owned by the V2 CoinAnk bridge; not tradable until Binance USD-M confirmation",
    "coinapi_wsds_depth": "owned by the V2 market-ingestor depth/microstructure data plane",
    "cross_timeframe_context": "deferred to a dedicated V2 cross-timeframe feature module",
    "kline_taker_buy_ratios": "owned by the V2 market-ingestor kline enrichment path",
}


# ----------------------------------------------------------------------
# data classes
# ----------------------------------------------------------------------


@dataclass
class UnifiedFeaturesResult:
    """Output of ``compute_unified_features``."""

    symbol: str
    timeframe: str
    features: Dict[str, str] = field(default_factory=dict)
    v2_keys_written: List[str] = field(default_factory=list)
    missing_inputs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class TAResult:
    """Output of ``compute_ta_indicators``."""

    symbol: str
    timeframe: str
    indicators: Dict[str, float] = field(default_factory=dict)
    v2_key: Optional[str] = None
    families_present: List[str] = field(default_factory=list)
    insufficient_history: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ResampleResult:
    """Output of ``resample_ohlcv``."""

    symbol: str
    timeframe: str
    fields: Dict[str, str] = field(default_factory=dict)
    expiry_seconds: int = OHLCV_RESAMPLER_DEFAULT_EXPIRY_SEC
    v2_key: Optional[str] = None
    skipped_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ValidationIssue:
    symbol: str
    code: str

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ValidationResult:
    """Output of ``validate_universe_coverage``."""

    symbols_checked: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    retries_remaining: int = STARTUP_VALIDATE_RETRIES
    sleep_seconds_between_retries: int = STARTUP_VALIDATE_SLEEP_SEC

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out["passed"] = self.passed
        return out


@dataclass
class ParalysisAlert:
    reason: str
    count: int
    sustained_buckets: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ParalysisResult:
    """Output of ``detect_paralysis``."""

    window_minutes: float
    expected_buckets: int
    total_events: int = 0
    per_reason_counts: Dict[str, int] = field(default_factory=dict)
    alerts: List[ParalysisAlert] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_minutes": self.window_minutes,
            "expected_buckets": self.expected_buckets,
            "total_events": self.total_events,
            "per_reason_counts": dict(self.per_reason_counts),
            "alerts": [a.to_dict() for a in self.alerts],
        }


# ----------------------------------------------------------------------
# service
# ----------------------------------------------------------------------


class FeaturePipelineAndTAService:
    """Pure in-memory service. Persistence is done by the CLI worker.

    Inputs are plain Python dicts (the CLI is responsible for sourcing them
    from V2 data-plane files or from public REST GETs). Outputs are dicts
    keyed by ``v2:features:*`` strings, written into ``self.data_plane``.
    """

    def __init__(self, *, data_plane: Optional[Dict[str, Any]] = None) -> None:
        self.data_plane: Dict[str, Any] = data_plane if data_plane is not None else {}

    # ------------------------------------------------------------------
    # 1) feature pipeline (anchor: legacy feature_pipeline.py
    #    FeatureAggregator.aggregate_symbol_tf, L127-646)
    # ------------------------------------------------------------------

    def compute_unified_features(
        self,
        symbol: str,
        tf: str,
        snapshot: Mapping[str, Any],
        *,
        now_ms: Optional[int] = None,
    ) -> UnifiedFeaturesResult:
        """Build the V2 unified-features payload from a per-symbol/tf snapshot.

        ``snapshot`` is expected to contain optional sub-dicts:
          - ``ohlcv`` (open/high/low/close/volume/timestamp)
          - ``orderbook_top`` (bid/ask or bids/asks list-of-lists)
          - ``mark`` (mark_price/index_price/basis_pct/last_funding_rate)
          - ``ta`` (pre-computed talib hash for ta:{symbol}:{tf}; otherwise
            ``compute_ta_indicators`` may be invoked separately)

        Output preserves the legacy unified_features field naming so V2
        consumers (trainer/feature_assembly) can read identical column names.
        """
        result = UnifiedFeaturesResult(symbol=symbol, timeframe=tf)
        ts_ms = int(now_ms) if now_ms is not None else 0
        features: Dict[str, str] = {
            "symbol": symbol,
            "tf": tf,
            "ts_ms": str(ts_ms),
        }

        ohlcv = snapshot.get("ohlcv") or {}
        if not ohlcv:
            result.missing_inputs.append("ohlcv")
        o = _safe_float(ohlcv.get("open"))
        h = _safe_float(ohlcv.get("high"))
        l = _safe_float(ohlcv.get("low"))
        c = _safe_float(ohlcv.get("close"))
        v = _safe_float(ohlcv.get("volume"))
        if o > 0:
            features[f"ccxt_price_change_{tf}_pct"] = str(((c - o) / o) * 100.0 if c > 0 else 0.0)
        if c > 0:
            features[f"ccxt_volatility_{tf}"] = str((h - l) / c if h > 0 and l > 0 else 0.0)
        features["ccxt_open"] = str(o)
        features["ccxt_high"] = str(h)
        features["ccxt_low"] = str(l)
        features["ccxt_close"] = str(c)
        features["ccxt_volume"] = str(v)
        features["open"] = str(o)
        features["high"] = str(h)
        features["low"] = str(l)
        features["close"] = str(c)
        features["volume"] = str(v)

        ob = snapshot.get("orderbook_top") or {}
        if not ob:
            result.missing_inputs.append("orderbook_top")
        bid_px, ask_px = _orderbook_best_prices(ob)
        if bid_px > 0 and ask_px > 0:
            features["ob_best_bid"] = str(bid_px)
            features["ob_best_ask"] = str(ask_px)
            features["ob_ob_mid_price"] = str((bid_px + ask_px) / 2.0)
            features["ob_ob_spread_bps"] = str(((ask_px - bid_px) / bid_px) * 10000.0)
            imbalance = _orderbook_imbalance(ob)
            if imbalance is not None:
                features["ob_ob_imbalance"] = str(imbalance)

        mark = snapshot.get("mark") or {}
        if mark.get("mark_price") is not None:
            features["mark_price"] = str(mark.get("mark_price"))
        if mark.get("index_price") is not None:
            features["index_price"] = str(mark.get("index_price"))
        if mark.get("basis_pct") is not None:
            features["basis_pct"] = str(mark.get("basis_pct"))
        if mark.get("last_funding_rate") is not None:
            features["funding_rate"] = str(mark.get("last_funding_rate"))

        ta_hash = snapshot.get("ta") or {}
        if ta_hash:
            features[f"ind_ind_{symbol}_timestamp"] = str(ts_ms)
            for k, raw in ta_hash.items():
                if not isinstance(k, str) or not k.startswith("ta_"):
                    continue
                try:
                    fv = float(raw)
                except (TypeError, ValueError):
                    continue
                features[f"ind_{k}"] = str(fv)
                features[f"ind_ind_{symbol}_{k}"] = str(fv)

        # Pressure (derived, bounded). Preserved from
        # legacy feature_pipeline.py L216-234.
        pressure = _safe_float(features.get("ind_ta_pressure", 0.0))
        if pressure == 0.0 and o > 0:
            chg_pct = ((c - o) / o) * 100.0 if c > 0 else 0.0
            pressure = max(-1.0, min(1.0, chg_pct / 2.0))
        features["ind_ta_pressure"] = str(pressure)
        if tf in ("1m", "5m", "15m", "1h"):
            features[f"ind_ind_{tf}_pressure"] = str(pressure)

        # Canonical volatility_pct. Preserved from legacy L554-566.
        try:
            vol_raw = features.get(f"ccxt_volatility_{tf}")
            if vol_raw is not None:
                vol = float(vol_raw)
                features["volatility"] = str(vol)
                features["volatility_pct"] = str(vol * 100.0 if vol <= 1.0 else vol)
        except (TypeError, ValueError):
            pass

        v2_key = f"{V2_KEY_PREFIX}:{symbol}:{tf}:unified"
        self.data_plane[v2_key] = dict(features)
        result.features = features
        result.v2_keys_written = [v2_key]
        return result

    # ------------------------------------------------------------------
    # 2) TA indicator engine (anchor: legacy ingest/technical_analysis.py
    #    TechnicalAnalysisEngine + ingest/live_technical_analysis.py
    #    LiveTechnicalAnalysisService)
    # ------------------------------------------------------------------

    def compute_ta_indicators(
        self,
        symbol: str,
        tf: str,
        candles: Sequence[Mapping[str, Any]],
        *,
        now_ms: Optional[int] = None,
    ) -> TAResult:
        """Compute the preserved TA indicator family set from candle history.

        ``candles`` is a chronologically-ordered sequence of dicts with at
        least ``open/high/low/close``. The legacy engine uses the TA-Lib
        Python binding (``import talib``); this V2 implementation deliberately
        avoids the talib dependency so the V2 control-plane venv stays
        lightweight. Indicator naming matches the legacy
        ``ta:{symbol}:{tf}`` hash convention.
        """
        result = TAResult(symbol=symbol, timeframe=tf)
        closes = [_safe_float(row.get("close")) for row in candles]
        highs = [_safe_float(row.get("high")) for row in candles]
        lows = [_safe_float(row.get("low")) for row in candles]
        if len(closes) < 30:
            result.insufficient_history = True
            return result

        rsi = _rsi(closes, 14)
        macd_line, macd_signal, macd_hist = _macd(closes, 12, 26, 9)
        atr = _atr(highs, lows, closes, 14)
        sma_20 = _sma(closes, 20)
        ema_20 = _ema(closes, 20)

        indicators: Dict[str, float] = {}
        if rsi is not None:
            indicators["ta_RSI_14"] = float(rsi)
            result.families_present.append("RSI")
        if macd_line is not None:
            indicators["ta_MACD_12_26_9_macd"] = float(macd_line)
            indicators["ta_MACD_12_26_9_signal"] = float(macd_signal or 0.0)
            indicators["ta_MACD_12_26_9_hist"] = float(macd_hist or 0.0)
            indicators["ta_MACDhist_12_26_9"] = float(macd_hist or 0.0)
            result.families_present.append("MACD")
        if atr is not None:
            indicators["ta_ATR_14"] = float(atr)
            result.families_present.append("ATR")
        if sma_20 is not None:
            indicators["ta_SMA_20"] = float(sma_20)
            result.families_present.append("SMA")
        if ema_20 is not None:
            indicators["ta_EMA_20"] = float(ema_20)
            result.families_present.append("EMA")

        if now_ms is not None:
            indicators["timestamp"] = float(int(now_ms))

        result.indicators = indicators
        v2_key = f"{V2_KEY_PREFIX}:{symbol}:{tf}:ta"
        self.data_plane[v2_key] = {
            "symbol": symbol,
            "timeframe": tf,
            "indicators": dict(indicators),
            "library_used": "v2_inline_pure_python",
            "legacy_library_preserved_naming_from": LEGACY_TA_LIBRARY,
            "families_present": list(result.families_present),
        }
        result.v2_key = v2_key
        return result

    # ------------------------------------------------------------------
    # 3) OHLCV resampler (anchor: legacy ohlcv_resampler_hotfix.py
    #    OHLCVResampler.process_combination, L122-165)
    # ------------------------------------------------------------------

    def resample_ohlcv(
        self,
        symbol: str,
        tf: str,
        market_data: Mapping[str, Any],
    ) -> ResampleResult:
        """Lift the six OHLCV+ts_ms fields from a market_data dict into the V2
        data plane. Preserves the legacy TF-aware expiry map verbatim.
        """
        result = ResampleResult(symbol=symbol, timeframe=tf)
        required = ("open", "high", "low", "close", "volume", "timestamp")
        if not all(field in market_data for field in required):
            result.skipped_reason = "missing_required_field"
            return result
        try:
            fields = {
                "open": str(market_data["open"]),
                "high": str(market_data["high"]),
                "low": str(market_data["low"]),
                "close": str(market_data["close"]),
                "volume": str(market_data["volume"]),
                "ts_ms": str(market_data["timestamp"]),
            }
        except Exception:
            result.skipped_reason = "extract_failed"
            return result
        expiry = OHLCV_RESAMPLER_TF_EXPIRY_SEC.get(tf, OHLCV_RESAMPLER_DEFAULT_EXPIRY_SEC)
        v2_key = f"{V2_KEY_PREFIX}:{symbol}:{tf}:ohlcv_resampled"
        self.data_plane[v2_key] = {
            "symbol": symbol,
            "timeframe": tf,
            "fields": dict(fields),
            "expiry_seconds": int(expiry),
        }
        result.fields = fields
        result.expiry_seconds = int(expiry)
        result.v2_key = v2_key
        return result

    # ------------------------------------------------------------------
    # 4) Universe coverage validator (anchor: legacy
    #    scripts/validate_symbol_universe_data.py main, L68-255)
    # ------------------------------------------------------------------

    def validate_universe_coverage(
        self,
        snapshot: Mapping[str, Any],
        *,
        now_ms: int,
        symbols: Optional[Sequence[str]] = None,
        timeframes: Optional[Sequence[str]] = None,
        orderbook_stale_sec: float = VALIDATE_ORDERBOOK_STALE_SEC,
        fast_tf_max_age_sec: float = VALIDATE_FAST_TF_MAX_AGE_SEC,
        slow_tf_max_age_sec: float = VALIDATE_SLOW_TF_MAX_AGE_SEC,
        min_candles: int = VALIDATE_MIN_CANDLES,
    ) -> ValidationResult:
        """Validate orderbook + unified-features coverage for the configured
        universe. Mirrors the legacy script's freshness checks; thresholds
        are unchanged unless explicitly overridden.
        """
        result = ValidationResult()
        syms = list(symbols or snapshot.get("symbols") or [])
        tfs = list(timeframes or snapshot.get("timeframes") or [])
        result.symbols_checked = len(syms)
        per_symbol: Mapping[str, Mapping[str, Any]] = snapshot.get("per_symbol") or {}
        tf_seconds = {"1m": 60, "5m": 5 * 60, "15m": 15 * 60, "1h": 60 * 60, "4h": 4 * 60 * 60}

        for sym in syms:
            sym_snap = per_symbol.get(sym) or {}
            ob = sym_snap.get("orderbook_top") or {}
            ob_ts = _safe_int(ob.get("ts_ms") or ob.get("ts") or ob.get("timestamp"))
            if not ob:
                result.issues.append(ValidationIssue(symbol=sym, code="orderbook:missing"))
            elif ob_ts <= 0:
                result.issues.append(ValidationIssue(symbol=sym, code="orderbook:bad_ts"))
            elif (now_ms - ob_ts) > int(orderbook_stale_sec * 1000):
                age_s = (now_ms - ob_ts) / 1000.0
                result.issues.append(ValidationIssue(symbol=sym, code=f"orderbook:stale({age_s:.1f}s)"))

            for tf in tfs:
                period = tf_seconds.get(tf)
                base_floor = fast_tf_max_age_sec if tf in ("1m", "5m") else slow_tf_max_age_sec
                max_age = max(base_floor, float(period) * 2.0) if period else base_floor

                tf_snap = (sym_snap.get("timeframes") or {}).get(tf) or {}
                mkt = tf_snap.get("market") or {}
                if not mkt:
                    result.issues.append(ValidationIssue(symbol=sym, code=f"market_input:{tf}:missing"))
                else:
                    mkt_ts = _safe_int(mkt.get("timestamp") or mkt.get("ts_ms") or mkt.get("ts"))
                    if mkt_ts <= 0:
                        result.issues.append(ValidationIssue(symbol=sym, code=f"market_input:{tf}:bad_ts"))
                    elif (now_ms - mkt_ts) > int(max_age * 1000):
                        age_s = (now_ms - mkt_ts) / 1000.0
                        result.issues.append(ValidationIssue(symbol=sym, code=f"market_input:{tf}:stale({age_s:.0f}s)"))

                unified = tf_snap.get("unified") or {}
                if not unified:
                    result.issues.append(ValidationIssue(symbol=sym, code=f"unified:{tf}:missing"))
                else:
                    u_ts = _safe_int(unified.get("ts_ms") or unified.get("timestamp") or unified.get("ts"))
                    if u_ts <= 0:
                        result.issues.append(ValidationIssue(symbol=sym, code=f"unified:{tf}:bad_ts"))
                    elif (now_ms - u_ts) > int(max_age * 1000):
                        age_s = (now_ms - u_ts) / 1000.0
                        result.issues.append(ValidationIssue(symbol=sym, code=f"unified:{tf}:stale({age_s:.0f}s)"))

                ohlcv_list = tf_snap.get("ohlcv_list") or []
                if not ohlcv_list:
                    result.issues.append(ValidationIssue(symbol=sym, code=f"ohlcv_list:{tf}:missing"))
                elif len(ohlcv_list) < min_candles:
                    result.issues.append(
                        ValidationIssue(symbol=sym, code=f"ohlcv_list:{tf}:short({len(ohlcv_list)})")
                    )
        return result

    # ------------------------------------------------------------------
    # 5) Paralysis detector (anchor: legacy scripts/paralysis_detectors.py)
    # ------------------------------------------------------------------

    def detect_paralysis(
        self,
        events: Iterable[Tuple[int, Mapping[str, Any]]],
        *,
        window_minutes: float = PARALYSIS_DETECTOR_DEFAULT_MINUTES,
        reason_field: str = "reason_code",
        now_ms: Optional[int] = None,
    ) -> ParalysisResult:
        """Detect sustained-paralysis patterns and emit alerts.

        Sustained = present in every 1-minute bucket inside the window.
        Mirrors the legacy ``_window_reason_stats`` + ``_bucket_coverage`` logic
        with the same ``expected_buckets = max(1, int(window_minutes))`` rule.
        """
        expected_buckets = max(1, int(window_minutes))
        window_ms = int(max(60_000, window_minutes * 60_000))
        cutoff_ms = (int(now_ms) if now_ms is not None else 0) - window_ms

        per_reason: Counter = Counter()
        buckets_by_reason: Dict[str, set] = defaultdict(set)
        total = 0

        for ts_ms, payload in events:
            if now_ms is not None and ts_ms < cutoff_ms:
                continue
            total += 1
            reason = str(payload.get(reason_field) or "").strip() or "UNKNOWN"
            per_reason[reason] += 1
            buckets_by_reason[reason].add(int(ts_ms // 60_000))

        result = ParalysisResult(
            window_minutes=float(window_minutes),
            expected_buckets=expected_buckets,
            total_events=total,
            per_reason_counts=dict(per_reason),
        )
        for reason, count in per_reason.items():
            sustained = len(buckets_by_reason[reason])
            if sustained >= expected_buckets and count > 0:
                result.alerts.append(
                    ParalysisAlert(
                        reason=reason,
                        count=int(count),
                        sustained_buckets=int(sustained),
                    )
                )
        return result


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _orderbook_best_prices(ob: Mapping[str, Any]) -> Tuple[float, float]:
    if "bid" in ob and "ask" in ob:
        return _safe_float(ob.get("bid")), _safe_float(ob.get("ask"))
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    if (
        bids
        and asks
        and isinstance(bids[0], (list, tuple))
        and isinstance(asks[0], (list, tuple))
    ):
        return _safe_float(bids[0][0]), _safe_float(asks[0][0])
    return 0.0, 0.0


def _orderbook_imbalance(ob: Mapping[str, Any]) -> Optional[float]:
    if "imbalance" in ob and ob.get("imbalance") is not None:
        return _safe_float(ob.get("imbalance"))
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    if (
        bids
        and asks
        and isinstance(bids[0], (list, tuple))
        and isinstance(asks[0], (list, tuple))
    ):
        bid_sz = _safe_float(bids[0][1])
        ask_sz = _safe_float(asks[0][1])
        denom = (bid_sz + ask_sz) if (bid_sz + ask_sz) > 0 else 1.0
        return (bid_sz - ask_sz) / denom
    return None


def _sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / float(period)


def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    multiplier = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / float(period)
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _rsi(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) <= period or period <= 0:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / float(period)
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / float(period)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(values) < slow + signal:
        return None, None, None
    macd_series: List[float] = []
    for i in range(slow - 1, len(values)):
        window = values[: i + 1]
        ema_fast = _ema(window, fast)
        ema_slow = _ema(window, slow)
        if ema_fast is None or ema_slow is None:
            continue
        macd_series.append(ema_fast - ema_slow)
    if len(macd_series) < signal:
        return None, None, None
    signal_line = _ema(macd_series, signal)
    if signal_line is None:
        return None, None, None
    macd_line = macd_series[-1]
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> Optional[float]:
    if min(len(highs), len(lows), len(closes)) <= period or period <= 0:
        return None
    trs: List[float] = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / float(period)
    for tr in trs[period:]:
        atr = ((atr * (period - 1)) + tr) / float(period)
    return atr
