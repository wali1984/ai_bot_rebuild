from __future__ import annotations

import math
from dataclasses import replace

import pytest
from v2.backend.app.services.liquidation_surface import (
    CandleObservation,
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    OutcomeCalibration,
    SurfaceContractError,
    SurfaceRequest,
    build_liquidation_surface,
    isolated_liquidation_price,
)

VENUE = "binance_usdm"
SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
BASE_MS = 900_000
AS_OF_MS = BASE_MS + 1_000_000
GENERATED_AT_MS = AS_OF_MS + 100
CANDLE_SHA = "a" * 64
OI_SHA = "b" * 64
BRACKET_SHA = "c" * 64
CALIBRATION_SHA = "d" * 64
MARK_SHA = "e" * 64


def _candle(
    index: int,
    *,
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    taker_buy_share: float | None = 0.9,
) -> CandleObservation:
    open_time = BASE_MS + index * 300_000
    close_time = open_time + 299_999
    quote_volume = 10_000.0
    return CandleObservation(
        venue=VENUE,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        open_time_ms=open_time,
        close_time_ms=close_time,
        event_time_ms=close_time,
        ingested_at_ms=close_time + 10,
        available_at_ms=close_time + 20,
        is_final=True,
        open=open_price,
        high=high,
        low=low,
        close=close,
        quote_volume=quote_volume,
        taker_buy_quote_volume=(
            quote_volume * taker_buy_share if taker_buy_share is not None else None
        ),
        source_key=f"v2:market:ohlcv:{VENUE}:{SYMBOL}:{TIMEFRAME}",
        source_sha256=CANDLE_SHA,
    )


def _candles() -> tuple[CandleObservation, ...]:
    return (_candle(0), _candle(1), _candle(2))


def _open_interest(
    values: tuple[float, ...] = (100.0, 120.0, 140.0),
) -> tuple[OpenInterestObservation, ...]:
    rows: list[OpenInterestObservation] = []
    for index, value in enumerate(values):
        feature_cutoff = _candle(index).close_time_ms
        event_time = feature_cutoff + 100
        rows.append(
            OpenInterestObservation(
                venue=VENUE,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                feature_cutoff_ms=feature_cutoff,
                event_time_ms=event_time,
                ingested_at_ms=event_time + 10,
                available_at_ms=event_time + 20,
                is_final=True,
                value=value,
                unit="quote_notional",
                source_key=f"v2:coinank:open_interest:{VENUE}:{SYMBOL}:{TIMEFRAME}",
                source_sha256=OI_SHA,
            )
        )
    return tuple(rows)


def _mark_price(**overrides: object) -> MarkPriceObservation:
    values: dict[str, object] = {
        "venue": VENUE,
        "symbol": SYMBOL,
        "event_time_ms": AS_OF_MS - 100,
        "ingested_at_ms": AS_OF_MS - 90,
        "available_at_ms": AS_OF_MS - 80,
        "price": 100.0,
        "source_key": f"v2:market:funding:{VENUE}:{SYMBOL}",
        "source_sha256": MARK_SHA,
    }
    values.update(overrides)
    return MarkPriceObservation(**values)  # type: ignore[arg-type]


def _mark_prices() -> tuple[MarkPriceObservation, ...]:
    return (
        _mark_price(
            event_time_ms=AS_OF_MS - 1_000,
            ingested_at_ms=AS_OF_MS - 990,
            available_at_ms=AS_OF_MS - 980,
        ),
        _mark_price(),
    )


def _brackets() -> tuple[LeverageBracket, ...]:
    common = {
        "venue": VENUE,
        "symbol": SYMBOL,
        "fetched_at_ms": AS_OF_MS - 1_000,
        "ingested_at_ms": AS_OF_MS - 900,
        "available_at_ms": AS_OF_MS - 800,
        "expires_at_ms": AS_OF_MS + 600_000,
        "source_key": f"v2:binance_usdm:leverage_bracket:{SYMBOL}",
        "source_sha256": BRACKET_SHA,
    }
    return (
        LeverageBracket(
            **common,
            bracket_id=1,
            notional_floor=0.0,
            notional_cap=50_000.0,
            initial_leverage=20,
            maintenance_margin_rate=0.004,
            cumulative_maintenance_amount=0.0,
        ),
        LeverageBracket(
            **common,
            bracket_id=2,
            notional_floor=50_000.0,
            notional_cap=1_000_000_000.0,
            initial_leverage=10,
            maintenance_margin_rate=0.01,
            cumulative_maintenance_amount=300.0,
        ),
    )


def _calibration(**overrides: object) -> OutcomeCalibration:
    values: dict[str, object] = {
        "venue": VENUE,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "feature_cutoff_ms": _candle(1).close_time_ms,
        "ingested_at_ms": _candle(2).close_time_ms + 10,
        "available_at_ms": _candle(2).close_time_ms + 20,
        "leverage_weights": {2: 1.0, 20: 2.0},
        "source_key": f"v2:liquidation:outcome_calibration:{VENUE}:{SYMBOL}:{TIMEFRAME}",
        "source_sha256": CALIBRATION_SHA,
    }
    values.update(overrides)
    return OutcomeCalibration(**values)  # type: ignore[arg-type]


