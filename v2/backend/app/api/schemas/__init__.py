"""Pydantic shapes for the V2 API surface.

All shapes are wire-compatible with `claude_worklog/v2_architecture/05_API_CONTRACTS.md`
as amended by `12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md`.
"""

from app.api.schemas.decision import DecisionAction, DecisionIngest, DecisionRead
from app.api.schemas.envelope import RequestEnvelope
from app.api.schemas.execution_intent import ExecutionIntentRead, ExecutionIntentSubmit
from app.api.schemas.feature_snapshot import FeatureSnapshotIngest, FeatureSnapshotRead
from app.api.schemas.lineage import CHAIN_FIELDS, LineageBlock, LineageGapReason
from app.api.schemas.paper_trade import PaperTradeAck, PaperTradeRead
from app.api.schemas.prediction import PredictionIngest, PredictionRead
from app.api.schemas.risk_decision import AllowBlock, RiskDecisionIngest, RiskDecisionRead
from app.api.schemas.signal import SignalAction, SignalPublish, SignalRead

__all__ = [
    "AllowBlock",
    "CHAIN_FIELDS",
    "DecisionAction",
    "DecisionIngest",
    "DecisionRead",
    "ExecutionIntentRead",
    "ExecutionIntentSubmit",
    "FeatureSnapshotIngest",
    "FeatureSnapshotRead",
    "LineageBlock",
    "LineageGapReason",
    "PaperTradeAck",
    "PaperTradeRead",
    "PredictionIngest",
    "PredictionRead",
    "RequestEnvelope",
    "RiskDecisionIngest",
    "RiskDecisionRead",
    "SignalAction",
    "SignalPublish",
    "SignalRead",
]
