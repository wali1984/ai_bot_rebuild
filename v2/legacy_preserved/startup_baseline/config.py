# WMA AI Bot Configuration - Centralized Live Trading Config
import os
import logging
from dataclasses import dataclass
from typing import List, Dict
from pathlib import Path

# Suppress noisy binance websocket reconnection logs (they auto-reconnect, so these are expected)
# Change from ERROR to WARNING since auto-reconnect handles these
logging.getLogger("binance.ws.reconnecting_websocket").setLevel(logging.WARNING)
logging.getLogger("binance.websocket").setLevel(logging.WARNING)

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        # Avoid noisy stdout spam when imported in many spawned subprocesses (e.g., SubprocVecEnv workers).
        try:
            import multiprocessing as _mp
            _is_main = (_mp.current_process().name == "MainProcess")
        except Exception:
            _is_main = True
        if _is_main:
            print(f"[CONFIG] Loaded environment from {env_path}")
except ImportError:
    try:
        import multiprocessing as _mp
        _is_main = (_mp.current_process().name == "MainProcess")
    except Exception:
        _is_main = True
    if _is_main:
        print("[CONFIG] python-dotenv not installed, using system environment only")


def _read_local_secret(name: str) -> str:
    """Read a secret from a local file (git-ignored) when env vars aren't set."""
    candidates = [
        Path(__file__).parent / 'secrets' / name,
        Path(__file__).parent / 'secrets' / f'{name}.txt',
    ]
    for path in candidates:
        try:
            if path.exists():
                value = path.read_text(encoding='utf-8').strip()
                if value:
                    return value
        except Exception:
            continue
    return ''

def _get_default_device():
    """Auto-detect CUDA device or fallback to CPU"""
    # OOM FIX (2026-04-14): Skip heavy torch import in SubprocVecEnv workers.
    # Workers set CUDA_VISIBLE_DEVICES="" before importing config; the answer
    # is always "cpu" for them, so avoid the 474 MB torch overhead entirely.
    if os.environ.get("CUDA_VISIBLE_DEVICES") == "":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            current_device = torch.cuda.current_device()
            device_name = torch.cuda.get_device_name(current_device)
            try:
                import multiprocessing as _mp
                _is_main = (_mp.current_process().name == "MainProcess")
            except Exception:
                _is_main = True
            if _is_main:
                print(f"[CONFIG] CUDA available: {device_count} devices, using device {current_device} ({device_name})")
            return f"cuda:{current_device}"
        else:
            try:
                import multiprocessing as _mp
                _is_main = (_mp.current_process().name == "MainProcess")
            except Exception:
                _is_main = True
            if _is_main:
                print("[CONFIG] CUDA not available, using CPU")
            return "cpu"
    except ImportError:
        try:
            import multiprocessing as _mp
            _is_main = (_mp.current_process().name == "MainProcess")
        except Exception:
            _is_main = True
        if _is_main:
            print("[CONFIG] PyTorch not available, defaulting to CPU")
        return "cpu"

# TODO: Ensure symbols & timeframes are defined here (Linux unified source of truth)
# Unified trading universe (keep trainer + traders + ingestors in sync)
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","1000SHIBUSDT","DOGEUSDT","ASTERUSDT",
    "LINKUSDT","UNIUSDT","LTCUSDT","WIFUSDT","AVNTUSDT","PIPPINUSDT",
    "1000PEPEUSDT","1000BONKUSDT","FARTCOINUSDT","1000FLOKIUSDT",
    "RIVERUSDT","RAVEUSDT","HIGHUSDT","PENGUUSDT",
    "BARDUSDT","BANKUSDT","AUCTIONUSDT","ALICEUSDT"
]
TIMEFRAMES = ["1m","5m","15m","1h","4h"]  # add "1d" if you want the 6th TF

# Canonical universe enforcement (3-layer safety net)
# - Default allowlist is SYMBOLS above.
# - Optional env override supports emergency narrowing without code changes.
UNIVERSE_ENFORCEMENT_ENABLED = os.getenv("UNIVERSE_ENFORCEMENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
_universe_allowed_env = os.getenv("UNIVERSE_ALLOWED_SYMBOLS", "").strip()
if _universe_allowed_env:
    UNIVERSE_ALLOWED_SYMBOLS = [s.strip().upper() for s in _universe_allowed_env.split(",") if s.strip()]
else:
    UNIVERSE_ALLOWED_SYMBOLS = [str(s).upper() for s in (SYMBOLS or [])]
UNIVERSE_ENFORCE_TRAINER = os.getenv("UNIVERSE_ENFORCE_TRAINER", "true").lower() in ("1", "true", "yes", "on")
UNIVERSE_ENFORCE_ORCHESTRATOR = os.getenv("UNIVERSE_ENFORCE_ORCHESTRATOR", "true").lower() in ("1", "true", "yes", "on")
UNIVERSE_ENFORCE_TRADER = os.getenv("UNIVERSE_ENFORCE_TRADER", "true").lower() in ("1", "true", "yes", "on")

# CoinAnk ingest policy
# - Source of truth lives in config.py (env override supported).
# - When enabled, CoinAnk endpoints that were previously BTC/ETH-only will expand to ALL SYMBOLS.
COINANK_EXPAND_ALL = os.getenv("COINANK_EXPAND_ALL", "true").lower() in ("1", "true", "yes", "on")

# Liquidation bridge / events stream configuration
LIQ_EVENTS_STREAM = os.getenv("LIQ_EVENTS_STREAM", "liquidations:events")
LIQ_SOURCE_BINANCE_FORCE_KEY = os.getenv("LIQ_SOURCE_BINANCE_FORCE_KEY", "binance:force:raw")
LIQ_SOURCE_COINANK_ORDERS_KEY = os.getenv("LIQ_SOURCE_COINANK_ORDERS_KEY", "raw:coinank:liquidation_orders:global")
LIQ_BRIDGE_POLL_INTERVAL_SEC = float(os.getenv("LIQ_BRIDGE_POLL_INTERVAL_SEC", "1.0"))
LIQ_BRIDGE_MAX_BATCH = int(os.getenv("LIQ_BRIDGE_MAX_BATCH", "500"))
LIQ_BRIDGE_DEDUP_TTL_SEC = int(os.getenv("LIQ_BRIDGE_DEDUP_TTL_SEC", str(6 * 3600)))
LIQ_BRIDGE_ENABLED = os.getenv("LIQ_BRIDGE_ENABLED", "true").lower() in ["1", "true", "yes", "on"]

# Learning-only timeframes: Used for feature extraction but NEVER for trading decisions
# These timeframes are excluded from:
# - Signal generation (multi-TF voting)
# - Main timeframe selection
# - Confidence thresholds
# They remain in feature pipeline for model training
LEARNING_TIMEFRAMES = ["1m"]  # 1m is too noisy for trading decisions, but valuable for learning

# ==========================================================================
# INTENT + TIMING + TOXICITY (1m always-on, execution-conditional)
# ==========================================================================
# Operator goal:
# - Catch impulse initiation without naive 1m churn.
# - Keep 1m always-on, but make it incapable of inventing direction.
# - Higher TF (5m/15m/1h/4h) defines INTENT; 1m triggers timing + execution mode.
ENABLE_INTENT_TIMING_STACK = os.getenv("ENABLE_INTENT_TIMING_STACK", "true").lower() in ("1", "true", "yes")

# Which timeframes define intent (direction). These must be a subset of TIMEFRAMES.
INTENT_TIMEFRAMES = [x.strip() for x in os.getenv("INTENT_TIMEFRAMES", "5m,15m,1h").split(",") if x.strip()]

# Timing timeframe used for entries (must exist in TIMEFRAMES). Default: 1m.
TIMING_TIMEFRAME = os.getenv("TIMING_TIMEFRAME", "1m").strip()

# Co-equal deterministic regime/trend prior (as confidence prior + veto, not a direction dictator)
ENABLE_REGIME_PRIOR = os.getenv("ENABLE_REGIME_PRIOR", "true").lower() in ("1", "true", "yes")

# Intent strength gates (soft priors, not hard blocks)
INTENT_MIN_AGREEMENT = float(os.getenv("INTENT_MIN_AGREEMENT", "0.55"))  # 0..1
INTENT_MIN_EFFECTIVE_CONF = float(os.getenv("INTENT_MIN_EFFECTIVE_CONF", "0.82"))  # 0..1

# Allow higher TF to execute entries directly only if ultra-confident (else it only sets intent)
INTENT_ALLOW_DIRECT_ENTRY_ULTRA_CONF = float(os.getenv("INTENT_ALLOW_DIRECT_ENTRY_ULTRA_CONF", "0.90"))
# Fallback: if timing TF has no candidate, allow intent-aligned HTF entry above this confidence.
INTENT_DIRECT_ENTRY_FALLBACK_MIN_CONF = float(os.getenv("INTENT_DIRECT_ENTRY_FALLBACK_MIN_CONF", "0.88"))

# ==========================================================================
# TOXICITY SHIELD (execution mode selection)
# ==========================================================================
ENABLE_TOXICITY_SHIELD = os.getenv("ENABLE_TOXICITY_SHIELD", "true").lower() in ("1", "true", "yes")
TOXICITY_WAIT_THRESHOLD = float(os.getenv("TOXICITY_WAIT_THRESHOLD", "0.75"))  # above -> WAIT_REPRICE
TOXICITY_MAKER_THRESHOLD = float(os.getenv("TOXICITY_MAKER_THRESHOLD", "0.45"))  # above -> maker-only preferred

# Require effective edge after costs to be positive before entry.
EFFECTIVE_EDGE_MIN_MULTIPLE = float(os.getenv("EFFECTIVE_EDGE_MIN_MULTIPLE", "1.2"))

# ==========================================================================
# HEDGE BUDGET GOVERNOR (dynamic, confidence/headroom-driven)
# ==========================================================================
ENABLE_HEDGE_BUDGET_GOVERNOR = os.getenv("ENABLE_HEDGE_BUDGET_GOVERNOR", "true").lower() in ("1", "true", "yes")
HEDGE_MAX_FRACTION_OF_AVAILABLE = float(os.getenv("HEDGE_MAX_FRACTION_OF_AVAILABLE", "0.30"))
HEDGE_MAX_FRACTION_OF_EQUITY = float(os.getenv("HEDGE_MAX_FRACTION_OF_EQUITY", "0.06"))

# ==========================================================================
# REPAIR / DE-RISK MODE (reduce-only exits for liquidation proximity & recovery)
# ==========================================================================
REPAIR_MODE_ENABLED = os.getenv("REPAIR_MODE_ENABLED", "true").lower() in ("1", "true", "yes")
REPAIR_LIQ_DIST_WARN_PCT = float(os.getenv("REPAIR_LIQ_DIST_WARN_PCT", "14.0"))
REPAIR_LIQ_DIST_CUT_PCT = float(os.getenv("REPAIR_LIQ_DIST_CUT_PCT", "10.0"))
REPAIR_LIQ_DIST_PANIC_PCT = float(os.getenv("REPAIR_LIQ_DIST_PANIC_PCT", "7.0"))
REPAIR_LIQ_DIST_CUT_FRACTION = float(os.getenv("REPAIR_LIQ_DIST_CUT_FRACTION", "0.20"))
REPAIR_LIQ_DIST_PANIC_FRACTION = float(os.getenv("REPAIR_LIQ_DIST_PANIC_FRACTION", "0.35"))
REPAIR_HEDGE_BUDGET_FRAC = float(os.getenv("REPAIR_HEDGE_BUDGET_FRAC", "0.35"))
REPAIR_HEDGE_LOSS_CUT_FRACTION = float(os.getenv("REPAIR_HEDGE_LOSS_CUT_FRACTION", "0.25"))
REPAIR_RECOVERY_ROE_PCT = float(os.getenv("REPAIR_RECOVERY_ROE_PCT", "-30.0"))
REPAIR_BREAKEVEN_BUFFER_PCT = float(os.getenv("REPAIR_BREAKEVEN_BUFFER_PCT", "0.05"))
REPAIR_COOLDOWN_SEC = int(os.getenv("REPAIR_COOLDOWN_SEC", "600"))
REPAIR_MAX_REALIZED_LOSS_USD_PER_ACTION = float(os.getenv("REPAIR_MAX_REALIZED_LOSS_USD_PER_ACTION", "25.0"))
REPAIR_LOSS_CAP_BYPASS_LIQ_PCT = float(os.getenv("REPAIR_LOSS_CAP_BYPASS_LIQ_PCT", "6.0"))
REPAIR_PAIR_UNWIND_ENABLED = os.getenv("REPAIR_PAIR_UNWIND_ENABLED", "true").lower() in ("1", "true", "yes")
REPAIR_PAIR_UNWIND_PROFIT_FRACTION = float(os.getenv("REPAIR_PAIR_UNWIND_PROFIT_FRACTION", "1.0"))
REPAIR_REBALANCE_ENABLED = os.getenv("REPAIR_REBALANCE_ENABLED", "true").lower() in ("1", "true", "yes")
REPAIR_MIN_REALIZED_STEP_USD = float(os.getenv("REPAIR_MIN_REALIZED_STEP_USD", "50.0"))

# ==========================================================================
# PROTECTIVE SAFETY CONTRACT (trader-side hard invariants)
# ==========================================================================
PROTECTIVE_NEGATIVE_REALIZED_BLOCK = os.getenv("PROTECTIVE_NEGATIVE_REALIZED_BLOCK", "true").lower() in ("1", "true", "yes")
PAIR_UNWIND_REQUIRED_FOR_LOSS_CLOSE = os.getenv("PAIR_UNWIND_REQUIRED_FOR_LOSS_CLOSE", "true").lower() in ("1", "true", "yes")
LIQ_EMERGENCY_ONLY_FOR_LOSS_CLOSE = os.getenv("LIQ_EMERGENCY_ONLY_FOR_LOSS_CLOSE", "true").lower() in ("1", "true", "yes")
MIN_NET_REALIZED_USD = float(os.getenv("MIN_NET_REALIZED_USD", "25.0"))
MIN_REALIZED_STEP_USD = float(os.getenv("MIN_REALIZED_STEP_USD", "50.0"))
MAX_PROTECTIVE_ACTIONS_PER_SYMBOL_PER_HOUR = int(os.getenv("MAX_PROTECTIVE_ACTIONS_PER_SYMBOL_PER_HOUR", "2"))
MIN_SECONDS_BETWEEN_PROTECTIVE_ACTIONS = int(os.getenv("MIN_SECONDS_BETWEEN_PROTECTIVE_ACTIONS", "1800"))
LIQ_EMERGENCY_DIST_BPS = int(os.getenv("LIQ_EMERGENCY_DIST_BPS", "700"))
MARGIN_EMERGENCY_RATIO = float(os.getenv("MARGIN_EMERGENCY_RATIO", "85.0"))
PROTECTIVE_BATCH_TTL_SEC = int(os.getenv("PROTECTIVE_BATCH_TTL_SEC", "21600"))

# OPEN_RISK budget governor (dynamic downsizer to prevent single-trade margin concentration)
ENABLE_OPEN_RISK_BUDGET_GOVERNOR = os.getenv("ENABLE_OPEN_RISK_BUDGET_GOVERNOR", "true").lower() in ("1", "true", "yes")
OPEN_RISK_MAX_FRACTION_OF_AVAILABLE = float(os.getenv("OPEN_RISK_MAX_FRACTION_OF_AVAILABLE", "0.35"))
OPEN_RISK_MAX_FRACTION_OF_EQUITY = float(os.getenv("OPEN_RISK_MAX_FRACTION_OF_EQUITY", "0.12"))
OPEN_RISK_BUDGET_MIN_SCALE = float(os.getenv("OPEN_RISK_BUDGET_MIN_SCALE", "0.15"))

# ==========================================================================
# HEDGE CAPS + EMERGENCY BYPASS (orchestrator-enforced)
# Default: hedge adds follow the SAME caps as OPEN_RISK.
# Emergency bypass is allowed only under strict conditions and never drains headroom reserve.
# ==========================================================================
HEDGE_HEADROOM_RESERVE_USD = float(os.getenv("HEDGE_HEADROOM_RESERVE_USD", "150.0"))
HEDGE_BYPASS_ENABLED = os.getenv("HEDGE_BYPASS_ENABLED", "true").lower() in ("1", "true", "yes")
HEDGE_BYPASS_MULTIPLIER = float(os.getenv("HEDGE_BYPASS_MULTIPLIER", "1.5"))
EMERGENCY_MARGIN_UTIL_PCT = float(os.getenv("EMERGENCY_MARGIN_UTIL_PCT", "85.0"))
HEDGE_BYPASS_MIN_PDS = float(os.getenv("HEDGE_BYPASS_MIN_PDS", "0.85"))
HEDGE_BYPASS_MIN_NECESSITY_CLASS = int(os.getenv("HEDGE_BYPASS_MIN_NECESSITY_CLASS", "2"))

# ==========================================================================
# MTF HEDGE OVERLAY (additive; disabled by default)
# Uses HTF regime disagreement to downsize LTF entries and attach small hedges.
# ==========================================================================
ENABLE_MTF_HEDGE_OVERLAY = os.getenv("ENABLE_MTF_HEDGE_OVERLAY", "true").lower() in ("1", "true", "yes")
MTF_REGIME_TF = os.getenv("MTF_REGIME_TF", "1h").strip()
MTF_ENTRY_TFS = [x.strip() for x in os.getenv("MTF_ENTRY_TFS", "5m,15m").split(",") if x.strip()]
MTF_BIAS_THRESHOLD = float(os.getenv("MTF_BIAS_THRESHOLD", "0.20"))
MTF_CONFLICT_ENTRY_MULT = float(os.getenv("MTF_CONFLICT_ENTRY_MULT", "0.50"))
MTF_HEDGE_MARGIN_MULT = float(os.getenv("MTF_HEDGE_MARGIN_MULT", "0.30"))
MTF_MAX_HEDGE_MARGIN_USD_PER_SYMBOL = float(os.getenv("MTF_MAX_HEDGE_MARGIN_USD_PER_SYMBOL", "0"))
MTF_MAX_TOTAL_HEDGE_MARGIN_USD = float(os.getenv("MTF_MAX_TOTAL_HEDGE_MARGIN_USD", "0"))

# ==========================================================================
# CHURN VETO (learned filter; trained from our own history)
# ==========================================================================
ENABLE_CHURN_VETO = os.getenv("ENABLE_CHURN_VETO", "true").lower() in ("1", "true", "yes")
CHURN_VETO_MODEL_PATH = os.getenv("CHURN_VETO_MODEL_PATH", "rl/churn_veto_bootstrap.json")
CHURN_VETO_BLOCK_PROB = float(os.getenv("CHURN_VETO_BLOCK_PROB", "0.65"))  # above -> veto to WAIT/Maker
CHURN_VETO_MAKER_ONLY_PROB = float(os.getenv("CHURN_VETO_MAKER_ONLY_PROB", "0.45"))  # above -> maker-only

# ==========================================================================
# PROFIT-ONLY FREESPACE REBALANCER (no-loss compatible)
# ==========================================================================
ENABLE_PROFIT_FREESPACE_REBALANCER = os.getenv("ENABLE_PROFIT_FREESPACE_REBALANCER", "true").lower() in ("1", "true", "yes")
FREESPACE_REBALANCER_MAX_CLOSE_PCT = float(os.getenv("FREESPACE_REBALANCER_MAX_CLOSE_PCT", "0.35"))
FREESPACE_REBALANCER_MIN_WEAKNESS = float(os.getenv("FREESPACE_REBALANCER_MIN_WEAKNESS", "0.55"))

# Base Linux paths for data
DATA_ROOT = "/home/wali/wma-ai-bot/data"                   # <-- Linux path (user writable)
HISTORY_DIR = f"{DATA_ROOT}/history"                       # CCXT historical output
FEATURE_DUMP_DIR = f"{DATA_ROOT}/feature_dumps"            # optional scratch
REDIS_URL = "redis://localhost:6379/0"

# =============================================================================
# LIVE DECISION OUTCOME EVALUATOR (OBSERVE_ONLY, no paper portfolio)
# =============================================================================
# Evaluates trainer decisions against future live prices without placing orders.
DECISION_EVAL_ENABLED = os.getenv("DECISION_EVAL_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DECISION_EVAL_SOURCE_STREAM = os.getenv("DECISION_EVAL_SOURCE_STREAM", "wma:decisions")
DECISION_EVAL_OUTCOME_STREAM = os.getenv("DECISION_EVAL_OUTCOME_STREAM", "wma:decision_outcomes")
DECISION_EVAL_PENDING_ZSET = os.getenv("DECISION_EVAL_PENDING_ZSET", "wma:evaluator:pending")
DECISION_EVAL_LAST_ID_KEY = os.getenv("DECISION_EVAL_LAST_ID_KEY", "wma:evaluator:last_id")
DECISION_EVAL_STREAM_MAXLEN = int(os.getenv("DECISION_EVAL_STREAM_MAXLEN", "50000"))
DECISION_EVAL_POLL_SECONDS = float(os.getenv("DECISION_EVAL_POLL_SECONDS", "1.0"))
DECISION_EVAL_BATCH_SIZE = int(os.getenv("DECISION_EVAL_BATCH_SIZE", "250"))
DECISION_EVAL_HORIZONS_SECONDS = [
    int(x.strip()) for x in os.getenv("DECISION_EVAL_HORIZONS_SECONDS", "60,300,900,3600").split(",") if x.strip()
]

# Decision coverage sweep (emit skip reasons for symbol×timeframe gaps in decision telemetry)
DECISION_COVERAGE_SWEEP_SECONDS = float(os.getenv("DECISION_COVERAGE_SWEEP_SECONDS", "30"))
DECISION_FEATURE_STALE_SECONDS = int(os.getenv("DECISION_FEATURE_STALE_SECONDS", "300"))

# Trainer/risk knobs - BALANCED SETTINGS (Post-Emergency Correction)
# NOTE: SIGNAL_CONFIDENCE_MIN is for TRAINER to publish
#       MIN_TRADING_CONFIDENCE is for TRADER to filter execution

# FIX Feb 26 2026: With entropy penalty multiplier = sqrt(norm_entropy), collapsed
# entropy (0.08) → penalty = 0.30 → max achievable confidence = raw * 0.30 ≈ 0.27.
# Even with auto-tau fix, 0.70 threshold is UNREACHABLE until entropy recovers.
# Lower thresholds temporarily; raise back to 0.65/0.70 once entropy > 0.50.
SIGNAL_CONFIDENCE_MIN = 0.50  # Trainer publishes signals at 50%+ (was 0.65 — unreachable with collapsed entropy)
MIN_TRADING_CONFIDENCE = float(os.getenv("MIN_TRADING_CONFIDENCE", "0.45"))  # Honest confidence scale: top1=0.55→conf=0.48, top1=0.70→conf=0.65  # FIX Apr 14: configurable via .env. Multi-layer protection (orchestrator, deconfliction, risk budget) now gates quality
MIN_TRADING_CONFIDENCE_MAJOR = float(os.getenv("MIN_TRADING_CONFIDENCE_MAJOR", "0.35"))  # Honest: top1=0.45→conf=0.36 for BTC/ETH/SOL  # Lower threshold for BTC/ETH/SOL (smaller moves → lower model confidence)
MAJOR_SYMBOLS_SET = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
MIN_TRADING_CONFIDENCE_HEDGE_DCA = float(os.getenv("MIN_TRADING_CONFIDENCE_HEDGE_DCA", "0.20"))  # Honest: hedges are protective, low bar
MIN_CLOSE_CONFIDENCE = 0.60  # 60% for profit-taking and risk management (was 0.85)
MIN_FLIP_CONFIDENCE = 0.85  # 85% confidence required to flip positions (was 0.97)

# TRADING FEES AND COSTS (Critical for accurate PnL calculations)
# Binance Futures default fees: Maker 0.02%, Taker 0.05%
# VIP levels can be lower, adjust via env vars
MAKER_FEE_PCT = float(os.getenv("MAKER_FEE_PCT", "0.02"))   # 0.02% maker fee
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.05"))   # 0.05% taker fee
# Round-trip cost = entry + exit.
# CRITICAL: Maker-first execution is the default, so use maker round-trip cost as the default baseline.
ROUND_TRIP_FEE_PCT = float(os.getenv("ROUND_TRIP_FEE_PCT", str(max(0.0, float(MAKER_FEE_PCT) * 2.0))))  # % of notional
# Minimum profit threshold AFTER fees (percent-of-notional, NOT ROE).
# Keep as an operator override (fallback); dynamic fee-aware gating may compute a stricter value under micro pressure.
MIN_NET_PROFIT_PCT = float(os.getenv("MIN_NET_PROFIT_PCT", str(ROUND_TRIP_FEE_PCT)))

# -----------------------------------------------------------------------------
# Micro-position (dust) cleanup (profit-only; no-loss safe)
# -----------------------------------------------------------------------------
MICRO_POSITION_CLEANUP_ENABLED = os.getenv("MICRO_POSITION_CLEANUP_ENABLED", "true").lower() in ("1", "true", "yes")
# CRITICAL (Jan 2026): Dust must be defined by **margin used**, not notional.
# A high-leverage leg can have large notional but tiny margin; the operational constraint is margin.
MICRO_POSITION_MIN_LEG_MARGIN_USD = float(os.getenv("MICRO_POSITION_MIN_LEG_MARGIN_USD", "5.0"))
# Backward-compat (deprecated): legacy notional-based dust threshold.
MICRO_POSITION_MIN_LEG_NOTIONAL_USD = float(os.getenv("MICRO_POSITION_MIN_LEG_NOTIONAL_USD", "5.0"))
# How often traders scan for dust legs.
MICRO_POSITION_CLEANUP_INTERVAL_SECONDS = int(float(os.getenv("MICRO_POSITION_CLEANUP_INTERVAL_SECONDS", "90") or 90))
# Require profit (after fees) before closing dust legs.
MICRO_POSITION_CLEANUP_MIN_NET_PROFIT_USD = float(os.getenv("MICRO_POSITION_CLEANUP_MIN_NET_PROFIT_USD", "0.10"))
MICRO_POSITION_CLEANUP_MIN_NET_PROFIT_PCT = float(os.getenv("MICRO_POSITION_CLEANUP_MIN_NET_PROFIT_PCT", "0.05"))

# ========================================================================
# STACKING / PAIR MARGIN CAPS (Jan 2026)
# Controls max margin per symbol pair (LONG + SHORT combined)
# Applies to OPEN signals with stacking AND to hedge signals
# ========================================================================
STACK_OPEN_MIN_CONFIDENCE = float(os.getenv("STACK_OPEN_MIN_CONFIDENCE", "0.93"))  # Min confidence to allow stacking
STACK_OPEN_MAX_MARGIN_USD = float(os.getenv("STACK_OPEN_MAX_MARGIN_USD", "800.0"))  # Max $800 per pair (aggressive sizing)
STACK_OPEN_MAX_EQUITY_PCT = float(os.getenv("STACK_OPEN_MAX_EQUITY_PCT", "0.10"))   # Max 10% of equity per pair (default)

# Tier-3 pair cap overrides (operator request): hard cap for Tier-3 symbols
TIER3_SYMBOLS = ["LTCUSDT", "ASTERUSDT"]
TIER3_PAIR_CAP_MAX_USD = float(os.getenv("TIER3_PAIR_CAP_MAX_USD", "200.0"))

# Manual-position hedge cap extension (operator request):
# If a manual leg already exceeds the base cap, allow hedges up to 50% equity.
MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED = os.getenv("MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED", "true").lower() in ("true", "1", "yes")
MANUAL_HEDGE_PAIR_CAP_EQUITY_PCT = float(os.getenv("MANUAL_HEDGE_PAIR_CAP_EQUITY_PCT", "0.50"))
# Symbols excluded from manual override (BTC/ETH remain strict)
MANUAL_HEDGE_PAIR_CAP_EXCLUDE_SYMBOLS = []  # FIX Apr 15: removed BTC/ETH exclusion — all symbols can use manual hedge pair cap
# Redis key prefix for per-leg origin markers (system/manual)
POSITION_ORIGIN_KEY_PREFIX = os.getenv("POSITION_ORIGIN_KEY_PREFIX", "wma:position_origin")

# ========================================================================
# PER-ACCOUNT PAIR CAPS (Jan 24, 2026)
# Independent margin caps for each trader account (primary/asjad)
# Format: {account_id: {"max_margin_usd": float, "max_equity_pct": float}}
# If an account is not listed, falls back to default STACK_OPEN_MAX_* values
# ========================================================================
_PAIR_CAP_PRIMARY_USD = float(os.getenv("PAIR_CAP_PRIMARY_USD", "300.0"))
_PAIR_CAP_PRIMARY_PCT = float(os.getenv("PAIR_CAP_PRIMARY_PCT", "0.10"))
_PAIR_CAP_ASJAD_USD = float(os.getenv("PAIR_CAP_ASJAD_USD", "300.0"))
_PAIR_CAP_ASJAD_PCT = float(os.getenv("PAIR_CAP_ASJAD_PCT", "0.10"))

PER_ACCOUNT_PAIR_CAPS = {
    "primary": {"max_margin_usd": _PAIR_CAP_PRIMARY_USD, "max_equity_pct": _PAIR_CAP_PRIMARY_PCT},
    "asjad": {"max_margin_usd": _PAIR_CAP_ASJAD_USD, "max_equity_pct": _PAIR_CAP_ASJAD_PCT},
}

# Dynamic pair cap boost for SHIELD-mode hedges (high PDS signals)
# When hedge_necessity_class >= 2 or PDS >= threshold, allow larger pair cap
PAIR_CAP_SHIELD_BOOST_ENABLED = os.getenv("PAIR_CAP_SHIELD_BOOST_ENABLED", "true").lower() in ("true", "1", "yes")
PAIR_CAP_SHIELD_BOOST_FACTOR = float(os.getenv("PAIR_CAP_SHIELD_BOOST_FACTOR", "1.5"))  # 50% boost for SHIELD hedges

# Hedge total margin caps:
# - Base hedge utilization cap is MAX_MARGIN_UTIL_HEDGE_PCT (legacy, in %).
# - Under margin pressure, we allow a bounded dynamic expansion up to MAX_MARGIN_UTIL_HEDGE_PCT_MAX
#   for *protective hedges* (HEDGE_V2), relying on hedge budget downsizing to keep increments small.
MAX_MARGIN_UTIL_HEDGE_PCT_MAX = float(os.getenv("MAX_MARGIN_UTIL_HEDGE_PCT_MAX", "85"))  # hard ceiling for hedged books

# ============================================================================
# ANTI-CHURN / FEE EFFICIENCY CONTROLS (ENHANCED Dec 28, 2025)
# ============================================================================
# Problem: 7,461 orders over 7 days = ~1,066 orders/day = ~44 orders/hour
# At $500 avg notional × 0.05% taker = $0.25/trade × 7,461 = $1,865 in fees
# If PnL was only $124, that's 1500% fee ratio (fees >> profits)
#
# Solution: Gate entries based on fee efficiency, position consolidation, maker orders

# ============================================================================
# OPTION 2: ADAPTIVE EDGE GATE (Quality Filter) - FULLY DYNAMIC
# ============================================================================
# NO STATIC THRESHOLDS - All values derived from LIVE market data:
# - ATR/Volatility → Expected move size (from unified_features:{symbol}:{tf})
# - Orderbook spread/depth → Actual execution costs (from orderbook:top:{symbol})
# - Liquidation proximity → Squeeze potential (from liquidation data)
# - OI/Funding → Trend strength (from CoinAnk features)
# - Microstructure → Execution quality (from msnap:coinapi_wsds:{symbol})
#
# Liquidity tier thresholds (depth in USD). Defaults are conservative and configurable.
# Tiers are derived in trainer by symbol rules (majors, 1000-prefixed, TIER3_SYMBOLS, fallback mid).
LIQUIDITY_HARD_MIN_DEPTH_USD = float(os.getenv("LIQUIDITY_HARD_MIN_DEPTH_USD", "10000"))

LIQUIDITY_MIN_DEPTH_USD_MAJOR = float(os.getenv("LIQUIDITY_MIN_DEPTH_USD_MAJOR", "250000"))
LIQUIDITY_WARN_DEPTH_USD_MAJOR = float(os.getenv("LIQUIDITY_WARN_DEPTH_USD_MAJOR", "500000"))

LIQUIDITY_MIN_DEPTH_USD_LARGE = float(os.getenv("LIQUIDITY_MIN_DEPTH_USD_LARGE", "100000"))
LIQUIDITY_WARN_DEPTH_USD_LARGE = float(os.getenv("LIQUIDITY_WARN_DEPTH_USD_LARGE", "250000"))

LIQUIDITY_MIN_DEPTH_USD_MID = float(os.getenv("LIQUIDITY_MIN_DEPTH_USD_MID", "50000"))
LIQUIDITY_WARN_DEPTH_USD_MID = float(os.getenv("LIQUIDITY_WARN_DEPTH_USD_MID", "100000"))

LIQUIDITY_MIN_DEPTH_USD_SMALL = float(os.getenv("LIQUIDITY_MIN_DEPTH_USD_SMALL", "10000"))
LIQUIDITY_WARN_DEPTH_USD_SMALL = float(os.getenv("LIQUIDITY_WARN_DEPTH_USD_SMALL", "75000"))

# The adaptive gate (trading/adaptive_edge_gate.py) computes:
#   Expected Edge = f(ATR, momentum, squeeze_potential, confidence_capture)
#   Required Edge = f(live_spread, depth_adjusted_slippage, fees) × dynamic_buffer
#   Trade only when: Expected Edge > Required Edge
#
# Fallback values below are ONLY used if live data unavailable
EDGE_GATE_ENABLED = os.getenv("EDGE_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
MIN_EDGE_MULTIPLE = float(os.getenv("MIN_EDGE_MULTIPLE", "1.5"))  # FALLBACK: Base safety buffer (adaptive adjusts this)
# Legacy static values - DEPRECATED, kept for backward compatibility only
MIN_EDGE_PCT = float(os.getenv("MIN_EDGE_PCT", "0.15"))  # DEPRECATED: Now computed from ATR
SPREAD_COST_BPS = float(os.getenv("SPREAD_COST_BPS", "3.0"))  # DEPRECATED: Now from live orderbook
SLIPPAGE_BPS = float(os.getenv("SLIPPAGE_BPS", "2.0"))  # DEPRECATED: Now computed from depth

# ============================================================================
# OPTION 3: ADAPTIVE MAKER-FIRST EXECUTION STRATEGY  
# ============================================================================
# Intelligent order type selection based on live market conditions:
# - Spread width → Use maker if spread tight enough to profit from rebate
# - Orderbook depth → Use maker if enough depth for fill probability
# - Volatility → Use taker in high vol (price may move before fill)
# - Signal freshness → Use taker for stale signals
#
# Decision logic (trading/maker_execution.py):
#   Use MAKER (limit) if: spread < ATR/10 AND depth > 2x order AND vol < 3% AND signal_age < 10s
#   Use TAKER (market) if: PROTECTIVE action OR confidence > dynamic_threshold OR conditions unfavorable
MAKER_FIRST_ENABLED = os.getenv("MAKER_FIRST_ENABLED", "true").lower() in ("1", "true", "yes")
# Fallback values - ONLY used if live orderbook data unavailable
MAKER_CONFIDENCE_THRESHOLD = float(os.getenv("MAKER_CONFIDENCE_THRESHOLD", "0.95"))  # FALLBACK: Use taker above this
# Enforce minimums so legacy .env values (30s/4 attempts) don't silently reintroduce cancellation churn.
try:
    _maker_wait_env = int(os.getenv("MAKER_WAIT_TIMEOUT_SECONDS", "120"))
except Exception:
    _maker_wait_env = 120
try:
    _maker_attempts_env = int(os.getenv("MAKER_REPRICE_ATTEMPTS", "5"))
except Exception:
    _maker_attempts_env = 5
# FIXED: Removed max(120, ...) and max(5, ...) clamps that silently ignored .env overrides.
# 5 maker attempts × 25s each = 125s total. If all 5 fail, taker fallback at trainer target_price.
MAKER_WAIT_TIMEOUT_SECONDS = max(10, _maker_wait_env)  # Total wait budget for maker ladder (min 10s safety)
MAKER_REPRICE_ATTEMPTS = max(1, _maker_attempts_env)  # Number of post-only reprices before taker fallback (min 1)
MAKER_REPRICE_ATTEMPTS_OPEN = int(os.getenv("MAKER_REPRICE_ATTEMPTS_OPEN", "3"))
MAKER_REPRICE_ATTEMPTS_REDUCE = int(os.getenv("MAKER_REPRICE_ATTEMPTS_REDUCE", "3"))  # Was 1 — give limit orders 3 attempts before taker fallback
FAST_EXIT_IN_STRESS = os.getenv("FAST_EXIT_IN_STRESS", "false").lower() in ("1", "true", "yes")  # Disabled: maker-first even in stress (avoid unnecessary taker fees)
# Price offset: higher value = more aggressive limit pricing = better fill rate but still maker
# 3 bps (0.03%) is still well within spread for most symbols and gets fills more reliably
MAKER_PRICE_OFFSET_BPS = float(os.getenv("MAKER_PRICE_OFFSET_BPS", "3.0"))  # Limit price offset from mid (was 1.0)
MAKER_ORDERBOOK_STALE_SECONDS = int(os.getenv("MAKER_ORDERBOOK_STALE_SECONDS", "5"))  # Treat Redis top-of-book older than this as stale
MAKER_ALLOW_MARKET_FALLBACK = os.getenv("MAKER_ALLOW_MARKET_FALLBACK", "true").lower() in ("1", "true", "yes")

# ============================================================================
# NEXT-CYCLE SIGNAL VALIDATION (Anti-squeeze / anti-crowd trap)
# ============================================================================
# Goal: prevent acting on a single-cycle "crowded" prediction that often gets
# reversed by a quick squeeze. Signals are staged once, then must pass a
# next-cycle validation before publishing to traders.
#
# Safety:
# - HEDGE + loss-cut PROTECTIVE exits are not delayed by default
# - OPEN_RISK + FLIP are delayed/validated
SIGNAL_NEXT_CYCLE_VALIDATION_ENABLED = os.getenv("SIGNAL_NEXT_CYCLE_VALIDATION_ENABLED", "true").lower() in ("1", "true", "yes")
SIGNAL_VALIDATION_PENDING_TTL_SECONDS = int(os.getenv("SIGNAL_VALIDATION_PENDING_TTL_SECONDS", "60"))  # Pending expires quickly
SIGNAL_VALIDATION_MIN_AGE_SECONDS = float(os.getenv("SIGNAL_VALIDATION_MIN_AGE_SECONDS", "4"))  # Prevent same-cycle double publish

# Apply to ALL signals (except HEARTBEAT/no-op) by default, per operator request.
# When true, the trainer stages *all* actionable signals for next-cycle validation.
# Default OFF to avoid starving publication in noisy regimes; can be enabled via env.
SIGNAL_VALIDATE_ALL_NEXT_CYCLE = os.getenv("SIGNAL_VALIDATE_ALL_NEXT_CYCLE", "false").lower() in ("1", "true", "yes")

# Which categories/types to validate
SIGNAL_VALIDATE_OPEN_RISK_NEXT_CYCLE = os.getenv("SIGNAL_VALIDATE_OPEN_RISK_NEXT_CYCLE", "true").lower() in ("1", "true", "yes")
SIGNAL_VALIDATE_FLIP_NEXT_CYCLE = os.getenv("SIGNAL_VALIDATE_FLIP_NEXT_CYCLE", "true").lower() in ("1", "true", "yes")
SIGNAL_VALIDATE_PROFIT_CLOSE_NEXT_CYCLE = os.getenv("SIGNAL_VALIDATE_PROFIT_CLOSE_NEXT_CYCLE", "true").lower() in ("1", "true", "yes")
SIGNAL_VALIDATE_PROFIT_CLOSE_MIN_PNL_PCT = float(os.getenv("SIGNAL_VALIDATE_PROFIT_CLOSE_MIN_PNL_PCT", "0.0"))

# Optional microstructure-based delay extension (CoinAPI msnap)
SIGNAL_VALIDATION_SNAPBACK_THRESHOLD = float(os.getenv("SIGNAL_VALIDATION_SNAPBACK_THRESHOLD", "0.60"))
SIGNAL_VALIDATION_MM_SCORE_THRESHOLD = float(os.getenv("SIGNAL_VALIDATION_MM_SCORE_THRESHOLD", "0.70"))
SIGNAL_VALIDATION_DELAY_ON_FLASH_MOVE = os.getenv("SIGNAL_VALIDATION_DELAY_ON_FLASH_MOVE", "true").lower() in ("1", "true", "yes")

# ============================================================================
# NO-LOSS EXIT GUARD (HEDGE-FIRST CONTRACT)
# ============================================================================
# When enabled, the trainer will NOT publish exposure-controller CLOSE_* signals that would
# realize a loss on the selected leg. Instead it will HOLD/hedge (per runbook design: hedge
# losers; take profits on winners).
NO_LOSS_EXIT_GUARD_ENABLED = os.getenv("NO_LOSS_EXIT_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")  # FIX Apr 14: Re-enabled (was false since Apr 7)
# Fix Q (Feb 2026): Deep-loss bypass.  If a leg's PnL drops below this floor,
# the no-loss guard steps aside so the trainer's EXIT-DECISION / PARTIAL_CLOSE
# can unwind the position instead of trapping it forever.
# Also applies to PARTIAL_CLOSE actions that explicitly reduce exposure on
# underwater positions — these are protective by nature.
NO_LOSS_GUARD_DEEP_LOSS_BYPASS_PCT = float(os.getenv("NO_LOSS_GUARD_DEEP_LOSS_BYPASS_PCT", "-5.0"))  # FIX Apr 14: -3→-5% (tighter; -3% was too loose at 50-100x leverage)
NO_LOSS_GUARD_ALLOW_PARTIAL_CLOSE = os.getenv("NO_LOSS_GUARD_ALLOW_PARTIAL_CLOSE", "true").lower() in ("1", "true", "yes")

# Ultra-high confidence bypass: skip no-loss guard when trainer is very confident
# Mar 20 2026: Re-enabled — loss closes allowed when trainer+market confirm direction.
# Previous $68/hr losses were caused by MANAGE_BYPASS bug (flips bypassing risk gates),
# not by this feature. Threshold raised from 0.92→0.85 (requires genuine high confidence).
ULTRA_CONF_NO_LOSS_BYPASS_ENABLED = os.getenv("ULTRA_CONF_NO_LOSS_BYPASS_ENABLED", "false").lower() in ("1", "true", "yes")  # STAYS OFF — was bleed vector
ULTRA_CONF_NO_LOSS_BYPASS_THRESHOLD = float(os.getenv("ULTRA_CONF_NO_LOSS_BYPASS_THRESHOLD", "0.95"))  # FIX Apr 14: 0.85→0.95 (if ever re-enabled, require near-certainty)

# ── BREAKOUT LOSS ACCEPTANCE ────────────────────────────────────────────────
# During confirmed breakouts (one-directional move, no reversal), the no-loss
# hedge-only strategy accumulates losses on both legs.  Allow a controlled
# loss-realizing close when ALL strict conditions are met simultaneously.
#
# HIGH-LEVERAGE NOTE (50x-100x):
#   -8% ROE = 0.08-0.16% price move (noise at 100x) — too tight.
#   -40% ROE = 0.4-0.8% price move — meaningful, not just a swing.
#   -70% ROE = 0.7-1.4% price move — serious, approaching danger.
# Thresholds are in ROE% space, NOT price space.
#
# TF REQUIREMENT: Requires 1h+ regime alignment to confirm real breakout.
# A 5m "trending" regime alone can be noise; 1h alignment is structural.
BREAKOUT_LOSS_ACCEPT_ENABLED = os.getenv("BREAKOUT_LOSS_ACCEPT_ENABLED", "true").lower() in ("true", "1", "yes")
BREAKOUT_LOSS_ACCEPT_MIN_LOSS_PCT = float(os.getenv("BREAKOUT_LOSS_ACCEPT_MIN_LOSS_PCT", "-40.0"))
BREAKOUT_LOSS_ACCEPT_MAX_LOSS_PCT = float(os.getenv("BREAKOUT_LOSS_ACCEPT_MAX_LOSS_PCT", "-70.0"))
BREAKOUT_LOSS_ACCEPT_MIN_DURATION_SEC = int(os.getenv("BREAKOUT_LOSS_ACCEPT_MIN_DURATION_SEC", "900"))
BREAKOUT_LOSS_ACCEPT_COOLDOWN_SEC = int(os.getenv("BREAKOUT_LOSS_ACCEPT_COOLDOWN_SEC", "1800"))
BREAKOUT_LOSS_ACCEPT_REGIMES = [r.strip().lower() for r in os.getenv(
    "BREAKOUT_LOSS_ACCEPT_REGIMES", "trending,trending_volatile,trending_bullish,trending_bearish"
).split(",") if r.strip()]
BREAKOUT_LOSS_ACCEPT_HTF_CONFIRM_TFS = [tf.strip() for tf in os.getenv(
    "BREAKOUT_LOSS_ACCEPT_HTF_CONFIRM_TFS", "1h,4h"
).split(",") if tf.strip()]
BREAKOUT_LOSS_ACCEPT_HEDGE_MIN_LOSS_PCT = float(os.getenv("BREAKOUT_LOSS_ACCEPT_HEDGE_MIN_LOSS_PCT", "-5.0"))

# ============================================================================
# ADAPTIVE THRESHOLD ENGINE (Apr 14 2026)
# ============================================================================
# When enabled, ALL loss/kill/hedge thresholds are computed dynamically from
# real-time ATR, liquidation distances, orderbook imbalance, CoinAPI microstructure,
# and funding rates. Static config values become FALLBACKS only.
# Kill switch: set to false to revert to static config defaults.
ADAPTIVE_THRESHOLDS_ENABLED = os.getenv("ADAPTIVE_THRESHOLDS_ENABLED", "true").lower() in ("1", "true", "yes")

# ============================================================================
# OPTION 4: POSITION SIZING CONSOLIDATION
# ============================================================================
# Fewer, larger trades instead of many small ones = same exposure, fewer fees
# Target: 1/3 the trades, 1/3 the fees
MIN_POSITION_SIZE_PCT = float(os.getenv("MIN_POSITION_SIZE_PCT", "2.0"))  # Min 2% equity per trade (lowered: 5% per-symbol cap requires smaller min)
MAX_TRADES_PER_SYMBOL_PER_DAY = int(os.getenv("MAX_TRADES_PER_SYMBOL_PER_DAY", "6"))  # Max 6 round-trips per symbol per day
CONSOLIDATE_SIGNALS = os.getenv("CONSOLIDATE_SIGNALS", "true").lower() in ("1", "true", "yes")

# ============================================================================
# OPTION 5: ADAPTIVE HOLD TIME REWARD SHAPING - FULLY DYNAMIC
# ============================================================================
# NO STATIC HOLD TIMES - All derived from live market conditions:
# - ATR → Base hold time (high vol = shorter optimal hold, low vol = longer)
# - Momentum strength → Hold multiplier (strong trend = hold longer)
# - Squeeze potential → Hold multiplier (squeeze building = hold longer)
#
# Formula: optimal_hold = (40 / ATR_pct) × momentum_mult × squeeze_mult
# Example: ATR 2% = 20min base, ATR 0.5% = 80min base
#
# Reward modifiers adapt to conditions:
# - Quick exit (< 50% of optimal): 0.3 to 0.7 penalty
# - Short hold (50-100% of optimal): 0.7 to 1.0 recovery
# - Long profitable hold (>100% optimal): 1.0 to 1.2 bonus
HOLD_TIME_SHAPING_ENABLED = os.getenv("HOLD_TIME_SHAPING_ENABLED", "true").lower() in ("1", "true", "yes")
# Fallback values - ONLY used if adaptive controller cannot fetch market data
QUICK_FLIP_PENALTY = float(os.getenv("QUICK_FLIP_PENALTY", "0.3"))  # FALLBACK: Base quick flip penalty
HOLD_BONUS_MAX_PCT = float(os.getenv("HOLD_BONUS_MAX_PCT", "0.20"))  # FALLBACK: Max hold bonus
# DEPRECATED static values - Now computed from ATR
HOLD_BONUS_START_MINUTES = int(os.getenv("HOLD_BONUS_START_MINUTES", "30"))  # DEPRECATED: Now from ATR
HOLD_BONUS_MAX_HOURS = float(os.getenv("HOLD_BONUS_MAX_HOURS", "2.0"))  # DEPRECATED: Now adaptive

# FEE-TO-PROFIT RATIO GATE: Block new entries if fees exceed profit threshold
# Tracks rolling 1-hour window of fees vs realized PnL
# If fee_ratio > MAX_FEE_TO_PROFIT_RATIO, block OPEN_RISK entries
MAX_FEE_TO_PROFIT_RATIO = float(os.getenv("MAX_FEE_TO_PROFIT_RATIO", "0.40"))  # Fees < 40% of profits (was 50%)
FEE_RATIO_ENABLED = os.getenv("FEE_RATIO_ENABLED", "true").lower() in ("1", "true", "yes")  # RE-ENABLED: data-driven gate using real Binance income API

# FEE RATIO REWARD SHAPING: Train models to be fee-aware
# When fee ratio is high, penalize rewards for OPEN_RISK actions to teach model to trade less
# This helps PPO and MASA learn that trading in high-fee states is unprofitable
FEE_RATIO_REWARD_SHAPING_ENABLED = os.getenv("FEE_RATIO_REWARD_SHAPING_ENABLED", "true").lower() in ("1", "true", "yes")
FEE_RATIO_WARNING_THRESHOLD = float(os.getenv("FEE_RATIO_WARNING_THRESHOLD", "0.30"))   # 30% - mild penalty
FEE_RATIO_HIGH_THRESHOLD = float(os.getenv("FEE_RATIO_HIGH_THRESHOLD", "0.50"))        # 50% - moderate penalty
FEE_RATIO_CRITICAL_THRESHOLD = float(os.getenv("FEE_RATIO_CRITICAL_THRESHOLD", "0.80")) # 80% - severe penalty

# TRADE THROTTLING: Maximum trades per symbol per hour
# CRITICAL: Enable to stop churning when fee ratio > 100%
# Set TRADE_THROTTLE_ENABLED=true to enforce hard limits
TRADE_THROTTLE_ENABLED = os.getenv("TRADE_THROTTLE_ENABLED", "true").lower() in ("1", "true", "yes")  # ENABLED - critical for fee control
MAX_TRADES_PER_SYMBOL_PER_HOUR = int(os.getenv("MAX_TRADES_PER_SYMBOL_PER_HOUR", "3"))  # FIX Apr 16: 6→3. Audit showed 629 fills/10h = death by fees ($114). Need 60 fills max.
MAX_TRADES_GLOBAL_PER_HOUR = int(os.getenv("MAX_TRADES_GLOBAL_PER_HOUR", "40"))  # Doubled to 40 trades/hour across all symbols

# MINIMUM HOLD TIME: Prevent immediate exits that generate fees without capturing moves
# Average hold time should be > MIN_HOLD_MINUTES to be profitable after fees
MIN_HOLD_MINUTES = int(os.getenv("MIN_HOLD_MINUTES", "30"))  # Hold at least 30 min (was 20) — prevents fee-destroying rapid exits
MIN_INTERVAL_BETWEEN_TRADES_SECONDS = int(os.getenv("MIN_INTERVAL_BETWEEN_TRADES_SECONDS", "600"))  # 10 min between same-symbol trades (was 5 min)

# LEGACY: Hourly fee budget (deprecated, use fee ratio instead)
HOURLY_FEE_BUDGET_USD = float(os.getenv("HOURLY_FEE_BUDGET_USD", "100.0"))  # Doubled to $100/hour max
FEE_BUDGET_ENABLED = os.getenv("FEE_BUDGET_ENABLED", "false").lower() in ("1", "true", "yes")  # Disabled - use SignalStateManager

# ============================================================================
# DAILY FEE BUDGET CIRCUIT BREAKER (AUDIT 12/30 - Priority 0)
# ============================================================================
# Goal: Prevent "death by a thousand fees" - stop trading when fee budget exceeded
# Enforcement: Trainer blocks OPEN_RISK when exceeded, trader final enforcement
# When triggered: Only PROTECTIVE exits allowed, no new OPEN_RISK
DAILY_FEE_BUDGET_USD = float(os.getenv("DAILY_FEE_BUDGET_USD", "120.0"))  # Doubled to $120/day
DAILY_FEE_BUDGET_PCT_EQUITY = float(os.getenv("DAILY_FEE_BUDGET_PCT_EQUITY", "16.0"))  # Doubled to 16% of equity/day
DYNAMIC_BUDGET_ENABLED = os.getenv("DYNAMIC_BUDGET_ENABLED", "true").lower() in ("1", "true", "yes")
DYNAMIC_FEE_BUDGET_BASE_PCT = float(os.getenv("DYNAMIC_FEE_BUDGET_BASE_PCT", "20.0"))  # Doubled to 20% of equity as base fee budget
DYNAMIC_FEE_BUDGET_PNL_REINVEST_PCT = float(os.getenv("DYNAMIC_FEE_BUDGET_PNL_REINVEST_PCT", "30.0"))  # reinvest 30% of profit into fees
DYNAMIC_FEE_BUDGET_FLOOR_USD = float(os.getenv("DYNAMIC_FEE_BUDGET_FLOOR_USD", "200.0"))  # Doubled to min $200/day
DYNAMIC_FEE_BUDGET_CEILING_PCT = float(os.getenv("DYNAMIC_FEE_BUDGET_CEILING_PCT", "32.0"))  # Doubled to max 32% of equity
DAILY_FEE_BUDGET_ENABLED = os.getenv("DAILY_FEE_BUDGET_ENABLED", "true").lower() in ("1", "true", "yes")
DAILY_FEE_BUDGET_BLOCK_MODE = os.getenv("DAILY_FEE_BUDGET_BLOCK_MODE", "OPEN_RISK_ONLY")  # Block only OPEN_RISK, allow PROTECTIVE

# Optional manual override (operator-controlled, TTL-based).
# Requires BOTH:
#  1) DAILY_FEE_BUDGET_OVERRIDE_ENABLED=true
#  2) Redis key set (example): redis-cli SETEX wma:override:daily_fee_budget:asjad 600 1
DAILY_FEE_BUDGET_OVERRIDE_ENABLED = os.getenv("DAILY_FEE_BUDGET_OVERRIDE_ENABLED", "false").lower() in ("1", "true", "yes")
DAILY_FEE_BUDGET_OVERRIDE_KEY_PREFIX = os.getenv("DAILY_FEE_BUDGET_OVERRIDE_KEY_PREFIX", "wma:override:daily_fee_budget")

# ============================================================================
# DAILY TRADE BUDGET (AUDIT 12/30 - Stop hyperactive mode)
# ============================================================================
# Goal: Max 50 trades/day to prevent churn that burns fees
DAILY_TRADE_BUDGET = int(os.getenv("DAILY_TRADE_BUDGET", "120"))  # Doubled to 120/day
DYNAMIC_TRADE_BUDGET_BASE = int(os.getenv("DYNAMIC_TRADE_BUDGET_BASE", "200"))  # Doubled to 200
DYNAMIC_TRADE_BUDGET_FLOOR = int(os.getenv("DYNAMIC_TRADE_BUDGET_FLOOR", "160"))  # Doubled to 160
DYNAMIC_TRADE_BUDGET_CEILING = int(os.getenv("DYNAMIC_TRADE_BUDGET_CEILING", "800"))  # Doubled to 800
# ENABLED: Prevents hyperactive churn mode that burns fees
DAILY_TRADE_BUDGET_ENABLED = os.getenv("DAILY_TRADE_BUDGET_ENABLED", "true").lower() in ("1", "true", "yes")

# ============================================================================
# MINIMUM HOLD TIME (AUDIT 12/30 - Stop open->close loops)
# ============================================================================
# Goal: Prevent rapid open/close cycles that generate fees without capturing moves
# Emergency carve-outs: liquidation-distance breach, hard stop-loss, explicit emergency
MIN_HOLD_SECONDS = int(os.getenv("MIN_HOLD_SECONDS", "1800"))  # 30 minutes minimum hold (was 15 min)
MIN_HOLD_ENABLED = os.getenv("MIN_HOLD_ENABLED", "true").lower() in ("1", "true", "yes")

# ANTI-SPAM / FLIP SAFETY SETTINGS (Added Dec 24, 2025 - Critical Risk Fix)
# NOTE: Do NOT hard-raise these defaults in code: operators tune confidence via env/.env.
#       Keep conservative-but-usable defaults aligned with live behavior.
MIN_CONF_ENTRY = float(os.getenv("MIN_CONF_ENTRY", str(MIN_TRADING_CONFIDENCE)))
# Fix K (Feb 2026): Restore EXIT threshold to architecture spec.
# Was raised 0.60→0.80→0.85 which blocks ALL close/reduce actions when PPO
# confidence is collapsed (~0.43 post-training).  Exits are risk-REDUCING
# and must flow even when the model is uncertain.  Lowered to 0.40 to allow
# position management while blocking new entries (0.87).
MIN_CONF_EXIT = float(os.getenv("MIN_CONF_EXIT", "0.20"))    # Honest scale: top1=0.32→conf=0.21. Exits are risk-reducing, low bar
# Profitable position protection: when a trailing stop is active and position ROI
# exceeds this level, require higher model confidence (below) to allow full MODEL_CLOSE.
# Otherwise the close is converted to a PARTIAL_CLOSE (keep a runner).
MODEL_CLOSE_PROFIT_PROTECT_ROI_PCT = float(os.getenv("MODEL_CLOSE_PROFIT_PROTECT_ROI_PCT", "30.0"))  # ROI% threshold to enable protection
MODEL_CLOSE_PROFIT_PROTECT_MIN_CONF = float(os.getenv("MODEL_CLOSE_PROFIT_PROTECT_MIN_CONF", "0.85"))  # Min conf for full close when position is winning
# Fix L (Feb 2026): Lower hedge gate from 0.85→0.70.  Hedges are PROTECTIVE
# (risk-reducing) and must not be gated at the same level as new entries.
MIN_CONF_HEDGE = float(os.getenv("MIN_CONF_HEDGE", "0.70"))  # Hedges (>= 70%)

# Fix (Feb 2026): Explicit manage threshold — used by the trainer publish gate
# for CLOSE/REDUCE/TP/SL actions on existing positions. Must be lower than
# MIN_CONF_ENTRY to let the model manage positions while still learning.
MIN_CONF_MANAGE = float(os.getenv("MIN_CONF_MANAGE", "0.50"))  # Position management (lowered from 0.55 → 0.50 to allow signals at 0.50-0.55)
DYN_OPEN_RISK_CONF_FLOOR = float(os.getenv("DYN_OPEN_RISK_CONF_FLOOR", "0.45"))  # Trainer OPEN_RISK dynamic threshold floor (lowered from 0.55 to allow more trades)

# ============================================================================
# AUDIT FIX (Apr 2026): Anti-Policy-Collapse & Adaptive Signal Flow
# ============================================================================
# Problem: PPO outputs 94% HOLD, 0 signals published. Training loop 0% win rate
# teaches "trading = losing" → HOLD absorbing barrier. These fixes break the cycle.

# Fix A: Exploration bonus - small positive reward for non-HOLD actions to
# prevent the model from converging to always-HOLD. Only active when model
# entropy is low (policy is collapsing). Set to 0 to disable.
RL_REWARD_EXPLORATION_BONUS = float(os.getenv("RL_REWARD_EXPLORATION_BONUS", "0.15"))
RL_REWARD_EXPLORATION_ENTROPY_THRESHOLD = float(os.getenv("RL_REWARD_EXPLORATION_ENTROPY_THRESHOLD", "0.85"))  # Normalized entropy below which bonus activates

# Fix B: Regime gate confidence override - when PPO confidence exceeds this
# threshold, bypass the regime alignment check. High conviction = let it trade.
REGIME_GATE_CONFIDENCE_OVERRIDE = float(os.getenv("REGIME_GATE_CONFIDENCE_OVERRIDE", "0.72"))
REGIME_GATE_CONFIDENCE_OVERRIDE_ENABLED = os.getenv("REGIME_GATE_CONFIDENCE_OVERRIDE_ENABLED", "true").lower() in ("1", "true", "yes")

# Fix C: Adaptive threshold decay - when 0 OPEN_RISK signals are published for
# N consecutive prediction cycles, temporarily lower the threshold floor.
ADAPTIVE_THRESHOLD_DECAY_ENABLED = os.getenv("ADAPTIVE_THRESHOLD_DECAY_ENABLED", "true").lower() in ("1", "true", "yes")
ADAPTIVE_THRESHOLD_DECAY_CYCLES = int(os.getenv("ADAPTIVE_THRESHOLD_DECAY_CYCLES", "3"))  # Cycles of 0 signals before decay kicks in
ADAPTIVE_THRESHOLD_DECAY_STEP = float(os.getenv("ADAPTIVE_THRESHOLD_DECAY_STEP", "0.03"))  # Lower floor by this each cycle
ADAPTIVE_THRESHOLD_DECAY_MIN_FLOOR = float(os.getenv("ADAPTIVE_THRESHOLD_DECAY_MIN_FLOOR", "0.35"))  # Never go below this

# Fix D: Emergency ROE kill switch - force-close positions exceeding this ROE loss
EMERGENCY_ROE_KILL_PCT = float(os.getenv("EMERGENCY_ROE_KILL_PCT", "-100.0"))  # -100% = loss exceeds margin
EMERGENCY_ROE_KILL_ENABLED = os.getenv("EMERGENCY_ROE_KILL_ENABLED", "true").lower() in ("1", "true", "yes")

# Close deconfliction quorum: require TFs to agree before a close
# signal can override entry signals. If fewer TFs vote close AND the best
# close confidence is below CLOSE_QUORUM_BYPASS_CONF, demote to entry logic.
# FIX Apr 15: Reduced from 2→1 TF quorum and 0.70→0.60 bypass conf.
# With 60% TF conflict rate, requiring 2+ TFs blocked most legitimate closes.
CLOSE_QUORUM_TF_MIN = int(os.getenv("CLOSE_QUORUM_TF_MIN", "1"))
CLOSE_QUORUM_BYPASS_CONF = float(os.getenv("CLOSE_QUORUM_BYPASS_CONF", "0.60"))

# PnL-aware close guard: when a position is profitable AND the market is
# moving in the position's favor, require this higher confidence to close.
MIN_PROFITABLE_CLOSE_CONF = float(os.getenv("MIN_PROFITABLE_CLOSE_CONF", "0.75"))

# ============================================================================
# TRAINER INTENT / AUTHORITY SYSTEM (Feb 2026 — Post-Liquidation Fix)
# ============================================================================
# The trainer publishes its directional conviction to Redis every prediction
# cycle.  Autonomous closers (PER_LEG_ROI_KILL, soft-reduce, auto-deleverager)
# check this intent BEFORE closing.  If a position ALIGNS with the trainer's
# high-confidence intent, elevated thresholds + streak persistence are required.
#
# This prevents the cascade that liquidated the portfolio:
#   brief spike → single-tick ROI kill → latch blocks re-entry → all shorts closed
#   → market dumps (as predicted) → liquidation.
#
# Kill-switch: set TRAINER_INTENT_ENABLED=false to revert to old behavior.
TRAINER_INTENT_ENABLED = os.getenv("TRAINER_INTENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TRAINER_INTENT_TTL_SEC = int(os.getenv("TRAINER_INTENT_TTL_SEC", "300"))                        # 5 min TTL for intent freshness
TRAINER_INTENT_MIN_CONFIDENCE = float(os.getenv("TRAINER_INTENT_MIN_CONFIDENCE", "0.70"))       # Min confidence for deference to apply
TRAINER_DEFERENCE_ROI_MULTIPLIER = float(os.getenv("TRAINER_DEFERENCE_ROI_MULTIPLIER", "2.0"))  # ROI kill threshold multiplier when aligned (e.g., -30% → -60%)

# ── PER-LEG ROI KILL SWITCH (Feb 2026) ──
# Hard stop-out for individual position legs based on ROI%.
# This is the LAST LINE OF DEFENSE when the model fails to close losing legs.
# These are NOT exchange stop-losses (which are blocked by NO_STOP_LOSS policy).
# Instead, the proactive health monitor will emit CLOSE signals for legs exceeding these.
PER_LEG_ROI_KILL_ENABLED = os.getenv("PER_LEG_ROI_KILL_ENABLED", "true").lower() in ("1", "true", "yes", "on")  # Re-enabled: now gated by market_intelligence.should_allow_kill()
PER_LEG_ROI_KILL_PCT = float(os.getenv("PER_LEG_ROI_KILL_PCT", "-30.0"))  # Close leg if ROI < -30%
PER_LEG_ROI_WARN_PCT = float(os.getenv("PER_LEG_ROI_WARN_PCT", "-15.0"))  # Warn (reduce size) if ROI < -15%
PER_LEG_ROI_CHECK_INTERVAL = float(os.getenv("PER_LEG_ROI_CHECK_INTERVAL", "15.0"))  # Check every 15s
# STREAK REQUIREMENT: Require N consecutive ticks at kill threshold before firing.
# At 30s cadence, 3 = 90s persistence. Prevents single-tick transient spikes
# from triggering permanent closes. CRITICAL FIX for the liquidation event.
PER_LEG_ROI_KILL_STREAK_REQUIRED = int(os.getenv("PER_LEG_ROI_KILL_STREAK_REQUIRED", "3"))  # 3 consecutive ticks (~90s) before kill fires

# LEVERAGE-AWARE KILL: Scale kill threshold by leverage so extreme leverage
# positions get tighter monitoring and fire sooner (before total blowup).
# Formula: scale = max(1, actual_lev / REFERENCE_LEV)
#          effective_kill = base_kill / scale
# At 20x -> kill = -30%.  At 96x -> kill = -6.25%.  At 10x -> kill = -30% (unchanged).
PER_LEG_ROI_KILL_LEVERAGE_AWARE = os.getenv("PER_LEG_ROI_KILL_LEVERAGE_AWARE", "true").lower() in ("1", "true", "yes", "on")
PER_LEG_ROI_KILL_REFERENCE_LEVERAGE = float(os.getenv("PER_LEG_ROI_KILL_REFERENCE_LEVERAGE", "20.0"))
# Max scale factor cap: prevents hyper-sensitive kills at extreme leverage.
# 3.0 → minimum kill = -30%/3 = -10% ROI regardless of leverage.
# At 100x, -10% ROI = 0.1% price move (tight but not noise-level).
PER_LEG_ROI_KILL_MAX_SCALE = float(os.getenv("PER_LEG_ROI_KILL_MAX_SCALE", "3.0"))

# MAX ROI KILLS PER HOUR: Stops cascading kill-reopen-kill death loop.
# After this many kills in one hour, ROI kill pauses until the hour resets.
# PROTECTIVE unlimited (does not count). Set to 0 to disable the cap.
PER_LEG_ROI_KILL_MAX_PER_HOUR = int(os.getenv("PER_LEG_ROI_KILL_MAX_PER_HOUR", "5"))

# LOSS BUDGET GATE: Skip ROI kills if hourly realized loss already exceeds budget.
# Budget = equity * PROACTIVE_SOFT_REDUCE_LOSS_BUDGET_PCT / 100.
# Set PER_LEG_ROI_KILL_BUDGET_GATE_ENABLED=false to disable.
PER_LEG_ROI_KILL_BUDGET_GATE_ENABLED = os.getenv("PER_LEG_ROI_KILL_BUDGET_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ── INTELLIGENT CLOSE GUARD ────────────────────────────────────────────────
# Data-driven guard that checks regime, 2000+ features, orderbook, liquidation
# data, and trainer intent BEFORE allowing auto-closes (ROI kill, soft reduce,
# auto deleverage).  Computes a hold_score 0-1; if >= threshold → defer close.
INTELLIGENT_CLOSE_GUARD_ENABLED = os.getenv("INTELLIGENT_CLOSE_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")
ICG_DEFER_THRESHOLD = float(os.getenv("ICG_DEFER_THRESHOLD", "0.55"))
ICG_MIN_DATA_SOURCES = int(os.getenv("ICG_MIN_DATA_SOURCES", "2"))
ICG_WEIGHT_REGIME = float(os.getenv("ICG_WEIGHT_REGIME", "0.20"))
ICG_WEIGHT_FEATURES = float(os.getenv("ICG_WEIGHT_FEATURES", "0.25"))
ICG_WEIGHT_ORDERBOOK = float(os.getenv("ICG_WEIGHT_ORDERBOOK", "0.15"))
ICG_WEIGHT_TRAINER = float(os.getenv("ICG_WEIGHT_TRAINER", "0.20"))
ICG_WEIGHT_MTF = float(os.getenv("ICG_WEIGHT_MTF", "0.10"))
ICG_WEIGHT_LIQUIDATION = float(os.getenv("ICG_WEIGHT_LIQUIDATION", "0.10"))
ICG_ROI_KILL_EXTRA_STREAK = int(os.getenv("ICG_ROI_KILL_EXTRA_STREAK", "3"))

# ─── INTELLIGENCE CLOSE GATE (Apr 2026) ─────────────────────
# Unified multi-source intelligence gate for ALL close operations.
# Consults trainer, CoinAnk, OHLCV klines, liquidation levels, tape, orderbook
# before allowing any position close (profitable or losing).
# Kill switch: set to false to disable all intelligence gating on closes.
INTELLIGENCE_CLOSE_GATE_ENABLED = os.getenv("INTELLIGENCE_CLOSE_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
# Minimum data sources that must be available for intelligence gate to activate.
# If fewer sources available, gate fails open (allows close) for safety.
INTELLIGENCE_CLOSE_GATE_MIN_SOURCES = int(os.getenv("INTELLIGENCE_CLOSE_GATE_MIN_SOURCES", "2"))
# Also gate FRH hedge auto-TP with intelligence (can disable separately)
INTELLIGENCE_FRH_GATE_ENABLED = os.getenv("INTELLIGENCE_FRH_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
# Gate stealth TP/TRAIL executions with intelligence (SL always bypasses). Kill switch.
INTELLIGENCE_STEALTH_TP_GATE_ENABLED = os.getenv("INTELLIGENCE_STEALTH_TP_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
# Gate adaptive_threshold_engine with MI context (trainer alignment widens thresholds)
INTELLIGENCE_ADAPTIVE_THRESHOLD_ENABLED = os.getenv("INTELLIGENCE_ADAPTIVE_THRESHOLD_ENABLED", "true").lower() in ("1", "true", "yes")
# ICG delegates to market_intelligence for unified hold scoring
ICG_DELEGATE_TO_MI_ENABLED = os.getenv("ICG_DELEGATE_TO_MI_ENABLED", "true").lower() in ("1", "true", "yes")
ICG_SOFT_REDUCE_EXTRA_STREAK = int(os.getenv("ICG_SOFT_REDUCE_EXTRA_STREAK", "4"))
# Freshness thresholds (ms) for IntelligentCloseGuard data sources.
# When a source is stale, ICG treats it as "not used" (won't satisfy min_sources).
ICG_MAX_AGE_REGIME_MS = int(os.getenv("ICG_MAX_AGE_REGIME_MS", "180000"))          # 3m
ICG_MAX_AGE_FEATURES_MS = int(os.getenv("ICG_MAX_AGE_FEATURES_MS", "240000"))      # 4m
ICG_MAX_AGE_ORDERBOOK_MS = int(os.getenv("ICG_MAX_AGE_ORDERBOOK_MS", "15000"))     # 15s
ICG_MAX_AGE_TRAINER_INTENT_MS = int(os.getenv("ICG_MAX_AGE_TRAINER_INTENT_MS", "300000"))  # 5m
ICG_MAX_AGE_PREDICTION_MS = int(os.getenv("ICG_MAX_AGE_PREDICTION_MS", "300000"))  # 5m

# Loss-close policy: when the system is considering a loss-realizing close,
# require enough fresh sources to justify it; otherwise DEFER (hedge-first behavior).
ICG_FAIL_CLOSED_ON_LOSS_CLOSE = os.getenv("ICG_FAIL_CLOSED_ON_LOSS_CLOSE", "true").lower() in ("1", "true", "yes", "on")
ICG_LOSS_CLOSE_MIN_SOURCES = int(os.getenv("ICG_LOSS_CLOSE_MIN_SOURCES", "2"))

# Stealth: when hedge:active marks a hedged book, require this many consecutive
# stealth trigger evaluations before a >=99% close executes (profit or loss).
# Set to 0 to disable. ROI-kill / survival reasons bypass this gate.
STEALTH_HEDGE_FLATTEN_CONFIRM_TICKS = int(os.getenv("STEALTH_HEDGE_FLATTEN_CONFIRM_TICKS", "3"))  # 0 = disabled (instant); ≥1 = N confirm-ticks (×2s each) before executing flatten on hedged position; 3 = 6s wick debounce
# Run profit-hedge builder on trailing-stop (STOP_LOSS+TRAIL) ticks, not only static TP.
STEALTH_TRAIL_PROFIT_HEDGE_ENABLED = os.getenv(
    "STEALTH_TRAIL_PROFIT_HEDGE_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")

# ── MTF scenario tags on trainer payloads / proposals (audit) ────────────────
ENABLE_MTF_SCENARIO_TAGS = os.getenv("ENABLE_MTF_SCENARIO_TAGS", "true").lower() in ("1", "true", "yes", "on")

# ── Profit-close hedge preflight (orchestrator_worker) ───────────────────────
# Before publishing profit-intent closes under elevated TF stress, emit a hedge-scale
# proposal to the unified proposal stream, then publish the TP with optional delay hint.
PROFIT_CLOSE_HEDGE_PREFLIGHT_ENABLED = os.getenv(
    "PROFIT_CLOSE_HEDGE_PREFLIGHT_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
PROFIT_PREFLIGHT_CONFLICT_MIN = float(os.getenv("PROFIT_PREFLIGHT_CONFLICT_MIN", "0.35"))
PROFIT_PREFLIGHT_FAST_MOVE_MIN = float(os.getenv("PROFIT_PREFLIGHT_FAST_MOVE_MIN", "0.72"))
PROFIT_PREFLIGHT_LIQ_BPS_MAX = float(os.getenv("PROFIT_PREFLIGHT_LIQ_BPS_MAX", "250"))
PROFIT_PREFLIGHT_HEDGE_MARGIN_FRAC = float(os.getenv("PROFIT_PREFLIGHT_HEDGE_MARGIN_FRAC", "0.15"))
PROFIT_PREFLIGHT_PUBLISH_DELAY_MS = int(os.getenv("PROFIT_PREFLIGHT_PUBLISH_DELAY_MS", "2000"))

# ── ROI kill: hedge escalation + market rechecks (trader proactive health) ───
# When enabled, first emit a hedge-scale proposal when kill streak is satisfied,
# then require N fresh unified_features timestamp ticks before firing PER_LEG_ROI_KILL.
# Emergency bypass: ROI worse than ROI_KILL_HEDGE_FIRST_EMERGENCY_ROI_PCT (e.g. -85%)
# or dust path still allows immediate kill.
ROI_KILL_HEDGE_FIRST_ENABLED = os.getenv("ROI_KILL_HEDGE_FIRST_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ROI_KILL_MARKET_RECHECKS_REQUIRED = int(os.getenv("ROI_KILL_MARKET_RECHECKS_REQUIRED", "2"))
ROI_KILL_ESCALATION_HEDGE_MARGIN_FRAC = float(os.getenv("ROI_KILL_ESCALATION_HEDGE_MARGIN_FRAC", "0.50"))
ROI_KILL_HEDGE_FIRST_EMERGENCY_ROI_PCT = float(os.getenv("ROI_KILL_HEDGE_FIRST_EMERGENCY_ROI_PCT", "-95.0"))

# ── GRADUATED KILL: HEDGE → TRIM → REDUCE (Apr 2026) ──
# Instead of FULL_CLOSE on losing legs, use a graduated approach:
#   Phase 1 (HEDGE): Open opposite-side hedge matching losing leg size
#   Phase 2 (TRIM):  Trim losing leg 15-25% per cycle until near breakeven
#   Phase 3 (CLOSE): Only full-close if loss exceeds EMERGENCY threshold
# This prevents realizing large losses; instead brings positions to near-zero loss.
GRADUATED_KILL_ENABLED = os.getenv("GRADUATED_KILL_ENABLED", "true").lower() in ("1", "true", "yes", "on")  # Re-enabled: now gated by market_intelligence
# Phase 1: Hedge margin as fraction of losing leg margin (0.5 = 50% of losing margin)
GRADUATED_KILL_HEDGE_MARGIN_FRAC = float(os.getenv("GRADUATED_KILL_HEDGE_MARGIN_FRAC", "0.25"))
# Phase 2: Max trim fraction per cycle (never close more than this at once)
GRADUATED_KILL_TRIM_MAX_FRAC = float(os.getenv("GRADUATED_KILL_TRIM_MAX_FRAC", "0.25"))
# Phase 2: Minimum trim fraction per cycle
GRADUATED_KILL_TRIM_MIN_FRAC = float(os.getenv("GRADUATED_KILL_TRIM_MIN_FRAC", "0.10"))
# Only trim if combined (losing+hedge) PnL is close enough to breakeven ($)
GRADUATED_KILL_BREAKEVEN_THRESHOLD_USD = float(os.getenv("GRADUATED_KILL_BREAKEVEN_THRESHOLD_USD", "5.0"))
# Time between trim cycles (seconds) — don't spam trims
GRADUATED_KILL_TRIM_COOLDOWN_SECS = float(os.getenv("GRADUATED_KILL_TRIM_COOLDOWN_SECS", "120.0"))
# Emergency: only full-close if ROI worse than this (margin nearly gone)
GRADUATED_KILL_EMERGENCY_ROI_PCT = float(os.getenv("GRADUATED_KILL_EMERGENCY_ROI_PCT", "-95.0"))
# Minimum hedge coverage before allowing ANY trim (hedge must be >= this fraction of losing leg)
GRADUATED_KILL_MIN_HEDGE_COVERAGE = float(os.getenv("GRADUATED_KILL_MIN_HEDGE_COVERAGE", "0.30"))

# ── WARN-LEVEL PROACTIVE HEDGING (Apr 2026) ──
# When ROI hits WARN threshold (before kill threshold), start building hedge
# EARLY to prevent positions from deteriorating to kill-level losses.
WARN_HEDGE_ENABLED = os.getenv("WARN_HEDGE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
WARN_HEDGE_COOLDOWN_SECS = float(os.getenv("WARN_HEDGE_COOLDOWN_SECS", "90.0"))  # 90s between warn-hedge proposals
WARN_HEDGE_MARGIN_FRAC = float(os.getenv("WARN_HEDGE_MARGIN_FRAC", "0.25"))  # 25% of losing margin for warn-level hedge

# ── TREND-FOLLOWING HEDGE SCALING (Apr 2026) ──
# When hedged pairs exist and one side is profitable while the other is losing,
# incrementally increase the PROFITABLE side to build the winning hedge leg.
# This ensures the system builds opposite-side positions slowly as market trends.
TREND_HEDGE_SCALE_ENABLED = os.getenv("TREND_HEDGE_SCALE_ENABLED", "true").lower() in ("1", "true", "yes", "on")  # Re-enabled: now gated by market_intelligence.should_allow_hedge()
TREND_HEDGE_SCALE_COOLDOWN_SECS = float(os.getenv("TREND_HEDGE_SCALE_COOLDOWN_SECS", "120.0"))  # 2min between scale proposals
TREND_HEDGE_MIN_PROFIT_ROI = float(os.getenv("TREND_HEDGE_MIN_PROFIT_ROI", "3.0"))  # Only scale if profitable side > 3% ROI
TREND_HEDGE_SCALE_MARGIN_FRAC = float(os.getenv("TREND_HEDGE_SCALE_MARGIN_FRAC", "0.15"))  # Add 15% of profitable margin each cycle
TREND_HEDGE_MAX_LOSING_ROI = float(os.getenv("TREND_HEDGE_MAX_LOSING_ROI", "-10.0"))  # Only scale if losing side < -10%

# ── DEPTH-VS-TAPE SPOOF DETECTION (Apr 2026) ──
# Uses Binance aggTrades real-time flow vs orderbook depth to detect spoofs.
# When depth shows buy pressure but tape shows selling, it's a manipulation signal.
ENABLE_TAPE_SPOOF_DETECTION = os.getenv("ENABLE_TAPE_SPOOF_DETECTION", "true").lower() in ("1", "true", "yes", "on")
DVT_WHIPSAW_WEIGHT = float(os.getenv("DVT_WHIPSAW_WEIGHT", "0.20"))  # Weight in whipsaw detection (was 0, now 20%)
DVT_SAFETY_BUFFER_MULT = float(os.getenv("DVT_SAFETY_BUFFER_MULT", "0.40"))  # Max +40% buffer increase from divergence
DVT_SUPPORT_OVERRIDE_THRESHOLD = float(os.getenv("DVT_SUPPORT_OVERRIDE_THRESHOLD", "0.40"))  # Override OB-based support above this

# ── HEDGE-ADD QUALITY GATE (Feb 2026) ──
# Block hedge-adds when the PPO model's policy entropy is near-maximum (= random).
# If the model isn't making meaningful distinctions between actions, hedge-adds
# based on its outputs are just adding noise to the portfolio.
HEDGE_ADD_MIN_CONFIDENCE = float(os.getenv("HEDGE_ADD_MIN_CONFIDENCE", "0.65"))  # TIGHTENED Apr 2026: was 0.40 (fee churn); 0.65 blocks low-conviction noise
HEDGE_ADD_BLOCK_STALE_PROTECTIVE = os.getenv("HEDGE_ADD_BLOCK_STALE_PROTECTIVE", "true").lower() in ("1", "true", "yes", "on")

# ── CONCENTRATION GATE THRESHOLDS (Feb 2026) ──
# The old 40%-of-notional cap always trips with 50-75× leverage.
# Switch to MARGIN-BASED concentration: gross_margin/equity.
# Optional directional guard via NET delta/equity.
CONCENTRATION_USE_MARGIN = os.getenv("CONCENTRATION_USE_MARGIN", "true").lower() in ("1", "true", "yes", "on")
CONCENTRATION_GROSS_MARGIN_MAX_PCT = float(os.getenv("CONCENTRATION_GROSS_MARGIN_MAX_PCT", "95.0"))  # Block at 95% gross margin util
CONCENTRATION_GROSS_MARGIN_WARN_PCT = float(os.getenv("CONCENTRATION_GROSS_MARGIN_WARN_PCT", "80.0"))  # Warn at 80%
CONCENTRATION_NET_DELTA_MAX_PCT = float(os.getenv("CONCENTRATION_NET_DELTA_MAX_PCT", "500.0"))  # TIGHTENED Apr 2026: Net notional delta/equity (was 2500% = no cap; 500% = $13k on $2.6k equity)
CONCENTRATION_SINGLE_SYMBOL_MARGIN_MAX_PCT = float(os.getenv("CONCENTRATION_SINGLE_SYMBOL_MARGIN_MAX_PCT", "25.0"))  # Max single-symbol margin/equity (raised from 6% — hedge mode doubles margin per symbol)

# ── NOTIONAL-TO-EQUITY CAP (Apr 2026 Audit P0) ──
# Prevents any single position from exceeding N% of equity in notional exposure.
# MAX_POSITION_PER_SYMBOL_PER_SIDE guards margin ($500); this guards notional ($500*50x=$25k).
# Adaptive: base cap is scaled DOWN in high-vol regimes (ATR-based) and scaled UP in low-vol.
NOTIONAL_TO_EQUITY_CAP_ENABLED = os.getenv("NOTIONAL_TO_EQUITY_CAP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MAX_NOTIONAL_TO_EQUITY_PCT = float(os.getenv("MAX_NOTIONAL_TO_EQUITY_PCT", "500.0"))  # 500% base = $13k on $2.6k equity
NOTIONAL_CAP_VOL_SCALE_ENABLED = os.getenv("NOTIONAL_CAP_VOL_SCALE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
NOTIONAL_CAP_VOL_SCALE_MIN = float(os.getenv("NOTIONAL_CAP_VOL_SCALE_MIN", "0.50"))  # In high vol: cap shrinks to 50% of base (= 250%)
NOTIONAL_CAP_VOL_SCALE_MAX = float(os.getenv("NOTIONAL_CAP_VOL_SCALE_MAX", "1.20"))  # In low vol: cap grows to 120% of base (= 600%)
# Volatility thresholds (NATR % — normalized ATR as % of price)
NOTIONAL_CAP_VOL_HIGH_NATR = float(os.getenv("NOTIONAL_CAP_VOL_HIGH_NATR", "3.0"))   # NATR >= 3% → high vol regime
NOTIONAL_CAP_VOL_LOW_NATR = float(os.getenv("NOTIONAL_CAP_VOL_LOW_NATR", "0.8"))    # NATR <= 0.8% → low vol regime

# ── DISTRESS CLOSE OVERRIDE (Apr 2026 Audit P1) ──
# Bypass close quorum when position ROI is deeply negative.
# Leverage-aware: threshold = base × (reference_lev / actual_lev)
# At 50x: -8% × (20/50) = -3.2% ROI triggers. At 10x: -8% × (20/10) = -16% ROI.
DISTRESS_CLOSE_OVERRIDE_ENABLED = os.getenv("DISTRESS_CLOSE_OVERRIDE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DISTRESS_CLOSE_ROI_BASE_PCT = float(os.getenv("DISTRESS_CLOSE_ROI_BASE_PCT", "-8.0"))  # Base ROI threshold
DISTRESS_CLOSE_REFERENCE_LEVERAGE = float(os.getenv("DISTRESS_CLOSE_REFERENCE_LEVERAGE", "20.0"))  # Reference leverage for scaling
DISTRESS_CLOSE_MIN_CONF = float(os.getenv("DISTRESS_CLOSE_MIN_CONF", "0.45"))  # Min single-TF conf for distress close
DISTRESS_CLOSE_MAX_SCALE = float(os.getenv("DISTRESS_CLOSE_MAX_SCALE", "3.0"))  # Cap scaling factor to prevent overshoot

# ── WIN RATE STRICT MODE (Apr 2026 Audit P2) ──
# When enabled: WR optimizer TIGHTENS conf when WR is high (opposite of default relax),
# HighQualitySignalFilter actually blocks below threshold, floor raised to 0.90.
WIN_RATE_STRICT_MODE = os.getenv("WIN_RATE_STRICT_MODE", "false").lower() in ("1", "true", "yes", "on")
WIN_RATE_STRICT_TARGET = float(os.getenv("WIN_RATE_STRICT_TARGET", "0.90"))  # Target WR in strict mode
WIN_RATE_STRICT_CONF_FLOOR = float(os.getenv("WIN_RATE_STRICT_CONF_FLOOR", "0.90"))  # Min confidence floor in strict mode

# ============================================================================
# PROFITABILITY GATES — Anti-Churn & Circuit Breakers (Feb 2026 Audit Fixes)
# ============================================================================
# These gates address the 6 root causes of losses identified in the 48h live audit:
# 1. PPO model randomness (99.2% entropy) → TOP_PROB gate
# 2. Commission churning ($939/30d) → notional/fill caps
# 3. Both-side hedging → single-direction enforcement
# 4. No downtime protection → exchange-side SL
# 5. Catastrophic days → daily drawdown circuit breaker
# 6. Per-symbol loss sink → per-symbol daily loss cap

# ── 1. TOP PROBABILITY GATE (kills random model noise) ──
# Force HOLD when the PPO model's top action probability is below this threshold.
# A 7-action uniform distribution gives ~14.3% per action. A minimum of 25% means
# the model must be at least 1.75x more decisive than random to trade.
TOP_PROB_GATE_ENABLED = os.getenv("TOP_PROB_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# FIXED: 0.25 was mathematically impossible for 7-action space (uniform=14.3%).
# 0.18 = 1.26x above uniform — reachable by a model that's starting to learn.
# Will be raised back to 0.22-0.25 once the model escapes the entropy trap.
TOP_PROB_MIN_THRESHOLD = float(os.getenv("TOP_PROB_MIN_THRESHOLD", "0.18"))  # Min top-1 softmax prob to allow non-HOLD

# ── 2. ANTI-CHURN: Rolling notional & fill caps ──
# Rolling 1-hour caps to prevent commission destruction
ANTI_CHURN_ENABLED = os.getenv("ANTI_CHURN_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MAX_FILLS_PER_SYMBOL_PER_HOUR = int(os.getenv("MAX_FILLS_PER_SYMBOL_PER_HOUR", "4"))  # APRIL PLAN v3: Tightened 10→4 to prevent churn (was creating 126 RAREUSDT trades/day)
MAX_HEDGE_FILLS_PER_SYMBOL_PER_HOUR = int(os.getenv("MAX_HEDGE_FILLS_PER_SYMBOL_PER_HOUR", "20"))  # Doubled to 20/hour
MAX_NOTIONAL_TURNOVER_RATIO = float(os.getenv("MAX_NOTIONAL_TURNOVER_RATIO", "80.0"))  # TIGHTENED Apr 2026: was 10000x (unlimited); 80x = ~$208k turnover on $2.6k equity/day
# Fee-aware minimum edge: block entries where expected profit < commission cost
MIN_EDGE_AFTER_FEES_BPS = float(os.getenv("MIN_EDGE_AFTER_FEES_BPS", "8.0"))  # Require 8bps expected edge above round-trip fees
# Close-then-reopen protection: block reopening same symbol+direction within cooldown after a close
CLOSE_REOPEN_COOLDOWN_SEC = int(os.getenv("CLOSE_REOPEN_COOLDOWN_SEC", "300"))  # 5min cooldown after closing before reopening same direction
CLOSE_REOPEN_BLOCK_ENABLED = os.getenv("CLOSE_REOPEN_BLOCK_ENABLED", "true").lower() in ("true", "1", "yes")

# ── 3. SINGLE DIRECTION PER SYMBOL (prevents both-sides hedging) ──
# When enabled, blocks OPEN on the opposite side of an existing position.
# Does NOT affect explicit HEDGE actions (those are routed differently).
SINGLE_DIRECTION_PER_SYMBOL = os.getenv("SINGLE_DIRECTION_PER_SYMBOL", "true").lower() in ("1", "true", "yes", "on")

# ── 4. EXCHANGE-SIDE STOP-LOSS (survives downtime) ──
# Places a real STOP_MARKET order on Binance as catastrophic protection.
# This is a WIDE stop (not for profit management) — only fires if system goes down.
EXCHANGE_STOP_ENABLED = os.getenv("EXCHANGE_STOP_ENABLED", "false").lower() in ("1", "true", "yes", "on")
EXCHANGE_STOP_PCT = float(os.getenv("EXCHANGE_STOP_PCT", "5.0"))  # 5% from entry (wide, downtime-only)

# ── RAMP: Dynamic Exchange Backstop (high-leverage crash protection) ──
# For positions with leverage > threshold, place exchange-side STOP_MARKET as
# an absolute backstop.  Distance is computed dynamically from ATR + leverage.
# This is 2x wider than the stealth trailing stop so it only fires if the bot
# fails to execute the trailing stop (crash, lag, WebSocket disconnect).
RAMP_EXCHANGE_BACKSTOP_ENABLED = os.getenv("RAMP_EXCHANGE_BACKSTOP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
RAMP_EXCHANGE_BACKSTOP_MIN_LEVERAGE = float(os.getenv("RAMP_EXCHANGE_BACKSTOP_MIN_LEVERAGE", "25.0"))
RAMP_EXCHANGE_BACKSTOP_MARGIN_PCT = float(os.getenv("RAMP_EXCHANGE_BACKSTOP_MARGIN_PCT", "80.0"))

# ── 5. DAILY DRAWDOWN CIRCUIT BREAKER ──
# Halt ALL new entries (across all symbols) when daily realized PnL drawdown exceeds cap.
# Only CLOSE/REDUCE actions allowed when breaker is tripped.
DAILY_DRAWDOWN_BREAKER_ENABLED = os.getenv("DAILY_DRAWDOWN_BREAKER_ENABLED", "false").lower() in ("1", "true", "yes", "on")
DAILY_DRAWDOWN_MAX_PCT = float(os.getenv("DAILY_DRAWDOWN_MAX_PCT", "-50.0"))  # -50% of equity = halt entries (relaxed)
DAILY_DRAWDOWN_RESET_HOUR_UTC = int(os.getenv("DAILY_DRAWDOWN_RESET_HOUR_UTC", "0"))  # Reset at midnight UTC

# ── 6. PER-SYMBOL DAILY LOSS CAP ──
# Stop trading a specific symbol if its daily realized loss exceeds this cap.
PER_SYMBOL_DAILY_LOSS_CAP_ENABLED = os.getenv("PER_SYMBOL_DAILY_LOSS_CAP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PER_SYMBOL_DAILY_LOSS_CAP_PCT = float(os.getenv("PER_SYMBOL_DAILY_LOSS_CAP_PCT", "-1.5"))  # -1.5% of equity per symbol/day

# ============================================================================
# ADAPTIVE MARKET-CONDITION GATE (Feb 2026 — replaces timer-based anti-churn)
# ============================================================================
# Master switch: When enabled, ALL timer-based gates (MIN_HOLD_SECONDS,
# MIN_INTERVAL_BETWEEN_TRADES_SECONDS, MAX_TRADES_PER_SYMBOL_PER_HOUR) are
# REPLACED by real-time data-driven gates from risk/adaptive_gate.py that read
# live features (ATR, spread, depth, ADX, funding, fast-move, etc.) from Redis.
# When disabled, the old timer-based fallbacks still work.
ADAPTIVE_GATE_ENABLED = os.getenv("ADAPTIVE_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Sub-gate kill switches (all default ON — disable individually if needed)
ADAPTIVE_GATE_SPREAD_ENABLED = os.getenv("ADAPTIVE_GATE_SPREAD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_LIQUIDITY_ENABLED = os.getenv("ADAPTIVE_GATE_LIQUIDITY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_VOLATILITY_ENABLED = os.getenv("ADAPTIVE_GATE_VOLATILITY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_FAST_MOVE_ENABLED = os.getenv("ADAPTIVE_GATE_FAST_MOVE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_TREND_ENABLED = os.getenv("ADAPTIVE_GATE_TREND_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_IMBALANCE_ENABLED = os.getenv("ADAPTIVE_GATE_IMBALANCE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_FUNDING_ENABLED = os.getenv("ADAPTIVE_GATE_FUNDING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_MANIPULATION_ENABLED = os.getenv("ADAPTIVE_GATE_MANIPULATION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_GATE_EDGE_FEES_ENABLED = os.getenv("ADAPTIVE_GATE_EDGE_FEES_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Adaptive hold: replace MIN_HOLD_SECONDS timer with live feature-based hold scoring
ADAPTIVE_HOLD_ENABLED = os.getenv("ADAPTIVE_HOLD_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ============================================================================
# ROTATION / SWAP POLICY (Orchestrator)
# ============================================================================
ROTATION_POLICY = {
    "enabled": os.getenv("ROTATION_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "swap_improvement_threshold": float(os.getenv("ROTATION_SWAP_IMPROVEMENT_THRESHOLD", "0.35")),
    "min_candidate_confidence": float(os.getenv("ROTATION_MIN_CANDIDATE_CONFIDENCE", "0.90")),
    "min_liq_distance_pct": float(os.getenv("ROTATION_MIN_LIQ_DISTANCE_PCT", "1.0")),
    "max_swaps_per_hour": int(os.getenv("ROTATION_MAX_SWAPS_PER_HOUR", "2")),
    "per_symbol_cooldown_sec": int(os.getenv("ROTATION_PER_SYMBOL_COOLDOWN_SEC", "900")),
    "global_cooldown_sec": int(os.getenv("ROTATION_GLOBAL_COOLDOWN_SEC", "120")),
    "reduce_instead_of_close": os.getenv("ROTATION_REDUCE_INSTEAD_OF_CLOSE", "true").lower() in ("1", "true", "yes", "on"),
    "reduce_fraction": float(os.getenv("ROTATION_REDUCE_FRACTION", "0.25")),
    "no_loss_only": os.getenv("ROTATION_NO_LOSS_ONLY", "true").lower() in ("1", "true", "yes", "on"),
    "loss_tolerance_pct": float(os.getenv("ROTATION_LOSS_TOLERANCE_PCT", "0.05")),
    "winner_protect_pnl_pct": float(os.getenv("ROTATION_WINNER_PROTECT_PNL_PCT", "1.5")),
    "winner_override_margin": float(os.getenv("ROTATION_WINNER_OVERRIDE_MARGIN", "0.75")),
    "dq_min_confidence": float(os.getenv("ROTATION_DQ_MIN_CONFIDENCE", "0.5")),
    "pending_timeout_sec": int(os.getenv("ROTATION_PENDING_TIMEOUT_SEC", "90")),
    "pending_max_attempts": int(os.getenv("ROTATION_PENDING_MAX_ATTEMPTS", "3")),
    "min_hold_sec": int(os.getenv("ROTATION_MIN_HOLD_SECS", "300")),
    "allow_if_drawdown_lt": float(os.getenv("ROTATION_ALLOW_IF_DD_LT", "6.0")),
    "block_if_tox_gt": float(os.getenv("ROTATION_BLOCK_IF_TOX_GT", "0.60")),
    "block_if_ob_lt": float(os.getenv("ROTATION_BLOCK_IF_OB_LT", "150000")),
    "dq_required_fields": ["liq_distance_pct", "orderbook_depth_usd", "volatility_pct"],
    "dq_max_orderbook_age_ms": int(os.getenv("ROTATION_DQ_MAX_ORDERBOOK_AGE_MS", "15000")),
    "dq_max_liqmap_age_ms": int(os.getenv("ROTATION_DQ_MAX_LIQMAP_AGE_MS", "90000")),
    "dq_max_vol_age_ms": int(os.getenv("ROTATION_DQ_MAX_VOL_AGE_MS", "120000")),
}

# ============================================================================
# HEDGE LIFECYCLE STATE MACHINE
# ============================================================================
HEDGE_ENABLED = os.getenv("HEDGE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HEDGE_LIQ_PARTIAL_ON = float(os.getenv("HEDGE_LIQ_PARTIAL_ON", "8.0"))
HEDGE_LIQ_FULL_ON = float(os.getenv("HEDGE_LIQ_FULL_ON", "5.0"))
HEDGE_LIQ_OFF = float(os.getenv("HEDGE_LIQ_OFF", "12.0"))
HEDGE_TOX_PARTIAL_ON = float(os.getenv("HEDGE_TOX_PARTIAL_ON", "0.35"))
HEDGE_TOX_FULL_ON = float(os.getenv("HEDGE_TOX_FULL_ON", "0.55"))
HEDGE_TOX_OFF = float(os.getenv("HEDGE_TOX_OFF", "0.25"))
HEDGE_VOL_PARTIAL_ON = float(os.getenv("HEDGE_VOL_PARTIAL_ON", "35.0"))
HEDGE_VOL_FULL_ON = float(os.getenv("HEDGE_VOL_FULL_ON", "55.0"))
HEDGE_VOL_OFF = float(os.getenv("HEDGE_VOL_OFF", "25.0"))
HEDGE_OB_MIN_OK = float(os.getenv("HEDGE_OB_MIN_OK", "250000"))
HEDGE_OB_MIN_BAD = float(os.getenv("HEDGE_OB_MIN_BAD", "100000"))
HEDGE_DD_PARTIAL_ON = float(os.getenv("HEDGE_DD_PARTIAL_ON", "4.0"))
HEDGE_DD_FULL_ON = float(os.getenv("HEDGE_DD_FULL_ON", "7.0"))
HEDGE_DD_OFF = float(os.getenv("HEDGE_DD_OFF", "2.5"))
HEDGE_COOLDOWN_SECS = int(os.getenv("HEDGE_COOLDOWN_SECS", "120"))
HEDGE_MIN_HOLD_SECS = int(os.getenv("HEDGE_MIN_HOLD_SECS", "90"))
HEDGE_ADD_FRESHNESS_MAX_AGE_MS = int(os.getenv("HEDGE_ADD_FRESHNESS_MAX_AGE_MS", "20000"))
# Fail-closed entry freshness gate (OPEN_RISK): do not open new exposure on stale features.
OPEN_RISK_FEATURES_MAX_AGE_MS = int(os.getenv("OPEN_RISK_FEATURES_MAX_AGE_MS", "120000"))
HEDGE_ADD_ANTI_CHASE_BPS = float(os.getenv("HEDGE_ADD_ANTI_CHASE_BPS", "25"))
HEDGE_ADD_ANTI_CHASE_PERSIST_N = int(os.getenv("HEDGE_ADD_ANTI_CHASE_PERSIST_N", "3"))
HEDGE_ADD_LADDER_STEP_USD = float(os.getenv("HEDGE_ADD_LADDER_STEP_USD", "75.0"))
HEDGE_ADD_LADDER_STEP_EQUITY_PCT = float(os.getenv("HEDGE_ADD_LADDER_STEP_EQUITY_PCT", "0.015"))
HEDGE_ADD_LADDER_COOLDOWN_SEC = int(os.getenv("HEDGE_ADD_LADDER_COOLDOWN_SEC", "30"))
HEDGE_ADD_LADDER_MIN_MOVE_BPS = float(os.getenv("HEDGE_ADD_LADDER_MIN_MOVE_BPS", "20"))
HEDGE_TP_STRESS_MIN_HOLD_SEC = int(os.getenv("HEDGE_TP_STRESS_MIN_HOLD_SEC", "120"))
HEDGE_TP_STRESS_MAX_PARTIAL_PCT = float(os.getenv("HEDGE_TP_STRESS_MAX_PARTIAL_PCT", "0.30"))
HEDGE_BUILD_TTL_SECS = int(os.getenv("HEDGE_BUILD_TTL_SECS", "600"))
HEDGE_UNWIND_STEP_FRACTION = float(os.getenv("HEDGE_UNWIND_STEP_FRACTION", "0.25"))
MAX_HEDGE_MARGIN_PCT_OF_EQUITY = float(os.getenv("MAX_HEDGE_MARGIN_PCT_OF_EQUITY", "0.20"))

# Hedge lifecycle percentile thresholds (adaptive to local symbol distributions)
HEDGE_PERCENTILE_ENABLED = os.getenv("HEDGE_PERCENTILE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HEDGE_PERCENTILE_WINDOW = int(os.getenv("HEDGE_PERCENTILE_WINDOW", "180"))
HEDGE_PERCENTILE_MIN_SAMPLES = int(os.getenv("HEDGE_PERCENTILE_MIN_SAMPLES", "40"))
HEDGE_PCTL_FULL_ON_HIGH = float(os.getenv("HEDGE_PCTL_FULL_ON_HIGH", "90"))
HEDGE_PCTL_PARTIAL_ON_HIGH = float(os.getenv("HEDGE_PCTL_PARTIAL_ON_HIGH", "75"))
HEDGE_PCTL_OFF_HIGH = float(os.getenv("HEDGE_PCTL_OFF_HIGH", "55"))
HEDGE_PCTL_FULL_ON_LOW = float(os.getenv("HEDGE_PCTL_FULL_ON_LOW", "10"))
HEDGE_PCTL_PARTIAL_ON_LOW = float(os.getenv("HEDGE_PCTL_PARTIAL_ON_LOW", "25"))
HEDGE_PCTL_OFF_LOW = float(os.getenv("HEDGE_PCTL_OFF_LOW", "40"))

# ============================================================================
# MARKET REGIME LAYER (Production Safety - All flags default OFF)
# ============================================================================
# Phase 0: Shadow mode - compute regime, log only, no behavior change
REGIME_LAYER_ENABLED = os.getenv("REGIME_LAYER_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Phase 1: Influence mode - orchestrator uses regime to adjust posture/coverage
REGIME_POLICY_ENABLED = os.getenv("REGIME_POLICY_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Phase 2: Adaptive hedging - hedge_manager uses regime for sizing
REGIME_HEDGE_ADAPTIVE_ENABLED = os.getenv("REGIME_HEDGE_ADAPTIVE_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Cache and staleness thresholds
REGIME_CACHE_TTL_SEC = int(os.getenv("REGIME_CACHE_TTL_SEC", "300"))
REGIME_STALE_SEC = int(os.getenv("REGIME_STALE_SEC", "300"))  # Raised from 120: must match CACHE_TTL or stale-check rejects valid cached regimes
REGIME_VERSION = os.getenv("REGIME_VERSION", "v1")

# Regime thresholds (move_score 0..1)
REGIME_MOVE_CALM_MAX = float(os.getenv("REGIME_MOVE_CALM_MAX", "0.20"))
REGIME_MOVE_NORMAL_MAX = float(os.getenv("REGIME_MOVE_NORMAL_MAX", "0.45"))
REGIME_MOVE_FAST_MAX = float(os.getenv("REGIME_MOVE_FAST_MAX", "0.70"))
# Above FAST_MAX = IMPULSE

# Big-move one-leg thresholds (only when REGIME_POLICY_ENABLED)
REGIME_BIG_MOVE_SCORE_MIN = float(os.getenv("REGIME_BIG_MOVE_SCORE_MIN", "0.55"))
REGIME_BIG_MOVE_ALIGNMENT_MIN = float(os.getenv("REGIME_BIG_MOVE_ALIGNMENT_MIN", "0.60"))
REGIME_BIG_MOVE_ENTROPY_MAX = float(os.getenv("REGIME_BIG_MOVE_ENTROPY_MAX", "0.35"))
REGIME_BIG_MOVE_LIQ_RISK_MAX = float(os.getenv("REGIME_BIG_MOVE_LIQ_RISK_MAX", "0.45"))

# Derived convenience helpers — FUNCTIONS, not constants.
# Computed dynamically so importlib.reload(config) + flag override
# always returns correct values (no stale derived state).
#   regime_active()      → decision mutations allowed (stress, cov, one-leg, etc.)
#   regime_attach_only() → data attached to proposals/signals, NO decision mutation
def regime_active() -> bool:
    """True when regime may mutate decisions (stress, coverage, one-leg)."""
    return bool(REGIME_POLICY_ENABLED)

def regime_attach_only() -> bool:
    """True when regime data is attached but MUST NOT mutate decisions."""
    return bool(REGIME_LAYER_ENABLED) and not bool(REGIME_POLICY_ENABLED)

# Legacy constants kept for backward compat — but prefer the functions above.
REGIME_ATTACH_ONLY: bool = REGIME_LAYER_ENABLED and not REGIME_POLICY_ENABLED
REGIME_ACTIVE: bool = bool(REGIME_POLICY_ENABLED)

# ============================================================================
# GLOBAL BREADTH + RISK BUDGET ALLOCATOR (Enterprise-grade scaling)
# ============================================================================
# Feature-flagged: when OFF, zero behavior change. Only adjusts SOFT caps.
# Hard constraints (liq buffer, margin caps, drawdown breakers, leverage caps,
# staleness gates, stress/shock emergency) are NEVER bypassed by this system.
#
# Three layers:
#   1. Global Breadth: cross-symbol consensus signal (regime:global:{tf})
#   2. Risk Budget Allocator: truth-table state machine → soft-cap adjustments
#   3. Reversal Detector: fires when breadth indicators flip → de-risk
GLOBAL_BREADTH_ENABLED = os.getenv("GLOBAL_BREADTH_ENABLED", "false").lower() in ("1", "true", "yes", "on")
RISK_BUDGET_ALLOCATOR_ENABLED = os.getenv("RISK_BUDGET_ALLOCATOR_ENABLED", "false").lower() in ("1", "true", "yes", "on")
REVERSAL_DETECTOR_ENABLED = os.getenv("REVERSAL_DETECTOR_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Breadth computation parameters
GLOBAL_BREADTH_MIN_SYMBOLS = int(os.getenv("GLOBAL_BREADTH_MIN_SYMBOLS", "4"))
GLOBAL_BREADTH_ALIGNED_THRESHOLD = float(os.getenv("GLOBAL_BREADTH_ALIGNED_THRESHOLD", "0.30"))
GLOBAL_BREADTH_CACHE_TTL_SEC = int(os.getenv("GLOBAL_BREADTH_CACHE_TTL_SEC", "300"))
GLOBAL_BREADTH_STALE_SEC = int(os.getenv("GLOBAL_BREADTH_STALE_SEC", "600"))
GLOBAL_BREADTH_TIMEFRAMES = [x.strip() for x in os.getenv("GLOBAL_BREADTH_TIMEFRAMES", "5m,15m").split(",") if x.strip()]
GLOBAL_BREADTH_COMPUTE_INTERVAL_SEC = int(os.getenv("GLOBAL_BREADTH_COMPUTE_INTERVAL_SEC", "30"))

# Risk Budget Allocator truth-table thresholds (see risk/risk_budget_allocator.py)
RBA_BREADTH_STRENGTH_MIN = float(os.getenv("RBA_BREADTH_STRENGTH_MIN", "0.70"))
RBA_BREADTH_ENTROPY_MAX = float(os.getenv("RBA_BREADTH_ENTROPY_MAX", "0.30"))
RBA_BREADTH_CORR_MAX = float(os.getenv("RBA_BREADTH_CORR_MAX", "0.75"))
RBA_BREADTH_VOL_MAX = float(os.getenv("RBA_BREADTH_VOL_MAX", "0.65"))
RBA_FAST_MOVE_SCORE_THRESHOLD = float(os.getenv("RBA_FAST_MOVE_SCORE_THRESHOLD", "0.60"))
RBA_LIQ_RISK_MAX = float(os.getenv("RBA_LIQ_RISK_MAX", "0.60"))
RBA_MARGIN_UTIL_MAX = float(os.getenv("RBA_MARGIN_UTIL_MAX", "75.0"))
RBA_DRAWDOWN_MAX_PCT = float(os.getenv("RBA_DRAWDOWN_MAX_PCT", "20.0"))
RBA_STALE_SEC = int(os.getenv("RBA_STALE_SEC", "120"))
RBA_MOMENTUM_HEDGE_FIRST_BREADTH_VOL_MIN = float(os.getenv("RBA_MOMENTUM_HEDGE_FIRST_BREADTH_VOL_MIN", "0.50"))
RBA_SYMBOL_NORMAL_WHEN_CONFLICT_ENABLED = os.getenv("RBA_SYMBOL_NORMAL_WHEN_CONFLICT_ENABLED", "false").lower() in ("1", "true", "yes", "on")
RBA_SYMBOL_NORMAL_TF_CONFLICT_MIN = float(os.getenv("RBA_SYMBOL_NORMAL_TF_CONFLICT_MIN", "0.58"))
RBA_SYMBOL_NORMAL_WHEN_BREADTH_DISAGREE_ENABLED = os.getenv(
    "RBA_SYMBOL_NORMAL_WHEN_BREADTH_DISAGREE_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")

# ── Adaptive TP Kill Switches ──────────────────────────────────────────────
# Feature flags for adaptive TP logic: set to false to revert to static thresholds
ADAPTIVE_RANGE_TIGHTEN_ENABLED = os.getenv("ADAPTIVE_RANGE_TIGHTEN_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADAPTIVE_STEALTH_TP_ENABLED = os.getenv("ADAPTIVE_STEALTH_TP_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ── Trainer Drawdown Gate ──────────────────────────────────────────────────
# Hard block all new entries when drawdown exceeds this %
TRAINER_DD_BLOCK_PCT = float(os.getenv("TRAINER_DD_BLOCK_PCT", "50.0"))
# Warning level: reduce leverage, but allow predictions
TRAINER_DD_WARN_PCT = float(os.getenv("TRAINER_DD_WARN_PCT", "25.0"))

# Reversal detector parameters (see risk/reversal_detector.py)
REVERSAL_WINDOW_SEC = int(os.getenv("REVERSAL_WINDOW_SEC", "120"))
REVERSAL_MIN_TRIGGERS = int(os.getenv("REVERSAL_MIN_TRIGGERS", "2"))
REVERSAL_BREADTH_DROP = float(os.getenv("REVERSAL_BREADTH_DROP", "0.25"))
REVERSAL_ENTROPY_SPIKE = float(os.getenv("REVERSAL_ENTROPY_SPIKE", "0.25"))
REVERSAL_LIQ_IMBAL_FLIP = float(os.getenv("REVERSAL_LIQ_IMBAL_FLIP", "0.50"))
REVERSAL_FAST_MOVE_SPIKE = float(os.getenv("REVERSAL_FAST_MOVE_SPIKE", "0.60"))
REVERSAL_COOLDOWN_SEC = int(os.getenv("REVERSAL_COOLDOWN_SEC", "180"))
REVERSAL_RECOVERY_ENTROPY_MAX = float(os.getenv("REVERSAL_RECOVERY_ENTROPY_MAX", "0.40"))
REVERSAL_RECOVERY_STRENGTH_MIN = float(os.getenv("REVERSAL_RECOVERY_STRENGTH_MIN", "0.55"))
REVERSAL_CACHE_TTL_SEC = int(os.getenv("REVERSAL_CACHE_TTL_SEC", "300"))

# Safety knobs: cap allocator aggressiveness (first-24h conservative defaults)
RISK_BUDGET_MAX_MULT = float(os.getenv("RISK_BUDGET_MAX_MULT", "1.25"))          # Cap risk_mult even in EXPAND
RISK_BUDGET_MAX_OPEN_SYMBOLS = int(os.getenv("RISK_BUDGET_MAX_OPEN_SYMBOLS", "6"))  # FIX Apr 16: 12→6. Concentrate capital on fewer high-conviction trades instead of spreading thin.
RISK_BUDGET_MIN_CADENCE_SEC = int(os.getenv("RISK_BUDGET_MIN_CADENCE_SEC", "45"))  # Floor on cadence (prevent rapid-fire opens)
REVERSAL_DEFENSIVE_MULT = float(os.getenv("REVERSAL_DEFENSIVE_MULT", "0.70"))    # risk_mult during reversal
REVERSAL_LOCKDOWN_ON_SHOCK = os.getenv("REVERSAL_LOCKDOWN_ON_SHOCK", "true").lower() in ("1", "true", "yes", "on")

# ── Microstructure Toxicity ────────────────────────────────────────────
MICROSTRUCTURE_TOXICITY_ENABLED = os.getenv("MICROSTRUCTURE_TOXICITY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TOXICITY_HIGH_THRESHOLD = float(os.getenv("TOXICITY_HIGH_THRESHOLD", "0.65"))          # Above → toxic
TOXICITY_EXTREME_THRESHOLD = float(os.getenv("TOXICITY_EXTREME_THRESHOLD", "0.85"))    # Above → hard-delay
TOXICITY_CACHE_TTL_SEC = int(os.getenv("TOXICITY_CACHE_TTL_SEC", "300"))  # Must exceed prediction cycle interval (~3min)

# ── Market State Contract ──────────────────────────────────────────────
MARKET_STATE_CONTRACT_ENABLED = os.getenv("MARKET_STATE_CONTRACT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MSC_CONTRACT_CACHE_TTL_SEC = int(os.getenv("MSC_CONTRACT_CACHE_TTL_SEC", "300"))
MSC_INGESTOR_HEALTHY_MAX_AGE_SEC = int(os.getenv("MSC_INGESTOR_HEALTHY_MAX_AGE_SEC", "360"))  # 6min: covers 5m candle gap + buffer
MSC_REGIME_HEALTHY_MAX_AGE_SEC = int(os.getenv("MSC_REGIME_HEALTHY_MAX_AGE_SEC", "600"))
MSC_BREADTH_HEALTHY_MAX_AGE_SEC = int(os.getenv("MSC_BREADTH_HEALTHY_MAX_AGE_SEC", "600"))
MSC_MIN_HEALTHY_FEEDS_PCT = float(os.getenv("MSC_MIN_HEALTHY_FEEDS_PCT", "0.60"))
MSC_MIN_REGIME_KEYS_PCT = float(os.getenv("MSC_MIN_REGIME_KEYS_PCT", "0.60"))

# ── Shared Risk Gate (trader-side enforcement) ─────────────────────────
SHARED_RISK_GATE_ENABLED = os.getenv("SHARED_RISK_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
CONFLICTING_ADD_GATE_ENABLED = os.getenv("CONFLICTING_ADD_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PREFLIGHT_MIN_NOTIONAL_USD = float(os.getenv("PREFLIGHT_MIN_NOTIONAL_USD", "5.0"))  # Hard floor for any order

# ── Order Fill Reconciliation (poll Binance when MARKET ack returns qty=0) ──
ORDER_FILL_RECONCILE_ENABLED = os.getenv("ORDER_FILL_RECONCILE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ORDER_FILL_POLL_MAX_SEC = float(os.getenv("ORDER_FILL_POLL_MAX_SEC", "2.0"))        # Max seconds to poll
ORDER_FILL_POLL_INTERVAL_SEC = float(os.getenv("ORDER_FILL_POLL_INTERVAL_SEC", "0.25"))  # Poll interval

# ── Emergency Account-Level Margin Gate (hard-block risk-adds under stress) ──
EMERGENCY_MARGIN_GATE_ENABLED = os.getenv("EMERGENCY_MARGIN_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
EMERGENCY_MARGIN_RATIO_MIN_PCT = float(os.getenv("EMERGENCY_MARGIN_RATIO_MIN_PCT", "40.0"))   # FIX Apr 15: 20→40% — 20% blocks too aggressively with high-leverage positions
# FIX Apr 15: Raised from 55→75%. With margin_util at 54%, the 55% cap was blocking
# 46% of all trade signals. 75% still protects against dangerous overleverage.
EMERGENCY_MARGIN_USED_MAX_PCT = float(os.getenv("EMERGENCY_MARGIN_USED_MAX_PCT", "75.0"))     # Block if margin_used > 75%
# Protective hedge elevated caps — hedges REDUCE net exposure so they get wider gates
EMERGENCY_MARGIN_RATIO_MIN_PCT_PROTECTIVE = float(os.getenv("EMERGENCY_MARGIN_RATIO_MIN_PCT_PROTECTIVE", "50.0"))
# FIX Apr 15: Raised from 60→85% for protective hedges
EMERGENCY_MARGIN_USED_MAX_PCT_PROTECTIVE = float(os.getenv("EMERGENCY_MARGIN_USED_MAX_PCT_PROTECTIVE", "85.0"))

# ── Margin Governor (unified I1-I4 invariant enforcer) ───────────────────────
# Enforces hard caps on ALL risk-adds.  Protective hedges get an elevated
# symbol cap (Fix M, Feb 2026) so they are not blocked at the same 20% limit
# as speculative entries.
MARGIN_GOVERNOR_ENABLED = os.getenv("MARGIN_GOVERNOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GOV_MAX_ACCOUNT_MARGIN_PCT = float(os.getenv("GOV_MAX_ACCOUNT_MARGIN_PCT", "0.90"))        # I1: totalIM/equity soft cap — 90%
GOV_MAX_ACCOUNT_MARGIN_PCT_PROTECTIVE = float(os.getenv("GOV_MAX_ACCOUNT_MARGIN_PCT_PROTECTIVE", "0.95"))  # I1+: elevated account cap for hedge legs
GOV_MAX_ACCOUNT_MU_PCT = float(os.getenv("GOV_MAX_ACCOUNT_MU_PCT", "95.0"))                # I1: MU% soft cap — 95%
GOV_MAX_SYMBOL_MARGIN_PCT = float(os.getenv("GOV_MAX_SYMBOL_MARGIN_PCT", "0.15"))          # I2: per-symbol IM/equity cap — 15% (raised to allow larger positions)
GOV_MAX_SYMBOL_MARGIN_PCT_PROTECTIVE = float(os.getenv("GOV_MAX_SYMBOL_MARGIN_PCT_PROTECTIVE", "0.15"))  # I2+: protective hedge elevated cap (raised: hedges are risk-reducing)
GOV_PROTECTIVE_CONVERSION_ENABLED = os.getenv("GOV_PROTECTIVE_CONVERSION_ENABLED", "true").lower() in ("1", "true", "yes", "on")  # I3: convert hedge ADD→REDUCE when stressed

# ── Auto-Deleverager (Layer 2: corrective reduce-only closes) ────────────────
# When caps are already breached by existing positions (equity moved, not new adds),
# the deleverager issues reduce-only partial closes to bring margin under cap.
GOV_AUTO_DELEVERAGE_ENABLED = os.getenv("GOV_AUTO_DELEVERAGE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GOV_DELEVERAGE_CADENCE_SEC = float(os.getenv("GOV_DELEVERAGE_CADENCE_SEC", "120.0"))       # Min seconds between reduce actions — give positions room to breathe
GOV_DELEVERAGE_HYSTERESIS_PCT = float(os.getenv("GOV_DELEVERAGE_HYSTERESIS_PCT", "0.03"))   # Reduce until 3pp below cap (prevents thrashing)
GOV_DELEVERAGE_MAX_REDUCE_PCT = float(os.getenv("GOV_DELEVERAGE_MAX_REDUCE_PCT", "0.20"))   # Max 20% of any leg per action
GOV_DELEVERAGE_MIN_REDUCE_USD = float(os.getenv("GOV_DELEVERAGE_MIN_REDUCE_USD", "5.0"))    # Don't bother below $5

# ── Hedge-Aware Deleveraging (pair-reduce for hedge cages) ───────────────────
# When both legs exist on a symbol, reduce proportionally to free margin without
# accidentally flipping net exposure. Prevents "I reduced hedge, exposed main leg."
GOV_DELEVERAGE_HEDGE_AWARE = os.getenv("GOV_DELEVERAGE_HEDGE_AWARE", "true").lower() in ("1", "true", "yes", "on")
GOV_DELEVERAGE_PAIR_REDUCE_RATIO = float(os.getenv("GOV_DELEVERAGE_PAIR_REDUCE_RATIO", "0.6"))   # hedge_leg gets 60% of reduction, main_leg gets 40%
GOV_DELEVERAGE_OVERRIDE_PROFIT_GUARD = os.getenv("GOV_DELEVERAGE_OVERRIDE_PROFIT_GUARD", "true").lower() in ("1", "true", "yes", "on")  # Deleverage bypasses profit-only guard
GOV_DELEVERAGE_OVERRIDE_SAFETY_BLOCK = os.getenv("GOV_DELEVERAGE_OVERRIDE_SAFETY_BLOCK", "true").lower() in ("1", "true", "yes", "on")  # Deleverage bypasses SAFETY_BLOCK_PROTECTIVE_LOSS
ENABLE_STALE_HEDGE_UNWIND_BYPASS = os.getenv("ENABLE_STALE_HEDGE_UNWIND_BYPASS", "true").lower() in ("1", "true", "yes", "on")
STALE_HEDGE_UNWIND_MIN_AGE_SECONDS = int(os.getenv("STALE_HEDGE_UNWIND_MIN_AGE_SECONDS", "900"))

# ── Full Close Protection (prevent single signal from unwinding large positions) ──
FULL_CLOSE_PROTECTION_ENABLED = os.getenv("FULL_CLOSE_PROTECTION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
FULL_CLOSE_MAX_FRACTION = float(os.getenv("FULL_CLOSE_MAX_FRACTION", "0.50"))       # Max 50% per close signal
FULL_CLOSE_PROTECTION_MIN_NOTIONAL_USD = float(os.getenv("FULL_CLOSE_PROTECTION_MIN_NOTIONAL_USD", "500.0"))  # Only protect positions >= $500 notional

# ── Main Leg Tracking (alpha-driven vs hedge) ────────────────────────────────
# Persists which leg is the "main" (alpha model signal) vs "hedge" (protective).
# Redis key: main_leg:{account_id}:{symbol} = LONG|SHORT
MAIN_LEG_TRACKING_ENABLED = os.getenv("MAIN_LEG_TRACKING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MAIN_LEG_TTL_SEC = int(os.getenv("MAIN_LEG_TTL_SEC", "86400"))                 # 24h TTL (refreshed on update)

# ── Position Adoption Framework ──────────────────────────────────────────────
# Scans open positions every 120 s and makes externally-opened (manual) positions
# first-class managed objects with default TP/SL/trailing-stop metadata.
# Redis key: wma:pos_adopted:{account_id}:{symbol}:{side}
# Kill switch: set POSITION_ADOPTION_ENABLED=false to disable scan.
POSITION_ADOPTION_ENABLED = os.getenv("POSITION_ADOPTION_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ── Hedge Cage Exit Policy ───────────────────────────────────────────────────
# Defines automatic exit behavior for symbols with both legs open (hedge cages).
# TIMEOUT_FLAT: flatten both legs gradually if cage persists too long.
HEDGE_CAGE_TIMEOUT_SEC = int(os.getenv("HEDGE_CAGE_TIMEOUT_SEC", "7200"))       # 2h timeout before forced unwind
HEDGE_CAGE_MAX_GROSS_IM_PCT = float(os.getenv("HEDGE_CAGE_MAX_GROSS_IM_PCT", "0.25"))  # 25% of equity max for a single cage
HEDGE_CAGE_ENABLED = os.getenv("HEDGE_CAGE_ENABLED", "false").lower() in ("1", "true", "yes", "on")  # DISABLED Apr 2026: 91 CAGE execs destroyed $2612 margin in 24h
CAGE_TIMEOUT_TRAINER_MIN_CONF = float(os.getenv("CAGE_TIMEOUT_TRAINER_MIN_CONF", "0.75"))  # Min trainer conf to use directional cage exit (raised from 0.55)
CAGE_DIRECTION_FLIP_COOLDOWN_SEC = float(os.getenv("CAGE_DIRECTION_FLIP_COOLDOWN_SEC", "600"))  # 10min cooldown after trainer direction change
CAGE_MAX_TOTAL_REDUCE_PCT = float(os.getenv("CAGE_MAX_TOTAL_REDUCE_PCT", "0.60"))  # Max 60% cumulative reduction per direction cycle
CAGE_MAX_CLOSE_LOSS_USD = float(os.getenv("CAGE_MAX_CLOSE_LOSS_USD", "2.0"))  # CAGE won't realize losses >$2 per close action

# ── Risk State Machine (3-state: NORMAL → STRESSED → EMERGENCY) ─────────────
# Prevents deleverager thrashing by requiring breach persistence + hysteresis.
# NORMAL: deleverage OFF, adds allowed. STRESSED: deleverage OFF, adds blocked.
# EMERGENCY: deleverage ON (only after N consecutive breaches above high-water).
RISK_STATE_MACHINE_ENABLED = os.getenv("RISK_STATE_MACHINE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Hysteresis thresholds: separate high-water (trigger) and low-water (recovery)
# MU thresholds (margin utilization %, 0-100 scale)
RISK_STRESS_MU_HIGH = float(os.getenv("RISK_STRESS_MU_HIGH", "70.0"))          # MU above → enter STRESSED
RISK_STRESS_MU_LOW = float(os.getenv("RISK_STRESS_MU_LOW", "60.0"))            # MU below → recover from STRESSED
RISK_EMERGENCY_MU_HIGH = float(os.getenv("RISK_EMERGENCY_MU_HIGH", "85.0"))    # MU above → enter EMERGENCY (after streak)
RISK_EMERGENCY_MU_LOW = float(os.getenv("RISK_EMERGENCY_MU_LOW", "75.0"))      # MU below → recover from EMERGENCY

# IM thresholds (initial margin ratio, 0-1 scale)
RISK_STRESS_IM_HIGH = float(os.getenv("RISK_STRESS_IM_HIGH", "0.65"))          # IM above → enter STRESSED
RISK_STRESS_IM_LOW = float(os.getenv("RISK_STRESS_IM_LOW", "0.55"))            # IM below → recover from STRESSED
RISK_EMERGENCY_IM_HIGH = float(os.getenv("RISK_EMERGENCY_IM_HIGH", "0.80"))    # IM above → enter EMERGENCY (after streak)
RISK_EMERGENCY_IM_LOW = float(os.getenv("RISK_EMERGENCY_IM_LOW", "0.70"))      # IM below → recover from EMERGENCY

# Breach persistence: consecutive checks above emergency threshold before action
RISK_BREACH_STREAK_REQUIRED = int(os.getenv("RISK_BREACH_STREAK_REQUIRED", "5"))  # Need 5 consecutive breaches (150s at 30s cadence) before EMERGENCY deleverage fires

# Edge feed: regime-based directional signal for smart leg selection
RISK_EDGE_MIN_ALIGNMENT = float(os.getenv("RISK_EDGE_MIN_ALIGNMENT", "0.25"))  # Min tf_alignment magnitude to act on

# ── Reduce-Only Latch (Fix #1) ──────────────────────────────────────────────
# When a deleverager action fires, set a Redis latch that blocks ALL risk-adds
# (ENTRY, INCREASE, ADD_HEDGE, scale-in) for N seconds. Only CLOSE/TP/stop pass.
REDUCE_ONLY_LATCH_ENABLED = os.getenv("REDUCE_ONLY_LATCH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
REDUCE_ONLY_LATCH_SECONDS = int(os.getenv("REDUCE_ONLY_LATCH_SECONDS", "180"))  # 3 min default (was 900s/15min — too long, blocked re-entry during correct predictions)
REDUCE_ONLY_LATCH_KEY_PREFIX = "risk:reduce_only_until"  # Redis key: {prefix}:{account_id}
# TRAINER INTENT BYPASS: When trainer has active directional intent matching a
# re-entry signal, bypass the reduce-only latch. This prevents the cascade where
# a correct prediction gets closed and then can't re-enter for 15 minutes.
REDUCE_ONLY_LATCH_TRAINER_BYPASS = os.getenv("REDUCE_ONLY_LATCH_TRAINER_BYPASS", "true").lower() in ("1", "true", "yes", "on")

# ── Deleverager Hard-Emergency Threshold (Fix #2) ────────────────────────────
# Deleverager ONLY fires when MU or IM reaches "liquidation risk" territory.
# Soft breaches (65-85%) are handled by governor blocking entries — no force-close.
DELEVERAGE_HARD_MU_THRESHOLD = float(os.getenv("DELEVERAGE_HARD_MU_THRESHOLD", "90.0"))      # MU% above this = force-close (only true liquidation risk)
DELEVERAGE_HARD_IM_THRESHOLD = float(os.getenv("DELEVERAGE_HARD_IM_THRESHOLD", "0.90"))       # IM/eq above this = force-close (only true liquidation risk)
DELEVERAGE_SOFT_ONLY_BLOCK = os.getenv("DELEVERAGE_SOFT_ONLY_BLOCK", "true").lower() in ("1", "true", "yes", "on")  # true = soft breaches only block, don't cut
GOV_DELEVERAGE_MODE = os.getenv("GOV_DELEVERAGE_MODE", "state_machine")  # "state_machine" = trust RSM EMERGENCY, "hard_only" = old behavior
# When GOV_DELEVERAGE_MODE = "state_machine", skip the hard threshold check if RSM says EMERGENCY
# This allows the state machine's streak-based persistence to drive deleveraging decisions
# If True (default): never auto-deleverage for per-symbol margin cap alone unless MU/IM are in hard-emergency band.
DELEVERAGE_SYMBOL_VIOLATION_REQUIRES_HARD_EMERGENCY = os.getenv(
    "DELEVERAGE_SYMBOL_VIOLATION_REQUIRES_HARD_EMERGENCY", "true"
).lower() in ("1", "true", "yes", "on")

# ── Proactive Portfolio Health Monitor (Feb 2026) ────────────────────────────
# Background thread in trader that ticks every N seconds, logs margin state,
# and triggers reduce-only latch + partial closes when soft-breach persists.
# This closes the gap where governor blocks entries but nobody actively reduces.
PROACTIVE_HEALTH_MONITOR_ENABLED = os.getenv("PROACTIVE_HEALTH_MONITOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PROACTIVE_HEALTH_MONITOR_CADENCE_SEC = float(os.getenv("PROACTIVE_HEALTH_MONITOR_CADENCE_SEC", "30.0"))
# Soft-breach reduction: when MU stays above soft cap for N consecutive ticks
# AND positions are losing, start reducing worst losers to bring MU down.
PROACTIVE_SOFT_REDUCE_ENABLED = os.getenv("PROACTIVE_SOFT_REDUCE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PROACTIVE_SOFT_REDUCE_MU_THRESHOLD = float(os.getenv("PROACTIVE_SOFT_REDUCE_MU_THRESHOLD", "85.0"))  # MU% above this AND losing = start trimming (was 70 — too aggressive)
PROACTIVE_SOFT_REDUCE_STREAK_REQUIRED = int(os.getenv("PROACTIVE_SOFT_REDUCE_STREAK_REQUIRED", "8"))  # 8 consecutive ticks (~4 min) above threshold before reducing
PROACTIVE_SOFT_REDUCE_MAX_PCT = float(os.getenv("PROACTIVE_SOFT_REDUCE_MAX_PCT", "0.10"))  # Max 10% per action
PROACTIVE_SOFT_REDUCE_LOSS_BUDGET_PCT = float(os.getenv("PROACTIVE_SOFT_REDUCE_LOSS_BUDGET_PCT", "5.0"))  # Max 5% equity loss realization per hour
# Hedge add throttle: max hedge-add actions per minute to prevent hedge domination
HEDGE_ADD_MAX_PER_MINUTE = int(os.getenv("HEDGE_ADD_MAX_PER_MINUTE", "3"))  # TIGHTENED Apr 2026: was 8 (480/hr theoretical); 3/min = max 180/hr

# ── Orchestrator Entry Spam Cap (Fix #3) ─────────────────────────────────────
# Hard cap on new ENTRY signals published per orchestrator cycle.
ORCH_MAX_NEW_ENTRIES_PER_CYCLE = int(os.getenv("ORCH_MAX_NEW_ENTRIES_PER_CYCLE", "12"))  # Raised from 6: trainer fires 15+ signals in <1s sweep, 6 was too tight
ORCH_MAX_NEW_INCREASES_PER_CYCLE = int(os.getenv("ORCH_MAX_NEW_INCREASES_PER_CYCLE", "6"))    # Max 6 per cycle (raised from 4)
ORCH_MAX_NEW_HEDGES_PER_CYCLE = int(os.getenv("ORCH_MAX_NEW_HEDGES_PER_CYCLE", "8"))          # Max 8 per cycle (raised from 5)

# When ADD_HEDGE_* fails ORCH liq precheck (LIQ_TOO_LOW / LIQ_NONE), optionally rewrite to
# reduce-only PARTIAL_CLOSE on the existing main leg (see orchestrator_worker._try_hedge_liq_fail_fallback).
ORCH_HEDGE_LIQ_FAIL_FALLBACK_ENABLED = os.getenv(
    "ORCH_HEDGE_LIQ_FAIL_FALLBACK_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
ORCH_HEDGE_LIQ_FAIL_CLOSE_FRACTION = float(os.getenv("ORCH_HEDGE_LIQ_FAIL_CLOSE_FRACTION", "0.35"))

ORCH_MAX_CONCURRENT_POSITIONS = int(os.getenv("ORCH_MAX_CONCURRENT_POSITIONS", "16"))         # Max 16 unique symbols (raised from 12)

# ── Symbol Cap Clamp (Fix #4) ───────────────────────────────────────────────
# Instead of hard-blocking when requested_margin slightly exceeds symbol cap,
# clamp down to (cap - epsilon).  Prevents "impossible by $1.50" blocks.
SYMBOL_CAP_CLAMP_EPSILON_USD = float(os.getenv("SYMBOL_CAP_CLAMP_EPSILON_USD", "0.50"))      # $0.50 buffer below cap
SYMBOL_CAP_CLAMP_MIN_USD = float(os.getenv("SYMBOL_CAP_CLAMP_MIN_USD", "5.0"))               # Don't trade if clamped below $5

# ── Hedge Swap Under Tight Margin (Fix #4) ──────────────────────────────────
# When hedge is needed but MU is tight, convert ADD_HEDGE into a swap:
# partial-close main leg to free margin, then open hedge with freed margin.
HEDGE_SWAP_ENABLED = os.getenv("HEDGE_SWAP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HEDGE_SWAP_MU_THRESHOLD = float(os.getenv("HEDGE_SWAP_MU_THRESHOLD", "0.40"))  # MU above this → convert hedge-add to swap

# ============================================================================
# DYNAMIC SIZING
# ============================================================================
BASE_OPEN_MARGIN_USD = float(os.getenv("BASE_OPEN_MARGIN_USD", "150.0"))  # Raised from 40: aggressive sizing for 1-2x equity/day target
TARGET_OPEN_MARGIN_USD = float(os.getenv("TARGET_OPEN_MARGIN_USD", "350.0"))  # Raised from 100: aggressive allocation for 1-2x equity/day target
MAX_OPEN_MARGIN_USD = float(os.getenv("MAX_OPEN_MARGIN_USD", "600.0"))  # Doubled to $600: allow larger positions
MAX_TOTAL_MARGIN_PCT_EQUITY = float(os.getenv("MAX_TOTAL_MARGIN_PCT_EQUITY", "0.95"))
MAX_MARGIN_PER_SYMBOL_PCT_EQUITY = float(os.getenv("MAX_MARGIN_PER_SYMBOL_PCT_EQUITY", "0.30"))  # Raised from 0.15: 30% equity per symbol for aggressive sizing

# Orchestrator respects trainer's dynamic margin instead of recalculating from scratch.
# When True: trainer's confidence-scaled margin flows through with only safety caps applied.
# When False: legacy mode where orchestrator recalculates margin from equity * base_symbol_pct * quality factors.
ORCH_RESPECT_TRAINER_MARGIN = os.getenv("ORCH_RESPECT_TRAINER_MARGIN", "true").lower() in ("1", "true", "yes", "on")

# Priority symbols: BTC, ETH, SOL always get slot reservation and budget priority.
# These are allocated first before other symbols compete for remaining slots.
PRIORITY_SYMBOLS = [s.strip() for s in os.getenv("PRIORITY_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
PRIORITY_SYMBOL_MIN_MARGIN_PCT = float(os.getenv("PRIORITY_SYMBOL_MIN_MARGIN_PCT", "0.05"))  # Min 5% equity per priority symbol

# Safe-mode: hard block new opens when margin_util exceeds this threshold (approaching danger zone)
# Raised to 75% to match GOV_MAX_ACCOUNT_MU_PCT — prevents premature blocking while governor handles soft cap
ORCH_SAFE_MODE_MARGIN_UTIL_BLOCK = float(os.getenv("ORCH_SAFE_MODE_MARGIN_UTIL_BLOCK", "0.80"))  # 80% MU → hard block all risk-add (last-resort gate)
ORCH_SAFE_MODE_ENABLED = os.getenv("ORCH_SAFE_MODE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# ── Prediction Quality Control (PQC) ─────────────────────────────────────────
# Prevents degenerate trainer predictions (always LONG, saturated confidence) from
# becoming real trades. Enforces observation health, entropy gating, and direction
# diversity at the trainer level — before signals reach orchestrator/trader.

# PPO confidence calibration: tau controls the sigmoid sharpness for logit-margin
# confidence. Default 0.35 produces saturated 0.9999 for any decisive model.
# Raised to 2.0 so confidence reflects actual uncertainty (sigmoid(margin/2.0)).
PPO_MARGIN_CONF_TAU = float(os.getenv("PPO_MARGIN_CONF_TAU", "2.0"))

# PPO Inference Temperature: Controls action selection during inference.
# >1.0: Flattens probability distribution (more exploration/diversity)
# =1.0: Standard softmax (no change)
# <1.0: Sharpens distribution (more exploitation)
# =0.0: Reverts to deterministic argmax (old behavior)
# FIX Apr 14 2026: Model collapsed to 93% HOLD because argmax always picks
# the highest-probability action. At temperature=1.5, HOLD drops from 93%
# selection to ~40%, allowing non-HOLD signals through the pipeline.
# The confidence gating system then filters out low-quality predictions.
PPO_INFERENCE_TEMPERATURE = float(os.getenv("PPO_INFERENCE_TEMPERATURE", "1.5"))

# Momentum alignment gate: reduces confidence when prediction contradicts
# recent price momentum (5m pct change). Prevents publishing counter-trend
# signals from a fresh/undertrained model. Disable once model is mature.
MOMENTUM_GATE_ENABLED = os.getenv("MOMENTUM_GATE_ENABLED", "true").lower() in ("1", "true", "yes")

# Entropy gating: minimum normalized entropy required for an ENTRY prediction.
# If norm_entropy is below this, the model is "too certain" — likely collapsed.
# Range [0,1]: 0=perfectly concentrated, 1=uniform distribution.
PQC_MIN_NORM_ENTROPY_ENTRY = float(os.getenv("PQC_MIN_NORM_ENTROPY_ENTRY", "0.10"))

# Observation health: if more than this fraction of features are zero or NaN,
# the prediction is forced to HOLD with confidence 0.
PQC_MAX_ZERO_FRAC = float(os.getenv("PQC_MAX_ZERO_FRAC", "0.90"))      # 90% zeros = unhealthy
PQC_MAX_NAN_FRAC = float(os.getenv("PQC_MAX_NAN_FRAC", "0.05"))        # 5% NaN = unhealthy

# Feature staleness: if features are older than this, force HOLD.
PQC_MAX_STALENESS_MS = int(os.getenv("PQC_MAX_STALENESS_MS", "120000"))  # 2 minutes

# Trainer-stuck watchdog: if LONG_rate > threshold over last N predictions,
# set a Redis latch blocking ENTRY signals for cooldown period.
PQC_STUCK_DIRECTION_THRESHOLD = float(os.getenv("PQC_STUCK_DIRECTION_THRESHOLD", "0.85"))  # >85% same direction
PQC_STUCK_WINDOW_SIZE = int(os.getenv("PQC_STUCK_WINDOW_SIZE", "100"))                     # Over last 100 predictions
PQC_STUCK_COOLDOWN_SEC = int(os.getenv("PQC_STUCK_COOLDOWN_SEC", "1800"))                  # 30 min cooldown
PQC_STUCK_LATCH_KEY = "risk:trainer_stuck_until"                                           # Redis key
PQC_STUCK_ENABLED = os.getenv("PQC_STUCK_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# QC stream: prediction diagnostics published for monitoring.
PQC_STREAM_NAME = os.getenv("PQC_STREAM_NAME", "wma:predictions_qc")
PQC_STREAM_MAXLEN = int(os.getenv("PQC_STREAM_MAXLEN", "50000"))
PQC_STREAM_ENABLED = os.getenv("PQC_STREAM_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Ramp budget scaling (allow extra positions when risk headroom is ample)
RAMP_BUDGET_SCALING_ENABLED = os.getenv("RAMP_BUDGET_SCALING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
RAMP_BUDGET_MAX_EXTRA_POSITIONS = int(os.getenv("RAMP_BUDGET_MAX_EXTRA_POSITIONS", "2"))  # Allow 2 extra positions beyond base when risk is ample
RAMP_BUDGET_MAX_POSITIONS_CAP = int(os.getenv("RAMP_BUDGET_MAX_POSITIONS_CAP", "15"))  # Unlocked: 15 symbols (aligned with PORTFOLIO_BASE_MAX_POSITIONS)
RAMP_BUDGET_MARGIN_UTIL_TARGET = float(os.getenv("RAMP_BUDGET_MARGIN_UTIL_TARGET", "0.55"))
RAMP_BUDGET_MARGIN_UTIL_MAX = float(os.getenv("RAMP_BUDGET_MARGIN_UTIL_MAX", "0.70"))
RAMP_BUDGET_FEE_UTIL_MAX = float(os.getenv("RAMP_BUDGET_FEE_UTIL_MAX", "0.80"))
RAMP_BUDGET_REQUIRE_FEE_DATA = os.getenv("RAMP_BUDGET_REQUIRE_FEE_DATA", "true").lower() in ("1", "true", "yes", "on")

# ============================================================================
# PnL DECOMPOSITION STREAM
# ============================================================================
ENABLE_PNL_DECOMP = os.getenv("ENABLE_PNL_DECOMP", "true").lower() in ("1", "true", "yes", "on")
PNL_DECOMP_STREAM = os.getenv("PNL_DECOMP_STREAM", "wma:pnl_decomp")
PNL_DECOMP_MAXLEN = int(os.getenv("PNL_DECOMP_MAXLEN", "200000"))
PNL_DECOMP_PRIMARY_STREAM = os.getenv("PNL_DECOMP_PRIMARY_STREAM", "pnl:decomp")
PNL_DECOMP_ROLLUP_1H_TTL_SEC = int(os.getenv("PNL_DECOMP_ROLLUP_1H_TTL_SEC", "7200"))
PNL_DECOMP_ROLLUP_1D_TTL_SEC = int(os.getenv("PNL_DECOMP_ROLLUP_1D_TTL_SEC", "172800"))
PNL_DECOMP_FUNDING_LOOKBACK_MS = int(os.getenv("PNL_DECOMP_FUNDING_LOOKBACK_MS", "3600000"))

# =========================================================================
# DQ SCORE / DQ GATING (Orchestrator)
# =========================================================================
DQ_SCORE_BLOCK_BELOW = float(os.getenv("DQ_SCORE_BLOCK_BELOW", "0.50"))
DQ_SCORE_DOWNSIZE_BELOW = float(os.getenv("DQ_SCORE_DOWNSIZE_BELOW", "0.80"))
DQ_SCORE_OB_MAX_AGE_MS = int(os.getenv("DQ_SCORE_OB_MAX_AGE_MS", "15000"))
DQ_SCORE_LIQMAP_MAX_AGE_MS = int(os.getenv("DQ_SCORE_LIQMAP_MAX_AGE_MS", "90000"))
DQ_SCORE_WEIGHTS = {
    "orderbook": float(os.getenv("DQ_SCORE_WEIGHT_ORDERBOOK", "0.30")),
    "liqmap": float(os.getenv("DQ_SCORE_WEIGHT_LIQMAP", "0.30")),
    "liq_distance": float(os.getenv("DQ_SCORE_WEIGHT_LIQ_DISTANCE", "0.20")),
    "depth": float(os.getenv("DQ_SCORE_WEIGHT_DEPTH", "0.20")),
}
DQ_MIN_TIER_MARGIN_USD = float(os.getenv("DQ_MIN_TIER_MARGIN_USD", "25.0"))

# =========================================================================
# ORDERBOOK SOURCE PRIORITY (Microstructure)
# =========================================================================
# Orchestrator will prefer CoinAPI WSDS msnap hashes and fall back to Binance
# when CoinAPI is stale/missing/incomplete.
OB_SOURCE_PRIORITY = [s.strip() for s in os.getenv("OB_SOURCE_PRIORITY", "coinapi_wsds,binance_ws").split(",") if s.strip()]
OB_DEPTH_BPS_WINDOWS = [int(x) for x in os.getenv("OB_DEPTH_BPS_WINDOWS", "10,25").split(",") if str(x).strip().isdigit()]

# Tiered max-age (ms) for orderbook snapshot selection.
# Tier0: strict (risk-add opens/flips)
# Tier1: normal (holds/info)
# Tier2: permissive (protective reduces/closes)
OB_PICK_MAX_AGE_TIER0_MS = int(os.getenv("OB_PICK_MAX_AGE_TIER0_MS", "2500"))
OB_PICK_MAX_AGE_TIER1_MS = int(os.getenv("OB_PICK_MAX_AGE_TIER1_MS", "8000"))
OB_PICK_MAX_AGE_TIER2_MS = int(os.getenv("OB_PICK_MAX_AGE_TIER2_MS", "15000"))

OB_PICK_REQUIRE_BEST_BID_ASK = os.getenv("OB_PICK_REQUIRE_BEST_BID_ASK", "true").lower() in ("1", "true", "yes", "on")
OB_PICK_REQUIRE_DEPTH_WINDOWS = os.getenv("OB_PICK_REQUIRE_DEPTH_WINDOWS", "false").lower() in ("1", "true", "yes", "on")

# DQ penalty applied when Binance fallback is used (depth source not CoinAPI).
DQ_SCORE_BINANCE_FALLBACK_PENALTY = float(os.getenv("DQ_SCORE_BINANCE_FALLBACK_PENALTY", "0.05"))

# =========================================================================
# PORTFOLIO RISK TIERS (Adaptive Scaling)
# =========================================================================
PORTFOLIO_TIER_ENABLED = os.getenv("PORTFOLIO_TIER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PORTFOLIO_TIER_DD_PROTECT_PCT = float(os.getenv("PORTFOLIO_TIER_DD_PROTECT_PCT", "4.0"))
PORTFOLIO_TIER_DD_AGG_PCT = float(os.getenv("PORTFOLIO_TIER_DD_AGG_PCT", "1.5"))
PORTFOLIO_TIER_FEE_BURN_PROTECT_PCT = float(os.getenv("PORTFOLIO_TIER_FEE_BURN_PROTECT_PCT", "0.6"))
PORTFOLIO_TIER_FEE_BURN_AGG_PCT = float(os.getenv("PORTFOLIO_TIER_FEE_BURN_AGG_PCT", "0.25"))
PORTFOLIO_TIER_DQ_PROTECT_PCT = float(os.getenv("PORTFOLIO_TIER_DQ_PROTECT_PCT", "70.0"))
PORTFOLIO_TIER_DQ_AGG_PCT = float(os.getenv("PORTFOLIO_TIER_DQ_AGG_PCT", "90.0"))

PORTFOLIO_TIER_MAX_POSITIONS = {
    0: int(os.getenv("PORTFOLIO_TIER0_MAX_POSITIONS", "15")),
    1: int(os.getenv("PORTFOLIO_TIER1_MAX_POSITIONS", "18")),
    2: int(os.getenv("PORTFOLIO_TIER2_MAX_POSITIONS", "22")),
}
PORTFOLIO_TIER_MAX_TOTAL_MARGIN_PCT = {
    0: float(os.getenv("PORTFOLIO_TIER0_MAX_TOTAL_MARGIN_PCT", "0.50")),
    1: float(os.getenv("PORTFOLIO_TIER1_MAX_TOTAL_MARGIN_PCT", "0.50")),
    2: float(os.getenv("PORTFOLIO_TIER2_MAX_TOTAL_MARGIN_PCT", "0.55")),
}
PORTFOLIO_TIER_MAX_MARGIN_PER_SYMBOL_PCT = {
    0: float(os.getenv("PORTFOLIO_TIER0_MAX_MARGIN_PER_SYMBOL_PCT", "0.20")),   # Raised from 0.10 for aggressive sizing
    1: float(os.getenv("PORTFOLIO_TIER1_MAX_MARGIN_PER_SYMBOL_PCT", "0.25")),   # Raised from 0.15 for aggressive sizing
    2: float(os.getenv("PORTFOLIO_TIER2_MAX_MARGIN_PER_SYMBOL_PCT", "0.30")),   # Raised from 0.18 for aggressive sizing
}
PORTFOLIO_TIER_BASE_SYMBOL_PCT = {
    0: float(os.getenv("PORTFOLIO_TIER0_BASE_SYMBOL_PCT", "0.08")),   # Raised from 0.05: 8% equity per position
    1: float(os.getenv("PORTFOLIO_TIER1_BASE_SYMBOL_PCT", "0.12")),   # Raised from 0.10: 12% equity per position = ~$178 at $1480 eq
    2: float(os.getenv("PORTFOLIO_TIER2_BASE_SYMBOL_PCT", "0.15")),   # Raised from 0.12: 15% aggressive
}

# ============================================================================
# HEDGE GATE BYPASS (Jan 2026 - Live safety / recovery)
# ============================================================================
# When true, hedge-category actions MUST NOT be blocked by governance gates
# such as confidence thresholds, budgets/cooldowns, or execution timing gates.
# Note: Exchange-level hard constraints still apply (e.g., hedge mode disabled,
# absolute margin caps, min notional).
HEDGE_BYPASS_ALL_GATES = os.getenv("HEDGE_BYPASS_ALL_GATES", "true").lower() in ("1", "true", "yes")
TRAINER_FLIP_COOLDOWN_MS = int(os.getenv("TRAINER_FLIP_COOLDOWN_MS", "900000"))  # 15 min per-symbol flip cooldown in trainer
TRAINER_ACTION_DEDUPE_MS = int(os.getenv("TRAINER_ACTION_DEDUPE_MS", "60000"))   # 1 min cross-TF action dedupe
TRAINER_ALIGN_MIN_CONF_TO_BLOCK = float(os.getenv("TRAINER_ALIGN_MIN_CONF_TO_BLOCK", "0.60"))  # Min trainer consensus conf to enforce DIRECTION_CONFLICT block (below = passthrough)
TRADER_FLIP_COOLDOWN_MS = int(os.getenv("TRADER_FLIP_COOLDOWN_MS", "600000"))    # 10 min per-symbol flip cooldown in trader

# ========== REGIME-AWARE MASA-PPO BLENDING ==========
# When enabled, _blend_masa_ppo_logits adjusts MASA weight based on market regime
# computed by _compute_regime_axes(). Trending → more MASA, crisis → less MASA.
REGIME_BLEND_ENABLED = os.getenv("REGIME_BLEND_ENABLED", "true").lower() in ("1", "true", "yes")
REGIME_BLEND_TRENDING_MULT = float(os.getenv("REGIME_BLEND_TRENDING_MULT", "1.2"))   # MASA weight × 1.2 in trending regimes
REGIME_BLEND_VOLATILE_MULT = float(os.getenv("REGIME_BLEND_VOLATILE_MULT", "0.7"))   # MASA weight × 0.7 in volatile/choppy regimes
REGIME_BLEND_CRISIS_MULT = float(os.getenv("REGIME_BLEND_CRISIS_MULT", "0.5"))       # MASA weight × 0.5 in crisis/panic regimes

# OPEN_RISK only: when PPO is strong but MASA drags the blend just under threshold, nudge confidence toward PPO.
ADAPTIVE_PPO_MASA_RELIEVE_ENABLED = os.getenv("ADAPTIVE_PPO_MASA_RELIEVE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
ADAPTIVE_PPO_MASA_RELIEVE_PPO_MIN = float(os.getenv("ADAPTIVE_PPO_MASA_RELIEVE_PPO_MIN", "0.72"))
ADAPTIVE_PPO_MASA_RELIEVE_MASA_MAX = float(os.getenv("ADAPTIVE_PPO_MASA_RELIEVE_MASA_MAX", "0.55"))
ADAPTIVE_PPO_MASA_RELIEVE_MAX_GAP = float(os.getenv("ADAPTIVE_PPO_MASA_RELIEVE_MAX_GAP", "0.035"))
ADAPTIVE_PPO_MASA_RELIEVE_W_PPO = float(os.getenv("ADAPTIVE_PPO_MASA_RELIEVE_W_PPO", "0.65"))

# ========== DECONFLICTION CHURN PROTECTION (Per-Symbol Publish Cooldown) ==========
# After publishing ANY signal for a symbol, enforce cooldown before publishing another.
# PROTECTIVE and HEDGE signals bypass this cooldown (safety-critical).
DECONFLICT_SYMBOL_COOLDOWN_ENABLED = os.getenv("DECONFLICT_SYMBOL_COOLDOWN_ENABLED", "true").lower() in ("1", "true", "yes")
DECONFLICT_SYMBOL_COOLDOWN_OPEN_SEC = int(os.getenv("DECONFLICT_SYMBOL_COOLDOWN_OPEN_SEC", "90"))    # Cooldown for OPEN_RISK signals (seconds)
DECONFLICT_SYMBOL_COOLDOWN_OTHER_SEC = int(os.getenv("DECONFLICT_SYMBOL_COOLDOWN_OTHER_SEC", "45"))   # Cooldown for other non-protective signals

# ── Dynamic Churn Cooldown (replaces static cooldown when enabled) ──
DYNAMIC_CHURN_COOLDOWN_ENABLED = os.getenv("DYNAMIC_CHURN_COOLDOWN_ENABLED", "true").lower() in ("1", "true", "yes")
CHURN_COOLDOWN_BASE_SEC = float(os.getenv("CHURN_COOLDOWN_BASE_SEC", "30"))
CHURN_COOLDOWN_MIN_SEC = float(os.getenv("CHURN_COOLDOWN_MIN_SEC", "10"))
CHURN_COOLDOWN_MAX_SEC = float(os.getenv("CHURN_COOLDOWN_MAX_SEC", "120"))
TRADER_MAX_ORDERS_PER_SYMBOL_PER_MIN = int(os.getenv("TRADER_MAX_ORDERS_PER_SYMBOL_PER_MIN", "2"))  # Rate limit: max orders/symbol/min
PORTFOLIO_MAX_AGE_MS = int(os.getenv("PORTFOLIO_MAX_AGE_MS", "120000"))  # 2 min portfolio staleness threshold

# ========== NEW: REVERSAL CONFIRMATION GATE (Prevent close-then-opposite at tops/bottoms) ==========
REVERSAL_CONFIRMATION_WINDOW_MS = int(os.getenv("REVERSAL_CONFIRMATION_WINDOW_MS", "120000"))  # 2 min confirmation after close
REVERSAL_HIGH_CONF_OVERRIDE = float(os.getenv("REVERSAL_HIGH_CONF_OVERRIDE", "0.95"))  # 95%+ confidence can override

# ========== NEW: EXIT-AWARE RE-ENTRY HYSTERESIS (No cooldown timers) ==========
# Goal: if a symbol was just closed (including manual/external closes), do NOT immediately re-open
# at effectively the same price. Require "new evidence" (better price or ultra fast-move override).
REENTRY_HYSTERESIS_ENABLED = os.getenv("REENTRY_HYSTERESIS_ENABLED", "true").lower() in ("1", "true", "yes")
REENTRY_MIN_PRICE_IMPROVEMENT_PCT = float(os.getenv("REENTRY_MIN_PRICE_IMPROVEMENT_PCT", "0.30"))  # 0.30% better price vs last exit

# ============================================================================
# PHASE 1: MULTI-TIMEFRAME PYRAMID HIERARCHY (Profitability Governance)
# ============================================================================
# Establishes clear roles for each timeframe to prevent multi-TF signal spam
# and improve signal quality through hierarchical confirmation
#
# Timeframe Roles:
#   4h: BIAS only (LONG_ONLY/SHORT_ONLY/NEUTRAL) - never direct OPEN_RISK
#   1h: CONFIRMATION - confirms or invalidates bias
#   15m: TRIGGER - generates primary entry/exit intent
#   5m: EXECUTION GATE - approves/denies timing using microstructure
#   1m: PROTECTIVE ONLY - never OPEN_RISK or HEDGE

TF_HIERARCHY_ENABLED = os.getenv("TF_HIERARCHY_ENABLED", "true").lower() in ("1", "true", "yes")
# Kill switch: disables the PQC gate that blocks entry actions when prediction:SYM:TF keys
# are empty (e.g. after trainer restart). Default=False to prevent self-reinforcing deadlock.
# Enable only after prediction: keys are populated across all TFs.
TF_STACK_PQC_GATE_ENABLED = os.getenv("TF_STACK_PQC_GATE_ENABLED", "false").lower() in ("1", "true", "yes")
TF_BIAS_TF = os.getenv("TF_BIAS_TF", "4h")        # Macro bias timeframe
TF_CONFIRM_TF = os.getenv("TF_CONFIRM_TF", "1h")  # Confirmation timeframe
TF_TRIGGER_TF = os.getenv("TF_TRIGGER_TF", "15m") # Tactical trigger timeframe
TF_EXEC_TF = os.getenv("TF_EXEC_TF", "5m")        # Execution gate timeframe
TF_PROTECT_TF = os.getenv("TF_PROTECT_TF", "1m")  # Protective-only timeframe

# ============================================================================
# TF SIGNAL GENERATION CONTROLS (2026-04-02)
# ============================================================================
# Allow all TFs except 1m to generate entry signals (not just 15m trigger)
# This enables the model to learn per-TF directional accuracy
TF_ALL_GENERATE_SIGNALS = os.getenv("TF_ALL_GENERATE_SIGNALS", "false").lower() in ("1", "true", "yes")
# TFs that can generate OPEN_RISK signals (if TF_ALL_GENERATE_SIGNALS=true)
TF_SIGNAL_GENERATOR_TFS = [x.strip() for x in os.getenv("TF_SIGNAL_GENERATOR_TFS", "15m,1h").split(",") if x.strip()]
TF_ROLE_ENFORCEMENT_ENABLED = os.getenv("TF_ROLE_ENFORCEMENT_ENABLED", "true").lower() in ("1", "true", "yes")
# Per-TF minimum confidence for signal generation (override global)
# CRITICAL: Based on directional accuracy analysis (Apr 2026):
# NOTE (Apr 2026): Live PPO confidence currently clusters ~0.50–0.70 for many symbols.
# Defaults must stay within that reachable range or the entire multi-TF stack deadlocks.
TF_MIN_CONF_5M = float(os.getenv("TF_MIN_CONF_5M", "0.40"))   # Honest scale: top1=0.49→conf=0.41. 5m noisiest, higher bar
TF_MIN_CONF_15M = float(os.getenv("TF_MIN_CONF_15M", "0.35"))  # Honest: top1=0.44→conf=0.35
TF_MIN_CONF_1H = float(os.getenv("TF_MIN_CONF_1H", "0.30"))    # Honest: top1=0.40→conf=0.30
TF_MIN_CONF_4H = float(os.getenv("TF_MIN_CONF_4H", "0.25"))    # Honest: top1=0.36→conf=0.25

# ============================================================================
# OPERATOR POLICY GATES (Trainer/Orchestrator; trader remains hard safety)
# ============================================================================
# Enforces deterministic live gates:
# - Main leg selected from HTF stack (4h+1h)
# - Stress freeze blocks hedge TP trims when main leg risk is elevated
# - Hedge coverage target bands (normal vs stress)
# - Main adds only in aligned/safe conditions
OPERATOR_POLICY_GATES_ENABLED = os.getenv("OPERATOR_POLICY_GATES_ENABLED", "true").lower() in ("1", "true", "yes")

# P0 protective bypass controls (must remain feature-flagged)
PROTECTIVE_BYPASS_KILL_SWITCH = os.getenv("PROTECTIVE_BYPASS_KILL_SWITCH", "true").lower() in ("1", "true", "yes")
PROTECTIVE_BYPASS_STALE_FEATURES = os.getenv("PROTECTIVE_BYPASS_STALE_FEATURES", "true").lower() in ("1", "true", "yes")
PROTECTIVE_MAX_ADD_PER_CYCLE_PCT = float(os.getenv("PROTECTIVE_MAX_ADD_PER_CYCLE_PCT", "0.10"))

# HTF weighted stack cutoffs for top bias
OP_BIAS_BULLISH_MIN = float(os.getenv("OP_BIAS_BULLISH_MIN", "0.75"))
OP_BIAS_BEARISH_MAX = float(os.getenv("OP_BIAS_BEARISH_MAX", "-0.75"))

# Liq buffer bands (bps)
OP_LIQ_BPS_SAFE = float(os.getenv("OP_LIQ_BPS_SAFE", "300"))
OP_LIQ_BPS_CAUTION = float(os.getenv("OP_LIQ_BPS_CAUTION", "200"))
OP_LIQ_BPS_DANGER = float(os.getenv("OP_LIQ_BPS_DANGER", "120"))
OP_LIQ_BPS_FREEZE = float(os.getenv("OP_LIQ_BPS_FREEZE", "200"))

# ── Position-level vs Cluster-level liquidation distance split ────────────
# pos_liq_distance_pct  = derived from proposed leverage (100/lev), used by safety gates
# cluster_liq_distance_pct = from unified_features (liquidation heatmap), used by liquidity risk
POS_LIQ_SPLIT_ENABLED = os.getenv("POS_LIQ_SPLIT_ENABLED", "true").lower() in ("1", "true", "yes")
POS_LIQ_MAX_PCT_CAP = float(os.getenv("POS_LIQ_MAX_PCT_CAP", "20.0"))          # Cap leverage-derived at 20%
POS_LIQ_HAIRCUT_MAJOR = float(os.getenv("POS_LIQ_HAIRCUT_MAJOR", "1.0"))       # No haircut for BTC/ETH
POS_LIQ_HAIRCUT_ALT_MEME = float(os.getenv("POS_LIQ_HAIRCUT_ALT_MEME", "0.85"))  # 15% haircut for alts/memes

# Stress triggers (velocity + score)
OP_STRESS_VEL_60S_BPS = float(os.getenv("OP_STRESS_VEL_60S_BPS", "250"))
OP_STRESS_VEL_15S_BPS = float(os.getenv("OP_STRESS_VEL_15S_BPS", "120"))
OP_STRESS_FAST_MOVE_SCORE = float(os.getenv("OP_STRESS_FAST_MOVE_SCORE", "0.80"))

# Shock/reversal state machine (tactical, symbol-level)
OP_SHOCK_STATE_ENABLED = os.getenv("OP_SHOCK_STATE_ENABLED", "true").lower() in ("1", "true", "yes")
OP_REVERSAL_MIN_DELTA_BPS = float(os.getenv("OP_REVERSAL_MIN_DELTA_BPS", "20"))
OP_REVERSAL_CANDIDATE_TICKS = int(os.getenv("OP_REVERSAL_CANDIDATE_TICKS", "2"))
OP_STRESS_RECOVERY_TICKS = int(os.getenv("OP_STRESS_RECOVERY_TICKS", "3"))

# Portfolio stress escalation (cross-symbol correlation pressure)
OP_PORTFOLIO_STRESS_MIN_SYMBOLS = int(os.getenv("OP_PORTFOLIO_STRESS_MIN_SYMBOLS", "3"))
OP_PORTFOLIO_STRESS_MIN_FRACTION = float(os.getenv("OP_PORTFOLIO_STRESS_MIN_FRACTION", "0.40"))
OP_PORTFOLIO_STRESS_DECAY_MS = int(os.getenv("OP_PORTFOLIO_STRESS_DECAY_MS", "120000"))

# Hedge coverage bands (coverage = hedge_notional / main_notional)
OP_HEDGE_COVERAGE_NORMAL_MIN = float(os.getenv("OP_HEDGE_COVERAGE_NORMAL_MIN", "0.25"))
OP_HEDGE_COVERAGE_NORMAL_MAX = float(os.getenv("OP_HEDGE_COVERAGE_NORMAL_MAX", "0.45"))
OP_HEDGE_COVERAGE_STRESS_MIN = float(os.getenv("OP_HEDGE_COVERAGE_STRESS_MIN", "0.50"))
OP_HEDGE_COVERAGE_STRESS_MAX = float(os.getenv("OP_HEDGE_COVERAGE_STRESS_MAX", "0.70"))

# Hedge TP trim requirements
OP_HEDGE_TRIM_MIN_LIQ_BPS = float(os.getenv("OP_HEDGE_TRIM_MIN_LIQ_BPS", "200"))
OP_HEDGE_TRIM_MAX_FRAC = float(os.getenv("OP_HEDGE_TRIM_MAX_FRAC", "0.05"))

# Hedge microstructure safety (anti-spoof / anti-chase)
HEDGE_MICRO_FAIL_CLOSED = os.getenv("HEDGE_MICRO_FAIL_CLOSED", "true").lower() in ("1", "true", "yes")
HEDGE_MSNAP_MAX_AGE_MS = int(os.getenv("HEDGE_MSNAP_MAX_AGE_MS", "1500"))
HEDGE_OB_STABILITY_TICKS = int(os.getenv("HEDGE_OB_STABILITY_TICKS", "4"))
HEDGE_OB_MIN_IMB_ABS = float(os.getenv("HEDGE_OB_MIN_IMB_ABS", "0.18"))
HEDGE_OB_MAX_SPOOF = float(os.getenv("HEDGE_OB_MAX_SPOOF", "0.35"))
HEDGE_SPREAD_MAX_BPS = float(os.getenv("HEDGE_SPREAD_MAX_BPS", "12"))

# Hedge churn/deconfliction windows
OP_HEDGE_ADD_COOLDOWN_SEC = int(os.getenv("OP_HEDGE_ADD_COOLDOWN_SEC", "30"))
OP_HEDGE_CONTRADICT_WINDOW_SEC = int(os.getenv("OP_HEDGE_CONTRADICT_WINDOW_SEC", "60"))

# Hedge entry timing gate (avoid opening hedges on impulse tops/bottoms)
OP_HEDGE_TIMING_GATE_ENABLED = os.getenv("OP_HEDGE_TIMING_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
OP_HEDGE_ADD_WAIT_VEL_15S_BPS = float(os.getenv("OP_HEDGE_ADD_WAIT_VEL_15S_BPS", "90"))
OP_HEDGE_ADD_WAIT_VEL_60S_BPS = float(os.getenv("OP_HEDGE_ADD_WAIT_VEL_60S_BPS", "180"))
OP_HEDGE_ADD_WAIT_FAST_MOVE_SCORE = float(os.getenv("OP_HEDGE_ADD_WAIT_FAST_MOVE_SCORE", "0.75"))
OP_HEDGE_ADD_ALLOW_IF_LIQ_BELOW_BPS = float(os.getenv("OP_HEDGE_ADD_ALLOW_IF_LIQ_BELOW_BPS", "200"))  # raised from 140: 2% buffer is dangerous
OP_HEDGE_ROE_URGENCY_PCT = float(os.getenv("OP_HEDGE_ROE_URGENCY_PCT", "-8.0"))  # Fix O: bypass timing gate when ROE below this
OP_HEDGE_IMPULSE_DIRECTION_AWARE = os.getenv("OP_HEDGE_IMPULSE_DIRECTION_AWARE", "true").lower() in ("true", "1", "yes")

# URC safe mode: disable one-legged force-open fallback by default
URC_UNHEDGED_PROTECT_ENABLED = os.getenv("URC_UNHEDGED_PROTECT_ENABLED", "true").lower() in ("1", "true", "yes")  # Re-enabled: has built-in microstructure + MI gate

# Contextual confidence thresholds based on HTF alignment
# Aligned stack: 4h bias + 1h confirm + 15m trigger all agree
TF_ENTRY_MIN_CONF_ALIGNED = float(os.getenv("TF_ENTRY_MIN_CONF_ALIGNED", "0.35"))  # Honest scale: top1=0.44→conf=0.35 when TFs agree
# Unaligned stack: Missing confirmation from higher timeframes
TF_ENTRY_MIN_CONF_UNALIGNED = float(os.getenv("TF_ENTRY_MIN_CONF_UNALIGNED", "0.50"))  # Honest: top1=0.57→conf=0.50 when TFs disagree
# Flip actions require high confidence + HTF alignment.
# NOTE (Jan 2026): 0.97 proved too strict in practice and led to "no flip" behavior
# during fast reversals; lowering the default improves participation while other guards
# (portfolio caps, microstructure gating, hourly budgets) still protect churn.
TF_FLIP_MIN_CONF = float(os.getenv("TF_FLIP_MIN_CONF", "0.92"))
CONTEXTUAL_CONF_DYNAMIC_ENABLED = os.getenv("CONTEXTUAL_CONF_DYNAMIC_ENABLED", "true").lower() in ("1", "true", "yes")
CONTEXTUAL_CONF_MAX_RELIEF = float(os.getenv("CONTEXTUAL_CONF_MAX_RELIEF", "0.08"))
CONTEXTUAL_CONF_MAX_PENALTY = float(os.getenv("CONTEXTUAL_CONF_MAX_PENALTY", "0.12"))
# Require 4h bias confirmation for all OPEN_RISK entries.
# FIX Apr 16: ENABLED. Without this, system opens both sides freely, losing $350+/day fighting trends.
# 10h audit showed: SOL shorted into +4.5% rally (-$254), DOGE closed longs then shorted (-$98)
TF_REQUIRE_BIAS_FOR_OPEN_RISK = os.getenv("TF_REQUIRE_BIAS_FOR_OPEN_RISK", "true").lower() in ("1", "true", "yes")

# ============================================================================
# SMART ENTRY GATE - Exploit MM moves, don't chase them (V2 Smart Timing)
# ============================================================================
# Detects fast moves (pump/dump spikes) and waits for pullback before entry.
# Turns "stop hunt traps" into "entry opportunities".
#
# Strategy:
#   1. Detect velocity spike (fast_move > threshold)
#   2. Create hunting zone with Fib retracement levels (38.2%, 50%, 61.8%)
#   3. Block chase entries during spike (WAIT_FOR_PULLBACK)
#   4. Enter on retracement with HTF confirmation (ENTER_ON_RETRACEMENT)
#   5. Counter-trade if HTF suggests reversal (COUNTER_ENTRY)
#
# Kill Switch: SMART_ENTRY_GATE_ENABLED=false disables all timing logic

SMART_ENTRY_GATE_ENABLED = os.getenv("SMART_ENTRY_GATE_ENABLED", "true").lower() in ("1", "true", "yes")

# Velocity threshold to detect fast move (% price change)
# Lower = more sensitive, higher = only catch big moves
SMART_ENTRY_VELOCITY_THRESHOLD = float(os.getenv("SMART_ENTRY_VELOCITY_THRESHOLD", "0.30"))  # 0.3% triggers detection

# Retracement zone (Fibonacci levels)
# Entry allowed when price retraces between MIN and MAX of the move
SMART_ENTRY_RETRACEMENT_MIN = float(os.getenv("SMART_ENTRY_RETRACEMENT_MIN", "0.30"))  # 30% retracement minimum
SMART_ENTRY_RETRACEMENT_MAX = float(os.getenv("SMART_ENTRY_RETRACEMENT_MAX", "0.618"))  # 61.8% maximum (golden zone)

# Cooldown after detecting fast move (seconds)
# During cooldown, OPEN entries are blocked (except COUNTER_ENTRY with HTF support)
SMART_ENTRY_COOLDOWN_SECONDS = int(os.getenv("SMART_ENTRY_COOLDOWN_SECONDS", "120"))  # 2 min default

# Hunting zone TTL - how long to track a move for retracement entry
SMART_ENTRY_HUNTING_ZONE_TTL = int(os.getenv("SMART_ENTRY_HUNTING_ZONE_TTL", "900"))  # 15 min window

# Size modifier for retracement entries (boost high-probability setups)
SMART_ENTRY_RETRACEMENT_SIZE_BOOST = float(os.getenv("SMART_ENTRY_RETRACEMENT_SIZE_BOOST", "1.2"))  # +20% size

# Size modifier for counter entries (reduce risk when trading against prior move)
SMART_ENTRY_COUNTER_SIZE_REDUCE = float(os.getenv("SMART_ENTRY_COUNTER_SIZE_REDUCE", "0.8"))  # -20% size

# Reversal fast-path (Jan 2026):
# When microstructure + short-term price action indicates a reversal, do NOT wait for a perfect
# retracement (which is often too late). This reduces "late at reversal" misses without changing leverage.
SMART_ENTRY_REVERSAL_FASTPATH_ENABLED = os.getenv("SMART_ENTRY_REVERSAL_FASTPATH_ENABLED", "true").lower() in ("1", "true", "yes")
# 0..1 score; higher = more conservative. Default tuned to avoid noise.
SMART_ENTRY_REVERSAL_MIN_SCORE = float(os.getenv("SMART_ENTRY_REVERSAL_MIN_SCORE", "0.78"))
# When fast-path triggers, apply this size multiplier (still respects downstream caps).
SMART_ENTRY_REVERSAL_SIZE_MULT = float(os.getenv("SMART_ENTRY_REVERSAL_SIZE_MULT", "0.7"))

# ============================================================================
# PHASE 3: ACTION AGGREGATION & DUPLICATE SUPPRESSION
# ============================================================================
# Limits output to ≤1 action per symbol per category per cycle
# Prevents multi-TF spam by selecting best signal per category
#
# Winner selection priority by category:
#   OPEN_RISK: 1h > 15m > 5m (prefer longer-term entries)
#   HEDGE: 15m > 1h > 5m (balance tactical + strategic)
#   PROTECTIVE: 1m > 5m > 15m > 1h (prioritize fast reaction)

AGGREGATION_ENABLED = os.getenv("AGGREGATION_ENABLED", "true").lower() in ("1", "true", "yes")
# Duplicate suppression TTL per category (seconds)
# - OPEN_RISK: 10 minutes (prevent repeated entry spam)
# - HEDGE: 5 minutes (allow tactical hedge adjustments)
# - PROTECTIVE: 0 seconds (never suppress safety stops)
DUPLICATE_SUPPRESS_SECONDS_OPEN_RISK = int(os.getenv("DUPLICATE_SUPPRESS_SECONDS_OPEN_RISK", "600"))
DUPLICATE_SUPPRESS_SECONDS_HEDGE = int(os.getenv("DUPLICATE_SUPPRESS_SECONDS_HEDGE", "300"))
DUPLICATE_SUPPRESS_SECONDS_PROTECTIVE = int(os.getenv("DUPLICATE_SUPPRESS_SECONDS_PROTECTIVE", "0"))

# ============================================================================
# PHASE 4: HOURLY BUDGETS & COOLDOWNS
# ============================================================================
# Rate limiting per symbol/globally to prevent excessive OPEN_RISK/HEDGE churn
# PROTECTIVE actions are NEVER limited (0 = unlimited)
# Budgets enforced via Redis rolling counters with 3600s TTL
# Cooldowns prevent rapid-fire OPEN_RISK on same symbol

BUDGETS_ENABLED = os.getenv("BUDGETS_ENABLED", "true").lower() in ("1", "true", "yes")

# Cooldown after OPEN_RISK published (per symbol)
# NOTE (Jan 2026): 15m default was too conservative for volatile markets and
# suppressed follow-up entries that could have captured large swings.
OPEN_RISK_PER_SYMBOL_COOLDOWN_SECONDS = int(os.getenv("OPEN_RISK_PER_SYMBOL_COOLDOWN_SECONDS", "300"))  # 5 min

# Hourly budgets for OPEN_RISK
# NOTE (Jan 2026): These were tuned aggressively low for churn reduction, but can
# cause "no trading" during sustained volatility. Defaults are relaxed; override via env.
OPEN_RISK_GLOBAL_MAX_PER_HOUR = int(os.getenv("OPEN_RISK_GLOBAL_MAX_PER_HOUR", "12"))
OPEN_RISK_PER_SYMBOL_MAX_PER_HOUR = int(os.getenv("OPEN_RISK_PER_SYMBOL_MAX_PER_HOUR", "3"))

# Hourly budgets for HEDGE
HEDGE_PER_SYMBOL_MAX_PER_HOUR = int(os.getenv("HEDGE_PER_SYMBOL_MAX_PER_HOUR", "4"))
HEDGE_GLOBAL_MAX_PER_HOUR = int(os.getenv("HEDGE_GLOBAL_MAX_PER_HOUR", "25"))

# PROTECTIVE rate limit - AUDIT 12/30 recommends 30/hour to prevent protective spam
# that can still fee-bleed via frequent closes/reopens (0 = unlimited)
PROTECTIVE_MAX_PER_HOUR = int(os.getenv("PROTECTIVE_MAX_PER_HOUR", "30"))  # Changed from 0 to 30 per audit

# Tiered Profit-Taking Configuration (DYNAMIC BASED ON CONFIDENCE)
ENABLE_TIERED_PROFIT_TAKING = True  # Enable smart partial closes based on confidence
# NOTE: Auto-hedge on close DISABLED - not documented in 122725-Enhancement.md
# Rely on HEDGE_BUILD mechanism from Phase 5 instead
ENABLE_AUTO_HEDGE_ON_CLOSE = False  # Disabled: Use HEDGE_BUILD state triggered by profit exit feedback

# Dynamic profit taking: percentage scales linearly with confidence (75%-90%)
# Formula: close_pct = (confidence - 0.75) / (0.90 - 0.75) * 100%
# Examples:
#   75% confidence → close 0% (don't take profit yet)
#   80% confidence → close 33% 
#   85% confidence → close 67%
#   90% confidence → close 100% (full exit)
PROFIT_TAKING_MIN_CONFIDENCE = 0.85  # Start considering profit taking at 75%
PROFIT_TAKING_MAX_CONFIDENCE = 0.99  # Full close at 90%+

MAX_LEVERAGE = 100  # Updated: BTC/ETH can use up to 100x leverage
BASE_NOTIONAL = 500.0
MAX_POSITION_VALUE = 2000.0
MAX_POSITION_PER_SYMBOL_PER_SIDE = 500.0  # Doubled to $500 per symbol per side (LONG or SHORT) - hedges allowed
HEDGE_V2_ENABLED = True  # Enable dual-side hedge execution semantics (open opposite without forced close when hedge intent is set)
MAX_HEDGE_GROSS_EXPOSURE_PCT = 25.0  # Cap combined LONG+SHORT gross notional per symbol as % of equity when hedging

# Risk-Based Position Sizing (PROPER RISK MANAGEMENT)
RISK_BASE_PCT = 1.0  # Base risk per trade: 1% of equity
CONFIDENCE_MIN_THRESHOLD = 0.85  # Minimum confidence for position sizing (we only trade 85%+)
CONFIDENCE_POWER = 1.5  # Exponential scaling: higher = more aggressive at high confidence
DRAWDOWN_SCALING_FACTOR = 1.5  # How much to reduce size in drawdown (1.5 = 30% smaller at -20% DD)
ATR_STOP_MULTIPLIER = 2.0  # Stop distance in ATR units (2 ATR = typical stop)

# Portfolio Risk Limits
MAX_PORTFOLIO_EXPOSURE_PCT = 60.0  # Max 60% of equity across all positions
MAX_DAILY_LOSS_PCT = 3.0  # Stop trading if daily loss exceeds 3%
CONSECUTIVE_LOSS_LIMIT = 3  # De-risk after 3 consecutive losses

# Circuit Breaker Configuration
# When daily loss exceeds this threshold, caution_mode activates (blocks new OPEN actions)
# Default 10% (0.10) - set higher to be less sensitive (e.g. 0.15 = 15%)
CIRCUIT_BREAKER_CAUTION_THRESHOLD = float(os.getenv("CIRCUIT_BREAKER_CAUTION_THRESHOLD", "0.15"))
# Circuit breaker protects against runaway losses
CIRCUIT_BREAKER_ENABLED = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() in ("true", "1", "yes")

# ============================================================================
# UNIFIED MARGIN CAPS - Trainer + Trader consistency layer
# ============================================================================
# These caps are used by BOTH trainer (for pre-validation) and traders (for execution)
# IMPORTANT: CLOSE/DECREASE/STOP_LOSS/TAKE_PROFIT are NEVER blocked by margin caps

# ============================================================================
# ACTION CATEGORY SYSTEM
# ============================================================================
# Actions are classified into three categories:
#   OPEN_RISK: New exposure (OPEN_*, INCREASE_*, FLIP_*, composite flips) - subject to caps
#   HEDGE: Risk-reducing opposite-side (OPEN_HEDGE_*) - separate slice
#   PROTECTIVE: Pure exits/reduces (CLOSE_*, DECREASE_*, STOP_LOSS) - never blocked
#   RECOVERY: Hedged-only recovery adds (risk-creating but constrained; URC emits INCREASE_* with recovery_intent)
#
# CRITICAL: Composite flip actions (CLOSE_*_OPEN_*, CLOSE_AND_*, FLIP_*) are OPEN_RISK because
#           they create new exposure, even though they contain "CLOSE".

ACTION_CATEGORIES = {
    'RECOVERY': [
        # Optional explicit recovery action names (URC currently reuses INCREASE_* with action_category="RECOVERY")
        'RECOVER_ADD_LONG', 'RECOVER_ADD_SHORT',
        'RECOVERY_ADD_LONG', 'RECOVERY_ADD_SHORT',
    ],
    'OPEN_RISK': [
        'OPEN_LONG', 'OPEN_SHORT', 
        'INCREASE_LONG', 'INCREASE_SHORT', 
        # ADD_* aliases (returned by should_open_position) - mapped to INCREASE_*
        'ADD_LONG', 'ADD_SHORT', 'ADD_TO_LONG', 'ADD_TO_SHORT',
        'FLIP_LONG', 'FLIP_SHORT',
        # Composite flips - ALL ALIASES ARE OPEN_RISK (create new exposure)
        # Standard format (from action_constants.py)
        'CLOSE_SHORT_OPEN_LONG', 'CLOSE_LONG_OPEN_SHORT',
        # With _AND_ separator
        'CLOSE_SHORT_AND_OPEN_LONG', 'CLOSE_LONG_AND_OPEN_SHORT',
        # CLOSE_AND_* shorthand
        'CLOSE_AND_LONG', 'CLOSE_AND_SHORT',
        # CLOSE_AND_FLIP_* format
        'CLOSE_AND_FLIP_LONG', 'CLOSE_AND_FLIP_SHORT',
    ],
    'HEDGE': [
        'OPEN_HEDGE_LONG', 'OPEN_HEDGE_SHORT',
        'ADD_HEDGE_LONG', 'ADD_HEDGE_SHORT',
        'SCALE_HEDGE', 'UNWIND_HEDGE', 'REBALANCE_HEDGE',
        'HEDGE_LONG', 'HEDGE_SHORT', 'HEDGE',  # Short-form hedge actions
    ],
    'STEALTH_TP': [
        # Stealth take-profit proposals — risk-reducing but NOT blanket bypass.
        # Subject to fee budget and confidence checks, unlike PROTECTIVE.
        'STEALTH_TP_LONG', 'STEALTH_TP_SHORT', 'STEALTH_TP',
        'STEALTH_PARTIAL_CLOSE_LONG', 'STEALTH_PARTIAL_CLOSE_SHORT',
    ],
    'PROTECTIVE': [
        'HOLD', 'NO_ACTION', 'NONE', 'UNKNOWN',  # Passive actions - never block
        'CLOSE_LONG', 'CLOSE_SHORT', 'CLOSE_ALL', 'CLOSE',
        'DECREASE_LONG', 'DECREASE_SHORT',
        'STOP_LOSS', 'TAKE_PROFIT', 'TAKE_PROFIT_PARTIAL',
        'PARTIAL_CLOSE_LONG', 'PARTIAL_CLOSE_SHORT', 'PARTIAL_CLOSE',
    ]
}

def normalize_action_name(action_name) -> str:
    """
    Normalize an action representation to a canonical UPPER_SNAKE string.
    
    Why:
    - The trainer historically emitted mixed formats ("Open Long", "Close Long → Open Short", "LONG", ints 0-6).
    - Traders, gates, and budgets expect stable canonical names (e.g., OPEN_LONG, CLOSE_LONG_AND_OPEN_SHORT).
    - Action categories (OPEN_RISK|HEDGE|PROTECTIVE) must be derived from the canonical name.
    
    Supports:
    - ints 0-6 (legacy extended mapping)
    - common human-readable variants
    - arrow formats (→, ->) for flip actions
    """
    try:
        if action_name is None:
            return ""

        # Bytes → string
        if isinstance(action_name, (bytes, bytearray)):
            try:
                action_name = action_name.decode("utf-8", errors="ignore")
            except Exception:
                action_name = str(action_name)

        # Numeric action ids (trainer/trader legacy)
        if isinstance(action_name, (int, float)) and not isinstance(action_name, bool):
            try:
                ai = int(action_name)
                if float(action_name) == float(ai):
                    id_map = {
                        0: "HOLD",
                        1: "OPEN_LONG",
                        2: "OPEN_SHORT",
                        3: "CLOSE_LONG",
                        4: "CLOSE_SHORT",
                        5: "CLOSE_SHORT_OPEN_LONG",
                        6: "CLOSE_LONG_OPEN_SHORT",
                    }
                    if ai in id_map:
                        return id_map[ai]
            except Exception:
                pass
            return str(action_name).upper()

        s = str(action_name).strip()
        if not s:
            return ""

        import re

        # Unify arrows/dashes
        s = s.replace("→", "->").replace("⇒", "->")
        s = s.replace("—", "-").replace("–", "-")

        u = s.upper().strip()
        u = re.sub(r"\s+", " ", u)

        # Common exact aliases (after arrow normalization + whitespace collapse)
        direct = {
            # Simple direction aliases
            "BUY": "OPEN_LONG",
            "SELL": "OPEN_SHORT",
            "LONG": "OPEN_LONG",
            "SHORT": "OPEN_SHORT",
            "BUY/LONG": "OPEN_LONG",
            "SELL/SHORT": "OPEN_SHORT",

            # Spaced canonical names
            "OPEN LONG": "OPEN_LONG",
            "OPEN SHORT": "OPEN_SHORT",
            "CLOSE LONG": "CLOSE_LONG",
            "CLOSE SHORT": "CLOSE_SHORT",

            # Flip display formats (trainer)
            "CLOSE SHORT -> OPEN LONG": "CLOSE_SHORT_AND_OPEN_LONG",
            "CLOSE LONG -> OPEN SHORT": "CLOSE_LONG_AND_OPEN_SHORT",

            # Risk mgmt synonyms
            "STOP LOSS": "STOP_LOSS",
            "TAKE PROFIT": "TAKE_PROFIT",
            "TAKE PROFIT PARTIAL": "TAKE_PROFIT_PARTIAL",
            "PARTIAL CLOSE": "PARTIAL_CLOSE",
            "PARTIAL CLOSE LONG": "PARTIAL_CLOSE_LONG",
            "PARTIAL CLOSE SHORT": "PARTIAL_CLOSE_SHORT",

            # Hedge synonyms
            "OPEN HEDGE LONG": "OPEN_HEDGE_LONG",
            "OPEN HEDGE SHORT": "OPEN_HEDGE_SHORT",
            "HEDGE LONG": "HEDGE_LONG",
            "HEDGE SHORT": "HEDGE_SHORT",
            "HEDGE": "HEDGE",

            # No-op synonyms
            "NO ACTION": "NO_ACTION",
            "NO_ACTION": "NO_ACTION",
        }
        if u in direct:
            return direct[u]

        # Pattern: "CLOSE <SIDE> -> OPEN <SIDE>" (or any string containing those tokens)
        if "CLOSE" in u and "OPEN" in u and ("LONG" in u or "SHORT" in u):
            close_side = None
            open_side = None
            if "CLOSE SHORT" in u:
                close_side = "SHORT"
            elif "CLOSE LONG" in u:
                close_side = "LONG"
            if "OPEN LONG" in u:
                open_side = "LONG"
            elif "OPEN SHORT" in u:
                open_side = "SHORT"
            if close_side and open_side:
                return f"CLOSE_{close_side}_AND_OPEN_{open_side}"

        # Pattern: "CLOSE AND LONG/SHORT" (with spaces)
        if u.startswith("CLOSE AND "):
            side = u.replace("CLOSE AND ", "").strip()
            if side in ("LONG", "SHORT"):
                return f"CLOSE_AND_{side}"

        # Fallback: convert remaining spaces to underscores, collapse repeats
        u2 = re.sub(r"[^A-Z0-9_]+", "_", u)  # keep only safe chars
        u2 = re.sub(r"_+", "_", u2).strip("_")
        return u2
    except Exception:
        try:
            return str(action_name).upper()
        except Exception:
            return ""

def get_action_category(action_name: str) -> str:
    """Get the category for an action name (OPEN_RISK|HEDGE|PROTECTIVE|RECOVERY)
    
    CRITICAL: Composite flips (CLOSE_AND_*, *_AND_OPEN_*) are OPEN_RISK,
              not PROTECTIVE, because they create new exposure.
    
    SAFETY: Default is PROTECTIVE (no-op), not OPEN_RISK.
            Unknown actions degrade to HOLD behavior, not exposure creation.
    """
    # Normalize action first (handles trainer display names, ints, and aliases)
    action_upper = normalize_action_name(action_name)
    
    # Empty/invalid → PROTECTIVE (safest default)
    if not action_upper or action_upper in ('', 'NONE', 'UNKNOWN', 'NULL'):
        return "PROTECTIVE"
    
    # 1) Explicit mapping first
    for category, actions in ACTION_CATEGORIES.items():
        if action_upper in actions:
            return category
    
    # 2) Composite flip / close+open patterns MUST be OPEN_RISK
    #    Check BEFORE generic "CLOSE" detection
    if ("AND_OPEN" in action_upper) or ("_AND_LONG" in action_upper) or ("_AND_SHORT" in action_upper):
        return "OPEN_RISK"
    if ("CLOSE" in action_upper and "OPEN" in action_upper):
        return "OPEN_RISK"
    if "FLIP" in action_upper:
        return "OPEN_RISK"
    
    # 3) Hedge next
    if "HEDGE" in action_upper:
        return "HEDGE"
    
    # 4) Protective (pure exits only - no OPEN/FLIP patterns)
    if any(x in action_upper for x in ["CLOSE", "DECREASE", "STOP", "TAKE_PROFIT", "PARTIAL"]):
        return "PROTECTIVE"
    
    # 5) Open risk (new exposure)
    if any(x in action_upper for x in ["OPEN", "INCREASE", "ADD"]):
        return "OPEN_RISK"
    
    # 6) SAFETY DEFAULT: Unknown actions → PROTECTIVE (no-op, not exposure)
    # This prevents unknown/malformed actions from accidentally opening positions
    return "PROTECTIVE"


def get_tf_exit_profile(timeframe: str, action_category: str = "OPEN_RISK") -> dict:
    """Get TF-scaled exit profile for a given timeframe and action category.
    
    Returns a dict with scaling multipliers that the DynamicTPEngine and trader
    use to adjust TP/trail/hold parameters based on signal origin timeframe.
    
    For HEDGE-category signals, the hedge_tp_mult is used instead of tp_mult
    to ensure hedge legs always take profit faster than main legs.
    
    Args:
        timeframe: Signal origin timeframe (5m, 15m, 1h, 4h)
        action_category: OPEN_RISK, HEDGE, PROTECTIVE, RECOVERY
        
    Returns:
        dict with tp_mult, trail_mult, trail_activation_mult, min_hold_sec, description
    """
    profile = dict(TF_EXIT_PROFILES.get(timeframe, TF_EXIT_PROFILE_DEFAULT))
    
    # Hedge legs use tighter TP (hedge_tp_mult instead of tp_mult)
    if action_category == "HEDGE":
        profile["tp_mult"] = profile.get("hedge_tp_mult", 0.5)
        profile["min_hold_sec"] = min(profile["min_hold_sec"], 90)  # Hedge legs exit faster
        profile["description"] = f"HEDGE({timeframe}): tight TP, fast exit"
    
    # Stealth TP actions: same as PROTECTIVE but labeled differently
    if action_category == "STEALTH_TP":
        profile["min_hold_sec"] = 0
        profile["tp_mult"] = 1.0
        profile["description"] = f"STEALTH_TP({timeframe}): fee-checked exit"
    
    # Protective actions have no hold constraint
    if action_category == "PROTECTIVE":
        profile["min_hold_sec"] = 0
        profile["tp_mult"] = 1.0
        profile["description"] = f"PROTECTIVE({timeframe}): immediate execution"
    
    return profile


# ============================================================================
# SIDE-BASED MARGIN CAPS (per-side + total + reserve)
# ============================================================================
# NOTE: PER_SIDE_CAP, TOTAL_CAP, MAX_MARGIN_UTIL_*_PCT are now DERIVED from 
# PORTFOLIO_*_BUDGET_PCT settings (single source of truth). See line ~1881.
# Do not set them here - they are defined after PORTFOLIO_* settings.

# Additional reserve headroom above TOTAL_CAP, usable only for ultra-high confidence fast-move entries.
RESERVE_RATIO = float(os.getenv("RESERVE_RATIO", "0.35"))  # +35% reserve headroom

# Reserve margin: Additional +25% allowed ONLY if confidence >= 0.97 AND fast-move conditions are met
RESERVE_MARGIN_PCT = float(os.getenv("RESERVE_MARGIN_PCT", "25.0"))  # +25% reserve
RESERVE_CONFIDENCE_THRESHOLD = float(os.getenv("RESERVE_CONFIDENCE_THRESHOLD", "0.97"))

# Hedge-specific slice (draws from separate allocation)
MAX_MARGIN_UTIL_HEDGE_SLICE_PCT = float(os.getenv("MAX_MARGIN_UTIL_HEDGE_SLICE_PCT", "20.0"))

# Normal risk-increasing actions (OPEN_LONG, OPEN_SHORT, INCREASE_*, FLIP_*)
MAX_MARGIN_UTIL_OPEN_PCT = float(os.getenv("MAX_MARGIN_UTIL_OPEN_PCT", "50.0"))

# Hedge-specific cap (OPEN_HEDGE_* consumes margin but reduces directional risk)
MAX_MARGIN_UTIL_HEDGE_PCT = float(os.getenv("MAX_MARGIN_UTIL_HEDGE_PCT", "70.0"))
# Allow hedges to bypass total margin cap (still subject to hedge budget governor downsizing).
# This is required for strict no-loss systems where hedging is the primary recovery mechanism.
HEDGE_BYPASS_TOTAL_MARGIN_CAP = os.getenv("HEDGE_BYPASS_TOTAL_MARGIN_CAP", "true").lower() in ("1", "true", "yes")

# Absolute cap: NEVER exceed for any new order including hedges
# Absolute safety cap for margin utilization.
# If set too low, the trainer will never open new positions once the account is moderately utilized.
# Operator requirement (Jan 2026): keep policy consistent across accounts; tune via env if needed.
MAX_MARGIN_UTIL_ABSOLUTE_PCT = float(os.getenv("MAX_MARGIN_UTIL_ABSOLUTE_PCT", "90.0"))

# Hedge absolute cap (Jan 2026): allow hedges to operate under deeper margin pressure than risk-increasing opens.
# This does NOT change the OPEN_RISK absolute cap; it only relaxes the absolute ceiling for hedge_intent orders.
# Use with caution: hedges consume margin even as they reduce directional risk.
MAX_MARGIN_UTIL_ABSOLUTE_HEDGE_PCT = float(os.getenv("MAX_MARGIN_UTIL_ABSOLUTE_HEDGE_PCT", "99.5"))

# -----------------------------------------------------------------------------
# HEDGE CAP OVERRIDES (No-loss systems)
# -----------------------------------------------------------------------------
# Operator intent: hedges are the primary recovery tool; do not pre-block hedge adds due to
# trader-side margin-util caps. We still require actual free margin (or we can free margin
# via micro-trims) and Binance may reject orders if truly insufficient.
HEDGE_BYPASS_TRADER_MARGIN_CAP = os.getenv("HEDGE_BYPASS_TRADER_MARGIN_CAP", "true").lower() in ("1", "true", "yes")

# When a hedge add is blocked due to free-margin / cap-hit, attempt a profit-only micro-trim
# to free margin and then retry the hedge once.
HEDGE_CAP_HIT_AUTO_TRIM_ENABLED = os.getenv("HEDGE_CAP_HIT_AUTO_TRIM_ENABLED", "true").lower() in ("1", "true", "yes")
HEDGE_CAP_HIT_TRIM_COOLDOWN_SECONDS = int(float(os.getenv("HEDGE_CAP_HIT_TRIM_COOLDOWN_SECONDS", "45") or 45))
HEDGE_CAP_HIT_TRIM_MIN_PNL_PCT = float(os.getenv("HEDGE_CAP_HIT_TRIM_MIN_PNL_PCT", "0.20"))
HEDGE_CAP_HIT_TRIM_MAX_FRACTION = float(os.getenv("HEDGE_CAP_HIT_TRIM_MAX_FRACTION", "0.10"))
HEDGE_CAP_HIT_TRIM_MIN_FRACTION = float(os.getenv("HEDGE_CAP_HIT_TRIM_MIN_FRACTION", "0.02"))

# Publish-time headroom-aware downsizing for hedge adds (prevents publish→drop loop).
HEDGE_PUBLISH_HEADROOM_AWARE = os.getenv("HEDGE_PUBLISH_HEADROOM_AWARE", "true").lower() in ("1", "true", "yes")
HEDGE_PUBLISH_HEADROOM_BUFFER_PCT = float(os.getenv("HEDGE_PUBLISH_HEADROOM_BUFFER_PCT", "95.0"))  # use <=95% of avail
HEDGE_MIN_MARGIN_USD_ON_ZERO_HEADROOM = float(os.getenv("HEDGE_MIN_MARGIN_USD_ON_ZERO_HEADROOM", "2.0"))

# Hedge behavior when at/near margin caps
# Options: "allow" (full size), "size_reduce" (reduce by factor), "block"
HEDGE_ON_MARGIN_CAP_ACTION = os.getenv("HEDGE_ON_MARGIN_CAP_ACTION", "size_reduce")

# When size_reduce is chosen, multiply hedge order size by this factor
HEDGE_SIZE_REDUCTION_FACTOR = float(os.getenv("HEDGE_SIZE_REDUCTION_FACTOR", "0.5"))

# =========================================================================
# ULTRA-HIGH CONFIDENCE MARGIN RELEASE (Profit Recycle)
# =========================================================================
# Purpose:
# - If a new ultra-high confidence entry signal arrives (e.g. >= 0.95) but the trader is blocked
#   by free-margin or cap conditions, optionally free margin by partially closing an existing
#   profitable position (profit-only) to release initial margin.
#
# Safety:
# - Default OFF
# - Profit-only (never closes losing legs)
# - Cooldown to avoid churn
ENABLE_ULTRA_HIGH_MARGIN_RELEASE = os.getenv("ENABLE_ULTRA_HIGH_MARGIN_RELEASE", "false").lower() in ("true", "1")
ULTRA_HIGH_MARGIN_RELEASE_CONF_THRESHOLD = float(os.getenv("ULTRA_HIGH_MARGIN_RELEASE_CONF_THRESHOLD", "0.95"))
ULTRA_HIGH_MARGIN_RELEASE_BUFFER = float(os.getenv("ULTRA_HIGH_MARGIN_RELEASE_BUFFER", "1.2"))
ULTRA_HIGH_MARGIN_RELEASE_MAX_CLOSE_FRACTION = float(os.getenv("ULTRA_HIGH_MARGIN_RELEASE_MAX_CLOSE_FRACTION", "0.50"))
ULTRA_HIGH_MARGIN_RELEASE_MIN_PROFIT_USD = float(os.getenv("ULTRA_HIGH_MARGIN_RELEASE_MIN_PROFIT_USD", "1.0"))
ULTRA_HIGH_MARGIN_RELEASE_COOLDOWN_SECONDS = int(os.getenv("ULTRA_HIGH_MARGIN_RELEASE_COOLDOWN_SECONDS", "60"))

# ============================================================================
# ADAPTIVE HEDGE V2 SYSTEM - Kill Switches & Feature Flags
# ============================================================================
# Master kill switch - revert to old behavior if any issues
ADAPTIVE_HEDGE_V2_ENABLED = os.getenv("ADAPTIVE_HEDGE_V2_ENABLED", "false").lower() in ("true", "1")

# Component-level kill switches (all default OFF for safety)
LEG_INDEPENDENT_ENABLED = os.getenv("LEG_INDEPENDENT_ENABLED", "false").lower() in ("true", "1")
MARGIN_85_ENABLED = os.getenv("MARGIN_85_ENABLED", "false").lower() in ("true", "1")
BINANCE_LIQ_PRIMARY = os.getenv("BINANCE_LIQ_PRIMARY", "false").lower() in ("true", "1")
DEPTH_EXECUTION_GATE_ENABLED = os.getenv("DEPTH_EXECUTION_GATE_ENABLED", "false").lower() in ("true", "1")

# Canary rollout - only apply V2 to specific symbols first
# Example: ADAPTIVE_V2_CANARY_SYMBOLS=BTCUSDT,ETHUSDT
ADAPTIVE_V2_CANARY_SYMBOLS = [s.strip() for s in os.getenv("ADAPTIVE_V2_CANARY_SYMBOLS", "").split(",") if s.strip()]

# ============================================================================
# ADAPTIVE MARGIN CAPS (V2) - Higher caps with adaptive safety
# ============================================================================
# When MARGIN_85_ENABLED=true, use these elevated caps
# Current: 50%/70%/75% → V2: 60%/80%/85%
MAX_MARGIN_UTIL_OPEN_V2_PCT = float(os.getenv("MAX_MARGIN_UTIL_OPEN_V2_PCT", "60.0"))
MAX_MARGIN_UTIL_HEDGE_V2_PCT = float(os.getenv("MAX_MARGIN_UTIL_HEDGE_V2_PCT", "80.0"))
MAX_MARGIN_UTIL_ABSOLUTE_V2_PCT = float(os.getenv("MAX_MARGIN_UTIL_ABSOLUTE_V2_PCT", "85.0"))

# Adaptive margin reduction based on market conditions
# When conditions are risky, reduce margin cap by up to this percentage
MARGIN_ADAPTIVE_MAX_REDUCTION_PCT = float(os.getenv("MARGIN_ADAPTIVE_MAX_REDUCTION_PCT", "20.0"))

# Risk factor weights for adaptive margin calculation
MARGIN_RISK_WEIGHT_VOLATILITY = float(os.getenv("MARGIN_RISK_WEIGHT_VOLATILITY", "0.35"))
MARGIN_RISK_WEIGHT_LIQUIDATION = float(os.getenv("MARGIN_RISK_WEIGHT_LIQUIDATION", "0.30"))
MARGIN_RISK_WEIGHT_SPREAD = float(os.getenv("MARGIN_RISK_WEIGHT_SPREAD", "0.20"))
MARGIN_RISK_WEIGHT_MOMENTUM = float(os.getenv("MARGIN_RISK_WEIGHT_MOMENTUM", "0.15"))

# Minimum caps (floor) even under max risk reduction
MARGIN_FLOOR_OPEN_PCT = float(os.getenv("MARGIN_FLOOR_OPEN_PCT", "30.0"))
MARGIN_FLOOR_HEDGE_PCT = float(os.getenv("MARGIN_FLOOR_HEDGE_PCT", "50.0"))
MARGIN_FLOOR_ABSOLUTE_PCT = float(os.getenv("MARGIN_FLOOR_ABSOLUTE_PCT", "60.0"))

# ============================================================================
# RAMP PHASES - Portfolio ramp-up limits (overrides risk/phase_controller.py defaults)
# ============================================================================
# These phases control per-symbol margin caps based on account equity.
# Format: list of dicts with name, min_equity, max_mu, per_pos_margin_pct, max_positions
#
# per_pos_margin_pct: Maximum margin per symbol as fraction of equity (e.g., 0.02 = 2%)
# max_mu: Maximum total margin utilization (e.g., 0.30 = 30%)
# max_positions: Maximum concurrent open positions
#
# With equity ~$2500, per_pos_margin_pct=0.04 gives ~$100 max per symbol at 100x = $10k notional
PHASES = [
    {
        "name": "P0",
        "min_equity": 0.0,
        "max_mu": float(os.getenv("RAMP_P0_MAX_MU", "0.30")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P0_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P0_MAX_POSITIONS", "6")),
        "min_free_margin_ratio": 0.0,
    },
    {
        "name": "P1",
        "min_equity": 1000.0,
        "max_mu": float(os.getenv("RAMP_P1_MAX_MU", "0.40")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P1_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P1_MAX_POSITIONS", "8")),
        "min_free_margin_ratio": 0.0,
    },
    {
        "name": "P1_5",
        "min_equity": 2000.0,
        "max_mu": float(os.getenv("RAMP_P1_5_MAX_MU", "0.50")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P1_5_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P1_5_MAX_POSITIONS", "15")),
        "min_free_margin_ratio": 0.0,
    },
    {
        "name": "P2",
        "min_equity": 3000.0,
        "max_mu": float(os.getenv("RAMP_P2_MAX_MU", "0.50")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P2_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P2_MAX_POSITIONS", "15")),
        "min_free_margin_ratio": 0.0,
    },
    {
        "name": "P3",
        "min_equity": 5000.0,
        "max_mu": float(os.getenv("RAMP_P3_MAX_MU", "0.50")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P3_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P3_MAX_POSITIONS", "15")),
        "min_free_margin_ratio": 0.0,
    },
    {
        "name": "P4",
        "min_equity": 10000.0,
        "max_mu": float(os.getenv("RAMP_P4_MAX_MU", "0.50")),
        "per_pos_margin_pct": float(os.getenv("RAMP_P4_PER_POS_MARGIN_PCT", "0.05")),
        "max_positions": int(os.getenv("RAMP_P4_MAX_POSITIONS", "15")),
        "min_free_margin_ratio": 0.0,
    },
]

# ============================================================================
# DEPTH EXECUTION GATE (V2) - Pre-trade filtering based on orderbook depth
# ============================================================================
# Spoof detection threshold (0-1 score) - delay trade if above this
DEPTH_GATE_SPOOF_THRESHOLD = float(os.getenv("DEPTH_GATE_SPOOF_THRESHOLD", "0.7"))

# Fast move threshold - reduce size if market is moving fast
DEPTH_GATE_FAST_MOVE_THRESHOLD = float(os.getenv("DEPTH_GATE_FAST_MOVE_THRESHOLD", "0.8"))

# Minimum depth quality score (0-1) - delay trade if below this
DEPTH_GATE_MIN_QUALITY = float(os.getenv("DEPTH_GATE_MIN_QUALITY", "0.5"))

# Depth imbalance threshold for size reduction (-1 to 1)
# If imbalance is strongly against our trade direction, reduce size
DEPTH_GATE_IMBALANCE_THRESHOLD = float(os.getenv("DEPTH_GATE_IMBALANCE_THRESHOLD", "0.6"))

# Staleness threshold (ms) - consider depth data stale if older than this
DEPTH_GATE_STALENESS_MS = int(os.getenv("DEPTH_GATE_STALENESS_MS", "2000"))

# Size reduction factor when depth gate recommends SIZE_REDUCE
DEPTH_GATE_SIZE_REDUCE_FACTOR = float(os.getenv("DEPTH_GATE_SIZE_REDUCE_FACTOR", "0.5"))

# Delay duration (seconds) when depth gate recommends DELAY
DEPTH_GATE_DELAY_SECONDS = int(os.getenv("DEPTH_GATE_DELAY_SECONDS", "5"))

# ============================================================================
# HEDGE BUILD STATE CONFIGURATION (Phase 5 - 122725-Enhancement.md)
# ============================================================================
# After a trailing-profit exit, enter HEDGE_BUILD state to prevent immediate flips
HEDGE_BUILD_TTL_SECONDS = int(os.getenv("HEDGE_BUILD_TTL_SECONDS", "600"))  # 10 min hedge-only window (Phase 5 spec)
HEDGE_BUILD_ENABLED = os.getenv("HEDGE_BUILD_ENABLED", "true").lower() in ["1", "true", "yes"]
HEDGE_BUILD_MAX_ADD_PCT = float(os.getenv("HEDGE_BUILD_MAX_ADD_PCT", "0.05"))  # 5% max per hedge addition
HEDGE_BUILD_FLIP_MIN_CONF = float(os.getenv("HEDGE_BUILD_FLIP_MIN_CONF", "0.97"))  # Phase 5: Min conf to exit HEDGE_BUILD with flip
HEDGE_BUILD_REQUIRE_ALIGNMENT = os.getenv("HEDGE_BUILD_REQUIRE_ALIGNMENT", "true").lower() in ["1", "true", "yes"]  # Phase 5: Require 4h+1h+15m alignment
HEDGE_BUILD_BLOCK_FLAT_REENTRY = os.getenv("HEDGE_BUILD_BLOCK_FLAT_REENTRY", "true").lower() in ["1", "true", "yes"]

# HEDGE-FIRST STRATEGY: Build hedges instead of flipping positions
# When model predicts opposite direction to current position:
# - DEFAULT: Open a hedge (keep original, add opposite position)
# - ONLY FLIP: When confidence >= FLIP_MIN_CONFIDENCE AND position loss <= FLIP_POSITION_LOSS_THRESHOLD
HEDGE_FIRST_ENABLED = os.getenv("HEDGE_FIRST_ENABLED", "true").lower() in ["1", "true", "yes"]
FLIP_MIN_CONFIDENCE = float(os.getenv("FLIP_MIN_CONFIDENCE", "0.97"))  # 97% confidence to flip
FLIP_POSITION_LOSS_THRESHOLD = float(os.getenv("FLIP_POSITION_LOSS_THRESHOLD", "-5.0"))  # Position must be -5% or worse to allow flip

# ========== NEW: HEDGE INSTEAD OF CLOSE THRESHOLDS ==========
# When a position is losing but not catastrophically, hedge instead of close
HEDGE_INSTEAD_OF_CLOSE_LOSS_THRESHOLD = float(os.getenv("HEDGE_INSTEAD_OF_CLOSE_LOSS_THRESHOLD", "-2.0"))  # -2% ROE: Start considering hedge
HEDGE_MAX_LOSS_FOR_RECOVERY = float(os.getenv("HEDGE_MAX_LOSS_FOR_RECOVERY", "-15.0"))  # -15% ROE: Beyond this, close outright

# ========== HEDGE-FIRST ON LOSING CLOSE (Apr 2026) ==========
# When model signals CLOSE on a losing position, open opposite hedge instead
# of realizing the loss.  Only close directly when in profit or confidence >= 0.80.
# Lowered from 0.95→0.80: at high leverage we MUST hedge instead of realize loss
HEDGE_FIRST_ON_LOSING_CLOSE_ENABLED = os.getenv("HEDGE_FIRST_ON_LOSING_CLOSE_ENABLED", "true").lower() in ("1", "true", "yes")
HEDGE_FIRST_ON_LOSING_CLOSE_MIN_CONF = float(os.getenv("HEDGE_FIRST_ON_LOSING_CLOSE_MIN_CONF", "0.80"))  # Close at loss only if conf >= this (was 0.95)
HEDGE_FIRST_ON_LOSING_CLOSE_MIN_LOSS_USD = float(os.getenv("HEDGE_FIRST_ON_LOSING_CLOSE_MIN_LOSS_USD", "0.50"))  # Only trigger if loss > $0.50 (was $1)

# ========== FAST REVERSAL HEDGE (FRH) — Apr 2026 ==========
# Detect price reversals on shortest TFs (1m/5m) using microstructure + momentum,
# then open a hedge to capture the reversal profit without closing the swing position.
# This lets the system profit on both sides: swing holds, hedge scalps the dip/spike.
# Kill switch: FRH_ENABLED
FRH_ENABLED = os.getenv("FRH_ENABLED", "true").lower() in ("1", "true", "yes")
FRH_MIN_REVERSAL_SCORE = float(os.getenv("FRH_MIN_REVERSAL_SCORE", "0.55"))        # 0-1 composite reversal score threshold
FRH_MIN_CONF = float(os.getenv("FRH_MIN_CONF", "0.65"))                            # Lower than entry (0.80) — hedging is protective
FRH_HEDGE_RATIO = float(os.getenv("FRH_HEDGE_RATIO", "0.20"))                      # Hedge 40% of main position notional
FRH_HEDGE_MAX_USD = float(os.getenv("FRH_HEDGE_MAX_USD", "75.0"))                  # Cap per FRH hedge at $150 margin (was $100 — need room for multi-layer)
FRH_HEDGE_MIN_USD = float(os.getenv("FRH_HEDGE_MIN_USD", "5.0"))                    # Min $5 margin for hedge to be meaningful

# ========== PROGRESSIVE MULTI-LAYER HEDGE SIZING ==========
# Instead of a single flat ratio, hedge size scales with position loss severity.
# Each layer defines: (ROE threshold, hedge ratio, max USD cap).
# When main position ROE drops past a threshold, the hedge ratio steps up.
# This ensures small hedges for small drawdowns, large hedges for deep losses.
# Format: comma-separated "roe:ratio:maxusd" triplets
# Layer 1: -2% ROE → 20% ratio, $50 cap  (light protection, early warning)
# Layer 2: -5% ROE → 40% ratio, $100 cap (moderate protection)
# Layer 3: -10% ROE → 65% ratio, $200 cap (heavy protection, prevent liquidation)
# Layer 4: -15% ROE → 85% ratio, $300 cap (emergency full hedge)
PROGRESSIVE_HEDGE_ENABLED = os.getenv("PROGRESSIVE_HEDGE_ENABLED", "true").lower() in ("true", "1", "yes")
PROGRESSIVE_HEDGE_LAYERS = os.getenv("PROGRESSIVE_HEDGE_LAYERS", "-5:0.15:40,-10:0.25:75,-15:0.35:100")

def parse_progressive_hedge_layers(raw: str = "") -> list:
    """Parse progressive hedge layers from env string to list of (roe_threshold, ratio, max_usd) tuples."""
    layers = []
    raw = raw or PROGRESSIVE_HEDGE_LAYERS
    for chunk in raw.split(","):
        parts = chunk.strip().split(":")
        if len(parts) == 3:
            try:
                layers.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except (ValueError, TypeError):
                continue
    # Sort by ROE threshold ascending (most negative first) so deepest layer matches first
    layers.sort(key=lambda x: x[0], reverse=False)
    return layers

PROGRESSIVE_HEDGE_LAYERS_PARSED = parse_progressive_hedge_layers()
FRH_COOLDOWN_SEC = int(os.getenv("FRH_COOLDOWN_SEC", "600"))                        # 3min cooldown per symbol between FRH hedges
FRH_MIN_POSITION_AGE_SEC = int(os.getenv("FRH_MIN_POSITION_AGE_SEC", "60"))         # Position must be >= 60s old before FRH
FRH_TP_ROE_PCT = float(os.getenv("FRH_TP_ROE_PCT", "8.0"))                          # Auto-TP hedge leg at 8% ROE (let hedge capture real reversal, not scalp)
FRH_MAX_HOLD_SEC = int(os.getenv("FRH_MAX_HOLD_SEC", "2700"))                       # Auto-close FRH hedge after 45min if no TP (was 15min — too short)
FRH_OB_IMBALANCE_WEIGHT = float(os.getenv("FRH_OB_IMBALANCE_WEIGHT", "0.30"))       # OB imbalance contribution to reversal score
FRH_MOMENTUM_FLIP_WEIGHT = float(os.getenv("FRH_MOMENTUM_FLIP_WEIGHT", "0.35"))     # Momentum flip contribution to reversal score
FRH_MICRO_FAST_MOVE_WEIGHT = float(os.getenv("FRH_MICRO_FAST_MOVE_WEIGHT", "0.20")) # CoinAPI fast_move contribution
FRH_PRICE_VELOCITY_WEIGHT = float(os.getenv("FRH_PRICE_VELOCITY_WEIGHT", "0.15"))   # Price velocity contribution

# ========== HEDGE COMMITMENT & PROFIT TARGETS (centralized, Apr 2026) ==========
# Tighter values for high-leverage scalping: faster commitment, lower profit target
HEDGE_COMMITMENT_SECONDS = int(os.getenv("HEDGE_COMMITMENT_SECONDS", "300"))        # Lock hedge for 5min (give hedge time to work)
HEDGE_PROFIT_TARGET_PCT = float(os.getenv("HEDGE_PROFIT_TARGET_PCT", "8.0"))        # Release lock at 8% ROE (was 2% — too early, hedge legs killed for pennies)
HEDGE_MAIN_RECOVERY_ROE_PCT = float(os.getenv("HEDGE_MAIN_RECOVERY_ROE_PCT", "-5.0"))  # Keep protecting if main < -5%

# ========== PARTIAL CLOSE THROTTLE (Apr 2026) ==========
# Max 1 partial close per symbol per cooldown window to prevent partial close spam
PARTIAL_CLOSE_THROTTLE_ENABLED = os.getenv("PARTIAL_CLOSE_THROTTLE_ENABLED", "true").lower() in ("1", "true", "yes")
PARTIAL_CLOSE_THROTTLE_SEC = float(os.getenv("PARTIAL_CLOSE_THROTTLE_SEC", "300"))  # 5min cooldown between partials

# ========== MIN HOLD ENFORCEMENT IN CLOSE HANDLER (Apr 2026) ==========
# Block model closes on positions younger than MIN_HOLD_SECONDS.
# Governor/emergency/stop-loss overrides bypass this.
CLOSE_MIN_HOLD_ENFORCE_ENABLED = os.getenv("CLOSE_MIN_HOLD_ENFORCE_ENABLED", "true").lower() in ("1", "true", "yes")

# ========== NEW: MASA WEIGHT STRENGTHENING (Prevent weak second-opinion entries) ==========
MASA_MIN_FOR_ENTRY = float(os.getenv("MASA_MIN_FOR_ENTRY", "0.60"))  # MASA must be at least 60% for entries
PPO_REQUIRED_WHEN_MASA_WEAK = float(os.getenv("PPO_REQUIRED_WHEN_MASA_WEAK", "0.95"))  # If MASA weak, PPO must be 95%+

# ========== NEW: HTF ALIGNMENT GATE (Prevent entries against higher TF trend) ==========
REQUIRE_HTF_ALIGNMENT_FOR_ENTRIES = os.getenv("REQUIRE_HTF_ALIGNMENT_FOR_ENTRIES", "true").lower() in ["1", "true", "yes"]

# ========== TF-DISAGGREGATED HEDGE INTENT ==========
# When deconflicting multi-TF signals for a symbol with an existing position,
# emit minority-direction signals as hedge intents instead of dropping them.
# This allows the system to proactively hedge based on TF disagreement
# (e.g., 1h SHORT while 4h LONG → hedge the 1h leg).
ENABLE_TF_HEDGE_DISAGG = os.getenv("ENABLE_TF_HEDGE_DISAGG", "true").lower() in ("true", "1", "yes")
TF_HEDGE_DISAGG_MIN_CONF = float(os.getenv("TF_HEDGE_DISAGG_MIN_CONF", "0.65"))
TF_HEDGE_DISAGG_TFS = [tf.strip() for tf in os.getenv("TF_HEDGE_DISAGG_TFS", "5m,15m,1h,4h").split(",") if tf.strip()]
# Minimum number of minority TFs that must agree before emitting a hedge intent.
# Prevents a single noisy TF from triggering a hedge open.
TF_HEDGE_DISAGG_MIN_TFS = int(os.getenv("TF_HEDGE_DISAGG_MIN_TFS", "2"))

# ── Dual-Leg Guard: prevent opening hedge when opposite leg already exists ──
# When True, trainer suppresses OPEN_HEDGE_* if the symbol already has BOTH legs
# open on the target account. Only ADD_HEDGE_* (scale existing) allowed.
ENABLE_HEDGE_DUAL_LEG_GUARD = os.getenv("ENABLE_HEDGE_DUAL_LEG_GUARD", "true").lower() in ("true", "1", "yes")

# ── RANGE mode: minimum price samples before range detection is valid ──
HEDGE_RANGE_MIN_SAMPLES = int(os.getenv("HEDGE_RANGE_MIN_SAMPLES", "40"))

# ── MTF Position Builder (gradual DCA for diverging timeframes) ──
ENABLE_MTF_POSITION_BUILDER = os.getenv("ENABLE_MTF_POSITION_BUILDER", "true").lower() in ("true", "1", "yes")
MTF_DIVERGENCE_MIN_SCORE = float(os.getenv("MTF_DIVERGENCE_MIN_SCORE", "0.30"))
MTF_DCA_MAX_PER_SYMBOL_PCT = float(os.getenv("MTF_DCA_MAX_PER_SYMBOL_PCT", "6.0"))
MTF_DCA_STEP_MAX_PCT = float(os.getenv("MTF_DCA_STEP_MAX_PCT", "3.0"))

TF_DEDUP_CONF_DELTA_MIN = float(os.getenv("TF_DEDUP_CONF_DELTA_MIN", "0.05"))
TF_DEDUP_WINDOW_SEC = int(os.getenv("TF_DEDUP_WINDOW_SEC", "600"))

REINFORCE_PDS_THRESHOLD = float(os.getenv("REINFORCE_PDS_THRESHOLD", "0.60"))

ENABLE_TF_PARTIAL_CLOSE = os.getenv("ENABLE_TF_PARTIAL_CLOSE", "true").lower() in ("true", "1", "yes")
TF_PARTIAL_CLOSE_MIN_RATIO = float(os.getenv("TF_PARTIAL_CLOSE_MIN_RATIO", "0.52"))

# FIX Apr 16: Minimum ROI before allowing partial closes (prevent premature profit-taking)
# Audit showed SOL partials at +$1.18 each while price went 86→89 (should have held)
# At 86x leverage, 10% ROI = only 0.12% price move — far too small to trigger exit
MIN_ROI_PCT_FOR_PARTIAL_CLOSE = float(os.getenv("MIN_ROI_PCT_FOR_PARTIAL_CLOSE", "15.0"))  # 15% ROI minimum before ANY partial close

# Additional FLIP conditions (any one triggers flip)
FLIP_TF_ALIGNMENT_ENABLED = os.getenv("FLIP_TF_ALIGNMENT_ENABLED", "true").lower() in ["1", "true", "yes"]  # Allow flip when 1m+5m agree
FLIP_MICROSTRUCTURE_PRESSURE_ENABLED = os.getenv("FLIP_MICROSTRUCTURE_PRESSURE_ENABLED", "true").lower() in ["1", "true", "yes"]  # Allow flip on high microstructure pressure
FLIP_MICROSTRUCTURE_THRESHOLD = float(os.getenv("FLIP_MICROSTRUCTURE_THRESHOLD", "0.90"))  # Spoof/fast_move score threshold to trigger flip

# ========== HEDGE MODE CONFIGURATION ==========
# Single hedge opener policy (Jan 2026)
#
# Problem:
# Multiple hedge systems can open hedge legs independently (proactive microstructure,
# adaptive hedge builder, hedge-first/flash-hedge conversion, trader-side adaptive hedges).
# This overlap causes duplicated hedge opens ("mystery hedges"), top/bottom hedges,
# and fee bleed from repeated re-hedging.
#
# Solution:
# Choose ONE hedge opener. All other hedge-open sources are suppressed in code.
#
# Allowed values:
# - "adaptive_hedge_builder_v2"  : Trainer progressive hedge builder (v2, recommended default)
# - "adaptive_hedge_builder"     : Trainer progressive hedge builder (legacy)
# - "proactive_microstructure"   : Trainer microstructure-proactive hedges (emergency-style)
# - "hedge_first"                : Trainer hedge-first conversion (model-opposite → OPEN_HEDGE_*)
# - "trader_dynamic"             : Trader-side DynamicAdaptiveHedge opens (executor overlay)
# - "always_hedge"               : Trainer always-hedge enforcement (emergency-only; not recommended for normal ops)
# - "off"                        : Disable hedge opens (not recommended; exits still allowed)
HEDGE_OPEN_POLICY = str(os.getenv("HEDGE_OPEN_POLICY", "trader_dynamic") or "trader_dynamic").strip().lower()

# Hedge rebalance (v2): profit-only reduction when hedge coverage is higher than the dynamic target.
# Safety defaults:
# - Enabled by default (can be disabled quickly via env)
# - Never forces a losing close (no-loss constraint)
HEDGE_REBALANCE_V2_ENABLED = os.getenv("HEDGE_REBALANCE_V2_ENABLED", "true").lower() in ("true", "1", "yes")

# ENABLE_ALWAYS_HEDGE: Forces hedges on every position.
# Addendum v3: this is emergency-only; normal operations should rely on Hedge Manager / hedge builder modes.
ENABLE_ALWAYS_HEDGE = os.getenv("ENABLE_ALWAYS_HEDGE", "false").lower() in ["1", "true", "yes"]

# CRITICAL: Continuous hedge ratio enforcement for no-loss system
# This ensures hedge is ALWAYS maintained, not just on model prediction
HEDGE_RATIO_ENFORCEMENT_ENABLED = os.getenv("HEDGE_RATIO_ENFORCEMENT_ENABLED", "false").lower() in ["1", "true", "yes"]
HEDGE_MIN_RATIO = float(os.getenv("HEDGE_MIN_RATIO", "0.30"))  # Minimum 30% hedge ratio
HEDGE_TARGET_RATIO = float(os.getenv("HEDGE_TARGET_RATIO", "0.50"))  # Target 50% hedge ratio
HEDGE_AUTO_READD_AFTER_HARVEST = os.getenv("HEDGE_AUTO_READD_AFTER_HARVEST", "true").lower() in ["1", "true", "yes"]
# Hedge harvest re-add behavior (Jan 2026 hardening):
# - Legacy behavior re-adds immediately after publishing a harvest.
# - Safer behavior waits for fill/position-confirmation before re-adding (prevents "phantom re-add" loops).
HEDGE_READD_FILL_CONFIRMED = os.getenv("HEDGE_READD_FILL_CONFIRMED", "true").lower() in ("1", "true", "yes")
# Pending re-add records TTL (seconds) when fill-confirmed mode is enabled.
HEDGE_READD_PENDING_TTL_SECONDS = int(os.getenv("HEDGE_READD_PENDING_TTL_SECONDS", "600"))  # 10 minutes
# Minimum re-add margin to avoid dust hedge adds (USD).
HEDGE_READD_MIN_MARGIN_USD = float(os.getenv("HEDGE_READD_MIN_MARGIN_USD", "15.0"))
# Dynamic hedge target ratio (DHRT): optional replacement for static HEDGE_TARGET_RATIO in re-add logic.
# Default OFF to preserve legacy behavior.
HEDGE_DYNAMIC_TARGET_RATIO_ENABLED = os.getenv("HEDGE_DYNAMIC_TARGET_RATIO_ENABLED", "true").lower() in ("1", "true", "yes")
# Bounds (ratio, not percent): 0.15 = 15%, 0.75 = 75%
HEDGE_DYNAMIC_TARGET_RATIO_MIN = float(os.getenv("HEDGE_DYNAMIC_TARGET_RATIO_MIN", "0.15"))
HEDGE_DYNAMIC_TARGET_RATIO_MAX = float(os.getenv("HEDGE_DYNAMIC_TARGET_RATIO_MAX", "0.75"))
HEDGE_ENFORCEMENT_INTERVAL_SECONDS = int(os.getenv("HEDGE_ENFORCEMENT_INTERVAL_SECONDS", "60"))  # Check every 60s

# ========== FLASH CRASH/PUMP PROTECTION (Market Maker Manipulation Defense) ==========
# Auto-hedge on rapid price moves to prevent liquidation on stop hunts
# Works alongside microstructure execution gate (Phase 6) for comprehensive timing protection
FLASH_MOVE_PROTECTION_ENABLED = os.getenv("FLASH_MOVE_PROTECTION_ENABLED", "true").lower() in ["1", "true", "yes"]
FLASH_MOVE_THRESHOLD_PCT = float(os.getenv("FLASH_MOVE_THRESHOLD_PCT", "1.0"))  # 1%+ move in <10min triggers hedge
FLASH_MOVE_WINDOW_SECONDS = int(os.getenv("FLASH_MOVE_WINDOW_SECONDS", "600"))  # Detection window (10min for slower moves)
FLASH_HEDGE_MIN_PNL_PCT = float(os.getenv("FLASH_HEDGE_MIN_PNL_PCT", "1.5"))  # Close both sides if hedge profits >1.5%
FLASH_HEDGE_COOLDOWN_SECONDS = int(os.getenv("FLASH_HEDGE_COOLDOWN_SECONDS", "300"))  # 5min cooldown between flash hedges

# MICROSTRUCTURE QUICK PROFIT: Take profits when microstructure signals reversal pressure
MICROSTRUCTURE_QUICK_PROFIT_ENABLED = os.getenv("MICROSTRUCTURE_QUICK_PROFIT_ENABLED", "true").lower() in ["1", "true", "yes"]
MICROSTRUCTURE_QUICK_PROFIT_MIN_PNL = float(os.getenv("MICROSTRUCTURE_QUICK_PROFIT_MIN_PNL", "30.0"))  # Min 30% profit for micro TP (was 15% — cut winners mid-trend)
MICROSTRUCTURE_QUICK_PROFIT_PRESSURE_THRESHOLD = float(os.getenv("MICROSTRUCTURE_QUICK_PROFIT_PRESSURE_THRESHOLD", "0.85"))  # Pressure score to trigger (was 0.75 — too sensitive)

# SQUEEZE CAPTURE: Enable dual-side hedging to capture squeeze moves both ways
SQUEEZE_CAPTURE_ENABLED = os.getenv("SQUEEZE_CAPTURE_ENABLED", "true").lower() in ["1", "true", "yes"]
SQUEEZE_MIN_PROFIT_PCT = float(os.getenv("SQUEEZE_MIN_PROFIT_PCT", "15.0"))  # 15% min profit for squeeze (excluding fees)
SQUEEZE_HEDGE_BOTH_SIDES = os.getenv("SQUEEZE_HEDGE_BOTH_SIDES", "true").lower() in ["1", "true", "yes"]  # Trail both LONG and SHORT legs

# PORTFOLIO REBALANCING: Close low-confidence positions to make room for high-confidence ones
ENABLE_PORTFOLIO_REBALANCE = os.getenv("ENABLE_PORTFOLIO_REBALANCE", "true").lower() in ["1", "true", "yes"]
REBALANCE_MIN_CONFIDENCE_DELTA = float(os.getenv("REBALANCE_MIN_CONFIDENCE_DELTA", "0.90"))  # New signal must be 90%+ confidence to trigger rebalance
REBALANCE_MIN_CONFIDENCE_IMPROVEMENT = float(os.getenv("REBALANCE_MIN_CONFIDENCE_IMPROVEMENT", "0.10"))  # New signal must beat weakest position by this delta
REBALANCE_MAX_POSITIONS_TO_CLOSE = int(os.getenv("REBALANCE_MAX_POSITIONS_TO_CLOSE", "2"))  # Max positions to close per rebalance

# Rebalance can use extra 10% budget if the symbol being opened was previously closed (weak reversal)
_rebal_rev_raw = os.getenv("REBALANCE_REVERSAL_BUDGET_BONUS_PCT", "0.10")
REBALANCE_REVERSAL_BUDGET_BONUS_PCT = float(_rebal_rev_raw) / 100.0 if float(_rebal_rev_raw) > 1.0 else float(_rebal_rev_raw)  # +10% for reversed weak positions

# ========================================================================
# STEALTH TRAILING STOP CONFIGURATION
# These control the position-driven profit protection that works independently
# of trainer signals - ensures profits are captured for all positions
# ========================================================================
# Minimum ROI% on margin before trailing stop is armed
# Stealth Trailing Stop Configuration - DYNAMIC (Trainer-Driven)
# These are FALLBACK values only - trainer should compute optimal levels based on:
# - Current ATR/volatility (wider trail in volatile markets)
# - Support/resistance proximity
# - Order book depth (avoid thin liquidity zones)
# - Position duration and momentum
# Set to 0 to disable static fallback and rely purely on trainer signals
#
# UPDATED 2025-12-28: Widened stops to reduce premature exits
# CRITICAL: These are ROI% thresholds, NOT price%. With 10x leverage:
# - 15% ROI = 1.5% price move (reasonable activation)
# - 8% distance = 0.8% price pullback allowed before trail triggers
# - 5% callback = 0.5% price retracement to trigger
# Previous values (3%/2.5%/2%) were too tight, causing constant premature exits

# KILL SWITCHES for stealth stops (temporarily disable specific features)
STEALTH_STOP_LOSS_ENABLED = os.getenv("STEALTH_STOP_LOSS_ENABLED", "false").lower() in ("true", "1", "yes")  # disabled by default
STEALTH_TAKE_PROFIT_ENABLED = os.getenv("STEALTH_TAKE_PROFIT_ENABLED", "true").lower() in ("true", "1", "yes")  # Enabled by default
STEALTH_TRAILING_ENABLED = os.getenv("STEALTH_TRAILING_ENABLED", "true").lower() in ("true", "1", "yes")  # Enabled by default

# HEDGE PROTECTION: Prevent closing hedged positions at a loss
# When enabled, positions with an active hedge cannot trigger stop loss
# They CAN still trigger take profit and trailing profit (maker-only)
STEALTH_HEDGE_PROTECTION_ENABLED = os.getenv("STEALTH_HEDGE_PROTECTION_ENABLED", "true").lower() in ("true", "1", "yes")
STEALTH_HEDGE_PROFIT_ONLY = os.getenv("STEALTH_HEDGE_PROFIT_ONLY", "true").lower() in ("true", "1", "yes")  # Only allow TP when hedged
STEALTH_HEDGE_MAKER_ONLY = os.getenv("STEALTH_HEDGE_MAKER_ONLY", "true").lower() in ("true", "1", "yes")  # Force maker orders when hedged

# HEDGE TP GUARDRAILS (P0 liquidation hardening)
# Prevent the system from trimming a profitable SHORT hedge via TP while the LONG leg is still liquidation-risk.
# Enforced in `trading/stealth_stops.py` right before any TP close is placed.
HEDGE_TP_GUARD_ENABLED = os.getenv("HEDGE_TP_GUARD_ENABLED", "true").lower() in ("true", "1", "yes")
STRESS_FREEZE_TP_ON_HEDGE = os.getenv("STRESS_FREEZE_TP_ON_HEDGE", "true").lower() in ("true", "1", "yes")
# Buffer is in basis points (bps): 120 bps = 1.2% distance-to-liquidation floor.
HEDGE_TP_LIQ_BUFFER_BPS = float(os.getenv("HEDGE_TP_LIQ_BUFFER_BPS", "200"))
# Maintain a minimum remaining hedge coverage after TP trims:
# remaining_short_qty >= long_qty * MIN_HEDGE_COVERAGE
MIN_HEDGE_COVERAGE = float(os.getenv("MIN_HEDGE_COVERAGE", "0.70"))

# TRAILING STOP CONFIGURATION (UPDATED 2025-12-30)
# At high leverage (50-100x), price-based trailing must be tight
# 30% ROI activation = position is profitable enough to protect
# 0.4% trail distance = trails every ~0.3-0.5% price move
# This is leverage-aware: 0.4% price at 89x = ~35% ROI drawdown
STEALTH_TRAIL_ACTIVATION_PCT = float(os.getenv("STEALTH_TRAIL_ACTIVATION_PCT", "20.0"))  # FIX Apr 16: 10→20% ROI. At 86x leverage, 10% ROI = 0.12% price move — too early. Need room to ride trends.
STEALTH_TRAIL_DISTANCE_PCT = float(os.getenv("STEALTH_TRAIL_DISTANCE_PCT", "2.5"))  # 2.5% price distance base (was 1.2% — too tight at high leverage)
STEALTH_TRAIL_CALLBACK_PCT = float(os.getenv("STEALTH_TRAIL_CALLBACK_PCT", "1.5"))  # 1.5% callback to trigger (was 1.0% — survive deeper pullbacks during trends)

# Breakeven stop feature - when trailing activates, also place breakeven stop
STEALTH_TRAIL_BREAKEVEN_ENABLED = os.getenv("STEALTH_TRAIL_BREAKEVEN_ENABLED", "true").lower() in ("true", "1", "yes")
STEALTH_TRAIL_BREAKEVEN_BUFFER_PCT = float(os.getenv("STEALTH_TRAIL_BREAKEVEN_BUFFER_PCT", "0.05"))  # 0.05% above entry for fees

# Stealth TP maker near-touch placement (reduce-only)
STEALTH_TP_MAKER_ENABLED = os.getenv("STEALTH_TP_MAKER_ENABLED", "true").lower() in ("true", "1", "yes")
STEALTH_TP_MAKER_NEAR_BPS = float(os.getenv("STEALTH_TP_MAKER_NEAR_BPS", "10.0"))  # 10 bps near-touch
STEALTH_TP_MAKER_COOLDOWN_SEC = int(os.getenv("STEALTH_TP_MAKER_COOLDOWN_SEC", "15"))

# TP touch fallback (maker-first + IOC fallback on fast crosses)
TP_TOUCH_FALLBACK_ENABLED = os.getenv("TP_TOUCH_FALLBACK_ENABLED", "true").lower() in ("true", "1", "yes")
TP_TOUCH_FALLBACK_SEC = float(os.getenv("TP_TOUCH_FALLBACK_SEC", "2.5"))
TP_TOUCH_CONFIRM_TICKS = int(os.getenv("TP_TOUCH_CONFIRM_TICKS", "2"))
TP_TOUCH_BUFFER_BPS = float(os.getenv("TP_TOUCH_BUFFER_BPS", "5.0"))
TP_MAKER_NEAR_ENABLED = os.getenv("TP_MAKER_NEAR_ENABLED", "true").lower() in ("true", "1", "yes")
TP_MAKER_COOLDOWN_SEC = int(os.getenv("TP_MAKER_COOLDOWN_SEC", "10"))
TP_FASTMOVE_DIRECT_IOC = os.getenv("TP_FASTMOVE_DIRECT_IOC", "true").lower() in ("true", "1", "yes")
TP_FASTMOVE_SCORE_MIN = float(os.getenv("TP_FASTMOVE_SCORE_MIN", "0.8"))
TP_POSTONLY_REJECT_MAX = int(os.getenv("TP_POSTONLY_REJECT_MAX", "2"))

# ================================================================================
# TRAINER-INTEGRATED DYNAMIC TP - Ride Big Moves with Trainer Intelligence
# ================================================================================
# When enabled, stealth_stops reads trainer signals from Redis to dynamically adjust:
# - Suppresses static TP when trainer detects momentum continuation
# - Enables partial exits on REVERSAL_IMMINENT signals
# - Widens trailing distance during strong trends
# 
# Redis Keys Read:
#   wma:ride_move:{SYMBOL} - TTL-based flag: {"suppress_tp": true, "reason": "...", "until_ts": ...}
#   wma:trainer:exit_signal:{SYMBOL} - Proactive exit signals from trainer
#
# This allows trainer's microstructure/hedge modules to override stealth_stop's static TP
# and instead let positions ride until trainer detects reversal signals.
# ================================================================================
STEALTH_TRAINER_INTEGRATION_ENABLED = os.getenv("STEALTH_TRAINER_INTEGRATION_ENABLED", "true").lower() in ("true", "1", "yes")

# ================================================================================
# TRAINER INTENT TP DEFERENCE — Defer TP Closes to Trainer's Direction
# ================================================================================
# When enabled, ALL TP paths (static, maker, IOC, trailing) in stealth_stops check
# trainer intent BEFORE executing.  If the position aligns with the trainer's
# high-confidence directional intent, the TP is DEFERRED — trainer controls exit
# timing via CLOSE/FLIP/PARTIAL_CLOSE signals instead of stealth TP.
#
# This prevents the "close at TP → re-enter at worse price" cycle.
#
# Integration points:
#   1. stealth_stops: gates maker/IOC/static TP paths
#   2. dynamic_tp_engine: suppresses TIGHTEN_TP / RANGE_TIGHTEN when aligned
#   3. Partial TP: first TP hit closes only TP_PARTIAL_CLOSE_PCT; remainder trails
#
# Kill-switch: TRAINER_INTENT_TP_DEFERENCE_ENABLED=false
# ================================================================================
TRAINER_INTENT_TP_DEFERENCE_ENABLED = os.getenv("TRAINER_INTENT_TP_DEFERENCE_ENABLED", "true").lower() in ("true", "1", "yes")
TRAINER_INTENT_TP_MIN_CONFIDENCE = float(os.getenv("TRAINER_INTENT_TP_MIN_CONFIDENCE", "0.80"))  # Min trainer conf to defer TP
TRAINER_INTENT_TRAIL_WIDEN_MULT = float(os.getenv("TRAINER_INTENT_TRAIL_WIDEN_MULT", "2.5"))     # Widen trailing distance when aligned (was 1.8x — give strong trends more room)
STEALTH_SL_TRAINER_DEFERENCE_ENABLED = os.getenv("STEALTH_SL_TRAINER_DEFERENCE_ENABLED", "true").lower() in ("true", "1", "yes")

# ================================================================================
# PROFIT HEDGE BUILD — Slowly open opposite leg when position is profitable
# and trainer signals mean-reversion or reversal.
#
# When enabled, stealth_stops will emit ADD_HEDGE_{opp} proposals to wma:proposals
# whenever:
#   1. An open TP stop has ROI above the ATR-adaptive threshold (min 5%, max 25%)
#   2. Trainer consensus direction OPPOSES the current position
#   3. Reversal score (conf × regime_factor × imbalance_factor) ≥ adaptive floor
#   4. No Redis cooldown active (hedge:build:cd:{sym}:{side})
#
# Hedge sizing is fully adaptive: 5-20% of position notional, scaled with
# reversal confidence.  Kill-switch: PROFIT_HEDGE_BUILD_ENABLED=false
# ================================================================================
PROFIT_HEDGE_BUILD_ENABLED = os.getenv("PROFIT_HEDGE_BUILD_ENABLED", "true").lower() in ("true", "1", "yes")

# ================================================================================
# PARTIAL TP ON FIRST HIT — Close only a fraction, trail the rest
# ================================================================================
# Instead of 100% close when TP triggers (and position is NOT deferred by trainer),
# close only TP_PARTIAL_CLOSE_PCT on the first hit.  The remainder stays open with
# a wider trailing stop.  This prevents full exits before trend completion.
# Set to 100.0 to disable (legacy behavior = full close on first TP).
# ================================================================================
TP_PARTIAL_CLOSE_PCT = float(os.getenv("TP_PARTIAL_CLOSE_PCT", "35.0"))             # First TP hit: close 35% (was 50% — let 65% trail for bigger moves)
TP_PARTIAL_REMAINDER_TRAIL = os.getenv("TP_PARTIAL_REMAINDER_TRAIL", "true").lower() in ("true", "1", "yes")  # Trail the remainder
TP_PARTIAL_TRAIL_DISTANCE_MULT = float(os.getenv("TP_PARTIAL_TRAIL_DISTANCE_MULT", "2.0"))  # 2.0x wider trail for remainder (was 1.5x — give trends room to breathe)

# Hedge-first TP protection: when a winner TP is hit while the opposite hedge leg
# is still deeply underwater, do NOT peel the winner immediately. Convert the TP
# into a profit-lock stop so the account keeps the winner alive while the losing
# hedge can recover / unwind more safely. Kill switch defaults ON for live safety.
HEDGE_TP_PROTECTIVE_TRAIL_ENABLED = os.getenv("HEDGE_TP_PROTECTIVE_TRAIL_ENABLED", "true").lower() in ("true", "1", "yes")
HEDGE_TP_PROTECTIVE_MIN_WIN_USD = float(os.getenv("HEDGE_TP_PROTECTIVE_MIN_WIN_USD", "5.0"))
HEDGE_TP_PROTECTIVE_OPP_LOSS_USD = float(os.getenv("HEDGE_TP_PROTECTIVE_OPP_LOSS_USD", "25.0"))
HEDGE_TP_PROTECTIVE_NET_PAIR_MAX_USD = float(os.getenv("HEDGE_TP_PROTECTIVE_NET_PAIR_MAX_USD", "15.0"))
HEDGE_TP_PROTECTIVE_LOCK_FRAC = float(os.getenv("HEDGE_TP_PROTECTIVE_LOCK_FRAC", "0.35"))

# ================================================================================
# DYNAMIC TP ENGINE - Feature-Driven Adaptive Profit Optimization
# ================================================================================
# When enabled, TP levels are continuously recalculated based on 200+ market features:
# - Volatility (ATR, BBands) → Wider TP in volatile markets
# - Momentum (RSI, MACD, ADX) → Suppress TP with strong aligned momentum
# - Liquidation levels → Widen TP to capture squeezes
# - Microstructure (order flow, spoofing) → Tighten TP on adverse flow
# - Funding/OI → Adjust based on market positioning
#
# This replaces static % TP with intelligent, market-adaptive profit targets.
# ================================================================================
DYNAMIC_TP_ENABLED = os.getenv("DYNAMIC_TP_ENABLED", "true").lower() in ("true", "1", "yes")
DYNAMIC_TP_BASE_PCT = float(os.getenv("DYNAMIC_TP_BASE_PCT", "8.0"))       # Base 8% TP (crypto needs room — was 5%)
DYNAMIC_TP_MIN_PCT = float(os.getenv("DYNAMIC_TP_MIN_PCT", "4.0"))         # Minimum 4% TP (was 2.5% — closed too early)
DYNAMIC_TP_MAX_PCT = float(os.getenv("DYNAMIC_TP_MAX_PCT", "50.0"))        # Maximum 50% TP (was 30% — let trending winners run longer for 1-2x daily target)
DYNAMIC_TP_UPDATE_INTERVAL = int(os.getenv("DYNAMIC_TP_UPDATE_INTERVAL", "300"))  # FIX Apr 16: 60→300s. 2874 SET_TP signals/10h = spam noise. Update every 5 min max.
DYNAMIC_TP_MIN_CHANGE_PCT = float(os.getenv("DYNAMIC_TP_MIN_CHANGE_PCT", "0.8"))  # Only update if TP changes >0.8%

# ==============================================================================
# PROFIT-LOCK TRAILING (SOLE TP AUTHORITY)
# ==============================================================================
# Enables MFE-based profit-lock trailing and disables ladder/static TP use.
# This uses a lock curve to protect gains while letting winners run.
PROFIT_LOCK_TP_ENABLED = os.getenv("PROFIT_LOCK_TP_ENABLED", "true").lower() in ("true", "1", "yes")
PROFIT_LOCK_MIN_ROE = float(os.getenv("PROFIT_LOCK_MIN_ROE", "1.5"))  # Min ROE% to start profit-lock (was 2.0% — lock gains earlier)
PROFIT_LOCK_MIN_LOCK_FRAC = float(os.getenv("PROFIT_LOCK_MIN_LOCK_FRAC", "0.25"))
PROFIT_LOCK_MAX_LOCK_FRAC = float(os.getenv("PROFIT_LOCK_MAX_LOCK_FRAC", "0.90"))
PROFIT_LOCK_K = float(os.getenv("PROFIT_LOCK_K", "0.02"))  # Curve steepness (ROE space)
PROFIT_LOCK_TIGHTEN_MULT = float(os.getenv("PROFIT_LOCK_TIGHTEN_MULT", "0.80"))  # Tighten giveback on adverse conditions
PROFIT_LOCK_LOOSEN_MULT = float(os.getenv("PROFIT_LOCK_LOOSEN_MULT", "1.20"))  # Loosen giveback on strong trends
PROFIT_LOCK_MIN_UPDATE_PCT = float(os.getenv("PROFIT_LOCK_MIN_UPDATE_PCT", "0.20"))  # Min stop move % to update
PROFIT_LOCK_UPDATE_INTERVAL_SEC = int(os.getenv("PROFIT_LOCK_UPDATE_INTERVAL_SEC", "10"))
PROFIT_LOCK_STATE_TTL_SEC = int(os.getenv("PROFIT_LOCK_STATE_TTL_SEC", "86400"))
PROFIT_LOCK_RANGE_MIN_MFE_ROE = float(os.getenv("PROFIT_LOCK_RANGE_MIN_MFE_ROE", "12.0"))
PROFIT_LOCK_RANGE_MIN_UPDATE_PCT = float(os.getenv("PROFIT_LOCK_RANGE_MIN_UPDATE_PCT", "1.0"))
PROFIT_LOCK_RANGE_UPDATE_INTERVAL_SEC = int(os.getenv("PROFIT_LOCK_RANGE_UPDATE_INTERVAL_SEC", "60"))
PROFIT_LOCK_CONFIRM_TICKS = int(os.getenv("PROFIT_LOCK_CONFIRM_TICKS", "2"))
PROFIT_LOCK_CONFIRM_SECS = int(os.getenv("PROFIT_LOCK_CONFIRM_SECS", "6"))
PROFIT_LOCK_VOL_BETA = float(os.getenv("PROFIT_LOCK_VOL_BETA", "1.6"))
PROFIT_LOCK_MIN_GIVEBACK_ROE = float(os.getenv("PROFIT_LOCK_MIN_GIVEBACK_ROE", "1.5"))
PROFIT_LOCK_FREEZE_SECS = int(os.getenv("PROFIT_LOCK_FREEZE_SECS", "15"))
PROFIT_LOCK_SHOCK_FAST_MOVE_SCORE = float(os.getenv("PROFIT_LOCK_SHOCK_FAST_MOVE_SCORE", "0.70"))
PROFIT_LOCK_SHOCK_LIQ_RISK = os.getenv("PROFIT_LOCK_SHOCK_LIQ_RISK", "HIGH").upper()
PROFIT_LOCK_HEDGE_BUDGET_FRAC = float(os.getenv("PROFIT_LOCK_HEDGE_BUDGET_FRAC", "0.35"))
PROFIT_LOCK_HEDGE_MAX_DURATION_SEC = int(os.getenv("PROFIT_LOCK_HEDGE_MAX_DURATION_SEC", "1800"))

# CRITICAL: do not hardcode a static ROE threshold for ride-the-move.
# We keep this as an optional *floor* (operator override), but the default is 0.0 and the
# effective threshold is computed dynamically from fees + ATR/volatility + microstructure.
STEALTH_RIDE_MOVE_MIN_ROE = float(os.getenv("STEALTH_RIDE_MOVE_MIN_ROE", "0.0"))
STEALTH_RIDE_MOVE_TTL_SEC = int(os.getenv("STEALTH_RIDE_MOVE_TTL_SEC", "600"))  # Ride-move flag expires after 10 min (was 5min — too short, all TPs fire when expired)
# Also allow ride-the-move to trigger from microstructure fast-move detection (trend continuation).
STEALTH_RIDE_MOVE_MIN_FAST_MOVE_SCORE = float(os.getenv("STEALTH_RIDE_MOVE_MIN_FAST_MOVE_SCORE", "0.70"))

# ============================================================================
# CRITICAL: Profit scanner hedge preservation (prevent trimming the hedge to ~0 in trends)
# ============================================================================
# When a symbol is dual-sided (both LONG+SHORT legs exist) and the dominant leg is underwater,
# do NOT allow the proactive profit scanner to shrink the hedge leg below a minimum coverage ratio.
PROFIT_SCANNER_HEDGE_PRESERVE_ENABLED = os.getenv("PROFIT_SCANNER_HEDGE_PRESERVE_ENABLED", "true").lower() in ("1", "true", "yes")
# Minimum hedge coverage ratio (smaller_notional / larger_notional). Example 0.25 = keep at least 25% hedge.
PROFIT_SCANNER_MIN_HEDGE_RATIO = float(os.getenv("PROFIT_SCANNER_MIN_HEDGE_RATIO", "0.25"))
# Only enforce preservation when the dominant leg is losing by at least this many USD (avoid tiny noise).
PROFIT_SCANNER_HEDGE_PRESERVE_MIN_DOMINANT_LOSS_USD = float(os.getenv("PROFIT_SCANNER_HEDGE_PRESERVE_MIN_DOMINANT_LOSS_USD", "10.0"))

# ================================================================================
# INCREASE Signal Safety (Jan 20, 2026)
# Allow trainer to re-add margin after profit scanner reduces position
# ================================================================================
ENABLE_INCREASE_AFTER_PROFIT_TAKING = os.getenv("ENABLE_INCREASE_AFTER_PROFIT_TAKING", "true").lower() in ("true", "1", "yes")
# Minimum time (seconds) between profit-taking and INCREASE to avoid immediate churn
INCREASE_AFTER_PROFIT_COOLDOWN_SEC = int(os.getenv("INCREASE_AFTER_PROFIT_COOLDOWN_SEC", "60"))
# Minimum profit scanner reduction (%) to qualify for INCREASE
INCREASE_MIN_REDUCTION_PCT = float(os.getenv("INCREASE_MIN_REDUCTION_PCT", "15.0"))
# Require ride_move active for INCREASE after profit-taking
INCREASE_REQUIRE_RIDE_MOVE = os.getenv("INCREASE_REQUIRE_RIDE_MOVE", "true").lower() in ("true", "1", "yes")
# Allow scaling profitable leg in hedge mode
HEDGE_ALLOW_SCALE_WINNER = os.getenv("HEDGE_ALLOW_SCALE_WINNER", "true").lower() in ("true", "1", "yes")
# Minimum PnL% on leg to allow INCREASE in hedge mode
HEDGE_MIN_PNL_FOR_INCREASE = float(os.getenv("HEDGE_MIN_PNL_FOR_INCREASE", "5.0"))
# Maximum leverage allowed for INCREASE signals
INCREASE_MAX_LEVERAGE = int(os.getenv("INCREASE_MAX_LEVERAGE", "100"))
# Minimum liquidation distance % for INCREASE
INCREASE_MIN_LIQ_DISTANCE_PCT = float(os.getenv("INCREASE_MIN_LIQ_DISTANCE_PCT", "15.0"))
# Maximum funding rate (absolute %) against position for INCREASE
INCREASE_MAX_ADVERSE_FUNDING_PCT = float(os.getenv("INCREASE_MAX_ADVERSE_FUNDING_PCT", "0.05"))

# Optional: Apply INCREASE to BOTH legs when already dual-sided.
# Enabled by default per production request; can be disabled via env.
# When enabled, the trader will split the increase size across the requested leg + the opposite leg,
# subject to additional guards.
ENABLE_INCREASE_BOTH_LEGS = os.getenv("ENABLE_INCREASE_BOTH_LEGS", "true").lower() in ("true", "1", "yes")
# Opposite-leg size multiplier relative to the requested INCREASE size.
INCREASE_BOTH_LEGS_OPPOSITE_MULT = float(os.getenv("INCREASE_BOTH_LEGS_OPPOSITE_MULT", "0.25"))
# Only increase the opposite leg if its unrealized PnL% is at least this threshold (avoid trapping/caging).
INCREASE_BOTH_LEGS_MIN_OPPOSITE_PNL_PCT = float(os.getenv("INCREASE_BOTH_LEGS_MIN_OPPOSITE_PNL_PCT", "0.0"))

# ================================================================================
# STEALTH STOP EXECUTION - Maker-first (POST_ONLY/GTX) order strategy
# Uses limit orders with GTX (Good-Til-Crossing) to get maker fees (0.02%)
# Falls back to market only if limit doesn't fill within timeout
# ================================================================================
STEALTH_HYBRID_LIMIT_ENABLED = os.getenv("STEALTH_HYBRID_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
STEALTH_LIMIT_WAIT_MIN_SEC = int(os.getenv("STEALTH_LIMIT_WAIT_MIN_SEC", "10"))  # Min wait for limit fill
STEALTH_LIMIT_WAIT_MAX_SEC = int(os.getenv("STEALTH_LIMIT_WAIT_MAX_SEC", "60"))  # Max wait for limit fill
STEALTH_LIMIT_PRICE_OFFSET_MIN_PCT = float(os.getenv("STEALTH_LIMIT_PRICE_OFFSET_MIN_PCT", "0.03"))  # Min offset from market
STEALTH_LIMIT_PRICE_OFFSET_MAX_PCT = float(os.getenv("STEALTH_LIMIT_PRICE_OFFSET_MAX_PCT", "0.08"))  # Max offset from market
MAKER_FEE_PCT = float(os.getenv("MAKER_FEE_PCT", "0.02"))  # Binance Futures maker fee
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.05"))  # Binance Futures taker fee

# ================================================================================
# TRADER SERVER-SIDE TRAILING STOPS (Binance TRAILING_STOP_MARKET)
# Default: disabled. We rely on `trading/stealth_stops.py` for maker-first exits.
# ================================================================================
TRADER_SERVER_SIDE_TRAILING_STOP_ENABLED = os.getenv("TRADER_SERVER_SIDE_TRAILING_STOP_ENABLED", "false").lower() in ("1", "true", "yes")

# ================================================================================
# DYNAMIC ADAPTIVE STOPS - Market-intelligent stop loss and take profit
# These values are BASE levels that get dynamically adjusted based on:
# - Volatility (ATR, realized vol, BBands width)
# - Liquidation levels and squeeze potential
# - Microstructure (order flow, spoofing, fast moves)
# - Technical indicators (RSI, MACD, ADX, BBands)
# - Open Interest and Funding Rate
# 
# IMPROVED 2025-12-28: Wider stops to let trades breathe and capture more profit
# FIXED 2026-03-19: Defaults aligned with .env wider values per session_summary.md
# ================================================================================
ADAPTIVE_STOPS_ENABLED = os.getenv("ADAPTIVE_STOPS_ENABLED", "true").lower() in ["1", "true", "yes"]
ADAPTIVE_BASE_SL_PCT = float(os.getenv("ADAPTIVE_BASE_SL_PCT", "4.0"))       # Base 4% price (40% ROE at 10x) - Room to breathe
ADAPTIVE_BASE_SL_PCT_WITH_HEDGE = float(os.getenv("ADAPTIVE_BASE_SL_PCT_WITH_HEDGE", "5.0"))  # 5% when hedged (50% ROE)
ADAPTIVE_BASE_TP_PCT = float(os.getenv("ADAPTIVE_BASE_TP_PCT", "6.0"))       # Base 6% price (60% ROE at 10x) - Wider to capture moves
ADAPTIVE_MIN_SL_PCT = float(os.getenv("ADAPTIVE_MIN_SL_PCT", "2.0"))         # Min 2% (20% ROE) - Allow room
ADAPTIVE_MAX_SL_PCT = float(os.getenv("ADAPTIVE_MAX_SL_PCT", "10.0"))        # Max 10% (100% ROE) - only with hedge
ADAPTIVE_MIN_TP_PCT = float(os.getenv("ADAPTIVE_MIN_TP_PCT", "3.0"))         # Min 3% (30% ROE) - Don't exit too early
ADAPTIVE_MAX_TP_PCT = float(os.getenv("ADAPTIVE_MAX_TP_PCT", "20.0"))        # Max 20% (200% ROE) - Allow larger trend captures
ADAPTIVE_TRAIL_ACTIVATION = float(os.getenv("ADAPTIVE_TRAIL_ACTIVATION", "15.0"))  # 15% ROE to activate trailing - Let winners run
ADAPTIVE_TRAIL_DISTANCE = float(os.getenv("ADAPTIVE_TRAIL_DISTANCE", "8.0"))       # 8% ROE trailing distance

# Safety Hedge - automatic hedge when position goes sideways/losing
SAFETY_HEDGE_ROE_THRESHOLD = float(os.getenv("SAFETY_HEDGE_ROE_THRESHOLD", "-45.0"))  # Open hedge at -45% ROE
SAFETY_HEDGE_SIZE_PCT = float(os.getenv("SAFETY_HEDGE_SIZE_PCT", "50.0"))             # Hedge 50% of position

# ================================================================================
# DYNAMIC ADAPTIVE HEDGE - Market-intelligent hedge building
# Hedges are triggered and sized dynamically based on the same data sources
# plus additional unified features from Redis and live websocket data
# ================================================================================
# NOTE: Fixed to skip already-hedged positions (won't hedge the hedge anymore)
ADAPTIVE_HEDGE_ENABLED = os.getenv("ADAPTIVE_HEDGE_ENABLED", "true").lower() in ["1", "true", "yes"]
ADAPTIVE_HEDGE_BASE_TRIGGER_ROE = float(os.getenv("ADAPTIVE_HEDGE_BASE_TRIGGER_ROE", "15.0"))  # Base 15% ROE to start hedging
ADAPTIVE_HEDGE_MAX_SIZE_PCT = float(os.getenv("ADAPTIVE_HEDGE_MAX_SIZE_PCT", "50.0"))          # Max 50% of position to hedge
# NOTE: Static 10% floor caused over-hedging in calm regimes. The hedge engine now sizes
# continuously from risk/microstructure/volatility; this env var is kept for compatibility
# but defaults to 0.0 and is not enforced as a hard floor.
ADAPTIVE_HEDGE_MIN_SIZE_PCT = float(os.getenv("ADAPTIVE_HEDGE_MIN_SIZE_PCT", "0.0"))
ADAPTIVE_HEDGE_UNWIND_ROE = float(os.getenv("ADAPTIVE_HEDGE_UNWIND_ROE", "8.0"))               # Unwind hedge when ROE drops to 8%
ADAPTIVE_HEDGE_COOLDOWN_SEC = int(os.getenv("ADAPTIVE_HEDGE_COOLDOWN_SEC", "180"))              # TIGHTENED: 3min between hedge actions (was 60s)

# Proactive Hedge Protection (DYNAMIC thresholds based on confidence)
# NOTE: Fixed to skip already-hedged positions (won't hedge the hedge anymore)
ENABLE_PROACTIVE_HEDGING = True  # Automatically suggest opening opposite side to protect positions

# Base thresholds (dynamically adjusted in trainer based on confidence):
# HIGH confidence (90%+):     Hedge at +1.0% profit, 75% hedge size
# GOOD confidence (80-90%):   Hedge at +1.5% profit, 60% hedge size  
# MEDIUM confidence (75-80%): Hedge at +2.0% profit, 50% hedge size
# LOW confidence (70-75%):    Hedge at +3.0% profit, 33% hedge size
HEDGE_PROFIT_THRESHOLD = 2.0  # Base threshold (medium confidence)
HEDGE_SIZE_PERCENTAGE = 0.50  # Base hedge size (medium confidence)

# Position Management - Updated for 12 position strategy (6 LONG + 6 SHORT)
MAX_CONCURRENT_POSITIONS = 20  # 20 symbols max (raised from 10 to match slot limits)
MIN_POSITION_HOLD_TIME = 600  # 10 minutes minimum hold time
MIN_REBALANCE_CONFIDENCE_DELTA = 0.05  # 5% confidence gap required for rebalancing
ENABLE_AUTO_REBALANCING = True  # ENABLED: Auto-close weak positions when margin limit reached

# Phase 1: 90% Confidence Implementation - Risk-Adjusted Rewards
USE_RISK_ADJUSTED_REWARD = True  # Feature flag for Phase 1A implementation
TRADE_PENALTY = 0.002  # Penalty per trade execution (reduces overtrading)
DRAWDOWN_PENALTY = 0.3  # Penalty multiplier for drawdown (0.3 = 30% DD adds -0.09 to reward)
PNL_SCALE = 100.0  # Scale factor to normalize PnL into tight reward range
EQUITY_CURVE_WINDOW = 1000  # Track last N steps for drawdown calculation

# ==========================================================================
# PPO REWARD FIX: Mark-to-Market + Scaling (fixes value_loss=0.0000)
# ==========================================================================
# Root cause: GPU env returned tiny fixed rewards (0.01 entries, ~0.0001 PnL-on-close).
# Fix: compute equity change EVERY step, scale to PPO-friendly magnitude, clip outliers.
#
# Mark-to-market: r_mtm = log(equity_now / equity_prev) per step (continuous signal)
RL_REWARD_MTM_ENABLED = os.getenv("RL_REWARD_MTM_ENABLED", "true").lower() in ("1", "true", "yes")
# Scale factor: raw MTM rewards are ~1e-5..1e-3; multiply to get ~1e-2..1e-1 for PPO
# CRITICAL FIX (2026-04-02): scale=500 caused EVERY step to clip at +5.0,
# destroying all learning signal. 3.4 billion timesteps of zero gradient.
# New scale=10 keeps rewards in [-2, +2] range — PPO-optimal.
RL_REWARD_SCALE = float(os.getenv("RL_REWARD_SCALE", "100.0"))  # FIX Apr 14: 10→100 so PnL signal >> entropy bonus
# Hard clip after scaling to prevent outlier gradient explosions
# CRITICAL FIX (2026-04-02): clip=5 with scale=500 meant 100% saturation.
# New clip=2.0 with scale=10 allows fine-grained reward differentiation.
RL_REWARD_CLIP = float(os.getenv("RL_REWARD_CLIP", "5.0"))  # FIX Apr 14: 2.0→5.0 to match reward_scale increase
# Drawdown penalty coefficient. Applied to dd_pct each step.
# FIX Apr 17: 0.1→0.02. Old value created death spiral (all actions → negative reward → HOLD trap).
RL_REWARD_DD_COEFF = float(os.getenv("RL_REWARD_DD_COEFF", "0.02"))
# Blend coefficient for discrete trade shaping term into MTM reward.
# Keep small to avoid reward saturation and preserve directional learning signal.
RL_TRADE_REWARD_BLEND = float(os.getenv("RL_TRADE_REWARD_BLEND", "0.1"))
# Diagnostic: print [REWARD_STATS] every N env steps (0 = disabled)
RL_REWARD_STATS_INTERVAL = int(os.getenv("RL_REWARD_STATS_INTERVAL", "2048"))
# Force close all positions at episode end and include terminal PnL
RL_REWARD_EPISODE_END_REALIZE = os.getenv("RL_REWARD_EPISODE_END_REALIZE", "true").lower() in ("1", "true", "yes")

# ==========================================================================
# REWARD SHAPING: Break HOLD-collapse local optimum
# ==========================================================================
# Problem: HOLD when flat gives 0 reward (risk-free optimum), model converges
# to always HOLD because any trade risks -0.05 invalid penalty or MTM loss.
# Fix: Make staying flat costly and trading rewarding.

# Per-step penalty for being flat (no position). Accumulates over episode.
# Over 1000 steps: -0.002 * 1000 = -2.0 total (makes pure HOLD strategy lose)
# FIX Apr 15: Reduced from -0.005 to -0.002 — at -5.0 total the flat penalty was
# maxing out RL_REWARD_CLIP=5.0, drowning out all other reward signals.
# At -2.0, HOLD is still costly but the model can learn from PnL differences.
RL_HOLD_FLAT_PENALTY = float(os.getenv("RL_HOLD_FLAT_PENALTY", "-0.002"))  # Per-step cost of being flat — 1000 steps = -2.0 total

# Per-step bonus for maintaining market exposure (holding a position)
# FIX Apr 15: Increased 5x from 0.0002 to 0.001 to better reward staying in positions
# Over 1000 steps: 0.001 * 1000 = 1.0 total — a meaningful positive signal
RL_POSITION_HOLD_BONUS = float(os.getenv("RL_POSITION_HOLD_BONUS", "0.001"))  # Per-step bonus for having exposure

# Bonus for successfully executing a valid trade (open/close/flip)
# Must be large enough to compensate for occasional invalid action penalties
RL_VALID_TRADE_BONUS = float(os.getenv("RL_VALID_TRADE_BONUS", "0.0"))  # DISABLED — trades rewarded only by PnL, not existence

# Penalty for attempting an invalid/impossible action
# FIX Apr 15: Reduced from -0.005 to -0.002 — was same magnitude as hold penalty,
# making exploration feel too costly. Small nudge is enough to learn valid actions.
RL_INVALID_ACTION_PENALTY = float(os.getenv("RL_INVALID_ACTION_PENALTY", "-0.002"))  # Small penalty for impossible actions

# Bonus multiplier for profitable trade closes.
# FIX Apr 15: Increased from 0.5 to 2.0 — with 0.5 the model had no incentive to
# find profitable exits; the reward signal was drowned out by penalties.
# At 2.0, closing a $10 profit gives strong positive gradient.
RL_PROFITABLE_CLOSE_BONUS = float(os.getenv("RL_PROFITABLE_CLOSE_BONUS", "2.0"))

# ==========================================================================
# TRAIN/PREDICT OBS ALIGNMENT: Position state + TF ordinal injection
# ==========================================================================
# Realistic Binance fees (maker=0.02%, taker=0.04%) — was 0.1% which is 2.5x too high
RL_TRANSACTION_COST = float(os.getenv("RL_TRANSACTION_COST", "0.0004"))

# Inject position state (dims 508-511) into prediction obs to match training env
# Kill switch: set false to disable (predictions will see flat position state)
ENABLE_POSITION_STATE_PREDICT = os.getenv("ENABLE_POSITION_STATE_PREDICT", "true").lower() in ("1", "true", "yes")

# Inject timeframe ordinal (dim 507) so model distinguishes TF-specific behavior
RL_TF_ORDINAL_ENABLED = os.getenv("RL_TF_ORDINAL_ENABLED", "true").lower() in ("1", "true", "yes")

# Asymmetric exit reward: penalty multiplier for LOSING closes
# Winners get PROFITABLE_CLOSE_BONUS, losers get loss * LOSS_PENALTY_MULT
RL_LOSS_PENALTY_MULT = float(os.getenv("RL_LOSS_PENALTY_MULT", "1.5"))

# Hold-time bonus: per-step reward for holding a PROFITABLE position.
# Increased from 0.0001 to 0.001 to incentivize letting winners run.
RL_HOLD_TIME_BONUS = float(os.getenv("RL_HOLD_TIME_BONUS", "0.001"))

# Early close penalty: penalize closing a profitable position before min hold steps.
# Penalty = close_pnl * RL_EARLY_CLOSE_PENALTY_FRAC when steps_in_position < RL_EARLY_CLOSE_MIN_STEPS.
RL_EARLY_CLOSE_MIN_STEPS = int(os.getenv("RL_EARLY_CLOSE_MIN_STEPS", "10"))
RL_EARLY_CLOSE_PENALTY_FRAC = float(os.getenv("RL_EARLY_CLOSE_PENALTY_FRAC", "0.5"))

# Direction-aware entry bonus (Feb 2026):
# Small reward for opening in the correct direction based on recent price movement.
# FIX Apr 15: Doubled from 0.005 to 0.01 — stronger directional learning signal.
RL_DIRECTION_BONUS = float(os.getenv("RL_DIRECTION_BONUS", "0.01"))

# Action-switch penalty (Feb 2026):
# Penalizes changing from one non-HOLD action to a different non-HOLD action
# in consecutive steps. Prevents the model from flip-flopping every step
# which destroys capital via transaction costs.
# FIX Apr 15: Reduced from 0.015 to 0.008 — was larger than direction bonus (0.005)
# making the model optimize for penalty avoidance. At 0.008, direction signal dominates.
RL_ACTION_SWITCH_PENALTY = float(os.getenv("RL_ACTION_SWITCH_PENALTY", "0.008"))
# Apply switch penalty only when opposite-direction re-entry happens quickly.
# Prevents penalizing normal regime transitions while still discouraging whipsaw churn.
RL_ACTION_SWITCH_MIN_SECONDS = float(os.getenv("RL_ACTION_SWITCH_MIN_SECONDS", "120"))

# ==========================================================================
# PPO ENTROPY COLLAPSE PREVENTION (2026-04-07)
# ==========================================================================
# Problem: PPO collapsed into 100% OPEN_LONG after 6000+ loops. Adaptive entropy
# floor was DISABLED (not in config). Enable to dynamically boost ent_coef when
# policy entropy drops below 40% of maximum (ln(7)=1.946).
ENTROPY_FLOOR_ENABLED = os.getenv("ENTROPY_FLOOR_ENABLED", "false").lower() in ("1", "true", "yes")  # FIX Apr 14: DISABLED - was boosting ent_coef to 0.30, drowning signal
ENTROPY_FLOOR_TARGET = float(os.getenv("ENTROPY_FLOOR_TARGET", "0.30"))  # FIX Apr 14: 0.50→0.30 (30% of max is healthy exploration)
ENTROPY_FLOOR_MAX_BOOST = float(os.getenv("ENTROPY_FLOOR_MAX_BOOST", "0.06"))  # FIX Apr 14: 0.30→0.06 (never exceed 3x base ent_coef)

# ==========================================================================
# SIGNAL VALIDATOR PRECISION MODE (2026-04)
# ==========================================================================
# Goal: prefer high-precision entries by requiring strong recent realized win-rate
# support before allowing exposure-increasing actions to pass.
# Backward-compatible and kill-switch controlled.
SIGNAL_VALIDATOR_PRECISION_MODE = os.getenv("SIGNAL_VALIDATOR_PRECISION_MODE", "true").lower() in ("1", "true", "yes")
# Live stabilization: 0.90 is effectively “almost no entries”; align with TF floors (~0.55) for throughput.
SIGNAL_VALIDATOR_TARGET_WIN_RATE = float(os.getenv("SIGNAL_VALIDATOR_TARGET_WIN_RATE", "0.58"))
SIGNAL_VALIDATOR_RECENT_WINDOW = int(os.getenv("SIGNAL_VALIDATOR_RECENT_WINDOW", "20"))
SIGNAL_VALIDATOR_MIN_BIN_SAMPLES = int(os.getenv("SIGNAL_VALIDATOR_MIN_BIN_SAMPLES", "8"))
SIGNAL_VALIDATOR_WINRATE_CONF_SLOPE = float(os.getenv("SIGNAL_VALIDATOR_WINRATE_CONF_SLOPE", "0.35"))
SIGNAL_VALIDATOR_COLDSTART_MIN_CONF = float(os.getenv("SIGNAL_VALIDATOR_COLDSTART_MIN_CONF", "0.55"))
SIGNAL_VALIDATOR_HOT_MIN_CONF = float(os.getenv("SIGNAL_VALIDATOR_HOT_MIN_CONF", "0.52"))
# Optional high-precision profile (paper/pre-funding):
# Restrict exposure-increasing actions to specific TFs and high confidence.
SIGNAL_VALIDATOR_HIGH_PRECISION_PROFILE_ENABLED = os.getenv("SIGNAL_VALIDATOR_HIGH_PRECISION_PROFILE_ENABLED", "false").lower() in ("1", "true", "yes")
SIGNAL_VALIDATOR_HIGH_PRECISION_TFS = [x.strip() for x in os.getenv("SIGNAL_VALIDATOR_HIGH_PRECISION_TFS", "5m,15m,1h,4h").split(",") if x.strip()]
SIGNAL_VALIDATOR_HIGH_PRECISION_MIN_CONF = float(os.getenv("SIGNAL_VALIDATOR_HIGH_PRECISION_MIN_CONF", "0.70"))

# ==========================================================================
# TF-SCALED EXIT PROFILES (2026-02-26)
# ==========================================================================
# Each originating timeframe gets different exit parameters.
# Higher TFs = wider targets, longer holds.  Lower TFs = tighter, faster.
# These are SCALING MULTIPLIERS applied to the DynamicTPEngine's base decisions.
# The DynamicTPEngine still computes data-driven TP/trail from 200+ features —
# these multipliers widen or tighten its output proportionally.
# Kill switch: TF_EXIT_PROFILE_ENABLED
TF_EXIT_PROFILE_ENABLED = os.getenv("TF_EXIT_PROFILE_ENABLED", "true").lower() in ("1", "true", "yes")

# Format: {tf: {tp_mult, trail_mult, min_hold_sec, trail_activation_mult, description}}
# tp_mult: scales TP% from DynamicTPEngine (>1 = wider target)
# trail_mult: scales trail distance (>1 = more room to breathe)
# trail_activation_mult: scales trail activation threshold (>1 = waits longer before arming trail)
# min_hold_sec: minimum hold time before exits are allowed
# hedge_tp_mult: scales TP for hedge legs (always tighter than main legs)
TF_EXIT_PROFILES = {
    "5m": {
        "tp_mult": 0.7,               # Tighter TP for scalps
        "trail_mult": 0.6,            # Tight trailing
        "trail_activation_mult": 0.8,  # Arm trail earlier
        "min_hold_sec": 120,           # 2 min minimum
        "hedge_tp_mult": 0.5,         # Hedge legs exit fast
        "description": "Scalp: tight TP, fast trail, quick exits",
    },
    "15m": {
        "tp_mult": 1.0,               # Base TP (DynamicTPEngine default)
        "trail_mult": 1.0,            # Base trailing
        "trail_activation_mult": 1.0,  # Base activation
        "min_hold_sec": 300,           # 5 min minimum
        "hedge_tp_mult": 0.6,         # Hedge legs tighter
        "description": "Tactical: balanced TP, standard trail",
    },
    "1h": {
        "tp_mult": 1.5,               # Wider TP for swings
        "trail_mult": 1.4,            # More room to breathe
        "trail_activation_mult": 1.3,  # Wait longer before arming
        "min_hold_sec": 900,           # 15 min minimum
        "hedge_tp_mult": 0.7,         # Hedge legs still tighter
        "description": "Swing: wide TP, patient trailing, longer hold",
    },
    "4h": {
        "tp_mult": 2.0,               # Widest TP for position trades
        "trail_mult": 1.8,            # Maximum room to breathe
        "trail_activation_mult": 1.5,  # Wait significantly before arming
        "min_hold_sec": 1800,          # 30 min minimum
        "hedge_tp_mult": 0.8,         # Hedge legs moderately tight
        "description": "Position: widest TP, patient trailing, hold for HTF target",
    },
}
# Fallback profile for unknown TFs (1m / missing)
TF_EXIT_PROFILE_DEFAULT = {
    "tp_mult": 1.0, "trail_mult": 1.0, "trail_activation_mult": 1.0,
    "min_hold_sec": 60, "hedge_tp_mult": 0.5, "description": "Default/protective",
}

# HTF-anchored hold override: when 4h bias is directional (LONG_ONLY/SHORT_ONLY),
# main-leg positions aligned with 4h cannot be closed by lower TF signals
# until either: (a) 4h bias flips, or (b) min_hold_sec elapsed.
# This prevents 5m noise from closing a 4h-backed swing trade prematurely.
HTF_HOLD_OVERRIDE_ENABLED = os.getenv("HTF_HOLD_OVERRIDE_ENABLED", "true").lower() in ("1", "true", "yes")

# ==========================================================================
# MICROSTRUCTURE-AWARE REWARD SHAPING (Training Only)
# ==========================================================================
# These reward adjustments teach the model to avoid entering during unfavorable
# microstructure conditions (wide spreads, spoofing, fast moves near liq zones).
# The model already SEES these features in its obs (implicitly in the 512-dim vector)
# but without reward signal it can't learn what they mean.
# Kill switch: RL_MICRO_REWARD_ENABLED
RL_MICRO_REWARD_ENABLED = os.getenv("RL_MICRO_REWARD_ENABLED", "true").lower() in ("1", "true", "yes")

# Penalty for opening during wide spread (basis points threshold)
RL_MICRO_SPREAD_PENALTY_BPS = float(os.getenv("RL_MICRO_SPREAD_PENALTY_BPS", "10.0"))  # > 10bps = penalty
RL_MICRO_SPREAD_PENALTY_AMOUNT = float(os.getenv("RL_MICRO_SPREAD_PENALTY_AMOUNT", "0.005"))

# Penalty for opening near detected spoofing
RL_MICRO_SPOOF_PENALTY_THRESHOLD = float(os.getenv("RL_MICRO_SPOOF_PENALTY_THRESHOLD", "0.5"))
RL_MICRO_SPOOF_PENALTY_AMOUNT = float(os.getenv("RL_MICRO_SPOOF_PENALTY_AMOUNT", "0.008"))

# Penalty for opening during fast moves (cascade risk)
RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD = float(os.getenv("RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD", "0.6"))
RL_MICRO_FAST_MOVE_PENALTY_AMOUNT = float(os.getenv("RL_MICRO_FAST_MOVE_PENALTY_AMOUNT", "0.010"))

# Bonus for closing during favorable microstructure (narrow spread, no spoof)
RL_MICRO_FAVORABLE_EXIT_BONUS = float(os.getenv("RL_MICRO_FAVORABLE_EXIT_BONUS", "0.003"))

# FIXED: Clear stale replay store on startup (one-time reset after death spiral fix)
# Set to false after the model has been retrained with good data
RL_REPLAY_STORE_RESET = os.getenv("RL_REPLAY_STORE_RESET", "false").lower() in ("1", "true", "yes")

# ==========================================================================
# TRAINER LEARNING: Persistent penalties for negative equity / negative legs
# ==========================================================================
# Operator requirement:
# - If overall equity is below the baseline, apply an ongoing penalty until equity recovers.
# - If any legs are negative, keep penalizing until those legs recover to green.
#
# These penalties affect training reward shaping (PPO + MASA) only. They do NOT force closes.
TRAIN_PERSISTENT_PENALTIES_ENABLED = os.getenv("TRAIN_PERSISTENT_PENALTIES_ENABLED", "true").lower() in ("1", "true", "yes")

# Penalty strength for equity being below baseline (normalized by baseline equity/balance).
# Example: if equity is -2% below baseline and K=2.0, penalty adds about -0.04 to reward.
TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K = float(os.getenv("TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K", "2.0"))

# Penalty strength for negative legs (normalized by baseline equity/balance).
# Uses total negative unrealized PnL (USD) when available (live), or reconstructed unrealized in env.
TRAIN_NEG_LEG_PENALTY_K = float(os.getenv("TRAIN_NEG_LEG_PENALTY_K", "1.5"))

# Multi-Signal Quality Scoring (OPTIONAL - disabled by default)
# Set to True to enable strict signal quality filtering (0-100 score, minimum 75 to execute)
ENABLE_SIGNAL_QUALITY_FILTER = False  # ⚠️ Disabled by default to maintain current behavior
MINIMUM_SIGNAL_QUALITY_SCORE = 75     # Minimum score (0-100) required to execute trade

# Signal Deconfliction (Production TA Section 1 - ENABLED FOR PRODUCTION)
# Set to True to enable multi-timeframe signal deconfliction (aggregates, resolves conflicts, prevents duplicates)
ENABLE_SIGNAL_DECONFLICTION = True     # ✅ ENABLED BY DEFAULT - uses _publish_decisions_batch_v2

# Telegram Alert Configuration
TELEGRAM_ENABLED = True                            # Master switch for Telegram alerts
TELEGRAM_SIGNAL_MIN_CONFIDENCE = 0.85              # Minimum confidence for Telegram AI signal alerts
TELEGRAM_SIGNAL_THRESHOLD = 0.85                   # Alias for consistency (same as above)
TRADING_EXEC_THRESHOLD = 0.75                      # Trader execution threshold (can execute below Telegram alert threshold)

# GPU Optimization (Production TA Section 3 - ENABLED FOR PRODUCTION)
# Set to True to enable batch GPU inference with zero CPU->GPU transfers in hot path
ENABLE_GPU_BATCH_INFERENCE = os.getenv("ENABLE_GPU_BATCH_INFERENCE", "true").lower() in ("1", "true", "yes")  # Enhanced for RTX 5080: Enable GPU batch inference for performance
GPU_BATCH_SIZE = 64  # INCREASED: Larger batches for 80% GPU utilization (was 32)

# Dynamic Leverage Cap (Production TA Section 4 - ENABLED FOR PRODUCTION)
# Set to True to enable dynamic leverage caps based on market volatility/stress
ENABLE_DYNAMIC_LEVERAGE_CAP = False    # ❌ DISABLED Apr 15: User mandate - leverage must NEVER be changed by trainer

# -----------------------------------------------------------------------------
# Adaptive leverage engine (trainer-side)
# -----------------------------------------------------------------------------
# Goal: keep leverage within SYMBOL_LEVERAGE_CONFIG tier ranges and optionally adapt leverage
# based on confidence + market risk (volatility/toxicity/spread) + margin headroom.
ENABLE_ADAPTIVE_LEVERAGE_ENGINE = os.getenv("ENABLE_ADAPTIVE_LEVERAGE_ENGINE", "true").lower() in ("1", "true", "yes")
# If true, trainer will read a small set of feature fields from Redis when not present in payload.
LEVERAGE_ENGINE_FETCH_FEATURES = os.getenv("LEVERAGE_ENGINE_FETCH_FEATURES", "true").lower() in ("1", "true", "yes")
# Timeframe to fetch features from for leverage decisions (5m is usually stable and cheap).
LEVERAGE_ENGINE_FEATURE_TF = os.getenv("LEVERAGE_ENGINE_FEATURE_TF", "5m")

# Risk weights (0..1-ish). Higher values reduce leverage more aggressively.
LEVERAGE_RISK_WEIGHT_ATR = float(os.getenv("LEVERAGE_RISK_WEIGHT_ATR", "0.55"))
LEVERAGE_RISK_WEIGHT_TOXICITY = float(os.getenv("LEVERAGE_RISK_WEIGHT_TOXICITY", "0.35"))
LEVERAGE_RISK_WEIGHT_SPREAD = float(os.getenv("LEVERAGE_RISK_WEIGHT_SPREAD", "0.25"))

# Headroom assist for hedges: when margin headroom is tight, prefer higher leverage (within tier max)
# so a downsized margin hedge still produces meaningful notional.
LEVERAGE_HEDGE_HEADROOM_ASSIST = os.getenv("LEVERAGE_HEDGE_HEADROOM_ASSIST", "true").lower() in ("1", "true", "yes")
LEVERAGE_HEDGE_HEADROOM_ASSIST_THRESHOLD_PCT = float(os.getenv("LEVERAGE_HEDGE_HEADROOM_ASSIST_THRESHOLD_PCT", "12.0"))

# Execution Feedback Loop (Production TA Section 5 - ENABLED FOR PRODUCTION)
# Set to True to enable execution confirmation tracking from trader to trainer
ENABLE_EXECUTION_FEEDBACK = True       # ✅ ENABLED BY DEFAULT - tracks latency/slippage

# Positions truth layer (canonical vs legacy key formats)
# Default OFF: do not write legacy symbol-only keys (positions:live:{symbol}).
# Set to True for emergency rollback compatibility.
ENABLE_POSITIONS_LIVE_LEGACY_WRITE = os.getenv("ENABLE_POSITIONS_LIVE_LEGACY_WRITE", "false").lower() in ("1", "true", "yes", "on")

# ==========================================================================
# EXECUTION OUTCOME FEEDBACK (Loss / Equity Collapse) - Safety Penalties
# ==========================================================================
# Traders publish additional outcome events into `wma:trader:execution_feedback`.
# Trainer may set per-account risk-off keys. Defaults are FAIL-SAFE:
# risk-off blocks new risk (OPEN_RISK), not exits.

ENABLE_LOSS_EXIT_FEEDBACK = os.getenv("ENABLE_LOSS_EXIT_FEEDBACK", "true").lower() in ("1", "true", "yes")
ENABLE_EQUITY_COLLAPSE_FEEDBACK = os.getenv("ENABLE_EQUITY_COLLAPSE_FEEDBACK", "true").lower() in ("1", "true", "yes")

# Equity collapse trigger (absolute floor). Use a small floor so minor drawdowns don’t trigger.
EQUITY_COLLAPSE_USD_THRESHOLD = float(os.getenv("EQUITY_COLLAPSE_USD_THRESHOLD", "10.0"))

# Throttle: avoid spamming repeated collapse events.
EQUITY_COLLAPSE_FEEDBACK_THROTTLE_SECONDS = int(os.getenv("EQUITY_COLLAPSE_FEEDBACK_THROTTLE_SECONDS", "900"))

# Trainer-side enforcement: risk-off gating.
ENABLE_RISK_OFF_ON_OUTCOME_EVENTS = os.getenv("ENABLE_RISK_OFF_ON_OUTCOME_EVENTS", "true").lower() in ("1", "true", "yes")
RISK_OFF_ON_LOSS_EXIT_TTL_SECONDS = int(os.getenv("RISK_OFF_ON_LOSS_EXIT_TTL_SECONDS", "900"))
RISK_OFF_ON_EQUITY_COLLAPSE_TTL_SECONDS = int(os.getenv("RISK_OFF_ON_EQUITY_COLLAPSE_TTL_SECONDS", "86400"))

# Categories to block while risk-off is active (comma-separated).
RISK_OFF_BLOCK_CATEGORIES_DEFAULT = os.getenv("RISK_OFF_BLOCK_CATEGORIES_DEFAULT", "OPEN_RISK")

# ==========================================================================
# PROFIT-FUNDED LOSS TRIM (Reduce-only, trainer-driven)
# ==========================================================================
# When traders publish PROFIT_EXIT outcomes to `wma:trader:execution_feedback`,
# the trainer can optionally emit bounded PROTECTIVE PARTIAL_CLOSE actions on
# losing legs (same-symbol preferred; cross-symbol optional).
#
# Safety:
# - default OFF (fail-closed)
# - never opens exposure (reduce-only)
# - hard rate limits per account/time bucket

ENABLE_PROFIT_FUNDED_TRIM = os.getenv("ENABLE_PROFIT_FUNDED_TRIM", "false").lower() in ("true", "1", "yes")
PROFIT_TRIM_MIN_EVENT_CONF = float(os.getenv("PROFIT_TRIM_MIN_EVENT_CONF", "0.85"))
PROFIT_TRIM_ALLOW_CROSS_SYMBOL = os.getenv("PROFIT_TRIM_ALLOW_CROSS_SYMBOL", "false").lower() in ("true", "1", "yes")
PROFIT_TRIM_ALLOW_TRIM_HEDGED_PAIRS = os.getenv("PROFIT_TRIM_ALLOW_TRIM_HEDGED_PAIRS", "false").lower() in ("true", "1", "yes")
PROFIT_TRIM_MIN_CREDIT_USD = float(os.getenv("PROFIT_TRIM_MIN_CREDIT_USD", "10"))
PROFIT_TRIM_MIN_LOSS_USD = float(os.getenv("PROFIT_TRIM_MIN_LOSS_USD", "25"))
PROFIT_TRIM_MIN_ROE_PCT = float(os.getenv("PROFIT_TRIM_MIN_ROE_PCT", "-100"))
PROFIT_TRIM_MAX_TRIMS_PER_BUCKET = int(os.getenv("PROFIT_TRIM_MAX_TRIMS_PER_BUCKET", "1"))
PROFIT_TRIM_MAX_CREDIT_USE_USD = float(os.getenv("PROFIT_TRIM_MAX_CREDIT_USE_USD", "100"))
PROFIT_TRIM_MAX_CLOSE_FRACTION = float(os.getenv("PROFIT_TRIM_MAX_CLOSE_FRACTION", "0.50"))

# Adjustment Actions (Production TA Section 6 - disabled by default for gradual rollout)
# Set to True to enable granular position adjustment actions (ADJUST_LONG/SHORT/LEVERAGE)
ENABLE_ADJUSTMENT_ACTIONS = False      # ⚠️ Feature flag for safe rollout - new action types 7-10

# MASA / PPO blend (50/50 balanced - PPO is actively learning, MASA provides second opinion)
# When PPO matures, can increase MASA_WEIGHT if MASA proves calibrated
MASA_ENABLED = True
MASA_WEIGHT = 0.50  # Balanced: equal weight until PPO is fully trained (was 0.80)
MASA_UPDATE_FREQ = 1000

# ============================================================================
# SAFE MODE EXIT POLICY (Prevents stuck forever on checkpoint load failure)
# ============================================================================
# After checkpoint load failure, trainer enters SAFE_MODE
# Auto-exit safe mode after warmup if shapes stable and training progressing
SAFE_MODE_MAX_SECONDS = int(os.getenv("SAFE_MODE_MAX_SECONDS", "900"))  # 15 min max
SAFE_MODE_MAX_LOOPS = int(os.getenv("SAFE_MODE_MAX_LOOPS", "300"))  # Or 300 training loops

# ============================================================================
# PHASE 6: MICROSTRUCTURE EXECUTION GATE (5m timing approval)
# ============================================================================
# Final gate before signal publication: approve/delay/reduce based on 5m microstructure
# Decisions: PASS (full size) | DELAY (skip this cycle) | SIZE_REDUCE (reduce notional)
EXEC_GATE_ENABLED = os.getenv("EXEC_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
EXEC_GATE_DELAY_SECONDS = int(os.getenv("EXEC_GATE_DELAY_SECONDS", "120"))  # Re-evaluate after delay
EXEC_GATE_SIZE_REDUCE_FACTOR = float(os.getenv("EXEC_GATE_SIZE_REDUCE_FACTOR", "0.5"))  # 50% size when reducing
EXEC_GATE_DYNAMIC_ENABLED = os.getenv("EXEC_GATE_DYNAMIC_ENABLED", "true").lower() in ("1", "true", "yes")
EXEC_GATE_MIN_SOURCE_COUNT = int(os.getenv("EXEC_GATE_MIN_SOURCE_COUNT", "2"))
EXEC_GATE_RISK_DELAY_THRESHOLD = float(os.getenv("EXEC_GATE_RISK_DELAY_THRESHOLD", "0.82"))
EXEC_GATE_RISK_SIZE_REDUCE_THRESHOLD = float(os.getenv("EXEC_GATE_RISK_SIZE_REDUCE_THRESHOLD", "0.58"))
EXEC_GATE_MAX_FALSE_MOVE = float(os.getenv("EXEC_GATE_MAX_FALSE_MOVE", "0.65"))
EXEC_GATE_MIN_QUALITY = float(os.getenv("EXEC_GATE_MIN_QUALITY", "0.35"))
EXEC_GATE_MAX_LIQ_IMBALANCE = float(os.getenv("EXEC_GATE_MAX_LIQ_IMBALANCE", "0.75"))

# Microstructure thresholds for execution gate decisions
EXEC_GATE_MAX_SPREAD_PCT = float(os.getenv("EXEC_GATE_MAX_SPREAD_PCT", "0.03"))  # 3% spread limit
EXEC_GATE_MAX_FAST_MOVE = float(os.getenv("EXEC_GATE_MAX_FAST_MOVE", "0.7"))  # Fast move score limit (SIZE_REDUCE)
EXEC_GATE_MAX_SPOOF = float(os.getenv("EXEC_GATE_MAX_SPOOF", "0.6"))  # Spoof score limit (DELAY)

# Fail-open vs fail-closed when microstructure data is unavailable
# PASS = fail-open (allow signals through when no msnap data)
# DELAY = fail-closed (block signals when no msnap data) — requires CoinAPI WSDS running
EXEC_GATE_NO_DATA_ACTION = os.getenv("EXEC_GATE_NO_DATA_ACTION", "DELAY").upper()  # PASS or DELAY

# Virtual equity floor for signal sizing: when account equity is below this,
# use this minimum for sizing calculations so signals still publish.
# Traders independently decide whether to execute based on their own equity.
# Set to 0 to disable (strict equity gating).
MIN_SIGNAL_EQUITY_USD = float(os.getenv("MIN_SIGNAL_EQUITY_USD", "100.0"))

# FIX-RCA-4: Maximum staleness (seconds) for equity fallback.
# When portfolio:equity key is stale, trainer degrades equity proportionally
# to age. At EQUITY_STALE_MAX_SEC, equity is halved. Beyond that, blocked.
EQUITY_STALE_MAX_SEC = float(os.getenv("EQUITY_STALE_MAX_SEC", "180.0"))

# TF-specific gate enforcement:
# - OPEN_RISK: Subject to full microstructure gate (PASS/DELAY/SIZE_REDUCE)
# - HEDGE: Bypass health check but subject to spoof/fast-move (allows risk-reducing in bad conditions)
# - PROTECTIVE: Always allowed (1m only, never blocked by microstructure)

# ============================================================================
# LIQUIDATION PREVENTION & EXECUTION CONSTRAINT FEEDBACK (1st Feb 2026)
# ============================================================================
# Component 1: Trader Execution Feedback Instrumentation
ENABLE_EXECUTION_EVENT_PUBLISHING = os.getenv("ENABLE_EXECUTION_EVENT_PUBLISHING", "true").lower() in ("1", "true", "yes")
EXECUTION_FEEDBACK_STREAM = os.getenv("EXECUTION_FEEDBACK_STREAM", "wma:trader:execution_feedback")

# Orchestrator hard guards (impossible-order prevention + feedback-adaptive suppression)
ORCH_PRE_PUBLISH_FEASIBILITY_ENABLED = os.getenv("ORCH_PRE_PUBLISH_FEASIBILITY_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_PRE_PUBLISH_BLOCK_PROTECTIVE = os.getenv("ORCH_PRE_PUBLISH_BLOCK_PROTECTIVE", "false").lower() in ("1", "true", "yes")
ORCH_FEEDBACK_SUPPRESS_ENABLED = os.getenv("ORCH_FEEDBACK_SUPPRESS_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_FEEDBACK_SUPPRESS_TTL_SEC = int(os.getenv("ORCH_FEEDBACK_SUPPRESS_TTL_SEC", "300"))
ORCH_FEEDBACK_POLL_SEC = int(os.getenv("ORCH_FEEDBACK_POLL_SEC", "2"))
ORCH_FEEDBACK_READ_COUNT = int(os.getenv("ORCH_FEEDBACK_READ_COUNT", "100"))
ORCH_FEEDBACK_SUPPRESS_REASON_CODES = [
    p.strip().upper()
    for p in os.getenv(
        "ORCH_FEEDBACK_SUPPRESS_REASON_CODES",
        "MARGIN_CAP_BLOCK,HEDGE_PAIR_MARGIN_CAP_BLOCK,TRADER_FREE_MARGIN_BLOCK,FREE_MARGIN_BLOCK,INSUFFICIENT_MARGIN,INSUFFICIENT_MARGIN_2019,API_2019,NO_HEADROOM",
    ).split(",")
    if p.strip()
]

# Orchestrator fallback-on-block (de-risk response instead of silent drop)
ORCH_FALLBACK_ON_BLOCK_ENABLED = os.getenv("ORCH_FALLBACK_ON_BLOCK_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_FALLBACK_FORCE_HOLD_ON_EQUITY_ZERO = os.getenv("ORCH_FALLBACK_FORCE_HOLD_ON_EQUITY_ZERO", "true").lower() in ("1", "true", "yes")
ORCH_FALLBACK_CLOSE_FRACTION = float(os.getenv("ORCH_FALLBACK_CLOSE_FRACTION", "0.25"))

# Tier-2 (explicit names): deterministic fallback publication on orchestrator blocks
ORCH_FALLBACK_ENABLED = os.getenv("ORCH_FALLBACK_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_FALLBACK_ON_CODES = {
    p.strip().upper()
    for p in os.getenv(
        "ORCH_FALLBACK_ON_CODES",
        "ORCH_FEEDBACK_SUPPRESS_BLOCK,ORCH_IMPOSSIBLE_TRADE_MARGIN_CAP,ORCH_IMPOSSIBLE_TRADE_SYMBOL_CAP,ORCH_IMPOSSIBLE_TRADE_MARGIN_MISSING,ORCH_IMPOSSIBLE_TRADE_EQUITY_ZERO,MISSING_TF_CONTEXT,TF_TIMING_CONFLICT,REGIME_DUMP_LONG_BLOCK,LIQ_CONFLICT_LONG_VULN,LIQ_CONFLICT_SHORT_VULN",
    ).split(",")
    if p.strip()
}
# Entry-context hard gates (fail-closed for OPEN_RISK proposals lacking TF/liq context)
ORCH_CONTEXT_GATE_ENABLED = os.getenv("ORCH_CONTEXT_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_CONTEXT_GATE_REQUIRE_TF_FIELDS = os.getenv("ORCH_CONTEXT_GATE_REQUIRE_TF_FIELDS", "true").lower() in ("1", "true", "yes")
ORCH_CONTEXT_GATE_TF_CONFLICT_THRESHOLD = float(os.getenv("ORCH_CONTEXT_GATE_TF_CONFLICT_THRESHOLD", "0.70"))  # Raised from 0.55: GPSUSDT was constantly blocked at 0.667
ORCH_CONTEXT_GATE_REGIME_DUMP_ENABLED = os.getenv("ORCH_CONTEXT_GATE_REGIME_DUMP_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_CONTEXT_GATE_DUMP_RET_15M_PCT = float(os.getenv("ORCH_CONTEXT_GATE_DUMP_RET_15M_PCT", "-1.50"))
ORCH_CONTEXT_GATE_DUMP_RET_1H_PCT = float(os.getenv("ORCH_CONTEXT_GATE_DUMP_RET_1H_PCT", "-2.50"))
ORCH_CONTEXT_GATE_LIQ_COUPLING_ENABLED = os.getenv("ORCH_CONTEXT_GATE_LIQ_COUPLING_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_CONTEXT_GATE_LIQ_IMBALANCE_RATIO = float(os.getenv("ORCH_CONTEXT_GATE_LIQ_IMBALANCE_RATIO", "1.25"))
ORCH_CONTEXT_GATE_LIQ_MIN_STRENGTH = float(os.getenv("ORCH_CONTEXT_GATE_LIQ_MIN_STRENGTH", "1.0"))
# LIQ conflict 3rd condition: liq cluster must be within this many BPS of current price to fire.
# 0 = disabled (no proximity check). Set to e.g. 500 to prevent false positives when blobs are far.
ORCH_CONTEXT_GATE_LIQ_MAX_DIST_BPS = float(os.getenv("ORCH_CONTEXT_GATE_LIQ_MAX_DIST_BPS", "0.0"))

# Regime pump block (symmetric to dump block — blocks SHORT entries during strong pumps)
ORCH_CONTEXT_GATE_REGIME_PUMP_ENABLED = os.getenv("ORCH_CONTEXT_GATE_REGIME_PUMP_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_CONTEXT_GATE_PUMP_RET_15M_PCT = float(os.getenv("ORCH_CONTEXT_GATE_PUMP_RET_15M_PCT", "1.50"))
ORCH_CONTEXT_GATE_PUMP_RET_1H_PCT = float(os.getenv("ORCH_CONTEXT_GATE_PUMP_RET_1H_PCT", "2.50"))

# Microstructure instability veto — block OPEN_RISK entries during spoof/spread/sweep conditions
ORCH_MICROSTRUCTURE_VETO_ENABLED = os.getenv("ORCH_MICROSTRUCTURE_VETO_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_MICROSTRUCTURE_SPOOF_THRESHOLD = float(os.getenv("ORCH_MICROSTRUCTURE_SPOOF_THRESHOLD", "0.70"))  # depth_spoof_score threshold
ORCH_MICROSTRUCTURE_SPREAD_SPIKE_BPS = float(os.getenv("ORCH_MICROSTRUCTURE_SPREAD_SPIKE_BPS", "15.0"))  # spread threshold in bps
ORCH_MICROSTRUCTURE_MOVE_INTENSITY_THRESHOLD = float(os.getenv("ORCH_MICROSTRUCTURE_MOVE_INTENSITY_THRESHOLD", "0.80"))  # move_intensity threshold

# Confidence saturation detector — flag entries with saturated confidence as potentially miscalibrated
ORCH_CONFIDENCE_SATURATION_ENABLED = os.getenv("ORCH_CONFIDENCE_SATURATION_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_CONFIDENCE_SATURATION_THRESHOLD = float(os.getenv("ORCH_CONFIDENCE_SATURATION_THRESHOLD", "0.97"))  # above this → suspect
ORCH_CONFIDENCE_SATURATION_ACTION = os.getenv("ORCH_CONFIDENCE_SATURATION_ACTION", "FLAG").strip().upper() or "FLAG"  # FLAG or BLOCK

# Return field enrichment — enrich proposals with price returns from Redis feature store
ORCH_ENRICH_RETURNS_ENABLED = os.getenv("ORCH_ENRICH_RETURNS_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_ENRICH_MICROSTRUCTURE_ENABLED = os.getenv("ORCH_ENRICH_MICROSTRUCTURE_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_ENRICH_LIQ_STRENGTH_ENABLED = os.getenv("ORCH_ENRICH_LIQ_STRENGTH_ENABLED", "true").lower() in ("1", "true", "yes")

# ── Hedge Shock Manager ─ fast-move leg protection for hedged positions ──────
# Detects SHOCK regime (stress state + vol expansion) and manages hedge legs:
#   - Blocks entries adding to the losing side during shock
#   - Cuts losing leg earlier when move is persistent
#   - Locks profits on winning leg during retracement from peak
#   - One-leg-only rule, hysteresis, cooldowns, anti-churn
ORCH_HEDGE_SHOCK_ENABLED = os.getenv("ORCH_HEDGE_SHOCK_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_HEDGE_SHOCK_STRESS_TICKS_MIN = int(os.getenv("ORCH_HEDGE_SHOCK_STRESS_TICKS_MIN", "3"))  # hysteresis: N consecutive stress ticks before acting
ORCH_HEDGE_SHOCK_LOSER_ROE_THRESHOLD_PCT = float(os.getenv("ORCH_HEDGE_SHOCK_LOSER_ROE_THRESHOLD_PCT", "-5.0"))  # ROE% below which loser cut eligible
ORCH_HEDGE_SHOCK_LOSER_CUT_FRACTION = float(os.getenv("ORCH_HEDGE_SHOCK_LOSER_CUT_FRACTION", "0.15"))  # fraction of losing leg to close (conservative)
ORCH_HEDGE_SHOCK_LOSER_COOLDOWN_SEC = int(os.getenv("ORCH_HEDGE_SHOCK_LOSER_COOLDOWN_SEC", "180"))  # min seconds between loser cuts per symbol
ORCH_HEDGE_SHOCK_WINNER_MIN_ROE_PCT = float(os.getenv("ORCH_HEDGE_SHOCK_WINNER_MIN_ROE_PCT", "5.0"))  # min ROE% for winner lock eligibility
ORCH_HEDGE_SHOCK_WINNER_RETRACE_PCT = float(os.getenv("ORCH_HEDGE_SHOCK_WINNER_RETRACE_PCT", "50.0"))  # % retracement from peak ROE to trigger lock (deep)
ORCH_HEDGE_SHOCK_WINNER_LOCK_FRACTION = float(os.getenv("ORCH_HEDGE_SHOCK_WINNER_LOCK_FRACTION", "0.08"))  # fraction of winning leg to lock (rare protection)
ORCH_HEDGE_SHOCK_WINNER_COOLDOWN_SEC = int(os.getenv("ORCH_HEDGE_SHOCK_WINNER_COOLDOWN_SEC", "300"))  # min seconds between winner locks per symbol
ORCH_HEDGE_SHOCK_MAX_ACTIONS_HOURLY = int(os.getenv("ORCH_HEDGE_SHOCK_MAX_ACTIONS_HOURLY", "3"))  # anti-churn: max shock actions per symbol per hour
ORCH_HEDGE_SHOCK_ONE_LEG_ONLY = os.getenv("ORCH_HEDGE_SHOCK_ONE_LEG_ONLY", "true").lower() in ("1", "true", "yes")  # only act on one leg per cycle
ORCH_HEDGE_SHOCK_BLOCK_ADD_TO_LOSER = os.getenv("ORCH_HEDGE_SHOCK_BLOCK_ADD_TO_LOSER", "true").lower() in ("1", "true", "yes")  # block entries adding to losing side
# Pair-action gap: suppress winner-lock if a loser-cut happened within this window (prevents trim-both-legs bleed)
ORCH_HEDGE_SHOCK_PAIR_ACTION_GAP_SEC = int(os.getenv("ORCH_HEDGE_SHOCK_PAIR_ACTION_GAP_SEC", "300"))  # 5 min
# Margin-critical escalation: allow bigger loser cuts when margin utilization is critical
ORCH_HEDGE_SHOCK_MARGIN_CRIT_THRESHOLD = float(os.getenv("ORCH_HEDGE_SHOCK_MARGIN_CRIT_THRESHOLD", "0.93"))  # margin_util above this = critical
ORCH_HEDGE_SHOCK_MARGIN_CRIT_CUT_FRACTION = float(os.getenv("ORCH_HEDGE_SHOCK_MARGIN_CRIT_CUT_FRACTION", "0.35"))  # escalated cut fraction under critical margin
# Winner-lock margin+suppression guard: disable winner-lock when margin is stressed or feedback suppression is armed
ORCH_HEDGE_SHOCK_WINNER_LOCK_MARGIN_GATE = float(os.getenv("ORCH_HEDGE_SHOCK_WINNER_LOCK_MARGIN_GATE", "0.85"))  # margin_util >= this → winner-lock disabled (preserve cushion)
ORCH_HEDGE_SHOCK_WINNER_LOCK_SUPPRESS_GATE = os.getenv("ORCH_HEDGE_SHOCK_WINNER_LOCK_SUPPRESS_GATE", "true").lower() in ("1", "true", "yes")  # check feedback suppression armed → winner-lock disabled
# Loser-cut momentum guard: require real momentum (fast-move OR ROE worsening) before cutting loser, prevents slow-drift trims
ORCH_HEDGE_SHOCK_LOSER_CUT_REQUIRE_MOMENTUM = os.getenv("ORCH_HEDGE_SHOCK_LOSER_CUT_REQUIRE_MOMENTUM", "true").lower() in ("1", "true", "yes")
ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_FAST_MOVE = float(os.getenv("ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_FAST_MOVE", "0.50"))  # fast_move_score threshold confirming momentum against loser
ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_ROE_DELTA = float(os.getenv("ORCH_HEDGE_SHOCK_LOSER_CUT_MIN_ROE_DELTA", "-1.0"))  # loser ROE must have worsened by at least this much since last check
# Crash-escalation: aggressive loser cut during fast crashes (all 3 must be true → 35% cut)
ORCH_HEDGE_SHOCK_CRASH_ESCALATION_ENABLED = os.getenv("ORCH_HEDGE_SHOCK_CRASH_ESCALATION_ENABLED", "true").lower() in ("1", "true", "yes")
ORCH_HEDGE_SHOCK_CRASH_FAST_MOVE_MIN = float(os.getenv("ORCH_HEDGE_SHOCK_CRASH_FAST_MOVE_MIN", "0.70"))  # fast_move_score ≥ 0.7 = violent move
ORCH_HEDGE_SHOCK_CRASH_ROE_DELTA_MAX = float(os.getenv("ORCH_HEDGE_SHOCK_CRASH_ROE_DELTA_MAX", "-2.0"))  # loser ROE worsening ≤ -2% since last check
ORCH_HEDGE_SHOCK_CRASH_MARGIN_UTIL_MIN = float(os.getenv("ORCH_HEDGE_SHOCK_CRASH_MARGIN_UTIL_MIN", "0.50"))  # margin_util ≥ 50% = already stressed
ORCH_HEDGE_SHOCK_CRASH_CUT_FRACTION = float(os.getenv("ORCH_HEDGE_SHOCK_CRASH_CUT_FRACTION", "0.35"))  # emergency 35% cut of losing leg
# Winner-lock equity gate: disable winner-lock when equity is below micro-account threshold
ORCH_HEDGE_SHOCK_WINNER_LOCK_EQUITY_GATE = float(os.getenv("ORCH_HEDGE_SHOCK_WINNER_LOCK_EQUITY_GATE", "1500.0"))  # equity < this → winner-lock disabled (preserve asymmetry)
# Prepublish add-to-loser hard block (independent of shock eval, always active)
ORCH_PREPUBLISH_BLOCK_ADD_TO_LOSER = os.getenv("ORCH_PREPUBLISH_BLOCK_ADD_TO_LOSER", "false").lower() in ("1", "true", "yes")

# Source-side entry hygiene (fail-closed before proposal emission)
TRAINER_SOURCE_REQUIRE_CONTEXT_FOR_OPEN_RISK = os.getenv("TRAINER_SOURCE_REQUIRE_CONTEXT_FOR_OPEN_RISK", "true").lower() in ("1", "true", "yes")
TRAINER_SOURCE_REQUIRE_DECISION_ID_FOR_OPEN_RISK = os.getenv("TRAINER_SOURCE_REQUIRE_DECISION_ID_FOR_OPEN_RISK", "true").lower() in ("1", "true", "yes")
# NOTE: check both unprefixed (bias_dir) AND tf_-prefixed (tf_bias_dir) aliases
TRAINER_SOURCE_REQUIRED_TF_FIELDS = [
    p.strip()
    for p in os.getenv("TRAINER_SOURCE_REQUIRED_TF_FIELDS", "bias_dir,timing_dir,conflict_score,tf_votes").split(",")
    if p.strip()
]
TRAINER_SOURCE_TF_FIELD_ALIASES = {
    "bias_dir": ["bias_dir", "tf_bias_dir"],
    "timing_dir": ["timing_dir", "tf_timing_dir"],
    "conflict_score": ["conflict_score", "tf_conflict_score"],
    "tf_votes": ["tf_votes"],
}
TRAINER_SOURCE_REQUIRED_LIQ_FIELDS = [
    p.strip()
    for p in os.getenv("TRAINER_SOURCE_REQUIRED_LIQ_FIELDS", "liquidation_long_strength,liquidation_short_strength").split(",")
    if p.strip()
]
TRAINER_SOURCE_MISSING_CONTEXT_ACTION = os.getenv("TRAINER_SOURCE_MISSING_CONTEXT_ACTION", "HOLD").strip().upper() or "HOLD"

# Probe safety in observe/validation workflows (default fail-closed)
PROBE_ALLOW_OPEN_RISK = os.getenv("PROBE_ALLOW_OPEN_RISK", "false").lower() in ("1", "true", "yes")

# Confidence hygiene: avoid 100%/0% saturation in emitted proposals
TRAINER_CLAMP_PROPOSAL_CONFIDENCE = os.getenv("TRAINER_CLAMP_PROPOSAL_CONFIDENCE", "true").lower() in ("1", "true", "yes")
TRAINER_PROPOSAL_CONFIDENCE_MIN = float(os.getenv("TRAINER_PROPOSAL_CONFIDENCE_MIN", "0.01"))
TRAINER_PROPOSAL_CONFIDENCE_MAX = float(os.getenv("TRAINER_PROPOSAL_CONFIDENCE_MAX", "0.99"))
ORCH_FALLBACK_DEFAULT_ACTION = os.getenv("ORCH_FALLBACK_DEFAULT_ACTION", "HOLD").strip().upper() or "HOLD"
ORCH_FALLBACK_PREFERRED_DERISK_ACTIONS = [
    p.strip().upper()
    for p in os.getenv("ORCH_FALLBACK_PREFERRED_DERISK_ACTIONS", "PARTIAL_CLOSE,REDUCE_POSITION,CLOSE_POSITION").split(",")
    if p.strip()
]

# Tier-3: stale signal drop (trader-side)
TRADER_MAX_SIGNAL_AGE_MS = int(os.getenv("TRADER_MAX_SIGNAL_AGE_MS", "180000"))  # Raised from 60000: trainer sweep ~90s, need 3x buffer

# Component 2: Stress Tracker & Consumer
ENABLE_STRESS_TRACKER = os.getenv("ENABLE_STRESS_TRACKER", "true").lower() in ("1", "true", "yes")
STRESS_TRACKER_WINDOW_SECONDS = int(os.getenv("STRESS_TRACKER_WINDOW_SECONDS", "60"))  # Rolling window
STRESS_TRACKER_MARGIN_BLOCK_THRESHOLD = int(os.getenv("STRESS_TRACKER_MARGIN_BLOCK_THRESHOLD", "3"))  # N blocks in window → STRESS
STRESS_TRACKER_CIRCUIT_BREAKER_WINDOW = int(os.getenv("STRESS_TRACKER_CIRCUIT_BREAKER_WINDOW", "300"))  # 5m for CB events

# Component 3A: Trainer Gating (Portfolio Constraints)
ENABLE_TRAINER_STRESS_GATING = os.getenv("ENABLE_TRAINER_STRESS_GATING", "true").lower() in ("1", "true", "yes")
MIN_FREE_MARGIN_RATIO = float(os.getenv("MIN_FREE_MARGIN_RATIO", "0.35"))  # 35% equity as free margin
RESERVED_EXIT_USD = float(os.getenv("RESERVED_EXIT_USD", "250.0"))  # Minimum reserve for exits
RESERVED_EXIT_EQUITY_PCT = float(os.getenv("RESERVED_EXIT_EQUITY_PCT", "0.25"))  # 25% of equity or RESERVED_EXIT_USD

# Component 3B: Reward Integration & Terminal Conditions
ENABLE_FEEDBACK_FAILURE_PENALTIES = os.getenv("ENABLE_FEEDBACK_FAILURE_PENALTIES", "true").lower() in ("1", "true", "yes")
ENABLE_TERMINAL_ON_EQUITY_COLLAPSE = os.getenv("ENABLE_TERMINAL_ON_EQUITY_COLLAPSE", "true").lower() in ("1", "true", "yes")
ENABLE_PORTFOLIO_AWARE_REWARD = os.getenv("ENABLE_PORTFOLIO_AWARE_REWARD", "true").lower() in ("1", "true", "yes")

# Penalty magnitudes (tunable)
PENALTY_FREE_MARGIN_BLOCK = float(os.getenv("PENALTY_FREE_MARGIN_BLOCK", "-0.5"))  # Per blocked trade
PENALTY_MARGIN_CAP_BLOCK = float(os.getenv("PENALTY_MARGIN_CAP_BLOCK", "-0.3"))
PENALTY_INSUFFICIENT_MARGIN_2019 = float(os.getenv("PENALTY_INSUFFICIENT_MARGIN_2019", "-1.0"))  # API error
PENALTY_CIRCUIT_BREAKER = float(os.getenv("PENALTY_CIRCUIT_BREAKER", "-2.0"))  # Circuit breaker trip
PENALTY_EQUITY_COLLAPSE = float(os.getenv("PENALTY_EQUITY_COLLAPSE", "-50.0"))  # Terminal event

# Component 4: Post-Cascade Cooldown (Optional)
ENABLE_POST_CASCADE_COOLDOWN = os.getenv("ENABLE_POST_CASCADE_COOLDOWN", "true").lower() in ("1", "true", "yes")
POST_CASCADE_COOLDOWN_SECONDS = int(os.getenv("POST_CASCADE_COOLDOWN_SECONDS", "1800"))  # 30 min
POST_CASCADE_COOLDOWN_LIQ_BURST_THRESHOLD = int(os.getenv("POST_CASCADE_COOLDOWN_LIQ_BURST_THRESHOLD", "3"))  # 3 liqs → cooldown

# PR-07: Recovery Pocket (post-cascade controlled coin switching)
ENABLE_RECOVERY_POCKET = os.getenv("ENABLE_RECOVERY_POCKET", "false").lower() in ("1", "true", "yes")
RECOVERY_POCKET_MAX_MARGIN_USD = float(os.getenv("RECOVERY_POCKET_MAX_MARGIN_USD", "50.0"))
RECOVERY_POCKET_BLOCK_DCA = os.getenv("RECOVERY_POCKET_BLOCK_DCA", "true").lower() in ("1", "true", "yes")
RECOVERY_POCKET_BLOCK_HEDGES = os.getenv("RECOVERY_POCKET_BLOCK_HEDGES", "true").lower() in ("1", "true", "yes")
POST_CASCADE_REDIS_KEY_PREFIX = os.getenv("POST_CASCADE_REDIS_KEY_PREFIX", "wma:post_cascade")
RECOVERY_POCKET_RESERVE_KEY_PREFIX = os.getenv("RECOVERY_POCKET_RESERVE_KEY_PREFIX", "wma:recovery_pocket:reserve")

# Retro Liquidation Memory: Apply decaying penalty for known past liquidation events
ENABLE_RETRO_LIQUIDATION_PENALTY = os.getenv("ENABLE_RETRO_LIQUIDATION_PENALTY", "true").lower() in ("1", "true", "yes")
RETRO_LIQUIDATION_PENALTY_DECAY_STEPS = int(os.getenv("RETRO_LIQUIDATION_PENALTY_DECAY_STEPS", "10000"))  # Decay over 10K steps
RETRO_LIQUIDATION_PENALTY_INITIAL = float(os.getenv("RETRO_LIQUIDATION_PENALTY_INITIAL", "-5.0"))  # Initial penalty magnitude

# ============================================================================
# TRAINER HEARTBEAT (Proof of liveness for monitoring)
# ============================================================================
# Trainer publishes periodic heartbeat to Redis for health monitoring
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "15"))  # Publish every 15s
HEARTBEAT_TTL_SECONDS = int(os.getenv("HEARTBEAT_TTL_SECONDS", "60"))  # Key expires after 60s

# Continuous training
CONTINUOUS = True
LOOP_TIMESTEPS = int(os.getenv('LOOP_TIMESTEPS', '3000'))  # Env override or default 3K timesteps
# Model checkpoint save frequency (0 = disabled)
# Reduced default to minimize CUDA pickle failures during Phase 4-7 implementation
SAVE_EVERY_LOOPS = int(os.getenv('SAVE_EVERY_LOOPS', '200'))  # Default 200 loops (was 3)
DISABLE_MODEL_SAVES = os.getenv('DISABLE_MODEL_SAVES', 'false').lower() in ('true', '1')

# ============================================================================
# PHASE 7: PERFORMANCE TRACKING & CHURN METRICS
# ============================================================================
# Track 24h metrics for churn/fee reduction validation

PERF_TRACKING_ENABLED = os.getenv("PERF_TRACKING_ENABLED", "true").lower() in ("1", "true", "yes")
PERF_SUMMARY_INTERVAL_SECONDS = int(os.getenv("PERF_SUMMARY_INTERVAL_SECONDS", "3600"))  # 1 hour
PERF_CHURN_WINDOW_MINUTES = int(os.getenv("PERF_CHURN_WINDOW_MINUTES", "20"))  # Reopen within 20 min = churn

# === Performance Tuning (Prediction Loop & Training) ===
# Prediction loop interval: how often to run prediction cycles
# B1 LATENCY FIX: Reduced from 5s to 3s for faster signal generation
# Default: 3s in live mode (was 5s), 30s otherwise (can be overridden by env var)
PREDICTION_LOOP_SECONDS = float(os.getenv('PREDICTION_LOOP_SECONDS', '3'))  # 3s for low-latency live trading

# Post-training pause between training loops
# Default: 0s in live mode, 10s otherwise (original behavior for non-live)
POST_TRAINING_PAUSE_SECONDS = float(os.getenv('POST_TRAINING_PAUSE_SECONDS', '-1'))  # -1 = use mode-dependent default

# PPO Rollout Parameters (optional overrides, defaults to existing hardcoded values if not set)
# These allow GPU utilization tuning without code changes
# WARNING: Increasing n_envs increases Redis/feature load
RL_NUM_ENVS = int(os.getenv('RL_NUM_ENVS', '0')) if os.getenv('RL_NUM_ENVS') else None  # None = use default (2)
RL_N_STEPS = int(os.getenv('RL_N_STEPS', '0')) if os.getenv('RL_N_STEPS') else None     # None = use default (512)
RL_BATCH_SIZE = int(os.getenv('RL_BATCH_SIZE', '0')) if os.getenv('RL_BATCH_SIZE') else None  # None = use default (512)

# ============================================================================
# OBSERVATION DIMENSION CONTRACT (Pad/truncate to prevent shape errors)
# ============================================================================
# Enforces consistent observation vector dimensions across training/prediction
OBS_DIM_ENFORCEMENT_ENABLED = os.getenv("OBS_DIM_ENFORCEMENT_ENABLED", "true").lower() in ("1", "true", "yes")
OBS_DIM_LOG_RATE_LIMIT_SECONDS = int(os.getenv("OBS_DIM_LOG_RATE_LIMIT_SECONDS", "60"))  # Log mismatch once per 60s per symbol

# === Signals ===
PUBLISH_SIGNALS = True                  # master switch
SIGNAL_OUTPUT_STREAM = "signals:trading"  # ✅ UPDATED: Canonical stream (was wma:trainer:predictions)
SIGNAL_HEARTBEAT_STREAM = "signals:trainer:heartbeat"  # Heartbeat/control stream for trainer health
SIGNAL_STREAM_MAXLEN = 5000            # Redis XADD MAXLEN cap (approximate)
SIGNAL_PUBLISH_EVERY_N_STEPS = 5       # call publisher every N forward() invocations

# === Per-Account Stream Routing ===
# When enabled, trainer publishes to separate streams per account to prevent double execution
ENABLE_PER_ACCOUNT_STREAMS = os.getenv("ENABLE_PER_ACCOUNT_STREAMS", "true").lower() in ("1", "true", "yes")

# Explicit account availability gates (cold-standby support)
ACCOUNT_PRIMARY_ENABLED = os.getenv("ACCOUNT_PRIMARY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ACCOUNT_ASJAD_ENABLED = os.getenv("ACCOUNT_ASJAD_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Optional second-level publish gate for asjad (can keep account enabled but suppress publish)
ACCOUNT_ASJAD_ALLOW_PUBLISH = os.getenv("ACCOUNT_ASJAD_ALLOW_PUBLISH", "false").lower() in ("1", "true", "yes", "on")
# Account readiness preflight policy
ACCOUNT_PREFLIGHT_MAX_AGE_S = int(os.getenv("ACCOUNT_PREFLIGHT_MAX_AGE_S", "30"))
ACCOUNT_PREFLIGHT_REQUIRED = os.getenv("ACCOUNT_PREFLIGHT_REQUIRED", "true").lower() in ("1", "true", "yes", "on")

TRADING_ACCOUNTS = ["primary", "asjad"]  # List of active trading accounts
# Optional runtime allowlist for OPEN_RISK publishing (comma-separated).
# If empty/unset, defaults to TRADING_ACCOUNTS.
_active_accounts_env = os.getenv("ACTIVE_TRADING_ACCOUNTS", "").strip()
if _active_accounts_env:
    ACTIVE_TRADING_ACCOUNTS = [s.strip() for s in _active_accounts_env.split(",") if s.strip()]
else:
    ACTIVE_TRADING_ACCOUNTS = list(TRADING_ACCOUNTS)

# Filter ACTIVE_TRADING_ACCOUNTS by explicit enable flags (safe default keeps primary live)
_account_enabled_map = {
    "primary": bool(ACCOUNT_PRIMARY_ENABLED),
    "asjad": bool(ACCOUNT_ASJAD_ENABLED),
}
ACTIVE_TRADING_ACCOUNTS = [
    aid for aid in ACTIVE_TRADING_ACCOUNTS if _account_enabled_map.get(str(aid).strip().lower(), True)
]
if not ACTIVE_TRADING_ACCOUNTS:
    ACTIVE_TRADING_ACCOUNTS = ["primary"]

# Trader execution compatibility switch:
# If hedge mode cannot be enabled (exchange/account constraints), allow one-way opens
# instead of dropping all entry actions with `hedge_mode_disabled`.
TRADER_ALLOW_ONEWAY_OPEN_FALLBACK = os.getenv("TRADER_ALLOW_ONEWAY_OPEN_FALLBACK", "true").lower() in ("1", "true", "yes", "on")

SIGNAL_STREAM_PER_ACCOUNT = {
    "primary": "signals:trading:primary",
    "asjad": "signals:trading:asjad",
}
# Default account if not specified (for backwards compatibility)
DEFAULT_TRADING_ACCOUNT = "primary"

# CRITICAL: Multi-account participation for model/trainer signals
# When enabled, trainer/model OPEN signals are published to EACH account individually (account-scoped sizing + caps).
# This prevents the system from effectively defaulting to primary for new exposure.
#
# Safety: position-derived producers (profit scanner / hedge builders / overlays) already stamp account_id and should
# NOT be broadcast cross-account.
BROADCAST_MODEL_SIGNALS_TO_ALL_ACCOUNTS = os.getenv("BROADCAST_MODEL_SIGNALS_TO_ALL_ACCOUNTS", "true").lower() in (
    "1",
    "true",
    "yes",
)

# If enabled, *OPEN* (new exposure) signals are broadcast to ALL accounts even if an upstream
# routing step already stamped a single account_id. This ensures "both accounts participate"
# and prevents the system from defaulting entries to primary-only.
#
# NOTE: We do NOT broadcast position-derived signals (profit scanner, hedge builder) because
# those are tied to existing per-account positions.
ENABLE_BROADCAST_OPEN_SIGNALS_TO_ALL_ACCOUNTS = os.getenv(
    "ENABLE_BROADCAST_OPEN_SIGNALS_TO_ALL_ACCOUNTS", "true"
).lower() in ("1", "true", "yes")

# Confidence filtering - defined above (lines 293-296)
# SIGNAL_CONFIDENCE_MIN, MIN_TRADING_CONFIDENCE — see module-level definitions
PUBLISH_SOURCE_TAG = "trainer"         # appears in payload["source"]

# === Optional safety gates (ON by default) ===
# These do NOT change baseline confidence thresholds; they constrain overrides and enforce a no-loss close policy
# when the exposure controller attempts FULL CLOSE signals.
ENABLE_OVERRIDE_CONF_GATE = os.getenv("ENABLE_OVERRIDE_CONF_GATE", "true").lower() in ("1", "true", "yes")
OVERRIDE_MIN_CONF = float(os.getenv("OVERRIDE_MIN_CONF", "0.92"))

ENABLE_NO_LOSS_GATING = os.getenv("ENABLE_NO_LOSS_GATING", "true").lower() in ("1", "true", "yes")  # FIX Apr 14: Re-enabled (was false)
TARGET_MIN_PROFIT_FOR_CLOSE = float(os.getenv("TARGET_MIN_PROFIT_FOR_CLOSE", "0.0"))

# === Price target / landing prediction (ON by default) ===
# Adds informational fields to trainer signals and per-TF prediction cache:
#   - price_target, price_target_pct, price_target_direction
# NOTE: Traders may optionally act on these fields, but execution remains backward-compatible.
ENABLE_PRICE_TARGET_PREDICTION = os.getenv("ENABLE_PRICE_TARGET_PREDICTION", "true").lower() in ("1", "true", "yes")
# Base multiplier applied to ATR-based expected move sizing (higher -> farther target)
PRICE_TARGET_ATR_MULTIPLIER = float(os.getenv("PRICE_TARGET_ATR_MULTIPLIER", "1.0"))
# Use PPO/MASA value-head outputs to scale price targets (set false to revert to pure ATR)
MODEL_BASED_PRICE_TARGET = os.getenv("MODEL_BASED_PRICE_TARGET", "true").lower() in ("1", "true", "yes")
# Blend weight: 0 = pure ATR scaling, 1 = full value-head scaling (0.5 recommended)
PRICE_TARGET_VALUE_WEIGHT = float(os.getenv("PRICE_TARGET_VALUE_WEIGHT", "0.5"))

# === Enhanced Observation & Multi-TF Context ===
# Canonical observation dimension: must match between training and prediction.
# Increased from 512 to 768 to accommodate cross-TF context features without truncation.
CANONICAL_OBS_DIM = int(os.getenv("CANONICAL_OBS_DIM", "768"))
# Inject summary features from other timeframes into each observation
ENABLE_CROSS_TF_FEATURES = os.getenv("ENABLE_CROSS_TF_FEATURES", "true").lower() in ("1", "true", "yes")
# Cross-TF feature fields to inject (key signals from each other TF)
CROSS_TF_SIGNAL_FIELDS = [
    "ccxt_close", "ccxt_volume", "ob_ob_imbalance", "funding_rate",
    "depth_fast_move_score", "depth_spoof_score", "depth_imbalance_5",
    "liquidation_long_distance_pct", "liquidation_short_distance_pct",
    "liquidation_long_strength", "liquidation_short_strength",
]

# === Return Prediction Head ===
# Auxiliary head on the policy network that predicts expected N-candle future return.
# Trained with supervised auxiliary loss alongside PPO; output used for price targets.
ENABLE_RETURN_PREDICTION = os.getenv("ENABLE_RETURN_PREDICTION", "true").lower() in ("1", "true", "yes")
RETURN_HEAD_AUX_WEIGHT = float(os.getenv("RETURN_HEAD_AUX_WEIGHT", "0.1"))

# === Feature Pruning: TA Indicator Whitelist ===
# Out of 91 TA indicator families (171 keys), keep only high-signal indicators.
# Redundant variants (RSI-14/21/28, ROC/ROCP/ROCR/ROCR100, 39 candlestick patterns) are dropped.
# This raises the signal-to-noise ratio from ~30% to ~70% in observation space.
ENABLE_TA_FEATURE_PRUNING = os.getenv("ENABLE_TA_FEATURE_PRUNING", "true").lower() in ("1", "true", "yes")
TA_FEATURE_WHITELIST_PREFIXES = [
    "RSI_14_",
    "MACD_12_26_9", "MACDhist_12_26_9", "MACDsignal_12_26_9",
    "ATR_14_",
    "EMA_10_", "EMA_50_",
    "SMA_20_", "SMA_200_",
    "ADX_14_",
    "OBV_",
    "STOCHRSI_14",
    "CCI_14_",
    "BOP_",
    "WILLR_14_",
    "NATR_14_",
    "AROON_down_14", "AROON_up_14",
    "TRIX_14_",
    "MOM_14_",
    "pressure",
    "HT_TRENDMODE",
    "PLUS_DI_14_", "MINUS_DI_14_",
    "ULTOSC_",
    "AD_",
    "CDLENGULFING", "CDLHAMMER", "CDLSHOOTINGSTAR", "CDLMORNINGSTAR", "CDLEVENINGSTAR",
]

# === Microstructure TF Aggregation ===
# Aggregate CoinAPI microstructure data into TF-aligned features
# ENABLED by default - provides execution timing signals to prevent bad entries
ENABLE_MICROSTRUCTURE_TF_AGG = os.getenv("ENABLE_MICROSTRUCTURE_TF_AGG", "true").lower() in ("1", "true", "yes")
ENABLE_MICROSTRUCTURE_FEATURES_IN_OBS = os.getenv("ENABLE_MICROSTRUCTURE_FEATURES_IN_OBS", "false").lower() in ("1", "true", "yes")
ENABLE_MICROSTRUCTURE_TF_MODIFIER = os.getenv("ENABLE_MICROSTRUCTURE_TF_MODIFIER", "true").lower() in ("1", "true", "yes")

# Microstructure modifier thresholds
MICRO_SPOOF_SCORE_REDUCE_THRESHOLD = float(os.getenv("MICRO_SPOOF_SCORE_REDUCE_THRESHOLD", "0.6"))  # Reduce size above this
MICRO_SPOOF_SCORE_BLOCK_THRESHOLD = float(os.getenv("MICRO_SPOOF_SCORE_BLOCK_THRESHOLD", "0.85"))  # Block entry above this
MICRO_FAST_MOVE_REDUCE_THRESHOLD = float(os.getenv("MICRO_FAST_MOVE_REDUCE_THRESHOLD", "0.7"))
MICRO_FAST_MOVE_BLOCK_THRESHOLD = float(os.getenv("MICRO_FAST_MOVE_BLOCK_THRESHOLD", "0.9"))
MICRO_SIZE_MULTIPLIER_MIN = float(os.getenv("MICRO_SIZE_MULTIPLIER_MIN", "0.3"))  # Minimum size multiplier when reducing

# === Proactive Microstructure (Multi-TF) ===
# Enables proactive signals: early exits, reversal detection, manipulation detection
# ENABLED by default - provides protective actions during market manipulation
ENABLE_MICROSTRUCTURE_PROACTIVE = os.getenv("ENABLE_MICROSTRUCTURE_PROACTIVE", "false").lower() in ("1", "true", "yes")

# Proactive thresholds
MICRO_PROACTIVE_SQUEEZE_PEAK_THRESHOLD = float(os.getenv("MICRO_PROACTIVE_SQUEEZE_PEAK_THRESHOLD", "0.7"))
MICRO_PROACTIVE_LIQ_BURST_WARNING_USD = float(os.getenv("MICRO_PROACTIVE_LIQ_BURST_WARNING_USD", "500000"))
MICRO_PROACTIVE_LIQ_DISTANCE_DANGER_PCT = float(os.getenv("MICRO_PROACTIVE_LIQ_DISTANCE_DANGER_PCT", "2.0"))
MICRO_PROACTIVE_PROFIT_LOCK_PCT = float(os.getenv("MICRO_PROACTIVE_PROFIT_LOCK_PCT", "2.0"))
MICRO_PROACTIVE_MOMENTUM_EXHAUSTION_ACCEL = float(os.getenv("MICRO_PROACTIVE_MOMENTUM_EXHAUSTION_ACCEL", "-0.2"))

# TF-specific proactive rules
MICRO_1M_PROTECTIVE_ONLY = os.getenv("MICRO_1M_PROTECTIVE_ONLY", "true").lower() in ("1", "true", "yes")  # 1m cannot open, only protect
MICRO_5M_PROACTIVE_ENABLED = os.getenv("MICRO_5M_PROACTIVE_ENABLED", "true").lower() in ("1", "true", "yes")  # 5m can be proactive
MICRO_1H_PROACTIVE_ENABLED = os.getenv("MICRO_1H_PROACTIVE_ENABLED", "true").lower() in ("1", "true", "yes")  # 1h can be proactive

# === Feature Vector Ordering / Normalization (Inference Safety) ===
# Redis hashes are inherently unordered. Any inference path that iterates over
# `hgetall(...).items()` will produce non-deterministic feature ordering.
#
# Modes:
# - "cached_sorted" (default): build a sorted key order once per obs-dim and reuse
# - "sorted": sort keys each call (deterministic but slightly slower)
# - "unordered": legacy behavior (NOT recommended; for emergency rollback only)
FEATURE_VECTOR_ORDERING_MODE = os.getenv("FEATURE_VECTOR_ORDERING_MODE", "cached_sorted").strip().lower()

# === Volatility Calculation ===
VOL_TF = "15m"                         # Timeframe for realized volatility calculation
VOL_LOOKBACK = 30                      # Number of bars for volatility lookback

# === Dynamic Symbol Selection (Confidence × Volatility) ===
# Goal: when multiple OPEN_RISK opportunities exist, prioritize the symbols with the
# best combination of model confidence + market volatility.
#
# This affects ordering (and optionally filtering) of OPEN_RISK signals in the trainer's
# deconfliction publish step. It does NOT affect PROTECTIVE/HEDGE signals.
DYNAMIC_SYMBOL_SELECTION_ENABLED = os.getenv("DYNAMIC_SYMBOL_SELECTION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# Modes:
# - "reorder": publish all OPEN_RISK signals but order them by score (best first)
# - "filter": publish only TOP_K OPEN_RISK signals (best first)
DYNAMIC_SYMBOL_SELECTION_MODE = os.getenv("DYNAMIC_SYMBOL_SELECTION_MODE", "reorder").strip().lower()
# If mode == "filter": keep only top K OPEN_RISK signals (0 disables filtering)
DYNAMIC_SYMBOL_SELECTION_TOP_K = int(os.getenv("DYNAMIC_SYMBOL_SELECTION_TOP_K", "0"))
# Score uses: score = confidence * (1 + VOL_WEIGHT * clamp(vol_pct / VOL_REF_PCT, 0..2))
DYNAMIC_SYMBOL_SELECTION_VOL_WEIGHT = float(os.getenv("DYNAMIC_SYMBOL_SELECTION_VOL_WEIGHT", "1.0"))
# Reference volatility (%) used to normalize vol_pct (e.g., 2.0% ≈ "high vol" for most majors)
DYNAMIC_SYMBOL_SELECTION_VOL_REF_PCT = float(os.getenv("DYNAMIC_SYMBOL_SELECTION_VOL_REF_PCT", "2.0"))

# ============================================================================
# ORCHESTRATOR (Single-Publisher Arbitration Layer) - Jan 2026
# ============================================================================
# Purpose:
# - Convert many independent "publishers" into "proposers"
# - Enforce trader-aligned feasibility checks at publish time (pair caps, mins, margin rules)
# - Choose ONE final action per (account, symbol) per cycle with a proof chain
#
# Modes:
# - off: orchestrator disabled (legacy behavior)
# - shadow: compute arbitration + feasibility, but do NOT change what gets published
# - publish: publish the orchestrator-selected/downsized actions
ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ORCHESTRATOR_MODE = os.getenv("ORCHESTRATOR_MODE", "publish").strip().lower()  # off|shadow|publish

# Phase-2 canary:
# - user requirement: canary should apply to ALL symbols (from symbol manager / config)
# - therefore canary should be done by account, not by symbol
# Default canary accounts: align with ACTIVE_TRADING_ACCOUNTS unless explicitly overridden.
_canary_env = os.getenv("ORCHESTRATOR_CANARY_ACCOUNTS", "").strip()
if _canary_env:
    ORCHESTRATOR_CANARY_ACCOUNTS = [s.strip() for s in _canary_env.split(",") if s.strip()]
else:
    ORCHESTRATOR_CANARY_ACCOUNTS = []

# Reversal override (mechanical snap protection) - defaults OFF for safety.
REVERSAL_OVERRIDE_ENABLED = os.getenv("REVERSAL_OVERRIDE_ENABLED", "false").lower() in ("1", "true", "yes")
REVERSAL_OVERRIDE_RET_60S_PCT = float(os.getenv("REVERSAL_OVERRIDE_RET_60S_PCT", "1.0"))
REVERSAL_OVERRIDE_RET_120S_PCT = float(os.getenv("REVERSAL_OVERRIDE_RET_120S_PCT", "2.0"))
REVERSAL_OVERRIDE_BUY_IMB_THRESHOLD = float(os.getenv("REVERSAL_OVERRIDE_BUY_IMB_THRESHOLD", "0.60"))
REVERSAL_OVERRIDE_OB_IMB_THRESHOLD = float(os.getenv("REVERSAL_OVERRIDE_OB_IMB_THRESHOLD", "0.60"))
REVERSAL_OVERRIDE_LIQ_MULT = float(os.getenv("REVERSAL_OVERRIDE_LIQ_MULT", "1.5"))
REVERSAL_OVERRIDE_TTL_SEC = int(os.getenv("REVERSAL_OVERRIDE_TTL_SEC", "90"))

# Optional symbol filter (empty => ALL active symbols).
# If set, orchestrator only applies to these symbols (useful for emergency isolation).
ORCHESTRATOR_CANARY_SYMBOLS = [s.strip().upper() for s in os.getenv("ORCHESTRATOR_CANARY_SYMBOLS", "").split(",") if s.strip()]

# Emit structured arbitration proofs to Redis for auditing.
ORCHESTRATOR_PROOF_STREAM = os.getenv("ORCHESTRATOR_PROOF_STREAM", "health:events")

# ============================================================================
# ORCHESTRATOR: Trader-Side Proposal Bus (Jan 2026)
# ============================================================================
# When enabled, trader-side systems (stealth stops, dynamic TP, trailing) emit proposals
# to Redis streams instead of directly acting/publishing to traders.
#
# NOTE: This is a *transport* toggle; it does not change no-loss rules.
ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED = os.getenv("ORCHESTRATOR_EXTERNAL_PROPOSALS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# Trainer-side modules can also emit proposals (instead of directly publishing to signals:trading:*).
# Safety:
# - Default OFF (legacy behavior unchanged).
# - When enabled, modules may emit proposals in shadow for analysis and/or in publish mode for execution.
ORCHESTRATOR_INTERNAL_PROPOSALS_ENABLED = os.getenv("ORCHESTRATOR_INTERNAL_PROPOSALS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# When true, trainer emits proposals even in shadow mode (for diffing); note: proposals are drained/acked by the trainer
# and are not replayed later. Keep OFF unless you actively want proposal stream monitoring.
ORCHESTRATOR_INTERNAL_PROPOSALS_SHADOW_EMIT = os.getenv("ORCHESTRATOR_INTERNAL_PROPOSALS_SHADOW_EMIT", "false").lower() in ("1", "true", "yes", "on")
# Comma-separated streams (empty => default set).
ORCHESTRATOR_PROPOSAL_STREAMS = [
    s.strip()
    for s in os.getenv(
        "ORCHESTRATOR_PROPOSAL_STREAMS",
        # Default list includes both trader-side and trainer-side proposal streams.
        # This is safe because proposals are only merged into arbitration when ORCHESTRATOR_MODE="publish".
        "proposals:stealth_stops,proposals:dynamic_tp,proposals:trailing_stop,"
        "proposals:urc,proposals:hedge_harvest,proposals:flash_hedge,proposals:adaptive_hedge_builder_v2",
    ).split(",")
    if s.strip()
]
ORCHESTRATOR_PROPOSAL_MAX_READ = int(os.getenv("ORCHESTRATOR_PROPOSAL_MAX_READ", "2000"))

# If enabled, route non-GPU hedge/protective publishers in HybridTrainer through the
# buffered publish pipeline (which includes orchestrator arbitration + governors),
# instead of direct single-signal publish calls.
# Default OFF for safety.
UNIFY_NON_GPU_PUBLISH_THROUGH_BUFFERED = os.getenv("UNIFY_NON_GPU_PUBLISH_THROUGH_BUFFERED", "true").lower() in ("1", "true", "yes", "on")

# ============================================================================
# ORCHESTRATOR WORKER (Jan 2026) - Single Publisher Architecture
# ============================================================================
# When enabled, the orchestrator worker is the ONLY component that publishes
# to signals:live:* streams. All modules emit proposals to wma:proposals.
# This ensures true single-publisher semantics with proper arbitration.
ORCHESTRATOR_WORKER_ENABLED = os.getenv("ORCHESTRATOR_WORKER_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Worker mode: "shadow" (log but don't publish) or "publish" (actual publishing)
# LIVE: switched to publish mode after successful shadow validation
ORCHESTRATOR_WORKER_MODE = os.getenv("ORCHESTRATOR_WORKER_MODE", "publish").strip().lower()
# Allow orchestrator to downsize proposals to ramp per-symbol caps instead of dropping.
RAMP_LIMIT_DOWNSIZE_ENABLED = os.getenv("RAMP_LIMIT_DOWNSIZE_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Unified proposal stream - all modules write here
ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM = os.getenv("ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM", "wma:proposals")

# Signal output streams (only orchestrator worker publishes here)
# Using signals:trading:* for backward compatibility with existing traders
ORCHESTRATOR_SIGNAL_STREAM_PRIMARY = os.getenv("ORCHESTRATOR_SIGNAL_STREAM_PRIMARY", "signals:trading:primary")
ORCHESTRATOR_SIGNAL_STREAM_ASJAD = os.getenv("ORCHESTRATOR_SIGNAL_STREAM_ASJAD", "signals:trading:asjad")

# Micro-window aggregation (ms) - proposals arriving within this window are co-arbitrated
ORCHESTRATOR_MICRO_WINDOW_MS = int(os.getenv("ORCHESTRATOR_MICRO_WINDOW_MS", "500"))

# Cooldown horizon (ms) - prevents conflicting actions for same (account, symbol) within this window
ORCHESTRATOR_COOLDOWN_HORIZON_MS = int(os.getenv("ORCHESTRATOR_COOLDOWN_HORIZON_MS", "15000"))

# Consumer group for proposal stream
ORCHESTRATOR_CONSUMER_GROUP = os.getenv("ORCHESTRATOR_CONSUMER_GROUP", "orchestrator_workers")

# Stream for forbidden direct publish attempts (audit trail)
ORCHESTRATOR_FORBIDDEN_PUBLISH_STREAM = os.getenv("ORCHESTRATOR_FORBIDDEN_PUBLISH_STREAM", "wma:forbidden_publishes")

# =========================================================================
# STREAM RETENTION MINIMUMS (PR-13)
# =========================================================================
STREAM_MAXLEN_PROPOSALS = int(os.getenv("STREAM_MAXLEN_PROPOSALS", "50000"))
STREAM_MAXLEN_SIGNALS = int(os.getenv("STREAM_MAXLEN_SIGNALS", "50000"))
STREAM_MAXLEN_EXEC_EVENTS = int(os.getenv("STREAM_MAXLEN_EXEC_EVENTS", "100000"))
STREAM_MAXLEN_ALERTS = int(os.getenv("STREAM_MAXLEN_ALERTS", "20000"))

# Backward compatibility: legacy variable used by GPU publishers
SIGNAL_STREAM_MAXLEN = int(os.getenv("SIGNAL_STREAM_MAXLEN", str(STREAM_MAXLEN_SIGNALS)))

# =========================================================================
# CANARY PIPELINE (PR-10)
# =========================================================================
ENABLE_CANARY_SIGNALS = os.getenv("ENABLE_CANARY_SIGNALS", "false").lower() in ("1", "true", "yes", "on")
CANARY_INTERVAL_SEC = int(os.getenv("CANARY_INTERVAL_SEC", "120"))
CANARY_ZERO_PUBLISH_CYCLES = int(os.getenv("CANARY_ZERO_PUBLISH_CYCLES", "5"))

# =========================================================================
# LIQUIDITY GATE BOUNDED SUPPRESSION (PR-11)
# =========================================================================
LIQUIDITY_GATE_MAX_BLOCKS = int(os.getenv("LIQUIDITY_GATE_MAX_BLOCKS", "5"))
LIQUIDITY_SOFT_BLOCK_ENABLED = os.getenv("LIQUIDITY_SOFT_BLOCK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
LIQUIDITY_SOFT_MAX_MARGIN_USD = float(os.getenv("LIQUIDITY_SOFT_MAX_MARGIN_USD", "5.0"))
LIQUIDITY_SOFT_MAX_POSITION_PCT = float(os.getenv("LIQUIDITY_SOFT_MAX_POSITION_PCT", "1.0"))
LIQUIDITY_BORDERLINE_SMALL_RELAX_ENABLED = os.getenv("LIQUIDITY_BORDERLINE_SMALL_RELAX_ENABLED", "false").lower() in ("1", "true", "yes", "on")
LIQUIDITY_BORDERLINE_SMALL_HARD_FLOOR_USD = float(os.getenv("LIQUIDITY_BORDERLINE_SMALL_HARD_FLOOR_USD", "6000"))

# =========================================================================
# STRUCTURAL REGIME (PR-14)
# =========================================================================
STRUCT_REGIME_DD5D_POST_CRASH = float(os.getenv("STRUCT_REGIME_DD5D_POST_CRASH", "-0.08"))
STRUCT_REGIME_DD10D_POST_CRASH = float(os.getenv("STRUCT_REGIME_DD10D_POST_CRASH", "-0.12"))
STRUCT_REGIME_DD10D_BEAR_DAMAGE = float(os.getenv("STRUCT_REGIME_DD10D_BEAR_DAMAGE", "-0.06"))
STRUCT_REGIME_DD5D_NORMAL_FLOOR = float(os.getenv("STRUCT_REGIME_DD5D_NORMAL_FLOOR", "-0.03"))
STRUCT_REGIME_DD5D_POST_CRASH_EXIT = float(os.getenv("STRUCT_REGIME_DD5D_POST_CRASH_EXIT", "-0.04"))
STRUCT_REGIME_DD10D_BEAR_DAMAGE_EXIT = float(os.getenv("STRUCT_REGIME_DD10D_BEAR_DAMAGE_EXIT", "-0.03"))

STRUCT_REGIME_RF_FAIL_MAX_DAYS = int(os.getenv("STRUCT_REGIME_RF_FAIL_MAX_DAYS", "10"))
STRUCT_REGIME_RF_RECLAIM_BARS = int(os.getenv("STRUCT_REGIME_RF_RECLAIM_BARS", "6"))  # 4h bars

STRUCT_REGIME_VR_CAPITULATION = float(os.getenv("STRUCT_REGIME_VR_CAPITULATION", "1.7"))
STRUCT_REGIME_CAPITULATION_R_MULT = float(os.getenv("STRUCT_REGIME_CAPITULATION_R_MULT", "2.0"))

STRUCT_REGIME_MIN_HOLD_CAPITULATION_SEC = int(os.getenv("STRUCT_REGIME_MIN_HOLD_CAPITULATION_SEC", str(6 * 3600)))
STRUCT_REGIME_MIN_HOLD_POST_CRASH_SEC = int(os.getenv("STRUCT_REGIME_MIN_HOLD_POST_CRASH_SEC", str(72 * 3600)))
STRUCT_REGIME_MIN_HOLD_BEAR_DAMAGE_SEC = int(os.getenv("STRUCT_REGIME_MIN_HOLD_BEAR_DAMAGE_SEC", str(5 * 24 * 3600)))
STRUCT_REGIME_MIN_HOLD_RECOVERY_SEC = int(os.getenv("STRUCT_REGIME_MIN_HOLD_RECOVERY_SEC", str(48 * 3600)))

STRUCT_REGIME_TREND_SLOPE_MIN = float(os.getenv("STRUCT_REGIME_TREND_SLOPE_MIN", "0.005"))
STRUCT_REGIME_RECOVERY_CONFIRM_DAYS = int(os.getenv("STRUCT_REGIME_RECOVERY_CONFIRM_DAYS", "2"))

# Risk gating policy by structural regime
STRUCT_REGIME_BLOCK_RISK_ADD = os.getenv("STRUCT_REGIME_BLOCK_RISK_ADD", "CAPITULATION").split(",")
STRUCT_REGIME_BEAR_DAMAGE_ALLOW_SHORTS = os.getenv("STRUCT_REGIME_BEAR_DAMAGE_ALLOW_SHORTS", "true").lower() in ("1", "true", "yes", "on")
STRUCT_REGIME_RECOVERY_MARGIN_CAP_PCT = float(os.getenv("STRUCT_REGIME_RECOVERY_MARGIN_CAP_PCT", "0.25"))

# =========================================================================
# ORCHESTRATOR LIVENESS ASSERTIONS (PR-12)
# =========================================================================
ORCH_LIVENESS_CHECK_SEC = int(os.getenv("ORCH_LIVENESS_CHECK_SEC", "30"))
ORCH_PENDING_STALL_MS = int(os.getenv("ORCH_PENDING_STALL_MS", "120000"))
ORCH_WATCHDOG_STALE_MS = int(os.getenv("ORCH_WATCHDOG_STALE_MS", "90000"))  # D3: trainer-side stale threshold

# =========================================================================
# HEDGE DIRECT-PUBLISH BYPASS (Operator override)
# =========================================================================
# Default behavior: hedge/protective signals should be arbitrated by the
# orchestrator worker.
#
# Operator requirement (Jan 27, 2026): do NOT block hedge signals; route through
# orchestrator unless confidence is very high, in which case allow direct publish
# to per-account trader streams.
#
# Kill switch provided via env var.
# Default changed to "false" (Feb 2026): all routes must go through orchestrator.
# Set HEDGE_DIRECT_PUBLISH_BYPASS_ENABLED=true to re-enable high-conf hedge bypass (break-glass).
HEDGE_DIRECT_PUBLISH_BYPASS_ENABLED = os.getenv("HEDGE_DIRECT_PUBLISH_BYPASS_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
HEDGE_DIRECT_PUBLISH_BYPASS_MIN_CONF = float(os.getenv("HEDGE_DIRECT_PUBLISH_BYPASS_MIN_CONF", "0.95"))

# ============================================================================
# EXECUTION AUTHORITY ENFORCEMENT (Feb 2026)
# Orchestrator is the single publication authority for all non-emergency actions.
# ============================================================================
# Stamp orch_approved=1 + orch_plan_sig on every orchestrator-published signal.
ORCH_EXEC_TOKEN_ENABLED = os.getenv("ORCH_EXEC_TOKEN_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Trader rejects signals without orch_approved=1 (kill switch: default OFF for safe rollout).
TRADER_REQUIRE_ORCH_APPROVAL = os.getenv("TRADER_REQUIRE_ORCH_APPROVAL", "false").lower() in ("1", "true", "yes", "on")
# How stale the orchestrator heartbeat must be (ms) before trader allows emergency bypass.
# Default 60 000 ms (60s) — if orch heartbeat is older than this the gate is considered down.
ORCH_HEARTBEAT_STALE_MS = int(os.getenv("ORCH_HEARTBEAT_STALE_MS", "60000"))

# Fast lane: PROTECTIVE/CLOSE_RISK proposals flush after ORCH_FASTLANE_WINDOW_MS (50ms)
# instead of the normal ORCH_MICRO_WINDOW_MS (500ms).
ORCH_FASTLANE_ENABLED = os.getenv("ORCH_FASTLANE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ORCH_FASTLANE_WINDOW_MS = int(os.getenv("ORCH_FASTLANE_WINDOW_MS", "50"))
ORCH_FASTLANE_CATEGORIES = set(os.getenv(
    "ORCH_FASTLANE_CATEGORIES",
    "PROTECTIVE,CLOSE_RISK,CLOSE_PROFIT,HEDGE_TRIM,RECOVERY"
).upper().split(","))

# Emergency bypass: a risk-reducing proposal may bypass orchestrator ONLY when:
#   (1) ORCH_EMERGENCY_BYPASS_ENABLED=true
#   (2) risk_reducing=True AND urgency=EMERGENCY (or liq_bps < threshold / mu > threshold)
#   (3) orchestrator heartbeat is stale (unavailable)
# It NEVER allows OPEN/INCREASE actions.
ORCH_EMERGENCY_BYPASS_ENABLED = os.getenv("ORCH_EMERGENCY_BYPASS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ORCH_EMERGENCY_BYPASS_ORCH_STALE_MS = int(os.getenv("ORCH_EMERGENCY_BYPASS_ORCH_STALE_MS", "5000"))  # orch heartbeat stale threshold
ORCH_EMERGENCY_BYPASS_LIQ_BPS = float(os.getenv("ORCH_EMERGENCY_BYPASS_LIQ_BPS", "100.0"))  # < 100 bps from liq = emergency
ORCH_EMERGENCY_BYPASS_MARGIN_UTIL = float(os.getenv("ORCH_EMERGENCY_BYPASS_MARGIN_UTIL", "0.90"))  # margin_util >= 90% = emergency

# Stealth stops execution mode: "direct" (legacy) or "propose_only" (route via orchestrator).
STEALTH_STOPS_MODE = os.getenv("STEALTH_STOPS_MODE", "direct").strip().lower()
# Stealth TP trainer deference: when True, TP execution checks trainer's latest prediction
# and defers if trainer has high-confidence signal to keep/add to the position.
STEALTH_TP_TRAINER_DEFERENCE = os.getenv("STEALTH_TP_TRAINER_DEFERENCE", "true").lower() in ("true", "1", "yes")

# ============================================================================
# HEDGE MANAGER v3 (Addendum v3) - Primary hedge decision surface
# ============================================================================
HEDGE_MANAGER_V3_ENABLED = os.getenv("HEDGE_MANAGER_V3_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HEDGE_MANAGER_V3_STREAM = os.getenv("HEDGE_MANAGER_V3_STREAM", "wma:hedge_manager:events")

# Decision trace telemetry (Addendum v3)
DECISION_TRACE_ENABLED = os.getenv("DECISION_TRACE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DECISION_TRACE_STREAM = os.getenv("DECISION_TRACE_STREAM", "wma:traces")

# ============================================================================
# HEDGE HARVEST ENGINE — profit-taking on green hedge legs (single source of truth)
# ============================================================================
ENABLE_HEDGE_HARVEST = os.getenv("ENABLE_HEDGE_HARVEST", "true").lower() in ("1", "true", "yes")
HEDGE_HARVEST_MIN_ROE_PCT = float(os.getenv("HEDGE_HARVEST_MIN_ROE_PCT", "5.0"))
HEDGE_HARVEST_MIN_OSCILLATION_PCT = float(os.getenv("HEDGE_HARVEST_MIN_OSCILLATION_PCT", "2.0"))
HEDGE_HARVEST_LOG_VERBOSE = os.getenv("HEDGE_HARVEST_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")

# ============================================================================
# NO-LOSS DEFAULT + OPTIONAL LOSS REALIZATION (Recovery Mode Only)
# ============================================================================
# Default: strict no-loss and no stop-loss closure.
# Optional: allow loss realization ONLY when explicitly enabled AND marked as recovery-mode,
# preferably funded by realized profits (profit bank) elsewhere.
LOSS_REALIZATION_MODE_ENABLED = os.getenv("LOSS_REALIZATION_MODE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
# Optional runtime override key (set to "1" to enable without restart):
LOSS_REALIZATION_MODE_REDIS_KEY_PREFIX = os.getenv("LOSS_REALIZATION_MODE_REDIS_KEY_PREFIX", "risk:loss_realization_enabled")

# === Position Tracking ===
POSITIONS_HASH_PREFIX = "positions"    # Redis hash prefix for position tracking: positions:{env}:{symbol}
ENV_MODE = None                        # Will be set to TRADE_MODE value

# Mode – set via .env (live-only)

@dataclass
class LiveConfig:
    """Centralized configuration for live trading system"""
    # Asset universe and data settings
    SYMBOLS: List[str]
    TIMEFRAMES: List[str]
    REQUIRED_FAMILIES: List[str]
    
    # Trading thresholds and modes
    MIN_TRADING_CONFIDENCE: float
    MIN_CLOSE_CONFIDENCE: float  # Lower threshold for CLOSE/risk management actions
    MIN_FLIP_CONFIDENCE: float  # NEW: Higher threshold for flips
    MAX_LEVERAGE: int
    BASE_NOTIONAL: float
    MAX_POSITION_VALUE: float
    PPO_CONF_THRESHOLD: float
    ENSEMBLE_CONF_THRESHOLD: float
    
    # Multi-Signal Quality Scoring (OPTIONAL)
    ENABLE_SIGNAL_QUALITY_FILTER: bool
    MINIMUM_SIGNAL_QUALITY_SCORE: float
    TRADE_MODE: str

    # Regime computation / policy toggles
    # NOTE: Several runtime modules (trainer/orchestrator/stops) query these via `self.main_config`.
    # If they are missing from LiveConfig, those modules silently fall back to defaults (often OFF),
    # causing regime keys like `regime:{symbol}` to never be computed/published.
    REGIME_LAYER_ENABLED: bool
    REGIME_POLICY_ENABLED: bool
    
    # Signal Deconfliction (Production TA Section 1)
    ENABLE_SIGNAL_DECONFLICTION: bool
    TELEGRAM_ENABLED: bool
    TELEGRAM_SIGNAL_MIN_CONFIDENCE: float
    TELEGRAM_SIGNAL_THRESHOLD: float
    TRADING_EXEC_THRESHOLD: float
    
    # GPU Optimization (Production TA Section 3)
    ENABLE_GPU_BATCH_INFERENCE: bool
    GPU_BATCH_SIZE: int
    
    # Canary/Heartbeat Publishing
    ENABLE_CANARY_PUBLISH: bool
    
    # Dynamic Leverage Cap (Production TA Section 4)
    ENABLE_DYNAMIC_LEVERAGE_CAP: bool
    
    # Execution Feedback Loop (Production TA Section 5)
    ENABLE_EXECUTION_FEEDBACK: bool

    # Execution Outcome Feedback + Risk-Off (loss / equity collapse)
    ENABLE_LOSS_EXIT_FEEDBACK: bool
    ENABLE_EQUITY_COLLAPSE_FEEDBACK: bool
    EQUITY_COLLAPSE_USD_THRESHOLD: float
    EQUITY_COLLAPSE_FEEDBACK_THROTTLE_SECONDS: int
    ENABLE_RISK_OFF_ON_OUTCOME_EVENTS: bool
    RISK_OFF_ON_LOSS_EXIT_TTL_SECONDS: int
    RISK_OFF_ON_EQUITY_COLLAPSE_TTL_SECONDS: int
    RISK_OFF_BLOCK_CATEGORIES_DEFAULT: str
    
    # Adjustment Actions (Production TA Section 6)
    ENABLE_ADJUSTMENT_ACTIONS: bool

    # Execution overlay scaffolding (disabled by default for compatibility)
    ENABLE_POSITION_CONTEXT: bool
    ENABLE_POSITION_CONTEXT_IN_OBS: bool  # P2: Append position context to observation tensor
    POSITION_CONTEXT_VECTOR_SIZE: int
    ENABLE_EXECUTION_OVERLAY: bool
    EXECUTION_OVERLAY_MODE: str
    ENABLE_PROTECTIVE_HEDGE: bool
    LEVERAGE_STATIC: bool
    ENABLE_EXECUTION_ATTRIBUTION: bool
    EXECUTION_ATTRIBUTION_STREAM: str
    
    # Dynamic leverage configuration
    SYMBOL_LEVERAGE_CONFIG: Dict[str, Dict[str, float]]
    
    # Portfolio allocation limits
    MAX_PORTFOLIO_ALLOCATION: float
    MAX_CONFIDENCE_ALLOCATION: float
    DYNAMIC_HEDGE_MODE: bool
    # Hedge-intent flip semantics (open opposite without forced close when hedge_intent=True)
    HEDGE_V2_ENABLED: bool
    
    # MASA / PPO blend knobs
    MASA_WEIGHT: float
    MASA_UPDATE_FREQ: int
    
    # Continuous training
    CONTINUOUS: bool
    LOOP_TIMESTEPS: int
    SAVE_EVERY_LOOPS: int
    
    # Signal publishing
    PUBLISH_SIGNALS: bool
    SIGNAL_OUTPUT_STREAM: str
    SIGNAL_HEARTBEAT_STREAM: str
    SIGNAL_STREAM_MAXLEN: int
    SIGNAL_PUBLISH_EVERY_N_STEPS: int
    SIGNAL_CONFIDENCE_MIN: float
    PUBLISH_SOURCE_TAG: str
    
    # Confidence thresholds (per action category)
    MIN_CONF_ENTRY: float
    MIN_CONF_EXIT: float
    MIN_CONF_HEDGE: float
    MIN_CONF_MANAGE: float
    
    # Volatility calculation
    VOL_TF: str
    VOL_LOOKBACK: int
    
    # Position tracking
    POSITIONS_HASH_PREFIX: str
    ENV_MODE: str
    
    # Feature pipeline toggles
    MASA_ENABLED: bool
    USE_GPU: bool
    FEATURE_BACKEND: str
    NORMALIZATION_ENABLED: bool
    NORMALIZATION_WINDOW: int
    
    # Ingestor Toggles
    BINANCE_ENABLED: bool
    TOKENMETRICS_ENABLED: bool
    COINANK_ENABLED: bool
    KUCOIN_ENABLED: bool
    ALPHAVANTAGE_ENABLED: bool
    
    # GPU and Performance Settings
    GPU_MODE: str
    RL_HIGH_THROUGHPUT: bool
    RL_FORCE_GPU_ONLY: bool
    RL_FEATURE_STRICT: bool
    
    # Attribution and Logging
    LOG_ATTRIB: bool
    LOG_TRADES: bool
    LOG_TRADE_SAMPLE_RATE: float
    
    # Risk Management
    MAX_POSITION_SIZE: float
    STOP_LOSS_PERCENT: float  
    TAKE_PROFIT_PERCENT: float
    POSITION_SIZE_PCT: float
    MAX_POSITION_SIZE_PCT: float
    
    # Device and Hardware Settings
    device: str
    
    # Redis key constants
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    REDIS_PASSWORD: str
    
    # API Configuration
    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str
    BINANCE_SECRET_KEY: str
    BINANCE_API_KEY_ASJAD: str
    BINANCE_API_SECRET_ASJAD: str
    BINANCE_FUT_API_KEY: str
    BINANCE_FUT_API_SECRET: str
    TOKENMETRICS_API_KEY: str
    TM_API_KEY: str
    TM_BASE_URL: str
    ALPHA_VANTAGE_API_KEY: str
    COINANK_API_KEY: str
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    PRIVATE_CHANNEL_ID: str
    PORTFOLIO_CHANNEL_ID: str
    TRADE_CHANNEL_ID: str
    AI_SIGNALS_CHANNEL_ID: str

    # Telegram icon media (local assets) - disabled by default for safety
    TELEGRAM_ENABLE_ICON_MEDIA: bool
    TELEGRAM_TRADE_ICON_MEDIA: bool
    TELEGRAM_PORTFOLIO_ICON_MEDIA: bool
    TELEGRAM_PORTFOLIO_ICON_MEDIA_MAX: int
    
    # Training/Execution settings
    EXECUTION_INTERVAL: int
    MIN_NONZERO_PCT: float
    OBS_VECTOR_SIZE: int
    LIVE_TRAINING_ENABLED: bool
    
    # Order book specific settings
    ORDERBOOK_MARKET: str
    
    # Data collection settings
    DATA_RETENTION_HOURS: int
    HEARTBEAT_INTERVAL: int

def get_live_config() -> LiveConfig:
    """
    Get centralized live trading configuration
    Loads from constants and environment overrides
    """
    return LiveConfig(
        # Single source of truth: module-level SYMBOLS/TIMEFRAMES above.
        # This keeps trainer + traders + ingestors in sync (critical for new listings).
        SYMBOLS=SYMBOLS[:],
        TIMEFRAMES=TIMEFRAMES[:],  # add "1d" if you want 6 TFs
        REQUIRED_FAMILIES=['ccxt', 'orderbook', 'coinank', 'indicators'],
        
        # Trading / risk knobs
        MIN_TRADING_CONFIDENCE=float(os.getenv('MIN_TRADING_CONFIDENCE', str(MIN_TRADING_CONFIDENCE))),
        MIN_CLOSE_CONFIDENCE=float(os.getenv('MIN_CLOSE_CONFIDENCE', str(MIN_CLOSE_CONFIDENCE))),
        MIN_FLIP_CONFIDENCE=float(os.getenv('MIN_FLIP_CONFIDENCE', str(MIN_FLIP_CONFIDENCE))),
        MAX_LEVERAGE=int(os.getenv('MAX_LEVERAGE', '100')),  # Max leverage for BTC/ETH (top-tier symbols)
        BASE_NOTIONAL=float(os.getenv('BASE_NOTIONAL', '500.0')),  # Doubled to $500 base size
        MAX_POSITION_VALUE=float(os.getenv('MAX_POSITION_VALUE', '5000.0')),  # Doubled to $5000
        
        # Multi-Signal Quality Scoring (OPTIONAL)
        ENABLE_SIGNAL_QUALITY_FILTER=os.getenv('ENABLE_SIGNAL_QUALITY_FILTER', 'false').lower() in ('true', '1', 'yes'),  # Disabled by default
        MINIMUM_SIGNAL_QUALITY_SCORE=float(os.getenv('MINIMUM_SIGNAL_QUALITY_SCORE', '75')),
        
        # Signal Deconfliction (Production TA Section 1) - Feature flag for gradual rollout
        ENABLE_SIGNAL_DECONFLICTION=os.getenv('ENABLE_SIGNAL_DECONFLICTION', 'true').lower() in ('true', '1', 'yes'),  # Enabled by default
        TELEGRAM_ENABLED=(os.getenv('TELEGRAM_ENABLED', '1').lower() in ['1', 'true', 'yes']),  # Enabled by default
        TELEGRAM_SIGNAL_MIN_CONFIDENCE=float(os.getenv('TELEGRAM_SIGNAL_MIN_CONFIDENCE', '0.85')),
        TELEGRAM_SIGNAL_THRESHOLD=float(os.getenv('TELEGRAM_SIGNAL_THRESHOLD', '0.85')),
        TRADING_EXEC_THRESHOLD=float(os.getenv('TRADING_EXEC_THRESHOLD', '0.75')),
        
        # GPU Optimization (Production TA Section 3) - Feature flag for gradual rollout
        ENABLE_GPU_BATCH_INFERENCE=os.getenv('ENABLE_GPU_BATCH_INFERENCE', 'true').lower() in ('true', '1', 'yes'),  # Enhanced: Enabled by default for RTX 5080
        GPU_BATCH_SIZE=int(os.getenv('GPU_BATCH_SIZE', '64')),  # INCREASED: Larger batches for RTX 5080 (80% GPU util)
        
        # Canary/Heartbeat Publishing - Disabled by default to prevent 0.5 confidence noise
        ENABLE_CANARY_PUBLISH=os.getenv('ENABLE_CANARY_PUBLISH', 'false').lower() in ('true', '1', 'yes'),  # Disabled by default
        
        # Dynamic Leverage Cap (Production TA Section 4) - Feature flag for gradual rollout
        ENABLE_DYNAMIC_LEVERAGE_CAP=os.getenv('ENABLE_DYNAMIC_LEVERAGE_CAP', 'false').lower() in ('true', '1', 'yes'),  # Disabled by default
        
        # Execution Feedback Loop (Production TA Section 5) - Feature flag for gradual rollout
        # Enabled by default so trader publishes execution feedback (latency/slippage) without needing env override
        ENABLE_EXECUTION_FEEDBACK=os.getenv('ENABLE_EXECUTION_FEEDBACK', 'true').lower() in ('true', '1', 'yes'),

        # Execution Outcome Feedback + Risk-Off
        ENABLE_LOSS_EXIT_FEEDBACK=os.getenv('ENABLE_LOSS_EXIT_FEEDBACK', 'true').lower() in ('true', '1', 'yes'),
        ENABLE_EQUITY_COLLAPSE_FEEDBACK=os.getenv('ENABLE_EQUITY_COLLAPSE_FEEDBACK', 'true').lower() in ('true', '1', 'yes'),
        EQUITY_COLLAPSE_USD_THRESHOLD=float(os.getenv('EQUITY_COLLAPSE_USD_THRESHOLD', '10.0')),
        EQUITY_COLLAPSE_FEEDBACK_THROTTLE_SECONDS=int(os.getenv('EQUITY_COLLAPSE_FEEDBACK_THROTTLE_SECONDS', '900')),
        ENABLE_RISK_OFF_ON_OUTCOME_EVENTS=os.getenv('ENABLE_RISK_OFF_ON_OUTCOME_EVENTS', 'true').lower() in ('true', '1', 'yes'),
        RISK_OFF_ON_LOSS_EXIT_TTL_SECONDS=int(os.getenv('RISK_OFF_ON_LOSS_EXIT_TTL_SECONDS', '900')),
        RISK_OFF_ON_EQUITY_COLLAPSE_TTL_SECONDS=int(os.getenv('RISK_OFF_ON_EQUITY_COLLAPSE_TTL_SECONDS', '86400')),
        RISK_OFF_BLOCK_CATEGORIES_DEFAULT=os.getenv('RISK_OFF_BLOCK_CATEGORIES_DEFAULT', 'OPEN_RISK'),
        
        # Adjustment Actions (Production TA Section 6) - Feature flag for gradual rollout
        ENABLE_ADJUSTMENT_ACTIONS=os.getenv('ENABLE_ADJUSTMENT_ACTIONS', 'false').lower() in ('true', '1', 'yes'),  # Disabled by default

        # Execution overlay + attribution (scaffolding defaults to off; live-only)
        ENABLE_POSITION_CONTEXT=os.getenv('ENABLE_POSITION_CONTEXT', 'false').lower() in ('true', '1', 'yes'),
        ENABLE_POSITION_CONTEXT_IN_OBS=os.getenv('ENABLE_POSITION_CONTEXT_IN_OBS', 'false').lower() in ('true', '1', 'yes'),  # P2: Append to obs tensor
        POSITION_CONTEXT_VECTOR_SIZE=int(os.getenv('POSITION_CONTEXT_VECTOR_SIZE', '10')),
        ENABLE_EXECUTION_OVERLAY=os.getenv('ENABLE_EXECUTION_OVERLAY', 'true').lower() in ('true', '1', 'yes'),
        EXECUTION_OVERLAY_MODE="live",
        ENABLE_PROTECTIVE_HEDGE=os.getenv('ENABLE_PROTECTIVE_HEDGE', 'false').lower() in ('true', '1', 'yes'),
        LEVERAGE_STATIC=os.getenv('LEVERAGE_STATIC', 'true').lower() in ('true', '1', 'yes'),  # FIX Apr 15: default TRUE — user mandate: never change leverage
        ENABLE_EXECUTION_ATTRIBUTION=os.getenv('ENABLE_EXECUTION_ATTRIBUTION', 'true').lower() in ('true', '1', 'yes'),
        EXECUTION_ATTRIBUTION_STREAM=os.getenv('EXECUTION_ATTRIBUTION_STREAM', 'trades:attribution'),
        
        # Dynamic leverage by symbol (RAISED — account at $2.6k, can handle proper leverage)
        SYMBOL_LEVERAGE_CONFIG={
            # Tier 1: BTC/ETH (50x-75x leverage — deep liquidity, tight spreads)
            "BTCUSDT": {"min_leverage": 50, "max_leverage": 75, "base_notional": 500.0},
            "ETHUSDT": {"min_leverage": 50, "max_leverage": 75, "base_notional": 400.0},
            
            # Tier 2: SOL (40x-50x leverage — top-5 coin, strong liquidity)
            "SOLUSDT": {"min_leverage": 40, "max_leverage": 50, "base_notional": 350.0},
            
            # Tier 3: Major alts — XRP, LTC, ASTER, DOGE, LINK (25x-50x leverage)
            # XRP/DOGE/LINK are top-10 coins with $1B+ daily volume — no reason for 10x
            "XRPUSDT": {"min_leverage": 25, "max_leverage": 50, "base_notional": 300.0},
            "LTCUSDT": {"min_leverage": 30, "max_leverage": 50, "base_notional": 300.0},
            "ASTERUSDT": {"min_leverage": 30, "max_leverage": 50, "base_notional": 250.0},
            "DOGEUSDT": {"min_leverage": 20, "max_leverage": 40, "base_notional": 250.0},
            "LINKUSDT": {"min_leverage": 20, "max_leverage": 40, "base_notional": 275.0},
            
            # Tier 4: Mid-cap alts (15x-30x leverage)
            "UNIUSDT": {"min_leverage": 15, "max_leverage": 30, "base_notional": 250.0},
            "1000SHIBUSDT": {"min_leverage": 15, "max_leverage": 30, "base_notional": 200.0},
            "WIFUSDT": {"min_leverage": 15, "max_leverage": 30, "base_notional": 200.0},
            "AVNTUSDT": {"min_leverage": 15, "max_leverage": 30, "base_notional": 200.0},
            "PIPPINUSDT": {"min_leverage": 15, "max_leverage": 30, "base_notional": 200.0},

            # Tier 5: Memecoins / high-volatility (10x-20x — still needs enough leverage to profit)
            "1000PEPEUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "1000BONKUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "1000FLOKIUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "FARTCOINUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},

            # Tier 4b: Recently added mid-cap alts (10x-25x)
            "HIGHUSDT": {"min_leverage": 10, "max_leverage": 25, "base_notional": 200.0},
            "ALICEUSDT": {"min_leverage": 10, "max_leverage": 25, "base_notional": 200.0},
            "RAVEUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "RIVERUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "PENGUUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "BARDUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "BANKUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
            "AUCTIONUSDT": {"min_leverage": 10, "max_leverage": 20, "base_notional": 150.0},
        },
        
        # Portfolio allocation limits
        MAX_PORTFOLIO_ALLOCATION=0.50,  # 50% max portfolio allocation (excluding profit compounding)
        MAX_CONFIDENCE_ALLOCATION=0.20,  # 20% allocation at 100% confidence level
        DYNAMIC_HEDGE_MODE=True,  # Always operate in dynamic hedge mode
        # CRITICAL: must be present in live config so traders can honor hedge_intent safely
        HEDGE_V2_ENABLED=os.getenv("HEDGE_V2_ENABLED", str(HEDGE_V2_ENABLED)).lower() in ("true", "1", "yes"),
        
        PPO_CONF_THRESHOLD=float(os.getenv('PPO_CONF_THRESHOLD', '0.6')),
        ENSEMBLE_CONF_THRESHOLD=float(os.getenv('ENSEMBLE_CONF_THRESHOLD', '0.7')),
        TRADE_MODE="live",

        # Regime layer/policy (must be present on LiveConfig for runtime getattr lookups)
        REGIME_LAYER_ENABLED=bool(REGIME_LAYER_ENABLED),
        REGIME_POLICY_ENABLED=bool(REGIME_POLICY_ENABLED),
        
        # MASA / PPO blend knobs - Optimized for low-frequency trading
        MASA_ENABLED=os.getenv('MASA_ENABLED', '1') == '1',
        # IMPORTANT: default to module-level constants (single source of truth), allow env overrides.
        MASA_WEIGHT=float(os.getenv('MASA_WEIGHT', str(MASA_WEIGHT))),
        MASA_UPDATE_FREQ=int(os.getenv('MASA_UPDATE_FREQ', str(MASA_UPDATE_FREQ))),
        
        # Continuous training - ULTRA-FAST for market adaptation
        CONTINUOUS=os.getenv('CONTINUOUS', '1') == '1',
        LOOP_TIMESTEPS=int(os.getenv('LOOP_TIMESTEPS', '3000')),  # Optimized: 3K timesteps for ultra-fast prediction windows
        SAVE_EVERY_LOOPS=SAVE_EVERY_LOOPS,  # Reference top-level constant (line 400, default 200)
        USE_GPU=os.getenv('USE_GPU', 'True').lower() == 'true',
        FEATURE_BACKEND=os.getenv('FEATURE_BACKEND', 'gpu_cupy'),
        NORMALIZATION_ENABLED=os.getenv('NORMALIZATION_ENABLED', 'True').lower() == 'true',
        NORMALIZATION_WINDOW=int(os.getenv('NORMALIZATION_WINDOW', '1000')),
        
        # Ingestor Toggles
        BINANCE_ENABLED=os.getenv('BINANCE_ENABLED', '1') == '1',
        # TokenMetrics is disabled by policy (do not use TokenMetrics-derived features/signals).
        TOKENMETRICS_ENABLED=False,
        COINANK_ENABLED=os.getenv('COINANK_ENABLED', '1') == '1',
        KUCOIN_ENABLED=os.getenv('KUCOIN_ENABLED', '1') == '1',
        ALPHAVANTAGE_ENABLED=os.getenv('ALPHAVANTAGE_ENABLED', '1') == '1',
        
        # GPU and Performance Settings
        GPU_MODE=os.getenv('GPU_MODE', 'PERFORMANCE'),  # Enhanced: Performance mode for RTX 5080
        RL_HIGH_THROUGHPUT=os.getenv('RL_HIGH_THROUGHPUT', '1') == '1',
        RL_FORCE_GPU_ONLY=os.getenv('RL_FORCE_GPU_ONLY', '1') == '1',
        RL_FEATURE_STRICT=os.getenv('RL_FEATURE_STRICT', '1') == '1',
        
        # Attribution and Logging
        LOG_ATTRIB=os.getenv('LOG_ATTRIB', '1') == '1',
        LOG_TRADES=os.getenv('LOG_TRADES', '1') == '1',
        LOG_TRADE_SAMPLE_RATE=float(os.getenv('LOG_TRADE_SAMPLE_RATE', '1.0')),
        
        # Risk Management  
        # UPDATED 2025-12-28: Widened stops for high-leverage crypto trading
        # With 20-25x leverage, tight stops get hit by normal volatility
        MAX_POSITION_SIZE=float(os.getenv('MAX_POSITION_SIZE', '1000.0')),
        STOP_LOSS_PERCENT=float(os.getenv('STOP_LOSS_PERCENT', '6.0')),  # 6% price = 60% ROE with 10x leverage - gives room for volatility
        TAKE_PROFIT_PERCENT=float(os.getenv('TAKE_PROFIT_PERCENT', '8.0')),  # 8% price = 80% ROE profit - 1.33:1 R:R ratio
        POSITION_SIZE_PCT=float(os.getenv('POSITION_SIZE_PCT', '2.0')),
        MAX_POSITION_SIZE_PCT=float(os.getenv('MAX_POSITION_SIZE_PCT', '25.0')),
        
        # Redis settings
        REDIS_HOST=os.getenv('REDIS_HOST', 'localhost'),
        REDIS_PORT=int(os.getenv('REDIS_PORT', '6379')),
        REDIS_DB=int(os.getenv('REDIS_DB', '0')),
        REDIS_PASSWORD=os.getenv('REDIS_PASSWORD', ''),
        
        # API Configuration
        # Production API Keys
        BINANCE_API_KEY=os.getenv('BINANCE_API_KEY', ''),
        BINANCE_API_SECRET=os.getenv('BINANCE_API_SECRET', ''),
        BINANCE_SECRET_KEY=os.getenv('BINANCE_SECRET_KEY', ''),  # Legacy alias

        # Secondary (Asjad) account for multi-account portfolio tracking
        BINANCE_API_KEY_ASJAD=os.getenv('BINANCE_API_KEY_ASJAD', ''),
        BINANCE_API_SECRET_ASJAD=os.getenv('BINANCE_API_SECRET_ASJAD', ''),
        
        # Futures Production Keys (use same keys as spot trading)
        BINANCE_FUT_API_KEY=os.getenv('BINANCE_FUT_API_KEY', os.getenv('BINANCE_API_KEY', '')),
        BINANCE_FUT_API_SECRET=os.getenv('BINANCE_FUT_API_SECRET', os.getenv('BINANCE_API_SECRET', '')),
        
        TOKENMETRICS_API_KEY=os.getenv('TOKENMETRICS_API_KEY', 'demo_key_placeholder'),
        TM_API_KEY=os.getenv('TOKENMETRICS_API_KEY', 'demo_key_placeholder'),
        TM_BASE_URL=os.getenv('TOKENMETRICS_BASE_URL', 'https://api.tokenmetrics.com/v2'),
        ALPHA_VANTAGE_API_KEY=os.getenv('ALPHA_VANTAGE_API_KEY', ''),
        COINANK_API_KEY=os.getenv('COINANK_API_KEY', 'e2f14605c4d744658451b361939163f1'),
        TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN', '8230376700:AAEy6Jye2nE_FSHUmEhCg4Pu2bX_aSGsSsY'),
        TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID', '2101288870'),
        PRIVATE_CHANNEL_ID=os.getenv('PRIVATE_CHANNEL_ID', '-1003011988388'),
        
        # Specialized channel routing
        PORTFOLIO_CHANNEL_ID=os.getenv('PORTFOLIO_CHANNEL_ID', '@walirlbotportfolio'),
        TRADE_CHANNEL_ID=os.getenv('TRADE_CHANNEL_ID', '@walirlbottrader'),
        # Prefer TELEGRAM_AI_SIGNALS_CHANNEL_ID override; fallback to AI_SIGNALS_CHANNEL_ID
        AI_SIGNALS_CHANNEL_ID=os.getenv(
            'TELEGRAM_AI_SIGNALS_CHANNEL_ID',
            os.getenv('AI_SIGNALS_CHANNEL_ID', '-1003151176891')
        ),  # AI Signals channel

        # Telegram icon media attachments (safe defaults OFF)
        TELEGRAM_ENABLE_ICON_MEDIA=os.getenv('TELEGRAM_ENABLE_ICON_MEDIA', '0').lower() in ['1','true','yes'],
        TELEGRAM_TRADE_ICON_MEDIA=os.getenv('TELEGRAM_TRADE_ICON_MEDIA', '1').lower() in ['1','true','yes'],
        TELEGRAM_PORTFOLIO_ICON_MEDIA=os.getenv('TELEGRAM_PORTFOLIO_ICON_MEDIA', '1').lower() in ['1','true','yes'],
        TELEGRAM_PORTFOLIO_ICON_MEDIA_MAX=int(os.getenv('TELEGRAM_PORTFOLIO_ICON_MEDIA_MAX', '10')),
        
        # Training/Execution settings
        EXECUTION_INTERVAL=int(os.getenv('EXECUTION_INTERVAL', '100')),
        MIN_NONZERO_PCT=float(os.getenv('MIN_NONZERO_PCT', '0.25')),
        OBS_VECTOR_SIZE=int(os.getenv('OBS_VECTOR_SIZE', '520')),
        LIVE_TRAINING_ENABLED=os.getenv('LIVE_TRAINING_ENABLED', '0').lower() in ['1','true','yes'],
        
        # Order book specific settings
        # Use USDT-M market umbrella so all USDT pairs (13 symbols) stream
        ORDERBOOK_MARKET='USDT-M',
        
        # Data collection settings
        DATA_RETENTION_HOURS=24,
        HEARTBEAT_INTERVAL=30,
        
        # Signal publishing configuration
        PUBLISH_SIGNALS=os.getenv('PUBLISH_SIGNALS', '1') == '1',
        SIGNAL_OUTPUT_STREAM=os.getenv('SIGNAL_OUTPUT_STREAM', 'signals:trading'),  # ✅ Updated canonical stream
        SIGNAL_HEARTBEAT_STREAM=os.getenv('SIGNAL_HEARTBEAT_STREAM', 'signals:trainer:heartbeat'),
        SIGNAL_STREAM_MAXLEN=int(os.getenv('SIGNAL_STREAM_MAXLEN', '5000')),
        SIGNAL_PUBLISH_EVERY_N_STEPS=int(os.getenv('SIGNAL_PUBLISH_EVERY_N_STEPS', '5')),
        SIGNAL_CONFIDENCE_MIN=float(os.getenv('SIGNAL_CONFIDENCE_MIN', str(SIGNAL_CONFIDENCE_MIN))),
        PUBLISH_SOURCE_TAG=os.getenv('PUBLISH_SOURCE_TAG', 'trainer'),
        
        # Confidence thresholds (per action category) — use module-level values
        # (which already incorporate MIN_TRADING_CONFIDENCE binding)
        MIN_CONF_ENTRY=float(MIN_CONF_ENTRY),
        MIN_CONF_EXIT=float(MIN_CONF_EXIT),
        MIN_CONF_HEDGE=float(MIN_CONF_HEDGE),
        MIN_CONF_MANAGE=float(MIN_CONF_MANAGE),
        
        # Volatility calculation configuration
        VOL_TF=os.getenv('VOL_TF', '5m'),
        VOL_LOOKBACK=int(os.getenv('VOL_LOOKBACK', '30')),
        
        # Position tracking configuration
        POSITIONS_HASH_PREFIX=os.getenv('POSITIONS_HASH_PREFIX', 'positions'),
        ENV_MODE="live",
        
        # Device configuration for PyTorch - auto-detect GPU
        device=os.getenv('DEVICE', _get_default_device())
    )

# Legacy constants for backwards compatibility
config = get_live_config()
SYMBOLS = config.SYMBOLS
TIMEFRAMES = config.TIMEFRAMES
ORDERBOOK_MARKET = config.ORDERBOOK_MARKET
ORDERBOOK_SYMBOLS = config.SYMBOLS
REDIS_HOST = config.REDIS_HOST
REDIS_PORT = config.REDIS_PORT
REDIS_DB = config.REDIS_DB
REDIS_PASSWORD = config.REDIS_PASSWORD
BINANCE_API_KEY = config.BINANCE_API_KEY
BINANCE_API_SECRET = config.BINANCE_API_SECRET
BINANCE_SECRET_KEY = config.BINANCE_SECRET_KEY
BINANCE_FUT_API_KEY = config.BINANCE_FUT_API_KEY
BINANCE_FUT_API_SECRET = config.BINANCE_FUT_API_SECRET
TOKENMETRICS_API_KEY = config.TOKENMETRICS_API_KEY
TM_API_KEY = config.TM_API_KEY
TM_BASE_URL = config.TM_BASE_URL
ALPHA_VANTAGE_API_KEY = config.ALPHA_VANTAGE_API_KEY
COINANK_API_KEY = config.COINANK_API_KEY
TELEGRAM_BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = config.TELEGRAM_CHAT_ID
PRIVATE_CHANNEL_ID = config.PRIVATE_CHANNEL_ID
PORTFOLIO_CHANNEL_ID = config.PORTFOLIO_CHANNEL_ID
TRADE_CHANNEL_ID = config.TRADE_CHANNEL_ID
AI_SIGNALS_CHANNEL_ID = config.AI_SIGNALS_CHANNEL_ID
TELEGRAM_ENABLE_ICON_MEDIA = config.TELEGRAM_ENABLE_ICON_MEDIA
TELEGRAM_TRADE_ICON_MEDIA = config.TELEGRAM_TRADE_ICON_MEDIA
TELEGRAM_PORTFOLIO_ICON_MEDIA = config.TELEGRAM_PORTFOLIO_ICON_MEDIA
TELEGRAM_PORTFOLIO_ICON_MEDIA_MAX = config.TELEGRAM_PORTFOLIO_ICON_MEDIA_MAX
TRAINING_SYMBOLS = config.SYMBOLS
TRADE_MODE = config.TRADE_MODE
DATA_RETENTION_HOURS = config.DATA_RETENTION_HOURS
HEARTBEAT_INTERVAL = config.HEARTBEAT_INTERVAL
MAX_LEVERAGE = config.MAX_LEVERAGE
SYMBOL_LEVERAGE_CONFIG = config.SYMBOL_LEVERAGE_CONFIG
MAX_PORTFOLIO_ALLOCATION = config.MAX_PORTFOLIO_ALLOCATION
MAX_CONFIDENCE_ALLOCATION = config.MAX_CONFIDENCE_ALLOCATION
DYNAMIC_HEDGE_MODE = config.DYNAMIC_HEDGE_MODE

# ============================================================================
# FEATURE FLAGS - Phase 0 Implementation (System Modernization)
# ============================================================================
# These flags control new functionality while maintaining backward compatibility
# Default: True (enable new features), set to False to revert to legacy behavior

# ============================================================================
# FASTLANE 1M PROTECTIVE MODE (Intrabar Squeeze Detection)
# ============================================================================
# Enables the 1-minute timeframe to emit PROTECTIVE-ONLY signals when intrabar
# squeeze events are detected. This is NOT for opening new positions, only for:
# - Closing/reducing positions on adverse squeezes
# - Hedging open positions (if FASTLANE_ALLOW_HEDGE_OPEN=True)
#
# The FastLane system has 4 anti-spam gates:
# 1. Dedupe: Same event_id cannot trigger twice
# 2. Cooldown: Minimum seconds between emissions per symbol
# 3. Rate Limit: Max emissions per hour per symbol
# 4. Spread Check: Suppresses during wide spreads (illiquid conditions)

# AUDIT 12/30: Disabled - 1m protective fast-lane tends to create churn in noise
ENABLE_FASTLANE_1M_PROTECTIVE = os.getenv("ENABLE_FASTLANE_1M_PROTECTIVE", "false").lower() in ("true", "1")

# FastLane Thresholds
FASTLANE_COOLDOWN_SEC = int(os.getenv("FASTLANE_COOLDOWN_SEC", "45"))  # Min seconds between emissions per symbol
FASTLANE_RATE_LIMIT_PER_HOUR = int(os.getenv("FASTLANE_RATE_LIMIT_PER_HOUR", "20"))  # Max emissions/hour/symbol
FASTLANE_EXTREME_SEVERITY = float(os.getenv("FASTLANE_EXTREME_SEVERITY", "0.9"))  # Severity >= this = emergency close
FASTLANE_MIN_CONF_PROTECT = float(os.getenv("FASTLANE_MIN_CONF_PROTECT", "0.95"))  # Min confidence for protective action
FASTLANE_ALLOW_HEDGE_OPEN = os.getenv("FASTLANE_ALLOW_HEDGE_OPEN", "false").lower() in ("true", "1")  # Allow opening hedge positions
FASTLANE_MAX_HEDGE_PCT_EQUITY = float(os.getenv("FASTLANE_MAX_HEDGE_PCT_EQUITY", "0.005"))  # Max 0.5% equity per hedge

# Severity thresholds for different event types
FASTLANE_SQUEEZE_MIN_SEVERITY = float(os.getenv("FASTLANE_SQUEEZE_MIN_SEVERITY", "0.7"))  # Min severity for squeeze events
FASTLANE_LIQ_BURST_MIN_SEVERITY = float(os.getenv("FASTLANE_LIQ_BURST_MIN_SEVERITY", "0.7"))  # Min severity for liquidation bursts
FASTLANE_SPREAD_SHOCK_MIN_SEVERITY = float(os.getenv("FASTLANE_SPREAD_SHOCK_MIN_SEVERITY", "0.7"))  # Min severity for spread shocks

# ============================================================================

# Data Normalization (Phase 1)
# Canonical symbol mapping, timestamp standardization, schema normalization
ENABLE_NORMALIZATION = os.getenv("ENABLE_NORMALIZATION", "true").lower() == "true"

# Enhanced Failover (Phase 2)
# Health checks, retry logic, cached fallback for TokenMetrics & CoinAnk
ENABLE_ENHANCED_FAILOVER = os.getenv("ENABLE_ENHANCED_FAILOVER", "true").lower() == "true"

# New Checkpoint System (Phase 3)
# Metadata-based checkpoints in models/checkpoints/ with training state
ENABLE_NEW_CHECKPOINTS = os.getenv("ENABLE_NEW_CHECKPOINTS", "true").lower() == "true"

# Global Features Broadcasting (Phase 4)
# Broadcast global features (market metrics) to all symbol×TF combinations
ENABLE_GLOBAL_BROADCASTING = os.getenv("ENABLE_GLOBAL_BROADCASTING", "true").lower() == "true"

# Data Quality Validation (Phase 5)
# Schema validation, completeness checks, anomaly detection
ENABLE_DATA_VALIDATION = os.getenv("ENABLE_DATA_VALIDATION", "true").lower() == "true"

# ============================================================================
# AUDIT FIXES (December 24, 2025) - Feature Flags for Safe Rollout
# ============================================================================

# P0-1: Structured Decision Log - Emit detailed log line per signal publish
ENABLE_STRUCTURED_DECISION_LOG = os.getenv("ENABLE_STRUCTURED_DECISION_LOG", "true").lower() == "true"

# P0-3: Close Reason Tracking - Classify every close with reason code
ENABLE_CLOSE_REASON_TRACKING = os.getenv("ENABLE_CLOSE_REASON_TRACKING", "true").lower() == "true"

# P1-1: Hourly Trade Cap - Category-aware caps per symbol per hour
# PROTECTIVE actions are NEVER blocked by caps (exits must always go through)
# HEDGE actions have separate higher cap
# OPEN_RISK actions use standard cap
ENABLE_HOURLY_TRADE_CAP = os.getenv("ENABLE_HOURLY_TRADE_CAP", "true").lower() == "true"
# FIX: Derive from MAX_TRADES_PER_SYMBOL_PER_HOUR (single source of truth, shared with trainer)
# Previously TRADER_MAX_TRADES_PER_SYMBOL_PER_HOUR was a separate env var (.env set it to 30, defeating trainer's cap of 3)
TRADER_MAX_TRADES_PER_SYMBOL_PER_HOUR = int(os.getenv("TRADER_MAX_TRADES_PER_SYMBOL_PER_HOUR", str(MAX_TRADES_PER_SYMBOL_PER_HOUR)))  # Defaults to same as trainer cap
TRADER_MAX_HEDGES_PER_SYMBOL_PER_HOUR = int(os.getenv("TRADER_MAX_HEDGES_PER_SYMBOL_PER_HOUR", "30"))  # HEDGE cap (higher)
# PROTECTIVE: No cap (unlimited protective actions allowed)

# P2-1: Stop Reconciliation - Periodic sync of stealth stops vs exchange
ENABLE_STOP_RECONCILIATION = os.getenv("ENABLE_STOP_RECONCILIATION", "false").lower() == "true"
STOP_RECONCILIATION_INTERVAL_SEC = int(os.getenv("STOP_RECONCILIATION_INTERVAL_SEC", "300"))

# P2-2: Min Confidence Applied - Add min_conf_applied to payloads
ENABLE_MIN_CONF_APPLIED_FIELD = os.getenv("ENABLE_MIN_CONF_APPLIED_FIELD", "true").lower() == "true"

# Close Reason Codes (for ENABLE_CLOSE_REASON_TRACKING)
class CloseReasonCode:
    MODEL_CLOSE = "MODEL_CLOSE"           # Normal model-initiated close
    STOP_LOSS = "STOP_LOSS"               # Stop loss triggered
    TRAILING_STOP = "TRAILING_STOP"       # Trailing stop triggered
    TAKE_PROFIT = "TAKE_PROFIT"           # TP target hit
    TAKE_PROFIT_TIERED = "TAKE_PROFIT_TIERED"  # Tiered profit taking
    TAKE_PROFIT_DYNAMIC = "TAKE_PROFIT_DYNAMIC"  # Dynamic overlay profit taking
    PROFIT_LOCK_RETRACE = "PROFIT_LOCK_RETRACE"  # Lock profit on retracement
    TRAILING_PROTECT = "TRAILING_PROTECT"  # Trailing protection from overlay
    LOSS_HEDGE_TRIGGER_20PCT = "LOSS_HEDGE_TRIGGER_20PCT"  # -20% ROE hedge trigger
    PROFIT_HEDGE_TRIGGER_20PCT = "PROFIT_HEDGE_TRIGGER_20PCT"  # +20% ROE hedge trigger
    LIQUIDATION_HEDGE = "LIQUIDATION_HEDGE"    # Emergency hedge
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"   # Circuit breaker emergency
    REBALANCING = "REBALANCING"           # Portfolio rebalancing
    FLIP_CLOSE = "FLIP_CLOSE"             # Close leg of flip
    MANUAL_CLOSE = "MANUAL_CLOSE"         # Manual/external close
    STEALTH_STOP_LOSS = "STEALTH_STOP_LOSS"   # Stealth SL triggered
    STEALTH_TAKE_PROFIT = "STEALTH_TAKE_PROFIT"  # Stealth TP triggered

# Skip Reason Codes (for signal blocking telemetry)
class SkipReasonCode:
    ONE_MIN_FLAT_ENTRY_BLOCK = "ONE_MIN_FLAT_ENTRY_BLOCK"  # 1m cannot open new risk when flat
    PORTFOLIO_RESERVE_BLOCK = "PORTFOLIO_RESERVE_BLOCK"    # Reserve buffer requires high conf
    PORTFOLIO_SLOT_BLOCK = "PORTFOLIO_SLOT_BLOCK"          # Position slot limit reached
    PORTFOLIO_BUDGET_BLOCK = "PORTFOLIO_BUDGET_BLOCK"      # Budget limit reached
    OVERLAY_CHURN_BLOCK = "OVERLAY_CHURN_BLOCK"           # Anti-churn blocked overlay action
    OVERLAY_CANARY_BLOCK = "OVERLAY_CANARY_BLOCK"         # Not a canary symbol
    SAFE_MODE_BLOCK = "SAFE_MODE_BLOCK"                   # Safe mode active
    FEATURE_HEALTH_BLOCK = "FEATURE_HEALTH_BLOCK"         # Feature health failed

# ============================================================================
# PORTFOLIO POLICY MANAGER (Addendum A) - Position Slots, Budgets, Reserve
# ============================================================================
# Master switch for portfolio policy enforcement
# Jan6 governance: ON by default (can still be disabled via env if needed)
ENABLE_PORTFOLIO_POLICY = os.getenv("ENABLE_PORTFOLIO_POLICY", "true").lower() == "true"

# Position slot limits (Jan6: max 5 unique symbols per account for new openings)
PORTFOLIO_MAX_LONG_SLOTS = int(os.getenv("PORTFOLIO_MAX_LONG_SLOTS", "20"))
PORTFOLIO_MAX_SHORT_SLOTS = int(os.getenv("PORTFOLIO_MAX_SHORT_SLOTS", "20"))
PORTFOLIO_MAX_TOTAL_POSITIONS = int(os.getenv("PORTFOLIO_MAX_TOTAL_POSITIONS", "24"))

# Ultra-high confidence exception
# Operator requirement (Feb 2026):
# - Base symbol cap should be 10
# - Ultra-high confidence cap should be 20 (finite, not unlimited)
PORTFOLIO_ULTRA_CONF_THRESHOLD = float(os.getenv("PORTFOLIO_ULTRA_CONF_THRESHOLD", "0.90"))
PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS = int(os.getenv("PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS", "24"))  # 12 symbols * 2 sides in hedge

# Reserve buffer threshold (lowered from 0.90 to 0.80 per AI TA 12-25-2025)
# FIX 4: 0.90 was blocking 3/4 signals - now allows conf >= 0.80 to use reserve
# Operator can still override via env var for tighter control
PORTFOLIO_RESERVE_MIN_CONF = float(os.getenv("PORTFOLIO_RESERVE_MIN_CONF", "0.80"))
PORTFOLIO_BASE_MAX_POSITIONS = int(os.getenv("PORTFOLIO_BASE_MAX_POSITIONS", "12"))  # 12 unique symbols max
PORTFOLIO_RESERVE_MAX_POSITIONS = int(os.getenv("PORTFOLIO_RESERVE_MAX_POSITIONS", "12"))  # Aligned with base

# -------------------------------------------------------------------
# CRITICAL: Clamp portfolio caps upward to avoid legacy `.env` overrides
# -------------------------------------------------------------------
# Cursor environment blocks editing `.env` in this workspace. Since `.env` still
# contains older caps (7/12), `load_dotenv()` would silently override these
# code defaults and reintroduce PORTFOLIO_SLOT_BLOCK deadlocks.
#
# User requirement (Feb 2026):
# - normal max symbols: 10
# - ultra max symbols: 20 (when confidence >= PORTFOLIO_ULTRA_CONF_THRESHOLD)
#
# Operators can still increase beyond these via environment variables.
PORTFOLIO_BASE_MAX_POSITIONS = max(int(PORTFOLIO_BASE_MAX_POSITIONS), 12)
PORTFOLIO_RESERVE_MAX_POSITIONS = max(int(PORTFOLIO_RESERVE_MAX_POSITIONS), 12)
PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS = max(int(PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS), 24)

# Exposure budgets (as fraction of equity)
def _env_pct_fraction(name: str, default: str) -> float:
    """
    Read a percentage-like env var as a fraction.
    Accepts both styles:
    - "0.25" -> 0.25
    - "25" or "25.0" -> 0.25
    """
    raw = os.getenv(name, default)
    try:
        v = float(raw)
    except Exception:
        v = float(default)
    # Treat values > 1.0 as "percent" (25 => 25%) and convert to fraction.
    if v > 1.0:
        v = v / 100.0
    # Clamp to sane bounds
    if v < 0:
        v = 0.0
    return float(v)

# ============================================================================
# SINGLE SOURCE OF TRUTH: Portfolio Budget Settings
# ============================================================================
# All other budget/cap settings derive from these values.
PORTFOLIO_LONG_BUDGET_PCT = _env_pct_fraction("PORTFOLIO_LONG_BUDGET_PCT", "0.45")  # 45% of equity per LONG side
PORTFOLIO_SHORT_BUDGET_PCT = _env_pct_fraction("PORTFOLIO_SHORT_BUDGET_PCT", "0.45")  # 45% of equity per SHORT side
PORTFOLIO_RESERVE_PCT = _env_pct_fraction("PORTFOLIO_RESERVE_PCT", "0.05")  # 5% reserve for hedges/recovery (50% -> 55% max)

# High-confidence budget bonus: conf >= 0.90 gets extra 10% per side (30% -> 40%)
PORTFOLIO_HIGH_CONF_BUDGET_BONUS_PCT = _env_pct_fraction("PORTFOLIO_HIGH_CONF_BUDGET_BONUS_PCT", "0.10")  # +10% per side for 0.90+ conf
PORTFOLIO_HIGH_CONF_THRESHOLD = float(os.getenv("PORTFOLIO_HIGH_CONF_THRESHOLD", "0.90"))  # Threshold for budget bonus

# Total margin budget: derived from LONG + SHORT budgets
PORTFOLIO_NORMAL_MAX_MARGIN_PCT = PORTFOLIO_LONG_BUDGET_PCT + PORTFOLIO_SHORT_BUDGET_PCT  # 70% (35% + 35%)
PORTFOLIO_ULTRA_MAX_MARGIN_PCT = PORTFOLIO_NORMAL_MAX_MARGIN_PCT + PORTFOLIO_RESERVE_PCT  # 85% (70% + 15%)

# Equity staleness threshold for fail-closed behavior
PORTFOLIO_EQUITY_MAX_AGE_MS = int(os.getenv("PORTFOLIO_EQUITY_MAX_AGE_MS", "120000"))  # 2 min

# ============================================================================
# DERIVED BUDGET SETTINGS (backward compatibility aliases)
# ============================================================================
# These all derive from the PORTFOLIO_* settings above - DO NOT SET INDEPENDENTLY
PER_SIDE_CAP = max(PORTFOLIO_LONG_BUDGET_PCT, PORTFOLIO_SHORT_BUDGET_PCT)  # 35%
TOTAL_CAP = PORTFOLIO_NORMAL_MAX_MARGIN_PCT  # 70%
MAX_MARGIN_UTIL_LONG_PCT = PORTFOLIO_LONG_BUDGET_PCT * 100.0  # 35.0
MAX_MARGIN_UTIL_SHORT_PCT = PORTFOLIO_SHORT_BUDGET_PCT * 100.0  # 35.0
MAX_MARGIN_UTIL_TOTAL_PCT = PORTFOLIO_NORMAL_MAX_MARGIN_PCT * 100.0  # 70.0

# ============================================================================
# OBSERVATION SCHEMA & CHECKPOINT COMPATIBILITY
# ============================================================================
# Schema version to use (v1=1053, v2=1061, v3=1911). Auto-detect from checkpoint if not set.
OBS_SCHEMA_VERSION = os.getenv("OBS_SCHEMA_VERSION", "")  # Empty = auto-detect

# SAFE_MODE: Protective-only trading when checkpoint load fails or is incompatible
# ON by default - only deactivates after successful checkpoint load
SAFE_MODE_DEFAULT_ON = os.getenv("SAFE_MODE_DEFAULT_ON", "true").lower() == "true"
SAFE_MODE_ALLOW_OVERRIDE = os.getenv("SAFE_MODE_ALLOW_OVERRIDE", "false").lower() == "true"

# Checkpoint compatibility
CHECKPOINT_AUTO_DOWNGRADE = os.getenv("CHECKPOINT_AUTO_DOWNGRADE", "true").lower() == "true"
CHECKPOINT_STRICT_DIM_CHECK = os.getenv("CHECKPOINT_STRICT_DIM_CHECK", "true").lower() == "true"

# ============================================================================
# FEATURE HEALTH & FAIL-CLOSED GATING
# ============================================================================
# Enable strict feature health checks that block entries if features are stale/sparse
ENABLE_FEATURE_HEALTH_GATING = os.getenv("ENABLE_FEATURE_HEALTH_GATING", "true").lower() == "true"

# Minimum nonzero ratio (0.0-1.0) for feature vector to be considered healthy
FEATURE_HEALTH_MIN_NONZERO_RATIO = float(os.getenv("FEATURE_HEALTH_MIN_NONZERO_RATIO", "0.3"))

# Maximum staleness (ms) before features are considered stale
FEATURE_HEALTH_MAX_STALENESS_MS = int(os.getenv("FEATURE_HEALTH_MAX_STALENESS_MS", "30000"))

# Optional stale-aware nulling (CoinAnk OI / market order flow)
FEATURE_STALE_OI_MAX_AGE_MS = int(os.getenv("FEATURE_STALE_OI_MAX_AGE_MS", "60000"))
FEATURE_STALE_TRADES_MAX_AGE_MS = int(os.getenv("FEATURE_STALE_TRADES_MAX_AGE_MS", "30000"))
FEATURE_STALE_LOG_INTERVAL_SEC = int(os.getenv("FEATURE_STALE_LOG_INTERVAL_SEC", "60"))

# Minimum expected numeric features (below this, block entries)
FEATURE_HEALTH_MIN_NUMERIC_COUNT = int(os.getenv("FEATURE_HEALTH_MIN_NUMERIC_COUNT", "16"))

# ============================================================================
# LSTM/SEQUENCE WARM-START
# ============================================================================
# Enable prefilling sequence buffers from Redis on startup
ENABLE_WARM_START_PREFILL = os.getenv("ENABLE_WARM_START_PREFILL", "true").lower() == "true"

# Minimum sequence length before allowing actions (LSTM warmup threshold)
# Set to 15 to ensure LSTM has enough history for stable predictions
WARM_START_MIN_SEQ_LEN = int(os.getenv("WARM_START_MIN_SEQ_LEN", "15"))

# Maximum lookback for prefill (observations to load from Redis)
WARM_START_PREFILL_LOOKBACK = int(os.getenv("WARM_START_PREFILL_LOOKBACK", "20"))

# Redis key pattern for observation history
WARM_START_OBS_HISTORY_KEY = os.getenv("WARM_START_OBS_HISTORY_KEY", "obs_history:{symbol}:{tf}")

# ============================================================================
# DECISION FUNNEL LOGGING (Audit/Diagnostics)
# ============================================================================
# Master switch for decision funnel logging (default OFF)
ENABLE_DECISION_FUNNEL_LOG = os.getenv("ENABLE_DECISION_FUNNEL_LOG", "false").lower() == "true"

# Trader liveness logging (every 60s: consumed/executed/skipped)
ENABLE_TRADER_LIVENESS_LOG = os.getenv("ENABLE_TRADER_LIVENESS_LOG", "true").lower() == "true"
TRADER_LIVENESS_LOG_INTERVAL_SEC = int(os.getenv("TRADER_LIVENESS_LOG_INTERVAL_SEC", "60"))

# Feature freshness logging (every N cycles, log nonzero ratio + staleness)
ENABLE_FEATURE_FRESHNESS_LOG = os.getenv("ENABLE_FEATURE_FRESHNESS_LOG", "false").lower() == "true"
FEATURE_FRESHNESS_LOG_CYCLE_INTERVAL = int(os.getenv("FEATURE_FRESHNESS_LOG_CYCLE_INTERVAL", "10"))

# ============================================================================
# DYNAMIC RUNNER & HEDGE OVERLAY (Addendum B) - Let Winners Run, Protect Reversals
# ============================================================================
ENABLE_DYNAMIC_RUNNER_HEDGE = os.getenv("ENABLE_DYNAMIC_RUNNER_HEDGE", "true").lower() == "true"

# EXECUTE mode: Actually publish intents to signals:trading (default ON = execute profit protection)
ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE = os.getenv("ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE", "true").lower() == "true"

# Allow overlay hedge opens.
#
# IMPORTANT (Jan 2026):
# We now run a unified hedge system via `DynamicAdaptiveHedge` in the traders.
# Allowing the overlay to ALSO open hedges creates overlapping hedge sources and
# can produce "mystery hedges" (e.g., ROE-triggered hedges at local tops/bottoms).
#
# Therefore, overlay hedge opens are **OFF by default**. If you explicitly want
# the overlay to open hedges, set `DYNAMIC_HEDGE_ALLOW_OPEN=true` AND ensure
# `ADAPTIVE_HEDGE_ENABLED=false` (single hedge opener rule).
DYNAMIC_HEDGE_ALLOW_OPEN = os.getenv("DYNAMIC_HEDGE_ALLOW_OPEN", "false").lower() == "true"
try:
    if DYNAMIC_HEDGE_ALLOW_OPEN and bool(ADAPTIVE_HEDGE_ENABLED):
        logging.getLogger(__name__).warning(
            "[CONFIG] DYNAMIC_HEDGE_ALLOW_OPEN=true but ADAPTIVE_HEDGE_ENABLED=true. "
            "Disabling overlay hedge opens to avoid overlapping hedge systems."
        )
        DYNAMIC_HEDGE_ALLOW_OPEN = False
except Exception:
    # Fail-safe: do not crash config import
    pass

# Canary mode: Only apply to canary symbols first (default ON for safety)
DYNAMIC_RUNNER_HEDGE_CANARY_ONLY = os.getenv("DYNAMIC_RUNNER_HEDGE_CANARY_ONLY", "true").lower() == "true"

# Anti-churn controls for overlay actions
DYNAMIC_RUNNER_HEDGE_MAX_ACTIONS_PER_SYMBOL_PER_10MIN = int(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_ACTIONS_PER_SYMBOL_PER_10MIN", "3"))
DYNAMIC_RUNNER_HEDGE_MIN_SECONDS_BETWEEN_ACTIONS = int(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_SECONDS_BETWEEN_ACTIONS", "60"))
DYNAMIC_RUNNER_HEDGE_MIN_DELTA_CLOSE_PCT = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_DELTA_CLOSE_PCT", "0.10"))  # Ignore micro partial closes

# Hedge sizing limits
DYNAMIC_RUNNER_HEDGE_MIN_HEDGE_NOTIONAL_USD = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_HEDGE_NOTIONAL_USD", "10"))
DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_MARGIN_PCT_EQUITY = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_MARGIN_PCT_EQUITY", "1.5"))  # TIGHTENED: Max 1.5% equity per hedge
DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_GROSS_PCT_EQUITY = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_GROSS_PCT_EQUITY", "5.0"))  # TIGHTENED: Max 5% across all hedges
DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_PER_SYMBOL_PCT = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_PER_SYMBOL_PCT", "3.0"))  # NEW: Max 3% hedge per symbol

# Reserve buffer: overlay must not consume reserve unless explicitly allowed
DYNAMIC_RUNNER_HEDGE_USE_RESERVE_BUFFER = os.getenv("DYNAMIC_RUNNER_HEDGE_USE_RESERVE_BUFFER", "false").lower() == "true"

# Overlay logging interval (seconds)
DYNAMIC_RUNNER_HEDGE_LOG_INTERVAL_SEC = int(os.getenv("DYNAMIC_RUNNER_HEDGE_LOG_INTERVAL_SEC", "60"))

# ROE threshold for triggering hedge protection (±20%)
RUNNER_HEDGE_ROE_THRESHOLD_PCT = float(os.getenv("RUNNER_HEDGE_ROE_THRESHOLD_PCT", "20.0"))

# Hysteresis: require condition to persist before acting
RUNNER_HEDGE_HYSTERESIS_SECONDS = int(os.getenv("RUNNER_HEDGE_HYSTERESIS_SECONDS", "30"))
RUNNER_HEDGE_HYSTERESIS_CANDLES = int(os.getenv("RUNNER_HEDGE_HYSTERESIS_CANDLES", "3"))  # 1m candles

# Exit hysteresis: drop below this % ROE to unwrap hedge
RUNNER_HEDGE_UNWIND_ROE_PCT = float(os.getenv("RUNNER_HEDGE_UNWIND_ROE_PCT", "12.0"))

# Hedge sizing as fraction of main position (configurable by ROE tier)
RUNNER_HEDGE_SIZE_20PCT_ROE = float(os.getenv("RUNNER_HEDGE_SIZE_20PCT_ROE", "0.15"))  # 15% at +20% ROE
RUNNER_HEDGE_SIZE_40PCT_ROE = float(os.getenv("RUNNER_HEDGE_SIZE_40PCT_ROE", "0.30"))  # 30% at +40% ROE
RUNNER_HEDGE_SIZE_80PCT_ROE = float(os.getenv("RUNNER_HEDGE_SIZE_80PCT_ROE", "0.50"))  # 50% at +80% ROE

# Hot monitor lane: 1m/5m enabled only for positions meeting criteria
ENABLE_HOT_MONITOR_LANE = os.getenv("ENABLE_HOT_MONITOR_LANE", "false").lower() == "true"
HOT_MONITOR_ROE_THRESHOLD_PCT = float(os.getenv("HOT_MONITOR_ROE_THRESHOLD_PCT", "20.0"))
HOT_MONITOR_CONF_THRESHOLD = float(os.getenv("HOT_MONITOR_CONF_THRESHOLD", "0.98"))

# ============================================================================
# PORTFOLIO RECOVERY ALLOCATION (PRA) — URC Stage‑2 (Scaffolding)
# ============================================================================
# Purpose:
# - Optional, bounded "recovery budget" allocator for other symbols (recommendation-only by default).
# - Does NOT replace per-symbol hedging.
# - Execution is intentionally OFF by default (safety).
PRA_ENABLED = os.getenv("PRA_ENABLED", "true").lower() in ("1", "true", "yes")
PRA_EXECUTE = os.getenv("PRA_EXECUTE", "false").lower() in ("1", "true", "yes")  # reserved for future
PRA_PUBLISH_INTERVAL_SEC = float(os.getenv("PRA_PUBLISH_INTERVAL_SEC", "120"))
PRA_MAX_SUGGESTIONS_PER_ACCOUNT = int(os.getenv("PRA_MAX_SUGGESTIONS_PER_ACCOUNT", "3"))
PRA_MAX_DATA_STALENESS_MS = float(os.getenv("PRA_MAX_DATA_STALENESS_MS", "60000"))
PRA_MAX_MARGIN_PCT_EQUITY = float(os.getenv("PRA_MAX_MARGIN_PCT_EQUITY", "1.0"))  # % of equity (cap)
PRA_MAX_MARGIN_PCT_AVAILABLE = float(os.getenv("PRA_MAX_MARGIN_PCT_AVAILABLE", "15.0"))  # % of available margin (cap)
PRA_SUGGEST_LEVERAGE = float(os.getenv("PRA_SUGGEST_LEVERAGE", "3.0"))  # suggestion leverage (execution layer may clamp)

# ==========================================================================
# CORRECTIVE RECOVERY (Reduce-First, No Exposure Increase)
# ==========================================================================
# Purpose:
# - When OPEN_RISK is repeatedly blocked by portfolio caps/budgets/diversification, emit a
#   bounded PROTECTIVE reduction to free margin/cap headroom.
# - This does NOT open new risk directly; it is designed to be exposure-neutral or reducing.
# - Defaults are FAIL-CLOSED (disabled).
#
# When enabled, the trainer can emit *reduce-first* signals to free margin/slots when a
# high-confidence OPEN_RISK candidate is blocked by portfolio caps/diversification.
ENABLE_CORRECTIVE_RECOVERY = os.getenv("ENABLE_CORRECTIVE_RECOVERY", "true").lower() in ("1", "true", "yes")

# Allow recovery-driven reductions to bypass NO_LOSS_EXIT_GUARD.
# Without this, corrective recovery cannot free headroom when the portfolio is underwater,
# which cascades into "no new trades" even when the market offers opportunities.
RECOVERY_BYPASS_NO_LOSS_EXIT_GUARD = os.getenv("RECOVERY_BYPASS_NO_LOSS_EXIT_GUARD", "false").lower() in ("1", "true", "yes")  # FIX Apr 14: false (was true — recovery was bypassing no-loss and realizing losses)

# Limit recovery reductions to avoid churn.
RECOVERY_MAX_REDUCTIONS_PER_BUCKET = int(os.getenv("RECOVERY_MAX_REDUCTIONS_PER_BUCKET", "1"))  # per account per ~cycle bucket
RECOVERY_REDUCE_FRACTION = float(os.getenv("RECOVERY_REDUCE_FRACTION", "0.20"))  # default 20% partial close

# Recovery candidate selection safety:
# Corrective recovery exists to free headroom (margin/slots) when portfolio caps block a high-priority action.
# By default, avoid realizing deep losses just to free margin; if all candidates are losing beyond the limit,
# recovery will skip and let the blocked action remain blocked (safer than forced loss-cut).
RECOVERY_AVOID_DEEP_LOSS = os.getenv("RECOVERY_AVOID_DEEP_LOSS", "true").lower() in ("1", "true", "yes")
RECOVERY_MAX_LOSS_PCT = float(os.getenv("RECOVERY_MAX_LOSS_PCT", "3.0"))  # avoid closing legs worse than -3% (estimate)
RECOVERY_MAX_LOSS_USD = float(os.getenv("RECOVERY_MAX_LOSS_USD", "50.0"))  # avoid closing legs with loss worse than -$50 (estimate)
RECOVERY_ALLOW_DEEP_LOSS_FALLBACK = os.getenv("RECOVERY_ALLOW_DEEP_LOSS_FALLBACK", "false").lower() in ("1", "true", "yes")

# ============================================================================
# FLIP-AT-TARGET: Close position + Open opposite with stealth TP at predicted price
# ============================================================================
# When a CLOSE signal has a price_target in the opposite direction, this feature:
# 1. Closes the position (as normal)
# 2. Opens the opposite side with the same margin
# 3. Arms a STEALTH TP at the predicted price (not on Binance - invisible to market)
#
# Safety guards prevent churn/bleeding:
# - Only flip on profitable closes (taking profits, not losses)
# - High confidence threshold (82%+)
# - Per-symbol cooldown to prevent rapid flips
# - Recovery/corrective signals excluded
# - Opposite position must not exist (no stacking)
# - Price target must be within 10% of current price
ENABLE_FLIP_AT_TARGET = os.getenv("ENABLE_FLIP_AT_TARGET", "false").lower() in ("1", "true", "yes")  # DISABLED Apr 2026: caused close-reopen churn
FLIP_AT_TARGET_MIN_MARGIN_USD = float(os.getenv("FLIP_AT_TARGET_MIN_MARGIN_USD", "5.0"))  # Min margin to flip
FLIP_AT_TARGET_MIN_SIZE_PCT = float(os.getenv("FLIP_AT_TARGET_MIN_SIZE_PCT", "0.5"))  # Min position size %
FLIP_AT_TARGET_MIN_CONFIDENCE = float(os.getenv("FLIP_AT_TARGET_MIN_CONFIDENCE", "0.82"))  # Min confidence to flip
FLIP_AT_TARGET_MIN_PROFIT_PNL_PCT = float(os.getenv("FLIP_AT_TARGET_MIN_PROFIT_PNL_PCT", "0.1"))  # Min PnL% on close (0.1% = fee-positive)
FLIP_AT_TARGET_COOLDOWN_SECONDS = int(os.getenv("FLIP_AT_TARGET_COOLDOWN_SECONDS", "300"))  # Cooldown per symbol
FLIP_AT_TARGET_MAX_SIZE_PCT = float(os.getenv("FLIP_AT_TARGET_MAX_SIZE_PCT", "8.0"))  # Max flip size %
FLIP_AT_TARGET_MAX_PRICE_DIFF_PCT = float(os.getenv("FLIP_AT_TARGET_MAX_PRICE_DIFF_PCT", "10.0"))  # Max target distance

# ============================================================================
# ANTI-CHURN PROTECTIONS (Addendum C) - Hedge State Machine & Execution Caps
# ============================================================================
ENABLE_ANTI_CHURN_PROTECTIONS = os.getenv("ENABLE_ANTI_CHURN_PROTECTIONS", "true").lower() == "true"  # FIX Apr 14: Re-enabled (was false — fee bleed vector)

# Per-symbol execution caps (per hour, separate by action type)
ANTI_CHURN_HEDGE_ADJUSTMENTS_PER_HOUR = int(os.getenv("ANTI_CHURN_HEDGE_ADJUSTMENTS_PER_HOUR", "2"))  # FIX Apr 16: 4→2. 341 hedge signals/10h = excessive churn
ANTI_CHURN_PARTIAL_CLOSES_PER_HOUR = int(os.getenv("ANTI_CHURN_PARTIAL_CLOSES_PER_HOUR", "2"))  # FIX Apr 16: 4→2. Premature partials killed winners (SOL +$10 partials while it went 86→89)
ANTI_CHURN_FLIPS_PER_HOUR = int(os.getenv("ANTI_CHURN_FLIPS_PER_HOUR", "2"))

# Hedge state machine minimum interval (seconds between state changes)
ANTI_CHURN_HEDGE_STATE_MIN_INTERVAL_SEC = int(os.getenv("ANTI_CHURN_HEDGE_STATE_MIN_INTERVAL_SEC", "120"))

# Warm start window: ignore signals older than this after startup
ANTI_CHURN_WARM_START_WINDOW_SEC = int(os.getenv("ANTI_CHURN_WARM_START_WINDOW_SEC", "60"))

# ============================================================================
# TARGET EXPOSURE CONTROLLER (Replaces simple duplicate suppression)
# ============================================================================
ENABLE_TARGET_EXPOSURE_CONTROLLER = os.getenv("ENABLE_TARGET_EXPOSURE_CONTROLLER", "true").lower() == "true"

# Minimum delta % (of equity) before emitting INCREASE/DECREASE
TARGET_MIN_DELTA_PCT = float(os.getenv("TARGET_MIN_DELTA_PCT", "1.0"))

# Minimum interval (seconds) between INCREASE/DECREASE actions per symbol
TARGET_MIN_INTERVAL_SEC = int(os.getenv("TARGET_MIN_INTERVAL_SEC", "60"))

# Maximum exposure % per symbol
TARGET_MAX_EXPOSURE_PCT = float(os.getenv("TARGET_MAX_EXPOSURE_PCT", "10.0"))

# Minimum exposure % for new positions
TARGET_MIN_EXPOSURE_PCT = float(os.getenv("TARGET_MIN_EXPOSURE_PCT", "2.0"))

# Minimum number of TFs that must vote FLAT before the controller can issue CLOSE
TARGET_CLOSE_QUORUM_TFS = int(os.getenv("TARGET_CLOSE_QUORUM_TFS", "2"))

# ============================================================================
# MICROSTRUCTURE OVERLAY (Spoof + Fast-Move Detection)
# ============================================================================
# Master switch: Enable microstructure overlay 
# ENABLED (AI TA 12-25-2025): Activated for fast-move/squeeze/liquidation detection
ENABLE_MICROSTRUCTURE_OVERLAY = os.getenv("ENABLE_MICROSTRUCTURE_OVERLAY", "true").lower() == "true"

# Mode: gating (block/reduce). Log-only mode is not supported in live-only system.
MICROSTRUCTURE_OVERLAY_MODE = "gating"

# Spoof detection threshold (0-1, higher = more sensitive)
MICROSTRUCTURE_SPOOF_THRESHOLD = float(os.getenv("MICROSTRUCTURE_SPOOF_THRESHOLD", "0.6"))

# Fast-move detection threshold (0-1, higher = more sensitive)
# 0.60: balanced — blocks genuine fast moves but allows normal volatility entries
MICROSTRUCTURE_FAST_MOVE_THRESHOLD = float(os.getenv("MICROSTRUCTURE_FAST_MOVE_THRESHOLD", "0.60"))

# Size reduction multiplier when spoof detected
MICROSTRUCTURE_SPOOF_SIZE_MULTIPLIER = float(os.getenv("MICROSTRUCTURE_SPOOF_SIZE_MULTIPLIER", "0.4"))

# Spoof action: "block" (block entry) or "size_reduce" (reduce size)
MICROSTRUCTURE_SPOOF_ACTION = os.getenv("MICROSTRUCTURE_SPOOF_ACTION", "size_reduce")

# Size reduction factor when spoof detected (0-1, lower = smaller position)
MICROSTRUCTURE_SIZE_REDUCTION_FACTOR = float(os.getenv("MICROSTRUCTURE_SIZE_REDUCTION_FACTOR", "0.5"))

# ============================================================================
# FOLKS REVERSAL CAPTURE SYSTEM (Dec 27, 2025)
# ============================================================================
# Reversal Watch: Enters after fast-move entries to manage reversal risk
REVERSAL_WATCH_ENABLED = os.getenv("REVERSAL_WATCH_ENABLED", "true").lower() == "true"
FAST_MOVE_THRESHOLD = float(os.getenv("FAST_MOVE_THRESHOLD", "0.02"))  # 2% 1m range
REVERSAL_WATCH_TIMEOUT_MINUTES = int(os.getenv("REVERSAL_WATCH_TIMEOUT_MINUTES", "15"))

# Profit Ladder: Partial take-profits during reversal watch
PROFIT_LADDER_ENABLED = os.getenv("PROFIT_LADDER_ENABLED", "true").lower() == "true"
PROFIT_LADDER_ROI_LEVELS = [0.05, 0.10, 0.15, 0.20]  # 5%, 10%, 15%, 20% ROI thresholds
PROFIT_LADDER_PCTS = [0.25, 0.25, 0.30, 0.20]  # Take 25%, 25%, 30%, 20% at each level
MAX_PROFIT_GIVEBACK_PCT = float(os.getenv("MAX_PROFIT_GIVEBACK_PCT", "0.15"))  # 15% max giveback

# Reversal Hedge Emitter: Deterministic hedge on microstructure flip
HEDGE_ON_MICRO_FLIP = os.getenv("HEDGE_ON_MICRO_FLIP", "true").lower() == "true"
HEDGE_PCT_LOW_ROI = float(os.getenv("HEDGE_PCT_LOW_ROI", "0.25"))  # 25% hedge if ROI < 8%
HEDGE_PCT_HIGH_ROI = float(os.getenv("HEDGE_PCT_HIGH_ROI", "0.50"))  # 50% hedge if ROI > 15%

# Dynamic Trailing: Tighten trailing during reversal watch
TRAIL_TIGHTEN_FACTOR_ON_REVERSAL_WATCH = float(os.getenv("TRAIL_TIGHTEN_FACTOR_ON_REVERSAL_WATCH", "0.5"))

# ============================================================================
# INGESTOR QUALITY ROUTER (Best-source routing for microstructure data)
# ============================================================================
# Master switch: Enable ingestor quality router (default OFF)
ENABLE_INGESTOR_QUALITY_ROUTER = os.getenv("ENABLE_INGESTOR_QUALITY_ROUTER", "false").lower() == "true"

# Update interval for quality scoring (seconds)
INGESTOR_QUALITY_UPDATE_INTERVAL_SEC = int(os.getenv("INGESTOR_QUALITY_UPDATE_INTERVAL_SEC", "30"))

# Canonicalize orderbook fields to unified_features:*:latest
INGESTOR_QUALITY_CANONICALIZE_ORDERBOOK = os.getenv("INGESTOR_QUALITY_CANONICALIZE_ORDERBOOK", "false").lower() == "true"

# ============================================================================
# COINAPI INTEGRATION (WebSocket DS + REST fallback)
# ============================================================================
# Master switch (OFF by default - must explicitly enable)
ENABLE_COINAPI = os.getenv("ENABLE_COINAPI", "false").lower() == "true"

# Environment: prod or sandbox
COINAPI_ENV = os.getenv("COINAPI_ENV", "prod")

# API Key (REQUIRED - from env only for security)
COINAPI_API_KEY = os.getenv("COINAPI_API_KEY", "")

# WebSocket DS endpoint (from CoinAPI docs)
# Production: wss://ws.coinapi.io/v1/
# Sandbox: wss://ws-sandbox.coinapi.io/v1/
COINAPI_WSDS_URL_PROD = "wss://ws.coinapi.io/v1/"
COINAPI_WSDS_URL_SANDBOX = "wss://ws-sandbox.coinapi.io/v1/"
COINAPI_WSDS_URL = os.getenv("COINAPI_WSDS_URL", COINAPI_WSDS_URL_PROD if COINAPI_ENV == "prod" else COINAPI_WSDS_URL_SANDBOX)

# REST API endpoint
COINAPI_REST_URL = os.getenv("COINAPI_REST_URL", "https://rest.coinapi.io")

# WebSocket vs REST mode control
# WebSocket is primary (low latency), REST is fallback only
COINAPI_ENABLE_WEBSOCKET = os.getenv("COINAPI_ENABLE_WEBSOCKET", "true").lower() == "true"
COINAPI_ENABLE_REST = os.getenv("COINAPI_ENABLE_REST", "false").lower() == "true"  # Disabled by default, manual enable

# Primary exchange to map symbols to (must match CoinAPI exchange IDs)
# Examples: BINANCE, BINANCEFTS (futures), COINBASE, KRAKEN
COINAPI_PRIMARY_EXCHANGE_ID = os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")

# Symbol map cache TTL (1 day default)
COINAPI_SYMBOL_MAP_TTL_SEC = int(os.getenv("COINAPI_SYMBOL_MAP_TTL_SEC", "86400"))

# Manual symbol overrides (JSON string: {"BTCUSDT": "BINANCEFTS_PERP_BTC_USDT", ...})
COINAPI_SYMBOL_OVERRIDES_JSON = os.getenv("COINAPI_SYMBOL_OVERRIDES_JSON", "{}")

# WebSocket subscription data types (per CoinAPI DS docs)
# Options: quote, trade, orderbooks (full L2), ohlcv
# Note: orderbooks provides full depth; quote provides best bid/ask
# CoinAPI subscribe_data_type options: quote (L1 BBO), trade, book (full L2), book5/book20/book50 (top N levels)
# Default to quote+book5 (L1 + shallow depth) to avoid ingest lag/policy-violation disconnects.
# Enable `trade` explicitly only if your WSDS consumer can keep up (high message rate on BTC/ETH).
COINAPI_SUBSCRIBE_DATA_TYPES = os.getenv("COINAPI_SUBSCRIBE_DATA_TYPES", "quote,book5").split(",")

# Maximum symbols to subscribe (bandwidth control)
COINAPI_MAX_SUBSCRIBED_SYMBOLS = int(os.getenv("COINAPI_MAX_SUBSCRIBED_SYMBOLS", "30"))

# Only subscribe to active trading universe
COINAPI_SUBSCRIBE_ONLY_ACTIVE_UNIVERSE = os.getenv("COINAPI_SUBSCRIBE_ONLY_ACTIVE_UNIVERSE", "true").lower() == "true"

# Staleness thresholds (ms)
COINAPI_STALE_WS_MS = int(os.getenv("COINAPI_STALE_WS_MS", "1500"))
COINAPI_STALE_REST_MS = int(os.getenv("COINAPI_STALE_REST_MS", "5000"))

# REST rate limiting
COINAPI_REST_MAX_RPS = float(os.getenv("COINAPI_REST_MAX_RPS", "0.5"))
COINAPI_REST_DAILY_CAP = int(os.getenv("COINAPI_REST_DAILY_CAP", "90000"))  # Keep under 100k/day

# WebSocket bandwidth caps (GB/day)
COINAPI_WS_BYTES_DAILY_SOFT_CAP_GB = float(os.getenv("COINAPI_WS_BYTES_DAILY_SOFT_CAP_GB", "450"))
COINAPI_WS_BYTES_DAILY_HARD_CAP_GB = float(os.getenv("COINAPI_WS_BYTES_DAILY_HARD_CAP_GB", "500"))

# Reconnection and resubscription controls
COINAPI_RESUBSCRIBE_MIN_INTERVAL_SEC = int(os.getenv("COINAPI_RESUBSCRIBE_MIN_INTERVAL_SEC", "60"))
COINAPI_RECONNECT_BACKOFF_SEC = [1, 2, 5, 10, 30, 60]  # With jitter
COINAPI_RECONNECT_MAX_ATTEMPTS = int(os.getenv("COINAPI_RECONNECT_MAX_ATTEMPTS", "10"))

# Logging interval
COINAPI_LOG_EVERY_SEC = int(os.getenv("COINAPI_LOG_EVERY_SEC", "60"))

# Redis metrics prefix
COINAPI_METRICS_REDIS_PREFIX = os.getenv("COINAPI_METRICS_REDIS_PREFIX", "metrics:coinapi")

# Microstructure snapshot Redis key prefix
COINAPI_MSNAP_PREFIX = "msnap"

# ============================================================================
# REALTIME PRICE PROVIDER - Multi-source failover with low latency
# ============================================================================
# Master switch for realtime price provider
ENABLE_REALTIME_PRICE_PROVIDER = os.getenv("ENABLE_REALTIME_PRICE_PROVIDER", "true").lower() == "true"

# Source priority (1=highest, higher numbers=lower priority)
# Sources: coinapi_ws, binance_ws, ccxt_rest, kucoin_rest, redis_cache
PRICE_SOURCE_COINAPI_PRIORITY = int(os.getenv("PRICE_SOURCE_COINAPI_PRIORITY", "1"))
PRICE_SOURCE_BINANCE_PRIORITY = int(os.getenv("PRICE_SOURCE_BINANCE_PRIORITY", "2"))
PRICE_SOURCE_CCXT_PRIORITY = int(os.getenv("PRICE_SOURCE_CCXT_PRIORITY", "3"))
PRICE_SOURCE_KUCOIN_PRIORITY = int(os.getenv("PRICE_SOURCE_KUCOIN_PRIORITY", "4"))
PRICE_SOURCE_CACHE_PRIORITY = int(os.getenv("PRICE_SOURCE_CACHE_PRIORITY", "99"))

# Enable/disable individual sources
PRICE_SOURCE_COINAPI_ENABLED = os.getenv("PRICE_SOURCE_COINAPI_ENABLED", "true").lower() == "true"
PRICE_SOURCE_BINANCE_ENABLED = os.getenv("PRICE_SOURCE_BINANCE_ENABLED", "true").lower() == "true"
PRICE_SOURCE_CCXT_ENABLED = os.getenv("PRICE_SOURCE_CCXT_ENABLED", "true").lower() == "true"
PRICE_SOURCE_KUCOIN_ENABLED = os.getenv("PRICE_SOURCE_KUCOIN_ENABLED", "true").lower() == "true"
PRICE_SOURCE_CACHE_ENABLED = os.getenv("PRICE_SOURCE_CACHE_ENABLED", "true").lower() == "true"

# Staleness thresholds (milliseconds) - source considered stale after this
PRICE_STALE_COINAPI_MS = int(os.getenv("PRICE_STALE_COINAPI_MS", "2000"))    # 2s for WebSocket
PRICE_STALE_BINANCE_MS = int(os.getenv("PRICE_STALE_BINANCE_MS", "2000"))    # 2s for WebSocket
PRICE_STALE_CCXT_MS = int(os.getenv("PRICE_STALE_CCXT_MS", "5000"))          # 5s for REST
PRICE_STALE_KUCOIN_MS = int(os.getenv("PRICE_STALE_KUCOIN_MS", "5000"))      # 5s for REST
PRICE_STALE_CACHE_MS = int(os.getenv("PRICE_STALE_CACHE_MS", "60000"))       # 60s for cache

# Failover delay (ms) - max time to wait before failing over to next source
PRICE_FAILOVER_COINAPI_MS = int(os.getenv("PRICE_FAILOVER_COINAPI_MS", "300"))
PRICE_FAILOVER_BINANCE_MS = int(os.getenv("PRICE_FAILOVER_BINANCE_MS", "500"))
PRICE_FAILOVER_CCXT_MS = int(os.getenv("PRICE_FAILOVER_CCXT_MS", "1000"))
PRICE_FAILOVER_KUCOIN_MS = int(os.getenv("PRICE_FAILOVER_KUCOIN_MS", "1000"))

# Recovery check interval (seconds) - how often to check if failed source recovered
PRICE_RECOVERY_CHECK_SEC = float(os.getenv("PRICE_RECOVERY_CHECK_SEC", "5.0"))

# Max consecutive failures before marking source unhealthy
PRICE_MAX_CONSECUTIVE_FAILURES = int(os.getenv("PRICE_MAX_CONSECUTIVE_FAILURES", "5"))

# Health check interval (seconds)
PRICE_HEALTH_CHECK_INTERVAL_SEC = float(os.getenv("PRICE_HEALTH_CHECK_INTERVAL_SEC", "1.0"))

# Publish rate limit (ms) - min interval between Redis publishes per symbol
PRICE_PUBLISH_INTERVAL_MS = int(os.getenv("PRICE_PUBLISH_INTERVAL_MS", "100"))

# ============================================================================
# PROMOTION CONTROLLER - Staged rollout (observe-only to live gating)
# ============================================================================
# Promotion Levels:
#   0 = CoinAPI ingest only (no router, no overlay)
#   1 = Router + canonicalization ON; overlay observe-only (no gating)
#   2 = Overlay gating ON but "size_reduce only" (no hard blocks)
#   3 = Overlay gating ON with hard blocks for entries on severe spoof/fast-move
PROMOTION_LEVEL = int(os.getenv("PROMOTION_LEVEL", "0"))

# Canary mode: Only apply gating to a subset of symbols first
PROMOTION_CANARY_MODE = os.getenv("PROMOTION_CANARY_MODE", "true").lower() in ('true', '1', 'yes')
PROMOTION_CANARY_MAX_SYMBOLS = int(os.getenv("PROMOTION_CANARY_MAX_SYMBOLS", "8"))
PROMOTION_CANARY_INCLUDE_OPEN_POSITIONS = os.getenv("PROMOTION_CANARY_INCLUDE_OPEN_POSITIONS", "true").lower() in ('true', '1', 'yes')
PROMOTION_CANARY_ROTATION_SEC = int(os.getenv("PROMOTION_CANARY_ROTATION_SEC", "1800"))

# Health prerequisites for promotion eligibility
# RELAXED 2025-12-28: CoinAPI WS is unstable with frequent reconnects
# Previous values (700/1500/0.85) too strict, causing MICROSTRUCTURE_FAIL_CLOSED on all entries
PROMOTION_MIN_WS_CONNECTED_SEC = int(os.getenv("PROMOTION_MIN_WS_CONNECTED_SEC", "60"))  # Was 120s
PROMOTION_MAX_WS_P50_STALENESS_MS = int(os.getenv("PROMOTION_MAX_WS_P50_STALENESS_MS", "10000"))  # Was 700ms - too strict
PROMOTION_MAX_WS_P95_STALENESS_MS = int(os.getenv("PROMOTION_MAX_WS_P95_STALENESS_MS", "30000"))  # Was 1500ms - too strict
PROMOTION_MIN_MSNAP_COMPLETENESS = float(os.getenv("PROMOTION_MIN_MSNAP_COMPLETENESS", "0.50"))  # Was 0.85 - too strict

# Budget thresholds for auto-demotion (stricter than caps for headroom)
PROMOTION_MAX_REST_DAILY_USED = int(os.getenv("PROMOTION_MAX_REST_DAILY_USED", "80000"))
PROMOTION_MAX_WS_BYTES_TODAY_GB = float(os.getenv("PROMOTION_MAX_WS_BYTES_TODAY_GB", "450"))
PROMOTION_WS_BYTES_HARD_CAP_GB = float(os.getenv("PROMOTION_WS_BYTES_HARD_CAP_GB", "500"))

# Microstructure overlay settings - use top-level constants (lines 1206-1221)
# Removed duplicates with conflicting defaults

# ============================================================================
# INTENT CODES (Addendum D) - Action Intent Classification
# ============================================================================
class IntentCode:
    ENTRY = "ENTRY"                     # New position entry
    MANAGE_PROFIT = "MANAGE_PROFIT"     # Profit management (trail, partial)
    MANAGE_LOSS = "MANAGE_LOSS"         # Loss management (stop, reduce)
    HEDGE_OPEN = "HEDGE_OPEN"           # Open protective hedge
    HEDGE_SCALE = "HEDGE_SCALE"         # Scale existing hedge
    HEDGE_UNWIND = "HEDGE_UNWIND"       # Remove hedge
    EXIT_EMERGENCY = "EXIT_EMERGENCY"   # Emergency exit (circuit breaker)
    EXIT_NORMAL = "EXIT_NORMAL"         # Normal model-driven exit

# Hedge State Machine States
class HedgeState:
    NONE = "NONE"                 # No hedge active
    HEDGE_OPEN = "HEDGE_OPEN"     # Initial hedge opened
    HEDGE_SCALED = "HEDGE_SCALED" # Hedge has been scaled up
    HEDGE_UNWIND = "HEDGE_UNWIND" # Hedge being unwound

# ============================================================================
# PREDICTION PIPELINE CONFIGURATION (Stabilization Audit)
# ============================================================================

# Pipeline mode: "v2" (batched/deconflicted single publisher) or "legacy" (per-symbol)
PREDICTION_PIPELINE_MODE = os.getenv("PREDICTION_PIPELINE_MODE", "v2")

# Training/Prediction yield time - how long prediction worker waits after training ends
TRAINING_PREDICTION_YIELD_SEC = float(os.getenv("TRAINING_PREDICTION_YIELD_SEC", "0.5"))

# Minimum notional for signals (below this, sizing bumps up or signal blocked)
MIN_NOTIONAL_USD = float(os.getenv("MIN_NOTIONAL_USD", "5.0"))

# Minimum OPEN_RISK floors (avoid dust trades after downsizing)
# IMPORTANT: MIN_OPEN_NOTIONAL_USD must be <= per_pos_margin_pct * equity to avoid ORCH-08 rejections
# With equity ~$2400 and per_pos_margin_pct=0.02 (2%), cap is ~$48, so min must be lower
MIN_OPEN_CLAMP_ENABLED = os.getenv("MIN_OPEN_CLAMP_ENABLED", "true").lower() in ("1", "true", "yes")
MIN_OPEN_MARGIN_USD = float(os.getenv("MIN_OPEN_MARGIN_USD", "30.0"))  # Raised from 10.0: floor for meaningful live sizing
MIN_OPEN_NOTIONAL_USD = float(os.getenv("MIN_OPEN_NOTIONAL_USD", "10.0"))  # Reduced from 150 to fit within per-symbol cap

# Data-quality guardrails for liquidation-distance fallback
DQ_LIQ_FALLBACK_ENABLED = os.getenv("DQ_LIQ_FALLBACK_ENABLED", "true").lower() in ("1", "true", "yes")
DQ_LIQ_FALLBACK_MAX_AGE_MS = int(os.getenv("DQ_LIQ_FALLBACK_MAX_AGE_MS", "60000"))
DQ_LIQ_FALLBACK_NON_MAJOR_DOWNSIZE_PCT = float(os.getenv("DQ_LIQ_FALLBACK_NON_MAJOR_DOWNSIZE_PCT", "0.2"))
DQ_LIQ_FALLBACK_CONFIDENCE = float(os.getenv("DQ_LIQ_FALLBACK_CONFIDENCE", "0.3"))

# Data-quality enrichment (fill missing fields from feature store)
DQ_ENRICH_ENABLED = os.getenv("DQ_ENRICH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DQ_ENRICH_MAX_AGE_MS = int(os.getenv("DQ_ENRICH_MAX_AGE_MS", "60000"))
DQ_ENRICH_CONFIDENCE = float(os.getenv("DQ_ENRICH_CONFIDENCE", "0.5"))
DQ_ENRICH_BLOCK_MISSING = os.getenv("DQ_ENRICH_BLOCK_MISSING", "true").lower() in ("1", "true", "yes", "on")
DQ_ENRICH_REQUIRED_FIELDS = ["liq_distance_pct", "orderbook_depth_usd", "volatility_pct"]
DQ_ENRICH_PARSE_CONSTRAINTS = os.getenv("DQ_ENRICH_PARSE_CONSTRAINTS", "true").lower() in ("1", "true", "yes", "on")

# Hedge stress percentile controller (dynamic hedge lifecycle)
HEDGE_STRESS_ENABLED = os.getenv("HEDGE_STRESS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HEDGE_STRESS_PCTL_FULL = float(os.getenv("HEDGE_STRESS_PCTL_FULL", "90"))
HEDGE_STRESS_PCTL_PARTIAL = float(os.getenv("HEDGE_STRESS_PCTL_PARTIAL", "75"))
HEDGE_STRESS_PCTL_OFF = float(os.getenv("HEDGE_STRESS_PCTL_OFF", "50"))
HEDGE_STRESS_MIN_DQ_SCORE = float(os.getenv("HEDGE_STRESS_MIN_DQ_SCORE", "0.50"))
HEDGE_STRESS_MIN_DEPTH_PCTL = float(os.getenv("HEDGE_STRESS_MIN_DEPTH_PCTL", "25"))
HEDGE_STRESS_W_LIQPROX = float(os.getenv("HEDGE_STRESS_W_LIQPROX", "0.35"))
HEDGE_STRESS_W_VOL = float(os.getenv("HEDGE_STRESS_W_VOL", "0.25"))
HEDGE_STRESS_W_TOX = float(os.getenv("HEDGE_STRESS_W_TOX", "0.25"))
HEDGE_STRESS_W_DEPTH = float(os.getenv("HEDGE_STRESS_W_DEPTH", "0.15"))

# Dynamic max positions scaling (portfolio health aware)
DYNAMIC_MAX_POSITIONS_ENABLED = os.getenv("DYNAMIC_MAX_POSITIONS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DYNAMIC_MAX_POSITIONS_BASE = int(os.getenv("DYNAMIC_MAX_POSITIONS_BASE", "15"))
DYNAMIC_MAX_POSITIONS_MIN = int(os.getenv("DYNAMIC_MAX_POSITIONS_MIN", "6"))
DYNAMIC_MAX_POSITIONS_CAP = int(os.getenv("DYNAMIC_MAX_POSITIONS_CAP", "18"))
DYNAMIC_MAX_POSITIONS_DD_SOFT_PCT = float(os.getenv("DYNAMIC_MAX_POSITIONS_DD_SOFT_PCT", "4.0"))
DYNAMIC_MAX_POSITIONS_DD_HARD_PCT = float(os.getenv("DYNAMIC_MAX_POSITIONS_DD_HARD_PCT", "6.0"))
DYNAMIC_MAX_POSITIONS_MU_SOFT = float(os.getenv("DYNAMIC_MAX_POSITIONS_MU_SOFT", "0.40"))
DYNAMIC_MAX_POSITIONS_MU_HARD = float(os.getenv("DYNAMIC_MAX_POSITIONS_MU_HARD", "0.50"))
DYNAMIC_MAX_POSITIONS_DQ_MED_SOFT = float(os.getenv("DYNAMIC_MAX_POSITIONS_DQ_MED_SOFT", "65.0"))
DYNAMIC_MAX_POSITIONS_DQ_MED_STRONG = float(os.getenv("DYNAMIC_MAX_POSITIONS_DQ_MED_STRONG", "75.0"))
DYNAMIC_MAX_POSITIONS_VOL_PCT = float(os.getenv("DYNAMIC_MAX_POSITIONS_VOL_PCT", "0.25"))
DYNAMIC_MAX_POSITIONS_VOL_BONUS = int(os.getenv("DYNAMIC_MAX_POSITIONS_VOL_BONUS", "1"))

# Gear-up risk budget (daily step adjustments)
GEAR_UP_ENABLED = os.getenv("GEAR_UP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
GEAR_UP_STEP_UP_PCT = float(os.getenv("GEAR_UP_STEP_UP_PCT", "0.10"))
GEAR_UP_STEP_DOWN_PCT = float(os.getenv("GEAR_UP_STEP_DOWN_PCT", "0.15"))
GEAR_UP_MIN_MULT = float(os.getenv("GEAR_UP_MIN_MULT", "0.40"))
GEAR_UP_MAX_MULT = float(os.getenv("GEAR_UP_MAX_MULT", "1.60"))
GEAR_UP_DD_UP_LIMIT_PCT = float(os.getenv("GEAR_UP_DD_UP_LIMIT_PCT", "2.0"))
GEAR_UP_DD_DOWN_LIMIT_PCT = float(os.getenv("GEAR_UP_DD_DOWN_LIMIT_PCT", "4.0"))
GEAR_UP_FEE_BURN_UP_LIMIT_PCT = float(os.getenv("GEAR_UP_FEE_BURN_UP_LIMIT_PCT", "2.0"))

# Data-quality watchdog (logging-only by default)
DQ_WATCHDOG_ENABLED = os.getenv("DQ_WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
DQ_WATCHDOG_LOG_INTERVAL_SEC = int(os.getenv("DQ_WATCHDOG_LOG_INTERVAL_SEC", "60"))
DQ_WATCHDOG_OB_STALE_MAJOR_MS = int(os.getenv("DQ_WATCHDOG_OB_STALE_MAJOR_MS", "8000"))
DQ_WATCHDOG_OB_STALE_ALT_MS = int(os.getenv("DQ_WATCHDOG_OB_STALE_ALT_MS", "15000"))
DQ_WATCHDOG_LIQMAP_STALE_MS = int(os.getenv("DQ_WATCHDOG_LIQMAP_STALE_MS", "60000"))
DQ_WATCHDOG_LIQ_UPDATED_STALE_MS = int(os.getenv("DQ_WATCHDOG_LIQ_UPDATED_STALE_MS", "120000"))

# Binance USDS-M Futures per-symbol MIN_NOTIONAL (USD) for our traded universe.
# Used by the trainer contract builder to avoid emitting orders below exchange minimums
# (e.g., BTCUSDT requires $100 min notional).
BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL = {
    "BTCUSDT": 100.0,
    "ETHUSDT": 20.0,
    "LINKUSDT": 20.0,
    "LTCUSDT": 20.0,
}

# ============================================================================
# EVENT-DRIVEN PREDICTIONS (B2 Enhancement)
# ============================================================================
# Enable event-driven prediction trigger (trigger on new data arrival)
ENABLE_EVENT_DRIVEN_PREDICTIONS = os.getenv("ENABLE_EVENT_DRIVEN_PREDICTIONS", "true").lower() == "true"

# Redis channel for feature update notifications
FEATURE_UPDATE_CHANNEL = os.getenv("FEATURE_UPDATE_CHANNEL", "features:updated")

# Debounce window (seconds) - coalesce rapid updates into single prediction
# Set to 0 for immediate trigger, >0 to batch rapid updates
EVENT_PREDICTION_DEBOUNCE_SEC = float(os.getenv("EVENT_PREDICTION_DEBOUNCE_SEC", "0.5"))

# Maximum event-driven predictions per minute (rate limiting)
EVENT_PREDICTION_MAX_PER_MIN = int(os.getenv("EVENT_PREDICTION_MAX_PER_MIN", "30"))

# Keep interval-based predictions as fallback/safety net
# When event-driven is enabled, interval acts as a heartbeat/catch-all
EVENT_PREDICTION_KEEP_INTERVAL = os.getenv("EVENT_PREDICTION_KEEP_INTERVAL", "true").lower() == "true"

# ============================================================================
# DECONFLICTION SETTINGS (C1/C2 Enhancement)
# ============================================================================
# Deconfliction mode: "trainer" (original) or "immediate" (publish immediately, trader handles)
DECONFLICTION_MODE = os.getenv("DECONFLICTION_MODE", "trainer")

# Signal aggregation window (seconds) - how long to buffer signals before deconfliction
# C1: Reduced from 30s to 5s for faster response
SIGNAL_AGGREGATION_WINDOW_SEC = float(os.getenv("SIGNAL_AGGREGATION_WINDOW_SEC", "5.0"))

# ============================================================================
# REGRESSION-PROOF ASSERTIONS
# ============================================================================
# These assertions validate critical invariants at import time.
# If any fail, the system will not start (fail-fast).

def _validate_config_invariants():
    """Validate critical config invariants at startup"""
    errors = []
    
    # 1. Action codes must remain 0-6 for HedgeAction compatibility
    valid_action_codes = set(range(7))  # 0, 1, 2, 3, 4, 5, 6
    
    # 2. OPEN_HEDGE_* must NOT be in OPEN_RISK category
    open_risk_actions = ACTION_CATEGORIES.get('OPEN_RISK', [])
    hedge_actions = ACTION_CATEGORIES.get('HEDGE', [])
    for action in hedge_actions:
        if action in open_risk_actions:
            errors.append(f"CRITICAL: {action} is in both HEDGE and OPEN_RISK categories!")
    
    # 3. Confidence thresholds must be 0-1 range
    conf_vars = [
        ('SIGNAL_CONFIDENCE_MIN', SIGNAL_CONFIDENCE_MIN),
        ('MIN_TRADING_CONFIDENCE', MIN_TRADING_CONFIDENCE),
        ('MIN_CLOSE_CONFIDENCE', MIN_CLOSE_CONFIDENCE),
        ('MIN_FLIP_CONFIDENCE', MIN_FLIP_CONFIDENCE),
        ('MIN_CONF_ENTRY', MIN_CONF_ENTRY),
        ('MIN_CONF_EXIT', MIN_CONF_EXIT),
    ]
    for name, value in conf_vars:
        if not (0.0 <= value <= 1.0):
            errors.append(f"CRITICAL: {name}={value} is not in [0, 1] range!")
    
    # 4. Margin caps must be positive and sane
    margin_vars = [
        ('MAX_MARGIN_UTIL_LONG_PCT', MAX_MARGIN_UTIL_LONG_PCT, 5, 100),
        ('MAX_MARGIN_UTIL_SHORT_PCT', MAX_MARGIN_UTIL_SHORT_PCT, 5, 100),
        ('MAX_MARGIN_UTIL_TOTAL_PCT', MAX_MARGIN_UTIL_TOTAL_PCT, 10, 200),  # >100% valid for hedging (long+short)
        ('MAX_MARGIN_UTIL_OPEN_PCT', MAX_MARGIN_UTIL_OPEN_PCT, 10, 100),
        ('MAX_MARGIN_UTIL_HEDGE_PCT', MAX_MARGIN_UTIL_HEDGE_PCT, 10, 100),
    ]
    for name, value, min_val, max_val in margin_vars:
        if not (min_val <= value <= max_val):
            errors.append(f"CRITICAL: {name}={value} is not in [{min_val}, {max_val}] range!")
    
    # 5. Protective actions must include all exit types
    protective = ACTION_CATEGORIES.get('PROTECTIVE', [])
    required_protective = ['CLOSE_LONG', 'CLOSE_SHORT', 'STOP_LOSS', 'TAKE_PROFIT']
    for action in required_protective:
        if action not in protective:
            errors.append(f"CRITICAL: {action} must be in PROTECTIVE category!")
    
    # Report errors
    if errors:
        import logging
        logger = logging.getLogger(__name__)
        for err in errors:
            logger.error(err)
        raise ValueError(f"Config invariant violations: {len(errors)} errors - {errors}")
    
    return True

# Run validation on import (fail-fast)
try:
    _validate_config_invariants()
except Exception as e:
    import sys
    print(f"[CONFIG] ⚠️ Config validation warning: {e}", file=sys.stderr)
    # Don't raise - allow system to start but log warning
    # In production, you may want to raise to enforce fail-fast

# ============================================================================
# ENTERPRISE MODULES - Hedge-Fund Grade Enhancements
# ============================================================================

# --- Mixture-of-Experts (MoE) Router ---
MOE_ENABLED = os.getenv("MOE_ENABLED", "false").lower() in ("1", "true", "yes")
MOE_NUM_EXPERTS = int(os.getenv("MOE_NUM_EXPERTS", "4"))            # calm, normal, fast, impulse
MOE_HIDDEN_DIM = int(os.getenv("MOE_HIDDEN_DIM", "128"))
MOE_ROUTER_INPUT_DIM = int(os.getenv("MOE_ROUTER_INPUT_DIM", "12"))  # regime primitives
MOE_TEMPERATURE = float(os.getenv("MOE_TEMPERATURE", "1.0"))
MOE_TOP_K = int(os.getenv("MOE_TOP_K", "2"))                        # top-k experts per sample
MOE_LOAD_BALANCE_COEFF = float(os.getenv("MOE_LOAD_BALANCE_COEFF", "0.01"))

# --- Uncertainty Estimation ---
UNCERTAINTY_ENABLED = os.getenv("UNCERTAINTY_ENABLED", "true").lower() in ("1", "true", "yes")
UNCERTAINTY_NUM_HEADS = int(os.getenv("UNCERTAINTY_NUM_HEADS", "5"))  # ensemble heads
UNCERTAINTY_MC_PASSES = int(os.getenv("UNCERTAINTY_MC_PASSES", "10"))  # MC dropout passes
UNCERTAINTY_DROPOUT_RATE = float(os.getenv("UNCERTAINTY_DROPOUT_RATE", "0.1"))
UNCERTAINTY_SIZING_FACTOR = float(os.getenv("UNCERTAINTY_SIZING_FACTOR", "0.5"))  # how much to reduce sizing
UNCERTAINTY_HIGH_THRESHOLD = float(os.getenv("UNCERTAINTY_HIGH_THRESHOLD", "0.3"))  # above this = high uncertainty
UNCERTAINTY_BLOCK_THRESHOLD = float(os.getenv("UNCERTAINTY_BLOCK_THRESHOLD", "0.5"))  # above this = block trade

# --- Replay Store (Experience Buffer) ---
REPLAY_ENABLED = os.getenv("REPLAY_ENABLED", "true").lower() in ("1", "true", "yes")
REPLAY_MAX_SIZE = int(os.getenv("REPLAY_MAX_SIZE", "100000"))
REPLAY_REGIME_BUCKETS = int(os.getenv("REPLAY_REGIME_BUCKETS", "4"))  # calm/trend/volatile/crisis
REPLAY_MIN_BUCKET_RATIO = float(os.getenv("REPLAY_MIN_BUCKET_RATIO", "0.1"))
REPLAY_BATCH_SIZE = int(os.getenv("REPLAY_BATCH_SIZE", "256"))
REPLAY_PRIORITY_ALPHA = float(os.getenv("REPLAY_PRIORITY_ALPHA", "0.6"))  # priority exponent
REPLAY_EWC_LAMBDA = float(os.getenv("REPLAY_EWC_LAMBDA", "0.1"))  # elastic weight consolidation
REPLAY_PERSIST_PATH = os.getenv("REPLAY_PERSIST_PATH", "data/replay_store.pkl")

# --- Constrained RL (Lagrangian Reward) ---
CRL_ENABLED = os.getenv("CRL_ENABLED", "true").lower() in ("1", "true", "yes")
CRL_LIQ_BUFFER_MIN_PCT = float(os.getenv("CRL_LIQ_BUFFER_MIN_PCT", "5.0"))
CRL_MARGIN_UTIL_MAX_PCT = float(os.getenv("CRL_MARGIN_UTIL_MAX_PCT", "30.0"))
CRL_DRAWDOWN_MAX_PCT = float(os.getenv("CRL_DRAWDOWN_MAX_PCT", "5.0"))
CRL_LAMBDA_LR = float(os.getenv("CRL_LAMBDA_LR", "0.001"))  # multiplier learning rate
CRL_LAMBDA_INIT = float(os.getenv("CRL_LAMBDA_INIT", "0.1"))  # initial multiplier
CRL_LAMBDA_MAX = float(os.getenv("CRL_LAMBDA_MAX", "10.0"))  # max multiplier cap
CRL_COST_PENALTY_WEIGHT = float(os.getenv("CRL_COST_PENALTY_WEIGHT", "0.3"))  # fee/slippage penalty

# --- Drift Monitor ---
DRIFT_MONITOR_ENABLED = os.getenv("DRIFT_MONITOR_ENABLED", "true").lower() in ("1", "true", "yes")
DRIFT_PSI_THRESHOLD = float(os.getenv("DRIFT_PSI_THRESHOLD", "0.25"))  # feature drift alert
DRIFT_KL_THRESHOLD = float(os.getenv("DRIFT_KL_THRESHOLD", "0.15"))   # policy drift alert
DRIFT_WINDOW_SIZE = int(os.getenv("DRIFT_WINDOW_SIZE", "1000"))       # samples in baseline window
DRIFT_CHECK_INTERVAL_SEC = int(os.getenv("DRIFT_CHECK_INTERVAL_SEC", "300"))  # check every 5 min
DRIFT_RETRAIN_TRIGGER = os.getenv("DRIFT_RETRAIN_TRIGGER", "false").lower() in ("1", "true", "yes")
DRIFT_ALERT_COOLDOWN_SEC = int(os.getenv("DRIFT_ALERT_COOLDOWN_SEC", "600"))

# --- Execution Engine ---
EXEC_ENGINE_ENABLED = os.getenv("EXEC_ENGINE_ENABLED", "true").lower() in ("1", "true", "yes")
EXEC_MAKER_SPREAD_BPS = float(os.getenv("EXEC_MAKER_SPREAD_BPS", "3.0"))  # spread threshold for maker
EXEC_TWAP_THRESHOLD_USD = float(os.getenv("EXEC_TWAP_THRESHOLD_USD", "500.0"))  # above this, use TWAP
EXEC_TWAP_SLICES = int(os.getenv("EXEC_TWAP_SLICES", "3"))
EXEC_TWAP_INTERVAL_SEC = float(os.getenv("EXEC_TWAP_INTERVAL_SEC", "10.0"))
EXEC_SLIPPAGE_TRACKING = os.getenv("EXEC_SLIPPAGE_TRACKING", "true").lower() in ("1", "true", "yes")
EXEC_SLIPPAGE_WARN_BPS = float(os.getenv("EXEC_SLIPPAGE_WARN_BPS", "5.0"))
EXEC_URGENCY_DECAY_SEC = float(os.getenv("EXEC_URGENCY_DECAY_SEC", "30.0"))

# ============================================================================
# ADAPTIVE MARGIN DEPLOYMENT v2 — Kill Switches & Config (Mar 2026)
# All 7 adaptive mechanisms are individually toggleable.
# Default: ON (True) — set to False to revert to prior static behavior.
# ============================================================================

# --- P1: Adaptive ROI Kill Budget (replaces static PER_LEG_ROI_KILL_MAX_PER_HOUR cap) ---
# Kill budget scales with portfolio stress / equity and current volatility.
ENABLE_ADAPTIVE_KILL_BUDGET = os.getenv("ENABLE_ADAPTIVE_KILL_BUDGET", "true").lower() in ("1", "true", "yes")
ADAPTIVE_KILL_BUDGET_BASE = int(os.getenv("ADAPTIVE_KILL_BUDGET_BASE", "5"))  # baseline kills/hr

# --- P2: Microstructure-Gated Loss Exit (dead-zone exit via ICG + directional confirmation) ---
# Allows PROFIT_ONLY_BLOCK bypass when ICG says ALLOW_CLOSE AND >=2 of 3 directional
# confirmations (trainer flipped, funding adverse, liq clusters closing in) are true.
ENABLE_MICROSTRUCTURE_LOSS_EXIT = os.getenv("ENABLE_MICROSTRUCTURE_LOSS_EXIT", "true").lower() in ("1", "true", "yes")
MICRO_LOSS_EXIT_MIN_CONFIRMATIONS = int(os.getenv("MICRO_LOSS_EXIT_MIN_CONFIRMATIONS", "2"))  # of 3 (raised back to 2: require stronger evidence before realizing losses)

# --- P2b: Extreme-vol persistent adverse-state de-risking ---
# When EXTREME volatility coexists with adverse microstructure and weak trainer
# alignment for multiple consecutive reads, tighten kill / hedge thresholds so
# trapped legs like RAVEUSDT de-risk faster instead of tying up capital.
EXTREME_VOL_DERISK_PERSIST_ENABLED = os.getenv("EXTREME_VOL_DERISK_PERSIST_ENABLED", "true").lower() in ("1", "true", "yes")
EXTREME_VOL_DERISK_MIN_STREAK = int(os.getenv("EXTREME_VOL_DERISK_MIN_STREAK", "3"))
EXTREME_VOL_DERISK_TTL_SECONDS = int(os.getenv("EXTREME_VOL_DERISK_TTL_SECONDS", "180"))
EXTREME_VOL_DERISK_MAX_TIGHTEN = float(os.getenv("EXTREME_VOL_DERISK_MAX_TIGHTEN", "0.35"))
EXTREME_VOL_DERISK_WEAK_ALIGN_MAX = float(os.getenv("EXTREME_VOL_DERISK_WEAK_ALIGN_MAX", "0.93"))
EXTREME_VOL_DERISK_ADVERSE_MICRO_MIN = float(os.getenv("EXTREME_VOL_DERISK_ADVERSE_MICRO_MIN", "0.45"))

# --- P3: Regime-Scaled Fill Budget (replaces static ANTI_CHURN_FILL_CAP) ---
# Fill budget per symbol scales with move_regime and orderbook depth.
ENABLE_ADAPTIVE_FILL_BUDGET = os.getenv("ENABLE_ADAPTIVE_FILL_BUDGET", "true").lower() in ("1", "true", "yes")

# --- P4: Adaptive Hedge Lock (replaces time-based 300s lock with effectiveness score) ---
# Hedge lock maintained only while hedge is measurably effective at reducing main-leg risk.
ENABLE_ADAPTIVE_HEDGE_LOCK = os.getenv("ENABLE_ADAPTIVE_HEDGE_LOCK", "true").lower() in ("1", "true", "yes")

# --- P5: Cluster Density-Weighted Sizing (liquidation cluster strength modulates margin) ---
# Sizing factor: 1/(1 + cluster_pressure * leverage/ref_leverage)
ENABLE_LIQ_CLUSTER_SIZING = os.getenv("ENABLE_LIQ_CLUSTER_SIZING", "true").lower() in ("1", "true", "yes")

# --- P6: Microstructure Readiness Score for Scale-In ---
# Scale-in (INCREASE/ADD) requires depth adequacy, flow alignment, low spoof risk.
ENABLE_MICRO_SCALE_IN_GATE = os.getenv("ENABLE_MICRO_SCALE_IN_GATE", "true").lower() in ("1", "true", "yes")

# --- P7: Velocity-Aware Kill Confirmation (replaces fixed 3-tick streak) ---
# Kill urgency computed from roi_severity * leverage + adverse_flow - recovery_signal.
ENABLE_VELOCITY_AWARE_KILL = os.getenv("ENABLE_VELOCITY_AWARE_KILL", "true").lower() in ("1", "true", "yes")

# ============================================================================
# TIER 1/2 LEVERAGE BIAS: BTC/ETH/SOL should prefer the HIGHER end of their
# leverage range due to better liquidity and tighter spreads.
# This floor % of the tier range ensures these symbols don't get pushed to min_leverage
# by moderate risk inputs. E.g., 0.60 → at least 60% of (max-min) range above min.
# ============================================================================
LEVERAGE_TIER1_BIAS_FLOOR = float(os.getenv("LEVERAGE_TIER1_BIAS_FLOOR", "0.60"))  # BTC/ETH: floor at 60% of range → min 65x for 50-75x tier
LEVERAGE_TIER2_BIAS_FLOOR = float(os.getenv("LEVERAGE_TIER2_BIAS_FLOOR", "0.50"))  # SOL: floor at 50% of range → min 45x for 40-50x tier
LEVERAGE_TIER1_SYMBOLS = [s.strip() for s in os.getenv("LEVERAGE_TIER1_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LEVERAGE_TIER2_SYMBOLS = [s.strip() for s in os.getenv("LEVERAGE_TIER2_SYMBOLS", "SOLUSDT").split(",") if s.strip()]

# ============================================================================
# TP EXPANSION ON STRESS-FAVORABLE MOVES: When orderbook/depth/liq signals
# confirm the move is genuine and in our favor, relax the leverage dampening
# on TP WIDEN to let profit targets expand more aggressively.
# ============================================================================
ENABLE_STRESS_TP_EXPANSION = os.getenv("ENABLE_STRESS_TP_EXPANSION", "true").lower() in ("1", "true", "yes")
# Minimum widen_lev_factor when stress confirms favorable move (default 0.35 vs normal 0.11 at 94x)
STRESS_TP_WIDEN_LEV_FLOOR = float(os.getenv("STRESS_TP_WIDEN_LEV_FLOOR", "0.35"))

# ============================================================================
# FAVORABLE MOVE ADD-MARGIN (Scale-In on Profit): When price moves in our
# favor and position is profitable, generate INCREASE_LONG/INCREASE_SHORT
# signals to add margin and compound gains.
# ============================================================================
ENABLE_FAVORABLE_ADD_MARGIN = os.getenv("ENABLE_FAVORABLE_ADD_MARGIN", "true").lower() in ("1", "true", "yes")
# Min ROE % to trigger add-margin (must be profitable enough to justify adding)
FAVORABLE_ADD_MARGIN_MIN_ROE = float(os.getenv("FAVORABLE_ADD_MARGIN_MIN_ROE", "8.0"))
# Max ROE % — don't add at extreme profit (likely reversal zone)
FAVORABLE_ADD_MARGIN_MAX_ROE = float(os.getenv("FAVORABLE_ADD_MARGIN_MAX_ROE", "45.0"))
# Additional margin as % of original margin
FAVORABLE_ADD_MARGIN_PCT = float(os.getenv("FAVORABLE_ADD_MARGIN_PCT", "25.0"))
# Cooldown between add-margin signals per symbol (seconds)
FAVORABLE_ADD_MARGIN_COOLDOWN_S = int(os.getenv("FAVORABLE_ADD_MARGIN_COOLDOWN_S", "300"))
# Min confidence from trainer to allow add-margin
FAVORABLE_ADD_MARGIN_MIN_CONF = float(os.getenv("FAVORABLE_ADD_MARGIN_MIN_CONF", "0.70"))

# ============================================================================
# TIGHT RANGE AUTO-HEDGE: When market is in consolidation/range (ADX low,
# VWAP tight, no trend), automatically prefer hedge actions over directional.
# ============================================================================
ENABLE_TIGHT_RANGE_AUTO_HEDGE = os.getenv("ENABLE_TIGHT_RANGE_AUTO_HEDGE", "true").lower() in ("1", "true", "yes")
# ADX threshold below which market is considered "tight range"
TIGHT_RANGE_ADX_THRESHOLD = float(os.getenv("TIGHT_RANGE_ADX_THRESHOLD", "18.0"))
# VWAP distance threshold (%) — price must be within this % of VWAP
TIGHT_RANGE_VWAP_PCT = float(os.getenv("TIGHT_RANGE_VWAP_PCT", "0.20"))

# ============================================================================
# PREFERRED SYMBOL SIGNAL PRIORITY: BTC/ETH/SOL get guaranteed signal
# generation slots and higher confidence floor bypass.
# ============================================================================
ENABLE_PREFERRED_SYMBOL_PRIORITY = os.getenv("ENABLE_PREFERRED_SYMBOL_PRIORITY", "true").lower() in ("1", "true", "yes")
# Confidence discount for priority symbols (they need less confidence to trigger)
PREFERRED_SYMBOL_CONF_DISCOUNT = float(os.getenv("PREFERRED_SYMBOL_CONF_DISCOUNT", "0.03"))
# Min signals per cycle for priority symbols (even if other symbols score higher)
PREFERRED_SYMBOL_MIN_SIGNALS = int(os.getenv("PREFERRED_SYMBOL_MIN_SIGNALS", "1"))

# ============================================================================
# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE REDESIGN v2 FIXES (March 2026)
# Evidence-based fixes from executed_signals forensics.
# Each fix has an independent kill switch defaulting ON.
# ═══════════════════════════════════════════════════════════════════════════════
# ============================================================================

# ── FIX 1: ATR-Based TP Distance ─────────────────────────────────────────────
# Replace flat leverage-scaled TP with ATR-based distances. Old TP=0.75% at
# 75x; new TP=5-15% based on actual volatility. Kill switch ON by default.
ATR_TP_ENABLED = os.getenv("ATR_TP_ENABLED", "true").lower() in ("1", "true", "yes")
ATR_TP_MULTIPLIER_MAP = {
    "CALM": 1.5, "RANGE": 1.5, "NORMAL": 2.5, "FAST": 3.5,
    "IMPULSE": 5.0, "BREAKOUT": 6.0, "TRENDING": 4.0,
}
ATR_TP_SOURCE_TF = os.getenv("ATR_TP_SOURCE_TF", "15m")
ATR_TP_ABSOLUTE_FLOOR_PCT = float(os.getenv("ATR_TP_ABSOLUTE_FLOOR_PCT", "2.0"))
ATR_TP_ABSOLUTE_CEILING_PCT = float(os.getenv("ATR_TP_ABSOLUTE_CEILING_PCT", "30.0"))

# ── FIX 2: TP Ratchet-Down Block ─────────────────────────────────────────────
# Once a TP is set, it can only WIDEN (move away from entry), never tighten.
# Blocks the SET_TAKE_PROFIT flood (31% of signals) from pulling TP closer.
TP_RATCHET_DOWN_BLOCK_ENABLED = os.getenv("TP_RATCHET_DOWN_BLOCK_ENABLED", "true").lower() in ("1", "true", "yes")

# ── FIX 3: ROI Kill ATR Floor ────────────────────────────────────────────────
# ROI kill threshold must be at least 1.5x ATR away in price terms so normal
# volatility can't trigger it. At 75x with 5% ATR, floor = 112% ROI not 10%.
ROI_KILL_ATR_FLOOR_ENABLED = os.getenv("ROI_KILL_ATR_FLOOR_ENABLED", "true").lower() in ("1", "true", "yes")
ROI_KILL_ATR_FLOOR_MULTIPLIER = float(os.getenv("ROI_KILL_ATR_FLOOR_MULTIPLIER", "1.5"))
ROI_KILL_ATR_SOURCE_TF = os.getenv("ROI_KILL_ATR_SOURCE_TF", "15m")

# ── FIX 4: Signal Dedup Guard ────────────────────────────────────────────────
# Redis SET NX before execution — prevents 150+ duplicate signal executions.
DEDUP_GUARD_ENABLED = os.getenv("DEDUP_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")
DEDUP_GUARD_TTL_SECONDS = int(os.getenv("DEDUP_GUARD_TTL_SECONDS", "120"))

# ── FIX 5: Side-Aware Close Guard ────────────────────────────────────────────
# Verify position side exists before executing close. Prevents ghost closes.
SIDE_GUARD_ENABLED = os.getenv("SIDE_GUARD_ENABLED", "true").lower() in ("1", "true", "yes")

# ── FIX 6: Hard Hold Floor ───────────────────────────────────────────────────
# Minimum position hold time that CANNOT be bypassed except by liquidation
# proximity. PER_LEG_ROI_KILL, GOVERNOR_DELEVERAGE must respect this.
HARD_HOLD_FLOOR_ENABLED = os.getenv("HARD_HOLD_FLOOR_ENABLED", "true").lower() in ("1", "true", "yes")
HARD_HOLD_FLOOR_SECONDS = {
    "1m": 120, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "multi": 600,
}
HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT = float(os.getenv("HARD_HOLD_BYPASS_LIQ_PROXIMITY_PCT", "3.0"))

# ── FIX 7: Dominant source_tf Extraction ──────────────────────────────────────
# Extract dominant timeframe from tf_votes in trainer signal builder so hold
# times and TP distances are TF-aware instead of always "multi"=120s.
DOMINANT_TF_EXTRACTION_ENABLED = os.getenv("DOMINANT_TF_EXTRACTION_ENABLED", "true").lower() in ("1", "true", "yes")
DOMINANT_TF_MIN_WEIGHT = float(os.getenv("DOMINANT_TF_MIN_WEIGHT", "0.30"))

# ── FIX 8: Direction Flip Cooldown ───────────────────────────────────────────
# After emitting a directional signal, opposite direction is blocked for a
# cooldown period per source_tf. Prevents 35s flips.
DIRECTION_FLIP_COOLDOWN_ENABLED = os.getenv("DIRECTION_FLIP_COOLDOWN_ENABLED", "true").lower() in ("1", "true", "yes")
DIRECTION_FLIP_COOLDOWN_SECONDS = {
    "1m": 120, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "multi": 300,
}
DIRECTION_FLIP_NATR_SCALE_ENABLED = os.getenv("DIRECTION_FLIP_NATR_SCALE_ENABLED", "true").lower() in ("1", "true", "yes")
DIRECTION_FLIP_COOLDOWN_NATR_REF_PCT = float(os.getenv("DIRECTION_FLIP_COOLDOWN_NATR_REF_PCT", "1.0"))
DIRECTION_FLIP_COOLDOWN_NATR_MIN_MULT = float(os.getenv("DIRECTION_FLIP_COOLDOWN_NATR_MIN_MULT", "0.35"))
DIRECTION_FLIP_COOLDOWN_NATR_MAX_MULT = float(os.getenv("DIRECTION_FLIP_COOLDOWN_NATR_MAX_MULT", "1.75"))
DIRECTION_FLIP_EARLY_RELEASE_ENABLED = os.getenv("DIRECTION_FLIP_EARLY_RELEASE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
DIRECTION_FLIP_EARLY_RELEASE_MIN_PRED_CONF = float(os.getenv("DIRECTION_FLIP_EARLY_RELEASE_MIN_PRED_CONF", "0.58"))
DIRECTION_FLIP_EARLY_RELEASE_IMB_ABS = float(os.getenv("DIRECTION_FLIP_EARLY_RELEASE_IMB_ABS", "0.12"))
DIRECTION_FLIP_EARLY_RELEASE_FAST_MOVE = float(os.getenv("DIRECTION_FLIP_EARLY_RELEASE_FAST_MOVE", "0.45"))

# ── FIX 9: Governor Protect Winners ──────────────────────────────────────────
# Skip deleveraging positions that are profitable AND aligned with regime.
GOV_DELEVERAGE_PROTECT_WINNERS = os.getenv("GOV_DELEVERAGE_PROTECT_WINNERS", "true").lower() in ("1", "true", "yes")
GOV_DELEVERAGE_PROTECT_MIN_ROE_PCT = float(os.getenv("GOV_DELEVERAGE_PROTECT_MIN_ROE_PCT", "5.0"))

# ── FIX 9b: Trainer-aware deleverage (reduces churn vs model) ────────────────
# Edge/regime votes can disagree with trainer:intent and previously picked a cut leg
# that fights the trainer. Prefer trimming legs that do NOT align with high-confidence
# intent (other leg on same symbol, or another symbol) until hard-emergency MU/IM.
GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT = os.getenv(
    "GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT", "true"
).lower() in ("1", "true", "yes", "on")

# ── FIX 10: Regime-Gated Entry ───────────────────────────────────────────────
# Block entries where zero higher TFs agree with signal direction.
REGIME_GATE_ENABLED = os.getenv("REGIME_GATE_ENABLED", "true").lower() in ("1", "true", "yes")
REGIME_GATE_REQUIRE_MIN_ALIGNMENT = int(os.getenv("REGIME_GATE_REQUIRE_MIN_ALIGNMENT", "1"))

# ── FIX 11: Adaptive Trailing Stop V2 ────────────────────────────────────────
# Trail at ATR behind best price once ROE exceeds activation threshold.
ADAPTIVE_TRAIL_V2_ENABLED = os.getenv("ADAPTIVE_TRAIL_V2_ENABLED", "true").lower() in ("1", "true", "yes")
ADAPTIVE_TRAIL_V2_ACTIVATION_ROE_PCT = float(os.getenv("ADAPTIVE_TRAIL_V2_ACTIVATION_ROE_PCT", "15.0"))
ADAPTIVE_TRAIL_V2_ATR_MULT_MAP = {
    "CALM": 1.0, "RANGE": 1.0, "NORMAL": 1.5, "FAST": 2.0,
    "IMPULSE": 2.5, "BREAKOUT": 3.0, "TRENDING": 2.0,
}
ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT = float(os.getenv("ADAPTIVE_TRAIL_V2_MIN_PROFIT_LOCK_PCT", "50.0"))

# ── FIX 12: Signal Emit Cadence ──────────────────────────────────────────────
# Per-action-type minimum seconds between emitting same action for same symbol.
SIGNAL_EMIT_CADENCE_ENABLED = os.getenv("SIGNAL_EMIT_CADENCE_ENABLED", "true").lower() in ("1", "true", "yes")
SIGNAL_EMIT_CADENCE = {
    "OPEN_RISK": 30, "CLOSE": 15, "HEDGE": 15,
    "SET_TAKE_PROFIT": 60, "HOLD": 60, "PROTECTIVE": 5, "UNKNOWN": 10,
}

# ── FIX 13: Hedge Protect Winners ────────────────────────────────────────────
# Don't hedge a position with ROE > threshold + regime-aligned unless reversal
# confidence exceeds a high bar.
HEDGE_PROTECT_WINNERS_ENABLED = os.getenv("HEDGE_PROTECT_WINNERS_ENABLED", "true").lower() in ("1", "true", "yes")
HEDGE_PROTECT_WINNERS_MIN_ROE_PCT = float(os.getenv("HEDGE_PROTECT_WINNERS_MIN_ROE_PCT", "5.0"))
HEDGE_PROTECT_WINNERS_MIN_REVERSAL_CONF = float(os.getenv("HEDGE_PROTECT_WINNERS_MIN_REVERSAL_CONF", "0.85"))

# ═══════════════════════════════════════════════════════════════════════════════
# MASTER FIX PLAN — Phase 1-7 Configuration
# ═══════════════════════════════════════════════════════════════════════════════

# ── Phase 1: PPO Action Masking Kill-Switch ──────────────────────────────────
# When False (default), position-aware masking of CLOSE/FLIP actions (3-6) is
# DISABLED in the prediction/inference path. This unblocks the model's full
# Discrete(7) action space. The masking was causing permanent -1e9 logits for
# actions 3-6 because the trainer has no live position data (always reads FLAT).
# Orchestrator + trader have their own position guards, so this is safe.
PREDICTION_PATH_POSITION_MASK_ENABLED = os.getenv(
    "PREDICTION_PATH_POSITION_MASK_ENABLED", "false"
).lower() in ("true", "1")

# ── Phase 2: Direction Alignment Gate ────────────────────────────────────────
# Counter-trend entries (e.g., OPEN_SHORT when 4h bias is bullish) require
# additional confidence boost to pass. Helps reduce SHORT bias in bull markets.
DIRECTION_ALIGNMENT_GATE_ENABLED = os.getenv(
    "DIRECTION_ALIGNMENT_GATE_ENABLED", "true"
).lower() in ("true", "1")
# Extra confidence required for counter-trend entries (added to min_conf)
DIRECTION_ALIGNMENT_CONF_BOOST = float(os.getenv("DIRECTION_ALIGNMENT_CONF_BOOST", "0.10"))

# ── Phase 3: Anti-Churn Signal Throttle ──────────────────────────────────────
# Minimum seconds between signals for the same symbol (trainer-side).
# Complements existing SIGNAL_EMIT_CADENCE and orchestrator cooldowns.
TRAINER_MIN_SIGNAL_INTERVAL_SEC = int(os.getenv("TRAINER_MIN_SIGNAL_INTERVAL_SEC", "120"))

# ── Phase 8: BTC Correlation Feature ─────────────────────────────────────────
# Rolling BTC price correlation with each altcoin, injected into features.
BTC_CORRELATION_ENABLED = os.getenv("BTC_CORRELATION_ENABLED", "true").lower() in ("true", "1")
BTC_CORRELATION_WINDOWS = [int(x) for x in os.getenv("BTC_CORRELATION_WINDOWS", "20,60,120").split(",")]
BTC_CORRELATION_CACHE_TTL_SEC = int(os.getenv("BTC_CORRELATION_CACHE_TTL_SEC", "30"))

# ── Hedge-Leg Close Protection (Apr 2026) ────────────────────────────────────
# When both LONG+SHORT legs exist on a symbol (hedge), block closing one leg
# unless confidence >= HEDGE_LEG_CLOSE_MIN_CONF or it's an override (governor/ROI kill).
# This prevents destroying hedge protection by closing one leg at a loss.
HEDGE_LEG_CLOSE_PROTECTION_ENABLED = os.getenv("HEDGE_LEG_CLOSE_PROTECTION_ENABLED", "true").lower() in ("true", "1")
HEDGE_LEG_CLOSE_MIN_CONF = float(os.getenv("HEDGE_LEG_CLOSE_MIN_CONF", "0.90"))  # need 90%+ to break a hedge
HEDGE_LEG_CLOSE_SURVIVAL_ROI = float(os.getenv("HEDGE_LEG_CLOSE_SURVIVAL_ROI", "-25.0"))  # only bypass for extreme losses

# ==============================================================================
# ALT-SEASON MOMENTUM REGIME (Apr 2026)
# ==============================================================================
# Detects per-symbol momentum surges (70-80%+ alt moves) and adapts:
#  - Wider TP caps to let winners run through extended moves
#  - Wider trailing stops to survive normal retracements in trending markets
#  - Trail loosening when trend resumes after consolidation
#  - Longer ride-move TTL to keep TP suppressed during multi-hour surges
#  - Faster/larger position scaling into profitable trending positions
#  - Shifted profit-lock curve so it doesn't choke early
#
# Safety: All changes are gated by MOMENTUM_REGIME_ENABLED kill switch.
# Defaults are conservative. Each sub-feature has its own enable flag.
# Detection uses ATR expansion + price velocity + volume, NOT prediction.
# ==============================================================================

# ── Master kill switch ──
MOMENTUM_REGIME_ENABLED = os.getenv("MOMENTUM_REGIME_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Detection thresholds (per-symbol, computed from market data) ──
# Price move % over lookback window to trigger momentum regime
MOMENTUM_REGIME_PRICE_MOVE_PCT = float(os.getenv("MOMENTUM_REGIME_PRICE_MOVE_PCT", "8.0"))  # 8% price move in lookback
# ATR expansion ratio (current ATR / 20-period avg ATR) to confirm volatility surge
MOMENTUM_REGIME_ATR_EXPANSION = float(os.getenv("MOMENTUM_REGIME_ATR_EXPANSION", "1.8"))  # ATR 1.8x above normal
# Lookback window in minutes for price move detection
MOMENTUM_REGIME_LOOKBACK_MINS = int(os.getenv("MOMENTUM_REGIME_LOOKBACK_MINS", "240"))  # 4 hours
# Minimum ADX to confirm directional strength (not just vol expansion)
MOMENTUM_REGIME_MIN_ADX = float(os.getenv("MOMENTUM_REGIME_MIN_ADX", "25.0"))
# Redis key TTL for momentum regime flag (auto-expires if not refreshed)
MOMENTUM_REGIME_TTL_SEC = int(os.getenv("MOMENTUM_REGIME_TTL_SEC", "900"))  # 15 min, re-evaluated each cycle

# ── TP adjustments when momentum regime active ──
# Dynamic TP max raises from DYNAMIC_TP_MAX_PCT to this value
MOMENTUM_TP_MAX_PCT = float(os.getenv("MOMENTUM_TP_MAX_PCT", "80.0"))  # Allow up to 80% ROI TP in momentum
# TP floor also raises to prevent premature exits
MOMENTUM_TP_MIN_PCT = float(os.getenv("MOMENTUM_TP_MIN_PCT", "8.0"))  # Minimum 8% TP floor in momentum

# ── Trailing stop adjustments when momentum regime active ──
# Trail distance multiplier (applied on top of dynamic trail params)
MOMENTUM_TRAIL_DISTANCE_MULT = float(os.getenv("MOMENTUM_TRAIL_DISTANCE_MULT", "2.5"))  # 2.5x wider trails
# Trail activation raised to let positions run further before arming
MOMENTUM_TRAIL_ACTIVATION_MULT = float(os.getenv("MOMENTUM_TRAIL_ACTIVATION_MULT", "2.0"))  # Activate at 2x normal ROE
# Allow trail to LOOSEN (widen) when price resumes trending after consolidation
MOMENTUM_TRAIL_LOOSEN_ENABLED = os.getenv("MOMENTUM_TRAIL_LOOSEN_ENABLED", "true").lower() in ("true", "1", "yes")
# Max trail loosening factor (can't widen beyond this multiple of initial trail distance)
MOMENTUM_TRAIL_LOOSEN_MAX_FACTOR = float(os.getenv("MOMENTUM_TRAIL_LOOSEN_MAX_FACTOR", "1.5"))  # Can widen up to 50% from current

# ── Ride-move TTL extension in momentum ──
# When momentum regime active, ride-move flag lasts much longer
MOMENTUM_RIDE_MOVE_TTL_SEC = int(os.getenv("MOMENTUM_RIDE_MOVE_TTL_SEC", "3600"))  # 1 hour (vs 10 min normal)

# ── Profit-lock curve shift in momentum ──
# Start profit-lock later (don't choke early gains)
MOMENTUM_PROFIT_LOCK_MIN_ROE = float(os.getenv("MOMENTUM_PROFIT_LOCK_MIN_ROE", "15.0"))  # Start at 15% ROE (vs 2% normal)
# Lower minimum lock fraction (allow more giveback room for retracements)
MOMENTUM_PROFIT_LOCK_MIN_FRAC = float(os.getenv("MOMENTUM_PROFIT_LOCK_MIN_FRAC", "0.15"))  # Lock at least 15% (vs 25% normal)
# Loosen multiplier override for strong trends
MOMENTUM_PROFIT_LOCK_LOOSEN_MULT = float(os.getenv("MOMENTUM_PROFIT_LOCK_LOOSEN_MULT", "1.50"))  # More giveback room (vs 1.20)

# ── Position scaling boost in momentum ──
# Higher per-increment cap when adding to winners in momentum
MOMENTUM_SCALE_MAX_INCREMENT = float(os.getenv("MOMENTUM_SCALE_MAX_INCREMENT", "150.0"))  # $150 (vs $50 normal)
# Shorter cooldown between scaling proposals
MOMENTUM_SCALE_COOLDOWN_SECS = float(os.getenv("MOMENTUM_SCALE_COOLDOWN_SECS", "60.0"))  # 1 min (vs 2 min normal)
# Higher margin fraction per scaling cycle
MOMENTUM_SCALE_MARGIN_FRAC = float(os.getenv("MOMENTUM_SCALE_MARGIN_FRAC", "0.25"))  # 25% of margin (vs 15% normal)
# Relaxed directional skew guard (allow more asymmetry in momentum)
MOMENTUM_SCALE_SKEW_LIMIT = float(os.getenv("MOMENTUM_SCALE_SKEW_LIMIT", "8.0"))  # 8x skew (vs 4x normal)

# ==========================================================================
# HEDGE SELECTIVE UNWIND (Apr 2026) — PRIMARY MODE
# Close ONLY the losing leg when the winner is strong enough to cover it.
# Winner keeps running with its trailing stop — this is the smart play in
# trending markets where coins move 3-5% routinely.
# Example: LONG +11% ($21), SHORT -22% ($-7) → close only SHORT, LONG runs.
# ==========================================================================
HEDGE_SELECTIVE_UNWIND_ENABLED = os.getenv("HEDGE_SELECTIVE_UNWIND_ENABLED", "false").lower() in ("true", "1", "yes")  # ❌ DISABLED Apr 15: defeats hedging purpose per user
# Winner leg must have ROI >= this to prove it's in a real move (not noise)
HEDGE_SELECTIVE_UNWIND_MIN_WINNER_ROI = float(os.getenv("HEDGE_SELECTIVE_UNWIND_MIN_WINNER_ROI", "8.0"))
# Winner PnL must be >= COVER_RATIO * abs(loser PnL) — net pair must be solidly positive
HEDGE_SELECTIVE_UNWIND_MIN_COVER_RATIO = float(os.getenv("HEDGE_SELECTIVE_UNWIND_MIN_COVER_RATIO", "1.5"))
# Don't close loser if it's too deeply underwater (might bounce back)
HEDGE_SELECTIVE_UNWIND_MAX_LOSER_ROI = float(os.getenv("HEDGE_SELECTIVE_UNWIND_MAX_LOSER_ROI", "60.0"))
# Minimum net pair PnL in USD to allow selective unwind (anti-noise)
HEDGE_SELECTIVE_UNWIND_MIN_NET_USD = float(os.getenv("HEDGE_SELECTIVE_UNWIND_MIN_NET_USD", "5.0"))
# Cooldown between selective unwind attempts per symbol (seconds)
HEDGE_SELECTIVE_UNWIND_COOLDOWN_SEC = float(os.getenv("HEDGE_SELECTIVE_UNWIND_COOLDOWN_SEC", "600.0"))

# ==========================================================================
# HEDGE FULL UNWIND — close BOTH legs (very high bar, last resort)
# Only fires when net profit is very substantial. In trending markets
# it's almost always better to use selective unwind above and let the
# winner keep running. This is a safety net for stagnant pairs.
# ==========================================================================
HEDGE_NET_PROFIT_UNWIND_ENABLED = os.getenv("HEDGE_NET_PROFIT_UNWIND_ENABLED", "true").lower() in ("true", "1", "yes")
# Minimum net ROI to close BOTH legs — very high bar (was 2%, now 10%)
HEDGE_NET_PROFIT_UNWIND_MIN_NET_ROI_PCT = float(os.getenv("HEDGE_NET_PROFIT_UNWIND_MIN_NET_ROI_PCT", "10.0"))
# Minimum net USD profit to close BOTH legs — substantial (was $5, now $20)
HEDGE_NET_PROFIT_UNWIND_MIN_NET_USD = float(os.getenv("HEDGE_NET_PROFIT_UNWIND_MIN_NET_USD", "20.0"))
# Winner must be at least this ROI to justify closing it (was 3%, now 15%)
HEDGE_NET_PROFIT_UNWIND_MIN_WINNER_ROI = float(os.getenv("HEDGE_NET_PROFIT_UNWIND_MIN_WINNER_ROI", "15.0"))
# Cooldown between full-unwind attempts per symbol (seconds)
HEDGE_NET_PROFIT_UNWIND_COOLDOWN_SEC = float(os.getenv("HEDGE_NET_PROFIT_UNWIND_COOLDOWN_SEC", "600.0"))
# Which leg to close first
HEDGE_NET_PROFIT_UNWIND_CLOSE_ORDER = os.getenv("HEDGE_NET_PROFIT_UNWIND_CLOSE_ORDER", "loser")
# Maximum loser leg ROI (abs) to allow unwind
HEDGE_NET_PROFIT_UNWIND_MAX_LOSER_ROI = float(os.getenv("HEDGE_NET_PROFIT_UNWIND_MAX_LOSER_ROI", "50.0"))

# ==========================================================================
# HEDGE PROTECTION — NET-PAIR BYPASS (Apr 2026)
# When the net pair PnL is positive, allow closing the losing hedge leg
# via stealth stops (bypasses the PROFIT_ONLY block).
# ==========================================================================
HEDGE_PROTECTION_NET_PAIR_BYPASS_ENABLED = os.getenv("HEDGE_PROTECTION_NET_PAIR_BYPASS_ENABLED", "true").lower() in ("true", "1", "yes")
# Min net pair USD profit for the bypass to activate
HEDGE_PROTECTION_NET_PAIR_MIN_USD = float(os.getenv("HEDGE_PROTECTION_NET_PAIR_MIN_USD", "5.0"))

# ==========================================================================
# TA DIRECTION ORACLE — Real indicator-based direction gating (Jun 2026)
# Blocks OPEN_RISK signals that go against strong TA-derived trend direction.
# Uses EMA stack, RSI, MACD, momentum, slope, funding, liquidation data.
# ==========================================================================
TA_ORACLE_GATE_ENABLED = os.getenv("TA_ORACLE_GATE_ENABLED", "true").lower() in ("true", "1", "yes")
# Minimum TA strength (0-1) to block counter-trend trades
TA_ORACLE_MIN_STRENGTH = float(os.getenv("TA_ORACLE_MIN_STRENGTH", "0.25"))
# Enable TA-based reward shaping for PPO learning
TA_ORACLE_REWARD_SHAPING_ENABLED = os.getenv("TA_ORACLE_REWARD_SHAPING_ENABLED", "false").lower() in ("true", "1", "yes")
# Reward shaping weight (how much TA alignment affects reward)
# FIX Apr 17: 0.3→1.5. TA oracle is the PRIMARY learning signal — must dominate MTM noise.
TA_ORACLE_REWARD_WEIGHT = float(os.getenv("TA_ORACLE_REWARD_WEIGHT", "0.03"))
# Penalty for HOLD when TA has a clear directional signal (missed opportunity cost).
# FIX Apr 17: Without this, HOLD always beats trading (0 > negative MTM reward).
# Kill switch: set to 0.0 to disable.
TA_HOLD_INACTION_PENALTY = float(os.getenv("TA_HOLD_INACTION_PENALTY", "0.015"))
# ==========================================================================
# APRIL PLAN v3 — UNIFIED EXIT OVERHAUL + TACTICAL ENTRIES (Apr 17, 2026)
# Master kill switch: SET killswitch:all_april_plan 1 in Redis to revert ALL
# ==========================================================================

# ── MASTER KILL SWITCH (checked at runtime via Redis) ──
APRIL_PLAN_EXITS_ENABLED = os.getenv("APRIL_PLAN_EXITS_ENABLED", "true").lower() in ("true", "1", "yes")

# ── LEVERAGE-NORMALIZED EXIT THRESHOLDS (price-move based) ──
# All ROE thresholds are converted to price-move % internally:
#   effective_roe = price_move_pct * leverage
# This ensures consistent behavior regardless of leverage.
EXIT_PROFIT_LOCK_MIN_PRICE_MOVE_PCT = float(os.getenv("EXIT_PROFIT_LOCK_MIN_PRICE_MOVE_PCT", "0.50"))  # 0.5% price move before profit-lock arms (at 86x=43% ROE, at 20x=10% ROE)
EXIT_TRAIL_ACTIVATION_PRICE_MOVE_PCT = float(os.getenv("EXIT_TRAIL_ACTIVATION_PRICE_MOVE_PCT", "1.0"))  # 1.0% price move to activate trailing
EXIT_TRAIL_DISTANCE_PRICE_PCT = float(os.getenv("EXIT_TRAIL_DISTANCE_PRICE_PCT", "0.40"))  # 0.4% price pullback allowed (ATR-scaled at runtime)
EXIT_TRAIL_CALLBACK_PRICE_PCT = float(os.getenv("EXIT_TRAIL_CALLBACK_PRICE_PCT", "0.25"))  # 0.25% callback to trigger close
EXIT_ROI_KILL_PRICE_MOVE_PCT = float(os.getenv("EXIT_ROI_KILL_PRICE_MOVE_PCT", "-3.0"))  # -3% adverse price move = kill (capped by margin)

# ── TP MINIMUM PROFIT GUARD ──
# Prevents TP from firing when profit is negligible (kills $1 wins)
EXIT_TP_MIN_ROE_PCT = float(os.getenv("EXIT_TP_MIN_ROE_PCT", "8.0"))  # Min 8% ROE before any TP fires (at 86x=0.09% price, at 20x=0.4% price)
EXIT_TP_MIN_PRICE_MOVE_PCT = float(os.getenv("EXIT_TP_MIN_PRICE_MOVE_PCT", "0.15"))  # Min 0.15% price move for TP regardless of leverage

# ── MR_TIGHTEN CAPS (prevent trainer MR from crushing TP to near-entry) ──
EXIT_MR_TIGHTEN_MAX_BLEND = float(os.getenv("EXIT_MR_TIGHTEN_MAX_BLEND", "0.15"))  # Was 0.55 — too aggressive ratchet
EXIT_MR_TIGHTEN_MIN_TP_DIST_PCT = float(os.getenv("EXIT_MR_TIGHTEN_MIN_TP_DIST_PCT", "0.30"))  # TP must stay >= 0.30% from current price (overrides ATR floor)
EXIT_MR_TIGHTEN_COOLDOWN_SEC = int(os.getenv("EXIT_MR_TIGHTEN_COOLDOWN_SEC", "120"))  # 2min cooldown between MR tightens (was every tick ~30s)
EXIT_MR_TIGHTEN_MIN_PROFIT_PCT = float(os.getenv("EXIT_MR_TIGHTEN_MIN_PROFIT_PCT", "0.30"))  # Need 0.30% price profit before MR tighten allowed

# ── ANTI-CHURN GOVERNOR ──
ANTI_CHURN_ENABLED = os.getenv("ANTI_CHURN_ENABLED", "true").lower() in ("true", "1", "yes")
ANTI_CHURN_MAX_TRADES_PER_SYMBOL_PER_HOUR = int(os.getenv("ANTI_CHURN_MAX_TRADES_PER_SYMBOL_PER_HOUR", "4"))
ANTI_CHURN_REENTRY_COOLDOWN_SEC = int(os.getenv("ANTI_CHURN_REENTRY_COOLDOWN_SEC", "180"))  # 3min cooldown after close
ANTI_CHURN_MIN_PROFIT_FEE_RATIO = float(os.getenv("ANTI_CHURN_MIN_PROFIT_FEE_RATIO", "3.0"))  # Expected profit must > 3x fees

# ── TACTICAL ENTRY INTELLIGENCE ──
TACTICAL_ENTRIES_ENABLED = os.getenv("TACTICAL_ENTRIES_ENABLED", "true").lower() in ("true", "1", "yes")
# Liquidation hunt detector
TACTICAL_LIQ_HUNT_DISTANCE_PCT = float(os.getenv("TACTICAL_LIQ_HUNT_DISTANCE_PCT", "3.0"))  # Liq cluster within 3%
TACTICAL_LIQ_HUNT_MIN_STRENGTH = float(os.getenv("TACTICAL_LIQ_HUNT_MIN_STRENGTH", "100.0"))  # $100M+ liquidation volume
TACTICAL_SPOOF_FADE_THRESHOLD = float(os.getenv("TACTICAL_SPOOF_FADE_THRESHOLD", "0.60"))  # Spoof score > 0.60
TACTICAL_FUNDING_SQUEEZE_MULT = float(os.getenv("TACTICAL_FUNDING_SQUEEZE_MULT", "3.0"))  # Funding > 3x normal

# ── TACTICAL POSITION SIZING (conviction-tiered) ──
TACTICAL_SIZING_ENABLED = os.getenv("TACTICAL_SIZING_ENABLED", "true").lower() in ("true", "1", "yes")
TACTICAL_TIER1_SIZE_PCT = float(os.getenv("TACTICAL_TIER1_SIZE_PCT", "8.0"))   # Liq hunt + whale + multi-TF
TACTICAL_TIER2_SIZE_PCT = float(os.getenv("TACTICAL_TIER2_SIZE_PCT", "5.0"))   # Spoof/funding + confirmation
TACTICAL_TIER3_SIZE_PCT = float(os.getenv("TACTICAL_TIER3_SIZE_PCT", "3.0"))   # Single tactical signal
TACTICAL_TIER4_SIZE_PCT = float(os.getenv("TACTICAL_TIER4_SIZE_PCT", "2.0"))   # Basic model signal (current default)

# ── EXIT COORDINATOR ──
EXIT_COORDINATOR_ENABLED = os.getenv("EXIT_COORDINATOR_ENABLED", "true").lower() in ("true", "1", "yes")
EXIT_COORDINATOR_EMERGENCY_LIQ_DIST_PCT = float(os.getenv("EXIT_COORDINATOR_EMERGENCY_LIQ_DIST_PCT", "2.0"))  # Emergency close if liq < 2%
EXIT_COORDINATOR_MIN_HOLD_SEC = int(os.getenv("EXIT_COORDINATOR_MIN_HOLD_SEC", "300"))  # 5 min min hold

# ══════════════════════════════════════════════════════════════════════════════
# HEDGE PAIR COORDINATOR — Net-position-aware enhancement for hedged pairs
# Kill: HEDGE_PAIR_COORDINATOR_ENABLED=false or redis SET killswitch:hedge_pair_coordinator 1
# ══════════════════════════════════════════════════════════════════════════════
HEDGE_PAIR_COORDINATOR_ENABLED = os.getenv("HEDGE_PAIR_COORDINATOR_ENABLED", "true").lower() in ("true", "1", "yes")
HEDGE_PAIR_COORD_COOLDOWN_SEC = float(os.getenv("HEDGE_PAIR_COORD_COOLDOWN_SEC", "300"))  # 5min between actions per symbol
# Max hedge coverage — hedge side must NOT exceed this % of main position margin
HEDGE_PAIR_MAX_COVERAGE_PCT = float(os.getenv("HEDGE_PAIR_MAX_COVERAGE_PCT", "60.0"))  # 60% max coverage
# When trimming, bring hedge back down to this %
HEDGE_PAIR_TARGET_COVERAGE_PCT = float(os.getenv("HEDGE_PAIR_TARGET_COVERAGE_PCT", "35.0"))  # 35% target after trim
# Both-sides-red: close worse leg when net loss exceeds this
HEDGE_PAIR_BOTH_RED_MIN_NET_LOSS = float(os.getenv("HEDGE_PAIR_BOTH_RED_MIN_NET_LOSS", "5.0"))

# ══════════════════════════════════════════════════════════════════════════════
# BILATERAL UNWIND — Detect and close wasteful bilateral positions
# When both LONG+SHORT exist for same symbol and net exposure is near zero
# relative to total margin used, close losing side(s) to free capital.
# Uses live NATR/volatility from Redis to gate decisions.
# Kill: BILATERAL_UNWIND_ENABLED=false
# ══════════════════════════════════════════════════════════════════════════════
BILATERAL_UNWIND_ENABLED = os.getenv("BILATERAL_UNWIND_ENABLED", "true").lower() in ("true", "1", "yes")
BILATERAL_UNWIND_COOLDOWN_SEC = float(os.getenv("BILATERAL_UNWIND_COOLDOWN_SEC", "300"))  # 5min per symbol
# Net exposure ratio threshold: if abs(net_pnl) / total_margin < this, consider unwinding
# NOT static — this is a ceiling; actual threshold is scaled by live NATR
BILATERAL_UNWIND_MAX_WASTE_RATIO = float(os.getenv("BILATERAL_UNWIND_MAX_WASTE_RATIO", "0.15"))

# HEDGE CONTEXT — Shared market awareness layer for all hedge systems
# Kill: HEDGE_CONTEXT_ENABLED=false
HEDGE_CONTEXT_ENABLED = os.getenv("HEDGE_CONTEXT_ENABLED", "true").lower() in ("true", "1", "yes")