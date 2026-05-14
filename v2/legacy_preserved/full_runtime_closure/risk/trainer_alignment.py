"""
risk/trainer_alignment.py — Trainer Alignment Gate for Signal Publishers.

All systems that publish trade signals or proposals (orchestrator, stealth stops,
dynamic TP, hedge harvest, URC, etc.) MUST consult trainer alignment before publishing.

Reads from:
  prediction:{symbol}:{timeframe}  — Per-TF trainer predictions (hash)
  regime:{symbol}                  — Market regime assessment (JSON string)

Returns a TrainerView with:
  - consensus_direction (LONG/SHORT/NEUTRAL) — weighted across timeframes
  - best_target_price — from the highest-confidence directional prediction
  - regime — move_regime, volatility_score, tf_alignment, etc.
  - bias_dir — from TF vote alignment
  - alignment verdict for any proposed action/direction
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PREDICTION_STALE_SEC = 300
_TF_WEIGHTS = {"1m": 0.05, "5m": 0.10, "15m": 0.15, "1h": 0.20, "4h": 0.15, "multi": 0.35}
_TIMEFRAMES = ["5m", "15m", "1h", "4h", "multi"]


def _safe_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        return float(v)
    except Exception:
        return default


def _safe_str(v, default: str = "") -> str:
    try:
        if v is None:
            return default
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", errors="ignore")
        return str(v)
    except Exception:
        return default


@dataclass
class TFPrediction:
    timeframe: str
    action: str
    direction: str
    confidence: float
    price_target: float
    price_target_direction: str
    price_target_pct: float
    ppo_confidence: float
    masa_confidence: float
    timestamp: float
    published: bool


@dataclass
class TrainerView:
    """Comprehensive snapshot of the trainer's current stance on a symbol."""
    symbol: str
    predictions: Dict[str, TFPrediction] = field(default_factory=dict)
    consensus_direction: str = "NEUTRAL"
    consensus_confidence: float = 0.0
    best_target_price: float = 0.0
    best_target_direction: str = ""
    best_target_pct: float = 0.0
    best_target_tf: str = ""
    regime: Dict[str, Any] = field(default_factory=dict)
    bias_dir: int = 0
    tf_alignment: float = 0.0
    stale: bool = True
    freshest_ts: float = 0.0

    @property
    def is_directional(self) -> bool:
        return self.consensus_direction in ("LONG", "SHORT")

    @property
    def has_target(self) -> bool:
        return self.best_target_price > 0

    @property
    def move_regime(self) -> str:
        return str(self.regime.get("move_regime", ""))

    @property
    def volatility_score(self) -> float:
        return _safe_float(self.regime.get("volatility_score"))

    def action_aligns(self, action: str) -> Tuple[bool, str]:
        """Check if a proposed action aligns with the trainer's view.

        Returns (aligned, reason).
        For OPEN_RISK entries: direction must match consensus.
        For CLOSE/REDUCE: always allowed (protective).
        For HEDGE: always allowed (protective).
        For SET_TAKE_PROFIT/SIDECAR: always allowed.
        """
        a = str(action or "").upper()

        if any(t in a for t in ("CLOSE", "REDUCE", "DECREASE", "PARTIAL", "EXIT",
                                 "STOP_LOSS", "TAKE_PROFIT")):
            return True, "PROTECTIVE_ALWAYS_ALLOWED"

        if "HEDGE" in a:
            return True, "HEDGE_ALWAYS_ALLOWED"

        if any(t in a for t in ("SET_", "ARM_", "UPDATE_", "ADJUST")):
            return True, "SIDECAR_ALWAYS_ALLOWED"

        if a in ("HOLD", "NONE", "WAIT", "NO_ACTION", ""):
            return True, "HOLD_ALLOWED"

        if not self.is_directional:
            return True, "TRAINER_NEUTRAL_PASSTHROUGH"

        # For directional entries, check alignment
        action_dir = self._action_direction(a)
        if action_dir == "NEUTRAL":
            return True, "ACTION_NEUTRAL_PASSTHROUGH"

        if action_dir == self.consensus_direction:
            return True, "DIRECTION_ALIGNED"

        # Only enforce the block if trainer confidence is meaningful.
        # Low-confidence consensus (e.g. 0.34) is essentially noise — don't
        # let it veto a high-confidence entry signal from the orchestrator.
        try:
            import config as _cfg
            _min_conf = float(getattr(_cfg, "TRAINER_ALIGN_MIN_CONF_TO_BLOCK", 0.60))
        except Exception:
            _min_conf = 0.60
        if self.consensus_confidence < _min_conf:
            return True, (
                f"DIRECTION_CONFLICT_CONF_TOO_LOW trainer={self.consensus_direction} "
                f"conf={self.consensus_confidence:.3f}<{_min_conf} (passthrough)"
            )

        return False, f"DIRECTION_CONFLICT trainer={self.consensus_direction} action_dir={action_dir} conf={self.consensus_confidence:.3f}"

    def target_aligns_with_price(self, current_price: float, action: str) -> Tuple[bool, str]:
        """Check if the trainer's target price supports the proposed action direction.

        For OPEN_LONG: target should be above current price.
        For OPEN_SHORT: target should be below current price.
        """
        if self.best_target_price <= 0 or current_price <= 0:
            return True, "NO_TARGET_PASSTHROUGH"

        a = str(action or "").upper()
        if not any(t in a for t in ("OPEN_LONG", "OPEN_SHORT", "INCREASE_LONG",
                                     "INCREASE_SHORT")):
            return True, "NON_ENTRY_PASSTHROUGH"

        if "LONG" in a and "SHORT" not in a:
            if self.best_target_price > current_price:
                pct = ((self.best_target_price - current_price) / current_price) * 100
                return True, f"TARGET_ABOVE_PRICE +{pct:.2f}%"
            else:
                pct = ((current_price - self.best_target_price) / current_price) * 100
                return False, f"TARGET_BELOW_PRICE -{pct:.2f}% (LONG but target lower)"

        if "SHORT" in a and "LONG" not in a:
            if self.best_target_price < current_price:
                pct = ((current_price - self.best_target_price) / current_price) * 100
                return True, f"TARGET_BELOW_PRICE -{pct:.2f}%"
            else:
                pct = ((self.best_target_price - current_price) / current_price) * 100
                return False, f"TARGET_ABOVE_PRICE +{pct:.2f}% (SHORT but target higher)"

        return True, "DIRECTION_UNKNOWN_PASSTHROUGH"

    @staticmethod
    def _action_direction(action: str) -> str:
        a = str(action or "").upper()
        if any(x in a for x in ("OPEN_LONG", "INCREASE_LONG", "AND_LONG")):
            return "LONG"
        if any(x in a for x in ("OPEN_SHORT", "INCREASE_SHORT", "AND_SHORT")):
            return "SHORT"
        if "LONG" in a and "SHORT" not in a and "CLOSE" not in a:
            return "LONG"
        if "SHORT" in a and "LONG" not in a and "CLOSE" not in a:
            return "SHORT"
        return "NEUTRAL"


