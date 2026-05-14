"""
Proposal Schema (Jan 2026)
==========================

Strict schema for all trade proposals. Every module MUST use this schema
to emit proposals to the orchestrator. Direct publishing is forbidden.

This enforces:
- Consistent fields across all modules
- Required fields for arbitration (source, priority, etc.)
- Trace chain for audit (proposal_id → plan_id → execution_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Map string urgency labels to float scores
_URGENCY_MAP = {"CRITICAL": 0.95, "HIGH": 0.75, "MEDIUM": 0.50, "MODERATE": 0.50, "LOW": 0.25}

def _safe_urgency_float(val) -> float:
    """Convert urgency value (string or number) to float safely."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return _URGENCY_MAP.get(val.upper(), 0.0)
    return 0.0


class ProposalPriority(Enum):
    """Priority levels for proposal arbitration."""
    LOW = 0           # Background optimization (e.g., rebalance suggestions)
    NORMAL = 1        # Standard signals (GPU predictions, hedge adds)
    HIGH = 2          # Important signals (profit exits, hedge adjustments)
    CRITICAL = 3      # Emergency signals (SHIELD mode, liquidation prevention)
    IMMEDIATE = 4     # Flush immediately, no window wait (ECF, emergency)


class ActionCategory(Enum):
    """Categories for arbitration grouping."""
    OPEN_RISK = "OPEN_RISK"           # New position entries
    HEDGE = "HEDGE"                    # Hedge opens/adds
    RECOVERY = "RECOVERY"              # Underwater recovery (URC)
    PROTECTIVE = "PROTECTIVE"          # SHIELD mode, emergency hedges
    CLOSE_PROFIT = "CLOSE_PROFIT"      # Take profit exits
    CLOSE_LOSS = "CLOSE_LOSS"          # Loss realization (rarely allowed)
    ADJUST = "ADJUST"                  # Position adjustments
    TP_MANAGEMENT = "TP_MANAGEMENT"    # Dynamic TP updates
    SIDECAR = "SIDECAR"                # ARM_*, SET_*, UPDATE_* (non-competing)


