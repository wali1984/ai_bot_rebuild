from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli import v2_paper_timeframe_churn_governance_audit as governance_audit
from v2.backend.app.cli.v2_paper_timeframe_churn_governance_audit import (
    OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS,
    PAPER_ROUTING_COMPONENTS,
    compact_economic_trades,
    current_paper_economic_trade_reconciliation,
    current_paper_timeframe_churn_audit,
    dynamic_timeframe_execution_eligibility_status,
    economic_trade_compaction_status,
    go_no_go_markdown,
    multi_timeframe_thesis_execution_contract_status,
    operator_dashboard_payload,
    operator_dashboard_truth_contract,
    paper_edge_to_cost_gate_status,
    paper_entry_cost_coverage_status,
    paper_churn_governor_runtime_wiring_status,
    paper_churn_governor_trace_status,
    paper_entry_cost_runtime_wiring_status,
    paper_governance_summary_pass_conditions,
    paper_governance_summary_source_blocker_fields,
    paper_governance_phase_trace,
    paper_reentry_dedup_runtime_wiring_status,
    paper_standalone_1m_runtime_wiring_status,
    paper_trade_management_reentry_dedup_runtime_wiring_status,
    paper_trade_management_standalone_1m_runtime_wiring_status,
    paper_timeframe_routing_repair_contract,
    paper_timeframe_routing_owner_status,
    paper_reentry_and_signal_dedup_status,
    post_fix_economic_outcome_sample,
    post_fix_paper_validation_status,
    read_local_paper_event_close_rows,
    repair_report_markdown,
    scan_hardcoded_timeframe_paths,
    timeframe_execution_concentration_guard_status,
)
from v2.backend.app.services.paper_churn_governor import (
    evaluate_churn_governor,
    evaluate_churn_governor_entry_gate,
)


REPO_ROOT = Path(__file__).resolve().parents[5]


def _closed_row(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "side": "LONG",
        "entry_prediction_id": "pred-1",
        "entry_signal_id": "sig-1",
        "entry_feature_snapshot_id": "snap-1",
        "entry_price": 100.0,
        "entry_feature_decision_time": "2026-06-25T00:00:00Z",
        "exit_price_utc": "2026-06-25T01:00:00Z",
        "strategy_id": "strategy-a",
        "model_source": "old-policy-model",
        "trainer_source": "old-trainer",
        "policy_version": "old-policy",
        "gross_pnl_usd": 2.0,
        "realized_pnl_usd": 1.5,
        "fees_usd": 0.25,
        "realized_slippage_usd": 0.10,
        "funding_pnl_usd": -0.05,
        "gross_notional_usd": 100.0,
        "close_reason": "partial_close",
    }
    row.update(overrides)
    return row


def _contract_row(**overrides):
    row = _closed_row(
        thesis_timeframe="1h",
        execution_timeframe="1m",
        confirmation_timeframes=["15m", "4h"],
        strategy_horizon_seconds=3600,
        expected_holding_period_seconds=3600,
        thesis_prediction_id="thesis-pred-1",
        execution_snapshot_id="exec-snap-1",
        economic_trade_id="econ-1",
        economic_thesis_id="thesis-1",
        parent_position_id="position-1",
        entry_feature_cutoff="2026-06-25T00:00:00Z",
        market_regime_at_entry="trend",
        expected_move_after_cost_bps=20.0,
        close_reason="full_close",
    )
    row.update(overrides)
    return row


def _production_grade_cost_row(**overrides):
    row = _contract_row(
        actual_observed_spread_entry_bps=2.0,
        expected_fee_bps=4.0,
        depth_price_impact_bps=1.0,
        depth_price_impact_source="unit_test_depth",
        expected_slippage_bps=1.5,
        expected_funding_bps=0.2,
        latency_reserve_bps=0.5,
        partial_fill_reserve_bps=0.25,
        round_trip_cost_bps=9.45,
        cost_uncertainty_bps=1.0,
        expected_gross_edge_bps=30.0,
        expected_net_edge_bps=20.0,
    )
    row.update(overrides)
    return row


def _post_fix_outcome_row(index: int, **overrides):
    timeframe = ["1m", "5m", "15m", "1h", "4h"][index % 5]
    row = _production_grade_cost_row(
        close_id=f"post-fix-close-{index}",
        symbol=f"SYM{index % 30:02d}USDT",
        timeframe=timeframe,
        thesis_timeframe=timeframe,
        execution_timeframe="1m" if timeframe != "1m" else "1m",
        confirmation_timeframes=["5m", "15m"] if timeframe == "1m" else ["1m"],
        strategy_horizon_seconds=3600,
        expected_holding_period_seconds=3600,
        thesis_prediction_id=f"post-fix-pred-{index}",
        execution_snapshot_id=f"post-fix-exec-snap-{index}",
        entry_prediction_id=f"post-fix-pred-{index}",
        entry_signal_id=f"post-fix-sig-{index}",
        entry_feature_snapshot_id=f"post-fix-feature-snap-{index}",
        economic_trade_id=f"post-fix-econ-{index}",
        economic_thesis_id=f"post-fix-thesis-{index}",
        parent_position_id=f"post-fix-position-{index}",
        paper_result="POSITION_CLOSED_PAPER_ONLY",
        realized_pnl_usd=1.0,
        exchange_order=False,
        live_order=False,
        routes_to_live=False,
        places_real_order=False,
        legacy_redis_write=False,
        close_reason="full_close",
    )
    row.update(overrides)
    return row


def test_compacts_partial_close_rows_into_one_economic_trade() -> None:
    rows = [
        _closed_row(close_id="close-1", realized_pnl_usd=1.0),
        _closed_row(close_id="close-2", realized_pnl_usd=2.0, exit_price_utc="2026-06-25T02:00:00Z"),
    ]

    compacted = compact_economic_trades(rows)
    reconciliation = current_paper_economic_trade_reconciliation(
        closed_rows=rows,
        portfolio_state={"closed_ledger_net_pnl_usd": 3.0},
        ledger={"closed_trade_count": 2},
    )
    compaction = economic_trade_compaction_status(
        closed_rows=rows,
        reconciliation=reconciliation,
    )

    assert len(compacted) == 1
    assert compacted[0]["raw_close_record_count"] == 2
    assert compacted[0]["is_partial_close"] is True
    assert compacted[0]["net_pnl_usd"] == 3.0
    assert reconciliation["status"] == "PASS_ECONOMIC_TRADE_RECONCILIATION"
    assert reconciliation["accounting_reconciliation_status"] == "PASS_ECONOMIC_TRADE_RECONCILIATION"
    assert reconciliation["position_count"] == 1
    assert reconciliation["pass_conditions"]["raw_close_sum_equals_compacted_sum_within_one_cent"] is True
    assert reconciliation["all_closed_rows_have_explicit_realized_pnl"] is True
    assert reconciliation["explicit_realized_pnl_sum_matches_portfolio_within_one_cent"] is True
    assert reconciliation["raw_close_sum_equals_compacted_sum_within_one_cent"] is True
    assert reconciliation["compacted_sum_equals_portfolio_realized_pnl_within_one_cent"] is True
    assert reconciliation["current_closed_records_sum_pnl_usd"] == 3.0
    assert reconciliation["compacted_sum_pnl_usd"] == 3.0
    assert reconciliation["compacted_economic_trade_net_pnl_sum"] == 3.0
    assert reconciliation["portfolio_closed_pnl_usd"] == 3.0
    assert reconciliation["portfolio_realized_pnl"] == 3.0
    assert reconciliation["explicit_realized_pnl_sum"] == 3.0
    assert reconciliation["pnl_delta"] == 0.0
    assert reconciliation["portfolio_realized_pnl_source"] == "portfolio_state"
    assert reconciliation["raw_closed_trade_count_matches_ledger"] is True
    assert reconciliation["ledger_closed_trade_count_matches_raw_rows"] is True
    assert reconciliation["reconciliation_blocker_count"] == 0
    assert reconciliation["reconciliation_blockers"] == []
    assert reconciliation["blocked_reasons"] == []
    assert reconciliation["blocker_details"] == []
    assert reconciliation["failed_blocker_details"] == []
    assert reconciliation["actuals"]["raw_closed_rows_gt_0"] == 2
    assert reconciliation["actuals"]["economic_trade_rows_gt_0"] == 1
    assert reconciliation["actuals"]["all_closed_rows_have_explicit_realized_pnl"] == {
        "explicit_realized_rows": 2,
        "raw_close_record_count": 2,
        "missing_rows": 0,
    }
    assert reconciliation["required"]["compacted_sum_equals_portfolio_realized_pnl_within_one_cent"] == (
        "absolute difference <= 0.01 USD"
    )
    assert reconciliation["sample_blockers"] == []
    assert reconciliation["counts_as_a_grade_evidence"] is False
    assert reconciliation["closed_rows_with_explicit_realized_pnl_count"] == 2
    assert reconciliation["closed_rows_using_fallback_cost_formula_count"] == 0
    assert reconciliation["sample_reconciliation_gaps"] == []
    assert compaction["status"] == "BLOCKED_ECONOMIC_TRADE_COMPACTION"
    assert compaction["raw_rows_with_explicit_economic_trade_id"] == 0
    assert compaction["raw_identity_present_counts"] == {
        "economic_thesis_id": 0,
        "economic_trade_id": 0,
        "parent_position_id": 0,
    }
    assert compaction["raw_identity_missing_field_counts"] == {
        "economic_thesis_id": 2,
        "economic_trade_id": 2,
        "parent_position_id": 2,
    }
    assert compaction["required_raw_identity_fields"] == [
        "economic_trade_id",
        "economic_thesis_id",
        "parent_position_id",
    ]
    assert compaction["missing_raw_identity_fields"] == [
        "economic_thesis_id",
        "economic_trade_id",
        "parent_position_id",
    ]
    assert compaction["raw_identity_missing_required_field_count"] == 3
    assert compaction["raw_identity_missing_required_row_total"] == 6
    assert compaction["missing_required_fields"] == []
    assert compaction["missing_required_field_count"] == 0
    assert compaction["missing_required_row_total"] == 0
    assert compaction["portfolio_realized_pnl"] == 3.0
    assert compaction["compacted_economic_trade_net_pnl"] == 3.0
    assert compaction["accounting_reconciliation_status"] == "PASS_ECONOMIC_TRADE_RECONCILIATION"
    assert compaction["actuals"]["raw_rows_have_explicit_economic_trade_id"] == 0
    assert compaction["required"]["raw_rows_have_explicit_economic_trade_id"] == 2
    assert compaction["sample_blockers"] == compaction["blocker_details"][:25]
    assert compaction["raw_identity_field_coverage"] == {
        "economic_thesis_id": 0.0,
        "economic_trade_id": 0.0,
        "parent_position_id": 0.0,
    }
    assert compaction["sample_raw_rows_missing_economic_trade_identity"][0]["missing_identity_fields"] == [
        "economic_trade_id",
        "economic_thesis_id",
        "parent_position_id",
    ]
    assert compaction["duplicate_economic_trade_count"] == 2
    assert compaction["duplicate_identity_violation_count"] == 2
    assert compaction["duplicate_economic_trade_samples"] == compaction["duplicate_identity_violation_samples"]
    assert compaction["duplicate_identity_sample_count"] == len(compaction["duplicate_economic_trade_samples"])
    assert compaction["duplicate_identity_sample_count"] > 0
    assert {
        sample["duplicate_identity_field"]
        for sample in compaction["duplicate_economic_trade_samples"]
    } <= {
        "same_prediction_duplicate_entries",
        "same_decision_duplicate_entries",
        "same_candle_duplicate_entries",
    }
    assert compaction["duplicate_economic_trade_samples"][0]["duplicate_count"] >= 1
    assert compaction["duplicate_economic_trade_samples"][0]["sample_raw_record_ids"]
    assert compaction["unexplained_same_candle_reentries"] == 1
    assert compaction["pass_conditions"]["raw_rows_have_explicit_economic_trade_id"] is False
    assert "raw_rows_have_explicit_economic_trade_id" in compaction["blocked_reasons"]
    assert compaction["failed_blocker_details"] == compaction["blocker_details"]
    assert compaction["counts_as_a_grade_evidence"] is False