def get_trainer_view(redis_client, symbol: str) -> Optional[TrainerView]:
    """Read the trainer's complete view for a symbol from Redis.

    Reads prediction:{symbol}:{tf} hashes and regime:{symbol} key.
    Returns None if Redis unavailable or no data at all.
    """
    if not redis_client or not symbol:
        return None

    try:
        view = TrainerView(symbol=symbol)
        now = time.time()
        long_weight = 0.0
        short_weight = 0.0
        total_weight = 0.0
        best_conf = 0.0
        best_target = 0.0
        best_target_dir = ""
        best_target_pct = 0.0
        best_target_tf = ""

        try:
            pipe = redis_client.pipeline(transaction=False)
            for tf in _TIMEFRAMES:
                pipe.hgetall(f"prediction:{symbol}:{tf}")
            pipe.get(f"regime:{symbol}")
            results = pipe.execute()
        except Exception:
            return None

        tf_results = results[:len(_TIMEFRAMES)]
        regime_raw = results[len(_TIMEFRAMES)]

        for i, tf in enumerate(_TIMEFRAMES):
            data = tf_results[i]
            if not data:
                continue

            ts = _safe_float(data.get("timestamp", data.get(b"timestamp")))
            if ts <= 0 or (now - ts) > _PREDICTION_STALE_SEC:
                continue

            direction = _safe_str(data.get("direction", data.get(b"direction")))
            _action_raw = _safe_str(data.get("action", data.get(b"action")))
            if direction not in ("LONG", "SHORT"):
                try:
                    from risk.trainer_intent import infer_direction_from_action

                    _inf = infer_direction_from_action(_action_raw)
                    if _inf in ("LONG", "SHORT"):
                        direction = _inf
                except Exception:
                    pass
            confidence = _safe_float(data.get("confidence", data.get(b"confidence")))
            price_target = _safe_float(data.get("price_target", data.get(b"price_target")))
            price_target_dir = _safe_str(data.get("price_target_direction",
                                                    data.get(b"price_target_direction")))
            price_target_pct = _safe_float(data.get("price_target_pct",
                                                     data.get(b"price_target_pct")))
            ppo_conf = _safe_float(data.get("ppo_confidence", data.get(b"ppo_confidence")))
            masa_conf = _safe_float(data.get("masa_confidence", data.get(b"masa_confidence")))

            pred = TFPrediction(
                timeframe=tf,
                action=_action_raw,
                direction=direction,
                confidence=confidence,
                price_target=price_target,
                price_target_direction=price_target_dir,
                price_target_pct=price_target_pct,
                ppo_confidence=ppo_conf,
                masa_confidence=masa_conf,
                timestamp=ts,
                published=_safe_str(data.get("published", data.get(b"published"))) == "1",
            )
            view.predictions[tf] = pred

            if ts > view.freshest_ts:
                view.freshest_ts = ts

            w = _TF_WEIGHTS.get(tf, 0.1)
            total_weight += w
            if direction == "LONG":
                long_weight += w * confidence
            elif direction == "SHORT":
                short_weight += w * confidence

            if confidence > best_conf and direction in ("LONG", "SHORT"):
                best_conf = confidence
                if price_target > 0:
                    best_target = price_target
                    best_target_dir = price_target_dir or direction
                    best_target_pct = price_target_pct
                    best_target_tf = tf

        # JSON blob cache (some paths use SET prediction:{symbol}:latest instead of per-TF hashes)
        try:
            _raw_lat = redis_client.get(f"prediction:{symbol}:latest")
            if _raw_lat:
                _s = (
                    _raw_lat.decode("utf-8", errors="ignore")
                    if isinstance(_raw_lat, (bytes, bytearray))
                    else str(_raw_lat)
                )
                _jd = json.loads(_s) if _s.strip().startswith("{") else {}
                if isinstance(_jd, dict) and _jd:
                    _tsj = _safe_float(_jd.get("timestamp", _jd.get("ts_ms", 0)))
                    if _tsj > 1e12:
                        _tsj = _tsj / 1000.0
                    if _tsj <= 0 or (now - _tsj) <= _PREDICTION_STALE_SEC:
                        _map = {str(k): str(v) for k, v in _jd.items()}
                        _dirj = _safe_str(_map.get("direction"))
                        _actj = _safe_str(_map.get("action", _map.get("action_name")))
                        if _dirj not in ("LONG", "SHORT"):
                            try:
                                from risk.trainer_intent import infer_direction_from_action

                                _ij = infer_direction_from_action(_actj)
                                if _ij in ("LONG", "SHORT"):
                                    _dirj = _ij
                            except Exception:
                                pass
                        _confj = _safe_float(_map.get("confidence", _map.get("model_confidence", 0)))
                        _tgj = _safe_float(_map.get("price_target", 0))
                        if _dirj in ("LONG", "SHORT") and _confj > 0:
                            _wl = 0.08
                            total_weight += _wl
                            if _dirj == "LONG":
                                long_weight += _wl * _confj
                            else:
                                short_weight += _wl * _confj
                            if _tsj > view.freshest_ts:
                                view.freshest_ts = _tsj
                            if _confj > best_conf:
                                best_conf = _confj
                                if _tgj > 0:
                                    best_target = _tgj
                                    best_target_dir = _dirj
                                    best_target_tf = "latest"
        except Exception:
            pass

        # Consensus (per-TF hashes + optional JSON latest)
        if total_weight > 0:
            long_score = long_weight / total_weight
            short_score = short_weight / total_weight
            margin = abs(long_score - short_score)
            if margin > 0.05:
                view.consensus_direction = "LONG" if long_score > short_score else "SHORT"
                view.consensus_confidence = max(long_score, short_score)
            else:
                view.consensus_direction = "NEUTRAL"
                view.consensus_confidence = 0.0

        view.best_target_price = best_target
        view.best_target_direction = best_target_dir
        view.best_target_pct = best_target_pct
        view.best_target_tf = best_target_tf
        view.stale = view.freshest_ts <= 0 or (now - view.freshest_ts) > _PREDICTION_STALE_SEC

        # Regime
        if regime_raw:
            try:
                if isinstance(regime_raw, (bytes, bytearray)):
                    regime_raw = regime_raw.decode("utf-8", errors="ignore")
                view.regime = json.loads(regime_raw) if isinstance(regime_raw, str) else {}
                view.tf_alignment = _safe_float(view.regime.get("tf_alignment"))
                raw_bias = view.regime.get("tf_alignment", 0)
                if _safe_float(raw_bias) > 0.3:
                    view.bias_dir = 1
                elif _safe_float(raw_bias) < -0.3:
                    view.bias_dir = -1
            except Exception:
                pass

        return view

    except Exception as e:
        logger.debug("TRAINER_ALIGNMENT_ERR | symbol=%s | %s", symbol, e)
        return None


