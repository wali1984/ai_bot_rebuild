"""
Mixture-of-Experts (MoE) Router — Regime-Aware Policy Selection

Routes inference through specialized expert heads based on detected market regime.
Each expert specialises in a regime archetype:
  • Expert 0 (calm):    Low-vol range-bound — tighter stops, mean-reversion bias
  • Expert 1 (normal):  Balanced — standard PPO+MASA ensemble
  • Expert 2 (fast):    Trending/momentum — wider stops, directional bias
  • Expert 3 (impulse): Crisis/spike — protective bias, hedge-first

The router is a lightweight MLP that takes regime primitive features and outputs
soft assignment weights across experts using top-k gating.

Integration:
  - Called inside `_make_batch_predictions_gpu` after PPO+MASA logits computed
  - Routes/blends expert-specific policy heads based on regime context
  - Returns blended action logits and expert assignment diagnostics
"""

import logging
import time
import math
import numpy as np
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    logger.warning("[MOE] PyTorch not available — MoE disabled")


class ExpertHead(nn.Module):
    """Single expert policy head — lightweight MLP that modulates action logits."""
    
    def __init__(self, input_dim: int, output_dim: int, hidden_dim: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, output_dim),
        )
        # Initialize near-identity (small perturbation so experts start similar)
        with torch.no_grad():
            for p in self.parameters():
                if p.dim() > 1:
                    nn.init.xavier_normal_(p, gain=0.1)
                else:
                    p.zero_()
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class MoERouter(nn.Module):
    """Gating network that routes inputs to top-k experts.
    
    Input: regime primitive features (move_score, vol_score, stress, etc.)
    Output: expert weights (B, num_experts) after top-k selection
    """
    
    def __init__(
        self,
        input_dim: int = 12,
        num_experts: int = 4,
        hidden_dim: int = 64,
        temperature: float = 1.0,
        top_k: int = 2,
    ):
        super().__init__()
        self.num_experts = num_experts
        self.temperature = temperature
        self.top_k = min(top_k, num_experts)
        
        self.gate = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, num_experts),
        )
        
        # Noise for load balancing during training
        self._noise_epsilon = 1e-2
        
        with torch.no_grad():
            for p in self.parameters():
                if p.dim() > 1:
                    nn.init.xavier_normal_(p, gain=0.3)
    
    def forward(self, regime_features: torch.Tensor, training: bool = False) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            regime_features: (B, input_dim) regime primitive features
            training: whether to add noise for load balancing
        
        Returns:
            weights: (B, num_experts) soft assignment weights (sum to 1 per sample)
            raw_logits: (B, num_experts) raw gate logits for diagnostics
        """
        logits = self.gate(regime_features) / max(self.temperature, 0.01)
        
        # Add noise during training for exploration
        if training:
            noise = torch.randn_like(logits) * self._noise_epsilon
            logits = logits + noise
        
        # Top-k selection
        if self.top_k < self.num_experts:
            topk_vals, topk_idx = torch.topk(logits, self.top_k, dim=-1)
            # Create mask
            mask = torch.zeros_like(logits).scatter_(-1, topk_idx, 1.0)
            # Apply mask (set non-top-k to -inf before softmax)
            logits = logits.masked_fill(mask == 0, float('-inf'))
        
        weights = F.softmax(logits, dim=-1)
        weights = torch.nan_to_num(weights, nan=1.0 / self.num_experts)
        
        return weights, logits


class MoEPolicySelector:
    """High-level MoE policy selector for the hybrid trainer.
    
    Manages expert heads + router, provides blended predictions,
    and tracks load-balance diagnostics.
    """
    
    def __init__(
        self,
        action_dim: int = 7,
        feature_dim: int = 0,
        num_experts: int = 4,
        router_input_dim: int = 12,
        hidden_dim: int = 128,
        temperature: float = 1.0,
        top_k: int = 2,
        load_balance_coeff: float = 0.01,
        device: str = "cuda",
    ):
        if not HAS_TORCH:
            raise RuntimeError("PyTorch required for MoE")
        
        self.action_dim = action_dim
        self.num_experts = num_experts
        self.load_balance_coeff = load_balance_coeff
        self.device = device if torch.cuda.is_available() else "cpu"
        
        # Expert heads: take action logits and modulate them
        self.experts = nn.ModuleList([
            ExpertHead(action_dim, action_dim, hidden_dim)
            for _ in range(num_experts)
        ]).to(self.device)
        
        # Router
        self.router = MoERouter(
            input_dim=router_input_dim,
            num_experts=num_experts,
            hidden_dim=hidden_dim // 2,
            temperature=temperature,
            top_k=top_k,
        ).to(self.device)
        
        # Optimizer for expert heads and router (separate from PPO/MASA optimizers)
        all_params = list(self.experts.parameters()) + list(self.router.parameters())
        self.optimizer = torch.optim.AdamW(all_params, lr=1e-4, weight_decay=1e-5)
        
        # Diagnostics
        self._expert_usage_counts = np.zeros(num_experts)
        self._last_log_ts = 0.0
        
        logger.info(
            f"[MOE] Initialized: {num_experts} experts, action_dim={action_dim}, "
            f"router_input={router_input_dim}, top_k={top_k}, device={self.device}"
        )
    
    def build_regime_features(self, feature_dicts: List[dict], batch_size: int) -> torch.Tensor:
        """Extract regime primitive features from feature dicts.
        
        Returns (B, router_input_dim) tensor with:
          [move_score, vol_score, fast_move_score, liq_risk, liquidity_score,
           tf_bias_dir, tf_timing_dir, conflict_score, spread_pct, depth_norm,
           pnl_pct, drawdown_pct]
        """
        features = np.zeros((batch_size, 12), dtype=np.float32)
        
        for i in range(min(batch_size, len(feature_dicts))):
            fd = feature_dicts[i] if feature_dicts[i] else {}
            try:
                features[i, 0] = float(fd.get("move_score", 0.0) or 0.0)
                features[i, 1] = float(fd.get("volatility_score", 0.0) or 0.0)
                features[i, 2] = float(fd.get("fast_move_score", 0.0) or 0.0)
                features[i, 3] = float(fd.get("liq_risk", 0.0) or 0.0)
                features[i, 4] = float(fd.get("liquidity_score", 0.0) or 0.0)
                features[i, 5] = float(fd.get("tf_bias_dir", 0) or 0) / 3.0  # normalize
                features[i, 6] = float(fd.get("tf_timing_dir", 0) or 0) / 3.0
                features[i, 7] = float(fd.get("conflict_score", 0.0) or 0.0)
                features[i, 8] = float(fd.get("spread_pct", 0.0) or 0.0)
                features[i, 9] = min(1.0, float(fd.get("orderbook_depth_usd", 0.0) or 0.0) / 1e6)
                features[i, 10] = float(fd.get("position_pnl_pct", 0.0) or 0.0) / 10.0
                features[i, 11] = float(fd.get("drawdown_pct", 0.0) or 0.0) / 10.0
            except Exception:
                pass
        
        # Sanitize
        features = np.nan_to_num(features, nan=0.0, posinf=1.0, neginf=-1.0)
        features = np.clip(features, -5.0, 5.0)
        
        return torch.tensor(features, dtype=torch.float32, device=self.device)
    
    @torch.no_grad()
    def route_and_blend(
        self,
        ppo_logits: torch.Tensor,
        regime_features: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """Route PPO action logits through expert heads based on regime.
        
        Args:
            ppo_logits: (B, action_dim) raw PPO action logits
            regime_features: (B, router_input_dim) regime primitives
        
        Returns:
            blended_logits: (B, action_dim) expert-blended logits
            diagnostics: dict with routing info
        """
        batch_size = ppo_logits.shape[0]
        
        # Ensure on correct device
        ppo_logits = ppo_logits.to(self.device, dtype=torch.float32)
        regime_features = regime_features.to(self.device, dtype=torch.float32)
        
        # Get expert weights from router
        weights, raw_gate_logits = self.router(regime_features, training=False)  # (B, E)
        
        # Compute each expert's output
        expert_outputs = []
        for expert in self.experts:
            # Expert modulates base logits (residual: base + expert_delta)
            delta = expert(ppo_logits)
            expert_outputs.append(ppo_logits + delta)
        
        # Stack: (B, E, action_dim)
        expert_stack = torch.stack(expert_outputs, dim=1)
        
        # Weighted combination: (B, E, 1) * (B, E, action_dim) → sum over E
        weights_expanded = weights.unsqueeze(-1)  # (B, E, 1)
        blended = (weights_expanded * expert_stack).sum(dim=1)  # (B, action_dim)
        
        # Diagnostics
        top_expert = weights.argmax(dim=-1).cpu().numpy()  # (B,)
        for idx in top_expert:
            self._expert_usage_counts[idx] += 1
        
        diag = {
            "expert_weights_mean": weights.mean(dim=0).cpu().numpy().tolist(),
            "top_expert_distribution": {
                int(i): int((top_expert == i).sum())
                for i in range(self.num_experts)
            },
            "load_balance_loss": self._load_balance_loss(weights).item(),
        }
        
        # Throttled logging
        now = time.time()
        if now - self._last_log_ts > 60:
            self._last_log_ts = now
            total = max(1, self._expert_usage_counts.sum())
            pcts = (self._expert_usage_counts / total * 100).round(1)
            expert_names = ["calm", "normal", "fast", "impulse"]
            usage_str = ", ".join(
                f"{expert_names[i] if i < len(expert_names) else f'e{i}'}={pcts[i]:.1f}%"
                for i in range(self.num_experts)
            )
            logger.info(f"[MOE] Expert usage: {usage_str} | LB_loss={diag['load_balance_loss']:.4f}")
        
        return blended, diag
    
    def _load_balance_loss(self, weights: torch.Tensor) -> torch.Tensor:
        """Compute load-balance auxiliary loss to prevent expert collapse.
        
        L_lb = num_experts * sum_e(fraction_e * mean_gate_e)
        """
        # fraction: what fraction of samples was routed to each expert
        fraction = weights.mean(dim=0)  # (E,)
        # Encourage uniform distribution
        target = torch.ones_like(fraction) / self.num_experts
        return self.load_balance_coeff * ((fraction - target) ** 2).sum() * self.num_experts
    
    def training_step(
        self,
        ppo_logits: torch.Tensor,
        regime_features: torch.Tensor,
        target_actions: torch.Tensor,
        rewards: torch.Tensor,
    ) -> Dict[str, float]:
        """Update expert heads and router using replay data.
        
        Args:
            ppo_logits: (B, action_dim) base logits
            regime_features: (B, router_input_dim)
            target_actions: (B,) ground truth actions from replay
            rewards: (B,) reward signals for weighting
        
        Returns: loss metrics dict
        """
        self.experts.train()
        self.router.train()
        
        ppo_logits = ppo_logits.to(self.device, dtype=torch.float32)
        regime_features = regime_features.to(self.device, dtype=torch.float32)
        target_actions = target_actions.to(self.device, dtype=torch.long)
        rewards = rewards.to(self.device, dtype=torch.float32)
        
        # Forward
        weights, _ = self.router(regime_features, training=True)
        
        expert_outputs = []
        for expert in self.experts:
            delta = expert(ppo_logits)
            expert_outputs.append(ppo_logits + delta)
        
        expert_stack = torch.stack(expert_outputs, dim=1)
        weights_expanded = weights.unsqueeze(-1)
        blended = (weights_expanded * expert_stack).sum(dim=1)
        
        # Cross-entropy loss weighted by reward magnitude
        log_probs = F.log_softmax(blended, dim=-1)
        action_log_probs = log_probs.gather(1, target_actions.unsqueeze(1)).squeeze(1)
        
        # Weight by reward: positive reward = reinforce, negative = anti-reinforce
        reward_weights = torch.abs(rewards) + 0.1
        reward_signs = torch.sign(rewards)
        
        policy_loss = -(reward_signs * reward_weights * action_log_probs).mean()
        lb_loss = self._load_balance_loss(weights)
        total_loss = policy_loss + lb_loss
        
        self.optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(
            list(self.experts.parameters()) + list(self.router.parameters()),
            max_norm=1.0,
        )
        self.optimizer.step()
        
        self.experts.eval()
        self.router.eval()
        
        return {
            "moe_policy_loss": policy_loss.item(),
            "moe_lb_loss": lb_loss.item(),
            "moe_total_loss": total_loss.item(),
        }
    
    def state_dict(self) -> dict:
        """Return full state dict for checkpointing."""
        return {
            "experts": self.experts.state_dict(),
            "router": self.router.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "expert_usage": self._expert_usage_counts.tolist(),
        }
    
    def load_state_dict(self, state: dict) -> None:
        """Load from checkpoint."""
        try:
            if "experts" in state:
                self.experts.load_state_dict(state["experts"])
            if "router" in state:
                self.router.load_state_dict(state["router"])
            if "optimizer" in state:
                self.optimizer.load_state_dict(state["optimizer"])
            if "expert_usage" in state:
                self._expert_usage_counts = np.array(state["expert_usage"])
            logger.info("[MOE] State dict loaded successfully")
        except Exception as e:
            logger.warning(f"[MOE] State dict load failed (fresh start): {e}")
