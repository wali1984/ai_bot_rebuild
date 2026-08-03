from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.runtime_alpha_dynamic_readiness.service import (
    BLOCKED,
    READY,
    DynamicReadinessPaths,
    build_payloads,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_json(path: Path, updates: dict) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write(path, payload)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _seed(
    public: Path,
    *,
    elapsed: int = 3_600,
    reconciled: str = "RECONCILED",
    goal_status: str = "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE",
) -> None:
    runtime = public / "operator_runtime"
    soak = runtime / "v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest"
    profit = runtime / "v2_monthly_10k_profit_target_monitor/latest"
    paper = runtime / "v2_paper_trade_management/latest"
    _write(
        soak / "operator_dashboard_payload.json",
        {
            "proof_status": "SOAK_1H_COMPLETE" if elapsed >= 3_600 else "PENDING_1H_OBSERVATION",
            "soak_complete": elapsed >= 3_600,
            "soak_1h_complete": elapsed >= 3_600,
            "soak_12h_complete": False,
            "completion_marker": READY if elapsed >= 3_600 else None,
            "completion_window_elapsed_seconds": elapsed,
            "observation_count": 160,
            "density_eligible_observation_count": 150,
            "minimum_required_observations": 120,
            "observation_density_status": "CLEAR",
            "last_observation_freshness_status": "CLEAR",
            "high_severity_alerts": [],
            "static_sizing_regression_status": "CLEAR",
            "same_symbol_stack_status": "CLEAR",
            "same_symbol_hedge_status": "CLEAR",
            "live_balance_hold_status": "CLEAR",
            "closed_positions_count": 1,
            "open_positions_count": 0,
            "outcome_label_count": 4,
            "trainer_feedback_total_row_count": 4,
            "paper_equity": 10_010.0,
            "realized_pnl_usd": 10.0,
            "unrealized_pnl_usd": 0.0,
        },
    )
    _write(soak / "paper_pnl_reconciliation_24h_status.json", {"paper_pnl_reconciliation_status": reconciled})
    _write_jsonl(
        soak / "runtime_alpha_remediated_soak_observations.jsonl",
        [
            {
                "observed_utc": "2026-06-15T01:00:00Z",
                "realized_pnl_usd": 5.0,
                "unrealized_pnl_usd": 0.0,
                "closed_positions_count": 1,
                "closed_trades_count": 1,
            },
            {
                "observed_utc": "2026-06-15T01:30:00Z",
                "realized_pnl_usd": 10.0,
                "unrealized_pnl_usd": 0.0,
                "closed_positions_count": 2,
                "closed_trades_count": 2,
            },
        ],
    )
    _write(soak / "strategy_weight_24h_status.json", {"strategy_weights_by_family": {"trend_following": 0.5}})
    _write(soak / "hedge_cost_benefit_24h_status.json", {"hedge_approvals": 1})
    _write(soak / "exit_reason_24h_status.json", {"exit_reason_distribution": {"TIER_2_PROFIT_BANK": 1}})
    _write(
        profit / "adaptive_strategy_selection_status.json",
        {
            "adaptive_strategy_selection_status": "DYNAMIC_STRATEGY_SELECTION_MONITORED",
            "strategy_selection_policy": "outcome_weighted",
            "families": [
                {
                    "strategy_family": "trend_following",
                    "enabled_for_paper": True,
                    "current_weight": 0.5,
                    "weight_change_reason": "positive expectancy",
                    "sample_count": 4,
                    "accepted_signals": 2,
                    "closed_trades": 1,
                }
            ],
        },
    )
    _write(profit / "adaptive_hedging_capability_status.json", {"adaptive_hedging_capability_status": "HEDGING_READY_ADAPTIVE"})
    _write(
        profit / "adaptive_leverage_margin_selection_status.json",
        {
            "selection_status": "ADAPTIVE_LEVERAGE_MARGIN_PAPER_RECOMMENDATION_READY",
            "paper_recommended_leverage": 1.0,
            "paper_recommended_margin_mode": "ISOLATED_PAPER_SIMULATION",
            "live_leverage_mutation_allowed": False,
            "live_margin_mode_mutation_allowed": False,
            "reason": "paper only",
            "inputs": {"avg_confidence": 0.7, "liquidity_score": 0.8, "drawdown_bps": 0.0},
        },
    )
    _write(
        profit / "monthly_10k_goal_simulation_status.json",
        {
            "goal_status": goal_status,
            "confidence_interval_lower": 20.0,
            "confidence_interval_upper": -10.0,
        },
    )
    _write(
        profit / "trainer_profit_goal_capability_status.json",
        {"samples_seen_last_hour": 12, "closed_trades_last_hour": 1, "training_steps_last_hour": 4},
    )
    _write(
        profit / "trainer_strategy_hedge_feedback_status.json",
        {
            "trainer_feedback_consumable_row_count": 4,
            "feedback_rows_with_hedge_fields": 4,
            "exit_feedback_rows": 4,
        },
    )
    _write(profit / "operator_dashboard_payload.json", {"paper_run_rate_monthly_pnl": -1.0})
    _write(
        runtime / "v2_native_trainer/latest/native_trainer_runtime_status.json",
        {
            "training_loop_active": True,
            "rl_core_primary_overwrites": 0,
            "training_steps_last_hour": 4,
            "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
            "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
            "prediction_grid_current": True,
        },
    )
    _write(
        runtime / "v2_signals/latest/signals_payload.json",
        {
            "summary": {
                "symbols_count": 2,
                "timeframes_count": 5,
                "prediction_rows_count": 10,
                "current_prediction_count": 10,
                "missing_prediction_count": 0,
                "stale_prediction_count": 0,
            },
            "cuda_prediction_contract": {
                "coverage_status": "FULL",
                "actionability_status": "PAPER_ACTIONABILITY_READY",
                "prediction_rows": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "selected_action": "long",
                        "paper_fill_gate_status": "BLOCKED",
                        "prediction_id": "pred-1m",
                        "feature_snapshot_id": "fs-1m",
                        "confidence_calibrated": 0.6,
                        "expected_move_after_cost_bps": 5.0,
                        "market_state_integrity_score": 100.0,
                        "market_state_reject_reasons": [],
                        "market_state_score_components": {"tf_alignment_score": 100.0},
                        "market_state_source_lineage": {"redis_key": "v2:prediction:BTCUSDT:1m"},
                    },
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "5m",
                        "selected_action": "hold",
                        "paper_fill_gate_status": "BLOCKED",
                        "prediction_id": "pred-5m",
                        "feature_snapshot_id": "fs-5m",
                        "confidence_calibrated": 0.55,
                        "expected_move_after_cost_bps": 4.0,
                        "market_state_integrity_score": 100.0,
                        "market_state_reject_reasons": [],
                        "market_state_score_components": {"tf_alignment_score": 100.0},
                        "market_state_source_lineage": {"redis_key": "v2:prediction:BTCUSDT:5m"},
                    },
                ],
            },
        },
    )
    _write(runtime / "v2_live_gate_runtime/latest/live_gate_runtime_state.json", {"trader_state": "LIVE_ARMED_BALANCE_HOLD", "order_transport_submit_enabled": False})
    _write(runtime / "v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json", {"fail_closed": True})
    _write(runtime / "v2_trainer_bridge/latest/v2_trainer_bridge_status.json", {"accepted_as_legacy_hybrid_prediction": False, "legacy_mutation_performed": False})
    _write(paper / "adaptive_capital_allocator_status.json", {"paper_allocator_active": True})
    _write(
        paper / "paper_adaptive_sizing_runtime_status.json",
        {
            "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
            "sample_allocations": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "model_inputs": {
                        "volatility_bps": 42.0,
                        "liquidity_score": 0.91,
                        "spread_bps": 1.7,
                        "slippage_bps": 2.1,
                        "drawdown_bps": 12.0,
                        "risk_envelope": {"max_loss_per_trade_pct": 0.01},
                    },
                }
            ],
        },
    )
    _write(paper / "trade_lifecycle_guard_status.json", {"paper_path_using_lifecycle_controls": True})
    _write(paper / "risk_envelope_dynamic_budget_status.json", {"operator_envelope_type": "PERCENTAGE_BASED_RISK_ENVELOPE"})
    _write(paper / "paper_hedge_netting_status.json", {"accidental_hedge_pairs_allowed": False})
    _write(paper / "paper_exit_coordinator_status.json", {"tiers_enabled": ["TIER_2_PROFIT_BANK"]})
    _write(paper / "paper_stop_takeprofit_trailing_status.json", {"triggered_count": 1})
    _write(paper / "paper_position_lifecycle_status.json", {"outcome_label_count": 4})
    _write(paper / "paper_closed_trade_outcome_label_status.json", {"outcome_label_count": 4, "new_closed_trade_count": 1})
    _write(
        paper / "trainer_feedback_outcomes.json",
        {
            "trainer_feedback_outcomes": [
                {
                    "strategy_id": "trend_following",
                    "strategy_family": "trend_following",
                    "hedge_state": "NO_HEDGE",
                    "hedge_reason": "NO_HEDGE_CONTEXT",
                    "exit_reason": "TIER_2_PROFIT_BANK",
                    "liquidity_zone_context": {"liquidity_score": 1.0},
                }
            ],
            "trainer_strategy_hedge_feedback_status": {"trainer_consumable_rows": 4},
        },
    )


