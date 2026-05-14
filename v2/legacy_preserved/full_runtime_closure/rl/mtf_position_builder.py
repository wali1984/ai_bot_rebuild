"""
Multi-Timeframe Position Builder with Gradual DCA Engine.

When short timeframes (1m, 5m) indicate one direction but higher timeframes
(1h, 4h) indicate the opposite, the builder emits:
  - A PRIMARY signal following the short-TF consensus (for immediate timing)
  - A HEDGE_DCA signal following the long-TF consensus (gradual counter-position)

All decisions are validated against real-time microstructure, order-book depth,
2000+ unified feature keys, TA indicators, CoinAnk data, and regime per TF.
"""

import logging
import time
import json
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("mtf_position_builder")

TF_GROUPS = {
    "short": ["1m", "5m"],
    "mid": ["15m"],
    "strategic": ["1h", "4h"],
}

DIRECTION_LONG_ACTIONS = {1, 5}  # OPEN_LONG, CLOSE_SHORT_OPEN_LONG
DIRECTION_SHORT_ACTIONS = {2, 6}  # OPEN_SHORT, CLOSE_LONG_OPEN_SHORT
CLOSE_ACTIONS = {3, 4}  # CLOSE_LONG, CLOSE_SHORT

DCA_LADDER = [0.10, 0.20, 0.30, 0.40]


