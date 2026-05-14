"""
Batch Processing Utilities for GPU-Optimized Inference

This module provides:
- Redis pipeline prefetch for batch feature loading
- Vectorized feature assembly with pinned memory
- Performance timing helpers
- Optional background prefetch worker

All utilities are throughput-only optimizations that do NOT change:
- Trading logic, thresholds, or action mappings
- Confidence formulas or gating logic
- MASA behavior or cooldowns
"""

import os
import time
import logging
import threading
import queue
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Environment Configuration
# ============================================================================

# Log per-candidate details only every N cycles (default 50)
AUDIT_LOG_EVERY_N = int(os.getenv("AUDIT_LOG_EVERY_N", "50"))

# Enable background prefetch (default OFF)
ENABLE_PREFETCH = os.getenv("ENABLE_PREFETCH", "0") == "1"


# ============================================================================
# Batch Context for Per-Cycle Data
# ============================================================================

@dataclass
class BatchContext:
    """Container for all batch data within a single prediction cycle."""
    
    # Candidate list
    symbols_tfs: List[Tuple[str, str]] = field(default_factory=list)
    
    # Redis data maps (keyed by (symbol, tf))
    features_map: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    pred_map: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    orderbook_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Batch tensors (populated after feature assembly)
    obs_np: Optional[np.ndarray] = None  # shape [B, D], float32
    
    # Timing metrics (milliseconds)
    redis_ms: float = 0.0
    feat_ms: float = 0.0
    h2d_ms: float = 0.0
    ppo_ms: float = 0.0
    masa_ms: float = 0.0
    gate_ms: float = 0.0
    publish_ms: float = 0.0
    
    @property
    def batch_size(self) -> int:
        return len(self.symbols_tfs)
    
    @property
    def feature_dim(self) -> int:
        return self.obs_np.shape[1] if self.obs_np is not None else 0


# ============================================================================
# Performance Timer Context Manager
# ============================================================================

class PerfTimer:
    """Simple context manager for timing code blocks."""
    
    def __init__(self):
        self.start_time = 0.0
        self.elapsed_ms = 0.0
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000.0


def log_perf_summary(ctx: BatchContext, cycle_num: int):
    """Log performance summary for a cycle."""
    total_ms = ctx.redis_ms + ctx.feat_ms + ctx.h2d_ms + ctx.ppo_ms + ctx.masa_ms + ctx.gate_ms + ctx.publish_ms
    logger.info(
        f"[PERF] cycle={cycle_num} redis_ms={ctx.redis_ms:.1f} feat_ms={ctx.feat_ms:.1f} "
        f"h2d_ms={ctx.h2d_ms:.1f} ppo_ms={ctx.ppo_ms:.1f} masa_ms={ctx.masa_ms:.1f} "
        f"gate_ms={ctx.gate_ms:.1f} publish_ms={ctx.publish_ms:.1f} total_ms={total_ms:.1f} "
        f"B={ctx.batch_size} D={ctx.feature_dim}"
    )


# ============================================================================
# Redis Pipeline Prefetch
# ============================================================================

