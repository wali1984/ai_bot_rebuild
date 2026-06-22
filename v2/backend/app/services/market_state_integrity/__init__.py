"""V2 market-state integrity scoring.

The package is intentionally read-only. It scores current V2 market/prediction
state and emits reject reasons for trainer, prediction, risk, orchestrator,
paper, and live gates. It never calls exchange mutation endpoints.
"""

from .contracts import IntegrityThresholds, MarketStateScore
from .decision_replay import clear_decision_replays, get_decision_replay, persist_decision_replay
from .scoring import score_market_state
from .trust import (
    EventTimeAligner,
    MarketStateEnvelope,
    TrustGateRejectedError,
    TrustGateResult,
    build_market_state_envelope_from_snapshot,
    coerce_market_state_envelope,
    coerce_trust_gate_result,
    hash_market_state_envelope,
    parse_timestamp,
    stable_hash,
)
from .validators import validate_candle_completion, validate_event_time_alignment

__all__ = [
    "IntegrityThresholds",
    "MarketStateScore",
    "MarketStateEnvelope",
    "TrustGateResult",
    "TrustGateRejectedError",
    "EventTimeAligner",
    "build_market_state_envelope_from_snapshot",
    "coerce_market_state_envelope",
    "coerce_trust_gate_result",
    "hash_market_state_envelope",
    "parse_timestamp",
    "stable_hash",
    "persist_decision_replay",
    "get_decision_replay",
    "clear_decision_replays",
    "score_market_state",
    "validate_candle_completion",
    "validate_event_time_alignment",
]
