from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.position_state import PaperNetPosition
from v2.backend.app.services.profit_target_monitor.contracts import MONTHLY_TARGET_NET_USDT
from v2.backend.app.services.profit_target_monitor import service as monitor_service
from v2.backend.app.services.profit_target_monitor.service import ProfitTargetMonitorPaths, build_monitor_payloads, collect_runtime_inputs


def _complete_outcome(*, pnl_usd: float, pnl_bps: float, winner: bool) -> dict:
    return {
        "symbol": "BTCUSDT",
        "exit_time": "2026-06-13T23:10:00Z",
        "realized_pnl_usd": pnl_usd,
        "realized_pnl_bps": pnl_bps,
        "fees": 0.8,
        "slippage": 0.4,
        "winner": winner,
        "strategy_id": "trend_mode",
        "strategy_family": "trend_following",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT" if winner else "TIER_1_STOP_LOSS",
        "hold_time_seconds": 300,
        "drawdown_at_entry": 0.0,
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"source": "test_liquidity"},
        "liquidation_distance_context": {"source": "test_liquidation"},
        "microstructure_context": {"source": "test_microstructure"},
    }


def test_redis_prediction_inventory_separates_current_stale_and_unknown_time_keys() -> None:
    class FakeRedis:
        payloads = {
            "v2:prediction:BTCUSDT:1m": {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "generated_utc": "2026-06-13T23:29:00Z",
            },
            "v2:prediction:AXLUSDT:1m": {
                "symbol": "AXLUSDT",
                "timeframe": "1m",
                "generated_utc": "2026-06-13T22:00:00Z",
            },
            "v2:prediction:ORCAUSDT:1m": {
                "symbol": "ORCAUSDT",
                "timeframe": "1m",
            },
        }

        def scan_iter(self, *, match: str, count: int):  # noqa: ARG002
            return iter(self.payloads)

        def get(self, key: str) -> str:
            return json.dumps(self.payloads[key])

    inventory = monitor_service.redis_prediction_timeframe_inventory(
        FakeRedis(),
        now_utc=datetime(2026, 6, 13, 23, 30, tzinfo=timezone.utc),
        fresh_seconds=900,
    )

    assert inventory["current"] == {"BTCUSDT": ["1m"]}
    assert inventory["stale"] == {"AXLUSDT": ["1m"]}
    assert inventory["unknown_time"] == {"ORCAUSDT": ["1m"]}


