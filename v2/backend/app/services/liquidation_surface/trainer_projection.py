"""Decision-bound projection of admitted liquidation surfaces into trainer slots.

The prospective liquidation model publishes a rich surface, while the native
trainer consumes scalar feature slots.  This module is the only semantic
projection between those contracts.  It accepts a factory-authenticated
``LiquidationSurfaceTrainerAdmission`` and either:

* exposes directly supported scalar values for the exact admitted decision; or
* emits the same ordered slots as explicit masked absence.

It never reads Redis, chooses a market threshold, substitutes a default value,
or grants prediction/trading authority.  In particular, the surface does not
currently contain either a calibrated cascade probability or a comparable
total side-mass pressure statistic.  ``liquidation_cascade_risk`` and
``liquidation_pressure_direction`` therefore remain masked instead of being
fabricated from differently-normalized per-side clusters.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, NoReturn

from .trainer_admission import LiquidationSurfaceTrainerAdmission

PROJECTION_SCHEMA_VERSION = "v2_liquidation_surface_trainer_projection_v1"
PROJECTION_SOURCE_LABEL = "v2:liquidation_surface:latest_trainer_eligible"
PROJECTION_FEATURE_NAMES: tuple[str, ...] = (
    "liquidation_long_level",
    "liquidation_short_level",
    "nearest_liquidation_level_above",
    "nearest_liquidation_level_below",
    "distance_to_long_liq_bps",
    "distance_to_short_liq_bps",
    "liquidation_cluster_strength_long",
    "liquidation_cluster_strength_short",
    "liquidation_distance_pct",
    "liquidation_strength",
    "liquidation_cascade_risk",
    "liquidation_pressure_direction",
)
PROJECTION_SOURCE_LABELS: tuple[str, ...] = tuple(
    PROJECTION_SOURCE_LABEL for _ in PROJECTION_FEATURE_NAMES
)
PROJECTION_REQUIREMENT_CLASSES: tuple[str, ...] = tuple(
    "ADAPTIVE_OPTIONAL" for _ in PROJECTION_FEATURE_NAMES
)
_INTENTIONALLY_MASKED_FEATURES = frozenset(
    {"liquidation_cascade_risk", "liquidation_pressure_direction"}
)
_TOKEN = object()
_PROJECTION_MATERIAL_FIELDS: tuple[str, ...] = (
    "schema_version",
    "projection_abi_sha256",
    "decision_id",
    "decision_time_ms",
    "symbol",
    "timeframe",
    "consumer_feature_abi_sha256",
    "surface_id",
    "surface_archive_payload_sha256",
    "surface_publication_receipt_sha256",
    "source_manifest_sha256",
    "publication_scope_sha256",
    "admission_receipt_sha256",
    "admission_receipt_hmac_sha256",
    "feature_cutoff_ms",
    "publication_available_at_ms",
    "projection_available_at_ms",
    "ordered_feature_names",
    "ordered_source_labels",
    "ordered_requirement_classes",
    "ordered_feature_values",
    "missing_mask",
    "stale_mask",
    "source_availability",
    "trainer_authority",
    "trainer_authority_reason",
    "rejection_reasons",
    "prediction_authority",
    "paper_trading_authority",
    "live_execution_authority",
)


class LiquidationSurfaceTrainerProjectionError(RuntimeError):
    """The admitted surface cannot be represented by the projection contract."""


def _fail(reason: str) -> NoReturn:
    raise LiquidationSurfaceTrainerProjectionError(reason) from None


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(nested)
            for key, nested in value.items()
        }
    if isinstance(value, tuple | list):
        return [_plain_json(nested) for nested in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _plain_json(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("LIQUIDATION_TRAINER_PROJECTION_CANONICAL_JSON_INVALID")


def _stable_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


PROJECTION_ABI_SHA256 = _stable_sha256(
    {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "ordered_feature_names": PROJECTION_FEATURE_NAMES,
        "ordered_source_labels": PROJECTION_SOURCE_LABELS,
        "ordered_requirement_classes": PROJECTION_REQUIREMENT_CLASSES,
    }
)


def _finite(value: object, *, name: str, positive: bool = False) -> float:
    if isinstance(value, bool):
        _fail(f"{name}_NOT_FINITE_NUMBER")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{name}_NOT_FINITE_NUMBER")
    if not math.isfinite(number) or (positive and number <= 0.0):
        _fail(f"{name}_NOT_FINITE_NUMBER")
    return number


def _level(value: object, *, side: str, current_price: float) -> tuple[float, float, float]:
    if not isinstance(value, Mapping):
        _fail(f"NEAREST_{side.upper()}_LEVEL_MISSING")
    price = _finite(value.get("price"), name=f"NEAREST_{side.upper()}_PRICE", positive=True)
    distance_bps = _finite(
        value.get("distance_bps"),
        name=f"NEAREST_{side.upper()}_DISTANCE_BPS",
    )
    strength = _finite(
        value.get("normalized_strength"),
        name=f"NEAREST_{side.upper()}_NORMALIZED_STRENGTH",
    )
    if distance_bps < 0.0:
        _fail(f"NEAREST_{side.upper()}_DISTANCE_BPS_NEGATIVE")
    if not 0.0 < strength <= 1.0:
        _fail(f"NEAREST_{side.upper()}_NORMALIZED_STRENGTH_OUT_OF_RANGE")
    if side == "long" and price >= current_price:
        _fail("NEAREST_LONG_LEVEL_NOT_BELOW_CURRENT_PRICE")
    if side == "short" and price <= current_price:
        _fail("NEAREST_SHORT_LEVEL_NOT_ABOVE_CURRENT_PRICE")
    recomputed_distance_bps = abs(price - current_price) / current_price * 10_000.0
    if not math.isclose(
        distance_bps,
        recomputed_distance_bps,
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        _fail(f"NEAREST_{side.upper()}_DISTANCE_BPS_INCONSISTENT")
    return price, distance_bps, strength


def _projection_material_values(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in _PROJECTION_MATERIAL_FIELDS}


def _projection_material(value: LiquidationSurfaceTrainerProjection) -> dict[str, Any]:
    return _projection_material_values(
        {key: getattr(value, key) for key in _PROJECTION_MATERIAL_FIELDS}
    )


@dataclass(frozen=True, slots=True)
class LiquidationSurfaceTrainerProjection:
    """Immutable scalar projection valid for exactly one trainer decision."""

    schema_version: str
    projection_abi_sha256: str
    decision_id: str
    decision_time_ms: int
    symbol: str
    timeframe: str
    consumer_feature_abi_sha256: str
    surface_id: str
    surface_archive_payload_sha256: str
    surface_publication_receipt_sha256: str
    source_manifest_sha256: str
    publication_scope_sha256: str
    admission_receipt_sha256: str
    admission_receipt_hmac_sha256: str
    feature_cutoff_ms: int
    publication_available_at_ms: int
    projection_available_at_ms: int
    ordered_feature_names: tuple[str, ...]
    ordered_source_labels: tuple[str, ...]
    ordered_requirement_classes: tuple[str, ...]
    ordered_feature_values: tuple[float | None, ...]
    missing_mask: tuple[bool, ...]
    stale_mask: tuple[bool, ...]
    source_availability: tuple[bool, ...]
    trainer_authority: bool
    trainer_authority_reason: str
    rejection_reasons: tuple[str, ...]
    prediction_authority: bool
    paper_trading_authority: bool
    live_execution_authority: bool
    projection_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        lengths = {
            len(self.ordered_feature_names),
            len(self.ordered_source_labels),
            len(self.ordered_requirement_classes),
            len(self.ordered_feature_values),
            len(self.missing_mask),
            len(self.stale_mask),
            len(self.source_availability),
        }
        value_mask_valid = all(
            (
                value is None
                and missing is True
                and available is False
            )
            or (
                value is not None
                and not isinstance(value, bool)
                and math.isfinite(value)
                and missing is False
                and available is True
            )
            for value, missing, available in zip(
                self.ordered_feature_values,
                self.missing_mask,
                self.source_availability,
                strict=True,
            )
        )
        intentional_mask = tuple(
            name in _INTENTIONALLY_MASKED_FEATURES
            for name in PROJECTION_FEATURE_NAMES
        )
        authority_shape_valid = (
            self.trainer_authority is True
            and not self.rejection_reasons
            and self.missing_mask == intentional_mask
        ) or (
            self.trainer_authority is False
            and bool(self.rejection_reasons)
            and all(self.missing_mask)
            and not any(self.source_availability)
        )
        if (
            self._construction_token is not _TOKEN
            or self.schema_version != PROJECTION_SCHEMA_VERSION
            or self.projection_abi_sha256 != PROJECTION_ABI_SHA256
            or self.ordered_feature_names != PROJECTION_FEATURE_NAMES
            or self.ordered_source_labels != PROJECTION_SOURCE_LABELS
            or self.ordered_requirement_classes != PROJECTION_REQUIREMENT_CLASSES
            or lengths != {len(PROJECTION_FEATURE_NAMES)}
            or self.prediction_authority is not False
            or self.paper_trading_authority is not False
            or self.live_execution_authority is not False
            or min(
                self.feature_cutoff_ms,
                self.publication_available_at_ms,
                self.projection_available_at_ms,
                self.decision_time_ms,
            )
            <= 0
            or (
                self.trainer_authority
                and not (
                    self.feature_cutoff_ms
                    <= self.publication_available_at_ms
                    <= self.projection_available_at_ms
                    <= self.decision_time_ms
                )
            )
            or not value_mask_valid
            or not authority_shape_valid
            or self.projection_sha256 != _stable_sha256(_projection_material(self))
        ):
            _fail("LIQUIDATION_TRAINER_PROJECTION_FACTORY_OR_INTEGRITY_INVALID")

    def is_authorized_for(
        self,
        *,
        decision_id: str,
        decision_time_ms: int,
        symbol: str,
        timeframe: str,
        feature_abi_sha256: str,
    ) -> bool:
        return bool(
            self.trainer_authority
            and self.projection_sha256 == _stable_sha256(_projection_material(self))
            and decision_id == self.decision_id
            and type(decision_time_ms) is int
            and decision_time_ms == self.decision_time_ms
            and symbol == self.symbol
            and timeframe == self.timeframe
            and feature_abi_sha256 == self.consumer_feature_abi_sha256
        )

    def feature_mapping(self) -> Mapping[str, float | None]:
        """Return a read-only exact-name mapping; masks remain on this object."""

        return MappingProxyType(
            dict(zip(self.ordered_feature_names, self.ordered_feature_values, strict=True))
        )


def _masked_projection_values(
    admission: LiquidationSurfaceTrainerAdmission,
) -> tuple[tuple[float | None, ...], tuple[bool, ...], tuple[bool, ...], tuple[bool, ...]]:
    count = len(PROJECTION_FEATURE_NAMES)
    stale = any(
        "FRESHNESS_EXPIRED" in reason
        or "EVIDENCE_EXPIRED" in reason
        or "SOURCE_DEGRADED" in reason
        for reason in admission.rejection_reasons
    )
    return (
        tuple(None for _ in range(count)),
        tuple(True for _ in range(count)),
        tuple(stale for _ in range(count)),
        tuple(False for _ in range(count)),
    )


def build_liquidation_surface_trainer_projection(
    admission: LiquidationSurfaceTrainerAdmission,
    *,
    decision_id: str,
    decision_time_ms: int,
    symbol: str,
    timeframe: str,
    feature_abi_sha256: str,
) -> LiquidationSurfaceTrainerProjection:
    """Project one admission without upgrading its decision-scoped authority."""

    if type(admission) is not LiquidationSurfaceTrainerAdmission:
        _fail("LIQUIDATION_TRAINER_ADMISSION_FACTORY_RESULT_REQUIRED")
    identity = {
        "decision_id": decision_id,
        "decision_time_ms": decision_time_ms,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_abi_sha256": feature_abi_sha256,
    }
    authorized = admission.is_authorized_for(**identity)
    if not authorized:
        mismatched_identity = (
            decision_id != admission.decision_id
            or type(decision_time_ms) is not int
            or decision_time_ms != admission.decision_time_ms
            or symbol != admission.symbol
            or timeframe != admission.timeframe
            or feature_abi_sha256 != admission.feature_abi_sha256
        )
        if mismatched_identity:
            _fail("LIQUIDATION_TRAINER_PROJECTION_DECISION_IDENTITY_MISMATCH")
        values, missing, stale, available = _masked_projection_values(admission)
        trainer_authority = False
        authority_reason = admission.trainer_authority_reason
        rejection_reasons = admission.rejection_reasons or (
            "LIQUIDATION_SURFACE_ADMISSION_NOT_AUTHORIZED",
        )
    else:
        payload = admission.surface_payload
        if not isinstance(payload, Mapping):
            _fail("AUTHORIZED_LIQUIDATION_SURFACE_PAYLOAD_MISSING")
        current_price = _finite(
            payload.get("current_price"),
            name="LIQUIDATION_SURFACE_CURRENT_PRICE",
            positive=True,
        )
        long_price, long_distance_bps, long_strength = _level(
            payload.get("nearest_long_level"),
            side="long",
            current_price=current_price,
        )
        short_price, short_distance_bps, short_strength = _level(
            payload.get("nearest_short_level"),
            side="short",
            current_price=current_price,
        )
        projected: list[float | None] = [
            long_price,
            short_price,
            short_price,
            long_price,
            long_distance_bps,
            short_distance_bps,
            long_strength,
            short_strength,
            min(long_distance_bps, short_distance_bps) / 100.0,
            max(long_strength, short_strength),
            None,
            None,
        ]
        values = tuple(projected)
        missing = tuple(value is None for value in values)
        stale = tuple(False for _ in values)
        available = tuple(value is not None for value in values)
        if missing != tuple(
            name in _INTENTIONALLY_MASKED_FEATURES
            for name in PROJECTION_FEATURE_NAMES
        ):
            _fail("LIQUIDATION_TRAINER_PROJECTION_UNEXPECTED_MISSING_SLOT")
        trainer_authority = True
        authority_reason = "DECISION_SCOPED_LIQUIDATION_SCALAR_PROJECTION_VERIFIED"
        rejection_reasons = ()

    result_values: dict[str, Any] = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "projection_abi_sha256": PROJECTION_ABI_SHA256,
        "decision_id": admission.decision_id,
        "decision_time_ms": admission.decision_time_ms,
        "symbol": admission.symbol,
        "timeframe": admission.timeframe,
        "consumer_feature_abi_sha256": admission.feature_abi_sha256,
        "surface_id": admission.surface_id,
        "surface_archive_payload_sha256": admission.surface_archive_payload_sha256,
        "surface_publication_receipt_sha256": (
            admission.surface_publication_receipt_sha256
        ),
        "source_manifest_sha256": admission.source_manifest_sha256,
        "publication_scope_sha256": admission.publication_scope_sha256,
        "admission_receipt_sha256": admission.admission_receipt_sha256,
        "admission_receipt_hmac_sha256": admission.admission_receipt_hmac_sha256,
        "feature_cutoff_ms": admission.feature_cutoff_ms,
        "publication_available_at_ms": admission.publication_available_at_ms,
        "projection_available_at_ms": admission.admission_checked_at_ms,
        "ordered_feature_names": PROJECTION_FEATURE_NAMES,
        "ordered_source_labels": PROJECTION_SOURCE_LABELS,
        "ordered_requirement_classes": PROJECTION_REQUIREMENT_CLASSES,
        "ordered_feature_values": values,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability": available,
        "trainer_authority": trainer_authority,
        "trainer_authority_reason": authority_reason,
        "rejection_reasons": tuple(rejection_reasons),
        "prediction_authority": False,
        "paper_trading_authority": False,
        "live_execution_authority": False,
    }
    return LiquidationSurfaceTrainerProjection(
        **result_values,
        projection_sha256=_stable_sha256(_projection_material_values(result_values)),
        _construction_token=_TOKEN,
    )


__all__ = [
    "PROJECTION_ABI_SHA256",
    "PROJECTION_FEATURE_NAMES",
    "PROJECTION_REQUIREMENT_CLASSES",
    "PROJECTION_SCHEMA_VERSION",
    "PROJECTION_SOURCE_LABEL",
    "PROJECTION_SOURCE_LABELS",
    "LiquidationSurfaceTrainerProjection",
    "LiquidationSurfaceTrainerProjectionError",
    "build_liquidation_surface_trainer_projection",
]
