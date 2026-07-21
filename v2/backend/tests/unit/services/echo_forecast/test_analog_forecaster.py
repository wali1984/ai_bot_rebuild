"""Tests for the Echo analog (k-NN) forecaster.

Validates analogue projection mechanics, distribution diagnostics, strict PIT
lineage, insufficient-data handling, and robustness to bad input.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.services.echo_forecast import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_INVALID_INPUT,
    STATUS_OK,
    AnalogForecast,
    PITAnalogCandidate,
    PITAnalogForecast,
    PITCurrentWindow,
    compute_analog_forecast,
    compute_feature_schema_sha256,
    compute_outcome_schema_sha256,
    compute_pit_safe_analog_forecast,
)


def _hist(pattern, fwd, n=12, jitter=1e-6):
    """Build distinct near-copies so independent analogues are not duplicates."""
    rows, fwds = [], []
    for i in range(n):
        centered = i - ((n - 1) / 2.0)
        rows.append([p + (centered * jitter * (column + 1)) for column, p in enumerate(pattern)])
        fwds.append(fwd)
    return rows, fwds


def test_identical_pattern_projects_its_forward_return() -> None:
    # Distinct historical analogues very near current all moved +80 bps.
    cur = [1.0, 2.0, 3.0]
    rows, fwds = _hist(cur, 80.0, n=30)  # >= default k=25 so count_term reaches 1.0
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert not f.insufficient_data
    assert f.direction == "long"
    assert abs(f.expected_move_bps - 80.0) < 1e-6
    assert f.dispersion_bps < 1e-6
    assert f.neighbor_direction_agreement == pytest.approx(1.0)
    assert f.heuristic_quality_score > 0.0
    assert f.status == STATUS_OK
    assert f.unique_analog_count == 30


def test_disagreeing_analogs_kill_heuristic_quality() -> None:
    # Same pattern but half went +100 and half went -100: expected ~0, huge
    # dispersion and low neighbour agreement suppress heuristic quality.
    cur = [0.5, -0.5, 0.25]
    rows, _ = _hist(cur, 0.0, n=20)
    fwds = [100.0 if i % 2 == 0 else -100.0 for i in range(20)]
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert abs(f.expected_move_bps) < 10.0  # bimodal -> expected ~0 -> "flat"
    assert f.dispersion_bps > 50.0  # wide disagreement
    assert f.direction == "flat"
    assert f.neighbor_direction_agreement < 0.1
    assert f.heuristic_quality_score < 0.1
    assert f.status == STATUS_OK


def test_nearest_analogs_dominate_over_far_ones() -> None:
    # Near analogs (close to current) moved +60; far analogs (very different) moved
    # -300. The forecast must follow the NEAR analogs.
    cur = [1.0, 1.0, 1.0]
    near_rows, near_fwd = _hist([1.01, 0.99, 1.0], 60.0, n=15)
    far_rows, far_fwd = _hist([50.0, -50.0, 30.0], -300.0, n=15)
    rows = near_rows + far_rows
    fwds = near_fwd + far_fwd
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds, k=15
    )
    assert f.direction == "long"
    assert f.expected_move_bps > 30.0  # pulled toward the near +60, not the far -300


def test_short_direction() -> None:
    cur = [2.0, -1.0]
    rows, fwds = _hist(cur, -45.0, n=16)
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert f.direction == "short"
    assert f.expected_move_bps < 0
    assert f.neighbor_direction_agreement == pytest.approx(1.0)


def test_flat_band() -> None:
    cur = [1.0, 1.0]
    rows, fwds = _hist(cur, 2.0, n=16)  # +2 bps within default flat_band 5 bps
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert f.direction == "flat"


def test_insufficient_data() -> None:
    cur = [1.0, 2.0]
    rows, fwds = _hist(cur, 50.0, n=3)  # below default min_analogs=8
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert f.insufficient_data
    assert f.heuristic_quality_score == 0.0
    assert f.direction == "flat"
    assert f.status == STATUS_INSUFFICIENT_DATA
    assert "INSUFFICIENT_UNIQUE_ANALOGS" in f.reason_codes


def test_bad_rows_are_dropped_not_raised() -> None:
    cur = [1.0, 2.0, 3.0]
    good_rows, good_fwd = _hist(cur, 70.0, n=10)
    # wrong-width row, NaN feature, NaN forward — all must be dropped silently.
    bad_rows = [[1.0, 2.0], [float("nan"), 2.0, 3.0], [1.0, 2.0, 3.0]]
    bad_fwd = [10.0, 20.0, float("nan")]
    f = compute_analog_forecast(
        current_window=cur,
        historical_windows=good_rows + bad_rows,
        forward_return_bps=good_fwd + bad_fwd,
    )
    assert not f.insufficient_data
    assert f.direction == "long"
    assert f.n_analogs == 10  # only the 10 good rows survived
    assert f.dropped_analog_count == 3
    assert "HISTORICAL_ROW_WIDTH_MISMATCH_DROPPED" in f.reason_codes
    assert "HISTORICAL_ROW_NON_FINITE_OR_NON_NUMERIC_DROPPED" in f.reason_codes
    assert "HISTORICAL_FORWARD_NON_FINITE_OR_NON_NUMERIC_DROPPED" in f.reason_codes


def test_no_lookahead_current_forward_not_required() -> None:
    # The forecast is computed WITHOUT any knowledge of the current window's own
    # future — only historical windows carry realized forward returns. (Purely by
    # signature: there is no current-forward argument.) Sanity: result is stable.
    cur = [0.3, 0.7, -0.2, 0.5]
    rows, fwds = _hist(cur, 55.0, n=30)
    f1 = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    f2 = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert isinstance(f1, AnalogForecast)
    assert f1 == f2  # deterministic


def test_zero_variance_dimension_does_not_crash() -> None:
    # A constant feature column (std 0) must be handled (unit-scaled), not divide-by-zero.
    cur = [5.0, 1.0]
    rows = [[5.0, 1.0 + i * 0.01] for i in range(12)]  # first column constant
    fwds = [40.0] * 12
    f = compute_analog_forecast(
        current_window=cur, historical_windows=rows, forward_return_bps=fwds
    )
    assert not f.insufficient_data
    assert f.direction == "long"


def test_exact_duplicates_do_not_inflate_count_or_quality() -> None:
    cur = [0.1, 0.2, 0.3]
    f = compute_analog_forecast(
        current_window=cur,
        historical_windows=[list(cur) for _ in range(25)],
        forward_return_bps=[80.0] * 25,
    )

    assert f.status == STATUS_INSUFFICIENT_DATA
    assert f.insufficient_data
    assert f.unique_analog_count == 1
    assert f.duplicate_analog_count == 24
    assert f.heuristic_quality_score == 0.0
    assert "EXACT_DUPLICATE_ANALOG_DROPPED" in f.reason_codes


def test_k_must_not_be_below_minimum_selected_analog_count() -> None:
    rows, labels = _hist([1.0, 2.0], 25.0, n=8)
    f = compute_analog_forecast(
        current_window=[1.0, 2.0],
        historical_windows=rows,
        forward_return_bps=labels,
        k=1,
        min_analogs=8,
    )

    assert f.status == STATUS_INVALID_INPUT
    assert f.insufficient_data
    assert f.n_analogs == 0
    assert f.heuristic_quality_score == 0.0
    assert "K_BELOW_MIN_ANALOGS" in f.reason_codes


def test_mismatched_window_and_label_lengths_fail_closed() -> None:
    f = compute_analog_forecast(
        current_window=[1.0],
        historical_windows=[[1.0]] * 8,
        forward_return_bps=[1.0] * 7,
    )

    assert f.status == STATUS_INVALID_INPUT
    assert f.reason_codes == ("HISTORICAL_FORWARD_LENGTH_MISMATCH",)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"k": 0}, "K_MUST_BE_POSITIVE_INTEGER"),
        ({"k": 8.0}, "K_MUST_BE_POSITIVE_INTEGER"),
        ({"min_analogs": 0}, "MIN_ANALOGS_MUST_BE_POSITIVE_INTEGER"),
        ({"dispersion_ref_bps": 0.0}, "DISPERSION_REF_BPS_MUST_BE_FINITE_POSITIVE"),
        ({"dispersion_ref_bps": float("inf")}, "DISPERSION_REF_BPS_MUST_BE_FINITE_POSITIVE"),
        ({"flat_band_bps": -1.0}, "FLAT_BAND_BPS_MUST_BE_FINITE_NONNEGATIVE"),
        ({"flat_band_bps": "5"}, "FLAT_BAND_BPS_MUST_BE_FINITE_NONNEGATIVE"),
    ],
)
def test_invalid_parameters_return_explicit_status(overrides, reason) -> None:
    rows, labels = _hist([1.0], 10.0, n=8)
    kwargs = {
        "current_window": [1.0],
        "historical_windows": rows,
        "forward_return_bps": labels,
        "k": 8,
        "min_analogs": 8,
    }
    kwargs.update(overrides)

    f = compute_analog_forecast(**kwargs)

    assert f.status == STATUS_INVALID_INPUT
    assert reason in f.reason_codes


@pytest.mark.parametrize(
    "current_window",
    [None, "1,2,3", [], [True], ["1.0"], [float("nan")], [float("inf")]],
)
def test_invalid_current_windows_never_raise(current_window) -> None:
    f = compute_analog_forecast(
        current_window=current_window,
        historical_windows=[[1.0]] * 8,
        forward_return_bps=[1.0] * 8,
        k=8,
        min_analogs=8,
    )

    assert f.status == STATUS_INVALID_INPUT
    assert f.insufficient_data


def test_extreme_finite_values_remain_finite() -> None:
    rows = [[(-1.0 if i % 2 else 1.0) * 1e308, float(i + 1) * 1e290] for i in range(8)]
    labels = [(-1.0 if i % 2 else 1.0) * 1e308 for i in range(8)]

    f = compute_analog_forecast(
        current_window=[1e308, 1e290],
        historical_windows=rows,
        forward_return_bps=labels,
        k=8,
        min_analogs=8,
    )

    assert f.status == STATUS_OK
    assert not f.insufficient_data
    assert all(
        math.isfinite(value)
        for value in (
            f.expected_move_bps,
            f.dispersion_bps,
            f.neighbor_direction_agreement,
            f.mean_distance,
            f.heuristic_quality_score,
        )
    )


class _ExplodingSequence(Sequence):
    def __len__(self):
        raise RuntimeError("boom")

    def __getitem__(self, index):
        raise RuntimeError("boom")


class _ArrayLike:
    """Minimal NumPy-style indexing protocol without Sequence inheritance."""

    def __init__(self, values):
        self._values = list(values)

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


def test_structural_array_like_numeric_inputs_remain_supported() -> None:
    rows = _ArrayLike(
        [_ArrayLike([1.0 + (index * 0.01), 2.0 - (index * 0.01)]) for index in range(8)]
    )

    result = compute_analog_forecast(
        current_window=_ArrayLike([1.0, 2.0]),
        historical_windows=rows,
        forward_return_bps=_ArrayLike([10.0 + index for index in range(8)]),
        k=8,
        min_analogs=8,
    )

    assert result.status == STATUS_OK
    assert result.n_analogs == 8


def test_hostile_sequence_access_is_converted_to_invalid_result() -> None:
    f = compute_analog_forecast(
        current_window=_ExplodingSequence(),
        historical_windows=[],
        forward_return_bps=[],
    )

    assert f.status == STATUS_INVALID_INPUT
    assert f.reason_codes == ("INPUT_ACCESS_OR_NUMERICAL_ERROR",)


_UTC = UTC
_CURRENT_START = datetime(2026, 1, 2, 0, 0, tzinfo=_UTC)
_FEATURE_NAMES = ("return_lag_1", "volume_zscore", "funding_fraction")
_FEATURE_UNITS = ("fraction", "zscore", "fraction")
_FEATURE_TRANSFORM_VERSION = "echo_test_transform_v1"
_LOOKBACK_BARS = 1
_LOOKBACK_SECONDS = 60
_FEATURE_SCHEMA_SHA256 = compute_feature_schema_sha256(
    feature_names=_FEATURE_NAMES,
    feature_units=_FEATURE_UNITS,
    feature_transform_version=_FEATURE_TRANSFORM_VERSION,
    lookback_bars=_LOOKBACK_BARS,
    lookback_seconds=_LOOKBACK_SECONDS,
)
assert _FEATURE_SCHEMA_SHA256 is not None
_OUTCOME_NAME = "forward_close_return"
_OUTCOME_UNIT = "bps"
_OUTCOME_TRANSFORM_VERSION = "simple_return_v1"
_OUTCOME_PRICE_SOURCE = "binance_usdm_closed_candle_close"
_OUTCOME_RETURN_CONVENTION = "gross_before_costs"
_OUTCOME_SCHEMA_SHA256 = compute_outcome_schema_sha256(
    outcome_name=_OUTCOME_NAME,
    outcome_unit=_OUTCOME_UNIT,
    outcome_transform_version=_OUTCOME_TRANSFORM_VERSION,
    outcome_price_source=_OUTCOME_PRICE_SOURCE,
    outcome_return_convention=_OUTCOME_RETURN_CONVENTION,
)
assert _OUTCOME_SCHEMA_SHA256 is not None


def _safe_current(**changes) -> PITCurrentWindow:
    current = PITCurrentWindow(
        current_window_id="current-001",
        symbol="btcusdt",
        timeframe="1m",
        forecast_horizon_seconds=60,
        values=[0.1, 0.2, 0.3],
        feature_schema_sha256=_FEATURE_SCHEMA_SHA256,
        feature_names=_FEATURE_NAMES,
        feature_units=_FEATURE_UNITS,
        feature_transform_version=_FEATURE_TRANSFORM_VERSION,
        lookback_bars=_LOOKBACK_BARS,
        lookback_seconds=_LOOKBACK_SECONDS,
        outcome_schema_sha256=_OUTCOME_SCHEMA_SHA256,
        outcome_name=_OUTCOME_NAME,
        outcome_unit=_OUTCOME_UNIT,
        outcome_transform_version=_OUTCOME_TRANSFORM_VERSION,
        outcome_price_source=_OUTCOME_PRICE_SOURCE,
        outcome_return_convention=_OUTCOME_RETURN_CONVENTION,
        feature_window_start=_CURRENT_START + timedelta(minutes=14),
        feature_cutoff=_CURRENT_START + timedelta(minutes=15),
        event_time=_CURRENT_START + timedelta(minutes=14),
        ingested_at=_CURRENT_START + timedelta(minutes=15, milliseconds=200),
        available_at=_CURRENT_START + timedelta(minutes=15, milliseconds=300),
        decision_time=_CURRENT_START + timedelta(minutes=16),
        candle_closed_confirmed=True,
        latest_unclosed_candle_excluded=True,
    )
    return replace(current, **changes)


def _safe_candidates(
    count: int = 12,
    *,
    spacing_minutes: int = 4,
) -> list[PITAnalogCandidate]:
    base = datetime(2026, 1, 1, 0, 0, tzinfo=_UTC)
    candidates: list[PITAnalogCandidate] = []
    for index in range(count):
        start = base + timedelta(minutes=index * spacing_minutes)
        cutoff = start + timedelta(minutes=1)
        candidates.append(
            PITAnalogCandidate(
                analog_id=f"analog-{index:03d}",
                symbol="BTCUSDT",
                timeframe="1m",
                forecast_horizon_seconds=60,
                values=[
                    0.1 + (index * 0.001),
                    0.2 - (index * 0.001),
                    0.3 + (index * 0.002),
                ],
                feature_schema_sha256=_FEATURE_SCHEMA_SHA256,
                feature_names=_FEATURE_NAMES,
                feature_units=_FEATURE_UNITS,
                feature_transform_version=_FEATURE_TRANSFORM_VERSION,
                lookback_bars=_LOOKBACK_BARS,
                lookback_seconds=_LOOKBACK_SECONDS,
                outcome_schema_sha256=_OUTCOME_SCHEMA_SHA256,
                outcome_name=_OUTCOME_NAME,
                outcome_unit=_OUTCOME_UNIT,
                outcome_transform_version=_OUTCOME_TRANSFORM_VERSION,
                outcome_price_source=_OUTCOME_PRICE_SOURCE,
                outcome_return_convention=_OUTCOME_RETURN_CONVENTION,
                forward_return_bps=20.0 + index,
                feature_window_start=start,
                feature_cutoff=cutoff,
                event_time=start,
                ingested_at=cutoff + timedelta(milliseconds=200),
                available_at=cutoff + timedelta(milliseconds=300),
                decision_time=cutoff + timedelta(milliseconds=400),
                outcome_start_time=cutoff + timedelta(seconds=1),
                outcome_end_time=cutoff + timedelta(seconds=61),
                outcome_available_at=cutoff + timedelta(seconds=62),
                candle_closed_confirmed=True,
                latest_unclosed_candle_excluded=True,
                outcome_candle_closed_confirmed=True,
            )
        )
    return candidates


def _safe_forecast(
    *,
    current: PITCurrentWindow | None = None,
    candidates: list[PITAnalogCandidate] | None = None,
    generated_at=None,
    k: int = 8,
    min_analogs: int = 8,
) -> PITAnalogForecast:
    current = current or _safe_current()
    return compute_pit_safe_analog_forecast(
        current=current,
        candidates=candidates if candidates is not None else _safe_candidates(),
        generated_at=(
            generated_at
            if generated_at is not None
            else _CURRENT_START + timedelta(minutes=15, seconds=30)
        ),
        k=k,
        min_analogs=min_analogs,
    )


def test_pit_safe_happy_path_normalizes_utc_and_emits_lineage() -> None:
    current = _safe_current(
        feature_window_start="2026-01-01T19:14:00-05:00",
        feature_cutoff="2026-01-01T19:15:00-05:00",
        event_time="2026-01-01T19:14:00-05:00",
        ingested_at="2026-01-01T19:15:00.200000-05:00",
        available_at="2026-01-01T19:15:00.300000-05:00",
        decision_time="2026-01-01T19:16:00-05:00",
    )

    result = _safe_forecast(current=current)

    assert isinstance(result, PITAnalogForecast)
    assert result.status == STATUS_OK
    assert not result.forecast.insufficient_data
    assert result.symbol == "BTCUSDT"
    assert result.timeframe == "1m"
    assert result.feature_cutoff == "2026-01-02T00:15:00Z"
    assert result.decision_time == "2026-01-02T00:16:00Z"
    assert result.input_available_at == "2026-01-02T00:15:00.300000Z"
    assert result.available_at == "2026-01-02T00:15:30Z"
    assert result.generated_at == "2026-01-02T00:15:30Z"
    assert len(result.input_sha256 or "") == 64
    assert len(result.forecast_config_sha256 or "") == 64
    assert len(result.eligible_analog_ids) == 12
    assert len(result.selected_analog_ids) == 8
    assert result.forecast.overlap_checked
    assert result.rejected_analogs == ()


def test_pit_safe_monthly_timeframe_does_not_match_minute() -> None:
    candidates = _safe_candidates(12)
    candidates[0] = replace(candidates[0], timeframe="1M")

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert result.status == STATUS_OK
    assert result.timeframe == "1m"
    assert "ANALOG_TIMEFRAME_MISMATCH" in rejected["analog-000"]


def test_pit_safe_accepts_calendar_valid_monthly_lookbacks() -> None:
    lookback_seconds = 31 * 24 * 60 * 60
    feature_hash = compute_feature_schema_sha256(
        feature_names=_FEATURE_NAMES,
        feature_units=_FEATURE_UNITS,
        feature_transform_version=_FEATURE_TRANSFORM_VERSION,
        lookback_bars=1,
        lookback_seconds=lookback_seconds,
    )
    assert feature_hash is not None
    current_start = datetime(2026, 1, 1, tzinfo=_UTC)
    current_cutoff = datetime(2026, 2, 1, tzinfo=_UTC)
    current = _safe_current(
        timeframe="1M",
        feature_schema_sha256=feature_hash,
        lookback_seconds=lookback_seconds,
        feature_window_start=current_start,
        event_time=current_start,
        feature_cutoff=current_cutoff,
        ingested_at=current_cutoff + timedelta(milliseconds=200),
        available_at=current_cutoff + timedelta(milliseconds=300),
        decision_time=current_cutoff + timedelta(minutes=1),
    )
    starts = [
        datetime(year, month, 1, tzinfo=_UTC)
        for year in (2019, 2021)
        for month in (1, 3, 5, 7, 10, 12)
    ]
    candidates = _safe_candidates()
    for index, start in enumerate(starts):
        cutoff = datetime(
            start.year + int(start.month == 12),
            1 if start.month == 12 else start.month + 1,
            1,
            tzinfo=_UTC,
        )
        candidates[index] = replace(
            candidates[index],
            timeframe="1M",
            feature_schema_sha256=feature_hash,
            lookback_seconds=lookback_seconds,
            feature_window_start=start,
            event_time=start,
            feature_cutoff=cutoff,
            ingested_at=cutoff + timedelta(milliseconds=200),
            available_at=cutoff + timedelta(milliseconds=300),
            decision_time=cutoff + timedelta(milliseconds=400),
            outcome_start_time=cutoff + timedelta(seconds=1),
            outcome_end_time=cutoff + timedelta(seconds=61),
            outcome_available_at=cutoff + timedelta(seconds=62),
        )

    result = _safe_forecast(
        current=current,
        candidates=candidates,
        generated_at=current_cutoff + timedelta(seconds=30),
    )

    assert result.status == STATUS_OK
    assert len(result.eligible_analog_ids) == 12


def test_pit_safe_accepts_bar_open_event_before_feature_cutoff() -> None:
    result = _safe_forecast()

    assert result.status == STATUS_OK
    assert result.event_time == "2026-01-02T00:14:00Z"
    assert result.feature_cutoff == "2026-01-02T00:15:00Z"


def test_pit_safe_rejects_event_after_feature_cutoff() -> None:
    result = _safe_forecast(
        current=_safe_current(
            event_time=_CURRENT_START + timedelta(minutes=15, milliseconds=100)
        )
    )

    assert result.status == STATUS_INVALID_INPUT
    assert "CURRENT_EVENT_TIME_AFTER_FEATURE_CUTOFF" in result.reason_codes


def test_pit_safe_rejects_semantically_different_feature_vector() -> None:
    candidates = _safe_candidates()
    different_names = ("return_lag_1", "volume_zscore", "open_interest_fraction")
    different_hash = compute_feature_schema_sha256(
        feature_names=different_names,
        feature_units=_FEATURE_UNITS,
        feature_transform_version=_FEATURE_TRANSFORM_VERSION,
        lookback_bars=_LOOKBACK_BARS,
        lookback_seconds=_LOOKBACK_SECONDS,
    )
    assert different_hash is not None
    candidates[0] = replace(
        candidates[0],
        feature_names=different_names,
        feature_schema_sha256=different_hash,
    )

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert "ANALOG_FEATURE_SCHEMA_MISMATCH" in rejected["analog-000"]
    assert "ANALOG_FEATURE_NAMES_MISMATCH" in rejected["analog-000"]


def test_pit_safe_rejects_semantically_different_outcome_label() -> None:
    candidates = _safe_candidates()
    different_convention = "net_after_costs"
    different_hash = compute_outcome_schema_sha256(
        outcome_name=_OUTCOME_NAME,
        outcome_unit=_OUTCOME_UNIT,
        outcome_transform_version=_OUTCOME_TRANSFORM_VERSION,
        outcome_price_source=_OUTCOME_PRICE_SOURCE,
        outcome_return_convention=different_convention,
    )
    assert different_hash is not None
    candidates[0] = replace(
        candidates[0],
        outcome_schema_sha256=different_hash,
        outcome_return_convention=different_convention,
    )

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert "ANALOG_OUTCOME_SCHEMA_MISMATCH" in rejected["analog-000"]
    assert "ANALOG_OUTCOME_RETURN_CONVENTION_MISMATCH" in rejected["analog-000"]


def test_pit_lineage_hash_includes_forecast_configuration() -> None:
    eight = _safe_forecast(k=8, min_analogs=8)
    ten = _safe_forecast(k=10, min_analogs=8)

    assert eight.status == STATUS_OK
    assert ten.status == STATUS_OK
    assert eight.selected_analog_ids != ten.selected_analog_ids
    assert eight.forecast_config_sha256 != ten.forecast_config_sha256
    assert eight.input_sha256 != ten.input_sha256


def test_pit_lineage_hash_includes_generation_time() -> None:
    first = _safe_forecast(generated_at=_CURRENT_START + timedelta(minutes=15, seconds=30))
    second = _safe_forecast(generated_at=_CURRENT_START + timedelta(minutes=15, seconds=31))

    assert first.status == STATUS_OK
    assert second.status == STATUS_OK
    assert first.forecast_config_sha256 == second.forecast_config_sha256
    assert first.input_sha256 != second.input_sha256


def test_pit_safe_rejects_naive_datetime() -> None:
    current = _safe_current(feature_cutoff=datetime(2026, 1, 2, 0, 15))

    result = _safe_forecast(current=current)

    assert result.status == STATUS_INVALID_INPUT
    assert "CURRENT_FEATURE_CUTOFF_INVALID_OR_NAIVE" in result.reason_codes
    assert result.input_sha256 is None
    assert result.overlap_checked is False
    assert result.forecast.overlap_checked is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"candle_closed_confirmed": False}, "CURRENT_CANDLE_NOT_FINAL"),
        ({"latest_unclosed_candle_excluded": False}, "CURRENT_UNCLOSED_CANDLE_NOT_EXCLUDED"),
        ({"lineage_valid": False}, "CURRENT_LINEAGE_INVALID"),
        ({"dirty": True}, "CURRENT_DIRTY"),
        ({"missing_required_fields": ("close",)}, "CURRENT_REQUIRED_FIELDS_MISSING"),
        (
            {"missing_required_fields": "close"},
            "CURRENT_MISSING_REQUIRED_FIELDS_CONTRACT_INVALID",
        ),
        ({"stale_required_fields": ("ret_pct",)}, "CURRENT_REQUIRED_FIELDS_STALE"),
        (
            {"available_at": _CURRENT_START + timedelta(minutes=17)},
            "CURRENT_AVAILABLE_AT_AFTER_DECISION_TIME",
        ),
        (
            {"feature_cutoff": _CURRENT_START + timedelta(minutes=17)},
            "CURRENT_FEATURE_CUTOFF_AFTER_DECISION_TIME",
        ),
    ],
)
def test_pit_safe_rejects_dirty_or_temporally_invalid_current(changes, reason) -> None:
    result = _safe_forecast(current=_safe_current(**changes))

    assert result.status == STATUS_INVALID_INPUT
    assert reason in result.reason_codes


def test_pit_safe_rejects_lookback_that_does_not_match_timeframe() -> None:
    result = _safe_forecast(current=_safe_current(timeframe="4h"))

    assert result.status == STATUS_INVALID_INPUT
    assert "CURRENT_LOOKBACK_TIMEFRAME_MISMATCH" in result.reason_codes


def test_pit_safe_rejects_generated_at_after_decision() -> None:
    result = _safe_forecast(generated_at=_CURRENT_START + timedelta(minutes=17))

    assert result.status == STATUS_INVALID_INPUT
    assert "GENERATED_AT_AFTER_DECISION_TIME" in result.reason_codes


def test_pit_safe_rejects_bad_candidates_with_explicit_per_id_reasons() -> None:
    candidates = _safe_candidates(16)
    decision = _CURRENT_START + timedelta(minutes=16)
    candidates[0] = replace(candidates[0], symbol="ETHUSDT")
    candidates[1] = replace(candidates[1], timeframe="5m")
    candidates[2] = replace(candidates[2], forecast_horizon_seconds=300)
    candidates[3] = replace(candidates[3], dirty=True)
    candidates[4] = replace(candidates[4], missing_required_fields=("close",))
    candidates[5] = replace(candidates[5], stale_required_fields=("ret_pct",))
    candidates[6] = replace(candidates[6], outcome_candle_closed_confirmed=False)
    candidates[7] = replace(candidates[7], outcome_available_at=decision + timedelta(seconds=1))

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert result.status == STATUS_OK
    assert "ANALOG_CANDIDATES_REJECTED" in result.reason_codes
    assert "ANALOG_SYMBOL_MISMATCH" in rejected["analog-000"]
    assert "ANALOG_TIMEFRAME_MISMATCH" in rejected["analog-001"]
    assert "ANALOG_FORECAST_HORIZON_MISMATCH" in rejected["analog-002"]
    assert "ANALOG_DIRTY" in rejected["analog-003"]
    assert "ANALOG_REQUIRED_FIELDS_MISSING" in rejected["analog-004"]
    assert "ANALOG_REQUIRED_FIELDS_STALE" in rejected["analog-005"]
    assert "ANALOG_OUTCOME_CANDLE_NOT_FINAL" in rejected["analog-006"]
    assert "ANALOG_OUTCOME_AVAILABLE_AT_AFTER_DECISION_TIME" in rejected["analog-007"]
    assert len(result.eligible_analog_ids) == 8


def test_pit_safe_rejects_feature_available_after_historical_outcome_started() -> None:
    candidates = _safe_candidates()
    candidate = candidates[0]
    candidates[0] = replace(
        candidate,
        decision_time=candidate.outcome_start_time,
        available_at=datetime(2026, 1, 1, 0, 1, 2, tzinfo=_UTC),
        outcome_start_time=datetime(2026, 1, 1, 0, 1, 1, tzinfo=_UTC),
        outcome_end_time=datetime(2026, 1, 1, 0, 2, 1, tzinfo=_UTC),
        outcome_available_at=datetime(2026, 1, 1, 0, 2, 2, tzinfo=_UTC),
    )

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert "ANALOG_AVAILABLE_AT_AFTER_ANALOG_DECISION_TIME" in rejected["analog-000"]


def test_pit_safe_requires_candidate_to_exclude_latest_unclosed_candle() -> None:
    candidates = _safe_candidates()
    candidates[0] = replace(candidates[0], latest_unclosed_candle_excluded=False)

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert "ANALOG_UNCLOSED_CANDLE_NOT_EXCLUDED" in rejected["analog-000"]


def test_pit_safe_rejects_duplicate_ids_instead_of_choosing_by_input_order() -> None:
    candidates = _safe_candidates(12)
    candidates[1] = replace(candidates[1], analog_id=candidates[0].analog_id)

    result = _safe_forecast(candidates=candidates, k=8, min_analogs=8)

    duplicate_rejections = [
        reasons for analog_id, reasons in result.rejected_analogs if analog_id == "analog-000"
    ]
    assert len(duplicate_rejections) == 2
    assert all("DUPLICATE_ANALOG_ID" in reasons for reasons in duplicate_rejections)
    assert "analog-000" not in result.eligible_analog_ids


def test_pit_safe_overlap_filter_is_deterministic_under_input_reordering() -> None:
    candidates = _safe_candidates(20, spacing_minutes=1)

    forward = _safe_forecast(candidates=candidates, k=6, min_analogs=6)
    reverse = _safe_forecast(candidates=list(reversed(candidates)), k=6, min_analogs=6)

    assert forward.status == STATUS_OK
    assert reverse.status == STATUS_OK
    assert forward.eligible_analog_ids == reverse.eligible_analog_ids
    assert forward.selected_analog_ids == reverse.selected_analog_ids
    assert forward.input_sha256 == reverse.input_sha256
    assert any(
        "ANALOG_INTERVAL_OVERLAPS_ANOTHER" in reasons
        for _analog_id, reasons in forward.rejected_analogs
    )


def test_pit_safe_candidate_outcome_must_precede_current_feature_window() -> None:
    candidates = _safe_candidates(12)
    candidate = candidates[0]
    cutoff = _CURRENT_START + timedelta(minutes=13, seconds=30)
    candidates[0] = replace(
        candidate,
        feature_window_start=cutoff - timedelta(minutes=1),
        feature_cutoff=cutoff,
        event_time=cutoff - timedelta(minutes=1),
        ingested_at=cutoff + timedelta(milliseconds=200),
        available_at=cutoff + timedelta(milliseconds=300),
        decision_time=cutoff + timedelta(milliseconds=400),
        outcome_start_time=cutoff + timedelta(seconds=1),
        outcome_end_time=cutoff + timedelta(seconds=61),
        outcome_available_at=cutoff + timedelta(seconds=62),
    )

    result = _safe_forecast(candidates=candidates)
    rejected = {analog_id: reasons for analog_id, reasons in result.rejected_analogs}

    assert "ANALOG_INTERVAL_OVERLAPS_CURRENT_WINDOW" in rejected["analog-000"]


def test_pit_safe_exact_numeric_duplicates_cannot_restore_quality() -> None:
    candidates = _safe_candidates(12)
    for index in range(1, len(candidates)):
        candidates[index] = replace(
            candidates[index],
            values=candidates[0].values,
            forward_return_bps=candidates[0].forward_return_bps,
        )

    result = _safe_forecast(candidates=candidates)

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.forecast.heuristic_quality_score == 0.0
    assert len(result.eligible_analog_ids) == 1
    assert (
        sum(
            "EXACT_DUPLICATE_ANALOG_DROPPED" in reasons
            for _analog_id, reasons in result.rejected_analogs
        )
        == 11
    )


def test_pit_safe_invalid_candidate_collection_never_raises() -> None:
    result = compute_pit_safe_analog_forecast(
        current=_safe_current(),
        candidates=None,
        generated_at=_CURRENT_START + timedelta(minutes=15, seconds=30),
    )

    assert result.status == STATUS_INVALID_INPUT
    assert "ANALOG_CANDIDATES_MUST_BE_SEQUENCE" in result.reason_codes
