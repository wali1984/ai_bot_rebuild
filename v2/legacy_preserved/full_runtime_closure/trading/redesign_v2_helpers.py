"""
Adaptive Redesign v2 — Shared Helpers (March 2026)

Evidence-based fixes from executed_signals forensics.
Used by stealth_stops.py, dynamic_adaptive_stops.py, trader.py, hybrid_trainer.py.
"""

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("redesign_v2")


def _decode_map(raw: dict) -> dict:
    """Decode Redis bytes→str map (handles both bytes and str keys/values)."""
    out = {}
    for k, v in raw.items():
        k2 = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
        v2 = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
        out[k2] = v2
    return out


def parse_unified_features_hash_for_dyn_threshold(uf: dict) -> tuple:
    """
    Extract (adx, volatility_score, tf_alignment) from a decoded unified_features hash.
    Handles optional JSON blob in field ``data`` (same convention as hybrid_trainer DQ checks).
    """
    adx_v = 0.0
    vol_s = 0.0
    tfa = 0.0
    if not uf:
        return (adx_v, vol_s, tfa)
    feat: Dict[str, Any] = {}
    try:
        fd = _decode_map(uf) if uf else {}
        raw = fd.get("data")
        if raw and isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    for k in ("features", "unified_features", "data"):
                        if isinstance(obj.get(k), dict):
                            obj = obj[k]
                            break
                    if isinstance(obj, dict):
                        feat = {str(k): (str(v) if v is not None else "") for k, v in obj.items()}
            except Exception:
                feat = {}
        if not feat:
            feat = fd
    except Exception:
        feat = {}

    def _fget(*keys, default=0.0) -> float:
        for k in keys:
            if k in feat:
                try:
                    return float(feat.get(k) or 0)
                except (ValueError, TypeError):
                    continue
        kl = [str(x).lower() for x in keys]
        for fk, fv in feat.items():
            fkl = str(fk).lower()
            for want in kl:
                if want in fkl or fkl.endswith(want):
                    try:
                        return float(fv or 0)
                    except (ValueError, TypeError):
                        continue
        return float(default)

    adx_v = _fget("adx", "ind_ta_adx_14", "ta_adx_14")
    vol_s = _fget("volatility_score", "momentum_score", "volatility")
    tfa = _fget("tf_alignment", "alignment_score", "xtf_alignment")
    return (float(adx_v), float(vol_s), float(tfa))


def read_unified_features_dyn_threshold_components(redis_client, symbol: str, tf: str) -> tuple:
    """Redis hgetall + parse for OPEN_RISK dynamic threshold (replaces broken JSON .get on key)."""
    if not redis_client or not symbol:
        return (0.0, 0.0, 0.0)
    tfx = str(tf or "5m").strip().lower()
    if tfx in ("multi", "deconflicted", "aggregate", ""):
        tfx = "5m"
    try:
        raw = redis_client.hgetall(f"unified_features:{str(symbol).upper().strip()}:{tfx}") or {}
        if not raw:
            return (0.0, 0.0, 0.0)
        return parse_unified_features_hash_for_dyn_threshold(raw)
    except Exception:
        return (0.0, 0.0, 0.0)


def get_atr_pct_for_symbol(redis_client, symbol: str, source_tf: str = "15m",
                            fallback_tf: str = "5m") -> float:
    """
    Get NATR (Normalized ATR) as % of price for a symbol from Redis features.
    
    Returns 0.0 if not available (caller should use fallback logic).
    Tries: unified_features:{symbol}:{source_tf} → ta_natr_14 fields,
    then cross-TF fields from 5m hash.
    """
    if not redis_client:
        return 0.0

    atr_pct = 0.0

    # Primary: read the specific TF hash
    for tf in (source_tf, fallback_tf, "1h", "4h"):
        try:
            feat_raw = redis_client.hgetall(f"unified_features:{symbol}:{tf}")
            if not feat_raw:
                continue
            feat = _decode_map(feat_raw)
            for k, v in feat.items():
                kl = k.lower()
                if "ta_natr_14" in kl or "natr_14" in kl:
                    try:
                        fv = float(v)
                        if fv > atr_pct:
                            atr_pct = fv
                    except (ValueError, TypeError):
                        continue
            if atr_pct > 0:
                return atr_pct
        except Exception:
            continue

    # Fallback: cross-TF fields in 5m hash
    try:
        feat5_raw = redis_client.hgetall(f"unified_features:{symbol}:5m")
        if feat5_raw:
            feat5 = _decode_map(feat5_raw)
            for k, v in feat5.items():
                kl = k.lower()
                if "xtf_" in kl and "atr_14" in kl:
                    try:
                        fv = float(v)
                        # xtf values may be raw ticks — need price context
                        # but NATR is already % so check magnitude
                        if 0 < fv < 50:  # sane NATR % range
                            if fv > atr_pct:
                                atr_pct = fv
                    except (ValueError, TypeError):
                        continue
    except Exception:
        pass

    return atr_pct


