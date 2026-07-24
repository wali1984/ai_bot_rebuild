"""Checkpointed PIT importer from profiled ledger samples to challenger replay.

One invocation imports one bounded source shard.  It authenticates that shard
through the existing profiled ledger loader, obtains its forward label only
from the canonical 5m archive, then appends deterministic replay snapshots to
the challenger's durable archive.  A durable checkpoint advances only after
every admitted row is atomically readable from that archive.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveError,
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    append_snapshot,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    label_archive_fixed_observation_high_water,
)
from v2.backend.app.services.native_trainer.profiled_pit_replay_projection_v1 import (
    project_profiled_training_sample_to_replay_snapshot_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    ProfiledTrainingLedgerSampleV1,
    ProfiledTrainingSourceProvenanceSnapshotSessionV1,
    admit_profiled_training_ledger_item_direct_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    ProfiledTrainingObservationManifestV1Error,
    build_profiled_training_label_binding_v1,
)

PROFILED_PIT_REPLAY_IMPORTER_V1_SCHEMA_VERSION: Final = "profiled_pit_replay_importer_v1"
PROFILED_PIT_REPLAY_IMPORTER_V1_STATE_FILENAME: Final = "checkpoint.json"


class ProfiledPitReplayImporterV1Error(RuntimeError):
    """A bounded importer shard could not be authenticated or committed."""


def _fail(reason: str) -> NoReturn:
    raise ProfiledPitReplayImporterV1Error(reason) from None


def _canonical_clock(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _exact_root(value: Path, *, reason: str, create: bool) -> Path:
    if type(value) is not type(Path()) or not value.is_absolute() or ".." in value.parts:
        _fail(reason)
    resolved = value.resolve(strict=False)
    if resolved != value:
        _fail(reason)
    if create:
        value.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not value.is_dir() or value.is_symlink():
        _fail(reason)
    return value


def _state_path(root: Path) -> Path:
    return root / PROFILED_PIT_REPLAY_IMPORTER_V1_STATE_FILENAME


def _new_state() -> dict[str, Any]:
    return {
        "schema_version": PROFILED_PIT_REPLAY_IMPORTER_V1_SCHEMA_VERSION,
        "last_completed_sequence": 0,
        "completed_shards": [],
    }


def _read_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return _new_state()
    if path.is_symlink() or not path.is_file():
        _fail("PROFILED_PIT_REPLAY_IMPORTER_STATE_PATH_INVALID")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("PROFILED_PIT_REPLAY_IMPORTER_STATE_READ_INVALID")
    if (
        type(raw) is not dict
        or raw.get("schema_version") != PROFILED_PIT_REPLAY_IMPORTER_V1_SCHEMA_VERSION
        or type(raw.get("last_completed_sequence")) is not int
        or raw["last_completed_sequence"] < 0
        or type(raw.get("completed_shards")) is not list
    ):
        _fail("PROFILED_PIT_REPLAY_IMPORTER_STATE_INVALID")
    return cast(dict[str, Any], raw)


def _write_state_atomic(root: Path, state: Mapping[str, Any]) -> None:
    path = _state_path(root)
    temporary = root / f".{path.name}.{os.getpid()}.tmp"
    payload = json.dumps(dict(state), sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directory_descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProfiledPitReplayImporterV1Error(
            f"PROFILED_PIT_REPLAY_IMPORTER_STATE_WRITE_FAILED:{type(exc).__name__}"
        ) from exc


def _label_high_water(
    *,
    archive: DurableCanonical5mLabelArchive,
    observation: datetime,
) -> dict[str, Any]:
    try:
        integrity = archive.verify_integrity()
        if integrity.get("archive_integrity_verified") is not True:
            _fail("PROFILED_PIT_REPLAY_IMPORTER_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED")
        high_water = label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=integrity,
            observation_cutoff=observation,
            scan_limit=max(
                int(integrity.get("verified_rows") or 0),
                int(integrity.get("verified_append_receipts") or 0),
                1,
            ),
        )
    except Canonical5mArchiveError as exc:
        raise ProfiledPitReplayImporterV1Error(
            f"PROFILED_PIT_REPLAY_IMPORTER_LABEL_ARCHIVE_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if (
        type(high_water) is not dict
        or high_water.get("full_archive_integrity_verified_at_reproduction") is not True
        or high_water.get("receipt_backed") is not True
        or high_water.get("postcommit_readback_verified") is not True
        or not isinstance(high_water.get("high_water_sha256"), str)
    ):
        _fail("PROFILED_PIT_REPLAY_IMPORTER_LABEL_HIGH_WATER_INVALID")
    return cast(dict[str, Any], high_water)


@dataclass(frozen=True, slots=True)
class ProfiledPitReplayImportShardResultV1:
    training_observed_at: str
    source_start_sequence: int | None
    source_end_sequence: int | None
    source_rows_scanned: int
    rows_imported: int
    rows_already_present: int
    rows_excluded: int
    excluded_by_reason: dict[str, int]
    checkpoint_last_completed_sequence: int
    source_rows_remaining: bool
    elapsed_seconds: float


def import_next_profiled_pit_replay_shard_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    challenger_archive_root: Path,
    checkpoint_root: Path,
    training_observed_at: str,
    source_shard_rows: int,
) -> ProfiledPitReplayImportShardResultV1:
    """Import the next bounded source shard and atomically advance its checkpoint.

    The loader's pre/post high-water proof authenticates the source page.  The
    label archive receives the same fixed observation before and after all
    canonical label joins.  No checkpoint advances on a moved observation.
    """

    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_PIT_REPLAY_IMPORTER_LEDGER_EXACT_TYPE_REQUIRED")
    if type(label_archive) is not DurableCanonical5mLabelArchive:
        _fail("PROFILED_PIT_REPLAY_IMPORTER_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED")
    if type(source_shard_rows) is not int or source_shard_rows <= 0:
        _fail("PROFILED_PIT_REPLAY_IMPORTER_SOURCE_SHARD_ROWS_INVALID")
    archive_root = _exact_root(
        challenger_archive_root,
        reason="PROFILED_PIT_REPLAY_IMPORTER_CHALLENGER_ARCHIVE_ROOT_INVALID",
        create=True,
    )
    state_root = _exact_root(
        checkpoint_root,
        reason="PROFILED_PIT_REPLAY_IMPORTER_CHECKPOINT_ROOT_INVALID",
        create=True,
    )
    state = _read_state(state_root)
    started = datetime.now(tz=UTC)
    try:
        items = ledger.query_fixed_cutoff(
            decision_time_cutoff=training_observed_at,
            training_observed_at=training_observed_at,
            limit=source_shard_rows,
            after_sequence=cast(int, state["last_completed_sequence"]),
        )
    except Exception as exc:
        raise ProfiledPitReplayImporterV1Error(
            f"PROFILED_PIT_REPLAY_IMPORTER_SOURCE_READ_FAILED:{type(exc).__name__}"
        ) from exc
    observation = datetime.fromisoformat(training_observed_at.replace("Z", "+00:00"))
    label_before = _label_high_water(archive=label_archive, observation=observation)
    exclusions: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    with ProfiledTrainingSourceProvenanceSnapshotSessionV1() as source_snapshot_session:
        admitted_items = [
            admit_profiled_training_ledger_item_direct_v1(
                ledger=ledger,
                item=item,
                trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
                source_snapshot_session=source_snapshot_session,
            )
            for item in items
        ]
    for admitted in admitted_items:
        if admitted is None:
            continue
        if type(admitted) is not ProfiledTrainingLedgerSampleV1:
            exclusions[str(admitted.reason)] += 1
            continue
        sample = admitted
        try:
            label_binding, label_reasons = build_profiled_training_label_binding_v1(
                sample=sample,
                archive=label_archive,
                archive_high_water=label_before,
                observation=observation,
            )
        except ProfiledTrainingObservationManifestV1Error as exc:
            exclusions[f"LABEL_BINDING_FAILED:{exc}"] += 1
            continue
        if label_binding is None:
            for reason in label_reasons:
                exclusions[f"LABEL_UNAVAILABLE:{reason}"] += 1
            continue
        records.append(
            project_profiled_training_sample_to_replay_snapshot_v1(
                sample=sample,
                label_binding=label_binding,
            )
        )
    label_after = _label_high_water(archive=label_archive, observation=observation)
    if label_after != label_before:
        _fail("PROFILED_PIT_REPLAY_IMPORTER_LABEL_HIGH_WATER_MOVED")

    already_present = 0
    for record in records:
        write = append_snapshot(record, root=archive_root, update_checksum_manifest=True)
        already_present += int(write.already_present)
    scanned_start_sequence = items[0].sequence if items else None
    scanned_end_sequence = items[-1].sequence if items else None
    if scanned_end_sequence is not None:
        if scanned_end_sequence <= state["last_completed_sequence"]:
            _fail("PROFILED_PIT_REPLAY_IMPORTER_SOURCE_CHECKPOINT_NONMONOTONIC")
        shard_material = {
            "source_start_sequence": scanned_start_sequence,
            "source_end_sequence": scanned_end_sequence,
            "source_record_sha256s": [
                item.record.get("record_sha256") for item in items
            ],
            "label_high_water_sha256": label_before["high_water_sha256"],
            "record_content_sha256s": [record["content_sha256"] for record in records],
            "excluded_by_reason": dict(sorted(exclusions.items())),
        }
        completed = list(cast(list[object], state["completed_shards"]))
        completed.append({**shard_material, "shard_sha256": stable_sha256(shard_material)})
        state = {
            "schema_version": PROFILED_PIT_REPLAY_IMPORTER_V1_SCHEMA_VERSION,
            "last_completed_sequence": scanned_end_sequence,
            "completed_shards": completed,
        }
        _write_state_atomic(state_root, state)
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()
    return ProfiledPitReplayImportShardResultV1(
        training_observed_at=training_observed_at,
        source_start_sequence=scanned_start_sequence,
        source_end_sequence=scanned_end_sequence,
        source_rows_scanned=len(items),
        rows_imported=len(records) - already_present,
        rows_already_present=already_present,
        rows_excluded=sum(exclusions.values()),
        excluded_by_reason=dict(sorted(exclusions.items())),
        checkpoint_last_completed_sequence=cast(int, state["last_completed_sequence"]),
        source_rows_remaining=len(items) == source_shard_rows,
        elapsed_seconds=elapsed,
    )


__all__ = [
    "PROFILED_PIT_REPLAY_IMPORTER_V1_SCHEMA_VERSION",
    "ProfiledPitReplayImporterV1Error",
    "ProfiledPitReplayImportShardResultV1",
    "import_next_profiled_pit_replay_shard_v1",
]
