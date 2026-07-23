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
    load_profiled_training_ledger_v1,
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
DEFAULT_MINIMUM_TRAIN_ROWS = 1_000
DEFAULT_MINIMUM_VALIDATION_ROWS = 100
DEFAULT_MINIMUM_HOLDOUT_ROWS = 100


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
    to the challenger archive and the archive checksum manifest has been
    durably refreshed.  A restart resumes at the next immutable ledger page;
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
    integrity = label_archive.verify_integrity()
    if integrity.get("archive_integrity_verified") is not True:
        raise ProfiledTrainingChallengerImportError(
            "PROFILED_TRAINING_CHALLENGER_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
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
            "post_purge_counts": (
                saved_counts
                if isinstance(saved_counts, dict)
                else _post_purge_counts(
                    challenger_archive_root=archive_root,
                    label_archive=label_archive,
                    training_observed_at=observed,
                )
            ),
        }

    total_imported = total_duplicates = total_excluded = 0
    total_label_paths = 0
    total_rejections: Counter[str] = Counter()
    shard_reports: list[dict[str, Any]] = []
    post_purge_counts: dict[str, int] = {}
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
        )
        imported = duplicates = label_paths = 0
        write_paths: list[tuple[Path, Path]] = []
        rejections: Counter[str] = Counter(
            str(exclusion.reason) for exclusion in batch.exclusions
        )
        for sample in batch.samples:
            try:
                label_rows, label_proof = label_archive.verified_label_path(
                    symbol=sample.symbol,
                    decision_time=sample.decision_time,
                    training_observed_at=observed,
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
                        rejections[str(reason)] += 1
                    continue
                record = _reconstructed_record(
                    sample=sample,
                    label_rows=label_rows,
                    label_proof=label_proof,
                )
                write_result = append_snapshot(
                    record,
                    root=archive_root,
                    update_checksum_manifest=False,
                )
            except (OSError, ValueError, ProfiledTrainingChallengerImportError) as exc:
                rejections[str(exc) or type(exc).__name__] += 1
                continue
            label_paths += 1
            write_paths.append((write_result.blob_path, write_result.index_path))
            if write_result.already_present:
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
        post_purge_counts = _post_purge_counts(
            challenger_archive_root=archive_root,
            label_archive=label_archive,
            training_observed_at=observed,
        )
        minimums_met = (
            post_purge_counts["train_rows"] >= minimum_train_rows
            and post_purge_counts["validation_rows"] >= minimum_validation_rows
            and post_purge_counts["untouched_holdout_rows"] >= minimum_holdout_rows
        )
        completed_shards += 1
        after_sequence = batch.next_after_sequence
        page_cursor = batch.next_cursor
        completed = batch.next_cursor is None
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
            "minimums_met": minimums_met,
            "checkpoint_path": str(path),
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
        "post_purge_counts": post_purge_counts,
        "shards": shard_reports,
        "paper_only": True,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
