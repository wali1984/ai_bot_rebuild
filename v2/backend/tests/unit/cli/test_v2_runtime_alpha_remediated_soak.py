from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak as soak
from v2.backend.tests.unit.cli.test_v2_adaptive_allocation_trade_lifecycle_24h_paper_soak import (
    FakeRedis,
    _dense_observations,
    _redis_payloads,
    _seed_runtime_files,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path(root: Path, absolute_template: Path) -> Path:
    return root / absolute_template.relative_to(soak.REPO_ROOT)


def _seed_alpha_files(root: Path, *, pnl_status: str = "RECONCILED") -> None:
    _write_json(
        root / "liquidity_liquidation_decision_consumer_wiring_status.json",
        {
            "display_only": False,
            "native_trainer_tensor": True,
            "risk_evaluator": {"alpha_liquidity_context_used": True},
            "orchestrator": {"signal_adjustment": "none"},
        },
    )
    _write_json(
        root / "adaptive_strategy_weight_runtime_status.json",
        {
            "adaptive_from_realized_outcomes": True,
            "outcome_count": 1,
            "strategy_runtime_rows": [
                {"strategy_family": "trend_following", "current_weight": 0.35, "closed_trade_count": 1}
            ],
        },
    )
    _write_json(
        root / "adaptive_hedging_runtime_status.json",
        {
            "hedge_allowed": True,
            "hedge_type": "explicit_adaptive_hedge",
            "hedge_reason": "volatility_spike_hedge",
            "hedge_blockers": [],
            "places_real_order": False,
        },
    )
    _write_json(
        root / "hedge_cost_benefit_status.json",
        {"hedge_cost_benefit_tracked": True, "hedge_cost_usd": 0.02, "hedge_benefit_usd": 1.2},
    )
    _write_json(root / "paper_exit_profit_protection_runtime_status.json", {"close_reason": "TIER_2_PROFIT_BANK"})
    _write_json(
        root / "paper_pnl_reconciliation_runtime_status.json",
        {"reconciliation_status": pnl_status, "closed_positions_count": 1, "paper_equity": 1001.0},
    )
    _write_json(
        root / "trainer_strategy_hedge_exit_feedback_status.json",
        {
            "strategy_fields_present": True,
            "hedge_fields_present": True,
            "liquidity_fields_present": True,
            "microstructure_fields_present": True,
            "exit_fields_present": True,
            "trainer_feedback_rows": 1,
        },
    )
    _write_json(
        root / "monthly_10k_goal_feasibility_after_alpha_remediation.json",
        {"goal_status": "INSUFFICIENT_SAMPLE_FOR_10K_TARGET", "guaranteed_profit": False},
    )


def _complete_feedback_payloads() -> dict[str, Any]:
    payloads = _redis_payloads()
    complete_row = {
        "symbol": "BTCUSDT",
        "strategy_id": "strategy_trend_following",
        "strategy_family": "trend_following",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "realized_pnl_bps": 20.0,
        "hold_time_seconds": 600,
        "drawdown_at_entry": 0.0,
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
    }
    payloads["v2:trainer:feedback:outcomes"] = [complete_row]
    payloads["v2:paper:intents"] = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "decision": "ACCEPTED_PAPER_FILL",
            "economic_fill_candidate": True,
            "paper_fill_allowed": True,
            "paper_sizing_complete": True,
            "paper_sizing_source": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
            "quantity": 0.01,
            "notional_usdt": 100.0,
            "entry_price": 10000.0,
            "risk_decision_id": "risk_test",
            "orchestrator_decision_id": "orch_test",
            "signal_id": "sig_test",
            "strategy_id": "strategy_trend_following",
            "strategy_family": "trend_following",
            "drawdown_at_entry": 0.0,
            "market_regime_at_entry": "TREND",
            "liquidity_zone_context": {"source": "test"},
            "liquidation_distance_context": {"source": "test"},
            "microstructure_context": {"source": "test"},
        }
    ]
    return payloads


