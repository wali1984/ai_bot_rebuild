"""Stdlib-only, caller-supplied feature-resolution observation contract.

These observations are immutable declarations, not authenticated evidence.
The leaf has no TensorBuilder, ledger, Redis, network, or runtime dependency so
the resolver may import it later without introducing an import cycle.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, cast

FEATURE_RESOLUTION_OBSERVATION_V4_SCHEMA_VERSION = "trainer_feature_resolution_observation_v4"
RESOLUTION_STATUS_RESOLVED = "RESOLVED"
RESOLUTION_STATUS_TYPED_NEGATIVE = "TYPED_NEGATIVE"

NEGATIVE_SOURCE_NOT_APPLICABLE = "SOURCE_NOT_APPLICABLE"
NEGATIVE_VALID_EMPTY_EVENT_WINDOW = "VALID_EMPTY_EVENT_WINDOW"
NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED = "CADENCE_OR_RATE_LIMIT_DEFERRED"
NEGATIVE_INTENTIONALLY_ISOLATED = "INTENTIONALLY_ISOLATED"
NEGATIVE_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
NEGATIVE_SOURCE_STALE = "SOURCE_STALE"
NEGATIVE_DERIVATION_EVIDENCE_UNAVAILABLE = "DERIVATION_EVIDENCE_UNAVAILABLE"

IDENTITY_TRANSFORM_ID = "IDENTITY_FLOAT32_V1"
IDENTITY_TRANSFORM_VERSION = "v1"
UNRESOLVED_TRANSFORM_ID = "NO_VALUE_SELECTED_V1"
UNRESOLVED_TRANSFORM_VERSION = "v1"

_IDENTITY_CONTRACT = {
    "schema_version": "feature_resolution_identity_transform_v1",
    "operation": "finite_numeric_to_ieee754_binary32",
    "configuration": "NONE",
}
_UNRESOLVED_CONTRACT = {
    "schema_version": "feature_resolution_unresolved_transform_v1",
    "operation": "NO_VALUE_SELECTED_NO_TRANSFORM_EXECUTED",
    "configuration": "NONE",
}


def _contract_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


IDENTITY_TRANSFORM_CODE_SHA256 = _contract_sha256(_IDENTITY_CONTRACT)
IDENTITY_TRANSFORM_CONFIG_SHA256 = _contract_sha256(
    {"schema_version": "feature_resolution_transform_config_v1", "configuration": "NONE"}
)
UNRESOLVED_TRANSFORM_CODE_SHA256 = _contract_sha256(_UNRESOLVED_CONTRACT)
UNRESOLVED_TRANSFORM_CONFIG_SHA256 = IDENTITY_TRANSFORM_CONFIG_SHA256

_STATUSES = frozenset({RESOLUTION_STATUS_RESOLVED, RESOLUTION_STATUS_TYPED_NEGATIVE})
_NEGATIVE_REASONS = frozenset(
    {
        NEGATIVE_SOURCE_NOT_APPLICABLE,
        NEGATIVE_VALID_EMPTY_EVENT_WINDOW,
        NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
        NEGATIVE_INTENTIONALLY_ISOLATED,
        NEGATIVE_SOURCE_UNAVAILABLE,
        NEGATIVE_SOURCE_STALE,
        NEGATIVE_DERIVATION_EVIDENCE_UNAVAILABLE,
    }
)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()


class FeatureResolutionObservationV4ValidationError(ValueError):
    """The caller's declared resolution observation is structurally invalid."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise FeatureResolutionObservationV4ValidationError(*reasons) from None


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_clock(value: object) -> datetime | None:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return parsed if parsed >= _EPOCH and canonical == value else None


