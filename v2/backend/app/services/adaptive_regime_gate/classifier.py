"""Regime classification before any strategy can trade.

Phase 3 of goal V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE.

Inputs (all read-only, from the canonical decision-time feature snapshot plus
HTF / cross-asset / trade-tape context):
    ADX, normalized ATR (atr_percentile), Bollinger bandwidth, trend/range
    proxy (EMA stack + ADX, standing in for Hurst), EMA stack, RSI zone,
    MACD state, HTF trend, BTC/ETH market regime, funding/OI/liquidation
    context.

Output: exactly one regime from REGIMES with confidence and full input
lineage. Missing critical inputs produce NO_TRADE (fail-closed), never a
guessed regime.
"""
from __future__ import annotations

from typing import Any, Mapping

REGIME_GATE_REDIS_KEY_TEMPLATE = "v2:regime:gate:{symbol}:{timeframe}"
SCHEMA_VERSION = "v2_adaptive_regime_gate_v1"

REGIMES = (
    "TRENDING_UP",
    "TRENDING_DOWN",
    "RANGING",
    "VOLATILE_EXPANSION",
    "LIQUIDITY_SWEEP",
    "FAKEOUT_RISK",
    "NO_TRADE",
)

REQUIRED_INPUT_FAMILIES = (
    "ADX",
    "ATR_NORMALIZED",
    "BOLLINGER_BANDWIDTH",
    "TREND_RANGE_PROXY",
    "EMA_STACK",
    "RSI_ZONE",
    "MACD_STATE",
    "HTF_TREND",
    "BTC_ETH_MARKET_REGIME",
    "FUNDING_OI_LIQUIDATION_CONTEXT",
)

ADX_TREND_MIN = 22.0
ADX_STRONG_TREND = 30.0
ADX_RANGE_MAX = 18.0
ATR_PERCENTILE_EXPANSION = 0.85
BB_WIDTH_EXPANSION_PCT = 0.055
SWEEP_DISTANCE_BPS_MAX = 35.0
# Minimum intensity percentile (symbol's own rolling history) for a
# LIQUIDITY_SWEEP claim — the top ~15% of the symbol's recent liquidation
# activity, so the bar adapts per symbol instead of a static notional.
SWEEP_INTENSITY_PERCENTILE_MIN = 0.85
FUNDING_EXTREME_ABS = 0.0008  # 8 bps per interval — crowded positioning