def _request(**overrides: object) -> SurfaceRequest:
    values: dict[str, object] = {
        "venue": VENUE,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "as_of_time_ms": AS_OF_MS,
        "generated_at_ms": GENERATED_AT_MS,
        "candles": _candles(),
        "mark_prices": _mark_prices(),
        "open_interest": _open_interest(),
        "leverage_brackets": _brackets(),
    }
    values.update(overrides)
    return SurfaceRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("side", "expected"),
    (
        ("long", 100.0 * (1.0 - 1.0 / 10.0) / (1.0 - 0.004)),
        ("short", 100.0 * (1.0 + 1.0 / 10.0) / (1.0 + 0.004)),
    ),
)
def test_isolated_liquidation_geometry(side: str, expected: float) -> None:
    assert isolated_liquidation_price(
        side=side,
        entry_price=100.0,
        leverage=10.0,
        maintenance_margin_rate=0.004,
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    (
        ({"side": "flat"}, "SIDE_NOT_LONG_OR_SHORT"),
        ({"entry_price": 0.0}, "ENTRY_PRICE_NOT_POSITIVE"),
        ({"leverage": 0.5}, "LEVERAGE_BELOW_ONE"),
        ({"maintenance_margin_rate": 1.0}, "MAINTENANCE_MARGIN_RATE_OUT_OF_RANGE"),
        ({"entry_price": math.nan}, "ENTRY_PRICE_NOT_FINITE"),
        ({"leverage": "10"}, "LEVERAGE_NOT_NUMERIC"),
    ),
)
def test_isolated_liquidation_geometry_rejects_invalid_inputs(
    kwargs: dict[str, object], error: str
) -> None:
    values: dict[str, object] = {
        "side": "long",
        "entry_price": 100.0,
        "leverage": 10.0,
        "maintenance_margin_rate": 0.004,
    }
    values.update(kwargs)
    with pytest.raises(SurfaceContractError, match=error):
        isolated_liquidation_price(**values)  # type: ignore[arg-type]


def test_valid_surface_is_prospective_but_requires_postcommit_receipt() -> None:
    payload = build_liquidation_surface(_request())

    assert payload["liquidation_semantic_kind"] == ("estimated_open_position_liquidation_surface")
    assert payload["venue"] == VENUE
    assert payload["symbol"] == SYMBOL
    assert payload["timeframe"] == TIMEFRAME
    assert payload["current_price"] == 100.0
    assert payload["current_price_source"] == "VENUE_MARK_PRICE"
    assert payload["mark_price_evidence_present"] is True
    assert payload["trainer_semantic_eligible"] is True
    assert payload["trainer_authority"] is False
    assert payload["trainer_authority_reason"] == "POSTCOMMIT_CONSUMER_RECEIPT_REQUIRED"
    assert payload["available_at"] is None
    assert payload["postcommit_receipt_bound"] is False
    assert payload["long_levels"]
    assert payload["short_levels"]
    assert all(row["price"] < payload["current_price"] for row in payload["long_levels"])
    assert all(row["price"] > payload["current_price"] for row in payload["short_levels"])
    assert payload["exchange_max_initial_leverage"] == 20
    assert payload["leverage_scenarios"] == list(range(2, 21))


def test_missing_brackets_emits_no_proxy_levels() -> None:
    payload = build_liquidation_surface(_request(leverage_brackets=()))

    assert payload["long_levels"] == []
    assert payload["short_levels"] == []
    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority_reason"] == "CURRENT_EXCHANGE_BRACKET_EVIDENCE_MISSING"
    assert payload["bracket_scenario_policy"] == "NO_BRACKET_PROXY_LEVELS_EMITTED"


def test_missing_open_interest_is_diagnostic_not_trainer_eligible() -> None:
    payload = build_liquidation_surface(_request(open_interest=()))

    assert payload["long_levels"]
    assert payload["short_levels"]
    assert payload["cohort_diagnostics"]["cohort_basis"] == (
        "quote_volume_proxy_no_positive_oi_delta"
    )
    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority_reason"] == ("POSITIVE_OPEN_INTEREST_COHORT_EVIDENCE_MISSING")


def test_missing_mark_price_uses_close_only_for_non_trainer_diagnostic() -> None:
    payload = build_liquidation_surface(_request(mark_prices=()))

    assert payload["current_price"] == _candles()[-1].close
    assert payload["current_price_source"] == "FINALIZED_CANDLE_CLOSE_FALLBACK"
    assert payload["mark_price_evidence_present"] is False
    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority_reason"] == "VENUE_MARK_PRICE_EVIDENCE_MISSING"