def get_regime_for_symbol(redis_client, symbol: str,
                           tf: str = "15m") -> dict:
    """
    Get regime data from Redis for symbol:tf.
    Returns dict with move_regime, trend_direction, tf_alignment etc.
    """
    if not redis_client:
        return {}
    try:
        raw = redis_client.get(f"regime:{symbol}:{tf}")
        if not raw:
            # Try without TF suffix (legacy key)
            raw = redis_client.get(f"regime:{symbol}")
        if raw:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            return json.loads(raw)
    except Exception:
        pass
    return {}


def compute_atr_tp_distance(redis_client, symbol: str, entry_price: float,
                             leverage: float, source_tf: str = "15m") -> Optional[float]:
    """
    Fix 1: Compute ATR-based TP distance as price %.
    Returns None if ATR data unavailable (caller should use legacy logic).
    """
    try:
        from config import (
            ATR_TP_ENABLED, ATR_TP_MULTIPLIER_MAP,
            ATR_TP_ABSOLUTE_FLOOR_PCT, ATR_TP_ABSOLUTE_CEILING_PCT,
        )
    except ImportError:
        return None

    if not ATR_TP_ENABLED:
        return None

    atr_pct = get_atr_pct_for_symbol(redis_client, symbol, source_tf)
    if atr_pct <= 0:
        return None

    regime = get_regime_for_symbol(redis_client, symbol, source_tf)
    move_regime = str(regime.get("move_regime", "NORMAL")).upper()

    multiplier = ATR_TP_MULTIPLIER_MAP.get(move_regime, 2.5)
    tp_distance_pct = atr_pct * multiplier

    # Clamp to absolute floor/ceiling
    tp_distance_pct = max(tp_distance_pct, ATR_TP_ABSOLUTE_FLOOR_PCT)
    tp_distance_pct = min(tp_distance_pct, ATR_TP_ABSOLUTE_CEILING_PCT)

    logger.info(
        "ATR_TP_CALC | sym=%s | atr_pct=%.3f%% | regime=%s | mult=%.1f | "
        "tp_dist=%.3f%% | floor=%.1f%% ceil=%.1f%% | lev=%.0fx",
        symbol, atr_pct, move_regime, multiplier,
        tp_distance_pct, ATR_TP_ABSOLUTE_FLOOR_PCT, ATR_TP_ABSOLUTE_CEILING_PCT,
        leverage,
    )

    return tp_distance_pct


def compute_atr_roi_kill_floor(redis_client, symbol: str,
                                leverage: float) -> Optional[float]:
    """
    Fix 3: Compute ATR-based ROI kill floor.
    Returns the floor ROI % (negative) that the kill threshold must not exceed.
    e.g., returns -161.0 meaning kill must be <= -161% ROI.
    Returns None if disabled or no ATR data.
    """
    try:
        from config import (
            ROI_KILL_ATR_FLOOR_ENABLED,
            ROI_KILL_ATR_FLOOR_MULTIPLIER,
            ROI_KILL_ATR_SOURCE_TF,
        )
    except ImportError:
        return None

    if not ROI_KILL_ATR_FLOOR_ENABLED:
        return None

    atr_pct = get_atr_pct_for_symbol(redis_client, symbol, ROI_KILL_ATR_SOURCE_TF)
    if atr_pct <= 0:
        return None

    # ATR floor in price %
    atr_floor_price_pct = atr_pct * ROI_KILL_ATR_FLOOR_MULTIPLIER
    # Convert to ROI % at this leverage (ROI = price_move% * leverage)
    atr_floor_roi_pct = -(atr_floor_price_pct * leverage)

    logger.info(
        "ROI_KILL_ATR_FLOOR | sym=%s | atr=%.3f%% | mult=%.1f | "
        "floor_price=%.3f%% | floor_roi=%.1f%% | lev=%.0fx",
        symbol, atr_pct, ROI_KILL_ATR_FLOOR_MULTIPLIER,
        atr_floor_price_pct, atr_floor_roi_pct, leverage,
    )

    return atr_floor_roi_pct


