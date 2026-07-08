from __future__ import annotations

from v2.backend.app.services.market_structure.advanced_indicator_replay import (
    REQUIRED_REPLAY_CATEGORIES,
    build_default_advanced_indicator_replay_scenarios,
    run_advanced_indicator_replay_scenarios,
)


def test_default_replay_matrix_covers_required_scenarios_without_future_leakage() -> None:
    status = run_advanced_indicator_replay_scenarios(
        build_default_advanced_indicator_replay_scenarios(),
        generated_utc="2026-07-08T12:00:00Z",
    )

    assert status["status"] == "ADVANCED_INDICATOR_REPLAY_READY"
    assert status["missing_categories"] == []
    assert set(REQUIRED_REPLAY_CATEGORIES).issubset(status["covered_categories"])
    assert status["future_leak_failures"] == 0
    assert status["expected_decision_failures"] == 0
    assert status["winning_blind_blocks"] == 0
    assert status["losing_not_prevented"] == 0
    assert status["fvg_standalone_approvals"] == 0
    assert status["all_entry_exit_decisions_replayed"] is True
    assert status["places_real_order"] is False


def test_replay_excludes_future_rows_from_every_scenario() -> None:
    status = run_advanced_indicator_replay_scenarios(
        build_default_advanced_indicator_replay_scenarios()
    )

    assert all(row["future_leakage_pass"] is True for row in status["rows"])
    assert all(row["future_labels_used_as_features"] is False for row in status["rows"])
    assert all(row["payload_timestamp_safe"] is True for row in status["rows"])
    assert any(row["excluded_future_rows"] > 0 for row in status["rows"])


def test_replay_blocks_or_shadows_losing_and_fakeout_scenarios() -> None:
    status = run_advanced_indicator_replay_scenarios(
        build_default_advanced_indicator_replay_scenarios()
    )
    losing = [
        row
        for row in status["rows"]
        if set(row["categories"])
        & {
            "HIGH_CONFIDENCE_LOSSES",
            "ATR_STOP_CLUSTERS",
            "FAKE_BREAKOUTS",
            "FAKE_BREAKDOWNS",
            "LIQUIDITY_SWEEPS",
            "RANGE_CHOP",
        }
    ]

    assert losing
    assert all(row["old_losing_trade_blocked_or_improved"] is True for row in losing)
    assert all(row["decision"] in {"NO_TRADE", "SHADOW_ONLY"} for row in losing)


def test_replay_does_not_blindly_block_winning_major_move_or_fvg_retest() -> None:
    status = run_advanced_indicator_replay_scenarios(
        build_default_advanced_indicator_replay_scenarios()
    )
    winners = [
        row
        for row in status["rows"]
        if set(row["categories"])
        & {"BTC_ETH_SOL_MAJOR_MOVES", "TREND_CONTINUATION", "FVG_RETESTS"}
    ]

    assert winners
    assert all(row["winning_move_not_blindly_blocked"] is True for row in winners)
    assert all(row["decision"] != "NO_TRADE" for row in winners)


def test_replay_keeps_fvg_from_becoming_standalone_approval() -> None:
    status = run_advanced_indicator_replay_scenarios(
        build_default_advanced_indicator_replay_scenarios()
    )
    fvg_rows = [row for row in status["rows"] if "FVG_RETESTS" in row["categories"]]

    assert fvg_rows
    assert all(row["fvg_standalone_allows_trade"] is False for row in fvg_rows)
