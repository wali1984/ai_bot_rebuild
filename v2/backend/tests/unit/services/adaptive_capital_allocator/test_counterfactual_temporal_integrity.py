from __future__ import annotations

import pytest

from v2.backend.app.services.adaptive_capital_allocator.counterfactual import (
    _temporal_status,
    run_counterfactual_sweep,
)


def _temporal_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "decision_time": "2026-07-19T12:00:00Z",
        "available_at": "2026-07-19T11:59:00Z",
        "generated_at": "2026-07-19T11:58:00Z",
        "feature_cutoff": "2026-07-19T11:57:00Z",
        "entry_feature_candle_closed_confirmed": True,
    }
    row.update(overrides)
    return row


def _a_grade_temporal_row(**overrides: object) -> dict[str, object]:
    row = _temporal_row(
        symbol="BTCUSDT",
        timeframe="1m",
        side="long",
        confidence_calibrated=0.86,
        expected_move_after_cost_bps=25.0,
        allocator_decision="ALLOW_WITH_SIZE",
    )
    row.update(overrides)
    return row


def test_temporal_status_accepts_complete_causal_lineage() -> None:
    assert _temporal_status(_temporal_row()) == (True, [])


def test_temporal_status_prefers_entry_feature_clocks() -> None:
    row = _temporal_row(
        entry_feature_decision_time="2026-07-19T12:00:00Z",
        entry_feature_available_at="2026-07-19T11:59:00Z",
        entry_feature_generated_at="2026-07-19T11:58:00Z",
        entry_feature_cutoff="2026-07-19T11:57:00Z",
        available_at="2026-07-19T12:01:00Z",
        generated_at="not-a-time",
        feature_cutoff="2026-07-19T12:02:00Z",
    )

    assert _temporal_status(row) == (True, [])


def test_temporal_status_rejects_conflicting_decision_aliases() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(
            decision_time="2026-07-19T12:10:00Z",
            entry_feature_decision_time="2026-07-19T12:00:00Z",
            entry_feature_available_at="2026-07-19T12:05:00Z",
        )
    )

    assert valid is False
    assert "DECISION_TIME_ALIAS_CONFLICT" in reasons


def test_temporal_status_rejects_malformed_secondary_decision_alias() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(entry_feature_decision_time="not-a-time")
    )

    assert valid is False
    assert "INVALID_DECISION_TIME" in reasons


def test_temporal_status_does_not_fall_through_malformed_preferred_clock() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(entry_feature_available_at="not-a-time")
    )

    assert valid is False
    assert reasons == ["INVALID_AVAILABLE_AT"]


def test_temporal_status_does_not_fabricate_decision_time() -> None:
    row = _temporal_row(
        entry_price_utc="2026-07-19T12:00:00Z",
        generated_utc="2026-07-19T12:00:00Z",
    )
    row.pop("decision_time")

    valid, reasons = _temporal_status(row)

    assert valid is False
    assert "MISSING_DECISION_TIME" in reasons


@pytest.mark.parametrize(
    "field",
    ("decision_time", "available_at", "generated_at", "feature_cutoff"),
)
def test_temporal_status_rejects_timezone_naive_clocks(field: str) -> None:
    valid, reasons = _temporal_status(
        _temporal_row(**{field: "2026-07-19T11:59:00"})
    )

    assert valid is False
    assert f"INVALID_{field.upper()}" in reasons


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("available_at", "AVAILABLE_AT_AFTER_DECISION_TIME"),
        ("generated_at", "GENERATED_AT_AFTER_DECISION_TIME"),
        ("feature_cutoff", "FEATURE_CUTOFF_AFTER_DECISION_TIME"),
    ),
)
def test_temporal_status_rejects_clocks_after_decision(
    field: str,
    reason: str,
) -> None:
    valid, reasons = _temporal_status(
        _temporal_row(**{field: "2026-07-19T12:00:01Z"})
    )

    assert valid is False
    assert reason in reasons


