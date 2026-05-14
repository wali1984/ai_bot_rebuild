"""
CPU-Only Trading Environment for SubprocVecEnv Workers (ZERO torch dependency)

PURPOSE: Eliminate the 474MB-per-worker torch import overhead that causes OOM
when running 125 SubprocVecEnv workers.

    WITH torch:    508 MB/worker × 125 = 62 GB  → OOM on 123GB system
    WITHOUT torch:  38 MB/worker × 125 =  5 GB  → plenty of headroom

This file is a FAITHFUL numpy-only port of GPUTradingEnvironment
(rl/gpu_environment.py). Observation space, action space, step/reward logic,
and feature extraction are IDENTICAL. The only difference is internal
representation uses numpy arrays instead of torch tensors.

The main process (trainer) still uses torch + CUDA for the PPO policy network.
Only the SubprocVecEnv child workers use this lightweight env.

Created: 2026-04-14  (OOM fix for subproc mode)
"""

import gymnasium as gym
import json
import math
import os
import time
import numpy as np
from typing import Dict, Any, Tuple, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Dynamic symbol loading (no torch dependency)
try:
    from utils.symbol_manager import get_symbols_cached
    SYMBOLS = get_symbols_cached()
except ImportError:
    from config import SYMBOLS

from utils.redis_client import get_redis
from utils.logger import get_logger

# ── Config imports (same as gpu_environment.py) ──────────────────────────
try:
    from config import (
        USE_RISK_ADJUSTED_REWARD,
        TRADE_PENALTY,
        DRAWDOWN_PENALTY,
        PNL_SCALE,
        EQUITY_CURVE_WINDOW,
        TRAIN_PERSISTENT_PENALTIES_ENABLED,
        TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K,
        TRAIN_NEG_LEG_PENALTY_K,
        RL_TRANSACTION_COST,
        RL_TF_ORDINAL_ENABLED,
        RL_LOSS_PENALTY_MULT,
        RL_HOLD_TIME_BONUS,
    )
except ImportError:
    USE_RISK_ADJUSTED_REWARD = False
    TRADE_PENALTY = 0.002
    DRAWDOWN_PENALTY = 0.3
    PNL_SCALE = 100.0
    EQUITY_CURVE_WINDOW = 1000
    TRAIN_PERSISTENT_PENALTIES_ENABLED = False
    TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K = 0.0
    TRAIN_NEG_LEG_PENALTY_K = 0.0
    RL_TRANSACTION_COST = 0.0004
    RL_TF_ORDINAL_ENABLED = True
    RL_LOSS_PENALTY_MULT = 1.5
    RL_HOLD_TIME_BONUS = 0.0001

try:
    from config import (
        RL_MICRO_REWARD_ENABLED,
        RL_MICRO_SPREAD_PENALTY_BPS,
        RL_MICRO_SPREAD_PENALTY_AMOUNT,
        RL_MICRO_SPOOF_PENALTY_THRESHOLD,
        RL_MICRO_SPOOF_PENALTY_AMOUNT,
        RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD,
        RL_MICRO_FAST_MOVE_PENALTY_AMOUNT,
        RL_MICRO_FAVORABLE_EXIT_BONUS,
    )
except ImportError:
    RL_MICRO_REWARD_ENABLED = False
    RL_MICRO_SPREAD_PENALTY_BPS = 10.0
    RL_MICRO_SPREAD_PENALTY_AMOUNT = 0.005
    RL_MICRO_SPOOF_PENALTY_THRESHOLD = 0.5
    RL_MICRO_SPOOF_PENALTY_AMOUNT = 0.008
    RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD = 0.6
    RL_MICRO_FAST_MOVE_PENALTY_AMOUNT = 0.010
    RL_MICRO_FAVORABLE_EXIT_BONUS = 0.003

logger = get_logger("cpu_trading_environment")

try:
    from config import CANONICAL_OBS_DIM as _CFG_OBS_DIM
    CANONICAL_OBS_DIM = _CFG_OBS_DIM
except ImportError:
    CANONICAL_OBS_DIM = 768

_FEATURE_KEY_ORDER_DIR = os.path.join(str(Path(__file__).parent.parent), "data", "feature_key_orders")


def _load_pinned_key_order(symbol: str, tf: str):
    """Load a previously-pinned alphabetical key order for (symbol, tf)."""
    try:
        fpath = os.path.join(_FEATURE_KEY_ORDER_DIR, f"{symbol}_{tf}.json")
        with open(fpath) as f:
            return json.load(f)
    except Exception:
        return None


def _save_pinned_key_order(symbol: str, tf: str, keys: list):
    """Save key order in a per-symbol file (no cross-worker race condition)."""
    try:
        os.makedirs(_FEATURE_KEY_ORDER_DIR, exist_ok=True)
        fpath = os.path.join(_FEATURE_KEY_ORDER_DIR, f"{symbol}_{tf}.json")
        tmp = fpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(keys, f)
        os.replace(tmp, fpath)
    except Exception as e:
        logger.debug("[KEYORDER] Save failed for %s:%s: %s", symbol, tf, e)