def test_aggregate_open_interest_is_matched_not_taker_flow_side_split() -> None:
    request = _request(
        candles=tuple(replace(row, taker_buy_quote_volume=10_000.0) for row in _candles())
    )
    payload = build_liquidation_surface(request)

    assert payload["cohort_diagnostics"]["aggregate_open_interest_directionality"] == (
        "MATCHED_LONG_AND_SHORT_NOT_SIDE_SPLIT"
    )
    assert sum(row["raw_weight"] for row in payload["long_levels"]) == pytest.approx(
        sum(row["raw_weight"] for row in payload["short_levels"])
    )


def test_no_positive_oi_delta_cannot_gain_trainer_eligibility_from_volume_proxy() -> None:
    payload = build_liquidation_surface(_request(open_interest=_open_interest((120.0, 120.0))))

    assert payload["cohort_diagnostics"]["positive_open_interest_delta_total"] == 0.0
    assert payload["trainer_semantic_eligible"] is False


def test_open_interest_reduction_is_reported_and_reduces_existing_cohorts() -> None:
    payload = build_liquidation_surface(
        _request(open_interest=_open_interest((100.0, 130.0, 117.0)))
    )

    diagnostics = payload["cohort_diagnostics"]
    assert diagnostics["positive_open_interest_delta_total"] == 30.0
    assert diagnostics["open_interest_reduction_event_count"] == 1
    assert diagnostics["current_open_interest"] == 117.0


def test_causal_outcome_calibration_is_lineage_bound() -> None:
    uncalibrated = build_liquidation_surface(_request())
    calibrated = build_liquidation_surface(_request(outcome_calibration=_calibration()))

    assert calibrated["calibration_cutoff"] == _calibration().feature_cutoff_ms
    expected_coverage = 2.0 / 19.0
    assert calibrated["quality_components"][
        "realized_outcome_calibration_coverage"
    ] == pytest.approx(expected_coverage)
    assert calibrated["scenario_distribution_uncertainty"] == pytest.approx(1.0 - expected_coverage)
    assert calibrated["source_input_sha256"] != uncalibrated["source_input_sha256"]


