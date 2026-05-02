"""Contract test: error taxonomy is the closed set per 04 §4.

Every entry that the API may return as `error.class` must appear in
`ERROR_CLASSES`; nothing else may. The required string set below is copied
verbatim from §4 of the route plan and cross-referenced with §3.2/§3.3 of
12B closure (lineage), §6 of 12C (feature snapshot), and §7 of 12C
(confidence).
"""

from __future__ import annotations

from app.api.errors.taxonomy import (
    ERROR_CLASS_NAMES,
    ERROR_CLASSES,
    ERROR_GROUPS,
)


REQUIRED_NAMES: frozenset[str] = frozenset(
    {
        # schema.*
        "schema.unknown_field",
        "schema.type_mismatch",
        "schema.required_missing",
        # rbac.*
        "rbac.forbidden",
        "rbac.role_unbound",
        # approval.*
        "approval.required",
        "approval.consumed",
        "approval.expired",
        "approval.subject_mismatch",
        # idempotency.*
        "idempotency.replay_mismatch",
        "idempotency.key_required",
        # concurrency.*
        "concurrency.etag_mismatch",
        "concurrency.etag_required",
        # lineage.* — seven classes (12B §3.2/§3.3)
        "lineage.malformed",
        "lineage.missing_required",
        "lineage.cross_symbol",
        "lineage.cross_timeframe",
        "lineage.parent_unknown",
        "lineage.gap_reason_missing",
        "lineage.downstream_set_too_early",
        # feature_snapshot.* — eleven classes (12C §6)
        "feature_snapshot.source_grounding_missing",
        "feature_snapshot.freshness_missing",
        "feature_snapshot.feature_value_orphan",
        "feature_snapshot.completeness_invalid",
        "feature_snapshot.checkpoint_unknown",
        "feature_snapshot.symbol_unknown",
        "feature_snapshot.timeframe_unknown",
        "feature_snapshot.duplicate_id",
        "feature_snapshot.manifest_unknown",
        "feature_snapshot.placeholder_misuse",
        "feature_snapshot.cardinality_invalid",
        # confidence.* — nine classes (12C §7)
        "confidence.block_missing",
        "confidence.contributor_count_low",
        "confidence.placeholder_misuse",
        "confidence.calibration_missing",
        "confidence.calibration_stale",
        "confidence.model_version_mismatch",
        "confidence.checkpoint_mismatch",
        "confidence.score_out_of_range",
        "confidence.contributor_orphan",
        # live.*
        "live.blocked_default",
        "live.readiness_not_active",
        "live.dangerous_setting_unauthorized",
        # audit.*
        "audit.chain_break",
        "audit.append_only_violation",
    }
)


def test_taxonomy_is_closed_set() -> None:
    """`ERROR_CLASS_NAMES` must equal the §4 required set exactly — no drift."""
    extra = ERROR_CLASS_NAMES - REQUIRED_NAMES
    missing = REQUIRED_NAMES - ERROR_CLASS_NAMES
    assert not extra, f"Unexpected error classes present: {sorted(extra)}"
    assert not missing, f"Required error classes missing: {sorted(missing)}"


def test_taxonomy_lineage_classes_seven() -> None:
    lineage_classes = [ec for ec in ERROR_CLASSES if ec.group == "lineage"]
    assert len(lineage_classes) == 7


def test_taxonomy_feature_snapshot_classes_eleven() -> None:
    fs = [ec for ec in ERROR_CLASSES if ec.group == "feature_snapshot"]
    assert len(fs) == 11


def test_taxonomy_confidence_classes_nine() -> None:
    conf = [ec for ec in ERROR_CLASSES if ec.group == "confidence"]
    assert len(conf) == 9


def test_taxonomy_groups_match_declared() -> None:
    actual_groups = {ec.group for ec in ERROR_CLASSES}
    assert actual_groups == set(ERROR_GROUPS)


def test_taxonomy_http_statuses_in_allowed_set() -> None:
    allowed = {400, 403, 404, 409, 412, 422}
    for ec in ERROR_CLASSES:
        assert ec.http_status in allowed, (
            f"{ec.name} has disallowed status {ec.http_status}"
        )
