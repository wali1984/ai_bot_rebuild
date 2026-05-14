"""
Hedge Manager v3 (Addendum v3)
=============================

Objective:
- Replace ratio-maintenance hedging with an adaptive hedge controller that selects ONE hedge action
  per (account, symbol) per cycle using 4 modes:
  1) SHIELD: liquidation protection / risk reduction
  2) ALPHA: hedge becomes profit engine when main is wrong in persistent trend
  3) HARVEST: range monetization (profit-only trims)
  4) ROLL: partial harvest + maintain protection when continuation risk persists

Design constraints:
- No-loss (never instruct losing closes; profit-only intent remains trader-enforced)
- No static caps/holds as primary drivers (continuous scoring, bounded outputs)
- Use existing feature plumbing (portfolio:positions, portfolio:equity, msnap, unified features)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from rl.decision_trace import emit_trace, build_trace

logger = logging.getLogger(__name__)


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x > 1.0:
        x = x / 100.0
    return max(0.0, min(1.0, float(x)))


@dataclass
class HedgeManagerDecision:
    mode: str  # SHIELD|ALPHA|HARVEST|ROLL|HOLD
    action: Optional[Dict[str, Any]]
    pds: float
    continuation_risk: float
    toxicity: float
    reason: str


class HedgeManagerV3:
    def __init__(self, redis_client: Any = None):
        self.redis = redis_client
        self._last_emit_ts: Dict[str, float] = {}
        # In-memory range memory for range-capture logic (avoid Redis churn).
        # Key: "{account}:{symbol}" -> deque[(ts, price)]
        self._range_mem: Dict[str, Any] = {}
        # Lightweight per-(account,symbol) cooldowns for "repair" (avg entry) actions.
        self._repair_last_ts: Dict[str, float] = {}
        # Track paired-unwind batches (winner -> loser dependency)
        self._repair_batch_state: Dict[str, Dict[str, Any]] = {}
        # Imbalance stability memory for anti-spoof gating
        self._imbalance_mem: Dict[str, Any] = {}

    def _read_trainer_signal(self, symbol: str) -> Tuple[str, float]:
        """
        Best-effort: read trainer direction + confidence from Redis.
        Returns (direction, confidence) where direction is 'LONG'|'SHORT'|'NONE' and confidence in [0..1].
        """
        sym_u = str(symbol or "").upper().strip()
        r = self.redis
        if r is None or not sym_u:
            return "NONE", 0.0

        # 1) Deconflicted multi-TF prediction (primary source — written by trainer)
        try:
            d = r.hgetall(f"prediction:{sym_u}:multi")
            if d:
                _raw_d = d if isinstance(d, dict) else {}
                if isinstance(list(_raw_d.values())[0] if _raw_d else "", bytes):
                    _raw_d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _raw_d.items()}
                conf = _clamp01(_f(_raw_d.get("confidence", _raw_d.get("model_confidence", 0.0)), 0.0))
                direction = str(_raw_d.get("direction") or "").upper()
                if direction in ("LONG", "SHORT") and conf > 0:
                    return direction, float(conf)
        except Exception:
            pass

        # 2) Per-TF prediction hashes (fallback — max confidence across TFs)
        best_dir = "NONE"
        best_conf = 0.0
        for tf in ("1h", "4h", "15m", "5m"):
            try:
                d = r.hgetall(f"prediction:{sym_u}:{tf}")
                if not d:
                    continue
                _raw_d = d if isinstance(d, dict) else {}
                if isinstance(list(_raw_d.values())[0] if _raw_d else "", bytes):
                    _raw_d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _raw_d.items()}
                conf = _clamp01(_f(_raw_d.get("confidence", _raw_d.get("model_confidence", 0.0)), 0.0))
                direction = str(_raw_d.get("direction") or "").upper()
                if direction in ("LONG", "SHORT") and conf > best_conf:
                    best_dir = direction
                    best_conf = conf
            except Exception:
                continue
        if best_conf > 0:
            return best_dir, float(best_conf)

        return "NONE", 0.0

    def _resolve_hedge_leverage(
        self,
        *,
        symbol: str,
        main_pos: Optional[Dict[str, Any]],
        pds: float,
        cont: float,
        tox: float,
        emergency: bool,
    ) -> float:
        """
        Ensure hedge actions carry an explicit leverage so the orchestrator can:
        - compute executable notional after resizing to pair-cap headroom
        - avoid DROP_MIN_NOTIONAL due to implicit 1x defaults
        """
        sym_u = str(symbol or "").upper().strip()
        # Prefer matching the live leg leverage when available.
        try:
            leg_lev = float(main_pos.get("leverage", 0.0) or 0.0) if isinstance(main_pos, dict) else 0.0
        except Exception:
            leg_lev = 0.0

        try:
            import config as _cfg  # local import to avoid heavy global imports on module load
            per = getattr(_cfg, "SYMBOL_LEVERAGE_CONFIG", {}) or {}
            scfg = per.get(sym_u) or per.get(sym_u.replace("USDT", "")) or {}
            min_lev = float(
                scfg.get("min_leverage")
                or scfg.get("min")
                or getattr(_cfg, "LEVERAGE_STATIC", 10.0)
                or 10.0
            )
            max_lev = float(scfg.get("max_leverage") or scfg.get("max") or min_lev)
        except Exception:
            min_lev, max_lev = 10.0, 10.0

        # Sanity clamps
        min_lev = max(1.0, float(min_lev))
        max_lev = max(min_lev, float(max_lev))

        # If the existing position is higher leverage, prefer to match within bounds.
        if leg_lev >= 1.0:
            min_lev = max(min_lev, min(float(leg_lev), max_lev))

        # Map risk/continuation to leverage in [min,max]
        score = max(_clamp01(pds), _clamp01(cont))
        target = float(min_lev) + (float(max_lev) - float(min_lev)) * float(score)
        if emergency:
            target = max(target, float(max_lev) * 0.85)

        lev = int(round(target))
        lev = max(int(round(min_lev)), min(int(round(max_lev)), lev))
        return float(max(1, lev))

    # -------------------------
    # Inputs
    # -------------------------
    def _read_positions(self, account_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Returns: {SYMBOL: {"LONG": pos, "SHORT": pos}}
        """
        r = self.redis
        if r is None:
            return {}
        key = f"portfolio:positions:{account_id}"
        raw_map = r.hgetall(key) or {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in (raw_map or {}).items():
            try:
                ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
            except Exception:
                ks = str(k)
            if ":" not in ks:
                continue
            sym, side = ks.rsplit(":", 1)
            side_u = str(side or "").upper()
            if side_u not in ("LONG", "SHORT"):
                continue
            try:
                if isinstance(v, dict):
                    d = v
                else:
                    vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                    d = json.loads(vv) if isinstance(vv, str) and vv else {}
            except Exception:
                d = {}
            if not isinstance(d, dict):
                continue
            try:
                sz = abs(float(d.get("size", 0) or 0.0))
            except Exception:
                sz = 0.0
            if sz <= 1e-12:
                continue
            out.setdefault(str(sym).upper(), {})[side_u] = d
        return out

    def _read_equity(self, account_id: str) -> Dict[str, Any]:
        r = self.redis
        if r is None:
            return {}
        try:
            raw = r.get(f"portfolio:equity:{account_id}")
            if isinstance(raw, dict):
                d = raw
            else:
                raw_s = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                d = json.loads(raw_s) if isinstance(raw_s, str) and raw_s else {}
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    # -------------------------
    # Feature synthesis
    # -------------------------
    def compute_continuation_and_toxicity(self, micro: Dict[str, Any]) -> Tuple[float, float]:
        if not isinstance(micro, dict):
            return 0.0, 0.0
        fast = _clamp01(_f(micro.get("fast_move_score", micro.get("flash_score", 0.0)), 0.0))
        churn = _clamp01(_f(micro.get("churn_score", 0.0), 0.0))
        snap = _clamp01(_f(micro.get("snapback_score", 0.0), 0.0))
        spoof = _clamp01(_f(micro.get("spoof_score", 0.0), 0.0))
        imb = _f(micro.get("imbalance_5", 0.0), 0.0)
        imb_mag = max(0.0, min(1.0, abs(float(imb))))
        tox = max(spoof, churn, fast)
        cont = (0.55 * fast) + (0.20 * imb_mag) + (0.15 * (1.0 - snap)) + (0.10 * (1.0 - churn))
        return max(0.0, min(1.0, cont)), max(0.0, min(1.0, tox))

    def compute_pds(
        self,
        *,
        equity: Dict[str, Any],
        main_leg: Dict[str, Any],
        micro: Dict[str, Any],
        both_losing: bool,
    ) -> float:
        # liquidation buffer (smaller buffer => higher demand)
        buf = max(0.0, _f(main_leg.get("buffer_percent", 0.0), 0.0))
        liq_close = 1.0 / (1.0 + (buf / 5.0))  # ~0.5 at 5%
        liq_close = max(0.0, min(1.0, float(liq_close)))

        eq = _f(equity.get("equity_usd", equity.get("total_margin_balance", 0.0)), 0.0)
        used = _f(equity.get("used_margin_usd", equity.get("total_initial_margin", 0.0)), 0.0)
        util = (used / eq) if eq > 0 else 0.0
        util = max(0.0, min(1.0, float(util)))

        cont, tox = self.compute_continuation_and_toxicity(micro)
        # PDS = probabilistic OR of risk factors (continuous)
        cage = 1.0 if both_losing else 0.0
        pds = 1.0 - ((1.0 - util) * (1.0 - tox) * (1.0 - liq_close) * (1.0 - 0.7 * cage))
        return max(0.0, min(1.0, float(pds)))

    # -------------------------
    # Decision
    # -------------------------
    def decide_for_symbol(
        self,
        *,
        account_id: str,
        symbol: str,
        legs: Dict[str, Any],
        equity: Dict[str, Any],
        micro: Dict[str, Any],
        pds_threshold: Optional[float] = None,
        now: Optional[float] = None,
        cooldown_sec: int = 60,
    ) -> HedgeManagerDecision:
        now = float(now if now is not None else time.time())
        key = f"{str(account_id).lower()}:{str(symbol).upper()}"

        # Single hedge opener policy (Jan 2026): HedgeManagerV3 emits opens only when selected.
        try:
            from config import HEDGE_OPEN_POLICY
            hop = str(HEDGE_OPEN_POLICY or "").strip().lower()
            if hop not in ("adaptive_hedge_builder_v2", "adaptive_hedge_builder", "always_hedge"):
                return HedgeManagerDecision("HOLD", None, 0.0, 0.0, 0.0, f"policy_block:{hop}")
        except Exception:
            pass

        long_pos = (legs or {}).get("LONG")
        short_pos = (legs or {}).get("SHORT")
        if not long_pos and not short_pos:
            return HedgeManagerDecision("HOLD", None, 0.0, 0.0, 0.0, "no_positions")

        # Determine main vs hedge by notional (fallback); prefer hedge:active marker if present.
        main_side = None
        hedge_side = None
        try:
            if self.redis is not None:
                ha = self.redis.get(f"hedge:active:{symbol}:{account_id}")
                ha = ha.decode("utf-8", errors="ignore") if isinstance(ha, (bytes, bytearray)) else ha
                ha = json.loads(ha) if ha else None
                if isinstance(ha, dict):
                    ms = str(ha.get("main_position_side") or "").upper()
                    hs = str(ha.get("hedge_position_side") or "").upper()
                    if ms in ("LONG", "SHORT") and hs in ("LONG", "SHORT"):
                        main_side, hedge_side = ms, hs
        except Exception:
            main_side, hedge_side = None, None

        def _notional(p: Optional[Dict[str, Any]]) -> float:
            if not p:
                return 0.0
            n = _f(p.get("notional", p.get("size_usd", 0.0)), 0.0)
            if n > 0:
                return abs(float(n))
            sz = abs(_f(p.get("size", 0.0), 0.0))
            px = _f(p.get("mark_price", p.get("current_price", p.get("entry_price", 0.0))), 0.0)
            return abs(float(sz) * float(px)) if sz > 0 and px > 0 else 0.0

        if not main_side:
            ln = _notional(long_pos)
            sn = _notional(short_pos)
            if ln >= sn:
                main_side, hedge_side = "LONG", "SHORT"
            else:
                main_side, hedge_side = "SHORT", "LONG"

        main_pos = long_pos if main_side == "LONG" else short_pos
        hedge_pos = long_pos if hedge_side == "LONG" else short_pos

        # Trainer signal snapshot (direction + confidence) for calibration + gating.
        trainer_dir, trainer_conf = self._read_trainer_signal(symbol)
        try:
            import config as _cfg
            min_open_conf = float(getattr(_cfg, "MIN_TRADING_CONFIDENCE", 0.87))
            min_close_conf = float(getattr(_cfg, "MIN_CLOSE_CONFIDENCE", 0.85))
            min_repair_conf = float(getattr(_cfg, "MIN_FLIP_CONFIDENCE", 0.97))
            hedge_min_ratio = float(getattr(_cfg, "HEDGE_MIN_RATIO", 0.30))
            pair_cap_usd_floor = float(getattr(_cfg, "STACK_OPEN_MAX_MARGIN_USD", 120.0))
            pair_cap_equity_pct = float(getattr(_cfg, "STACK_OPEN_MAX_EQUITY_PCT", 0.06))
        except Exception:
            min_open_conf, min_close_conf, min_repair_conf = 0.87, 0.85, 0.97
            hedge_min_ratio, pair_cap_usd_floor, pair_cap_equity_pct = 0.30, 120.0, 0.06

        # Never emit 100% confidence.
        trainer_conf = float(max(0.0, min(0.99, float(trainer_conf or 0.0))))

        # Trainer consultation policy (Jan 2026):
        # - HedgeManagerV3 remains the primary decision maker (micro/PDS/timing).
        # - Trainer acts as a validator: we only "veto" when the trainer is strongly confident
        #   *against* the exposure change implied by an action (unless emergency).
        trainer_dir_u = str(trainer_dir or "NONE").upper().strip()
        trainer_available = bool(trainer_dir_u in ("LONG", "SHORT") and float(trainer_conf) > 0.0)

        main_roe = _f(main_pos.get("roi_pct", main_pos.get("pnl_pct", 0.0)), 0.0) if main_pos else 0.0
        hedge_roe = _f(hedge_pos.get("roi_pct", hedge_pos.get("pnl_pct", 0.0)), 0.0) if hedge_pos else 0.0
        both_losing = bool(main_pos and hedge_pos and (main_roe < 0.0) and (hedge_roe < 0.0))

        cont, tox = self.compute_continuation_and_toxicity(micro)
        pds = self.compute_pds(equity=equity, main_leg=main_pos or {}, micro=micro, both_losing=both_losing)
        pds_thresh = float(pds_threshold) if pds_threshold is not None else float(pds)

        # ------------------------------------------------------------------
        # RANGE CAPTURE (Jan 2026):
        # If we have a single-leg position and market is in a bounded range,
        # open a small opposite hedge near range extremes and unwind it near
        # the other extreme. This is how we "spoil both sides" on swings like
        # ETH 2950↔2890 without needing the PPO to time every reversal.
        # ------------------------------------------------------------------
        try:
            px = _f(main_pos.get("mark_price", main_pos.get("current_price", main_pos.get("entry_price", 0.0))), 0.0) if main_pos else 0.0
        except Exception:
            px = 0.0

        range_width_pct = 0.0
        range_pos = 0.5
        range_high = 0.0
        range_low = 0.0
        try:
            if px > 0:
                k = f"{str(account_id).lower()}:{str(symbol).upper()}"
                dq = self._range_mem.get(k)
                if dq is None:
                    dq = deque(maxlen=420)  # ~3.5h at 30s cadence
                    self._range_mem[k] = dq
                now = time.time()
                dq.append((now, float(px)))
                try:
                    window_sec = int(os.getenv("HEDGE_RANGE_WINDOW_SEC", "7200"))
                except Exception:
                    window_sec = 7200
                window_sec = max(900, min(6 * 3600, int(window_sec)))
                # trim old samples
                while dq and (now - float(dq[0][0])) > window_sec:
                    dq.popleft()
                vals = [float(p) for (_t, p) in dq if p and p > 0]
                try:
                    import config as _cfg_range_samp
                    _range_min_samples = int(getattr(_cfg_range_samp, "HEDGE_RANGE_MIN_SAMPLES", 40))
                except Exception:
                    _range_min_samples = 40
                _range_min_samples = max(20, min(200, _range_min_samples))
                if len(vals) >= _range_min_samples:
                    range_high = max(vals)
                    range_low = min(vals)
                    mid = (range_high + range_low) / 2.0 if (range_high > 0 and range_low > 0) else 0.0
                    if mid > 0 and range_high > range_low:
                        range_width_pct = ((range_high - range_low) / mid) * 100.0
                        range_pos = (float(px) - float(range_low)) / (float(range_high) - float(range_low))
                        range_pos = max(0.0, min(1.0, float(range_pos)))
        except Exception:
            pass

        # Decide mode
        have_both = bool(long_pos and short_pos)
        # REINFORCE < SHIELD < ALPHA; HARVEST/ROLL when have_both.
        mode = "HOLD"
        try:
            import config as _cfg_mode
            _reinforce_thresh = float(getattr(_cfg_mode, "REINFORCE_PDS_THRESHOLD", 0.60))
        except Exception:
            _reinforce_thresh = 0.60
        if pds >= _reinforce_thresh and not have_both and main_roe < -1.0:
            mode = "REINFORCE"
        if pds >= 0.70:
            mode = "SHIELD"
        if main_roe < 0.0 and cont >= 0.65:
            mode = "ALPHA"
        if have_both and cont <= 0.35 and tox <= 0.45:
            mode = "HARVEST"
        if have_both and hedge_roe > 0.0 and cont >= 0.55:
            mode = "ROLL"

        # Global kill-switch: disable hedge harvest/trims when requested.
        try:
            import config as _cfg_hh
            _hh_enabled = bool(getattr(_cfg_hh, "ENABLE_HEDGE_HARVEST", True))
        except Exception:
            _hh_enabled = True
        if not _hh_enabled and mode in ("HARVEST", "ROLL"):
            mode = "HOLD"

        action: Optional[Dict[str, Any]] = None
        reason = f"mode={mode}|pds={pds:.2f}|cont={cont:.2f}|tox={tox:.2f}|main_roe={main_roe:.1f}|hedge_roe={hedge_roe:.1f}"

        # ------------------------------------------------------------------
        # REPAIR / DE-RISK MODE (operator): reduce-only risk cuts + recovery exits
        # ------------------------------------------------------------------
        try:
            import config as _cfg
            repair_enabled = bool(getattr(_cfg, "REPAIR_MODE_ENABLED", False))
            liq_warn = float(getattr(_cfg, "REPAIR_LIQ_DIST_WARN_PCT", 14.0))
            liq_cut = float(getattr(_cfg, "REPAIR_LIQ_DIST_CUT_PCT", 10.0))
            liq_panic = float(getattr(_cfg, "REPAIR_LIQ_DIST_PANIC_PCT", 7.0))
            cut_frac = float(getattr(_cfg, "REPAIR_LIQ_DIST_CUT_FRACTION", 0.20))
            panic_frac = float(getattr(_cfg, "REPAIR_LIQ_DIST_PANIC_FRACTION", 0.35))
            hedge_budget_frac = float(getattr(_cfg, "REPAIR_HEDGE_BUDGET_FRAC", 0.35))
            hedge_loss_cut_frac = float(getattr(_cfg, "REPAIR_HEDGE_LOSS_CUT_FRACTION", 0.25))
            recovery_roe = float(getattr(_cfg, "REPAIR_RECOVERY_ROE_PCT", -30.0))
            be_buffer_pct = float(getattr(_cfg, "REPAIR_BREAKEVEN_BUFFER_PCT", 0.05))
            repair_cooldown = int(getattr(_cfg, "REPAIR_COOLDOWN_SEC", 45))
            max_loss_usd = float(getattr(_cfg, "REPAIR_MAX_REALIZED_LOSS_USD_PER_ACTION", 25.0))
            cap_bypass_liq = float(getattr(_cfg, "REPAIR_LOSS_CAP_BYPASS_LIQ_PCT", 6.0))
            pair_unwind_enabled = bool(getattr(_cfg, "REPAIR_PAIR_UNWIND_ENABLED", True))
            pair_unwind_frac = float(getattr(_cfg, "REPAIR_PAIR_UNWIND_PROFIT_FRACTION", 1.0))
            repair_rebalance_enabled = bool(getattr(_cfg, "REPAIR_REBALANCE_ENABLED", False))
            min_realized_step_usd = float(getattr(_cfg, "REPAIR_MIN_REALIZED_STEP_USD", 25.0))
        except Exception:
            repair_enabled = False
            liq_warn, liq_cut, liq_panic = 14.0, 10.0, 7.0
            cut_frac, panic_frac = 0.20, 0.35
            hedge_budget_frac, hedge_loss_cut_frac = 0.35, 0.25
            recovery_roe, be_buffer_pct = -30.0, 0.05
            repair_cooldown = 45
            max_loss_usd = 25.0
            cap_bypass_liq = 6.0
            pair_unwind_enabled = True
            pair_unwind_frac = 1.0
            repair_rebalance_enabled = False
            min_realized_step_usd = 25.0

        def _liq_dist_pct(pos: Optional[Dict[str, Any]], side_hint: Optional[str] = None) -> Optional[float]:
            if not pos:
                return None
            try:
                lp = float(pos.get("liquidation_price") or pos.get("liquidationPrice") or 0.0)
            except Exception:
                lp = 0.0
            try:
                mp = float(pos.get("mark_price") or pos.get("current_price") or pos.get("entry_price") or 0.0)
            except Exception:
                mp = 0.0
            try:
                side_u = str(side_hint or pos.get("side") or "").upper()
            except Exception:
                side_u = ""
            try:
                buf = float(pos.get("buffer_percent") or 0.0)
            except Exception:
                buf = 0.0
            if lp <= 0 or mp <= 0 or side_u not in ("LONG", "SHORT"):
                return float(buf) if buf > 0 else None
            if side_u == "LONG":
                if lp >= mp:
                    return float(buf) if buf > 0 else None
                return max(0.0, ((mp - lp) / mp) * 100.0)
            if lp <= mp:
                return float(buf) if buf > 0 else None
            return max(0.0, ((lp - mp) / mp) * 100.0)

        def _pnl_usd(pos: Optional[Dict[str, Any]]) -> float:
            if not pos:
                return 0.0
            return _f(pos.get("unrealized_pnl", pos.get("unRealizedProfit", 0.0)), 0.0)

        def _pnl_per_unit(pos: Optional[Dict[str, Any]], side_hint: str) -> Optional[float]:
            if not pos:
                return None
            try:
                entry = float(pos.get("entry_price") or pos.get("entryPrice") or 0.0)
            except Exception:
                entry = 0.0
            try:
                mark = float(pos.get("mark_price") or pos.get("current_price") or pos.get("entry_price") or 0.0)
            except Exception:
                mark = 0.0
            if entry <= 0 or mark <= 0:
                return None
            side_u = str(side_hint or pos.get("side") or "").upper()
            if side_u == "LONG":
                return float(mark - entry)
            if side_u == "SHORT":
                return float(entry - mark)
            return None

        def _cap_close_fraction(
            pos: Optional[Dict[str, Any]],
            side_hint: str,
            close_frac: float,
            loss_cap_usd: float,
            *,
            bypass_cap: bool = False,
            min_step_usd: float = 0.0,
        ) -> Tuple[float, Optional[float], Optional[float]]:
            if not pos or close_frac <= 0:
                return 0.0, None, None
            try:
                size = abs(float(pos.get("size", 0.0) or 0.0))
            except Exception:
                size = 0.0
            if size <= 0:
                return 0.0, None, None
            per_unit = _pnl_per_unit(pos, side_hint)
            if per_unit is None:
                return float(close_frac), None, None
            est_realized = float(per_unit) * float(size) * float(close_frac)
            if est_realized >= 0 or bypass_cap:
                return float(close_frac), est_realized, None
            if min_step_usd > 0 and abs(float(est_realized)) < float(min_step_usd):
                return 0.0, est_realized, float(loss_cap_usd)
            if loss_cap_usd <= 0:
                return 0.0, est_realized, 0.0
            max_qty = float(loss_cap_usd) / max(1e-12, abs(float(per_unit)))
            max_frac = max(0.0, min(1.0, float(max_qty) / float(size)))
            return float(min(close_frac, max_frac)), est_realized, float(loss_cap_usd)

        if repair_enabled:
            rk = f"repair:{key}"
            last_rep = float(self._repair_last_ts.get(rk, 0.0) or 0.0)
            # Lightweight decision log for repair gating (rate-limited)
            try:
                if not hasattr(self, "_repair_diag_last_ts"):
                    self._repair_diag_last_ts = {}
                diag_key = f"repair_diag:{key}"
                last_diag = float(self._repair_diag_last_ts.get(diag_key, 0.0) or 0.0)
                if (now - last_diag) >= 60.0:
                    ld_long = _liq_dist_pct(long_pos, side_hint="LONG")
                    ld_short = _liq_dist_pct(short_pos, side_hint="SHORT")
                    long_pnl_dbg = _pnl_usd(long_pos)
                    short_pnl_dbg = _pnl_usd(short_pos)
                    cushion_dbg = max(0.0, long_pnl_dbg) + max(0.0, short_pnl_dbg)
                    losing_side_dbg = "LONG" if long_pnl_dbg < short_pnl_dbg else "SHORT"
                    logger.info(
                        "REPAIR_DIAG | sym=%s has_long=%s has_short=%s ld_long=%s ld_short=%s "
                        "pnl_long=%.2f pnl_short=%.2f cushion=%.2f losing_side=%s",
                        str(symbol).upper(),
                        1 if long_pos else 0,
                        1 if short_pos else 0,
                        f"{ld_long:.2f}" if ld_long is not None else "None",
                        f"{ld_short:.2f}" if ld_short is not None else "None",
                        float(long_pnl_dbg),
                        float(short_pnl_dbg),
                        float(cushion_dbg),
                        losing_side_dbg,
                    )
                    self._repair_diag_last_ts[diag_key] = now
            except Exception:
                pass
            if not getattr(self, "_repair_mode_logged", False):
                logger.warning(
                    f"REPAIR_MODE_ACTIVE | warn={liq_warn} cut={liq_cut} panic={liq_panic} "
                    f"cut_frac={cut_frac} panic_frac={panic_frac} hedge_budget_frac={hedge_budget_frac}"
                )
                self._repair_mode_logged = True
            if (now - last_rep) >= float(repair_cooldown):
                # A) Liquidation-distance deleveraging (reduce-only cut)
                if repair_rebalance_enabled:
                    ld_long = _liq_dist_pct(long_pos, side_hint="LONG")
                    ld_short = _liq_dist_pct(short_pos, side_hint="SHORT")
                    ld_candidates = []
                    if ld_long is not None:
                        ld_candidates.append(("LONG", float(ld_long)))
                    if ld_short is not None:
                        ld_candidates.append(("SHORT", float(ld_short)))
                    if ld_candidates:
                        side_u, ld = sorted(ld_candidates, key=lambda x: x[1])[0]
                        if ld <= float(liq_panic):
                            close_frac = float(panic_frac)
                            reason_tag = "REPAIR_LIQ_DIST_PANIC"
                        elif ld <= float(liq_cut):
                            close_frac = float(cut_frac)
                            reason_tag = "REPAIR_LIQ_DIST_CUT"
                        else:
                            close_frac = 0.0
                            reason_tag = ""
                        if close_frac > 0:
                            bypass_cap = bool(float(ld) <= float(cap_bypass_liq))
                            adj_frac, est_realized, loss_cap_used = _cap_close_fraction(
                                long_pos if side_u == "LONG" else short_pos,
                                side_u,
                                close_frac,
                                float(max_loss_usd),
                                bypass_cap=bypass_cap,
                                min_step_usd=float(min_realized_step_usd),
                            )
                            close_frac = float(max(0.0, adj_frac))
                            if close_frac <= 0:
                                logger.warning(
                                    "REPAIR_SKIP | reason=%s sym=%s side=%s close_frac=0 (loss_cap) ld=%.2f",
                                    reason_tag,
                                    symbol,
                                    side_u,
                                    float(ld),
                                )
                                return HedgeManagerDecision("REPAIR", None, float(pds), float(cont), float(tox), reason)
                            close_side = "SELL" if side_u == "LONG" else "BUY"
                            batch_id = str(batch.get("batch_id") or "") if (pair_unwind_enabled and float(winner_pnl) > 0 and isinstance(batch, dict)) else ""
                            action = {
                            "timestamp": time.time(),
                            "symbol": str(symbol).upper(),
                            "account_id": str(account_id),
                            "action": f"PARTIAL_CLOSE_{side_u}",
                            "action_name": f"PARTIAL_CLOSE_{side_u}",
                            "timeframe": "multi",
                            "confidence": 0.99,
                            "model_confidence": 0.99,
                            "close_fraction": float(max(0.05, min(0.90, close_frac))),
                            "side": side_u,
                            "pos_side": side_u,
                            "position_side": side_u,
                            "close_side": close_side,
                            "reduce_only": True,
                            "risk_add": 0,
                            "action_category": "RECOVERY",
                            "recovery_rebalance": True,
                            "trainer_recovery_mode": True,
                            "repair_intent": True,
                                "repair_intent_type": "LIQ_EMERGENCY" if float(ld) <= float(liq_panic) else "REBALANCE",
                                "force_loss_close": True if float(ld) <= float(liq_panic) else False,
                                "force_loss_reason": "LIQ_EMERGENCY" if float(ld) <= float(liq_panic) else None,
                            "hedge_mode": "REPAIR",
                                "expected_realized_pnl_usd": float(est_realized) if est_realized is not None else None,
                                "expected_net_realized_usd": float(est_realized) if est_realized is not None else None,
                            "reason": f"{reason_tag} | liq_dist_pct={ld:.2f}%",
                        }
                        try:
                            pos_ref = long_pos if side_u == "LONG" else short_pos
                            qty_before = abs(float(pos_ref.get("size", 0.0) or 0.0)) if isinstance(pos_ref, dict) else 0.0
                        except Exception:
                            qty_before = 0.0
                        close_qty = float(qty_before) * float(close_frac)
                        logger.warning(
                            "REPAIR_EXEC | reason=%s sym=%s side=%s close_qty=%.6f close_frac=%.3f "
                            "est_realized=%.2f cap_usd=%s liq_dist_pct=%.2f",
                            reason_tag,
                            symbol,
                            side_u,
                            close_qty,
                            float(close_frac),
                            float(est_realized) if est_realized is not None else 0.0,
                            f"{loss_cap_used:.2f}" if loss_cap_used is not None else "None",
                            float(ld),
                        )
                        logger.warning(
                            f"REPAIR_TRIGGER | reason={reason_tag} sym={symbol} side={side_u} "
                            f"close_frac={action.get('close_fraction')} liq_dist_pct={ld:.2f}"
                        )
                        self._repair_last_ts[rk] = now
                        return HedgeManagerDecision("REPAIR", action, float(pds), float(cont), float(tox), action.get("reason", reason))

                # B) Hedge-loss budget enforcement (reduce-only cut on losing leg)
                if repair_rebalance_enabled and long_pos and short_pos:
                    long_pnl = _pnl_usd(long_pos)
                    short_pnl = _pnl_usd(short_pos)
                    cushion = max(0.0, long_pnl) + max(0.0, short_pnl)
                    max_loss = float(cushion) * float(max(0.0, hedge_budget_frac))
                    losing_side = "LONG" if long_pnl < short_pnl else "SHORT"
                    losing_pnl = long_pnl if losing_side == "LONG" else short_pnl
                    winner_pnl = short_pnl if losing_side == "LONG" else long_pnl
                    batch = {}
                    if pair_unwind_enabled and float(winner_pnl) > 0:
                        max_loss = min(float(max_loss), float(winner_pnl) * float(max(0.0, pair_unwind_frac)))
                    if float(losing_pnl) < -float(max_loss) and float(max_loss) > 0:
                        # Paired-unwind: close winner first, then loser after confirmation.
                        if pair_unwind_enabled and float(winner_pnl) > 0:
                            winner_side = "SHORT" if losing_side == "LONG" else "LONG"
                            batch_key = f"{key}:pair_unwind"
                            batch = self._repair_batch_state.get(batch_key) or {}
                            if not batch or batch.get("loser_side") != losing_side:
                                batch = {
                                    "batch_id": f"rb_{int(now * 1000)}",
                                    "winner_side": winner_side,
                                    "loser_side": losing_side,
                                    "created_ts": now,
                                    "target_profit_usd": None,
                                }
                                self._repair_batch_state[batch_key] = batch

                            batch_id = str(batch.get("batch_id") or "")
                            winner_filled = False
                            if batch_id and self.redis is not None:
                                try:
                                    winner_filled = bool(self.redis.get(f"repair:batch:{batch_id}:winner_filled"))
                                except Exception:
                                    winner_filled = False

                            if not winner_filled:
                                # Emit winner trim only
                                winner_pos = long_pos if winner_side == "LONG" else short_pos
                                winner_per_unit = _pnl_per_unit(winner_pos, winner_side)
                                if winner_per_unit is None or float(winner_per_unit) <= 0:
                                    logger.warning(
                                        "REPAIR_SKIP | reason=PAIR_UNWIND_NO_WINNER_PNL sym=%s loser=%s winner=%s",
                                        symbol,
                                        losing_side,
                                        winner_side,
                                    )
                                    return HedgeManagerDecision("REPAIR", None, float(pds), float(cont), float(tox), reason)

                                # Target profit to cover capped loss (incl. fees) and avoid negative net
                                target_profit_usd = float(max_loss_usd) * float(max(0.5, min(2.0, pair_unwind_frac)))
                                try:
                                    batch["target_profit_usd"] = float(target_profit_usd)
                                    self._repair_batch_state[batch_key] = batch
                                except Exception:
                                    pass
                                try:
                                    winner_size = abs(float(winner_pos.get("size", 0.0) or 0.0)) if isinstance(winner_pos, dict) else 0.0
                                except Exception:
                                    winner_size = 0.0
                                if winner_size <= 0:
                                    logger.warning(
                                        "REPAIR_SKIP | reason=PAIR_UNWIND_NO_WINNER_SIZE sym=%s winner=%s",
                                        symbol,
                                        winner_side,
                                    )
                                    return HedgeManagerDecision("REPAIR", None, float(pds), float(cont), float(tox), reason)
                                winner_frac = min(0.90, max(0.01, float(target_profit_usd) / max(1e-12, float(winner_per_unit) * float(winner_size))))

                                winner_action = {
                                    "timestamp": time.time(),
                                    "symbol": str(symbol).upper(),
                                    "account_id": str(account_id),
                                    "action": f"PARTIAL_CLOSE_{winner_side}",
                                    "action_name": f"PARTIAL_CLOSE_{winner_side}",
                                    "timeframe": "multi",
                                    "confidence": 0.99,
                                    "model_confidence": 0.99,
                                    "close_fraction": float(max(0.01, min(0.90, winner_frac))),
                                    "side": winner_side,
                                    "pos_side": winner_side,
                                    "position_side": winner_side,
                                    "close_side": "SELL" if winner_side == "LONG" else "BUY",
                                    "reduce_only": True,
                                    "risk_add": 0,
                                    "action_category": "RECOVERY",
                                    "recovery_rebalance": True,
                                    "trainer_recovery_mode": True,
                                    "repair_intent": True,
                                    "repair_intent_type": "PAIR_UNWIND_WINNER",
                                    "hedge_mode": "REPAIR",
                                    "repair_batch_id": batch_id,
                                    "repair_phase": "WINNER",
                                    "repair_pair_unwind": True,
                                    "repair_target_profit_usd": float(target_profit_usd),
                                    "expected_realized_pnl_usd": float(winner_per_unit) * float(winner_size) * float(winner_frac),
                                    "expected_net_realized_usd": float(winner_per_unit) * float(winner_size) * float(winner_frac),
                                    "reason": f"REPAIR_PAIR_UNWIND_WINNER | target_profit_usd={target_profit_usd:.2f}",
                                }
                                logger.warning(
                                    "REPAIR_EXEC | reason=PAIR_UNWIND_WINNER sym=%s side=%s close_frac=%.3f target_profit_usd=%.2f batch_id=%s",
                                    symbol,
                                    winner_side,
                                    float(winner_action.get("close_fraction") or 0.0),
                                    float(target_profit_usd),
                                    batch_id,
                                )
                                self._repair_last_ts[rk] = now
                                return HedgeManagerDecision("REPAIR", winner_action, float(pds), float(cont), float(tox), winner_action.get("reason", reason))

                        adj_frac, est_realized, loss_cap_used = _cap_close_fraction(
                            long_pos if losing_side == "LONG" else short_pos,
                            losing_side,
                            float(hedge_loss_cut_frac),
                            float(max_loss_usd),
                            bypass_cap=False,
                            min_step_usd=float(min_realized_step_usd),
                        )
                        close_fraction = float(max(0.0, adj_frac))
                        if close_fraction <= 0:
                            logger.warning(
                                "REPAIR_SKIP | reason=REPAIR_HEDGE_BUDGET sym=%s side=%s close_frac=0 (loss_cap)",
                                symbol,
                                losing_side,
                            )
                            return HedgeManagerDecision("REPAIR", None, float(pds), float(cont), float(tox), reason)
                        close_side = "SELL" if losing_side == "LONG" else "BUY"
                        batch_target_profit = None
                        try:
                            if isinstance(batch, dict):
                                batch_target_profit = batch.get("target_profit_usd")
                        except Exception:
                            batch_target_profit = None
                        action = {
                            "timestamp": time.time(),
                            "symbol": str(symbol).upper(),
                            "account_id": str(account_id),
                            "action": f"PARTIAL_CLOSE_{losing_side}",
                            "action_name": f"PARTIAL_CLOSE_{losing_side}",
                            "timeframe": "multi",
                            "confidence": 0.99,
                            "model_confidence": 0.99,
                            "close_fraction": float(max(0.01, min(0.90, close_fraction))),
                            "side": losing_side,
                            "pos_side": losing_side,
                            "position_side": losing_side,
                            "close_side": close_side,
                            "reduce_only": True,
                            "risk_add": 0,
                            "action_category": "RECOVERY",
                            "recovery_rebalance": True,
                            "trainer_recovery_mode": True,
                            "repair_intent": True,
                            "repair_intent_type": "PAIR_UNWIND_LOSER" if batch_id else "REBALANCE",
                            "hedge_mode": "REPAIR",
                            "reason": f"REPAIR_HEDGE_BUDGET | cushion={cushion:.2f} max_loss={max_loss:.2f} losing_pnl={losing_pnl:.2f}",
                            "repair_batch_id": batch_id or None,
                            "repair_phase": "LOSER" if batch_id else None,
                            "repair_pair_unwind": bool(batch_id),
                            "expected_realized_pnl_usd": float(est_realized) if est_realized is not None else None,
                            "expected_net_realized_usd": (
                                (float(batch_target_profit) + float(est_realized))
                                if (batch_target_profit is not None and est_realized is not None)
                                else None
                            ),
                        }
                        try:
                            pos_ref = long_pos if losing_side == "LONG" else short_pos
                            qty_before = abs(float(pos_ref.get("size", 0.0) or 0.0)) if isinstance(pos_ref, dict) else 0.0
                        except Exception:
                            qty_before = 0.0
                        close_qty = float(qty_before) * float(action.get("close_fraction") or 0.0)
                        logger.warning(
                            "REPAIR_EXEC | reason=REPAIR_HEDGE_BUDGET sym=%s side=%s close_qty=%.6f close_frac=%.3f "
                            "est_realized=%.2f cap_usd=%s cushion=%.2f losing_pnl=%.2f",
                            symbol,
                            losing_side,
                            close_qty,
                            float(action.get("close_fraction") or 0.0),
                            float(est_realized) if est_realized is not None else 0.0,
                            f"{loss_cap_used:.2f}" if loss_cap_used is not None else "None",
                            float(cushion),
                            float(losing_pnl),
                        )
                        if batch_id:
                            try:
                                self._repair_batch_state.pop(batch_key, None)
                            except Exception:
                                pass
                            if self.redis is not None:
                                try:
                                    self.redis.delete(f"repair:batch:{batch_id}:winner_filled")
                                except Exception:
                                    pass
                        logger.warning(
                            f"REPAIR_TRIGGER | reason=REPAIR_HEDGE_BUDGET sym={symbol} side={losing_side} "
                            f"close_frac={action.get('close_fraction')} cushion={cushion:.2f} losing_pnl={losing_pnl:.2f}"
                        )
                        self._repair_last_ts[rk] = now
                        return HedgeManagerDecision("REPAIR", action, float(pds), float(cont), float(tox), action.get("reason", reason))

                # C) Recovery exit: set TP at breakeven+buffer for deep-negative legs
                for side_u, pos in (("LONG", long_pos), ("SHORT", short_pos)):
                    if not pos:
                        continue
                    roe = _f(pos.get("roi_pct", pos.get("pnl_pct", 0.0)), 0.0)
                    if roe > float(recovery_roe):
                        continue
                    try:
                        entry = float(pos.get("entry_price") or pos.get("entryPrice") or 0.0)
                    except Exception:
                        entry = 0.0
                    if entry <= 0:
                        continue
                    buf = max(0.0, float(be_buffer_pct)) / 100.0
                    tp = entry * (1.0 + buf) if side_u == "LONG" else entry * (1.0 - buf)
                    action = {
                        "timestamp": time.time(),
                        "symbol": str(symbol).upper(),
                        "account_id": str(account_id),
                        "action": "SET_TAKE_PROFIT",
                        "action_name": "SET_TAKE_PROFIT",
                        "timeframe": "multi",
                        "confidence": 0.95,
                        "model_confidence": 0.95,
                        "side": side_u,
                        "take_profit": float(tp),
                        "reduce_only": True,
                        "risk_add": 0,
                        "action_category": "RECOVERY",
                        "recovery_rebalance": True,
                        "trainer_recovery_mode": True,
                        "repair_intent": True,
                        "reason": f"REPAIR_BREAKEVEN_EXIT | roe={roe:.1f}% entry={entry:.4f} tp={tp:.4f}",
                    }
                    logger.warning(
                        f"REPAIR_TRIGGER | reason=REPAIR_BREAKEVEN_EXIT sym={symbol} side={side_u} "
                        f"tp={tp:.6f} roe={roe:.1f}"
                    )
                    self._repair_last_ts[rk] = now
                    return HedgeManagerDecision("REPAIR", action, float(pds), float(cont), float(tox), action.get("reason", reason))

        # RANGE mode overrides HOLD for swing capture when conditions fit.
        try:
            min_range_pct = float(os.getenv("HEDGE_RANGE_MIN_WIDTH_PCT", "1.20"))
        except Exception:
            min_range_pct = 1.20
        min_range_pct = max(0.30, min(10.0, float(min_range_pct)))
        try:
            max_cont_range = float(os.getenv("HEDGE_RANGE_MAX_CONT", "0.55"))
        except Exception:
            max_cont_range = 0.55
        max_cont_range = max(0.10, min(0.95, float(max_cont_range)))
        try:
            max_tox_range = float(os.getenv("HEDGE_RANGE_MAX_TOX", "0.60"))
        except Exception:
            max_tox_range = 0.60
        max_tox_range = max(0.10, min(0.95, float(max_tox_range)))
        is_range_regime = (float(range_width_pct) >= float(min_range_pct)) and (float(cont) <= float(max_cont_range)) and (float(tox) <= float(max_tox_range))

        # Build at most one RANGE action (only if not already in a stronger mode).
        # Gate: only enter RANGE hedge when primary position is underwater (ROE < 0).
        # If primary is in profit, there's no need for a protective range hedge.
        if mode == "HOLD" and is_range_regime and main_pos and float(main_roe) < 0.0:
            mode = "RANGE"
            reason = f"mode=RANGE|rng={range_width_pct:.2f}% pos={range_pos:.2f} hi={range_high:.2f} lo={range_low:.2f}|main_roe={main_roe:.1f}|{reason}"

            # Effective available margin (use derived calc if needed).
            try:
                wallet = float(equity.get("wallet_balance_usd") or 0.0)
            except Exception:
                wallet = 0.0
            try:
                used_m = float(equity.get("used_margin_usd") or equity.get("initial_margin_usd") or 0.0)
            except Exception:
                used_m = 0.0
            try:
                avail_m = float(equity.get("available_margin_usd") or equity.get("available_balance_usd") or 0.0)
            except Exception:
                avail_m = 0.0
            avail_calc = max(0.0, float(wallet) - float(used_m)) if wallet > 0 else 0.0
            avail_eff = max(avail_m, avail_calc)

            # Single-leg: open micro-hedge near range top/bottom.
            if not have_both:
                near_top = float(range_pos) >= 0.82
                near_bot = float(range_pos) <= 0.18
                if (main_side == "LONG" and near_top) or (main_side == "SHORT" and near_bot):
                    hedge_open_side = "SHORT" if main_side == "LONG" else "LONG"

                    # Trainer consult (validator): veto only if trainer is strongly confident AGAINST hedge direction.
                    # LTFMR: Raise veto threshold when lower-TF data shows mean-reversion is likely.
                    _ltf_rev_open = 0.0
                    _ltf_rev_open_adj = float(min_open_conf)
                    try:
                        from risk.ltf_reversal import compute_ltf_reversal_score
                        _ltf_rev_open, _ltf_rev_comps = compute_ltf_reversal_score(symbol, trainer_dir_u, self.redis)
                        if _ltf_rev_open >= 0.35:
                            _ltf_rev_open_adj = min(0.95, float(min_open_conf) + _ltf_rev_open * 0.35)
                    except Exception:
                        pass
                    if trainer_available and float(trainer_conf) >= _ltf_rev_open_adj:
                        if str(trainer_dir_u) != str(hedge_open_side).upper():
                            return HedgeManagerDecision(
                                "HOLD",
                                None,
                                float(pds),
                                float(cont),
                                float(tox),
                                f"range_open_veto_trainer_dir|need={hedge_open_side} got={trainer_dir_u} conf={trainer_conf:.2f} ltf_rev={_ltf_rev_open:.2f} adj_thr={_ltf_rev_open_adj:.2f}|{reason}",
                            )

                    # Size small and bounded; never consume full free margin.
                    try:
                        floor_usd = float(os.getenv("HEDGE_RANGE_MIN_MARGIN_USD", "15"))
                    except Exception:
                        floor_usd = 15.0
                    floor_usd = max(5.0, min(200.0, float(floor_usd)))
                    try:
                        cap_usd = float(os.getenv("HEDGE_RANGE_MAX_MARGIN_USD", "120"))
                    except Exception:
                        cap_usd = 120.0
                    cap_usd = max(floor_usd, min(120.0, float(cap_usd)))
                    m_usd = min(cap_usd, max(floor_usd, float(avail_eff) * 0.30, float(wallet) * 0.01))
                    m_usd = max(0.0, float(m_usd))
                    try:
                        _rg_raw = self.redis.get(f"regime:{symbol}")
                        if _rg_raw:
                            import json as _json_rg
                            if isinstance(_rg_raw, (bytes, bytearray)):
                                _rg_raw = _rg_raw.decode("utf-8", errors="ignore")
                            _rg = _json_rg.loads(_rg_raw)
                            if _rg:
                                _te = max(0.0, min(1.0, float(_rg.get("tf_entropy", 0) or 0)))
                                m_usd *= (1.0 - 0.40 * _te)
                    except Exception:
                        pass

                    if m_usd > 0 and float(avail_eff) >= float(floor_usd):
                        lev = self._resolve_hedge_leverage(
                            symbol=str(symbol).upper(),
                            main_pos=main_pos if isinstance(main_pos, dict) else None,
                            pds=float(pds),
                            cont=float(cont),
                            tox=float(tox),
                            emergency=False,
                        )
                        action = {
                            "timestamp": time.time(),
                            "symbol": symbol,
                            "account_id": account_id,
                            "action": f"OPEN_HEDGE_{hedge_open_side}",
                            "action_name": f"OPEN_HEDGE_{hedge_open_side}",
                            "timeframe": "multi",
                            "confidence": float(trainer_conf),
                            "model_confidence": float(trainer_conf),
                            "margin_usd": float(m_usd),
                            "leverage": float(lev),
                            "recommended_leverage": float(lev),
                            "notional_usd": float(m_usd) * float(lev) if float(m_usd) > 0 else 0.0,
                            "pds": float(pds),
                            "cont": float(cont),
                            "tox": float(tox),
                            "hedge_mode": "RANGE",
                            "decision_reason": f"range_open_{hedge_open_side.lower()}|pos={range_pos:.2f}|rng={range_width_pct:.2f}%|avail=${avail_eff:.2f}|{reason}",
                        }
                        return HedgeManagerDecision("RANGE", action, float(pds), float(cont), float(tox), action.get("decision_reason", reason))

            # Two-leg: unwind the hedge leg near the opposite extreme (profit-only intent).
            if have_both and hedge_pos:
                near_bot = float(range_pos) <= 0.18
                near_top = float(range_pos) >= 0.82
                # Unwind hedge when price moves back in favor of main.
                should_unwind = (main_side == "LONG" and near_bot) or (main_side == "SHORT" and near_top)
                if should_unwind and float(hedge_roe) > 0.0:
                    # Trainer consult (validator): unwinding hedge increases MAIN exposure.
                    # Veto only if trainer is strongly confident AGAINST main direction.
                    # LTFMR: Raise veto threshold when LTF data shows reversal against the unwind direction.
                    _ltf_rev_unwind = 0.0
                    _ltf_rev_unwind_adj = float(min_close_conf)
                    try:
                        from risk.ltf_reversal import compute_ltf_reversal_score
                        _ltf_rev_unwind, _ = compute_ltf_reversal_score(symbol, trainer_dir_u, self.redis)
                        if _ltf_rev_unwind >= 0.35:
                            _ltf_rev_unwind_adj = min(0.95, float(min_close_conf) + _ltf_rev_unwind * 0.30)
                    except Exception:
                        pass
                    if trainer_available and float(trainer_conf) >= _ltf_rev_unwind_adj:
                        if str(trainer_dir_u) != str(main_side).upper():
                            return HedgeManagerDecision(
                                "HOLD",
                                None,
                                float(pds),
                                float(cont),
                                float(tox),
                                f"range_unwind_veto_trainer_dir|need={main_side} got={trainer_dir_u} conf={trainer_conf:.2f} ltf_rev={_ltf_rev_unwind:.2f} adj_thr={_ltf_rev_unwind_adj:.2f}|{reason}",
                            )
                    close_side = hedge_side
                    action = {
                        "timestamp": time.time(),
                        "symbol": symbol,
                        "account_id": account_id,
                        "action": f"PARTIAL_CLOSE_{close_side}",
                        "action_name": f"PARTIAL_CLOSE_{close_side}",
                        "timeframe": "multi",
                        # Use trainer confidence directly for profit actions.
                        "confidence": float(trainer_conf),
                        "model_confidence": float(trainer_conf),
                        "close_fraction": 0.25,
                        "reduce_only": True,
                        "pds": float(pds),
                        "cont": float(cont),
                        "tox": float(tox),
                        "hedge_mode": "RANGE",
                        "decision_reason": f"range_unwind_{close_side.lower()}|pos={range_pos:.2f}|rng={range_width_pct:.2f}%|hedge_roe={hedge_roe:.2f}%|{reason}",
                    }
                    return HedgeManagerDecision("RANGE", action, float(pds), float(cont), float(tox), action.get("decision_reason", reason))

        # Build at most one action
        # ------------------------------------------------------------------
        # REPAIR (Avg Entry) - operator requested:
        # Allow adding to the losing leg ONLY when trainer is ultra-high confidence
        # in that direction, and only within strict pair-cap headroom.
        # ------------------------------------------------------------------
        try:
            if have_both and main_pos and hedge_pos:
                # Identify losing leg by PnL sign (best-effort)
                def _pnl_usd(p: Dict[str, Any]) -> float:
                    return _f(p.get("unrealized_pnl", p.get("unRealizedProfit", 0.0)), 0.0)

                long_pnl = _pnl_usd(long_pos) if isinstance(long_pos, dict) else 0.0
                short_pnl = _pnl_usd(short_pos) if isinstance(short_pos, dict) else 0.0
                losing_side = "LONG" if long_pnl < short_pnl else "SHORT"
                losing_pos = long_pos if losing_side == "LONG" else short_pos

                # Require the leg to be meaningfully negative
                try:
                    min_loss_usd = float(os.getenv("HEDGE_V3_REPAIR_MIN_LOSS_USD", "20.0"))
                except Exception:
                    min_loss_usd = 20.0
                min_loss_usd = max(5.0, min(500.0, float(min_loss_usd)))

                if float(_pnl_usd(losing_pos)) <= -float(min_loss_usd):
                    # Ultra-high confidence + direction alignment
                    if trainer_dir == losing_side and float(trainer_conf) >= float(min_repair_conf):
                        # Pair-cap headroom
                        wallet = _f(
                            equity.get("wallet_balance_usd", equity.get("equity_usd", equity.get("total_margin_balance", 0.0))),
                            0.0,
                        )
                        cap = float(max(float(pair_cap_usd_floor), float(wallet) * float(pair_cap_equity_pct))) if wallet > 0 else float(pair_cap_usd_floor)

                        # Tier-3 hard cap (operator request)
                        try:
                            if str(symbol).upper() in set(getattr(_cfg, "TIER3_SYMBOLS", []) or []):
                                cap = min(float(cap), float(getattr(_cfg, "TIER3_PAIR_CAP_MAX_USD", 200.0)))
                        except Exception:
                            pass

                        # Manual override: if a manual leg already exceeds base cap, allow hedges up to 50% equity
                        try:
                            if bool(getattr(_cfg, "MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED", False)):
                                exclude = set(getattr(_cfg, "MANUAL_HEDGE_PAIR_CAP_EXCLUDE_SYMBOLS", []) or [])
                                sym_u = str(symbol).upper()
                                if sym_u not in exclude and wallet > 0:
                                    origin_prefix = str(getattr(_cfg, "POSITION_ORIGIN_KEY_PREFIX", "wma:position_origin"))

                                    def _origin_for(side: str, pos: Optional[Dict[str, Any]]) -> str:
                                        try:
                                            if isinstance(pos, dict) and pos.get("origin"):
                                                return str(pos.get("origin") or "")
                                        except Exception:
                                            pass
                                        try:
                                            raw = self.redis.get(f"{origin_prefix}:{account_id}:{sym_u}:{side}") if self.redis else None
                                            if raw:
                                                raw = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                                                try:
                                                    return str(json.loads(raw).get("origin") or "")
                                                except Exception:
                                                    return str(raw)
                                        except Exception:
                                            pass
                                        return ""

                                    def _margin_for(p: Optional[Dict[str, Any]]) -> float:
                                        if not p:
                                            return 0.0
                                        return abs(_f(p.get("margin_used", p.get("initialMargin", 0.0)), 0.0))

                                    manual_override = False
                                    for side, pos in (("LONG", long_pos), ("SHORT", short_pos)):
                                        m_usd = _margin_for(pos)
                                        if m_usd <= 0:
                                            continue
                                        if _origin_for(side, pos).lower() == "manual" and float(m_usd) > float(cap):
                                            manual_override = True
                                            break
                                    if manual_override:
                                        cap = max(float(cap), float(wallet) * float(getattr(_cfg, "MANUAL_HEDGE_PAIR_CAP_EQUITY_PCT", 0.50)))
                        except Exception:
                            pass

                        def _m_usd(p: Optional[Dict[str, Any]]) -> float:
                            if not p:
                                return 0.0
                            return abs(_f(p.get("margin_used", p.get("initialMargin", 0.0)), 0.0))

                        pair_margin = float(_m_usd(long_pos) + _m_usd(short_pos))
                        headroom = max(0.0, float(cap - pair_margin))

                        # Budget for repair add
                        try:
                            max_add_usd = float(os.getenv("HEDGE_V3_REPAIR_MAX_MARGIN_USD", "60.0"))
                        except Exception:
                            max_add_usd = 60.0
                        max_add_usd = max(10.0, min(100.0, float(max_add_usd)))
                        try:
                            pct_wallet = float(os.getenv("HEDGE_V3_REPAIR_MAX_WALLET_PCT", "0.02"))
                        except Exception:
                            pct_wallet = 0.02
                        pct_wallet = max(0.005, min(0.05, float(pct_wallet)))

                        budget = min(float(max_add_usd), float(headroom), float(wallet) * float(pct_wallet) if wallet > 0 else float(max_add_usd))
                        try:
                            _rg2_raw = self.redis.get(f"regime:{symbol}")
                            if _rg2_raw:
                                import json as _json_rg2
                                if isinstance(_rg2_raw, (bytes, bytearray)):
                                    _rg2_raw = _rg2_raw.decode("utf-8", errors="ignore")
                                _rg2 = _json_rg2.loads(_rg2_raw)
                                if _rg2:
                                    _te2 = max(0.0, min(1.0, float(_rg2.get("tf_entropy", 0) or 0)))
                                    budget *= (1.0 - 0.30 * _te2)
                        except Exception:
                            pass
                        if budget >= 10.0:
                            # LTFMR: Block INCREASE to losing leg when reversal is likely.
                            # Adding to a losing SHORT during a bounce (or losing LONG during a dump)
                            # worsens drawdown if the reversal continues.
                            _ltf_rev_repair = 0.0
                            try:
                                from risk.ltf_reversal import compute_ltf_reversal_score
                                _ltf_rev_repair, _ = compute_ltf_reversal_score(symbol, losing_side, self.redis)
                                if _ltf_rev_repair >= 0.35:
                                    return HedgeManagerDecision(
                                        "HOLD",
                                        None,
                                        float(pds),
                                        float(cont),
                                        float(tox),
                                        f"REPAIR_BLOCK_LTFMR_REVERSAL|add_to={losing_side} rev_score={_ltf_rev_repair:.2f}>=0.35|{reason}",
                                    )
                            except Exception:
                                pass

                            # Leverage: match losing leg when possible
                            try:
                                lev = float(losing_pos.get("leverage", 10) or 10)
                            except Exception:
                                lev = 10.0
                            lev = max(1.0, float(lev))

                            action = {
                                "account_id": str(account_id),
                                "symbol": str(symbol).upper(),
                                "action": f"INCREASE_{losing_side}",
                                "action_name": f"INCREASE_{losing_side}",
                                "timeframe": "multi",
                                "confidence": float(trainer_conf),
                                "model_confidence": float(trainer_conf),
                                "margin_usd": float(budget),
                                "leverage": float(lev),
                                "recommended_leverage": float(lev),
                                "notional_usd": float(budget) * float(lev),
                                "action_category": "RECOVERY",
                                "source": "hedge_manager_v3",
                                "repair_intent": True,
                                "no_loss_compliant": True,
                                "pds": float(pds),
                                "hedge_necessity_class": 2,
                                "continuation_risk": float(cont),
                                "toxicity": float(tox),
                                "reason": f"🛠️ REPAIR_{losing_side}: ultra_conf={trainer_conf:.2f} loss_usd={_pnl_usd(losing_pos):.2f} headroom=${headroom:.2f} cap=${cap:.0f}",
                            }
                            return HedgeManagerDecision("REPAIR", action, float(pds), float(cont), float(tox), action["reason"])
        except Exception:
            pass

        if mode in ("HARVEST", "ROLL") and have_both and hedge_pos:
            # Consult trainer before taking profit actions (operator requirement).
            if float(trainer_conf or 0.0) <= 0.0:
                return HedgeManagerDecision("HOLD", None, float(pds), float(cont), float(tox), f"harvest_no_trainer_conf|{reason}")
            # ------------------------------------------------------------------
            # Proper data check: only trim the hedge leg when we're meaningfully
            # over-hedged vs a target hedge ratio. Do NOT harvest just because the
            # hedge is green; that kills 100x runners in continuation regimes.
            # ------------------------------------------------------------------
            try:
                from config import HEDGE_TARGET_RATIO as _HEDGE_TARGET_RATIO
                target_ratio = float(_HEDGE_TARGET_RATIO)
            except Exception:
                try:
                    target_ratio = float(os.getenv("HEDGE_TARGET_RATIO", "0.50"))
                except Exception:
                    target_ratio = 0.50
            target_ratio = max(0.10, min(1.50, float(target_ratio)))

            try:
                main_n = _notional(main_pos)
                hedge_n = _notional(hedge_pos)
                hedge_ratio = float(hedge_n / main_n) if main_n > 0 else 0.0
            except Exception:
                hedge_ratio = 0.0

            # If not over-hedged, let the winner run.
            if hedge_ratio <= (target_ratio * 1.05):
                return HedgeManagerDecision(
                    "HOLD",
                    None,
                    float(pds),
                    float(cont),
                    float(tox),
                    f"harvest_ratio_gate|ratio={hedge_ratio:.2f}<=target={target_ratio:.2f}|{reason}",
                )

            # In strong continuation, avoid trimming winners unless extremely over-hedged.
            if mode == "ROLL" and float(cont) >= 0.70 and hedge_ratio <= (target_ratio * 1.40):
                return HedgeManagerDecision(
                    "HOLD",
                    None,
                    float(pds),
                    float(cont),
                    float(tox),
                    f"roll_hold_runner|cont={cont:.2f} ratio={hedge_ratio:.2f} target={target_ratio:.2f}|{reason}",
                )

            # ------------------------------------------------------------------
            # Anti-churn / fee bleed guard for profit harvest:
            # Only harvest when the hedge leg has *enough* profit to beat fees/slippage.
            # ------------------------------------------------------------------
            try:
                min_profit_usd = float(os.getenv("HEDGE_HARVEST_MIN_PROFIT_USD", "3.0"))
            except Exception:
                min_profit_usd = 3.0
            min_profit_usd = max(0.5, min(50.0, float(min_profit_usd)))

            # Require a minimum ROI to avoid trims in noise.
            # HARVEST is range monetization → require stronger profit than ROLL.
            try:
                min_roi_pct_harvest = float(os.getenv("HEDGE_HARVEST_MIN_ROI_PCT", "0.60"))
            except Exception:
                min_roi_pct_harvest = 0.60
            try:
                min_roi_pct_roll = float(os.getenv("HEDGE_ROLL_MIN_ROI_PCT", "0.30"))
            except Exception:
                min_roi_pct_roll = 0.30
            min_roi_pct = float(min_roi_pct_harvest if mode == "HARVEST" else min_roi_pct_roll)
            min_roi_pct = max(0.05, min(5.0, float(min_roi_pct)))

            # Hedge leg profit (best-effort from position snapshot)
            hedge_pnl_usd = 0.0
            try:
                hedge_pnl_usd = _f(hedge_pos.get("unrealized_pnl", hedge_pos.get("unRealizedProfit", 0.0)), 0.0)
            except Exception:
                hedge_pnl_usd = 0.0


            # Profit sufficiency gate
            if (float(hedge_roe) < float(min_roi_pct)) or (float(hedge_pnl_usd) < float(min_profit_usd)):
                return HedgeManagerDecision(
                    "HOLD",
                    None,
                    float(pds),
                    float(cont),
                    float(tox),
                    f"harvest_profit_gate|mode={mode}|hedge_pnl_usd={hedge_pnl_usd:.2f}<{min_profit_usd:.2f}|"
                    f"hedge_roe={hedge_roe:.2f}<{min_roi_pct:.2f}|{reason}",
                )

            # Cost-aware gate: require profit to exceed estimated fees+slippage
            try:
                import config as _cfg
                round_trip_fee_pct = float(getattr(_cfg, "ROUND_TRIP_FEE_PCT", 0.0) or 0.0)
            except Exception:
                round_trip_fee_pct = 0.0
            try:
                hedge_n = _notional(hedge_pos)
                est_cost_usd = abs(float(hedge_n)) * (float(round_trip_fee_pct) / 100.0)
            except Exception:
                est_cost_usd = 0.0
            if est_cost_usd > 0 and float(hedge_pnl_usd) < float(est_cost_usd) * 2.0:
                return HedgeManagerDecision(
                    "HOLD",
                    None,
                    float(pds),
                    float(cont),
                    float(tox),
                    f"harvest_cost_gate|mode={mode}|hedge_pnl_usd={hedge_pnl_usd:.2f}<2xcost={est_cost_usd:.2f}|{reason}",
                )

            # Mean-reversion gate (range-aware when available)
            try:
                if float(range_width_pct or 0.0) > 0:
                    if str(main_side).upper() == "LONG" and float(range_pos) > 0.50:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"harvest_mean_reversion_wait|mode={mode}|range_pos={float(range_pos):.2f}|{reason}",
                        )
                    if str(main_side).upper() == "SHORT" and float(range_pos) < 0.50:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"harvest_mean_reversion_wait|mode={mode}|range_pos={float(range_pos):.2f}|{reason}",
                        )
            except Exception:
                pass

            # Profit-only trim the hedge leg (or the greener leg if roles are ambiguous)
            close_side = hedge_side
            # Operator request: allow harvesting the WINNING leg while hedged even if that
            # increases net exposure risk, but NEVER fully naked and never flip net exposure.
            try:
                # Ride-move suppression: if trainer requested to ride, do not harvest here.
                ride_key = f"wma:ride_move:{str(symbol).upper()}"
                raw_ride = self.redis.get(ride_key) if self.redis is not None else None
                raw_ride = raw_ride.decode("utf-8", errors="ignore") if isinstance(raw_ride, (bytes, bytearray)) else raw_ride
                ride = json.loads(raw_ride) if raw_ride else {}
                if isinstance(ride, dict) and bool(ride.get("suppress_tp")):
                    return HedgeManagerDecision("HOLD", None, float(pds), float(cont), float(tox), f"harvest_suppressed_ride_move|{reason}")
            except Exception:
                pass

            try:
                # Winner leg by PnL (fallback to ROE)
                main_pnl = _f(main_pos.get("unrealized_pnl", main_pos.get("unRealizedProfit", 0.0)), 0.0) if isinstance(main_pos, dict) else 0.0
                hedge_pnl = float(hedge_pnl_usd)
                winner_side = main_side if main_pnl >= hedge_pnl else hedge_side
                # Only allow if trainer is at least close-confidence
                if float(trainer_conf or 0.0) > 0.0:
                    # Fraction cap (small trims only)
                    try:
                        max_frac = float(os.getenv("HEDGE_HARVEST_WINNER_MAX_FRACTION", "0.15"))
                    except Exception:
                        max_frac = 0.15
                    max_frac = max(0.05, min(0.35, float(max_frac)))

                    # Ensure we don't leave the book effectively naked or flip net direction.
                    main_n = _notional(main_pos)
                    hedge_n = _notional(hedge_pos)
                    # Post-close notional estimates
                    f_try = max(0.05, min(max_frac, float(base_frac)))
                    main_after = main_n * (1.0 - f_try) if winner_side == main_side else main_n
                    hedge_after = hedge_n * (1.0 - f_try) if winner_side == hedge_side else hedge_n
                    # Minimum hedge ratio maintained (avoid naked main)
                    hr_after = (hedge_after / main_after) if main_after > 0 else 0.0

                    # Avoid flipping net exposure vs main: require main_after >= hedge_after * 0.70
                    try:
                        min_main_ratio = float(os.getenv("HEDGE_HARVEST_WINNER_MIN_MAIN_RATIO", "0.70"))
                    except Exception:
                        min_main_ratio = 0.70
                    min_main_ratio = max(0.50, min(0.95, float(min_main_ratio)))

                    if (hr_after >= float(hedge_min_ratio)) and (main_after >= hedge_after * float(min_main_ratio)):
                        close_side = winner_side
            except Exception:
                pass

            # Trainer consult (validator): closing one leg increases exposure to the other.
            # Veto only when trainer is strongly confident AGAINST the resulting exposure.
            try:
                # If we close hedge leg -> net exposure shifts toward MAIN side.
                # If we close main leg  -> net exposure shifts toward HEDGE side.
                expected_dir = str(main_side if str(close_side).upper() == str(hedge_side).upper() else hedge_side).upper()
                if trainer_available and float(trainer_conf) >= float(min_close_conf):
                    if str(trainer_dir_u) != expected_dir:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"harvest_veto_trainer_dir|closing={close_side} need={expected_dir} got={trainer_dir_u} conf={trainer_conf:.2f}|{reason}",
                        )
            except Exception:
                pass
            # Size: range harvest larger; roll smaller to preserve protection
            base_frac = 0.20 if mode == "HARVEST" else 0.10
            # damp by PDS (higher demand => harvest smaller)
            frac = float(base_frac) * float(max(0.25, (1.0 - pds)))
            frac = max(0.05, min(0.35, float(frac)))
            # HARVEST/ROLL: Profit-only partial close (NO-LOSS COMPLIANT)
            # The trader will reject this if the position is not profitable
            action = {
                "account_id": str(account_id),
                "symbol": str(symbol).upper(),
                "action": f"PARTIAL_CLOSE_{close_side}",
                "action_name": f"PARTIAL_CLOSE_{close_side}",
                "timeframe": "multi",
                # No static thresholds for closures; use trainer confidence directly.
                "confidence": float(min(0.95, max(0.70, float(trainer_conf or 0.0)))),
                "model_confidence": float(trainer_conf),
                "close_fraction": float(frac),
                "action_category": "PROTECTIVE",
                "source": "hedge_manager_v3",
                "profit_intent": True,  # CRITICAL: Only close if profitable
                "no_loss_compliant": True,  # Explicit no-loss flag
                "hedge_intent": True,
                "pds": float(pds),
                "continuation_risk": float(cont),
                "toxicity": float(tox),
                "hedge_mode": mode,
                "reason": f"🧠 HEDGE_{mode}: {reason}",
                "timestamp": float(now),
                "ts_ms": int(now * 1000),
                "_harvest_min_profit_usd": float(min_profit_usd),
                "_harvest_min_roi_pct": float(min_roi_pct),
            }

        elif mode in ("SHIELD", "ALPHA", "REINFORCE") and main_pos:
            # Add/maintain hedge on opposite side of main leg
            hedge_open_side = "SHORT" if main_side == "LONG" else "LONG"
            ecf_triggered = False

            # ── PHASE 3: Trainer-aware close cooldown ────────────────────
            # If the trainer recently closed a position on this side, defer
            # to prevent close-then-reopen churn.  Also check trainer:intent.
            try:
                if self.redis is not None:
                    _cd_key = f"position:close_cooldown:{str(symbol).upper()}:{hedge_open_side}"
                    _cd_val = self.redis.get(_cd_key)
                    if _cd_val:
                        _cd_str = _cd_val.decode("utf-8") if isinstance(_cd_val, (bytes, bytearray)) else str(_cd_val)
                        _trainer_still_closing = False
                        try:
                            from risk.trainer_intent import get_intent as _gi_cd
                            _ti_cd = _gi_cd(self.redis, str(symbol).upper())
                            if _ti_cd and not _ti_cd.is_stale and _ti_cd.confidence >= 0.70:
                                _ti_cd_dir = str(_ti_cd.direction or "").upper()
                                if f"CLOSE_{hedge_open_side}" in _ti_cd_dir:
                                    _trainer_still_closing = True
                        except Exception:
                            _trainer_still_closing = True
                        if not _trainer_still_closing:
                            self.redis.delete(_cd_key)
                            logger.info(
                                "HEDGE_V3_COOLDOWN_CLEARED | sym=%s side=%s | "
                                "trainer intent no longer CLOSE_%s — allowing hedge reopen",
                                symbol, hedge_open_side, hedge_open_side,
                            )
                        else:
                            logger.info(
                                "HEDGE_V3_COOLDOWN_BLOCK | sym=%s side=%s | "
                                "trainer recently closed this side (%s) — deferring %s",
                                symbol, hedge_open_side, _cd_str, mode,
                            )
                            return HedgeManagerDecision(
                                "HOLD", None, float(pds), float(cont), float(tox),
                                f"close_cooldown_active|side={hedge_open_side}|{_cd_str}|{reason}",
                            )

                    # Also check trainer:intent — if trainer wants to CLOSE
                    # the side we want to OPEN, defer unless regime overrides.
                    try:
                        from risk.trainer_intent import get_intent
                        _ti = get_intent(self.redis, str(symbol).upper())
                        if _ti is not None and not _ti.is_stale and _ti.confidence >= 0.75:
                            _ti_close_side = None
                            _ti_dir = str(_ti.direction or "").upper()
                            if "CLOSE_LONG" in _ti_dir:
                                _ti_close_side = "LONG"
                            elif "CLOSE_SHORT" in _ti_dir:
                                _ti_close_side = "SHORT"
                            if _ti_close_side == hedge_open_side:
                                # LTFMR: Bypass trainer conflict when reversal score is high.
                                _ltf_rev_ti = 0.0
                                try:
                                    from risk.ltf_reversal import compute_ltf_reversal_score
                                    _ltf_rev_ti, _ = compute_ltf_reversal_score(symbol, main_side, self.redis)
                                except Exception:
                                    pass
                                if _ltf_rev_ti < 0.35:
                                    logger.info(
                                        "HEDGE_V3_TRAINER_CONFLICT | sym=%s | trainer wants CLOSE_%s "
                                        "but hedge v3 wants OPEN_%s — deferring %s",
                                        symbol, _ti_close_side, hedge_open_side, mode,
                                    )
                                    return HedgeManagerDecision(
                                        "HOLD", None, float(pds), float(cont), float(tox),
                                        f"trainer_close_conflict|trainer={_ti_dir}|hedge_side={hedge_open_side}|{reason}",
                                    )
                    except Exception:
                        pass
            except Exception as _cd_err:
                logger.debug("HEDGE_V3_COOLDOWN_ERR | %s | %s", symbol, _cd_err)

            # ------------------------------------------------------------------
            # Direction + data validation (Jan 2026):
            # Do not open a protective hedge purely because the main leg is red.
            # Require real-time data to confirm continuation *against* the main leg:
            # - CoinAPI microstructure snapshot (`msnap:coinapi_wsds:*`)
            # - CoinAnk OI/funding (best-effort keys already in Redis)
            # - Spoof/churn filters (avoid hedging into spoof events)
            # Also: prefer better timing (wait for a small pullback) when not in emergency.
            # ------------------------------------------------------------------
            try:
                try:
                    import config as _cfg
                    fail_closed = bool(getattr(_cfg, "HEDGE_MICRO_FAIL_CLOSED", True))
                    msnap_max_age_ms = int(getattr(_cfg, "HEDGE_MSNAP_MAX_AGE_MS", 1500) or 1500)
                    ob_stability_ticks = int(getattr(_cfg, "HEDGE_OB_STABILITY_TICKS", 4) or 4)
                    ob_min_imb_abs = float(getattr(_cfg, "HEDGE_OB_MIN_IMB_ABS", 0.18) or 0.18)
                    spread_max_bps = float(getattr(_cfg, "HEDGE_SPREAD_MAX_BPS", 12.0) or 12.0)
                    spoof_cap_cfg = float(getattr(_cfg, "HEDGE_OB_MAX_SPOOF", 0.35) or 0.35)
                except Exception:
                    fail_closed = True
                    msnap_max_age_ms = 1500
                    ob_stability_ticks = 4
                    ob_min_imb_abs = 0.18
                    spread_max_bps = 12.0
                    spoof_cap_cfg = 0.35

                now_ms = int(now * 1000)

                # Freshness and spread sanity gates (fail-closed by default)
                ts_ms_raw = _f(micro.get("ts_ms", micro.get("timestamp_ms", micro.get("timestamp", 0.0))), 0.0)
                ts_ms = int(ts_ms_raw)
                if ts_ms > 0 and ts_ms < 10_000_000_000:
                    ts_ms = int(ts_ms * 1000)
                msnap_age_ms = (now_ms - ts_ms) if ts_ms > 0 else (msnap_max_age_ms + 1)
                spread_bps = _f(micro.get("spread_bps", 0.0), 0.0)

                if msnap_age_ms > int(msnap_max_age_ms):
                    if fail_closed:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"protective_block_micro|MSNAP_STALE age_ms={msnap_age_ms} max_age_ms={msnap_max_age_ms}|{reason}",
                        )
                if spread_bps > float(spread_max_bps):
                    return HedgeManagerDecision(
                        "HOLD",
                        None,
                        float(pds),
                        float(cont),
                        float(tox),
                        f"protective_block_micro|SPREAD_WIDE spread_bps={spread_bps:.2f} max={spread_max_bps:.2f}|{reason}",
                    )

                # Adverse direction is the hedge side (opposite of main)
                adverse_side = str(hedge_open_side).upper()
                imb = _f(micro.get("imbalance_5", micro.get("imbalance", 0.0)), 0.0)
                imb_mag = max(0.0, min(1.0, abs(float(imb))))
                spoof = _clamp01(_f(micro.get("spoof_score", 0.0), 0.0))
                churn = _clamp01(_f(micro.get("churn_score", 0.0), 0.0))
                snap = _clamp01(_f(micro.get("snapback_score", 0.0), 0.0))
                fast = _clamp01(_f(micro.get("fast_move_score", micro.get("fast_move_persist", 0.0)), 0.0))
                mm_score = _clamp01(_f(micro.get("market_maker_score", micro.get("mm_score", 0.0)), 0.0))

                # Direction from imbalance sign (best-effort)
                pressure_dir = None
                try:
                    min_imb = float(os.getenv("HEDGE_PROTECTIVE_MIN_IMB", "0.08"))
                except Exception:
                    min_imb = 0.08
                min_imb = max(0.01, min(0.50, float(min_imb)))
                if float(imb) >= float(min_imb):
                    pressure_dir = "LONG"
                elif float(imb) <= -float(min_imb):
                    pressure_dir = "SHORT"

                # Fast reversal score (orderbook-only) for sub-minute reaction — before stability gate
                fast_reversal_score = 0.0
                try:
                    from risk.ltf_reversal import compute_ltf_reversal_score_fast
                    fast_reversal_score, _fr_comps = compute_ltf_reversal_score_fast(symbol, main_side, self.redis)
                except Exception:
                    _fr_comps = {}


                # Imbalance stability gate (N snapshots with same sign and meaningful magnitude)
                # LTFMR fast path: relax to 2 ticks when reversal high, or bypass on orderbook flip
                mem_key = f"{str(account_id).lower()}:{str(symbol).upper()}"
                dq = self._imbalance_mem.get(mem_key)
                if dq is None:
                    dq = deque(maxlen=max(8, int(ob_stability_ticks) * 2))
                    self._imbalance_mem[mem_key] = dq
                dq.append(float(imb))
                stable = False

                # Orderbook flip: strong sign change in one sample (e.g. -0.3 -> +0.3)
                flip_thresh = float(os.getenv("HEDGE_OB_FLIP_THRESH", "0.25"))
                flip_detected = False
                if len(dq) >= 2:
                    prev_imb, cur_imb = float(dq[-2]), float(dq[-1])
                    if adverse_side == "LONG":
                        flip_detected = prev_imb <= -flip_thresh and cur_imb >= flip_thresh
                    else:
                        flip_detected = prev_imb >= flip_thresh and cur_imb <= -flip_thresh

                reversal_ok = float(fast_reversal_score) >= 0.35
                effective_ticks = 2 if (reversal_ok or flip_detected) else int(ob_stability_ticks)
                if flip_detected:
                    stable = True
                elif len(dq) >= max(2, effective_ticks):
                    vals = list(dq)[-effective_ticks:]
                    same_sign = all((v >= 0 and vals[-1] >= 0) or (v <= 0 and vals[-1] <= 0) for v in vals)
                    min_abs_ok = all(abs(float(v)) >= float(ob_min_imb_abs) for v in vals)
                    stable = bool(same_sign and min_abs_ok)

                # CoinAnk confirm (best-effort)
                oi_change = 0.0
                funding_rate = 0.0
                try:
                    if self.redis is not None:
                        raw_oi = self.redis.get(f"coinank:oi:{str(symbol).upper()}")
                        raw_oi = raw_oi.decode("utf-8", errors="ignore") if isinstance(raw_oi, (bytes, bytearray)) else raw_oi
                        d_oi = json.loads(raw_oi) if raw_oi else {}
                        if isinstance(d_oi, dict):
                            oi_change = _f(d_oi.get("oi_change_pct", d_oi.get("change_pct", 0.0)), 0.0)
                except Exception:
                    oi_change = 0.0
                try:
                    if self.redis is not None:
                        raw_f = self.redis.get(f"coinank:funding:{str(symbol).upper()}")
                        raw_f = raw_f.decode("utf-8", errors="ignore") if isinstance(raw_f, (bytes, bytearray)) else raw_f
                        d_f = json.loads(raw_f) if raw_f else {}
                        if isinstance(d_f, dict):
                            funding_rate = _f(d_f.get("funding_rate", d_f.get("rate", 0.0)), 0.0)
                except Exception:
                    funding_rate = 0.0

                # Direction support score (0..1)
                try:
                    oi_score = max(0.0, min(1.0, abs(float(oi_change)) / 10.0))
                except Exception:
                    oi_score = 0.0
                try:
                    fund_score = max(0.0, min(1.0, abs(float(funding_rate)) / 0.001))
                except Exception:
                    fund_score = 0.0
                dir_score = 0.55 * float(imb_mag) + 0.30 * float(oi_score) + 0.15 * float(fund_score)
                dir_score = max(0.0, min(1.0, float(dir_score)))

                # Emergency override: high PDS or ECF-triggered can bypass direction validation.
                # Fast adverse move: orderbook shows clear pressure against main position
                fast_adverse_move = False
                if float(fast) >= 0.45 and float(imb_mag) >= 0.12:
                    if (main_side == "SHORT" and float(imb) > 0) or (main_side == "LONG" and float(imb) < 0):
                        fast_adverse_move = True
                emergency_ok = bool(ecf_triggered) or (float(pds) >= 0.90) or fast_adverse_move


                # Reject hedges into obvious spoof/churn unless emergency.
                try:
                    # Tighten default: reduce spoof-triggered churn
                    spoof_max = float(os.getenv("HEDGE_PROTECTIVE_MAX_SPOOF", "0.55"))
                except Exception:
                    spoof_max = 0.55
                spoof_max = min(float(spoof_max), float(spoof_cap_cfg))
                spoof_max = max(0.20, min(0.99, float(spoof_max)))
                # Additional anti-MM filters: avoid hedging into churn/snapback and maker games.
                try:
                    churn_max = float(os.getenv("HEDGE_PROTECTIVE_MAX_CHURN", "0.65"))
                except Exception:
                    churn_max = 0.65
                churn_max = max(0.10, min(0.99, float(churn_max)))
                try:
                    snap_max = float(os.getenv("HEDGE_PROTECTIVE_MAX_SNAPBACK", "0.70"))
                except Exception:
                    snap_max = 0.70
                snap_max = max(0.10, min(0.99, float(snap_max)))
                try:
                    mm_max = float(os.getenv("HEDGE_PROTECTIVE_MAX_MM_SCORE", "0.70"))
                except Exception:
                    mm_max = 0.70
                mm_max = max(0.10, min(0.99, float(mm_max)))

                if (not emergency_ok) and (
                    (float(spoof) >= float(spoof_max))
                    or (float(churn) >= float(churn_max))
                    or (float(snap) >= float(snap_max))
                    or (float(mm_score) >= float(mm_max) and float(fast) < 0.80)
                ):
                    return HedgeManagerDecision(
                        "HOLD",
                        None,
                        float(pds),
                        float(cont),
                        float(tox),
                        f"protective_block_micro|spoof={spoof:.2f} churn={churn:.2f} snap={snap:.2f} mm={mm_score:.2f} fast={fast:.2f}"
                        f"|limits spoof<={spoof_max:.2f} churn<={churn_max:.2f} snap<={snap_max:.2f} mm<={mm_max:.2f}|{reason}",
                    )

                # Require continuation *against* main: pressure_dir should match adverse_side.
                dir_ok = (pressure_dir == adverse_side)
                # Also require some corroboration (avoid single-signal hedges), unless emergency.
                corroborated = (dir_score >= float(os.getenv("HEDGE_PROTECTIVE_MIN_DIR_SCORE", "0.35"))) or (float(cont) >= 0.70)
                if (not emergency_ok) and ((not dir_ok) or (not corroborated)):
                    return HedgeManagerDecision(
                        "HOLD",
                        None,
                        float(pds),
                        float(cont),
                        float(tox),
                        f"protective_wait_confirm|need={adverse_side} got={pressure_dir or 'NONE'} "
                        f"dir_score={dir_score:.2f} cont={cont:.2f} oi={oi_change:+.1f}% funding={funding_rate:+.5f}|{reason}",
                    )

                if (not emergency_ok) and (not stable):
                    return HedgeManagerDecision(
                        "HOLD",
                        None,
                        float(pds),
                        float(cont),
                        float(tox),
                        f"protective_wait_stability|imb={imb:+.3f} min_abs={ob_min_imb_abs:.3f} ticks={len(dq)}/{int(ob_stability_ticks)}|{reason}",
                    )

                # Two-tick confirmation (anti-spoof): require the same adverse direction to persist
                # across two consecutive decide() calls within a short window.
                try:
                    confirm_required = str(os.getenv("HEDGE_V3_CONFIRM_REQUIRED", "1")).strip().lower() in ("1", "true", "yes", "on")
                except Exception:
                    confirm_required = True
                # LTFMR fast path: bypass two-tick when reversal score high (fast or full)
                reversal_bypass_confirm = reversal_ok
                if (not reversal_bypass_confirm) and self.redis is not None:
                    try:
                        from risk.ltf_reversal import compute_ltf_reversal_score
                        _ltf_full, _ = compute_ltf_reversal_score(symbol, main_side, self.redis)
                        reversal_bypass_confirm = float(_ltf_full) >= 0.35
                    except Exception:
                        pass
                if confirm_required and (not emergency_ok) and (not reversal_bypass_confirm) and self.redis is not None:
                    try:
                        ck = f"hedge:v3:confirm:{str(account_id).lower()}:{str(symbol).upper()}:{adverse_side}"
                        raw = self.redis.get(ck)
                        raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                        prev = _f(raw, 0.0)
                        # first sighting → set and wait
                        if prev <= 0.0 or (now - prev) > 20.0:
                            self.redis.setex(ck, 25, str(now))
                            return HedgeManagerDecision(
                                "HOLD",
                                None,
                                float(pds),
                                float(cont),
                                float(tox),
                                f"protective_wait_persist|need_two_ticks adverse={adverse_side} dir_score={dir_score:.2f} cont={cont:.2f}|{reason}",
                            )
                    except Exception:
                        pass

                # Timing: if not emergency and price is at a local extreme in the wrong direction, wait for a pullback.
                # LTFMR: Bypass wait when reversal score is high — we're at a reversal point, open hedge now.
                try:
                    _ltf_rev_prot = 0.0
                    try:
                        from risk.ltf_reversal import compute_ltf_reversal_score
                        _ltf_rev_prot, _ = compute_ltf_reversal_score(symbol, main_side, self.redis)
                    except Exception:
                        pass

                    near_extreme = False
                    # For a LONG hedge, avoid buying at the very top of the recent range.
                    if adverse_side == "LONG" and float(range_pos) >= float(os.getenv("HEDGE_PROTECTIVE_MAX_RANGE_POS_FOR_LONG", "0.88")):
                        near_extreme = True
                    # For a SHORT hedge, avoid selling at the very bottom.
                    if adverse_side == "SHORT" and float(range_pos) <= float(os.getenv("HEDGE_PROTECTIVE_MIN_RANGE_POS_FOR_SHORT", "0.12")):
                        near_extreme = True
                    if near_extreme and (not emergency_ok) and float(cont) >= 0.55 and _ltf_rev_prot < 0.35:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"protective_wait_pullback|adverse={adverse_side} range_pos={range_pos:.2f} "
                            f"cont={cont:.2f} dir_score={dir_score:.2f}|{reason}",
                        )
                except Exception:
                    pass
            except Exception as e:
                try:
                    if fail_closed:
                        return HedgeManagerDecision(
                            "HOLD",
                            None,
                            float(pds),
                            float(cont),
                            float(tox),
                            f"protective_block_fail_closed|err={str(e)[:140]}|{reason}",
                        )
                except Exception:
                    pass
                # Explicit fallback only if fail-closed is disabled.
                logger.warning(f"HEDGE_V3_PROTECTIVE_VALIDATION_ERROR_FALLBACK | {account_id}:{symbol} | {e}")

            # Use equity headroom to size; keep small but responsive.
            eq = _f(equity.get("equity_usd", 0.0), 0.0)
            avail = _f(equity.get("available_margin_usd", equity.get("available_balance", 0.0)), 0.0)
            
            # ============================================================
            # ECF v2: Emergency Coverage Floor with Free-Margin-First
            # ============================================================
            is_one_legged = not have_both
            ecf_triggered = False
            ecf_free_margin_first = False
            
            # Dynamic sizing based on hazard (not fixed percentages)
            # Required margin = f(liquidation_distance, volatility, continuation_risk)
            liq_buf = max(0.0, _f(main_pos.get("buffer_percent", 0.0), 0.0))
            liq_urgency = max(0.0, min(1.0, 1.0 / (1.0 + liq_buf / 3.0)))  # ~0.75 at 1% buffer
            
            # Dynamic scale: higher when liq_urgency or PDS is high
            scale = 0.03 + (0.12 * pds) + (0.08 * liq_urgency) + (0.05 * cont)
            _tf_ent = 0.0
            try:
                _reg = self.redis.hgetall(f"regime:{sym}") if self.redis else None
                if _reg:
                    _tf_ent = max(0.0, min(1.0, float(_reg.get("tf_entropy", 0) or 0)))
                    scale *= (1.0 - 0.30 * _tf_ent)
            except Exception:
                pass
            scale = max(0.03, min(0.25, float(scale)))
            
            # Compute needed margin dynamically — cap to per-symbol margin limit
            try:
                from config import GOV_MAX_SYMBOL_MARGIN_PCT as _gov_sym_pct
                _sym_cap_pct = float(_gov_sym_pct)
            except Exception:
                _sym_cap_pct = 0.06
            needed_margin = eq * float(scale) if eq > 0 else 20.0
            needed_margin = max(15.0, min(needed_margin, eq * _sym_cap_pct * 0.80)) if eq > 0 else 15.0
            
            # Check if we have headroom
            margin_usd = min(needed_margin, avail * 0.40) if avail > 0 else 0.0
            
            # ECF v2: When one-legged + high PDS + no headroom, trigger FREE_MARGIN_FIRST
            # IMPORTANT:
            # - Only trigger ECF when the account is in genuine margin stress (high utilization).
            # - Apply a per-account cooldown to prevent repeated "ECF free margin" churn.
            # - Require PDS to clear both the dynamic threshold and a fixed emergency minimum.
            #
            # This addresses the observed behavior where ECF trims fire repeatedly and feel "random".
            emerg_min_pds = 0.85
            emerg_util_pct = 85.0
            try:
                from config import HEDGE_BYPASS_MIN_PDS as _HEDGE_BYPASS_MIN_PDS
                emerg_min_pds = float(_HEDGE_BYPASS_MIN_PDS)
            except Exception:
                pass
            try:
                from config import EMERGENCY_MARGIN_UTIL_PCT as _EMERGENCY_MARGIN_UTIL_PCT
                emerg_util_pct = float(_EMERGENCY_MARGIN_UTIL_PCT)
            except Exception:
                pass

            # Best-effort margin utilization (%)
            util_pct = 0.0
            try:
                eq_usd = _f(equity.get("wallet_balance_usd", equity.get("equity_usd", 0.0)), 0.0)
                used_usd = _f(equity.get("used_margin_usd", equity.get("initial_margin_usd", 0.0)), 0.0)
                if eq_usd > 0:
                    util_pct = (used_usd / eq_usd) * 100.0
            except Exception:
                util_pct = 0.0

            # ECF cooldown (account-level)
            try:
                ecf_cd_sec = int(os.getenv("ECF_FREE_MARGIN_COOLDOWN_SEC", "600"))
            except Exception:
                ecf_cd_sec = 600
            ecf_cd_sec = max(60, min(3600, int(ecf_cd_sec)))

            can_ecf = (
                is_one_legged
                and (margin_usd < 10.0)
                and (util_pct >= float(emerg_util_pct))
                and (pds >= float(max(pds_thresh or 0.0, emerg_min_pds)))
            )
            if can_ecf:
                try:
                    if self.redis is not None:
                        ck = f"ecf:free_margin:last:{str(account_id).lower()}"
                        last_ecf = self.redis.get(ck)
                        last_ecf = last_ecf.decode("utf-8", errors="ignore") if isinstance(last_ecf, (bytes, bytearray)) else last_ecf
                        last_ts = _f(last_ecf, 0.0)
                        if last_ts > 0 and (now - last_ts) < float(ecf_cd_sec):
                            # Cooldown active: do NOT trigger ECF; allow normal hedge sizing path to proceed.
                            can_ecf = False
                except Exception:
                    pass

            if can_ecf:
                ecf_triggered = True
                if avail < 10.0:
                    # Cannot open hedge without freeing margin first
                    ecf_free_margin_first = True
                    logger.warning(
                        f"⚠️ [ECF_V2] FREE_MARGIN_FIRST | {account_id}:{symbol} | "
                        f"one_legged=True pds={pds:.2f} util={util_pct:.1f}% avail=${avail:.2f} needed=${needed_margin:.2f} cd={ecf_cd_sec}s"
                    )
                else:
                    # Have some margin, use it
                    margin_usd = min(needed_margin, avail * 0.80)
                    logger.warning(
                        f"⚠️ [ECF_V2] EMERGENCY_HEDGE | {account_id}:{symbol} | "
                        f"one_legged=True pds={pds:.2f} util={util_pct:.1f}% margin=${margin_usd:.2f}"
                    )
            
            # ECF v2: FREE_MARGIN_FIRST action (profit-only trim from OTHER symbols)
            if ecf_free_margin_first:
                # Emit a FREE_MARGIN action instead of OPEN_HEDGE
                # This tells the system to harvest from profitable positions elsewhere first
                # Stamp ECF cooldown so we don't spam the sequencer every cycle.
                try:
                    if self.redis is not None:
                        self.redis.setex(
                            f"ecf:free_margin:last:{str(account_id).lower()}",
                            int(ecf_cd_sec),
                            str(now),
                        )
                except Exception:
                    pass
                action = {
                    "account_id": str(account_id),
                    "symbol": str(symbol).upper(),  # Target symbol that needs hedge
                    "action": "FREE_MARGIN_FOR_HEDGE",
                    "action_name": "FREE_MARGIN_FOR_HEDGE",
                    "timeframe": "multi",
                    "confidence": float(trainer_conf),
                    "model_confidence": float(trainer_conf),
                    "target_margin_usd": float(needed_margin),
                    "target_hedge_side": str(hedge_open_side),
                    "action_category": "ECF_SEQUENCER",
                    "source": "hedge_manager_v3",
                    "hedge_intent": True,
                    "no_loss_compliant": True,  # Will only trim profitable positions
                    "profit_intent": True,  # Only close profitable positions
                    "pds": float(pds),
                    "hedge_necessity_class": 2,  # Highest priority
                    "continuation_risk": float(cont),
                    "toxicity": float(tox),
                    "hedge_mode": "ECF_FREE_MARGIN",
                    "ecf_triggered": True,
                    "ecf_version": 2,
                    "one_legged_emergency": True,
                    "reason": f"🚨 ECF_V2_FREE_MARGIN: {reason}",
                }
            elif margin_usd >= 5.0:
                # Have margin, proceed with hedge
                hnc = 2 if (ecf_triggered or pds >= 0.85) else (1 if pds >= 0.65 else 0)
                lev = self._resolve_hedge_leverage(
                    symbol=str(symbol).upper(),
                    main_pos=main_pos if isinstance(main_pos, dict) else None,
                    pds=float(pds),
                    cont=float(cont),
                    tox=float(tox),
                    emergency=bool(ecf_triggered) or float(pds) >= 0.85 or int(hnc) >= 2,
                )
                # SHIELD/ALPHA/REINFORCE: Open new hedge position (NO-LOSS COMPLIANT)
                _reinforce_scale = 0.50 if mode == "REINFORCE" else 1.0
                _eff_margin = float(margin_usd) * _reinforce_scale
                action = {
                    "account_id": str(account_id),
                    "symbol": str(symbol).upper(),
                    "action": f"ADD_HEDGE_{hedge_open_side}" if have_both else f"OPEN_HEDGE_{hedge_open_side}",
                    "action_name": f"ADD_HEDGE_{hedge_open_side}" if have_both else f"OPEN_HEDGE_{hedge_open_side}",
                    "timeframe": "multi",
                    "confidence": float(trainer_conf),
                    "model_confidence": float(trainer_conf),
                    "margin_usd": float(_eff_margin),
                    "leverage": float(lev),
                    "recommended_leverage": float(lev),
                    "notional_usd": float(_eff_margin) * float(lev) if float(_eff_margin) > 0 else 0.0,
                    "action_category": "HEDGE",
                    "source": "hedge_manager_v3",
                    "hedge_intent": True,
                    "no_loss_compliant": True,  # Explicit no-loss flag (hedge opening never realizes loss)
                    # Need-based bypass metadata (consumed by policy layers)
                    "pds": float(pds),
                    "hedge_necessity_class": int(hnc),
                    "continuation_risk": float(cont),
                    "toxicity": float(tox),
                    "hedge_mode": mode,
                    "ecf_triggered": bool(ecf_triggered),
                    "ecf_version": 2 if ecf_triggered else 0,
                    "one_legged_emergency": bool(ecf_triggered and is_one_legged),
                    "reason": f"🧠 HEDGE_{mode}: {reason}",
                }

        if action:
            pass
        return HedgeManagerDecision(mode, action, float(pds), float(cont), float(tox), reason)

    def generate_signals(self, *, accounts: Tuple[str, ...] = ("primary", "asjad")) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.redis is None:
            return out

        # Self-guard: respect HEDGE_MANAGER_V3_ENABLED kill switch (defense-in-depth)
        try:
            from config import HEDGE_MANAGER_V3_ENABLED
            if not HEDGE_MANAGER_V3_ENABLED:
                logger.debug("[HEDGE_V3_SELF_GUARD] Disabled via config — returning empty")
                return out
        except ImportError:
            pass  # Config unavailable — fail-open (caller already guards)

        now = time.time()
        try:
            from config import DECISION_TRACE_ENABLED, DECISION_TRACE_STREAM
        except Exception:
            DECISION_TRACE_ENABLED = False
            DECISION_TRACE_STREAM = "wma:traces"
        for aid in accounts:
            legs_by_sym = self._read_positions(str(aid))
            if not legs_by_sym:
                continue
            equity = self._read_equity(str(aid))

            # Compute dynamic PDS threshold (account-level p95 across symbols)
            pds_vals: List[float] = []
            for sym, legs in (legs_by_sym or {}).items():
                try:
                    micro = {}
                    try:
                        micro = self.redis.hgetall(f"msnap:coinapi_wsds:{sym}") or {}
                        if micro and isinstance(next(iter(micro.keys())), (bytes, bytearray)):
                            micro = {k.decode("utf-8", errors="ignore"): v.decode("utf-8", errors="ignore") for k, v in micro.items()}
                    except Exception:
                        micro = {}
                    # Best-effort main leg for PDS
                    main_leg = (legs or {}).get("LONG") or (legs or {}).get("SHORT") or {}
                    p = self.compute_pds(equity=equity, main_leg=main_leg or {}, micro=micro, both_losing=False)
                    pds_vals.append(float(p))
                except Exception:
                    continue
            pds_threshold = None
            if pds_vals:
                pds_vals.sort()
                idx = int(max(0, min(len(pds_vals) - 1, round(0.95 * (len(pds_vals) - 1)))))
                pds_threshold = float(pds_vals[idx])

            for sym, legs in (legs_by_sym or {}).items():
                # best-effort microstructure snapshot
                micro = {}
                try:
                    micro = self.redis.hgetall(f"msnap:coinapi_wsds:{sym}") or {}
                    # decode bytes
                    if micro and isinstance(next(iter(micro.keys())), (bytes, bytearray)):
                        micro = {k.decode("utf-8", errors="ignore"): v.decode("utf-8", errors="ignore") for k, v in micro.items()}
                except Exception:
                    micro = {}

                _sym_pds_thresh = pds_threshold
                _hedge_closed_evt = False
                try:
                    _evt_key = f"hedge:closed_event:{sym}:{aid}"
                    _evt_raw = self.redis.get(_evt_key)
                    if _evt_raw:
                        # P4 ALIGNMENT: Check reopen cooldown before allowing
                        # immediate re-evaluation. If the hedge was adaptively
                        # released (ineffective), don't set pds_threshold=0.
                        _cd_key = f"hedge:reopen_cooldown:{sym}:{aid}"
                        _in_cooldown = False
                        try:
                            _in_cooldown = bool(self.redis.exists(_cd_key))
                        except Exception:
                            pass
                        if _in_cooldown:
                            logger.info(
                                "[HEDGE_REEVAL_COOLDOWN] %s:%s hedge closed event "
                                "suppressed — adaptive release cooldown active",
                                aid, sym,
                            )
                            self.redis.delete(_evt_key)
                        else:
                            _hedge_closed_evt = True
                            _sym_pds_thresh = 0.0
                            self.redis.delete(_evt_key)
                            logger.info("[HEDGE_REEVAL] %s:%s hedge closed event → immediate re-evaluation", aid, sym)
                except Exception:
                    pass

                dec = self.decide_for_symbol(
                    account_id=str(aid),
                    symbol=str(sym),
                    legs=legs,
                    equity=equity,
                    micro=micro,
                    pds_threshold=_sym_pds_thresh,
                    now=now,
                )
                if DECISION_TRACE_ENABLED:
                    try:
                        trace = build_trace(
                            trace_id=None,
                            account_id=str(aid),
                            symbol=str(sym),
                            phase="HEDGE_MANAGER_V3",
                            module="hedge_manager_v3",
                            payload={
                                "mode": dec.mode,
                                "pds": dec.pds,
                                "continuation_risk": dec.continuation_risk,
                                "toxicity": dec.toxicity,
                                "reason": dec.reason,
                            },
                        )
                        emit_trace(self.redis, stream=str(DECISION_TRACE_STREAM), trace=trace)
                    except Exception:
                        pass
                if dec.action:
                    out.append(dec.action)
        return out

