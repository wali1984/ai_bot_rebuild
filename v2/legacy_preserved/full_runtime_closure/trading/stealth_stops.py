"""
Stealth Stop Loss / Take Profit System

Instead of placing visible STOP_MARKET orders on the exchange (which market makers can see),
this module monitors prices client-side and executes when thresholds are hit.

Execution Strategy (Hybrid Limit → Market Fallback):
- Uses POST_ONLY limit orders first to save maker fees (~0.04% savings per trade)
- Random wait time (10-60s) to avoid detection by market maker algos
- Falls back to market order if limit doesn't fill
- Anti-chase: randomized price offset (0.03-0.08%) and wait times

Benefits:
- Hides trader intentions from market makers
- Prevents stop hunting
- Saves ~70-80% of taker fees via maker orders
- Guaranteed execution with market fallback

Author: WMA AI Trading System
"""

import time
import json
import threading
import logging
import random
import math
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
import redis

# Optional Telegram integration (used for alerts)
try:
    from telegram_alerts import TelegramNotifier  # type: ignore
except Exception:
    TelegramNotifier = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class StealthStop:
    """Represents a client-side conditional order"""
    symbol: str
    side: str  # LONG or SHORT
    stop_type: str  # STOP_LOSS or TAKE_PROFIT
    trigger_price: float
    position_size: float  # Quantity to close
    close_percentage: float = 100.0  # % of position to close
    timestamp_created: float = 0.0
    account_id: str = "primary"
    
    # Metadata
    signal_id: Optional[str] = None
    reason: str = ""
    
    # Hedge protection - force maker-only execution for hedged positions
    hedge_maker_only: bool = False
    
    # Entry price for PnL calculation in feedback publishers
    entry_price: float = 0.0
    
    def __post_init__(self):
        if self.timestamp_created == 0.0:
            self.timestamp_created = time.time()
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'StealthStop':
        # Handle old data that doesn't have hedge_maker_only or entry_price
        data.pop('hedge_maker_only', None)  # Remove if exists, we'll use default
        _entry_px = float(data.pop('entry_price', 0.0) or 0.0)
        stop = cls(**data)
        stop.entry_price = _entry_px
        return stop
    
    def should_trigger(self, current_price: float) -> bool:
        """Check if current price has hit the trigger threshold"""
        if self.stop_type == 'STOP_LOSS':
            if self.side == 'LONG':
                # Long stop loss triggers when price goes below threshold
                return current_price <= self.trigger_price
            else:  # SHORT
                # Short stop loss triggers when price goes above threshold
                return current_price >= self.trigger_price
        
        elif self.stop_type == 'TAKE_PROFIT':
            _is_trailing_tp = "TRAIL" in str(getattr(self, 'reason', '') or '').upper()
            # APRIL PLAN v3: Minimum profit guard — prevent $1 wins
            _entry_px = getattr(self, 'entry_price', 0) or 0
            if _entry_px and _entry_px > 0:
                try:
                    from config import EXIT_TP_MIN_PRICE_MOVE_PCT, APRIL_PLAN_EXITS_ENABLED
                    if APRIL_PLAN_EXITS_ENABLED:
                        if self.side == 'LONG':
                            _price_move_pct = (current_price - _entry_px) / _entry_px * 100
                        else:
                            _price_move_pct = (_entry_px - current_price) / _entry_px * 100
                        if _price_move_pct < EXIT_TP_MIN_PRICE_MOVE_PCT:
                            return False  # Not enough profit to justify TP
                except Exception:
                    pass  # Fail-open: allow trigger if config import fails
            if self.side == 'LONG':
                return current_price <= self.trigger_price if _is_trailing_tp else current_price >= self.trigger_price
            else:  # SHORT
                return current_price >= self.trigger_price if _is_trailing_tp else current_price <= self.trigger_price
        
        return False


