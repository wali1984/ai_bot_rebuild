"""PaperAccountEpochV1 rotation + scoping — the 12 required tests.

Isolated on Redis DB 15 (production is DB 0 and is NEVER touched). Each test
flushes ONLY db 15. Run:
  cd v2/backend && "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" -m pytest tests/test_paper_epoch_rotation.py -q
"""
from __future__ import annotations

import json

import pytest

redis_lib = pytest.importorskip("redis")
from app.services.paper_session import epoch as E  # noqa: E402

TEST_URL = "redis://localhost:6379/15"
OLD = "paper_old_session_TESTONLY"


@pytest.fixture()
def r():
    client = redis_lib.Redis.from_url(TEST_URL, decode_responses=True, socket_timeout=5)
    try:
        client.ping()
    except Exception:
        pytest.skip("redis db15 unavailable")
    assert client.connection_pool.connection_kwargs.get("db") == 15  # guard: never db0
    client.flushdb()
    yield client
    client.flushdb()


def _trades(session_id, n=5):
    return [
        {"close_id": f"c{i}", "symbol": "BTCUSDT", "side": "Long",
         "realized_net_pnl_usd": -1.0, "paper_session_id": session_id}
        for i in range(n)
    ]


def _seed_clean(r, session_id=OLD, trades=None):
    """Seed a state where preflight PASSES."""
    trades = _trades(session_id) if trades is None else trades
    ledger = round(sum(t["realized_net_pnl_usd"] for t in trades), 8)
    r.set(E.LEGACY_SESSION_KEY, json.dumps({"paper_session_id": session_id, "initial_capital": 3000.0, "checkpoint_id": "ckpt-1"}))
    r.set(E.PORTFOLIO_STATE_KEY, json.dumps({
        "starting_equity_usd": 3000.0, "free_margin_usd": 3000.0 + ledger,
        "used_margin_usd": 0.0, "reserved_margin_usd": 0.0, "realized_pnl_usd": ledger,
        "paper_session_id": session_id}))
    r.set(E.GLOBAL_CLOSED_TRADES_KEY, json.dumps(trades))
    r.set(E.GLOBAL_ACCEPTED_FILLS_KEY, json.dumps([]))
    r.set(E.GLOBAL_POSITIONS_KEY, json.dumps([]))
    r.set(E.FILL_PERSISTENCE_TRACE_KEY, json.dumps({
        "proof_store_initialized": True, "proof_store_backfill_complete": True,
        "invalid_admission_quarantined": 0}))
    return trades


# 1 — reset with no positions/reservations: new session starts at exactly $3,000
def test_01_clean_start_3000(r):
    _seed_clean(r)
    assert E.evaluate_preconditions(r)["status"] == "PASS"
    res = E.rotate(r, execute=True)
    assert res["status"] == "ROTATED" and res["state_mutated"] is True
    pf = json.loads(r.get(E.PORTFOLIO_STATE_KEY))
    assert pf["equity_usd"] == 3000.0 and pf["free_margin_usd"] == 3000.0
    assert pf["used_margin_usd"] == 0.0 and pf["reserved_margin_usd"] == 0.0
    assert pf["realized_pnl_usd"] == 0.0 and pf["paper_account_epoch"] == 1


# 2 — historical evidence preserved byte/hash-identical
def test_02_history_byte_identical(r):
    trades = _seed_clean(r)
    before = r.get(E.GLOBAL_CLOSED_TRADES_KEY)
    before_hash = E._sha256(before)
    E.rotate(r, execute=True)
    after = r.get(E.GLOBAL_CLOSED_TRADES_KEY)
    assert after == before and E._sha256(after) == before_hash
    assert json.loads(after) == trades  # not emptied, not rewritten


# 3 — frontend default scope hides old rows
def test_03_current_scope_hides_old(r):
    _seed_clean(r)
    res = E.rotate(r, execute=True)
    new_id = res["new_session_id"]
    all_closed = json.loads(r.get(E.GLOBAL_CLOSED_TRADES_KEY))
    assert E.scope_rows(all_closed, new_id, "current_session") == []
    assert json.loads(r.get(E.epoch_key(1, "closed_trades"))) == []  # epoch view empty


# 4 — archived scope still retrievable
def test_04_archived_scope_retrievable(r):
    trades = _seed_clean(r)
    res = E.rotate(r, execute=True)
    all_closed = json.loads(r.get(E.GLOBAL_CLOSED_TRADES_KEY))
    assert E.scope_rows(all_closed, res["new_session_id"], "archived") == trades