def _base_inputs(*, live_margin: float = 0.0) -> dict:
    outcomes = [
        {
            "symbol": "BTCUSDT",
            "exit_time": "2026-06-13T23:10:00Z",
            "realized_pnl_usd": 25.0,
            "realized_pnl_bps": 50.0,
            "fees": 0.8,
            "slippage": 0.4,
            "winner": True,
            "hold_time_seconds": 300,
            "close_reason": "TIER_2_TAKE_PROFIT",
        },
        {
            "symbol": "ETHUSDT",
            "exit_time": "2026-06-13T23:20:00Z",
            "realized_pnl_usd": -10.0,
            "realized_pnl_bps": -20.0,
            "fees": 0.5,
            "slippage": 0.25,
            "winner": False,
            "hold_time_seconds": 200,
            "close_reason": "TIER_1_STOP_LOSS",
        },
    ]
    return {
        "portfolio": {
            "equity": 10_000.0,
            "total_pnl_usd": 15.0,
            "generated_utc": "2026-06-13T23:30:00Z",
        },
        "live_gate": {
            "available_margin": live_margin,
            "wallet_balance": 0.00000001,
            "required_initial_margin": 8.0,
            "live_order_submit_blocker": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
        },
        "trainer": {
            "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
            "cuda_active": True,
            "training_loop_active": True,
            "continuous_training_enabled": True,
            "training_steps_total": 100,
            "training_steps_last_hour": 5,
            "prediction_grid_rows": 2,
            "blocked_prediction_rows": 1,
            "checkpoint_id": "ckpt",
            "paper_current_session_pnl": 15.0,
            "resource_bottleneck_reason": "CURRENT_RUNTIME_TELEMETRY_PUBLISHED",
        },
        "predictions": {
            "prediction_rows": [
                {
                    "symbol": "BTCUSDT",
                    "confidence_calibrated": 0.7,
                    "expected_move_after_cost_bps": 40.0,
                    "paper_fill_allowed": True,
                },
                {
                    "symbol": "ETHUSDT",
                    "confidence_calibrated": 0.55,
                    "expected_move_after_cost_bps": -5.0,
                    "paper_fill_allowed": False,
                },
            ]
        },
        "paper_outcomes": outcomes,
        "trainer_feedback": outcomes,
        "closed_trades": outcomes,
        "positions": [],
        "soak_observations": [
            {"observed_utc": "2026-06-12T23:30:00Z", "paper_equity": 9_900.0, "drawdown_bps": 0.0},
            {"observed_utc": "2026-06-13T23:30:00Z", "paper_equity": 10_000.0, "drawdown_bps": 0.0},
        ],
        "trade_management": {
            "strategy_router_mode_counts": {"trend_mode": 4, "no_trade_mode": 2},
            "strategy_router_regime_counts": {"TREND": 4},
            "intents_accepted": 1,
            "intents_blocked": 2,
        },
        "paper_hedge_netting": {"accidental_hedge_pairs_allowed": False},
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_collect_runtime_inputs_prefers_remediated_12h_soak_evidence(tmp_path: Path, monkeypatch) -> None:
    public = tmp_path / "public"
    monkeypatch.setattr(monitor_service, "connect_redis", lambda: None)
    _write_json(public / monitor_service.SOAK_STATUS_REL, {"gate": "LEGACY_24H"})
    _write_json(public / monitor_service.REMEDIATED_SOAK_STATUS_REL, {"gate": "REMEDIATED_12H"})
    _write_jsonl(
        public / monitor_service.SOAK_OBSERVATIONS_REL,
        [{"observed_utc": "2026-06-13T00:00:00Z", "paper_equity": 1.0}],
    )
    _write_jsonl(
        public / monitor_service.REMEDIATED_SOAK_OBSERVATIONS_REL,
        [{"observed_utc": "2026-06-14T00:00:00Z", "paper_equity": 2.0}],
    )

    inputs = collect_runtime_inputs(ProfitTargetMonitorPaths(repo_root=tmp_path, public_root=public))

    assert inputs["soak_status"]["gate"] == "REMEDIATED_12H"
    assert inputs["soak_observations"] == [{"observed_utc": "2026-06-14T00:00:00Z", "paper_equity": 2.0}]


def test_collect_runtime_inputs_prefers_redis_portfolio_equity(tmp_path: Path, monkeypatch) -> None:
    public = tmp_path / "public"
    _write_json(
        public / monitor_service.PORTFOLIO_REL,
        {
            "equity": 9_999.0,
            "total_pnl_usd": -1.0,
            "generated_utc": "2026-06-14T10:00:00Z",
        },
    )

    def fake_redis_json(_client, key: str, default=None):
        if key == "v2:portfolio:state":
            return {
                "equity": 10_052.25,
                "total_pnl_usd": 52.25,
                "generated_utc": "2026-06-14T11:30:00Z",
            }
        return default if default is not None else {}

    monkeypatch.setattr(monitor_service, "connect_redis", lambda: object())
    monkeypatch.setattr(monitor_service, "redis_json", fake_redis_json)

    inputs = collect_runtime_inputs(ProfitTargetMonitorPaths(repo_root=tmp_path, public_root=public))

    assert inputs["portfolio"]["equity"] == 10_052.25
    assert inputs["portfolio"]["_portfolio_source"] == "redis:v2:portfolio:state"


def test_live_zero_margin_reports_target_not_executable_without_guarantee() -> None:
    payloads = build_monitor_payloads(
        _base_inputs(live_margin=0.0),
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feasibility = payloads["monthly_profit_target_feasibility_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    simulation = payloads["monthly_10k_goal_simulation_status.json"]

    assert dashboard["gate"] == "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_READY"
    assert dashboard["go_no_go_marker"] == "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_READY"
    assert feasibility["monthly_target_net_usdt"] == MONTHLY_TARGET_NET_USDT
    assert feasibility["daily_target_net_usdt"] == round(MONTHLY_TARGET_NET_USDT / 30, 8)
    assert feasibility["hourly_target_net_usdt"] == round(MONTHLY_TARGET_NET_USDT / 720, 8)
    assert feasibility["goal_status"] == "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL"
    assert dashboard["goal_status"] == "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL"
    assert dashboard["goal_feasibility_status"] == "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL"
    assert dashboard["paper_equity_source"] == feasibility["paper_equity_source"]
    assert feasibility["live_target_executable"] is False
    assert feasibility["required_monthly_return_pct"] == 1.0
    assert feasibility["profit_claim_policy"] == "NO_GUARANTEE_EVIDENCE_REQUIRED"
    assert simulation["status"] == simulation["goal_simulation_status"]
    assert simulation["goal_status"] == simulation["goal_simulation_status"]
    report = payloads["V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_REPORT.md"].lower()
    assert "not a guaranteed return" in report
    assert "is guaranteed" not in report


def test_profit_target_drawdown_uses_corrected_soak_window_equity_curve() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["soak_status"] = {
        "density_window_first_observation_utc": "2026-06-14T19:00:00Z",
    }
    inputs["soak_observations"] = [
        {"observed_utc": "2026-06-14T18:00:00Z", "paper_equity": 0.0, "drawdown_bps": 0.0},
        {"observed_utc": "2026-06-14T19:00:00Z", "paper_equity": 10_000.0},
        {"observed_utc": "2026-06-14T20:00:00Z", "paper_equity": 9_900.0},
        {"observed_utc": "2026-06-14T21:00:00Z", "paper_equity": 9_950.0},
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-14T17:30:00-04:00",
        generated_utc="2026-06-14T21:30:00Z",
    )

    feasibility = payloads["monthly_profit_target_feasibility_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert feasibility["paper_24h_pnl"] == -50.0
    assert feasibility["paper_run_rate_monthly_pnl"] == -1500.0
    assert feasibility["max_drawdown"] == 100.0
    assert feasibility["max_drawdown_bps"] == 100.0
    assert feasibility["drawdown_source"] == "paper_equity_curve"
    assert feasibility["drawdown_observation_count"] == 3
    assert feasibility["drawdown_equity_point_count"] == 3
    assert feasibility["drawdown_window_start_utc"] == "2026-06-14T19:00:00Z"
    assert dashboard["paper_24h_pnl"] == -50.0
    assert dashboard["paper_run_rate_monthly_return_pct"] == -0.15
    assert dashboard["max_drawdown_bps"] == 100.0
    assert dashboard["drawdown_source"] == "paper_equity_curve"
    assert dashboard["drawdown_window_start_utc"] == "2026-06-14T19:00:00Z"


def test_adaptive_leverage_margin_monitor_stays_balance_held_without_live_mutation() -> None:
    payloads = build_monitor_payloads(
        _base_inputs(live_margin=0.0),
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    leverage_margin = payloads["adaptive_leverage_margin_selection_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    strategy = payloads["adaptive_strategy_selection_status.json"]
    assert leverage_margin["status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert leverage_margin["selection_status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert leverage_margin["recommended_leverage"] == 1.0
    assert leverage_margin["recommended_margin_mode"] == "ISOLATED_PAPER_SIMULATION"
    assert leverage_margin["paper_recommended_leverage"] == 1.0
    assert leverage_margin["paper_recommended_margin_mode"] == "ISOLATED_PAPER_SIMULATION"
    assert leverage_margin["live_leverage_margin_action_status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert leverage_margin["live_leverage_mutation_allowed"] is False
    assert leverage_margin["live_margin_mode_mutation_allowed"] is False
    assert leverage_margin["no_live_mutation"] is True
    assert "balance-held" in leverage_margin["rationale"]
    assert dashboard["live_leverage_margin_action_status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert dashboard["live_action_status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert dashboard["adaptive_leverage_status"] == "LIVE_READY_BALANCE_HELD_NO_ACTION"
    assert dashboard["adaptive_leverage"] == 1.0
    assert dashboard["adaptive_margin_mode"] == "ISOLATED_PAPER_SIMULATION"
    assert dashboard["live_required_min_order_margin"] == leverage_margin["live_required_min_order_margin"]
    assert dashboard["adaptive_leverage_evidence_quality"] == leverage_margin["evidence_quality"]
    assert dashboard["risk_envelope_can_veto_allocator_output"] is True
    assert dashboard["risk_envelope_veto_reason"] == "live available margin is below required minimum order margin"
    assert strategy["strategy_selection_status"] == "DYNAMIC_STRATEGY_SELECTION_MONITORED"
    assert dashboard["strategy_selection_status"] == "DYNAMIC_STRATEGY_SELECTION_MONITORED"


def test_adaptive_leverage_margin_monitor_recommends_higher_paper_leverage_from_evidence() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["predictions"] = {
        "prediction_rows": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "confidence_calibrated": 0.82,
                "expected_move_after_cost_bps": 45.0,
                "paper_fill_allowed": True,
                "volatility_bps": 40.0,
                "liquidity_score": 0.85,
                "effective_spread_bps": 2.0,
                "min_notional_usdt": 5.0,
                "step_size": 0.001,
            },
            {
                "symbol": "ETHUSDT",
                "timeframe": "15m",
                "confidence_calibrated": 0.78,
                "expected_move_after_cost_bps": 35.0,
                "paper_fill_allowed": True,
                "volatility_bps": 45.0,
                "liquidity_score": 0.8,
                "effective_spread_bps": 3.0,
                "min_notional_usdt": 5.0,
                "step_size": 0.001,
            },
        ]
    }
    inputs["paper_outcomes"] = [
        *[_complete_outcome(pnl_usd=10.0, pnl_bps=30.0, winner=True) for _ in range(39)],
        _complete_outcome(pnl_usd=-5.0, pnl_bps=-10.0, winner=False),
    ]
    inputs["trainer_feedback"] = inputs["paper_outcomes"]
    inputs["closed_trades"] = inputs["paper_outcomes"]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    leverage_margin = payloads["adaptive_leverage_margin_selection_status.json"]
    assert leverage_margin["selection_status"] == "ADAPTIVE_LEVERAGE_MARGIN_PAPER_RECOMMENDATION_READY"
    assert leverage_margin["paper_recommended_leverage"] == 3.0
    assert leverage_margin["risk_envelope_can_veto_allocator_output"] is True
    assert leverage_margin["live_leverage_mutation_allowed"] is False
    assert leverage_margin["live_margin_mode_mutation_allowed"] is False
    assert leverage_margin["selection_factors"]["current_win_rate_qualified"] is not None
    assert leverage_margin["selection_factors"]["current_profit_factor_qualified"] is not None
    assert leverage_margin["selection_factors"]["performance_sample_status"] == "QUALIFIED_CLEAN_PERFORMANCE_SAMPLE"
    assert leverage_margin["selection_factors"]["exchange_filter_evidence_present"] is True


def test_monitor_exposes_missing_strategy_hedge_feedback_fields() -> None:
    payloads = build_monitor_payloads(
        _base_inputs(live_margin=20.0),
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feedback = payloads["trainer_strategy_hedge_feedback_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert feedback["status"] == "MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS"
    assert feedback["feedback_status"] == "MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS"
    assert "complete strategy/hedge feedback rows" in feedback["readiness_summary"]
    assert feedback["missing_field_counts"]["strategy_id"] > 0
    assert "trainer feedback missing strategy/hedge/regime fields" in " ".join(
        payloads["operator_dashboard_payload.json"]["blockers"]
    )


def test_incomplete_outcomes_do_not_drive_profit_performance_metrics() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["trainer_feedback"] = []

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feasibility = payloads["monthly_profit_target_feasibility_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    simulation = payloads["monthly_10k_goal_simulation_status.json"]

    assert feasibility["performance_metric_source"] == "INSUFFICIENT_CLEAN_TRAINER_FEEDBACK_OUTCOMES"
    assert feasibility["raw_outcome_count"] == 2
    assert feasibility["performance_outcome_count"] == 0
    assert feasibility["dirty_outcome_count"] == 2
    assert feasibility["current_win_rate"] is None
    assert feasibility["current_win_rate_qualified"] is None
    assert feasibility["current_profit_factor"] is None
    assert feasibility["current_profit_factor_qualified"] is None
    assert feasibility["performance_sample_status"] == "NO_CLEAN_PERFORMANCE_SAMPLE"
    assert feasibility["minimum_qualified_performance_outcomes"] == 30
    assert simulation["win_rate"] is None
    assert simulation["win_rate_qualified"] is None
    assert simulation["profit_factor"] is None
    assert simulation["profit_factor_qualified"] is None
    assert simulation["performance_sample_status"] == "NO_CLEAN_PERFORMANCE_SAMPLE"
    assert dashboard["performance_metric_source"] == "INSUFFICIENT_CLEAN_TRAINER_FEEDBACK_OUTCOMES"
    assert dashboard["performance_outcome_count"] == 0
    assert dashboard["dirty_outcome_count"] == 2
    assert dashboard["current_win_rate_qualified"] is None
    assert dashboard["current_profit_factor_qualified"] is None


def test_small_clean_sample_is_raw_but_not_qualified_performance_evidence() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["paper_outcomes"] = [_complete_outcome(pnl_usd=10.0, pnl_bps=30.0, winner=True)]
    inputs["trainer_feedback"] = inputs["paper_outcomes"]
    inputs["closed_trades"] = inputs["paper_outcomes"]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feasibility = payloads["monthly_profit_target_feasibility_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    simulation = payloads["monthly_10k_goal_simulation_status.json"]
    leverage_margin = payloads["adaptive_leverage_margin_selection_status.json"]

    assert feasibility["performance_outcome_count"] == 1
    assert feasibility["performance_sample_status"] == "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
    assert feasibility["current_win_rate"] == 1.0
    assert feasibility["current_win_rate_qualified"] is None
    assert feasibility["current_profit_factor"] is None
    assert feasibility["current_profit_factor_qualified"] is None
    assert simulation["win_rate"] == 1.0
    assert simulation["win_rate_qualified"] is None
    assert simulation["performance_sample_status"] == "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
    assert dashboard["current_win_rate"] == 1.0
    assert dashboard["current_win_rate_qualified"] is None
    assert dashboard["performance_sample_status"] == "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
    assert leverage_margin["selection_status"] == "ADAPTIVE_LEVERAGE_MARGIN_RECOMMENDATION_INSUFFICIENT_EVIDENCE"
    assert leverage_margin["paper_recommended_leverage"] == 1.0


def test_monitor_distinguishes_consumable_and_quarantined_feedback() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["trainer_feedback"] = []
    inputs["trainer_feedback_quarantine"] = [
        {
            "symbol": "BTCUSDT",
            "exit_time": "2026-06-13T23:10:00Z",
            "realized_pnl_bps": 12.0,
            "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
            "trainer_consumable": False,
            "missing_feedback_fields": ["strategy_id", "market_regime_at_entry"],
        }
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feedback = payloads["trainer_strategy_hedge_feedback_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert feedback["status"] == "MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS"
    assert feedback["trainer_feedback_row_count"] == 0
    assert feedback["trainer_feedback_consumable_row_count"] == 0
    assert feedback["trainer_feedback_quarantined_row_count"] == 1
    assert feedback["trainer_feedback_total_row_count"] == 1
    assert feedback["trainer_consumes_closed_trade_outcomes"] is False
    assert feedback["trainer_feedback_quarantine_active"] is True
    assert feedback["missing_field_counts"]["strategy_id"] == 1
    assert feedback["quarantine_missing_field_counts"]["strategy_id"] == 1
    assert feedback["consumable_missing_field_counts"]["strategy_id"] == 0
    assert feedback["feedback_rows_with_strategy_fields"] == 0
    assert feedback["feedback_rows_with_hedge_fields"] == 0
    assert feedback["missing_strategy_feedback_count"] == 1
    assert feedback["missing_hedge_feedback_count"] == 1
    assert dashboard["trainer_feedback_row_count"] == 0
    assert dashboard["trainer_feedback_consumable_row_count"] == 0
    assert dashboard["trainer_feedback_quarantined_row_count"] == 1
    assert dashboard["trainer_feedback_total_row_count"] == 1
    assert dashboard["trainer_feedback_quarantine_missing_field_counts"]["strategy_id"] == 1
    assert dashboard["trainer_feedback_rows_with_strategy_fields"] == 0
    assert dashboard["trainer_feedback_rows_with_hedge_fields"] == 0
    assert dashboard["trainer_feedback_missing_strategy_feedback_count"] == 1
    assert dashboard["trainer_feedback_missing_hedge_feedback_count"] == 1
    assert "quarantined rows" in dashboard["trainer_feedback_readiness_summary"]


def test_monitor_counts_quarantine_missing_fields_when_consumable_feedback_is_complete() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["trainer_feedback"] = [_complete_outcome(pnl_usd=12.0, pnl_bps=18.0, winner=True)]
    inputs["trainer_feedback_quarantine"] = [
        {
            "symbol": "BTCUSDT",
            "exit_time": "2026-06-13T23:10:00Z",
            "realized_pnl_bps": 12.0,
            "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
            "trainer_consumable": False,
            "missing_feedback_fields": ["strategy_id", "market_regime_at_entry"],
        }
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feedback = payloads["trainer_strategy_hedge_feedback_status.json"]
    assert feedback["status"] == "COMPLETE_FEEDBACK_AVAILABLE_WITH_QUARANTINE"
    assert feedback["trainer_feedback_consumable_row_count"] == 1
    assert feedback["trainer_feedback_quarantined_row_count"] == 1
    assert feedback["consumable_missing_field_counts"]["strategy_id"] == 0
    assert feedback["quarantine_missing_field_counts"]["strategy_id"] == 1
    assert feedback["missing_field_counts"]["strategy_id"] == 1
    assert feedback["feedback_rows_with_strategy_fields"] == 1
    assert feedback["feedback_rows_with_hedge_fields"] == 1
    assert feedback["missing_strategy_feedback_count"] == 1
    assert feedback["missing_hedge_feedback_count"] == 1
    assert "quarantined required fields" in feedback["readiness_summary"]


def test_trainer_capability_treats_below_target_batch_as_active_training_not_dataset_blocker() -> None:
    status = monitor_service.build_trainer_profit_goal_capability_status(
        generated_est="2026-06-14T14:50:00-04:00",
        trainer={
            "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
            "cuda_active": True,
            "training_loop_active": True,
            "training_steps_total": 3608,
            "training_steps_last_hour": 24,
            "prediction_grid_rows": 680,
            "blocked_prediction_rows": 45,
            "resource_bottleneck_reason": "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH",
        },
        predictions=[
            {
                "confidence_calibrated": 0.48,
                "expected_move_after_cost_bps": -35.0,
                "paper_fill_allowed": False,
            }
        ],
        outcomes=[],
        feedback_rows=[],
        closed_trades=[],
        now_utc=datetime(2026, 6, 14, 18, 50, tzinfo=timezone.utc),
    )

    assert status["bottleneck_reason"] == "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH"
    assert status["trainer_capability_status"] == "TRAINER_ACTIVE_BUT_INSUFFICIENT_FEEDBACK"


def test_strategy_and_leverage_payloads_expose_website_aliases() -> None:
    inputs = _base_inputs(live_margin=0.0)

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    strategy = payloads["adaptive_strategy_selection_status.json"]
    assert strategy["status"] == "DYNAMIC_STRATEGY_SELECTION_MONITORED"
    assert strategy["adaptive_strategy_selection_status"] == strategy["strategy_selection_status"]
    assert strategy["strategy_family_count"] == len(monitor_service.STRATEGY_FAMILIES)
    assert len(strategy["families"]) == len(monitor_service.STRATEGY_FAMILIES)
    assert strategy["strategies"] == strategy["families"]
    assert strategy["strategy_families"] == list(monitor_service.STRATEGY_FAMILIES)
    assert "confidence" in strategy["dynamic_selection_inputs"]
    assert strategy["dynamic_strategy_inputs"] == strategy["dynamic_selection_inputs"]
    assert strategy["dynamic_selection_factors"] == strategy["dynamic_selection_inputs"]
    assert "hard_code_strategy_trend" in strategy["not_allowed_static_behavior"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert dashboard["strategy_selection_status"] == strategy["strategy_selection_status"]
    assert dashboard["adaptive_strategy_selection_status"] == strategy["adaptive_strategy_selection_status"]
    assert dashboard["strategy_family_count"] == strategy["strategy_family_count"]
    assert dashboard["dynamic_strategy_inputs"] == strategy["dynamic_strategy_inputs"]
    assert dashboard["dynamic_selection_factors"] == strategy["dynamic_selection_factors"]

    hedge = payloads["adaptive_hedging_capability_status.json"]
    assert hedge["status"] == hedge["hedging_status"]
    assert hedge["adaptive_hedging_capability_status"] == hedge["hedging_status"]
    assert hedge["hedge_status"] == hedge["hedging_status"]
    assert dashboard["adaptive_hedging_capability_status"] == hedge["adaptive_hedging_capability_status"]
    assert dashboard["hedge_status"] == hedge["hedge_status"]
    assert dashboard["accidental_hedge_count"] == hedge["accidental_hedge_count"]

    leverage = payloads["adaptive_leverage_margin_selection_status.json"]
    assert leverage["adaptive_leverage"] == leverage["paper_recommended_leverage"]
    assert leverage["adaptive_margin_mode"] == leverage["paper_recommended_margin_mode"]
    assert leverage["live_available_margin"] == 0.0
    assert leverage["live_target_executable"] is False
    assert leverage["reason"]
    assert leverage["inputs"]["performance_sample_status"]
    assert leverage["risk_envelope"]["can_veto_allocator_output"] is True
    assert leverage["safety"]["live_leverage_mutation_allowed"] is False
    assert leverage["safety"]["live_margin_mode_mutation_allowed"] is False


def test_trainer_capability_exposes_missing_prediction_symbols_and_block_reasons() -> None:
    inputs = _base_inputs(live_margin=0.0)
    inputs["predictions"]["missing_prediction_rows_count"] = 10
    inputs["predictions"]["missing_prediction_symbols"] = ["EIGENUSDT", "KAITOUSDT"]
    inputs["predictions"]["missing_prediction_timeframes_by_symbol"] = {
        "EIGENUSDT": ["1m", "5m", "15m", "1h", "4h"],
        "KAITOUSDT": ["1m", "5m", "15m", "1h", "4h"],
    }
    inputs["predictions"]["stale_prediction_rows_count"] = 1
    inputs["predictions"]["stale_prediction_symbols"] = ["BTCUSDT"]
    inputs["predictions"]["stale_prediction_timeframes_by_symbol"] = {"BTCUSDT": ["1m"]}
    inputs["predictions"]["symbols_covered"] = ["BTCUSDT", "EIGENUSDT", "KAITOUSDT"]
    inputs["predictions"]["paper_actionability_allowed_rows_count"] = 0
    inputs["predictions"]["paper_actionability_blocked_rows_count"] = 2
    inputs["predictions"]["paper_actionability_block_reason_counts"] = {
        "confidence_below_threshold": 2,
    }
    inputs["redis_prediction_timeframes_by_symbol"] = {
        "BTCUSDT": ["1m", "5m", "15m", "1h", "4h"],
    }
    inputs["redis_stale_prediction_timeframes_by_symbol"] = {
        "AXLUSDT": ["1m", "5m", "15m", "1h", "4h"],
    }
    inputs["missing_prediction_input_diagnostics"] = {
        "missing_prediction_input_reason_counts": {
            "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE": 5,
            "MISSING_FEATURE_PAYLOAD": 5,
        },
        "missing_prediction_input_diagnostics_by_symbol": {
            "EIGENUSDT": {
                "missing_prediction_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "missing_closed_candle_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "missing_feature_payload_timeframes": [],
                "likely_root_cause": "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE",
            },
            "KAITOUSDT": {
                "missing_prediction_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "missing_closed_candle_timeframes": [],
                "missing_feature_payload_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "likely_root_cause": "MISSING_FEATURE_PAYLOAD",
            },
        },
    }

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    trainer = payloads["trainer_profit_goal_capability_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert trainer["missing_prediction_rows_count"] == 10
    assert trainer["missing_prediction_symbols"] == ["EIGENUSDT", "KAITOUSDT"]
    assert trainer["missing_prediction_timeframes_by_symbol"]["EIGENUSDT"] == ["1m", "5m", "15m", "1h", "4h"]
    assert trainer["stale_prediction_rows_count"] == 1
    assert trainer["stale_prediction_symbols"] == ["BTCUSDT"]
    assert trainer["paper_actionability_block_reason_counts"] == {"confidence_below_threshold": 2}
    assert trainer["trainer_symbol_universe_alignment_status"] == "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_MISMATCH"
    assert trainer["trainer_prediction_redis_symbol_count"] == 1
    assert trainer["publisher_expected_symbol_count"] == 3
    assert trainer["trainer_expected_missing_from_redis_symbols"] == ["EIGENUSDT", "KAITOUSDT"]
    assert trainer["trainer_redis_extra_prediction_symbols"] == []
    assert trainer["trainer_stale_redis_prediction_symbols"] == ["AXLUSDT"]
    assert trainer["trainer_stale_redis_prediction_timeframes_by_symbol"]["AXLUSDT"] == [
        "1m",
        "5m",
        "15m",
        "1h",
        "4h",
    ]
    assert dashboard["trainer_missing_prediction_rows_count"] == 10
    assert dashboard["trainer_missing_prediction_symbols"] == ["EIGENUSDT", "KAITOUSDT"]
    assert dashboard["trainer_paper_actionability_allowed_rows_count"] == 0
    assert dashboard["trainer_paper_actionability_blocked_rows_count"] == 2
    assert dashboard["trainer_paper_actionability_block_reason_counts"] == {"confidence_below_threshold": 2}
    assert dashboard["trainer_primary_actionability_blocker"] == "confidence_below_threshold"
    assert dashboard["trainer_confidence_distribution"] == trainer["confidence_distribution"]
    assert dashboard["trainer_expected_move_distribution"] == trainer["expected_move_distribution"]
    assert dashboard["trainer_confidence_median"] == trainer["confidence_distribution"]["median"]
    assert dashboard["trainer_confidence_max"] == trainer["confidence_distribution"]["max"]
    assert dashboard["trainer_confidence_high_count"] == trainer["confidence_distribution"]["high_count"]
    assert dashboard["trainer_expected_move_after_cost_median_bps"] == trainer["expected_move_distribution"]["median_bps"]
    assert dashboard["trainer_expected_move_after_cost_max_bps"] == trainer["expected_move_distribution"]["max_bps"]
    assert dashboard["trainer_positive_expected_move_count"] == trainer["expected_move_distribution"]["positive_count"]
    assert dashboard["trainer_symbol_universe_alignment_status"] == "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_MISMATCH"
    assert dashboard["trainer_redis_extra_prediction_symbols"] == []
    assert dashboard["trainer_stale_redis_prediction_symbols"] == ["AXLUSDT"]
    assert trainer["missing_prediction_input_reason_counts"]["MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE"] == 5
    assert trainer["missing_prediction_input_diagnostics_by_symbol"]["EIGENUSDT"]["likely_root_cause"] == (
        "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE"
    )
    assert dashboard["missing_prediction_input_reason_counts"]["MISSING_FEATURE_PAYLOAD"] == 5
    assert dashboard["missing_prediction_input_diagnostics_by_symbol"]["KAITOUSDT"]["likely_root_cause"] == (
        "MISSING_FEATURE_PAYLOAD"
    )


def test_trainer_capability_classifies_extra_current_redis_keys_as_recent_residue() -> None:
    inputs = _base_inputs(live_margin=0.0)
    inputs["predictions"]["symbols_covered"] = ["BTCUSDT", "ETHUSDT"]
    inputs["redis_prediction_timeframes_by_symbol"] = {
        "BTCUSDT": ["1m", "5m", "15m", "1h", "4h"],
        "ETHUSDT": ["1m", "5m", "15m", "1h", "4h"],
        "HMSTRUSDT": ["1m", "5m", "15m", "1h", "4h"],
    }

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    trainer = payloads["trainer_profit_goal_capability_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    assert trainer["trainer_symbol_universe_alignment_status"] == (
        "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_ALIGNED_WITH_RECENT_REDIS_RESIDUE"
    )
    assert trainer["trainer_expected_symbol_mismatch_count"] == 0
    assert trainer["trainer_recent_redis_residue_symbol_count"] == 1
    assert trainer["trainer_recent_redis_residue_symbols"] == ["HMSTRUSDT"]
    assert trainer["trainer_redis_extra_prediction_symbols"] == ["HMSTRUSDT"]
    assert dashboard["trainer_symbol_universe_alignment_status"] == (
        "TRAINER_PUBLISHER_SYMBOL_UNIVERSE_ALIGNED_WITH_RECENT_REDIS_RESIDUE"
    )
    assert dashboard["trainer_expected_symbol_mismatch_count"] == 0
    assert dashboard["trainer_recent_redis_residue_symbol_count"] == 1
    assert dashboard["trainer_recent_redis_residue_symbols"] == ["HMSTRUSDT"]


def test_monitor_uses_remediated_soak_feedback_aggregate_when_rows_are_absent() -> None:
    inputs = _base_inputs(live_margin=0.0)
    inputs["paper_outcomes"] = []
    inputs["trainer_feedback"] = []
    inputs["trainer_feedback_quarantine"] = []
    inputs["soak_status"] = {
        "trainer_feedback_alpha_status": {
            "current_complete_strategy_hedge_feedback_rows": 3,
            "current_quarantined_incomplete_feedback_rows": 110,
            "current_trainer_feedback_total_rows": 113,
            "current_feedback_readiness_status": "COMPLETE_FEEDBACK_AVAILABLE",
            "current_feedback_readiness_summary": "3/3 trainer feedback rows are complete and consumable.",
            "current_feedback_source": "redis:v2:trainer:feedback:outcomes",
            "current_missing_field_counts": {
                "strategy_id": 110,
                "strategy_family": 110,
                "hedge_state": 0,
                "hedge_reason": 0,
                "exit_reason": 0,
                "hold_time_seconds": 0,
                "realized_pnl_bps": 0,
                "market_regime_at_entry": 110,
                "market_regime_at_exit": 110,
                "drawdown_at_entry": 110,
            },
        }
    }

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    dashboard = payloads["operator_dashboard_payload.json"]
    feedback = payloads["trainer_strategy_hedge_feedback_status.json"]
    feasibility = payloads["monthly_profit_target_feasibility_status.json"]

    assert feedback["feedback_status"] == "COMPLETE_FEEDBACK_AVAILABLE_FROM_SOAK_EVIDENCE"
    assert feedback["trainer_feedback_row_count"] == 3
    assert feedback["trainer_feedback_quarantined_row_count"] == 110
    assert feedback["trainer_feedback_total_row_count"] == 113
    assert feedback["feedback_aggregate_evidence_used"] is True
    assert feedback["performance_rows_materialized_for_metrics"] is False
    assert dashboard["feedback_status"] == "COMPLETE_FEEDBACK_AVAILABLE_FROM_SOAK_EVIDENCE"
    assert dashboard["trainer_feedback_row_count"] == 3
    assert dashboard["trainer_feedback_quarantined_row_count"] == 110
    assert dashboard["trainer_feedback_total_row_count"] == 113
    assert dashboard["trainer_feedback_aggregate_evidence_used"] is True
    assert dashboard["trainer_feedback_performance_rows_materialized_for_metrics"] is False
    assert feasibility["performance_sample_status"] == "NO_CLEAN_PERFORMANCE_SAMPLE"
    assert "trainer feedback missing strategy/hedge/regime fields" not in " ".join(dashboard["blockers"])
    assert "realized-PnL feedback rows were not materialized" in " ".join(dashboard["blockers"])


def test_complete_feedback_with_quarantine_is_not_reported_missing() -> None:
    inputs = _base_inputs(live_margin=0.0)
    inputs["trainer_feedback"] = [_complete_outcome(pnl_usd=12.0, pnl_bps=24.0, winner=True)]
    inputs["trainer_feedback_quarantine"] = [
        {
            "symbol": "ETHUSDT",
            "hedge_state": "NO_HEDGE",
            "hedge_reason": "NO_HEDGE_CONTEXT",
            "exit_reason": "LOW_CONFIDENCE_NO_TRADE",
            "hold_time_seconds": 0,
            "realized_pnl_bps": 0.0,
        }
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    dashboard = payloads["operator_dashboard_payload.json"]
    feedback = payloads["trainer_strategy_hedge_feedback_status.json"]

    assert feedback["feedback_status"] == "COMPLETE_FEEDBACK_AVAILABLE_WITH_QUARANTINE"
    assert feedback["trainer_feedback_row_count"] == 1
    assert feedback["trainer_feedback_quarantined_row_count"] == 1
    assert feedback["trainer_feedback_total_row_count"] == 2
    assert dashboard["feedback_status"] == "COMPLETE_FEEDBACK_AVAILABLE_WITH_QUARANTINE"
    assert "trainer feedback missing strategy/hedge/regime fields" not in " ".join(dashboard["blockers"])


def test_complete_feedback_without_optional_context_still_drives_performance_metrics() -> None:
    inputs = _base_inputs(live_margin=20.0)
    row = _complete_outcome(pnl_usd=12.0, pnl_bps=24.0, winner=True)
    for field in (
        "liquidity_zone_context",
        "liquidation_distance_context",
        "microstructure_context",
    ):
        row.pop(field)
    inputs["paper_outcomes"] = [row]
    inputs["trainer_feedback"] = [row]
    inputs["closed_trades"] = [row]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    feasibility = payloads["monthly_profit_target_feasibility_status.json"]
    dashboard = payloads["operator_dashboard_payload.json"]
    simulation = payloads["monthly_10k_goal_simulation_status.json"]

    assert feasibility["performance_outcome_count"] == 1
    assert feasibility["performance_sample_status"] == "INSUFFICIENT_CLEAN_PERFORMANCE_SAMPLE"
    assert feasibility["current_win_rate"] == 1.0
    assert feasibility["current_win_rate_qualified"] is None
    assert feasibility["performance_context_missing_field_counts"] == {
        "liquidity_zone_context": 1,
        "liquidation_distance_context": 1,
        "microstructure_context": 1,
    }
    assert dashboard["performance_outcome_count"] == 1
    assert dashboard["current_win_rate"] == 1.0
    assert simulation["performance_outcome_count"] == 1
    assert simulation["win_rate"] == 1.0


def test_missing_prediction_input_diagnostics_classifies_redis_input_gaps() -> None:
    class FakeRedis:
        def __init__(self, present_keys: set[str]) -> None:
            self.present_keys = present_keys

        def exists(self, key: str) -> int:
            return int(key in self.present_keys)

    client = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:ALPHAUSDT:1m",
            "v2:features:latest:ALPHAUSDT:1m",
            "v2:features:latest:ALPHAUSDT:5m",
            "v2:market:ohlcv_closed:binance:BETAUSDT:1m",
            "v2:market:ohlcv_closed:binance:GAMMAUSDT:1m",
            "v2:unified_features:GAMMAUSDT:1m:latest",
        }
    )
    payload = {
        "prediction_rows": [
            {"symbol": "ALPHAUSDT", "timeframe": "1m", "status": "MISSING_TF_PREDICTION"},
            {"symbol": "ALPHAUSDT", "timeframe": "5m", "status": "MISSING_TF_PREDICTION"},
            {"symbol": "BETAUSDT", "timeframe": "1m", "status": "MISSING_TF_PREDICTION"},
            {"symbol": "GAMMAUSDT", "timeframe": "1m", "status": "MISSING_TF_PREDICTION"},
        ],
    }

    diagnostics = monitor_service.missing_prediction_input_diagnostics(client, payload)

    by_symbol = diagnostics["missing_prediction_input_diagnostics_by_symbol"]
    assert by_symbol["ALPHAUSDT"]["likely_root_cause"] == "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE"
    assert by_symbol["ALPHAUSDT"]["missing_closed_candle_timeframes"] == ["5m"]
    assert by_symbol["BETAUSDT"]["likely_root_cause"] == "MISSING_FEATURE_PAYLOAD"
    assert by_symbol["BETAUSDT"]["missing_feature_payload_timeframes"] == ["1m"]
    assert by_symbol["GAMMAUSDT"]["likely_root_cause"] == (
        "TRAINING_TRUST_CONTRACT_REJECTED_DESPITE_BASIC_INPUTS_PRESENT"
    )
    assert diagnostics["missing_prediction_input_reason_counts"] == {
        "MISSING_CANONICAL_CLOSED_CANDLE_COVERAGE": 1,
        "MISSING_FEATURE_PAYLOAD": 1,
        "TRAINING_TRUST_CONTRACT_REJECTED_DESPITE_BASIC_INPUTS_PRESENT": 1,
    }


def test_accidental_hedge_detection_ignores_closed_or_zero_quantity_history() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["positions"] = [
        {"symbol": "BTCUSDT", "side": "long", "net_quantity": 0.0, "position_state": "CLOSED_POSITION"},
        {"symbol": "BTCUSDT", "side": "short", "net_quantity": 0.0, "position_state": "CLOSED_POSITION"},
        {"symbol": "ETHUSDT", "side": "long", "net_quantity": 1.0, "position_state": "OPEN_POSITION"},
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    hedge = payloads["adaptive_hedging_capability_status.json"]
    assert hedge["accidental_hedge_count"] == 0
    assert hedge["open_position_count_checked_for_accidental_hedge"] == 1


def test_accidental_hedge_detection_ignores_raw_fill_ledger_rows() -> None:
    inputs = _base_inputs(live_margin=20.0)
    inputs["positions"] = [
        {
            "symbol": "ZECUSDT",
            "side": "long",
            "quantity": 0.1,
            "decision": "ACCEPTED_PAPER_FILL",
            "fill_id": "fill-long",
            "ledger_row_id": "fill-long",
        },
        {
            "symbol": "ZECUSDT",
            "side": "short",
            "quantity": 0.1,
            "decision": "ACCEPTED_PAPER_FILL",
            "fill_id": "fill-short",
            "ledger_row_id": "fill-short",
        },
    ]

    payloads = build_monitor_payloads(
        inputs,
        generated_est="2026-06-13T19:30:00-04:00",
        generated_utc="2026-06-13T23:30:00Z",
    )

    hedge = payloads["adaptive_hedging_capability_status.json"]
    assert hedge["accidental_hedge_count"] == 0
    assert hedge["open_position_count_checked_for_accidental_hedge"] == 0
    assert hedge["noncanonical_position_rows_ignored_count"] == 2


def test_paper_close_outcome_propagates_strategy_and_hedge_metadata() -> None:
    position = PaperNetPosition(
        position_id="pos1",
        symbol="BTCUSDT",
        side="long",
        net_quantity=0.1,
        avg_entry_price=100.0,
        opened_est="2026-06-13T23:00:00Z",
        strategy_id="strategy_trend_following",
        strategy_family="trend_following",
        strategy_selected_mode="trend_mode",
        hedge_state="NO_HEDGE",
        hedge_reason="NO_HEDGE_CONTEXT",
        drawdown_at_entry=12.5,
        market_regime_at_entry="TREND",
        fill_ids=["fill1"],
    )

    close_event, outcome = build_close_event(
        position=position,
        close_quantity=0.1,
        exit_price=110.0,
        exit_time="2026-06-13T23:10:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
    )

    for row in (close_event, outcome):
        assert row["strategy_id"] == "strategy_trend_following"
        assert row["strategy_family"] == "trend_following"
        assert row["hedge_state"] == "NO_HEDGE"
        assert row["exit_reason"] == "TIER_2_TAKE_PROFIT"
        assert row["drawdown_at_entry"] == 12.5
        assert row["market_regime_at_entry"] == "TREND"
