from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli import v2_audit_2026_06_19_runtime_validator as validator


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.writes: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get(self, key: str) -> str | None:
        if key not in self.payloads:
            return None
        return json.dumps(self.payloads[key])

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        keys = list(self.payloads)
        if match is None:
            yield from keys
            return
        prefix = match[:-1] if match.endswith("*") else match
        for key in keys:
            if match.endswith("*"):
                if key.startswith(prefix):
                    yield key
            elif key == match:
                yield key

    def set(self, *args: Any, **kwargs: Any) -> None:
        self.writes.append(("set", args, kwargs))
        raise AssertionError("runtime audit validator must be read-only")


def _closed_row(index: int, *, side: str, mode: str, timeframe: str = "1m") -> dict[str, Any]:
    pnl = 1.5 if index % 3 else -0.4
    return {
        "close_id": f"close_{index}",
        "symbol": f"SYM{index % 12}USDT",
        "timeframe": timeframe,
        "side": side,
        "close_reason": "TIER_2_TRAILING_STOP" if index < 40 else "TIER_3_TAKE_PROFIT",
        "realized_pnl_usd": pnl,
        "realized_pnl_bps": 12.0 if pnl > 0 else -4.0,
        "strategy_selected_mode": mode,
        "drawdown_at_entry": float(index % 7) * 3.0,
        "squeeze_evidence_score": 0.15 + (index % 5) * 0.1,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "actual_observed_spread_entry_bps": 1.0 + (index % 4),
        "actual_observed_spread_exit_bps": 1.5 + (index % 5),
        "expected_slippage_bps": 0.8 + (index % 3) * 0.2,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "realized_slippage_bps": 1.0 + (index % 4) * 0.1,
        "implementation_shortfall_usd": 0.01 * (index % 3),
        "mfe_bps": 25.0 + index % 20,
        "mae_bps": 5.0 + index % 10,
        "intra_trade_high_price": 101.0 + index,
        "intra_trade_low_price": 99.0 + index,
        "trailing_stop_history": [{"trailing_stop_price": 100.0 + index}] if index < 40 else [],
    }


def _passing_payloads() -> dict[str, Any]:
    rows = []
    for index in range(320):
        side = "long" if index < 160 else "short"
        mode = "trend_mode" if index % 3 == 0 else "mean_reversion_mode"
        timeframe = "1m" if index % 2 == 0 else "15m"
        rows.append(_closed_row(index, side=side, mode=mode, timeframe=timeframe))
    realized = sum(float(row["realized_pnl_usd"]) for row in rows)
    return {
        "v2:live_gate:state": {"live_gate": "blocked_human_only"},
        "v2:paper:closed_trades": rows,
        "v2:portfolio:state": {
            "realized_pnl_usd": realized,
            "equity": 10000.0 + realized,
            "current_drawdown_bps": 12.0,
        },
        "v2:paper:outcome_memory:BTCUSDT:1m": {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "trade_count": 25,
            "degraded": True,
            "block_reason": "WIN_RATE_DEGRADED:20.00%<35.00%",
            "data_source": "REDIS",
        },
    }


def test_runtime_validator_passes_complete_current_evidence_without_redis_writes() -> None:
    fake = FakeRedis(_passing_payloads())

    report = validator.build_report(fake, generated_utc="2026-06-19T01:30:00Z")

    assert report["overall_status"] == validator.PASSED
    assert report["read_only"] is True
    assert report["writes_redis"] is False
    assert report["places_real_order"] is False
    assert report["live_gate"] == "blocked_human_only"
    assert report["remaining_blockers"] == []
    assert all(row["status"] == validator.PASSED for row in report["findings"].values())
    assert report["findings"]["F01"]["metrics"]["long_count"] >= 50
    assert report["findings"]["F05"]["metrics"]["all_static_2bps"] is False
    assert fake.writes == []


def test_runtime_validator_keeps_no_go_for_short_only_static_cost_old_evidence() -> None:
    rows = [
        {
            "close_id": f"old_{index}",
            "symbol": "BTCUSDT",
            "timeframe": "5m" if index % 2 else "4h",
            "side": "short",
            "strategy_selected_mode": "trend_mode",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "realized_pnl_bps": -10.0,
            "drawdown_at_entry": 0.0,
            "microstructure_context": {"bid_ask_spread_bps": 2.0},
        }
        for index in range(60)
    ]
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": 0.0},
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T01:30:00Z")

    assert report["overall_status"] == validator.NO_GO
    assert report["findings"]["F01"]["status"] == validator.FAILED
    assert report["findings"]["F03"]["status"] == validator.FAILED
    assert report["findings"]["F04"]["status"] == validator.FAILED
    assert report["findings"]["F05"]["status"] == validator.FAILED
    assert report["findings"]["F06"]["status"] == validator.FAILED
    assert report["findings"]["F07"]["status"] == validator.FAILED
    assert report["findings"]["F11"]["status"] == validator.FAILED
    assert report["findings"]["F13"]["status"] == validator.FAILED
    assert "F01" in report["remaining_blockers"]
    assert fake.writes == []