def check_dedup_guard(redis_client, signal: dict, account_id: str) -> bool:
    """
    Fix 4: Signal dedup guard using Redis SET NX.
    Returns True if signal is a DUPLICATE (should be skipped).
    Returns False if signal is new (proceed with execution).
    """
    try:
        from config import DEDUP_GUARD_ENABLED, DEDUP_GUARD_TTL_SECONDS
    except ImportError:
        return False

    if not DEDUP_GUARD_ENABLED or not redis_client:
        return False

    # Get a unique signal identifier
    pid = (
        signal.get("proposal_id")
        or signal.get("signal_id")
        or signal.get("id")
    )
    if not pid:
        return False

    key = f"signal:dedup:{pid}:{account_id}"
    try:
        was_new = redis_client.set(key, account_id, nx=True, ex=DEDUP_GUARD_TTL_SECONDS)
        if not was_new:
            logger.info(
                "DEDUP_GUARD_SKIP | pid=%s | account=%s | already processed",
                pid, account_id,
            )
            return True  # Duplicate
    except Exception as e:
        logger.debug("DEDUP_GUARD_ERR | %s | %s", pid, e)

    return False  # Not duplicate


def check_side_guard(redis_client, symbol: str, expected_side: str,
                      account_id: str) -> bool:
    """
    Fix 5: Side-aware close guard.
    Returns True if position exists on the expected side.
    Returns False if no position on that side (close should be skipped).
    """
    try:
        from config import SIDE_GUARD_ENABLED
    except ImportError:
        return True  # Default: allow

    if not SIDE_GUARD_ENABLED or not redis_client:
        return True

    expected_side_u = expected_side.upper()

    # Check portfolio positions for this account
    try:
        pos_key = f"portfolio:positions:{account_id}"
        pos_data = redis_client.hgetall(pos_key)
        if not pos_data:
            # Try live positions key
            for sym_side_key in [f"{symbol}:{expected_side_u}"]:
                live_key = f"positions:live:{account_id}:{symbol}"
                live_data = redis_client.hgetall(live_key)
                if live_data:
                    ld = _decode_map(live_data)
                    side = str(ld.get("side", "")).upper()
                    size = abs(float(ld.get("size", 0) or ld.get("positionAmt", 0) or 0))
                    if size > 0 and side == expected_side_u:
                        return True
            logger.info(
                "SIDE_GUARD_BLOCK | sym=%s | expected_side=%s | account=%s | no_position_found",
                symbol, expected_side_u, account_id,
            )
            return False

        pd = _decode_map(pos_data)
        check_key = f"{symbol}:{expected_side_u}"
        pos_json = pd.get(check_key)
        if pos_json:
            try:
                pos = json.loads(pos_json)
                size = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or 0))
                if size > 0:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass

        logger.info(
            "SIDE_GUARD_BLOCK | sym=%s | expected_side=%s | account=%s | position_not_found",
            symbol, expected_side_u, account_id,
        )
        return False
    except Exception as e:
        logger.debug("SIDE_GUARD_ERR | %s | %s", symbol, e)
        return True  # On error, allow (fail-open for safety)


