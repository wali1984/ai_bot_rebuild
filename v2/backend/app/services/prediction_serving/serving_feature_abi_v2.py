"""ServingFeatureABIV2: one point-in-time feature contract for train and serve.

The builder in this module is deliberately small and pure.  Dataset construction
and canonical prediction serving both call :func:`build_serving_feature_vector`;
neither is allowed to maintain its own feature order, transform, or imputation.
All ABI features are required in V2, so the missing mask is explicit and always
zero for an admitted vector.  A missing, stale, non-finite, future-available, or
non-final feature rejects the row rather than being zero-filled.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "ServingFeatureABIV2"
POINT_IN_TIME_SEMANTICS = (
    "feature_cutoff<=record_available_at<=decision_time;"
    "latest_unclosed_kline_excluded=true;latest_closed_kline_close_time_ms<="
    "latest_unclosed_exclusion_decision_time_ms<=decision_time_ms"
)
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


@dataclass(frozen=True)
class FeatureDeclaration:
    name: str
    position: int
    dtype: str
    unit: str
    producer: str
    source_key_or_record: str
    required: bool
    optional_reason: str | None
    missing_value_policy: str
    staleness_limit: str
    normalization: dict[str, Any]
    point_in_time_cutoff_semantics: str = POINT_IN_TIME_SEMANTICS


@dataclass(frozen=True)
class ServingFeatureVectorV2:
    values: tuple[float, ...]
    missing_mask: tuple[int, ...]
    ordered_feature_names: tuple[str, ...]
    feature_abi_sha256: str
    feature_builder_sha256: str
    feature_cutoff: str
    record_available_at: str
    decision_time: str
    source_record_sha256: str
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    latest_closed_kline_close_time_ms: int


def _decl(
    name: str,
    position: int,
    *,
    unit: str,
    transform: str,
    producer: str = "v2_feature_pipeline_native_loop",
    source: str | None = None,
) -> FeatureDeclaration:
    return FeatureDeclaration(
        name=name,
        position=position,
        dtype="float32",
        unit=unit,
        producer=producer,
        source_key_or_record=source
        or f"v2:features:latest:{{symbol}}:{{timeframe}}.features.{name}",
        required=True,
        optional_reason=None,
        missing_value_policy="REJECT_ROW_NO_IMPUTATION",
        staleness_limit=(
            "SOURCE_EXPIRES_AT_AND_DECISION_TIME_BOUND"
            if producer == "adaptive_cost_model_v1"
            else "LATEST_CLOSED_CANDLE_WITHIN_TWO_TIMEFRAME_INTERVALS"
        ),
        normalization={"transform": transform, "checkpoint_standardization": "TRAIN_FIT_ONLY"},
    )


_RAW_FEATURE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("expected_funding_bps", "basis_points", "DIVIDE_10", "cost"),
    ("expected_slippage_bps", "basis_points_per_side", "DIVIDE_10", "cost"),
    ("fee_bps", "basis_points_per_side", "DIVIDE_10", "cost"),
    ("spread_bps", "basis_points_full_spread", "DIVIDE_10", "cost"),
    ("bb_width_pct", "fraction", "MULTIPLY_100", "feature"),
    ("body_pct", "fraction", "MULTIPLY_100", "feature"),
    ("close", "quote_currency_per_base", "LOG1P_NONNEGATIVE", "feature"),
    ("ema_12", "quote_currency_per_base", "RATIO_TO_CLOSE_MINUS_ONE", "feature"),
    ("ema_26", "quote_currency_per_base", "RATIO_TO_CLOSE_MINUS_ONE", "feature"),
    ("high", "quote_currency_per_base", "RATIO_TO_CLOSE_MINUS_ONE", "feature"),
    ("log_return", "log_fraction", "MULTIPLY_100", "feature"),
    ("low", "quote_currency_per_base", "RATIO_TO_CLOSE_MINUS_ONE", "feature"),
    ("macd", "quote_currency_per_base_delta", "DIVIDE_BY_CLOSE", "feature"),
    ("macd_hist", "quote_currency_per_base_delta", "DIVIDE_BY_CLOSE", "feature"),
    ("macd_signal", "quote_currency_per_base_delta", "DIVIDE_BY_CLOSE", "feature"),
    ("num_trades", "count", "LOG1P_NONNEGATIVE", "feature"),
    ("open", "quote_currency_per_base", "RATIO_TO_CLOSE_MINUS_ONE", "feature"),
    ("quote_volume", "quote_currency", "LOG1P_NONNEGATIVE", "feature"),
    ("range_pct", "fraction", "MULTIPLY_100", "feature"),
    ("ret_pct", "fraction", "MULTIPLY_100", "feature"),
    ("rsi_14", "rsi_points_0_100", "CENTER_50_DIVIDE_50", "feature"),
    ("taker_buy_base_vol", "base_currency", "LOG1P_NONNEGATIVE", "feature"),
    ("taker_buy_quote_vol", "quote_currency", "LOG1P_NONNEGATIVE", "feature"),
    ("taker_buy_ratio", "fraction_0_1", "IDENTITY", "feature"),
    ("taker_sell_base_vol", "base_currency", "LOG1P_NONNEGATIVE", "feature"),
    ("taker_sell_quote_vol", "quote_currency", "LOG1P_NONNEGATIVE", "feature"),
    ("taker_sell_ratio", "fraction_0_1", "IDENTITY", "feature"),
    ("true_range_pct", "fraction", "MULTIPLY_100", "feature"),
    ("volume", "base_currency", "LOG1P_NONNEGATIVE", "feature"),
)

FEATURE_DECLARATIONS: tuple[FeatureDeclaration, ...] = tuple(
    _decl(
        name,
        position,
        unit=unit,
        transform=transform,
        producer="adaptive_cost_model_v1"
        if source_kind == "cost"
        else "v2_feature_pipeline_native_loop",
        source=(f"v2:costs:round_trip_bps:{{symbol}}.{name}" if source_kind == "cost" else None),
    )
    for position, (name, unit, transform, source_kind) in enumerate(_RAW_FEATURE_SPECS)
)
ORDERED_FEATURE_NAMES = tuple(item.name for item in FEATURE_DECLARATIONS)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def serving_feature_abi_v2() -> dict[str, Any]:
    material = {
        "schema_version": SCHEMA_VERSION,
        "feature_count": len(FEATURE_DECLARATIONS),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "features": [asdict(item) for item in FEATURE_DECLARATIONS],
        "required_feature_policy": "ALL_REQUIRED_REJECT_NO_ZERO_FILL",
        "optional_missing_mask_policy": (
            "EXPLICIT_MASK_REQUIRED_IF_A_FUTURE_ABI_ADDS_OPTIONAL_FEATURES"
        ),
        "point_in_time_cutoff_semantics": POINT_IN_TIME_SEMANTICS,
        "finality_contract": {
            "latest_unclosed_kline_excluded": True,
            "required_fields": [
                "latest_unclosed_kline_excluded",
                "latest_unclosed_exclusion_method",
                "latest_unclosed_exclusion_decision_time_ms",
                "latest_closed_kline_close_time_ms",
            ],
        },
    }
    material["feature_builder_sha256"] = feature_builder_sha256()
    return material


def feature_abi_sha256() -> str:
    return hashlib.sha256(_canonical_bytes(serving_feature_abi_v2())).hexdigest()


def feature_builder_sha256() -> str:
    source = inspect.getsource(build_serving_feature_vector)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_MISSING")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}_NOT_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"REQUIRED_FEATURE_INVALID:{name}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"REQUIRED_FEATURE_MISSING:{name}") from exc
    if not math.isfinite(result):
        raise ValueError(f"REQUIRED_FEATURE_NONFINITE:{name}")
    return result


def _transform(name: str, value: float, transform: str, close: float) -> float:
    if transform == "IDENTITY":
        result = value
    elif transform == "DIVIDE_10":
        result = value / 10.0
    elif transform == "MULTIPLY_100":
        result = value * 100.0
    elif transform == "LOG1P_NONNEGATIVE":
        if value < 0.0:
            raise ValueError(f"FEATURE_DOMAIN_INVALID:{name}")
        result = math.log1p(value)
    elif transform == "RATIO_TO_CLOSE_MINUS_ONE":
        if close <= 0.0:
            raise ValueError("FEATURE_DOMAIN_INVALID:close")
        result = value / close - 1.0
    elif transform == "DIVIDE_BY_CLOSE":
        if close <= 0.0:
            raise ValueError("FEATURE_DOMAIN_INVALID:close")
        result = value / close
    elif transform == "CENTER_50_DIVIDE_50":
        result = (value - 50.0) / 50.0
    else:  # pragma: no cover - declarations are module constants
        raise ValueError(f"FEATURE_TRANSFORM_UNKNOWN:{name}")
    if not math.isfinite(result):
        raise ValueError(f"FEATURE_TRANSFORM_NONFINITE:{name}")
    return result


def build_serving_feature_vector(
    *,
    feature_record: Mapping[str, Any],
    decision_time: str,
    exact_cost_record: Mapping[str, Any] | None = None,
) -> ServingFeatureVectorV2:
    """Build one V2 vector or reject it with a stable reason.

    Historical authenticated records already contain cost values captured at
    their decision time.  Current serving records must provide
    ``exact_cost_record``; its explicit fields replace the mutable snapshot's
    cost aliases.  The feature transforms and order are otherwise identical.
    """
    features_raw = feature_record.get("features")
    if not isinstance(features_raw, Mapping):
        raise ValueError("FEATURES_MAPPING_MISSING")
    features = dict(features_raw)
    if exact_cost_record is not None:
        aliases = {
            "expected_funding_bps": "funding_bps_at_decision_time",
            "expected_slippage_bps": "slippage_bps_per_side",
            "fee_bps": "fee_bps_per_side",
            "spread_bps": "spread_bps",
        }
        for feature_name, source_name in aliases.items():
            if exact_cost_record.get(source_name) is None:
                raise ValueError(f"EXACT_COST_FIELD_MISSING:{source_name}")
            features[feature_name] = exact_cost_record[source_name]

    cutoff_text = str(feature_record.get("feature_cutoff") or "")
    available_text = str(
        feature_record.get("record_available_at")
        or feature_record.get("available_at")
        or feature_record.get("generated_at")
        or ""
    )
    cutoff = _parse_utc(cutoff_text, "feature_cutoff")
    available = _parse_utc(available_text, "record_available_at")
    decision = _parse_utc(decision_time, "decision_time")
    if not (cutoff <= available <= decision):
        raise ValueError("POINT_IN_TIME_CLOCK_ORDER_INVALID")
    timeframe = str(feature_record.get("timeframe") or "")
    interval_seconds = _TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        raise ValueError("FEATURE_TIMEFRAME_UNSUPPORTED")
    if (decision - cutoff).total_seconds() > interval_seconds * 2:
        raise ValueError("FEATURE_STALENESS_LIMIT_EXCEEDED")
    if exact_cost_record is not None:
        cost_source = _parse_utc(
            exact_cost_record.get("source_event_time"), "cost_source_event_time"
        )
        cost_generated = _parse_utc(
            exact_cost_record.get("producer_generated_at"), "cost_producer_generated_at"
        )
        cost_available = _parse_utc(
            exact_cost_record.get("record_available_at"), "cost_record_available_at"
        )
        cost_expires = _parse_utc(exact_cost_record.get("expires_at"), "cost_expires_at")
        if not (cost_source <= cost_generated <= cost_available <= decision <= cost_expires):
            raise ValueError("EXACT_COST_CLOCK_ORDER_INVALID")
        if exact_cost_record.get("source_readback_verified") is not True:
            raise ValueError("EXACT_COST_READBACK_UNVERIFIED")

    if feature_record.get("latest_unclosed_kline_excluded") is not True:
        raise ValueError("LATEST_UNCLOSED_KLINE_NOT_EXCLUDED")
    method = str(feature_record.get("latest_unclosed_exclusion_method") or "").strip()
    if not method:
        raise ValueError("LATEST_UNCLOSED_EXCLUSION_METHOD_MISSING")
    try:
        exclusion_ms = int(feature_record["latest_unclosed_exclusion_decision_time_ms"])
        closed_ms = int(feature_record["latest_closed_kline_close_time_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("FINALITY_CLOCKS_MISSING") from exc
    decision_ms = int(decision.timestamp() * 1000)
    if closed_ms > exclusion_ms or exclusion_ms > decision_ms:
        raise ValueError("FINALITY_CLOCK_ORDER_INVALID")

    close = _finite(features.get("close"), "close")
    values: list[float] = []
    for declaration in FEATURE_DECLARATIONS:
        raw = _finite(features.get(declaration.name), declaration.name)
        values.append(
            _transform(
                declaration.name,
                raw,
                str(declaration.normalization["transform"]),
                close,
            )
        )
    source_sha = hashlib.sha256(_canonical_bytes(dict(feature_record))).hexdigest()
    return ServingFeatureVectorV2(
        values=tuple(values),
        missing_mask=tuple(0 for _ in values),
        ordered_feature_names=ORDERED_FEATURE_NAMES,
        feature_abi_sha256=feature_abi_sha256(),
        feature_builder_sha256=feature_builder_sha256(),
        feature_cutoff=cutoff_text,
        record_available_at=available_text,
        decision_time=decision_time,
        source_record_sha256=source_sha,
        latest_unclosed_kline_excluded=True,
        latest_unclosed_exclusion_method=method,
        latest_unclosed_exclusion_decision_time_ms=exclusion_ms,
        latest_closed_kline_close_time_ms=closed_ms,
    )


def canonical_abi_json() -> str:
    return json.dumps(serving_feature_abi_v2(), indent=2, sort_keys=True) + "\n"


__all__ = [
    "FEATURE_DECLARATIONS",
    "ORDERED_FEATURE_NAMES",
    "SCHEMA_VERSION",
    "ServingFeatureVectorV2",
    "build_serving_feature_vector",
    "canonical_abi_json",
    "feature_abi_sha256",
    "feature_builder_sha256",
    "serving_feature_abi_v2",
]
