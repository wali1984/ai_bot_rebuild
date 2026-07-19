"""Versioned core-TA minimum coverage and contiguous-input binding.

This module describes the minimum finalized source-candle coverage needed for
the core native OHLCV/TA derivations in ``_features_from_market``. Its 71-row
minimum is derived from RSI(14) applied to
the positional ``closes[::5]`` proxy in ``v2_feature_pipeline_native_loop``:
RSI(14) needs 15 transformed closes and indices ``0, 5, ..., 70`` need 71
source rows. It is a minimum-coverage invariant, not the exact row count the
current recursive and phase-anchored algorithms consume, and not a market-quality,
liquidity, admission, risk, leverage, or trading threshold.

The read-only inspection API accepts canonical closed-candle dictionaries and
reports every gap plus the entire exact latest contiguous suffix. Raw Binance list
rows are deliberately rejected: they do not carry canonical ``candle_id`` or
``available_at`` fields and therefore cannot produce an honest identity or
point-in-time binding.  Full 30-field source-schema validation remains the
responsibility of :mod:`ohlcv_closed_window_schema`; this module validates only
the timing and identity projection needed for continuity and selection.

``consumer_observed_at_ms`` means when the caller possessed the source value.
It is not ``event_time``, ``ingested_at``, ``generated_at``, feature cutoff,
trainer decision time, or execution time.  End-exclusive finality is enforced
as ``candle_close_time + 1 <= consumer_observed_at_ms`` (equivalently,
``candle_close_time < consumer_observed_at_ms``). Availability cannot precede
that end-exclusive finality instant or follow the observation clock.

The full suffix must be supplied unchanged to current core algorithms: trimming
an 80- or 100-row suffix to 71 changes recursive TA values and changes the
``closes[::5]`` phase. Structure, FVG, liquidity-zone, VWAP, volume-profile,
and CVD derivations consume separately selected full lists (currently up to
100/240/500 rows) and
are explicitly outside this core minimum contract; each needs its own exact
selected-count/candle-chain manifest.

When an internal gap exists, the full *post-gap* suffix excludes every pre-gap
row. The current worker instead supplies its full raw list, so wiring this
selection is a versioned input-selection behavior change that must be reviewed
and authorized; callers must not splice the excluded prefix back in.

The returned hashes are deterministic bindings, not source-authenticity
proofs, immutable CAS receipts, trainer-admission grants, or live authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from itertools import islice
from typing import Final, NoReturn, cast

from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_ROWS,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
)

CORE_TA_MINIMUM_COVERAGE_CONTRACT_VERSION = "trainer_core_ta_minimum_coverage_v1"
CONTIGUOUS_SUFFIX_INSPECTION_VERSION = "trainer_contiguous_suffix_inspection_v1"
FULL_CONTIGUOUS_CORE_INPUT_BINDING_VERSION = "trainer_full_contiguous_core_input_v1"
CANDLE_ID_CHAIN_VERSION = "trainer_candle_id_chain_v1"

DEPENDENCY_CLASSIFICATION = "CORE_TA_MINIMUM_COVERAGE_INVARIANT"
DEPENDENCY_SCOPE = "CORE_NATIVE_OHLCV_DERIVATIONS_FEATURES_FROM_MARKET"
EXTERNAL_FULL_LIST_DERIVATIONS: Final = (
    ("market_structure", 100),
    ("fair_value_gap", 100),
    ("liquidity_zones", 100),
    ("vwap", 240),
    ("volume_profile", 240),
    ("cvd", 500),
)
EXTERNAL_DERIVATION_SEMANTICS = (
    "NOT_COVERED_SEPARATE_EXACT_SELECTED_COUNT_AND_CANDLE_ID_CHAIN_MANIFEST_REQUIRED"
)
FINALITY_SEMANTICS = (
    "END_EXCLUSIVE_CANDLE_CLOSE_PLUS_ONE_LE_CONSUMER_OBSERVED_AT_AND_"
    "CANDLE_CLOSE_PLUS_ONE_LE_AVAILABLE_AT_LE_CONSUMER_OBSERVED_AT"
)

# These constants mirror parameters in the current feature implementation.
# They are transform definitions, not tunable market-selection cutoffs.
RSI_PERIOD: Final = 14
HTF_POSITIONAL_STRIDE: Final = 5
MACD_FAST_PERIOD: Final = 12
MACD_SLOW_PERIOD: Final = 26
MACD_SIGNAL_PERIOD: Final = 9
ATR_PERIOD: Final = 14
ATR_PERCENTILE_MIN_SAMPLES: Final = 20
BOLLINGER_PERIOD: Final = 20
EMA_SLOW_PERIOD: Final = 26

RSI_REQUIRED_CLOSES: Final = RSI_PERIOD + 1
HTF_RSI_MINIMUM_SOURCE_ROWS: Final = (RSI_REQUIRED_CLOSES - 1) * HTF_POSITIONAL_STRIDE + 1
CORE_TA_MINIMUM_SOURCE_ROWS: Final = HTF_RSI_MINIMUM_SOURCE_ROWS

assert CORE_TA_MINIMUM_SOURCE_ROWS == 71

_MAX_SIGNED_64 = (1 << 63) - 1
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_MAX_CANONICAL_PROJECTION_FIELDS = 64


class FeatureWindowContractError(ValueError):
    """The dependency, continuity, finality, or identity contract failed."""


@dataclass(frozen=True, slots=True)
class CoreTATransformMinimum:
    """One core TA transform's minimum source-row coverage."""

    feature_name: str
    minimum_source_rows: int
    derivation: str
    parameters: tuple[tuple[str, int | str], ...]