def check_alignment(
    redis_client,
    symbol: str,
    action: str,
    current_price: float = 0.0,
    source_module: str = "",
) -> Tuple[bool, str, Optional[TrainerView]]:
    """One-call alignment check for any signal publisher.

    Returns:
        (allowed, reason, trainer_view)

    Rules:
    - PROTECTIVE/HEDGE/SIDECAR actions: always allowed.
    - OPEN_RISK entries: must align with trainer consensus direction.
    - If trainer data is stale or unavailable: fail-open (allowed).
    - target_price alignment: informational warning, does not block.
    """
    view = get_trainer_view(redis_client, symbol)
    if view is None:
        return True, "NO_TRAINER_DATA", None

    if view.stale:
        return True, "TRAINER_DATA_STALE", view

    aligned, reason = view.action_aligns(action)
    if not aligned:
        logger.warning(
            "[TRAINER_ALIGN] BLOCKED %s %s | %s | consensus=%s conf=%.3f "
            "target=%.6f regime=%s | source=%s",
            symbol, action, reason, view.consensus_direction,
            view.consensus_confidence, view.best_target_price,
            view.move_regime, source_module,
        )
        return False, reason, view

    if current_price > 0:
        target_ok, target_reason = view.target_aligns_with_price(current_price, action)
        if not target_ok:
            logger.warning(
                "[TRAINER_ALIGN] TARGET_WARN %s %s | %s | price=%.6f target=%.6f | source=%s",
                symbol, action, target_reason, current_price,
                view.best_target_price, source_module,
            )

    return True, reason, view


def enrich_proposal_with_trainer(
    redis_client,
    proposal: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich a proposal dict with trainer alignment context.

    Adds trainer_* fields without modifying existing fields.
    """
    symbol = str(proposal.get("symbol") or "")
    if not symbol:
        return proposal

    view = get_trainer_view(redis_client, symbol)
    if view is None:
        return proposal

    proposal["trainer_consensus_direction"] = view.consensus_direction
    proposal["trainer_consensus_confidence"] = round(view.consensus_confidence, 4)
    proposal["trainer_target_price"] = view.best_target_price
    proposal["trainer_target_direction"] = view.best_target_direction
    proposal["trainer_target_pct"] = round(view.best_target_pct, 6)
    proposal["trainer_target_tf"] = view.best_target_tf
    proposal["trainer_move_regime"] = view.move_regime
    proposal["trainer_volatility_score"] = round(view.volatility_score, 4)
    proposal["trainer_bias_dir"] = view.bias_dir
    proposal["trainer_tf_alignment"] = round(view.tf_alignment, 4)
    proposal["trainer_stale"] = view.stale

    return proposal