def check_hard_hold_floor(redis_client, symbol: str, side: str,
                           account_id: str, source_tf: str = "multi",
                           leverage: float = 1.0) -> bool:
    """
    Fix 6: Hard hold floor check.
    Returns True if position has been held long enough (OK to close).
    Returns False if position is too new (block close).
    
    Only bypassed by liquidation proximity < HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT.
    """
    try:
        from config import (
            HARD_HOLD_FLOOR_ENABLED,
            HARD_HOLD_FLOOR_SECONDS,
            HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT,
        )
    except ImportError:
        return True  # Default: allow

    if not HARD_HOLD_FLOOR_ENABLED or not redis_client:
        return True

    # Get minimum hold seconds for this TF
    min_hold_s = HARD_HOLD_FLOOR_SECONDS.get(source_tf, HARD_HOLD_FLOOR_SECONDS.get("multi", 600))

    # Get position open time
    try:
        pos_key = f"positions:live:{account_id}:{symbol}"
        pos_data = redis_client.hgetall(pos_key)
        if not pos_data:
            return True  # No position data → allow
        pd = _decode_map(pos_data)

        open_ts = float(pd.get("open_ts_ms", 0) or pd.get("ts_ms", 0) or pd.get("updateTime", 0) or 0)
        if open_ts > 1e12:  # milliseconds
            open_ts /= 1000.0
        if open_ts <= 0:
            return True  # No timestamp → allow

        held_seconds = time.time() - open_ts
        if held_seconds >= min_hold_s:
            return True  # Held long enough

        # Check liquidation proximity bypass
        liq_dist_pct = 100.0 / max(1.0, leverage)
        if liq_dist_pct < HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT:
            logger.info(
                "HARD_HOLD_LIQ_BYPASS | sym=%s side=%s | held=%.0fs < min=%ds | "
                "liq_dist=%.2f%% < bypass=%.1f%%",
                symbol, side, held_seconds, min_hold_s,
                liq_dist_pct, HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT,
            )
            return True  # Liq proximity bypass

        logger.info(
            "HARD_HOLD_BLOCK | sym=%s side=%s | held=%.0fs < min=%ds | "
            "source_tf=%s | account=%s",
            symbol, side, held_seconds, min_hold_s,
            source_tf, account_id,
        )
        return False  # Block: too new

    except Exception as e:
        logger.debug("HARD_HOLD_CHECK_ERR | %s | %s", symbol, e)
        return True  # On error, allow


def extract_dominant_tf(tf_votes: dict, min_weight: float = 0.30) -> str:
    """
    Fix 7: Extract dominant TF from tf_votes dict.
    Returns the TF with highest vote strength, else "multi".
    tf_votes: {"4h": 1, "1h": 0, "15m": -1, "5m": 1} (direction votes)
    
    NOTE (2026-04-02): Removed HTF weight bias (4h:4.0, 5m:1.0) as it caused
    ~100% of signals to be attributed to 4h. Now uses EQUAL WEIGHTS so each TF
    competes fairly based on vote strength alone.
    
    When multiple TFs are tied, rotate selection to ensure fair distribution.
    """
    import random
    
    try:
        from config import DOMINANT_TF_EXTRACTION_ENABLED, DOMINANT_TF_MIN_WEIGHT
        if not DOMINANT_TF_EXTRACTION_ENABLED:
            return "multi"
        min_weight = DOMINANT_TF_MIN_WEIGHT
    except ImportError:
        pass

    if not tf_votes or not isinstance(tf_votes, dict):
        return "multi"

    # EQUAL WEIGHTS: Each TF competes fairly (no HTF bias)
    # This ensures 5m, 15m, 1h, 4h all have equal opportunity to be dominant
    tf_weight_map = {"4h": 1.0, "1h": 1.0, "15m": 1.0, "5m": 1.0, "1m": 0.5}  # 1m still lower (noise)

    # Find all TFs with strongest directional vote (collect ties)
    candidates = []  # List of (tf, score) tuples with max score
    best_score = 0.0
    total_weight = 0.0

    for tf, vote in tf_votes.items():
        try:
            v = abs(float(vote))
            w = tf_weight_map.get(tf, 1.0)
            score = v * w
            total_weight += w
            if score > best_score:
                best_score = score
                candidates = [(tf, score)]  # Reset to single best
            elif score == best_score and score > 0:
                candidates.append((tf, score))  # Add tie
        except (ValueError, TypeError):
            continue

    # If we have multiple tied TFs, randomly select one for fair distribution
    if len(candidates) > 1:
        best_tf = random.choice(candidates)[0]
    elif len(candidates) == 1:
        best_tf = candidates[0][0]
    else:
        best_tf = "multi"

    # Check if dominant TF meets minimum weight threshold
    if total_weight > 0 and best_score / total_weight >= min_weight:
        return best_tf

    # Fallback: randomly select from TFs with non-zero vote (not just HTF preference)
    fallback_tfs = []
    for tf in ("5m", "15m", "1h", "4h"):  # Ordered from fastest to slowest
        try:
            v = abs(float(tf_votes.get(tf, 0)))
            if v > 0:
                fallback_tfs.append(tf)
        except (ValueError, TypeError):
            continue
    
    if fallback_tfs:
        return random.choice(fallback_tfs)

    return "multi"


