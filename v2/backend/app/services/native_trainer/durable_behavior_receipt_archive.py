"""Durable lifecycle archive for exact paper behavior-policy receipts.

Redis remains a convenient lookup cache, but exact PPO evidence cannot depend on
Redis retention.  This archive stores the self-authenticating receipt as an
immutable, content-addressed blob and records paper/trainer lifecycle events in
an append-only per-receipt journal.  Nothing in this module authorizes live
execution.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARCHIVE_SCHEMA_VERSION = "v2_durable_behavior_receipt_archive_v1"
LIFECYCLE_EVENT_SCHEMA_VERSION = "v2_behavior_receipt_lifecycle_event_v1"
DEFAULT_ARCHIVE_REL = Path(
    ".local_data/v2_native_trainer/durable_behavior_receipt_archive"
)
RECEIPT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
UPDATE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")

EVENT_PUBLISHED = "PUBLISHED"
EVENT_ENTRY_ACCEPTED = "ENTRY_ACCEPTED"
EVENT_OUTCOME_FINALIZED = "OUTCOME_FINALIZED"
EVENT_TRAINER_CONSUMED = "TRAINER_CONSUMED"
EVENT_ORDER = (
    EVENT_PUBLISHED,
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_TRAINER_CONSUMED,
)
EVENT_SEMANTIC_TIME_FIELDS = {
    EVENT_PUBLISHED: ("decision_time",),
    EVENT_ENTRY_ACCEPTED: ("decision_time", "entry_time"),
    EVENT_OUTCOME_FINALIZED: ("outcome_available_at",),
    EVENT_TRAINER_CONSUMED: ("ledger_recorded_utc",),
}
DURABLE_RECEIPT_LINEAGE_FIELDS = (
    "behavior_policy_receipt_archive_schema_version",
    "behavior_policy_receipt_archive_write_success",
    "behavior_policy_receipt_archive_content_sha256",
    "behavior_policy_receipt_archive_blob_path",
    "behavior_policy_receipt_archive_published_event_hash",
)


class BehaviorReceiptArchiveError(ValueError):
    """Raised when durable receipt evidence is missing, corrupt, or conflicting."""


@dataclass(frozen=True)
class BehaviorReceiptArchiveWrite:
    receipt_hash: str
    archive_content_sha256: str
    blob_path: Path
    already_present: bool


@dataclass(frozen=True)
class BehaviorReceiptLifecycleWrite:
    receipt_hash: str
    event_type: str
    event_hash: str
    event_path: Path
    already_present: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def default_archive_root(repo_root: Path | None = None) -> Path:
    return (repo_root or _repo_root()) / DEFAULT_ARCHIVE_REL


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BehaviorReceiptArchiveError("NON_CANONICAL_JSON_PAYLOAD") from exc
    return encoded.encode("utf-8")


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _strict_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _validated_event_recorded_time(
    *,
    event_type: str,
    binding: Mapping[str, Any],
    recorded_at: Any,
) -> datetime:
    recorded_time = _strict_utc(recorded_at)
    if recorded_time is None:
        raise BehaviorReceiptArchiveError("LIFECYCLE_RECORDED_AT_INVALID")
    semantic_times = _validated_event_semantic_times(
        event_type=event_type,
        binding=binding,
    )
    if recorded_time < max(semantic_times.values()):
        raise BehaviorReceiptArchiveError(
            "LIFECYCLE_EVENT_RECORDED_AT_BEFORE_SEMANTIC_TIME"
        )
    return recorded_time


def _validated_event_semantic_times(
    *,
    event_type: str,
    binding: Mapping[str, Any],
) -> dict[str, datetime]:
    """Return strict UTC semantic clocks required by one lifecycle event."""

    semantic_times: dict[str, datetime] = {}
    for field in EVENT_SEMANTIC_TIME_FIELDS[event_type]:
        if field not in binding or binding.get(field) in (None, ""):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_TIME_MISSING"
            )
        parsed = _strict_utc(binding.get(field))
        if parsed is None:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_TIME_INVALID"
            )
        semantic_times[field] = parsed
    return semantic_times


def _validate_lifecycle_semantic_order(
    events_by_type: Mapping[str, Mapping[str, Any]],
) -> None:
    """Re-prove semantic clock identity and causal order for a journal."""

    times_by_type: dict[str, dict[str, datetime]] = {}
    for event_type in EVENT_ORDER:
        event = events_by_type.get(event_type)
        if event is None:
            continue
        binding = event.get("binding")
        if not isinstance(binding, Mapping):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_BINDING_INVALID")
        times_by_type[event_type] = _validated_event_semantic_times(
            event_type=event_type,
            binding=binding,
        )

    published = times_by_type.get(EVENT_PUBLISHED)
    entry = times_by_type.get(EVENT_ENTRY_ACCEPTED)
    outcome = times_by_type.get(EVENT_OUTCOME_FINALIZED)
    consumed = times_by_type.get(EVENT_TRAINER_CONSUMED)
    if published is not None and entry is not None:
        if entry["decision_time"] != published["decision_time"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_ENTRY_DECISION_TIME_BINDING_MISMATCH"
            )
        if entry["decision_time"] > entry["entry_time"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID"
            )
    if entry is not None and outcome is not None:
        if entry["entry_time"] > outcome["outcome_available_at"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID"
            )
    if outcome is not None and consumed is not None:
        if outcome["outcome_available_at"] > consumed["ledger_recorded_utc"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID"
            )


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    row = dict(receipt)
    supplied = str(row.pop("receipt_hash", ""))
    if not RECEIPT_HASH_RE.fullmatch(supplied):
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_INVALID")
    if canonical_sha256(row) != supplied:
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_CONTENT_MISMATCH")
    return supplied


def _blob_path(root: Path, receipt_hash: str) -> Path:
    return (
        root
        / "receipts"
        / receipt_hash[:2]
        / receipt_hash[2:4]
        / f"{receipt_hash}.json"
    )


def _event_dir(root: Path, receipt_hash: str) -> Path:
    return root / "lifecycle" / receipt_hash[:2] / receipt_hash


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_create_or_identical(path: Path, payload: Mapping[str, Any]) -> bool:
    """Atomically create ``path`` or prove its existing bytes are identical."""

    encoded = _canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise BehaviorReceiptArchiveError("ARCHIVE_EXISTING_READ_FAILED") from exc
        if existing != encoded:
            raise BehaviorReceiptArchiveError("ARCHIVE_IMMUTABLE_CONFLICT")
        return True
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            if path.read_bytes() != encoded:
                raise BehaviorReceiptArchiveError(
                    "ARCHIVE_IMMUTABLE_CONFLICT"
                ) from exc
            return True
        _fsync_dir(path.parent)
        return False
    except OSError as exc:
        raise BehaviorReceiptArchiveError("ARCHIVE_DURABLE_WRITE_FAILED") from exc
    finally:
        temporary.unlink(missing_ok=True)


def archive_behavior_receipt(
    receipt: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> BehaviorReceiptArchiveWrite:
    """Persist and verify an immutable exact behavior receipt."""

    receipt_hash = _receipt_hash(receipt)
    archive_root = root or default_archive_root()
    record_without_hash = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "receipt_hash": receipt_hash,
        "receipt": dict(receipt),
    }
    archive_hash = canonical_sha256(record_without_hash)
    record = {
        **record_without_hash,
        "archive_content_sha256": archive_hash,
    }
    blob_path = _blob_path(archive_root, receipt_hash)
    already_present = _write_json_create_or_identical(blob_path, record)
    loaded = load_behavior_receipt(receipt_hash, root=archive_root)
    if loaded != dict(receipt):
        raise BehaviorReceiptArchiveError("ARCHIVE_READ_AFTER_WRITE_MISMATCH")
    return BehaviorReceiptArchiveWrite(
        receipt_hash=receipt_hash,
        archive_content_sha256=archive_hash,
        blob_path=blob_path,
        already_present=already_present,
    )


def load_behavior_receipt(
    receipt_hash: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    value = str(receipt_hash or "")
    if not RECEIPT_HASH_RE.fullmatch(value):
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_INVALID")
    archive_root = root or default_archive_root()
    path = _blob_path(archive_root, value)
    if not path.is_file():
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_MISSING")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_UNREADABLE") from exc
    if not isinstance(record, dict):
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_RECORD_INVALID")
    supplied_archive_hash = str(record.pop("archive_content_sha256", ""))
    if (
        not RECEIPT_HASH_RE.fullmatch(supplied_archive_hash)
        or canonical_sha256(record) != supplied_archive_hash
        or record.get("schema_version") != ARCHIVE_SCHEMA_VERSION
        or record.get("receipt_hash") != value
        or not isinstance(record.get("receipt"), dict)
    ):
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_INTEGRITY_INVALID")
    receipt = dict(record["receipt"])
    if _receipt_hash(receipt) != value:
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_BINDING_INVALID")
    return receipt


def verify_archived_behavior_receipt(
    receipt: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    receipt_hash = _receipt_hash(receipt)
    archived = load_behavior_receipt(receipt_hash, root=root)
    if archived != dict(receipt):
        raise BehaviorReceiptArchiveError("ARCHIVED_RECEIPT_PAYLOAD_MISMATCH")
    return {
        "archive_verified": True,
        "receipt_hash": receipt_hash,
        "archive_content_sha256": canonical_sha256(
            {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "receipt_hash": receipt_hash,
                "receipt": archived,
            }
        ),
        "blob_path": str(_blob_path(root or default_archive_root(), receipt_hash)),
    }


def _event_files(root: Path, receipt_hash: str) -> list[Path]:
    directory = _event_dir(root, receipt_hash)
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def lifecycle_events(
    receipt_hash: Any,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    value = str(receipt_hash or "")
    if not RECEIPT_HASH_RE.fullmatch(value):
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_INVALID")
    archive_root = root or default_archive_root()
    events: list[dict[str, Any]] = []
    for path in _event_files(archive_root, value):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_UNREADABLE") from exc
        if not isinstance(row, dict):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_INVALID")
        supplied_hash = str(row.pop("event_hash", ""))
        if (
            not RECEIPT_HASH_RE.fullmatch(supplied_hash)
            or canonical_sha256(row) != supplied_hash
            or row.get("schema_version") != LIFECYCLE_EVENT_SCHEMA_VERSION
            or row.get("receipt_hash") != value
            or path.name != f"{supplied_hash}.json"
            or row.get("event_type") not in EVENT_ORDER
            or _strict_utc(row.get("recorded_at")) is None
            or not isinstance(row.get("binding"), Mapping)
            or row.get("paper_only") is not True
            or row.get("routes_to_live") is not False
            or row.get("places_real_order") is not False
        ):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_INTEGRITY_INVALID")
        row["event_hash"] = supplied_hash
        events.append(row)
    event_types = [str(row.get("event_type") or "") for row in events]
    if len(event_types) != len(set(event_types)):
        raise BehaviorReceiptArchiveError("LIFECYCLE_DUPLICATE_EVENT_TYPE")
    present_types = set(event_types)
    for event_type in event_types:
        prior_types = set(EVENT_ORDER[: EVENT_ORDER.index(event_type)])
        if event_type != EVENT_PUBLISHED and not prior_types.issubset(present_types):
            raise BehaviorReceiptArchiveError("LIFECYCLE_PREREQUISITE_MISSING")
    events_by_type = {
        str(event["event_type"]): event
        for event in events
    }
    _validate_lifecycle_semantic_order(events_by_type)
    previous_recorded_time: datetime | None = None
    for event_type in EVENT_ORDER:
        event = events_by_type.get(event_type)
        if event is None:
            continue
        binding = event.get("binding")
        if not isinstance(binding, Mapping):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_BINDING_INVALID")
        recorded_time = _validated_event_recorded_time(
            event_type=event_type,
            binding=binding,
            recorded_at=event.get("recorded_at"),
        )
        if (
            previous_recorded_time is not None
            and recorded_time < previous_recorded_time
        ):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_TEMPORAL_ORDER_INVALID"
            )
        previous_recorded_time = recorded_time
    return sorted(
        events,
        key=lambda item: (str(item.get("recorded_at")), item["event_hash"]),
    )


def _append_lifecycle_event_locked(
    *,
    receipt_hash: str,
    event_type: str,
    binding: Mapping[str, Any],
    root: Path | None = None,
    recorded_at: str | None = None,
) -> BehaviorReceiptLifecycleWrite:
    """Append one immutable event after proving its lifecycle prerequisites."""

    value = str(receipt_hash or "")
    if not RECEIPT_HASH_RE.fullmatch(value):
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_INVALID")
    if event_type not in EVENT_ORDER:
        raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_TYPE_INVALID")
    archive_root = root or default_archive_root()
    load_behavior_receipt(value, root=archive_root)
    existing = lifecycle_events(value, root=archive_root)
    existing_types = {str(row.get("event_type")) for row in existing}
    prior_types = set(EVENT_ORDER[: EVENT_ORDER.index(event_type)])
    if event_type != EVENT_PUBLISHED and not prior_types.issubset(existing_types):
        raise BehaviorReceiptArchiveError("LIFECYCLE_PREREQUISITE_MISSING")
    if event_type == EVENT_TRAINER_CONSUMED:
        update_key = str(binding.get("ppo_consumption_update_key") or "")
        if not UPDATE_KEY_RE.fullmatch(update_key):
            raise BehaviorReceiptArchiveError("TRAINER_CONSUMPTION_UPDATE_KEY_INVALID")
    identity_fields = {
        EVENT_PUBLISHED: ("prediction_id",),
        EVENT_ENTRY_ACCEPTED: ("paper_fill_id",),
        EVENT_OUTCOME_FINALIZED: (
            "finalized_outcome_id",
            "finalized_outcome_digest",
            "ppo_consumption_update_key",
        ),
        EVENT_TRAINER_CONSUMED: ("ppo_consumption_update_key",),
    }[event_type]
    requested_identity = tuple(str(binding.get(field) or "") for field in identity_fields)
    if any(not part for part in requested_identity):
        raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_IDENTITY_MISSING")
    timestamp = recorded_at or utc_now()
    recorded_time = _validated_event_recorded_time(
        event_type=event_type,
        binding=binding,
        recorded_at=timestamp,
    )
    for prior in existing:
        if prior.get("event_type") != event_type:
            continue
        prior_binding = prior.get("binding")
        if not isinstance(prior_binding, Mapping):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_BINDING_INVALID")
        prior_identity = tuple(
            str(prior_binding.get(field) or "") for field in identity_fields
        )
        if prior_identity != requested_identity or dict(prior_binding) != dict(binding):
            raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_BINDING_CONFLICT")
        return BehaviorReceiptLifecycleWrite(
            receipt_hash=value,
            event_type=event_type,
            event_hash=str(prior["event_hash"]),
            event_path=_event_dir(archive_root, value)
            / f"{prior['event_hash']}.json",
            already_present=True,
        )
    prospective_events = {
        str(event["event_type"]): event
        for event in existing
    }
    prospective_events[event_type] = {
        "event_type": event_type,
        "recorded_at": timestamp,
        "binding": dict(binding),
    }
    _validate_lifecycle_semantic_order(prospective_events)
    prior_recorded_times = [
        _strict_utc(event.get("recorded_at"))
        for event in existing
        if EVENT_ORDER.index(str(event.get("event_type")))
        < EVENT_ORDER.index(event_type)
    ]
    if any(
        prior_time is not None and recorded_time < prior_time
        for prior_time in prior_recorded_times
    ):
        raise BehaviorReceiptArchiveError("LIFECYCLE_EVENT_TEMPORAL_ORDER_INVALID")
    material = {
        "schema_version": LIFECYCLE_EVENT_SCHEMA_VERSION,
        "receipt_hash": value,
        "event_type": event_type,
        "recorded_at": timestamp,
        "binding": dict(binding),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    event_hash = canonical_sha256(material)
    row = {**material, "event_hash": event_hash}
    event_path = _event_dir(archive_root, value) / f"{event_hash}.json"
    already_present = _write_json_create_or_identical(event_path, row)
    # Read-after-write verification catches storage corruption before the caller
    # makes this receipt eligible for entry or training.
    if event_hash not in {
        str(event.get("event_hash"))
        for event in lifecycle_events(value, root=archive_root)
    }:
        raise BehaviorReceiptArchiveError("LIFECYCLE_READ_AFTER_WRITE_MISMATCH")
    return BehaviorReceiptLifecycleWrite(
        receipt_hash=value,
        event_type=event_type,
        event_hash=event_hash,
        event_path=event_path,
        already_present=already_present,
    )


def append_lifecycle_event(
    *,
    receipt_hash: str,
    event_type: str,
    binding: Mapping[str, Any],
    root: Path | None = None,
    recorded_at: str | None = None,
) -> BehaviorReceiptLifecycleWrite:
    """Serialize each receipt's read/check/write/readback lifecycle transition."""

    value = str(receipt_hash or "")
    if not RECEIPT_HASH_RE.fullmatch(value):
        raise BehaviorReceiptArchiveError("RECEIPT_HASH_INVALID")
    archive_root = root or default_archive_root()
    lock_path = archive_root / "locks" / value[:2] / f"{value}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            return _append_lifecycle_event_locked(
                receipt_hash=value,
                event_type=event_type,
                binding=binding,
                root=archive_root,
                recorded_at=recorded_at,
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def receipt_lifecycle_status(
    receipt_hash: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    events = lifecycle_events(receipt_hash, root=root)
    types = {str(row.get("event_type")) for row in events}
    event_bindings = {
        str(row["event_type"]): dict(row.get("binding") or {}) for row in events
    }
    highest = next(
        (event for event in reversed(EVENT_ORDER) if event in types),
        None,
    )
    return {
        "schema_version": "v2_behavior_receipt_lifecycle_status_v1",
        "receipt_hash": str(receipt_hash),
        "event_count": len(events),
        "event_types": sorted(types, key=EVENT_ORDER.index),
        "event_bindings": event_bindings,
        "highest_lifecycle_event": highest,
        "published_durable": EVENT_PUBLISHED in types,
        "entry_accepted_durable": EVENT_ENTRY_ACCEPTED in types,
        "outcome_finalized_durable": EVENT_OUTCOME_FINALIZED in types,
        "trainer_consumed_durable": EVENT_TRAINER_CONSUMED in types,
        "retention_required": EVENT_TRAINER_CONSUMED not in types,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