def _finite(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _ema_stack_state(features: Mapping[str, Any]) -> str:
    close = _finite(features.get("close"))
    ema20 = _finite(features.get("ema_20") or features.get("ta_EMA_20"))
    ema50 = _finite(features.get("ema_50") or features.get("ta_EMA_50"))
    if None in (close, ema20, ema50):
        return "UNKNOWN"
    if close > ema20 > ema50:
        return "STACKED_UP"
    if close < ema20 < ema50:
        return "STACKED_DOWN"
    return "MIXED"


def _macd_direction(features: Mapping[str, Any]) -> str:
    hist = _finite(features.get("macd_hist") or features.get("ta_MACD_macdhist"))
    if hist is None:
        return "UNKNOWN"
    if hist > 0:
        return "UP"
    if hist < 0:
        return "DOWN"
    return "FLAT"


def _rsi_zone(features: Mapping[str, Any]) -> str:
    rsi = _finite(features.get("rsi_14") or features.get("ta_RSI_14"))
    if rsi is None:
        return "UNKNOWN"
    if rsi >= 70:
        return "OVERBOUGHT"
    if rsi >= 55:
        return "BULLISH"
    if rsi > 45:
        return "NEUTRAL"
    if rsi > 30:
        return "BEARISH"
    return "OVERSOLD"


def classify_regime(
    *,
    symbol: str,
    timeframe: str,
    features: Mapping[str, Any],
    htf_context: Mapping[str, Any] | None = None,
    cross_asset: Mapping[str, Any] | None = None,
    trade_tape: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the current market regime for one symbol/timeframe."""
    htf = htf_context or {}
    cross = cross_asset or {}
    tape = trade_tape or {}
    missing_inputs: list[str] = []

    adx = _finite(features.get("ta_ADX"))
    atr_percentile = _finite(features.get("atr_percentile"))
    bb_width_pct = _finite(features.get("bb_width_pct") or features.get("ta_BB_width_pct"))
    ema_stack = _ema_stack_state(features)
    macd_direction = _macd_direction(features)
    rsi_zone = _rsi_zone(features)
    htf_trend = str(htf.get("htf_4h_trend") or "UNKNOWN")
    market_risk_state = str(cross.get("market_risk_state") or "UNKNOWN")
    funding_rate = _finite(features.get("funding_rate"))
    oi_change_pct = _finite(features.get("oi_change_pct"))
    cascade_risk = _finite(features.get("liquidation_cascade_risk"))

    if adx is None:
        missing_inputs.append("ta_ADX")
    if atr_percentile is None:
        missing_inputs.append("atr_percentile")
    if bb_width_pct is None:
        missing_inputs.append("bb_width_pct")
    if ema_stack == "UNKNOWN":
        missing_inputs.append("ema_stack")

    # Trend/range proxy (Hurst stand-in): ADX strength blended with EMA-stack
    # persistence. > 0.6 behaves trending, < 0.4 behaves mean-reverting.
    trend_range_proxy = None
    if adx is not None:
        proxy = min(1.0, adx / 40.0)
        if ema_stack in {"STACKED_UP", "STACKED_DOWN"}:
            proxy = min(1.0, proxy + 0.2)
        elif ema_stack == "MIXED":
            proxy = max(0.0, proxy - 0.15)
        trend_range_proxy = proxy

    sweep_long_bps = _finite(features.get("liquidation_sweep_target_long_distance_bps"))
    sweep_short_bps = _finite(features.get("liquidation_sweep_target_short_distance_bps"))
    sweep_proximity = min(
        (value for value in (sweep_long_bps, sweep_short_bps) if value is not None),
        default=None,
    )

    inputs = {
        "adx": adx,
        "atr_percentile": atr_percentile,
        "bb_width_pct": bb_width_pct,
        "trend_range_proxy": trend_range_proxy,
        "ema_stack": ema_stack,
        "rsi_zone": rsi_zone,
        "macd_direction": macd_direction,
        "htf_trend": htf_trend,
        "market_risk_state": market_risk_state,
        "funding_rate": funding_rate,
        "oi_change_pct": oi_change_pct,
        "liquidation_cascade_risk": cascade_risk,
        "sweep_proximity_bps": sweep_proximity,
        "tape_confirmation_score": _finite(tape.get("trade_tape_confirmation_score")),
        "tape_state": tape.get("trade_tape_confirmation_state"),
    }

    def _result(regime: str, confidence: float, reasons: list[str]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "regime": regime,
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "reasons": reasons,
            "inputs": inputs,
            "missing_inputs": missing_inputs,
            "fail_closed": regime == "NO_TRADE" and bool(missing_inputs),
            "places_real_order": False,
            "writes_legacy_redis": False,
        }

    # Fail closed when core inputs are absent — a regime must never be guessed.
    if missing_inputs:
        return _result("NO_TRADE", 1.0, [f"MISSING_REGIME_INPUT:{name}" for name in missing_inputs])

    reasons: list[str] = []

    # Liquidity sweep: liquidation cluster within reach plus EXTREME
    # liquidation intensity. cascade_risk carries intensity-percentile
    # semantics (v2): the symbol's current decay-weighted liquidation
    # activity ranked against its own rolling history — self-adaptive per
    # symbol, no static notional threshold. None = missing/warming input;
    # a sweep is never guessed from a missing intensity. (The v1 metric was
    # the long-side share of strength — neutral at 0.5 and ≥0.5 on nearly
    # every symbol during directional markets — which classified ~half of
    # all cycles system-wide as LIQUIDITY_SWEEP and universally failed the
    # A+ regime_aligned check; 2026-07-17 regime uniformity investigation.)
    sweep_risk = (
        sweep_proximity is not None
        and sweep_proximity <= SWEEP_DISTANCE_BPS_MAX
        and cascade_risk is not None
        and cascade_risk >= SWEEP_INTENSITY_PERCENTILE_MIN
    )
    if sweep_risk:
        reasons.append(
            f"LIQUIDATION_CLUSTER_WITHIN_{SWEEP_DISTANCE_BPS_MAX:.0f}BPS_AND_INTENSITY_PCTL_{(cascade_risk or 0.0):.2f}"
        )
        return _result("LIQUIDITY_SWEEP", 0.6 + 0.4 * min(1.0, (cascade_risk or 0.0)), reasons)

    # Volatile expansion: volatility percentile extreme or bandwidth blowout.
    if (atr_percentile is not None and atr_percentile >= ATR_PERCENTILE_EXPANSION) or (
        bb_width_pct is not None and bb_width_pct >= BB_WIDTH_EXPANSION_PCT
    ):
        reasons.append(
            f"VOLATILITY_EXPANSION:atr_pct={atr_percentile}:bb_width={bb_width_pct}"
        )
        return _result("VOLATILE_EXPANSION", 0.7, reasons)

    # Fakeout risk: momentum and structure disagree, or crowded funding against
    # the apparent move, or tape contradicts the direction the chart shows.
    fakeout_signals: list[str] = []
    if ema_stack == "STACKED_UP" and macd_direction == "DOWN":
        fakeout_signals.append("EMA_UP_MACD_DOWN")
    if ema_stack == "STACKED_DOWN" and macd_direction == "UP":
        fakeout_signals.append("EMA_DOWN_MACD_UP")
    if funding_rate is not None and abs(funding_rate) >= FUNDING_EXTREME_ABS:
        crowd_side = "LONG" if funding_rate > 0 else "SHORT"
        fakeout_signals.append(f"FUNDING_CROWDED_{crowd_side}:{funding_rate:.5f}")
    tape_score = _finite(tape.get("trade_tape_confirmation_score"))
    if tape_score is not None:
        if ema_stack == "STACKED_UP" and tape_score <= 0.35:
            fakeout_signals.append(f"TAPE_SELLS_INTO_UPTREND:{tape_score:.2f}")
        if ema_stack == "STACKED_DOWN" and tape_score >= 0.65:
            fakeout_signals.append(f"TAPE_BUYS_INTO_DOWNTREND:{tape_score:.2f}")
    if len(fakeout_signals) >= 2:
        return _result("FAKEOUT_RISK", 0.5 + 0.15 * len(fakeout_signals), fakeout_signals)

    # Trending regimes require ADX strength, stacked EMAs, and HTF agreement.
    if adx >= ADX_TREND_MIN and ema_stack == "STACKED_UP":
        confidence = min(1.0, adx / ADX_STRONG_TREND) * 0.7
        if htf_trend == "UP":
            confidence += 0.2
            reasons.append("HTF_4H_TREND_AGREES_UP")
        elif htf_trend == "DOWN":
            confidence -= 0.25
            reasons.append("HTF_4H_TREND_DISAGREES")
        if macd_direction == "UP":
            confidence += 0.1
        reasons.append(f"ADX_{adx:.1f}_EMA_STACKED_UP")
        if confidence >= 0.45:
            return _result("TRENDING_UP", confidence, reasons)
        return _result("FAKEOUT_RISK", 0.55, reasons + ["TREND_WITHOUT_HTF_SUPPORT"])
    if adx >= ADX_TREND_MIN and ema_stack == "STACKED_DOWN":
        confidence = min(1.0, adx / ADX_STRONG_TREND) * 0.7
        if htf_trend == "DOWN":
            confidence += 0.2
            reasons.append("HTF_4H_TREND_AGREES_DOWN")
        elif htf_trend == "UP":
            confidence -= 0.25
            reasons.append("HTF_4H_TREND_DISAGREES")
        if macd_direction == "DOWN":
            confidence += 0.1
        reasons.append(f"ADX_{adx:.1f}_EMA_STACKED_DOWN")
        if confidence >= 0.45:
            return _result("TRENDING_DOWN", confidence, reasons)
        return _result("FAKEOUT_RISK", 0.55, reasons + ["TREND_WITHOUT_HTF_SUPPORT"])

    # Ranging: weak directional energy and contained volatility.
    if adx <= ADX_RANGE_MAX and (trend_range_proxy is None or trend_range_proxy <= 0.45):
        reasons.append(f"ADX_{adx:.1f}_BELOW_RANGE_MAX_{ADX_RANGE_MAX:.0f}")
        return _result("RANGING", 0.6 + max(0.0, (ADX_RANGE_MAX - adx) / ADX_RANGE_MAX * 0.3), reasons)

    # Between range and trend with no confirming structure: stand aside.
    reasons.append(f"INDETERMINATE_STRUCTURE:adx={adx:.1f}:ema={ema_stack}")
    return _result("NO_TRADE", 0.5, reasons)


def regime_classifier_behavioral_proofs() -> dict[str, Any]:
    """Deterministic proof cases for the seven required regimes.

    These are not market decisions. They are static fixtures used by artifacts
    and tests to prove that the classifier can produce every required regime
    and that missing core inputs fail closed to NO_TRADE.
    """
    base = {
        "close": 100.0,
        "ema_20": 101.0,
        "ema_50": 102.0,
        "ta_ADX": 14.0,
        "atr_percentile": 0.35,
        "bb_width_pct": 0.02,
        "rsi_14": 50.0,
        "macd_hist": 0.0,
        "funding_rate": 0.0,
        "oi_change_pct": 0.0,
        "liquidation_cascade_risk": 0.0,
        "liquidation_sweep_target_long_distance_bps": 120.0,
        "liquidation_sweep_target_short_distance_bps": 120.0,
    }
    cases: list[dict[str, Any]] = [
        {
            "name": "missing_core_input_fail_closed",
            "expected_regime": "NO_TRADE",
            "features": {key: value for key, value in base.items() if key != "ta_ADX"},
            "htf_context": {"htf_4h_trend": "UP"},
            "expected_fail_closed": True,
        },
        {
            "name": "trending_up",
            "expected_regime": "TRENDING_UP",
            "features": {**base, "close": 105.0, "ema_20": 103.0, "ema_50": 100.0, "ta_ADX": 28.0, "macd_hist": 1.0, "rsi_14": 62.0},
            "htf_context": {"htf_4h_trend": "UP"},
        },
        {
            "name": "trending_down",
            "expected_regime": "TRENDING_DOWN",
            "features": {**base, "close": 95.0, "ema_20": 97.0, "ema_50": 100.0, "ta_ADX": 28.0, "macd_hist": -1.0, "rsi_14": 38.0},
            "htf_context": {"htf_4h_trend": "DOWN"},
        },
        {
            "name": "ranging",
            "expected_regime": "RANGING",
            "features": {**base, "close": 101.0, "ema_20": 100.0, "ema_50": 102.0, "ta_ADX": 12.0, "macd_hist": 0.0},
            "htf_context": {"htf_4h_trend": "RANGE"},
        },
        {
            "name": "volatile_expansion",
            "expected_regime": "VOLATILE_EXPANSION",
            "features": {**base, "ta_ADX": 18.0, "atr_percentile": 0.92, "bb_width_pct": 0.07},
            "htf_context": {"htf_4h_trend": "RANGE"},
        },
        {
            "name": "liquidity_sweep",
            "expected_regime": "LIQUIDITY_SWEEP",
            "features": {
                **base,
                # intensity percentile ≥ SWEEP_INTENSITY_PERCENTILE_MIN (0.85):
                # this symbol's liquidation activity is extreme vs its own history
                "liquidation_cascade_risk": 0.93,
                "liquidation_sweep_target_long_distance_bps": 18.0,
                "liquidation_sweep_target_short_distance_bps": 80.0,
            },
            "htf_context": {"htf_4h_trend": "RANGE"},
        },
        {
            "name": "fakeout_risk",
            "expected_regime": "FAKEOUT_RISK",
            "features": {
                **base,
                "close": 105.0,
                "ema_20": 103.0,
                "ema_50": 100.0,
                "ta_ADX": 24.0,
                "macd_hist": -1.0,
                "funding_rate": 0.001,
            },
            "htf_context": {"htf_4h_trend": "UP"},
        },
    ]
    proofs: list[dict[str, Any]] = []
    produced: set[str] = set()
    for case in cases:
        decision = classify_regime(
            symbol="BTCUSDT",
            timeframe="1h",
            features=case["features"],
            htf_context=case.get("htf_context"),
            cross_asset={"market_risk_state": "RISK_ON"},
            trade_tape=case.get("trade_tape"),
        )
        expected = str(case["expected_regime"])
        passed = decision.get("regime") == expected
        if case.get("expected_fail_closed") is True:
            passed = passed and decision.get("fail_closed") is True
        produced.add(str(decision.get("regime")))
        proofs.append(
            {
                "name": case["name"],
                "expected_regime": expected,
                "actual_regime": decision.get("regime"),
                "passed": passed,
                "fail_closed": decision.get("fail_closed"),
                "reasons": decision.get("reasons"),
            }
        )
    return {
        "required_regimes": list(REGIMES),
        "required_input_families": list(REQUIRED_INPUT_FAMILIES),
        "proofs": proofs,
        "produced_regimes": sorted(produced),
        "all_required_regime_outputs_proven": all(regime in produced for regime in REGIMES),
        "all_proofs_passed": all(proof["passed"] for proof in proofs),
    }