@pytest.mark.parametrize(
    ("overrides", "error"),
    (
        ({"venue": "coinank"}, "CALIBRATION_VENUE_MISMATCH"),
        ({"symbol": "ETHUSDT"}, "CALIBRATION_SYMBOL_MISMATCH"),
        ({"timeframe": "1h"}, "CALIBRATION_TIMEFRAME_MISMATCH"),
        ({"feature_cutoff_ms": AS_OF_MS + 1}, "CALIBRATION_CLOCK_ORDER_INVALID"),
        ({"available_at_ms": AS_OF_MS + 1}, "CALIBRATION_CLOCK_ORDER_INVALID"),
        ({"leverage_weights": {}}, "CALIBRATION_WEIGHTS_EMPTY"),
        ({"leverage_weights": {20: 0.0}}, "CALIBRATION_WEIGHT_NOT_POSITIVE"),
        ({"source_sha256": "bad"}, "CALIBRATION_SOURCE_SHA256_INVALID"),
    ),
)
def test_calibration_contract_fails_closed(overrides: dict[str, object], error: str) -> None:
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(outcome_calibration=_calibration(**overrides)))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("venue", "Binance_USDM", "REQUEST_VENUE_NOT_CANONICAL"),
        ("symbol", "btcusdt", "REQUEST_SYMBOL_NOT_CANONICAL"),
        ("timeframe", "5M", "REQUEST_TIMEFRAME_NOT_CANONICAL"),
        ("as_of_time_ms", 0, "AS_OF_TIME_MS_NOT_POSITIVE_INTEGER"),
        ("as_of_time_ms", 1.0, "AS_OF_TIME_MS_NOT_INTEGER"),
        ("generated_at_ms", AS_OF_MS - 1, "AS_OF_AFTER_GENERATED_AT"),
    ),
)
def test_request_identity_and_clock_contract(field: str, value: object, error: str) -> None:
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("venue", "other", "CANDLE_VENUE_MISMATCH"),
        ("symbol", "ETHUSDT", "CANDLE_SYMBOL_MISMATCH"),
        ("timeframe", "1h", "CANDLE_TIMEFRAME_MISMATCH"),
        ("event_time_ms", _candle(0).close_time_ms - 1, "CANDLE_CLOCK_ORDER_INVALID"),
        ("ingested_at_ms", _candle(0).event_time_ms - 1, "CANDLE_CLOCK_ORDER_INVALID"),
        ("available_at_ms", AS_OF_MS + 1, "CANDLE_CLOCK_ORDER_INVALID"),
        ("available_at_ms", 1.0, "CANDLE_CLOCK_NOT_INTEGER_MS"),
        ("source_key", "", "CANDLE_SOURCE_KEY_INVALID"),
        ("source_sha256", "A" * 64, "CANDLE_SOURCE_SHA256_INVALID"),
        ("is_final", False, "CANDLE_NOT_FINAL"),
        ("high", 98.0, "CANDLE_OHLC_GEOMETRY_INVALID"),
        ("quote_volume", -1.0, "CANDLE_QUOTE_VOLUME_NEGATIVE"),
        ("taker_buy_quote_volume", 10_001.0, "CANDLE_TAKER_BUY_EXCEEDS_QUOTE_VOLUME"),
    ),
)
def test_candle_contract_fails_closed(field: str, value: object, error: str) -> None:
    candles = list(_candles())
    candles[0] = replace(candles[0], **{field: value})
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(candles=tuple(candles)))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("venue", "other", "OPEN_INTEREST_VENUE_MISMATCH"),
        ("symbol", "ETHUSDT", "OPEN_INTEREST_SYMBOL_MISMATCH"),
        ("timeframe", "1h", "OPEN_INTEREST_TIMEFRAME_MISMATCH"),
        (
            "ingested_at_ms",
            _open_interest()[0].event_time_ms - 1,
            "OPEN_INTEREST_CLOCK_ORDER_INVALID",
        ),
        ("available_at_ms", AS_OF_MS + 1, "OPEN_INTEREST_CLOCK_ORDER_INVALID"),
        ("value", -1.0, "OPEN_INTEREST_VALUE_NEGATIVE"),
        ("value", math.inf, "OPEN_INTEREST_VALUE_NOT_FINITE"),
        ("unit", "usd", "OPEN_INTEREST_UNIT_UNRECOGNIZED"),
        ("source_key", "", "OPEN_INTEREST_SOURCE_KEY_INVALID"),
        ("source_sha256", "bad", "OPEN_INTEREST_SOURCE_SHA256_INVALID"),
        ("is_final", False, "OPEN_INTEREST_NOT_FINAL"),
    ),
)
def test_open_interest_contract_fails_closed(field: str, value: object, error: str) -> None:
    rows = list(_open_interest())
    rows[0] = replace(rows[0], **{field: value})
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(open_interest=tuple(rows)))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("venue", "other", "MARK_PRICE_VENUE_MISMATCH"),
        ("symbol", "ETHUSDT", "MARK_PRICE_SYMBOL_MISMATCH"),
        ("ingested_at_ms", AS_OF_MS - 101, "MARK_PRICE_CLOCK_ORDER_INVALID"),
        ("available_at_ms", AS_OF_MS + 1, "MARK_PRICE_CLOCK_ORDER_INVALID"),
        ("event_time_ms", 1.0, "MARK_PRICE_CLOCK_NOT_INTEGER_MS"),
        ("price", 0.0, "MARK_PRICE_NOT_POSITIVE"),
        ("price", math.nan, "MARK_PRICE_NOT_FINITE"),
        ("source_key", "", "MARK_PRICE_SOURCE_KEY_INVALID"),
        ("source_sha256", "bad", "MARK_PRICE_SOURCE_SHA256_INVALID"),
    ),
)
def test_mark_price_contract_fails_closed(field: str, value: object, error: str) -> None:
    rows = list(_mark_prices())
    rows[-1] = replace(rows[-1], **{field: value})
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(mark_prices=tuple(rows)))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("venue", "other", "BRACKET_VENUE_MISMATCH"),
        ("symbol", "ETHUSDT", "BRACKET_SYMBOL_MISMATCH"),
        ("available_at_ms", AS_OF_MS + 1, "BRACKET_CLOCK_ORDER_OR_FRESHNESS_INVALID"),
        ("expires_at_ms", GENERATED_AT_MS, "BRACKET_CLOCK_ORDER_OR_FRESHNESS_INVALID"),
        ("source_key", "", "BRACKET_SOURCE_KEY_INVALID"),
        ("source_sha256", "bad", "BRACKET_SOURCE_SHA256_INVALID"),
        ("maintenance_margin_rate", 1.0, "BRACKET_MMR_OUT_OF_RANGE"),
        ("cumulative_maintenance_amount", -1.0, "BRACKET_CUM_NEGATIVE"),
    ),
)
def test_bracket_contract_fails_closed(field: str, value: object, error: str) -> None:
    rows = list(_brackets())
    rows[0] = replace(rows[0], **{field: value})
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(leverage_brackets=tuple(rows)))


def test_mixed_open_interest_units_are_rejected() -> None:
    rows = list(_open_interest())
    rows[1] = replace(rows[1], unit="base_asset")
    with pytest.raises(SurfaceContractError, match="OPEN_INTEREST_UNIT_CHANGED_WITHIN_WINDOW"):
        build_liquidation_surface(_request(open_interest=tuple(rows)))


