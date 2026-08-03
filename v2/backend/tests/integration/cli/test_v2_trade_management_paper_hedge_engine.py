"""V2 native adaptive hedge paper engine tests."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def _long_position(**overrides) -> "object":
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        HedgePositionInputs,
    )

    base = dict(
        symbol="BTCUSDT",
        side="long",
        notional_usd=10000.0,
        unrealized_pnl_bps=-50.0,
        age_seconds=600,
        drawdown_bps_abs=50.0,
    )
    base.update(overrides)
    return HedgePositionInputs(**base)


def test_hedge_fail_closed_when_operator_not_approved() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(_long_position(drawdown_bps_abs=200.0))
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_FAIL_CLOSED_OPERATOR_NOT_APPROVED"
    assert res.operator_paper_hedge_engine_approved is False


def test_hedge_fail_closed_when_inputs_missing() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        HedgePositionInputs,
        evaluate_hedge,
    )

    bad = HedgePositionInputs(
        symbol="",
        side="long",
        notional_usd=-1.0,
        unrealized_pnl_bps=0.0,
        age_seconds=-1,
        drawdown_bps_abs=300.0,
    )
    res = evaluate_hedge(bad, operator_paper_hedge_engine_approved=True)
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_FAIL_CLOSED_MISSING_INPUTS"
    assert res.hedge_fail_closed_when_missing_inputs is True


def test_hedge_fail_closed_when_live_posture_leak() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    leaked = _long_position(live_gate="allowed", live_symbols=("BTCUSDT",))
    res = evaluate_hedge(leaked, operator_paper_hedge_engine_approved=True)
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_FAIL_CLOSED_LIVE_POSTURE_LEAK"


def test_hedge_not_needed_when_flat() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(side="flat", notional_usd=0.0),
        operator_paper_hedge_engine_approved=True,
    )
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_NOT_NEEDED_FLAT_POSITION"


def test_hedge_not_needed_when_min_age_not_met() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(age_seconds=5, drawdown_bps_abs=300.0),
        operator_paper_hedge_engine_approved=True,
        min_open_age_seconds=60,
    )
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_NOT_NEEDED_MIN_AGE_NOT_MET"


def test_hedge_not_needed_when_below_trigger() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(drawdown_bps_abs=50.0),
        operator_paper_hedge_engine_approved=True,
        drawdown_bps_trigger=100.0,
    )
    assert res.hedge_needed is False
    assert res.hedge_block_reason == "HEDGE_NOT_NEEDED_BELOW_TRIGGER"


def test_hedge_needed_long_position_proposes_short_hedge() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(drawdown_bps_abs=200.0),
        operator_paper_hedge_engine_approved=True,
        drawdown_bps_trigger=100.0,
        max_hedge_size_ratio=0.6,
        max_budget_ratio=0.6,
    )
    assert res.hedge_needed is True
    assert res.hedge_side == "short"
    assert 0.0 < res.hedge_size_ratio <= 0.6
    assert res.hedge_budget_check.allowed is True
    assert res.hedge_block_reason == "HEDGE_NEEDED_BUDGET_OK"


def test_hedge_needed_short_position_proposes_long_hedge() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(side="short", drawdown_bps_abs=300.0),
        operator_paper_hedge_engine_approved=True,
        drawdown_bps_trigger=100.0,
    )
    assert res.hedge_needed is True
    assert res.hedge_side == "long"


def test_hedge_needed_but_budget_blocks_when_max_ratio_too_low() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        evaluate_hedge,
    )

    res = evaluate_hedge(
        _long_position(drawdown_bps_abs=400.0),
        operator_paper_hedge_engine_approved=True,
        drawdown_bps_trigger=100.0,
        max_hedge_size_ratio=0.6,
        max_budget_ratio=0.05,
    )
    assert res.hedge_needed is True
    assert res.hedge_budget_check.allowed is False
    assert res.hedge_block_reason == "HEDGE_NEEDED_BUDGET_BLOCKED"


def test_hedge_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        hedge_engine_invariants_snapshot,
    )

    s = hedge_engine_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["places_exchange_orders"] is False
    assert s["writes_legacy_redis"] is False
    assert s["default_paper_hedge_engine_operator_approved"] is False


def test_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/trade_management_paper/hedge_engine.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
        "import requests",
    ):
        assert forbidden not in text, f"hedge_engine.py contains forbidden: {forbidden}"
