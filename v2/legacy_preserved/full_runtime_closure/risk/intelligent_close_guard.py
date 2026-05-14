"""
risk/intelligent_close_guard.py — Data-Driven Auto-Close Guard.

PURPOSE:
  Before PER_LEG_ROI_KILL, PROACTIVE_SOFT_REDUCE, or AutoDeleverager closes
  a position, this guard consults ALL available real-time data to determine
  if the close is truly justified or if the position should be held.

DATA SOURCES CONSULTED (in order of weight):
  1. regime:{symbol}         — move_regime, trend_direction, tf_alignment,
                               volatility_score, liq_risk, liquidity_score
  2. unified_features        — 2000+ feature keys (TA-lib, orderbook,
                               CoinAnk, liquidations) across multiple TFs
  3. msnap:coinapi_wsds      — Live CoinAPI WebSocket orderbook/microstructure
  4. trainer:intent:{symbol} — Trainer's directional intent + confidence
  5. prediction:{symbol}:*   — Per-TF predictions for multi-timeframe consensus

DECISION:
  Computes a "hold_score" 0.0–1.0 representing how strongly the data
  supports keeping the position open.  Above a threshold → DEFER (don't close).
  Below → ALLOW (proceed with close).

  HARD EMERGENCY (MU>85% or IM>85%) bypasses the guard entirely — survival
  takes priority over intelligence.

Kill-switch:  config.INTELLIGENT_CLOSE_GUARD_ENABLED  (default: True)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _cfg(name: str, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def _sf(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _decode_map(raw: dict) -> Dict[str, str]:
    if not raw:
        return {}
    out = {}
    for k, v in raw.items():
        kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
        vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)
        out[kk] = vv
    return out


@dataclass
class CloseGuardVerdict:
    """Result from the intelligent close guard."""
    action: str          # "ALLOW_CLOSE", "DEFER_CLOSE"
    hold_score: float    # 0.0–1.0 (higher = stronger case to keep position)
    reason: str          # Human-readable explanation
    components: Dict[str, float]  # Individual score components for debugging
    data_sources_used: int  # How many data sources contributed

    @property
    def should_defer(self) -> bool:
        return self.action == "DEFER_CLOSE"


def _now_ms() -> int:
    try:
        return int(time.time() * 1000)
    except Exception:
        return 0


def _ts_to_ms(ts_val: Any) -> int:
    """
    Best-effort conversion of timestamp-like values to epoch milliseconds.
    Supports:
      - int/float epoch seconds or ms
      - numeric strings
    """
    try:
        if ts_val is None:
            return 0
        if isinstance(ts_val, (bytes, bytearray)):
            ts_val = ts_val.decode("utf-8", errors="ignore")
        if isinstance(ts_val, str):
            s = ts_val.strip()
            if not s:
                return 0
            ts_val = float(s) if ("." in s) else int(s)
        v = float(ts_val)
        if v <= 0:
            return 0
        # Heuristic: >= 1e12 is already ms, else seconds.
        return int(v) if v >= 1e12 else int(v * 1000.0)
    except Exception:
        return 0


def _age_ms(ts_ms: int, now_ms: Optional[int] = None) -> Optional[int]:
    try:
        if ts_ms <= 0:
            return None
        n = int(now_ms) if now_ms is not None else _now_ms()
        if n <= 0:
            return None
        return max(0, n - int(ts_ms))
    except Exception:
        return None


def _is_fresh(ts_ms: int, *, max_age_ms: int, now_ms: Optional[int] = None) -> bool:
    a = _age_ms(ts_ms, now_ms=now_ms)
    return (a is not None) and (a <= int(max_age_ms))


def _require_fresh(
    source: str,
    ts_ms: int,
    *,
    max_age_ms: int,
    now_ms: Optional[int] = None,
) -> Tuple[bool, str, Optional[int]]:
    """
    Returns (ok, reason, age_ms). When ok=False, reason encodes stale/missing.
    """
    try:
        if ts_ms <= 0:
            return False, f"{source}_missing_ts", None
        a = _age_ms(ts_ms, now_ms=now_ms)
        if a is None:
            return False, f"{source}_age_unknown", None
        if a > int(max_age_ms):
            return False, f"{source}_stale age_ms={a} max_age_ms={int(max_age_ms)}", a
        return True, f"{source}_fresh age_ms={a}", a
    except Exception:
        return False, f"{source}_fresh_check_err", None


# Feature keys from unified_features that indicate momentum/trend
_MOMENTUM_KEYS = [
    "rsi_14", "rsi_7", "rsi_21",
    "macd_histogram", "macd_signal", "macd_line",
    "ema_9", "ema_21", "ema_50",
    "adx_14", "adx",
    "cci_14", "cci_20",
    "willr_14", "willr",
    "mfi_14",
    "stoch_k", "stoch_d", "stochrsi_k", "stochrsi_d",
    "trix", "trix_signal",
    "aroon_up", "aroon_down", "aroon_oscillator",
]

_VOLUME_KEYS = [
    "obv", "obv_slope",
    "vwap", "vwap_deviation",
    "volume_ratio", "volume_sma_ratio",
    "volume_delta", "buy_volume_ratio",
    "taker_buy_ratio", "taker_sell_ratio",
]

_ORDERBOOK_KEYS = [
    "bid_ask_spread", "bid_ask_imbalance",
    "book_imbalance", "book_depth_ratio",
    "bid_depth", "ask_depth",
    "orderbook_imbalance_ratio",
    "micro_bid_depth", "micro_ask_depth",
    "micro_book_imbalance",
]

_LIQUIDATION_KEYS = [
    "liquidation_long_strength", "liquidation_short_strength",
    "liquidation_long_distance_pct", "liquidation_short_distance_pct",
    "liquidation_imbalance", "liquidation_net_pressure",
    "liq_cluster_proximity",
]

_COINANK_KEYS = [
    "funding_rate", "funding_rate_8h",
    "open_interest_change", "oi_change_pct",
    "long_short_ratio", "long_short_account_ratio",
    "top_trader_ls_ratio",
    "coinank_order_flow_score",
]


def evaluate_close(
    redis_client,
    symbol: str,
    position_side: str,
    close_reason: str = "",
    *,
    is_hard_emergency: bool = False,
) -> CloseGuardVerdict:
    """
    Evaluate whether an auto-close should proceed using all available data.

    Args:
        redis_client: Redis connection
        symbol:        Trading symbol (e.g., "BTCUSDT")
        position_side: "LONG" or "SHORT"
        close_reason:  Why the close was triggered (for logging)
        is_hard_emergency: If True, skip the guard (survival mode)

    Returns:
        CloseGuardVerdict with action="ALLOW_CLOSE" or "DEFER_CLOSE"
    """
    enabled = bool(_cfg("INTELLIGENT_CLOSE_GUARD_ENABLED", True))
    if not enabled:
        return CloseGuardVerdict(
            action="ALLOW_CLOSE", hold_score=0.0,
            reason="guard_disabled", components={}, data_sources_used=0,
        )

    if is_hard_emergency:
        return CloseGuardVerdict(
            action="ALLOW_CLOSE", hold_score=0.0,
            reason="hard_emergency_bypass", components={}, data_sources_used=0,
        )

    if not redis_client:
        return CloseGuardVerdict(
            action="ALLOW_CLOSE", hold_score=0.0,
            reason="no_redis", components={}, data_sources_used=0,
        )

    side_upper = position_side.upper().strip()
    is_long = side_upper == "LONG"

    components: Dict[str, float] = {}
    data_sources = 0
    freshness: Dict[str, Any] = {}
    now_ms = _now_ms()

    # Freshness thresholds (ms) — tuned for each source's update cadence.
    # When a source is stale, we treat it as "not contributing" rather than a directional 0.0 score,
    # so data_sources reflects usable realtime confirmation.
    try:
        max_age_regime_ms = int(_cfg("ICG_MAX_AGE_REGIME_MS", 180_000))          # 3m
        max_age_features_ms = int(_cfg("ICG_MAX_AGE_FEATURES_MS", 240_000))      # 4m
        max_age_orderbook_ms = int(_cfg("ICG_MAX_AGE_ORDERBOOK_MS", 15_000))     # 15s
        max_age_trainer_intent_ms = int(_cfg("ICG_MAX_AGE_TRAINER_INTENT_MS", 300_000))  # 5m
        max_age_prediction_ms = int(_cfg("ICG_MAX_AGE_PREDICTION_MS", 300_000))  # 5m
    except Exception:
        max_age_regime_ms = 180_000
        max_age_features_ms = 240_000
        max_age_orderbook_ms = 15_000
        max_age_trainer_intent_ms = 300_000
        max_age_prediction_ms = 300_000

    # Fail-closed policy for loss closes (do not allow loss-realizing closes without fresh data).
    try:
        fail_closed_loss = bool(_cfg("ICG_FAIL_CLOSED_ON_LOSS_CLOSE", True))
    except Exception:
        fail_closed_loss = True
    is_loss_close = any(tok in str(close_reason or "").upper() for tok in ("LOSS", "ROI_KILL", "SOFT_REDUCE", "DELEVERAGE", "MICRO_LOSS_EXIT"))
    # Callers may include explicit markers in close_reason, but we also allow overriding the policy via config.
    if not fail_closed_loss:
        is_loss_close = False

    # ── 1. Regime Data ─────────────────────────────────────────────────
    regime_score = 0.0
    try:
        raw_regime = redis_client.get(f"regime:{symbol}")
        if raw_regime:
            val = raw_regime.decode("utf-8") if isinstance(raw_regime, (bytes, bytearray)) else str(raw_regime)
            d = json.loads(val) if isinstance(val, str) and val.strip().startswith("{") else {}
            regime_ts_ms = _ts_to_ms(d.get("ts_ms") or d.get("updated_ts_ms") or d.get("timestamp") or d.get("ts"))
        else:
            regime_ts_ms = 0
    except Exception:
        regime_ts_ms = 0
    ok_regime, reason_regime, age_regime = _require_fresh("regime", regime_ts_ms, max_age_ms=max_age_regime_ms, now_ms=now_ms)
    freshness["regime"] = {"ok": ok_regime, "ts_ms": regime_ts_ms, "age_ms": age_regime, "reason": reason_regime}
    if ok_regime:
        regime_score = _evaluate_regime(redis_client, symbol, is_long)
    components["regime"] = regime_score
    if ok_regime and regime_score != 0.0:
        data_sources += 1

    # ── 2. Unified Features (2000+ keys) across TFs ───────────────────
    features_score = 0.0
    # Determine freshness from the max ts_ms across our main TFs.
    try:
        uf_ts = 0
        for tf in ("1m", "5m", "15m", "1h"):
            try:
                _t = redis_client.hget(f"unified_features:{symbol}:{tf}", "ts_ms")
                if not _t:
                    _t = redis_client.hget(f"unified_features:{symbol}:{tf}", "timestamp")
                uf_ts = max(uf_ts, _ts_to_ms(_t))
            except Exception:
                continue
    except Exception:
        uf_ts = 0
    ok_feat, reason_feat, age_feat = _require_fresh("features", uf_ts, max_age_ms=max_age_features_ms, now_ms=now_ms)
    freshness["features"] = {"ok": ok_feat, "ts_ms": uf_ts, "age_ms": age_feat, "reason": reason_feat}
    if ok_feat:
        features_score = _evaluate_features(redis_client, symbol, is_long)
    components["features"] = features_score
    if ok_feat and features_score != 0.0:
        data_sources += 1

    # ── 3. CoinAPI Orderbook/Microstructure ───────────────────────────
    orderbook_score = 0.0
    try:
        ob_ts = _ts_to_ms(redis_client.hget(f"msnap:coinapi_wsds:{symbol}", "ts_ms"))
    except Exception:
        ob_ts = 0
    ok_ob, reason_ob, age_ob = _require_fresh("orderbook", ob_ts, max_age_ms=max_age_orderbook_ms, now_ms=now_ms)
    freshness["orderbook"] = {"ok": ok_ob, "ts_ms": ob_ts, "age_ms": age_ob, "reason": reason_ob}
    if ok_ob:
        orderbook_score = _evaluate_orderbook(redis_client, symbol, is_long)
    components["orderbook"] = orderbook_score
    if ok_ob and orderbook_score != 0.0:
        data_sources += 1

    # ── 4. Trainer Intent ─────────────────────────────────────────────
    trainer_score = 0.0
    try:
        from risk.trainer_intent import get_intent
        intent = get_intent(redis_client, symbol)
        intent_ts = int(getattr(intent, "ts_ms", 0) or 0) if intent else 0
    except Exception:
        intent_ts = 0
        intent = None
    ok_intent, reason_intent, age_intent = _require_fresh("trainer_intent", intent_ts, max_age_ms=max_age_trainer_intent_ms, now_ms=now_ms)
    freshness["trainer_intent"] = {"ok": ok_intent, "ts_ms": intent_ts, "age_ms": age_intent, "reason": reason_intent}
    if ok_intent:
        trainer_score = _evaluate_trainer_intent(redis_client, symbol, is_long)
    components["trainer_intent"] = trainer_score
    if ok_intent and trainer_score != 0.0:
        data_sources += 1

    # ── 5. Multi-TF Prediction Consensus ──────────────────────────────
    mtf_score = 0.0
    # Freshness: accept if we find any recent prediction hash among the core keys.
    try:
        pred_ts_max = 0
        sym_u = str(symbol or "").upper().strip()
        for tf in ("multi", "5m", "15m", "1h", "4h"):
            try:
                t = redis_client.hget(f"prediction:{sym_u}:{tf}", "ts_ms")
                if not t:
                    t = redis_client.hget(f"prediction:{sym_u}:{tf}", "timestamp")
                pred_ts_max = max(pred_ts_max, _ts_to_ms(t))
            except Exception:
                continue
    except Exception:
        pred_ts_max = 0
    ok_pred, reason_pred, age_pred = _require_fresh("prediction", pred_ts_max, max_age_ms=max_age_prediction_ms, now_ms=now_ms)
    freshness["mtf_consensus"] = {"ok": ok_pred, "ts_ms": pred_ts_max, "age_ms": age_pred, "reason": reason_pred}
    if ok_pred:
        mtf_score = _evaluate_mtf_consensus(redis_client, symbol, is_long)
    components["mtf_consensus"] = mtf_score
    if ok_pred and mtf_score != 0.0:
        data_sources += 1

    # ── 6. Liquidation Proximity ──────────────────────────────────────
    liq_score = 0.0
    # Liquidation data comes from unified_features; reuse features freshness gate.
    if ok_feat:
        liq_score = _evaluate_liquidation_data(redis_client, symbol, is_long)
    components["liquidation"] = liq_score
    if ok_feat and liq_score != 0.0:
        data_sources += 1

    # ── Weighted Combination ──────────────────────────────────────────
    weights = {
        "regime":         float(_cfg("ICG_WEIGHT_REGIME", 0.20)),
        "features":       float(_cfg("ICG_WEIGHT_FEATURES", 0.25)),
        "orderbook":      float(_cfg("ICG_WEIGHT_ORDERBOOK", 0.15)),
        "trainer_intent": float(_cfg("ICG_WEIGHT_TRAINER", 0.20)),
        "mtf_consensus":  float(_cfg("ICG_WEIGHT_MTF", 0.10)),
        "liquidation":    float(_cfg("ICG_WEIGHT_LIQUIDATION", 0.10)),
    }

    total_weight = sum(weights.values())
    hold_score = sum(
        components.get(k, 0.0) * w for k, w in weights.items()
    ) / total_weight if total_weight > 0 else 0.0

    hold_score = max(0.0, min(1.0, hold_score))

    defer_threshold = float(_cfg("ICG_DEFER_THRESHOLD", 0.55))
    min_sources = int(_cfg("ICG_MIN_DATA_SOURCES", 2))

    # ── ROE-AWARE THRESHOLD: Deeply underwater positions get lower defer threshold ──
    # Reads position ROE from Redis (positions:{account_id} hash).
    # The more underwater, the harder it is for ICG to justify holding.
    # This uses live position data, not static thresholds.
    try:
        _roe_adjust = 0.0
        # Try to find position ROE from any account's position data
        for _acct_key in redis_client.keys("positions:*"):
            try:
                _acct_key_str = _acct_key.decode() if isinstance(_acct_key, bytes) else str(_acct_key)
                _pos_raw = redis_client.hget(_acct_key_str, f"{symbol}:{side_upper}")
                if _pos_raw:
                    _pos_data = json.loads(_pos_raw.decode() if isinstance(_pos_raw, bytes) else str(_pos_raw))
                    _pos_roi = float(_pos_data.get("roi_pct", 0) or _pos_data.get("pnl_pct", 0) or 0)
                    if _pos_roi == 0:
                        _pos_margin = float(_pos_data.get("margin_used", 0) or _pos_data.get("initialMargin", 0) or 1)
                        _pos_upnl = float(_pos_data.get("unrealized_pnl", 0) or _pos_data.get("unrealizedProfit", 0) or 0)
                        if _pos_margin > 0:
                            _pos_roi = (_pos_upnl / _pos_margin) * 100.0
                    # Scale threshold down for underwater positions:
                    # ROI -5% → threshold -0.02, ROI -20% → -0.08, ROI -50%+ → -0.15
                    if _pos_roi < -5.0:
                        _roe_adjust = min(0.0, _pos_roi + 5.0) * 0.003  # -0.003 per 1% below -5%
                        _roe_adjust = max(-0.15, _roe_adjust)  # Floor: threshold can drop by 0.15 max
                    break
            except Exception:
                continue
        if _roe_adjust < 0:
            defer_threshold = max(0.30, defer_threshold + _roe_adjust)
            components["roe_threshold_adj"] = _roe_adjust
    except Exception:
        pass

    if hold_score >= defer_threshold and data_sources >= min_sources:
        action = "DEFER_CLOSE"
        reason = (
            f"hold_score={hold_score:.3f}>={defer_threshold} "
            f"sources={data_sources}/{min_sources} "
            f"top={_top_contributor(components, weights)}"
        )
    else:
        action = "ALLOW_CLOSE"
        reason = f"hold_score={hold_score:.3f}<{defer_threshold} sources={data_sources}"

    # Loss-close safety: if we do not have enough fresh sources to justify a loss-realizing close,
    # defer by default. This prevents stale/missing external data from authorizing bleeding exits.
    if is_loss_close:
        try:
            required_loss_sources = int(_cfg("ICG_LOSS_CLOSE_MIN_SOURCES", 2))
        except Exception:
            required_loss_sources = 2
        if data_sources < required_loss_sources:
            action = "DEFER_CLOSE"
            reason = f"loss_close_fail_closed sources={data_sources}<{required_loss_sources}"

    # ── MARKET INTELLIGENCE DELEGATION (Apr 2026) ─────────────────────
    # Consult MI's unified should_allow_close() for a second opinion.
    # If MI disagrees with ICG's ALLOW, escalate to DEFER (conservative).
    # If MI agrees with ICG's DEFER, strengthen the hold.
    # Kill switch: ICG_DELEGATE_TO_MI_ENABLED (default True)
    # ──────────────────────────────────────────────────────────────────
    _mi_hold = 0.0
    try:
        _mi_delegate = bool(_cfg("ICG_DELEGATE_TO_MI_ENABLED", True))
        if _mi_delegate and not is_hard_emergency:
            from trading.market_intelligence import should_allow_close as _mi_check
            _mi_allow, _mi_reason_str, _mi_hold = _mi_check(
                redis_client, symbol, side_upper,
                close_source=f"icg_{close_reason[:40]}",
                roe_pct=0.0,  # ICG doesn't have ROE — conservative
            )
            components["mi_unified"] = _mi_hold

            if action == "ALLOW_CLOSE" and not _mi_allow:
                # MI says HOLD but ICG said ALLOW → escalate to DEFER (conservative)
                action = "DEFER_CLOSE"
                reason = (
                    f"MI_OVERRIDE:hold_score={hold_score:.3f} mi_hold={_mi_hold:.3f} | "
                    f"ICG_allow but MI_defers: {_mi_reason_str[:120]}"
                )
                logger.info(
                    "ICG_MI_OVERRIDE_DEFER | sym=%s side=%s | "
                    "icg_score=%.3f mi_hold=%.3f | %s",
                    symbol, side_upper, hold_score, _mi_hold, _mi_reason_str[:100],
                )
            elif action == "DEFER_CLOSE" and _mi_allow and hold_score < defer_threshold + 0.10:
                # ICG defers marginally, but MI confidently says ALLOW → release
                action = "ALLOW_CLOSE"
                reason = (
                    f"MI_RELEASE:hold_score={hold_score:.3f} mi_hold={_mi_hold:.3f} | "
                    f"ICG_defers marginally but MI allows: {_mi_reason_str[:120]}"
                )
                logger.info(
                    "ICG_MI_RELEASE | sym=%s side=%s | "
                    "icg_score=%.3f mi_hold=%.3f | %s",
                    symbol, side_upper, hold_score, _mi_hold, _mi_reason_str[:100],
                )
            # Blend MI hold score into ICG hold score for richer verdict
            hold_score = hold_score * 0.65 + _mi_hold * 0.35
            hold_score = max(0.0, min(1.0, hold_score))
    except ImportError:
        pass
    except Exception as _mi_err:
        logger.debug("ICG_MI_DELEGATE_ERR | %s | %s", symbol, _mi_err)

    logger.info(
        "INTELLIGENT_CLOSE_GUARD | symbol=%s | side=%s | action=%s | "
        "hold_score=%.3f | threshold=%.2f | sources=%d | "
        "regime=%.2f features=%.2f ob=%.2f trainer=%.2f mtf=%.2f liq=%.2f | "
        "trigger=%s",
        symbol, side_upper, action, hold_score, defer_threshold,
        data_sources,
        components.get("regime", 0), components.get("features", 0),
        components.get("orderbook", 0), components.get("trainer_intent", 0),
        components.get("mtf_consensus", 0), components.get("liquidation", 0),
        close_reason,
    )
    try:
        # Debug-only diag (rate-limited elsewhere by caller logs); keep compact.
        logger.info(
            "ICG_FRESHNESS | symbol=%s side=%s | %s",
            symbol, side_upper, json.dumps(freshness, separators=(",", ":"), sort_keys=True)[:900],
        )
    except Exception:
        pass


    return CloseGuardVerdict(
        action=action,
        hold_score=hold_score,
        reason=reason,
        components=components,
        data_sources_used=data_sources,
    )


def _top_contributor(components: Dict[str, float], weights: Dict[str, float]) -> str:
    weighted = {k: components.get(k, 0.0) * weights.get(k, 0.0) for k in components}
    if not weighted:
        return "none"
    top_k = max(weighted, key=weighted.get)  # type: ignore
    return f"{top_k}={components.get(top_k, 0):.2f}"


def _evaluate_regime(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: how much the regime supports keeping the position."""
    try:
        raw = redis_client.get(f"regime:{symbol}")
        if not raw:
            return 0.0
        val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        regime = json.loads(val)

        tf_alignment = _sf(regime.get("tf_alignment"), 0.0)
        trend_dir = str(regime.get("trend_direction", "NEUTRAL")).upper()
        move_regime = str(regime.get("move_regime", "UNKNOWN")).upper()
        volatility = _sf(regime.get("volatility_score"), 0.5)

        score = 0.0

        # tf_alignment: positive=bullish, negative=bearish
        # For LONG positions, positive alignment supports holding
        alignment_support = tf_alignment if is_long else -tf_alignment
        if alignment_support > 0:
            score += min(alignment_support, 1.0) * 0.5

        # trend_direction alignment
        if (is_long and trend_dir in ("BULLISH", "LONG")) or \
           (not is_long and trend_dir in ("BEARISH", "SHORT")):
            score += 0.3

        # Move regime: TRENDING/FAST/IMPULSE supports position
        if move_regime in ("TRENDING", "FAST", "IMPULSE"):
            score += 0.2
        elif move_regime == "BREAKOUT":
            score += 0.1

        return min(1.0, max(0.0, score))
    except Exception:
        return 0.0


