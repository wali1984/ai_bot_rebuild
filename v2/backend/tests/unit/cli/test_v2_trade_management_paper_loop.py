from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


class _FakeRedis:
    def __init__(self, payloads: dict[str, object]):
        self.payloads = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str):
        return self.payloads.get(key)

    def set(self, key: str, value: str):
        self.payloads[key] = value
        return True

    def strlen(self, key: str) -> int:
        value = self.payloads.get(key)
        if value is None:
            return 0
        return len(value.encode("utf-8") if isinstance(value, str) else value)


def _preemptive_allow_decision(**overrides) -> dict[str, object]:
    decision = {
        "preemptive_decision_id": "test_preemptive_allow",
        "preemptive_decision": "ALLOW",
        "preemptive_decision_reasons": [],
        "pre_trade_loss_probability": 0.20,
        "confidence_overstatement_risk": 0.0,
        "expected_edge_after_cost_bps": 12.0,
        "allow_paper_fill": True,
        "allow_live_dry_run": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    decision.update(overrides)
    return decision


def test_operator_et_timestamp_fields_preserve_utc_trace() -> None:
    row = {
        "generated_utc": "2026-07-08T06:00:00.000Z",
        "decision_time": "2026-07-08T06:01:00.000Z",
        "entry_time": "2026-07-08T06:02:00.000Z",
        "exit_time": "2026-07-08T06:03:00.000Z",
        "available_at": "2026-07-08T05:59:30.000Z",
    }

    enriched = paper_loop._with_operator_et_timestamp_fields(row)  # noqa: SLF001

    assert enriched["generated_utc"] == row["generated_utc"]
    assert enriched["generated_et"] == "2026-07-08T02:00:00.000-04:00"
    assert enriched["decision_time_et"] == "2026-07-08T02:01:00.000-04:00"
    assert enriched["entry_time_et"] == "2026-07-08T02:02:00.000-04:00"
    assert enriched["exit_time_et"] == "2026-07-08T02:03:00.000-04:00"
    assert enriched["available_at_et"] == "2026-07-08T01:59:30.000-04:00"
    assert enriched["operator_display_timezone"] == "America/New_York"
    assert enriched["raw_utc_allowed_for_machine_trace"] is True


def test_advanced_indicator_fallback_publishes_only_v2_market_keys() -> None:
    base = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    candles = [
        {
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 1000 + i,
            "taker_buy_base_vol": 550 + i,
            "available_at": (base.replace(minute=i % 60)).isoformat(),
            "event_time": (base.replace(minute=i % 60)).isoformat(),
            "candle_closed_confirmed": True,
        }
        for i in range(12)
    ]
    redis = _FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": candles,
            "v2:market:prices:BTCUSDT": {"price": 112.0},
        }
    )

    context = paper_loop._compute_and_publish_v2_advanced_indicator_context(  # noqa: SLF001
        redis,
        "BTCUSDT",
        timeframe="5m",
        decision_time=base.replace(minute=20).isoformat(),
    )

    published = context["advanced_indicator_source_keys"]
    assert context["advanced_indicator_status"] == "ADVANCED_INDICATOR_CONTEXT_COMPUTED_FROM_CLOSED_CANDLES"
    assert published
    assert all(key.startswith("v2:market:") for key in published)
    assert not any(key.startswith("v1:") or key.startswith("legacy:") for key in redis.payloads)
    assert "v2:market:fvg:BTCUSDT:5m" in redis.payloads


def test_advanced_indicator_reader_rejects_stale_contract_and_republishes() -> None:
    base = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    candles = [
        {
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 1000 + i,
            "taker_buy_base_vol": 550 + i,
            "available_at": (base.replace(minute=i % 60)).isoformat(),
            "event_time": (base.replace(minute=i % 60)).isoformat(),
            "candle_closed_confirmed": True,
        }
        for i in range(12)
    ]
    redis = _FakeRedis(
        {
            "v2:market:fvg:BTCUSDT:5m": {
                "schema_version": "v2_fvg_v1",
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "bullish_fvg_present": True,
            },
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": candles,
            "v2:market:prices:BTCUSDT": {"price": 112.0},
        }
    )

    context = paper_loop._read_v2_advanced_indicator_context(  # noqa: SLF001
        redis,
        "BTCUSDT",
        timeframe="5m",
        decision_time=base.replace(minute=20).isoformat(),
    )
    fvg = json.loads(redis.payloads["v2:market:fvg:BTCUSDT:5m"])

    assert context["advanced_indicator_status"] == "ADVANCED_INDICATOR_CONTEXT_COMPUTED_FROM_CLOSED_CANDLES"
    assert context["advanced_indicator_invalid_contract_keys_repaired"]
    assert fvg["event_time"]
    assert fvg["available_at"]
    assert fvg["decision_time"]
    assert fvg["trainer_consumes"] is True
    assert fvg["risk_consumes"] is True


def test_b_grade_calibration_safety_halts_negative_warmup() -> None:
    rows = [
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_B_GRADE_EXPLORATION,
            "realized_net_pnl_bps": value,
            "gross_notional_usd": 100.0,
        }
        for value in (12.0, -20.0, -14.0, 8.0, -18.0)
    ]

    status = paper_loop._b_grade_calibration_safety_status(  # noqa: SLF001
        rows,
        churn_status={"status": "ACTIVE", "new_entries_allowed": True},
        generated_utc="2026-07-06T12:00:00Z",
    )

    assert status["status"] == "HALTED_PERFORMANCE"
    assert status["new_b_grade_entries_allowed"] is False
    assert "B_GRADE_PROFIT_FACTOR_BELOW_1" in status["blockers"]
    assert "B_GRADE_EXPECTANCY_NON_POSITIVE" in status["blockers"]
    assert status["places_real_order"] is False


def test_paper_entry_freeze_halts_when_portfolio_truth_untrusted() -> None:
    freeze = paper_loop._read_paper_entry_freeze(  # noqa: SLF001
        _FakeRedis(
            {
                "v2:portfolio:state": {
                    "equity_trusted": False,
                    "pnl_trusted": False,
                    "reason_if_untrusted": "MARK_PRICE_MISSING_FOR_OPEN_POSITION",
                    "paper_equity_reason": "MARK_PRICE_MISSING",
                }
            }
        )
    )

    assert freeze["paper_new_entries_halted"] is True
    assert freeze["new_entries_allowed"] is False
    assert freeze["reason"] == "MARK_PRICE_MISSING_FOR_OPEN_POSITION"
    assert freeze["source"] == "v2:portfolio:state"
    assert freeze["source_keys"] == ["v2:portfolio:state"]
    assert freeze["places_real_order"] is False


def test_sync_lifecycle_open_position_views_clears_stale_open_views() -> None:
    lifecycle = {
        "open_positions": [{"symbol": "BTCUSDT", "unrealized_pnl_usd": 1.2}],
        "positions_by_symbol": {
            "BTCUSDT": {"symbol": "BTCUSDT", "unrealized_pnl_usd": 1.2}
        },
        "unrealized_pnl_usd": 1.2,
        "total_open_notional": 100.0,
        "paper_position_lifecycle_status": {"open_positions_count": 1},
        "paper_position_exposure_cap_status": {
            "evaluations": [{"symbol": "BTCUSDT", "allowed": True}],
            "blocked_count": 0,
        },
        "paper_hedge_netting_status": {
            "events": [{"symbol": "BTCUSDT", "event": "OPEN_POSITION"}]
        },
        "paper_exit_coordinator_status": {
            "evaluations": [{"symbol": "BTCUSDT", "should_close": False}]
        },
        "paper_stop_takeprofit_trailing_status": {
            "trailing_stop_context_policy": {
                "position_decisions": [{"symbol": "BTCUSDT", "enabled": True}]
            }
        },
    }

    paper_loop._sync_lifecycle_open_position_views(lifecycle, [])  # noqa: SLF001

    assert lifecycle["open_positions"] == []
    assert lifecycle["positions_by_symbol"] == {}
    assert lifecycle["open_position_count"] == 0
    assert lifecycle["unrealized_pnl_usd"] == 0
    assert lifecycle["total_open_notional"] == 0
    assert lifecycle["paper_position_lifecycle_status"]["open_positions_count"] == 0
    assert lifecycle["paper_position_exposure_cap_status"]["evaluations"] == []
    assert lifecycle["paper_hedge_netting_status"]["events"] == []
    assert lifecycle["paper_exit_coordinator_status"]["evaluations"] == []
    assert (
        lifecycle["paper_stop_takeprofit_trailing_status"][
            "trailing_stop_context_policy"
        ]["position_decisions"]
        == []
    )


def test_a_plus_gate_redistribution_flags_100pct_present_source_failures() -> None:
    evaluations = [
        {
            "a_plus": False,
            "failed_checks": [
                "side_bucket_positive",
                "regime_aligned",
                "microstructure_trust_confirms",
                "allocator_allows",
            ],
            "checks": {
                "side_bucket_positive": {"passed": False, "missing_evidence": False},
                "regime_aligned": {"passed": False, "missing_evidence": False},
                "microstructure_trust_confirms": {"passed": False, "missing_evidence": False},
                "allocator_allows": {"passed": False, "missing_evidence": False},
            },
        },
        {
            "a_plus": False,
            "failed_checks": [
                "side_bucket_positive",
                "regime_aligned",
                "microstructure_trust_confirms",
                "allocator_allows",
            ],
            "checks": {
                "side_bucket_positive": {"passed": False, "missing_evidence": False},
                "regime_aligned": {"passed": False, "missing_evidence": False},
                "microstructure_trust_confirms": {"passed": False, "missing_evidence": False},
                "allocator_allows": {"passed": False, "missing_evidence": False},
            },
        },
    ]

    status = paper_loop._a_plus_gate_redistribution_status(  # noqa: SLF001
        evaluations,
        generated_utc="2026-07-06T12:00:00Z",
        paper_session_id="session-1",
    )

    assert status["evaluated_candidates"] == 2
    assert status["a_plus_candidates"] == 0
    assert status["failed_check_counts"]["side_bucket_positive"] == 2
    assert "side_bucket_positive" in status["plumbing_bug_suspected_checks"]
    assert status["known_bad_pattern_detected"] is True


def test_a_plus_gate_redistribution_separates_safety_blocks_from_plumbing() -> None:
    evaluations = [
        {
            "a_plus": False,
            "failed_checks": [
                "allocator_allows",
                "cost_evidence_production_grade",
                "no_quarantine_bucket",
                "no_stale_or_missing_critical_feature",
            ],
            "checks": {
                "allocator_allows": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "ALLOCATOR_BLOCKED:BLOCK_NO_EDGE",
                },
                "cost_evidence_production_grade": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "runtime_cost_capture_status=PARTIAL_COST_CAPTURE",
                },
                "no_quarantine_bucket": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "bucket_quarantine_status=ACTIVE_WITH_QUARANTINES",
                },
                "no_stale_or_missing_critical_feature": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "MISSING_CRITICAL_FEATURES:204",
                },
            },
        },
        {
            "a_plus": False,
            "failed_checks": [
                "allocator_allows",
                "cost_evidence_production_grade",
                "no_quarantine_bucket",
                "no_stale_or_missing_critical_feature",
            ],
            "checks": {
                "allocator_allows": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "ALLOCATOR_BLOCKED:BLOCK_INSUFFICIENT_LIQUIDITY",
                },
                "cost_evidence_production_grade": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "runtime_cost_capture_status=PARTIAL_COST_CAPTURE",
                },
                "no_quarantine_bucket": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "candidate_bucket_quarantined:side:long",
                },
                "no_stale_or_missing_critical_feature": {
                    "passed": False,
                    "missing_evidence": False,
                    "reason": "STALE_FEATURES:3",
                },
            },
        },
    ]

    status = paper_loop._a_plus_gate_redistribution_status(  # noqa: SLF001
        evaluations,
        generated_utc="2026-07-06T12:00:00Z",
        paper_session_id="session-1",
    )

    assert status["source_present_100pct_failure_checks"] == [
        "allocator_allows",
        "cost_evidence_production_grade",
        "no_quarantine_bucket",
        "no_stale_or_missing_critical_feature",
    ]
    assert status["safety_block_100pct_checks"] == [
        "allocator_allows",
        "cost_evidence_production_grade",
        "no_quarantine_bucket",
        "no_stale_or_missing_critical_feature",
    ]
    assert status["plumbing_bug_suspected_checks"] == []


def test_a_plus_5_trade_gate_requires_five_wins() -> None:
    rows = [
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_A_GRADE_EXECUTION,
            "counts_as_a_grade_evidence": True,
            "realized_net_pnl_bps": 5.0,
            "gross_notional_usd": 100.0,
        }
        for _ in range(5)
    ]

    status = paper_loop._a_plus_5_trade_gate_runtime_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-06T12:00:00Z",
    )

    assert status["status"] == "PASSED_A_PLUS_5_TRADE_GATE"
    assert status["win_count"] == 5
    assert status["loss_count"] == 0
    assert status["no_live_mutation"] is True


def test_b_grade_resumption_requests_patch_after_three_zero_fill_cycles() -> None:
    status = paper_loop._b_grade_exploration_resumption_status(  # noqa: SLF001
        intents=[
            {
                "paper_opportunity_tier": paper_loop.PAPER_TIER_B_GRADE_EXPLORATION,
                "confidence_calibrated": 0.5,
            }
        ],
        accepted_rows=[],
        closed_rows=[],
        trainer_feedback_rows=[],
        trainer_hybrid_cuda_status={"status": "RUNNING"},
        b_grade_canary_supply_status={
            "root_cause_counts": {"allocator_failed": 4, "risk_failed": 1}
        },
        previous_status={"accepted_fills_zero_cycle_streak": 2},
        generated_utc="2026-07-06T12:00:00Z",
    )

    assert status["accepted_fills_zero_cycle_streak"] == 3
    assert status["patch_required"] is True
    assert status["patch_target"] == "allocator_failed"
    assert status["exact_blocker"] == "allocator_failed"
    assert status["redis_keys_checked"] == [
        "v2:paper:intents",
        "v2:paper:accepted_fills",
        "v2:paper:closed_trades",
        "v2:trainer:feedback:outcomes",
        "v2:trainer:hybrid_cuda:status",
    ]


def test_write_paper_open_position_state_mirrors_canonical_positions_key() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str, int | None]] = []

        def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.writes.append((key, value, ex))

    redis_client = FakeRedis()
    rows = [{"position_id": "paper_pos_BASUSDT", "symbol": "BASUSDT"}]

    written = paper_loop._write_paper_open_position_state(  # noqa: SLF001
        redis_client,
        rows,
        ttl_seconds=123,
    )

    assert written == ["v2:paper:positions", "v2:paper:open_positions"]
    assert [key for key, _, _ in redis_client.writes] == written
    assert [ttl for _, _, ttl in redis_client.writes] == [123, 123]
    assert [json.loads(payload) for _, payload, _ in redis_client.writes] == [rows, rows]


def test_paper_session_metadata_rows_bind_open_position_identity() -> None:
    rows = paper_loop._with_paper_session_metadata_rows(  # noqa: SLF001
        [{"position_id": "paper_pos_BASUSDT", "symbol": "BASUSDT"}],
        paper_session_id="paper_session_current",
        starting_equity_usd=3000.0,
    )

    assert rows == [
        {
            "position_id": "paper_pos_BASUSDT",
            "symbol": "BASUSDT",
            "paper_session_id": "paper_session_current",
            "session_id": "paper_session_current",
            "reset_session_id": "paper_session_current",
            "starting_equity_usd": 3000.0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    ]


def _allow_preemptive_decision() -> dict:
    return {
        "preemptive_decision_id": "pec_test_allow",
        "preemptive_decision": "ALLOW",
        "pre_trade_loss_probability": 0.35,
    }


def test_missing_preemptive_decision_fails_paper_admission_closed() -> None:
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        {"paper_opportunity_tier": paper_loop.PAPER_TIER_A_GRADE_EXECUTION}
    )

    assert "PREEMPTIVE_DECISION_MISSING_FAIL_CLOSED" in reasons
    assert "PRE_TRADE_LOSS_PROBABILITY_MISSING_FAIL_CLOSED" in reasons


def test_high_pretrade_loss_probability_blocks_paper_admission() -> None:
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_A_GRADE_EXECUTION,
            "preemptive_edge_control": {
                "preemptive_decision_id": "pec_high_loss",
                "preemptive_decision": "ALLOW",
            },
            "pre_trade_loss_probability": 0.91,
        }
    )

    assert "PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND" in reasons


def test_preemptive_reduced_size_requires_guardian_approval_at_admission() -> None:
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE,
            "preemptive_edge_control": {
                "preemptive_decision_id": "pec_reduce",
                "preemptive_decision": "REDUCE_SIZE_PAPER_ONLY",
            },
            "pre_trade_loss_probability": 0.45,
            "continuous_edge_guardian_new_entries_allowed": False,
        }
    )

    assert "REDUCE_SIZE_FILL_LACKS_GUARDIAN_APPROVAL" in reasons


def test_positive_edge_probation_admission_can_pass_halted_guardian() -> None:
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_POSITIVE_EDGE_PROBATION,
            "preemptive_edge_control": {
                "preemptive_decision_id": "pec_probation",
                "preemptive_decision": "POSITIVE_EDGE_PROBATION_PAPER",
            },
            "pre_trade_loss_probability": 0.45,
            "continuous_edge_guardian_status": "HALTED_PERFORMANCE",
            "paper_effective_entry_gate_state": "HALTED",
        }
    )

    assert "GUARDIAN_HALTED_PERFORMANCE_NO_NEW_ENTRY" not in reasons
    assert reasons == []


def test_preemptive_shadow_only_classifier_blocks_sized_entry() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 14.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 14.0,
        },
        allocation=_allowed_allocation(expected_move_after_cost_bps=14.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
        preemptive_decision={
            "preemptive_decision_id": "pec_shadow",
            "preemptive_decision": "SHADOW_ONLY",
            "pre_trade_loss_probability": 0.72,
        },
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "PREEMPTIVE_EDGE_CONTROL_SHADOW_ONLY"
    )
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_preemptive_blocked_counterfactual_feedback_is_pending_and_timestamped() -> None:
    payload, status = paper_loop._build_preemptive_blocked_counterfactual_feedback(  # noqa: SLF001
        [
            {
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "side": "long",
                "strategy_id": "trend_breakout",
                "decision_time": "2026-07-08T12:00:00Z",
                "available_at": "2026-07-08T11:59:58Z",
                "feature_cutoff": "2026-07-08T11:55:00Z",
                "prediction_id": "prediction_1",
                "feature_snapshot_id": "feature_1",
                "mtf_snapshot_id": "mtf_1",
                "expected_move_after_cost_bps": -7.5,
                "preemptive_edge_control": {
                    "preemptive_decision_id": "pec_blocked",
                    "preemptive_decision": "NO_TRADE",
                    "preemptive_decision_reasons": ["BUCKET_EXPECTANCY_NON_POSITIVE"],
                    "pre_trade_loss_probability": 0.91,
                    "confidence_overstatement_risk": 0.78,
                    "expected_edge_after_cost_bps": -7.5,
                    "target_notional_usd": 0.0,
                },
            }
        ],
        paper_session_id="paper-session",
        generated_utc="2026-07-08T12:01:00Z",
    )

    assert payload["row_count"] == 1
    row = payload["rows"][0]
    assert row["counterfactual_feedback_id"] == "preemptive_blocked_pec_blocked"
    assert row["trainer_feedback_source"] == (
        "V2_PREEMPTIVE_EDGE_CONTROL_BLOCKED_CANDIDATE"
    )
    assert row["paper_session_id"] == "paper-session"
    assert row["decision_time"] == "2026-07-08T12:00:00Z"
    assert row["available_at"] == "2026-07-08T11:59:58Z"
    assert row["feature_cutoff"] == "2026-07-08T11:55:00Z"
    assert row["preemptive_decision_id"] == "pec_blocked"
    assert row["preemptive_decision"] == "NO_TRADE"
    assert row["pre_trade_loss_probability"] == pytest.approx(0.91)
    assert row["realized_future_window_label"] is None
    assert row["outcome_label"] == "PENDING_COUNTERFACTUAL_FUTURE_WINDOW"
    assert row["counterfactual_label_pending"] is True
    assert row["consumable_by_trainer_now"] is False
    assert row["no_future_leakage"] is True
    assert row["paper_only"] is True
    assert row["routes_to_live"] is False
    assert row["places_real_order"] is False
    assert status["blocked_candidate_counterfactual_rows"] == 1
    assert status["counterfactual_labels_pending"] == 1
    assert status["consumable_labeled_counterfactual_rows"] == 0
    assert status["trainer_consumption_state"] == "PENDING_FUTURE_WINDOW_LABELS"
    assert status["trainer_key"] == "v2:trainer:preemptive_blocked_candidates"


def test_classifier_admits_positive_edge_probation_paper_only() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": 22.0,
        },
        intent={
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "side": "long",
            "strategy_selected_mode": "trend_mode",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": 22.0,
            "production_grade_cost_flag": True,
            "microstructure_action": "ALLOW",
            "composite_microstructure_trust_score": 0.82,
            "pre_trade_loss_probability": 0.45,
            "exit_feasibility_score": 0.75,
        },
        allocation=_allowed_allocation(expected_move_after_cost_bps=22.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=False,
        positive_edge_probation_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={
            "status": "HALTED_PERFORMANCE",
            "a_grade_new_entries_allowed": False,
        },
        preemptive_decision={
            "preemptive_decision_id": "pec_probation",
            "preemptive_decision": "POSITIVE_EDGE_PROBATION_PAPER",
            "pre_trade_loss_probability": 0.45,
        },
    )

    assert classification["paper_opportunity_tier"] == (
        paper_loop.PAPER_TIER_POSITIVE_EDGE_PROBATION
    )
    assert classification["paper_only"] is True
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False
    assert classification["counts_as_final_a_plus"] is False
    assert classification["counts_as_live_ready"] is False
    assert classification["probation_paper_enabled"] is True


