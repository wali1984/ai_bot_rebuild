from __future__ import annotations

# mypy: disable-error-code=misc
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _rsi as production_ta_rsi,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    CORE_TA_MINIMUM_SOURCE_ROWS,
    EXTERNAL_DERIVATION_SEMANTICS,
    EXTERNAL_FULL_LIST_DERIVATIONS,
    FINALITY_SEMANTICS,
    HTF_POSITIONAL_STRIDE,
    HTF_RSI_MINIMUM_SOURCE_ROWS,
    RSI_PERIOD,
    RSI_REQUIRED_CLOSES,
    CanonicalContiguousSuffixInspection,
    FeatureWindowContractError,
    FullContiguousCoreInputBinding,
    bind_full_contiguous_core_ta_input,
    build_core_ta_minimum_coverage_contract,
    inspect_canonical_contiguous_suffix,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_ROWS,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
)

SYMBOL = "BTCUSDT"
BASE_MS = 1_800_000_000_000


def _aligned_base(timeframe: str) -> int:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    return (BASE_MS // duration) * duration


def _rest_source_row(open_time: int, timeframe: str) -> list[object]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    return [
        open_time,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "12.0",
        open_time + duration - 1,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_rest(
    index: int,
    timeframe: str = "1m",
    *,
    availability_lag_ms: int = 200,
) -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    open_time = _aligned_base(timeframe) + (index * duration)
    close_time = open_time + duration - 1
    return canonical_from_binance_rest(
        _rest_source_row(open_time, timeframe),
        symbol=SYMBOL,
        timeframe=timeframe,
        ingested_at=close_time + availability_lag_ms,
    ).to_dict()


def _rows(indices: list[int], timeframe: str = "1m") -> list[dict[str, Any]]:
    return [_canonical_rest(index, timeframe) for index in indices]


def _observed_after(rows: list[dict[str, Any]]) -> int:
    return max(cast(int, row["available_at"]) for row in rows)


def _expected_close(
    rows: list[dict[str, Any]] | tuple[()],
    timeframe: str = "1m",
) -> int:
    if rows:
        return cast(int, rows[-1]["candle_close_time"])
    return _aligned_base(timeframe) - 1


def _inspect(
    rows: list[dict[str, Any]] | tuple[()],
    *,
    timeframe: str = "1m",
    observed_at: int | None = None,
    expected_latest_close: int | None = None,
) -> CanonicalContiguousSuffixInspection:
    resolved_observed = (
        observed_at
        if observed_at is not None
        else (_observed_after(rows) if rows else _aligned_base(timeframe))
    )
    return inspect_canonical_contiguous_suffix(
        rows,
        expected_symbol=SYMBOL,
        timeframe=timeframe,
        consumer_observed_at_ms=resolved_observed,
        expected_latest_finalized_close_time=(
            expected_latest_close
            if expected_latest_close is not None
            else _expected_close(rows, timeframe)
        ),
    )


def _bind(
    rows: list[dict[str, Any]],
    *,
    timeframe: str = "1m",
) -> FullContiguousCoreInputBinding:
    return bind_full_contiguous_core_ta_input(
        rows,
        expected_symbol=SYMBOL,
        timeframe=timeframe,
        consumer_observed_at_ms=_observed_after(rows),
        expected_latest_finalized_close_time=_expected_close(rows, timeframe),
    )


def _production_feature_rows(count: int) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for index in range(count):
        close = 100.0 + (index * 0.17) + (((index % 7) - 3) * 1.1) + (((index % 11) - 5) * 0.23)
        rows.append(
            {
                "open": close - 0.2,
                "high": close + 0.8,
                "low": close - 0.9,
                "close": close,
                "volume": 10.0 + index,
            }
        )
    return rows


def test_contract_derives_core_ta_minimum_71_from_transform_parameters() -> None:
    contract = build_core_ta_minimum_coverage_contract(timeframe="1m")
    dependencies = {item.feature_name: item for item in contract.dependencies}

    assert RSI_REQUIRED_CLOSES == RSI_PERIOD + 1 == 15
    assert HTF_RSI_MINIMUM_SOURCE_ROWS == ((RSI_REQUIRED_CLOSES - 1) * HTF_POSITIONAL_STRIDE + 1)
    assert HTF_RSI_MINIMUM_SOURCE_ROWS == 71
    assert CORE_TA_MINIMUM_SOURCE_ROWS == 71
    assert contract.minimum_source_rows == max(
        item.minimum_source_rows for item in contract.dependencies
    )
    assert contract.minimum_source_rows == 71
    assert dependencies["htf_rsi_14_positional_5x_proxy"].minimum_source_rows == 71
    assert dict(dependencies["htf_rsi_14_positional_5x_proxy"].parameters) == {
        "transform": "closes[::5]",
        "rsi_period": 14,
        "required_transformed_closes": 15,
        "positional_stride": 5,
    }


@pytest.mark.parametrize("timeframe", SUPPORTED_TRAINER_TIMEFRAMES)
def test_contract_is_deterministic_and_binds_supported_timeframe_semantics(
    timeframe: str,
) -> None:
    first = build_core_ta_minimum_coverage_contract(timeframe=timeframe)
    second = build_core_ta_minimum_coverage_contract(timeframe=timeframe)
    material = json.loads(first.contract_material_json)

    assert first == second
    assert (
        first.contract_sha256
        == hashlib.sha256(first.contract_material_json.encode("utf-8")).hexdigest()
    )
    assert first.timeframe_duration_ms == TIMEFRAME_DURATION_MS[timeframe]
    assert material["timeframe"] == timeframe
    assert material["timeframe_duration_ms"] == TIMEFRAME_DURATION_MS[timeframe]
    assert material["alignment_and_finality"]["finality"] == FINALITY_SEMANTICS
    assert first.dependency_classification == "CORE_TA_MINIMUM_COVERAGE_INVARIANT"
    assert first.dependency_scope == ("CORE_NATIVE_OHLCV_DERIVATIONS_FEATURES_FROM_MARKET")
    assert first.market_selection_threshold is False
    assert first.grants_market_admission is False
    assert first.grants_trainer_admission is False
    assert first.grants_live_execution is False


def test_timeframe_changes_contract_hash_but_not_core_minimum() -> None:
    one_minute = build_core_ta_minimum_coverage_contract(timeframe="1m")
    five_minute = build_core_ta_minimum_coverage_contract(timeframe="5m")

    assert one_minute.contract_sha256 != five_minute.contract_sha256
    assert one_minute.minimum_source_rows == five_minute.minimum_source_rows == 71
    assert one_minute.dependencies == five_minute.dependencies


def test_contract_cannot_misrepresent_core_71_as_all_feature_families() -> None:
    contract = build_core_ta_minimum_coverage_contract(timeframe="1m")
    material = json.loads(contract.contract_material_json)

    assert contract.all_feature_families_covered is False
    assert contract.external_full_list_derivations == (
        ("market_structure", 100),
        ("fair_value_gap", 100),
        ("liquidity_zones", 100),
        ("vwap", 240),
        ("volume_profile", 240),
        ("cvd", 500),
    )
    assert contract.external_full_list_derivations == EXTERNAL_FULL_LIST_DERIVATIONS
    assert contract.external_derivation_semantics == EXTERNAL_DERIVATION_SEMANTICS
    assert material["all_feature_families_covered"] is False
    assert all(
        item["covered_by_this_contract"] is False
        for item in material["excluded_external_full_list_derivations"]
    )


def test_inspection_reports_all_gaps_and_only_the_latest_contiguous_suffix() -> None:
    rows = _rows([0, 2, 3, 6, 7, 8])
    result = _inspect(rows)

    assert result.raw_row_count == 6
    assert result.gap_count == 2
    assert result.gap_indices == (1, 3)
    assert result.gap_missing_interval_counts == (1, 2)
    assert result.missing_interval_count == 3
    assert result.contiguous_suffix_start_index == 3
    assert result.contiguous_suffix_count == 3
    assert result.selected_suffix_count == 3
    assert [row.source_index for row in result.selected_suffix_rows] == [3, 4, 5]
    assert result.selected_candle_ids == tuple(cast(str, row["candle_id"]) for row in rows[3:])
    assert (
        result.selected_candle_id_chain_sha256
        == hashlib.sha256(result.selected_candle_id_chain_material_json.encode("utf-8")).hexdigest()
    )
    assert result.core_ta_minimum_source_rows == 71
    assert result.core_ta_minimum_coverage_ready is False
    assert result.tail_missing_interval_count == 0
    assert result.market_selection_threshold is False
    assert result.source_schema_fully_validated is False
    assert result.trainer_admission_granted is False
    assert result.live_execution_authorized is False


def test_empty_census_is_reportable_but_cannot_bind_a_core_input() -> None:
    result = _inspect(())

    assert result.symbol == SYMBOL
    assert result.raw_row_count == 0
    assert result.contiguous_suffix_start_index == 0
    assert result.contiguous_suffix_count == 0
    assert result.selected_suffix_rows == ()
    assert result.selected_candle_ids == ()
    assert result.tail_missing_interval_count is None
    assert result.core_ta_minimum_coverage_ready is False
    with pytest.raises(
        FeatureWindowContractError,
        match="tail_is_stale",
    ):
        bind_full_contiguous_core_ta_input(
            (),
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS,
            expected_latest_finalized_close_time=BASE_MS - 1,
        )


def test_internal_gap_cannot_be_hidden_by_large_raw_row_count() -> None:
    # 141 rows in total, but the latest gap leaves only 70 contiguous rows.
    rows = _rows(list(range(71)) + list(range(72, 142)))
    inspection = _inspect(rows)

    assert inspection.raw_row_count == 141
    assert inspection.gap_indices == (71,)
    assert inspection.contiguous_suffix_count == 70
    assert inspection.core_ta_minimum_coverage_ready is False
    with pytest.raises(
        FeatureWindowContractError,
        match="core_ta_minimum_coverage_unavailable",
    ):
        _bind(rows)


def test_binding_with_sufficient_post_gap_history_excludes_pre_gap_prefix() -> None:
    # This intentionally characterizes a future input-selection behavior
    # change versus the current worker, which passes its full raw list. Wiring
    # must consume exactly this 90-row suffix or remain held pending approval.
    rows = _rows(list(range(10)) + list(range(11, 101)))
    binding = _bind(rows)

    assert binding.raw_row_count == 100
    assert binding.gap_indices == (10,)
    assert binding.gap_missing_interval_counts == (1,)
    assert binding.contiguous_suffix_start_index == 10
    assert binding.contiguous_suffix_count == 90
    assert binding.selected_source_start_index == 10
    assert binding.selected_source_end_index_exclusive == 100
    assert binding.selected_row_count == 90
    assert binding.selected_candle_ids == tuple(cast(str, row["candle_id"]) for row in rows[10:])


def test_tail_missing_intervals_hold_minimum_coverage_even_with_80_rows() -> None:
    rows = _rows(list(range(80)))
    duration = TIMEFRAME_DURATION_MS["1m"]
    expected_latest_close = cast(int, rows[-1]["candle_close_time"]) + (3 * duration)
    observed_at = expected_latest_close + 1
    inspection = _inspect(
        rows,
        observed_at=observed_at,
        expected_latest_close=expected_latest_close,
    )

    assert inspection.contiguous_suffix_count == 80
    assert inspection.tail_missing_interval_count == 3
    assert inspection.latest_candle_matches_expected_cutoff is False
    assert inspection.core_ta_minimum_coverage_ready is False
    with pytest.raises(FeatureWindowContractError, match="tail_is_stale"):
        bind_full_contiguous_core_ta_input(
            rows,
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=observed_at,
            expected_latest_finalized_close_time=expected_latest_close,
        )


def test_explicit_symbol_and_latest_finalized_cutoff_are_required() -> None:
    rows = _rows([0, 1])
    with pytest.raises(FeatureWindowContractError, match="rows_symbol_mismatch"):
        inspect_canonical_contiguous_suffix(
            rows,
            expected_symbol="ETHUSDT",
            timeframe="1m",
            consumer_observed_at_ms=_observed_after(rows),
            expected_latest_finalized_close_time=_expected_close(rows),
        )

    with pytest.raises(
        FeatureWindowContractError,
        match="source_close_after_expected_cutoff",
    ):
        inspect_canonical_contiguous_suffix(
            rows,
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=_observed_after(rows),
            expected_latest_finalized_close_time=cast(int, rows[0]["candle_close_time"]),
        )


def test_binding_preserves_all_80_contiguous_rows_and_exact_identities() -> None:
    rows = _rows(list(range(80)))
    observed_at = _observed_after(rows)
    selected = _bind(rows)
    material = json.loads(selected.selection_material_json)

    assert selected.raw_row_count == 80
    assert selected.contiguous_suffix_count == 80
    assert selected.selected_source_start_index == 0
    assert selected.selected_source_end_index_exclusive == 80
    assert selected.selected_row_count == 80
    assert [row.source_index for row in selected.selected_rows] == list(range(80))
    assert selected.selected_candle_ids == tuple(cast(str, row["candle_id"]) for row in rows)
    assert (
        selected.selected_candle_id_chain_sha256
        == hashlib.sha256(
            selected.selected_candle_id_chain_material_json.encode("utf-8")
        ).hexdigest()
    )
    assert material["selection"]["selected_row_count"] == 80
    assert len(material["selection"]["rows"]) == 80
    assert material["selection"]["selected_candle_id_chain_sha256"] == (
        selected.selected_candle_id_chain_sha256
    )
    assert (
        selected.selection_sha256
        == hashlib.sha256(selected.selection_material_json.encode("utf-8")).hexdigest()
    )
    assert selected.latest_selected_end_exclusive_finality_time == (
        selected.latest_selected_economic_close_time + 1
    )
    assert selected.max_selected_available_at <= observed_at
    assert selected.entire_contiguous_suffix_bound is True
    assert selected.all_feature_families_covered is False
    assert selected.source_schema_fully_validated is False
    assert selected.immutable_cas_captured is False
    assert selected.trainer_admission_granted is False
    assert selected.live_execution_authorized is False


@pytest.mark.parametrize("full_count", [80, 100])
def test_production_characterization_proves_71_is_minimum_not_trim_count(
    full_count: int,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as feature_loop

    rows_70 = _production_feature_rows(70)
    rows_71 = _production_feature_rows(71)
    closes_70 = [row["close"] for row in rows_70]
    closes_71 = [row["close"] for row in rows_71]
    features_70 = feature_loop._features_from_market(  # noqa: SLF001
        {"ticker_24hr": {}, "funding": {}, "_klines": rows_70}
    )
    features_71 = feature_loop._features_from_market(  # noqa: SLF001
        {"ticker_24hr": {}, "funding": {}, "_klines": rows_71}
    )

    assert feature_loop.__dict__["_ta_rsi"] is production_ta_rsi
    assert production_ta_rsi(closes_70[::5], 14) is None
    assert features_70["htf_rsi_14"] is None
    assert production_ta_rsi(closes_71[::5], 14) is not None
    assert features_71["htf_rsi_14"] is not None

    full_rows = _production_feature_rows(full_count)
    full_features = feature_loop._features_from_market(  # noqa: SLF001
        {"ticker_24hr": {}, "funding": {}, "_klines": full_rows}
    )
    trimmed_features = feature_loop._features_from_market(  # noqa: SLF001
        {"ticker_24hr": {}, "funding": {}, "_klines": full_rows[-71:]}
    )

    # The positional higher-timeframe proxy changes phase and recursive TA
    # changes warmup history. A minimum-coverage gate must never trim inputs.
    assert full_features["htf_rsi_14"] != trimmed_features["htf_rsi_14"]
    assert full_features["ema_26"] != trimmed_features["ema_26"]


def test_selection_hash_changes_when_exact_selected_identity_changes() -> None:
    first_rows = _rows(list(range(71)))
    replacement = _canonical_rest(71)
    # Preserve continuity while changing the selected identity by replacing
    # the full window with the next contiguous 71-candle range.
    second_rows = _rows(list(range(1, 72)))

    first = _bind(first_rows)
    second = _bind(second_rows)

    assert replacement["candle_id"] == second_rows[-1]["candle_id"]
    assert first.selected_candle_ids != second.selected_candle_ids
    assert first.selected_candle_id_chain_sha256 != (second.selected_candle_id_chain_sha256)
    assert first.selection_sha256 != second.selection_sha256


def test_end_exclusive_finality_boundary_is_enforced_exactly() -> None:
    row = _canonical_rest(0, availability_lag_ms=0)
    close_time = cast(int, row["candle_close_time"])

    with pytest.raises(
        FeatureWindowContractError,
        match="expected_latest_close_not_final",
    ):
        _inspect([row], observed_at=close_time)

    with pytest.raises(
        FeatureWindowContractError,
        match="available_at_precedes_end_exclusive_finality",
    ):
        _inspect([row], observed_at=close_time + 1)

    first_available_row = _canonical_rest(0, availability_lag_ms=1)
    accepted = _inspect([first_available_row], observed_at=close_time + 1)
    assert accepted.selected_suffix_rows[0].candle_close_time + 1 == close_time + 1


def test_unix_epoch_open_zero_remains_a_valid_aligned_candle_time() -> None:
    duration = TIMEFRAME_DURATION_MS["1m"]
    close_time = duration - 1
    # The continuity helper intentionally consumes only this canonical timing
    # and identity projection; the full source-schema validator remains the
    # authority for all other canonical fields.
    row = {
        "symbol": SYMBOL,
        "timeframe": "1m",
        "candle_id": "a" * 24,
        "candle_open_time": 0,
        "candle_close_time": close_time,
        "available_at": close_time + 1,
    }

    result = inspect_canonical_contiguous_suffix(
        [row],
        expected_symbol=SYMBOL,
        timeframe="1m",
        consumer_observed_at_ms=close_time + 1,
        expected_latest_finalized_close_time=close_time,
    )
    assert result.selected_suffix_rows[0].candle_open_time == 0


def test_available_at_must_not_be_after_consumer_observation() -> None:
    row = _canonical_rest(0, availability_lag_ms=200)
    available_at = cast(int, row["available_at"])
    with pytest.raises(
        FeatureWindowContractError,
        match="available_after_consumer_observation",
    ):
        _inspect([row], observed_at=available_at - 1)


@pytest.mark.parametrize("timeframe", SUPPORTED_TRAINER_TIMEFRAMES)
def test_canonical_rows_validate_exact_alignment_for_every_supported_timeframe(
    timeframe: str,
) -> None:
    rows = _rows([0, 1, 2], timeframe)
    result = _inspect(rows, timeframe=timeframe)

    assert result.timeframe == timeframe
    assert result.timeframe_duration_ms == TIMEFRAME_DURATION_MS[timeframe]
    assert result.contiguous_suffix_count == 3


@pytest.mark.parametrize(
    "timeframe",
    [None, True, False, 1, 1.0, b"1m", "", "1M", "2m", "1d"],
)
def test_hostile_or_unsupported_timeframes_fail_closed(timeframe: object) -> None:
    with pytest.raises(FeatureWindowContractError, match="timeframe_invalid"):
        build_core_ta_minimum_coverage_contract(timeframe=timeframe)


@pytest.mark.parametrize(
    "observed_at",
    [None, True, False, 0, -1, 1.0, float("nan"), float("inf"), "1800000000000"],
)
def test_hostile_consumer_observation_clocks_fail_closed(observed_at: object) -> None:
    with pytest.raises(
        FeatureWindowContractError,
        match="consumer_observed_at_ms_invalid",
    ):
        inspect_canonical_contiguous_suffix(
            (),
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=observed_at,
            expected_latest_finalized_close_time=BASE_MS - 1,
        )


@pytest.mark.parametrize(
    "symbol",
    [None, True, False, 1, 1.0, b"BTCUSDT", "", "btcusdt", "BTC-USDT"],
)
def test_hostile_expected_symbols_fail_closed(symbol: object) -> None:
    with pytest.raises(FeatureWindowContractError, match="expected_symbol_invalid"):
        inspect_canonical_contiguous_suffix(
            (),
            expected_symbol=symbol,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS,
            expected_latest_finalized_close_time=BASE_MS - 1,
        )


@pytest.mark.parametrize(
    "expected_close",
    [None, True, False, -1, 1.0, float("nan"), float("inf"), "1799999999999"],
)
def test_hostile_expected_latest_cutoffs_fail_closed(expected_close: object) -> None:
    with pytest.raises(
        FeatureWindowContractError,
        match="expected_latest_finalized_close_time_invalid",
    ):
        inspect_canonical_contiguous_suffix(
            (),
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS,
            expected_latest_finalized_close_time=expected_close,
        )


def test_expected_latest_cutoff_must_be_aligned_and_already_final() -> None:
    with pytest.raises(
        FeatureWindowContractError,
        match="expected_latest_close_alignment_invalid",
    ):
        inspect_canonical_contiguous_suffix(
            (),
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS,
            expected_latest_finalized_close_time=BASE_MS - 2,
        )

    with pytest.raises(
        FeatureWindowContractError,
        match="expected_latest_close_not_final",
    ):
        inspect_canonical_contiguous_suffix(
            (),
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS - 1,
            expected_latest_finalized_close_time=BASE_MS - 1,
        )


@pytest.mark.parametrize("rows", [None, True, {}, set(), "rows", 1])
def test_hostile_row_containers_fail_closed(rows: object) -> None:
    with pytest.raises(FeatureWindowContractError, match="rows_container_invalid"):
        inspect_canonical_contiguous_suffix(
            rows,
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS,
            expected_latest_finalized_close_time=BASE_MS - 1,
        )


def test_raw_binance_list_rows_are_rejected_without_false_identity_evidence() -> None:
    row = _rest_source_row(_aligned_base("1m"), "1m")
    with pytest.raises(
        FeatureWindowContractError,
        match="row_requires_canonical_dict",
    ):
        inspect_canonical_contiguous_suffix(
            [row],
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=BASE_MS + TIMEFRAME_DURATION_MS["1m"],
            expected_latest_finalized_close_time=(BASE_MS + TIMEFRAME_DURATION_MS["1m"] - 1),
        )


@pytest.mark.parametrize(
    "hostile_open",
    [True, False, 1.0, float("nan"), float("inf"), "1800000000000"],
)
def test_bool_nonfinite_and_noninteger_candle_times_fail_closed(
    hostile_open: object,
) -> None:
    row = _canonical_rest(0)
    row["candle_open_time"] = hostile_open
    with pytest.raises(FeatureWindowContractError, match="candle_open_time_invalid"):
        _inspect([row])


def test_misaligned_close_duplicate_ids_and_nonmonotonic_rows_fail_closed() -> None:
    aligned = _canonical_rest(0)
    bad_close = copy.deepcopy(aligned)
    bad_close["candle_close_time"] = cast(int, bad_close["candle_close_time"]) - 1
    with pytest.raises(FeatureWindowContractError, match="close_alignment_invalid"):
        _inspect(
            [bad_close],
            expected_latest_close=cast(int, aligned["candle_close_time"]),
        )

    rows = _rows([0, 1])
    rows[1]["candle_id"] = rows[0]["candle_id"]
    with pytest.raises(FeatureWindowContractError, match="candle_ids_duplicate"):
        _inspect(rows)

    reversed_rows = list(reversed(_rows([0, 1])))
    with pytest.raises(FeatureWindowContractError, match="not_strictly_increasing"):
        _inspect(reversed_rows)


def test_symbol_and_timeframe_mixing_fail_closed() -> None:
    rows = _rows([0, 1])
    rows[1]["symbol"] = "ETHUSDT"
    with pytest.raises(FeatureWindowContractError, match="rows_symbol_mismatch"):
        _inspect(rows)

    rows = _rows([0, 1])
    rows[1]["timeframe"] = "5m"
    with pytest.raises(FeatureWindowContractError, match="rows_timeframe_mismatch"):
        _inspect(rows)


def test_input_list_is_snapshotted_and_results_are_frozen() -> None:
    rows = _rows([0, 1, 2])
    result = _inspect(rows)
    rows.clear()

    assert result.raw_row_count == 3
    assert result.selected_suffix_count == 3
    with pytest.raises(FrozenInstanceError):
        result.raw_row_count = 0
    with pytest.raises(FrozenInstanceError):
        result.selected_suffix_rows[0].candle_id = "0" * 24


def test_resource_row_cap_is_not_a_market_selection_threshold() -> None:
    rows: list[dict[str, Any]] = []
    row = _canonical_rest(0)
    for _ in range(MAX_OHLCV_CLOSED_ROWS + 1):
        rows.append(row)
    with pytest.raises(FeatureWindowContractError, match="row_count_invalid"):
        inspect_canonical_contiguous_suffix(
            rows,
            expected_symbol=SYMBOL,
            timeframe="1m",
            consumer_observed_at_ms=cast(int, row["available_at"]),
            expected_latest_finalized_close_time=cast(int, row["candle_close_time"]),
        )
