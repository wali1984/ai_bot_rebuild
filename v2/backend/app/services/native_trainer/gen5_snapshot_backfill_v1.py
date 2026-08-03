"""Durable, fixed-observation generation-5 corpus backfill.

The live feature and label producers remain online.  This runner uses SQLite's
online backup API to freeze each source database once, binds one observation
clock to those immutable files, and resumes the existing authenticated importer
one shard at a time.  Every completed shard and every observed termination is
fsynced before the process advances or exits.

This module has no prediction, paper-trading, or live-execution authority.
"""

from __future__ import annotations

import fcntl
import gc
import hashlib
import json
import os
import resource
import signal
import sqlite3
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    default_ledger_path,
)
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    import_profiled_training_ledger_shards_to_challenger_archive_v1,
)

SCHEMA_VERSION = "gen5_snapshot_backfill_v1"
SNAPSHOT_MANIFEST_SCHEMA_VERSION = "gen5_fixed_observation_manifest_v1"
PROGRESS_SCHEMA_VERSION = "gen5_backfill_shard_progress_v1"
TERMINAL_SCHEMA_VERSION = "gen5_backfill_terminal_receipt_v1"
MAX_IMPORT_THRESHOLD = 2**63 - 1
DEFAULT_COST_STORE_ROOT = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
DEFAULT_LABEL_ARCHIVE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/" "canonical_finalized_5m_label_archive.sqlite3"
)
DEFAULT_STATE_ROOT = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1")
SAFE_RESUME_COMMAND = "systemctl --user start ai-bot-v2-gen5-backfill.service"


class Gen5SnapshotBackfillError(RuntimeError):
    """Raised when the snapshot or backfill cannot be proved safe."""


class _ObservedSignal(BaseException):
    def __init__(self, signal_number: int) -> None:
        super().__init__(f"observed_signal_{signal_number}")
        self.signal_number = signal_number


