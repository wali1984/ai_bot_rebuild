"""Causal prospective liquidation-surface model.

The model reconstructs newly opened market-position cohorts from finalized
candles and point-in-time open-interest observations.  It then applies the
exchange isolated-margin liquidation equation across every represented
leverage/bracket scenario.  It never treats a forced-liquidation print as a
still-open liquidation level.

Market participants' exact entry price, leverage, position notional, wallet
balance, and margin mode are private.  Consequently the output is an
exchange-geometry market-cohort estimate, not an exchange-reported position
liquidation price.  The distinction is explicit in every payload.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import asdict
from decimal import Decimal
from typing import Any, cast

from .contracts import (
    CandleObservation,
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    OutcomeCalibration,
    SurfaceRequest,
)

MODEL_VERSION = "prospective_liquidation_surface_v1"
SCHEMA_VERSION = "v2_prospective_liquidation_surface_v1"
SEMANTIC_KIND = "estimated_open_position_liquidation_surface"

HARD_MAX_SOURCE_ROWS_PER_FAMILY = 250_000
HARD_MAX_COHORTS = 250_000
HARD_MAX_LEVERAGE_SCENARIOS = 512
HARD_MAX_LEVELS_PER_SIDE = 250_000
HARD_MAX_EXPANDED_CANDIDATES = 10_000_000

_TIMEFRAME_RE = re.compile(r"^([1-9][0-9]*)([smhdw])$")
_TIMEFRAME_UNIT_MS = {
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}


class SurfaceContractError(ValueError):
    """Raised when an immutable identity, clock, or numeric contract fails."""


def _timeframe_duration_ms(timeframe: str) -> int:
    matched = _TIMEFRAME_RE.fullmatch(timeframe)
    if matched is None:
        raise SurfaceContractError("REQUEST_TIMEFRAME_UNSUPPORTED")
    count_text = matched.group(1)
    if len(count_text) > 19:
        raise SurfaceContractError("REQUEST_TIMEFRAME_DURATION_OUTSIDE_SIGNED_64_BIT_MS")
    duration_ms = int(count_text) * _TIMEFRAME_UNIT_MS[matched.group(2)]
    if duration_ms > (1 << 63) - 1:
        raise SurfaceContractError("REQUEST_TIMEFRAME_DURATION_OUTSIDE_SIGNED_64_BIT_MS")
    return duration_ms


def _timeframe_alignment_offset_ms(timeframe: str) -> int:
    matched = _TIMEFRAME_RE.fullmatch(timeframe)
    if matched is None:
        raise SurfaceContractError("REQUEST_TIMEFRAME_UNSUPPORTED")
    # Unix epoch began on Thursday; Binance-style weekly periods begin Monday.
    return 345_600_000 if matched.group(2) == "w" else 0


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SurfaceContractError(f"{name}_NOT_NUMERIC")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise SurfaceContractError(f"{name}_NOT_FINITE") from exc
    if not math.isfinite(parsed):
        raise SurfaceContractError(f"{name}_NOT_FINITE")
    return parsed


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SurfaceContractError(f"{name}_NOT_INTEGER")
    parsed = value
    if parsed <= 0:
        raise SurfaceContractError(f"{name}_NOT_POSITIVE_INTEGER")
    return parsed


def _bounded_resource(value: Any, *, name: str, hard_maximum: int) -> int:
    parsed = _positive_int(value, name=name)
    if parsed > hard_maximum:
        raise SurfaceContractError(f"{name}_EXCEEDS_HARD_RESOURCE_MAXIMUM")
    return parsed


def _validate_lineage(*, source_key: Any, source_sha256: Any, name: str) -> None:
    if not isinstance(source_key, str) or not source_key or source_key.strip() != source_key:
        raise SurfaceContractError(f"{name}_SOURCE_KEY_INVALID")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or source_sha256.lower() != source_sha256
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise SurfaceContractError(f"{name}_SOURCE_SHA256_INVALID")


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def isolated_liquidation_price(
    *,
    side: str,
    entry_price: float,
    leverage: float,
    maintenance_margin_rate: float,
) -> float:
    """Return conservative isolated USD-M liquidation geometry.

    The exchange bracket ``cum`` amount is deliberately omitted.  For both
    longs and shorts, omitting a non-negative cumulative maintenance amount
    moves the modeled level toward entry, which is the conservative direction.
    The function is exact for the supplied entry/leverage/MMR under that
    documented isolated-margin assumption; it is not valid for cross margin.
    """

    normalized_side = str(side or "").strip().lower()
    if normalized_side not in {"long", "short"}:
        raise SurfaceContractError("SIDE_NOT_LONG_OR_SHORT")
    entry = _finite(entry_price, name="ENTRY_PRICE")
    lev = _finite(leverage, name="LEVERAGE")
    mmr = _finite(maintenance_margin_rate, name="MAINTENANCE_MARGIN_RATE")
    if entry <= 0.0:
        raise SurfaceContractError("ENTRY_PRICE_NOT_POSITIVE")
    if lev < 1.0:
        raise SurfaceContractError("LEVERAGE_BELOW_ONE")
    if not 0.0 <= mmr < 1.0:
        raise SurfaceContractError("MAINTENANCE_MARGIN_RATE_OUT_OF_RANGE")
    if normalized_side == "long":
        return max(0.0, entry * (1.0 - 1.0 / lev) / (1.0 - mmr))
    return entry * (1.0 + 1.0 / lev) / (1.0 + mmr)


def _validate_candle(
    candle: CandleObservation,
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    timeframe_duration_ms: int,
    timeframe_alignment_offset_ms: int,
    as_of_time_ms: int,
) -> None:
    if candle.venue != venue:
        raise SurfaceContractError("CANDLE_VENUE_MISMATCH")
    if candle.symbol != symbol:
        raise SurfaceContractError("CANDLE_SYMBOL_MISMATCH")
    if candle.timeframe != timeframe:
        raise SurfaceContractError("CANDLE_TIMEFRAME_MISMATCH")
    clocks = (
        candle.open_time_ms,
        candle.close_time_ms,
        candle.event_time_ms,
        candle.ingested_at_ms,
        candle.available_at_ms,
        as_of_time_ms,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in clocks):
        raise SurfaceContractError("CANDLE_CLOCK_NOT_INTEGER_MS")
    if not (
        candle.open_time_ms
        < candle.close_time_ms
        <= candle.event_time_ms
        <= candle.ingested_at_ms
        <= candle.available_at_ms
        <= as_of_time_ms
    ):
        raise SurfaceContractError("CANDLE_CLOCK_ORDER_INVALID")
    if candle.close_time_ms - candle.open_time_ms + 1 != timeframe_duration_ms:
        raise SurfaceContractError("CANDLE_TIMEFRAME_DURATION_MISMATCH")
    if (candle.open_time_ms - timeframe_alignment_offset_ms) % timeframe_duration_ms != 0:
        raise SurfaceContractError("CANDLE_TIMEFRAME_BOUNDARY_MISMATCH")
    if candle.is_final is not True:
        raise SurfaceContractError("CANDLE_NOT_FINAL")
    open_price = _finite(candle.open, name="CANDLE_OPEN")
    high = _finite(candle.high, name="CANDLE_HIGH")
    low = _finite(candle.low, name="CANDLE_LOW")
    close = _finite(candle.close, name="CANDLE_CLOSE")
    if min(open_price, high, low, close) <= 0.0:
        raise SurfaceContractError("CANDLE_PRICE_NOT_POSITIVE")
    if low > min(open_price, close) or high < max(open_price, close) or low > high:
        raise SurfaceContractError("CANDLE_OHLC_GEOMETRY_INVALID")
    quote_volume = (
        None
        if candle.quote_volume is None
        else _finite(candle.quote_volume, name="CANDLE_QUOTE_VOLUME")
    )
    taker_buy = (
        None
        if candle.taker_buy_quote_volume is None
        else _finite(candle.taker_buy_quote_volume, name="CANDLE_TAKER_BUY_QUOTE_VOLUME")
    )
    if quote_volume is not None and quote_volume < 0.0:
        raise SurfaceContractError("CANDLE_QUOTE_VOLUME_NEGATIVE")
    if taker_buy is not None and taker_buy < 0.0:
        raise SurfaceContractError("CANDLE_TAKER_BUY_QUOTE_VOLUME_NEGATIVE")
    if quote_volume is not None and taker_buy is not None and taker_buy > quote_volume:
        raise SurfaceContractError("CANDLE_TAKER_BUY_EXCEEDS_QUOTE_VOLUME")
    _validate_lineage(
        source_key=candle.source_key,
        source_sha256=candle.source_sha256,
        name="CANDLE",
    )


def _validate_oi(
    observation: OpenInterestObservation,
    *,
    venue: str,
    symbol: str,
    as_of_time_ms: int,
) -> None:
    if observation.venue != venue:
        raise SurfaceContractError("OPEN_INTEREST_VENUE_MISMATCH")
    if observation.symbol != symbol:
        raise SurfaceContractError("OPEN_INTEREST_SYMBOL_MISMATCH")
    canonical_timeframe = str(observation.timeframe or "").strip().lower()
    if canonical_timeframe != observation.timeframe or not canonical_timeframe:
        raise SurfaceContractError("OPEN_INTEREST_TIMEFRAME_NOT_CANONICAL")
    _timeframe_duration_ms(canonical_timeframe)
    if not (
        isinstance(observation.feature_cutoff_ms, int)
        and not isinstance(observation.feature_cutoff_ms, bool)
        and isinstance(observation.event_time_ms, int)
        and not isinstance(observation.event_time_ms, bool)
        and isinstance(observation.ingested_at_ms, int)
        and not isinstance(observation.ingested_at_ms, bool)
        and isinstance(observation.available_at_ms, int)
        and not isinstance(observation.available_at_ms, bool)
        and observation.feature_cutoff_ms
        <= observation.event_time_ms
        <= observation.ingested_at_ms
        <= observation.available_at_ms
        <= as_of_time_ms
    ):
        raise SurfaceContractError("OPEN_INTEREST_CLOCK_ORDER_INVALID")
    if observation.is_final is not True:
        raise SurfaceContractError("OPEN_INTEREST_NOT_FINAL")
    if _finite(observation.value, name="OPEN_INTEREST_VALUE") < 0.0:
        raise SurfaceContractError("OPEN_INTEREST_VALUE_NEGATIVE")
    if observation.unit not in {"base_asset", "quote_notional", "contracts", "unknown"}:
        raise SurfaceContractError("OPEN_INTEREST_UNIT_UNRECOGNIZED")
    _validate_lineage(
        source_key=observation.source_key,
        source_sha256=observation.source_sha256,
        name="OPEN_INTEREST",
    )


def _validate_mark_price(
    observation: MarkPriceObservation,
    *,
    venue: str,
    symbol: str,
    as_of_time_ms: int,
) -> None:
    if observation.venue != venue:
        raise SurfaceContractError("MARK_PRICE_VENUE_MISMATCH")
    if observation.symbol != symbol:
        raise SurfaceContractError("MARK_PRICE_SYMBOL_MISMATCH")
    clocks = (
        observation.event_time_ms,
        observation.ingested_at_ms,
        observation.available_at_ms,
        as_of_time_ms,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in clocks):
        raise SurfaceContractError("MARK_PRICE_CLOCK_NOT_INTEGER_MS")
    if not (
        observation.event_time_ms
        <= observation.ingested_at_ms
        <= observation.available_at_ms
        <= as_of_time_ms
    ):
        raise SurfaceContractError("MARK_PRICE_CLOCK_ORDER_INVALID")
    if _finite(observation.price, name="MARK_PRICE") <= 0.0:
        raise SurfaceContractError("MARK_PRICE_NOT_POSITIVE")
    _validate_lineage(
        source_key=observation.source_key,
        source_sha256=observation.source_sha256,
        name="MARK_PRICE",
    )


def _validate_bracket(
    bracket: LeverageBracket,
    *,
    venue: str,
    symbol: str,
    as_of_time_ms: int,
    generated_at_ms: int,
) -> None:
    if bracket.venue != venue:
        raise SurfaceContractError("BRACKET_VENUE_MISMATCH")
    if bracket.symbol != symbol:
        raise SurfaceContractError("BRACKET_SYMBOL_MISMATCH")
    clocks = (
        bracket.fetched_at_ms,
        bracket.ingested_at_ms,
        bracket.available_at_ms,
        as_of_time_ms,
        generated_at_ms,
        bracket.expires_at_ms,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in clocks):
        raise SurfaceContractError("BRACKET_CLOCK_NOT_INTEGER_MS")
    if not (
        bracket.fetched_at_ms
        <= bracket.ingested_at_ms
        <= bracket.available_at_ms
        <= as_of_time_ms
        <= generated_at_ms
        < bracket.expires_at_ms
    ):
        raise SurfaceContractError("BRACKET_CLOCK_ORDER_OR_FRESHNESS_INVALID")
    _positive_int(bracket.bracket_id, name="BRACKET_ID")
    _positive_int(bracket.initial_leverage, name="BRACKET_INITIAL_LEVERAGE")
    floor = _finite(bracket.notional_floor, name="BRACKET_NOTIONAL_FLOOR")
    cap = _finite(bracket.notional_cap, name="BRACKET_NOTIONAL_CAP")
    mmr = _finite(bracket.maintenance_margin_rate, name="BRACKET_MMR")
    cum = _finite(
        bracket.cumulative_maintenance_amount,
        name="BRACKET_CUMULATIVE_MAINTENANCE_AMOUNT",
    )
    if floor < 0.0 or cap <= floor:
        raise SurfaceContractError("BRACKET_NOTIONAL_RANGE_INVALID")
    if not 0.0 <= mmr < 1.0:
        raise SurfaceContractError("BRACKET_MMR_OUT_OF_RANGE")
    if cum < 0.0:
        raise SurfaceContractError("BRACKET_CUM_NEGATIVE")
    _validate_lineage(
        source_key=bracket.source_key,
        source_sha256=bracket.source_sha256,
        name="BRACKET",
    )


def _validate_calibration(
    calibration: OutcomeCalibration,
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    as_of_time_ms: int,
) -> dict[int, float]:
    if calibration.venue != venue:
        raise SurfaceContractError("CALIBRATION_VENUE_MISMATCH")
    if calibration.symbol != symbol:
        raise SurfaceContractError("CALIBRATION_SYMBOL_MISMATCH")
    if calibration.timeframe != timeframe:
        raise SurfaceContractError("CALIBRATION_TIMEFRAME_MISMATCH")
    clocks = (
        calibration.feature_cutoff_ms,
        calibration.ingested_at_ms,
        calibration.available_at_ms,
        as_of_time_ms,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in clocks):
        raise SurfaceContractError("CALIBRATION_CLOCK_NOT_INTEGER_MS")
    if not (
        calibration.feature_cutoff_ms
        <= calibration.ingested_at_ms
        <= calibration.available_at_ms
        <= as_of_time_ms
    ):
        raise SurfaceContractError("CALIBRATION_CLOCK_ORDER_INVALID")
    _validate_lineage(
        source_key=calibration.source_key,
        source_sha256=calibration.source_sha256,
        name="CALIBRATION",
    )
    weights: dict[int, float] = {}
    for raw_leverage, raw_weight in calibration.leverage_weights.items():
        leverage = _positive_int(raw_leverage, name="CALIBRATION_LEVERAGE")
        weight = _finite(raw_weight, name="CALIBRATION_WEIGHT")
        if weight <= 0.0:
            raise SurfaceContractError("CALIBRATION_WEIGHT_NOT_POSITIVE")
        weights[leverage] = weight
    if not weights:
        raise SurfaceContractError("CALIBRATION_WEIGHTS_EMPTY")
    return weights


def _dedupe_sorted_candles(candles: Iterable[CandleObservation]) -> list[CandleObservation]:
    by_close: dict[int, CandleObservation] = {}
    for candle in candles:
        if candle.close_time_ms in by_close:
            raise SurfaceContractError("DUPLICATE_CANDLE_CLOSE_TIME")
        by_close[candle.close_time_ms] = candle
    return [by_close[key] for key in sorted(by_close)]


def _dedupe_sorted_oi(
    observations: Iterable[OpenInterestObservation],
) -> list[OpenInterestObservation]:
    by_cutoff: dict[int, OpenInterestObservation] = {}
    for observation in observations:
        if observation.feature_cutoff_ms in by_cutoff:
            raise SurfaceContractError("DUPLICATE_OPEN_INTEREST_FEATURE_CUTOFF")
        by_cutoff[observation.feature_cutoff_ms] = observation
    return [by_cutoff[key] for key in sorted(by_cutoff)]


def _dedupe_sorted_marks(
    observations: Iterable[MarkPriceObservation],
) -> list[MarkPriceObservation]:
    by_event: dict[int, MarkPriceObservation] = {}
    for observation in observations:
        if observation.event_time_ms in by_event:
            raise SurfaceContractError("DUPLICATE_MARK_PRICE_EVENT_TIME")
        by_event[observation.event_time_ms] = observation
    return [by_event[key] for key in sorted(by_event)]


def _validate_period_sequences(
    *,
    candles: list[CandleObservation],
    open_interest: list[OpenInterestObservation],
    candle_timeframe_duration_ms: int,
    oi_timeframe_duration_ms: int,
    oi_timeframe_alignment_offset_ms: int,
) -> None:
    for left, right in zip(candles, candles[1:], strict=False):
        if (
            right.open_time_ms - left.open_time_ms != candle_timeframe_duration_ms
            or right.close_time_ms - left.close_time_ms != candle_timeframe_duration_ms
        ):
            raise SurfaceContractError("CANDLE_SEQUENCE_GAP_OR_OVERLAP")
    for left, right in zip(open_interest, open_interest[1:], strict=False):
        if right.feature_cutoff_ms - left.feature_cutoff_ms != oi_timeframe_duration_ms:
            raise SurfaceContractError("OPEN_INTEREST_SEQUENCE_GAP_OR_OVERLAP")
    for observation in open_interest:
        if (
            observation.feature_cutoff_ms - oi_timeframe_alignment_offset_ms
        ) % oi_timeframe_duration_ms != 0:
            raise SurfaceContractError("OPEN_INTEREST_TIMEFRAME_BOUNDARY_MISMATCH")


def _adaptive_freshness_evidence(
    *,
    candles: list[CandleObservation],
    open_interest: list[OpenInterestObservation],
    mark_prices: list[MarkPriceObservation],
    timeframe_duration_ms: int,
    as_of_time_ms: int,
) -> dict[str, Any]:
    candle_age = as_of_time_ms - candles[-1].close_time_ms
    candle_lag = max(row.available_at_ms - row.close_time_ms for row in candles)
    candle_budget = timeframe_duration_ms + candle_lag
    candle_fresh = len(candles) >= 2 and candle_age <= candle_budget

    oi_age: int | None = None
    oi_budget: int | None = None
    oi_fresh = False
    if open_interest:
        oi_age = as_of_time_ms - open_interest[-1].feature_cutoff_ms
    if len(open_interest) >= 2:
        oi_cadence = max(
            right.feature_cutoff_ms - left.feature_cutoff_ms
            for left, right in zip(open_interest, open_interest[1:], strict=False)
        )
        oi_lag = max(row.available_at_ms - row.feature_cutoff_ms for row in open_interest)
        oi_budget = oi_cadence + oi_lag
        oi_fresh = oi_age is not None and oi_age <= oi_budget

    mark_age: int | None = None
    mark_budget: int | None = None
    mark_fresh = False
    if mark_prices:
        mark_age = as_of_time_ms - mark_prices[-1].event_time_ms
    if len(mark_prices) >= 2:
        mark_cadence = max(
            right.event_time_ms - left.event_time_ms
            for left, right in zip(mark_prices, mark_prices[1:], strict=False)
        )
        mark_lag = max(row.available_at_ms - row.event_time_ms for row in mark_prices)
        mark_budget = mark_cadence + mark_lag
        mark_fresh = mark_age is not None and mark_age <= mark_budget

    return {
        "method": "OBSERVED_CADENCE_PLUS_MAX_CAUSAL_PUBLICATION_LAG",
        "static_market_threshold_used": False,
        "candle": {"age_ms": candle_age, "budget_ms": candle_budget, "fresh": candle_fresh},
        "open_interest": {"age_ms": oi_age, "budget_ms": oi_budget, "fresh": oi_fresh},
        "mark_price": {"age_ms": mark_age, "budget_ms": mark_budget, "fresh": mark_fresh},
        "all_required_sources_fresh": candle_fresh and oi_fresh and mark_fresh,
    }


def _candle_entry_price(candle: CandleObservation) -> float:
    return (candle.open + candle.high + candle.low + candle.close) / 4.0


def _aggressor_buy_share(candle: CandleObservation) -> tuple[float | None, str]:
    quote_volume = candle.quote_volume
    taker_buy = candle.taker_buy_quote_volume
    if (
        quote_volume is not None
        and quote_volume > 0.0
        and taker_buy is not None
        and 0.0 <= taker_buy <= quote_volume
    ):
        return taker_buy / quote_volume, "taker_buy_quote_share_observed"
    return None, "taker_flow_unavailable"


def _latest_candle_not_after(
    candles: list[CandleObservation], event_time_ms: int
) -> CandleObservation | None:
    selected: CandleObservation | None = None
    for candle in candles:
        if candle.close_time_ms > event_time_ms:
            break
        selected = candle
    return selected


def _build_cohorts(
    *,
    candles: list[CandleObservation],
    open_interest: list[OpenInterestObservation],
    max_cohorts: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cohorts: list[dict[str, Any]] = []
    opened_oi = 0.0
    reductions = 0
    flow_backed = 0
    previous: OpenInterestObservation | None = None
    for observation in open_interest:
        if previous is None:
            previous = observation
            continue
        delta = observation.value - previous.value
        if delta < 0.0 and previous.value > 0.0:
            retained_fraction = max(0.0, min(1.0, observation.value / previous.value))
            for cohort in cohorts:
                cohort["long_weight"] *= retained_fraction
                cohort["short_weight"] *= retained_fraction
            reductions += 1
        elif delta > 0.0:
            candle = _latest_candle_not_after(candles, observation.feature_cutoff_ms)
            if candle is not None:
                aggressor_buy_share, flow_basis = _aggressor_buy_share(candle)
                if aggressor_buy_share is not None:
                    flow_backed += 1
                cohorts.append(
                    {
                        "entry_price": _candle_entry_price(candle),
                        "entry_time_ms": candle.close_time_ms,
                        # Aggregate open interest is matched long and short
                        # exposure regardless of whether the source unit is
                        # base asset, quote notional, or contracts. Taker flow
                        # describes the aggressor; it cannot turn aggregate OI
                        # into directional inventory.
                        "long_weight": delta,
                        "short_weight": delta,
                        "aggressor_buy_share": aggressor_buy_share,
                        "flow_basis": flow_basis,
                        "cohort_basis": "positive_open_interest_delta",
                    }
                )
                opened_oi += delta
        previous = observation

    if not cohorts:
        for candle in candles:
            weight = candle.quote_volume if candle.quote_volume is not None else 0.0
            if weight <= 0.0:
                weight = 1.0
            aggressor_buy_share, flow_basis = _aggressor_buy_share(candle)
            if aggressor_buy_share is not None:
                flow_backed += 1
            cohorts.append(
                {
                    "entry_price": _candle_entry_price(candle),
                    "entry_time_ms": candle.close_time_ms,
                    "long_weight": weight,
                    "short_weight": weight,
                    "aggressor_buy_share": aggressor_buy_share,
                    "flow_basis": flow_basis,
                    "cohort_basis": "quote_volume_proxy_no_positive_oi_delta",
                }
            )

    cohorts = [
        cohort for cohort in cohorts if cohort["long_weight"] > 0.0 or cohort["short_weight"] > 0.0
    ]
    cohorts.sort(key=lambda row: int(row["entry_time_ms"]))
    if len(cohorts) > max_cohorts:
        cohorts = cohorts[-max_cohorts:]
    flow_backed = sum(1 for cohort in cohorts if cohort.get("aggressor_buy_share") is not None)
    retained_modeled_open_interest = sum(
        float(cohort["long_weight"])
        for cohort in cohorts
        if cohort.get("cohort_basis") == "positive_open_interest_delta"
    )
    current_oi = open_interest[-1].value if open_interest else None
    oi_coverage = (
        min(1.0, retained_modeled_open_interest / current_oi)
        if current_oi is not None and current_oi > 0.0
        else 0.0
    )
    return cohorts, {
        "cohort_count": len(cohorts),
        "positive_open_interest_delta_total": opened_oi,
        "retained_modeled_open_interest": retained_modeled_open_interest,
        "current_open_interest": current_oi,
        "open_interest_new_cohort_coverage": oi_coverage,
        "open_interest_reduction_event_count": reductions,
        "aggressor_flow_metadata_cohort_count": flow_backed,
        "aggressor_flow_metadata_coverage": flow_backed / len(cohorts) if cohorts else 0.0,
        "aggregate_open_interest_directionality": "MATCHED_LONG_AND_SHORT_NOT_SIDE_SPLIT",
        "cohort_basis": (
            "positive_open_interest_delta"
            if opened_oi > 0.0
            else "quote_volume_proxy_no_positive_oi_delta"
        ),
    }


def _scenario_leverages(max_leverage: int, max_scenarios: int) -> list[int]:
    if max_leverage < 2:
        return []
    scenario_count = max_leverage - 1
    if scenario_count <= max_scenarios:
        return list(range(2, max_leverage + 1))
    if max_scenarios == 1:
        return [max_leverage]
    denominator = max_scenarios - 1
    span = max_leverage - 2
    selected = {
        2 + (index * span + denominator // 2) // denominator for index in range(max_scenarios)
    }
    return sorted(selected)


def _adverse_excursions(candles: Iterable[CandleObservation], *, side: str) -> list[float]:
    values: list[float] = []
    for candle in candles:
        if side == "long":
            values.append(max(0.0, (candle.open - candle.low) / candle.open))
        else:
            values.append(max(0.0, (candle.high - candle.open) / candle.open))
    return values


def _scenario_survived_since_entry(
    *,
    candles: Iterable[CandleObservation],
    entry_time_ms: int,
    side: str,
    liquidation_price: float,
) -> bool:
    for candle in candles:
        # The cohort entry proxy is the finalized close. Intraperiod extremes
        # from that same candle happened before the modeled entry and cannot
        # liquidate the newly created cohort.
        if candle.close_time_ms <= entry_time_ms:
            continue
        if side == "long" and candle.low <= liquidation_price:
            return False
        if side == "short" and candle.high >= liquidation_price:
            return False
    return True


def _empirical_scenario_weight(
    *,
    liquidation_distance: float,
    adverse_excursions: list[float],
    calibration_weight: float,
) -> float:
    survived = sum(1 for excursion in adverse_excursions if excursion < liquidation_distance)
    # Add-one smoothing is mathematical finite-sample regularization, not a
    # market threshold. Leverage starts with an equal non-probabilistic prior;
    # empirical survival and causal realized-outcome calibration adapt it.
    survival_probability = (survived + 1.0) / (len(adverse_excursions) + 2.0)
    return survival_probability * calibration_weight


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise SurfaceContractError("PERCENTILE_EMPTY")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] * (1.0 - ratio) + ordered[upper] * ratio


def _adaptive_bucket_width(prices: list[float], tick_size: float | None) -> float | None:
    if tick_size is not None:
        parsed_tick = _finite(tick_size, name="TICK_SIZE")
        if parsed_tick <= 0.0:
            raise SurfaceContractError("TICK_SIZE_NOT_POSITIVE")
        return parsed_tick
    if len(prices) < 2:
        return None
    iqr = _percentile(prices, 0.75) - _percentile(prices, 0.25)
    if iqr > 0.0:
        width = 2.0 * iqr / (len(prices) ** (1.0 / 3.0))
        if width > 0.0 and math.isfinite(width):
            return width
    gaps = [
        right - left
        for left, right in zip(sorted(set(prices)), sorted(set(prices))[1:], strict=False)
        if right > left
    ]
    return statistics.median(gaps) if gaps else None


def _aggregate_levels(
    candidates: list[dict[str, Any]],
    *,
    current_price: float,
    side: str,
    tick_size: float | None,
    max_levels: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, float]:
    valid: list[dict[str, Any]] = []
    crossed = 0
    for candidate in candidates:
        price = float(candidate["price"])
        correct_side = price < current_price if side == "long" else price > current_price
        if price <= 0.0 or not correct_side:
            crossed += 1
            continue
        valid.append(candidate)
    if not valid:
        return [], None, crossed, 0.0
    width = _adaptive_bucket_width([float(row["price"]) for row in valid], tick_size)
    buckets: dict[Any, dict[str, Any]] = {}
    for row in valid:
        price = float(row["price"])
        if width is not None:
            bucket_ratio = price / width
            if not math.isfinite(bucket_ratio):
                raise SurfaceContractError("BUCKET_INDEX_NOT_FINITE")
            bucket_id: Any = round(bucket_ratio)
        else:
            bucket_id = round(price, 12)
        bucket = buckets.setdefault(
            bucket_id,
            {
                "weighted_price": 0.0,
                "weight": 0.0,
                "scenario_count": 0,
                "leverage_weighted": 0.0,
                "min_leverage": int(row["leverage"]),
                "max_leverage": int(row["leverage"]),
                "maintenance_margin_rates": set(),
                "bracket_ids": set(),
            },
        )
        weight = _finite(row["weight"], name="SCENARIO_WEIGHT")
        if weight <= 0.0:
            raise SurfaceContractError("SCENARIO_WEIGHT_NOT_POSITIVE")
        bucket["weighted_price"] = _finite(
            bucket["weighted_price"] + price * weight,
            name="BUCKET_WEIGHTED_PRICE",
        )
        bucket["weight"] = _finite(
            bucket["weight"] + weight,
            name="BUCKET_WEIGHT",
        )
        bucket["scenario_count"] += 1
        bucket["leverage_weighted"] = _finite(
            bucket["leverage_weighted"] + int(row["leverage"]) * weight,
            name="BUCKET_LEVERAGE_WEIGHT",
        )
        bucket["min_leverage"] = min(bucket["min_leverage"], int(row["leverage"]))
        bucket["max_leverage"] = max(bucket["max_leverage"], int(row["leverage"]))
        bucket["maintenance_margin_rates"].add(float(row["maintenance_margin_rate"]))
        bucket["bracket_ids"].add(int(row["bracket_id"]))
    total_weight = _finite(
        sum(float(bucket["weight"]) for bucket in buckets.values()),
        name="TOTAL_SCENARIO_WEIGHT",
    )
    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        weight = float(bucket["weight"])
        price = float(bucket["weighted_price"]) / weight
        rows.append(
            {
                "price": price,
                "distance_bps": abs(price - current_price) / current_price * 10_000.0,
                "normalized_strength": weight / total_weight,
                "raw_weight": weight,
                "scenario_count": int(bucket["scenario_count"]),
                "weighted_leverage": float(bucket["leverage_weighted"]) / weight,
                "min_leverage": int(bucket["min_leverage"]),
                "max_leverage": int(bucket["max_leverage"]),
                "maintenance_margin_rates": sorted(bucket["maintenance_margin_rates"]),
                "bracket_ids": sorted(bucket["bracket_ids"]),
            }
        )
    nearest = min(rows, key=lambda row: float(row["distance_bps"]))
    if len(rows) > max_levels:
        strongest_others = sorted(
            (row for row in rows if row is not nearest),
            key=lambda row: (-float(row["normalized_strength"]), float(row["distance_bps"])),
        )[: max_levels - 1]
        rows = [nearest, *strongest_others]
    retained_mass = sum(float(row["raw_weight"]) for row in rows) / total_weight
    rows.sort(key=lambda row: float(row["price"]), reverse=side == "long")
    return rows, dict(nearest), crossed, retained_mass


def _source_material(request: SurfaceRequest) -> dict[str, Any]:
    return {
        "venue": request.venue,
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "as_of_time_ms": request.as_of_time_ms,
        "generated_at_ms": request.generated_at_ms,
        "candles": [
            asdict(row) for row in sorted(request.candles, key=lambda row: row.close_time_ms)
        ],
        "mark_prices": [
            asdict(row) for row in sorted(request.mark_prices, key=lambda row: row.event_time_ms)
        ],
        "open_interest": [
            asdict(row)
            for row in sorted(
                request.open_interest,
                key=lambda row: row.feature_cutoff_ms,
            )
        ],
        "leverage_brackets": [
            asdict(row)
            for row in sorted(
                request.leverage_brackets,
                key=lambda row: (row.notional_floor, row.bracket_id),
            )
        ],
        "outcome_calibration": (
            asdict(request.outcome_calibration) if request.outcome_calibration is not None else None
        ),
        "tick_size": request.tick_size,
        "max_cohorts": request.max_cohorts,
        "max_leverage_scenarios": request.max_leverage_scenarios,
        "max_levels_per_side": request.max_levels_per_side,
        "max_source_rows_per_family": request.max_source_rows_per_family,
        "max_expanded_candidates": request.max_expanded_candidates,
    }


def build_liquidation_surface(request: SurfaceRequest) -> dict[str, Any]:
    """Build a prospective symbol/timeframe liquidation surface.

    Invalid identity, clock, finality proxy, or numeric evidence raises and is
    expected to be quarantined by the producer. Missing optional market inputs
    yield a degraded, non-authoritative surface instead of fabricated fields.
    """

    venue = str(request.venue or "").strip().lower()
    symbol = str(request.symbol or "").strip().upper()
    timeframe = str(request.timeframe or "").strip().lower()
    if venue != request.venue or not venue:
        raise SurfaceContractError("REQUEST_VENUE_NOT_CANONICAL")
    if symbol != request.symbol or not symbol:
        raise SurfaceContractError("REQUEST_SYMBOL_NOT_CANONICAL")
    if timeframe != request.timeframe or not timeframe:
        raise SurfaceContractError("REQUEST_TIMEFRAME_NOT_CANONICAL")
    timeframe_duration_ms = _timeframe_duration_ms(timeframe)
    timeframe_alignment_offset_ms = _timeframe_alignment_offset_ms(timeframe)
    as_of_time_ms = _positive_int(request.as_of_time_ms, name="AS_OF_TIME_MS")
    generated_at_ms = _positive_int(request.generated_at_ms, name="GENERATED_AT_MS")
    if as_of_time_ms > generated_at_ms:
        raise SurfaceContractError("AS_OF_AFTER_GENERATED_AT")
    max_cohorts = _bounded_resource(
        request.max_cohorts,
        name="MAX_COHORTS",
        hard_maximum=HARD_MAX_COHORTS,
    )
    max_scenarios = _bounded_resource(
        request.max_leverage_scenarios,
        name="MAX_LEVERAGE_SCENARIOS",
        hard_maximum=HARD_MAX_LEVERAGE_SCENARIOS,
    )
    max_levels = _bounded_resource(
        request.max_levels_per_side,
        name="MAX_LEVELS_PER_SIDE",
        hard_maximum=HARD_MAX_LEVELS_PER_SIDE,
    )
    max_source_rows = _bounded_resource(
        request.max_source_rows_per_family,
        name="MAX_SOURCE_ROWS_PER_FAMILY",
        hard_maximum=HARD_MAX_SOURCE_ROWS_PER_FAMILY,
    )
    max_expanded_candidates = _bounded_resource(
        request.max_expanded_candidates,
        name="MAX_EXPANDED_CANDIDATES",
        hard_maximum=HARD_MAX_EXPANDED_CANDIDATES,
    )
    source_counts = {
        "candles": len(request.candles),
        "mark_prices": len(request.mark_prices),
        "open_interest": len(request.open_interest),
        "leverage_brackets": len(request.leverage_brackets),
    }
    if any(count > max_source_rows for count in source_counts.values()):
        raise SurfaceContractError("SOURCE_FAMILY_ROW_LIMIT_EXCEEDED")
    if not request.candles:
        raise SurfaceContractError("FINALIZED_CANDLES_MISSING")
    for candle in request.candles:
        _validate_candle(
            candle,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            timeframe_duration_ms=timeframe_duration_ms,
            timeframe_alignment_offset_ms=timeframe_alignment_offset_ms,
            as_of_time_ms=as_of_time_ms,
        )
    candles = _dedupe_sorted_candles(request.candles)
    for mark_price in request.mark_prices:
        _validate_mark_price(
            mark_price,
            venue=venue,
            symbol=symbol,
            as_of_time_ms=as_of_time_ms,
        )
    mark_prices = _dedupe_sorted_marks(request.mark_prices)
    for observation in request.open_interest:
        _validate_oi(
            observation,
            venue=venue,
            symbol=symbol,
            as_of_time_ms=as_of_time_ms,
        )
    open_interest = _dedupe_sorted_oi(request.open_interest)
    oi_source_timeframes = {row.timeframe for row in open_interest}
    if len(oi_source_timeframes) > 1:
        raise SurfaceContractError("OPEN_INTEREST_TIMEFRAME_CHANGED_WITHIN_WINDOW")
    oi_source_timeframe = next(iter(oi_source_timeframes)) if oi_source_timeframes else None
    oi_timeframe_duration_ms = (
        _timeframe_duration_ms(oi_source_timeframe)
        if oi_source_timeframe is not None
        else timeframe_duration_ms
    )
    oi_timeframe_alignment_offset_ms = (
        _timeframe_alignment_offset_ms(oi_source_timeframe)
        if oi_source_timeframe is not None
        else timeframe_alignment_offset_ms
    )
    if len({row.unit for row in open_interest}) > 1:
        raise SurfaceContractError("OPEN_INTEREST_UNIT_CHANGED_WITHIN_WINDOW")
    _validate_period_sequences(
        candles=candles,
        open_interest=open_interest,
        candle_timeframe_duration_ms=timeframe_duration_ms,
        oi_timeframe_duration_ms=oi_timeframe_duration_ms,
        oi_timeframe_alignment_offset_ms=oi_timeframe_alignment_offset_ms,
    )
    for bracket in request.leverage_brackets:
        _validate_bracket(
            bracket,
            venue=venue,
            symbol=symbol,
            as_of_time_ms=as_of_time_ms,
            generated_at_ms=generated_at_ms,
        )
    brackets = sorted(
        request.leverage_brackets,
        key=lambda row: (row.notional_floor, row.bracket_id),
    )
    if len({row.bracket_id for row in brackets}) != len(brackets):
        raise SurfaceContractError("DUPLICATE_BRACKET_ID")
    bracket_snapshots = {
        (
            row.fetched_at_ms,
            row.ingested_at_ms,
            row.available_at_ms,
            row.expires_at_ms,
            row.source_key,
            row.source_sha256,
        )
        for row in brackets
    }
    if len(bracket_snapshots) > 1:
        raise SurfaceContractError("BRACKETS_MIX_MULTIPLE_SOURCE_SNAPSHOTS")
    for index, bracket in enumerate(brackets, start=1):
        if bracket.bracket_id != index:
            raise SurfaceContractError("BRACKET_SEQUENCE_NOT_CONTIGUOUS")
        if index == 1:
            if bracket.notional_floor != 0.0:
                raise SurfaceContractError("FIRST_BRACKET_FLOOR_NOT_ZERO")
            if bracket.cumulative_maintenance_amount != 0.0:
                raise SurfaceContractError("FIRST_BRACKET_CUM_NOT_ZERO")
            continue
        previous = brackets[index - 2]
        if bracket.notional_floor != previous.notional_cap:
            raise SurfaceContractError("BRACKET_RANGES_NOT_CONTIGUOUS")
        if bracket.initial_leverage > previous.initial_leverage:
            raise SurfaceContractError("INITIAL_LEVERAGE_INCREASES_WITH_NOTIONAL")
        if bracket.maintenance_margin_rate < previous.maintenance_margin_rate:
            raise SurfaceContractError("MAINT_MARGIN_RATE_DECREASES_WITH_NOTIONAL")
        expected_cum = Decimal(str(previous.cumulative_maintenance_amount)) + Decimal(
            str(bracket.notional_floor)
        ) * (
            Decimal(str(bracket.maintenance_margin_rate))
            - Decimal(str(previous.maintenance_margin_rate))
        )
        if Decimal(str(bracket.cumulative_maintenance_amount)) != expected_cum:
            raise SurfaceContractError("BRACKET_CUM_RECURRENCE_INVALID")
    calibration: dict[int, float] = {}
    if request.outcome_calibration is not None:
        calibration = _validate_calibration(
            request.outcome_calibration,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time_ms=as_of_time_ms,
        )

    exchange_max = max((row.initial_leverage for row in brackets), default=1)
    leverages = _scenario_leverages(exchange_max, max_scenarios) if brackets else []
    provided_calibration = dict(calibration)
    calibration = {
        leverage: weight
        for leverage, weight in provided_calibration.items()
        if leverage in leverages
    }
    if provided_calibration and not calibration:
        raise SurfaceContractError("CALIBRATION_NO_MODELED_LEVERAGE_OVERLAP")
    calibration_coverage = len(calibration) / len(leverages) if leverages and calibration else 0.0
    unused_calibration_leverages = sorted(set(provided_calibration) - set(calibration))
    cohorts, cohort_diagnostics = _build_cohorts(
        candles=candles,
        open_interest=open_interest,
        max_cohorts=max_cohorts,
    )
    mark_price_evidence_present = bool(mark_prices)
    current_price = mark_prices[-1].price if mark_prices else candles[-1].close
    current_price_source = "VENUE_MARK_PRICE" if mark_prices else "FINALIZED_CANDLE_CLOSE_FALLBACK"
    freshness_evidence = _adaptive_freshness_evidence(
        candles=candles,
        open_interest=open_interest,
        mark_prices=mark_prices,
        timeframe_duration_ms=timeframe_duration_ms,
        as_of_time_ms=as_of_time_ms,
    )
    adaptive_validity_candidates = (
        candles[-1].close_time_ms + freshness_evidence["candle"]["budget_ms"],
        (
            open_interest[-1].feature_cutoff_ms
            + freshness_evidence["open_interest"]["budget_ms"]
            if open_interest
            and freshness_evidence["open_interest"]["budget_ms"] is not None
            else None
        ),
        (
            mark_prices[-1].event_time_ms
            + freshness_evidence["mark_price"]["budget_ms"]
            if mark_prices and freshness_evidence["mark_price"]["budget_ms"] is not None
            else None
        ),
    )
    adaptive_source_valid_until = (
        min(cast(int, value) for value in adaptive_validity_candidates)
        if all(value is not None for value in adaptive_validity_candidates)
        else None
    )
    bracket_valid_until = min((row.expires_at_ms for row in brackets), default=None)
    long_excursions = _adverse_excursions(candles, side="long")
    short_excursions = _adverse_excursions(candles, side="short")
    bracket_scenarios = tuple(brackets)
    expanded_candidate_upper_bound = 2 * len(cohorts) * len(leverages) * len(bracket_scenarios)
    if expanded_candidate_upper_bound > max_expanded_candidates:
        raise SurfaceContractError("EXPANDED_CANDIDATE_LIMIT_EXCEEDED")
    candidates: dict[str, list[dict[str, Any]]] = {"long": [], "short": []}
    historical_crossed = {"long": 0, "short": 0}
    for side in ("long", "short"):
        excursions = long_excursions if side == "long" else short_excursions
        for cohort in cohorts:
            cohort_weight = float(cohort[f"{side}_weight"])
            if cohort_weight <= 0.0:
                continue
            for leverage in leverages:
                applicable = [
                    bracket for bracket in bracket_scenarios if leverage <= bracket.initial_leverage
                ]
                if not applicable:
                    continue
                for bracket in applicable:
                    mmr = bracket.maintenance_margin_rate
                    level = isolated_liquidation_price(
                        side=side,
                        entry_price=float(cohort["entry_price"]),
                        leverage=leverage,
                        maintenance_margin_rate=mmr,
                    )
                    if not _scenario_survived_since_entry(
                        candles=candles,
                        entry_time_ms=int(cohort["entry_time_ms"]),
                        side=side,
                        liquidation_price=level,
                    ):
                        historical_crossed[side] += 1
                        continue
                    distance = abs(level - float(cohort["entry_price"])) / float(
                        cohort["entry_price"]
                    )
                    scenario_weight = _empirical_scenario_weight(
                        liquidation_distance=distance,
                        adverse_excursions=excursions,
                        calibration_weight=calibration.get(leverage, 1.0),
                    )
                    candidate_weight = _finite(
                        cohort_weight * scenario_weight / len(applicable),
                        name="CANDIDATE_WEIGHT",
                    )
                    if candidate_weight <= 0.0:
                        raise SurfaceContractError("CANDIDATE_WEIGHT_NOT_POSITIVE")
                    candidates[side].append(
                        {
                            "price": level,
                            "weight": candidate_weight,
                            "leverage": leverage,
                            "maintenance_margin_rate": mmr,
                            "bracket_id": bracket.bracket_id,
                        }
                    )

    long_levels, nearest_long, crossed_long, retained_long_mass = _aggregate_levels(
        candidates["long"],
        current_price=current_price,
        side="long",
        tick_size=request.tick_size,
        max_levels=max_levels,
    )
    short_levels, nearest_short, crossed_short, retained_short_mass = _aggregate_levels(
        candidates["short"],
        current_price=current_price,
        side="short",
        tick_size=request.tick_size,
        max_levels=max_levels,
    )

    positive_oi_evidence_present = (
        len(open_interest) >= 2 and cohort_diagnostics["positive_open_interest_delta_total"] > 0.0
    )
    oi_unit_trainer_usable = bool(open_interest) and open_interest[-1].unit != "unknown"
    oi_evidence_present = positive_oi_evidence_present and oi_unit_trainer_usable
    bracket_evidence_present = bool(brackets)
    required_sources_fresh = bool(freshness_evidence["all_required_sources_fresh"])
    oi_temporal_resolution_coverage = (
        min(1.0, timeframe_duration_ms / oi_timeframe_duration_ms) if open_interest else 0.0
    )
    strict_input_contract = bool(leverages and long_levels and short_levels)
    trainer_semantic_eligible = bool(
        strict_input_contract
        and oi_evidence_present
        and bracket_evidence_present
        and mark_price_evidence_present
        and required_sources_fresh
    )
    if trainer_semantic_eligible:
        trainer_authority_reason = "POSTCOMMIT_CONSUMER_RECEIPT_REQUIRED"
    elif not bracket_evidence_present:
        trainer_authority_reason = "CURRENT_EXCHANGE_BRACKET_EVIDENCE_MISSING"
    elif not mark_price_evidence_present:
        trainer_authority_reason = "VENUE_MARK_PRICE_EVIDENCE_MISSING"
    elif not positive_oi_evidence_present:
        trainer_authority_reason = "POSITIVE_OPEN_INTEREST_COHORT_EVIDENCE_MISSING"
    elif not oi_unit_trainer_usable:
        trainer_authority_reason = "OPEN_INTEREST_UNIT_UNKNOWN"
    elif not required_sources_fresh:
        trainer_authority_reason = "ADAPTIVE_SOURCE_FRESHNESS_FAILED"
    else:
        trainer_authority_reason = "NO_VALID_BOTH_SIDE_LIQUIDATION_LEVELS"
    quality_components = {
        "finalized_candle_contract_coverage": 1.0,
        "venue_mark_price_coverage": 1.0 if mark_price_evidence_present else 0.0,
        "open_interest_new_cohort_coverage": cohort_diagnostics[
            "open_interest_new_cohort_coverage"
        ],
        "open_interest_temporal_resolution_coverage": (oi_temporal_resolution_coverage),
        "aggressor_flow_metadata_coverage": cohort_diagnostics["aggressor_flow_metadata_coverage"],
        "exchange_bracket_coverage": 1.0 if bracket_evidence_present else 0.0,
        "adaptive_source_freshness_coverage": sum(
            int(bool(freshness_evidence[name]["fresh"]))
            for name in ("candle", "open_interest", "mark_price")
        )
        / 3.0,
        "realized_outcome_calibration_coverage": calibration_coverage,
    }
    mandatory_quality = (
        quality_components["finalized_candle_contract_coverage"],
        quality_components["venue_mark_price_coverage"],
        quality_components["open_interest_new_cohort_coverage"],
        quality_components["open_interest_temporal_resolution_coverage"],
        quality_components["exchange_bracket_coverage"],
        quality_components["adaptive_source_freshness_coverage"],
    )
    structural_confidence = math.prod(mandatory_quality) ** (1.0 / len(mandatory_quality))
    feature_cutoff_sources = (
        [row.close_time_ms for row in candles]
        + [row.feature_cutoff_ms for row in open_interest]
        + [row.event_time_ms for row in mark_prices]
        + [row.fetched_at_ms for row in brackets]
    )
    if request.outcome_calibration is not None:
        feature_cutoff_sources.append(request.outcome_calibration.feature_cutoff_ms)
    feature_cutoff = max(feature_cutoff_sources)
    event_time_sources = (
        [row.event_time_ms for row in candles]
        + [row.event_time_ms for row in open_interest]
        + [row.event_time_ms for row in mark_prices]
    )
    event_time = max(event_time_sources)
    ingested_sources = (
        [row.ingested_at_ms for row in candles]
        + [row.ingested_at_ms for row in open_interest]
        + [row.ingested_at_ms for row in brackets]
    )
    available_sources = (
        [row.available_at_ms for row in candles]
        + [row.available_at_ms for row in open_interest]
        + [row.available_at_ms for row in brackets]
    )
    ingested_sources.extend(row.ingested_at_ms for row in mark_prices)
    available_sources.extend(row.available_at_ms for row in mark_prices)
    if request.outcome_calibration is not None:
        ingested_sources.append(request.outcome_calibration.ingested_at_ms)
        available_sources.append(request.outcome_calibration.available_at_ms)
    ingested_at = max(ingested_sources)
    source_available_at = max(available_sources)
    source_material = _source_material(request)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "liquidation_semantic_kind": SEMANTIC_KIND,
        "venue": venue,
        "symbol": symbol,
        "timeframe": timeframe,
        "open_interest_source_timeframe": oi_source_timeframe,
        "open_interest_source_to_surface_duration_ratio": (
            oi_timeframe_duration_ms / timeframe_duration_ms if open_interest else None
        ),
        "market_scope": "modeled_aggregate_open_position_cohorts",
        "not_position_exact": True,
        "forced_liquidation_events_used_as_level_source": False,
        "forced_liquidation_events_allowed_only_as_post_outcome_calibration": True,
        "margin_geometry": "isolated_usdm_conservative_cum_omitted",
        "cross_margin_position_exact": False,
        "accuracy_class": (
            "EXCHANGE_GEOMETRY_MARKET_COHORT_ESTIMATE"
            if trainer_semantic_eligible
            else "DEGRADED_SCENARIO_NOT_TRAINER_ELIGIBLE"
        ),
        "current_price": current_price,
        "current_price_source": current_price_source,
        "mark_price_evidence_present": mark_price_evidence_present,
        "long_levels": long_levels,
        "short_levels": short_levels,
        "nearest_long_level": nearest_long,
        "nearest_short_level": nearest_short,
        "long_level_count": len(long_levels),
        "short_level_count": len(short_levels),
        "exchange_max_initial_leverage": exchange_max if brackets else None,
        "leverage_scenarios": leverages,
        "leverage_scenario_count": len(leverages),
        "bracket_scenario_count": len(brackets),
        "bracket_scenario_policy": (
            "ALL_NOTIONAL_TIERS_RETAINED_AS_UNCERTAINTY_SCENARIOS;"
            "EQUAL_PRIOR_WITHIN_LEVERAGE_BEFORE_CAUSAL_OUTCOME_CALIBRATION"
            if brackets
            else "NO_BRACKET_PROXY_LEVELS_EMITTED"
        ),
        "cumulative_maintenance_amount_policy": ("omitted_conservative_toward_entry"),
        "cohort_diagnostics": cohort_diagnostics,
        "crossed_or_already_liquidated_long_scenario_count": crossed_long,
        "crossed_or_already_liquidated_short_scenario_count": crossed_short,
        "historically_crossed_long_scenario_count": historical_crossed["long"],
        "historically_crossed_short_scenario_count": historical_crossed["short"],
        "retained_long_scenario_weight_fraction": retained_long_mass,
        "retained_short_scenario_weight_fraction": retained_short_mass,
        "quality_components": quality_components,
        "structural_uncertainty": 1.0 - structural_confidence,
        "scenario_distribution_uncertainty": 1.0 - calibration_coverage,
        "calibration_applied_leverages": sorted(calibration),
        "calibration_unused_leverages": unused_calibration_leverages,
        "trainer_semantic_eligible": trainer_semantic_eligible,
        "trainer_authority": False,
        "trainer_authority_reason": trainer_authority_reason,
        "source_input_sha256": _canonical_sha256(source_material),
        "source_input_counts": {
            "finalized_candles": len(candles),
            "mark_price_observations": len(mark_prices),
            "open_interest_observations": len(open_interest),
            "leverage_brackets": len(brackets),
            "calibration_weights": len(calibration),
            "outcome_calibration_records": int(request.outcome_calibration is not None),
        },
        "event_time": event_time,
        "feature_cutoff": feature_cutoff,
        "ingested_at": ingested_at,
        "source_available_at": source_available_at,
        "surface_as_of": as_of_time_ms,
        "generated_at": generated_at_ms,
        "adaptive_source_valid_until": adaptive_source_valid_until,
        "adaptive_source_valid_until_inclusive": True,
        "bracket_valid_until": bracket_valid_until,
        "bracket_valid_until_exclusive": True,
        "available_at": None,
        "postcommit_receipt_bound": False,
        "source_age_ms": {
            "latest_finalized_candle": as_of_time_ms - candles[-1].close_time_ms,
            "mark_price": (as_of_time_ms - mark_prices[-1].event_time_ms if mark_prices else None),
            "latest_open_interest_period": (
                as_of_time_ms - open_interest[-1].feature_cutoff_ms if open_interest else None
            ),
            "bracket_validity_remaining_at_generation": (
                min(row.expires_at_ms for row in brackets) - generated_at_ms if brackets else None
            ),
            "adaptive_freshness_threshold_applied": True,
            "static_market_freshness_threshold_applied": False,
        },
        "adaptive_freshness_evidence": freshness_evidence,
        "calibration_cutoff": (
            request.outcome_calibration.feature_cutoff_ms
            if request.outcome_calibration is not None
            else None
        ),
        "resource_bounds": {
            "max_cohorts": max_cohorts,
            "max_leverage_scenarios": max_scenarios,
            "max_levels_per_side": max_levels,
            "max_source_rows_per_family": max_source_rows,
            "max_expanded_candidates": max_expanded_candidates,
            "expanded_candidate_upper_bound": expanded_candidate_upper_bound,
            "resource_bounds_are_market_thresholds": False,
        },
    }
    payload["surface_payload_sha256"] = _canonical_sha256(payload)
    return payload