@dataclass(frozen=True, slots=True)
class CoreTAMinimumCoverageContract:
    """Deterministic, timeframe-bound core TA minimum-coverage contract."""

    schema_version: str
    dependency_classification: str
    dependency_scope: str
    market_selection_threshold: bool
    timeframe: str
    timeframe_duration_ms: int
    minimum_source_rows: int
    dependencies: tuple[CoreTATransformMinimum, ...]
    external_full_list_derivations: tuple[tuple[str, int], ...]
    external_derivation_semantics: str
    all_feature_families_covered: bool
    candle_open_alignment_semantics: str
    candle_close_alignment_semantics: str
    finality_semantics: str
    contract_material_json: str
    contract_sha256: str
    grants_market_admission: bool = field(default=False, init=False)
    grants_trainer_admission: bool = field(default=False, init=False)
    grants_live_execution: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CanonicalCandleIdentity:
    """Immutable timing/identity projection of one caller-owned canonical row."""

    source_index: int
    symbol: str
    timeframe: str
    candle_id: str
    candle_open_time: int
    candle_close_time: int
    available_at: int


@dataclass(frozen=True, slots=True)
class CanonicalContiguousSuffixInspection:
    """Read-only gap census and exact latest contiguous identity suffix."""

    schema_version: str
    contract_version: str
    contract_sha256: str
    contract_material_json: str
    dependency_classification: str
    dependency_scope: str
    market_selection_threshold: bool
    all_feature_families_covered: bool
    external_full_list_derivations: tuple[tuple[str, int], ...]
    external_derivation_semantics: str
    symbol: str
    timeframe: str
    timeframe_duration_ms: int
    consumer_observed_at_ms: int
    expected_latest_finalized_close_time: int
    raw_row_count: int
    gap_count: int
    gap_indices: tuple[int, ...]
    gap_missing_interval_counts: tuple[int, ...]
    missing_interval_count: int
    tail_missing_interval_count: int | None
    latest_candle_matches_expected_cutoff: bool
    contiguous_suffix_start_index: int
    contiguous_suffix_count: int
    selected_suffix_rows: tuple[CanonicalCandleIdentity, ...]
    selected_suffix_count: int
    selected_candle_ids: tuple[str, ...]
    selected_candle_id_chain_material_json: str
    selected_candle_id_chain_sha256: str
    core_ta_minimum_source_rows: int
    core_ta_minimum_coverage_ready: bool
    source_schema_fully_validated: bool = field(default=False, init=False)
    immutable_cas_captured: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class FullContiguousCoreInputBinding:
    """Entire latest contiguous core input and deterministic identity binding."""

    schema_version: str
    contract_version: str
    contract_sha256: str
    contract_material_json: str
    dependency_classification: str
    dependency_scope: str
    market_selection_threshold: bool
    all_feature_families_covered: bool
    external_full_list_derivations: tuple[tuple[str, int], ...]
    external_derivation_semantics: str
    symbol: str
    timeframe: str
    timeframe_duration_ms: int
    consumer_observed_at_ms: int
    expected_latest_finalized_close_time: int
    raw_row_count: int
    gap_count: int
    gap_indices: tuple[int, ...]
    gap_missing_interval_counts: tuple[int, ...]
    missing_interval_count: int
    tail_missing_interval_count: int
    latest_candle_matches_expected_cutoff: bool
    contiguous_suffix_start_index: int
    contiguous_suffix_count: int
    selected_source_start_index: int
    selected_source_end_index_exclusive: int
    selected_rows: tuple[CanonicalCandleIdentity, ...]
    selected_row_count: int
    selected_candle_ids: tuple[str, ...]
    selected_candle_id_chain_material_json: str
    selected_candle_id_chain_sha256: str
    first_selected_economic_close_time: int
    latest_selected_economic_close_time: int
    latest_selected_end_exclusive_finality_time: int
    max_selected_available_at: int
    selection_material_json: str
    selection_sha256: str
    entire_contiguous_suffix_bound: bool = field(default=True, init=False)
    source_schema_fully_validated: bool = field(default=False, init=False)
    immutable_cas_captured: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