def test_run_audit_summary_publishes_required_artifact_contract(tmp_path, monkeypatch) -> None:
    closed_row = _production_grade_cost_row(
        close_id="close-1",
        realized_pnl_usd=1.5,
        economic_trade_id="econ-1",
        economic_thesis_id="thesis-1",
        parent_position_id="position-1",
        close_reason="full_close",
    )
    ledger = {
        "closed_trade_count": 1,
        "accepted": [closed_row],
    }
    portfolio_state = {"closed_ledger_net_pnl_usd": 1.5, "closed_positions_count": 1}
    heartbeat = {"closed_trade_count": 1}
    local_post_fix_close = _post_fix_outcome_row(2, economic_trade_id="local-econ-1")

    def fake_read_redis_payloads():
        return (
            {
                "v2:paper:closed_trades": {"closed_trades": [closed_row]},
                "v2:paper:ledger": ledger,
                "v2:portfolio:state": portfolio_state,
                "v2:paper:heartbeat": heartbeat,
                "_signals": {},
            },
            {
                "v2:paper:closed_trades": {"exists": True, "json_status": "PASS"},
                "v2:paper:ledger": {"exists": True, "json_status": "PASS"},
                "v2:portfolio:state": {"exists": True, "json_status": "PASS"},
                "v2:paper:heartbeat": {"exists": True, "json_status": "PASS"},
            },
        )

    def fake_read_local_paper_event_close_rows(repo_root):
        row = dict(local_post_fix_close)
        row["_post_fix_sample_source"] = "paper_online_latest_jsonl"
        row["_post_fix_sample_source_path"] = str(repo_root / "v2/runtime/paper_online/latest/paper_events.jsonl")
        row["_post_fix_sample_line_number"] = 12
        return (
            [row],
            {
                "paper_online_latest_jsonl": {
                    "status": "PASS_LOCAL_PAPER_EVENTS_JSONL_READ",
                    "closed_paper_outcome_rows": 1,
                    "line_count": 12,
                }
            },
        )

    monkeypatch.setattr(governance_audit, "read_redis_payloads", fake_read_redis_payloads)
    monkeypatch.setattr(
        governance_audit,
        "read_local_paper_event_close_rows",
        fake_read_local_paper_event_close_rows,
    )

    summary = governance_audit.run_audit(repo_root=REPO_ROOT, out_dir=tmp_path)

    assert summary["artifacts_written"] == list(governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    assert summary["source_artifacts_written"] == summary["artifacts_written"]
    assert summary["source_artifact_count"] == len(governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    assert summary["required_artifacts"] == list(governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    assert summary["required_artifact_count"] == len(governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    assert summary["source_required_artifact_count"] == len(governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS)
    assert summary["missing_required_artifacts"] == []
    assert summary["missing_required_artifact_count"] == 0
    assert summary["source_missing_required_artifact_count"] == 0
    assert summary["required_artifacts_present"] is True
    assert summary["source_required_artifacts_present"] is True
    assert summary["pass_conditions"]["required_artifacts_present"] is True
    assert isinstance(summary["ready"], bool)
    assert isinstance(summary["hardcoded_1m_economic_paths_removed"], bool)
    assert isinstance(summary["silent_1m_fallbacks_absent"], bool)
    assert summary["current_closed_ledger_recomputed"] is True
    assert summary["current_timeframe_distribution_proven"] is True
    assert summary["economic_trade_compaction_present"] is True
    assert summary["blocked_conditions"] == summary["blocked_reasons"]
    assert summary["blocked_condition_count"] == len(summary["blocked_conditions"])
    assert summary["blocker_count"] == len(summary["blocked_conditions"])
    assert summary["failed_pass_conditions"] == summary["blocked_conditions"]
    assert summary["source_blocked_conditions"] == summary["blocked_conditions"]
    assert summary["source_blocked_condition_count"] == len(summary["blocked_conditions"])
    assert summary["source_blocked_pass_conditions"] == summary["blocked_conditions"]
    assert summary["source_blocker_count"] == len(summary["blocked_conditions"])
    assert summary["source_paper_governance_blockers_cleared"] == (len(summary["blocked_conditions"]) == 0)
    assert summary["actuals"]["final_gate_ready"] == summary["final_gate"]
    assert summary["required"]["final_gate_ready"] == governance_audit.FINAL_READY_MARKER
    assert summary["sample_blockers"] == summary["blocker_details"][:25]
    assert summary["phase_blocker_count"] == sum(len(blockers) for blockers in summary["phase_blockers"].values())
    assert len(summary["phase_blocked_conditions"]) == summary["phase_blocker_count"]
    assert {
        (row["phase"], row["blocked_condition"])
        for row in summary["phase_blocked_conditions"]
    } == {
        (phase, condition)
        for phase, blockers in summary["phase_blockers"].items()
        for condition in blockers
    }
    assert summary["post_fix_sample_raw_close_rows"] == 2
    assert summary["post_fix_sample_eligible_raw_close_rows"] == 1
    assert summary["post_fix_sample_source_counts"] == {
        "paper_online_latest_jsonl": 1,
        "redis_v2_paper_closed_trades": 1,
    }
    assert summary["post_fix_sample_eligible_source_counts"] == {"paper_online_latest_jsonl": 1}
    assert summary["post_fix_sample_excluded_source_counts"] == {"redis_v2_paper_closed_trades": 1}
    assert summary["post_fix_sample_source_read_status"]["paper_online_latest_jsonl"]["closed_paper_outcome_rows"] == 1
    assert summary["post_fix_sample_sample_excluded_rows"][0]["source"] == "redis_v2_paper_closed_trades"
    assert summary["post_fix_sample_excluded_row_samples"] == summary["post_fix_sample_sample_excluded_rows"]
    assert summary["sample_excluded_rows"] == summary["post_fix_sample_sample_excluded_rows"]
    assert summary["excluded_row_samples"] == summary["post_fix_sample_sample_excluded_rows"]
    assert summary["post_fix_sample_sample_excluded_rows_by_source"]["redis_v2_paper_closed_trades"][0]["source"] == (
        "redis_v2_paper_closed_trades"
    )
    assert summary["post_fix_sample_sample_compacted_economic_trades"][0]["economic_trade_id"] == "local-econ-1"
    for artifact in governance_audit.REQUIRED_PAPER_GOVERNANCE_ARTIFACTS:
        assert (tmp_path / artifact).exists()


def test_read_local_paper_event_close_rows_filters_append_only_closed_events(tmp_path) -> None:
    path = tmp_path / "v2/runtime/paper_online/latest/paper_events.jsonl"
    path.parent.mkdir(parents=True)
    closed = _post_fix_outcome_row(7)
    blocked = _post_fix_outcome_row(8, paper_result="NO_FILL_RISK_BLOCKED", realized_pnl_usd=None)
    path.write_text(
        "\n".join(
            [
                json.dumps(blocked),
                "not-json POSITION_CLOSED_PAPER_ONLY",
                json.dumps(closed),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows, status = read_local_paper_event_close_rows(tmp_path)

    source_status = status["paper_online_latest_jsonl"]
    assert len(rows) == 1
    assert rows[0]["paper_result"] == "POSITION_CLOSED_PAPER_ONLY"
    assert rows[0]["_post_fix_sample_source"] == "paper_online_latest_jsonl"
    assert rows[0]["_post_fix_sample_line_number"] == 3
    assert source_status["line_count"] == 3
    assert source_status["candidate_close_line_count"] == 2
    assert source_status["closed_paper_outcome_rows"] == 1
    assert source_status["json_decode_error_count"] == 1
    assert source_status["status"] == "READ_LOCAL_PAPER_EVENTS_JSONL_WITH_ERRORS"


def test_reconciliation_reports_portfolio_gap_details() -> None:
    payload = current_paper_economic_trade_reconciliation(
        closed_rows=[_closed_row(realized_pnl_usd=2.0, fees_usd=0.0, realized_slippage_usd=0.0)],
        portfolio_state={"closed_ledger_net_pnl_usd": 2.25},
        ledger={"realized_pnl_usd": 2.0, "closed_trade_count": 1},
    )

    assert payload["status"] == "FAIL_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["current_closed_records_sum_pnl_usd"] == 2.0
    assert payload["compacted_sum_pnl_usd"] == 2.0
    assert payload["portfolio_closed_pnl_usd"] == 2.25
    assert payload["ledger_closed_pnl_usd"] == 2.0
    assert payload["portfolio_realized_pnl_source"] == "portfolio_state"
    assert payload["ledger_closed_trade_count"] == 1
    assert payload["raw_closed_trade_count_matches_ledger"] is True
    assert payload["accounting_reconciliation_status"] == "FAIL_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["reconciliation_blocker_count"] == 2
    assert payload["reconciliation_blockers"] == [
        "explicit_realized_pnl_sum_matches_portfolio_within_one_cent",
        "compacted_sum_equals_portfolio_realized_pnl_within_one_cent",
    ]
    assert payload["blocked_reasons"] == payload["reconciliation_blockers"]
    assert {
        detail["pass_condition"] for detail in payload["blocker_details"]
    } == set(payload["reconciliation_blockers"])
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["explicit_realized_pnl_sum_matches_portfolio_within_one_cent"] == {
        "explicit_realized_pnl_sum_usd": 2.0,
        "portfolio_realized_pnl_usd": 2.25,
        "difference_usd": -0.25,
        "portfolio_realized_pnl_source": "portfolio_state",
    }
    assert payload["actuals"]["compacted_sum_equals_portfolio_realized_pnl_within_one_cent"]["difference_usd"] == -0.25
    assert payload["required"]["explicit_realized_pnl_sum_matches_portfolio_within_one_cent"] == (
        "absolute difference <= 0.01 USD"
    )
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert payload["pass_conditions"]["all_closed_rows_have_explicit_realized_pnl"] is True
    assert any(
        gap["invariant"] == "compacted_sum_equals_portfolio_realized_pnl_within_one_cent"
        for gap in payload["sample_reconciliation_gaps"]
    )
    assert any(gap.get("difference_usd") == -0.25 for gap in payload["sample_reconciliation_gaps"])


def test_reconciliation_reports_stale_closed_trade_count_gap() -> None:
    payload = current_paper_economic_trade_reconciliation(
        closed_rows=[_closed_row(realized_pnl_usd=2.0, fees_usd=0.0, realized_slippage_usd=0.0)],
        portfolio_state={"closed_ledger_net_pnl_usd": 2.0},
        ledger={"realized_pnl_usd": 2.0, "closed_trade_count": 2},
    )

    assert payload["status"] == "FAIL_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["raw_closed_trade_count_matches_ledger"] is False
    assert payload["ledger_closed_trade_count_matches_raw_rows"] is False
    assert payload["pass_conditions"]["ledger_closed_trade_count_matches_raw_rows"] is False
    assert payload["sample_reconciliation_gaps"][0]["invariant"] == "ledger_closed_trade_count_matches_raw_rows"


def test_reconciliation_reports_rows_using_fallback_cost_formula() -> None:
    payload = current_paper_economic_trade_reconciliation(
        closed_rows=[
            _closed_row(
                realized_pnl_usd=None,
                realized_net_pnl_usd=None,
                fees_usd=0.0,
                gross_pnl_usd=0.0,
                realized_slippage_usd=0.5,
                funding_pnl_usd=0.0,
            )
        ],
        portfolio_state={"closed_ledger_net_pnl_usd": 0.0},
        ledger={"realized_pnl_usd": 0.0, "closed_trade_count": 1},
    )

    assert payload["status"] == "FAIL_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["closed_rows_with_explicit_realized_pnl_count"] == 0
    assert payload["closed_rows_using_fallback_cost_formula_count"] == 1
    assert payload["fallback_formula_net_pnl_usd"] == -0.5
    assert payload["all_closed_rows_have_explicit_realized_pnl"] is False
    assert payload["pass_conditions"]["all_closed_rows_have_explicit_realized_pnl"] is False
    assert payload["actuals"]["all_closed_rows_have_explicit_realized_pnl"] == {
        "explicit_realized_rows": 0,
        "raw_close_record_count": 1,
        "missing_rows": 1,
    }
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert payload["sample_rows_using_fallback_cost_formula"][0]["net_pnl_usd_used_by_audit"] == -0.5


def test_current_paper_churn_audit_reports_timeframe_share_and_old_policy_owner() -> None:
    rows = [
        _closed_row(timeframe="1m", close_id="close-1", entry_prediction_id="pred-1", entry_signal_id="sig-1"),
        _closed_row(timeframe="1m", close_id="close-2", entry_prediction_id="pred-2", entry_signal_id="sig-2"),
        _closed_row(timeframe="1h", close_id="close-3", entry_prediction_id="pred-3", entry_signal_id="sig-3"),
    ]

    payload = current_paper_timeframe_churn_audit(
        closed_rows=rows,
        ledger={"closed_trade_count": 3},
        portfolio_state={"closed_positions_count": 3},
        heartbeat={"closed_trade_count": 3},
        challenger_candidate_id="challenger-v2",
    )

    assert payload["raw_close_record_count"] == 3
    assert payload["trade_count_by_timeframe"] == {"1h": 1, "1m": 2}
    assert payload["current_1m_share"] == 2 / 3
    assert payload["challenger_trade_count"] == 0
    assert payload["old_policy_trade_count"] == 3
    assert payload["required_attribution_fields_present"] is True
    assert payload["attribution_missing_counts"] == {}
    assert payload["records_missing_required_attribution_count"] == 0
    assert payload["record_attribution"]["records_missing_required_attribution_count"] == 0
    assert payload["pass_conditions"]["required_attribution_fields_present"] is True
    assert payload["blocked_reasons"] == []
    assert payload["actuals"]["current_1m_share_present"] == 2 / 3
    assert payload["required"]["challenger_remains_paper_inactive"] == 0
    assert payload["sample_blockers"] == []
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_routing_owner_flags_hardcoded_1m_path(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        'r.set(f"v2:signals:paper:{symbol_key}:1m", json.dumps(signal_record))\n',
        encoding="utf-8",
    )

    payload = paper_timeframe_routing_owner_status(
        repo_root=tmp_path,
        closed_rows=[
            _closed_row(timeframe="1m", close_id="close-1"),
            _closed_row(timeframe="1h", close_id="close-2", entry_prediction_id="pred-2"),
        ],
        heartbeat={"worker_id": "paper_online_runtime"},
        redis_signal_payloads={
            "v2:signals:paper:BTCUSDT:1m": {"symbol": "BTCUSDT", "timeframe": "1m"},
            "v2:signals:paper:BTCUSDT:1h": {"symbol": "BTCUSDT", "timeframe": "1h"},
        },
        challenger_candidate_id="challenger-v2",
    )

    assert payload["status"] == "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    assert payload["hardcoded_1m_path_count"] == 1
    assert payload["pass_conditions"]["hardcoded_1m_economic_paths_absent"] is False
    assert payload["paper_fill_owner"] == "paper_online_runtime"
    assert payload["old_policy_controls_paper"] is True
    assert payload["challenger_controls_paper"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_routing_owner_flags_silent_1m_thesis_fallback(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                'PAPER_EXECUTION_TIMING_TIMEFRAME = "1m"',
                "def _paper_thesis_timeframe(*sources):",
                "    return PAPER_EXECUTION_TIMING_TIMEFRAME",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    routing = paper_timeframe_routing_owner_status(
        repo_root=tmp_path,
        closed_rows=[
            _closed_row(timeframe="1m", close_id="close-1"),
            _closed_row(timeframe="1h", close_id="close-2", entry_prediction_id="pred-2"),
        ],
        heartbeat={"worker_id": "paper_online_runtime"},
        redis_signal_payloads={
            "v2:signals:paper:BTCUSDT:1m": {"symbol": "BTCUSDT", "timeframe": "1m"},
            "v2:signals:paper:BTCUSDT:1h": {"symbol": "BTCUSDT", "timeframe": "1h"},
        },
        challenger_candidate_id="challenger-v2",
    )
    repair = paper_timeframe_routing_repair_contract(routing=routing)

    assert routing["status"] == "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    assert routing["hardcoded_1m_path_count"] == 0
    assert routing["silent_1m_fallback_path_count"] == 1
    assert routing["timeframe_routing_violation_count"] == 1
    assert routing["pass_conditions"]["silent_1m_thesis_or_economic_fallbacks_absent"] is False
    assert "silent_1m_thesis_or_economic_fallbacks_absent" in routing["blocked_reasons"]
    assert routing["silent_1m_fallback_paths"][0]["function"] == "_paper_thesis_timeframe"
    assert routing["silent_1m_fallback_paths"][0]["reason"] == "unsafe_thesis_or_economic_timeframe_default_to_execution_1m"
    assert repair["status"] == "BLOCKED_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT"
    assert repair["silent_1m_fallback_path_count"] == 1
    assert repair["timeframe_routing_violation_count"] == 1
    assert repair["repair_steps"][0]["repair_kind"] == "remove_silent_1m_thesis_or_economic_fallback"
    assert repair["pass_conditions"]["repair_steps_cover_all_current_silent_fallbacks"] is True
    assert repair["pass_conditions"]["silent_1m_fallbacks_absent"] is False


def test_routing_repair_contract_blocks_and_maps_hardcoded_paths(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                'feature_timeframe = "1m"',
                'snapshot = fetch_unified_market_snapshot(symbol, timeframe="1m", limit=30)',
                'r.set(f"v2:signals:paper:{symbol_key}:1m", json.dumps(signal_record))',
                'timeframe="1m",',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    routing = paper_timeframe_routing_owner_status(
        repo_root=tmp_path,
        closed_rows=[
            _closed_row(timeframe="1m", close_id="close-1"),
            _closed_row(timeframe="1h", close_id="close-2", entry_prediction_id="pred-2"),
        ],
        heartbeat={"worker_id": "paper_online_runtime"},
        redis_signal_payloads={
            "v2:signals:paper:BTCUSDT:1m": {"symbol": "BTCUSDT", "timeframe": "1m"},
            "v2:signals:paper:BTCUSDT:1h": {"symbol": "BTCUSDT", "timeframe": "1h"},
        },
        challenger_candidate_id="challenger-v2",
    )
    payload = paper_timeframe_routing_repair_contract(routing=routing)

    assert payload["status"] == "BLOCKED_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT"
    assert payload["hardcoded_1m_path_count"] == 4
    assert len(payload["repair_steps"]) == 4
    assert payload["pass_conditions"]["repair_steps_cover_all_current_hardcoded_paths"] is True
    assert payload["pass_conditions"]["hardcoded_1m_paths_absent"] is False
    assert payload["forbidden_changes"]
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_routing_owner_traces_complete_paper_chain(tmp_path) -> None:
    file_terms: dict[str, set[str]] = {}
    for component in PAPER_ROUTING_COMPONENTS:
        for file_name in component["files"]:
            file_terms.setdefault(str(file_name), set())
        first_file = str(component["files"][0])
        for term in component["required_terms"]:
            file_terms[first_file].add(str(term))
    for relative, terms in file_terms.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(terms)) + "\n", encoding="utf-8")

    payload = paper_timeframe_routing_owner_status(
        repo_root=tmp_path,
        closed_rows=[
            _closed_row(timeframe="1m", close_id="close-1"),
            _closed_row(timeframe="1h", close_id="close-2", entry_prediction_id="pred-2"),
        ],
        heartbeat={"worker_id": "paper_management_loop"},
        redis_signal_payloads={
            "v2:signals:paper:BTCUSDT:1m": {"symbol": "BTCUSDT", "timeframe": "1m"},
            "v2:signals:paper:BTCUSDT:1h": {"symbol": "BTCUSDT", "timeframe": "1h"},
        },
        challenger_candidate_id="challenger-v2",
    )

    assert payload["routing_component_trace_status"] == "PASS_PAPER_ROUTING_COMPONENT_TRACE"
    assert payload["routing_component_trace"]["missing_or_incomplete_components"] == []
    assert payload["pass_conditions"]["routing_components_traced"] is True
    assert payload["status"] == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False


def test_routing_repair_contract_passes_clean_routing_trace(tmp_path) -> None:
    file_terms: dict[str, set[str]] = {}
    for component in PAPER_ROUTING_COMPONENTS:
        for file_name in component["files"]:
            file_terms.setdefault(str(file_name), set())
        first_file = str(component["files"][0])
        for term in component["required_terms"]:
            file_terms[first_file].add(str(term))
    for relative, terms in file_terms.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(terms)) + "\n", encoding="utf-8")

    routing = paper_timeframe_routing_owner_status(
        repo_root=tmp_path,
        closed_rows=[
            _closed_row(timeframe="1m", close_id="close-1"),
            _closed_row(timeframe="1h", close_id="close-2", entry_prediction_id="pred-2"),
        ],
        heartbeat={"worker_id": "paper_management_loop"},
        redis_signal_payloads={
            "v2:signals:paper:BTCUSDT:1m": {"symbol": "BTCUSDT", "timeframe": "1m"},
            "v2:signals:paper:BTCUSDT:1h": {"symbol": "BTCUSDT", "timeframe": "1h"},
        },
        challenger_candidate_id="challenger-v2",
    )
    payload = paper_timeframe_routing_repair_contract(routing=routing)

    assert routing["status"] == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    assert payload["status"] == "PASS_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT"
    assert payload["hardcoded_1m_path_count"] == 0
    assert payload["repair_steps"] == []
    assert all(payload["pass_conditions"].values())


def test_current_paper_runtime_has_no_hardcoded_1m_economic_paths() -> None:
    findings = [
        finding
        for finding in scan_hardcoded_timeframe_paths(REPO_ROOT)
        if finding["path"] == "v2/backend/app/cli/paper_online_runtime.py"
    ]

    assert findings == []


def test_1m_timing_preserves_1h_thesis() -> None:
    payload = multi_timeframe_thesis_execution_contract_status(
        closed_rows=[_contract_row(timeframe="1h", thesis_timeframe="1h", execution_timeframe="1m")],
        candidate_rows=[],
    )

    assert payload["status"] == "PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
    assert payload["higher_tf_1m_timing_rows"] == 1
    assert payload["pass_conditions"]["higher_tf_1m_timing_preserves_thesis"] is True
    assert payload["higher_tf_1m_timing_preserves_thesis"] is True


def test_thesis_execution_contract_publishes_missing_required_field_details() -> None:
    payload = multi_timeframe_thesis_execution_contract_status(
        closed_rows=[
            _contract_row(
                thesis_prediction_id=None,
                entry_prediction_id=None,
                execution_snapshot_id=None,
                entry_feature_snapshot_id=None,
            )
        ],
        candidate_rows=[],
    )

    assert payload["status"] == "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
    assert payload["missing_required_fields"] == [
        "execution_snapshot_id",
        "thesis_prediction_id",
    ]
    assert payload["missing_required_field_counts"] == {
        "execution_snapshot_id": 1,
        "thesis_prediction_id": 1,
    }
    assert payload["missing_required_field_count"] == 2
    assert payload["missing_required_row_total"] == 2
    assert payload["required_fields_present_for_all_rows"] is False
    assert payload["required_thesis_execution_fields_present"] is False
    assert payload["violations"] == payload["sample_violations"]
    assert payload["violation_samples"] == payload["sample_violations"]
    assert payload["sample_violation_rows"] == payload["sample_violations"]
    assert payload["violation_count"] == len(payload["sample_violations"])


def test_higher_tf_position_not_reopened_on_each_1m_tick() -> None:
    rows = [
        _contract_row(close_id="close-1", economic_trade_id="econ-1"),
        _contract_row(close_id="close-2", economic_trade_id="econ-2", thesis_prediction_id="thesis-pred-2"),
    ]

    payload = multi_timeframe_thesis_execution_contract_status(closed_rows=rows, candidate_rows=[])

    assert payload["status"] == "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
    assert payload["higher_tf_same_candle_reopen_rows"] == 1
    assert payload["pass_conditions"]["higher_tf_position_not_reopened_on_each_1m_tick"] is False
    assert payload["higher_tf_position_not_reopened_on_each_1m_tick"] is False
    assert "higher_tf_position_not_reopened_on_each_1m_tick" in payload["blocked_reasons"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]


def test_standalone_1m_requires_eligible_1m_strategy() -> None:
    payload = multi_timeframe_thesis_execution_contract_status(
        closed_rows=[
            _contract_row(
                timeframe="1m",
                thesis_timeframe="1m",
                execution_timeframe="1m",
                strategy_id="generic_momentum",
                strategy_bucket="generic",
            )
        ],
        candidate_rows=[],
    )

    assert payload["status"] == "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
    assert payload["standalone_1m_without_eligible_strategy_rows"] == 1
    assert payload["pass_conditions"]["standalone_1m_requires_eligible_1m_strategy"] is False
    assert payload["standalone_1m_requires_eligible_1m_strategy"] is False
    assert "standalone_1m_requires_eligible_1m_strategy" in payload["blocked_reasons"]
    assert payload["counts_as_a_grade_evidence"] is False


def test_close_outcome_attributed_to_thesis_timeframe() -> None:
    passing = multi_timeframe_thesis_execution_contract_status(
        closed_rows=[_contract_row(timeframe="1h", thesis_timeframe="1h", execution_timeframe="1m")],
        candidate_rows=[],
    )
    failing = multi_timeframe_thesis_execution_contract_status(
        closed_rows=[_contract_row(timeframe="1m", thesis_timeframe="1h", execution_timeframe="1m")],
        candidate_rows=[],
    )

    assert passing["pass_conditions"]["close_outcome_attributed_to_thesis_timeframe"] is True
    assert passing["close_outcome_attributed_to_thesis_timeframe"] is True
    assert failing["status"] == "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT"
    assert failing["close_outcome_thesis_timeframe_mismatch_rows"] == 1
    assert failing["close_outcome_attributed_to_thesis_timeframe"] is False


def test_same_prediction_cannot_open_twice() -> None:
    rows = [
        _contract_row(close_id="close-1", entry_prediction_id="pred-1"),
        _contract_row(close_id="close-2", entry_prediction_id="pred-1", thesis_prediction_id="thesis-pred-2"),
    ]

    payload = paper_reentry_and_signal_dedup_status(closed_rows=rows)

    assert payload["status"] == "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["same_prediction_duplicate_entries"] == 1
    assert payload["duplicate_economic_trades"] >= 1
    assert payload["decision_dedup_contract"]["blocked_duplicate_identity_fields"] == [
        "prediction_id",
        "decision_id",
        "signal_id",
        "feature_snapshot_id",
        "symbol_timeframe_candle_strategy_side",
    ]
    assert {
        detail["pass_condition"] for detail in payload["blocker_details"]
    } >= {"same_prediction_cannot_open_twice"}
    assert "same_prediction_cannot_open_twice" in payload["blocked_reasons"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["pass_conditions"]["same_prediction_cannot_open_twice"] is False
    assert payload["sample_duplicate_entries"] == payload["sample_duplicate_blocks"]
    assert payload["sample_duplicate_entry_blocks"] == payload["sample_duplicate_blocks"]
    assert payload["duplicate_entry_sample_count"] == len(payload["sample_duplicate_blocks"])
    assert payload["duplicate_entry_sample_count"] > 0
    assert payload["sample_duplicate_entries"][0]["violation"] == "duplicate_prediction_id"
    assert payload["sample_duplicate_entries"][0]["duplicate_key"] == "pred-1"
    assert payload["unexplained_reentry_sample_count"] == len(payload["sample_unexplained_reentries"])


def test_same_candle_same_thesis_cannot_reenter() -> None:
    rows = [
        _contract_row(close_id="close-1", entry_prediction_id="pred-1", entry_signal_id="sig-1"),
        _contract_row(close_id="close-2", entry_prediction_id="pred-2", entry_signal_id="sig-2"),
    ]

    payload = paper_reentry_and_signal_dedup_status(closed_rows=rows)

    assert payload["status"] == "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["same_candle_duplicate_entries"] == 1
    assert payload["pass_conditions"]["same_candle_same_thesis_cannot_reenter"] is False


def test_partial_close_does_not_authorize_reentry() -> None:
    rows = [
        _contract_row(close_id="close-1", entry_prediction_id="pred-1", entry_signal_id="sig-1", close_reason="partial_close"),
        _contract_row(close_id="close-2", entry_prediction_id="pred-2", entry_signal_id="sig-2", close_reason="full_close"),
    ]

    payload = paper_reentry_and_signal_dedup_status(closed_rows=rows)

    assert payload["status"] == "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["partial_close_reentry_count"] == 1
    assert payload["pass_conditions"]["partial_close_does_not_authorize_reentry"] is False


def test_new_thesis_candle_can_reenter() -> None:
    rows = [
        _contract_row(close_id="close-1", entry_prediction_id="pred-1", entry_signal_id="sig-1"),
        _contract_row(
            close_id="close-2",
            entry_prediction_id="pred-2",
            entry_signal_id="sig-2",
            entry_feature_snapshot_id="snap-2",
            feature_snapshot_id="snap-2",
            entry_feature_cutoff="2026-06-25T01:00:00Z",
            execution_snapshot_id="exec-snap-2",
        ),
    ]

    payload = paper_reentry_and_signal_dedup_status(closed_rows=rows)

    assert payload["status"] == "PASS_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["permitted_reentries_with_material_change"] == 1
    assert payload["unexplained_reentry_count"] == 0


def test_regime_change_can_reenter() -> None:
    rows = [
        _contract_row(close_id="close-1", entry_prediction_id="pred-1", entry_signal_id="sig-1", market_regime_at_entry="trend"),
        _contract_row(
            close_id="close-2",
            entry_prediction_id="pred-2",
            entry_signal_id="sig-2",
            entry_feature_snapshot_id="snap-2",
            feature_snapshot_id="snap-2",
            execution_snapshot_id="exec-snap-2",
            market_regime_at_entry="mean_revert",
        ),
    ]

    payload = paper_reentry_and_signal_dedup_status(closed_rows=rows)

    assert payload["status"] == "PASS_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["permitted_reentries_with_material_change"] == 1
    assert payload["same_candle_duplicate_entries"] == 0


def test_churn_governor_shadow_blocks_negative_expectancy_bucket() -> None:
    payload = evaluate_churn_governor(
        [
            _contract_row(symbol="BTCUSDT", realized_pnl_usd=-1.0, gross_pnl_usd=1.0),
            _contract_row(symbol="BTCUSDT", realized_pnl_usd=-2.0, gross_pnl_usd=2.0, entry_feature_cutoff="2026-06-25T01:00:00Z"),
        ]
    )

    assert payload["status"] == "BLOCKED_PAPER_CHURN_GOVERNOR_NOT_WIRED_TO_ENTRY_GATE"
    assert payload["evaluation_status"] == "PASS_PAPER_CHURN_GOVERNOR_EVALUATED"
    bucket = next(iter(payload["buckets"].values()))
    assert bucket["state"] == "CHURN_HALTED"
    assert "recent_after_cost_expectancy_lte_0" in bucket["block_reasons"]
    assert payload["runtime_wired_to_entry_gate"] is False


def test_churn_governor_entry_gate_blocks_negative_wired_bucket() -> None:
    rows = [
        _contract_row(symbol="BTCUSDT", realized_pnl_usd=-1.0, gross_pnl_usd=1.0),
        _contract_row(symbol="BTCUSDT", realized_pnl_usd=-2.0, gross_pnl_usd=2.0, entry_feature_cutoff="2026-06-25T01:00:00Z"),
    ]
    payload = evaluate_churn_governor(
        rows,
        runtime_wired_to_entry_gate=True,
    )
    gate = evaluate_churn_governor_entry_gate(
        rows,
        _contract_row(symbol="BTCUSDT", realized_pnl_usd=0.0, gross_pnl_usd=0.0),
    )

    assert payload["status"] == "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert gate["status"] == "BLOCKED_PAPER_CHURN_GOVERNOR_ENTRY_GATE"
    assert gate["allowed"] is False
    assert "bucket_state_not_active:CHURN_HALTED" in gate["reasons"]
    assert "recent_after_cost_expectancy_lte_0" in gate["reasons"]
    assert gate["routes_to_live"] is False


def test_churn_governor_trace_status_publishes_pass_conditions() -> None:
    governor = evaluate_churn_governor(
        [_contract_row(symbol="BTCUSDT", realized_pnl_usd=1.0)],
        runtime_wired_to_entry_gate=True,
    )
    wiring = {
        "status": "PASS_PAPER_CHURN_GOVERNOR_RUNTIME_WIRING",
        "runtime_wired_to_entry_gate": True,
        "source_order_passed": True,
        "missing_terms": [],
        "routes_to_live": False,
        "places_real_order": False,
    }

    payload = paper_churn_governor_trace_status(governor, wiring)

    assert payload["status"] == "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE"
    assert all(payload["pass_conditions"].values())
    assert payload["blocked_reasons"] == []
    assert payload["runtime_source_order_passed"] is True
    assert payload["counts_as_a_grade_evidence"] is False


def test_churn_governor_trace_status_blocks_without_source_order() -> None:
    governor = evaluate_churn_governor(
        [_contract_row(symbol="BTCUSDT", realized_pnl_usd=1.0)],
        runtime_wired_to_entry_gate=True,
    )
    wiring = {
        "status": "BLOCKED_PAPER_CHURN_GOVERNOR_RUNTIME_WIRING",
        "runtime_wired_to_entry_gate": False,
        "source_order_passed": False,
        "missing_terms": [],
        "routes_to_live": False,
        "places_real_order": False,
    }

    payload = paper_churn_governor_trace_status(governor, wiring)

    assert payload["status"] == "BLOCKED_PAPER_CHURN_GOVERNOR_RUNTIME_TRACE"
    assert payload["pass_conditions"]["runtime_wired_to_entry_gate"] is False
    assert payload["pass_conditions"]["runtime_source_order_passed"] is False
    assert payload["blocked_reasons"] == [
        "runtime_wired_to_entry_gate",
        "runtime_source_order_passed",
    ]
    assert payload["failed_blocker_details"] == payload["blocker_details"]


def test_churn_governor_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "churn_result = evaluate_churn_governor_entry_gate(",
                "_paper_churn_governor_runtime_rows()",
                "_paper_churn_governor_candidate_row(",
                'risk["paper_churn_governor"] = churn_result',
                'if not churn_result["allowed"]:',
                '_block("deny_paper_churn_governor", churn_result["reasons"], "paper_churn_governor")',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_churn_governor_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_PAPER_CHURN_GOVERNOR_RUNTIME_WIRING"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert [hit["term"] for hit in payload["ordered_gate_term_hits"]] == list(payload["ordered_gate_terms"])
    assert payload["routes_to_live"] is False


def test_paper_entry_cost_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "cost_result = _paper_entry_production_cost_gate(",
                'risk["paper_entry_production_cost_gate"] = cost_result',
                'if not cost_result["allowed"]:',
                '_block("deny_paper_entry_cost_gate", cost_result["blockers"], "paper_entry_production_cost_gate")',
                '"production_cost_evidence": {}',
                '"expected_net_edge_lower_bound_bps": 1.0',
                '"fallback_flag_false": True',
                '"edge_to_cost_ratio_below_contextual_safety_ratio"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_entry_cost_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_PAPER_ENTRY_COST_RUNTIME_WIRING"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert payload["places_real_order"] is False


def test_paper_entry_cost_runtime_wiring_blocks_unordered_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "cost_result = _paper_entry_production_cost_gate(",
                '_block("deny_paper_entry_cost_gate", cost_result["blockers"], "paper_entry_production_cost_gate")',
                'risk["paper_entry_production_cost_gate"] = cost_result',
                'if not cost_result["allowed"]:',
                '"production_cost_evidence": {}',
                '"expected_net_edge_lower_bound_bps": 1.0',
                '"fallback_flag_false": True',
                '"edge_to_cost_ratio_below_contextual_safety_ratio"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_entry_cost_runtime_wiring_status(tmp_path)

    assert payload["status"] == "BLOCKED_PAPER_ENTRY_COST_RUNTIME_WIRING"
    assert payload["missing_terms"] == []
    assert payload["source_order_passed"] is False
    assert payload["runtime_wired_to_entry_gate"] is False
    assert {
        detail["pass_condition"] for detail in payload["blocker_details"]
    } == {"gate_evaluation_risk_attachment_and_deny_block_ordered"}


def test_paper_reentry_dedup_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "dedup_result = _paper_reentry_dedup_gate(",
                "_paper_reentry_dedup_runtime_rows()",
                "_paper_reentry_dedup_candidate_row(",
                'risk["paper_reentry_dedup_gate"] = dedup_result',
                'if not dedup_result["allowed"]:',
                '_block("deny_paper_reentry_dedup", dedup_result["blockers"], "paper_reentry_dedup_gate")',
                "same_candle_same_thesis",
                "same_prediction_id",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_reentry_dedup_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_PAPER_REENTRY_DEDUP_RUNTIME_WIRING"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert payload["routes_to_live"] is False


def test_paper_standalone_1m_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/paper_online_runtime.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "one_minute_result = _paper_standalone_1m_eligibility_gate(",
                'risk["paper_standalone_1m_eligibility"] = one_minute_result',
                'if not one_minute_result["allowed"]:',
                '"deny_paper_standalone_1m_eligibility"',
                "standalone_1m_thesis_requires_dedicated_strategy_bucket",
                "higher_timeframe_timing_role_allowed",
                "dedicated_1m_strategy_bucket",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_standalone_1m_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_PAPER_STANDALONE_1M_RUNTIME_WIRING"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert payload["places_real_order"] is False


def test_active_paper_owner_standalone_1m_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/v2_trade_management_paper_loop.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "def _paper_standalone_1m_eligibility_gate():",
                "    return {'higher_timeframe_timing_role_allowed': True, 'dedicated_strategy_bucket': False}",
                "standalone_1m_thesis_requires_dedicated_strategy_bucket",
                "one_minute_result = _paper_standalone_1m_eligibility_gate(",
                'risk_decisions[-1]["paper_standalone_1m_eligibility"] = one_minute_result',
                "_apply_paper_standalone_1m_gate(intent, one_minute_result)",
                'if one_minute_result["allowed"]:',
                '    pass  # and one_minute_result["allowed"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_trade_management_standalone_1m_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_ACTIVE_PAPER_OWNER_STANDALONE_1M_RUNTIME_WIRING"
    assert payload["path"] == "v2/backend/app/cli/v2_trade_management_paper_loop.py"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert payload["routes_to_live"] is False


def test_active_paper_owner_reentry_dedup_runtime_wiring_status_reads_source_terms(tmp_path) -> None:
    runtime_path = tmp_path / "v2/backend/app/cli/v2_trade_management_paper_loop.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        "\n".join(
            [
                "PAPER_REENTRY_DEDUP_BLOCKED",
                "same_candle_same_thesis",
                "same_prediction_id",
                "def _paper_reentry_dedup_gate():",
                "    pass",
                "def _apply_paper_reentry_dedup_gate():",
                "    pass",
                "_paper_reentry_source_rows(existing_ledger)",
                "_paper_reentry_dedup_candidate_row(",
                "paper_reentry_dedup_gate",
                "reentry_dedup_result = _paper_reentry_dedup_gate(",
                'risk_decisions[-1]["paper_reentry_dedup_gate"] = reentry_dedup_result',
                "_apply_paper_reentry_dedup_gate(intent, reentry_dedup_result)",
                'if reentry_dedup_result["allowed"]:',
                '    pass  # and reentry_dedup_result["allowed"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = paper_trade_management_reentry_dedup_runtime_wiring_status(tmp_path)

    assert payload["status"] == "PASS_ACTIVE_PAPER_OWNER_REENTRY_DEDUP_RUNTIME_WIRING"
    assert payload["path"] == "v2/backend/app/cli/v2_trade_management_paper_loop.py"
    assert payload["runtime_wired_to_entry_gate"] is True
    assert payload["source_order_passed"] is True
    assert payload["places_real_order"] is False


def test_paper_entry_cost_coverage_requires_reserves_and_uncertainty() -> None:
    passing = paper_entry_cost_coverage_status(candidate_rows=[_production_grade_cost_row()])
    failing = paper_entry_cost_coverage_status(candidate_rows=[_contract_row()])

    assert passing["status"] == "PASS_PAPER_ENTRY_COST_COVERAGE"
    assert passing["production_grade_cost_coverage"] == 1.0
    assert passing["actuals"]["candidate_rows_gt_0"] == 1
    assert passing["actuals"]["production_grade_cost_coverage_gte_95pct"] == 1.0
    assert passing["sample_blockers"] == []
    assert failing["status"] == "BLOCKED_PAPER_ENTRY_COST_COVERAGE"
    assert failing["production_grade_cost_coverage"] == 0.0
    assert failing["required_coverage"] == 0.95
    assert failing["production_grade_cost_coverage_required"] == 0.95
    assert failing["production_grade_cost_coverage_shortfall_to_required"] == 0.95
    assert failing["rows_examined"] == 1
    assert failing["required_fields"] == failing["required_cost_fields"]
    assert failing["missing_field_counts"] == failing["missing_cost_field_counts"]
    assert failing["missing_required_fields"] == failing["missing_cost_fields"]
    assert failing["missing_required_field_counts"] == failing["missing_cost_field_counts"]
    assert failing["missing_required_field_count"] == len(failing["missing_cost_fields"])
    assert failing["missing_required_row_total"] == sum(failing["missing_cost_field_counts"].values())
    assert failing["present_required_field_counts"] == failing["present_cost_field_counts"]
    assert failing["field_coverage"] == failing["required_field_coverage"]
    assert failing["field_coverage"] == failing["cost_field_coverage"]
    assert failing["field_coverage"]["latency_reserve"] == {
        "present_rows": 0,
        "missing_rows": 1,
        "coverage": 0.0,
        "required_coverage": 0.95,
        "passes_required_coverage": False,
    }
    assert failing["field_coverage"]["observed_spread"]["coverage"] == 0.0
    assert failing["field_coverage"]["maker_taker_fee"]["coverage"] == 1.0
    assert failing["field_coverage"]["round_trip_cost"]["coverage"] == 1.0
    assert {
        field
        for field, coverage in failing["field_coverage"].items()
        if coverage["coverage"] == 0.0
    } == set(failing["missing_cost_fields"])
    assert failing["fallback_rows"] == 1
    assert failing["shadow_only_rows"] == 1
    assert failing["shadow_only_missing_cost_rows"] == 1
    assert {
        detail["pass_condition"] for detail in failing["blocker_details"]
    } >= {"production_grade_cost_coverage_gte_95pct", "missing_cost_fields_eq_0"}
    assert set(failing["blocked_reasons"]) >= {
        "production_grade_cost_coverage_gte_95pct",
        "missing_cost_fields_eq_0",
    }
    assert failing["failed_blocker_details"] == failing["blocker_details"]
    assert failing["actuals"]["candidate_rows_gt_0"] == 1
    assert failing["actuals"]["production_grade_cost_coverage_gte_95pct"] == 0.0
    assert failing["actuals"]["missing_cost_fields_eq_0"] == failing["missing_cost_field_counts"]
    assert failing["actuals"]["shadow_only_missing_cost_rows"] == 1
    assert failing["required"]["production_grade_cost_coverage_gte_95pct"] == ">=0.95"
    assert failing["required"]["missing_cost_fields_eq_0"] == {}
    assert failing["required"]["shadow_only_missing_cost_rows"] == 0
    assert failing["sample_blockers"] == failing["blocker_details"][:25]
    assert failing["counts_as_a_grade_evidence"] is False
    assert failing["missing_cost_field_counts"]["latency_reserve"] == 1
    assert failing["missing_cost_field_counts"]["cost_uncertainty"] == 1
    assert failing["missing_cost_row_samples"] == failing["sample_missing_cost_rows"]
    assert failing["sample_missing_required_cost_rows"] == failing["sample_missing_cost_rows"]
    assert failing["sample_required_cost_missing_rows"] == failing["sample_missing_cost_rows"]
    assert failing["sample_rows_missing_cost_fields"] == failing["sample_missing_cost_rows"]
    assert failing["sample_shadow_only_missing_cost_rows"] == failing["sample_missing_cost_rows"]
    assert set(failing["sample_rows_missing_cost_fields"][0]["missing_cost_fields"]) == set(failing["missing_cost_fields"])


def test_paper_edge_to_cost_gate_requires_positive_lower_bound_and_ratio() -> None:
    cost_coverage = paper_entry_cost_coverage_status(candidate_rows=[_production_grade_cost_row()])
    passing = paper_edge_to_cost_gate_status(
        candidate_rows=[_production_grade_cost_row()],
        cost_coverage=cost_coverage,
    )
    failing = paper_edge_to_cost_gate_status(
        candidate_rows=[
            _production_grade_cost_row(
                expected_gross_edge_bps=10.0,
                expected_net_edge_bps=0.5,
                round_trip_cost_bps=9.0,
                cost_uncertainty_bps=1.0,
            )
        ],
        cost_coverage=cost_coverage,
    )

    assert passing["status"] == "PASS_PAPER_EDGE_TO_COST_GATE"
    assert passing["admitted_candidate_rows"] == 1
    assert passing["admitted_candidate_count"] == 1
    assert passing["shadow_only_candidate_count"] == 0
    assert passing["production_grade_cost_coverage"] == 1.0
    assert passing["paper_entry_production_grade_cost_coverage"] == 1.0
    assert passing["actuals"]["admitted_candidate_rows"] == 1
    assert passing["actuals"]["shadow_only_candidate_rows"] == 0
    assert passing["sample_blockers"] == []
    assert failing["status"] == "BLOCKED_PAPER_EDGE_TO_COST_GATE"
    assert failing["admitted_candidate_rows"] == 0
    assert failing["admitted_candidate_count"] == 0
    assert failing["shadow_only_candidate_count"] == 1
    assert failing["production_grade_cost_coverage"] == 1.0
    assert failing["blocked_reason_counts"]["expected_net_edge_lower_bound_lte_0"] == 1
    assert failing["blocked_reason_counts"]["edge_to_cost_ratio_below_contextual_safety_ratio"] == 1
    assert failing["blocked_reasons"] == [
        "admitted_rows_have_positive_lower_bound",
        "admitted_rows_meet_contextual_safety_ratio",
    ]
    assert failing["sample_blocked_candidates"] == failing["sample_blocked_rows"]
    assert failing["sample_shadow_only_candidates"] == failing["sample_blocked_rows"]
    assert failing["sample_shadow_only_rows"] == failing["sample_blocked_rows"]
    assert failing["blocked_candidate_sample_count"] == 1
    assert failing["shadow_only_candidate_sample_count"] == 1
    assert failing["sample_blocked_candidates"][0]["blockers"] == [
        "expected_net_edge_lower_bound_lte_0",
        "edge_to_cost_ratio_below_contextual_safety_ratio",
    ]
    assert failing["failed_blocker_details"] == failing["blocker_details"]
    assert failing["actuals"]["admitted_rows_have_positive_lower_bound"] == 1
    assert failing["actuals"]["admitted_rows_meet_contextual_safety_ratio"] == 1
    assert failing["actuals"]["contextual_safety_ratio"] == governance_audit.EDGE_TO_COST_CONTEXTUAL_SAFETY_RATIO
    assert failing["required"]["admitted_rows_have_positive_lower_bound"] == 0
    assert failing["required"]["admitted_rows_meet_contextual_safety_ratio"] == 0
    assert failing["sample_blockers"] == failing["blocker_details"][:25]
    assert failing["counts_as_a_grade_evidence"] is False


def test_dynamic_timeframe_keeps_1m_timing_only_without_after_cost_governance() -> None:
    payload = dynamic_timeframe_execution_eligibility_status(
        economic_rows=[
            _contract_row(symbol="BTCUSDT", timeframe="1m", thesis_timeframe="1m", realized_pnl_usd=2.0),
            _contract_row(symbol="ETHUSDT", timeframe="1m", thesis_timeframe="1m", realized_pnl_usd=3.0),
        ],
        cost_coverage={"production_grade_cost_coverage": 0.0},
        edge_to_cost={"status": "BLOCKED_PAPER_EDGE_TO_COST_GATE"},
        min_economic_trades=2,
        min_symbols=2,
    )

    one_minute = payload["timeframe_states"]["1m"]
    assert payload["status"] == "BLOCKED_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY"
    assert payload["bucket_count"] == 1
    assert payload["bucket_state_counts"] == {"TIMING_ONLY": 1}
    assert payload["sample_bucket_statuses"][0]["timeframe"] == "1m"
    assert payload["sample_blocked_buckets"][0]["timeframe"] == "1m"
    assert payload["sample_shadow_only_buckets"][0]["timeframe"] == "1m"
    assert one_minute["state"] == "TIMING_ONLY"
    assert one_minute["standalone_execution_allowed"] is False
    assert one_minute["higher_timeframe_timing_role_allowed"] is True
    assert "production_grade_cost_coverage_below_95pct" in one_minute["block_reasons"]
    assert "paper_edge_to_cost_gate_not_passed" in one_minute["block_reasons"]
    assert "at_least_one_timeframe_active" in payload["blocked_reasons"]
    assert "production_grade_cost_coverage_gte_95pct" in payload["blocked_reasons"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["counts_as_a_grade_evidence"] is False


def test_dynamic_timeframe_allows_active_only_with_positive_after_cost_bucket() -> None:
    rows = [
        _contract_row(symbol="BTCUSDT", timeframe="1h", thesis_timeframe="1h", realized_pnl_usd=3.0),
        _contract_row(symbol="ETHUSDT", timeframe="1h", thesis_timeframe="1h", realized_pnl_usd=3.5),
        _contract_row(symbol="BTCUSDT", timeframe="1h", thesis_timeframe="1h", realized_pnl_usd=4.0),
        _contract_row(symbol="ETHUSDT", timeframe="1h", thesis_timeframe="1h", realized_pnl_usd=4.5),
    ]

    payload = dynamic_timeframe_execution_eligibility_status(
        economic_rows=rows,
        cost_coverage={"production_grade_cost_coverage": 1.0},
        edge_to_cost={"status": "PASS_PAPER_EDGE_TO_COST_GATE"},
        min_economic_trades=4,
        min_symbols=2,
    )

    one_hour = payload["timeframe_states"]["1h"]
    assert payload["status"] == "PASS_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY"
    assert one_hour["state"] == "ACTIVE"
    assert one_hour["standalone_execution_allowed"] is True
    assert one_hour["metrics"]["after_cost_expectancy_95_lower_bound_usd"] > 0.0
    assert one_hour["metrics"]["profit_factor"] == float("inf")
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == []


def test_timeframe_concentration_guard_flags_unproven_dominance() -> None:
    rows = [
        _contract_row(symbol="BTCUSDT", timeframe="4h", thesis_timeframe="4h", gross_notional_usd=100.0),
        _contract_row(symbol="ETHUSDT", timeframe="4h", thesis_timeframe="4h", gross_notional_usd=100.0),
        _contract_row(symbol="SOLUSDT", timeframe="4h", thesis_timeframe="4h", gross_notional_usd=100.0),
        _contract_row(symbol="BTCUSDT", timeframe="1h", thesis_timeframe="1h", gross_notional_usd=100.0),
    ]

    payload = timeframe_execution_concentration_guard_status(
        economic_rows=rows,
        eligibility={"timeframe_states": {"4h": {"state": "SHADOW_ONLY"}, "1h": {"state": "ACTIVE"}}},
        max_share=0.50,
    )

    assert payload["status"] == "BLOCKED_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD"
    assert payload["violation_count"] > 0
    assert payload["operator_concentration_envelope"] == {
        "max_share": 0.50,
        "dimensions": [
            "economic_trade_share_by_timeframe",
            "gross_notional_share_by_timeframe",
            "fee_share_by_timeframe",
            "absolute_net_pnl_share_by_timeframe",
        ],
        "no_unproven_concentration_required": True,
    }
    assert payload["trade_share_by_timeframe"] == payload["share_dimensions"]["economic_trade_share_by_timeframe"]
    assert payload["gross_notional_share_by_timeframe"] == payload["share_dimensions"]["gross_notional_share_by_timeframe"]
    assert payload["fee_share_by_timeframe"] == payload["share_dimensions"]["fee_share_by_timeframe"]
    assert payload["net_pnl_share_by_timeframe"] == payload["share_dimensions"]["absolute_net_pnl_share_by_timeframe"]
    assert payload["absolute_net_pnl_share_by_timeframe"] == payload["share_dimensions"]["absolute_net_pnl_share_by_timeframe"]
    assert any(
        violation["timeframe"] == "4h" and violation["unproven_concentration"] is True
        for violation in payload["violations"]
    )
    assert payload["sample_violations"] == payload["violations"][:25]
    assert payload["violation_samples"] == payload["sample_violations"]
    assert payload["concentration_violation_samples"] == payload["sample_violations"]
    assert "no_timeframe_dimension_exceeds_operator_envelope" in payload["blocked_reasons"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["counts_as_a_grade_evidence"] is False


def test_timeframe_concentration_guard_passes_balanced_evidence() -> None:
    rows = [
        _contract_row(symbol="BTCUSDT", timeframe="1h", thesis_timeframe="1h", gross_notional_usd=100.0, realized_pnl_usd=2.0),
        _contract_row(symbol="ETHUSDT", timeframe="4h", thesis_timeframe="4h", gross_notional_usd=100.0, realized_pnl_usd=2.0),
    ]

    payload = timeframe_execution_concentration_guard_status(
        economic_rows=rows,
        eligibility={"timeframe_states": {"1h": {"state": "ACTIVE"}, "4h": {"state": "ACTIVE"}}},
        max_share=0.50,
    )

    assert payload["status"] == "PASS_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD"
    assert payload["violation_count"] == 0
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == []


def test_post_fix_sample_counts_only_explicit_future_governance_outcomes() -> None:
    rows = [
        _closed_row(close_id="legacy-close", realized_pnl_usd=1.0),
        _post_fix_outcome_row(1),
        _post_fix_outcome_row(2, economic_trade_id=None),
    ]

    payload = post_fix_economic_outcome_sample(rows)

    assert payload["status"] == "POST_FIX_SAMPLE_READY"
    assert payload["raw_close_rows_examined"] == 3
    assert payload["eligible_raw_close_rows"] == 1
    assert payload["excluded_raw_close_rows"] == 2
    assert payload["compacted_economic_trade_count"] == 1
    assert payload["new_compacted_economic_paper_outcomes"] == 1
    assert payload["sample_started"] is True
    assert payload["required_identity_fields"] == [
        "economic_trade_id",
        "economic_thesis_id",
        "parent_position_id",
    ]
    assert payload["required_thesis_execution_fields"] == list(governance_audit.THESIS_EXECUTION_REQUIRED_FIELDS)
    assert "missing_explicit_economic_identity" in payload["exclusion_reason_counts"]
    assert "not_closed_paper_outcome" in payload["exclusion_reason_counts"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_post_fix_validation_uses_future_sample_count_for_100_outcome_gate() -> None:
    rows = [_post_fix_outcome_row(index) for index in range(100)]
    sample = post_fix_economic_outcome_sample(rows)
    churn = {
        "status": "CURRENT_PAPER_LEDGER_AUDITED",
        "raw_close_record_count": 100,
        "economic_trade_count": 100,
        "trade_count_by_timeframe": {"1m": 20, "5m": 20, "15m": 20, "1h": 20, "4h": 20},
        "economic_trade_count_by_timeframe": {"1m": 20, "5m": 20, "15m": 20, "1h": 20, "4h": 20},
        "current_1m_economic_trade_share": 0.20,
    }
    post_fix = post_fix_paper_validation_status(
        churn=churn,
        reconciliation={"status": "PASS_ECONOMIC_TRADE_RECONCILIATION"},
        compaction={"status": "PASS_ECONOMIC_TRADE_COMPACTION"},
        churn_governor={"status": "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE", "runtime_wired_to_entry_gate": True},
        cost_coverage={"status": "PASS_PAPER_ENTRY_COST_COVERAGE", "production_grade_cost_coverage": 0.96},
        edge_to_cost={"status": "PASS_PAPER_EDGE_TO_COST_GATE"},
        dynamic_timeframe_eligibility={
            "status": "PASS_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY",
            "active_timeframes": ["1m", "5m", "15m"],
        },
        concentration_guard={"status": "PASS_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD"},
        thesis_execution={
            "status": "PASS_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
            "standalone_1m_runtime_wired_to_entry_gate": True,
        },
        reentry_dedup={
            "status": "PASS_PAPER_REENTRY_AND_SIGNAL_DEDUP",
            "same_candle_duplicate_entries": 0,
            "duplicate_economic_trades": 0,
            "runtime_wired_to_entry_gate": True,
        },
        routing={"status": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"},
        post_fix_sample=sample,
    )

    assert sample["compacted_economic_trade_count"] == 100
    assert post_fix["pass_conditions"]["post_fix_100_new_compacted_economic_outcomes_collected"] is True
    assert post_fix["validation_actuals"]["post_fix_100_new_compacted_economic_outcomes_collected"] == 100
    assert post_fix["actuals"] == post_fix["validation_actuals"]
    assert post_fix["required"] == post_fix["validation_required"]
    assert post_fix["post_fix_sample_status"] == "POST_FIX_SAMPLE_READY"
    assert post_fix["post_fix_sample_started"] is True
    assert post_fix["post_fix_sample_eligible_raw_close_rows"] == 100
    assert post_fix["new_compacted_economic_paper_outcomes"] == 100
    assert post_fix["status"] == "PASS_POST_FIX_PAPER_VALIDATION"
    assert post_fix["final_gate"] == "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY"
    assert post_fix["blocked_reasons"] == []
    assert post_fix["paper_fill_allowed"] is False
    assert post_fix["routes_to_live"] is False
    assert post_fix["places_real_order"] is False
    assert post_fix["counts_as_a_grade_evidence"] is False
    assert post_fix["promotion_evidence"] is False


def test_post_fix_status_and_dashboard_remain_blocked_without_runtime_repair() -> None:
    rows = [
        _contract_row(timeframe="1m", thesis_timeframe="1m", realized_pnl_usd=1.0, economic_trade_id="econ-1"),
        _contract_row(
            timeframe="5m",
            thesis_timeframe="5m",
            realized_pnl_usd=1.0,
            entry_prediction_id="pred-2",
            entry_signal_id="sig-2",
            economic_trade_id="econ-2",
        ),
        _contract_row(
            timeframe="15m",
            thesis_timeframe="15m",
            realized_pnl_usd=1.0,
            entry_prediction_id="pred-3",
            entry_signal_id="sig-3",
            economic_trade_id="econ-3",
        ),
        _contract_row(
            timeframe="1h",
            thesis_timeframe="1h",
            realized_pnl_usd=1.0,
            entry_prediction_id="pred-4",
            entry_signal_id="sig-4",
            economic_trade_id="econ-4",
        ),
        _contract_row(
            timeframe="4h",
            thesis_timeframe="4h",
            realized_pnl_usd=1.0,
            entry_prediction_id="pred-5",
            entry_signal_id="sig-5",
            economic_trade_id="econ-5",
        ),
    ]
    churn = current_paper_timeframe_churn_audit(
        closed_rows=rows,
        ledger={"closed_trade_count": 5},
        portfolio_state={"closed_positions_count": 5},
        heartbeat={"closed_trade_count": 5},
        challenger_candidate_id="challenger-v2",
    )
    reconciliation = current_paper_economic_trade_reconciliation(
        closed_rows=rows,
        portfolio_state={"closed_ledger_net_pnl_usd": 5.0},
        ledger={},
    )
    compaction = economic_trade_compaction_status(closed_rows=rows, reconciliation=reconciliation)
    cost_coverage = paper_entry_cost_coverage_status(candidate_rows=[])
    edge_to_cost = paper_edge_to_cost_gate_status(candidate_rows=[], cost_coverage=cost_coverage)
    dynamic = dynamic_timeframe_execution_eligibility_status(
        economic_rows=rows,
        cost_coverage={"production_grade_cost_coverage": 0.0},
        edge_to_cost={"status": "BLOCKED_PAPER_EDGE_TO_COST_GATE"},
        min_economic_trades=1,
        min_symbols=1,
    )
    concentration = timeframe_execution_concentration_guard_status(
        economic_rows=rows,
        eligibility=dynamic,
        max_share=0.50,
    )
    thesis = multi_timeframe_thesis_execution_contract_status(closed_rows=rows, candidate_rows=[])
    reentry = paper_reentry_and_signal_dedup_status(closed_rows=rows)
    routing = {"status": "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"}
    churn_governor = {"status": "BLOCKED_PAPER_CHURN_GOVERNOR_NOT_WIRED_TO_ENTRY_GATE", "runtime_wired_to_entry_gate": False}

    post_fix = post_fix_paper_validation_status(
        churn=churn,
        reconciliation=reconciliation,
        compaction=compaction,
        churn_governor=churn_governor,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic,
        concentration_guard=concentration,
        thesis_execution=thesis,
        reentry_dedup=reentry,
        routing=routing,
    )
    dashboard = operator_dashboard_payload(
        churn=churn,
        reentry_dedup=reentry,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic,
        concentration_guard=concentration,
        thesis_execution=thesis,
        post_fix_validation=post_fix,
    )

    assert post_fix["status"] == "BLOCKED_POST_FIX_PAPER_VALIDATION"
    assert post_fix["final_gate"] == "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_BLOCKED"
    assert post_fix["post_fix_ready"] is False
    assert post_fix["source_statuses"]["post_fix_paper_validation_status"] == post_fix["status"]
    assert post_fix["source_statuses"]["paper_timeframe_routing_owner_status"] == routing["status"]
    assert post_fix["source_statuses"]["current_paper_economic_trade_reconciliation"] == reconciliation["status"]
    assert post_fix["blocker_summary"]["blocker_count"] == len(post_fix["blockers"])
    assert post_fix["blocked_reasons"] == post_fix["blockers"]
    assert post_fix["blocker_details"] == post_fix["blocker_summary"]["blocker_details"]
    assert post_fix["failed_blocker_details"] == post_fix["blocker_details"]
    assert post_fix["counts_as_a_grade_evidence"] is False
    assert post_fix["promotion_evidence"] is False
    assert post_fix["validation_actuals"]["runtime_routing_repair_applied"] == routing["status"]
    assert post_fix["actuals"] == post_fix["validation_actuals"]
    assert post_fix["validation_required"]["runtime_routing_repair_applied"] == "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT"
    assert post_fix["required"] == post_fix["validation_required"]
    assert post_fix["sample_excluded_rows"] == post_fix["post_fix_sample_sample_excluded_rows"]
    assert post_fix["excluded_row_samples"] == post_fix["post_fix_sample_sample_excluded_rows"]
    assert post_fix["post_fix_sample_excluded_row_samples"] == post_fix["post_fix_sample_sample_excluded_rows"]
    assert post_fix["duplicate_economic_trades"] == reentry["duplicate_economic_trades"]
    assert post_fix["unexplained_same_candle_reentries"] == reentry["same_candle_duplicate_entries"]
    assert post_fix["accounting_reconciliation_status"] == reconciliation["status"]
    assert post_fix["required_production_grade_cost_coverage"] == 0.95
    assert post_fix["edge_to_cost_gate_status"] == edge_to_cost["status"]
    assert {
        detail["pass_condition"]: detail["source_artifact"]
        for detail in post_fix["blocker_summary"]["blocker_details"]
    }["runtime_routing_repair_applied"] == "paper_timeframe_routing_owner_status"
    assert {
        detail["pass_condition"]: detail["actual"]
        for detail in post_fix["blocker_summary"]["blocker_details"]
    }["runtime_routing_repair_applied"] == routing["status"]
    assert {
        detail["pass_condition"]: detail["required"]
        for detail in post_fix["blocker_summary"]["blocker_details"]
    }["post_fix_100_new_compacted_economic_outcomes_collected"] == ">= 100"
    assert post_fix["pass_conditions"]["post_fix_100_new_compacted_economic_outcomes_collected"] is False
    assert post_fix["pass_conditions"]["runtime_routing_repair_applied"] is False
    phase_trace = paper_governance_phase_trace(
        churn=churn,
        reconciliation=reconciliation,
        compaction=compaction,
        routing=routing,
        routing_repair={"status": "BLOCKED_PAPER_TIMEFRAME_ROUTING_REPAIR_CONTRACT", "pass_conditions": {"hardcoded_1m_paths_absent": False}},
        thesis_execution=thesis,
        reentry_dedup=reentry,
        churn_governor=churn_governor,
        cost_coverage=cost_coverage,
        edge_to_cost=edge_to_cost,
        dynamic_timeframe_eligibility=dynamic,
        concentration_guard=concentration,
        post_fix_validation=post_fix,
    )
    assert phase_trace["phase_statuses"]["phase_10_post_fix_paper_validation"] == post_fix["status"]
    assert "runtime_routing_repair_applied" in phase_trace["phase_blockers"]["phase_10_post_fix_paper_validation"]
    assert phase_trace["phase_pass_conditions"]["phase_4_economic_trade_identity"]["raw_rows_have_explicit_economic_trade_id"] is True
    source_blocker_fields = paper_governance_summary_source_blocker_fields(
        post_fix_validation=post_fix,
        phase_trace=phase_trace,
    )
    assert source_blocker_fields["source_blocker_count"] == len(post_fix["blocked_reasons"])
    assert source_blocker_fields["source_blocked_pass_conditions"] == post_fix["blocked_reasons"]
    assert source_blocker_fields["source_blocker_details"] == post_fix["blocker_details"]
    assert source_blocker_fields["source_phase_blockers"] == phase_trace["phase_blockers"]
    assert source_blocker_fields["source_phase_blocker_count"] == sum(
        len(blockers) for blockers in phase_trace["phase_blockers"].values()
    )
    assert dashboard["raw_close_records"] == 5
    assert dashboard["raw_close_record_count"] == 5
    assert dashboard["compacted_economic_trades"] == 5
    assert dashboard["economic_trade_count"] == 5
    assert dashboard["cost_drag"] == churn["cost_as_pct_of_gross_by_timeframe"]
    assert dashboard["turnover"] == sum(churn["turnover_by_timeframe"].values())
    assert dashboard["one_min_status"] == dashboard["one_minute_status"]
    assert dashboard["thesis_timeframe"]["contract_status"] == thesis["status"]
    assert dashboard["execution_timeframe"]["contract_status"] == thesis["status"]
    assert dashboard["do_not_display_raw_close_count_as_independent_trades"] is True
    assert dashboard["paper_fill_allowed"] is False
    assert dashboard["routes_to_live"] is False
    assert dashboard["places_real_order"] is False
    assert dashboard["counts_as_a_grade_evidence"] is False
    assert dashboard["promotion_evidence"] is False
    assert dashboard["operator_dashboard_truth_contract_status"] == "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
    assert dashboard["website_truth_contract_status"] == "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
    assert dashboard["blocked_reasons"] == []
    assert dashboard["missing_required_fields"] == []
    assert dashboard["required_website_truth_fields"] == list(OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS)
    assert all(dashboard["pass_conditions"].values())
    dashboard_contract = operator_dashboard_truth_contract(dashboard)
    assert dashboard_contract["status"] == "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
    assert dashboard_contract["blocked_reasons"] == []
    assert dashboard_contract["missing_required_fields"] == []
    assert dashboard_contract["required_website_truth_fields"] == list(OPERATOR_DASHBOARD_WEBSITE_TRUTH_REQUIRED_FIELDS)
    assert all(dashboard_contract["pass_conditions"].values())

    summary = {
        **dashboard,
        "raw_close_record_count": dashboard["raw_close_record_count"],
        "economic_trade_count": dashboard["economic_trade_count"],
        "current_1m_share": churn["current_1m_share"],
        "current_1m_economic_trade_share": churn["current_1m_economic_trade_share"],
        "old_policy_trade_count": churn["old_policy_trade_count"],
        "challenger_trade_count": churn["challenger_trade_count"],
        "routing_status": routing["status"],
        "hardcoded_1m_path_count": 0,
        "silent_1m_fallback_path_count": 1,
        "timeframe_routing_violation_count": 1,
        "silent_1m_fallback_paths": [
            {
                "path": "v2/backend/app/cli/paper_online_runtime.py",
                "line": 181,
                "function": "_paper_thesis_timeframe",
                "reason": "unsafe_thesis_or_economic_timeframe_default_to_execution_1m",
                "text": "return PAPER_EXECUTION_TIMING_TIMEFRAME",
            }
        ],
        "paper_entry_production_grade_cost_coverage": cost_coverage["production_grade_cost_coverage"],
        "production_grade_cost_coverage": cost_coverage["production_grade_cost_coverage"],
        "multi_timeframe_thesis_execution_contract_status": thesis["status"],
        "paper_reentry_and_signal_dedup_status": reentry["status"],
        "phase_statuses": phase_trace["phase_statuses"],
        "phase_blockers": phase_trace["phase_blockers"],
        "post_fix_ready": post_fix["post_fix_ready"],
        "operator_dashboard_truth_contract_status": dashboard_contract["status"],
        "final_gate": post_fix["final_gate"],
        "blocked_reasons": post_fix["blocked_reasons"],
        **source_blocker_fields,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
    }
    summary_pass_conditions = paper_governance_summary_pass_conditions(summary)
    go_no_go = go_no_go_markdown(summary, post_fix)
    report = repair_report_markdown(summary, post_fix)

    assert summary_pass_conditions["required_artifacts_present"] is False
    assert summary_pass_conditions["current_ledger_recomputed"] is True
    assert summary_pass_conditions["challenger_remains_paper_inactive"] is True
    assert summary_pass_conditions["operator_dashboard_website_truth_contract_passed"] is True
    assert summary_pass_conditions["post_fix_ready"] is False
    assert summary_pass_conditions["final_gate_ready"] is False
    assert summary_pass_conditions["source_blockers_cleared"] is False
    assert summary_pass_conditions["source_phase_blockers_cleared"] is False
    assert summary_pass_conditions["paper_only_no_live_routes"] is True
    assert summary["production_grade_cost_coverage"] == summary["paper_entry_production_grade_cost_coverage"]
    assert "- Raw close records are not independent trades: true" in go_no_go
    assert "- 1m status:" in go_no_go
    assert "- Duplicate/reentry blocks:" in go_no_go
    assert "- Silent 1m fallback path count: 1" in go_no_go
    assert "- Timeframe routing violation count: 1" in go_no_go
    assert "- Phase statuses:" in go_no_go
    assert "- Cost drag by timeframe:" in report
    assert "- Silent 1m fallback paths:" in report
    assert "unsafe_thesis_or_economic_timeframe_default_to_execution_1m" in report
    assert "## Thesis And Execution" in report
    assert "- Phase blockers:" in report
    assert "- Edge-to-cost ratio:" in report