def test_f02_uses_active_policy_trailing_cohort_after_exit_policy_patch() -> None:
    legacy_trailing_losses = []
    for index in range(60):
        row = _closed_row(index, side="short", mode="trend_mode", timeframe="5m")
        row["close_reason"] = "TIER_2_TRAILING_STOP"
        row["realized_pnl_usd"] = -1.0
        row["realized_pnl_bps"] = -10.0
        legacy_trailing_losses.append(row)

    active_policy_rows = []
    for index in range(220):
        row = _closed_row(
            1000 + index,
            side="long" if index % 2 == 0 else "short",
            mode="mean_reversion_mode" if index % 3 else "reduce_size_mode",
            timeframe="1m" if index % 2 == 0 else "15m",
        )
        row["paper_exit_policy_version"] = validator.PAPER_EXIT_POLICY_VERSION
        if index < 60:
            row["close_reason"] = "TIER_2_TRAILING_STOP"
            if index < 40:
                row["realized_pnl_usd"] = 1.0
                row["realized_pnl_bps"] = 20.0
            else:
                row["realized_pnl_usd"] = -0.25
                row["realized_pnl_bps"] = -5.0
        else:
            row["close_reason"] = "TIER_2_TAKE_PROFIT"
            row["realized_pnl_usd"] = 0.25
            row["realized_pnl_bps"] = 5.0
        active_policy_rows.append(row)

    rows = legacy_trailing_losses + active_policy_rows
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": sum(float(row["realized_pnl_usd"]) for row in rows)},
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T02:00:00Z")

    f02 = report["findings"]["F02"]
    assert f02["status"] == validator.PASSED
    assert f02["blockers"] == []
    assert f02["metrics"]["historical_trailing_stop_count"] == 120
    assert f02["metrics"]["historical_trailing_stop_pnl_usd"] < 0.0
    assert f02["metrics"]["active_policy_version"] == validator.PAPER_EXIT_POLICY_VERSION
    assert f02["metrics"]["active_policy_closed_trade_count"] == 220
    assert f02["metrics"]["active_policy_trailing_stop_count"] == 60
    assert f02["metrics"]["active_policy_trailing_stop_win_rate"] == 40 / 60
    assert f02["metrics"]["active_policy_trailing_stop_pnl_usd"] > 0.0
    assert fake.writes == []


def test_f02_keeps_no_go_until_active_policy_sample_is_large_enough() -> None:
    legacy_trailing_losses = []
    for index in range(60):
        row = _closed_row(index, side="short", mode="trend_mode", timeframe="5m")
        row["close_reason"] = "TIER_2_TRAILING_STOP"
        row["realized_pnl_usd"] = -1.0
        row["realized_pnl_bps"] = -10.0
        legacy_trailing_losses.append(row)

    active_policy_rows = []
    for index in range(13):
        row = _closed_row(
            2000 + index,
            side="long",
            mode="reduce_size_mode",
            timeframe="1m",
        )
        row["paper_exit_policy_version"] = validator.PAPER_EXIT_POLICY_VERSION
        row["close_reason"] = "TIER_1_ATR_VOLATILITY_STOP"
        row["realized_pnl_usd"] = -0.1
        row["realized_pnl_bps"] = -3.0
        active_policy_rows.append(row)

    rows = legacy_trailing_losses + active_policy_rows
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": sum(float(row["realized_pnl_usd"]) for row in rows)},
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T02:05:00Z")

    f02 = report["findings"]["F02"]
    assert f02["status"] == validator.INSUFFICIENT
    assert f02["metrics"]["historical_trailing_stop_count"] == 60
    assert f02["metrics"]["active_policy_closed_trade_count"] == 13
    assert f02["metrics"]["active_policy_trailing_stop_count"] == 0
    assert "POST_POLICY_CLOSED_TRADE_SAMPLE_BELOW_MINIMUM" in f02["blockers"]
    assert "POST_POLICY_TRAILING_STOP_SAMPLE_BELOW_MINIMUM" in f02["blockers"]
    assert "F02" in report["remaining_blockers"]
    assert fake.writes == []


