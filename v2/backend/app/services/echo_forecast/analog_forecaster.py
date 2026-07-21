"""Pure analogue forecasts with an optional point-in-time-safe contract.

``compute_analog_forecast`` remains the dependency-light numerical kernel.  It
accepts anonymous vectors for research callers, but anonymous vectors cannot
prove candle finality or temporal lineage.  ``compute_pit_safe_analog_forecast``
adds the fail-closed clock, identity, cleanliness, uniqueness, and non-overlap
contract required before an analogue forecast may be represented as PIT-safe.

Neither API performs I/O, publishes signals, mutates trainer state, or places
orders.  An analogue forecast is a research feature, not an execution signal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from calendar import monthrange
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from typing import Any, TypeGuard

SCHEMA_VERSION = "echo_analog_forecast_v2"
PIT_SCHEMA_VERSION = "echo_analog_forecast_pit_v2"

STATUS_OK = "ok"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_INVALID_INPUT = "invalid_input"

_MAX_DISTANCE_COMPONENT = 1.0e150
_CANONICAL_TIMEFRAME = re.compile(r"[1-9][0-9]*(?:s|m|h|d|w|M)")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class AnalogForecast:
    """Distribution assembled from nearest unique historical analogues.

    The agreement and quality fields are descriptive research diagnostics,
    not out-of-sample accuracy or calibrated probability.  The additional
    status/lineage fields make fail-closed results explicit.
    ``selected_analog_indices`` refers to positions in the caller's original
    ``historical_windows`` sequence.
    """

    expected_move_bps: float
    dispersion_bps: float
    direction: str
    neighbor_direction_agreement: float
    n_analogs: int
    mean_distance: float
    heuristic_quality_score: float
    insufficient_data: bool
    schema_version: str = SCHEMA_VERSION
    status: str = STATUS_OK
    reason_codes: tuple[str, ...] = ()
    unique_analog_count: int = 0
    dropped_analog_count: int = 0
    duplicate_analog_count: int = 0
    selected_analog_indices: tuple[int, ...] = ()
    overlap_checked: bool = False


TimestampLike = datetime | str


@dataclass(frozen=True)
class PITCurrentWindow:
    """Timestamped current feature window used by the safe API."""

    current_window_id: str
    symbol: str
    timeframe: str
    forecast_horizon_seconds: int
    values: Sequence[float]
    feature_schema_sha256: str
    feature_names: Sequence[str]
    feature_units: Sequence[str]
    feature_transform_version: str
    lookback_bars: int
    lookback_seconds: int
    outcome_schema_sha256: str
    outcome_name: str
    outcome_unit: str
    outcome_transform_version: str
    outcome_price_source: str
    outcome_return_convention: str
    feature_window_start: TimestampLike
    feature_cutoff: TimestampLike
    event_time: TimestampLike
    ingested_at: TimestampLike
    available_at: TimestampLike
    decision_time: TimestampLike
    candle_closed_confirmed: bool
    latest_unclosed_candle_excluded: bool
    lineage_valid: bool = True
    dirty: bool = False
    missing_required_fields: tuple[str, ...] = ()
    stale_required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class PITAnalogCandidate:
    """One historical feature window and its already-realized outcome."""

    analog_id: str
    symbol: str
    timeframe: str
    forecast_horizon_seconds: int
    values: Sequence[float]
    feature_schema_sha256: str
    feature_names: Sequence[str]
    feature_units: Sequence[str]
    feature_transform_version: str
    lookback_bars: int
    lookback_seconds: int
    outcome_schema_sha256: str
    outcome_name: str
    outcome_unit: str
    outcome_transform_version: str
    outcome_price_source: str
    outcome_return_convention: str
    forward_return_bps: float
    feature_window_start: TimestampLike
    feature_cutoff: TimestampLike
    event_time: TimestampLike
    ingested_at: TimestampLike
    available_at: TimestampLike
    decision_time: TimestampLike
    outcome_start_time: TimestampLike
    outcome_end_time: TimestampLike
    outcome_available_at: TimestampLike
    candle_closed_confirmed: bool
    latest_unclosed_candle_excluded: bool
    outcome_candle_closed_confirmed: bool
    lineage_valid: bool = True
    dirty: bool = False
    missing_required_fields: tuple[str, ...] = ()
    stale_required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class PITAnalogForecast:
    """Forecast plus immutable PIT clock and neighbour lineage."""

    forecast: AnalogForecast
    status: str
    reason_codes: tuple[str, ...]
    current_window_id: str
    symbol: str
    timeframe: str
    forecast_horizon_seconds: int
    event_time: str | None
    ingested_at: str | None
    input_available_at: str | None
    available_at: str | None
    feature_cutoff: str | None
    decision_time: str | None
    generated_at: str | None
    input_sha256: str | None
    forecast_config_sha256: str | None
    eligible_analog_ids: tuple[str, ...]
    selected_analog_ids: tuple[str, ...]
    rejected_analogs: tuple[tuple[str, tuple[str, ...]], ...]
    overlap_checked: bool = False
    schema_version: str = PIT_SCHEMA_VERSION


def _stable_reasons(*groups: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for reason in group:
            text = str(reason)
            if text and text not in seen:
                seen.add(text)
                ordered.append(text)
    return tuple(ordered)


def _is_sequence(value: object) -> TypeGuard[Sequence[Any]]:
    if isinstance(value, str | bytes | bytearray | Mapping):
        return False
    return isinstance(value, Sequence) or (
        hasattr(value, "__len__") and hasattr(value, "__getitem__")
    )


def _finite(value: object) -> float | None:
    """Return a finite real number while rejecting bools and numeric strings."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None
    converted = int(value)
    return converted if converted > 0 else None


