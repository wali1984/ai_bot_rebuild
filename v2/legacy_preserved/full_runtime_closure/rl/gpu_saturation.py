"""
GPU Saturation Module for RTX 5080

This module provides optimizations to achieve 40-75% steady GPU utilization:
1. Larger batch sizes for GPU saturation
2. Gradient accumulation for effective large batches
3. CUDA stream management for overlapping compute/transfer
4. Pre-allocated pinned memory buffers
5. Async data prefetching

IMPORTANT: These are throughput-only optimizations that do NOT change:
- Trading logic, thresholds, or action mappings
- Confidence formulas or gating logic
- MASA behavior or cooldowns
"""

import os
import time
import logging
import threading
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


# ============================================================================
# Environment Configuration for GPU Saturation
# ============================================================================

# Target GPU utilization percentages
TARGET_GPU_UTIL_LOW = float(os.getenv("TARGET_GPU_UTIL_LOW", "0.40"))  # 40% minimum
TARGET_GPU_UTIL_HIGH = float(os.getenv("TARGET_GPU_UTIL_HIGH", "0.75"))  # 75% maximum
TARGET_VRAM_UTIL = float(os.getenv("TARGET_VRAM_UTIL", "0.70"))  # 70% VRAM target

# Batch size multiplier for GPU saturation
GPU_BATCH_MULTIPLIER = int(os.getenv("GPU_BATCH_MULTIPLIER", "2"))  # 2x default batch

# Enable gradient accumulation for larger effective batches
ENABLE_GRAD_ACCUMULATION = os.getenv("ENABLE_GRAD_ACCUMULATION", "0") == "1"
GRAD_ACCUMULATION_STEPS = int(os.getenv("GRAD_ACCUMULATION_STEPS", "2"))


# ============================================================================
# GPU Optimization Configuration
# ============================================================================

@dataclass
class GPUSaturationConfig:
    """Configuration for GPU saturation optimizations."""
    
    # Batch sizes (will be applied to training)
    min_batch_size: int = 2048
    target_batch_size: int = 4096  # Increased from 2048
    max_batch_size: int = 8192
    
    # Network sizes for GPU saturation
    features_dim: int = 2048
    hidden_sizes: Tuple[int, ...] = (2048, 1024, 512, 256)
    
    # CUDA optimizations
    use_cuda_graphs: bool = False  # Disabled for stability
    use_async_transfers: bool = True
    use_pinned_memory: bool = True
    num_cuda_streams: int = 2
    
    # Memory management
    target_vram_pct: float = 0.70  # 70% VRAM utilization target
    memory_fraction: float = 0.75  # Allow up to 75% of VRAM
    
    # Timing/profiling
    profile_interval: int = 10  # Profile every N batches


def get_optimal_batch_size(vram_gb: float = 16.0, feature_dim: int = 1911) -> int:
    """
    Calculate optimal batch size based on available VRAM and feature dimensions.
    
    For RTX 5080 with 16GB VRAM:
    - Each sample: ~1911 features × 4 bytes = 7.6KB
    - Policy network: ~50-100MB
    - Rollout buffer: batch_size × n_steps × feature_dim × 4 bytes
    
    Target: 70% VRAM utilization for steady high GPU usage
    """
    # Available VRAM for batch processing (subtract model overhead)
    model_overhead_gb = 0.5  # Approximate model size
    buffer_overhead_gb = 1.0  # Rollout buffer, optimizer states
    available_gb = vram_gb * TARGET_VRAM_UTIL - model_overhead_gb - buffer_overhead_gb
    
    if available_gb <= 0:
        return 2048  # Safe default
    
    # Calculate max batch size that fits
    bytes_per_sample = feature_dim * 4  # float32
    max_samples = int((available_gb * 1e9) / bytes_per_sample)
    
    # Round down to power of 2 for efficient GPU processing
    batch_size = 2048  # Minimum
    while batch_size * 2 <= max_samples and batch_size * 2 <= 16384:
        batch_size *= 2
    
    # Cap at reasonable maximum
    batch_size = min(batch_size, 8192)
    
    logger.info(f"[GPU_SAT] Calculated optimal batch_size={batch_size} for {vram_gb}GB VRAM, {feature_dim} features")
    return batch_size


# ============================================================================
# CUDA Stream Manager
# ============================================================================