class CPUTradingEnvironment(gym.Env):
    """
    Numpy-only Trading Environment for SubprocVecEnv workers.

    Drop-in replacement for GPUTradingEnvironment + TradingEnvironmentWrapper
    that implements gymnasium.Env directly, skipping the torch import chain.

    Observation space: Box(-10, 10, shape=(CANONICAL_OBS_DIM,))
    Action space: Discrete(7)  (7-action hedge space)
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "5m",
        initial_balance: float = 10000.0,
        transaction_cost: float = None,
        max_position: float = 1.0,
        lookback_window: int = 10,
    ):
        super().__init__()

        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost if transaction_cost is not None else RL_TRANSACTION_COST
        self.max_position = max_position
        self.lookback_window = lookback_window

        # Gymnasium spaces (MUST match GPUTradingEnvironment + wrapper)
        self.observation_space = gym.spaces.Box(
            low=-10.0, high=10.0,
            shape=(CANONICAL_OBS_DIM,),
            dtype=np.float32,
        )
        self.action_space = gym.spaces.Discrete(7)

        # State arrays (numpy, matching torch tensors in gpu_environment.py)
        self.positions = np.zeros(1, dtype=np.float32)
        self.entry_prices = np.zeros(1, dtype=np.float32)
        self.current_balance = float(initial_balance)
        self.position_sides = np.zeros(1, dtype=np.float32)
        self.n_symbols = 1

        # Cross-step reward tracking
        self._rw_prev_equity = float(initial_balance)
        self._rw_max_equity = float(initial_balance)

        # Feature key order cache
        self._feature_key_order = None

        # Price cache
        self._step_prices_cache = None
        self._step_prices_cache_id = -1
        self._step_counter = 0

        # Feature cache
        self._last_feature_ts = 0.0
        self._cached_features = None
        self._feature_cache_ttl = float(os.getenv("GPU_ENV_FEATURE_CACHE_SECONDS", "0.5"))
        try:
            self._min_step_seconds = float(os.getenv("GPU_ENV_MIN_STEP_SECONDS", "0.02"))
        except Exception:
            self._min_step_seconds = 0.02
        self._min_step_seconds = max(0.0, min(1.0, self._min_step_seconds))
        self._last_step_walltime = 0.0

        # Feature timestamp telemetry
        self._last_features_ts_ms = 0
        self._last_features_age_ms = -1
        self._last_features_hlen = 0

        # Redis (created lazily)
        self.redis = None
        try:
            from utils.redis_client import get_redis_config
            self._redis_cfg = get_redis_config()
        except Exception:
            self._redis_cfg = None

        # Episode tracking
        self.equity_curve = []
        self.max_equity = initial_balance
        self.prev_action = None
        self.step_count = 0
        self.episode_steps = 0
        self.max_episode_steps = 1000
        self.steps_in_position = 0

        # Realized PnL tracking
        self._last_realized_pnl_usd = 0.0
        self._last_realized_action = ""

        # Equity baseline for persistent penalties
        self._equity_baseline = float(initial_balance)

        # Microstructure cache
        self._cached_micro_raw = None

        # Reward config (lazy-loaded)
        self._rw_cfg_loaded = False
        self._reward_cfg_loaded = False

        logger.info(
            f"CPUTradingEnvironment ready | {symbol}:{timeframe} | "
            f"obs_dim={CANONICAL_OBS_DIM} | tx_cost={self.transaction_cost} | NO TORCH"
        )

    # ── Pickling support (SubprocVecEnv spawn) ───────────────────────────

    def __getstate__(self):
        state = self.__dict__.copy()
        state['redis'] = None
        state['_cached_features'] = None
        state['_feature_key_order'] = None
        state['_rw_cfg_loaded'] = False
        state['_reward_cfg_loaded'] = False
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    # ── Redis ─────────────────────────────────────────────────────────────

    def _ensure_redis(self):
        if getattr(self, 'redis', None) is None:
            try:
                if getattr(self, '_redis_cfg', None):
                    from utils.redis_client import create_redis_from_config
                    self.redis = create_redis_from_config(self._redis_cfg)
                else:
                    self.redis = get_redis()
            except Exception as e:
                logger.warning(f"Redis connection failed in PID {os.getpid()}: {e}")
                self.redis = None
        return self.redis

    # ── Feature extraction (MATCHES gpu_environment.py EXACTLY) ──────────

    @staticmethod
    def _is_feature_metadata_key(key):
        if not key:
            return True
        if key in ("ts_ms", "symbol", "timeframe", "timestamp"):
            return True
        lk = key.lower()
        if "timestamp" in lk:
            return True
        if key.startswith(("portfolio_", "position_", "_acct")):
            return True
        if lk.endswith("_ts") or "_updated_ts" in lk or "_event_ts" in lk:
            return True
        if "_tss_" in lk:
            return True
        if "_col0_" in key:
            return True
        if "staleness" in lk:
            return True
        if lk.endswith("_begin") and ("_data_" in lk or "_kline_" in lk):
            return True
        return False

    @staticmethod
    def _is_pruned_ta_feature(key):
        try:
            from config import ENABLE_TA_FEATURE_PRUNING, TA_FEATURE_WHITELIST_PREFIXES
        except ImportError:
            return False
        if not ENABLE_TA_FEATURE_PRUNING:
            return False
        if not key.startswith("ind_ta_"):
            return False
        ta_name = key[7:]
        for prefix in TA_FEATURE_WHITELIST_PREFIXES:
            if ta_name.startswith(prefix):
                return False
        return True

    @staticmethod
    def _normalize_feature_vector_robust(vec):
        """Robust median/MAD normalization with tanh squash.
        IDENTICAL to GPUTradingEnvironment._normalize_feature_vector_robust"""
        if not vec:
            return vec
        arr = np.array(vec, dtype=np.float32)
        arr[np.abs(arr) > 1e8] = 0.0
        arr = np.clip(arr, -1e6, 1e6)
        median = float(np.nanmedian(arr))
        mad = float(np.nanmedian(np.abs(arr - median)))
        scale = 1.4826 * max(mad, 1e-3)
        arr = (arr - median) / scale
        arr = np.tanh(arr / 3.0) * 3.0
        arr = np.clip(arr, -5.0, 5.0)
        return arr.astype(np.float32).tolist()

    def _get_features(self) -> np.ndarray:
        """Get features for assigned symbol:tf — numpy-only version of get_current_features_gpu."""
        self._ensure_redis()
        self._step_counter += 1

        now = time.time()
        if self._cached_features is not None and (now - self._last_feature_ts) < self._feature_cache_ttl:
            return self._cached_features

        sym = self.symbol or SYMBOLS[0]
        tf = self.timeframe or '5m'

        try:
            if self.redis is None:
                return self._get_default_features()

            redis_key = f"unified_features:{sym}:{tf}"
            raw_hash = self.redis.hgetall(redis_key)

            if not raw_hash:
                logger.debug(f"No features in {redis_key}, using defaults")
                return self._get_default_features()

            fdict = {}
            for k, v in raw_hash.items():
                kk = k.decode('utf-8') if isinstance(k, (bytes, bytearray)) else str(k)
                vv = v.decode('utf-8') if isinstance(v, (bytes, bytearray)) else str(v)
                fdict[kk] = vv

            # Feature timestamp telemetry + staleness guard
            _STALE_FEATURE_MAX_MS = 120_000
            try:
                ts_raw = fdict.get("ts_ms") or fdict.get("timestamp_ms") or fdict.get("timestamp") or "0"
                ts_ms = int(float(ts_raw))
                self._last_features_ts_ms = ts_ms
                if ts_ms > 0:
                    self._last_features_age_ms = int(max(0.0, (time.time() * 1000.0) - float(ts_ms)))
                else:
                    self._last_features_age_ms = -1
            except Exception:
                self._last_features_ts_ms = 0
                self._last_features_age_ms = -1
            if self._last_features_age_ms > _STALE_FEATURE_MAX_MS:
                if self._cached_features is not None:
                    return self._cached_features
                return self._get_default_features()
            try:
                self._last_features_hlen = int(len(fdict))
            except Exception:
                self._last_features_hlen = 0

            # Build or use cached key order (alphabetical, exclude metadata)
            if self._feature_key_order is None:
                pinned = _load_pinned_key_order(sym, tf)
                if pinned:
                    self._feature_key_order = pinned
                    logger.info(
                        f"[TRAIN_FEATURES] Loaded PINNED key order for {sym}:{tf}: "
                        f"{len(self._feature_key_order)} keys, OBS_DIM={CANONICAL_OBS_DIM}"
                    )
                else:
                    keys_set = set()
                    for kk in fdict.keys():
                        if not self._is_feature_metadata_key(kk) and not self._is_pruned_ta_feature(kk):
                            keys_set.add(kk)
                    self._feature_key_order = sorted(keys_set)
                    _save_pinned_key_order(sym, tf, self._feature_key_order)
                    logger.info(
                        f"[TRAIN_FEATURES] Built & pinned key order for {sym}:{tf}: "
                        f"{len(self._feature_key_order)} numeric keys (after TA pruning), "
                        f"OBS_DIM={CANONICAL_OBS_DIM}, first_5={self._feature_key_order[:5]}"
                    )

            # Extract in deterministic order
            numeric_features = []
            for kk in self._feature_key_order:
                try:
                    vv = fdict.get(kk)
                    if vv is None:
                        numeric_features.append(0.0)
                        continue
                    fv = float(vv)
                    numeric_features.append(fv if np.isfinite(fv) else 0.0)
                except (ValueError, TypeError):
                    numeric_features.append(0.0)

            # Normalize (same as prediction path)
            numeric_features = self._normalize_feature_vector_robust(numeric_features)

            # Pad/truncate to CANONICAL_OBS_DIM
            if len(numeric_features) > CANONICAL_OBS_DIM:
                numeric_features = numeric_features[:CANONICAL_OBS_DIM]
            elif len(numeric_features) < CANONICAL_OBS_DIM:
                numeric_features.extend([0.0] * (CANONICAL_OBS_DIM - len(numeric_features)))

            # numpy equivalent of torch.tensor + nan_to_num + clamp
            feature_arr = np.array(numeric_features, dtype=np.float32)
            feature_arr = np.nan_to_num(feature_arr, nan=0.0, posinf=0.0, neginf=0.0)
            feature_arr = np.clip(feature_arr, -5.0, 5.0)

            _nonzero_ct = int(np.sum(np.abs(feature_arr) > 1e-7))
            if _nonzero_ct < 10 and self._cached_features is not None:
                return self._cached_features

            # Cache
            self._cached_features = feature_arr
            self._last_feature_ts = now
            self._cached_micro_raw = {
                'spread_bps': float(fdict.get('ob_ob_spread_bps', 0) or 0),
                'depth_spread': float(fdict.get('depth_spread', 0) or 0),
                'spoof_score': float(fdict.get('depth_spoof_score', 0) or 0),
                'fast_move_score': float(fdict.get('depth_fast_move_score', 0) or 0),
                'fast_move_1m': float(fdict.get('depth_fast_move_1m', 0) or 0),
                'fast_move_5m': float(fdict.get('depth_fast_move_5m', 0) or 0),
                'depth_imbalance': float(fdict.get('depth_imbalance_5', 0) or 0),
                'depth_churn': float(fdict.get('depth_churn_score', 0) or 0),
                'depth_quality': float(fdict.get('depth_quality_score', 0) or 0),
                'depth_vs_tape_divergence': float(fdict.get('depth_vs_tape_divergence', 0) or 0),
                'tape_imbalance_5s': float(fdict.get('tape_imbalance_5s', 0) or 0),
            }

            # Periodic logging
            if not hasattr(self, '_feature_log_counter'):
                self._feature_log_counter = 0
            self._feature_log_counter += 1
            if self._feature_log_counter <= 3 or self._feature_log_counter % 10000 == 0:
                nonzero = int(np.sum(np.abs(feature_arr) > 1e-7))
                logger.info(
                    f"[TRAIN_FEATURES] {sym}:{tf} -> "
                    f"{len(self._feature_key_order)} keys -> {CANONICAL_OBS_DIM}-dim | "
                    f"nonzero={nonzero}/{CANONICAL_OBS_DIM} ({100*nonzero/CANONICAL_OBS_DIM:.1f}%)"
                )

            return feature_arr

        except Exception as e:
            logger.error(f"Error getting features for {sym}:{tf}: {e}")
            return self._get_default_features()

    def _get_default_features(self) -> np.ndarray:
        return np.zeros(CANONICAL_OBS_DIM, dtype=np.float32)

    def _get_state(self) -> np.ndarray:
        """Observation = raw features + TF ordinal + position state.
        IDENTICAL layout to GPUTradingEnvironment.get_state_gpu()."""
        raw_features = self._get_features()

        if raw_features.shape[0] != CANONICAL_OBS_DIM:
            padded = np.zeros(CANONICAL_OBS_DIM, dtype=np.float32)
            n = min(raw_features.shape[0], CANONICAL_OBS_DIM)
            padded[:n] = raw_features[:n]
            raw_features = padded

        # dim -5: TF ordinal
        if RL_TF_ORDINAL_ENABLED:
            tf_ordinal_map = {'1m': 0.0, '5m': 0.25, '15m': 0.5, '1h': 0.75, '4h': 1.0}
            raw_features[CANONICAL_OBS_DIM - 5] = tf_ordinal_map.get(self.timeframe or '5m', 0.5)

        # Position state (last 4 dims)
        pos = float(self.positions[0])
        side = float(self.position_sides[0])
        bal = float(self.current_balance)

        raw_features[CANONICAL_OBS_DIM - 4] = side
        raw_features[CANONICAL_OBS_DIM - 3] = 1.0 if abs(pos) > 1e-8 else 0.0
        raw_features[CANONICAL_OBS_DIM - 2] = (bal / max(self.initial_balance, 1.0)) - 1.0

        if abs(pos) > 1e-8:
            entry = float(self.entry_prices[0])
            if entry > 0:
                price = self._get_current_price()
                pnl_ratio = side * (price - entry) / entry
                raw_features[CANONICAL_OBS_DIM - 1] = max(-1.0, min(1.0, pnl_ratio * 10.0))

        return raw_features

    # ── Price ─────────────────────────────────────────────────────────────

    def _get_price(self, symbol: str) -> float:
        redis = self._ensure_redis()
        if redis is None:
            return 0.0
        try:
            data = redis.get(f"market:{symbol}:1m")
            if data:
                raw = data if isinstance(data, str) else data.decode()
                parsed = json.loads(raw)
                close = float(parsed.get('close', 0.0))
                if close > 0:
                    return close
        except Exception:
            pass
        try:
            raw = redis.get(f"price:{symbol}")
            if raw:
                val = raw.decode() if isinstance(raw, bytes) else str(raw)
                try:
                    parsed = json.loads(val)
                    price = float(parsed.get('price', 0.0))
                    if price > 0:
                        return price
                except (ValueError, TypeError):
                    price = float(val)
                    if price > 0:
                        return price
        except Exception:
            pass
        return 0.0

    def _get_current_price(self) -> float:
        """Get live price for assigned symbol (cached per step)."""
        if (self._step_prices_cache is not None
                and self._step_prices_cache_id == self._step_counter):
            return self._step_prices_cache

        price = max(self._get_price(self.symbol or SYMBOLS[0]), 1e-10)
        self._step_prices_cache = price
        self._step_prices_cache_id = self._step_counter
        return price

    def _calculate_portfolio_value(self) -> float:
        current_price = self._get_current_price()
        side = float(self.position_sides[0])
        pos = float(self.positions[0])
        entry = float(self.entry_prices[0])
        margin_used = pos * entry
        unrealized_pnl = side * pos * (current_price - entry)
        return self.current_balance + margin_used + unrealized_pnl

    # ── Gymnasium interface ───────────────────────────────────────────────

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        self._ensure_redis()

        self.positions[:] = 0.0
        self.entry_prices[:] = 0.0
        self.current_balance = float(self.initial_balance)
        self.position_sides[:] = 0.0

        self._equity_baseline = float(self.initial_balance)
        self.equity_curve = [self.initial_balance]
        self.max_equity = self.initial_balance
        self.prev_action = None
        self.step_count = 0
        self.episode_steps = 0
        self.steps_in_position = 0

        self._rw_prev_equity = float(self.initial_balance)
        self._rw_max_equity = float(self.initial_balance)

        self._cached_features = None
        self._feature_key_order = None
        self._step_prices_cache = None
        self._step_counter = 0

        obs = self._get_state()
        obs = np.clip(obs, -10.0, 10.0)
        return obs, {}

    def step(self, action):
        """Execute one step — IDENTICAL logic to gpu_environment.step_gpu + wrapper."""
        # Throttle
        if self._min_step_seconds > 0:
            try:
                now = time.time()
                last = self._last_step_walltime or 0.0
                if last > 0:
                    dt = now - last
                    if dt < self._min_step_seconds:
                        time.sleep(self._min_step_seconds - dt)
                self._last_step_walltime = time.time()
            except Exception:
                pass

        self.step_count += 1
        self.episode_steps += 1
        self._last_realized_pnl_usd = 0.0
        self._last_realized_action = ""

        action = int(action)

        # ── Lazy-load reward config ──────────────────────────────────
        if not self._rw_cfg_loaded:
            try:
                from config import (
                    RL_REWARD_MTM_ENABLED, RL_REWARD_SCALE, RL_REWARD_CLIP,
                    RL_REWARD_DD_COEFF, RL_REWARD_STATS_INTERVAL,
                    RL_REWARD_EPISODE_END_REALIZE,
                )
                self._rw_mtm = RL_REWARD_MTM_ENABLED
                self._rw_scale = RL_REWARD_SCALE
                self._rw_clip = RL_REWARD_CLIP
                self._rw_dd_coeff = RL_REWARD_DD_COEFF
                self._rw_stats_interval = RL_REWARD_STATS_INTERVAL
                self._rw_episode_end_realize = RL_REWARD_EPISODE_END_REALIZE
            except Exception:
                self._rw_mtm = True
                self._rw_scale = 100.0
                self._rw_clip = 5.0
                self._rw_dd_coeff = 0.05
                self._rw_stats_interval = 2048
                self._rw_episode_end_realize = True
            self._rw_cfg_loaded = True
            self._rw_sum = 0.0
            self._rw_abs_sum = 0.0
            self._rw_nonzero = 0
            self._rw_n = 0
            self._rw_prev_equity = float(self.initial_balance)
            print(f"[REWARD_INIT] pid={os.getpid()} MTM={self._rw_mtm} scale={self._rw_scale} "
                  f"clip={self._rw_clip} dd_coeff={self._rw_dd_coeff}", flush=True)

        # ── Action masking with penalty feedback (FIX Apr 14 2026) ─────
        # Previous: silently converted invalid actions to HOLD → PPO attributed
        # HOLD reward to the wrong action, causing gradient confusion.
        # New: Track whether action was masked so we can apply INVALID penalty.
        pos = float(self.positions[0])
        side = float(self.position_sides[0])
        _is_flat = abs(pos) < 1e-8
        _was_masked = False
        if _is_flat and action in (3, 4, 5, 6):
            _was_masked = True
            action = 0
        elif not _is_flat:
            if side > 0 and action in (2, 4, 5):
                _was_masked = True
                action = 0
            elif side < 0 and action in (1, 3, 6):
                _was_masked = True
                action = 0

        trade_executed = (self.prev_action is not None and action != self.prev_action and action != 0)

        # Execute trade
        trade_reward = self._execute_trades_7action(action)

        # FIX Apr 14: Apply invalid-action penalty for masked actions
        # so PPO learns which actions are impossible in each state
        if _was_masked:
            trade_reward = -0.005  # Override with explicit invalid-action signal

        # ── Direction-aware entry bonus ──────────────────────────────
        try:
            _dir_bonus_scale = float(getattr(self, '_rl_direction_bonus', None) or 0.005)
            if _dir_bonus_scale > 0 and action in (1, 2, 5, 6):
                cur_price = self._get_current_price()
                prev_price = float(getattr(self, '_prev_step_price', cur_price) or cur_price)
                if prev_price > 0 and cur_price > 0:
                    price_ret = (cur_price - prev_price) / prev_price
                    if action in (1, 5):
                        trade_reward += _dir_bonus_scale * (1.0 if price_ret > 0.0001 else (-0.5 if price_ret < -0.0001 else 0.0))
                    elif action in (2, 6):
                        trade_reward += _dir_bonus_scale * (1.0 if price_ret < -0.0001 else (-0.5 if price_ret > 0.0001 else 0.0))
                self._prev_step_price = cur_price
        except Exception:
            pass

        # ── Action-switch penalty ────────────────────────────────────
        if trade_executed and getattr(self, '_ACTION_SWITCH_PENALTY', 0.015) > 0:
            trade_reward -= self._ACTION_SWITCH_PENALTY

        # ── Microstructure reward shaping ────────────────────────────
        if RL_MICRO_REWARD_ENABLED and action != 0:
            try:
                micro_adj = self._microstructure_reward_adjustment(action)
                if abs(micro_adj) > 1e-8:
                    trade_reward += micro_adj
            except Exception:
                pass

        # Hold-time tracking
        if abs(float(self.positions[0])) > 1e-8:
            self.steps_in_position += 1
        else:
            self.steps_in_position = 0

        # Portfolio value
        equity_now = self._calculate_portfolio_value()

        # ── Cross-step MTM reward ────────────────────────────────────
        if self._rw_mtm:
            initial_bal = float(self.initial_balance)
            equity_prev = self._rw_prev_equity
            safe_prev = max(equity_prev, initial_bal * 0.01)
            safe_now = max(equity_now, initial_bal * 0.01)
            r_mtm = math.log(safe_now / safe_prev)

            self._rw_max_equity = max(self._rw_max_equity, equity_now)
            # FIX Apr 2026: Faster decay (0.995) prevents permanent equity ceiling
            self._rw_max_equity = self._rw_max_equity * 0.995 + equity_now * 0.005
            dd_pct = max(0.0, (self._rw_max_equity - equity_now) / max(self._rw_max_equity, 1.0))
            r_dd = -self._rw_dd_coeff * dd_pct

            raw_reward = r_mtm + r_dd
            if abs(trade_reward) > 1e-6:
                # FIX Apr 17: With TA reward removed, trade_reward shaping
                # (open/close/hold bonuses) can be higher without drowning MTM.
                # 0.3 keeps trade signals meaningful vs log-return MTM.
                raw_reward += trade_reward * 0.3

            # ── Exploration bonus — DISABLED Apr 17 2026 ─────────────
            # Was adding up to 15.0 per step (0.15 * scale 100), drowning MTM signal.
            # PPO's ent_coef already handles exploration via entropy bonus in the
            # policy gradient loss. No need for reward-based exploration.

            # ── TA ORACLE REWARD SHAPING — DISABLED Apr 17 2026 ────────
            # ROOT CAUSE FIX: TA reward dominated MTM by ~240x, causing PPO to
            # optimize for "match TA direction" instead of actual profitable
            # trading. After 7400 loops: reward=641 but win_rate=0.0%.
            # The policy must learn from ACTUAL price movements (MTM) not TA.
            # Kill switch: set TA_ORACLE_REWARD_SHAPING_ENABLED=true in config
            try:
                import config as _cfg
                _ta_rw_enabled = bool(getattr(_cfg, "TA_ORACLE_REWARD_SHAPING_ENABLED", False))
                if _ta_rw_enabled:
                    _ta_rw_weight = float(getattr(_cfg, "TA_ORACLE_REWARD_WEIGHT", 0.03))
                    _ta_hold_penalty = float(getattr(_cfg, "TA_HOLD_INACTION_PENALTY", 0.015))
                    from rl.ta_direction_oracle import get_ta_direction_cached
                    _ta_rc = getattr(self, "redis", None)
                    _ta_sym = getattr(self, "symbol", "")
                    if _ta_rc and _ta_sym and _ta_rw_weight > 0:
                        _ta_res = get_ta_direction_cached(_ta_rc, _ta_sym)
                        _ta_dir = _ta_res.get("direction", 0)
                        _ta_str = _ta_res.get("strength", 0.0)
                        if _ta_dir != 0 and _ta_str >= 0.15:
                            if action == 0:
                                raw_reward -= _ta_hold_penalty * _ta_str
                            else:
                                _act_dir = 0
                                if action in (1, 5):    _act_dir = 1
                                elif action in (2, 6):  _act_dir = -1
                                elif action == 3:       _act_dir = -1
                                elif action == 4:       _act_dir = 1
                                if _act_dir != 0:
                                    _alignment = 1.0 if _act_dir == _ta_dir else -1.0
                                    raw_reward += _alignment * _ta_str * _ta_rw_weight
            except Exception:
                pass

            scaled = raw_reward * self._rw_scale
            reward = max(-self._rw_clip, min(self._rw_clip, scaled))
        else:
            reward = trade_reward

        self._step_equity_delta = equity_now - self._rw_prev_equity
        self._rw_prev_equity = equity_now

        # Reward stats
        self._rw_sum += reward
        self._rw_abs_sum += abs(reward)
        if abs(reward) > 1e-7:
            self._rw_nonzero += 1
        self._rw_n += 1
        if self._rw_stats_interval > 0 and self._rw_n % self._rw_stats_interval == 0:
            n = max(self._rw_n, 1)
            nz_frac = self._rw_nonzero / n
            mean_abs = self._rw_abs_sum / n
            mean_r = self._rw_sum / n
            print(
                f"[REWARD_STATS] pid={os.getpid()} {self.symbol}:{self.timeframe} n={n} nonzero={nz_frac:.3f} "
                f"mean={mean_r:.6f} mean_abs={mean_abs:.6f} equity={equity_now:.2f} "
                f"max_eq={self._rw_max_equity:.2f} last_r={reward:.6f}",
                flush=True,
            )

        self.prev_action = action
        obs = self._get_state()

        done = self.current_balance < self.initial_balance * 0.1

        # Episode-end PnL realization
        if done and getattr(self, '_rw_episode_end_realize', True) and self._rw_mtm:
            if abs(float(self.positions[0])) > 1e-8:
                terminal_r = self._close_position(0, self._get_current_price())
                terminal_r = max(-self._rw_clip, min(self._rw_clip, terminal_r * self._rw_scale))
                reward = max(-self._rw_clip, min(self._rw_clip, reward + terminal_r))

        # Persistent penalties
        if bool(TRAIN_PERSISTENT_PENALTIES_ENABLED):
            try:
                baseline = getattr(self, "_equity_baseline", self.initial_balance) or self.initial_balance
                baseline = max(1.0, float(baseline))
                eq_delta = (float(equity_now) - baseline) / baseline
                if eq_delta < 0.0:
                    reward -= float(TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K or 0.0) * abs(eq_delta)
                cur_price = self._get_current_price()
                pnl_leg = self.position_sides[0] * self.positions[0] * (cur_price - self.entry_prices[0])
                neg_unreal = max(0.0, float(-pnl_leg))
                if neg_unreal > 0.0:
                    reward -= float(TRAIN_NEG_LEG_PENALTY_K or 0.0) * (neg_unreal / baseline)
            except Exception:
                pass

        # Clip observation
        obs = np.clip(obs, -10.0, 10.0)

        pnl_change = getattr(self, '_step_equity_delta', 0.0)
        info = {
            'balance': float(self.current_balance),
            'positions': self.positions.copy(),
            'total_value': equity_now,
            'pnl_change': pnl_change,
            'trade_executed': trade_executed,
            'realized_pnl_usd': float(self._last_realized_pnl_usd),
            'realized_action': str(self._last_realized_action),
            'features_ts_ms': int(self._last_features_ts_ms),
            'features_age_ms': int(self._last_features_age_ms),
            'features_hlen': int(self._last_features_hlen),
            'raw_reward': reward,
            'risk_adjusted_reward': reward,
            'gpu_device': 'cpu',
            'observation_on_gpu': False,
            'micro_features': self._cached_micro_raw,
        }

        # Gymnasium 5-value return
        terminated = done and (self.current_balance <= 0.1 * self.initial_balance)
        truncated = self.episode_steps >= self.max_episode_steps or (done and not terminated)

        return obs, float(reward), terminated, truncated, info

    # ── Trade execution (7-action hedge space) ───────────────────────────

    def _execute_trades_7action(self, action: int) -> float:
        """Execute 7-action trade — IDENTICAL logic to gpu_environment._execute_trades_gpu_7action."""
        price = self._get_current_price()
        if price <= 0:
            return 0.0

        pos = float(self.positions[0])
        side = float(self.position_sides[0])
        fee = self.transaction_cost

        equity = float(self.current_balance)
        # FIX Apr 14 2026: 5% position was too small - rewards were 450x smaller
        # than entropy bonus. 15% creates meaningful PnL signals for learning.
        target_frac = min(0.15, self.max_position)
        target_notional = target_frac * max(equity, 1.0)
        target_qty = target_notional / max(price, 1.0)

        # Lazy-load reward shaping constants
        if not self._reward_cfg_loaded:
            try:
                from config import (
                    RL_HOLD_FLAT_PENALTY, RL_POSITION_HOLD_BONUS,
                    RL_VALID_TRADE_BONUS, RL_INVALID_ACTION_PENALTY,
                    RL_PROFITABLE_CLOSE_BONUS, RL_LOSS_PENALTY_MULT,
                    RL_HOLD_TIME_BONUS, RL_DIRECTION_BONUS,
                    RL_ACTION_SWITCH_PENALTY,
                    RL_EARLY_CLOSE_MIN_STEPS, RL_EARLY_CLOSE_PENALTY_FRAC,
                )
                self._HOLD_FLAT_PENALTY = RL_HOLD_FLAT_PENALTY
                self._POSITION_HOLD_BONUS = RL_POSITION_HOLD_BONUS
                self._VALID_TRADE_BONUS = RL_VALID_TRADE_BONUS
                self._INVALID_ACTION_PENALTY = RL_INVALID_ACTION_PENALTY
                self._PROFITABLE_CLOSE_BONUS = RL_PROFITABLE_CLOSE_BONUS
                self._LOSS_PENALTY_MULT = RL_LOSS_PENALTY_MULT
                self._HOLD_TIME_BONUS = RL_HOLD_TIME_BONUS
                self._rl_direction_bonus = RL_DIRECTION_BONUS
                self._ACTION_SWITCH_PENALTY = RL_ACTION_SWITCH_PENALTY
                self._EARLY_CLOSE_MIN_STEPS = RL_EARLY_CLOSE_MIN_STEPS
                self._EARLY_CLOSE_PENALTY_FRAC = RL_EARLY_CLOSE_PENALTY_FRAC
            except ImportError:
                self._HOLD_FLAT_PENALTY = -0.008
                self._POSITION_HOLD_BONUS = 0.002
                self._VALID_TRADE_BONUS = 0.025
                self._INVALID_ACTION_PENALTY = -0.02
                self._PROFITABLE_CLOSE_BONUS = 0.5
                self._LOSS_PENALTY_MULT = 1.5
                self._HOLD_TIME_BONUS = 0.001
                self._rl_direction_bonus = 0.005
                self._ACTION_SWITCH_PENALTY = 0.015
                self._EARLY_CLOSE_MIN_STEPS = 10
                self._EARLY_CLOSE_PENALTY_FRAC = 0.5
            self._reward_cfg_loaded = True

        INVALID_ACTION_PENALTY = self._INVALID_ACTION_PENALTY
        VALID_TRADE_BONUS = self._VALID_TRADE_BONUS

        # 0 = HOLD
        if action == 0:
            if abs(pos) > 1e-8:
                hold_reward = self._POSITION_HOLD_BONUS
                if self.entry_prices is not None and abs(float(self.entry_prices[0])) > 1e-8:
                    entry_p = float(self.entry_prices[0])
                    cur_p = self._get_current_price()
                    unrealized = side * (cur_p - entry_p) / entry_p
                    if unrealized > 0:
                        hold_steps = min(getattr(self, 'steps_in_position', 0), 100)
                        hold_reward += self._HOLD_TIME_BONUS * (1.0 + hold_steps * 0.01)
                return hold_reward
            return self._HOLD_FLAT_PENALTY

        # 1 = OPEN_LONG
        if action == 1:
            if side <= 0 and abs(pos) < 1e-8:
                cost = target_qty * price * (1 + fee)
                if cost <= self.current_balance:
                    self.current_balance -= cost
                    self.positions[0] = target_qty
                    self.entry_prices[0] = price
                    self.position_sides[0] = 1.0
                    return VALID_TRADE_BONUS
            return INVALID_ACTION_PENALTY

        # 2 = OPEN_SHORT
        if action == 2:
            if side >= 0 and abs(pos) < 1e-8:
                margin = target_qty * price * (1 + fee)
                if margin <= self.current_balance:
                    self.current_balance -= margin
                    self.positions[0] = target_qty
                    self.entry_prices[0] = price
                    self.position_sides[0] = -1.0
                    return VALID_TRADE_BONUS
            return INVALID_ACTION_PENALTY

        # 3 = CLOSE_LONG
        if action == 3:
            if side > 0 and pos > 1e-8:
                close_r = self._close_position(0, price)
                if close_r > 0:
                    close_r += close_r * self._PROFITABLE_CLOSE_BONUS
                    _hold_steps = getattr(self, 'steps_in_position', 0)
                    if _hold_steps < self._EARLY_CLOSE_MIN_STEPS:
                        close_r -= abs(close_r) * self._EARLY_CLOSE_PENALTY_FRAC
                elif close_r < 0:
                    close_r += close_r * self._LOSS_PENALTY_MULT
                self.steps_in_position = 0
                return close_r + VALID_TRADE_BONUS
            return INVALID_ACTION_PENALTY

        # 4 = CLOSE_SHORT
        if action == 4:
            if side < 0 and pos > 1e-8:
                close_r = self._close_position(0, price)
                if close_r > 0:
                    close_r += close_r * self._PROFITABLE_CLOSE_BONUS
                    _hold_steps = getattr(self, 'steps_in_position', 0)
                    if _hold_steps < self._EARLY_CLOSE_MIN_STEPS:
                        close_r -= abs(close_r) * self._EARLY_CLOSE_PENALTY_FRAC
                elif close_r < 0:
                    close_r += close_r * self._LOSS_PENALTY_MULT
                self.steps_in_position = 0
                return close_r + VALID_TRADE_BONUS
            return INVALID_ACTION_PENALTY

        # 5 = CLOSE_SHORT_OPEN_LONG (flip)
        if action == 5:
            reward = 0.0
            if side < 0 and pos > 1e-8:
                close_r = self._close_position(0, price)
                if close_r > 0:
                    close_r += close_r * self._PROFITABLE_CLOSE_BONUS
                    _hold_steps = getattr(self, 'steps_in_position', 0)
                    if _hold_steps < self._EARLY_CLOSE_MIN_STEPS:
                        close_r -= abs(close_r) * self._EARLY_CLOSE_PENALTY_FRAC
                elif close_r < 0:
                    close_r += close_r * self._LOSS_PENALTY_MULT
                reward += close_r
                self.steps_in_position = 0
            elif abs(pos) > 1e-8:
                return INVALID_ACTION_PENALTY
            else:
                reward += INVALID_ACTION_PENALTY * 0.5
            cost = target_qty * price * (1 + fee)
            if cost <= self.current_balance:
                self.current_balance -= cost
                self.positions[0] = target_qty
                self.entry_prices[0] = price
                self.position_sides[0] = 1.0
                self.steps_in_position = 0
                reward += VALID_TRADE_BONUS
            return reward

        # 6 = CLOSE_LONG_OPEN_SHORT (flip)
        if action == 6:
            reward = 0.0
            if side > 0 and pos > 1e-8:
                close_r = self._close_position(0, price)
                if close_r > 0:
                    close_r += close_r * self._PROFITABLE_CLOSE_BONUS
                    _hold_steps = getattr(self, 'steps_in_position', 0)
                    if _hold_steps < self._EARLY_CLOSE_MIN_STEPS:
                        close_r -= abs(close_r) * self._EARLY_CLOSE_PENALTY_FRAC
                elif close_r < 0:
                    close_r += close_r * self._LOSS_PENALTY_MULT
                reward += close_r
                self.steps_in_position = 0
            elif abs(pos) > 1e-8:
                return INVALID_ACTION_PENALTY
            else:
                reward += INVALID_ACTION_PENALTY * 0.5
            margin = target_qty * price * (1 + fee)
            if margin <= self.current_balance:
                self.current_balance -= margin
                self.positions[0] = target_qty
                self.entry_prices[0] = price
                self.position_sides[0] = -1.0
                self.steps_in_position = 0
                reward += VALID_TRADE_BONUS
            return reward

        return 0.0

    def _close_position(self, symbol_idx: int, current_price: float) -> float:
        """Close entire position — numpy version of _close_position_gpu."""
        pos = float(self.positions[symbol_idx])
        if abs(pos) < 1e-8:
            return 0.0

        side = float(self.position_sides[symbol_idx])
        entry_p = float(self.entry_prices[symbol_idx])
        fee = self.transaction_cost

        if side > 0:  # LONG
            proceeds = pos * current_price * (1 - fee)
            self.current_balance += proceeds
            pnl = (current_price - entry_p) * pos
        else:  # SHORT
            margin_refund = pos * entry_p
            short_pnl = pos * (entry_p - current_price)
            close_fee = pos * current_price * fee
            self.current_balance += margin_refund + short_pnl - close_fee
            pnl = short_pnl

        reward = pnl / max(self.initial_balance, 1.0)

        try:
            gross = (current_price - entry_p) * pos if side > 0 else (entry_p - current_price) * pos
            net = gross - (pos * entry_p * fee) - (pos * current_price * fee)
            self._last_realized_pnl_usd = float(net)
            self._last_realized_action = "CLOSE_LONG" if side > 0 else "CLOSE_SHORT"
        except Exception:
            self._last_realized_pnl_usd = 0.0
            self._last_realized_action = ""

        self.positions[symbol_idx] = 0.0
        self.entry_prices[symbol_idx] = 0.0
        self.position_sides[symbol_idx] = 0.0

        return float(reward)

    # ── Microstructure reward ────────────────────────────────────────────

    def _microstructure_reward_adjustment(self, action: int) -> float:
        micro = getattr(self, '_cached_micro_raw', None)
        if not micro:
            return 0.0

        adj = 0.0
        spread_bps = float(micro.get('spread_bps', 0) or 0)
        spoof_score = float(micro.get('spoof_score', 0) or 0)
        fast_move = float(micro.get('fast_move_score', 0) or 0)
        dvt_div = float(micro.get('depth_vs_tape_divergence', 0) or 0)

        is_open = action in (1, 2, 5, 6)
        is_close = action in (3, 4, 5, 6)

        if is_open:
            if spread_bps > RL_MICRO_SPREAD_PENALTY_BPS:
                excess = (spread_bps - RL_MICRO_SPREAD_PENALTY_BPS) / max(RL_MICRO_SPREAD_PENALTY_BPS, 1.0)
                adj -= RL_MICRO_SPREAD_PENALTY_AMOUNT * min(excess, 3.0)
            if spoof_score > RL_MICRO_SPOOF_PENALTY_THRESHOLD:
                excess = (spoof_score - RL_MICRO_SPOOF_PENALTY_THRESHOLD)
                adj -= RL_MICRO_SPOOF_PENALTY_AMOUNT * min(excess / 0.5, 2.0)
            if fast_move > RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD:
                excess = (fast_move - RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD)
                adj -= RL_MICRO_FAST_MOVE_PENALTY_AMOUNT * min(excess / 0.4, 2.0)
            # Depth-vs-Tape divergence: penalize opens when depth is spoofed
            if dvt_div > 0.4:
                excess_dvt = (dvt_div - 0.4)
                adj -= RL_MICRO_SPOOF_PENALTY_AMOUNT * min(excess_dvt / 0.6, 2.0)

        if is_close:
            calm = (spread_bps < RL_MICRO_SPREAD_PENALTY_BPS * 0.5
                    and spoof_score < RL_MICRO_SPOOF_PENALTY_THRESHOLD * 0.3
                    and fast_move < RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD * 0.3
                    and dvt_div < 0.2)  # Tape must also be clean
            if calm:
                adj += RL_MICRO_FAVORABLE_EXIT_BONUS

        return adj

    def render(self):
        pass

    def close(self):
        pass
