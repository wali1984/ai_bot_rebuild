"""V2-native ingestor / publisher contracts (paper / read-only).

Pure data classes and pure functions. No network IO, no Redis client
construction, no credentials. Real Redis publishing is a separate layer
that consumes these contracts; tests exercise the contracts directly.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# Freshness state vocabulary — keep names stable across all V2 lanes so
# the report center can render a single legend.
FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_MISSING_SOURCE = "MISSING_SOURCE"
FRESHNESS_BRIDGE_ONLY = "BRIDGE_ONLY"
FRESHNESS_NO_CLIENT_PRESENT = "NO_CLIENT_PRESENT"
FRESHNESS_OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"

VALID_FRESHNESS_STATES = (
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_MISSING_SOURCE,
    FRESHNESS_BRIDGE_ONLY,
    FRESHNESS_NO_CLIENT_PRESENT,
    FRESHNESS_OPERATOR_DECISION_REQUIRED,
)


# Source labels — what the data actually IS, separate from freshness.
SOURCE_V2_NATIVE = "V2_NATIVE"
SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS = "V2_BRIDGE_FROM_LEGACY_REDIS"
SOURCE_PLACEHOLDER_NOT_READY = "PLACEHOLDER_NOT_READY"
SOURCE_OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"

VALID_SOURCE_LABELS = (
    SOURCE_V2_NATIVE,
    SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
    SOURCE_PLACEHOLDER_NOT_READY,
    SOURCE_OPERATOR_DECISION_REQUIRED,
)


@dataclass(frozen=True)
class FreshnessEnvelope:
    """Wrap any payload with source + freshness + per-symbol heartbeat.

    The publisher writes ``payload`` under the target Redis key only when
    ``source_label`` is V2_NATIVE or V2_BRIDGE_FROM_LEGACY_REDIS *and*
    ``freshness_state`` is FRESH. All other combinations are observable
    states (and must be emitted) but do not lead to a Redis write — the
    publisher records the gap reason instead.
    """

    symbol: str
    source_label: str
    freshness_state: str
    generated_utc: str
    payload: dict[str, Any] = field(default_factory=dict)
    heartbeat_seconds_since_last_write: float | None = None
    gap_reason: str | None = None

    def __post_init__(self) -> None:
        if self.source_label not in VALID_SOURCE_LABELS:
            raise ValueError(
                f"invalid source_label: {self.source_label}"
            )
        if self.freshness_state not in VALID_FRESHNESS_STATES:
            raise ValueError(
                f"invalid freshness_state: {self.freshness_state}"
            )

    def should_publish_to_redis(self) -> bool:
        return (
            self.source_label in (
                SOURCE_V2_NATIVE,
                SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
            )
            and self.freshness_state == FRESHNESS_FRESH
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source_label": self.source_label,
            "freshness_state": self.freshness_state,
            "generated_utc": self.generated_utc,
            "payload": self.payload,
            "heartbeat_seconds_since_last_write": (
                self.heartbeat_seconds_since_last_write
            ),
            "gap_reason": self.gap_reason,
        }


def features_hash(rows: list[dict[str, Any]]) -> str:
    """Stable hash over a list of feature rows for integrity stamping."""
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# Trainer prediction publisher contract — exact field set the trainer
# bridge-exit task H enforces. Predictions that do not satisfy this
# contract are emitted only as gap evidence and never to Redis.
@dataclass(frozen=True)
class TrainerPredictionContract:
    symbol: str
    timeframe: str
    feature_snapshot_id: str
    trainer_source: str  # V2_NATIVE or V2_BRIDGE_FROM_LEGACY_TRAINER
    expected_move_after_cost_bps: float | None
    confidence_calibrated: float | None
    feature_freshness_state: str
    missing_fields: list[str] = field(default_factory=list)
    stale_fields: list[str] = field(default_factory=list)

    REQUIRED_FIELDS = (
        "symbol",
        "timeframe",
        "feature_snapshot_id",
        "trainer_source",
        "expected_move_after_cost_bps",
        "confidence_calibrated",
        "feature_freshness_state",
    )

    def is_publishable(self) -> bool:
        if self.trainer_source not in (
            "V2_NATIVE",
            "V2_BRIDGE_FROM_LEGACY_TRAINER",
        ):
            return False
        if self.feature_freshness_state != FRESHNESS_FRESH:
            return False
        if self.expected_move_after_cost_bps is None:
            return False
        if self.confidence_calibrated is None:
            return False
        if self.missing_fields:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "feature_snapshot_id": self.feature_snapshot_id,
            "trainer_source": self.trainer_source,
            "expected_move_after_cost_bps": self.expected_move_after_cost_bps,
            "confidence_calibrated": self.confidence_calibrated,
            "feature_freshness_state": self.feature_freshness_state,
            "missing_fields": list(self.missing_fields),
            "stale_fields": list(self.stale_fields),
            "is_publishable": self.is_publishable(),
        }
