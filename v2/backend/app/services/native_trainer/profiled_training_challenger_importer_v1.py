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

import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
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
    ArchiveWriteResult,
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record,
    load_snapshot,
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
    load_profiled_training_ledger_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    ProfiledTrainingObservationManifestV1Error,
    authenticate_profiled_training_observation_manifest_v1,
    build_finalized_label_binding_v1,
    derive_label_archive_fixed_observation_proof_v1,
    label_archive_high_water_for_integrity_v1,
    read_profiled_training_observation_page_v1,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TrainerSourceProvenanceLedgerEntryV4,
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
SHARD_CHECKPOINT_SCHEMA_VERSION = "profiled_training_challenger_import_checkpoint_v1"
DEFAULT_SHARD_CHECKPOINT_FILENAME = "profiled_training_challenger_import_checkpoint_v1.json"
LABEL_INTEGRITY_CHECKPOINT_SCHEMA_VERSION = (
    "profiled_training_challenger_label_integrity_checkpoint_v1"
)
DEFAULT_LABEL_INTEGRITY_CHECKPOINT_FILENAME = (
    "profiled_training_challenger_label_integrity_checkpoint_v1.json"
)
DEFAULT_MINIMUM_TRAIN_ROWS = 1_000
DEFAULT_MINIMUM_VALIDATION_ROWS = 100
DEFAULT_MINIMUM_HOLDOUT_ROWS = 100
MANIFEST_SHARD_CHECKPOINT_SCHEMA_VERSION = (
    "profiled_training_manifest_shard_import_checkpoint_v1"
)
DEFAULT_MANIFEST_SHARD_CHECKPOINT_FILENAME = (
    "profiled_training_manifest_shard_import_checkpoint_v1.json"
)


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


def _label_independent_feature_identity(record: Mapping[str, Any]) -> str:
    """Bind the immutable feature/cost record while excluding label observations.

    The challenger archive is keyed by the immutable profiled feature record.
    Canonical labels are re-verified when a dataset is frozen, so a later
    manifest may legitimately carry a different label-observation receipt for
    the same feature record.  That later receipt must not overwrite the
    archive entry, but neither may it be treated as the same entry unless every
    feature and cost provenance field still agrees exactly.
    """

    source_hashes = record.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SOURCE_HASHES_INVALID"
        )
    normalized_hashes = dict(source_hashes)
    normalized_hashes.pop("canonical_label_binding_sha256", None)
    normalized_hashes.pop("profiled_ledger_high_water_sha256", None)
    material = {
        key: value
        for key, value in record.items()
        if key not in {"content_sha256", "label_binding", "source_hashes"}
    }
    material["source_hashes"] = normalized_hashes
    return canonical_label_stable_sha256(material)


def _valid_label_receipt_binding(record: Mapping[str, Any]) -> bool:
    binding = record.get("label_binding")
    source_hashes = record.get("source_hashes")
    if not isinstance(binding, Mapping) or not isinstance(source_hashes, Mapping):
        return False
    binding_sha = binding.get("label_binding_sha256")
    return (
        record.get("label_source") == LABEL_SOURCE
        and isinstance(binding_sha, str)
        and bool(binding_sha)
        and source_hashes.get("canonical_label_binding_sha256") == binding_sha
    )


def _append_or_reuse_label_observation_record(
    *,
    record: Mapping[str, Any],
    challenger_archive_root: Path,
) -> tuple[ArchiveWriteResult | None, bool]:
    """Append a new record or safely reuse an exact feature/cost predecessor.

    ``append_snapshot`` correctly refuses to replace a snapshot ID with a
    different content digest.  A different digest is only reusable here when
    it is caused exclusively by a later authenticated label-observation
    receipt; every label-independent field must remain identical.  The stored
    object remains immutable and the next freeze independently verifies the
    canonical labels at its own observation time.
    """

    try:
        return (
            append_snapshot(
                record,
                root=challenger_archive_root,
                update_checksum_manifest=False,
            ),
            False,
        )
    except SnapshotArchiveError as exc:
        if str(exc) != "SNAPSHOT_ID_CONTENT_HASH_CHANGED":
            raise
    snapshot_id = record.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SNAPSHOT_ID_INVALID"
        )
    existing = load_snapshot(snapshot_id, root=challenger_archive_root, verify=True)
    if (
        existing is None
        or not _valid_label_receipt_binding(existing)
        or not _valid_label_receipt_binding(record)
        or _label_independent_feature_identity(existing)
        != _label_independent_feature_identity(record)
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SNAPSHOT_ID_CONFLICT"
        )
    return None, True


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