def test_duplicate_candle_and_open_interest_clocks_are_rejected() -> None:
    candles = (*_candles(), _candles()[0])
    with pytest.raises(SurfaceContractError, match="DUPLICATE_CANDLE_CLOSE_TIME"):
        build_liquidation_surface(_request(candles=candles))

    open_interest = (*_open_interest(), _open_interest()[0])
    with pytest.raises(SurfaceContractError, match="DUPLICATE_OPEN_INTEREST_FEATURE_CUTOFF"):
        build_liquidation_surface(_request(open_interest=open_interest))


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        ({"bracket_id": 3}, "BRACKET_SEQUENCE_NOT_CONTIGUOUS"),
        ({"notional_floor": 1.0}, "FIRST_BRACKET_FLOOR_NOT_ZERO"),
        ({"cumulative_maintenance_amount": 1.0}, "FIRST_BRACKET_CUM_NOT_ZERO"),
    ),
)
def test_first_bracket_canonical_contract(mutation: dict[str, object], error: str) -> None:
    rows = list(_brackets())
    rows[0] = replace(rows[0], **mutation)
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(leverage_brackets=tuple(rows)))


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        ({"notional_floor": 50_001.0}, "BRACKET_RANGES_NOT_CONTIGUOUS"),
        ({"initial_leverage": 21}, "INITIAL_LEVERAGE_INCREASES_WITH_NOTIONAL"),
        ({"maintenance_margin_rate": 0.003}, "MAINT_MARGIN_RATE_DECREASES_WITH_NOTIONAL"),
        ({"cumulative_maintenance_amount": 299.0}, "BRACKET_CUM_RECURRENCE_INVALID"),
    ),
)
def test_later_bracket_canonical_contract(mutation: dict[str, object], error: str) -> None:
    rows = list(_brackets())
    rows[1] = replace(rows[1], **mutation)
    with pytest.raises(SurfaceContractError, match=error):
        build_liquidation_surface(_request(leverage_brackets=tuple(rows)))


def test_brackets_from_multiple_snapshots_are_rejected() -> None:
    rows = list(_brackets())
    rows[1] = replace(rows[1], source_sha256="e" * 64)
    with pytest.raises(SurfaceContractError, match="BRACKETS_MIX_MULTIPLE_SOURCE_SNAPSHOTS"):
        build_liquidation_surface(_request(leverage_brackets=tuple(rows)))


def test_duplicate_bracket_ids_are_rejected() -> None:
    rows = list(_brackets())
    rows[1] = replace(rows[1], bracket_id=1)
    with pytest.raises(SurfaceContractError, match="DUPLICATE_BRACKET_ID"):
        build_liquidation_surface(_request(leverage_brackets=tuple(rows)))


def test_resource_bounds_are_integer_computation_limits_not_market_caps() -> None:
    payload = build_liquidation_surface(
        _request(max_cohorts=1, max_leverage_scenarios=3, max_levels_per_side=2)
    )

    assert payload["leverage_scenarios"][-1] == 20
    assert len(payload["leverage_scenarios"]) <= 3
    assert len(payload["long_levels"]) <= 2
    assert len(payload["short_levels"]) <= 2
    assert payload["resource_bounds"]["resource_bounds_are_market_thresholds"] is False
    assert payload["nearest_long_level"] in payload["long_levels"]
    assert payload["nearest_short_level"] in payload["short_levels"]


@pytest.mark.parametrize(
    "field",
    ("max_cohorts", "max_leverage_scenarios", "max_levels_per_side"),
)
def test_resource_bounds_reject_non_integer_values(field: str) -> None:
    with pytest.raises(SurfaceContractError, match="NOT_INTEGER"):
        build_liquidation_surface(_request(**{field: 2.0}))


def _global_weighted_leverage(levels: list[dict[str, object]]) -> float:
    total = sum(float(row["raw_weight"]) for row in levels)
    return sum(float(row["raw_weight"]) * float(row["weighted_leverage"]) for row in levels) / total


def test_scenario_weights_adapt_to_observed_adverse_excursions() -> None:
    calm = tuple(_candle(index, high=100.1, low=99.9) for index in range(3))
    volatile = tuple(_candle(index, high=130.0, low=70.0) for index in range(3))

    calm_payload = build_liquidation_surface(_request(candles=calm))
    volatile_payload = build_liquidation_surface(_request(candles=volatile))

    assert _global_weighted_leverage(volatile_payload["long_levels"]) < (
        _global_weighted_leverage(calm_payload["long_levels"])
    )


def test_source_hash_is_order_independent_but_changes_on_tamper() -> None:
    original = build_liquidation_surface(_request())
    reordered = build_liquidation_surface(
        _request(
            candles=tuple(reversed(_candles())),
            open_interest=tuple(reversed(_open_interest())),
        )
    )
    changed_candles = list(_candles())
    changed_candles[0] = replace(
        changed_candles[0],
        open=100.1,
        high=101.1,
        source_sha256="f" * 64,
    )
    changed = build_liquidation_surface(_request(candles=tuple(changed_candles)))

    assert original["source_input_sha256"] == reordered["source_input_sha256"]
    assert original["surface_payload_sha256"] == reordered["surface_payload_sha256"]
    assert original["source_input_sha256"] != changed["source_input_sha256"]