def _direction_flip_early_release_ok(
    redis_client, symbol: str, new_dir_u: str, _existing_dir: str
) -> Tuple[bool, str]:
    """Strict early release: fresh multi prediction agrees with new dir + microstructure."""
    try:
        from config import (
            DIRECTION_FLIP_EARLY_RELEASE_ENABLED,
            DIRECTION_FLIP_EARLY_RELEASE_MIN_PRED_CONF,
            DIRECTION_FLIP_EARLY_RELEASE_IMB_ABS,
            DIRECTION_FLIP_EARLY_RELEASE_FAST_MOVE,
        )
    except ImportError:
        return False, "cfg_missing"
    if not DIRECTION_FLIP_EARLY_RELEASE_ENABLED:
        return False, "disabled"
    try:
        pred_raw = redis_client.hgetall(f"prediction:{str(symbol).upper().strip()}:multi") or {}
        pred = _decode_map(pred_raw) if pred_raw else {}
        pdir = str(pred.get("direction") or "").upper()
        try:
            pconf = float(pred.get("confidence") or pred.get("model_confidence") or 0.0)
        except (ValueError, TypeError):
            pconf = 0.0
        if pdir != new_dir_u or pconf < float(DIRECTION_FLIP_EARLY_RELEASE_MIN_PRED_CONF):
            return False, "pred_mismatch"

        msnap_raw = redis_client.hgetall(f"msnap:coinapi_wsds:{str(symbol).upper().strip()}") or {}
        msnap = _decode_map(msnap_raw) if msnap_raw else {}
        try:
            imb = float(msnap.get("trade_imbalance_5s", 0) or 0.0)
        except (ValueError, TypeError):
            imb = 0.0
        imb_thr = float(DIRECTION_FLIP_EARLY_RELEASE_IMB_ABS)
        imb_ok = (new_dir_u == "LONG" and imb >= imb_thr) or (new_dir_u == "SHORT" and imb <= -imb_thr)

        fm = 0.0
        try:
            uf = redis_client.hgetall(f"unified_features:{str(symbol).upper().strip()}:5m") or {}
            for fk, fv in _decode_map(uf).items():
                if "fast_move" in str(fk).lower():
                    try:
                        fm = max(fm, float(fv))
                    except (ValueError, TypeError):
                        continue
        except Exception:
            pass
        fm_ok = fm >= float(DIRECTION_FLIP_EARLY_RELEASE_FAST_MOVE)

        if imb_ok or fm_ok:
            return True, "imb" if imb_ok else "fast_move"
        return False, "micro_weak"
    except Exception as _e:
        logger.debug("EARLY_RELEASE_ERR | %s | %s", symbol, _e)
        return False, "error"


