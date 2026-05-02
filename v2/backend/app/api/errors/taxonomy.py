"""Closed error taxonomy for AI BOT V2 API.

Per `claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md` §4 and
`claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md`.

Every API failure response carries a stable `error.class` from this module.
The set is closed: handlers must not invent ad-hoc strings. The contract test
`backend/tests/contract/test_taxonomy_enumeration.py` enumerates `ERROR_CLASSES`
and asserts the closed set has not drifted.

This module performs no I/O at import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ErrorClass:
    """A taxonomy entry: stable wire string, fixed HTTP status, group label."""

    name: str
    http_status: int
    group: str


# Schema validation
SCHEMA_UNKNOWN_FIELD: Final = ErrorClass("schema.unknown_field", 400, "schema")
SCHEMA_TYPE_MISMATCH: Final = ErrorClass("schema.type_mismatch", 400, "schema")
SCHEMA_REQUIRED_MISSING: Final = ErrorClass("schema.required_missing", 400, "schema")

# RBAC
RBAC_FORBIDDEN: Final = ErrorClass("rbac.forbidden", 403, "rbac")
RBAC_ROLE_UNBOUND: Final = ErrorClass("rbac.role_unbound", 403, "rbac")

# Approval gate
APPROVAL_REQUIRED: Final = ErrorClass("approval.required", 403, "approval")
APPROVAL_CONSUMED: Final = ErrorClass("approval.consumed", 409, "approval")
APPROVAL_EXPIRED: Final = ErrorClass("approval.expired", 403, "approval")
APPROVAL_SUBJECT_MISMATCH: Final = ErrorClass("approval.subject_mismatch", 403, "approval")

# Idempotency
IDEMPOTENCY_REPLAY_MISMATCH: Final = ErrorClass("idempotency.replay_mismatch", 409, "idempotency")
IDEMPOTENCY_KEY_REQUIRED: Final = ErrorClass("idempotency.key_required", 400, "idempotency")

# Concurrency
CONCURRENCY_ETAG_MISMATCH: Final = ErrorClass("concurrency.etag_mismatch", 412, "concurrency")
CONCURRENCY_ETAG_REQUIRED: Final = ErrorClass("concurrency.etag_required", 412, "concurrency")

# Lineage (12B closure §3.2/§3.3) — seven classes
LINEAGE_MALFORMED: Final = ErrorClass("lineage.malformed", 400, "lineage")
LINEAGE_MISSING_REQUIRED: Final = ErrorClass("lineage.missing_required", 422, "lineage")
LINEAGE_CROSS_SYMBOL: Final = ErrorClass("lineage.cross_symbol", 422, "lineage")
LINEAGE_CROSS_TIMEFRAME: Final = ErrorClass("lineage.cross_timeframe", 422, "lineage")
LINEAGE_PARENT_UNKNOWN: Final = ErrorClass("lineage.parent_unknown", 422, "lineage")
LINEAGE_GAP_REASON_MISSING: Final = ErrorClass("lineage.gap_reason_missing", 422, "lineage")
LINEAGE_DOWNSTREAM_SET_TOO_EARLY: Final = ErrorClass(
    "lineage.downstream_set_too_early", 422, "lineage"
)

# Feature snapshot (12C §6, §11.7.3) — eleven classes
FEATURE_SNAPSHOT_SOURCE_GROUNDING_MISSING: Final = ErrorClass(
    "feature_snapshot.source_grounding_missing", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_FRESHNESS_MISSING: Final = ErrorClass(
    "feature_snapshot.freshness_missing", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_FEATURE_VALUE_ORPHAN: Final = ErrorClass(
    "feature_snapshot.feature_value_orphan", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_COMPLETENESS_INVALID: Final = ErrorClass(
    "feature_snapshot.completeness_invalid", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_CHECKPOINT_UNKNOWN: Final = ErrorClass(
    "feature_snapshot.checkpoint_unknown", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_SYMBOL_UNKNOWN: Final = ErrorClass(
    "feature_snapshot.symbol_unknown", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_TIMEFRAME_UNKNOWN: Final = ErrorClass(
    "feature_snapshot.timeframe_unknown", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_DUPLICATE_ID: Final = ErrorClass(
    "feature_snapshot.duplicate_id", 409, "feature_snapshot"
)
FEATURE_SNAPSHOT_MANIFEST_UNKNOWN: Final = ErrorClass(
    "feature_snapshot.manifest_unknown", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_PLACEHOLDER_MISUSE: Final = ErrorClass(
    "feature_snapshot.placeholder_misuse", 422, "feature_snapshot"
)
FEATURE_SNAPSHOT_CARDINALITY_INVALID: Final = ErrorClass(
    "feature_snapshot.cardinality_invalid", 422, "feature_snapshot"
)

# Confidence (12C §7, §11.7.4-7.5) — nine classes
CONFIDENCE_BLOCK_MISSING: Final = ErrorClass("confidence.block_missing", 422, "confidence")
CONFIDENCE_CONTRIBUTOR_COUNT_LOW: Final = ErrorClass(
    "confidence.contributor_count_low", 422, "confidence"
)
CONFIDENCE_PLACEHOLDER_MISUSE: Final = ErrorClass(
    "confidence.placeholder_misuse", 422, "confidence"
)
CONFIDENCE_CALIBRATION_MISSING: Final = ErrorClass(
    "confidence.calibration_missing", 422, "confidence"
)
CONFIDENCE_CALIBRATION_STALE: Final = ErrorClass(
    "confidence.calibration_stale", 422, "confidence"
)
CONFIDENCE_MODEL_VERSION_MISMATCH: Final = ErrorClass(
    "confidence.model_version_mismatch", 422, "confidence"
)
CONFIDENCE_CHECKPOINT_MISMATCH: Final = ErrorClass(
    "confidence.checkpoint_mismatch", 422, "confidence"
)
CONFIDENCE_SCORE_OUT_OF_RANGE: Final = ErrorClass(
    "confidence.score_out_of_range", 422, "confidence"
)
CONFIDENCE_CONTRIBUTOR_ORPHAN: Final = ErrorClass(
    "confidence.contributor_orphan", 422, "confidence"
)

# Live mode
LIVE_BLOCKED_DEFAULT: Final = ErrorClass("live.blocked_default", 403, "live")
LIVE_READINESS_NOT_ACTIVE: Final = ErrorClass("live.readiness_not_active", 403, "live")
LIVE_DANGEROUS_SETTING_UNAUTHORIZED: Final = ErrorClass(
    "live.dangerous_setting_unauthorized", 403, "live"
)

# Audit
AUDIT_CHAIN_BREAK: Final = ErrorClass("audit.chain_break", 409, "audit")
AUDIT_APPEND_ONLY_VIOLATION: Final = ErrorClass("audit.append_only_violation", 409, "audit")


ERROR_CLASSES: Final[tuple[ErrorClass, ...]] = (
    SCHEMA_UNKNOWN_FIELD,
    SCHEMA_TYPE_MISMATCH,
    SCHEMA_REQUIRED_MISSING,
    RBAC_FORBIDDEN,
    RBAC_ROLE_UNBOUND,
    APPROVAL_REQUIRED,
    APPROVAL_CONSUMED,
    APPROVAL_EXPIRED,
    APPROVAL_SUBJECT_MISMATCH,
    IDEMPOTENCY_REPLAY_MISMATCH,
    IDEMPOTENCY_KEY_REQUIRED,
    CONCURRENCY_ETAG_MISMATCH,
    CONCURRENCY_ETAG_REQUIRED,
    LINEAGE_MALFORMED,
    LINEAGE_MISSING_REQUIRED,
    LINEAGE_CROSS_SYMBOL,
    LINEAGE_CROSS_TIMEFRAME,
    LINEAGE_PARENT_UNKNOWN,
    LINEAGE_GAP_REASON_MISSING,
    LINEAGE_DOWNSTREAM_SET_TOO_EARLY,
    FEATURE_SNAPSHOT_SOURCE_GROUNDING_MISSING,
    FEATURE_SNAPSHOT_FRESHNESS_MISSING,
    FEATURE_SNAPSHOT_FEATURE_VALUE_ORPHAN,
    FEATURE_SNAPSHOT_COMPLETENESS_INVALID,
    FEATURE_SNAPSHOT_CHECKPOINT_UNKNOWN,
    FEATURE_SNAPSHOT_SYMBOL_UNKNOWN,
    FEATURE_SNAPSHOT_TIMEFRAME_UNKNOWN,
    FEATURE_SNAPSHOT_DUPLICATE_ID,
    FEATURE_SNAPSHOT_MANIFEST_UNKNOWN,
    FEATURE_SNAPSHOT_PLACEHOLDER_MISUSE,
    FEATURE_SNAPSHOT_CARDINALITY_INVALID,
    CONFIDENCE_BLOCK_MISSING,
    CONFIDENCE_CONTRIBUTOR_COUNT_LOW,
    CONFIDENCE_PLACEHOLDER_MISUSE,
    CONFIDENCE_CALIBRATION_MISSING,
    CONFIDENCE_CALIBRATION_STALE,
    CONFIDENCE_MODEL_VERSION_MISMATCH,
    CONFIDENCE_CHECKPOINT_MISMATCH,
    CONFIDENCE_SCORE_OUT_OF_RANGE,
    CONFIDENCE_CONTRIBUTOR_ORPHAN,
    LIVE_BLOCKED_DEFAULT,
    LIVE_READINESS_NOT_ACTIVE,
    LIVE_DANGEROUS_SETTING_UNAUTHORIZED,
    AUDIT_CHAIN_BREAK,
    AUDIT_APPEND_ONLY_VIOLATION,
)


ERROR_CLASS_NAMES: Final[frozenset[str]] = frozenset(ec.name for ec in ERROR_CLASSES)


ERROR_GROUPS: Final[tuple[str, ...]] = (
    "schema",
    "rbac",
    "approval",
    "idempotency",
    "concurrency",
    "lineage",
    "feature_snapshot",
    "confidence",
    "live",
    "audit",
)


def lookup(name: str) -> ErrorClass:
    """Return the `ErrorClass` for a wire name. Raises `KeyError` if unknown."""
    for ec in ERROR_CLASSES:
        if ec.name == name:
            return ec
    raise KeyError(name)