@dataclass
class TradeProposal:
    """
    Strict schema for trade proposals.
    
    All modules MUST construct proposals using this class.
    Missing required fields will raise ValidationError.
    """
    # === REQUIRED: Identity ===
    account_id: str                     # "primary" or "asjad"
    symbol: str                         # e.g., "BTCUSDT"
    action: str                         # e.g., "OPEN_LONG", "PARTIAL_CLOSE_SHORT"
    source_module: str                  # e.g., "hedge_manager_v3", "urc", "gpu_predictor"
    
    # === REQUIRED: Arbitration ===
    category: str                       # ActionCategory value
    priority: int = 1                   # ProposalPriority value (0-4)
    confidence: float = 0.0             # Model confidence (0.0-1.0)
    urgency_score: float = 0.0          # Urgency for arbitration (0.0-1.0)
    expected_edge_net: float = 0.0      # Expected edge after fees/slippage
    
    # === REQUIRED: Risk/Sizing ===
    margin_usd: float = 0.0             # Margin required
    notional_usd: float = 0.0           # Notional value
    leverage: float = 1.0               # Leverage
    risk_delta: float = 0.0             # Change in portfolio risk
    
    # === REQUIRED: No-Loss Compliance ===
    no_loss_compliant: bool = True      # Does this comply with no-loss rule?
    profit_intent: bool = False         # Is this a profit-taking action?
    expected_pnl_usd: float = 0.0       # Expected PnL if executed
    
    # === GENERATED: Tracking ===
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""                  # Links to parent decision cycle
    cycle_id: str = ""                  # Decision tick identifier
    created_ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    
    # === OPTIONAL: Context ===
    side: str = ""                      # "LONG" or "SHORT"
    hedge_intent: bool = False          # Is this a hedge action?
    hedge_necessity_class: int = 0      # 0-4 (higher = more urgent)
    pds: float = 0.0                    # Protection Demand Score
    trigger_reason: str = ""            # Why this was generated
    
    # === OPTIONAL: Execution Hints ===
    current_price: float = 0.0          # Mark/mid price at signal time
    target_price: float = 0.0           # Target price if any
    stop_loss: float = 0.0              # SL if any
    take_profit: float = 0.0            # TP if any
    reduce_only: bool = False           # Reduce-only order
    
    # === MARKET CONTEXT (Required for orchestrator scoring) ===
    ctx_id: str = ""                    # MarketContext snapshot ID
    orderbook_ts_ms: int = 0            # Order book data timestamp
    liqmap_ts_ms: int = 0               # Liquidation map timestamp
    
    # === COMPARABLE SCORES (For utility-based winner selection) ===
    # These scores are computed using the linked MarketContext
    scores: Dict[str, float] = field(default_factory=dict)
    # Expected fields in scores:
    # - edge_net_usd: Expected value after fees + slippage + spread
    # - fill_prob: Maker/taker conditional fill probability
    # - toxicity_score: Order book toxicity (spoof/churn/adverse selection)
    # - liq_risk: Distance to liquidation bands + density
    # - capital_efficiency: Expected net profit per margin-hour
    # - utility: Final combined utility score
    
    # === PROOF: Top Features / Why Generated ===
    proof_top_features: List[Dict[str, Any]] = field(default_factory=list)
    # Each entry: {"feature": "rsi_14", "value": 0.72, "contribution": 0.15}
    
    # === METADATA ===
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate required fields and normalize values."""
        # Normalize account_id
        self.account_id = str(self.account_id or "").strip().lower()
        if not self.account_id:
            raise ValueError("account_id is required")
        if self.account_id not in ("primary", "asjad"):
            raise ValueError(f"Invalid account_id: {self.account_id}")
        
        # Normalize symbol
        self.symbol = str(self.symbol or "").strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        
        # Normalize action
        self.action = str(self.action or "").strip().upper()
        if not self.action:
            raise ValueError("action is required")
        
        # Validate source_module
        if not self.source_module:
            raise ValueError("source_module is required")
        
        # Normalize category
        self.category = str(self.category or "").strip().upper()
        if not self.category:
            self.category = self._infer_category()
        
        # Normalize priority
        self.priority = int(self.priority or 1)
        if self.priority < 0 or self.priority > 4:
            self.priority = 1
        
        # Normalize confidence
        if self.confidence > 1.0:
            self.confidence = self.confidence / 100.0
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        
        # Normalize urgency
        self.urgency_score = max(0.0, min(1.0, float(self.urgency_score or 0.0)))
        
        # Infer side from action if not set
        if not self.side:
            self.side = self._infer_side()
        
        # Generate trace_id if not set
        if not self.trace_id:
            self.trace_id = f"t_{int(time.time() * 1000)}_{self.proposal_id[:8]}"
        
        # Generate cycle_id if not set
        if not self.cycle_id:
            # Cycle ID groups proposals within a decision window
            window_ms = 500  # 500ms window
            self.cycle_id = f"c_{int(self.created_ts_ms // window_ms)}"
    
    def _infer_category(self) -> str:
        """Infer category from action name."""
        action = self.action.upper()
        
        if action.startswith("OPEN_HEDGE") or action.startswith("ADD_HEDGE"):
            return "HEDGE"
        if "HEDGE" in action:
            return "HEDGE"
        if action.startswith("OPEN_") or action.startswith("INCREASE_"):
            return "OPEN_RISK"
        if "CLOSE" in action and self.profit_intent:
            return "CLOSE_PROFIT"
        if "CLOSE" in action:
            return "ADJUST"
        if action.startswith("SET_") or action.startswith("ARM_") or action.startswith("UPDATE_"):
            return "SIDECAR"
        
        return "OPEN_RISK"
    
    def _infer_side(self) -> str:
        """Infer side from action name."""
        action = self.action.upper()
        if "LONG" in action:
            return "LONG"
        if "SHORT" in action:
            return "SHORT"
        return ""
    
    @property
    def dedupe_key(self) -> str:
        """
        Stable key for deduplication.
        Same (account, symbol, action_family, side, cycle_id) = same intent.
        """
        action_family = self._action_family()
        return f"{self.account_id}:{self.symbol}:{action_family}:{self.side}:{self.cycle_id}"
    
    def _action_family(self) -> str:
        """Group similar actions into families for dedupe."""
        action = self.action.upper()
        if action.startswith("OPEN_HEDGE") or action.startswith("ADD_HEDGE"):
            return "HEDGE_ADD"
        if "PARTIAL_CLOSE" in action:
            return "PARTIAL_CLOSE"
        if "CLOSE" in action:
            return "CLOSE"
        if action.startswith("OPEN_") or action.startswith("INCREASE_"):
            return "OPEN_INCREASE"
        return action
    
    @property
    def is_critical(self) -> bool:
        """Should this proposal be flushed immediately?"""
        return self.priority >= ProposalPriority.CRITICAL.value
    
    @property
    def is_sidecar(self) -> bool:
        """Is this a non-competing sidecar action?"""
        action = self.action.upper()
        return action.startswith("SET_") or action.startswith("ARM_") or action.startswith("UPDATE_")
    
    @property
    def is_exposure_increasing(self) -> bool:
        """Does this increase position exposure?"""
        action = self.action.upper()
        return (
            action.startswith("OPEN_") or 
            action.startswith("INCREASE_") or 
            action.startswith("ADD_")
        )
    
    @property
    def has_scores(self) -> bool:
        """Check if proposal has computed scores for arbitration."""
        return bool(self.scores) and "utility" in self.scores
    
    @property
    def has_context(self) -> bool:
        """Check if proposal links to a market context."""
        return bool(self.ctx_id)
    
    @property
    def is_scored(self) -> bool:
        """Check if proposal is fully scored and ready for arbitration."""
        return self.has_scores and self.has_context
    
    def compute_scores(self, market_context: Any) -> Dict[str, float]:
        """
        Compute comparable scores using the linked MarketContext.
        
        This ensures all proposals can be compared on the same basis.
        Returns the scores dict and also updates self.scores.
        """
        from rl.market_context import MarketContext
        
        if not isinstance(market_context, MarketContext):
            return {}
        
        # Link context
        self.ctx_id = market_context.ctx_id
        self.orderbook_ts_ms = market_context.price_ts_ms
        self.liqmap_ts_ms = market_context.created_ts_ms
        
        # Compute scores
        scores = {}
        
        # 1. Edge net USD (expected value after fees + slippage)
        base_edge = self.expected_edge_net or 0.0
        slippage_penalty = market_context.orderbook.expected_slippage_bps / 10000 * abs(self.notional_usd or 0)
        scores["edge_net_usd"] = base_edge - slippage_penalty
        
        # 2. Fill probability (maker vs taker)
        if self.reduce_only or "CLOSE" in self.action.upper():
            scores["fill_prob"] = market_context.orderbook.fill_prob_taker
        else:
            scores["fill_prob"] = market_context.orderbook.fill_prob_maker
        
        # 3. Toxicity score (0-1, higher = worse)
        scores["toxicity_score"] = market_context.orderbook.toxicity_score
        
        # 4. Liquidation risk (0-1, higher = worse)
        scores["liq_risk"] = market_context.liquidation.liq_risk_score
        
        # 5. Capital efficiency (expected profit per margin-hour)
        if self.margin_usd > 0 and scores["edge_net_usd"] > 0:
            # Assume 1 hour hold for simplicity
            scores["capital_efficiency"] = scores["edge_net_usd"] / self.margin_usd
        else:
            scores["capital_efficiency"] = 0.0
        
        # 6. Compute utility (regime-weighted)
        weights = market_context.regime.get_weight_multipliers()
        
        utility = (
            weights["edge_weight"] * scores["edge_net_usd"] * 10  # Scale edge
            + weights["fill_prob_weight"] * scores["fill_prob"] * 5  # Fill prob boost
            - weights["toxicity_weight"] * scores["toxicity_score"] * 3  # Toxicity penalty
            - weights["liq_risk_weight"] * scores["liq_risk"] * 3  # Liq risk penalty
            + weights["capital_eff_weight"] * scores["capital_efficiency"] * 2  # Cap eff boost
        )
        
        # Data quality adjustment
        utility *= market_context.data_quality_score
        
        scores["utility"] = utility
        scores["regime"] = market_context.regime.regime
        scores["data_quality"] = market_context.data_quality_score
        
        self.scores = scores
        return scores
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeProposal":
        """Create from dictionary."""
        # Extract known fields
        known_fields = {
            "account_id", "symbol", "action", "source_module", "category",
            "priority", "confidence", "urgency_score", "expected_edge_net",
            "margin_usd", "notional_usd", "leverage", "risk_delta",
            "no_loss_compliant", "profit_intent", "expected_pnl_usd",
            "proposal_id", "trace_id", "cycle_id", "created_ts_ms",
            "side", "hedge_intent", "hedge_necessity_class", "pds",
            "trigger_reason", "current_price", "target_price", "stop_loss", "take_profit",
            "reduce_only", "metadata",
            # New market context fields
            "ctx_id", "orderbook_ts_ms", "liqmap_ts_ms",
            "scores", "proof_top_features"
        }
        
        kwargs = {k: v for k, v in data.items() if k in known_fields}
        
        # Put unknown fields in metadata
        metadata = dict(kwargs.get("metadata") or {})
        for k, v in data.items():
            if k not in known_fields:
                metadata[k] = v
        kwargs["metadata"] = metadata
        
        return cls(**kwargs)
    
    @classmethod
    def from_json(cls, json_str: str) -> "TradeProposal":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    @classmethod
    def from_legacy_payload(cls, payload: Dict[str, Any]) -> "TradeProposal":
        """
        Convert legacy signal payload to TradeProposal.
        Maps old field names to new schema.
        """
        # Extract scores if present
        scores = payload.get("scores") or {}
        if not isinstance(scores, dict):
            scores = {}
        
        # Extract proof_top_features if present
        proof_top_features = payload.get("proof_top_features") or payload.get("top_features") or []
        if not isinstance(proof_top_features, list):
            proof_top_features = []
        
        # Map legacy fields
        return cls(
            account_id=str(payload.get("account_id") or payload.get("account") or "primary"),
            symbol=str(payload.get("symbol") or ""),
            action=str(payload.get("action") or payload.get("final_action") or payload.get("action_name") or ""),
            source_module=str(payload.get("source") or payload.get("source_module") or "legacy"),
            category=str(payload.get("action_category") or payload.get("category") or ""),
            priority=int(payload.get("priority") or 1),
            confidence=float(payload.get("confidence") or payload.get("model_confidence") or 0.0),
            urgency_score=_safe_urgency_float(payload.get("urgency_score") or payload.get("trade_urgency") or payload.get("urgency") or 0.0),
            expected_edge_net=float(payload.get("expected_edge_net") or payload.get("edge_score") or 0.0),
            margin_usd=float(payload.get("margin_usd") or 0.0),
            notional_usd=float(payload.get("notional_usd") or 0.0),
            leverage=float(payload.get("leverage") or 1.0),
            risk_delta=float(payload.get("risk_delta") or 0.0),
            no_loss_compliant=bool(payload.get("no_loss_compliant", True)),
            profit_intent=bool(payload.get("profit_intent", False)),
            expected_pnl_usd=float(payload.get("expected_pnl_usd") or payload.get("expected_profit_usd") or 0.0),
            trace_id=str(payload.get("trace_id") or ""),
            cycle_id=str(payload.get("cycle_id") or ""),
            side=str(payload.get("side") or ""),
            hedge_intent=bool(payload.get("hedge_intent", False)),
            hedge_necessity_class=int(payload.get("hedge_necessity_class") or 0),
            pds=float(payload.get("pds") or payload.get("protection_demand_score") or 0.0),
            trigger_reason=str(payload.get("trigger_reason") or payload.get("reason") or ""),
            current_price=float(payload.get("current_price") or payload.get("price") or payload.get("mark_price") or 0.0),
            target_price=float(payload.get("target_price") or payload.get("price_target") or 0.0),
            stop_loss=float(payload.get("stop_loss") or payload.get("sl") or 0.0),
            take_profit=float(payload.get("take_profit") or payload.get("tp") or 0.0),
            reduce_only=bool(payload.get("reduce_only", False)),
            # New market context fields
            ctx_id=str(payload.get("ctx_id") or ""),
            orderbook_ts_ms=int(payload.get("orderbook_ts_ms") or payload.get("orderbook_ts") or 0),
            liqmap_ts_ms=int(payload.get("liqmap_ts_ms") or payload.get("liqmap_ts") or 0),
            scores=scores,
            proof_top_features=proof_top_features,
            metadata=payload,  # Preserve all original fields
        )


def validate_proposal(data: Dict[str, Any]) -> TradeProposal:
    """
    Validate and construct a TradeProposal.
    Raises ValueError if validation fails.
    """
    return TradeProposal.from_dict(data)


def emit_proposal_to_stream(
    redis_client: Any,
    proposal: TradeProposal,
    stream: str = "wma:proposals",
) -> bool:
    """
    Emit a validated proposal to the orchestrator stream.
    
    Returns True if successful, False otherwise.
    Does NOT fall back to direct publish.
    """
    if redis_client is None:
        logger.error("[PROPOSAL_EMIT] Redis client is None - cannot emit proposal")
        return False
    
    try:
        data = proposal.to_dict()
        data["event"] = "TRADE_PROPOSAL"
        data["schema_version"] = "2026.01.25"
        
        json_data = json.dumps(data, separators=(",", ":"), default=str)
        
        try:
            from config import STREAM_MAXLEN_PROPOSALS
            maxlen = int(STREAM_MAXLEN_PROPOSALS)
        except Exception:
            maxlen = 50000

        _stream_fields = {"data": json_data}
        _sym = str(data.get("symbol") or "")
        _tf = str(data.get("timeframe") or "")
        if _sym:
            _stream_fields["symbol"] = _sym
        if _tf:
            _stream_fields["timeframe"] = _tf

        msg_id = redis_client.xadd(
            stream,
            _stream_fields,
            maxlen=maxlen,
            approximate=True,
        )
        
        logger.info(
            f"📤 [PROPOSAL] {proposal.account_id}:{proposal.symbol} {proposal.action} "
            f"src={proposal.source_module} pri={proposal.priority} id={proposal.proposal_id[:8]} "
            f"stream_id={msg_id}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"[PROPOSAL_EMIT] Failed to emit proposal: {e}")
        return False
