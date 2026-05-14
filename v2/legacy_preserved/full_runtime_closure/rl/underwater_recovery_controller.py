"""
Underwater Recovery Controller (URC)
==================================
Stage 1 implementation: hedged recovery adds ONLY (no loss closures, no decage).

Design goals (per Documentation/Trainer-recovery-Options.md):
- No-realized-loss by default (URC emits no CLOSE actions)
- Hedged recovery adds only (never unhedged averaging)
- Avoid “top/bottom” recovery adds via reversal confirmation + manipulation dampening
- Account-scoped decisions (primary/asjad independent)

URC consumes:
- portfolio:positions:{account_id} (canonical per-leg snapshots from traders)
- portfolio:equity:{account_id} (equity + margin snapshot from traders)
- price:realtime:{SYMBOL} (low-latency truth, multi-source failover)
- msnap:coinapi_wsds:{SYMBOL} (microstructure scores: spoof/fast_move/snapback/churn/imbalance)

URC emits:
- INCREASE_LONG / INCREASE_SHORT with:
  - action_category="RECOVERY"
  - recovery_intent=true
  - sizing fields (margin_usd/notional_usd/leverage/position_size_pct)
"""

from __future__ import annotations

import json
import logging
import os
import time
import bisect
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _to_str(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="ignore")
    return str(v)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        return float(v)
    except Exception:
        return float(default)


def _decode_hash(h: Dict[Any, Any]) -> Dict[str, Any]:
    if not h:
        return {}
    out: Dict[str, Any] = {}
    for k, v in h.items():
        out[_to_str(k)] = _to_str(v) if isinstance(v, (bytes, bytearray)) else v
    return out


def _pos_exists(pos: Optional[Dict[str, Any]]) -> bool:
    if not pos or not isinstance(pos, dict):
        return False
    try:
        if not bool(pos.get("has_position", True)):
            return False
    except Exception:
        pass
    try:
        return abs(float(pos.get("size", 0) or 0)) > 1e-12
    except Exception:
        return False


def _pos_notional_usd(pos: Optional[Dict[str, Any]]) -> float:
    if not pos:
        return 0.0
    try:
        n = _to_float(pos.get("notional", 0) or pos.get("size_usd", 0) or 0.0, 0.0)
        if n:
            return abs(float(n))
    except Exception:
        pass
    try:
        sz = abs(_to_float(pos.get("size", 0) or 0.0, 0.0))
        px = _to_float(pos.get("mark_price") or pos.get("current_price") or pos.get("entry_price") or 0.0, 0.0)
        if sz > 0 and px > 0:
            return float(sz * px)
    except Exception:
        pass
    return 0.0


def _pos_roe_pct(pos: Optional[Dict[str, Any]]) -> float:
    """Prefer trader-published ROI/ROE pct; fallback to pnl/margin if present."""
    if not pos:
        return 0.0
    try:
        rp = pos.get("roi_pct", None)
        if rp is not None:
            return float(rp)
    except Exception:
        pass
    try:
        upnl = _to_float(pos.get("unrealized_pnl", None), default=None)  # type: ignore[arg-type]
        margin = _to_float(pos.get("margin_used", None), default=None)  # type: ignore[arg-type]
        if upnl is not None and margin is not None and float(margin) > 0:
            return (float(upnl) / float(margin)) * 100.0
    except Exception:
        pass
    return _to_float(pos.get("pnl_pct", 0.0) or 0.0, 0.0)


@dataclass
class URCDecision:
    state: str  # NORMAL|PROTECT|RECOVER|EMERGENCY
    allow_recover: bool
    recovery_side: Optional[str] = None  # LONG/SHORT
    hedge_side: Optional[str] = None  # LONG/SHORT
    add_notional_usd: float = 0.0
    add_margin_usd: float = 0.0
    leverage: float = 0.0
    reversal_score: float = 0.0
    reversal_rank: float = 0.0
    sev: float = 0.0
    manip: float = 0.0
    min_hedge_ratio: float = 0.0
    hedge_ratio: float = 0.0
    main_notional_usd: float = 0.0
    hedge_notional_usd: float = 0.0
    reason: str = ""