def test_run_once_writes_remediated_artifacts_and_supersedes_old_soak(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    fake_redis = FakeRedis(_complete_feedback_payloads())

    status = soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc),
        archive_previous=True,
        stopped_observer_status="NO_PREVIOUS_OBSERVER_PROCESS_FOUND",
    )

    public_dir = _path(tmp_path, soak.PUBLIC_DIR)
    runtime_dir = _path(tmp_path, soak.RUNTIME_DIR)
    old_public_dir = tmp_path / "v2" / "frontend" / "public" / soak.OLD_SLUG / "latest"
    old_runtime_dir = tmp_path / "v2" / "frontend" / "public" / "operator_runtime" / soak.OLD_SLUG / "latest"
    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_1H_OBSERVATION"
    assert status["remediation_id"] == soak.DEFAULT_REMEDIATION_ID
    assert status["observer_pid"] == os.getpid()
    assert status["soak_window_label"] == "1h"
    assert status["soak_required_seconds"] == 3600
    assert status["soak_1h_complete"] is False
    assert status["soak_12h_complete"] is False
    assert status["completion_window_elapsed_seconds"] == 0
    assert status["latest_metrics"]["liquidity_decision_consumer_status"] == "ACTIVE"
    assert status["latest_metrics"]["paper_pnl_reconciliation_status"] == "RECONCILED"
    assert status["latest_metrics"]["forward_paper_intent_entry_context_fields_present"] is True
    assert status["operator_dashboard_flattened_metrics_version"] == "runtime_alpha_soak_top_level_v1"
    assert status["forward_paper_intent_rows"] == status["latest_metrics"]["forward_paper_intent_rows"]
    assert status["forward_paper_symbol_count"] == 1
    assert status["forward_paper_timeframe_count"] == 1
    assert status["forward_paper_timeframe_counts"] == [{"reason": "5m", "count": 1}]
    assert status["paper_equity_source"] == status["latest_metrics"]["paper_equity_source"]
    assert status["position_source"] == status["latest_metrics"]["position_source"]
    assert status["canonical_redis_position_row_count"] == status["latest_metrics"]["canonical_redis_position_row_count"]
    assert status["forward_paper_accepted_candidate_rows"] == 1
    assert status["trainer_feedback_complete_row_count"] == 1
    assert status["paper_ledger_current_cycle_static_accepted_rows"] == 0
    assert status["forward_paper_no_trade_root_cause_status"]["redis_keys_used"] == [
        "v2:paper:intents",
        "v2:trainer:feedback:outcomes",
        "v2:paper:ledger",
    ]
    assert status["root_cause"] == status["forward_paper_no_trade_root_cause_status"][
        "natural_language_summary"
    ]
    assert status["forward_paper_no_trade_root_cause_summary"] == status["root_cause"]
    assert status["forward_paper_primary_allocator_decision"] == "missing"
    assert (public_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == soak.READY_GATE
    assert (public_dir / "observer.pid").read_text(encoding="utf-8").strip() == str(os.getpid())
    assert (runtime_dir / "observer.pid").read_text(encoding="utf-8").strip() == str(os.getpid())
    assert (public_dir / "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_24H_PAPER_SOAK_REPORT.md").exists()
    assert (public_dir / "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_12H_PAPER_SOAK_REPORT.md").exists()
    assert (runtime_dir / "runtime_alpha_remediated_soak_observations.jsonl").exists()
    assert (public_dir / "liquidity_consumer_24h_status.json").exists()
    assert (public_dir / "strategy_weight_24h_status.json").exists()
    assert (public_dir / "hedge_cost_benefit_24h_status.json").exists()
    assert (public_dir / "exit_reason_24h_status.json").exists()
    assert (public_dir / "paper_pnl_reconciliation_24h_status.json").exists()
    assert (public_dir / "trainer_feedback_alpha_24h_status.json").exists()
    assert (public_dir / "monthly_10k_goal_feasibility_after_24h_soak.json").exists()
    supersession = json.loads(
        (old_public_dir / "SOAK_SUPERSEDED_BY_RUNTIME_ALPHA_REMEDIATION.json").read_text(encoding="utf-8")
    )
    assert supersession["superseded"] is True
    assert supersession["new_slug"] == soak.SLUG
    for old_dir in (old_public_dir, old_runtime_dir):
        legacy_alias = json.loads((old_dir / "soak_24h_final_operator_dashboard_payload.json").read_text(encoding="utf-8"))
        assert legacy_alias["legacy_alias_superseded"] is True
        assert legacy_alias["superseded_by_slug"] == soak.SLUG
        assert legacy_alias["proof_status"] == "PENDING_1H_OBSERVATION"
        assert legacy_alias["completion_marker"] is None
    assert fake_redis.writes == []


def test_unreconciled_paper_pnl_blocks_remediated_soak(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path, pnl_status="UNRECONCILED")

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(_complete_feedback_payloads()),
        now=datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert status["gate"] == soak.BLOCKED_GATE
    assert "PAPER_PNL_NOT_RECONCILED" in status["high_severity_alerts"]


def test_remediated_soak_completes_after_1h_with_density(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    start = datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc)
    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(_complete_feedback_payloads()),
        now=start,
    )
    observations = _dense_observations(observation, start=start, seconds=3600, count=13)
    status = soak.build_alpha_soak_status(
        observations,
        generated_utc=observations[-1]["observed_utc"],
        interval_seconds=300,
    )

    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "SOAK_1H_COMPLETE"
    assert status["completion_marker"] == soak.COMPLETE_READY_GATE
    assert status["soak_complete"] is True
    assert status["soak_1h_complete"] is True
    assert status["soak_12h_complete"] is False
    assert status["soak_24h_complete"] is False
    assert status["completion_window_elapsed_seconds"] == 3600
    assert status["observation_density_status"] == "CLEAR"
    assert status["latest_observation_age_seconds"] == status["last_observation_age_seconds"]
    assert status["last_observation_freshness_status"] == "CLEAR"