def check_direction_flip_cooldown(redis_client, symbol: str,
                                    new_direction: str,
                                    source_tf: str = "multi") -> bool:
    """
    Fix 8: Direction flip cooldown.
    Returns True if direction change is ALLOWED.
    Returns False if still in cooldown (should block).
    """
    try:
        from config import (
            DIRECTION_FLIP_COOLDOWN_ENABLED,
            DIRECTION_FLIP_COOLDOWN_SECONDS,
            DIRECTION_FLIP_NATR_SCALE_ENABLED,
            DIRECTION_FLIP_COOLDOWN_NATR_REF_PCT,
            DIRECTION_FLIP_COOLDOWN_NATR_MIN_MULT,
            DIRECTION_FLIP_COOLDOWN_NATR_MAX_MULT,
        )
    except ImportError:
        return True

    if not DIRECTION_FLIP_COOLDOWN_ENABLED or not redis_client:
        return True

    sym_u = str(symbol or "").upper().strip()
    if not sym_u:
        return True

    new_dir_u = new_direction.upper()
    if new_dir_u not in ("LONG", "SHORT"):
        return True  # Non-directional: allow

    base_cd = float(
        DIRECTION_FLIP_COOLDOWN_SECONDS.get(
            source_tf, DIRECTION_FLIP_COOLDOWN_SECONDS.get("multi", 300)
        )
    )
    cooldown_s = int(max(30, round(base_cd)))
    if DIRECTION_FLIP_NATR_SCALE_ENABLED:
        natr = float(get_atr_pct_for_symbol(redis_client, sym_u, source_tf, "5m"))
        ref = max(float(DIRECTION_FLIP_COOLDOWN_NATR_REF_PCT), 0.02)
        lo = float(DIRECTION_FLIP_COOLDOWN_NATR_MIN_MULT)
        hi = float(DIRECTION_FLIP_COOLDOWN_NATR_MAX_MULT)
        if natr > 0:
            mult = ref / max(natr, 0.05)
            mult = max(lo, min(hi, mult))
            cooldown_s = int(max(30, round(base_cd * mult)))

    lock_key = f"direction_lock:{sym_u}"
    try:
        existing = redis_client.get(lock_key)
        if existing:
            if isinstance(existing, (bytes, bytearray)):
                existing = existing.decode("utf-8")
            existing_dir = existing.upper()
            # Same direction: always allow
            if existing_dir == new_dir_u:
                return True
            # Opposite direction: check TTL
            ttl = redis_client.ttl(lock_key)
            if ttl and ttl > 0:
                _er_ok, _er_why = _direction_flip_early_release_ok(
                    redis_client, sym_u, new_dir_u, existing_dir
                )
                if not _er_ok:
                    logger.info(
                        "FLIP_COOLDOWN_BLOCK | sym=%s | current=%s | requested=%s | "
                        "ttl=%ds | source_tf=%s | lock_cd=%ds | early_rel=%s",
                        sym_u, existing_dir, new_dir_u, ttl, source_tf, cooldown_s, _er_why,
                    )
                    return False
                try:
                    redis_client.delete(lock_key)
                except Exception:
                    pass
                logger.info(
                    "FLIP_COOLDOWN_EARLY_RELEASE | sym=%s | was=%s | new=%s | "
                    "ttl_was=%ds | reason=%s | lock_cd=%ds",
                    sym_u, existing_dir, new_dir_u, ttl, _er_why, cooldown_s,
                )

        # Set new direction lock
        redis_client.set(lock_key, new_dir_u, ex=int(cooldown_s))
        return True  # Allow
    except Exception as e:
        logger.debug("FLIP_COOLDOWN_ERR | %s | %s", symbol, e)
        return True  # On error, allow


def check_governor_protect_winners(redis_client, symbol: str, side: str,
                                     account_id: str) -> bool:
    """
    Fix 9: Governor protect winners.
    Returns True if position should be PROTECTED from deleverage (skip deleverage).
    Returns False if position can be deleveraged normally.
    """
    try:
        from config import GOV_DELEVERAGE_PROTECT_WINNERS, GOV_DELEVERAGE_PROTECT_MIN_ROE_PCT
    except ImportError:
        return False

    if not GOV_DELEVERAGE_PROTECT_WINNERS or not redis_client:
        return False

    try:
        pos_key = f"positions:live:{account_id}:{symbol}"
        pos_data = redis_client.hgetall(pos_key)
        if not pos_data:
            return False
        pd = _decode_map(pos_data)

        roi = float(pd.get("roi_pct", 0) or pd.get("pnl_pct", 0) or 0)
        pnl = float(pd.get("unrealized_pnl", 0) or pd.get("unrealizedProfit", 0) or 0)
        margin = float(pd.get("margin_used", 0) or pd.get("initialMargin", 0) or pd.get("margin", 0) or 0)

        # Compute ROI if not directly available
        if abs(roi) < 0.01 and margin > 0 and abs(pnl) > 0:
            roi = (pnl / margin) * 100.0

        if roi < GOV_DELEVERAGE_PROTECT_MIN_ROE_PCT:
            return False  # Not profitable enough

        # Check regime alignment
        regime = get_regime_for_symbol(redis_client, symbol, "15m")
        trend_dir = str(regime.get("trend_direction", "")).upper()
        side_u = side.upper()
        aligned = (
            (side_u == "LONG" and trend_dir in ("LONG", "BULLISH", "UP"))
            or (side_u == "SHORT" and trend_dir in ("SHORT", "BEARISH", "DOWN"))
        )

        if aligned:
            logger.info(
                "GOV_PROTECT_WINNER | sym=%s side=%s | roi=%.1f%% | "
                "regime=%s aligned=%s | SKIPPING deleverage",
                symbol, side, roi, trend_dir, aligned,
            )
            return True  # Protect

        return False
    except Exception as e:
        logger.debug("GOV_PROTECT_ERR | %s | %s", symbol, e)
        return False