def _find_feat(feat: Dict[str, str], *patterns) -> Optional[float]:
    """Find the first feature key matching any pattern (case-insensitive substring)."""
    for pat in patterns:
        pat_l = pat.lower()
        for k, v in feat.items():
            if pat_l in k.lower():
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue
    return None


def _evaluate_features(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: how much 2000+ features support keeping the position."""
    try:
        votes = 0.0
        total_signals = 0

        for tf in ["1m", "5m", "15m", "1h"]:
            raw = redis_client.hgetall(f"unified_features:{symbol}:{tf}")
            if not raw:
                continue
            feat = _decode_map(raw)

            # RSI (keys: xtf_1m_rsi_14, ind_ta_RSI_14_5m, etc.)
            rsi = _find_feat(feat, "rsi_14", "rsi_21")
            if rsi is not None and rsi > 0:
                total_signals += 1
                if is_long and rsi < 40:
                    votes += 0.6
                elif is_long and rsi > 50:
                    votes += 0.3
                elif not is_long and rsi > 60:
                    votes += 0.6
                elif not is_long and rsi < 50:
                    votes += 0.3

            # MACD histogram (keys: ind_ta_MACD_hist_..., ind_ta_MACDEXT_hist_...)
            macd_hist = _find_feat(feat, "macd_hist", "MACD_hist")
            if macd_hist is not None and macd_hist != 0:
                total_signals += 1
                if (is_long and macd_hist > 0) or (not is_long and macd_hist < 0):
                    votes += 0.5

            # ADX (keys: ind_ta_ADX_14_5m, ind_ta_ADX_21_5m)
            adx = _find_feat(feat, "ta_ADX_14", "ta_ADX_21")
            if adx is not None and adx > 0:
                total_signals += 1
                if adx > 25:
                    votes += 0.4
                elif adx > 15:
                    votes += 0.2

            # CCI (keys: ind_ta_CCI_14_5m, ind_ta_CCI_20_5m)
            cci = _find_feat(feat, "ta_CCI_14", "ta_CCI_20")
            if cci is not None and cci != 0:
                total_signals += 1
                if (is_long and cci > 0) or (not is_long and cci < 0):
                    votes += 0.3

            # Funding rate (keys: funding_rate, xtf_1m_funding_rate)
            funding = _find_feat(feat, "funding_rate")
            if funding is not None and funding != 0:
                total_signals += 1
                if is_long and funding < -0.0005:
                    votes += 0.3
                elif not is_long and funding > 0.0005:
                    votes += 0.3

            # Orderbook imbalance (keys: depth_imbalance_5, ob_ob_imbalance)
            book_imb = _find_feat(feat, "depth_imbalance", "ob_imbalance", "ob_ob_imbalance")
            if book_imb is not None and book_imb != 0:
                total_signals += 1
                if (is_long and book_imb > 0.1) or (not is_long and book_imb < -0.1):
                    votes += 0.4

            # EMA crossover (keys: ind_ta_EMA_10_5m, ind_ta_EMA_50_5m)
            ema_short = _find_feat(feat, "ta_EMA_10_", "ta_EMA_5_")
            ema_long = _find_feat(feat, "ta_EMA_50_", "ta_EMA_100_")
            if ema_short is not None and ema_long is not None and ema_short > 0 and ema_long > 0:
                total_signals += 1
                if (is_long and ema_short > ema_long) or (not is_long and ema_short < ema_long):
                    votes += 0.3

            # Stochastic RSI (keys: ind_ta_STOCHRSI_k_...)
            stoch_k = _find_feat(feat, "STOCHRSI_k")
            if stoch_k is not None and stoch_k > 0:
                total_signals += 1
                if is_long and stoch_k < 30:
                    votes += 0.4
                elif not is_long and stoch_k > 70:
                    votes += 0.4

            # CoinAnk order flow
            order_flow = _find_feat(feat, "coinank_orderFlow")
            if order_flow is not None and order_flow != 0:
                total_signals += 1
                if (is_long and order_flow > 0) or (not is_long and order_flow < 0):
                    votes += 0.3

            # OI change
            oi_change = _find_feat(feat, "oi_change", "open_interest")
            if oi_change is not None and oi_change != 0:
                total_signals += 1
                votes += 0.2

        if total_signals == 0:
            return 0.0

        return min(1.0, votes / max(total_signals, 1))
    except Exception:
        return 0.0


def _evaluate_orderbook(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: how much the live orderbook supports the position."""
    try:
        raw = redis_client.hgetall(f"msnap:coinapi_wsds:{symbol}")
        if not raw:
            return 0.0
        snap = _decode_map(raw)

        score = 0.0
        signals = 0

        # Bid/ask depth ratio (keys: book_bid_sum_5, book_ask_sum_5,
        # best_bid_qty/sz, best_ask_qty/sz, depth_bps_10_bid_usd/ask_usd)
        bid_depth = _sf(
            snap.get("book_bid_sum_5")
            or snap.get("depth_bps_10_bid_usd")
            or snap.get("best_bid_qty")
            or snap.get("best_bid_sz"),
            0.0,
        )
        ask_depth = _sf(
            snap.get("book_ask_sum_5")
            or snap.get("depth_bps_10_ask_usd")
            or snap.get("best_ask_qty")
            or snap.get("best_ask_sz"),
            0.0,
        )
        if bid_depth > 0 and ask_depth > 0:
            signals += 1
            ratio = bid_depth / (bid_depth + ask_depth)
            if is_long and ratio > 0.55:
                score += 0.5
            elif not is_long and ratio < 0.45:
                score += 0.5

        # Book imbalance (key: imbalance_5)
        imbalance = _sf(snap.get("imbalance_5"), 0.0)
        if imbalance != 0:
            signals += 1
            # Positive imbalance = bid-heavy (supports longs)
            if (is_long and imbalance > 0.05) or (not is_long and imbalance < -0.05):
                score += 0.4

        # Fast move score — direction-aware: only support holding if move is favorable
        fast_move = _sf(snap.get("fast_move_score"), 0.0)
        if fast_move > 0.5:
            signals += 1
            fm_favorable = (is_long and imbalance > 0.05) or (not is_long and imbalance < -0.05)
            fm_adverse = (is_long and imbalance < -0.10) or (not is_long and imbalance > 0.10)
            if fm_favorable:
                score += 0.2
            elif fm_adverse:
                score -= 0.3

        # Microprice vs mid (key: microprice, mid_px)
        microprice = _sf(snap.get("microprice"), 0.0)
        mid_px = _sf(snap.get("mid_px"), 0.0)
        if microprice > 0 and mid_px > 0:
            signals += 1
            micro_skew = (microprice - mid_px) / mid_px
            # Positive skew = buy pressure, negative = sell pressure
            if (is_long and micro_skew > 0.0001) or (not is_long and micro_skew < -0.0001):
                score += 0.3


        if signals == 0:
            return 0.0
        return min(1.0, score / max(signals * 0.3, 1))
    except Exception:
        return 0.0


def _evaluate_trainer_intent(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: how much the trainer supports keeping the position."""
    try:
        from risk.trainer_intent import get_intent
        intent = get_intent(redis_client, symbol)
        if intent is None:
            return 0.0

        if not intent.is_directional:
            return 0.1  # neutral — slight support for holding

        aligned = intent.aligns_with_position("LONG" if is_long else "SHORT")
        if aligned:
            return min(1.0, 0.5 + intent.confidence * 0.5)

        # Opposing intent — no support for holding
        return 0.0
    except Exception:
        return 0.0


def _prediction_effective_direction(pred: Dict[str, str]) -> str:
    """Map Redis prediction hash to LONG/SHORT using direction field or action inference."""
    d = str(pred.get("direction") or "").upper().strip()
    if d in ("LONG", "SHORT"):
        return d
    action = str(pred.get("action") or pred.get("action_name") or "").upper()
    try:
        from risk.trainer_intent import infer_direction_from_action

        idir = infer_direction_from_action(action)
        return idir if idir in ("LONG", "SHORT") else ""
    except Exception:
        return ""


def _prediction_is_hold_neutral(pred: Dict[str, str]) -> bool:
    """True when trainer is explicitly non-directional (multi-TF wait) — not OPEN/CLOSE risk."""
    a = str(pred.get("action") or pred.get("action_name") or "").upper()
    if any(
        x in a
        for x in (
            "CLOSE",
            "OPEN",
            "INCREASE",
            "DECREASE",
            "REDUCE",
            "PARTIAL",
            "FLIP",
            "HEDGE",
        )
    ):
        return False
    d = str(pred.get("direction") or "").upper().strip()
    if d in ("HOLD", "NEUTRAL"):
        return True
    if a in ("HOLD", "NONE", "WAIT", "NO_ACTION", ""):
        return True
    return False


def _evaluate_mtf_consensus(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: multi-TF prediction consensus supporting the position."""
    try:
        sym_u = str(symbol or "").upper().strip()
        try:
            import config as _cfg

            _extra = list(getattr(_cfg, "INTENT_TIMEFRAMES", []) or [])
        except Exception:
            _extra = []
        tfs = list(
            dict.fromkeys(
                [x.strip() for x in _extra if x and str(x).strip()]
                + ["multi", "1m", "5m", "15m", "1h", "4h"]
            )
        )
        aligned_count = 0
        total_conf = 0.0
        total_predictions = 0
        neutral_count = 0
        neutral_conf_sum = 0.0

        # String JSON cache: prediction:{SYM}:latest (not a Redis hash)
        try:
            _rl = redis_client.get(f"prediction:{sym_u}:latest")
            if _rl:
                _js = (
                    _rl.decode("utf-8", errors="ignore")
                    if isinstance(_rl, (bytes, bytearray))
                    else str(_rl)
                )
                if _js.strip().startswith("{"):
                    _pj = json.loads(_js)
                    if isinstance(_pj, dict):
                        pred = {str(k): str(v) for k, v in _pj.items()}
                        conf = _sf(pred.get("confidence") or pred.get("model_confidence"), 0.0)
                        edir = _prediction_effective_direction(pred)
                        if edir:
                            total_predictions += 1
                            if (is_long and edir == "LONG") or (not is_long and edir == "SHORT"):
                                aligned_count += 1
                                total_conf += conf
                        elif _prediction_is_hold_neutral(pred):
                            neutral_count += 1
                            neutral_conf_sum += conf
        except Exception:
            pass

        for tf in tfs:
            try:
                raw = redis_client.hgetall(f"prediction:{sym_u}:{tf}")
                if not raw:
                    continue
                pred = _decode_map(raw)
                conf = _sf(pred.get("confidence"), 0.0)
                edir = _prediction_effective_direction(pred)
                if edir:
                    total_predictions += 1
                    if (is_long and edir == "LONG") or (not is_long and edir == "SHORT"):
                        aligned_count += 1
                        total_conf += conf
                elif _prediction_is_hold_neutral(pred):
                    neutral_count += 1
                    neutral_conf_sum += conf
            except Exception:
                continue

        dir_score = 0.0
        if total_predictions > 0:
            alignment_ratio = aligned_count / total_predictions
            avg_conf = total_conf / aligned_count if aligned_count > 0 else 0.0
            dir_score = min(1.0, alignment_ratio * 0.6 + avg_conf * 0.4)

        neutral_score = 0.0
        if neutral_count > 0:
            navg = neutral_conf_sum / neutral_count
            cap = 0.40 if neutral_count >= 3 else (0.28 if neutral_count == 2 else 0.18)
            neutral_score = min(cap, 0.06 + navg * 0.52)

        if total_predictions == 0 and neutral_count == 0:
            try:
                _ts0 = int(time.time() * 1000)
                _last0 = globals().get("_ICG_MTF_EMPTY_LOG_LAST", {}) or {}
                _k0 = f"{sym_u}:{'L' if is_long else 'S'}:empty"
                if _ts0 - int(_last0.get(_k0, 0) or 0) > 120_000:
                    _last0[_k0] = _ts0
                    globals()["_ICG_MTF_EMPTY_LOG_LAST"] = _last0
                    logger.info(
                        "ICG_MTF_DIAG | sym=%s is_long=%s dir_preds=0 neutral=0 score=0.000 | "
                        "no usable prediction hashes/json for this evaluation",
                        sym_u, is_long,
                    )
            except Exception:
                pass
            return 0.0

        score = min(1.0, max(dir_score, neutral_score))
        try:
            _ts = int(time.time() * 1000)
            _last = globals().get("_ICG_MTF_LOG_LAST", {}) or {}
            _k = f"{sym_u}:{'L' if is_long else 'S'}"
            if _ts - int(_last.get(_k, 0) or 0) > 120_000:
                _last[_k] = _ts
                globals()["_ICG_MTF_LOG_LAST"] = _last
                logger.info(
                    "ICG_MTF_DIAG | sym=%s is_long=%s dir_preds=%d aligned=%d neutral_tf=%d "
                    "dir_score=%.3f neutral_score=%.3f final=%.3f",
                    sym_u, is_long, total_predictions, aligned_count, neutral_count,
                    dir_score, neutral_score, score,
                )
        except Exception:
            pass
        return score
    except Exception:
        return 0.0


def _evaluate_liquidation_data(redis_client, symbol: str, is_long: bool) -> float:
    """Score 0–1: liquidation data supporting position retention."""
    try:
        score = 0.0
        signals = 0

        for tf in ["5m", "15m", "1h"]:
            raw = redis_client.hgetall(f"unified_features:{symbol}:{tf}")
            if not raw:
                continue
            feat = _decode_map(raw)

            long_str = _sf(feat.get("liquidation_long_strength"), 0.0)
            short_str = _sf(feat.get("liquidation_short_strength"), 0.0)
            long_dist = _sf(feat.get("liquidation_long_distance_pct"), 0.0)
            short_dist = _sf(feat.get("liquidation_short_distance_pct"), 0.0)

            if long_str > 0 or short_str > 0:
                signals += 1
                if is_long:
                    # Longs benefit from short liquidation clusters above price
                    if short_str > long_str * 1.2:
                        score += 0.5  # more short liq = potential short squeeze
                elif not is_long:
                    if long_str > short_str * 1.2:
                        score += 0.5  # more long liq = potential long squeeze

            if long_dist > 0 and short_dist > 0:
                signals += 1
                if is_long and short_dist < long_dist:
                    score += 0.3  # short liqs closer — cascade likely
                elif not is_long and long_dist < short_dist:
                    score += 0.3

        if signals == 0:
            return 0.0
        return min(1.0, score / max(signals * 0.3, 1))
    except Exception:
        return 0.0


def _get_counterpart_roi(redis_client, symbol: str, counter_side: str) -> Optional[float]:
    """Fetch the counterpart position's ROI from Redis positions:live:{symbol} nested hash."""
    try:
        import json as _jcp
        _sym = symbol.upper()
        _sk = counter_side.lower()
        _ph = redis_client.hgetall(f"positions:live:{_sym}")
        if not _ph:
            return None
        _pd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _ph.items()}
        _raw = _pd.get(_sk)
        if not _raw:
            return None
        pos = _jcp.loads(_raw) if isinstance(_raw, str) else {}
        if not isinstance(pos, dict):
            return None
        _size = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or 0))
        if _size <= 0:
            return None
        _roi = pos.get("roi_pct") or pos.get("roe_pct") or pos.get("percentage")
        if _roi is not None:
            return float(_roi)
        _pnl = float(pos.get("unrealizedProfit", 0) or pos.get("unRealizedProfit", 0) or 0)
        _margin = abs(float(pos.get("isolatedWallet", 0) or pos.get("initialMargin", 0) or pos.get("margin_used", 0) or 1))
        if _margin > 0:
            return (_pnl / _margin) * 100.0
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
#  evaluate_tp_hold  — TP-specific evaluation for ride-move decisions
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TPHoldVerdict:
    """Whether a profitable position should extend past its TP."""
    should_hold: bool
    suggested_tp_extension_pct: float
    hold_score: float
    reason: str
    components: Dict[str, float]