def test_current_redis_feedback_overrides_static_alpha_feedback_status(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["trainer_feedback_row_count"] == 0
    assert observation["trainer_feedback_total_row_count"] == 1
    assert observation["trainer_feedback_alpha_fields_present"] is False
    assert observation["trainer_feedback_alpha_status"]["current_feedback_source"] == "redis:v2:trainer:feedback:outcomes"
    assert observation["trainer_feedback_alpha_status"]["current_missing_field_counts"]["strategy_id"] == 1
    assert observation["trainer_feedback_alpha_status"]["current_dirty_consumable_feedback_rows"] == 1
    assert observation["trainer_feedback_readiness_status"] == "DIRTY_CONSUMABLE_FEEDBACK_DETECTED"
    assert "incorrectly marked consumable" in observation["trainer_feedback_readiness_summary"]
    assert status["gate"] == soak.BLOCKED_GATE
    assert "DIRTY_TRAINER_FEEDBACK_MARKED_CONSUMABLE" in status["high_severity_alerts"]


def test_quarantined_incomplete_feedback_keeps_soak_pending_not_blocked(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    payloads = _redis_payloads()
    row = dict(payloads["v2:trainer:feedback:outcomes"][0])
    row["trainer_consumable"] = False
    row["feedback_schema_version"] = "strategy_hedge_exit_feedback_v1"
    row["missing_feedback_fields"] = ["strategy_id", "strategy_family"]
    payloads["v2:trainer:feedback:outcomes"] = [row]

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(payloads),
        now=datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["trainer_feedback_alpha_fields_present"] is False
    assert observation["trainer_feedback_row_count"] == 0
    assert observation["trainer_feedback_total_row_count"] == 1
    assert observation["trainer_feedback_quarantined_row_count"] == 1
    assert observation["trainer_feedback_alpha_status"]["current_quarantined_incomplete_feedback_rows"] == 1
    assert observation["trainer_feedback_alpha_status"]["current_dirty_consumable_feedback_rows"] == 0
    assert observation["trainer_feedback_readiness_status"] == "FEEDBACK_ROWS_QUARANTINED_MISSING_ALPHA_FIELDS"
    assert observation["trainer_feedback_missing_field_counts"][:2] == [
        {"field": "strategy_family", "count": 1},
        {"field": "strategy_id", "count": 1},
    ]
    assert observation["trainer_feedback_quarantined_example_rows"][0]["trainer_consumable"] is False
    assert status["trainer_feedback_readiness_status"] == "FEEDBACK_ROWS_QUARANTINED_MISSING_ALPHA_FIELDS"
    assert "quarantined" in status["trainer_feedback_readiness_summary"]
    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_1H_OBSERVATION"
    assert status["success_criteria"]["trainer_feedback_rows_gt_0"] is False
    assert status["success_criteria"]["trainer_consumable_feedback_count_gt_0"] is False
    assert status["success_criteria"]["trainer_feedback_total_rows_gt_0"] is True
    assert status["high_severity_alerts"] == []


def test_dirty_consumable_trainer_feedback_blocks_remediated_soak(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    payloads = _redis_payloads()
    payloads["v2:trainer:feedback:outcomes"] = [
        {
            "symbol": "BTCUSDT",
            "strategy_id": None,
            "strategy_family": None,
            "hedge_state": "NO_HEDGE",
            "hedge_reason": "NO_HEDGE_CONTEXT",
            "exit_reason": "TIER_2_TAKE_PROFIT",
            "realized_pnl_bps": 10.0,
            "hold_time_seconds": 600,
            "market_regime_at_entry": None,
            "market_regime_at_exit": None,
            "drawdown_at_entry": None,
            "trainer_consumable": True,
            "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
        }
    ]

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(payloads),
        now=datetime(2026, 6, 14, 5, 8, 13, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["trainer_feedback_alpha_status"]["current_dirty_consumable_feedback_rows"] == 1
    assert status["gate"] == soak.BLOCKED_GATE
    assert "DIRTY_TRAINER_FEEDBACK_MARKED_CONSUMABLE" in status["high_severity_alerts"]


def test_forward_paper_intent_context_status_reads_current_redis() -> None:
    fake_redis = FakeRedis(
        {
            "v2:paper:intents": [
                {
                    "symbol": "BTCUSDT",
                    "paper_fill_allowed": True,
                    "paper_sizing_complete": True,
                    "strategy_id": "trend_following",
                    "strategy_family": "trend_following",
                    "drawdown_at_entry": 0.0,
                    "market_regime_at_entry": "TREND",
                    "liquidity_zone_context": {"source": "test"},
                    "liquidation_distance_context": {"source": "test"},
                    "microstructure_context": {"source": "test"},
                },
                {
                    "symbol": "ETHUSDT",
                    "paper_fill_allowed": False,
                    "paper_sizing_complete": False,
                    "strategy_id": None,
                },
            ]
        }
    )

    status = soak._current_paper_intent_entry_context_status(fake_redis)  # noqa: SLF001

    assert status["paper_intent_rows"] == 2
    assert status["entry_context_rows"] == 1
    assert status["entry_context_fields_present"] is False
    assert status["accepted_candidate_rows"] == 0
    assert status["accepted_candidate_context_rows"] == 0
    assert status["missing_field_counts"]["strategy_id"] == 1


def test_forward_paper_intent_context_does_not_count_no_trade_as_executable() -> None:
    fake_redis = FakeRedis(
        {
            "v2:paper:intents": [
                {
                    "symbol": "BTCUSDT",
                    "paper_fill_allowed": True,
                    "paper_sizing_complete": True,
                    "strategy_id": "no_trade_mode",
                    "strategy_family": "no_trade_mode",
                    "drawdown_at_entry": 0.0,
                    "market_regime_at_entry": "NO_TRADE",
                    "paper_fill_block_reason": "STRATEGY_ROUTER_BLOCKED",
                    "allocator_decision": "BLOCK_NO_EDGE",
                    "allocator_reason": "expected_move_after_cost_not_positive",
                    "local_block_reasons": ["strategy_router:EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"],
                    "paper_fill_gate_block_reasons": ["confidence_below_threshold"],
                    "execution_success_metric_source": "V2_PAPER_CLOSED_TRADE_OUTCOMES",
                    "closed_trade_outcome_count": 11,
                    "strategy_decision_time": "2026-06-14T08:00:30Z",
                    "strategy_feature_cutoff": "2026-06-14T07:59:59Z",
                    "strategy_future_cutoff_offender_count": 1,
                    "strategy_future_cutoff_offenders": [
                        {
                            "symbol": "BTCUSDT",
                            "timeframe": "1m",
                            "feature_cutoff": "2026-06-14T08:00:59Z",
                            "decision_time": "2026-06-14T08:00:30Z",
                        }
                    ],
                    "strategy_router": {
                        "block_reason": "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD",
                        "reason_codes": ["PPO_CONFIDENCE_LOW"],
                        "allowed_actions": ["hold"],
                        "confidence": 0.42,
                        "explanation": {
                            "execution_success_probability": 0.31,
                            "expected_move_bps": -2.5,
                            "data_quality_score": 98.0,
                            "ppo_action": "long",
                            "ppo_confidence": 0.41,
                            "masa_confidence": 0.52,
                            "lower_timeframe": {"timeframe": "1m", "feature_cutoff": "2026-06-14T08:00:59Z"},
                            "mid_timeframe": {"timeframe": "15m", "feature_cutoff": "2026-06-14T07:59:59Z"},
                            "higher_timeframe": {"timeframe": "4h", "feature_cutoff": "2026-06-14T03:59:59Z"},
                        },
                    },
                    "liquidity_zone_context": {"source": "test"},
                    "liquidation_distance_context": {"source": "test"},
                    "microstructure_context": {"source": "test"},
                },
                {
                    "symbol": "ETHUSDT",
                    "decision": "ACCEPTED_PAPER_FILL",
                    "economic_fill_candidate": True,
                    "paper_fill_allowed": True,
                    "paper_sizing_complete": True,
                    "paper_sizing_source": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
                    "quantity": 0.1,
                    "notional_usdt": 100.0,
                    "entry_price": 1000.0,
                    "risk_decision_id": "risk_test",
                    "orchestrator_decision_id": "orch_test",
                    "signal_id": "sig_test",
                    "strategy_id": "trend_following",
                    "strategy_family": "trend_following",
                    "drawdown_at_entry": 0.0,
                    "market_regime_at_entry": "TREND",
                    "liquidity_zone_context": {"source": "test"},
                    "liquidation_distance_context": {"source": "test"},
                    "microstructure_context": {"source": "test"},
                },
            ]
        }
    )

    status = soak._current_paper_intent_entry_context_status(fake_redis)  # noqa: SLF001

    assert status["entry_context_rows"] == 2
    assert status["accepted_candidate_rows"] == 1
    assert status["accepted_candidate_context_rows"] == 1
    assert status["no_trade_context_rows"] == 1
    assert status["strategy_id_counts"][0] == {"reason": "no_trade_mode", "count": 1}
    assert status["market_regime_counts"][0] == {"reason": "NO_TRADE", "count": 1}
    assert status["paper_fill_block_reason_counts"][0] == {"reason": "STRATEGY_ROUTER_BLOCKED", "count": 1}
    assert status["allocator_decision_counts"][0] == {"reason": "BLOCK_NO_EDGE", "count": 1}
    assert status["allocator_reason_counts"][0] == {
        "reason": "expected_move_after_cost_not_positive",
        "count": 1,
    }
    assert status["local_block_reason_counts"][0] == {
        "reason": "strategy_router:EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD",
        "count": 1,
    }
    assert status["paper_fill_gate_block_reason_counts"][0] == {
        "reason": "confidence_below_threshold",
        "count": 1,
    }
    assert status["router_reason_code_counts"][0] == {"reason": "PPO_CONFIDENCE_LOW", "count": 1}
    assert status["selected_timeframe_cutoff_examples"][0]["selected_timeframe_slot"] == "lower_timeframe"
    assert status["selected_timeframe_cutoff_examples"][0]["feature_cutoff"] == "2026-06-14T08:00:59Z"
    assert status["no_trade_example_rows"][0]["router_block_reason"] == (
        "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"
    )
    assert status["no_trade_example_rows"][0]["execution_success_probability"] == 0.31
    assert status["no_trade_example_rows"][0]["execution_success_metric_source"] == (
        "V2_PAPER_CLOSED_TRADE_OUTCOMES"
    )
    assert status["no_trade_example_rows"][0]["closed_trade_outcome_count"] == 11
    assert status["no_trade_example_rows"][0]["strategy_decision_time"] == "2026-06-14T08:00:30Z"
    assert status["no_trade_example_rows"][0]["strategy_future_cutoff_offender_count"] == 1
    assert status["no_trade_example_rows"][0]["strategy_future_cutoff_offenders"][0]["timeframe"] == "1m"
    assert status["future_cutoff_offender_examples"][0]["strategy_future_cutoff_offender_count"] == 1
    assert status["future_cutoff_offender_examples"][0]["strategy_future_cutoff_offenders"][0]["timeframe"] == "1m"
    assert status["no_trade_example_rows"][0]["expected_move_bps"] == -2.5
    assert status["no_trade_example_rows"][0]["lower_timeframe"]["feature_cutoff"] == "2026-06-14T08:00:59Z"
    root_cause = soak._current_no_trade_root_cause_status(status)  # noqa: SLF001
    assert root_cause["primary_router_blocker"] == {
        "reason": "strategy_router:EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD",
        "count": 1,
    }
    assert root_cause["primary_fill_gate_blocker"] == {"reason": "confidence_below_threshold", "count": 1}
    assert root_cause["primary_allocator_decision"] == {"reason": "BLOCK_NO_EDGE", "count": 1}
    assert root_cause["primary_router_reason_code"] == {"reason": "PPO_CONFIDENCE_LOW", "count": 1}
    assert root_cause["execution_success_probability_below_threshold_count"] == 1
    assert root_cause["confidence_below_threshold_count"] == 1
    assert root_cause["selected_timeframe_cutoff_examples"][0]["selected_timeframe"] == "1m"
    assert root_cause["future_cutoff_offender_examples"][0]["strategy_future_cutoff_offenders"][0]["timeframe"] == "1m"
    assert "1/2 current paper intents are no-trade" in root_cause["natural_language_summary"]


def test_historical_static_paper_ledger_rows_are_quarantined_not_blocking(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    payloads = _complete_feedback_payloads()
    payloads["v2:paper:ledger"] = {
        "accepted_intents": [
            {
                "symbol": "XMRUSDT",
                "timeframe": "1h",
                "side": "short",
                "generated_utc": "2026-06-14T07:23:27Z",
                "paper_sizing_source": "V2_PAPER_DEFAULT_NOTIONAL_SIMULATION_POLICY",
                "notional_usdt": 25.0,
                "paper_fill_persistence_status": "EXISTING_FILL_CARRIED_FORWARD",
                "paper_lifecycle_status": "CLOSED_PREVIOUSLY",
            }
        ]
    }

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(payloads),
        now=datetime(2026, 6, 14, 8, 10, 0, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["paper_ledger_static_sizing_regression_status"] == "LEGACY_STATIC_ACCEPTED_ROWS_QUARANTINED"
    assert observation["paper_ledger_legacy_static_accepted_rows"] == 1
    assert observation["paper_ledger_current_cycle_static_accepted_rows"] == 0
    assert status["latest_metrics"]["paper_ledger_current_cycle_static_accepted_rows"] == 0
    assert status["success_criteria"]["current_cycle_static_accepted_ledger_rows_zero"] is True
    assert status["gate"] == soak.READY_GATE
    assert "CURRENT_CYCLE_STATIC_ACCEPTED_FILL" not in status["high_severity_alerts"]


def test_current_cycle_static_paper_ledger_row_blocks_soak(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    _seed_alpha_files(tmp_path)
    payloads = _complete_feedback_payloads()
    payloads["v2:paper:ledger"] = {
        "accepted_intents": [
            {
                "symbol": "XMRUSDT",
                "timeframe": "1h",
                "side": "short",
                "generated_utc": "2026-06-14T08:10:00Z",
                "paper_sizing_source": "V2_PAPER_DEFAULT_NOTIONAL_SIMULATION_POLICY",
                "notional_usdt": 25.0,
                "paper_fill_persistence_status": "NEW_FILL",
                "paper_lifecycle_status": "OPEN",
            }
        ]
    }

    observation = soak.collect_alpha_observation(
        root=tmp_path,
        redis_client=FakeRedis(payloads),
        now=datetime(2026, 6, 14, 8, 10, 0, tzinfo=timezone.utc),
    )
    status = soak.build_alpha_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["paper_ledger_static_sizing_regression_status"] == "CURRENT_CYCLE_STATIC_ACCEPTED_FILL"
    assert observation["paper_ledger_current_cycle_static_accepted_rows"] == 1
    assert status["gate"] == soak.BLOCKED_GATE
    assert "CURRENT_CYCLE_STATIC_ACCEPTED_FILL" in status["high_severity_alerts"]
    assert status["success_criteria"]["current_cycle_static_accepted_ledger_rows_zero"] is False
