#!/usr/bin/env python3
"""
Orchestrator Worker (Jan 2026)
==============================

THE SINGLE PUBLISHER FOR ALL TRADE SIGNALS.

This worker is the ONLY component that publishes to signals:live:{account}.
All modules (GPU predictor, HEDGE_MGR_V3, URC, Dynamic_TP) emit proposals
to wma:proposals stream. This worker:

1. Continuously consumes proposals using Redis consumer group
2. Groups proposals by (account, symbol) over a micro-window (500ms)
3. Runs TradePlanOrchestrator for arbitration
4. Publishes only winners to signals:live:{account}
5. Maintains cooldown horizon to prevent conflicting actions
6. Emits proofs to health:events and traces to wma:traces

INVARIANTS (must hold in publish mode):
- No other component publishes to signals:live:*
- Every published signal has a plan_id linking back to orchestrator proof
- Max 1 action per (account, symbol) per decision window
- CRITICAL proposals flush immediately but still arbitrate

Usage:
    python -m rl.orchestrator_worker [--shadow] [--window-ms=500]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from utils.redis_key_audit import wrap_redis_client

from risk.assertions import (
    assert_risk, build_portfolio_snapshot, is_risk_add_action,
    check_liq_buffer, PORTFOLIO_STALE_THRESHOLD_S,
)
from risk.kill_switch import get_kill_switch, kill_switch_blocks, set_kill_switch
from risk.phase_controller import get_ramp_phase, resolve_phase, check_ramp_limits
from utils.ensemble_diagnostics import publish_ensemble_diagnostic

try:
    import config
except ImportError:
    config = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("orchestrator_worker")


# ==============================================================================
# CONFIGURATION
# ==============================================================================

PROPOSAL_STREAM = os.getenv("ORCHESTRATOR_PROPOSAL_STREAM", "wma:proposals")
CONSUMER_GROUP = os.getenv("ORCHESTRATOR_CONSUMER_GROUP", "orchestrator_workers")
CONSUMER_NAME = os.getenv("ORCHESTRATOR_CONSUMER_NAME", f"worker_{os.getpid()}")

# Decision windows
MICRO_WINDOW_MS = int(os.getenv("ORCHESTRATOR_MICRO_WINDOW_MS", "500"))  # Aggregate proposals
COOLDOWN_HORIZON_MS = int(os.getenv("ORCHESTRATOR_COOLDOWN_HORIZON_MS", "15000"))  # Conflict prevention

# Output streams (use signals:trading:* for backward compatibility with existing traders)
SIGNAL_STREAM_PRIMARY = os.getenv("ORCHESTRATOR_SIGNAL_STREAM_PRIMARY", "signals:trading:primary")
SIGNAL_STREAM_ASJAD = os.getenv("ORCHESTRATOR_SIGNAL_STREAM_ASJAD", "signals:trading:asjad")
PROOF_STREAM = os.getenv("ORCHESTRATOR_PROOF_STREAM", "health:events")
TRACE_STREAM = os.getenv("ORCHESTRATOR_TRACE_STREAM", "wma:traces")
EXEC_EVENT_STREAM = os.getenv("ORCHESTRATOR_EXEC_EVENT_STREAM", "wma:exec_events")

# Hedge churn guard (no cooldowns; per-cycle hedge de-dup + critical confidence bypass)
HEDGE_CHURN_GUARD_ENABLED = os.getenv("ORCHESTRATOR_HEDGE_CHURN_GUARD_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Confidence threshold to mark hedge/protective proposals as CRITICAL (immediate flush)
HEDGE_CRITICAL_CONF = float(os.getenv("ORCHESTRATOR_HEDGE_CRITICAL_CONF", "0.90"))

# Invariant checks
FORBIDDEN_DIRECT_PUBLISH_STREAM = os.getenv("ORCHESTRATOR_FORBIDDEN_STREAM", "wma:forbidden_publishes")


@dataclass
class PublishedPlan:
    """Tracks a published plan for cooldown horizon conflict detection."""
    plan_id: str
    account_id: str
    symbol: str
    action: str
    action_family: str
    published_ts_ms: int
    proposal_id: str
    trace_id: str


@dataclass
class DecisionWindow:
    """Accumulates proposals for a micro-window before arbitration."""
    window_id: str
    account_id: str
    symbol: str
    start_ts_ms: int
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    flushed: bool = False
    fastlane: bool = False  # True → flush after ORCH_FASTLANE_WINDOW_MS (50ms) not micro_window_ms


class OrchestratorWorker:
    """
    Continuous orchestrator worker.
    
    Consumes proposals from wma:proposals, arbitrates, publishes winners.
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        shadow_mode: bool = False,
        micro_window_ms: int = MICRO_WINDOW_MS,
        cooldown_horizon_ms: int = COOLDOWN_HORIZON_MS,
    ):
        self.redis = redis_client
        self.shadow_mode = shadow_mode
        self.micro_window_ms = micro_window_ms
        self.cooldown_horizon_ms = cooldown_horizon_ms

        try:
            self.exec_event_maxlen = int(getattr(config, "STREAM_MAXLEN_EXEC_EVENTS", 100000))
            self.signal_maxlen = int(getattr(config, "STREAM_MAXLEN_SIGNALS", 50000))
        except Exception:
            self.exec_event_maxlen = 100000
            self.signal_maxlen = 50000

        try:
            self.liveness_check_sec = int(getattr(config, "ORCH_LIVENESS_CHECK_SEC", 30))
            self.pending_stall_ms = int(getattr(config, "ORCH_PENDING_STALL_MS", 120000))
        except Exception:
            self.liveness_check_sec = 30
            self.pending_stall_ms = 120000

        self._rotation_policy = self._load_rotation_policy()

        self._last_orch_heartbeat_ms = 0
        self._last_liveness_check_ms = 0
        self._orch_stall_hits = 0

        self._telegram = None
        try:
            from telegram_alerts import TelegramNotifier
            bot_token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
            bot_chat_id = getattr(config, "TELEGRAM_CHAT_ID", None)
            channel_id = getattr(config, "TELEGRAM_CHANNEL_ID", None)
            if bot_token and (bot_chat_id or channel_id):
                self._telegram = TelegramNotifier(
                    bot_token=bot_token,
                    bot_chat_id=bot_chat_id or channel_id,
                    channel_id=channel_id or bot_chat_id,
                    portfolio_channel_id=getattr(config, "PORTFOLIO_CHANNEL_ID", None),
                    trade_channel_id=getattr(config, "TRADE_CHANNEL_ID", None),
                    ai_signals_channel_id=getattr(config, "AI_SIGNALS_CHANNEL_ID", None),
                    redis_client=self.redis,
                )
        except Exception:
            self._telegram = None
        
        # Active decision windows: (account_id, symbol) -> DecisionWindow
        self.windows: Dict[Tuple[str, str], DecisionWindow] = {}
        
        # Published plans for cooldown horizon: (account_id, symbol) -> List[PublishedPlan]
        self.published_plans: Dict[Tuple[str, str], List[PublishedPlan]] = defaultdict(list)
        
        # Dedupe: seen proposal dedupe_keys in current cycle
        self.seen_dedupe_keys: Set[str] = set()
        
        # Stats
        self.stats = {
            "proposals_received": 0,
            "proposals_deduped": 0,
            "windows_arbitrated": 0,
            "signals_published": 0,
            "signals_dropped": 0,
            "conflicts_prevented": 0,
            "critical_flushes": 0,
            "hedge_churn_dropped": 0,
        }

        # Symbol price memory for stress velocity checks (operator policy gates)
        # key: "{account}:{symbol}" -> {"ts_ms": int, "price": float, "v60": List[(ts_ms, price)]}
        self._policy_price_state: Dict[str, Dict[str, Any]] = {}

        # Shock/reversal state memory (operator policy gates)
        # key: "{account}:{symbol}" -> state dict
        self._policy_shock_state: Dict[str, Dict[str, Any]] = {}

        # Portfolio stress memory (operator policy gates)
        # key: account_id -> state dict
        self._policy_portfolio_stress_state: Dict[str, Dict[str, Any]] = {}

        # Hedge add memory to prevent contradictory rapid-fire adds
        # key: "{account}:{symbol}" -> {"ts": float, "side": "LONG|SHORT"}
        self._policy_hedge_add_state: Dict[str, Dict[str, Any]] = {}

        # RBA cadence tracking: last open timestamp per account
        # key: account_id -> float (time.time() of last risk-add publish)
        self._rba_last_open_ts: Dict[str, float] = {}

        # Fix #3: Rolling entry counter — tracks ENTRY publishes per minute
        # Prevents entry spam overwhelming risk subsystem
        self._entry_publish_log: List[float] = []  # timestamps of recent ENTRY publishes
        self._entry_cap_window_sec: float = 60.0  # Rolling window (1 min)
        self._hedge_publish_log: List[float] = []  # timestamps of recent HEDGE publishes (separate cap)

        # Anti-churn: per-symbol rolling fill tracker (Feb 2026 Audit Fix #2)
        # key: symbol -> list of timestamps when a signal was published for that symbol
        self._per_symbol_fill_log: Dict[str, List[float]] = {}
        # Daily notional accumulator: tracks total notional published today (resets at midnight UTC)
        self._daily_notional_usd: float = 0.0
        self._daily_notional_reset_date: str = ""  # YYYY-MM-DD to detect day rollover
        # Daily drawdown tracker: tracks realized PnL today for circuit breaker
        self._daily_realized_pnl_usd: float = 0.0
        self._daily_pnl_reset_date: str = ""

        # Hedge shock manager state (per-symbol leg management during stress)
        # key: "{account}:{symbol}" -> {stress_consec_ticks, last_loser_cut_ts,
        #   last_winner_lock_ts, winner_peak_roe, winner_peak_side, actions_log}
        self._hedge_shock_mgr_state: Dict[str, Dict[str, Any]] = {}

        # Explicit account routing/standby controls
        try:
            self.account_primary_enabled = bool(getattr(config, "ACCOUNT_PRIMARY_ENABLED", True))
            self.account_asjad_enabled = bool(getattr(config, "ACCOUNT_ASJAD_ENABLED", False))
            self.account_asjad_allow_publish = bool(getattr(config, "ACCOUNT_ASJAD_ALLOW_PUBLISH", False))
            self.account_preflight_required = bool(getattr(config, "ACCOUNT_PREFLIGHT_REQUIRED", True))
            self.account_preflight_max_age_s = int(getattr(config, "ACCOUNT_PREFLIGHT_MAX_AGE_S", 30) or 30)
        except Exception:
            self.account_primary_enabled = True
            self.account_asjad_enabled = False
            self.account_asjad_allow_publish = False
            self.account_preflight_required = True
            self.account_preflight_max_age_s = 30

        logger.info(
            "ORCH_ACCOUNT_FLAGS | primary_enabled=%s | asjad_enabled=%s | asjad_allow_publish=%s | preflight_required=%s | preflight_max_age_s=%s",
            int(self.account_primary_enabled),
            int(self.account_asjad_enabled),
            int(self.account_asjad_allow_publish),
            int(self.account_preflight_required),
            int(self.account_preflight_max_age_s),
        )

        # Trader feedback suppression + publish feasibility (liquidation-path hardening)
        try:
            self.orch_pre_publish_feasibility_enabled = bool(getattr(config, "ORCH_PRE_PUBLISH_FEASIBILITY_ENABLED", True))
            self.orch_pre_publish_block_protective = bool(getattr(config, "ORCH_PRE_PUBLISH_BLOCK_PROTECTIVE", False))
            self.orch_context_gate_enabled = bool(getattr(config, "ORCH_CONTEXT_GATE_ENABLED", True))
            self.orch_context_gate_require_tf_fields = bool(getattr(config, "ORCH_CONTEXT_GATE_REQUIRE_TF_FIELDS", True))
            self.orch_context_gate_tf_conflict_threshold = float(getattr(config, "ORCH_CONTEXT_GATE_TF_CONFLICT_THRESHOLD", 0.55) or 0.55)
            self.orch_context_gate_regime_dump_enabled = bool(getattr(config, "ORCH_CONTEXT_GATE_REGIME_DUMP_ENABLED", True))
            self.orch_context_gate_dump_ret_15m_pct = float(getattr(config, "ORCH_CONTEXT_GATE_DUMP_RET_15M_PCT", -1.5) or -1.5)
            self.orch_context_gate_dump_ret_1h_pct = float(getattr(config, "ORCH_CONTEXT_GATE_DUMP_RET_1H_PCT", -2.5) or -2.5)
            self.orch_context_gate_regime_pump_enabled = bool(getattr(config, "ORCH_CONTEXT_GATE_REGIME_PUMP_ENABLED", True))
            self.orch_context_gate_pump_ret_15m_pct = float(getattr(config, "ORCH_CONTEXT_GATE_PUMP_RET_15M_PCT", 1.5) or 1.5)
            self.orch_context_gate_pump_ret_1h_pct = float(getattr(config, "ORCH_CONTEXT_GATE_PUMP_RET_1H_PCT", 2.5) or 2.5)
            self.orch_microstructure_veto_enabled = bool(getattr(config, "ORCH_MICROSTRUCTURE_VETO_ENABLED", True))
            self.orch_microstructure_spoof_threshold = float(getattr(config, "ORCH_MICROSTRUCTURE_SPOOF_THRESHOLD", 0.70) or 0.70)
            self.orch_microstructure_spread_spike_bps = float(getattr(config, "ORCH_MICROSTRUCTURE_SPREAD_SPIKE_BPS", 15.0) or 15.0)
            self.orch_microstructure_move_intensity_threshold = float(getattr(config, "ORCH_MICROSTRUCTURE_MOVE_INTENSITY_THRESHOLD", 0.80) or 0.80)
            self.orch_confidence_saturation_enabled = bool(getattr(config, "ORCH_CONFIDENCE_SATURATION_ENABLED", True))
            self.orch_confidence_saturation_threshold = float(getattr(config, "ORCH_CONFIDENCE_SATURATION_THRESHOLD", 0.99) or 0.99)
            self.orch_confidence_saturation_action = str(getattr(config, "ORCH_CONFIDENCE_SATURATION_ACTION", "FLAG") or "FLAG").upper().strip()
            self.orch_context_gate_liq_coupling_enabled = bool(getattr(config, "ORCH_CONTEXT_GATE_LIQ_COUPLING_ENABLED", True))
            self.orch_context_gate_liq_imbalance_ratio = float(getattr(config, "ORCH_CONTEXT_GATE_LIQ_IMBALANCE_RATIO", 1.50) or 1.50)
            self.orch_context_gate_liq_min_strength = float(getattr(config, "ORCH_CONTEXT_GATE_LIQ_MIN_STRENGTH", 5e8) or 5e8)
            # 3rd condition: liq cluster proximity (0 = disabled)
            self.orch_context_gate_liq_max_dist_bps = float(getattr(config, "ORCH_CONTEXT_GATE_LIQ_MAX_DIST_BPS", 0.0) or 0.0)
            # Hedge shock manager
            self.orch_hedge_shock_enabled = bool(getattr(config, "ORCH_HEDGE_SHOCK_ENABLED", True))
            self.orch_hedge_shock_stress_ticks_min = int(getattr(config, "ORCH_HEDGE_SHOCK_STRESS_TICKS_MIN", 3) or 3)
            self.orch_hedge_shock_loser_roe_threshold_pct = float(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_ROE_THRESHOLD_PCT", -5.0))
            self.orch_hedge_shock_loser_cut_fraction = float(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_CUT_FRACTION", 0.15) or 0.15)
            self.orch_hedge_shock_loser_cooldown_sec = int(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_COOLDOWN_SEC", 180) or 180)
            self.orch_hedge_shock_winner_min_roe_pct = float(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_MIN_ROE_PCT", 5.0) or 5.0)
            self.orch_hedge_shock_winner_retrace_pct = float(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_RETRACE_PCT", 50.0) or 50.0)
            self.orch_hedge_shock_winner_lock_fraction = float(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_LOCK_FRACTION", 0.08) or 0.08)
            self.orch_hedge_shock_winner_cooldown_sec = int(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_COOLDOWN_SEC", 300) or 300)
            self.orch_hedge_shock_max_actions_hourly = int(getattr(config, "ORCH_HEDGE_SHOCK_MAX_ACTIONS_HOURLY", 3) or 3)
            self.orch_hedge_shock_one_leg_only = bool(getattr(config, "ORCH_HEDGE_SHOCK_ONE_LEG_ONLY", True))
            self.orch_hedge_shock_block_add_to_loser = bool(getattr(config, "ORCH_HEDGE_SHOCK_BLOCK_ADD_TO_LOSER", True))
            self.orch_hedge_shock_pair_action_gap_sec = int(getattr(config, "ORCH_HEDGE_SHOCK_PAIR_ACTION_GAP_SEC", 300) or 300)
            self.orch_hedge_shock_margin_crit_threshold = float(getattr(config, "ORCH_HEDGE_SHOCK_MARGIN_CRIT_THRESHOLD", 0.93) or 0.93)
            self.orch_hedge_shock_margin_crit_cut_fraction = float(getattr(config, "ORCH_HEDGE_SHOCK_MARGIN_CRIT_CUT_FRACTION", 0.35) or 0.35)
            self.orch_hedge_shock_winner_lock_margin_gate = float(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_LOCK_MARGIN_GATE", 0.85) or 0.85)
            self.orch_hedge_shock_winner_lock_suppress_gate = bool(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_LOCK_SUPPRESS_GATE", True))
            self.orch_hedge_shock_loser_cut_require_momentum = bool(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_CUT_REQUIRE_MOMENTUM", True))
            self.orch_hedge_shock_loser_cut_min_fast_move = float(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_FAST_MOVE", 0.50) or 0.50)
            self.orch_hedge_shock_loser_cut_min_roe_delta = float(getattr(config, "ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_ROE_DELTA", -1.0))
            # Crash-escalation vars
            self.orch_hedge_shock_crash_escalation_enabled = bool(getattr(config, "ORCH_HEDGE_SHOCK_CRASH_ESCALATION_ENABLED", True))
            self.orch_hedge_shock_crash_fast_move_min = float(getattr(config, "ORCH_HEDGE_SHOCK_CRASH_FAST_MOVE_MIN", 0.70) or 0.70)
            self.orch_hedge_shock_crash_roe_delta_max = float(getattr(config, "ORCH_HEDGE_SHOCK_CRASH_ROE_DELTA_MAX", -2.0))
            self.orch_hedge_shock_crash_margin_util_min = float(getattr(config, "ORCH_HEDGE_SHOCK_CRASH_MARGIN_UTIL_MIN", 0.50) or 0.50)
            self.orch_hedge_shock_crash_cut_fraction = float(getattr(config, "ORCH_HEDGE_SHOCK_CRASH_CUT_FRACTION", 0.35) or 0.35)
            # Winner-lock equity gate
            self.orch_hedge_shock_winner_lock_equity_gate = float(getattr(config, "ORCH_HEDGE_SHOCK_WINNER_LOCK_EQUITY_GATE", 1500.0) or 1500.0)
            self.orch_feedback_suppress_enabled = bool(getattr(config, "ORCH_FEEDBACK_SUPPRESS_ENABLED", True))
            self.orch_feedback_suppress_ttl_sec = int(getattr(config, "ORCH_FEEDBACK_SUPPRESS_TTL_SEC", 300) or 300)
            self.orch_feedback_poll_sec = int(getattr(config, "ORCH_FEEDBACK_POLL_SEC", 2) or 2)
            self.orch_feedback_read_count = int(getattr(config, "ORCH_FEEDBACK_READ_COUNT", 100) or 100)
            self.orch_feedback_stream = str(getattr(config, "EXECUTION_FEEDBACK_STREAM", "wma:trader:execution_feedback") or "wma:trader:execution_feedback")
            self.orch_feedback_reason_codes = {
                str(v).upper().strip()
                for v in (getattr(config, "ORCH_FEEDBACK_SUPPRESS_REASON_CODES", [
                    "MARGIN_CAP_BLOCK",
                    "HEDGE_PAIR_MARGIN_CAP_BLOCK",
                    "TRADER_FREE_MARGIN_BLOCK",
                    "FREE_MARGIN_BLOCK",
                    "INSUFFICIENT_MARGIN",
                    "INSUFFICIENT_MARGIN_2019",
                    "API_2019",
                    "NO_HEADROOM",
                ]) or [])
                if str(v or "").strip()
            }
        except Exception:
            self.orch_pre_publish_feasibility_enabled = True
            self.orch_pre_publish_block_protective = False
            self.orch_context_gate_enabled = True
            self.orch_context_gate_require_tf_fields = True
            self.orch_context_gate_tf_conflict_threshold = 0.55
            self.orch_context_gate_regime_dump_enabled = True
            self.orch_context_gate_dump_ret_15m_pct = -1.5
            self.orch_context_gate_dump_ret_1h_pct = -2.5
            self.orch_context_gate_regime_pump_enabled = True
            self.orch_context_gate_pump_ret_15m_pct = 1.5
            self.orch_context_gate_pump_ret_1h_pct = 2.5
            self.orch_microstructure_veto_enabled = True
            self.orch_microstructure_spoof_threshold = 0.70
            self.orch_microstructure_spread_spike_bps = 15.0
            self.orch_microstructure_move_intensity_threshold = 0.80
            self.orch_confidence_saturation_enabled = True
            self.orch_confidence_saturation_threshold = 0.99
            self.orch_confidence_saturation_action = "FLAG"
            self.orch_context_gate_liq_coupling_enabled = True
            self.orch_context_gate_liq_imbalance_ratio = 1.50
            self.orch_context_gate_liq_min_strength = 5e8
            self.orch_context_gate_liq_max_dist_bps = 0.0  # 3rd condition disabled by default
            # Hedge shock manager fallback defaults
            self.orch_hedge_shock_enabled = True
            self.orch_hedge_shock_stress_ticks_min = 3
            self.orch_hedge_shock_loser_roe_threshold_pct = -5.0
            self.orch_hedge_shock_loser_cut_fraction = 0.15
            self.orch_hedge_shock_loser_cooldown_sec = 180
            self.orch_hedge_shock_winner_min_roe_pct = 5.0
            self.orch_hedge_shock_winner_retrace_pct = 50.0
            self.orch_hedge_shock_winner_lock_fraction = 0.08
            self.orch_hedge_shock_winner_cooldown_sec = 300
            self.orch_hedge_shock_max_actions_hourly = 3
            self.orch_hedge_shock_one_leg_only = True
            self.orch_hedge_shock_block_add_to_loser = True
            self.orch_hedge_shock_pair_action_gap_sec = 300
            self.orch_hedge_shock_margin_crit_threshold = 0.93
            self.orch_hedge_shock_margin_crit_cut_fraction = 0.35
            self.orch_hedge_shock_winner_lock_margin_gate = 0.85
            self.orch_hedge_shock_winner_lock_suppress_gate = True
            self.orch_hedge_shock_loser_cut_require_momentum = True
            self.orch_hedge_shock_loser_cut_min_fast_move = 0.50
            self.orch_hedge_shock_loser_cut_min_roe_delta = -1.0
            # Crash-escalation fallbacks
            self.orch_hedge_shock_crash_escalation_enabled = True
            self.orch_hedge_shock_crash_fast_move_min = 0.70
            self.orch_hedge_shock_crash_roe_delta_max = -2.0
            self.orch_hedge_shock_crash_margin_util_min = 0.50
            self.orch_hedge_shock_crash_cut_fraction = 0.35
            # Winner-lock equity gate fallback
            self.orch_hedge_shock_winner_lock_equity_gate = 1500.0
            self.orch_feedback_suppress_enabled = True
            self.orch_feedback_suppress_ttl_sec = 300
            self.orch_feedback_poll_sec = 2
            self.orch_feedback_read_count = 100
            self.orch_feedback_stream = "wma:trader:execution_feedback"
            self.orch_feedback_reason_codes = {
                "MARGIN_CAP_BLOCK",
                "HEDGE_PAIR_MARGIN_CAP_BLOCK",
                "TRADER_FREE_MARGIN_BLOCK",
                "FREE_MARGIN_BLOCK",
                "INSUFFICIENT_MARGIN",
                "INSUFFICIENT_MARGIN_2019",
                "API_2019",
                "NO_HEADROOM",
            }

        self._feedback_stream_last_id: Optional[str] = None
        self._feedback_block_state: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._last_feedback_poll_ms = 0

        # Canonical symbol universe enforcement (fail-closed at orchestrator publish boundary)
        try:
            self.universe_enforcement_enabled = bool(getattr(config, "UNIVERSE_ENFORCEMENT_ENABLED", True))
            self.universe_enforce_orchestrator = bool(getattr(config, "UNIVERSE_ENFORCE_ORCHESTRATOR", True))
            raw_allowed = getattr(config, "UNIVERSE_ALLOWED_SYMBOLS", getattr(config, "SYMBOLS", [])) or []
            self.universe_allowed_symbols = {
                str(s or "").upper().strip() for s in raw_allowed if str(s or "").strip()
            }
        except Exception:
            self.universe_enforcement_enabled = True
            self.universe_enforce_orchestrator = True
            self.universe_allowed_symbols = {
                str(s or "").upper().strip()
                for s in (getattr(config, "SYMBOLS", []) or [])
                if str(s or "").strip()
            }

        logger.info(
            "ORCH_UNIVERSE_FLAGS | enabled=%s | enforce_orchestrator=%s | allow_count=%s",
            int(self.universe_enforcement_enabled),
            int(self.universe_enforce_orchestrator),
            int(len(self.universe_allowed_symbols)),
        )
        
        # Initialize TradePlanOrchestrator
        self._init_orchestrator()
        
        # Ensure consumer group exists
        self._ensure_consumer_group()
        
        # Running flag
        self.running = True
    
    def _init_orchestrator(self):
        """Initialize the TradePlanOrchestrator for arbitration."""
        try:
            from rl.tradeplan_orchestrator import TradePlanOrchestrator
            self.orchestrator = TradePlanOrchestrator(
                redis_client=self.redis,
                cfg=config,
            )
            logger.info("✅ TradePlanOrchestrator initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize TradePlanOrchestrator: {e}")
            self.orchestrator = None

    def _load_rotation_policy(self) -> Dict[str, Any]:
        defaults = {
            "enabled": True,
            "swap_improvement_threshold": 0.35,
            "min_candidate_confidence": 0.90,
            "min_liq_distance_pct": 1.0,
            "max_swaps_per_hour": 2,
            "per_symbol_cooldown_sec": 900,
            "global_cooldown_sec": 120,
            "reduce_instead_of_close": True,
            "reduce_fraction": 0.25,
            "no_loss_only": False,
            "loss_tolerance_pct": 0.05,
            "winner_protect_pnl_pct": 1.5,
            "winner_override_margin": 0.75,
            "dq_min_confidence": 0.5,
            "pending_timeout_sec": 90,
            "pending_max_attempts": 3,
            "min_hold_sec": 300,
            "allow_if_drawdown_lt": 6.0,
            "block_if_tox_gt": 0.60,
            "block_if_ob_lt": 150000,
            "dq_required_fields": ["liq_distance_pct", "orderbook_depth_usd", "volatility_pct"],
            "dq_max_orderbook_age_ms": 15000,
            "dq_max_liqmap_age_ms": 90000,
            "dq_max_vol_age_ms": 120000,
        }
        try:
            policy = getattr(config, "ROTATION_POLICY", None)
        except Exception:
            policy = None
        if isinstance(policy, dict):
            merged = dict(defaults)
            merged.update(policy)
            return merged
        return defaults

    @staticmethod
    def _clamp(val: float, lo: float, hi: float) -> float:
        try:
            v = float(val)
        except Exception:
            v = 0.0
        return max(lo, min(hi, v))

    @staticmethod
    def _score_candidate_open_static(signal: Dict[str, Any], policy: Dict[str, Any]) -> float:
        confidence = float(signal.get("confidence") or signal.get("model_confidence") or 0.0)
        edge = float(signal.get("expected_edge_net") or 0.0)
        meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
        tox = meta.get("toxicity") if meta else signal.get("toxicity")
        try:
            tox = float(tox or 0.0)
        except Exception:
            tox = 0.0
        liq_dist = float(signal.get("liq_distance_pct") or 0.0)
        dq_conf = float(signal.get("dq_confidence") or 0.0)
        dq_fallback = bool(signal.get("dq_fallback_used"))
        try:
            dq_score = float(signal.get("dq_score") or 0.0)
        except Exception:
            dq_score = 0.0
        if dq_score <= 0:
            dq_score = 0.0
        liquidity_soft = bool(signal.get("liquidity_soft_block")) or bool(signal.get("liquidity_soft_throttle"))

        edge_clamped = OrchestratorWorker._clamp(edge, -1.0, 1.0)
        liq_term = OrchestratorWorker._clamp(liq_dist / 10.0, 0.0, 1.0)

        score = (
            1.5 * confidence
            + 0.8 * edge_clamped
            - 0.8 * tox
            + 0.4 * liq_term
            + 0.2 * dq_conf
            - 1.0 * (1.0 if dq_fallback else 0.0)
            - 1.0 * (1.0 if liquidity_soft else 0.0)
        )
        return float(score)

    @staticmethod
    def _score_keep_position_static(pos: Dict[str, Any]) -> float:
        pnl_pct = pos.get("unrealized_pnl_pct")
        drawdown_pct = pos.get("drawdown_pct")
        age_sec = pos.get("age_sec")
        churn_flag = bool(pos.get("churn_risk"))

        try:
            pnl_pct = float(pnl_pct or 0.0)
        except Exception:
            pnl_pct = 0.0
        try:
            drawdown_pct = float(drawdown_pct or 0.0)
        except Exception:
            drawdown_pct = 0.0
        try:
            age_sec = float(age_sec or 0.0)
        except Exception:
            age_sec = 0.0

        time_score = OrchestratorWorker._clamp(age_sec / 3600.0, 0.0, 1.0)

        score = (
            0.6 * pnl_pct
            + 0.4 * time_score
            - 0.8 * drawdown_pct
            - 0.5 * (1.0 if churn_flag else 0.0)
        )
        return float(score)

    def _get_cost_penalty(self, account_id: str, symbol: str) -> float:
        if not self.redis:
            return 0.0
        sym = str(symbol or "").upper()
        key = f"pnl:decomp:1d:{account_id}:symbols"
        try:
            fees = self.redis.hget(key, f"fee_usd:{sym}")
            slippage = self.redis.hget(key, f"slippage_usd:{sym}")
            net = self.redis.hget(key, f"net_pnl_usd:{sym}")
            fees = float(fees or 0.0)
            slippage = float(slippage or 0.0)
            net = float(net or 0.0)
        except Exception:
            return 0.0
        cost = abs(fees) + abs(slippage)
        denom = max(1.0, abs(net) + cost)
        penalty = cost / denom if denom > 0 else 0.0
        return max(0.0, min(1.0, float(penalty)))

    @staticmethod
    def _extract_metric(proposal: Dict[str, Any], keys: List[str]) -> Optional[float]:
        meta = proposal.get("metadata") if isinstance(proposal.get("metadata"), dict) else {}
        for key in keys:
            val = proposal.get(key)
            if val is None and meta:
                val = meta.get(key)
            if val is not None:
                try:
                    return float(val)
                except Exception:
                    return None
        return None

    def _dynamic_threshold(self, symbol: str, lo: float, hi: float, *, invert: bool = False) -> float:
        """Compute a data-driven threshold between lo..hi using real-time regime/ADX/TF alignment.

        When invert=False (default): strong trend/alignment → threshold moves toward lo (more permissive).
        When invert=True: strong trend/alignment → threshold moves toward hi (more restrictive).
        """
        try:
            if not self.redis or not symbol:
                return (lo + hi) / 2.0
            import json as _jdt
            _sym = symbol.upper().strip()
            _regime_raw = self.redis.get(f"regime:{_sym}")
            _move_regime = ""
            if _regime_raw:
                _rs = (_regime_raw.decode() if isinstance(_regime_raw, (bytes, bytearray)) else str(_regime_raw)).upper().strip()
                if _rs and _rs != "NONE":
                    try:
                        _rj = _jdt.loads(_rs) if _rs.startswith("{") else {}
                        _move_regime = str(_rj.get("move_regime") or _rj.get("regime") or _rs).upper()
                    except Exception:
                        _move_regime = _rs
            _uf = {}
            for _tf in ["5m", "15m", "1h"]:
                _uf_raw = self.redis.get(f"unified_features:{_sym}:{_tf}")
                if _uf_raw:
                    try:
                        _uf = _jdt.loads(_uf_raw.decode() if isinstance(_uf_raw, (bytes, bytearray)) else _uf_raw)
                        break
                    except Exception:
                        pass
            _adx = float(_uf.get("adx") or _uf.get("ADX_14") or _uf.get("adx_14") or 0)
            _tf_align = float(_uf.get("tf_alignment") or _uf.get("timeframe_alignment") or 0.5)
            _vol_score = float(_uf.get("volatility_score") or _uf.get("vol_score") or 0.5)
            _score = 0.0
            if _move_regime in ("TRENDING", "FAST", "IMPULSE", "BREAKOUT"):
                _score += 0.4
            if _adx > 25:
                _score += 0.3
            elif _adx > 18:
                _score += 0.15
            if _tf_align > 0.6:
                _score += 0.3
            elif _tf_align > 0.4:
                _score += 0.15
            _t = min(1.0, _score)
            if invert:
                return lo + (hi - lo) * _t
            return hi - (hi - lo) * _t
        except Exception:
            return (lo + hi) / 2.0

    def _dynamic_value(self, symbol: str, lo: float, hi: float) -> float:
        """Compute a data-driven value between lo..hi. Strong trend → toward hi."""
        return self._dynamic_threshold(symbol, lo, hi, invert=True)

    def _read_hedge_state(self, account_id: str, symbol: str) -> Dict[str, Any]:
        if not self.redis:
            return {}
        key = f"hedge:state:{account_id}:{symbol}"
        try:
            raw = self.redis.hgetall(key) or {}
        except Exception:
            return {}
        state = {
            "state": raw.get(b"state", b"").decode() if isinstance(raw.get(b"state"), (bytes, bytearray)) else raw.get("state"),
            "last_ts_ms": raw.get(b"last_ts_ms", b"").decode() if isinstance(raw.get(b"last_ts_ms"), (bytes, bytearray)) else raw.get("last_ts_ms"),
            "last_change_ts_ms": raw.get(b"last_change_ts_ms", b"").decode() if isinstance(raw.get(b"last_change_ts_ms"), (bytes, bytearray)) else raw.get("last_change_ts_ms"),
            "reason": raw.get(b"reason", b"").decode() if isinstance(raw.get(b"reason"), (bytes, bytearray)) else raw.get("reason"),
        }
        return state

    def _write_hedge_state(
        self,
        account_id: str,
        symbol: str,
        state: str,
        reason: str,
        now_ms: int,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.redis:
            return
        key = f"hedge:state:{account_id}:{symbol}"
        payload = {
            "state": state,
            "reason": reason,
            "last_ts_ms": str(now_ms),
        }
        if metrics:
            for k, v in metrics.items():
                if k == "last_change_ts_ms":
                    payload[k] = str(v)
                    continue
                try:
                    payload[k] = f"{float(v):.6f}"
                except Exception:
                    payload[k] = str(v)
        try:
            self.redis.hset(key, mapping=payload)
        except Exception:
            pass

    def _calc_hedge_state(
        self,
        liq_dist: Optional[float],
        toxicity: Optional[float],
        vol: Optional[float],
        ob_depth: Optional[float],
        drawdown: Optional[float],
        thresholds: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Tuple[str, str]:
        liq_dist = float(liq_dist) if liq_dist is not None else None
        toxicity = float(toxicity) if toxicity is not None else None
        vol = float(vol) if vol is not None else None
        ob_depth = float(ob_depth) if ob_depth is not None else None
        drawdown = float(drawdown) if drawdown is not None else None

        full_on = False
        partial_on = False
        reasons = []

        liq_full_on = float(getattr(config, "HEDGE_LIQ_FULL_ON", 5.0))
        liq_partial_on = float(getattr(config, "HEDGE_LIQ_PARTIAL_ON", 8.0))
        liq_off = float(getattr(config, "HEDGE_LIQ_OFF", 12.0))
        tox_full_on = float(getattr(config, "HEDGE_TOX_FULL_ON", 0.55))
        tox_partial_on = float(getattr(config, "HEDGE_TOX_PARTIAL_ON", 0.35))
        tox_off = float(getattr(config, "HEDGE_TOX_OFF", 0.25))
        vol_full_on = float(getattr(config, "HEDGE_VOL_FULL_ON", 55.0))
        vol_partial_on = float(getattr(config, "HEDGE_VOL_PARTIAL_ON", 35.0))
        vol_off = float(getattr(config, "HEDGE_VOL_OFF", 25.0))
        ob_bad = float(getattr(config, "HEDGE_OB_MIN_BAD", 100000))
        ob_ok = float(getattr(config, "HEDGE_OB_MIN_OK", 250000))
        dd_full_on = float(getattr(config, "HEDGE_DD_FULL_ON", 7.0))
        dd_partial_on = float(getattr(config, "HEDGE_DD_PARTIAL_ON", 4.0))
        dd_off = float(getattr(config, "HEDGE_DD_OFF", 2.5))

        if thresholds:
            try:
                if thresholds.get("liq_dist"):
                    liq_full_on = float(thresholds["liq_dist"].get("full_on", liq_full_on))
                    liq_partial_on = float(thresholds["liq_dist"].get("partial_on", liq_partial_on))
                    liq_off = float(thresholds["liq_dist"].get("off", liq_off))
                if thresholds.get("toxicity"):
                    tox_full_on = float(thresholds["toxicity"].get("full_on", tox_full_on))
                    tox_partial_on = float(thresholds["toxicity"].get("partial_on", tox_partial_on))
                    tox_off = float(thresholds["toxicity"].get("off", tox_off))
                if thresholds.get("volatility"):
                    vol_full_on = float(thresholds["volatility"].get("full_on", vol_full_on))
                    vol_partial_on = float(thresholds["volatility"].get("partial_on", vol_partial_on))
                    vol_off = float(thresholds["volatility"].get("off", vol_off))
                if thresholds.get("ob_depth"):
                    ob_bad = float(thresholds["ob_depth"].get("full_on", ob_bad))
                    ob_ok = float(thresholds["ob_depth"].get("partial_on", ob_ok))
                if thresholds.get("drawdown"):
                    dd_full_on = float(thresholds["drawdown"].get("full_on", dd_full_on))
                    dd_partial_on = float(thresholds["drawdown"].get("partial_on", dd_partial_on))
                    dd_off = float(thresholds["drawdown"].get("off", dd_off))
            except Exception:
                pass

        if liq_dist is not None and liq_dist <= liq_full_on:
            full_on = True
            reasons.append("LIQ_FULL")
        elif liq_dist is not None and liq_dist <= liq_partial_on:
            partial_on = True
            reasons.append("LIQ_PARTIAL")

        if toxicity is not None and toxicity >= tox_full_on:
            full_on = True
            reasons.append("TOX_FULL")
        elif toxicity is not None and toxicity >= tox_partial_on:
            partial_on = True
            reasons.append("TOX_PARTIAL")

        if vol is not None and vol >= vol_full_on:
            full_on = True
            reasons.append("VOL_FULL")
        elif vol is not None and vol >= vol_partial_on:
            partial_on = True
            reasons.append("VOL_PARTIAL")

        if ob_depth is not None and ob_depth <= ob_bad:
            full_on = True
            reasons.append("OB_BAD")
        elif ob_depth is not None and ob_depth <= ob_ok:
            partial_on = True
            reasons.append("OB_WEAK")

        if drawdown is not None and drawdown >= dd_full_on:
            full_on = True
            reasons.append("DD_FULL")
        elif drawdown is not None and drawdown >= dd_partial_on:
            partial_on = True
            reasons.append("DD_PARTIAL")

        if full_on:
            return "HEDGE_FULL", "+".join(reasons) if reasons else "FULL_ON"
        if partial_on:
            return "HEDGE_PARTIAL", "+".join(reasons) if reasons else "PARTIAL_ON"

        off_ok = True
        if liq_dist is not None and liq_dist < liq_off:
            off_ok = False
        if toxicity is not None and toxicity > tox_off:
            off_ok = False
        if vol is not None and vol > vol_off:
            off_ok = False
        if drawdown is not None and drawdown > dd_off:
            off_ok = False
        if ob_depth is not None and ob_depth < ob_ok:
            off_ok = False

        if off_ok:
            return "HEDGE_OFF", "OFF_SAFE"
        return "HEDGE_PARTIAL", "PARTIAL_UNCLEAR"

    def _update_hedge_state_from_proposals(
        self,
        account_id: str,
        symbol: str,
        proposals: List[Dict[str, Any]],
        now_ms: int,
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        if not getattr(config, "HEDGE_ENABLED", False):
            return "HEDGE_DISABLED", {}
        liq_vals = []
        tox_vals = []
        vol_vals = []
        ob_vals = []
        dd_vals = []
        for p in proposals:
            liq = self._extract_metric(p, ["liq_distance_pct", "liq_dist_pct", "liq_distance"])
            tox = self._extract_metric(p, ["toxicity", "tox"])
            vol = self._extract_metric(p, ["volatility_pct", "volatility", "vol"])
            ob = self._extract_metric(p, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])
            dd = self._extract_metric(p, ["drawdown_pct", "dd_pct", "drawdown"])
            if liq is not None:
                liq_vals.append(liq)
            if tox is not None:
                tox_vals.append(tox)
            if vol is not None:
                vol_vals.append(vol)
            if ob is not None:
                ob_vals.append(ob)
            if dd is not None:
                dd_vals.append(dd)

        liq_dist = min(liq_vals) if liq_vals else None
        toxicity = max(tox_vals) if tox_vals else None
        vol = max(vol_vals) if vol_vals else None
        ob_depth = min(ob_vals) if ob_vals else None
        drawdown = max(dd_vals) if dd_vals else None

        previous = self._read_hedge_state(account_id, symbol)
        prev_state = str(previous.get("state") or "HEDGE_OFF").upper()
        last_change_ms = int(previous.get("last_change_ts_ms") or previous.get("last_ts_ms") or 0)

        build_key = f"hedge:build:trigger:{account_id}:{symbol}"
        build_triggered = False
        if self.redis:
            try:
                build_triggered = bool(self.redis.get(build_key))
            except Exception:
                build_triggered = False

        percentile_meta = self._update_hedge_percentiles(symbol, {
            "liq_dist": liq_dist,
            "toxicity": toxicity,
            "volatility": vol,
            "ob_depth": ob_depth,
            "drawdown": drawdown,
        })

        if build_triggered:
            desired_state = "HEDGE_BUILD"
            reason = "BUILD_TRIGGER"
        else:
            desired_state, reason = self._calc_hedge_state(
                liq_dist,
                toxicity,
                vol,
                ob_depth,
                drawdown,
                thresholds=percentile_meta.get("thresholds") if percentile_meta.get("used") else None,
            )

        dq_score, dq_meta = self._calc_dq_score(
            {
                "liq_distance_pct": liq_dist,
                "orderbook_depth_usd": ob_depth,
                "orderbook_ts_ms": max(int(p.get("orderbook_ts_ms") or 0) for p in proposals) if proposals else 0,
                "liqmap_ts_ms": max(int(p.get("liqmap_ts_ms") or 0) for p in proposals) if proposals else 0,
            }
        )
        if float(dq_score) < 0.8 and desired_state == "HEDGE_FULL":
            desired_state = "HEDGE_PARTIAL"
            reason = f"DQ_BLOCK_FULL|{reason}"

        min_hold_ms = int(getattr(config, "HEDGE_MIN_HOLD_SECS", 90)) * 1000
        cooldown_ms = int(getattr(config, "HEDGE_COOLDOWN_SECS", 120)) * 1000
        state = prev_state
        if desired_state != prev_state:
            if (now_ms - last_change_ms) >= max(cooldown_ms, min_hold_ms):
                state = desired_state
                self._write_hedge_state(
                    account_id,
                    symbol,
                    state,
                    reason,
                    now_ms,
                    {
                        "liq_dist": liq_dist if liq_dist is not None else "",
                        "toxicity": toxicity if toxicity is not None else "",
                        "volatility": vol if vol is not None else "",
                        "ob_depth_usd": ob_depth if ob_depth is not None else "",
                        "drawdown": drawdown if drawdown is not None else "",
                        "last_change_ts_ms": str(now_ms),
                    },
                )
            else:
                state = prev_state
                self._write_hedge_state(
                    account_id,
                    symbol,
                    state,
                    f"HOLD_{reason}",
                    now_ms,
                    {
                        "liq_dist": liq_dist if liq_dist is not None else "",
                        "toxicity": toxicity if toxicity is not None else "",
                        "volatility": vol if vol is not None else "",
                        "ob_depth_usd": ob_depth if ob_depth is not None else "",
                        "drawdown": drawdown if drawdown is not None else "",
                        "last_change_ts_ms": str(last_change_ms),
                    },
                )
        else:
            self._write_hedge_state(
                account_id,
                symbol,
                state,
                reason,
                now_ms,
                {
                    "liq_dist": liq_dist if liq_dist is not None else "",
                    "toxicity": toxicity if toxicity is not None else "",
                    "volatility": vol if vol is not None else "",
                    "ob_depth_usd": ob_depth if ob_depth is not None else "",
                    "drawdown": drawdown if drawdown is not None else "",
                    "last_change_ts_ms": str(last_change_ms),
                },
            )

        metrics = {
            "liq_dist": liq_dist,
            "toxicity": toxicity,
            "volatility": vol,
            "ob_depth_usd": ob_depth,
            "drawdown": drawdown,
            "dq_score": float(dq_score),
        }
        if dq_meta:
            metrics.update({f"dq_{k}": v for k, v in dq_meta.items()})
        return state, metrics, percentile_meta

    def _apply_dynamic_sizing(self, winner: Dict[str, Any], proof: Dict[str, Any], portfolio: Optional[Dict[str, Any]] = None, tier: Optional[int] = None) -> None:
        if self._is_hedge_like(winner):
            return
        action = str(winner.get("action") or winner.get("action_name") or "")
        if not is_risk_add_action(action):
            return

        try:
            current_margin = float(winner.get("margin_usd") or 0.0)
        except Exception:
            current_margin = 0.0
        if current_margin <= 0:
            return

        tox = self._extract_metric(winner, ["toxicity", "tox"])
        liq_dist = self._extract_metric(winner, ["liq_distance_pct", "liq_dist_pct", "liq_distance"])
        ob_depth = self._extract_metric(winner, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])
        vol = self._extract_metric(winner, ["volatility_pct", "volatility", "vol"])
        dq_score = self._extract_metric(winner, ["dq_score"]) or 1.0

        try:
            confidence = float(winner.get("confidence") or winner.get("model_confidence") or 0.0)
        except Exception:
            confidence = 0.0
        quality = max(0.0, min(1.0, confidence * (1.0 - float(tox or 0.0))))
        liq_safety = max(0.0, min(1.0, float(liq_dist or 0.0) / 4.0)) if liq_dist is not None else 0.5

        # Major symbols (BTC/ETH/SOL) run at higher leverage → smaller liq_dist,
        # which unfairly penalizes their margin sizing. Apply a floor so they get
        # at least 50% of normal sizing instead of being crushed to $10 MIN_OPEN.
        _sym_u = str(winner.get("symbol") or "").upper().strip()
        _MAJOR_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        if _sym_u in _MAJOR_SYMBOLS and liq_safety < 0.50:
            # #region agent log
            try:
                import json as _jmod; open("/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log","a").write(_jmod.dumps({"sessionId":"53deb7","hypothesisId":"btc_liq","location":"orchestrator_worker.py:LIQ_SAFETY_FLOOR","message":"major symbol liq_safety floor applied","data":{"symbol":_sym_u,"original_liq_safety":round(liq_safety,4),"liq_dist":liq_dist,"new_liq_safety":0.50},"timestamp":__import__('time').time()*1000})+"\n")
            except Exception:
                pass
            # #endregion
            liq_safety = 0.50

        liq_penalty = 0.5 if bool(winner.get("liquidity_soft_block") or winner.get("liquidity_soft_throttle")) else 1.0
        dq_factor = max(0.0, min(1.0, float(dq_score or 0.0)))

        # ── P5: Cluster Density-Weighted Sizing (Mar 2026) ──
        # cluster_pressure = nearby_cluster_strength / daily_volume
        # cluster_scale = 1.0 / (1 + cluster_pressure * leverage / ref_leverage)
        _cluster_scale = 1.0
        try:
            from config import ENABLE_LIQ_CLUSTER_SIZING
            if ENABLE_LIQ_CLUSTER_SIZING and self.redis:
                _cs_sym = _sym_u
                _cs_long_str = self._extract_metric(winner, ["liquidation_long_strength", "liq_long_strength"])
                _cs_short_str = self._extract_metric(winner, ["liquidation_short_strength", "liq_short_strength"])
                if _cs_long_str is None or _cs_short_str is None:
                    try:
                        _cs_long_str = float(self.redis.hget(f"unified_features:{_cs_sym}:5m", "liquidation_long_strength") or 0)
                        _cs_short_str = float(self.redis.hget(f"unified_features:{_cs_sym}:5m", "liquidation_short_strength") or 0)
                    except Exception:
                        _cs_long_str = _cs_long_str or 0
                        _cs_short_str = _cs_short_str or 0
                _cs_nearby_strength = float(_cs_long_str or 0) + float(_cs_short_str or 0)
                # Get adaptive proximity window from NATR
                _cs_natr = 0.005
                try:
                    _cs_natr_raw = self.redis.hget(f"unified_features:{_cs_sym}:1h", "ind_ta_NATR_14_1h")
                    if _cs_natr_raw:
                        _cs_natr = max(0.001, float(_cs_natr_raw) / 100.0)
                except Exception:
                    pass
                # Estimate daily volume from 5m candle volume
                _cs_vol = 0.0
                try:
                    _cs_vol_raw = self.redis.hget(f"unified_features:{_cs_sym}:5m", "ccxt_volume")
                    if _cs_vol_raw:
                        _cs_close_raw = self.redis.hget(f"unified_features:{_cs_sym}:5m", "ccxt_close")
                        _cs_close = float(_cs_close_raw) if _cs_close_raw else 1.0
                        _cs_vol = float(_cs_vol_raw) * _cs_close * 288  # 5m candles per day
                except Exception:
                    pass
                _cs_daily_vol = max(_cs_vol, 1_000_000)  # floor at $1M
                _cs_pressure = _cs_nearby_strength / _cs_daily_vol
                _cs_leverage = float(winner.get("leverage") or 20)
                _cluster_scale = 1.0 / (1.0 + _cs_pressure * _cs_leverage / 20.0)
                _cluster_scale = max(0.2, min(1.0, _cluster_scale))
                if _cluster_scale < 0.95:
                    logger.info(
                        "LIQ_CLUSTER_SIZING | sym=%s | cluster_scale=%.3f | "
                        "nearby_str=%.0f daily_vol=%.0f pressure=%.6f lev=%.0f",
                        _cs_sym, _cluster_scale, _cs_nearby_strength,
                        _cs_daily_vol, _cs_pressure, _cs_leverage,
                    )
                    proof.setdefault("cluster_sizing", {
                        "scale": round(_cluster_scale, 4),
                        "nearby_strength": round(_cs_nearby_strength, 2),
                        "daily_vol": round(_cs_daily_vol, 2),
                        "pressure": round(_cs_pressure, 6),
                    })
        except ImportError:
            pass
        except Exception as _cs_err:
            logger.debug("LIQ_CLUSTER_SIZING_ERR | %s", _cs_err)

        try:
            from config import PORTFOLIO_TIER_BASE_SYMBOL_PCT, MIN_OPEN_MARGIN_USD
        except Exception:
            PORTFOLIO_TIER_BASE_SYMBOL_PCT = {0: 0.03, 1: 0.05, 2: 0.06}
            MIN_OPEN_MARGIN_USD = 10.0

        tier_idx = int(tier) if tier is not None else 1
        base_symbol_pct = float(PORTFOLIO_TIER_BASE_SYMBOL_PCT.get(tier_idx, 0.05) or 0.05)

        equity = 0.0
        margin_util = 0.0
        if isinstance(portfolio, dict):
            try:
                equity = float(portfolio.get("equity") or 0.0)
            except Exception:
                equity = 0.0
            try:
                margin_util = float(portfolio.get("margin_util") or 0.0)
            except Exception:
                margin_util = 0.0

        # ── Respect Trainer Margin Mode (Mar 2026) ──
        # The trainer already computes confidence-scaled dynamic margins via
        # OPEN_RISK_SIZING_APPLIED. The orchestrator should NOT recalculate from
        # scratch (which over-dampens via multiplicative quality factors to ~$30).
        # Instead: use trainer's margin as base, apply only safety dampening + hard caps.
        try:
            _respect_trainer = bool(getattr(config, "ORCH_RESPECT_TRAINER_MARGIN", True))
        except Exception:
            _respect_trainer = True

        if _respect_trainer and current_margin > 0:
            # Safety dampening: only apply liq_penalty and cluster_scale (not quality/dq which
            # the trainer already factored into confidence). Floor at 60% to prevent crush.
            safety_scale = max(0.60, float(liq_penalty) * float(_cluster_scale))
            desired = current_margin * safety_scale
            # Equity-based floor: ensure at least base_symbol_pct * equity * 0.30
            equity_floor = equity * base_symbol_pct * 0.30 if equity > 0 else 0.0
            desired = max(desired, equity_floor)
        else:
            # Legacy mode: full recalculation (kept for backward compat)
            desired = equity * base_symbol_pct * quality * dq_factor * liq_safety * liq_penalty * _cluster_scale

        try:
            max_total_pct = float(getattr(config, "MAX_TOTAL_MARGIN_PCT_EQUITY", 0.50))
        except Exception:
            max_total_pct = 0.50
        try:
            max_per_symbol_pct = float(getattr(config, "MAX_MARGIN_PER_SYMBOL_PCT_EQUITY", 0.05))
        except Exception:
            max_per_symbol_pct = 0.05

        if isinstance(proof.get("portfolio_tier_caps"), dict):
            caps = proof.get("portfolio_tier_caps")
            try:
                max_total_pct = float(caps.get("max_mu") or max_total_pct)
            except Exception:
                pass
            try:
                max_per_symbol_pct = float(caps.get("per_pos_margin_pct") or max_per_symbol_pct)
            except Exception:
                pass

        cap_total_margin = max_total_pct * equity if equity > 0 else None
        cap_symbol_margin = max_per_symbol_pct * equity if equity > 0 else None
        remaining_cap = (cap_total_margin - (margin_util * equity)) if (cap_total_margin is not None and equity > 0) else None

        desired = max(float(MIN_OPEN_MARGIN_USD or 0.0), float(desired or 0.0))
        if cap_symbol_margin is not None and cap_symbol_margin > 0:
            desired = min(desired, cap_symbol_margin)
        if remaining_cap is not None and remaining_cap > 0:
            desired = min(desired, remaining_cap)

        if abs(desired - current_margin) < 0.01:
            return

        winner["margin_usd"] = round(desired, 4)
        try:
            leverage = float(winner.get("leverage") or 1.0)
        except Exception:
            leverage = 1.0
        if leverage <= 0:
            leverage = 1.0
        winner["notional_usd"] = round(desired * leverage, 4)
        proof["dynamic_sizing"] = {
            "applied": True,
            "quality": round(quality, 4),
            "liq_safety": round(liq_safety, 4),
            "dq_factor": round(dq_factor, 4),
            "liq_penalty": round(liq_penalty, 4),
            "cluster_scale": round(_cluster_scale, 4),
            "prev_margin_usd": round(current_margin, 4),
            "new_margin_usd": round(desired, 4),
            "toxicity": tox,
            "liq_dist": liq_dist,
            "ob_depth_usd": ob_depth,
            "volatility": vol,
            "tier": tier_idx,
        }

    def _score_candidate_open(self, signal: Dict[str, Any]) -> float:
        return self._score_candidate_open_static(signal, self._rotation_policy)

    def _score_keep_position(self, pos: Dict[str, Any]) -> float:
        return self._score_keep_position_static(pos)

    def _rotation_eligible(self, signal: Dict[str, Any]) -> Tuple[bool, str]:
        policy = self._rotation_policy
        confidence = float(signal.get("confidence") or signal.get("model_confidence") or 0.0)
        liq_dist = float(signal.get("liq_distance_pct") or 0.0)
        dq_conf = float(signal.get("dq_confidence") or 0.0)
        dq_fallback = bool(signal.get("dq_fallback_used"))
        liquidity_soft = bool(signal.get("liquidity_soft_block")) or bool(signal.get("liquidity_soft_throttle"))
        tox = self._extract_metric(signal, ["toxicity", "tox"])
        ob_depth = self._extract_metric(signal, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])
        dq_score = self._extract_metric(signal, ["dq_score"]) or 0.0
        hold_sec = self._extract_metric(signal, ["hold_sec", "min_hold_sec", "age_sec"])
        drawdown = self._extract_metric(signal, ["drawdown_pct", "dd_pct", "drawdown"])
        dq_missing = []
        meta_blob = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
        for src in (signal.get("dq_missing_fields"), meta_blob.get("dq_missing_fields")):
            if isinstance(src, list):
                dq_missing.extend([str(x) for x in src])
        dq_missing = list(dict.fromkeys(dq_missing))

        _static_min_conf = float(policy.get("min_candidate_confidence", 0.90))
        _sym = str(signal.get("symbol") or "").upper()
        _dyn_min_conf = self._dynamic_value(_sym, 0.70, _static_min_conf) if _sym else _static_min_conf
        if confidence < _dyn_min_conf:
            return False, "CONFIDENCE_BELOW_MIN"
        if liq_dist > 0 and liq_dist < float(policy.get("min_liq_distance_pct", 0.0)):
            return False, "LIQ_DISTANCE_BELOW_MIN"
        if dq_fallback and dq_conf < float(policy.get("dq_min_confidence", 0.0)):
            return False, "DQ_CONFIDENCE_TOO_LOW"
        if dq_score and dq_score < 0.8:
            return False, "DQ_SCORE_TOO_LOW"
        required_fields = policy.get("dq_required_fields") or []
        missing_required = [f for f in required_fields if f in dq_missing]
        if missing_required:
            return False, "DQ_MISSING_FIELDS"
        if signal.get("dq_source_ok") is False or meta_blob.get("dq_source_ok") is False:
            return False, "DQ_SOURCE_NOT_OK"
        now_ms = int(time.time() * 1000)
        ob_age = self._extract_metric(signal, ["dq_orderbook_age_ms", "orderbook_age_ms"])
        if ob_age is None:
            ob_ts = self._extract_metric(signal, ["orderbook_ts_ms"])
            if ob_ts:
                try:
                    ob_age = float(now_ms - float(ob_ts))
                except Exception:
                    ob_age = None
        if ob_age is not None and float(policy.get("dq_max_orderbook_age_ms", 0.0)) > 0:
            if float(ob_age) > float(policy.get("dq_max_orderbook_age_ms")):
                return False, "DQ_ORDERBOOK_STALE"

        lm_age = self._extract_metric(signal, ["dq_liqmap_age_ms"])
        if lm_age is None:
            lm_ts = self._extract_metric(signal, ["liqmap_ts_ms"])
            if lm_ts:
                try:
                    lm_age = float(now_ms - float(lm_ts))
                except Exception:
                    lm_age = None
        if lm_age is not None and float(policy.get("dq_max_liqmap_age_ms", 0.0)) > 0:
            if float(lm_age) > float(policy.get("dq_max_liqmap_age_ms")):
                return False, "DQ_LIQMAP_STALE"

        vol_age = self._extract_metric(signal, ["dq_volatility_age_ms", "volatility_age_ms"])
        if vol_age is None:
            vol_ts = self._extract_metric(signal, ["volatility_ts_ms"])
            if vol_ts:
                try:
                    vol_age = float(now_ms - float(vol_ts))
                except Exception:
                    vol_age = None
        if vol_age is not None and float(policy.get("dq_max_vol_age_ms", 0.0)) > 0:
            if float(vol_age) > float(policy.get("dq_max_vol_age_ms")):
                return False, "DQ_VOL_STALE"
        if liquidity_soft:
            return False, "LIQUIDITY_SOFT_BLOCK"
        if tox is not None and tox > float(policy.get("block_if_tox_gt", 1.0)):
            return False, "TOXICITY_BLOCK"
        if ob_depth is not None and ob_depth < float(policy.get("block_if_ob_lt", 0.0)):
            return False, "ORDERBOOK_BLOCK"
        if hold_sec is not None and hold_sec < float(policy.get("min_hold_sec", 0.0)):
            return False, "MIN_HOLD_NOT_MET"
        if drawdown is not None and drawdown > float(policy.get("allow_if_drawdown_lt", 999.0)):
            return False, "DRAWDOWN_BLOCK"
        return True, "OK"

    def _get_open_positions(self, account_id: str) -> List[Dict[str, Any]]:
        positions = []
        now_ms = int(time.time() * 1000)

        # Prefer authoritative live positions
        try:
            live_symbols = list(self.redis.smembers(f"positions:live:symbols:{account_id}") or []) if self.redis else []
        except Exception:
            live_symbols = []

        if live_symbols:
            for sym in live_symbols:
                try:
                    sym_u = sym.decode("utf-8", errors="ignore") if isinstance(sym, (bytes, bytearray)) else str(sym)
                    raw_live = self.redis.hgetall(f"positions:live:{account_id}:{sym_u}") or {}
                    if not raw_live:
                        continue
                    def _get(v):
                        return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                    side = _get(raw_live.get(b"side") or raw_live.get("side") or "")
                    try:
                        amt = float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0))
                    except Exception:
                        amt = 0.0
                    if abs(amt) <= 0.0:
                        continue
                    try:
                        margin = float(_get(raw_live.get(b"initial_margin_usd") or raw_live.get("initial_margin_usd") or 0.0))
                    except Exception:
                        margin = 0.0
                    try:
                        notional = float(_get(raw_live.get(b"notional_usd") or raw_live.get("notional_usd") or 0.0))
                    except Exception:
                        notional = 0.0
                    try:
                        roe = float(_get(raw_live.get(b"roe_pct") or raw_live.get("roe_pct") or 0.0))
                    except Exception:
                        roe = 0.0
                    try:
                        upnl = float(_get(raw_live.get(b"unrealized_pnl_usd") or raw_live.get("unrealized_pnl_usd") or 0.0))
                    except Exception:
                        upnl = 0.0
                    try:
                        updated_ts = int(_get(raw_live.get(b"updated_ts_ms") or raw_live.get("updated_ts_ms") or 0))
                    except Exception:
                        updated_ts = 0
                    age_sec = max(0.0, (now_ms - updated_ts) / 1000.0) if updated_ts else None
                    pnl_pct = roe
                    drawdown_pct = max(0.0, -float(roe)) if roe is not None else None

                    positions.append(
                        {
                            "symbol": sym_u.upper(),
                            "side": str(side or "").upper(),
                            "margin_used_usd": abs(margin),
                            "notional_usd": abs(notional),
                            "unrealized_pnl_pct": pnl_pct,
                            "drawdown_pct": drawdown_pct,
                            "opened_ts_ms": None,
                            "last_action_ts_ms": updated_ts,
                            "age_sec": age_sec,
                            "unrealized_pnl_usd": upnl,
                        }
                    )
                except Exception:
                    continue

        if positions:
            logger.info(f"ORCH_POS_SNAPSHOT count={len(positions)} acct={account_id} source=positions_live")
            return positions

        try:
            raw = self.redis.hgetall(f"portfolio:positions:{account_id}") or {}
        except Exception:
            raw = {}
        for field, val in (raw or {}).items():
            try:
                f = str(field)
                if ":" not in f:
                    continue
                sym, side = f.split(":", 1)
                sym = str(sym).upper().strip()
                side_u = str(side).upper().strip()
                if not sym:
                    continue

                if isinstance(val, str):
                    d = json.loads(val) if val and val.lstrip().startswith("{") else {}
                else:
                    d = val if isinstance(val, dict) else {}

                margin = float(d.get("margin_used", 0.0) or d.get("initialMargin", 0.0) or d.get("initial_margin", 0.0) or 0.0)
                notional = float(d.get("notional", 0.0) or d.get("notional_usd", 0.0) or d.get("positionNotional", 0.0) or 0.0)
                size = float(d.get("size", 0.0) or d.get("positionAmt", 0.0) or d.get("qty", 0.0) or 0.0)
                if abs(size) <= 0.0:
                    continue

                pnl_pct = d.get("unrealized_pnl_pct")
                if pnl_pct is None:
                    pnl_pct = d.get("roe") or d.get("pnl_pct")
                try:
                    pnl_pct = float(pnl_pct) if pnl_pct is not None else None
                except Exception:
                    pnl_pct = None

                drawdown_pct = d.get("drawdown_pct") or d.get("dd_pct")
                try:
                    drawdown_pct = float(drawdown_pct) if drawdown_pct is not None else None
                except Exception:
                    drawdown_pct = None

                opened_ts = d.get("opened_ts_ms") or d.get("opened_ts") or d.get("open_ts_ms")
                last_action_ts = d.get("last_action_ts_ms") or d.get("last_update_ts_ms") or d.get("updated_ts_ms")
                try:
                    opened_ts = int(opened_ts) if opened_ts is not None else None
                except Exception:
                    opened_ts = None
                try:
                    last_action_ts = int(last_action_ts) if last_action_ts is not None else None
                except Exception:
                    last_action_ts = None
                age_sec = None
                if opened_ts:
                    age_sec = max(0.0, (now_ms - opened_ts) / 1000.0)

                positions.append(
                    {
                        "symbol": sym,
                        "side": "LONG" if "LONG" in side_u else ("SHORT" if "SHORT" in side_u else ""),
                        "margin_used_usd": abs(margin),
                        "notional_usd": abs(notional),
                        "unrealized_pnl_pct": pnl_pct,
                        "drawdown_pct": drawdown_pct,
                        "opened_ts_ms": opened_ts,
                        "last_action_ts_ms": last_action_ts,
                        "age_sec": age_sec,
                    }
                )
            except Exception:
                continue

        logger.info(f"ORCH_POS_SNAPSHOT count={len(positions)} acct={account_id} source=portfolio_hash")
        return positions

    def _rotation_cooldown_ok(self, account_id: str, symbol: str, now_ms: int) -> Tuple[bool, str]:
        policy = self._rotation_policy
        if not self.redis:
            return True, "OK"
        try:
            global_key = "orch:rotation:last_ts"
            per_key = f"orch:rotation:last_ts:{account_id}:{symbol}"
            last_global = self.redis.get(global_key)
            last_symbol = self.redis.get(per_key)
            last_global_ms = int(last_global) if last_global else 0
            last_symbol_ms = int(last_symbol) if last_symbol else 0
        except Exception:
            last_global_ms = 0
            last_symbol_ms = 0

        if last_global_ms and (now_ms - last_global_ms) < int(policy.get("global_cooldown_sec", 0)) * 1000:
            return False, "GLOBAL_COOLDOWN"
        if last_symbol_ms and (now_ms - last_symbol_ms) < int(policy.get("per_symbol_cooldown_sec", 0)) * 1000:
            return False, "PER_SYMBOL_COOLDOWN"
        return True, "OK"

    def _attempt_rotation(self, account_id: str, candidate: Dict[str, Any], ramp_meta: Dict[str, Any]) -> bool:
        policy = self._rotation_policy
        if not policy.get("enabled", False):
            return False

        ok, reason = self._rotation_eligible(candidate)
        if not ok:
            logger.info(f"ORCH_ROT_REJECT | reason={reason} | account={account_id} | symbol={candidate.get('symbol')}")
            return False

        now_ms = int(time.time() * 1000)
        cool_ok, cool_reason = self._rotation_cooldown_ok(account_id, str(candidate.get("symbol") or ""), now_ms)
        if not cool_ok:
            logger.info(f"ORCH_ROT_REJECT | reason={cool_reason} | account={account_id} | symbol={candidate.get('symbol')}")
            return False

        positions = self._get_open_positions(account_id)
        if not positions:
            return False

        bucket_counts: Dict[str, int] = {}
        for p in positions:
            b = self._symbol_bucket(p.get("symbol") or "")
            bucket_counts[b] = bucket_counts.get(b, 0) + 1

        for p in positions:
            base = self._score_keep_position(p)
            cost_penalty = self._get_cost_penalty(account_id, p.get("symbol"))
            b = self._symbol_bucket(p.get("symbol") or "")
            corr_penalty = max(0.0, float(bucket_counts.get(b, 1) - 1) * 0.05)
            p["keep_score"] = float(base) - float(cost_penalty) - float(corr_penalty)
            p["cost_penalty"] = cost_penalty
            p["corr_penalty"] = corr_penalty

        positions.sort(key=lambda x: x.get("keep_score", 0.0))
        loser = positions[0]
        loser_score = float(loser.get("keep_score") or 0.0)
        candidate_score = float(self._score_candidate_open(candidate))
        candidate_cost_penalty = self._get_cost_penalty(account_id, candidate.get("symbol"))
        cand_bucket = self._symbol_bucket(candidate.get("symbol") or "")
        cand_corr_penalty = max(0.0, float(bucket_counts.get(cand_bucket, 0)) * 0.05)
        candidate_score = float(candidate_score) - float(candidate_cost_penalty) - float(cand_corr_penalty)

        logger.info(
            "ORCH_ROT_SCORE | account=%s | candidate=%s | cand_score=%.4f | loser=%s | loser_score=%.4f",
            account_id,
            candidate.get("symbol"),
            candidate_score,
            loser.get("symbol"),
            loser_score,
        )

        threshold = float(policy.get("swap_improvement_threshold", 0.0))
        if candidate_score <= (loser_score + threshold):
            logger.info(
                "ORCH_ROT_REJECT | reason=BELOW_THRESHOLD | account=%s | candidate=%s | cand_score=%.4f | loser=%s | loser_score=%.4f | threshold=%.4f",
                account_id,
                candidate.get("symbol"),
                candidate_score,
                loser.get("symbol"),
                loser_score,
                threshold,
            )
            return False

        # No-loss and winner protection
        pnl_pct = loser.get("unrealized_pnl_pct")
        try:
            pnl_pct = float(pnl_pct) if pnl_pct is not None else None
        except Exception:
            pnl_pct = None
        if policy.get("no_loss_only", True):
            loss_tol = float(policy.get("loss_tolerance_pct", 0.0))
            if pnl_pct is not None and pnl_pct < -abs(loss_tol):
                logger.info(
                    "ORCH_ROT_BLOCK_NOLOSS | account=%s | loser=%s | pnl_pct=%.4f",
                    account_id,
                    loser.get("symbol"),
                    pnl_pct,
                )
                return False
        winner_protect = float(policy.get("winner_protect_pnl_pct", 0.0))
        if pnl_pct is not None and pnl_pct >= winner_protect:
            override_margin = float(policy.get("winner_override_margin", 0.0))
            if candidate_score < (loser_score + threshold + override_margin):
                logger.info(
                    "ORCH_ROT_BLOCK_WINNER_PROTECT | account=%s | loser=%s | pnl_pct=%.4f",
                    account_id,
                    loser.get("symbol"),
                    pnl_pct,
                )
                return False

        # Trainer alignment: check if trainer wants to keep the loser position
        try:
            _rot_sym = str(loser.get("symbol") or "")
            if self.redis and _rot_sym:
                _rot_pred = self.redis.hgetall(f"prediction:{_rot_sym}:multi")
                if _rot_pred:
                    _rp = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _rot_pred.items()}
                    _rp_dir = str(_rp.get("direction", "")).upper()
                    _rp_conf = float(_rp.get("confidence", _rp.get("model_confidence", 0)) or 0)
                    _loser_side = str(loser.get("side") or "").upper()
                    _trainer_aligned = (
                        (_loser_side == "LONG" and _rp_dir == "LONG") or
                        (_loser_side == "SHORT" and _rp_dir == "SHORT")
                    )
                    _rot_conf_thr = self._dynamic_threshold(str(_rot_sym or ""), 0.60, 0.80)
                    if _trainer_aligned and _rp_conf >= _rot_conf_thr:
                        logger.info(
                            "ORCH_ROT_BLOCK_TRAINER_ALIGNED | account=%s | loser=%s | side=%s | trainer_dir=%s | trainer_conf=%.3f",
                            account_id, _rot_sym, _loser_side, _rp_dir, _rp_conf,
                        )
                        return False
        except Exception:
            pass

        # Publish rotation close/reduce
        reduce_mode = bool(policy.get("reduce_instead_of_close", False))
        reduce_fraction = float(policy.get("reduce_fraction", 0.25))
        reduce_fraction = max(0.05, min(0.75, reduce_fraction))

        loser_side = str(loser.get("side") or "").upper()
        if reduce_mode:
            action = f"REDUCE_{loser_side}" if loser_side else "REDUCE"
        else:
            action = f"CLOSE_{loser_side}" if loser_side else "CLOSE_ALL"

        rotation_id = f"rot_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        close_signal = {
            "account_id": account_id,
            "symbol": loser.get("symbol"),
            "action": action,
            "action_name": action,
            "action_category": "REDUCE" if reduce_mode else "CLOSE",
            "reduce_only": True,
            "close_fraction": reduce_fraction if reduce_mode else 1.0,
            "confidence": 1.0,
            "source": "orchestrator_rotation",
            "source_module": "orchestrator_rotation",
            "proposal_id": rotation_id,
            "signal_id": rotation_id,
            "timeframe": candidate.get("timeframe") or (candidate.get("metadata") or {}).get("timeframe") or "rotation",
            "metadata": {
                "rotation": True,
                "rotation_reason": "RAMP_LIMIT_SWAP",
                "rotation_candidate_symbol": candidate.get("symbol"),
                "rotation_candidate_score": candidate_score,
                "rotation_loser_score": loser_score,
            },
        }

        plan_id = self._publish_winner(close_signal, {"rotation": True})
        if not plan_id:
            logger.info("ORCH_ROT_REJECT | reason=CLOSE_PUBLISH_FAIL | account=%s | loser=%s", account_id, loser.get("symbol"))
            return False

        pending = {
            "account_id": account_id,
            "candidate": candidate,
            "loser_symbol": loser.get("symbol"),
            "loser_side": loser_side,
            "loser_margin_usd": loser.get("margin_used_usd"),
            "reduce_mode": reduce_mode,
            "reduce_fraction": reduce_fraction,
            "candidate_score": candidate_score,
            "loser_score": loser_score,
            "created_ts_ms": now_ms,
            "attempts": 0,
        }

        if self.redis:
            try:
                self.redis.setex(
                    f"orch:rotation:pending:{account_id}",
                    int(policy.get("pending_timeout_sec", 90)),
                    json.dumps(pending, separators=(",", ":")),
                )
                self.redis.set("orch:rotation:last_ts", str(now_ms))
                self.redis.set(f"orch:rotation:last_ts:{account_id}:{candidate.get('symbol')}", str(now_ms))
            except Exception:
                pass

        logger.info(
            "ORCH_ROT_ACCEPT | account=%s | loser=%s | candidate=%s | cand_score=%.4f | loser_score=%.4f",
            account_id,
            loser.get("symbol"),
            candidate.get("symbol"),
            candidate_score,
            loser_score,
        )
        return True

    def _process_pending_rotations(self, now_ms: int) -> None:
        if not self.redis:
            return
        policy = self._rotation_policy
        try:
            keys = list(self.redis.scan_iter(match="orch:rotation:pending:*", count=20))
        except Exception:
            keys = []
        for key in keys:
            try:
                raw = self.redis.get(key)
                if not raw:
                    continue
                pending = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                if not isinstance(pending, dict):
                    self.redis.delete(key)
                    continue

                created_ts = int(pending.get("created_ts_ms") or 0)
                if created_ts and (now_ms - created_ts) > int(policy.get("pending_timeout_sec", 90)) * 1000:
                    logger.info("ORCH_ROT_TIMEOUT | key=%s", key)
                    self.redis.delete(key)
                    continue

                account_id = str(pending.get("account_id") or "primary")
                loser_symbol = str(pending.get("loser_symbol") or "").upper()
                reduce_mode = bool(pending.get("reduce_mode"))
                reduce_fraction = float(pending.get("reduce_fraction") or 0.0)
                base_margin = pending.get("loser_margin_usd")
                try:
                    base_margin = float(base_margin) if base_margin is not None else None
                except Exception:
                    base_margin = None

                positions = self._get_open_positions(account_id)
                loser_pos = next((p for p in positions if str(p.get("symbol")).upper() == loser_symbol), None)

                can_open = False
                if not loser_pos:
                    can_open = True
                elif reduce_mode and base_margin:
                    cur_margin = float(loser_pos.get("margin_used_usd") or 0.0)
                    target_margin = base_margin * (1.0 - reduce_fraction + 0.05)
                    if cur_margin <= target_margin:
                        can_open = True

                if not can_open:
                    continue

                candidate = pending.get("candidate") or {}
                attempts = int(pending.get("attempts") or 0) + 1
                pending["attempts"] = attempts
                if attempts > int(policy.get("pending_max_attempts", 3)):
                    logger.info("ORCH_ROT_TIMEOUT | key=%s | reason=MAX_ATTEMPTS", key)
                    self.redis.delete(key)
                    continue

                try:
                    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                    meta["rotation"] = True
                    meta["rotation_reason"] = "RAMP_LIMIT_SWAP"
                    candidate["metadata"] = meta
                    candidate["rotation_pending"] = False
                except Exception:
                    pass

                plan_id = self._publish_winner(candidate, {"rotation": True})
                if plan_id:
                    logger.info("ORCH_ROT_EXEC_OPEN | account=%s | symbol=%s", account_id, candidate.get("symbol"))
                    self.redis.delete(key)
                else:
                    self.redis.setex(
                        key,
                        int(policy.get("pending_timeout_sec", 90)),
                        json.dumps(pending, separators=(",", ":")),
                    )
            except Exception:
                try:
                    self.redis.delete(key)
                except Exception:
                    pass
    
    def _ensure_consumer_group(self):
        """Create consumer group if it doesn't exist."""
        try:
            self.redis.xgroup_create(
                PROPOSAL_STREAM,
                CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
            logger.info(f"✅ Created consumer group {CONSUMER_GROUP} on {PROPOSAL_STREAM}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"Consumer group {CONSUMER_GROUP} already exists")
            else:
                raise
    
    def run(self):
        """Main loop: consume proposals, arbitrate, publish."""
        logger.info(
            f"🚀 Orchestrator Worker starting | "
            f"shadow={self.shadow_mode} | "
            f"window_ms={self.micro_window_ms} | "
            f"cooldown_ms={self.cooldown_horizon_ms}"
        )
        
        last_flush_ts = time.time() * 1000
        
        while self.running:
            try:
                # Read proposals with blocking (up to micro_window_ms)
                messages = self.redis.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {PROPOSAL_STREAM: ">"},
                    count=100,
                    block=self.micro_window_ms,
                )
                
                now_ms = int(time.time() * 1000)
                
                # Process received proposals
                if messages:
                    for stream_name, stream_messages in messages:
                        for msg_id, msg_data in stream_messages:
                            self._process_proposal(msg_id, msg_data)
                            # ACK the message
                            self.redis.xack(PROPOSAL_STREAM, CONSUMER_GROUP, msg_id)
                
                # Check for windows to flush (micro-window elapsed)
                self._flush_ready_windows(now_ms)
                
                # Clean up old published plans (beyond cooldown horizon)
                self._cleanup_old_plans(now_ms)

                # Process pending rotations (close -> open sequencing)
                self._process_pending_rotations(now_ms)

                # Consume trader execution feedback to suppress repeated impossible adds.
                self._consume_execution_feedback(now_ms)
                
                # Clear dedupe keys periodically
                if now_ms - last_flush_ts > 60000:  # Every 60s
                    self.seen_dedupe_keys.clear()
                    last_flush_ts = now_ms

                # Liveness heartbeat + pending checks
                self._maybe_emit_orch_heartbeat(now_ms)
                self._check_orchestrator_liveness(now_ms)
                
            except (KeyboardInterrupt, SystemExit) as e:
                logger.warning(f"Worker received exit signal: {type(e).__name__}: {e}")
                self.running = False
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")
                time.sleep(1)
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("Orchestrator Worker stopped")

    def _maybe_emit_orch_heartbeat(self, now_ms: int) -> None:
        if now_ms - self._last_orch_heartbeat_ms < int(self.liveness_check_sec * 1000):
            return
        self._last_orch_heartbeat_ms = now_ms
        # D3: Write simple Redis key so external watchdogs can detect staleness
        try:
            self.redis.set("orchestrator:heartbeat_ms", str(now_ms), ex=120)
        except Exception:
            pass
        self._publish_exec_event(
            code="ORCH_HEARTBEAT",
            account_id="system",
            symbol="SYSTEM",
            action="HEARTBEAT",
            meta={"stream": PROPOSAL_STREAM, "consumer": CONSUMER_NAME},
        )

    def _check_orchestrator_liveness(self, now_ms: int) -> None:
        if now_ms - self._last_liveness_check_ms < int(self.liveness_check_sec * 1000):
            return
        self._last_liveness_check_ms = now_ms

        if not self.redis:
            return

        try:
            pending_summary = self.redis.xpending(PROPOSAL_STREAM, CONSUMER_GROUP)
            pending_count = int(pending_summary.get("pending", 0)) if isinstance(pending_summary, dict) else int(pending_summary[0])
        except Exception:
            pending_count = 0

        oldest_idle_ms = 0
        if pending_count > 0:
            try:
                entries = self.redis.xpending_range(
                    PROPOSAL_STREAM,
                    CONSUMER_GROUP,
                    min="-",
                    max="+",
                    count=1,
                )
                if entries:
                    entry = entries[0]
                    oldest_idle_ms = int(entry.get("time_since_delivered", 0) if isinstance(entry, dict) else entry[2])
            except Exception:
                oldest_idle_ms = 0

        stalled = bool(pending_count > 0 and oldest_idle_ms >= self.pending_stall_ms)
        if stalled:
            self._orch_stall_hits += 1
        else:
            self._orch_stall_hits = 0

        if stalled and self._orch_stall_hits >= 2:
            try:
                set_kill_switch(
                    self.redis,
                    scope="GLOBAL",
                    code="ORCH_STALLED",
                    details={
                        "pending": pending_count,
                        "oldest_idle_ms": oldest_idle_ms,
                        "stream": PROPOSAL_STREAM,
                        "consumer": CONSUMER_NAME,
                    },
                )
            except Exception:
                pass

            self._publish_exec_event(
                code="ORCH_STALLED",
                account_id="system",
                symbol="SYSTEM",
                action="HALT_OPEN_RISK",
                meta={
                    "pending": pending_count,
                    "oldest_idle_ms": oldest_idle_ms,
                    "stream": PROPOSAL_STREAM,
                    "consumer": CONSUMER_NAME,
                },
            )

            if self._telegram:
                try:
                    payload = {
                        "tg_kind": "SYSTEM_ALERT",
                        "alert_kind": "ORCH_STALLED",
                        "message": f"pending={pending_count} oldest_idle_ms={oldest_idle_ms}",
                        "env": os.getenv("ENV", "LIVE"),
                        "account": "system",
                        "ts_utc": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
                        "portfolio_mode": "ORCH",
                        "engine": "orchestrator_worker",
                        "intent": "ORCH_LIVENESS",
                        "regime": "UNKNOWN",
                        "symbol": "SYSTEM",
                        "action": "ORCH_STALLED",
                        "side": "NA",
                        "reduce_only": True,
                        "is_risk_add": 0,
                        "is_reduce": 1,
                    }
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self._telegram.send_tg("SYSTEM_ALERT", payload))
                    loop.close()
                except Exception:
                    pass
    
    def _process_proposal(self, msg_id: str, msg_data: Dict[str, Any]):
        """Process a single proposal from the stream."""
        self.stats["proposals_received"] += 1
        
        try:
            # Parse proposal data
            raw_data = msg_data.get(b"data") or msg_data.get("data") or "{}"
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            
            proposal = json.loads(raw_data)
            
            # Validate required fields
            account_id = str(proposal.get("account_id") or "").strip().lower()
            symbol = str(proposal.get("symbol") or "").strip().upper()
            action = str(proposal.get("action") or "").strip().upper()
            source = str(proposal.get("source_module") or proposal.get("source") or "unknown")
            source_module = str(proposal.get("source_module") or "").strip().lower()
            producer = str(proposal.get("producer") or "").strip().lower()
            
            if not account_id or not symbol or not action:
                logger.warning(f"Invalid proposal (missing fields): {proposal}")
                return


            # Standby account routing: keep asjad quiet when explicitly disabled.
            requested_account = account_id
            tf = str(proposal.get("timeframe") or proposal.get("tf") or "").strip().lower()
            decision_id = str(proposal.get("decision_id") or proposal.get("proposal_id") or proposal.get("trace_id") or "")
            if not self._is_account_enabled(account_id):
                if account_id == "asjad" and self._is_risk_add_action(action):
                    account_id = "primary"
                    proposal["account_id"] = "primary"
                    proposal["requested_account_id"] = requested_account
                    logger.info(
                        "ORCH_ACCOUNT_REROUTE | reason=ACCOUNT_DISABLED_ASJAD | requested=%s | selected=%s | symbol=%s | action=%s",
                        requested_account,
                        account_id,
                        symbol,
                        action,
                    )
                    self._emit_account_diag(
                        kind="orch_account_disabled",
                        decision_id=decision_id,
                        symbol=symbol,
                        tf=tf,
                        requested_account=requested_account,
                        selected_account=account_id,
                        reason="ACCOUNT_DISABLED_ASJAD_REROUTE_PRIMARY",
                        reasons_json={"account_disabled": True, "rule": "risk_add_reroute"},
                    )
                else:
                    logger.warning(
                        "ORCH_ACCOUNT_DISABLED_DROP | requested=%s | symbol=%s | action=%s",
                        requested_account,
                        symbol,
                        action,
                    )
                    self._publish_exec_event(
                        code="ACCOUNT_DISABLED_ASJAD",
                        account_id=requested_account,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(proposal.get("proposal_id") or proposal.get("id") or ""),
                        meta={"requested_account": requested_account, "selected_account": "", "reason": "ACCOUNT_DISABLED_ASJAD"},
                    )
                    self._emit_account_diag(
                        kind="orch_account_disabled",
                        decision_id=decision_id,
                        symbol=symbol,
                        tf=tf,
                        requested_account=requested_account,
                        selected_account="",
                        reason="ACCOUNT_DISABLED_ASJAD",
                        reasons_json={"account_disabled": True, "rule": "drop_non_risk_add"},
                    )
                    return

            # Manual-test quarantine (PR-10A)
            manual_test = source_module == "manual_test" or producer == "manual_test"
            allow_manual = os.getenv("ALLOW_MANUAL_TEST", "0").lower() in ("1", "true", "yes", "on")
            if manual_test and not (allow_manual and account_id == "dryrun"):
                logger.warning(
                    f"ORCH_RISK_REJECT | reason=MANUAL_TEST_BLOCKED | account={account_id} | symbol={symbol} | action={action}"
                )
                self._publish_exec_event(
                    code="MANUAL_TEST_BLOCKED",
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(proposal.get("proposal_id") or proposal.get("id") or ""),
                    meta={
                        "reason": "MANUAL_TEST_BLOCKED",
                        "trace_id": proposal.get("trace_id") or "",
                        "source_module": source_module,
                        "producer": producer,
                    },
                )
                return
            
            # Dedupe check
            dedupe_key = proposal.get("dedupe_key") or self._compute_dedupe_key(proposal)
            if dedupe_key in self.seen_dedupe_keys:
                self.stats["proposals_deduped"] += 1
                logger.debug(f"Deduped proposal: {dedupe_key}")
                return
            self.seen_dedupe_keys.add(dedupe_key)
            
            # Add stream metadata
            proposal["_stream_id"] = str(msg_id)
            proposal["_received_ts_ms"] = int(time.time() * 1000)
            
            # Check if CRITICAL priority -> immediate flush
            try:
                priority = int(proposal.get("priority") or 1)
            except Exception:
                priority = 1

            # Hedge churn guard: hedge/protective proposals are only CRITICAL
            # when confidence >= threshold (operator requirement).
            try:
                conf = float(proposal.get("confidence") or proposal.get("model_confidence") or 0.0)
            except Exception:
                conf = 0.0
            is_hedge_like = self._is_hedge_like(proposal)
            if is_hedge_like:
                is_critical = conf >= float(HEDGE_CRITICAL_CONF)
            else:
                is_critical = priority >= 3  # CRITICAL or IMMEDIATE

            # Fast lane: PROTECTIVE/CLOSE_RISK/risk_reducing/urgency=HIGH proposals
            # get a much narrower window (ORCH_FASTLANE_WINDOW_MS, default 50ms).
            # They still co-arbitrate with other proposals arriving in that window.
            _is_fastlane = False
            try:
                if not is_critical and getattr(config, "ORCH_FASTLANE_ENABLED", True):
                    _fl_cat = str(proposal.get("action_category") or proposal.get("category") or "").upper()
                    _fl_urgency = str(proposal.get("urgency") or "").upper()
                    _fl_risk_reducing = bool(proposal.get("risk_reducing"))
                    _fl_categories = getattr(
                        config,
                        "ORCH_FASTLANE_CATEGORIES",
                        {"PROTECTIVE", "CLOSE_RISK", "CLOSE_PROFIT", "HEDGE_TRIM", "RECOVERY"},
                    )
                    _is_fastlane = (
                        _fl_cat in _fl_categories
                        or _fl_risk_reducing
                        or _fl_urgency in ("HIGH", "EMERGENCY")
                    )
                    if _is_fastlane:
                        proposal["_fastlane"] = True
                        logger.debug(
                            "ORCH_FASTLANE_TAGGED | %s:%s %s cat=%s urgency=%s risk_reducing=%s",
                            account_id, symbol, action, _fl_cat, _fl_urgency, _fl_risk_reducing,
                        )
            except Exception:
                pass
            
            key = (account_id, symbol)
            
            if is_critical:
                # Flush immediately for this (account, symbol)
                self.stats["critical_flushes"] += 1
                logger.info(
                    f"⚡ CRITICAL proposal: {account_id}:{symbol} {action} from {source} "
                    f"conf={conf:.3f} hedge_like={is_hedge_like}"
                )
                
                # Add to window and flush immediately
                if key not in self.windows:
                    self.windows[key] = DecisionWindow(
                        window_id=str(uuid.uuid4())[:8],
                        account_id=account_id,
                        symbol=symbol,
                        start_ts_ms=int(time.time() * 1000),
                    )
                self.windows[key].proposals.append(proposal)
                self._flush_window(key)
            else:
                # Add to micro-window for batched arbitration
                now_ms = int(time.time() * 1000)

                if key not in self.windows:
                    self.windows[key] = DecisionWindow(
                        window_id=str(uuid.uuid4())[:8],
                        account_id=account_id,
                        symbol=symbol,
                        start_ts_ms=now_ms,
                    )

                # Escalate to fast lane if ANY proposal in this window is fast-lane eligible
                if _is_fastlane and not self.windows[key].fastlane:
                    self.windows[key].fastlane = True
                    logger.debug(
                        "ORCH_FASTLANE_WINDOW | %s:%s window=%s",
                        account_id, symbol, self.windows[key].window_id,
                    )

                self.windows[key].proposals.append(proposal)

                logger.debug(
                    f"Buffered proposal: {account_id}:{symbol} {action} from {source} "
                    f"(window={self.windows[key].window_id}, count={len(self.windows[key].proposals)}, "
                    f"fastlane={self.windows[key].fastlane})"
                )
        
        except Exception as e:
            logger.error(f"Failed to process proposal: {e}")
    
    def _compute_dedupe_key(self, proposal: Dict[str, Any]) -> str:
        """Compute dedupe key for a proposal."""
        account_id = str(proposal.get("account_id") or "").strip().lower()
        symbol = str(proposal.get("symbol") or "").strip().upper()
        action = str(proposal.get("action") or "").strip().upper()
        side = str(proposal.get("side") or "").strip().upper()
        cycle_id = str(proposal.get("cycle_id") or "")
        
        # Group similar actions
        action_family = action
        if action.startswith("OPEN_HEDGE") or action.startswith("ADD_HEDGE"):
            action_family = "HEDGE_ADD"
        elif "PARTIAL_CLOSE" in action:
            action_family = "PARTIAL_CLOSE"
        elif "CLOSE" in action:
            action_family = "CLOSE"
        elif action.startswith("OPEN_") or action.startswith("INCREASE_"):
            action_family = "OPEN_INCREASE"

        if proposal.get("tf_hedge_disagg"):
            src_tf = str(proposal.get("tf_hedge_source_tf") or "").strip()
            action_family = f"TF_HEDGE_DISAGG_{src_tf}"

        return f"{account_id}:{symbol}:{action_family}:{side}:{cycle_id}"

    def _is_hedge_like(self, proposal: Dict[str, Any]) -> bool:
        """Heuristic: classify hedge/protective proposals for churn guard."""
        try:
            action = str(proposal.get("action") or proposal.get("action_name") or "").upper()
            category = str(proposal.get("action_category") or proposal.get("category") or "").upper()
        except Exception:
            action = ""
            category = ""
        if category in ("HEDGE", "PROTECTIVE", "RECOVERY"):
            return True
        if proposal.get("hedge_intent"):
            return True
        if action.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) or "HEDGE" in action:
            return True
        return False

    def _is_hedge_add_action(self, proposal: Dict[str, Any], action_override: Optional[str] = None) -> bool:
        try:
            action = str(action_override or proposal.get("action") or proposal.get("action_name") or "").upper()
            category = str(proposal.get("action_category") or proposal.get("category") or "").upper()
        except Exception:
            action = ""
            category = ""
        if not action or not self._is_risk_add_action(action):
            return False
        if action.startswith(("OPEN_HEDGE", "ADD_HEDGE", "HEDGE_")) or "HEDGE" in action:
            return True
        hedge_intent = bool(proposal.get("hedge_intent") or proposal.get("risk_intent") == "RECOVERY_HEDGE")
        if action.startswith("INCREASE_") and hedge_intent:
            return True
        if category in {"HEDGE", "RECOVERY"} and hedge_intent:
            return True
        return False

    def _is_risk_add_action(self, action: str) -> bool:
        return bool(is_risk_add_action(action))

    def _is_symbol_allowed(self, symbol: str) -> bool:
        s = str(symbol or "").upper().strip()
        if not s:
            return False
        if not bool(getattr(self, "universe_enforcement_enabled", True)):
            return True
        if not bool(getattr(self, "universe_enforce_orchestrator", True)):
            return True
        allowed = getattr(self, "universe_allowed_symbols", set()) or set()
        return s in allowed

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            out = float(value)
            if out != out:
                return None
            return out
        except Exception:
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(float(value))
        except Exception:
            return None

    def _entry_direction(self, action: str) -> int:
        a = str(action or "").upper().strip()
        if not a:
            return 0
        if "LONG" in a and "SHORT" not in a:
            return 1
        if "SHORT" in a and "LONG" not in a:
            return -1
        return 0

    def _is_open_risk_entry(self, winner: Dict[str, Any], action: str) -> bool:
        act = str(action or "").upper().strip()
        if not self._is_risk_add_action(act):
            return False
        cat = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
        if cat in {"HEDGE", "PROTECTIVE", "RECOVERY", "HEDGE_TRIM", "SYSTEM", "SYSTEM_CANARY"}:
            return False
        if "HEDGE" in act:
            return False
        return cat in {"OPEN_RISK", "OPEN", "ENTRY", ""} and ("OPEN_" in act or "INCREASE_" in act)

    def _extract_with_meta(self, winner: Dict[str, Any], keys: List[str]) -> Any:
        for k in keys:
            if k in winner and winner.get(k) is not None:
                return winner.get(k)
        meta = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        for k in keys:
            if k in meta and meta.get(k) is not None:
                return meta.get(k)
        return None

    def _entry_context_gate(
        self,
        winner: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        if not self.orch_context_gate_enabled:
            return True, None, {}
        if not self._is_open_risk_entry(winner, action):
            return True, None, {}

        direction = self._entry_direction(action)
        meta: Dict[str, Any] = {
            "direction": direction,
            "action": str(action or ""),
            "symbol": str(symbol or ""),
            "account_id": str(account_id or ""),
            "source": str(winner.get("source") or ""),
            "source_module": str(winner.get("source_module") or ""),
        }

        bias_dir = self._safe_int(self._extract_with_meta(winner, ["bias_dir", "tf_bias_dir"]))
        timing_dir = self._safe_int(self._extract_with_meta(winner, ["timing_dir", "tf_timing_dir"]))
        conflict_score = self._safe_float(self._extract_with_meta(winner, ["conflict_score", "tf_conflict_score"]))
        tf_votes = self._extract_with_meta(winner, ["tf_votes"])
        meta.update(
            {
                "bias_dir": bias_dir,
                "timing_dir": timing_dir,
                "conflict_score": conflict_score,
                "tf_votes_present": bool(isinstance(tf_votes, dict) and len(tf_votes) > 0),
            }
        )

        if self.orch_context_gate_require_tf_fields:
            missing = []
            if bias_dir is None:
                missing.append("bias_dir")
            if timing_dir is None:
                missing.append("timing_dir")
            if conflict_score is None:
                missing.append("conflict_score")
            if not isinstance(tf_votes, dict) or len(tf_votes) == 0:
                missing.append("tf_votes")
            if missing:
                meta["missing_fields"] = missing
                return False, "MISSING_TF_CONTEXT", meta

        if timing_dir in (-1, 1) and direction in (-1, 1) and conflict_score is not None:
            if direction != timing_dir and float(conflict_score) >= float(self.orch_context_gate_tf_conflict_threshold):
                _conf_f = float(winner.get("confidence") or winner.get("model_confidence") or 0)
                _w_cat = str(winner.get("action_category") or winner.get("category") or "").upper()
                _tf_bypass_conf = self._dynamic_threshold(str(winner.get("symbol", "")), 0.65, 0.85)
                if _conf_f >= _tf_bypass_conf or _w_cat == "HEDGE_DCA":
                    meta["tf_conflict_bypassed"] = True
                    meta["bypass_reason"] = f"high_conf={_conf_f:.3f}>={_tf_bypass_conf:.3f}" if _conf_f >= _tf_bypass_conf else "HEDGE_DCA"
                    logger.info(
                        "TF_TIMING_CONFLICT_BYPASSED | %s | conf=%.3f cat=%s | allowing entry",
                        winner.get("symbol", "?"), _conf_f, _w_cat,
                    )
                else:
                    meta["tf_conflict_threshold"] = float(self.orch_context_gate_tf_conflict_threshold)
                    return False, "TF_TIMING_CONFLICT", meta

        if self.orch_context_gate_regime_dump_enabled and direction == 1:
            ret15 = self._safe_float(
                self._extract_with_meta(
                    winner,
                    [
                        "ret_15m",
                        "ret_15m_pct",
                        "return_15m_pct",
                        "return_15m",
                        "price_change_15m_pct",
                    ],
                )
            )
            ret1h = self._safe_float(
                self._extract_with_meta(
                    winner,
                    [
                        "ret_1h",
                        "ret_1h_pct",
                        "return_1h_pct",
                        "return_1h",
                        "price_change_1h_pct",
                    ],
                )
            )
            meta["ret_15m_pct"] = ret15
            meta["ret_1h_pct"] = ret1h
            if ret15 is not None and ret1h is not None:
                if float(ret15) <= float(self.orch_context_gate_dump_ret_15m_pct) and float(ret1h) <= float(self.orch_context_gate_dump_ret_1h_pct):
                    meta["dump_ret_15m_threshold"] = float(self.orch_context_gate_dump_ret_15m_pct)
                    meta["dump_ret_1h_threshold"] = float(self.orch_context_gate_dump_ret_1h_pct)
                    return False, "REGIME_DUMP_LONG_BLOCK", meta

        # --- Regime pump block (symmetric: block SHORT entries during strong pumps) ---
        if self.orch_context_gate_regime_pump_enabled and direction == -1:
            ret15 = self._safe_float(
                self._extract_with_meta(
                    winner,
                    ["ret_15m", "ret_15m_pct", "return_15m_pct", "return_15m", "price_change_15m_pct"],
                )
            )
            ret1h = self._safe_float(
                self._extract_with_meta(
                    winner,
                    ["ret_1h", "ret_1h_pct", "return_1h_pct", "return_1h", "price_change_1h_pct"],
                )
            )
            if "ret_15m_pct" not in meta:
                meta["ret_15m_pct"] = ret15
            if "ret_1h_pct" not in meta:
                meta["ret_1h_pct"] = ret1h
            if ret15 is not None and ret1h is not None:
                if float(ret15) >= float(self.orch_context_gate_pump_ret_15m_pct) and float(ret1h) >= float(self.orch_context_gate_pump_ret_1h_pct):
                    meta["pump_ret_15m_threshold"] = float(self.orch_context_gate_pump_ret_15m_pct)
                    meta["pump_ret_1h_threshold"] = float(self.orch_context_gate_pump_ret_1h_pct)
                    return False, "REGIME_PUMP_SHORT_BLOCK", meta

        # --- Microstructure instability veto (block entries during spoof/spread/sweep) ---
        if self.orch_microstructure_veto_enabled:
            spoof = self._safe_float(
                self._extract_with_meta(winner, ["depth_spoof_score", "spoof_score", "ob_spoof_score"])
            )
            spread = self._safe_float(
                self._extract_with_meta(winner, ["spread_bps", "bid_ask_spread_bps", "spread"])
            )
            move_int = self._safe_float(
                self._extract_with_meta(winner, ["move_intensity", "price_move_intensity", "volatility_intensity"])
            )
            meta["depth_spoof_score"] = spoof
            meta["spread_bps"] = spread
            meta["move_intensity"] = move_int

            spoof_triggered = spoof is not None and float(spoof) >= float(self.orch_microstructure_spoof_threshold)
            spread_triggered = spread is not None and float(spread) >= float(self.orch_microstructure_spread_spike_bps)
            move_triggered = move_int is not None and float(move_int) >= float(self.orch_microstructure_move_intensity_threshold)

            # Veto if spoof is high, OR (spread + move intensity both triggered)
            if spoof_triggered or (spread_triggered and move_triggered):
                veto_reasons = []
                if spoof_triggered:
                    veto_reasons.append(f"spoof={spoof:.2f}>={self.orch_microstructure_spoof_threshold}")
                if spread_triggered:
                    veto_reasons.append(f"spread={spread:.1f}bps>={self.orch_microstructure_spread_spike_bps}")
                if move_triggered:
                    veto_reasons.append(f"move_int={move_int:.2f}>={self.orch_microstructure_move_intensity_threshold}")
                meta["microstructure_veto_reasons"] = veto_reasons
                return False, "MICROSTRUCTURE_INSTABILITY_VETO", meta

        # --- Confidence saturation detector (flag or block entries with saturated confidence) ---
        if self.orch_confidence_saturation_enabled:
            conf_raw = self._safe_float(winner.get("confidence") or winner.get("model_confidence"))
            raw_conf_orig = self._safe_float(winner.get("raw_confidence"))
            check_conf = raw_conf_orig if raw_conf_orig is not None else conf_raw
            meta["confidence_checked"] = check_conf
            meta["confidence_saturation_threshold"] = float(self.orch_confidence_saturation_threshold)
            if check_conf is not None and float(check_conf) >= float(self.orch_confidence_saturation_threshold):
                meta["confidence_saturated"] = True
                if self.orch_confidence_saturation_action == "BLOCK":
                    return False, "CONFIDENCE_SATURATION_BLOCK", meta
                else:
                    # FLAG mode: stamp warning but allow through
                    winner["confidence_saturation_flag"] = True
                    winner["confidence_saturation_raw"] = float(check_conf)

        if self.orch_context_gate_liq_coupling_enabled and direction in (-1, 1):
            long_strength = self._safe_float(
                self._extract_with_meta(
                    winner,
                    [
                        "liquidation_long_strength",
                        "liq_long_strength",
                    ],
                )
            )
            short_strength = self._safe_float(
                self._extract_with_meta(
                    winner,
                    [
                        "liquidation_short_strength",
                        "liq_short_strength",
                    ],
                )
            )
            meta["liquidation_long_strength"] = long_strength
            meta["liquidation_short_strength"] = short_strength
            if long_strength is not None and short_strength is not None:
                total_strength = abs(float(long_strength)) + abs(float(short_strength))
                meta["liq_total_strength"] = total_strength
                if total_strength >= float(self.orch_context_gate_liq_min_strength):
                    # 3rd condition: liq cluster must be within max_dist_bps of current price
                    # (0 = disabled; fail-open when field absent so old signals still pass)
                    _max_dist = float(self.orch_context_gate_liq_max_dist_bps or 0.0)
                    _cluster_dist_bps = None
                    if _max_dist > 0:
                        try:
                            _raw_dist = self._extract_with_meta(
                                winner,
                                ["liq_cluster_dist_bps", "liq_distance_bps",
                                 "liq_near_price_bps", "liq_cluster_distance_bps"],
                            )
                            if _raw_dist is not None:
                                _cluster_dist_bps = float(_raw_dist)
                        except Exception:
                            _cluster_dist_bps = None
                    _proximity_ok = (
                        _max_dist <= 0.0  # disabled: always allow
                        or _cluster_dist_bps is None  # field absent: fail-open
                        or _cluster_dist_bps <= _max_dist  # within range: apply block
                    )
                    meta["liq_cluster_dist_bps"] = _cluster_dist_bps
                    meta["liq_max_dist_bps"] = _max_dist
                    if not _proximity_ok:
                        # Blob exists + strong, but too far from current price → skip block
                        pass
                    else:
                        ratio = float(self.orch_context_gate_liq_imbalance_ratio)
                        # Empty-portfolio leniency: when 0 positions open, use 2×
                        # the ratio so only extreme liq imbalances block initial
                        # positioning.  This prevents the deadlock where liq
                        # conflict blocks ALL entries on a fresh/empty portfolio.
                        _liq_empty_bypass = False
                        try:
                            _pos_raw_liq = self.redis.hgetall(f"positions:{account_id}") if self.redis else {}
                            _n_open_liq = 0
                            for _pk_l, _pv_l in (_pos_raw_liq or {}).items():
                                try:
                                    _pd_l = json.loads(
                                        _pv_l.decode("utf-8") if isinstance(_pv_l, (bytes, bytearray)) else str(_pv_l)
                                    )
                                    if abs(float(_pd_l.get("positionAmt") or _pd_l.get("size") or 0)) > 0:
                                        _n_open_liq += 1
                                except Exception:
                                    pass
                            if _n_open_liq == 0:
                                _liq_empty_bypass = True
                        except Exception:
                            pass
                        if _liq_empty_bypass:
                            ratio = ratio * 2.0  # lenient: 2× ratio for empty portfolio
                            meta["liq_empty_portfolio_bypass"] = True
                        if direction == 1 and float(long_strength) > float(short_strength) * ratio:
                            meta["liq_imbalance_ratio"] = ratio
                            return False, "LIQ_CONFLICT_LONG_VULN", meta
                        if direction == -1 and float(short_strength) > float(long_strength) * ratio:
                            meta["liq_imbalance_ratio"] = ratio
                            return False, "LIQ_CONFLICT_SHORT_VULN", meta

        return True, None, meta

    def _emit_account_diag(
        self,
        *,
        kind: str,
        decision_id: str,
        symbol: str,
        tf: str,
        requested_account: str,
        selected_account: str,
        reason: str,
        reasons_json: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "kind": str(kind or "orch_account_diag"),
            "decision_id": str(decision_id or ""),
            "symbol": str(symbol or ""),
            "tf": str(tf or ""),
            "requested_account": str(requested_account or ""),
            "selected_account": str(selected_account or ""),
            "reason": str(reason or ""),
            "reasons_json": reasons_json or {},
        }
        try:
            publish_ensemble_diagnostic(payload)
        except Exception:
            pass

    def _is_account_enabled(self, account_id: str) -> bool:
        aid = str(account_id or "primary").strip().lower()
        if aid == "asjad":
            return bool(self.account_asjad_enabled)
        if aid == "primary":
            return bool(self.account_primary_enabled)
        return True

    def _resolve_account_equity_context(self, account_id: str, portfolio: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Resolve equity/margin context using the freshest available source.

        Priority:
        1) portfolio snapshot values (orchestrator-local)
        2) Redis portfolio:equity:{account_id} (trader-published canonical snapshot)

        This prevents false `EQUITY_ZERO` blocks when one source is stale/empty.
        """
        aid = str(account_id or "primary").strip().lower()
        out: Dict[str, float] = {
            "equity_usd": 0.0,
            "available_margin_usd": 0.0,
            "free_margin_ratio": 0.0,
            "margin_util": 0.0,
            "source": "portfolio",
            "age_ms": float("inf"),
        }

        # Base: portfolio snapshot
        p = portfolio if isinstance(portfolio, dict) else {}
        try:
            out["equity_usd"] = float(p.get("equity") or 0.0)
        except Exception:
            out["equity_usd"] = 0.0
        try:
            out["margin_util"] = float(p.get("margin_util") or 0.0)
        except Exception:
            out["margin_util"] = 0.0
        try:
            out["free_margin_ratio"] = float(p.get("free_margin_ratio") or 0.0)
        except Exception:
            out["free_margin_ratio"] = 0.0
        if out["equity_usd"] > 0 and out["free_margin_ratio"] > 0:
            out["available_margin_usd"] = max(0.0, out["equity_usd"] * out["free_margin_ratio"])

        # Overlay: Redis canonical trader snapshot when available/fresher/better.
        eq_payload: Dict[str, Any] = {}
        try:
            raw_eq = self.redis.get(f"portfolio:equity:{aid}") if self.redis else None
            if isinstance(raw_eq, (bytes, bytearray)):
                raw_eq = raw_eq.decode("utf-8", errors="ignore")
            if isinstance(raw_eq, str) and raw_eq.strip().startswith("{"):
                eq_payload = json.loads(raw_eq)
        except Exception:
            eq_payload = {}

        if isinstance(eq_payload, dict) and eq_payload:
            now_ms = int(time.time() * 1000)
            ts_ms = eq_payload.get("ts_ms") or eq_payload.get("timestamp_ms")
            if ts_ms is None and eq_payload.get("timestamp") is not None:
                try:
                    ts_ms = int(float(eq_payload.get("timestamp")) * 1000)
                except Exception:
                    ts_ms = None
            try:
                age_ms = float(now_ms - int(float(ts_ms))) if ts_ms is not None else float("inf")
            except Exception:
                age_ms = float("inf")

            try:
                eq2 = float(eq_payload.get("equity_usd") or eq_payload.get("equity") or 0.0)
            except Exception:
                eq2 = 0.0

            avail2 = None
            for k in ("available_margin_usd", "available_margin", "free_margin_usd", "available_balance_usd", "availableBalance"):
                try:
                    if eq_payload.get(k) is not None:
                        avail2 = float(eq_payload.get(k) or 0.0)
                        break
                except Exception:
                    continue

            try:
                fmr2 = float(eq_payload.get("free_margin_ratio") or 0.0)
            except Exception:
                fmr2 = 0.0
            try:
                mu2 = float(eq_payload.get("margin_util") or 0.0)
            except Exception:
                mu2 = 0.0

            if fmr2 <= 0.0 and eq2 > 0.0 and avail2 is not None:
                fmr2 = max(0.0, min(1.0, float(avail2) / float(eq2)))
            if fmr2 <= 0.0 and eq2 > 0.0 and mu2 > 0.0:
                fmr2 = max(0.0, min(1.0, 1.0 - float(mu2)))
            if avail2 is None and eq2 > 0.0 and fmr2 > 0.0:
                avail2 = max(0.0, float(eq2) * float(fmr2))

            # Prefer Redis snapshot when portfolio is zero/empty OR Redis has fresher non-zero equity.
            prefer_redis = bool(
                (out["equity_usd"] <= 0.0 and eq2 > 0.0)
                or (eq2 > 0.0 and age_ms <= float(self.account_preflight_max_age_s * 1000))
            )
            if prefer_redis:
                out["equity_usd"] = float(eq2)
                out["available_margin_usd"] = float(max(0.0, avail2 or 0.0))
                out["free_margin_ratio"] = float(max(0.0, min(1.0, fmr2)))
                out["margin_util"] = float(max(0.0, mu2 if mu2 > 0 else out["margin_util"]))
                out["source"] = "redis_equity"
                out["age_ms"] = float(age_ms)

        # Final derivations
        if out["free_margin_ratio"] <= 0.0 and out["equity_usd"] > 0.0 and out["margin_util"] > 0.0:
            out["free_margin_ratio"] = max(0.0, min(1.0, 1.0 - out["margin_util"]))
        if out["available_margin_usd"] <= 0.0 and out["equity_usd"] > 0.0 and out["free_margin_ratio"] > 0.0:
            out["available_margin_usd"] = max(0.0, out["equity_usd"] * out["free_margin_ratio"])

        return out

    def _account_preflight(self, account_id: str, symbol: str, action: str) -> Tuple[bool, Dict[str, Any]]:
        aid = str(account_id or "primary").strip().lower()
        out: Dict[str, Any] = {
            "account": aid,
            "equity_missing": False,
            "equity_stale": False,
            "kill_switch_active": False,
            "kill_switch_reason": "",
        }
        if not self.account_preflight_required:
            return True, out
        try:
            if aid == "asjad" and (not self.account_asjad_allow_publish):
                out["publish_gate"] = "ACCOUNT_ASJAD_ALLOW_PUBLISH_FALSE"
                return False, out
        except Exception:
            pass
        try:
            raw = self.redis.get(f"portfolio:equity:{aid}") if self.redis else None
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            obj = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else None
            if not isinstance(obj, dict):
                out["equity_missing"] = True
                return False, out
            ts_ms = obj.get("ts_ms") or obj.get("timestamp_ms")
            if ts_ms is None and obj.get("timestamp") is not None:
                try:
                    ts_ms = int(float(obj.get("timestamp")) * 1000)
                except Exception:
                    ts_ms = None
            if ts_ms is None:
                out["equity_stale"] = True
                return False, out
            age_ms = int(time.time() * 1000) - int(float(ts_ms))
            out["equity_age_ms"] = int(age_ms)
            if age_ms > int(self.account_preflight_max_age_s * 1000):
                out["equity_stale"] = True
                return False, out
        except Exception:
            out["equity_missing"] = True
            return False, out
        try:
            halted, halt_info = self._kill_switch_active(aid, symbol)
            if halted and self._is_risk_add_action(action) and kill_switch_blocks(halt_info, account=aid, symbol=symbol):
                out["kill_switch_active"] = True
                out["kill_switch_reason"] = str((halt_info or {}).get("reason") or (halt_info or {}).get("code") or "KILL_SWITCH_ACTIVE")
                return False, out
        except Exception:
            pass
        return True, out

    def _is_protective_action(self, payload: Dict[str, Any], action: str) -> bool:
        act = str(action or payload.get("action") or payload.get("action_name") or "").upper().strip()
        cat = str(payload.get("action_category") or payload.get("category") or "").upper().strip()
        src = str(payload.get("source") or payload.get("source_module") or "").upper().strip()
        if act.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")):
            return True
        if cat in {"PROTECTIVE", "HEDGE", "RECOVERY", "HEDGE_TRIM"}:
            return True
        if "PROTECT" in src and "HEDGE" in act:
            return True
        return False

    def _get_symbol_used_margin(self, account_id: str, symbol: str) -> float:
        if not self.redis:
            return 0.0
        try:
            raw = self.redis.hgetall(f"portfolio:positions:{account_id}") or {}
        except Exception:
            raw = {}
        total = 0.0
        for field, val in (raw or {}).items():
            try:
                k = str(field).upper().strip()
                if not k.startswith(f"{str(symbol).upper().strip()}:"):
                    continue
                if isinstance(val, str):
                    d = json.loads(val) if val and val.lstrip().startswith("{") else {}
                else:
                    d = val if isinstance(val, dict) else {}
                margin = float(d.get("margin_used", 0.0) or d.get("initialMargin", 0.0) or d.get("initial_margin", 0.0) or 0.0)
                total += abs(margin)
            except Exception:
                continue
        return float(total)

    def _prepublish_feasibility_gate(
        self,
        winner: Dict[str, Any],
        proof: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        if not self.orch_pre_publish_feasibility_enabled:
            return True, None, {}
        if not self._is_risk_add_action(action):
            return True, None, {}

        # ── REDUCE-ONLY LATCH: per-symbol scoping ──
        # Only block the symbol that triggered the kill event, not all symbols globally.
        # HEDGE_DCA signals bypass the latch entirely (risk-reducing hedge building).
        _cat_upper = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
        _act_u_latch = str(action or "").upper()
        _is_hedge_dca = _cat_upper == "HEDGE_DCA" or bool(winner.get("tf_hedge_disagg"))
        _is_protective_hedge = (
            _act_u_latch.startswith(("OPEN_HEDGE_", "ADD_HEDGE_"))
            or (_cat_upper in ("HEDGE", "PROTECTIVE", "RECOVERY") and "HEDGE" in _act_u_latch)
        )
        _is_flip_latch = ("CLOSE" in _act_u_latch and "OPEN" in _act_u_latch) or "FLIP" in _act_u_latch
        _latch_bypass = _is_hedge_dca or _is_protective_hedge or _is_flip_latch
        try:
            from risk.reduce_only_latch import get_latch_per_symbol as _orch_get_latch_symbol
            _sym_latch_active, _sym_latch_until, _sym_latch_reason = _orch_get_latch_symbol(self.redis, account_id, symbol)
            if _sym_latch_active and not _latch_bypass:
                _sym_remaining = max(0, (_sym_latch_until - int(time.time() * 1000)) // 1000)
                return False, "ORCH_REDUCE_ONLY_LATCH_BLOCK", {
                    "equity_usd": 0.0,
                    "margin_util": 0.0,
                    "latch_remaining_sec": _sym_remaining,
                    "latch_reason": _sym_latch_reason,
                    "reason": f"Per-symbol latch active for {symbol} ({_sym_latch_reason}), {_sym_remaining}s remaining",
                }
        except ImportError:
            pass
        except Exception as _sl_err:
            logger.debug("ORCH_SYMBOL_LATCH_CHECK_ERR | %s", _sl_err)
        try:
            from risk.reduce_only_latch import get_latch as _orch_get_latch_early
            _latch_active_e, _latch_until_e, _latch_reason_e = _orch_get_latch_early(self.redis, account_id)
            if _latch_active_e and not _latch_bypass:
                _latch_remaining_e = max(0, (_latch_until_e - int(time.time() * 1000)) // 1000)
                return False, "ORCH_REDUCE_ONLY_LATCH_BLOCK", {
                    "equity_usd": 0.0,
                    "margin_util": 0.0,
                    "latch_remaining_sec": _latch_remaining_e,
                    "latch_reason": _latch_reason_e,
                    "reason": f"Reduce-only latch active ({_latch_reason_e}), {_latch_remaining_e}s remaining — blocks ALL risk-adds",
                }
        except ImportError:
            pass
        except Exception as _latch_err_e:
            logger.debug("ORCH_LATCH_EARLY_CHECK_ERR | %s", _latch_err_e)

        # ── LTFMR Exhaustion Scaling Pause (BEFORE protective bypass) ──
        # Evaluates INCREASE/ADD actions against lower-TF exhaustion signals.
        # Must run before protective bypass so INCREASE_SHORT/LONG are caught
        # even when classified as "protective" by the hedge manager.
        try:
            _act_u_exh = str(action or "").upper()
            _is_increase = "INCREASE" in _act_u_exh or "ADD" in _act_u_exh
            _is_hedge_exh = "HEDGE" in _act_u_exh
            if _is_increase and not _is_hedge_exh:
                from risk.ltf_reversal import compute_ltf_exhaustion_score
                _exh_dir = "LONG" if "LONG" in _act_u_exh else "SHORT" if "SHORT" in _act_u_exh else None
                if _exh_dir:
                    try:
                        _exh_req_margin = float(winner.get("margin_usd") or 0.0)
                    except Exception:
                        _exh_req_margin = 0.0
                    _exh_score, _exh_comps = compute_ltf_exhaustion_score(symbol, _exh_dir, self.redis)
                    if _exh_score >= 0.55:
                        return False, "ORCH_LTFMR_EXHAUSTION_BLOCK", {
                            "exhaustion_score": round(_exh_score, 4),
                            "direction": _exh_dir,
                            "symbol": symbol,
                            "action": action,
                            "components": _exh_comps,
                            "reason": f"LTF exhaustion score {_exh_score:.2f} >= 0.55 — blocking INCREASE scaling into exhausted move",
                        }
                    elif _exh_score >= 0.35 and _exh_req_margin > 0:
                        _exh_mult = max(0.3, 1.0 - (_exh_score - 0.35) * 2.0)
                        _orig_margin = float(_exh_req_margin)
                        _adj_margin = round(_exh_req_margin * _exh_mult, 2)
                        winner["margin_usd"] = _adj_margin
                        try:
                            _lev = float(winner.get("leverage") or 1.0)
                            if _lev > 0:
                                winner["notional_usd"] = _adj_margin * _lev
                        except Exception:
                            pass
                        winner["ltfmr_exhaustion_downsize"] = True
                        winner["ltfmr_exhaustion_score"] = round(_exh_score, 4)
                        winner["ltfmr_original_margin"] = _orig_margin
                        logger.warning(
                            "ORCH_LTFMR_EXHAUSTION_DOWNSIZE | sym=%s dir=%s score=%.2f mult=%.2f orig=$%.1f adj=$%.1f",
                            symbol, _exh_dir, _exh_score, _exh_mult, _orig_margin, _adj_margin,
                        )
        except Exception as _exh_err:
            logger.debug("[ORCH_LTFMR_EXHAUSTION] Non-fatal: %s", _exh_err)

        # ── P6: Microstructure Readiness Score for Scale-In (Mar 2026) ──
        # Scale-in (INCREASE/ADD) requires depth adequacy, flow alignment, low spoof risk.
        # micro_readiness = weighted sum of depth, spread, flow, spoof, snapback scores.
        try:
            _act_u_msi = str(action or "").upper()
            _is_increase_msi = "INCREASE" in _act_u_msi or "ADD" in _act_u_msi
            _is_hedge_msi = "HEDGE" in _act_u_msi
            from config import ENABLE_MICRO_SCALE_IN_GATE
            if ENABLE_MICRO_SCALE_IN_GATE and _is_increase_msi and not _is_hedge_msi and self.redis:
                _msi_sym = str(symbol).upper()
                _msi_side = "LONG" if "LONG" in _act_u_msi else "SHORT" if "SHORT" in _act_u_msi else ""
                _msi_ms = {}
                try:
                    _msi_ms_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{_msi_sym}")
                    if _msi_ms_raw:
                        _msi_ms = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _msi_ms_raw.items()}
                except Exception:
                    pass
                _msi_feats = {}
                try:
                    for _fk in ["ob_ob_spread_bps", "ind_ta_NATR_14_5m", "depth_bps_10_total_usd"]:
                        _fv = self.redis.hget(f"unified_features:{_msi_sym}:5m", _fk)
                        if _fv:
                            _msi_feats[_fk] = float(_fv)
                except Exception:
                    pass
                if _msi_ms or _msi_feats:
                    _msi_leverage = float(winner.get("leverage") or 20)
                    _msi_notional = float(winner.get("notional_usd") or float(winner.get("margin_usd") or 0) * _msi_leverage)
                    # Component 1: Depth adequacy — order should not eat >2% of visible depth
                    _msi_depth = float(_msi_ms.get("bps_10_total_usd", 0) or _msi_feats.get("depth_bps_10_total_usd", 0) or 0)
                    _msi_impact_factor = max(1.0, _msi_leverage / 20.0)
                    _msi_depth_score = min(1.0, _msi_depth / max(_msi_notional * _msi_impact_factor * 50, 1.0)) if _msi_depth > 0 else 0.5
                    # Component 2: Spread cost relative to expected move
                    _msi_spread = float(_msi_feats.get("ob_ob_spread_bps", 3.0) or 3.0)
                    _msi_natr_bps = float(_msi_feats.get("ind_ta_NATR_14_5m", 0.5) or 0.5) * 100  # NATR% to bps
                    _msi_spread_score = min(1.0, max(0.0, 1.0 - _msi_spread / max(_msi_natr_bps, 1.0)))
                    # Component 3: Flow alignment
                    _msi_flow_imb = float(_msi_ms.get("trade_imbalance_5s", 0) or 0)
                    _msi_flow_score = 0.5
                    if _msi_side == "LONG":
                        _msi_flow_score = min(1.0, max(0.0, 0.5 + _msi_flow_imb))
                    elif _msi_side == "SHORT":
                        _msi_flow_score = min(1.0, max(0.0, 0.5 - _msi_flow_imb))
                    # Component 4: Spoof safety
                    _msi_spoof = float(_msi_ms.get("spoof_score", 0) or 0)
                    _msi_spoof_score = max(0.0, 1.0 - _msi_spoof)
                    # Component 5: Snapback risk
                    _msi_snapback = float(_msi_ms.get("snapback_score", 0) or 0)
                    _msi_snap_score = max(0.0, 1.0 - _msi_snapback)
                    # Weighted readiness
                    _msi_readiness = (
                        _msi_depth_score * 0.25 +
                        _msi_spread_score * 0.20 +
                        _msi_flow_score * 0.25 +
                        _msi_spoof_score * 0.15 +
                        _msi_snap_score * 0.15
                    )
                    # Dynamic threshold from regime
                    _msi_thresh = 0.40  # default
                    try:
                        _msi_thresh = self._dynamic_value(_msi_sym, 0.30, 0.60)
                    except Exception:
                        pass
                    logger.info(
                        "MICRO_SCALE_IN | sym=%s side=%s | readiness=%.3f thresh=%.3f | "
                        "depth=%.2f spread=%.2f flow=%.2f spoof=%.2f snap=%.2f",
                        _msi_sym, _msi_side, _msi_readiness, _msi_thresh,
                        _msi_depth_score, _msi_spread_score, _msi_flow_score,
                        _msi_spoof_score, _msi_snap_score,
                    )
                    if _msi_readiness < _msi_thresh:
                        return False, "MICRO_SCALE_IN_BLOCK", {
                            "readiness": round(_msi_readiness, 4),
                            "threshold": round(_msi_thresh, 4),
                            "symbol": _msi_sym,
                            "action": action,
                            "reason": f"Microstructure readiness {_msi_readiness:.3f} < {_msi_thresh:.3f} — scale-in blocked",
                        }
        except ImportError:
            pass
        except Exception as _msi_err:
            logger.debug("[MICRO_SCALE_IN_GATE] Non-fatal: %s", _msi_err)

        if (not self.orch_pre_publish_block_protective) and self._is_protective_action(winner, action):
            # ── Governor still enforces hard margin caps on protective actions ──
            try:
                from risk.margin_governor import MarginGovernor
                _ppf_gov = MarginGovernor(self.redis)
                _ppf_verdict = _ppf_gov.evaluate(
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposed_margin_usd=float(winner.get("margin_usd") or 0.0),
                    source="orch_prepublish_protective",
                    is_protective=True,
                )
                if not _ppf_verdict.allowed:
                    return False, _ppf_verdict.code, {
                        "governor_verdict": _ppf_verdict.action,
                        "governor_reason": _ppf_verdict.reason,
                        **_ppf_verdict.meta,
                    }
            except Exception:
                pass  # Fail-open
            return True, None, {"bypass": "protective"}

        # ── Add-to-loser hard block (always active, independent of shock eval) ──
        # Prevents adding margin to the losing side of a hedge pair at ANY time,
        # not just during detected shock. Critical for micro-account survival.
        try:
            prepublish_block_add_to_loser = bool(getattr(config, "ORCH_PREPUBLISH_BLOCK_ADD_TO_LOSER", True))
        except Exception:
            prepublish_block_add_to_loser = True
        if prepublish_block_add_to_loser:
            proposed_u = str(action or "").upper()
            legs = self._get_hedge_legs(account_id, symbol)
            if len(legs) == 2:
                long_leg = legs.get("LONG", {})
                short_leg = legs.get("SHORT", {})
                long_roe = float(long_leg.get("roe_pct") or long_leg.get("unrealized_pnl_pct") or 0)
                short_roe = float(short_leg.get("roe_pct") or short_leg.get("unrealized_pnl_pct") or 0)
                loser_side = "LONG" if long_roe <= short_roe else "SHORT"
                # Check if proposed action adds to the losing side
                if ("LONG" in proposed_u and loser_side == "LONG") or \
                   ("SHORT" in proposed_u and loser_side == "SHORT"):
                    return False, "ORCH_PREPUBLISH_ADD_TO_LOSER_BLOCK", {
                        "proposed_action": proposed_u,
                        "loser_side": loser_side,
                        "long_roe_pct": round(long_roe, 2),
                        "short_roe_pct": round(short_roe, 2),
                        "reason": "Cannot add margin to losing hedge leg (survival lockdown)",
                    }

        try:
            req_margin = float(winner.get("margin_usd") or 0.0)
        except Exception:
            req_margin = 0.0

        # ── Global Reversal Gate: block new risk-adds when reversal is active ──
        try:
            _rev_gate_enabled = bool(getattr(config, "REVERSAL_DETECTOR_ENABLED", False))
            if _rev_gate_enabled:
                from risk.reversal_detector import read_cached_reversal
                _rev_state = read_cached_reversal(self.redis)
                if _rev_state and isinstance(_rev_state, dict) and bool(_rev_state.get("active", False)):
                    _rev_triggers = int(_rev_state.get("trigger_count") or 0)
                    return False, "ORCH_REVERSAL_BLOCK", {
                        "reversal_active": True,
                        "reversal_triggers": _rev_triggers,
                        "symbol": symbol,
                        "action": action,
                        "reason": "Global reversal active — blocking new risk-adds",
                    }
        except Exception as _rev_err:
            logger.debug("[ORCH_REVERSAL_GATE] Non-fatal: %s", _rev_err)

        # ── Risk Budget Allocator: apply soft sizing multiplier (feature-flagged) ──
        try:
            _rba_enabled = bool(getattr(config, "RISK_BUDGET_ALLOCATOR_ENABLED", False))
            if _rba_enabled and req_margin > 0.0:
                from risk.risk_budget_allocator import (
                    read_cached_allocation,
                    apply_risk_budget_to_sizing,
                    STATE_LOCKDOWN,
                    maybe_symbol_hedge_normal_override,
                )
                _alloc = read_cached_allocation(self.redis, account_id)
                if _alloc is not None:
                    _alloc = maybe_symbol_hedge_normal_override(
                        self.redis, str(symbol).upper(), _alloc, winner
                    )
                    # LOCKDOWN → block (reduce-only)
                    if _alloc.state == STATE_LOCKDOWN:
                        return False, "ORCH_RBA_LOCKDOWN", {
                            "rba_state": _alloc.state,
                            "rba_reason": _alloc.reason,
                            "requested_margin_usd": float(req_margin),
                        }

                    # ── Cadence gate: minimum time between new opens ──
                    # FLIP/composite actions (CLOSE_X_AND_OPEN_Y) are directional
                    # reversals — they must not be cadence-gated since the market
                    # may require immediate direction change.
                    _act_u_rba = str(action or "").upper()
                    _is_flip_rba = ("CLOSE" in _act_u_rba and "OPEN" in _act_u_rba) or "FLIP" in _act_u_rba

                    # Empty-portfolio bypass: when 0 positions open, relax cadence
                    # to allow initial positioning without 48s delays between each.
                    _empty_portfolio_bypass = False
                    try:
                        _pos_raw_cad = self.redis.hgetall(f"positions:{account_id}") if self.redis else {}
                        _n_open_cad = 0
                        for _pk_c, _pv_c in (_pos_raw_cad or {}).items():
                            try:
                                _pd_c = json.loads(_pv_c.decode("utf-8") if isinstance(_pv_c, (bytes, bytearray)) else str(_pv_c))
                                if abs(float(_pd_c.get("positionAmt") or _pd_c.get("size") or 0)) > 0:
                                    _n_open_cad += 1
                            except Exception:
                                pass
                        if _n_open_cad == 0:
                            _empty_portfolio_bypass = True
                    except Exception:
                        pass

                    if not _is_flip_rba and not _empty_portfolio_bypass:
                        try:
                            _cadence_min = int(_alloc.cadence_min_sec)
                            _last_open = self._rba_last_open_ts.get(account_id, 0.0)
                            _since = time.time() - _last_open if _last_open > 0 else 999999.0
                            if _since < _cadence_min:
                                _conf_val = float(
                                    winner.get("confidence") or winner.get("model_confidence") or 0
                                )
                                _hi_conf_bypass = False
                                _cad_conf_thr = self._dynamic_threshold(symbol, 0.65, 0.85)
                                _cad_time_frac = self._dynamic_threshold(symbol, 0.15, 0.40)
                                if _conf_val >= _cad_conf_thr and _since >= _cadence_min * _cad_time_frac:
                                    _hi_conf_bypass = True
                                if not _hi_conf_bypass:
                                    return False, "ORCH_RBA_CADENCE_BLOCK", {
                                        "rba_state": _alloc.state,
                                        "cadence_min_sec": _cadence_min,
                                        "since_last_open_sec": round(_since, 1),
                                        "account_id": account_id,
                                        "symbol": symbol,
                                    }
                        except Exception:
                            pass

                    if _empty_portfolio_bypass and not _is_flip_rba:
                        logger.info(
                            "ORCH_RBA_CADENCE_BYPASS | empty_portfolio | acct=%s sym=%s | "
                            "n_positions=0 → allowing initial positioning",
                            account_id, symbol,
                        )

                    # ── Max risk symbols gate: limit concurrent open symbols ──
                    try:
                        _max_syms = int(_alloc.max_risk_symbols)
                        if _max_syms > 0:
                            _positions_raw = self.redis.hgetall(f"positions:{account_id}") if self.redis else {}
                            _open_syms = set()
                            for _pk, _pv in (_positions_raw or {}).items():
                                try:
                                    _pkey = _pk.decode("utf-8") if isinstance(_pk, (bytes, bytearray)) else str(_pk)
                                    _pval = _pv.decode("utf-8") if isinstance(_pv, (bytes, bytearray)) else str(_pv)
                                    _pdata = json.loads(_pval)
                                    if isinstance(_pdata, dict):
                                        _pamt = float(_pdata.get("positionAmt") or _pdata.get("size") or 0)
                                        if abs(_pamt) > 0:
                                            _psym = str(_pdata.get("symbol") or _pkey.split(":")[0]).upper()
                                            _open_syms.add(_psym)
                                except Exception:
                                    pass
                            if len(_open_syms) >= _max_syms and symbol.upper() not in _open_syms:
                                return False, "ORCH_RBA_MAX_SYMBOLS_BLOCK", {
                                    "rba_state": _alloc.state,
                                    "max_risk_symbols": _max_syms,
                                    "current_open_symbols": len(_open_syms),
                                    "open_symbols": sorted(list(_open_syms))[:10],
                                    "proposed_symbol": symbol,
                                }
                    except Exception:
                        pass

                    # ── Data-health gate: block EXPAND if data degraded ──
                    try:
                        _msc_enabled = bool(getattr(config, "MARKET_STATE_CONTRACT_ENABLED", True))
                        if _msc_enabled and _alloc.state in ("EXPAND", "MOMENTUM_SHOCK"):
                            from risk.market_state_contract import read_cached_contract
                            _contract = read_cached_contract(self.redis)
                            if _contract and isinstance(_contract, dict):
                                if not bool(_contract.get("can_expand", False)):
                                    # Downgrade to BASELINE sizing instead of EXPAND
                                    _alloc.risk_mult = min(_alloc.risk_mult, 1.0)
                                    logger.info(
                                        "ORCH_EXPAND_BLOCKED | acct=%s sym=%s reason=%s",
                                        account_id, symbol,
                                        str(_contract.get("reason", "DATA_HEALTH")),
                                    )
                    except Exception:
                        pass

                    # Apply risk_mult to margin (soft scaling)
                    _is_major = str(symbol).upper() in ("BTCUSDT", "ETHUSDT")
                    adjusted = apply_risk_budget_to_sizing(req_margin, _alloc, is_major=_is_major)
                    if adjusted < req_margin:
                        winner["rba_original_margin_usd"] = float(req_margin)
                        winner["rba_adjusted_margin_usd"] = float(adjusted)
                        winner["rba_scale_factor"] = round(float(adjusted) / max(1e-9, float(req_margin)), 4)
                        winner["margin_usd"] = float(adjusted)
                        req_margin = float(adjusted)
                        # Scale notional proportionally
                        try:
                            _lev = float(winner.get("leverage") or 1.0)
                            if _lev > 0:
                                winner["notional_usd"] = float(adjusted) * _lev
                        except Exception:
                            pass
                        logger.info(
                            "ORCH_RBA_DOWNSIZE | acct=%s sym=%s state=%s mult=%.2f orig=$%.1f adj=$%.1f",
                            account_id, symbol, _alloc.state, _alloc.risk_mult,
                            float(winner.get("rba_original_margin_usd", 0)),
                            float(adjusted),
                        )
                    elif adjusted > req_margin:
                        # EXPAND/MOMENTUM_SHOCK upsize — scale up within safety caps
                        winner["rba_original_margin_usd"] = float(req_margin)
                        winner["rba_adjusted_margin_usd"] = float(adjusted)
                        winner["rba_scale_factor"] = round(float(adjusted) / max(1e-9, float(req_margin)), 4)
                        winner["margin_usd"] = float(adjusted)
                        req_margin = float(adjusted)
                        try:
                            _lev = float(winner.get("leverage") or 1.0)
                            if _lev > 0:
                                winner["notional_usd"] = float(adjusted) * _lev
                        except Exception:
                            pass
                        logger.info(
                            "ORCH_RBA_UPSIZE | acct=%s sym=%s state=%s mult=%.2f orig=$%.1f adj=$%.1f",
                            account_id, symbol, _alloc.state, _alloc.risk_mult,
                            float(winner.get("rba_original_margin_usd", 0)),
                            float(adjusted),
                        )
        except Exception as _rba_err:
            logger.debug("[ORCH_RBA] Non-fatal error: %s", _rba_err)

        if req_margin <= 0.0:
            return False, "ORCH_IMPOSSIBLE_TRADE_MARGIN_MISSING", {"requested_margin_usd": float(req_margin)}

        portfolio = build_portfolio_snapshot(self.redis, account_id)

        # ── Staleness check for margin feasibility ──
        try:
            _feas_ts_ms = int(portfolio.get("updated_ts_ms") or 0)
            _feas_age_s = (time.time() * 1000 - _feas_ts_ms) / 1000.0 if _feas_ts_ms > 0 else float("inf")
            if _feas_age_s > PORTFOLIO_STALE_THRESHOLD_S:
                return False, "ORCH_PORTFOLIO_STALE", {
                    "age_s": round(_feas_age_s, 1),
                    "threshold_s": PORTFOLIO_STALE_THRESHOLD_S,
                    "updated_ts_ms": _feas_ts_ms,
                }
        except Exception:
            pass  # Fail-open

        _acct_ctx = self._resolve_account_equity_context(account_id, portfolio)
        try:
            equity = float(_acct_ctx.get("equity_usd") or 0.0)
        except Exception:
            equity = 0.0
        try:
            margin_util = float(winner.get("margin_util") or _acct_ctx.get("margin_util") or portfolio.get("margin_util") or 0.0)
        except Exception:
            margin_util = 0.0
        try:
            free_margin_ratio = float(winner.get("free_margin_ratio") or _acct_ctx.get("free_margin_ratio") or portfolio.get("free_margin_ratio") or 0.0)
        except Exception:
            free_margin_ratio = 0.0
        # ── Derive free_margin_ratio when not explicitly provided ──────────
        # If free_margin_ratio is 0.0 but margin_util shows available capacity,
        # derive it so the headroom check doesn't block on stale/missing data.
        if free_margin_ratio <= 0.0 and equity > 0.0:
            free_margin_ratio = max(0.0, 1.0 - margin_util)

        if equity <= 0.0:
            # region agent log
            try:
                import json as _aj
                _ts = int(time.time() * 1000)
                _payload = {
                    "sessionId": "53deb7",
                    "id": f"log_{_ts}_orch_equity_zero_{aid}_{symbol}",
                    "timestamp": _ts,
                    "location": "rl/orchestrator_worker.py:_prepublish_feasibility_gate",
                    "message": "orch_block_equity_zero",
                    "runId": "post-fix",
                    "hypothesisId": "H1",
                    "data": {
                        "account_id": str(aid),
                        "symbol": str(symbol),
                        "action": str(action),
                        "req_margin_usd": float(req_margin),
                        "winner_margin_util": float(winner.get("margin_util") or 0.0),
                        "winner_free_margin_ratio": float(winner.get("free_margin_ratio") or 0.0),
                        "portfolio_equity": float((portfolio or {}).get("equity") or 0.0),
                        "portfolio_margin_util": float((portfolio or {}).get("margin_util") or 0.0),
                        "portfolio_free_margin_ratio": float((portfolio or {}).get("free_margin_ratio") or 0.0),
                        "portfolio_updated_ts_ms": int((portfolio or {}).get("updated_ts_ms") or 0),
                        "acct_ctx_equity_usd": float((_acct_ctx or {}).get("equity_usd") or 0.0),
                        "acct_ctx_available_margin_usd": float((_acct_ctx or {}).get("available_margin_usd") or 0.0),
                        "acct_ctx_free_margin_ratio": float((_acct_ctx or {}).get("free_margin_ratio") or 0.0),
                        "acct_ctx_margin_util": float((_acct_ctx or {}).get("margin_util") or 0.0),
                        "acct_ctx_source": str((_acct_ctx or {}).get("source") or ""),
                        "acct_ctx_age_ms": float((_acct_ctx or {}).get("age_ms") or 0.0),
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
            return False, "ORCH_IMPOSSIBLE_TRADE_EQUITY_ZERO", {
                "equity_usd": float(equity),
                "margin_util": float(margin_util),
                "free_margin_ratio": float(free_margin_ratio),
                "requested_margin_usd": float(req_margin),
            }

        # ── Fix #1: Reduce-only latch (per-symbol first, then global fallback) ──
        _cat_u2 = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
        _act_u_latch2 = str(action or "").upper()
        _is_hedge_dca2 = _cat_u2 == "HEDGE_DCA" or bool(winner.get("tf_hedge_disagg"))
        _is_protective_hedge2 = (
            _act_u_latch2.startswith(("OPEN_HEDGE_", "ADD_HEDGE_"))
            or (_cat_u2 in ("HEDGE", "PROTECTIVE", "RECOVERY") and "HEDGE" in _act_u_latch2)
        )
        _is_flip_latch2 = ("CLOSE" in _act_u_latch2 and "OPEN" in _act_u_latch2) or "FLIP" in _act_u_latch2
        _latch_bypass2 = _is_hedge_dca2 or _is_protective_hedge2 or _is_flip_latch2
        try:
            from risk.reduce_only_latch import get_latch_per_symbol as _orch_get_sym_latch
            _sym_active, _sym_until, _sym_reason = _orch_get_sym_latch(self.redis, account_id, symbol)
            if _sym_active and not _latch_bypass2:
                _sym_rem = max(0, (_sym_until - int(time.time() * 1000)) // 1000)
                return False, "ORCH_REDUCE_ONLY_LATCH_BLOCK", {
                    "equity_usd": float(equity),
                    "margin_util": float(margin_util),
                    "latch_remaining_sec": _sym_rem,
                    "latch_reason": _sym_reason,
                    "reason": f"Per-symbol latch for {symbol} ({_sym_reason}), {_sym_rem}s remaining",
                }
        except ImportError:
            pass
        except Exception:
            pass
        try:
            from risk.reduce_only_latch import get_latch as _orch_get_latch
            _latch_active, _latch_until, _latch_reason = _orch_get_latch(self.redis, account_id)
            if _latch_active and not _latch_bypass2:
                _latch_remaining = max(0, (_latch_until - int(time.time() * 1000)) // 1000)
                return False, "ORCH_REDUCE_ONLY_LATCH_BLOCK", {
                    "equity_usd": float(equity),
                    "margin_util": float(margin_util),
                    "latch_remaining_sec": _latch_remaining,
                    "latch_reason": _latch_reason,
                    "reason": f"Deleverage latch active ({_latch_reason}), {_latch_remaining}s remaining",
                }
        except ImportError:
            pass
        except Exception as _latch_err:
            logger.debug("ORCH_LATCH_CHECK_ERR | %s", _latch_err)

        # ── PQC: Trainer-stuck latch — block entries when trainer predictions are degenerate ──
        try:
            _pqc_stuck_key = str(getattr(config, 'PQC_STUCK_LATCH_KEY', 'risk:trainer_stuck_until'))
            _pqc_stuck_val = self.redis.get(_pqc_stuck_key)
            if _pqc_stuck_val is not None:
                _pqc_until_ms = int(_pqc_stuck_val)
                _pqc_now_ms = int(time.time() * 1000)
                if _pqc_now_ms < _pqc_until_ms:
                    _pqc_remaining = max(0, (_pqc_until_ms - _pqc_now_ms) // 1000)
                    return False, "ORCH_TRAINER_STUCK_LATCH_BLOCK", {
                        "equity_usd": float(equity),
                        "margin_util": float(margin_util),
                        "stuck_remaining_sec": _pqc_remaining,
                        "reason": f"Trainer stuck latch active, {_pqc_remaining}s remaining — predictions degenerate",
                    }
        except Exception as _pqc_stuck_err:
            logger.debug("ORCH_TRAINER_STUCK_CHECK_ERR | %s", _pqc_stuck_err)

        # ── Safe-mode: hard block when approaching danger zone ────────────
        try:
            safe_mode_enabled = bool(getattr(config, "ORCH_SAFE_MODE_ENABLED", True))
            safe_mode_mu_block = float(getattr(config, "ORCH_SAFE_MODE_MARGIN_UTIL_BLOCK", 0.60))
        except Exception:
            safe_mode_enabled = True
            safe_mode_mu_block = 0.85
        if safe_mode_enabled and margin_util >= safe_mode_mu_block:
            return False, "ORCH_SAFE_MODE_MARGIN_BLOCK", {
                "equity_usd": float(equity),
                "margin_util": float(margin_util),
                "safe_mode_threshold": float(safe_mode_mu_block),
                "requested_margin_usd": float(req_margin),
            }

        # ── Risk State Machine: graduated response ──────────────────────
        # EMERGENCY → hard block (deleverage active)
        # STRESSED  → allow with warning (RBA/sizing handles reduction)
        # Prevents triple-blocking with RBA + Safe Mode + RSM
        try:
            rsm_enabled = bool(getattr(config, "RISK_STATE_MACHINE_ENABLED", True))
            if rsm_enabled:
                from risk.risk_state_machine import RiskStateMachine, RiskState
                _rsm_cache = getattr(self, "_risk_state_machine", None)
                if _rsm_cache is None:
                    _rsm_cache = RiskStateMachine(redis_client=getattr(self, "redis", None))
                    self._risk_state_machine = _rsm_cache
                mu_pct_for_rsm = margin_util * 100.0  # RSM uses 0-100 scale
                im_ratio = margin_util  # Already 0-1
                rsm_snap = _rsm_cache.evaluate(
                    account_id=str(getattr(self, "_account_id", "primary")),
                    mu_pct=mu_pct_for_rsm,
                    acct_im_pct=im_ratio,
                    equity=float(equity),
                )
                # Only hard-block on EMERGENCY; STRESSED allows reduced-size entries
                if rsm_snap.state == RiskState.EMERGENCY:
                    return False, "ORCH_RISK_STATE_BLOCK", {
                        "risk_state": rsm_snap.state.value,
                        "mu_pct": round(mu_pct_for_rsm, 1),
                        "breach_streak": rsm_snap.breach_streak,
                        "equity_usd": float(equity),
                        "margin_util": float(margin_util),
                        "requested_margin_usd": float(req_margin),
                    }
                elif rsm_snap.state == RiskState.STRESSED:
                    logger.info(
                        "ORCH_RSM_STRESSED_ALLOW | mu=%.1f%% eq=$%.0f | "
                        "allowing risk-add (RBA/sizing handles reduction)",
                        mu_pct_for_rsm, float(equity),
                    )
        except ImportError:
            pass  # risk_state_machine not available
        except Exception as rsm_err:
            logger.debug("ORCH_RSM_CHECK_ERR | %s", rsm_err)

        try:
            max_abs_util_pct = float(getattr(config, "MAX_MARGIN_UTIL_ABSOLUTE_PCT", 90.0))
        except Exception:
            max_abs_util_pct = 90.0
        try:
            max_total_margin_pct = float(getattr(config, "MAX_TOTAL_MARGIN_PCT_EQUITY", 0.50))
        except Exception:
            max_total_margin_pct = 0.50

        hard_mu_cap = min(float(max_abs_util_pct) / 100.0, float(max_total_margin_pct))
        hard_mu_cap = max(0.0, min(1.0, hard_mu_cap))
        used_margin_usd = max(0.0, float(margin_util) * float(equity))
        remaining_margin_usd = max(0.0, float(hard_mu_cap) * float(equity) - used_margin_usd)

        # ── Use available_margin_usd directly when present (most robust) ─────
        avail_margin_direct = float(portfolio.get("available_margin_usd") or 0.0)
        if avail_margin_direct > 0.0:
            free_margin_usd = max(0.0, min(float(avail_margin_direct), float(equity)))
        else:
            free_margin_usd = max(0.0, float(free_margin_ratio) * float(equity))
        safe_headroom_usd = min(float(remaining_margin_usd), float(free_margin_usd))

        meta = {
            "equity_usd": float(equity),
            "margin_util": float(margin_util),
            "free_margin_ratio": float(free_margin_ratio),
            "available_margin_usd": float(avail_margin_direct),
            "requested_margin_usd": float(req_margin),
            "remaining_margin_usd": float(remaining_margin_usd),
            "free_margin_usd": float(free_margin_usd),
            "safe_headroom_usd": float(safe_headroom_usd),
            "hard_mu_cap": float(hard_mu_cap),
        }

        if safe_headroom_usd <= 0.0:
            return False, "ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP", meta
        if float(req_margin) > float(safe_headroom_usd):
            meta["requested_over_headroom_ratio"] = float(req_margin) / max(1e-9, float(safe_headroom_usd))
            return False, "ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP", meta

        try:
            max_per_symbol_pct = float(getattr(config, "MAX_MARGIN_PER_SYMBOL_PCT_EQUITY", 0.05))
        except Exception:
            max_per_symbol_pct = 0.05
        if max_per_symbol_pct > 0.0:
            cur_symbol_margin = self._get_symbol_used_margin(account_id, symbol)
            per_symbol_cap = max(0.0, float(max_per_symbol_pct) * float(equity))
            meta["symbol_margin_used_usd"] = float(cur_symbol_margin)
            meta["symbol_margin_cap_usd"] = float(per_symbol_cap)
            _effective_cur = float(cur_symbol_margin)
            _act_u_cap = str(action or "").upper()
            _is_flip_cap = ("CLOSE" in _act_u_cap and "OPEN" in _act_u_cap) or "FLIP" in _act_u_cap
            if _is_flip_cap and _effective_cur > 0:
                _closing_side = "SHORT" if "CLOSE_SHORT" in _act_u_cap else ("LONG" if "CLOSE_LONG" in _act_u_cap else "")
                _closing_margin = 0.0
                _diag_matches = []
                if _closing_side:
                    try:
                        _pos_raw_flip = self.redis.hgetall(f"portfolio:positions:{account_id}") if self.redis else {}
                        for _fpk, _fpv in (_pos_raw_flip or {}).items():
                            try:
                                _fk = _fpk.decode("utf-8") if isinstance(_fpk, (bytes, bytearray)) else str(_fpk)
                                _fv = _fpv.decode("utf-8") if isinstance(_fpv, (bytes, bytearray)) else str(_fpv)
                                if not _fk.upper().startswith(f"{symbol.upper()}:"):
                                    continue
                                _diag_matches.append({"key": _fk, "val_preview": _fv[:200], "is_json": _fv.lstrip().startswith("{") if _fv else False})
                                _fd = json.loads(_fv) if isinstance(_fv, str) and _fv.lstrip().startswith("{") else {}
                                if isinstance(_fd, dict) and _fd:
                                    _fside = str(_fd.get("positionSide") or _fd.get("side") or _fk.split(":")[-1]).upper()
                                    if _fside == _closing_side:
                                        _closing_margin = abs(float(
                                            _fd.get("margin_used") or _fd.get("initialMargin")
                                            or _fd.get("initial_margin") or _fd.get("margin")
                                            or _fd.get("isolatedWallet") or 0
                                        ))
                                        break
                            except Exception:
                                pass
                    except Exception:
                        pass
                    if _closing_margin <= 0:
                        try:
                            _live_raw = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") if self.redis else {}
                            if _live_raw:
                                _gv = lambda v: v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                                _live_side = str(_gv(_live_raw.get(b"side") or _live_raw.get("side") or "")).upper()
                                if not _live_side:
                                    _amt = float(_gv(_live_raw.get(b"position_amt") or _live_raw.get("position_amt") or 0))
                                    _live_side = "LONG" if _amt > 0 else "SHORT" if _amt < 0 else ""
                                if _live_side == _closing_side:
                                    _closing_margin = abs(float(
                                        _gv(_live_raw.get(b"margin_used") or _live_raw.get("margin_used")
                                            or _live_raw.get(b"initialMargin") or _live_raw.get("initialMargin")
                                            or _live_raw.get(b"initial_margin") or _live_raw.get("initial_margin")
                                            or _live_raw.get(b"isolatedWallet") or _live_raw.get("isolatedWallet") or 0)
                                    ))
                        except Exception:
                            pass
                if _closing_margin > 0:
                    _effective_cur = max(0.0, _effective_cur - _closing_margin)
                else:
                    _effective_cur = 0.0
                meta["flip_margin_offset"] = True
                meta["flip_closing_side"] = _closing_side
                meta["flip_closing_margin"] = round(_closing_margin, 2)
            if per_symbol_cap > 0.0 and (_effective_cur + float(req_margin)) > float(per_symbol_cap):
                # Instead of hard-blocking, clamp req_margin to fit within the cap
                # (prevents "impossible by $1.50" caused by RBA scaling rounding up slightly)
                _epsilon = float(getattr(config, "SYMBOL_CAP_CLAMP_EPSILON_USD", 0.50))
                _clamped = float(per_symbol_cap) - float(_effective_cur) - _epsilon
                if _clamped >= float(getattr(config, "SYMBOL_CAP_CLAMP_MIN_USD", 5.0)):
                    # Clamp is viable: adjust ALL margin-derived fields so downstream
                    # checks (pair caps, audits, desired_usd) stay consistent.
                    _orig_req = float(req_margin)
                    try:
                        _lev = float(winner.get("leverage") or 1.0)
                        _notional_clamped = round(_clamped * max(1.0, _lev), 8)
                        winner["margin_usd"] = round(_clamped, 8)
                        winner["notional_usd"] = _notional_clamped
                        # Keep desired_usd / m_usd fields consistent
                        if winner.get("desired_usd") is not None:
                            winner["desired_usd"] = round(_clamped, 8)
                        if winner.get("m_usd") is not None:
                            winner["m_usd"] = round(_clamped, 8)
                        # Recalculate position_size_pct if equity available
                        if equity and float(equity) > 0:
                            winner["position_size_pct"] = round(_clamped / float(equity) * 100.0, 6)
                        req_margin = _clamped
                        meta["requested_margin_usd"] = _clamped
                        meta["symbol_cap_clamped"] = True
                        meta["symbol_cap_clamp_delta_usd"] = round(_orig_req - _clamped, 6)
                        logger.info(
                            "ORCH_SYMBOL_CAP_CLAMP | account=%s | symbol=%s | orig=%.3f | clamped=%.3f | notional=%.3f | cap=%.3f | used=%.3f",
                            account_id, symbol, _orig_req, _clamped, _notional_clamped, per_symbol_cap, cur_symbol_margin,
                        )
                    except Exception as _clamp_e:
                        logger.debug("[ORCH_SYMBOL_CAP_CLAMP] clamp error: %s", _clamp_e)
                        meta["post_symbol_margin_usd"] = float(cur_symbol_margin) + float(req_margin)
                        return False, "ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP", meta
                else:
                    meta["post_symbol_margin_usd"] = float(cur_symbol_margin) + float(req_margin)
                    meta["symbol_cap_clamp_min_fail"] = True
                    return False, "ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP", meta

        return True, None, meta

    def _feedback_reason_code(self, payload: Dict[str, Any]) -> str:
        raw_reason = ""
        for key in ("reason_code", "block_type", "reason", "error"):
            val = payload.get(key)
            if val:
                raw_reason = str(val).upper().strip()
                break

        text = self._feedback_payload_to_text(payload)
        if not raw_reason:
            status = str(payload.get("status") or "").upper().strip()
            if status in {"REJECTED", "FAILED", "BLOCKED"}:
                # Deterministic fallback for variant payloads without reason fields
                if "HEDGE_PAIR_MARGIN_CAP_BLOCK" in text or "MARGIN_CAP_BLOCK" in text:
                    raw_reason = "MARGIN_CAP_BLOCK"
                elif "TRADER_FREE_MARGIN_BLOCK" in text or "FREE_MARGIN_BLOCK" in text:
                    raw_reason = "FREE_MARGIN_BLOCK"
                elif "INSUFFICIENT_MARGIN_2019" in text or "API_2019" in text:
                    raw_reason = "INSUFFICIENT_MARGIN_2019"
                elif "INSUFFICIENT_MARGIN" in text:
                    raw_reason = "INSUFFICIENT_MARGIN"
                elif "NO_HEADROOM" in text:
                    raw_reason = "NO_HEADROOM"
                elif "MARGIN" in text:
                    raw_reason = "MARGIN_BLOCK"
                else:
                    raw_reason = "EXEC_REJECTED"

        # Normalize common variants to deterministic suppress keys
        alias = {
            "HEDGE_PAIR_MARGIN_CAP_BLOCK": "MARGIN_CAP_BLOCK",
            "TRADER_MARGIN_CAP_BLOCK": "MARGIN_CAP_BLOCK",
            "TRADER_FREE_MARGIN_BLOCK": "FREE_MARGIN_BLOCK",
            "INSUFFICIENT_MARGIN_API_2019": "INSUFFICIENT_MARGIN_2019",
            "API_ERROR_2019": "INSUFFICIENT_MARGIN_2019",
        }
        return alias.get(raw_reason, raw_reason)

    def _feedback_payload_to_text(self, payload: Dict[str, Any]) -> str:
        try:
            return json.dumps(payload, separators=(",", ":"), default=str).upper()
        except Exception:
            return str(payload).upper()

    def _classify_feedback_action_family(self, action: str) -> str:
        fam = self._action_family(str(action or "").upper().strip())
        if fam in {"OPEN_INCREASE", "HEDGE_ADD"}:
            return fam
        if "HEDGE" in str(action or "").upper():
            return "HEDGE_ADD"
        return "OPEN_INCREASE"

    def _get_symbol_live_side(self, account_id: str, symbol: str) -> str:
        if not self.redis:
            return ""
        try:
            raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
            if not raw_live:
                return ""

            def _get(v):
                return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v

            side = str(_get(raw_live.get(b"side") or raw_live.get("side") or "")).upper().strip()
            if side in {"LONG", "SHORT"}:
                return side
            try:
                amt = float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0))
            except Exception:
                amt = 0.0
            if amt > 0:
                return "LONG"
            if amt < 0:
                return "SHORT"
        except Exception:
            return ""
        return ""

    def _get_symbol_live_position_amt(self, account_id: str, symbol: str) -> float:
        if not self.redis:
            return 0.0
        try:
            raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
            if not raw_live:
                return 0.0

            def _get(v):
                return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v

            return float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0) or 0.0)
        except Exception:
            return 0.0

    def _symbol_has_live_position(self, account_id: str, symbol: str, eps: float = 1e-12) -> bool:
        try:
            return abs(float(self._get_symbol_live_position_amt(account_id, symbol))) > float(eps)
        except Exception:
            return False

    def _count_open_risk_symbols_live(self, account_id: str, eps: float = 1e-12) -> int:
        try:
            universe = list(getattr(config, "SYMBOLS", []) or [])
        except Exception:
            universe = []
        cnt = 0
        for sym in universe:
            s = str(sym or "").upper().strip()
            if not s:
                continue
            if self._symbol_has_live_position(account_id, s, eps=eps):
                cnt += 1
        return int(cnt)

    def _derive_fallback_signal(
        self,
        winner: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
        reason_code: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            enabled = bool(getattr(config, "ORCH_FALLBACK_ENABLED", getattr(config, "ORCH_FALLBACK_ON_BLOCK_ENABLED", True)))
            force_hold_on_zero = bool(getattr(config, "ORCH_FALLBACK_FORCE_HOLD_ON_EQUITY_ZERO", True))
            close_fraction = float(getattr(config, "ORCH_FALLBACK_CLOSE_FRACTION", 0.25) or 0.25)
            default_action = str(getattr(config, "ORCH_FALLBACK_DEFAULT_ACTION", "HOLD") or "HOLD").upper().strip()
            preferred_derisk_actions = [
                str(v).upper().strip()
                for v in (getattr(config, "ORCH_FALLBACK_PREFERRED_DERISK_ACTIONS", ["PARTIAL_CLOSE", "REDUCE_POSITION", "CLOSE_POSITION"]) or [])
                if str(v or "").strip()
            ]
        except Exception:
            enabled = True
            force_hold_on_zero = True
            close_fraction = 0.25
            default_action = "HOLD"
            preferred_derisk_actions = ["PARTIAL_CLOSE", "REDUCE_POSITION", "CLOSE_POSITION"]

        if not enabled:
            return None
        if bool(winner.get("_is_fallback_action")):
            return None
        if not self._is_risk_add_action(action):
            return None

        close_fraction = max(0.05, min(0.75, float(close_fraction)))
        fb = dict(winner)
        fb["_is_fallback_action"] = True
        fb["fallback_from_action"] = str(action)
        fb["fallback_reason_code"] = str(reason_code)
        fb["fallback_family"] = self._classify_feedback_action_family(action)
        fb["source"] = "orchestrator_fallback"
        fb["source_module"] = "orchestrator_fallback"
        fb["action_category"] = "PROTECTIVE"
        fb["category"] = "PROTECTIVE"
        fb["priority"] = max(2, int(fb.get("priority") or 1))
        fb["confidence"] = max(0.95, float(fb.get("confidence") or 0.0))
        _fb_now_ms = int(time.time() * 1000)
        fb["ts_ms"] = _fb_now_ms
        fb["created_ts_ms"] = _fb_now_ms
        fb["timestamp"] = time.time()
        if not str(fb.get("timeframe") or "").strip():
            fb["timeframe"] = str(winner.get("timeframe") or winner.get("tf") or "multi")
        if not str(fb.get("signal_id") or "").strip():
            fb["signal_id"] = f"fb_{int(time.time()*1000)}_{str(account_id)}_{str(symbol)}_{uuid.uuid4().hex[:6]}"

        # HOLD when account cannot deploy risk capital.
        portfolio = build_portfolio_snapshot(self.redis, account_id)
        try:
            equity = float(portfolio.get("equity") or 0.0)
        except Exception:
            equity = 0.0
        if force_hold_on_zero and equity <= 0.0:
            fb["action"] = default_action
            fb["action_name"] = default_action
            fb["action_type"] = "hold"
            # Bypass risk assertions in zero-equity mode (safe no-op control message).
            fb["action_category"] = "SYSTEM"
            fb["category"] = "SYSTEM"
            fb["reduce_only"] = True
            fb["margin_usd"] = 0.0
            fb["notional_usd"] = 0.0
            return fb

        # Prefer de-risk when there is live exposure on symbol.
        side = self._get_symbol_live_side(account_id, symbol)
        if side in {"LONG", "SHORT"}:
            chosen = "PARTIAL_CLOSE"
            for candidate in preferred_derisk_actions:
                if candidate in {"PARTIAL_CLOSE", "REDUCE_POSITION", "CLOSE_POSITION"}:
                    chosen = candidate
                    break
            if chosen == "CLOSE_POSITION":
                fb_action = f"CLOSE_{side}"
            else:
                fb_action = f"PARTIAL_CLOSE_{side}"
            fb["action"] = fb_action
            fb["action_name"] = fb_action
            fb["action_type"] = "close"
            fb["position_side"] = side
            fb["close_side"] = side
            fb["close_fraction"] = float(close_fraction)
            fb["reduce_only"] = True
            fb["profit_intent"] = False
            fb["no_loss_compliant"] = True
            reason_u = str(reason_code or "").upper().strip()
            defensive_loss = bool(
                reason_u in {
                    "ORCH_FEEDBACK_SUPPRESS_BLOCK",
                    "ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP",
                    "ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP",
                    "ORCH_IMPOSSIBLE_TRADE_MARGIN_MISSING",
                    "FREE_MARGIN_BLOCK",
                    "TRADER_FREE_MARGIN_BLOCK",
                    "MARGIN_CAP_BLOCK",
                    "HEDGE_PAIR_MARGIN_CAP_BLOCK",
                    "INSUFFICIENT_MARGIN",
                    "INSUFFICIENT_MARGIN_2019",
                    "NO_HEADROOM",
                }
                or "MARGIN" in reason_u
                or "LIQ" in reason_u
            )
            if defensive_loss:
                fb["force_loss_close"] = True
                fb["force_loss_reason"] = reason_u or "MARGIN_STRESS"
                fb["reason_code"] = reason_u or "MARGIN_STRESS"
            fb["margin_usd"] = 0.0
            fb["notional_usd"] = 0.0
            return fb

        # No exposure to reduce: safe no-op.
        fb["action"] = default_action
        fb["action_name"] = default_action
        fb["action_type"] = "hold"
        fb["reduce_only"] = True
        fb["margin_usd"] = 0.0
        fb["notional_usd"] = 0.0
        return fb

    def _maybe_publish_fallback_on_block(
        self,
        winner: Dict[str, Any],
        proof: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
        reason_code: str,
        reason_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        try:
            enabled = bool(getattr(config, "ORCH_FALLBACK_ENABLED", getattr(config, "ORCH_FALLBACK_ON_BLOCK_ENABLED", True)))
            on_codes_cfg = getattr(config, "ORCH_FALLBACK_ON_CODES", {
                "ORCH_FEEDBACK_SUPPRESS_BLOCK",
                "ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP",
                "ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP",
                "ORCH_IMPOSSIBLE_TRADE_MARGIN_MISSING",
                "ORCH_IMPOSSIBLE_TRADE_EQUITY_ZERO",
            })
            on_codes = {str(v).upper().strip() for v in (on_codes_cfg or []) if str(v or "").strip()}
        except Exception:
            enabled = True
            on_codes = {
                "ORCH_FEEDBACK_SUPPRESS_BLOCK",
                "ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP",
                "ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP",
                "ORCH_IMPOSSIBLE_TRADE_MARGIN_MISSING",
                "ORCH_IMPOSSIBLE_TRADE_EQUITY_ZERO",
            }

        if not enabled:
            return None
        if str(reason_code or "").upper().strip() not in on_codes:
            return None

        fallback = self._derive_fallback_signal(
            winner,
            account_id=account_id,
            symbol=symbol,
            action=action,
            reason_code=reason_code,
        )
        if not fallback:
            return None

        fb_plan_id = self._publish_winner(fallback, {"fallback": True, "parent_reason": reason_code})
        if not fb_plan_id:
            try:
                self._publish_exec_event(
                    code="ORCH_FALLBACK_SKIPPED",
                    account_id=account_id,
                    symbol=symbol,
                    action=str(fallback.get("action") or fallback.get("action_name") or "HOLD"),
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta={
                        "from_action": str(action),
                        "reason_code": str(reason_code),
                        "fallback_action": str(fallback.get("action") or fallback.get("action_name") or "HOLD"),
                        "fallback_family": str(fallback.get("fallback_family") or ""),
                        "reason_meta": reason_meta or {},
                    },
                )
            except Exception:
                pass
            return None

        try:
            self._publish_exec_event(
                code="ORCH_FALLBACK_PUBLISHED",
                account_id=account_id,
                symbol=symbol,
                action=str(fallback.get("action") or fallback.get("action_name") or "HOLD"),
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta={
                    "from_action": str(action),
                    "reason_code": str(reason_code),
                    "plan_id": str(fb_plan_id),
                    "fallback_action": str(fallback.get("action") or fallback.get("action_name") or "HOLD"),
                    "fallback_family": str(fallback.get("fallback_family") or ""),
                    "reason_meta": reason_meta or {},
                },
            )
        except Exception:
            pass

        logger.warning(
            "ORCH_FALLBACK_PUBLISHED | account=%s | symbol=%s | from=%s | to=%s | reason=%s | plan_id=%s",
            account_id,
            symbol,
            action,
            str(fallback.get("action") or fallback.get("action_name") or "HOLD"),
            reason_code,
            fb_plan_id,
        )
        return fb_plan_id

    def _consume_execution_feedback(self, now_ms: int) -> None:
        if not self.redis:
            return
        if not self.orch_feedback_suppress_enabled:
            return
        if (now_ms - int(self._last_feedback_poll_ms or 0)) < int(self.orch_feedback_poll_sec * 1000):
            return
        self._last_feedback_poll_ms = now_ms

        # Bootstrap once with a concrete stream id (never use "$" repeatedly;
        # it can miss entries between polls).
        if not self._feedback_stream_last_id:
            try:
                latest = self.redis.xrevrange(self.orch_feedback_stream, "+", "-", count=1)
                if latest:
                    self._feedback_stream_last_id = str(latest[0][0])
                else:
                    self._feedback_stream_last_id = "0-0"
            except Exception:
                self._feedback_stream_last_id = "0-0"

        try:
            entries = self.redis.xread(
                {self.orch_feedback_stream: self._feedback_stream_last_id},
                count=int(self.orch_feedback_read_count),
                block=max(100, int(self.orch_feedback_poll_sec * 1000)),
            )
        except Exception:
            entries = []

        if not entries:
            return

        now = int(time.time() * 1000)
        ttl_ms = int(max(30, self.orch_feedback_suppress_ttl_sec) * 1000)

        for _, stream_messages in entries:
            for msg_id, msg_data in stream_messages:
                self._feedback_stream_last_id = str(msg_id)
                try:
                    raw = msg_data.get("data") if isinstance(msg_data, dict) else None
                    if raw is None and isinstance(msg_data, dict):
                        raw = msg_data.get(b"data")
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="ignore")
                    payload = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
                    if not isinstance(payload, dict):
                        continue

                    event_type = str(payload.get("event_type") or "").upper().strip()
                    status = str(payload.get("status") or "").upper().strip()
                    if event_type not in {"EXEC_EVENT", "SIGNAL_BLOCKED"}:
                        continue
                    if event_type == "EXEC_EVENT" and status not in {"REJECTED", "FAILED", "BLOCKED", ""}:
                        continue

                    reason_code = self._feedback_reason_code(payload)
                    payload_text = self._feedback_payload_to_text(payload)
                    if not reason_code:
                        continue
                    if (reason_code not in self.orch_feedback_reason_codes) and ("MARGIN" not in payload_text):
                        continue

                    account_id = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower()
                    symbol = str(payload.get("symbol") or "").strip().upper()
                    action = str(payload.get("action") or payload.get("action_name") or "").strip().upper()
                    if not symbol:
                        continue
                    fam = self._classify_feedback_action_family(action)
                    until_ms = now + ttl_ms
                    state = {
                        "reason_code": reason_code,
                        "event_type": event_type,
                        "source_msg_id": str(msg_id),
                        "last_ts_ms": int(payload.get("ts_ms") or now),
                        "until_ms": int(until_ms),
                    }
                    self._feedback_block_state[(account_id, symbol, fam)] = state
                    self._feedback_block_state[(account_id, symbol, "RISK_ADD")] = dict(state)
                    logger.warning(
                        "ORCH_FEEDBACK_BLOCK_ARMED | account=%s | symbol=%s | family=%s | reason=%s | ttl_sec=%s",
                        account_id,
                        symbol,
                        fam,
                        reason_code,
                        int(self.orch_feedback_suppress_ttl_sec),
                    )
                    self._publish_exec_event(
                        code="ORCH_FEEDBACK_BLOCK_ARMED",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id="",
                        meta={
                            "reason_code": reason_code,
                            "family": fam,
                            "ttl_sec": int(self.orch_feedback_suppress_ttl_sec),
                            "until_ts_ms": int(until_ms),
                            "event_type": event_type,
                            "source_msg_id": str(msg_id),
                        },
                    )
                except Exception:
                    continue

        # Expire stale blocks
        for key in list(self._feedback_block_state.keys()):
            st = self._feedback_block_state.get(key) or {}
            if int(st.get("until_ms") or 0) <= now:
                self._feedback_block_state.pop(key, None)

    def _feedback_suppression_gate(self, account_id: str, symbol: str, action: str) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        if not self.orch_feedback_suppress_enabled:
            return True, None, {}
        if not self._is_risk_add_action(action):
            return True, None, {}

        now = int(time.time() * 1000)
        fam = self._classify_feedback_action_family(action)
        keys = [
            (account_id, symbol, fam),
            (account_id, symbol, "RISK_ADD"),
        ]
        for k in keys:
            st = self._feedback_block_state.get(k)
            if not st:
                continue
            until_ms = int(st.get("until_ms") or 0)
            if until_ms <= now:
                self._feedback_block_state.pop(k, None)
                continue
            reason_code = str(st.get("reason_code") or "UNKNOWN").upper().strip()
            meta = {
                "reason_code": reason_code,
                "family": fam,
                "until_ms": until_ms,
                "remaining_ms": int(max(0, until_ms - now)),
                "source_msg_id": str(st.get("source_msg_id") or ""),
            }
            return False, f"ORCH_FEEDBACK_SUPPRESS_{reason_code}", meta
        return True, None, {}

    def _kill_switch_active(self, account_id: Optional[str] = None, symbol: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
        return get_kill_switch(self.redis, account=account_id, symbol=symbol)

    def _hedge_score(self, proposal: Dict[str, Any]) -> Tuple[int, float]:
        """Score hedge proposals: priority first, then confidence."""
        try:
            pri = int(proposal.get("priority") or 1)
        except Exception:
            pri = 1
        try:
            conf = float(proposal.get("confidence") or proposal.get("model_confidence") or 0.0)
        except Exception:
            conf = 0.0
        return pri, conf

    def _symbol_bucket(self, symbol: str) -> str:
        sym = str(symbol or "").upper().strip()
        if sym in {"BTCUSDT", "ETHUSDT"}:
            return "major"
        try:
            from config import SYMBOL_LEVERAGE_CONFIG
        except Exception:
            SYMBOL_LEVERAGE_CONFIG = {}
        try:
            lev_cfg = SYMBOL_LEVERAGE_CONFIG.get(sym) or {}
            max_lev = float(lev_cfg.get("max_leverage") or 0.0)
        except Exception:
            max_lev = 0.0
        if max_lev and max_lev <= 15:
            return "meme"
        return "alt"

    def _extract_liq_distance_pct(self, payload: Dict[str, Any]) -> Optional[float]:
        # Check pos_liq first (leverage-derived, preferred for safety)
        try:
            if "pos_liq_distance_pct" in payload:
                return float(payload.get("pos_liq_distance_pct"))
        except Exception:
            pass
        for key in ("liq_distance_pct", "liquidation_distance_pct", "min_liq_distance_pct"):
            try:
                if key in payload:
                    return float(payload.get(key))
            except Exception:
                pass
        if isinstance(payload.get("metadata"), dict):
            try:
                prox = payload.get("metadata", {}).get("liquidation_proximity") or {}
                if isinstance(prox, dict) and prox.get("distance_pct") is not None:
                    return float(prox.get("distance_pct"))
            except Exception:
                pass
        return None

    def _fallback_liq_from_leverage(self, payload: Dict[str, Any]) -> Optional[float]:
        try:
            lev = payload.get("leverage") or payload.get("recommended_leverage")
            if lev is None and isinstance(payload.get("metadata"), dict):
                lev = payload.get("metadata", {}).get("leverage")
            lev = float(lev) if lev is not None else 0.0
        except Exception:
            lev = 0.0
        if lev > 0:
            try:
                return max(0.0, 100.0 / lev)
            except Exception:
                return None
        return None

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        try:
            if val is None:
                return None
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8", errors="ignore")
            return float(val)
        except Exception:
            return None

    @staticmethod
    def _decode_hash(raw: Dict[str, Any]) -> Dict[str, Any]:
        decoded: Dict[str, Any] = {}
        for k, v in (raw or {}).items():
            try:
                kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
            except Exception:
                kk = str(k)
            if isinstance(v, (bytes, bytearray)):
                try:
                    vv: Any = v.decode("utf-8", errors="ignore")
                except Exception:
                    vv = v
            else:
                vv = v
            decoded[kk] = vv
        return decoded

    def _read_unified_features(self, symbol: str, tf: str) -> Dict[str, Any]:
        if not self.redis:
            return {}
        h = {}
        try:
            raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}") or {}
            h = self._decode_hash(raw)
        except Exception:
            h = {}
        if not h:
            try:
                raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}:latest") or {}
                h = self._decode_hash(raw)
            except Exception:
                h = {}
        return h

    def _get_recent_ohlc(self, symbol: str, tf_candidates: List[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        for tf0 in tf_candidates:
            feats = self._read_unified_features(symbol, tf0)
            if not feats:
                continue
            low = self._safe_float(feats.get("low"))
            high = self._safe_float(feats.get("high"))
            if low is not None or high is not None:
                return low, high, tf0
        return None, None, None

    def _get_price_ref(self, symbol: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[Optional[float], str]:
        ref = ""
        price = None
        if isinstance(payload, dict):
            ref = str(payload.get("price_ref") or payload.get("price_source") or "").strip().lower()
            price = self._safe_float(
                payload.get("price_ref_value")
                or payload.get("current_price")
                or payload.get("mark_price")
                or payload.get("price")
            )
        if price is None and self.redis:
            try:
                price = self._safe_float(self.redis.get(f"price:{symbol}"))
            except Exception:
                price = None
            if not ref:
                ref = "mark"
        if not ref:
            ref = "unknown"
        return price, ref

    def _extract_coverage_ratio(self, payload: Dict[str, Any], meta_blob: Dict[str, Any]) -> Optional[float]:
        keys = [
            "hedge_coverage_ratio",
            "coverage_ratio",
            "hedge_coverage",
            "coverage",
            "portfolio_hedge_coverage",
        ]
        for key in keys:
            val = self._safe_float(payload.get(key))
            if val is None:
                val = self._safe_float(meta_blob.get(key))
            if val is not None:
                return float(val)
        return None

    def _extract_bias_score(self, payload: Dict[str, Any], meta_blob: Dict[str, Any]) -> float:
        # Normalize to [-1, 1] where +1 bullish, -1 bearish.
        score = None
        for key in ("bias_score", "mtf_bias_score", "market_bias_score", "context_bias_score"):
            v = self._safe_float(payload.get(key))
            if v is None:
                v = self._safe_float(meta_blob.get(key))
            if v is not None:
                score = float(v)
                break

        if score is None:
            label = ""
            for key in ("bias", "market_bias", "htf_bias", "mtf_bias", "context_bias"):
                raw = payload.get(key) if payload.get(key) is not None else meta_blob.get(key)
                if raw is not None:
                    label = str(raw).strip().upper()
                    break
            if "BULL" in label:
                score = 1.0
            elif "BEAR" in label:
                score = -1.0
            else:
                score = 0.0

        if score > 1.0:
            score = min(1.0, score / 100.0)
        if score < -1.0:
            score = max(-1.0, score / 100.0)
        return float(max(-1.0, min(1.0, score)))

    def _compute_policy_velocities(
        self,
        account_id: str,
        symbol: str,
        price: Optional[float],
        now_ms: int,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        if price is None or price <= 0:
            return None, None, None, None
        key = f"{account_id}:{symbol}"
        st = self._policy_price_state.get(key) or {}
        v60: List[Tuple[int, float]] = list(st.get("v60") or [])
        v60.append((int(now_ms), float(price)))
        cutoff_60 = int(now_ms) - 60000
        v60 = [pt for pt in v60 if int(pt[0]) >= cutoff_60 and float(pt[1]) > 0]

        def _vel(window_ms: int) -> Tuple[Optional[float], Optional[float]]:
            cutoff = int(now_ms) - int(window_ms)
            pts = [pt for pt in v60 if int(pt[0]) >= cutoff]
            if not pts:
                return None, None
            base = float(pts[0][1])
            if base <= 0:
                return None, None
            signed = (float(price) - base) / base * 10000.0
            return abs(signed), signed

        vel_15, signed_15 = _vel(15000)
        vel_60, signed_60 = _vel(60000)
        self._policy_price_state[key] = {"ts_ms": int(now_ms), "price": float(price), "v60": v60}
        return vel_15, vel_60, signed_15, signed_60

    def _derive_shock_state(
        self,
        account_id: str,
        symbol: str,
        *,
        now_ms: int,
        stress: bool,
        price: Optional[float],
        signed_15_bps: Optional[float],
        signed_60_bps: Optional[float],
        reversal_delta_bps: float,
        candidate_ticks_required: int,
        recovery_ticks_required: int,
    ) -> Dict[str, Any]:
        key = f"{account_id}:{symbol}"
        prev = dict(self._policy_shock_state.get(key) or {})

        prev_state = str(prev.get("state") or "NORMAL").upper()
        prev_reversal_to = str(prev.get("reversal_to") or "").upper()
        prev_candidate_ticks = int(prev.get("candidate_ticks") or 0)
        prev_recovery_ticks = int(prev.get("recovery_ticks") or 0)

        signed_15 = self._safe_float(signed_15_bps)
        signed_60 = self._safe_float(signed_60_bps)
        rev_threshold = max(1.0, float(reversal_delta_bps))

        direction = ""
        if signed_15 is not None and float(signed_15) <= -rev_threshold:
            direction = "DOWN"
        elif signed_15 is not None and float(signed_15) >= rev_threshold:
            direction = "UP"
        elif signed_60 is not None and float(signed_60) <= -rev_threshold:
            direction = "DOWN"
        elif signed_60 is not None and float(signed_60) >= rev_threshold:
            direction = "UP"

        state = prev_state
        reversal_to = prev_reversal_to
        candidate_ticks = prev_candidate_ticks
        recovery_ticks = prev_recovery_ticks

        if stress and direction in {"DOWN", "UP"}:
            target_state = f"STRESS_{direction}"
            if prev_state == "NORMAL":
                state = target_state
                reversal_to = ""
                candidate_ticks = 0
                recovery_ticks = 0
            elif prev_state.startswith("STRESS_"):
                prev_dir = prev_state.replace("STRESS_", "", 1)
                if prev_dir == direction:
                    state = target_state
                    reversal_to = ""
                    candidate_ticks = 0
                    recovery_ticks = 0
                else:
                    state = "REVERSAL_CANDIDATE"
                    reversal_to = direction
                    candidate_ticks = 1
                    recovery_ticks = 0
            elif prev_state == "REVERSAL_CANDIDATE":
                if direction and direction == prev_reversal_to:
                    candidate_ticks = int(prev_candidate_ticks) + 1
                    if candidate_ticks >= int(max(1, candidate_ticks_required)):
                        state = "REVERSAL_CONFIRMED"
                    else:
                        state = "REVERSAL_CANDIDATE"
                    reversal_to = direction
                    recovery_ticks = 0
                else:
                    state = target_state
                    reversal_to = ""
                    candidate_ticks = 0
                    recovery_ticks = 0
            elif prev_state == "REVERSAL_CONFIRMED":
                if direction and direction == prev_reversal_to:
                    state = "REVERSAL_CONFIRMED"
                    reversal_to = direction
                    recovery_ticks = 0
                else:
                    state = target_state
                    reversal_to = ""
                    candidate_ticks = 0
                    recovery_ticks = 0
            else:
                state = target_state
                reversal_to = ""
                candidate_ticks = 0
                recovery_ticks = 0
        else:
            if prev_state in {"STRESS_DOWN", "STRESS_UP", "REVERSAL_CANDIDATE", "REVERSAL_CONFIRMED"}:
                recovery_ticks = int(prev_recovery_ticks) + 1
                if recovery_ticks >= int(max(1, recovery_ticks_required)):
                    state = "NORMAL"
                    reversal_to = ""
                    candidate_ticks = 0
                    recovery_ticks = 0
                else:
                    if prev_state == "REVERSAL_CANDIDATE" and prev_reversal_to and direction == prev_reversal_to:
                        state = "REVERSAL_CONFIRMED"
                        reversal_to = prev_reversal_to
                        candidate_ticks = max(prev_candidate_ticks, 1)
                    else:
                        state = prev_state
                        reversal_to = prev_reversal_to
                        candidate_ticks = prev_candidate_ticks
            else:
                state = "NORMAL"
                reversal_to = ""
                candidate_ticks = 0
                recovery_ticks = 0

        out = {
            "state": state,
            "direction": direction,
            "reversal_to": reversal_to,
            "candidate_ticks": int(candidate_ticks),
            "recovery_ticks": int(recovery_ticks),
            "stress": bool(stress),
            "updated_ms": int(now_ms),
        }
        if price is not None and price > 0:
            out["price"] = float(price)

        if prev_state != state:
            logger.info(
                "ORCH_SHOCK_STATE_TRANSITION | account=%s | symbol=%s | from=%s | to=%s | direction=%s | reversal_to=%s | stress=%s",
                account_id,
                symbol,
                prev_state,
                state,
                direction,
                reversal_to,
                bool(stress),
            )

        self._policy_shock_state[key] = out
        return out

    def _derive_portfolio_stress(
        self,
        account_id: str,
        *,
        now_ms: int,
        min_symbols: int,
        min_fraction: float,
        decay_ms: int,
    ) -> Dict[str, Any]:
        prev = dict(self._policy_portfolio_stress_state.get(account_id) or {})
        threshold_symbols = max(1, int(min_symbols))
        threshold_fraction = max(0.0, min(1.0, float(min_fraction)))
        freshness_cutoff = int(now_ms) - max(1000, int(decay_ms))

        symbols_total = 0
        symbols_stressed = 0
        for key, st in list(self._policy_shock_state.items()):
            if not key.startswith(f"{account_id}:"):
                continue
            updated_ms = int(st.get("updated_ms") or 0)
            if updated_ms < freshness_cutoff:
                continue
            symbols_total += 1
            state = str(st.get("state") or "NORMAL").upper()
            if state in {"STRESS_DOWN", "STRESS_UP", "REVERSAL_CANDIDATE"}:
                symbols_stressed += 1

        stressed_fraction = float(symbols_stressed) / float(max(1, symbols_total))
        active = bool(symbols_stressed >= threshold_symbols and stressed_fraction >= threshold_fraction)

        out = {
            "active": active,
            "symbols_stressed": int(symbols_stressed),
            "symbols_total": int(symbols_total),
            "stress_fraction": stressed_fraction,
            "updated_ms": int(now_ms),
        }

        if bool(prev.get("active")) != active:
            logger.warning(
                "ORCH_PORTFOLIO_STRESS_%s | account=%s | stressed=%s | total=%s | fraction=%.3f",
                "ON" if active else "OFF",
                account_id,
                symbols_stressed,
                symbols_total,
                stressed_fraction,
            )

        self._policy_portfolio_stress_state[account_id] = out
        return out

    # ── Hedge Shock Manager ──────────────────────────────────────────────────

    def _get_hedge_legs(self, account_id: str, symbol: str) -> Dict[str, Dict[str, Any]]:
        """Read both LONG/SHORT position legs from portfolio:positions:{account_id}.

        Returns dict like {"LONG": {...}, "SHORT": {...}} with parsed leg data.
        Only includes legs with size > 0.
        """
        if not self.redis:
            return {}
        try:
            key = f"portfolio:positions:{account_id}"
            result: Dict[str, Dict[str, Any]] = {}
            for side in ("LONG", "SHORT"):
                raw = self.redis.hget(key, f"{symbol}:{side}")
                if not raw:
                    continue
                try:
                    val = raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore")
                    data = json.loads(val)
                    sz = float(data.get("size") or data.get("position_amt") or 0)
                    if sz > 0:
                        data["_side"] = side
                        result[side] = data
                except Exception:
                    continue
            if result:
                return result
            # Legacy fallback: nested long/short JSON on positions:live:{account}:{symbol}
            try:
                raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}

                def _gv(field: str) -> str:
                    v = raw_live.get(field) or raw_live.get(field.encode() if isinstance(field, str) else field)
                    if v is None:
                        return ""
                    return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)

                for side_key, side_const in (("long", "LONG"), ("short", "SHORT")):
                    blob = _gv(side_key)
                    if not blob or not blob.strip().startswith("{"):
                        continue
                    try:
                        data = json.loads(blob)
                        if not isinstance(data, dict) or not data.get("has_position"):
                            continue
                        sz = float(data.get("size") or data.get("position_amt") or 0)
                        if sz > 0:
                            data["_side"] = side_const
                            result[side_const] = data
                    except Exception:
                        continue
            except Exception:
                pass
            return result
        except Exception:
            return {}

    def _hedge_shock_eval(
        self,
        account_id: str,
        symbol: str,
        proposed_action: str,
        winner: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Hedge shock manager — pre-publish evaluation for hedged positions.

        Called before every publish in _publish_winner.
        Leverages the existing _derive_shock_state stress detection to protect
        hedge legs during fast moves:
          - Blocks entries adding to the losing side during shock
          - Cuts losing leg when ROE exceeds threshold + cooldown met
          - Escalates cut fraction when margin_util is critical (≥0.93)
          - Locks winning-leg profits on retracement from peak
          - Pair-action gap: suppresses winner-lock if a loser-cut happened
            within PAIR_ACTION_GAP_SEC (prevents trim-both-legs bleed)
          - Enforces one-leg-only rule, hysteresis, and hourly anti-churn cap

        Returns None (passthrough) or dict with:
          verdict:  BLOCK | OVERRIDE | BLOCK_AND_OVERRIDE
          reason:   exec event reason code
          derisk_action:   replacement action (for OVERRIDE verdicts)
          derisk_side:     target position side
          derisk_fraction: fraction to close
          derisk_event_code: exec event code for the de-risk
          meta:     detail dict for logging/telemetry
        """
        try:
            now = time.time()
            sym = str(symbol or "").upper().strip()
            acct = str(account_id or "").lower().strip()
            if not sym or not acct:
                return None

            # ── 1. Read hedge legs ────────────────────────────────────────
            legs = self._get_hedge_legs(acct, sym)
            if len(legs) < 2:
                return None  # Not hedged → passthrough

            long_leg = legs.get("LONG", {})
            short_leg = legs.get("SHORT", {})

            # ── 2. Get shock state from existing state machine ────────────
            shock_key = f"{acct}:{sym}"
            shock = self._policy_shock_state.get(shock_key) or {}
            shock_state = str(shock.get("state") or "NORMAL").upper()
            shock_direction = str(shock.get("direction") or "").upper()

            is_stressed = shock_state in {
                "STRESS_UP", "STRESS_DOWN",
                "REVERSAL_CANDIDATE", "REVERSAL_CONFIRMED",
            }

            # ── 3. Track consecutive stress ticks (hysteresis) ────────────
            mgr = self._hedge_shock_mgr_state.get(shock_key)
            if mgr is None:
                mgr = {
                    "stress_consec_ticks": 0,
                    "last_loser_cut_ts": 0.0,
                    "last_winner_lock_ts": 0.0,
                    "winner_peak_roe": 0.0,
                    "winner_peak_side": "",
                    "actions_log": [],
                }
                self._hedge_shock_mgr_state[shock_key] = mgr

            if is_stressed:
                mgr["stress_consec_ticks"] = int(mgr.get("stress_consec_ticks") or 0) + 1
            else:
                mgr["stress_consec_ticks"] = 0
                mgr["winner_peak_roe"] = 0.0
                mgr["winner_peak_side"] = ""
                return None  # Not stressed → passthrough

            stress_ticks = int(mgr.get("stress_consec_ticks") or 0)

            # Hysteresis: require N consecutive stress ticks before acting
            if stress_ticks < self.orch_hedge_shock_stress_ticks_min:
                logger.debug(
                    "ORCH_HEDGE_SHOCK_HYSTERESIS | account=%s | symbol=%s | ticks=%d/%d",
                    acct, sym, stress_ticks, self.orch_hedge_shock_stress_ticks_min,
                )
                return None

            # ── 4. Determine winning / losing legs ────────────────────────
            long_roe = float(long_leg.get("roi_pct") or long_leg.get("roe") or 0)
            short_roe = float(short_leg.get("roi_pct") or short_leg.get("roe") or 0)

            if long_roe >= short_roe:
                winner_side, loser_side = "LONG", "SHORT"
                winner_roe, loser_roe = long_roe, short_roe
            else:
                winner_side, loser_side = "SHORT", "LONG"
                winner_roe, loser_roe = short_roe, long_roe

            # Track winner peak ROE for retracement detection
            if winner_roe > float(mgr.get("winner_peak_roe") or 0):
                mgr["winner_peak_roe"] = float(winner_roe)
                mgr["winner_peak_side"] = winner_side
            peak_roe = float(mgr.get("winner_peak_roe") or 0)

            # ── 5. Anti-churn: max actions per hour ───────────────────────
            cutoff_hr = now - 3600.0
            mgr["actions_log"] = [
                (t, a) for t, a in (mgr.get("actions_log") or [])
                if float(t) > cutoff_hr
            ]
            hourly_count = len(mgr.get("actions_log") or [])
            churn_limited = hourly_count >= self.orch_hedge_shock_max_actions_hourly

            if churn_limited:
                logger.info(
                    "ORCH_HEDGE_SHOCK_CHURN_LIMIT | account=%s | symbol=%s | "
                    "actions_this_hour=%d | max=%d",
                    acct, sym, hourly_count,
                    self.orch_hedge_shock_max_actions_hourly,
                )

            # ── 5b. Read margin utilization + equity for escalation ────────
            margin_util = 0.0
            shock_equity = 0.0
            try:
                mu = winner.get("margin_util")
                eq = winner.get("equity") or winner.get("equity_usd")
                if (mu is None or eq is None) and self.redis:
                    raw_ps = self.redis.get(f"portfolio:state:{acct}")
                    if raw_ps:
                        if isinstance(raw_ps, (bytes, bytearray)):
                            raw_ps = raw_ps.decode("utf-8", errors="ignore")
                        ps_data = json.loads(raw_ps) if isinstance(raw_ps, str) else {}
                        if mu is None:
                            mu = ps_data.get("margin_util") or ps_data.get("margin_ratio")
                        if eq is None:
                            eq = ps_data.get("equity") or ps_data.get("total_wallet_balance")
                margin_util = float(mu or 0)
                shock_equity = float(eq or 0)
            except Exception:
                margin_util = 0.0
                shock_equity = 0.0
            margin_critical = margin_util >= self.orch_hedge_shock_margin_crit_threshold

            # ── 6. Check if proposal adds to losing side → BLOCK ──────────
            proposed_u = str(proposed_action or "").upper().strip()
            is_open_risk = any(
                tok in proposed_u
                for tok in ("OPEN", "INCREASE", "ADD", "CLOSE_AND")
            )
            adds_to_loser = False
            if is_open_risk and self.orch_hedge_shock_block_add_to_loser:
                if ("LONG" in proposed_u and loser_side == "LONG") or \
                   ("SHORT" in proposed_u and loser_side == "SHORT"):
                    adds_to_loser = True

            meta_base = {
                "shock_state": shock_state,
                "shock_direction": shock_direction,
                "stress_ticks": stress_ticks,
                "long_roe_pct": round(long_roe, 2),
                "short_roe_pct": round(short_roe, 2),
                "winner_side": winner_side,
                "loser_side": loser_side,
                "winner_roe_pct": round(winner_roe, 2),
                "loser_roe_pct": round(loser_roe, 2),
                "peak_roe_pct": round(peak_roe, 2),
                "hourly_actions": hourly_count,
                "margin_util": round(margin_util, 4),
                "margin_critical": margin_critical,
            }

            # ── 7. Compute effective loser cut fraction (escalation) ──────
            base_cut_fraction = float(self.orch_hedge_shock_loser_cut_fraction)
            if margin_critical:
                esc_frac = float(self.orch_hedge_shock_margin_crit_cut_fraction)
                effective_cut_fraction = max(base_cut_fraction, esc_frac)
                meta_base["cut_fraction_escalated"] = True
                meta_base["cut_fraction_base"] = round(base_cut_fraction, 3)
                meta_base["cut_fraction_effective"] = round(effective_cut_fraction, 3)
            else:
                effective_cut_fraction = base_cut_fraction

            # ── 7b. Crash-escalation: violent move + MU stressed → 35% cut ──
            # All 3 conditions must be true: fast_move ≥ 0.7, ROE delta ≤ -2%, MU ≥ 0.5
            crash_escalated = False
            if self.orch_hedge_shock_crash_escalation_enabled:
                crash_fast_move = self._safe_float(
                    winner.get("fast_move_score")
                    or winner.get("micro_fast_move_score")
                    or winner.get("depth_fast_move_score")
                ) or 0.0
                # Read loser ROE delta from manager state (computed in Step 8b, but we need it here)
                prev_loser_roe_early = float(mgr.get("prev_loser_roe") or loser_roe)
                crash_roe_delta = loser_roe - prev_loser_roe_early

                crash_conditions_met = (
                    crash_fast_move >= self.orch_hedge_shock_crash_fast_move_min
                    and crash_roe_delta <= self.orch_hedge_shock_crash_roe_delta_max
                    and margin_util >= self.orch_hedge_shock_crash_margin_util_min
                )
                if crash_conditions_met:
                    crash_cut = float(self.orch_hedge_shock_crash_cut_fraction)
                    effective_cut_fraction = max(effective_cut_fraction, crash_cut)
                    crash_escalated = True
                    meta_base["crash_escalated"] = True
                    meta_base["crash_fast_move"] = round(crash_fast_move, 3)
                    meta_base["crash_roe_delta"] = round(crash_roe_delta, 2)
                    meta_base["crash_margin_util"] = round(margin_util, 4)
                    meta_base["cut_fraction_effective"] = round(effective_cut_fraction, 3)
                    logger.warning(
                        "ORCH_HEDGE_SHOCK_CRASH_ESCALATION | account=%s | symbol=%s | "
                        "fast_move=%.3f(≥%.2f) | roe_delta=%.2f(≤%.1f) | mu=%.4f(≥%.2f) | "
                        "cut_fraction=%.2f | loser=%s(%.1f%%)",
                        acct, sym,
                        crash_fast_move, self.orch_hedge_shock_crash_fast_move_min,
                        crash_roe_delta, self.orch_hedge_shock_crash_roe_delta_max,
                        margin_util, self.orch_hedge_shock_crash_margin_util_min,
                        effective_cut_fraction, loser_side, loser_roe,
                    )

            # ── 8. Evaluate LOSER CUT eligibility ────────────────────────
            loser_cooldown_remaining = max(
                0.0,
                float(self.orch_hedge_shock_loser_cooldown_sec)
                - (now - float(mgr.get("last_loser_cut_ts") or 0)),
            )
            loser_cooldown_ok = loser_cooldown_remaining <= 0.0

            loser_cut_ok = (
                not churn_limited
                and loser_roe <= self.orch_hedge_shock_loser_roe_threshold_pct
                and loser_cooldown_ok
            )

            # ── 8b. Momentum guard: loser cut requires real momentum ─────
            # Prevents slow-drift trims every 3 minutes when shock lingers.
            # Require EITHER fast_move_score >= threshold OR ROE worsening.
            momentum_confirmed = True  # default pass when guard disabled
            fast_move_score = None
            loser_roe_delta = 0.0
            fast_move_confirmed = False
            roe_worsening = False

            if self.orch_hedge_shock_loser_cut_require_momentum and loser_cut_ok:
                # Read fast_move_score from winner dict (same source as _derive_shock_state)
                fast_move_score = self._safe_float(
                    winner.get("fast_move_score")
                    or winner.get("micro_fast_move_score")
                    or winner.get("depth_fast_move_score")
                )

                # Track loser ROE delta (worsening since last check)
                prev_loser_roe = float(mgr.get("prev_loser_roe") or loser_roe)
                loser_roe_delta = loser_roe - prev_loser_roe

                fast_move_confirmed = (
                    fast_move_score is not None
                    and fast_move_score >= self.orch_hedge_shock_loser_cut_min_fast_move
                )
                roe_worsening = loser_roe_delta <= self.orch_hedge_shock_loser_cut_min_roe_delta

                momentum_confirmed = fast_move_confirmed or roe_worsening

                if not momentum_confirmed:
                    loser_cut_ok = False
                    logger.info(
                        "ORCH_HEDGE_SHOCK_MOMENTUM_GUARD | account=%s | symbol=%s | "
                        "loser_cut_suppressed | fast_move=%.3f(need>=%.2f) | "
                        "roe_delta=%.2f(need<=%.1f) | loser=%s(%.1f%%)",
                        acct, sym,
                        float(fast_move_score or 0),
                        self.orch_hedge_shock_loser_cut_min_fast_move,
                        loser_roe_delta,
                        self.orch_hedge_shock_loser_cut_min_roe_delta,
                        loser_side, loser_roe,
                    )

            # Always track prev_loser_roe for next cycle delta
            mgr["prev_loser_roe"] = float(loser_roe)

            # Enrich meta_base with momentum + cooldown observability
            meta_base["fast_move_score"] = round(float(fast_move_score or 0), 3)
            meta_base["loser_roe_delta"] = round(loser_roe_delta, 3)
            meta_base["fast_move_confirmed"] = fast_move_confirmed
            meta_base["roe_worsening"] = roe_worsening
            meta_base["momentum_confirmed"] = momentum_confirmed
            meta_base["loser_cooldown_remaining_sec"] = round(loser_cooldown_remaining, 1)

            # ── 9. Evaluate WINNER LOCK eligibility ──────────────────────
            retrace_from_peak = 0.0
            if peak_roe > 0 and winner_roe < peak_roe:
                retrace_from_peak = ((peak_roe - winner_roe) / peak_roe) * 100.0

            # Pair-action gap: suppress winner-lock if a loser-cut happened
            # within the gap window (prevents trim-both-legs bleed).
            last_loser_ts = float(mgr.get("last_loser_cut_ts") or 0)
            pair_gap_sec = float(self.orch_hedge_shock_pair_action_gap_sec)
            pair_gap_blocked = (now - last_loser_ts) < pair_gap_sec

            # ── 9b. Winner-lock margin + suppression + equity guard ────────
            # Disable winner-lock when margin is stressed (preserve cushion),
            # when feedback suppression is armed (trader already rejecting),
            # or when equity is below micro-account threshold (preserve asymmetry).
            margin_gate_blocked = margin_util >= self.orch_hedge_shock_winner_lock_margin_gate
            equity_gate_blocked = shock_equity < self.orch_hedge_shock_winner_lock_equity_gate and shock_equity > 0
            suppress_gate_blocked = False
            if self.orch_hedge_shock_winner_lock_suppress_gate:
                now_ms = int(now * 1000)
                for k, st in list(self._feedback_block_state.items()):
                    fb_acct, fb_sym, _fb_fam = k
                    if fb_acct == acct and fb_sym == sym:
                        until_ms = int(st.get("until_ms") or 0)
                        if until_ms > now_ms:
                            suppress_gate_blocked = True
                            break
                        else:
                            self._feedback_block_state.pop(k, None)

            winner_lock_ok = (
                not churn_limited
                and not pair_gap_blocked
                and not margin_gate_blocked
                and not suppress_gate_blocked
                and not equity_gate_blocked
                and winner_roe >= self.orch_hedge_shock_winner_min_roe_pct
                and retrace_from_peak >= self.orch_hedge_shock_winner_retrace_pct
                and (now - float(mgr.get("last_winner_lock_ts") or 0))
                    >= float(self.orch_hedge_shock_winner_cooldown_sec)
            )
            meta_base["retrace_from_peak_pct"] = round(retrace_from_peak, 2)
            meta_base["pair_gap_blocked"] = pair_gap_blocked
            meta_base["margin_gate_blocked"] = margin_gate_blocked
            meta_base["equity_gate_blocked"] = equity_gate_blocked
            meta_base["suppress_gate_blocked"] = suppress_gate_blocked
            pair_gap_remaining = max(0.0, pair_gap_sec - (now - last_loser_ts)) if pair_gap_blocked else 0.0
            winner_cooldown_remaining = max(
                0.0,
                float(self.orch_hedge_shock_winner_cooldown_sec)
                - (now - float(mgr.get("last_winner_lock_ts") or 0)),
            )
            meta_base["pair_gap_remaining_sec"] = round(pair_gap_remaining, 1)
            meta_base["winner_cooldown_remaining_sec"] = round(winner_cooldown_remaining, 1)

            if margin_gate_blocked and not churn_limited:
                logger.info(
                    "ORCH_HEDGE_SHOCK_MARGIN_GATE | account=%s | symbol=%s | "
                    "winner_lock_suppressed | margin_util=%.4f >= gate=%.2f | "
                    "preserving winner %s(%.1f%%)",
                    acct, sym, margin_util,
                    self.orch_hedge_shock_winner_lock_margin_gate,
                    winner_side, winner_roe,
                )

            if suppress_gate_blocked and not churn_limited and not margin_gate_blocked:
                logger.info(
                    "ORCH_HEDGE_SHOCK_SUPPRESS_GATE | account=%s | symbol=%s | "
                    "winner_lock_suppressed | feedback_suppression_armed | "
                    "preserving winner %s(%.1f%%)",
                    acct, sym, winner_side, winner_roe,
                )

            if equity_gate_blocked and not churn_limited and not margin_gate_blocked and not suppress_gate_blocked:
                logger.info(
                    "ORCH_HEDGE_SHOCK_EQUITY_GATE | account=%s | symbol=%s | "
                    "winner_lock_suppressed | equity=$%.2f < gate=$%.0f | "
                    "preserving winner asymmetry %s(%.1f%%)",
                    acct, sym, shock_equity,
                    self.orch_hedge_shock_winner_lock_equity_gate,
                    winner_side, winner_roe,
                )

            if pair_gap_blocked and not churn_limited:
                secs_remaining = round(pair_gap_sec - (now - last_loser_ts), 1)
                logger.info(
                    "ORCH_HEDGE_SHOCK_PAIR_GAP | account=%s | symbol=%s | "
                    "winner_lock_suppressed | loser_cut_ago=%.0fs | gap=%ds | "
                    "remaining=%.1fs",
                    acct, sym, now - last_loser_ts,
                    int(pair_gap_sec), secs_remaining,
                )

            # ── 10. Decide verdict ────────────────────────────────────────
            # Priority: block add-to-loser → loser cut → winner lock

            if adds_to_loser and loser_cut_ok:
                # Block the harmful add AND substitute with loser cut
                mgr["last_loser_cut_ts"] = now
                mgr["actions_log"].append((now, "DERISK_LOSER"))
                logger.warning(
                    "ORCH_HEDGE_SHOCK_BLOCK_AND_CUT | account=%s | symbol=%s | "
                    "blocked=%s | cutting=%s(%.1f%%) frac=%.2f%s | shock=%s | ticks=%d",
                    acct, sym, proposed_u, loser_side, loser_roe,
                    effective_cut_fraction,
                    " [ESCALATED]" if margin_critical else "",
                    shock_state, stress_ticks,
                )
                return {
                    "verdict": "BLOCK_AND_OVERRIDE",
                    "reason": "ORCH_HEDGE_SHOCK_ADD_LOSER_BLOCK",
                    "derisk_action": f"PARTIAL_CLOSE_{loser_side}",
                    "derisk_side": loser_side,
                    "derisk_fraction": effective_cut_fraction,
                    "derisk_event_code": "ORCH_SHOCK_LOSER_CUT",
                    "meta": {**meta_base, "trigger": "add_loser_block_with_cut"},
                }

            if adds_to_loser:
                # Block the add (no de-risk conditions met yet)
                logger.warning(
                    "ORCH_HEDGE_SHOCK_ADD_LOSER_BLOCK | account=%s | symbol=%s | "
                    "blocked=%s | loser=%s(%.1f%%) | shock=%s | ticks=%d",
                    acct, sym, proposed_u, loser_side, loser_roe,
                    shock_state, stress_ticks,
                )
                return {
                    "verdict": "BLOCK",
                    "reason": "ORCH_HEDGE_SHOCK_ADD_LOSER_BLOCK",
                    "meta": {**meta_base, "trigger": "add_loser_block"},
                }

            if loser_cut_ok:
                # Override proposal with loser cut
                mgr["last_loser_cut_ts"] = now
                mgr["actions_log"].append((now, "DERISK_LOSER"))
                logger.warning(
                    "ORCH_SHOCK_LOSER_CUT | account=%s | symbol=%s | "
                    "loser=%s(%.1f%%) frac=%.2f%s | shock=%s | ticks=%d",
                    acct, sym, loser_side, loser_roe,
                    effective_cut_fraction,
                    " [ESCALATED]" if margin_critical else "",
                    shock_state, stress_ticks,
                )
                return {
                    "verdict": "OVERRIDE",
                    "reason": "ORCH_SHOCK_LOSER_CUT",
                    "derisk_action": f"PARTIAL_CLOSE_{loser_side}",
                    "derisk_side": loser_side,
                    "derisk_fraction": effective_cut_fraction,
                    "derisk_event_code": "ORCH_SHOCK_LOSER_CUT",
                    "meta": {**meta_base, "trigger": "loser_cut"},
                }

            # Winner lock (only if pair-action-gap allows it — loser_cut_ok
            # was already False when we reach here; pair_gap_blocked guards
            # against trim-both-legs bleed)
            if winner_lock_ok:
                mgr["last_winner_lock_ts"] = now
                mgr["actions_log"].append((now, "LOCK_PROFIT_WINNER"))
                logger.warning(
                    "ORCH_SHOCK_WINNER_LOCK | account=%s | symbol=%s | "
                    "winner=%s(%.1f%%) | peak=%.1f%% | retrace=%.1f%% | "
                    "frac=%.2f | shock=%s | ticks=%d",
                    acct, sym, winner_side, winner_roe,
                    peak_roe, retrace_from_peak,
                    float(self.orch_hedge_shock_winner_lock_fraction),
                    shock_state, stress_ticks,
                )
                return {
                    "verdict": "OVERRIDE",
                    "reason": "ORCH_SHOCK_WINNER_LOCK",
                    "derisk_action": f"PARTIAL_CLOSE_{winner_side}",
                    "derisk_side": winner_side,
                    "derisk_fraction": float(self.orch_hedge_shock_winner_lock_fraction),
                    "derisk_event_code": "ORCH_SHOCK_WINNER_LOCK",
                    "meta": {
                        **meta_base,
                        "trigger": "winner_lock",
                        "retrace_from_peak_pct": round(retrace_from_peak, 2),
                    },
                }

            # Periodic monitoring log (every 5th stressed tick)
            if stress_ticks > 0 and stress_ticks % 5 == 0:
                logger.info(
                    "ORCH_HEDGE_SHOCK_MONITOR | account=%s | symbol=%s | "
                    "state=%s | ticks=%d | loser=%s(%.1f%%) | "
                    "winner=%s(%.1f%%) | peak=%.1f%% | retrace=%.1f%% | "
                    "margin_util=%.4f%s | pair_gap=%s | margin_gate=%s | suppress_gate=%s",
                    acct, sym, shock_state, stress_ticks,
                    loser_side, loser_roe,
                    winner_side, winner_roe,
                    peak_roe, retrace_from_peak,
                    margin_util,
                    " CRITICAL" if margin_critical else "",
                    pair_gap_blocked,
                    margin_gate_blocked,
                    suppress_gate_blocked,
                )

            return None  # No action needed

        except Exception as exc:
            logger.error(
                "ORCH_HEDGE_SHOCK_EVAL_ERROR | account=%s | symbol=%s | %s",
                account_id, symbol, exc, exc_info=True,
            )
            return None  # Fail-safe: passthrough on error

    def _apply_operator_policy_gates(
        self,
        winner: Dict[str, Any],
        proof: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
        portfolio: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        try:
            from config import (
                OPERATOR_POLICY_GATES_ENABLED,
                OP_BIAS_BULLISH_MIN,
                OP_BIAS_BEARISH_MAX,
                OP_LIQ_BPS_SAFE,
                OP_LIQ_BPS_CAUTION,
                OP_LIQ_BPS_DANGER,
                OP_LIQ_BPS_FREEZE,
                OP_STRESS_VEL_60S_BPS,
                OP_STRESS_VEL_15S_BPS,
                OP_STRESS_FAST_MOVE_SCORE,
                OP_HEDGE_COVERAGE_NORMAL_MIN,
                OP_HEDGE_COVERAGE_NORMAL_MAX,
                OP_HEDGE_COVERAGE_STRESS_MIN,
                OP_HEDGE_COVERAGE_STRESS_MAX,
                OP_HEDGE_TRIM_MIN_LIQ_BPS,
                OP_HEDGE_TRIM_MAX_FRAC,
                OP_HEDGE_TIMING_GATE_ENABLED,
                OP_HEDGE_ADD_WAIT_VEL_15S_BPS,
                OP_HEDGE_ADD_WAIT_VEL_60S_BPS,
                OP_HEDGE_ADD_WAIT_FAST_MOVE_SCORE,
                OP_HEDGE_ADD_ALLOW_IF_LIQ_BELOW_BPS,
                OP_HEDGE_ADD_COOLDOWN_SEC,
                OP_HEDGE_CONTRADICT_WINDOW_SEC,
                OP_SHOCK_STATE_ENABLED,
                OP_REVERSAL_MIN_DELTA_BPS,
                OP_REVERSAL_CANDIDATE_TICKS,
                OP_STRESS_RECOVERY_TICKS,
                OP_PORTFOLIO_STRESS_MIN_SYMBOLS,
                OP_PORTFOLIO_STRESS_MIN_FRACTION,
                OP_PORTFOLIO_STRESS_DECAY_MS,
            )
        except Exception:
            OPERATOR_POLICY_GATES_ENABLED = False
            OP_BIAS_BULLISH_MIN = 0.15
            OP_BIAS_BEARISH_MAX = -0.15
            OP_LIQ_BPS_SAFE = 350.0
            OP_LIQ_BPS_CAUTION = 220.0
            OP_LIQ_BPS_DANGER = 140.0
            OP_LIQ_BPS_FREEZE = 200.0
            OP_STRESS_VEL_60S_BPS = 90.0
            OP_STRESS_VEL_15S_BPS = 45.0
            OP_STRESS_FAST_MOVE_SCORE = 0.65
            OP_HEDGE_COVERAGE_NORMAL_MIN = 0.35
            OP_HEDGE_COVERAGE_NORMAL_MAX = 0.65
            OP_HEDGE_COVERAGE_STRESS_MIN = 0.55
            OP_HEDGE_COVERAGE_STRESS_MAX = 0.85
            OP_HEDGE_TRIM_MIN_LIQ_BPS = 220.0
            OP_HEDGE_TRIM_MAX_FRAC = 0.35
            OP_HEDGE_TIMING_GATE_ENABLED = True
            OP_HEDGE_ADD_WAIT_VEL_15S_BPS = 90.0
            OP_HEDGE_ADD_WAIT_VEL_60S_BPS = 180.0
            OP_HEDGE_ADD_WAIT_FAST_MOVE_SCORE = 0.75
            OP_HEDGE_ADD_ALLOW_IF_LIQ_BELOW_BPS = 140.0
            OP_HEDGE_ADD_COOLDOWN_SEC = 30
            OP_HEDGE_CONTRADICT_WINDOW_SEC = 60
            OP_SHOCK_STATE_ENABLED = True
            OP_REVERSAL_MIN_DELTA_BPS = 20.0
            OP_REVERSAL_CANDIDATE_TICKS = 2
            OP_STRESS_RECOVERY_TICKS = 3
            OP_PORTFOLIO_STRESS_MIN_SYMBOLS = 3
            OP_PORTFOLIO_STRESS_MIN_FRACTION = 0.4
            OP_PORTFOLIO_STRESS_DECAY_MS = 120000

        if not bool(OPERATOR_POLICY_GATES_ENABLED):
            return True, None, {}

        meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        action_u = str(action or "").upper().strip()
        category = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
        source = str(winner.get("source") or winner.get("source_module") or "").lower()

        risk_intent = str(winner.get("risk_intent") or meta_blob.get("risk_intent") or "").upper().strip()
        is_add = self._is_risk_add_action(action_u)
        is_hedge_add = self._is_hedge_add_action(winner, action_u)
        is_reduce = any(tok in action_u for tok in ("PARTIAL_CLOSE", "DECREASE", "REDUCE", "CLOSE")) and "CLOSE_AND" not in action_u
        reason_text = " ".join([
            str(winner.get("reason") or ""),
            str(winner.get("trigger_reason") or ""),
            str(meta_blob.get("reason") or ""),
            str(meta_blob.get("reasoning") or ""),
        ]).upper()
        proposal_stream = str(
            winner.get("_proposal_stream")
            or winner.get("proposal_stream")
            or meta_blob.get("_proposal_stream")
            or meta_blob.get("proposal_stream")
            or ""
        ).lower()
        is_stealth_tp_trim = bool(
            is_reduce
            and (
                proposal_stream == "proposals:stealth_stops"
                or "STEALTH_TRIGGER TAKE_PROFIT" in reason_text
            )
        )
        is_hedge_context = (
            "HEDGE" in action_u
            or category in {"HEDGE", "PROTECTIVE", "RECOVERY"}
            or bool(winner.get("hedge_intent"))
            or risk_intent == "RECOVERY_HEDGE"
            or "hedge_manager" in source
        )
        is_hedge_trim = bool((is_reduce and is_hedge_context) or is_stealth_tp_trim)
        is_main_add = bool(is_add and not is_hedge_add)
        is_protective = bool(category == "PROTECTIVE" or ("PROTECT" in source and is_hedge_context))
        _is_tf_disagg = bool(winner.get("tf_hedge_disagg"))

        # Prefer pos_liq_distance_pct (leverage-derived) for safety gates,
        # fall back to liq_distance_pct (backward compat)
        liq_pct = self._safe_float(winner.get("pos_liq_distance_pct"))
        if liq_pct is None:
            liq_pct = self._extract_liq_distance_pct(winner)
        liq_bps = float(liq_pct) * 100.0 if liq_pct is not None else None
        bias_score = self._extract_bias_score(winner, meta_blob)
        bias_present = any(
            (winner.get(k) is not None or meta_blob.get(k) is not None)
            for k in ("bias_score", "mtf_bias_score", "market_bias_score", "context_bias_score", "bias", "market_bias", "htf_bias", "mtf_bias", "context_bias")
        )
        coverage_ratio = self._extract_coverage_ratio(winner, meta_blob)
        # bias_present quality gate is applied below after velocities + regime are available
        # (see "Bias quality gate: tighten to AND-logic" comment block).

        htf_aligned_raw = winner.get("htf_aligned")
        if htf_aligned_raw is None:
            htf_aligned_raw = meta_blob.get("htf_aligned")
        if htf_aligned_raw is None:
            htf_aligned_raw = meta_blob.get("alignment_ok")
        htf_aligned_known = htf_aligned_raw is not None
        htf_aligned = True
        if htf_aligned_known:
            if isinstance(htf_aligned_raw, str):
                htf_aligned = str(htf_aligned_raw).strip().lower() in {"1", "true", "yes", "on", "aligned"}
            else:
                htf_aligned = bool(htf_aligned_raw)

        price_val, _ = self._get_price_ref(symbol, winner)
        now_ms = int(time.time() * 1000)
        vel_15_bps, vel_60_bps, signed_15_bps, signed_60_bps = self._compute_policy_velocities(account_id, symbol, price_val, now_ms)
        fast_move_score = self._safe_float(
            winner.get("fast_move_score")
            or meta_blob.get("fast_move_score")
            or winner.get("micro_fast_move_score")
            or meta_blob.get("micro_fast_move_score")
        )
        # ── Market regime extraction (single source: risk/market_regime.py) ──
        # Only extract when at least one regime flag is ON; otherwise defaults to UNKNOWN/0
        _regime_any_enabled = (
            getattr(config, "REGIME_LAYER_ENABLED", False)
            or config.regime_active()
        )
        market_regime = {}
        move_score = 0.0
        move_regime = "UNKNOWN"
        volatility_score = 0.0
        liq_risk = 0.0
        liquidity_score_val = 0.0
        if _regime_any_enabled:
            market_regime = winner.get("market_regime") or meta_blob.get("market_regime") or {}
            if isinstance(market_regime, str):
                try:
                    market_regime = json.loads(market_regime)
                except Exception:
                    market_regime = {}
            # Staleness check: ignore regime data older than REGIME_STALE_SEC
            _regime_ts = float(market_regime.get("updated_ts_ms", 0) or 0)
            _regime_age_s = (time.time() * 1000 - _regime_ts) / 1000 if _regime_ts > 0 else 999
            _stale_sec = getattr(config, "REGIME_STALE_SEC", 120)
            _regime_is_fresh = _regime_age_s <= _stale_sec

            if _regime_is_fresh:
                move_score = self._safe_float(
                    winner.get("move_score") or meta_blob.get("move_score") or market_regime.get("move_score")
                )
                move_regime = str(
                    winner.get("move_regime") or meta_blob.get("move_regime") or market_regime.get("move_regime") or "UNKNOWN"
                ).upper()
                volatility_score = self._safe_float(
                    winner.get("volatility_score") or meta_blob.get("volatility_score") or market_regime.get("volatility_score")
                )
                liq_risk = self._safe_float(
                    winner.get("liq_risk") or meta_blob.get("liq_risk") or market_regime.get("liq_risk")
                )
                liquidity_score_val = self._safe_float(
                    winner.get("liquidity_score") or meta_blob.get("liquidity_score") or market_regime.get("liquidity_score")
                )
            else:
                # Stale regime → ignore (fail-open: use defaults)
                move_score = 0.0
                move_regime = "UNKNOWN"
        # Prefer regime's fast_move_score over None — but ONLY when regime_active()
        # (otherwise this subtly changes stress decisions via fast_move_score threshold)
        if config.regime_active():
            if fast_move_score is None and market_regime.get("fast_move_score") is not None:
                fast_move_score = self._safe_float(market_regime.get("fast_move_score"))

        # ── Bias quality gate: tighten to AND-logic so that all three signal
        # sources must be available before bias blocks are enforced.
        # AND: coverage_ratio known + regime not UNKNOWN + at least one velocity.
        # Also require |bias_score| > eps to prevent 0.0 placeholder triggering blocks.
        if bias_present:
            _bias_eps = 1e-4
            _bias_score_nonzero = (bias_score is not None and abs(float(bias_score or 0)) > _bias_eps)
            _bias_coverage_ok = coverage_ratio is not None
            _bias_regime_known = move_regime not in ("UNKNOWN", "")
            _bias_vel_known = (vel_15_bps is not None or vel_60_bps is not None)
            bias_present = (
                _bias_score_nonzero
                and _bias_coverage_ok
                and _bias_regime_known
                and _bias_vel_known
            )

        stress = False
        if vel_60_bps is not None and float(vel_60_bps) >= float(OP_STRESS_VEL_60S_BPS):
            stress = True
        if vel_15_bps is not None and float(vel_15_bps) >= float(OP_STRESS_VEL_15S_BPS):
            stress = True
        if fast_move_score is not None and float(fast_move_score) >= float(OP_STRESS_FAST_MOVE_SCORE):
            stress = True
        # Regime-driven stress: FAST/IMPULSE regimes are inherently stressed
        # GATED: only when regime_active() — otherwise binary-identical to pre-regime behavior
        if config.regime_active() and move_regime in ("FAST", "IMPULSE"):
            stress = True

        shock_state = {
            "state": "NORMAL",
            "direction": "",
            "reversal_to": "",
            "candidate_ticks": 0,
            "recovery_ticks": 0,
            "stress": bool(stress),
        }
        if bool(OP_SHOCK_STATE_ENABLED):
            shock_state = self._derive_shock_state(
                account_id,
                symbol,
                now_ms=now_ms,
                stress=bool(stress),
                price=price_val,
                signed_15_bps=signed_15_bps,
                signed_60_bps=signed_60_bps,
                reversal_delta_bps=float(OP_REVERSAL_MIN_DELTA_BPS),
                candidate_ticks_required=int(OP_REVERSAL_CANDIDATE_TICKS),
                recovery_ticks_required=int(OP_STRESS_RECOVERY_TICKS),
            )

        portfolio_stress = self._derive_portfolio_stress(
            account_id,
            now_ms=now_ms,
            min_symbols=int(OP_PORTFOLIO_STRESS_MIN_SYMBOLS),
            min_fraction=float(OP_PORTFOLIO_STRESS_MIN_FRACTION),
            decay_ms=int(OP_PORTFOLIO_STRESS_DECAY_MS),
        )

        _base_cov_min = float(OP_HEDGE_COVERAGE_STRESS_MIN if stress else OP_HEDGE_COVERAGE_NORMAL_MIN)
        _base_cov_max = float(OP_HEDGE_COVERAGE_STRESS_MAX if stress else OP_HEDGE_COVERAGE_NORMAL_MAX)
        cov_min = self._dynamic_value(symbol, _base_cov_min * 0.7, _base_cov_min * 1.3)
        cov_max = self._dynamic_value(symbol, _base_cov_max * 0.8, _base_cov_max * 1.1)

        # ── Adaptive hedge coverage based on regime (gated by regime_active()) ──
        # In FAST/IMPULSE with strong aligned bias → reduce hedge coverage
        # (don't smother momentum).  In high-conflict → widen coverage.
        if config.regime_active():
            _regime_tf_bias_abs = abs(float(
                winner.get("tf_bias_dir") or (meta_blob.get("tf_bias_dir") if isinstance(meta_blob, dict) else 0) or 0
            ))
            _regime_tf_conflict = float(
                winner.get("tf_conflict_score") or (meta_blob.get("tf_conflict_score") if isinstance(meta_blob, dict) else 0) or 0
            )
            _cov_conflict_thr = self._dynamic_threshold(symbol, 0.40, 0.70)
            _cov_liq_thr = self._dynamic_threshold(symbol, 0.30, 0.60)
            _cov_floor = self._dynamic_threshold(symbol, 0.10, 0.25)
            _cov_ceil = self._dynamic_value(symbol, 0.80, 0.95)
            if move_regime in ("FAST", "IMPULSE") and _regime_tf_bias_abs >= 1.0 and _regime_tf_conflict <= _cov_conflict_thr * 0.5:
                cov_min = max(_cov_floor, cov_min * 0.7)
                cov_max = max(cov_min + 0.10, cov_max * 0.8)
            elif _regime_tf_conflict >= _cov_conflict_thr or (liq_risk is not None and liq_risk >= _cov_liq_thr):
                cov_min = min(_cov_ceil, cov_min * 1.2)
                cov_max = min(_cov_ceil + 0.10, cov_max * 1.15)
        liq_band = "UNKNOWN"
        if liq_bps is not None:
            if liq_bps >= float(OP_LIQ_BPS_SAFE):
                liq_band = "SAFE"
            elif liq_bps >= float(OP_LIQ_BPS_CAUTION):
                liq_band = "CAUTION"
            elif liq_bps >= float(OP_LIQ_BPS_DANGER):
                liq_band = "DANGER"
            else:
                liq_band = "CRITICAL"

        policy_meta = {
            "stress": bool(stress),
            "liq_bps": liq_bps,
            "liq_band": liq_band,
            "pos_liq_pct": self._safe_float(winner.get("pos_liq_distance_pct")),
            "cluster_liq_pct": self._safe_float(winner.get("cluster_liq_distance_pct")),
            "bias_score": float(bias_score),
            "coverage_ratio": coverage_ratio,
            "coverage_band": {"min": cov_min, "max": cov_max},
            "stealth_tp_trim": bool(is_stealth_tp_trim),
            "vel_15_bps": vel_15_bps,
            "vel_60_bps": vel_60_bps,
            "signed_15_bps": signed_15_bps,
            "signed_60_bps": signed_60_bps,
            "fast_move_score": fast_move_score,
            "htf_aligned": bool(htf_aligned),
            "htf_aligned_known": bool(htf_aligned_known),
            "bias_present": bool(bias_present),
            "shock_state": shock_state,
            "portfolio_stress": portfolio_stress,
            # Market regime (data-driven move detection)
            "move_score": move_score,
            "move_regime": move_regime,
            "volatility_score": volatility_score,
            "liq_risk": liq_risk,
            "liquidity_score": liquidity_score_val,
        }

        shock_name = str((shock_state or {}).get("state") or "NORMAL").upper()
        portfolio_stress_active = bool((portfolio_stress or {}).get("active"))
        liq_urgent = False

        # Hedge timing gate: delay hedge adds during impulse spikes to avoid top/bottom chasing.
        # Safety bypasses:
        #   1. Liquidation distance already dangerous → allow immediately
        #   2. Position ROE deeply negative → hedging is urgent, bypass timing
        #   3. Liquidation band is DANGER or worse → bypass timing
        if is_hedge_add and bool(OP_HEDGE_TIMING_GATE_ENABLED):
            _dyn_liq_urgent_bps = self._dynamic_value(symbol, 100.0, float(OP_HEDGE_ADD_ALLOW_IF_LIQ_BELOW_BPS or 140.0))
            if liq_bps is not None and float(liq_bps) <= _dyn_liq_urgent_bps:
                liq_urgent = True

            # Fix O (Feb 2026): ROE-based urgency bypass.
            # When position is already deep underwater, delaying the hedge
            # increases liquidation risk. Allow hedge immediately.
            roe_urgent = False
            _roe_bypass_thresh = float(getattr(config, "OP_HEDGE_ROE_URGENCY_PCT", -8.0) or -8.0)
            _pos_roi = self._safe_float(
                winner.get("roi_pct") or winner.get("roe_pct") or winner.get("pnl_pct")
            )
            if _pos_roi is not None and _pos_roi <= _roe_bypass_thresh:
                roe_urgent = True

            # Fix O.2: If liq band is DANGER or CRITICAL, treat as urgent
            if liq_band in ("DANGER", "CRITICAL"):
                liq_urgent = True

            _dyn_vel15 = self._dynamic_value(symbol, 50.0, float(OP_HEDGE_ADD_WAIT_VEL_15S_BPS or 90.0))
            _dyn_vel60 = self._dynamic_value(symbol, 100.0, float(OP_HEDGE_ADD_WAIT_VEL_60S_BPS or 180.0))
            _dyn_fms = self._dynamic_value(symbol, 0.50, float(OP_HEDGE_ADD_WAIT_FAST_MOVE_SCORE or 0.75))
            wait_15 = vel_15_bps is not None and float(vel_15_bps) >= _dyn_vel15
            wait_60 = vel_60_bps is not None and float(vel_60_bps) >= _dyn_vel60
            _fms_data_reliable = move_regime != "UNKNOWN" and move_score > 0.0
            wait_fms = _fms_data_reliable and fast_move_score is not None and float(fast_move_score) >= _dyn_fms
            impulse_wait = bool(wait_15 or wait_60 or wait_fms)
            reversal_ready = shock_name == "REVERSAL_CONFIRMED"

            policy_meta["hedge_timing_gate"] = {
                "enabled": True,
                "liq_urgent": bool(liq_urgent),
                "roe_urgent": bool(roe_urgent),
                "impulse_wait": bool(impulse_wait),
                "reversal_ready": bool(reversal_ready),
                "vel15_wait": bool(wait_15),
                "vel60_wait": bool(wait_60),
                "fms_wait": bool(wait_fms),
                "pos_roi_pct": _pos_roi,
            }

            # Direction-aware impulse gate: if the fast move is AGAINST the
            # main position (signed velocity opposes pos side), this hedge is
            # protective — let it through.  Only block when the impulse is
            # aligned with the position (hedge would be chasing a retracement).
            _impulse_aligned_with_pos = True  # assume aligned → block
            try:
                _da_enabled = bool(getattr(config, "OP_HEDGE_IMPULSE_DIRECTION_AWARE", True))
                if _da_enabled:
                    _pos_side_raw = str(
                        winner.get("position_side") or winner.get("pos_side") or ""
                    ).upper()
                    if not _pos_side_raw:
                        _hs = hedge_add_side
                        _pos_side_raw = "SHORT" if _hs == "LONG" else ("LONG" if _hs == "SHORT" else "")
                    _sv = signed_60_bps if signed_60_bps is not None else signed_15_bps
                    if _pos_side_raw in ("LONG", "SHORT") and _sv is not None:
                        _pos_sign = 1.0 if _pos_side_raw == "LONG" else -1.0
                        _move_against = (_pos_sign * float(_sv)) < 0
                        if _move_against:
                            _impulse_aligned_with_pos = False
                            policy_meta["hedge_timing_gate"]["impulse_against_pos"] = True
            except Exception:
                pass

            if impulse_wait and _impulse_aligned_with_pos and (not liq_urgent) and (not roe_urgent) and (not reversal_ready) and (not _is_tf_disagg):
                return False, "OP_HEDGE_ADD_SWING_WAIT", policy_meta

        # Hedge add deconfliction: block contradictory side adds and rapid repeat churn.
        hedge_add_side = "LONG" if "LONG" in action_u else "SHORT" if "SHORT" in action_u else ""
        if is_hedge_add and hedge_add_side:
            now_s = float(time.time())
            memory_key = f"{account_id}:{symbol}"
            last = self._policy_hedge_add_state.get(memory_key) or {}
            last_side = str(last.get("side") or "").upper()
            last_ts = float(last.get("ts") or 0.0)

            # FIX-RCA-5: Margin-stress-aware adaptive cooldown.
            # When margin utilization is high (crisis), cooldown shrinks to allow
            # faster protective hedging. Uses real-time margin data from Redis.
            _cd_base = self._dynamic_value(symbol, 15.0, float(OP_HEDGE_ADD_COOLDOWN_SEC or 30.0))
            _margin_stress_mult = 1.0
            try:
                _rc = self.redis
                if _rc and account_id:
                    _eq_raw = _rc.get(f"portfolio:equity:{account_id}")
                    if _eq_raw:
                        import json as _mj
                        _eq_str = _eq_raw.decode() if isinstance(_eq_raw, (bytes, bytearray)) else str(_eq_raw)
                        _eq_data = _mj.loads(_eq_str) if _eq_str.strip().startswith("{") else {}
                        _mu = float(_eq_data.get("margin_util", 0) or _eq_data.get("margin_utilization", 0) or 0)
                        _fr = float(_eq_data.get("free_margin_ratio", 1.0) or 1.0)
                        # Adaptive: high margin util → shrink cooldown (min 0.2x at mu>=0.90)
                        # Low margin util → full cooldown
                        if _mu > 0.5:
                            _margin_stress_mult = max(0.2, 1.0 - (_mu - 0.5) * 2.0)
                        elif _fr < 0.3:
                            _margin_stress_mult = max(0.2, _fr / 0.3)
            except Exception:
                pass
            cd_sec = max(1.0, _cd_base * _margin_stress_mult)
            _contra_base = self._dynamic_value(symbol, 30.0, float(OP_HEDGE_CONTRADICT_WINDOW_SEC or 60.0))
            contradict_sec = max(cd_sec, _contra_base * _margin_stress_mult)
            policy_meta["hedge_cooldown_adaptive"] = {
                "cd_sec": round(cd_sec, 1),
                "contra_sec": round(contradict_sec, 1),
                "margin_stress_mult": round(_margin_stress_mult, 2),
            }

            if last_side and last_ts > 0:
                dt = max(0.0, now_s - last_ts)
                policy_meta["hedge_last_add"] = {"side": last_side, "age_sec": dt}

                if dt < cd_sec and last_side == hedge_add_side and (not liq_urgent) and (not _is_tf_disagg):
                    return False, "OP_HEDGE_ADD_COOLDOWN", policy_meta

                if dt < contradict_sec and last_side != hedge_add_side and (not liq_urgent) and (not _is_tf_disagg):
                    return False, "OP_HEDGE_CONTRADICT_BLOCK", policy_meta

        direction = "LONG" if "LONG" in action_u else "SHORT" if "SHORT" in action_u else ""
        if is_main_add and not is_protective:
            if shock_name in {"STRESS_DOWN", "STRESS_UP", "REVERSAL_CANDIDATE"}:
                return False, "OP_MAIN_ADD_STRESS_DELAY", policy_meta
            if htf_aligned_known and not htf_aligned:
                return False, "OP_HTF_ALIGN_BLOCK", policy_meta
            if bias_present and direction == "LONG" and float(bias_score) < float(OP_BIAS_BULLISH_MIN):
                _bias_mode = str(getattr(config, "ORCH_BIAS_BLOCK_MODE", "DOWNSIZE") or "DOWNSIZE").upper().strip()
                if _bias_mode == "BLOCK":
                    return False, "OP_BIAS_LONG_BLOCK", policy_meta
                _bias_mult = float(getattr(config, "ORCH_BIAS_SOFT_MULT", 0.35) or 0.35)
                _cur_m = float(winner.get("margin_usd") or 0.0)
                winner["margin_usd"] = round(_cur_m * _bias_mult, 4)
                winner["notional_usd"] = round(float(winner.get("notional_usd") or 0.0) * _bias_mult, 4)
                policy_meta["bias_soft_mult"] = _bias_mult
                logger.info("OP_BIAS_LONG_SOFT | sym=%s margin_usd %.4f→%.4f mult=%.2f",
                            symbol, _cur_m, winner["margin_usd"], _bias_mult)
            if bias_present and direction == "SHORT" and float(bias_score) > float(OP_BIAS_BEARISH_MAX):
                _bias_mode = str(getattr(config, "ORCH_BIAS_BLOCK_MODE", "DOWNSIZE") or "DOWNSIZE").upper().strip()
                if _bias_mode == "BLOCK":
                    return False, "OP_BIAS_SHORT_BLOCK", policy_meta
                _bias_mult = float(getattr(config, "ORCH_BIAS_SOFT_MULT", 0.35) or 0.35)
                _cur_m = float(winner.get("margin_usd") or 0.0)
                winner["margin_usd"] = round(_cur_m * _bias_mult, 4)
                winner["notional_usd"] = round(float(winner.get("notional_usd") or 0.0) * _bias_mult, 4)
                policy_meta["bias_soft_mult"] = _bias_mult
                logger.info("OP_BIAS_SHORT_SOFT | sym=%s margin_usd %.4f→%.4f mult=%.2f",
                            symbol, _cur_m, winner["margin_usd"], _bias_mult)
            if liq_bps is not None and float(liq_bps) < float(OP_LIQ_BPS_DANGER):
                return False, "OP_MAIN_ADD_LIQ_BLOCK", policy_meta

            # ── Big move → one-leg allowed (gated by REGIME_POLICY_ENABLED) ───────
            # When move_regime is FAST/IMPULSE AND TF bias is strong AND
            # conflict is low → allow primary entry without requiring hedge-first.
            # Otherwise, in CALM/NORMAL → require stronger conviction.
            _big_move_one_leg = False
            if config.regime_active():
                tf_bias_abs = abs(float(winner.get("tf_bias_dir") or meta_blob.get("tf_bias_dir") or 0))
                tf_conflict_val = float(winner.get("tf_conflict_score") or meta_blob.get("tf_conflict_score") or 0)
                # Thresholds from config
                _big_move_score_min = getattr(config, "REGIME_BIG_MOVE_SCORE_MIN", 0.55)
                _big_move_align_min = getattr(config, "REGIME_BIG_MOVE_ALIGNMENT_MIN", 0.60)
                _big_move_ent_max = getattr(config, "REGIME_BIG_MOVE_ENTROPY_MAX", 0.35)
                if (move_score is not None and move_score >= _big_move_score_min 
                    and tf_bias_abs >= _big_move_align_min and tf_conflict_val <= _big_move_ent_max):
                    _big_move_one_leg = True
                    policy_meta["big_move_one_leg"] = True
                    policy_meta["one_leg_reason"] = (
                        f"move={move_regime} score={move_score:.2f} "
                        f"bias={tf_bias_abs:.1f} conflict={tf_conflict_val:.2f}"
                    )
                else:
                    policy_meta["big_move_one_leg"] = False

                # In CALM regime without strong TF alignment, require htf_aligned
                if move_regime in ("CALM", "UNKNOWN") and tf_bias_abs < _big_move_align_min:
                    if not htf_aligned:
                        return False, "OP_CALM_REGIME_ALIGN_REQUIRED", policy_meta
            else:
                policy_meta["big_move_one_leg"] = False

        if is_hedge_add and coverage_ratio is not None and float(coverage_ratio) >= float(cov_max):
            return False, "OP_HEDGE_ADD_OVERCOVERED", policy_meta

        if is_hedge_trim:
            trim_frac = self._safe_float(
                winner.get("close_fraction")
                or meta_blob.get("close_fraction")
                or winner.get("close_pct")
                or meta_blob.get("close_pct")
                or winner.get("close_percentage")
                or meta_blob.get("close_percentage")
            )
            if trim_frac is not None:
                if float(trim_frac) > 1.0:
                    trim_frac = float(trim_frac) / 100.0
                trim_frac = max(0.0, min(1.0, float(trim_frac)))
            elif "PARTIAL" in action_u:
                trim_frac = 0.5
            elif "CLOSE" in action_u:
                trim_frac = 1.0
            else:
                trim_frac = 0.0

            coverage_before = float(coverage_ratio) if coverage_ratio is not None else None
            coverage_after = None
            if coverage_before is not None:
                coverage_after = max(0.0, float(coverage_before) * max(0.0, 1.0 - float(trim_frac or 0.0)))
            policy_meta["trim_fraction"] = trim_frac
            policy_meta["coverage_before"] = coverage_before
            policy_meta["coverage_after"] = coverage_after

            if liq_bps is not None and float(liq_bps) < float(OP_LIQ_BPS_FREEZE):
                return False, "OP_HEDGE_TRIM_LIQ_BLOCK", policy_meta
            if coverage_ratio is not None and float(coverage_ratio) <= float(cov_min):
                return False, "OP_HEDGE_TRIM_UNDERCOVERED", policy_meta
            if liq_bps is not None and float(liq_bps) < float(OP_HEDGE_TRIM_MIN_LIQ_BPS):
                return False, "OP_HEDGE_TRIM_LIQ_BLOCK", policy_meta
            # HEDGE_TRIM_STRESS_BLOCK must NOT fire on genuine model-driven CLOSE_* actions
            # (those are de-risking; blocking them during stress is counterproductive).
            # Only apply to stealth-TP trims (is_stealth_tp_trim) and partial trims,
            # not to full closes originating from the model.
            _is_full_model_close = (
                "CLOSE" in action_u
                and "PARTIAL" not in action_u
                and not is_stealth_tp_trim
                and source not in ("stealth_stops", "dynamic_tp", "trailing_stop")
            )
            if (stress or portfolio_stress_active) and not _is_full_model_close:
                return False, "OP_HEDGE_TRIM_STRESS_BLOCK", policy_meta
            if coverage_after is not None and float(coverage_after) < float(cov_min):
                return False, "OP_HEDGE_FLOOR_VIOLATION", policy_meta
            try:
                trim_margin = float(winner.get("margin_usd") or 0.0)
            except Exception:
                trim_margin = 0.0
            cap_frac = max(0.0, min(1.0, float(OP_HEDGE_TRIM_MAX_FRAC or 0.0)))
            if cap_frac > 0 and trim_margin > 0:
                implied_total = trim_margin / cap_frac
                winner["op_trim_cap_fraction"] = float(cap_frac)
                winner["op_trim_implied_total_margin_usd"] = float(implied_total)

        if is_hedge_add and hedge_add_side:
            self._policy_hedge_add_state[f"{account_id}:{symbol}"] = {
                "ts": float(time.time()),
                "side": str(hedge_add_side),
            }

        return True, None, policy_meta

    def _extract_feature_ts_ms(self, feature: Dict[str, Any]) -> Optional[int]:
        for key in ("ts_ms", "timestamp", "ts", "updated_ts_ms"):
            ts = self._safe_float(feature.get(key))
            if ts is not None and ts > 0:
                try:
                    return int(ts)
                except Exception:
                    continue
        return None

    def _extract_first_float(self, feature: Dict[str, Any], keys: List[str]) -> Optional[float]:
        for key in keys:
            if key in feature:
                val = self._safe_float(feature.get(key))
                if val is not None:
                    return val
        return None

    def _fetch_orderbook_depth_usd(self, symbol: str) -> Tuple[Optional[float], Optional[int]]:
        if not self.redis:
            return None, None
        try:
            raw = self.redis.get(f"orderbook:depth:{symbol}")
        except Exception:
            raw = None
        if not raw:
            return None, None
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return None, None
        depth = (
            self._safe_float(payload.get("depth_usd"))
            or self._safe_float(payload.get("total_depth"))
            or self._safe_float(payload.get("orderbook_depth_usd"))
            or self._safe_float(payload.get("depth_bps_25_total_usd"))
        )
        bid_depth = self._safe_float(payload.get("bid_depth")) or 0.0
        ask_depth = self._safe_float(payload.get("ask_depth")) or 0.0
        if depth is None and (bid_depth or ask_depth):
            depth = float(bid_depth) + float(ask_depth)
        ts = self._safe_float(payload.get("ts_ms") or payload.get("timestamp"))
        try:
            ts_ms = int(ts) if ts else None
        except Exception:
            ts_ms = None
        return depth, ts_ms

    def _enrich_signal_with_features(self, winner: Dict[str, Any], proof: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from config import DQ_ENRICH_ENABLED, DQ_ENRICH_MAX_AGE_MS, DQ_ENRICH_CONFIDENCE
        except Exception:
            DQ_ENRICH_ENABLED = True
            DQ_ENRICH_MAX_AGE_MS = 60000
            DQ_ENRICH_CONFIDENCE = 0.5
        if not DQ_ENRICH_ENABLED or not self.redis:
            return {}

        symbol = str(winner.get("symbol") or "").upper().strip()
        meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        tf = winner.get("timeframe") or meta_blob.get("timeframe") or meta_blob.get("tf") or ""
        tf = str(tf or "").strip()
        tf_candidates = [tf] if tf else []
        for fallback_tf in ("5m", "15m", "1h"):
            if fallback_tf and fallback_tf not in tf_candidates:
                tf_candidates.append(fallback_tf)

        dq_missing_fields: List[str] = []
        for src in (winner.get("dq_missing_fields"), meta_blob.get("dq_missing_fields")):
            if isinstance(src, list):
                dq_missing_fields.extend([str(x) for x in src])
        dq_missing_fields = list(dict.fromkeys(dq_missing_fields))

        enrich_info: Dict[str, Any] = {
            "dq_fallback_used": False,
            "dq_enriched_fields": [],
            "dq_enrich_sources": {},
        }

        def mark_missing(field: str) -> None:
            if field not in dq_missing_fields:
                dq_missing_fields.append(field)

        def mark_present(field: str) -> None:
            if field in dq_missing_fields:
                dq_missing_fields.remove(field)

        now_ms = int(time.time() * 1000)

        # ── Liq distance enrichment: pos_liq vs cluster_liq split ────────────
        # pos_liq_distance_pct  = derived from proposed leverage (100/lev * haircut)
        #   → used by safety gates (OP_MAIN_ADD_LIQ_BLOCK, ORCH_LIQ_BUFFER_PRECHECK)
        # cluster_liq_distance_pct = from unified_features liquidation heatmap
        #   → used by microstructure / liquidity risk analysis
        # liq_distance_pct = pos_liq (backward compat for all existing consumers)
        try:
            from config import POS_LIQ_SPLIT_ENABLED, POS_LIQ_MAX_PCT_CAP, POS_LIQ_HAIRCUT_MAJOR, POS_LIQ_HAIRCUT_ALT_MEME
        except Exception:
            POS_LIQ_SPLIT_ENABLED = True
            POS_LIQ_MAX_PCT_CAP = 20.0
            POS_LIQ_HAIRCUT_MAJOR = 1.0
            POS_LIQ_HAIRCUT_ALT_MEME = 0.85

        _liq_existing = self._extract_liq_distance_pct(winner)
        # Treat as missing if None OR exactly 0.0 from trainer (trainer emits 0.0 as placeholder
        # when liquidation data unavailable; a real liq distance would be >0 on a live position).
        # Log if we are overwriting a non-None value so it's auditable.
        _liq_is_placeholder = (_liq_existing is None or float(_liq_existing) == 0.0)
        if _liq_is_placeholder:
            if _liq_existing is not None and float(_liq_existing) == 0.0:
                logger.debug(
                    "DQ_LIQ_ZERO_OVERWRITE | symbol=%s | existing=0.0 (placeholder) -> enriching from leverage/features",
                    symbol
                )
        if _liq_is_placeholder:
            pos_liq_val = None       # from leverage
            cluster_liq_val = None   # from unified_features
            liq_ts = None
            liq_source_tf = None

            # ── Step 1: Compute pos_liq from proposed leverage + haircut ──
            _lev_fallback = self._fallback_liq_from_leverage(winner)
            if _lev_fallback is not None and _lev_fallback > 0:
                # Apply bucket-aware haircut (alts/memes: maintenance margin, fees, slippage)
                _bucket = self._symbol_bucket(symbol)
                _haircut = float(POS_LIQ_HAIRCUT_MAJOR) if _bucket == "major" else float(POS_LIQ_HAIRCUT_ALT_MEME)
                _capped = min(float(_lev_fallback) * _haircut, float(POS_LIQ_MAX_PCT_CAP))
                pos_liq_val = max(0.0, _capped)
                logger.debug(
                    "DQ_LIQ_ENRICH_POS_LIQ | symbol=%s | leverage=%.2f | raw=%.4f | haircut=%.2f | capped=%.4f | bucket=%s",
                    symbol,
                    float(winner.get("leverage") or winner.get("recommended_leverage") or 0),
                    _lev_fallback, _haircut, pos_liq_val, _bucket,
                )

            # ── Step 2: Compute cluster_liq from unified_features heatmap ──
            for tf0 in tf_candidates:
                feats = self._read_unified_features(symbol, tf0)
                if not feats:
                    continue
                liq_long = self._extract_first_float(feats, ["liquidation_long_distance_pct", "liq_long_distance_pct"])
                liq_short = self._extract_first_float(feats, ["liquidation_short_distance_pct", "liq_short_distance_pct"])
                liq_direct = self._extract_first_float(feats, ["liq_distance_pct", "liquidation_distance_pct", "liquidation_min_distance_pct"])
                _cluster = None
                if liq_direct is not None:
                    _cluster = liq_direct
                elif liq_long is not None or liq_short is not None:
                    vals = [v for v in (liq_long, liq_short) if v is not None]
                    _cluster = min(vals) if vals else None
                if _cluster is not None:
                    cluster_liq_val = float(_cluster)
                    liq_ts = self._safe_float(feats.get("liquidation_updated_ts") or feats.get("liquidation_last_event_ts"))
                    try:
                        liq_ts = int(liq_ts) if liq_ts else None
                    except Exception:
                        liq_ts = None
                    liq_source_tf = tf0
                    break

            # ── Step 3: Set canonical fields ──
            # pos_liq takes priority for safety gates; cluster_liq stored separately
            if POS_LIQ_SPLIT_ENABLED:
                if pos_liq_val is not None:
                    winner["pos_liq_distance_pct"] = float(pos_liq_val)
                if cluster_liq_val is not None:
                    winner["cluster_liq_distance_pct"] = float(cluster_liq_val)

            # liq_distance_pct = pos_liq (priority) → cluster_liq (fallback)
            # This is backward-compatible: all existing consumers read liq_distance_pct
            liq_val = pos_liq_val if pos_liq_val is not None else cluster_liq_val

            if liq_val is not None:
                winner["liq_distance_pct"] = float(liq_val)
                liq_source_tf = "pos_liq" if pos_liq_val is not None else (liq_source_tf or "cluster_liq")
                if liq_ts:
                    winner["liqmap_ts_ms"] = int(liq_ts)
                mark_present("liq_distance_pct")
                enrich_info["dq_fallback_used"] = True
                enrich_info["dq_enriched_fields"].append("liq_distance_pct")
                enrich_info["dq_enrich_sources"]["liq_distance_pct"] = {
                    "tf": liq_source_tf,
                    "ts_ms": int(liq_ts) if liq_ts else None,
                    "pos_liq": pos_liq_val,
                    "cluster_liq": cluster_liq_val,
                    "split_enabled": bool(POS_LIQ_SPLIT_ENABLED),
                }
            else:
                mark_missing("liq_distance_pct")

        _ob_existing = self._extract_metric(winner, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])
        if _ob_existing is None or float(_ob_existing) <= 0.0:
            ob_val = None
            ob_ts = None
            ob_source_tf = None
            for tf0 in tf_candidates:
                feats = self._read_unified_features(symbol, tf0)
                if not feats:
                    continue
                ob_val = self._extract_first_float(feats, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])
                if ob_val is not None:
                    ob_ts = self._extract_feature_ts_ms(feats)
                    ob_source_tf = tf0
                    break
            if ob_val is None:
                ob_val, ob_ts = self._fetch_orderbook_depth_usd(symbol)
            if ob_val is not None:
                winner["orderbook_depth_usd"] = float(ob_val)
                if ob_ts:
                    winner["orderbook_ts_ms"] = int(ob_ts)
                mark_present("orderbook_depth_usd")
                enrich_info["dq_fallback_used"] = True
                enrich_info["dq_enriched_fields"].append("orderbook_depth_usd")
                enrich_info["dq_enrich_sources"]["orderbook_depth_usd"] = {
                    "tf": ob_source_tf,
                    "ts_ms": int(ob_ts) if ob_ts else None,
                }
            else:
                mark_missing("orderbook_depth_usd")

        _vol_existing = self._extract_metric(winner, ["volatility_pct", "volatility", "vol"])
        if _vol_existing is None or float(_vol_existing) <= 0.0:
            vol_val = None
            vol_ts = None
            vol_source_tf = None
            for tf0 in tf_candidates:
                feats = self._read_unified_features(symbol, tf0)
                if not feats:
                    continue
                vol_val = self._extract_first_float(feats, ["volatility_pct", "volatility", "vol"])
                if vol_val is not None:
                    vol_ts = self._extract_feature_ts_ms(feats)
                    vol_source_tf = tf0
                    break
            if vol_val is not None:
                if float(vol_val) <= 2.5:
                    vol_val = float(vol_val) * 100.0
                winner["volatility_pct"] = float(vol_val)
                if vol_ts:
                    winner["volatility_ts_ms"] = int(vol_ts)
                mark_present("volatility_pct")
                enrich_info["dq_fallback_used"] = True
                enrich_info["dq_enriched_fields"].append("volatility_pct")
                enrich_info["dq_enrich_sources"]["volatility_pct"] = {
                    "tf": vol_source_tf,
                    "ts_ms": int(vol_ts) if vol_ts else None,
                }
            else:
                mark_missing("volatility_pct")

        if enrich_info["dq_enriched_fields"]:
            dq_conf = self._safe_float(winner.get("dq_confidence") or meta_blob.get("dq_confidence"))
            if dq_conf is None or dq_conf <= 0:
                dq_conf = float(DQ_ENRICH_CONFIDENCE)
            else:
                dq_conf = min(float(dq_conf), float(DQ_ENRICH_CONFIDENCE))
            winner["dq_confidence"] = dq_conf
            meta_blob["dq_confidence"] = dq_conf
            meta_blob["dq_fallback_used"] = True
            winner["dq_fallback_used"] = True

        if dq_missing_fields:
            winner["dq_missing_fields"] = dq_missing_fields
            meta_blob["dq_missing_fields"] = dq_missing_fields

        if enrich_info["dq_enriched_fields"]:
            meta_blob["dq_enriched_fields"] = enrich_info["dq_enriched_fields"]
            meta_blob["dq_enrich_sources"] = enrich_info["dq_enrich_sources"]
            enrich_info["dq_enrich_age_ms"] = {}
            for field, src in enrich_info["dq_enrich_sources"].items():
                try:
                    ts_ms = int(src.get("ts_ms") or 0)
                except Exception:
                    ts_ms = 0
                age_ms = (now_ms - ts_ms) if ts_ms else None
                enrich_info["dq_enrich_age_ms"][field] = age_ms
                if age_ms is not None:
                    if field == "orderbook_depth_usd":
                        winner["dq_orderbook_age_ms"] = age_ms
                        meta_blob["dq_orderbook_age_ms"] = age_ms
                    elif field == "liq_distance_pct":
                        winner["dq_liqmap_age_ms"] = age_ms
                        meta_blob["dq_liqmap_age_ms"] = age_ms
                    elif field == "volatility_pct":
                        winner["dq_volatility_age_ms"] = age_ms
                        meta_blob["dq_volatility_age_ms"] = age_ms
            meta_blob["dq_enrich_age_ms"] = enrich_info.get("dq_enrich_age_ms")

        # Feature snapshot age (for hedge freshness gate + audit)
        try:
            ts_candidates = []
            for key in ("features_ts_ms", "orderbook_ts_ms", "volatility_ts_ms", "liqmap_ts_ms"):
                ts_val = self._safe_float(winner.get(key) or meta_blob.get(key))
                if ts_val:
                    ts_candidates.append(int(ts_val))
            # Include unified_features:5m timestamp (feature pipeline liveness).
            try:
                feats_5m = self._read_unified_features(symbol, "5m")
                uf_ts = self._extract_feature_ts_ms(feats_5m) if feats_5m else None
            except Exception:
                uf_ts = None
            try:
                if uf_ts:
                    uf_ts_i = int(uf_ts)
                    uf_age_i = int(now_ms - uf_ts_i) if uf_ts_i > 0 else None
                    winner.setdefault("unified_features_ts_ms", uf_ts_i)
                    meta_blob.setdefault("unified_features_ts_ms", uf_ts_i)
                    if uf_age_i is not None:
                        winner.setdefault("unified_features_age_ms", uf_age_i)
                        meta_blob.setdefault("unified_features_age_ms", uf_age_i)
                    ts_candidates.append(uf_ts_i)
                    # Feed into dq_source_ok for risk-add actions (fail-closed on stale features).
                    try:
                        from config import OPEN_RISK_FEATURES_MAX_AGE_MS as _FEAT_MAX
                        _FEAT_MAX = int(_FEAT_MAX)
                    except Exception:
                        _FEAT_MAX = 120_000
                    if uf_age_i is None or uf_age_i > int(_FEAT_MAX):
                        try:
                            act_u = str(
                                winner.get("action")
                                or winner.get("action_name")
                                or meta_blob.get("action")
                                or meta_blob.get("action_name")
                                or ""
                            ).upper().strip()
                        except Exception:
                            act_u = ""
                        if self._is_risk_add_action(act_u):
                            winner["dq_source_ok"] = False
                            meta_blob["dq_source_ok"] = False
                            meta_blob["dq_features_stale"] = True
                            meta_blob["dq_features_age_ms"] = uf_age_i
                            proof["dq_features_stale"] = {"age_ms": uf_age_i, "max_age_ms": _FEAT_MAX}
            except Exception:
                pass
            if ts_candidates:
                feat_ts = min(ts_candidates)
                feat_age = (now_ms - feat_ts) if feat_ts else None
                if feat_ts:
                    winner.setdefault("features_ts_ms", int(feat_ts))
                    meta_blob.setdefault("features_ts_ms", int(feat_ts))
                if feat_age is not None:
                    winner.setdefault("features_age_ms", int(feat_age))
                    meta_blob.setdefault("features_age_ms", int(feat_age))
        except Exception:
            pass

        winner["metadata"] = meta_blob

        # --- Enrich: price returns (ret_5m, ret_15m, ret_1h) for regime gate ---
        try:
            from config import ORCH_ENRICH_RETURNS_ENABLED
        except Exception:
            ORCH_ENRICH_RETURNS_ENABLED = True
        if ORCH_ENRICH_RETURNS_ENABLED:
            ret_map = {
                "ret_5m": ("5m", ["ret_5m", "return_5m_pct", "price_change_5m_pct", "ret_5m_pct"]),
                "ret_15m": ("15m", ["ret_15m", "return_15m_pct", "price_change_15m_pct", "ret_15m_pct"]),
                "ret_1h": ("1h", ["ret_1h", "return_1h_pct", "price_change_1h_pct", "ret_1h_pct"]),
            }
            for canon_key, (tf_pref, aliases) in ret_map.items():
                existing = None
                for a in aliases:
                    existing = self._safe_float(winner.get(a))
                    if existing is None and isinstance(meta_blob, dict):
                        existing = self._safe_float(meta_blob.get(a))
                    if existing is not None:
                        break
                if existing is None:
                    # Pull from unified features
                    tf_try = [tf_pref] + [t for t in tf_candidates if t != tf_pref]
                    for tf0 in tf_try:
                        feats = self._read_unified_features(symbol, tf0)
                        if not feats:
                            continue
                        for a in aliases + ["close_change_pct", "price_pct_change"]:
                            val = self._safe_float(feats.get(a))
                            if val is not None:
                                winner[canon_key] = float(val)
                                meta_blob[canon_key] = float(val)
                                enrich_info["dq_enriched_fields"].append(canon_key)
                                enrich_info["dq_fallback_used"] = True
                                break
                        if winner.get(canon_key) is not None:
                            break

        # --- Enrich: microstructure fields (depth_spoof_score, spread_bps, move_intensity) ---
        try:
            from config import ORCH_ENRICH_MICROSTRUCTURE_ENABLED
        except Exception:
            ORCH_ENRICH_MICROSTRUCTURE_ENABLED = True
        if ORCH_ENRICH_MICROSTRUCTURE_ENABLED:
            micro_fields = {
                "depth_spoof_score": ["depth_spoof_score", "spoof_score", "ob_spoof_score"],
                "spread_bps": ["spread_bps", "bid_ask_spread_bps", "spread"],
                "move_intensity": ["move_intensity", "price_move_intensity", "volatility_intensity"],
            }
            for canon_key, aliases in micro_fields.items():
                existing = None
                for a in aliases:
                    existing = self._safe_float(winner.get(a))
                    if existing is None and isinstance(meta_blob, dict):
                        existing = self._safe_float(meta_blob.get(a))
                    if existing is not None:
                        break
                if existing is None:
                    for tf0 in tf_candidates:
                        feats = self._read_unified_features(symbol, tf0)
                        if not feats:
                            continue
                        for a in aliases:
                            val = self._safe_float(feats.get(a))
                            if val is not None:
                                winner[canon_key] = float(val)
                                meta_blob[canon_key] = float(val)
                                enrich_info["dq_enriched_fields"].append(canon_key)
                                enrich_info["dq_fallback_used"] = True
                                break
                        if winner.get(canon_key) is not None:
                            break

        # --- Enrich: liquidation strength fields for liq coupling gate ---
        try:
            from config import ORCH_ENRICH_LIQ_STRENGTH_ENABLED
        except Exception:
            ORCH_ENRICH_LIQ_STRENGTH_ENABLED = True
        if ORCH_ENRICH_LIQ_STRENGTH_ENABLED:
            liq_fields = {
                "liquidation_long_strength": ["liquidation_long_strength", "liq_long_strength"],
                "liquidation_short_strength": ["liquidation_short_strength", "liq_short_strength"],
            }
            for canon_key, aliases in liq_fields.items():
                existing = None
                for a in aliases:
                    existing = self._safe_float(winner.get(a))
                    if existing is None and isinstance(meta_blob, dict):
                        existing = self._safe_float(meta_blob.get(a))
                    if existing is not None:
                        break
                if existing is None:
                    for tf0 in tf_candidates:
                        feats = self._read_unified_features(symbol, tf0)
                        if not feats:
                            continue
                        for a in aliases:
                            val = self._safe_float(feats.get(a))
                            if val is not None:
                                winner[canon_key] = float(val)
                                meta_blob[canon_key] = float(val)
                                enrich_info["dq_enriched_fields"].append(canon_key)
                                enrich_info["dq_fallback_used"] = True
                                break
                        if winner.get(canon_key) is not None:
                            break

        winner["metadata"] = meta_blob

        # --- Enrich: Global Breadth + Risk Budget Allocator (feature-flagged) ---
        try:
            _gb_enabled = bool(getattr(config, "GLOBAL_BREADTH_ENABLED", False))
            _rba_enabled = bool(getattr(config, "RISK_BUDGET_ALLOCATOR_ENABLED", False))
            if (_gb_enabled or _rba_enabled) and self.redis:
                # Attach cached global breadth snapshot
                if _gb_enabled:
                    try:
                        from risk.global_breadth import read_cached_breadth
                        _breadth_tf = "5m"  # primary TF
                        _breadth = read_cached_breadth(self.redis, _breadth_tf)
                        if _breadth and isinstance(_breadth, dict):
                            winner["breadth_dir"] = int(_breadth.get("breadth_dir") or 0)
                            winner["breadth_strength"] = float(_breadth.get("breadth_strength") or 0)
                            winner["breadth_entropy"] = float(_breadth.get("breadth_entropy") or 1)
                            winner["breadth_vol"] = float(_breadth.get("breadth_vol") or 0)
                            meta_blob["global_breadth"] = _breadth
                            enrich_info["dq_enriched_fields"].append("global_breadth")
                    except Exception:
                        pass
                # Attach risk budget allocation state
                if _rba_enabled:
                    try:
                        from risk.risk_budget_allocator import read_cached_allocation
                        _acct = str(winner.get("account_id") or "primary").strip().lower()
                        _alloc = read_cached_allocation(self.redis, _acct)
                        if _alloc is not None:
                            winner["rba_state"] = str(_alloc.state)
                            winner["rba_risk_mult"] = float(_alloc.risk_mult)
                            winner["rba_max_risk_symbols"] = int(_alloc.max_risk_symbols)
                            winner["rba_cadence_min_sec"] = int(_alloc.cadence_min_sec)
                            winner["rba_hedge_policy"] = str(_alloc.hedge_policy)
                            meta_blob["risk_budget"] = _alloc.to_dict()
                            enrich_info["dq_enriched_fields"].append("risk_budget")
                    except Exception:
                        pass
                # Attach reversal state
                try:
                    _rev_enabled = bool(getattr(config, "REVERSAL_DETECTOR_ENABLED", False))
                    if _rev_enabled:
                        from risk.reversal_detector import read_cached_reversal
                        _rev = read_cached_reversal(self.redis)
                        if _rev and isinstance(_rev, dict):
                            winner["reversal_active"] = bool(_rev.get("active", False))
                            meta_blob["reversal_state"] = _rev
                            if bool(_rev.get("active", False)):
                                enrich_info["dq_enriched_fields"].append("reversal_active")
                except Exception:
                    pass
                # Attach microstructure toxicity
                try:
                    _tox_enabled = bool(getattr(config, "MICROSTRUCTURE_TOXICITY_ENABLED", True))
                    if _tox_enabled and symbol:
                        from risk.microstructure_toxicity import read_cached_toxicity
                        _tox = read_cached_toxicity(self.redis, str(symbol).upper())
                        if _tox is not None:
                            winner["toxicity_score"] = float(_tox.score)
                            winner["toxicity_hint"] = str(_tox.execution_hint)
                            meta_blob["toxicity"] = _tox.to_dict()
                            enrich_info["dq_enriched_fields"].append("toxicity")
                except Exception:
                    pass
                # Attach market state contract
                try:
                    _msc_enabled = bool(getattr(config, "MARKET_STATE_CONTRACT_ENABLED", True))
                    if _msc_enabled:
                        from risk.market_state_contract import read_cached_contract
                        _msc = read_cached_contract(self.redis)
                        if _msc and isinstance(_msc, dict):
                            winner["msc_can_expand"] = bool(_msc.get("can_expand", False))
                            winner["msc_effective_state"] = str(_msc.get("effective_state", "UNKNOWN"))
                            meta_blob["market_state_contract"] = _msc
                            enrich_info["dq_enriched_fields"].append("market_state_contract")
                except Exception:
                    pass
        except Exception:
            pass

        winner["metadata"] = meta_blob

        if enrich_info["dq_enriched_fields"]:
            logger.info(
                "ORCH_DQ_ENRICH | symbol=%s | fields=%s | tf=%s",
                symbol,
                ",".join(enrich_info["dq_enriched_fields"]),
                tf or "na",
            )
            proof["dq_enrich"] = enrich_info

        max_age = int(DQ_ENRICH_MAX_AGE_MS)
        if max_age > 0 and enrich_info.get("dq_enrich_age_ms"):
            too_old = {}
            for field, age in enrich_info["dq_enrich_age_ms"].items():
                if age is not None and age > max_age:
                    too_old[field] = int(age)
            if too_old:
                winner["dq_source_ok"] = False
                meta_blob["dq_source_ok"] = False
                meta_blob["dq_enrich_age_over"] = too_old
                proof["dq_enrich_age_over"] = too_old

        return enrich_info

    def _cleanup_dq_missing_fields(self, winner: Dict[str, Any], meta_blob: Dict[str, Any], fields: List[str]) -> None:
        for field in fields:
            if winner.get(field) is not None:
                try:
                    missing = winner.get("dq_missing_fields") or []
                    if isinstance(missing, list) and field in missing:
                        missing.remove(field)
                        winner["dq_missing_fields"] = missing
                except Exception:
                    pass
                try:
                    meta_missing = meta_blob.get("dq_missing_fields") or []
                    if isinstance(meta_missing, list) and field in meta_missing:
                        meta_missing.remove(field)
                        meta_blob["dq_missing_fields"] = meta_missing
                except Exception:
                    pass

    def _calc_percentile(self, values: List[float], pct: float) -> Optional[float]:
        if not values:
            return None
        try:
            p = float(pct)
        except Exception:
            p = 0.0
        if p <= 0:
            return min(values)
        if p >= 100:
            return max(values)
        vals = sorted(values)
        idx = int(round((p / 100.0) * (len(vals) - 1)))
        idx = max(0, min(len(vals) - 1, idx))
        return float(vals[idx])

    def _update_hedge_percentiles(self, symbol: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from config import (
                HEDGE_PERCENTILE_ENABLED,
                HEDGE_PERCENTILE_WINDOW,
                HEDGE_PERCENTILE_MIN_SAMPLES,
                HEDGE_PCTL_FULL_ON_HIGH,
                HEDGE_PCTL_PARTIAL_ON_HIGH,
                HEDGE_PCTL_OFF_HIGH,
                HEDGE_PCTL_FULL_ON_LOW,
                HEDGE_PCTL_PARTIAL_ON_LOW,
                HEDGE_PCTL_OFF_LOW,
            )
        except Exception:
            HEDGE_PERCENTILE_ENABLED = False
            HEDGE_PERCENTILE_WINDOW = 180
            HEDGE_PERCENTILE_MIN_SAMPLES = 40
            HEDGE_PCTL_FULL_ON_HIGH = 90
            HEDGE_PCTL_PARTIAL_ON_HIGH = 75
            HEDGE_PCTL_OFF_HIGH = 55
            HEDGE_PCTL_FULL_ON_LOW = 10
            HEDGE_PCTL_PARTIAL_ON_LOW = 25
            HEDGE_PCTL_OFF_LOW = 40

        if not HEDGE_PERCENTILE_ENABLED or not self.redis:
            return {"used": False}

        symbol_u = str(symbol or "").upper().strip()
        window = max(20, int(HEDGE_PERCENTILE_WINDOW))
        min_samples = max(10, int(HEDGE_PERCENTILE_MIN_SAMPLES))
        thresholds: Dict[str, Dict[str, float]] = {}
        samples: Dict[str, int] = {}

        for key, val in metrics.items():
            if val is None:
                continue
            try:
                v = float(val)
            except Exception:
                continue
            list_key = f"hedge:metric:{symbol_u}:{key}"
            try:
                pipe = self.redis.pipeline()
                pipe.lpush(list_key, str(v))
                pipe.ltrim(list_key, 0, window - 1)
                pipe.lrange(list_key, 0, window - 1)
                res = pipe.execute()
                raw_vals = res[-1] if res else []
            except Exception:
                raw_vals = []

            values: List[float] = []
            for rv in raw_vals or []:
                fv = self._safe_float(rv)
                if fv is not None:
                    values.append(float(fv))

            samples[key] = len(values)
            if len(values) < min_samples:
                continue

            if key in {"liq_dist", "ob_depth"}:
                thresholds[key] = {
                    "full_on": self._calc_percentile(values, HEDGE_PCTL_FULL_ON_LOW),
                    "partial_on": self._calc_percentile(values, HEDGE_PCTL_PARTIAL_ON_LOW),
                    "off": self._calc_percentile(values, HEDGE_PCTL_OFF_LOW),
                }
            else:
                thresholds[key] = {
                    "full_on": self._calc_percentile(values, HEDGE_PCTL_FULL_ON_HIGH),
                    "partial_on": self._calc_percentile(values, HEDGE_PCTL_PARTIAL_ON_HIGH),
                    "off": self._calc_percentile(values, HEDGE_PCTL_OFF_HIGH),
                }

        used = bool(thresholds)
        meta = {
            "used": used,
            "thresholds": thresholds,
            "samples": samples,
        }
        if used:
            logger.info(
                "ORCH_HEDGE_PCTL | symbol=%s | thresholds=%s",
                symbol_u,
                thresholds,
            )
        return meta

    def _calc_dq_score(self, payload: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        try:
            from config import DQ_SCORE_OB_MAX_AGE_MS, DQ_SCORE_LIQMAP_MAX_AGE_MS, DQ_SCORE_WEIGHTS
        except Exception:
            DQ_SCORE_OB_MAX_AGE_MS = 15000
            DQ_SCORE_LIQMAP_MAX_AGE_MS = 90000
            DQ_SCORE_WEIGHTS = {"orderbook": 0.30, "liqmap": 0.30, "liq_distance": 0.20, "depth": 0.20}

        now_ms = int(time.time() * 1000)
        try:
            ob_ts = int(payload.get("orderbook_ts_ms") or 0)
        except Exception:
            ob_ts = 0
        try:
            lm_ts = int(payload.get("liqmap_ts_ms") or 0)
        except Exception:
            lm_ts = 0

        liq_dist = self._extract_liq_distance_pct(payload)
        ob_depth = self._extract_metric(payload, ["orderbook_depth_usd", "ob_depth_usd", "orderbook_depth", "depth_bps_25_total_usd", "depth_total_usd", "depth_usd"])

        dq_ob = 1.0 if (ob_ts > 0 and (now_ms - ob_ts) < int(DQ_SCORE_OB_MAX_AGE_MS)) else 0.0
        dq_liq = 1.0 if (lm_ts > 0 and (now_ms - lm_ts) < int(DQ_SCORE_LIQMAP_MAX_AGE_MS)) else 0.0
        dq_liq_distance = 1.0 if liq_dist is not None else 0.0
        dq_depth = 1.0 if ob_depth is not None else 0.0

        w_ob = float(DQ_SCORE_WEIGHTS.get("orderbook", 0.0))
        w_liq = float(DQ_SCORE_WEIGHTS.get("liqmap", 0.0))
        w_ld = float(DQ_SCORE_WEIGHTS.get("liq_distance", 0.0))
        w_dep = float(DQ_SCORE_WEIGHTS.get("depth", 0.0))
        w_sum = w_ob + w_liq + w_ld + w_dep
        if w_sum <= 0:
            w_sum = 1.0

        dq = (dq_ob * w_ob + dq_liq * w_liq + dq_liq_distance * w_ld + dq_depth * w_dep) / w_sum
        meta = {
            "dq_ob": dq_ob,
            "dq_liq": dq_liq,
            "dq_liq_distance": dq_liq_distance,
            "dq_depth": dq_depth,
            "dq_score": dq,
        }
        return float(dq), meta

    def _update_dq_stats(self, account_id: str, dq_score: float) -> None:
        if not self.redis:
            return
        try:
            key = f"orch:dq:stats:{account_id}"
            pipe = self.redis.pipeline()
            pipe.hincrbyfloat(key, "total", 1.0)
            if float(dq_score) >= 0.8:
                pipe.hincrbyfloat(key, "good", 1.0)
            pipe.hset(key, "last_ts_ms", str(int(time.time() * 1000)))
            pipe.expire(key, 7200)
            pipe.execute()
        except Exception:
            pass

    def _get_portfolio_metrics(self, account_id: str, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        metrics = {
            "equity_usd": float(portfolio.get("equity") or 0.0),
            "dd_24h_pct": None,
            "fee_burn_24h_pct": None,
            "dq_health_pct": None,
            "net_pnl_7d": None,
        }
        if not self.redis:
            return metrics

        try:
            raw = self.redis.hgetall(f"portfolio:drawdown:{account_id}") or {}
            dd = raw.get("drawdown_24h_pct") or raw.get(b"drawdown_24h_pct")
            if dd is not None:
                metrics["dd_24h_pct"] = float(dd)
        except Exception:
            pass

        equity = float(metrics.get("equity_usd") or 0.0)
        try:
            raw = self.redis.hgetall(f"pnl:decomp:1d:{account_id}") or {}
            fees = raw.get("fee_usd") or raw.get(b"fee_usd") or 0.0
            fees = float(fees or 0.0)
            if equity > 0:
                metrics["fee_burn_24h_pct"] = (fees / equity) * 100.0
        except Exception:
            pass

        try:
            raw = self.redis.hgetall(f"orch:dq:stats:{account_id}") or {}
            total = raw.get("total") or raw.get(b"total") or 0.0
            good = raw.get("good") or raw.get(b"good") or 0.0
            total = float(total or 0.0)
            good = float(good or 0.0)
            if total > 0:
                metrics["dq_health_pct"] = (good / total) * 100.0
        except Exception:
            pass

        try:
            net_7d = 0.0
            for i in range(0, 7):
                day_key = time.strftime("%Y%m%d", time.gmtime(time.time() - (i * 86400)))
                raw = self.redis.hgetall(f"pnl:decomp:1d:{account_id}:{day_key}") or {}
                net = raw.get("net_pnl_usd") or raw.get(b"net_pnl_usd") or 0.0
                net_7d += float(net or 0.0)
            metrics["net_pnl_7d"] = net_7d
        except Exception:
            pass

        return metrics

    def _resolve_portfolio_tier(self, metrics: Dict[str, Any]) -> int:
        try:
            from config import (
                PORTFOLIO_TIER_ENABLED,
                PORTFOLIO_TIER_DD_PROTECT_PCT,
                PORTFOLIO_TIER_DD_AGG_PCT,
                PORTFOLIO_TIER_FEE_BURN_PROTECT_PCT,
                PORTFOLIO_TIER_FEE_BURN_AGG_PCT,
                PORTFOLIO_TIER_DQ_PROTECT_PCT,
                PORTFOLIO_TIER_DQ_AGG_PCT,
            )
        except Exception:
            PORTFOLIO_TIER_ENABLED = False
            PORTFOLIO_TIER_DD_PROTECT_PCT = 4.0
            PORTFOLIO_TIER_DD_AGG_PCT = 1.5
            PORTFOLIO_TIER_FEE_BURN_PROTECT_PCT = 0.6
            PORTFOLIO_TIER_FEE_BURN_AGG_PCT = 0.25
            PORTFOLIO_TIER_DQ_PROTECT_PCT = 70.0
            PORTFOLIO_TIER_DQ_AGG_PCT = 90.0

        if not PORTFOLIO_TIER_ENABLED:
            return 1

        dd = metrics.get("dd_24h_pct")
        fee_burn = metrics.get("fee_burn_24h_pct")
        dq_health = metrics.get("dq_health_pct")
        net_7d = metrics.get("net_pnl_7d")

        protect = False
        if dd is not None and float(dd) > float(PORTFOLIO_TIER_DD_PROTECT_PCT):
            protect = True
        if fee_burn is not None and float(fee_burn) > float(PORTFOLIO_TIER_FEE_BURN_PROTECT_PCT):
            protect = True
        if dq_health is not None and float(dq_health) < float(PORTFOLIO_TIER_DQ_PROTECT_PCT):
            protect = True
        if protect:
            return 0

        aggressive = True
        if dd is None or float(dd) >= float(PORTFOLIO_TIER_DD_AGG_PCT):
            aggressive = False
        if fee_burn is None or float(fee_burn) >= float(PORTFOLIO_TIER_FEE_BURN_AGG_PCT):
            aggressive = False
        if dq_health is None or float(dq_health) <= float(PORTFOLIO_TIER_DQ_AGG_PCT):
            aggressive = False
        if net_7d is None or float(net_7d) <= 0:
            aggressive = False

        return 2 if aggressive else 1

    def _apply_portfolio_tier_caps(self, phase: Dict[str, Any], tier: int, proof: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from config import (
                PORTFOLIO_TIER_MAX_POSITIONS,
                PORTFOLIO_TIER_MAX_TOTAL_MARGIN_PCT,
                PORTFOLIO_TIER_MAX_MARGIN_PER_SYMBOL_PCT,
            )
        except Exception:
            return phase

        scaled = dict(phase or {})
        max_positions = int(PORTFOLIO_TIER_MAX_POSITIONS.get(int(tier), scaled.get("max_positions") or 0) or 0)
        max_mu = float(PORTFOLIO_TIER_MAX_TOTAL_MARGIN_PCT.get(int(tier), scaled.get("max_mu") or 0.0) or 0.0)
        per_pos_pct = float(PORTFOLIO_TIER_MAX_MARGIN_PER_SYMBOL_PCT.get(int(tier), scaled.get("per_pos_margin_pct") or 0.0) or 0.0)

        if max_positions > 0:
            scaled["max_positions"] = max_positions
        if max_mu > 0:
            scaled["max_mu"] = max_mu
        if per_pos_pct > 0:
            scaled["per_pos_margin_pct"] = per_pos_pct

        proof["portfolio_tier"] = int(tier)
        proof["portfolio_tier_caps"] = {
            "max_positions": scaled.get("max_positions"),
            "max_mu": scaled.get("max_mu"),
            "per_pos_margin_pct": scaled.get("per_pos_margin_pct"),
        }
        return scaled

    def _apply_ramp_budget_scaling(self, phase: Dict[str, Any], portfolio: Dict[str, Any], account_id: str, proof: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from config import (
                RAMP_BUDGET_SCALING_ENABLED,
                RAMP_BUDGET_MAX_EXTRA_POSITIONS,
                RAMP_BUDGET_MAX_POSITIONS_CAP,
                RAMP_BUDGET_MARGIN_UTIL_TARGET,
                RAMP_BUDGET_MARGIN_UTIL_MAX,
                RAMP_BUDGET_FEE_UTIL_MAX,
                RAMP_BUDGET_REQUIRE_FEE_DATA,
                FEE_BUDGET_ENABLED,
                HOURLY_FEE_BUDGET_USD,
            )
        except Exception:
            return phase

        if not RAMP_BUDGET_SCALING_ENABLED:
            return phase

        scaled = dict(phase or {})
        base_max_positions = int(scaled.get("max_positions") or 0)
        if base_max_positions <= 0:
            return scaled

        try:
            margin_util = float(portfolio.get("margin_util") or 0.0)
        except Exception:
            margin_util = 0.0

        if margin_util > float(RAMP_BUDGET_MARGIN_UTIL_MAX):
            return scaled

        fee_util = None
        fee_ok = True
        if FEE_BUDGET_ENABLED and float(HOURLY_FEE_BUDGET_USD or 0.0) > 0:
            perf_data = None
            try:
                perf_data = self.redis.get("trainer:perf_metrics") if self.redis else None
            except Exception:
                perf_data = None
            if perf_data:
                try:
                    perf = json.loads(perf_data.decode() if isinstance(perf_data, (bytes, bytearray)) else perf_data)
                    fees_today = float(perf.get("fees_today", 0.0) or 0.0)
                    fee_util = fees_today / float(HOURLY_FEE_BUDGET_USD)
                    if fee_util >= float(RAMP_BUDGET_FEE_UTIL_MAX):
                        fee_ok = False
                except Exception:
                    fee_ok = False
            else:
                fee_ok = not RAMP_BUDGET_REQUIRE_FEE_DATA

        if not fee_ok:
            return scaled

        target = float(RAMP_BUDGET_MARGIN_UTIL_TARGET)
        if target <= 0:
            return scaled

        headroom = max(0.0, min(1.0, (target - margin_util) / target))
        extra = int(round(float(RAMP_BUDGET_MAX_EXTRA_POSITIONS) * headroom))
        if extra <= 0:
            return scaled

        max_cap = int(RAMP_BUDGET_MAX_POSITIONS_CAP)
        # Safety: if phase base is ≤ 3 (low-equity safe mode), limit extra to +1
        # This prevents P1 (3 positions) from inflating to 6+ at high leverage
        if base_max_positions <= 3:
            extra = min(extra, 1)
        new_max = min(max_cap, base_max_positions + extra)
        if new_max <= base_max_positions:
            return scaled

        scaled["max_positions"] = new_max
        proof["ramp_budget_scaled"] = True
        proof["ramp_budget_meta"] = {
            "base_max_positions": base_max_positions,
            "scaled_max_positions": new_max,
            "extra_positions": extra,
            "margin_util": margin_util,
            "fee_util": fee_util,
        }
        logger.info(
            "ORCH_RAMP_SCALE | account=%s | base=%s | scaled=%s | mu=%.4f | fee_util=%s",
            account_id,
            base_max_positions,
            new_max,
            margin_util,
            f"{fee_util:.3f}" if fee_util is not None else "na",
        )
        return scaled

    def _publish_exec_event(
        self,
        *,
        code: str,
        account_id: str,
        symbol: str,
        action: str,
        proposal_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.redis:
            return
        payload = {
            "layer": "ORCH",
            "code": str(code or ""),
            "reason": str(code or ""),
            "account": str(account_id or ""),
            "symbol": str(symbol or ""),
            "action": str(action or ""),
            "proposal_id": str(proposal_id or ""),
            "ts_ms": int(time.time() * 1000),
        }
        if meta:
            try:
                payload.update({"meta": json.dumps(meta, separators=(",", ":"))})
            except Exception:
                payload.update({"meta": str(meta)})
        try:
            self.redis.xadd(
                EXEC_EVENT_STREAM,
                {"data": json.dumps(payload, separators=(",", ":"))},
                maxlen=int(self.exec_event_maxlen),
                approximate=True,
            )
        except Exception:
            pass

    def _profit_close_hedge_preflight(
        self,
        winner: Dict[str, Any],
        *,
        account_id: str,
        symbol: str,
        action: str,
        category: str,
        proof: Dict[str, Any],
    ) -> None:
        """
        Under elevated multi-TF / microstructure stress, emit a hedge-scale proposal
        before publishing a profit-intent close. Additive; failures are swallowed.
        """
        try:
            if not bool(getattr(config, "PROFIT_CLOSE_HEDGE_PREFLIGHT_ENABLED", False)):
                return
            if not self.redis:
                return
            action_u = str(action or "").upper()
            if "CLOSE_AND" in action_u:
                return
            cat_u = str(category or "").upper()
            meta_w = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
            profit_intent = bool(winner.get("profit_intent")) or bool(meta_w.get("profit_intent"))
            is_reduce = any(
                tok in action_u
                for tok in ("PARTIAL_CLOSE", "DECREASE", "REDUCE", "CLOSE", "TAKE_PROFIT")
            )
            if not is_reduce:
                return
            profit_cat = cat_u in (
                "CLOSE_PROFIT",
                "HEDGE_TRIM",
                "TP_MANAGEMENT",
                "PROFIT",
                "STEALTH_TP",
            ) or profit_intent
            if not profit_cat:
                return

            _cf = float(
                meta_w.get("tf_conflict_score")
                or winner.get("tf_conflict_score")
                or winner.get("conflict_score")
                or 0.0
            )
            _fm = float(
                meta_w.get("fast_move_score")
                or winner.get("fast_move_score")
                or 0.0
            )
            _liq = float(
                meta_w.get("liq_distance_bps")
                or winner.get("liq_distance_bps")
                or winner.get("liq_bps")
                or 9_999.0
            )
            _thr_c = float(getattr(config, "PROFIT_PREFLIGHT_CONFLICT_MIN", 0.35))
            _thr_f = float(getattr(config, "PROFIT_PREFLIGHT_FAST_MOVE_MIN", 0.72))
            _thr_l = float(getattr(config, "PROFIT_PREFLIGHT_LIQ_BPS_MAX", 250.0))
            stressed = _cf >= _thr_c or _fm >= _thr_f or _liq <= _thr_l
            if not stressed:
                return

            close_side = ""
            if "LONG" in action_u and "SHORT" not in action_u.replace("LONG", ""):
                close_side = "LONG"
            elif "SHORT" in action_u:
                close_side = "SHORT"
            if not close_side:
                return
            hedge_side = "SHORT" if close_side == "LONG" else "LONG"
            hedge_action = f"ADD_HEDGE_{hedge_side}"

            base_margin = float(winner.get("margin_usd") or meta_w.get("margin_usd") or 0.0)
            if base_margin <= 0:
                base_margin = float(winner.get("position_margin") or 0.0)
            frac = float(getattr(config, "PROFIT_PREFLIGHT_HEDGE_MARGIN_FRAC", 0.15))
            hedge_margin = max(5.0, base_margin * frac)

            from rl.proposal_hedge_preflight import emit_scale_hedge_proposal

            ok = emit_scale_hedge_proposal(
                self.redis,
                account_id=account_id,
                symbol=symbol,
                hedge_action=hedge_action,
                margin_usd=hedge_margin,
                source="profit_close_preflight",
                reason=(
                    f"PREFLIGHT stress cf={_cf:.2f} fm={_fm:.2f} liq_bps={_liq:.0f} "
                    f"before {action_u}"
                ),
            )
            if ok:
                delay_ms = int(getattr(config, "PROFIT_PREFLIGHT_PUBLISH_DELAY_MS", 2000))
                winner["profit_preflight_hedge_emitted"] = True
                winner["profit_preflight_delay_ms"] = delay_ms
                proof["profit_preflight_hedge"] = {
                    "hedge_action": hedge_action,
                    "margin_usd": hedge_margin,
                    "conflict_score": _cf,
                    "fast_move_score": _fm,
                    "liq_bps": _liq,
                }
                logger.info(
                    "PROFIT_CLOSE_PREFLIGHT | acct=%s sym=%s | emitted %s margin=%.2f | "
                    "cf=%.2f fm=%.2f liq_bps=%.0f",
                    account_id,
                    symbol,
                    hedge_action,
                    hedge_margin,
                    _cf,
                    _fm,
                    _liq,
                )
        except Exception as _pf_err:
            logger.debug("PROFIT_PREFLIGHT_ERR | %s", _pf_err)

    def _flush_ready_windows(self, now_ms: int):
        """Flush windows that have exceeded micro-window duration."""
        keys_to_flush = []
        _fastlane_ms = int(getattr(config, "ORCH_FASTLANE_WINDOW_MS", 50))

        for key, window in self.windows.items():
            if window.flushed:
                continue

            elapsed = now_ms - window.start_ts_ms
            # Fast-lane windows use a narrower timeout (50ms) to minimize protective latency.
            threshold_ms = _fastlane_ms if window.fastlane else self.micro_window_ms
            if elapsed >= threshold_ms:
                keys_to_flush.append(key)

        for key in keys_to_flush:
            self._flush_window(key)
    
    def _flush_window(self, key: Tuple[str, str]):
        """Arbitrate and publish winner for a decision window."""
        window = self.windows.get(key)
        if not window or window.flushed:
            return
        
        window.flushed = True
        self.stats["windows_arbitrated"] += 1
        
        account_id, symbol = key
        proposals = window.proposals
        
        if not proposals:
            del self.windows[key]
            return

        now_ms = int(time.time() * 1000)
        hedge_override_info = {}
        hedge_state, hedge_metrics, hedge_percentiles = self._update_hedge_state_from_proposals(
            account_id,
            symbol,
            proposals,
            now_ms,
        )
        if hedge_state in {"HEDGE_BUILD", "HEDGE_FULL", "HEDGE_PARTIAL"}:
            hedge_props = [p for p in proposals if self._is_hedge_like(p)]
            non_hedge_props = [p for p in proposals if not self._is_hedge_like(p)]
            if hedge_props and non_hedge_props:
                proposals = hedge_props
                hedge_override_info = {
                    "state": hedge_state,
                    "kept": len(hedge_props),
                    "dropped": len(non_hedge_props),
                    "reason": "HEDGE_FIRST_OVERRIDE",
                }
        
        # Hedge churn guard: keep only 1 hedge/protective proposal per window
        # TF-disagg hedges are always kept (they represent deconflicted minority-TF intelligence)
        hedge_guard_info = {}
        if HEDGE_CHURN_GUARD_ENABLED:
            hedge_props = [p for p in proposals if self._is_hedge_like(p)]
            non_hedge_props = [p for p in proposals if not self._is_hedge_like(p)]
            tf_disagg_hedges = [p for p in hedge_props if p.get("tf_hedge_disagg")]
            regular_hedges = [p for p in hedge_props if not p.get("tf_hedge_disagg")]
            dropped = []
            if len(regular_hedges) > 1:
                regular_hedges.sort(key=self._hedge_score, reverse=True)
                kept = regular_hedges[0]
                dropped = regular_hedges[1:]
                proposals = non_hedge_props + [kept] + tf_disagg_hedges
            else:
                proposals = non_hedge_props + regular_hedges + tf_disagg_hedges
            if dropped:
                dropped_count = len(dropped)
                self.stats["hedge_churn_dropped"] += dropped_count
                hedge_guard_info = {
                    "enabled": True,
                    "dropped": dropped_count,
                    "kept_action": str(regular_hedges[0].get("action") or regular_hedges[0].get("action_name") or "") if regular_hedges else "",
                    "kept_conf": float(regular_hedges[0].get("confidence") or regular_hedges[0].get("model_confidence") or 0.0) if regular_hedges else 0.0,
                    "tf_disagg_kept": len(tf_disagg_hedges),
                }
                logger.info(
                    f"🧹 [HEDGE_CHURN_GUARD] {account_id}:{symbol} dropped={dropped_count} tf_disagg_kept={len(tf_disagg_hedges)}"
                )

        logger.info(
            f"🎯 Arbitrating window {window.window_id}: {account_id}:{symbol} "
            f"({len(proposals)} proposals)"
        )
        
        # Check cooldown horizon for conflicts
        conflict_info = self._check_cooldown_conflict(key, proposals)
        
        try:
            if self.orchestrator:
                # Use TradePlanOrchestrator for arbitration
                decision = self.orchestrator.orchestrate_group(proposals)
                
                winner = decision.winner
                dropped = decision.dropped
                reason = decision.reason
                proof = decision.proof
                

                # Add extra fields to proof
                proof["decision_window_id"] = window.window_id
                proof["decision_window_ms"] = int(time.time() * 1000) - window.start_ts_ms
                proof["proposal_count"] = len(proposals)
                proof["sources"] = list(set(
                    str(p.get("source_module") or p.get("source") or "unknown")
                    for p in proposals
                ))
                proof["conflict_check"] = conflict_info
                if hedge_guard_info:
                    proof["hedge_churn_guard"] = hedge_guard_info
                proof["hedge_state"] = hedge_state
                if hedge_metrics:
                    proof["hedge_metrics"] = hedge_metrics
                if hedge_percentiles:
                    proof["hedge_percentiles"] = hedge_percentiles
                if hedge_override_info:
                    proof["hedge_override"] = hedge_override_info
                
                if dropped:
                    self.stats["signals_dropped"] += 1
                    logger.info(
                        f"❌ Dropped: {account_id}:{symbol} {winner.get('action')} | reason={reason}"
                    )
                else:
                    # Check cooldown conflict (TF-disagg hedges bypass)
                    if conflict_info.get("has_conflict") and not bool(winner.get("tf_hedge_disagg")):
                        # Compare with existing plan
                        if not self._should_replace_plan(winner, conflict_info):
                            self.stats["conflicts_prevented"] += 1
                            dropped = True
                            reason = f"COOLDOWN_CONFLICT|existing={conflict_info.get('existing_action')}"
                            proof["cooldown_blocked"] = True
                            logger.info(
                                f"🛡️ Conflict prevented: {account_id}:{symbol} {winner.get('action')} "
                                f"blocked by existing {conflict_info.get('existing_action')}"
                            )
                
                if not dropped:
                    # Special-case: ECF v2 "FREE_MARGIN_FOR_HEDGE" is a sequencer intent, not a tradable action.
                    # Convert it into profit-only partial closes on OTHER symbols (NO_LOSS compliant),
                    # then do NOT publish the original FREE_MARGIN_FOR_HEDGE signal.
                    try:
                        act_u = str(winner.get("action") or "").strip().upper()
                    except Exception:
                        act_u = ""
                    if act_u == "FREE_MARGIN_FOR_HEDGE":
                        batch = self._handle_free_margin_for_hedge(winner, proof)
                        proof["ecf_free_margin_batch"] = batch
                        if batch.get("published_count", 0) > 0:
                            # Treat as executed (sequenced) rather than dropped.
                            proof["ecf_sequencer_executed"] = True
                            proof["ecf_sequencer_action"] = "FREE_MARGIN_FOR_HEDGE"
                            proof["ecf_target_symbol"] = str(winner.get("symbol") or "").upper()
                            proof["ecf_target_margin_usd"] = float(winner.get("target_margin_usd") or 0.0)
                            proof["ecf_reason"] = "FREE_MARGIN_FOR_HEDGE translated into profit-only trims"
                            # Do not publish original winner
                            dropped = True
                            reason = "ECF_FREE_MARGIN_BATCH"
                            proof["reason"] = reason
                        else:
                            proof["ecf_sequencer_executed"] = False
                            proof["ecf_reason"] = "no profit donors available for free-margin"
                            dropped = True
                            reason = "DROP_ECF_NO_DONORS"
                            proof["reason"] = reason

                if not dropped:
                    # Publish winner
                    plan_id = self._publish_winner(winner, proof)
                    
                    if plan_id:
                        # Record in published plans for cooldown
                        self._record_published_plan(key, winner, plan_id, proof)
                    else:
                        pass
                
                # Emit proof
                self._emit_proof(proof)
                
            else:
                # Fallback: simple winner selection (first by priority, then confidence)
                proposals.sort(
                    key=lambda p: (
                        int(p.get("priority") or 1),
                        float(p.get("confidence") or 0),
                    ),
                    reverse=True,
                )
                winner = proposals[0]
                
                if not conflict_info.get("has_conflict"):
                    plan_id = self._publish_winner(winner, {})
                    if plan_id:
                        self._record_published_plan(key, winner, plan_id, {})
                else:
                    self.stats["conflicts_prevented"] += 1
                    logger.info(
                        f"🛡️ Conflict prevented (no orchestrator): {account_id}:{symbol}"
                    )
        
        except Exception as e:
            logger.error(f"Arbitration failed for {key}: {e}", exc_info=True)
        
        # Clean up window
        del self.windows[key]
    
    def _check_cooldown_conflict(
        self,
        key: Tuple[str, str],
        proposals: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check if new proposals conflict with recently published plans.

        Also detects CLOSE-then-reopen conflicts via Redis close cooldown keys
        to prevent hedge v3 from immediately reopening what the trainer just closed.
        """
        account_id, symbol = key
        now_ms = int(time.time() * 1000)

        # ── Phase 3: Redis-based close cooldown detection ──────────
        for prop in proposals:
            new_action = str(prop.get("action") or "").upper()
            _is_open = ("OPEN" in new_action or "ADD" in new_action) and "CLOSE" not in new_action
            if _is_open:
                _open_side = None
                if "LONG" in new_action:
                    _open_side = "LONG"
                elif "SHORT" in new_action:
                    _open_side = "SHORT"
                if _open_side:
                    try:
                        _redis = getattr(self, "redis", None) or getattr(getattr(self, "orchestrator", None), "redis", None)
                        if _redis:
                            _cd_key = f"position:close_cooldown:{str(symbol).upper()}:{_open_side}"
                            _cd_val = _redis.get(_cd_key)
                            if _cd_val:
                                _cd_str = _cd_val.decode("utf-8") if isinstance(_cd_val, (bytes, bytearray)) else str(_cd_val)
                                logger.info(
                                    "ORCH_CLOSE_COOLDOWN_CONFLICT | sym=%s action=%s | "
                                    "trainer recently closed %s (%s) — blocking reopen",
                                    symbol, new_action, _open_side, _cd_str,
                                )
                                return {
                                    "has_conflict": True,
                                    "existing_plan_id": "close_cooldown",
                                    "existing_action": f"MODEL_CLOSE_{_open_side}",
                                    "existing_family": "CLOSE",
                                    "existing_ts_ms": now_ms,
                                    "time_since_ms": 0,
                                }
                    except Exception:
                        pass

        # Get recent published plans for this (account, symbol)
        recent_plans = [
            p for p in self.published_plans.get(key, [])
            if (now_ms - p.published_ts_ms) < self.cooldown_horizon_ms
        ]
        
        if not recent_plans:
            return {"has_conflict": False}
        
        # Check for conflicting actions
        latest_plan = max(recent_plans, key=lambda p: p.published_ts_ms)
        
        # Determine if new proposals conflict
        for prop in proposals:
            new_action = str(prop.get("action") or "").upper()
            new_family = self._action_family(new_action)
            
            # Conflicting families
            if self._are_conflicting_families(latest_plan.action_family, new_family):
                return {
                    "has_conflict": True,
                    "existing_plan_id": latest_plan.plan_id,
                    "existing_action": latest_plan.action,
                    "existing_family": latest_plan.action_family,
                    "existing_ts_ms": latest_plan.published_ts_ms,
                    "time_since_ms": now_ms - latest_plan.published_ts_ms,
                }
        
        return {"has_conflict": False}
    
    def _action_family(self, action: str) -> str:
        """Get action family for conflict detection."""
        action = action.upper()
        if action.startswith("OPEN_HEDGE") or action.startswith("ADD_HEDGE"):
            return "HEDGE_ADD"
        if "PARTIAL_CLOSE" in action:
            return "PARTIAL_CLOSE"
        if "CLOSE" in action:
            return "CLOSE"
        if action.startswith("OPEN_") or action.startswith("INCREASE_"):
            return "OPEN_INCREASE"
        return action
    
    def _are_conflicting_families(self, family1: str, family2: str) -> bool:
        """Check if two action families conflict."""
        # OPEN_INCREASE conflicts with CLOSE/PARTIAL_CLOSE
        if family1 == "OPEN_INCREASE" and family2 in ("CLOSE", "PARTIAL_CLOSE"):
            return True
        if family2 == "OPEN_INCREASE" and family1 in ("CLOSE", "PARTIAL_CLOSE"):
            return True
        
        # HEDGE_ADD conflicts with PARTIAL_CLOSE (of hedge leg)
        if family1 == "HEDGE_ADD" and family2 == "PARTIAL_CLOSE":
            return True
        if family2 == "HEDGE_ADD" and family1 == "PARTIAL_CLOSE":
            return True
        
        return False
    
    def _should_replace_plan(
        self,
        new_winner: Dict[str, Any],
        conflict_info: Dict[str, Any],
    ) -> bool:
        """
        Determine if new winner should replace existing plan.
        
        Only replace if new plan has significantly higher priority or edge.
        """
        new_priority = int(new_winner.get("priority") or 1)
        new_edge = float(new_winner.get("expected_edge_net") or 0)
        
        # CRITICAL always replaces
        if new_priority >= 3:
            return True
        
        # Otherwise, require substantial improvement
        # (This is conservative - prevents thrashing)
        return False

    def _handle_free_margin_for_hedge(self, winner: Dict[str, Any], proof: Dict[str, Any]) -> Dict[str, Any]:
        """
        ECF v2 sequencer: convert FREE_MARGIN_FOR_HEDGE into profit-only partial closes on OTHER symbols.

        Notes:
        - This does NOT realize losses (profit-only donors).
        - This does NOT publish STOP_LOSS; it only emits PARTIAL_CLOSE_* with profit_intent=True.
        - This is best-effort. If no donors are available, returns published_count=0.
        """
        try:
            account_id = str(winner.get("account_id") or "primary").strip().lower()
        except Exception:
            account_id = "primary"
        target_symbol = str(winner.get("symbol") or "").strip().upper()
        try:
            target_margin_usd = float(winner.get("target_margin_usd") or 0.0)
        except Exception:
            target_margin_usd = 0.0

        # Fall back to reserve if caller didn't specify a target amount.
        if target_margin_usd <= 0:
            try:
                target_margin_usd = float(getattr(config, "HEDGE_HEADROOM_RESERVE_USD", 150.0)) if config else 150.0
            except Exception:
                target_margin_usd = 150.0

        # Global ECF cooldown (prevents repeated margin-freeing churn).
        # If the HedgeManager is spamming FREE_MARGIN_FOR_HEDGE, we will suppress repeats here as a second line of defense.
        try:
            cooldown_sec = int(os.getenv("ECF_FREE_MARGIN_COOLDOWN_SEC", "600"))
        except Exception:
            cooldown_sec = 600
        cooldown_sec = max(60, min(3600, int(cooldown_sec)))
        cooldown_key = f"ecf:free_margin:cooldown:{account_id}:{target_symbol or 'ALL'}"
        try:
            if self.redis is not None:
                if self.redis.get(cooldown_key):
                    return {
                        "account_id": account_id,
                        "target_symbol": target_symbol,
                        "target_margin_usd": float(target_margin_usd),
                        "published_count": 0,
                        "freed_margin_est_usd": 0.0,
                        "remaining_est_usd": float(target_margin_usd),
                        "published": [],
                        "cooldown": True,
                        "cooldown_sec": int(cooldown_sec),
                    }
        except Exception:
            pass

        try:
            max_close_pct = float(getattr(config, "FREESPACE_REBALANCER_MAX_CLOSE_PCT", 0.35)) if config else 0.35
        except Exception:
            max_close_pct = 0.35
        max_close_pct = max(0.05, min(0.75, max_close_pct))

        # Keep actions limited (avoid churn); configurable via env.
        try:
            max_actions = int(os.getenv("ECF_FREE_MARGIN_MAX_ACTIONS", "4"))
        except Exception:
            max_actions = 4
        max_actions = max(1, min(10, max_actions))

        try:
            min_frac = float(os.getenv("ECF_FREE_MARGIN_MIN_CLOSE_FRACTION", "0.10"))
        except Exception:
            min_frac = 0.10
        min_frac = max(0.02, min(0.25, min_frac))

        donors = []
        try:
            raw = self.redis.hgetall(f"portfolio:positions:{account_id}") or {}
        except Exception:
            raw = {}

        for field, val in (raw or {}).items():
            try:
                f = str(field)
                if ":" not in f:
                    continue
                sym, side = f.split(":", 1)
                sym = str(sym).upper().strip()
                side_u = str(side).upper().strip()
                if not sym or sym == target_symbol:
                    continue

                if isinstance(val, str):
                    d = json.loads(val) if val and val.lstrip().startswith("{") else {}
                else:
                    d = val if isinstance(val, dict) else {}

                margin = float(d.get("margin_used", 0.0) or d.get("initialMargin", 0.0) or d.get("initial_margin", 0.0) or 0.0)
                pnl = float(d.get("unrealized_pnl", 0.0) or d.get("unrealizedPnl", 0.0) or d.get("pnl_usd", 0.0) or 0.0)
                size = float(d.get("size", 0.0) or 0.0)
                if abs(size) <= 0.0 or margin <= 0.0:
                    continue
                if pnl <= 0.0:
                    continue

                donors.append(
                    {
                        "symbol": sym,
                        "side": "LONG" if "LONG" in side_u else ("SHORT" if "SHORT" in side_u else ""),
                        "margin_used": abs(margin),
                        "pnl": pnl,
                        "score": pnl / max(1.0, abs(margin)),
                    }
                )
            except Exception:
                continue

        donors.sort(key=lambda x: (x["score"], x["pnl"]), reverse=True)

        remaining = float(target_margin_usd)
        published = []
        freed_est = 0.0

        for d in donors:
            if remaining <= 0 or len(published) >= max_actions:
                break
            sym = d["symbol"]
            side = d["side"]
            if side not in ("LONG", "SHORT"):
                continue

            # Estimate the close fraction needed to free margin, bounded for safety.
            try:
                frac = remaining / float(d["margin_used"])
            except Exception:
                frac = 0.0
            frac = max(min_frac, min(max_close_pct, float(frac)))
            if frac <= 0.0:
                continue

            signal = {
                "account_id": account_id,
                "symbol": sym,
                "action": f"PARTIAL_CLOSE_{side}",
                "action_name": f"PARTIAL_CLOSE_{side}",
                "timeframe": "multi",
                "confidence": 0.95,  # Sequencer actions are deterministic/protective
                "close_fraction": float(frac),
                "action_category": "PROTECTIVE",
                "source": "orchestrator_ecf_free_margin",
                "profit_intent": True,
                "no_loss_compliant": True,
                "_ecf_parent_symbol": target_symbol,
                "_ecf_target_margin_usd": float(target_margin_usd),
            }

            # Respect cooldown horizon to avoid churn.
            key = (account_id, sym)
            try:
                conflict = self._check_cooldown_conflict(key, [signal])
                if conflict.get("has_conflict") and (not self._should_replace_plan(signal, conflict)):
                    continue
            except Exception:
                pass

            plan_id = self._publish_winner(signal, proof)
            if plan_id:
                self._record_published_plan(key, signal, plan_id, proof)
                freed = float(d["margin_used"]) * float(frac)
                freed_est += freed
                remaining -= freed
                published.append(
                    {
                        "plan_id": plan_id,
                        "symbol": sym,
                        "side": side,
                        "close_fraction": float(frac),
                        "freed_margin_est_usd": float(freed),
                    }
                )

        # Arm cooldown after any successful publish; also arm a short cooldown when no donors exist
        # to prevent a tight spam loop.
        try:
            if self.redis is not None:
                if len(published) > 0:
                    self.redis.setex(cooldown_key, int(cooldown_sec), "1")
                else:
                    # No donors: don't hammer every cycle; short backoff
                    self.redis.setex(cooldown_key, int(min(120, cooldown_sec)), "0")
        except Exception:
            pass

        return {
            "account_id": account_id,
            "target_symbol": target_symbol,
            "target_margin_usd": float(target_margin_usd),
            "published_count": int(len(published)),
            "freed_margin_est_usd": float(freed_est),
            "remaining_est_usd": float(max(0.0, remaining)),
            "published": published,
        }

    def _try_hedge_liq_fail_fallback(
        self,
        winner: Dict[str, Any],
        proof: Dict[str, Any],
        account_id: str,
        symbol: str,
        action: str,
        liq_result: Dict[str, Any],
    ) -> bool:
        """If protective ADD_HEDGE is blocked by liq buffer, rewrite winner to PARTIAL_CLOSE on main leg."""
        try:
            enabled = bool(getattr(config, "ORCH_HEDGE_LIQ_FAIL_FALLBACK_ENABLED", True))
        except Exception:
            enabled = True
        if not enabled:
            return False
        act_u = str(action or "").upper().strip()
        if not act_u.startswith("ADD_HEDGE_"):
            return False
        reason = str((liq_result or {}).get("reason") or "")
        if reason not in ("LIQ_TOO_LOW", "LIQ_NONE"):
            return False

        mc = winner.get("market_context") if isinstance(winner.get("market_context"), dict) else {}
        meta = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        src = str(winner.get("source_module") or winner.get("source") or "").upper()
        trig = (
            str(winner.get("trigger_reason") or "")
            + " "
            + str(meta.get("trigger_reason") or "")
            + " "
            + str(winner.get("reason") or "")
        ).upper()
        stop_t = str(mc.get("stop_type") or meta.get("stop_type") or "").upper()
        cat = str(winner.get("action_category") or winner.get("category") or "").upper()
        stealthish = (
            "STEALTH" in src
            or "STEALTH" in trig
            or "TRAIL" in trig
            or stop_t == "STOP_LOSS"
        )
        hedgeish = (
            "HEDGE" in cat
            or "PROFIT_HEDGE" in src
            or "STEALTH_PROFIT_HEDGE" in src
            or str(mc.get("source") or "").lower().find("profit_hedge") >= 0
        )
        if not (stealthish or hedgeish):
            return False

        hedge_is_long = "LONG" in act_u and "SHORT" not in act_u
        hedge_is_short = "SHORT" in act_u and "LONG" not in act_u
        if hedge_is_long:
            main_side = "SHORT"
        elif hedge_is_short:
            main_side = "LONG"
        else:
            return False

        if not self.redis:
            return False
        # Hedge-mode safe leg truth: prefer per-leg portfolio positions, fall back to net positions:live.
        legs = {}
        try:
            legs = self._get_hedge_legs(account_id, symbol) or {}
        except Exception:
            legs = {}
        if legs:
            # If we cannot confirm that the main leg exists, do not rewrite.
            if main_side not in legs:
                return False
        else:
            try:
                raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
            except Exception:
                raw_live = {}

            def _gv(k):
                v = raw_live.get(k) or raw_live.get(k.encode() if isinstance(k, str) else k)
                if v is None:
                    return ""
                return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)

            side_live = str(_gv("side") or _gv(b"side")).upper()
            if not side_live:
                try:
                    amt = float(_gv("position_amt") or _gv(b"position_amt") or 0.0)
                except (TypeError, ValueError):
                    amt = 0.0
                side_live = "LONG" if amt > 0 else "SHORT" if amt < 0 else ""
            if side_live != main_side:
                return False

        try:
            frac = float(getattr(config, "ORCH_HEDGE_LIQ_FAIL_CLOSE_FRACTION", 0.35))
        except Exception:
            frac = 0.35
        frac = max(0.05, min(0.95, frac))

        close_action = f"PARTIAL_CLOSE_{main_side}"
        winner["action"] = close_action
        winner["action_name"] = close_action
        winner["action_category"] = "PROTECTIVE"
        winner["category"] = "PROTECTIVE"
        winner["side"] = main_side
        winner["current_position_side"] = main_side
        winner["reduce_only"] = True
        winner["close_fraction"] = float(frac)
        winner["margin_usd"] = 0.0
        winner["notional_usd"] = 0.0
        winner.setdefault("risk_reducing", True)
        meta = dict(meta)
        meta["hedge_liq_fallback"] = "1"
        meta["hedge_liq_fallback_from"] = act_u
        meta["hedge_liq_fallback_liq_reason"] = reason
        winner["metadata"] = meta

        proof["hedge_liq_fallback"] = {
            "from": act_u,
            "to": close_action,
            "close_fraction": frac,
            "liq_reason": reason,
            "liq": liq_result.get("liq"),
            "min_liq": liq_result.get("min_liq"),
        }
        logger.warning(
            "ORCH_HEDGE_LIQ_FALLBACK | account=%s | symbol=%s | %s -> %s | close_fraction=%.2f | "
            "liq_reason=%s liq=%s min_liq=%s",
            account_id,
            symbol,
            act_u,
            close_action,
            frac,
            reason,
            liq_result.get("liq"),
            liq_result.get("min_liq"),
        )
        try:
            self._publish_exec_event(
                code="ORCH_HEDGE_LIQ_FALLBACK",
                account_id=account_id,
                symbol=symbol,
                action=close_action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta=dict(proof["hedge_liq_fallback"]),
            )
        except Exception:
            pass
        return True

    def _publish_winner(
        self,
        winner: Dict[str, Any],
        proof: Dict[str, Any],
    ) -> Optional[str]:
        """Publish winning signal to the appropriate stream."""
        account_id = str(winner.get("account_id") or "primary").strip().lower()
        symbol = str(winner.get("symbol") or "").strip().upper()
        action = str(winner.get("action") or "").strip().upper()
        source = str(winner.get("source_module") or winner.get("source") or "unknown")
        category = str(winner.get("category") or winner.get("action_category") or "").strip().upper()

        # Normalize stealth TP close proposals as hedge trims (P0 hardening)
        try:
            meta_blob0 = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
            action_u0 = str(action or "").upper().strip()
            is_reduce0 = any(tok in action_u0 for tok in ("PARTIAL_CLOSE", "DECREASE", "REDUCE", "CLOSE")) and "CLOSE_AND" not in action_u0
            reason_text0 = " ".join([
                str(winner.get("reason") or ""),
                str(winner.get("trigger_reason") or ""),
                str(meta_blob0.get("reason") or ""),
                str(meta_blob0.get("reasoning") or ""),
            ]).upper()
            proposal_stream0 = str(
                winner.get("_proposal_stream")
                or winner.get("proposal_stream")
                or meta_blob0.get("_proposal_stream")
                or meta_blob0.get("proposal_stream")
                or ""
            ).lower()
            if is_reduce0 and (
                proposal_stream0 == "proposals:stealth_stops"
                or "STEALTH_TRIGGER TAKE_PROFIT" in reason_text0
            ):
                winner["action_category"] = "HEDGE_TRIM"
                winner["category"] = "HEDGE_TRIM"
                winner["subtype"] = "TP_STEALTH"
                meta_blob0["action_category"] = "HEDGE_TRIM"
                meta_blob0["category"] = "HEDGE_TRIM"
                meta_blob0["subtype"] = "TP_STEALTH"
                winner["metadata"] = meta_blob0
                category = "HEDGE_TRIM"
        except Exception:
            pass

        is_canary = action == "CANARY" or category in ("SYSTEM", "SYSTEM_CANARY") or "SYSTEM_CANARY" in category


        # ── Fix #3: Per-cycle entry cap ─ limit new ENTRY signals per rolling window ─────
        # Buckets (3-way split to avoid INCREASE eating the OPEN budget):
        #   HEDGE_*  → ORCH_MAX_NEW_HEDGES_PER_CYCLE   (default 5)
        #   INCREASE_* / ADD_TO_* → ORCH_MAX_NEW_INCREASES_PER_CYCLE (default 4)
        #   OPEN_* / FLIP_* / everything else → ORCH_MAX_NEW_ENTRIES_PER_CYCLE (default 3)
        if self._is_risk_add_action(action) and not is_canary:
            try:
                _action_u_cap = str(action).upper()
                _action_is_hedge = "HEDGE" in _action_u_cap
                _action_is_increase = (
                    not _action_is_hedge
                    and (_action_u_cap.startswith("INCREASE") or _action_u_cap.startswith("ADD_TO") or _action_u_cap.startswith("ADD_"))
                )
                if _action_is_hedge:
                    max_entries = int(getattr(config, "ORCH_MAX_NEW_HEDGES_PER_CYCLE", 5))
                    _cap_log = self._hedge_publish_log
                    _cap_label = "ORCH_HEDGE_CAP_BLOCK"
                elif _action_is_increase:
                    max_entries = int(getattr(config, "ORCH_MAX_NEW_INCREASES_PER_CYCLE", 4))
                    _cap_log = self._entry_publish_log  # shared with opens (same risk pool)
                    _cap_label = "ORCH_ENTRY_CAP_BLOCK"
                else:
                    max_entries = int(getattr(config, "ORCH_MAX_NEW_ENTRIES_PER_CYCLE", 3))
                    _cap_log = self._entry_publish_log
                    _cap_label = "ORCH_ENTRY_CAP_BLOCK"
                now_t = time.time()
                # Prune old entries outside window
                _pruned = [t for t in _cap_log if (now_t - t) < self._entry_cap_window_sec]
                if _action_is_hedge:
                    self._hedge_publish_log = _pruned
                else:
                    self._entry_publish_log = _pruned
                if len(_pruned) >= max_entries:
                    proof["dropped"] = True
                    proof["risk_reject_code"] = _cap_label
                    logger.warning(
                        "%s | account=%s | symbol=%s | action=%s | "
                        "entries_in_window=%d | max=%d | window_sec=%.0f",
                        _cap_label, account_id, symbol, action,
                        len(_pruned), max_entries,
                        self._entry_cap_window_sec,
                    )
                    self._publish_exec_event(
                        code=_cap_label,
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta={
                            "entries_in_window": len(_pruned),
                            "max_entries": max_entries,
                            "window_sec": self._entry_cap_window_sec,
                            "is_hedge": _action_is_hedge,
                        },
                    )
                    return None

                # Also check max concurrent positions
                max_concurrent = int(getattr(config, "ORCH_MAX_CONCURRENT_POSITIONS", 10))
                try:
                    _pos_raw = self.redis.hgetall(f"positions:{account_id}") if self.redis else {}
                    _live_syms = set()
                    for _pk, _pv in (_pos_raw or {}).items():
                        try:
                            _pkey = _pk.decode("utf-8") if isinstance(_pk, (bytes, bytearray)) else str(_pk)
                            _pval = _pv.decode("utf-8") if isinstance(_pv, (bytes, bytearray)) else str(_pv)
                            _pdata = json.loads(_pval)
                            if isinstance(_pdata, dict):
                                _pamt = float(_pdata.get("positionAmt") or _pdata.get("size") or 0)
                                if abs(_pamt) > 0:
                                    _psym = str(_pdata.get("symbol") or _pkey.split(":")[0]).upper()
                                    _live_syms.add(_psym)
                        except Exception:
                            pass
                    if len(_live_syms) >= max_concurrent and symbol.upper() not in _live_syms:
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "ORCH_MAX_CONCURRENT_BLOCK"
                        logger.warning(
                            "ORCH_MAX_CONCURRENT_BLOCK | account=%s | symbol=%s | "
                            "open_positions=%d | max=%d | open=%s",
                            account_id, symbol,
                            len(_live_syms), max_concurrent,
                            sorted(list(_live_syms))[:6],
                        )
                        self._publish_exec_event(
                            code="ORCH_MAX_CONCURRENT_BLOCK",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta={
                                "open_positions": len(_live_syms),
                                "max_concurrent": max_concurrent,
                                "open_symbols": sorted(list(_live_syms))[:6],
                            },
                        )
                        return None
                except Exception as _cc_err:
                    logger.debug("ORCH_CONCURRENT_CHECK_ERR | %s", _cc_err)
            except Exception as _cap_err:
                logger.debug("ORCH_ENTRY_CAP_ERR | %s", _cap_err)

        # ── Fix #4: Hedge swap under tight margin ─────────────────────────────
        # When hedge-add is proposed but MU is tight, convert to a swap:
        # partial-close main leg, then open hedge with freed margin.
        try:
            hedge_swap_enabled = bool(getattr(config, "HEDGE_SWAP_ENABLED", True))
            hedge_swap_mu = float(getattr(config, "HEDGE_SWAP_MU_THRESHOLD", 0.45))
            act_u_swap = str(action or "").upper()
            is_hedge_add = ("HEDGE" in act_u_swap and ("OPEN" in act_u_swap or "ADD" in act_u_swap or "INCREASE" in act_u_swap))

            if hedge_swap_enabled and is_hedge_add and not is_canary:
                _swap_mu = float(winner.get("margin_util") or 0.0)
                if _swap_mu <= 0:
                    _swap_port = build_portfolio_snapshot(self.redis, account_id) if self.redis else {}
                    _swap_mu = float(_swap_port.get("margin_util") or 0.0)

                if _swap_mu >= hedge_swap_mu:
                    # Convert hedge-add to swap: partial-close main leg first
                    hedge_side = "LONG" if "LONG" in act_u_swap else "SHORT" if "SHORT" in act_u_swap else ""
                    main_side = "SHORT" if hedge_side == "LONG" else "LONG" if hedge_side == "SHORT" else ""

                    if main_side and symbol:
                        # Check if main leg actually exists
                        _pos_raw_swap = self.redis.hgetall(f"positions:{account_id}") if self.redis else {}
                        main_exists = False
                        for _spk, _spv in (_pos_raw_swap or {}).items():
                            try:
                                _skey = _spk.decode("utf-8") if isinstance(_spk, (bytes, bytearray)) else str(_spk)
                                _sval = _spv.decode("utf-8") if isinstance(_spv, (bytes, bytearray)) else str(_spv)
                                _sdata = json.loads(_sval)
                                if isinstance(_sdata, dict):
                                    _ssym = str(_sdata.get("symbol") or _skey.split(":")[0]).upper()
                                    _sside = str(_sdata.get("positionSide") or "").upper()
                                    _samt = float(_sdata.get("positionAmt") or _sdata.get("size") or 0)
                                    if _ssym == symbol.upper() and _sside == main_side and abs(_samt) > 0:
                                        main_exists = True
                                        break
                            except Exception:
                                pass

                        if main_exists:
                            # Publish a partial-close of main leg FIRST (to free margin)
                            hedge_margin = float(winner.get("margin_usd") or 0.0)
                            trim_pct = min(0.30, max(0.10, hedge_margin / max(1.0, float(winner.get("position_margin") or hedge_margin * 3))))  # 10-30% trim
                            trim_action = f"PARTIAL_CLOSE_{main_side}"
                            _trim_now_ms = int(time.time() * 1000)
                            trim_signal = {
                                "action": trim_action,
                                "action_name": trim_action,
                                "action_category": "HEDGE_SWAP_TRIM",
                                "symbol": symbol,
                                "account_id": account_id,
                                "confidence": 0.95,
                                "reduce_only": True,
                                "percentage": round(trim_pct, 4),
                                "source": "hedge_swap",
                                "source_module": "hedge_swap",
                                "reason": f"HEDGE_SWAP: free margin for {action} (MU={_swap_mu:.1%})",
                                "timeframe": str(winner.get("timeframe") or "5m"),
                                "published_by": "orchestrator_worker",
                                "published_ts_ms": _trim_now_ms,
                                "ts_ms": _trim_now_ms,
                                "created_ts_ms": _trim_now_ms,
                                "timestamp": time.time(),
                                "event": "TRADING_SIGNAL",
                                "plan_id": f"swap_trim_{_trim_now_ms}_{uuid.uuid4().hex[:8]}",
                            }
                            try:
                                # ── Stamp exec token so trader approval gate accepts this signal ──
                                if getattr(config, "ORCH_EXEC_TOKEN_ENABLED", True):
                                    try:
                                        import hashlib as _hl_trim
                                        _trim_pid = str(trim_signal.get("plan_id") or "")
                                        _trim_sig_input = f"{_trim_pid}:{symbol}:{trim_action}:{account_id}"
                                        trim_signal["orch_approved"] = 1
                                        trim_signal["orch_plan_sig"] = _hl_trim.sha256(_trim_sig_input.encode()).hexdigest()[:16]
                                        trim_signal["orch_ts_ms"] = int(trim_signal.get("published_ts_ms") or (time.time() * 1000))
                                        trim_signal["published_by"] = "orchestrator_worker"
                                    except Exception:
                                        trim_signal["orch_approved"] = 1  # stamp even if hash fails
                                from utils.signal_publish import publish_trading_signal
                                _swap_stream = SIGNAL_STREAM_ASJAD if account_id == "asjad" else SIGNAL_STREAM_PRIMARY
                                publish_trading_signal(
                                    self.redis,
                                    _swap_stream,
                                    {"data": json.dumps(trim_signal, separators=(",", ":"), default=str)},
                                    maxlen=int(self.signal_maxlen),
                                    approximate=True,
                                )
                                logger.warning(
                                    "HEDGE_SWAP_TRIM_PUBLISHED | account=%s | symbol=%s | "
                                    "trim_side=%s | trim_pct=%.1f%% | mu=%.1f%% | "
                                    "then_hedge=%s",
                                    account_id, symbol, main_side,
                                    trim_pct * 100, _swap_mu * 100, action,
                                )
                                proof["hedge_swap"] = {
                                    "trim_side": main_side,
                                    "trim_pct": round(trim_pct * 100, 1),
                                    "mu_pct": round(_swap_mu * 100, 1),
                                    "freed_margin_est": round(hedge_margin * trim_pct, 2),
                                }
                                # Add small delay annotation for trader sequencing
                                winner["hedge_swap_delay_ms"] = 3000
                                winner["hedge_swap_trim_plan"] = trim_signal.get("plan_id")
                            except Exception as _swap_pub_err:
                                logger.debug("HEDGE_SWAP_TRIM_PUB_ERR | %s", _swap_pub_err)
        except Exception as _swap_err:
            logger.debug("HEDGE_SWAP_CHECK_ERR | %s", _swap_err)

        try:
            self._profit_close_hedge_preflight(
                winner,
                account_id=account_id,
                symbol=symbol,
                action=action,
                category=category,
                proof=proof,
            )
        except Exception:
            pass

        # Final account enable + preflight gate before any publish attempt.
        requested_account = str(winner.get("requested_account_id") or account_id).strip().lower()
        tf = str(winner.get("timeframe") or winner.get("tf") or "").strip().lower()
        decision_id = str(winner.get("decision_id") or winner.get("proposal_id") or winner.get("trace_id") or "")
        if not self._is_account_enabled(account_id):
            if account_id == "asjad" and self._is_risk_add_action(action):
                account_id = "primary"
                winner["account_id"] = "primary"
                logger.info(
                    "ORCH_ACCOUNT_REROUTE_PUBLISH | reason=ACCOUNT_DISABLED_ASJAD | requested=%s | selected=%s | symbol=%s | action=%s",
                    requested_account,
                    account_id,
                    symbol,
                    action,
                )
            else:
                proof["dropped"] = True
                proof["risk_reject_code"] = "ACCOUNT_DISABLED"
                logger.warning(
                    "ORCH_ACCOUNT_DISABLED_PUBLISH | account=%s | symbol=%s | action=%s | requested=%s",
                    account_id,
                    symbol,
                    action,
                    requested_account,
                )
                self._publish_exec_event(
                    code="ACCOUNT_DISABLED_ASJAD",
                    account_id=requested_account or account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta={"requested_account": requested_account, "selected_account": "", "reason": "ACCOUNT_DISABLED_ASJAD"},
                )
                self._emit_account_diag(
                    kind="orch_account_disabled",
                    decision_id=decision_id,
                    symbol=symbol,
                    tf=tf,
                    requested_account=requested_account,
                    selected_account="",
                    reason="ACCOUNT_DISABLED_ASJAD",
                    reasons_json={"account_disabled": True, "stage": "publish"},
                )
                return None

        preflight_ok, preflight_meta = self._account_preflight(account_id, symbol, action)
        if not preflight_ok:
            if account_id == "asjad" and self._is_risk_add_action(action):
                winner["requested_account_id"] = "asjad"
                winner["account_id"] = "primary"
                account_id = "primary"
                logger.warning(
                    "ORCH_ACCOUNT_PREFLIGHT_REROUTE | requested=asjad | selected=primary | symbol=%s | action=%s | meta=%s",
                    symbol,
                    action,
                    preflight_meta,
                )
                self._emit_account_diag(
                    kind="orch_account_select",
                    decision_id=decision_id,
                    symbol=symbol,
                    tf=tf,
                    requested_account="asjad",
                    selected_account="primary",
                    reason="ASJAD_PREFLIGHT_FAIL_REROUTE",
                    reasons_json=preflight_meta,
                )
            else:
                proof["dropped"] = True
                proof["risk_reject_code"] = "ACCOUNT_PREFLIGHT_FAILED"
                proof["risk_reject_meta"] = preflight_meta or {}
                logger.warning(
                    "ORCH_ACCOUNT_PREFLIGHT_FAILED | account=%s | symbol=%s | action=%s | meta=%s",
                    account_id,
                    symbol,
                    action,
                    preflight_meta,
                )
                self._publish_exec_event(
                    code="ACCOUNT_PREFLIGHT_FAILED",
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta=preflight_meta,
                )
                self._emit_account_diag(
                    kind="orch_account_select",
                    decision_id=decision_id,
                    symbol=symbol,
                    tf=tf,
                    requested_account=requested_account or account_id,
                    selected_account="",
                    reason="ACCOUNT_PREFLIGHT_FAILED",
                    reasons_json=preflight_meta,
                )
                return None

        # Ensure top-level timeframe + signal_id for downstream assertions (ORCH-04)
        meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        if not winner.get("timeframe"):
            tf = meta_blob.get("timeframe") or meta_blob.get("tf") or meta_blob.get("interval")
            if tf:
                winner["timeframe"] = tf
        if not winner.get("signal_id"):
            sig = meta_blob.get("signal_id") or meta_blob.get("signalId") or winner.get("proposal_id") or winner.get("trace_id")
            if sig:
                winner["signal_id"] = sig
        # Enrich missing DQ fields from feature store before gating.
        self._enrich_signal_with_features(winner, proof)
        meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
        self._cleanup_dq_missing_fields(winner, meta_blob, ["liq_distance_pct", "orderbook_depth_usd", "volatility_pct"])

        # Entry context gate: prevent confidently-wrong OPEN_RISK publishes when TF/liq context is missing/conflicting.
        ctx_ok, ctx_code, ctx_meta = self._entry_context_gate(
            winner,
            account_id=account_id,
            symbol=symbol,
            action=action,
        )
        if not ctx_ok and ctx_code:
            proof["dropped"] = True
            proof["risk_reject_code"] = str(ctx_code)
            proof["risk_reject_meta"] = ctx_meta or {}
            logger.warning(
                "ORCH_CONTEXT_GATE_BLOCK | account=%s | symbol=%s | action=%s | code=%s | meta=%s",
                account_id,
                symbol,
                action,
                ctx_code,
                ctx_meta,
            )
            self._publish_exec_event(
                code=str(ctx_code),
                account_id=account_id,
                symbol=symbol,
                action=action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta=ctx_meta or {},
            )
            self._maybe_publish_fallback_on_block(
                winner,
                proof,
                account_id=account_id,
                symbol=symbol,
                action=action,
                reason_code=str(ctx_code),
                reason_meta=ctx_meta or {},
            )
            return None

        # Trader feedback suppression gate (prevents repeated impossible order spam)
        fb_ok, fb_code, fb_meta = self._feedback_suppression_gate(account_id, symbol, action)
        if not fb_ok and fb_code:
            proof["dropped"] = True
            reason_code = str((fb_meta or {}).get("reason_code") or "UNKNOWN").upper().strip()
            proof["risk_reject_code"] = "ORCH_FEEDBACK_SUPPRESS_BLOCK"
            proof["risk_reject_meta"] = {**(fb_meta or {}), "suppress_reason_code": reason_code, "suppress_code": str(fb_code)}
            logger.warning(
                "ORCH_FEEDBACK_SUPPRESS_BLOCK | account=%s | symbol=%s | action=%s | code=%s | meta=%s",
                account_id,
                symbol,
                action,
                fb_code,
                fb_meta,
            )
            self._publish_exec_event(
                code="ORCH_FEEDBACK_SUPPRESS_BLOCK",
                account_id=account_id,
                symbol=symbol,
                action=action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta={**(fb_meta or {}), "reason_code": reason_code, "suppress_code": str(fb_code)},
            )
            self._maybe_publish_fallback_on_block(
                winner,
                proof,
                account_id=account_id,
                symbol=symbol,
                action=action,
                reason_code="ORCH_FEEDBACK_SUPPRESS_BLOCK",
                reason_meta={**(fb_meta or {}), "reason_code": reason_code, "suppress_code": str(fb_code)},
            )
            return None

        # Pre-publish feasibility gate: block impossible risk-add orders before stream publish.
        feasible, feas_code, feas_meta = self._prepublish_feasibility_gate(
            winner,
            proof,
            account_id=account_id,
            symbol=symbol,
            action=action,
        )
        if not feasible and feas_code:
            proof["dropped"] = True
            proof["risk_reject_code"] = str(feas_code)
            proof["risk_reject_meta"] = feas_meta or {}
            logger.warning(
                "ORCH_IMPOSSIBLE_TRADE_BLOCK | account=%s | symbol=%s | action=%s | code=%s | meta=%s",
                account_id,
                symbol,
                action,
                feas_code,
                feas_meta,
            )
            self._publish_exec_event(
                code=str(feas_code),
                account_id=account_id,
                symbol=symbol,
                action=action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta=feas_meta or {},
            )
            self._maybe_publish_fallback_on_block(
                winner,
                proof,
                account_id=account_id,
                symbol=symbol,
                action=action,
                reason_code=str(feas_code),
                reason_meta=feas_meta or {},
            )
            return None

        # Kill switch: block risk-add signals during HALT (reduce-only still allowed)
        halted, halt_info = self._kill_switch_active(account_id, symbol)
        def _halt02_allows_hedge() -> bool:
            try:
                reason = (halt_info or {}).get("reason") or (halt_info or {}).get("code") or ""
                if str(reason).upper() != "HALT-02":
                    return False
                if "HEDGE" not in action:
                    return False
                desired_side = "LONG" if "LONG" in action else "SHORT" if "SHORT" in action else ""
                if not desired_side or not self.redis:
                    return False
                raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
                if not raw_live:
                    return False
                def _get(v):
                    return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                side = str(_get(raw_live.get(b"side") or raw_live.get("side") or "")).upper()
                if not side:
                    try:
                        amt = float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0))
                    except Exception:
                        amt = 0.0
                    side = "LONG" if amt > 0 else "SHORT" if amt < 0 else "FLAT"
                if side == "LONG" and desired_side == "SHORT":
                    return True
                if side == "SHORT" and desired_side == "LONG":
                    return True
            except Exception:
                return False
            return False
        def _halt03_allows_protective_hedge() -> bool:
            """HALT-03 (exec_fail_storm) must not block protective hedges.

            Allow only when the hedge is clearly opposite an existing live position.
            """
            try:
                reason = (halt_info or {}).get("reason") or (halt_info or {}).get("code") or ""
                if str(reason).upper() != "HALT-03":
                    return False
                if "HEDGE" not in action:
                    return False
                desired_side = "LONG" if "LONG" in action else "SHORT" if "SHORT" in action else ""
                if not desired_side or not self.redis:
                    return False
                raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
                if not raw_live:
                    return False
                def _get(v):
                    return v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                side = str(_get(raw_live.get(b"side") or raw_live.get("side") or "")).upper()
                if not side:
                    try:
                        amt = float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0))
                    except Exception:
                        amt = 0.0
                    side = "LONG" if amt > 0 else "SHORT" if amt < 0 else "FLAT"
                if side == "LONG" and desired_side == "SHORT":
                    return True
                if side == "SHORT" and desired_side == "LONG":
                    return True
            except Exception:
                return False
            return False
        try:
            from config import PROTECTIVE_BYPASS_KILL_SWITCH
        except Exception:
            PROTECTIVE_BYPASS_KILL_SWITCH = True

        def _is_protective_bypass_candidate() -> bool:
            act_u = str(action or "").upper().strip()
            cat_u = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
            src_u = str(winner.get("source") or winner.get("source_module") or "").upper().strip()
            if act_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")):
                return True
            if cat_u in {"PROTECTIVE", "RECOVERY", "HEDGE"} and "HEDGE" in act_u:
                return True
            if ("PROTECT" in src_u or "URC" in src_u) and "HEDGE" in act_u:
                return True
            return False

        if halted and self._is_risk_add_action(action) and kill_switch_blocks(
            halt_info,
            account=account_id,
            symbol=symbol,
        ):
            proof["kill_switch_active"] = True
            proof["kill_switch_reason"] = (halt_info or {}).get("reason") or (halt_info or {}).get("code") or "KILL_SWITCH_ACTIVE"
            halt_code = str(proof.get("kill_switch_reason") or "").upper().strip()
            if bool(PROTECTIVE_BYPASS_KILL_SWITCH) and _is_protective_bypass_candidate() and halt_code in {"HALT-02", "HALT-03"}:
                # ── Governor gate: protective hedge kill-switch bypass ──
                _ks_gov_blocked = False
                try:
                    from risk.margin_governor import MarginGovernor
                    _ks_gov = MarginGovernor(self.redis)
                    _ks_verdict = _ks_gov.evaluate(
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposed_margin_usd=float(winner.get("margin_usd") or 0.0),
                        source="orch_kill_switch_bypass",
                        is_protective=True,
                    )
                    proof["governor_verdict"] = _ks_verdict.action
                    proof["governor_code"] = _ks_verdict.code
                    if not _ks_verdict.allowed:
                        _ks_gov_blocked = True
                        proof["dropped"] = True
                        proof["risk_reject_code"] = _ks_verdict.code
                        logger.warning(
                            "MARGIN_GOVERNOR_OVERRIDE_KS_BYPASS | account=%s | symbol=%s | action=%s | "
                            "verdict=%s | code=%s | reason=%s",
                            account_id, symbol, action,
                            _ks_verdict.action, _ks_verdict.code, _ks_verdict.reason,
                        )
                        self._publish_exec_event(
                            code=_ks_verdict.code,
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta=_ks_verdict.meta,
                        )
                        return None
                except Exception as _ks_gov_err:
                    logger.debug("MARGIN_GOVERNOR_ERR_FAILOPEN | ks_bypass | err=%s", _ks_gov_err)
                # ── End governor gate ──

                logger.warning(
                    "PROTECTIVE_BYPASS_KILL_SWITCH | account=%s | symbol=%s | action=%s | reason=%s",
                    account_id,
                    symbol,
                    action,
                    halt_code,
                )
                proof["risk_allow_code"] = "PROTECTIVE_BYPASS_KILL_SWITCH"
            elif _halt02_allows_hedge() or _halt03_allows_protective_hedge():
                logger.warning(
                    "KILL_SWITCH_ALLOW_PROTECTIVE | account=%s | symbol=%s | action=%s | reason=%s",
                    account_id,
                    symbol,
                    action,
                    proof["kill_switch_reason"],
                )
            else:
                proof["dropped"] = True
                logger.warning(
                    "KILL_SWITCH_CONTEXT | account=%s | symbol=%s | action=%s | reason=%s | details=%s",
                    account_id,
                    symbol,
                    action,
                    proof["kill_switch_reason"],
                    (halt_info or {}).get("details") or (halt_info or {}).get("fields") or {},
                )
                logger.warning(
                    f"🛑 [KILL_SWITCH] Blocked publish: {account_id}:{symbol} {action} reason={proof['kill_switch_reason']}"
                )
                logger.warning(
                    f"KILL_SWITCH_BLOCK | account={account_id} | symbol={symbol} | action={action} | reason={proof['kill_switch_reason']}"
                )
                try:
                    publish_ensemble_diagnostic(
                        {
                            "kind": "orch_blocked_killswitch",
                            "decision_id": str(winner.get("decision_id") or winner.get("proposal_id") or winner.get("trace_id") or ""),
                            "symbol": symbol,
                            "tf": str(winner.get("timeframe") or winner.get("tf") or ""),
                            "action": action,
                            "requested_account": str(winner.get("requested_account_id") or account_id),
                            "selected_account": account_id,
                            "reason": str(proof.get("kill_switch_reason") or "KILL_SWITCH_ACTIVE"),
                            "reason_details": (halt_info or {}).get("details") or (halt_info or {}).get("fields") or {},
                        }
                    )
                except Exception:
                    pass
                self._publish_exec_event(
                    code="KILL_SWITCH_ACTIVE",
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta={"reason": proof["kill_switch_reason"], "details": (halt_info or {}).get("details") or {}},
                )
                return None

        # Risk assertions pre-filter (single source)
        if not is_canary:
            portfolio = build_portfolio_snapshot(self.redis, account_id)

            # ── Staleness gate: reject OPEN_RISK on stale portfolio data ──
            try:
                _snap_ts_ms = int(portfolio.get("updated_ts_ms") or 0)
                _snap_age_s = (time.time() * 1000 - _snap_ts_ms) / 1000.0 if _snap_ts_ms > 0 else float("inf")
                proof["portfolio_age_s"] = round(_snap_age_s, 1)
                if self._is_risk_add_action(action) and _snap_age_s > PORTFOLIO_STALE_THRESHOLD_S:
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "ORCH_PORTFOLIO_STALE"
                    logger.warning(
                        "ORCH_PORTFOLIO_STALE | account=%s | symbol=%s | action=%s | age_s=%.1f | threshold_s=%d",
                        account_id, symbol, action, _snap_age_s, PORTFOLIO_STALE_THRESHOLD_S,
                    )
                    self._publish_exec_event(
                        code="ORCH_PORTFOLIO_STALE",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta={"age_s": round(_snap_age_s, 1), "threshold_s": PORTFOLIO_STALE_THRESHOLD_S,
                              "updated_ts_ms": _snap_ts_ms},
                    )
                    return None
            except Exception:
                pass  # Fail-open: skip staleness check on import/parse error

            portfolio["margin_util"] = float(winner.get("margin_util") or portfolio.get("margin_util") or 0.0)
            portfolio["free_margin_ratio"] = float(winner.get("free_margin_ratio") or portfolio.get("free_margin_ratio") or 0.0)
            portfolio["portfolio_mode"] = winner.get("portfolio_mode") or portfolio.get("portfolio_mode")
            phase = resolve_phase(float(portfolio.get("equity") or 0.0), get_ramp_phase(self.redis))
            phase = self._apply_ramp_budget_scaling(phase, portfolio, account_id, proof)

            metrics = self._get_portfolio_metrics(account_id, portfolio)
            tier = self._resolve_portfolio_tier(metrics)
            phase = self._apply_portfolio_tier_caps(phase, tier, proof)
            proof["portfolio_metrics"] = metrics

            # Operator policy gates (trainer/orchestrator intelligence layer)
            op_allow, op_block_code, op_meta = self._apply_operator_policy_gates(
                winner,
                proof,
                account_id=account_id,
                symbol=symbol,
                action=action,
                portfolio=portfolio,
            )
            if op_meta:
                proof["operator_policy"] = op_meta
                meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                meta_blob["operator_policy"] = op_meta
                winner["metadata"] = meta_blob
                winner["operator_policy"] = op_meta
            if not op_allow and op_block_code:
                proof["dropped"] = True
                proof["risk_reject_code"] = str(op_block_code)
                proof["risk_reject_meta"] = op_meta or {}
                logger.warning(
                    "ORCH_OPERATOR_POLICY_BLOCK | account=%s | symbol=%s | action=%s | code=%s | meta=%s",
                    account_id,
                    symbol,
                    action,
                    op_block_code,
                    op_meta,
                )
                self._publish_exec_event(
                    code=str(op_block_code),
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta=op_meta or {},
                )
                return None

            # ── Trainer alignment gate: ensure entry direction matches trainer view ──
            # TF-disagg hedges are inherently trainer-derived minority signals — exempt.
            try:
                from risk.trainer_alignment import check_alignment, enrich_proposal_with_trainer
                if self._is_risk_add_action(action) and not bool(winner.get("tf_hedge_disagg")):
                    _ta_price = self._safe_float(
                        self._extract_with_meta(winner, ["current_price", "price", "mark_price"])
                    )
                    _ta_ok, _ta_reason, _ta_view = check_alignment(
                        self.redis, symbol, action,
                        current_price=_ta_price or 0.0,
                        source_module="orchestrator",
                    )
                    if _ta_view:
                        proof["trainer_alignment"] = {
                            "direction": _ta_view.consensus_direction,
                            "confidence": round(_ta_view.consensus_confidence, 4),
                            "target_price": _ta_view.best_target_price,
                            "move_regime": _ta_view.move_regime,
                            "bias_dir": _ta_view.bias_dir,
                            "aligned": _ta_ok,
                            "reason": _ta_reason,
                        }
                        enrich_proposal_with_trainer(self.redis, winner)
                    if not _ta_ok:
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "ORCH_TRAINER_DIRECTION_CONFLICT"
                        proof["risk_reject_meta"] = proof.get("trainer_alignment") or {}
                        logger.warning(
                            "ORCH_TRAINER_DIRECTION_CONFLICT | account=%s | symbol=%s | action=%s | "
                            "trainer_dir=%s trainer_conf=%.3f | reason=%s",
                            account_id, symbol, action,
                            (_ta_view.consensus_direction if _ta_view else "?"),
                            (_ta_view.consensus_confidence if _ta_view else 0),
                            _ta_reason,
                        )
                        self._publish_exec_event(
                            code="ORCH_TRAINER_DIRECTION_CONFLICT",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or ""),
                            meta=proof.get("trainer_alignment") or {},
                        )
                        return None
                else:
                    enrich_proposal_with_trainer(self.redis, winner)
            except ImportError:
                pass
            except Exception as _ta_err:
                logger.debug("ORCH_TRAINER_ALIGN_ERR | %s", _ta_err)

            dq_score, dq_meta = self._calc_dq_score(winner)
            self._update_dq_stats(account_id, dq_score)
            meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
            meta_blob.update(dq_meta)
            winner.update(dq_meta)
            winner["metadata"] = meta_blob
            proof["dq_score"] = dq_score

            # Hedge-add gates: freshness, anti-chase, laddering
            try:
                if self._is_hedge_add_action(winner, action):
                    try:
                        from config import (
                            HEDGE_ADD_FRESHNESS_MAX_AGE_MS,
                            HEDGE_ADD_ANTI_CHASE_BPS,
                            HEDGE_ADD_ANTI_CHASE_PERSIST_N,
                            HEDGE_ADD_LADDER_STEP_USD,
                            HEDGE_ADD_LADDER_STEP_EQUITY_PCT,
                            HEDGE_ADD_LADDER_COOLDOWN_SEC,
                            HEDGE_ADD_LADDER_MIN_MOVE_BPS,
                            PROTECTIVE_BYPASS_STALE_FEATURES,
                        )
                    except Exception:
                        HEDGE_ADD_FRESHNESS_MAX_AGE_MS = 20000
                        HEDGE_ADD_ANTI_CHASE_BPS = 25.0
                        HEDGE_ADD_ANTI_CHASE_PERSIST_N = 3
                        HEDGE_ADD_LADDER_STEP_USD = 75.0
                        HEDGE_ADD_LADDER_STEP_EQUITY_PCT = 0.015
                        HEDGE_ADD_LADDER_COOLDOWN_SEC = 30
                        HEDGE_ADD_LADDER_MIN_MOVE_BPS = 20.0
                        PROTECTIVE_BYPASS_STALE_FEATURES = True

                    now_ms = int(time.time() * 1000)
                    meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                    feat_ts = self._safe_float(winner.get("features_ts_ms") or meta_blob.get("features_ts_ms"))
                    if not feat_ts:
                        ts_candidates = []
                        for key in ("orderbook_ts_ms", "volatility_ts_ms", "liqmap_ts_ms"):
                            ts_val = self._safe_float(winner.get(key) or meta_blob.get(key))
                            if ts_val:
                                ts_candidates.append(int(ts_val))
                        if ts_candidates:
                            feat_ts = min(ts_candidates)
                    feat_age = None
                    if feat_ts:
                        feat_ts = int(feat_ts)
                        feat_age = int(now_ms - feat_ts)
                        winner.setdefault("features_ts_ms", feat_ts)
                        winner.setdefault("features_age_ms", feat_age)
                        meta_blob.setdefault("features_ts_ms", feat_ts)
                        meta_blob.setdefault("features_age_ms", feat_age)
                        winner["metadata"] = meta_blob

                    price_val, price_ref = self._get_price_ref(symbol, winner)
                    if price_val is not None:
                        winner.setdefault("price_ref_value", float(price_val))
                        winner.setdefault("price_ref", price_ref)
                        meta_blob.setdefault("price_ref_value", float(price_val))
                        meta_blob.setdefault("price_ref", price_ref)
                        winner["metadata"] = meta_blob

                    stress_state = str(portfolio.get("portfolio_mode") or winner.get("portfolio_mode") or "UNKNOWN").upper()
                    mu_util = float(portfolio.get("margin_util") or 0.0)
                    free_ratio = float(portfolio.get("free_margin_ratio") or 0.0)
                    equity = float(portfolio.get("equity") or 0.0)
                    headroom = max(0.0, (1.0 - mu_util) * equity) if equity > 0 else 0.0
                    signal_id = str(winner.get("signal_id") or winner.get("proposal_id") or winner.get("id") or "")
                    dq_fallback = bool(winner.get("dq_fallback_used") or meta_blob.get("dq_fallback_used"))

                    if feat_age is not None and float(HEDGE_ADD_FRESHNESS_MAX_AGE_MS or 0) > 0:
                        if float(feat_age) > float(HEDGE_ADD_FRESHNESS_MAX_AGE_MS):
                            action_category = str(winner.get("action_category") or winner.get("category") or "").upper()
                            source_key = str(winner.get("source_module") or winner.get("source") or "").upper()
                            pds_val = self._safe_float(winner.get("pds") or winner.get("protection_demand_score") or 0.0)
                            # Treat STOP_LOSS-derived stealth hedges as protective even when features are stale.
                            # These are safety actions and must not be suppressed by stale feature freshness gates.
                            _mc = winner.get("market_context") if isinstance(winner.get("market_context"), dict) else {}
                            _stop_type = str(_mc.get("stop_type") or "").upper().strip() if isinstance(_mc, dict) else ""
                            _is_stealth_stoploss_hedge = (
                                ("STEALTH" in source_key)
                                and ("HEDGE" in action)
                                and (_stop_type == "STOP_LOSS")
                            )
                            is_protective_hedge = (
                                "HEDGE" in action
                                and (
                                    action_category in ("PROTECTIVE", "RECOVERY")
                                    or ("PROTECT" in source_key or "URC" in source_key)
                                    or (pds_val is not None and float(pds_val) >= self._dynamic_threshold(symbol, 0.50, 0.75))
                                    or _is_stealth_stoploss_hedge
                                )
                            )
                            _tf_disagg_bypass = bool(winner.get("tf_hedge_disagg"))
                            if (is_protective_hedge and bool(PROTECTIVE_BYPASS_STALE_FEATURES)) or _tf_disagg_bypass:
                                # ── MARGIN GOVERNOR GATE (I1-I4) ──────────────
                                # Protective hedges are NOT exempt from margin caps.
                                # Governor overrides the stale-features bypass.
                                _gov_blocked = False
                                try:
                                    from risk.margin_governor import MarginGovernor
                                    _gov = MarginGovernor(self.redis)
                                    _proposed_margin = float(winner.get("margin_usd") or step_cap or 0.0)
                                    _gov_verdict = _gov.evaluate(
                                        account_id=account_id,
                                        symbol=symbol,
                                        action=action,
                                        proposed_margin_usd=_proposed_margin,
                                        margin_used_pct=mu_util * 100.0 if mu_util < 1.0 else mu_util,
                                        source="orch_protective_bypass",
                                        is_protective=True,
                                    )
                                    proof["governor_verdict"] = _gov_verdict.action
                                    proof["governor_code"] = _gov_verdict.code
                                    if not _gov_verdict.allowed:
                                        _gov_blocked = True

                                        # ── Protective conversion: DELEVERAGE → convert ADD to REDUCE ──
                                        _gov_convert_enabled = bool(getattr(config, "GOV_PROTECTIVE_CONVERSION_ENABLED", True))
                                        if (_gov_verdict.action == "DELEVERAGE"
                                            and _gov_verdict.suggested_action
                                            and _gov_convert_enabled):
                                            # Convert the hedge-add to a partial close
                                            _orig_action = action
                                            _conv_action = _gov_verdict.suggested_action
                                            winner["action"] = _conv_action
                                            winner["action_name"] = _conv_action
                                            winner["action_type"] = "close"
                                            winner["action_category"] = "PROTECTIVE_DELEVERAGE"
                                            winner["risk_intent"] = "GOVERNOR_DELEVERAGE"
                                            winner["margin_usd"] = 0.0  # closes don't need margin
                                            winner["notional_usd"] = 0.0
                                            meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                                            meta_blob["governor_converted"] = True
                                            meta_blob["governor_original_action"] = _orig_action
                                            meta_blob["governor_conv_action"] = _conv_action
                                            meta_blob["governor_reason"] = _gov_verdict.reason
                                            winner["metadata"] = meta_blob
                                            proof["governor_conversion"] = {
                                                "original": _orig_action,
                                                "converted_to": _conv_action,
                                                "verdict": _gov_verdict.action,
                                                "code": _gov_verdict.code,
                                            }
                                            logger.warning(
                                                "MARGIN_GOVERNOR_CONVERT_PROTECTIVE | account=%s | symbol=%s | "
                                                "%s → %s | code=%s | MU=%.1f%% | reason=%s",
                                                account_id, symbol, _orig_action, _conv_action,
                                                _gov_verdict.code,
                                                mu_util * 100.0 if mu_util < 1.0 else mu_util,
                                                _gov_verdict.reason,
                                            )
                                            self._publish_exec_event(
                                                code="GOV_PROTECTIVE_CONVERSION",
                                                account_id=account_id,
                                                symbol=symbol,
                                                action=_conv_action,
                                                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                                meta=proof.get("governor_conversion") or {},
                                            )
                                            # DON'T return None — let the converted signal flow through
                                            _gov_blocked = False
                                        else:
                                            proof["dropped"] = True
                                            proof["risk_reject_code"] = _gov_verdict.code
                                            proof["risk_reject_meta"] = _gov_verdict.meta
                                            logger.warning(
                                                "MARGIN_GOVERNOR_OVERRIDE_PROTECTIVE | account=%s | symbol=%s | "
                                                "action=%s | verdict=%s | code=%s | MU=%.1f%% | "
                                                "proposed=$%.2f | reason=%s",
                                                account_id, symbol, action,
                                                _gov_verdict.action, _gov_verdict.code,
                                                mu_util * 100.0 if mu_util < 1.0 else mu_util,
                                                _proposed_margin, _gov_verdict.reason,
                                            )
                                            self._publish_exec_event(
                                                code=_gov_verdict.code,
                                                account_id=account_id,
                                                symbol=symbol,
                                                action=action,
                                                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                                meta=_gov_verdict.meta,
                                            )
                                            return None
                                except Exception as _gov_err:
                                    logger.debug(
                                        "MARGIN_GOVERNOR_ERR_FAILOPEN | account=%s | err=%s",
                                        account_id, _gov_err,
                                    )
                                # ── End governor gate ─────────────────────────

                                proof["risk_allow_code"] = "HEDGE_ADD_ALLOW_STALE_PROTECTIVE"
                                proof["risk_allow_meta"] = {
                                    "features_ts_ms": feat_ts,
                                    "features_age_ms": feat_age,
                                    "dq_fallback_used": dq_fallback,
                                }
                                winner["exec_profile"] = "SAFE_HEDGE"
                                winner.setdefault("execution_mode", "SAFE_HEDGE")
                                meta_blob.setdefault("exec_profile", "SAFE_HEDGE")
                                meta_blob.setdefault("execution_mode", "SAFE_HEDGE")
                                winner["metadata"] = meta_blob
                                logger.warning(
                                    "PROTECTIVE_BYPASS_STALE_FEATURES | account=%s | symbol=%s | action=%s | signal_id=%s",
                                    account_id,
                                    symbol,
                                    action,
                                    signal_id,
                                )
                                logger.warning(
                                    "HEDGE_ADD_ALLOW_STALE_PROTECTIVE | account=%s | symbol=%s | action=%s | signal_id=%s | "
                                    "price_ref=%s | features_ts_ms=%s | features_age_ms=%s | dq_fallback=%s | stress_state=%s | "
                                    "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f",
                                    account_id,
                                    symbol,
                                    action,
                                    signal_id,
                                    price_ref,
                                    feat_ts,
                                    feat_age,
                                    int(dq_fallback),
                                    stress_state,
                                    mu_util,
                                    free_ratio,
                                    headroom,
                                )
                                self._publish_exec_event(
                                    code="PROTECTIVE_BYPASS_STALE_FEATURES",
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                    meta=proof.get("risk_allow_meta") or {},
                                )
                                self._publish_exec_event(
                                    code="HEDGE_ADD_ALLOW_STALE_PROTECTIVE",
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                    meta=proof.get("risk_allow_meta") or {},
                                )
                            else:
                                proof["dropped"] = True
                                proof["risk_reject_code"] = "HEDGE_ADD_BLOCK_STALE_FEATURES"
                                proof["risk_reject_meta"] = {
                                    "features_ts_ms": feat_ts,
                                    "features_age_ms": feat_age,
                                    "dq_fallback_used": dq_fallback,
                                }
                                logger.warning(
                                    "HEDGE_ADD_BLOCK_STALE_FEATURES | account=%s | symbol=%s | action=%s | signal_id=%s | "
                                    "price_ref=%s | features_ts_ms=%s | features_age_ms=%s | dq_fallback=%s | stress_state=%s | "
                                    "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f",
                                    account_id,
                                    symbol,
                                    action,
                                    signal_id,
                                    price_ref,
                                    feat_ts,
                                    feat_age,
                                    int(dq_fallback),
                                    stress_state,
                                    mu_util,
                                    free_ratio,
                                    headroom,
                                )
                                self._publish_exec_event(
                                    code="HEDGE_ADD_BLOCK_STALE_FEATURES",
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                    meta=proof.get("risk_reject_meta") or {},
                                )
                                return None

                    side = str(winner.get("side") or winner.get("position_side") or "").upper().strip()
                    if not side:
                        if "SHORT" in action:
                            side = "SHORT"
                        elif "LONG" in action:
                            side = "LONG"

                    tf = winner.get("timeframe") or meta_blob.get("timeframe") or meta_blob.get("tf") or ""
                    tf = str(tf or "").strip()
                    tf_candidates = [tf] if tf else []
                    for fallback_tf in ("1m", "5m", "15m"):
                        if fallback_tf and fallback_tf not in tf_candidates:
                            tf_candidates.append(fallback_tf)

                    low, high, tf_used = self._get_recent_ohlc(symbol, tf_candidates)
                    if low is not None:
                        winner["anti_chase_low"] = float(low)
                    if high is not None:
                        winner["anti_chase_high"] = float(high)
                    if tf_used:
                        winner["anti_chase_tf"] = tf_used
                    _dyn_chase_bps = self._dynamic_value(symbol, 15.0, float(HEDGE_ADD_ANTI_CHASE_BPS or 25.0))
                    winner["anti_chase_bps"] = _dyn_chase_bps

                    near_extreme = False
                    bps = _dyn_chase_bps
                    if price_val is not None and bps > 0:
                        if side == "SHORT" and low is not None and low > 0:
                            near_extreme = float(price_val) <= float(low) * (1.0 + bps / 10000.0)
                        if side == "LONG" and high is not None and high > 0:
                            near_extreme = float(price_val) >= float(high) * (1.0 - bps / 10000.0)

                    if near_extreme:
                        persist_n = max(1, int(HEDGE_ADD_ANTI_CHASE_PERSIST_N or 1))
                        persist_ok = persist_n <= 1
                        if self.redis:
                            count_key = f"hedge:anti_chase:count:{account_id}:{symbol}:{side or 'NA'}"
                            try:
                                count = int(self.redis.get(count_key) or 0) + 1
                            except Exception:
                                count = 1
                            try:
                                self.redis.setex(count_key, 60, str(count))
                            except Exception:
                                pass
                            persist_ok = count >= persist_n
                        if not persist_ok:
                            proof["dropped"] = True
                            proof["risk_reject_code"] = "HEDGE_ADD_BLOCK_ANTI_CHASE"
                            proof["risk_reject_meta"] = {
                                "anti_chase_bps": bps,
                                "anti_chase_tf": tf_used,
                                "anti_chase_low": low,
                                "anti_chase_high": high,
                                "price_ref": price_ref,
                                "price_ref_value": price_val,
                            }
                            logger.warning(
                                "HEDGE_ADD_BLOCK_ANTI_CHASE | account=%s | symbol=%s | action=%s | signal_id=%s | "
                                "price_ref=%s | features_ts_ms=%s | features_age_ms=%s | dq_fallback=%s | stress_state=%s | "
                                "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f",
                                account_id,
                                symbol,
                                action,
                                signal_id,
                                price_ref,
                                feat_ts,
                                feat_age,
                                int(dq_fallback),
                                stress_state,
                                mu_util,
                                free_ratio,
                                headroom,
                            )
                            self._publish_exec_event(
                                code="HEDGE_ADD_BLOCK_ANTI_CHASE",
                                account_id=account_id,
                                symbol=symbol,
                                action=action,
                                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                meta=proof.get("risk_reject_meta") or {},
                            )
                            return None
                    else:
                        if self.redis and side:
                            try:
                                self.redis.delete(f"hedge:anti_chase:count:{account_id}:{symbol}:{side}")
                            except Exception:
                                pass

                    step_usd = self._dynamic_value(symbol, 50.0, float(HEDGE_ADD_LADDER_STEP_USD or 75.0))
                    step_pct = self._dynamic_value(symbol, 0.010, float(HEDGE_ADD_LADDER_STEP_EQUITY_PCT or 0.015))
                    step_caps = [v for v in (step_usd, equity * step_pct if equity > 0 and step_pct > 0 else 0.0) if v and v > 0]
                    step_cap = min(step_caps) if step_caps else 0.0

                    if step_cap > 0:
                        try:
                            cur_margin = float(winner.get("margin_usd") or 0.0)
                        except Exception:
                            cur_margin = 0.0
                        if cur_margin > step_cap:
                            try:
                                lev0 = float(winner.get("leverage") or 1.0)
                            except Exception:
                                lev0 = 1.0
                            if lev0 <= 0:
                                lev0 = 1.0
                            scale = step_cap / cur_margin if cur_margin > 0 else 0.0
                            prev_margin = cur_margin
                            winner["margin_usd"] = float(step_cap)
                            winner["notional_usd"] = float(winner.get("notional_usd") or 0.0) * float(scale) if winner.get("notional_usd") else float(step_cap) * float(lev0)
                            if equity > 0:
                                winner["position_size_pct"] = float(step_cap) / float(equity) * 100.0
                            winner["hedge_ladder_step_margin_usd"] = float(step_cap)
                            winner["hedge_ladder_scaled"] = True
                            proof["hedge_ladder_scaled"] = True
                            proof["hedge_ladder_step_margin_usd"] = float(step_cap)
                            logger.info(
                                "HEDGE_ADD_LADDER_STEP | account=%s | symbol=%s | action=%s | signal_id=%s | "
                                "price_ref=%s | features_ts_ms=%s | features_age_ms=%s | dq_fallback=%s | stress_state=%s | "
                                "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f | prev_margin=%.4f step_margin=%.4f",
                                account_id,
                                symbol,
                                action,
                                signal_id,
                                price_ref,
                                feat_ts,
                                feat_age,
                                int(dq_fallback),
                                stress_state,
                                mu_util,
                                free_ratio,
                                headroom,
                                prev_margin,
                                float(step_cap),
                            )

                        if self.redis and price_val is not None:
                            _dyn_ladder_cd = self._dynamic_value(symbol, 15.0, float(HEDGE_ADD_LADDER_COOLDOWN_SEC or 30.0))
                            cooldown_ms = int(_dyn_ladder_cd * 1000)
                            min_move_bps = self._dynamic_value(symbol, 10.0, float(HEDGE_ADD_LADDER_MIN_MOVE_BPS or 20.0))
                            last_key = f"hedge:ladder:last:{account_id}:{symbol}"
                            last_ts = 0
                            last_price = None
                            try:
                                raw = self.redis.get(last_key)
                                if raw:
                                    parsed = json.loads(raw)
                                    last_ts = int(parsed.get("ts_ms") or 0)
                                    last_price = float(parsed.get("price") or 0.0) if parsed.get("price") is not None else None
                            except Exception:
                                last_ts = 0
                                last_price = None
                            if cooldown_ms > 0 and last_ts > 0 and (now_ms - last_ts) < cooldown_ms and not bool(winner.get("tf_hedge_disagg")):
                                move_bps = None
                                if last_price and last_price > 0:
                                    move_bps = abs(float(price_val) - float(last_price)) / float(last_price) * 10000.0
                                if move_bps is None or move_bps < float(min_move_bps):
                                    proof["dropped"] = True
                                    proof["risk_reject_code"] = "HEDGE_ADD_LADDER_STEP"
                                    proof["risk_reject_meta"] = {
                                        "cooldown_ms": cooldown_ms,
                                        "last_ts_ms": last_ts,
                                        "last_price": last_price,
                                        "price_ref_value": price_val,
                                        "move_bps": move_bps,
                                    }
                                    logger.warning(
                                        "HEDGE_ADD_LADDER_STEP | account=%s | symbol=%s | action=%s | signal_id=%s | "
                                        "price_ref=%s | features_ts_ms=%s | features_age_ms=%s | dq_fallback=%s | stress_state=%s | "
                                        "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f | decision=block",
                                        account_id,
                                        symbol,
                                        action,
                                        signal_id,
                                        price_ref,
                                        feat_ts,
                                        feat_age,
                                        int(dq_fallback),
                                        stress_state,
                                        mu_util,
                                        free_ratio,
                                        headroom,
                                    )
                                    self._publish_exec_event(
                                        code="HEDGE_ADD_LADDER_STEP",
                                        account_id=account_id,
                                        symbol=symbol,
                                        action=action,
                                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                        meta=proof.get("risk_reject_meta") or {},
                                    )
                                    return None

                            try:
                                self.redis.setex(
                                    last_key,
                                    max(60, int(float(HEDGE_ADD_LADDER_COOLDOWN_SEC or 0) * 2)),
                                    json.dumps({"ts_ms": now_ms, "price": float(price_val), "action": action}, separators=(",", ":")),
                                )
                            except Exception:
                                pass
            except Exception:
                pass

            # DQ gating for risk-add opens
            try:
                from config import DQ_SCORE_BLOCK_BELOW, DQ_SCORE_DOWNSIZE_BELOW, DQ_MIN_TIER_MARGIN_USD
            except Exception:
                DQ_SCORE_BLOCK_BELOW = 0.5
                DQ_SCORE_DOWNSIZE_BELOW = 0.8
                DQ_MIN_TIER_MARGIN_USD = 25.0

            if self._is_risk_add_action(action) and str(winner.get("action_category") or winner.get("category") or "").upper() in {"OPEN_RISK", "OPEN", "ENTRY"}:
                if float(dq_score) < float(DQ_SCORE_BLOCK_BELOW):
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "DQ_SCORE_BLOCK"
                    proof["risk_reject_meta"] = {"dq_score": float(dq_score)}
                    logger.warning(
                        "ORCH_RISK_REJECT | reason=DQ_SCORE_BLOCK | account=%s | symbol=%s | action=%s | dq=%.3f",
                        account_id,
                        symbol,
                        action,
                        float(dq_score),
                    )
                    self._publish_exec_event(
                        code="DQ_SCORE_BLOCK",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta={"dq_score": float(dq_score)},
                    )
                    return None
                if float(dq_score) < float(DQ_SCORE_DOWNSIZE_BELOW):
                    winner["dq_downsized"] = True
                    winner["dq_cap_margin_usd"] = float(DQ_MIN_TIER_MARGIN_USD)
                    proof["dq_downsized"] = True
                    proof["dq_cap_margin_usd"] = float(DQ_MIN_TIER_MARGIN_USD)

            # Dynamic sizing after tier + DQ scoring
            self._apply_dynamic_sizing(winner, proof, portfolio=portfolio, tier=tier)

            # Recovery hedge downsizing (no-loss posture): fit within ramp/MU/free-margin caps
            try:
                action_category = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
                source_module = str(winner.get("source") or winner.get("source_module") or "").lower()
                is_hedge_action = self._is_hedge_action(action)
                is_recovery_src = ("hedge_manager_v3" in source_module) or ("hedge_mgr_v3" in source_module)
                is_recovery_hedge = bool(winner.get("hedge_intent")) or is_hedge_action or is_recovery_src
                if is_recovery_hedge and action_category in {"", "PROTECTIVE", "RECOVERY", "HEDGE"}:
                    winner["risk_intent"] = "RECOVERY_HEDGE"
                elif self._is_risk_add_action(action):
                    winner.setdefault("risk_intent", "ALPHA_ADD")

                meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                if winner.get("risk_intent") and isinstance(meta_blob, dict):
                    meta_blob["risk_intent"] = winner.get("risk_intent")
                    winner["metadata"] = meta_blob
            except Exception:
                pass

            try:
                if winner.get("risk_intent") == "RECOVERY_HEDGE" and self._is_risk_add_action(action):
                    try:
                        cur_margin = float(winner.get("margin_usd") or 0.0)
                    except Exception:
                        cur_margin = 0.0
                    try:
                        cur_notional = float(winner.get("notional_usd") or 0.0)
                    except Exception:
                        cur_notional = 0.0
                    try:
                        lev0 = float(winner.get("leverage") or 1.0)
                    except Exception:
                        lev0 = 1.0
                    if lev0 <= 0:
                        lev0 = 1.0

                    equity = float(portfolio.get("equity") or 0.0)
                    margin_util = float(portfolio.get("margin_util") or 0.0)
                    free_margin_ratio = float(portfolio.get("free_margin_ratio") or 0.0)
                    max_mu = float(phase.get("max_mu") or 0.0)
                    min_fmr = float(phase.get("min_free_margin_ratio") or 0.0)

                    caps = []
                    if equity > 0 and max_mu > 0:
                        caps.append(max(0.0, (float(max_mu) - float(margin_util)) * float(equity)))
                    if equity > 0 and min_fmr > 0:
                        caps.append(max(0.0, (float(free_margin_ratio) - float(min_fmr)) * float(equity)))

                    if caps:
                        cap_margin = float(min(caps))
                        if cap_margin <= 0.0:
                            proof["dropped"] = True
                            proof["risk_reject_code"] = "RECOVERY_HEDGE_NO_HEADROOM"
                            proof["risk_reject_meta"] = {
                                "reason": "recovery_hedge_no_headroom",
                                "max_mu": float(max_mu),
                                "margin_util": float(margin_util),
                                "min_free_margin_ratio": float(min_fmr),
                                "free_margin_ratio": float(free_margin_ratio),
                            }
                            logger.warning(
                                "ORCH_RISK_REJECT | reason=RECOVERY_HEDGE_NO_HEADROOM | account=%s | symbol=%s | action=%s",
                                account_id,
                                symbol,
                                action,
                            )
                            self._publish_exec_event(
                                code="RECOVERY_HEDGE_NO_HEADROOM",
                                account_id=account_id,
                                symbol=symbol,
                                action=action,
                                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                meta=proof.get("risk_reject_meta") or {},
                            )
                            return None

                        if cap_margin < cur_margin and cur_margin > 0:
                            scale = cap_margin / cur_margin if cur_margin > 0 else 0.0
                            winner["margin_usd"] = float(cap_margin)
                            if cur_notional > 0:
                                winner["notional_usd"] = float(cur_notional) * float(scale)
                            else:
                                winner["notional_usd"] = float(cap_margin) * float(lev0)
                            if equity > 0:
                                winner["position_size_pct"] = float(cap_margin) / float(equity) * 100.0
                            winner["recovery_hedge_downsized"] = True
                            winner["recovery_cap_margin_usd"] = float(cap_margin)
                            proof["recovery_hedge_downsized"] = True
                            proof["recovery_cap_margin_usd"] = float(cap_margin)

                            # Ensure downsized recovery hedge still meets min notional
                            try:
                                from config import MIN_NOTIONAL_USD, BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL
                            except Exception:
                                MIN_NOTIONAL_USD = 5.0
                                BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL = {}
                            try:
                                sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD)
                            except Exception:
                                sym_min = float(MIN_NOTIONAL_USD or 5.0)
                            effective_min_notional = max(float(MIN_NOTIONAL_USD or 5.0), float(sym_min or 0.0))
                            try:
                                post_notional = float(winner.get("notional_usd") or 0.0)
                            except Exception:
                                post_notional = 0.0
                            if post_notional > 0 and post_notional < effective_min_notional:
                                proof["dropped"] = True
                                proof["risk_reject_code"] = "RECOVERY_HEDGE_TOO_SMALL"
                                proof["risk_reject_meta"] = {
                                    "reason": "recovery_hedge_below_min_notional",
                                    "notional_usd": float(post_notional),
                                    "min_notional_usd": float(effective_min_notional),
                                }
                                logger.warning(
                                    "ORCH_RISK_REJECT | reason=RECOVERY_HEDGE_TOO_SMALL | account=%s | symbol=%s | action=%s | notional=%.4f min_notional=%.4f",
                                    account_id,
                                    symbol,
                                    action,
                                    float(post_notional),
                                    float(effective_min_notional),
                                )
                                self._publish_exec_event(
                                    code="RECOVERY_HEDGE_TOO_SMALL",
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                    meta=proof.get("risk_reject_meta") or {},
                                )
                                return None
            except Exception:
                pass

            if winner.get("dq_downsized") and winner.get("dq_cap_margin_usd"):
                try:
                    cap = float(winner.get("dq_cap_margin_usd") or 0.0)
                except Exception:
                    cap = 0.0
                if cap > 0:
                    try:
                        cur_margin = float(winner.get("margin_usd") or 0.0)
                    except Exception:
                        cur_margin = 0.0
                    if cur_margin > cap:
                        winner["dq_prev_margin_usd"] = cur_margin
                        winner["margin_usd"] = cap
                        try:
                            lev0 = float(winner.get("leverage") or 1.0)
                        except Exception:
                            lev0 = 1.0
                        if lev0 <= 0:
                            lev0 = 1.0
                        winner["notional_usd"] = float(cap) * float(lev0)
                        proof["dq_downsized"] = True
                        proof["dq_prev_margin_usd"] = cur_margin
                        proof["dq_cap_margin_usd"] = cap

            # Ramp phase limits (PR-12)
            _act_u_ramp = str(action or "").upper()
            _is_flip_ramp = ("CLOSE" in _act_u_ramp and "OPEN" in _act_u_ramp) or "FLIP" in _act_u_ramp
            if self._is_risk_add_action(action) and not _is_flip_ramp:
                ramp_check = check_ramp_limits(phase, portfolio, winner)
                if not ramp_check.get("ok"):
                    try:
                        from config import RAMP_LIMIT_DOWNSIZE_ENABLED
                    except Exception:
                        RAMP_LIMIT_DOWNSIZE_ENABLED = False

                    meta = ramp_check.get("meta") or {}
                    if RAMP_LIMIT_DOWNSIZE_ENABLED and meta.get("limit") == "per_symbol_margin":
                        try:
                            cap = float(meta.get("cap") or 0.0)
                        except Exception:
                            cap = 0.0
                        try:
                            cur_margin = float(winner.get("margin_usd") or 0.0)
                        except Exception:
                            cur_margin = 0.0

                        if cap > 0 and cur_margin > cap:
                            winner["ramp_limit_downsized"] = True
                            winner["ramp_limit_prev_margin_usd"] = cur_margin
                            winner["ramp_limit_cap_margin_usd"] = cap
                            winner["margin_usd"] = cap
                            try:
                                lev0 = float(winner.get("leverage") or 1.0)
                            except Exception:
                                lev0 = 1.0
                            if lev0 <= 0:
                                lev0 = 1.0
                            winner["notional_usd"] = float(cap) * float(lev0)
                            try:
                                eq = float(portfolio.get("equity") or 0.0)
                                if eq > 0:
                                    winner["position_size_pct"] = float(cap) / float(eq) * 100.0
                            except Exception:
                                pass
                            proof["ramp_limit_downsized"] = True
                            proof["ramp_limit_prev_margin_usd"] = cur_margin
                            proof["ramp_limit_cap_margin_usd"] = cap
                            proof["risk_reject_meta"] = meta
                        else:
                            reject_code = "ORCH_RAMP_CAP_BLOCK" if str(meta.get("limit") or "").lower() == "max_positions" else "RAMP_LIMIT"
                            proof["dropped"] = True
                            proof["risk_reject_code"] = reject_code
                            proof["risk_reject_meta"] = meta
                            logger.warning(
                                f"ORCH_RISK_REJECT | reason={reject_code} | account={account_id} | symbol={symbol} | action={action} | "
                                f"limit={meta}")
                            self._publish_exec_event(
                                code=reject_code,
                                account_id=account_id,
                                symbol=symbol,
                                action=action,
                                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                meta=meta,
                            )
                            if reject_code == "ORCH_RAMP_CAP_BLOCK":
                                self._maybe_publish_fallback_on_block(
                                    winner,
                                    proof,
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    reason_code=reject_code,
                                    reason_meta=meta,
                                )
                            return None
                    else:
                        action_cat = str(winner.get("action_category") or winner.get("category") or "").upper()
                        if meta.get("limit") == "max_positions" and action_cat in {"OPEN_RISK", "OPEN", "ENTRY"}:
                            if self._attempt_rotation(account_id, winner, meta):
                                proof["rotation_triggered"] = True
                                proof["dropped"] = True
                                proof["risk_reject_code"] = "RAMP_LIMIT_ROTATION"
                                self._publish_exec_event(
                                    code="RAMP_LIMIT_ROTATION",
                                    account_id=account_id,
                                    symbol=symbol,
                                    action=action,
                                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                                    meta={"limit": meta, "rotation": True},
                                )
                                return None
                        reject_code = "ORCH_RAMP_CAP_BLOCK" if str(meta.get("limit") or "").lower() == "max_positions" else "RAMP_LIMIT"
                        proof["dropped"] = True
                        proof["risk_reject_code"] = reject_code
                        proof["risk_reject_meta"] = meta
                        logger.warning(
                            f"ORCH_RISK_REJECT | reason={reject_code} | account={account_id} | symbol={symbol} | action={action} | "
                            f"limit={meta}")
                        self._publish_exec_event(
                            code=reject_code,
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta=meta,
                        )
                        if reject_code == "ORCH_RAMP_CAP_BLOCK":
                            self._maybe_publish_fallback_on_block(
                                winner,
                                proof,
                                account_id=account_id,
                                symbol=symbol,
                                action=action,
                                reason_code=reject_code,
                                reason_meta=meta,
                            )
                        return None
            # Data-quality policy for missing liquidation distance
            dq_downsized = False
            dq_prev_margin = None
            dq_meta: Dict[str, Any] = {}
            if isinstance(meta_blob.get("dq_missing_fields"), list):
                dq_meta["dq_missing_fields"] = list(meta_blob.get("dq_missing_fields"))
            if isinstance(winner.get("dq_missing_fields"), list):
                dq_meta["dq_missing_fields"] = list(dict.fromkeys(dq_meta.get("dq_missing_fields", []) + list(winner.get("dq_missing_fields"))))
            if winner.get("dq_confidence") is not None:
                dq_meta["dq_confidence"] = winner.get("dq_confidence")
            if meta_blob.get("dq_confidence") is not None:
                dq_meta["dq_confidence"] = meta_blob.get("dq_confidence")
            if winner.get("dq_fallback_used") is not None:
                dq_meta["dq_fallback_used"] = winner.get("dq_fallback_used")
            if meta_blob.get("dq_fallback_used") is not None:
                dq_meta["dq_fallback_used"] = meta_blob.get("dq_fallback_used")
            if winner.get("dq_source_ok") is not None:
                dq_meta["dq_source_ok"] = winner.get("dq_source_ok")
            if meta_blob.get("dq_source_ok") is not None:
                dq_meta["dq_source_ok"] = meta_blob.get("dq_source_ok")

            liq_val = self._extract_liq_distance_pct(winner)
            if liq_val is None:
                try:
                    from config import (
                        DQ_LIQ_FALLBACK_ENABLED,
                        DQ_LIQ_FALLBACK_MAX_AGE_MS,
                        DQ_LIQ_FALLBACK_NON_MAJOR_DOWNSIZE_PCT,
                        DQ_LIQ_FALLBACK_CONFIDENCE,
                    )
                except Exception:
                    DQ_LIQ_FALLBACK_ENABLED = True
                    DQ_LIQ_FALLBACK_MAX_AGE_MS = 60000
                    DQ_LIQ_FALLBACK_NON_MAJOR_DOWNSIZE_PCT = 0.2
                    DQ_LIQ_FALLBACK_CONFIDENCE = 0.3
                dq_meta.setdefault("dq_fallback_used", False)
                dq_meta.setdefault("dq_missing_fields", ["liq_distance_pct"])
                dq_meta.setdefault("dq_confidence", float(DQ_LIQ_FALLBACK_CONFIDENCE))

                if not DQ_LIQ_FALLBACK_ENABLED:
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "DQ_MISSING_LIQ"
                    proof["risk_reject_meta"] = {"reason": "dq_fallback_disabled"}
                    logger.warning(
                        f"ORCH_RISK_REJECT | reason=DQ_MISSING_LIQ | account={account_id} | symbol={symbol} | action={action} | disabled=1"
                    )
                    self._publish_exec_event(
                        code="DQ_MISSING_LIQ",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta={"reason": "dq_fallback_disabled"},
                    )
                    return None

                now_ms = int(time.time() * 1000)
                ob_ts = winner.get("orderbook_ts_ms")
                lm_ts = winner.get("liqmap_ts_ms")
                try:
                    ob_ts = int(ob_ts) if ob_ts is not None else 0
                except Exception:
                    ob_ts = 0
                try:
                    lm_ts = int(lm_ts) if lm_ts is not None else 0
                except Exception:
                    lm_ts = 0
                ob_age = (now_ms - ob_ts) if ob_ts > 0 else None
                lm_age = (now_ms - lm_ts) if lm_ts > 0 else None
                fresh = False
                if ob_age is not None and ob_age <= int(DQ_LIQ_FALLBACK_MAX_AGE_MS):
                    fresh = True
                if lm_age is not None and lm_age <= int(DQ_LIQ_FALLBACK_MAX_AGE_MS):
                    fresh = True

                bucket = self._symbol_bucket(symbol)
                if bucket == "major" or fresh:
                    liq_val = self._fallback_liq_from_leverage(winner)
                    if liq_val is not None:
                        winner["liq_distance_pct"] = liq_val
                        if "liq_distance_pct" in dq_meta.get("dq_missing_fields", []):
                            try:
                                dq_meta["dq_missing_fields"].remove("liq_distance_pct")
                            except Exception:
                                pass
                    dq_meta["dq_fallback_used"] = True
                    dq_meta["dq_source_ok"] = bool(fresh or bucket == "major")
                    dq_meta["dq_bucket"] = bucket
                    dq_meta["dq_orderbook_age_ms"] = ob_age
                    dq_meta["dq_liqmap_age_ms"] = lm_age

                    if bucket != "major":
                        try:
                            cur_margin = float(winner.get("margin_usd") or 0.0)
                        except Exception:
                            cur_margin = 0.0
                        dq_prev_margin = cur_margin
                        try:
                            downsized_margin = cur_margin * float(DQ_LIQ_FALLBACK_NON_MAJOR_DOWNSIZE_PCT)
                        except Exception:
                            downsized_margin = cur_margin
                        if downsized_margin > 0 and downsized_margin < cur_margin:
                            dq_downsized = True
                            winner["dq_downsized"] = True
                            winner["dq_prev_margin_usd"] = cur_margin
                            winner["margin_usd"] = downsized_margin
                            try:
                                lev0 = float(winner.get("leverage") or 1.0)
                            except Exception:
                                lev0 = 1.0
                            if lev0 <= 0:
                                lev0 = 1.0
                            winner["notional_usd"] = float(downsized_margin) * float(lev0)
                            try:
                                eq = float(portfolio.get("equity") or 0.0)
                                if eq > 0:
                                    winner["position_size_pct"] = float(downsized_margin) / float(eq) * 100.0
                            except Exception:
                                pass
                else:
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "DQ_MISSING_LIQ"
                    proof["risk_reject_meta"] = {
                        "reason": "missing_liq_no_fresh_source",
                        "dq_bucket": bucket,
                        "dq_orderbook_age_ms": ob_age,
                        "dq_liqmap_age_ms": lm_age,
                    }
                    logger.warning(
                        f"ORCH_RISK_REJECT | reason=DQ_MISSING_LIQ | account={account_id} | symbol={symbol} | action={action} | bucket={bucket}"
                    )
                    self._publish_exec_event(
                        code="DQ_MISSING_LIQ",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta=proof.get("risk_reject_meta") or {},
                    )
                    return None

            if dq_meta:
                meta_blob = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                meta_blob.update(dq_meta)
                winner["metadata"] = meta_blob
                winner.update(dq_meta)

            # Optional DQ hard block for missing critical fields (post-enrichment)
            try:
                from config import DQ_ENRICH_BLOCK_MISSING, DQ_ENRICH_REQUIRED_FIELDS
            except Exception:
                DQ_ENRICH_BLOCK_MISSING = False
                DQ_ENRICH_REQUIRED_FIELDS = ["liq_distance_pct", "orderbook_depth_usd", "volatility_pct"]
            if DQ_ENRICH_BLOCK_MISSING and self._is_risk_add_action(action):
                missing = winner.get("dq_missing_fields") or []
                if isinstance(missing, list):
                    missing_required = [f for f in DQ_ENRICH_REQUIRED_FIELDS if f in missing]
                    if missing_required:
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "DQ_MISSING_FIELDS"
                        proof["risk_reject_meta"] = {"missing_fields": missing_required}
                        logger.warning(
                            "ORCH_RISK_REJECT | reason=DQ_MISSING_FIELDS | account=%s | symbol=%s | action=%s | missing=%s",
                            account_id,
                            symbol,
                            action,
                            ",".join(missing_required),
                        )
                        self._publish_exec_event(
                            code="DQ_MISSING_FIELDS",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta=proof.get("risk_reject_meta") or {},
                        )
                        return None

            # Min-notional guard after downsizing
            if self._is_risk_add_action(action) and (winner.get("ramp_limit_downsized") or dq_downsized):
                try:
                    from config import MIN_NOTIONAL_USD, BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL
                except Exception:
                    MIN_NOTIONAL_USD = 5.0
                    BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL = {}
                try:
                    sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD)
                except Exception:
                    sym_min = float(MIN_NOTIONAL_USD or 5.0)
                effective_min_notional = max(float(MIN_NOTIONAL_USD or 5.0), float(sym_min or 0.0))
                try:
                    cur_notional = float(winner.get("notional_usd") or 0.0)
                except Exception:
                    cur_notional = 0.0
                if cur_notional > 0 and cur_notional < effective_min_notional:
                    try:
                        lev0 = float(winner.get("leverage") or 1.0)
                    except Exception:
                        lev0 = 1.0
                    if lev0 <= 0:
                        lev0 = 1.0
                    required_margin = float(effective_min_notional) / float(lev0)
                    cap_margin = float(winner.get("ramp_limit_cap_margin_usd") or 0.0)
                    if winner.get("ramp_limit_downsized") and cap_margin > 0 and required_margin <= cap_margin:
                        winner["margin_usd"] = required_margin
                        winner["notional_usd"] = float(effective_min_notional)
                        try:
                            eq = float(portfolio.get("equity") or 0.0)
                            if eq > 0:
                                winner["position_size_pct"] = float(required_margin) / float(eq) * 100.0
                        except Exception:
                            pass
                        winner["min_notional_clamped"] = True
                        proof["min_notional_clamped"] = True
                        proof["min_notional_required"] = effective_min_notional
                    else:
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "MIN_NOTIONAL_BLOCK"
                        proof["risk_reject_meta"] = {
                            "reason": "NOTIONAL_BELOW_MIN_AFTER_DOWNSIZE",
                            "notional_usd": cur_notional,
                            "min_notional_usd": effective_min_notional,
                        }
                        logger.warning(
                            f"ORCH_RISK_REJECT | reason=MIN_NOTIONAL_BLOCK | account={account_id} | symbol={symbol} | action={action} | "
                            f"notional={cur_notional:.4f} min_notional={effective_min_notional:.4f}"
                        )
                        self._publish_exec_event(
                            code="MIN_NOTIONAL_BLOCK",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta=proof.get("risk_reject_meta") or {},
                        )
                        return None

            # Minimum OPEN_RISK floor (avoid dust after downsizing)
            action_category = str(winner.get("action_category") or winner.get("category") or "").upper()
            if self._is_risk_add_action(action) and action_category in {"OPEN_RISK", "OPEN", "ENTRY"}:
                try:
                    from config import MIN_OPEN_MARGIN_USD, MIN_OPEN_NOTIONAL_USD, MIN_OPEN_CLAMP_ENABLED
                except Exception:
                    MIN_OPEN_MARGIN_USD = 0.0
                    MIN_OPEN_NOTIONAL_USD = 0.0
                    MIN_OPEN_CLAMP_ENABLED = False
                if MIN_OPEN_CLAMP_ENABLED:
                    try:
                        cur_margin = float(winner.get("margin_usd") or 0.0)
                    except Exception:
                        cur_margin = 0.0
                    try:
                        cur_notional = float(winner.get("notional_usd") or 0.0)
                    except Exception:
                        cur_notional = 0.0
                    try:
                        lev0 = float(winner.get("leverage") or 1.0)
                    except Exception:
                        lev0 = 1.0
                    if lev0 <= 0:
                        lev0 = 1.0

                    cap_margin = float(winner.get("ramp_limit_cap_margin_usd") or 0.0)
                    # If ramp-limit downsizing did not compute a cap, derive an
                    # incremental per-symbol cap from the active phase + portfolio.
                    # This prevents MIN_OPEN_* clamps from self-sabotaging entries
                    # by forcing `margin_usd` above the same cap enforced by ORCH-08.
                    if cap_margin <= 0.0:
                        try:
                            _eq = float(portfolio.get("equity") or 0.0)
                        except Exception:
                            _eq = 0.0
                        try:
                            _per_pos_pct = float(phase.get("per_pos_margin_pct") or 0.0)
                        except Exception:
                            _per_pos_pct = 0.0
                        try:
                            _existing_sym_margin = float(
                                (portfolio.get("per_symbol_margin_usd") or {}).get(symbol, 0.0) or 0.0
                            )
                        except Exception:
                            _existing_sym_margin = 0.0
                        _cap_total = float(_per_pos_pct) * float(_eq) if (_eq > 0.0 and _per_pos_pct > 0.0) else 0.0
                        cap_margin = max(0.0, float(_cap_total) - float(_existing_sym_margin))
                    min_margin = float(MIN_OPEN_MARGIN_USD or 0.0)
                    min_notional = float(MIN_OPEN_NOTIONAL_USD or 0.0)
                    target_notional = cur_notional
                    if min_margin > 0:
                        target_notional = max(target_notional, float(min_margin) * float(lev0))
                    if min_notional > 0:
                        target_notional = max(target_notional, float(min_notional))
                    target_margin = float(target_notional) / float(lev0) if float(lev0) > 0 else cur_margin
                    # If the MIN_OPEN_* floor exceeds the phase cap, cap it (do NOT block).
                    # Otherwise the orchestrator ends up forcing margin_usd above the same
                    # cap later enforced by `assert_risk(...)->ORCH-08`, resulting in zero trades.
                    _min_open_capped = False
                    if cap_margin > 0 and target_margin > cap_margin:
                        _min_open_capped = True
                        target_margin = float(cap_margin)
                        target_notional = float(target_margin) * float(lev0)

                    if target_margin > cur_margin or target_notional > cur_notional:
                        prev_margin = cur_margin
                        prev_notional = cur_notional
                        winner["margin_usd"] = target_margin
                        winner["notional_usd"] = float(target_notional)
                        if min_margin > 0:
                            winner["min_open_margin_clamped"] = True
                            proof["min_open_margin_clamped"] = True
                            proof["min_open_margin_usd"] = float(MIN_OPEN_MARGIN_USD)
                        if min_notional > 0:
                            winner["min_open_notional_clamped"] = True
                            proof["min_open_notional_clamped"] = True
                            proof["min_open_notional_usd"] = float(MIN_OPEN_NOTIONAL_USD)
                        if _min_open_capped:
                            winner["min_open_capped_to_cap"] = True
                            proof["min_open_capped_to_cap"] = True
                            proof["min_open_cap_margin_usd"] = float(cap_margin)
                        logger.info(
                            "ORCH_CLAMP_MIN_OPEN | account=%s | symbol=%s | action=%s | prev_margin=%.4f prev_notional=%.4f "
                            "new_margin=%.4f new_notional=%.4f lev=%.4f",
                            account_id,
                            symbol,
                            action,
                            prev_margin,
                            prev_notional,
                            float(target_margin),
                            float(target_notional),
                            float(lev0),
                        )
        # ── Post-clamp liq buffer pre-check: shared helper (no drift vs ORCH-09) ──
        if not is_canary and self._is_risk_add_action(action):
            try:
                _liq_result = check_liq_buffer(symbol, winner)
                if not _liq_result["ok"]:
                    if self._try_hedge_liq_fail_fallback(
                        winner, proof, account_id, symbol, action, _liq_result
                    ):
                        action = str(
                            winner.get("action") or winner.get("action_name") or ""
                        ).strip().upper()
                        symbol = str(winner.get("symbol") or "").strip().upper()
                        category = str(
                            winner.get("category") or winner.get("action_category") or ""
                        ).strip().upper()
                    else:
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "ORCH_LIQ_BUFFER_PRECHECK_FAIL"
                        logger.warning(
                            "ORCH_LIQ_BUFFER_PRECHECK_FAIL | account=%s | symbol=%s | action=%s | "
                            "liq_distance_pct=%s | min_liq=%.2f | bucket=%s | reason=%s",
                            account_id, symbol, action,
                            f"{_liq_result['liq']:.2f}" if _liq_result["liq"] is not None else "None",
                            _liq_result["min_liq"], _liq_result["bucket"], _liq_result["reason"],
                        )
                        self._publish_exec_event(
                            code="ORCH_LIQ_BUFFER_PRECHECK_FAIL",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                            meta={"liq_distance_pct": _liq_result["liq"], "min_liq": _liq_result["min_liq"],
                                  "bucket": _liq_result["bucket"], "reason": _liq_result["reason"]},
                        )
                        return None
            except Exception:
                pass  # Fail-open: let assert_risk handle it

        if not is_canary:
            risk_result = assert_risk("ORCH", phase, portfolio, winner)
            if not risk_result.ok:
                proof["dropped"] = True
                proof["risk_reject_code"] = risk_result.code
                proof["risk_reject_meta"] = risk_result.meta or {}
                logger.warning(
                    f"ORCH_RISK_REJECT | RISK_ASSERT_FAIL | code={risk_result.code} | account={account_id} | symbol={symbol} | action={action}"
                )
                self._publish_exec_event(
                    code=str(risk_result.code),
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta=risk_result.meta or {},
                )
                return None
        else:
            proof["canary"] = True

        # ------------------------------------------------------------------
        # Repair kill-switch (drop stale repair trims when repair disabled)
        # ------------------------------------------------------------------
        try:
            repair_enabled = bool(getattr(config, "REPAIR_MODE_ENABLED", False))
        except Exception:
            repair_enabled = False
        if not repair_enabled:
            try:
                src_u = str(winner.get("source") or winner.get("source_module") or "").lower()
                action_cat_u = str(winner.get("action_category") or winner.get("category") or "").upper().strip()
                action_u = str(winner.get("action_name") or winner.get("action") or "").upper().strip()
                is_repair_src = ("hedge_manager_v3" in src_u) or ("hedge_mgr_v3" in src_u)
                is_repair_action = (
                    action_u.startswith("PARTIAL_CLOSE")
                    or action_u.startswith("CLOSE_")
                    or action_u in {"CLOSE", "CLOSE_ALL"}
                    or action_u.startswith("DECREASE_")
                )
                force_loss = bool(winner.get("force_loss_close")) and str(winner.get("force_loss_reason") or "").upper() == "LIQ_EMERGENCY"
                _meta_rep = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                _hedge_liq_fb = str(_meta_rep.get("hedge_liq_fallback") or "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                if (
                    is_repair_src
                    and action_cat_u == "PROTECTIVE"
                    and is_repair_action
                    and not force_loss
                    and not _hedge_liq_fb
                ):
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "REPAIR_DISABLED"
                    proof["risk_reject_meta"] = {
                        "reason": "repair_disabled",
                        "source": src_u,
                        "action": action_u,
                        "action_category": action_cat_u,
                    }
                    self.stats["signals_dropped"] = int(self.stats.get("signals_dropped", 0) or 0) + 1
                    logger.warning(
                        "ORCH_REPAIR_DROP_DISABLED | src=%s action=%s symbol=%s reason=repair_disabled",
                        src_u,
                        action_u,
                        symbol,
                    )
                    self._publish_exec_event(
                        code="REPAIR_DISABLED",
                        account_id=account_id,
                        symbol=symbol,
                        action=action_u,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta=proof.get("risk_reject_meta") or {},
                    )
                    return None
            except Exception:
                pass
        
        # Hard symbol-universe deny gate (single publisher safety boundary)
        if not self._is_symbol_allowed(symbol):
            meta = {
                "reason": "symbol_not_allowed",
                "symbol": str(symbol or "").upper(),
                "allow_count": int(len(self.universe_allowed_symbols or set())),
            }
            self.stats["signals_dropped"] = int(self.stats.get("signals_dropped", 0) or 0) + 1
            logger.warning(
                "ORCH_SYMBOL_DENY | symbol=%s action=%s account=%s reason=symbol_not_allowed",
                symbol,
                action,
                account_id,
            )
            self._publish_exec_event(
                code="SYMBOL_NOT_ALLOWED",
                account_id=account_id,
                symbol=symbol,
                action=action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta=meta,
            )
            return None

        # Final observe-only fail-closed gate (never publish OPEN_RISK when unfunded).
        if self._is_open_risk_entry(winner, action):
            _acct_ctx = self._resolve_account_equity_context(account_id, portfolio)
            try:
                equity_usd = float(_acct_ctx.get("equity_usd") or 0.0)
            except Exception:
                equity_usd = 0.0
            try:
                free_margin_ratio = float(_acct_ctx.get("free_margin_ratio") or 0.0)
            except Exception:
                free_margin_ratio = 0.0
            try:
                available_margin_usd = float(_acct_ctx.get("available_margin_usd") or 0.0)
            except Exception:
                available_margin_usd = 0.0
            if available_margin_usd <= 0.0 and equity_usd > 0.0:
                available_margin_usd = max(0.0, float(free_margin_ratio) * float(equity_usd))

            if float(equity_usd) <= 0.0 or float(available_margin_usd) <= 0.0:
                meta = {
                    "reason": "observe_only_unfunded",
                    "equity_usd": float(equity_usd),
                    "available_margin_usd": float(available_margin_usd),
                    "action": str(action or ""),
                    "symbol": str(symbol or "").upper(),
                }
                self.stats["signals_dropped"] = int(self.stats.get("signals_dropped", 0) or 0) + 1
                logger.warning(
                    "ORCH_RISK_REJECT | reason=ORCH_OBSERVE_ONLY_BLOCK | account=%s | symbol=%s | action=%s | equity=%.4f avail=%.4f",
                    account_id,
                    symbol,
                    action,
                    float(equity_usd),
                    float(available_margin_usd),
                )
                self._publish_exec_event(
                    code="ORCH_OBSERVE_ONLY_BLOCK",
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                    meta=meta,
                )
                self._maybe_publish_fallback_on_block(
                    winner,
                    proof,
                    account_id=account_id,
                    symbol=symbol,
                    action=action,
                    reason_code="ORCH_OBSERVE_ONLY_BLOCK",
                    reason_meta=meta,
                )
                return None

            # Symbol-count ramp cap from live positions (capacity gate, not allowlist).
            try:
                cap = int(getattr(config, "RAMP_MAX_OPEN_RISK_SYMBOLS", 0) or 0)
            except Exception:
                cap = 0
            if cap <= 0:
                try:
                    cap = int((phase or {}).get("max_positions") or 0)
                except Exception:
                    cap = 0

            if cap > 0:
                symbol_open = bool(self._symbol_has_live_position(account_id, symbol))
                open_count = int(self._count_open_risk_symbols_live(account_id))
                if (not symbol_open) and open_count >= int(cap):
                    meta = {
                        "reason": "max_open_risk_symbols_reached",
                        "limit": "max_positions",
                        "open_positions": int(open_count),
                        "max_positions": int(cap),
                        "symbol_open": int(symbol_open),
                        "source": "positions:live",
                        "symbol": str(symbol or "").upper(),
                    }
                    self.stats["signals_dropped"] = int(self.stats.get("signals_dropped", 0) or 0) + 1
                    logger.warning(
                        "ORCH_RISK_REJECT | reason=ORCH_RAMP_CAP_BLOCK | account=%s | symbol=%s | action=%s | open=%s cap=%s",
                        account_id,
                        symbol,
                        action,
                        int(open_count),
                        int(cap),
                    )
                    self._publish_exec_event(
                        code="ORCH_RAMP_CAP_BLOCK",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                        meta=meta,
                    )
                    self._maybe_publish_fallback_on_block(
                        winner,
                        proof,
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        reason_code="ORCH_RAMP_CAP_BLOCK",
                        reason_meta=meta,
                    )
                    return None

        # ── Hedge Shock Manager (pre-publish leg protection) ─────────────
        if self.orch_hedge_shock_enabled:
            try:
                _shock_result = self._hedge_shock_eval(
                    account_id, symbol, action, winner,
                )
                if _shock_result is not None:
                    _sv = str(_shock_result.get("verdict") or "").upper()
                    _sr = str(_shock_result.get("reason") or "ORCH_HEDGE_SHOCK")
                    _sm = dict(_shock_result.get("meta") or {})

                    # ─ BLOCK verdicts: reject the original proposal ──────
                    if _sv in ("BLOCK", "BLOCK_AND_OVERRIDE"):
                        self.stats["signals_dropped"] = int(
                            self.stats.get("signals_dropped", 0) or 0
                        ) + 1
                        logger.warning(
                            "ORCH_RISK_REJECT | reason=%s | account=%s | "
                            "symbol=%s | action=%s | verdict=%s",
                            _sr, account_id, symbol, action, _sv,
                        )
                        self._publish_exec_event(
                            code=_sr,
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(
                                winner.get("proposal_id")
                                or winner.get("id") or ""
                            ),
                            meta=_sm,
                        )

                    # ─ Pure BLOCK (no override) → fallback + return ──────
                    if _sv == "BLOCK":
                        self._maybe_publish_fallback_on_block(
                            winner,
                            proof,
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            reason_code=_sr,
                            reason_meta=_sm,
                        )
                        return None

                    # ─ OVERRIDE / BLOCK_AND_OVERRIDE → replace action ────
                    if _sv in ("OVERRIDE", "BLOCK_AND_OVERRIDE"):
                        derisk_action = str(
                            _shock_result.get("derisk_action") or action
                        ).upper()
                        derisk_side = str(
                            _shock_result.get("derisk_side") or ""
                        ).upper()
                        derisk_frac = float(
                            _shock_result.get("derisk_fraction") or 0.50
                        )
                        derisk_evt = str(
                            _shock_result.get("derisk_event_code")
                            or "ORCH_HEDGE_SHOCK_OVERRIDE"
                        )

                        # Patch the winner dict for the de-risk action
                        winner = dict(winner)
                        winner["action"] = derisk_action
                        winner["action_type"] = "close"
                        winner["action_category"] = "PROTECTIVE"
                        winner["category"] = "PROTECTIVE"
                        winner["position_side"] = derisk_side
                        winner["close_side"] = derisk_side
                        winner["reduce_only"] = True
                        winner["close_fraction"] = derisk_frac
                        winner["shock_close_fraction"] = derisk_frac
                        winner["shock_reason"] = _sr
                        winner["shock_event_code"] = derisk_evt
                        # Clear open-specific sizing (trader derives
                        # close qty from position + fraction)
                        winner.pop("margin_usd", None)
                        winner.pop("notional_usd", None)
                        winner.pop("position_size_pct", None)
                        action = derisk_action

                        self._publish_exec_event(
                            code=derisk_evt,
                            account_id=account_id,
                            symbol=symbol,
                            action=derisk_action,
                            proposal_id=str(
                                winner.get("proposal_id")
                                or winner.get("id") or ""
                            ),
                            meta={
                                **_sm,
                                "derisk_side": derisk_side,
                                "derisk_fraction": derisk_frac,
                            },
                        )
                        logger.info(
                            "ORCH_HEDGE_SHOCK_OVERRIDE | account=%s | "
                            "symbol=%s | new_action=%s | side=%s | "
                            "fraction=%.2f | reason=%s",
                            account_id, symbol, derisk_action,
                            derisk_side, derisk_frac, _sr,
                        )
            except Exception as exc:
                logger.error(
                    "ORCH_HEDGE_SHOCK_WIRE_ERROR | %s", exc, exc_info=True,
                )

        # Generate plan_id
        plan_id = f"plan_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        
        # Select output stream
        if account_id == "asjad":
            stream = SIGNAL_STREAM_ASJAD
        else:
            stream = SIGNAL_STREAM_PRIMARY
        
        # Build signal payload
        signal = dict(winner)
        signal["plan_id"] = plan_id
        signal["trace_id"] = winner.get("trace_id") or proof.get("trace_id") or ""
        signal["published_by"] = "orchestrator_worker"
        _pub_now_ms = int(time.time() * 1000)
        signal["published_ts_ms"] = _pub_now_ms
        signal["ts_ms"] = _pub_now_ms
        signal["created_ts_ms"] = _pub_now_ms
        signal["timestamp"] = time.time()
        signal["event"] = "TRADING_SIGNAL"

        try:
            _sig_meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
            for _mtk in (
                "mtf_scenario_id",
                "primary_tf",
                "contrary_htf_bias",
                "tf_votes",
                "tf_bias_dir",
                "tf_timing_dir",
                "tf_conflict_score",
            ):
                if signal.get(_mtk) is None and _sig_meta.get(_mtk) is not None:
                    signal[_mtk] = _sig_meta.get(_mtk)
        except Exception:
            pass

        # ── Execution authority token ─────────────────────────────────────────
        # Stamp orch_approved=1 + a lightweight plan signature so traders can
        # verify the signal came from the orchestrator and was not injected
        # directly by any other module.
        if getattr(config, "ORCH_EXEC_TOKEN_ENABLED", True):
            try:
                import hashlib as _hl
                _sig_input = f"{plan_id}:{symbol}:{action}:{account_id}"
                signal["orch_approved"] = 1
                signal["orch_plan_sig"] = _hl.sha256(_sig_input.encode()).hexdigest()[:16]
                signal["orch_ts_ms"] = signal["published_ts_ms"]
            except Exception:
                signal["orch_approved"] = 1  # stamp even if hash fails
        # Ensure regime fields survive into published signal for downstream consumers
        # GATED: attachment permitted when REGIME_LAYER_ENABLED (no decision mutation here)
        if getattr(config, "REGIME_LAYER_ENABLED", False) or config.regime_active():
            _op_policy = signal.get("operator_policy") or proof.get("operator_policy") or {}
            if isinstance(_op_policy, dict):
                for _rk in ("move_score", "move_regime", "volatility_score", "liq_risk",
                            "liquidity_score", "fast_move_score", "big_move_one_leg"):
                    if _op_policy.get(_rk) is not None and signal.get(_rk) is None:
                        signal[_rk] = _op_policy[_rk]
            # Enrich ALL signals with cached regime data when regime fields are missing or UNKNOWN.
            # Also always ensure signal["regime"] is set — trader regime_label fallback reads this.
            _needs_regime = (
                signal.get("move_regime") is None
                or str(signal.get("move_regime", "")).upper() in ("", "UNKNOWN")
                or signal.get("trend_direction") is None
                or signal.get("regime") is None  # also enrich when regime key missing even if move_regime present
                or str(signal.get("regime", "")).upper() in ("", "UNKNOWN")
            )
            if _needs_regime:
                try:
                    _sig_sym = str(signal.get("symbol") or "").upper()
                    _cached_regime = self.redis.get(f"regime:{_sig_sym}") if _sig_sym else None
                    if _cached_regime:
                        import json as _json_regime
                        if isinstance(_cached_regime, (bytes, bytearray)):
                            _cached_regime = _cached_regime.decode("utf-8", errors="ignore")
                        _rdict = _json_regime.loads(_cached_regime)
                        if isinstance(_rdict, dict):
                            _regime_age_s = (time.time() * 1000 - float(_rdict.get("updated_ts_ms", 0))) / 1000
                            _stale_sec = getattr(config, "REGIME_STALE_SEC", 300)
                            if _regime_age_s <= _stale_sec:
                                for _rk2 in ("move_score", "move_regime", "market_regime",
                                             "trend_direction", "volatility_score",
                                             "fast_move_score", "liq_risk", "liquidity_score",
                                             "tf_alignment", "tf_entropy", "liq_imbalance"):
                                    _rv = _rdict.get(_rk2)
                                    _sv = signal.get(_rk2)
                                    if _rv is not None and (_sv is None or str(_sv).upper() in ("", "UNKNOWN")):
                                        signal[_rk2] = _rv
                                # Always set regime from move_regime/market_regime (primary field traders read)
                                if signal.get("regime") is None or str(signal.get("regime", "")).upper() in ("", "UNKNOWN"):
                                    signal["regime"] = str(_rdict.get("move_regime") or _rdict.get("market_regime") or "UNKNOWN")
                except Exception:
                    pass  # fail-open: regime enrichment is best-effort
            # Final fallback: if regime still UNKNOWN/None, derive from structural_regime in signal itself
            if not signal.get("regime") or str(signal.get("regime", "")).upper() in ("", "UNKNOWN"):
                _sr = str(signal.get("structural_regime") or signal.get("effective_structural") or "").upper()
                if _sr and _sr not in ("", "UNKNOWN", "NONE", "NORMAL"):
                    signal["regime"] = _sr
                elif signal.get("move_regime") and str(signal["move_regime"]).upper() not in ("", "UNKNOWN"):
                    signal["regime"] = str(signal["move_regime"]).upper()
        # Ensure origin tagging is always present for downstream auditing/cap logic.
        # Traders frequently key behavior off `source`; some producers only set `source_module`.
        if not str(signal.get("source") or "").strip():
            signal["source"] = str(signal.get("source_module") or source)
        if not str(signal.get("source_module") or "").strip():
            signal["source_module"] = str(signal.get("source") or source)

        # Ensure explicit close side fields for hedge-mode safety
        try:
            action_u = str(action or "").upper().strip()
            is_close_action = (
                ("CLOSE" in action_u or "PARTIAL_CLOSE" in action_u or "TAKE_PROFIT" in action_u or "STOP_LOSS" in action_u)
                and "CLOSE_AND" not in action_u
            )
            if is_close_action:
                pos_side = str(
                    signal.get("position_side")
                    or signal.get("pos_side")
                    or signal.get("side")
                    or ""
                ).upper().strip()
                if not pos_side:
                    if "LONG" in action_u:
                        pos_side = "LONG"
                    elif "SHORT" in action_u:
                        pos_side = "SHORT"

                if pos_side:
                    signal["position_side"] = pos_side
                    signal["close_side"] = signal.get("close_side") or pos_side
                    if "order_side" not in signal or not str(signal.get("order_side") or "").strip():
                        signal["order_side"] = "SELL" if pos_side == "LONG" else "BUY"
                    signal["reduce_only"] = True
        except Exception:
            pass
        
        if self.shadow_mode:
            # Shadow mode: log but don't publish
            logger.info(
                f"👻 [SHADOW] Would publish: {account_id}:{symbol} {action} "
                f"src={source} plan_id={plan_id}"
            )
            self.stats["signals_published"] += 1
            return plan_id

        # ── ANTI-CHURN GATE (Feb 2026 Audit Fix #2) ─────────────────────
        # Block entries when per-symbol hourly fill cap or daily notional cap exceeded.
        # Only applies to risk-adding actions (not closes/reduces).
        #
        # ADAPTIVE OVERRIDE (Feb 2026): When ADAPTIVE_GATE_ENABLED=true,
        # the fill cap and notional cap are supplemented by the AdaptiveGate
        # which uses live market features (spread, depth, volatility, etc.)
        # to make data-driven anti-churn decisions instead of static caps.
        try:
            # ── ADAPTIVE GATE (data-driven anti-churn) ──
            _adaptive_on = bool(getattr(config, "ADAPTIVE_GATE_ENABLED", True))
            if _adaptive_on and self._is_risk_add_action(action) and not is_canary:
                try:
                    from risk.adaptive_gate import AdaptiveGate
                    _ag_redis = self.redis
                    if _ag_redis:
                        _ag = AdaptiveGate(_ag_redis)
                        _ag_action_u = str(action or "").upper()
                        _ag_side = "LONG" if "LONG" in _ag_action_u else "SHORT"
                        _ag_act_type = "open"
                        if "HEDGE" in _ag_action_u:
                            _ag_act_type = "hedge"
                        elif "INCREASE" in _ag_action_u or "ADD" in _ag_action_u:
                            _ag_act_type = "increase"
                        elif "CLOSE_AND" in _ag_action_u:
                            _ag_act_type = "flip"
                        _ag_notional = float(signal.get("notional_usd") or signal.get("margin_usd", 0) or 0)
                        _ag_conf = float(signal.get("model_confidence") or signal.get("confidence", 0) or 0)
                        _ag_tf = str(signal.get("timeframe") or signal.get("tf") or "5m")

                        _ag_verdict = _ag.evaluate(
                            symbol=symbol,
                            side=_ag_side,
                            action_type=_ag_act_type,
                            notional_usd=_ag_notional,
                            model_confidence=_ag_conf,
                            timeframe=_ag_tf,
                        )

                        if not _ag_verdict.allow:
                            logger.warning(
                                "ADAPTIVE_GATE_BLOCK | symbol=%s | action=%s | code=%s | reason=%s",
                                symbol, action, _ag_verdict.code, _ag_verdict.reason[:200],
                            )
                            self._publish_exec_event(
                                code="ADAPTIVE_GATE_BLOCK",
                                account_id=account_id,
                                symbol=symbol,
                                action=action,
                                proposal_id=str(winner.get("proposal_id") or ""),
                                meta={
                                    "gate_code": _ag_verdict.code,
                                    "reason": _ag_verdict.reason[:300],
                                    "sizing_mult": _ag_verdict.sizing_mult,
                                },
                            )
                            proof["dropped"] = True
                            proof["risk_reject_code"] = f"ADAPTIVE_GATE:{_ag_verdict.code}"
                            return None

                        # Apply sizing reduction
                        if _ag_verdict.sizing_mult < 1.0:
                            _ag_m = _ag_verdict.sizing_mult
                            _old_n = float(signal.get("notional_usd", 0) or 0)
                            _old_mg = float(signal.get("margin_usd", 0) or 0)
                            _old_pct = float(signal.get("position_size_pct", 0) or 0)
                            if _old_n > 0:
                                signal["notional_usd"] = round(_old_n * _ag_m, 2)
                            if _old_mg > 0:
                                signal["margin_usd"] = round(_old_mg * _ag_m, 2)
                            if _old_pct > 0:
                                signal["position_size_pct"] = round(_old_pct * _ag_m, 4)

                            # Enforce minimum OPEN_RISK floors AFTER any adaptive downsizing.
                            # Without this, adaptive sizing can produce dust-sized entries (e.g. $1–$3 margin),
                            # which is operationally useless and contradicts the MIN_OPEN_* contract.
                            try:
                                action_category_u = str(
                                    signal.get("action_category") or signal.get("category") or ""
                                ).upper().strip()
                            except Exception:
                                action_category_u = ""
                            if action_category_u in {"OPEN_RISK", "OPEN", "ENTRY"}:
                                try:
                                    from config import MIN_OPEN_MARGIN_USD, MIN_OPEN_NOTIONAL_USD, MIN_OPEN_CLAMP_ENABLED
                                except Exception:
                                    MIN_OPEN_MARGIN_USD = 0.0
                                    MIN_OPEN_NOTIONAL_USD = 0.0
                                    MIN_OPEN_CLAMP_ENABLED = False
                                if MIN_OPEN_CLAMP_ENABLED:
                                    try:
                                        _cur_m = float(signal.get("margin_usd") or 0.0)
                                    except Exception:
                                        _cur_m = 0.0
                                    try:
                                        _cur_n = float(signal.get("notional_usd") or 0.0)
                                    except Exception:
                                        _cur_n = 0.0
                                    try:
                                        _lev0 = float(signal.get("leverage") or winner.get("leverage") or 1.0)
                                    except Exception:
                                        _lev0 = 1.0
                                    if _lev0 <= 0:
                                        _lev0 = 1.0
                                    try:
                                        _cap_margin = float(winner.get("ramp_limit_cap_margin_usd") or 0.0)
                                    except Exception:
                                        _cap_margin = 0.0
                                    try:
                                        _min_margin = float(MIN_OPEN_MARGIN_USD or 0.0)
                                    except Exception:
                                        _min_margin = 0.0
                                    try:
                                        _min_notional = float(MIN_OPEN_NOTIONAL_USD or 0.0)
                                    except Exception:
                                        _min_notional = 0.0

                                    _target_notional = float(_cur_n)
                                    if _min_margin > 0:
                                        _target_notional = max(_target_notional, float(_min_margin) * float(_lev0))
                                    if _min_notional > 0:
                                        _target_notional = max(_target_notional, float(_min_notional))
                                    _target_margin = float(_target_notional) / float(_lev0) if float(_lev0) > 0 else float(_cur_m)

                                    # Respect ramp caps (same rule as the earlier clamp)
                                    if _cap_margin > 0 and _target_margin > _cap_margin:
                                        proof["dropped"] = True
                                        proof["risk_reject_code"] = "MIN_OPEN_MARGIN_BLOCK"
                                        proof["risk_reject_meta"] = {
                                            "reason": "MIN_OPEN_MARGIN_EXCEEDS_CAP_AFTER_ADAPTIVE_DOWNSIZE",
                                            "margin_usd": float(_cur_m),
                                            "notional_usd": float(_cur_n),
                                            "min_open_margin_usd": float(MIN_OPEN_MARGIN_USD),
                                            "min_open_notional_usd": float(MIN_OPEN_NOTIONAL_USD),
                                            "cap_margin_usd": float(_cap_margin),
                                            "adaptive_gate_mult": float(_ag_m),
                                        }
                                        self._publish_exec_event(
                                            code="MIN_OPEN_MARGIN_BLOCK",
                                            account_id=account_id,
                                            symbol=symbol,
                                            action=action,
                                            proposal_id=str(winner.get("proposal_id") or ""),
                                            meta=proof.get("risk_reject_meta") or {},
                                        )
                                        return None

                                    # Clamp up to min-open floors (avoid dust entries)
                                    if (_target_margin > float(_cur_m) + 1e-9) or (_target_notional > float(_cur_n) + 1e-9):
                                        signal["margin_usd"] = round(float(_target_margin), 4)
                                        signal["notional_usd"] = round(float(_target_notional), 4)
                                        signal["min_open_margin_clamped"] = True
                                        signal["min_open_notional_clamped"] = True
                                        # Keep signal metadata consistent for audits
                                        try:
                                            _meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
                                            _meta["min_open_margin_usd"] = float(MIN_OPEN_MARGIN_USD)
                                            _meta["min_open_notional_usd"] = float(MIN_OPEN_NOTIONAL_USD)
                                            _meta["adaptive_gate_mult"] = float(_ag_m)
                                            signal["metadata"] = _meta
                                        except Exception:
                                            pass
                            logger.info(
                                "ADAPTIVE_GATE_SIZE_REDUCE | symbol=%s | mult=%.2f | "
                                "notional $%.0f→$%.0f | reason=%s",
                                symbol, _ag_m, _old_n,
                                float(signal.get("notional_usd", 0)),
                                _ag_verdict.reason[:150],
                            )
                except ImportError:
                    pass  # adaptive_gate module not available
                except Exception as _ag_err:
                    logger.debug("ADAPTIVE_GATE_ORCH_ERR | %s", _ag_err)

            # ── Static anti-churn caps (fallback / additional defense) ──
            _anti_churn_on = bool(getattr(config, "ANTI_CHURN_ENABLED", True))
            if _anti_churn_on and self._is_risk_add_action(action) and not is_canary:
                import datetime as _dt_ac
                _now_ac = time.time()
                _sym_u_ac = str(symbol).upper()
                _hour_ago = _now_ac - 3600.0

                # (A) Per-symbol hourly fill cap — separate counters for
                #     risk-add vs protective/hedge to avoid hedges starving entries
                _is_hedge_fill = self._is_protective_action(winner, action)
                _max_fills = int(getattr(config, "MAX_FILLS_PER_SYMBOL_PER_HOUR", 3))
                if _is_hedge_fill:
                    _max_fills = int(getattr(config, "MAX_HEDGE_FILLS_PER_SYMBOL_PER_HOUR", _max_fills))

                # ── P3: Regime-Scaled Fill Budget (Mar 2026, v2) ──
                # Scale fill budget using unified_features:5m NATR + ADX directly.
                # regime:{sym} key does not exist — ingest writes unified_features:{sym}:{tf}.
                # fill_budget = base * natr_mult * adx_mult * depth_factor
                try:
                    from config import ENABLE_ADAPTIVE_FILL_BUDGET
                    if ENABLE_ADAPTIVE_FILL_BUDGET and self.redis:
                        _afb_natr_mult = 1.0
                        _afb_adx_mult = 1.0
                        _afb_depth_factor = 1.0
                        try:
                            import json as _jfb
                            _afb_feat = self.redis.hgetall(f"unified_features:{_sym_u_ac}:5m")
                            if _afb_feat:
                                def _afb_fv(d, *pats):
                                    for k, v in d.items():
                                        kl = (k.decode() if isinstance(k, (bytes, bytearray)) else k).lower()
                                        vl = (v.decode() if isinstance(v, (bytes, bytearray)) else str(v))
                                        for p in pats:
                                            if p in kl:
                                                try: return float(vl)
                                                except: pass
                                    return None
                                # NATR % — use 1h cross-TF field if present, else 5m
                                _afb_natr = (_afb_fv(_afb_feat, "xtf_1h_natr") or
                                             _afb_fv(_afb_feat, "ta_natr_14") or 0.0)
                                # ADX — use 1h cross-TF field if present, else 5m
                                _afb_adx = (_afb_fv(_afb_feat, "xtf_1h_adx") or
                                            _afb_fv(_afb_feat, "ta_adx_14") or 0.0)
                                # NATR mult: 0.5% → 1.0x, 1.5% → 2.0x, 3%+ → 3.0x (scale aggressively for high-vol)
                                if _afb_natr > 0.3:
                                    _afb_natr_mult = min(3.0, max(1.0, _afb_natr / 0.5))
                                # ADX mult: ADX > 25 → trending → more fills; ADX > 40 → strong trend → max
                                if _afb_adx > 20:
                                    _afb_adx_mult = min(2.0, max(1.0, _afb_adx / 25.0))
                                # Depth factor
                                _afb_depth_raw = _afb_fv(_afb_feat, "depth_bps_25_total_usd")
                                if _afb_depth_raw and _afb_depth_raw > 0:
                                    _afb_depth_factor = min(1.5, max(0.7, _afb_depth_raw / 500000.0))
                        except Exception:
                            pass
                        _afb_scaled = int(_max_fills * _afb_natr_mult * _afb_adx_mult * _afb_depth_factor)
                        _afb_scaled = max(_max_fills, min(30, _afb_scaled))  # floor=base, cap=30/hour
                        if _afb_scaled != _max_fills:
                            logger.info(
                                "ADAPTIVE_FILL_BUDGET | sym=%s | base=%d scaled=%d | "
                                "natr_mult=%.2f adx_mult=%.2f depth_factor=%.2f",
                                _sym_u_ac, _max_fills, _afb_scaled,
                                _afb_natr_mult, _afb_adx_mult, _afb_depth_factor,
                            )
                        _max_fills = _afb_scaled
                except ImportError:
                    pass
                except Exception as _afb_err:
                    logger.debug("ADAPTIVE_FILL_BUDGET_ERR | %s", _afb_err)

                _fill_key = f"{_sym_u_ac}:HEDGE" if _is_hedge_fill else _sym_u_ac
                if _fill_key not in self._per_symbol_fill_log:
                    self._per_symbol_fill_log[_fill_key] = []
                self._per_symbol_fill_log[_fill_key] = [
                    t for t in self._per_symbol_fill_log[_fill_key] if t > _hour_ago
                ]
                if len(self._per_symbol_fill_log[_fill_key]) >= _max_fills:
                    _material_change = False
                    try:
                        _mc_roi = self._safe_float(winner.get("roi_pct") or winner.get("roe_pct") or winner.get("pnl_pct"))
                        _mc_regime = str(winner.get("regime") or winner.get("move_regime") or "").upper()
                        _mc_conf = float(winner.get("confidence") or winner.get("model_confidence") or 0.0)
                        _mc_liq = self._safe_float(winner.get("liq_distance_bps") or winner.get("liq_bps"))
                        _last_fill_meta = getattr(self, '_last_fill_meta', {}).get(_fill_key, {})
                        _roi_delta = abs((_mc_roi or 0) - (_last_fill_meta.get("roi", 0) or 0))
                        _regime_changed = _mc_regime and _mc_regime != _last_fill_meta.get("regime", "")
                        _liq_worsened = _mc_liq is not None and _last_fill_meta.get("liq") is not None and _mc_liq < _last_fill_meta["liq"] * 0.8
                        # P3 adaptive: material-change ROI threshold scales with NATR * leverage
                        _mc_roi_thresh = 2.0  # default
                        try:
                            from config import ENABLE_ADAPTIVE_FILL_BUDGET as _EAFB2
                            if _EAFB2 and self.redis:
                                _mc_natr_raw = self.redis.hget(f"unified_features:{_sym_u_ac}:5m", "ind_ta_NATR_14_5m")
                                _mc_lev = float(winner.get("leverage") or 20)
                                if _mc_natr_raw:
                                    _mc_natr = float(_mc_natr_raw)
                                    _mc_roi_thresh = max(0.5, _mc_natr * _mc_lev / 20.0 * 2.0)
                        except Exception:
                            pass
                        if _roi_delta >= _mc_roi_thresh or _regime_changed or _liq_worsened or _mc_conf >= 0.90:
                            _material_change = True
                    except Exception:
                        pass
                    _act_upper_fc = str(action).upper()
                    _is_flip_fc = ("CLOSE" in _act_upper_fc and "OPEN" in _act_upper_fc) or "FLIP" in _act_upper_fc
                    if _material_change or _is_flip_fc:
                        logger.info(
                            "ANTI_CHURN_FILL_BYPASS | symbol=%s | fills_1h=%d | max=%d | "
                            "material_change=%s flip=%s | ALLOWED",
                            _sym_u_ac, len(self._per_symbol_fill_log[_fill_key]),
                            _max_fills, _material_change, _is_flip_fc,
                        )
                    else:
                        logger.warning(
                            "ANTI_CHURN_FILL_CAP | symbol=%s | fills_1h=%d | max=%d | action=%s | hedge=%s | BLOCKED",
                            _sym_u_ac, len(self._per_symbol_fill_log[_fill_key]), _max_fills, action, _is_hedge_fill,
                        )
                        self._publish_exec_event(
                            code="ANTI_CHURN_FILL_CAP",
                            account_id=account_id,
                            symbol=symbol,
                            action=action,
                            proposal_id=str(winner.get("proposal_id") or ""),
                            meta={"fills_1h": len(self._per_symbol_fill_log[_fill_key]), "max": _max_fills, "hedge": _is_hedge_fill},
                        )
                        proof["dropped"] = True
                        proof["risk_reject_code"] = "ANTI_CHURN_FILL_CAP"
                        return None

                # (B) Daily notional turnover cap
                _max_turnover = float(getattr(config, "MAX_NOTIONAL_TURNOVER_RATIO", 30.0))
                _today_str = _dt_ac.datetime.utcnow().strftime("%Y-%m-%d")
                if self._daily_notional_reset_date != _today_str:
                    self._daily_notional_usd = 0.0
                    self._daily_notional_reset_date = _today_str
                _signal_notional = float(signal.get("notional_usd") or signal.get("margin_usd", 0) or 0)
                _equity_est = 0.0
                try:
                    _eq_raw = self.redis.get(f"portfolio:equity:{account_id}") if self.redis else None
                    if _eq_raw:
                        import json as _json_eq
                        _eq_parsed = _json_eq.loads(_eq_raw)
                        _equity_est = float(_eq_parsed.get("equity_usd", 0)) if isinstance(_eq_parsed, dict) else float(_eq_parsed)
                    if not _equity_est or _equity_est <= 0:
                        _eq_raw2 = self.redis.get(f"equity:{account_id}") if self.redis else None
                        _equity_est = float(_eq_raw2) if _eq_raw2 else 1000.0
                except Exception:
                    _equity_est = 1000.0
                _max_daily_notional = _equity_est * _max_turnover
                _act_upper_ac = str(action).upper()
                _is_hedge_ac = self._is_protective_action(winner, action)
                _is_flip_ac = ("CLOSE" in _act_upper_ac) and ("OPEN" in _act_upper_ac or "AND" in _act_upper_ac)
                # Risk-reducing actions (closes, reduces, TP/SL adjustments)
                # should NOT consume the notional budget — only new risk entries count
                _is_reduce_ac = any(tok in _act_upper_ac for tok in [
                    "CLOSE", "REDUCE", "PARTIAL_CLOSE", "SET_TAKE_PROFIT",
                    "SET_STOP_LOSS", "DELEVERAGE", "EXIT",
                ])
                _bypass_notional = _is_hedge_ac or _is_flip_ac or _is_reduce_ac
                if _bypass_notional:
                    logger.info(
                        "ANTI_CHURN_NOTIONAL_BYPASS | symbol=%s | action=%s | hedge=%s | flip=%s | reduce=%s | "
                        "daily_notional=$%.0f | max=$%.0f | ALLOWED",
                        _sym_u_ac, action, _is_hedge_ac, _is_flip_ac, _is_reduce_ac,
                        self._daily_notional_usd, _max_daily_notional,
                    )
                elif _max_daily_notional > 0 and (self._daily_notional_usd + _signal_notional) > _max_daily_notional:
                    logger.warning(
                        "ANTI_CHURN_NOTIONAL_CAP | symbol=%s | daily_notional=$%.0f | "
                        "signal_notional=$%.0f | max=$%.0f | BLOCKED",
                        _sym_u_ac, self._daily_notional_usd, _signal_notional, _max_daily_notional,
                    )
                    self._publish_exec_event(
                        code="ANTI_CHURN_NOTIONAL_CAP",
                        account_id=account_id,
                        symbol=symbol,
                        action=action,
                        proposal_id=str(winner.get("proposal_id") or ""),
                        meta={
                            "daily_notional": self._daily_notional_usd,
                            "signal_notional": _signal_notional,
                            "max_daily": _max_daily_notional,
                        },
                    )
                    proof["dropped"] = True
                    proof["risk_reject_code"] = "ANTI_CHURN_NOTIONAL_CAP"
                    return None

                # Track notional for the day — only count non-bypassed signals
                # so protective hedges/flips don't consume the new-entry budget
                if not _bypass_notional:
                    self._daily_notional_usd += _signal_notional
                # Track fill for this symbol (use separated hedge/risk key)
                if _fill_key not in self._per_symbol_fill_log:
                    self._per_symbol_fill_log[_fill_key] = []
                self._per_symbol_fill_log[_fill_key].append(_now_ac)
                if not hasattr(self, '_last_fill_meta'):
                    self._last_fill_meta = {}
                self._last_fill_meta[_fill_key] = {
                    "roi": self._safe_float(winner.get("roi_pct") or winner.get("roe_pct") or winner.get("pnl_pct")),
                    "regime": str(winner.get("regime") or winner.get("move_regime") or "").upper(),
                    "liq": self._safe_float(winner.get("liq_distance_bps") or winner.get("liq_bps")),
                    "ts": _now_ac,
                }
        except Exception as _ac_err:
            logger.debug("ANTI_CHURN_ERR | %s", _ac_err)
        
        try:
            from utils.signal_publish import publish_trading_signal

            # Ensure decision_id for end-to-end proof correlation.
            if not signal.get("decision_id"):
                signal["decision_id"] = f"{int(time.time()*1000)}-{str(symbol).upper()}-{str(signal.get('timeframe') or signal.get('tf') or 'na').lower()}-{str(account_id).lower()}"

            json_data = json.dumps(signal, separators=(",", ":"), default=str)
            msg_id = publish_trading_signal(
                self.redis,
                stream,
                {"data": json_data},
                maxlen=int(self.signal_maxlen),
                approximate=True,
            )
            
            self.stats["signals_published"] += 1
            logger.info(
                f"✅ Published: {account_id}:{symbol} {action} src={source} "
                f"plan_id={plan_id} stream_id={msg_id}"
            )

            # Update RBA cadence tracker on successful risk-add publish
            # Only NET-NEW directional entries reset the cadence:
            # - Hedges are risk-reducing → no reset
            # - FLIPs are net-neutral (close one side, open another) → no reset
            try:
                _act_u_cad = str(action or "").upper()
                _is_hedge_cad = "HEDGE" in _act_u_cad
                _is_flip_cad = ("CLOSE" in _act_u_cad and "OPEN" in _act_u_cad) or "FLIP" in _act_u_cad
                _should_reset = self._is_risk_add_action(action) and not _is_hedge_cad and not _is_flip_cad
                if _should_reset:
                    self._rba_last_open_ts[account_id] = time.time()
                if self._is_risk_add_action(action):
                    _now_t = time.time()
                    if _is_hedge_cad:
                        self._hedge_publish_log.append(_now_t)
                    else:
                        self._entry_publish_log.append(_now_t)
            except Exception:
                pass

            kind_tag = "SYSTEM_CANARY" if is_canary else "TRADE"
            self._emit_account_diag(
                kind="orch_account_select",
                decision_id=str(signal.get("decision_id") or decision_id),
                symbol=symbol,
                tf=str(signal.get("timeframe") or tf),
                requested_account=str(signal.get("requested_account_id") or requested_account or account_id),
                selected_account=account_id,
                reason="PUBLISH_OK",
                reasons_json={"stream": stream, "kind": kind_tag},
            )
            logger.info(
                f"ORCH_PUBLISH_OK | account={account_id} | stream={stream} | symbol={symbol} | action={action} | proposal_id={winner.get('proposal_id')} | kind={kind_tag}"
            )
            self._publish_exec_event(
                code="ORCH_PUBLISH_OK",
                account_id=account_id,
                symbol=symbol,
                action=action,
                proposal_id=str(winner.get("proposal_id") or winner.get("id") or ""),
                meta={"stream": stream, "plan_id": plan_id, "kind": kind_tag},
            )
            
            return plan_id
            
        except Exception as e:
            logger.error(f"Failed to publish signal: {e}")
            return None
    
    def _record_published_plan(
        self,
        key: Tuple[str, str],
        winner: Dict[str, Any],
        plan_id: str,
        proof: Dict[str, Any],
    ):
        """Record published plan for cooldown tracking."""
        account_id, symbol = key
        action = str(winner.get("action") or "").upper()
        
        plan = PublishedPlan(
            plan_id=plan_id,
            account_id=account_id,
            symbol=symbol,
            action=action,
            action_family=self._action_family(action),
            published_ts_ms=int(time.time() * 1000),
            proposal_id=str(winner.get("proposal_id") or ""),
            trace_id=str(winner.get("trace_id") or ""),
        )
        
        self.published_plans[key].append(plan)
    
    def _cleanup_old_plans(self, now_ms: int):
        """Remove published plans older than cooldown horizon."""
        cutoff = now_ms - self.cooldown_horizon_ms
        
        for key in list(self.published_plans.keys()):
            self.published_plans[key] = [
                p for p in self.published_plans[key]
                if p.published_ts_ms > cutoff
            ]
            if not self.published_plans[key]:
                del self.published_plans[key]
    
    def _emit_proof(self, proof: Dict[str, Any]):
        """Emit orchestrator proof to health:events stream."""
        try:
            proof["event"] = "ORCHESTRATOR_PROOF"
            proof["severity"] = "INFO"
            proof["worker_id"] = CONSUMER_NAME
            proof["shadow_mode"] = self.shadow_mode
            
            json_data = json.dumps(proof, separators=(",", ":"), default=str)
            self.redis.xadd(PROOF_STREAM, {"data": json_data})
            
        except Exception as e:
            logger.error(f"Failed to emit proof: {e}")
    
    def _emit_trace(self, trace: Dict[str, Any]):
        """Emit decision trace to wma:traces stream."""
        try:
            trace["event"] = "ORCHESTRATOR_TRACE"
            trace["ts_ms"] = int(time.time() * 1000)
            trace["worker_id"] = CONSUMER_NAME
            
            json_data = json.dumps(trace, separators=(",", ":"), default=str)
            self.redis.xadd(TRACE_STREAM, {"data": json_data})
            
        except Exception as e:
            logger.error(f"Failed to emit trace: {e}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self.running = False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        return {
            **self.stats,
            "active_windows": len(self.windows),
            "tracked_plans": sum(len(v) for v in self.published_plans.values()),
            "shadow_mode": self.shadow_mode,
        }


def main():
    """Entry point for orchestrator worker."""
    parser = argparse.ArgumentParser(description="Orchestrator Worker")
    parser.add_argument("--shadow", action="store_true", help="Run in shadow mode (don't publish)")
    parser.add_argument("--window-ms", type=int, default=MICRO_WINDOW_MS, help="Micro-window duration (ms)")
    parser.add_argument("--cooldown-ms", type=int, default=COOLDOWN_HORIZON_MS, help="Cooldown horizon (ms)")
    args = parser.parse_args()
    
    # Connect to Redis
    try:
        redis_host = getattr(config, "REDIS_HOST", "localhost") if config else "localhost"
        redis_port = getattr(config, "REDIS_PORT", 6379) if config else 6379
        redis_db = getattr(config, "REDIS_DB", 0) if config else 0
        
        r = wrap_redis_client(redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
        ))
        r.ping()
        logger.info(f"✅ Connected to Redis at {redis_host}:{redis_port}")
        # region agent log
        try:
            import json as _aj
            _ts = int(time.time() * 1000)
            _info = {}
            try:
                _info = r.info() or {}
            except Exception:
                _info = {}
            _kw = {}
            try:
                _kw = getattr(getattr(r, "connection_pool", None), "connection_kwargs", {}) or {}
            except Exception:
                _kw = {}
            _payload = {
                "sessionId": "53deb7",
                "id": f"log_{_ts}_orch_redis_identity",
                "timestamp": _ts,
                "location": "rl/orchestrator_worker.py:main",
                "message": "orch_redis_identity",
                "runId": "post-fix",
                "hypothesisId": "H4",
                "data": {
                    "pid": int(os.getpid()),
                    "redis_host_cfg": str(redis_host),
                    "redis_port_cfg": int(redis_port),
                    "redis_db_cfg": int(redis_db),
                    "redis_host_conn": _kw.get("host"),
                    "redis_port_conn": _kw.get("port"),
                    "redis_db_conn": _kw.get("db"),
                    "redis_server_run_id": _info.get("run_id") if isinstance(_info, dict) else None,
                    "redis_server_tcp_port": _info.get("tcp_port") if isinstance(_info, dict) else None,
                    "redis_version": _info.get("redis_version") if isinstance(_info, dict) else None,
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
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        sys.exit(1)

    # ── SINGLETON LEADER LOCK ───────────────────────────────────────────
    # Prevent duplicate orchestrators (liquidation-class bug: double-publish
    # defeats cadence and can stack conflicting signals).
    ORCH_LOCK_KEY = "orchestrator:leader_lock"
    ORCH_LOCK_TTL = 30  # seconds; renewed every 10s in background
    _orch_lock_id = str(uuid.uuid4())
    acquired = r.set(ORCH_LOCK_KEY, _orch_lock_id, nx=True, ex=ORCH_LOCK_TTL)
    if not acquired:
        existing = r.get(ORCH_LOCK_KEY)
        logger.error(
            f"❌ ORCHESTRATOR_SINGLETON_BLOCKED | Another orchestrator holds the lock "
            f"(lock_value={existing}). Exiting to prevent duplicate publishing."
        )
        sys.exit(1)
    logger.info(f"🔒 Acquired orchestrator leader lock: {_orch_lock_id} (TTL={ORCH_LOCK_TTL}s)")

    # Background thread to renew the lock every 10s
    import threading
    _orch_lock_running = threading.Event()
    _orch_lock_running.set()

    # ── Lua CAS scripts for token-safe lock operations ───────────────
    # Atomic compare-and-set: prevents race where another instance
    # steals the lock between GET and EXPIRE/DELETE.
    _LUA_RENEW = r.register_script(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "  return redis.call('expire', KEYS[1], tonumber(ARGV[2])) "
        "else "
        "  return 0 "
        "end"
    )
    _LUA_RELEASE = r.register_script(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "  return redis.call('del', KEYS[1]) "
        "else "
        "  return 0 "
        "end"
    )

    _renew_fail_streak = [0]  # mutable counter for closure

    def _renew_orch_lock():
        MAX_RENEW_FAILURES = 2  # consecutive failures before self-terminate
        while _orch_lock_running.is_set():
            try:
                # Atomic CAS: renew TTL only if we still own the lock
                renewed = _LUA_RENEW(keys=[ORCH_LOCK_KEY], args=[_orch_lock_id, ORCH_LOCK_TTL])
                if not renewed:
                    logger.error("ORCHESTRATOR_LOCK_LOST | Lock was taken by another instance. Self-terminating.")
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                _renew_fail_streak[0] = 0  # reset on success
            except Exception as e:
                _renew_fail_streak[0] += 1
                logger.error(
                    f"ORCHESTRATOR_LOCK_RENEW_FAIL | streak={_renew_fail_streak[0]}/{MAX_RENEW_FAILURES} | {e}"
                )
                if _renew_fail_streak[0] >= MAX_RENEW_FAILURES:
                    logger.error(
                        "ORCHESTRATOR_LOCK_LOST_EXCEPTION | Redis unreachable for "
                        f"{_renew_fail_streak[0]} consecutive renews. Self-terminating (fail-closed)."
                    )
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
            time.sleep(10)

    _lock_thread = threading.Thread(target=_renew_orch_lock, daemon=True, name="orch-lock-renew")
    _lock_thread.start()

    # Create worker
    worker = OrchestratorWorker(
        redis_client=r,
        shadow_mode=args.shadow,
        micro_window_ms=args.window_ms,
        cooldown_horizon_ms=args.cooldown_ms,
    )
    
    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        worker.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run worker with auto-restart on crash
    MAX_RESTARTS = 10
    BACKOFF_BASE = 2.0
    restart_count = 0
    _graceful_exit = False

    while restart_count <= MAX_RESTARTS and not _graceful_exit:
        try:
            if restart_count > 0:
                backoff = min(60, BACKOFF_BASE ** restart_count)
                logger.warning(
                    f"ORCH_RESTART | attempt={restart_count}/{MAX_RESTARTS} | backoff={backoff:.0f}s"
                )
                time.sleep(backoff)
                # Re-create worker for clean state
                worker = OrchestratorWorker(
                    redis_client=r,
                    shadow_mode=args.shadow,
                    micro_window_ms=args.window_ms,
                    cooldown_horizon_ms=args.cooldown_ms,
                )
                signal.signal(signal.SIGINT, lambda s, f: worker.stop())
                signal.signal(signal.SIGTERM, lambda s, f: worker.stop())
            worker.run()
            _graceful_exit = True
        except (KeyboardInterrupt, SystemExit):
            logger.info("Orchestrator received shutdown signal")
            _graceful_exit = True
        except Exception as e:
            restart_count += 1
            logger.error(
                f"ORCH_CRASH | restart={restart_count}/{MAX_RESTARTS} | error={e}",
                exc_info=True,
            )
            if restart_count > MAX_RESTARTS:
                logger.critical("ORCH_MAX_RESTARTS_EXCEEDED | giving up after %d crashes", MAX_RESTARTS)
        finally:
            try:
                stats = worker.get_stats()
                logger.info(f"Cycle stats: {json.dumps(stats)}")
            except Exception:
                pass

    # Final cleanup: release leader lock
    try:
        _orch_lock_running.clear()
        released = _LUA_RELEASE(keys=[ORCH_LOCK_KEY], args=[_orch_lock_id])
        if released:
            logger.info(f"Released orchestrator leader lock: {_orch_lock_id}")
        else:
            logger.warning("Lock already taken by another instance during shutdown")
    except Exception:
        pass


if __name__ == "__main__":
    main()