def test_output_clocks_include_every_causal_source_family() -> None:
    calibration = _calibration(
        feature_cutoff_ms=AS_OF_MS - 700,
        ingested_at_ms=AS_OF_MS - 600,
        available_at_ms=AS_OF_MS - 500,
    )
    mark_prices = (
        _mark_price(
            event_time_ms=AS_OF_MS - 2_000,
            ingested_at_ms=AS_OF_MS - 1_950,
            available_at_ms=AS_OF_MS - 1_900,
        ),
        _mark_price(
            event_time_ms=AS_OF_MS - 800,
            ingested_at_ms=AS_OF_MS - 750,
            available_at_ms=AS_OF_MS - 650,
        ),
    )
    payload = build_liquidation_surface(
        _request(outcome_calibration=calibration, mark_prices=mark_prices)
    )

    assert payload["feature_cutoff"] == AS_OF_MS - 700
    assert payload["ingested_at"] == AS_OF_MS - 600
    assert payload["source_available_at"] == AS_OF_MS - 500
    assert payload["surface_as_of"] == AS_OF_MS
    assert payload["generated_at"] == GENERATED_AT_MS
    assert payload["feature_cutoff"] <= payload["ingested_at"]
    assert payload["source_available_at"] <= payload["surface_as_of"]


def test_forced_liquidations_are_never_level_sources() -> None:
    payload = build_liquidation_surface(_request(outcome_calibration=_calibration()))

    assert payload["forced_liquidation_events_used_as_level_source"] is False
    assert payload["forced_liquidation_events_allowed_only_as_post_outcome_calibration"] is True
    assert "forced_liquidation_events" not in payload["source_input_counts"]
    assert payload["not_position_exact"] is True
    assert payload["cross_margin_position_exact"] is False


def test_recovered_long_level_does_not_reappear_after_historical_cross() -> None:
    candles = list(_candles())
    candles[2] = replace(candles[2], low=1.0)
    payload = build_liquidation_surface(
        _request(candles=tuple(candles), open_interest=_open_interest((100.0, 120.0)))
    )

    assert payload["current_price"] == 100.0
    assert payload["long_levels"] == []
    assert payload["historically_crossed_long_scenario_count"] > 0


def test_recovered_short_level_does_not_reappear_after_historical_cross() -> None:
    candles = list(_candles())
    candles[2] = replace(candles[2], high=200.0)
    payload = build_liquidation_surface(
        _request(candles=tuple(candles), open_interest=_open_interest((100.0, 120.0)))
    )

    assert payload["current_price"] == 100.0
    assert payload["short_levels"] == []
    assert payload["historically_crossed_short_scenario_count"] > 0


def test_pre_entry_excursion_does_not_kill_later_cohort() -> None:
    candles = list(_candles())
    candles[0] = replace(candles[0], high=200.0, low=1.0)
    payload = build_liquidation_surface(
        _request(candles=tuple(candles), open_interest=_open_interest((100.0, 120.0)))
    )

    assert payload["long_levels"]
    assert payload["short_levels"]
    assert payload["historically_crossed_long_scenario_count"] == 0
    assert payload["historically_crossed_short_scenario_count"] == 0


def test_oi_reduction_and_historical_cross_are_both_applied() -> None:
    candles = list(_candles())
    candles[2] = replace(candles[2], low=1.0)
    payload = build_liquidation_surface(
        _request(
            candles=tuple(candles),
            open_interest=_open_interest((100.0, 130.0, 117.0)),
        )
    )

    assert payload["cohort_diagnostics"]["open_interest_reduction_event_count"] == 1
    assert payload["long_levels"] == []
    assert payload["historically_crossed_long_scenario_count"] > 0


def test_adaptive_freshness_blocks_stale_candle_window() -> None:
    shifted_as_of = AS_OF_MS + 400_000
    payload = build_liquidation_surface(
        _request(
            as_of_time_ms=shifted_as_of,
            generated_at_ms=shifted_as_of + 100,
        )
    )

    assert payload["adaptive_freshness_evidence"]["candle"]["fresh"] is False
    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority_reason"] == "ADAPTIVE_SOURCE_FRESHNESS_FAILED"


def test_adaptive_freshness_blocks_stale_open_interest_only() -> None:
    payload = build_liquidation_surface(_request(open_interest=_open_interest((100.0, 120.0))))

    evidence = payload["adaptive_freshness_evidence"]
    assert evidence["candle"]["fresh"] is True
    assert evidence["mark_price"]["fresh"] is True
    assert evidence["open_interest"]["fresh"] is False
    assert payload["trainer_authority_reason"] == "ADAPTIVE_SOURCE_FRESHNESS_FAILED"


