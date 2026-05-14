"""
Drift Monitor — Feature, Policy, and Execution Quality Drift Detection

Monitors three drift dimensions:
  1. Feature drift (PSI/KL): detects when input feature distributions shift
  2. Policy drift: detects when model's action distribution changes
  3. Execution quality drift: detects degradation in fill rates, slippage, etc.

Uses Population Stability Index (PSI) for features and KL divergence for policies.
Publishes alerts to Redis and logs for observability.

Integration:
  - Instantiated in HybridTrainer.__init__
  - Feature distributions updated every prediction cycle
  - Policy distributions updated every prediction cycle
  - Background check every DRIFT_CHECK_INTERVAL_SEC
"""

import logging
import time
import threading
import json
import numpy as np
from collections import deque
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


def compute_psi(baseline: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """Compute Population Stability Index between two distributions.
    
    PSI = sum((actual_% - expected_%) * ln(actual_% / expected_%))
    
    Interpretation:
      < 0.10: No significant change
      0.10 - 0.25: Moderate change, investigate
      > 0.25: Significant change, action needed
    """
    if len(baseline) < 20 or len(current) < 20:
        return 0.0
    
    try:
        # Create bins from combined data for consistent binning
        combined = np.concatenate([baseline, current])
        bins = np.percentile(combined, np.linspace(0, 100, n_bins + 1))
        bins[0] = -np.inf
        bins[-1] = np.inf
        
        # Count in each bin
        base_counts = np.histogram(baseline, bins=bins)[0].astype(float)
        curr_counts = np.histogram(current, bins=bins)[0].astype(float)
        
        # Normalize to proportions (add small epsilon to avoid log(0))
        eps = 1e-6
        base_pct = base_counts / max(1, base_counts.sum()) + eps
        curr_pct = curr_counts / max(1, curr_counts.sum()) + eps
        
        # PSI
        psi = np.sum((curr_pct - base_pct) * np.log(curr_pct / base_pct))
        return float(np.clip(psi, 0.0, 100.0))
    except Exception:
        return 0.0


def compute_kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """Compute KL(P || Q) for discrete distributions.
    
    Both p and q should be probability distributions (sum to 1).
    """
    try:
        eps = 1e-8
        p = np.clip(p, eps, 1.0)
        q = np.clip(q, eps, 1.0)
        p = p / p.sum()
        q = q / q.sum()
        return float(np.sum(p * np.log(p / q)))
    except Exception:
        return 0.0


class FeatureDriftTracker:
    """Tracks feature distribution drift using PSI."""
    
    def __init__(self, window_size: int = 1000, n_features: int = 50):
        self.window_size = window_size
        self.n_features = n_features
        
        # Baseline and current windows
        self.baseline: Optional[np.ndarray] = None  # (window_size, n_features)
        self.current_buffer: List[np.ndarray] = []
        self._baseline_set = False
        self._feature_names: List[str] = []
    
    def set_baseline(self, features: np.ndarray) -> None:
        """Set the reference baseline distribution.
        
        Args:
            features: (N, D) array of feature vectors
        """
        self.baseline = features[-self.window_size:].copy()
        self.n_features = features.shape[1]
        self._baseline_set = True
        logger.info(f"[DRIFT] Feature baseline set: {self.baseline.shape}")
    
    def update(self, features: np.ndarray) -> None:
        """Add new feature observations to the current window.
        
        Args:
            features: (B, D) batch of feature vectors
        """
        self.current_buffer.append(features)
        
        # Auto-set baseline if not set and we have enough data
        if not self._baseline_set:
            total = sum(f.shape[0] for f in self.current_buffer)
            if total >= self.window_size:
                all_features = np.concatenate(self.current_buffer, axis=0)
                self.set_baseline(all_features[:self.window_size])
                self.current_buffer = [all_features[self.window_size:]] if len(all_features) > self.window_size else []
        
        # Trim buffer to prevent memory growth
        total_samples = sum(f.shape[0] for f in self.current_buffer)
        while total_samples > self.window_size * 2 and len(self.current_buffer) > 1:
            removed = self.current_buffer.pop(0)
            total_samples -= removed.shape[0]
    
    def compute_drift(self) -> Dict[str, float]:
        """Compute PSI for each feature dimension.
        
        Returns dict with:
            mean_psi: average PSI across features
            max_psi: maximum PSI across features
            drifted_features: number of features with PSI > threshold
            per_feature_psi: list of per-feature PSI values
        """
        if not self._baseline_set or not self.current_buffer:
            return {"mean_psi": 0.0, "max_psi": 0.0, "drifted_features": 0, "per_feature_psi": []}
        
        current = np.concatenate(self.current_buffer, axis=0)
        if len(current) < 20:
            return {"mean_psi": 0.0, "max_psi": 0.0, "drifted_features": 0, "per_feature_psi": []}
        
        # Use last window_size samples
        current = current[-self.window_size:]
        
        # Compute PSI per feature
        n_feat = min(self.baseline.shape[1], current.shape[1])
        psi_values = []
        for j in range(n_feat):
            psi = compute_psi(self.baseline[:, j], current[:, j])
            psi_values.append(psi)
        
        psi_arr = np.array(psi_values)
        
        return {
            "mean_psi": float(psi_arr.mean()),
            "max_psi": float(psi_arr.max()),
            "drifted_features": int((psi_arr > 0.25).sum()),
            "per_feature_psi": psi_values[:20],  # Top 20 for logging
        }


class PolicyDriftTracker:
    """Tracks policy action distribution drift using KL divergence."""
    
    def __init__(self, action_dim: int = 7, window_size: int = 500):
        self.action_dim = action_dim
        self.window_size = window_size
        
        # Action distribution history
        self.baseline_dist: Optional[np.ndarray] = None
        self.current_actions: deque = deque(maxlen=window_size)
        self._baseline_set = False
    
    def set_baseline(self, action_counts: np.ndarray) -> None:
        """Set baseline action distribution.
        
        Args:
            action_counts: (action_dim,) count per action
        """
        total = action_counts.sum()
        if total > 0:
            self.baseline_dist = action_counts / total
            self._baseline_set = True
            logger.info(f"[DRIFT] Policy baseline set: {self.baseline_dist.round(3).tolist()}")
    
    def update(self, action_idx: int) -> None:
        """Record a new action prediction."""
        self.current_actions.append(action_idx)
        
        # Auto-set baseline
        if not self._baseline_set and len(self.current_actions) >= self.window_size:
            counts = np.bincount(list(self.current_actions), minlength=self.action_dim).astype(float)
            self.set_baseline(counts)
    
    def update_batch(self, action_indices: np.ndarray) -> None:
        """Record a batch of action predictions."""
        for a in action_indices:
            self.current_actions.append(int(a))
        
        if not self._baseline_set and len(self.current_actions) >= self.window_size:
            counts = np.bincount(list(self.current_actions), minlength=self.action_dim).astype(float)
            self.set_baseline(counts)
    
    def compute_drift(self) -> Dict[str, float]:
        """Compute KL divergence between baseline and current action distribution."""
        if not self._baseline_set or len(self.current_actions) < 50:
            return {"kl_divergence": 0.0, "current_dist": [], "baseline_dist": []}
        
        current_counts = np.bincount(
            list(self.current_actions), minlength=self.action_dim
        ).astype(float)
        current_dist = current_counts / max(1, current_counts.sum())
        
        kl = compute_kl_divergence(current_dist, self.baseline_dist)
        
        return {
            "kl_divergence": kl,
            "current_dist": current_dist.round(3).tolist(),
            "baseline_dist": self.baseline_dist.round(3).tolist(),
        }


class ExecutionQualityTracker:
    """Tracks execution quality metrics for drift detection."""
    
    def __init__(self, window_size: int = 200):
        self.window_size = window_size
        self.fill_rates: deque = deque(maxlen=window_size)
        self.slippages: deque = deque(maxlen=window_size)
        self.latencies_ms: deque = deque(maxlen=window_size)
        
        self._baseline_fill_rate = None
        self._baseline_slippage = None
    
    def record_execution(
        self,
        filled: bool,
        slippage_bps: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        self.fill_rates.append(1.0 if filled else 0.0)
        self.slippages.append(slippage_bps)
        self.latencies_ms.append(latency_ms)
        
        # Auto-set baseline
        if self._baseline_fill_rate is None and len(self.fill_rates) >= self.window_size:
            self._baseline_fill_rate = np.mean(list(self.fill_rates))
            self._baseline_slippage = np.mean(list(self.slippages))
    
    def compute_drift(self) -> Dict[str, float]:
        if len(self.fill_rates) < 20:
            return {"fill_rate_drift": 0.0, "slippage_drift": 0.0}
        
        current_fill = np.mean(list(self.fill_rates)[-50:])
        current_slip = np.mean(list(self.slippages)[-50:])
        
        fill_drift = 0.0
        slip_drift = 0.0
        
        if self._baseline_fill_rate is not None:
            fill_drift = abs(current_fill - self._baseline_fill_rate)
        if self._baseline_slippage is not None:
            slip_drift = abs(current_slip - self._baseline_slippage)
        
        return {
            "fill_rate_drift": fill_drift,
            "slippage_drift": slip_drift,
            "current_fill_rate": current_fill,
            "current_avg_slippage_bps": current_slip,
            "current_avg_latency_ms": float(np.mean(list(self.latencies_ms)[-50:])) if self.latencies_ms else 0.0,
        }


class DriftMonitor:
    """Unified drift monitor for features, policy, and execution quality.
    
    Runs periodic checks and publishes alerts when drift exceeds thresholds.
    """
    
    def __init__(
        self,
        action_dim: int = 7,
        psi_threshold: float = 0.25,
        kl_threshold: float = 0.15,
        window_size: int = 1000,
        check_interval_sec: int = 300,
        alert_cooldown_sec: int = 600,
        redis_client=None,
    ):
        self.psi_threshold = psi_threshold
        self.kl_threshold = kl_threshold
        self.check_interval_sec = check_interval_sec
        self.alert_cooldown_sec = alert_cooldown_sec
        self.redis = redis_client
        
        # Sub-trackers
        self.feature_tracker = FeatureDriftTracker(window_size=window_size)
        self.policy_tracker = PolicyDriftTracker(action_dim=action_dim, window_size=window_size // 2)
        self.exec_tracker = ExecutionQualityTracker(window_size=200)
        
        # Alert state
        self._last_check_ts = 0.0
        self._last_alert_ts = {}  # {alert_type: last_ts}
        self._drift_history = []
        self._lock = threading.Lock()
        
        logger.info(
            f"[DRIFT] Monitor initialized: psi_thresh={psi_threshold}, "
            f"kl_thresh={kl_threshold}, check_interval={check_interval_sec}s"
        )
    
    def update_features(self, features: np.ndarray) -> None:
        """Feed new feature observations (called each prediction cycle)."""
        try:
            self.feature_tracker.update(features)
        except Exception as e:
            logger.debug(f"[DRIFT] Feature update error: {e}")
    
    def update_actions(self, action_indices: np.ndarray) -> None:
        """Feed new action predictions (called each prediction cycle)."""
        try:
            self.policy_tracker.update_batch(action_indices)
        except Exception as e:
            logger.debug(f"[DRIFT] Action update error: {e}")
    
    def record_execution(self, filled: bool, slippage_bps: float = 0.0, latency_ms: float = 0.0) -> None:
        """Feed execution result (called by trader feedback)."""
        try:
            self.exec_tracker.record_execution(filled, slippage_bps, latency_ms)
        except Exception as e:
            logger.debug(f"[DRIFT] Execution record error: {e}")
    
    def check(self) -> Dict[str, Any]:
        """Run drift check (call periodically or after each prediction cycle).
        
        Returns dict with:
            feature_drift: PSI metrics
            policy_drift: KL metrics
            exec_drift: execution quality metrics
            alerts: list of active alerts
            should_retrain: whether drift suggests retraining
        """
        now = time.time()
        if (now - self._last_check_ts) < self.check_interval_sec:
            return {"skipped": True}
        
        self._last_check_ts = now
        
        # Compute drift metrics
        feature_drift = self.feature_tracker.compute_drift()
        policy_drift = self.policy_tracker.compute_drift()
        exec_drift = self.exec_tracker.compute_drift()
        
        alerts = []
        should_retrain = False
        
        # Check feature drift
        mean_psi = feature_drift.get("mean_psi", 0.0)
        max_psi = feature_drift.get("max_psi", 0.0)
        if mean_psi > self.psi_threshold:
            alert = {
                "type": "FEATURE_DRIFT",
                "severity": "HIGH" if mean_psi > self.psi_threshold * 2 else "MEDIUM",
                "mean_psi": mean_psi,
                "max_psi": max_psi,
                "drifted_features": feature_drift.get("drifted_features", 0),
            }
            alerts.append(alert)
            should_retrain = True
        
        # Check policy drift
        kl = policy_drift.get("kl_divergence", 0.0)
        if kl > self.kl_threshold:
            alert = {
                "type": "POLICY_DRIFT",
                "severity": "HIGH" if kl > self.kl_threshold * 2 else "MEDIUM",
                "kl_divergence": kl,
            }
            alerts.append(alert)
        
        # Check execution quality
        fill_drift = exec_drift.get("fill_rate_drift", 0.0)
        if fill_drift > 0.1:
            alerts.append({
                "type": "EXECUTION_QUALITY_DRIFT",
                "severity": "MEDIUM",
                "fill_rate_drift": fill_drift,
            })
        
        result = {
            "feature_drift": feature_drift,
            "policy_drift": policy_drift,
            "exec_drift": exec_drift,
            "alerts": alerts,
            "should_retrain": should_retrain,
            "ts": now,
        }
        
        # Publish alerts
        if alerts:
            self._publish_alerts(alerts)
        
        # Log
        if alerts:
            logger.warning(
                f"[DRIFT] ⚠️ {len(alerts)} drift alerts: "
                + ", ".join(a["type"] for a in alerts)
                + f" | PSI={mean_psi:.3f} KL={kl:.3f}"
            )
        else:
            logger.info(
                f"[DRIFT] Check OK: PSI={mean_psi:.3f} KL={kl:.3f} "
                f"fill_drift={fill_drift:.3f}"
            )
        
        # Store history
        with self._lock:
            self._drift_history.append(result)
            if len(self._drift_history) > 100:
                self._drift_history = self._drift_history[-100:]
        
        return result
    
    def _publish_alerts(self, alerts: List[dict]) -> None:
        """Publish drift alerts to Redis for observability."""
        if not self.redis:
            return
        
        now = time.time()
        for alert in alerts:
            alert_type = alert.get("type", "UNKNOWN")
            
            # Cooldown check
            last = self._last_alert_ts.get(alert_type, 0.0)
            if (now - last) < self.alert_cooldown_sec:
                continue
            
            self._last_alert_ts[alert_type] = now
            
            try:
                payload = {
                    "type": "DRIFT_ALERT",
                    "alert": json.dumps(alert),
                    "ts_ms": str(int(now * 1000)),
                }
                self.redis.xadd("wma:drift_alerts", payload, maxlen=500)
            except Exception as e:
                logger.debug(f"[DRIFT] Redis publish error: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get current drift summary for telemetry."""
        feature_drift = self.feature_tracker.compute_drift()
        policy_drift = self.policy_tracker.compute_drift()
        exec_drift = self.exec_tracker.compute_drift()
        
        return {
            "feature_psi": feature_drift.get("mean_psi", 0.0),
            "feature_max_psi": feature_drift.get("max_psi", 0.0),
            "policy_kl": policy_drift.get("kl_divergence", 0.0),
            "exec_fill_rate": exec_drift.get("current_fill_rate", 0.0),
            "exec_avg_slippage": exec_drift.get("current_avg_slippage_bps", 0.0),
            "total_alerts": sum(1 for h in self._drift_history if h.get("alerts")),
        }
