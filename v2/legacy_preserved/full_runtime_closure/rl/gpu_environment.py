"""
GPU-Accelerated Trading Environment for SubprocVecEnv Workers

ARCHITECTURE FIX (2026-02-25): Complete rewrite.

OLD (BROKEN):
- All 25 symbols concatenated into 2000-dim vector
- Passed through untrained random NN (feature_processor) -> 1000-dim
- Portfolio state (25 positions + 25 entries + ...) appended -> 1101-dim
- Prediction path used DIFFERENT representation (alphabetical sort, no NN)
- Result: model trained on one representation, predicted with another -> garbage

NEW (MATCHES PREDICTION PATH):
- Each env assigned a SINGLE (symbol, timeframe)
- Reads unified_features:{symbol}:{tf} from Redis
- Sorts all ~450 numeric keys alphabetically (DETERMINISTIC)
- Applies median/MAD robust normalization + tanh squash
- Pads/truncates to CANONICAL_OBS_DIM (512)
- NO feature_processor NN, NO portfolio state
- Exactly matches _preprocess_features_gpu() in prediction path
"""

import json
import math
import os
import time
import numpy as np
from typing import Dict, List, Tuple, Any, Optional
import torch

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Dynamic symbol loading
try:
    from utils.symbol_manager import get_symbols_cached
    SYMBOLS = get_symbols_cached()
except ImportError:
    from config import SYMBOLS

from utils.redis_client import get_redis
from utils.logger import get_logger

# Import Phase 1 reward config
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

# Import microstructure reward config (kill-switched, fail-safe defaults OFF)
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

logger = get_logger("gpu_trading_environment")

# Canonical observation dimension: must match between training and prediction.
# Loaded from config so it stays in sync across env, trainer, and prediction path.
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