def test_f09_uses_active_policy_strategy_mode_cohort_when_present() -> None:
    legacy_trend_rows = []
    for index in range(300):
        row = _closed_row(index, side="short", mode="trend_mode", timeframe="5m")
        row["close_reason"] = "TIER_2_TAKE_PROFIT"
        row["realized_pnl_usd"] = 0.1
        legacy_trend_rows.append(row)

    active_policy_rows = []
    for index in range(60):
        mode = "reduce_size_mode" if index % 2 == 0 else "mean_reversion_mode"
        row = _closed_row(
            3000 + index,
            side="long" if index % 2 == 0 else "short",
            mode=mode,
            timeframe="1m",
        )
        row["paper_exit_policy_version"] = validator.PAPER_EXIT_POLICY_VERSION
        row["close_reason"] = "TIER_2_TAKE_PROFIT"
        row["realized_pnl_usd"] = 0.1
        active_policy_rows.append(row)

    rows = legacy_trend_rows + active_policy_rows
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": sum(float(row["realized_pnl_usd"]) for row in rows)},
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T02:10:00Z")

    f09 = report["findings"]["F09"]
    assert f09["status"] == validator.PASSED
    assert f09["blockers"] == []
    assert f09["metrics"]["strategy_mode_evidence_scope"] == "active_policy"
    assert f09["metrics"]["closed_trade_count"] == 60
    assert f09["metrics"]["active_policy_closed_trade_count"] == 60
    assert f09["metrics"]["strategy_mode_counts"] == {
        "mean_reversion_mode": 30,
        "reduce_size_mode": 30,
    }
    assert f09["metrics"]["historical_strategy_mode_counts"]["trend_mode"] == 300
    assert fake.writes == []


def test_f09_requires_minimum_active_policy_strategy_mode_sample() -> None:
    legacy_trend_rows = []
    for index in range(300):
        row = _closed_row(index, side="short", mode="trend_mode", timeframe="5m")
        row["close_reason"] = "TIER_2_TAKE_PROFIT"
        row["realized_pnl_usd"] = 0.1
        legacy_trend_rows.append(row)

    active_policy_rows = []
    for index in range(12):
        row = _closed_row(
            4000 + index,
            side="long",
            mode="reduce_size_mode",
            timeframe="1m",
        )
        row["paper_exit_policy_version"] = validator.PAPER_EXIT_POLICY_VERSION
        row["close_reason"] = "TIER_2_TAKE_PROFIT"
        row["realized_pnl_usd"] = 0.1
        active_policy_rows.append(row)

    rows = legacy_trend_rows + active_policy_rows
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": sum(float(row["realized_pnl_usd"]) for row in rows)},
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T02:11:00Z")

    f09 = report["findings"]["F09"]
    assert f09["status"] == validator.INSUFFICIENT
    assert "POST_POLICY_STRATEGY_MODE_SAMPLE_BELOW_MINIMUM" in f09["blockers"]
    assert f09["metrics"]["strategy_mode_evidence_scope"] == "active_policy"
    assert f09["metrics"]["closed_trade_count"] == 12
    assert f09["metrics"]["minimum_closed_trades"] == validator.F09_ACTIVE_POLICY_MIN_CLOSED_TRADES
    assert "F09" in report["remaining_blockers"]
    assert fake.writes == []


def test_f07_passes_when_negative_timeframe_has_active_aggregate_quarantine() -> None:
    rows = [
        {
            "close_id": f"tf_loss_{index}",
            "symbol": f"SYM{index % 4}USDT",
            "timeframe": "5m",
            "side": "short",
            "strategy_selected_mode": "trend_mode",
            "realized_pnl_usd": -1.0,
            "realized_pnl_bps": -10.0,
            "drawdown_at_entry": float(index % 3),
            "actual_observed_spread_entry_bps": 1.0 + (index % 2),
        }
        for index in range(40)
    ]
    fake = FakeRedis(
        {
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:closed_trades": rows,
            "v2:portfolio:state": {"realized_pnl_usd": -40.0},
            "v2:paper:outcome_memory:__ALL__:5m": {
                "symbol": "__ALL__",
                "timeframe": "5m",
                "trade_count": 40,
                "rolling_win_rate": 0.0,
                "drawdown_contribution_usd": -40.0,
                "degraded": True,
                "block_reason": "WIN_RATE_DEGRADED:0.00%<35.00%",
                "data_source": "REDIS",
            },
        }
    )

    report = validator.build_report(fake, generated_utc="2026-06-19T01:45:00Z")

    assert report["findings"]["F07"]["status"] == validator.PASSED
    assert report["findings"]["F07"]["metrics"]["negative_timeframes_with_min_20_trades"] == ["5m"]
    assert report["findings"]["F07"]["metrics"]["unquarantined_negative_timeframes"] == []
    assert report["findings"]["F10"]["status"] == validator.PASSED
    assert fake.writes == []