def test_build_payloads_blocks_when_1h_elapsed_missing(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=1_800)
    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    assert dashboard["gate"] == BLOCKED
    assert "1h density-aware soak is still pending" in dashboard["blockers"]
    assert dashboard["live_order_submitted"] is False
    assert dashboard["exchange_leverage_mutation"] is False
    assert dashboard["exchange_margin_mode_mutation"] is False
    strategy = payloads["dynamic_strategy_brain_runtime_status.json"]
    assert strategy["all_timeframe_prediction_grid_current"] is True
    assert strategy["strategies"][0]["active_timeframes"] == ["1m", "5m", "15m", "1h", "4h"]
    trainer = payloads["trainer_10k_objective_readiness_status.json"]
    assert trainer["local_trainer_core_status"] == "LOCAL_NATIVE_TRAINER_CORE_ACTIVE"
    assert trainer["samples_seen_last_hour"] == 12
    assert trainer["closed_trade_feedback_last_hour"] == 1
    assert trainer["strategy_feedback_rows"] == 4
    assert trainer["hedge_feedback_rows"] == 4
    assert trainer["exit_feedback_rows"] == 4
    assert trainer["liquidity_feedback_rows"] == 1
    assert trainer["paper_pnl_last_hour"] == 5.0
    trainer_contract = payloads["local_trainer_core_contract_status.json"]
    assert trainer_contract["status"] == "LOCAL_NATIVE_TRAINER_CORE_ACTIVE"
    assert trainer_contract["legacy_hybrid_reference"] == "v2/legacy_owned_runtime/rl/hybrid_trainer.py"
    assert trainer_contract["wrapper_role"] == "launch_and_proof_guard_only"
    assert "model_replacement" in trainer_contract["wrapper_forbidden_roles"]
    assert trainer_contract["all_dynamic_symbols_must_use_local_model"] is True
    assert trainer_contract["expected_prediction_grid_rows"] == 10
    assert trainer_contract["prediction_grid_rows"] == 10
    assert trainer_contract["current_prediction_count"] == 10
    assert trainer_contract["full_dynamic_symbol_timeframe_grid_covered"] is True
    market = payloads["all_timeframe_market_brain_status.json"]
    assert market["market_row_count"] == 2
    assert market["markets"][0]["symbol"] == "BTCUSDT"
    report = payloads["V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_1H_PAPER_SOAK_DYNAMIC_STRATEGY_LEVERAGE_MARGIN_REPORT.md"]
    assert "Operator-Gated Dynamic Strategy" in report
    assert "Operator-gated validation mode: `true`" in report
    assert "Paper only" not in report
    assert "Paper Soak" not in report


