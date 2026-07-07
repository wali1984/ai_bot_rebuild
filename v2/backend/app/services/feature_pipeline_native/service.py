"""V2 Native Feature Pipeline (P0.1).

Computes feature snapshots from raw OHLCV + orderbook + funding/OI /
liquidation inputs. This is a native V2 computation, NOT a bridge that
re-reads legacy `features:*` Redis keys.

Legacy behavior sources consulted (read-only mirrors under
v2/legacy_owned_runtime/):

- feature_pipeline.py
    sha256=143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8
    size=69156
- rl/unified_feature_builder.py
    sha256=2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5
    size=29925
- rl/obs_schema.py
    sha256=9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f
    size=17346
- rl/tf_aggregator.py
    sha256=d20049f79b916723c59362bfb5cf0c74d4d8ae7cc0bf57f8a929b15b83c7f9f4
    size=6496
- rl/microstructure_features.py
    sha256=aca206e60f83a94ac2f447fb6aae6715c6b55ee573619100b6d20eae3dfca0d0
    size=20760
- rl/microstructure_aggregator.py
    sha256=355e26df9bab22b01b4b01ec17fa926c2dc81c33c18bd4799fbb41bbc713e74d
    size=17428
- rl/microstructure_overlay.py
    sha256=eff2a1e69f5b839e46e8cad2f7dd77eb2697723e1ed945acc643471550d34f3b
    size=50596
- rl/portfolio_aware_features.py
    sha256=4224832092df169348a34cfc7b53b23f429a730868e3b58d0517e5deb9d33d53
    size=18352
- rl/portfolio_risk_features.py
    sha256=9ba168b9e870486b6e1a19d022b445c1daad88d2f077a65b3861a8689f05c30f
    size=15814
- ingest/technical_analysis.py
    sha256=909437e7e77bcf6a03371c546b074a20e7a216bcd72b13ba783dcd78154dbee0
    size=34191

Feature categories implemented (every category is computed natively, not
read from legacy keys; absent input → explicit missing flag, never
fabricated):

- ohlcv_derived           (returns, log_return, range_pct, body_pct,
                           true_range_pct, gap_pct)
- ta_indicators            (EMA, RSI, MACD, ATR, Bollinger bands width)
- multi_timeframe          (closes_aggregated_to_higher_tf with policy)
- microstructure           (bid/ask spread bps, depth imbalance,
                           micro_price, toxicity_proxy)
- funding_oi_liquidation   (funding_rate, oi_change_pct, last_liq_bps_24h)
- portfolio_aware          (paper_position_present, paper_unrealized_bps,
                           paper_position_age_seconds)
- freshness                (each input's age_seconds, FRESH/STALE/MISSING)

Feature snapshot id = sha256 of the (sorted) feature value dict +
generation timestamp slot, providing chain-of-custody integrity.

Safety invariants enforced by current_paper_only_status():
- live_gate == "blocked_human_only"
- live_symbols == []
- approves_live == approves_canary == approves_legacy_shutdown == false
- old Redis writes attempted = 0 (service does not import a Redis client)
- exchange mutation reachable = false
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

FEATURE_PIPELINE_NATIVE_SCHEMA_VERSION = "1.0.0"

LIVE_GATE_STATUS = "blocked_human_only"

LEGACY_SOURCES = {
    "feature_pipeline.py": {
        "sha256": "143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8",
        "size_bytes": 69156,
        "v2_owned_path": "v2/legacy_owned_runtime/feature_pipeline.py",
    },
    "rl/unified_feature_builder.py": {
        "sha256": "2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5",
        "size_bytes": 29925,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/unified_feature_builder.py",
    },
    "rl/obs_schema.py": {
        "sha256": "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f",
        "size_bytes": 17346,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/obs_schema.py",
    },
    "rl/tf_aggregator.py": {
        "sha256": "d20049f79b916723c59362bfb5cf0c74d4d8ae7cc0bf57f8a929b15b83c7f9f4",
        "size_bytes": 6496,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/tf_aggregator.py",
    },
    "rl/microstructure_features.py": {
        "sha256": "aca206e60f83a94ac2f447fb6aae6715c6b55ee573619100b6d20eae3dfca0d0",
        "size_bytes": 20760,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/microstructure_features.py",
    },
    "rl/microstructure_aggregator.py": {
        "sha256": "355e26df9bab22b01b4b01ec17fa926c2dc81c33c18bd4799fbb41bbc713e74d",
        "size_bytes": 17428,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/microstructure_aggregator.py",
    },
    "rl/microstructure_overlay.py": {
        "sha256": "eff2a1e69f5b839e46e8cad2f7dd77eb2697723e1ed945acc643471550d34f3b",
        "size_bytes": 50596,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/microstructure_overlay.py",
    },
    "rl/portfolio_aware_features.py": {
        "sha256": "4224832092df169348a34cfc7b53b23f429a730868e3b58d0517e5deb9d33d53",
        "size_bytes": 18352,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/portfolio_aware_features.py",
    },
    "rl/portfolio_risk_features.py": {
        "sha256": "9ba168b9e870486b6e1a19d022b445c1daad88d2f077a65b3861a8689f05c30f",
        "size_bytes": 15814,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/portfolio_risk_features.py",
    },
    "ingest/technical_analysis.py": {
        "sha256": "909437e7e77bcf6a03371c546b074a20e7a216bcd72b13ba783dcd78154dbee0",
        "size_bytes": 34191,
        "v2_owned_path": "v2/legacy_owned_runtime/ingest/technical_analysis.py",
    },
}

FEATURE_CATEGORIES = (
    "ohlcv_derived",
    "ta_indicators",
    "multi_timeframe",
    "microstructure",
    "funding_oi_liquidation",
    "portfolio_aware",
    "freshness",
)


# --------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class NativeFeatureInputs:
    """Inputs the native pipeline computes against. All fields except
    symbol/timeframe/generated_utc are optional. Missing inputs produce
    explicit `missing_feature_flags`, not fabricated zeros.
    """
    symbol: str
    timeframe: str
    generated_utc: str

    # OHLCV window (newest last). Each entry: dict with open/high/low/close/volume.
    ohlcv_window: tuple[dict[str, float], ...] = ()
    ohlcv_window_age_seconds: int | None = None

    # Orderbook top of book
    bid_price: float | None = None
    ask_price: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    orderbook_age_seconds: int | None = None

    # Higher-timeframe close window (newest last).
    higher_tf_label: str | None = None
    higher_tf_close_window: tuple[float, ...] = ()
    higher_tf_age_seconds: int | None = None

    # Funding / OI / liquidation snapshot
    funding_rate: float | None = None
    funding_age_seconds: int | None = None
    open_interest: float | None = None
    open_interest_prior: float | None = None
    open_interest_age_seconds: int | None = None
    last_liquidation_notional_24h: float | None = None
    liquidation_age_seconds: int | None = None

    # Portfolio-aware (paper only)
    paper_position_notional: float | None = None
    paper_position_entry_price: float | None = None
    paper_position_age_seconds: int | None = None


# --------------------------------------------------------------------- helpers


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _freshness(age_seconds: int | None, *, max_fresh: int) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds < 0:
        return "STALE"
    return "FRESH" if age_seconds <= max_fresh else "STALE"


# --------------------------------------------------------------------- TA core


def _ema(values: list[float], period: int) -> float | None:
    if not values or period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period  # SMA seed
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, float | None]:
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "hist": None}
    # rolling EMA on full window
    def rolling_ema(vals: list[float], p: int) -> list[float]:
        out: list[float] = []
        k = 2.0 / (p + 1.0)
        seed = sum(vals[:p]) / p
        out.append(seed)
        for v in vals[p:]:
            out.append(v * k + out[-1] * (1.0 - k))
        return out
    ema_fast = rolling_ema(closes, fast)
    ema_slow = rolling_ema(closes, slow)
    # align lengths
    n = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-n + i] - ema_slow[-n + i] for i in range(n)]
    if len(macd_line) < signal:
        return {"macd": macd_line[-1] if macd_line else None, "signal": None, "hist": None}
    sig_line = rolling_ema(macd_line, signal)
    macd_v = macd_line[-1]
    sig_v = sig_line[-1]
    return {"macd": macd_v, "signal": sig_v, "hist": macd_v - sig_v}


def _atr_pct(ohlcv: list[dict[str, float]], period: int = 14) -> float | None:
    if len(ohlcv) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(ohlcv)):
        h = float(ohlcv[i]["high"])
        l = float(ohlcv[i]["low"])
        pc = float(ohlcv[i - 1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr = sum(trs[-period:]) / period
    last_close = float(ohlcv[-1]["close"])
    if last_close <= 0:
        return None
    return atr / last_close


def _atr_pct_series(
    ohlcv: list[dict[str, float]],
    period: int = 14,
) -> list[float]:
    if len(ohlcv) < period + 1:
        return []
    trs: list[float] = []
    for i in range(1, len(ohlcv)):
        h = float(ohlcv[i]["high"])
        l = float(ohlcv[i]["low"])
        pc = float(ohlcv[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out: list[float] = []
    for end in range(period, len(trs) + 1):
        close = float(ohlcv[end]["close"])
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


def _atr_percentile(
    ohlcv: list[dict[str, float]],
    *,
    period: int = 14,
    min_samples: int = 20,
) -> float | None:
    series = _atr_pct_series(ohlcv, period=period)
    if len(series) < min_samples:
        return None
    return _percentile_rank(series, series[-1])


def _bb_width_pct(closes: list[float], period: int = 20, k: float = 2.0) -> float | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    std = statistics.pstdev(window)
    if mean <= 0:
        return None
    upper = mean + k * std
    lower = mean - k * std
    return (upper - lower) / mean


# --------------------------------------------------------------------- compute


@dataclass(frozen=True)
class FeatureSnapshotResult:
    schema_version: str
    symbol: str
    timeframe: str
    generated_utc: str
    feature_snapshot_id: str
    feature_count: int
    categories_present: tuple[str, ...]
    missing_feature_flags: tuple[str, ...]
    stale_feature_flags: tuple[str, ...]
    source_inputs_age_seconds: dict[str, int | None]
    features: dict[str, float | int | None]


def feature_snapshot_id(symbol: str, timeframe: str, generated_utc: str,
                        features: dict[str, Any]) -> str:
    """SHA256 chain-of-custody id over the symbol, timeframe, timestamp
    slot, and the sorted feature dict.
    """
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_utc": generated_utc,
        "features": dict(sorted(features.items())),
    }
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"v2_fsnap_{h}"


def compute_feature_snapshot(inputs: NativeFeatureInputs, *,
                             ohlcv_max_age_seconds: int = 120,
                             orderbook_max_age_seconds: int = 30,
                             funding_max_age_seconds: int = 3600,
                             oi_max_age_seconds: int = 300,
                             liquidation_max_age_seconds: int = 3600,
                             paper_position_max_age_seconds: int = 300) -> FeatureSnapshotResult:
    features: dict[str, float | int | None] = {}
    missing: list[str] = []
    stale: list[str] = []
    categories_present: list[str] = []

    # ---- ohlcv_derived ----------------------------------------------------
    if inputs.ohlcv_window and len(inputs.ohlcv_window) >= 2:
        try:
            closes = [float(c["close"]) for c in inputs.ohlcv_window if c.get("close") is not None]
            opens = [float(c["open"]) for c in inputs.ohlcv_window if c.get("open") is not None]
            highs = [float(c["high"]) for c in inputs.ohlcv_window if c.get("high") is not None]
            lows = [float(c["low"]) for c in inputs.ohlcv_window if c.get("low") is not None]
            if len(closes) >= 2 and closes[-2] > 0:
                features["ret_pct"] = (closes[-1] - closes[-2]) / closes[-2]
                features["log_return"] = math.log(closes[-1] / closes[-2]) if closes[-1] > 0 else None
            else:
                missing.append("ohlcv_returns")
            if highs and lows and closes:
                last_close = closes[-1]
                features["range_pct"] = (highs[-1] - lows[-1]) / last_close if last_close > 0 else None
                features["body_pct"] = (closes[-1] - opens[-1]) / last_close if last_close > 0 else None
            else:
                missing.append("ohlcv_range_body")
            atr = _atr_pct(list(inputs.ohlcv_window))
            features["true_range_pct"] = atr if atr is not None else None
            if atr is None:
                missing.append("ohlcv_true_range")
            atr_percentile = _atr_percentile(list(inputs.ohlcv_window))
            features["atr_percentile"] = atr_percentile
            if atr_percentile is None:
                missing.append("ohlcv_atr_percentile")
            if len(closes) >= 2 and closes[-2] > 0:
                features["gap_pct"] = (opens[-1] - closes[-2]) / closes[-2]
            else:
                missing.append("ohlcv_gap")
            categories_present.append("ohlcv_derived")
        except Exception:
            missing.append("ohlcv_derived_exception")
    else:
        missing.extend([
            "ohlcv_returns",
            "ohlcv_range_body",
            "ohlcv_true_range",
            "ohlcv_atr_percentile",
            "ohlcv_gap",
        ])
    if _freshness(inputs.ohlcv_window_age_seconds, max_fresh=ohlcv_max_age_seconds) == "STALE":
        stale.append("ohlcv_window")

    # ---- ta_indicators ----------------------------------------------------
    closes = [float(c["close"]) for c in inputs.ohlcv_window if c.get("close") is not None]
    if len(closes) >= 26:
        features["ema_12"] = _ema(closes, 12)
        features["ema_26"] = _ema(closes, 26)
        features["rsi_14"] = _rsi(closes, 14)
        macd = _macd(closes)
        features["macd"] = macd.get("macd")
        features["macd_signal"] = macd.get("signal")
        features["macd_hist"] = macd.get("hist")
        features["bb_width_pct"] = _bb_width_pct(closes)
        categories_present.append("ta_indicators")
    else:
        missing.extend(["ema_12", "ema_26", "rsi_14", "macd", "bb_width_pct"])

    # ---- multi_timeframe --------------------------------------------------
    if inputs.higher_tf_close_window and len(inputs.higher_tf_close_window) >= 2:
        htf = list(inputs.higher_tf_close_window)
        if htf[-2] > 0:
            features["htf_ret_pct"] = (htf[-1] - htf[-2]) / htf[-2]
        if len(htf) >= 14:
            features["htf_rsi_14"] = _rsi(htf, 14)
        categories_present.append("multi_timeframe")
    else:
        missing.append("multi_timeframe_higher_tf_window")
    if _freshness(inputs.higher_tf_age_seconds, max_fresh=ohlcv_max_age_seconds * 4) == "STALE":
        stale.append("higher_tf_window")

    # ---- microstructure ---------------------------------------------------
    bid = _safe_float(inputs.bid_price)
    ask = _safe_float(inputs.ask_price)
    bsize = _safe_float(inputs.bid_size)
    asize = _safe_float(inputs.ask_size)
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        features["bid_ask_spread_bps"] = ((ask - bid) / mid) * 10000.0
        if bsize is not None and asize is not None and (bsize + asize) > 0:
            features["micro_price"] = (bid * asize + ask * bsize) / (bsize + asize)
            features["depth_imbalance"] = (bsize - asize) / (bsize + asize)
        else:
            features["micro_price"] = mid
            missing.append("orderbook_depth_sizes")
        spread_norm = min(features["bid_ask_spread_bps"] / 50.0, 1.0)
        di = features.get("depth_imbalance")
        if di is not None:
            features["toxicity_proxy"] = max(0.0, min(1.0, 0.5 * spread_norm + 0.5 * min(abs(di), 1.0)))
        else:
            features["toxicity_proxy"] = max(0.0, min(1.0, spread_norm))
        categories_present.append("microstructure")
    else:
        missing.extend(["bid_ask_spread_bps", "micro_price", "depth_imbalance", "toxicity_proxy"])
    if _freshness(inputs.orderbook_age_seconds, max_fresh=orderbook_max_age_seconds) == "STALE":
        stale.append("orderbook")

    # ---- funding_oi_liquidation -------------------------------------------
    funding = _safe_float(inputs.funding_rate)
    if funding is not None:
        features["funding_rate"] = funding
    else:
        missing.append("funding_rate")
    oi = _safe_float(inputs.open_interest)
    oi_prior = _safe_float(inputs.open_interest_prior)
    if oi is not None and oi_prior is not None and oi_prior > 0:
        features["oi_change_pct"] = (oi - oi_prior) / oi_prior
    else:
        missing.append("oi_change_pct")
    liq = _safe_float(inputs.last_liquidation_notional_24h)
    last_close = closes[-1] if closes else None
    if liq is not None and last_close and last_close > 0:
        features["last_liq_bps_24h"] = (liq / last_close) * 10000.0
    else:
        missing.append("last_liq_bps_24h")
    if any(features.get(k) is not None for k in ("funding_rate", "oi_change_pct", "last_liq_bps_24h")):
        categories_present.append("funding_oi_liquidation")
    if _freshness(inputs.funding_age_seconds, max_fresh=funding_max_age_seconds) == "STALE":
        stale.append("funding")
    if _freshness(inputs.open_interest_age_seconds, max_fresh=oi_max_age_seconds) == "STALE":
        stale.append("open_interest")
    if _freshness(inputs.liquidation_age_seconds, max_fresh=liquidation_max_age_seconds) == "STALE":
        stale.append("liquidation")

    # ---- portfolio_aware --------------------------------------------------
    pos_notional = _safe_float(inputs.paper_position_notional)
    pos_entry = _safe_float(inputs.paper_position_entry_price)
    if pos_notional is not None and pos_notional != 0:
        features["paper_position_present"] = 1
        features["paper_position_notional"] = pos_notional
        if pos_entry is not None and pos_entry > 0 and last_close and last_close > 0:
            features["paper_unrealized_bps"] = ((last_close - pos_entry) / pos_entry) * 10000.0 * (1 if pos_notional > 0 else -1)
        features["paper_position_age_seconds"] = inputs.paper_position_age_seconds
        categories_present.append("portfolio_aware")
    else:
        features["paper_position_present"] = 0
        categories_present.append("portfolio_aware")  # explicit empty is a valid present state
    if _freshness(inputs.paper_position_age_seconds, max_fresh=paper_position_max_age_seconds) == "STALE":
        stale.append("paper_position")

    # ---- freshness category is always present (it tracks the others) ------
    categories_present.append("freshness")

    source_inputs_age = {
        "ohlcv_window": inputs.ohlcv_window_age_seconds,
        "orderbook": inputs.orderbook_age_seconds,
        "higher_tf_window": inputs.higher_tf_age_seconds,
        "funding": inputs.funding_age_seconds,
        "open_interest": inputs.open_interest_age_seconds,
        "liquidation": inputs.liquidation_age_seconds,
        "paper_position": inputs.paper_position_age_seconds,
    }

    snap_id = feature_snapshot_id(inputs.symbol, inputs.timeframe, inputs.generated_utc, features)

    return FeatureSnapshotResult(
        schema_version=FEATURE_PIPELINE_NATIVE_SCHEMA_VERSION,
        symbol=inputs.symbol,
        timeframe=inputs.timeframe,
        generated_utc=inputs.generated_utc,
        feature_snapshot_id=snap_id,
        feature_count=len(features),
        categories_present=tuple(dict.fromkeys(categories_present)),
        missing_feature_flags=tuple(missing),
        stale_feature_flags=tuple(stale),
        source_inputs_age_seconds=source_inputs_age,
        features=features,
    )


# --------------------------------------------------------------------- service


@dataclass
class FeaturePipelineNativeService:
    """Native V2 feature pipeline service facade."""

    ohlcv_max_age_seconds: int = 120
    orderbook_max_age_seconds: int = 30
    funding_max_age_seconds: int = 3600
    oi_max_age_seconds: int = 300
    liquidation_max_age_seconds: int = 3600
    paper_position_max_age_seconds: int = 300

    def compute(self, inputs: NativeFeatureInputs) -> dict[str, Any]:
        result = compute_feature_snapshot(
            inputs,
            ohlcv_max_age_seconds=self.ohlcv_max_age_seconds,
            orderbook_max_age_seconds=self.orderbook_max_age_seconds,
            funding_max_age_seconds=self.funding_max_age_seconds,
            oi_max_age_seconds=self.oi_max_age_seconds,
            liquidation_max_age_seconds=self.liquidation_max_age_seconds,
            paper_position_max_age_seconds=self.paper_position_max_age_seconds,
        )
        # asdict converts the snapshot to a plain dict for JSON emission.
        out = asdict(result)
        out["legacy_behavior_mapping"] = {k: v for k, v in LEGACY_SOURCES.items()}
        out["live_gate"] = LIVE_GATE_STATUS
        out["live_symbols"] = []
        return out

    def emit_trainer_consumable_snapshot(self, inputs: NativeFeatureInputs) -> dict[str, Any]:
        """Produce a trainer-consumable snapshot payload.

        Schema: v2_native_feature_snapshot_v1. Includes the full feature
        dict, snapshot id, categories present, explicit missing/stale
        flag arrays, source freshness, an overall feature_freshness_state,
        and the trainer_consumable=true marker.
        """
        result = compute_feature_snapshot(
            inputs,
            ohlcv_max_age_seconds=self.ohlcv_max_age_seconds,
            orderbook_max_age_seconds=self.orderbook_max_age_seconds,
            funding_max_age_seconds=self.funding_max_age_seconds,
            oi_max_age_seconds=self.oi_max_age_seconds,
            liquidation_max_age_seconds=self.liquidation_max_age_seconds,
            paper_position_max_age_seconds=self.paper_position_max_age_seconds,
        )
        any_input_present = any(v is not None for v in result.source_inputs_age_seconds.values())
        if result.stale_feature_flags:
            freshness_state = "STALE"
        elif not any_input_present:
            freshness_state = "MISSING"
        else:
            freshness_state = "CURRENT"
        return {
            "schema_version": "v2_native_feature_snapshot_v1",
            "worker_id": "v2_feature_pipeline_native",
            "feature_snapshot_id": result.feature_snapshot_id,
            "generated_at": result.generated_utc,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "features": result.features,
            "feature_count": result.feature_count,
            "categories_present": list(result.categories_present),
            "missing_feature_flags": list(result.missing_feature_flags),
            "stale_feature_flags": list(result.stale_feature_flags),
            "source_inputs": {
                "ohlcv_bar_count": len(inputs.ohlcv_window),
                "higher_tf_bar_count": len(inputs.higher_tf_close_window),
                "orderbook_present": inputs.bid_price is not None and inputs.ask_price is not None,
                "funding_present": inputs.funding_rate is not None,
                "open_interest_present": inputs.open_interest is not None,
                "liquidation_present": inputs.last_liquidation_notional_24h is not None,
                "paper_position_present": inputs.paper_position_notional is not None,
                "higher_tf_label": inputs.higher_tf_label,
            },
            "source_freshness_seconds": result.source_inputs_age_seconds,
            "feature_freshness_state": freshness_state,
            "trainer_consumable": True,
            "legacy_behavior_mapping": LEGACY_SOURCES,
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }

    def build_deterministic_default_inputs(self, symbol: str, timeframe: str, generated_utc: str) -> NativeFeatureInputs:
        """Build a deterministic default input set so the CLI can emit a
        trainer-consumable snapshot without requiring upstream data.

        Defaults seed a 60-bar OHLCV ramp, a balanced orderbook, a
        higher-timeframe window, funding/OI/liquidation snapshots, and
        no paper position. Ages are small (FRESH).
        """
        base = 100.0
        ohlcv = tuple(
            {
                "open": base + i * 0.5 - 0.1,
                "high": base + i * 0.5 + 0.4,
                "low": base + i * 0.5 - 0.5,
                "close": base + i * 0.5,
                "volume": 1000.0 + i,
            }
            for i in range(60)
        )
        higher = tuple(base + i for i in range(20))
        return NativeFeatureInputs(
            symbol=symbol,
            timeframe=timeframe,
            generated_utc=generated_utc,
            ohlcv_window=ohlcv,
            ohlcv_window_age_seconds=5,
            bid_price=base + 30 * 0.5 - 0.05,
            ask_price=base + 30 * 0.5 + 0.05,
            bid_size=10.0,
            ask_size=10.0,
            orderbook_age_seconds=1,
            higher_tf_label="15m",
            higher_tf_close_window=higher,
            higher_tf_age_seconds=30,
            funding_rate=0.0001,
            funding_age_seconds=120,
            open_interest=1_000_000.0,
            open_interest_prior=950_000.0,
            open_interest_age_seconds=60,
            last_liquidation_notional_24h=50_000.0,
            liquidation_age_seconds=120,
            paper_position_notional=None,
            paper_position_entry_price=None,
            paper_position_age_seconds=None,
        )

    def current_paper_only_status(self) -> dict[str, Any]:
        return {
            "worker_id": "v2_feature_pipeline_native",
            "schema_version": FEATURE_PIPELINE_NATIVE_SCHEMA_VERSION,
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "scope": "PAPER_ONLY_NATIVE_COMPUTATION",
            "is_bridge_only": False,
            "reads_legacy_features_keys_as_authoritative": False,
            "writes_to_legacy_redis": False,
            "exchange_mutation_reachable": False,
            "feature_categories_implemented": list(FEATURE_CATEGORIES),
            "feature_snapshot_id_emitted": True,
            "legacy_behavior_mapping": LEGACY_SOURCES,
            "migration_classification": "PARTIALLY_MIGRATED",
            "components_ported": [
                "ohlcv_derived_returns_log_return_range_body_true_range_gap",
                "ta_indicators_ema_rsi_macd_bb_width",
                "multi_timeframe_higher_tf_returns_rsi",
                "microstructure_spread_imbalance_micro_price_toxicity",
                "funding_oi_liquidation_derived_features",
                "portfolio_aware_paper_position_features",
                "freshness_fresh_stale_missing_flags",
                "feature_snapshot_id_sha256_chain_of_custody",
                "explicit_missing_feature_flags",
            ],
            "components_missing": [
                "full_legacy_unified_feature_builder_2000_plus_features",
                "regime_state_machine_hysteresis",
                "ingestor_layer_native_websocket_rest",
                "cross_exchange_aggregation",
                "tokenmetrics_alphavantage_derived_features",
            ],
            "contract_ref": "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
        }