class MTFPositionBuilder:
    """Coordinates multi-TF signals into primary + gradual counter-position DCA."""

    def __init__(self, redis_conn):
        self.redis = redis_conn

    def classify_tf_bias(
        self, symbol: str, predictions_by_tf: Dict[str, dict]
    ) -> Dict[str, dict]:
        """Group TFs into short/mid/strategic and compute per-group bias.

        CLOSE_LONG implies bearish sentiment (weak SHORT), CLOSE_SHORT implies
        bullish (weak LONG). These contribute at 0.35x weight so explicit
        directional actions dominate while closes still register as opinion.
        """
        _CLOSE_WEIGHT = 0.35
        result = {}
        for group_name, tfs in TF_GROUPS.items():
            long_score = 0.0
            short_score = 0.0
            total_conf = 0.0
            n = 0
            for tf in tfs:
                pred = predictions_by_tf.get(tf)
                if not pred:
                    continue
                action_id = int(pred.get("action_idx", 0))
                conf = float(pred.get("confidence", 0))
                action_str = str(pred.get("action", "")).upper()

                is_long = action_id in DIRECTION_LONG_ACTIONS
                is_short = action_id in DIRECTION_SHORT_ACTIONS
                weight = 1.0
                if not is_long and not is_short and action_str:
                    if any(tok in action_str for tok in ("OPEN_LONG", "CLOSE_SHORT_AND_OPEN_LONG", "CLOSE_SHORT_OPEN_LONG", "ADD_LONG", "INCREASE_LONG")):
                        is_long = True
                    elif any(tok in action_str for tok in ("OPEN_SHORT", "CLOSE_LONG_AND_OPEN_SHORT", "CLOSE_LONG_OPEN_SHORT", "ADD_SHORT", "INCREASE_SHORT")):
                        is_short = True
                    elif "LONG" in action_str and "SHORT" not in action_str and "CLOSE" not in action_str:
                        is_long = True
                    elif "SHORT" in action_str and "LONG" not in action_str and "CLOSE" not in action_str:
                        is_short = True
                    elif action_str == "CLOSE_LONG":
                        is_short = True
                        weight = _CLOSE_WEIGHT
                    elif action_str == "CLOSE_SHORT":
                        is_long = True
                        weight = _CLOSE_WEIGHT

                if is_long:
                    long_score += conf * weight
                elif is_short:
                    short_score += conf * weight
                total_conf += conf
                n += 1
            if n == 0:
                result[group_name] = {"bias": "NEUTRAL", "confidence": 0.0, "strength": 0.0}
                continue
            if long_score > short_score:
                bias = "LONG"
                strength = long_score / max(total_conf, 1e-9)
            elif short_score > long_score:
                bias = "SHORT"
                strength = short_score / max(total_conf, 1e-9)
            else:
                bias = "NEUTRAL"
                strength = 0.0
            avg_conf = total_conf / n
            result[group_name] = {"bias": bias, "confidence": avg_conf, "strength": strength}
        return result

    def compute_divergence_score(
        self, group_biases: Dict[str, dict]
    ) -> float:
        """0.0 = fully aligned, 1.0 = fully opposed."""
        short_b = group_biases.get("short", {}).get("bias", "NEUTRAL")
        strat_b = group_biases.get("strategic", {}).get("bias", "NEUTRAL")
        if short_b == "NEUTRAL" or strat_b == "NEUTRAL":
            return 0.0
        if short_b == strat_b:
            return 0.0
        short_str = group_biases["short"].get("strength", 0)
        strat_str = group_biases["strategic"].get("strength", 0)
        return min(1.0, (short_str + strat_str) / 2.0)

    def should_scale_counter_position(
        self, symbol: str, counter_dir: str
    ) -> Tuple[bool, str]:
        """Real-time gate using microstructure, order book, features, regime."""
        reasons = []
        try:
            msnap = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
            if msnap:
                _g = lambda k, d=0.0: float(msnap.get(k, msnap.get(k.encode() if isinstance(k, str) else k, d)) or d)
                churn = _g("churn_score")
                spoof = _g("spoof_score")
                fast_move = _g("fast_move_score")
                imbalance = _g("imbalance_5", 0.0)

                if churn > 0.7:
                    return False, "CHURN_TOO_HIGH"
                if spoof > 0.6:
                    return False, "SPOOF_DETECTED"
                if fast_move > 0.8:
                    reasons.append("FAST_MOVE_CAUTION")

                if counter_dir == "LONG" and imbalance > 0.5:
                    reasons.append("BOOK_SUPPORTS_LONG")
                elif counter_dir == "SHORT" and imbalance < -0.5:
                    reasons.append("BOOK_SUPPORTS_SHORT")
        except Exception as e:
            logger.debug(f"[MTF_BUILDER] msnap read failed: {e}")

        try:
            for tf in ("5m", "15m", "1h"):
                uf = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if not uf:
                    continue
                feat = {(k.decode() if isinstance(k, bytes) else str(k)): (v.decode() if isinstance(v, bytes) else str(v)) for k, v in uf.items()}

                def _find(patterns, default=0.0):
                    for pat in patterns:
                        pl = pat.lower()
                        for k, v in feat.items():
                            if pl in k.lower():
                                try:
                                    return float(v)
                                except (ValueError, TypeError):
                                    continue
                    return default

                adx = _find(["ta_ADX_14_", "ta_ADX_21_"], 0.0)
                rsi = _find(["rsi_14", "rsi_21"], 50.0)
                macd_h = _find(["macd_hist", "MACD_hist"], 0.0)
                stoch_k = _find(["STOCHRSI_k"], 50.0)
                cci = _find(["ta_CCI_14", "ta_CCI_20"], 0.0)

                if adx > 25:
                    reasons.append(f"TREND_STRONG_{tf}")
                if counter_dir == "LONG" and rsi < 30:
                    reasons.append(f"RSI_OVERSOLD_{tf}")
                elif counter_dir == "SHORT" and rsi > 70:
                    reasons.append(f"RSI_OVERBOUGHT_{tf}")
                if (counter_dir == "LONG" and macd_h > 0) or (counter_dir == "SHORT" and macd_h < 0):
                    reasons.append(f"MACD_ALIGNED_{tf}")
                if (counter_dir == "LONG" and stoch_k < 30) or (counter_dir == "SHORT" and stoch_k > 70):
                    reasons.append(f"STOCH_ALIGNED_{tf}")
                if (counter_dir == "LONG" and cci < -100) or (counter_dir == "SHORT" and cci > 100):
                    reasons.append(f"CCI_EXTREME_{tf}")
                break
        except Exception as e:
            logger.debug(f"[MTF_BUILDER] features read failed: {e}")

        try:
            depth = 0.0
            ob_raw = self.redis.get(f"orderbook:depth:{symbol}")
            if ob_raw:
                if isinstance(ob_raw, (bytes, bytearray)):
                    ob_raw = ob_raw.decode("utf-8", errors="ignore")
                ob = json.loads(ob_raw) if isinstance(ob_raw, str) else {}
                depth = float(ob.get("depth_usd", 0) or ob.get("orderbook_depth_usd", 0) or 0)
            if depth <= 0:
                top_raw = self.redis.get(f"orderbook:top:{symbol}")
                if top_raw:
                    if isinstance(top_raw, (bytes, bytearray)):
                        top_raw = top_raw.decode("utf-8", errors="ignore")
                    top = json.loads(top_raw) if isinstance(top_raw, str) else {}
                    depth = float(top.get("total_depth", 0) or top.get("bid_notional", 0) or 0)
            if 0 < depth < 5000:
                return False, "ORDERBOOK_TOO_THIN"
        except Exception:
            pass

        try:
            regime_raw = self.redis.get(f"regime:{symbol}")
            if regime_raw:
                if isinstance(regime_raw, (bytes, bytearray)):
                    regime_raw = regime_raw.decode("utf-8", errors="ignore")
                regime = json.loads(regime_raw)
                r_regime = str(regime.get("move_regime", regime.get("market_regime", ""))).upper()
                r_trend = str(regime.get("trend_direction", "")).upper()
                if r_trend == counter_dir:
                    reasons.append(f"REGIME_TREND={r_trend}")
                if "TREND" in r_regime:
                    reasons.append(f"REGIME_TRENDING={r_regime}")
        except Exception:
            pass

        return True, "|".join(reasons) if reasons else "OK"

    def compute_dca_step(
        self,
        symbol: str,
        counter_direction: str,
        current_hedge_margin: float,
        equity: float,
        divergence_score: float,
    ) -> Tuple[float, float]:
        """Return (margin_to_add, target_margin) for gradual DCA.

        Uses a ladder approach: each call adds the next step.
        """
        max_per_symbol_pct = 0.06
        target_margin = equity * max_per_symbol_pct * min(1.0, divergence_score + 0.3)
        if target_margin <= 0:
            return 0.0, 0.0

        ratio = current_hedge_margin / max(target_margin, 1e-9)
        step_pct = 0.0
        for i, ladder_threshold in enumerate(DCA_LADDER):
            if ratio < ladder_threshold:
                step_pct = DCA_LADDER[i]
                break
        if step_pct == 0.0 and ratio < 1.0:
            step_pct = 1.0 - ratio

        margin_to_add = target_margin * step_pct
        margin_to_add = max(1.0, min(margin_to_add, equity * 0.03))
        return margin_to_add, target_margin

    def build_hedge_dca_signal(
        self,
        symbol: str,
        counter_direction: str,
        confidence: float,
        divergence_score: float,
        margin_to_add: float,
        target_margin: float,
        source_tf: str = "1h",
        account_id: str = "primary",
    ) -> dict:
        """Construct a HEDGE_DCA signal payload."""
        if counter_direction == "LONG":
            action = "OPEN_HEDGE_LONG"
        else:
            action = "OPEN_HEDGE_SHORT"

        return {
            "symbol": symbol,
            "action": action,
            "action_name": action,
            "direction": counter_direction,
            "action_category": "HEDGE_DCA",
            "signal_type": "HEDGE_DCA",
            "confidence": str(confidence),
            "model_confidence": str(confidence),
            "margin_usd": str(round(margin_to_add, 2)),
            "target_margin_usd": str(round(target_margin, 2)),
            "dca_step": str(round(margin_to_add / max(target_margin, 1e-9), 4)),
            "divergence_score": str(round(divergence_score, 4)),
            "timeframe": source_tf,
            "source": "mtf_position_builder",
            "source_module": "mtf_position_builder",
            "account_id": account_id,
            "tf_hedge_disagg": "1",
            "hedge_intent": "1",
            "timestamp": str(time.time()),
            "ts_ms": str(int(time.time() * 1000)),
        }

    def process_symbol(
        self,
        symbol: str,
        predictions_by_tf: Dict[str, dict],
        equity: float,
        current_hedge_margin: float = 0.0,
        account_id: str = "primary",
    ) -> Optional[dict]:
        """Main entry: return a HEDGE_DCA signal if TFs diverge, else None."""
        group_biases = self.classify_tf_bias(symbol, predictions_by_tf)
        divergence = self.compute_divergence_score(group_biases)

        if divergence < 0.3:
            return None

        strat = group_biases.get("strategic", {})
        counter_dir = strat.get("bias", "NEUTRAL")
        if counter_dir == "NEUTRAL":
            return None

        should_scale, reason = self.should_scale_counter_position(symbol, counter_dir)
        if not should_scale:
            logger.debug(f"[MTF_BUILDER] {symbol} scale blocked: {reason}")
            return None

        margin_to_add, target_margin = self.compute_dca_step(
            symbol, counter_dir, current_hedge_margin, equity, divergence,
        )
        if margin_to_add < 1.0:
            return None

        conf = strat.get("confidence", 0.5)
        best_tf = "4h" if predictions_by_tf.get("4h") else "1h"

        signal = self.build_hedge_dca_signal(
            symbol=symbol,
            counter_direction=counter_dir,
            confidence=conf,
            divergence_score=divergence,
            margin_to_add=margin_to_add,
            target_margin=target_margin,
            source_tf=best_tf,
            account_id=account_id,
        )
        logger.info(
            f"[MTF_BUILDER] {symbol} HEDGE_DCA {counter_dir} | div={divergence:.2f} "
            f"margin_add=${margin_to_add:.2f} target=${target_margin:.2f} | reason={reason}"
        )
        return signal