def test_build_payloads_blocks_partial_dynamic_symbol_timeframe_grid(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=3_600)
    signals_path = public / "operator_runtime/v2_signals/latest/signals_payload.json"
    _patch_json(
        signals_path,
        {
            "summary": {
                "symbols_count": 2,
                "timeframes_count": 5,
                "prediction_rows_count": 9,
                "current_prediction_count": 9,
                "missing_prediction_count": 0,
                "stale_prediction_count": 0,
            }
        },
    )

    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    guard = payloads["release_candidate_dynamic_strategy_leverage_margin_guard_status.json"]
    strategy = payloads["dynamic_strategy_brain_runtime_status.json"]
    trainer_contract = payloads["local_trainer_core_contract_status.json"]

    assert dashboard["gate"] == BLOCKED
    assert "release-candidate guard is not clear" in dashboard["blockers"]
    assert guard["dynamic_symbol_timeframe_grid_current"] is False
    assert guard["expected_prediction_grid_rows"] == 10
    assert guard["prediction_grid_rows"] == 9
    assert strategy["all_timeframe_prediction_grid_current"] is False
    assert trainer_contract["status"] == "LOCAL_NATIVE_TRAINER_CORE_NOT_PROVEN"
    assert trainer_contract["full_dynamic_symbol_timeframe_grid_covered"] is False