def pipeline_fetch_features(
    redis_client,
    symbol_tf_pairs: List[Tuple[str, str]],
    include_predictions: bool = True,
    include_orderbook: bool = False,
    freshness_thresholds: Optional[Dict[str, int]] = None,
) -> BatchContext:
    """
    Fetch all required Redis keys for a batch of (symbol, tf) pairs in ONE pipeline.
    
    This replaces per-candidate HGETALL calls with a single pipeline execution,
    significantly reducing Redis round-trips.
    
    Args:
        redis_client: Redis client with pipeline() support
        symbol_tf_pairs: List of (symbol, timeframe) tuples to fetch
        include_predictions: Whether to also fetch prediction:{symbol}:{tf} keys
        include_orderbook: Whether to fetch orderbook:top:{symbol} keys
        freshness_thresholds: Optional dict of {timeframe: max_age_ms}
    
    Returns:
        BatchContext with populated feature/prediction/orderbook maps
    """
    if freshness_thresholds is None:
        # RELAXED thresholds to ensure ALL symbols get processed
        freshness_thresholds = {
            '1m': 600_000,     # 10 minutes - ensures 1m data included even if slightly stale
            '5m': 1_800_000,   # 30 minutes - more tolerance for feature lag
            '15m': 3_600_000,  # 60 minutes - full hour tolerance
            '1h': 14_400_000,  # 4 hours - more tolerance for slower updates
            '4h': 57_600_000,  # 16 hours - 4x candle period tolerance
        }
    
    ctx = BatchContext()
    
    if not redis_client or not symbol_tf_pairs:
        return ctx
    
    try:
        pipe = redis_client.pipeline(transaction=False)
        
        # Build key list and track indices
        key_indices = []  # [(key_type, symbol, tf, pipe_index), ...]
        
        for symbol, tf in symbol_tf_pairs:
            # Feature key
            key_indices.append(('feature', symbol, tf, len(key_indices)))
            pipe.hgetall(f"unified_features:{symbol}:{tf}")
            
            if include_predictions:
                key_indices.append(('pred', symbol, tf, len(key_indices)))
                pipe.hgetall(f"prediction:{symbol}:{tf}")
        
        # Orderbook keys (one per unique symbol)
        if include_orderbook:
            unique_symbols = list(set(s for s, _ in symbol_tf_pairs))
            for symbol in unique_symbols:
                key_indices.append(('orderbook', symbol, '', len(key_indices)))
                pipe.hgetall(f"orderbook:top:{symbol}")
        
        # Execute pipeline
        results = pipe.execute(raise_on_error=False)
        
        now_ms = int(time.time() * 1000)
        
        # Parse results
        for i, (key_type, symbol, tf, _) in enumerate(key_indices):
            if i >= len(results):
                break
                
            data = results[i]
            if not data or not isinstance(data, dict):
                continue
            
            # Decode bytes if needed
            decoded = {}
            for k, v in data.items():
                key_str = k.decode('utf-8') if isinstance(k, bytes) else k
                val_str = v.decode('utf-8') if isinstance(v, bytes) else v
                decoded[key_str] = val_str
            
            if key_type == 'feature':
                # Check freshness
                ts_ms = int(decoded.get('ts_ms', 0) or 0)
                if ts_ms > 0:
                    age_ms = now_ms - ts_ms
                    threshold = freshness_thresholds.get(tf, 300_000)
                    if age_ms <= threshold:
                        ctx.features_map[(symbol, tf)] = decoded
                        ctx.symbols_tfs.append((symbol, tf))
            
            elif key_type == 'pred':
                ctx.pred_map[(symbol, tf)] = decoded
            
            elif key_type == 'orderbook':
                ctx.orderbook_map[symbol] = decoded
        
    except Exception as e:
        logger.warning(f"[BATCH_UTILS] Pipeline fetch failed: {e}")
    
    return ctx


# ============================================================================
# Vectorized Feature Assembly
# ============================================================================

def assemble_feature_batch(
    ctx: BatchContext,
    expected_dim: int,
    exclude_keys: Optional[set] = None,
    use_pinned_memory: bool = True,
) -> np.ndarray:
    """
    Convert feature dicts to a [B, D] numpy array with vectorized sanitization.
    
    This replaces per-item tensor creation with a single batch assembly,
    reducing CPU overhead and enabling efficient GPU transfer.
    
    Args:
        ctx: BatchContext with populated features_map and symbols_tfs
        expected_dim: Expected feature dimension D
        exclude_keys: Set of keys to skip (metadata fields)
        use_pinned_memory: Whether to use page-locked memory (for async H2D)
    
    Returns:
        np.ndarray of shape [B, D] with dtype float32
    """
    if exclude_keys is None:
        exclude_keys = {'ts_ms', 'symbol', 'timeframe', 'timestamp'}
    
    B = len(ctx.symbols_tfs)
    if B == 0:
        ctx.obs_np = np.zeros((0, expected_dim), dtype=np.float32)
        return ctx.obs_np
    
    # Pre-allocate output array
    obs_np = np.zeros((B, expected_dim), dtype=np.float32)
    
    for i, (symbol, tf) in enumerate(ctx.symbols_tfs):
        features = ctx.features_map.get((symbol, tf), {})
        
        # Extract numeric values in consistent order
        numeric_values = []
        for key, value in features.items():
            # Skip metadata
            if key in exclude_keys or 'timestamp' in key.lower():
                continue
            
            try:
                val = float(value)
                # Will be sanitized vectorized below
                numeric_values.append(val)
            except (ValueError, TypeError):
                continue
        
        # Truncate or pad to expected_dim
        n = len(numeric_values)
        if n > expected_dim:
            obs_np[i, :] = numeric_values[:expected_dim]
        else:
            obs_np[i, :n] = numeric_values
            # Rest stays as zeros (pre-initialized)
    
    # Vectorized sanitization: nan_to_num + clamp
    obs_np = np.nan_to_num(obs_np, nan=0.0, posinf=0.0, neginf=0.0)
    np.clip(obs_np, -1e6, 1e6, out=obs_np)
    
    # Make contiguous for efficient GPU transfer
    obs_np = np.ascontiguousarray(obs_np, dtype=np.float32)
    
    ctx.obs_np = obs_np
    return obs_np


