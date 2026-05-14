#!/usr/bin/env python3
"""
Trade Lifecycle Trace Script
Links signal->execution->fills->PnL->reward update for the last N trades
and categorizes root causes for failures/skips.

Author: WMA AI Trading System
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis


# =============================================================================
# ROOT CAUSE CATEGORIES
# =============================================================================

ROOT_CAUSE_CATEGORIES = {
    # Signal Generation Issues
    "STALE_SIGNAL": "Signal age exceeded max latency threshold",
    "MISSING_SIZING": "Signal missing margin_usd/notional_usd/position_size_pct",
    "LOW_CONFIDENCE": "Confidence below MIN_CONF_ENTRY or MIN_CONF_EXIT",
    "CONTRACT_BLOCK": "Signal failed contract validation (_build_signal_payload_margin_v1)",
    "TRAINER_FLIP_COOLDOWN": "Flip blocked by per-symbol cooldown in trainer",
    "TRAINER_ACTION_DEDUPE": "Action deduplicated (same symbol+action within window)",
    "VALIDATOR_BLOCK": "SignalValidator blocked based on historical win rate",
    
    # Trader Execution Issues
    "FLIP_PREFLIGHT_BLOCK": "Flip preflight checks failed (caution mode, sizing, staleness)",
    "CAUTION_MODE": "Circuit breaker in caution mode, blocking new opens",
    "RATE_LIMIT_SYMBOL": "Per-symbol order rate limit exceeded",
    "TRADER_FLIP_COOLDOWN": "Flip blocked by trader-side cooldown",
    "MISSING_MARGIN_OPEN_LEG": "Flip open leg missing margin sizing",
    "UNKNOWN_ACTION": "Unknown action mapping in trader",
    "REDUCE_ONLY_REJECTED": "Close order rejected (already flat)",
    "API_ERROR": "Binance API error during execution",
    "HOURLY_CAP_EXCEEDED": "Per-symbol hourly trade cap exceeded (P1-1 audit fix)",
    
    # Portfolio Policy Issues (Addendum A)
    "PORTFOLIO_SLOT_BLOCK": "Position slot limit exceeded (5 long/5 short)",
    "PORTFOLIO_BUDGET_BLOCK": "Side margin budget exceeded (25%)",
    "PORTFOLIO_RESERVE_BLOCK": "Requires ultra reserve but conf < 0.98",
    "PORTFOLIO_STALE_EQUITY_BLOCK": "Equity data stale or missing (fail-closed)",
    "PORTFOLIO_TOTAL_MARGIN_BLOCK": "Total margin budget exceeded",
    
    # Anti-Churn Issues (Addendum C)
    "ANTI_CHURN_BLOCK": "General anti-churn rate limit",
    "HEDGE_STATE_COOLDOWN_BLOCK": "Hedge state machine minimum interval",
    "SYMBOL_RATE_LIMIT_BLOCK": "Per-symbol action type rate limit",
    "WARM_START_BLOCK": "Warm start window after trader restart",
    "SIGNAL_STALE_BLOCK": "Signal too old to execute",
    
    # Position Management Issues
    "NO_POSITION": "Close/reduce attempted on non-existent position",
    "WRONG_SIDE": "Close requested for side that doesn't exist",
    "PARTIAL_FILL": "Order only partially filled",
    
    # Risk Gate Issues
    "RISK_GATE_MARGIN": "Margin utilization exceeded 80%",
    "RISK_GATE_DRAWDOWN": "Drawdown exceeded 15% threshold",
    "RISK_GATE_CONCENTRATION": "Portfolio concentration limit exceeded",
    "RISK_GATE_LIQUIDITY": "Liquidity/spread gate blocked order",
    
    # Feedback Issues
    "REWARD_NOT_ATTRIBUTED": "Trade PnL not fed back to reward calculation",
    "FEEDBACK_LAG": "Significant delay between fill and reward update",
    
    # Success Cases (for completeness)
    "SUCCESS_EXECUTED": "Signal executed successfully",
    "SUCCESS_IDEMPOTENT": "Idempotent close (already flat)",
}

# Close Reason Codes (P0-3 audit fix)
CLOSE_REASON_CODES = {
    "MODEL_CLOSE": "Normal model-initiated close signal",
    "STOP_LOSS": "Stop loss triggered (stealth or exchange)",
    "TRAILING_STOP": "Trailing stop triggered",
    "TAKE_PROFIT": "TP target hit",
    "TAKE_PROFIT_TIERED": "Tiered profit taking (confidence-based partial)",
    "LIQUIDATION_HEDGE": "Emergency hedge to prevent liquidation",
    "CIRCUIT_BREAKER": "Circuit breaker emergency close",
    "REBALANCING": "Portfolio rebalancing close",
    "FLIP_CLOSE": "Close leg of flip operation",
    "MANUAL_CLOSE": "Manual/external close",
    "STEALTH_STOP_LOSS": "Stealth SL triggered",
    "STEALTH_TAKE_PROFIT": "Stealth TP triggered",
}


@dataclass
class TradeLifecycle:
    """Represents a single signal->execution->reward lifecycle."""
    signal_id: str = ""
    symbol: str = ""
    action: str = ""
    timeframe: str = ""
    confidence: float = 0.0
    
    # Signal phase
    signal_ts_ms: int = 0
    signal_source: str = ""
    margin_usd: float = 0.0
    notional_usd: float = 0.0
    leverage: int = 0
    
    # Execution phase
    execution_ts_ms: int = 0
    executed: bool = False
    skip_reason: Optional[str] = None
    order_id: Optional[str] = None
    fill_price: float = 0.0
    fill_qty: float = 0.0
    
    # Close classification (P0-3 audit fix)
    close_reason_code: Optional[str] = None
    is_close_action: bool = False
    
    # Contract fields (Addendum D)
    intent: str = ""
    roe_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    hot_monitor: bool = False
    hedge_reason_code: Optional[str] = None
    
    # Portfolio policy snapshot
    portfolio_slots_used: int = 0
    portfolio_margin_pct: float = 0.0
    portfolio_ultra_mode: bool = False
    
    # PnL phase
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Reward phase
    reward_ts_ms: int = 0
    reward_value: float = 0.0
    reward_attributed: bool = False
    
    # Categorization
    root_causes: List[str] = field(default_factory=list)
    latency_signal_to_exec_ms: int = 0
    latency_exec_to_reward_ms: int = 0
    
    def categorize(self):
        """Determine root cause categories for this lifecycle."""
        # Detect close actions
        action_upper = self.action.upper() if self.action else ""
        self.is_close_action = any(x in action_upper for x in ['CLOSE', 'STOP_LOSS', 'TAKE_PROFIT', 'FLIP'])
        is_hedge_action = 'HEDGE' in action_upper
        
        if self.executed:
            if self.order_id:
                self.root_causes.append("SUCCESS_EXECUTED")
            else:
                self.root_causes.append("SUCCESS_IDEMPOTENT")
            
            # Track close reason code distribution for closes
            if self.is_close_action and self.close_reason_code:
                self.root_causes.append(f"CLOSE:{self.close_reason_code}")
            
            # Track hedge reason code for hedge actions
            if is_hedge_action and self.hedge_reason_code:
                self.root_causes.append(f"HEDGE:{self.hedge_reason_code}")
            
            # Track intent distribution
            if self.intent:
                self.root_causes.append(f"INTENT:{self.intent}")
            
            # Track hot monitor activity
            if self.hot_monitor:
                self.root_causes.append("HOT_MONITOR_ACTIVE")
        else:
            if self.skip_reason:
                # Map skip_reason to category
                reason_upper = self.skip_reason.upper()
                for cat_key in ROOT_CAUSE_CATEGORIES.keys():
                    if cat_key in reason_upper:
                        self.root_causes.append(cat_key)
                        break
                else:
                    # Unknown category - add raw reason
                    self.root_causes.append(f"UNKNOWN:{self.skip_reason}")
            else:
                self.root_causes.append("UNKNOWN:no_skip_reason")
        
        # Check for feedback issues
        if self.executed and not self.reward_attributed:
            self.root_causes.append("REWARD_NOT_ATTRIBUTED")
        if self.latency_exec_to_reward_ms > 60000:  # >1 minute
            self.root_causes.append("FEEDBACK_LAG")
        
        # ROE extremes tracking
        if self.executed and abs(self.roe_pct) >= 20:
            if self.roe_pct >= 20:
                self.root_causes.append("ROE_HIGH_POSITIVE")
            else:
                self.root_causes.append("ROE_HIGH_NEGATIVE")


def get_redis_client() -> redis.Redis:
    """Get Redis client."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    return redis.Redis(host=host, port=port, db=db, decode_responses=True)


