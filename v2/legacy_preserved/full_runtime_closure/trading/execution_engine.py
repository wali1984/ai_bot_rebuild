"""
Execution Engine — Smart Order Routing, TWAP, Slippage Tracking

Provides execution intelligence for the trading pipeline:
  1. Maker/Taker decision: based on spread, urgency, and order size
  2. TWAP slicing: split large orders into time-weighted slices
  3. Slippage tracking: record and analyse execution quality
  4. Urgency decay: time-sensitive signals degrade gracefully

This module enriches signal payloads with execution metadata before
they reach the trader. The trader uses these hints for order placement.

Integration:
  - Called in _emit_proposal or signal enrichment phase
  - Adds exec_strategy, exec_slices, exec_urgency to signal payload
  - Receives feedback from trader execution events
"""

import logging
import time
import threading
import json
import numpy as np
from collections import deque
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class SlippageTracker:
    """Tracks execution slippage for analysis and feedback."""
    
    def __init__(self, window_size: int = 500):
        self.window_size = window_size
        self._records: deque = deque(maxlen=window_size)
        self._by_symbol: Dict[str, deque] = {}
        self._lock = threading.Lock()
    
    def record(
        self,
        symbol: str,
        side: str,
        expected_price: float,
        fill_price: float,
        notional_usd: float,
        latency_ms: float = 0.0,
        order_type: str = "MARKET",
    ) -> Dict[str, float]:
        """Record an execution and compute slippage.
        
        Returns slippage metrics dict.
        """
        if expected_price <= 0:
            return {"slippage_bps": 0.0}
        
        # Slippage: positive = adverse, negative = favorable
        if side.upper() in ("BUY", "LONG"):
            slippage_bps = (fill_price - expected_price) / expected_price * 10_000
        else:
            slippage_bps = (expected_price - fill_price) / expected_price * 10_000
        
        record = {
            "symbol": symbol,
            "side": side,
            "expected_price": expected_price,
            "fill_price": fill_price,
            "notional_usd": notional_usd,
            "slippage_bps": slippage_bps,
            "latency_ms": latency_ms,
            "order_type": order_type,
            "ts": time.time(),
        }
        
        with self._lock:
            self._records.append(record)
            if symbol not in self._by_symbol:
                self._by_symbol[symbol] = deque(maxlen=100)
            self._by_symbol[symbol].append(record)
        
        return {"slippage_bps": slippage_bps, "latency_ms": latency_ms}
    
    def get_stats(self, symbol: Optional[str] = None) -> Dict[str, float]:
        """Get slippage statistics, optionally filtered by symbol."""
        with self._lock:
            if symbol and symbol in self._by_symbol:
                records = list(self._by_symbol[symbol])
            else:
                records = list(self._records)
        
        if not records:
            return {
                "mean_slippage_bps": 0.0,
                "p95_slippage_bps": 0.0,
                "mean_latency_ms": 0.0,
                "sample_count": 0,
            }
        
        slippages = [r["slippage_bps"] for r in records]
        latencies = [r["latency_ms"] for r in records]
        
        return {
            "mean_slippage_bps": float(np.mean(slippages)),
            "p95_slippage_bps": float(np.percentile(slippages, 95)),
            "max_slippage_bps": float(np.max(slippages)),
            "mean_latency_ms": float(np.mean(latencies)),
            "sample_count": len(records),
        }


