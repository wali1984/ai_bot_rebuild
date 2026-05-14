"""
Replay Store — Regime-Stratified Experience Buffer

Stores (state, action, reward, next_state, regime_label) tuples with:
  • Ring-buffer per regime bucket (calm / trend / volatile / crisis)
  • Balanced mini-batch sampling across regimes
  • Priority-weighted replay (prioritised by |TD-error| or raw reward magnitude)
  • Elastic Weight Consolidation (EWC) Fisher diagonal estimation
  • Persistence to disk for crash recovery

Integration:
  - Trainer calls `store.add(...)` after each step or episode
  - Training loop calls `store.sample(batch_size)` for balanced mini-batches
  - EWC helper computes Fisher matrix from replay data to regularise weight updates
"""

import os
import logging
import pickle
import threading
import time
import numpy as np
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Regime labels
REGIME_CALM = 0
REGIME_TREND = 1
REGIME_VOLATILE = 2
REGIME_CRISIS = 3
REGIME_NAMES = {0: "calm", 1: "trend", 2: "volatile", 3: "crisis"}


def classify_regime(feature_dict: dict) -> int:
    """Classify current market regime from feature/regime dict.
    
    Uses move_regime + volatility_score from the market regime system
    already running in production.
    """
    try:
        move_regime = str(feature_dict.get("move_regime", "UNKNOWN")).upper()
        vol_score = float(feature_dict.get("volatility_score", 0.0) or 0.0)
        stress = float(feature_dict.get("liq_risk", 0.0) or 0.0)
        move_score = float(feature_dict.get("move_score", 0.0) or 0.0)
        if stress > 0.6 and vol_score > 0.5:
            return REGIME_CRISIS
        if vol_score > 0.65:
            return REGIME_VOLATILE
        if abs(move_score) > 0.3 or vol_score > 0.35:
            return REGIME_TREND
        return REGIME_CALM
    except Exception:
        return REGIME_CALM


