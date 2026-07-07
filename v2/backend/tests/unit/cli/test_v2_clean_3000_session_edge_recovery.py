from __future__ import annotations

from v2.backend.app.cli import v2_clean_3000_session_edge_recovery as recovery


def test_current_session_rows_exclude_old_and_missing_session_rows() -> None:
    rows = [
        {"paper_session_id": "paper_3000", "realized_pnl_usd": 1.0},
        {"session_id": "old_session", "realized_pnl_usd": 999.0},
        {"realized_pnl_usd": 999.0},
    ]

    current, old, missing = recovery._current_session_rows(rows, "paper_3000")

    assert len(current) == 1
    assert current[0]["realized_pnl_usd"] == 1.0
    assert len(old) == 1
    assert len(missing) == 1


def test_first_populated_alias_rows_does_not_double_count_ledger_aliases() -> None:
    ledger = {
        "accepted": [
            {"fill_id": "fill-1", "paper_session_id": "paper_3000"},
            {"fill_id": "fill-2", "paper_session_id": "paper_3000"},
        ],
        "accepted_intents": [
            {"fill_id": "fill-1", "paper_session_id": "paper_3000"},
            {"fill_id": "fill-2", "paper_session_id": "paper_3000"},
        ],
    }

    rows = recovery._first_populated_alias_rows(  # noqa: SLF001
        ledger,
        keys=("accepted", "accepted_intents"),
    )

    assert [row["fill_id"] for row in rows] == ["fill-1", "fill-2"]


def test_baseline_metadata_ok_allows_current_equity_after_session_pnl() -> None:
    session_id = "paper_3000_final_pre_live_20260705T024432Z"

    assert recovery._baseline_metadata_ok(  # noqa: SLF001
        portfolio={
            "paper_session_id": session_id,
            "starting_equity_usd": 3000.0,
            "equity": 2997.88,
        },
        session={
            "paper_session_id": session_id,
            "starting_equity_usd": 3000.0,
        },
        ledger={
            "paper_session_id": session_id,
            "starting_equity_usd": 3000.0,
            "accepted_count": 54,
            "live_gate": "blocked_human_only",
            "places_real_order": False,
        },
        session_id=session_id,
    ) is True


def test_invalid_admission_source_ids_come_from_entry_gate_blocked_fills() -> None:
    ids = recovery._invalid_admission_source_ids(  # noqa: SLF001
        [
            {
                "fill_id": "fill-blocked",
                "ledger_row_id": "ledger-blocked",
                "prediction_id": "pred-blocked",
                "entry_signal_id": "entry-signal-blocked",
                "entry_gate_block_reasons": [
                    "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:INJUSDT:1h"
                ],
            },
            {
                "fill_id": "fill-valid",
                "prediction_id": "pred-valid",
                "entry_gate_block_reasons": [],
            },
        ]
    )

    assert ids == {
        "entry-signal-blocked",
        "fill-blocked",
        "ledger-blocked",
        "pred-blocked",
    }


def test_accepted_session_counts_prefer_full_fill_state_rows() -> None:
    rows, source = recovery._accepted_rows_for_session_counts(  # noqa: SLF001
        ledger_rows=[{"fill_id": "compact-only"}],
        fill_state_rows=[
            {"fill_id": "full-1"},
            {"fill_id": "full-2"},
        ],
    )

    assert source == "paper_accepted_fills_state"
    assert [row["fill_id"] for row in rows] == ["full-1", "full-2"]


def test_invalid_admission_accepted_rows_are_excluded_from_valid_progress() -> None:
    session_rows = [
        {
            "paper_session_id": "paper_3000",
            "fill_id": "fill-blocked",
            "prediction_id": "pred-blocked",
        },
        {
            "paper_session_id": "paper_3000",
            "fill_id": "fill-valid",
            "prediction_id": "pred-valid",
        },
    ]

    valid, invalid = recovery._split_invalid_admission_rows(  # noqa: SLF001
        session_rows,
        {"fill-blocked", "pred-blocked"},
    )

    assert [row["fill_id"] for row in valid] == ["fill-valid"]
    assert [row["fill_id"] for row in invalid] == ["fill-blocked"]


def test_invalid_admission_closed_rows_are_excluded_by_source_fill_id() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "source_fill_ids": ["fill-blocked"],
            "realized_pnl_usd": -1.0,
        },
        {
            "paper_session_id": "paper_3000",
            "source_fill_ids": ["fill-valid"],
            "realized_pnl_usd": 2.0,
        },
    ]

    valid, invalid = recovery._split_invalid_admission_rows(  # noqa: SLF001
        rows,
        {"fill-blocked"},
    )

    assert [row["source_fill_ids"] for row in valid] == [["fill-valid"]]
    assert [row["source_fill_ids"] for row in invalid] == [["fill-blocked"]]
    assert recovery._performance(valid)["net_pnl_usd"] == 2.0


