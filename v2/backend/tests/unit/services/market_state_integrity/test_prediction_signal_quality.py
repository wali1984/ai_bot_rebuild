"""Tests for prediction_signal_quality_auditor.

Covers:
  - validate_pit_safety: CLEAN, FUTURE_LEAKAGE, BACKFILLED, MISSING_DECISION_CUTOFF
  - compute_actionability: all reason codes
  - audit_prediction_row: stale exclusion, PIT exclusion, actionable inclusion
  - build_quality_status: counts, grid, overall status
  - Point-in-time boundary: available_at == decision_cutoff_time is CLEAN (not leakage)
  - feature_cutoff derived from market_state_reject_reasons propagation
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from v2.backend.app.services.prediction_signal_quality_auditor import (
    CURRENT_PREDICTION_STATUSES,
    DEFAULT_CONFIDENCE_FLOOR,
    audit_prediction_row,
    build_quality_status,
    compute_actionability,
    summarize_feature_coverage,
    validate_pit_safety,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_iso(seconds: int = 60) -> str:
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    return past.strftime("%Y-%m-%dT%H:%M:%SZ")


def _future_iso(seconds: int = 60) -> str:
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)
    return future.strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_current_row(**overrides: Any) -> dict[str, Any]:
    """Minimal valid current prediction row."""
    row: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "freshness_seconds": 30,
        "selected_action": "long",
        "confidence_calibrated": 0.72,
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        "prediction_id": "pred-test-001",
        "data_coverage_percent": 96.0,
        "missing_feature_count": 2,
        "stale_feature_count": 0,
        "missing_feature_names": ["surf_score", "moralis_whale_net_flow_usd"],
        "stale_feature_names": [],
        "valid_for_prediction": True,
        "valid_for_paper": True,
        "market_state_integrity_score": 87.5,
        "market_state_reject_reasons": [],
        "decision_cutoff_time_est": _past_iso(30),
        "market_state_source_lineage": {
            "source_event_time_est": _past_iso(60),
            "source_received_time_est": _past_iso(55),
            "decision_cutoff_time_est": _past_iso(30),
        },
        "source_lineage": {
            "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        },
        "paper_fill_allowed": True,
        "paper_fill_gate_block_reasons": [],
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# validate_pit_safety
# ---------------------------------------------------------------------------


class TestValidatePitSafety:
    def test_clean_when_source_event_before_decision_cutoff(self) -> None:
        row = _base_current_row()
        result = validate_pit_safety(row)
        assert result["status"] == "CLEAN"
        assert result["violations"] == []
        assert "decision_cutoff_time_est" in result["fields"]

    def test_clean_when_source_event_equals_decision_cutoff(self) -> None:
        ts = _past_iso(60)
        row = _base_current_row(
            decision_cutoff_time_est=ts,
            market_state_source_lineage={
                "source_event_time_est": ts,
                "decision_cutoff_time_est": ts,
            },
        )
        result = validate_pit_safety(row)
        assert result["status"] == "CLEAN"

    def test_future_leakage_from_reject_reason_token(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"],
        )
        result = validate_pit_safety(row)
        assert result["status"] == "FUTURE_LEAKAGE"
        assert "feature_timestamp_after_decision_cutoff" in result["violations"]

    def test_future_leakage_from_source_available_after_cutoff(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["source_available_after_decision_cutoff"],
        )
        result = validate_pit_safety(row)
        assert result["status"] == "FUTURE_LEAKAGE"
        assert "source_available_after_decision_cutoff" in result["violations"]

    def test_future_leakage_detected_by_independent_timestamp_check(self) -> None:
        """Audit detects leakage even when market_state_reject_reasons is empty."""
        decision = _past_iso(60)
        source_event_in_future = _future_iso(5)
        row = _base_current_row(
            market_state_reject_reasons=[],
            decision_cutoff_time_est=decision,
            market_state_source_lineage={
                "source_event_time_est": source_event_in_future,
                "decision_cutoff_time_est": decision,
            },
        )
        result = validate_pit_safety(row)
        assert result["status"] == "FUTURE_LEAKAGE"
        assert "feature_timestamp_after_decision_cutoff" in result["violations"]

    def test_backfilled_flag_triggers_backfilled_status(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"],
        )
        result = validate_pit_safety(row)
        assert result["status"] == "BACKFILLED"
        assert "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME" in result["violations"]

    def test_missing_decision_cutoff_when_no_timestamp_available(self) -> None:
        row = _base_current_row(
            decision_cutoff_time_est=None,
            market_state_reject_reasons=[],
            market_state_source_lineage={},
            source_lineage={},
        )
        result = validate_pit_safety(row)
        assert result["status"] == "MISSING_DECISION_CUTOFF"

    def test_fields_always_present_in_result(self) -> None:
        row = _base_current_row()
        result = validate_pit_safety(row)
        assert "decision_cutoff_time_est" in result["fields"]
        assert "source_event_time_est" in result["fields"]
        assert "source_available_at_decision_time" in result["fields"]

    def test_source_available_after_cutoff_detected_by_timestamp(self) -> None:
        decision = _past_iso(60)
        available_later = _future_iso(10)
        row = _base_current_row(
            market_state_reject_reasons=[],
            decision_cutoff_time_est=decision,
            market_state_source_lineage={
                "source_event_time_est": _past_iso(90),
                "source_available_at_decision_time": available_later,
                "decision_cutoff_time_est": decision,
            },
        )
        result = validate_pit_safety(row)
        assert result["status"] == "FUTURE_LEAKAGE"
        assert "source_available_after_decision_cutoff" in result["violations"]

    def test_explanation_present_for_all_statuses(self) -> None:
        cases = [
            _base_current_row(),
            _base_current_row(market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"]),
            _base_current_row(market_state_reject_reasons=["BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"]),
            _base_current_row(
                decision_cutoff_time_est=None,
                market_state_source_lineage={},
                source_lineage={},
                market_state_reject_reasons=[],
            ),
        ]
        for row in cases:
            result = validate_pit_safety(row)
            assert isinstance(result["explanation"], str) and result["explanation"]


# ---------------------------------------------------------------------------
# compute_actionability
# ---------------------------------------------------------------------------


class TestComputeActionability:
    def test_actionable_long(self) -> None:
        row = _base_current_row(selected_action="long", confidence_calibrated=0.75)
        result = compute_actionability(row)
        assert result["actionable"] is True
        assert result["reason_code"] == "actionable"

    def test_actionable_short(self) -> None:
        row = _base_current_row(selected_action="short", confidence_calibrated=0.80)
        result = compute_actionability(row)
        assert result["actionable"] is True
        assert result["reason_code"] == "actionable"

    def test_non_directional_hold(self) -> None:
        row = _base_current_row(selected_action="hold")
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "non_directional_action"

    def test_below_confidence_floor(self) -> None:
        row = _base_current_row(
            selected_action="long",
            confidence_calibrated=DEFAULT_CONFIDENCE_FLOOR - 0.01,
        )
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "below_confidence_floor"

    def test_exactly_at_confidence_floor_is_actionable(self) -> None:
        row = _base_current_row(
            selected_action="long",
            confidence_calibrated=DEFAULT_CONFIDENCE_FLOOR,
        )
        result = compute_actionability(row)
        assert result["actionable"] is True

    def test_missing_confidence(self) -> None:
        row = _base_current_row(selected_action="long", confidence_calibrated=None)
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "confidence_missing"

    def test_prediction_not_current(self) -> None:
        row = _base_current_row(status="STALE_TF_PREDICTION")
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "prediction_not_current"

    def test_market_state_invalid_for_prediction(self) -> None:
        row = _base_current_row(
            selected_action="long",
            confidence_calibrated=0.75,
            valid_for_prediction=False,
        )
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "market_state_invalid_for_prediction"

    def test_market_state_invalid_for_paper(self) -> None:
        row = _base_current_row(
            selected_action="long",
            confidence_calibrated=0.75,
            valid_for_prediction=True,
            valid_for_paper=False,
        )
        result = compute_actionability(row)
        assert result["actionable"] is False
        assert result["reason_code"] == "market_state_invalid_for_paper"

    def test_explanation_always_present(self) -> None:
        row = _base_current_row(selected_action="hold")
        result = compute_actionability(row)
        assert isinstance(result["explanation"], str) and result["explanation"]


# ---------------------------------------------------------------------------
# audit_prediction_row
# ---------------------------------------------------------------------------


class TestAuditPredictionRow:
    def test_stale_prediction_excluded(self) -> None:
        row = _base_current_row(freshness_seconds=901)
        result = audit_prediction_row(row, stale_seconds=900)
        assert result["is_fresh"] is False
        assert result["excluded_from_paper_candidates"] is True
        assert any("NOT_FRESH" in r for r in result["exclusion_reasons"])

    def test_current_clean_actionable_row_not_excluded(self) -> None:
        row = _base_current_row()
        result = audit_prediction_row(row)
        assert result["is_fresh"] is True
        assert result["pit_safety"]["status"] == "CLEAN"
        assert result["excluded_from_paper_candidates"] is False

    def test_pit_violation_excludes_row(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"],
        )
        result = audit_prediction_row(row)
        assert result["excluded_from_paper_candidates"] is True
        assert any("PIT_VIOLATION" in r for r in result["exclusion_reasons"])

    def test_backfilled_row_excluded(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"],
        )
        result = audit_prediction_row(row)
        assert result["excluded_from_paper_candidates"] is True
        assert any("PIT_VIOLATION" in r for r in result["exclusion_reasons"])

    def test_missing_prediction_status_excluded(self) -> None:
        row = _base_current_row(status="MISSING_TF_PREDICTION", freshness_seconds=None)
        result = audit_prediction_row(row)
        assert result["excluded_from_paper_candidates"] is True

    def test_stale_threshold_boundary(self) -> None:
        row_at_boundary = _base_current_row(freshness_seconds=900)
        result = audit_prediction_row(row_at_boundary, stale_seconds=900)
        assert result["is_fresh"] is True

        row_just_over = _base_current_row(freshness_seconds=901)
        result2 = audit_prediction_row(row_just_over, stale_seconds=900)
        assert result2["is_fresh"] is False

    def test_all_required_operator_fields_present(self) -> None:
        row = _base_current_row()
        result = audit_prediction_row(row)
        for field in (
            "symbol", "timeframe", "prediction_id", "prediction_status",
            "freshness_seconds", "is_fresh", "freshness_explanation",
            "pit_safety", "actionability", "feature_coverage",
            "excluded_from_paper_candidates", "exclusion_reasons",
            "operator_explanation",
        ):
            assert field in result, f"Missing field: {field}"

    def test_operator_explanation_is_non_empty_string(self) -> None:
        row = _base_current_row()
        result = audit_prediction_row(row)
        assert isinstance(result["operator_explanation"], str)
        assert len(result["operator_explanation"]) > 30

    def test_hold_action_is_not_excluded_by_audit(self) -> None:
        row = _base_current_row(selected_action="hold")
        result = audit_prediction_row(row)
        # hold is non-directional but not itself an exclusion cause
        assert result["excluded_from_paper_candidates"] is False
        assert result["actionability"]["actionable"] is False
        assert result["actionability"]["reason_code"] == "non_directional_action"

    def test_missing_confidence_does_not_exclude_row(self) -> None:
        row = _base_current_row(selected_action="long", confidence_calibrated=None)
        result = audit_prediction_row(row)
        # Missing confidence makes it non-actionable but doesn't exclude from paper grid
        assert result["excluded_from_paper_candidates"] is False
        assert result["actionability"]["actionable"] is False

    def test_stale_row_retains_pit_audit_result(self) -> None:
        """A stale row that is also PIT-clean should show CLEAN PIT status."""
        row = _base_current_row(freshness_seconds=2000)
        result = audit_prediction_row(row, stale_seconds=900)
        assert result["is_fresh"] is False
        assert result["pit_safety"]["status"] == "CLEAN"


# ---------------------------------------------------------------------------
# build_quality_status
# ---------------------------------------------------------------------------


class TestBuildQualityStatus:
    _TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
    _SYMBOLS = ["BTCUSDT", "ETHUSDT"]

    def _make_rows(self, **overrides: Any) -> list[dict[str, Any]]:
        rows = []
        for symbol in self._SYMBOLS:
            for tf in self._TIMEFRAMES:
                row = _base_current_row(symbol=symbol, timeframe=tf, **overrides)
                rows.append(row)
        return rows

    def test_all_clean_rows_produce_quality_pass(self) -> None:
        rows = self._make_rows()
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        assert result["pit_violation_count"] == 0
        assert result["status"] == "PREDICTION_GRID_QUALITY_PASS"
        assert result["prediction_grid_count_actual"] == 10

    def test_pit_violations_produce_blocked_status(self) -> None:
        rows = self._make_rows(
            market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"],
        )
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        assert result["status"] == "BLOCKED_PIT_VIOLATIONS_DETECTED"
        assert result["pit_violation_count"] == 10

    def test_stale_rows_excluded_and_counted(self) -> None:
        rows = self._make_rows(freshness_seconds=9999)
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
            stale_seconds=900,
        )
        assert result["stale_count"] == 10
        assert result["excluded_from_paper_count"] == 10
        assert result["paper_candidate_count"] == 0

    def test_symbol_grid_has_all_symbols(self) -> None:
        rows = self._make_rows()
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        for symbol in self._SYMBOLS:
            assert symbol in result["symbol_grid"]

    def test_symbol_grid_missing_timeframe_shows_missing(self) -> None:
        only_1m_rows = [
            _base_current_row(symbol="BTCUSDT", timeframe="1m"),
        ]
        result = build_quality_status(
            only_1m_rows,
            symbols=["BTCUSDT"],
            timeframes=self._TIMEFRAMES,
        )
        btc_grid = result["symbol_grid"]["BTCUSDT"]
        assert "5m" in btc_grid["missing_timeframes"]
        assert btc_grid["timeframe_states"]["1m"] in {"ACTIONABLE", "CURRENT_NON_ACTIONABLE", "EXCLUDED"}

    def test_empty_rows_returns_no_prediction_rows_status(self) -> None:
        result = build_quality_status(
            [],
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        assert result["status"] == "NO_PREDICTION_ROWS"

    def test_partial_grid_produces_incomplete_status(self) -> None:
        rows = [_base_current_row(symbol="BTCUSDT", timeframe="1m")]
        result = build_quality_status(
            rows,
            symbols=["BTCUSDT", "ETHUSDT"],
            timeframes=self._TIMEFRAMES,
        )
        assert result["status"] == "INCOMPLETE_PREDICTION_GRID"

    def test_required_top_level_fields_present(self) -> None:
        rows = self._make_rows()
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        for field in (
            "schema_version", "service_id", "generated_at", "live_gate",
            "symbols_covered", "timeframes_covered",
            "prediction_grid_count_expected", "prediction_grid_count_actual",
            "fresh_count", "stale_count", "pit_clean_count", "pit_violation_count",
            "pit_violations", "paper_candidate_count", "excluded_from_paper_count",
            "actionable_candidate_count", "status", "symbol_grid", "audit_rows",
        ):
            assert field in result, f"Missing top-level field: {field}"

    def test_live_gate_always_blocked(self) -> None:
        rows = self._make_rows()
        result = build_quality_status(
            rows,
            symbols=self._SYMBOLS,
            timeframes=self._TIMEFRAMES,
        )
        assert result["live_gate"] == "blocked_human_only"


# ---------------------------------------------------------------------------
# feature coverage
# ---------------------------------------------------------------------------


class TestSummarizeFeatureCoverage:
    def test_high_coverage(self) -> None:
        row = _base_current_row(data_coverage_percent=97.0)
        result = summarize_feature_coverage(row)
        assert result["coverage_status"] == "HIGH"

    def test_partial_coverage(self) -> None:
        row = _base_current_row(data_coverage_percent=80.0)
        result = summarize_feature_coverage(row)
        assert result["coverage_status"] == "PARTIAL"

    def test_low_coverage(self) -> None:
        row = _base_current_row(data_coverage_percent=40.0)
        result = summarize_feature_coverage(row)
        assert result["coverage_status"] == "LOW"

    def test_unknown_when_no_coverage_percent(self) -> None:
        row = _base_current_row(data_coverage_percent=None)
        result = summarize_feature_coverage(row)
        assert result["coverage_status"] == "UNKNOWN"

    def test_missing_critical_family_detected_from_reject_reasons(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["MISSING_CRITICAL_FEATURE_FAMILY"],
        )
        result = summarize_feature_coverage(row)
        assert result["missing_critical_feature_family"] is True

    def test_optional_missing_does_not_flag_critical(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=[],
            missing_feature_names=["surf_score", "moralis_whale_net_flow_usd"],
        )
        result = summarize_feature_coverage(row)
        assert result["missing_critical_feature_family"] is False


# ---------------------------------------------------------------------------
# PIT leakage with feature_cutoff terminology
# ---------------------------------------------------------------------------


class TestFeatureCutoffTerminology:
    """Verify that 'feature_cutoff' style fields are also covered.

    The publisher may embed candle_close_time and feature_cutoff in the
    source lineage.  The audit should not independently re-derive those
    (the scorer already validated them), but the audit fields map must
    expose decision_cutoff_time_est for operator review.
    """

    def test_decision_cutoff_field_is_reported_in_pit_safety(self) -> None:
        ts = _past_iso(120)
        row = _base_current_row(
            decision_cutoff_time_est=ts,
            market_state_source_lineage={
                "decision_cutoff_time_est": ts,
                "source_event_time_est": _past_iso(180),
            },
        )
        result = validate_pit_safety(row)
        assert result["fields"]["decision_cutoff_time_est"] == ts

    def test_missing_source_event_time_does_not_cause_false_leakage(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=[],
            market_state_source_lineage={
                "decision_cutoff_time_est": _past_iso(60),
                "source_event_time_est": None,
            },
        )
        result = validate_pit_safety(row)
        # No event time to compare → no leakage detected, not CLEAN either
        # (decision_cutoff is present, so not MISSING_DECISION_CUTOFF)
        assert result["status"] == "CLEAN"
        assert result["violations"] == []

    def test_future_feature_cutoff_detected_via_reject_reason(self) -> None:
        """A future feature_cutoff surfaces as feature_timestamp_after_decision_cutoff."""
        row = _base_current_row(
            market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"],
        )
        result = validate_pit_safety(row)
        assert result["status"] == "FUTURE_LEAKAGE"
        assert result["violations"] == ["feature_timestamp_after_decision_cutoff"]

    def test_audit_row_excludes_future_feature_cutoff(self) -> None:
        row = _base_current_row(
            market_state_reject_reasons=["feature_timestamp_after_decision_cutoff"],
        )
        audit = audit_prediction_row(row)
        assert audit["excluded_from_paper_candidates"] is True
        assert audit["pit_safety"]["status"] == "FUTURE_LEAKAGE"


class TestMissingTfPredictionPitBehavior:
    """MISSING_TF_PREDICTION rows must not be classified as PIT violations.

    Absence of a prediction is not a safety violation — it is missing data.
    The PIT audit only applies to rows that exist and could contain future-leaking
    features. Rows with no prediction (build_blocker_row output) must receive
    pit_safety.status == CLEAN so they are not counted in pit_violation_count.
    """

    def _missing_row(self) -> dict:
        return {
            "symbol": "AGTUSDT",
            "timeframe": "1m",
            "status": "MISSING_TF_PREDICTION",
            "freshness_seconds": None,
            "selected_action": None,
            "confidence_calibrated": None,
            "decision_cutoff_time_est": None,
            "market_state_reject_reasons": [],
            "market_state_source_lineage": {},
        }

    def test_missing_prediction_pit_status_is_clean(self) -> None:
        row = self._missing_row()
        audit = audit_prediction_row(row)
        assert audit["pit_safety"]["status"] == "CLEAN", (
            "MISSING_TF_PREDICTION must not be classified as MISSING_DECISION_CUTOFF "
            "— absence of prediction is not a PIT violation"
        )

    def test_missing_prediction_not_in_pit_violations_list(self) -> None:
        """build_quality_status must not count MISSING_TF_PREDICTION in pit_violation_count."""
        missing_row = self._missing_row()
        quality = build_quality_status(
            [missing_row],
            symbols=["AGTUSDT"],
            timeframes=("1m",),
            stale_seconds=900,
        )
        assert quality["pit_violation_count"] == 0, (
            "pit_violation_count must be 0 when only row is MISSING_TF_PREDICTION"
        )
        assert quality["status"] != "BLOCKED_PIT_VIOLATIONS_DETECTED"

    def test_missing_prediction_excluded_but_not_by_pit(self) -> None:
        row = self._missing_row()
        audit = audit_prediction_row(row)
        assert audit["excluded_from_paper_candidates"] is True
        # Exclusion reason is NOT_FRESH, not PIT_VIOLATION
        assert not any("PIT_VIOLATION" in r for r in audit["exclusion_reasons"]), (
            "MISSING_TF_PREDICTION exclusion reason must be NOT_FRESH, not PIT_VIOLATION"
        )
        assert any("NOT_FRESH" in r for r in audit["exclusion_reasons"])
