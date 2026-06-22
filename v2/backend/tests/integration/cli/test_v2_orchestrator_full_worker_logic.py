"""V2 orchestrator full worker logic tests (paper-only)."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def _make_proposal(**overrides):
    from v2.backend.app.services.orchestrator_arbitration.proposal import Proposal

    base = dict(
        proposal_id="v2_p_001",
        symbol="BTCUSDT",
        side="long",
        confidence_calibrated=0.7,
        expected_move_after_cost_bps=25.0,
        generated_utc="2026-05-16T22:40:00Z",
        source="V2_NATIVE_RL_CORE",
        freshness_seconds=5.0,
        model_version="v2_native_policy_cpu_forward_v1",
    )
    base.update(overrides)
    return Proposal(**base)


def test_proposal_bus_publish_accepts_fresh_proposal() -> None:
    from v2.backend.app.services.orchestrator_arbitration.proposal_bus import (
        V2NativeProposalBus,
    )

    bus = V2NativeProposalBus(max_age_seconds=60)
    res = bus.publish(_make_proposal(freshness_seconds=5.0))
    assert getattr(res, "accepted_at_utc", None) is not None


def test_proposal_bus_rejects_duplicate() -> None:
    from v2.backend.app.services.orchestrator_arbitration.proposal_bus import (
        V2NativeProposalBus,
    )

    bus = V2NativeProposalBus(max_age_seconds=60)
    bus.publish(_make_proposal(proposal_id="dup"))
    res = bus.publish(_make_proposal(proposal_id="dup"))
    assert getattr(res, "reason", "") == "DUPLICATE"


def test_proposal_bus_rejects_stale() -> None:
    from v2.backend.app.services.orchestrator_arbitration.proposal_bus import (
        V2NativeProposalBus,
    )

    bus = V2NativeProposalBus(max_age_seconds=10)
    res = bus.publish(_make_proposal(freshness_seconds=1000.0))
    assert getattr(res, "reason", "") == "STALE"


def test_proposal_bus_status_holds_safety() -> None:
    from v2.backend.app.services.orchestrator_arbitration.proposal_bus import (
        V2NativeProposalBus,
    )

    bus = V2NativeProposalBus()
    s = bus.status()
    assert s["imports_redis"] is False
    assert s["writes_legacy_redis"] is False
    assert s["places_exchange_orders"] is False
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []


def test_full_worker_arbitrates_native_proposal_paper_only() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        V2OrchestratorFullWorker,
    )

    w = V2OrchestratorFullWorker(max_age_seconds=300)
    out = w.run([_make_proposal()])
    assert len(out.accepted_proposal_ids) == 1
    assert len(out.rejected_proposal_ids) == 0
    assert out.live_gate == "blocked_human_only"
    assert out.live_symbols == ()
    assert out.approves_live is False


def test_full_worker_rejects_live_posture_leak_in_source() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        V2OrchestratorFullWorker,
    )

    w = V2OrchestratorFullWorker()
    out = w.run([_make_proposal(source="live_trader_publish")])
    assert len(out.accepted_proposal_ids) == 0
    assert "LIVE_POSTURE_LEAK" in out.rejected_reasons


def test_full_worker_hedge_overlay_fail_closed_when_not_approved() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        V2OrchestratorFullWorker,
    )
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        HedgePositionInputs,
    )

    w = V2OrchestratorFullWorker(operator_paper_hedge_engine_approved=False)
    pos = HedgePositionInputs(
        symbol="BTCUSDT", side="long", notional_usd=10000.0,
        unrealized_pnl_bps=-200.0, age_seconds=600, drawdown_bps_abs=300.0,
    )
    out = w.run([_make_proposal()], hedge_position=pos)
    assert out.hedge_overlay["hedge_needed"] is False
    assert out.hedge_overlay["hedge_block_reason"] == "HEDGE_FAIL_CLOSED_OPERATOR_NOT_APPROVED"


def test_full_worker_hedge_overlay_proposes_when_approved_and_drawdown_high() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        V2OrchestratorFullWorker,
    )
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        HedgePositionInputs,
    )

    w = V2OrchestratorFullWorker(operator_paper_hedge_engine_approved=True)
    pos = HedgePositionInputs(
        symbol="BTCUSDT", side="long", notional_usd=10000.0,
        unrealized_pnl_bps=-200.0, age_seconds=600, drawdown_bps_abs=300.0,
    )
    out = w.run([_make_proposal()], hedge_position=pos)
    assert out.hedge_overlay["hedge_needed"] is True
    assert out.hedge_overlay["hedge_side"] == "short"


def test_protection_demand_score_monotone_in_drawdown() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        compute_protection_demand_score,
    )

    low = compute_protection_demand_score(
        open_positions_count=1, aggregate_drawdown_bps_abs=50.0, portfolio_exposure_ratio=0.5,
    )
    high = compute_protection_demand_score(
        open_positions_count=1, aggregate_drawdown_bps_abs=300.0, portfolio_exposure_ratio=0.5,
    )
    assert high.score > low.score


def test_full_worker_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.orchestrator_arbitration.full_worker_logic import (
        full_worker_invariants_snapshot,
    )

    s = full_worker_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["imports_redis"] is False
    assert s["writes_legacy_redis"] is False
    assert s["places_exchange_orders"] is False


def test_modules_have_no_forbidden_imports() -> None:
    for rel in (
        "v2/backend/app/services/orchestrator_arbitration/proposal_bus.py",
        "v2/backend/app/services/orchestrator_arbitration/full_worker_logic.py",
    ):
        text = (REPO / rel).read_text()
        for forbidden in (
            "import torch", "from torch",
            "import redis", "from redis",
            "import ccxt", "from ccxt",
            "import binance",
            "import requests",
        ):
            assert forbidden not in text, f"{rel} contains forbidden: {forbidden}"