def evaluate_tp_hold(
    redis_client,
    symbol: str,
    position_side: str,
    current_roe: float = 0.0,
) -> TPHoldVerdict:
    """Evaluate whether a profitable position should ride past its TP.

    Uses the same 6 data sources as evaluate_close() but with weights
    tuned for the TP context: heavier on trend momentum and regime,
    lighter on liquidation.  Returns a suggested ATR-based TP extension.
    """
    _default = TPHoldVerdict(False, 0.0, 0.0, "default", {})

    enabled = bool(_cfg("INTELLIGENT_CLOSE_GUARD_ENABLED", True))
    if not enabled or not redis_client:
        return _default

    side_upper = position_side.upper().strip()
    is_long = side_upper == "LONG"

    components: Dict[str, float] = {}

    regime_score = _evaluate_regime(redis_client, symbol, is_long)
    components["regime"] = regime_score

    features_score = _evaluate_features(redis_client, symbol, is_long)
    components["features"] = features_score

    orderbook_score = _evaluate_orderbook(redis_client, symbol, is_long)
    components["orderbook"] = orderbook_score

    trainer_score = _evaluate_trainer_intent(redis_client, symbol, is_long)
    components["trainer_intent"] = trainer_score

    mtf_score = _evaluate_mtf_consensus(redis_client, symbol, is_long)
    components["mtf_consensus"] = mtf_score

    liq_score = _evaluate_liquidation_data(redis_client, symbol, is_long)
    components["liquidation"] = liq_score

    # TP-specific weights: heavier on trend/regime, lighter on liquidation
    tp_weights = {
        "regime":         0.25,
        "features":       0.30,
        "orderbook":      0.15,
        "trainer_intent": 0.15,
        "mtf_consensus":  0.10,
        "liquidation":    0.05,
    }

    total_w = sum(tp_weights.values())
    hold_score = sum(
        components.get(k, 0.0) * w for k, w in tp_weights.items()
    ) / total_w if total_w > 0 else 0.0
    hold_score = max(0.0, min(1.0, hold_score))

    tp_hold_threshold = float(_cfg("ICG_TP_HOLD_THRESHOLD", 0.60))

    # ── RAMP Phase 2: Counterpart distress boost ───────────────────
    # When the opposite leg is deeply underwater AND regime supports
    # this side, boost hold_score to prevent premature TP closure
    # on the winning side during a squeeze.
    _distress_boost = 0.0
    try:
        counter_side = "SHORT" if is_long else "LONG"
        _counter_roi = _get_counterpart_roi(redis_client, symbol, counter_side)
        if _counter_roi is not None and _counter_roi < -30.0:
            _regime_raw = redis_client.get(f"regime:{symbol}")
            if _regime_raw:
                import json as _rj_tp
                _regime_d = _rj_tp.loads(
                    _regime_raw.decode() if isinstance(_regime_raw, bytes) else str(_regime_raw)
                )
                _td = str(_regime_d.get("trend_direction", "")).upper()
                _regime_supports = (
                    (is_long and _td in ("LONG", "BULLISH", "UP"))
                    or (not is_long and _td in ("SHORT", "BEARISH", "DOWN"))
                )
                if _regime_supports:
                    _distress_boost = min(0.30, abs(_counter_roi) / 300.0)
                    hold_score = min(1.0, hold_score + _distress_boost)
                    components["counterpart_distress"] = _distress_boost
                    logger.info(
                        "RAMP_TP_HOLD_DISTRESS | sym=%s side=%s | counter_roi=%.1f%% | "
                        "boost=%.3f hold_score=%.3f trend=%s",
                        symbol, side_upper, _counter_roi, _distress_boost, hold_score, _td,
                    )
    except Exception:
        pass

    # ATR-based extension estimate from features
    atr_extension = 0.0
    try:
        for tf in ("15m", "5m", "1h"):
            raw = redis_client.hgetall(f"unified_features:{symbol}:{tf}")
            if not raw:
                continue
            feat = _decode_map(raw)
            _atr = _find_feat(feat, "atr_pct", "atr_14")
            if _atr and _atr > atr_extension:
                atr_extension = _atr
    except Exception:
        pass

    if hold_score >= tp_hold_threshold:
        strength = min(2.0, hold_score / tp_hold_threshold)
        extension = max(0.5, atr_extension * strength * 0.8)
        if _distress_boost > 0.1:
            extension *= 1.5
        extension = min(extension, 5.0)

        reason = (
            f"TP_HOLD hold={hold_score:.3f}>={tp_hold_threshold} "
            f"ext={extension:.2f}% regime={components.get('regime', 0):.2f} "
            f"feat={components.get('features', 0):.2f} "
            f"trainer={components.get('trainer_intent', 0):.2f}"
            + (f" distress_boost={_distress_boost:.3f}" if _distress_boost > 0 else "")
        )
        logger.info(
            "ICG_TP_HOLD | sym=%s side=%s | hold_score=%.3f | "
            "extension=%.2f%% | roe=%.1f%% | %s",
            symbol, side_upper, hold_score, extension, current_roe, reason,
        )
        return TPHoldVerdict(True, extension, hold_score, reason, components)

    return TPHoldVerdict(
        False, 0.0, hold_score,
        f"TP_RELEASE hold={hold_score:.3f}<{tp_hold_threshold}",
        components,
    )