class CUDAStreamManager:
    """
    Manages CUDA streams for overlapping compute and data transfer.
    
    Uses separate streams for:
    - compute_stream: Model forward/backward passes
    - transfer_stream: Host-to-device and device-to-host transfers
    
    This allows data transfer to overlap with computation for higher GPU utilization.
    """
    
    def __init__(self, num_streams: int = 2):
        self.num_streams = num_streams
        self.streams = []
        self.events = []
        self._initialized = False
        
        if torch.cuda.is_available():
            self._init_streams()
    
    def _init_streams(self):
        """Initialize CUDA streams and events."""
        try:
            for i in range(self.num_streams):
                stream = torch.cuda.Stream()
                event = torch.cuda.Event(enable_timing=True)
                self.streams.append(stream)
                self.events.append(event)
            
            self._initialized = True
            logger.info(f"[CUDA_STREAMS] Initialized {self.num_streams} streams for overlapping compute/transfer")
        except Exception as e:
            logger.warning(f"[CUDA_STREAMS] Failed to initialize: {e}")
            self._initialized = False
    
    @property
    def compute_stream(self):
        """Stream for compute operations."""
        if self._initialized and len(self.streams) > 0:
            return self.streams[0]
        return None
    
    @property
    def transfer_stream(self):
        """Stream for data transfer operations."""
        if self._initialized and len(self.streams) > 1:
            return self.streams[1]
        return self.compute_stream
    
    def synchronize_all(self):
        """Synchronize all streams."""
        if self._initialized:
            for stream in self.streams:
                stream.synchronize()
    
    def record_event(self, stream_idx: int = 0):
        """Record an event on a stream."""
        if self._initialized and stream_idx < len(self.events):
            self.events[stream_idx].record(self.streams[stream_idx])
    
    def wait_event(self, event_idx: int, stream_idx: int):
        """Make a stream wait for an event."""
        if self._initialized:
            if event_idx < len(self.events) and stream_idx < len(self.streams):
                self.streams[stream_idx].wait_event(self.events[event_idx])


# Global stream manager instance
_stream_manager: Optional[CUDAStreamManager] = None


def get_stream_manager() -> Optional[CUDAStreamManager]:
    """Get or create the global CUDA stream manager."""
    global _stream_manager
    if _stream_manager is None and torch.cuda.is_available():
        _stream_manager = CUDAStreamManager()
    return _stream_manager


# ============================================================================
# Pinned Memory Buffer Pool
# ============================================================================

class PinnedMemoryPool:
    """
    Pre-allocated pinned memory buffers for efficient GPU transfers.
    
    Pinned (page-locked) memory enables truly async H2D transfers,
    reducing CPU-GPU synchronization overhead.
    """
    
    def __init__(self, buffer_shapes: Dict[str, Tuple[int, ...]], dtype=torch.float32):
        self.buffers: Dict[str, torch.Tensor] = {}
        self.dtype = dtype
        self._lock = threading.Lock()
        
        for name, shape in buffer_shapes.items():
            try:
                buf = torch.empty(shape, dtype=dtype, pin_memory=True)
                self.buffers[name] = buf
                logger.debug(f"[PIN_MEM] Allocated pinned buffer '{name}': {shape}")
            except Exception as e:
                logger.warning(f"[PIN_MEM] Failed to allocate '{name}': {e}")
    
    def get_buffer(self, name: str) -> Optional[torch.Tensor]:
        """Get a pre-allocated pinned buffer."""
        return self.buffers.get(name)
    
    def copy_to_gpu(self, name: str, data: np.ndarray, device, non_blocking: bool = True) -> torch.Tensor:
        """
        Copy numpy data to GPU via pinned buffer.
        
        This is faster than torch.from_numpy().to(device) because:
        1. Data is copied to pre-allocated pinned memory (no allocation)
        2. GPU transfer is truly async with non_blocking=True
        """
        with self._lock:
            buf = self.buffers.get(name)
            if buf is None:
                # Fallback: direct transfer
                return torch.from_numpy(data).to(device, non_blocking=non_blocking)
            
            # Check shape compatibility
            if buf.shape != data.shape:
                # Reallocate if shape changed
                try:
                    buf = torch.empty(data.shape, dtype=self.dtype, pin_memory=True)
                    self.buffers[name] = buf
                except Exception:
                    return torch.from_numpy(data).to(device, non_blocking=non_blocking)
            
            # Copy to pinned buffer
            buf.copy_(torch.from_numpy(data))
            
            # Transfer to GPU
            return buf.to(device, non_blocking=non_blocking)