def test_temporal_status_requires_cutoff_before_availability() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(feature_cutoff="2026-07-19T11:59:01Z")
    )

    assert valid is False
    assert "FEATURE_CUTOFF_AFTER_AVAILABLE_AT" in reasons


def test_temporal_status_requires_cutoff_before_generation() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(feature_cutoff="2026-07-19T11:58:01Z")
    )

    assert valid is False
    assert "FEATURE_CUTOFF_AFTER_GENERATED_AT" in reasons


def test_temporal_status_requires_generation_before_availability() -> None:
    valid, reasons = _temporal_status(
        _temporal_row(
            generated_at="2026-07-19T11:59:01Z",
            available_at="2026-07-19T11:59:00Z",
        )
    )

    assert valid is False
    assert "GENERATED_AT_AFTER_AVAILABLE_AT" in reasons


def test_temporal_status_accepts_inclusive_causal_boundaries() -> None:
    assert _temporal_status(
        _temporal_row(
            entry_feature_decision_time="2026-07-19T12:00:00+00:00",
            feature_cutoff="2026-07-19T11:59:00Z",
            generated_at="2026-07-19T11:59:00Z",
            available_at="2026-07-19T11:59:00Z",
        )
    ) == (True, [])


@pytest.mark.parametrize(
    ("value", "reason"),
    (
        (None, "MISSING_CANDLE_FINALITY"),
        (False, "UNFINISHED_CANDLE"),
        ("true", "INVALID_CANDLE_FINALITY"),
    ),
)
def test_temporal_status_requires_explicit_true_candle_finality(
    value: object,
    reason: str,
) -> None:
    row = _temporal_row()
    if value is None:
        row.pop("entry_feature_candle_closed_confirmed")
    else:
        row["entry_feature_candle_closed_confirmed"] = value

    valid, reasons = _temporal_status(row)

    assert valid is False
    assert reason in reasons


def test_temporal_status_distinguishes_null_from_absent_finality() -> None:
    null_valid, null_reasons = _temporal_status(
        _temporal_row(entry_feature_candle_closed_confirmed=None)
    )
    absent = _temporal_row()
    absent.pop("entry_feature_candle_closed_confirmed")
    absent_valid, absent_reasons = _temporal_status(absent)

    assert null_valid is False
    assert null_reasons == ["INVALID_CANDLE_FINALITY"]
    assert absent_valid is False
    assert absent_reasons == ["MISSING_CANDLE_FINALITY"]


def test_counterfactual_sweep_surfaces_generated_after_available_rejection() -> None:
    sweep = run_counterfactual_sweep(
        [
            _a_grade_temporal_row(
                generated_at="2026-07-19T11:59:01Z",
                available_at="2026-07-19T11:59:00Z",
            )
        ]
    )

    assert sweep["event_time_valid_candidate_count"] == 0
    assert sweep["skipped_temporal_invalid_count"] == 1
    assert "GENERATED_AT_AFTER_AVAILABLE_AT" in sweep[
        "skipped_temporal_invalid_sample"
    ][0]["reasons"]


@pytest.mark.parametrize(
    ("finality", "reason"),
    (
        (None, "MISSING_CANDLE_FINALITY"),
        (False, "UNFINISHED_CANDLE"),
        ("true", "INVALID_CANDLE_FINALITY"),
    ),
)
def test_counterfactual_sweep_surfaces_candle_finality_rejection(
    finality: object,
    reason: str,
) -> None:
    row = _a_grade_temporal_row()
    if finality is None:
        row.pop("entry_feature_candle_closed_confirmed")
    else:
        row["entry_feature_candle_closed_confirmed"] = finality

    sweep = run_counterfactual_sweep([row])

    assert sweep["event_time_valid_candidate_count"] == 0
    assert sweep["skipped_temporal_invalid_count"] == 1
    assert reason in sweep["skipped_temporal_invalid_sample"][0]["reasons"]
