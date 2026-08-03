from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntegrityThresholds:
    training_min_score: float = 80.0
    prediction_min_score: float = 70.0
    risk_min_score: float = 80.0
    paper_min_score: float = 70.0
    live_min_score: float = 90.0


@dataclass
class MarketStateScore:
    market_state_id: str
    symbol: str
    timeframe: str
    decision_time_est: str
    data_freshness_score: float
    candle_completion_score: float
    tf_alignment_score: float
    missing_data_score: float
    source_disagreement_score: float
    latency_score: float
    backfill_score: float
    execution_fill_quality_score: float
    market_state_integrity_score: float
    valid_for_training: bool
    valid_for_prediction: bool
    valid_for_risk: bool
    valid_for_orchestrator: bool
    valid_for_paper: bool
    valid_for_live: bool
    reject_reasons: list[str] = field(default_factory=list)
    source_lineage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_state_id": self.market_state_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_time_est": self.decision_time_est,
            "data_freshness_score": self.data_freshness_score,
            "candle_completion_score": self.candle_completion_score,
            "tf_alignment_score": self.tf_alignment_score,
            "missing_data_score": self.missing_data_score,
            "source_disagreement_score": self.source_disagreement_score,
            "latency_score": self.latency_score,
            "backfill_score": self.backfill_score,
            "execution_fill_quality_score": self.execution_fill_quality_score,
            "market_state_integrity_score": self.market_state_integrity_score,
            "valid_for_training": self.valid_for_training,
            "valid_for_prediction": self.valid_for_prediction,
            "valid_for_risk": self.valid_for_risk,
            "valid_for_orchestrator": self.valid_for_orchestrator,
            "valid_for_paper": self.valid_for_paper,
            "valid_for_live": self.valid_for_live,
            "reject_reasons": list(self.reject_reasons),
            "source_lineage": dict(self.source_lineage),
        }