def _invalid(reason: str) -> NoReturn:
    raise FeatureWindowContractError(reason) from None


def _canonical_json(material: object) -> str:
    try:
        return json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _invalid("feature_window_material_invalid")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def _validated_timeframe(value: object) -> str:
    if type(value) is not str or value not in SUPPORTED_TRAINER_TIMEFRAMES:
        _invalid("feature_window_timeframe_invalid")
    return value


def _validated_symbol(value: object) -> str:
    if type(value) is not str or not value.isascii() or _SYMBOL_RE.fullmatch(value) is None:
        _invalid("feature_window_expected_symbol_invalid")
    return value


def _validated_clock(
    value: object,
    *,
    field_name: str,
    allow_unix_epoch_zero: bool = False,
) -> int:
    minimum = 0 if allow_unix_epoch_zero else 1
    if type(value) is not int or not minimum <= value <= _MAX_SIGNED_64:
        _invalid(f"feature_window_{field_name}_invalid")
    return value


def _dependencies() -> tuple[CoreTATransformMinimum, ...]:
    dependencies = (
        CoreTATransformMinimum(
            feature_name="latest_candle_range_body",
            minimum_source_rows=1,
            derivation="latest finalized candle",
            parameters=(),
        ),
        CoreTATransformMinimum(
            feature_name="close_to_close_returns",
            minimum_source_rows=2,
            derivation="current and immediately prior finalized close",
            parameters=(("close_count", 2),),
        ),
        CoreTATransformMinimum(
            feature_name="htf_ret_pct",
            minimum_source_rows=HTF_POSITIONAL_STRIDE,
            derivation="closes[-1] divided by closes[-5]",
            parameters=(("positional_lag", HTF_POSITIONAL_STRIDE),),
        ),
        CoreTATransformMinimum(
            feature_name="rsi_14",
            minimum_source_rows=RSI_REQUIRED_CLOSES,
            derivation="RSI period plus one close",
            parameters=(("period", RSI_PERIOD),),
        ),
        CoreTATransformMinimum(
            feature_name="atr_14",
            minimum_source_rows=ATR_PERIOD + 1,
            derivation="ATR period true ranges require period plus one candle",
            parameters=(("period", ATR_PERIOD),),
        ),
        CoreTATransformMinimum(
            feature_name="sma_20_and_bollinger_width",
            minimum_source_rows=BOLLINGER_PERIOD,
            derivation="twenty-close rolling window",
            parameters=(("period", BOLLINGER_PERIOD),),
        ),
        CoreTATransformMinimum(
            feature_name="ema_26",
            minimum_source_rows=EMA_SLOW_PERIOD,
            derivation="slow EMA seed requires period closes",
            parameters=(("period", EMA_SLOW_PERIOD),),
        ),
        CoreTATransformMinimum(
            feature_name="atr_percentile",
            minimum_source_rows=ATR_PERIOD + ATR_PERCENTILE_MIN_SAMPLES,
            derivation="period true-range warmup plus percentile sample count",
            parameters=(
                ("period", ATR_PERIOD),
                ("minimum_percentile_samples", ATR_PERCENTILE_MIN_SAMPLES),
            ),
        ),
        CoreTATransformMinimum(
            feature_name="macd_12_26_9",
            minimum_source_rows=MACD_SLOW_PERIOD + MACD_SIGNAL_PERIOD,
            derivation="current implementation gates on slow plus signal periods",
            parameters=(
                ("fast_period", MACD_FAST_PERIOD),
                ("slow_period", MACD_SLOW_PERIOD),
                ("signal_period", MACD_SIGNAL_PERIOD),
            ),
        ),
        CoreTATransformMinimum(
            feature_name="htf_rsi_14_positional_5x_proxy",
            minimum_source_rows=HTF_RSI_MINIMUM_SOURCE_ROWS,
            derivation=("(RSI required transformed closes - 1) * positional stride + 1"),
            parameters=(
                ("transform", "closes[::5]"),
                ("rsi_period", RSI_PERIOD),
                ("required_transformed_closes", RSI_REQUIRED_CLOSES),
                ("positional_stride", HTF_POSITIONAL_STRIDE),
            ),
        ),
    )
    if max(item.minimum_source_rows for item in dependencies) != 71:
        _invalid("feature_window_dependency_derivation_invalid")
    return dependencies