def check_regime_gate(redis_client, symbol: str,
                       signal_direction: str,
                       confidence: float = 0.0) -> bool:
    """
    Fix 10: Regime-gated entry.
    Returns True if entry is ALLOWED (at least 1 higher TF agrees).
    Returns False if entry should be BLOCKED (all TFs oppose).
    
    Fix B (Apr 2026): High-confidence override — when PPO confidence exceeds
    REGIME_GATE_CONFIDENCE_OVERRIDE, bypass the alignment requirement. This
    prevents the gate from killing high-conviction signals during trending
    markets where regime detection may lag.
    """
    try:
        from config import (REGIME_GATE_ENABLED, REGIME_GATE_REQUIRE_MIN_ALIGNMENT,
                           REGIME_GATE_CONFIDENCE_OVERRIDE, REGIME_GATE_CONFIDENCE_OVERRIDE_ENABLED)
    except ImportError:
        return True

    if not REGIME_GATE_ENABLED or not redis_client:
        return True

    dir_u = signal_direction.upper()
    if dir_u not in ("LONG", "SHORT"):
        return True

    aligned_count = 0
    checked_count = 0

    for tf in ("4h", "1h", "15m"):
        regime = get_regime_for_symbol(redis_client, symbol, tf)
        if not regime:
            continue
        checked_count += 1
        trend_dir = str(regime.get("trend_direction", "")).upper()
        if dir_u == "LONG" and trend_dir in ("LONG", "BULLISH", "UP"):
            aligned_count += 1
        elif dir_u == "SHORT" and trend_dir in ("SHORT", "BEARISH", "DOWN"):
            aligned_count += 1

    if checked_count == 0:
        return True  # No regime data: allow

    if aligned_count >= REGIME_GATE_REQUIRE_MIN_ALIGNMENT:
        return True  # Enough alignment

    # Fix B (Apr 2026): High-confidence override
    if REGIME_GATE_CONFIDENCE_OVERRIDE_ENABLED and confidence >= REGIME_GATE_CONFIDENCE_OVERRIDE:
        logger.info(
            "REGIME_GATE_CONF_OVERRIDE | sym=%s | direction=%s | aligned=%d/%d | conf=%.4f >= %.4f | ALLOWED",
            symbol, dir_u, aligned_count, checked_count, confidence, REGIME_GATE_CONFIDENCE_OVERRIDE,
        )
        return True

    logger.info(
        "REGIME_GATE_BLOCK | sym=%s | direction=%s | aligned=%d/%d | min_required=%d",
        symbol, dir_u, aligned_count, checked_count, REGIME_GATE_REQUIRE_MIN_ALIGNMENT,
    )
    return False


def check_signal_emit_cadence(redis_client, symbol: str,
                                action_category: str) -> bool:
    """
    Fix 12: Signal emit cadence.
    Returns True if signal emission is ALLOWED.
    Returns False if too soon (should be throttled).
    """
    try:
        from config import SIGNAL_EMIT_CADENCE_ENABLED, SIGNAL_EMIT_CADENCE
    except ImportError:
        return True

    if not SIGNAL_EMIT_CADENCE_ENABLED or not redis_client:
        return True

    cat = str(action_category).upper()
    cadence_s = SIGNAL_EMIT_CADENCE.get(cat, SIGNAL_EMIT_CADENCE.get("UNKNOWN", 10))
    if cadence_s <= 0:
        return True

    key = f"emit_cadence:{symbol}:{cat}"
    try:
        was_new = redis_client.set(key, "1", nx=True, ex=cadence_s)
        if not was_new:
            logger.debug(
                "CADENCE_THROTTLE | sym=%s | cat=%s | cadence=%ds",
                symbol, cat, cadence_s,
            )
            return False  # Throttled
        return True
    except Exception as e:
        logger.debug("CADENCE_ERR | %s | %s", symbol, e)
        return True