def compute_feature_schema_sha256(
    *,
    feature_names: object,
    feature_units: object,
    feature_transform_version: object,
    lookback_bars: object,
    lookback_seconds: object,
) -> str | None:
    """Return the canonical semantic feature-contract hash, or ``None``.

    Vector width alone cannot establish that two analogue windows contain the
    same ordered features, units, transform, or lookback.  The PIT API requires
    this hash on both current and historical windows and independently
    recomputes it before admitting either side.
    """

    if not _is_sequence(feature_names) or not _is_sequence(feature_units):
        return None
    names = tuple(str(item).strip() for item in feature_names if isinstance(item, str))
    units = tuple(str(item).strip() for item in feature_units if isinstance(item, str))
    transform = (
        str(feature_transform_version).strip()
        if isinstance(feature_transform_version, str)
        else ""
    )
    bars = _positive_int(lookback_bars)
    seconds = _positive_int(lookback_seconds)
    if (
        not names
        or len(names) != len(feature_names)
        or len(units) != len(feature_units)
        or len(names) != len(units)
        or len(set(names)) != len(names)
        or any(not item for item in (*names, *units))
        or not transform
        or bars is None
        or seconds is None
    ):
        return None
    encoded = json.dumps(
        {
            "feature_names": names,
            "feature_units": units,
            "feature_transform_version": transform,
            "lookback_bars": bars,
            "lookback_seconds": seconds,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_outcome_schema_sha256(
    *,
    outcome_name: object,
    outcome_unit: object,
    outcome_transform_version: object,
    outcome_price_source: object,
    outcome_return_convention: object,
) -> str | None:
    """Return the canonical realized-outcome contract hash, or ``None``.

    A horizon and a numeric bps label are not enough to establish that two
    historical outcomes are comparable.  The price source, transform, and
    gross/net convention must also be identical.
    """

    raw_fields = {
        "outcome_name": outcome_name,
        "outcome_unit": outcome_unit,
        "outcome_transform_version": outcome_transform_version,
        "outcome_price_source": outcome_price_source,
        "outcome_return_convention": outcome_return_convention,
    }
    if any(not isinstance(value, str) or not value.strip() for value in raw_fields.values()):
        return None
    normalized = {name: str(value).strip() for name, value in raw_fields.items()}
    normalized["outcome_unit"] = normalized["outcome_unit"].casefold()
    if normalized["outcome_unit"] != "bps":
        return None
    return _payload_sha256(normalized)


def _validate_outcome_contract(owner: object, *, prefix: str) -> tuple[list[str], dict[str, str]]:
    reasons: list[str] = []
    field_names = (
        "outcome_name",
        "outcome_unit",
        "outcome_transform_version",
        "outcome_price_source",
        "outcome_return_convention",
    )
    raw = {name: getattr(owner, name, None) for name in field_names}
    normalized = {
        name: value.strip() if isinstance(value, str) else ""
        for name, value in raw.items()
    }
    normalized["outcome_unit"] = normalized["outcome_unit"].casefold()
    computed_hash = compute_outcome_schema_sha256(**normalized)
    supplied_hash = str(getattr(owner, "outcome_schema_sha256", "") or "").strip().lower()
    if computed_hash is None:
        reasons.append(f"{prefix}_OUTCOME_CONTRACT_INVALID")
    elif not _SHA256_HEX.fullmatch(supplied_hash) or supplied_hash != computed_hash:
        reasons.append(f"{prefix}_OUTCOME_SCHEMA_HASH_MISMATCH")
    return reasons, {
        "outcome_schema_sha256": computed_hash or "",
        **normalized,
    }


def _validate_feature_contract(
    owner: object,
    *,
    value_count: int,
    prefix: str,
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    names = getattr(owner, "feature_names", None)
    units = getattr(owner, "feature_units", None)
    transform = getattr(owner, "feature_transform_version", None)
    lookback_bars = _positive_int(getattr(owner, "lookback_bars", None))
    lookback_seconds = _positive_int(getattr(owner, "lookback_seconds", None))
    supplied_hash = str(getattr(owner, "feature_schema_sha256", "") or "").strip().lower()
    computed_hash = compute_feature_schema_sha256(
        feature_names=names,
        feature_units=units,
        feature_transform_version=transform,
        lookback_bars=getattr(owner, "lookback_bars", None),
        lookback_seconds=getattr(owner, "lookback_seconds", None),
    )
    if computed_hash is None:
        reasons.append(f"{prefix}_FEATURE_CONTRACT_INVALID")
        normalized_names: tuple[str, ...] = ()
        normalized_units: tuple[str, ...] = ()
        normalized_transform = ""
    else:
        assert _is_sequence(names)
        assert _is_sequence(units)
        assert isinstance(transform, str)
        normalized_names = tuple(str(item).strip() for item in names)
        normalized_units = tuple(str(item).strip() for item in units)
        normalized_transform = str(transform).strip()
        if len(normalized_names) != value_count:
            reasons.append(f"{prefix}_FEATURE_CONTRACT_WIDTH_MISMATCH")
        if not _SHA256_HEX.fullmatch(supplied_hash) or supplied_hash != computed_hash:
            reasons.append(f"{prefix}_FEATURE_SCHEMA_HASH_MISMATCH")
    return reasons, {
        "feature_schema_sha256": computed_hash or "",
        "feature_names": normalized_names,
        "feature_units": normalized_units,
        "feature_transform_version": normalized_transform,
        "lookback_bars": lookback_bars or 0,
        "lookback_seconds": lookback_seconds or 0,
    }


def _empty_forecast(
    *,
    status: str,
    reasons: Sequence[str],
    unique_count: int = 0,
    dropped_count: int = 0,
    duplicate_count: int = 0,
    overlap_checked: bool = False,
) -> AnalogForecast:
    return AnalogForecast(
        expected_move_bps=0.0,
        dispersion_bps=0.0,
        direction="flat",
        neighbor_direction_agreement=0.0,
        n_analogs=0,
        mean_distance=0.0,
        heuristic_quality_score=0.0,
        insufficient_data=True,
        status=status,
        reason_codes=_stable_reasons(reasons),
        unique_analog_count=max(0, int(unique_count)),
        dropped_analog_count=max(0, int(dropped_count)),
        duplicate_analog_count=max(0, int(duplicate_count)),
        overlap_checked=overlap_checked,
    )


def _column_stds(rows: Sequence[Sequence[float]], dims: int) -> list[float]:
    """Population standard deviations computed without overflowing large inputs."""

    stds: list[float] = []
    for column in range(dims):
        values = [row[column] for row in rows]
        scale = max(abs(value) for value in values)
        if scale == 0.0:
            stds.append(1.0)
            continue
        scaled = [value / scale for value in values]
        mean_scaled = max(-1.0, min(1.0, math.fsum(scaled) / len(scaled)))
        variance_scaled = math.fsum(
            (value - mean_scaled) * (value - mean_scaled) for value in scaled
        ) / len(scaled)
        std = scale * min(1.0, math.sqrt(max(0.0, variance_scaled)))
        if not math.isfinite(std) or std <= 1.0e-12:
            std = 1.0
        stds.append(std)
    return stds


def _scaled_component(a: float, b: float, std: float) -> float:
    if a == b:
        return 0.0
    magnitude = max(abs(a), abs(b), std, 1.0)
    normalized_difference = (a / magnitude) - (b / magnitude)
    scale_ratio = magnitude / std
    component = normalized_difference * scale_ratio
    if not math.isfinite(component):
        component = _MAX_DISTANCE_COMPONENT if a > b else -_MAX_DISTANCE_COMPONENT
    return max(-_MAX_DISTANCE_COMPONENT, min(_MAX_DISTANCE_COMPONENT, component))


def _distance(a: Sequence[float], b: Sequence[float], stds: Sequence[float]) -> float:
    if not a:
        return 0.0
    components = [_scaled_component(a[i], b[i], stds[i]) for i in range(len(a))]
    distance = math.hypot(*components) / math.sqrt(len(components))
    return distance if math.isfinite(distance) else _MAX_DISTANCE_COMPONENT


def _safe_nonnegative_mean(values: Sequence[float]) -> float:
    scale = max(values, default=0.0)
    if scale <= 0.0:
        return 0.0
    return scale * (math.fsum(value / scale for value in values) / len(values))


def _weighted_distribution(
    labels: Sequence[float], weights: Sequence[float]
) -> tuple[float, float]:
    weight_sum = math.fsum(weights)
    label_scale = max((abs(label) for label in labels), default=0.0)
    if weight_sum <= 0.0 or label_scale == 0.0:
        return 0.0, 0.0
    normalized = [label / label_scale for label in labels]
    mean_normalized = (
        math.fsum(weight * label for weight, label in zip(weights, normalized, strict=True))
        / weight_sum
    )
    mean_normalized = max(-1.0, min(1.0, mean_normalized))
    variance_normalized = (
        math.fsum(
            weight * (label - mean_normalized) * (label - mean_normalized)
            for weight, label in zip(weights, normalized, strict=True)
        )
        / weight_sum
    )
    dispersion_normalized = min(1.0, math.sqrt(max(0.0, variance_normalized)))
    expected = label_scale * mean_normalized
    dispersion = label_scale * dispersion_normalized
    if not math.isfinite(expected):
        expected = math.copysign(label_scale, mean_normalized)
    if not math.isfinite(dispersion):
        dispersion = label_scale
    return expected, dispersion


def _compute_analog_forecast_impl(
    *,
    current_window: Sequence[float],
    historical_windows: Sequence[Sequence[float]],
    forward_return_bps: Sequence[float],
    k: int,
    min_analogs: int,
    dispersion_ref_bps: float,
    flat_band_bps: float,
    overlap_checked: bool,
) -> AnalogForecast:
    parameter_reasons: list[str] = []
    normalized_k = _positive_int(k)
    normalized_min = _positive_int(min_analogs)
    dispersion_ref = _finite(dispersion_ref_bps)
    flat_band = _finite(flat_band_bps)
    if normalized_k is None:
        parameter_reasons.append("K_MUST_BE_POSITIVE_INTEGER")
    if normalized_min is None:
        parameter_reasons.append("MIN_ANALOGS_MUST_BE_POSITIVE_INTEGER")
    if normalized_k is not None and normalized_min is not None and normalized_k < normalized_min:
        parameter_reasons.append("K_BELOW_MIN_ANALOGS")
    if dispersion_ref is None or dispersion_ref <= 0.0:
        parameter_reasons.append("DISPERSION_REF_BPS_MUST_BE_FINITE_POSITIVE")
    if flat_band is None or flat_band < 0.0:
        parameter_reasons.append("FLAT_BAND_BPS_MUST_BE_FINITE_NONNEGATIVE")
    if parameter_reasons:
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=parameter_reasons,
            overlap_checked=overlap_checked,
        )
    # All optional normalized values are proven present by the fail-closed
    # parameter branch above; these assertions also preserve that invariant for
    # static analysis and future edits.
    assert normalized_k is not None
    assert normalized_min is not None
    assert dispersion_ref is not None
    assert flat_band is not None

    if not _is_sequence(current_window):
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("CURRENT_WINDOW_MUST_BE_SEQUENCE",),
            overlap_checked=overlap_checked,
        )
    if not _is_sequence(historical_windows):
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("HISTORICAL_WINDOWS_MUST_BE_SEQUENCE",),
            overlap_checked=overlap_checked,
        )
    if not _is_sequence(forward_return_bps):
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("FORWARD_RETURNS_MUST_BE_SEQUENCE",),
            overlap_checked=overlap_checked,
        )

    dims = len(current_window)
    if dims == 0:
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("CURRENT_WINDOW_EMPTY",),
            overlap_checked=overlap_checked,
        )
    if len(historical_windows) != len(forward_return_bps):
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("HISTORICAL_FORWARD_LENGTH_MISMATCH",),
            overlap_checked=overlap_checked,
        )

    current_values = [_finite(value) for value in current_window]
    if any(value is None for value in current_values):
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("CURRENT_WINDOW_CONTAINS_NON_FINITE_OR_NON_NUMERIC_VALUE",),
            overlap_checked=overlap_checked,
        )
    current = [float(value) for value in current_values if value is not None]

    warnings: list[str] = []
    clean: list[tuple[list[float], float, int]] = []
    seen_pairs: set[tuple[tuple[float, ...], float]] = set()
    dropped_count = 0
    duplicate_count = 0
    for original_index in range(len(historical_windows)):
        row = historical_windows[original_index]
        label = forward_return_bps[original_index]
        if not _is_sequence(row):
            dropped_count += 1
            warnings.append("HISTORICAL_ROW_NOT_SEQUENCE_DROPPED")
            continue
        if len(row) != dims:
            dropped_count += 1
            warnings.append("HISTORICAL_ROW_WIDTH_MISMATCH_DROPPED")
            continue
        finite_label = _finite(label)
        if finite_label is None:
            dropped_count += 1
            warnings.append("HISTORICAL_FORWARD_NON_FINITE_OR_NON_NUMERIC_DROPPED")
            continue
        finite_row = [_finite(value) for value in row]
        if any(value is None for value in finite_row):
            dropped_count += 1
            warnings.append("HISTORICAL_ROW_NON_FINITE_OR_NON_NUMERIC_DROPPED")
            continue
        vector = [float(value) for value in finite_row if value is not None]
        pair_key = (tuple(vector), finite_label)
        if pair_key in seen_pairs:
            dropped_count += 1
            duplicate_count += 1
            warnings.append("EXACT_DUPLICATE_ANALOG_DROPPED")
            continue
        seen_pairs.add(pair_key)
        clean.append((vector, finite_label, original_index))

    if len(clean) < normalized_min:
        return _empty_forecast(
            status=STATUS_INSUFFICIENT_DATA,
            reasons=_stable_reasons(warnings, ("INSUFFICIENT_UNIQUE_ANALOGS",)),
            unique_count=len(clean),
            dropped_count=dropped_count,
            duplicate_count=duplicate_count,
            overlap_checked=overlap_checked,
        )

    stds = _column_stds([item[0] for item in clean], dims)
    scored = [
        (_distance(current, vector, stds), label, original_index)
        for vector, label, original_index in clean
    ]
    scored.sort(key=lambda item: (item[0], item[2]))
    neighbours = scored[: min(normalized_k, len(scored))]
    if len(neighbours) < normalized_min:
        return _empty_forecast(
            status=STATUS_INSUFFICIENT_DATA,
            reasons=_stable_reasons(warnings, ("SELECTED_ANALOGS_BELOW_MINIMUM",)),
            unique_count=len(clean),
            dropped_count=dropped_count,
            duplicate_count=duplicate_count,
            overlap_checked=overlap_checked,
        )

    distances = [item[0] for item in neighbours]
    mean_distance = _safe_nonnegative_mean(distances)
    distance_scale = mean_distance if mean_distance > 1.0e-9 else 1.0
    weights = [math.exp(-(distance / distance_scale)) for distance in distances]
    labels = [item[1] for item in neighbours]
    expected_move, dispersion = _weighted_distribution(labels, weights)
    weight_sum = math.fsum(weights)

    if expected_move > flat_band:
        direction = "long"
    elif expected_move < -flat_band:
        direction = "short"
    else:
        direction = "flat"

    def agrees(label: float) -> bool:
        if direction == "long":
            return label > 0.0
        if direction == "short":
            return label < 0.0
        return abs(label) <= flat_band

    neighbor_direction_agreement = (
        math.fsum(weight for weight, label in zip(weights, labels, strict=True) if agrees(label))
        / weight_sum
    )
    dispersion_ratio = dispersion / dispersion_ref
    dispersion_term = math.exp(-dispersion_ratio) if math.isfinite(dispersion_ratio) else 0.0
    closeness_term = 1.0 / (1.0 + mean_distance)
    count_term = min(1.0, len(neighbours) / normalized_k)
    agreement_term = max(0.0, (neighbor_direction_agreement - 0.5) * 2.0)
    heuristic_quality_score = agreement_term * dispersion_term * closeness_term * count_term
    heuristic_quality_score = max(0.0, min(1.0, heuristic_quality_score))

    return AnalogForecast(
        expected_move_bps=round(expected_move, 4),
        dispersion_bps=round(dispersion, 4),
        direction=direction,
        neighbor_direction_agreement=round(neighbor_direction_agreement, 4),
        n_analogs=len(neighbours),
        mean_distance=round(mean_distance, 6),
        heuristic_quality_score=round(heuristic_quality_score, 4),
        insufficient_data=False,
        status=STATUS_OK,
        reason_codes=_stable_reasons(warnings),
        unique_analog_count=len(clean),
        dropped_analog_count=dropped_count,
        duplicate_analog_count=duplicate_count,
        selected_analog_indices=tuple(item[2] for item in neighbours),
        overlap_checked=overlap_checked,
    )