def build_core_ta_minimum_coverage_contract(
    *,
    timeframe: object,
) -> CoreTAMinimumCoverageContract:
    """Build the deterministic core-TA minimum contract for one timeframe."""

    validated_timeframe = _validated_timeframe(timeframe)
    duration_ms = TIMEFRAME_DURATION_MS[validated_timeframe]
    dependencies = _dependencies()
    minimum_source_rows = max(item.minimum_source_rows for item in dependencies)
    material = {
        "schema_version": CORE_TA_MINIMUM_COVERAGE_CONTRACT_VERSION,
        "dependency_classification": DEPENDENCY_CLASSIFICATION,
        "dependency_scope": DEPENDENCY_SCOPE,
        "market_selection_threshold": False,
        "all_feature_families_covered": False,
        "timeframe": validated_timeframe,
        "timeframe_duration_ms": duration_ms,
        "minimum_source_rows": minimum_source_rows,
        "dependencies": [
            {
                "feature_name": item.feature_name,
                "minimum_source_rows": item.minimum_source_rows,
                "derivation": item.derivation,
                "parameters": {key: value for key, value in item.parameters},
            }
            for item in dependencies
        ],
        "excluded_external_full_list_derivations": [
            {
                "feature_family": feature_family,
                "current_caller_max_rows": current_caller_max_rows,
                "covered_by_this_contract": False,
            }
            for feature_family, current_caller_max_rows in EXTERNAL_FULL_LIST_DERIVATIONS
        ],
        "external_derivation_semantics": EXTERNAL_DERIVATION_SEMANTICS,
        "alignment_and_finality": {
            "candle_open_time": "candle_open_time % timeframe_duration_ms == 0",
            "candle_close_time": (
                "candle_close_time == candle_open_time + timeframe_duration_ms - 1"
            ),
            "finality": FINALITY_SEMANTICS,
        },
    }
    material_json = _canonical_json(material)
    return CoreTAMinimumCoverageContract(
        schema_version=CORE_TA_MINIMUM_COVERAGE_CONTRACT_VERSION,
        dependency_classification=DEPENDENCY_CLASSIFICATION,
        dependency_scope=DEPENDENCY_SCOPE,
        market_selection_threshold=False,
        timeframe=validated_timeframe,
        timeframe_duration_ms=duration_ms,
        minimum_source_rows=minimum_source_rows,
        dependencies=dependencies,
        external_full_list_derivations=EXTERNAL_FULL_LIST_DERIVATIONS,
        external_derivation_semantics=EXTERNAL_DERIVATION_SEMANTICS,
        all_feature_families_covered=False,
        candle_open_alignment_semantics=("candle_open_time % timeframe_duration_ms == 0"),
        candle_close_alignment_semantics=(
            "candle_close_time == candle_open_time + timeframe_duration_ms - 1"
        ),
        finality_semantics=FINALITY_SEMANTICS,
        contract_material_json=material_json,
        contract_sha256=_sha256_text(material_json),
    )