# ============================================================================
# GPU Utilization Monitor
# ============================================================================

class GPUUtilizationMonitor:
    """
    Monitors GPU utilization and suggests optimizations.
    
    Tracks:
    - GPU compute utilization %
    - VRAM utilization %
    - Kernel execution time
    - Memory bandwidth utilization
    """
    
    def __init__(self, target_util_low: float = 0.40, target_util_high: float = 0.75):
        self.target_low = target_util_low
        self.target_high = target_util_high
        self.history = []
        self.max_history = 100
        
        self._nvml_handle = None
        self._init_nvml()
    
    def _init_nvml(self):
        """Initialize NVML for GPU monitoring."""
        try:
            import pynvml as nvml
            nvml.nvmlInit()
            self._nvml_handle = nvml.nvmlDeviceGetHandleByIndex(0)
            logger.debug("[GPU_MON] NVML initialized successfully")
        except Exception as e:
            logger.debug(f"[GPU_MON] NVML not available: {e}")
            self._nvml_handle = None
    
    def get_utilization(self) -> Dict[str, float]:
        """Get current GPU utilization metrics."""
        result = {
            'gpu_util': 0.0,
            'vram_util': 0.0,
            'vram_used_gb': 0.0,
            'vram_total_gb': 16.0,
            'temperature': 0.0,
        }
        
        try:
            import pynvml as nvml
            if self._nvml_handle:
                util = nvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                mem = nvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                temp = nvml.nvmlDeviceGetTemperature(self._nvml_handle, nvml.NVML_TEMPERATURE_GPU)
                
                result['gpu_util'] = util.gpu / 100.0
                result['vram_used_gb'] = mem.used / 1e9
                result['vram_total_gb'] = mem.total / 1e9
                result['vram_util'] = mem.used / mem.total
                result['temperature'] = float(temp)
        except Exception:
            pass
        
        # Record history
        self.history.append({
            'timestamp': time.time(),
            **result
        })
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
        
        return result
    
    def get_average_utilization(self, window: int = 10) -> Dict[str, float]:
        """Get average utilization over last N samples."""
        if not self.history:
            return {'gpu_util': 0.0, 'vram_util': 0.0}
        
        recent = self.history[-window:]
        return {
            'gpu_util': sum(h['gpu_util'] for h in recent) / len(recent),
            'vram_util': sum(h['vram_util'] for h in recent) / len(recent),
        }
    
    def suggest_batch_adjustment(self, current_batch_size: int) -> Tuple[int, str]:
        """
        Suggest batch size adjustment based on utilization.
        
        Returns:
            (new_batch_size, reason)
        """
        avg = self.get_average_utilization()
        gpu_util = avg['gpu_util']
        vram_util = avg['vram_util']
        
        if gpu_util < self.target_low and vram_util < TARGET_VRAM_UTIL - 0.1:
            # GPU underutilized, VRAM has room - increase batch
            new_size = min(current_batch_size * 2, 16384)
            return new_size, f"GPU underutilized ({gpu_util*100:.1f}%)"
        
        elif gpu_util > self.target_high or vram_util > TARGET_VRAM_UTIL + 0.1:
            # GPU overutilized or VRAM pressure - decrease batch
            new_size = max(current_batch_size // 2, 512)
            return new_size, f"GPU overutilized ({gpu_util*100:.1f}%) or VRAM high ({vram_util*100:.1f}%)"
        
        return current_batch_size, "utilization optimal"


# Global monitor instance
_gpu_monitor: Optional[GPUUtilizationMonitor] = None


def get_gpu_monitor() -> GPUUtilizationMonitor:
    """Get or create the global GPU utilization monitor."""
    global _gpu_monitor
    if _gpu_monitor is None:
        _gpu_monitor = GPUUtilizationMonitor(TARGET_GPU_UTIL_LOW, TARGET_GPU_UTIL_HIGH)
    return _gpu_monitor


# ============================================================================
# Training Batch Optimizer
# ============================================================================

def optimize_ppo_for_gpu_saturation(
    ppo_model,
    target_vram_pct: float = 0.70,
    min_batch: int = 2048,
    max_batch: int = 8192,
) -> Dict[str, Any]:
    """
    Optimize PPO hyperparameters for GPU saturation.
    
    This function adjusts batch_size and other parameters to achieve
    target GPU utilization without changing trading logic.
    
    Args:
        ppo_model: SB3 PPO model instance
        target_vram_pct: Target VRAM utilization (0.0-1.0)
        min_batch: Minimum batch size
        max_batch: Maximum batch size
    
    Returns:
        Dict with applied optimizations
    """
    if not torch.cuda.is_available():
        return {'status': 'skipped', 'reason': 'CUDA not available'}
    
    # Get current settings
    current_batch = getattr(ppo_model, 'batch_size', 2048)
    current_n_envs = getattr(ppo_model, 'n_envs', 65)
    current_n_steps = getattr(ppo_model, 'n_steps', 512)
    
    # Calculate total samples per rollout
    samples_per_rollout = current_n_envs * current_n_steps
    
    # Get VRAM info
    vram_total = torch.cuda.get_device_properties(0).total_memory / 1e9
    vram_used = torch.cuda.memory_allocated() / 1e9
    vram_free = vram_total - vram_used
    
    # Calculate optimal batch size
    # Larger batches = better GPU utilization, but must fit in memory
    optimal_batch = get_optimal_batch_size(vram_total)
    optimal_batch = max(min_batch, min(optimal_batch, max_batch))
    
    # Ensure batch divides samples evenly
    while samples_per_rollout % optimal_batch != 0 and optimal_batch > min_batch:
        optimal_batch -= 128
    optimal_batch = max(min_batch, optimal_batch)
    
    result = {
        'status': 'applied',
        'previous_batch_size': current_batch,
        'new_batch_size': optimal_batch,
        'samples_per_rollout': samples_per_rollout,
        'vram_total_gb': vram_total,
        'vram_used_gb': vram_used,
        'target_vram_pct': target_vram_pct,
    }
    
    # Apply new batch size if different
    if optimal_batch != current_batch:
        try:
            ppo_model.batch_size = optimal_batch
            logger.info(f"[GPU_SAT] Adjusted batch_size: {current_batch} → {optimal_batch}")
            result['batch_changed'] = True
        except Exception as e:
            logger.warning(f"[GPU_SAT] Failed to change batch_size: {e}")
            result['batch_changed'] = False
    else:
        result['batch_changed'] = False
    
    return result


# ============================================================================
# Integration Functions
# ============================================================================

def apply_gpu_saturation_settings(trainer):
    """
    Apply GPU saturation settings to a HybridTrainer instance.
    
    This is called during trainer initialization to set up optimal
    GPU utilization parameters.
    """
    if not torch.cuda.is_available():
        logger.info("[GPU_SAT] CUDA not available, skipping GPU saturation setup")
        return
    
    # Get VRAM info
    vram_total = torch.cuda.get_device_properties(0).total_memory / 1e9
    gpu_name = torch.cuda.get_device_name(0)
    
    logger.info(f"[GPU_SAT] Setting up GPU saturation for {gpu_name} ({vram_total:.1f}GB)")
    
    # Calculate optimal batch size
    feature_dim = 1911  # Current feature dimension
    optimal_batch = get_optimal_batch_size(vram_total, feature_dim)
    
    # Apply to config
    if hasattr(trainer, 'config'):
        old_batch = getattr(trainer.config, 'batch_size', 2048)
        
        # Only increase, never decrease (safety)
        if optimal_batch > old_batch:
            trainer.config.batch_size = optimal_batch
            logger.info(f"[GPU_SAT] Increased batch_size: {old_batch} → {optimal_batch}")
    
    # Initialize stream manager
    get_stream_manager()
    
    # Initialize GPU monitor
    get_gpu_monitor()
    
    logger.info("[GPU_SAT] GPU saturation setup complete")


def log_gpu_saturation_status():
    """Log current GPU saturation status."""
    monitor = get_gpu_monitor()
    if monitor:
        util = monitor.get_utilization()
        avg = monitor.get_average_utilization()
        
        logger.info(
            f"[GPU_SAT] Current: {util['gpu_util']*100:.1f}% GPU, {util['vram_util']*100:.1f}% VRAM, "
            f"Avg: {avg['gpu_util']*100:.1f}% GPU"
        )




