class UnderwaterRecoveryController:
    """
    URC controller object. Keeps lightweight rolling history for dynamic (regime-relative)
    reversal confirmation using realtime prices.
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        maxlen = int(os.getenv("URC_PRICE_HISTORY_MAXLEN", "900") or 900)
        self._price_hist: Dict[str, Deque[Tuple[int, float]]] = defaultdict(lambda: deque(maxlen=maxlen))

        self._rev_hist: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=int(os.getenv("URC_REV_HISTORY_MAXLEN", "240") or 240)))
        self._last_emit_ts: Dict[str, float] = {}

    # ---------------------------------------------------------------------
    # Inputs
    # ---------------------------------------------------------------------
    def _read_price_realtime(self, symbol: str) -> Tuple[float, int, str]:
        """Return (price, ts_ms, source) from price:realtime:{SYMBOL}."""
        if not self.redis:
            return 0.0, 0, ""
        try:
            raw = self.redis.get(f"price:realtime:{symbol}")
            if not raw:
                return 0.0, 0, ""
            raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                return 0.0, 0, ""
            px = _to_float(data.get("price", 0.0) or 0.0, 0.0)
            ts_ms = int(_to_float(data.get("ts_ms", 0) or data.get("timestamp_ms", 0) or 0, 0.0))
            src = str(data.get("source") or "")
            return float(px), int(ts_ms), src
        except Exception:
            return 0.0, 0, ""

    def _update_price_history(self, symbol: str) -> Dict[str, float]:
        """
        Update internal price history for a symbol and compute short-horizon return features.
        Returns dict with ret_15s, ret_60s, accel_15s, vol_60s (all in pct units).
        """
        now_ms = int(time.time() * 1000)
        px, ts_ms, _src = self._read_price_realtime(symbol)
        if px <= 0:
            return {"ret_15s": 0.0, "ret_60s": 0.0, "accel_15s": 0.0, "vol_60s": 0.0}
        if ts_ms <= 0:
            ts_ms = now_ms

        hist = self._price_hist[symbol]
        # De-dup by timestamp
        if not hist or hist[-1][0] != ts_ms:
            hist.append((ts_ms, float(px)))

        def _price_at(age_ms: int) -> Optional[float]:
            target = ts_ms - age_ms
            # Find the last entry <= target (linear scan from tail; history is small)
            for t, p in reversed(hist):
                if t <= target:
                    return p
            return None

        p15 = _price_at(15_000)
        p60 = _price_at(60_000)

        ret_15s = ((px - p15) / p15 * 100.0) if (p15 and p15 > 0) else 0.0
        ret_60s = ((px - p60) / p60 * 100.0) if (p60 and p60 > 0) else 0.0
        # Acceleration proxy: short-horizon return vs quarter of 60s return.
        accel_15s = float(ret_15s) - (float(ret_60s) / 4.0)

        # Volatility proxy: stddev of 5s returns over last ~60s
        rets: List[float] = []
        cutoff = ts_ms - 60_000
        prev_t, prev_p = None, None
        for t, p in hist:
            if t < cutoff:
                continue
            if prev_t is not None and prev_p is not None and prev_p > 0:
                # per-step return in %
                rets.append(((p - prev_p) / prev_p) * 100.0)
            prev_t, prev_p = t, p
        if len(rets) >= 5:
            m = sum(rets) / len(rets)
            var = sum((x - m) ** 2 for x in rets) / max(1, (len(rets) - 1))
            vol_60s = var ** 0.5
        else:
            vol_60s = 0.0

        return {
            "ret_15s": float(ret_15s),
            "ret_60s": float(ret_60s),
            "accel_15s": float(accel_15s),
            "vol_60s": float(vol_60s),
        }

    # ---------------------------------------------------------------------
    # Decision logic
    # ---------------------------------------------------------------------
    def _percentile_rank(self, xs: Iterable[float], x: float) -> float:
        arr = sorted(float(v) for v in xs)
        if not arr:
            return 0.0
        return float(bisect.bisect_right(arr, float(x))) / float(len(arr))

    def _compute_sev(
        self,
        *,
        equity: float,
        used_margin: float,
        main_buffer_pct: float,
        micro_danger: float,
        both_losing: bool,
    ) -> float:
        """
        Continuous severity score in [0,1].
        This is NOT a static threshold gate; it's used for smooth sizing + state selection.
        """
        util = 0.0
        if equity and equity > 0:
            util = max(0.0, min(1.0, float(used_margin) / float(equity)))

        # Liquidation closeness: smaller buffer => higher danger (smooth)
        b = max(0.0, float(main_buffer_pct))
        liq_close = 1.0 / (1.0 + (b / 5.0))  # 5% buffer ≈ 0.5
        liq_close = max(0.0, min(1.0, float(liq_close)))

        cage = 1.0 if both_losing else 0.0

        # Probabilistic OR (continuous)
        sev = 1.0 - ((1.0 - util) * (1.0 - micro_danger) * (1.0 - liq_close) * (1.0 - 0.7 * cage))
        return max(0.0, min(1.0, float(sev)))

    def _decide_for_symbol(
        self,
        *,
        account_id: str,
        symbol: str,
        long_pos: Dict[str, Any],
        short_pos: Dict[str, Any],
        equity_snapshot: Dict[str, Any],
        msnap: Dict[str, Any],
        hedge_active: Optional[Dict[str, Any]] = None,
    ) -> URCDecision:
        # Identify main/hedge sides
        main_side = None
        hedge_side = None
        try:
            if hedge_active and isinstance(hedge_active, dict):
                ms = str(hedge_active.get("main_position_side") or hedge_active.get("main_side") or "").upper()
                hs = str(hedge_active.get("hedge_position_side") or hedge_active.get("hedge_side") or "").upper()
                if ms in ("LONG", "SHORT") and hs in ("LONG", "SHORT"):
                    main_side, hedge_side = ms, hs
        except Exception:
            main_side, hedge_side = None, None

        long_not = _pos_notional_usd(long_pos)
        short_not = _pos_notional_usd(short_pos)
        if not main_side:
            # Fallback: main leg is larger notional (stable default)
            if long_not >= short_not:
                main_side, hedge_side = "LONG", "SHORT"
            else:
                main_side, hedge_side = "SHORT", "LONG"

        main_pos = long_pos if main_side == "LONG" else short_pos
        hedge_pos = long_pos if hedge_side == "LONG" else short_pos

        main_roe = _pos_roe_pct(main_pos)
        hedge_roe = _pos_roe_pct(hedge_pos)

        # Underwater condition (dominant leg underwater)
        if main_roe >= 0.0:
            return URCDecision(
                state="NORMAL",
                allow_recover=False,
                recovery_side=main_side,
                hedge_side=hedge_side,
                reason="main_not_underwater",
            )

        # Microstructure quality + danger
        spoof = _to_float(msnap.get("spoof_score", 0.0) or 0.0, 0.0)
        snapback = _to_float(msnap.get("snapback_score", 0.0) or 0.0, 0.0)
        churn = _to_float(msnap.get("churn_score", 0.0) or 0.0, 0.0)
        fast_move = _to_float(msnap.get("fast_move_score", 0.0) or 0.0, 0.0)
        fast_move = max(fast_move, _to_float(msnap.get("fast_move_max_1m", 0.0) or 0.0, 0.0))
        imbalance_5 = _to_float(msnap.get("imbalance_5", 0.0) or 0.0, 0.0)

        manip = max(0.0, min(1.0, max(spoof, snapback)))
        micro_danger = max(0.0, min(1.0, max(manip, churn, fast_move)))

        # Reversal confirmation using realtime return features (trainer-maintained history)
        px_feats = self._update_price_history(symbol)
        ret_15s = float(px_feats.get("ret_15s", 0.0) or 0.0)
        accel_15s = float(px_feats.get("accel_15s", 0.0) or 0.0)

        dir_sign = 1.0 if main_side == "LONG" else -1.0
        signed_ret = dir_sign * ret_15s
        signed_accel = dir_sign * accel_15s
        signed_imb = dir_sign * imbalance_5

        scoped = f"{account_id}:{symbol}"
        # Combine relative ranks into a reversal score 0..1
        # Use history to avoid hard thresholds; bootstrap to neutral if no history.
        rev_hist = self._rev_hist[scoped]
        # Store components into temporary rank via history when available
        r_ret = self._percentile_rank(rev_hist, signed_ret) if len(rev_hist) >= 20 else max(0.0, min(1.0, 0.5 + 0.5 * (signed_ret / (abs(signed_ret) + 0.2))))
        r_acc = self._percentile_rank(rev_hist, signed_accel) if len(rev_hist) >= 20 else max(0.0, min(1.0, 0.5 + 0.5 * (signed_accel / (abs(signed_accel) + 0.2))))
        r_imb = max(0.0, min(1.0, 0.5 + 0.5 * float(signed_imb)))

        reversal_score = (0.45 * r_ret) + (0.25 * r_acc) + (0.20 * r_imb) - (0.25 * manip) - (0.10 * churn)
        reversal_score = max(0.0, min(1.0, float(reversal_score)))
        rev_hist.append(float(reversal_score))

        reversal_rank = self._percentile_rank(rev_hist, reversal_score) if len(rev_hist) >= 30 else float(reversal_score)

        # Portfolio/equity snapshot
        equity = _to_float(equity_snapshot.get("equity_usd", 0.0) or 0.0, 0.0)
        used_margin = _to_float(equity_snapshot.get("used_margin_usd", 0.0) or 0.0, 0.0)
        avail_margin = _to_float(equity_snapshot.get("available_margin_usd", 0.0) or 0.0, 0.0)

        main_buffer = _to_float(main_pos.get("buffer_percent", 0.0) or 0.0, 0.0)
        both_losing = bool(main_roe < 0.0 and hedge_roe < 0.0)

        sev = self._compute_sev(
            equity=equity,
            used_margin=used_margin,
            main_buffer_pct=main_buffer,
            micro_danger=micro_danger,
            both_losing=both_losing,
        )

        # State selection (dynamic comparisons; not brittle absolute thresholds)
        # - If danger dominates reversal confidence => PROTECT
        # - If reversal confidence dominates danger and manipulation is not dominating => RECOVER
        allow_recover = bool(reversal_rank > sev and manip < reversal_rank)
        state = "RECOVER" if allow_recover else "PROTECT"

        # Hard safety: if free margin is zero, recovery adds will almost certainly fail (-2019)
        # and can create spam/latency. In that case, we must first free margin (gross reduction).
        if allow_recover and float(avail_margin) <= 0.0:
            allow_recover = False
            state = "PROTECT"

        # Sizing: dynamic add fraction of main notional based on (reversal_rank - sev)
        main_not = _pos_notional_usd(main_pos)
        hedge_not = _pos_notional_usd(hedge_pos)
        # Leverage selection for URC signals:
        # - Do NOT rely on a default 10x fallback (this causes tier drift, e.g. SOL should be 40-66x).
        # - Prefer current leg leverage if present, but clamp to config tier bounds for the symbol.
        try:
            from config import SYMBOL_LEVERAGE_CONFIG
            sym_cfg = (SYMBOL_LEVERAGE_CONFIG or {}).get(symbol, {}) or {}
            tier_min = float(sym_cfg.get("min_leverage", 1.0) or 1.0)
            tier_max = float(sym_cfg.get("max_leverage", 25.0) or 25.0)
        except Exception:
            tier_min, tier_max = 1.0, 25.0
        tier_min = max(1.0, float(tier_min))
        tier_max = max(tier_min, float(tier_max))

        lev_raw = _to_float(main_pos.get("leverage", 0.0) or 0.0, 0.0)
        if lev_raw <= 0.0:
            # If missing, pick a sensible mid-tier default rather than 10x.
            lev_raw = max(tier_min, min(tier_max, (tier_min + tier_max) * 0.5))
        leverage = max(tier_min, min(tier_max, float(lev_raw)))

        # Cap via env (safe defaults); still continuous and scaled by signal strength.
        try:
            max_add_pct = float(os.getenv("URC_RECOVER_MAX_ADD_PCT_OF_MAIN", "5.0") or 5.0)
        except Exception:
            max_add_pct = 5.0
        max_add_pct = max(0.0, min(25.0, float(max_add_pct)))

        strength = max(0.0, float(reversal_rank) - float(sev))
        # Start with low margin on weak reversals; ramp up smoothly as reversal strengthens.
        # Continuous scaling only (no hard thresholds).
        ramp = 0.25 + 0.75 * float(reversal_rank)
        add_pct = float(max_add_pct) * (strength ** 2.0) * max(0.0, min(1.0, ramp))
        if both_losing:
            add_pct *= 0.5  # extra caution when both legs are red

        add_notional = max(0.0, float(main_not) * (float(add_pct) / 100.0))
        add_margin = float(add_notional / leverage) if leverage > 0 else 0.0

        # Hedge coverage constraint: do not reduce hedge ratio below a dynamic floor.
        # min_ratio rises with severity; falls with reversal confidence.
        min_ratio = max(0.15, min(0.90, 0.25 + 0.50 * float(sev) + 0.15 * (1.0 - float(reversal_rank))))
        new_ratio = float(hedge_not) / max(1e-9, float(main_not + add_notional))
        if new_ratio < min_ratio:
            allow_recover = False
            state = "PROTECT"

        # Margin availability sanity (best-effort; portfolio caps also apply downstream)
        if allow_recover and avail_margin > 0 and add_margin > (0.35 * avail_margin):
            # Scale down instead of blocking outright
            scale = max(0.0, min(1.0, (0.35 * avail_margin) / max(1e-9, add_margin)))
            add_margin *= scale
            add_notional = add_margin * leverage

        reason = (
            f"urc:{state} main={main_side} main_roe={main_roe:.2f}% hedge_roe={hedge_roe:.2f}% "
            f"rev_rank={reversal_rank:.2f} sev={sev:.2f} manip={manip:.2f} "
            f"ret15={ret_15s:.3f}% accel15={accel_15s:.3f}% imb5={imbalance_5:.2f} "
            f"add_pct={add_pct:.2f}% min_ratio={min_ratio:.2f} new_ratio={new_ratio:.2f} "
            f"avail_margin={avail_margin:.2f}"
        )

        return URCDecision(
            state=state,
            allow_recover=allow_recover,
            recovery_side=main_side,
            hedge_side=hedge_side,
            add_notional_usd=float(add_notional),
            add_margin_usd=float(add_margin),
            leverage=float(leverage),
            reversal_score=float(reversal_score),
            reversal_rank=float(reversal_rank),
            sev=float(sev),
            manip=float(manip),
            min_hedge_ratio=float(min_ratio),
            hedge_ratio=float(float(hedge_not) / max(1e-9, float(main_not))),
            main_notional_usd=float(main_not),
            hedge_notional_usd=float(hedge_not),
            reason=reason,
        )

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def generate_signals(self, accounts: Iterable[str] = ("primary", "asjad")) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []

        mode = str(os.getenv("URC_MODE", "RECOVER") or "RECOVER").strip().upper()
        enabled = str(os.getenv("URC_ENABLED", "true") or "true").lower() in ("1", "true", "yes")
        if (not enabled) or mode in {"OFF", "DISABLED", "FALSE", "0"}:
            return signals
        observe_only = mode in {"OBSERVE", "DRY", "DRY_RUN", "LOG"}

        if not self.redis:
            return signals

        # Cooldown
        try:
            cooldown_sec = int(float(os.getenv("URC_RECOVER_COOLDOWN_SECONDS", "120") or 120))
        except Exception:
            cooldown_sec = 120
        cooldown_sec = max(15, min(1800, int(cooldown_sec)))

        # Exchange min notional guard (do NOT bump tiny adds)
        try:
            from config import MIN_NOTIONAL_USD, BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL
            min_notional_default = float(MIN_NOTIONAL_USD or 0.0)
            per_sym_min = dict(BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {})
        except Exception:
            min_notional_default = 0.0
            per_sym_min = {}

        now = time.time()

        for account_id in list(accounts):
            # Equity snapshot
            eq = {}
            try:
                raw = self.redis.get(f"portfolio:equity:{account_id}")
                raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                eq = json.loads(raw) if raw else {}
                if not isinstance(eq, dict):
                    eq = {}
            except Exception:
                eq = {}

            # Positions (canonical)
            try:
                raw_map = self.redis.hgetall(f"portfolio:positions:{account_id}") or {}
            except Exception:
                raw_map = {}

            # Build symbol->(LONG,SHORT)
            sym_legs: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
            for k, v in (raw_map or {}).items():
                try:
                    ks = _to_str(k)
                    if ":" not in ks:
                        continue
                    sym, side = ks.rsplit(":", 1)
                    side = str(side).upper()
                    if side not in ("LONG", "SHORT"):
                        continue
                    raw = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                    pos = json.loads(raw) if raw else {}
                    if isinstance(pos, dict) and _pos_exists(pos):
                        sym_legs[str(sym).upper()][side] = pos
                except Exception:
                    continue

            for symbol, legs in (sym_legs or {}).items():
                long_pos = legs.get("LONG")
                short_pos = legs.get("SHORT")
                
                # Stage 1.2 (Jan 2026): Unhedged Underwater Protection
                # If only ONE leg exists and it's underwater, consider opening a hedge.
                # This prevents naked losers from staying exposed when model predicts adverse continuation.
                has_long = _pos_exists(long_pos)
                has_short = _pos_exists(short_pos)
                is_one_legged = (has_long and not has_short) or (has_short and not has_long)
                
                if is_one_legged:
                    try:
                        try:
                            import config as _cfg
                            cfg_default = bool(getattr(_cfg, "URC_UNHEDGED_PROTECT_ENABLED", False))
                        except Exception:
                            cfg_default = False
                        env_default = "true" if cfg_default else "false"
                        unhedged_protect_enabled = str(os.getenv("URC_UNHEDGED_PROTECT_ENABLED", env_default) or env_default).lower() in ("1", "true", "yes")
                    except Exception:
                        unhedged_protect_enabled = False
                    
                    if unhedged_protect_enabled:
                        # Process unhedged underwater position
                        single_pos = long_pos if has_long else short_pos
                        single_side = "LONG" if has_long else "SHORT"
                        single_roe = _pos_roe_pct(single_pos)
                        single_margin = float(single_pos.get("margin_used", 0) or single_pos.get("initialMargin", 0) or 0)
                        
                        # ── URC PROTECT: Only trigger when ALL signals align toward catastrophic loss ──
                        # Requirement: position underwater + trainer prediction adverse + CoinAPI depth adverse + orderbook adverse
                        # This is a last-resort liquidation prevention, NOT a normal hedge tool.
                        
                        # Must be meaningfully underwater (at least -10% ROE) and not dust
                        if single_roe < -10.0 and single_margin >= 25.0:
                            import json as _json_urc
                            
                            # ── Signal 1: Trainer prediction (model bias) ──
                            model_bias = 0.0
                            model_conf = 0.0
                            trainer_adverse = False
                            
                            try:
                                pred = {}
                                for tf in ["5m", "15m", "1h"]:
                                    pred_key = f"predictions:{symbol}:{tf}"
                                    pred_raw = self.redis.hgetall(pred_key) or {}
                                    pred = _decode_hash(pred_raw)
                                    if pred:
                                        break
                                
                                if not pred:
                                    for aid in ["primary", "asjad"]:
                                        sig_key = f"signals:trading:last:{symbol}:{aid}"
                                        sig_raw = self.redis.hgetall(sig_key) or {}
                                        if sig_raw:
                                            sig = _decode_hash(sig_raw)
                                            action = str(sig.get("action", "") or sig.get("action_name", "")).upper()
                                            conf = float(sig.get("confidence", 0) or sig.get("model_confidence", 0) or 0)
                                            if "LONG" in action:
                                                model_bias = 0.5
                                                model_conf = conf
                                            elif "SHORT" in action:
                                                model_bias = -0.5
                                                model_conf = conf
                                            if model_conf > 0:
                                                break
                                else:
                                    model_bias = float(pred.get("bias", 0) or pred.get("direction", 0) or 0)
                                    model_conf = float(pred.get("confidence", 0) or pred.get("conf", 0) or 0)
                                
                                if single_side == "LONG" and model_bias < -0.3 and model_conf >= 0.75:
                                    trainer_adverse = True
                                elif single_side == "SHORT" and model_bias > 0.3 and model_conf >= 0.75:
                                    trainer_adverse = True
                            except Exception as pred_err:
                                logger.debug(f"[URC_PROTECT] {account_id}:{symbol} prediction fetch: {pred_err}")
                            
                            # ── Signal 2: CoinAPI microstructure depth ──
                            depth_adverse = False
                            depth_score = 0.0
                            try:
                                msnap_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}") or {}
                                msnap = _decode_hash(msnap_raw)
                                if msnap:
                                    imb5 = float(msnap.get("imbalance_5", 0) or 0)
                                    imb20 = float(msnap.get("imbalance_20", 0) or 0)
                                    fast_move = float(msnap.get("fast_move_score", 0) or 0)
                                    spoof = float(msnap.get("spoof_score", 0) or 0)
                                    
                                    # For LONG: negative imbalance = sell pressure (adverse)
                                    # For SHORT: positive imbalance = buy pressure (adverse)
                                    if single_side == "LONG":
                                        if imb5 < -0.3 or imb20 < -0.3:
                                            depth_score += 0.4
                                        if fast_move > 0.4:
                                            depth_score += 0.3
                                        if spoof > 0.3:
                                            depth_score += 0.3
                                    elif single_side == "SHORT":
                                        if imb5 > 0.3 or imb20 > 0.3:
                                            depth_score += 0.4
                                        if fast_move > 0.4:
                                            depth_score += 0.3
                                        if spoof > 0.3:
                                            depth_score += 0.3
                                    
                                    depth_adverse = depth_score >= 0.4
                            except Exception as depth_err:
                                logger.debug(f"[URC_PROTECT] {account_id}:{symbol} depth fetch: {depth_err}")
                            
                            # ── Signal 3: Orderbook imbalance ──
                            ob_adverse = False
                            ob_imb = 0.0
                            try:
                                ob_raw = self.redis.get(f"orderbook:top:{symbol}") or self.redis.get(f"orderbook:{symbol}")
                                if ob_raw:
                                    ob_raw = ob_raw.decode("utf-8") if isinstance(ob_raw, (bytes, bytearray)) else ob_raw
                                    ob = _json_urc.loads(ob_raw) if isinstance(ob_raw, str) else {}
                                    ob_imb = float(ob.get("imbalance", 0) or 0)
                                    # LONG adverse: ask-heavy (negative imbalance)
                                    # SHORT adverse: bid-heavy (positive imbalance)
                                    if single_side == "LONG" and ob_imb < -0.25:
                                        ob_adverse = True
                                    elif single_side == "SHORT" and ob_imb > 0.25:
                                        ob_adverse = True
                            except Exception as ob_err:
                                logger.debug(f"[URC_PROTECT] {account_id}:{symbol} orderbook fetch: {ob_err}")
                            
                            # ── DECISION: ALL THREE must align for catastrophic risk ──
                            # Count how many signals confirm adverse continuation
                            adverse_count = sum([trainer_adverse, depth_adverse, ob_adverse])
                            
                            logger.info(
                                f"[URC_PROTECT_CHECK] {account_id}:{symbol} {single_side} roe={single_roe:.1f}% | "
                                f"trainer={'✓' if trainer_adverse else '✗'}(bias={model_bias:.2f},conf={model_conf:.2f}) "
                                f"depth={'✓' if depth_adverse else '✗'}(score={depth_score:.2f}) "
                                f"ob={'✓' if ob_adverse else '✗'}(imb={ob_imb:.2f}) | "
                                f"aligned={adverse_count}/3"
                            )
                            
                            # STRICT: Need ALL 3 aligned, OR 2/3 aligned + already deeply underwater (-30%+ ROE)
                            should_hedge = False
                            if adverse_count >= 3:
                                should_hedge = True
                            elif adverse_count >= 2 and single_roe < -30.0:
                                should_hedge = True
                                logger.warning(
                                    f"[URC_PROTECT] {account_id}:{symbol} 2/3 signals + deep underwater ({single_roe:.1f}%) → hedge"
                                )
                            
                            if should_hedge:
                                hedge_side = "SHORT" if single_side == "LONG" else "LONG"
                                
                                # Cooldown check
                                cooldown_key = f"urc:unhedged_protect_cooldown:{account_id}:{symbol}"
                                last_protect = None
                                try:
                                    last_protect_raw = self.redis.get(cooldown_key)
                                    if last_protect_raw:
                                        last_protect = float(last_protect_raw.decode("utf-8", errors="ignore") if isinstance(last_protect_raw, (bytes, bytearray)) else last_protect_raw)
                                except Exception:
                                    last_protect = None
                                
                                cooldown_sec = int(os.getenv("URC_UNHEDGED_PROTECT_COOLDOWN_SECONDS", "600") or 600)
                                if last_protect and (time.time() - last_protect) < cooldown_sec:
                                    logger.debug(f"[URC_UNHEDGED_PROTECT] {account_id}:{symbol} cooldown active ({cooldown_sec - (time.time() - last_protect):.0f}s remaining)")
                                else:
                                    # Size the hedge: PROPORTIONAL to drawdown severity
                                    # -3% ROE → 15% coverage, -5% → 25%, -8% → 35%, -15%+ → 50% max
                                    # This prevents 1:1 hedge ratios that lock in losses on both sides
                                    drawdown_severity = min(abs(single_roe) / 30.0, 0.50)  # 0-50% scale
                                    drawdown_severity = max(drawdown_severity, 0.10)  # minimum 10% coverage
                                    hedge_margin = min(single_margin * drawdown_severity, 100.0)  # Max $100
                                    hedge_margin = max(hedge_margin, 5.0)  # Min $5 to be meaningful
                                    
                                    # Get leverage from config
                                    try:
                                        from config import SYMBOL_LEVERAGE_CONFIG
                                        sym_cfg = SYMBOL_LEVERAGE_CONFIG.get(symbol, SYMBOL_LEVERAGE_CONFIG.get("default", {}))
                                        lev = int(sym_cfg.get("max_leverage", 20))
                                    except Exception:
                                        lev = 20
                                    
                                    hedge_notional = hedge_margin * lev
                                    
                                    # ── COVERAGE CAP: check existing hedge from other sources ──
                                    MAX_URC_COVERAGE = 0.35  # Max 35% total coverage
                                    try:
                                        main_notional = single_margin * lev
                                        # Check if any hedge leg already exists
                                        for pos_key_prefix in [f"positions:live:{symbol}", f"positions:live:{account_id}:{symbol}"]:
                                            opp_data = self.redis.hgetall(pos_key_prefix) if self.redis.type(pos_key_prefix).decode() == 'hash' else {}
                                            if opp_data:
                                                opp_data = {(kk.decode() if isinstance(kk, bytes) else kk): (vv.decode() if isinstance(vv, bytes) else vv) for kk, vv in opp_data.items()}
                                                opp_side_key = hedge_side.lower()
                                                opp_raw = opp_data.get(opp_side_key, '{}')
                                                import json as _json_urc
                                                opp_pos = _json_urc.loads(opp_raw) if opp_raw else {}
                                                existing_opp_notional = abs(float(opp_pos.get('notional', 0) or 0))
                                                if existing_opp_notional > 0 and main_notional > 0:
                                                    current_cov = existing_opp_notional / main_notional
                                                    if current_cov >= MAX_URC_COVERAGE:
                                                        logger.info(
                                                            f"[URC_UNHEDGED_PROTECT] {account_id}:{symbol} SKIP: "
                                                            f"existing hedge coverage {current_cov:.0%} >= {MAX_URC_COVERAGE:.0%}"
                                                        )
                                                        break  # Don't add more hedge
                                                    proposed_cov = (existing_opp_notional + hedge_notional) / main_notional
                                                    if proposed_cov > MAX_URC_COVERAGE:
                                                        allowed = (MAX_URC_COVERAGE * main_notional) - existing_opp_notional
                                                        if allowed <= 0:
                                                            break
                                                        hedge_notional = allowed
                                                        hedge_margin = hedge_notional / lev if lev > 0 else hedge_notional
                                                        logger.info(
                                                            f"[URC_UNHEDGED_PROTECT] {account_id}:{symbol} SIZED_DOWN: "
                                                            f"coverage {current_cov:.0%}→{MAX_URC_COVERAGE:.0%} margin=${hedge_margin:.2f}"
                                                        )
                                                break
                                    except Exception as cov_err:
                                        logger.debug(f"[URC_UNHEDGED_PROTECT] {account_id}:{symbol} coverage check: {cov_err}")
                                    
                                    if hedge_margin < 5.0:
                                        logger.debug(f"[URC_UNHEDGED_PROTECT] {account_id}:{symbol} hedge margin too small after cap: ${hedge_margin:.2f}")
                                    else:
                                        logger.warning(
                                            f"[URC_PROTECT_TRIGGERED] {account_id}:{symbol} {single_side} underwater ({single_roe:.2f}%) "
                                            f"ALL signals adverse: trainer(bias={model_bias:.2f},conf={model_conf:.2f}) "
                                            f"depth(score={depth_score:.2f}) ob(imb={ob_imb:.2f}) "
                                            f"→ opening {hedge_side} hedge margin=${hedge_margin:.2f} notional=${hedge_notional:.2f} @ {lev}x"
                                        )
                                    
                                        # Calculate position_size_pct (margin as % of portfolio)
                                        portfolio_balance = 3000.0  # Fallback
                                        try:
                                            bal_key = f"portfolio:balance:{account_id}"
                                            bal_raw = self.redis.get(bal_key)
                                            if bal_raw:
                                                portfolio_balance = float(bal_raw.decode("utf-8") if isinstance(bal_raw, (bytes, bytearray)) else bal_raw) or 3000.0
                                        except Exception:
                                            pass
                                        position_size_pct = (hedge_margin / portfolio_balance) * 100 if portfolio_balance > 0 else 2.0
                                    
                                        # Emit OPEN_HEDGE signal
                                        signal_payload = {
                                            "timestamp": time.time(),
                                            "ts_ms": int(time.time() * 1000),
                                            "symbol": symbol,
                                            "account_id": account_id,
                                            "timeframe": "multi",  # Required by contract validation
                                            "action": f"OPEN_HEDGE_{hedge_side}",
                                            "action_name": f"OPEN_HEDGE_{hedge_side}",
                                            "action_category": "HEDGE",
                                            "action_type": "open",
                                            "hedge_intent": True,
                                            "hedge_against_side": single_side,
                                            "margin_usd": hedge_margin,
                                            "notional_usd": hedge_notional,
                                            "leverage": lev,
                                            "position_size_pct": position_size_pct,  # Required by contract
                                            "recommended_position_pct": position_size_pct,
                                            "confidence": model_conf,
                                            "model_confidence": model_conf,
                                            "source": "urc_unhedged_protect",
                                            "reasoning": (
                                                f"CATASTROPHIC_RISK: {single_side} roe={single_roe:.1f}% "
                                                f"trainer+depth+ob all adverse ({adverse_count}/3)"
                                            ),
                                            "bypass_gating": True,
                                            "_override_conf_gate_skipped_for_hedge": True,
                                        }
                                    
                                        signals.append(signal_payload)
                                    
                                        # Set cooldown
                                        try:
                                            self.redis.setex(cooldown_key, cooldown_sec, str(time.time()))
                                        except Exception:
                                            pass
                    
                    continue  # Skip normal hedged-only processing for one-legged positions
                
                # Original Stage 1: hedged-only processing
                if not (_pos_exists(long_pos) and _pos_exists(short_pos)):
                    continue  # hedged-only in Stage 1

                # msnap (microstructure)
                try:
                    msnap_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}") or {}
                    msnap = _decode_hash(msnap_raw)
                except Exception:
                    msnap = {}
                if not msnap:
                    continue  # fail-closed for recovery adds

                # Hedge active marker (best-effort)
                hedge_active = None
                try:
                    ha_raw = self.redis.get(f"hedge:active:{symbol}:{account_id}")
                    ha_raw = ha_raw.decode("utf-8", errors="ignore") if isinstance(ha_raw, (bytes, bytearray)) else ha_raw
                    hedge_active = json.loads(ha_raw) if ha_raw else None
                    if not isinstance(hedge_active, dict):
                        hedge_active = None
                except Exception:
                    hedge_active = None

                decision = self._decide_for_symbol(
                    account_id=account_id,
                    symbol=symbol,
                    long_pos=long_pos,  # type: ignore[arg-type]
                    short_pos=short_pos,  # type: ignore[arg-type]
                    equity_snapshot=eq or {},
                    msnap=msnap,
                    hedge_active=hedge_active,
                )

                # Persist state for observability (TTL)
                try:
                    state_payload = {
                        "account_id": account_id,
                        "symbol": symbol,
                        "state": decision.state,
                        "allow_recover": bool(decision.allow_recover),
                        "recovery_side": decision.recovery_side,
                        "min_ratio": round(float(getattr(decision, "min_hedge_ratio", 0.0) or 0.0), 6),
                        "hedge_ratio": round(float(getattr(decision, "hedge_ratio", 0.0) or 0.0), 6),
                        "add_notional_usd": round(float(decision.add_notional_usd), 6),
                        "add_margin_usd": round(float(decision.add_margin_usd), 6),
                        "leverage": float(decision.leverage),
                        "reversal_score": round(float(decision.reversal_score), 4),
                        "reversal_rank": round(float(decision.reversal_rank), 4),
                        "sev": round(float(decision.sev), 4),
                        "manip": round(float(decision.manip), 4),
                        "ts": time.time(),
                        "reason": str(decision.reason)[:500],
                    }
                    self.redis.setex(
                        f"urc:state:{account_id}:{symbol}",
                        int(os.getenv("URC_STATE_TTL_SECONDS", "600") or 600),
                        json.dumps(state_payload, separators=(",", ":")),
                    )
                except Exception:
                    pass

                # Stage 1.1 (Jan 2026): PROTECT-mode hedge scaling
                # If main is underwater and hedge ratio is too low, allow an ADD_HEDGE_* to increase
                # coverage while still relying on downstream hedge governors.
                try:
                    protect_scale_enabled = str(os.getenv("URC_PROTECT_SCALE_ENABLED", "true") or "true").lower() in ("1", "true", "yes")
                except Exception:
                    protect_scale_enabled = True

                if (not decision.allow_recover) and protect_scale_enabled:
                    try:
                        main_roe = _pos_roe_pct(long_pos if decision.recovery_side == "LONG" else short_pos)
                    except Exception:
                        main_roe = 0.0
                    if main_roe < 0.0 and float(decision.hedge_ratio) < float(decision.min_hedge_ratio):
                        # If the underlying position is "dust", do not spam micro hedge adds.
                        # Dust legs are handled by trader-side dust cleanup / slot exemption.
                        # Dust check (Jan 2026): use margin used, not notional.
                        try:
                            import config as cfg
                            dust_min_margin = float(getattr(cfg, "MICRO_POSITION_MIN_LEG_MARGIN_USD", 25.0) or 25.0)
                        except Exception:
                            dust_min_margin = 25.0
                        dust_min_margin = max(0.0, float(dust_min_margin))
                        try:
                            main_pos0 = (long_pos if decision.recovery_side == "LONG" else short_pos) or {}
                            mu0 = _to_float(
                                main_pos0.get("margin_used", None)
                                or main_pos0.get("initialMargin", None)
                                or main_pos0.get("positionInitialMargin", None)
                                or 0.0,
                                0.0,
                            )
                            if float(mu0) > 0.0 and float(mu0) < float(dust_min_margin):
                                # Too small to justify ratio targeting; avoid fee-bleed churn.
                                continue
                        except Exception:
                            pass
                        # Cooldown for protect-scale, separate from recovery adds
                        try:
                            protect_cd = int(float(os.getenv("URC_PROTECT_COOLDOWN_SECONDS", "120") or 120))
                        except Exception:
                            protect_cd = 120
                        # IMPORTANT: match trader hourly hedge cap (30/hour) → >=120s between hedge adds per symbol
                        protect_cd = max(120, min(1800, int(protect_cd)))
                        scoped_p = f"{account_id}:{symbol}:protect"
                        lastp = self._last_emit_ts.get(scoped_p, 0.0) or 0.0
                        if (now - lastp) < float(protect_cd):
                            # Still allow other symbols this cycle
                            pass
                        else:
                            # Compute a bounded hedge add notional to move ratio toward min_ratio
                            # IMPORTANT: Avoid micro-churn. When headroom is high and severity is high,
                            # we intentionally aim ABOVE the bare min_ratio to reduce repeated tiny adds.
                            # This stays fully dynamic (depends on equity headroom + sev), not a static floor.
                            base_min_ratio = float(decision.min_hedge_ratio)
                            try:
                                eq_usd = _to_float((eq or {}).get("equity_usd", 0.0) or 0.0, 0.0)
                            except Exception:
                                eq_usd = 0.0
                            try:
                                avail_usd = _to_float((eq or {}).get("available_margin_usd", 0.0) or 0.0, 0.0)
                            except Exception:
                                avail_usd = 0.0
                            headroom = (float(avail_usd) / float(eq_usd)) if (eq_usd > 0 and avail_usd > 0) else 0.0
                            headroom = max(0.0, min(1.0, float(headroom)))
                            sev = float(getattr(decision, "sev", 0.0) or 0.0)
                            sev = max(0.0, min(1.0, float(sev)))

                            # Overshoot grows smoothly with severity and headroom (0 → ~0.25 max).
                            overshoot = (0.03 + 0.22 * headroom) * sev
                            target_ratio = max(0.0, min(0.95, base_min_ratio + float(overshoot)))

                            needed = (target_ratio * float(decision.main_notional_usd)) - float(decision.hedge_notional_usd)
                            if needed > 0.0:
                                try:
                                    # Default higher than legacy: protect-scale is the primary recovery lever in no-loss mode.
                                    max_add_pct = float(os.getenv("URC_PROTECT_MAX_ADD_PCT_OF_MAIN", "25.0") or 25.0)
                                except Exception:
                                    max_add_pct = 25.0
                                max_add_pct = max(0.0, min(50.0, float(max_add_pct)))

                                # Profit-bank assist (best-effort): allow slightly larger hedge adds when we have
                                # realized profit buffer, without breaking no-loss rules.
                                bank_usd = 0.0
                                try:
                                    if self.redis:
                                        pb_raw = self.redis.get(f"profit_bank:state:{account_id}")
                                        pb_raw = pb_raw.decode("utf-8", errors="ignore") if isinstance(pb_raw, (bytes, bytearray)) else pb_raw
                                        pb = json.loads(pb_raw) if pb_raw else {}
                                        if isinstance(pb, dict):
                                            bank_usd = float(pb.get("balance_usd", 0.0) or 0.0)
                                except Exception:
                                    bank_usd = 0.0
                                if bank_usd > 0.0:
                                    # At most +15% of main when bank is healthy (scaled by bank/equity).
                                    try:
                                        eq_usd = _to_float((eq or {}).get("equity_usd", 0.0) or 0.0, 0.0)
                                    except Exception:
                                        eq_usd = 0.0
                                    bank_ratio = (bank_usd / eq_usd) if eq_usd > 0 else 0.0
                                    bonus = 15.0 * max(0.0, min(1.0, bank_ratio * 2.0))  # bank>=50% eq -> full bonus
                                    max_add_pct = min(50.0, float(max_add_pct) + float(bonus))
                                cap_notional = float(decision.main_notional_usd) * (max_add_pct / 100.0)
                                add_notional = max(0.0, min(float(needed), float(cap_notional)))
                                # Basic margin sanity
                                # Hedge-leg leverage for protect-scale: prefer existing hedge leg leverage; clamp to tier.
                                try:
                                    from config import SYMBOL_LEVERAGE_CONFIG
                                    sym_cfg2 = (SYMBOL_LEVERAGE_CONFIG or {}).get(symbol, {}) or {}
                                    tier_min2 = float(sym_cfg2.get("min_leverage", 1.0) or 1.0)
                                    tier_max2 = float(sym_cfg2.get("max_leverage", 25.0) or 25.0)
                                except Exception:
                                    tier_min2, tier_max2 = 1.0, 25.0
                                tier_min2 = max(1.0, float(tier_min2))
                                tier_max2 = max(tier_min2, float(tier_max2))
                                try:
                                    leg = (short_pos if decision.hedge_side == "SHORT" else long_pos) or {}
                                    lev_h_raw = _to_float(leg.get("leverage", 0.0) or 0.0, 0.0)
                                except Exception:
                                    lev_h_raw = 0.0
                                if lev_h_raw <= 0.0:
                                    lev_h_raw = max(tier_min2, min(tier_max2, (tier_min2 + tier_max2) * 0.5))
                                lev_h = max(tier_min2, min(tier_max2, float(lev_h_raw)))
                                add_margin = add_notional / lev_h if lev_h > 0 else 0.0
                                avail_margin = _to_float((eq or {}).get("available_margin_usd", 0.0) or 0.0, 0.0)
                                if avail_margin > 0 and add_margin > (0.35 * avail_margin):
                                    scale = max(0.0, min(1.0, (0.35 * avail_margin) / max(1e-9, add_margin)))
                                    add_margin *= scale
                                    add_notional = add_margin * lev_h

                                # Headroom-aware minimum sizing (dynamic, no static hard floor):
                                # If headroom is high and severity is non-trivial, avoid micro-adds (fee bleed)
                                # by bumping the add to a small fraction of equity scaled by (sev × headroom).
                                try:
                                    eq_usd2 = _to_float((eq or {}).get("equity_usd", 0.0) or 0.0, 0.0)
                                except Exception:
                                    eq_usd2 = 0.0
                                try:
                                    headroom2 = (float(avail_margin) / float(eq_usd2)) if (eq_usd2 > 0 and avail_margin > 0) else 0.0
                                except Exception:
                                    headroom2 = 0.0
                                headroom2 = max(0.0, min(1.0, float(headroom2)))
                                sev2 = max(0.0, min(1.0, float(getattr(decision, "sev", 0.0) or 0.0)))
                                if eq_usd2 > 0 and headroom2 > 0 and sev2 > 0:
                                    # Smooth minimum margin target: ~0.05%..~0.45% of equity depending on (sev×headroom).
                                    min_margin_target = float(eq_usd2) * (0.0005 + 0.004 * (sev2 * headroom2))
                                    # Still respect our existing availability guards and profit-bank guard downstream.
                                    if add_margin < min_margin_target and min_margin_target > 0:
                                        add_margin = float(min_margin_target)
                                        add_notional = float(add_margin) * float(lev_h)

                                # Profit-bank margin guard: don't spend more than 30% of bank in one protect-scale add.
                                if bank_usd > 0.0 and add_margin > (0.30 * bank_usd):
                                    add_margin = float(0.30 * bank_usd)
                                    add_notional = add_margin * lev_h

                                # Min notional guard
                                eff_min = max(float(min_notional_default), float(per_sym_min.get(symbol, 0.0) or 0.0))
                                if eff_min <= 0.0 or add_notional >= eff_min:
                                    hedge_side = str(decision.hedge_side or "").upper()
                                    if hedge_side in ("LONG", "SHORT") and add_margin > 0.0:
                                        equity_usd = _to_float((eq or {}).get("equity_usd", 0.0) or 0.0, 0.0)
                                        pos_pct = (float(add_margin) / float(equity_usd) * 100.0) if equity_usd > 0 else 0.0
                                        sig = {
                                            "account_id": account_id,
                                            "symbol": symbol,
                                            "action": f"ADD_HEDGE_{hedge_side}",
                                            "action_name": f"ADD_HEDGE_{hedge_side}",
                                            "timeframe": "multi",
                                            "confidence": max(0.80, min(0.95, 0.80 + 0.15 * float(decision.sev))),
                                            "leverage": int(round(float(lev_h))),
                                            "margin_usd": float(add_margin),
                                            "notional_usd": float(add_notional),
                                            "position_size_pct": float(pos_pct),
                                            "action_category": "HEDGE",
                                            "source": "urc_protect_scale",
                                            "hedge_intent": True,
                                            "urc_state": decision.state,
                                            "urc_min_ratio": float(decision.min_hedge_ratio),
                                            "urc_ratio": float(decision.hedge_ratio),
                                            "reason": f"🛡️ urc:PROTECT scale hedge toward min_ratio={decision.min_hedge_ratio:.2f} (ratio={decision.hedge_ratio:.2f})",
                                        }
                                        if not observe_only:
                                            signals.append(sig)
                                            self._last_emit_ts[scoped_p] = float(now)

                if not decision.allow_recover:
                    continue

                # Cooldown per (account,symbol)
                scoped = f"{account_id}:{symbol}"
                last = self._last_emit_ts.get(scoped, 0.0) or 0.0
                if (now - last) < float(cooldown_sec):
                    continue

                # Min notional guard (do not bump)
                eff_min = max(float(min_notional_default), float(per_sym_min.get(symbol, 0.0) or 0.0))
                if eff_min > 0.0 and float(decision.add_notional_usd) < float(eff_min):
                    continue

                equity_usd = _to_float((eq or {}).get("equity_usd", 0.0) or 0.0, 0.0)
                pos_pct = (float(decision.add_margin_usd) / float(equity_usd) * 100.0) if equity_usd > 0 else 0.0

                action = f"INCREASE_{decision.recovery_side}"
                signal = {
                    "account_id": account_id,
                    "symbol": symbol,
                    "action": action,
                    "action_name": action,
                    "timeframe": "multi",
                    # Confidence here is a gating hint (micro overlay uses it dynamically)
                    "confidence": max(0.0, min(0.95, 0.55 + 0.40 * float(decision.reversal_rank))),
                    "leverage": int(round(float(decision.leverage))),
                    "margin_usd": float(decision.add_margin_usd),
                    "notional_usd": float(decision.add_notional_usd),
                    "position_size_pct": float(pos_pct),
                    "action_category": "RECOVERY",
                    "source": "urc_recovery",
                    "recovery_intent": True,
                    "urc_state": decision.state,
                    "urc_reversal_rank": float(decision.reversal_rank),
                    "urc_sev": float(decision.sev),
                    "urc_manip": float(decision.manip),
                    "reason": f"🧩 {decision.reason}",
                }

                # In observe mode, do not emit trade signals
                if observe_only:
                    continue

                signals.append(signal)
                self._last_emit_ts[scoped] = float(now)

        return signals




def emit_urc_proposal(redis_client, signal: Dict[str, Any]) -> bool:
    """Emit a URC signal as a proposal to the orchestrator."""
    if redis_client is None or not signal:
        return False
    try:
        from rl.proposal_bus import emit_proposal
        proposal = dict(signal)
        proposal["event"] = "URC_PROPOSAL"
        proposal["source"] = proposal.get("source", "underwater_recovery_controller")
        try:
            from risk.trainer_alignment import enrich_proposal_with_trainer
            enrich_proposal_with_trainer(redis_client, proposal)
        except Exception:
            pass
        success = emit_proposal(redis_client, stream="proposals:urc", proposal=proposal)
        if success:
            logger.info(f"🛟 [URC] PROPOSAL_EMITTED | {signal.get('account_id')}:{signal.get('symbol')} | action={signal.get('action')}")
        return success
    except Exception as e:
        logger.warning(f"[URC] emit_proposal error: {e}")
        return False
