from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MarketType(str, Enum):
    FUTURES = "futures"
    SPOT = "spot"


class ContractFamily(str, Enum):
    COIN_M = "coin_m"
    USD_M = "usd_m"
    LINEAR = "linear"
    INVERSE = "inverse"
    UNKNOWN = "unknown"


class ContractType(str, Enum):
    PERPETUAL = "perpetual"
    CURRENT_QUARTER = "current_quarter"
    NEXT_QUARTER = "next_quarter"
    DATED_DELIVERY = "dated_delivery"
    UNKNOWN = "unknown"


class NormalizationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SymbolState(str, Enum):
    DISCOVERED = "discovered"
    OBSERVED = "observed"
    ELIGIBLE_FOR_TRAINING = "eligible_for_training"
    TRAINING_ACTIVE = "training_active"
    ELIGIBLE_FOR_PAPER = "eligible_for_paper"
    PAPER_TRADING = "paper_trading"
    SHADOW_CANDIDATE = "shadow_candidate"
    LIVE_BLOCKED = "live_blocked"
    DISABLED = "disabled"
    REMOVED = "removed"
    MANUAL_OVERRIDE = "manual_override"


class ManualOverride(str, Enum):
    FORCE_OBSERVE = "force_observe"
    FORCE_TRAIN = "force_train"
    FORCE_DISABLE = "force_disable"
    FORCE_PAPER = "force_paper"
    FORCE_SHADOW_CANDIDATE = "force_shadow_candidate"
    REMOVE = "remove"
    SET_PRIORITY = "set_priority"
    SET_MAX_RISK = "set_max_risk"
    PAUSE_SYMBOL = "pause_symbol"


@dataclass(frozen=True)
class SymbolIdentity:
    canonical_symbol_id: str
    base_asset: str
    quote_asset: str
    settlement_asset: str
    market_type: str
    contract_family: str
    contract_type: str
    exchange: str
    source: str
    source_symbol: str
    source_pair: Optional[str] = None
    legacy_symbol: Optional[str] = None
    normalization_confidence: str = NormalizationConfidence.MEDIUM.value
    alias_set: List[str] = field(default_factory=list)
    status: Optional[str] = None
    last_seen_ts: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_trading(self) -> bool:
        return (self.status or "").upper() in {"TRADING", "LIVE", "OPEN", "ACTIVE"}


@dataclass(frozen=True)
class SymbolOverride:
    action: str
    reason: str
    priority: Optional[int] = None
    max_risk: Optional[float] = None


@dataclass(frozen=True)
class SymbolStateRecord:
    identity: SymbolIdentity
    state: str = SymbolState.DISCOVERED.value
    override: Optional[SymbolOverride] = None
    state_reason: str = "initial_discovery"


@dataclass(frozen=True)
class SymbolScoreInput:
    liquidity_score: float = 0.0
    volume_score: float = 0.0
    volatility_score: float = 0.0
    spread_score: float = 0.0
    funding_score: float = 0.0
    open_interest_score: float = 0.0
    freshness_score: float = 0.0
    feature_completeness_score: float = 0.0
    exchange_availability_score: float = 0.0
    replay_score: float = 0.0
    paper_score: float = 0.0
    risk_score: float = 0.0
    manual_priority_score: float = 0.0


@dataclass(frozen=True)
class SymbolScore:
    canonical_symbol_id: str
    total_score: float
    confidence: str
    reason_codes: List[str]
    eligible_for_training: bool
    eligible_for_paper: bool
    eligible_for_shadow: bool


@dataclass(frozen=True)
class UniverseVersion:
    universe_version_id: str
    generated_ts: str
    source_snapshot_ids: List[str]
    changed_symbols: List[str]
    added_symbols: List[str]
    removed_symbols: List[str]
    disabled_symbols: List[str]
    override_symbols: List[str]
    reason: str
    approval_state: str
    hot_reload_required_components: List[str]

