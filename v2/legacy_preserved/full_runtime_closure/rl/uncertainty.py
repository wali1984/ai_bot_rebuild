"""
Uncertainty Estimation — Multi-Head Ensemble + MC Dropout

Provides calibrated uncertainty estimates for trading decisions:
  • Multi-head ensemble: N parallel action heads with shared backbone
  • MC Dropout: multiple stochastic forward passes at inference time
  • Epistemic uncertainty from prediction disagreement across heads/passes
  • Aleatoric uncertainty from individual head variance

Uncertainty is used to:
  1. Modulate position sizing (high uncertainty → smaller positions)
  2. Widen confidence thresholds (uncertain → harder to pass threshold)
  3. Trigger HOLD when uncertainty exceeds block threshold
  4. Provide telemetry for drift detection

Integration:
  - Instantiated in HybridTrainer.__init__
  - Called in _make_batch_predictions_gpu after PPO logits computed
  - Returns uncertainty_score per sample, used to modulate confidence
"""

import logging
import time
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


class UncertaintyHead(nn.Module):
    """Single uncertainty estimation head — lightweight MLP branching from latent."""
    
    def __init__(self, input_dim: int, output_dim: int, dropout_rate: float = 0.1):
        super().__init__()
        hidden = max(64, input_dim // 2)
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.Linear(hidden // 2, output_dim),
        )
        with torch.no_grad():
            for p in self.parameters():
                if p.dim() > 1:
                    nn.init.xavier_normal_(p, gain=1.0)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class UncertaintyEstimator:
    """Multi-head ensemble uncertainty for trading decisions.
    
    Architecture:
      - N independent heads branch from PPO's latent features
      - Each head predicts action logits independently
      - Disagreement across heads = epistemic uncertainty
      - Variance within softmax = aleatoric uncertainty
      - MC dropout provides additional stochastic uncertainty
    """
    
    def __init__(
        self,
        action_dim: int = 7,
        latent_dim: int = 64,
        num_heads: int = 5,
        mc_passes: int = 10,
        dropout_rate: float = 0.1,
        sizing_factor: float = 0.5,
        high_threshold: float = 0.3,
        block_threshold: float = 0.5,
        device: str = "cuda",
    ):
        if not HAS_TORCH:
            raise RuntimeError("PyTorch required for uncertainty estimation")
        
        self.action_dim = action_dim
        self.num_heads = num_heads
        self.mc_passes = mc_passes
        self.sizing_factor = sizing_factor
        self.high_threshold = high_threshold
        self.block_threshold = block_threshold
        self.device = device if torch.cuda.is_available() else "cpu"
        
        # Ensemble heads
        self.heads = nn.ModuleList([
            UncertaintyHead(latent_dim, action_dim, dropout_rate)
            for _ in range(num_heads)
        ]).to(self.device)
        
        # Optimizer for ensemble heads
        self.optimizer = torch.optim.AdamW(
            self.heads.parameters(), lr=3e-4, weight_decay=1e-5
        )
        
        # Running statistics for calibration
        self._uncertainty_history = []
        self._max_history = 1000
        self._last_log_ts = 0.0
        
        # Adaptive input projection (handles variable latent dims)
        self._input_proj = None
        self._expected_input_dim = latent_dim
        
        logger.info(
            f"[UNCERTAINTY] Initialized: {num_heads} heads, mc_passes={mc_passes}, "
            f"latent_dim={latent_dim}, device={self.device}"
        )
    
    def _ensure_input_proj(self, actual_dim: int) -> None:
        """Create/update input projection if latent dim doesn't match."""
        if actual_dim == self._expected_input_dim and self._input_proj is None:
            return
        if self._input_proj is not None and actual_dim == self._input_proj.in_features:
            return
        
        self._input_proj = nn.Linear(actual_dim, self._expected_input_dim).to(self.device)
        with torch.no_grad():
            nn.init.xavier_normal_(self._input_proj.weight, gain=1.0)
            self._input_proj.bias.zero_()
        logger.info(f"[UNCERTAINTY] Input projection created: {actual_dim} → {self._expected_input_dim}")
    
    @torch.no_grad()
    def estimate(
        self,
        latent_features: torch.Tensor,
        ppo_action_logits: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        """Compute uncertainty estimates for a batch.
        
        Args:
            latent_features: (B, latent_dim) from PPO's feature extractor
            ppo_action_logits: (B, action_dim) PPO's action logits
        
        Returns dict with:
            epistemic: (B,) disagreement across heads
            aleatoric: (B,) average prediction variance
            total: (B,) combined uncertainty score [0, 1]
            sizing_mult: (B,) position size multiplier (1.0 = full, 0.0 = none)
            should_block: (B,) boolean mask for high-uncertainty blocks
        """
        B = latent_features.shape[0]
        latent_features = latent_features.to(self.device, dtype=torch.float32)
        ppo_action_logits = ppo_action_logits.to(self.device, dtype=torch.float32)
        
        # Handle dimension mismatch
        self._ensure_input_proj(latent_features.shape[-1])
        if self._input_proj is not None:
            latent_features = self._input_proj(latent_features)
        
        # 1. Multi-head ensemble predictions
        head_logits = []
        for head in self.heads:
            head.eval()
            h_logits = head(latent_features)  # (B, action_dim)
            head_logits.append(h_logits)
        
        head_stack = torch.stack(head_logits, dim=0)  # (H, B, action_dim)
        head_probs = F.softmax(head_stack, dim=-1)  # (H, B, action_dim)
        
        # Epistemic uncertainty: disagreement across heads
        # Use pairwise KL divergence as measure of disagreement
        mean_probs = head_probs.mean(dim=0)  # (B, action_dim)
        mean_probs = torch.clamp(mean_probs, min=1e-8)
        
        kl_sum = torch.zeros(B, device=self.device)
        for h in range(self.num_heads):
            hp = torch.clamp(head_probs[h], min=1e-8)
            kl = (hp * (hp.log() - mean_probs.log())).sum(dim=-1)
            kl_sum += kl
        epistemic = kl_sum / self.num_heads  # (B,)
        
        # Aleatoric uncertainty: entropy of mean prediction
        aleatoric = -(mean_probs * mean_probs.log()).sum(dim=-1)  # (B,)
        max_entropy = np.log(self.action_dim)
        aleatoric = aleatoric / max_entropy  # Normalize to [0, 1]
        
        # 2. MC Dropout passes (use first head with dropout enabled)
        mc_logits = []
        self.heads[0].train()  # Enable dropout
        for _ in range(self.mc_passes):
            mc_out = self.heads[0](latent_features)
            mc_logits.append(mc_out)
        self.heads[0].eval()
        
        mc_stack = torch.stack(mc_logits, dim=0)  # (M, B, action_dim)
        mc_probs = F.softmax(mc_stack, dim=-1)
        mc_var = mc_probs.var(dim=0).mean(dim=-1)  # (B,) avg variance across actions
        
        # 3. Combined uncertainty
        # Weighted combination: epistemic (model disagreement) + aleatoric (inherent noise) + MC variance
        total = 0.4 * epistemic + 0.3 * aleatoric + 0.3 * mc_var * 10.0  # Scale MC var
        total = torch.clamp(total, 0.0, 1.0)
        total = torch.nan_to_num(total, nan=0.5)
        
        # 4. Sizing multiplier: reduce position size under uncertainty
        # sizing_mult = 1.0 - sizing_factor * uncertainty
        sizing_mult = 1.0 - self.sizing_factor * total
        sizing_mult = torch.clamp(sizing_mult, 0.1, 1.0)
        
        # 5. Block mask
        should_block = total > self.block_threshold
        
        # Track history for calibration
        total_np = total.cpu().numpy()
        self._uncertainty_history.extend(total_np.tolist())
        if len(self._uncertainty_history) > self._max_history:
            self._uncertainty_history = self._uncertainty_history[-self._max_history:]
        
        # Throttled logging
        now = time.time()
        if now - self._last_log_ts > 60:
            self._last_log_ts = now
            hist = np.array(self._uncertainty_history[-200:])
            logger.info(
                f"[UNCERTAINTY] Batch stats: mean={total_np.mean():.3f}, "
                f"max={total_np.max():.3f}, blocked={should_block.sum().item()}/{B} | "
                f"Rolling p50={np.median(hist):.3f} p95={np.percentile(hist, 95):.3f}"
            )
        
        return {
            "epistemic": epistemic,
            "aleatoric": aleatoric,
            "mc_variance": mc_var,
            "total": total,
            "sizing_mult": sizing_mult,
            "should_block": should_block,
        }
    
    def training_step(
        self,
        latent_features: torch.Tensor,
        target_actions: torch.Tensor,
        rewards: torch.Tensor,
    ) -> Dict[str, float]:
        """Train ensemble heads using replay data.
        
        Each head gets a slightly different gradient signal to maintain diversity.
        """
        self.heads.train()
        
        latent_features = latent_features.to(self.device, dtype=torch.float32).detach()
        target_actions = target_actions.to(self.device, dtype=torch.long)
        rewards = rewards.to(self.device, dtype=torch.float32)
        
        if self._input_proj is not None:
            latent_features = self._input_proj(latent_features)
        
        total_loss = torch.tensor(0.0, device=self.device)
        
        for i, head in enumerate(self.heads):
            logits = head(latent_features)
            log_probs = F.log_softmax(logits, dim=-1)
            action_lp = log_probs.gather(1, target_actions.unsqueeze(1)).squeeze(1)
            
            # Bootstrap: each head sees a random subset (90%)
            mask = torch.rand(len(rewards), device=self.device) < 0.9
            if mask.sum() == 0:
                continue
            
            loss = -(rewards[mask].sign() * torch.abs(rewards[mask] + 0.1) * action_lp[mask]).mean()
            total_loss = total_loss + loss
        
        total_loss = total_loss / max(1, self.num_heads)
        
        self.optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.heads.parameters(), max_norm=1.0)
        self.optimizer.step()
        
        self.heads.eval()
        
        return {"uncertainty_train_loss": total_loss.item()}
    
    def state_dict(self) -> dict:
        state = {
            "heads": self.heads.state_dict(),
            "optimizer": self.optimizer.state_dict(),
        }
        if self._input_proj is not None:
            state["input_proj"] = self._input_proj.state_dict()
        return state
    
    def load_state_dict(self, state: dict) -> None:
        try:
            if "heads" in state:
                self.heads.load_state_dict(state["heads"])
            if "optimizer" in state:
                self.optimizer.load_state_dict(state["optimizer"])
            if "input_proj" in state and self._input_proj is not None:
                self._input_proj.load_state_dict(state["input_proj"])
            logger.info("[UNCERTAINTY] State dict loaded successfully")
        except Exception as e:
            logger.warning(f"[UNCERTAINTY] State dict load failed (fresh start): {e}")