def test_adaptive_freshness_blocks_stale_mark_price_only() -> None:
    stale_marks = (
        _mark_price(
            event_time_ms=AS_OF_MS - 3_000,
            ingested_at_ms=AS_OF_MS - 2_990,
            available_at_ms=AS_OF_MS - 2_980,
        ),
        _mark_price(
            event_time_ms=AS_OF_MS - 2_000,
            ingested_at_ms=AS_OF_MS - 1_990,
            available_at_ms=AS_OF_MS - 1_980,
        ),
    )
    payload = build_liquidation_surface(_request(mark_prices=stale_marks))

    evidence = payload["adaptive_freshness_evidence"]
    assert evidence["candle"]["fresh"] is True
    assert evidence["open_interest"]["fresh"] is True
    assert evidence["mark_price"]["fresh"] is False
    assert payload["trainer_authority_reason"] == "ADAPTIVE_SOURCE_FRESHNESS_FAILED"


def test_candle_duration_must_match_declared_timeframe() -> None:
    candles = list(_candles())
    row = candles[0]
    candles[0] = replace(
        row,
        close_time_ms=row.close_time_ms + 1,
        event_time_ms=row.event_time_ms + 1,
        ingested_at_ms=row.ingested_at_ms + 1,
        available_at_ms=row.available_at_ms + 1,
    )
    with pytest.raises(SurfaceContractError, match="CANDLE_TIMEFRAME_DURATION_MISMATCH"):
        build_liquidation_surface(_request(candles=tuple(candles)))


def test_candle_boundary_and_sequence_are_exact() -> None:
    candles = list(_candles())
    row = candles[0]
    candles[0] = replace(
        row,
        open_time_ms=row.open_time_ms + 1,
        close_time_ms=row.close_time_ms + 1,
        event_time_ms=row.event_time_ms + 1,
        ingested_at_ms=row.ingested_at_ms + 1,
        available_at_ms=row.available_at_ms + 1,
    )
    with pytest.raises(SurfaceContractError, match="CANDLE_TIMEFRAME_BOUNDARY_MISMATCH"):
        build_liquidation_surface(_request(candles=tuple(candles)))


def test_missing_candle_period_is_rejected_as_sequence_gap() -> None:
    with pytest.raises(SurfaceContractError, match="CANDLE_SEQUENCE_GAP_OR_OVERLAP"):
        build_liquidation_surface(_request(candles=(_candles()[0], _candles()[2])))


def test_open_interest_boundary_is_exact() -> None:
    rows = list(_open_interest())
    row = rows[0]
    rows[0] = replace(
        row,
        feature_cutoff_ms=row.feature_cutoff_ms + 1,
        event_time_ms=row.event_time_ms + 1,
        ingested_at_ms=row.ingested_at_ms + 1,
        available_at_ms=row.available_at_ms + 1,
    )
    with pytest.raises(
        SurfaceContractError,
        match="OPEN_INTEREST_TIMEFRAME_BOUNDARY_MISMATCH|OPEN_INTEREST_SEQUENCE_GAP_OR_OVERLAP",
    ):
        build_liquidation_surface(_request(open_interest=tuple(rows)))


def test_one_minute_timeframe_uses_its_own_cadence() -> None:
    duration = 60_000
    as_of = BASE_MS + 200_000
    candles: list[CandleObservation] = []
    oi_rows: list[OpenInterestObservation] = []
    for index, value in enumerate((100.0, 120.0, 140.0)):
        open_time = BASE_MS + index * duration
        close_time = open_time + duration - 1
        candles.append(
            replace(
                _candle(index),
                timeframe="1m",
                open_time_ms=open_time,
                close_time_ms=close_time,
                event_time_ms=close_time,
                ingested_at_ms=close_time + 10,
                available_at_ms=close_time + 20,
            )
        )
        oi_rows.append(
            replace(
                _open_interest()[index],
                timeframe="1m",
                feature_cutoff_ms=close_time,
                event_time_ms=close_time + 100,
                ingested_at_ms=close_time + 110,
                available_at_ms=close_time + 120,
                value=value,
            )
        )
    marks = (
        _mark_price(
            event_time_ms=as_of - 1_000,
            ingested_at_ms=as_of - 990,
            available_at_ms=as_of - 980,
        ),
        _mark_price(
            event_time_ms=as_of - 100,
            ingested_at_ms=as_of - 90,
            available_at_ms=as_of - 80,
        ),
    )
    brackets = tuple(
        replace(
            row,
            fetched_at_ms=as_of - 1_000,
            ingested_at_ms=as_of - 900,
            available_at_ms=as_of - 800,
            expires_at_ms=as_of + 600_000,
        )
        for row in _brackets()
    )
    payload = build_liquidation_surface(
        _request(
            timeframe="1m",
            as_of_time_ms=as_of,
            generated_at_ms=as_of + 100,
            candles=tuple(candles),
            mark_prices=marks,
            open_interest=tuple(oi_rows),
            leverage_brackets=brackets,
        )
    )

    assert payload["trainer_semantic_eligible"] is True
    assert payload["adaptive_freshness_evidence"]["candle"]["budget_ms"] == 60_020
    assert payload["adaptive_freshness_evidence"]["open_interest"]["budget_ms"] == 60_120