def transfer_to_gpu(
    obs_np: np.ndarray,
    device,
    use_pinned: bool = True,
    non_blocking: bool = True,
):
    """
    Transfer CPU numpy array to GPU tensor efficiently.
    
    Uses pinned memory for truly non-blocking transfer when possible.
    
    Args:
        obs_np: NumPy array of shape [B, D]
        device: torch device
        use_pinned: Use pinned (page-locked) memory
        non_blocking: Use non-blocking transfer
    
    Returns:
        torch.Tensor on device
    """
    import torch
    
    if obs_np.size == 0:
        return torch.empty((0, obs_np.shape[1] if obs_np.ndim > 1 else 0), 
                          dtype=torch.float32, device=device)
    
    # Ensure contiguous
    if not obs_np.flags['C_CONTIGUOUS']:
        obs_np = np.ascontiguousarray(obs_np)
    
    if use_pinned and device.type == 'cuda':
        # Create pinned tensor on CPU, then transfer
        obs_cpu = torch.from_numpy(obs_np).pin_memory()
        obs_gpu = obs_cpu.to(device, non_blocking=non_blocking)
    else:
        # Direct transfer (may block)
        obs_gpu = torch.from_numpy(obs_np).to(device, non_blocking=non_blocking)
    
    return obs_gpu


# ============================================================================
# Optional Background Prefetch Worker
# ============================================================================

class PrefetchWorker:
    """
    Background worker that prefetches Redis data one cycle ahead.
    
    This is OPTIONAL and disabled by default (ENABLE_PREFETCH=0).
    When enabled, the main loop can consume pre-fetched data if available,
    otherwise falls back to synchronous fetch.
    """
    
    def __init__(self, redis_client, symbols: List[str], timeframes: List[str]):
        self.redis_client = redis_client
        self.symbols = symbols
        self.timeframes = timeframes
        
        self._queue: queue.Queue = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the prefetch worker thread."""
        if not ENABLE_PREFETCH:
            logger.info("[PREFETCH] Disabled (ENABLE_PREFETCH=0)")
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        logger.info("[PREFETCH] Worker started")
    
    def stop(self):
        """Stop the prefetch worker thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("[PREFETCH] Worker stopped")
    
    def get_prefetched(self, timeout: float = 0.01) -> Optional[BatchContext]:
        """
        Get prefetched data if available.
        
        Returns None if no prefetched data is ready (caller should fallback).
        """
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
    
    def _worker_loop(self):
        """Background loop that continuously prefetches data."""
        while not self._stop_event.is_set():
            try:
                # Build symbol/tf pairs
                pairs = [(s, tf) for s in self.symbols for tf in self.timeframes]
                
                # Fetch via pipeline
                ctx = pipeline_fetch_features(
                    self.redis_client,
                    pairs,
                    include_predictions=True,
                    include_orderbook=False,
                )
                
                # Put in queue (non-blocking, drop if full)
                try:
                    self._queue.put_nowait(ctx)
                except queue.Full:
                    pass  # Discard old data
                
                # Sleep briefly before next prefetch
                time.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"[PREFETCH] Worker error: {e}")
                time.sleep(1.0)


# ============================================================================
# GPU Math Optimizations
# ============================================================================