class ExecutionEngine:
    """Smart execution engine for order routing and quality optimization.
    
    Decides HOW to execute a trade based on:
      - Current spread and depth
      - Order size relative to available liquidity
      - Signal urgency and time sensitivity
      - Historical slippage for the symbol
    """
    
    def __init__(
        self,
        maker_spread_bps: float = 3.0,
        twap_threshold_usd: float = 500.0,
        twap_slices: int = 3,
        twap_interval_sec: float = 10.0,
        slippage_warn_bps: float = 5.0,
        urgency_decay_sec: float = 30.0,
        redis_client=None,
    ):
        self.maker_spread_bps = maker_spread_bps
        self.twap_threshold_usd = twap_threshold_usd
        self.twap_slices = twap_slices
        self.twap_interval_sec = twap_interval_sec
        self.slippage_warn_bps = slippage_warn_bps
        self.urgency_decay_sec = urgency_decay_sec
        self.redis = redis_client
        
        # Slippage tracker
        self.slippage_tracker = SlippageTracker()
        
        # Execution decisions log
        self._decision_log: deque = deque(maxlen=200)
        self._last_log_ts = 0.0
        
        logger.info(
            f"[EXEC_ENGINE] Initialized: maker_spread={maker_spread_bps}bps, "
            f"twap_threshold=${twap_threshold_usd}, slices={twap_slices}"
        )
    
    def enrich_signal(
        self,
        signal: dict,
        orderbook_data: Optional[dict] = None,
    ) -> dict:
        """Enrich a trading signal with execution strategy metadata.
        
        Args:
            signal: Trading signal payload dict
            orderbook_data: Optional dict with spread_bps, bid_depth_usd, ask_depth_usd
        
        Returns:
            Signal dict enriched with execution fields
        """
        try:
            symbol = signal.get("symbol", "")
            action = str(signal.get("action", "HOLD")).upper()
            notional = float(signal.get("notional_usd", 0) or 0)
            confidence = float(signal.get("confidence", 0) or 0)
            signal_ts = float(signal.get("ts_ms", time.time() * 1000) or time.time() * 1000) / 1000.0
            
            # Skip enrichment for non-actionable signals
            if action in ("HOLD", "NONE", "WAIT", "HEARTBEAT"):
                signal["exec_strategy"] = "NONE"
                return signal
            
            # Get orderbook context
            spread_bps = 0.0
            depth_usd = 0.0
            if orderbook_data:
                spread_bps = float(orderbook_data.get("spread_bps", 0) or 0)
                depth_usd = float(
                    orderbook_data.get("bid_depth_usd", 0) or 0
                ) + float(
                    orderbook_data.get("ask_depth_usd", 0) or 0
                )
            
            # Fetch from Redis if no orderbook provided
            if spread_bps == 0 and self.redis and symbol:
                try:
                    ob_key = f"orderbook:{symbol}"
                    ob_data = self.redis.hgetall(ob_key)
                    if ob_data:
                        spread_bps = float(ob_data.get("spread_bps", ob_data.get(b"spread_bps", 0)) or 0)
                        depth_usd = float(ob_data.get("total_depth_usd", ob_data.get(b"total_depth_usd", 0)) or 0)
                except Exception:
                    pass
            
            # 1. Urgency calculation
            age_sec = max(0, time.time() - signal_ts)
            urgency = max(0.0, 1.0 - age_sec / max(0.1, self.urgency_decay_sec))
            urgency *= confidence  # Scale urgency by confidence
            
            # 2. Maker/Taker decision
            exec_strategy = self._decide_maker_taker(
                spread_bps=spread_bps,
                notional_usd=notional,
                depth_usd=depth_usd,
                urgency=urgency,
                action=action,
            )
            
            # 3. TWAP decision
            twap_slices = 1  # Default: single order
            if notional > self.twap_threshold_usd and exec_strategy != "MAKER":
                twap_slices = min(self.twap_slices, max(2, int(notional / self.twap_threshold_usd) + 1))
            
            # 4. Historical slippage context
            hist_slippage = self.slippage_tracker.get_stats(symbol)
            
            # Enrich signal
            signal["exec_strategy"] = exec_strategy
            signal["exec_urgency"] = round(urgency, 3)
            signal["exec_twap_slices"] = twap_slices
            signal["exec_twap_interval_sec"] = self.twap_interval_sec if twap_slices > 1 else 0
            signal["exec_spread_bps"] = round(spread_bps, 2)
            signal["exec_depth_usd"] = round(depth_usd, 0)
            signal["exec_hist_slippage_bps"] = round(hist_slippage.get("mean_slippage_bps", 0), 2)
            signal["exec_hist_p95_slippage_bps"] = round(hist_slippage.get("p95_slippage_bps", 0), 2)
            
            # Size adjustment: reduce size if expected slippage is high
            expected_slip = hist_slippage.get("p95_slippage_bps", 0)
            if expected_slip > self.slippage_warn_bps and notional > 0:
                # Reduce notional proportionally
                reduction = min(0.3, (expected_slip - self.slippage_warn_bps) / 20.0)
                signal["exec_size_reduction_pct"] = round(reduction * 100, 1)
            
            # Log decision
            self._log_decision(symbol, action, exec_strategy, notional, spread_bps, urgency, twap_slices)
            
            return signal
            
        except Exception as e:
            logger.warning(f"[EXEC_ENGINE] Enrichment failed: {e}")
            signal["exec_strategy"] = "TAKER"  # Safe default
            return signal
    
    def _decide_maker_taker(
        self,
        spread_bps: float,
        notional_usd: float,
        depth_usd: float,
        urgency: float,
        action: str,
    ) -> str:
        """Decide between MAKER and TAKER order execution.
        
        MAKER: Post limit order (lower fees, risk of non-fill)
        TAKER: Market order (guaranteed fill, higher fees)
        """
        # PROTECTIVE actions always use TAKER (urgency matters)
        if any(tok in action for tok in ["CLOSE", "STOP", "EXIT", "REDUCE"]):
            return "TAKER"
        
        # If spread is wide enough and urgency is low, use MAKER
        if spread_bps >= self.maker_spread_bps and urgency < 0.7:
            return "MAKER"
        
        # If notional is large relative to depth, use MAKER to avoid impact
        if depth_usd > 0 and notional_usd > depth_usd * 0.1:
            return "MAKER"
        
        # Default: TAKER for speed
        return "TAKER"
    
    def _log_decision(
        self,
        symbol: str,
        action: str,
        strategy: str,
        notional: float,
        spread_bps: float,
        urgency: float,
        twap_slices: int,
    ) -> None:
        """Log execution decision for diagnostics."""
        self._decision_log.append({
            "symbol": symbol,
            "action": action,
            "strategy": strategy,
            "notional": notional,
            "spread_bps": spread_bps,
            "urgency": urgency,
            "twap_slices": twap_slices,
            "ts": time.time(),
        })
        
        # Throttled summary log
        now = time.time()
        if now - self._last_log_ts > 120:
            self._last_log_ts = now
            recent = list(self._decision_log)[-20:]
            maker_pct = sum(1 for d in recent if d["strategy"] == "MAKER") / max(1, len(recent)) * 100
            twap_pct = sum(1 for d in recent if d["twap_slices"] > 1) / max(1, len(recent)) * 100
            avg_slip = self.slippage_tracker.get_stats()
            logger.info(
                f"[EXEC_ENGINE] Stats: maker={maker_pct:.0f}% twap={twap_pct:.0f}% "
                f"avg_slip={avg_slip.get('mean_slippage_bps', 0):.1f}bps "
                f"p95_slip={avg_slip.get('p95_slippage_bps', 0):.1f}bps"
            )
    
    def process_execution_feedback(self, event: dict) -> None:
        """Process execution feedback from trader.
        
        Args:
            event: dict with symbol, side, expected_price, fill_price, notional_usd, etc.
        """
        try:
            result = self.slippage_tracker.record(
                symbol=event.get("symbol", ""),
                side=event.get("side", ""),
                expected_price=float(event.get("expected_price", 0) or 0),
                fill_price=float(event.get("fill_price", 0) or 0),
                notional_usd=float(event.get("notional_usd", 0) or 0),
                latency_ms=float(event.get("latency_ms", 0) or 0),
                order_type=event.get("order_type", "MARKET"),
            )
            
            slip = result.get("slippage_bps", 0)
            if abs(slip) > self.slippage_warn_bps:
                logger.warning(
                    f"[EXEC_ENGINE] ⚠️ High slippage: {event.get('symbol')} "
                    f"{slip:.1f}bps (warn={self.slippage_warn_bps}bps)"
                )
        except Exception as e:
            logger.debug(f"[EXEC_ENGINE] Feedback processing error: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get execution engine summary for telemetry."""
        stats = self.slippage_tracker.get_stats()
        recent = list(self._decision_log)[-50:]
        
        return {
            "total_executions": stats.get("sample_count", 0),
            "mean_slippage_bps": stats.get("mean_slippage_bps", 0),
            "p95_slippage_bps": stats.get("p95_slippage_bps", 0),
            "maker_pct": sum(1 for d in recent if d.get("strategy") == "MAKER") / max(1, len(recent)) * 100,
            "twap_pct": sum(1 for d in recent if d.get("twap_slices", 1) > 1) / max(1, len(recent)) * 100,
        }