# 5 — training reader: full corpus available via scope=all
def test_05_training_reader_all(r):
    trades = _seed_clean(r)
    res = E.rotate(r, execute=True)
    all_closed = json.loads(r.get(E.GLOBAL_CLOSED_TRADES_KEY))
    assert E.scope_rows(all_closed, res["new_session_id"], "all") == trades


# 6 — governed economic evidence unchanged (global corpus count/hash intact)
def test_06_economic_cohort_unchanged(r):
    _seed_clean(r)
    pre = E.evaluate_preconditions(r)["historical_closed_trade_count"]
    E.rotate(r, execute=True)
    post = E.evaluate_preconditions(r)["historical_closed_trade_count"]
    assert pre == post == 5  # governed readers (scope=all) see identical history


# 7 — open-position precondition blocks; no mutation
def test_07_open_position_blocks(r):
    _seed_clean(r)
    r.set(E.GLOBAL_POSITIONS_KEY, json.dumps([{"symbol": "ETHUSDT", "accepted_fills": ["f1"]}]))
    res = E.rotate(r, execute=True)
    assert res["status"] == "BLOCKED_RESET_PRECONDITION" and res["state_mutated"] is False
    assert json.loads(r.get(E.GLOBAL_POSITIONS_KEY))  # position NOT removed
    assert r.get(E.EPOCH_POINTER_KEY) is None  # no session created


# 8 — uninitialized proof store blocks; no positions removed
def test_08_uninitialized_proof_store_blocks(r):
    _seed_clean(r)
    r.set(E.FILL_PERSISTENCE_TRACE_KEY, json.dumps({"proof_store_initialized": None, "invalid_admission_quarantined": 3}))
    res = E.rotate(r, execute=True)
    assert res["status"] == "BLOCKED_RESET_PRECONDITION" and res["state_mutated"] is False
    assert "proof_store_initialized" in res["failing"]
    assert r.get(E.EPOCH_COUNTER_KEY) is None  # epoch not allocated


# 9 — idempotency: replay does not create a second session
def test_09_idempotent(r):
    _seed_clean(r)
    a = E.rotate(r, execute=True)
    b = E.rotate(r, execute=True)
    assert a["status"] == "ROTATED"
    assert b["status"] == "NOOP_ALREADY_ROTATED" and b["state_mutated"] is False
    assert int(r.get(E.EPOCH_COUNTER_KEY)) == 1  # only one epoch allocated
    assert a["new_session_id"] == b["receipt"]["new_session_id"]


# 10 — accounting: $3000 / 0 / 0 and conservation
def test_10_accounting_conservation(r):
    _seed_clean(r)
    E.rotate(r, execute=True)
    pf = json.loads(r.get(E.PORTFOLIO_STATE_KEY))
    assert pf["wallet_balance_usd"] == pf["equity_usd"] == 3000.0
    assert pf["free_margin_usd"] + pf["used_margin_usd"] == pf["equity_usd"]
    assert pf["reserved_margin_usd"] == 0.0 and pf["unrealized_pnl_usd"] == 0.0


# 11 — session isolation: a new-session fill does not alter archived totals
def test_11_session_isolation(r):
    old_trades = _seed_clean(r)
    res = E.rotate(r, execute=True)
    new_id = res["new_session_id"]
    # simulate a new fill landing in the new session (writer appends to global corpus, tagged)
    corpus = json.loads(r.get(E.GLOBAL_CLOSED_TRADES_KEY))
    corpus.append({"close_id": "new1", "symbol": "SOLUSDT", "realized_net_pnl_usd": 2.0, "paper_session_id": new_id})
    r.set(E.GLOBAL_CLOSED_TRADES_KEY, json.dumps(corpus))
    assert E.scope_rows(corpus, new_id, "archived") == old_trades  # archived totals unchanged
    assert len(E.scope_rows(corpus, new_id, "current_session")) == 1  # only the new fill


# 12 — frontend cache: an old-session row can never appear in the new current view
def test_12_no_stale_current_rows(r):
    _seed_clean(r)
    res = E.rotate(r, execute=True)
    old_row = {"close_id": "x", "paper_session_id": OLD}
    untagged = {"close_id": "y"}  # even untagged rows excluded from current (strict)
    assert E.scope_rows([old_row, untagged], res["new_session_id"], "current_session") == []


# Bonus — dry-run never mutates
def test_13_dry_run_no_mutation(r):
    _seed_clean(r)
    plan = E.rotate(r, execute=False)
    assert plan["status"] == "DRY_RUN_OK" and plan["state_mutated"] is False
    assert r.get(E.EPOCH_POINTER_KEY) is None and r.get(E.EPOCH_COUNTER_KEY) is None
    assert E.GLOBAL_CLOSED_TRADES_KEY not in plan["would_write_keys"]
