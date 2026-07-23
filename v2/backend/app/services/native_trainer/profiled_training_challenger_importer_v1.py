"""PIT-safe bridge from authenticated profiled samples to challenger input.

The challenger intentionally consumes the durable feature-snapshot archive,
while the commissioned publisher writes authenticated samples to the durable
feature ledger.  This bridge is the single, deterministic import boundary
between those two stores.  It never reconstructs a feature or a cost from a
later observation: the strict ledger loader authenticates the complete input
at the original decision time, and the canonical 5m archive supplies only the
subsequently available label path.

It has no prediction, paper, live, or exchange authority.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    stable_sha256 as canonical_label_stable_sha256,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    append_snapshot,
    build_archive_record,
    write_checksum_manifest,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_FIXED_OBSERVATION_V1_SCHEMA_VERSION,
    ProfiledTrainingLedgerExclusionV1,
    ProfiledTrainingLedgerSampleV1,
    load_profiled_training_ledger_fixed_observation_v1,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    FUTURE_LABEL_PREFIXES,
)

SCHEMA_VERSION = "profiled_training_challenger_importer_v1"
LABEL_SOURCE = "DURABLE_CANONICAL_5M_LABEL_ARCHIVE"
MTF_BINDING_SCHEMA_VERSION = "profiled_training_challenger_mtf_binding_v1"
LABEL_BINDING_SCHEMA_VERSION = "profiled_training_challenger_label_binding_v1"
IMPORT_SNAPSHOT_PREFIX = "profiled_training_challenger_v1"
MAX_IMPORT_PAGE_SIZE = 32


class ProfiledTrainingChallengerImportError(ValueError):
    """A caller supplied an invalid import boundary."""


@dataclass(frozen=True)
class ProfiledTrainingChallengerImportResult:
    schema_version: str
    training_observed_at: str
    archive_root: str
    label_archive_path: str
    source_observation_schema_version: str | None
    source_scanned_record_count: int
    source_admitted_sample_count: int
    source_exclusion_count: int
    label_paths_verified: int
    imported_rows: int
    duplicate_rows: int
    rejected_rows: int
    rejection_reasons: dict[str, int]
    imported_snapshot_ids: tuple[str, ...]
    paper_only: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool


def _aware_utc(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_INVALID"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_INVALID"
        )
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_INVALID"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_INVALID"
        ) from exc
    if not math.isfinite(parsed):
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_INVALID"
        )
    return parsed


def _stable_snapshot_id(sample: ProfiledTrainingLedgerSampleV1) -> str:
    return (
        f"{IMPORT_SNAPSHOT_PREFIX}:"
        f"{sample.durable_snapshot_id}:"
        f"{sample.record_sha256}"
    )


def _label_binding(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    label_rows: list[dict[str, Any]],
    label_proof: Mapping[str, Any],
) -> dict[str, Any]:
    identities = [
        {
            "candle_id": row.get("candle_id"),
            "candle_close_time": row.get("candle_close_time"),
            "content_sha256": hashlib.sha256(
                str(row.get("raw_payload_hash")).encode("utf-8")
            ).hexdigest(),
            "raw_payload_hash": row.get("raw_payload_hash"),
        }
        for row in label_rows
    ]
    material = {
        "schema_version": LABEL_BINDING_SCHEMA_VERSION,
        "source": LABEL_SOURCE,
        "symbol": sample.symbol,
        "decision_time": sample.decision_time,
        "horizon_seconds": sample.expected_holding_horizon_seconds,
        "label_available_at_ms": label_proof.get("label_available_at_ms"),
        "path_identities": identities,
    }
    return {
        **material,
        "label_binding_sha256": canonical_label_stable_sha256(material),
    }


def _selected_logical_feature_names(
    sample: ProfiledTrainingLedgerSampleV1,
) -> tuple[str, ...]:
    """Return exactly the loader-attested logical projection, never labels."""

    names: list[str] = []
    for name, selected in zip(
        sample.logical_feature_names,
        sample.logical_profile_selection_mask,
        strict=True,
    ):
        if type(selected) is not int or selected not in (0, 1):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_SELECTION_MASK_INVALID"
            )
        if selected == 0:
            continue
        normalized = str(name)
        if normalized.lower().startswith(FUTURE_LABEL_PREFIXES):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_SELECTED_FUTURE_LABEL_REJECTED"
            )
        if normalized in names:
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_SELECTED_FEATURE_DUPLICATE"
            )
        names.append(normalized)
    if not names:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SELECTED_FEATURES_EMPTY"
        )
    return tuple(names)


def _feature_mapping(
    sample: ProfiledTrainingLedgerSampleV1,
) -> tuple[dict[str, float], tuple[str, ...]]:
    selected_names = _selected_logical_feature_names(sample)
    selected_name_set = frozenset(selected_names)
    features = {
        str(name): _finite(value, field="LOGICAL_FEATURE")
        for name, value in zip(
            sample.logical_feature_names,
            sample.logical_feature_values,
            strict=True,
        )
        if str(name) in selected_name_set
    }
    if tuple(features) != selected_names:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SELECTED_FEATURE_PROJECTION_INVALID"
        )
    costs = {
        name: _finite(value, field=f"{name.upper()}")
        for name, value in zip(
            CAUSAL_COST_ORDERED_FEATURE_NAMES,
            sample.auxiliary_label_values,
            strict=True,
        )
    }
    if costs["fee_bps"] < 0.0 or costs["expected_slippage_bps"] < 0.0:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_COST_NEGATIVE"
        )
    features.update(costs)
    # The ledger loader authenticates this as the exact decision-time
    # order-book mid.  The challenger uses it as the counterfactual entry
    # price rather than a later close.
    features["decision_reference_price"] = _finite(
        sample.decision_reference_price,
        field="DECISION_REFERENCE_PRICE",
    )
    return features, selected_names


def _selected_mask_mapping(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    values: tuple[int, ...],
    selected_names: tuple[str, ...],
    field: str,
) -> dict[str, bool]:
    selected_name_set = frozenset(selected_names)
    projected: dict[str, bool] = {}
    for name, value in zip(sample.logical_feature_names, values, strict=True):
        normalized = str(name)
        if normalized not in selected_name_set:
            continue
        if type(value) is not int or value not in (0, 1):
            raise ProfiledTrainingChallengerImportError(
                f"PROFILED_TRAINING_CHALLENGER_{field}_MASK_INVALID"
            )
        projected[normalized] = bool(value)
    if tuple(projected) != selected_names:
        raise ProfiledTrainingChallengerImportError(
            f"PROFILED_TRAINING_CHALLENGER_{field}_MASK_PROJECTION_INVALID"
        )
    return projected


def _reconstructed_record(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    label_rows: list[dict[str, Any]],
    label_proof: Mapping[str, Any],
) -> dict[str, Any]:
    decision = _aware_utc(sample.decision_time, field="DECISION_TIME")
    feature_cutoff = _aware_utc(sample.feature_cutoff, field="FEATURE_CUTOFF")
    feature_available = _aware_utc(sample.feature_available_at, field="FEATURE_AVAILABLE_AT")
    cost_available = _aware_utc(
        sample.cost_evidence_available_at,
        field="COST_AVAILABLE_AT",
    )
    reference_available = _aware_utc(
        sample.decision_reference_price_available_at,
        field="REFERENCE_PRICE_AVAILABLE_AT",
    )
    available_at = max(feature_available, cost_available, reference_available)
    if feature_cutoff > available_at or available_at > decision:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_PIT_CLOCK_ORDER_INVALID"
        )
    label_binding = _label_binding(
        sample=sample,
        label_rows=label_rows,
        label_proof=label_proof,
    )
    mtf_material = {
        "schema_version": MTF_BINDING_SCHEMA_VERSION,
        "source_snapshot_id": sample.feature_snapshot_id,
        "source_durable_snapshot_id": sample.durable_snapshot_id,
        "logical_projection_sha256": sample.logical_projection_sha256,
        "logical_model_vector_sha256": sample.logical_model_vector_sha256,
        "feature_cutoff": sample.feature_cutoff,
        "feature_available_at": sample.feature_available_at,
        "decision_time": sample.decision_time,
    }
    mtf_snapshot_id = "profiled-mtf:" + canonical_label_stable_sha256(mtf_material)
    source_hashes = {
        "profiled_ledger_record_sha256": sample.record_sha256,
        "profiled_ledger_high_water_sha256": sample.ledger_high_water_sha256,
        "parent_record_sha256": sample.parent_record_sha256,
        "parent_lineage_binding_sha256": sample.parent_lineage_binding_sha256,
        "cost_capture_binding_sha256": sample.cost_capture_binding_sha256,
        "cost_capture_artifact_sha256": sample.cost_capture_artifact_sha256,
        "cost_capture_receipt_sha256": sample.cost_capture_receipt_sha256,
        "cost_cas_object_inventory_sha256": sample.cost_cas_object_inventory_sha256,
        "mtf_binding_sha256": canonical_label_stable_sha256(mtf_material),
        "canonical_label_binding_sha256": label_binding["label_binding_sha256"],
    }
    features, selected_names = _feature_mapping(sample)
    return build_archive_record(
        snapshot_id=_stable_snapshot_id(sample),
        symbol=sample.symbol,
        timeframe=sample.timeframe,
        feature_cutoff=_utc_iso(feature_cutoff),
        decision_time=_utc_iso(decision),
        available_at=_utc_iso(available_at),
        mtf_snapshot_id=mtf_snapshot_id,
        features=features,
        missing_mask=_selected_mask_mapping(
            sample=sample,
            values=sample.logical_missing_mask,
            selected_names=selected_names,
            field="MISSING",
        ),
        stale_mask=_selected_mask_mapping(
            sample=sample,
            values=sample.logical_stale_mask,
            selected_names=selected_names,
            field="STALE",
        ),
        source_availability=_selected_mask_mapping(
            sample=sample,
            values=sample.logical_source_availability_mask,
            selected_names=selected_names,
            field="SOURCE_AVAILABILITY",
        ),
        source_hashes=source_hashes,
        # This is the original immutable feature-record generation clock, not
        # this import's processing clock.  Keeping it stable makes reruns
        # idempotent without falsely refreshing historical provenance.
        created_at=sample.generated_at,
        extra={
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "feature_freshness_state": "AUTHENTICATED_PROFILED_PIT_RECONSTRUCTED",
            "decision_time_group_key": sample.decision_time,
            "label_source": LABEL_SOURCE,
            "label_binding": label_binding,
            "profiled_loader_schema_version": (
                PROFILED_TRAINING_FIXED_OBSERVATION_V1_SCHEMA_VERSION
            ),
            "profiled_ledger_sequence": sample.sequence,
            "profiled_source_snapshot_id": sample.durable_snapshot_id,
            "source_provenance_receipt_sha256s": list(
                sample.auxiliary_feature_receipt_sha256s
            ),
        },
    )


def import_profiled_training_ledger_to_challenger_archive_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    challenger_archive_root: Path,
    training_observed_at: str,
    page_size: int = MAX_IMPORT_PAGE_SIZE,
) -> ProfiledTrainingChallengerImportResult:
    """Import fully authenticated samples into the challenger's exact store.

    Every source sample is admitted by the existing fixed-observation loader.
    Every import additionally requires an authenticated canonical-label path.
    A failed row is skipped and counted; no fallback feature, cost, or label is
    synthesized.
    """

    if type(ledger) is not DurableFeatureSnapshotLedger:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LEDGER_EXACT_TYPE_REQUIRED"
        )
    if type(label_archive) is not DurableCanonical5mLabelArchive:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED"
        )
    if not isinstance(trusted_immutable_cost_store_root, Path):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_COST_STORE_PATH_INVALID"
        )
    if not isinstance(challenger_archive_root, Path):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_ARCHIVE_ROOT_INVALID"
        )
    if type(page_size) is not int or not 0 < page_size <= MAX_IMPORT_PAGE_SIZE:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_PAGE_SIZE_INVALID"
        )
    observed = _aware_utc(training_observed_at, field="OBSERVATION_TIME")
    observed_text = _utc_iso(observed)
    archive_root = challenger_archive_root.resolve()
    integrity = label_archive.verify_integrity()
    if integrity.get("archive_integrity_verified") is not True:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
        )

    imported_ids: list[str] = []
    rejection_reasons: Counter[str] = Counter()
    imported_rows = 0
    duplicate_rows = 0
    label_paths_verified = 0
    source_observation: dict[str, Any] | None = None

    def observe_high_water(value: Mapping[str, Any]) -> None:
        nonlocal source_observation
        source_observation = dict(value)

    def consume_page(
        samples: tuple[ProfiledTrainingLedgerSampleV1, ...],
        exclusions: tuple[ProfiledTrainingLedgerExclusionV1, ...],
    ) -> None:
        nonlocal imported_rows, duplicate_rows, label_paths_verified
        for exclusion in exclusions:
            rejection_reasons[str(exclusion.reason)] += 1
        for sample in samples:
            try:
                label_rows, label_proof = label_archive.verified_label_path(
                    symbol=sample.symbol,
                    decision_time=sample.decision_time,
                    training_observed_at=observed_text,
                    horizon_seconds=sample.expected_holding_horizon_seconds,
                    archive_integrity_proof=integrity,
                    require_receipt_committed_by_observation=True,
                )
                if (
                    label_rows is None
                    or label_proof.get("status")
                    != "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
                ):
                    for reason in label_proof.get("rejection_reasons") or [
                        "CANONICAL_LABEL_PATH_UNVERIFIED"
                    ]:
                        rejection_reasons[str(reason)] += 1
                    continue
                record = _reconstructed_record(
                    sample=sample,
                    label_rows=label_rows,
                    label_proof=label_proof,
                )
                result = append_snapshot(
                    record,
                    root=archive_root,
                    update_checksum_manifest=False,
                )
            except (OSError, ValueError, ProfiledTrainingChallengerImportError) as exc:
                rejection_reasons[str(exc) or type(exc).__name__] += 1
                continue
            label_paths_verified += 1
            imported_ids.append(result.snapshot_id)
            if result.already_present:
                duplicate_rows += 1
            else:
                imported_rows += 1

    source_result = load_profiled_training_ledger_fixed_observation_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
        training_observed_at=observed_text,
        page_size=page_size,
        observation_consumer=observe_high_water,
        page_consumer=consume_page,
    )
    if imported_rows:
        write_checksum_manifest(archive_root)
    return ProfiledTrainingChallengerImportResult(
        schema_version=SCHEMA_VERSION,
        training_observed_at=observed_text,
        archive_root=str(archive_root),
        label_archive_path=str(label_archive.path.resolve()),
        source_observation_schema_version=(
            source_observation.get("schema_version") if source_observation else None
        ),
        source_scanned_record_count=source_result.scanned_record_count,
        source_admitted_sample_count=source_result.admitted_sample_count,
        source_exclusion_count=source_result.exclusion_count,
        label_paths_verified=label_paths_verified,
        imported_rows=imported_rows,
        duplicate_rows=duplicate_rows,
        rejected_rows=sum(rejection_reasons.values()),
        rejection_reasons=dict(sorted(rejection_reasons.items())),
        imported_snapshot_ids=tuple(sorted(imported_ids)),
        paper_only=True,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
    )
