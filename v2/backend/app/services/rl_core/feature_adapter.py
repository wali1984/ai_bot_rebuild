"""
Feature Adapter: Convert unified feature dicts to normalized observation tensors

Input: unified_features dict (409+ fields from feature pipeline)
Output: PyTorch tensor (562 dims, normalized to [-1, 1])

Handles:
- Dict → flat array conversion
- Dimension padding (409 → 562)
- Normalization (z-score to [-1, 1])
- NaN/Inf handling
- Type conversion (any → float32)
"""

import numpy as np
import torch
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class FeatureAdapter:
    """
    Adapts unified feature dicts to normalized observation tensors.

    Compatible with legacy PPO policies expecting 562-dimensional input.
    """

    # Target observation dimension (must match policy input layer)
    TARGET_OBS_DIM = 562

    # Field priority order (which fields to include first if truncating)
    FIELD_PRIORITY = [
        # Core market data (highest priority)
        "ohlcv_return", "ohlcv_log_return", "ohlcv_high_low_range_pct",
        # TA indicators (critical for signal)
        "ta_RSI_14", "ta_MACD_12_26_9_macd", "ta_MACD_12_26_9_signal",
        "ta_BB_upper", "ta_BB_lower", "ta_ATR_14",
        # Regime and toxicity (critical gates)
        "regime_volatility", "regime_trend", "regime_momentum",
        "toxicity_overall", "toxicity_flow", "toxicity_slippage",
        # Microstructure
        "microstructure_spread_bps", "microstructure_bid", "microstructure_ask",
        # Liquidation and OI
        "liquidation_level_long", "liquidation_level_short",
        "liquidation_strength_long", "liquidation_strength_short",
        # Freshness
        "freshness_data_quality", "data_completeness_pct",
    ]

    def __init__(self, target_dim: int = 562, normalize: bool = True, device: str = "cpu"):
        """
        Initialize adapter.

        Args:
            target_dim: Target observation dimension (default 562)
            normalize: Whether to normalize to [-1, 1] (default True)
            device: PyTorch device (cpu or cuda)
        """
        self.target_dim = target_dim
        self.normalize = normalize
        self.device = torch.device(device)

        # Field tracking
        self.field_names = []
        self.field_count = 0

        # Normalization stats
        self.mean = None
        self.std = None
        self.min_val = None
        self.max_val = None
        self.normalization_ready = False

        logger.info(f"FeatureAdapter initialized (dim={target_dim}, normalize={normalize}, device={device})")

    def adapt(self, unified_features: Dict[str, Any]) -> torch.Tensor:
        """
        Adapt unified features to observation tensor.

        Args:
            unified_features: Dict from feature pipeline with 409+ fields

        Returns:
            PyTorch tensor of shape (target_dim,) with dtype float32
        """
        # 1. Extract and order fields
        feature_array = self._extract_features(unified_features)

        # 2. Handle missing dimensions
        if len(feature_array) < self.target_dim:
            feature_array = np.pad(
                feature_array,
                (0, self.target_dim - len(feature_array)),
                mode='constant',
                constant_values=0.0
            )
        elif len(feature_array) > self.target_dim:
            # Truncate to target (keep priority fields)
            feature_array = feature_array[:self.target_dim]

        # 3. Handle NaN/Inf
        feature_array = self._safe_clean(feature_array)

        # 4. Normalize if enabled
        if self.normalize:
            feature_array = self._normalize(feature_array)

        # 5. Convert to tensor
        tensor = torch.from_numpy(feature_array.astype(np.float32))
        tensor = tensor.to(self.device)

        return tensor

    def _extract_features(self, unified_features: Dict[str, Any]) -> np.ndarray:
        """
        Extract feature fields from dict and convert to ordered array.

        Priority:
        1. Explicitly ordered critical fields
        2. TA indicators (start with ta_)
        3. CoinAnk features
        4. Other fields
        """
        extracted = []

        # Phase 1: Critical fields in priority order
        for field_name in self.FIELD_PRIORITY:
            if field_name in unified_features:
                val = unified_features[field_name]
                extracted.append(self._to_float(val))

        # Phase 2: TA indicators
        for key, val in unified_features.items():
            if key.startswith("ta_") and key not in self.FIELD_PRIORITY:
                extracted.append(self._to_float(val))

        # Phase 3: CoinAnk features
        for key, val in unified_features.items():
            if key.startswith("coinank_") and key not in self.FIELD_PRIORITY:
                extracted.append(self._to_float(val))

        # Phase 4: Remaining fields
        for key, val in unified_features.items():
            if (not key.startswith("ta_") and
                not key.startswith("coinank_") and
                key not in self.FIELD_PRIORITY):
                extracted.append(self._to_float(val))

        # Track for debugging
        self.field_count = len(extracted)
        if len(extracted) > self.target_dim:
            logger.warning(f"Feature count ({len(extracted)}) exceeds target dim ({self.target_dim})")

        return np.array(extracted, dtype=np.float32)

    @staticmethod
    def _to_float(val: Any) -> float:
        """Safely convert any value to float."""
        try:
            if val is None:
                return 0.0
            if isinstance(val, (int, float, np.integer, np.floating)):
                return float(val)
            if isinstance(val, bool):
                return 1.0 if val else 0.0
            if isinstance(val, str):
                return float(val)  # May raise ValueError
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_clean(arr: np.ndarray) -> np.ndarray:
        """Handle NaN and Inf values."""
        arr = np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
        arr = np.clip(arr, -1e6, 1e6)  # Clip extreme values
        return arr

    def _normalize(self, arr: np.ndarray) -> np.ndarray:
        """
        Normalize to approximately [-1, 1].

        If stats not available, use robust normalization (quantile-based).
        """
        if self.mean is None:
            # First call: compute stats
            valid_mask = np.isfinite(arr)
            if not np.any(valid_mask):
                return arr

            valid = arr[valid_mask]

            self.mean = np.mean(valid)
            self.std = np.std(valid)
            self.min_val = np.percentile(valid, 1)
            self.max_val = np.percentile(valid, 99)
            self.normalization_ready = True

            logger.info(f"Normalization stats computed: mean={self.mean:.4f}, std={self.std:.4f}")

        # Normalize with running stats
        epsilon = 1e-8
        if self.std > epsilon:
            arr = (arr - self.mean) / (self.std + epsilon)
        else:
            arr = (arr - self.mean) / epsilon

        # Clip to [-1, 1] after normalization
        arr = np.clip(arr, -1.0, 1.0)

        return arr

    def batch_adapt(self, batch_features: list) -> torch.Tensor:
        """
        Adapt a batch of feature dicts.

        Args:
            batch_features: List of unified_features dicts

        Returns:
            Tensor of shape (batch_size, target_dim)
        """
        batch = []
        for features_dict in batch_features:
            tensor = self.adapt(features_dict)
            batch.append(tensor.cpu().numpy())

        batch_array = np.stack(batch, axis=0)
        batch_tensor = torch.from_numpy(batch_array.astype(np.float32))
        return batch_tensor.to(self.device)

    def get_stats(self) -> Dict[str, Any]:
        """Get normalization statistics."""
        return {
            "field_count": self.field_count,
            "target_dim": self.target_dim,
            "mean": float(self.mean) if self.mean is not None else None,
            "std": float(self.std) if self.std is not None else None,
            "min": float(self.min_val) if self.min_val is not None else None,
            "max": float(self.max_val) if self.max_val is not None else None,
            "normalization_ready": self.normalization_ready,
        }