def test_build_payloads_reports_exact_missing_prediction_grid_rows(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=3_600)
    signals_path = public / "operator_runtime/v2_signals/latest/signals_payload.json"
    missing_rows = [
        {
            "symbol": "JUPUSDT",
            "timeframe": tf,
            "status": "MISSING_TF_PREDICTION",
            "missing_stale_reason": "MISSING_TF_PREDICTION",
            "prediction_redis_key": f"v2:prediction:JUPUSDT:{tf}",
            "trainer_source": "missing source",
            "trainer_source_required": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
            "model_source": "missing source",
            "model_source_required": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
            "next_remediation": f"Generate v2:prediction:JUPUSDT:{tf} from CUDA/RL inference.",
        }
        for tf in ["1m", "5m", "15m", "1h", "4h"]
    ]
    _patch_json(
        signals_path,
        {
            "summary": {
                "symbols_count": 2,
                "timeframes_count": 5,
                "prediction_rows_count": 10,
                "current_prediction_count": 5,
                "missing_prediction_count": 5,
                "stale_prediction_count": 0,
            },
            "cuda_prediction_contract": {
                "coverage_status": "PARTIAL",
                "actionability_status": "BLOCKED_MISSING_TF_PREDICTION",
                "prediction_rows": missing_rows,
                "missing_prediction_symbols": ["JUPUSDT"],
                "missing_prediction_timeframes_by_symbol": {"JUPUSDT": ["1m", "5m", "15m", "1h", "4h"]},
            },
        },
    )

    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    guard = payloads["release_candidate_dynamic_strategy_leverage_margin_guard_status.json"]
    market = payloads["all_timeframe_market_brain_status.json"]
    trainer_contract = payloads["local_trainer_core_contract_status.json"]

    assert dashboard["gate"] == BLOCKED
    assert dashboard["missing_symbol_timeframe_count"] == 5
    assert "local trainer prediction grid missing 5 symbol/timeframe rows: JUPUSDT(1m,5m,15m,1h,4h)" in dashboard["blockers"]
    assert guard["missing_symbol_timeframes_by_symbol"] == {"JUPUSDT": ["1m", "5m", "15m", "1h", "4h"]}
    assert market["missing_symbol_timeframes"][0]["required_prediction_key"] == "v2:prediction:JUPUSDT:1m"
    assert trainer_contract["missing_symbol_timeframe_count"] == 5
    assert trainer_contract["missing_symbol_timeframes"][4]["timeframe"] == "4h"