def configure_gpu_optimizations(device=None):
    """
    Configure GPU math optimizations for inference/training.
    
    Enables TF32 for matrix multiplications (safe precision tradeoff).
    Does NOT enable AMP unless already enabled.
    
    Call this once at trainer initialization.
    """
    try:
        import torch
        
        if torch.cuda.is_available():
            # Enable TF32 for Tensor Cores (RTX 30xx, 40xx, 50xx)
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            
            # Set float32 matmul precision to "high" (uses TF32)
            torch.set_float32_matmul_precision("high")
            
            # Enable cuDNN benchmarking for stable workloads
            torch.backends.cudnn.benchmark = True
            
            logger.info(
                f"[GPU_OPT] TF32 enabled, matmul_precision=high, cudnn.benchmark=True"
            )
            
            if device is not None:
                gpu_name = torch.cuda.get_device_name(device)
                logger.info(f"[GPU_OPT] Device: {gpu_name}")
        else:
            logger.info("[GPU_OPT] CUDA not available, skipping GPU optimizations")
            
    except Exception as e:
        logger.warning(f"[GPU_OPT] Failed to configure: {e}")


# ============================================================================
# Batched MASA Forward Helper
# ============================================================================

def batched_masa_forward(
    masa_model,
    obs_gpu,
    ppo_proxy=None,
    clamp_input: float = 10.0,
    clamp_output: float = 20.0,
):
    """
    Efficient batched MASA forward pass.
    
    Performs dimension check once for the batch, not per-item.
    Vectorized sanitization of outputs.
    
    Args:
        masa_model: MASA model with forward() method
        obs_gpu: [B, D] tensor on GPU
        ppo_proxy: Optional [B] or [B, A] tensor to use as fallback
        clamp_input: Input clamp magnitude
        clamp_output: Output clamp magnitude
    
    Returns:
        Tuple of (logits, is_valid, repair_count)
        - logits: [B, A] or [B] tensor of action logits
        - is_valid: bool indicating if MASA output is valid
        - repair_count: int, number of params repaired
    """
    import torch
    
    try:
        # Get device from model
        try:
            masa_device = next(masa_model.parameters()).device
        except StopIteration:
            masa_device = obs_gpu.device
        
        # Transfer and sanitize input ONCE for batch
        x = obs_gpu.to(dtype=torch.float32, device=masa_device, non_blocking=True)
        x = torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        x = torch.clamp(x, -clamp_input, clamp_input)
        x = x.contiguous()
        
        # Dimension check ONCE for batch
        expected_dim = getattr(getattr(masa_model, "config", None), "obs_dim", None)
        if expected_dim is not None and x.shape[-1] != expected_dim:
            logger.warning(
                f"[MASA_BATCH] obs_dim mismatch: got {x.shape[-1]}, expected {expected_dim}"
            )
            if ppo_proxy is not None:
                return ppo_proxy.to(dtype=torch.float32, device=masa_device), False, 0
            return torch.zeros((x.shape[0],), device=masa_device, dtype=torch.float32), False, 0
        
        # Ensure batch dimension
        if x.dim() == 1:
            x = x.unsqueeze(0)
        
        # Forward pass
        prev_mode = masa_model.training
        masa_model.eval()
        repair_count = 0
        
        with torch.no_grad():
            with torch.amp.autocast('cuda', enabled=False):
                out = masa_model(x)
                if isinstance(out, tuple):
                    out = out[0]
        
        # Vectorized finite check
        finite_mask = torch.isfinite(out)
        if not finite_mask.all():
            # Replace non-finite with zeros
            out = torch.where(finite_mask, out, torch.zeros_like(out))
            repair_count = (~finite_mask).sum().item()
        
        # Clamp outputs
        out = torch.clamp(out.to(torch.float32), -clamp_output, clamp_output)
        
        # Check for collapsed logits (std too low)
        is_valid = True
        try:
            std = float(out.std().item())
            if std < 1e-6:
                logger.warning(f"[MASA_BATCH] Collapsed logits (std={std:.2e})")
                is_valid = False
                if ppo_proxy is not None:
                    out = ppo_proxy.to(dtype=torch.float32, device=masa_device)
                else:
                    out = torch.zeros_like(out)
        except Exception:
            pass
        
        masa_model.train(prev_mode)
        return out, is_valid, repair_count
        
    except Exception as e:
        logger.warning(f"[MASA_BATCH] Forward failed: {e}")
        if ppo_proxy is not None:
            return ppo_proxy.to(dtype=torch.float32), False, 0
        return torch.zeros((obs_gpu.shape[0],), device=obs_gpu.device, dtype=torch.float32), False, 0
























