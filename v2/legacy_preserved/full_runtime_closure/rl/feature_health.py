"""
Feature Health Monitoring and Fail-Closed Gating

This module monitors the health of feature vectors and blocks entry signals
when features are unhealthy (stale, sparse, or malformed).

Key Concepts:
- Nonzero ratio: Percentage of non-zero values in feature vector
- Staleness: Time since last update of feature data
- Numeric count: Number of valid numeric features (not NaN/Inf)

Actions are classified as:
- Entry actions: OPEN_LONG, OPEN_SHORT, INCREASE_*, FLIP actions
- Protective actions: CLOSE_*, DECREASE_*, PARTIAL_CLOSE, REDUCE, HOLD

When feature health fails:
- Entry actions are BLOCKED with reason_code=FEATURE_HEALTH_BLOCK
- Protective actions are ALLOWED (fail-safe for exits)
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class FeatureSlice(Enum):
    """Known feature slices in the observation vector."""
    OHLCV = "ohlcv"
    TECHNICAL = "technical"
    ORDERBOOK = "orderbook"
    MICROSTRUCTURE = "microstructure"
    VOLATILITY = "volatility"
    LIQUIDATION = "liquidation"
    PORTFOLIO = "portfolio"
    ONCHAIN = "onchain"
    POSITION_CONTEXT = "position_context"


@dataclass
class SliceHealth:
    """Health metrics for a single feature slice."""
    name: str
    size: int
    nonzero_count: int
    nonzero_ratio: float
    nan_count: int
    inf_count: int
    last_update_ms: int = 0
    staleness_ms: int = 0
    is_healthy: bool = True
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "size": self.size,
            "nonzero_ratio": round(self.nonzero_ratio, 3),
            "staleness_ms": self.staleness_ms,
            "is_healthy": self.is_healthy,
            "reason": self.reason,
        }


@dataclass 
class FeatureHealthReport:
    """Complete health report for a feature vector."""
    symbol: str
    timeframe: str
    timestamp_ms: int
    
    # Overall metrics
    total_dim: int = 0
    numeric_count: int = 0
    nonzero_count: int = 0
    nonzero_ratio: float = 0.0
    nan_count: int = 0
    inf_count: int = 0
    
    # Slice-level health
    slice_health: Dict[str, SliceHealth] = field(default_factory=dict)
    
    # Overall decision
    is_healthy: bool = True
    block_reason: str = ""
    missing_keys: List[str] = field(default_factory=list)
    
    def to_log_line(self) -> str:
        """Format as structured log line."""
        stale_info = ",".join(
            f"{k}:{v.staleness_ms}ms" 
            for k, v in self.slice_health.items() 
            if v.staleness_ms > 0
        )
        missing_str = ",".join(self.missing_keys[:5]) if self.missing_keys else "none"
        
        return (
            f"FEATURE_HEALTH | {self.symbol} | {self.timeframe} | "
            f"dim={self.total_dim} | numeric={self.numeric_count} | "
            f"nonzero={self.nonzero_ratio:.2f} | "
            f"stale_ms={{{stale_info or 'ok'}}} | "
            f"missing_keys=[{missing_str}] | "
            f"healthy={self.is_healthy}"
        )


class FeatureHealthMonitor:
    """
    Monitors feature vector health and provides gating decisions.
    
    Usage:
        monitor = FeatureHealthMonitor(config)
        report = monitor.check_health(symbol, tf, features, metadata)
        if not report.is_healthy and monitor.is_entry_action(action):
            # Block the signal
    """
    
    # Entry actions that should be blocked when features are unhealthy
    ENTRY_ACTIONS = {
        'OPEN_LONG', 'OPEN_SHORT',
        'INCREASE_LONG', 'INCREASE_SHORT',
        'CLOSE_LONG_AND_OPEN_SHORT', 'CLOSE_SHORT_AND_OPEN_LONG',
        'CLOSE_AND_LONG', 'CLOSE_AND_SHORT',
        'FLIP_TO_LONG', 'FLIP_TO_SHORT',
    }
    
    # Protective actions allowed even when features are unhealthy
    PROTECTIVE_ACTIONS = {
        'CLOSE_LONG', 'CLOSE_SHORT', 'CLOSE_ALL',
        'DECREASE_LONG', 'DECREASE_SHORT',
        'PARTIAL_CLOSE', 'REDUCE', 'HOLD',
    }
    
    def __init__(
        self,
        min_nonzero_ratio: float = 0.3,
        max_staleness_ms: int = 30000,
        min_numeric_count: int = 16,
    ):
        self.min_nonzero_ratio = min_nonzero_ratio
        self.max_staleness_ms = max_staleness_ms
        self.min_numeric_count = min_numeric_count
        
        # Cache of last reports per symbol/tf
        self._last_reports: Dict[str, FeatureHealthReport] = {}
        self._log_cycle_count = 0
        
    def check_health(
        self,
        symbol: str,
        timeframe: str,
        features: np.ndarray,
        metadata: Optional[Dict] = None,
        slice_info: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> FeatureHealthReport:
        """
        Check health of feature vector.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            timeframe: Timeframe (e.g., 5m)
            features: Numpy array of feature values
            metadata: Optional dict with last_update_ms per slice
            slice_info: Optional dict mapping slice name to (start_idx, end_idx)
            
        Returns:
            FeatureHealthReport with health status and metrics
        """
        now_ms = int(time.time() * 1000)
        
        report = FeatureHealthReport(
            symbol=symbol,
            timeframe=timeframe,
            timestamp_ms=now_ms,
        )
        
        if features is None or len(features) == 0:
            report.is_healthy = False
            report.block_reason = "EMPTY_FEATURES"
            return report
        
        # Convert to numpy if tensor
        if hasattr(features, 'cpu'):
            features = features.cpu().numpy()
        features = np.asarray(features).flatten()
        
        # Overall metrics
        report.total_dim = len(features)
        
        # Count valid numeric values (not NaN/Inf)
        valid_mask = np.isfinite(features)
        report.numeric_count = int(np.sum(valid_mask))
        report.nan_count = int(np.sum(np.isnan(features)))
        report.inf_count = int(np.sum(np.isinf(features)))
        
        # Nonzero ratio (only among valid values)
        valid_features = features[valid_mask]
        if len(valid_features) > 0:
            report.nonzero_count = int(np.count_nonzero(valid_features))
            report.nonzero_ratio = report.nonzero_count / len(valid_features)
        else:
            report.nonzero_count = 0
            report.nonzero_ratio = 0.0
        
        # Check slice-level health if slice info provided
        if slice_info:
            for slice_name, (start, end) in slice_info.items():
                if start < len(features) and end <= len(features):
                    slice_data = features[start:end]
                    slice_valid = np.isfinite(slice_data)
                    slice_valid_data = slice_data[slice_valid]
                    
                    slice_nonzero = int(np.count_nonzero(slice_valid_data)) if len(slice_valid_data) > 0 else 0
                    slice_nonzero_ratio = slice_nonzero / len(slice_valid_data) if len(slice_valid_data) > 0 else 0.0
                    
                    # Get staleness from metadata if available
                    staleness_ms = 0
                    if metadata and slice_name in metadata:
                        last_update = metadata.get(slice_name, {}).get("last_update_ms", 0)
                        if last_update > 0:
                            staleness_ms = now_ms - last_update
                    
                    slice_healthy = slice_nonzero_ratio >= self.min_nonzero_ratio / 2  # Looser per-slice
                    slice_healthy = slice_healthy and staleness_ms < self.max_staleness_ms
                    
                    report.slice_health[slice_name] = SliceHealth(
                        name=slice_name,
                        size=end - start,
                        nonzero_count=slice_nonzero,
                        nonzero_ratio=slice_nonzero_ratio,
                        nan_count=int(np.sum(np.isnan(slice_data))),
                        inf_count=int(np.sum(np.isinf(slice_data))),
                        staleness_ms=staleness_ms,
                        is_healthy=slice_healthy,
                        reason="" if slice_healthy else f"sparse_or_stale:{staleness_ms}ms",
                    )
        
        # Determine overall health
        block_reasons = []
        
        if report.numeric_count < self.min_numeric_count:
            block_reasons.append(f"TOO_FEW_NUMERIC:{report.numeric_count}/{self.min_numeric_count}")
        
        if report.nonzero_ratio < self.min_nonzero_ratio:
            block_reasons.append(f"LOW_NONZERO_RATIO:{report.nonzero_ratio:.2f}<{self.min_nonzero_ratio}")
        
        if report.nan_count > 0 or report.inf_count > 0:
            block_reasons.append(f"INVALID_VALUES:nan={report.nan_count},inf={report.inf_count}")
        
        # Check for stale slices
        for slice_name, slice_health in report.slice_health.items():
            if slice_health.staleness_ms > self.max_staleness_ms:
                block_reasons.append(f"STALE_{slice_name.upper()}:{slice_health.staleness_ms}ms")
        
        if block_reasons:
            report.is_healthy = False
            report.block_reason = "|".join(block_reasons)
        
        # Cache report
        cache_key = f"{symbol}:{timeframe}"
        self._last_reports[cache_key] = report
        
        return report
    
    def is_entry_action(self, action) -> bool:
        """Check if action is an entry/exposure-increasing action."""
        # Handle int action indices (from model)
        if isinstance(action, (int, float)):
            # Treat int actions conservatively as entry (block when unhealthy)
            return True
        if not action:
            return False
        return str(action).upper() in self.ENTRY_ACTIONS
    
    def is_protective_action(self, action) -> bool:
        """Check if action is a protective/exposure-reducing action."""
        # Handle int action indices (from model)
        if isinstance(action, (int, float)):
            # HOLD (index 0 or 6) is protective
            if int(action) in (0, 6):
                return True
            return False
        if not action:
            return False
        return str(action).upper() in self.PROTECTIVE_ACTIONS
    
    def should_block_action(
        self,
        action: str,
        report: FeatureHealthReport,
    ) -> Tuple[bool, Optional[str]]:
        """
        Determine if action should be blocked based on feature health.
        
        Returns:
            (should_block, reason_code)
        """
        if report.is_healthy:
            return False, None
        
        if self.is_protective_action(action):
            # Allow protective actions even when unhealthy
            return False, None
        
        if self.is_entry_action(action):
            return True, f"FEATURE_HEALTH_BLOCK:{report.block_reason}"
        
        # Unknown action - be conservative, block if unhealthy
        return True, f"FEATURE_HEALTH_BLOCK:UNKNOWN_ACTION:{report.block_reason}"
    
    def log_health_report(self, report: FeatureHealthReport, force: bool = False):
        """Log health report (rate-limited unless force=True)."""
        self._log_cycle_count += 1
        
        # Log every 10 cycles or if unhealthy or if forced
        from config import ENABLE_FEATURE_FRESHNESS_LOG, FEATURE_FRESHNESS_LOG_CYCLE_INTERVAL
        
        should_log = (
            force or 
            not report.is_healthy or 
            (ENABLE_FEATURE_FRESHNESS_LOG and 
             self._log_cycle_count % FEATURE_FRESHNESS_LOG_CYCLE_INTERVAL == 0)
        )
        
        if should_log:
            if report.is_healthy:
                logger.debug(report.to_log_line())
            else:
                logger.warning(report.to_log_line())
    
    def get_last_report(self, symbol: str, timeframe: str) -> Optional[FeatureHealthReport]:
        """Get cached health report for symbol/tf."""
        return self._last_reports.get(f"{symbol}:{timeframe}")
    
    def get_all_unhealthy(self) -> List[FeatureHealthReport]:
        """Get all currently unhealthy symbol/tf pairs."""
        return [r for r in self._last_reports.values() if not r.is_healthy]


# Global instance
_feature_health_monitor: Optional[FeatureHealthMonitor] = None


def get_feature_health_monitor() -> FeatureHealthMonitor:
    """Get global feature health monitor instance."""
    global _feature_health_monitor
    if _feature_health_monitor is None:
        from config import (
            FEATURE_HEALTH_MIN_NONZERO_RATIO,
            FEATURE_HEALTH_MAX_STALENESS_MS,
            FEATURE_HEALTH_MIN_NUMERIC_COUNT,
        )
        _feature_health_monitor = FeatureHealthMonitor(
            min_nonzero_ratio=FEATURE_HEALTH_MIN_NONZERO_RATIO,
            max_staleness_ms=FEATURE_HEALTH_MAX_STALENESS_MS,
            min_numeric_count=FEATURE_HEALTH_MIN_NUMERIC_COUNT,
        )
    return _feature_health_monitor


def check_feature_health(
    symbol: str,
    timeframe: str,
    features: np.ndarray,
    metadata: Optional[Dict] = None,
) -> FeatureHealthReport:
    """Convenience function to check feature health."""
    return get_feature_health_monitor().check_health(symbol, timeframe, features, metadata)


def should_block_entry(
    action: str,
    symbol: str,
    timeframe: str,
    features: np.ndarray,
    metadata: Optional[Dict] = None,
) -> Tuple[bool, Optional[str], Optional[FeatureHealthReport]]:
    """
    Check if entry action should be blocked due to feature health.
    
    Returns:
        (should_block, reason_code, report)
    """
    monitor = get_feature_health_monitor()
    report = monitor.check_health(symbol, timeframe, features, metadata)
    should_block, reason = monitor.should_block_action(action, report)
    return should_block, reason, report