def fetch_signals(rc: redis.Redis, count: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent signals from the configured trading stream(s) (per-account aware)."""
    signals = []
    try:
        # Prefer per-account streams when enabled
        try:
            import config as cfg
            enable_per_account = bool(getattr(cfg, "ENABLE_PER_ACCOUNT_STREAMS", False))
            stream_per_account = dict(getattr(cfg, "SIGNAL_STREAM_PER_ACCOUNT", {}) or {})
            signal_output_stream = str(getattr(cfg, "SIGNAL_OUTPUT_STREAM", "signals:trading"))
        except Exception:
            enable_per_account = False
            stream_per_account = {}
            signal_output_stream = "signals:trading"

        streams: List[Tuple[str, str]] = []  # (stream, account_id_hint)
        if enable_per_account and stream_per_account:
            streams = [(s, a) for a, s in stream_per_account.items()]
        else:
            streams = [(signal_output_stream, "global")]

        for stream_name, acct_hint in streams:
            entries = rc.xrevrange(stream_name, count=count)
            for stream_id, data in entries:
                try:
                    payload = json.loads(data.get("data", "{}"))
                except json.JSONDecodeError:
                    continue
                payload["_stream_id"] = stream_id
                payload["_stream"] = stream_name
                if not payload.get("account_id") and acct_hint != "global":
                    payload["account_id"] = acct_hint
                signals.append(payload)

        # Keep newest N total
        def _ts_ms(p: Dict[str, Any]) -> int:
            ts = p.get("ts_ms")
            try:
                if ts is not None:
                    return int(float(ts))
            except Exception:
                pass
            sid = str(p.get("_stream_id") or "0-0")
            try:
                return int(sid.split("-", 1)[0])
            except Exception:
                return 0

        signals.sort(key=_ts_ms, reverse=True)
        signals = signals[:count]
    except Exception as e:
        print(f"Error fetching signals: {e}")
    return signals


def fetch_skips(rc: redis.Redis, count: int = 200) -> List[Dict[str, Any]]:
    """Fetch recent skip events from signals:execution:skips stream."""
    skips = []
    try:
        entries = rc.xrevrange("signals:execution:skips", count=count)
        for stream_id, data in entries:
            try:
                payload = json.loads(data.get("data", "{}"))
                payload["_stream_id"] = stream_id
                skips.append(payload)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"Error fetching skips: {e}")
    return skips


def fetch_executions(rc: redis.Redis, count: int = 200) -> List[Dict[str, Any]]:
    """Fetch recent execution feedback from wma:trader:execution_feedback stream."""
    execs = []
    try:
        entries = rc.xrevrange("wma:trader:execution_feedback", count=count)
        for stream_id, data in entries:
            try:
                payload = json.loads(data.get("data", "{}"))
                payload["_stream_id"] = stream_id
                execs.append(payload)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"Error fetching executions: {e}")
    return execs


def fetch_fills(rc: redis.Redis, count: int = 200) -> List[Dict[str, Any]]:
    """Fetch recent fills from wma:trader:fills stream."""
    fills = []
    try:
        entries = rc.xrevrange("wma:trader:fills", count=count)
        for stream_id, data in entries:
            try:
                payload = json.loads(data.get("data", "{}"))
                payload["_stream_id"] = stream_id
                fills.append(payload)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"Error fetching fills: {e}")
    return fills


def fetch_reward_updates(rc: redis.Redis, count: int = 200) -> List[Dict[str, Any]]:
    """Fetch recent reward updates from signals:feedback:outcomes stream."""
    rewards = []
    try:
        entries = rc.xrevrange("signals:feedback:outcomes", count=count)
        for stream_id, data in entries:
            try:
                payload = json.loads(data.get("data", "{}"))
                payload["_stream_id"] = stream_id
                rewards.append(payload)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"Error fetching reward updates: {e}")
    return rewards


def correlate_lifecycle(
    signals: List[Dict],
    skips: List[Dict],
    executions: List[Dict],
    fills: List[Dict],
    rewards: List[Dict],
) -> List[TradeLifecycle]:
    """Correlate signals with their execution outcomes."""
    
    lifecycles = []
    
    # Index skips, executions, fills, rewards by signal characteristics
    skip_by_key = defaultdict(list)
    for skip in skips:
        key = f"{skip.get('symbol')}:{skip.get('action_name')}:{skip.get('ts_ms', 0) // 60000}"
        skip_by_key[key].append(skip)
    
    exec_by_key = defaultdict(list)
    for ex in executions:
        key = f"{ex.get('symbol')}:{ex.get('action')}:{int(ex.get('timestamp', 0) * 1000) // 60000}"
        exec_by_key[key].append(ex)
    
    fill_by_symbol = defaultdict(list)
    for fill in fills:
        fill_by_symbol[fill.get('symbol')].append(fill)
    
    reward_by_symbol = defaultdict(list)
    for reward in rewards:
        reward_by_symbol[reward.get('symbol')].append(reward)
    
    for signal in signals:
        lc = TradeLifecycle()
        
        # Signal phase
        lc.signal_id = signal.get('_stream_id', '')
        lc.symbol = signal.get('symbol', '')
        lc.action = signal.get('action_name') or signal.get('action') or signal.get('final_action', '')
        lc.timeframe = signal.get('timeframe', '')
        lc.confidence = float(signal.get('confidence', 0))
        lc.signal_ts_ms = int(signal.get('ts_ms') or signal.get('created_ts_ms', 0))
        lc.signal_source = signal.get('decision_source') or signal.get('source', '')
        lc.margin_usd = float(signal.get('margin_usd', 0))
        lc.notional_usd = float(signal.get('notional_usd', 0))
        lc.leverage = int(signal.get('leverage') or signal.get('recommended_leverage', 0))
        
        # Contract fields (Addendum D)
        lc.intent = signal.get('intent', '')
        lc.roe_pct = float(signal.get('roe_pct', 0))
        lc.mfe_pct = float(signal.get('mfe_pct', 0))
        lc.mae_pct = float(signal.get('mae_pct', 0))
        lc.hot_monitor = bool(signal.get('hot_monitor', 0))
        lc.hedge_reason_code = signal.get('hedge_reason_code')
        
        # Portfolio policy snapshot (Addendum A)
        policy_snapshot = signal.get('policy_snapshot', {})
        if policy_snapshot:
            lc.portfolio_slots_used = int(policy_snapshot.get('total_positions', 0))
            lc.portfolio_margin_pct = float(policy_snapshot.get('total_margin_pct', 0))
            lc.portfolio_ultra_mode = bool(policy_snapshot.get('ultra_mode', False))
        
        # Look for matching skip
        skip_key = f"{lc.symbol}:{lc.action}:{lc.signal_ts_ms // 60000}"
        matching_skips = skip_by_key.get(skip_key, [])
        if matching_skips:
            skip = matching_skips[0]
            lc.skip_reason = skip.get('reason_code') or skip.get('reason_detail', '')
            lc.executed = False
        
        # Look for matching execution
        exec_key = f"{lc.symbol}:{lc.action}:{lc.signal_ts_ms // 60000}"
        matching_execs = exec_by_key.get(exec_key, [])
        if matching_execs:
            ex = matching_execs[0]
            lc.execution_ts_ms = int(ex.get('timestamp', 0) * 1000)
            lc.executed = ex.get('ok', False)
            if not lc.executed:
                lc.skip_reason = ex.get('error', '')
            else:
                order = ex.get('order', {})
                lc.order_id = str(order.get('orderId', ''))
                lc.fill_price = float(order.get('avgPrice', 0))
                lc.fill_qty = float(order.get('executedQty', 0))
                # P0-3: Extract close_reason_code from execution
                lc.close_reason_code = ex.get('close_reason_code') or order.get('close_reason_code')
                # Addendum D: Contract fields from execution
                if ex.get('intent'):
                    lc.intent = ex.get('intent')
                if ex.get('roe_pct'):
                    lc.roe_pct = float(ex.get('roe_pct', 0))
                if ex.get('mfe_pct'):
                    lc.mfe_pct = float(ex.get('mfe_pct', 0))
                if ex.get('mae_pct'):
                    lc.mae_pct = float(ex.get('mae_pct', 0))
                if ex.get('hot_monitor'):
                    lc.hot_monitor = bool(ex.get('hot_monitor'))
                if ex.get('hedge_reason_code'):
                    lc.hedge_reason_code = ex.get('hedge_reason_code')
            lc.latency_signal_to_exec_ms = lc.execution_ts_ms - lc.signal_ts_ms if lc.execution_ts_ms > 0 else 0
        
        # Look for matching fill
        symbol_fills = fill_by_symbol.get(lc.symbol, [])
        for fill in symbol_fills:
            fill_ts = int(fill.get('timestamp', 0) * 1000)
            if abs(fill_ts - lc.signal_ts_ms) < 120000:  # Within 2 minutes
                lc.realized_pnl = float(fill.get('pnl', 0))
                lc.fill_price = float(fill.get('price', 0)) or lc.fill_price
                lc.fill_qty = float(fill.get('quantity', 0)) or lc.fill_qty
                break
        
        # Look for matching reward update
        symbol_rewards = reward_by_symbol.get(lc.symbol, [])
        for reward in symbol_rewards:
            reward_ts = int(reward.get('ts_ms', 0))
            if abs(reward_ts - lc.signal_ts_ms) < 300000:  # Within 5 minutes
                lc.reward_ts_ms = reward_ts
                lc.reward_value = float(reward.get('reward') or reward.get('adjusted_reward', 0))
                lc.reward_attributed = True
                lc.latency_exec_to_reward_ms = reward_ts - lc.execution_ts_ms if lc.execution_ts_ms > 0 else 0
                break
        
        # Categorize
        lc.categorize()
        lifecycles.append(lc)
    
    return lifecycles


def print_summary(lifecycles: List[TradeLifecycle]):
    """Print summary statistics."""
    total = len(lifecycles)
    executed = sum(1 for lc in lifecycles if lc.executed)
    skipped = total - executed
    
    # Count root causes
    cause_counts = defaultdict(int)
    for lc in lifecycles:
        for cause in lc.root_causes:
            cause_counts[cause] += 1
    
    print("\n" + "=" * 80)
    print("TRADE LIFECYCLE TRACE SUMMARY")
    print("=" * 80)
    print(f"\nTotal Signals Analyzed: {total}")
    print(f"Executed: {executed} ({executed/total*100:.1f}%)")
    print(f"Skipped: {skipped} ({skipped/total*100:.1f}%)")
    
    # Root cause breakdown
    print("\n" + "-" * 40)
    print("ROOT CAUSE BREAKDOWN")
    print("-" * 40)
    for cause, count in sorted(cause_counts.items(), key=lambda x: -x[1]):
        desc = ROOT_CAUSE_CATEGORIES.get(cause, cause)
        pct = count / total * 100
        print(f"  {cause}: {count} ({pct:.1f}%) - {desc}")
    
    # Latency stats
    exec_latencies = [lc.latency_signal_to_exec_ms for lc in lifecycles if lc.latency_signal_to_exec_ms > 0]
    reward_latencies = [lc.latency_exec_to_reward_ms for lc in lifecycles if lc.latency_exec_to_reward_ms > 0]
    
    print("\n" + "-" * 40)
    print("LATENCY STATISTICS")
    print("-" * 40)
    if exec_latencies:
        avg_exec = sum(exec_latencies) / len(exec_latencies)
        max_exec = max(exec_latencies)
        print(f"  Signal→Execution: avg={avg_exec:.0f}ms, max={max_exec:.0f}ms")
    if reward_latencies:
        avg_reward = sum(reward_latencies) / len(reward_latencies)
        max_reward = max(reward_latencies)
        print(f"  Execution→Reward: avg={avg_reward:.0f}ms, max={max_reward:.0f}ms")
    
    # Close Reason Code Distribution (P0-3 audit)
    close_reason_counts = defaultdict(int)
    for lc in lifecycles:
        if lc.is_close_action and lc.close_reason_code:
            close_reason_counts[lc.close_reason_code] += 1
    
    if close_reason_counts:
        print("\n" + "-" * 40)
        print("CLOSE REASON CODE DISTRIBUTION (P0-3)")
        print("-" * 40)
        for code, count in sorted(close_reason_counts.items(), key=lambda x: -x[1]):
            desc = CLOSE_REASON_CODES.get(code, "Unknown")
            print(f"  {code}: {count} - {desc}")
    
    # PnL stats
    realized_pnls = [lc.realized_pnl for lc in lifecycles if lc.realized_pnl != 0]
    if realized_pnls:
        print("\n" + "-" * 40)
        print("PNL STATISTICS")
        print("-" * 40)
        total_pnl = sum(realized_pnls)
        wins = sum(1 for p in realized_pnls if p > 0)
        losses = sum(1 for p in realized_pnls if p < 0)
        win_rate = wins / len(realized_pnls) * 100 if realized_pnls else 0
        print(f"  Total Realized PnL: ${total_pnl:.2f}")
        print(f"  Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
    
    # Intent Distribution (Addendum D)
    intent_counts = defaultdict(int)
    for lc in lifecycles:
        if lc.intent:
            intent_counts[lc.intent] += 1
    
    if intent_counts:
        print("\n" + "-" * 40)
        print("INTENT DISTRIBUTION (Addendum D)")
        print("-" * 40)
        for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"  {intent}: {count} ({pct:.1f}%)")
    
    # Hedge Activity (Addendum B/D)
    hedge_counts = defaultdict(int)
    for lc in lifecycles:
        if lc.hedge_reason_code:
            hedge_counts[lc.hedge_reason_code] += 1
    
    if hedge_counts:
        print("\n" + "-" * 40)
        print("HEDGE REASON DISTRIBUTION (Addendum B/D)")
        print("-" * 40)
        for reason, count in sorted(hedge_counts.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
    
    # ROE Extremes (Addendum B)
    roe_values = [lc.roe_pct for lc in lifecycles if lc.roe_pct != 0]
    if roe_values:
        print("\n" + "-" * 40)
        print("ROE EXTREMES (Addendum B)")
        print("-" * 40)
        max_roe = max(roe_values)
        min_roe = min(roe_values)
        high_roe = sum(1 for r in roe_values if r >= 20)
        low_roe = sum(1 for r in roe_values if r <= -20)
        print(f"  Max ROE: {max_roe:+.1f}% | Min ROE: {min_roe:+.1f}%")
        print(f"  Trades with ROE >= +20%: {high_roe}")
        print(f"  Trades with ROE <= -20%: {low_roe}")
    
    # Hot Monitor Activity (Addendum B)
    hot_count = sum(1 for lc in lifecycles if lc.hot_monitor)
    if hot_count > 0:
        print("\n" + "-" * 40)
        print("HOT MONITOR ACTIVITY (Addendum B)")
        print("-" * 40)
        print(f"  Trades from hot monitor lane: {hot_count} ({hot_count/total*100:.1f}%)")
    
    # Portfolio Policy Blocks (Addendum A)
    policy_blocks = [cause for lc in lifecycles for cause in lc.root_causes if cause.startswith("PORTFOLIO_")]
    if policy_blocks:
        print("\n" + "-" * 40)
        print("PORTFOLIO POLICY BLOCKS (Addendum A)")
        print("-" * 40)
        block_counts = defaultdict(int)
        for block in policy_blocks:
            block_counts[block] += 1
        for block, count in sorted(block_counts.items(), key=lambda x: -x[1]):
            desc = ROOT_CAUSE_CATEGORIES.get(block, "")
            print(f"  {block}: {count} - {desc}")
    
    # Anti-Churn Blocks (Addendum C)
    churn_blocks = [cause for lc in lifecycles for cause in lc.root_causes 
                    if cause in ["ANTI_CHURN_BLOCK", "HEDGE_STATE_COOLDOWN_BLOCK", "SYMBOL_RATE_LIMIT_BLOCK", "WARM_START_BLOCK", "SIGNAL_STALE_BLOCK"]]
    if churn_blocks:
        print("\n" + "-" * 40)
        print("ANTI-CHURN BLOCKS (Addendum C)")
        print("-" * 40)
        block_counts = defaultdict(int)
        for block in churn_blocks:
            block_counts[block] += 1
        for block, count in sorted(block_counts.items(), key=lambda x: -x[1]):
            desc = ROOT_CAUSE_CATEGORIES.get(block, "")
            print(f"  {block}: {count} - {desc}")


def print_details(lifecycles: List[TradeLifecycle], limit: int = 10):
    """Print detailed lifecycle info for recent trades."""
    print("\n" + "=" * 80)
    print(f"DETAILED TRADE LIFECYCLES (last {limit})")
    print("=" * 80)
    
    for i, lc in enumerate(lifecycles[:limit]):
        ts_str = datetime.fromtimestamp(lc.signal_ts_ms / 1000).strftime('%H:%M:%S') if lc.signal_ts_ms else "?"
        status = "✅" if lc.executed else "❌"
        
        print(f"\n{i+1}. {status} [{ts_str}] {lc.symbol} {lc.action} (TF={lc.timeframe})")
        print(f"   Confidence: {lc.confidence:.2f} | Margin: ${lc.margin_usd:.2f} | Leverage: {lc.leverage}x")
        print(f"   Signal ID: {lc.signal_id[:30]}...")
        
        # Contract fields (Addendum D)
        if lc.intent or lc.roe_pct or lc.hot_monitor:
            intent_str = f"Intent: {lc.intent}" if lc.intent else ""
            roe_str = f"ROE: {lc.roe_pct:+.1f}%" if lc.roe_pct else ""
            mfe_str = f"MFE: {lc.mfe_pct:.1f}%" if lc.mfe_pct else ""
            mae_str = f"MAE: {lc.mae_pct:.1f}%" if lc.mae_pct else ""
            hot_str = "🔥HOT" if lc.hot_monitor else ""
            metrics = " | ".join(filter(None, [intent_str, roe_str, mfe_str, mae_str, hot_str]))
            print(f"   {metrics}")
        
        # Portfolio policy snapshot (Addendum A)
        if lc.portfolio_slots_used > 0:
            ultra_str = " [ULTRA]" if lc.portfolio_ultra_mode else ""
            print(f"   Portfolio: {lc.portfolio_slots_used} slots | {lc.portfolio_margin_pct:.1f}% margin{ultra_str}")
        
        if lc.executed:
            print(f"   Order: {lc.order_id} | Fill: {lc.fill_qty} @ ${lc.fill_price:.4f}")
            if lc.realized_pnl:
                print(f"   PnL: ${lc.realized_pnl:.2f}")
            if lc.close_reason_code:
                print(f"   Close Reason: {lc.close_reason_code}")
            if lc.hedge_reason_code:
                print(f"   Hedge Reason: {lc.hedge_reason_code}")
            print(f"   Latency: signal→exec={lc.latency_signal_to_exec_ms}ms")
        else:
            print(f"   Skip Reason: {lc.skip_reason}")
        
        if lc.reward_attributed:
            print(f"   Reward: {lc.reward_value:.4f} (latency: {lc.latency_exec_to_reward_ms}ms)")
        
        print(f"   Root Causes: {', '.join(lc.root_causes)}")


def print_portfolio_snapshot(rc: redis.Redis):
    """Print current portfolio policy snapshot (Addendum D telemetry)."""
    print("\n" + "=" * 80)
    print("CURRENT PORTFOLIO POLICY SNAPSHOT (Addendum A/D)")
    print("=" * 80)
    
    try:
        # Get portfolio state
        portfolio = rc.hgetall("portfolio:primary:state")
        if portfolio:
            equity = float(portfolio.get('total_balance', portfolio.get(b'total_balance', 0)) or 0)
            margin_used = float(portfolio.get('total_margin_used', portfolio.get(b'total_margin_used', 0)) or 0)
            margin_pct = float(portfolio.get('margin_utilization_pct', portfolio.get(b'margin_utilization_pct', 0)) or 0)
            upnl = float(portfolio.get('unrealized_pnl', portfolio.get(b'unrealized_pnl', 0)) or 0)
            
            print(f"\n  Equity: ${equity:.2f}")
            print(f"  Margin Used: ${margin_used:.2f} ({margin_pct:.1f}%)")
            print(f"  Unrealized PnL: ${upnl:.2f}")
        
        # Get positions
        positions = rc.hgetall("positions:primary:all")
        if positions:
            long_count = 0
            short_count = 0
            long_margin = 0.0
            short_margin = 0.0
            
            print("\n  Open Positions:")
            for key, value in positions.items():
                try:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    pos = json.loads(value.decode() if isinstance(value, bytes) else value)
                    size = pos.get('size', pos.get('positionAmt', 0))
                    if size and float(size) != 0:
                        symbol = pos.get('symbol', key_str)
                        side = pos.get('side', 'UNKNOWN')
                        margin = abs(float(pos.get('initialMargin', pos.get('margin', 0)) or 0))
                        upnl = float(pos.get('unrealizedProfit', pos.get('unrealizedPnl', 0)) or 0)
                        entry = float(pos.get('entryPrice', 0))
                        mark = float(pos.get('markPrice', 0))
                        
                        if side == 'LONG':
                            long_count += 1
                            long_margin += margin
                        elif side == 'SHORT':
                            short_count += 1
                            short_margin += margin
                        
                        roe_pct = ((mark - entry) / entry * 100) if side == 'LONG' and entry > 0 else \
                                 ((entry - mark) / entry * 100) if side == 'SHORT' and entry > 0 else 0
                        
                        print(f"    {symbol} {side}: margin=${margin:.2f}, uPnL=${upnl:.2f}, ROE={roe_pct:+.1f}%")
                except Exception:
                    continue
            
            print(f"\n  Slot Usage: {long_count} LONG / {short_count} SHORT (total {long_count + short_count})")
            print(f"  Long Margin: ${long_margin:.2f}")
            print(f"  Short Margin: ${short_margin:.2f}")
            
            # Policy limits reminder
            print(f"\n  Policy Limits: 5L/5S slots, 25% side budget, 50% total (70% with ultra reserve)")
        else:
            print("\n  No open positions found.")
    
    except Exception as e:
        print(f"\n  Error fetching portfolio snapshot: {e}")


def main():
    parser = argparse.ArgumentParser(description="Trace trade lifecycle from signal to reward")
    parser.add_argument("-n", "--count", type=int, default=50, help="Number of signals to analyze")
    parser.add_argument("-d", "--details", type=int, default=10, help="Number of detailed entries to show")
    parser.add_argument("--symbol", type=str, help="Filter by symbol")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--portfolio", action="store_true", help="Show current portfolio snapshot")
    args = parser.parse_args()
    
    print("📊 Fetching trade lifecycle data from Redis...")
    
    rc = get_redis_client()
    
    # Print portfolio snapshot if requested
    if args.portfolio:
        print_portfolio_snapshot(rc)
    
    # Fetch all data
    signals = fetch_signals(rc, count=args.count * 2)  # Fetch extra to account for filtering
    skips = fetch_skips(rc, count=args.count * 4)
    executions = fetch_executions(rc, count=args.count * 4)
    fills = fetch_fills(rc, count=args.count * 4)
    rewards = fetch_reward_updates(rc, count=args.count * 4)
    
    print(f"   Signals: {len(signals)}")
    print(f"   Skips: {len(skips)}")
    print(f"   Executions: {len(executions)}")
    print(f"   Fills: {len(fills)}")
    print(f"   Rewards: {len(rewards)}")
    
    # Filter by symbol if specified
    if args.symbol:
        signals = [s for s in signals if s.get('symbol') == args.symbol]
        print(f"   Filtered to {len(signals)} signals for {args.symbol}")
    
    # Limit to requested count
    signals = signals[:args.count]
    
    # Correlate lifecycle
    lifecycles = correlate_lifecycle(signals, skips, executions, fills, rewards)
    
    if args.json:
        # JSON output with full contract fields
        output = []
        for lc in lifecycles:
            output.append({
                'signal_id': lc.signal_id,
                'symbol': lc.symbol,
                'action': lc.action,
                'timeframe': lc.timeframe,
                'confidence': lc.confidence,
                'executed': lc.executed,
                'skip_reason': lc.skip_reason,
                'root_causes': lc.root_causes,
                'realized_pnl': lc.realized_pnl,
                'reward_attributed': lc.reward_attributed,
                'latency_signal_to_exec_ms': lc.latency_signal_to_exec_ms,
                # Contract fields (Addendum D)
                'intent': lc.intent,
                'roe_pct': lc.roe_pct,
                'mfe_pct': lc.mfe_pct,
                'mae_pct': lc.mae_pct,
                'hot_monitor': lc.hot_monitor,
                'close_reason_code': lc.close_reason_code,
                'hedge_reason_code': lc.hedge_reason_code,
                # Portfolio policy (Addendum A)
                'portfolio_slots_used': lc.portfolio_slots_used,
                'portfolio_margin_pct': lc.portfolio_margin_pct,
                'portfolio_ultra_mode': lc.portfolio_ultra_mode,
            })
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        print_summary(lifecycles)
        print_details(lifecycles, limit=args.details)
        
        # Recommendations
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)
        
        cause_counts = defaultdict(int)
        for lc in lifecycles:
            for cause in lc.root_causes:
                cause_counts[cause] += 1
        
        top_issues = sorted(cause_counts.items(), key=lambda x: -x[1])[:5]
        for cause, count in top_issues:
            if cause.startswith("SUCCESS"):
                continue
            desc = ROOT_CAUSE_CATEGORIES.get(cause, "")
            if "SIZING" in cause or "MARGIN" in cause:
                print(f"  🔧 {cause}: Ensure trainer publishes margin_usd/notional_usd for all entry/flip signals")
            elif "COOLDOWN" in cause:
                print(f"  🔧 {cause}: Consider adjusting TRAINER_FLIP_COOLDOWN_MS or TRADER_FLIP_COOLDOWN_MS")
            elif "CONFIDENCE" in cause:
                print(f"  🔧 {cause}: Review MIN_CONF_ENTRY/MIN_CONF_EXIT thresholds")
            elif "CAUTION_MODE" in cause:
                print(f"  🔧 {cause}: Circuit breaker active - check daily loss threshold")
            elif "REWARD_NOT_ATTRIBUTED" in cause:
                print(f"  🔧 {cause}: Ensure ExecutionFeedbackConsumer is running in trainer")
            elif "FEEDBACK_LAG" in cause:
                print(f"  🔧 {cause}: High latency in feedback loop - check network/Redis performance")
            # Addendum A: Portfolio Policy blocks
            elif "PORTFOLIO_SLOT" in cause:
                print(f"  🔧 {cause}: Position slot limit reached (5L/5S) - need to close positions or increase ultra confidence")
            elif "PORTFOLIO_BUDGET" in cause:
                print(f"  🔧 {cause}: Side margin budget exceeded (25%) - reduce position sizes or close positions")
            elif "PORTFOLIO_RESERVE" in cause:
                print(f"  🔧 {cause}: Requires ultra reserve (conf>=0.98) - increase confidence or wait for capacity")
            elif "PORTFOLIO_STALE" in cause:
                print(f"  🔧 {cause}: Equity data stale - check portfolio_publisher service")
            # Addendum C: Anti-churn blocks
            elif "ANTI_CHURN" in cause or "SYMBOL_RATE_LIMIT" in cause:
                print(f"  🔧 {cause}: Rate limit hit - reduce signal frequency or increase limits")
            elif "HEDGE_STATE_COOLDOWN" in cause:
                print(f"  🔧 {cause}: Hedge state machine interval - increase ANTI_CHURN_HEDGE_STATE_MIN_INTERVAL_SEC")
            elif "WARM_START" in cause:
                print(f"  🔧 {cause}: Warm start window active - wait {int(os.getenv('ANTI_CHURN_WARM_START_WINDOW_SEC', 60))}s after restart")
            elif "SIGNAL_STALE" in cause:
                print(f"  🔧 {cause}: Signal too old - check signal latency in publish pipeline")


if __name__ == "__main__":
    main()
