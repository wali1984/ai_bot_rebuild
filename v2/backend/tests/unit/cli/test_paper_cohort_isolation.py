from __future__ import annotations

from v2.backend.app.cli.v2_trade_management_paper_loop import (
    _paper_performance_circuit_breaker_status as breaker,
)
from v2.backend.app.cli.v2_trade_management_paper_loop import (
    _paper_performance_source_rows,
    _read_active_paper_provisional_cohort,
    _stamp_paper_cohort_metadata,
    _with_paper_session_metadata,
    _with_paper_session_metadata_rows,
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


# ---------------------------------------------------------------------------
# Phase 5: cohort id propagation checkpoint -> prediction -> intent -> ledger ->
# closed-trade, with equality at every stage and no relabeling of history.
# ---------------------------------------------------------------------------
COHORT = {
    "paper_strategy_cohort_id": "paper_provisional:CKPT_x:2026-07-25T20:39:42Z",
    "checkpoint_id": "CKPT_x",
    "paper_cohort_activation_utc": "2026-07-25T20:39:42Z",
    "paper_cohort_initial_equity_usd": 2985.59,
}
CID = COHORT["paper_strategy_cohort_id"]


def test_stamp_sets_cohort_and_safety_anchors():
    pred = {"symbol": "BTCUSDT", "side": "long", "checkpoint_id": "CKPT_x"}
    stamped = _stamp_paper_cohort_metadata(pred, COHORT)
    assert stamped["paper_strategy_cohort_id"] == CID
    assert stamped["paper_cohort_checkpoint_id"] == "CKPT_x"
    assert stamped["live_eligible"] is False
    assert stamped["routes_to_live"] is False
    assert stamped["places_real_order"] is False
    # Original object not mutated (returns a copy).
    assert "paper_strategy_cohort_id" not in pred


def test_stamp_is_noop_without_cohort():
    row = {"symbol": "BTCUSDT"}
    assert _stamp_paper_cohort_metadata(row, None) is row
    assert _stamp_paper_cohort_metadata(row, {}) is row


def test_stamp_never_relabels_a_different_cohort():
    hist = {"paper_strategy_cohort_id": "paper_provisional:OLD:t", "symbol": "AVAX"}
    out = _stamp_paper_cohort_metadata(hist, COHORT)
    assert out is hist  # historical cohort id preserved, unchanged
    assert out["paper_strategy_cohort_id"] == "paper_provisional:OLD:t"


def test_cohort_id_survives_full_chain_with_equality():
    # checkpoint -> prediction (stamped at origin)
    prediction = _stamp_paper_cohort_metadata(
        {"symbol": "BTCUSDT", "side": "long", "checkpoint_id": "CKPT_x",
         "confidence": 0.7},
        COHORT,
    )
    assert prediction["paper_strategy_cohort_id"] == CID
    # prediction -> accepted intent (session metadata add preserves keys)
    intent = _with_paper_session_metadata(
        prediction, paper_session_id="sess1", starting_equity_usd=2985.59
    )
    assert intent["paper_strategy_cohort_id"] == CID
    # accepted intent -> ledger rows (row-wise session metadata)
    ledger = _with_paper_session_metadata_rows(
        [intent], paper_session_id="sess1", starting_equity_usd=2985.59
    )
    assert ledger[0]["paper_strategy_cohort_id"] == CID
    # ledger -> closed trade (fill/close copy of the row) -> cohort breaker reads it
    closed_trade = dict(ledger[0])
    closed_trade.update({"decision": "CLOSED", "realized_pnl_bps": 12.0})
    assert closed_trade["paper_strategy_cohort_id"] == CID
    # The cohort breaker governs this closed trade as ITS own cohort row.
    assert _paper_performance_source_rows([closed_trade], cohort_id=CID) == [closed_trade]
    # Equality across the whole chain.
    stages = [prediction, intent, ledger[0], closed_trade]
    assert {s["paper_strategy_cohort_id"] for s in stages} == {CID}


def test_ordinary_intent_is_not_relabeled_and_keeps_global_breaker():
    ordinary = {"symbol": "ETHUSDT", "side": "short", "checkpoint_id": "OTHER"}
    intent = _with_paper_session_metadata(
        ordinary, paper_session_id="sess1", starting_equity_usd=2985.59
    )
    assert "paper_strategy_cohort_id" not in intent
    # Global breaker still governs ordinary intents (no cohort filter match).
    assert _paper_performance_source_rows([intent], cohort_id=CID) == []


def test_paper_account_epoch_is_stamped_on_every_session_row() -> None:
    rows = _with_paper_session_metadata_rows(
        [{"fill_id": "fill-1"}, {"position_id": "position-1"}],
        paper_session_id="paper_epoch_1",
        starting_equity_usd=3000.0,
        paper_account_epoch=1,
    )

    assert {row["paper_session_id"] for row in rows} == {"paper_epoch_1"}
    assert {row["paper_account_epoch"] for row in rows} == {1}


# ---------------------------------------------------------------------------
# Phase 5-6: active cohort resolver (env override / shared redis record / None).
# ---------------------------------------------------------------------------
class _FakeRedis:
    def __init__(self, store):
        self._store = store

    def get(self, key):
        return self._store.get(key)


def test_resolver_env_override(monkeypatch):
    monkeypatch.setenv("PAPER_PROVISIONAL_ACTIVE_COHORT_ID", CID)
    got = _read_active_paper_provisional_cohort(None)
    assert got is not None and got["paper_strategy_cohort_id"] == CID


def test_resolver_reads_shared_redis_record(monkeypatch):
    monkeypatch.delenv("PAPER_PROVISIONAL_ACTIVE_COHORT_ID", raising=False)
    import json as _json
    fake = _FakeRedis(
        {"v2:paper:provisional_cohort_activation": _json.dumps(COHORT)}
    )
    got = _read_active_paper_provisional_cohort(fake)
    assert got is not None
    assert got["paper_strategy_cohort_id"] == CID
    assert got["checkpoint_id"] == "CKPT_x"


def test_resolver_none_when_absent(monkeypatch):
    monkeypatch.delenv("PAPER_PROVISIONAL_ACTIVE_COHORT_ID", raising=False)
    assert _read_active_paper_provisional_cohort(_FakeRedis({})) is None
    assert _read_active_paper_provisional_cohort(None) is None