def test_unknown_open_interest_unit_is_diagnostic_only() -> None:
    rows = tuple(replace(row, unit="unknown") for row in _open_interest())
    payload = build_liquidation_surface(_request(open_interest=rows))

    assert payload["long_levels"]
    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority_reason"] == "OPEN_INTEREST_UNIT_UNKNOWN"


def test_bracket_fetch_clock_is_part_of_feature_cutoff_and_full_ordering() -> None:
    brackets = tuple(
        replace(
            row,
            fetched_at_ms=AS_OF_MS - 30,
            ingested_at_ms=AS_OF_MS - 20,
            available_at_ms=AS_OF_MS - 10,
        )
        for row in _brackets()
    )
    payload = build_liquidation_surface(_request(leverage_brackets=brackets))

    assert payload["feature_cutoff"] == AS_OF_MS - 30
    assert payload["ingested_at"] == AS_OF_MS - 20
    assert payload["source_available_at"] == AS_OF_MS - 10
    assert payload["feature_cutoff"] <= payload["ingested_at"]
    assert payload["source_available_at"] <= payload["surface_as_of"]


def test_disjoint_calibration_leverages_fail_closed() -> None:
    calibration = _calibration(leverage_weights={100: 1.0})
    with pytest.raises(
        SurfaceContractError,
        match="CALIBRATION_NO_MODELED_LEVERAGE_OVERLAP",
    ):
        build_liquidation_surface(_request(outcome_calibration=calibration))


def test_full_calibration_has_zero_distribution_uncertainty() -> None:
    calibration = _calibration(leverage_weights={leverage: 1.0 for leverage in range(2, 21)})
    payload = build_liquidation_surface(_request(outcome_calibration=calibration))

    assert payload["quality_components"]["realized_outcome_calibration_coverage"] == 1.0
    assert payload["scenario_distribution_uncertainty"] == 0.0
    assert payload["calibration_unused_leverages"] == []


def test_unused_calibration_weights_are_excluded_from_confidence() -> None:
    calibration = _calibration(leverage_weights={2: 1.0, 100: 99.0})
    payload = build_liquidation_surface(_request(outcome_calibration=calibration))

    assert payload["calibration_applied_leverages"] == [2]
    assert payload["calibration_unused_leverages"] == [100]
    assert payload["quality_components"]["realized_outcome_calibration_coverage"] == pytest.approx(
        1.0 / 19.0
    )
    assert payload["scenario_distribution_uncertainty"] == pytest.approx(18.0 / 19.0)


def test_subnormal_tick_fails_with_contract_error() -> None:
    with pytest.raises(SurfaceContractError, match="BUCKET_INDEX_NOT_FINITE"):
        build_liquidation_surface(_request(tick_size=5e-324))


def test_calibration_weight_overflow_fails_with_contract_error() -> None:
    calibration = _calibration(leverage_weights={2: 1e308})
    with pytest.raises(SurfaceContractError, match="CANDIDATE_WEIGHT_NOT_FINITE"):
        build_liquidation_surface(_request(outcome_calibration=calibration))


def test_huge_exchange_leverage_fails_without_materializing_huge_range() -> None:
    brackets = list(_brackets())
    brackets[0] = replace(brackets[0], initial_leverage=10**400)
    with pytest.raises(SurfaceContractError, match="LEVERAGE_NOT_FINITE"):
        build_liquidation_surface(_request(leverage_brackets=tuple(brackets)))


def test_resource_hard_maximum_fails_closed() -> None:
    with pytest.raises(
        SurfaceContractError,
        match="MAX_COHORTS_EXCEEDS_HARD_RESOURCE_MAXIMUM",
    ):
        build_liquidation_surface(_request(max_cohorts=250_001))


def test_source_family_row_limit_fails_before_expansion() -> None:
    with pytest.raises(SurfaceContractError, match="SOURCE_FAMILY_ROW_LIMIT_EXCEEDED"):
        build_liquidation_surface(_request(max_source_rows_per_family=2))


def test_expanded_candidate_limit_fails_before_nested_generation() -> None:
    with pytest.raises(SurfaceContractError, match="EXPANDED_CANDIDATE_LIMIT_EXCEEDED"):
        build_liquidation_surface(_request(max_expanded_candidates=1))


def test_truncated_diagnostic_coverages_remain_probabilities() -> None:
    payload = build_liquidation_surface(_request(max_cohorts=1, max_levels_per_side=1))

    for value in payload["quality_components"].values():
        assert 0.0 <= value <= 1.0
    diagnostics = payload["cohort_diagnostics"]
    assert 0.0 <= diagnostics["aggressor_flow_metadata_coverage"] <= 1.0
    assert diagnostics["aggressor_flow_metadata_cohort_count"] <= diagnostics["cohort_count"]
