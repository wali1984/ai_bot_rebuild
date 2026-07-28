"""Identity-scoped FINAL PASS data-utilization report.

The historical v2 report forced unlike identities into one decreasing list:
market events, feature snapshots, candidate decisions, and checkpoint rows.
That can look arithmetically green while comparing unrelated cohorts.  V3 keeps
the required counters, but reconciles only paths whose rows share an identity
domain and publishes checkpoint usage as a separate manifest-bound ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from v2.backend.app.services.adaptive_system.data_utilization_funnel_v2 import (
    REDIS_KEY,
    build_path_funnel,
)

SCHEMA_VERSION = "data_utilization_report_v3"
HISTORICAL_PATH_STAGES = (
    "feature_snapshots",
    "finality_proven_snapshots",
    "cost_complete_snapshots",
    "microstructure_complete_snapshots",
    "labeled_snapshots",
    "training_eligible_rows",
)
CANDIDATE_PATH_STAGES = (
    "candidate_outcome_rows",
    "matured_candidate_outcome_rows",
)
RAW_PATH_STAGES = ("raw_events", "canonical_events")


class DataUtilizationReportError(ValueError):
    """Raised when source evidence is malformed or identity-incoherent."""


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DataUtilizationReportError("REPORT_NOT_STRICT_JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _required_int(source: Mapping[str, Any], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DataUtilizationReportError(f"{field}:NONNEGATIVE_INT_REQUIRED")
    return value


def _required_text(source: Mapping[str, Any], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DataUtilizationReportError(f"{field}:NONEMPTY_TEXT_REQUIRED")
    return value


def _required_sha256(source: Mapping[str, Any], field: str) -> str:
    value = _required_text(source, field)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DataUtilizationReportError(f"{field}:SHA256_REQUIRED")
    return value


def _authority_is_safe(source: Mapping[str, Any]) -> bool:
    return bool(
        source.get("paper_only") is True
        and source.get("live_gate") == "blocked_human_only"
        and source.get("routes_to_live") is False
        and source.get("places_real_order") is False
        and source.get("exchange_action_taken") is False
    )


def _checkpoint_usage(
    rows: Sequence[Mapping[str, Any]],
    *,
    active_checkpoint_id: str,
    active_registry_generation: int,
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for raw in rows:
        checkpoint_id = _required_text(raw, "checkpoint_id")
        training_rows = _required_int(raw, "training_rows")
        validation_rows = _required_int(raw, "validation_rows")
        holdout_rows = _required_int(raw, "holdout_rows")
        manifest_id = _required_text(raw, "training_manifest_id")
        manifest_sha256 = _required_sha256(raw, "training_manifest_sha256")
        content_sha256 = _required_sha256(raw, "content_sha256")
        entry = {
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_sha256": content_sha256,
            "training_manifest_id": manifest_id,
            "training_manifest_sha256": manifest_sha256,
            "training_rows": training_rows,
            "validation_rows": validation_rows,
            "holdout_rows": holdout_rows,
            "rows_used_total": training_rows + validation_rows + holdout_rows,
            "active": checkpoint_id == active_checkpoint_id,
            "registry_generation": (
                active_registry_generation if checkpoint_id == active_checkpoint_id else None
            ),
            "source_paths": sorted(
                {
                    str(value)
                    for value in raw.get("source_paths", [])
                    if isinstance(value, str) and value
                }
            ),
        }
        prior = seen.get(checkpoint_id)
        if prior is not None:
            comparable = dict(entry)
            comparable.pop("source_paths")
            prior_comparable = dict(prior)
            prior_comparable.pop("source_paths")
            if comparable != prior_comparable:
                raise DataUtilizationReportError(
                    f"CHECKPOINT_IDENTITY_CONFLICT:{checkpoint_id}"
                )
            prior["source_paths"] = sorted(
                set(prior["source_paths"]) | set(entry["source_paths"])
            )
            continue
        seen[checkpoint_id] = entry
    if active_checkpoint_id not in seen:
        raise DataUtilizationReportError("ACTIVE_CHECKPOINT_USAGE_MISSING")
    return [seen[key] for key in sorted(seen)]


def build_data_utilization_report_v3(
    *,
    generated_at: str,
    frozen_corpus: Mapping[str, Any],
    candidate_outcomes: Mapping[str, Any],
    checkpoint_rows: Sequence[Mapping[str, Any]],
    active_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a fail-closed report from already authenticated source profiles."""

    snapshot_id = _required_text(frozen_corpus, "snapshot_id")
    snapshot_manifest_sha256 = _required_sha256(
        frozen_corpus, "snapshot_manifest_sha256"
    )
    dataset_id = _required_text(frozen_corpus, "dataset_id")
    dataset_sha256 = _required_sha256(frozen_corpus, "dataset_sha256")
    dataset_manifest_id = _required_text(frozen_corpus, "dataset_manifest_id")
    dataset_manifest_sha256 = _required_sha256(
        frozen_corpus, "dataset_manifest_sha256"
    )

    raw_counts = {stage: _required_int(frozen_corpus, stage) for stage in RAW_PATH_STAGES}
    historical_counts = {
        stage: _required_int(frozen_corpus, stage) for stage in HISTORICAL_PATH_STAGES
    }
    candidate_counts = {
        stage: _required_int(candidate_outcomes, stage) for stage in CANDIDATE_PATH_STAGES
    }
    overlap_count = _required_int(candidate_outcomes, "gen5_exact_identity_overlap_rows")

    source_exclusions = frozen_corpus.get("historical_exclusions_by_stage")
    if not isinstance(source_exclusions, Mapping):
        raise DataUtilizationReportError("HISTORICAL_EXCLUSIONS_OBJECT_REQUIRED")
    pending_reasons = candidate_outcomes.get("pending_reasons")
    if not isinstance(pending_reasons, Mapping):
        raise DataUtilizationReportError("CANDIDATE_PENDING_REASONS_OBJECT_REQUIRED")

    raw_path = build_path_funnel(RAW_PATH_STAGES, raw_counts)
    historical_path = build_path_funnel(
        HISTORICAL_PATH_STAGES,
        historical_counts,
        source_exclusions,
    )
    candidate_path = build_path_funnel(
        CANDIDATE_PATH_STAGES,
        candidate_counts,
        {"candidate_outcome_rows": pending_reasons},
    )

    active_checkpoint_id = _required_text(active_registry, "checkpoint_id")
    active_generation = _required_int(active_registry, "registry_generation")
    checkpoint_usage = _checkpoint_usage(
        checkpoint_rows,
        active_checkpoint_id=active_checkpoint_id,
        active_registry_generation=active_generation,
    )

    safety_sources = (frozen_corpus, candidate_outcomes, active_registry)
    source_authority_safe = all(_authority_is_safe(source) for source in safety_sources)
    paths_consistent = bool(
        raw_path.consistent and historical_path.consistent and candidate_path.consistent
    )
    source_integrity_verified = bool(
        frozen_corpus.get("source_integrity_verified") is True
        and candidate_outcomes.get("archive_verified") is True
        and active_registry.get("registry_binding_verified") is True
    )
    complete_paid_source_inventory_bound = bool(
        frozen_corpus.get("complete_paid_source_inventory_bound") is True
    )
    exact_candidate_join_complete = bool(
        overlap_count > 0
        and overlap_count == historical_counts["training_eligible_rows"]
    )
    blockers: list[str] = []
    if not paths_consistent:
        blockers.append("IDENTITY_SCOPED_FUNNEL_INCONSISTENT")
    if not source_integrity_verified:
        blockers.append("SOURCE_INTEGRITY_UNVERIFIED")
    if not source_authority_safe:
        blockers.append("PAPER_LIVE_AUTHORITY_BOUNDARY_INVALID")
    if not complete_paid_source_inventory_bound:
        blockers.append("FULL_PAID_SOURCE_INVENTORY_NOT_BOUND_TO_FROZEN_GEN5_SCOPE")
    if not exact_candidate_join_complete:
        blockers.append("TYPED_CANDIDATE_OUTCOMES_NOT_JOINED_TO_GEN5_TRAINING_ROWS")

    counters: dict[str, Any] = {
        **raw_counts,
        **historical_counts,
        "candidate_outcome_rows": candidate_counts["candidate_outcome_rows"],
        "matured_candidate_outcome_rows": candidate_counts[
            "matured_candidate_outcome_rows"
        ],
        "gen5_candidate_outcome_identity_overlap_rows": overlap_count,
        "rows_used_by_each_checkpoint": {
            row["checkpoint_id"]: row["rows_used_total"] for row in checkpoint_usage
        },
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _required_text({"generated_at": generated_at}, "generated_at"),
        "redis_key": REDIS_KEY,
        "scope": {
            "frozen_snapshot_id": snapshot_id,
            "snapshot_manifest_sha256": snapshot_manifest_sha256,
            "dataset_id": dataset_id,
            "dataset_sha256": dataset_sha256,
            "dataset_manifest_id": dataset_manifest_id,
            "dataset_manifest_sha256": dataset_manifest_sha256,
            "active_checkpoint_id": active_checkpoint_id,
            "active_registry_generation": active_generation,
            "raw_event_counter_definition": (
                "UNIQUE_RAW_PAYLOAD_HASHES_IN_FROZEN_CANONICAL_5M_LABEL_ARCHIVE"
            ),
            "complete_paid_source_inventory_bound": complete_paid_source_inventory_bound,
        },
        "required_counters": counters,
        "identity_scoped_paths": {
            "raw_to_canonical_one_to_one": {
                "identity_domain": "canonical_5m_sequence_with_unique_raw_payload_hash",
                **raw_path.to_dict(),
            },
            "gen5_historical_label_training": {
                "identity_domain": "frozen_feature_ledger_sequence",
                **historical_path.to_dict(),
            },
            "candidate_outcome_maturation": {
                "identity_domain": "candidate_id",
                **candidate_path.to_dict(),
            },
        },
        "checkpoint_usage": checkpoint_usage,
        "candidate_outcome_training_join": {
            "join_identity": "symbol+timeframe+decision_time_ms",
            "exact_overlap_rows": overlap_count,
            "gen5_training_eligible_rows": historical_counts["training_eligible_rows"],
            "complete": exact_candidate_join_complete,
            "counterfactual_counts_as_realized_paper_profit": False,
        },
        "paths_consistent": paths_consistent,
        "source_integrity_verified": source_integrity_verified,
        "complete_eligible_data_utilized": exact_candidate_join_complete,
        "blockers": blockers,
        "status": "PASS" if not blockers else "BLOCK",
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


__all__ = [
    "CANDIDATE_PATH_STAGES",
    "DataUtilizationReportError",
    "HISTORICAL_PATH_STAGES",
    "RAW_PATH_STAGES",
    "SCHEMA_VERSION",
    "build_data_utilization_report_v3",
]