def test_five_trade_gate_fails_and_requires_halt_on_negative_expectancy() -> None:
    rows = [
        {"paper_session_id": "paper_3000", "realized_pnl_usd": -1.0, "notional": 10.0},
        {"paper_session_id": "paper_3000", "realized_pnl_usd": -1.0, "notional": 10.0},
        {"paper_session_id": "paper_3000", "realized_pnl_usd": 0.5, "notional": 10.0},
        {"paper_session_id": "paper_3000", "realized_pnl_usd": 0.25, "notional": 10.0},
        {"paper_session_id": "paper_3000", "realized_pnl_usd": -0.25, "notional": 10.0},
    ]

    metrics = recovery._performance(rows)
    gate = recovery._gate_payload(
        gate_name="5_trade",
        threshold=5,
        session_id="paper_3000",
        metrics=metrics,
        generated_utc="2026-07-05T00:00:00Z",
    )

    assert gate["status"] == "FAIL_HALT_REQUIRED"
    assert gate["halt_required"] is True
    assert gate["pass_conditions"]["profit_factor_gte_1"] is False
    assert gate["pass_conditions"]["expectancy_positive"] is False


def test_performance_uses_gross_notional_usd_for_weighted_expectancy() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": 1.0,
            "gross_notional_usd": 25.0,
        },
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": -0.25,
            "gross_notional_usd": 75.0,
        },
    ]

    metrics = recovery._performance(rows)

    assert metrics["total_notional_usd"] == 100.0
    assert metrics["notional_weighted_expectancy"] == 0.0075


def test_fifty_trade_gate_fails_when_notional_weighted_expectancy_missing() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": 0.01,
            "gross_notional_usd": 0.0,
        }
        for _ in range(50)
    ]

    metrics = recovery._performance(rows)
    gate = recovery._gate_payload(
        gate_name="50_trade",
        threshold=50,
        session_id="paper_3000",
        metrics=metrics,
        generated_utc="2026-07-05T00:00:00Z",
    )

    assert metrics["notional_weighted_expectancy"] is None
    assert gate["status"] == "FAIL"
    assert gate["pass_conditions"]["notional_weighted_expectancy_positive"] is False


def test_future_gate_blockers_detect_irrecoverable_atr_cluster_before_50() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": -0.25,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
        },
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": -0.15,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
        },
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": 2.0,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_2_TRAILING_STOP",
        },
    ]

    metrics = recovery._performance(rows)
    blockers = recovery._future_gate_blockers(metrics)  # noqa: SLF001

    assert metrics["profit_factor"] > 1.0
    assert metrics["expectancy_usd"] > 0.0
    assert blockers == ["ATR_STOP_CLUSTER_BEFORE_50_TRADE_GATE"]


def test_future_gate_blockers_clear_when_no_irrecoverable_cluster() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": -0.25,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
        },
        {
            "paper_session_id": "paper_3000",
            "realized_pnl_usd": 2.0,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_2_TRAILING_STOP",
        },
    ]

    metrics = recovery._performance(rows)

    assert recovery._future_gate_blockers(metrics) == []  # noqa: SLF001


def test_atr_stop_cluster_diagnostic_captures_blocking_loss_rows() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "symbol": "WLDUSDT",
            "side": "SHORT",
            "timeframe": "1h",
            "strategy_regime": "trend_mode",
            "realized_pnl_usd": -0.25,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
            "entry_atr_bps": 7.1,
            "atr_stop_multiplier_used": 3.0,
        },
        {
            "paper_session_id": "paper_3000",
            "symbol": "INJUSDT",
            "side": "SHORT",
            "timeframe": "1h",
            "strategy_regime": "trend_mode",
            "realized_pnl_usd": -0.15,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
            "entry_atr_bps": 6.3,
            "atr_stop_multiplier_used": 3.0,
        },
        {
            "paper_session_id": "paper_3000",
            "symbol": "CRVUSDT",
            "side": "LONG",
            "realized_pnl_usd": 1.0,
            "gross_notional_usd": 10.0,
            "close_reason": "TIER_2_TRAILING_STOP",
        },
    ]

    metrics = recovery._performance(rows)
    blockers = recovery._future_gate_blockers(metrics)  # noqa: SLF001
    diagnostic = recovery._atr_stop_cluster_diagnostic(  # noqa: SLF001
        rows=rows,
        metrics=metrics,
        session_id="paper_3000",
        generated_utc="2026-07-05T00:00:00Z",
        future_gate_blockers=blockers,
    )

    assert diagnostic["status"] == "BLOCKING_50_TRADE_GATE"
    assert diagnostic["root_cause_classification"] == "CURRENT_SESSION_ATR_STOP_CLUSTER"
    assert diagnostic["paper_new_entries_halted_required"] is True
    assert diagnostic["diagnostic_row_count"] == 2
    assert [row["symbol"] for row in diagnostic["diagnostic_rows"]] == ["WLDUSDT", "INJUSDT"]
    assert diagnostic["diagnostic_rows"][0]["entry_atr_bps"] == 7.1
    assert diagnostic["places_real_order"] is False