if __name__ == "__main__":
    # Test adapter
    adapter = FeatureAdapter(target_dim=562, normalize=True, device="cpu")

    # Simulate unified features (409 fields)
    mock_features = {
        "ohlcv_return": 0.0012,
        "ta_RSI_14": 65.5,
        "ta_MACD_12_26_9_macd": -0.0234,
        "regime_volatility": 0.45,
        "toxicity_overall": 0.25,
        "microstructure_spread_bps": 2.1,
        "liquidation_level_long": 44500.0,
        "liquidation_level_short": 45500.0,
        "freshness_data_quality": 0.95,
        "data_completeness_pct": 85.5,
    }

    # Add more fields to reach ~409
    for i in range(400):
        mock_features[f"field_{i}"] = np.random.randn()

    # Test adaptation
    obs_tensor = adapter.adapt(mock_features)

    print(f"\n✅ Feature Adapter Test:")
    print(f"   Input features: {len(mock_features)}")
    print(f"   Output tensor shape: {obs_tensor.shape}")
    print(f"   Output dtype: {obs_tensor.dtype}")
    print(f"   Output device: {obs_tensor.device}")
    print(f"   Output range: [{obs_tensor.min().item():.4f}, {obs_tensor.max().item():.4f}]")
    print(f"   Adapter stats: {adapter.get_stats()}")