def _reconstructed_record_from_verified_label_binding(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    label_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one challenger row from a manifest-reverified label binding."""

    binding = dict(label_binding)
    claimed_binding_sha = binding.get("label_binding_sha256")
    if (
        type(claimed_binding_sha) is not str
        or not claimed_binding_sha
        or binding.get("decision_time") != sample.decision_time
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_MANIFEST_LABEL_BINDING_INVALID"
        )
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
        "canonical_label_binding_sha256": claimed_binding_sha,
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
            "label_binding": binding,
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
    label_high_water = label_archive_high_water_for_integrity_v1(
        archive=label_archive,
        integrity=integrity,
        observation=observed,
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
                label_binding, label_reasons = build_finalized_label_binding_v1(
                    sample=sample,
                    archive=label_archive,
                    observation=observed,
                    archive_integrity=integrity,
                    archive_high_water=label_high_water,
                )
                if label_binding is None:
                    for reason in label_reasons or ("CANONICAL_LABEL_PATH_UNVERIFIED",):
                        rejection_reasons[str(reason)] += 1
                    continue
                record = _reconstructed_record_from_verified_label_binding(
                    sample=sample,
                    label_binding=label_binding,
                )
                result, reused_label_observation = (
                    _append_or_reuse_label_observation_record(
                        record=record,
                        challenger_archive_root=archive_root,
                    )
                )
            except (
                OSError,
                ValueError,
                ProfiledTrainingChallengerImportError,
                ProfiledTrainingObservationManifestV1Error,
            ) as exc:
                rejection_reasons[str(exc) or type(exc).__name__] += 1
                continue
            label_paths_verified += 1
            imported_ids.append(str(record["snapshot_id"]))
            if reused_label_observation or (result is not None and result.already_present):
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


def _manifest_shard_checkpoint_path(
    *,
    challenger_archive_root: Path,
    checkpoint_path: Path | None,
) -> Path:
    path = checkpoint_path or (
        challenger_archive_root / DEFAULT_MANIFEST_SHARD_CHECKPOINT_FILENAME
    )
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path.parent != challenger_archive_root
        or path.is_symlink()
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_CHECKPOINT_PATH_INVALID"
        )
    return path


def _read_manifest_shard_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_CHECKPOINT_UNSAFE"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_CHECKPOINT_INVALID"
        ) from exc
    if (
        type(payload) is not dict
        or payload.get("schema_version") != MANIFEST_SHARD_CHECKPOINT_SCHEMA_VERSION
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_CHECKPOINT_INVALID"
        )
    return payload


def import_profiled_training_observation_manifest_shard_to_challenger_archive_v1(
    *,
    manifest_path: Path,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    expected_manifest_id: str,
    expected_observation_time: str,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    challenger_archive_root: Path,
    checkpoint_path: Path | None = None,
    shard_size: int = 1,
    progress_consumer: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Durably import one bounded page from an exact HMAC-authenticated manifest.

    This is evidence maintenance only.  It neither admits an optimizer nor
    grants checkpoint, prediction, paper, live, or execution authority.
    """

    if (
        type(ledger) is not DurableFeatureSnapshotLedger
        or type(label_archive) is not DurableCanonical5mLabelArchive
        or not isinstance(manifest_path, Path)
        or not manifest_path.is_absolute()
        or manifest_path.is_symlink()
        or not isinstance(trusted_immutable_cost_store_root, Path)
        or not trusted_immutable_cost_store_root.is_absolute()
        or not isinstance(challenger_archive_root, Path)
        or not challenger_archive_root.is_absolute()
        or challenger_archive_root.is_symlink()
        or type(shard_size) is not int
        or not 0 < shard_size <= MAX_IMPORT_PAGE_SIZE
        or progress_consumer is not None
        and not callable(progress_consumer)
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_ARGUMENT_INVALID"
        )
    archive_root = challenger_archive_root
    try:
        archive_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_ARCHIVE_ROOT_UNAVAILABLE"
        ) from exc
    if not archive_root.is_dir() or archive_root.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_ARCHIVE_ROOT_UNSAFE"
        )
    try:
        authenticated_manifest = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=manifest_path,
            hmac_key=manifest_hmac_key,
            expected_auth_key_id=manifest_auth_key_id,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_AUTHENTICATION_FAILED"
        ) from exc
    path = _manifest_shard_checkpoint_path(
        challenger_archive_root=archive_root,
        checkpoint_path=checkpoint_path,
    )
    checkpoint = _read_manifest_shard_checkpoint(path)
    if checkpoint is None:
        after_ordinal = 0
        completed_shards = 0
        completed = False
    else:
        if (
            checkpoint.get("archive_root") != str(archive_root)
            or checkpoint.get("manifest_path") != str(manifest_path)
            or checkpoint.get("manifest_id") != authenticated_manifest.manifest_id
            or checkpoint.get("observation_time")
            != authenticated_manifest.observation_time
            or checkpoint.get("entry_chain_head_sha256")
            != authenticated_manifest.entry_chain_head_sha256
            or checkpoint.get("label_archive_path") != str(label_archive.path.resolve())
            or checkpoint.get("cost_store_root")
            != str(trusted_immutable_cost_store_root)
            or type(checkpoint.get("next_after_ordinal")) is not int
            or checkpoint["next_after_ordinal"] < 0
            or type(checkpoint.get("completed_shards")) is not int
            or checkpoint["completed_shards"] < 0
            or type(checkpoint.get("completed")) is not bool
        ):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_MANIFEST_SHARD_CHECKPOINT_CONTEXT_INVALID"
            )
        after_ordinal = checkpoint["next_after_ordinal"]
        completed_shards = checkpoint["completed_shards"]
        completed = checkpoint["completed"]
    if completed:
        return {
            "schema_version": MANIFEST_SHARD_CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_path": str(path),
            "manifest_id": authenticated_manifest.manifest_id,
            "next_after_ordinal": after_ordinal,
            "completed_shards": completed_shards,
            "completed": True,
            "shards_processed_this_run": 0,
            "imported_rows": 0,
            "duplicate_rows": 0,
            "label_unavailable_rows": 0,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
        }
    reopened: list[tuple[ProfiledTrainingLedgerSampleV1, Mapping[str, Any]]] = []

    def collect_reopened(
        sample: ProfiledTrainingLedgerSampleV1,
        entry: Mapping[str, Any],
    ) -> None:
        reopened.append((sample, entry))

    try:
        page = read_profiled_training_observation_page_v1(
            manifest_path=manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
            hmac_key=manifest_hmac_key,
            expected_auth_key_id=manifest_auth_key_id,
            expected_manifest_id=authenticated_manifest.manifest_id,
            expected_observation_time=authenticated_manifest.observation_time,
            after_ordinal=after_ordinal,
            limit=shard_size,
            reopened_sample_consumer=collect_reopened,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_REOPEN_FAILED"
        ) from exc
    if len(reopened) != len(page.examples):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_MANIFEST_SHARD_REOPEN_COUNT_MISMATCH"
        )
    imported = duplicates = 0
    write_paths: list[tuple[Path, Path]] = []
    for sample, entry in reopened:
        label_binding = entry.get("label_binding")
        if (
            type(label_binding) is not dict
            or label_binding.get("archive_path") != str(label_archive.path.resolve())
        ):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_MANIFEST_SHARD_LABEL_ARCHIVE_MISMATCH"
            )
        try:
            record = _reconstructed_record_from_verified_label_binding(
                sample=sample,
                label_binding=label_binding,
            )
            write_result, reused_label_observation = (
                _append_or_reuse_label_observation_record(
                    record=record,
                    challenger_archive_root=archive_root,
                )
            )
        except (OSError, ValueError, ProfiledTrainingChallengerImportError) as exc:
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_MANIFEST_SHARD_ARCHIVE_WRITE_FAILED"
            ) from exc
        if write_result is not None and not write_result.already_present:
            write_paths.append((write_result.blob_path, write_result.index_path))
        if reused_label_observation or (
            write_result is not None and write_result.already_present
        ):
            duplicates += 1
        else:
            imported += 1
    _commit_shard_writes_durably(
        archive_root=archive_root,
        write_paths=write_paths,
    )
    completed_shards += 1
    completed = not page.has_more_manifest_entries
    checkpoint_payload = {
        "schema_version": MANIFEST_SHARD_CHECKPOINT_SCHEMA_VERSION,
        "archive_root": str(archive_root),
        "manifest_path": str(manifest_path),
        "manifest_id": authenticated_manifest.manifest_id,
        "observation_time": authenticated_manifest.observation_time,
        "entry_chain_head_sha256": authenticated_manifest.entry_chain_head_sha256,
        "label_archive_path": str(label_archive.path.resolve()),
        "cost_store_root": str(trusted_immutable_cost_store_root),
        "next_after_ordinal": page.next_after_ordinal,
        "completed_shards": completed_shards,
        "completed": completed,
    }
    _write_checkpoint_atomic(path, checkpoint_payload)
    result = {
        "schema_version": MANIFEST_SHARD_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_path": str(path),
        "manifest_id": authenticated_manifest.manifest_id,
        "source_scanned_entry_count": page.scanned_entry_count,
        "source_admitted_entry_count": len(reopened),
        "label_unavailable_rows": page.label_unavailable_scanned,
        "imported_rows": imported,
        "duplicate_rows": duplicates,
        "next_after_ordinal": page.next_after_ordinal,
        "completed_shards": completed_shards,
        "completed": completed,
        "shards_processed_this_run": 1,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    if progress_consumer is not None:
        progress_consumer(result)
    return result


def _checkpoint_path(
    *,
    challenger_archive_root: Path,
    checkpoint_path: Path | None,
) -> Path:
    path = checkpoint_path or (
        challenger_archive_root / DEFAULT_SHARD_CHECKPOINT_FILENAME
    )
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path.parent != challenger_archive_root
        or path.is_symlink()
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_PATH_INVALID"
        )
    return path