def test_global_performance_halt_preserves_probation_allocator_evidence() -> None:
    intent = {
        "paper_only": True,
        "symbol": "UNRELATEDUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
    }
    allocation = _allowed_allocation()

    blocked = paper_loop._paper_block_new_entry_by_performance_circuit(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        performance_circuit_breaker_status={
            "new_entries_allowed": False,
            "blocked_bucket_keys": [],
        },
    )

    assert blocked is True
    assert intent["paper_performance_circuit_global_halt_only"] is True
    assert allocation["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert allocation["global_halt_preserves_probation_allocator_evidence"] is True


def _allowed_allocation(**overrides):
    payload = {
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usd": 1000.0,
        "target_notional_usdt": 1000.0,
        "target_quantity": 10.0,
        "risk_budget_usd": 100.0,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "expected_fees_usd": 4.0,
        "expected_slippage_usd": 2.0,
        "expected_funding_usd": 1.0,
        "expected_net_pnl_usd": 12.0,
        "expected_shortfall_usd": 150.0,
        "hedge_budget_usd": 10.0,
        "hedge_enabled": True,
        "risk_budget_pct": 0.01,
        "risk_budget_pct_of_equity": 0.01,
        "risk_budget_pct_of_available_margin": 0.02,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
        "model_inputs": {"selected_allocated_margin_usd": 500.0},
    }
    payload.update(overrides)
    return payload


def test_paper_adaptive_sizing_runtime_status_exposes_full_candidate_allocations(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation_rows = [
        _allowed_allocation(
            allocation_id=f"alloc-{index}",
            allocator_decision=(
                "ALLOW_WITH_SIZE" if index % 2 == 0 else "BLOCK_LOW_CONFIDENCE"
            ),
            paper_opportunity_tier=(
                "B_GRADE_EXPLORATION_PAPER" if index % 2 == 0 else "NO_TRADE"
            ),
            source_tier=(
                "B_GRADE_EXPLORATION_PAPER" if index % 2 == 0 else "NO_TRADE"
            ),
            policy_tier=(
                "B_GRADE_EXPLORATION_PAPER" if index % 2 == 0 else "NO_TRADE"
            ),
            selected_action=("long" if index % 2 == 0 else "hold"),
            action=("long" if index % 2 == 0 else "hold"),
            expected_move_bps=(24.0 if index % 2 == 0 else -48.0),
            expected_move_after_cost_bps=(12.0 if index % 2 == 0 else 0.0),
            paper_fill_block_reason=(
                None
                if index % 2 == 0
                else "MARKET_STATE_INTEGRITY_PAPER_GATE_BLOCKED"
            ),
            local_block_reasons=(
                []
                if index % 2 == 0
                else [
                    "entry_gate:EXPECTED_MOVE_NON_POSITIVE:0.0bps",
                    "strategy_router:PPO_ACTION_NOT_TRADABLE",
                ]
            ),
            capital_class=(
                "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
                if index % 2 == 0
                else "NO_TRADE_ZERO_SIZE"
            ),
            guardian_status="A_GRADE_HALTED_PERFORMANCE",
            guardian_new_entries_allowed=False,
        )
        for index in range(30)
    ]

    status = paper_loop._paper_adaptive_sizing_runtime_status(allocation_rows)  # noqa: SLF001

    assert status["paper_candidates_with_allocation"] == 30
    assert status["candidate_allocation_count"] == 30
    assert [row["allocation_id"] for row in status["candidate_allocations"]] == [
        row["allocation_id"] for row in allocation_rows
    ]
    assert all(row["paper_only"] is True for row in status["candidate_allocations"])
    assert all(row["places_real_order"] is False for row in status["candidate_allocations"])
    assert all(row["test_order"] is False for row in status["candidate_allocations"])
    assert all(row["leverage_mutation"] is False for row in status["candidate_allocations"])
    assert all(row["margin_mode_mutation"] is False for row in status["candidate_allocations"])
    assert status["candidate_allocations_complete"] is True
    assert status["candidate_allocations_source"] == (
        "paper_loop_allocation_rows_before_sample_truncation"
    )
    assert status["candidate_allocations_selected_before_outcome"] is True
    assert status["candidate_allocations_future_labels_used_as_features"] is False
    assert len(status["sample_allocations"]) == 25
    assert status["sample_allocations"] == status["candidate_allocations"][:25]
    assert status["accepted_allocation_count"] == 15
    assert status["allocator_pass_rows"] == 15
    assert status["blocked_allocation_count"] == 15
    assert status["a_grade_rows"] == 0
    assert status["A_grade_rows"] == 0
    assert status["near_a_grade_rows"] == 15
    assert status["near_A_grade_rows"] == 15
    assert status["source_tier_counts"] == {
        "B_GRADE_EXPLORATION_PAPER": 15,
        "NO_TRADE": 15,
    }
    assert status["source_tier_a_grade_execution_rows"] == 0
    assert status["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert status["guardian_status_counts"] == {"A_GRADE_HALTED_PERFORMANCE": 30}
    assert status["guardian_new_entries_allowed"] is False
    assert status["source_tier_or_guardian_blocked_allocator_pass_rows"] == 15
    assert status["runtime_status_api_blockers"] == [
        "A_GRADE_SUPPLY_ZERO",
        "SOURCE_TIER_A_GRADE_EXECUTION_ZERO",
        "GUARDIAN_NEW_ENTRIES_DISABLED",
    ]
    assert status["allocator_decision_counts"] == {
        "ALLOW_WITH_SIZE": 15,
        "BLOCK_NON_EXECUTABLE_PAPER_TIER": 15,
    }
    assert status["selected_action_counts"] == {"hold": 15, "long": 15}
    assert status["selected_action_expected_move_bps_sign_counts"] == {
        "hold:negative": 15,
        "long:positive": 15,
    }
    assert status["hold_with_directional_expected_move_bps_count"] == 15
    assert (
        status["hold_zero_after_cost_with_directional_expected_move_bps_count"]
        == 15
    )
    assert status["paper_opportunity_tier_counts"] == {
        "B_GRADE_EXPLORATION_PAPER": 15,
        "NO_TRADE": 15,
    }
    assert status["paper_opportunity_tier_reason_counts"] == {
        "NON_EXECUTABLE_PAPER_TIER:NO_TRADE": 15,
        "missing": 15,
    }
    assert status["paper_fill_block_reason_counts"] == {
        "MARKET_STATE_INTEGRITY_PAPER_GATE_BLOCKED": 15,
        "missing": 15,
    }
    assert status["paper_allocation_block_reason_counts"] == {
        "NON_EXECUTABLE_PAPER_TIER:NO_TRADE": 15,
        "missing": 15,
    }
    assert status["strategy_router_block_reason_counts"] == {
        "PPO_ACTION_NOT_TRADABLE": 15,
        "missing": 15,
    }
    assert status["local_block_reason_counts"] == {
        "entry_gate:EXPECTED_MOVE_NON_POSITIVE:0.0bps": 15,
        "strategy_router:PPO_ACTION_NOT_TRADABLE": 15,
    }
    blocked_rows = [
        row
        for row in status["candidate_allocations"]
        if row["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    ]
    assert all(row["strategy_router_block_reason"] == "PPO_ACTION_NOT_TRADABLE" for row in blocked_rows)
    assert all(row["strategy_router_block_reason_source"] == "local_block_reasons" for row in blocked_rows)
    assert status["allocator_microstructure_block_reason_counts"] == {"missing": 30}
    assert status["microstructure_trust_status_counts"] == {"missing": 30}
    assert status["missing_microstructure_trust_candidate_count"] == 0
    assert status["paper_only"] is True
    assert status["places_real_order"] is False
    assert status["test_orders"] is False
    assert status["leverage_mutation"] is False
    assert status["margin_mode_mutation"] is False
    assert status["old_redis_writes"] is False
    assert status["generated_utc"] == "2026-06-22T13:30:00Z"


def test_running_cycle_heartbeat_uses_challenger_owner_and_long_ttl(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str, int | None]] = []

        def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.writes.append((key, value, ex))

    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T04:30:00Z")
    fake = FakeRedis()

    written = paper_loop._write_paper_runtime_heartbeat(  # noqa: SLF001
        fake,
        started_at="2026-06-27T04:29:00Z",
        cycle_state="RUNNING_CYCLE",
    )

    assert written is True
    assert len(fake.writes) == 1
    key, raw_payload, ttl = fake.writes[0]
    payload = json.loads(raw_payload)
    assert key == f"{paper_loop.V2_REDIS_PREFIX}paper:heartbeat"
    assert ttl == paper_loop.PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS
    assert ttl > paper_loop.PAPER_RUNTIME_TRANSIENT_TTL_SECONDS
    assert payload["cycle_state"] == "RUNNING_CYCLE"
    assert payload["finished_at"] is None
    assert payload["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert payload["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert payload["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert payload["model_source"] == paper_loop.CHALLENGER_V2_MODEL_SOURCE
    assert payload["current_allowed_paper_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["writes_legacy_redis"] is False


def test_candidate_publication_derives_paper_accounting_aliases_from_decision_time_sources(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-accounting",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        side="short",
        entry_price=100.0,
        fill_price=100.0,
        expected_move_after_cost_bps=-50.0,
        depth_price_impact_bps=0.75,
        hedge_budget_usd=0.0,
        hedge_enabled=None,
    )
    allocation.pop("take_profit_price", None)
    allocation.pop("take_profit_structure", None)
    allocation.pop("depth_impact_bps", None)

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["paper_only"] is True
    assert published["places_real_order"] is False
    assert published["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert published["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert published["depth_impact_bps"] == 0.75
    assert published["take_profit_price"] == 99.5
    assert published["take_profit_structure"] == "decision_time_expected_move_or_price_target"
    assert published["hedge_enabled"] is False
    normalized = published["paper_accounting_normalized_fields"]
    assert {
        "target_field": "depth_impact_bps",
        "source_field": "depth_price_impact_bps",
        "normalization": "paper_depth_price_impact_alias",
    } in normalized
    assert {
        "target_field": "take_profit_price",
        "source_field": "expected_move_after_cost_bps",
        "normalization": "paper_expected_move_take_profit_price",
    } in normalized
    assert {
        "target_field": "hedge_enabled",
        "source_field": "hedge_budget_usd",
        "normalization": "paper_hedge_enabled_from_reserved_budget",
    } in normalized


def test_candidate_publication_derives_bounded_hedge_contract_from_budget(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-hedge",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        timeframe="1h",
        hedge_budget_usd=10.0,
        expected_shortfall_usd=150.0,
        expected_fees_usd=4.0,
        expected_slippage_usd=2.0,
        expected_funding_usd=1.0,
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_hedge_budget_pct_of_risk": 0.1,
            "hedge_budget_selection_reason": "correlation_drawdown_volatility_cost_pressure",
        },
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["hedge_enabled"] is True
    assert published["hedge_parent_id"] == "alloc-hedge"
    assert published["hedge_child_id"] == "alloc-hedge:paper_hedge"
    assert published["hedge_intent"] == "expected_shortfall_reduction"
    assert published["hedge_ratio"] == 0.1
    assert published["expected_shortfall_before"] == 150.0
    assert published["hedge_expected_shortfall_reduction_usd"] == 10.0
    assert published["expected_shortfall_after"] == 140.0
    assert published["maximum_duration"] == 7200
    assert published["unwind_plan"] == "close_with_parent_or_timeout"
    assert published["hedge_cost_usd"] == 0.7
    normalized = published["paper_accounting_normalized_fields"]
    assert {
        "target_field": "hedge_parent_id",
        "source_field": "allocation_or_prediction_id",
        "normalization": "paper_bounded_hedge_parent_id",
    } in normalized
    assert {
        "target_field": "expected_shortfall_after",
        "source_field": "expected_shortfall_before:hedge_expected_shortfall_reduction_usd",
        "normalization": "paper_bounded_hedge_expected_shortfall_after",
    } in normalized
    assert published["paper_only"] is True
    assert published["places_real_order"] is False


def test_candidate_publication_disables_hedge_when_cost_exceeds_shortfall_reduction(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-hedge-cost-blocked",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        timeframe="1h",
        hedge_budget_usd=0.5,
        expected_shortfall_usd=150.0,
        expected_fees_usd=4.0,
        expected_slippage_usd=2.0,
        expected_funding_usd=1.0,
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_hedge_budget_pct_of_risk": 0.1,
            "hedge_budget_selection_reason": "correlation_drawdown_volatility_cost_pressure",
        },
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["hedge_enabled"] is False
    assert published["hedge_budget_usd"] == 0.0
    assert published["hedge_expected_shortfall_reduction_usd"] == 0.0
    assert published["expected_shortfall_before"] == 150.0
    assert published["expected_shortfall_after"] == 150.0
    assert published["hedge_cost_usd"] == 0.7
    assert published["pre_hedge_admission_block_hedge_budget_usd"] == 0.5
    assert (
        published["hedge_admission_block_reason"]
        == "paper_bounded_hedge_expected_shortfall_reduction_not_greater_than_costs"
    )
    assert "hedge_parent_id" not in published
    assert "hedge_child_id" not in published
    assert "hedge_intent" not in published
    assert "hedge_ratio" not in published
    assert {
        "target_field": "hedge_enabled",
        "source_field": "hedge_expected_shortfall_reduction_usd:hedge_cost_usd",
        "normalization": "paper_bounded_hedge_expected_shortfall_reduction_not_greater_than_costs",
    } in published["paper_accounting_normalized_fields"]


def test_candidate_publication_derives_zero_liquidation_rare_event_stress_suite(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-stress",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        entry_atr_bps=40.0,
        expected_move_after_cost_bps=50.0,
        actual_observed_spread_entry_bps=1.0,
        bid_ask_spread_bps_fallback=False,
        depth_price_impact_bps=2.0,
        depth_utilization_pct=0.1,
        allocator_liquidity_score=0.9,
        expected_funding_bps=0.5,
        correlation_exposure_pct=0.2,
        liquidation_pressure=0.3,
        mark_index_divergence_bps=4.0,
        latency_ms=100.0,
        recommended_leverage=2.0,
        liquidation_buffer_bps=500.0,
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]
    stress = published["pre_entry_stress_tests"]

    assert status["rare_event_stress_complete_candidate_count"] == 1
    assert status["rare_event_stress_partial_candidate_count"] == 0
    assert published["rare_event_stress_status"] == "COMPLETE_RARE_EVENT_STRESS_SUITE"
    assert published["rare_event_stress_missing_inputs"] == []
    assert stress["status"] == "COMPLETE_RARE_EVENT_STRESS_SUITE"
    assert stress["gap_shock"]["adverse_move_bps"] == 100.0
    assert stress["spread_explosion"]["adverse_move_bps"] == 5.0
    assert stress["double_sided_liquidation_cascade"]["adverse_move_bps"] == 187.5
    assert stress["execution_uncertainty_bps"] == 4.0
    assert stress["correlation_stress_bps"] == 20.0
    assert stress["maintenance_margin_uncertainty_bps"] == 50.0
    assert published["modeled_999_adverse_move_bps"] == 187.5
    assert published["rare_event_required_liquidation_buffer_bps"] == 261.5
    assert stress["liquidation_buffer_covers_required"] is True
    assert {
        "target_field": "pre_entry_stress_tests",
        "source_field": "decision_time_candidate_market_risk_context",
        "normalization": "paper_zero_liquidation_rare_event_stress_suite",
    } in published["paper_accounting_normalized_fields"]
    assert published["paper_only"] is True
    assert published["places_real_order"] is False


def test_paper_adaptive_sizing_status_blocks_missing_tier_allocations(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(allocation_id="alloc-missing-tier")

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert status["accepted_allocation_count"] == 0
    assert status["blocked_allocation_count"] == 1
    assert status["unclassified_allocation_publication_block_count"] == 1
    assert status["non_executable_tier_publication_block_count"] == 1
    assert published["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert published["paper_opportunity_tier_reason"] == (
        "MISSING_OR_INVALID_EXPLICIT_PAPER_OPPORTUNITY_TIER"
    )
    assert published["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert published["original_allocator_decision_before_paper_tier_block"] == "ALLOW_WITH_SIZE"
    assert published["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert published["gross_notional_usd"] == 0.0
    assert published["places_real_order"] is False
    assert allocation["allocator_decision"] == "ALLOW_WITH_SIZE"


def test_current_cycle_candidate_allocations_exclude_historical_accepted_rows() -> None:
    current_allocation = _allowed_allocation(
        allocation_id="current",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
    )
    historical_allocation = _allowed_allocation(
        allocation_id="historical-a-grade",
        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
    )
    lifecycle_blocked_allocation = _allowed_allocation(
        allocation_id="lifecycle-blocked",
        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
    )

    rows = paper_loop._current_cycle_candidate_allocation_rows(  # noqa: SLF001
        intents=[{"adaptive_allocation": current_allocation}],
        historical_accepted_rows=[{"adaptive_allocation": historical_allocation}],
        lifecycle_blocked_rows=[{"adaptive_allocation": lifecycle_blocked_allocation}],
    )

    assert rows == [current_allocation]


def test_current_cycle_candidate_allocations_publish_intent_runtime_evidence() -> None:
    current_allocation = _allowed_allocation(
        allocation_id="current",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
    )
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "adaptive_allocation": current_allocation,
        "paper_fill_allowed": True,
        "paper_tier_local_fill_allowed": True,
        "paper_runtime_market_evidence_rejection_reasons": [],
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "runtime_cost_capture_order_cost_applicable": False,
        "runtime_cost_capture_no_order_reason": "NO_TRADE_ZERO_SIZE_PAPER_INTENT",
        "runtime_cost_capture_missing_fields": ["observed_bid"],
        "runtime_cost_capture_explained_missing_fields": ["observed_bid"],
        "runtime_cost_capture_unexplained_missing_fields": [],
        "paper_standalone_1m_eligibility": {
            "status": "BLOCKED_PAPER_STANDALONE_1M_ELIGIBILITY",
            "standalone_1m_adaptive_policy": (
                "FAIL_CLOSED_REQUIRES_DEDICATED_OR_PRIORITY_BUCKET_EVIDENCE"
            ),
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "paper_standalone_1m_eligibility_blocked": True,
        "paper_standalone_1m_eligibility_blockers": [
            paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON
        ],
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "fee_bps_readonly_schedule": False,
        "long_short_ratio_status": "REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION",
        "long_short_ratio_decision_effect": "REJECTED_PIT_TELEMETRY_ONLY_NO_ADMISSION_CHANGE",
        "rejected_long_short_period": "5m",
        "rejected_long_short_source": (
            "binance_global_long_short_account_ratio:v2:market:long_short:BTCUSDT"
        ),
        "rejected_long_short_event_time": "2026-06-22T13:00:00Z",
        "rejected_long_short_available_at": "2026-06-22T13:00:21Z",
        "rejected_long_short_captured_at": "2026-06-22T13:00:30Z",
        "rejected_long_short_decision_time": "2026-06-22T13:00:20Z",
        "source_tier": "B_GRADE_EXPLORATION_PAPER",
        "policy_tier": "B_GRADE_EXPLORATION_PAPER",
        "capital_class": "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET",
        "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
        "guardian_new_entries_allowed": False,
        "guardian_block_reasons": [{"reason": "ROLLING_100_WIN_RATE_BELOW_90P"}],
        "guardian_allowed_runtime_actions": ["reduce", "close"],
        "continuous_edge_guardian_status": "A_GRADE_HALTED_PERFORMANCE",
        "continuous_edge_guardian_new_entries_allowed": False,
        "expected_funding_bps": 1.25,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "latency_ms": 125.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 1.0, "price": 100.0}],
        "mark_price": 100.1,
        "index_price": 100.0,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
    }

    rows = paper_loop._current_cycle_candidate_allocation_rows(  # noqa: SLF001
        intents=[intent],
    )

    assert rows[0]["allocation_id"] == "current"
    assert rows[0]["paper_fill_allowed"] is True
    assert rows[0]["paper_runtime_market_evidence_rejection_reasons"] == []
    assert rows[0]["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert rows[0]["runtime_cost_capture_status"] == "PRODUCTION_GRADE_COST_CAPTURE"
    assert rows[0]["runtime_cost_capture_order_cost_applicable"] is False
    assert rows[0]["runtime_cost_capture_no_order_reason"] == "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    assert rows[0]["runtime_cost_capture_missing_fields"] == ["observed_bid"]
    assert rows[0]["runtime_cost_capture_explained_missing_fields"] == ["observed_bid"]
    assert rows[0]["runtime_cost_capture_unexplained_missing_fields"] == []
    assert rows[0]["paper_standalone_1m_eligibility"]["status"] == (
        "BLOCKED_PAPER_STANDALONE_1M_ELIGIBILITY"
    )
    assert rows[0]["paper_standalone_1m_eligibility"]["standalone_1m_adaptive_policy"] == (
        "FAIL_CLOSED_REQUIRES_DEDICATED_OR_PRIORITY_BUCKET_EVIDENCE"
    )
    assert rows[0]["paper_standalone_1m_eligibility_blocked"] is True
    assert rows[0]["paper_standalone_1m_eligibility_blockers"] == [
        paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON
    ]
    assert rows[0]["fee_bps"] == 4.0
    assert rows[0]["fee_bps_source"] == "exchange_fee_schedule"
    assert rows[0]["fee_bps_readonly_schedule"] is False
    assert rows[0]["long_short_ratio_status"] == "REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION"
    assert rows[0]["long_short_ratio_decision_effect"] == (
        "REJECTED_PIT_TELEMETRY_ONLY_NO_ADMISSION_CHANGE"
    )
    assert rows[0]["rejected_long_short_source"] == (
        "binance_global_long_short_account_ratio:v2:market:long_short:BTCUSDT"
    )
    assert rows[0]["rejected_long_short_event_time"] == "2026-06-22T13:00:00Z"
    assert rows[0]["rejected_long_short_available_at"] == "2026-06-22T13:00:21Z"
    assert rows[0]["rejected_long_short_captured_at"] == "2026-06-22T13:00:30Z"
    assert rows[0]["rejected_long_short_decision_time"] == "2026-06-22T13:00:20Z"
    assert rows[0]["source_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert rows[0]["policy_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert rows[0]["capital_class"] == "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
    assert rows[0]["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert rows[0]["guardian_new_entries_allowed"] is False
    assert rows[0]["guardian_block_reasons"] == [
        {"reason": "ROLLING_100_WIN_RATE_BELOW_90P"}
    ]
    assert rows[0]["guardian_allowed_runtime_actions"] == ["reduce", "close"]
    assert rows[0]["continuous_edge_guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert rows[0]["continuous_edge_guardian_new_entries_allowed"] is False
    assert rows[0]["expected_funding_bps_source"] == "funding_snapshot"
    assert rows[0]["latency_ms"] == 125.0
    assert rows[0]["quantity"] == 1.0
    assert rows[0]["notional"] == 100.0
    assert rows[0]["notional_usdt"] == 100.0
    assert rows[0]["partial_fill_count"] == 1
    assert rows[0]["entry_feature_available_at"] == "2026-06-22T12:59:00Z"
    assert "paper_fill_allowed" not in current_allocation


def test_paper_adaptive_sizing_runtime_status_counts_microstructure_trust_blocks() -> None:
    status = paper_loop._paper_adaptive_sizing_runtime_status(  # noqa: SLF001
        [
            _allowed_allocation(
                allocator_decision="BLOCK_INSUFFICIENT_LIQUIDITY",
                allocator_microstructure_block_reason="MICROSTRUCTURE_TRUST_SCORE_MISSING",
                microstructure_trust_status="MISSING_MICROSTRUCTURE_TRUST_SCORE",
            ),
            _allowed_allocation(
                allocator_decision="BLOCK_INSUFFICIENT_LIQUIDITY",
                allocator_microstructure_block_reason="MICROSTRUCTURE_TRUST_SCORE_MISSING",
                microstructure_trust_status="MISSING_MICROSTRUCTURE_TRUST_SCORE",
            ),
            _allowed_allocation(
                allocator_decision="BLOCK_LOW_CONFIDENCE",
                microstructure_trust_status="MICROSTRUCTURE_TRUST_SCORE_FOUND",
            ),
        ]
    )

    assert status["allocator_microstructure_block_reason_counts"] == {
        "MICROSTRUCTURE_TRUST_SCORE_MISSING": 2,
        "missing": 1,
    }
    assert status["microstructure_trust_status_counts"] == {
        "MICROSTRUCTURE_TRUST_SCORE_FOUND": 1,
        "MISSING_MICROSTRUCTURE_TRUST_SCORE": 2,
    }
    assert status["missing_microstructure_trust_candidate_count"] == 2


def test_build_allocation_input_uses_configured_paper_fee_schedule_when_missing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }
    signal = {
        "timeframe": "1m",
        "price_target": 100.0,
        "expected_funding_bps": 0.5,
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    # AllocationInput uses the configured paper fee schedule when no explicit fee evidence.
    configured = paper_loop._configured_paper_fee_bps()  # noqa: SLF001
    assert allocation_input.fee_bps == configured
    # Configured fee is production-grade: it IS recorded in intent, not marked as fallback.
    assert intent["fee_bps"] == configured
    assert intent["fee_bps_source"] == paper_loop.PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE  # noqa: SLF001
    assert intent["fee_bps_fallback"] is False
    assert intent["fee_bps_for_allocator"] == configured
    assert intent["fee_bps_readonly_schedule"] is False
    assert intent["fee_bps_configured_schedule"] is True
    assert intent["fee_bps_unavailable_reason"] is None
    assert intent["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert "MISSING_FEES" not in (intent.get("market_cost_evidence_missing_fields") or [])


def test_read_orderbook_microstructure_marks_missing_trust_score() -> None:
    redis_client = _FakeRedis(
        {
            "v2:market:orderbook:BANKUSDT": {
                "bid_ask_spread_bps": 1.2,
                "best_bid": 99.99,
                "best_ask": 100.01,
                "bids": [[99.99, 10.0]],
                "asks": [[100.01, 10.0]],
                "generated_at_ms": 1783293900000,
            },
        }
    )

    microstructure = paper_loop._read_v2_orderbook_microstructure(  # noqa: SLF001
        redis_client,
        "BANKUSDT",
    )

    assert microstructure["microstructure_trust_status"] == "MISSING_MICROSTRUCTURE_TRUST_SCORE"
    assert microstructure["microstructure_trust_missing_reason"] == (
        "NO_V2_MICROSTRUCTURE_TRUST_SCORE_REDIS_PAYLOAD"
    )
    assert microstructure["microstructure_trust_lookup_keys"] == [
        "v2:microstructure:trust_score:BANKUSDT:1m",
        "v2:microstructure:trust_score:BANKUSDT:5m",
        "v2:microstructure:trust_score:BANKUSDT:15m",
    ]
    assert "microstructure_trust_score" not in microstructure


def test_build_allocation_input_exposes_missing_microstructure_trust_block() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 40.0,
        "market_state_integrity_score": 92.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 100.0,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
            "microstructure_trust_status": "MISSING_MICROSTRUCTURE_TRUST_SCORE",
            "microstructure_trust_missing_reason": (
                "NO_V2_MICROSTRUCTURE_TRUST_SCORE_REDIS_PAYLOAD"
            ),
            "microstructure_trust_lookup_keys": [
                "v2:microstructure:trust_score:BTCUSDT:1m",
                "v2:microstructure:trust_score:BTCUSDT:5m",
                "v2:microstructure:trust_score:BTCUSDT:15m",
            ],
        },
    )

    assert allocation_input.liquidity_score == 0.0
    assert intent["allocator_liquidity_score_before_microstructure_trust_gate"] > 0.0
    assert intent["allocator_liquidity_score_after_microstructure"] == 0.0
    assert intent["allocator_liquidity_score_after_microstructure_trust_gate"] == 0.0
    assert intent["allocator_microstructure_block_reason"] == "MICROSTRUCTURE_TRUST_SCORE_MISSING"
    assert intent["allocator_microstructure_trust_gate_status"] == (
        "BLOCKED_MISSING_MICROSTRUCTURE_TRUST_SCORE"
    )
    assert intent["microstructure_trust_status"] == "MISSING_MICROSTRUCTURE_TRUST_SCORE"
    assert intent["microstructure_trust_lookup_keys"] == [
        "v2:microstructure:trust_score:BTCUSDT:1m",
        "v2:microstructure:trust_score:BTCUSDT:5m",
        "v2:microstructure:trust_score:BTCUSDT:15m",
    ]


def test_build_allocation_input_uses_readonly_fee_schedule_before_configured_default() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 100.0,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
        fee_schedule_context={
            "source": "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:BTCUSDT",
            "taker_fee_rate": "0.00035",
        },
    )

    assert allocation_input.fee_bps == pytest.approx(3.5)
    assert intent["fee_bps"] == pytest.approx(3.5)
    assert intent["fee_bps_source"] == (
        "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:BTCUSDT."
        "taker_fee_rate:rate_to_bps"
    )
    assert intent["fee_bps_fallback"] is False
    assert intent["fee_bps_readonly_schedule"] is True
    assert intent["fee_bps_configured_schedule"] is False
    assert intent["fee_bps_for_allocator"] == pytest.approx(3.5)
    assert intent["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"


def test_read_readonly_fee_schedule_context_uses_symbol_specific_redis_payload() -> None:
    redis_client = _FakeRedis(
        {
            "v2:account:fee_schedule:BTCUSDT": {
                "symbol": "BTCUSDT",
                "taker_fee_bps": 3.25,
                "maker_fee_bps": 1.0,
            }
        }
    )

    context = paper_loop._read_readonly_fee_schedule_context(  # noqa: SLF001
        redis_client,
        symbol="BTCUSDT",
    )

    assert context["source"] == "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:BTCUSDT"
    assert paper_loop._fee_bps_from_readonly_schedule(context) == (  # noqa: SLF001
        3.25,
        "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:BTCUSDT.taker_fee_bps",
    )


def test_pre_trade_fee_context_uses_readonly_schedule_before_configured_default() -> None:
    context = paper_loop._pre_trade_fee_context(  # noqa: SLF001
        signal={},
        prediction={"features": {}},
        fee_schedule_context={
            "source": "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:ETHUSDT",
            "taker_fee_bps": 3.1,
        },
    )

    assert context["fee_bps"] == pytest.approx(3.1)
    assert context["fee_bps_source"] == (
        "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:ETHUSDT.taker_fee_bps"
    )
    assert context["fee_bps_readonly_schedule"] is True
    assert context["fee_bps_configured_schedule"] is False


def test_pre_trade_fee_context_prefers_explicit_signal_fee() -> None:
    context = paper_loop._pre_trade_fee_context(  # noqa: SLF001
        signal={"fee_bps": 2.4},
        prediction={"features": {}},
        fee_schedule_context={
            "source": "READ_ONLY_FEE_SCHEDULE_REDIS:v2:account:fee_schedule:SOLUSDT",
            "taker_fee_bps": 3.1,
        },
    )

    assert context["fee_bps"] == pytest.approx(2.4)
    assert context["fee_bps_source"] == "signal.fee_bps"
    assert context["fee_bps_readonly_schedule"] is False
    assert context["fee_bps_configured_schedule"] is False


def test_read_v2_feature_snapshot_missing_timeframe_does_not_default_to_1m() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def get(self, key: str):
            self.keys.append(key)
            return None

    fake = FakeRedis()

    snapshot = paper_loop._read_v2_feature_snapshot(  # noqa: SLF001
        fake,
        "BTCUSDT",
        None,
        decision_time="2026-06-22T13:00:00Z",
    )

    assert snapshot["features"] == {}
    assert snapshot["unavailable_reason"] == paper_loop.MISSING_THESIS_TIMEFRAME_BLOCK_REASON
    assert fake.keys == []


def test_build_allocation_input_marks_missing_thesis_timeframe_unknown() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "price_target": 100.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.timeframe == paper_loop.UNKNOWN_THESIS_TIMEFRAME
    assert intent["timeframe_attribution_status"] == "MISSING_THESIS_TIMEFRAME"
    assert intent["timeframe_attribution_rejection_reason"] == paper_loop.MISSING_THESIS_TIMEFRAME_BLOCK_REASON


def test_standalone_1m_without_dedicated_bucket_is_shadow_blocked() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "thesis_timeframe": "1m",
        "strategy_id": "paper_runtime_momentum",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1m",
        side="long",
        intent=intent,
        signal={"timeframe": "1m"},
        prediction={},
        feature_snapshot={"timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert gate["standalone_1m_thesis"] is True
    assert gate["dedicated_strategy_bucket"] is False
    assert gate["blockers"] == [paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON]
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_standalone_1m_eligibility_blocked"] is True
    assert intent["paper_standalone_1m_eligibility_blockers"] == [
        paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON
    ]
    assert intent["paper_fill_block_reason"] == paper_loop.PAPER_STANDALONE_1M_GATE_BLOCK_REASON
    assert paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON in intent["paper_fill_gate_block_reasons"]
    assert f"standalone_1m_eligibility:{paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON}" in intent[
        "local_block_reasons"
    ]


def test_standalone_1m_with_dedicated_bucket_remains_eligible_for_paper_gate() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "thesis_timeframe": "1m",
        "strategy_id": "standalone_1m_scalp",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1m",
        side="long",
        intent=intent,
        signal={},
        prediction={},
        feature_snapshot={"timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "standalone_1m_scalp"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["dedicated_strategy_bucket"] is True
    assert intent["paper_fill_allowed"] is True
    assert "paper_standalone_1m_eligibility_blocked" not in intent


def test_standalone_1m_priority_bucket_evidence_allows_b_grade_collection_only() -> None:
    intent = {
        "symbol": "HUSDT",
        "timeframe": "1m",
        "thesis_timeframe": "1m",
        "side": "long",
        "strategy_id": "paper_runtime_momentum",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
        "expected_move_after_cost_bps": 8.0,
        "paper_fill_allowed": True,
    }
    priority_index = paper_loop._paper_only_label_collection_priority_index(  # noqa: SLF001
        {
            "generated_utc": "2026-06-23T20:55:00Z",
            "paper_only_label_collection_priority_buckets": [
                {
                    "symbol": "HUSDT",
                    "timeframe": "1m",
                    "side": "long",
                    "strategy": "paper_runtime_momentum",
                    "regime": "TREND",
                    "confidence_bucket": "0.6-0.7",
                    "closed_economic_outcome_count": 3,
                    "sample_count_deficit_to_minimum": 27,
                    "priority_reason": "PRIORITY_UNDERPOWERED_1M_BUCKET",
                }
            ],
        }
    )

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="HUSDT",
        thesis_timeframe="1m",
        side="long",
        intent=intent,
        signal={"timeframe": "1m"},
        prediction={},
        feature_snapshot={"timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
        paper_only_label_collection_priority_index=priority_index,
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["dedicated_strategy_bucket"] is False
    assert gate["paper_only_label_collection_priority_allowed"] is True
    assert gate["paper_only_label_collection_priority_bucket_key"] == (
        "HUSDT|1m|long|paper_runtime_momentum|TREND|0.6-0.7"
    )
    assert gate["standalone_1m_adaptive_policy"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert gate["blockers"] == []
    assert gate["counts_as_a_grade_evidence"] is False
    assert gate["a_grade_promotion_allowed"] is False
    assert gate["live_ready_implication"] is False
    assert "paper_standalone_1m_eligibility_blocked" not in intent

    allocation = _allowed_allocation(
        confidence_calibrated=0.64,
        expected_move_after_cost_bps=8.0,
    )
    paper_loop._attach_paper_only_label_collection_priority(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        priority_index=priority_index,
    )
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
        },
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert classification["counts_as_a_grade_evidence"] is False
    assert classification["a_grade_promotion_allowed"] is False
    assert classification["live_ready_implication"] is False


def test_higher_timeframe_thesis_can_use_1m_execution_timing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "thesis_timeframe": "1h",
        "execution_timeframe": "1m",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1h",
        side="long",
        intent=intent,
        signal={"execution_timeframe": "1m", "timeframe": "1h"},
        prediction={},
        feature_snapshot={"execution_timeframe": "1m", "timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["standalone_1m_thesis"] is False
    assert gate["higher_timeframe_timing_role_allowed"] is True
    assert intent["paper_fill_allowed"] is True


def _reentry_candidate(
    *,
    candle: str = "2026-06-25T13:00:00Z",
    prediction_id: str = "pred-new",
    signal_id: str = "sig-new",
    decision_id: str = "dec-new",
    feature_snapshot_id: str = "fs-new",
    expected_edge: float = 12.0,
) -> dict:
    intent = {
        "paper_fill_allowed": True,
        "expected_move_after_cost_bps": expected_edge,
        "entry_feature_cutoff": candle,
        "generated_utc": "2026-06-25T13:01:00Z",
    }
    return paper_loop._paper_reentry_dedup_candidate_row(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1h",
        side="long",
        intent=intent,
        signal={"signal_id": signal_id},
        prediction={
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "generated_at": "2026-06-25T13:01:00Z",
        },
        feature_snapshot={
            "feature_snapshot_id": feature_snapshot_id,
            "feature_cutoff": candle,
            "features": {},
        },
        risk={"decision_id": decision_id, "risk_decision_id": f"risk-{decision_id}"},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )


def test_paper_reentry_dedup_blocks_same_prediction_id() -> None:
    candidate = _reentry_candidate(prediction_id="pred-1")
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-1",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "paper_result": "FILLED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001
    intent = {"paper_fill_allowed": True}
    paper_loop._apply_paper_reentry_dedup_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "same_prediction_id" in gate["blockers"]
    assert "prediction_id" in gate["duplicate_identity_fields"]
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_reentry_dedup_blocked"] is True
    assert intent["paper_fill_block_reason"] == paper_loop.PAPER_REENTRY_DEDUP_GATE_BLOCK_REASON


def test_paper_reentry_dedup_blocks_same_candle_same_thesis_without_material_change() -> None:
    candidate = _reentry_candidate(expected_edge=10.0)
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "same_candle_same_thesis" in gate["blockers"]
    assert "same_symbol_side_strategy_without_material_change" in gate["blockers"]


def test_paper_reentry_dedup_blocks_partial_close_reentry_without_material_change() -> None:
    candidate = _reentry_candidate(expected_edge=10.0)
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "close_reason": "partial_take_profit",
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "partial_close_reentry_without_material_change" in gate["blockers"]


def test_paper_reentry_dedup_allows_new_finalized_thesis_candle() -> None:
    candidate = _reentry_candidate(
        candle="2026-06-25T14:00:00Z",
        prediction_id="pred-new",
        signal_id="sig-new",
        decision_id="dec-new",
        feature_snapshot_id="fs-new",
        expected_edge=10.0,
    )
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["blockers"] == []
    assert gate["permitted_reentry_reasons"] == ["new_finalized_thesis_candle"]


def test_build_allocation_input_prefers_explicit_fee_over_configured_schedule() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 100.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.fee_bps == 2.5
    assert intent["fee_bps"] == 2.5
    assert intent["fee_bps_source"] == "signal.fee_bps"
    assert intent["fee_bps_configured_schedule"] is False


def test_build_allocation_input_preserves_signed_short_edge_for_allocator() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "short",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": -42.0,
        "market_state_integrity_score": 92.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 99.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.action == "short"
    # Signed edge is passed directly; allocator negates internally for short (max(0, -signed_edge)).
    assert allocation_input.expected_move_after_cost_bps == -42.0
    assert intent["paper_allocation_signed_edge_normalized"] is True
    assert intent["paper_allocation_signed_expected_move_after_cost_bps"] == -42.0
    assert "paper_allocation_signed_edge_preserved" not in intent
    assert "paper_allocation_signed_edge_mismatch" not in intent


def test_write_payload_atomically_replaces_invalid_json(tmp_path) -> None:
    path = tmp_path / "trainer_feedback_outcomes.json"
    path.write_text('{"trainer_feedback_outcomes": []}\\n }\\n}\\n', encoding="utf-8")

    paper_loop.write_payload(
        {
            "paper_only": True,
            "places_real_order": False,
            "trainer_feedback_outcomes": [{"trainer_feedback_id": "fb-1"}],
        },
        path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["paper_only"] is True
    assert payload["places_real_order"] is False
    assert payload["trainer_feedback_outcomes"] == [{"trainer_feedback_id": "fb-1"}]
    assert not list(tmp_path.glob("*.tmp"))


def _write_fake_proc(
    proc_root,
    pid: int,
    argv: list[str],
    *,
    cgroup: str = "",
) -> None:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True)
    proc_dir.joinpath("cmdline").write_bytes(
        b"\0".join(arg.encode() for arg in argv) + b"\0"
    )
    proc_dir.joinpath("cgroup").write_text(cgroup, encoding="utf-8")


def test_paper_active_runtime_owner_status_passes_single_canonical_writer(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T10:20:00Z")
    monkeypatch.setattr(
        paper_loop,
        "_user_systemd_service_enabled",
        lambda service_name: (
            service_name == paper_loop.CANONICAL_PAPER_RUNTIME_SERVICE_NAME
        ),
    )
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_fake_proc(
        proc_root,
        101,
        [
            "/repo/.venv/bin/python3",
            "-m",
            "v2.backend.app.cli.v2_trade_management_paper_loop",
            "--loop",
        ],
        cgroup="0::/user.slice/app.slice/ai-bot-v2-trade-management-paper-loop.service",
    )
    _write_fake_proc(
        proc_root,
        102,
        ["rg", "paper_online_runtime|v2_trade_management_paper_loop"],
    )
    _write_fake_proc(
        proc_root,
        103,
        [
            "/bin/bash",
            "-c",
            "sleep 75; redis-cli GET v2:paper:active_runtime_owner_status | "
            "jq '{paper_online_runtime_active,toy_momentum_entry_writer_active}'",
        ],
    )
    _write_fake_proc(
        proc_root,
        104,
        [
            "/bin/bash",
            "-c",
            "python - <<'PY'\n"
            "import importlib\n"
            "fp = importlib.import_module('v2.backend.app.cli.v2_trade_management_paper_loop')\n"
            "print(fp._paper_runtime_process_rows())\n"
            "PY",
        ],
    )

    status = paper_loop._paper_active_runtime_owner_status(proc_root)  # noqa: SLF001

    assert status["status"] == "PASS_ACTIVE_RUNTIME_OWNER_VALIDATION"
    assert status["canonical_paper_writer_count"] == 1
    assert status["forbidden_entry_process_count"] == 0
    assert status["duplicate_paper_writer_count"] == 0
    assert status["active_new_entry_owner"] == "v2_trade_management_paper_loop"
    assert status["paper_online_runtime_active"] is False
    assert status["paper_online_runtime_enabled"] is False
    assert status["canonical_paper_runtime_enabled"] is True
    assert status["active_process_rows"][0]["canonical_service_scope"] is True
    assert all(status["pass_conditions"].values())


def test_paper_active_runtime_owner_status_blocks_duplicate_or_forbidden_writer(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T10:21:00Z")
    monkeypatch.setattr(
        paper_loop,
        "_user_systemd_service_enabled",
        lambda _service_name: True,
    )
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_fake_proc(
        proc_root,
        101,
        [
            "/repo/.venv/bin/python3",
            "-m",
            "v2.backend.app.cli.v2_trade_management_paper_loop",
        ],
    )
    _write_fake_proc(
        proc_root,
        202,
        [
            "/repo/.venv/bin/python3",
            "-m",
            "v2.backend.app.cli.v2_trade_management_paper_loop",
        ],
    )
    _write_fake_proc(
        proc_root,
        303,
        ["/repo/.venv/bin/python3", "-m", "v2.backend.app.cli.paper_online_runtime"],
    )
    _write_fake_proc(
        proc_root,
        404,
        ["/repo/.venv/bin/python3", "-m", "toy_momentum_wrapper"],
    )

    status = paper_loop._paper_active_runtime_owner_status(proc_root)  # noqa: SLF001

    assert status["status"] == "BLOCKED_ACTIVE_RUNTIME_OWNER_VALIDATION"
    assert status["canonical_paper_writer_count"] == 2
    assert status["forbidden_entry_process_count"] == 2
    assert status["duplicate_paper_writer_count"] == 3
    assert (
        status["active_new_entry_owner"]
        == "BLOCKED_AMBIGUOUS_OR_FORBIDDEN_PAPER_RUNTIME_OWNER"
    )
    assert status["paper_online_runtime_active"] is True
    assert status["paper_online_runtime_enabled"] is True
    assert status["toy_momentum_entry_writer_active"] is True
    assert status["pass_conditions"]["canonical_paper_writer_count_eq_1"] is False
    assert status["pass_conditions"]["forbidden_entry_process_count_zero"] is False
    assert status["pass_conditions"]["paper_online_runtime_enabled_false"] is False


def _completed_controlled_one_shot_status(**overrides):
    payload = {
        "classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK",
        "cycle_state": "COMPLETED_CYCLE",
        "started_at": "2026-06-29T10:00:00Z",
        "finished_at": "2026-06-29T10:00:30Z",
        "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "current_allowed_paper_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        "live_gate": paper_loop.LIVE_GATE_BLOCKED,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "paper_runtime_cost_capture_status": {
            "production_grade_cost_coverage": 1.0,
            "unexplained_missing_cost_rows": 0,
        },
        "paper_b_grade_canary_supply_status": {
            "canary_id": paper_loop.CHALLENGER_B_GRADE_PAPER_CANARY,
            "canary_candidates": 416,
            "canary_intents": 21,
            "canary_pending_rows": 21,
            "canary_binding_missing_rows": 0,
            "counts_as_a_grade_evidence": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {
                "canary_candidates_gt_zero": True,
                "canary_identity_preserved": True,
                "canary_intents_gt_zero": True,
                "canary_pending_rows_gt_zero": True,
            },
        },
    }
    payload.update(overrides)
    return payload


def test_controlled_one_shot_cutover_marker_writes_only_safe_challenger_canary(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T10:01:00Z")
    marker_path = tmp_path / "paper_forward_canary_cutover_marker.json"
    one_shot_output_path = tmp_path / "controlled_one_shot.json"

    marker = paper_loop._write_controlled_one_shot_cutover_marker(  # noqa: SLF001
        _completed_controlled_one_shot_status(),
        one_shot_output_path=one_shot_output_path,
        path=marker_path,
    )

    assert marker["cutover_marker_written"] is True
    assert marker["cutover_completed_at"] == "2026-06-29T10:00:30Z"
    assert marker["one_shot_completed"] is True
    assert marker["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert marker["model_source"] == paper_loop.CHALLENGER_V2_MODEL_SOURCE
    assert marker["production_grade_cost_coverage"] == 1.0
    assert marker["canary_intents"] == 21
    persisted = json.loads(marker_path.read_text(encoding="utf-8"))
    assert persisted["cutover_marker_write_allowed"] is True
    assert persisted["controlled_one_shot_output"] == str(one_shot_output_path)
    assert persisted["routes_to_live"] is False
    assert persisted["places_real_order"] is False
    assert persisted["counts_as_a_grade_evidence"] is False


def test_controlled_one_shot_cutover_marker_rejects_incomplete_canary_contract(
    tmp_path,
) -> None:
    marker_path = tmp_path / "paper_forward_canary_cutover_marker.json"
    status = _completed_controlled_one_shot_status(
        live_gate=paper_loop.LIVE_GATE_ENABLED,
        paper_b_grade_canary_supply_status={
            "canary_id": paper_loop.CHALLENGER_B_GRADE_PAPER_CANARY,
            "canary_candidates": 12,
            "canary_intents": 0,
            "canary_pending_rows": 0,
            "counts_as_a_grade_evidence": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
    )

    marker = paper_loop._write_controlled_one_shot_cutover_marker(  # noqa: SLF001
        status,
        one_shot_output_path=tmp_path / "controlled_one_shot.json",
        path=marker_path,
    )

    assert marker["cutover_marker_written"] is False
    assert marker["cutover_marker_write_allowed"] is False
    assert "LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY" in marker["cutover_marker_write_rejection_reasons"]
    assert "NO_CHALLENGER_CANARY_INTENTS" in marker["cutover_marker_write_rejection_reasons"]
    assert "NO_CHALLENGER_CANARY_PENDING_ROWS" in marker["cutover_marker_write_rejection_reasons"]
    assert "CHALLENGER_CANARY_BINDING_MISSING_ROWS_UNKNOWN" in marker[
        "cutover_marker_write_rejection_reasons"
    ]
    assert not marker_path.exists()


def test_compact_accepted_fill_state_omits_snapshot_but_keeps_trust_and_execution() -> None:
    compact = paper_loop._compact_accepted_fill_for_state(  # noqa: SLF001
        {
            "fill_id": "fill-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "prediction_id": "pred-1",
            "signal_id": "sig-1",
            "decision_id": "dec-1",
            "feature_snapshot_id": "fs-1",
            "entry_feature_snapshot_id": "fs-1",
            "feature_cutoff": "2026-06-22T12:59:00Z",
            "decision_time": "2026-06-22T13:00:00Z",
            "available_at": "2026-06-22T12:59:01Z",
            "entry_feature_snapshot": {"features": {"very_large": [1, 2, 3]}},
            "entry_price": 100.0,
            "fill_price": 100.0,
            "quantity": 2.0,
            "notional_usdt": 200.0,
            "maker_probability": 0.0,
            "taker_probability": 1.0,
            "maker_taker_probability_source": (
                "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE"
            ),
            "selector_policy_fingerprint": "selector-fp-1",
            "frozen_selector_fingerprint": "selector-fp-1",
            "candidate_selected_before_outcome": True,
            "candidate_selected_after_outcome": False,
            "post_outcome_candidate_selection": False,
            "future_labels_used_as_features": False,
            "latency_ms": 125.0,
            "partial_fill_count": 1,
            "partial_fills": [{"quantity": 2.0, "price": 100.0}],
            "mark_price": 100.1,
            "index_price": 100.0,
            "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BTCUSDT",
            "runtime_cost_capture_explained_missing_fields": ["order_size"],
            "runtime_cost_capture_unexplained_missing_fields": [],
            "runtime_cost_capture_order_cost_applicable": False,
            "runtime_cost_capture_no_order_reason": "NO_TRADE_ZERO_SIZE_PAPER_INTENT",
            "adaptive_allocation": {
                "target_notional_usd": 200.0,
                "target_notional_usdt": 200.0,
                "gross_notional_usd": 200.0,
                "recommended_leverage": 2.0,
                "max_loss_if_stop_hit": 2.5,
                "risk_reward": 1.8,
                "risk_of_ruin_contribution": 0.0008,
                "portfolio_exposure_after_trade": 250.0,
                "correlation_exposure_after_trade": 0.025,
                "take_profit_structure": "decision_time_expected_move_or_price_target",
                "take_profit_price": 101.5,
                "hedge_enabled": False,
                "depth_impact_bps": 0.25,
                "model_inputs": {
                    "confidence_calibrated": 0.75,
                    "huge_feature_vector": [9, 9, 9],
                },
            },
        }
    )

    assert compact["accepted_fill_state_compacted"] is True
    assert compact["entry_feature_snapshot_omitted_from_state"] is True
    assert "entry_feature_snapshot" not in compact
    assert compact["prediction_id"] == "pred-1"
    assert compact["feature_snapshot_id"] == "fs-1"
    assert compact["entry_feature_snapshot_id"] == "fs-1"
    assert compact["maker_probability"] == 0.0
    assert compact["taker_probability"] == 1.0
    assert compact["selector_policy_fingerprint"] == "selector-fp-1"
    assert compact["frozen_selector_fingerprint"] == "selector-fp-1"
    assert compact["candidate_selected_before_outcome"] is True
    assert compact["candidate_selected_after_outcome"] is False
    assert compact["post_outcome_candidate_selection"] is False
    assert compact["future_labels_used_as_features"] is False
    assert compact["latency_ms"] == 125.0
    assert compact["partial_fill_count"] == 1
    assert compact["mark_price"] == 100.1
    assert compact["index_price"] == 100.0
    assert compact["runtime_cost_capture_explained_missing_fields"] == ["order_size"]
    assert compact["runtime_cost_capture_unexplained_missing_fields"] == []
    assert compact["runtime_cost_capture_order_cost_applicable"] is False
    assert compact["runtime_cost_capture_no_order_reason"] == "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    assert compact["adaptive_allocation"]["target_notional_usd"] == 200.0
    assert compact["adaptive_allocation"]["target_notional_usdt"] == 200.0
    assert compact["adaptive_allocation"]["gross_notional_usd"] == 200.0
    assert compact["adaptive_allocation"]["recommended_leverage"] == 2.0
    assert compact["adaptive_allocation"]["max_loss_if_stop_hit"] == 2.5
    assert compact["adaptive_allocation"]["risk_reward"] == 1.8
    assert compact["adaptive_allocation"]["risk_of_ruin_contribution"] == 0.0008
    assert compact["adaptive_allocation"]["portfolio_exposure_after_trade"] == 250.0
    assert compact["adaptive_allocation"]["correlation_exposure_after_trade"] == 0.025
    assert compact["adaptive_allocation"]["take_profit_structure"] == (
        "decision_time_expected_move_or_price_target"
    )
    assert compact["adaptive_allocation"]["take_profit_price"] == 101.5
    assert compact["adaptive_allocation"]["hedge_enabled"] is False
    assert compact["adaptive_allocation"]["depth_impact_bps"] == 0.25
    assert compact["adaptive_allocation"]["model_inputs"]["confidence_calibrated"] == 0.75
    assert "huge_feature_vector" not in compact["adaptive_allocation"]["model_inputs"]
    assert "partial_fills" not in compact
    assert "all_partial_fills" not in compact
    assert "partial_fills" not in compact["adaptive_allocation"]
    assert "all_partial_fills" not in compact["adaptive_allocation"]


def test_compact_accepted_fill_backfills_adaptive_allocation_contract() -> None:
    compact = paper_loop._compact_accepted_fill_for_state(  # noqa: SLF001
        {
            "fill_id": "fill-legacy",
            "symbol": "CRVUSDT",
            "gross_notional_usd": 100.0,
            "starting_equity_usd": 1000.0,
            "drawdown_bps": 0.0,
            "adaptive_allocation": {
                "allocator_decision": "ALLOW_WITH_SIZE",
                "target_notional_usd": 500.0,
                "target_notional_usdt": 100.0,
                "gross_notional_usd": 100.0,
                "total_exposure_usdt": 200.0,
                "correlation_exposure_pct": 0.02,
                "stop_distance_bps": 25.0,
                "expected_fees_usd": 0.4,
                "expected_slippage_usd": 0.2,
                "expected_funding_usd": 0.05,
                "expected_net_pnl_usd": 2.7,
            },
        }
    )

    allocation = compact["adaptive_allocation"]
    assert allocation["target_notional_usd"] == 100.0
    assert allocation["target_notional_usdt"] == 100.0
    assert allocation["max_loss_if_stop_hit"] == 0.9
    assert allocation["risk_reward"] == 3.0
    assert allocation["portfolio_exposure_after_trade"] == 300.0
    assert allocation["correlation_exposure_after_trade"] == 0.12
    assert allocation["risk_of_ruin_contribution"] == 0.001
    assert allocation["adaptive_allocation_contract_backfilled"] is True
    assert allocation["adaptive_allocation_contract_backfill_sources"]["target_notional_usd"] == (
        "normalized_to_target_notional_usdt"
    )


def test_read_existing_accepted_fills_prefers_compact_file_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "paper_accepted_fills_state.json"
    state_path.write_text(
        json.dumps(
            {
                "accepted_fills": [
                    {
                        "fill_id": "file-fill",
                        "ledger_row_id": "file-fill",
                        "symbol": "BTCUSDT",
                        "prediction_id": "file-pred",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_ACCEPTED_FILLS_STATE_PATH", state_path)
    redis_client = _FakeRedis(
        {
            "v2:paper:ledger": {
                "accepted": [
                    {
                        "fill_id": "redis-fill",
                        "ledger_row_id": "redis-fill",
                        "symbol": "ETHUSDT",
                        "prediction_id": "redis-pred",
                    }
                ]
            }
        }
    )

    rows = paper_loop._read_existing_accepted_fills(redis_client)  # noqa: SLF001

    assert list(rows) == ["file-fill"]
    assert rows["file-fill"]["prediction_id"] == "file-pred"


def test_read_existing_accepted_fills_replays_open_positions_when_file_is_oversized(
    monkeypatch,
    tmp_path,
) -> None:
    state_path = tmp_path / "paper_accepted_fills_state.json"
    state_path.write_text(
        json.dumps(
            {
                "accepted_fills": [
                    {
                        "fill_id": "stale-file-fill",
                        "symbol": "ETHUSDT",
                        "prediction_id": "stale-file-pred",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_ACCEPTED_FILLS_STATE_PATH", state_path)
    monkeypatch.setattr(paper_loop, "PAPER_STATE_FULL_FILE_READ_MAX_BYTES", 1)
    redis_client = _FakeRedis(
        {
            "v2:paper:positions": [
                {
                    "position_id": "pos-BTC",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "net_quantity": 0.25,
                    "avg_entry_price": 40000.0,
                    "notional": 10000.0,
                    "prediction_id": "pred-open",
                    "risk_decision_id": "risk-open",
                    "orchestrator_decision_id": "orch-open",
                }
            ]
        }
    )

    rows = paper_loop._read_existing_accepted_fills(redis_client)  # noqa: SLF001

    assert list(rows) == ["pos-BTC"]
    replay = rows["pos-BTC"]
    assert replay["prediction_id"] == "pred-open"
    assert replay["quantity"] == 0.25
    assert replay["fill_price"] == 40000.0
    assert replay["paper_fill_persistence_status"] == "OPEN_POSITION_COMPACT_STATE_REPLAY"


def test_compact_status_for_redis_omits_heavy_row_lists() -> None:
    payload = {
        "paper_adaptive_sizing_runtime_status": {
            "candidate_allocation_count": 2,
            "candidate_allocations": [{"allocation_id": "a1"}, {"allocation_id": "a2"}],
            "sample_allocations": [{"allocation_id": "a1"}],
        },
        "paper_a_grade_gate_burndown_status": {
            "near_A_grade_rows": 1,
            "sample_near_a_grade_rows": [{"prediction_id": "pred-1"}],
            "failure_reasons": [{"reason": "A_GRADE_HALTED"}],
        },
        "shadow_observations": [{"prediction_id": "shadow-1"}],
        "held_by_paper_fill_gate": [{"prediction_id": "held-1"}],
    }

    compact = paper_loop._compact_status_for_redis(payload)  # noqa: SLF001

    sizing = compact["paper_adaptive_sizing_runtime_status"]
    assert "candidate_allocations" not in sizing
    assert "sample_allocations" not in sizing
    assert sizing["candidate_allocations_count"] == 2
    assert sizing["sample_allocations_count"] == 1
    assert sizing["sample_rows_omitted_from_redis_status"] is True
    burndown = compact["paper_a_grade_gate_burndown_status"]
    assert "sample_near_a_grade_rows" not in burndown
    assert burndown["sample_near_a_grade_rows_count"] == 1
    assert burndown["failure_reasons"] == [{"reason": "A_GRADE_HALTED"}]
    assert "shadow_observations" not in compact
    assert compact["shadow_observations_count"] == 1
    assert "held_by_paper_fill_gate" not in compact
    assert compact["held_by_paper_fill_gate_count"] == 1


def test_paper_runtime_cost_capture_summary_counts_order_applicable_rows() -> None:
    rows = [
        {
            "runtime_cost_capture_order_cost_applicable": True,
            "production_grade_cost_flag": True,
            "paper_fill_allowed": True,
        },
        {
            "runtime_cost_capture_order_cost_applicable": True,
            "production_grade_cost_flag": False,
            "runtime_cost_capture_unexplained_missing_fields": ["observed_bid"],
        },
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "runtime_cost_capture_missing_fields": ["order_size"],
        },
    ]

    summary = paper_loop._paper_runtime_cost_capture_summary(rows)  # noqa: SLF001

    assert summary["paper_intent_rows"] == 3
    assert summary["order_cost_applicable_rows"] == 2
    assert summary["production_grade_cost_rows"] == 1
    assert summary["production_grade_cost_order_applicable_rows"] == 1
    assert summary["production_grade_cost_coverage"] == 0.5
    assert summary["production_grade_cost_coverage_basis"] == "order_applicable_rows"
    assert summary["production_grade_cost_total_row_coverage"] == 1 / 3
    assert summary["no_order_explained_rows"] == 1
    assert summary["unexplained_missing_cost_rows"] == 1
    assert summary["no_order_missing_cost_rows"] == 1
    assert summary["paper_fill_allowed_rows"] == 1
    assert summary["places_real_order"] is False


def test_paper_runtime_cost_capture_summary_uses_total_coverage_when_no_order_applicable() -> None:
    rows = [
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "production_grade_cost_flag": True,
            "runtime_cost_capture_missing_fields": ["order_size"],
        },
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "production_grade_cost_evidence": True,
            "runtime_cost_capture_missing_fields": ["order_size"],
        },
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "runtime_cost_capture_missing_fields": ["order_size"],
        },
    ]

    summary = paper_loop._paper_runtime_cost_capture_summary(rows)  # noqa: SLF001

    assert summary["paper_intent_rows"] == 3
    assert summary["order_cost_applicable_rows"] == 0
    assert summary["production_grade_cost_rows"] == 2
    assert summary["production_grade_cost_order_applicable_rows"] == 0
    assert summary["production_grade_cost_coverage"] == pytest.approx(2 / 3)
    assert summary["production_grade_cost_coverage_basis"] == (
        "all_intent_rows_no_order_applicable"
    )
    assert summary["production_grade_cost_total_row_coverage"] == pytest.approx(2 / 3)
    assert summary["unexplained_missing_cost_rows"] == 0
    assert summary["no_order_missing_cost_rows"] == 3


def test_paper_runtime_cost_capture_summary_preserves_true_zero_without_cost_rows() -> None:
    rows = [
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "runtime_cost_capture_missing_fields": ["order_size"],
        },
    ]

    summary = paper_loop._paper_runtime_cost_capture_summary(rows)  # noqa: SLF001

    assert summary["production_grade_cost_rows"] == 0
    assert summary["production_grade_cost_coverage"] == 0.0
    assert summary["production_grade_cost_coverage_basis"] == (
        "all_intent_rows_no_order_applicable"
    )
    assert summary["production_grade_cost_total_row_coverage"] == 0.0


def test_paper_candidate_cost_field_coverage_tracks_order_applicable_fields() -> None:
    complete = {
        field: f"value-{field}"
        for field in paper_loop.PHASE2_RUNTIME_COST_CAPTURE_REQUIRED_FIELDS
    }
    complete.update(
        {
            "runtime_cost_capture_order_cost_applicable": True,
            "fallback_cost_flag": False,
            "production_grade_cost_flag": True,
            "runtime_cost_capture_missing_fields": [],
            "runtime_cost_capture_unexplained_missing_fields": [],
        }
    )
    no_order = {
        field: f"value-{field}"
        for field in paper_loop.PHASE2_RUNTIME_COST_CAPTURE_REQUIRED_FIELDS
    }
    no_order.update(
        {
            "runtime_cost_capture_order_cost_applicable": False,
            "fallback_cost_flag": True,
            "production_grade_cost_flag": False,
            "order_size": None,
            "gross_notional_usd": None,
            "allocated_margin_usd": None,
            "runtime_cost_capture_missing_fields": [
                "allocated_margin_usd",
                "gross_notional_usd",
                "order_size",
            ],
            "runtime_cost_capture_unexplained_missing_fields": [],
        }
    )

    coverage = paper_loop._paper_candidate_cost_field_coverage([complete, no_order])  # noqa: SLF001

    assert coverage["candidate_rows"] == 2
    assert coverage["order_applicable_rows"] == 1
    assert coverage["order_applicable_field_coverage"] == 1.0
    assert coverage["unexplained_missing_order_applicable_rows"] == 0
    assert coverage["pass_conditions"] == {
        "unexplained_missing_order_applicable_rows_zero": True,
        "order_applicable_field_coverage_complete": True,
    }
    assert coverage["paper_only"] is True
    assert coverage["routes_to_live"] is False
    assert coverage["places_real_order"] is False


def test_paper_candidate_cost_field_coverage_fails_unexplained_order_applicable_gap() -> None:
    row = {
        field: f"value-{field}"
        for field in paper_loop.PHASE2_RUNTIME_COST_CAPTURE_REQUIRED_FIELDS
    }
    row.update(
        {
            "runtime_cost_capture_order_cost_applicable": True,
            "observed_bid": None,
            "fallback_cost_flag": True,
            "production_grade_cost_flag": False,
            "runtime_cost_capture_missing_fields": ["observed_bid"],
            "runtime_cost_capture_unexplained_missing_fields": ["observed_bid"],
        }
    )

    coverage = paper_loop._paper_candidate_cost_field_coverage([row])  # noqa: SLF001

    assert coverage["order_applicable_field_coverage"] < 1.0
    assert coverage["unexplained_missing_order_applicable_rows"] == 1
    assert coverage["unexplained_missing_by_field"] == {"observed_bid": 1}
    assert coverage["pass_conditions"] == {
        "unexplained_missing_order_applicable_rows_zero": False,
        "order_applicable_field_coverage_complete": False,
    }


def test_feedback_context_fallback_preserves_pre_outcome_candidate_provenance() -> None:
    close_event = {"trainer_feedback_id": "fb-1", "prediction_id": "pred-1"}
    source_context = {
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "selector_policy_fingerprint": "selector-fp-1",
        "frozen_selector_fingerprint": "selector-fp-1",
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "post_outcome_candidate_selection": False,
        "future_labels_used_as_features": False,
    }

    enriched = paper_loop._with_feedback_context_fallback(close_event, source_context)  # noqa: SLF001

    assert enriched["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert enriched["selector_policy_fingerprint"] == "selector-fp-1"
    assert enriched["frozen_selector_fingerprint"] == "selector-fp-1"
    assert enriched["candidate_selected_before_outcome"] is True
    assert enriched["candidate_selected_after_outcome"] is False
    assert enriched["post_outcome_candidate_selection"] is False
    assert enriched["future_labels_used_as_features"] is False


def test_existing_ledger_payload_overlays_lifecycle_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "paper_lifecycle_state.json"
    state_path.write_text(
        json.dumps(
            {
                "accepted_fills": [{"fill_id": "state-fill", "symbol": "BTCUSDT"}],
                "closed_trades": [{"trainer_feedback_id": "close-1", "source_fill_ids": ["state-fill"]}],
                "outcome_labels": [{"trainer_feedback_id": "close-1", "winner": True}],
                "open_positions": [{"position_id": "pos-1", "symbol": "BTCUSDT"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_LIFECYCLE_STATE_PATH", state_path)
    redis_client = _FakeRedis(
        {
            "v2:paper:ledger": {
                "redis_ledger_compacted": True,
                "accepted": [{"fill_id": "redis-sample"}],
                "closed_trades": [{"trainer_feedback_id": "redis-close"}],
            }
        }
    )

    ledger = paper_loop._read_existing_ledger_payload(redis_client)  # noqa: SLF001

    assert ledger["accepted"] == [{"fill_id": "state-fill", "symbol": "BTCUSDT"}]
    assert ledger["accepted_count"] == 1
    # CG-F044: Redis-derived close history (here the ledger fallback sample)
    # must never be displaced by the state file; the file only rescues history
    # keys Redis knows nothing about (outcome_labels below).
    assert ledger["closed_trades"] == [{"trainer_feedback_id": "redis-close"}]
    assert ledger["closed_trade_count"] == 1
    assert ledger["outcome_labels"] == [{"trainer_feedback_id": "close-1", "winner": True}]
    assert ledger["outcome_label_count"] == 1
    assert ledger["open_positions"] == [{"position_id": "pos-1", "symbol": "BTCUSDT"}]
    assert ledger["lifecycle_state_source"] == str(state_path)


def test_existing_ledger_payload_skips_oversized_lifecycle_state(
    monkeypatch,
    tmp_path,
) -> None:
    state_path = tmp_path / "paper_lifecycle_state.json"
    state_path.write_text(
        json.dumps(
            {
                "closed_trades": [{"trainer_feedback_id": "stale-file-close"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_LIFECYCLE_STATE_PATH", state_path)
    monkeypatch.setattr(paper_loop, "PAPER_STATE_FULL_FILE_READ_MAX_BYTES", 1)
    redis_client = _FakeRedis(
        {
            "v2:paper:positions": [{"position_id": "pos-redis", "symbol": "BTCUSDT"}],
            "v2:paper:closed_trades": [
                {"trainer_feedback_id": "redis-close", "source_fill_ids": ["pos-redis"]}
            ],
            "v2:paper:outcome_labels": [{"trainer_feedback_id": "redis-close", "winner": True}],
        }
    )

    ledger = paper_loop._read_existing_ledger_payload(redis_client)  # noqa: SLF001

    assert ledger["open_position_count"] == 1
    assert ledger["closed_trade_count"] == 1
    assert ledger["outcome_label_count"] == 1
    assert ledger["closed_trades"] == [
        {"trainer_feedback_id": "redis-close", "source_fill_ids": ["pos-redis"]}
    ]
    assert ledger["outcome_labels"] == [{"trainer_feedback_id": "redis-close", "winner": True}]
    assert ledger["lifecycle_state_file_skipped"]["skipped_reason"] == (
        "STATE_FILE_EXCEEDS_BOUNDED_RUNTIME_READ_CAP"
    )


def test_attach_paper_sizing_preserves_decision_time_context_on_allocation() -> None:
    intent = {
        "intent_id": "intent-1",
        "source_intent_id": "intent-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "short",
        "selected_action": "short",
        "decision_time": "2026-06-22T13:00:00Z",
        "available_at": "2026-06-22T12:59:10Z",
        "feature_cutoff": "2026-06-22T12:45:00Z",
        "entry_feature_snapshot_id": "fs-1",
        "entry_feature_available_at": "2026-06-22T12:59:10Z",
        "entry_feature_generated_at": "2026-06-22T12:59:05Z",
        "entry_feature_cutoff": "2026-06-22T12:45:00Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "feature_snapshot_id": "fs-1",
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "strategy_id": "trend_mode",
        "strategy_family": "trend_mode",
        "strategy_regime_labels": ["trend"],
        "entry_atr_bps": 42.5,
        "liquidity_score": 0.8,
        "regime_score": 0.7,
        "actual_observed_spread_entry_bps": 1.25,
        "expected_slippage_bps": 0.75,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.5,
        "orderbook_depth_usd": 250000.0,
        "correlation_exposure_pct": 0.12,
        "maker_probability": 0.4,
        "taker_probability": 0.6,
        "maker_taker_probability_source": "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH",
        "latency_ms": 37.0,
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 10.0, "price": 100.0}],
        "mark_index_divergence_bps": 0.3,
        "mark_price": 100.03,
        "index_price": 100.0,
        "margin_mode_simulated": "cross_paper_simulated",
        "generated_utc": "2026-06-22T13:00:01Z",
        "live_gate": "blocked_human_only",
    }
    allocation = _allowed_allocation(
        allocator_decision="BLOCK_LOW_CONFIDENCE",
        recommended_margin_mode="isolated_paper_simulated",
    )

    paper_loop._attach_paper_sizing(intent, allocation)  # noqa: SLF001

    assert allocation["selector_policy_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert intent["selector_policy_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert allocation["frozen_selector_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert intent["frozen_selector_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert allocation["candidate_selected_before_outcome"] is True
    assert intent["candidate_selected_before_outcome"] is True
    assert intent["candidate_selected_after_outcome"] is False
    assert intent["post_outcome_candidate_selection"] is False
    assert allocation["future_labels_used_as_features"] is False
    assert intent["future_labels_used_as_features"] is False
    assert allocation["paper_only"] is True
    assert allocation["places_real_order"] is False
    assert allocation["side"] == "short"
    assert allocation["action"] == "short"
    assert allocation["strategy"] == "trend_mode"
    assert allocation["strategy_family"] == "trend_mode"
    assert allocation["decision_time"] == "2026-06-22T13:00:00Z"
    assert allocation["available_at"] == "2026-06-22T12:59:10Z"
    assert allocation["feature_cutoff"] == "2026-06-22T12:45:00Z"
    assert allocation["entry_feature_snapshot_id"] == "fs-1"
    assert allocation["prediction_id"] == "pred-1"
    assert allocation["signal_id"] == "sig-1"
    assert allocation["risk_decision_id"] == "risk-1"
    assert allocation["entry_atr_bps"] == 42.5
    assert allocation["liquidity_score"] == 0.8
    assert allocation["actual_observed_spread_entry_bps"] == 1.25
    assert allocation["entry_spread_bps"] == 1.25
    assert allocation["expected_slippage_bps"] == 0.75
    assert allocation["fee_bps"] == 4.0
    assert allocation["expected_funding_bps"] == 0.5
    assert allocation["orderbook_depth_usd"] == 250000.0
    assert allocation["correlation_exposure_pct"] == 0.12
    assert allocation["maker_probability"] == 0.4
    assert allocation["taker_probability"] == 0.6
    assert allocation["maker_taker_probability_source"] == "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH"
    assert allocation["latency_ms"] == 37.0
    assert allocation["partial_fill_count"] == 1
    assert allocation["partial_fills"] == [{"quantity": 10.0, "price": 100.0}]
    assert allocation["mark_index_divergence_bps"] == 0.3
    assert allocation["mark_price"] == 100.03
    assert allocation["index_price"] == 100.0
    assert allocation["margin_mode"] == "cross_paper_simulated"
    assert allocation["generated_at"] == "2026-06-22T12:59:05Z"
    assert allocation["live_gate"] == "blocked_human_only"


def test_v2_mark_index_evidence_uses_positive_premium_index_values() -> None:
    redis_client = _FakeRedis({
        "v2:market:funding:BANKUSDT": {
            "symbol": "BANKUSDT",
            "markPrice": "0.03776715",
            "indexPrice": "0.03768583",
            "time": 1782175051004,
        },
    })

    evidence = paper_loop._read_v2_mark_index_evidence(redis_client, "BANKUSDT")  # noqa: SLF001

    assert evidence["mark_price"] == 0.03776715
    assert evidence["index_price"] == 0.03768583
    assert evidence["mark_index_divergence_bps"] > 0.0
    assert evidence["mark_index_source"] == (
        "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT"
    )
    assert evidence["mark_index_available_at"].endswith("Z")


def test_v2_mark_index_evidence_does_not_fabricate_zero_or_missing_values() -> None:
    redis_client = _FakeRedis({
        "v2:market:funding:BTCUSDT": {
            "symbol": "BTCUSDT",
            "markPrice": "0",
            "indexPrice": "0",
            "time": 1782175051004,
        },
        "v2:market:prices:BTCUSDT": {
            "symbol": "BTCUSDT",
            "funding": None,
            "fetched_utc": "2026-06-22T13:00:00Z",
        },
    })

    evidence = paper_loop._read_v2_mark_index_evidence(redis_client, "BTCUSDT")  # noqa: SLF001

    assert evidence == {}


def test_v2_long_short_ratio_evidence_reads_v2_market_payload(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:00:30Z")
    redis_client = _FakeRedis({
        "v2:market:long_short:BANKUSDT": {
            "symbol": "BANKUSDT",
            "period": "5m",
            "longShortRatio": "1.25",
            "longAccount": "0.5556",
            "shortAccount": "0.4444",
            "timestamp": 1782175051004,
            "source": "binance_global_long_short_account_ratio",
            "fetched_utc": "2026-06-22T13:00:10Z",
        }
    })

    evidence = paper_loop._read_v2_long_short_ratio_evidence(redis_client, "BANKUSDT")  # noqa: SLF001

    assert evidence["long_short_ratio"] == 1.25
    assert evidence["long_account_ratio"] == 0.5556
    assert evidence["short_account_ratio"] == 0.4444
    assert evidence["long_short_period"] == "5m"
    assert evidence["long_short_source"] == (
        "binance_global_long_short_account_ratio:v2:market:long_short:BANKUSDT"
    )
    assert evidence["long_short_available_at"] == "2026-06-22T13:00:10.000Z"
    assert evidence["long_short_captured_at"] == "2026-06-22T13:00:30Z"


def test_attach_long_short_ratio_context_is_telemetry_only() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "decision_time": "2026-06-22T13:00:20Z",
        "paper_fill_allowed": False,
    }
    evidence = {
        "long_short_ratio": 1.25,
        "long_account_ratio": 0.5556,
        "short_account_ratio": 0.4444,
        "long_short_period": "5m",
        "long_short_source": "binance_global_long_short_account_ratio:v2:market:long_short:BANKUSDT",
        "long_short_available_at": "2026-06-22T13:00:10Z",
        "long_short_captured_at": "2026-06-22T13:00:30Z",
    }

    paper_loop._attach_long_short_ratio_context(intent, evidence)  # noqa: SLF001

    assert intent["long_short_ratio"] == 1.25
    assert intent["long_account_ratio"] == 0.5556
    assert intent["short_account_ratio"] == 0.4444
    assert intent["long_short_ratio_status"] == "V2_LONG_SHORT_RATIO_ATTACHED"
    assert intent["long_short_ratio_decision_effect"] == "TELEMETRY_ONLY_NO_ADMISSION_CHANGE"
    assert intent["long_short_decision_time"] == "2026-06-22T13:00:20Z"
    assert intent["paper_fill_allowed"] is False


def test_attach_long_short_ratio_context_rejects_future_available_at() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "decision_time": "2026-06-22T13:00:20Z",
        "paper_fill_allowed": False,
    }
    evidence = {
        "long_short_ratio": 1.25,
        "long_short_period": "5m",
        "long_short_source": "binance_global_long_short_account_ratio:v2:market:long_short:BANKUSDT",
        "long_short_event_time": "2026-06-22T13:00:00Z",
        "long_short_available_at": "2026-06-22T13:00:21Z",
        "long_short_captured_at": "2026-06-22T13:00:30Z",
    }

    paper_loop._attach_long_short_ratio_context(intent, evidence)  # noqa: SLF001

    assert intent["long_short_ratio_status"] == "REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION"
    assert intent["long_short_ratio_decision_effect"] == (
        "REJECTED_PIT_TELEMETRY_ONLY_NO_ADMISSION_CHANGE"
    )
    assert "long_short_ratio" not in intent
    assert "long_short_available_at" not in intent
    assert intent["rejected_long_short_period"] == "5m"
    assert intent["rejected_long_short_source"] == (
        "binance_global_long_short_account_ratio:v2:market:long_short:BANKUSDT"
    )
    assert intent["rejected_long_short_event_time"] == "2026-06-22T13:00:00Z"
    assert intent["rejected_long_short_available_at"] == "2026-06-22T13:00:21Z"
    assert intent["rejected_long_short_captured_at"] == "2026-06-22T13:00:30Z"
    assert intent["rejected_long_short_decision_time"] == "2026-06-22T13:00:20Z"
    assert intent["paper_fill_allowed"] is False


def test_v2_long_short_ratio_evidence_does_not_fabricate_missing_values() -> None:
    redis_client = _FakeRedis({
        "v2:market:long_short:BANKUSDT": {
            "symbol": "BANKUSDT",
            "longShortRatio": "0",
            "fetched_utc": "2026-06-22T13:00:10Z",
        }
    })
    intent = {}

    evidence = paper_loop._read_v2_long_short_ratio_evidence(redis_client, "BANKUSDT")  # noqa: SLF001
    paper_loop._attach_long_short_ratio_context(intent, evidence)  # noqa: SLF001

    assert evidence == {}
    assert intent["long_short_ratio_status"] == "MISSING_V2_LONG_SHORT_RATIO"
    assert "long_short_ratio" not in intent


def test_attach_paper_execution_evidence_builds_pre_outcome_fill_metadata() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "entry_price_provenance_present": True,
        "entry_spread_decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.100Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 100.0,
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "actual_observed_spread_entry_bps": 1.2,
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence": 0.0003,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T13:00:00.000Z",
    }

    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["latency_source"] == "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"
    assert intent["maker_probability"] == 0.0
    assert intent["taker_probability"] == 1.0
    assert intent["maker_taker_probability_source"] == (
        "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE"
    )
    assert intent["partial_fill_count"] == 1
    assert intent["fill_count"] == 1
    assert intent["partial_fills"][0]["paper_only"] is True
    assert intent["partial_fills"][0]["places_real_order"] is False
    assert intent["mark_price"] == 100.03
    assert intent["index_price"] == 100.0
    assert intent["mark_index_source"] == mark_index["mark_index_source"]


def test_attach_paper_execution_evidence_uses_non_future_latency_source() -> None:
    intent = {
        "symbol": "AGTUSDT",
        "entry_price_provenance_present": True,
        "entry_spread_decision_time": "2026-06-22T13:00:00.251Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.250Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 0.020898,
        "quantity": 3762.351700169794,
        "notional_usdt": 78.62562583,
        "actual_observed_spread_entry_bps": 6.22,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["quantity"] == 3762.351700169794


def test_attach_paper_execution_evidence_prefers_feature_decision_over_spread_capture() -> None:
    intent = {
        "symbol": "AGTUSDT",
        "entry_price_provenance_present": True,
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_spread_decision_time": "2026-06-22T13:00:00.100Z",
        "entry_spread_captured_at": "2026-06-22T13:00:00.100Z",
        "generated_utc": "2026-06-22T13:00:00.200Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 0.020898,
        "quantity": 3762.351700169794,
        "notional_usdt": 78.62562583,
        "actual_observed_spread_entry_bps": 6.22,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["latency_source"] == "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"


def test_attach_paper_execution_evidence_refreshes_partial_fill_after_size_change() -> None:
    intent = {
        "symbol": "DEXEUSDT",
        "entry_price_provenance_present": True,
        "decision_time": "2026-06-22T13:00:00.000Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 22.58,
        "quantity": 6.0,
        "notional_usdt": 135.48,
        "actual_observed_spread_entry_bps": 2.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    assert intent["partial_fills"][0]["quantity"] == 6.0
    assert intent["partial_fills"][0]["notional_usd"] == 135.48

    intent["quantity"] = 1.5
    intent["notional"] = 33.87
    intent["notional_usdt"] = 33.87

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["quantity"] == 1.5
    assert intent["partial_fills"][0]["notional_usd"] == 33.87
    assert intent["all_partial_fills"][0]["quantity"] == 1.5


def test_attach_paper_sizing_copies_target_fields_for_execution_evidence() -> None:
    intent = {
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.250Z",
        "entry_price_provenance_present": True,
        "actual_observed_spread_entry_bps": 1.2,
    }
    allocation = _allowed_allocation(
        adaptive_capital_policy_version="ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        recommended_leverage=2.0,
        effective_leverage=2.0,
        recommended_margin_mode="isolated_paper_simulated",
        stop_distance_bps=25.0,
        liquidation_price_estimate=50.0,
        liquidation_buffer_bps=9000.0,
        capital_allocation_reason="adaptive_allocation_from_test",
        final_size_reason="adaptive_allocation_from_test",
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_leverage": 2.0,
            "selected_margin_mode": "isolated_paper_simulated",
            "selected_hedge_budget_pct_of_risk": 0.1,
        },
    )

    paper_loop._attach_paper_sizing(intent, allocation)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["target_notional_usdt"] == 1000.0
    assert intent["target_notional_usd"] == 1000.0
    assert intent["target_quantity"] == 10.0
    assert intent["quantity"] == 10.0
    assert intent["notional_usdt"] == 1000.0
    assert intent["paper_sizing_complete"] is True
    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["notional_usd"] == 1000.0


def test_depth_price_impact_uses_orderbook_top5_vwap_after_sizing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "quantity": 2.0,
        "notional_usdt": 200.0,
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "best_bid": 99.99,
        "best_ask": 100.0,
        "mid_price": 99.995,
        "ask_depth_usd": 500.0,
        "bid_depth_usd": 600.0,
        "ask_levels_top5": [
            {"price": 100.0, "quantity": 1.0},
            {"price": 100.2, "quantity": 2.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 6.0},
        ],
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001

    assert intent["entry_orderbook_depth_usd"] == 500.0
    assert intent["entry_orderbook_depth_side"] == "ask"
    assert intent["depth_price_impact_bps"] == pytest.approx(10.0005)
    assert intent["depth_price_impact_source"] == (
        "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT:"
        "ask_levels_top5:top5_vwap_vs_touch"
    )
    assert intent["depth_price_impact_model"] == "ORDERBOOK_TOP5_VWAP_VS_TOUCH"
    assert intent["depth_price_impact_fill_complete"] is True
    assert intent["depth_utilization_pct"] == 0.4


def test_runtime_cost_capture_contract_marks_complete_production_grade_cost() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_generated_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_cutoff": "2026-06-22T12:45:00.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "entry_feature_candle_closed_confirmed": True,
        "feature_vector_hash": "fv-hash-1",
        "selected_action": "long",
        "expected_move_bps": 20.0,
        "expected_move_after_cost_bps": 12.0,
        "score": 0.72,
        "entry_price_provenance_present": True,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "entry_spread_decision_time": "2026-06-22T13:00:00.000Z",
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "fee_bps_readonly_schedule": False,
        "fee_bps_configured_schedule": True,
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "funding_interval_seconds": 28800,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "entry_price": 100.0,
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "orderbook_latency_ms": 25.0,
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "microstructure_trust_source": "v2:microstructure:trust_score:BANKUSDT:15m",
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert intent["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert intent["predicted_direction"] == "long"
    assert intent["predicted_move_bps"] == 20.0
    assert intent["score"] == 0.72
    assert intent["order_size"] == 250.0
    assert intent["gross_notional_usd"] == 250.0
    assert intent["allocated_margin_usd"] == 125.0
    assert intent["recommended_leverage"] == 2.0
    assert intent["effective_leverage"] == 2.0
    assert intent["recommended_margin_mode"] == "isolated_paper_simulated"
    assert intent["observed_bid"] == 99.99
    assert intent["observed_ask"] == 100.01
    assert intent["top_book_bid_depth_usd"] == 10000.0
    assert intent["top_book_ask_depth_usd"] == 12000.0
    assert intent["depth_derived_price_impact_bps"] == 0.0
    assert intent["maker_taker_assumption"] == "taker"
    assert intent["fee_schedule"]["fee_bps"] == 4.0
    assert intent["fee_schedule"]["readonly_schedule"] is False
    assert intent["holding_period_funding_bps"] == 0.5
    assert intent["latency_reserve_bps"] == 0.0
    assert intent["partial_fill_estimate"]["expected_fill_probability"] == 1.0
    assert intent["cost_source_family"] == "V2_MARKET_MICROSTRUCTURE_PAYLOAD"
    assert intent["cost_source_allowed"] is True
    assert intent["cost_source_timestamp"] == "2026-06-22T12:59:59.500Z"
    assert intent["cost_evidence_freshness_ms"] == 500.0
    assert intent["runtime_cost_capture_required_fields"] == list(
        paper_loop.PHASE2_RUNTIME_COST_CAPTURE_REQUIRED_FIELDS
    )
    assert "allocated_margin_usd" in intent["runtime_cost_capture_required_fields"]
    assert "effective_leverage" in intent["runtime_cost_capture_required_fields"]
    assert "expected_funding_bps" in intent["runtime_cost_capture_required_fields"]
    assert "production_grade_cost_flag" in intent["runtime_cost_capture_required_fields"]
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_source_reject_reasons"] == []
    assert intent["fallback_cost_flag"] is False
    assert intent["fallback"] is False
    assert intent["production_grade_cost_flag"] is True
    assert intent["routes_to_live"] is False
    assert intent["counts_as_a_grade_evidence"] is False
    assert intent["paper_canary_fixed_notional_allowed"] is False
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []  # noqa: SLF001
    assert intent["paper_policy_owner_open_allowed"] is True
    assert intent["adaptive_allocation"]["production_grade_cost_flag"] is True

    rows = paper_loop._current_cycle_candidate_allocation_rows(intents=[intent])  # noqa: SLF001
    assert rows[0]["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert rows[0]["predicted_direction"] == "long"
    assert rows[0]["production_grade_cost_flag"] is True
    assert rows[0]["routes_to_live"] is False


def _complete_runtime_cost_capture_intent_and_microstructure(
    *,
    microstructure_action: str,
    microstructure_trust_score: float,
    microstructure_adaptive_minimum: float = 0.65,
) -> tuple[dict[str, object], dict[str, object]]:
    intent: dict[str, object] = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "expected_move_bps": 20.0,
        "expected_move_after_cost_bps": 12.0,
        "score": 0.72,
        "entry_price_provenance_present": True,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "latency_reserve_bps": 0.0,
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "entry_price": 100.0,
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure: dict[str, object] = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "depth_derived_price_impact_bps": 0.0,
        "microstructure_trust_score": microstructure_trust_score,
        "microstructure_adaptive_minimum": microstructure_adaptive_minimum,
        "orderbook_trust_tier": (
            "REDUCED_SIZE" if microstructure_action == "REDUCE_SIZE" else "HIGH_TRUST"
        ),
        "microstructure_action": microstructure_action,
        "orderbook_latency_ms": 25.0,
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "microstructure_trust_source": "v2:microstructure:trust_score:BANKUSDT:15m",
    }
    return intent, market_microstructure


def test_runtime_cost_capture_allows_reduce_size_below_microstructure_minimum() -> None:
    intent, market_microstructure = _complete_runtime_cost_capture_intent_and_microstructure(
        microstructure_action="REDUCE_SIZE",
        microstructure_trust_score=0.52,
    )

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["microstructure_below_adaptive_minimum"] is True
    assert intent["runtime_cost_capture_microstructure_trust_policy"] == (
        "REDUCE_SIZE_BELOW_ADAPTIVE_MINIMUM"
    )
    assert intent["runtime_cost_capture_source_reject_reasons"] == []
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["production_grade_cost_flag"] is True
    assert intent["fallback_cost_flag"] is False
    assert intent["microstructure_gate_allows_a_grade"] is False
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []  # noqa: SLF001
    assert intent["paper_policy_owner_open_allowed"] is True


def test_runtime_cost_capture_rejects_allow_below_microstructure_minimum() -> None:
    intent, market_microstructure = _complete_runtime_cost_capture_intent_and_microstructure(
        microstructure_action="ALLOW",
        microstructure_trust_score=0.52,
    )

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["runtime_cost_capture_source_reject_reasons"] == [
        "MICROSTRUCTURE_TRUST_BELOW_ADAPTIVE_MINIMUM"
    ]
    assert intent["production_grade_cost_flag"] is False
    assert intent["fallback_cost_flag"] is True
    assert "source:MICROSTRUCTURE_TRUST_BELOW_ADAPTIVE_MINIMUM" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_direct_orderbook_features_feed_production_grade_cost_contract() -> None:
    fake = _FakeRedis(
        {
            "v2:orderbook:features:binance:ARBUSDT": {
                "schema_version": "direct_orderbook_features_v1",
                "source": "direct_binance",
                "exchange": "binance",
                "symbol": "ARBUSDT",
                "best_bid": 0.08044,
                "best_ask": 0.08045,
                "bid_ask_mid": 0.080445,
                "spread_bps": 1.2430853378,
                "available_at": "2026-06-22T12:59:59.500Z",
                "received_at": "2026-06-22T12:59:59.500Z",
                "event_time": "2026-06-22T12:59:59.000Z",
                "depth_5_bid_usd": 12559.017389,
                "depth_5_ask_usd": 7525.206321,
                "depth_20_bid_usd": 93566.472852,
                "depth_20_ask_usd": 89967.454721,
                "orderbook_depth_usd": 89967.454721,
                "microstructure_liquidity_depth": 89967.454721,
                "estimated_price_impact_bps": 1.6058845596,
            },
            "v2:microstructure:trust_score:ARBUSDT:1m": {
                "microstructure_trust_score": 0.82,
                "orderbook_trust_score": 0.82,
                "orderbook_trust_tier": "HIGH_TRUST",
                "microstructure_action": "ALLOW",
                "adaptive_minimum": 0.65,
                "orderbook_latency_ms": 35.0,
                "book_sequence_gap": False,
                "depth_persistence": 0.9,
                "cancel_pressure": 0.1,
                "trade_tape_confirmation_score": 0.8,
                "cross_venue_confirmation_score": 0.8,
                "sweep_risk_score": 0.1,
                "available_at": "2026-06-22T12:59:59.500Z",
                "decision_time": "2026-06-22T13:00:00.000Z",
            },
        }
    )
    market_microstructure = paper_loop._read_v2_orderbook_microstructure(  # noqa: SLF001
        fake,
        "ARBUSDT",
    )
    intent = {
        "symbol": "ARBUSDT",
        "timeframe": "1h",
        "side": "short",
        "strategy_id": "trend_mode",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "paper_admission_decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "selected_action": "short",
        "expected_move_bps": -20.0,
        "expected_move_after_cost_bps": -12.0,
        "score": 0.72,
        "entry_price": 0.08044,
        "fill_price": 0.08044,
        "quantity": 1000.0,
        "notional_usdt": 80.44,
        "gross_notional_usd": 80.44,
        "allocated_margin_usd": 40.22,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_slippage_bps": 0.620694,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "latency_reserve_bps": 0.0,
        "mark_index_divergence_bps": 0.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "adaptive_allocation": {},
    }

    assert market_microstructure["entry_spread_available_at"] == "2026-06-22T12:59:59.500Z"
    assert market_microstructure["bid_depth_usd"] == pytest.approx(12559.017389)
    assert market_microstructure["ask_depth_usd"] == pytest.approx(7525.206321)
    assert market_microstructure["market_depth_usd"] == pytest.approx(89967.454721)
    assert market_microstructure["depth_derived_price_impact_bps"] == pytest.approx(1.60588456)

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["cost_source"] == (
        "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:orderbook:features:binance:ARBUSDT"
    )
    assert intent["cost_source_timestamp"] == "2026-06-22T12:59:59.500Z"
    assert intent["top_book_bid_depth_usd"] == pytest.approx(12559.017389)
    assert intent["top_book_ask_depth_usd"] == pytest.approx(7525.206321)
    assert intent["market_depth_usd"] == pytest.approx(89967.454721)
    assert intent["depth_derived_price_impact_bps"] == pytest.approx(1.60588456)
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == []
    assert intent["production_grade_cost_flag"] is True


@pytest.mark.parametrize(
    ("source", "family"),
    [
        ("COINAPI_WSDS:book_depth:BANKUSDT", "COINAPI_WSDS_BOOK_DEPTH"),
        ("BINANCE_PUBLIC_BOOK_DEPTH:BANKUSDT", "BINANCE_PUBLIC_BOOK_DEPTH"),
        ("KUCOIN_PUBLIC_ORDERBOOK_DEPTH:BANKUSDT", "KUCOIN_PUBLIC_BOOK_DEPTH"),
        ("V2_TRADE_TERMINAL_ORDERBOOK_PAYLOAD", "V2_TRADE_TERMINAL_ORDERBOOK_PAYLOAD"),
        (
            "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
            "V2_MARKET_MICROSTRUCTURE_PAYLOAD",
        ),
    ],
)
def test_runtime_cost_capture_source_family_allows_approved_sources(
    source: str,
    family: str,
) -> None:
    actual_family, allowed = paper_loop._runtime_cost_capture_source_family(  # noqa: SLF001
        source
    )

    assert actual_family == family
    assert allowed is True


def test_runtime_cost_capture_rejects_disallowed_cost_source_family() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "observed_bid": 99.99,
        "observed_ask": 100.01,
        "observed_spread_bps": 2.0,
        "top_book_bid_depth_usd": 10000.0,
        "top_book_ask_depth_usd": 12000.0,
        "market_depth_usd": 10000.0,
        "depth_derived_price_impact_bps": 0.0,
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_slippage_bps": 0.8,
        "expected_funding_bps": 0.5,
        "latency_reserve_bps": 0.0,
        "mark_index_divergence_bps": 0.0,
        "cost_source": "LEGACY_PAPER_RUNTIME_FAKE_COST",
        "cost_source_timestamp": "2026-06-22T12:59:59.500Z",
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "orderbook_latency_ms": 25.0,
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "microstructure_trust_source": "v2:microstructure:trust_score:BANKUSDT:15m",
        "adaptive_allocation": {},
    }

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        {},
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["cost_source_allowed"] is False
    assert "cost_source_family" not in intent
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_source_reject_reasons"] == [
        "DISALLOWED_COST_SOURCE"
    ]
    assert intent["production_grade_cost_flag"] is False
    assert intent["fallback_cost_flag"] is True
    assert "source:DISALLOWED_COST_SOURCE" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_runtime_cost_capture_rejects_orderbook_timestamp_after_feature_decision() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "entry_spread_decision_time": "2026-06-22T13:05:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:05:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T13:00:05.000Z",
        "entry_spread_captured_at": "2026-06-22T13:05:00.000Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "orderbook_latency_ms": 25.0,
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "microstructure_trust_source": "v2:microstructure:trust_score:BANKUSDT:15m",
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["cost_source_timestamp"] == "2026-06-22T13:00:05.000Z"
    assert intent["runtime_cost_capture_decision_time"] == "2026-06-22T13:00:00.000Z"
    assert intent["cost_evidence_freshness_ms"] == -5000.0
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == [
        "COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME"
    ]
    assert intent["production_grade_cost_flag"] is False
    assert intent["fallback_cost_flag"] is True
    assert "temporal:COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_runtime_cost_capture_uses_explicit_paper_admission_decision_time() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "paper_admission_decision_time": "2026-06-22T13:05:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:05:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T13:00:05.000Z",
        "entry_spread_captured_at": "2026-06-22T13:05:00.000Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "orderbook_latency_ms": 25.0,
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "microstructure_trust_source": "v2:microstructure:trust_score:BANKUSDT:15m",
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["model_decision_time"] == "2026-06-22T13:00:00.000Z"
    assert intent["runtime_cost_capture_decision_time"] == "2026-06-22T13:05:00.000Z"
    assert intent["cost_source_timestamp"] == "2026-06-22T13:00:05.000Z"
    assert intent["cost_evidence_freshness_ms"] == 295000.0
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == []
    assert intent["production_grade_cost_flag"] is True
    assert intent["fallback_cost_flag"] is False
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []  # noqa: SLF001


def test_runtime_cost_capture_derives_orderbook_latency_from_pit_cost_timestamps() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "paper_admission_decision_time": "2026-06-22T13:00:00.000Z",
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "observed_bid": 99.99,
        "observed_ask": 100.01,
        "observed_spread_bps": 2.0,
        "top_book_bid_depth_usd": 10000.0,
        "top_book_ask_depth_usd": 12000.0,
        "market_depth_usd": 10000.0,
        "depth_derived_price_impact_bps": 0.0,
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_slippage_bps": 0.8,
        "expected_funding_bps": 0.5,
        "latency_reserve_bps": 0.0,
        "mark_index_divergence_bps": 0.0,
        "cost_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "cost_source_timestamp": "2026-06-22T12:59:59.500Z",
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "adaptive_allocation": {},
    }

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        {},
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["cost_evidence_freshness_ms"] == 500.0
    assert intent["orderbook_latency_ms"] == 500.0
    assert intent["orderbook_latency_source"] == (
        "DERIVED_FROM_COST_SOURCE_TIMESTAMP_AND_RUNTIME_DECISION_TIME"
    )
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == []
    assert intent["production_grade_cost_flag"] is True


def test_runtime_cost_capture_does_not_derive_latency_from_future_cost_timestamp() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "paper_admission_decision_time": "2026-06-22T13:00:00.000Z",
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "observed_bid": 99.99,
        "observed_ask": 100.01,
        "observed_spread_bps": 2.0,
        "top_book_bid_depth_usd": 10000.0,
        "top_book_ask_depth_usd": 12000.0,
        "market_depth_usd": 10000.0,
        "depth_derived_price_impact_bps": 0.0,
        "maker_taker_assumption": "taker",
        "maker_taker_probability": 1.0,
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_slippage_bps": 0.8,
        "expected_funding_bps": 0.5,
        "latency_reserve_bps": 0.0,
        "mark_index_divergence_bps": 0.0,
        "cost_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "cost_source_timestamp": "2026-06-22T13:00:00.500Z",
        "microstructure_trust_score": 0.82,
        "microstructure_adaptive_minimum": 0.65,
        "orderbook_trust_tier": "HIGH_TRUST",
        "microstructure_action": "ALLOW",
        "book_sequence_gap": False,
        "book_depth_persistence_score": 0.9,
        "book_cancel_pressure_score": 0.1,
        "trade_tape_confirmation_score": 0.8,
        "cross_venue_confirmation_score": 0.8,
        "sweep_risk_score": 0.1,
        "adaptive_allocation": {},
    }

    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        {},
        signal={"policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["cost_evidence_freshness_ms"] == -500.0
    assert "orderbook_latency_ms" not in intent
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == [
        "COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME"
    ]
    assert intent["production_grade_cost_flag"] is False


def test_runtime_cost_capture_prefers_final_paper_notional_for_order_size() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "side": "long",
        "order_size": 1000.0,
        "order_size_usd": 1000.0,
        "gross_notional_usd": 250.0,
        "notional_usdt": 250.0,
    }

    paper_loop._attach_runtime_cost_capture_contract(intent, {})  # noqa: SLF001

    assert intent["order_size"] == 250.0
    assert intent["order_size_usd"] == 250.0


def test_runtime_cost_capture_contract_fallback_rows_do_not_pass_challenger_owner_gate() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "no_trade_monitor",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_price_provenance_present": True,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "mark_index_divergence_bps": 0.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(intent, {})  # noqa: SLF001
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["fallback_cost_flag"] is True
    assert intent["production_grade_cost_flag"] is False
    assert "observed_bid" in intent["runtime_cost_capture_missing_fields"]
    assert "allocated_margin_usd" in intent["runtime_cost_capture_missing_fields"]
    assert "recommended_leverage" in intent["runtime_cost_capture_missing_fields"]
    assert "effective_leverage" in intent["runtime_cost_capture_missing_fields"]
    assert "recommended_margin_mode" in intent["runtime_cost_capture_missing_fields"]
    assert "top_book_bid_depth_usd" in intent["runtime_cost_capture_missing_fields"]
    assert "depth_derived_price_impact_bps" in intent["runtime_cost_capture_missing_fields"]
    assert "cost_source_timestamp" in intent["runtime_cost_capture_missing_fields"]
    assert "CHALLENGER_COST_CAPTURE_NOT_PRODUCTION_GRADE" in reasons
    assert "missing:observed_bid" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_runtime_cost_capture_marks_zero_size_no_trade_rows_complete_without_training_credit() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "no_trade_monitor",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "paper_opportunity_tier": paper_loop.PAPER_TIER_NO_TRADE,
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "mark_index_divergence_bps": 0.0,
    }
    market_microstructure = {
        "source": "V2_TRADE_TERMINAL_ORDERBOOK_PAYLOAD",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_ask_spread_bps": 2.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
    )

    assert intent["production_grade_cost_flag"] is True
    assert intent["fallback_cost_flag"] is False
    assert intent["counts_as_production_grade_training_evidence"] is False
    assert intent["runtime_cost_capture_order_cost_applicable"] is False
    assert intent["runtime_cost_capture_no_order_reason"] == "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_explained_missing_fields"] == []
    assert intent["runtime_cost_capture_unexplained_missing_fields"] == []
    assert intent["depth_derived_price_impact_bps"] == 0.0
    assert intent["depth_price_impact_source"] == "NO_ORDER_ZERO_SIZE_NO_MARKET_IMPACT"
    assert intent["paper_canary_fixed_notional_allowed"] is False
    assert intent["routes_to_live"] is False
    assert intent["places_real_order"] is False


def test_runtime_cost_capture_explains_no_order_missing_cost_without_production_credit() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "paper_opportunity_tier": paper_loop.PAPER_TIER_NO_TRADE,
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(intent, {})  # noqa: SLF001

    assert intent["runtime_cost_capture_order_cost_applicable"] is False
    assert intent["runtime_cost_capture_no_order_reason"] == "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    assert intent["runtime_cost_capture_missing_fields"]
    assert intent["runtime_cost_capture_explained_missing_fields"] == intent[
        "runtime_cost_capture_missing_fields"
    ]
    assert intent["runtime_cost_capture_unexplained_missing_fields"] == []
    assert intent["fallback_cost_flag"] is True
    assert intent["production_grade_cost_flag"] is False
    assert intent["production_grade_cost_evidence"] is False
    assert intent["counts_as_production_grade_training_evidence"] is False
    assert intent["routes_to_live"] is False
    assert intent["places_real_order"] is False
    assert intent["paper_canary_fixed_notional_allowed"] is False


def test_old_policy_owner_cannot_open_new_economic_paper_fills() -> None:
    intent = {
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_OLD_POLICY,
        "production_grade_cost_flag": True,
    }

    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert reasons == ["OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"]
    assert intent["paper_policy_owner_open_allowed"] is False
    assert intent["paper_policy_owner_open_block_reason"] == "OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"


def test_missing_runtime_owner_identity_cannot_open_new_economic_paper_fills() -> None:
    intent = {
        "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        "production_grade_cost_flag": True,
        "routes_to_live": False,
        "places_real_order": False,
    }

    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert reasons[0] == paper_loop.PAPER_RUNTIME_OWNER_BLOCK_REASON
    assert "paper_policy_owner_missing" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False
    assert intent["paper_policy_owner_open_block_reason"] == paper_loop.PAPER_RUNTIME_OWNER_BLOCK_REASON


def test_mismatched_runtime_owner_identity_cannot_open_new_economic_paper_fills() -> None:
    intent = {
        "candidate_id": "paper_online_runtime",
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        "production_grade_cost_flag": True,
        "routes_to_live": False,
        "places_real_order": False,
    }

    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert reasons[0] == paper_loop.PAPER_RUNTIME_OWNER_BLOCK_REASON
    assert "candidate_id_mismatch:paper_online_runtime" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False
    assert intent["paper_runtime_owner_rejection_reasons"] == [
        "candidate_id_mismatch:paper_online_runtime"
    ]


def test_missing_owner_attribution_rows_are_explicit_pre_cutover_not_challenger_credit() -> None:
    row = {
        "fill_id": "fill-pre-cutover",
        "ledger_row_id": "fill-pre-cutover",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision": "ACCEPTED_PAPER_FILL",
        "counts_as_a_grade_evidence": True,
        "a_grade_promotion_allowed": True,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001
    compact = paper_loop._compact_accepted_fill_for_state(normalized)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER
    assert normalized["policy_fingerprint"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is False
    assert set(normalized["paper_owner_attribution_missing_fields"]) == {
        "candidate_id",
        "model_source",
        "paper_policy_owner",
        "policy_fingerprint",
        "policy_id",
    }
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is True
    assert normalized["counts_as_a_grade_evidence"] is False
    assert normalized["a_grade_promotion_allowed"] is False
    assert normalized["challenger_credit_allowed"] is False
    assert compact["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert compact["paper_owner_attribution_status"] == "INCOMPLETE_OR_PRE_CUTOVER_OWNER_ATTRIBUTION"


def test_pre_cutover_owner_attribution_does_not_keep_challenger_model_identity() -> None:
    row = {
        "fill_id": "fill-old-normalized",
        "ledger_row_id": "fill-old-normalized",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID,
        "policy_id": paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER
    assert normalized["policy_fingerprint"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is False
    assert normalized["paper_owner_attribution_missing_fields"] == ["pre_cutover_owner_attribution"]
    assert normalized["counts_as_a_grade_evidence"] is False


def test_active_cuda_owner_attribution_rewrites_stale_frozen_candidate_id() -> None:
    row = {
        "fill_id": "fill-stale-frozen-candidate",
        "ledger_row_id": "fill-stale-frozen-candidate",
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "short",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": paper_loop.CHALLENGER_V2_FROZEN_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_FROZEN_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["policy_fingerprint"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.CHALLENGER_V2_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is True
    assert normalized["paper_owner_attribution_missing_fields"] == []
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is False


def test_active_cuda_owner_attribution_keeps_unknown_candidate_mismatch_blocked() -> None:
    row = {
        "fill_id": "fill-unknown-candidate",
        "ledger_row_id": "fill-unknown-candidate",
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "short",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": "challenger_v2_unknown_candidate",
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == "challenger_v2_unknown_candidate"
    assert normalized["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["paper_owner_attribution_complete"] is False
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is True
    assert normalized["counts_as_a_grade_evidence"] is False
    assert normalized["challenger_credit_allowed"] is False


def test_owner_attribution_status_allows_current_challenger_and_quarantines_history() -> None:
    current = paper_loop._normalize_paper_owner_attribution(  # noqa: SLF001
        {
            "fill_id": "fill-current",
            "ledger_row_id": "fill-current",
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "side": "short",
            "decision": "ACCEPTED_PAPER_FILL",
            "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
            "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
            "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        }
    )
    historical = paper_loop._normalize_paper_owner_attribution(  # noqa: SLF001
        {
            "fill_id": "fill-pre-cutover",
            "ledger_row_id": "fill-pre-cutover",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "side": "long",
            "decision": "ACCEPTED_PAPER_FILL",
        }
    )

    status = paper_loop._paper_owner_attribution_status(  # noqa: SLF001
        [historical, current],
        current_accepted_rows=[current],
    )

    assert status["status"] == "PASS_CURRENT_ACCEPTED_OWNER_ATTRIBUTION"
    assert status["current_accepted_count"] == 1
    assert status["current_incomplete_count"] == 0
    assert status["persistent_incomplete_or_pre_cutover_count"] == 1
    assert status["current_owner_counts"] == {paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2: 1}
    assert status["persistent_owner_counts"][paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER] == 1
    assert status["pre_cutover_rows_block_challenger_credit"] is True


def test_owner_attribution_status_validates_current_runtime_rows_without_current_fills() -> None:
    current_intent = {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "side": "short",
        "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    status = paper_loop._paper_owner_attribution_status(  # noqa: SLF001
        [],
        current_accepted_rows=[],
        current_runtime_rows=[current_intent],
    )

    assert status["status"] == "PASS_CURRENT_RUNTIME_OWNER_ATTRIBUTION_NO_ACCEPTED_FILLS"
    assert status["accepted_fill_status"] == "NO_CURRENT_ACCEPTED_ROWS_TO_VERIFY"
    assert status["current_runtime_row_count"] == 1
    assert status["current_runtime_complete_count"] == 1
    assert status["current_runtime_owner_contract_passed"] is True
    assert status["current_runtime_owner_counts"] == {
        paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2: 1
    }


def test_paper_policy_owner_handoff_runtime_proof_passes_current_challenger_path() -> None:
    current_intent = {
        "intent_id": "intent-current",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "side": "short",
        "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        "paper_fill_allowed": True,
        "production_grade_cost_flag": True,
        "production_grade_cost_evidence": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    fill = {
        **current_intent,
        "fill_id": "fill-current",
        "decision": "ACCEPTED_PAPER_FILL",
    }
    close = {
        **fill,
        "close_id": "close-current",
        "paper_fill_allowed": False,
    }
    outcome = {
        **fill,
        "outcome_label_id": "outcome-current",
        "paper_fill_allowed": False,
    }

    proof = paper_loop._paper_policy_owner_handoff_runtime_proof(  # noqa: SLF001
        current_runtime_rows=[current_intent],
        current_accepted_rows=[fill],
        accepted_rows=[fill],
        closed_rows=[close],
        outcome_label_rows=[outcome],
        shadow_rows=[{"paper_fill_allowed": False, "decision": "SHADOW_ONLY"}],
    )

    assert proof["status"] == "PASSED_PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF"
    assert proof["paper_new_entry_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert proof["new_old_policy_entry_count"] == 0
    assert proof["new_challenger_candidate_count"] == 1
    assert proof["new_challenger_intent_count"] == 1
    assert proof["new_challenger_accepted_fill_count"] == 1
    assert proof["challenger_identity_preserved_to_outcome"] is True
    assert proof["shadow_economic_fill_count"] == 0
    assert proof["fallback_challenger_fill_count"] == 0
    assert all(proof["pass_conditions"].values())


def test_paper_policy_owner_handoff_runtime_proof_blocks_old_policy_or_missing_identity() -> None:
    old_policy_intent = {
        "intent_id": "intent-old",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_OLD_POLICY,
        "paper_fill_allowed": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    challenger_intent = {
        "intent_id": "intent-challenger",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "side": "short",
        "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        "paper_fill_allowed": True,
        "production_grade_cost_flag": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    incomplete_challenger_close = {
        "close_id": "close-missing-identity",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "side": "short",
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
    }

    proof = paper_loop._paper_policy_owner_handoff_runtime_proof(  # noqa: SLF001
        current_runtime_rows=[old_policy_intent, challenger_intent],
        current_accepted_rows=[],
        accepted_rows=[],
        closed_rows=[incomplete_challenger_close],
        outcome_label_rows=[],
        shadow_rows=[{"decision": "ACCEPTED_PAPER_FILL", "paper_fill_allowed": True}],
    )

    assert proof["status"] == "BLOCKED_PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF"
    assert proof["new_old_policy_entry_count"] == 1
    assert proof["new_challenger_candidate_count"] == 1
    assert proof["challenger_identity_missing_lifecycle_rows"] == 1
    assert proof["challenger_identity_preserved_to_outcome"] is False
    assert proof["shadow_economic_fill_count"] == 1
    assert proof["pass_conditions"]["new_old_policy_entry_count_zero"] is False
    assert proof["pass_conditions"]["challenger_identity_preserved_to_outcome"] is False
    assert proof["pass_conditions"]["shadow_rows_never_become_economic_fills"] is False


def test_runtime_market_evidence_requires_execution_evidence_fields() -> None:
    base_intent = {
        "entry_price_provenance_present": True,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_generated_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "actual_observed_spread_entry_bps": 1.2,
        "bid_ask_spread_bps_fallback": False,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_bps_fallback": False,
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "expected_funding_bps": 1.5,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "orderbook_depth_usd": 10000.0,
        "orderbook_depth_source": "orderbook_top5",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE",
        "latency_ms": 250.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "maker_taker_probability_source": "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE",
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 2.5, "price": 100.0}],
        "mark_price": 100.03,
        "index_price": 100.0,
    }

    assert paper_loop._paper_runtime_market_evidence_rejection_reasons(base_intent) == []  # noqa: SLF001

    missing_mark_index = dict(base_intent)
    missing_mark_index.pop("mark_price")
    reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(missing_mark_index)  # noqa: SLF001

    assert "MISSING_MARK_INDEX_DIVERGENCE_EVIDENCE" in reasons

    missing_cost_provenance = dict(base_intent)
    missing_cost_provenance.pop("fee_bps")
    missing_cost_provenance.pop("expected_funding_bps_source")
    missing_cost_provenance["orderbook_depth_usd"] = None
    reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(missing_cost_provenance)  # noqa: SLF001

    assert "MISSING_EXPLICIT_FEE_BPS_AT_DECISION_TIME" in reasons
    assert "MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME" in reasons
    assert "MISSING_MARKET_DEPTH_EVIDENCE" in reasons


def test_prefill_market_evidence_does_not_require_partial_fill_ledger() -> None:
    candidate = {
        "entry_price_provenance_present": True,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_generated_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "actual_observed_spread_entry_bps": 1.2,
        "bid_ask_spread_bps_fallback": False,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_bps_fallback": False,
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "expected_funding_bps": 1.5,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "orderbook_depth_usd": 10000.0,
        "orderbook_depth_source": "orderbook_top5",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE",
        "latency_ms": 250.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "maker_taker_probability_source": "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE",
        "mark_price": 100.03,
        "index_price": 100.0,
    }

    prefill_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(  # noqa: SLF001
        candidate,
        require_fill_ledger=False,
    )
    postfill_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(candidate)  # noqa: SLF001

    assert prefill_reasons == []
    assert "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE" in postfill_reasons


def test_b_grade_model_quality_status_computes_metrics_by_context_bucket(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    rows = [
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 10.0,
            "realized_net_pnl_bps": 12.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "short",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.7,
            "expected_move_after_cost_bps": -8.0,
            "realized_net_pnl_bps": -6.0,
            "directional_outcome": "UP",
            "action_was_profitable": False,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "ETHUSDT",
            "timeframe": "5m",
            "selected_action": "short",
            "strategy_id": "breakout",
            "market_regime_at_entry": "bear",
            "confidence_calibrated": 0.6,
            "expected_move_after_cost_bps": 5.0,
            "realized_net_pnl_bps": 4.0,
            "directional_outcome": "DOWN",
            "action_was_profitable": True,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "SHADOW_ONLY",
            "realized_net_pnl_bps": 99.0,
        },
    ]

    status = paper_loop._paper_b_grade_model_quality_status(rows)  # noqa: SLF001

    assert status["status"] == "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS"
    assert status["generated_utc"] == "2026-06-22T13:30:00Z"
    assert status["scope"] == "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY"
    assert status["counts_as_a_grade_evidence"] is False
    assert status["a_grade_promotion_allowed"] is False
    assert status["sample_count"] == 3
    assert status["b_grade_closed_outcome_count"] == 3
    assert status["rows_rejected_by_reason"] == {"NOT_B_GRADE_EXPLORATION_OUTCOME": 1}
    assert status["directional_accuracy"] == pytest.approx(2 / 3)
    assert status["expected_move_mae"] == pytest.approx(5 / 3)
    assert status["brier_score"] == pytest.approx(0.23)
    assert status["precision"] == pytest.approx(2 / 3)
    assert status["recall"] is None
    assert status["false_positive_rate"] == pytest.approx(1 / 3)
    assert status["after_cost_expectancy_bps"] == pytest.approx(10 / 3)
    assert status["expectancy_95pct_lower_confidence_bound_bps"] < 0.0
    assert status["win_rate_after_cost"] == pytest.approx(2 / 3)
    assert status["win_rate_95pct_lower_confidence_bound"] < 0.90
    assert status["profit_factor"] == pytest.approx(16 / 6)
    assert status["trade_outcome_counts"] == {"WIN": 2, "LOSS": 1, "BREAKEVEN": 0}
    buckets = status["metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket"]
    assert status["metrics_by_bucket"] == buckets
    assert status["bucket_count"] == 3
    assert status["published_bucket_count"] == 3
    assert status["metric_summary"]["bucket_count"] == 3
    assert status["metric_summary"]["published_bucket_count"] == 3
    assert status["metric_summary"]["directional_accuracy"] == pytest.approx(2 / 3)
    assert status["metric_summary"]["after_cost_expectancy_bps"] == pytest.approx(10 / 3)
    assert {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "strategy": "trend",
        "regime": "bull",
        "confidence_bucket": "0.8-0.9",
    }.items() <= buckets[0].items()

    readiness = paper_loop._paper_b_grade_bucket_promotion_readiness_status(status)  # noqa: SLF001
    assert readiness["status"] == "BLOCKED_B_GRADE_BUCKETS_NOT_A_GRADE_READY"
    assert readiness["counts_as_a_grade_evidence"] is False
    assert readiness["a_grade_promotion_allowed"] is False
    assert readiness["metric_ready_bucket_count"] == 0
    assert readiness["a_grade_promotable_bucket_count"] == 0
    assert readiness["blocker_counts"]["INSUFFICIENT_BUCKET_SAMPLE_COUNT"] == 3
    assert readiness["blocker_counts"]["WIN_RATE_95PCT_LCB_BELOW_90P"] == 3
    fragmentation = readiness["evidence_fragmentation_status"]
    assert fragmentation["status"] == "BLOCKED_FRAGMENTED_B_GRADE_EVIDENCE"
    assert fragmentation["bucket_count"] == 3
    assert fragmentation["insufficient_sample_bucket_count"] == 3
    assert fragmentation["buckets_at_or_above_minimum_count"] == 0
    assert fragmentation["sample_count_deficit_to_minimum_total"] == 87
    assert fragmentation["sample_count_distribution"]["1"] == 3
    assert fragmentation["paper_only_label_collection_priority_bucket_count"] == 2
    priority = readiness["paper_only_label_collection_priority_buckets"]
    assert len(priority) == 2
    assert all(bucket["paper_only"] is True for bucket in priority)
    assert all(bucket["places_real_order"] is False for bucket in priority)
    assert all(bucket["counts_as_a_grade_evidence"] is False for bucket in priority)
    assert all(bucket["a_grade_promotion_allowed"] is False for bucket in priority)
    assert all(
        bucket["priority_reason"]
        == "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
        for bucket in priority
    )
    assert all(
        bucket["a_grade_execution_tier_if_candidate_now"] == "SHADOW_ONLY"
        for bucket in readiness["buckets"]
    )
    assert all(bucket["counts_as_a_grade_evidence"] is False for bucket in readiness["buckets"])


def test_trainer_model_quality_runtime_status_publishes_phase_9_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:45:00Z")
    quality = paper_loop._paper_b_grade_model_quality_status([  # noqa: SLF001
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 10.0,
            "realized_net_pnl_bps": 12.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "ETHUSDT",
            "timeframe": "5m",
            "selected_action": "short",
            "strategy_id": "breakout",
            "market_regime_at_entry": "bear",
            "confidence_calibrated": 0.7,
            "expected_move_after_cost_bps": 8.0,
            "realized_net_pnl_bps": 6.0,
            "directional_outcome": "DOWN",
            "action_was_profitable": True,
        },
    ])
    status = paper_loop._paper_trainer_model_quality_runtime_status(  # noqa: SLF001
        quality,
        {
            "checkpoint": {
                "checkpoint_id": "ckpt-1",
                "weight_blob_written": True,
            },
            "checkpoint_reload_verified": True,
            "training": {
                "metrics": {
                    "trusted_rows_loaded": 42,
                    "optimizer_steps_last_hour": 7,
                    "parameter_hash_before": "before",
                    "parameter_hash_after": "after",
                    "checkpoint_reload_verified": True,
                }
            },
        },
    )

    assert status["schema_version"] == "paper_trainer_model_quality_runtime_status_v1"
    assert status["status"] == "PASSED_CURRENT_MODEL_QUALITY_PUBLISHED_A_GRADE_BLOCKED"
    assert status["generated_utc"] == "2026-06-22T13:45:00Z"
    assert status["weights_update"] is True
    assert status["quality_metrics_current"] is True
    assert status["trusted_rows_loaded"] == 42
    assert status["optimizer_steps_last_hour"] == 7
    assert status["parameter_hash_changed"] is True
    assert status["checkpoint_written"] is True
    assert status["checkpoint_reload_verified"] is True
    assert status["directional_accuracy"] == pytest.approx(1.0)
    assert status["expected_move_mae_bps"] == pytest.approx(2.0)
    assert status["Brier"] == pytest.approx(0.065)
    assert status["ECE"] == pytest.approx(0.25)
    assert status["false_positive_rate"] == 0.0
    assert status["after_cost_expectancy_bps"] == pytest.approx(9.0)
    assert status["pass_conditions"]["accuracy_gt_baseline"] is True
    assert status["pass_conditions"]["after_cost_expectancy_positive"] is True
    assert status["accuracy_by_symbol"][0]["symbol"] == "BTCUSDT"
    assert status["accuracy_by_tf"][0]["timeframe"] == "1m"
    assert {row["side"] for row in status["accuracy_by_side"]} == {"long", "short"}
    assert {row["strategy"] for row in status["accuracy_by_strategy"]} == {
        "breakout",
        "trend",
    }
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False
    assert status["a_grade_promotion_allowed"] is False
    assert status["ready_allowed"] is False


def test_b_grade_bucket_promotion_readiness_never_promotes_learning_only_bucket(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T14:30:00Z")
    rows = [
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.97,
            "expected_move_after_cost_bps": 11.0,
            "realized_net_pnl_bps": 12.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
        }
        for _ in range(120)
    ]

    quality = paper_loop._paper_b_grade_model_quality_status(rows)  # noqa: SLF001
    readiness = paper_loop._paper_b_grade_bucket_promotion_readiness_status(quality)  # noqa: SLF001

    assert quality["profit_factor"] == "inf"
    assert readiness["source_bucket_count"] == 1
    assert readiness["metric_ready_bucket_count"] == 1
    assert readiness["a_grade_promotable_bucket_count"] == 0
    assert readiness["evidence_fragmentation_status"]["status"] == (
        "READY_B_GRADE_BUCKET_SAMPLE_COVERAGE"
    )
    assert readiness["evidence_fragmentation_status"]["insufficient_sample_bucket_count"] == 0
    assert readiness["paper_only_label_collection_priority_buckets"] == []
    bucket = readiness["buckets"][0]
    assert bucket["bucket_metric_conditions_pass"] is True
    assert bucket["metric_blocker_reasons"] == []
    assert bucket["profit_factor_is_infinite"] is True
    assert bucket["counts_as_a_grade_evidence"] is False
    assert bucket["a_grade_promotion_allowed"] is False
    assert bucket["a_grade_execution_tier_if_candidate_now"] == "SHADOW_ONLY"
    assert "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE" in bucket[
        "promotion_blocker_reasons"
    ]
    assert "UNTOUCHED_HOLDOUT_AND_FROZEN_POLICY_NOT_VERIFIED_FOR_BUCKET" in bucket[
        "promotion_blocker_reasons"
    ]


def test_b_grade_exploration_budget_fraction_uses_uncertainty_and_drawdown() -> None:
    low_confidence = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.55,
        drawdown_bps=0.0,
    )
    higher_confidence = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.70,
        drawdown_bps=0.0,
    )
    drawdown_reduced = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.70,
        drawdown_bps=400.0,
    )

    assert 0.0 < low_confidence["risk_budget_fraction_of_normal_adaptive"]
    assert (
        low_confidence["risk_budget_fraction_of_normal_adaptive"]
        < higher_confidence["risk_budget_fraction_of_normal_adaptive"]
        <= paper_loop.B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
    )
    assert (
        0.0
        < drawdown_reduced["risk_budget_fraction_of_normal_adaptive"]
        < higher_confidence["risk_budget_fraction_of_normal_adaptive"]
    )


def test_b_grade_exploration_budget_fraction_adaptive_floor_is_fail_closed() -> None:
    base = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.55,
        drawdown_bps=0.0,
    )
    pressured = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.52,
        drawdown_bps=450.0,
        expected_move_after_cost_bps=6.0,
        observed_spread_bps=4.0,
        expected_slippage_bps=3.0,
        fee_bps=4.0,
        depth_utilization_pct=0.40,
        long_short_ratio_status="REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION",
    )

    assert base["b_grade_exploration_static_confidence_floor"] == 0.5
    assert base["b_grade_exploration_adaptive_confidence_floor"] == 0.5
    assert base["b_grade_exploration_confidence_floor_pass"] is True
    assert pressured["b_grade_exploration_adaptive_confidence_floor"] > 0.5
    assert pressured["b_grade_exploration_floor_never_below_static"] is True
    assert pressured["b_grade_exploration_confidence_floor_pass"] is False
    assert pressured["risk_budget_fraction_of_normal_adaptive"] == 0.0
    assert pressured["b_grade_exploration_budget_formula"] == (
        "confidence_below_adaptive_b_grade_exploration_floor"
    )
    penalties = pressured["b_grade_exploration_floor_penalties"]
    assert penalties["drawdown_pressure"] > 0.0
    assert penalties["cost_edge_pressure"] > 0.0
    assert penalties["depth_pressure"] > 0.0
    assert penalties["long_short_point_in_time_pressure"] > 0.0


def test_paper_signal_adaptive_stale_policy_never_relaxes_static_cap() -> None:
    one_minute = paper_loop._paper_signal_adaptive_stale_policy(  # noqa: SLF001
        {"timeframe": "1m"}
    )
    five_minute = paper_loop._paper_signal_adaptive_stale_policy(  # noqa: SLF001
        {"timeframe": "5m"}
    )
    higher_timeframe = paper_loop._paper_signal_adaptive_stale_policy(  # noqa: SLF001
        {"timeframe": "4h"}
    )
    missing_timeframe = paper_loop._paper_signal_adaptive_stale_policy({})  # noqa: SLF001

    assert one_minute["adaptive_stale_seconds"] == 180
    assert one_minute["adaptive_stricter_than_static"] is True
    assert five_minute["adaptive_stale_seconds"] == paper_loop.PAPER_SIGNAL_STALE_SECONDS
    assert higher_timeframe["adaptive_stale_seconds"] == paper_loop.PAPER_SIGNAL_STALE_SECONDS
    assert missing_timeframe["adaptive_stale_seconds"] == paper_loop.PAPER_SIGNAL_STALE_SECONDS
    for policy in (one_minute, five_minute, higher_timeframe, missing_timeframe):
        assert policy["adaptive_never_above_static"] is True
        assert policy["threshold_lowering_to_force_trades"] is False


def test_paper_signal_temporal_rejection_uses_adaptive_stale_seconds() -> None:
    now = datetime(2026, 6, 29, 2, 0, tzinfo=timezone.utc)

    one_minute_reasons = paper_loop._paper_signal_temporal_rejection_reasons(  # noqa: SLF001
        signal={
            "timeframe": "1m",
            "generated_utc": "2026-06-29T01:56:00Z",
        },
        prediction={},
        now=now,
    )
    higher_timeframe_reasons = paper_loop._paper_signal_temporal_rejection_reasons(  # noqa: SLF001
        signal={
            "timeframe": "4h",
            "generated_utc": "2026-06-29T01:56:00Z",
        },
        prediction={},
        now=now,
    )

    assert one_minute_reasons == ["STALE_SIGNAL_GT_180s_ADAPTIVE"]
    assert higher_timeframe_reasons == []


def test_adaptive_threshold_runtime_status_counts_b_grade_floor_blocks() -> None:
    rows = [
        {
            "symbol": "BANKUSDT",
            "timeframe": "1m",
            "side": "long",
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": 18.0,
            "actual_observed_spread_entry_bps": 1.0,
            "expected_slippage_bps": 1.0,
            "fee_bps": 4.0,
            "depth_utilization_pct": 0.01,
            "long_short_ratio_status": "V2_LONG_SHORT_RATIO_ATTACHED",
            "paper_drawdown_recovery_guard": {
                "adaptive_confidence_policy": {
                    "threshold_id": "paper_drawdown_recovery_min_confidence",
                    "static_floor": 0.65,
                    "dynamic_floor": 0.65,
                    "threshold_lowering_to_force_trades": False,
                    "never_below_static": True,
                },
            },
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        {
            "symbol": "RISKUSDT",
            "timeframe": "5m",
            "side": "short",
            "paper_opportunity_tier": "NO_TRADE",
            "confidence_calibrated": 0.52,
            "expected_move_after_cost_bps": -6.0,
            "actual_observed_spread_entry_bps": 4.0,
            "expected_slippage_bps": 3.0,
            "fee_bps": 4.0,
            "depth_utilization_pct": 0.40,
            "long_short_ratio_status": "REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION",
            "paper_drawdown_recovery_guard": {
                "adaptive_confidence_policy": {
                    "threshold_id": "paper_drawdown_recovery_min_confidence",
                    "static_floor": 0.65,
                    "dynamic_floor": 0.72,
                    "threshold_lowering_to_force_trades": False,
                    "never_below_static": True,
                },
            },
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
    ]

    status = paper_loop._paper_adaptive_threshold_runtime_status(rows)  # noqa: SLF001

    assert status["status"] == (
        "PARTIAL_B_GRADE_SIGNAL_STALE_AND_DRAWDOWN_RECOVERY_ADAPTIVE_FAIL_CLOSED_"
        "STATIC_THRESHOLDS_REMAIN"
    )
    assert status["adaptive_threshold_id"] == (
        "b_grade_confidence_floor,paper_signal_stale_seconds,"
        "paper_drawdown_recovery_min_confidence,directional_collapse_guard"
    )
    assert status["evaluated_rows"] == 2
    assert status["static_floor_pass_rows"] == 2
    assert status["adaptive_floor_pass_rows"] == 1
    assert status["adaptive_floor_block_rows"] == 1
    assert status["adaptive_floor_never_below_static_rows"] == 2
    assert status["threshold_lowering_to_force_trades"] is False
    assert status["pass_conditions"]["adaptive_floor_never_below_static"] is True
    assert status["pass_conditions"]["adaptive_signal_stale_threshold_never_above_static"] is True
    assert status["adaptive_signal_stale_threshold"]["evaluated_rows"] == 2
    assert status["adaptive_signal_stale_threshold"]["adaptive_stricter_than_static_rows"] == 1
    assert status["adaptive_drawdown_recovery_confidence_floor"]["evaluated_rows"] == 2
    assert status["adaptive_drawdown_recovery_confidence_floor"]["dynamic_never_below_static_rows"] == 2
    assert status["adaptive_drawdown_recovery_confidence_floor"]["dynamic_tightened_rows"] == 1
    assert status["adaptive_directional_collapse_guard"]["evaluated_rows"] == 0
    assert "paper_signal_stale_seconds" not in status["remaining_static_threshold_blockers"]
    assert "paper_drawdown_recovery_min_confidence" not in status["remaining_static_threshold_blockers"]
    assert "directional_collapse_guard" in status["remaining_static_threshold_blockers"]
    assert (
        status["pass_conditions"]["adaptive_drawdown_recovery_threshold_never_below_static"]
        is True
    )
    assert status["pass_conditions"]["ready_allowed"] is False
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False


def test_adaptive_directional_collapse_guard_tightens_large_one_sided_samples() -> None:
    ledger = {
        "closed_trades": (
            [{"side": "short"} for _ in range(540)]
            + [{"side": "long"} for _ in range(60)]
        )
    }

    short_guard = paper_loop._paper_directional_collapse_guard(ledger, "short")  # noqa: SLF001
    long_guard = paper_loop._paper_directional_collapse_guard(ledger, "long")  # noqa: SLF001

    assert short_guard["static_directional_collapse_detected"] is False
    assert short_guard["adaptive_directional_collapse_detected"] is True
    assert short_guard["directional_collapse_detected"] is True
    assert short_guard["allowed"] is False
    assert short_guard["block_reason"] == paper_loop.DIRECTIONAL_COLLAPSE_BLOCK_REASON
    adaptive_policy = short_guard["adaptive_policy"]
    assert adaptive_policy["adaptive_never_looser_than_static"] is True
    assert adaptive_policy["adaptive_minimum_side_trades"] >= (
        paper_loop.DIRECTIONAL_COLLAPSE_MIN_SIDE_TRADES
    )
    assert adaptive_policy["adaptive_major_side_share_threshold"] <= (
        paper_loop.DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE
    )
    assert adaptive_policy["threshold_lowering_to_force_trades"] is False
    assert long_guard["allowed"] is True
    assert long_guard["adaptive_directional_collapse_detected"] is True


def test_adaptive_threshold_runtime_status_removes_directional_static_blocker_when_guard_adaptive() -> None:
    ledger = {
        "closed_trades": (
            [{"side": "short"} for _ in range(540)]
            + [{"side": "long"} for _ in range(60)]
        )
    }
    rows = [
        {
            "symbol": "DIRUSDT",
            "timeframe": "15m",
            "side": "short",
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "confidence_calibrated": 0.71,
            "expected_move_after_cost_bps": 20.0,
            "actual_observed_spread_entry_bps": 1.0,
            "expected_slippage_bps": 1.0,
            "fee_bps": 4.0,
            "depth_utilization_pct": 0.01,
            "long_short_ratio_status": "V2_LONG_SHORT_RATIO_ATTACHED",
            "paper_directional_collapse_guard": paper_loop._paper_directional_collapse_guard(  # noqa: SLF001
                ledger,
                "short",
            ),
            "paper_drawdown_recovery_guard": {
                "adaptive_confidence_policy": {
                    "threshold_id": "paper_drawdown_recovery_min_confidence",
                    "static_floor": 0.65,
                    "dynamic_floor": 0.65,
                    "threshold_lowering_to_force_trades": False,
                    "never_below_static": True,
                },
            },
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    ]

    status = paper_loop._paper_adaptive_threshold_runtime_status(rows)  # noqa: SLF001

    directional = status["adaptive_directional_collapse_guard"]
    assert directional["evaluated_rows"] == 1
    assert directional["adaptive_never_looser_than_static_rows"] == 1
    assert directional["adaptive_tightened_rows"] == 1
    assert status["pass_conditions"]["adaptive_directional_collapse_guard_evaluated_rows_gt_zero"] is True
    assert (
        status["pass_conditions"]["adaptive_directional_collapse_guard_never_looser_than_static"]
        is True
    )
    assert "directional_collapse_guard" not in status["remaining_static_threshold_blockers"]
    assert status["threshold_lowering_to_force_trades"] is False
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_b_grade_canary_supply_status_reports_paper_only_pending_supply(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:05:00Z")
    row = {
        "symbol": "HUSDT",
        "timeframe": "4h",
        "side": "long",
        "strategy_id": "trend_mode",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
        "expected_move_after_cost_bps": 8.0,
        "production_grade_cost_flag": True,
        "valid_for_paper": True,
        "risk_decision_id": "rd-1",
        "orchestrator_decision_id": "dec-1",
        "gross_notional_usd": 1000.0,
        "risk_budget_usd": 10.0,
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "challenger_canary_id": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "challenger_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_fill_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
        "paper_canary_adaptive_sizing_required": True,
        "paper_canary_fixed_notional_allowed": False,
        "paper_canary_live_routing_allowed": False,
        "long_short_ratio_status": "V2_LONG_SHORT_RATIO_ATTACHED",
    }

    status = paper_loop._paper_b_grade_canary_supply_status([row])  # noqa: SLF001

    assert status["status"] == "B_GRADE_CANARY_PENDING_SUPPLY_PRESENT"
    assert status["canary_candidates"] == 1
    assert status["canary_intents"] == 1
    assert status["canary_pending_rows"] == 1
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False
    assert status["pass_conditions"] == {
        "canary_candidates_gt_zero": True,
        "canary_intents_gt_zero": True,
        "canary_pending_rows_gt_zero": True,
        "canary_identity_preserved": True,
    }
    assert status["predicate_counts"]["risk_gateway_decision_rows"] == 1
    assert status["predicate_counts"]["risk_pass_rows"] == 1


def test_b_grade_canary_supply_status_keeps_no_trade_strategy_blocked(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:06:00Z")
    row = {
        "symbol": "ALLOUSDT",
        "timeframe": "1h",
        "side": "long",
        "strategy_id": "no_trade_mode",
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": 40.0,
        "production_grade_cost_flag": True,
        "valid_for_paper": True,
        "risk_decision_id": "rd-2",
        "orchestrator_decision_id": "dec-2",
        "pre_paper_tier_block_gross_notional_usd": 187.0,
        "pre_paper_tier_block_risk_budget_usd": 0.75,
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "challenger_canary_id": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "challenger_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE",
        "paper_fill_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
        "paper_canary_adaptive_sizing_required": True,
        "paper_canary_fixed_notional_allowed": False,
        "paper_canary_live_routing_allowed": False,
    }

    status = paper_loop._paper_b_grade_canary_supply_status([row])  # noqa: SLF001

    assert status["status"] == "BLOCKED_ZERO_B_GRADE_CANARY_SUPPLY"
    assert status["canary_candidates"] == 0
    assert status["canary_intents"] == 0
    assert status["canary_pending_rows"] == 0
    assert status["near_miss_strategy_blocked_rows"] == 1
    assert status["root_cause_counts"]["strategy_failed"] == 1
    assert status["root_cause_counts"]["expected_edge_below_cost"] == 0
    assert status["root_cause_counts"]["allocator_failed"] == 0
    assert status["root_cause_counts"]["unsafe_live_route_flags"] == 0
    assert status["predicate_counts"]["strategy_entry_evidence_rows"] == 0
    assert status["predicate_counts"]["risk_gateway_decision_rows"] == 1
    assert status["predicate_counts"]["risk_pass_rows"] == 1


def test_b_grade_canary_supply_status_treats_short_negative_edge_as_favorable() -> None:
    row = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "short",
        "strategy_id": "trend_mode",
        "confidence_calibrated": 0.67,
        "expected_move_after_cost_bps": -12.0,
        "production_grade_cost_flag": True,
        "valid_for_paper": True,
        "risk_decision_id": "rd-3",
        "orchestrator_decision_id": "dec-3",
        "gross_notional_usd": 200.0,
        "risk_budget_usd": 1.0,
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "challenger_canary_id": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "challenger_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_fill_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
        "paper_canary_adaptive_sizing_required": True,
        "paper_canary_fixed_notional_allowed": False,
        "paper_canary_live_routing_allowed": False,
    }

    status = paper_loop._paper_b_grade_canary_supply_status([row])  # noqa: SLF001

    assert status["canary_candidates"] == 1
    assert status["canary_intents"] == 0
    assert status["canary_pending_rows"] == 0
    assert status["predicate_counts"]["expected_edge_after_cost_favorable_rows"] == 1
    assert status["root_cause_counts"]["expected_edge_below_cost"] == 0


def test_b_grade_canary_supply_status_counts_lifecycle_supply_when_current_cycle_blocked(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:55:00Z")
    current_blocked = {
        "symbol": "AGTUSDT",
        "timeframe": "4h",
        "side": "short",
        "strategy_id": "no_trade_mode",
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": -40.0,
        "production_grade_cost_flag": True,
        "valid_for_paper": True,
        "risk_decision_id": "rd-current",
        "orchestrator_decision_id": "dec-current",
        "gross_notional_usd": 100.0,
        "risk_budget_usd": 1.0,
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE",
        "paper_fill_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
    }
    accepted = {
        "symbol": "AGTUSDT",
        "timeframe": "4h",
        "side": "short",
        "strategy_id": "trend_mode",
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": -40.0,
        "production_grade_cost_flag": True,
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "valid_for_paper": True,
        "risk_decision_id": "rd-accepted",
        "orchestrator_decision_id": "dec-accepted",
        "gross_notional_usd": 100.0,
        "risk_budget_usd": 1.0,
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "challenger_canary_id": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "challenger_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_fill_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
        "paper_canary_adaptive_sizing_required": True,
        "paper_canary_fixed_notional_allowed": False,
        "paper_canary_live_routing_allowed": False,
    }
    open_position = {
        **accepted,
        "position_id": "paper_pos_AGTUSDT",
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "paper_canary_adaptive_sizing_required": None,
        "paper_canary_fixed_notional_allowed": None,
        "paper_canary_live_routing_allowed": None,
    }

    status = paper_loop._paper_b_grade_canary_supply_status(  # noqa: SLF001
        [current_blocked],
        accepted_rows=[accepted],
        open_position_rows=[open_position],
    )

    assert status["status"] == "B_GRADE_CANARY_LIFECYCLE_SUPPLY_PRESENT_CURRENT_CYCLE_BLOCKED"
    assert status["canary_candidates"] == 1
    assert status["canary_intents"] == 1
    assert status["canary_pending_rows"] == 1
    assert status["current_cycle_canary_candidates"] == 0
    assert status["current_cycle_canary_intents"] == 0
    assert status["current_cycle_canary_pending_rows"] == 0
    assert status["lifecycle_accepted_canary_rows"] == 1
    assert status["lifecycle_open_canary_rows"] == 1
    assert status["pass_conditions"] == {
        "canary_candidates_gt_zero": True,
        "canary_intents_gt_zero": True,
        "canary_pending_rows_gt_zero": True,
        "canary_identity_preserved": True,
    }
    assert status["current_cycle_pass_conditions"]["canary_pending_rows_gt_zero"] is False
    assert status["root_cause_counts"]["strategy_failed"] == 1
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False


def test_open_position_replay_binds_missing_b_grade_canary_identity() -> None:
    row = {
        "position_id": "paper_pos_AGTUSDT",
        "symbol": "AGTUSDT",
        "timeframe": "4h",
        "side": "short",
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": -40.0,
        "production_grade_cost_flag": True,
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "valid_for_paper": True,
        "risk_decision_id": "rd-open",
        "orchestrator_decision_id": "dec-open",
        "paper_fill_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "gross_notional_usd": 100.0,
        "risk_budget_usd": 1.0,
        "quantity": 2.0,
        "entry_price": 50.0,
        "fill_price": 50.0,
    }

    replayed = paper_loop._accepted_fill_from_open_position(row)  # noqa: SLF001

    assert replayed["challenger_canary_id"] == "CHALLENGER_B_GRADE_PAPER_CANARY"
    assert replayed["challenger_canary_profile"] == "CHALLENGER_B_GRADE_PAPER_CANARY"
    assert replayed["paper_canary_profile"] == "CHALLENGER_B_GRADE_PAPER_CANARY"
    assert replayed["paper_canary_adaptive_sizing_required"] is True
    assert replayed["paper_canary_fixed_notional_allowed"] is False
    assert replayed["paper_canary_live_routing_allowed"] is False
    assert replayed["routes_to_live"] is False
    assert replayed["places_real_order"] is False
    assert replayed["counts_as_a_grade_evidence"] is False
    assert replayed["challenger_canary_binding_status"] == (
        "BOUND_CHALLENGER_B_GRADE_PAPER_CANARY"
    )
    assert "challenger_canary_id" in replayed["challenger_canary_binding_backfilled_fields"]
    assert paper_loop._paper_b_grade_lifecycle_canary_row(replayed) is True  # noqa: SLF001


def test_a_grade_gate_burndown_tracks_live_counts_and_guardian_block(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:58:00Z")
    row = {
        "symbol": "AGTUSDT",
        "timeframe": "4h",
        "side": "short",
        "strategy_id": "no_trade_mode",
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": -40.0,
        "production_grade_cost_flag": True,
        "valid_for_paper": True,
        "risk_decision_id": "rd-1",
        "orchestrator_decision_id": "dec-1",
        "gross_notional_usd": 100.0,
        "risk_budget_usd": 1.0,
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE",
        "paper_fill_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_a_grade_evidence": False,
    }
    b_grade_supply = {
        "pass_conditions": {
            "canary_candidates_gt_zero": True,
            "canary_intents_gt_zero": True,
            "canary_pending_rows_gt_zero": True,
            "canary_identity_preserved": True,
        },
        "current_cycle_pass_conditions": {
            "canary_candidates_gt_zero": False,
            "canary_intents_gt_zero": False,
            "canary_pending_rows_gt_zero": False,
            "canary_identity_preserved": True,
        },
        "current_cycle_canary_candidates": 0,
        "current_cycle_canary_intents": 0,
        "current_cycle_canary_pending_rows": 0,
        "lifecycle_accepted_canary_rows": 77,
        "lifecycle_open_canary_rows": 1,
        "lifecycle_closed_canary_outcome_rows": 33,
    }
    guardian_gate = {
        "status": "A_GRADE_HALTED_PERFORMANCE",
        "a_grade_new_entries_allowed": False,
        "block_all_new_a_grade_entries": True,
        "new_candidate_tier_override": "SHADOW_ONLY",
        "allowed_runtime_actions": ["reduce", "close"],
        "failure_reasons": [
            {
                "reason": "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES",
                "observed": 0,
                "required": 1000,
            }
        ],
        "generated_utc": "2026-06-27T23:57:00Z",
    }
    guardian_status = {
        "strategy_brain_status": {
            "status": "BLOCKED_NO_A_GRADE_STRATEGY_ELIGIBILITY",
            "a_grade_active_bucket_count": 0,
            "bucket_count": 33,
            "blocker_counts": {"B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE": 33},
        },
        "zero_liquidation_status": {
            "status": "BLOCKED_NO_A_GRADE_CANDIDATES_STRESS_VERIFIED",
            "a_grade_candidate_count": 0,
            "passed_a_grade_candidate_count": 0,
        },
        "realtime_a_grade_performance_status": {
            "status": "BLOCKED_INSUFFICIENT_REALTIME_A_GRADE_EVIDENCE",
            "closed_economic_trade_count": 0,
            "symbol_count": 0,
        },
    }

    status = paper_loop._paper_a_grade_gate_burndown_status(  # noqa: SLF001
        [row],
        accepted_rows=[],
        open_position_rows=[],
        closed_rows=[],
        guardian_gate=guardian_gate,
        guardian_status=guardian_status,
        b_grade_canary_supply_status=b_grade_supply,
    )

    assert status["status"] == "A_GRADE_GATE_ACTIVE_BLOCKED_SOURCE_OWNED"
    assert status["prediction_rows"] == 1
    assert status["production_grade_cost_rows"] == 1
    assert status["risk_pass_rows"] == 1
    assert status["strategy_pass_rows"] == 0
    assert status["A_grade_rows"] == 0
    assert status["near_A_grade_rows"] == 0
    assert status["b_grade_lifecycle_supply_present"] is True
    assert status["current_cycle_b_grade_supply_present"] is False
    assert status["accepted_b_grade_lifecycle_rows"] == 77
    assert status["open_b_grade_lifecycle_rows"] == 1
    assert status["closed_b_grade_lifecycle_outcome_rows"] == 33
    assert status["guardian_gate_status"]["a_grade_new_entries_allowed"] is False
    assert status["closest_gap_source_owner"] == "continuous_edge_guardian"
    assert status["zero_supply_source_owner"] == "continuous_edge_guardian"
    assert status["source_owned_zero_supply_root_cause"] == {
        "reason": "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE",
        "source_owner": "continuous_edge_guardian",
        "guardian_halted": True,
        "near_a_grade_rows_present": False,
        "top_current_runtime_reason": "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE",
        "top_guardian_reason": "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES",
    }
    assert status["pass_conditions"] == {
        "A_grade_rows_gt_zero": False,
        "source_owned_zero_supply_root_cause_mapped": True,
        "a_grade_new_entries_allowed": False,
        "ready_allowed": False,
    }
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False


def test_churn_equity_bleed_governor_compacts_economic_trades_and_costs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T08:00:00Z")
    closed = [
        {
            "close_id": "close-1",
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "side": "long",
            "entry_time": "2026-06-29T07:40:00Z",
            "exit_time": "2026-06-29T07:45:00Z",
            "gross_notional_usd": 100.0,
            "fees_usd": 0.04,
            "realized_slippage_usd": 0.02,
            "funding_pnl_usd": 0.01,
            "realized_net_pnl_usd": 1.25,
            "hold_time_seconds": 300,
            "paper_only": True,
            "places_real_order": False,
        },
        {
            "close_id": "close-1",
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "side": "long",
            "entry_time": "2026-06-29T07:40:00Z",
            "exit_time": "2026-06-29T07:45:00Z",
            "gross_notional_usd": 100.0,
            "fees_usd": 0.04,
            "realized_slippage_usd": 0.02,
            "funding_pnl_usd": 0.01,
            "realized_net_pnl_usd": 1.25,
            "hold_time_seconds": 300,
            "paper_only": True,
            "places_real_order": False,
        },
    ]
    current = [
        {
            "fill_id": "fill-1",
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "side": "long",
            "prediction_id": "pred-1",
            "signal_id": "sig-1",
            "entry_feature_cutoff": "2026-06-29T07:44:59.999Z",
            "policy_activated_at": "2026-06-29T07:50:00Z",
            "paper_only": True,
            "places_real_order": False,
        }
    ]

    status = paper_loop._paper_churn_equity_bleed_governor_status(  # noqa: SLF001
        accepted_rows=current,
        open_position_rows=[],
        closed_rows=closed,
        current_accepted_rows=current,
        generated_utc="2026-06-29T08:00:00Z",
    )

    assert status["state"] == "ACTIVE"
    assert status["new_entries_allowed"] is True
    assert status["raw_close_records"] == 2
    assert status["compacted_economic_trades"] == 1
    assert status["duplicate_close_record_count"] == 1
    assert status["fees_usd"] == 0.04
    assert status["slippage_usd"] == 0.02
    assert status["funding_usd"] == 0.01
    assert status["turnover_usd"] == 100.0
    assert status["edge_to_cost_ratio"] == pytest.approx(17.85714286)
    assert status["median_hold_time"] == 300
    assert status["entries_per_symbol_per_hour"] == 1
    assert status["duplicate_new_entries"] == 0
    assert status["pass_conditions"] == {
        "duplicate_new_entries_eq_zero": True,
        "same_candle_reentry_unexplained_eq_zero": True,
        "cost_drag_within_envelope": True,
        "economic_trade_count_reconciles": True,
    }
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_churn_equity_bleed_governor_halts_duplicate_current_entries() -> None:
    row = {
        "fill_id": "fill-1",
        "symbol": "SOLUSDT",
        "timeframe": "5m",
        "side": "short",
        "prediction_id": "pred-dupe",
        "signal_id": "sig-dupe",
        "entry_feature_cutoff": "2026-06-29T07:54:59.999Z",
        "policy_activated_at": "2026-06-29T07:58:00Z",
        "paper_only": True,
        "places_real_order": False,
    }
    duplicate = {**row, "fill_id": "fill-2"}

    status = paper_loop._paper_churn_equity_bleed_governor_status(  # noqa: SLF001
        accepted_rows=[row, duplicate],
        open_position_rows=[],
        closed_rows=[],
        current_accepted_rows=[row, duplicate],
        generated_utc="2026-06-29T08:00:00Z",
    )

    assert status["state"] == "CHURN_HALTED"
    assert status["new_entries_allowed"] is False
    assert status["duplicate_new_entries"] == 1
    assert status["same_candle_reentry_count"] == 1
    assert status["same_prediction_duplicate_count"] == 1
    assert status["same_signal_duplicate_count"] == 1
    assert status["pass_conditions"]["duplicate_new_entries_eq_zero"] is False


def test_churn_equity_bleed_current_entry_rejection_reasons() -> None:
    existing = {
        "fill_id": "fill-1",
        "symbol": "SOLUSDT",
        "timeframe": "5m",
        "side": "short",
        "prediction_id": "pred-dupe",
        "signal_id": "sig-dupe",
        "entry_feature_cutoff": "2026-06-29T07:54:59.999Z",
    }
    candidate = {**existing, "fill_id": "fill-2"}

    reasons = paper_loop._paper_churn_current_entry_rejection_reasons(  # noqa: SLF001
        candidate,
        [existing],
    )

    assert reasons == [
        "DUPLICATE_CURRENT_CYCLE_PREDICTION",
        "DUPLICATE_CURRENT_CYCLE_SIGNAL",
        "SAME_CANDLE_REENTRY_CURRENT_CYCLE",
    ]


def test_churn_equity_bleed_post_backfill_quarantines_same_signal_duplicates() -> None:
    current = [
        {
            "fill_id": "fill-1",
            "signal_id": "sig-original-1",
            "prediction_id": "pred-1",
        },
        {
            "fill_id": "fill-2",
            "signal_id": "sig-original-2",
            "prediction_id": "pred-2",
        },
    ]
    backfilled = [
        {
            "fill_id": "fill-1",
            "symbol": "GUSDT",
            "timeframe": "1h",
            "side": "short",
            "signal_id": "sig-shared",
            "prediction_id": "pred-1",
            "entry_feature_cutoff": "2026-06-29T07:59:59.999Z",
        },
        {
            "fill_id": "fill-2",
            "symbol": "GUSDT",
            "timeframe": "15m",
            "side": "short",
            "signal_id": "sig-shared",
            "prediction_id": "pred-2",
            "entry_feature_cutoff": "2026-06-29T07:44:59.999Z",
        },
    ]

    filtered, current_after_backfill, blocked = (
        paper_loop._paper_filter_post_backfill_current_churn_duplicates(  # noqa: SLF001
            backfilled,
            current,
        )
    )

    assert [row["fill_id"] for row in filtered] == ["fill-1"]
    assert [row["fill_id"] for row in current_after_backfill] == ["fill-1"]
    assert [row["fill_id"] for row in blocked] == ["fill-2"]
    assert blocked[0]["paper_fill_block_reason"] == (
        paper_loop.PAPER_CHURN_EQUITY_BLEED_BLOCK_REASON
    )
    assert blocked[0]["paper_churn_equity_bleed_block_stage"] == (
        "POST_BACKFILL_PRE_LIFECYCLE"
    )
    assert blocked[0]["paper_churn_equity_bleed_governor_block_reasons"] == [
        "DUPLICATE_CURRENT_CYCLE_SIGNAL"
    ]


def test_churn_equity_bleed_open_position_filter_matches_position_id_to_fill_id() -> None:
    open_positions = [
        {
            "position_id": "paper_pos_KEEPUSDT",
            "symbol": "KEEPUSDT",
            "side": "short",
        },
        {
            "position_id": "paper_pos_DROPUSDT",
            "symbol": "DROPUSDT",
            "side": "short",
        },
    ]
    accepted_rows = [
        {
            "fill_id": "paper_pos_KEEPUSDT",
            "ledger_row_id": "paper_pos_KEEPUSDT",
            "symbol": "KEEPUSDT",
            "side": "short",
        }
    ]

    filtered, dropped = paper_loop._paper_filter_open_positions_to_accepted_rows(  # noqa: SLF001
        open_positions,
        accepted_rows,
    )

    assert [row["position_id"] for row in filtered] == ["paper_pos_KEEPUSDT"]
    # F-0007: dropped positions must be surfaced for audit, never silently lost
    assert [row["position_id"] for row in dropped] == ["paper_pos_DROPUSDT"]


def _forward_canary_closed_row(symbol: str, side: str, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "timeframe": "15m",
        "side": side,
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_policy_owner": "challenger_v2",
        "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
        "policy_fingerprint": (
            "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
        ),
        "challenger_canary_id": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "challenger_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_profile": "CHALLENGER_B_GRADE_PAPER_CANARY",
        "paper_canary_adaptive_sizing_required": True,
        "paper_canary_fixed_notional_allowed": False,
        "paper_canary_live_routing_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "production_grade_cost_flag": True,
        "production_grade_cost_evidence": True,
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "realized_pnl_bps": 12.5,
        "decision_time": "2026-06-27T17:10:09.000Z",
        "feature_cutoff": "2026-06-27T17:04:59.999Z",
        "available_at": "2026-06-27T17:05:31.000Z",
    }
    row.update(overrides)
    return row


def test_closed_outcome_entry_context_backfill_restores_cost_lineage(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:40:00Z")
    accepted = _forward_canary_closed_row(
        "ARXUSDT",
        "short",
        signal_id="sig-1",
        prediction_id="pred-1",
    )
    closed = _forward_canary_closed_row(
        "ARXUSDT",
        "short",
        entry_signal_id="sig-1",
        entry_prediction_id="pred-1",
        production_grade_cost_flag=None,
        production_grade_cost_evidence=None,
        runtime_cost_capture_status=None,
    )

    context = paper_loop._entry_feedback_context_by_fill_id([accepted])  # noqa: SLF001
    repaired, status = paper_loop._paper_backfill_closed_outcome_entry_context_rows(  # noqa: SLF001
        [closed],
        entry_context_by_fill_id=context,
        row_kind="closed_trades",
    )
    forward = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=repaired,
        accepted_rows=[accepted],
    )

    assert repaired[0]["production_grade_cost_flag"] is True
    assert repaired[0]["runtime_cost_capture_status"] == "PRODUCTION_GRADE_COST_CAPTURE"
    assert repaired[0]["closed_outcome_entry_context_backfilled"] is True
    assert status["production_grade_cost_repaired_rows"] == 1
    assert status["matched_entry_context_rows"] == 1
    assert status["unmatched_b_grade_challenger_missing_cost_rows"] == 0
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert forward["valid_forward_canary_economic_outcomes"] == 1
    assert forward["production_grade_cost_coverage"] == 1.0


def test_forward_canary_evidence_status_reports_incomplete_runtime_evidence(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:20:00Z")
    valid = _forward_canary_closed_row("ARXUSDT", "short")
    missing_cost = _forward_canary_closed_row(
        "BNBUSDT",
        "long",
        production_grade_cost_flag=None,
        production_grade_cost_evidence=None,
        runtime_cost_capture_status=None,
    )
    live_unsafe = _forward_canary_closed_row("ETHUSDT", "short", places_real_order=True)

    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=[valid, missing_cost, live_unsafe],
        accepted_rows=[
            _forward_canary_closed_row("ARXUSDT", "short"),
            _forward_canary_closed_row("BNBUSDT", "long"),
        ],
    )

    assert status["status"] == "BLOCKED_FORWARD_CANARY_EVIDENCE_INCOMPLETE"
    assert status["source_closed_trade_rows"] == 3
    assert status["b_grade_challenger_closed_outcome_rows"] == 3
    assert status["valid_forward_canary_economic_outcomes"] == 1
    assert status["required_forward_canary_economic_outcomes"] == 100
    assert status["required_symbol_count"] == 20
    assert status["required_initial_symbols"] == 20
    assert status["minimum_required_symbol_count"] == 20
    assert status["production_grade_cost_closed_outcome_rows"] == 2
    assert status["production_grade_cost_coverage"] == pytest.approx(2 / 3)
    assert status["accepted_b_grade_canary_rows"] == 2
    assert status["accepted_b_grade_production_grade_cost_rows"] == 2
    assert status["valid_side_counts"] == {"long": 0, "short": 1}
    assert status["side_counts"] == {"long": 0, "short": 1}
    assert status["required_side_counts"] == {"long": 1, "short": 1}
    assert status["source_side_counts"] == {"long": 1, "short": 2}
    assert status["unsafe_live_route_rows"] == 1
    assert status["rows_rejected_by_reason"] == {
        "MISSING_PRODUCTION_GRADE_COST_EVIDENCE_ON_CLOSED_OUTCOME": 1,
        "UNSAFE_LIVE_ROUTE_FLAG": 1,
    }
    assert status["pass_conditions"]["valid_forward_canary_outcomes_gte_100"] is False
    assert status["pass_conditions"]["production_grade_cost_coverage_gte_95pct"] is False
    assert status["failed_pass_conditions"] == [
        "long_outcomes_gt_zero",
        "no_live_route_flags",
        "production_grade_cost_coverage_gte_95pct",
        "valid_forward_canary_outcomes_gte_100",
        "valid_symbol_count_gte_20",
    ]
    assert status["forward_canary_shortfalls"]["valid_forward_canary_economic_outcomes"] == 99
    assert status["forward_canary_shortfalls"]["valid_symbol_count"] == 19
    assert status["forward_canary_shortfalls"]["long_outcomes"] == 1
    assert status["forward_canary_shortfalls"]["short_outcomes"] == 0
    assert status["failed_forward_canary_blocker_details"]["valid_symbol_count_gte_20"] == {
        "actual": 1,
        "required": 20,
        "remaining": 19,
        "passed": False,
    }
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["counts_as_a_grade_evidence"] is False


def test_forward_canary_evidence_rejects_missing_canary_identity(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:20:30Z")
    missing_identity = _forward_canary_closed_row(
        "ARXUSDT",
        "short",
        challenger_canary_id=None,
        challenger_canary_profile=None,
        paper_canary_profile=None,
    )

    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=[missing_identity],
        accepted_rows=[missing_identity],
    )

    assert status["valid_forward_canary_economic_outcomes"] == 0
    assert status["rows_rejected_by_reason"] == {
        "MISSING_CHALLENGER_B_GRADE_PAPER_CANARY_IDENTITY": 1
    }
    assert status["sample_rejected_forward_canary_outcomes"][0]["forward_canary_rejection_reasons"] == [
        "MISSING_CHALLENGER_B_GRADE_PAPER_CANARY_IDENTITY"
    ]


def test_forward_canary_evidence_status_passes_only_complete_paper_canary_set(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T23:21:00Z")
    rows = [
        _forward_canary_closed_row(
            f"SYM{idx % 20:02d}USDT",
            "long" if idx % 2 == 0 else "short",
            realized_pnl_bps=float(idx % 7) - 2.0,
        )
        for idx in range(100)
    ]

    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=rows,
        accepted_rows=rows,
    )

    assert status["status"] == "FORWARD_CANARY_EVIDENCE_REQUIREMENTS_MET"
    assert status["valid_forward_canary_economic_outcomes"] == 100
    assert status["required_symbol_count"] == 20
    assert status["valid_symbol_count"] == 20
    assert status["valid_side_counts"] == {"long": 50, "short": 50}
    assert status["side_counts"] == {"long": 50, "short": 50}
    assert status["forward_canary_shortfalls"]["valid_forward_canary_economic_outcomes"] == 0
    assert status["forward_canary_shortfalls"]["valid_symbol_count"] == 0
    assert status["failed_pass_conditions"] == []
    assert status["failed_forward_canary_blocker_details"] == {}
    assert status["production_grade_cost_coverage"] == 1.0
    assert status["accounting_mismatch_rows"] == 0
    assert status["liquidation_rows"] == 0
    assert status["point_in_time_invalid_rows"] == 0
    assert all(status["pass_conditions"].values())
    assert status["paper_only"] is True
    assert status["live_path_changed"] is False


def test_forward_canary_evidence_status_requires_post_cutover_outcomes(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T04:20:00Z")
    archived_rows = [
        _forward_canary_closed_row(
            f"OLD{idx % 20:02d}USDT",
            "long" if idx % 2 == 0 else "short",
            close_id=f"old-close-{idx}",
            exit_price_utc="2026-06-29T03:57:37.000Z",
        )
        for idx in range(100)
    ]
    post_cutover_rows = [
        _forward_canary_closed_row(
            "NEW01USDT",
            "long",
            close_id="new-close-1",
            exit_price_utc="2026-06-29T03:57:39.000Z",
        ),
        _forward_canary_closed_row(
            "NEW02USDT",
            "short",
            close_id="new-close-2",
            exit_price_utc="2026-06-29T03:57:40.000Z",
        ),
    ]

    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=[*archived_rows, *post_cutover_rows],
        accepted_rows=[*archived_rows, *post_cutover_rows],
        cutover_completed_at="2026-06-29T03:57:38.333Z",
    )

    assert status["status"] == "BLOCKED_FORWARD_CANARY_EVIDENCE_INCOMPLETE"
    assert status["source_closed_trade_rows"] == 102
    assert status["archived_b_grade_challenger_closed_outcome_rows"] == 102
    assert status["b_grade_challenger_closed_outcome_rows"] == 2
    assert status["pre_cutover_b_grade_challenger_closed_outcome_rows"] == 100
    assert status["cutover_marker_present"] is True
    assert status["cutover_marker_valid"] is True
    assert status["valid_forward_canary_economic_outcomes"] == 2
    assert status["post_cutover_valid_forward_canary_economic_outcomes"] == 2
    assert status["required_symbol_count"] == 20
    assert status["valid_symbol_count"] == 2
    assert status["valid_side_counts"] == {"long": 1, "short": 1}
    assert status["side_counts"] == {"long": 1, "short": 1}
    assert status["production_grade_cost_coverage"] == 1.0
    assert status["pass_conditions"]["valid_forward_canary_outcomes_gte_100"] is False
    assert status["pass_conditions"]["valid_symbol_count_gte_20"] is False
    assert status["forward_canary_shortfalls"]["valid_forward_canary_economic_outcomes"] == 98
    assert status["forward_canary_shortfalls"]["valid_symbol_count"] == 18
    assert status["failed_forward_canary_blocker_details"]["valid_symbol_count_gte_20"] == {
        "actual": 2,
        "required": 20,
        "remaining": 18,
        "passed": False,
    }
    assert status["counts_as_a_grade_evidence"] is False


def test_forward_canary_evidence_status_rejects_invalid_cutover_marker(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-29T04:21:00Z")
    rows = [
        _forward_canary_closed_row(
            f"SYM{idx % 20:02d}USDT",
            "long" if idx % 2 == 0 else "short",
            close_id=f"close-{idx}",
        )
        for idx in range(100)
    ]

    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=rows,
        accepted_rows=rows,
        cutover_completed_at="not-a-timestamp",
    )

    assert status["status"] == "BLOCKED_FORWARD_CANARY_CUTOVER_MARKER_INVALID"
    assert status["cutover_marker_present"] is True
    assert status["cutover_marker_valid"] is False
    assert status["valid_forward_canary_economic_outcomes"] == 100


def test_forward_canary_archive_preserves_observed_outcomes_across_cycles(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-28T01:20:00Z")
    archive_path = tmp_path / "paper_forward_canary_closed_outcome_archive.json"
    existing_rows = [
        _forward_canary_closed_row("ARXUSDT", "long", close_id="close-1"),
        _forward_canary_closed_row("BNBUSDT", "short", close_id="close-2"),
    ]
    archive_path.write_text(
        json.dumps({"closed_outcomes": existing_rows}),
        encoding="utf-8",
    )

    archive = paper_loop._paper_forward_canary_closed_outcome_archive_status(  # noqa: SLF001
        [_forward_canary_closed_row("ETHUSDT", "short", close_id="close-3")],
        path=archive_path,
    )
    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=archive["closed_outcomes"],
        accepted_rows=[],
    )

    assert archive["existing_archived_closed_outcome_rows"] == 2
    assert archive["archived_closed_outcome_rows"] == 3
    assert archive["new_archived_closed_outcome_rows"] == 1
    assert archive["paper_only"] is True
    assert archive["routes_to_live"] is False
    assert archive["places_real_order"] is False
    assert status["valid_forward_canary_economic_outcomes"] == 3
    assert status["valid_symbol_count"] == 3
    assert status["production_grade_cost_coverage"] == 1.0


def test_forward_canary_archive_filters_pre_reset_rows_when_session_scoped(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-07-05T04:20:00Z")
    archive_path = tmp_path / "paper_forward_canary_closed_outcome_archive.json"
    old_rows = [
        _forward_canary_closed_row(
            f"OLD{idx % 20:02d}USDT",
            "long" if idx % 2 == 0 else "short",
            close_id=f"old-close-{idx}",
        )
        for idx in range(100)
    ]
    archive_path.write_text(
        json.dumps({"closed_outcomes": old_rows}),
        encoding="utf-8",
    )
    current_row = _forward_canary_closed_row(
        "NEW01USDT",
        "long",
        close_id="new-close-1",
        paper_session_id="paper_3000_final_pre_live_20260705T024432Z",
    )

    archive = paper_loop._paper_forward_canary_closed_outcome_archive_status(  # noqa: SLF001
        [current_row],
        path=archive_path,
        paper_session_id="paper_3000_final_pre_live_20260705T024432Z",
    )
    status = paper_loop._paper_forward_canary_evidence_status(  # noqa: SLF001
        closed_rows=archive["closed_outcomes"],
        accepted_rows=[],
    )

    assert archive["paper_session_filter_enabled"] is True
    assert archive["paper_session_id"] == "paper_3000_final_pre_live_20260705T024432Z"
    assert archive["existing_archived_closed_outcome_rows"] == 100
    assert archive["session_excluded_archived_closed_outcome_rows"] == 100
    assert archive["archived_closed_outcome_rows"] == 1
    assert archive["closed_outcomes"][0]["close_id"] == "new-close-1"
    assert status["source_closed_trade_rows"] == 1
    assert status["valid_forward_canary_economic_outcomes"] == 1
    assert status["forward_canary_shortfalls"]["valid_forward_canary_economic_outcomes"] == 99


def test_forward_canary_archive_replaces_duplicate_with_cost_complete_row(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-28T01:21:00Z")
    archive_path = tmp_path / "paper_forward_canary_closed_outcome_archive.json"
    archive_path.write_text(
        json.dumps(
            {
                "closed_outcomes": [
                    _forward_canary_closed_row(
                        "ARXUSDT",
                        "short",
                        close_id="close-1",
                        production_grade_cost_flag=None,
                        production_grade_cost_evidence=None,
                        runtime_cost_capture_status=None,
                    )
                ]
            }
        ),
        encoding="utf-8",
    )

    archive = paper_loop._paper_forward_canary_closed_outcome_archive_status(  # noqa: SLF001
        [_forward_canary_closed_row("ARXUSDT", "short", close_id="close-1")],
        path=archive_path,
    )

    assert archive["archived_closed_outcome_rows"] == 1
    assert archive["duplicate_closed_outcome_rows"] == 1
    assert archive["closed_outcomes"][0]["production_grade_cost_flag"] is True
    assert archive["closed_outcomes"][0]["runtime_cost_capture_status"] == "PRODUCTION_GRADE_COST_CAPTURE"


def test_confidence_trial_positive_edge_becomes_b_grade_paper_only_exploration() -> None:
    signal = {
        "paper_confidence_threshold_trial": True,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
    }
    intent = {
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
        "paper_only": True,
        "places_real_order": False,
    }
    allocation = _allowed_allocation()
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal=signal,
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_fill_allowed_source"] == "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE"
    assert classification["strict_paper_fill_allowed_upstream"] is False
    fraction = classification["risk_budget_fraction_of_normal_adaptive"]
    assert 0.0 < fraction <= paper_loop.B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL

    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )
    paper_loop._apply_b_grade_exploration_budget_cap(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        risk_budget_fraction_of_normal_adaptive=fraction,
    )

    assert intent["paper_only"] is True
    assert intent["places_real_order"] is False


def test_reduced_size_microstructure_becomes_a_plus_bootstrap_paper_only() -> None:
    signal = {
        "confidence_calibrated": 0.70,
        "expected_move_after_cost_bps": 14.0,
    }
    intent = {
        "confidence_calibrated": 0.70,
        "expected_move_after_cost_bps": 14.0,
        "paper_only": True,
        "places_real_order": False,
        "production_grade_cost_flag": True,
        "microstructure_action": "REDUCE_SIZE",
        "public_orderbook_trust_score": 0.51,
        "composite_microstructure_trust_score": 0.52,
        "bootstrap_reduced_size_paper_only": True,
    }
    allocation = _allowed_allocation(confidence_calibrated=0.70)

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal=signal,
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
        continuous_edge_guardian_gate={
            "status": "ACTIVE",
            "a_grade_new_entries_allowed": True,
            "allowed_runtime_actions": ["new_entry", "reduce", "close"],
        },
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert (
        classification["paper_opportunity_tier"]
        == paper_loop.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE
    )
    assert classification["counts_as_final_a_plus"] is False
    assert classification["counts_as_live_ready"] is False
    assert classification["routes_to_live"] is False
    assert classification["mandatory_size_haircut"] is True
    fraction = classification["risk_budget_fraction_of_normal_adaptive"]
    assert 0.0 < fraction <= paper_loop.B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL

    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )
    paper_loop._apply_b_grade_exploration_budget_cap(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        risk_budget_fraction_of_normal_adaptive=fraction,
    )

    assert intent["paper_only"] is True
    assert intent["places_real_order"] is False
    assert allocation["target_notional_usdt"] < allocation["normal_adaptive_target_notional_usdt"]
    assert intent["counts_as_final_a_plus"] is False
    assert allocation["b_grade_exploration_budget_cap_applied"] is True
    assert allocation["normal_adaptive_risk_budget_usd"] == 100.0
    assert allocation["risk_budget_usd"] == round(100.0 * fraction, 8)
    assert allocation["target_notional_usdt"] == round(1000.0 * fraction, 8)
    assert allocation["target_quantity"] == round(10.0 * fraction, 12)
    assert allocation["model_inputs"]["risk_budget_fraction_of_normal_adaptive"] == fraction


def test_reduced_size_bootstrap_requires_explicit_guardian_new_entries_allowed() -> None:
    base_signal = {
        "selected_action": "long",
        "confidence_calibrated": 0.72,
        "expected_move_after_cost_bps": 18.0,
    }
    base_intent = {
        "side": "long",
        "confidence_calibrated": 0.72,
        "expected_move_after_cost_bps": 18.0,
        "paper_only": True,
        "places_real_order": False,
        "production_grade_cost_flag": True,
        "microstructure_action": "REDUCE_SIZE",
        "public_orderbook_trust_score": 0.51,
        "composite_microstructure_trust_score": 0.52,
        "bootstrap_reduced_size_paper_only": True,
    }

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal=base_signal,
        intent=base_intent,
        allocation=_allowed_allocation(confidence_calibrated=0.72),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate=None,
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "REDUCED_SIZE_BOOTSTRAP_REQUIRES_GUARDIAN_NEW_ENTRIES_ALLOWED"
    )
    assert classification["pre_guardian_paper_opportunity_tier"] == (
        paper_loop.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE
    )
    assert classification["paper_fill_allowed_source"] == (
        "CONTINUOUS_EDGE_GUARDIAN_BLOCKED_REDUCED_SIZE_BOOTSTRAP"
    )
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_reduced_size_bootstrap_halted_guardian_blocks_cake_avnt_style_local_gate() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.78,
            "expected_move_after_cost_bps": -17.0,
        },
        intent={
            "symbol": "AVNTUSDT",
            "side": "short",
            "timeframe": "4h",
            "strategy_id": "scalp_mode",
            "confidence_calibrated": 0.78,
            "expected_move_after_cost_bps": -17.0,
            "paper_only": True,
            "places_real_order": False,
            "production_grade_cost_flag": True,
            "microstructure_action": "REDUCE_SIZE",
            "public_orderbook_trust_score": 0.51,
            "composite_microstructure_trust_score": 0.52,
            "bootstrap_reduced_size_paper_only": True,
        },
        allocation=_allowed_allocation(
            confidence_calibrated=0.78,
            expected_move_after_cost_bps=-17.0,
        ),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={
            "status": "A_GRADE_HALTED_PERFORMANCE",
            "a_grade_new_entries_allowed": False,
            "failure_reasons": [{"reason": "HIGH_CONFIDENCE_LOSS_CLUSTER"}],
            "allowed_runtime_actions": ["reduce", "close", "emergency_de_risk"],
        },
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "REDUCED_SIZE_BOOTSTRAP_REQUIRES_GUARDIAN_NEW_ENTRIES_ALLOWED"
    )
    assert classification["continuous_edge_guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert classification["continuous_edge_guardian_new_entries_allowed"] is False
    assert classification["paper_fill_allowed_source"] == (
        "CONTINUOUS_EDGE_GUARDIAN_BLOCKED_REDUCED_SIZE_BOOTSTRAP"
    )
    assert classification["counts_as_final_a_plus"] is False
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_short_signed_edge_can_be_a_grade_when_strict_gate_allowed() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": -12.0,
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": -12.0,
        },
        allocation=_allowed_allocation(expected_move_after_cost_bps=-12.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert classification["paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert classification["paper_fill_allowed_source"] == "STRICT_UPSTREAM_PAPER_FILL_GATE"


def test_continuous_edge_guardian_halt_downgrades_new_a_grade_to_shadow_only() -> None:
    allocation = _allowed_allocation(expected_move_after_cost_bps=12.0)
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 12.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 12.0,
        },
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={
            "status": "A_GRADE_HALTED_PERFORMANCE",
            "a_grade_new_entries_allowed": False,
            "failure_reasons": [{"reason": "ROLLING_100_WIN_RATE_BELOW_90P"}],
            "allowed_runtime_actions": ["reduce", "close"],
        },
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == "CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED"
    assert classification["pre_guardian_paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert classification["pre_guardian_paper_opportunity_tier_reason"] == (
        "STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED"
    )
    assert classification["pre_guardian_paper_fill_allowed_source"] == (
        "STRICT_UPSTREAM_PAPER_FILL_GATE"
    )
    assert classification["continuous_edge_guardian_forced_shadow_only"] is True
    assert classification["counts_as_a_grade_evidence"] is False
    assert classification["continuous_edge_guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False

    intent: dict[str, object] = {}
    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )

    assert intent["source_tier"] == "SHADOW_ONLY"
    assert intent["policy_tier"] == "SHADOW_ONLY"
    assert intent["capital_class"] == "SHADOW_ONLY_ZERO_SIZE"
    assert intent["pre_guardian_source_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert intent["pre_guardian_policy_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert intent["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert intent["guardian_new_entries_allowed"] is False
    assert intent["guardian_block_reasons"] == [
        {"reason": "ROLLING_100_WIN_RATE_BELOW_90P"}
    ]
    assert intent["guardian_allowed_runtime_actions"] == ["reduce", "close"]
    assert allocation["source_tier"] == "SHADOW_ONLY"
    assert allocation["model_inputs"]["source_tier"] == "SHADOW_ONLY"
    assert allocation["model_inputs"]["capital_class"] == "SHADOW_ONLY_ZERO_SIZE"


def test_dynamic_positive_edge_below_a_grade_becomes_b_grade_when_exploration_gates_pass() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.64, expected_move_after_cost_bps=8.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
        preemptive_decision=_preemptive_allow_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False
    assert classification["risk_budget_fraction_of_normal_adaptive"] > 0.0


@pytest.mark.parametrize(
    "entry_gate_reason",
    [
        "REGIME_GATE_CASCADE_CONTEXT_SHADOW_ONLY:short:trend_mode:CRVUSDT:15m",
        "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:INJUSDT:1h",
    ],
)
def test_b_grade_exploration_cannot_relax_p0_entry_gate_blocks(entry_gate_reason: str) -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -40.0,
            "strategy_selected_mode": "trend_mode",
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -40.0,
            "strategy_selected_mode": "trend_mode",
            "entry_gate_block_reasons": [entry_gate_reason],
            "local_block_reasons": [f"entry_gate:{entry_gate_reason}"],
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(
            confidence_calibrated=0.68,
            expected_move_after_cost_bps=-40.0,
        ),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )
    assert classification["non_relaxable_entry_gate_reasons"] == [entry_gate_reason]
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False


def test_invalid_admission_feedback_rows_are_quarantined_by_lineage() -> None:
    rows = [
        {
            "trainer_feedback_id": "tf-bad",
            "source_fill_ids": ["fill-bad"],
            "entry_prediction_id": "pred-bad",
            "trainer_consumable": True,
            "quarantine_reason": "NONE",
            "missing_feedback_classifications": [],
            "counts_as_production_grade_training_evidence": True,
        },
        {
            "trainer_feedback_id": "tf-good",
            "source_fill_ids": ["fill-good"],
            "trainer_consumable": True,
            "quarantine_reason": "NONE",
            "missing_feedback_classifications": [],
            "counts_as_production_grade_training_evidence": True,
        },
    ]

    quarantined, status = paper_loop._quarantine_invalid_admission_feedback_rows(  # noqa: SLF001
        rows,
        {"fill-bad", "pred-bad"},
    )

    assert status["status"] == "INVALID_ADMISSION_FEEDBACK_QUARANTINED"
    assert status["invalid_admission_feedback_rows_seen"] == 2
    assert status["invalid_admission_feedback_rows_quarantined"] == 1
    assert status["invalid_admission_feedback_rows_remaining_consumable"] == 1
    assert quarantined[0]["trainer_consumable"] is False
    assert quarantined[0]["quarantine_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )
    assert quarantined[0]["invalid_admission_quarantine_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )
    assert quarantined[0]["paper_admission_quarantine_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )
    assert quarantined[0]["invalid_admission_source_ids_matched"] == [
        "fill-bad",
        "pred-bad",
    ]
    assert paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON in quarantined[0][
        "quarantine_reasons"
    ]
    assert paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_FEEDBACK_CLASSIFICATION in (
        quarantined[0]["missing_feedback_classifications"]
    )
    assert quarantined[0]["counts_as_production_grade_training_evidence"] is False
    assert quarantined[1]["trainer_consumable"] is True
    assert quarantined[1]["quarantine_reason"] == "NONE"


def test_invalid_admission_accepted_rows_are_split_to_quarantine() -> None:
    invalid_reason = "REGIME_GATE_CASCADE_CONTEXT_SHADOW_ONLY:long:trend_mode:BTCUSDT:1m"
    rows = [
        {
            "fill_id": "signal-btc-1m",
            "signal_id": "signal-btc-1m",
            "entry_signal_id": "signal-btc-1m",
            "symbol": "BTCUSDT",
            "entry_price": 100.0,
            "entry_gate_block_reasons": [invalid_reason],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "trainer_consumable": True,
            "counts_as_production_grade_training_evidence": True,
            "counts_as_a_grade_evidence": True,
        },
        {
            "fill_id": "fill-valid",
            "signal_id": "signal-valid",
            "symbol": "ETHUSDT",
            "entry_price": 2500.0,
            "entry_gate_block_reasons": [],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "trainer_consumable": True,
        },
    ]

    valid_rows, quarantine_rows, status = (
        paper_loop._split_invalid_admission_accepted_rows(rows)  # noqa: SLF001
    )
    compact_quarantine = paper_loop._compact_rows_for_state(quarantine_rows)  # noqa: SLF001

    assert valid_rows == [rows[1]]
    assert len(quarantine_rows) == 1
    assert rows[0].get("accepted_fill_quarantined") is None
    assert quarantine_rows[0]["fill_id"] == "signal-btc-1m"
    assert quarantine_rows[0]["accepted_fill_quarantined"] is True
    assert quarantine_rows[0]["accepted_fill_quarantine_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )
    assert quarantine_rows[0]["invalid_admission_entry_gate_block_reasons"] == [
        invalid_reason
    ]
    assert quarantine_rows[0]["trainer_consumable"] is False
    assert quarantine_rows[0]["counts_as_production_grade_training_evidence"] is False
    assert quarantine_rows[0]["counts_as_a_grade_evidence"] is False
    assert status["status"] == "INVALID_ADMISSION_ACCEPTED_FILLS_QUARANTINED"
    assert status["accepted_rows_seen"] == 2
    assert status["valid_accepted_rows"] == 1
    assert status["invalid_admission_accepted_rows_quarantined"] == 1
    assert status["paper_only"] is True
    assert status["places_real_order"] is False
    assert compact_quarantine[0]["accepted_fill_quarantined"] is True
    assert compact_quarantine[0]["accepted_fill_quarantine_reason"] == (
        paper_loop.P0_ENTRY_GATE_NOT_EXPLORATION_RELAXABLE_REASON
    )


def test_priority_bucket_context_matches_strategy_regime_labels_for_paper_only_collection() -> None:
    readiness = {
        "generated_utc": "2026-06-23T20:55:00Z",
        "paper_only_label_collection_priority_buckets": [
            {
                "symbol": "HUSDT",
                "timeframe": "4h",
                "side": "long",
                "strategy": "trend_mode",
                "regime": "TREND",
                "confidence_bucket": "0.6-0.7",
                "closed_economic_outcome_count": 3,
                "sample_count_deficit_to_minimum": 27,
                "priority_reason": (
                    "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                ),
            }
        ],
    }
    priority_index = paper_loop._paper_only_label_collection_priority_index(readiness)  # noqa: SLF001
    intent = {
        "symbol": "HUSDT",
        "timeframe": "4h",
        "side": "long",
        "strategy_id": "trend_mode",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
    }
    allocation = {"model_inputs": {}}

    payload = paper_loop._attach_paper_only_label_collection_priority(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        priority_index=priority_index,
    )

    assert payload is not None
    assert intent["paper_only_label_collection_priority"] is True
    assert intent["paper_only_label_collection_priority_rank"] == 1
    assert intent["paper_only_label_collection_priority_bucket_key"] == (
        "HUSDT|4h|long|trend_mode|TREND|0.6-0.7"
    )
    assert intent["paper_only_label_collection_priority_sample_count_deficit_to_minimum"] == 27
    assert intent["counts_as_a_grade_evidence"] is False
    assert intent["a_grade_promotion_allowed"] is False
    assert intent["live_ready_implication"] is False
    assert allocation["model_inputs"]["paper_only_label_collection_priority"] is True


def test_priority_bucket_candidate_becomes_paper_only_b_grade_label_collection() -> None:
    intent = {
        "symbol": "HUSDT",
        "timeframe": "4h",
        "side": "long",
        "strategy_id": "trend_mode",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
        "expected_move_after_cost_bps": 8.0,
    }
    allocation = _allowed_allocation(
        confidence_calibrated=0.64,
        expected_move_after_cost_bps=8.0,
    )
    priority_index = paper_loop._paper_only_label_collection_priority_index(  # noqa: SLF001
        {
            "generated_utc": "2026-06-23T20:55:00Z",
            "paper_only_label_collection_priority_buckets": [
                {
                    "symbol": "HUSDT",
                    "timeframe": "4h",
                    "side": "long",
                    "strategy": "trend_mode",
                    "regime": "TREND",
                    "confidence_bucket": "0.6-0.7",
                    "closed_economic_outcome_count": 3,
                    "sample_count_deficit_to_minimum": 27,
                    "priority_reason": "PRIORITY_UNDERPOWERED_BUCKET",
                }
            ],
        }
    )
    paper_loop._attach_paper_only_label_collection_priority(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        priority_index=priority_index,
    )

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
        },
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert classification["calibration_label_purpose"] == "B_GRADE_EXPLORATION_OUTCOME_LABEL"
    assert classification["paper_only_label_collection_priority"] is True
    assert classification["paper_only_label_collection_priority_reason"] == "PRIORITY_UNDERPOWERED_BUCKET"
    assert classification["counts_as_a_grade_evidence"] is False
    assert classification["a_grade_promotion_allowed"] is False
    assert classification["live_ready_implication"] is False
    assert classification["risk_budget_fraction_of_normal_adaptive"] > 0.0

    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )

    assert allocation["paper_opportunity_tier_reason"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert allocation["model_inputs"]["paper_only_label_collection_priority"] is True
    assert allocation["model_inputs"]["a_grade_promotion_allowed"] is False
    assert allocation["model_inputs"]["live_ready_implication"] is False
    assert intent["source_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert intent["policy_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert intent["capital_class"] == "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
    assert allocation["source_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert allocation["capital_class"] == "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
    assert allocation["model_inputs"]["source_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert allocation["model_inputs"]["capital_class"] == (
        "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
    )


def test_size_adjusted_trend_entry_is_not_lifecycle_no_trade() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "strategy_regime_labels": ["TREND"],
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_id": "trend_mode",
            "strategy_family": "trend_mode",
            "strategy_subtype": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "entry_reason": "reduce_size_mode",
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.66, expected_move_after_cost_bps=-14.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert "lifecycle_or_no_trade_strategy_reasons" not in classification


def test_size_adjusted_trend_entry_with_reduce_only_router_canonical_mode_is_not_lifecycle_no_trade() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "strategy_regime_labels": ["TREND"],
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_id": "trend_mode",
            "strategy_family": "trend_mode",
            "strategy_subtype": "trend_mode",
            "strategy_mode": "reduce_only_recovery",
            "strategy_canonical_mode": "reduce_only_recovery",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "entry_reason": "trend_mode",
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.66, expected_move_after_cost_bps=-14.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == (
        "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    )
    assert "lifecycle_or_no_trade_strategy_reasons" not in classification


def test_no_trade_strategy_mode_cannot_be_b_grade_executable() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 10.0,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "strategy_router_selected_mode": "no_trade_mode",
            "strategy_regime_labels": ["MODEL_DISAGREEMENT", "NO_TRADE"],
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 10.0,
            "strategy_selected_mode": "no_trade_mode",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.72, expected_move_after_cost_bps=10.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False
    assert "intent.strategy_selected_mode=NO_TRADE" in classification["no_trade_strategy_reasons"]
    assert "strategy_regime_labels_include_NO_TRADE" in classification["no_trade_strategy_reasons"]


def test_no_trade_regime_label_blocks_dynamic_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "market_regime": "MODEL_DISAGREEMENT,NO_TRADE",
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "market_regime_at_entry": "MODEL_DISAGREEMENT,NO_TRADE",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.68, expected_move_after_cost_bps=-9.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert classification["no_trade_strategy_reasons"] == [
        "strategy_regime_labels_include_NO_TRADE"
    ]


def test_canonical_risk_off_strategy_mode_cannot_be_b_grade_entry_evidence() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 14.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 14.0,
            "strategy_mode": "risk_off_no_trade",
            "strategy_canonical_mode": "risk_off_no_trade",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.72, expected_move_after_cost_bps=14.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert "intent.strategy_mode=NO_TRADE" in classification[
        "lifecycle_or_no_trade_strategy_reasons"
    ]


def test_lifecycle_strategy_mode_cannot_be_b_grade_entry_evidence() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "strategy_router_selected_mode": "reduce_size_mode",
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "entry_reason": "reduce_size_mode",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.68, expected_move_after_cost_bps=-9.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert "intent.strategy_router_selected_mode=LIFECYCLE_ACTION" in classification[
        "lifecycle_or_no_trade_strategy_reasons"
    ]
    assert "intent.entry_reason=LIFECYCLE_ACTION" in classification[
        "lifecycle_or_no_trade_strategy_reasons"
    ]


def test_feedback_entry_context_uses_audited_strategy_as_entry_reason() -> None:
    intent = {
        "strategy_selected_mode": "trend_mode",
        "strategy_id": "trend_mode",
        "strategy_family": "trend_mode",
        "strategy_subtype": "trend_mode",
        "strategy_size_adjustment_mode": "reduce_size_mode",
    }

    paper_loop._attach_trainer_feedback_entry_context(  # noqa: SLF001
        intent=intent,
        prediction={},
        strategy_router={
            "selected_mode": "reduce_size_mode",
            "strategy_mode": "trend_continuation",
            "strategy_modes_supported": ["trend_continuation", "risk_off_no_trade"],
            "market_regime": "TREND",
            "regime_features": {
                "trend_strength": 0.81,
                "liquidation_cluster_proximity": 18.0,
            },
            "regime_feature_status": {
                "missing_features_are_explicit": True,
                "missing_features": [],
            },
            "strategy_bucket_key": {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "strategy_mode": "trend_continuation",
                "market_regime": "TREND",
            },
            "bucket_quarantined": False,
            "bucket_quarantine_reason": None,
            "bucket_performance_state": {
                "profit_factor": 1.4,
                "expectancy_bps": 8.0,
                "negative_bucket": False,
            },
            "paper_loss_quarantine_status": "ACTIVE_WITH_QUARANTINES",
            "paper_loss_quarantine_blocked_bucket_keys": ["side:short"],
            "paper_loss_quarantine_candidate_bucket_keys": ["side:short", "timeframe:15m"],
            "paper_loss_quarantine_matched_bucket_keys": ["side:short"],
            "strategy_feature_snapshot_status": "ATTACHED_PIT_VALID_FEATURE_SNAPSHOT",
            "strategy_feature_snapshot_id": "v2_fsnap_test",
            "strategy_feature_snapshot_available_at": "2026-07-06T02:15:33Z",
            "strategy_feature_snapshot_feature_cutoff": "2026-07-06T01:59:59Z",
            "strategy_feature_snapshot_candle_closed_confirmed": True,
            "strategy_feature_snapshot_latest_unclosed_kline_excluded": True,
            "strategy_regime_feature_source_map": {
                "trend_strength": "feature_snapshot.ta_ADX"
            },
            "strategy_cross_asset_context_status": (
                "ATTACHED_PIT_BTC_ETH_SOL_PREDICTION_GRID"
            ),
            "strategy_cross_asset_context_source": "PIT_PREDICTION_GRID",
            "regime_labels": ["TREND"],
            "explanation": {},
        },
        allocation={"model_inputs": {}},
        portfolio_context={"drawdown_bps": 0.0},
    )

    assert intent["strategy_selected_mode"] == "trend_mode"
    assert intent["strategy_size_adjustment_mode"] == "reduce_size_mode"
    assert intent["entry_reason"] == "trend_mode"
    assert intent["strategy_mode"] == "trend_continuation"
    assert intent["strategy_canonical_mode"] == "trend_continuation"
    assert intent["market_regime_at_entry"] == "TREND"
    assert intent["strategy_regime_feature_status"]["missing_features_are_explicit"] is True
    assert intent["strategy_bucket_key"]["strategy_mode"] == "trend_continuation"
    assert intent["strategy_bucket_performance_state"]["profit_factor"] == 1.4
    assert intent["strategy_paper_loss_quarantine_status"] == "ACTIVE_WITH_QUARANTINES"
    assert intent["strategy_paper_loss_quarantine_blocked_bucket_keys"] == ["side:short"]
    assert intent["strategy_paper_loss_quarantine_matched_bucket_keys"] == ["side:short"]
    assert intent["strategy_feature_snapshot_status"] == "ATTACHED_PIT_VALID_FEATURE_SNAPSHOT"
    assert intent["strategy_feature_snapshot_id"] == "v2_fsnap_test"
    assert intent["strategy_feature_snapshot_candle_closed_confirmed"] is True
    assert intent["strategy_feature_snapshot_latest_unclosed_kline_excluded"] is True
    assert intent["strategy_regime_feature_source_map"] == {
        "trend_strength": "feature_snapshot.ta_ADX"
    }
    assert intent["strategy_cross_asset_context_status"] == (
        "ATTACHED_PIT_BTC_ETH_SOL_PREDICTION_GRID"
    )
    assert intent["strategy_cross_asset_context_source"] == "PIT_PREDICTION_GRID"


def test_strategy_router_provenance_survives_publication_and_compaction() -> None:
    provenance = {
        "strategy_feature_snapshot_status": "ATTACHED_PIT_VALID_FEATURE_SNAPSHOT",
        "strategy_feature_snapshot_id": "v2_fsnap_publish",
        "strategy_feature_snapshot_available_at": "2026-07-06T02:15:33Z",
        "strategy_feature_snapshot_feature_cutoff": "2026-07-06T01:59:59Z",
        "strategy_feature_snapshot_candle_closed_confirmed": True,
        "strategy_feature_snapshot_latest_unclosed_kline_excluded": True,
        "strategy_regime_feature_source_map": {
            "trend_strength": "feature_snapshot.ta_ADX"
        },
        "strategy_cross_asset_context_status": (
            "ATTACHED_PIT_BTC_ETH_SOL_PREDICTION_GRID"
        ),
        "strategy_cross_asset_context_source": "PIT_PREDICTION_GRID",
        "strategy_cross_asset_available_symbol_count": 3,
    }
    intent = {
        "intent_id": "fill-publish",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "long",
        "paper_opportunity_tier": "NO_TRADE",
        "strategy_regime_features": {"trend_strength": 0.42},
        "strategy_regime_feature_status": {
            "missing_features_are_explicit": True,
            "missing_features": ["atr_percentile", "fakeout_reversal_probability"],
        },
        **provenance,
    }
    allocation = {
        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
        "paper_opportunity_tier": "NO_TRADE",
    }

    paper_loop._attach_paper_allocation_decision_context(  # noqa: SLF001
        intent,
        allocation,
    )
    allocation_rows = paper_loop._current_cycle_candidate_allocation_rows(  # noqa: SLF001
        intents=[{**intent, "adaptive_allocation": allocation}],
    )
    compact_rows = paper_loop._compact_rows_for_state(allocation_rows)  # noqa: SLF001
    feedback_context = paper_loop._entry_feedback_context_by_fill_id(  # noqa: SLF001
        compact_rows,
    )

    for field, value in provenance.items():
        assert allocation[field] == value
        assert allocation_rows[0][field] == value
        assert compact_rows[0][field] == value
        assert feedback_context["fill-publish"][field] == value


def test_strategy_router_feature_snapshot_context_maps_pit_regime_inputs() -> None:
    envelope = {
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "decision_time": "2026-07-06T02:18:07.712Z",
    }
    feature_snapshot = {
        "feature_snapshot_id": "v2_fsnap_test",
        "available_at": "2026-07-06T02:15:33.179Z",
        "feature_cutoff": "2026-07-06T01:59:59.999Z",
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "features": {
            "ta_ADX": 42.0,
            "ta_HT_TRENDMODE_integer": 0.0,
            "true_range_pct": 0.031,
            "atr_percentile": 0.73,
            "expected_funding_bps": 1.5,
            "oi_change_pct": -2.2,
            "long_short_ratio": 2.48,
            "liquidation_sweep_target_short_distance_bps": 59.49,
            "liquidation_sweep_target_long_distance_bps": 23.8,
            "liquidation_short_strength": 29321.9,
            "liquidation_long_strength": 7971.1,
            "depth_imbalance": 0.62,
            "bid_ask_spread_bps": 1.29,
            "expected_slippage_bps": 0.44,
            "orderbook_depth_usd": 270466.33,
            "bid_depth_usd": 284664.97,
            "ask_depth_usd": 270466.33,
            "taker_buy_quote_vol": 60.0,
            "quote_volume": 100.0,
        },
    }

    paper_loop._attach_strategy_router_feature_snapshot_context(  # noqa: SLF001
        envelope,
        feature_snapshot,
    )
    volatility_liquidity = paper_loop._build_volatility_liquidity_state(  # noqa: SLF001
        signal={},
        prediction={},
        feature_snapshot=feature_snapshot,
    )

    assert envelope["strategy_feature_snapshot_status"] == "ATTACHED_PIT_VALID_FEATURE_SNAPSHOT"
    assert envelope["strategy_feature_snapshot_id"] == "v2_fsnap_test"
    assert envelope["strategy_feature_snapshot_candle_closed_confirmed"] is True
    assert envelope["strategy_feature_snapshot_latest_unclosed_kline_excluded"] is True
    assert envelope["trend_strength"] == 0.42
    assert envelope["range_chop_score"] == 1.0
    assert envelope["volatility_expansion"] == 0.031
    assert envelope["atr_percentile"] == 0.73
    assert envelope["funding_skew"] == 1.5
    assert envelope["open_interest_change"] == -2.2
    assert envelope["long_short_ratio"] == 2.48
    assert envelope["liquidation_cluster_proximity"] == 23.8
    assert envelope["orderbook_imbalance"] == 0.62
    assert envelope["aggressive_flow"] == pytest.approx(0.2)
    assert envelope["liquidation_context"]["source"] == "PIT_VALID_FEATURE_SNAPSHOT"
    assert envelope["liquidation_context"]["nearest_distance_bps"] == 23.8
    assert envelope["microstructure_context"]["order_flow_imbalance"] == pytest.approx(0.2)
    assert envelope["oi_funding_context"]["long_short_ratio"] == 2.48
    assert envelope["strategy_regime_feature_source_map"]["trend_strength"] == "feature_snapshot.ta_ADX"
    assert envelope["strategy_regime_feature_source_map"]["atr_percentile"] == "feature_snapshot.atr_percentile"
    assert volatility_liquidity["bid_ask_spread_bps"] == 1.29
    assert volatility_liquidity["orderbook_depth_usd"] == 270466.33
    assert volatility_liquidity["expected_slippage_bps"] == 0.44


def test_strategy_router_feature_snapshot_context_marks_unavailable_snapshot() -> None:
    envelope: dict[str, object] = {}

    paper_loop._attach_strategy_router_feature_snapshot_context(  # noqa: SLF001
        envelope,
        {"features": {}, "unavailable_reason": "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME"},
    )

    assert envelope == {
        "strategy_feature_snapshot_status": "UNAVAILABLE_FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME"
    }


def test_strategy_router_microstructure_context_uses_pit_fakeout_probability() -> None:
    redis_client = _FakeRedis(
        {
            "v2:microstructure:trust_score:DOGEUSDT:1m": {
                "symbol": "DOGEUSDT",
                "timeframe": "1m",
                "available_at": "2026-07-06T02:29:45Z",
                "generated_at": "2026-07-06T02:29:50Z",
                "microstructure_trust_score": 0.71,
                "orderbook_trust_score": 0.69,
                "microstructure_action": "ALLOW",
                "sweep_risk_score": 0.33,
                "post_sweep_reversal_probability": 0.42,
            }
        }
    )

    trust = paper_loop._read_v2_microstructure_trust(  # noqa: SLF001
        redis_client,
        "DOGEUSDT",
        decision_time="2026-07-06T02:30:00Z",
        timeframe="15m",
    )
    envelope: dict[str, object] = {}
    paper_loop._attach_strategy_router_microstructure_context(envelope, trust)  # noqa: SLF001

    assert trust["microstructure_trust_status"] == "MICROSTRUCTURE_TRUST_SCORE_FOUND"
    assert envelope["fakeout_reversal_probability"] == 0.42
    assert envelope["microstructure_context"]["post_sweep_reversal_probability"] == 0.42
    assert envelope["strategy_regime_feature_source_map"] == {
        "fakeout_reversal_probability": (
            "v2:microstructure:trust_score:DOGEUSDT:1m.post_sweep_reversal_probability"
        )
    }


def test_strategy_router_microstructure_context_rejects_future_fakeout_probability() -> None:
    redis_client = _FakeRedis(
        {
            "v2:microstructure:trust_score:DOGEUSDT:1m": {
                "symbol": "DOGEUSDT",
                "timeframe": "1m",
                "available_at": "2026-07-06T02:30:10Z",
                "generated_at": "2026-07-06T02:30:11Z",
                "microstructure_trust_score": 0.71,
                "microstructure_action": "ALLOW",
                "post_sweep_reversal_probability": 0.42,
            }
        }
    )

    trust = paper_loop._read_v2_microstructure_trust(  # noqa: SLF001
        redis_client,
        "DOGEUSDT",
        decision_time="2026-07-06T02:30:00Z",
        timeframe="15m",
    )
    envelope: dict[str, object] = {}
    paper_loop._attach_strategy_router_microstructure_context(envelope, trust)  # noqa: SLF001

    assert trust["microstructure_trust_status"] == (
        "REJECTED_MICROSTRUCTURE_TRUST_AFTER_DECISION"
    )
    assert "fakeout_reversal_probability" not in envelope
    assert envelope["microstructure_context"]["microstructure_trust_status"] == (
        "REJECTED_MICROSTRUCTURE_TRUST_AFTER_DECISION"
    )


def test_strategy_router_cross_asset_context_uses_pit_prediction_grid() -> None:
    envelope = {"decision_time": "2026-07-06T02:30:00Z", "timeframe": "15m"}
    predictions_by_symbol = {
        "BTCUSDT": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "prediction_id": "btc-15m",
                "available_at": "2026-07-06T02:29:00Z",
                "feature_cutoff": "2026-07-06T02:14:59Z",
                "expected_move_after_cost_bps": -10.0,
                "selected_action": "short",
            }
        ],
        "ETHUSDT": [
            {
                "symbol": "ETHUSDT",
                "timeframe": "15m",
                "prediction_id": "eth-15m",
                "available_at": "2026-07-06T02:29:05Z",
                "feature_cutoff": "2026-07-06T02:14:59Z",
                "expected_move_after_cost_bps": -8.0,
                "selected_action": "short",
            }
        ],
        "SOLUSDT": [
            {
                "symbol": "SOLUSDT",
                "timeframe": "15m",
                "prediction_id": "sol-15m",
                "available_at": "2026-07-06T02:29:10Z",
                "feature_cutoff": "2026-07-06T02:14:59Z",
                "expected_move_after_cost_bps": 2.0,
                "selected_action": "long",
            }
        ],
    }

    paper_loop._attach_strategy_router_cross_asset_context(  # noqa: SLF001
        envelope,
        predictions_by_symbol,
    )

    assert envelope["strategy_cross_asset_context_status"] == (
        "ATTACHED_PIT_BTC_ETH_SOL_PREDICTION_GRID"
    )
    assert envelope["cross_asset_btc_eth_sol_regime"] == "btc_eth_sol_risk_off"
    assert envelope["market_wide_risk"] == "risk_off"
    assert envelope["public_intel_context"]["source"] == "PIT_PREDICTION_GRID"
    assert envelope["public_intel_context"]["market_breadth_score"] == pytest.approx(
        -1 / 3
    )
    assert len(envelope["public_intel_context"]["source_rows"]) == 3


def test_strategy_router_cross_asset_context_rejects_future_prediction_rows() -> None:
    envelope = {"decision_time": "2026-07-06T02:30:00Z", "timeframe": "15m"}
    predictions_by_symbol = {
        "BTCUSDT": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "available_at": "2026-07-06T02:31:00Z",
                "feature_cutoff": "2026-07-06T02:14:59Z",
                "expected_move_after_cost_bps": -10.0,
            }
        ],
        "ETHUSDT": [
            {
                "symbol": "ETHUSDT",
                "timeframe": "15m",
                "available_at": "2026-07-06T02:29:00Z",
                "feature_cutoff": "2026-07-06T02:31:00Z",
                "expected_move_after_cost_bps": -8.0,
            }
        ],
    }

    paper_loop._attach_strategy_router_cross_asset_context(  # noqa: SLF001
        envelope,
        predictions_by_symbol,
    )

    assert envelope["strategy_cross_asset_context_status"] == (
        "INSUFFICIENT_PIT_BTC_ETH_SOL_PREDICTION_ROWS"
    )
    assert envelope["strategy_cross_asset_available_symbol_count"] == 0
    assert "public_intel_context" not in envelope


def test_positive_edge_below_a_grade_row_becomes_dynamic_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={"selected_action": "long", "confidence_calibrated": 0.65, "expected_move_after_cost_bps": 12.0},
        intent={"side": "long", "confidence_calibrated": 0.65, "expected_move_after_cost_bps": 12.0},
        allocation=_allowed_allocation(),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False


def test_negative_edge_trial_is_no_trade_not_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "paper_confidence_threshold_trial": True,
            "confidence_calibrated": 0.65,
            "expected_move_after_cost_bps": -1.0,
        },
        intent={"confidence_calibrated": 0.65, "expected_move_after_cost_bps": -1.0},
        allocation=_allowed_allocation(expected_move_after_cost_bps=-1.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"


def _phase1_closed_trade_row(
    realized_bps: float,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    strategy_id: str = "trend_continuation",
    regime: str = "trend",
    confidence: float = 0.90,
    close_reason: str = "TAKE_PROFIT",
    tier: str = paper_loop.PAPER_TIER_B_GRADE_EXPLORATION,
) -> dict[str, object]:
    return {
        "paper_only": True,
        "paper_opportunity_tier": tier,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": "long",
        "strategy_id": strategy_id,
        "market_regime": regime,
        "confidence_calibrated": confidence,
        "realized_pnl_bps": realized_bps,
        "realized_pnl_usd": realized_bps / 10.0,
        "gross_notional_usd": 1000.0,
        "close_reason": close_reason,
    }


def _high_confidence_loss_fixture_rows() -> list[dict[str, object]]:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/high_confidence_loss_cluster_current_session.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return list(payload["rows"])


def _active_guardian_gate() -> dict[str, object]:
    return {
        "status": "ACTIVE",
        "a_grade_new_entries_allowed": True,
        "allowed_runtime_actions": ["new_entry", "reduce", "close"],
    }


def test_paper_performance_circuit_breaker_blocks_negative_rolling_25() -> None:
    rows = [
        _phase1_closed_trade_row(10.0, confidence=0.70, close_reason="TAKE_PROFIT")
        for _ in range(10)
    ] + [
        _phase1_closed_trade_row(-10.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(15)
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert status["state"] == "HALTED_PERFORMANCE"
    assert status["new_entries_allowed"] is False
    assert "ROLLING_25_PF_BELOW_1_AND_EXPECTANCY_NON_POSITIVE" in status["block_reasons"]
    assert status["pass_conditions"]["negative_pf_blocks_new_entries"] is True
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_paper_performance_governor_mirror_uses_current_circuit_breaker() -> None:
    rows = [
        _phase1_closed_trade_row(-10.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(5)
    ]
    circuit = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-06T03:30:00Z",
    )

    governor = paper_loop._paper_performance_governor_status_from_circuit_breaker(  # noqa: SLF001
        circuit,
        generated_utc="2026-07-06T03:30:00Z",
    )

    assert governor["schema_version"] == "paper_performance_governor_status_v2"
    assert governor["generated_utc"] == "2026-07-06T03:30:00Z"
    assert governor["state"] == "HALTED_PERFORMANCE"
    assert governor["new_entries_allowed"] is False
    assert governor["closed_outcome_count"] == 5
    assert governor["profit_factor"] == circuit["aggregate"]["profit_factor"]
    assert governor["notional_weighted_expectancy_bps"] == circuit["aggregate"][
        "notional_weighted_expectancy_bps"
    ]
    assert "CLOSED_5_PROFIT_FACTOR_BELOW_1" in governor["state_reasons"]
    assert governor["pass_conditions"]["mirrors_current_performance_circuit_breaker"] is True
    assert governor["paper_only"] is True
    assert governor["places_real_order"] is False
    assert governor["writes_legacy_redis"] is False
    assert governor["exchange_action_taken"] is False


def test_paper_new_entry_emergency_halt_mirror_tracks_current_bleed_state() -> None:
    rows = [
        _phase1_closed_trade_row(-10.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(5)
    ]
    circuit = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-06T03:30:00Z",
    )
    bleed = paper_loop._paper_bleed_halt_status(  # noqa: SLF001
        circuit,
        generated_utc="2026-07-06T03:30:00Z",
    )

    emergency = paper_loop._paper_new_entry_emergency_halt_status_from_performance(  # noqa: SLF001
        circuit,
        bleed,
        generated_utc="2026-07-06T03:30:00Z",
    )

    assert emergency["schema_version"] == "paper_new_entry_emergency_halt_status_v2"
    assert emergency["generated_utc"] == "2026-07-06T03:30:00Z"
    assert emergency["status"] == "HALTED"
    assert emergency["allow_new_entries"] is False
    assert emergency["new_entries_allowed"] is False
    assert emergency["performance_governor_v2_state"] == "HALTED_PERFORMANCE"
    assert emergency["bleed_halt_state"] == "HALTED"
    assert "CLOSED_5_EXPECTANCY_NON_POSITIVE" in emergency["halt_reasons"]
    assert emergency["paper_only"] is True
    assert emergency["places_real_order"] is False
    assert emergency["writes_legacy_redis"] is False
    assert emergency["exchange_action_taken"] is False


def test_paper_new_entry_emergency_halt_mirror_allows_clean_bootstrap_state() -> None:
    circuit = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        [],
        generated_utc="2026-07-06T03:30:00Z",
    )
    bleed = paper_loop._paper_bleed_halt_status(  # noqa: SLF001
        circuit,
        generated_utc="2026-07-06T03:30:00Z",
    )

    emergency = paper_loop._paper_new_entry_emergency_halt_status_from_performance(  # noqa: SLF001
        circuit,
        bleed,
        generated_utc="2026-07-06T03:30:00Z",
    )

    assert emergency["status"] == "ACTIVE"
    assert emergency["allow_new_entries"] is True
    assert emergency["halt_reason"] is None
    assert emergency["halt_reasons"] == []
    assert emergency["recovery_session_lift_allowed"] is True
    assert emergency["routes_to_live"] is False


def test_paper_effective_entry_gate_blocks_when_performance_halted() -> None:
    rows = [
        _phase1_closed_trade_row(-10.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(5)
    ]
    circuit = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-06T03:30:00Z",
    )
    bleed = paper_loop._paper_bleed_halt_status(  # noqa: SLF001
        circuit,
        generated_utc="2026-07-06T03:30:00Z",
    )
    governor = paper_loop._paper_performance_governor_status_from_circuit_breaker(  # noqa: SLF001
        circuit,
        generated_utc="2026-07-06T03:30:00Z",
    )
    emergency = paper_loop._paper_new_entry_emergency_halt_status_from_performance(  # noqa: SLF001
        circuit,
        bleed,
        generated_utc="2026-07-06T03:30:00Z",
    )

    effective = paper_loop._paper_effective_entry_gate_status(  # noqa: SLF001
        paper_entry_freeze={
            "schema_version": "paper_entry_freeze_v1",
            "paper_new_entries_halted": False,
            "new_entries_allowed": True,
            "reason": None,
            "source": "v2:paper:entry_freeze",
        },
        performance_circuit_breaker_status=circuit,
        bleed_halt_status=bleed,
        performance_governor_status=governor,
        new_entry_emergency_halt_status=emergency,
        churn_equity_bleed_governor_status={
            "schema_version": "paper_churn_equity_bleed_governor_status_v1",
            "state": "ACTIVE",
            "new_entries_allowed": True,
        },
        generated_utc="2026-07-06T03:30:00Z",
    )

    assert effective["schema_version"] == "paper_effective_entry_gate_status_v1"
    assert effective["status"] == "HALTED"
    assert effective["paper_new_entries_halted"] is True
    assert effective["new_entries_allowed"] is False
    assert "performance_circuit_breaker" in effective["blocking_components"]
    assert "CLOSED_5_PROFIT_FACTOR_BELOW_1" in effective["halt_reasons"]
    assert (
        effective["component_statuses"]["manual_or_portfolio_freeze"][
            "new_entries_allowed"
        ]
        is True
    )
    assert effective["paper_only"] is True
    assert effective["routes_to_live"] is False
    assert effective["places_real_order"] is False


def test_paper_performance_circuit_breaker_blocks_pf_below_one_even_if_expectancy_positive() -> None:
    rows = [
        {
            **_phase1_closed_trade_row(
                -10.0,
                confidence=0.70,
                close_reason="MODEL_STOP",
            ),
            "gross_notional_usd": 100.0,
        }
        for _ in range(4)
    ] + [
        {
            **_phase1_closed_trade_row(
                30.0,
                confidence=0.70,
                close_reason="TAKE_PROFIT",
            ),
            "gross_notional_usd": 1000.0,
        }
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert status["rolling_25"]["profit_factor_numeric"] < 1.0
    assert status["rolling_25"]["notional_weighted_expectancy_bps"] > 0.0
    assert status["new_entries_allowed"] is False
    assert "CLOSED_5_PROFIT_FACTOR_BELOW_1" in status["block_reasons"]
    assert status["pass_conditions"]["negative_pf_blocks_new_entries"] is True


def test_paper_performance_circuit_breaker_blocks_expectancy_non_positive_even_if_pf_above_one() -> None:
    rows = [
        {
            **_phase1_closed_trade_row(
                10.0,
                confidence=0.70,
                close_reason="TAKE_PROFIT",
            ),
            "gross_notional_usd": 100.0,
        }
        for _ in range(4)
    ] + [
        {
            **_phase1_closed_trade_row(
                -30.0,
                confidence=0.70,
                close_reason="MODEL_STOP",
            ),
            "gross_notional_usd": 1000.0,
        }
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert status["rolling_25"]["profit_factor_numeric"] > 1.0
    assert status["rolling_25"]["notional_weighted_expectancy_bps"] <= 0.0
    assert status["new_entries_allowed"] is False
    assert "CLOSED_5_EXPECTANCY_NON_POSITIVE" in status["block_reasons"]
    assert status["pass_conditions"]["negative_expectancy_blocks_new_entries"] is True


def test_paper_performance_circuit_breaker_blocks_high_confidence_loss_cluster_even_with_positive_edge() -> None:
    rows = [
        _phase1_closed_trade_row(
            100.0,
            symbol=f"WIN{idx}USDT",
            confidence=0.74,
            close_reason="TIER_2_TRAILING_STOP",
        )
        for idx in range(3)
    ] + [
        _phase1_closed_trade_row(
            -10.0,
            symbol="CAKEUSDT",
            confidence=0.71,
            close_reason="TIER_1_ATR_VOLATILITY_STOP",
        ),
        _phase1_closed_trade_row(
            -10.0,
            symbol="AVNTUSDT",
            confidence=0.78,
            close_reason="TIER_2_MFE_BREAKEVEN_PROTECTION",
        ),
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-07T18:45:00Z",
    )

    cluster = status["recovery_high_confidence_loss_cluster_status"]
    assert status["aggregate"]["profit_factor_numeric"] > 1.0
    assert status["aggregate"]["notional_weighted_expectancy_bps"] > 0.0
    assert cluster["cluster_detected"] is True
    assert cluster["high_confidence_min_score"] == pytest.approx(0.70)
    assert cluster["high_confidence_loss_count"] == 2
    assert status["new_entries_allowed"] is False
    assert "HIGH_CONFIDENCE_LOSS_CLUSTER" in status["block_reasons"]
    assert (
        status["pass_conditions"]["high_confidence_loss_cluster_blocks_new_entries"]
        is True
    )
    assert status["paper_only"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_high_confidence_loss_cluster_blocks_new_entries() -> None:
    rows = _high_confidence_loss_fixture_rows()

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-07T21:20:00Z",
    )

    cluster = status["recovery_high_confidence_loss_cluster_status"]
    assert cluster["cluster_detected"] is True
    assert cluster["high_confidence_min_score"] == pytest.approx(0.70)
    assert cluster["high_confidence_loss_count"] == len(rows)
    assert status["new_entries_allowed"] is False
    assert "HIGH_CONFIDENCE_LOSS_CLUSTER" in status["block_reasons"]
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_high_confidence_loss_cluster_forces_shadow_only_not_reduced_size(
    monkeypatch,
) -> None:
    rows = _high_confidence_loss_fixture_rows()
    # Pin the verified-repair epoch out: this test asserts the behavior when
    # the fixture losses ARE current blocking evidence (post-repair losses
    # re-block instantly; the repo-level epoch artifact must not neuter them).
    monkeypatch.setattr(
        paper_loop, "_paper_verified_exit_repair_deployed_utc", lambda: None
    )
    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-07T21:20:00Z",
    )
    cake = next(row for row in rows if row["symbol"] == "CAKEUSDT")
    intent = {
        "symbol": cake["symbol"],
        "timeframe": cake["timeframe"],
        "side": cake["side"],
        "strategy_id": cake["strategy_id"],
        "market_regime_at_entry": cake["market_regime_at_entry"],
        "confidence_calibrated": cake["confidence_calibrated"],
        "expected_move_after_cost_bps": 30.0,
        "paper_only": True,
        "places_real_order": False,
        "production_grade_cost_flag": True,
        "microstructure_action": "REDUCE_SIZE",
        "public_orderbook_trust_score": 0.51,
        "composite_microstructure_trust_score": 0.52,
        "bootstrap_reduced_size_paper_only": True,
    }

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={"selected_action": "long", "expected_move_after_cost_bps": 30.0},
        intent=intent,
        allocation=_allowed_allocation(confidence_calibrated=0.72),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate=_active_guardian_gate(),
        bucket_quarantine_status=status["bucket_quarantine_status"],
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY"
    )
    assert classification["paper_fill_allowed_source"] == (
        "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY"
    )
    assert classification["counts_as_final_a_plus"] is False
    assert classification["routes_to_live"] is False
    assert "side:long" in classification[
        "paper_bucket_quarantine_matched_blocked_bucket_keys"
    ]


def test_reduced_size_bootstrap_requires_guardian_new_entry_approval() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 18.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 18.0,
            "paper_only": True,
            "places_real_order": False,
            "production_grade_cost_flag": True,
            "microstructure_action": "REDUCE_SIZE",
            "public_orderbook_trust_score": 0.51,
            "composite_microstructure_trust_score": 0.52,
            "bootstrap_reduced_size_paper_only": True,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.72),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={},
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "REDUCED_SIZE_BOOTSTRAP_REQUIRES_GUARDIAN_NEW_ENTRIES_ALLOWED"
    )
    assert classification["pre_guardian_paper_opportunity_tier"] == (
        paper_loop.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE
    )
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_halted_guardian_blocks_reduced_size_bootstrap() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.78,
            "expected_move_after_cost_bps": -17.0,
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.78,
            "expected_move_after_cost_bps": -17.0,
            "paper_only": True,
            "places_real_order": False,
            "production_grade_cost_flag": True,
            "microstructure_action": "REDUCE_SIZE",
            "public_orderbook_trust_score": 0.51,
            "composite_microstructure_trust_score": 0.52,
            "bootstrap_reduced_size_paper_only": True,
        },
        allocation=_allowed_allocation(
            confidence_calibrated=0.78,
            expected_move_after_cost_bps=-17.0,
        ),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={
            "status": "A_GRADE_HALTED_PERFORMANCE",
            "a_grade_new_entries_allowed": True,
            "allowed_runtime_actions": ["new_entry", "reduce", "close"],
        },
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == (
        "REDUCED_SIZE_BOOTSTRAP_REQUIRES_GUARDIAN_NEW_ENTRIES_ALLOWED"
    )
    assert classification["continuous_edge_guardian_status"] == (
        "A_GRADE_HALTED_PERFORMANCE"
    )
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_high_confidence_loss_bucket_does_not_block_unrelated_bucket_when_bucket_specific_recovery_enabled() -> None:
    bucket_status = {
        "status": "ACTIVE_WITH_QUARANTINES",
        "blocked_bucket_keys": [
            "CAKEUSDT|5m|breakout_mode|BREAKOUT,HIGH_VOLATILITY,TREND"
        ],
        "quarantined_buckets": [
            {
                "bucket_key": "CAKEUSDT|5m|breakout_mode|BREAKOUT,HIGH_VOLATILITY,TREND",
                "bucket_type": "exact_context",
                "state": "QUARANTINED",
                "block_reasons": ["HIGH_CONFIDENCE_LOSS_RATE_ABOVE_ADAPTIVE_BOUND"],
                "candidate_blocking": True,
            }
        ],
    }

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={"selected_action": "long", "expected_move_after_cost_bps": 20.0},
        intent={
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "side": "long",
            "strategy_id": "breakout_mode",
            "market_regime_at_entry": "BREAKOUT,HIGH_VOLATILITY,TREND",
            "confidence_calibrated": 0.73,
            "expected_move_after_cost_bps": 20.0,
            "paper_only": True,
            "places_real_order": False,
            "production_grade_cost_flag": True,
            "microstructure_action": "REDUCE_SIZE",
            "public_orderbook_trust_score": 0.51,
            "composite_microstructure_trust_score": 0.52,
            "bootstrap_reduced_size_paper_only": True,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.73),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate=_active_guardian_gate(),
        bucket_quarantine_status=bucket_status,
        preemptive_decision=_allow_preemptive_decision(),
    )

    assert classification["paper_opportunity_tier"] == (
        paper_loop.PAPER_TIER_A_PLUS_BOOTSTRAP_REDUCED_SIZE
    )
    assert "paper_bucket_quarantine_matched_blocked_bucket_keys" not in classification
    assert classification["routes_to_live"] is False
    assert classification["places_real_order"] is False


def test_high_confidence_loss_cluster_preserves_close_reduce_only() -> None:
    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        _high_confidence_loss_fixture_rows(),
        generated_utc="2026-07-07T21:20:00Z",
    )

    assert status["new_entries_allowed"] is False
    assert status["allow_close"] is True
    assert status["allow_reduce"] is True
    assert status["allow_mark_to_market"] is True
    assert status["allow_feedback_recording"] is True
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False


def test_paper_performance_circuit_breaker_blocks_negative_rolling_50_expectancy() -> None:
    rows = [
        _phase1_closed_trade_row(5.0, confidence=0.70, close_reason="TAKE_PROFIT")
        for _ in range(25)
    ] + [
        _phase1_closed_trade_row(-5.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(25)
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert status["new_entries_allowed"] is False
    assert "ROLLING_50_EXPECTANCY_NON_POSITIVE" in status["block_reasons"]
    assert status["pass_conditions"]["negative_expectancy_blocks_new_entries"] is True


def test_bucket_quarantine_blocks_same_bad_bucket_reentry() -> None:
    rows = [
        _phase1_closed_trade_row(
            -12.0,
            symbol="ETHUSDT",
            timeframe="15m",
            strategy_id="breakout_squeeze",
            regime="squeeze",
            confidence=0.94,
            close_reason="MODEL_STOP",
        ),
        _phase1_closed_trade_row(
            -8.0,
            symbol="ETHUSDT",
            timeframe="15m",
            strategy_id="breakout_squeeze",
            regime="squeeze",
            confidence=0.93,
            close_reason="MODEL_STOP",
        ),
    ]
    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )
    intent = {
        "paper_only": True,
        "symbol": "ETHUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "breakout_squeeze",
        "market_regime": "squeeze",
    }
    allocation = _allowed_allocation()

    blocked = paper_loop._paper_block_new_entry_by_performance_circuit(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        performance_circuit_breaker_status=status,
    )

    quarantined_by_key = {
        row["bucket_key"]: row
        for row in status["bucket_quarantine_status"]["quarantined_buckets"]
    }
    assert "ETHUSDT|15m|breakout_squeeze|squeeze" in quarantined_by_key
    assert "HIGH_CONFIDENCE_LOSS_RATE_ABOVE_ADAPTIVE_BOUND" in quarantined_by_key[
        "ETHUSDT|15m|breakout_squeeze|squeeze"
    ]["block_reasons"]
    assert blocked is True
    assert intent["paper_fill_allowed"] is False
    assert intent["places_real_order"] is False
    assert intent["routes_to_live"] is False
    assert allocation["allocator_decision"] == "BLOCK_PAPER_PERFORMANCE_CIRCUIT_BREAKER"


def test_negative_phase3_side_and_strategy_regime_buckets_block_reentry() -> None:
    rows = [
        {
            **_phase1_closed_trade_row(
                -10.0 - idx,
                symbol=symbol,
                timeframe="1h" if idx < 3 else "15m",
                strategy_id="trend_mode",
                regime="TREND",
                confidence=0.62,
                close_reason="MODEL_STOP",
            ),
            "side": "short",
        }
        for idx, symbol in enumerate(
            ["BARDUSDT", "CRVUSDT", "DASHUSDT", "INJUSDT", "WLDUSDT"]
        )
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )
    quarantined_by_key = {
        row["bucket_key"]: row
        for row in status["bucket_quarantine_status"]["quarantined_buckets"]
    }

    assert "BUCKET_QUARANTINE_ACTIVE" in status["block_reasons"]
    assert "side:short" in quarantined_by_key
    assert "strategy_regime:trend_mode|TREND" in quarantined_by_key
    assert "NEGATIVE_EXPECTANCY_SIDE_BUCKET" in quarantined_by_key[
        "side:short"
    ]["block_reasons"]
    assert "NEGATIVE_PROFIT_FACTOR_STRATEGY_REGIME_BUCKET" in quarantined_by_key[
        "strategy_regime:trend_mode|TREND"
    ]["block_reasons"]

    intent = {
        "paper_only": True,
        "symbol": "NEWUSDT",
        "timeframe": "4h",
        "side": "short",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
    }
    allocation = _allowed_allocation()

    blocked = paper_loop._paper_block_new_entry_by_performance_circuit(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        performance_circuit_breaker_status=status,
    )

    assert blocked is True
    assert "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY" in intent[
        "paper_performance_circuit_breaker_block_reasons"
    ]
    assert "side:short" in intent[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ]
    assert "strategy_regime:trend_mode|TREND" in intent[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ]
    assert intent["paper_fill_allowed"] is False
    assert allocation["allocator_decision"] == "BLOCK_PAPER_PERFORMANCE_CIRCUIT_BREAKER"


def test_atr_stop_loss_cluster_quarantines_matching_bucket() -> None:
    rows = [
        _phase1_closed_trade_row(
            -7.0,
            symbol="SOLUSDT",
            timeframe="1m",
            strategy_id="range_scalp",
            regime="chop",
            confidence=0.72,
            close_reason="TIER_1_ATR_VOLATILITY_STOP",
        ),
        _phase1_closed_trade_row(
            -9.0,
            symbol="SOLUSDT",
            timeframe="1m",
            strategy_id="range_scalp",
            regime="chop",
            confidence=0.74,
            close_reason="TIER_1_ATR_VOLATILITY_STOP",
        ),
    ]

    status = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert status["status"] == "ACTIVE_WITH_QUARANTINES"
    assert status["quarantined_buckets"][0]["bucket_key"] == (
        "SOLUSDT|1m|range_scalp|chop"
    )
    assert "ATR_STOP_LOSS_CLUSTER" in status["quarantined_buckets"][0]["block_reasons"]
    assert status["paper_only"] is True
    assert status["places_real_order"] is False


def test_atr_stop_loss_cluster_quarantines_side_timeframe_bucket_when_aggregate_positive() -> None:
    rows = [
        {
            **_phase1_closed_trade_row(
                -8.0,
                symbol="WLDUSDT",
                timeframe="1h",
                strategy_id="trend_mode",
                regime="TREND",
                confidence=0.50,
                close_reason="TIER_1_ATR_VOLATILITY_STOP",
            ),
            "side": "short",
        },
        {
            **_phase1_closed_trade_row(
                -7.0,
                symbol="INJUSDT",
                timeframe="1h",
                strategy_id="trend_mode",
                regime="TREND",
                confidence=0.50,
                close_reason="TIER_1_ATR_VOLATILITY_STOP",
            ),
            "side": "short",
        },
        {
            **_phase1_closed_trade_row(
                40.0,
                symbol="TAOUSDT",
                timeframe="1h",
                strategy_id="trend_mode",
                regime="TREND",
                confidence=0.50,
                close_reason="TIER_2_TRAILING_STOP",
            ),
            "side": "short",
        },
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )
    quarantined_by_key = {
        row["bucket_key"]: row
        for row in status["bucket_quarantine_status"]["quarantined_buckets"]
    }

    assert "BUCKET_QUARANTINE_ACTIVE" in status["block_reasons"]
    assert status["aggregate"]["profit_factor_numeric"] > 1.0
    assert status["aggregate"]["notional_weighted_expectancy_bps"] > 0.0
    assert "side:short" not in quarantined_by_key
    assert "timeframe:1h" not in quarantined_by_key
    assert "side_timeframe:short|1h" in quarantined_by_key
    assert "strategy_side_timeframe:trend_mode|short|1h" in quarantined_by_key
    assert "ATR_STOP_LOSS_CLUSTER_SIDE_TIMEFRAME_BUCKET" in quarantined_by_key[
        "side_timeframe:short|1h"
    ]["block_reasons"]
    assert "ATR_STOP_LOSS_CLUSTER_STRATEGY_SIDE_TIMEFRAME_BUCKET" in quarantined_by_key[
        "strategy_side_timeframe:trend_mode|short|1h"
    ]["block_reasons"]

    intent = {
        "paper_only": True,
        "symbol": "NEWUSDT",
        "timeframe": "1h",
        "side": "short",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
    }
    allocation = _allowed_allocation()

    blocked = paper_loop._paper_block_new_entry_by_performance_circuit(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        performance_circuit_breaker_status=status,
    )

    assert blocked is True
    assert "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY" in intent[
        "paper_performance_circuit_breaker_block_reasons"
    ]
    assert "side_timeframe:short|1h" in intent[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ]
    assert "strategy_side_timeframe:trend_mode|short|1h" in intent[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ]
    assert intent["paper_fill_allowed"] is False
    assert intent["places_real_order"] is False
    assert intent["routes_to_live"] is False


def test_first_negative_bootstrap_close_prevents_bootstrap_reopen() -> None:
    rows = [
        _phase1_closed_trade_row(
            -1.0,
            tier="A_GRADE_BOOTSTRAP_PAPER",
            close_reason="TIER_1_ATR_VOLATILITY_STOP",
        )
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    bootstrap = status["first_bootstrap_close_block_status"]
    assert bootstrap["first_bootstrap_close_negative"] is True
    assert bootstrap["bootstrap_reopen_allowed"] is False
    assert bootstrap["candidate_policy_change_required"] is True
    assert "FIRST_BOOTSTRAP_CLOSE_NEGATIVE" in status["block_reasons"]


def test_non_negative_first_bootstrap_close_does_not_halt() -> None:
    rows = [
        _phase1_closed_trade_row(
            0.0,
            tier="A_GRADE_BOOTSTRAP_PAPER",
            close_reason="TIER_3_MODEL_REVERSAL_NETTING",
        )
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    bootstrap = status["first_bootstrap_close_block_status"]
    assert bootstrap["first_bootstrap_close_negative"] is False
    assert bootstrap["bootstrap_reopen_allowed"] is True
    # Only 1 trade < 5 minimum for rolling windows, so no rolling block fires either
    assert "FIRST_BOOTSTRAP_CLOSE_NEGATIVE" not in status["block_reasons"]
    assert "ROLLING_25_PF_BELOW_1_AND_EXPECTANCY_NON_POSITIVE" not in status["block_reasons"]
    assert status["new_entries_allowed"] is True


def test_rolling_25_does_not_fire_with_fewer_than_5_trades() -> None:
    # With < 5 trades, rolling window checks must be silent regardless of PF.
    # This prevents a brand-new session (1-4 trades) from being permanently halted.
    rows = [
        _phase1_closed_trade_row(-10.0, confidence=0.90, close_reason="MODEL_STOP")
        for _ in range(4)
    ]

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert "ROLLING_25_PF_BELOW_1_AND_EXPECTANCY_NON_POSITIVE" not in status["block_reasons"]
    assert "ROLLING_50_PROFIT_FACTOR_BELOW_1" not in status["block_reasons"]
    assert "ROLLING_50_EXPECTANCY_NON_POSITIVE" not in status["block_reasons"]


def test_rolling_50_does_not_fire_with_fewer_than_10_trades() -> None:
    # 5-9 trades may fire rolling_25 but must NOT fire rolling_50 checks.
    rows = [
        _phase1_closed_trade_row(10.0, confidence=0.70, close_reason="TAKE_PROFIT")
        for _ in range(3)
    ] + [
        _phase1_closed_trade_row(-15.0, confidence=0.70, close_reason="MODEL_STOP")
        for _ in range(6)
    ]
    # 9 total trades: PF < 1 → rolling_25 fires (9 >= 5); rolling_50 must NOT (9 < 10)

    status = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        rows,
        generated_utc="2026-07-02T10:00:00Z",
    )

    assert "ROLLING_25_PF_BELOW_1_AND_EXPECTANCY_NON_POSITIVE" in status["block_reasons"]
    assert "ROLLING_50_PROFIT_FACTOR_BELOW_1" not in status["block_reasons"]
    assert "ROLLING_50_EXPECTANCY_NON_POSITIVE" not in status["block_reasons"]


def test_no_trade_tier_blocks_executable_allocator_decision() -> None:
    intent = {
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
        "paper_only": True,
        "places_real_order": False,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "paper_fill_allowed": True,
        "paper_sizing_complete": True,
    }
    allocation = _allowed_allocation(paper_opportunity_tier="NO_TRADE")

    blocked = paper_loop._block_non_executable_paper_tier(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
    )

    assert blocked is True
    assert intent["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert allocation["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert intent["pre_non_executable_paper_tier"] == "NO_TRADE"
    assert intent["pre_non_executable_paper_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"
    assert intent["non_executable_paper_tier_block_reason"] == "NON_EXECUTABLE_PAPER_TIER:NO_TRADE"
    assert allocation["pre_non_executable_paper_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_sizing_complete"] is False
    assert intent["gross_notional_usd"] == 0.0
    assert allocation["gross_notional_usd"] == 0.0
    assert intent["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert allocation["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert intent["places_real_order"] is False
    assert allocation["places_real_order"] is False


def test_blocked_directional_candidate_can_emit_shadow_observation_without_fill_implication() -> None:
    intent = {
        "intent_id": "intent-shadow-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "selected_action": "long",
        "timeframe": "1m",
        "strategy_selected_mode": "trend_mode",
        "strategy_router_selected_mode": "trend_mode",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
        "paper_only": True,
        "places_real_order": False,
        "paper_fill_allowed": True,
        "strict_paper_fill_allowed_upstream": True,
        "entry_price": 100.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "entry_price_provenance_present": True,
        "paper_signal_temporal_rejection_reasons": [],
        "paper_pre_fill_market_evidence_rejection_reasons": [],
        "valid_for_paper": True,
    }

    shadow = paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
        intent=intent,
        signal={"selected_action": "long"},
        integrity_gate={"allowed": True},
        observation_source="NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
        observation_reason="EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
    )

    assert shadow is not None
    assert shadow["decision"] == "SHADOW_OBSERVATION_ONLY"
    assert shadow["side"] == "long"
    assert shadow["paper_opportunity_tier"] == "NO_TRADE"
    assert shadow["shadow_observation_source"] == "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK"
    assert shadow["shadow_observation_selected_before_outcome"] is True
    assert shadow["paper_fill_allowed"] is False
    assert shadow["strict_paper_fill_allowed_upstream"] is False
    assert shadow["places_real_order"] is False
    assert shadow["counted_as_fill"] is False
    assert shadow["affects_pnl_ledger"] is False
    assert shadow["counts_as_a_grade_evidence"] is False
    assert shadow["a_grade_promotion_allowed"] is False
    assert shadow["live_ready_implication"] is False
    assert shadow["candidate_selected_after_outcome"] is False
    assert shadow["future_labels_used_as_features"] is False


def test_shadow_observation_rejects_dirty_or_no_trade_strategy_candidates() -> None:
    base_intent = {
        "intent_id": "intent-shadow-dirty",
        "symbol": "ETHUSDT",
        "side": "short",
        "selected_action": "short",
        "strategy_selected_mode": "trend_mode",
        "strategy_router_selected_mode": "trend_mode",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_only": True,
        "places_real_order": False,
        "entry_price": 2000.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "entry_price_provenance_present": True,
        "paper_signal_temporal_rejection_reasons": [],
        "paper_pre_fill_market_evidence_rejection_reasons": [],
        "valid_for_paper": True,
    }

    dirty = dict(base_intent)
    dirty["paper_signal_temporal_rejection_reasons"] = ["AVAILABLE_AT_AFTER_DECISION_TIME"]
    assert (
        paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
            intent=dirty,
            signal={"selected_action": "short"},
            integrity_gate={"allowed": True},
            observation_source="LOCAL_PAPER_TRADE_GATES_FAILED",
            observation_reason="temporal",
        )
        is None
    )

    no_trade_strategy = dict(base_intent)
    no_trade_strategy["strategy_selected_mode"] = "no_trade_mode"
    assert (
        paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
            intent=no_trade_strategy,
            signal={"selected_action": "short", "strategy_regime_labels": ["NO_TRADE"]},
            integrity_gate={"allowed": True},
            observation_source="NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
            observation_reason="NO_TRADE_STRATEGY",
        )
        is None
    )


def test_shadow_observation_history_preserves_original_entry_time_for_duplicate() -> None:
    existing = {
        "decision": "SHADOW_OBSERVATION_ONLY",
        "intent_id": "intent-shadow-1",
        "prediction_id": "prediction-shadow-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "timeframe": "1m",
        "shadow_observation_source": "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
        "shadow_observation_reason": "BLOCK_NO_EDGE",
        "entry_price": 100.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "paper_only": True,
        "places_real_order": False,
        "paper_fill_allowed": False,
        "counted_as_fill": False,
    }
    current = {
        **existing,
        "entry_price": 101.0,
        "entry_price_utc": "2026-06-23T17:04:30Z",
        "generated_utc": "2026-06-23T17:04:30Z",
    }

    merged = paper_loop._merge_shadow_observation_history(  # noqa: SLF001
        [existing],
        [current],
        now_utc="2026-06-23T17:05:00Z",
    )

    assert len(merged) == 1
    row = merged[0]
    assert row["entry_price"] == 100.0
    assert row["entry_price_utc"] == "2026-06-23T17:00:00Z"
    assert row["shadow_observation_first_seen_utc"] == "2026-06-23T17:00:00Z"
    assert row["shadow_observation_last_seen_utc"] == "2026-06-23T17:05:00Z"
    assert row["shadow_observation_seen_count"] == 2
    assert row["shadow_observation_history_persisted"] is True
    assert row["paper_fill_allowed"] is False
    assert row["counted_as_fill"] is False
    assert row["affects_pnl_ledger"] is False
    assert row["counts_as_a_grade_evidence"] is False
    assert row["live_ready_implication"] is False


def test_shadow_observation_history_is_bounded_to_newest_rows() -> None:
    rows = [
        {
            "decision": "SHADOW_OBSERVATION_ONLY",
            "intent_id": f"intent-{idx}",
            "prediction_id": f"prediction-{idx}",
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "1m",
            "shadow_observation_source": "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
            "shadow_observation_reason": "BLOCK_NO_EDGE",
            "entry_price": 100.0 + idx,
            "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
            "entry_price_utc": f"2026-06-23T17:0{idx}:00Z",
            "paper_only": True,
            "places_real_order": False,
        }
        for idx in range(5)
    ]

    merged = paper_loop._merge_shadow_observation_history(  # noqa: SLF001
        rows,
        [],
        now_utc="2026-06-23T17:10:00Z",
        max_rows=3,
    )

    assert [row["prediction_id"] for row in merged] == [
        "prediction-2",
        "prediction-3",
        "prediction-4",
    ]
    assert all(row["paper_fill_allowed"] is False for row in merged)
    assert all(row["places_real_order"] is False for row in merged)


def test_b_grade_tier_remains_paper_only_executable_lane() -> None:
    intent = {
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_only": True,
        "places_real_order": False,
    }
    allocation = _allowed_allocation(paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER")

    blocked = paper_loop._block_non_executable_paper_tier(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
    )

    assert blocked is False
    assert allocation["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert allocation["gross_notional_usd"] == 1000.0


def test_compact_accepted_fill_state_preserves_paper_session_metadata() -> None:
    compact = paper_loop._compact_accepted_fill_for_state(  # noqa: SLF001
        {
            "fill_id": "fill-session-1",
            "symbol": "SOLUSDT",
            "side": "long",
            "paper_session_id": "paper_3000_final_pre_live_20260705T024432Z",
            "session_id": "paper_3000_final_pre_live_20260705T024432Z",
            "reset_session_id": "paper_3000_final_pre_live_20260705T024432Z",
            "starting_equity_usd": 3000.0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )

    assert compact["paper_session_id"] == "paper_3000_final_pre_live_20260705T024432Z"
    assert compact["session_id"] == "paper_3000_final_pre_live_20260705T024432Z"
    assert compact["reset_session_id"] == "paper_3000_final_pre_live_20260705T024432Z"
    assert compact["starting_equity_usd"] == 3000.0
    assert compact["paper_only"] is True
    assert compact["routes_to_live"] is False
    assert compact["places_real_order"] is False


def test_exploration_tier_status_separates_legacy_missing_tiers() -> None:
    status = paper_loop._paper_exploration_tier_status(  # noqa: SLF001
        accepted_rows=[
            {"fill_id": "legacy-1"},
            {
                "fill_id": "b-1",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "risk_budget_fraction_of_normal_adaptive": 0.12,
                "b_grade_exploration_budget_cap_applied": True,
                "paper_only": True,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "paper_only_label_collection_priority": True,
                "paper_only_label_collection_priority_reason": (
                    "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                ),
            },
        ],
        blocked_rows=[
            {
                "intent_id": "blocked-1",
                "paper_opportunity_tier": "NO_TRADE",
                "paper_opportunity_tier_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                "pre_non_executable_paper_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
                "non_executable_paper_tier_block_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                "local_block_reasons": ["paper_tier:NON_EXECUTABLE_PAPER_TIER:NO_TRADE"],
                "paper_fill_gate_block_reasons": ["NON_EXECUTABLE_PAPER_TIER:NO_TRADE"],
                "paper_runtime_market_evidence_rejection_reasons": [
                    "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE"
                ],
                "lifecycle_or_no_trade_strategy_reasons": [
                    "intent.strategy_selected_mode=NO_TRADE"
                ],
            }
        ],
        shadow_rows=[{"paper_opportunity_tier": "SHADOW_ONLY"}],
        held_rows=[],
    )

    assert "missing" not in status["tier_counts"]
    assert status["accepted_tier_counts"] == {"B_GRADE_EXPLORATION_PAPER": 1}
    assert status["legacy_accepted_without_tier_count"] == 1
    assert status["b_grade_exploration_accepted_count"] == 1
    assert status["paper_only_label_collection_priority_candidate_count"] == 1
    assert status["paper_only_label_collection_priority_b_grade_accepted_count"] == 1
    assert status["persistent_paper_only_label_collection_priority_b_grade_accepted_count"] == 1
    assert status["paper_only_label_collection_priority_live_routing_blocked"] is True
    assert status["paper_only_label_collection_priority_reason_counts"] == {
        "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET": 1
    }
    assert status["b_grade_exploration_live_routing_blocked"] is True
    assert status["blocked_final_reason_counts"] == {
        "NON_EXECUTABLE_PAPER_TIER:NO_TRADE": 1
    }
    assert status["blocked_upstream_tier_reason_counts"] == {
        "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST": 1
    }
    assert status["blocked_runtime_market_evidence_rejection_counts"] == {
        "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE": 1
    }
    assert status["blocked_lifecycle_or_no_trade_strategy_reason_counts"] == {
        "intent.strategy_selected_mode=NO_TRADE": 1
    }
    assert status["sample_blocked_fills"][0]["accepted_fill_state_compacted"] is True


def test_exploration_tier_status_uses_current_accepted_rows_for_primary_counts() -> None:
    status = paper_loop._paper_exploration_tier_status(  # noqa: SLF001
        accepted_rows=[
            {
                "fill_id": "historical-a",
                "paper_opportunity_tier": "A_GRADE_EXECUTION_PAPER",
                "paper_only": True,
                "places_real_order": False,
            },
            {
                "fill_id": "historical-b",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "paper_only": True,
                "places_real_order": False,
            },
        ],
        current_accepted_rows=[
            {
                "fill_id": "current-b",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "risk_budget_fraction_of_normal_adaptive": 0.12,
                "paper_only": True,
                "places_real_order": False,
            }
        ],
        blocked_rows=[],
        shadow_rows=[],
        held_rows=[],
    )

    assert status["accepted_tier_counts_scope"] == "current_cycle_accepted_fills_only"
    assert status["accepted_tier_counts"] == {"B_GRADE_EXPLORATION_PAPER": 1}
    assert status["persistent_accepted_tier_counts"] == {
        "A_GRADE_EXECUTION_PAPER": 1,
        "B_GRADE_EXPLORATION_PAPER": 1,
    }
    assert status["b_grade_exploration_accepted_count"] == 1
    assert status["persistent_b_grade_exploration_accepted_count"] == 1


def test_merge_persistent_accepted_fills_preserves_policy_funding_metadata() -> None:
    prior = {
        "fill_id": "fill-1",
        "ledger_row_id": "fill-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "signal_id": "sig-1",
        "prediction_id": "pred-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "entry_price": 100.0,
        "entry_price_source": "prior_entry",
        "entry_price_utc": "2026-06-21T00:00:00Z",
        "fill_price": 100.0,
        "fill_price_source": "prior_fill",
        "fill_price_utc": "2026-06-21T00:00:00Z",
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "policy_activated_at": "2026-06-21T00:00:00Z",
        "expected_funding_bps": 1.25,
        "funding_rate": 0.000125,
        "funding_interval_seconds": 3600.0,
        "adaptive_allocation": {
            "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
            "policy_activated_at": "2026-06-21T00:00:00Z",
            "expected_funding_bps": 1.25,
            "expected_funding_usd": 0.0125,
            "model_inputs": {
                "funding_rate": 0.000125,
                "funding_interval_seconds": 3600.0,
            },
        },
    }
    current = {
        "fill_id": "fill-1",
        "ledger_row_id": "fill-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "signal_id": "sig-1",
        "prediction_id": "pred-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "entry_price": 101.0,
        "fill_price": 101.0,
        "fill_price_utc": "2026-06-21T00:01:00Z",
        "quantity": 1.0,
        "notional": 101.0,
        "latest_price": 102.0,
        "latest_price_source": "current_mark",
        "latest_price_utc": "2026-06-21T00:02:00Z",
        "expected_funding_bps": 2.0,
        "adaptive_allocation": {
            "expected_funding_bps": 2.0,
            "model_inputs": {
                "expected_funding_bps": 2.0,
            },
        },
    }

    merged = paper_loop._merge_persistent_accepted_fills(  # noqa: SLF001
        {"fill-1": prior},
        [current],
    )

    assert len(merged) == 1
    row = merged[0]
    assert row["entry_price"] == 100.0
    assert row["fill_price"] == 100.0
    assert row["fill_price_utc"] == "2026-06-21T00:00:00Z"
    assert row["latest_price"] == 102.0
    assert row["paper_fill_persistence_status"] == "EXISTING_FILL_IMMUTABLE_FIELDS_PRESERVED"
    assert row["adaptive_capital_policy_version"] == "ADAPTIVE_CAPITAL_ALLOCATOR_V1"
    assert row["policy_activated_at"] == "2026-06-21T00:00:00Z"
    assert row["expected_funding_bps"] == 2.0
    assert row["funding_rate"] == 0.000125
    assert row["funding_interval_seconds"] == 3600.0
    allocation = row["adaptive_allocation"]
    assert allocation["adaptive_capital_policy_version"] == "ADAPTIVE_CAPITAL_ALLOCATOR_V1"
    assert allocation["policy_activated_at"] == "2026-06-21T00:00:00Z"
    assert allocation["expected_funding_bps"] == 2.0
    assert allocation["expected_funding_usd"] == 0.0125
    assert allocation["model_inputs"]["expected_funding_bps"] == 2.0
    assert allocation["model_inputs"]["funding_rate"] == 0.000125
    assert allocation["model_inputs"]["funding_interval_seconds"] == 3600.0


# ─── CG-F038: SHORT trend_mode blocked at entry gate ─────────────────────────

def test_cg_f038_short_trend_mode_blocked_by_default() -> None:
    """
    CG-F038 (upgraded to R29-D2 regime gate): SHORT trend_mode must be blocked by
    default when no liquidation data is available (no redis_client passed).

    Original CG-F038 was a hard side+mode block. R29-D2 replaced it with a cascade-risk
    regime gate that blocks when cascade_risk < 0.30 OR liq data is missing/stale.
    Without redis, _load_liq_regime_data returns None → REGIME_GATE_NO_CASCADE_DATA.

    Evidence: 743-trade B_GRADE session (Jun19-Jul1) in a bullish market had
      cascade_risk consistently < 0.05 → regime gate would have blocked all entries.
    """
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    cfg = PaperEntryGateConfig()

    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="4h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-10.0,
        major_move_detected=False,
        redis_client=None,
        config=cfg,
    )

    assert result["allowed"] is False, "SHORT trend_mode must be blocked by default (no liq data)"
    block_reasons = result.get("reasons", [])
    assert any("REGIME_GATE_NO_CASCADE_DATA" in r for r in block_reasons), (
        f"Expected REGIME_GATE_NO_CASCADE_DATA in reasons, got {block_reasons}"
    )


def test_cg_f038_long_trend_mode_still_allowed() -> None:
    """LONG trend_mode is not gated by the regime gate — only SHORT trend is controlled."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    cfg = PaperEntryGateConfig()

    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="4h",
        side="long",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=15.0,
        major_move_detected=False,
        config=cfg,
    )

    block_reasons = result.get("reasons", [])
    assert not any("REGIME_GATE" in r for r in block_reasons), (
        f"long:trend_mode must not be regime-gated, got {block_reasons}"
    )


def test_cg_f038_short_trend_mode_blocked_side_mode_in_default_frozenset() -> None:
    """Verify CG-F009 hard block remains; CG-F038 upgraded to R29-D2 regime gate."""
    from v2.backend.app.services.paper_trade_management.entry_gate import PaperEntryGateConfig

    cfg = PaperEntryGateConfig()
    assert "long:mean_reversion_mode" in cfg.blocked_side_mode_combinations, (
        "CG-F009 rule must remain: long:mean_reversion_mode blocked"
    )
    # R29-D2 upgrade: short:trend_mode removed from hard block frozenset, now controlled
    # by short_trend_mode_regime_gate_enabled + short_trend_cascade_risk_min
    assert "short:trend_mode" not in cfg.blocked_side_mode_combinations, (
        "CG-F038 hard block was upgraded to R29-D2 regime gate; should not be in frozenset"
    )
    assert cfg.short_trend_mode_regime_gate_enabled is True, (
        "R29-D2 regime gate must be enabled by default"
    )
    assert cfg.short_trend_cascade_risk_min == 0.30, (
        "R29-D2 cascade risk floor must default to 0.30"
    )


def test_r29_d2_short_trend_blocked_low_cascade_risk() -> None:
    """R29-D2: SHORT trend_mode blocked when cascade_risk < floor (bullish market)."""
    import json
    from unittest.mock import MagicMock
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    liq_data = {
        "liquidation_is_stale": 0,
        "liquidation_cascade_risk": 0.047,  # Jun-Jul bullish market level
        "liquidation_long_distance_pct": 0.2,
        "liquidation_pressure_direction": -0.1,
    }
    redis_mock = MagicMock()
    redis_mock.get.return_value = json.dumps(liq_data).encode()

    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="ETHUSDT",
        timeframe="1h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-8.0,
        redis_client=redis_mock,
        config=cfg,
    )

    assert result["allowed"] is False
    block_reasons = result.get("reasons", [])
    assert any("REGIME_GATE_INSUFFICIENT_CASCADE_RISK" in r for r in block_reasons), (
        f"Expected REGIME_GATE_INSUFFICIENT_CASCADE_RISK, got {block_reasons}"
    )
    assert any("0.0470" in r for r in block_reasons), (
        f"Block reason should contain cascade_risk value, got {block_reasons}"
    )


def test_r29_d2_short_trend_allowed_high_cascade_risk() -> None:
    """R29-D2: SHORT trend_mode allowed when cascade_risk >= floor (cascade conditions)."""
    import json
    from unittest.mock import MagicMock
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    liq_data = {
        "liquidation_is_stale": 0,
        "liquidation_cascade_risk": 0.42,  # elevated — longs at risk
        "liquidation_long_distance_pct": 0.05,
        "liquidation_pressure_direction": -0.85,
    }
    redis_mock = MagicMock()
    redis_mock.get.return_value = json.dumps(liq_data).encode()

    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="ETHUSDT",
        timeframe="1h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-8.0,
        redis_client=redis_mock,
        config=cfg,
    )

    block_reasons = result.get("reasons", [])
    assert not any("REGIME_GATE" in r for r in block_reasons), (
        f"HIGH cascade_risk should pass regime gate, got block_reasons={block_reasons}"
    )
    assert result["allowed"] is True, (
        f"HIGH cascade_risk SHORT trend entry should be allowed, reasons={block_reasons}"
    )


def test_r29_d2_stale_liq_data_blocks_short_trend() -> None:
    """R29-D2: Stale liquidation data is treated as missing → blocks SHORT trend."""
    import json
    from unittest.mock import MagicMock
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    stale_data = {
        "liquidation_is_stale": 1,  # stale
        "liquidation_cascade_risk": 0.99,  # high but stale — must not be used
    }
    redis_mock = MagicMock()
    redis_mock.get.return_value = json.dumps(stale_data).encode()

    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="BNBUSDT",
        timeframe="4h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-5.0,
        redis_client=redis_mock,
        config=cfg,
    )

    assert result["allowed"] is False
    assert any("REGIME_GATE_NO_CASCADE_DATA" in r for r in result.get("reasons", [])), (
        "Stale data must be treated as missing → REGIME_GATE_NO_CASCADE_DATA"
    )


def test_r29_d2_gate_disabled_allows_short_trend_without_liq_check() -> None:
    """R29-D2: When regime gate disabled, SHORT trend passes without liq data check."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    cfg = PaperEntryGateConfig(short_trend_mode_regime_gate_enabled=False)
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="4h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-10.0,
        redis_client=None,
        config=cfg,
    )

    block_reasons = result.get("reasons", [])
    assert not any("REGIME_GATE" in r for r in block_reasons), (
        f"Disabled gate must not emit regime block reasons, got {block_reasons}"
    )


def test_r29_d2_short_mean_reversion_not_gated() -> None:
    """R29-D2: Regime gate only applies to trend_mode SHORT; other modes not affected."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )

    # short:mean_reversion_mode — no redis, but regime gate should NOT fire
    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="4h",
        side="short",
        strategy_mode="mean_reversion_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=-5.0,
        redis_client=None,
        config=cfg,
    )

    block_reasons = result.get("reasons", [])
    assert not any("REGIME_GATE" in r for r in block_reasons), (
        f"Regime gate must only apply to trend_mode SHORT, got {block_reasons}"
    )


def test_r29_d4_trend_mode_uses_wider_atr_multiplier() -> None:
    """R29-D4: trend_mode uses atr_stop_multiplier_trend_mode (3.0x) not default (2.0x)."""
    from v2.backend.app.services.paper_trade_management.exits import (
        PaperExitConfig,
        evaluate_exit,
    )
    from v2.backend.app.services.paper_trade_management.position_state import (
        PaperNetPosition,
    )

    # trend_mode SHORT position with atr_bps=30
    # 2.0x stop = -60 bps (default), 3.0x stop = -90 bps (trend_mode override)
    # PnL at -70 bps: should NOT stop out with 3.0x (stop at -90), would stop at 2.0x
    entry_price = 3000.0
    pos = PaperNetPosition(
        position_id="test-trend-short",
        symbol="ETHUSDT",
        side="short",
        net_quantity=0.1,
        avg_entry_price=entry_price,
        opened_est="2026-07-02T10:00:00Z",
        strategy_selected_mode="trend_mode",
    )
    # Simulate -70 bps adverse move (price went UP vs short)
    mark_at_minus_70bps = entry_price * (1 + 70 / 10000)  # short goes against at +70 bps price
    cfg = PaperExitConfig(
        static_stop_loss_enabled=False,
        static_take_profit_enabled=False,
        static_profit_lock_enabled=False,
        static_profit_bank_enabled=False,
        static_max_hold_enabled=False,
        atr_stop_multiplier=2.0,
        atr_stop_multiplier_trend_mode=3.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=mark_at_minus_70bps,
        generated_utc="2026-07-02T11:00:00Z",
        config=cfg,
        atr_bps=30.0,  # ATR = 30 bps
    )
    # With 3.0x: stop at -90 bps. At -70 bps, should NOT close.
    assert result["should_close"] is False, (
        f"trend_mode with 3.0x ATR should NOT stop at -70 bps (stop is -90 bps), got {result}"
    )


def test_r29_d4_non_trend_mode_uses_default_atr_multiplier() -> None:
    """R29-D4: non-trend_mode uses default atr_stop_multiplier (2.0x), not the wider override."""
    from v2.backend.app.services.paper_trade_management.exits import (
        PaperExitConfig,
        evaluate_exit,
    )
    from v2.backend.app.services.paper_trade_management.position_state import (
        PaperNetPosition,
    )

    # mean_reversion_mode position with atr_bps=30
    # 2.0x stop = -60 bps (default), 3.0x (trend override should NOT apply)
    # PnL at -70 bps: SHOULD stop out with 2.0x (stop at -60)
    entry_price = 3000.0
    pos = PaperNetPosition(
        position_id="test-mr-short",
        symbol="ETHUSDT",
        side="short",
        net_quantity=0.1,
        avg_entry_price=entry_price,
        opened_est="2026-07-02T10:00:00Z",
        strategy_selected_mode="mean_reversion_mode",
    )
    mark_at_minus_70bps = entry_price * (1 + 70 / 10000)
    cfg = PaperExitConfig(
        static_stop_loss_enabled=False,
        static_take_profit_enabled=False,
        static_profit_lock_enabled=False,
        static_profit_bank_enabled=False,
        static_max_hold_enabled=False,
        atr_stop_multiplier=2.0,
        atr_stop_multiplier_trend_mode=3.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=mark_at_minus_70bps,
        generated_utc="2026-07-02T11:00:00Z",
        config=cfg,
        atr_bps=30.0,
    )
    # mean_reversion_mode: default 2.0x stop at -60 bps. At -70 bps, SHOULD close.
    assert result["should_close"] is True, (
        f"mean_reversion_mode should stop at -70 bps with 2.0x multiplier (stop=-60), got {result}"
    )
    assert result.get("close_reason") == "TIER_1_ATR_VOLATILITY_STOP", (
        f"Expected TIER_1_ATR_VOLATILITY_STOP, got {result.get('close_reason')}"
    )
    assert result.get("atr_stop_multiplier_used") == 2.0, (
        f"Non-trend mode must use 2.0x multiplier, got {result.get('atr_stop_multiplier_used')}"
    )


def test_r29_d4_default_trend_mode_multiplier_is_3x() -> None:
    """R29-D4: PaperExitConfig default for atr_stop_multiplier_trend_mode is 3.0."""
    from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig

    cfg = PaperExitConfig()
    assert cfg.atr_stop_multiplier == 2.0, "Default ATR multiplier must remain 2.0"
    assert cfg.atr_stop_multiplier_trend_mode == 3.0, (
        "R29-D4 trend_mode ATR multiplier must default to 3.0"
    )


def test_r30_d1_synusdt_trend_mode_blocked_by_default() -> None:
    """R30-D1: SYNUSDT in trend_mode blocked (13-100x ATR gap loss evidence)."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )
    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="SYNUSDT",
        timeframe="4h",
        side="long",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=15.0,
        config=cfg,
    )
    assert result["allowed"] is False
    assert any("TREND_MODE_MICRO_CAP_GAP_RISK" in r for r in result.get("reasons", [])), (
        f"SYNUSDT trend_mode should be blocked as micro-cap gap risk, got {result['reasons']}"
    )


def test_r30_d1_all_known_gap_risk_tokens_blocked() -> None:
    """R30-D1: All 5 known gap-risk tokens blocked for trend_mode (both sides)."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )
    cfg = PaperEntryGateConfig()
    known_gap_risk = ["SYNUSDT", "RAVEUSDT", "LITUSDT", "CAPUSDT", "EPICUSDT"]
    for sym in known_gap_risk:
        for side, move in [("long", 15.0), ("short", -10.0)]:
            result = evaluate_entry_gate(
                symbol=sym,
                timeframe="4h",
                side=side,
                strategy_mode="trend_mode",
                confidence_calibrated=0.70,
                expected_move_after_cost_bps=move,
                config=cfg,
            )
            block_reasons = result.get("reasons", [])
            assert any("TREND_MODE_MICRO_CAP_GAP_RISK" in r for r in block_reasons), (
                f"{sym} {side} trend_mode should be gap-risk blocked, got {block_reasons}"
            )


def test_r30_d1_gap_risk_token_allowed_in_mean_reversion() -> None:
    """R30-D1: Gap-risk filter only applies to trend_mode; mean_reversion_mode passes filter."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )
    cfg = PaperEntryGateConfig()
    # SYNUSDT in mean_reversion_mode — NOT blocked by R30-D1
    result = evaluate_entry_gate(
        symbol="SYNUSDT",
        timeframe="15m",
        side="long",
        strategy_mode="mean_reversion_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=10.0,
        config=cfg,
    )
    block_reasons = result.get("reasons", [])
    assert not any("TREND_MODE_MICRO_CAP_GAP_RISK" in r for r in block_reasons), (
        f"SYNUSDT mean_reversion_mode must NOT be gap-risk blocked, got {block_reasons}"
    )


def test_r30_d1_btcusdt_not_in_gap_risk_exclusion() -> None:
    """R30-D1: BTCUSDT is not in gap-risk exclusion; trend_mode allowed (if other gates pass)."""
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )
    cfg = PaperEntryGateConfig()
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="4h",
        side="long",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=15.0,
        config=cfg,
    )
    block_reasons = result.get("reasons", [])
    assert not any("TREND_MODE_MICRO_CAP_GAP_RISK" in r for r in block_reasons), (
        f"BTCUSDT must NOT be in gap-risk exclusion, got {block_reasons}"
    )


def test_r30_d1_default_exclusion_set_contains_evidence_tokens() -> None:
    """R30-D1: Default trend_mode_micro_cap_exclusion contains all 5 evidence-backed tokens."""
    from v2.backend.app.services.paper_trade_management.entry_gate import PaperEntryGateConfig
    cfg = PaperEntryGateConfig()
    required = {"SYNUSDT", "RAVEUSDT", "LITUSDT", "CAPUSDT", "EPICUSDT"}
    assert required <= cfg.trend_mode_micro_cap_exclusion, (
        f"Missing gap-risk tokens: {required - cfg.trend_mode_micro_cap_exclusion}"
    )


def test_bucket_quarantine_pre_repair_losses_do_not_halt_globally(tmp_path, monkeypatch) -> None:
    """A+ goal Phase 1/8: after a verified exit repair, buckets whose loss
    evidence entirely pre-dates the repair stay bucket-blocked but no longer
    escalate to a global entry halt. Post-repair losses re-escalate; a missing
    artifact or missing exit timestamps keep the original fail-closed halt."""
    artifact = tmp_path / "atr_stop_cluster_repair_status.json"
    artifact.write_text(
        '{"repair_test_passed": true, "repair_deployed_utc": "2026-07-06T18:00:00Z"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_EXIT_REPAIR_STATUS_PATH", artifact)

    def _atr_loss(ts: str) -> dict[str, object]:
        row = _phase1_closed_trade_row(
            -25.0, confidence=0.75, close_reason="TIER_1_ATR_VOLATILITY_STOP"
        )
        row["exit_price_utc"] = ts
        return row

    wins = [
        _phase1_closed_trade_row(15.0, confidence=0.70, close_reason="TIER_2_TRAILING_STOP")
        for _ in range(6)
    ]
    for row in wins:
        row["exit_price_utc"] = "2026-07-06T05:00:00.000Z"

    # Two pre-repair ATR losses -> bucket quarantined but non-escalating.
    pre_repair = wins + [_atr_loss("2026-07-06T01:34:09.533Z"), _atr_loss("2026-07-06T02:01:00.000Z")]
    status = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        pre_repair, generated_utc="2026-07-06T19:00:00Z"
    )
    assert status["quarantined_bucket_count"] > 0
    assert status["global_halt_required"] is False
    # Operator-approved (2026-07-06): pre-repair-only buckets are listed as
    # PRE_REPAIR_EVIDENCE_ONLY but reopen for candidates; any post-repair loss
    # re-blocks instantly (asserted below).
    assert status["blocked_bucket_keys"] == []
    assert all(
        row.get("state") == "PRE_REPAIR_EVIDENCE_ONLY" and row.get("candidate_blocking") is False
        for row in status["quarantined_buckets"]
    )
    circuit = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        pre_repair, generated_utc="2026-07-06T19:00:00Z"
    )
    assert "BUCKET_QUARANTINE_ACTIVE" not in circuit["block_reasons"]

    # A post-repair loss escalates again.
    post_repair = pre_repair + [_atr_loss("2026-07-06T19:30:00.000Z"), _atr_loss("2026-07-06T19:40:00.000Z")]
    circuit_post = paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
        post_repair, generated_utc="2026-07-06T20:00:00Z"
    )
    assert "BUCKET_QUARANTINE_ACTIVE" in circuit_post["block_reasons"]
    status_post = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        post_repair, generated_utc="2026-07-06T20:00:00Z"
    )
    assert status_post["blocked_bucket_keys"]  # post-repair losses re-block

    # Missing exit timestamps fail closed.
    no_ts = wins + [
        {k: v for k, v in _atr_loss("x").items() if k != "exit_price_utc"},
        {k: v for k, v in _atr_loss("x").items() if k != "exit_price_utc"},
    ]
    status_no_ts = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        no_ts, generated_utc="2026-07-06T19:00:00Z"
    )
    assert status_no_ts["global_halt_required"] is True

    # Missing artifact keeps the original always-escalate behaviour.
    monkeypatch.setattr(paper_loop, "PAPER_EXIT_REPAIR_STATUS_PATH", tmp_path / "missing.json")
    status_no_artifact = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        pre_repair, generated_utc="2026-07-06T19:00:00Z"
    )
    assert status_no_artifact["global_halt_required"] is True


class TestForbiddenMarkerExecutablePosition:
    """F-0011: monitoring processes that mention forbidden runtime names in
    ARGUMENTS must not be classified as forbidden runtimes."""

    def test_grep_pattern_argument_not_forbidden(self):
        argv = ["bash", "-c", "ps aux | grep paper_online_runtime | head -5"]
        assert paper_loop._forbidden_markers_for_argv(argv) == []  # noqa: SLF001

    def test_systemctl_status_argument_not_forbidden(self):
        argv = ["systemctl", "--user", "status", "ai-bot-v2-paper-online-runtime.service"]
        assert paper_loop._forbidden_markers_for_argv(argv) == []  # noqa: SLF001

    def test_actual_script_execution_is_forbidden(self):
        argv = ["python3", "/legacy/paper_online_runtime.py", "--loop"]
        assert "paper_online_runtime" in paper_loop._forbidden_markers_for_argv(argv)  # noqa: SLF001

    def test_module_execution_is_forbidden(self):
        argv = ["python3", "-m", "legacy.runtime.paper_online_runtime"]
        assert "paper_online_runtime" in paper_loop._forbidden_markers_for_argv(argv)  # noqa: SLF001

    def test_bash_wrapped_script_execution_is_forbidden(self):
        argv = ["bash", "-c", "cd /app && python3 toy_momentum_wrapper.py --run"]
        matched = paper_loop._forbidden_markers_for_argv(argv)  # noqa: SLF001
        assert "toy_momentum" in matched or "momentum_wrapper" in matched

    def test_worker_task_argument_not_forbidden(self):
        argv = ["python3", "worker.py", "--task", "verify paper_online_runtime stays disabled"]
        assert paper_loop._forbidden_markers_for_argv(argv) == []  # noqa: SLF001


class TestAdmissionInvalidatedPositionsStayManaged:
    """F-0015: admission-invalidated positions must remain under lifecycle
    management (mark-to-market + stops) — never silently orphaned."""

    def test_retained_rows_flagged_and_session_stamped(self):
        rows = [{"position_id": "paper_pos_XUSDT", "symbol": "XUSDT", "side": "long"}]
        out = paper_loop._retain_admission_invalidated_positions(  # noqa: SLF001
            rows, recorded_utc="2026-07-07T06:00:00Z", paper_session_id="sess-1"
        )
        assert len(out) == 1
        row = out[0]
        assert row["admission_invalidated"] is True
        assert row["new_entry_admission_eligible"] is False
        assert row["admission_drop_reason"] == "OPEN_POSITION_FILL_NO_LONGER_ADMISSION_VALID"
        assert row["paper_session_id"] == "sess-1"

    def test_existing_session_id_preserved(self):
        rows = [{"position_id": "p", "paper_session_id": "orig"}]
        out = paper_loop._retain_admission_invalidated_positions(  # noqa: SLF001
            rows, recorded_utc="t", paper_session_id="new"
        )
        assert out[0]["paper_session_id"] == "orig"

    def test_non_dict_rows_skipped(self):
        out = paper_loop._retain_admission_invalidated_positions(  # noqa: SLF001
            ["junk", None, {"position_id": "ok"}], recorded_utc="t", paper_session_id="s"
        )
        assert len(out) == 1 and out[0]["position_id"] == "ok"

    def test_stop_breached_retained_position_closes_in_one_lifecycle_cycle(self):
        from v2.backend.app.services.paper_trade_management import (  # noqa: PLC0415
            PaperLifecycleConfig,
            reconcile_paper_lifecycle,
        )
        from v2.backend.app.services.paper_trade_management.exits import (  # noqa: PLC0415
            PaperExitConfig,
        )

        retained = paper_loop._retain_admission_invalidated_positions(  # noqa: SLF001
            [
                {
                    "fill_id": "p0018-stop",
                    "ledger_row_id": "p0018-stop",
                    "position_id": "paper_pos_BTCUSDT",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "quantity": 1.0,
                    "notional": 100.0,
                    "notional_usdt": 100.0,
                    "entry_price": 100.0,
                    "fill_price": 100.0,
                    "fill_price_utc": "2026-07-07T10:00:00Z",
                    "generated_utc": "2026-07-07T10:00:00Z",
                    "signal_id": "sig_p0018_stop",
                    "prediction_id": "pred_p0018_stop",
                    "risk_decision_id": "risk_p0018_stop",
                    "orchestrator_decision_id": "orch_p0018_stop",
                    "paper_only": True,
                    "places_real_order": False,
                    "gross_notional_usd": 100.0,
                }
            ],
            recorded_utc="2026-07-07T10:00:30Z",
            paper_session_id="paper_3000_final_pre_live_20260705T024432Z",
        )

        result = reconcile_paper_lifecycle(
            existing_ledger={},
            accepted_fills=retained,
            mark_prices={"BTCUSDT": 98.0},
            generated_utc="2026-07-07T10:01:00Z",
            config=PaperLifecycleConfig(
                portfolio_equity_usdt=3000.0,
                exit_config=PaperExitConfig(
                    stop_loss_bps=50.0,
                    take_profit_bps=99999.0,
                    trailing_stop_bps=99999.0,
                ),
            ),
        )

        assert result["open_positions"] == []
        assert len(result["new_close_events"]) == 1
        close = result["new_close_events"][0]
        assert close["close_reason"] == "TIER_1_STOP_LOSS"
        assert close["realized_pnl_bps"] == pytest.approx(-200.0)
        assert close["realized_pnl_usd"] == pytest.approx(-2.0)
        assert close["realized_net_pnl_usd"] < close["realized_pnl_usd"]
        assert result["paper_exit_coordinator_status"]["evaluations"][0]["should_close"] is True


class TestHighConfidenceLossClusterGate:
    """F-0021 cluster gate: explicit cluster-bucket quarantine + the
    trust-evidence-missing bootstrap denial that closes the admission vector
    behind the 2026-07 high-confidence loss cluster."""

    @staticmethod
    def _cluster_gate() -> dict:
        return {
            "cluster_detected": True,
            "cluster_evidence_missing": False,
            "high_confidence_loss_count": 6,
            "affected_symbols": ["CRVUSDT", "WLDUSDT", "AEROUSDT", "XPLUSDT", "CAKEUSDT", "AVNTUSDT"],
            "quarantined_sides": ["short"],
            "quarantined_timeframes": ["4h"],
            "quarantined_strategy_modes": ["breakout_mode"],
            "bucket_specific_recovery_enabled": True,
        }

    @staticmethod
    def _bootstrap_intent(**overrides) -> dict:
        intent = {
            "symbol": "DOGEUSDT",
            "timeframe": "15m",
            "side": "long",
            "strategy_id": "trend_mode",
            "strategy_selected_mode": "trend_mode",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 18.0,
            "paper_only": True,
            "places_real_order": False,
            "production_grade_cost_flag": True,
            "microstructure_action": "REDUCE_SIZE",
            "public_orderbook_trust_score": 0.51,
            "composite_microstructure_trust_score": 0.52,
            "bootstrap_reduced_size_paper_only": True,
        }
        intent.update(overrides)
        return intent

    def _classify(self, intent, *, cluster_gate=None, guardian=None):
        return paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
            signal={
                "selected_action": intent.get("side"),
                "confidence_calibrated": intent.get("confidence_calibrated"),
                "expected_move_after_cost_bps": intent.get(
                    "expected_move_after_cost_bps"
                ),
            },
            intent=intent,
            allocation=_allowed_allocation(
                confidence_calibrated=intent.get("confidence_calibrated"),
                expected_move_after_cost_bps=intent.get(
                    "expected_move_after_cost_bps"
                ),
            ),
            integrity_gate={"allowed": True},
            local_trade_gates_pass=False,
            exploration_trade_gates_pass=True,
            paper_fill_allowed_upstream=False,
            portfolio_drawdown_bps=0.0,
            continuous_edge_guardian_gate=(
                guardian if guardian is not None else _active_guardian_gate()
            ),
            high_confidence_loss_cluster_gate=cluster_gate,
            preemptive_decision=_allow_preemptive_decision(),
    )

    def test_bootstrap_flag_without_any_trust_evidence_is_denied(self) -> None:
        intent = self._bootstrap_intent(
            public_orderbook_trust_score=None,
            composite_microstructure_trust_score=None,
        )
        intent.pop("public_orderbook_trust_score")
        intent.pop("composite_microstructure_trust_score")
        classification = self._classify(intent)
        assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
        assert classification["paper_opportunity_tier_reason"] == (
            "MICROSTRUCTURE_TRUST_EVIDENCE_MISSING_BOOTSTRAP_DENIED"
        )
        assert classification["counts_as_final_a_plus"] is False
        assert classification["routes_to_live"] is False
        assert classification["places_real_order"] is False

    def test_cluster_side_dimension_quarantines_short_candidate(self) -> None:
        intent = self._bootstrap_intent(
            symbol="LINKUSDT", side="short", expected_move_after_cost_bps=-18.0
        )
        classification = self._classify(intent, cluster_gate=self._cluster_gate())
        assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
        assert classification["paper_opportunity_tier_reason"] == (
            "HIGH_CONFIDENCE_LOSS_CLUSTER_BUCKET_QUARANTINED"
        )
        assert "HIGH_CONFIDENCE_LOSS_CLUSTER_SIDE_QUARANTINED" in classification[
            "high_confidence_loss_cluster_bucket_match_reasons"
        ]
        assert classification["counts_as_final_a_plus"] is False

    def test_cluster_symbol_quarantine_blocks_even_unquarantined_side(self) -> None:
        intent = self._bootstrap_intent(symbol="CAKEUSDT", side="long")
        classification = self._classify(intent, cluster_gate=self._cluster_gate())
        assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
        assert "HIGH_CONFIDENCE_LOSS_CLUSTER_SYMBOL_QUARANTINED" in classification[
            "high_confidence_loss_cluster_bucket_match_reasons"
        ]

    def test_unrelated_bucket_not_blocked_by_cluster_gate(self) -> None:
        intent = self._bootstrap_intent(symbol="DOGEUSDT", side="long", timeframe="15m")
        classification = self._classify(intent, cluster_gate=self._cluster_gate())
        assert classification["paper_opportunity_tier_reason"] != (
            "HIGH_CONFIDENCE_LOSS_CLUSTER_BUCKET_QUARANTINED"
        )
        assert classification["high_confidence_loss_cluster_bucket_match_reasons"] == []

    def test_missing_cluster_evidence_fails_closed(self) -> None:
        gate = paper_loop._high_confidence_loss_cluster_gate(None)  # noqa: SLF001
        assert gate["cluster_detected"] is True
        assert gate["cluster_evidence_missing"] is True
        intent = self._bootstrap_intent()
        classification = self._classify(intent, cluster_gate=gate)
        assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
        assert classification["paper_opportunity_tier_reason"] == (
            "HIGH_CONFIDENCE_LOSS_CLUSTER_BUCKET_QUARANTINED"
        )

    def test_final_a_plus_denied_while_cluster_active_even_for_unrelated_a_grade(
        self,
    ) -> None:
        classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
            signal={
                "selected_action": "long",
                "confidence_calibrated": 0.80,
                "expected_move_after_cost_bps": 15.0,
            },
            intent={
                "symbol": "DOGEUSDT",
                "timeframe": "15m",
                "side": "long",
                "strategy_selected_mode": "trend_mode",
                "confidence_calibrated": 0.80,
                "expected_move_after_cost_bps": 15.0,
            },
            allocation=_allowed_allocation(expected_move_after_cost_bps=15.0),
            integrity_gate={"allowed": True},
            local_trade_gates_pass=True,
            paper_fill_allowed_upstream=True,
            portfolio_drawdown_bps=0.0,
            high_confidence_loss_cluster_gate=self._cluster_gate(),
            preemptive_decision=_allow_preemptive_decision(),
    )
        assert classification["paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
        assert classification["counts_as_final_a_plus"] is False
        assert classification[
            "final_a_plus_denied_by_high_confidence_loss_cluster"
        ] is True


class TestCgF044StateFileOverrideAndSyntheticQuarantine:
    """CG-F044: state file must never displace non-empty Redis close history,
    and close rows with no exit evidence must be quarantined, not counted."""

    _FIXTURE_STUB = {
        "trainer_feedback_id": "fb_incomplete",
        "outcome_label_id": "out_incomplete",
        "position_id": "pos_incomplete",
        "symbol": "BTCUSDT",
        "realized_pnl_bps": 4.2,
        "hold_time_seconds": 120,
        "exit_reason": "TIER_2_TAKE_PROFIT",
    }

    def _real_close(self, i: int) -> dict[str, object]:
        return {
            "close_id": f"close_{i}",
            "symbol": "ETHUSDT",
            "side": "long",
            "exit_price_utc": "2026-07-08T15:00:00Z",
            "realized_pnl_bps": 10.0 + i,
            "paper_session_id": "sess_a",
        }

    def test_state_file_does_not_override_non_empty_redis_closes(
        self, monkeypatch
    ) -> None:
        redis_rows = [self._real_close(i) for i in range(18)]
        fake = _FakeRedis(
            {
                "v2:paper:closed_trades": redis_rows,
                "v2:paper:outcome_labels": [{"outcome_label_id": "lbl_1"}],
            }
        )
        monkeypatch.setattr(
            paper_loop,
            "_read_lifecycle_state_file",
            lambda *a, **kw: {
                "closed_trades": [dict(self._FIXTURE_STUB)],
                "closes": [dict(self._FIXTURE_STUB)],
                "outcome_labels": [],
            },
        )
        payload = paper_loop._read_existing_ledger_payload(fake)  # noqa: SLF001
        assert len(payload["closed_trades"]) == 18
        assert len(payload["closes"]) == 18
        assert payload["closed_trades"][0]["close_id"] == "close_0"
        assert len(payload["outcome_labels"]) == 1

    def test_state_file_still_rescues_when_redis_read_is_empty(
        self, monkeypatch
    ) -> None:
        fake = _FakeRedis({})
        rescue_rows = [self._real_close(0)]
        monkeypatch.setattr(
            paper_loop,
            "_read_lifecycle_state_file",
            lambda *a, **kw: {"closed_trades": rescue_rows, "closes": rescue_rows},
        )
        payload = paper_loop._read_existing_ledger_payload(fake)  # noqa: SLF001
        assert len(payload["closed_trades"]) == 1
        assert payload["closed_trades"][0]["close_id"] == "close_0"

    def test_fixture_stub_without_exit_evidence_is_quarantined(self) -> None:
        real = self._real_close(1)
        restored_compact = {
            "symbol": "TLMUSDT",
            "side": "long",
            "realized_pnl_bps": 493.52,
            "reconstructed_from_artifacts": True,
        }
        kept, quarantined = paper_loop._split_closes_without_exit_evidence(  # noqa: SLF001
            [real, dict(self._FIXTURE_STUB), restored_compact]
        )
        assert real in kept
        assert restored_compact in kept
        assert len(quarantined) == 1
        assert quarantined[0]["position_id"] == "pos_incomplete"
        assert (
            quarantined[0]["quarantine_reason"]
            == "NO_EXIT_EVIDENCE_SYNTHETIC_OR_TEST_ROW"
        )
        assert quarantined[0]["counts_as_closed_trade"] is False

    def test_exit_time_alone_counts_as_exit_evidence(self) -> None:
        row = {
            "symbol": "SOLUSDT",
            "side": "short",
            "exit_time": "2026-07-08T15:05:00Z",
            "realized_pnl_bps": -3.0,
        }
        kept, quarantined = paper_loop._split_closes_without_exit_evidence(  # noqa: SLF001
            [row]
        )
        assert kept == [row]
        assert quarantined == []