class StealthStopMonitor:
    """
    Monitors prices and executes conditional orders client-side.
    
    This replaces visible exchange-side STOP_MARKET orders with
    client-side monitoring that only places market orders when triggered.
    
    Integrates with DynamicAdaptiveStops for market-intelligent stop levels.
    """
    
    def __init__(self, redis_client, binance_client, account_id: str = "primary", telegram_notifier: Optional[Any] = None):
        self.redis = redis_client
        self.binance = binance_client
        self.account_id = account_id
        self.telegram = telegram_notifier
        
        # In-memory storage of pending stops
        self.pending_stops: Dict[str, List[StealthStop]] = defaultdict(list)  # symbol -> [stops]
        self._lock = threading.RLock()
        
        # Monitoring thread
        self._running = False
        self._monitor_thread = None
        
        # Performance tracking
        self.stops_triggered = 0
        self.stops_executed = 0
        self.stops_failed = 0
        
        # Hybrid limit execution tracking (fee savings)
        self.limit_fills = 0      # Orders filled via limit (maker fee)
        self.market_fallbacks = 0 # Orders that needed market fallback (taker fee)
        self.total_fee_savings_usd = 0.0  # Estimated USD saved via maker orders
        
        # Adaptive stops integration
        self._adaptive_stops = None
        self._init_adaptive_stops()

        # Profit-lock confirmation state (anti-wick)
        self._profit_lock_confirm: Dict[str, Dict[str, float]] = {}
        # Full flatten of a hedged book: require N consecutive stealth trigger evaluations
        self._hedge_flat_confirm: Dict[str, int] = {}
        # TP touch state (maker placement + IOC fallback)
        self._tp_touch_state: Dict[str, Dict[str, Any]] = {}
        # Low-rate heartbeat to confirm TP evaluation loop is alive
        self._tp_monitor_hb_ts: Dict[str, float] = {}
        # Exchange info cache for price/qty precision
        self._exchange_info_cache: Dict[str, Any] = {"ts": 0.0, "symbols": {}}
        self._exchange_info_ttl_sec = 300
        
        logger.info(f"[STEALTH-STOPS] Initialized for account: {account_id}")

    def _account_label(self) -> str:
        """Human friendly account label for Telegram messages."""
        aid = str(self.account_id or "").strip().lower()
        if aid == "primary":
            return "Wajid"
        if aid == "asjad":
            return "Asjad"
        return str(self.account_id or "UNKNOWN")

    def _send_trade_alert_async(self, message: str):
        """Fire-and-forget send to Telegram trade channel (never blocks stop execution)."""
        if not self.telegram:
            return

        def _runner():
            loop = None
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.telegram.send_trade_alert(message))
            except Exception as e:
                logger.debug(f"[TELEGRAM] Stealth alert failed: {e}")
            finally:
                try:
                    if loop:
                        loop.close()
                except Exception:
                    pass

        try:
            t = threading.Thread(target=_runner, daemon=True)
            t.start()
        except Exception:
            # As a last resort, don't block execution
            return
    
    def _init_adaptive_stops(self):
        """Initialize adaptive stops system if enabled."""
        try:
            from config import ADAPTIVE_STOPS_ENABLED
            if ADAPTIVE_STOPS_ENABLED:
                from trading.dynamic_adaptive_stops import get_adaptive_stops
                self._adaptive_stops = get_adaptive_stops(self.redis)
                logger.info("[STEALTH-STOPS] ✅ Adaptive stops system enabled")
        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Adaptive stops not available: {e}")

    def _microstructure_trail_compression(self, symbol: str, side: str, leverage: float = 1.0) -> float:
        """Dynamically compress trailing stop distance when microstructure confirms
        a genuine adverse move against the position.

        Returns a compression factor (0.3–1.0).  1.0 = no compression.
        Uses fast_move_score, p_false_move, snapback_score, imbalance, and
        liquidation cluster proximity — all from live Redis data.
        """
        try:
            if not self.redis:
                return 1.0
            from risk.intelligent_close_guard import _decode_map, _find_feat

            # ── 1. Microstructure snapshot ──────────────────────────
            msnap_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
            if not msnap_raw:
                return 1.0
            msnap = _decode_map(msnap_raw)

            fast_move = float(msnap.get("fast_move_score", 0) or 0)
            p_false   = float(msnap.get("p_false_move", 0) or 0)
            snapback  = float(msnap.get("snapback_score", 0) or 0)
            imbalance = float(msnap.get("imbalance_5", 0) or 0)

            # If the move is likely false/spoofed → no compression
            if p_false > 0.4 or snapback > 0.5:
                return 1.0

            # ── 2. Is the move AGAINST the position? ────────────────
            is_long = side.upper() == "LONG"
            is_adverse = (is_long and imbalance < -0.3) or (not is_long and imbalance > 0.3)
            if not is_adverse:
                return 1.0

            # ── 3. Confirmed move intensity ─────────────────────────
            move_intensity = fast_move * (1.0 - p_false)
            if move_intensity <= 0.5:
                return 1.0

            leverage_factor = min(leverage / 25.0, 3.0)
            compression = max(0.3, 1.0 - (move_intensity - 0.5) * leverage_factor * 0.5)

            # ── 4. Hedge coverage dampens compression ───────────────
            hedge_cov = 0.0
            try:
                counter_side = "SHORT" if is_long else "LONG"
                hedge_cov = self._get_hedge_coverage_for_ramp(symbol, side, counter_side)
            except Exception:
                pass
            if hedge_cov >= 0.30:
                compression = min(1.0, compression + 0.3)

            # ── 5. Liquidation cluster proximity (Phase 6) ──────────
            try:
                for tf in ("1m", "5m"):
                    feat_raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                    if not feat_raw:
                        continue
                    feat = _decode_map(feat_raw)
                    if is_long:
                        liq_dist = float(feat.get("liquidation_long_distance_pct", 100) or 100)
                        liq_str  = float(feat.get("liquidation_long_strength", 0) or 0)
                    else:
                        liq_dist = float(feat.get("liquidation_short_distance_pct", 100) or 100)
                        liq_str  = float(feat.get("liquidation_short_strength", 0) or 0)

                    proximity_threshold = 5.0 / max(1.0, leverage / 15.0)
                    if liq_dist < proximity_threshold and liq_str > 0.3:
                        liq_compression = max(0.5, 1.0 - (1.0 - liq_dist / proximity_threshold) * liq_str)
                        compression *= liq_compression
                        break
            except Exception:
                pass

            compression = max(0.3, min(1.0, compression))

            if compression < 0.95:
                logger.info(
                    "RAMP_TRAIL_COMPRESS | sym=%s side=%s | fast_move=%.2f p_false=%.2f "
                    "snapback=%.2f imbalance=%.3f | lev=%.0fx hedge_cov=%.0f%% | "
                    "compression=%.2f",
                    symbol, side, fast_move, p_false, snapback, imbalance,
                    leverage, hedge_cov * 100, compression,
                )

            return compression
        except Exception:
            return 1.0

    def _get_hedge_coverage_for_ramp(self, symbol: str, pos_side: str, counter_side: str) -> float:
        """Return hedge coverage ratio (counter margin / main margin). 0.0 if no hedge."""
        try:
            if not self.redis:
                return 0.0
            import json as _hjson
            _sym = symbol.upper()
            _main_sk = pos_side.lower()
            _hedge_sk = counter_side.lower()
            _ph = self.redis.hgetall(f"positions:live:{_sym}")
            if not _ph:
                return 0.0
            _pd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _ph.items()}
            _main_raw = _pd.get(_main_sk)
            _hedge_raw = _pd.get(_hedge_sk)
            if not _main_raw:
                return 0.0
            _main = _hjson.loads(_main_raw) if isinstance(_main_raw, str) else {}
            main_margin = abs(float(_main.get("margin_used", 0) or _main.get("isolatedWallet", 0) or _main.get("initialMargin", 0) or 0))
            if main_margin <= 0:
                return 0.0
            if not _hedge_raw:
                return 0.0
            _hedge = _hjson.loads(_hedge_raw) if isinstance(_hedge_raw, str) else {}
            hedge_margin = abs(float(_hedge.get("margin_used", 0) or _hedge.get("isolatedWallet", 0) or _hedge.get("initialMargin", 0) or 0))
            if hedge_margin > 0:
                return hedge_margin / main_margin
            return 0.0
        except Exception:
            return 0.0

    def _atr_adaptive_trail_distance(self, symbol: str, side: str, base_dist: float) -> float:
        """Widen trailing stop distance using live ATR when regime supports the trend.

        Returns max(base_dist, ATR_pct * 1.5) when regime is FAST/IMPULSE and
        trend aligns with position side. Falls back to base_dist otherwise.
        """
        try:
            if not self.redis:
                return base_dist
            import json as _json
            regime_raw = self.redis.get(f"regime:{symbol}")
            if not regime_raw:
                return base_dist
            regime = _json.loads(
                regime_raw.decode("utf-8") if isinstance(regime_raw, (bytes, bytearray)) else str(regime_raw)
            )
            move_regime = str(regime.get("move_regime", "")).upper()
            trend_dir = str(regime.get("trend_direction", "")).upper()
            is_long = side.upper() == "LONG"
            trend_aligned = (
                (is_long and trend_dir in ("LONG", "BULLISH", "UP"))
                or (not is_long and trend_dir in ("SHORT", "BEARISH", "DOWN"))
            )
            if move_regime not in ("FAST", "IMPULSE", "TRENDING", "BREAKOUT") or not trend_aligned:
                return base_dist

            from risk.intelligent_close_guard import _find_feat, _decode_map
            atr_pct = 0.0
            for tf in ("15m", "5m", "1h"):
                feat_raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if not feat_raw:
                    continue
                feat = _decode_map(feat_raw)
                _atr = _find_feat(feat, "atr_pct", "atr_14", "ind_ta_NATR_14")
                if _atr and _atr > atr_pct:
                    atr_pct = _atr

            if atr_pct <= 0:
                return base_dist

            _vol_score = float(regime.get("volatility_score", 0.5) or 0.5)
            _liq_score = float(regime.get("liquidity_score", 0.5) or 0.5)
            _trail_atr_mult = 1.0
            if _vol_score > 0.6:
                _trail_atr_mult += 0.3 + (_vol_score - 0.6)
            if _liq_score > 0.5:
                _trail_atr_mult += 0.2
            _adx_trail = 0.0
            try:
                from risk.intelligent_close_guard import _find_feat, _decode_map as _dm_trail
                for _ttf in ("15m", "5m"):
                    _tfr = self.redis.hgetall(f"unified_features:{symbol}:{_ttf}")
                    if not _tfr:
                        continue
                    _tff = _dm_trail(_tfr)
                    _adx_trail = _find_feat(_tff, "adx_14", "adx", "ind_ta_ADX_14") or 0.0
                    if _adx_trail > 0:
                        break
            except Exception:
                pass
            if _adx_trail > 35:
                _trail_atr_mult += 0.4
            elif _adx_trail > 25:
                _trail_atr_mult += 0.2
            _trail_atr_mult = max(1.0, min(3.0, _trail_atr_mult))
            adaptive_dist = atr_pct * _trail_atr_mult
            widened = max(base_dist, adaptive_dist)
            if widened > base_dist:
                logger.info(
                    "ATR_TRAIL_WIDEN | sym=%s side=%s | base=%.2f%% atr=%.3f%% adaptive=%.2f%% | regime=%s trend=%s",
                    symbol, side, base_dist, atr_pct, widened, move_regime, trend_dir,
                )
            return widened
        except Exception:
            return base_dist

    def _update_exchange_backstop(self, symbol: str, side: str,
                                  current_price: float, leverage: float,
                                  trail_trigger_price: float,
                                  position_qty: float) -> None:
        """Place/update an exchange-side STOP_MARKET as crash protection for
        high-leverage positions.  The backstop is set WIDER than the stealth
        trailing stop so it only fires if the bot fails.

        RAMP Phase 4 — no bleeding risk (single exchange order, no fee until
        triggered; 2x wider than trailing stop).
        """
        try:
            from config import (
                RAMP_EXCHANGE_BACKSTOP_ENABLED,
                RAMP_EXCHANGE_BACKSTOP_MIN_LEVERAGE,
                RAMP_EXCHANGE_BACKSTOP_MARGIN_PCT,
            )
            if not RAMP_EXCHANGE_BACKSTOP_ENABLED:
                return
            if leverage < RAMP_EXCHANGE_BACKSTOP_MIN_LEVERAGE:
                return
        except Exception:
            return

        try:
            if not self.binance or not self.redis or current_price <= 0:
                return

            from risk.intelligent_close_guard import _decode_map, _find_feat
            atr_pct = 0.0
            for tf in ("5m", "15m"):
                feat_raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if feat_raw:
                    feat = _decode_map(feat_raw)
                    _a = _find_feat(feat, "atr_pct", "atr_14", "ind_ta_NATR_14")
                    if _a and _a > atr_pct:
                        atr_pct = _a

            # Trailing stop distance (current price to trail trigger)
            is_long = side.upper() == "LONG"
            if is_long:
                trail_dist_pct = (trail_trigger_price - current_price) / current_price * 100.0 if trail_trigger_price > current_price else 1.0
            else:
                trail_dist_pct = (current_price - trail_trigger_price) / current_price * 100.0 if trail_trigger_price < current_price else 1.0
            trail_dist_pct = abs(trail_dist_pct)

            margin_pct = float(RAMP_EXCHANGE_BACKSTOP_MARGIN_PCT) / 100.0
            backstop_dist_pct = max(
                trail_dist_pct * 2.0,
                atr_pct * 3.0,
                (1.0 / leverage) * margin_pct * 100.0,
            )
            backstop_dist_pct = min(backstop_dist_pct, 10.0)

            if is_long:
                backstop_price = current_price * (1.0 - backstop_dist_pct / 100.0)
            else:
                backstop_price = current_price * (1.0 + backstop_dist_pct / 100.0)

            backstop_price = round(backstop_price, 2)

            # Check if we already have a backstop at roughly this price
            _bs_key = f"ramp:backstop:{symbol}:{side}"
            _existing_raw = self.redis.get(_bs_key) if self.redis else None
            if _existing_raw:
                import json as _bsj
                _existing = _bsj.loads(_existing_raw.decode() if isinstance(_existing_raw, bytes) else str(_existing_raw))
                _old_price = float(_existing.get("price", 0))
                if _old_price > 0 and abs(_old_price - backstop_price) / _old_price < 0.005:
                    return

                # Cancel old backstop
                _old_oid = _existing.get("order_id")
                if _old_oid:
                    try:
                        self.binance.futures_cancel_order(symbol=symbol, orderId=_old_oid)
                    except Exception:
                        pass

            # Place new backstop
            order_side = "SELL" if is_long else "BUY"
            try:
                bs_order = self.binance.futures_create_order(
                    symbol=symbol,
                    side=order_side,
                    positionSide=side.upper(),
                    type="STOP_MARKET",
                    stopPrice=str(backstop_price),
                    quantity=str(abs(position_qty)),
                    reduceOnly="true",
                    workingType="MARK_PRICE",
                    newOrderRespType="RESULT",
                )
                if bs_order and bs_order.get("orderId"):
                    import json as _bsj2
                    self.redis.set(_bs_key, _bsj2.dumps({
                        "order_id": bs_order["orderId"],
                        "price": backstop_price,
                        "ts": time.time(),
                        "leverage": leverage,
                    }), ex=86400)
                    logger.info(
                        "RAMP_EXCHANGE_BACKSTOP | sym=%s side=%s | price=%.2f | "
                        "trail=%.4f dist=%.2f%% lev=%.0fx atr=%.3f%% | oid=%s",
                        symbol, side, backstop_price, trail_trigger_price,
                        backstop_dist_pct, leverage, atr_pct, bs_order["orderId"],
                    )
            except Exception as _bs_err:
                logger.debug("RAMP_BACKSTOP_ORDER_ERR | %s %s | %s", symbol, side, _bs_err)
        except Exception as _bs_outer_err:
            logger.debug("RAMP_BACKSTOP_ERR | %s | %s", symbol, _bs_outer_err)

    def _recalculate_tp_dynamic(self, stop, current_price: float) -> None:
        """Dynamically adjust TP trigger_price based on FULL live market data.

        Called every monitoring tick for TAKE_PROFIT stops.  Uses regime,
        trend, ATR, ADX across ALL timeframes (1m→4h), microstructure,
        and trainer prediction to:
        - WIDEN TP when market is trending in our favour (ride the move)
        - TIGHTEN TP when regime is RANGE/CALM and momentum is fading
        - Boost TP when opposite-side liquidation clusters are close
        - Extend TP toward trainer's current predicted target price
        - Tighten TP on mean-reversion signal from trainer

        All thresholds derived from live data — no static values.
        Adapted for high-leverage Binance Futures (use NATR %, not raw ATR ticks).
        """
        if not self._is_static_tp_stop(stop):
            return
        try:
            entry_px = float(getattr(stop, "entry_price", 0) or 0)
            if entry_px <= 0 or current_price <= 0:
                return
            is_long = stop.side.upper() == "LONG"

            # ── 1. Regime ────────────────────────────────────────
            import json as _json
            regime_raw = self.redis.get(f"regime:{stop.symbol}") if self.redis else None
            if regime_raw:
                regime = _json.loads(
                    regime_raw.decode("utf-8") if isinstance(regime_raw, (bytes, bytearray)) else str(regime_raw)
                )
            else:
                regime = {}
                # region agent log
                try:
                    _ts = int(time.time() * 1000)
                    _symu = str(getattr(stop, "symbol", "") or "").upper().strip()
                    _ttl = None
                    try:
                        _ttl = int(self.redis.ttl(f"regime:{_symu}")) if self.redis else None
                    except Exception:
                        _ttl = None
                    _refresh_attempted = False
                    _refresh_ok = False
                    _refresh_fields = {}
                    # On-demand refresh (throttled): stops must stay dynamic even if trainer isn't
                    # computing regimes for this symbol frequently.
                    try:
                        _rmap = globals().get("_AGENT_TP_REGIME_REFRESH_LAST", {}) or {}
                        try:
                            _r_last = int(_rmap.get(_symu, 0) or 0)
                        except Exception:
                            _r_last = 0
                        if (_ts - _r_last) >= 60_000:
                            _rmap[_symu] = _ts
                            globals()["_AGENT_TP_REGIME_REFRESH_LAST"] = _rmap
                            _refresh_attempted = True
                            from risk.market_regime import compute_regime_from_redis as _crfr
                            _rg = _crfr(self.redis, _symu, timeframes=["1m", "5m", "15m", "1h", "4h"])
                            if isinstance(_rg, dict) and _rg:
                                regime = _rg
                                _refresh_ok = True
                                _refresh_fields = {
                                    "move_regime": _rg.get("move_regime"),
                                    "trend_direction": _rg.get("trend_direction"),
                                    "tf_alignment": _rg.get("tf_alignment"),
                                    "volatility_score": _rg.get("volatility_score"),
                                }
                                try:
                                    _ttl = int(self.redis.ttl(f"regime:{_symu}")) if self.redis else _ttl
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    # Throttle: at most 1/min per symbol to avoid spam.
                    _last_map = globals().get("_AGENT_TP_REGIME_MISS_LAST", {}) or {}
                    try:
                        _last_ts = int(_last_map.get(_symu, 0) or 0)
                    except Exception:
                        _last_ts = 0
                    if (_ts - _last_ts) >= 60_000:
                        _last_map[_symu] = _ts
                        globals()["_AGENT_TP_REGIME_MISS_LAST"] = _last_map
                        _payload = {
                            "sessionId": "53deb7",
                            "id": f"log_{_ts}_tp_regime_missing_{_symu}",
                            "timestamp": _ts,
                            "location": "trading/stealth_stops.py:_recalculate_tp_dynamic",
                            "message": "tp_dynamic_regime_missing",
                            "runId": "post-fix",
                            "hypothesisId": "H5",
                            "data": {
                                "account_id": str(getattr(self, "account_id", "") or ""),
                                "symbol": _symu,
                                "stop_side": str(getattr(stop, "side", "") or ""),
                                "entry_price": float(getattr(stop, "entry_price", 0) or 0),
                                "current_price": float(current_price or 0),
                                "regime_ttl_sec": _ttl,
                                "refresh_attempted": bool(_refresh_attempted),
                                "refresh_ok": bool(_refresh_ok),
                                "refresh": _refresh_fields,
                            },
                        }
                        with open(
                            "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                            "a",
                            encoding="utf-8",
                        ) as _f:
                            _f.write(_json.dumps(_payload, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion
            move_regime = str(regime.get("move_regime", "UNKNOWN")).upper()
            trend_dir = str(regime.get("trend_direction", "NEUTRAL")).upper()
            tf_alignment = float(regime.get("tf_alignment", 0) or 0)
            vol_score = float(regime.get("volatility_score", 0.5) or 0.5)
            liq_imbalance = float(regime.get("liq_imbalance", 0) or 0)

            trend_favours = (
                (is_long and trend_dir in ("BULLISH", "LONG", "UP"))
                or (not is_long and trend_dir in ("BEARISH", "SHORT", "DOWN"))
            )
            strong_alignment = abs(tf_alignment) > 0.4 and (
                (is_long and tf_alignment > 0) or (not is_long and tf_alignment < 0)
            )

            # ── 2. Multi-TF ADX + NATR (% not ticks) — INCLUDE 4h ──────────
            # Key pattern: ind_ta_ADX_14_{tf}, ind_ta_NATR_14_{tf}
            # Also collect xtf_*_adx / xtf_*_atr_14 from the 5m hash (all TFs in one read)
            from risk.intelligent_close_guard import _decode_map
            adx_val = 0.0       # highest ADX across TFs (trend strength)
            adx_4h = 0.0        # 4h ADX specifically (structural trend)
            atr_pct = 0.0       # NATR in % (normalized, not raw ticks)
            atr_4h_pct = 0.0    # 4h NATR for high-leverage scale awareness
            rsi_1h = 50.0       # 1h RSI for trend exhaustion
            rsi_4h = 50.0       # 4h RSI for macro exhaustion
            fast_move = 0.0
            imbalance = 0.0
            p_false_move = 0.0
            spoof_score = 0.0

            # Primary: read each TF hash individually for accuracy
            for tf in ("5m", "15m", "1h", "4h"):
                try:
                    feat_raw = self.redis.hgetall(f"unified_features:{stop.symbol}:{tf}")
                    if not feat_raw:
                        continue
                    feat = _decode_map(feat_raw)
                    # ADX: ind_ta_ADX_14_{tf} — substring match finds it
                    for k, v in feat.items():
                        kl = k.lower()
                        try:
                            fv = float(v)
                        except Exception:
                            continue
                        if "ta_adx_14" in kl and fv > adx_val:
                            adx_val = fv
                            if tf == "4h":
                                adx_4h = fv
                        elif tf == "4h" and "ta_adx_14" in kl:
                            adx_4h = fv
                        # NATR (normalised ATR = %) — avoid raw ATR in price ticks
                        if "ta_natr_14" in kl and fv > 0:
                            if fv > atr_pct:
                                atr_pct = fv
                            if tf == "4h" and fv > atr_4h_pct:
                                atr_4h_pct = fv
                        # RSI
                        if "ta_rsi_14" in kl and fv > 0:
                            if tf == "1h":
                                rsi_1h = fv
                            elif tf == "4h":
                                rsi_4h = fv
                except Exception:
                    continue

            # If NATR not found fall back to xtf cross-TF field in 5m hash
            if atr_pct <= 0:
                try:
                    feat5_raw = self.redis.hgetall(f"unified_features:{stop.symbol}:5m")
                    if feat5_raw:
                        feat5 = _decode_map(feat5_raw)
                        for k, v in feat5.items():
                            kl = k.lower()
                            if "xtf_" in kl and "atr_14" in kl:
                                try:
                                    fv = float(v)
                                    # xtf values are raw ATR ticks — convert to NATR pct
                                    if current_price > 0 and fv > 0:
                                        fv_pct = fv / current_price * 100.0
                                        if fv_pct > atr_pct:
                                            atr_pct = fv_pct
                                except Exception:
                                    continue
                except Exception:
                    pass

            # ── 3. Microstructure from dedicated msnap hash ──────────────────
            try:
                msnap_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{stop.symbol}")
                if msnap_raw:
                    msnap = _decode_map(msnap_raw)
                    fast_move = float(msnap.get("fast_move_score", 0) or 0)
                    # Use multi-TF fast move max for better signal
                    fm_5m = float(msnap.get("fast_move_max_5m", 0) or 0)
                    fm_15m = float(msnap.get("fast_move_max_15m", 0) or 0)
                    fast_move = max(fast_move, fm_5m, fm_15m)
                    imbalance = float(msnap.get("imbalance_5", 0) or 0)
                    p_false_move = float(msnap.get("p_false_move", 0) or 0)
                    spoof_score = float(msnap.get("spoof_score", 0) or 0)
            except Exception:
                pass

            momentum_favours = (
                fast_move > 0.25 or
                (is_long and imbalance > 0.08) or
                (not is_long and imbalance < -0.08)
            )

            # ── 4. Liquidation clusters — read from 5m hash (has all xtf TFs) ──
            # Use multi-TF cascade: 5m immediate + 1h structural + 4h macro
            liq_boost = 0.0
            liq_cascade_boost = 0.0
            try:
                feat5_raw = self.redis.hgetall(f"unified_features:{stop.symbol}:5m")
                if feat5_raw:
                    feat5 = _decode_map(feat5_raw)
                    # Check each TF's liquidation cluster distance
                    for tf_prefix, weight in (("liquidation", 1.0), ("xtf_1m_liquidation", 0.6),
                                               ("xtf_15m_liquidation", 0.8), ("xtf_1h_liquidation", 1.2),
                                               ("xtf_4h_liquidation", 1.5)):
                        if is_long:
                            _ld_k = f"{tf_prefix}_short_distance_pct"
                            _ls_k = f"{tf_prefix}_short_strength"
                        else:
                            _ld_k = f"{tf_prefix}_long_distance_pct"
                            _ls_k = f"{tf_prefix}_long_strength"
                        _ld = float(feat5.get(_ld_k, 100) or 100)
                        _ls = float(feat5.get(_ls_k, 0) or 0)
                        # Normalize strength by symbol price scale
                        _ls_norm = min(1.0, _ls / max(1.0, current_price * 1e4)) if _ls > 0 else 0
                        if _ls_norm <= 0 and _ls > 1e5:
                            _ls_norm = min(1.0, _ls / 1e8)  # absolute fallback
                        if _ld < 2.0 and _ls > 0:
                            _boost = weight * min(0.6, (2.0 - _ld) / 2.0)
                            if _boost > liq_cascade_boost:
                                liq_cascade_boost = _boost
                        if _ld < 3.0 and _ls > 0:
                            _b = min(0.5, (3.0 - _ld) / 3.0 * min(1.0, _ls / 1e7))
                            if _b > liq_boost:
                                liq_boost = _b
            except Exception:
                pass

            # 4h liq_imbalance from regime: strong cascade potential
            if is_long and liq_imbalance > 0.3:
                liq_boost = max(liq_boost, liq_imbalance * 0.4)
            elif not is_long and liq_imbalance < -0.3:
                liq_boost = max(liq_boost, abs(liq_imbalance) * 0.4)

            # ── 5. Live leverage for scale-aware extension ────────────────────
            leverage = 1.0
            try:
                for _acc in (self.account_id, "primary"):
                    _plk = f"positions:live:{_acc}:{stop.symbol.upper()}"
                    _plr = self.redis.hgetall(_plk)
                    if _plr:
                        _pld = _decode_map(_plr)
                        _rl = float(_pld.get("leverage", 0) or 0)
                        if _rl >= 1:
                            leverage = _rl
                            break
            except Exception:
                pass

            # At high leverage, price moves are amplified — be more responsive
            # lev_sensitivity scales TP adjustments proportionally to leverage
            # 75x → 2.3, 50x → 1.8, 20x → 1.2, 10x → 1.0
            lev_sensitivity = min(3.0, max(1.0, 1.0 + (leverage - 10.0) / 50.0))

            # ── 6. Decision: WIDEN, TIGHTEN, or HOLD ──────────────────────────
            old_tp = float(stop.trigger_price)

            # Block widening on spoofed/false moves
            if spoof_score > 0.5 or p_false_move > 0.4:
                return

            # A) TRENDING / IMPULSE regime with favourable trend + ADX > 18 → WIDEN
            # Use 4h ADX when available for structural confirmation
            _adx_thresh = 18.0
            is_trending = move_regime in ("TRENDING", "BREAKOUT", "FAST", "IMPULSE")
            _structural_trend = adx_4h >= 25.0 and trend_favours  # 4h confirms structure
            if is_trending and trend_favours and (adx_val >= _adx_thresh or _structural_trend):
                _eff_adx = max(adx_val, adx_4h)  # use strongest TF's ADX
                if atr_pct <= 0:
                    atr_pct = 0.5  # minimal fallback for high-lev symbols
                strength_mult = min(3.0, max(1.0, _eff_adx / 22.0))

                # Momentum factor: multi-TF fast_move
                momentum_mult = 1.0 + min(0.6, fast_move * 0.6)

                # Liq cascade: nearby opposite liquidations extend profit target
                liq_mult = 1.0 + min(0.8, max(liq_boost, liq_cascade_boost))

                # RSI exhaustion dampening: macro (4h) RSI takes priority
                rsi_damp = 1.0
                _ref_rsi = rsi_4h if adx_4h > 20 else rsi_1h
                if (is_long and _ref_rsi > 78) or (not is_long and _ref_rsi < 22):
                    rsi_damp = 0.5  # severely overbought/oversold
                elif (is_long and _ref_rsi > 72) or (not is_long and _ref_rsi < 28):
                    rsi_damp = 0.75

                # liq_imbalance from regime: macro cash cascade signal
                _regime_liq_factor = 1.0
                if is_long and liq_imbalance > 0.2:
                    _regime_liq_factor = 1.0 + liq_imbalance * 0.5
                elif not is_long and liq_imbalance < -0.2:
                    _regime_liq_factor = 1.0 + abs(liq_imbalance) * 0.5

                extension_pct = (atr_pct * strength_mult * momentum_mult * liq_mult
                                 * rsi_damp * _regime_liq_factor * 0.4)

                # LEVERAGE SCALING FOR WIDEN: At high leverage, price moves are
                # already amplified. Extensions must be SMALLER not larger.
                # 94x → widen_lev_factor=0.11, 20x → 0.50, 10x → 1.0
                _widen_lev_factor = min(1.0, max(0.05, 10.0 / max(1.0, leverage)))

                # ── STRESS-FAVORABLE OVERRIDE: When orderbook/depth/liq signals
                # confirm the move is genuine and in our favor, relax the leverage
                # dampening to let TP expand more aggressively.
                # Conditions: momentum confirms + strong alignment + no spoof/false
                try:
                    from config import ENABLE_STRESS_TP_EXPANSION, STRESS_TP_WIDEN_LEV_FLOOR
                    if ENABLE_STRESS_TP_EXPANSION:
                        _stress_confirms = (
                            momentum_favours
                            and strong_alignment
                            and (fast_move > 0.30 or max(liq_boost, liq_cascade_boost) > 0.15)
                            and p_false_move < 0.25
                            and spoof_score < 0.30
                        )
                        if _stress_confirms:
                            _old_wlf = _widen_lev_factor
                            _widen_lev_factor = max(_widen_lev_factor, float(STRESS_TP_WIDEN_LEV_FLOOR))
                            if _widen_lev_factor > _old_wlf:
                                logger.info(
                                    "STRESS_TP_EXPANSION | sym=%s side=%s | widen_lev_factor %.3f→%.3f | "
                                    "fm=%.2f liq=%.2f imbal=%.2f align=%.2f spoof=%.2f false=%.2f lev=%.0fx",
                                    stop.symbol, stop.side, _old_wlf, _widen_lev_factor,
                                    fast_move, max(liq_boost, liq_cascade_boost), imbalance,
                                    tf_alignment, spoof_score, p_false_move, leverage,
                                )
                except Exception:
                    pass

                extension_pct *= _widen_lev_factor

                if is_long:
                    new_tp = max(old_tp, current_price * (1.0 + extension_pct / 100.0))
                else:
                    new_tp = min(old_tp, current_price * (1.0 - extension_pct / 100.0))

                # MAX TP ROE CAP: Never push TP beyond max_tp_roe % ROE
                _max_tp_roe = 200.0  # cap TP at 200% ROE (was 85% — prevented capturing big moves)
                _max_tp_dist_pct = _max_tp_roe / max(1.0, leverage)
                if is_long:
                    _tp_cap = entry_px * (1.0 + _max_tp_dist_pct / 100.0)
                    new_tp = min(new_tp, _tp_cap)
                else:
                    _tp_cap = entry_px * (1.0 - _max_tp_dist_pct / 100.0)
                    new_tp = max(new_tp, _tp_cap)

                if abs(new_tp - old_tp) / max(old_tp, 1e-12) > 0.001:
                    stop.trigger_price = new_tp
                    logger.info(
                        "DYNAMIC_TP_WIDEN | sym=%s side=%s | old_tp=%.6f new_tp=%.6f | "
                        "regime=%s adx=%.1f adx4h=%.1f natr=%.3f%% ext=%.3f%% "
                        "fm=%.2f liq=%.2f rsi1h=%.0f rsi4h=%.0f lev=%.0fx | trend=%s align=%.2f",
                        stop.symbol, stop.side, old_tp, new_tp,
                        move_regime, adx_val, adx_4h, atr_pct, extension_pct,
                        fast_move, liq_boost, rsi_1h, rsi_4h, leverage, trend_dir, tf_alignment,
                    )

            # B) RANGE/CALM regime with fading momentum → TIGHTEN
            # Use ROE-aware PnL threshold (high leverage = smaller price move = big profit)
            elif move_regime in ("RANGE", "CALM", "NORMAL") and not momentum_favours and adx_val < 22:
                _price_pnl_pct = (
                    (current_price - entry_px) / entry_px * 100 if is_long
                    else (entry_px - current_price) / entry_px * 100
                )

                _adaptive_stp_enabled = True
                try:
                    from config import ADAPTIVE_STEALTH_TP_ENABLED
                    _adaptive_stp_enabled = bool(ADAPTIVE_STEALTH_TP_ENABLED)
                except Exception:
                    pass

                if _adaptive_stp_enabled and atr_pct > 0:
                    # For high-leverage: tighten when even a fraction of one ATR is captured
                    # At 75x, 0.1% price = 7.5% ROE — worth locking in sooner
                    _lev_factor = max(0.3, min(1.0, 10.0 / max(1.0, leverage)))  # 75x→0.13, 20x→0.5, 10x→1.0
                    _tighten_pnl_min = max(0.15, atr_pct * 0.6 * _lev_factor)  # Raised floor from 0.05 to 0.15, factor from 0.4 to 0.6
                    _adx_factor = max(0.5, adx_val / 22.0)
                    _tighten_pnl_min = max(0.10, _tighten_pnl_min * _adx_factor)  # Raised floor from 0.03 to 0.10
                else:
                    _tighten_pnl_min = 1.0 / max(1.0, leverage / 10.0)  # Raised from 0.5 to 1.0

                if _price_pnl_pct > _tighten_pnl_min:
                    if is_long:
                        _tp_dist = (old_tp - current_price) / current_price * 100
                    else:
                        _tp_dist = (current_price - old_tp) / current_price * 100

                    # Leverage-scale the ATR floor: at high leverage, TP distances
                    # are much smaller than raw ATR, so the floor must scale down
                    _b_lev_scale = min(1.0, max(0.05, 10.0 / max(1.0, leverage)))
                    _b_atr_floor = atr_pct * 0.3 * _b_lev_scale
                    if _tp_dist > _b_atr_floor:
                        _tighten_pct = min(0.35, (22.0 - adx_val) / 44.0) * _tp_dist * lev_sensitivity
                        if is_long:
                            new_tp = old_tp - current_price * (_tighten_pct / 100.0)
                            new_tp = max(new_tp, current_price * 1.0005)
                        else:
                            new_tp = old_tp + current_price * (_tighten_pct / 100.0)
                            new_tp = min(new_tp, current_price * 0.9995)

                        if abs(new_tp - old_tp) / max(old_tp, 1e-12) > 0.001:
                            stop.trigger_price = new_tp
                            logger.info(
                                "DYNAMIC_TP_TIGHTEN | sym=%s side=%s | old_tp=%.6f new_tp=%.6f | "
                                "regime=%s adx=%.1f pnl=%.3f%% tighten=%.3f%% natr=%.3f%% "
                                "min_pnl=%.3f%% lev=%.0fx",
                                stop.symbol, stop.side, old_tp, new_tp,
                                move_regime, adx_val, _price_pnl_pct, _tighten_pct,
                                atr_pct, _tighten_pnl_min, leverage,
                            )

            # C) Building momentum (strong alignment, microstructure confirms) → mild widen
            elif trend_favours and strong_alignment and momentum_favours and adx_val >= 15:
                if atr_pct > 0:
                    # Scale extension DOWN for high leverage
                    _mild_lev_scale = min(1.0, max(0.05, 10.0 / max(1.0, leverage)))
                    _mild_ext = atr_pct * 0.35 * _mild_lev_scale
                    if is_long:
                        new_tp = max(old_tp, current_price * (1.0 + _mild_ext / 100.0))
                    else:
                        new_tp = min(old_tp, current_price * (1.0 - _mild_ext / 100.0))
                    # Max TP ROE cap
                    _mc_max_dist = 85.0 / max(1.0, leverage)
                    if is_long:
                        new_tp = min(new_tp, entry_px * (1.0 + _mc_max_dist / 100.0))
                    else:
                        new_tp = max(new_tp, entry_px * (1.0 - _mc_max_dist / 100.0))
                    if abs(new_tp - old_tp) / max(old_tp, 1e-12) > 0.001:
                        stop.trigger_price = new_tp
                        logger.info(
                            "DYNAMIC_TP_MILD_WIDEN | sym=%s side=%s | old=%.6f new=%.6f | "
                            "regime=%s adx=%.1f natr=%.3f%% align=%.2f lev=%.0fx",
                            stop.symbol, stop.side, old_tp, new_tp,
                            move_regime, adx_val, atr_pct, tf_alignment, leverage,
                        )

            # ── D) Trainer-prediction TP attractor — refreshed every tick ────────
            # Reads individual TF predictions PLUS consensus from get_trainer_view.
            # Uses the best-confidence directional TF target as anchor.
            #
            # D1 — ALIGNED trainer (agrees with position):
            #   Pull TP toward trainer's target. Blend scales with:
            #     conf × regime_factor × adx_factor × lev_sensitivity → max 90%
            #   4h-confirmed trends get maximum extension.
            #
            # D2 — OPPOSING trainer (RANGE/CALM → mean-reversion):
            #   Tighten TP to capture profit before price reverts.
            #   Applies when trainer confidently disagrees + ranging regime.
            try:
                from risk.trainer_alignment import get_trainer_view
                _tv = get_trainer_view(self.redis, stop.symbol)

                # Also read per-TF predictions directly — get_trainer_view may
                # under-weight strong individual TF signals
                _best_tgt = 0.0
                _best_conf = 0.0
                _best_dir = ""
                try:
                    for _tf in ("4h", "1h", "15m", "5m"):
                        _ph = self.redis.hgetall(f"prediction:{stop.symbol}:{_tf}")
                        if not _ph:
                            continue
                        _pd = _decode_map(_ph)
                        _pdir = str(_pd.get("direction", "") or "").upper()
                        _pconf = float(_pd.get("confidence", 0) or 0)
                        _ptgt = float(_pd.get("price_target", 0) or 0)
                        if _pconf > _best_conf and _ptgt > 0 and _pdir:
                            _best_conf = _pconf
                            _best_tgt = _ptgt
                            _best_dir = _pdir
                except Exception:
                    pass

                # Merge: use consensus if conf >= 0.55, else fall back to best per-TF
                if _tv and _tv.is_directional and _tv.consensus_confidence >= 0.55:
                    _tgt = _tv.best_target_price if _tv.best_target_price > 0 else _best_tgt
                    _tdir = _tv.consensus_direction.upper()
                    _tconf = float(_tv.consensus_confidence)
                    _tv_regime = str(_tv.move_regime or move_regime).upper()
                elif _best_conf >= 0.55 and _best_tgt > 0:
                    _tgt = _best_tgt
                    _tdir = _best_dir
                    _tconf = _best_conf
                    _tv_regime = move_regime
                else:
                    _tgt = 0.0
                    _tdir = ""
                    _tconf = 0.0
                    _tv_regime = move_regime

                if _tgt > 0 and _tdir:
                    _current_tp = float(stop.trigger_price)

                    _trainer_aligns = (
                        (is_long and _tdir in ("LONG", "BULLISH", "UP"))
                        or (not is_long and _tdir in ("SHORT", "BEARISH", "DOWN"))
                    )
                    _trainer_opposes = (
                        (is_long and _tdir in ("SHORT", "BEARISH", "DOWN"))
                        or (not is_long and _tdir in ("LONG", "BULLISH", "UP"))
                    )

                    # ── D1: Pull TP toward trainer's target ──────────────────
                    if _trainer_aligns and _tconf >= 0.55:
                        _tp_beyond = (
                            (is_long and _tgt > _current_tp)
                            or (not is_long and _tgt < _current_tp)
                        )
                        if _tp_beyond:
                            # Regime scaling
                            _d1_regime_f = (
                                1.6 if _tv_regime in ("TRENDING", "BREAKOUT", "FAST", "IMPULSE")
                                else 1.1
                            )
                            # ADX scaling: use max ADX across TFs
                            _d1_adx_f = min(1.6, max(0.75, max(adx_val, adx_4h) / 22.0))
                            # Leverage scaling: at high leverage, be CONSERVATIVE
                            # to prevent TP from running away to unreachable levels
                            _d1_lev_f = max(0.5, min(1.0, 10.0 / max(1.0, leverage)))
                            # Final blend: cap at 70% to never fully collapse distance
                            _blend = min(0.70, _tconf * 0.75 * _d1_regime_f * _d1_adx_f * _d1_lev_f)
                            _new_tp = _current_tp + (_tgt - _current_tp) * _blend
                            # Safety: never pull SHORT TP above price or LONG TP below price
                            if is_long:
                                _new_tp = max(_new_tp, current_price * 1.0002)
                            else:
                                _new_tp = min(_new_tp, current_price * 0.9998)
                            # MAX TP ROE CAP: Trainer target may be unrealistic at high leverage
                            _d1_max_tp_roe = 85.0
                            _d1_max_dist = _d1_max_tp_roe / max(1.0, leverage)
                            if is_long:
                                _d1_cap = entry_px * (1.0 + _d1_max_dist / 100.0)
                                _new_tp = min(_new_tp, _d1_cap)
                            else:
                                _d1_cap = entry_px * (1.0 - _d1_max_dist / 100.0)
                                _new_tp = max(_new_tp, _d1_cap)
                            if abs(_new_tp - _current_tp) / max(_current_tp, 1e-12) > 0.0005:
                                stop.trigger_price = _new_tp
                                logger.info(
                                    "DYNAMIC_TP_TRAINER_EXTEND | sym=%s side=%s | "
                                    "old_tp=%.6f new_tp=%.6f trainer_tgt=%.6f | "
                                    "conf=%.2f blend=%.2f dir=%s regime=%s adx=%.1f adx4h=%.1f lev=%.0fx",
                                    stop.symbol, stop.side, _current_tp, _new_tp, _tgt,
                                    _tconf, _blend, _tdir, _tv_regime, adx_val, adx_4h, leverage,
                                )

                    # ── D2: Mean-reversion tighten (DATA-DRIVEN) ────────────
                    # Fire when: trainer clearly opposes + regime supports
                    # ENHANCED: Consults live microstructure, ADX trend strength,
                    # liquidation proximity, and ATR-based cumulative cap before
                    # overriding the data-driven TP.  All variables below are
                    # already computed from live market data in sections 1-5 above.
                    elif _trainer_opposes and _tconf >= 0.60:
                        _d2_ranging = _tv_regime in ("RANGE", "CALM", "NORMAL")
                        _d2_high_conf_reversal = _tconf >= 0.80
                        if _d2_ranging or _d2_high_conf_reversal:
                            _price_pnl = (
                                (current_price - entry_px) / entry_px * 100 if is_long
                                else (entry_px - current_price) / entry_px * 100
                            )
                            # APRIL PLAN v3: Use config-driven min profit (price-move based)
                            from config import (EXIT_MR_TIGHTEN_MIN_PROFIT_PCT, EXIT_MR_TIGHTEN_MAX_BLEND,
                                                EXIT_MR_TIGHTEN_COOLDOWN_SEC, EXIT_MR_TIGHTEN_MIN_TP_DIST_PCT,
                                                APRIL_PLAN_EXITS_ENABLED)
                            _d2_min_profit = EXIT_MR_TIGHTEN_MIN_PROFIT_PCT if APRIL_PLAN_EXITS_ENABLED else max(0.02, max(0.05, min(0.3, atr_pct * 0.2)) * max(0.3, 10.0 / max(1.0, leverage)))
                            # Check cooldown (prevent ratcheting every 30s tick)
                            _mr_cd_key = f"{stop.symbol}:{stop.side}:mr_tighten_ts"
                            _mr_last_ts = float(getattr(self, '_mr_tighten_ts', {}).get(_mr_cd_key, 0))
                            _mr_cd_ok = (time.time() - _mr_last_ts) >= EXIT_MR_TIGHTEN_COOLDOWN_SEC if APRIL_PLAN_EXITS_ENABLED else True
                            if _price_pnl > _d2_min_profit and _mr_cd_ok:
                                _mr_max = EXIT_MR_TIGHTEN_MAX_BLEND if APRIL_PLAN_EXITS_ENABLED else 0.55
                                _mr_blend = min(_mr_max, _tconf * 0.45 * lev_sensitivity)

                                # ── DATA-DRIVEN DAMPENING (uses live market data) ──

                                # 1. Orderbook imbalance: if depth supports position, dampen
                                #    imbalance > 0 = buy pressure, < 0 = sell pressure
                                _micro_supports_pos = (
                                    (is_long and imbalance > 0.15) or
                                    (not is_long and imbalance < -0.15)
                                )
                                _d2_micro_damp = 1.0
                                if _micro_supports_pos:
                                    _d2_micro_damp = max(0.15, 1.0 - abs(imbalance) * 1.2)
                                    _mr_blend *= _d2_micro_damp

                                # 2. Spoof / false-move: don't tighten on fake moves
                                if p_false_move > 0.3 or spoof_score > 0.4:
                                    _mr_blend *= 0.2

                                # 3. Trend regime + ADX: stronger trend → less MR tighten
                                #    ADX 25 → ×0.5, ADX 40 → ×0.2 (data-driven scaling)
                                if _tv_regime in ("TRENDING", "BREAKOUT", "FAST", "IMPULSE"):
                                    _eff_adx = max(adx_val, adx_4h)
                                    _adx_damp = max(0.10, 1.0 - _eff_adx / 50.0)
                                    _mr_blend *= _adx_damp

                                # 4. Liquidation clusters favor position: dampen
                                _eff_liq = max(liq_boost, liq_cascade_boost)
                                if _eff_liq > 0.1:
                                    _mr_blend *= max(0.3, 1.0 - _eff_liq)

                                # 5. ATR-based cumulative cap: TP must stay ≥ ATR floor
                                #    from current price.  Prevents ratchet to near-entry.
                                #    LEVERAGE-SCALED: At high leverage, raw ATR floor is
                                #    unreachable (e.g., 3.2% at 66x = 212% ROE).
                                #    Scale floor so it stays within realistic ROE bounds.
                                _lev_atr_scale = min(1.0, max(0.05, 10.0 / max(1.0, leverage)))
                                _min_tp_dist_pct = max(0.05, atr_pct * 1.5 * _lev_atr_scale) if atr_pct > 0 else 0.10
                                # APRIL PLAN v3: Enforce hard minimum TP distance from config
                                if APRIL_PLAN_EXITS_ENABLED:
                                    _min_tp_dist_pct = max(_min_tp_dist_pct, EXIT_MR_TIGHTEN_MIN_TP_DIST_PCT)
                                # Ensure floor doesn't exceed 70% of liquidation distance
                                _liq_dist_tp = 100.0 / max(1.0, leverage)
                                _min_tp_dist_pct = min(_min_tp_dist_pct, _liq_dist_tp * 0.70)
                                _current_dist_pct = abs(_current_tp - current_price) / max(current_price, 1e-12) * 100
                                if _current_dist_pct < _min_tp_dist_pct:
                                    logger.info(
                                        "D2_TIGHTEN_ATR_CAPPED | sym=%s side=%s | "
                                        "tp_dist=%.3f%% < atr_min=%.3f%% | atr=%.3f%% "
                                        "trainer=%s conf=%.2f regime=%s",
                                        stop.symbol, stop.side, _current_dist_pct,
                                        _min_tp_dist_pct, atr_pct, _tdir, _tconf, _tv_regime,
                                    )
                                    _mr_blend = 0.0  # TP already at ATR floor

                                # Skip if dampening reduced blend below meaningful threshold
                                if _mr_blend >= 0.02:
                                    if is_long:
                                        _mr_target = current_price * 1.0003
                                        _new_tp = _current_tp + (_mr_target - _current_tp) * _mr_blend
                                        _new_tp = max(_new_tp, current_price * 1.0002)
                                        _new_tp = min(_new_tp, _current_tp)  # only tighten
                                    else:
                                        _mr_target = current_price * 0.9997
                                        _new_tp = _current_tp + (_mr_target - _current_tp) * _mr_blend
                                        _new_tp = min(_new_tp, current_price * 0.9998)
                                        _new_tp = max(_new_tp, _current_tp)  # only tighten
                                    if abs(_new_tp - _current_tp) / max(_current_tp, 1e-12) > 0.0005:
                                        stop.trigger_price = _new_tp
                                        # APRIL PLAN: Track cooldown timestamp
                                        if not hasattr(self, '_mr_tighten_ts'):
                                            self._mr_tighten_ts = {}
                                        self._mr_tighten_ts[f"{stop.symbol}:{stop.side}:mr_tighten_ts"] = time.time()
                                        logger.info(
                                            "DYNAMIC_TP_TRAINER_MR_TIGHTEN | sym=%s side=%s | "
                                            "old_tp=%.6f new_tp=%.6f | trainer=%s conf=%.2f "
                                            "blend=%.2f regime=%s pnl=%.3f%% lev=%.0fx | "
                                            "imb=%.3f adx=%.1f/%.1f liq=%.2f micro_damp=%.2f",
                                            stop.symbol, stop.side, _current_tp, _new_tp,
                                            _tdir, _tconf, _mr_blend, _tv_regime, _price_pnl, leverage,
                                            imbalance, adx_val, adx_4h, _eff_liq, _d2_micro_damp,
                                        )
            except Exception:
                pass

        except Exception as e:
            logger.debug("DYNAMIC_TP_RECALC_ERR | %s | %s", stop.symbol, e)

    def _recalculate_sl_dynamic(self, stop, current_price: float) -> None:
        """Dynamically adjust SL trigger_price based on live market data.

        Called every monitoring tick for non-trailing STOP_LOSS stops.
        Leverage-aware: all adjustments respect the liquidation distance.

        Logic:
        - WIDEN SL when position is profitable AND regime trends in our favor
          (give winning trade more room to breathe)
        - TIGHTEN SL (move toward breakeven) when position is profitable in
          RANGE/CALM regime (lock in profit)
        - Never widen SL beyond initial value or beyond 80% of liq distance
        - Never move SL to create MORE risk than initial placement
        """
        if stop.stop_type != "STOP_LOSS":
            return
        if "TRAIL" in str(stop.reason or "").upper():
            return  # Trailing SL has its own compression logic
        try:
            entry_px = float(getattr(stop, "entry_price", 0) or 0)
            if entry_px <= 0 or current_price <= 0:
                return
            is_long = stop.side.upper() == "LONG"

            # ── 1. Position PnL ──────────────────────────────────
            if is_long:
                price_pnl_pct = (current_price - entry_px) / entry_px * 100.0
            else:
                price_pnl_pct = (entry_px - current_price) / entry_px * 100.0

            # Only adjust SL when position is in profit
            if price_pnl_pct <= 0:
                return

            # ── 2. Get leverage ──────────────────────────────────
            leverage = 1.0
            try:
                from risk.intelligent_close_guard import _decode_map
                for _acc in (self.account_id, "primary"):
                    _plk = f"positions:live:{_acc}:{stop.symbol.upper()}"
                    _plr = self.redis.hgetall(_plk) if self.redis else None
                    if _plr:
                        _pld = _decode_map(_plr)
                        _rl = float(_pld.get("leverage", 0) or 0)
                        if _rl >= 1:
                            leverage = _rl
                            break
            except Exception:
                pass

            roe_pct = price_pnl_pct * leverage
            _liq_dist_pct = 100.0 / max(1.0, leverage)

            # ── 3. Regime + trend ────────────────────────────────
            import json as _json
            regime_raw = self.redis.get(f"regime:{stop.symbol}") if self.redis else None
            if not regime_raw:
                return
            regime = _json.loads(
                regime_raw.decode("utf-8") if isinstance(regime_raw, (bytes, bytearray)) else str(regime_raw)
            )
            move_regime = str(regime.get("move_regime", "UNKNOWN")).upper()
            trend_dir = str(regime.get("trend_direction", "NEUTRAL")).upper()

            trend_favours = (
                (is_long and trend_dir in ("BULLISH", "LONG", "UP"))
                or (not is_long and trend_dir in ("BEARISH", "SHORT", "DOWN"))
            )

            old_sl = float(stop.trigger_price)

            # ── 4a. BREAKEVEN MOVE: When profitable enough, move SL to breakeven
            # Threshold: >= 15% ROE → move SL to entry + small buffer
            if roe_pct >= 15.0:
                _buffer_pct = 0.02  # 0.02% price buffer above/below entry
                if is_long:
                    _be_sl = entry_px * (1.0 + _buffer_pct / 100.0)
                    if _be_sl > old_sl:  # Only move SL UP for longs
                        stop.trigger_price = _be_sl
                        logger.info(
                            "DYNAMIC_SL_BREAKEVEN | sym=%s side=%s | old=%.6f new=%.6f | "
                            "roe=%.1f%% pnl=%.3f%%p lev=%.0fx",
                            stop.symbol, stop.side, old_sl, _be_sl,
                            roe_pct, price_pnl_pct, leverage,
                        )
                else:
                    _be_sl = entry_px * (1.0 - _buffer_pct / 100.0)
                    if _be_sl < old_sl:  # Only move SL DOWN for shorts
                        stop.trigger_price = _be_sl
                        logger.info(
                            "DYNAMIC_SL_BREAKEVEN | sym=%s side=%s | old=%.6f new=%.6f | "
                            "roe=%.1f%% pnl=%.3f%%p lev=%.0fx",
                            stop.symbol, stop.side, old_sl, _be_sl,
                            roe_pct, price_pnl_pct, leverage,
                        )

            # ── 4b. PROFIT LOCK: When very profitable (>= 30% ROE),
            #    move SL to lock in a portion of the profit
            elif roe_pct >= 30.0:
                # Lock in 40% of current price profit
                _lock_pct = price_pnl_pct * 0.40
                if is_long:
                    _lock_sl = entry_px * (1.0 + _lock_pct / 100.0)
                    if _lock_sl > old_sl:
                        stop.trigger_price = _lock_sl
                        logger.info(
                            "DYNAMIC_SL_PROFIT_LOCK | sym=%s side=%s | old=%.6f new=%.6f | "
                            "roe=%.1f%% locked=%.3f%%p lev=%.0fx regime=%s",
                            stop.symbol, stop.side, old_sl, _lock_sl,
                            roe_pct, _lock_pct, leverage, move_regime,
                        )
                else:
                    _lock_sl = entry_px * (1.0 - _lock_pct / 100.0)
                    if _lock_sl < old_sl:
                        stop.trigger_price = _lock_sl
                        logger.info(
                            "DYNAMIC_SL_PROFIT_LOCK | sym=%s side=%s | old=%.6f new=%.6f | "
                            "roe=%.1f%% locked=%.3f%%p lev=%.0fx regime=%s",
                            stop.symbol, stop.side, old_sl, _lock_sl,
                            roe_pct, _lock_pct, leverage, move_regime,
                        )

        except Exception as e:
            logger.debug("DYNAMIC_SL_RECALC_ERR | %s | %s", stop.symbol, e)

    def _get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            now = time.time()
            cache_ts = float(self._exchange_info_cache.get("ts") or 0.0)
            if (now - cache_ts) > float(self._exchange_info_ttl_sec or 300) or not self._exchange_info_cache.get("symbols"):
                info = self.binance.futures_exchange_info()
                symbols = {}
                for item in info.get("symbols", []):
                    sym = item.get("symbol")
                    if sym:
                        symbols[sym] = item
                self._exchange_info_cache = {"ts": now, "symbols": symbols}
            return (self._exchange_info_cache.get("symbols") or {}).get(symbol)
        except Exception:
            return None

    def _extract_filters(self, symbol: str) -> Tuple[float, float, Optional[int], Optional[int]]:
        tick_size = 0.0
        step_size = 0.0
        price_precision = None
        qty_precision = None
        info = self._get_symbol_info(symbol)
        if info:
            try:
                price_precision = int(info.get("pricePrecision")) if info.get("pricePrecision") is not None else None
            except Exception:
                price_precision = None
            try:
                qty_precision = int(info.get("quantityPrecision")) if info.get("quantityPrecision") is not None else None
            except Exception:
                qty_precision = None
            for f in info.get("filters", []) or []:
                ftype = f.get("filterType")
                if ftype == "PRICE_FILTER":
                    try:
                        tick_size = float(f.get("tickSize") or 0.0)
                    except Exception:
                        tick_size = 0.0
                elif ftype == "LOT_SIZE":
                    try:
                        step_size = float(f.get("stepSize") or 0.0)
                    except Exception:
                        step_size = 0.0
        return tick_size, step_size, price_precision, qty_precision

    def _quantize_qty(self, qty: float, step_size: float, qty_precision: Optional[int]) -> float:
        try:
            if step_size and step_size > 0:
                steps = math.floor(float(qty) / step_size)
                qty = steps * step_size
            if qty_precision is not None:
                qty = float(f"{float(qty):.{int(qty_precision)}f}")
        except Exception:
            return float(qty or 0.0)
        return float(qty or 0.0)

    def _quantize_price(self, price: float, tick_size: float, side: str, price_precision: Optional[int]) -> float:
        try:
            if tick_size and tick_size > 0:
                if str(side).upper() == "BUY":
                    steps = math.ceil(float(price) / tick_size)
                else:
                    steps = math.floor(float(price) / tick_size)
                price = steps * tick_size
            if price_precision is not None:
                price = float(f"{float(price):.{int(price_precision)}f}")
        except Exception:
            return float(price or 0.0)
        return float(price or 0.0)

    def _prepare_order_params(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> Tuple[Optional[float], Optional[float]]:
        tick_size, step_size, price_precision, qty_precision = self._extract_filters(symbol)
        qty = self._quantize_qty(float(quantity or 0.0), step_size, qty_precision)
        if qty <= 0:
            logger.warning(f"[STEALTH-ORDER-SKIP] {symbol} {side} qty too small after quantize: {quantity}")
            return None, None
        if price is None:
            return None, qty
        px = self._quantize_price(float(price or 0.0), tick_size, side, price_precision)
        if px <= 0:
            logger.warning(f"[STEALTH-ORDER-SKIP] {symbol} {side} price invalid after quantize: {price}")
            return None, None
        return px, qty

    def _place_limit_order(
        self,
        symbol: str,
        order_side: str,
        position_side: str,
        price: float,
        quantity: float,
        time_in_force: str,
        reduce_only: bool = True,
    ) -> Optional[Dict]:
        px, qty = self._prepare_order_params(symbol, order_side, quantity, price)
        if px is None or qty is None:
            return None
        try:
            params = dict(
                symbol=symbol,
                side=order_side,
                positionSide=position_side,
                type='LIMIT',
                price=px,
                quantity=qty,
                timeInForce=time_in_force,
            )
            if reduce_only:
                params["reduceOnly"] = True
            order = self.binance.futures_create_order(**params)
            return order
        except Exception as e:
            if reduce_only and ('-1106' in str(e) or 'reduceOnly' in str(e).lower()):
                # If the exchange rejects reduceOnly, only retry without it when we're sure
                # this order cannot increase exposure (close direction + qty <= current position).
                if not self._safe_allow_no_reduceonly(symbol, order_side, position_side, qty):
                    raise
                try:
                    params = dict(
                        symbol=symbol,
                        side=order_side,
                        positionSide=position_side,
                        type='LIMIT',
                        price=px,
                        quantity=qty,
                        timeInForce=time_in_force,
                    )
                    return self.binance.futures_create_order(**params)
                except Exception:
                    raise
            raise

    def _safe_allow_no_reduceonly(self, symbol: str, order_side: str, position_side: str, qty: float) -> bool:
        """Return True only when retrying without reduceOnly cannot increase exposure."""
        try:
            ps = str(position_side or "").upper().strip()
            oside = str(order_side or "").upper().strip()
            if ps not in ("LONG", "SHORT"):
                return False
            if (ps == "LONG" and oside != "SELL") or (ps == "SHORT" and oside != "BUY"):
                return False

            positions = self.binance.futures_position_information(symbol=symbol)
            for pos in positions or []:
                try:
                    amt = float(pos.get("positionAmt", 0) or 0)
                except Exception:
                    amt = 0.0
                if ps == "LONG" and amt > 0:
                    return float(qty or 0.0) <= abs(float(amt)) + 1e-9
                if ps == "SHORT" and amt < 0:
                    return float(qty or 0.0) <= abs(float(amt)) + 1e-9
        except Exception:
            return False
        return False

    def _is_stress_mode(self, symbol: str) -> bool:
        """Best-effort stress detector for guardrails (does NOT block protective exits).

        Used only to freeze hedge take-profit trims during stress windows.
        """
        # Kill switch / halt is treated as stress.
        try:
            from risk.kill_switch import get_kill_switch
            active, data = get_kill_switch(self.redis, account=self.account_id, symbol=symbol) if self.redis else (False, None)
            if active:
                code = str((data or {}).get("code") or (data or {}).get("reason") or "").upper()
                if code.startswith("HALT-") or code in ("HALT", "KILL_SWITCH_ACTIVE"):
                    return True
        except Exception:
            pass

        # Operator override (runtime flag) can force a stress mode.
        try:
            from utils.runtime_flags import get_flag_env
            forced = get_flag_env(self.redis, "FORCE_PORTFOLIO_MODE", None) if self.redis else None
            if forced and str(forced).upper().strip() in ("STRESS", "EMERGENCY"):
                return True
        except Exception:
            pass

        return False

    def _hedge_tp_guard(self, symbol: str, requested_qty: float, mark_price: float) -> Tuple[bool, float, str, Dict[str, Any]]:
        """Guardrail for TAKE_PROFIT closes on SHORT hedge legs.

        Returns: (allow, adjusted_qty, reason, meta)
        """
        meta: Dict[str, Any] = {
            "symbol": symbol,
            "mark_price": float(mark_price or 0.0),
            "requested_qty": float(requested_qty or 0.0),
        }
        try:
            from config import (
                HEDGE_TP_GUARD_ENABLED,
                STRESS_FREEZE_TP_ON_HEDGE,
                HEDGE_TP_LIQ_BUFFER_BPS,
                MIN_HEDGE_COVERAGE,
            )
        except Exception:
            HEDGE_TP_GUARD_ENABLED = True
            STRESS_FREEZE_TP_ON_HEDGE = True
            HEDGE_TP_LIQ_BUFFER_BPS = 120.0
            MIN_HEDGE_COVERAGE = 0.70

        if not HEDGE_TP_GUARD_ENABLED:
            return True, float(requested_qty or 0.0), "GUARD_DISABLED", meta

        try:
            positions = self.binance.futures_position_information(symbol=symbol)
        except Exception as e:
            meta["pos_fetch_err"] = str(e)
            # Can't validate -> allow but don't change qty.
            return True, float(requested_qty or 0.0), "NO_POS_SNAPSHOT", meta

        long_qty = 0.0
        short_qty = 0.0
        liq_long = None

        for pos in positions or []:
            try:
                amt = float(pos.get("positionAmt", 0) or 0.0)
            except Exception:
                amt = 0.0
            if amt > 0:
                long_qty = abs(amt)
                try:
                    liq_long = float(pos.get("liquidationPrice", 0) or 0.0)
                except Exception:
                    liq_long = None
            elif amt < 0:
                short_qty = abs(amt)

        meta.update({"long_qty": long_qty, "short_qty": short_qty, "liq_long": liq_long})
        if long_qty <= 0 or short_qty <= 0:
            return True, float(requested_qty or 0.0), "OK_NO_OPPOSITE_LEG", meta

        # Stress freeze: never trim hedge during stress windows.
        # Only freeze if stress is genuinely active (kill switch / halt).
        # Previously this was permanently blocking all hedge TPs.
        if STRESS_FREEZE_TP_ON_HEDGE and self._is_stress_mode(symbol):
            logger.debug(
                "STRESS_FREEZE_CHECK | sym=%s | stress=True | action=FREEZE_TP",
                symbol,
            )
            return False, 0.0, "STEALTH_TP_SKIPPED_STRESS_FREEZE", meta

        # Liquidation buffer: block when LONG leg is still too close to liquidation.
        liq_bps = None
        try:
            mp = float(mark_price or 0.0)
            lp = float(liq_long or 0.0)
            if mp > 0 and lp > 0:
                liq_bps = (mp - lp) / mp * 10000.0
        except Exception:
            liq_bps = None
        meta["liq_bps_long"] = liq_bps
        if liq_bps is not None and float(liq_bps) < float(HEDGE_TP_LIQ_BUFFER_BPS):
            return False, 0.0, f"BLOCK_HEDGE_TP_LIQ_BUFFER", meta

        # Hedge floor: keep remaining short >= long * MIN_HEDGE_COVERAGE
        min_short_needed = float(long_qty) * max(0.0, float(MIN_HEDGE_COVERAGE))
        max_close_allowed = max(0.0, float(short_qty) - float(min_short_needed))
        meta.update({"min_short_needed": min_short_needed, "max_close_allowed": max_close_allowed})
        if max_close_allowed <= 0:
            return False, 0.0, "BLOCK_HEDGE_TP_HEDGE_FLOOR", meta

        adj = min(float(requested_qty or 0.0), float(max_close_allowed))
        if adj <= 0:
            return False, 0.0, "BLOCK_HEDGE_TP_ZERO", meta
        if adj + 1e-12 < float(requested_qty or 0.0):
            return True, adj, "CAP_HEDGE_TP", meta
        return True, adj, "OK", meta
    
    def _fetch_market_features(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch unified features from Redis for data-driven stop calculations.
        This is the PRIMARY source - config values are FALLBACK only.
        """
        features = {}
        if not self.redis:
            logger.debug(f"[ADAPTIVE-STOPS] No Redis client, using config defaults")
            return features
        
        try:
            def _decode_map(m: Dict[str, Any]) -> Dict[str, Any]:
                if not m:
                    return {}
                try:
                    k0 = next(iter(m.keys()))
                except Exception:
                    return {}
                if isinstance(k0, (bytes, bytearray)):
                    out = {}
                    for k, v in (m or {}).items():
                        try:
                            kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                        except Exception:
                            kk = str(k)
                        vv = v
                        try:
                            vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                        except Exception:
                            vv = v
                        out[kk] = vv
                    return out
                return m

            def _maybe_parse_data_field(m: Dict[str, Any]) -> Dict[str, Any]:
                """
                Some producers store unified features as a Redis hash with a single 'data' JSON field.
                Normalize that so stop logic can actually see 200+ fields.
                """
                m = _decode_map(m)
                try:
                    raw = m.get("data")
                    if not raw:
                        return m
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="ignore")
                    if isinstance(raw, str):
                        import json as _json
                        obj = _json.loads(raw)
                        if isinstance(obj, dict):
                            # common wrappers
                            for k in ("features", "unified_features", "data"):
                                if isinstance(obj.get(k), dict):
                                    obj = obj[k]
                                    break
                            # merge: explicit hash fields win
                            merged = dict(obj)
                            for k, v in m.items():
                                if k != "data":
                                    merged[k] = v
                            return merged
                except Exception:
                    return m
                return m

            # Fetch features from multiple timeframes (prefer 5m for stop calculations)
            for tf in ['5m', '15m', '1h']:
                key = f"unified_features:{symbol}:{tf}"
                raw_data = self.redis.hgetall(key)
                if raw_data:
                    raw_data = _maybe_parse_data_field(raw_data)
                    
                    # Extract key volatility and microstructure features.
                    # Unified features use many naming conventions; prefer canonical keys but fall back
                    # to the TA-lib prefixed keys produced by the feature pipeline.
                    sym_u = str(symbol).upper().strip()
                    tf_u = str(tf).lower().strip()

                    def _first(*candidates):
                        for k in candidates:
                            if not k:
                                continue
                            v = raw_data.get(k)
                            if v is None or v == "":
                                continue
                            return v
                        return None

                    def _put(name: str, v):
                        if v is None or name in features:
                            return
                        try:
                            features[name] = float(v)
                        except Exception:
                            return

                    # Volatility (ATR/NATR)
                    _put(
                        "atr_14",
                        _first(
                            "atr_14",
                            f"ind_ta_ATR_14_{tf_u}",
                            f"ind_ind_{sym_u}_ta_ATR_14_{tf_u}",
                        ),
                    )
                    # Normalized ATR is already percent-ish; treat as atr_pct when available.
                    _put(
                        "atr_pct",
                        _first(
                            "atr_pct",
                            f"ind_ta_NATR_14_{tf_u}",
                            f"ind_ind_{sym_u}_ta_NATR_14_{tf_u}",
                        ),
                    )

                    # Technicals
                    _put("rsi_14", _first("rsi_14", f"ind_ta_RSI_14_{tf_u}", f"ind_ind_{sym_u}_ta_RSI_14_{tf_u}"))
                    _put("adx_14", _first("adx_14", f"ind_ta_ADX_14_{tf_u}", f"ind_ind_{sym_u}_ta_ADX_14_{tf_u}"))

                    # Orderbook/microstructure (pipeline + overlays)
                    _put("spread_bps", _first("spread_bps", "ob_ob_spread_bps"))
                    _put("order_imbalance", _first("order_imbalance", "ob_ob_imbalance", "depth_imbalance_5", "bid_ask_imbalance"))
                    _put("bid_ask_imbalance", _first("bid_ask_imbalance", "depth_imbalance_5", "ob_ob_imbalance"))
                    _put("spoof_score", _first("spoof_score", "depth_spoof_score"))
                    _put("fast_move_score", _first("fast_move_score", "depth_fast_move_score", "depth_fast_move_1m", "depth_fast_move_5m"))
                    _put("order_flow_imbalance", _first("order_flow_imbalance", "micro_order_flow_imbalance", "tape_imbalance_5s", "tape_imbalance_30s"))
                    _put("false_move_score", _first("false_move_score", "p_false_move", "micro_p_false_move", "depth_vs_tape_divergence"))
                    _put("src_quality_score", _first("src_quality_score", "depth_quality_score", "micro_quality_score"))

                    # Funding/OI & liquidation (best-effort)
                    _put("funding_rate", _first("funding_rate", "coinank_fundingRate_indicator_data_0_fundingRate"))
                    _put("liq_squeeze_score", _first("liq_squeeze_score", "liquidation_short_strength", "liquidation_long_strength"))
                    _put("liquidation_imbalance", _first("liquidation_imbalance", "liquidation_long_distance_pct", "liquidation_short_distance_pct"))
                    _put("liquidation_long_distance_pct", _first("liquidation_long_distance_pct"))
                    _put("liquidation_short_distance_pct", _first("liquidation_short_distance_pct"))
                    _put("liquidation_long_strength", _first("liquidation_long_strength"))
                    _put("liquidation_short_strength", _first("liquidation_short_strength"))
                    _put("volatility_5m", _first("volatility_5m", "volatility_pct" if tf_u == "5m" else None))
                    _put("volatility_1h", _first("volatility_1h", "volatility_pct" if tf_u == "1h" else None))
                    
                    logger.debug(f"[ADAPTIVE-STOPS] Loaded {len(features)} features from {key}")
                    if len(features) >= 5:  # Have enough data, no need for more TFs
                        break
            
            # Also fetch real-time microstructure from msnap if available
            msnap_key = f"msnap:coinapi_wsds:{symbol}"
            msnap_data = self.redis.hgetall(msnap_key)
            if msnap_data:
                msnap_data = _maybe_parse_data_field(msnap_data)
                for field in ['bid_ask_imbalance', 'order_flow_imbalance', 'spread_bps', 'fast_move_score', 'spoof_score', 'snapback_score', 'src_quality_score', 'p_false_move']:
                    val = msnap_data.get(field)
                    if val:
                        try:
                            features[field] = float(val)
                        except:
                            pass
            
            if features:
                logger.info(f"[DATA-DRIVEN-STOPS] {symbol}: Loaded {len(features)} market features for adaptive calculation")
            else:
                logger.warning(f"[DATA-DRIVEN-STOPS] {symbol}: No market features found, using config fallbacks")
                
        except Exception as e:
            logger.warning(f"[ADAPTIVE-STOPS] Error fetching features for {symbol}: {e}")
        
        return features
    
    def _check_hedge_status(self, symbol: str, side: str) -> bool:
        """Check if this position has an active hedge (opposite position open)"""
        if not self.redis:
            return False
        side_u = str(side or "").upper().strip()
        if side_u not in ("LONG", "SHORT"):
            # Cannot determine opposite side safely.
            return False
        try:
            # Preferred: explicit hedge marker set by traders when an OPEN_HEDGE_* executes.
            try:
                hedge_active_key = f"hedge:active:{symbol}:{self.account_id}"
                if self.redis.exists(hedge_active_key):
                    return True
            except Exception:
                pass

            # Fallback: check canonical per-account consolidated positions hash
            # Key format: portfolio:positions:{account_id} with fields "{SYMBOL}:{SIDE}"
            positions_key = f"portfolio:positions:{self.account_id}"
            opposite_side = "SHORT" if side_u == "LONG" else "LONG"
            field = f"{symbol}:{opposite_side}"
            raw = self.redis.hget(positions_key, field)
            if raw:
                raw_s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                pos = json.loads(raw_s)
                sz = abs(float(pos.get("size", 0) or 0))
                if pos.get("has_position", True) and sz > 0:
                    return True
        except Exception as e:
            logger.debug(f"[ADAPTIVE-STOPS] Error checking hedge status: {e}")
        return False

    def _resolve_leg_entry_pnl(self, symbol: str, side: str, account_id: str) -> Tuple[float, Optional[float], str]:
        """
        Resolve entry price + unrealized PnL for a specific leg.

        Source priority:
        1) Redis portfolio hash `portfolio:positions:{account}` field `{symbol}:{side}`
        2) Binance futures_position_information(symbol) leg snapshot

        Returns: (entry_price, unreal_pnl, source)
        """
        symbol_u = str(symbol or "").upper().strip()
        side_u = str(side or "").upper().strip()

        # 1) Redis portfolio snapshot
        try:
            if self.redis and symbol_u and side_u in ("LONG", "SHORT"):
                pos_key = f"portfolio:positions:{account_id}"
                field = f"{symbol_u}:{side_u}"
                raw = self.redis.hget(pos_key, field)
                if raw:
                    raw_s = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                    pos = json.loads(raw_s)
                    if isinstance(pos, dict):
                        entry_price = 0.0
                        for k in (
                            "entry_price",
                            "avg_entry",
                            "avg_entry_price",
                            "entryPrice",
                            "avgPrice",
                            "entry",
                        ):
                            try:
                                entry_price = float(pos.get(k, 0) or 0.0)
                            except Exception:
                                entry_price = 0.0
                            if entry_price > 0:
                                break

                        unreal_pnl: Optional[float] = None
                        for pk in ("unrealized_pnl", "unrealizedPnl", "unRealizedProfit", "pnl_usd"):
                            if pk in pos:
                                try:
                                    unreal_pnl = float(pos.get(pk) or 0.0)
                                except Exception:
                                    unreal_pnl = None
                                break

                        if entry_price > 0 or unreal_pnl is not None:
                            return float(entry_price), unreal_pnl, "redis_portfolio"
        except Exception as e:
            logger.debug(f"[HEDGE-PROFIT] Redis leg snapshot read failed for {symbol_u} {side_u}: {e}")

        # 2) Exchange snapshot fallback (robust against Redis lag/missing fields)
        try:
            positions = self.binance.futures_position_information(symbol=symbol_u)
            for pos in positions or []:
                try:
                    amt = float(pos.get("positionAmt", 0) or 0.0)
                except Exception:
                    amt = 0.0

                if side_u == "LONG" and amt <= 0:
                    continue
                if side_u == "SHORT" and amt >= 0:
                    continue

                entry_price = 0.0
                try:
                    entry_price = float(pos.get("entryPrice", 0) or pos.get("entry_price", 0) or 0.0)
                except Exception:
                    entry_price = 0.0

                unreal_pnl = None
                for pk in ("unRealizedProfit", "unrealizedProfit", "unrealizedPnl"):
                    if pk in pos:
                        try:
                            unreal_pnl = float(pos.get(pk) or 0.0)
                        except Exception:
                            unreal_pnl = None
                        break

                return float(entry_price), unreal_pnl, "binance_position"
        except Exception as e:
            logger.debug(f"[HEDGE-PROFIT] Exchange leg snapshot read failed for {symbol_u} {side_u}: {e}")

        return 0.0, None, "none"

    def _compute_tp_execution_plan(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size: float = 0.0,
    ) -> Dict[str, float]:
        """Build a live market-data TP plan from CoinAPI, CoinAnk, Binance-derived OHLCV features, and liquidation context."""
        plan: Dict[str, float] = {
            "partial_pct": 35.0,
            "partial_trail": 1.0,
            "trail_mult": 2.0,
            "min_win_usd": 5.0,
            "opp_loss_usd": 25.0,
            "net_pair_max_usd": 15.0,
            "lock_frac": 0.35,
            "trail_distance_pct": 5.0,
            "trend_score": 0.0,
            "risk_score": 0.0,
            "liq_pressure": 0.0,
            "source_count": 0.0,
        }

        try:
            features = self._fetch_market_features(symbol)
            side_u = str(side or "").upper().strip()
            notional_usd = abs(float(position_size or 0.0)) * max(float(current_price or 0.0), float(entry_price or 0.0), 0.0)
            has_hedge = self._check_hedge_status(symbol, side_u)

            def _f(name: str, default: float = 0.0) -> float:
                try:
                    return float(features.get(name, default) or default)
                except Exception:
                    return float(default)

            atr_pct = max(0.0, _f("atr_pct", _f("atr_14", 0.0)))
            adx = max(0.0, _f("adx_14", 0.0))
            fast_move = max(0.0, min(1.5, _f("fast_move_score", 0.0)))
            spoof = max(0.0, min(1.5, _f("spoof_score", 0.0)))
            false_move = max(0.0, min(1.5, _f("false_move_score", _f("p_false_move", 0.0))))
            quality = max(0.0, min(1.0, _f("src_quality_score", 0.0)))
            funding_pressure = min(1.0, abs(_f("funding_rate", 0.0)) * 250.0)
            order_imb = max(
                abs(_f("order_imbalance", 0.0)),
                abs(_f("bid_ask_imbalance", 0.0)),
                abs(_f("order_flow_imbalance", 0.0)),
            )
            liq_long_strength = max(0.0, _f("liquidation_long_strength", 0.0))
            liq_short_strength = max(0.0, _f("liquidation_short_strength", 0.0))
            liq_long_dist = max(0.0, _f("liquidation_long_distance_pct", 0.0))
            liq_short_dist = max(0.0, _f("liquidation_short_distance_pct", 0.0))
            liq_support = liq_short_strength if side_u == "LONG" else liq_long_strength
            liq_pressure = liq_long_strength if side_u == "LONG" else liq_short_strength
            liq_dist = liq_short_dist if side_u == "LONG" else liq_long_dist

            trend_score = min(1.0, max((adx / 35.0), min(1.0, atr_pct / 4.0), min(1.0, order_imb)))
            liq_tailwind = min(1.0, liq_support / max(liq_support + liq_pressure, 1.0)) if (liq_support + liq_pressure) > 0 else 0.0
            liq_risk = 0.0
            if liq_dist > 0:
                liq_risk = min(1.0, max(0.0, (2.5 - liq_dist) / 2.5))

            risk_score = min(
                1.0,
                0.28 * min(1.0, spoof)
                + 0.22 * min(1.0, false_move)
                + 0.15 * min(1.0, fast_move)
                + 0.10 * funding_pressure
                + 0.15 * liq_risk
                + 0.10 * (1.0 - quality),
            )

            partial_pct = 35.0 + (28.0 * risk_score) + (12.0 if has_hedge else 0.0) - (16.0 * trend_score) - (8.0 * liq_tailwind)
            partial_pct = max(15.0, min(85.0, partial_pct))

            trail_mult = 1.6 + (0.9 * trend_score) + (0.5 * liq_tailwind) - (0.5 * risk_score)
            trail_mult = max(1.0, min(3.2, trail_mult))

            min_win_usd = max(3.0, min(45.0, (notional_usd * max(atr_pct, 0.35) / 100.0) * (0.18 + 0.18 * risk_score)))
            opp_loss_usd = max(8.0, min(120.0, (notional_usd * max(atr_pct, 0.50) / 100.0) * (0.40 + 0.45 * float(has_hedge) + 0.35 * risk_score + 0.20 * liq_risk)))
            net_pair_max_usd = max(4.0, min(60.0, min_win_usd * (0.55 + 0.35 * trend_score + 0.15 * liq_tailwind)))
            lock_frac = 0.24 + (0.28 * risk_score) + (0.15 * liq_risk) - (0.12 * trend_score)
            lock_frac = max(0.15, min(0.80, lock_frac))

            trail_distance_pct = 5.0
            try:
                if entry_price > 0 and current_price > 0:
                    _sl, _tp, _trail_act, _trail_dist = self.calculate_adaptive_stop_levels(
                        symbol=symbol,
                        side=side_u,
                        entry_price=float(entry_price),
                        current_price=float(current_price),
                        position_size_usd=float(notional_usd or 0.0),
                        leverage=1.0,
                    )
                    trail_distance_pct = max(1.0, float(_trail_dist or 5.0))
            except Exception:
                trail_distance_pct = max(1.0, min(12.0, 2.5 + atr_pct))

            plan.update({
                "partial_pct": float(partial_pct),
                "partial_trail": 1.0,
                "trail_mult": float(trail_mult),
                "min_win_usd": float(min_win_usd),
                "opp_loss_usd": float(opp_loss_usd),
                "net_pair_max_usd": float(net_pair_max_usd),
                "lock_frac": float(lock_frac),
                "trail_distance_pct": float(trail_distance_pct),
                "trend_score": float(trend_score),
                "risk_score": float(risk_score),
                "liq_pressure": float(liq_pressure),
                "liq_tailwind": float(liq_tailwind),
                "liq_dist_pct": float(liq_dist),
                "atr_pct": float(atr_pct),
                "source_count": float(len(features)),
            })
        except Exception as exc:
            logger.debug("TP_EXECUTION_PLAN_ERR | %s | %s", symbol, exc)

        return plan

    def _sanitize_trailing_tp_trigger(self, stop: StealthStop, current_price: float) -> bool:
        """Repair legacy or stale trailing TP triggers that are still on the wrong side of price."""
        try:
            if not self._is_trailing_tp_stop(stop):
                return False
            if current_price <= 0:
                return False

            side_u = str(getattr(stop, "side", "") or "").upper().strip()
            old_trigger = float(getattr(stop, "trigger_price", 0.0) or 0.0)
            if side_u not in ("LONG", "SHORT") or old_trigger <= 0:
                return False

            wrong_side = (side_u == "LONG" and old_trigger >= current_price) or (side_u == "SHORT" and old_trigger <= current_price)
            if not wrong_side:
                return False

            plan = self._compute_tp_execution_plan(
                stop.symbol,
                side_u,
                float(getattr(stop, "entry_price", 0.0) or 0.0),
                float(current_price),
                float(getattr(stop, "position_size", 0.0) or 0.0),
            )
            trail_dist_pct = max(1.0, float(plan.get("trail_distance_pct", 5.0) or 5.0)) * max(1.0, float(plan.get("trail_mult", 1.0) or 1.0))
            trail_dist_pct = self._atr_adaptive_trail_distance(stop.symbol, side_u, trail_dist_pct)

            if side_u == "LONG":
                new_trigger = current_price * (1.0 - trail_dist_pct / 100.0)
            else:
                new_trigger = current_price * (1.0 + trail_dist_pct / 100.0)

            stop.trigger_price = float(new_trigger)
            logger.warning(
                "TP_TRAIL_SANITIZE | %s %s | old=%.6f new=%.6f px=%.6f dist=%.2f%% features=%d",
                stop.symbol,
                side_u,
                old_trigger,
                float(new_trigger),
                float(current_price),
                float(trail_dist_pct),
                int(plan.get("source_count", 0.0) or 0.0),
            )
            return True
        except Exception as exc:
            logger.debug("TP_TRAIL_SANITIZE_ERR | %s | %s", getattr(stop, "symbol", "?"), exc)
            return False

    def _get_hedged_tp_protective_lock(self, stop: StealthStop, current_price: float) -> Optional[Dict[str, float]]:
        """
        Hedge-first TP override.

        When a winner TP is touched but the opposite hedge leg is still deeply
        underwater and the pair does not yet have enough net cushion, defer the
        TP peel and convert it into a profit-lock stop on the winner.
        """
        try:
            import config as _cfg
            if not bool(getattr(_cfg, "HEDGE_TP_PROTECTIVE_TRAIL_ENABLED", True)):
                return None
        except Exception:
            return None

        if str(getattr(stop, "stop_type", "") or "").upper() != "TAKE_PROFIT":
            return None
        if current_price <= 0:
            return None

        side_u = str(getattr(stop, "side", "") or "").upper().strip()
        if side_u not in ("LONG", "SHORT"):
            return None
        if not self._check_hedge_status(stop.symbol, side_u):
            return None

        account_id = str(getattr(stop, "account_id", None) or getattr(self, "account_id", "primary") or "primary")
        opp_side = "SHORT" if side_u == "LONG" else "LONG"

        leg_entry = float(getattr(stop, "entry_price", 0) or 0)
        leg_unreal = None
        leg_src = "stop"
        try:
            _entry_px, _leg_unreal, _leg_src = self._resolve_leg_entry_pnl(stop.symbol, side_u, account_id)
            if leg_entry <= 0 and _entry_px > 0:
                leg_entry = float(_entry_px)
            leg_unreal = _leg_unreal
            leg_src = _leg_src
        except Exception:
            pass

        try:
            opp_entry, opp_unreal, opp_src = self._resolve_leg_entry_pnl(stop.symbol, opp_side, account_id)
        except Exception:
            opp_entry, opp_unreal, opp_src = 0.0, None, "none"

        tp_plan = self._compute_tp_execution_plan(
            stop.symbol,
            side_u,
            float(leg_entry or getattr(stop, "entry_price", 0.0) or 0.0),
            float(current_price),
            float(getattr(stop, "position_size", 0.0) or 0.0),
        )
        min_win_usd = float(tp_plan.get("min_win_usd", 5.0) or 5.0)
        opp_loss_usd = abs(float(tp_plan.get("opp_loss_usd", 25.0) or 25.0))
        net_pair_max_usd = float(tp_plan.get("net_pair_max_usd", 15.0) or 15.0)
        lock_frac = max(0.05, min(0.95, float(tp_plan.get("lock_frac", 0.35) or 0.35)))

        if leg_entry <= 0 or leg_unreal is None or float(leg_unreal) < float(min_win_usd):
            return None
        if opp_unreal is None or float(opp_unreal) > -float(opp_loss_usd):
            return None

        net_pair = float(leg_unreal) + float(opp_unreal)
        if net_pair > float(net_pair_max_usd):
            return None

        if side_u == "LONG":
            if current_price <= leg_entry:
                return None
            lock_price = leg_entry + (current_price - leg_entry) * lock_frac
            lock_price = min(current_price * 0.999, lock_price)
        else:
            if current_price >= leg_entry:
                return None
            lock_price = leg_entry - (leg_entry - current_price) * lock_frac
            lock_price = max(current_price * 1.001, lock_price)

        if lock_price <= 0:
            return None

        return {
            "lock_price": float(lock_price),
            "leg_unreal": float(leg_unreal),
            "leg_entry": float(leg_entry),
            "leg_src": str(leg_src or "none"),
            "opp_unreal": float(opp_unreal),
            "opp_entry": float(opp_entry or 0.0),
            "opp_src": str(opp_src or "none"),
            "net_pair": float(net_pair),
            "opp_side": opp_side,
            "lock_frac": float(lock_frac),
            "plan_partial_pct": float(tp_plan.get("partial_pct", 35.0) or 35.0),
            "plan_risk_score": float(tp_plan.get("risk_score", 0.0) or 0.0),
            "plan_trend_score": float(tp_plan.get("trend_score", 0.0) or 0.0),
            "plan_features": int(tp_plan.get("source_count", 0.0) or 0.0),
        }

    def _infer_side_from_portfolio(self, symbol: str, account_id: str) -> str:
        """
        Best-effort inference of LONG/SHORT from portfolio:positions.
        Returns "" when it cannot be inferred.
        """
        if not self.redis:
            return ""
        try:
            pos_key = f"portfolio:positions:{account_id}"
            raw_long = self.redis.hget(pos_key, f"{symbol}:LONG")
            raw_short = self.redis.hget(pos_key, f"{symbol}:SHORT")
            def _load(raw):
                if not raw:
                    return None
                s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                try:
                    return json.loads(s) if s else None
                except Exception:
                    return None
            pl = _load(raw_long) or {}
            ps = _load(raw_short) or {}
            try:
                long_sz = abs(float(pl.get("size", 0) or 0.0))
            except Exception:
                long_sz = 0.0
            try:
                short_sz = abs(float(ps.get("size", 0) or 0.0))
            except Exception:
                short_sz = 0.0
            if long_sz <= 0 and short_sz <= 0:
                return ""
            # Prefer whichever exists / larger size.
            return "LONG" if long_sz >= short_sz else "SHORT"
        except Exception:
            return ""
    
    def _check_ride_move_flag(self, symbol: str, side: str) -> Tuple[bool, str]:
        """
        Check if trainer has set a ride-move flag to suppress static TP.
        
        The trainer sets wma:ride_move:{SYMBOL} when:
        1. Position ROE >= STEALTH_RIDE_MOVE_MIN_ROE (default 50%)
        2. Strong momentum continuation detected (squeeze > 0.5 OR momentum > 0.3)
        3. No reversal signal imminent
        
        Returns:
            (suppress_tp: bool, reason: str)
        """
        if not self.redis:
            return False, ""
        
        try:
            from config import STEALTH_TRAINER_INTEGRATION_ENABLED
            if not STEALTH_TRAINER_INTEGRATION_ENABLED:
                return False, ""
        except ImportError:
            return False, ""
        
        try:
            ride_key = f"wma:ride_move:{symbol}"
            data = self.redis.get(ride_key)
            if not data:
                return False, ""
            
            flag_data = json.loads(data.decode('utf-8') if isinstance(data, bytes) else data)
            
            # Check if flag is for this side
            flag_side = flag_data.get('side', '')
            if flag_side and flag_side.upper() != side.upper():
                return False, ""
            
            # Check if suppress_tp is True
            suppress_tp = bool(flag_data.get('suppress_tp', False))
            if suppress_tp:
                # Freshness guard:
                # Trainer writes ride-move via SETEX, so Redis TTL is authoritative.
                # Also honor payload set_ts/ttl_sec if present.
                now = time.time()
                try:
                    set_ts = float(flag_data.get('set_ts', 0) or 0)
                except Exception:
                    set_ts = 0.0
                try:
                    ttl_sec = float(flag_data.get('ttl_sec', 0) or 0)
                except Exception:
                    ttl_sec = 0.0

                payload_not_expired = (set_ts > 0 and ttl_sec > 0 and now < (set_ts + ttl_sec))
                try:
                    redis_ttl = int(self.redis.ttl(ride_key))
                except Exception:
                    redis_ttl = None
                redis_not_expired = (redis_ttl is not None and redis_ttl > 0)
                if not (payload_not_expired or redis_not_expired):
                    return False, ""

                reason = flag_data.get('reason', 'trainer_signal')
                squeeze = float(flag_data.get('squeeze_potential', 0) or 0)
                momentum = float(flag_data.get('momentum_score', 0) or 0)
                fast_move = float(flag_data.get('fast_move_score', 0) or 0)
                return True, f"{reason} (squeeze={squeeze:.2f}, momentum={momentum:.2f}, fast_move={fast_move:.2f})"
            
            return False, ""
            
        except Exception as e:
            logger.debug(f"[RIDE-MOVE] Error checking flag for {symbol}: {e}")
            return False, ""
    
    def calculate_adaptive_stop_levels(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size_usd: float = 0,
        leverage: float = 1.0,
    ) -> Tuple[float, float, float, float]:
        """
        Calculate adaptive SL/TP levels based on REAL MARKET DATA.
        Config values are FALLBACK only when data unavailable.
        
        LEVERAGE-AWARE: Passes position leverage to adaptive stops so
        SL/TP distances are scaled to produce realistic ROE targets.
        
        Data Sources (priority order):
        1. unified_features:{symbol}:{tf} - volatility, indicators
        2. msnap:coinapi_wsds:{symbol} - real-time microstructure
        3. Config defaults - only when data unavailable
        
        Returns:
            (sl_price, tp_price, trail_activation_pct, trail_distance_pct)
        """
        leverage = max(1.0, float(leverage or 1.0))
        # =====================================================================
        # FALLBACK PATH: When adaptive stops system not initialized
        # =====================================================================
        if not self._adaptive_stops:
            logger.warning(f"[ADAPTIVE-STOPS] {symbol}: System not initialized, using CONFIG FALLBACKS")
            try:
                from config import STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT
                from config import STEALTH_TRAIL_ACTIVATION_PCT, STEALTH_TRAIL_DISTANCE_PCT
                sl_pct = STOP_LOSS_PERCENT
                tp_pct = TAKE_PROFIT_PERCENT
                trail_act = STEALTH_TRAIL_ACTIVATION_PCT
                trail_dist = STEALTH_TRAIL_DISTANCE_PCT
            except:
                sl_pct = 6.0
                tp_pct = 8.0
                trail_act = 15.0
                trail_dist = 8.0
            
            # Scale by leverage: config values are ROE % at 10x
            _lev_scale = 10.0 / leverage
            sl_pct = sl_pct * _lev_scale
            tp_pct = tp_pct * _lev_scale
            # Clamp SL within 80% of liq distance
            _liq_dist = 100.0 / leverage
            sl_pct = min(sl_pct, _liq_dist * 0.80)
            sl_pct = max(0.05, sl_pct)
            
            if side == 'LONG':
                sl_price = entry_price * (1 - sl_pct / 100)
                tp_price = entry_price * (1 + tp_pct / 100)
            else:
                sl_price = entry_price * (1 + sl_pct / 100)
                tp_price = entry_price * (1 - tp_pct / 100)
            
            return sl_price, tp_price, trail_act, trail_dist
        
        # =====================================================================
        # DATA-DRIVEN PATH: Fetch real market features for intelligent stops
        # =====================================================================
        try:
            # Fetch market data - THIS IS THE KEY ENHANCEMENT
            features = self._fetch_market_features(symbol)
            
            # Check if position is hedged (allows wider SL)
            has_hedge = self._check_hedge_status(symbol, side)
            
            # ── Fetch REAL microstructure from coinapi_wsds ──
            microstructure_data = {}
            try:
                if self.redis:
                    _ms_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
                    if _ms_raw:
                        for _mk, _mv in _ms_raw.items():
                            _k = _mk.decode("utf-8") if isinstance(_mk, (bytes, bytearray)) else str(_mk)
                            _v = _mv.decode("utf-8") if isinstance(_mv, (bytes, bytearray)) else str(_mv)
                            try:
                                microstructure_data[_k] = float(_v)
                            except (ValueError, TypeError):
                                microstructure_data[_k] = _v
                    if microstructure_data:
                        logger.debug(f"[ADAPTIVE-STOPS] {symbol}: Loaded {len(microstructure_data)} microstructure fields from msnap")
            except Exception as _ms_err:
                logger.debug(f"[ADAPTIVE-STOPS] {symbol}: msnap fetch error: {_ms_err}")

            # ── Fetch REAL liquidation data from unified_features ──
            liquidation_data = {}
            try:
                if self.redis:
                    for _liq_tf in ('1m', '5m'):
                        _liq_raw = self.redis.hgetall(f"unified_features:{symbol}:{_liq_tf}")
                        if not _liq_raw:
                            continue
                        for _lk, _lv in _liq_raw.items():
                            _lk_s = _lk.decode("utf-8") if isinstance(_lk, (bytes, bytearray)) else str(_lk)
                            _lv_s = _lv.decode("utf-8") if isinstance(_lv, (bytes, bytearray)) else str(_lv)
                            _lkl = _lk_s.lower()
                            if 'liquidation' in _lkl or 'liq_' in _lkl:
                                try:
                                    liquidation_data[_lk_s] = float(_lv_s)
                                except (ValueError, TypeError):
                                    pass
                        if liquidation_data:
                            break
                    if liquidation_data:
                        logger.debug(f"[ADAPTIVE-STOPS] {symbol}: Loaded {len(liquidation_data)} liquidation fields")
            except Exception as _liq_err:
                logger.debug(f"[ADAPTIVE-STOPS] {symbol}: liquidation fetch error: {_liq_err}")

            # Get adaptive levels from the system WITH REAL MARKET DATA
            levels = self._adaptive_stops.calculate_adaptive_stops(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                current_price=current_price,
                position_size_usd=position_size_usd,
                features=features,
                microstructure=microstructure_data,
                liquidation_data=liquidation_data,
                has_hedge=has_hedge,
                leverage=leverage,
            )
            
            # Log with clear indication of data source
            data_source = "📊 DATA-DRIVEN" if len(features) >= 3 else "⚙️ CONFIG-FALLBACK"
            hedge_indicator = "🔄 HEDGED" if has_hedge else ""
            _sl_roe = levels.stop_loss_pct * leverage
            _tp_roe = levels.take_profit_pct * leverage
            
            logger.info(
                f"[{data_source}] {symbol} {side} {hedge_indicator} lev={leverage:.0f}x: "
                f"SL={levels.stop_loss_pct:.3f}%p ({_sl_roe:.1f}% ROE) (${levels.stop_loss_price:.4f}) | "
                f"TP={levels.take_profit_pct:.3f}%p ({_tp_roe:.1f}% ROE) (${levels.take_profit_price:.4f}) | "
                f"vol={levels.volatility_regime} | liq={levels.liquidation_risk} | "
                f"micro={levels.microstructure_signal} | action={levels.recommended_action} | "
                f"features_used={len(features)}"
            )
            
            return (
                levels.stop_loss_price,
                levels.take_profit_price,
                levels.trailing_activation_pct,
                levels.trailing_distance_pct
            )
        except Exception as e:
            logger.warning(f"[ADAPTIVE-STOPS] Fallback to static for {symbol}: {e}")
            # Fallback — leverage-scaled
            _lev_scale = 10.0 / leverage
            sl_pct = 6.0 * _lev_scale
            tp_pct = 8.0 * _lev_scale
            _liq_dist = 100.0 / leverage
            sl_pct = min(sl_pct, _liq_dist * 0.80)
            sl_pct = max(0.05, sl_pct)
            if side == 'LONG':
                sl_price = entry_price * (1 - sl_pct / 100)
                tp_price = entry_price * (1 + tp_pct / 100)
            else:
                sl_price = entry_price * (1 + sl_pct / 100)
                tp_price = entry_price * (1 - tp_pct / 100)
            return sl_price, tp_price, 15.0, 8.0

    def get_profit_lock_context(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size_usd: float = 0,
    ) -> Dict[str, Any]:
        """
        Compute a compact context snapshot for profit-lock trailing.

        Returns regime/microstructure context and features_used.
        """
        context = {
            "volatility_regime": "UNKNOWN",
            "liquidation_risk": "UNKNOWN",
            "microstructure_signal": "UNKNOWN",
            "trend_strength": "UNKNOWN",
            "features_used": 0,
            "has_hedge": False,
            "atr_pct": 0.0,
            "volatility_5m": 0.0,
            "volatility_1h": 0.0,
            "fast_move_score": 0.0,
        }

        try:
            features = self._fetch_market_features(symbol)
            context["features_used"] = int(len(features))
            try:
                context["atr_pct"] = float(features.get("atr_pct", features.get("atr_14", 0)) or 0.0)
            except Exception:
                context["atr_pct"] = 0.0
            try:
                context["volatility_5m"] = float(features.get("volatility_5m", 0) or 0.0)
            except Exception:
                context["volatility_5m"] = 0.0
            try:
                context["volatility_1h"] = float(features.get("volatility_1h", 0) or 0.0)
            except Exception:
                context["volatility_1h"] = 0.0
            try:
                context["fast_move_score"] = float(features.get("fast_move_score", 0) or 0.0)
            except Exception:
                context["fast_move_score"] = 0.0
            has_hedge = self._check_hedge_status(symbol, side)
            context["has_hedge"] = bool(has_hedge)

            if self._adaptive_stops:
                # Fetch real microstructure + liquidation data
                _ctx_micro = {}
                _ctx_liq = {}
                try:
                    if self.redis:
                        _ms_r = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
                        if _ms_r:
                            for _k, _v in _ms_r.items():
                                _ks = _k.decode("utf-8") if isinstance(_k, (bytes, bytearray)) else str(_k)
                                _vs = _v.decode("utf-8") if isinstance(_v, (bytes, bytearray)) else str(_v)
                                try:
                                    _ctx_micro[_ks] = float(_vs)
                                except (ValueError, TypeError):
                                    _ctx_micro[_ks] = _vs
                        for _ltf in ('1m', '5m'):
                            _lr = self.redis.hgetall(f"unified_features:{symbol}:{_ltf}")
                            if not _lr:
                                continue
                            for _k, _v in _lr.items():
                                _ks = _k.decode("utf-8") if isinstance(_k, (bytes, bytearray)) else str(_k)
                                _vs = _v.decode("utf-8") if isinstance(_v, (bytes, bytearray)) else str(_v)
                                if 'liquidation' in _ks.lower() or 'liq_' in _ks.lower():
                                    try:
                                        _ctx_liq[_ks] = float(_vs)
                                    except (ValueError, TypeError):
                                        pass
                            if _ctx_liq:
                                break
                except Exception:
                    pass
                levels = self._adaptive_stops.calculate_adaptive_stops(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    current_price=current_price,
                    position_size_usd=position_size_usd,
                    features=features,
                    microstructure=_ctx_micro,
                    liquidation_data=_ctx_liq,
                    has_hedge=has_hedge,
                )
                context["volatility_regime"] = str(levels.volatility_regime)
                context["liquidation_risk"] = str(levels.liquidation_risk)
                context["microstructure_signal"] = str(levels.microstructure_signal)
                context["trend_strength"] = str(levels.trend_strength)
        except Exception as e:
            logger.debug(f"[PROFIT_LOCK] Context error for {symbol}: {e}")

        return context
    
    def start(self):
        """Start the background price monitoring thread"""
        if self._running:
            logger.warning("[STEALTH-STOPS] Already running")
            return
        
        self._running = True
        self._load_from_redis()
        self._reconcile_with_exchange()
        
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[STEALTH-STOPS] ✅ Monitoring thread started")
    
    # Last reconciliation timestamp (for periodic re-checks in the monitor loop)
    _last_reconcile_ts: float = 0.0
    _RECONCILE_INTERVAL_SEC: float = 120.0  # reconcile every 2 minutes

    def _reconcile_with_exchange(self) -> int:
        """Verify all pending stops against actual exchange positions.

        Removes stops for positions that no longer exist on the exchange and
        cleans up stale Redis position metadata keys.

        Returns the number of stops removed.
        """
        removed = 0
        try:
            with self._lock:
                symbols_with_stops = list(self.pending_stops.keys())
            if not symbols_with_stops:
                return 0

            exchange_positions: Dict[str, Dict[str, float]] = {}
            for sym in symbols_with_stops:
                try:
                    pos_list = self.binance.futures_position_information(symbol=sym)
                    for pos in (pos_list or []):
                        amt = float(pos.get("positionAmt", 0) or 0)
                        if abs(amt) > 0:
                            side = "LONG" if amt > 0 else "SHORT"
                            exchange_positions.setdefault(sym, {})[side] = abs(amt)
                except Exception as e:
                    logger.debug(f"[STEALTH-RECONCILE] Exchange query failed for {sym}: {e}")

            with self._lock:
                for sym in symbols_with_stops:
                    live_sides = exchange_positions.get(sym, {})
                    stops = self.pending_stops.get(sym, [])
                    stale = [
                        s for s in stops
                        if s.side not in live_sides or live_sides.get(s.side, 0) < 1e-6
                    ]
                    if stale:
                        for s in stale:
                            stops.remove(s)
                            removed += 1
                            logger.info(
                                "[STEALTH-RECONCILE] Removed ghost stop: %s %s %s (no exchange position)",
                                s.symbol, s.side, s.stop_type,
                            )
                        if not stops:
                            self.pending_stops.pop(sym, None)

                        # Clear stale TP touch state
                        for s in stale:
                            _key = f"{s.symbol}:{s.side}:TAKE_PROFIT"
                            if hasattr(self, '_tp_touch_state') and _key in self._tp_touch_state:
                                del self._tp_touch_state[_key]

                if removed:
                    self._save_to_redis()

            # Clean stale Redis position metadata keys
            self._clean_stale_redis_position_keys(exchange_positions)

            self._last_reconcile_ts = time.time()
            if removed:
                logger.info("[STEALTH-RECONCILE] Removed %d ghost stops total", removed)
        except Exception as e:
            logger.warning("[STEALTH-RECONCILE] Reconciliation error: %s", e)
        return removed

    def _clean_stale_redis_position_keys(self, live_positions: Dict[str, Dict[str, float]]) -> int:
        """Remove Redis position metadata keys that don't correspond to real exchange positions.

        Also applies TTL to surviving position keys so they auto-expire if not refreshed.
        """
        cleaned = 0
        try:
            acct = str(self.account_id or "primary")
            redis_members_key = f"positions:live:symbols:{acct}"
            stored_symbols = self.redis.smembers(redis_members_key)
            if not stored_symbols:
                return 0

            for raw_sym in stored_symbols:
                sym = raw_sym.decode() if isinstance(raw_sym, bytes) else str(raw_sym)
                live_sides = live_positions.get(sym, {})

                if not live_sides:
                    # No position on exchange at all — remove from the set and delete the hash
                    self.redis.srem(redis_members_key, sym)
                    pos_key = f"positions:live:{acct}:{sym}"
                    self.redis.delete(pos_key)
                    # Also clean legacy key format
                    self.redis.delete(f"positions:live:{sym}")
                    cleaned += 1
                    logger.info("[REDIS-HYGIENE] Removed stale position key: %s", pos_key)
                else:
                    # Position exists — ensure the Redis key has a TTL so it auto-expires
                    # if position reporting stops refreshing it.
                    pos_key = f"positions:live:{acct}:{sym}"
                    ttl = self.redis.ttl(pos_key)
                    if ttl is None or ttl < 0:
                        self.redis.expire(pos_key, 600)  # 10-min TTL

            if cleaned:
                logger.info("[REDIS-HYGIENE] Cleaned %d stale position keys", cleaned)
        except Exception as e:
            logger.debug("[REDIS-HYGIENE] Cleanup error: %s", e)
        return cleaned

    def stop(self):
        """Stop the monitoring thread"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("[STEALTH-STOPS] Stopped")

    def _adaptive_trail_v2_check(self, stop, current_price: float) -> None:
        """
        Fix 11 (Redesign v2): Adaptive Trailing Stop V2.
        Once ROE exceeds activation threshold, trail TP at ATR distance
        behind best price to lock in profits while allowing winners to run.
        Only applies to TAKE_PROFIT stops.
        """
        if stop.stop_type != "TAKE_PROFIT":
            return
        try:
            from config import (
                ADAPTIVE_TRAIL_V2_ENABLED,
                ADAPTIVE_TRAIL_V2_ACTIVATION_ROE_PCT,
                ADAPTIVE_TRAIL_V2_ATR_MULT_MAP,
                ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT,
            )
            if not ADAPTIVE_TRAIL_V2_ENABLED:
                return
        except ImportError:
            return

        try:
            entry_px = float(getattr(stop, "entry_price", 0) or 0)
            if entry_px <= 0 or current_price <= 0:
                return
            is_long = stop.side.upper() == "LONG"

            # Get leverage
            from risk.intelligent_close_guard import _decode_map
            leverage = 1.0
            try:
                for _acc in (getattr(self, 'account_id', 'primary'), "primary"):
                    _plk = f"positions:live:{_acc}:{stop.symbol}"
                    _plr = self.redis.hgetall(_plk) if self.redis else None
                    if _plr:
                        _pld = _decode_map(_plr)
                        _rl = float(_pld.get("leverage", 0) or 0)
                        if _rl >= 1:
                            leverage = _rl
                            break
            except Exception:
                pass

            # Compute current ROE
            if is_long:
                roe = (current_price - entry_px) / entry_px * 100.0 * leverage
            else:
                roe = (entry_px - current_price) / entry_px * 100.0 * leverage

            if roe < ADAPTIVE_TRAIL_V2_ACTIVATION_ROE_PCT:
                return  # Not profitable enough to trail

            # Get ATR for trail distance
            from trading.redesign_v2_helpers import get_atr_pct_for_symbol, get_regime_for_symbol
            atr_pct = get_atr_pct_for_symbol(self.redis, stop.symbol, "15m")
            if atr_pct <= 0:
                atr_pct = 0.5  # Fallback

            regime = get_regime_for_symbol(self.redis, stop.symbol, "15m")
            move_regime = str(regime.get("move_regime", "NORMAL")).upper()
            atr_mult = ADAPTIVE_TRAIL_V2_ATR_MULT_MAP.get(move_regime, 1.5)

            # ── INTELLIGENCE-DRIVEN TRAIL PARAMS (Apr 2026) ──
            # Overrides static ATR mult with adaptive values from market data:
            # liq clusters, trend strength, momentum, reversal risk, spoof risk
            _intel_trail_reason = ""
            try:
                from trading.market_intelligence import get_adaptive_trail_params
                _atp = get_adaptive_trail_params(
                    self.redis, stop.symbol, stop.side,
                )
                _intel_trail_dist_mult = float(_atp.get("trail_distance_mult", 1.0))
                _intel_trail_act_mult = float(_atp.get("trail_activation_mult", 1.0))
                _intel_trail_reason = str(_atp.get("reason", ""))
                # Apply multipliers to ATR mult (stacks with regime)
                atr_mult *= _intel_trail_dist_mult
            except ImportError:
                pass
            except Exception as _at_err:
                logger.debug("INTEL_TRAIL_ERR | %s | %s", stop.symbol, _at_err)

            trail_dist_pct = atr_pct * atr_mult
            trail_dist_pct = max(trail_dist_pct, 0.5)  # Minimum 0.5% trail

            # Track best price (stored as attribute on stop)
            _best_key = f"_trail_v2_best:{stop.symbol}:{stop.side}"
            best_price = getattr(self, _best_key, None)
            if best_price is None:
                best_price = current_price
            if is_long:
                best_price = max(best_price, current_price)
            else:
                best_price = min(best_price, current_price)
            setattr(self, _best_key, best_price)

            # Compute trail trigger
            if is_long:
                trail_tp = best_price * (1 - trail_dist_pct / 100.0)
                # Ensure trail TP locks in minimum profit
                min_lock_price = entry_px * (1 + (roe * ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT / 100.0) / leverage / 100.0)
                trail_tp = max(trail_tp, min_lock_price)
            else:
                trail_tp = best_price * (1 + trail_dist_pct / 100.0)
                min_lock_price = entry_px * (1 - (roe * ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT / 100.0) / leverage / 100.0)
                trail_tp = min(trail_tp, min_lock_price)

            old_tp = float(stop.trigger_price)

            # ── MOMENTUM REGIME: Allow trail to loosen (Apr 2026) ──
            # In momentum regime, trail can widen when trend resumes,
            # plus the min profit lock % is lower to give more room.
            _v2_in_momentum = False
            _eff_min_profit_lock_pct = float(ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT)
            try:
                from config import MOMENTUM_REGIME_ENABLED as _V2_MRE
                if _V2_MRE and self.redis:
                    _v2_mflag = self.redis.get(f"wma:momentum_regime:{stop.symbol}")
                    if _v2_mflag:
                        _v2_in_momentum = True
                        # In momentum: lower min profit lock from 50% to 25%
                        # so trail is wider and gives more room for retracements
                        try:
                            from config import MOMENTUM_PROFIT_LOCK_MIN_FRAC
                            _eff_min_profit_lock_pct = float(MOMENTUM_PROFIT_LOCK_MIN_FRAC) * 100.0  # 0.15 → 15%
                        except ImportError:
                            _eff_min_profit_lock_pct = 25.0
                        # Also widen trail distance in momentum
                        try:
                            from config import MOMENTUM_TRAIL_DISTANCE_MULT
                            trail_dist_pct *= float(MOMENTUM_TRAIL_DISTANCE_MULT)
                        except ImportError:
                            trail_dist_pct *= 2.5
            except (ImportError, Exception):
                pass

            # Recompute trail trigger with effective params
            if is_long:
                trail_tp = best_price * (1 - trail_dist_pct / 100.0)
                min_lock_price = entry_px * (1 + (roe * _eff_min_profit_lock_pct / 100.0) / leverage / 100.0)
                trail_tp = max(trail_tp, min_lock_price)
            else:
                trail_tp = best_price * (1 + trail_dist_pct / 100.0)
                min_lock_price = entry_px * (1 - (roe * _eff_min_profit_lock_pct / 100.0) / leverage / 100.0)
                trail_tp = min(trail_tp, min_lock_price)

            # Trail can only tighten UNLESS momentum regime allows loosening
            should_update = False
            if _v2_in_momentum:
                # In momentum: allow trail to loosen (move FURTHER from price)
                # but never below entry (breakeven floor)
                if is_long and trail_tp > entry_px:
                    should_update = True
                elif not is_long and trail_tp < entry_px:
                    should_update = True
            else:
                # Normal: trail can only tighten
                if is_long and trail_tp > entry_px and trail_tp > old_tp:
                    should_update = True
                elif not is_long and trail_tp < entry_px and trail_tp < old_tp:
                    should_update = True

            if should_update:
                stop.trigger_price = trail_tp
                logger.info(
                    "ADAPTIVE_TRAIL_V2 | sym=%s side=%s | roe=%.1f%% | "
                    "best_px=%.6f current=%.6f | trail_dist=%.3f%% (ATR×%.1f) | "
                    "old_tp=%.6f → new_tp=%.6f | regime=%s lev=%.0fx%s%s",
                    stop.symbol, stop.side, roe,
                    best_price, current_price, trail_dist_pct, atr_mult,
                    old_tp, trail_tp, move_regime, leverage,
                    " 🚀MOMENTUM" if _v2_in_momentum else "",
                    f" 🧠INTEL:{_intel_trail_reason}" if _intel_trail_reason else "",
                )
        except Exception as e:
            logger.debug("ADAPTIVE_TRAIL_V2_ERR | %s | %s", stop.symbol, e)

    def _is_tp_stop(self, stop) -> bool:
        return str(getattr(stop, "stop_type", "") or "").upper() == "TAKE_PROFIT"

    def _is_trailing_tp_stop(self, stop) -> bool:
        return self._is_tp_stop(stop) and "TRAIL" in str(getattr(stop, "reason", "") or "").upper()

    def _is_static_tp_stop(self, stop) -> bool:
        return self._is_tp_stop(stop) and not self._is_trailing_tp_stop(stop)
    
    def add_stop(self, stop: StealthStop, source: str = "manual"):
        """
        Add or update a conditional stop to monitor
        
        Args:
            stop: StealthStop to add
            source: Source of the stop ('manual', 'dynamic', 'trailing')
        """
        with self._lock:
            # Normalize/repair stop side (older producers sometimes omit side for TP updates).
            try:
                stop.side = str(stop.side or "").upper().strip()
            except Exception:
                stop.side = ""
            if stop.side not in ("LONG", "SHORT"):
                inferred = self._infer_side_from_portfolio(stop.symbol, stop.account_id)
                if inferred in ("LONG", "SHORT"):
                    stop.side = inferred
                else:
                    logger.warning(
                        f"[STEALTH-STOPS] ⚠️ Skipping stop with unknown side: {stop.symbol} stop_type={stop.stop_type} "
                        f"trigger={stop.trigger_price} source={source}"
                    )
                    return
            # Check if stop already exists for this symbol/side/type
            existing_stops = self.pending_stops.get(stop.symbol, [])
            updated = False
            
            for i, existing in enumerate(existing_stops):
                if (existing.side == stop.side and 
                    existing.stop_type == stop.stop_type and
                    existing.account_id == stop.account_id):
                    if self._is_trailing_tp_stop(existing) and not self._is_trailing_tp_stop(stop):
                        logger.info(
                            "[STEALTH-STOPS] ⏭️ Keeping trailing TP for %s %s; ignoring static TP update from %s",
                            stop.symbol, stop.side, source,
                        )
                        return
                    # ── FIX 2 (Redesign v2): TP Ratchet-Down Block ──────────
                    # For TAKE_PROFIT updates, block if new TP is closer to
                    # entry than existing TP (prevents SET_TP flood from
                    # pulling TP closer on bounces).
                    if self._is_static_tp_stop(stop):
                        try:
                            from trading.redesign_v2_helpers import check_tp_ratchet_block
                            _entry = float(getattr(existing, "entry_price", 0) or getattr(stop, "entry_price", 0) or 0)
                            _is_long = stop.side.upper() == "LONG"
                            if _entry > 0 and check_tp_ratchet_block(
                                _entry, float(existing.trigger_price),
                                float(stop.trigger_price), _is_long
                            ):
                                return  # Block: new TP is closer to entry
                        except Exception:
                            pass
                    # Update existing stop (for dynamic/trailing updates)
                    logger.info(f"[STEALTH-STOPS] 🔄 Updated {stop.stop_type} for {stop.symbol} {stop.side}: "
                               f"{existing.trigger_price:.2f} → {stop.trigger_price:.2f} (source: {source})")
                    self.pending_stops[stop.symbol][i] = stop
                    updated = True
                    break
            
            if not updated:
                # Add new stop
                self.pending_stops[stop.symbol].append(stop)
                logger.info(f"[STEALTH-STOPS] ➕ Added {stop.stop_type} for {stop.symbol} {stop.side} @ {stop.trigger_price} (source: {source})")
            
            # Persist to Redis
            self._save_to_redis()

    # ---------------------------------------------------------------------
    # Convenience helpers (backwards-compatible with older call sites)
    # ---------------------------------------------------------------------
    def add_take_profit(
        self,
        *,
        symbol: str,
        side: str,
        trigger_price: float,
        position_size: float,
        close_percentage: float = 100.0,
        source: str = "manual",
        account_id: str = "primary",
        reason: str = "",
        signal_id: Optional[str] = None,
        hedge_maker_only: bool = False,
        entry_price: float = 0.0,
    ) -> None:
        """Add/update a TAKE_PROFIT stealth stop for a position."""
        stop = StealthStop(
            symbol=str(symbol),
            side=str(side).upper(),
            stop_type="TAKE_PROFIT",
            trigger_price=float(trigger_price),
            position_size=float(position_size),
            close_percentage=float(close_percentage),
            account_id=str(account_id or "primary"),
            reason=str(reason or ""),
            signal_id=signal_id,
            hedge_maker_only=bool(hedge_maker_only),
            entry_price=float(entry_price or 0.0),
        )
        self.add_stop(stop, source=str(source or "manual"))

            # Telegram: alert when stops are ARMED - DISABLED to reduce spam
            # To re-enable, set STEALTH_STOP_TELEGRAM_ALERTS=true in .env
            # try:
            #     should_alert = (not updated) and (str(source).lower() in {"entry", "manual"})
            #     if should_alert and self.telegram:
            #         acct = self._account_label()
            #         emoji = "🛑" if stop.stop_type == "STOP_LOSS" else "🎯" if stop.stop_type == "TAKE_PROFIT" else "🕶️"
            #         msg = (
            #             f"{emoji} <b>STEALTH {stop.stop_type} ARMED</b>\n\n"
            #             f"👤 <b>{acct}</b>\n"
            #             f"📊 <b>{stop.symbol}</b> | {stop.side}\n"
            #             f"Trigger: <b>{float(stop.trigger_price):.4f}</b>\n"
            #             f"Qty: <b>{float(stop.position_size):.6f}</b>\n"
            #             f"Close: <b>{float(stop.close_percentage):.0f}%</b>\n"
            #             f"Source: <b>{source}</b>\n"
            #             f"Reason: <code>{str(stop.reason or '')[:400]}</code>"
            #         )
            #         self._send_trade_alert_async(msg)
            # except Exception:
            #     pass
    
    def remove_stop(self, symbol: str, side: str, stop_type: str, account_id: Optional[str] = None):
        """Remove a specific stop; optionally filter by account_id for multi-account setups."""
        with self._lock:
            if symbol in self.pending_stops:
                self.pending_stops[symbol] = [
                    s for s in self.pending_stops[symbol]
                    if not (s.side == side and s.stop_type == stop_type and (account_id is None or s.account_id == account_id))
                ]
                if not self.pending_stops[symbol]:
                    del self.pending_stops[symbol]
                
                self._save_to_redis()
                logger.info(f"[STEALTH-STOPS] ➖ Removed {stop_type} for {symbol} {side} (account={account_id or 'any'})")
    
    def remove_all_for_symbol(self, symbol: str):
        """Remove all stops for a symbol (e.g., when position closed)"""
        with self._lock:
            if symbol in self.pending_stops:
                count = len(self.pending_stops[symbol])
                del self.pending_stops[symbol]
                self._save_to_redis()
                logger.info(f"[STEALTH-STOPS] 🗑️ Removed all {count} stops for {symbol}")
            # Reset partial TP tracker for this symbol (both sides)
            tracker = getattr(self, '_tp_partial_tracker', None)
            if tracker:
                for side in ("LONG", "SHORT"):
                    tracker.pop(f"_tp_partial_done:{symbol}:{side}", None)
            # Clear TP touch state
            for side in ("LONG", "SHORT"):
                for stype in ("TAKE_PROFIT", "STOP_LOSS"):
                    _k = f"{symbol}:{side}:{stype}"
                    if hasattr(self, '_tp_touch_state') and _k in self._tp_touch_state:
                        del self._tp_touch_state[_k]

    def remove_all_for_symbol_side(self, symbol: str, side: str):
        """Remove all stops for a specific symbol+side after a close execution."""
        with self._lock:
            if symbol in self.pending_stops:
                side_u = side.upper()
                before = len(self.pending_stops[symbol])
                self.pending_stops[symbol] = [
                    s for s in self.pending_stops[symbol] if s.side != side_u
                ]
                removed = before - len(self.pending_stops[symbol])
                if not self.pending_stops[symbol]:
                    del self.pending_stops[symbol]
                if removed:
                    self._save_to_redis()
                    logger.info(
                        "[STEALTH-DUST-CLEANUP] Removed %d stops for %s %s after close",
                        removed, symbol, side_u,
                    )
            # Clear TP touch state for this side
            for stype in ("TAKE_PROFIT", "STOP_LOSS"):
                _k = f"{symbol}:{side.upper()}:{stype}"
                if hasattr(self, '_tp_touch_state') and _k in self._tp_touch_state:
                    del self._tp_touch_state[_k]
            tracker = getattr(self, '_tp_partial_tracker', None)
            if tracker:
                tracker.pop(f"_tp_partial_done:{symbol}:{side.upper()}", None)
    
    def get_pending_stops(self, symbol: Optional[str] = None) -> List[StealthStop]:
        """Get pending stops for a symbol or all symbols"""
        with self._lock:
            if symbol:
                return list(self.pending_stops.get(symbol, []))
            else:
                # Return all stops across all symbols
                all_stops = []
                for stops in self.pending_stops.values():
                    all_stops.extend(stops)
                return all_stops
    
    def _maybe_propose_profit_hedge(
        self,
        symbol: str,
        side: str,
        current_price: float,
        entry_price: float,
        position_size: float,
    ) -> None:
        """
        When a profitable open position shows trainer-confirmed reversal or mean-reversion
        signals, slowly build an opposite hedge leg by publishing ADD_HEDGE_{opp} proposals
        to wma:proposals.

        Gating (ALL must pass):
          1. PROFIT_HEDGE_BUILD_ENABLED kill-switch is on (default True)
          2. Redis cooldown not active  (hedge:build:cd:{sym}:{side})
          3. Live ROE (from Redis position data OR computed via leverage) >= adaptive threshold
             Threshold = NATR_pct × leverage × 0.20  (captures at least 20% of one ATR-lev unit)
          4. Trainer direction OPPOSES current position — sourced from:
             a) Per-TF predictions (4h > 1h > 15m > 5m, highest conf wins)
             b) Consensus from get_trainer_view as fallback
             Minimum confidence threshold scales with regime strength (lower in RANGE)
          5. Composite reversal_score >= adaptive floor
             Score = trainer_conf × regime_factor × microstructure_factor × liq_factor

        Sizing is fully adaptive — no static dollar amounts:
          hedge_fraction = 5%-25% of position notional
          Bounded by wallet-relative sanity: floor $8, cap derived from live wallet balance
        """
        try:
            from config import PROFIT_HEDGE_BUILD_ENABLED
            if not bool(PROFIT_HEDGE_BUILD_ENABLED):
                return
        except Exception:
            pass  # default enabled

        if not self.redis or entry_price <= 0 or current_price <= 0 or position_size <= 0:
            return

        sym = str(symbol or "").upper().strip()
        side_u = str(side or "").upper().strip()
        is_long = side_u == "LONG"

        # ── 1. Redis cooldown — anti-churn ───────────────────────────────────
        _cd_key = f"hedge:build:cd:{sym}:{side_u}"
        try:
            if self.redis.exists(_cd_key):
                return
        except Exception:
            return

        # ── 2. Live leverage + ROE from Redis position data ───────────────────
        # Use roe_pct directly from positions:live (Binance-reported, most accurate)
        leverage = 1.0
        roe_pct = 0.0
        pos_notional = 0.0
        try:
            from risk.intelligent_close_guard import _decode_map
            for _acc in (self.account_id, "primary"):
                _plk = f"positions:live:{_acc}:{sym}"
                _plr = self.redis.hgetall(_plk)
                if _plr:
                    _pld = _decode_map(_plr)
                    _rl = float(_pld.get("leverage", 0) or 0)
                    if _rl >= 1:
                        leverage = _rl
                        roe_pct = float(_pld.get("roe_pct", 0) or 0)
                        pos_notional = float(_pld.get("notional_usd", 0) or 0)
                        break
        except Exception:
            pass

        # Fallback: compute ROE from price move × leverage if Redis data missing
        if roe_pct <= 0 and leverage > 0:
            price_pnl_pct = (
                (current_price - entry_price) / entry_price * 100.0 if is_long
                else (entry_price - current_price) / entry_price * 100.0
            )
            roe_pct = price_pnl_pct * leverage

        if roe_pct <= 0:
            return

        # ── 3. NATR across ALL TFs (4h NATR most important for scale awareness) ─
        atr_pct_5m = 0.0
        atr_pct_4h = 0.0
        adx_4h = 0.0
        adx_best = 0.0
        try:
            for _tf in ("5m", "15m", "1h", "4h"):
                _fr = self.redis.hgetall(f"unified_features:{sym}:{_tf}")
                if not _fr:
                    continue
                _fm = _decode_map(_fr)
                for _k, _v in _fm.items():
                    try:
                        _fv = float(_v)
                    except Exception:
                        continue
                    _kl = _k.lower()
                    if "ta_natr_14" in _kl and _fv > 0:
                        if _tf == "4h":
                            atr_pct_4h = max(atr_pct_4h, _fv)
                        elif _tf == "5m":
                            atr_pct_5m = max(atr_pct_5m, _fv)
                    if "ta_adx_14" in _kl and _fv > adx_best:
                        adx_best = _fv
                        if _tf == "4h":
                            adx_4h = _fv
        except Exception:
            pass

        # Use 4h NATR for threshold (most meaningful for high-lev), fallback to 5m
        atr_ref = atr_pct_4h if atr_pct_4h > 0 else (atr_pct_5m if atr_pct_5m > 0 else 0.5)

        # ── 4. Adaptive ROE threshold ─────────────────────────────────────────
        # Need at least (atr_ref × lev × 0.20)% ROE before building hedge
        # This ensures we've captured enough profit to absorb the hedge cost
        # Examples: 75x, NATR=0.82%: min_roe = 0.82*75*0.20 = 12.3%
        #           41x, NATR=0.24%: min_roe = 0.24*41*0.20 = 1.97% → floor 8%
        #           10x, NATR=1.5%:  min_roe = 1.5*10*0.20 = 3% → floor 8%
        min_roe = max(8.0, min(40.0, atr_ref * leverage * 0.20))
        if roe_pct < min_roe:
            return

        # ── 5. Trainer direction: MUST oppose current position ────────────────
        # Read per-TF predictions directly (4h bias is most important)
        # ALSO read consensus — use whichever gives stronger opposing signal
        _best_opp_conf = 0.0
        _best_opp_dir = ""
        _best_opp_tgt = 0.0
        _per_tf_votes = 0  # count of TFs opposing
        _per_tf_total = 0
        try:
            for _ptf in ("4h", "1h", "15m", "5m"):
                _ph = self.redis.hgetall(f"prediction:{sym}:{_ptf}")
                if not _ph:
                    continue
                _pd = _decode_map(_ph)
                _pdir = str(_pd.get("direction", "") or "").upper()
                if _pdir not in ("LONG", "SHORT"):
                    try:
                        from risk.trainer_intent import infer_direction_from_action

                        _ia = str(_pd.get("action") or _pd.get("action_name") or "")
                        _inf = infer_direction_from_action(_ia)
                        if _inf in ("LONG", "SHORT"):
                            _pdir = _inf
                    except Exception:
                        pass
                _pconf = float(_pd.get("confidence", 0) or 0)
                _ptgt_px = float(_pd.get("price_target", 0) or 0)
                _ts = float(_pd.get("timestamp", 0) or _pd.get("ts_ms", 0) or 0)
                # Skip stale predictions (> 5 min)
                if _ts > 0 and (time.time() - _ts / 1000.0 if _ts > 1e9 else time.time() - _ts) > 300:
                    continue
                _popposes = (
                    (is_long and _pdir in ("SHORT", "BEARISH", "DOWN"))
                    or (not is_long and _pdir in ("LONG", "BULLISH", "UP"))
                )
                _per_tf_total += 1
                if _popposes:
                    _per_tf_votes += 1
                    if _pconf > _best_opp_conf:
                        _best_opp_conf = _pconf
                        _best_opp_dir = _pdir
                        _best_opp_tgt = _ptgt_px
        except Exception:
            pass

        # Also check consensus
        _consensus_opposes = False
        _consensus_conf = 0.0
        _consensus_dir = ""
        try:
            from risk.trainer_alignment import get_trainer_view
            _tv = get_trainer_view(self.redis, sym)
            if _tv and _tv.is_directional:
                _tv_dir = _tv.consensus_direction.upper()
                _tv_conf = float(_tv.consensus_confidence)
                if ((is_long and _tv_dir in ("SHORT", "BEARISH", "DOWN"))
                        or (not is_long and _tv_dir in ("LONG", "BULLISH", "UP"))):
                    _consensus_opposes = True
                    _consensus_conf = _tv_conf
                    _consensus_dir = _tv_dir
        except Exception:
            pass

        # Require: either >50% of TFs oppose OR consensus opposes with conf >= 0.55
        # Use the higher-confidence signal
        tf_majority_opposes = _per_tf_total > 0 and _per_tf_votes / _per_tf_total >= 0.50
        if not (tf_majority_opposes or _consensus_opposes):
            return

        # Final opposing direction + confidence
        if _best_opp_conf >= _consensus_conf:
            _tconf = _best_opp_conf
            _tdir = _best_opp_dir
        else:
            _tconf = _consensus_conf
            _tdir = _consensus_dir

        if _tconf < 0.55 or not _tdir:
            return

        # ── 6. Regime data ────────────────────────────────────────────────────
        import json as _json
        try:
            _reg_raw = self.redis.get(f"regime:{sym}")
            _reg = (
                _json.loads(_reg_raw.decode() if isinstance(_reg_raw, (bytes, bytearray)) else str(_reg_raw))
                if _reg_raw else {}
            )
            _move_regime = str(_reg.get("move_regime", "UNKNOWN")).upper()
            _liq_imbalance = float(_reg.get("liq_imbalance", 0) or 0)
            _tf_conflict = float(_reg.get("tf_conflict", 0) or 0)
        except Exception:
            _move_regime = "UNKNOWN"
            _liq_imbalance = 0.0
            _tf_conflict = 0.0

        # Regime factor: ranging → 1.6x (mean-reversion), trending-against → 1.3x
        regime_factor = (
            1.6 if _move_regime in ("RANGE", "CALM", "NORMAL", "MEAN_REVERSION")
            else 1.3 if _move_regime in ("TRENDING", "BREAKOUT", "IMPULSE")
            else 1.0
        )
        # Penalise if TF signals conflict strongly (noisy market)
        if _tf_conflict > 0.4:
            regime_factor *= (1.0 - _tf_conflict * 0.5)

        # ── 7. Microstructure: orderflow opposing position ────────────────────
        ms_factor = 1.0
        opp_imbalance_factor = 0.0
        try:
            _ms_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{sym}")
            if _ms_raw:
                _ms = _decode_map(_ms_raw)
                _imb = float(_ms.get("imbalance_5", 0) or 0)
                _fast_mv = max(
                    float(_ms.get("fast_move_score", 0) or 0),
                    float(_ms.get("fast_move_max_5m", 0) or 0),
                    float(_ms.get("fast_move_max_15m", 0) or 0),
                )
                _churn = float(_ms.get("churn_score", 0) or 0)
                _snap = float(_ms.get("snapback_score", 0) or 0)
                # Imbalance opposing our position = bullish flow for SHORT pos, bearish for LONG
                if is_long and _imb < -0.05:  # bearish imbalance on LONG
                    opp_imbalance_factor = min(1.0, abs(_imb) * 2.5)
                elif not is_long and _imb > 0.05:  # bullish imbalance on SHORT
                    opp_imbalance_factor = min(1.0, _imb * 2.5)
                # Snapback score (reversal micro signal)
                if _snap > 0.1:
                    ms_factor *= (1.0 + _snap * 0.5)
                # Churn penalises entry (unstable market)
                if _churn > 0.4:
                    ms_factor *= max(0.6, 1.0 - _churn * 0.5)
        except Exception:
            pass

        # ── 8. Liquidation factor: opposite-side liq clusters near price ──────
        liq_factor = 1.0
        try:
            _f5 = self.redis.hgetall(f"unified_features:{sym}:5m")
            if _f5:
                _fd = _decode_map(_f5)
                # If we're LONG and SHORT liq clusters are near → price could reverse
                # If we're SHORT and LONG liq clusters are near → price could reverse  
                if is_long:
                    _opp_liq_d = float(_fd.get("liquidation_long_distance_pct", 100) or 100)
                    _opp_liq_s = float(_fd.get("liquidation_long_strength", 0) or 0)
                else:
                    _opp_liq_d = float(_fd.get("liquidation_short_distance_pct", 100) or 100)
                    _opp_liq_s = float(_fd.get("liquidation_short_strength", 0) or 0)
                # Nearby same-direction liq cascade potential → don't hedge yet
                if _opp_liq_d < 1.5 and _opp_liq_s > 1e6:
                    liq_factor = 1.3  # reversal potential high
                elif _opp_liq_d < 3.0 and _opp_liq_s > 5e5:
                    liq_factor = 1.15
        except Exception:
            pass

        # ── 9. Composite reversal score ───────────────────────────────────────
        # Base: trainer_conf × regime_factor
        # Amplifiers: microstructure opposing + TF majority votes + liq factor
        tf_vote_factor = 1.0 + min(0.5, (_per_tf_votes / max(1, _per_tf_total) - 0.5) * 1.0)
        reversal_score = (_tconf * regime_factor * tf_vote_factor
                          * ms_factor * liq_factor * (1.0 + opp_imbalance_factor * 0.4))

        # Adaptive floor: relax as ROE cushion grows
        # At min_roe threshold: need score >= 0.72
        # At 2× min_roe: need score >= 0.48 (large profit cushion → act sooner)
        excess_roe_ratio = min(3.0, (roe_pct - min_roe) / max(1.0, min_roe))
        min_reversal = max(0.42, 0.72 - excess_roe_ratio * 0.15)

        if reversal_score < min_reversal:
            return

        # ── 10. Adaptive hedge sizing ─────────────────────────────────────────
        # Use actual position notional from Redis, fallback to qty × price
        if pos_notional <= 0:
            pos_notional = position_size * current_price

        # Hedge fraction: 5%-25% of notional, scaled by reversal conviction
        score_surplus = max(0.0, reversal_score - min_reversal) / max(0.1, 1.0 - min_reversal)
        hedge_fraction = min(0.25, 0.05 + score_surplus * 0.20)

        # Also scale hedge size with ROE cushion ratio: more profit → can hedge more
        roe_scale = min(1.5, roe_pct / max(1.0, min_roe))
        hedge_fraction = min(0.25, hedge_fraction * max(1.0, roe_scale * 0.7))

        hedge_notional = pos_notional * hedge_fraction
        hedge_margin = hedge_notional / max(1.0, leverage)

        # Floor/cap relative to wallet balance if available
        _wallet_bal = 0.0
        try:
            _wb = self.redis.get(f"wallet:balance:{self.account_id or 'primary'}")
            if _wb:
                _wallet_bal = float(_wb)
        except Exception:
            pass
        _min_margin = 8.0
        _max_margin = max(200.0, _wallet_bal * 0.15) if _wallet_bal > 0 else 300.0
        hedge_margin = max(_min_margin, min(_max_margin, hedge_margin))

        # ── 11. Publish ADD_HEDGE proposal ───────────────────────────────────
        _opp_action = "ADD_HEDGE_SHORT" if is_long else "ADD_HEDGE_LONG"
        try:
            from rl.trade_proposal import TradeProposal
            from rl.proposal_bus import emit_proposal

            _proposal = TradeProposal.new(
                source="stealth_profit_hedge",
                account_id=str(self.account_id or "primary"),
                symbol=sym,
                action_name=_opp_action,
                action_category="HEDGE",
                confidence=float(min(1.0, _tconf)),
                urgency_score=float(min(0.85, reversal_score * 0.55)),
                no_loss_compliant=True,
                margin_usd=float(hedge_margin),
                notional_usd=float(hedge_margin * leverage),
                leverage=float(leverage),
                trigger_reason=(
                    f"PROFIT_HEDGE_BUILD {sym} {side_u} roe={roe_pct:.1f}% "
                    f"score={reversal_score:.2f} trainer={_tdir} conf={_tconf:.2f} "
                    f"regime={_move_regime} tf_votes={_per_tf_votes}/{_per_tf_total} "
                    f"imb={opp_imbalance_factor:.2f} atr4h={atr_pct_4h:.3f}%"
                ),
                market_context={
                    "roe_pct": float(roe_pct),
                    "min_roe_threshold": float(min_roe),
                    "reversal_score": float(reversal_score),
                    "min_reversal_threshold": float(min_reversal),
                    "trainer_direction": _tdir,
                    "trainer_confidence": float(_tconf),
                    "regime": _move_regime,
                    "regime_factor": float(regime_factor),
                    "tf_votes_opp": int(_per_tf_votes),
                    "tf_votes_total": int(_per_tf_total),
                    "opp_imbalance_factor": float(opp_imbalance_factor),
                    "liq_factor": float(liq_factor),
                    "ms_factor": float(ms_factor),
                    "adx_4h": float(adx_4h),
                    "atr_pct_4h": float(atr_pct_4h),
                    "entry_price": float(entry_price),
                    "current_price": float(current_price),
                    "leverage": float(leverage),
                    "hedge_fraction": float(hedge_fraction),
                    "source_side": side_u,
                    "source": "profit_hedge_build",
                },
            ).to_dict()

            emitted = emit_proposal(self.redis, stream="wma:proposals", proposal=_proposal)
            if emitted:
                # Cooldown: shorter when high score (act sooner on strong signals)
                # 3-10 minutes, inversely scaled with reversal conviction
                _cd_ttl = int(max(180, min(600, 250.0 / max(0.1, reversal_score))))
                self.redis.setex(_cd_key, _cd_ttl, "1")
                logger.info(
                    "PROFIT_HEDGE_PROPOSED | sym=%s pos_side=%s opp=%s | "
                    "roe=%.1f%% min_roe=%.1f%% score=%.2f conf=%.2f "
                    "margin=%.2f frac=%.0f%% | "
                    "trainer=%s regime=%s tf_votes=%d/%d imb=%.2f atr4h=%.3f%% cd=%ds",
                    sym, side_u, _opp_action,
                    roe_pct, min_roe, reversal_score, _tconf,
                    hedge_margin, hedge_fraction * 100,
                    _tdir, _move_regime, _per_tf_votes, _per_tf_total,
                    opp_imbalance_factor, atr_pct_4h, _cd_ttl,
                )
            else:
                logger.debug(
                    "PROFIT_HEDGE_EMIT_SKIP | sym=%s side=%s score=%.2f",
                    sym, side_u, reversal_score,
                )
        except Exception as _prop_err:
            logger.warning("PROFIT_HEDGE_BUILD_ERR | sym=%s side=%s | %s", sym, side_u, _prop_err)

    def _monitor_loop(self):
        """Main monitoring loop - checks prices and triggers stops"""
        logger.info("[STEALTH-STOPS] 🔍 Monitoring loop started")
        
        while self._running:
            try:
                # Periodic exchange reconciliation to purge ghost stops
                if (time.time() - self._last_reconcile_ts) >= self._RECONCILE_INTERVAL_SEC:
                    try:
                        self._reconcile_with_exchange()
                    except Exception as _recon_err:
                        logger.debug("[STEALTH-RECONCILE] Periodic check failed: %s", _recon_err)

                with self._lock:
                    symbols_to_check = list(self.pending_stops.keys())
                    _total_stops = sum(len(v) for v in self.pending_stops.values())
                    _tp_stops = 0
                    _sl_stops = 0
                    _trail_stops = 0
                    try:
                        for _sym, _lst in (self.pending_stops or {}).items():
                            for _s in (_lst or []):
                                try:
                                    _st = str(getattr(_s, "stop_type", "") or "").upper()
                                    _reason_u = str(getattr(_s, "reason", "") or "").upper()
                                    if "TRAIL" in _reason_u:
                                        _trail_stops += 1
                                    if _st == "TAKE_PROFIT":
                                        _tp_stops += 1
                                    elif _st == "STOP_LOSS":
                                        _sl_stops += 1
                                except Exception:
                                    continue
                    except Exception:
                        pass

                # region agent log
                try:
                    import json as _aj_p
                    _ts_p = int(time.time() * 1000)
                    _last_p = int(globals().get("_AGENT_STEALTH_PRESENCE_LAST_868108", 0) or 0)
                    if (_ts_p - _last_p) >= 30_000:
                        globals()["_AGENT_STEALTH_PRESENCE_LAST_868108"] = _ts_p
                        try:
                            from config import STEALTH_STOP_LOSS_ENABLED as _SL_EN, STEALTH_TRAILING_ENABLED as _TR_EN
                            _sl_en_p = bool(_SL_EN)
                            _tr_en_p = bool(_TR_EN)
                        except Exception:
                            _sl_en_p = None
                            _tr_en_p = None
                        _bank = "BANKUSDT"
                        _aster = "ASTERUSDT"
                        try:
                            _bank_n = int(len((self.pending_stops or {}).get(_bank, []) or []))
                        except Exception:
                            _bank_n = 0
                        try:
                            _aster_n = int(len((self.pending_stops or {}).get(_aster, []) or []))
                        except Exception:
                            _aster_n = 0
                        _payload_p = {
                            "sessionId": "868108",
                            "id": f"log_{_ts_p}_stealth_pending_presence",
                            "timestamp": _ts_p,
                            "location": "trading/stealth_stops.py:_monitor_loop",
                            "message": "stealth_pending_stops_presence",
                            "runId": "pre-fix",
                            "hypothesisId": "H1",
                            "data": {
                                "account_id": str(getattr(self, "account_id", "") or ""),
                                "symbols_count": int(len(symbols_to_check or [])),
                                "total_stops": int(_total_stops),
                                "tp_stops": int(_tp_stops),
                                "sl_stops": int(_sl_stops),
                                "trail_stops": int(_trail_stops),
                                "stealth_stop_loss_enabled": _sl_en_p,
                                "stealth_trailing_enabled": _tr_en_p,
                                "has_BANKUSDT": bool(_bank_n > 0),
                                "has_ASTERUSDT": bool(_aster_n > 0),
                                "BANKUSDT_stop_count": int(_bank_n),
                                "ASTERUSDT_stop_count": int(_aster_n),
                            },
                        }
                        with open(
                            "/home/wali/Desktop/AI BOT/.cursor/debug-868108.log",
                            "a",
                            encoding="utf-8",
                        ) as _f_p:
                            _f_p.write(_aj_p.dumps(_payload_p, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion

                # region agent log
                try:
                    import json as _aj
                    _ts = int(time.time() * 1000)
                    _last_ts = int(globals().get("_AGENT_STEALTH_HB_LAST", 0) or 0)
                    if (_ts - _last_ts) >= 60_000:
                        globals()["_AGENT_STEALTH_HB_LAST"] = _ts
                        _payload = {
                            "sessionId": "53deb7",
                            "id": f"log_{_ts}_stealth_hb_{getattr(self, 'account_id', 'na')}",
                            "timestamp": _ts,
                            "location": "trading/stealth_stops.py:_monitor_loop",
                            "message": "stealth_stops_heartbeat",
                            "runId": "post-fix",
                            "hypothesisId": "H7",
                            "data": {
                                "account_id": str(getattr(self, "account_id", "") or ""),
                                "symbols_count": int(len(symbols_to_check or [])),
                                "total_stops": int(_total_stops),
                                "tp_stops": int(_tp_stops),
                                "sl_stops": int(_sl_stops),
                                "trail_stops": int(_trail_stops),
                            },
                        }
                        with open(
                            "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                            "a",
                            encoding="utf-8",
                        ) as _f:
                            _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion
                
                if not symbols_to_check:
                    time.sleep(5)
                    continue
                
                # Fetch current prices for all symbols with pending stops
                prices = self._fetch_mark_prices(symbols_to_check)
                
                # Check each symbol's stops
                for symbol in symbols_to_check:
                    current_price = prices.get(symbol)
                    if not current_price or current_price <= 0:
                        continue
                    
                    with self._lock:
                        stops_for_symbol = self.pending_stops.get(symbol, [])
                        triggered_stops = []

                        # region agent log
                        try:
                            _symu = str(symbol or "").upper().strip()
                            if _symu in ("BANKUSDT", "ASTERUSDT"):
                                import json as _aj
                                _ts = int(time.time() * 1000)
                                _m = globals().get("_AGENT_STEALTH_SUMMARY_LAST_868108", {}) or {}
                                try:
                                    _lt = int(_m.get(_symu, 0) or 0)
                                except Exception:
                                    _lt = 0
                                if (_ts - _lt) >= 30_000:
                                    _m[_symu] = _ts
                                    globals()["_AGENT_STEALTH_SUMMARY_LAST_868108"] = _m
                                    try:
                                        from config import STEALTH_STOP_LOSS_ENABLED as _SL_EN, STEALTH_TRAILING_ENABLED as _TR_EN
                                        _sl_en = bool(_SL_EN)
                                        _tr_en = bool(_TR_EN)
                                    except Exception:
                                        _sl_en = None
                                        _tr_en = None
                                    _types = {}
                                    try:
                                        for _s in (stops_for_symbol or []):
                                            _t = str(getattr(_s, "stop_type", "") or "").upper()
                                            _types[_t] = int(_types.get(_t, 0)) + 1
                                    except Exception:
                                        _types = {}
                                    _payload = {
                                        "sessionId": "868108",
                                        "id": f"log_{_ts}_stealth_stops_summary_{_symu}",
                                        "timestamp": _ts,
                                        "location": "trading/stealth_stops.py:_monitor_loop",
                                        "message": "stealth_stops_symbol_summary",
                                        "runId": "pre-fix",
                                        "hypothesisId": "H1",
                                        "data": {
                                            "account_id": str(getattr(self, "account_id", "") or ""),
                                            "symbol": _symu,
                                            "current_price": float(current_price or 0.0),
                                            "stop_count": int(len(stops_for_symbol or [])),
                                            "stop_types": _types,
                                            "stealth_stop_loss_enabled": _sl_en,
                                            "stealth_trailing_enabled": _tr_en,
                                        },
                                    }
                                    with open(
                                        "/home/wali/Desktop/AI BOT/.cursor/debug-868108.log",
                                        "a",
                                        encoding="utf-8",
                                    ) as _f:
                                        _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                        except Exception:
                            pass
                        # endregion
                        
                        # Prune phantom stops with zero/dust qty (< 1e-4 is unexecutable)
                        _zero_qty = [s for s in stops_for_symbol if float(getattr(s, 'position_size', 0) or 0) < 1e-4]
                        if _zero_qty:
                            for s in _zero_qty:
                                stops_for_symbol.remove(s)
                            if not stops_for_symbol:
                                self.pending_stops.pop(symbol, None)
                            self._save_to_redis()
                            logger.info(f"[STEALTH-PRUNE] Removed {len(_zero_qty)} zero-qty stops for {symbol}")
                            if not stops_for_symbol:
                                continue
                        
                        for stop in stops_for_symbol:
                            # ========================================================
                            # KILL SWITCHES: Check if this stop type is enabled
                            # ========================================================
                            try:
                                from config import STEALTH_STOP_LOSS_ENABLED, STEALTH_TAKE_PROFIT_ENABLED, STEALTH_TRAILING_ENABLED
                                _is_trail = 'TRAIL' in str(stop.reason or '').upper()
                                if _is_trail and not STEALTH_TRAILING_ENABLED:
                                    continue  # Skip trailing - disabled
                                if stop.stop_type == 'STOP_LOSS' and not STEALTH_STOP_LOSS_ENABLED and not _is_trail:
                                    # region agent log
                                    try:
                                        import json as _aj
                                        _ts = int(time.time() * 1000)
                                        _symu = str(stop.symbol or "").upper().strip()
                                        _m = globals().get("_AGENT_SL_DISABLED_LAST", {}) or {}
                                        try:
                                            _lt = int(_m.get(_symu, 0) or 0)
                                        except Exception:
                                            _lt = 0
                                        if (_ts - _lt) >= 60_000:
                                            _m[_symu] = _ts
                                            globals()["_AGENT_SL_DISABLED_LAST"] = _m
                                            _payload = {
                                                "sessionId": "53deb7",
                                                "id": f"log_{_ts}_sl_skipped_disabled_{_symu}",
                                                "timestamp": _ts,
                                                "location": "trading/stealth_stops.py:_monitor_loop",
                                                "message": "stop_loss_skipped_disabled",
                                                "runId": "post-fix",
                                                "hypothesisId": "H9",
                                                "data": {
                                                    "account_id": str(getattr(self, "account_id", "") or ""),
                                                    "symbol": _symu,
                                                    "side": str(stop.side or ""),
                                                    "stop_type": str(stop.stop_type or ""),
                                                    "reason": str(getattr(stop, "reason", "") or "")[:120],
                                                    "trigger_price": float(getattr(stop, "trigger_price", 0) or 0),
                                                    "position_size": float(getattr(stop, "position_size", 0) or 0),
                                                },
                                            }
                                            with open(
                                                "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                                                "a",
                                                encoding="utf-8",
                                            ) as _f:
                                                _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                                    except Exception:
                                        pass
                                    # endregion
                                    continue  # Skip non-trailing stop loss - disabled
                                if self._is_tp_stop(stop) and not STEALTH_TAKE_PROFIT_ENABLED:
                                    continue  # Skip take profit - disabled
                            except ImportError:
                                pass  # Config not available, allow all
                            
                            # CRITICAL: Validate price reasonableness before triggering
                            # This prevents false triggers from corrupt/stale prices
                            # FIX: Increased threshold from 20% to 50% because:
                            # - Stops may have been set at different price levels (historical entries)
                            # - During volatile periods, prices can move 30-40% from entry
                            # - The 20% threshold was causing legitimate stops to be skipped
                            if stop.trigger_price > 0:
                                deviation_pct = abs(current_price - stop.trigger_price) / stop.trigger_price * 100
                                if deviation_pct > 50:  # More than 50% deviation is suspicious - reject
                                    logger.warning(
                                        f"⚠️ [STEALTH-SKIP-STALE] {stop.symbol} {stop.side}: "
                                        f"price={current_price:.4f} is {deviation_pct:.1f}% from trigger={stop.trigger_price:.4f} "
                                        f"- SKIPPING (stop may need refresh)"
                                    )
                                    continue  # Skip this stop, don't trigger on bad data
                            
                            # ========================================================
                            # TRAINER INTENT TP DEFERENCE — Gate ALL TP paths
                            # If position aligns with trainer's high-confidence
                            # directional intent, SUPPRESS TP entirely.  Let the
                            # trainer decide when to exit via CLOSE/FLIP signals.
                            # This must run BEFORE maker/IOC/static TP paths.
                            # ========================================================
                            if self._is_static_tp_stop(stop):
                                try:
                                    from config import TRAINER_INTENT_TP_DEFERENCE_ENABLED, TRAINER_INTENT_TP_MIN_CONFIDENCE
                                    _ti_defer_on = bool(TRAINER_INTENT_TP_DEFERENCE_ENABLED)
                                    _ti_min_conf = float(TRAINER_INTENT_TP_MIN_CONFIDENCE)
                                except Exception:
                                    _ti_defer_on = False
                                    _ti_min_conf = 0.80
                                if _ti_defer_on:
                                    try:
                                        from risk.trainer_intent import get_intent
                                        _ti = get_intent(self.redis, stop.symbol)
                                        if (_ti is not None
                                            and not _ti.is_stale
                                            and _ti.is_directional
                                            and _ti.confidence >= _ti_min_conf
                                            and _ti.aligns_with_position(stop.side)):
                                            logger.info(
                                                "[TRAINER_INTENT_TP_DEFER] sym=%s side=%s: TP SUPPRESSED — "
                                                "trainer intent %s conf=%.3f age=%.0fs. "
                                                "Trainer controls exit timing.",
                                                stop.symbol, stop.side, _ti.direction,
                                                _ti.confidence, _ti.age_seconds,
                                            )
                                            # region agent log
                                            try:
                                                import json as _aj
                                                _ts = int(time.time() * 1000)
                                                _symu = str(stop.symbol or "").upper().strip()
                                                _k = f"{_symu}:{str(stop.side or '').upper()}"
                                                _m = globals().get("_AGENT_TP_DEFER_LAST", {}) or {}
                                                try:
                                                    _lt = int(_m.get(_k, 0) or 0)
                                                except Exception:
                                                    _lt = 0
                                                if (_ts - _lt) >= 60_000:
                                                    _m[_k] = _ts
                                                    globals()["_AGENT_TP_DEFER_LAST"] = _m
                                                    _payload = {
                                                        "sessionId": "53deb7",
                                                        "id": f"log_{_ts}_tp_defer_{_k}",
                                                        "timestamp": _ts,
                                                        "location": "trading/stealth_stops.py:_monitor_loop",
                                                        "message": "tp_deferred_by_trainer_intent",
                                                        "runId": "post-fix",
                                                        "hypothesisId": "H6",
                                                        "data": {
                                                            "account_id": str(getattr(self, "account_id", "") or ""),
                                                            "symbol": _symu,
                                                            "side": str(stop.side or ""),
                                                            "intent_dir": str(_ti.direction),
                                                            "intent_conf": float(_ti.confidence),
                                                            "intent_age_s": float(_ti.age_seconds),
                                                            "min_conf": float(_ti_min_conf),
                                                        },
                                                    }
                                                    with open(
                                                        "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                                                        "a",
                                                        encoding="utf-8",
                                                    ) as _f:
                                                        _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                                            except Exception:
                                                pass
                                            # endregion
                                            continue  # Skip ALL TP paths for this stop
                                    except Exception as _ti_err:
                                        logger.debug("[TRAINER_INTENT_TP_DEFER] check error: %s", _ti_err)

                            # ========================================================
                            # TF-SOURCED HOLD LOCK: prevent premature TP for 1h/4h
                            # positions within their min_hold_sec window.
                            # SL always executes (safety takes priority).
                            # ========================================================
                            if self._is_static_tp_stop(stop):
                                try:
                                    _hl_r = getattr(self, 'redis', None)
                                    if _hl_r:
                                        _src_tf_raw = _hl_r.get(f"position_meta:{stop.symbol}:source_tf")
                                        if _src_tf_raw:
                                            _src_tf = _src_tf_raw.decode() if isinstance(_src_tf_raw, bytes) else str(_src_tf_raw)
                                            if _src_tf in ("1h", "4h"):
                                                from config import TF_EXIT_PROFILES
                                                _profile = TF_EXIT_PROFILES.get(_src_tf, {})
                                                _min_hold = float(_profile.get("min_hold_sec", 0))
                                                if _min_hold > 0:
                                                    _open_ts_raw = _hl_r.get(f"position_meta:{stop.symbol}:open_ts")
                                                    _open_ts = float(_open_ts_raw) if _open_ts_raw else 0.0
                                                    _held_sec = time.time() - _open_ts if _open_ts > 0 else 99999
                                                    if _held_sec < _min_hold:
                                                        logger.info(
                                                            "[STEALTH_TP_TF_HOLD_LOCK] sym=%s tf=%s held=%.0fs < min_hold=%.0fs → TP DEFERRED",
                                                            stop.symbol, _src_tf, _held_sec, _min_hold,
                                                        )
                                                        # region agent log
                                                        try:
                                                            import json as _aj
                                                            _ts = int(time.time() * 1000)
                                                            _symu = str(stop.symbol or "").upper().strip()
                                                            _k = f"{_symu}:{_src_tf}"
                                                            _m = globals().get("_AGENT_TP_HOLD_LAST", {}) or {}
                                                            try:
                                                                _lt = int(_m.get(_k, 0) or 0)
                                                            except Exception:
                                                                _lt = 0
                                                            if (_ts - _lt) >= 60_000:
                                                                _m[_k] = _ts
                                                                globals()["_AGENT_TP_HOLD_LAST"] = _m
                                                                _payload = {
                                                                    "sessionId": "53deb7",
                                                                    "id": f"log_{_ts}_tp_hold_{_k}",
                                                                    "timestamp": _ts,
                                                                    "location": "trading/stealth_stops.py:_monitor_loop",
                                                                    "message": "tp_deferred_by_tf_hold_lock",
                                                                    "runId": "post-fix",
                                                                    "hypothesisId": "H6",
                                                                    "data": {
                                                                        "account_id": str(getattr(self, "account_id", "") or ""),
                                                                        "symbol": _symu,
                                                                        "source_tf": str(_src_tf),
                                                                        "held_sec": float(_held_sec),
                                                                        "min_hold_sec": float(_min_hold),
                                                                    },
                                                                }
                                                                with open(
                                                                    "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                                                                    "a",
                                                                    encoding="utf-8",
                                                                ) as _f:
                                                                    _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                                                        except Exception:
                                                            pass
                                                        # endregion
                                                        continue
                                except Exception as _hl_err:
                                    logger.debug("[STEALTH_TP_TF_HOLD_LOCK] error: %s", _hl_err)

                            # ========================================================
                            # TP TOUCH TRACKING + MAKER PLACEMENT + IOC FALLBACK
                            # ========================================================
                            if self._is_tp_stop(stop):
                                try:
                                    from config import (
                                        TP_TOUCH_FALLBACK_ENABLED,
                                        TP_TOUCH_FALLBACK_SEC,
                                        TP_TOUCH_CONFIRM_TICKS,
                                        TP_TOUCH_BUFFER_BPS,
                                        TP_MAKER_NEAR_ENABLED,
                                        TP_MAKER_COOLDOWN_SEC,
                                        TP_FASTMOVE_DIRECT_IOC,
                                        TP_FASTMOVE_SCORE_MIN,
                                        TP_POSTONLY_REJECT_MAX,
                                        TP_MONITOR_HEARTBEAT_SEC,
                                    )
                                except Exception:
                                    TP_TOUCH_FALLBACK_ENABLED = True
                                    TP_TOUCH_FALLBACK_SEC = 2.5
                                    TP_TOUCH_CONFIRM_TICKS = 2
                                    TP_TOUCH_BUFFER_BPS = 5.0
                                    TP_MAKER_NEAR_ENABLED = True
                                    TP_MAKER_COOLDOWN_SEC = 10
                                    TP_FASTMOVE_DIRECT_IOC = True
                                    TP_FASTMOVE_SCORE_MIN = 0.8
                                    TP_POSTONLY_REJECT_MAX = 2
                                    TP_MONITOR_HEARTBEAT_SEC = 60

                                side_u = str(stop.side or "").upper()
                                if side_u in ("LONG", "SHORT") and float(stop.trigger_price or 0) > 0:
                                    if self._is_trailing_tp_stop(stop):
                                        try:
                                            if self._sanitize_trailing_tp_trigger(stop, current_price):
                                                self._save_to_redis()
                                        except Exception:
                                            pass
                                    tp = float(stop.trigger_price)
                                    buf = max(0.0, float(TP_TOUCH_BUFFER_BPS)) / 10000.0
                                    _is_trailing_tp = self._is_trailing_tp_stop(stop)

                                    _ep_chk = float(getattr(stop, 'entry_price', 0) or 0.0)
                                    if _ep_chk > 0 and not _is_trailing_tp:
                                        _wrong_dir_tp = (side_u == "LONG" and tp < _ep_chk * 0.998) or (side_u == "SHORT" and tp > _ep_chk * 1.002)
                                        if _wrong_dir_tp:
                                            logger.warning(
                                                "[TP_WRONG_DIR_EVICT] sym=%s side=%s tp=%.6f entry=%.6f reason=%s → REMOVING",
                                                stop.symbol, side_u, tp, _ep_chk, str(getattr(stop, 'reason', ''))[:60],
                                            )
                                            try:
                                                self.pending_stops[symbol].remove(stop)
                                                if not self.pending_stops[symbol]:
                                                    del self.pending_stops[symbol]
                                                self._save_to_redis()
                                            except Exception:
                                                pass
                                            continue

                                    touched = False
                                    if side_u == "LONG":
                                        touched = current_price <= tp * (1.0 + buf) if _is_trailing_tp else current_price >= tp * (1.0 - buf)
                                    else:
                                        touched = current_price >= tp * (1.0 - buf) if _is_trailing_tp else current_price <= tp * (1.0 + buf)

                                    hb_key = f"{stop.symbol}:{side_u}"
                                    now_ts = time.time()
                                    hb_sec = float(TP_MONITOR_HEARTBEAT_SEC or 0)
                                    if hb_sec > 0 and (now_ts - float(self._tp_monitor_hb_ts.get(hb_key, 0.0) or 0.0)) >= hb_sec:
                                        self._tp_monitor_hb_ts[hb_key] = now_ts
                                        bid = 0.0
                                        ask = 0.0
                                        has_book = False
                                        try:
                                            if self.redis:
                                                ob_raw = self.redis.get(f"orderbook:top:{stop.symbol}")
                                                if ob_raw:
                                                    if isinstance(ob_raw, (bytes, bytearray)):
                                                        ob_raw = ob_raw.decode("utf-8", errors="ignore")
                                                    if isinstance(ob_raw, str):
                                                        ob = json.loads(ob_raw) or {}
                                                    else:
                                                        ob = {}
                                                    bid = float(ob.get("bid") or ob.get("best_bid_px") or 0.0)
                                                    ask = float(ob.get("ask") or ob.get("best_ask_px") or 0.0)
                                                    has_book = bid > 0 and ask > 0
                                        except Exception:
                                            pass
                                        dist_bps = 0.0
                                        if tp > 0:
                                            try:
                                                dist_bps = abs(current_price - tp) / tp * 10000.0
                                            except Exception:
                                                dist_bps = 0.0
                                        touch_th_bps = buf * 10000.0
                                        close_side = "SELL" if side_u == "LONG" else "BUY"
                                        logger.info(
                                            f"[TP_MONITOR_HEARTBEAT] sym={stop.symbol} side={side_u} close_side={close_side} "
                                            f"armed=1 has_book={has_book} bid={bid:.6f} ask={ask:.6f} "
                                            f"px={current_price:.6f} tp={tp:.6f} dist_bps={dist_bps:.2f} "
                                            f"touch_th_bps={touch_th_bps:.2f} touched={int(touched)}"
                                        )
                                    if touched:
                                        key = f"{stop.symbol}:{side_u}:{stop.stop_type}"
                                        st = self._tp_touch_state.get(key, {"count": 0, "first_ts": 0.0, "last_maker_ts": 0.0, "rejects": 0})
                                        now_ts = time.time()
                                        if st.get("first_ts", 0.0) <= 0:
                                            st["first_ts"] = now_ts
                                        st["count"] = int(st.get("count", 0) or 0) + 1
                                        self._tp_touch_state[key] = st

                                        touch_age = float(now_ts - float(st.get("first_ts", 0.0) or 0.0))
                                        logger.info(
                                            f"[TP_TOUCH] sym={stop.symbol} side={side_u} count={st.get('count', 0)} age={touch_age:.2f}s "
                                            f"px={current_price:.6f} tp={tp:.6f}"
                                        )

                                        # Maker placement near touch (post-only)
                                        if TP_MAKER_NEAR_ENABLED:
                                            last_maker_ts = float(st.get("last_maker_ts", 0.0) or 0.0)
                                            if (now_ts - last_maker_ts) >= float(TP_MAKER_COOLDOWN_SEC or 0):
                                                st["last_maker_ts"] = now_ts
                                                self._tp_touch_state[key] = st
                                                order_side = "SELL" if side_u == "LONG" else "BUY"
                                                position_side = side_u  # hedge mode
                                                qty = float(stop.position_size * (stop.close_percentage / 100.0))
                                                # P0 Guardrail: block/cap hedge TP trims on SHORT leg while LONG is at risk
                                                try:
                                                    if str(stop.stop_type or '').upper() == 'TAKE_PROFIT' and str(side_u) == 'SHORT':
                                                        allow, adj_qty, reason, meta = self._hedge_tp_guard(stop.symbol, float(qty or 0.0), float(current_price or tp or 0.0))
                                                        if not allow or float(adj_qty or 0.0) <= 0:
                                                            if str(reason) == "STEALTH_TP_SKIPPED_STRESS_FREEZE":
                                                                logger.warning(
                                                                    "STEALTH_TP_SKIPPED_STRESS_FREEZE | sym=%s side=SHORT phase=maker liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f",
                                                                    stop.symbol,
                                                                    f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                    float(meta.get('long_qty') or 0.0),
                                                                    float(meta.get('short_qty') or 0.0),
                                                                    float(meta.get('requested_qty') or 0.0),
                                                                )
                                                            logger.warning(
                                                                "HEDGE_TP_GUARD_TOUCH | sym=%s side=SHORT phase=maker reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=0.0",
                                                                stop.symbol,
                                                                reason,
                                                                f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                float(meta.get('long_qty') or 0.0),
                                                                float(meta.get('short_qty') or 0.0),
                                                                float(meta.get('requested_qty') or 0.0),
                                                            )
                                                            continue
                                                        if float(adj_qty) + 1e-12 < float(qty or 0.0):
                                                            logger.warning(
                                                                "HEDGE_TP_GUARD_TOUCH | sym=%s side=SHORT phase=maker reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=%.6f",
                                                                stop.symbol,
                                                                reason,
                                                                f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                float(meta.get('long_qty') or 0.0),
                                                                float(meta.get('short_qty') or 0.0),
                                                                float(meta.get('requested_qty') or 0.0),
                                                                float(adj_qty or 0.0),
                                                            )
                                                            qty = float(adj_qty)
                                                except Exception:
                                                    pass
                                                try:
                                                    limit_order = self._place_limit_order(
                                                        stop.symbol,
                                                        order_side,
                                                        position_side,
                                                        tp,
                                                        qty,
                                                        'GTX',
                                                        reduce_only=True,
                                                    )
                                                    if not limit_order:
                                                        raise RuntimeError("limit_order_not_placed")
                                                    logger.info(
                                                        f"[TP_MAKER_PLACED] sym={stop.symbol} side={side_u} tp={tp:.6f} qty={qty:.6f} "
                                                        f"order_id={limit_order.get('orderId')}"
                                                    )
                                                except Exception as limit_err:
                                                    err_str = str(limit_err)
                                                    if '-5022' in err_str or 'would immediately match' in err_str.lower():
                                                        st["rejects"] = int(st.get("rejects", 0) or 0) + 1
                                                        self._tp_touch_state[key] = st
                                                        if int(st.get("rejects", 0)) >= int(TP_POSTONLY_REJECT_MAX or 0):
                                                            order_side = "SELL" if side_u == "LONG" else "BUY"
                                                            position_side = side_u
                                                            ioc_px = current_price
                                                            logger.warning(
                                                                f"[TP_IOC_FALLBACK] sym={stop.symbol} side={side_u} reason=postonly_rejects "
                                                                f"qty={qty:.6f} px={ioc_px:.6f}"
                                                            )
                                                            order = self._execute_ioc_order(
                                                                stop.symbol,
                                                                order_side,
                                                                position_side,
                                                                qty,
                                                                ioc_px,
                                                                stop,
                                                            )
                                                            if order:
                                                                self._finalize_stop_execution(stop, order, current_price, exec_method="IOC", used_limit=False)
                                                                triggered_stops.append(stop)
                                                                continue
                                                        # Reprice one tick away using small buffer
                                                        adj = max(0.0, buf)
                                                        if order_side == "BUY":
                                                            new_px = min(tp, current_price * (1.0 - adj))
                                                        else:
                                                            new_px = max(tp, current_price * (1.0 + adj))
                                                        try:
                                                            limit_order = self._place_limit_order(
                                                                stop.symbol,
                                                                order_side,
                                                                position_side,
                                                                new_px,
                                                                qty,
                                                                'GTX',
                                                                reduce_only=True,
                                                            )
                                                            if not limit_order:
                                                                raise RuntimeError("limit_order_not_placed")
                                                            logger.info(
                                                                f"[TP_POSTONLY_REPRICE] sym={stop.symbol} side={side_u} new_px={new_px:.6f} "
                                                                f"order_id={limit_order.get('orderId')}"
                                                            )
                                                        except Exception as reprice_err:
                                                            st["rejects"] = int(st.get("rejects", 0) or 0) + 1
                                                            self._tp_touch_state[key] = st
                                                            if int(st.get("rejects", 0)) >= int(TP_POSTONLY_REJECT_MAX or 0):
                                                                order_side = "SELL" if side_u == "LONG" else "BUY"
                                                                position_side = side_u
                                                                ioc_px = current_price
                                                                logger.warning(
                                                                    f"[TP_IOC_FALLBACK] sym={stop.symbol} side={side_u} reason=postonly_rejects "
                                                                    f"qty={qty:.6f} px={ioc_px:.6f}"
                                                                )
                                                                order = self._execute_ioc_order(
                                                                    stop.symbol,
                                                                    order_side,
                                                                    position_side,
                                                                    qty,
                                                                    ioc_px,
                                                                    stop,
                                                                )
                                                                if order:
                                                                    self._finalize_stop_execution(stop, order, current_price, exec_method="IOC", used_limit=False)
                                                                    triggered_stops.append(stop)
                                                                    continue
                                                            logger.info(
                                                                f"[TP_MAKER_SKIP] sym={stop.symbol} side={side_u} reason={reprice_err}"
                                                            )
                                                    else:
                                                        logger.info(
                                                            f"[TP_MAKER_SKIP] sym={stop.symbol} side={side_u} reason={limit_err}"
                                                        )

                                        # IOC fallback if touch persists or fast move
                                        fallback = bool(TP_TOUCH_FALLBACK_ENABLED)
                                        if fallback:
                                            confirm_ticks = int(TP_TOUCH_CONFIRM_TICKS or 0)
                                            trigger_by_ticks = int(st.get("count", 0)) >= max(1, confirm_ticks)
                                            trigger_by_time = touch_age >= float(TP_TOUCH_FALLBACK_SEC or 0)
                                            fast_move = False
                                            if TP_FASTMOVE_DIRECT_IOC:
                                                try:
                                                    feats = self._fetch_market_features(stop.symbol)
                                                    fast_score = float(feats.get("fast_move_score", 0) or 0.0)
                                                    fast_move = fast_score >= float(TP_FASTMOVE_SCORE_MIN)
                                                except Exception:
                                                    fast_move = False
                                            if trigger_by_ticks or trigger_by_time or fast_move:
                                                order_side = "SELL" if side_u == "LONG" else "BUY"
                                                position_side = side_u
                                                qty = float(stop.position_size * (stop.close_percentage / 100.0))
                                                qty = round(qty, 3)
                                                # P0 Guardrail: block/cap hedge TP trims on SHORT leg while LONG is at risk
                                                try:
                                                    if str(stop.stop_type or '').upper() == 'TAKE_PROFIT' and str(side_u) == 'SHORT':
                                                        allow, adj_qty, reason, meta = self._hedge_tp_guard(stop.symbol, float(qty or 0.0), float(current_price or tp or 0.0))
                                                        if not allow or float(adj_qty or 0.0) <= 0:
                                                            if str(reason) == "STEALTH_TP_SKIPPED_STRESS_FREEZE":
                                                                logger.warning(
                                                                    "STEALTH_TP_SKIPPED_STRESS_FREEZE | sym=%s side=SHORT phase=ioc liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f",
                                                                    stop.symbol,
                                                                    f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                    float(meta.get('long_qty') or 0.0),
                                                                    float(meta.get('short_qty') or 0.0),
                                                                    float(meta.get('requested_qty') or 0.0),
                                                                )
                                                            logger.warning(
                                                                "HEDGE_TP_GUARD_TOUCH | sym=%s side=SHORT phase=ioc reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=0.0",
                                                                stop.symbol,
                                                                reason,
                                                                f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                float(meta.get('long_qty') or 0.0),
                                                                float(meta.get('short_qty') or 0.0),
                                                                float(meta.get('requested_qty') or 0.0),
                                                            )
                                                            continue
                                                        if float(adj_qty) + 1e-12 < float(qty or 0.0):
                                                            logger.warning(
                                                                "HEDGE_TP_GUARD_TOUCH | sym=%s side=SHORT phase=ioc reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=%.6f",
                                                                stop.symbol,
                                                                reason,
                                                                f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                                                                float(meta.get('long_qty') or 0.0),
                                                                float(meta.get('short_qty') or 0.0),
                                                                float(meta.get('requested_qty') or 0.0),
                                                                float(adj_qty or 0.0),
                                                            )
                                                            qty = float(adj_qty)
                                                except Exception:
                                                    pass
                                                # IOC price slightly through to ensure fill
                                                adj = max(0.0, buf)
                                                if order_side == "BUY":
                                                    ioc_px = current_price * (1.0 + adj)
                                                else:
                                                    ioc_px = current_price * (1.0 - adj)
                                                logger.warning(
                                                    f"[TP_IOC_FALLBACK] sym={stop.symbol} side={side_u} reason="
                                                    f"{'fast_move' if fast_move else 'touch_confirm'} qty={qty:.6f} px={ioc_px:.6f}"
                                                )
                                                # ── PROPOSE_ONLY MODE ─────────────────────────────────
                                                # When STEALTH_STOPS_MODE=propose_only, emit a STEALTH_TP
                                                # proposal to wma:proposals instead of placing the order
                                                # directly.  The orchestrator fast lane (50ms window) picks
                                                # it up and publishes to signals:trading:primary.
                                                # NOTE: Uses STEALTH_TP category (not PROTECTIVE) so it
                                                # remains subject to fee budget and confidence checks.
                                                try:
                                                    from config import STEALTH_STOPS_MODE
                                                except Exception:
                                                    STEALTH_STOPS_MODE = "direct"
                                                if str(STEALTH_STOPS_MODE).strip().lower() == "propose_only":
                                                    try:
                                                        import json as _ss_json
                                                        _close_pct = float(stop.close_percentage or 100.0)
                                                        _close_frac = _close_pct / 100.0
                                                        _propose_action = f"PARTIAL_CLOSE_{side_u}" if _close_pct < 99.9 else f"CLOSE_{side_u}"
                                                        _proposal = {
                                                            "action": _propose_action,
                                                            "action_name": _propose_action,
                                                            "action_category": "STEALTH_TP",
                                                            "action_type": "close",
                                                            "symbol": stop.symbol,
                                                            "account_id": getattr(self, "account_id", "primary"),
                                                            "confidence": 0.97,
                                                            "risk_reducing": True,
                                                            "reduce_only": True,
                                                            "urgency": "HIGH",
                                                            "close_fraction": _close_frac,
                                                            "close_percentage": _close_pct,
                                                            "qty": float(qty),
                                                            "ioc_price": float(ioc_px),
                                                            "order_side": order_side,
                                                            "position_side": position_side,
                                                            "stop_type": str(stop.stop_type or "TAKE_PROFIT"),
                                                            "source": "stealth_stops",
                                                            "source_module": "stealth_stops",
                                                            "trigger_reason": "fast_move" if fast_move else "touch_confirm",
                                                            "proposal_stream": "proposals:stealth_stops",
                                                            "priority": 3,
                                                            "created_ts_ms": int(time.time() * 1000),
                                                        }
                                                        _redis_prop = getattr(self, "redis", None)
                                                        if _redis_prop:
                                                            _redis_prop.xadd(
                                                                "wma:proposals",
                                                                {"data": _ss_json.dumps(_proposal, separators=(",", ":"), default=str)},
                                                                maxlen=50000,
                                                                approximate=True,
                                                            )
                                                            logger.info(
                                                                "STEALTH_STOP_PROPOSED | sym=%s side=%s action=%s qty=%.6f px=%.6f reason=%s",
                                                                stop.symbol, side_u, _propose_action, qty, ioc_px,
                                                                _proposal["trigger_reason"],
                                                            )
                                                            continue  # Don't place direct order
                                                    except Exception as _prop_err:
                                                        logger.warning(
                                                            "STEALTH_STOP_PROPOSE_FAIL | sym=%s | %s | -> fallback to direct",
                                                            stop.symbol, _prop_err,
                                                        )
                                                        # Fall through to direct execution on proposal error
                                                order = self._execute_ioc_order(
                                                    stop.symbol,
                                                    order_side,
                                                    position_side,
                                                    qty,
                                                    ioc_px,
                                                    stop,
                                                )
                                                if order:
                                                    self._finalize_stop_execution(stop, order, current_price, exec_method="IOC", used_limit=False)
                                                    triggered_stops.append(stop)
                                                    continue

                            # ── PHASE 2: Dynamic TP recalculation on every tick ──
                            if self._is_static_tp_stop(stop):
                                _pre_tp = float(stop.trigger_price)
                                try:
                                    self._recalculate_tp_dynamic(stop, current_price)
                                except Exception:
                                    pass
                                _post_tp = float(stop.trigger_price)
                                try:
                                    if _pre_tp > 0 and _post_tp > 0:
                                        _d = abs(_post_tp - _pre_tp) / max(_pre_tp, 1e-12)
                                    else:
                                        _d = 0.0
                                except Exception:
                                    _d = 0.0
                                if _d >= 0.001:
                                    # region agent log
                                    try:
                                        import json as _aj
                                        import json as _j2
                                        _ts = int(time.time() * 1000)
                                        _symu = str(stop.symbol or "").upper().strip()
                                        _m = globals().get("_AGENT_TP_UPDATE_LAST", {}) or {}
                                        try:
                                            _lt = int(_m.get(_symu, 0) or 0)
                                        except Exception:
                                            _lt = 0
                                        if (_ts - _lt) >= 60_000:
                                            _m[_symu] = _ts
                                            globals()["_AGENT_TP_UPDATE_LAST"] = _m
                                            _reg = {}
                                            try:
                                                _raw = self.redis.get(f"regime:{_symu}") if self.redis else None
                                                if _raw:
                                                    _reg = _j2.loads(
                                                        _raw.decode("utf-8", errors="ignore")
                                                        if isinstance(_raw, (bytes, bytearray))
                                                        else str(_raw)
                                                    )
                                            except Exception:
                                                _reg = {}
                                            _payload = {
                                                "sessionId": "53deb7",
                                                "id": f"log_{_ts}_tp_updated_{_symu}",
                                                "timestamp": _ts,
                                                "location": "trading/stealth_stops.py:_monitor_loop",
                                                "message": "tp_dynamic_trigger_updated",
                                                "runId": "post-fix",
                                                "hypothesisId": "H8",
                                                "data": {
                                                    "account_id": str(getattr(self, "account_id", "") or ""),
                                                    "symbol": _symu,
                                                    "side": str(stop.side or ""),
                                                    "entry_price": float(getattr(stop, "entry_price", 0) or 0),
                                                    "current_price": float(current_price or 0),
                                                    "old_tp": float(_pre_tp),
                                                    "new_tp": float(_post_tp),
                                                    "delta_rel": float(_d),
                                                    "move_regime": str(_reg.get("move_regime") or ""),
                                                    "trend_direction": str(_reg.get("trend_direction") or ""),
                                                    "tf_alignment": float(_reg.get("tf_alignment") or 0.0),
                                                    "volatility_score": float(_reg.get("volatility_score") or 0.0),
                                                },
                                            }
                                            with open(
                                                "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                                                "a",
                                                encoding="utf-8",
                                            ) as _f:
                                                _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                                    except Exception:
                                        pass
                                    # endregion

                                # ── FIX 11 (Redesign v2): Adaptive Trail V2 ──────
                                # Once position is profitable enough, trail TP at
                                # ATR distance behind best price to lock profits.
                                try:
                                    self._adaptive_trail_v2_check(stop, current_price)
                                except Exception:
                                    pass

                                # ── PHASE 2b: Profit-triggered opposite hedge building ──
                                # When position is profitable and trainer signals reversal /
                                # mean-reversion, slowly build an opposite hedge leg.
                                # Cooldown-gated per symbol+side to prevent churn.
                                try:
                                    _ep_phg = float(getattr(stop, "entry_price", 0) or 0)
                                    _qty_phg = float(getattr(stop, "position_size", 0) or 0)
                                    if _ep_phg > 0 and _qty_phg > 0:
                                        self._maybe_propose_profit_hedge(
                                            stop.symbol, stop.side,
                                            current_price, _ep_phg, _qty_phg,
                                        )
                                except Exception:
                                    pass

                            # ── RAMP Phase 1+6: Microstructure trail compression ──
                            # For trailing SL stops, dynamically tighten the trigger
                            # when microstructure confirms a genuine adverse move.
                            #
                            # ── NEW: Dynamic SL recalculation for non-trail SL ──
                            # Widen SL when regime is trending in favor, tighten when
                            # conditions deteriorate. Leverage-aware.
                            if stop.stop_type == "STOP_LOSS" and "TRAIL" not in str(stop.reason or "").upper():
                                try:
                                    self._recalculate_sl_dynamic(stop, current_price)
                                except Exception:
                                    pass

                            if stop.stop_type == "STOP_LOSS" and "TRAIL" in str(stop.reason or "").upper():
                                try:
                                    _ramp_leverage = 1.0
                                    try:
                                        if self.redis:
                                            for _racc in (self.account_id, "primary"):
                                                _plk = f"positions:live:{_racc}:{stop.symbol.upper()}"
                                                _plr = self.redis.hgetall(_plk)
                                                if _plr:
                                                    _pld = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _plr.items()}
                                                    _rl = float(_pld.get("leverage", 0) or 0)
                                                    if _rl > 1:
                                                        _ramp_leverage = _rl
                                                        break
                                    except Exception:
                                        pass


                                    _comp = self._microstructure_trail_compression(
                                        stop.symbol, stop.side, _ramp_leverage,
                                    )
                                    if _comp < 0.95:
                                        _old_trigger = float(stop.trigger_price)
                                        _entry_px = float(getattr(stop, "entry_price", 0) or 0)
                                        if _entry_px <= 0:
                                            _entry_px = current_price

                                        if stop.side.upper() == "LONG":
                                            _base_dist = (_old_trigger - current_price) / current_price if current_price > 0 else 0
                                            _new_dist = _base_dist * _comp
                                            _new_trigger = current_price * (1.0 + _new_dist)
                                            _new_trigger = max(_new_trigger, _old_trigger)
                                        else:
                                            _base_dist = (current_price - _old_trigger) / current_price if current_price > 0 else 0
                                            _new_dist = _base_dist * _comp
                                            _new_trigger = current_price * (1.0 - _new_dist)
                                            _new_trigger = min(_new_trigger, _old_trigger)

                                        if abs(_new_trigger - _old_trigger) / max(_old_trigger, 1e-12) > 0.0005:
                                            stop.trigger_price = _new_trigger
                                            logger.info(
                                                "RAMP_TRAIL_TIGHTEN | sym=%s side=%s | old=%.6f new=%.6f | "
                                                "comp=%.2f lev=%.0fx px=%.6f",
                                                stop.symbol, stop.side, _old_trigger, _new_trigger,
                                                _comp, _ramp_leverage, current_price,
                                            )
                                    # ── RAMP Phase 4: Update exchange backstop ──
                                    try:
                                        self._update_exchange_backstop(
                                            stop.symbol, stop.side, current_price,
                                            _ramp_leverage, float(stop.trigger_price),
                                            float(stop.position_size),
                                        )
                                    except Exception as _bs_err:
                                        logger.debug("BACKSTOP_UPDATE_ERR | %s | %s", stop.symbol, _bs_err)
                                except Exception as _ramp_err:
                                    logger.debug("RAMP_TRAIL_COMPRESS_ERR | %s | %s", stop.symbol, _ramp_err)

                            # Same reversal→hedge builder as TP path, but for trailing stops (STOP_LOSS+TRAIL).
                            if stop.stop_type == "STOP_LOSS" and "TRAIL" in str(stop.reason or "").upper():
                                try:
                                    from config import STEALTH_TRAIL_PROFIT_HEDGE_ENABLED

                                    if bool(STEALTH_TRAIL_PROFIT_HEDGE_ENABLED):
                                        _ep_t = float(getattr(stop, "entry_price", 0) or 0)
                                        _qty_t = float(getattr(stop, "position_size", 0) or 0)
                                        if _ep_t > 0 and _qty_t > 0:
                                            self._maybe_propose_profit_hedge(
                                                stop.symbol, stop.side,
                                                current_price, _ep_t, _qty_t,
                                            )
                                except Exception:
                                    pass

                            if stop.should_trigger(current_price):
                                # ========================================================
                                # PROFIT-LOCK CONFIRMATION (anti-wick)
                                # Require stop condition to persist for ticks or seconds.
                                # ========================================================
                                try:
                                    is_profit_lock = "PROFIT_LOCK" in str(stop.reason or "").upper()
                                    if is_profit_lock:
                                        try:
                                            from config import PROFIT_LOCK_CONFIRM_TICKS, PROFIT_LOCK_CONFIRM_SECS
                                        except Exception:
                                            PROFIT_LOCK_CONFIRM_TICKS = 2
                                            PROFIT_LOCK_CONFIRM_SECS = 6

                                        confirm_key = f"{stop.symbol}:{stop.side}:{stop.stop_type}"
                                        st = self._profit_lock_confirm.get(confirm_key, {"count": 0, "first_ts": 0.0})
                                        now_ts = time.time()
                                        if st.get("first_ts", 0.0) <= 0:
                                            st["first_ts"] = now_ts
                                        st["count"] = int(st.get("count", 0) or 0) + 1
                                        self._profit_lock_confirm[confirm_key] = st

                                        elapsed = float(now_ts - float(st.get("first_ts", 0.0) or 0.0))
                                        ticks_ok = int(st.get("count", 0)) >= int(PROFIT_LOCK_CONFIRM_TICKS or 0)
                                        secs_ok = elapsed >= float(PROFIT_LOCK_CONFIRM_SECS or 0)
                                        if not (ticks_ok or secs_ok):
                                            logger.debug(
                                                f"[PROFIT_LOCK_CONFIRM] {stop.symbol} {stop.side}: "
                                                f"ticks={st.get('count', 0)} elapsed={elapsed:.1f}s "
                                                f"(need ticks>={PROFIT_LOCK_CONFIRM_TICKS} or secs>={PROFIT_LOCK_CONFIRM_SECS})"
                                            )
                                            continue
                                except Exception:
                                    pass
                                # ========================================================
                                # EMERGENCY EXIT DETECTION (ROI kill / survival overrides)
                                # ========================================================
                                is_emergency_exit = False
                                try:
                                    _ru = str(stop.reason or "").upper()
                                    if "ROI_KILL" in _ru or "PER_LEG_ROI_KILL" in _ru:
                                        is_emergency_exit = True
                                    else:
                                        is_emergency_exit = bool(
                                            getattr(stop, "override_profit_guard", False)
                                            or getattr(stop, "proactive_override", False)
                                            or getattr(stop, "override_safety_block", False)
                                        )
                                except Exception:
                                    is_emergency_exit = False
                                # ========================================================
                                # HEDGE PROTECTION: Block stop loss on hedged positions
                                # Hedged positions should only close at profit, not loss
                                # ========================================================
                                try:
                                    from config import (
                                        STEALTH_HEDGE_PROTECTION_ENABLED,
                                        STEALTH_HEDGE_PROFIT_ONLY
                                    )
                                    if STEALTH_HEDGE_PROTECTION_ENABLED:
                                        is_hedged = self._check_hedge_status(stop.symbol, stop.side)
                                        if is_hedged:
                                            # Hedged position: enforce PROFIT-ONLY exits using robust leg snapshot
                                            # (Redis first, Binance fallback to avoid false blocks on missing Redis entry).
                                            entry_price, unreal_pnl, profit_src = self._resolve_leg_entry_pnl(
                                                stop.symbol,
                                                stop.side,
                                                str(stop.account_id or self.account_id or "primary"),
                                            )

                                            # ── FIX: If position no longer exists (entry=0, pnl=None, src=none),
                                            # the stop is stale — skip it silently instead of blocking forever.
                                            if entry_price <= 0 and unreal_pnl is None and profit_src == "none":
                                                logger.debug(
                                                    f"🛡️ [HEDGE-PROTECTION] {stop.symbol} {stop.side}: "
                                                    f"Stop SKIPPED - position no longer exists (src=none, entry=0)"
                                                )
                                                continue

                                            profitable_exit = True
                                            if unreal_pnl is not None:
                                                # Best-effort: if the leg is green, allow profit-only exit.
                                                # This avoids false blocks when entry_price is missing in Redis.
                                                profitable_exit = float(unreal_pnl) > 0.0
                                            elif entry_price > 0:
                                                if stop.side.upper() == "LONG":
                                                    profitable_exit = current_price >= entry_price
                                                else:  # SHORT
                                                    profitable_exit = current_price <= entry_price
                                            else:
                                                # If we can't resolve entry, be conservative under PROFIT_ONLY.
                                                profitable_exit = False

                                            if STEALTH_HEDGE_PROFIT_ONLY and not profitable_exit:
                                                if is_emergency_exit:
                                                    logger.warning(
                                                        f"🛡️ [HEDGE-PROTECTION-EMERGENCY-BYPASS] {stop.symbol} {stop.side}: "
                                                        f"Emergency exit allowed despite unprofitable hedge leg "
                                                        f"(entry={entry_price:.4f}, px={current_price:.4f}, pnl={unreal_pnl}, src={profit_src}, "
                                                        f"type={stop.stop_type}, reason={stop.reason})"
                                                    )
                                                else:
                                                    # TAKE_PROFIT stops are inherently profit-seeking:
                                                    # they only trigger when price crosses the TP target.
                                                    # Blocking them on entry=0/pnl=None is a false negative.
                                                    _is_tp_type = str(getattr(stop, 'stop_type', '') or '').upper() in ('TAKE_PROFIT', 'TP', 'TRAILING_TP')
                                                    if _is_tp_type:
                                                        logger.info(
                                                            f"🛡️ [HEDGE-PROTECTION-TP-BYPASS] {stop.symbol} {stop.side}: "
                                                            f"TAKE_PROFIT exit ALLOWED despite unresolved entry "
                                                            f"(entry={entry_price:.4f}, px={current_price:.4f}, pnl={unreal_pnl}, src={profit_src})"
                                                        )
                                                        stop.hedge_maker_only = True
                                                        # fall through to execution
                                                    else:
                                                        # ── NET-PAIR-PROFIT BYPASS (Apr 2026) ──
                                                        # If the net pair PnL is positive (winning leg covers losing leg),
                                                        # allow closing the losing leg. This is safe because the net
                                                        # outcome is still profit.
                                                        _net_pair_bypass = False
                                                        try:
                                                            from config import (
                                                                HEDGE_PROTECTION_NET_PAIR_BYPASS_ENABLED,
                                                                HEDGE_PROTECTION_NET_PAIR_MIN_USD,
                                                            )
                                                            if HEDGE_PROTECTION_NET_PAIR_BYPASS_ENABLED:
                                                                import json as _hp_json
                                                                _hp_opp_side = "SHORT" if stop.side.upper() == "LONG" else "LONG"
                                                                _hp_opp_pnl = None
                                                                # Try Redis positions for opposite leg PnL
                                                                try:
                                                                    _hp_redis = getattr(self, 'redis', None) or getattr(self, '_redis', None)
                                                                    if _hp_redis:
                                                                        _hp_acct = str(getattr(stop, 'account_id', None) or getattr(self, 'account_id', 'primary') or 'primary')
                                                                        _hp_pos_raw = _hp_redis.hgetall(f"positions:live:{stop.symbol}")
                                                                        if _hp_pos_raw:
                                                                            for _hp_sk in ("long", "short"):
                                                                                _hp_raw = _hp_pos_raw.get(_hp_sk) or _hp_pos_raw.get(_hp_sk.encode())
                                                                                if _hp_raw:
                                                                                    _hp_pd = _hp_json.loads(_hp_raw)
                                                                                    if isinstance(_hp_pd, dict) and _hp_pd.get("has_position"):
                                                                                        _hp_pside = (_hp_pd.get("side", "") or "").upper()
                                                                                        if _hp_pside == _hp_opp_side:
                                                                                            _hp_opp_pnl = float(_hp_pd.get("unrealized_pnl", 0) or 0)
                                                                except Exception:
                                                                    pass
                                                                if _hp_opp_pnl is not None and unreal_pnl is not None:
                                                                    _hp_net = float(unreal_pnl) + _hp_opp_pnl
                                                                    if _hp_net >= float(HEDGE_PROTECTION_NET_PAIR_MIN_USD):
                                                                        _net_pair_bypass = True
                                                                        logger.warning(
                                                                            f"🎯 [HEDGE-PROTECTION-NET-PAIR-BYPASS] {stop.symbol} {stop.side}: "
                                                                            f"Exit ALLOWED — net pair PnL=${_hp_net:.2f} >= ${float(HEDGE_PROTECTION_NET_PAIR_MIN_USD):.0f} "
                                                                            f"(this_pnl=${float(unreal_pnl):.2f}, opp_pnl=${_hp_opp_pnl:.2f}, "
                                                                            f"type={stop.stop_type}, reason={stop.reason})"
                                                                        )
                                                                        stop.hedge_maker_only = True
                                                        except ImportError:
                                                            pass
                                                        except Exception as _npb_err:
                                                            logger.debug(f"HEDGE_NET_PAIR_BYPASS_ERR: {_npb_err}")

                                                        # ── INTELLIGENCE-DRIVEN BYPASS (Apr 2026) ──
                                                        # If MarketIntelligence says trend/momentum/liq are
                                                        # strongly against this leg, allow closing it even
                                                        # if net pair isn't positive yet.
                                                        _intel_bypass = False
                                                        if not _net_pair_bypass:
                                                            try:
                                                                from trading.market_intelligence import should_bypass_hedge_protection
                                                                _hp_redis = getattr(self, 'redis', None) or getattr(self, '_redis', None)
                                                                if _hp_redis:
                                                                    _ib_should, _ib_reason = should_bypass_hedge_protection(
                                                                        _hp_redis, stop.symbol, stop.side,
                                                                        float(unreal_pnl or 0),
                                                                    )
                                                                    if _ib_should:
                                                                        _intel_bypass = True
                                                                        logger.warning(
                                                                            "🧠 [HEDGE-PROTECTION-INTEL-BYPASS] %s %s: "
                                                                            "Exit ALLOWED by market intelligence — %s "
                                                                            "(pnl=$%.2f, type=%s)",
                                                                            stop.symbol, stop.side, _ib_reason,
                                                                            float(unreal_pnl or 0), stop.stop_type,
                                                                        )
                                                                        stop.hedge_maker_only = True
                                                            except ImportError:
                                                                pass
                                                            except Exception as _ib_err:
                                                                logger.debug("HEDGE_INTEL_BYPASS_ERR: %s", _ib_err)

                                                        if not _net_pair_bypass and not _intel_bypass:
                                                            logger.warning(
                                                                f"🛡️ [HEDGE-PROTECTION] {stop.symbol} {stop.side}: "
                                                                f"Exit BLOCKED - hedged position and exit is not profitable "
                                                                f"(entry={entry_price:.4f}, px={current_price:.4f}, pnl={unreal_pnl}, src={profit_src}, "
                                                                f"type={stop.stop_type}, reason={stop.reason})"
                                                            )
                                                            continue

                                            # Allowed exit on hedged position → normally force maker-only execution.
                                            if is_emergency_exit:
                                                logger.warning(
                                                    f"🛡️ [HEDGE-PROFIT-EXIT-EMERGENCY] {stop.symbol} {stop.side}: "
                                                    f"{stop.stop_type} allowed on hedged position (taker allowed) | "
                                                    f"entry={entry_price:.4f} px={current_price:.4f} pnl={unreal_pnl} src={profit_src}"
                                                )
                                                stop.hedge_maker_only = False
                                            else:
                                                logger.info(
                                                    f"🛡️ [HEDGE-PROFIT-EXIT] {stop.symbol} {stop.side}: "
                                                    f"{stop.stop_type} allowed on hedged position (maker-only) | "
                                                    f"entry={entry_price:.4f} px={current_price:.4f} pnl={unreal_pnl} src={profit_src}"
                                                )
                                                stop.hedge_maker_only = True
                                except ImportError:
                                    pass  # Config not available, allow all
                                
                                # ========================================================
                                # RIDE-THE-MOVE: Suppress static TP if trainer signals momentum
                                # Trainer sets wma:ride_move:{SYMBOL} when position should ride out
                                # ========================================================
                                try:
                                    is_static_tp = stop.stop_type == 'TAKE_PROFIT' and 'TRAIL' not in stop.reason.upper()
                                    if is_static_tp:
                                        suppress_tp, ride_reason = self._check_ride_move_flag(stop.symbol, stop.side)
                                        if suppress_tp:
                                            logger.info(
                                                f"🚀 [RIDE-THE-MOVE] {stop.symbol} {stop.side}: "
                                                f"Static TP SUPPRESSED - {ride_reason}. "
                                                f"Letting winner run via trailing stop."
                                            )
                                            continue  # Skip static TP, let trailing handle it
                                except Exception as e:
                                    logger.debug(f"[RIDE-MOVE] Error in check: {e}")
                                
                                if stop.stop_type == 'STOP_LOSS':
                                    try:
                                        from config import STEALTH_SL_TRAINER_DEFERENCE_ENABLED
                                        _sl_defer_on = bool(STEALTH_SL_TRAINER_DEFERENCE_ENABLED)
                                    except Exception:
                                        _sl_defer_on = True
                                    # Emergency exits must not be deferred by trainer intent.
                                    if is_emergency_exit:
                                        _sl_defer_on = False
                                    if _sl_defer_on:
                                        try:
                                            from risk.trainer_intent import get_intent
                                            _sl_ti = get_intent(self.redis, stop.symbol)
                                            if (_sl_ti is not None
                                                and not _sl_ti.is_stale
                                                and _sl_ti.is_directional
                                                and _sl_ti.confidence >= 0.80
                                                and _sl_ti.aligns_with_position(stop.side)):
                                                logger.info(
                                                    "[TRAINER_INTENT_SL_DEFER] sym=%s side=%s: SL SUPPRESSED — "
                                                    "trainer intent %s conf=%.3f. Let trainer manage exit.",
                                                    stop.symbol, stop.side, _sl_ti.direction, _sl_ti.confidence,
                                                )
                                                continue
                                        except Exception as _sl_ti_err:
                                            logger.debug("[TRAINER_INTENT_SL_DEFER] check error: %s", _sl_ti_err)

                                    # ── INTELLIGENT CLOSE GUARD (light touch for SL) ──
                                    # If regime/features/orderbook strongly support the position,
                                    # require extra ticks of SL persistence before executing.
                                    # Bypass ICG when fast adverse move detected (don't defer SL during adverse fast moves)
                                    try:
                                        _icg_hard_emerg = bool(is_emergency_exit)
                                        try:
                                            if self.redis:
                                                _fm_snap = self.redis.hgetall(f"msnap:coinapi_wsds:{stop.symbol}") or {}
                                                if _fm_snap and isinstance(next(iter(_fm_snap.keys()), ""), (bytes, bytearray)):
                                                    _fm_snap = {k.decode(): v.decode() for k, v in _fm_snap.items()}
                                                _fm_sc = float(_fm_snap.get("fast_move_score", 0) or 0)
                                                _fm_imb = float(_fm_snap.get("imbalance_5", 0) or 0)
                                                if _fm_sc >= 0.5:
                                                    _fm_is_adverse = (stop.side == "LONG" and _fm_imb < -0.12) or (stop.side == "SHORT" and _fm_imb > 0.12)
                                                    if _fm_is_adverse:
                                                        _icg_hard_emerg = True
                                        except Exception:
                                            pass
                                        from risk.intelligent_close_guard import evaluate_close as _sl_icg_eval
                                        _sl_icg = _sl_icg_eval(
                                            self.redis, stop.symbol, stop.side,
                                            close_reason=f"STEALTH_SL trigger={stop.trigger_price:.4f}",
                                            is_hard_emergency=_icg_hard_emerg,
                                        )
                                        if _sl_icg.should_defer:
                                            _sl_icg_key = f"icg_sl:{stop.symbol}:{stop.side}"
                                            if not hasattr(self, '_icg_sl_ticks'):
                                                self._icg_sl_ticks = {}
                                            _sl_icg_count = self._icg_sl_ticks.get(_sl_icg_key, 0) + 1
                                            self._icg_sl_ticks[_sl_icg_key] = _sl_icg_count
                                            _sl_icg_extra = 2
                                            if _sl_icg_count <= _sl_icg_extra:
                                                logger.info(
                                                    "ICG_STEALTH_SL_DEFER | sym=%s side=%s | "
                                                    "hold_score=%.3f | sl_ticks=%d/%d | sources=%d",
                                                    stop.symbol, stop.side,
                                                    _sl_icg.hold_score,
                                                    _sl_icg_count, _sl_icg_extra,
                                                    _sl_icg.data_sources_used,
                                                )
                                                continue
                                            else:
                                                logger.info(
                                                    "ICG_STEALTH_SL_OVERRIDE | sym=%s side=%s | "
                                                    "hold_score=%.3f | sl_ticks=%d > %d | FIRING",
                                                    stop.symbol, stop.side,
                                                    _sl_icg.hold_score,
                                                    _sl_icg_count, _sl_icg_extra,
                                                )
                                                self._icg_sl_ticks.pop(_sl_icg_key, None)
                                        else:
                                            if hasattr(self, '_icg_sl_ticks'):
                                                _sl_icg_key = f"icg_sl:{stop.symbol}:{stop.side}"
                                                self._icg_sl_ticks.pop(_sl_icg_key, None)
                                    except Exception as _sl_icg_err:
                                        logger.debug("ICG_STEALTH_SL_ERR | %s | %s", stop.symbol, _sl_icg_err)


                                triggered_stops.append(stop)
                                # region agent log
                                try:
                                    if str(getattr(stop, "stop_type", "") or "").upper() == "STOP_LOSS":
                                        import json as _aj
                                        _ts = int(time.time() * 1000)
                                        _symu = str(getattr(stop, "symbol", "") or "").upper().strip()
                                        _sideu = str(getattr(stop, "side", "") or "").upper().strip()
                                        _k = f"{_symu}:{_sideu}:STOP_LOSS"
                                        _m = globals().get("_AGENT_SL_TRIGGER_LAST", {}) or {}
                                        try:
                                            _lt = int(_m.get(_k, 0) or 0)
                                        except Exception:
                                            _lt = 0
                                        if (_ts - _lt) >= 10_000:
                                            _m[_k] = _ts
                                            globals()["_AGENT_SL_TRIGGER_LAST"] = _m
                                            try:
                                                _dev = 0.0
                                                if float(getattr(stop, "trigger_price", 0) or 0) > 0:
                                                    _dev = abs(float(current_price) - float(stop.trigger_price)) / float(stop.trigger_price) * 100.0
                                            except Exception:
                                                _dev = None
                                            try:
                                                from config import ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED, ORCHESTRATOR_MODE
                                                _orch_enabled = bool(ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED) and str(ORCHESTRATOR_MODE or "").strip().lower() == "publish"
                                            except Exception:
                                                _orch_enabled = None
                                            _payload = {
                                                "sessionId": "53deb7",
                                                "id": f"log_{_ts}_stealth_sl_triggered_{_k}",
                                                "timestamp": _ts,
                                                "location": "trading/stealth_stops.py:_monitor_loop",
                                                "message": "stealth_sl_triggered",
                                                "runId": "post-fix",
                                                "hypothesisId": "H11",
                                                "data": {
                                                    "account_id": str(getattr(stop, "account_id", "") or ""),
                                                    "symbol": _symu,
                                                    "side": _sideu,
                                                    "stop_type": "STOP_LOSS",
                                                    "current_price": float(current_price or 0.0),
                                                    "trigger_price": float(getattr(stop, "trigger_price", 0) or 0.0),
                                                    "deviation_pct": _dev,
                                                    "position_size": float(getattr(stop, "position_size", 0) or 0.0),
                                                    "close_percentage": float(getattr(stop, "close_percentage", 100.0) or 100.0),
                                                    "reason": str(getattr(stop, "reason", "") or "")[:160],
                                                    "orch_enabled": _orch_enabled,
                                                },
                                            }
                                            with open(
                                                "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                                                "a",
                                                encoding="utf-8",
                                            ) as _f:
                                                _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                                except Exception:
                                    pass
                                # endregion
                                logger.warning(f"🎯 [STEALTH-TRIGGER] {stop.symbol} {stop.side} {stop.stop_type} "
                                             f"hit @ {current_price} (trigger: {stop.trigger_price})")
                            else:
                                # Reset confirmation when price moves back above/below trigger
                                try:
                                    if "PROFIT_LOCK" in str(stop.reason or "").upper():
                                        confirm_key = f"{stop.symbol}:{stop.side}:{stop.stop_type}"
                                        if confirm_key in self._profit_lock_confirm:
                                            del self._profit_lock_confirm[confirm_key]
                                except Exception:
                                    pass
                                # Reset ICG SL tick counter when price recovers
                                try:
                                    if hasattr(self, '_icg_sl_ticks') and stop.stop_type == 'STOP_LOSS':
                                        _icg_reset_key = f"icg_sl:{stop.symbol}:{stop.side}"
                                        self._icg_sl_ticks.pop(_icg_reset_key, None)
                                except Exception:
                                    pass
                                try:
                                    _hfr = f"hedge_flat:{stop.symbol}:{stop.side}:{stop.stop_type}"
                                    if hasattr(self, "_hedge_flat_confirm"):
                                        self._hedge_flat_confirm.pop(_hfr, None)
                                except Exception:
                                    pass
                        
                        # Execute triggered stops (or publish proposals to the orchestrator)
                        for stop in triggered_stops:
                            # ====================================================
                            # PARTIAL TP: On first TP hit, close only a fraction
                            # and arm a wider trailing stop on the remainder.
                            # Prevents full exit before trend completion.
                            # ====================================================
                            _tp_plan = self._compute_tp_execution_plan(
                                stop.symbol,
                                stop.side,
                                float(getattr(stop, "entry_price", 0.0) or 0.0),
                                float(current_price or 0.0),
                                float(getattr(stop, "position_size", 0.0) or 0.0),
                            )
                            _partial_pct = float(_tp_plan.get("partial_pct", 35.0) or 35.0)
                            _partial_trail = bool(int(_tp_plan.get("partial_trail", 1.0) or 1.0))
                            _trail_mult = float(_tp_plan.get("trail_mult", 2.0) or 2.0)

                            _is_tp = str(stop.stop_type or "").upper() == "TAKE_PROFIT"
                            _is_full = float(stop.close_percentage or 100.0) >= 99.9
                            _partial_key = f"_tp_partial_done:{stop.symbol}:{stop.side}"
                            _already_partialed = getattr(self, '_tp_partial_tracker', {}).get(_partial_key, False)
                            _orig_size = float(stop.position_size or 0)

                            # Hedge-first TP protection:
                            # If this TP belongs to the winning leg of an active hedge while the
                            # opposite leg is still deeply underwater, convert the TP into a
                            # profit-lock stop instead of peeling the winner immediately.
                            if _is_tp and _is_full and not _already_partialed:
                                try:
                                    _hedge_lock = self._get_hedged_tp_protective_lock(stop, current_price)
                                except Exception as _hlt_err:
                                    _hedge_lock = None
                                    logger.debug("HEDGE_TP_PROTECT_ERR | %s | %s", stop.symbol, _hlt_err)
                                if _hedge_lock:
                                    try:
                                        self.remove_stop(stop.symbol, stop.side, "TAKE_PROFIT", stop.account_id)
                                    except Exception:
                                        pass

                                    _lock_reason = " ".join(
                                        tok for tok in [str(stop.reason or "").strip(), "PROFIT_LOCK", "HEDGE_RESCUE"] if tok
                                    )
                                    _lock_stop = StealthStop(
                                        symbol=str(stop.symbol),
                                        side=str(stop.side).upper(),
                                        stop_type="STOP_LOSS",
                                        trigger_price=float(_hedge_lock["lock_price"]),
                                        position_size=float(_orig_size or stop.position_size or 0.0),
                                        close_percentage=100.0,
                                        account_id=str(stop.account_id or self.account_id or "primary"),
                                        reason=_lock_reason,
                                        signal_id=getattr(stop, "signal_id", None),
                                        hedge_maker_only=True,
                                        entry_price=float(getattr(stop, "entry_price", 0.0) or _hedge_lock["leg_entry"] or 0.0),
                                    )
                                    self.add_stop(_lock_stop, source="hedge_tp_protect")
                                    logger.warning(
                                        "HEDGE_TP_PROTECTIVE_TRAIL | %s %s | tp_deferred lock=%.6f | "
                                        "winner_pnl=$%.2f loser=%s pnl=$%.2f net=$%.2f frac=%.2f | "
                                        "winner_src=%s loser_src=%s",
                                        stop.symbol,
                                        stop.side,
                                        float(_hedge_lock["lock_price"]),
                                        float(_hedge_lock["leg_unreal"]),
                                        str(_hedge_lock["opp_side"]),
                                        float(_hedge_lock["opp_unreal"]),
                                        float(_hedge_lock["net_pair"]),
                                        float(_hedge_lock["lock_frac"]),
                                        str(_hedge_lock["leg_src"]),
                                        str(_hedge_lock["opp_src"]),
                                    )
                                    continue

                            try:
                                if _is_tp and _is_full and 0 < _partial_pct < 99.9 and not _already_partialed:
                                    # First TP hit → partial close only
                                    stop.close_percentage = _partial_pct
                                    stop.position_size = float(stop.position_size)  # keep original for remainder calc
                                    _orig_size = float(stop.position_size)

                                    if not hasattr(self, '_tp_partial_tracker'):
                                        self._tp_partial_tracker = {}
                                    self._tp_partial_tracker[_partial_key] = True

                                    logger.info(
                                        "[TP_PARTIAL_FIRST_HIT] sym=%s side=%s: closing %.0f%% "
                                        "(was 100%%). Remainder will trail. risk=%.2f trend=%.2f features=%d",
                                        stop.symbol, stop.side, _partial_pct,
                                        float(_tp_plan.get("risk_score", 0.0) or 0.0),
                                        float(_tp_plan.get("trend_score", 0.0) or 0.0),
                                        int(_tp_plan.get("source_count", 0.0) or 0.0),
                                    )
                            except Exception:
                                _is_tp = False
                                _partial_trail = False

                            # ── ICG TP HOLD + RIDE-MOVE GATE ──────────────────
                            # Use evaluate_tp_hold() for TP-specific evaluation.
                            # If the trend strongly supports holding, widen TP by the
                            # suggested ATR-based extension and skip this trigger cycle.
                            _icg_tp_deferred = False
                            if _is_tp:
                                try:
                                    from risk.intelligent_close_guard import evaluate_tp_hold as _tp_hold_eval
                                    _entry_px = float(getattr(stop, "entry_price", 0) or 0)
                                    _current_roe = 0.0
                                    if _entry_px > 0 and current_price > 0:
                                        if stop.side.upper() == "LONG":
                                            _current_roe = ((current_price - _entry_px) / _entry_px) * 100.0
                                        else:
                                            _current_roe = ((_entry_px - current_price) / _entry_px) * 100.0

                                    _tp_hold = _tp_hold_eval(
                                        self.redis, stop.symbol, stop.side,
                                        current_roe=_current_roe,
                                    )
                                    if _tp_hold.should_hold:
                                        _old_tp = float(stop.trigger_price)
                                        _ext_pct = _tp_hold.suggested_tp_extension_pct
                                        if stop.side.upper() == "LONG":
                                            _new_tp = _old_tp * (1.0 + _ext_pct / 100.0)
                                        else:
                                            _new_tp = _old_tp * (1.0 - _ext_pct / 100.0)
                                        stop.trigger_price = _new_tp
                                        logger.info(
                                            "ICG_TP_HOLD_WIDEN | sym=%s side=%s | "
                                            "old_tp=%.6f new_tp=%.6f ext=%.2f%% | "
                                            "hold_score=%.3f roe=%.1f%% | %s",
                                            stop.symbol, stop.side, _old_tp, _new_tp,
                                            _ext_pct, _tp_hold.hold_score, _current_roe,
                                            _tp_hold.reason,
                                        )
                                        _icg_tp_deferred = True
                                except Exception as _tp_icg_err:
                                    logger.debug("ICG_STEALTH_TP_ERR | %s | %s", stop.symbol, _tp_icg_err)

                            if _icg_tp_deferred:
                                continue

                            # ================================================================
                            # Hedged book: require N consecutive trigger evaluations before
                            # executing or proposing a full flatten. Applies in BOTH orchestrator
                            # -publish and direct-execute modes (moved here from _execute_stop
                            # so it is not bypassed when orch_enabled=True).
                            # Emergency / ROI-kill reasons bypass the gate.
                            # ================================================================
                            _defer_this_stop = False
                            try:
                                from config import STEALTH_HEDGE_FLATTEN_CONFIRM_TICKS as _nfc_cfg_ml
                                _nfc_ml = int(_nfc_cfg_ml or 0)
                            except Exception:
                                _nfc_ml = 2
                            try:
                                _ru_ml = str(stop.reason or "").upper()
                                _bypass_flat_ml = "ROI_KILL" in _ru_ml or "PER_LEG_ROI_KILL" in _ru_ml
                            except Exception:
                                _bypass_flat_ml = False
                            if (
                                _nfc_ml >= 1
                                and not _bypass_flat_ml
                                and self._check_hedge_status(stop.symbol, stop.side)
                                and float(stop.close_percentage or 100.0) >= 99.0
                            ):
                                _hfk_ml = f"hedge_flat:{stop.symbol}:{stop.side}:{stop.stop_type}"
                                self._hedge_flat_confirm[_hfk_ml] = int(self._hedge_flat_confirm.get(_hfk_ml, 0)) + 1
                                if self._hedge_flat_confirm[_hfk_ml] < _nfc_ml:
                                    logger.info(
                                        "STEALTH_HEDGE_FLAT_DEFER | sym=%s side=%s type=%s tick=%d/%d",
                                        stop.symbol, stop.side, stop.stop_type,
                                        self._hedge_flat_confirm[_hfk_ml], _nfc_ml,
                                    )
                                    _defer_this_stop = True
                                else:
                                    self._hedge_flat_confirm.pop(_hfk_ml, None)
                            if _defer_this_stop:
                                continue

                            executed = False
                            try:
                                from config import ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED, ORCHESTRATOR_MODE
                                orch_enabled = bool(ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED) and str(ORCHESTRATOR_MODE or "").strip().lower() == "publish"
                            except Exception:
                                orch_enabled = False

                            if orch_enabled:
                                executed = bool(self._emit_orchestrator_proposal(stop, current_price))
                            else:
                                executed = bool(self._execute_stop(stop, current_price))

                            # Remove from pending after execution/proposal emission
                            if executed:
                                try:
                                    self.pending_stops[symbol].remove(stop)
                                except Exception:
                                    pass

                                # Arm trailing stop on remainder after partial TP
                                if (_is_tp and _partial_trail
                                        and 0 < _partial_pct < 99.9
                                        and hasattr(self, '_tp_partial_tracker')
                                        and self._tp_partial_tracker.get(_partial_key)):
                                    try:
                                        remainder_pct = 100.0 - _partial_pct
                                        remainder_qty = float(_orig_size) * (remainder_pct / 100.0)
                                        if remainder_qty > 0:
                                            from config import STEALTH_TRAIL_DISTANCE_PCT, STEALTH_TRAIL_CALLBACK_PCT
                                            trail_dist = float(STEALTH_TRAIL_DISTANCE_PCT) * _trail_mult
                                            trail_cb = float(STEALTH_TRAIL_CALLBACK_PCT) * _trail_mult
                                            trail_dist = self._atr_adaptive_trail_distance(
                                                stop.symbol, stop.side, trail_dist,
                                            )
                                            # Calculate trail trigger in the protective direction so the remainder
                                            # exits on pullback after profit has already been locked in.
                                            if stop.side.upper() == "LONG":
                                                trail_trigger = current_price * (1.0 - trail_dist / 100.0)
                                            else:
                                                trail_trigger = current_price * (1.0 + trail_dist / 100.0)
                                            self.add_take_profit(
                                                symbol=stop.symbol,
                                                side=stop.side,
                                                trigger_price=trail_trigger,
                                                position_size=remainder_qty,
                                                close_percentage=100.0,
                                                source="partial_tp_trail",
                                                account_id=stop.account_id,
                                                reason=f"TRAIL_REMAINDER after partial TP ({_partial_pct:.0f}%)",
                                                entry_price=float(getattr(stop, "entry_price", 0.0) or 0.0),
                                            )
                                            logger.info(
                                                "[TP_PARTIAL_TRAIL_ARMED] sym=%s side=%s remainder_qty=%.6f "
                                                "trail_trigger=%.4f trail_dist=%.2f%%",
                                                stop.symbol, stop.side, remainder_qty,
                                                trail_trigger, trail_dist,
                                            )
                                    except Exception as _trail_err:
                                        logger.warning("[TP_PARTIAL_TRAIL] Failed to arm remainder trail: %s", _trail_err)
                        
                        if triggered_stops:
                            # Clean up and persist
                            if not self.pending_stops[symbol]:
                                del self.pending_stops[symbol]
                            self._save_to_redis()
                
                # Check every 2 seconds (fast response time)
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"[STEALTH-STOPS] Monitor loop error: {e}", exc_info=True)
                time.sleep(5)

    def _emit_orchestrator_proposal(self, stop: StealthStop, current_price: float) -> bool:
        """
        Convert a triggered stealth stop into a TradeProposal so the orchestrator can arbitrate.

        No-loss default:
        - STOP_LOSS triggers propose a hedge action (never close at loss).
        - TAKE_PROFIT / TRAIL triggers propose profit exits (partial/close) which are no-loss compliant.
        """
        if not self.redis:
            return False
        try:
            # Emit to the same proposal stream that the orchestrator worker consumes.
            # Orchestrator reads env ORCHESTRATOR_PROPOSAL_STREAM (default: wma:proposals).
            import os as _os
            _env_stream = str(_os.getenv("ORCHESTRATOR_PROPOSAL_STREAM", "") or "").strip()
            if _env_stream:
                stream = _env_stream
            else:
                from config import ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM
                stream = str(ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM or "wma:proposals")
        except Exception:
            try:
                from config import ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM
                stream = str(ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM or "wma:proposals")
            except Exception:
                stream = "wma:proposals"

        try:
            from rl.trade_proposal import TradeProposal
            from rl.proposal_bus import emit_proposal
        except Exception:
            return False

        sym = str(stop.symbol or "").upper().strip()
        side = str(stop.side or "").upper().strip()
        stype = str(stop.stop_type or "").upper().strip()
        reason = str(stop.reason or "")

        # Data-driven urgency: closer to liquidation / high microstructure stress => higher urgency.
        # Here we use available real-time context only (current_price vs trigger deviation).
        urgency = 0.0
        try:
            if stop.trigger_price > 0:
                dist_pct = abs(float(current_price) - float(stop.trigger_price)) / float(stop.trigger_price) * 100.0
                # smaller distance => higher urgency (normalize with a smooth curve, no hard threshold)
                urgency = max(0.0, min(1.0, 1.0 / (1.0 + dist_pct)))
        except Exception:
            urgency = 0.5

        close_fraction = max(0.0, min(1.0, float(stop.close_percentage or 100.0) / 100.0))

        # P0 Guardrail: If this is a profit-exit on a SHORT hedge leg, block/cap the proposal
        # when the opposite LONG leg is still liquidation-risk or system is in stress.
        try:
            if str(stype).upper() != "STOP_LOSS" and str(side).upper() == "SHORT":
                req_qty = float(stop.position_size or 0.0) * float(close_fraction or 0.0)
                allow, adj_qty, reason, meta = self._hedge_tp_guard(sym, req_qty, float(current_price or 0.0))
                if not allow or float(adj_qty or 0.0) <= 0.0:
                    logger.warning(
                        "HEDGE_TP_GUARD_PROPOSAL | sym=%s side=SHORT reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=0.0",
                        sym,
                        reason,
                        f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                        float(meta.get('long_qty') or 0.0),
                        float(meta.get('short_qty') or 0.0),
                        float(meta.get('requested_qty') or 0.0),
                    )
                    return False
                if float(stop.position_size or 0.0) > 0:
                    close_fraction = max(0.0, min(1.0, float(adj_qty) / float(stop.position_size or 1.0)))
        except Exception:
            pass

        if stype == "STOP_LOSS":
            # No stop-loss closure: convert to hedge intent.
            action = "ADD_HEDGE_SHORT" if side == "LONG" else "ADD_HEDGE_LONG"
            cat = "HEDGE"
            no_loss_ok = True
        else:
            # TAKE_PROFIT or trailing: propose close/partial close
            if close_fraction >= 0.999:
                action = "CLOSE_LONG" if side == "LONG" else "CLOSE_SHORT"
            else:
                # Use canonical trader-supported action name + pass side via market_context
                action = "PARTIAL_CLOSE"
            cat = "STEALTH_TP"
            no_loss_ok = True

        p = TradeProposal.new(
            source="stealth_stop",
            account_id=str(stop.account_id or self.account_id or "primary"),
            symbol=sym,
            action_name=str(action),
            action_category=str(cat),
            close_fraction=float(close_fraction if "PARTIAL" in action else 0.0),
            confidence=1.0,  # deterministic trigger
            urgency_score=float(urgency),
            no_loss_compliant=bool(no_loss_ok),
            trigger_reason=f"STEALTH_TRIGGER {stype} {sym} {side} px={current_price:.6f} trig={float(stop.trigger_price or 0.0):.6f} reason={reason}",
            market_context={
                "stop_type": stype,
                "trigger_price": float(stop.trigger_price or 0.0),
                "current_price": float(current_price or 0.0),
                "side": side,
                "close_fraction": float(close_fraction),
                "reason": reason,
            },
        ).to_dict()

        try:
            from risk.trainer_alignment import enrich_proposal_with_trainer, get_trainer_view
            enrich_proposal_with_trainer(self.redis, p)
            tv = get_trainer_view(self.redis, sym)
            if tv and tv.is_directional and tv.best_target_price > 0:
                p["trainer_target_price"] = tv.best_target_price
                p["trainer_direction"] = tv.consensus_direction
                p["trainer_regime"] = tv.move_regime
        except Exception:
            pass

        _ok = bool(emit_proposal(self.redis, stream=str(stream), proposal=p))
        # region agent log
        try:
            _symu2 = str(sym or "").upper().strip()
            if _symu2 in ("BANKUSDT", "ASTERUSDT") and str(stype).upper() == "STOP_LOSS":
                import json as _aj3
                _ts3 = int(time.time() * 1000)
                _payload3 = {
                    "sessionId": "868108",
                    "id": f"log_{_ts3}_stealth_stoploss_emit_{_symu2}_{side}",
                    "timestamp": _ts3,
                    "location": "trading/stealth_stops.py:_emit_orchestrator_proposal",
                    "message": "stealth_stoploss_emitted",
                    "runId": "pre-fix",
                    "hypothesisId": "H2",
                    "data": {
                        "account_id": str(stop.account_id or self.account_id or "primary"),
                        "symbol": _symu2,
                        "side": str(side),
                        "action": str(action),
                        "category": str(cat),
                        "stream": str(stream),
                        "emit_ok": bool(_ok),
                        "current_price": float(current_price or 0.0),
                        "trigger_price": float(stop.trigger_price or 0.0),
                        "close_fraction": float(close_fraction),
                        "reason": str(reason or "")[:160],
                    },
                }
                with open(
                    "/home/wali/Desktop/AI BOT/.cursor/debug-868108.log",
                    "a",
                    encoding="utf-8",
                ) as _f3:
                    _f3.write(_aj3.dumps(_payload3, separators=(",", ":")) + "\n")
        except Exception:
            pass
        # endregion
        # region agent log
        try:
            if str(stype).upper() == "STOP_LOSS":
                import json as _aj
                _ts = int(time.time() * 1000)
                _k = f"{sym}:{side}:STOP_LOSS"
                _m = globals().get("_AGENT_SL_EMIT_LAST", {}) or {}
                try:
                    _lt = int(_m.get(_k, 0) or 0)
                except Exception:
                    _lt = 0
                if (_ts - _lt) >= 10_000:
                    _m[_k] = _ts
                    globals()["_AGENT_SL_EMIT_LAST"] = _m
                    _payload = {
                        "sessionId": "53deb7",
                        "id": f"log_{_ts}_stealth_sl_emit_{_k}",
                        "timestamp": _ts,
                        "location": "trading/stealth_stops.py:_emit_orchestrator_proposal",
                        "message": "stealth_sl_emit_proposal",
                        "runId": "post-fix",
                        "hypothesisId": "H11",
                        "data": {
                            "account_id": str(stop.account_id or self.account_id or "primary"),
                            "symbol": str(sym),
                            "side": str(side),
                            "stop_type": "STOP_LOSS",
                            "action": str(action),
                            "category": str(cat),
                            "proposal_stream": str(stream),
                            "emit_ok": bool(_ok),
                            "current_price": float(current_price or 0.0),
                            "trigger_price": float(stop.trigger_price or 0.0),
                            "close_fraction": float(close_fraction),
                        },
                    }
                    with open(
                        "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                        "a",
                        encoding="utf-8",
                    ) as _f:
                        _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
        except Exception:
            pass
        # endregion
        return _ok
    
    def _fetch_mark_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch current mark prices using WATERFALL approach:
        
        PRIORITY ORDER (WebSocket sources first, REST last):
        1. Binance mark price (Redis `latest:binance:mark_price:{SYMBOL}`) - PRIMARY for Binance Futures
        2. Binance WebSocket (trader WebSocket helper if available)
        3. CoinAPI WebSocket (msnap:coinapi_wsds:{SYMBOL}) - fallback (may diverge vs futures mark)
        4. Redis price key (price:{SYMBOL}) - cached fallback (can be non-Binance spot)
        5. Binance REST API - LAST RESORT (rate limited)
        
        CRITICAL: Always validates prices are reasonable before returning to prevent
        false stop triggers from stale/corrupt data.
        """
        result = {}
        symbols_remaining = list(symbols)
        current_time_ms = int(time.time() * 1000)
        max_staleness_ms = 30000  # 30 seconds max staleness for WS sources (increased from 10s)
        
        # ========== SOURCE 1: Binance mark price key in Redis (PRIMARY) ==========
        # Written by `ingest/live_binance.py` as JSON:
        # {"ts_ms": ..., "mark_price": ..., ...}
        if self.redis and symbols_remaining:
            try:
                for symbol in list(symbols_remaining):
                    mp_key = f"latest:binance:mark_price:{symbol}"
                    mp_json = self.redis.get(mp_key)
                    if not mp_json:
                        continue

                    mp_data = json.loads(mp_json)
                    mark_price = float(mp_data.get("mark_price") or 0.0)
                    updated_ts = int(mp_data.get("ts_ms") or 0)
                    staleness = current_time_ms - updated_ts

                    if mark_price > 0 and updated_ts > 0 and staleness < max_staleness_ms:
                        result[symbol] = mark_price
                        symbols_remaining.remove(symbol)
                        logger.debug(f"[PRICE] {symbol}: Binance Redis mark_price={mark_price:.4f} age={staleness}ms")
            except Exception as e:
                logger.debug(f"[PRICE] Binance mark price key error: {e}")

        # ========== SOURCE 2: Trader WebSocket Helper (if available) ==========
        if symbols_remaining and hasattr(self, '_ws_helper') and self._ws_helper:
            try:
                for symbol in list(symbols_remaining):
                    price = self._ws_helper.get_mark_price(symbol)
                    if price and price > 0:
                        result[symbol] = price
                        symbols_remaining.remove(symbol)
                        logger.debug(f"[PRICE] {symbol}: Trader WS mark_price={price:.4f}")
            except Exception as e:
                logger.debug(f"[PRICE] Trader WS error: {e}")

        # ========== SOURCE 3: CoinAPI WebSocket (fallback) ==========
        if self.redis and symbols_remaining:
            try:
                for symbol in list(symbols_remaining):
                    msnap_key = f"msnap:coinapi_wsds:{symbol}"
                    msnap_data = self.redis.hgetall(msnap_key)
                    if msnap_data:
                        # Decode bytes if needed
                        if isinstance(list(msnap_data.keys())[0], bytes):
                            msnap_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in msnap_data.items()}
                        
                        mid_px = float(msnap_data.get('mid_px', 0) or 0)
                        updated_ts = int(msnap_data.get('updated_ts_ms', 0) or 0)
                        staleness = current_time_ms - updated_ts
                        
                        if mid_px > 0 and staleness < max_staleness_ms:
                            result[symbol] = mid_px
                            symbols_remaining.remove(symbol)
                            logger.debug(f"[PRICE] {symbol}: CoinAPI WS mid_px={mid_px:.4f} age={staleness}ms")
            except Exception as e:
                logger.debug(f"[PRICE] CoinAPI read error: {e}")
        
        # ========== SOURCE 4: CCXT/KuCoin price key ==========
        if self.redis and symbols_remaining:
            try:
                for symbol in list(symbols_remaining):
                    # Try CCXT price key
                    price_key = f"price:{symbol}"
                    price_str = self.redis.get(price_key)
                    if price_str:
                        price = float(price_str)
                        if price > 0:
                            result[symbol] = price
                            symbols_remaining.remove(symbol)
                            logger.debug(f"[PRICE] {symbol}: Redis price key={price:.4f}")
            except Exception as e:
                logger.debug(f"[PRICE] Redis price key error: {e}")
        
        # ========== SOURCE 5: Binance REST API (LAST RESORT) ==========
        if symbols_remaining and self.binance:
            try:
                # Rate limit: only call API once per 5 seconds (conservative for Binance)
                # With multiple traders, we need more headroom
                now = time.time()
                last_api_call = getattr(self, '_last_mark_price_api_call', 0)
                
                if now - last_api_call < 5:
                    # Use cached prices if rate limited
                    cached_prices = getattr(self, '_cached_mark_prices', {})
                    for sym in list(symbols_remaining):
                        if sym in cached_prices:
                            cached_data = cached_prices[sym]
                            if now - cached_data.get('ts', 0) < 30:  # Cache valid for 30s
                                result[sym] = cached_data['price']
                                symbols_remaining.remove(sym)
                                logger.debug(f"[PRICE] {sym}: REST cache={cached_data['price']:.4f}")
                else:
                    self._last_mark_price_api_call = now
                    mark_prices = self.binance.futures_mark_price()
                    
                    # Cache ALL prices
                    if not hasattr(self, '_cached_mark_prices'):
                        self._cached_mark_prices = {}
                    
                    for item in mark_prices:
                        sym = item['symbol']
                        price = float(item['markPrice'])
                        self._cached_mark_prices[sym] = {'price': price, 'ts': now}
                        if sym in symbols_remaining:
                            result[sym] = price
                            symbols_remaining.remove(sym)
                            logger.debug(f"[PRICE] {sym}: REST API={price:.4f}")
                            
            except Exception as e:
                logger.warning(f"[PRICE] REST API error: {e}")
        
        # Log any symbols we couldn't get prices for
        if symbols_remaining:
            logger.warning(f"[PRICE] No price available for: {symbols_remaining}")
        
        # NOTE: Previously validated price vs trigger here but that's wrong for orphan stops.
        # Orphan cleanup is now done in trader._cleanup_orphan_stealth_stops()
        # The _execute_stop() has its own API-verified price check before execution.
        
        return result
    
    def _execute_hybrid_limit_order(
        self,
        symbol: str,
        order_side: str,
        position_side: str,
        quantity: float,
        current_price: float,
        stop: StealthStop,
        force_maker_only: bool = False
    ) -> Tuple[Optional[Dict], bool, str]:
        """
        Execute order using hybrid limit → market fallback strategy.
        
        Strategy:
        1. Place POST_ONLY limit order at favorable price (0.03-0.08% offset)
        2. Wait random time (10-60 seconds) for fill
        3. If filled → Done (saved maker fee!)
        4. If not filled → Cancel and execute market order (unless force_maker_only)
        
        Anti-Chase Safeguards:
        - Random wait time prevents pattern detection
        - Random price offset varies placement
        - Order only visible for short window
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            order_side: BUY or SELL
            position_side: LONG or SHORT (for hedge mode)
            quantity: Order quantity
            current_price: Current market price
            stop: StealthStop object for context
            force_maker_only: If True, do NOT fall back to market (hedged position protection)
            
        Returns:
            (order_dict, used_limit, execution_method) - order result, whether limit was used, method string
        """
        try:
            # Load config for hybrid execution
            from config import (
                STEALTH_HYBRID_LIMIT_ENABLED,
                STEALTH_LIMIT_WAIT_MIN_SEC,
                STEALTH_LIMIT_WAIT_MAX_SEC,
                STEALTH_LIMIT_PRICE_OFFSET_MIN_PCT,
                STEALTH_LIMIT_PRICE_OFFSET_MAX_PCT,
                MAKER_FEE_PCT,
                TAKER_FEE_PCT
            )
        except ImportError:
            # Defaults if config not available
            STEALTH_HYBRID_LIMIT_ENABLED = True
            STEALTH_LIMIT_WAIT_MIN_SEC = 10
            STEALTH_LIMIT_WAIT_MAX_SEC = 60
            STEALTH_LIMIT_PRICE_OFFSET_MIN_PCT = 0.03
            STEALTH_LIMIT_PRICE_OFFSET_MAX_PCT = 0.08
            MAKER_FEE_PCT = 0.02
            TAKER_FEE_PCT = 0.05
        
        # If hybrid disabled and NOT force_maker_only, go straight to market
        if not STEALTH_HYBRID_LIMIT_ENABLED and not force_maker_only:
            return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_DIRECT"
        
        # Calculate limit price with random offset (favorable side for maker)
        offset_pct = random.uniform(STEALTH_LIMIT_PRICE_OFFSET_MIN_PCT, STEALTH_LIMIT_PRICE_OFFSET_MAX_PCT) / 100
        
        if order_side == 'SELL':
            # Selling: place limit slightly ABOVE market (favorable for us)
            limit_price = current_price * (1 + offset_pct)
        else:  # BUY
            # Buying: place limit slightly BELOW market (favorable for us)
            limit_price = current_price * (1 - offset_pct)
        
        # Quantize via exchange info (precision-safe)
        try:
            tick_size, _, price_precision, _ = self._extract_filters(symbol)
            limit_price = self._quantize_price(limit_price, tick_size, order_side, price_precision)
        except Exception:
            pass
        
        # Random wait time for anti-detection
        wait_seconds = random.randint(STEALTH_LIMIT_WAIT_MIN_SEC, STEALTH_LIMIT_WAIT_MAX_SEC)
        
        logger.info(
            f"🎯 [HYBRID-LIMIT] {symbol} {order_side}: Placing POST_ONLY limit @ {limit_price:.4f} "
            f"(market: {current_price:.4f}, offset: {offset_pct*100:.3f}%, wait: {wait_seconds}s)"
        )
        
        limit_order = None
        try:
            # Place POST_ONLY (GTX) limit order - will be rejected if it would take liquidity
            limit_order = self._place_limit_order(
                symbol,
                order_side,
                position_side,
                limit_price,
                quantity,
                'GTX',
                reduce_only=True,
            )
            if not limit_order:
                raise RuntimeError("limit_order_not_placed")
            
            order_id = limit_order.get('orderId')
            logger.info(f"📋 [HYBRID-LIMIT] {symbol}: Limit order placed (ID: {order_id}), waiting {wait_seconds}s for fill...")
            
        except Exception as limit_err:
            err_str = str(limit_err)
            
            # GTX rejection (-5022) means order would cross (take liquidity)
            if '-5022' in err_str or 'would immediately match' in err_str.lower():
                if force_maker_only:
                    # Hedged position - do NOT fall back to market, re-queue the stop
                    logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: GTX rejected - NOT using market (hedged position). Will retry later.")
                    return None, False, "MAKER_ONLY_RETRY"
                logger.info(f"🔄 [HYBRID-LIMIT] {symbol}: GTX rejected (would cross) - using market order")
                return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_GTX_REJECT"
            
            # -1106 or reduceOnly error - retry without reduceOnly
            if '-1106' in err_str or 'reduceOnly' in err_str.lower():
                try:
                    limit_order = self._place_limit_order(
                        symbol,
                        order_side,
                        position_side,
                        limit_price,
                        quantity,
                        'GTX',
                        reduce_only=False,
                    )
                    if not limit_order:
                        raise RuntimeError("limit_order_not_placed")
                    order_id = limit_order.get('orderId')
                    logger.info(f"📋 [HYBRID-LIMIT] {symbol}: Limit order placed without reduceOnly (ID: {order_id})")
                except Exception as retry_err:
                    if force_maker_only:
                        logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: Limit retry failed - NOT using market (hedged). Will retry later.")
                        return None, False, "MAKER_ONLY_RETRY"
                    logger.warning(f"⚠️ [HYBRID-LIMIT] {symbol}: Limit retry failed: {retry_err} - using market")
                    return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_LIMIT_FAIL"
            else:
                if force_maker_only:
                    logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: Limit order failed - NOT using market (hedged). Will retry later.")
                    return None, False, "MAKER_ONLY_RETRY"
                logger.warning(f"⚠️ [HYBRID-LIMIT] {symbol}: Limit order failed: {limit_err} - using market")
                return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_LIMIT_FAIL"
        
        if not limit_order:
            if force_maker_only:
                logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: No limit order - NOT using market (hedged). Will retry later.")
                return None, False, "MAKER_ONLY_RETRY"
            return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_NO_LIMIT"
        
        order_id = limit_order.get('orderId')
        
        # Wait for fill (with periodic checks)
        check_interval = min(5, wait_seconds)  # Check every 5s or less
        elapsed = 0
        filled = False
        
        while elapsed < wait_seconds:
            time.sleep(check_interval)
            elapsed += check_interval
            
            try:
                order_status = self.binance.futures_get_order(symbol=symbol, orderId=order_id)
                status = order_status.get('status', '')
                
                if status == 'FILLED':
                    filled = True
                    executed_qty = float(order_status.get('executedQty', quantity))
                    avg_price = float(order_status.get('avgPrice', limit_price))
                    
                    # Calculate fee savings
                    notional = executed_qty * avg_price
                    fee_saved = notional * (TAKER_FEE_PCT - MAKER_FEE_PCT) / 100
                    self.limit_fills += 1
                    self.total_fee_savings_usd += fee_saved
                    
                    logger.info(
                        f"✅ [HYBRID-LIMIT-FILL] {symbol} {order_side}: Limit FILLED @ {avg_price:.4f} "
                        f"after {elapsed}s | Fee saved: ${fee_saved:.4f} | Total saved: ${self.total_fee_savings_usd:.2f}"
                    )
                    return order_status, True, "LIMIT_FILLED"
                    
                elif status in ('CANCELED', 'REJECTED', 'EXPIRED'):
                    if force_maker_only:
                        logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: Limit order {status} - NOT using market (hedged). Will retry later.")
                        return None, False, "MAKER_ONLY_RETRY"
                    logger.info(f"🔄 [HYBRID-LIMIT] {symbol}: Limit order {status} - using market fallback")
                    break
                    
                # Still open - continue waiting
                logger.debug(f"[HYBRID-LIMIT] {symbol}: Order status={status}, elapsed={elapsed}/{wait_seconds}s")
                
            except Exception as check_err:
                logger.warning(f"[HYBRID-LIMIT] {symbol}: Error checking order status: {check_err}")
        
        # Timeout or cancelled - cancel limit and use market (unless force_maker_only)
        if not filled:
            try:
                self.binance.futures_cancel_order(symbol=symbol, orderId=order_id)
                logger.info(f"🚫 [HYBRID-LIMIT] {symbol}: Cancelled unfilled limit order (ID: {order_id})")
            except Exception as cancel_err:
                # May already be cancelled/filled
                cancel_str = str(cancel_err)
                if 'UNKNOWN_ORDER' not in cancel_str and '-2011' not in cancel_str:
                    logger.debug(f"[HYBRID-LIMIT] {symbol}: Cancel error (may be filled): {cancel_err}")
                    
                    # Double-check if it filled while we were cancelling
                    try:
                        final_status = self.binance.futures_get_order(symbol=symbol, orderId=order_id)
                        if final_status.get('status') == 'FILLED':
                            executed_qty = float(final_status.get('executedQty', quantity))
                            avg_price = float(final_status.get('avgPrice', limit_price))
                            notional = executed_qty * avg_price
                            fee_saved = notional * (TAKER_FEE_PCT - MAKER_FEE_PCT) / 100
                            self.limit_fills += 1
                            self.total_fee_savings_usd += fee_saved
                            logger.info(f"✅ [HYBRID-LIMIT-FILL] {symbol}: Filled during cancel! Fee saved: ${fee_saved:.4f}")
                            return final_status, True, "LIMIT_FILLED_LATE"
                    except:
                        pass
            
            # Execute market fallback (unless force_maker_only)
            if force_maker_only:
                logger.warning(f"🛡️ [HEDGE-MAKER-ONLY] {symbol}: Timeout after {wait_seconds}s - NOT using market (hedged position). Stop will be retried on next trigger.")
                return None, False, "MAKER_ONLY_TIMEOUT"
            
            self.market_fallbacks += 1
            logger.info(f"🔄 [HYBRID-LIMIT] {symbol}: Timeout after {wait_seconds}s - executing MARKET fallback")
            return self._execute_market_order(symbol, order_side, position_side, quantity, stop), False, "MARKET_TIMEOUT"
        
        return limit_order, True, "LIMIT_FILLED"
    
    def _execute_market_order(
        self,
        symbol: str,
        order_side: str,
        position_side: str,
        quantity: float,
        stop: StealthStop
    ) -> Optional[Dict]:
        """Execute a market order with reduceOnly handling."""
        order = None
        _, qty = self._prepare_order_params(symbol, order_side, quantity, None)
        if qty is None:
            return None
        
        # First attempt: with reduceOnly=True
        try:
            order = self.binance.futures_create_order(
                symbol=symbol,
                side=order_side,
                positionSide=position_side,
                type='MARKET',
                quantity=qty,
                reduceOnly=True
            )
            logger.info(f"STEALTH_MARKET_OK | {symbol} {order_side} | reduceOnly=True | order_id={order.get('orderId')}")
            return order
            
        except Exception as first_err:
            err_str = str(first_err)
            
            # -2022: Position already closed — immediately clean up, no retry
            if '-2022' in err_str:
                logger.info(f"[STEALTH-ALREADY-CLOSED] Position already closed: {symbol} - cleaning up stops")
                _closed_side = "LONG" if str(position_side).upper() == "LONG" else "SHORT"
                self.remove_all_for_symbol_side(symbol, _closed_side)
                return {'status': 'POSITION_CLOSED', 'symbol': symbol}
            
            # -1106: reduceOnly not required - retry without it using direction-check only
            if '-1106' in err_str or 'reduceOnly' in err_str.lower():
                _is_close_dir = (
                    (str(position_side).upper() == "SHORT" and str(order_side).upper() == "BUY") or
                    (str(position_side).upper() == "LONG"  and str(order_side).upper() == "SELL")
                )
                if not _is_close_dir:
                    logger.error(
                        f"STEALTH_MARKET_BLOCK | {symbol} {order_side} | positionSide={position_side} | "
                        f"unsafe_direction | reduceOnly_rejected=1 | retry_without_reduceOnly=0 | qty={qty}"
                    )
                    raise first_err
                try:
                    order = self.binance.futures_create_order(
                        symbol=symbol,
                        side=order_side,
                        positionSide=position_side,
                        type='MARKET',
                        quantity=qty
                    )
                    logger.info(
                        f"STEALTH_MARKET_OK | {symbol} {order_side} | positionSide={position_side} | "
                        f"reduceOnly=False(-1106) | order_id={order.get('orderId')}"
                    )
                    return order
                except Exception as retry_err:
                    if '-2022' in str(retry_err):
                        logger.info(f"[STEALTH-ALREADY-CLOSED] Position closed during market retry: {symbol}")
                        _closed_side = "LONG" if str(position_side).upper() == "LONG" else "SHORT"
                        self.remove_all_for_symbol_side(symbol, _closed_side)
                        return {'status': 'POSITION_CLOSED', 'symbol': symbol}
                    raise retry_err
            
            raise first_err

    def _execute_stop(self, stop: StealthStop, current_price: float) -> bool:
        """Execute the conditional order using hybrid limit → market strategy.
        
        Uses POST_ONLY limit orders first to save maker fees.
        Falls back to market orders if limit doesn't fill within timeout.
        
        Handles -1106 "reduceOnly not required" error by retrying without reduceOnly.
        Handles -2022 "ReduceOnly Order is rejected" when position already closed.
        """
        try:
            self.stops_triggered += 1
            
            # CRITICAL FIX: Check if position still exists before executing
            # This prevents -2022 errors when position was already closed
            try:
                positions = self.binance.futures_position_information(symbol=stop.symbol)
                position_exists = False
                for pos in positions:
                    pos_amt = float(pos.get('positionAmt', 0))
                    pos_side = 'LONG' if pos_amt > 0 else 'SHORT' if pos_amt < 0 else None
                    if pos_side == stop.side and abs(pos_amt) > 0:
                        position_exists = True
                        # Update position size from current data
                        stop.position_size = abs(pos_amt)
                        # Best-effort entry price for Telegram PnL
                        try:
                            stop.entry_price = float(pos.get("entryPrice") or 0.0)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        break
                
                if not position_exists:
                    logger.warning(f"[STEALTH-SKIP] Position no longer exists: {stop.symbol} {stop.side} - removing all stops for this side")
                    self.remove_all_for_symbol_side(stop.symbol, stop.side)
                    return True  # safe to remove; nothing to do
            except Exception as check_err:
                logger.debug(f"[STEALTH] Position check failed (proceeding anyway): {check_err}")

            # NOTE: Hedge-flatten confirm-ticks (STEALTH_HEDGE_FLATTEN_CONFIRM_TICKS) gate was
            # moved to the _monitor_loop before the orch_enabled branch so it applies in both
            # orchestrator-publish and direct-execute modes. Do not re-check here to avoid
            # double-counting ticks when orch_enabled=False.

            # ========================================================================
            # P4 ALIGNMENT: Respect adaptive hedge lock (prevents closing hedge
            # leg while trader considers the hedge protective)
            # SL always executes (safety); TP/TRAIL on hedged leg checks lock.
            # ========================================================================
            try:
                if self.redis and str(stop.stop_type or '').upper() != 'STOP_LOSS':
                    _hl_key = f"hedge:lock:{stop.symbol}:{self.account_id}"
                    if self.redis.exists(_hl_key):
                        logger.warning(
                            "STEALTH_HEDGE_LOCK_BLOCK | sym=%s side=%s type=%s | "
                            "Hedge lock active — deferring stealth execution",
                            stop.symbol, stop.side, stop.stop_type,
                        )
                        return False  # Keep stop armed, retry next cycle
            except Exception:
                pass
            
            # ========================================================================
            # CRITICAL: Cross-check price against Binance API before executing
            # This prevents false triggers from corrupt/stale Redis data
            # ========================================================================
            try:
                api_prices = self.binance.futures_mark_price(symbol=stop.symbol)
                api_mark_price = float(api_prices['markPrice'])
                
                # Calculate deviation between trigger price and actual API price
                price_deviation = abs(current_price - api_mark_price) / api_mark_price * 100
                
                if price_deviation > 2:  # More than 2% difference = bad data
                    logger.error(
                        f"🚫 [STEALTH-ABORT] {stop.symbol}: "
                        f"Trigger price ({current_price:.4f}) differs {price_deviation:.1f}% from "
                        f"Binance API ({api_mark_price:.4f}) - ABORTING execution (likely bad data)"
                    )
                    return False  # Don't execute; keep stop armed
                
                # Also verify the stop should actually trigger at the REAL price
                if stop.stop_type == 'STOP_LOSS':
                    if stop.side == 'LONG' and api_mark_price > stop.trigger_price:
                        logger.warning(
                            f"⚠️ [STEALTH-FALSE-TRIGGER] {stop.symbol} LONG SL: "
                            f"API price ({api_mark_price:.4f}) is ABOVE trigger ({stop.trigger_price:.4f}) - NOT executing"
                        )
                        return False
                    elif stop.side == 'SHORT' and api_mark_price < stop.trigger_price:
                        logger.warning(
                            f"⚠️ [STEALTH-FALSE-TRIGGER] {stop.symbol} SHORT SL: "
                            f"API price ({api_mark_price:.4f}) is BELOW trigger ({stop.trigger_price:.4f}) - NOT executing"
                        )
                        return False
                        
                logger.info(f"[STEALTH-VERIFY] {stop.symbol}: API price ({api_mark_price:.4f}) confirms trigger")
                
            except Exception as verify_err:
                logger.warning(f"[STEALTH-VERIFY] Could not verify price via API (proceeding): {verify_err}")
            
            # Determine order side (opposite of position side)
            order_side = 'SELL' if stop.side == 'LONG' else 'BUY'
            
            # Determine position side for hedge mode
            position_side = stop.side  # Assuming hedge mode
            
            # Calculate quantity to close
            quantity_to_close = stop.position_size * (stop.close_percentage / 100.0)

            # --------------------------------------------------------------------
            # P0 Guardrail: Freeze/cap hedge TP trims (SHORT leg) while LONG is at risk
            # --------------------------------------------------------------------
            try:
                if str(stop.stop_type or '').upper() == 'TAKE_PROFIT' and str(stop.side or '').upper() == 'SHORT':
                    allow, adj_qty, reason, meta = self._hedge_tp_guard(stop.symbol, float(quantity_to_close or 0.0), float(api_mark_price or current_price or 0.0))
                    if not allow or float(adj_qty or 0.0) <= 0:
                        logger.warning(
                            "HEDGE_TP_GUARD | sym=%s side=SHORT action=CLOSE_SHORT reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=0.0",
                            stop.symbol,
                            reason,
                            f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                            float(meta.get('long_qty') or 0.0),
                            float(meta.get('short_qty') or 0.0),
                            float(meta.get('requested_qty') or 0.0),
                        )
                        return False
                    if float(adj_qty) + 1e-12 < float(quantity_to_close or 0.0):
                        logger.warning(
                            "HEDGE_TP_GUARD | sym=%s side=SHORT action=CLOSE_SHORT reason=%s liq_bps=%s long_qty=%.6f short_qty=%.6f requested_qty=%.6f executed_qty=%.6f",
                            stop.symbol,
                            reason,
                            f"{meta.get('liq_bps_long'):.1f}" if meta.get('liq_bps_long') is not None else "None",
                            float(meta.get('long_qty') or 0.0),
                            float(meta.get('short_qty') or 0.0),
                            float(meta.get('requested_qty') or 0.0),
                            float(adj_qty or 0.0),
                        )
                        quantity_to_close = float(adj_qty)
            except Exception:
                pass
            
            # Round to exchange precision (implement proper precision logic if needed)
            quantity_to_close = round(quantity_to_close, 3)
            
            # ====================================================================
            # TRAINER SIGNAL CHECK: Consult trainer's latest prediction before TP
            # STOP_LOSS always executes (safety). TAKE_PROFIT checks if trainer
            # agrees with the close direction or at minimum doesn't contradict.
            # Feature-flagged via STEALTH_TP_TRAINER_DEFERENCE (default: True).
            # ====================================================================
            try:
                from config import STEALTH_TP_TRAINER_DEFERENCE
            except ImportError:
                STEALTH_TP_TRAINER_DEFERENCE = True
            
            if STEALTH_TP_TRAINER_DEFERENCE and self._is_static_tp_stop(stop):
                try:
                    _redis_ref = getattr(self, 'redis', None)
                    if _redis_ref and stop.symbol:
                        # Read trainer's latest prediction for this symbol
                        _pred_key = f"prediction:{stop.symbol}"
                        _pred_raw = _redis_ref.hgetall(_pred_key)
                        if _pred_raw:
                            _trainer_action = str(
                                _pred_raw.get("action_name") or _pred_raw.get(b"action_name", b"")
                            ).upper().strip()
                            if isinstance(_trainer_action, bytes):
                                _trainer_action = _trainer_action.decode()
                            _trainer_conf = 0.0
                            try:
                                _trainer_conf = float(_pred_raw.get("confidence") or _pred_raw.get(b"confidence", 0))
                            except Exception:
                                pass
                            
                            # If trainer is actively recommending OPEN on the SAME side with
                            # high confidence, defer the TP to let the position run.
                            _tp_side_u = str(stop.side or '').upper()
                            _trainer_contradicts = False
                            if _tp_side_u == "LONG" and _trainer_action in ("OPEN_LONG", "INCREASE_LONG") and _trainer_conf >= 0.92:
                                _trainer_contradicts = True
                            elif _tp_side_u == "SHORT" and _trainer_action in ("OPEN_SHORT", "INCREASE_SHORT") and _trainer_conf >= 0.92:
                                _trainer_contradicts = True
                            
                            if _trainer_contradicts:
                                logger.info(
                                    "STEALTH_TP_TRAINER_DEFER | sym=%s side=%s | trainer_action=%s conf=%.3f | "
                                    "Deferring TP - trainer wants to keep/add to this side",
                                    stop.symbol, _tp_side_u, _trainer_action, _trainer_conf,
                                )
                                # #region agent log
                                try:
                                    import json as _dj
                                    import time as _dt
                                    open("/home/wali/Desktop/AI BOT/.cursor/debug-1acbe2.log", "a").write(
                                        _dj.dumps(
                                            {
                                                "sessionId": "1acbe2",
                                                "hypothesisId": "H3",
                                                "location": "stealth_stops:tp_defer_trainer",
                                                "message": "tp_deferred_trainer_contradicts",
                                                "data": {
                                                    "symbol": str(stop.symbol),
                                                    "side": str(_tp_side_u),
                                                    "trainer_action": str(_trainer_action),
                                                    "trainer_conf": round(float(_trainer_conf), 6),
                                                },
                                                "timestamp": int(_dt.time() * 1000),
                                            }
                                        )
                                        + "\n"
                                    )
                                except Exception:
                                    pass
                                # #endregion
                                return False  # Keep stop armed, don't execute TP
                            else:
                                logger.debug(
                                    "STEALTH_TP_TRAINER_OK | sym=%s side=%s | trainer_action=%s conf=%.3f | "
                                    "TP execution allowed",
                                    stop.symbol, _tp_side_u, _trainer_action, _trainer_conf,
                                )
                except Exception as _trd_err:
                    logger.debug(f"[STEALTH_TP_TRAINER_CHECK] Failed (proceeding): {_trd_err}")

            # ====================================================================
            # INTELLIGENCE CLOSE GATE: Consult unified 7-source market intelligence
            # before allowing TP or TRAIL execution. SL always bypasses (safety).
            # Emergency exits (ROI_KILL) always bypass.
            # Kill switch: INTELLIGENCE_STEALTH_TP_GATE_ENABLED (config.py)
            # ====================================================================
            _stop_type_u = str(stop.stop_type or '').upper()
            _reason_u_intel = str(stop.reason or '').upper()
            _is_sl_type = (_stop_type_u == 'STOP_LOSS' and 'TRAIL' not in _reason_u_intel)
            _is_emergency = ('ROI_KILL' in _reason_u_intel or 'PER_LEG_ROI_KILL' in _reason_u_intel
                             or 'GOVERNOR' in _reason_u_intel or 'MARGIN_UTIL' in _reason_u_intel)
            if not _is_sl_type and not _is_emergency:
                try:
                    from config import INTELLIGENCE_STEALTH_TP_GATE_ENABLED
                    _intel_gate_on = bool(INTELLIGENCE_STEALTH_TP_GATE_ENABLED)
                except Exception:
                    _intel_gate_on = True
                if _intel_gate_on:
                    try:
                        from trading.market_intelligence import should_allow_close as _mi_allow_close
                        # Estimate ROE from entry + current price
                        _mi_entry = float(getattr(stop, 'entry_price', 0) or 0)
                        _mi_roe = 0.0
                        if _mi_entry > 0 and current_price > 0:
                            if stop.side.upper() == 'LONG':
                                _mi_roe = ((current_price - _mi_entry) / _mi_entry) * 100.0
                            else:
                                _mi_roe = ((_mi_entry - current_price) / _mi_entry) * 100.0
                        _mi_allow, _mi_reason, _mi_hold = _mi_allow_close(
                            self.redis, stop.symbol, stop.side,
                            close_source=f"stealth_{_stop_type_u.lower()}",
                            roe_pct=_mi_roe,
                        )
                        if not _mi_allow:
                            logger.info(
                                "INTEL_STEALTH_TP_DEFER | sym=%s side=%s type=%s | "
                                "hold_score=%.3f roe=%.1f%% | %s",
                                stop.symbol, stop.side, _stop_type_u,
                                _mi_hold, _mi_roe, _mi_reason,
                            )
                            # #region agent log
                            try:
                                import json as _dj
                                import time as _dt
                                open("/home/wali/Desktop/AI BOT/.cursor/debug-1acbe2.log", "a").write(
                                    _dj.dumps(
                                        {
                                            "sessionId": "1acbe2",
                                            "hypothesisId": "H4",
                                            "location": "stealth_stops:intel_tp_defer",
                                            "message": "tp_deferred_intelligence_gate",
                                            "data": {
                                                "symbol": str(stop.symbol),
                                                "side": str(stop.side),
                                                "stop_type": str(_stop_type_u),
                                                "roe_pct": round(float(_mi_roe), 4),
                                                "reason": str(_mi_reason)[:200],
                                            },
                                            "timestamp": int(_dt.time() * 1000),
                                        }
                                    )
                                    + "\n"
                                )
                            except Exception:
                                pass
                            # #endregion
                            return False  # Keep stop armed, retry next cycle
                        else:
                            logger.debug(
                                "INTEL_STEALTH_TP_ALLOW | sym=%s side=%s type=%s | "
                                "hold=%.3f roe=%.1f%% | %s",
                                stop.symbol, stop.side, _stop_type_u,
                                _mi_hold, _mi_roe, _mi_reason,
                            )
                    except ImportError:
                        pass
                    except Exception as _mi_gate_err:
                        logger.debug("INTEL_STEALTH_TP_ERR | %s | %s", stop.symbol, _mi_gate_err)

            # Enhanced logging for trailing stops (matches hydration logging format)
            if 'TRAIL' in stop.reason.upper():
                logger.info(
                    f"STEALTH_TRAIL_TRIGGERED | {stop.symbol} {stop.side} | "
                    f"trigger_price={stop.trigger_price:.4f} | current_price={current_price:.4f} | "
                    f"qty={quantity_to_close}"
                )
            
            # ====================================================================
            # HEDGE MAKER-ONLY: If position is hedged, enforce maker-only execution
            # Do not fall back to market orders - cancel if limit doesn't fill
            # ====================================================================
            # Emergency exits must not be forced into maker-only mode (survival > fees).
            is_emergency_exit = False
            try:
                _ru = str(stop.reason or "").upper()
                if "ROI_KILL" in _ru or "PER_LEG_ROI_KILL" in _ru:
                    is_emergency_exit = True
                else:
                    is_emergency_exit = bool(
                        getattr(stop, "override_profit_guard", False)
                        or getattr(stop, "proactive_override", False)
                        or getattr(stop, "override_safety_block", False)
                        or getattr(stop, "fastlane", False)
                    )
            except Exception:
                is_emergency_exit = False
            force_maker_only = getattr(stop, 'hedge_maker_only', False)
            if is_emergency_exit:
                if force_maker_only:
                    logger.warning(
                        "🛡️ [HEDGE-MAKER-ONLY-EMERGENCY-BYPASS] %s %s | type=%s | reason=%s",
                        stop.symbol, stop.side, stop.stop_type, str(stop.reason or "")[:200],
                    )
                force_maker_only = False
            elif not force_maker_only:
                # Check config and hedge status at execution time
                try:
                    from config import STEALTH_HEDGE_PROTECTION_ENABLED, STEALTH_HEDGE_MAKER_ONLY
                    if STEALTH_HEDGE_PROTECTION_ENABLED and STEALTH_HEDGE_MAKER_ONLY:
                        is_hedged = self._check_hedge_status(stop.symbol, stop.side)
                        if is_hedged:
                            force_maker_only = True
                            logger.info(f"🛡️ [HEDGE-MAKER-ONLY] {stop.symbol}: Enforcing maker-only execution for hedged position")
                except ImportError:
                    pass
            
            logger.warning(f"⚡ [STEALTH-EXECUTE] Starting {'MAKER-ONLY' if force_maker_only else 'hybrid'} execution: {stop.symbol} {order_side} "
                          f"{quantity_to_close} (was {stop.stop_type} @ {stop.trigger_price}, "
                          f"triggered @ {current_price})")
            
            # ====================================================================
            # HYBRID EXECUTION: Try POST_ONLY limit first, fallback to market
            # This saves ~0.04% per trade via maker fees
            # If force_maker_only=True, do NOT fall back to market
            # ====================================================================
            if is_emergency_exit and not force_maker_only:
                logger.warning(
                    "STEALTH_EMERGENCY_MARKET_DIRECT | %s %s | type=%s | reason=%s",
                    stop.symbol, stop.side, stop.stop_type, str(stop.reason or "")[:200],
                )
                order = self._execute_market_order(stop.symbol, order_side, position_side, quantity_to_close, stop)
                used_limit = False
                exec_method = "MARKET_DIRECT_EMERGENCY"
            else:
                order, used_limit, exec_method = self._execute_hybrid_limit_order(
                    symbol=stop.symbol,
                    order_side=order_side,
                    position_side=position_side,
                    quantity=quantity_to_close,
                    current_price=current_price,
                    stop=stop,
                    force_maker_only=force_maker_only
                )
            
            if order and order.get('status') != 'POSITION_CLOSED':
                self.stops_executed += 1
                
                fee_type = "MAKER" if used_limit else "TAKER"
                logger.info(
                    f"✅ [STEALTH-SUCCESS] {stop.stop_type} executed: {stop.symbol} {stop.side} "
                    f"@ {current_price} (order ID: {order.get('orderId')}, method={exec_method}, fee={fee_type})"
                )

                # Telegram: alert on TP trigger / stealth execution (include maker/taker)
                try:
                    if self.telegram:
                        acct = self._account_label()
                        liq = "MAKER" if used_limit else "TAKER"
                        fill_px = float(order.get("avgPrice", 0) or 0) or float(current_price or 0)
                        qty_exec = float(order.get("executedQty", 0) or 0) or float(quantity_to_close or 0)
                        is_trailing = "TRAIL" in (stop.reason or "").upper()
                        title = "TRAILING EXIT" if is_trailing else stop.stop_type.replace("_", " ")
                        emoji = "🎯" if stop.stop_type == "TAKE_PROFIT" else "🛑" if stop.stop_type == "STOP_LOSS" else "🏁"
                        hedged_note = "🛡️ <b>HEDGED: MAKER-ONLY</b>\n" if force_maker_only else ""

                        pnl_line = ""
                        try:
                            entry_px = float(getattr(stop, "entry_price", 0.0) or 0.0)
                            if entry_px > 0 and qty_exec > 0:
                                pnl = (fill_px - entry_px) * qty_exec if stop.side == "LONG" else (entry_px - fill_px) * qty_exec
                                pnl_pct = (pnl / (entry_px * qty_exec)) * 100.0
                                pnl_line = f"P&L: <b>${pnl:+.2f}</b> ({pnl_pct:+.2f}%)\n"
                        except Exception:
                            pnl_line = ""

                        msg = (
                            f"{emoji} <b>STEALTH {title} EXECUTED</b>\n\n"
                            f"👤 <b>{acct}</b>\n"
                            f"📊 <b>{stop.symbol}</b> | {stop.side}\n"
                            f"{hedged_note}"
                            f"Trigger: <b>{float(stop.trigger_price):.4f}</b>\n"
                            f"Executed: <b>{fill_px:.4f}</b>\n"
                            f"Qty: <b>{qty_exec:.6f}</b>\n"
                            f"{pnl_line}"
                            f"Method: <b>{exec_method}</b>\n"
                            f"Liquidity: <b>{liq}</b>\n"
                            f"Order ID: <b>{order.get('orderId')}</b>\n"
                            f"Reason: <code>{str(stop.reason or '')[:400]}</code>"
                        )
                        self._send_trade_alert_async(msg)
                except Exception:
                    pass
                
                # Publish to executed_signals for feedback
                self._publish_execution_feedback(stop, order, current_price, exec_method, used_limit)
                
                # Publish execution feedback to wma:trader:execution_feedback for HEDGE_BUILD state
                exec_px = float(order.get("avgPrice", 0) or 0) or float(current_price or 0)
                self._publish_trail_exit_feedback(stop, order, exec_px)
                self._publish_profit_exit_feedback(stop, order, exec_px)
                self._publish_loss_exit_feedback(stop, order, exec_px)

                # ── P1 ALIGNMENT: Notify kill budget of stealth SL close ──
                # Stealth SL/trail closes bypass the trainer's ROI kill path,
                # so we publish a Redis counter so P1's adaptive budget accounts
                # for them and doesn't double-allocate kills.
                try:
                    if self.redis and stop.stop_type == 'STOP_LOSS':
                        _sk_key = f"stealth:kills:{self.account_id}"
                        self.redis.hincrby(_sk_key, "count", 1)
                        self.redis.expire(_sk_key, 3600)  # 1hr TTL matches kill budget window
                        logger.info(
                            "STEALTH_KILL_BUDGET_NOTIFY | sym=%s side=%s reason=%s | "
                            "Incremented stealth kill counter for P1 budget alignment",
                            stop.symbol, stop.side, str(stop.reason or '')[:80],
                        )
                except Exception:
                    pass

                # ── RAMP Phase 5: Scale-up winning counterpart ──
                # After a trailing SL / ROI kill closes a losing leg,
                # emit an INCREASE signal for the winning counterpart
                # using a fraction of the freed margin.
                try:
                    _is_sl_trail = stop.stop_type == "STOP_LOSS" and "TRAIL" in str(stop.reason or "").upper()
                    _is_roi_kill = "ROI_KILL" in str(stop.reason or "").upper()
                    if (_is_sl_trail or _is_roi_kill) and self.redis:
                        self._ramp_scale_up_winner(stop, order, exec_px)
                except Exception:
                    pass
                
            elif order and order.get('status') == 'POSITION_CLOSED':
                # Position was already closed — clean up all stops for this side
                self.stops_executed += 1
                logger.info(f"[STEALTH-ALREADY-CLOSED] {stop.symbol} {stop.side} - stop achieved (position closed)")
                self.remove_all_for_symbol_side(stop.symbol, stop.side)
            return True
            
        except Exception as e:
            self.stops_failed += 1
            logger.error(f"❌ [STEALTH-FAIL] Failed to execute {stop.stop_type} for {stop.symbol}: {e}")
            return False

    def _execute_ioc_order(
        self,
        symbol: str,
        order_side: str,
        position_side: str,
        quantity: float,
        price: float,
        stop: StealthStop,
    ) -> Optional[Dict]:
        """Execute reduce-only IOC limit order; fallback to market on failure.
        
        FIX-RCA-8: Added consecutive failure tracking. After 3 consecutive IOC
        failures for the same symbol:side, escalate directly to market order.
        After 5, disarm the stop entirely (position likely already gone).
        """
        # Track consecutive failures per symbol:side for circuit breaking
        _fail_key = f"{symbol}:{position_side}:ioc_fails"
        if not hasattr(self, '_ioc_fail_counter'):
            self._ioc_fail_counter = {}
        _fail_info = self._ioc_fail_counter.get(_fail_key, {"count": 0, "first_ts": 0.0})
        
        # If too many consecutive failures, escalate
        if _fail_info["count"] >= 5:
            _age = time.time() - _fail_info.get("first_ts", 0.0)
            logger.warning(
                "TP_IOC_CIRCUIT_BREAK | %s %s | consecutive_fails=%d age=%.0fs -> disarming stop",
                symbol, position_side, _fail_info["count"], _age
            )
            # Disarm: clear touch state and stop retrying
            _stale_key = f"{symbol}:{position_side}:TAKE_PROFIT"
            if hasattr(self, '_tp_touch_state') and _stale_key in self._tp_touch_state:
                del self._tp_touch_state[_stale_key]
            self._ioc_fail_counter[_fail_key] = {"count": 0, "first_ts": 0.0}
            # Clean up all stops for this side (position likely liquidated)
            _closed_side = "LONG" if str(position_side).upper() == "LONG" else "SHORT"
            self.remove_all_for_symbol_side(symbol, _closed_side)
            return None
        
        if _fail_info["count"] >= 3:
            # Escalate directly to market order — IOC is failing repeatedly
            logger.warning(
                "TP_IOC_ESCALATE_MARKET | %s %s | consecutive_fails=%d -> market fallback",
                symbol, position_side, _fail_info["count"]
            )
            _fail_info["count"] += 1
            self._ioc_fail_counter[_fail_key] = _fail_info
            return self._execute_market_order(symbol, order_side, position_side, quantity, stop)
        
        try:
            px, qty = self._prepare_order_params(symbol, order_side, quantity, price)
            if px is None or qty is None:
                return None
            order = self.binance.futures_create_order(
                symbol=symbol,
                side=order_side,
                positionSide=position_side,
                type='LIMIT',
                price=px,
                quantity=qty,
                timeInForce='IOC',
                reduceOnly=True
            )
            logger.info(f"TP_IOC_OK | {symbol} {order_side} | price={price:.6f} qty={quantity:.6f} | order_id={order.get('orderId')}")
            # Success — reset failure counter
            self._ioc_fail_counter[_fail_key] = {"count": 0, "first_ts": 0.0}
            return order
        except Exception as e:
            err_str = str(e)
            if '-1106' in err_str or 'reduceOnly' in err_str.lower():
                # -1106: exchange says reduceOnly not required/supported for this order type.
                # In hedge mode, positionSide already guarantees close-only semantics.
                # Do NOT call _safe_allow_no_reduceonly — it queries position info and returns
                # False when the position is mid-close (qty→0), causing a permanent block.
                _is_close_dir = (
                    (position_side.upper() == "SHORT" and order_side.upper() == "BUY") or
                    (position_side.upper() == "LONG" and order_side.upper() == "SELL")
                )
                if _is_close_dir:
                    try:
                        # Safety: clamp qty to actual position size to prevent
                        # accidental opener if position closed between first attempt and retry.
                        _safe_qty = float(quantity)
                        try:
                            _pos_info = self.binance.futures_position_information(symbol=symbol)
                            for _p in (_pos_info or []):
                                _ps = str(_p.get("positionSide", "")).upper()
                                if _ps == position_side.upper():
                                    _pos_amt = abs(float(_p.get("positionAmt", 0) or 0))
                                    if _pos_amt <= 0:
                                        logger.warning(
                                            "TP_IOC_BLOCK | %s %s | positionSide=%s | -1106_retry | pos_amt=0 -> skip (position gone)",
                                            symbol, order_side, position_side
                                        )
                                        # Disarm stale TP touch state so the monitor stops
                                        # hammering a position that no longer exists.
                                        # The stop object itself will be removed on next
                                        # position-sync cycle; this prevents it closing any
                                        # new position that opens in the same symbol.
                                        _stale_key = f"{symbol}:{position_side}:TAKE_PROFIT"
                                        if hasattr(self, '_tp_touch_state') and _stale_key in self._tp_touch_state:
                                            del self._tp_touch_state[_stale_key]
                                            logger.warning(
                                                "TP_STALE_DISARMED | %s | positionSide=%s | touch_state cleared (pos_amt=0)",
                                                symbol, position_side
                                            )
                                        return None
                                    _safe_qty = min(_safe_qty, _pos_amt)
                                    break
                        except Exception as _pos_e:
                            logger.debug("TP_IOC_POS_CHECK_SKIP | %s | %s", symbol, _pos_e)
                        px, qty = self._prepare_order_params(symbol, order_side, _safe_qty, price)
                        if px is not None and qty is not None:
                            logger.info(
                                "EXEC_CLIENT | route=futures | symbol=%s | type=LIMIT/IOC | reduceOnly=False | retry_reason=-1106 | qty=%.6f",
                                symbol, _safe_qty
                            )
                            order = self.binance.futures_create_order(
                                symbol=symbol,
                                side=order_side,
                                positionSide=position_side,
                                type='LIMIT',
                                price=px,
                                quantity=qty,
                                timeInForce='IOC'
                            )
                            logger.info(
                                "TP_IOC_OK | %s %s | price=%.6f qty=%.6f | reduceOnly=False(-1106) | order_id=%s",
                                symbol, order_side, price, _safe_qty, order.get('orderId')
                            )
                            return order
                    except Exception as _retry_e:
                        _retry_e_str = str(_retry_e)
                        if '-2022' in _retry_e_str:
                            # Position closed — clean up immediately, do NOT retrigger
                            logger.info(
                                "[STEALTH-ALREADY-CLOSED] TP_IOC_LIMIT_RETRY_2022 | %s %s | "
                                "pos closed -> cleaning up stops (no retry)",
                                symbol, order_side
                            )
                            _closed_side = "LONG" if str(position_side).upper() == "LONG" else "SHORT"
                            self.remove_all_for_symbol_side(symbol, _closed_side)
                            return None
                        logger.warning(
                            "TP_IOC_RETRY_FAIL | %s %s | %s -> MARKET fallback",
                            symbol, order_side, _retry_e
                        )
                else:
                    logger.error(
                        "TP_IOC_BLOCK | %s %s | positionSide=%s | reduceOnly_rejected=1 | unsafe_direction",
                        symbol, order_side, position_side
                    )
            logger.warning(f"TP_IOC_FAIL | {symbol} {order_side} | {e} -> MARKET fallback")
            # FIX-RCA-8: Track consecutive failures for circuit breaking
            _fail_info["count"] = _fail_info.get("count", 0) + 1
            if _fail_info.get("first_ts", 0.0) <= 0:
                _fail_info["first_ts"] = time.time()
            self._ioc_fail_counter[_fail_key] = _fail_info
            return self._execute_market_order(symbol, order_side, position_side, quantity, stop)

    def _finalize_stop_execution(self, stop: StealthStop, order: Dict, current_price: float, exec_method: str, used_limit: bool = False):
        """Shared finalize path for TP/SL executions."""
        try:
            if order and order.get('status') == 'POSITION_CLOSED':
                self.stops_executed += 1
                logger.info(f"[STEALTH-ALREADY-CLOSED] {stop.symbol} {stop.side} - stop achieved (position closed)")
                # Position is gone — immediately clean up all remaining stops for this side
                self.remove_all_for_symbol_side(stop.symbol, stop.side)
                return

            if order:
                self.stops_executed += 1
                fee_type = "MAKER" if used_limit else "TAKER"
                logger.info(
                    f"✅ [STEALTH-SUCCESS] {stop.stop_type} executed: {stop.symbol} {stop.side} "
                    f"@ {current_price} (order ID: {order.get('orderId')}, method={exec_method}, fee={fee_type})"
                )
                self._publish_execution_feedback(stop, order, current_price, exec_method, used_limit)
                exec_px = float(order.get("avgPrice", 0) or 0) or float(current_price or 0)
                self._publish_trail_exit_feedback(stop, order, exec_px)
                self._publish_profit_exit_feedback(stop, order, exec_px)
                self._publish_loss_exit_feedback(stop, order, exec_px)

                # If this was a full close (100%), clean up remaining stops for this side
                if float(stop.close_percentage or 0) >= 99.9:
                    self.remove_all_for_symbol_side(stop.symbol, stop.side)
        except Exception:
            pass
    
    def _ramp_scale_up_winner(self, stop: StealthStop, order: Dict, exec_px: float) -> None:
        """RAMP Phase 5: After closing a losing leg, emit a signal to increase
        the winning counterpart using a portion of the freed margin.

        Safeguards:
        - Counterpart must exist and be profitable (ROI > 5%)
        - Regime must confirm the direction
        - Microstructure must confirm genuine move (p_false < 0.3)
        - Maximum 50% of freed margin allocated
        - Routed as HEDGE category (still passes hedge risk gates)
        """
        try:
            import json as _rjsu
            counter_side = "SHORT" if stop.side.upper() == "LONG" else "LONG"

            # Find counterpart position from positions:live:{symbol} nested hash
            counter_pos = None
            import json as _rjsu
            _ph = self.redis.hgetall(f"positions:live:{stop.symbol.upper()}")
            if _ph:
                _pd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _ph.items()}
                _counter_raw = _pd.get(counter_side.lower())
                if _counter_raw:
                    _cp = _rjsu.loads(_counter_raw) if isinstance(_counter_raw, str) else {}
                    if isinstance(_cp, dict) and _cp.get("has_position") and abs(float(_cp.get("size", 0) or 0)) > 0:
                        counter_pos = _cp

            if not counter_pos:
                return

            _c_roi = float(counter_pos.get("roi_pct") or counter_pos.get("roe_pct") or counter_pos.get("percentage") or 0)
            if _c_roi < 5.0:
                return

            # Regime confirmation
            regime_raw = self.redis.get(f"regime:{stop.symbol}")
            if not regime_raw:
                return
            regime = _rjsu.loads(regime_raw.decode() if isinstance(regime_raw, bytes) else str(regime_raw))
            _td = str(regime.get("trend_direction", "")).upper()
            regime_aligned = (
                (counter_side == "LONG" and _td in ("LONG", "BULLISH", "UP"))
                or (counter_side == "SHORT" and _td in ("SHORT", "BEARISH", "DOWN"))
            )
            if not regime_aligned:
                return

            # Microstructure confirmation
            from risk.intelligent_close_guard import _decode_map
            msnap_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{stop.symbol}")
            if not msnap_raw:
                return
            msnap = _decode_map(msnap_raw)
            _fm = float(msnap.get("fast_move_score", 0) or 0)
            _pf = float(msnap.get("p_false_move", 1) or 1)
            if _fm < 0.5 or _pf > 0.3:
                return

            # Compute freed margin
            _freed_margin = abs(float(counter_pos.get("margin_used", 0) or counter_pos.get("initialMargin", 0) or counter_pos.get("isolatedWallet", 0) or 0))
            _alloc_pct = min(0.50, _fm * 0.5)
            _increase_margin = _freed_margin * _alloc_pct
            if _increase_margin < 5.0:
                return

            # Emit proposal
            from rl.trade_proposal import TradeProposal
            from rl.proposal_bus import emit_proposal
            proposal = TradeProposal.new(
                source="ramp_scale_up",
                account_id=str(self.account_id),
                symbol=stop.symbol,
                action_name=f"INCREASE_{counter_side}",
                action_category="HEDGE",
                confidence=min(0.95, _fm),
                urgency_score=0.8,
                no_loss_compliant=True,
                reduce_only=False,
                risk_add=1,
                side=counter_side,
                trigger_reason=f"RAMP_SCALE_UP: counter_roi={_c_roi:.1f}% freed={_freed_margin:.0f} alloc={_increase_margin:.0f}",
                market_context={
                    "symbol": stop.symbol,
                    "side": counter_side,
                    "margin_usd": float(_increase_margin),
                    "counter_roi_pct": float(_c_roi),
                    "fast_move": float(_fm),
                    "p_false_move": float(_pf),
                    "ramp_source": "scale_up",
                },
            ).to_dict()
            _emitted = emit_proposal(self.redis, stream="wma:proposals", proposal=proposal)
            if _emitted:
                logger.info(
                    "RAMP_SCALE_UP_EMITTED | sym=%s | closed=%s | scale=%s | "
                    "freed=$%.0f alloc=$%.0f | counter_roi=%.1f%% | fast_move=%.2f",
                    stop.symbol, stop.side, counter_side,
                    _freed_margin, _increase_margin, _c_roi, _fm,
                )
        except Exception as _su_err:
            logger.debug("RAMP_SCALE_UP_ERR | %s | %s", stop.symbol, _su_err)

    def _publish_trail_exit_feedback(self, stop: StealthStop, order: Dict, execution_price: float):
        """Publish trailing exit to Redis so trainer can enter HEDGE_BUILD state"""
        try:
            if 'TRAIL' not in stop.reason.upper():
                return  # Only for trailing stops

            qty_exec = 0.0
            try:
                qty_exec = float(order.get("executedQty", 0) or 0) or float(stop.position_size * (stop.close_percentage / 100.0) or 0)
            except Exception:
                qty_exec = 0.0
            
            # Calculate realized PnL (best-effort)
            pnl_pct = 0.0
            pnl_usd = 0.0
            entry_price = float(getattr(stop, "entry_price", 0.0) or 0.0)
            try:
                # Try to get entry price from position Redis key
                if entry_price <= 0:
                    pos_key = f"wma:{stop.account_id}:positions:{stop.symbol}"
                    pos_data = self.redis.hgetall(pos_key)
                    if pos_data:
                        side_key = 'long' if stop.side == 'LONG' else 'short'
                        side_data = pos_data.get(side_key)
                        if side_data:
                            side_json = json.loads(side_data)
                            entry_price = float(side_json.get('entry_price', 0))
                # Fallback: resolve via portfolio:positions or Binance API
                if entry_price <= 0:
                    try:
                        entry_price, _, _src = self._resolve_leg_entry_pnl(
                            stop.symbol, stop.side, stop.account_id
                        )
                        if entry_price > 0:
                            logger.info(
                                "TRAIL_EXIT_ENTRY_RESOLVED | sym=%s side=%s entry=%.6f src=%s",
                                stop.symbol, stop.side, entry_price, _src,
                            )
                    except Exception:
                        entry_price = 0.0
                if entry_price > 0:
                    if stop.side == 'LONG':
                        pnl_pct = ((execution_price - entry_price) / entry_price) * 100
                    else:  # SHORT
                        pnl_pct = ((entry_price - execution_price) / entry_price) * 100
                    if qty_exec > 0:
                        pnl_usd = (execution_price - entry_price) * qty_exec if stop.side == "LONG" else (entry_price - execution_price) * qty_exec
            except Exception as e:
                logger.debug(f"[STEALTH-STOPS] Could not calculate PnL for feedback: {e}")
            
            feedback = {
                'timestamp': time.time(),
                'ts_ms': int(time.time() * 1000),
                'event_type': 'TRAILING_EXIT',
                'symbol': stop.symbol,
                'side': stop.side,
                'account_id': stop.account_id,
                'executed_price': execution_price,
                'qty': qty_exec,
                'trigger_price': stop.trigger_price,
                'order_id': order.get('orderId'),
                'stop_type': stop.stop_type,
                'reason': stop.reason,
                # Unit-consistent PnL fields (trainer consumes realized_pnl_usd for profit-funded trim credit)
                'realized_pnl_usd': float(pnl_usd),
                'realized_pnl_pct': float(pnl_pct),
                'pnl_usd': float(pnl_usd),
                'pnl_pct': round(pnl_pct, 4),
                # Legacy: keep `pnl` as USD (not percent)
                'pnl': float(pnl_usd),
            }
            
            self.redis.xadd(
                'wma:trader:execution_feedback',
                {'data': json.dumps(feedback)},
                maxlen=500,
                approximate=True
            )
            logger.info(
                f"EXEC_FEEDBACK_TRAILING_EXIT account={stop.account_id} symbol={stop.symbol} side={stop.side} "
                f"qty={qty_exec:.6f} px={execution_price:.6f} pnl_pct={pnl_pct:.4f}"
            )
            
        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to publish trail exit feedback: {e}")

    def _publish_profit_exit_feedback(self, stop: StealthStop, order: Dict, execution_price: float):
        """Publish TAKE_PROFIT exits so trainer can enter HEDGE_BUILD state (PROFIT_EXIT)."""
        try:
            if stop.stop_type != 'TAKE_PROFIT':
                return
            # Trailing exits already handled by _publish_trail_exit_feedback
            if 'TRAIL' in stop.reason.upper():
                return
            if not self.redis:
                return

            # Resolve entry price: stop field → Redis/Binance fallback
            entry_price = float(getattr(stop, "entry_price", 0.0) or 0.0)
            if entry_price <= 0:
                try:
                    entry_price, _, _src = self._resolve_leg_entry_pnl(
                        stop.symbol, stop.side, stop.account_id
                    )
                    if entry_price > 0:
                        logger.info(
                            "PROFIT_EXIT_ENTRY_RESOLVED | sym=%s side=%s entry=%.6f src=%s",
                            stop.symbol, stop.side, entry_price, _src,
                        )
                except Exception:
                    entry_price = 0.0

            # Calculate realized PnL (best-effort)
            pnl_pct = 0.0
            pnl_usd = 0.0
            try:
                if entry_price > 0:
                    if stop.side == 'LONG':
                        pnl_pct = ((execution_price - entry_price) / entry_price) * 100
                    else:
                        pnl_pct = ((entry_price - execution_price) / entry_price) * 100
            except Exception:
                pnl_pct = 0.0

            qty_exec = 0.0
            try:
                qty_exec = float(order.get("executedQty", 0) or 0) or float(stop.position_size * (stop.close_percentage / 100.0) or 0)
            except Exception:
                qty_exec = 0.0
            try:
                if entry_price > 0 and qty_exec > 0:
                    pnl_usd = (execution_price - entry_price) * qty_exec if stop.side == "LONG" else (entry_price - execution_price) * qty_exec
            except Exception:
                pnl_usd = 0.0

            feedback = {
                'timestamp': time.time(),
                'ts_ms': int(time.time() * 1000),
                'event_type': 'PROFIT_EXIT',
                'symbol': stop.symbol,
                'side': stop.side,
                'account_id': stop.account_id,
                'executed_price': execution_price,
                'qty': qty_exec,
                'trigger_price': stop.trigger_price,
                'order_id': order.get('orderId'),
                'stop_type': stop.stop_type,
                'reason': stop.reason,
                # Unit-consistent PnL fields
                'realized_pnl_usd': float(pnl_usd),
                'realized_pnl_pct': float(pnl_pct),
                'pnl_usd': float(pnl_usd),
                'pnl_pct': round(pnl_pct, 4),
                # Legacy: keep `pnl` as USD (not percent)
                'pnl': float(pnl_usd),
            }

            self.redis.xadd(
                'wma:trader:execution_feedback',
                {'data': json.dumps(feedback)},
                maxlen=500,
                approximate=True
            )
            logger.info(
                f"EXEC_FEEDBACK_PROFIT_EXIT account={stop.account_id} symbol={stop.symbol} side={stop.side} "
                f"qty={qty_exec:.6f} px={execution_price:.6f} pnl_pct={pnl_pct:.4f}"
            )

        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to publish profit exit feedback: {e}")

    def _publish_loss_exit_feedback(self, stop: StealthStop, order: Dict, execution_price: float):
        """Publish STOP_LOSS exits so trainer can apply penalties / risk-off (LOSS_EXIT)."""
        try:
            from config import get_live_config
            cfg = get_live_config()
            if not getattr(cfg, "ENABLE_LOSS_EXIT_FEEDBACK", True):
                return

            if stop.stop_type != 'STOP_LOSS':
                return
            if not self.redis:
                return

            pnl_pct = 0.0
            pnl_usd = 0.0
            try:
                entry_price = float(getattr(stop, "entry_price", 0.0) or 0.0)
                if entry_price > 0:
                    if stop.side == 'LONG':
                        pnl_pct = ((execution_price - entry_price) / entry_price) * 100
                    else:
                        pnl_pct = ((entry_price - execution_price) / entry_price) * 100
            except Exception:
                pnl_pct = 0.0

            qty_exec = 0.0
            try:
                qty_exec = float(order.get("executedQty", 0) or 0) or float(stop.position_size * (stop.close_percentage / 100.0) or 0)
            except Exception:
                qty_exec = 0.0
            try:
                entry_price = float(getattr(stop, "entry_price", 0.0) or 0.0)
                if entry_price > 0 and qty_exec > 0:
                    pnl_usd = (execution_price - entry_price) * qty_exec if stop.side == "LONG" else (entry_price - execution_price) * qty_exec
            except Exception:
                pnl_usd = 0.0

            feedback = {
                'timestamp': time.time(),
                'ts_ms': int(time.time() * 1000),
                'event_type': 'LOSS_EXIT',
                'symbol': stop.symbol,
                'side': stop.side,
                'account_id': stop.account_id,
                'executed_price': execution_price,
                'qty': qty_exec,
                'trigger_price': stop.trigger_price,
                'order_id': order.get('orderId'),
                'stop_type': stop.stop_type,
                'reason': stop.reason,
                'realized_pnl_usd': float(pnl_usd),
                'realized_pnl_pct': float(pnl_pct),
                'pnl_usd': float(pnl_usd),
                'pnl_pct': round(pnl_pct, 4),
                # Legacy: keep `pnl` as USD (not percent)
                'pnl': float(pnl_usd),
            }

            self.redis.xadd(
                'wma:trader:execution_feedback',
                {'data': json.dumps(feedback)},
                maxlen=500,
                approximate=True
            )
            logger.info(
                f"EXEC_FEEDBACK_LOSS_EXIT account={stop.account_id} symbol={stop.symbol} side={stop.side} "
                f"qty={qty_exec:.6f} px={execution_price:.6f} pnl_pct={pnl_pct:.4f}"
            )

        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to publish loss exit feedback: {e}")
    
    def _publish_execution_feedback(self, stop: StealthStop, order: Dict, execution_price: float, 
                                      exec_method: str = "MARKET", used_limit: bool = False):
        """Publish execution to Redis for trade feedback system"""
        try:
            executed_qty = stop.position_size * (stop.close_percentage / 100.0)

            # Compute realized PnL so system_telegram_monitor can display it correctly
            entry_px = float(getattr(stop, "entry_price", 0.0) or 0.0)
            if entry_px <= 0:
                try:
                    entry_px, _, _src = self._resolve_leg_entry_pnl(
                        stop.symbol, stop.side,
                        str(getattr(self, "account_id", None) or stop.account_id or "primary"),
                    )
                    if entry_px > 0:
                        logger.info(
                            "EXEC_FEEDBACK_ENTRY_RESOLVED | sym=%s side=%s entry=%.6f src=%s",
                            stop.symbol, stop.side, entry_px, _src,
                        )
                except Exception:
                    entry_px = 0.0
            realized_pnl_usd = None
            realized_pnl_pct = None
            try:
                if entry_px > 0 and executed_qty > 0 and execution_price > 0:
                    if str(stop.side or "").upper() == "LONG":
                        realized_pnl_usd = (execution_price - entry_px) * executed_qty
                    else:  # SHORT
                        realized_pnl_usd = (entry_px - execution_price) * executed_qty
                    realized_pnl_pct = (realized_pnl_usd / (entry_px * executed_qty)) * 100.0
            except Exception:
                realized_pnl_usd = None
                realized_pnl_pct = None

            feedback = {
                'timestamp': time.time(),
                'ts_ms': int(time.time() * 1000),
                'account_id': str(getattr(self, "account_id", None) or stop.account_id or "primary"),
                'symbol': stop.symbol,
                'action': f"STEALTH_{stop.stop_type}_{stop.side}",
                'action_name': f"STEALTH_{stop.stop_type}_{stop.side}",
                'success': True,
                'executed': True,
                'executed_price': execution_price,
                'executed_qty': executed_qty,
                'entry_price': entry_px if entry_px > 0 else None,
                'realized_pnl_usd': realized_pnl_usd,
                'realized_pnl_pct': realized_pnl_pct,
                'latency_ms': 0,
                'exchange_order_id': order.get('orderId'),
                'order_id': order.get('orderId'),
                'liquidity': "MAKER" if used_limit else "TAKER",
                'error': None,
                'stop_trigger_price': stop.trigger_price,
                'stop_type': stop.stop_type,
                'execution_method': exec_method,
                'used_maker_fee': used_limit,
                'leverage': int(getattr(stop, "leverage", 0) or 0) or None,
                'fee_savings_tracking': {
                    'total_limit_fills': self.limit_fills,
                    'total_market_fallbacks': self.market_fallbacks,
                    'total_fee_savings_usd': round(self.total_fee_savings_usd, 4)
                }
            }
            
            self.redis.xadd(
                'executed_signals',
                {'data': json.dumps(feedback)},
                maxlen=1000,
                approximate=True
            )
            
        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to publish execution feedback: {e}")
    
    def _save_to_redis(self):
        """Persist pending stops to Redis for recovery after restart"""
        try:
            redis_key = f"stealth_stops:{self.account_id}"
            
            # Serialize all pending stops
            all_stops = []
            for symbol, stops in self.pending_stops.items():
                for stop in stops:
                    all_stops.append(stop.to_dict())
            
            if all_stops:
                self.redis.set(redis_key, json.dumps(all_stops), ex=86400)  # 24h expiry
            else:
                self.redis.delete(redis_key)
                
        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to save to Redis: {e}")
    
    def _load_from_redis(self):
        """Load pending stops from Redis on startup"""
        try:
            redis_key = f"stealth_stops:{self.account_id}"
            data = self.redis.get(redis_key)
            
            if data:
                all_stops = json.loads(data)
                self.pending_stops.clear()
                
                for stop_data in all_stops:
                    stop = StealthStop.from_dict(stop_data)
                    # Repair missing/invalid side on load.
                    try:
                        stop.side = str(stop.side or "").upper().strip()
                    except Exception:
                        stop.side = ""
                    if stop.side not in ("LONG", "SHORT"):
                        inferred = self._infer_side_from_portfolio(stop.symbol, stop.account_id)
                        if inferred in ("LONG", "SHORT"):
                            stop.side = inferred
                        else:
                            continue
                    self.pending_stops[stop.symbol].append(stop)
                
                logger.info(f"[STEALTH-STOPS] 📂 Loaded {len(all_stops)} pending stops from Redis")
        
        except Exception as e:
            logger.warning(f"[STEALTH-STOPS] Failed to load from Redis: {e}")
    
    def get_stats(self) -> Dict:
        """Get statistics about stealth stops"""
        with self._lock:
            total_pending = sum(len(stops) for stops in self.pending_stops.values())
            total_executions = self.limit_fills + self.market_fallbacks
            limit_fill_rate = (self.limit_fills / total_executions * 100) if total_executions > 0 else 0
            
            return {
                'pending_stops': total_pending,
                'symbols_monitored': len(self.pending_stops),
                'stops_triggered': self.stops_triggered,
                'stops_executed': self.stops_executed,
                'stops_failed': self.stops_failed,
                'success_rate': (self.stops_executed / self.stops_triggered * 100) if self.stops_triggered > 0 else 0,
                # Hybrid limit execution stats
                'limit_fills': self.limit_fills,
                'market_fallbacks': self.market_fallbacks,
                'limit_fill_rate_pct': round(limit_fill_rate, 1),
                'total_fee_savings_usd': round(self.total_fee_savings_usd, 4)
            }


# Global instances (initialized by traders)
_stealth_monitors: Dict[str, StealthStopMonitor] = {}


def get_stealth_monitor(account_id: str = "primary") -> Optional[StealthStopMonitor]:
    """Get the stealth stop monitor for an account"""
    return _stealth_monitors.get(account_id)


# Backwards-compatible alias (older code calls this name).
# IMPORTANT: This returns the per-account StealthStopMonitor.
def get_stealth_stop_manager(account_id: str = "primary") -> Optional[StealthStopMonitor]:
    return get_stealth_monitor(account_id=account_id)


def initialize_stealth_monitor(
    redis_client,
    binance_client,
    account_id: str = "primary",
    telegram_notifier: Optional[Any] = None,
) -> StealthStopMonitor:
    """Initialize stealth stop monitor for an account"""
    global _stealth_monitors
    
    if account_id in _stealth_monitors:
        logger.warning(f"[STEALTH-STOPS] Monitor for {account_id} already exists")
        # Allow late-binding Telegram notifier (e.g., when trader restarts)
        try:
            if telegram_notifier is not None:
                _stealth_monitors[account_id].telegram = telegram_notifier
        except Exception:
            pass
        return _stealth_monitors[account_id]
    
    monitor = StealthStopMonitor(redis_client, binance_client, account_id, telegram_notifier=telegram_notifier)
    monitor.start()
    
    _stealth_monitors[account_id] = monitor
    logger.info(f"[STEALTH-STOPS] ✅ Initialized monitor for {account_id}")
    
    return monitor