def compute_analog_forecast(
    *,
    current_window: Sequence[float],
    historical_windows: Sequence[Sequence[float]],
    forward_return_bps: Sequence[float],
    k: int = 25,
    min_analogs: int = 8,
    dispersion_ref_bps: float = 120.0,
    flat_band_bps: float = 5.0,
) -> AnalogForecast:
    """Compute a defensive k-NN forecast over anonymous numerical vectors.

    Invalid inputs never raise: they return ``status='invalid_input'``.  Bad
    historical rows are dropped with explicit reason codes.  Exact duplicate
    ``(window, label)`` pairs count once.  This raw API cannot verify temporal
    overlap; callers needing a PIT claim must use the timestamped safe API.
    """

    try:
        return _compute_analog_forecast_impl(
            current_window=current_window,
            historical_windows=historical_windows,
            forward_return_bps=forward_return_bps,
            k=k,
            min_analogs=min_analogs,
            dispersion_ref_bps=dispersion_ref_bps,
            flat_band_bps=flat_band_bps,
            overlap_checked=False,
        )
    except Exception:
        return _empty_forecast(
            status=STATUS_INVALID_INPUT,
            reasons=("INPUT_ACCESS_OR_NUMERICAL_ERROR",),
        )


def _parse_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _clean_identity(value: object, *, upper: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if upper:
        return text.upper()
    return text


def _clean_timeframe(value: object) -> str | None:
    """Return a case-sensitive canonical timeframe (``1m`` != ``1M``)."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CANONICAL_TIMEFRAME.fullmatch(text) else None


def _calendar_months_after(value: datetime, months: int) -> datetime | None:
    if months <= 0:
        return None
    zero_based = (value.year * 12) + (value.month - 1) + months
    year, month_index = divmod(zero_based, 12)
    if year < 1 or year > 9999:
        return None
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _lookback_matches_timeframe(
    *,
    timeframe: str,
    lookback_bars: int,
    lookback_seconds: int,
    start: datetime,
    cutoff: datetime,
) -> bool:
    match = _CANONICAL_TIMEFRAME.fullmatch(timeframe)
    if match is None or lookback_bars <= 0 or lookback_seconds <= 0:
        return False
    count_text = timeframe[:-1]
    unit = timeframe[-1]
    count = int(count_text)
    actual_seconds = (cutoff - start).total_seconds()
    if actual_seconds <= 0.0 or actual_seconds != lookback_seconds:
        return False
    if unit == "M":
        expected_cutoff = _calendar_months_after(start, count * lookback_bars)
        return expected_cutoff == cutoff
    multiplier = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }.get(unit)
    if multiplier is None:
        return False
    return lookback_seconds == count * multiplier * lookback_bars


def _field_names_state(value: object) -> tuple[bool, bool]:
    """Return ``(contract_valid, contains_names)`` for dirty-field tuples."""

    if not _is_sequence(value):
        return False, False
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return False, False
    return True, bool(value)


def _parse_named_clocks(
    owner: object, names: Sequence[str], prefix: str, reasons: list[str]
) -> dict[str, datetime]:
    parsed: dict[str, datetime] = {}
    for name in names:
        clock = _parse_utc(getattr(owner, name, None))
        if clock is None:
            reasons.append(f"{prefix}_{name.upper()}_INVALID_OR_NAIVE")
        else:
            parsed[name] = clock
    return parsed


def _invalid_pit_output(
    *,
    reasons: Sequence[str],
    current: object,
    generated_at: datetime | None,
    parsed_current: dict[str, datetime] | None = None,
    rejected: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> PITAnalogForecast:
    normalized_reasons = _stable_reasons(reasons)
    forecast = _empty_forecast(
        status=STATUS_INVALID_INPUT,
        reasons=normalized_reasons,
        overlap_checked=False,
    )
    clocks = parsed_current or {}
    horizon = _positive_int(getattr(current, "forecast_horizon_seconds", None)) or 0
    return PITAnalogForecast(
        forecast=forecast,
        status=STATUS_INVALID_INPUT,
        reason_codes=normalized_reasons,
        current_window_id=_clean_identity(getattr(current, "current_window_id", None)) or "",
        symbol=_clean_identity(getattr(current, "symbol", None), upper=True) or "",
        timeframe=_clean_timeframe(getattr(current, "timeframe", None)) or "",
        forecast_horizon_seconds=horizon,
        event_time=_utc_text(clocks.get("event_time")),
        ingested_at=_utc_text(clocks.get("ingested_at")),
        input_available_at=_utc_text(clocks.get("available_at")),
        available_at=_utc_text(generated_at),
        feature_cutoff=_utc_text(clocks.get("feature_cutoff")),
        decision_time=_utc_text(clocks.get("decision_time")),
        generated_at=_utc_text(generated_at),
        input_sha256=None,
        forecast_config_sha256=None,
        eligible_analog_ids=(),
        selected_analog_ids=(),
        rejected_analogs=rejected,
        overlap_checked=False,
    )


def _validate_current(
    current: object, generated_at: object
) -> tuple[list[str], dict[str, Any], datetime | None]:
    reasons: list[str] = []
    if not isinstance(current, PITCurrentWindow):
        return ["CURRENT_CONTRACT_TYPE_INVALID"], {}, _parse_utc(generated_at)

    current_id = _clean_identity(current.current_window_id)
    symbol = _clean_identity(current.symbol, upper=True)
    timeframe = _clean_timeframe(current.timeframe)
    horizon = _positive_int(current.forecast_horizon_seconds)
    if current_id is None:
        reasons.append("CURRENT_WINDOW_ID_INVALID")
    if symbol is None:
        reasons.append("CURRENT_SYMBOL_INVALID")
    if timeframe is None:
        reasons.append("CURRENT_TIMEFRAME_INVALID")
    if horizon is None:
        reasons.append("CURRENT_FORECAST_HORIZON_INVALID")
    if not _is_sequence(current.values) or len(current.values) == 0:
        reasons.append("CURRENT_VALUES_INVALID")
        values: list[float] = []
    else:
        finite_values = [_finite(value) for value in current.values]
        if any(value is None for value in finite_values):
            reasons.append("CURRENT_VALUES_INVALID")
            values = []
        else:
            values = [float(value) for value in finite_values if value is not None]
    feature_reasons, feature_contract = _validate_feature_contract(
        current,
        value_count=len(values),
        prefix="CURRENT",
    )
    reasons.extend(feature_reasons)
    outcome_reasons, outcome_contract = _validate_outcome_contract(
        current,
        prefix="CURRENT",
    )
    reasons.extend(outcome_reasons)
    if current.candle_closed_confirmed is not True:
        reasons.append("CURRENT_CANDLE_NOT_FINAL")
    if current.latest_unclosed_candle_excluded is not True:
        reasons.append("CURRENT_UNCLOSED_CANDLE_NOT_EXCLUDED")
    if current.lineage_valid is not True:
        reasons.append("CURRENT_LINEAGE_INVALID")
    if current.dirty is not False:
        reasons.append("CURRENT_DIRTY")
    missing_contract_valid, missing_present = _field_names_state(current.missing_required_fields)
    stale_contract_valid, stale_present = _field_names_state(current.stale_required_fields)
    if not missing_contract_valid:
        reasons.append("CURRENT_MISSING_REQUIRED_FIELDS_CONTRACT_INVALID")
    elif missing_present:
        reasons.append("CURRENT_REQUIRED_FIELDS_MISSING")
    if not stale_contract_valid:
        reasons.append("CURRENT_STALE_REQUIRED_FIELDS_CONTRACT_INVALID")
    elif stale_present:
        reasons.append("CURRENT_REQUIRED_FIELDS_STALE")

    clock_names = (
        "feature_window_start",
        "feature_cutoff",
        "event_time",
        "ingested_at",
        "available_at",
        "decision_time",
    )
    clocks = _parse_named_clocks(current, clock_names, "CURRENT", reasons)
    generated = _parse_utc(generated_at)
    if generated is None:
        reasons.append("GENERATED_AT_INVALID_OR_NAIVE")
    if len(clocks) == len(clock_names):
        if clocks["feature_window_start"] > clocks["feature_cutoff"]:
            reasons.append("CURRENT_FEATURE_WINDOW_START_AFTER_CUTOFF")
        if clocks["feature_window_start"] > clocks["event_time"]:
            reasons.append("CURRENT_FEATURE_WINDOW_START_AFTER_EVENT_TIME")
        if clocks["event_time"] > clocks["feature_cutoff"]:
            reasons.append("CURRENT_EVENT_TIME_AFTER_FEATURE_CUTOFF")
        if clocks["feature_cutoff"] > clocks["ingested_at"]:
            reasons.append("CURRENT_FEATURE_CUTOFF_AFTER_INGESTED_AT")
        if clocks["ingested_at"] > clocks["available_at"]:
            reasons.append("CURRENT_INGESTED_AT_AFTER_AVAILABLE_AT")
        if generated is not None and clocks["available_at"] > generated:
            reasons.append("CURRENT_AVAILABLE_AT_AFTER_GENERATED_AT")
        if clocks["available_at"] > clocks["decision_time"]:
            reasons.append("CURRENT_AVAILABLE_AT_AFTER_DECISION_TIME")
        if clocks["feature_cutoff"] > clocks["decision_time"]:
            reasons.append("CURRENT_FEATURE_CUTOFF_AFTER_DECISION_TIME")
        if generated is not None and generated > clocks["decision_time"]:
            reasons.append("GENERATED_AT_AFTER_DECISION_TIME")
        if not _lookback_matches_timeframe(
            timeframe=timeframe or "",
            lookback_bars=feature_contract["lookback_bars"],
            lookback_seconds=feature_contract["lookback_seconds"],
            start=clocks["feature_window_start"],
            cutoff=clocks["feature_cutoff"],
        ):
            reasons.append("CURRENT_LOOKBACK_TIMEFRAME_MISMATCH")

    return (
        reasons,
        {
            "current_window_id": current_id or "",
            "symbol": symbol or "",
            "timeframe": timeframe or "",
            "horizon": horizon or 0,
            "values": values,
            **feature_contract,
            **outcome_contract,
            "clocks": clocks,
            "generated_at": generated,
        },
        generated,
    )


def _candidate_identity(candidate: object, index: int) -> str:
    if isinstance(candidate, PITAnalogCandidate):
        identity = _clean_identity(candidate.analog_id)
        if identity is not None:
            return identity
    return f"<candidate:{index}>"


def _validate_candidate(
    candidate: object,
    *,
    current: dict[str, Any],
    duplicate_id: bool,
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    if not isinstance(candidate, PITAnalogCandidate):
        return ["ANALOG_CONTRACT_TYPE_INVALID"], {}
    analog_id = _clean_identity(candidate.analog_id)
    symbol = _clean_identity(candidate.symbol, upper=True)
    timeframe = _clean_timeframe(candidate.timeframe)
    horizon = _positive_int(candidate.forecast_horizon_seconds)
    if analog_id is None:
        reasons.append("ANALOG_ID_INVALID")
    if duplicate_id:
        reasons.append("DUPLICATE_ANALOG_ID")
    if symbol is None or symbol != current["symbol"]:
        reasons.append("ANALOG_SYMBOL_MISMATCH")
    if timeframe is None or timeframe != current["timeframe"]:
        reasons.append("ANALOG_TIMEFRAME_MISMATCH")
    if horizon is None or horizon != current["horizon"]:
        reasons.append("ANALOG_FORECAST_HORIZON_MISMATCH")
    if not _is_sequence(candidate.values) or len(candidate.values) != len(current["values"]):
        reasons.append("ANALOG_VALUES_INVALID_OR_WIDTH_MISMATCH")
        values: list[float] = []
    else:
        finite_values = [_finite(value) for value in candidate.values]
        if any(value is None for value in finite_values):
            reasons.append("ANALOG_VALUES_INVALID_OR_WIDTH_MISMATCH")
            values = []
        else:
            values = [float(value) for value in finite_values if value is not None]
    feature_reasons, feature_contract = _validate_feature_contract(
        candidate,
        value_count=len(values),
        prefix="ANALOG",
    )
    reasons.extend(feature_reasons)
    for field, reason in (
        ("feature_schema_sha256", "ANALOG_FEATURE_SCHEMA_MISMATCH"),
        ("feature_names", "ANALOG_FEATURE_NAMES_MISMATCH"),
        ("feature_units", "ANALOG_FEATURE_UNITS_MISMATCH"),
        ("feature_transform_version", "ANALOG_FEATURE_TRANSFORM_MISMATCH"),
        ("lookback_bars", "ANALOG_LOOKBACK_BARS_MISMATCH"),
        ("lookback_seconds", "ANALOG_LOOKBACK_SECONDS_MISMATCH"),
    ):
        if feature_contract.get(field) != current.get(field):
            reasons.append(reason)
    outcome_reasons, outcome_contract = _validate_outcome_contract(
        candidate,
        prefix="ANALOG",
    )
    reasons.extend(outcome_reasons)
    for field, reason in (
        ("outcome_schema_sha256", "ANALOG_OUTCOME_SCHEMA_MISMATCH"),
        ("outcome_name", "ANALOG_OUTCOME_NAME_MISMATCH"),
        ("outcome_unit", "ANALOG_OUTCOME_UNIT_MISMATCH"),
        ("outcome_transform_version", "ANALOG_OUTCOME_TRANSFORM_MISMATCH"),
        ("outcome_price_source", "ANALOG_OUTCOME_PRICE_SOURCE_MISMATCH"),
        ("outcome_return_convention", "ANALOG_OUTCOME_RETURN_CONVENTION_MISMATCH"),
    ):
        if outcome_contract.get(field) != current.get(field):
            reasons.append(reason)
    label = _finite(candidate.forward_return_bps)
    if label is None:
        reasons.append("ANALOG_FORWARD_RETURN_INVALID")
    if candidate.candle_closed_confirmed is not True:
        reasons.append("ANALOG_FEATURE_CANDLE_NOT_FINAL")
    if candidate.latest_unclosed_candle_excluded is not True:
        reasons.append("ANALOG_UNCLOSED_CANDLE_NOT_EXCLUDED")
    if candidate.outcome_candle_closed_confirmed is not True:
        reasons.append("ANALOG_OUTCOME_CANDLE_NOT_FINAL")
    if candidate.lineage_valid is not True:
        reasons.append("ANALOG_LINEAGE_INVALID")
    if candidate.dirty is not False:
        reasons.append("ANALOG_DIRTY")
    missing_contract_valid, missing_present = _field_names_state(candidate.missing_required_fields)
    stale_contract_valid, stale_present = _field_names_state(candidate.stale_required_fields)
    if not missing_contract_valid:
        reasons.append("ANALOG_MISSING_REQUIRED_FIELDS_CONTRACT_INVALID")
    elif missing_present:
        reasons.append("ANALOG_REQUIRED_FIELDS_MISSING")
    if not stale_contract_valid:
        reasons.append("ANALOG_STALE_REQUIRED_FIELDS_CONTRACT_INVALID")
    elif stale_present:
        reasons.append("ANALOG_REQUIRED_FIELDS_STALE")

    clock_names = (
        "feature_window_start",
        "feature_cutoff",
        "event_time",
        "ingested_at",
        "available_at",
        "decision_time",
        "outcome_start_time",
        "outcome_end_time",
        "outcome_available_at",
    )
    clocks = _parse_named_clocks(candidate, clock_names, "ANALOG", reasons)
    if len(clocks) == len(clock_names):
        decision_time = current["clocks"]["decision_time"]
        generated_at = current["generated_at"]
        current_window_start = current["clocks"]["feature_window_start"]
        if clocks["feature_window_start"] > clocks["feature_cutoff"]:
            reasons.append("ANALOG_FEATURE_WINDOW_START_AFTER_CUTOFF")
        if clocks["feature_window_start"] > clocks["event_time"]:
            reasons.append("ANALOG_FEATURE_WINDOW_START_AFTER_EVENT_TIME")
        if clocks["event_time"] > clocks["feature_cutoff"]:
            reasons.append("ANALOG_EVENT_TIME_AFTER_FEATURE_CUTOFF")
        if clocks["feature_cutoff"] > clocks["ingested_at"]:
            reasons.append("ANALOG_FEATURE_CUTOFF_AFTER_INGESTED_AT")
        if clocks["ingested_at"] > clocks["available_at"]:
            reasons.append("ANALOG_INGESTED_AT_AFTER_AVAILABLE_AT")
        if generated_at is not None and clocks["available_at"] > generated_at:
            reasons.append("ANALOG_AVAILABLE_AT_AFTER_GENERATED_AT")
        if clocks["available_at"] > clocks["decision_time"]:
            reasons.append("ANALOG_AVAILABLE_AT_AFTER_ANALOG_DECISION_TIME")
        if clocks["decision_time"] > clocks["outcome_start_time"]:
            reasons.append("ANALOG_DECISION_TIME_AFTER_OUTCOME_START_TIME")
        if clocks["outcome_start_time"] >= clocks["outcome_end_time"]:
            reasons.append("ANALOG_OUTCOME_NOT_FORWARD")
        if (
            horizon is not None
            and (
                clocks["outcome_end_time"] - clocks["outcome_start_time"]
            ).total_seconds()
            != horizon
        ):
            reasons.append("ANALOG_OUTCOME_HORIZON_MISMATCH")
        if clocks["outcome_end_time"] > clocks["outcome_available_at"]:
            reasons.append("ANALOG_OUTCOME_END_AFTER_AVAILABLE_AT")
        if clocks["available_at"] > clocks["outcome_available_at"]:
            reasons.append("ANALOG_FEATURE_AVAILABLE_AFTER_OUTCOME_AVAILABLE")
        if generated_at is not None and clocks["outcome_available_at"] > generated_at:
            reasons.append("ANALOG_OUTCOME_AVAILABLE_AT_AFTER_GENERATED_AT")
        if clocks["outcome_available_at"] > decision_time:
            reasons.append("ANALOG_OUTCOME_AVAILABLE_AT_AFTER_DECISION_TIME")
        if clocks["outcome_end_time"] >= current_window_start:
            reasons.append("ANALOG_INTERVAL_OVERLAPS_CURRENT_WINDOW")
        if not _lookback_matches_timeframe(
            timeframe=timeframe or "",
            lookback_bars=feature_contract["lookback_bars"],
            lookback_seconds=feature_contract["lookback_seconds"],
            start=clocks["feature_window_start"],
            cutoff=clocks["feature_cutoff"],
        ):
            reasons.append("ANALOG_LOOKBACK_TIMEFRAME_MISMATCH")

    return reasons, {
        "analog_id": analog_id or "",
        "values": values,
        "label": label,
        **feature_contract,
        **outcome_contract,
        "clocks": clocks,
    }


def _forecast_config_payload(
    *,
    k: object,
    min_analogs: object,
    dispersion_ref_bps: object,
    flat_band_bps: object,
) -> dict[str, Any]:
    return {
        "k": _positive_int(k),
        "min_analogs": _positive_int(min_analogs),
        "dispersion_ref_bps": _finite(dispersion_ref_bps),
        "flat_band_bps": _finite(flat_band_bps),
    }


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_hash(
    current: dict[str, Any],
    eligible: Sequence[dict[str, Any]],
    rejected: object,
    forecast_config: Mapping[str, Any],
) -> str:
    payload = {
        "schema_version": PIT_SCHEMA_VERSION,
        "current": {
            "current_window_id": current["current_window_id"],
            "symbol": current["symbol"],
            "timeframe": current["timeframe"],
            "forecast_horizon_seconds": current["horizon"],
            "values": current["values"],
            "feature_schema_sha256": current["feature_schema_sha256"],
            "feature_names": current["feature_names"],
            "feature_units": current["feature_units"],
            "feature_transform_version": current["feature_transform_version"],
            "lookback_bars": current["lookback_bars"],
            "lookback_seconds": current["lookback_seconds"],
            "outcome_schema_sha256": current["outcome_schema_sha256"],
            "outcome_name": current["outcome_name"],
            "outcome_unit": current["outcome_unit"],
            "outcome_transform_version": current["outcome_transform_version"],
            "outcome_price_source": current["outcome_price_source"],
            "outcome_return_convention": current["outcome_return_convention"],
            "clocks": {name: _utc_text(value) for name, value in sorted(current["clocks"].items())},
            "generated_at": _utc_text(current["generated_at"]),
        },
        "eligible_analogs": [
            {
                "analog_id": item["analog_id"],
                "values": item["values"],
                "forward_return_bps": item["label"],
                "feature_schema_sha256": item["feature_schema_sha256"],
                "feature_names": item["feature_names"],
                "feature_units": item["feature_units"],
                "feature_transform_version": item["feature_transform_version"],
                "lookback_bars": item["lookback_bars"],
                "lookback_seconds": item["lookback_seconds"],
                "outcome_schema_sha256": item["outcome_schema_sha256"],
                "outcome_name": item["outcome_name"],
                "outcome_unit": item["outcome_unit"],
                "outcome_transform_version": item["outcome_transform_version"],
                "outcome_price_source": item["outcome_price_source"],
                "outcome_return_convention": item["outcome_return_convention"],
                "clocks": {
                    name: _utc_text(value) for name, value in sorted(item["clocks"].items())
                },
            }
            for item in eligible
        ],
        "rejected_analogs": rejected,
        "forecast_config": dict(forecast_config),
    }
    return _payload_sha256(payload)


def _compute_pit_safe_impl(
    *,
    current: PITCurrentWindow,
    candidates: Sequence[PITAnalogCandidate],
    generated_at: TimestampLike,
    k: int,
    min_analogs: int,
    dispersion_ref_bps: float,
    flat_band_bps: float,
) -> PITAnalogForecast:
    current_reasons, normalized_current, generated = _validate_current(current, generated_at)
    if current_reasons:
        return _invalid_pit_output(
            reasons=current_reasons,
            current=current,
            generated_at=generated,
            parsed_current=normalized_current.get("clocks", {}),
        )
    if not _is_sequence(candidates):
        return _invalid_pit_output(
            reasons=("ANALOG_CANDIDATES_MUST_BE_SEQUENCE",),
            current=current,
            generated_at=generated,
            parsed_current=normalized_current["clocks"],
        )

    candidate_ids = [
        _clean_identity(candidate.analog_id)
        for candidate in candidates
        if isinstance(candidate, PITAnalogCandidate)
    ]
    id_counts = Counter(identity for identity in candidate_ids if identity is not None)
    rejected_by_index: dict[int, list[str]] = {}
    normalized_by_index: dict[int, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        identity = (
            _clean_identity(candidate.analog_id)
            if isinstance(candidate, PITAnalogCandidate)
            else None
        )
        reasons, normalized = _validate_candidate(
            candidate,
            current=normalized_current,
            duplicate_id=identity is not None and id_counts[identity] > 1,
        )
        if reasons:
            rejected_by_index[index] = list(_stable_reasons(reasons))
        else:
            normalized_by_index[index] = normalized

    # Retain one deterministic representative of an exact numeric duplicate.
    numeric_groups: dict[tuple[tuple[float, ...], float], list[int]] = {}
    for index, item in normalized_by_index.items():
        key = (tuple(item["values"]), float(item["label"]))
        numeric_groups.setdefault(key, []).append(index)
    for indexes in numeric_groups.values():
        if len(indexes) <= 1:
            continue
        ranked = sorted(
            indexes,
            key=lambda idx: (
                normalized_by_index[idx]["clocks"]["feature_cutoff"],
                normalized_by_index[idx]["analog_id"],
            ),
            reverse=True,
        )
        for duplicate_index in ranked[1:]:
            rejected_by_index.setdefault(duplicate_index, []).append(
                "EXACT_DUPLICATE_ANALOG_DROPPED"
            )
            normalized_by_index.pop(duplicate_index, None)

    # Deterministic newest-first interval scheduling prevents candidate outcomes
    # and feature windows from being counted as independent when they overlap.
    ranked_indexes = sorted(
        normalized_by_index,
        key=lambda idx: (
            normalized_by_index[idx]["clocks"]["feature_window_start"],
            normalized_by_index[idx]["clocks"]["outcome_end_time"],
            normalized_by_index[idx]["analog_id"],
        ),
        reverse=True,
    )
    kept_indexes: list[int] = []
    next_newer_start: datetime | None = None
    for index in ranked_indexes:
        item = normalized_by_index[index]
        interval_end = item["clocks"]["outcome_end_time"]
        if next_newer_start is not None and interval_end >= next_newer_start:
            rejected_by_index.setdefault(index, []).append("ANALOG_INTERVAL_OVERLAPS_ANOTHER")
            continue
        kept_indexes.append(index)
        next_newer_start = item["clocks"]["feature_window_start"]
    kept_indexes.sort(
        key=lambda idx: (
            normalized_by_index[idx]["clocks"]["feature_cutoff"],
            normalized_by_index[idx]["analog_id"],
        )
    )
    eligible = [normalized_by_index[index] for index in kept_indexes]

    rejected = tuple(
        sorted(
            (
                _candidate_identity(candidates[index], index),
                _stable_reasons(reasons),
            )
            for index, reasons in rejected_by_index.items()
        )
    )
    forecast = _compute_analog_forecast_impl(
        current_window=normalized_current["values"],
        historical_windows=[item["values"] for item in eligible],
        forward_return_bps=[item["label"] for item in eligible],
        k=k,
        min_analogs=min_analogs,
        dispersion_ref_bps=dispersion_ref_bps,
        flat_band_bps=flat_band_bps,
        overlap_checked=True,
    )
    selected_ids = tuple(
        eligible[index]["analog_id"]
        for index in forecast.selected_analog_indices
        if 0 <= index < len(eligible)
    )
    top_reasons = list(forecast.reason_codes)
    if rejected:
        top_reasons.append("ANALOG_CANDIDATES_REJECTED")
    reason_codes = _stable_reasons(top_reasons)
    forecast_config = _forecast_config_payload(
        k=k,
        min_analogs=min_analogs,
        dispersion_ref_bps=dispersion_ref_bps,
        flat_band_bps=flat_band_bps,
    )
    forecast_config_hash = _payload_sha256(forecast_config)
    input_hash = _canonical_hash(
        normalized_current,
        eligible,
        rejected,
        forecast_config,
    )
    clocks = normalized_current["clocks"]
    return PITAnalogForecast(
        forecast=forecast,
        status=forecast.status,
        reason_codes=reason_codes,
        current_window_id=normalized_current["current_window_id"],
        symbol=normalized_current["symbol"],
        timeframe=normalized_current["timeframe"],
        forecast_horizon_seconds=normalized_current["horizon"],
        event_time=_utc_text(clocks["event_time"]),
        ingested_at=_utc_text(clocks["ingested_at"]),
        input_available_at=_utc_text(clocks["available_at"]),
        available_at=_utc_text(generated),
        feature_cutoff=_utc_text(clocks["feature_cutoff"]),
        decision_time=_utc_text(clocks["decision_time"]),
        generated_at=_utc_text(generated),
        input_sha256=input_hash,
        forecast_config_sha256=forecast_config_hash,
        eligible_analog_ids=tuple(item["analog_id"] for item in eligible),
        selected_analog_ids=selected_ids,
        rejected_analogs=rejected,
        overlap_checked=True,
    )


def compute_pit_safe_analog_forecast(
    *,
    current: PITCurrentWindow,
    candidates: Sequence[PITAnalogCandidate],
    generated_at: TimestampLike,
    k: int = 25,
    min_analogs: int = 8,
    dispersion_ref_bps: float = 120.0,
    flat_band_bps: float = 5.0,
) -> PITAnalogForecast:
    """Compute a fail-closed, timestamped, non-overlapping analogue forecast.

    All timestamps must be timezone-aware ISO-8601 strings or aware ``datetime``
    objects.  They are normalized to UTC in the output.  Invalid/dirty/current
    rows fail the whole request; invalid candidates are explicitly rejected and
    the forecast proceeds only when enough independent candidates remain.
    """

    try:
        return _compute_pit_safe_impl(
            current=current,
            candidates=candidates,
            generated_at=generated_at,
            k=k,
            min_analogs=min_analogs,
            dispersion_ref_bps=dispersion_ref_bps,
            flat_band_bps=flat_band_bps,
        )
    except Exception:
        return _invalid_pit_output(
            reasons=("PIT_INPUT_ACCESS_OR_NUMERICAL_ERROR",),
            current=current,
            generated_at=_parse_utc(generated_at),
        )