def check_hedge_protect_winners(redis_client, symbol: str,
                                  hedge_side: str, account_id: str,
                                  signal_confidence: float = 0.0) -> bool:
    """
    Fix 13: Hedge protect winners.
    Returns True if hedging is ALLOWED.
    Returns False if existing position is profitable + aligned → don't hedge.
    """
    try:
        from config import (
            HEDGE_PROTECT_WINNERS_ENABLED,
            HEDGE_PROTECT_WINNERS_MIN_ROE_PCT,
            HEDGE_PROTECT_WINNERS_MIN_REVERSAL_CONF,
        )
    except ImportError:
        return True

    if not HEDGE_PROTECT_WINNERS_ENABLED or not redis_client:
        return True

    # High reversal confidence overrides protection
    if signal_confidence >= HEDGE_PROTECT_WINNERS_MIN_REVERSAL_CONF:
        return True

    # Check the OPPOSITE side (the position we'd be hedging against)
    hedge_side_u = hedge_side.upper()
    main_side = "SHORT" if hedge_side_u == "LONG" else "LONG"

    try:
        pos_key = f"positions:live:{account_id}:{symbol}"
        pos_data = redis_client.hgetall(pos_key)
        if not pos_data:
            return True
        pd = _decode_map(pos_data)

        roi = float(pd.get("roi_pct", 0) or pd.get("pnl_pct", 0) or 0)
        pnl = float(pd.get("unrealized_pnl", 0) or pd.get("unrealizedProfit", 0) or 0)
        margin = float(pd.get("margin_used", 0) or pd.get("initialMargin", 0) or pd.get("margin", 0) or 0)
        pos_side = str(pd.get("side", "")).upper()

        if pos_side != main_side:
            return True  # No position on that side

        if abs(roi) < 0.01 and margin > 0 and abs(pnl) > 0:
            roi = (pnl / margin) * 100.0

        if roi < HEDGE_PROTECT_WINNERS_MIN_ROE_PCT:
            return True  # Not profitable enough to protect

        # Check regime alignment
        regime = get_regime_for_symbol(redis_client, symbol, "15m")
        trend_dir = str(regime.get("trend_direction", "")).upper()
        aligned = (
            (main_side == "LONG" and trend_dir in ("LONG", "BULLISH", "UP"))
            or (main_side == "SHORT" and trend_dir in ("SHORT", "BEARISH", "DOWN"))
        )

        if aligned:
            logger.info(
                "HEDGE_PROTECT_WINNER | sym=%s | main_side=%s roi=%.1f%% | "
                "hedge_side=%s blocked | regime=%s conf=%.2f < %.2f",
                symbol, main_side, roi, hedge_side_u,
                trend_dir, signal_confidence, HEDGE_PROTECT_WINNERS_MIN_REVERSAL_CONF,
            )
            return False  # Block hedge

        return True
    except Exception as e:
        logger.debug("HEDGE_PROTECT_ERR | %s | %s", symbol, e)
        return True


def check_tp_ratchet_block(entry_price: float, current_tp: float,
                            new_tp: float, is_long: bool) -> bool:
    """
    Fix 2: TP Ratchet-Down Block.
    Returns True if new TP should be BLOCKED (it's closer to entry than current).
    Returns False if new TP is OK (wider than current).
    """
    try:
        from config import TP_RATCHET_DOWN_BLOCK_ENABLED
    except ImportError:
        return False

    if not TP_RATCHET_DOWN_BLOCK_ENABLED:
        return False

    if entry_price <= 0 or current_tp <= 0 or new_tp <= 0:
        return False

    # Calculate distance from entry for both TPs
    if is_long:
        current_dist = current_tp - entry_price
        new_dist = new_tp - entry_price
    else:
        current_dist = entry_price - current_tp
        new_dist = entry_price - new_tp

    # Block if new TP is closer to entry (smaller distance)
    if new_dist < current_dist * 0.95:  # 5% tolerance for rounding
        logger.info(
            "TP_RATCHET_BLOCK | entry=%.6f | current_tp=%.6f (dist=%.4f%%) | "
            "new_tp=%.6f (dist=%.4f%%) | is_long=%s | BLOCKED (closer to entry)",
            entry_price, current_tp, current_dist / entry_price * 100,
            new_tp, new_dist / entry_price * 100, is_long,
        )
        return True  # Block

    return False  # Allow