@dataclass(frozen=True)
class Gen5BackfillConfig:
    source_ledger_path: Path
    source_label_archive_path: Path
    cost_store_root: Path
    state_root: Path
    shard_size: int = 32

    @classmethod
    def production_defaults(cls) -> Gen5BackfillConfig:
        return cls(
            source_ledger_path=default_ledger_path().resolve(),
            source_label_archive_path=DEFAULT_LABEL_ARCHIVE_PATH,
            cost_store_root=DEFAULT_COST_STORE_ROOT,
            state_root=DEFAULT_STATE_ROOT,
        )

    @property
    def snapshot_root(self) -> Path:
        return self.state_root / "snapshots"

    @property
    def snapshot_ledger_path(self) -> Path:
        return self.snapshot_root / "durable_feature_snapshot_ledger.sqlite3"

    @property
    def snapshot_label_archive_path(self) -> Path:
        return self.snapshot_root / "canonical_finalized_5m_label_archive.sqlite3"

    @property
    def snapshot_manifest_path(self) -> Path:
        return self.state_root / "snapshot_manifest.json"

    @property
    def challenger_archive_root(self) -> Path:
        return self.state_root / "challenger_archive"

    @property
    def importer_checkpoint_path(self) -> Path:
        return (
            self.challenger_archive_root / "profiled_training_challenger_import_checkpoint_v1.json"
        )

    @property
    def progress_path(self) -> Path:
        return self.state_root / "progress.jsonl"

    @property
    def status_path(self) -> Path:
        return self.state_root / "status.json"

    @property
    def terminal_history_path(self) -> Path:
        return self.state_root / "terminal_receipts.jsonl"

    @property
    def terminal_receipt_path(self) -> Path:
        return self.state_root / "terminal_receipt.json"

    @property
    def lock_path(self) -> Path:
        return self.state_root / "runner.lock"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise Gen5SnapshotBackfillError("GEN5_STATE_DIRECTORY_UNSAFE")
    path.chmod(0o700)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        if temporary.is_symlink() or not temporary.is_file():
            raise Gen5SnapshotBackfillError("GEN5_ATOMIC_TEMP_PATH_UNSAFE")
        temporary.unlink()
    data = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _append_jsonl_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    line = _canonical_bytes(payload) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, line)
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise Gen5SnapshotBackfillError("GEN5_JSON_PATH_UNSAFE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gen5SnapshotBackfillError("GEN5_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise Gen5SnapshotBackfillError("GEN5_JSON_OBJECT_REQUIRED")
    return value


def _readonly_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _quick_check(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or str(result[0]) != "ok":
        raise Gen5SnapshotBackfillError("GEN5_SQLITE_QUICK_CHECK_FAILED")


def _feature_state(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*), COALESCE(MAX(sequence), 0),
               COALESCE(SUM(strict_training_eligible), 0)
        FROM feature_snapshot_records
        """
    ).fetchone()
    head = connection.execute(
        """
        SELECT head_sequence, total_unique_rows, archive_chain_sha256,
               head_sha256, commit_prepared_at
        FROM feature_snapshot_ledger_heads
        ORDER BY head_sequence DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None or head is None:
        raise Gen5SnapshotBackfillError("GEN5_FEATURE_LEDGER_HIGH_WATER_MISSING")
    return {
        "record_count": int(row[0]),
        "high_water_sequence": int(row[1]),
        "strict_eligible_rows": int(row[2]),
        "head_sequence": int(head[0]),
        "head_total_unique_rows": int(head[1]),
        "archive_chain_sha256": str(head[2]),
        "head_sha256": str(head[3]),
        "commit_prepared_at": str(head[4]),
    }


def _label_state(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT COUNT(*), COALESCE(MAX(sequence), 0) FROM canonical_5m_candles"
    ).fetchone()
    receipt = connection.execute(
        """
        SELECT total_unique_rows, archive_chain_sha256,
               commit_prepared_at, receipt_sha256
        FROM canonical_5m_append_receipts
        ORDER BY rowid DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None or receipt is None:
        raise Gen5SnapshotBackfillError("GEN5_LABEL_ARCHIVE_HIGH_WATER_MISSING")
    return {
        "record_count": int(row[0]),
        "high_water_sequence": int(row[1]),
        "receipt_total_unique_rows": int(receipt[0]),
        "archive_chain_sha256": str(receipt[1]),
        "commit_prepared_at": str(receipt[2]),
        "receipt_sha256": str(receipt[3]),
    }


def _database_state(path: Path, *, kind: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise Gen5SnapshotBackfillError(f"GEN5_{kind.upper()}_DATABASE_UNSAFE")
    with sqlite3.connect(_readonly_uri(path), uri=True, timeout=60.0) as connection:
        _quick_check(connection)
        if kind == "feature":
            return _feature_state(connection)
        if kind == "label":
            return _label_state(connection)
    raise Gen5SnapshotBackfillError("GEN5_DATABASE_KIND_INVALID")


def _remove_explicit_regular_file(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_file() or path.is_symlink():
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_REPLACEMENT_PATH_UNSAFE")
    path.unlink()


def sqlite_snapshot(source: Path, destination: Path, *, kind: str) -> dict[str, Any]:
    """Create one transactionally consistent SQLite online-backup snapshot."""

    source = source.resolve()
    if not source.is_file() or source.is_symlink():
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_SOURCE_UNSAFE")
    _ensure_private_directory(destination.parent)
    partial = destination.with_name(f".{destination.name}.partial")
    _remove_explicit_regular_file(partial)
    _remove_explicit_regular_file(destination)

    source_before = _database_state(source, kind=kind)
    with sqlite3.connect(_readonly_uri(source), uri=True, timeout=60.0) as src:
        src.execute("BEGIN")
        source_transaction_state = _feature_state(src) if kind == "feature" else _label_state(src)
        with sqlite3.connect(str(partial), timeout=60.0) as dst:
            src.backup(dst, pages=2048, sleep=0.01)
    partial.chmod(0o600)
    snapshot_state = _database_state(partial, kind=kind)
    if snapshot_state != source_transaction_state:
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_HIGH_WATER_MISMATCH")
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(partial, destination)
    _fsync_directory(destination.parent)
    source_after = _database_state(source, kind=kind)
    return {
        "source_path": str(source),
        "snapshot_path": str(destination.resolve()),
        "source_high_water_before": source_before,
        "snapshot_high_water": snapshot_state,
        "source_high_water_after": source_after,
        "file_sha256": _sha256_file(destination),
        "file_bytes": destination.stat().st_size,
        "sqlite_quick_check": "ok",
        "online_backup_api": True,
    }


def _manifest_digest_material(manifest: Mapping[str, Any]) -> dict[str, Any]:
    material = dict(manifest)
    material.pop("manifest_sha256", None)
    return material


def _validate_snapshot_manifest(
    config: Gen5BackfillConfig,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest.get("schema_version") != SNAPSHOT_MANIFEST_SCHEMA_VERSION:
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_MANIFEST_SCHEMA_INVALID")
    expected_digest = _sha256_bytes(_canonical_bytes(_manifest_digest_material(manifest)))
    if manifest.get("manifest_sha256") != expected_digest:
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_MANIFEST_HASH_INVALID")
    if (
        manifest.get("paper_only") is not True
        or manifest.get("live_gate") != "blocked_human_only"
        or manifest.get("routes_to_live") is not False
        or manifest.get("places_real_order") is not False
        or manifest.get("exchange_action_taken") is not False
    ):
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_AUTHORITY_INVALID")
    databases = manifest.get("databases")
    if not isinstance(databases, dict):
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_DATABASES_INVALID")
    expected = {
        "feature": config.snapshot_ledger_path.resolve(),
        "label": config.snapshot_label_archive_path.resolve(),
    }
    for kind, path in expected.items():
        entry = databases.get(kind)
        if not isinstance(entry, dict) or entry.get("snapshot_path") != str(path):
            raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_PATH_BINDING_INVALID")
        if entry.get("file_sha256") != _sha256_file(path):
            raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_FILE_HASH_INVALID")
        state = _database_state(path, kind=kind)
        if state != entry.get("snapshot_high_water"):
            raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_STATE_CHANGED")
    return dict(manifest)


def load_or_create_fixed_snapshot(config: Gen5BackfillConfig) -> dict[str, Any]:
    existing = _read_json_object(config.snapshot_manifest_path)
    if existing is not None:
        return _validate_snapshot_manifest(config, existing)

    _ensure_private_directory(config.state_root)
    _ensure_private_directory(config.snapshot_root)
    started_at = _utc_now()
    feature = sqlite_snapshot(
        config.source_ledger_path,
        config.snapshot_ledger_path,
        kind="feature",
    )
    label = sqlite_snapshot(
        config.source_label_archive_path,
        config.snapshot_label_archive_path,
        kind="label",
    )
    completed_at = _utc_now()
    snapshot_identity_material = {
        "feature_sha256": feature["file_sha256"],
        "label_sha256": label["file_sha256"],
        "training_observed_at": completed_at,
    }
    snapshot_id = "gen5_fixed_observation_v1:" + _sha256_bytes(
        _canonical_bytes(snapshot_identity_material)
    )
    manifest: dict[str, Any] = {
        "schema_version": SNAPSHOT_MANIFEST_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "snapshot_started_at": started_at,
        "snapshot_completed_at": completed_at,
        "training_observed_at": completed_at,
        "databases": {"feature": feature, "label": label},
        "cost_store_root": str(config.cost_store_root.resolve()),
        "challenger_archive_root": str(config.challenger_archive_root.resolve()),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    manifest["manifest_sha256"] = _sha256_bytes(
        _canonical_bytes(_manifest_digest_material(manifest))
    )
    _write_json_atomic(config.snapshot_manifest_path, manifest)
    return _validate_snapshot_manifest(config, manifest)


def validate_existing_fixed_snapshot(config: Gen5BackfillConfig) -> dict[str, Any]:
    """Load and fully revalidate an existing snapshot without creating one."""

    manifest = _read_json_object(config.snapshot_manifest_path)
    if manifest is None:
        raise Gen5SnapshotBackfillError("GEN5_SNAPSHOT_MANIFEST_MISSING")
    return _validate_snapshot_manifest(config, manifest)


def _process_resources() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    descriptor_count: int | None
    try:
        descriptor_count = len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        descriptor_count = None
    return {
        "rss_peak_kib": int(usage.ru_maxrss),
        "open_file_descriptors": descriptor_count,
    }


def _manifest_tail(challenger_root: Path) -> tuple[int, str | None, int | None]:
    path = challenger_root / "manifest.jsonl"
    if not path.exists():
        return 0, None, None
    if not path.is_file() or path.is_symlink():
        raise Gen5SnapshotBackfillError("GEN5_CHALLENGER_MANIFEST_UNSAFE")
    rows = 0
    last: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            rows += 1
            value = json.loads(line)
            if not isinstance(value, dict):
                raise Gen5SnapshotBackfillError("GEN5_CHALLENGER_MANIFEST_INVALID")
            last = value
    if last is None:
        return rows, None, None
    snapshot_id = last.get("snapshot_id")
    blob_path = last.get("blob_path")
    ledger_sequence: int | None = None
    if isinstance(blob_path, str):
        blob = challenger_root / blob_path
        if blob.is_file() and not blob.is_symlink():
            value = json.loads(blob.read_text(encoding="utf-8"))
            sequence = value.get("profiled_ledger_sequence")
            if type(sequence) is int:
                ledger_sequence = sequence
    return rows, snapshot_id if isinstance(snapshot_id, str) else None, ledger_sequence


def _checkpoint_state(config: Gen5BackfillConfig) -> dict[str, Any]:
    checkpoint = _read_json_object(config.importer_checkpoint_path) or {}
    return {
        "completed_shards": checkpoint.get("completed_shards", 0),
        "next_after_sequence": checkpoint.get("next_after_sequence", 0),
        "completed": checkpoint.get("completed", False),
        "cumulative_imported_rows": checkpoint.get("cumulative_imported_rows"),
        "cumulative_duplicate_rows": checkpoint.get("cumulative_duplicate_rows"),
        "cumulative_rejected_rows": checkpoint.get("cumulative_rejected_rows"),
        "cumulative_rejections_by_reason": checkpoint.get("cumulative_rejections_by_reason"),
        "last_candidate_id": checkpoint.get("last_candidate_id"),
        "last_completed_sequence": checkpoint.get("last_completed_sequence"),
        "checkpoint_path": str(config.importer_checkpoint_path.resolve()),
    }


def _initial_status(
    config: Gen5BackfillConfig,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _read_json_object(config.status_path)
    if previous is not None:
        if previous.get("snapshot_id") != manifest.get("snapshot_id"):
            raise Gen5SnapshotBackfillError("GEN5_STATUS_SNAPSHOT_MISMATCH")
        status = previous
    else:
        status = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": manifest["snapshot_id"],
            "snapshot_manifest_sha256": manifest["manifest_sha256"],
            "training_observed_at": manifest["training_observed_at"],
            "started_at": _utc_now(),
            "completed_shards": 0,
            "next_after_sequence": 0,
            "imported_rows": 0,
            "duplicate_rows": 0,
            "rejected_rows": 0,
            "rejections_by_reason": {},
            "completed": False,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
    checkpoint = _checkpoint_state(config)
    if int(checkpoint["completed_shards"]) > int(status["completed_shards"]):
        required = (
            checkpoint["cumulative_imported_rows"],
            checkpoint["cumulative_duplicate_rows"],
            checkpoint["cumulative_rejected_rows"],
            checkpoint["cumulative_rejections_by_reason"],
        )
        if any(type(value) is not int for value in required[:3]) or not isinstance(
            required[3], dict
        ):
            raise Gen5SnapshotBackfillError("GEN5_CHECKPOINT_PROGRESS_EVIDENCE_MISSING")
        imported_rows, manifest_candidate_id, manifest_ledger_sequence = _manifest_tail(
            config.challenger_archive_root
        )
        status["completed_shards"] = checkpoint["completed_shards"]
        status["next_after_sequence"] = checkpoint["next_after_sequence"]
        status["imported_rows"] = imported_rows
        status["duplicate_rows"] = checkpoint["cumulative_duplicate_rows"]
        status["rejected_rows"] = checkpoint["cumulative_rejected_rows"]
        status["rejections_by_reason"] = checkpoint["cumulative_rejections_by_reason"]
        status["last_candidate_id"] = checkpoint["last_candidate_id"] or manifest_candidate_id
        status["last_ledger_sequence"] = (
            checkpoint["last_completed_sequence"] or manifest_ledger_sequence
        )
        status["completed"] = checkpoint["completed"] is True
        status["recovered_from_checkpoint"] = True
        _write_json_atomic(config.status_path, status)
    return status


def _merge_rejections(
    existing: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, int]:
    merged: dict[str, int] = {str(key): int(value) for key, value in existing.items()}
    for key, value in current.items():
        merged[str(key)] = merged.get(str(key), 0) + int(value)
    return dict(sorted(merged.items()))


def _terminal_receipt(
    *,
    config: Gen5BackfillConfig,
    manifest: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
    started_monotonic: float,
    exit_reason: str,
    exit_code: int,
    signal_number: int | None = None,
    exception: BaseException | None = None,
) -> dict[str, Any]:
    checkpoint = _checkpoint_state(config)
    receipt: dict[str, Any] = {
        "schema_version": TERMINAL_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "exit_reason": exit_reason,
        "exit_code": exit_code,
        "signal_number": signal_number,
        "exception_type": type(exception).__name__ if exception is not None else None,
        "exception_message": (str(exception)[:2000] if exception is not None else None),
        "last_completed_shard": checkpoint["completed_shards"],
        "last_completed_sequence": checkpoint["next_after_sequence"],
        "last_candidate_id": checkpoint["last_candidate_id"],
        "cumulative_imported_rows": checkpoint["cumulative_imported_rows"],
        "cumulative_duplicate_rows": checkpoint["cumulative_duplicate_rows"],
        "cumulative_rejected_rows": checkpoint["cumulative_rejected_rows"],
        "checkpoint_path": checkpoint["checkpoint_path"],
        "safe_resume_command": SAFE_RESUME_COMMAND,
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
        "snapshot_id": manifest.get("snapshot_id") if manifest else None,
        "status_completed": status.get("completed") if status else False,
        **_process_resources(),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    if exception is not None:
        trace = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        receipt["traceback_sha256"] = _sha256_bytes(trace.encode("utf-8"))
    return receipt


def _persist_terminal(config: Gen5BackfillConfig, receipt: Mapping[str, Any]) -> None:
    _append_jsonl_fsync(config.terminal_history_path, receipt)
    _write_json_atomic(config.terminal_receipt_path, receipt)
    print("GEN5_TERMINAL_RECEIPT", json.dumps(receipt, sort_keys=True), flush=True)


def run_snapshot_backfill(
    config: Gen5BackfillConfig,
    *,
    importer: Callable[..., dict[str, Any]] = (
        import_profiled_training_ledger_shards_to_challenger_archive_v1
    ),
) -> dict[str, Any]:
    """Freeze once and resume bounded shards until the frozen ledger is exhausted."""

    if type(config.shard_size) is not int or not 0 < config.shard_size <= 32:
        raise Gen5SnapshotBackfillError("GEN5_SHARD_SIZE_INVALID")
    _ensure_private_directory(config.state_root)
    lock_descriptor = os.open(config.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Gen5SnapshotBackfillError("GEN5_BACKFILL_ALREADY_RUNNING") from exc

        started_monotonic = time.monotonic()
        manifest: dict[str, Any] | None = None
        status: dict[str, Any] | None = None
        previous_handlers: dict[int, Any] = {}

        def observe_signal(signal_number: int, _frame: Any) -> None:
            raise _ObservedSignal(signal_number)

        for signal_number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous_handlers[signal_number] = signal.signal(signal_number, observe_signal)
        try:
            manifest = load_or_create_fixed_snapshot(config)
            status = _initial_status(config, manifest)
            _ensure_private_directory(config.challenger_archive_root)
            if not config.cost_store_root.resolve().is_dir():
                raise Gen5SnapshotBackfillError("GEN5_COST_STORE_MISSING")

            while True:
                ledger = DurableFeatureSnapshotLedger(config.snapshot_ledger_path)
                label_archive = DurableCanonical5mLabelArchive(config.snapshot_label_archive_path)
                result = importer(
                    ledger=ledger,
                    trusted_immutable_cost_store_root=config.cost_store_root.resolve(),
                    label_archive=label_archive,
                    challenger_archive_root=config.challenger_archive_root.resolve(),
                    checkpoint_path=config.importer_checkpoint_path.resolve(),
                    training_observed_at=str(manifest["training_observed_at"]),
                    shard_size=config.shard_size,
                    max_shards=1,
                    minimum_train_rows=MAX_IMPORT_THRESHOLD,
                    minimum_validation_rows=MAX_IMPORT_THRESHOLD,
                    minimum_holdout_rows=MAX_IMPORT_THRESHOLD,
                )
                del ledger, label_archive
                gc.collect()

                shard_reports = result.get("shards")
                if not isinstance(shard_reports, list):
                    raise Gen5SnapshotBackfillError("GEN5_IMPORTER_SHARDS_INVALID")
                if not shard_reports:
                    if result.get("completed") is True:
                        status["completed"] = True
                        status["completed_at"] = _utc_now()
                        _write_json_atomic(config.status_path, status)
                        break
                    raise Gen5SnapshotBackfillError("GEN5_IMPORTER_NO_PROGRESS")
                report = shard_reports[-1]
                if not isinstance(report, dict):
                    raise Gen5SnapshotBackfillError("GEN5_IMPORTER_REPORT_INVALID")
                checkpoint = _checkpoint_state(config)
                imported_rows, last_candidate_id, last_ledger_sequence = _manifest_tail(
                    config.challenger_archive_root
                )
                current_rejections = report.get("rejections_by_reason")
                if not isinstance(current_rejections, dict):
                    raise Gen5SnapshotBackfillError("GEN5_REJECTIONS_INVALID")
                status["generated_at"] = _utc_now()
                status["completed_shards"] = checkpoint["completed_shards"]
                status["next_after_sequence"] = checkpoint["next_after_sequence"]
                status["imported_rows"] = imported_rows
                status["duplicate_rows"] = int(
                    checkpoint["cumulative_duplicate_rows"]
                    if type(checkpoint["cumulative_duplicate_rows"]) is int
                    else int(status["duplicate_rows"]) + int(report.get("duplicate_rows", 0))
                )
                status["rejected_rows"] = int(
                    checkpoint["cumulative_rejected_rows"]
                    if type(checkpoint["cumulative_rejected_rows"]) is int
                    else int(status["rejected_rows"])
                    + sum(int(value) for value in current_rejections.values())
                )
                status["rejections_by_reason"] = (
                    checkpoint["cumulative_rejections_by_reason"]
                    if isinstance(checkpoint["cumulative_rejections_by_reason"], dict)
                    else _merge_rejections(status["rejections_by_reason"], current_rejections)
                )
                status["last_candidate_id"] = checkpoint["last_candidate_id"] or last_candidate_id
                status["last_ledger_sequence"] = (
                    checkpoint["last_completed_sequence"] or last_ledger_sequence
                )
                status["completed"] = checkpoint["completed"] is True
                status["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 6)
                status.update(_process_resources())
                progress = {
                    "schema_version": PROGRESS_SCHEMA_VERSION,
                    "snapshot_id": manifest["snapshot_id"],
                    "generated_at": status["generated_at"],
                    "completed_shards": status["completed_shards"],
                    "next_after_sequence": status["next_after_sequence"],
                    "imported_rows": status["imported_rows"],
                    "duplicate_rows": status["duplicate_rows"],
                    "rejected_rows": status["rejected_rows"],
                    "last_candidate_id": last_candidate_id,
                    "last_ledger_sequence": last_ledger_sequence,
                    "shard_report": report,
                    "elapsed_seconds": status["elapsed_seconds"],
                    "rss_peak_kib": status["rss_peak_kib"],
                    "open_file_descriptors": status["open_file_descriptors"],
                    "completed": status["completed"],
                    "paper_only": True,
                    "live_gate": "blocked_human_only",
                    "routes_to_live": False,
                    "places_real_order": False,
                    "exchange_action_taken": False,
                }
                _append_jsonl_fsync(config.progress_path, progress)
                _write_json_atomic(config.status_path, status)
                print("GEN5_SHARD", json.dumps(progress, sort_keys=True), flush=True)
                if status["completed"]:
                    status["completed_at"] = _utc_now()
                    _write_json_atomic(config.status_path, status)
                    break

            receipt = _terminal_receipt(
                config=config,
                manifest=manifest,
                status=status,
                started_monotonic=started_monotonic,
                exit_reason="COMPLETED",
                exit_code=0,
            )
            _persist_terminal(config, receipt)
            return status
        except _ObservedSignal as exc:
            receipt = _terminal_receipt(
                config=config,
                manifest=manifest,
                status=status,
                started_monotonic=started_monotonic,
                exit_reason="SIGNAL",
                exit_code=128 + exc.signal_number,
                signal_number=exc.signal_number,
                exception=exc,
            )
            _persist_terminal(config, receipt)
            raise SystemExit(128 + exc.signal_number) from None
        except Exception as exc:
            receipt = _terminal_receipt(
                config=config,
                manifest=manifest,
                status=status,
                started_monotonic=started_monotonic,
                exit_reason="EXCEPTION",
                exit_code=1,
                exception=exc,
            )
            _persist_terminal(config, receipt)
            raise
        finally:
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)
    finally:
        os.close(lock_descriptor)


__all__ = [
    "Gen5BackfillConfig",
    "Gen5SnapshotBackfillError",
    "load_or_create_fixed_snapshot",
    "run_snapshot_backfill",
    "sqlite_snapshot",
    "validate_existing_fixed_snapshot",
]