def _bounded_row_snapshot(rows: object) -> tuple[object, ...]:
    if type(rows) is tuple:
        snapshot = cast(tuple[object, ...], rows)
    elif type(rows) is list:
        snapshot = tuple(cast(list[object], rows)[: MAX_OHLCV_CLOSED_ROWS + 1])
    else:
        _invalid("feature_window_rows_container_invalid")
    if len(snapshot) > MAX_OHLCV_CLOSED_ROWS:
        _invalid("feature_window_row_count_invalid")
    return snapshot


def _bounded_projection(row: object) -> dict[str, object]:
    if type(row) is not dict:
        # Binance REST/WSS list rows have no canonical candle identity or
        # available_at clock, so accepting them would create false evidence.
        _invalid("feature_window_row_requires_canonical_dict")
    raw = cast(dict[object, object], row)
    if len(raw) > _MAX_CANONICAL_PROJECTION_FIELDS:
        _invalid("feature_window_row_field_count_invalid")
    try:
        pairs = tuple(islice(raw.items(), _MAX_CANONICAL_PROJECTION_FIELDS + 1))
    except RuntimeError:
        _invalid("feature_window_row_mutated_during_snapshot")
    if len(pairs) != len(raw) or len(pairs) > _MAX_CANONICAL_PROJECTION_FIELDS:
        _invalid("feature_window_row_mutated_during_snapshot")
    projection: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is str and key in {
            "symbol",
            "timeframe",
            "candle_id",
            "candle_open_time",
            "candle_close_time",
            "available_at",
        }:
            projection[key] = value
    return projection


def _canonical_identity(
    raw_row: object,
    *,
    source_index: int,
    expected_timeframe: str,
    duration_ms: int,
    consumer_observed_at_ms: int,
    expected_symbol: str,
) -> CanonicalCandleIdentity:
    row = _bounded_projection(raw_row)
    required_keys = {
        "symbol",
        "timeframe",
        "candle_id",
        "candle_open_time",
        "candle_close_time",
        "available_at",
    }
    if set(row) != required_keys:
        _invalid("feature_window_canonical_projection_missing")

    symbol = row["symbol"]
    timeframe = row["timeframe"]
    candle_id = row["candle_id"]
    if type(symbol) is not str or not symbol.isascii() or _SYMBOL_RE.fullmatch(symbol) is None:
        _invalid("feature_window_symbol_invalid")
    if symbol != expected_symbol:
        _invalid("feature_window_rows_symbol_mismatch")
    if type(timeframe) is not str or timeframe != expected_timeframe:
        _invalid("feature_window_rows_timeframe_mismatch")
    if type(candle_id) is not str or _CANDLE_ID_RE.fullmatch(candle_id) is None:
        _invalid("feature_window_candle_id_invalid")

    candle_open_time = _validated_clock(
        row["candle_open_time"],
        field_name="candle_open_time",
        allow_unix_epoch_zero=True,
    )
    candle_close_time = _validated_clock(
        row["candle_close_time"],
        field_name="candle_close_time",
        allow_unix_epoch_zero=True,
    )
    available_at = _validated_clock(
        row["available_at"],
        field_name="available_at",
        allow_unix_epoch_zero=True,
    )
    if candle_open_time % duration_ms != 0:
        _invalid("feature_window_candle_open_alignment_invalid")
    if candle_close_time != candle_open_time + duration_ms - 1:
        _invalid("feature_window_candle_close_alignment_invalid")
    if candle_close_time >= consumer_observed_at_ms:
        _invalid("feature_window_candle_not_final_at_consumer_observation")
    if available_at < candle_close_time + 1:
        _invalid("feature_window_available_at_precedes_end_exclusive_finality")
    if available_at > consumer_observed_at_ms:
        _invalid("feature_window_available_after_consumer_observation")

    return CanonicalCandleIdentity(
        source_index=source_index,
        symbol=symbol,
        timeframe=timeframe,
        candle_id=candle_id,
        candle_open_time=candle_open_time,
        candle_close_time=candle_close_time,
        available_at=available_at,
    )


