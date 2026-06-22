"""Unit tests for the paper-only symbol concentration guard."""
from __future__ import annotations

from v2.backend.app.services.paper_guards.symbol_concentration_guard import (
    ALLOW,
    BLOCK,
    BLOCK_REASON_BELOW_DIVERSITY,
    BLOCK_REASON_OVERCONCENTRATED,
    DEFAULT_MAX_RECENT_INTENT_SHARE_PER_SYMBOL,
    DEFAULT_MIN_SYMBOL_DIVERSITY,
    DOWNRANK,
    DOWNRANK_REASON_CONCENTRATED,
    compute_share,
    evaluate,
    replay_miner_feed,
)


def test_compute_share_returns_zero_when_distribution_empty() -> None:
    assert compute_share({}, "BTCUSDT") == (0.0, 0)
    assert compute_share(None, "BTCUSDT") == (0.0, 0)


def test_compute_share_normalises_uppercase_and_total() -> None:
    share, total = compute_share({"btcusdt": 90, "ETHUSDT": 10}, "btcusdt")
    assert total == 100
    assert share == 0.9


def test_evaluate_allows_when_well_below_thresholds() -> None:
    d = evaluate({"BTCUSDT": 1, "ETHUSDT": 4, "SOLUSDT": 5}, "BTCUSDT")
    assert d.decision == ALLOW
    assert d.reason is None


def test_evaluate_downranks_at_concentrated_band() -> None:
    d = evaluate(
        {"BTCUSDT": 4, "ETHUSDT": 3, "SOLUSDT": 3}, "BTCUSDT",
    )
    # share = 0.4 → DOWNRANK band
    assert d.decision == DOWNRANK
    assert d.reason == DOWNRANK_REASON_CONCENTRATED


def test_evaluate_blocks_when_distribution_one_symbol_and_target_is_that_symbol() -> None:
    d = evaluate(
        {"1000BONKUSDT": 109}, "1000BONKUSDT",
    )
    assert d.decision == BLOCK
    assert d.reason == BLOCK_REASON_BELOW_DIVERSITY


def test_evaluate_blocks_when_distinct_below_min_diversity_for_existing_symbol() -> None:
    d = evaluate({"BTCUSDT": 90, "ETHUSDT": 10}, "BTCUSDT", min_diversity=3)
    assert d.decision == BLOCK
    assert d.reason == BLOCK_REASON_BELOW_DIVERSITY


def test_evaluate_allows_new_symbol_when_below_min_diversity() -> None:
    # Window has only 1 distinct symbol; a new symbol candidate should
    # be allowed because admitting it lifts diversity.
    d = evaluate({"1000BONKUSDT": 109}, "BTCUSDT", min_diversity=3)
    assert d.decision == ALLOW


def test_evaluate_blocks_overconcentrated_above_max_share() -> None:
    distribution = {f"SYM{i}": 1 for i in range(10)}
    distribution["DOMUSDT"] = 100
    d = evaluate(distribution, "DOMUSDT", max_share=0.60)
    assert d.decision == BLOCK
    assert d.reason == BLOCK_REASON_OVERCONCENTRATED


def test_replay_miner_feed_carries_live_safety_envelope() -> None:
    d1 = evaluate(
        {"1000BONKUSDT": 109, "BTCUSDT": 0, "ETHUSDT": 0, "SOLUSDT": 0},
        "1000BONKUSDT",
    )
    out = replay_miner_feed([d1])
    assert len(out) == 1
    row = out[0]
    assert row["decision"] in (BLOCK, DOWNRANK, ALLOW)
    safety = row["live_safety"]
    assert safety["live_gate_status"] == "blocked_human_only"
    assert safety["live_symbols"] == []
    assert safety["exchange_action_taken"] is False
    assert safety["old_redis_writes"] is False


def test_defaults_are_what_we_publish() -> None:
    assert DEFAULT_MAX_RECENT_INTENT_SHARE_PER_SYMBOL == 0.60
    assert DEFAULT_MIN_SYMBOL_DIVERSITY == 3


def test_guard_module_does_not_import_redis_or_ccxt() -> None:
    src = open(
        "v2/backend/app/services/paper_guards/symbol_concentration_guard.py"
    ).read()
    # The guard is a pure deterministic evaluator. It must never reach
    # out to Redis or any exchange SDK; that responsibility belongs to
    # callers. We assert by the absence of import-level coupling.
    for forbidden_import in ("import redis", "from redis", "import ccxt", "from ccxt"):
        assert forbidden_import not in src