def _read_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_UNSAFE"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_INVALID"
        ) from exc
    if type(payload) is not dict or payload.get("schema_version") != (
        SHARD_CHECKPOINT_SCHEMA_VERSION
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_INVALID"
        )
    return payload


def _label_integrity_checkpoint_path(*, challenger_archive_root: Path) -> Path:
    path = challenger_archive_root / DEFAULT_LABEL_INTEGRITY_CHECKPOINT_FILENAME
    if path.parent != challenger_archive_root or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_INTEGRITY_CHECKPOINT_PATH_INVALID"
        )
    return path


def _read_label_integrity_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_INTEGRITY_CHECKPOINT_UNSAFE"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_INTEGRITY_CHECKPOINT_INVALID"
        ) from exc
    if (
        type(payload) is not dict
        or payload.get("schema_version") != LABEL_INTEGRITY_CHECKPOINT_SCHEMA_VERSION
        or type(payload.get("label_archive_path")) is not str
        or not isinstance(payload.get("integrity_proof"), dict)
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_INTEGRITY_CHECKPOINT_INVALID"
        )
    return payload


def _load_or_verify_label_integrity(
    *,
    challenger_archive_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
) -> tuple[dict[str, Any], bool, Path]:
    """Reuse a full proof only while each bounded label read proves it current."""

    path = _label_integrity_checkpoint_path(
        challenger_archive_root=challenger_archive_root,
    )
    cached = _read_label_integrity_checkpoint(path)
    if cached is not None:
        if cached["label_archive_path"] != str(label_archive.path.resolve()):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_LABEL_INTEGRITY_CHECKPOINT_CONTEXT_INVALID"
            )
        return dict(cached["integrity_proof"]), True, path
    integrity = label_archive.verify_integrity()
    if integrity.get("archive_integrity_verified") is not True:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
        )
    _write_checkpoint_atomic(
        path,
        {
            "schema_version": LABEL_INTEGRITY_CHECKPOINT_SCHEMA_VERSION,
            "label_archive_path": str(label_archive.path.resolve()),
            "integrity_proof": integrity,
        },
    )
    return integrity, False, path


