"""Shared feature adapter for V2 challenger replay and runtime inference.

The adapter is intentionally side-effect free. It is used by historical
trusted replay, blind lockbox construction, current shadow inference, and any
paper-only challenger path so model input construction cannot drift silently.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from v2.backend.app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
)


SCHEMA_VERSION = "challenger_v2_shared_feature_adapter_v1"
FUTURE_LABEL_PREFIXES = (
    "future_return",
    "future_",
    "label_",
    "target_",
    "realized_",
)
PIT_SAFE_REALIZED_FEATURES = {"realized_slippage_error"}


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _feature_name_allowed(name: str) -> bool:
    lowered = str(name).lower()
    if lowered in PIT_SAFE_REALIZED_FEATURES:
        return True
    return not lowered.startswith(FUTURE_LABEL_PREFIXES)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def extract_feature_mapping(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    features = _as_mapping(snapshot.get("features"))
    if not features:
        feature_snapshot = _as_mapping(snapshot.get("feature_snapshot"))
        features = _as_mapping(feature_snapshot.get("features"))
    return {str(name): value for name, value in features.items()}


def numeric_feature_mapping(snapshot: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in extract_feature_mapping(snapshot).items():
        if not _feature_name_allowed(name):
            continue
        parsed = finite_float(value)
        if parsed is not None:
            out[name] = parsed
    return out


def _mask_names(
    snapshot: Mapping[str, Any],
    *,
    mask_key: str,
    names_keys: Sequence[str],
) -> list[str]:
    features = extract_feature_mapping(snapshot)
    names: set[str] = set()
    raw_mask = snapshot.get(mask_key)
    if isinstance(raw_mask, Mapping):
        names.update(str(name) for name, flag in raw_mask.items() if bool(flag))
    elif isinstance(raw_mask, Iterable) and not isinstance(raw_mask, (str, bytes, Mapping)):
        names.update(str(name) for name in raw_mask)
    for key in names_keys:
        raw_names = snapshot.get(key)
        if isinstance(raw_names, Iterable) and not isinstance(raw_names, (str, bytes, Mapping)):
            names.update(str(name) for name in raw_names)
    return sorted(name for name in names if name in features or name)


def _first_present(snapshot: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = snapshot.get(name)
        if value not in (None, ""):
            return value
    return None


@dataclass(frozen=True)
class NormalizationSpec:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    stds: tuple[float, ...]
    mins: tuple[float, ...]
    maxs: tuple[float, ...]
    schema_version: str = SCHEMA_VERSION

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "feature_names": list(self.feature_names),
            "means": list(self.means),
            "stds": list(self.stds),
            "mins": list(self.mins),
            "maxs": list(self.maxs),
        }


@dataclass(frozen=True)
class AdaptedFeatureVector:
    symbol: str
    timeframe: str
    snapshot_id: str
    source_context: str
    feature_schema_version: str
    feature_names_in_order: tuple[str, ...]
    raw_vector: tuple[float, ...]
    normalized_vector: tuple[float, ...]
    feature_vector_hash: str
    missing_feature_names: tuple[str, ...]
    stale_feature_names: tuple[str, ...]
    out_of_range_features: tuple[str, ...]
    normalization_status: str
    integrity_status: dict[str, Any]
    rejection_reasons: tuple[str, ...]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "snapshot_id": self.snapshot_id,
            "source_context": self.source_context,
            "integrity_status": self.integrity_status,
            "feature_schema_version": self.feature_schema_version,
            "feature_vector_hash": self.feature_vector_hash,
            "missing_feature_names": list(self.missing_feature_names),
            "stale_feature_names": list(self.stale_feature_names),
            "out_of_range_features": list(self.out_of_range_features),
            "normalization_status": self.normalization_status,
            "rejection_reasons": list(self.rejection_reasons),
        }


def build_normalization_spec(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
) -> NormalizationSpec:
    if not feature_names:
        raise ValueError("feature_names_required")
    vectors: list[list[float]] = []
    for row in rows:
        features = numeric_feature_mapping(row)
        vectors.append([float(features.get(name, 0.0)) for name in feature_names])
    if not vectors:
        raise ValueError("normalization_rows_required")
    means: list[float] = []
    stds: list[float] = []
    mins: list[float] = []
    maxs: list[float] = []
    for col in zip(*vectors):
        values = [float(value) for value in col]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        std = math.sqrt(variance)
        means.append(mean)
        stds.append(std if std > 1e-9 else 1.0)
        mins.append(min(values))
        maxs.append(max(values))
    return NormalizationSpec(
        feature_names=tuple(str(name) for name in feature_names),
        means=tuple(means),
        stds=tuple(stds),
        mins=tuple(mins),
        maxs=tuple(maxs),
    )


def feature_schema_hash(feature_names: Sequence[str]) -> str:
    return stable_hash({"schema_version": SCHEMA_VERSION, "feature_names": list(feature_names)})


def normalization_hash(spec: NormalizationSpec) -> str:
    return stable_hash(spec.to_jsonable())


def _trust_row(snapshot: Mapping[str, Any], missing_names: Sequence[str], stale_names: Sequence[str]) -> dict[str, Any]:
    features = extract_feature_mapping(snapshot)
    decision_time = _first_present(
        snapshot,
        "decision_time",
        "decision_time_est",
        "decision_cutoff_time_est",
        "generated_at",
        "generated_utc",
    )
    feature_cutoff = _first_present(
        snapshot,
        "feature_cutoff",
        "source_event_time_est",
        "candle_close_time",
    )
    available_at = _first_present(
        snapshot,
        "available_at",
        "source_available_time",
        "source_received_time_est",
        "generated_at",
        "generated_utc",
    )
    snapshot_id = str(snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id") or "")
    return {
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "timeframe": str(snapshot.get("timeframe") or ""),
        "feature_snapshot_id": snapshot_id,
        "prediction_id": snapshot.get("prediction_id"),
        "feature_vector_hash": stable_hash(features),
        "generated_at": decision_time,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "decision_time_est": decision_time,
        "decision_cutoff_time_est": decision_time,
        "source_event_time_est": feature_cutoff,
        "source_received_time_est": available_at,
        "source_available_time": available_at,
        "candle_open_time": snapshot.get("candle_open_time"),
        "candle_close_time": snapshot.get("candle_close_time") or feature_cutoff,
        "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        "feature_freshness_state": snapshot.get("feature_freshness_state") or "CURRENT",
        "trainer_consumable": snapshot.get("trainer_consumable") is not False,
        "row_classification": "TRAINABLE",
        "missing_feature_count": len(missing_names),
        "missing_feature_names": list(missing_names),
        "stale_feature_count": len(stale_names),
        "stale_feature_names": list(stale_names),
        "features": dict(features),
    }


def adapt_feature_snapshot(
    snapshot: Mapping[str, Any],
    *,
    feature_names: Sequence[str] | None = None,
    normalization: NormalizationSpec | None = None,
    source_context: str,
) -> AdaptedFeatureVector:
    features = extract_feature_mapping(snapshot)
    numeric = numeric_feature_mapping(snapshot)
    names = tuple(
        str(name)
        for name in (
            normalization.feature_names
            if normalization is not None
            else feature_names
            if feature_names is not None
            else sorted(numeric)
        )
    )
    raw_missing = set(
        _mask_names(
            snapshot,
            mask_key="missing_mask",
            names_keys=("missing_feature_names", "missing_feature_flags"),
        )
    )
    stale_names = set(
        _mask_names(
            snapshot,
            mask_key="stale_mask",
            names_keys=("stale_feature_names", "stale_feature_flags"),
        )
    )
    raw_missing = {name for name in raw_missing if name in set(names)}
    stale_names = {name for name in stale_names if name in set(names)}
    required_missing = {name for name in names if name not in numeric}
    missing_names = tuple(sorted(raw_missing | required_missing))

    rejection_reasons: set[str] = set()
    if not features:
        rejection_reasons.add("FEATURES_EMPTY")
    if any(not _feature_name_allowed(name) for name in features):
        rejection_reasons.add("FUTURE_LABEL_PRESENT_IN_FEATURES")
    if required_missing:
        rejection_reasons.add("MISSING_MODEL_FEATURE")
    if stale_names:
        rejection_reasons.add("STALE_MODEL_FEATURE")

    decision_time = parse_utc(
        _first_present(snapshot, "decision_time", "decision_time_est", "decision_cutoff_time_est", "generated_at", "generated_utc")
    )
    feature_cutoff = parse_utc(_first_present(snapshot, "feature_cutoff", "source_event_time_est", "candle_close_time"))
    available_at = parse_utc(_first_present(snapshot, "available_at", "source_available_time", "source_received_time_est", "generated_at", "generated_utc"))
    if decision_time is None:
        rejection_reasons.add("DECISION_TIME_MISSING")
    if feature_cutoff is None:
        rejection_reasons.add("FEATURE_CUTOFF_MISSING")
    if available_at is None:
        rejection_reasons.add("AVAILABLE_AT_MISSING")
    if decision_time is not None and feature_cutoff is not None and feature_cutoff > decision_time:
        rejection_reasons.add("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if decision_time is not None and available_at is not None and available_at > decision_time:
        rejection_reasons.add("AVAILABLE_AT_AFTER_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        rejection_reasons.add("OPEN_CANDLE_REJECTED")

    raw_vector = tuple(float(numeric.get(name, 0.0)) for name in names)
    out_of_range: list[str] = []
    if normalization is None:
        normalized_vector = raw_vector
        normalization_status = "NO_NORMALIZATION_SPEC"
    else:
        normalized: list[float] = []
        for name, value, mean, std, low, high in zip(
            names,
            raw_vector,
            normalization.means,
            normalization.stds,
            normalization.mins,
            normalization.maxs,
        ):
            normalized.append((value - mean) / (std if abs(std) > 1e-12 else 1.0))
            if value < low - 1e-9 or value > high + 1e-9:
                out_of_range.append(name)
        normalized_vector = tuple(float(value) for value in normalized)
        normalization_status = "PASS" if not out_of_range and not required_missing else "FAILED"
    if out_of_range:
        rejection_reasons.add("NORMALIZATION_OUT_OF_TRAINING_RANGE")

    trust_row = _trust_row(snapshot, missing_names, sorted(stale_names))
    integrity = classify_training_sample(trust_row)
    rejection_reasons.update(str(reason) for reason in integrity.get("reject_reasons") or [])
    if integrity.get("accepted_for_training") is not True:
        rejection_reasons.add("INTEGRITY_FAILED")

    snapshot_id = str(snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id") or "")
    vector_hash = stable_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "feature_names": list(names),
            "raw_vector": list(raw_vector),
            "normalized_vector": list(normalized_vector),
            "missing_feature_names": list(missing_names),
            "stale_feature_names": sorted(stale_names),
        }
    )
    return AdaptedFeatureVector(
        symbol=str(snapshot.get("symbol") or "").upper(),
        timeframe=str(snapshot.get("timeframe") or ""),
        snapshot_id=snapshot_id,
        source_context=source_context,
        feature_schema_version=SCHEMA_VERSION,
        feature_names_in_order=names,
        raw_vector=raw_vector,
        normalized_vector=normalized_vector,
        feature_vector_hash=vector_hash,
        missing_feature_names=missing_names,
        stale_feature_names=tuple(sorted(stale_names)),
        out_of_range_features=tuple(sorted(out_of_range)),
        normalization_status=normalization_status,
        integrity_status=integrity,
        rejection_reasons=tuple(sorted(rejection_reasons)),
    )


def adapt_replay_snapshot(
    snapshot: Mapping[str, Any],
    *,
    feature_names: Sequence[str] | None = None,
    normalization: NormalizationSpec | None = None,
) -> AdaptedFeatureVector:
    return adapt_feature_snapshot(
        snapshot,
        feature_names=feature_names,
        normalization=normalization,
        source_context="historical_trusted_replay",
    )


def adapt_runtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    feature_names: Sequence[str] | None = None,
    normalization: NormalizationSpec | None = None,
) -> AdaptedFeatureVector:
    return adapt_feature_snapshot(
        snapshot,
        feature_names=feature_names,
        normalization=normalization,
        source_context="runtime_current_or_paper",
    )
