from __future__ import annotations

from v2.backend.app.cli.v2_trade_management_paper_loop import (
    _paper_performance_circuit_breaker_status as breaker,
)
from v2.backend.app.cli.v2_trade_management_paper_loop import (
    _paper_performance_source_rows,
)

# Historical July losing cohort: 20 negative paper closes, NO cohort id.
HIST = [
    {"paper_only": True, "realized_pnl_bps": -50.0, "symbol": "X", "side": "long"}
    for _ in range(20)
]


def test_global_breaker_stays_halted_for_historical_cohort():
    g = breaker(HIST)
    assert g["state"] == "HALTED_PERFORMANCE"
    assert g["new_entries_allowed"] is False
    assert g["cohort_id"] is None


def test_fresh_cohort_is_active_and_never_inherits_global_halt():
    cid = "paper_provisional:ckA:2026-07-25T18:00:00Z"
    c = breaker(HIST, cohort_id=cid)
    assert c["state"] == "ACTIVE_INSUFFICIENT_COHORT_SAMPLE"
    assert c["new_entries_allowed"] is True
    assert c["cohort_id"] == cid
    assert c["governed_closed_rows"] == 0  # empty fallback, NOT the 20 global rows
    # Safety anchors preserved on the cohort payload.
    assert c["paper_only"] is True
    assert c["routes_to_live"] is False
    assert c["places_real_order"] is False


def test_source_rows_cohort_filter_excludes_non_cohort_rows():
    assert _paper_performance_source_rows(HIST, cohort_id="ckA") == []
    assert len(_paper_performance_source_rows(HIST)) == 20  # global unchanged


def test_cohort_with_its_own_losing_rows_can_halt_independently():
    cid = "paper_provisional:ckB:t"
    rows = HIST + [
        {"paper_only": True, "realized_pnl_bps": -60.0, "symbol": "Y",
         "side": "long", "paper_strategy_cohort_id": cid}
        for _ in range(12)
    ]
    c = breaker(rows, cohort_id=cid)
    # 12 cohort rows -> rolling detectors can evaluate; governed rows are cohort-only.
    assert c["cohort_id"] == cid
    assert c["governed_closed_rows"] == 12  # only its own rows, not the 20 global
