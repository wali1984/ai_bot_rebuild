"""V2 full orchestrator worker logic (paper-only).

Wires the V2 proposal bus + the existing OrchestratorArbitrationService
+ the adaptive hedge engine (Phase 5) + a protection-demand score.

Hard constraints:

- V2 namespace only; no legacy Redis writes
- No exchange mutation
- Hedge overlay fail-closed when not operator-approved
- Live posture (live_gate/live_symbols) must remain
  blocked_human_only / []; if a proposal leaks live state, it is
  rejected

Legacy behavior sources consulted (read-only):

- rl/orchestrator_worker.py
    sha256=a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6
- rl/proposal_bus.py
    sha256=e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d
- rl/tradeplan_orchestrator.py
    sha256=1e4ad19faed9dc3498f15401dc1065f1e1eedb400a662fc7272bed7df12fa4d0
- rl/intent_engine.py
    sha256=7d8d474237f08f3ab1f2775044f6e535c0a3934eb336c757b2cf4443f18b0975
- rl/action_ontology.py
    sha256=961a0e418a723d790d4cc692fe337cdd2e383b0b53963efbdc051c12d6a7b9ce
- rl/hybrid_action_space.py
    sha256=abc7ecf1e655e4a018eeedcb4ad675c7bb35e101d4b5a42d432132243aed6c23
- rl/hedge_action_space.py
    sha256=bf7869acba78d469a53ca101425284477c66a6e011e9ae6613e8d4bee79b3b70
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from v2.backend.app.services.trade_management_paper.hedge_engine import (
    HedgePositionInputs,
    evaluate_hedge,
)

from .proposal import Proposal
from .proposal_bus import V2NativeProposalBus
from .service import (
    ArbitrationResult,
    OrchestratorArbitrationService,
)

FULL_WORKER_SCHEMA_VERSION = "v2_orchestrator_full_worker_logic_v1"

LEGACY_SHA256 = {
    "rl/orchestrator_worker.py": "a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6",
    "rl/proposal_bus.py": "e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d",
    "rl/tradeplan_orchestrator.py": "1e4ad19faed9dc3498f15401dc1065f1e1eedb400a662fc7272bed7df12fa4d0",
    "rl/intent_engine.py": "7d8d474237f08f3ab1f2775044f6e535c0a3934eb336c757b2cf4443f18b0975",
    "rl/action_ontology.py": "961a0e418a723d790d4cc692fe337cdd2e383b0b53963efbdc051c12d6a7b9ce",
    "rl/hybrid_action_space.py": "abc7ecf1e655e4a018eeedcb4ad675c7bb35e101d4b5a42d432132243aed6c23",
    "rl/hedge_action_space.py": "bf7869acba78d469a53ca101425284477c66a6e011e9ae6613e8d4bee79b3b70",
}


@dataclass(frozen=True)
class ProtectionDemandScore:
    score: float
    inputs: dict


def compute_protection_demand_score(
    *,
    open_positions_count: int,
    aggregate_drawdown_bps_abs: float,
    portfolio_exposure_ratio: float,
) -> ProtectionDemandScore:
    """Mirror the legacy tradeplan_orchestrator protection-demand surface.

    Higher score => more pressure to protect the book (e.g. reduce size
    or hedge). Pure-Python, paper-only.
    """
    open_positions_count = max(0, int(open_positions_count))
    drawdown = max(0.0, float(aggregate_drawdown_bps_abs))
    exposure = max(0.0, min(2.0, float(portfolio_exposure_ratio)))
    # Components clamped to [0, 1] and weighted.
    pos_component = min(1.0, open_positions_count / 5.0)
    dd_component = min(1.0, drawdown / 300.0)
    exp_component = min(1.0, exposure / 1.0)
    score = 0.35 * pos_component + 0.4 * dd_component + 0.25 * exp_component
    return ProtectionDemandScore(
        score=float(score),
        inputs={
            "open_positions_count": open_positions_count,
            "aggregate_drawdown_bps_abs": drawdown,
            "portfolio_exposure_ratio": exposure,
        },
    )


@dataclass(frozen=True)
class FullWorkerOutput:
    schema_version: str
    arbitration: ArbitrationResult
    accepted_proposal_ids: tuple[str, ...]
    rejected_proposal_ids: tuple[str, ...]
    rejected_reasons: tuple[str, ...]
    protection_demand: ProtectionDemandScore
    hedge_overlay: dict
    bus_status: dict
    generated_utc: str
    live_gate: str = "blocked_human_only"
    live_symbols: tuple[str, ...] = ()
    approves_live: bool = False


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _proposal_violates_live_posture(p: Proposal) -> bool:
    # Proposal dataclass has no live_* fields, but any non-paper source
    # should have been rejected upstream. Defensive: refuse any proposal
    # whose source name itself encodes live intent.
    src = (p.source or "").lower()
    return "live" in src and "v2_native" not in src


class V2OrchestratorFullWorker:
    """One-shot worker: publish -> drain -> arbitrate -> hedge overlay."""

    def __init__(
        self,
        *,
        max_age_seconds: int = 300,
        operator_paper_hedge_engine_approved: bool = False,
    ) -> None:
        self._bus = V2NativeProposalBus(max_age_seconds=max_age_seconds)
        self._service = OrchestratorArbitrationService(max_age_seconds=max_age_seconds)
        self._hedge_approved = bool(operator_paper_hedge_engine_approved)

    def run(
        self,
        proposals: Iterable[Proposal],
        *,
        hedge_position: Optional[HedgePositionInputs] = None,
        protection_inputs: Optional[dict] = None,
    ) -> FullWorkerOutput:
        accepted_ids: list[str] = []
        rejected_ids: list[str] = []
        rejected_reasons: list[str] = []
        for p in proposals:
            if _proposal_violates_live_posture(p):
                rejected_ids.append(p.proposal_id)
                rejected_reasons.append("LIVE_POSTURE_LEAK")
                continue
            decision = self._bus.publish(p)
            if hasattr(decision, "reason"):
                rejected_ids.append(getattr(decision, "proposal_id", p.proposal_id))
                rejected_reasons.append(getattr(decision, "reason", "REJECTED"))
            else:
                accepted_ids.append(getattr(decision, "proposal_id", p.proposal_id))
        # Drain the bus and arbitrate.
        drained = self._bus.drain()
        arbitration = self._service.arbitrate(drained)
        # Hedge overlay (fail-closed when not operator-approved).
        if hedge_position is None:
            hedge_overlay = {
                "hedge_needed": False,
                "hedge_block_reason": "NO_POSITION_INPUTS_PROVIDED",
                "hedge_fail_closed_when_missing_inputs": True,
                "operator_paper_hedge_engine_approved": self._hedge_approved,
            }
        else:
            ev = evaluate_hedge(
                hedge_position,
                operator_paper_hedge_engine_approved=self._hedge_approved,
            )
            hedge_overlay = {
                "hedge_needed": ev.hedge_needed,
                "hedge_side": ev.hedge_side,
                "hedge_size_ratio": ev.hedge_size_ratio,
                "hedge_budget_check": {
                    "allowed": ev.hedge_budget_check.allowed,
                    "ratio": ev.hedge_budget_check.ratio,
                    "max_ratio": ev.hedge_budget_check.max_ratio,
                },
                "hedge_block_reason": ev.hedge_block_reason,
                "hedge_fail_closed_when_missing_inputs":
                    ev.hedge_fail_closed_when_missing_inputs,
                "operator_paper_hedge_engine_approved": ev.operator_paper_hedge_engine_approved,
            }
        # Protection-demand score.
        pi = protection_inputs or {}
        protection = compute_protection_demand_score(
            open_positions_count=int(pi.get("open_positions_count", 0)),
            aggregate_drawdown_bps_abs=float(pi.get("aggregate_drawdown_bps_abs", 0.0)),
            portfolio_exposure_ratio=float(pi.get("portfolio_exposure_ratio", 0.0)),
        )
        return FullWorkerOutput(
            schema_version=FULL_WORKER_SCHEMA_VERSION,
            arbitration=arbitration,
            accepted_proposal_ids=tuple(accepted_ids),
            rejected_proposal_ids=tuple(rejected_ids),
            rejected_reasons=tuple(rejected_reasons),
            protection_demand=protection,
            hedge_overlay=hedge_overlay,
            bus_status=self._bus.status(),
            generated_utc=_utc_iso(),
        )


def full_worker_invariants_snapshot() -> dict:
    return {
        "schema_version": FULL_WORKER_SCHEMA_VERSION,
        "legacy_sha256": LEGACY_SHA256,
        "imports_torch": False,
        "imports_numpy": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