def _write_checkpoint_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_PARENT_UNSAFE"
        )
    encoded = (
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_WRITE_FAILED"
        ) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _fsync_existing_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SHARD_FILE_UNSAFE"
        )
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SHARD_FILE_FSYNC_FAILED"
        ) from exc


def _fsync_existing_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SHARD_DIRECTORY_UNSAFE"
        )
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SHARD_DIRECTORY_FSYNC_FAILED"
        ) from exc


def _commit_shard_writes_durably(
    *,
    archive_root: Path,
    write_paths: list[tuple[Path, Path]],
) -> None:
    """Make only this shard durable; never rescan the global archive here."""

    if not write_paths:
        return
    directories = {
        archive_root,
        archive_root / "index",
        archive_root / "index" / "snapshot_id",
    }
    for blob_path, index_path in write_paths:
        try:
            blob_path.relative_to(archive_root)
            index_path.relative_to(archive_root)
        except ValueError as exc:
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_SHARD_WRITE_OUTSIDE_ARCHIVE"
            ) from exc
        _fsync_existing_file(blob_path)
        _fsync_existing_file(index_path)
        directories.update((blob_path.parent, index_path.parent))
    _fsync_existing_file(archive_root / "manifest.jsonl")
    for directory in sorted(directories, key=str):
        _fsync_existing_directory(directory)