def canonical_float32_v4(value: object) -> float:
    """Return the exact runtime float32 value or reject lossy underflow."""

    if type(value) not in (int, float) or isinstance(value, bool):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_VALUE_INVALID")
    try:
        parsed = float(cast(int | float, value))
        runtime = float(struct.unpack("!f", struct.pack("!f", parsed))[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_VALUE_INVALID")
    if not math.isfinite(parsed) or not math.isfinite(runtime):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_VALUE_INVALID")
    if parsed != 0.0 and runtime == 0.0:
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_VALUE_UNDERFLOW")
    return 0.0 if runtime == 0.0 else runtime


@dataclass(frozen=True, slots=True)
class FeatureSlotResolutionObservationV4:
    """Factory-only declaration of one resolver branch outcome."""

    abi_index: int
    feature_name: str
    resolution_status: str
    selected_payload: str | None
    selected_key: str | None
    selected_path: tuple[str, ...] | None
    selected_alias: str | None
    resolver_version: str
    resolver_code_sha256: str
    resolver_config_sha256: str
    transform_id: str
    transform_version: str
    transform_code_sha256: str
    transform_config_sha256: str
    resolved_value: float | None
    negative_reason: str | None
    source_root_sha256: str | None
    dependency_root_sha256s: tuple[str, ...]
    negative_evidence_sha256: str | None
    event_time: str | None
    ingested_at: str | None
    available_at: str | None
    generated_at: str | None
    feature_cutoff: str
    decision_time: str
    masa_feature_cutoff: str | None
    execution_time: str | None
    consumer_observed_at: str
    candle_close_time: str | None
    candle_final: bool | None
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_observation(self)


def _validate_clocks(observation: FeatureSlotResolutionObservationV4) -> None:
    values = {
        "event_time": observation.event_time,
        "ingested_at": observation.ingested_at,
        "available_at": observation.available_at,
        "generated_at": observation.generated_at,
        "feature_cutoff": observation.feature_cutoff,
        "decision_time": observation.decision_time,
        "masa_feature_cutoff": observation.masa_feature_cutoff,
        "execution_time": observation.execution_time,
        "consumer_observed_at": observation.consumer_observed_at,
        "candle_close_time": observation.candle_close_time,
    }
    parsed: dict[str, datetime] = {}
    for name, value in values.items():
        if value is None:
            continue
        instant = _parse_clock(value)
        if instant is None:
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{name.upper()}_INVALID")
        parsed[name] = instant
    for name in ("feature_cutoff", "decision_time", "consumer_observed_at"):
        if name not in parsed:
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{name.upper()}_REQUIRED")
    needs_source_clocks = (
        observation.resolution_status == RESOLUTION_STATUS_RESOLVED
        or observation.negative_reason == NEGATIVE_SOURCE_STALE
    )
    if needs_source_clocks:
        for name in ("event_time", "ingested_at", "available_at", "generated_at"):
            if name not in parsed:
                _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{name.upper()}_REQUIRED")
    decision_time = parsed["decision_time"]
    for name in ("event_time", "ingested_at", "generated_at", "available_at"):
        if name in parsed and parsed[name] > decision_time:
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{name.upper()}_AFTER_DECISION_TIME")
    for earlier, later, reason in (
        ("event_time", "ingested_at", "EVENT_TIME_AFTER_INGESTED_AT"),
        # In this schema generated_at is the downstream feature/artifact
        # generation clock. Producer publication time belongs in event_time,
        # so a supplied generation clock cannot precede its source event.
        ("event_time", "generated_at", "EVENT_TIME_AFTER_GENERATED_AT"),
        ("event_time", "available_at", "EVENT_TIME_AFTER_AVAILABLE_AT"),
        ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF"),
        ("ingested_at", "available_at", "INGESTED_AT_AFTER_AVAILABLE_AT"),
        ("generated_at", "available_at", "GENERATED_AT_AFTER_AVAILABLE_AT"),
        ("feature_cutoff", "decision_time", "FEATURE_CUTOFF_AFTER_DECISION_TIME"),
        (
            "masa_feature_cutoff",
            "decision_time",
            "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        ),
        ("decision_time", "execution_time", "DECISION_TIME_AFTER_EXECUTION_TIME"),
        (
            "execution_time",
            "consumer_observed_at",
            "EXECUTION_TIME_AFTER_CONSUMER_OBSERVED_AT",
        ),
        (
            "decision_time",
            "consumer_observed_at",
            "DECISION_TIME_AFTER_CONSUMER_OBSERVED_AT",
        ),
    ):
        if earlier in parsed and later in parsed and parsed[earlier] > parsed[later]:
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{reason}")
    close = parsed.get("candle_close_time")
    if close is None:
        if observation.candle_final is not None:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_CANDLE_FINALITY_PAIR_INVALID")
    else:
        if observation.candle_final is not True:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_UNFINISHED_CANDLE")
        # A resolved or stale closed-candle observation becomes available
        # strictly after its end-exclusive close. This is the only latency
        # relation asserted here; producer-specific latency remains external.
        if needs_source_clocks and close >= parsed["available_at"]:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_CANDLE_CLOSE_NOT_BEFORE_AVAILABLE_AT")
        if close > parsed["feature_cutoff"]:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_CANDLE_CLOSE_AFTER_FEATURE_CUTOFF")
        if close >= parsed["decision_time"]:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_CANDLE_CLOSE_NOT_BEFORE_DECISION_TIME")


def _validate_observation(observation: FeatureSlotResolutionObservationV4) -> None:
    if type(observation.abi_index) is not int or not 0 <= observation.abi_index < 4096:
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_ABI_INDEX_INVALID")
    if not _valid_label(observation.feature_name):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_FEATURE_NAME_INVALID")
    if (
        type(observation.resolution_status) is not str
        or observation.resolution_status not in _STATUSES
    ):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_STATUS_INVALID")
    for value, reason in (
        (observation.resolver_version, "RESOLVER_VERSION_INVALID"),
        (observation.transform_id, "TRANSFORM_ID_INVALID"),
        (observation.transform_version, "TRANSFORM_VERSION_INVALID"),
    ):
        if not _valid_label(value):
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{reason}")
    for value, reason in (
        (observation.resolver_code_sha256, "RESOLVER_CODE_SHA256_INVALID"),
        (observation.resolver_config_sha256, "RESOLVER_CONFIG_SHA256_INVALID"),
        (observation.transform_code_sha256, "TRANSFORM_CODE_SHA256_INVALID"),
        (observation.transform_config_sha256, "TRANSFORM_CONFIG_SHA256_INVALID"),
    ):
        if not _valid_sha256(value):
            _fail(f"FEATURE_RESOLUTION_OBSERVATION_V4_{reason}")
    if (
        type(observation.dependency_root_sha256s) is not tuple
        or len(observation.dependency_root_sha256s) > 64
    ):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_DEPENDENCY_ROOTS_INVALID")
    if any(not _valid_sha256(root) for root in observation.dependency_root_sha256s):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_DEPENDENCY_ROOTS_INVALID")
    if len(observation.dependency_root_sha256s) != len(set(observation.dependency_root_sha256s)):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_DEPENDENCY_ROOTS_NOT_UNIQUE")

    path = observation.selected_path
    if path is not None and (
        type(path) is not tuple
        or not path
        or len(path) > 32
        or any(not _valid_label(part) for part in path)
    ):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_SELECTED_PATH_INVALID")
    selector_values = (
        observation.selected_payload,
        observation.selected_key,
        observation.selected_alias,
    )
    selector_present = any(value is not None for value in selector_values) or path is not None
    selector_complete = (
        all(_valid_label(value) for value in selector_values)
        and path is not None
        and path[0] == observation.selected_payload
        and path[-1] == observation.selected_key
    )
    if selector_present and not selector_complete:
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_SELECTOR_PARTIAL")

    if observation.transform_id == IDENTITY_TRANSFORM_ID and (
        observation.transform_version != IDENTITY_TRANSFORM_VERSION
        or observation.transform_code_sha256 != IDENTITY_TRANSFORM_CODE_SHA256
        or observation.transform_config_sha256 != IDENTITY_TRANSFORM_CONFIG_SHA256
    ):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_IDENTITY_TRANSFORM_BINDING_INVALID")
    if not selector_present and (
        observation.transform_id != UNRESOLVED_TRANSFORM_ID
        or observation.transform_version != UNRESOLVED_TRANSFORM_VERSION
        or observation.transform_code_sha256 != UNRESOLVED_TRANSFORM_CODE_SHA256
        or observation.transform_config_sha256 != UNRESOLVED_TRANSFORM_CONFIG_SHA256
    ):
        _fail("FEATURE_RESOLUTION_OBSERVATION_V4_UNRESOLVED_TRANSFORM_BINDING_INVALID")

    if observation.resolution_status == RESOLUTION_STATUS_RESOLVED:
        if not selector_complete:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_RESOLVED_SELECTOR_REQUIRED")
        canonical_float32_v4(observation.resolved_value)
        if (
            observation.negative_reason is not None
            or observation.negative_evidence_sha256 is not None
        ):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_RESOLVED_NEGATIVE_FORBIDDEN")
        if not _valid_sha256(observation.source_root_sha256):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_SOURCE_ROOT_REQUIRED")
    else:
        if observation.resolved_value is not None:
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_NEGATIVE_VALUE_FORBIDDEN")
        if (
            type(observation.negative_reason) is not str
            or observation.negative_reason not in _NEGATIVE_REASONS
        ):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_NEGATIVE_REASON_INVALID")
        if not _valid_sha256(observation.negative_evidence_sha256):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_NEGATIVE_EVIDENCE_REQUIRED")
        if observation.source_root_sha256 is not None and not _valid_sha256(
            observation.source_root_sha256
        ):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_SOURCE_ROOT_INVALID")
        if observation.negative_reason == NEGATIVE_SOURCE_STALE and not _valid_sha256(
            observation.source_root_sha256
        ):
            _fail("FEATURE_RESOLUTION_OBSERVATION_V4_STALE_SOURCE_ROOT_REQUIRED")
    _validate_clocks(observation)


def build_feature_slot_resolution_observation_v4(
    *,
    abi_index: int,
    feature_name: str,
    resolution_status: str,
    selected_payload: str | None,
    selected_key: str | None,
    selected_path: tuple[str, ...] | None,
    selected_alias: str | None,
    resolver_version: str,
    resolver_code_sha256: str,
    resolver_config_sha256: str,
    transform_id: str,
    transform_version: str,
    transform_code_sha256: str,
    transform_config_sha256: str,
    resolved_value: float | None,
    negative_reason: str | None,
    source_root_sha256: str | None,
    dependency_root_sha256s: tuple[str, ...],
    negative_evidence_sha256: str | None,
    event_time: str | None,
    ingested_at: str | None,
    available_at: str | None,
    generated_at: str | None,
    feature_cutoff: str,
    decision_time: str,
    masa_feature_cutoff: str | None,
    execution_time: str | None,
    consumer_observed_at: str,
    candle_close_time: str | None = None,
    candle_final: bool | None = None,
) -> FeatureSlotResolutionObservationV4:
    """Validate and freeze one explicitly caller-supplied observation."""

    return FeatureSlotResolutionObservationV4(
        abi_index=abi_index,
        feature_name=feature_name,
        resolution_status=resolution_status,
        selected_payload=selected_payload,
        selected_key=selected_key,
        selected_path=selected_path,
        selected_alias=selected_alias,
        resolver_version=resolver_version,
        resolver_code_sha256=resolver_code_sha256,
        resolver_config_sha256=resolver_config_sha256,
        transform_id=transform_id,
        transform_version=transform_version,
        transform_code_sha256=transform_code_sha256,
        transform_config_sha256=transform_config_sha256,
        resolved_value=resolved_value,
        negative_reason=negative_reason,
        source_root_sha256=source_root_sha256,
        dependency_root_sha256s=dependency_root_sha256s,
        negative_evidence_sha256=negative_evidence_sha256,
        event_time=event_time,
        ingested_at=ingested_at,
        available_at=available_at,
        generated_at=generated_at,
        feature_cutoff=feature_cutoff,
        decision_time=decision_time,
        masa_feature_cutoff=masa_feature_cutoff,
        execution_time=execution_time,
        consumer_observed_at=consumer_observed_at,
        candle_close_time=candle_close_time,
        candle_final=candle_final,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "FEATURE_RESOLUTION_OBSERVATION_V4_SCHEMA_VERSION",
    "FeatureResolutionObservationV4ValidationError",
    "FeatureSlotResolutionObservationV4",
    "IDENTITY_TRANSFORM_CODE_SHA256",
    "IDENTITY_TRANSFORM_CONFIG_SHA256",
    "IDENTITY_TRANSFORM_ID",
    "IDENTITY_TRANSFORM_VERSION",
    "NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED",
    "NEGATIVE_DERIVATION_EVIDENCE_UNAVAILABLE",
    "NEGATIVE_INTENTIONALLY_ISOLATED",
    "NEGATIVE_SOURCE_NOT_APPLICABLE",
    "NEGATIVE_SOURCE_STALE",
    "NEGATIVE_SOURCE_UNAVAILABLE",
    "NEGATIVE_VALID_EMPTY_EVENT_WINDOW",
    "RESOLUTION_STATUS_RESOLVED",
    "RESOLUTION_STATUS_TYPED_NEGATIVE",
    "UNRESOLVED_TRANSFORM_CODE_SHA256",
    "UNRESOLVED_TRANSFORM_CONFIG_SHA256",
    "UNRESOLVED_TRANSFORM_ID",
    "UNRESOLVED_TRANSFORM_VERSION",
    "build_feature_slot_resolution_observation_v4",
    "canonical_float32_v4",
]
