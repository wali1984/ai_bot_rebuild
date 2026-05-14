"""
Observation Schema Registry for PPO Checkpoint Compatibility

This module manages observation vector schemas to ensure checkpoint/model compatibility
across restarts and feature changes.

Schema Versions:
- v1: Base features (1053 dims) - legacy, no on-chain, no position context
- v2: With on-chain features (1061 dims) - adds BTC/ETH on-chain slices  
- v3: Full enhanced (1911 dims) - current production default

The system auto-detects checkpoint schema and downgrades/upgrades as needed.
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ObsSchemaVersion(Enum):
    """Known observation schema versions."""
    V1_LEGACY = "v1"         # 1053 dims - legacy
    V2_ONCHAIN = "v2"        # 1061 dims - adds on-chain
    V3_ENHANCED = "v3"       # 1911 dims - current production
    UNKNOWN = "unknown"


@dataclass
class ObsSlice:
    """Describes a slice within the observation vector."""
    name: str
    size: int
    start_idx: int = 0
    end_idx: int = 0
    optional: bool = False
    description: str = ""


@dataclass
class ObsSchema:
    """Complete observation schema definition."""
    version: ObsSchemaVersion
    total_dim: int
    slices: List[ObsSlice] = field(default_factory=list)
    description: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version.value,
            "total_dim": self.total_dim,
            "slices": [
                {
                    "name": s.name,
                    "size": s.size,
                    "start_idx": s.start_idx,
                    "end_idx": s.end_idx,
                    "optional": s.optional,
                }
                for s in self.slices
            ],
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ObsSchema":
        """Create from dictionary."""
        version_str = data.get("version", "unknown")
        try:
            version = ObsSchemaVersion(version_str)
        except ValueError:
            version = ObsSchemaVersion.UNKNOWN
            
        slices = [
            ObsSlice(
                name=s.get("name", "unknown"),
                size=s.get("size", 0),
                start_idx=s.get("start_idx", 0),
                end_idx=s.get("end_idx", 0),
                optional=s.get("optional", False),
            )
            for s in data.get("slices", [])
        ]
        
        return cls(
            version=version,
            total_dim=data.get("total_dim", 0),
            slices=slices,
            description=data.get("description", ""),
        )
    
    def get_slice_summary(self) -> str:
        """Get human-readable summary of slices."""
        parts = []
        for s in self.slices:
            opt_marker = "?" if s.optional else ""
            parts.append(f"{s.name}{opt_marker}:{s.size}")
        return ",".join(parts)


# ============================================================================
# Schema Definitions
# ============================================================================

def _build_schema_v1() -> ObsSchema:
    """Build schema v1 (legacy, 1053 dims)."""
    slices = [
        ObsSlice(name="technical_indicators", size=50, description="RSI, MACD, BB, etc."),
        ObsSlice(name="ohlcv_multi_tf", size=600, description="OHLCV across timeframes"),
        ObsSlice(name="orderbook_depth", size=100, description="Bid/ask depth features"),
        ObsSlice(name="volatility", size=50, description="Volatility measures"),
        ObsSlice(name="momentum", size=50, description="Momentum indicators"),
        ObsSlice(name="volume_profile", size=50, description="Volume profile features"),
        ObsSlice(name="portfolio_state", size=153, description="Positions, balances, entries"),
    ]
    # Calculate indices
    idx = 0
    for s in slices:
        s.start_idx = idx
        s.end_idx = idx + s.size
        idx = s.end_idx
        
    return ObsSchema(
        version=ObsSchemaVersion.V1_LEGACY,
        total_dim=1053,
        slices=slices,
        description="Legacy schema without on-chain features",
    )


def _build_schema_v2() -> ObsSchema:
    """Build schema v2 (with on-chain, 1061 dims)."""
    slices = [
        ObsSlice(name="technical_indicators", size=50),
        ObsSlice(name="ohlcv_multi_tf", size=600),
        ObsSlice(name="orderbook_depth", size=100),
        ObsSlice(name="volatility", size=50),
        ObsSlice(name="momentum", size=50),
        ObsSlice(name="volume_profile", size=50),
        ObsSlice(name="portfolio_state", size=153),
        ObsSlice(name="onchain_btc", size=4, optional=True, description="BTC on-chain features"),
        ObsSlice(name="onchain_eth", size=4, optional=True, description="ETH on-chain features"),
    ]
    idx = 0
    for s in slices:
        s.start_idx = idx
        s.end_idx = idx + s.size
        idx = s.end_idx
        
    return ObsSchema(
        version=ObsSchemaVersion.V2_ONCHAIN,
        total_dim=1061,
        slices=slices,
        description="Schema with on-chain features for BTC/ETH",
    )


def _build_schema_v3() -> ObsSchema:
    """Build schema v3 (current enhanced, 1911 dims)."""
    slices = [
        ObsSlice(name="unified_features", size=1430, description="Comprehensive unified features"),
        ObsSlice(name="portfolio_state", size=401, description="Extended portfolio state"),
        ObsSlice(name="onchain_btc", size=15, optional=True, description="BTC on-chain features"),
        ObsSlice(name="onchain_eth", size=15, optional=True, description="ETH on-chain features"),
        ObsSlice(name="position_context", size=50, optional=True, description="Position MFE/MAE/ROE context"),
    ]
    idx = 0
    for s in slices:
        s.start_idx = idx
        s.end_idx = idx + s.size
        idx = s.end_idx
        
    return ObsSchema(
        version=ObsSchemaVersion.V3_ENHANCED,
        total_dim=1911,
        slices=slices,
        description="Current production schema with full features",
    )


# Schema registry
SCHEMA_REGISTRY: Dict[ObsSchemaVersion, ObsSchema] = {
    ObsSchemaVersion.V1_LEGACY: _build_schema_v1(),
    ObsSchemaVersion.V2_ONCHAIN: _build_schema_v2(),
    ObsSchemaVersion.V3_ENHANCED: _build_schema_v3(),
}

# Dimension to schema mapping for auto-detection
DIM_TO_SCHEMA: Dict[int, ObsSchemaVersion] = {
    1053: ObsSchemaVersion.V1_LEGACY,
    1061: ObsSchemaVersion.V2_ONCHAIN,
    1911: ObsSchemaVersion.V3_ENHANCED,
}


# ============================================================================
# Schema Manager
# ============================================================================

class ObsSchemaManager:
    """
    Manages observation schema selection and checkpoint compatibility.
    
    Responsibilities:
    1. Detect checkpoint schema from metadata or dimension
    2. Select compatible schema for current session
    3. Enable/disable optional slices to match target dimension
    4. Log schema info on startup
    """
    
    def __init__(self, default_version: str = "v3"):
        self.default_version = default_version
        self.active_schema: Optional[ObsSchema] = None
        self.checkpoint_schema: Optional[ObsSchema] = None
        self.safe_mode_active = False
        self.safe_mode_reason: Optional[str] = None
        
    def detect_schema_from_dim(self, dim: int) -> Optional[ObsSchema]:
        """Detect schema version from observation dimension."""
        version = DIM_TO_SCHEMA.get(dim)
        if version:
            return SCHEMA_REGISTRY[version]
        # Try fuzzy match (within 5%)
        for known_dim, version in DIM_TO_SCHEMA.items():
            if abs(known_dim - dim) < known_dim * 0.05:
                logger.warning(
                    f"Fuzzy schema match: dim={dim} ~= {known_dim} (version={version.value})"
                )
                return SCHEMA_REGISTRY[version]
        return None
    
    def load_checkpoint_metadata(self, checkpoint_path: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Load checkpoint metadata to determine expected obs_dim and schema version.
        
        Returns:
            (obs_dim, schema_version) or (None, None) if not found
        """
        obs_dim = None
        schema_version = None
        
        # Try metadata file first
        metadata_path = checkpoint_path.replace('.zip', '_metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    obs_dim = metadata.get('obs_dim')
                    schema_version = metadata.get('schema_version')
                    logger.info(f"📂 Loaded checkpoint metadata: obs_dim={obs_dim}, schema={schema_version}")
            except Exception as e:
                logger.warning(f"Could not read checkpoint metadata: {e}")
        
        return obs_dim, schema_version
    
    def select_schema(
        self,
        checkpoint_path: Optional[str] = None,
        current_obs_dim: Optional[int] = None,
        force_version: Optional[str] = None,
    ) -> ObsSchema:
        """
        Select the appropriate schema for this session.
        
        Priority:
        1. Force version if specified (from env/config)
        2. Checkpoint schema (if checkpoint exists and is compatible)
        3. Default schema
        
        If checkpoint exists but is incompatible, activates SAFE_MODE.
        """
        # 1. Check for forced version
        env_version = force_version or os.getenv("OBS_SCHEMA_VERSION")
        if env_version:
            try:
                version = ObsSchemaVersion(env_version)
                self.active_schema = SCHEMA_REGISTRY[version]
                logger.info(f"OBS_SCHEMA | forced version={env_version} | dim={self.active_schema.total_dim}")
                return self.active_schema
            except (ValueError, KeyError):
                logger.warning(f"Unknown forced schema version: {env_version}")
        
        # 2. Load checkpoint metadata if available
        if checkpoint_path and os.path.exists(checkpoint_path):
            ckpt_obs_dim, ckpt_version = self.load_checkpoint_metadata(checkpoint_path)
            
            if ckpt_version:
                # Use explicit version from metadata
                try:
                    version = ObsSchemaVersion(ckpt_version)
                    self.checkpoint_schema = SCHEMA_REGISTRY[version]
                except (ValueError, KeyError):
                    pass
            elif ckpt_obs_dim:
                # Infer from dimension
                self.checkpoint_schema = self.detect_schema_from_dim(ckpt_obs_dim)
            
            if self.checkpoint_schema:
                # Check compatibility with current env
                if current_obs_dim and current_obs_dim != self.checkpoint_schema.total_dim:
                    # Need to downgrade/upgrade
                    logger.warning(
                        f"⚠️ [OBS_SCHEMA] Dimension mismatch: current={current_obs_dim}, "
                        f"checkpoint={self.checkpoint_schema.total_dim}"
                    )
                    # Try to adapt by selecting checkpoint schema
                    self.active_schema = self.checkpoint_schema
                    logger.info(
                        f"📊 [OBS_SCHEMA] Auto-adapting to checkpoint schema: "
                        f"version={self.checkpoint_schema.version.value}, dim={self.checkpoint_schema.total_dim}"
                    )
                    return self.active_schema
                else:
                    self.active_schema = self.checkpoint_schema
                    logger.info(
                        f"✅ [OBS_SCHEMA] Checkpoint compatible: version={self.active_schema.version.value}, "
                        f"dim={self.active_schema.total_dim}"
                    )
                    return self.active_schema
        
        # 3. Use default schema
        try:
            version = ObsSchemaVersion(self.default_version)
            self.active_schema = SCHEMA_REGISTRY[version]
        except (ValueError, KeyError):
            self.active_schema = SCHEMA_REGISTRY[ObsSchemaVersion.V3_ENHANCED]
        
        logger.info(
            f"OBS_SCHEMA | version={self.active_schema.version.value} | "
            f"dim={self.active_schema.total_dim} | "
            f"slices=[{self.active_schema.get_slice_summary()}]"
        )
        return self.active_schema
    
    def activate_safe_mode(self, reason: str):
        """Activate SAFE_MODE with reason."""
        self.safe_mode_active = True
        self.safe_mode_reason = reason
        logger.warning(f"⚠️ HEALTH | SAFE_MODE_ACTIVE | reason={reason}")
    
    def deactivate_safe_mode(self):
        """Deactivate SAFE_MODE after successful checkpoint load."""
        if self.safe_mode_active:
            logger.info("✅ SAFE_MODE deactivated - checkpoint loaded successfully")
            self.safe_mode_active = False
            self.safe_mode_reason = None
    
    def is_safe_mode(self) -> bool:
        """Check if SAFE_MODE is active."""
        return self.safe_mode_active
    
    def get_safe_mode_reason(self) -> str:
        """Get SAFE_MODE reason if active."""
        return self.safe_mode_reason or "unknown"
    
    def is_protective_action(self, action) -> bool:
        """Check if action is allowed in SAFE_MODE (protective only)."""
        protective_actions = {
            'CLOSE_LONG', 'CLOSE_SHORT', 'CLOSE_ALL',
            'DECREASE_LONG', 'DECREASE_SHORT',
            'PARTIAL_CLOSE', 'REDUCE', 'HOLD',
        }
        # Handle int action indices (from model) - treat as non-protective
        if isinstance(action, (int, float)):
            # Action indices: 0=HOLD is protective, others depend on mapping
            # HOLD is typically index 0 or 6 depending on action space
            if int(action) in (0, 6):  # HOLD indices
                return True
            return False
        
        # Handle None or empty
        if not action:
            return False
        
        return str(action).upper() in protective_actions
    
    def should_block_action(self, action) -> Tuple[bool, Optional[str]]:
        """
        Check if action should be blocked in SAFE_MODE.
        
        Returns:
            (should_block, reason_code)
        """
        if not self.safe_mode_active:
            return False, None
        
        if self.is_protective_action(action):
            return False, None  # Allow protective actions
        
        return True, f"SAFE_MODE_NO_CHECKPOINT:{self.safe_mode_reason}"
    
    def log_startup_info(self):
        """Log comprehensive schema info on startup."""
        if not self.active_schema:
            logger.warning("OBS_SCHEMA | NOT_INITIALIZED")
            return
        
        lines = [
            f"OBS_SCHEMA | version={self.active_schema.version.value}",
            f"OBS_SCHEMA | dim={self.active_schema.total_dim}",
            f"OBS_SCHEMA | slices=[{self.active_schema.get_slice_summary()}]",
        ]
        
        if self.checkpoint_schema:
            lines.append(f"OBS_SCHEMA | checkpoint_version={self.checkpoint_schema.version.value}")
        
        if self.safe_mode_active:
            lines.append(f"HEALTH | SAFE_MODE_ACTIVE | reason={self.safe_mode_reason}")
        
        for line in lines:
            logger.info(line)
    
    def save_metadata(self, checkpoint_path: str) -> bool:
        """
        Save schema metadata alongside checkpoint for future compatibility.
        
        Call this after saving a checkpoint.
        """
        if not self.active_schema:
            return False
        
        metadata_path = checkpoint_path.replace('.zip', '_metadata.json')
        try:
            metadata = {
                'obs_dim': self.active_schema.total_dim,
                'schema_version': self.active_schema.version.value,
                'schema': self.active_schema.to_dict(),
            }
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.debug(f"Saved schema metadata to {metadata_path}")
            return True
        except Exception as e:
            logger.warning(f"Could not save schema metadata: {e}")
            return False


# Global instance
_schema_manager: Optional[ObsSchemaManager] = None


def get_schema_manager() -> ObsSchemaManager:
    """Get global schema manager instance."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = ObsSchemaManager()
    return _schema_manager


def get_active_schema() -> Optional[ObsSchema]:
    """Get currently active schema."""
    return get_schema_manager().active_schema


def is_safe_mode() -> bool:
    """Check if SAFE_MODE is active."""
    return get_schema_manager().is_safe_mode()


def should_block_action(action) -> Tuple[bool, Optional[str]]:
    """Check if action should be blocked due to SAFE_MODE."""
    return get_schema_manager().should_block_action(action)

