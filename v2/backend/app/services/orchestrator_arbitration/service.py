"""V2 orchestrator arbitration service (PaperOnly).

A thin façade over ``proposal.score_proposal``, ``signal_schema.validate_signal``,
``deconflict.deconflict_signals``, and ``stream_routing.StreamRouter``.

Safety invariants surfaced through :meth:`current_paper_only_status`:

  - ``live_gate == "blocked_human_only"``
  - ``live_symbols == []``
  - ``approves_live is False``
  - ``cannot_bypass_risk_gateway is True``
  - ``orchestrator_overrides_risk is False``

The arbitration service is informational/paper-only: it does NOT place trades,
does NOT publish to Redis streams, and does NOT call any exchange SDK. Downstream
risk gating remains the binding gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .deconflict import (
    DECONFLICT_REASON_EMPTY,
    DECONFLICT_REASON_MISSING_EVIDENCE,
    DeconflictResult,
    deconflict_signals,
)
from .proposal import DEFAULT_MAX_AGE_SECONDS, Proposal, score_proposal
from .signal_schema import V2Signal, validate_signal
from .stream_routing import (
    STREAM_LABEL_ALLOWED,
    STREAM_LABEL_SHADOW,
    StreamRouter,
)


SERVICE_ID = "v2_orchestrator_arbitration"
LIVE_GATE_STATUS = "blocked_human_only"
RISK_GATEWAY_BINDING = "risk_gateway_is_binding_gate_orchestrator_only_proposes"
LEGACY_SOURCE_PATHS: Tuple[str, ...] = (
    "v2/legacy_preserved/full_runtime_closure/rl/orchestrator_worker.py",
    "v2/legacy_preserved/full_runtime_closure/rl/proposal_bus.py",
    "v2/legacy_preserved/full_runtime_closure/rl/tradeplan_orchestrator.py",
    "v2/legacy_preserved/full_runtime_closure/rl/intent_engine.py",
)

LEGACY_SHA256_INDEX: Dict[str, str] = {
    "v2/legacy_preserved/full_runtime_closure/rl/orchestrator_worker.py":
        "a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6",
    "v2/legacy_preserved/full_runtime_closure/rl/proposal_bus.py":
        "e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d",
    "v2/legacy_preserved/full_runtime_closure/rl/tradeplan_orchestrator.py":
        "1e4ad19faed9dc3498f15401dc1065f1e1eedb400a662fc7272bed7df12fa4d0",
    "v2/legacy_preserved/full_runtime_closure/rl/intent_engine.py":
        "7d8d474237f08f3ab1f2775044f6e535c0a3934eb336c757b2cf4443f18b0975",
}

COMPONENTS_PORTED: Tuple[str, ...] = (
    "proposal_dataclass_and_deterministic_scoring_paper_only",
    "v2_signal_schema_validator",
    "deconflict_signals_with_missing_evidence_fail_closed",
    "stream_routing_informational_metadata_only",
    "stale_signal_handling_via_max_age_seconds",
)

COMPONENTS_MISSING_IN_V2: Tuple[str, ...] = (
    "full_10523_line_orchestrator_worker_arbitration_logic",
    "live_order_routing",
    "live_redis_proposal_bus_integration",
    "hedge_cage_arbitration_overlays",
    "asjad_account_publish_path",
    "intent_engine_higher_timeframe_consensus_full_runtime",
    "tradeplan_orchestrator_protection_demand_score",
)


@dataclass(frozen=True)
class ArbitrationBucketResult:
    """Top scoring proposal for a single ``(symbol, side)`` bucket."""

    symbol: str
    side: str
    winner: Proposal
    score: float
    considered_proposal_ids: Tuple[str, ...]


@dataclass(frozen=True)
class ArbitrationResult:
    bucket_winners: Tuple[ArbitrationBucketResult, ...] = field(default_factory=tuple)
    stale_proposal_ids: Tuple[str, ...] = field(default_factory=tuple)
    considered_count: int = 0


class OrchestratorArbitrationService:
    """Public façade for paper-only orchestrator arbitration primitives."""

    def __init__(
        self,
        *,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        stream_router: Optional[StreamRouter] = None,
    ) -> None:
        if not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be a positive int")
        if stream_router is not None and not isinstance(stream_router, StreamRouter):
            raise TypeError("stream_router must be a StreamRouter or None")
        self._max_age_seconds = max_age_seconds
        self._stream_router = stream_router or StreamRouter()

    # ------------------------------------------------------------------ API
    def arbitrate(self, proposals: Sequence[Proposal]) -> ArbitrationResult:
        """Group proposals by ``(symbol, side)`` and pick the top score per bucket."""
        if not isinstance(proposals, (list, tuple)):
            raise TypeError("proposals must be a list/tuple of Proposal records")
        buckets: Dict[Tuple[str, str], List[Proposal]] = {}
        stale_ids: List[str] = []
        considered_total = 0
        for proposal in proposals:
            if not isinstance(proposal, Proposal):
                continue
            considered_total += 1
            score = score_proposal(proposal, max_age_seconds=self._max_age_seconds)
            if score == float("-inf"):
                stale_ids.append(proposal.proposal_id)
                continue
            key = (proposal.symbol.upper(), proposal.side)
            buckets.setdefault(key, []).append(proposal)

        winners: List[ArbitrationBucketResult] = []
        for (symbol, side), bucket in sorted(buckets.items()):
            scored: List[Tuple[float, Proposal]] = [
                (
                    score_proposal(p, max_age_seconds=self._max_age_seconds),
                    p,
                )
                for p in bucket
            ]
            scored.sort(
                key=lambda item: (
                    -item[0],
                    -float(item[1].confidence_calibrated),
                    float(item[1].freshness_seconds),
                    item[1].proposal_id,
                )
            )
            top_score, top_proposal = scored[0]
            winners.append(
                ArbitrationBucketResult(
                    symbol=symbol,
                    side=side,
                    winner=top_proposal,
                    score=top_score,
                    considered_proposal_ids=tuple(p.proposal_id for p in bucket),
                )
            )
        return ArbitrationResult(
            bucket_winners=tuple(winners),
            stale_proposal_ids=tuple(stale_ids),
            considered_count=considered_total,
        )

    def validate_signal(self, payload: Dict[str, Any]) -> V2Signal:
        return validate_signal(payload)

    def deconflict(self, signals: Sequence[V2Signal]) -> DeconflictResult:
        return deconflict_signals(signals)

    def route(self, symbol: str) -> str:
        return self._stream_router.route_for(symbol)

    # ---------------------------------------------------------- public status
    def current_paper_only_status(
        self,
        *,
        last_arbitration: Optional[ArbitrationResult] = None,
        last_deconflict: Optional[DeconflictResult] = None,
    ) -> Dict[str, Any]:
        """Build the operator-runtime public status payload."""
        winners_payload: List[Dict[str, Any]] = []
        considered_count = 0
        stale_ids: List[str] = []
        if last_arbitration is not None:
            considered_count = int(last_arbitration.considered_count)
            stale_ids = list(last_arbitration.stale_proposal_ids)
            for bucket in last_arbitration.bucket_winners:
                winners_payload.append(
                    {
                        "symbol": bucket.symbol,
                        "side": bucket.side,
                        "winner_proposal_id": bucket.winner.proposal_id,
                        "score": float(bucket.score),
                        "winner_confidence_calibrated": float(
                            bucket.winner.confidence_calibrated
                        ),
                        "winner_expected_move_after_cost_bps": float(
                            bucket.winner.expected_move_after_cost_bps
                        ),
                        "winner_freshness_seconds": float(
                            bucket.winner.freshness_seconds
                        ),
                        "winner_model_version": bucket.winner.model_version,
                        "considered_proposal_ids": list(
                            bucket.considered_proposal_ids
                        ),
                    }
                )

        if last_deconflict is None:
            deconflict_payload: Mapping[str, Any] = {
                "selected_side": None,
                "selected_signal_id": None,
                "conflict_reason": DECONFLICT_REASON_EMPTY,
                "long_aggregate_confidence": 0.0,
                "short_aggregate_confidence": 0.0,
                "considered_count": 0,
            }
        else:
            selected_id = (
                last_deconflict.selected_signal.signal_id
                if last_deconflict.selected_signal is not None
                else None
            )
            deconflict_payload = {
                "selected_side": last_deconflict.selected_side,
                "selected_signal_id": selected_id,
                "conflict_reason": last_deconflict.conflict_reason,
                "long_aggregate_confidence": float(
                    last_deconflict.long_aggregate_confidence
                ),
                "short_aggregate_confidence": float(
                    last_deconflict.short_aggregate_confidence
                ),
                "considered_count": int(last_deconflict.considered_count),
            }

        return {
            "service_id": SERVICE_ID,
            "live_gate": LIVE_GATE_STATUS,
            "current_gate_state": LIVE_GATE_STATUS,
            "live_symbols": [],
            "live_blocked": True,
            "approves_live": False,
            "cannot_bypass_risk_gateway": True,
            "orchestrator_overrides_risk": False,
            "risk_gateway_binding": RISK_GATEWAY_BINDING,
            "max_age_seconds": int(self._max_age_seconds),
            "stream_label_allowed": list(STREAM_LABEL_ALLOWED),
            "stream_default_label": STREAM_LABEL_SHADOW,
            "stream_routing_snapshot": self._stream_router.mapping_snapshot(),
            "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
            "legacy_sha256_index": dict(LEGACY_SHA256_INDEX),
            "components_ported": list(COMPONENTS_PORTED),
            "components_missing_in_v2": list(COMPONENTS_MISSING_IN_V2),
            "fail_closed_invariants": {
                "missing_evidence_returns_MISSING_EVIDENCE_CANNOT_COMPARE": True,
                "stale_proposals_scored_minus_infinity": True,
                "invalid_signals_rejected_with_explicit_reason": True,
            },
            "arbitration_bucket_winners": winners_payload,
            "arbitration_considered_count": considered_count,
            "arbitration_stale_proposal_ids": stale_ids,
            "deconflict": dict(deconflict_payload),
            "missing_evidence_reason": DECONFLICT_REASON_MISSING_EVIDENCE,
            "subproject": "4_orchestrator_arbitration",
        }