def test_build_payloads_ready_when_required_evidence_clear_and_goal_rejected_with_evidence(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=3_600, goal_status="GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE")
    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    assert dashboard["gate"] == READY
    assert dashboard["blockers"] == []
    assert payloads["dynamic_leverage_recommendation_status.json"]["paper_only"] is True
    assert payloads["dynamic_margin_mode_recommendation_status.json"]["exchange_mutation"] is False
    paper_ready = payloads["paper_trader_adaptive_readiness_status.json"]
    assert paper_ready["position_size_selection_status"] == "ADAPTIVE_ALLOCATOR_ACTIVE"
    assert paper_ready["exit_logic_selection_status"] == "DYNAMIC_EXIT_LOGIC_READY_PAPER_ONLY"
    assert "confidence" in paper_ready["position_size_selection_inputs"]
    assert payloads["dynamic_exit_logic_status.json"]["status"] == "DYNAMIC_EXIT_LOGIC_READY_PAPER_ONLY"
    leverage = payloads["dynamic_leverage_recommendation_status.json"]
    assert leverage["inputs"]["volatility_bps"] == 42.0
    assert leverage["inputs"]["spread_bps"] == 1.7
    assert leverage["inputs"]["slippage_bps"] == 2.1
    assert leverage["inputs"]["risk_envelope_evidence_present"] is True
    assert leverage["candidates"][0]["volatility_adjustment"] == 42.0
    market = payloads["all_timeframe_market_brain_status.json"]
    assert market["volatility_state"] == 42.0
    assert market["microstructure_state"] == "SPREAD_EVIDENCE_PRESENT"
    projection = payloads["monthly_10k_goal_1h_soak_projection_status.json"]
    assert projection["paper_1h_return_pct"] is not None
    assert projection["projected_daily_net_pnl"] is not None
    assert projection["goal_status"] == "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE"
    assert any("edge shortfall" in item for item in projection["goal_blockers"])
    assert projection["confidence_interval_lower"] == -10.0
    assert projection["confidence_interval_upper"] == 20.0


def test_build_payloads_rejects_10k_when_live_capital_is_missing(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=3_600, goal_status="INSUFFICIENT_EVIDENCE")
    profit_dashboard = public / "operator_runtime/v2_monthly_10k_profit_target_monitor/latest/operator_dashboard_payload.json"
    _patch_json(
        profit_dashboard,
        {
            "live_available_margin": 0.0,
            "live_required_min_order_margin": 64.86,
            "live_target_executable": False,
        },
    )
    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    projection = payloads["monthly_10k_goal_1h_soak_projection_status.json"]
    assert projection["goal_status"] == "GOAL_REQUIRES_MORE_CAPITAL"
    assert any("capital shortfall" in item for item in projection["goal_blockers"])
    assert dashboard["gate"] == READY
    assert "10k/month feasibility cannot be accepted or rejected from current evidence" not in dashboard["blockers"]


def test_build_payloads_blocks_when_goal_evidence_insufficient(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _seed(public, elapsed=3_600, goal_status="INSUFFICIENT_EVIDENCE")
    soak_dashboard = public / "operator_runtime/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/operator_dashboard_payload.json"
    _patch_json(soak_dashboard, {"realized_pnl_usd": None, "paper_pnl": None})
    payloads = build_payloads(DynamicReadinessPaths(repo_root=tmp_path, public_root=public))
    dashboard = payloads["operator_dashboard_payload.json"]
    projection = payloads["monthly_10k_goal_1h_soak_projection_status.json"]
    assert dashboard["gate"] == BLOCKED
    assert projection["goal_status"] == "INSUFFICIENT_SAMPLE_FOR_10K_TARGET"
    assert any("insufficient evidence" in item for item in projection["goal_blockers"])
    assert "10k/month feasibility cannot be accepted or rejected from current evidence" not in dashboard["blockers"]