class ReplayStore:
    """Regime-stratified experience replay buffer with priority sampling."""
    
    def __init__(
        self,
        max_size: int = 100_000,
        num_buckets: int = 4,
        min_bucket_ratio: float = 0.1,
        priority_alpha: float = 0.6,
        persist_path: Optional[str] = None,
    ):
        self.max_per_bucket = max_size // num_buckets
        self.num_buckets = num_buckets
        self.min_bucket_ratio = min_bucket_ratio
        self.priority_alpha = priority_alpha
        self.persist_path = persist_path
        
        # Per-regime ring buffers
        self.buckets: Dict[int, deque] = {
            i: deque(maxlen=self.max_per_bucket) for i in range(num_buckets)
        }
        # Priority scores (parallel arrays with buckets)
        self.priorities: Dict[int, deque] = {
            i: deque(maxlen=self.max_per_bucket) for i in range(num_buckets)
        }
        
        self._lock = threading.Lock()
        self._total_added = 0
        self._last_persist_ts = 0.0
        
        # Try loading persisted data
        if persist_path and os.path.exists(persist_path):
            try:
                self._load(persist_path)
                logger.info(f"[REPLAY] Loaded {self.total_size()} experiences from {persist_path}")
            except Exception as e:
                logger.warning(f"[REPLAY] Failed to load persisted data: {e}")
        
        logger.info(
            f"[REPLAY] Initialized: max_per_bucket={self.max_per_bucket}, "
            f"buckets={num_buckets}, alpha={priority_alpha}"
        )
    
    def add(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: Optional[np.ndarray],
        regime: int,
        priority: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add a transition to the appropriate regime bucket."""
        regime = max(0, min(self.num_buckets - 1, int(regime)))
        
        if priority is None:
            priority = abs(reward) + 1e-6  # Default priority = |reward|
        
        experience = {
            "state": state,
            "action": action,
            "reward": reward,
            "next_state": next_state,
            "regime": regime,
            "ts": time.time(),
            "metadata": metadata or {},
        }
        
        with self._lock:
            self.buckets[regime].append(experience)
            self.priorities[regime].append(priority ** self.priority_alpha)
            self._total_added += 1
        
        # Auto-persist every 5 minutes
        if self.persist_path and (time.time() - self._last_persist_ts) > 300:
            self.persist()
    
    def sample(self, batch_size: int = 256) -> List[dict]:
        """Sample a balanced mini-batch across regime buckets.
        
        Ensures each regime contributes at least `min_bucket_ratio` of the batch,
        with remainder distributed proportional to bucket size.
        """
        with self._lock:
            bucket_sizes = {k: len(v) for k, v in self.buckets.items()}
        
        total = sum(bucket_sizes.values())
        if total == 0:
            return []
        
        # Minimum samples per non-empty bucket
        non_empty = [k for k, v in bucket_sizes.items() if v > 0]
        if not non_empty:
            return []
        
        min_per_bucket = max(1, int(batch_size * self.min_bucket_ratio))
        
        # Allocate minimum first, then proportional remainder
        allocation = {}
        remaining = batch_size
        for k in non_empty:
            alloc = min(min_per_bucket, bucket_sizes[k])
            allocation[k] = alloc
            remaining -= alloc
        
        # Distribute remainder proportionally
        if remaining > 0:
            weight_total = sum(bucket_sizes[k] for k in non_empty)
            for k in non_empty:
                extra = int(remaining * bucket_sizes[k] / max(1, weight_total))
                extra = min(extra, bucket_sizes[k] - allocation[k])
                allocation[k] += max(0, extra)
        
        # Sample with priority weighting
        samples = []
        with self._lock:
            for bucket_id, count in allocation.items():
                if count <= 0 or len(self.buckets[bucket_id]) == 0:
                    continue
                
                priorities_arr = np.array(list(self.priorities[bucket_id]), dtype=np.float64)
                priorities_arr = np.maximum(priorities_arr, 1e-8)
                prob = priorities_arr / priorities_arr.sum()
                
                n = min(count, len(self.buckets[bucket_id]))
                indices = np.random.choice(len(self.buckets[bucket_id]), size=n, replace=False, p=prob)
                
                bucket_list = list(self.buckets[bucket_id])
                for idx in indices:
                    samples.append(bucket_list[idx])
        
        return samples
    
    def sample_tensors(self, batch_size: int = 256):
        """Sample and return as stacked numpy arrays ready for torch conversion.
        
        Returns: (states, actions, rewards, next_states, regimes) or None if empty
        """
        samples = self.sample(batch_size)
        if not samples:
            return None
        
        states = np.stack([s["state"] for s in samples])
        actions = np.array([s["action"] for s in samples], dtype=np.int64)
        rewards = np.array([s["reward"] for s in samples], dtype=np.float32)
        next_states = np.stack([
            s["next_state"] if s["next_state"] is not None else s["state"]
            for s in samples
        ])
        regimes = np.array([s["regime"] for s in samples], dtype=np.int64)
        
        return states, actions, rewards, next_states, regimes
    
    def total_size(self) -> int:
        with self._lock:
            return sum(len(v) for v in self.buckets.values())
    
    def bucket_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                REGIME_NAMES.get(k, f"bucket_{k}"): len(v)
                for k, v in self.buckets.items()
            }
    
    def persist(self) -> None:
        """Save replay buffer to disk."""
        if not self.persist_path:
            return
        try:
            path = Path(self.persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._lock:
                data = {
                    "buckets": {k: list(v) for k, v in self.buckets.items()},
                    "priorities": {k: list(v) for k, v in self.priorities.items()},
                    "total_added": self._total_added,
                    "timestamp": time.time(),
                }
            
            tmp_path = str(path) + ".tmp"
            with open(tmp_path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, str(path))
            
            self._last_persist_ts = time.time()
            logger.info(f"[REPLAY] Persisted {self.total_size()} experiences to {self.persist_path}")
        except Exception as e:
            logger.warning(f"[REPLAY] Persist failed: {e}")
    
    def _load(self, path: str) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        
        for k, items in data.get("buckets", {}).items():
            k = int(k)
            if k in self.buckets:
                for item in items[-self.max_per_bucket:]:
                    self.buckets[k].append(item)
        
        for k, prios in data.get("priorities", {}).items():
            k = int(k)
            if k in self.priorities:
                for p in prios[-self.max_per_bucket:]:
                    self.priorities[k].append(p)
        
        self._total_added = data.get("total_added", 0)


class EWCRegularizer:
    """Elastic Weight Consolidation for preventing catastrophic forgetting.
    
    Computes Fisher Information Matrix diagonal from replay data,
    then provides a regularisation loss term during training.
    """
    
    def __init__(self, ewc_lambda: float = 0.1):
        self.ewc_lambda = ewc_lambda
        self._fisher_diag = None
        self._anchor_params = None
        self._computed = False
    
    def compute_fisher(self, model, replay_store: ReplayStore, n_samples: int = 500) -> None:
        """Compute Fisher Information diagonal from replay data.
        
        Should be called periodically (e.g. every N training loops) to
        update the importance weights.
        """
        import torch
        
        try:
            samples = replay_store.sample(min(n_samples, replay_store.total_size()))
            if len(samples) < 10:
                logger.debug("[EWC] Not enough samples for Fisher computation")
                return
            
            # Collect parameters
            params = {n: p for n, p in model.policy.named_parameters() if p.requires_grad}
            
            # Initialize Fisher diagonal
            fisher = {n: torch.zeros_like(p) for n, p in params.items()}
            
            # Compute gradients on replay samples
            states = np.stack([s["state"] for s in samples])
            states_t = torch.tensor(states, dtype=torch.float32, device=next(model.policy.parameters()).device)
            
            model.policy.train()
            for i in range(len(states_t)):
                model.policy.zero_grad()
                obs = states_t[i:i+1]
                
                try:
                    features = model.policy.extract_features(obs)
                    latent_pi = model.policy.mlp_extractor.forward_actor(features)
                    logits = model.policy.action_net(latent_pi)
                    log_probs = torch.log_softmax(logits, dim=-1)
                    # Use predicted action's log prob
                    action = samples[i]["action"]
                    loss = -log_probs[0, min(action, logits.shape[-1] - 1)]
                    loss.backward()
                    
                    for n, p in params.items():
                        if p.grad is not None:
                            fisher[n] += p.grad.data.pow(2)
                except Exception:
                    continue
            
            # Average
            for n in fisher:
                fisher[n] /= max(1, len(states_t))
            
            self._fisher_diag = fisher
            self._anchor_params = {n: p.data.clone() for n, p in params.items()}
            self._computed = True
            
            logger.info(f"[EWC] Fisher diagonal computed from {len(samples)} samples")
            
        except Exception as e:
            logger.warning(f"[EWC] Fisher computation failed: {e}")
    
    def penalty(self, model) -> float:
        """Compute EWC penalty loss term.
        
        Returns scalar loss to add to training objective:
            L_ewc = (lambda/2) * sum_i F_i * (theta_i - theta_i*)^2
        """
        import torch
        
        if not self._computed or self._fisher_diag is None:
            return 0.0
        
        try:
            loss = torch.tensor(0.0, device=next(model.policy.parameters()).device)
            
            for n, p in model.policy.named_parameters():
                if n in self._fisher_diag and n in self._anchor_params:
                    fisher = self._fisher_diag[n]
                    anchor = self._anchor_params[n]
                    loss += (fisher * (p - anchor).pow(2)).sum()
            
            return float(self.ewc_lambda * 0.5 * loss.item())
        except Exception as e:
            logger.debug(f"[EWC] Penalty computation failed: {e}")
            return 0.0
    
    def penalty_tensor(self, model):
        """Return EWC penalty as a differentiable tensor for backprop."""
        import torch
        
        if not self._computed or self._fisher_diag is None:
            return torch.tensor(0.0, requires_grad=False)
        
        try:
            device = next(model.policy.parameters()).device
            loss = torch.tensor(0.0, device=device, requires_grad=True)
            penalty = torch.tensor(0.0, device=device)
            
            for n, p in model.policy.named_parameters():
                if n in self._fisher_diag and n in self._anchor_params:
                    fisher = self._fisher_diag[n]
                    anchor = self._anchor_params[n]
                    penalty = penalty + (fisher * (p - anchor).pow(2)).sum()
            
            return self.ewc_lambda * 0.5 * penalty
        except Exception:
            return torch.tensor(0.0, requires_grad=False)