def _post_purge_counts(
    *,
    challenger_archive_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    label_archive_integrity_proof: Mapping[str, Any] | None = None,
    training_observed_at: str,
) -> dict[str, int]:
    # Import locally to retain the importer as the one-way data boundary.
    from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
        _split_rows,
        freeze_dataset_from_archive,
    )

    freeze = freeze_dataset_from_archive(
        archive_root=challenger_archive_root,
        canonical_label_archive=label_archive,
        canonical_label_integrity_proof=label_archive_integrity_proof,
        training_observed_at=training_observed_at,
    )
    train, validation, holdout, split_manifest = _split_rows(freeze.rows)
    return {
        "train_rows": len(train),
        "validation_rows": len(validation),
        "untouched_holdout_rows": len(holdout),
        "decision_time_groups": int(
            split_manifest.get("decision_time_groups", 0)
        ),
    }


def import_profiled_training_ledger_shards_to_challenger_archive_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    challenger_archive_root: Path,
    checkpoint_path: Path | None = None,
    training_observed_at: str | None = None,
    shard_size: int = MAX_IMPORT_PAGE_SIZE,
    max_shards: int = 1,
    minimum_train_rows: int = DEFAULT_MINIMUM_TRAIN_ROWS,
    minimum_validation_rows: int = DEFAULT_MINIMUM_VALIDATION_ROWS,
    minimum_holdout_rows: int = DEFAULT_MINIMUM_HOLDOUT_ROWS,
    progress_consumer: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Import bounded authenticated shards and atomically checkpoint progress.

    The cursor is advanced only after every row in its shard has been written
    and its blob, index, and append manifest have been durably fsynced.  A
    restart resumes at the next immutable ledger page;
    a crash before checkpointing may verify a partial page again, but archive
    snapshot IDs make that recovery idempotent.
    """

    if type(ledger) is not DurableFeatureSnapshotLedger:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LEDGER_EXACT_TYPE_REQUIRED"
        )
    if type(label_archive) is not DurableCanonical5mLabelArchive:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED"
        )
    if (
        type(shard_size) is not int
        or not 0 < shard_size <= MAX_IMPORT_PAGE_SIZE
        or type(max_shards) is not int
        or max_shards <= 0
        or any(
            type(value) is not int or value <= 0
            for value in (
                minimum_train_rows,
                minimum_validation_rows,
                minimum_holdout_rows,
            )
        )
        or progress_consumer is not None
        and not callable(progress_consumer)
    ):
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_SHARD_CONFIGURATION_INVALID"
        )
    archive_root = challenger_archive_root.resolve()
    try:
        archive_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_ARCHIVE_ROOT_UNAVAILABLE"
        ) from exc
    if not archive_root.is_dir() or archive_root.is_symlink():
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_ARCHIVE_ROOT_UNSAFE"
        )
    path = _checkpoint_path(
        challenger_archive_root=archive_root,
        checkpoint_path=checkpoint_path,
    )
    checkpoint = _read_checkpoint(path)
    if checkpoint is None:
        observed = _utc_iso(
            _aware_utc(training_observed_at, field="OBSERVATION_TIME")
            if training_observed_at is not None
            else datetime.now(UTC)
        )
        after_sequence = 0
        page_cursor = None
        completed_shards = 0
        completed = False
        halted_at_minimums = False
    else:
        if (
            checkpoint.get("archive_root") != str(archive_root)
            or checkpoint.get("cost_store_root")
            != str(trusted_immutable_cost_store_root)
            or checkpoint.get("label_archive_path") != str(label_archive.path.resolve())
            or type(checkpoint.get("training_observed_at")) is not str
            or type(checkpoint.get("next_after_sequence")) is not int
            or checkpoint["next_after_sequence"] < 0
            or checkpoint.get("next_cursor") is not None
            and type(checkpoint.get("next_cursor")) is not str
            or type(checkpoint.get("completed_shards")) is not int
            or checkpoint["completed_shards"] < 0
            or type(checkpoint.get("completed")) is not bool
            or type(checkpoint.get("last_minimums_met")) is not bool
            or any(
                type(checkpoint.get(field, 0)) is not int
                or checkpoint.get(field, 0) < 0
                for field in (
                    "cumulative_imported_rows",
                    "cumulative_duplicate_rows",
                    "cumulative_rejected_rows",
                )
            )
            or not isinstance(
                checkpoint.get("cumulative_rejections_by_reason", {}), dict
            )
            or any(
                type(reason) is not str
                or not reason
                or type(count) is not int
                or count < 0
                for reason, count in checkpoint.get(
                    "cumulative_rejections_by_reason", {}
                ).items()
            )
            or checkpoint.get("last_candidate_id") is not None
            and type(checkpoint.get("last_candidate_id")) is not str
        ):
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_CHECKPOINT_CONTEXT_INVALID"
            )
        observed = checkpoint["training_observed_at"]
        after_sequence = checkpoint["next_after_sequence"]
        page_cursor = checkpoint["next_cursor"]
        completed_shards = checkpoint["completed_shards"]
        completed = checkpoint["completed"]
        halted_at_minimums = checkpoint["last_minimums_met"]
    cumulative_imported_rows = int(
        checkpoint.get("cumulative_imported_rows", 0) if checkpoint else 0
    )
    cumulative_duplicate_rows = int(
        checkpoint.get("cumulative_duplicate_rows", 0) if checkpoint else 0
    )
    cumulative_rejected_rows = int(
        checkpoint.get("cumulative_rejected_rows", 0) if checkpoint else 0
    )
    cumulative_rejections: Counter[str] = Counter(
        checkpoint.get("cumulative_rejections_by_reason", {}) if checkpoint else {}
    )
    last_candidate_id = checkpoint.get("last_candidate_id") if checkpoint else None
    if completed or halted_at_minimums:
        saved_counts = checkpoint.get("last_post_purge_counts") if checkpoint else None
        return {
            "schema_version": SHARD_CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_path": str(path),
            "training_observed_at": observed,
            "shards_completed": completed_shards,
            "shards_processed_this_run": 0,
            "completed": completed,
            "minimums_met": halted_at_minimums,
            "halted_at_minimums": halted_at_minimums,
            "cumulative_imported_rows": cumulative_imported_rows,
            "cumulative_duplicate_rows": cumulative_duplicate_rows,
            "cumulative_rejected_rows": cumulative_rejected_rows,
            "cumulative_rejections_by_reason": dict(
                sorted(cumulative_rejections.items())
            ),
            "last_candidate_id": last_candidate_id,
            "last_completed_sequence": after_sequence,
            "post_purge_counts": (
                saved_counts
                if isinstance(saved_counts, dict)
                else _post_purge_counts(
                    challenger_archive_root=archive_root,
                    label_archive=label_archive,
                    label_archive_integrity_proof=None,
                    training_observed_at=observed,
                )
            ),
        }

    integrity, label_integrity_checkpoint_reused, label_integrity_path = (
        _load_or_verify_label_integrity(
            challenger_archive_root=archive_root,
            label_archive=label_archive,
        )
    )
    observed_clock = _aware_utc(observed, field="OBSERVATION_TIME")
    # Defect B: the reused full integrity proof can go stale against a
    # continuously appended label archive. Cheaply confirm it is still current;
    # only when it is not do we re-derive a fresh proof. A quiescent archive
    # (e.g. the completed-resume path) never pays a full re-verification.
    if not label_archive.integrity_proof_is_current(integrity):
        fresh_integrity, _fresh_high_water = (
            derive_label_archive_fixed_observation_proof_v1(
                archive=label_archive,
                observation=observed_clock,
            )
        )
        if fresh_integrity is None:
            raise ProfiledTrainingChallengerImportError(
                "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
            )
        integrity = fresh_integrity
    label_high_water = label_archive_high_water_for_integrity_v1(
        archive=label_archive,
        integrity=integrity,
        observation=observed_clock,
    )

    last_post_purge_counts = checkpoint.get("last_post_purge_counts") if checkpoint else None
    if not isinstance(last_post_purge_counts, dict):
        last_post_purge_counts = {}
    total_imported = total_duplicates = total_excluded = 0
    total_label_paths = 0
    total_rejections: Counter[str] = Counter()
    verified_source_entries: dict[
        str, dict[int, TrainerSourceProvenanceLedgerEntryV4]
    ] = {}
    shard_reports: list[dict[str, Any]] = []
    post_purge_counts: dict[str, Any] = dict(last_post_purge_counts)
    minimums_met = False
    for shard_index in range(max_shards):
        shard_started = datetime.now(UTC)
        batch = load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
            training_observed_at=observed,
            scan_limit=shard_size,
            after_sequence=after_sequence,
            page_cursor=page_cursor,
            _verified_source_entries_cache=verified_source_entries,
        )
        imported = duplicates = label_paths = 0
        write_paths: list[tuple[Path, Path]] = []
        rejections: Counter[str] = Counter(
            str(exclusion.reason) for exclusion in batch.exclusions
        )
        for sample in batch.samples:
            last_candidate_id = sample.durable_snapshot_id
            # Defect B, hot-archive execution path: the label archive is
            # continuously appended, so the shared proof can go stale between
            # rows.  A cheap currency check (no scan) refreshes the shared proof
            # at most once per append instead of re-verifying per row;
            # build_finalized_label_binding_v1 still re-proofs internally if the
            # archive advances within the row itself.
            if not label_archive.integrity_proof_is_current(integrity):
                fresh_integrity, fresh_high_water = (
                    derive_label_archive_fixed_observation_proof_v1(
                        archive=label_archive,
                        observation=observed_clock,
                    )
                )
                if fresh_integrity is not None and fresh_high_water is not None:
                    integrity = fresh_integrity
                    label_high_water = fresh_high_water
            try:
                label_binding, label_reasons = build_finalized_label_binding_v1(
                    sample=sample,
                    archive=label_archive,
                    observation=observed_clock,
                    archive_integrity=integrity,
                    archive_high_water=label_high_water,
                )
                if label_binding is None:
                    for reason in label_reasons or ("CANONICAL_LABEL_PATH_UNVERIFIED",):
                        rejections[str(reason)] += 1
                    continue
                record = _reconstructed_record_from_verified_label_binding(
                    sample=sample,
                    label_binding=label_binding,
                )
                write_result, reused_label_observation = (
                    _append_or_reuse_label_observation_record(
                        record=record,
                        challenger_archive_root=archive_root,
                    )
                )
            except (
                OSError,
                ValueError,
                ProfiledTrainingChallengerImportError,
                ProfiledTrainingObservationManifestV1Error,
            ) as exc:
                rejections[str(exc) or type(exc).__name__] += 1
                continue
            label_paths += 1
            if write_result is not None and not write_result.already_present:
                write_paths.append((write_result.blob_path, write_result.index_path))
            if reused_label_observation or (
                write_result is not None and write_result.already_present
            ):
                duplicates += 1
            else:
                imported += 1
        # The full archive has millions of historical snapshots, so a global
        # checksum rewrite is not a bounded shard operation.  The blob, index,
        # append-only manifest, and their directories are fsynced before the
        # cursor checkpoint instead.  A crash before that checkpoint restarts
        # this page idempotently; a completed checkpoint never points past a
        # durable shard.
        _commit_shard_writes_durably(
            archive_root=archive_root,
            write_paths=write_paths,
        )
        completed_shards += 1
        after_sequence = batch.next_after_sequence
        page_cursor = batch.next_cursor
        completed = batch.next_cursor is None
        cumulative_imported_rows += imported
        cumulative_duplicate_rows += duplicates
        cumulative_rejected_rows += sum(rejections.values())
        cumulative_rejections.update(rejections)
        # Materializing the complete challenger view is intentionally deferred
        # until this fixed observation is exhausted.  Repeating its 60k-row
        # bounded scan after every one-row source page starves the checkpoint
        # path while adding no new decision-time group evidence.  Each source
        # page remains fully durable and resumable; the final page computes the
        # exact post-purge proof before the completed checkpoint is published.
        post_purge_assessed = completed
        if post_purge_assessed:
            post_purge_counts = _post_purge_counts(
                challenger_archive_root=archive_root,
                label_archive=label_archive,
                label_archive_integrity_proof=integrity,
                training_observed_at=observed,
            )
            minimums_met = (
                post_purge_counts["train_rows"] >= minimum_train_rows
                and post_purge_counts["validation_rows"] >= minimum_validation_rows
                and post_purge_counts["untouched_holdout_rows"] >= minimum_holdout_rows
            )
        else:
            minimums_met = False
        checkpoint_payload = {
            "schema_version": SHARD_CHECKPOINT_SCHEMA_VERSION,
            "archive_root": str(archive_root),
            "cost_store_root": str(trusted_immutable_cost_store_root),
            "label_archive_path": str(label_archive.path.resolve()),
            "training_observed_at": observed,
            "next_after_sequence": after_sequence,
            "next_cursor": page_cursor,
            "completed_shards": completed_shards,
            "completed": completed,
            "last_post_purge_counts": post_purge_counts,
            "last_minimums_met": minimums_met,
            "cumulative_imported_rows": cumulative_imported_rows,
            "cumulative_duplicate_rows": cumulative_duplicate_rows,
            "cumulative_rejected_rows": cumulative_rejected_rows,
            "cumulative_rejections_by_reason": dict(
                sorted(cumulative_rejections.items())
            ),
            "last_candidate_id": last_candidate_id,
            "last_completed_sequence": after_sequence,
        }
        _write_checkpoint_atomic(path, checkpoint_payload)
        elapsed_seconds = (datetime.now(UTC) - shard_started).total_seconds()
        report = {
            "shard_number": completed_shards,
            "shard_index_this_run": shard_index + 1,
            "source_scanned_record_count": batch.scanned_record_count,
            "source_admitted_sample_count": len(batch.samples),
            "source_exclusion_count": len(batch.exclusions),
            "imported_rows": imported,
            "duplicate_rows": duplicates,
            "cumulative_imported_rows": cumulative_imported_rows,
            "cumulative_duplicate_rows": cumulative_duplicate_rows,
            "cumulative_rejected_rows": cumulative_rejected_rows,
            "cumulative_rejections_by_reason": dict(
                sorted(cumulative_rejections.items())
            ),
            "last_candidate_id": last_candidate_id,
            "last_completed_sequence": after_sequence,
            "label_paths_verified": label_paths,
            "rejections_by_reason": dict(sorted(rejections.items())),
            "shards_remaining": (
                0
                if completed or minimums_met
                else math.ceil(
                    max(
                        0,
                        batch.authenticated_prefix_record_count - after_sequence,
                    )
                    / shard_size
                )
            ),
            "elapsed_seconds": elapsed_seconds,
            "post_purge_counts": post_purge_counts,
            "post_purge_assessment_pending": not post_purge_assessed,
            "minimums_met": minimums_met,
            "checkpoint_path": str(path),
            "label_integrity_checkpoint_path": str(label_integrity_path),
            "label_integrity_checkpoint_reused": label_integrity_checkpoint_reused,
        }
        shard_reports.append(report)
        if progress_consumer is not None:
            progress_consumer(report)
        total_imported += imported
        total_duplicates += duplicates
        total_excluded += len(batch.exclusions)
        total_label_paths += label_paths
        total_rejections.update(rejections)
        if completed or minimums_met:
            break
    return {
        "schema_version": SHARD_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_path": str(path),
        "label_integrity_checkpoint_path": str(label_integrity_path),
        "label_integrity_checkpoint_reused": label_integrity_checkpoint_reused,
        "training_observed_at": observed,
        "shards_completed": completed_shards,
        "shards_processed_this_run": len(shard_reports),
        "completed": completed,
        "minimums_met": minimums_met,
        "halted_at_minimums": minimums_met,
        "total_imported_rows": total_imported,
        "total_duplicate_rows": total_duplicates,
        "total_source_exclusions": total_excluded,
        "total_label_paths_verified": total_label_paths,
        "total_rejections_by_reason": dict(sorted(total_rejections.items())),
        "cumulative_imported_rows": cumulative_imported_rows,
        "cumulative_duplicate_rows": cumulative_duplicate_rows,
        "cumulative_rejected_rows": cumulative_rejected_rows,
        "cumulative_rejections_by_reason": dict(
            sorted(cumulative_rejections.items())
        ),
        "last_candidate_id": last_candidate_id,
        "last_completed_sequence": after_sequence,
        "post_purge_counts": post_purge_counts,
        "shards": shard_reports,
        "paper_only": True,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