def _candle_id_chain(
    *,
    symbol: str,
    timeframe: str,
    rows: tuple[CanonicalCandleIdentity, ...],
) -> tuple[str, str]:
    material = {
        "schema_version": CANDLE_ID_CHAIN_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_count": len(rows),
        "candle_ids": [row.candle_id for row in rows],
    }
    material_json = _canonical_json(material)
    return material_json, _sha256_text(material_json)


def inspect_canonical_contiguous_suffix(
    canonical_rows: object,
    *,
    expected_symbol: object,
    timeframe: object,
    consumer_observed_at_ms: object,
    expected_latest_finalized_close_time: object,
) -> CanonicalContiguousSuffixInspection:
    """Report every gap and the exact latest canonical contiguous suffix.

    A short or stale suffix is reportable for coverage/backfill callers but is
    never marked core-TA ready. Invalid timing, identity, alignment, or
    finality evidence fails closed.
    """

    contract = build_core_ta_minimum_coverage_contract(timeframe=timeframe)
    bound_symbol = _validated_symbol(expected_symbol)
    observed_at = _validated_clock(
        consumer_observed_at_ms,
        field_name="consumer_observed_at_ms",
    )
    expected_latest_close = _validated_clock(
        expected_latest_finalized_close_time,
        field_name="expected_latest_finalized_close_time",
        allow_unix_epoch_zero=True,
    )
    if (expected_latest_close + 1) % contract.timeframe_duration_ms != 0:
        _invalid("feature_window_expected_latest_close_alignment_invalid")
    if expected_latest_close >= observed_at:
        _invalid("feature_window_expected_latest_close_not_final")
    raw_rows = _bounded_row_snapshot(canonical_rows)

    identities: list[CanonicalCandleIdentity] = []
    gap_indices: list[int] = []
    gap_missing_counts: list[int] = []
    seen_candle_ids: set[str] = set()
    previous_open: int | None = None
    for index, raw_row in enumerate(raw_rows):
        identity = _canonical_identity(
            raw_row,
            source_index=index,
            expected_timeframe=contract.timeframe,
            duration_ms=contract.timeframe_duration_ms,
            consumer_observed_at_ms=observed_at,
            expected_symbol=bound_symbol,
        )
        if identity.candle_id in seen_candle_ids:
            _invalid("feature_window_candle_ids_duplicate")
        seen_candle_ids.add(identity.candle_id)
        if previous_open is not None:
            if identity.candle_open_time <= previous_open:
                _invalid("feature_window_rows_not_strictly_increasing")
            distance = identity.candle_open_time - previous_open
            if distance != contract.timeframe_duration_ms:
                gap_indices.append(index)
                gap_missing_counts.append((distance // contract.timeframe_duration_ms) - 1)
        identities.append(identity)
        previous_open = identity.candle_open_time

    frozen_identities = tuple(identities)
    frozen_gap_indices = tuple(gap_indices)
    frozen_gap_missing_counts = tuple(gap_missing_counts)
    suffix_start = frozen_gap_indices[-1] if frozen_gap_indices else 0
    selected_suffix = frozen_identities[suffix_start:]
    if frozen_identities:
        latest_close = frozen_identities[-1].candle_close_time
        if latest_close > expected_latest_close:
            _invalid("feature_window_source_close_after_expected_cutoff")
        tail_missing_interval_count: int | None = (
            expected_latest_close - latest_close
        ) // contract.timeframe_duration_ms
    else:
        tail_missing_interval_count = None
    latest_matches_expected = tail_missing_interval_count == 0
    core_ta_ready = latest_matches_expected and len(selected_suffix) >= contract.minimum_source_rows
    chain_material_json, chain_sha256 = _candle_id_chain(
        symbol=bound_symbol,
        timeframe=contract.timeframe,
        rows=selected_suffix,
    )
    return CanonicalContiguousSuffixInspection(
        schema_version=CONTIGUOUS_SUFFIX_INSPECTION_VERSION,
        contract_version=contract.schema_version,
        contract_sha256=contract.contract_sha256,
        contract_material_json=contract.contract_material_json,
        dependency_classification=contract.dependency_classification,
        dependency_scope=contract.dependency_scope,
        market_selection_threshold=contract.market_selection_threshold,
        all_feature_families_covered=contract.all_feature_families_covered,
        external_full_list_derivations=contract.external_full_list_derivations,
        external_derivation_semantics=contract.external_derivation_semantics,
        symbol=bound_symbol,
        timeframe=contract.timeframe,
        timeframe_duration_ms=contract.timeframe_duration_ms,
        consumer_observed_at_ms=observed_at,
        expected_latest_finalized_close_time=expected_latest_close,
        raw_row_count=len(frozen_identities),
        gap_count=len(frozen_gap_indices),
        gap_indices=frozen_gap_indices,
        gap_missing_interval_counts=frozen_gap_missing_counts,
        missing_interval_count=sum(frozen_gap_missing_counts),
        tail_missing_interval_count=tail_missing_interval_count,
        latest_candle_matches_expected_cutoff=latest_matches_expected,
        contiguous_suffix_start_index=suffix_start,
        contiguous_suffix_count=len(selected_suffix),
        selected_suffix_rows=selected_suffix,
        selected_suffix_count=len(selected_suffix),
        selected_candle_ids=tuple(row.candle_id for row in selected_suffix),
        selected_candle_id_chain_material_json=chain_material_json,
        selected_candle_id_chain_sha256=chain_sha256,
        core_ta_minimum_source_rows=contract.minimum_source_rows,
        core_ta_minimum_coverage_ready=core_ta_ready,
    )


def bind_full_contiguous_core_ta_input(
    canonical_rows: object,
    *,
    expected_symbol: object,
    timeframe: object,
    consumer_observed_at_ms: object,
    expected_latest_finalized_close_time: object,
) -> FullContiguousCoreInputBinding:
    """Bind the entire latest contiguous suffix without altering TA inputs."""

    inspection = inspect_canonical_contiguous_suffix(
        canonical_rows,
        expected_symbol=expected_symbol,
        timeframe=timeframe,
        consumer_observed_at_ms=consumer_observed_at_ms,
        expected_latest_finalized_close_time=expected_latest_finalized_close_time,
    )
    if inspection.tail_missing_interval_count != 0:
        _invalid("feature_window_tail_is_stale")
    if not inspection.core_ta_minimum_coverage_ready:
        _invalid("feature_window_core_ta_minimum_coverage_unavailable")

    # Recursive EMA/RSI/MACD values and the positional closes[::5] phase depend
    # on the supplied window's start. Bind the full suffix; never trim it to
    # the 71-row minimum here.
    selected = inspection.selected_suffix_rows
    selected_start = selected[0].source_index
    selected_end = selected[-1].source_index + 1
    chain_material_json, chain_sha256 = _candle_id_chain(
        symbol=inspection.symbol,
        timeframe=inspection.timeframe,
        rows=selected,
    )
    selection_material = {
        "schema_version": FULL_CONTIGUOUS_CORE_INPUT_BINDING_VERSION,
        "contract_version": inspection.contract_version,
        "contract_sha256": inspection.contract_sha256,
        "dependency_classification": inspection.dependency_classification,
        "dependency_scope": inspection.dependency_scope,
        "market_selection_threshold": False,
        "all_feature_families_covered": False,
        "excluded_external_full_list_derivations": [
            {
                "feature_family": feature_family,
                "current_caller_max_rows": current_caller_max_rows,
                "covered_by_this_binding": False,
            }
            for feature_family, current_caller_max_rows in (
                inspection.external_full_list_derivations
            )
        ],
        "external_derivation_semantics": inspection.external_derivation_semantics,
        "symbol": inspection.symbol,
        "timeframe": inspection.timeframe,
        "timeframe_duration_ms": inspection.timeframe_duration_ms,
        "consumer_observed_at_ms": inspection.consumer_observed_at_ms,
        "expected_latest_finalized_close_time": (inspection.expected_latest_finalized_close_time),
        "source_continuity": {
            "raw_row_count": inspection.raw_row_count,
            "gap_indices": list(inspection.gap_indices),
            "gap_missing_interval_counts": list(inspection.gap_missing_interval_counts),
            "contiguous_suffix_start_index": (inspection.contiguous_suffix_start_index),
            "contiguous_suffix_count": inspection.contiguous_suffix_count,
            "tail_missing_interval_count": inspection.tail_missing_interval_count,
        },
        "selection": {
            "selected_source_start_index": selected_start,
            "selected_source_end_index_exclusive": selected_end,
            "selected_row_count": len(selected),
            "selected_candle_id_chain_sha256": chain_sha256,
            "rows": [
                {
                    "source_index": row.source_index,
                    "candle_id": row.candle_id,
                    "candle_open_time": row.candle_open_time,
                    "candle_close_time": row.candle_close_time,
                    "available_at": row.available_at,
                }
                for row in selected
            ],
        },
        "finality_semantics": FINALITY_SEMANTICS,
    }
    selection_material_json = _canonical_json(selection_material)
    return FullContiguousCoreInputBinding(
        schema_version=FULL_CONTIGUOUS_CORE_INPUT_BINDING_VERSION,
        contract_version=inspection.contract_version,
        contract_sha256=inspection.contract_sha256,
        contract_material_json=inspection.contract_material_json,
        dependency_classification=inspection.dependency_classification,
        dependency_scope=inspection.dependency_scope,
        market_selection_threshold=False,
        all_feature_families_covered=False,
        external_full_list_derivations=inspection.external_full_list_derivations,
        external_derivation_semantics=inspection.external_derivation_semantics,
        symbol=inspection.symbol,
        timeframe=inspection.timeframe,
        timeframe_duration_ms=inspection.timeframe_duration_ms,
        consumer_observed_at_ms=inspection.consumer_observed_at_ms,
        expected_latest_finalized_close_time=(inspection.expected_latest_finalized_close_time),
        raw_row_count=inspection.raw_row_count,
        gap_count=inspection.gap_count,
        gap_indices=inspection.gap_indices,
        gap_missing_interval_counts=inspection.gap_missing_interval_counts,
        missing_interval_count=inspection.missing_interval_count,
        tail_missing_interval_count=inspection.tail_missing_interval_count,
        latest_candle_matches_expected_cutoff=(inspection.latest_candle_matches_expected_cutoff),
        contiguous_suffix_start_index=inspection.contiguous_suffix_start_index,
        contiguous_suffix_count=inspection.contiguous_suffix_count,
        selected_source_start_index=selected_start,
        selected_source_end_index_exclusive=selected_end,
        selected_rows=selected,
        selected_row_count=len(selected),
        selected_candle_ids=tuple(row.candle_id for row in selected),
        selected_candle_id_chain_material_json=chain_material_json,
        selected_candle_id_chain_sha256=chain_sha256,
        first_selected_economic_close_time=selected[0].candle_close_time,
        latest_selected_economic_close_time=selected[-1].candle_close_time,
        latest_selected_end_exclusive_finality_time=(selected[-1].candle_close_time + 1),
        max_selected_available_at=max(row.available_at for row in selected),
        selection_material_json=selection_material_json,
        selection_sha256=_sha256_text(selection_material_json),
    )