def test_three_hundred_gate_requires_long_short_and_20_symbols() -> None:
    rows = [
        {
            "paper_session_id": "paper_3000",
            "symbol": f"SYM{i % 10}USDT",
            "side": "LONG",
            "realized_pnl_usd": 1.0,
            "notional": 10.0,
        }
        for i in range(300)
    ]

    metrics = recovery._performance(rows)
    gate = recovery._gate_payload(
        gate_name="300_trade",
        threshold=300,
        session_id="paper_3000",
        metrics=metrics,
        generated_utc="2026-07-05T00:00:00Z",
    )

    assert gate["status"] == "FAIL"
    assert gate["pass_conditions"]["short_pnl_positive"] is False
    assert gate["pass_conditions"]["at_least_20_symbols"] is False


def test_atr_stop_cluster_recoverable_after_verified_exit_repair(tmp_path, monkeypatch) -> None:
    """Pre-repair ATR-stop losses stop driving the blocking cluster once a
    verified exit-repair artifact exists; new post-repair losses re-block."""
    artifact = tmp_path / "atr_stop_cluster_repair_status.json"
    artifact.write_text(
        '{"repair_test_passed": true, "repair_deployed_utc": "2026-07-06T07:00:00Z"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(recovery, "ATR_EXIT_REPAIR_STATUS_PATH", artifact)

    pre_repair_loss = {
        "paper_session_id": "paper_3000",
        "realized_pnl_usd": -0.25,
        "gross_notional_usd": 10.0,
        "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
        "exit_price_utc": "2026-07-06T01:34:09.533Z",
    }
    rows = [
        dict(pre_repair_loss),
        {**pre_repair_loss, "realized_pnl_usd": -0.15, "exit_price_utc": "2026-07-06T02:01:00.000Z"},
    ]
    metrics = recovery._performance(rows)  # noqa: SLF001
    assert metrics["atr_stop_loss_count"] == 2
    assert metrics["atr_stop_loss_count_post_exit_repair"] == 0
    assert metrics["atr_stop_cluster"] is False
    assert metrics["atr_stop_cluster_pre_repair_losses_excluded"] is True
    assert recovery._future_gate_blockers(metrics) == []  # noqa: SLF001

    # Two NEW post-repair ATR losses re-block the gate.
    rows_post = rows + [
        {**pre_repair_loss, "exit_price_utc": "2026-07-06T08:30:00.000Z"},
        {**pre_repair_loss, "exit_price_utc": "2026-07-06T09:10:00.000Z"},
    ]
    metrics_post = recovery._performance(rows_post)  # noqa: SLF001
    assert metrics_post["atr_stop_loss_count_post_exit_repair"] == 2
    assert metrics_post["atr_stop_cluster"] is True
    assert "ATR_STOP_CLUSTER_BEFORE_50_TRADE_GATE" in recovery._future_gate_blockers(metrics_post)  # noqa: SLF001

    # Missing exit timestamps fail closed (count as post-repair).
    rows_no_ts = [
        {k: v for k, v in pre_repair_loss.items() if k != "exit_price_utc"},
        {k: v for k, v in pre_repair_loss.items() if k != "exit_price_utc"},
    ]
    metrics_no_ts = recovery._performance(rows_no_ts)  # noqa: SLF001
    assert metrics_no_ts["atr_stop_cluster"] is True


def test_atr_stop_cluster_stays_blocking_without_verified_repair_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recovery, "ATR_EXIT_REPAIR_STATUS_PATH", tmp_path / "missing.json")
    loss = {
        "paper_session_id": "paper_3000",
        "realized_pnl_usd": -0.25,
        "gross_notional_usd": 10.0,
        "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
        "exit_price_utc": "2026-07-06T01:34:09.533Z",
    }
    metrics = recovery._performance([dict(loss), dict(loss)])  # noqa: SLF001
    assert metrics["atr_stop_cluster"] is True
    assert metrics["atr_exit_repair_deployed_utc"] is None