class GPUTradingEnvironment:
    """
    GPU-Accelerated Trading Environment -- SubprocVecEnv Worker Version.

    Each env is assigned a SINGLE (symbol, timeframe) and builds observations
    by reading unified_features:{symbol}:{tf} from Redis, sorting keys
    alphabetically, normalizing, and padding to CANONICAL_OBS_DIM.

    This EXACTLY matches the prediction/inference path.
    """

    def __init__(self,
                 initial_balance: float = 10000.0,
                 transaction_cost: float = None,
                 max_position: float = 1.0,
                 lookback_window: int = 10,
                 device: str = 'cuda'):
        """Initialize GPU-accelerated trading environment"""

        self.device_str = device
        self._device = None
        self._cuda_initialized = False

        self.initial_balance = initial_balance
        # Use config-driven transaction cost (realistic Binance fees)
        self.transaction_cost = transaction_cost if transaction_cost is not None else RL_TRANSACTION_COST
        self.max_position = max_position
        self.lookback_window = lookback_window

        # These are set by the factory (_make_subproc_env) AFTER construction
        self.symbol = None      # e.g. 'BTCUSDT'
        self.timeframe = None   # e.g. '5m'

        # Defer GPU tensor initialization
        self._positions_initialized = False
        self.positions = None
        self.entry_prices = None
        self.current_balance = None
        self.position_sides = None
        self.feature_processor = None  # DISABLED -- always None
        self.feature_buffer = None
        self.observation_buffer = None

        # Cross-step reward tracking
        self._rw_prev_equity = float(initial_balance)
        self._rw_max_equity = float(initial_balance)

        # Per-env feature key order cache (built lazily)
        self._feature_key_order = None

        # Price cache per step
        self._step_prices_cache = None
        self._step_prices_cache_id = -1
        self._step_counter = 0

        # Feature fetch cache
        self._last_feature_ts = 0.0
        self._cached_features = None
        self._feature_cache_ttl = float(os.getenv("GPU_ENV_FEATURE_CACHE_SECONDS", "0.5"))
        # Live-training realism: avoid stepping orders-of-magnitude faster than
        # feature/price updates. Default is a modest throttle that still allows
        # accelerated training, but prevents millions of duplicate states.
        try:
            self._min_step_seconds = float(os.getenv("GPU_ENV_MIN_STEP_SECONDS", "0.02"))
        except Exception:
            self._min_step_seconds = 0.02
        self._min_step_seconds = max(0.0, min(1.0, float(self._min_step_seconds)))
        self._last_step_walltime = 0.0

        # Feature timestamp telemetry (from unified_features:* hash if present)
        self._last_features_ts_ms = 0
        self._last_features_age_ms = -1
        self._last_features_hlen = 0

        # Action space: 7-action hedge space (matches hybrid_trainer Discrete(7))
        self.action_space_size = 7
        # ARCHITECTURE FIX: Each env trades ONLY one symbol
        self.n_symbols = 1

        # Redis: picklable config, client created lazily
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
        # Realized net PnL (USD) for accurate win/loss stats
        self._last_realized_pnl_usd = 0.0
        self._last_realized_action = ""

        # Hold-time tracking: counts steps while in a position (for hold-time reward)
        self.steps_in_position = 0

        logger.info(f"GPU Environment ready (CUDA deferred, n_symbols=1, tx_cost={self.transaction_cost})")

    def __getstate__(self):
        """Prepare state for pickling (SubprocVecEnv spawn compatibility)"""
        state = self.__dict__.copy()
        state['redis'] = None
        state['_device'] = None
        state['positions'] = None
        state['entry_prices'] = None
        state['current_balance'] = None
        state['position_sides'] = None
        state['feature_processor'] = None
        state['feature_buffer'] = None
        state['observation_buffer'] = None
        state['_cuda_initialized'] = False
        state['_positions_initialized'] = False
        state['_rw_cfg_loaded'] = False
        state['_cached_features'] = None
        state['_feature_key_order'] = None
        return state

    def __setstate__(self, state):
        """Restore state after unpickling"""
        self.__dict__.update(state)

    def _ensure_redis(self):
        """Ensure Redis connection is available (multiprocessing-safe)"""
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

    @property
    def device(self):
        """Get device, initializing CUDA if needed"""
        if self._device is None:
            self._initialize_cuda()
        return self._device

    def _initialize_cuda(self):
        """Initialize CUDA after process fork"""
        if self._cuda_initialized:
            return

        self._ensure_redis()

        cuda_available = torch.cuda.is_available()
        self._device = torch.device(self.device_str if cuda_available else 'cpu')

        if self._device.type == 'cuda':
            logger.info(f"GPU Environment initialized on {torch.cuda.get_device_name()}")
        elif self.device_str == 'cuda' and not cuda_available:
            logger.warning("CUDA requested but unavailable, falling back to CPU")
        else:
            logger.debug("CPU environment initialized (as configured)")

        # Single-symbol tensors (n_symbols=1)
        self.positions = torch.zeros(self.n_symbols, device=self._device, dtype=torch.float32)
        self.entry_prices = torch.zeros(self.n_symbols, device=self._device, dtype=torch.float32)
        self.current_balance = torch.tensor(self.initial_balance, device=self._device, dtype=torch.float32)
        self.position_sides = torch.zeros(self.n_symbols, device=self._device, dtype=torch.float32)

        # ARCHITECTURE FIX: No feature_processor NN
        self.feature_processor = None

        # Pre-allocated buffers at CANONICAL_OBS_DIM
        self.feature_buffer = torch.zeros(CANONICAL_OBS_DIM, device=self._device, dtype=torch.float32)
        self.observation_buffer = torch.zeros(CANONICAL_OBS_DIM, device=self._device, dtype=torch.float32)

        self._cuda_initialized = True
        sym = getattr(self, 'symbol', '?')
        tf = getattr(self, 'timeframe', '?')
        logger.info(f"CUDA init complete on {self._device} | assigned={sym}:{tf} | obs_dim={CANONICAL_OBS_DIM}")

    def warm_up_gpu(self):
        """Warm up GPU by ensuring CUDA is initialized"""
        _ = self.device
        logger.info("GPU warmed up successfully")

    # ============================================================
    # FEATURE EXTRACTION (matches prediction path EXACTLY)
    # ============================================================

    @staticmethod
    def _is_feature_metadata_key(key):
        """Check if a Redis hash key is metadata (not a numeric feature).

        Filters:
        - Explicit metadata keys (ts_ms, symbol, timeframe, timestamp)
        - Prediction-injected keys (portfolio_*, position_*, _acct*)
        - Timestamp-valued keys (_ts suffix, _tss_ stats, _col0_ coinank ts column)
        - Staleness keys (staleness_ms, _staleness)
        - Epoch/begin timestamp keys (_0_ts, _0_begin, _data_0_begin)
        These carry trillion-scale values that destroy median/MAD normalization.
        """
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
        """Check if a TA feature should be pruned (low-signal redundant indicator).
        Returns True if the key should be EXCLUDED from observations.
        Only applies when ENABLE_TA_FEATURE_PRUNING is True.
        """
        try:
            from config import ENABLE_TA_FEATURE_PRUNING, TA_FEATURE_WHITELIST_PREFIXES
        except ImportError:
            return False
        if not ENABLE_TA_FEATURE_PRUNING:
            return False
        if not key.startswith("ind_ta_"):
            return False
        # Strip the "ind_ta_" prefix and check against whitelist
        ta_name = key[7:]  # Remove "ind_ta_"
        for prefix in TA_FEATURE_WHITELIST_PREFIXES:
            if ta_name.startswith(prefix):
                return False
        return True

    @staticmethod
    def _normalize_feature_vector_robust(vec):
        """Robust median/MAD normalization with tanh squash.
        Matches HybridTrainer._normalize_feature_vector_robust exactly."""
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

    def get_current_features_gpu(self):
        """Get features for assigned symbol:tf, matching prediction path exactly.

        1. Read unified_features:{symbol}:{tf} from Redis
        2. Filter metadata keys
        3. Sort remaining keys alphabetically
        4. Convert to float
        5. Normalize (median/MAD + tanh squash)
        6. Pad/truncate to CANONICAL_OBS_DIM
        """
        self._initialize_cuda()
        self._ensure_redis()
        self._step_counter += 1

        # Fast cache
        now = time.time()
        if self._cached_features is not None and (now - self._last_feature_ts) < self._feature_cache_ttl:
            return self._cached_features

        sym = getattr(self, 'symbol', None) or SYMBOLS[0]
        tf = getattr(self, 'timeframe', None) or '5m'

        try:
            if self.redis is None:
                return self._get_default_features_gpu()

            redis_key = f"unified_features:{sym}:{tf}"
            raw_hash = self.redis.hgetall(redis_key)

            if not raw_hash:
                logger.debug(f"No features in {redis_key}, using defaults")
                return self._get_default_features_gpu()

            # Decode
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
                return self._get_default_features_gpu()
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

            feature_tensor = torch.tensor(numeric_features, device=self._device, dtype=torch.float32)
            feature_tensor = torch.nan_to_num(feature_tensor, nan=0.0, posinf=0.0, neginf=0.0)
            feature_tensor = torch.clamp(feature_tensor, -5.0, 5.0)

            _nonzero_ct = int((feature_tensor.abs() > 1e-7).sum().item())
            if _nonzero_ct < 10 and self._cached_features is not None:
                return self._cached_features

            # Cache
            self._cached_features = feature_tensor
            self._last_feature_ts = now
            # Cache raw microstructure features for reward shaping (pre-normalization)
            # These are the actual market microstructure signals the agent should learn from
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
            }

            # Periodic logging
            if not hasattr(self, '_feature_log_counter'):
                self._feature_log_counter = 0
            self._feature_log_counter += 1
            if self._feature_log_counter <= 3 or self._feature_log_counter % 10000 == 0:
                nonzero = (feature_tensor.abs() > 1e-7).sum().item()
                logger.info(
                    f"[TRAIN_FEATURES] {sym}:{tf} -> "
                    f"{len(self._feature_key_order)} keys -> {CANONICAL_OBS_DIM}-dim | "
                    f"nonzero={nonzero}/{CANONICAL_OBS_DIM} ({100*nonzero/CANONICAL_OBS_DIM:.1f}%)"
                )

            return feature_tensor

        except Exception as e:
            logger.error(f"Error getting features for {sym}:{tf}: {e}")
            return self._get_default_features_gpu()

    def _get_default_features_gpu(self):
        """Default features when Redis unavailable."""
        return torch.zeros(CANONICAL_OBS_DIM, device=self.device, dtype=torch.float32)

    def get_state_gpu(self):
        """Get observation -- raw features + TF ordinal + position state for training.
        
        ARCHITECTURE FIX 2026-02-26: Added position state to observation.
        ARCHITECTURE FIX 2026-02-28: Added TF ordinal + train/predict alignment.
        
        Without position info, the model CAN'T learn state-dependent policies:
        it doesn't know if it's flat, long, or short, so it can't learn
        when OPEN_LONG is valid (flat) vs when CLOSE_LONG is valid (in long).
        Result: collapses to unconditional policy (always HOLD or always one action).
        
        Observation layout (last 5 dims of CANONICAL_OBS_DIM vector):
          dim -5: timeframe ordinal (0.0=1m, 0.25=5m, 0.5=15m, 0.75=1h, 1.0=4h)
          dim -4: position_side (-1=short, 0=flat, +1=long)
          dim -3: has_position (0=flat, 1=in position)
          dim -2: balance_ratio ((current_bal/initial_bal) - 1.0)
          dim -1: unrealized_pnl_ratio (clipped to [-1, 1])
        
        These SAME dims are injected in the prediction path (hybrid_trainer.py)
        after _preprocess_features_gpu() to ensure train/predict alignment.
        Kill switch: ENABLE_POSITION_STATE_PREDICT in config.py.
        """
        self._initialize_cuda()
        raw_features = self.get_current_features_gpu()

        # Ensure exact CANONICAL_OBS_DIM
        if raw_features.shape[0] != CANONICAL_OBS_DIM:
            padded = torch.zeros(CANONICAL_OBS_DIM, device=self.device, dtype=torch.float32)
            n = min(raw_features.shape[0], CANONICAL_OBS_DIM)
            padded[:n] = raw_features[:n]
            raw_features = padded

        # dim -5 (507): Timeframe ordinal — lets model learn TF-specific behavior
        if RL_TF_ORDINAL_ENABLED:
            tf = getattr(self, 'timeframe', None) or '5m'
            tf_ordinal_map = {'1m': 0.0, '5m': 0.25, '15m': 0.5, '1h': 0.75, '4h': 1.0}
            raw_features[CANONICAL_OBS_DIM - 5] = tf_ordinal_map.get(tf, 0.5)

        # Embed position state into last 4 dims (replaces padding zeros)
        # This gives the model the ability to learn state-dependent policies
        pos = float(self.positions[0].item()) if self.positions is not None else 0.0
        side = float(self.position_sides[0].item()) if self.position_sides is not None else 0.0
        bal = float(self.current_balance.item()) if self.current_balance is not None else self.initial_balance
        
        # dim -4 (508): position side (-1=short, 0=flat, +1=long)
        raw_features[CANONICAL_OBS_DIM - 4] = side
        # dim -3 (509): has position (0=flat, 1=in position) — binary signal
        raw_features[CANONICAL_OBS_DIM - 3] = 1.0 if abs(pos) > 1e-8 else 0.0
        # dim -2 (510): balance ratio (current/initial, normalized around 1.0)
        raw_features[CANONICAL_OBS_DIM - 2] = (bal / max(self.initial_balance, 1.0)) - 1.0
        # dim -1 (511): unrealized PnL ratio (if in position)
        if abs(pos) > 1e-8 and self.entry_prices is not None:
            entry = float(self.entry_prices[0].item())
            if entry > 0:
                current_prices = self._get_current_prices_gpu()
                price = float(current_prices[0].item())
                pnl_ratio = side * (price - entry) / entry
                raw_features[CANONICAL_OBS_DIM - 1] = max(-1.0, min(1.0, pnl_ratio * 10.0))

        return raw_features

    # ============================================================
    # PRICE & PORTFOLIO
    # ============================================================

    def _get_price(self, symbol):
        """Get price for a symbol from Redis."""
        redis = self._ensure_redis()
        if redis is None:
            return 0.0

        # Primary: market:{symbol}:1m
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

        # Secondary: price:{symbol}
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

    def _get_current_prices_gpu(self):
        """Get LIVE price for assigned symbol from Redis.

        Each env has a different (symbol, timeframe) so prices differ across
        symbol-groups naturally (BTC≠ETH≠SOL).  Within same-symbol envs the
        price IS identical per step, but that's correct — the diversity in
        advantages comes from different positions/actions taken by each env.
        """
        # Return cached if same step (avoids redundant Redis reads)
        if (self._step_prices_cache is not None
                and self._step_prices_cache_id == self._step_counter):
            return self._step_prices_cache

        sym = getattr(self, 'symbol', None) or SYMBOLS[0]
        price = self._get_price(sym)

        prices_t = torch.tensor([max(price, 1e-10)], device=self.device, dtype=torch.float32)

        self._step_prices_cache = prices_t
        self._step_prices_cache_id = self._step_counter
        return prices_t

    def _calculate_portfolio_value_gpu(self):
        """Calculate portfolio value (single symbol)."""
        current_prices = self._get_current_prices_gpu()

        if hasattr(self, 'position_sides') and self.position_sides is not None:
            sides = self.position_sides
        else:
            sides = torch.ones(self.n_symbols, device=self.device, dtype=torch.float32)

        margin_used = (self.positions * self.entry_prices).sum()
        unrealized_pnl = (sides * self.positions * (current_prices - self.entry_prices)).sum()

        return self.current_balance + margin_used + unrealized_pnl

    # ============================================================
    # TRADING EXECUTION (7-action hedge space)
    # ============================================================

    def step_gpu(self, action):
        """Execute trading step with cross-step MTM reward."""
        # Throttle to prevent stepping far faster than data refresh.
        if getattr(self, "_min_step_seconds", 0.0) > 0:
            try:
                now = time.time()
                last = float(getattr(self, "_last_step_walltime", 0.0) or 0.0)
                if last > 0:
                    dt = now - last
                    min_dt = float(self._min_step_seconds)
                    if dt < min_dt:
                        time.sleep(min_dt - dt)
                self._last_step_walltime = time.time()
            except Exception:
                pass

        self.step_count += 1
        # Reset realized PnL marker each step; set only by CLOSE/FLIP actions
        self._last_realized_pnl_usd = 0.0
        self._last_realized_action = ""

        # Lazy-load reward config
        if not hasattr(self, '_rw_cfg_loaded') or not self._rw_cfg_loaded:
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

        if not hasattr(self, 'position_sides') or self.position_sides is None:
            self.position_sides = torch.zeros(self.n_symbols, device=self.device, dtype=torch.float32)

        # Position-aware action masking: remap structurally invalid actions to HOLD.
        # Matches inference-time masking (actions 3-6 masked when flat, 1-2 masked
        # when in a position of the wrong side). This eliminates the train/inference
        # distribution mismatch where training explored 7 actions but inference only 3.
        pos = float(self.positions[0].item()) if self.positions is not None else 0.0
        side = float(self.position_sides[0].item()) if self.position_sides is not None else 0.0
        _is_flat = abs(pos) < 1e-8
        if _is_flat and action in (3, 4, 5, 6):
            action = 0
        elif not _is_flat:
            if side > 0 and action in (2, 4, 5):
                action = 0
            elif side < 0 and action in (1, 3, 6):
                action = 0

        # Action-based trade detection (not pnl-based -- prevents noise from triggering)
        trade_executed = (self.prev_action is not None and action != self.prev_action and action != 0)

        # Execute trade
        trade_reward = self._execute_trades_gpu_7action(action)

        # ── DIRECTION-AWARE ENTRY BONUS (Feb 2026) ────────────────────
        # FIX: Model collapsed to HOLD+LONG only (0% SHORT) because no reward
        # signal taught it WHEN to go SHORT vs LONG based on price direction.
        # This adds a small bonus/penalty based on whether the entry direction
        # aligns with recent price movement:
        # - OPEN_SHORT when price is falling → small bonus
        # - OPEN_LONG when price is rising → small bonus
        # - Wrong direction → small penalty (not a full INVALID_ACTION)
        # Kill-switch: RL_DIRECTION_BONUS (default: 0.005)
        try:
            _dir_bonus_scale = float(getattr(self, '_rl_direction_bonus', None) or 0.005)
            if _dir_bonus_scale > 0 and action in (1, 2, 5, 6):  # All entry actions
                prices = self._get_current_prices_gpu()
                cur_price = float(prices[0].item())
                prev_price = float(getattr(self, '_prev_step_price', cur_price) or cur_price)
                if prev_price > 0 and cur_price > 0:
                    price_ret = (cur_price - prev_price) / prev_price
                    if action in (1, 5):  # OPEN_LONG or flip-to-long
                        trade_reward += _dir_bonus_scale * (1.0 if price_ret > 0.0001 else (-0.5 if price_ret < -0.0001 else 0.0))
                    elif action in (2, 6):  # OPEN_SHORT or flip-to-short
                        trade_reward += _dir_bonus_scale * (1.0 if price_ret < -0.0001 else (-0.5 if price_ret > 0.0001 else 0.0))
                self._prev_step_price = cur_price
        except Exception:
            pass  # Fail-safe: no direction bonus on error

        # ── ACTION-SWITCH PENALTY ──────────────────────────────────────
        # Penalize consecutive non-HOLD action changes to prevent churning.
        # Without this, VALID_TRADE_BONUS (+0.025) per switch incentivizes
        # 990 switches/episode. This makes net reward per switch negative
        # unless the position earns real MTM profit.
        if trade_executed and self._ACTION_SWITCH_PENALTY > 0:
            trade_reward -= self._ACTION_SWITCH_PENALTY

        # ── MICROSTRUCTURE REWARD SHAPING ──────────────────────────────
        # Teach the model about market microstructure conditions:
        # - Penalize OPENs during wide spread / spoofing / fast moves
        # - Bonus CLOSEs during favorable microstructure (tight spread, calm book)
        # This is kill-switched via RL_MICRO_REWARD_ENABLED (default: True)
        if RL_MICRO_REWARD_ENABLED and action != 0:
            try:
                micro_adj = self._microstructure_reward_adjustment(action)
                if abs(micro_adj) > 1e-8:
                    trade_reward += micro_adj
            except Exception:
                pass  # Fail-safe: no microstructure adjustment on error

        # Track hold-time (steps spent in a position)
        if self.positions is not None and abs(float(self.positions[0].item())) > 1e-8:
            self.steps_in_position += 1
        else:
            self.steps_in_position = 0

        # Portfolio value
        equity_now = self._calculate_portfolio_value_gpu().item()

        # Cross-step MTM reward
        if self._rw_mtm:
            initial_bal = float(self.initial_balance)
            equity_prev = self._rw_prev_equity

            safe_prev = max(equity_prev, initial_bal * 0.01)
            safe_now = max(equity_now, initial_bal * 0.01)
            r_mtm = math.log(safe_now / safe_prev)

            self._rw_max_equity = max(self._rw_max_equity, equity_now)
            self._rw_max_equity = self._rw_max_equity * 0.999 + equity_now * 0.001
            dd_pct = max(0.0, (self._rw_max_equity - equity_now) / max(self._rw_max_equity, 1.0))
            r_dd = -self._rw_dd_coeff * dd_pct

            raw_reward = r_mtm + r_dd
            if abs(trade_reward) > 1e-6:
                raw_reward += trade_reward * 0.5

            scaled = raw_reward * self._rw_scale
            reward = max(-self._rw_clip, min(self._rw_clip, scaled))
        else:
            reward = trade_reward

        # Capture equity delta BEFORE overwriting prev (used in info dict for trade counting)
        self._step_equity_delta = equity_now - self._rw_prev_equity
        self._rw_prev_equity = equity_now

        # REWARD_STATS diagnostic
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
            sym = getattr(self, 'symbol', '?')
            tf = getattr(self, 'timeframe', '?')
            print(
                f"[REWARD_STATS] pid={os.getpid()} {sym}:{tf} n={n} nonzero={nz_frac:.3f} "
                f"mean={mean_r:.6f} mean_abs={mean_abs:.6f} equity={equity_now:.2f} "
                f"max_eq={self._rw_max_equity:.2f} last_r={reward:.6f}",
                flush=True
            )

        self.prev_action = action
        next_state = self.get_state_gpu()

        done = self.current_balance < self.initial_balance * 0.1

        # Episode-end PnL realization
        if done and getattr(self, '_rw_episode_end_realize', True) and self._rw_mtm:
            prices = self._get_current_prices_gpu()
            if abs(float(self.positions[0].item())) > 1e-8:
                terminal_r = self._close_position_gpu(0, prices[0])
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
                prices_t = self._get_current_prices_gpu()
                pnl_legs = self.position_sides * self.positions * (prices_t - self.entry_prices)
                neg_unreal = torch.clamp(-pnl_legs, min=0.0).sum().item()
                if neg_unreal > 0.0:
                    reward -= float(TRAIN_NEG_LEG_PENALTY_K or 0.0) * (neg_unreal / baseline)
            except Exception:
                pass

        pnl_change = getattr(self, '_step_equity_delta', 0.0)
        info = {
            'balance': self.current_balance.item(),
            'positions': self.positions.cpu().numpy(),
            'total_value': equity_now,
            'pnl_change': pnl_change,
            'trade_executed': trade_executed,
            # Realized net PnL in USD for CLOSE/FLIP actions (0.0 otherwise)
            'realized_pnl_usd': float(getattr(self, '_last_realized_pnl_usd', 0.0) or 0.0),
            'realized_action': str(getattr(self, '_last_realized_action', '') or ''),
            # Feature freshness telemetry (for training diagnostics)
            'features_ts_ms': int(getattr(self, '_last_features_ts_ms', 0) or 0),
            'features_age_ms': int(getattr(self, '_last_features_age_ms', -1) or -1),
            'features_hlen': int(getattr(self, '_last_features_hlen', 0) or 0),
            'raw_reward': reward,
            'risk_adjusted_reward': reward,
            'gpu_device': str(self.device),
            'observation_on_gpu': True,
            'micro_features': getattr(self, '_cached_micro_raw', None),
        }

        return next_state, reward, done, info

    def _microstructure_reward_adjustment(self, action: int) -> float:
        """Compute microstructure-aware reward adjustment for trade actions.

        Reads cached raw microstructure features (spread, spoof score, fast move)
        and returns a penalty (negative) for OPENs in unfavorable conditions or
        a bonus (positive) for CLOSEs in favorable conditions.

        This teaches the model to:
        - Avoid entering during wide spreads (higher slippage cost)
        - Avoid entering when spoof detection is high (fake liquidity)
        - Avoid entering during fast moves (momentum exhaustion risk)
        - Prefer exiting when microstructure is calm (better fills)

        Returns 0.0 if microstructure data unavailable or kill-switch off.
        """
        micro = getattr(self, '_cached_micro_raw', None)
        if not micro:
            return 0.0

        adj = 0.0
        spread_bps = float(micro.get('spread_bps', 0) or 0)
        spoof_score = float(micro.get('spoof_score', 0) or 0)
        fast_move = float(micro.get('fast_move_score', 0) or 0)
        depth_quality = float(micro.get('depth_quality', 0) or 0)

        # Classify action: is it an OPEN (risk-adding) or CLOSE (risk-reducing)?
        is_open = action in (1, 2, 5, 6)   # OPEN_LONG, OPEN_SHORT, FLIP_TO_LONG, FLIP_TO_SHORT
        is_close = action in (3, 4, 5, 6)  # CLOSE_LONG, CLOSE_SHORT (flips have both)

        if is_open:
            # Penalty for wide spread: higher transaction cost not captured by flat fee
            if spread_bps > RL_MICRO_SPREAD_PENALTY_BPS:
                excess = (spread_bps - RL_MICRO_SPREAD_PENALTY_BPS) / max(RL_MICRO_SPREAD_PENALTY_BPS, 1.0)
                adj -= RL_MICRO_SPREAD_PENALTY_AMOUNT * min(excess, 3.0)  # Cap at 3x

            # Penalty for spoofing: fake liquidity may reverse after entry
            if spoof_score > RL_MICRO_SPOOF_PENALTY_THRESHOLD:
                excess = (spoof_score - RL_MICRO_SPOOF_PENALTY_THRESHOLD)
                adj -= RL_MICRO_SPOOF_PENALTY_AMOUNT * min(excess / 0.5, 2.0)

            # Penalty for fast moves: entering during momentum exhaustion
            if fast_move > RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD:
                excess = (fast_move - RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD)
                adj -= RL_MICRO_FAST_MOVE_PENALTY_AMOUNT * min(excess / 0.4, 2.0)

        if is_close:
            # Bonus for closing in calm microstructure (better fills)
            calm = (spread_bps < RL_MICRO_SPREAD_PENALTY_BPS * 0.5
                    and spoof_score < RL_MICRO_SPOOF_PENALTY_THRESHOLD * 0.3
                    and fast_move < RL_MICRO_FAST_MOVE_PENALTY_THRESHOLD * 0.3)
            if calm:
                adj += RL_MICRO_FAVORABLE_EXIT_BONUS

        return adj

    def _execute_trades_gpu_7action(self, action):
        """Execute 7-action trade for the SINGLE assigned symbol.

        Action mapping (matches rl/action_ontology.py):
        0=HOLD, 1=OPEN_LONG, 2=OPEN_SHORT, 3=CLOSE_LONG,
        4=CLOSE_SHORT, 5=CLOSE_SHORT_OPEN_LONG, 6=CLOSE_LONG_OPEN_SHORT

        FIX 2026-02-26: Reward shaping to break HOLD-collapse local optimum.
        Problem: HOLD-when-flat gave 0 reward (risk-free), model converged to
        always HOLD because trading risked -0.05 penalties. trades=0 forever.
        Fix: (a) HOLD-flat is now penalized, (b) valid trades get meaningful
        bonus, (c) invalid penalty reduced, (d) position-holding gives tiny
        per-step bonus, (e) profitable closes get extra bonus.
        """
        current_prices = self._get_current_prices_gpu()
        price = current_prices[0]
        if price.item() <= 0:
            return 0.0

        pos = float(self.positions[0].item())
        side = float(self.position_sides[0].item())
        fee = self.transaction_cost

        equity = float(self.current_balance.item())
        target_frac = min(0.05, self.max_position)
        target_notional = target_frac * max(equity, 1.0)
        target_qty = target_notional / max(float(price.item()), 1.0)

        # Load reward shaping constants from config (with safe defaults)
        if not hasattr(self, '_reward_cfg_loaded'):
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
                # In a position: base bonus for maintaining market exposure
                hold_reward = self._POSITION_HOLD_BONUS
                # Hold-time bonus: extra reward for holding PROFITABLE positions
                # Encourages letting winners run instead of premature exits
                if self.entry_prices is not None and abs(float(self.entry_prices[0].item())) > 1e-8:
                    entry_p = float(self.entry_prices[0].item())
                    cur_prices = self._get_current_prices_gpu()
                    cur_p = float(cur_prices[0].item())
                    unrealized = side * (cur_p - entry_p) / entry_p
                    if unrealized > 0:
                        # Scale bonus by hold duration (capped at 100 steps)
                        hold_steps = min(getattr(self, 'steps_in_position', 0), 100)
                        hold_reward += self._HOLD_TIME_BONUS * (1.0 + hold_steps * 0.01)
                return hold_reward
            # Flat: penalize to break HOLD-collapse (opportunity cost)
            return self._HOLD_FLAT_PENALTY

        # 1 = OPEN_LONG
        if action == 1:
            if side <= 0 and abs(pos) < 1e-8:  # Flat -> go long
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
            if side >= 0 and abs(pos) < 1e-8:  # Flat -> go short
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
                close_r = self._close_position_gpu(0, price)
                if close_r > 0:
                    close_r += close_r * self._PROFITABLE_CLOSE_BONUS
                    # Early close penalty: discourage closing winners before min hold
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
                close_r = self._close_position_gpu(0, price)
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
                close_r = self._close_position_gpu(0, price)
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
                return INVALID_ACTION_PENALTY  # Can't flip from long
            else:
                # FLAT: flip-when-flat is redundant — penalize so model
                # learns to use direct OPEN_LONG (action 1) instead.
                # Without this, flip strictly dominates direct open.
                reward += INVALID_ACTION_PENALTY * 0.5
            # Open long
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
                close_r = self._close_position_gpu(0, price)
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
                return INVALID_ACTION_PENALTY  # Can't flip from short
            else:
                # FLAT: flip-when-flat is redundant — penalize so model
                # learns to use direct OPEN_SHORT (action 2) instead.
                reward += INVALID_ACTION_PENALTY * 0.5
            # Open short
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

    def _close_position_gpu(self, symbol_idx, current_price):
        """Close entire position with correct LONG/SHORT accounting."""
        pos = self.positions[symbol_idx]
        if abs(pos.item()) < 1e-8:
            return 0.0

        side = self.position_sides[symbol_idx].item()
        entry = self.entry_prices[symbol_idx]
        qty = float(pos.item())
        entry_p = float(entry.item())
        cur_p = float(current_price.item())
        fee = float(self.transaction_cost)

        if side > 0:  # LONG
            proceeds = pos * current_price * (1 - self.transaction_cost)
            self.current_balance += proceeds
            pnl = (current_price - entry) * pos
        else:  # SHORT
            margin_refund = pos * entry
            short_pnl = pos * (entry - current_price)
            close_fee = pos * current_price * self.transaction_cost
            self.current_balance += margin_refund + short_pnl - close_fee
            pnl = short_pnl

        reward = float((pnl / self.initial_balance).item())

        # Realized net PnL (USD) including entry+exit fees (used for stats, not reward)
        try:
            gross = (cur_p - entry_p) * qty if side > 0 else (entry_p - cur_p) * qty
            net = gross - (qty * entry_p * fee) - (qty * cur_p * fee)
            self._last_realized_pnl_usd = float(net)
            self._last_realized_action = "CLOSE_LONG" if side > 0 else "CLOSE_SHORT"
        except Exception:
            self._last_realized_pnl_usd = 0.0
            self._last_realized_action = ""

        self.positions[symbol_idx] = 0.0
        self.entry_prices[symbol_idx] = 0.0
        self.position_sides[symbol_idx] = 0.0

        return reward

    def reset_gpu(self):
        """Reset environment."""
        if not self._cuda_initialized:
            self._initialize_cuda()

        self.positions.zero_()
        self.entry_prices.zero_()
        self.current_balance.fill_(self.initial_balance)
        if hasattr(self, 'position_sides') and self.position_sides is not None:
            self.position_sides.zero_()

        self._equity_baseline = float(self.initial_balance or 1.0)
        self.equity_curve = [self.initial_balance]
        self.max_equity = self.initial_balance
        self.prev_action = None
        self.step_count = 0
        self.steps_in_position = 0

        self._rw_prev_equity = float(self.initial_balance)
        self._rw_max_equity = float(self.initial_balance)

        # Reset feature cache (force fresh data on new episode)
        self._cached_features = None
        self._feature_key_order = None
        self._step_prices_cache = None
        self._step_counter = 0

        return self.get_state_gpu()
