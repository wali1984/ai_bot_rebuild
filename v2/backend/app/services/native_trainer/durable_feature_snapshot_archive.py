"""Durable feature snapshot archive for trusted native trainer replay.

Redis remains the fast current store. This archive is the disk source of truth
for trainer-eligible feature snapshots that may later be referenced by paper
positions, outcomes, feedback rows, or trusted replay samples.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


SCHEMA_VERSION = "durable_feature_snapshot_archive_record_v1"
STATUS_SCHEMA_VERSION = "durable_feature_snapshot_archive_status_v1"
DEFAULT_ARCHIVE_REL = Path(".local_data/v2_native_trainer/durable_feature_snapshot_archive")
DEFAULT_ROLLOVER_LIMIT_BYTES = 300 * 1024 * 1024 * 1024

REQUIRED_RECORD_FIELDS: tuple[str, ...] = (
    "snapshot_id",
    "symbol",
    "timeframe",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "mtf_snapshot_id",
    "features",
    "missing_mask",
    "stale_mask",
    "source_availability",
    "source_hashes",
    "schema_version",
    "content_sha256",
    "created_at",
)


class SnapshotArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveWriteResult:
    snapshot_id: str
    content_sha256: str
    blob_path: Path
    index_path: Path
    already_present: bool


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_archive_root(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / DEFAULT_ARCHIVE_REL


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _content_material(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(record).items() if key != "content_sha256"}


def content_sha256(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_content_material(record)).encode("utf-8")).hexdigest()


def _parse_utc(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_index_name(snapshot_id: str) -> str:
    digest = hashlib.sha256(snapshot_id.encode("utf-8")).hexdigest()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", snapshot_id)[:80].strip("._")
    return f"{slug or 'snapshot'}_{digest[:16]}.json"


def _blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / digest[:2] / digest[2:4] / f"{digest}.json"


def _index_path(root: Path, snapshot_id: str) -> Path:
    return root / "index" / "snapshot_id" / _safe_index_name(snapshot_id)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json(payload) + "\n")


def build_archive_record(
    *,
    snapshot_id: Any,
    symbol: Any,
    timeframe: Any,
    feature_cutoff: Any,
    decision_time: Any,
    available_at: Any,
    mtf_snapshot_id: Any,
    features: Mapping[str, Any],
    missing_mask: Mapping[str, Any] | Iterable[str] | None = None,
    stale_mask: Mapping[str, Any] | Iterable[str] | None = None,
    source_availability: Mapping[str, Any] | Iterable[Any] | None = None,
    source_hashes: Mapping[str, Any] | None = None,
    created_at: Any | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    feature_names = sorted(str(name) for name in features.keys())

    def mask(value: Mapping[str, Any] | Iterable[str] | None) -> dict[str, bool]:
        if isinstance(value, Mapping):
            return {str(name): bool(flag) for name, flag in value.items()}
        names = {str(name) for name in (value or [])}
        return {name: name in names for name in feature_names}

    if isinstance(source_availability, Mapping):
        availability: Any = {str(k): v for k, v in source_availability.items()}
    elif source_availability is None:
        availability = {}
    else:
        availability = list(source_availability)

    record = {
        "snapshot_id": str(snapshot_id),
        "feature_snapshot_id": str(snapshot_id),
        "symbol": str(symbol).upper(),
        "timeframe": str(timeframe),
        "feature_cutoff": feature_cutoff,
        "decision_time": decision_time,
        "available_at": available_at,
        "mtf_snapshot_id": str(mtf_snapshot_id),
        "features": dict(features),
        "missing_mask": mask(missing_mask),
        "stale_mask": mask(stale_mask),
        "source_availability": availability,
        "source_hashes": dict(source_hashes or {}),
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at or utc_now(),
    }
    if extra:
        for key, value in extra.items():
            if key not in record and key != "content_sha256":
                record[str(key)] = value
    record["content_sha256"] = content_sha256(record)
    return record


def build_archive_record_from_prediction_payload(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    snapshot_id = payload.get("feature_snapshot_id")
    if snapshot_id in (None, ""):
        return None
    replay_snapshot = payload.get("replay_snapshot") if isinstance(payload.get("replay_snapshot"), Mapping) else {}
    prediction = replay_snapshot.get("prediction") if isinstance(replay_snapshot.get("prediction"), Mapping) else {}
    if not prediction and isinstance(replay_snapshot.get("feature_snapshot"), Mapping):
        prediction = replay_snapshot
    feature_snapshot = (
        prediction.get("feature_snapshot")
        if isinstance(prediction.get("feature_snapshot"), Mapping)
        else payload.get("feature_snapshot")
        if isinstance(payload.get("feature_snapshot"), Mapping)
        else payload.get("entry_feature_snapshot")
    )
    feature_snapshot = feature_snapshot if isinstance(feature_snapshot, Mapping) else {}
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), Mapping) else {}
    if not features:
        return None
    feature_names = [str(name) for name in payload.get("feature_names") or features.keys()]
    missing_names = set(str(name) for name in payload.get("missing_feature_names") or payload.get("missing_feature_flags") or [])
    stale_names = set(str(name) for name in payload.get("stale_feature_names") or payload.get("stale_feature_flags") or [])
    missing_mask = {name: name in missing_names for name in feature_names}
    stale_mask = {name: name in stale_names for name in feature_names}
    candle_closed_confirmed = (
        feature_snapshot.get("candle_closed_confirmed")
        if "candle_closed_confirmed" in feature_snapshot
        else payload.get("candle_closed_confirmed")
    )
    latest_unclosed_kline_excluded = (
        feature_snapshot.get("latest_unclosed_kline_excluded")
        if "latest_unclosed_kline_excluded" in feature_snapshot
        else payload.get("latest_unclosed_kline_excluded")
    )

    def _preserve(field: str) -> Any:
        # Preserve an explicit upstream producer value only (feature_snapshot,
        # then payload); never derived from adjacent PIT fields.
        if field in feature_snapshot:
            return feature_snapshot.get(field)
        return payload.get(field)

    latest_unclosed_exclusion_method = _preserve("latest_unclosed_exclusion_method")
    latest_unclosed_exclusion_decision_time_ms = _preserve(
        "latest_unclosed_exclusion_decision_time_ms"
    )
    latest_closed_kline_close_time_ms = _preserve("latest_closed_kline_close_time_ms")
    # The archive writer is not the feature producer and must not manufacture
    # a producer admission claim from adjacent PIT fields.  Preserve an explicit
    # upstream boolean claim only; an absent or malformed claim remains absent
    # and is fail-closed by the trusted-replay loader.
    upstream_trainer_consumable = (
        feature_snapshot.get("trainer_consumable")
        if "trainer_consumable" in feature_snapshot
        else payload.get("trainer_consumable")
    )
    archive_extra = {
        "prediction_id": payload.get("prediction_id"),
        "signal_id": payload.get("signal_id"),
        "decision_id": payload.get("decision_id"),
        "model_version": payload.get("model_version"),
        "checkpoint_id": payload.get("checkpoint_id"),
        "candle_closed_confirmed": candle_closed_confirmed,
        "latest_unclosed_kline_excluded": latest_unclosed_kline_excluded,
        "latest_unclosed_exclusion_method": latest_unclosed_exclusion_method,
        "latest_unclosed_exclusion_decision_time_ms": latest_unclosed_exclusion_decision_time_ms,
        "latest_closed_kline_close_time_ms": latest_closed_kline_close_time_ms,
        "source": "trainer_prediction_payload",
    }
    if type(upstream_trainer_consumable) is bool:
        archive_extra["trainer_consumable"] = upstream_trainer_consumable
    return build_archive_record(
        snapshot_id=snapshot_id,
        symbol=payload.get("symbol"),
        timeframe=payload.get("timeframe"),
        feature_cutoff=payload.get("feature_cutoff") or feature_snapshot.get("feature_cutoff"),
        decision_time=payload.get("decision_time"),
        available_at=payload.get("available_at") or feature_snapshot.get("available_at"),
        mtf_snapshot_id=payload.get("mtf_snapshot_id") or feature_snapshot.get("mtf_snapshot_id"),
        features=features,
        missing_mask=missing_mask,
        stale_mask=stale_mask,
        source_availability=payload.get("source_availability_vector") or {},
        source_hashes=payload.get("source_hashes") or feature_snapshot.get("source_hashes") or {},
        created_at=payload.get("generated_utc") or payload.get("generated_at") or utc_now(),
        extra=archive_extra,
    )


def verify_record(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in REQUIRED_RECORD_FIELDS:
        value = record.get(field)
        if value in (None, "") or (field in {"features", "source_hashes"} and not isinstance(value, Mapping)):
            reasons.append(f"MISSING_{field.upper()}")
    if isinstance(record.get("features"), Mapping) and not record["features"]:
        reasons.append("FEATURES_EMPTY")
    expected_hash = record.get("content_sha256")
    if isinstance(expected_hash, str) and expected_hash:
        actual_hash = content_sha256(record)
        if actual_hash != expected_hash:
            reasons.append("CONTENT_SHA256_MISMATCH")
    feature_cutoff = _parse_utc(record.get("feature_cutoff"))
    decision_time = _parse_utc(record.get("decision_time"))
    available_at = _parse_utc(record.get("available_at"))
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_UNPARSEABLE")
    if decision_time is None:
        reasons.append("DECISION_TIME_UNPARSEABLE")
    if available_at is None:
        reasons.append("AVAILABLE_AT_UNPARSEABLE")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    return sorted(set(reasons))


def append_snapshot(
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
    update_checksum_manifest: bool = True,
) -> ArchiveWriteResult:
    archive_root = root or default_archive_root()
    item = dict(record)
    item.setdefault("schema_version", SCHEMA_VERSION)
    if not item.get("content_sha256"):
        item["content_sha256"] = content_sha256(item)
    reasons = verify_record(item)
    if reasons:
        raise SnapshotArchiveError(",".join(reasons))

    snapshot_id = str(item["snapshot_id"])
    digest = str(item["content_sha256"])
    blob_path = _blob_path(archive_root, digest)
    index_path = _index_path(archive_root, snapshot_id)
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        if existing.get("content_sha256") != digest:
            raise SnapshotArchiveError("SNAPSHOT_ID_CONTENT_HASH_CHANGED")
        return ArchiveWriteResult(snapshot_id, digest, blob_path, index_path, True)

    if not blob_path.exists():
        _write_json_atomic(blob_path, item)
    index_record = {
        "snapshot_id": snapshot_id,
        "content_sha256": digest,
        "blob_path": str(blob_path.relative_to(archive_root)),
        "created_at": item.get("created_at"),
        "symbol": item.get("symbol"),
        "timeframe": item.get("timeframe"),
    }
    _write_json_atomic(index_path, index_record)
    _append_jsonl(archive_root / "manifest.jsonl", index_record)
    if update_checksum_manifest:
        _write_checksum_manifest(archive_root)
    return ArchiveWriteResult(snapshot_id, digest, blob_path, index_path, False)


def _read_index(root: Path, snapshot_id: str) -> dict[str, Any] | None:
    path = _index_path(root, snapshot_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(snapshot_id: Any, *, root: Path | None = None, verify: bool = True) -> dict[str, Any] | None:
    archive_root = root or default_archive_root()
    if snapshot_id in (None, ""):
        return None
    index = _read_index(archive_root, str(snapshot_id))
    if not index:
        return None
    blob_path = archive_root / str(index.get("blob_path") or "")
    if not blob_path.exists():
        raise SnapshotArchiveError("ARCHIVE_BLOB_MISSING")
    record = json.loads(blob_path.read_text(encoding="utf-8"))
    if verify:
        reasons = verify_record(record)
        if reasons:
            raise SnapshotArchiveError(",".join(reasons))
    return record


def _iter_lines_reverse(path: Path, *, chunk_size: int = 1024 * 1024) -> Iterator[str]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        buffer = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            buffer = handle.read(read_size) + buffer
            lines = buffer.split(b"\n")
            buffer = lines[0]
            for raw_line in reversed(lines[1:]):
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    yield line
        if buffer.strip():
            yield buffer.decode("utf-8", errors="replace").strip()


def _iter_manifest_index_records(
    root: Path,
    *,
    newest_first: bool = False,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        return
    seen: set[str] = set()
    if newest_first:
        lines = _iter_lines_reverse(manifest)
        yield from _iter_manifest_lines(lines, manifest=manifest, limit=limit, seen=seen)
    else:
        with manifest.open("r", encoding="utf-8") as handle:
            yield from _iter_manifest_lines(handle, manifest=manifest, limit=limit, seen=seen)


def _iter_manifest_lines(
    lines: Iterable[str],
    *,
    manifest: Path,
    limit: int | None,
    seen: set[str],
) -> Iterator[dict[str, Any]]:
    count = 0
    for line in lines:
        if limit is not None and count >= int(limit):
            return
        try:
            record = json.loads(line)
        except Exception:
            continue
        snapshot_id = str(record.get("snapshot_id") or "")
        if not snapshot_id or snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        record["_manifest_path"] = str(manifest)
        record["_index_path"] = str(_index_path(manifest.parent, snapshot_id))
        count += 1
        yield record


def iter_index_records(
    root: Path | None = None,
    *,
    newest_first: bool = False,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    archive_root = root or default_archive_root()
    index_dir = archive_root / "index" / "snapshot_id"
    manifest = archive_root / "manifest.jsonl"
    if manifest.exists():
        yielded = False
        for record in _iter_manifest_index_records(archive_root, newest_first=newest_first, limit=limit):
            yielded = True
            yield record
        if yielded:
            return
    if not index_dir.exists():
        return
    paths = sorted(
        index_dir.glob("*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=bool(newest_first),
    )
    count = 0
    for path in paths:
        if limit is not None and count >= int(limit):
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        record["_index_path"] = str(path)
        count += 1
        yield record


def iter_snapshots(
    root: Path | None = None,
    *,
    limit: int | None = None,
    newest_first: bool = False,
) -> Iterator[dict[str, Any]]:
    count = 0
    archive_root = root or default_archive_root()
    for index in iter_index_records(archive_root, newest_first=newest_first, limit=limit):
        if limit is not None and count >= int(limit):
            return
        snapshot = load_snapshot(index.get("snapshot_id"), root=archive_root)
        if snapshot is None:
            continue
        count += 1
        yield snapshot


def iter_manifest_records_from_offset(
    root: Path | None = None,
    *,
    start_offset: int = 0,
    limit: int | None = None,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Walk manifest.jsonl oldest-first from a byte offset.

    Yields ``(next_byte_offset, record)`` so callers can persist a durable
    replay cursor and resume without rescanning the archive (F-0013: the
    trusted-replay training lane starved because a bounded newest-first scan
    can never reach labelable snapshots that are older than the outcome
    label horizon). Offsets are only valid for append-only manifests, which
    is how the archive writes them.
    """
    archive_root = root or default_archive_root()
    manifest = archive_root / "manifest.jsonl"
    if not manifest.exists():
        return
    count = 0
    with manifest.open("r", encoding="utf-8") as handle:
        try:
            handle.seek(max(0, int(start_offset)))
        except (OSError, ValueError):
            handle.seek(0)
        while True:
            if limit is not None and count >= int(limit):
                return
            line = handle.readline()
            if not line:
                return
            next_offset = handle.tell()
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict) or not record.get("snapshot_id"):
                continue
            count += 1
            yield next_offset, record


def iter_snapshots_from_offset(
    root: Path | None = None,
    *,
    start_offset: int = 0,
    limit: int | None = None,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(next_byte_offset, snapshot)`` oldest-first from a byte offset."""
    archive_root = root or default_archive_root()
    count = 0
    for next_offset, record in iter_manifest_records_from_offset(
        archive_root, start_offset=start_offset
    ):
        if limit is not None and count >= int(limit):
            return
        snapshot = load_snapshot(record.get("snapshot_id"), root=archive_root)
        if snapshot is None:
            continue
        count += 1
        yield next_offset, snapshot


def _archive_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def _write_checksum_manifest(root: Path) -> dict[str, Any]:
    records = []
    for index in iter_index_records(root):
        records.append(
            {
                "snapshot_id": index.get("snapshot_id"),
                "content_sha256": index.get("content_sha256"),
                "blob_path": index.get("blob_path"),
            }
        )
    payload = {
        "schema_version": "durable_feature_snapshot_archive_checksum_manifest_v1",
        "generated_utc": utc_now(),
        "record_count": len(records),
        "records": records,
        "manifest_sha256": hashlib.sha256(_canonical_json({"records": records}).encode("utf-8")).hexdigest(),
    }
    _write_json_atomic(root / "checksum_manifest.json", payload)
    return payload


def write_checksum_manifest(root: Path | None = None) -> dict[str, Any]:
    return _write_checksum_manifest(root or default_archive_root())


def referenced_snapshot_not_deleted(snapshot_id: Any, referenced_snapshot_ids: Iterable[Any]) -> bool:
    return str(snapshot_id) in {str(item) for item in referenced_snapshot_ids if item not in (None, "")}


def rollover_archive(
    *,
    root: Path | None = None,
    max_bytes: int = DEFAULT_ROLLOVER_LIMIT_BYTES,
    referenced_snapshot_ids: Iterable[Any] = (),
) -> dict[str, Any]:
    archive_root = root or default_archive_root()
    referenced = {str(item) for item in referenced_snapshot_ids if item not in (None, "")}
    before_bytes = _archive_size_bytes(archive_root)
    removed: list[str] = []
    pinned: list[str] = []
    if before_bytes > int(max_bytes):
        candidates = list(iter_index_records(archive_root))
        candidates.sort(key=lambda row: str(row.get("created_at") or ""))
        for index in candidates:
            if _archive_size_bytes(archive_root) <= int(max_bytes):
                break
            snapshot_id = str(index.get("snapshot_id") or "")
            if snapshot_id in referenced:
                pinned.append(snapshot_id)
                continue
            blob_path = archive_root / str(index.get("blob_path") or "")
            index_path = Path(str(index.get("_index_path")))
            try:
                blob_path.unlink(missing_ok=True)
                index_path.unlink(missing_ok=True)
                removed.append(snapshot_id)
            except OSError:
                continue
    _write_checksum_manifest(archive_root)
    return {
        "schema_version": "snapshot_archive_rollover_status_v1",
        "generated_utc": utc_now(),
        "archive_root": str(archive_root),
        "rollover_limit_bytes": int(max_bytes),
        "size_before_bytes": before_bytes,
        "size_after_bytes": _archive_size_bytes(archive_root),
        "removed_snapshot_ids": removed,
        "pinned_referenced_snapshot_ids": pinned,
        "referenced_snapshot_ids": sorted(referenced),
        "rollover_status": "ROLLOVER_NOT_REQUIRED"
        if before_bytes <= int(max_bytes)
        else "ROLLOVER_COMPLETED",
    }


def build_archive_status(*, root: Path | None = None) -> dict[str, Any]:
    archive_root = root or default_archive_root()
    index_records = list(iter_index_records(archive_root))
    corrupt = []
    missing = []
    for index in index_records:
        snapshot_id = index.get("snapshot_id")
        try:
            load_snapshot(snapshot_id, root=archive_root)
        except SnapshotArchiveError as exc:
            if "ARCHIVE_BLOB_MISSING" in str(exc):
                missing.append(snapshot_id)
            else:
                corrupt.append({"snapshot_id": snapshot_id, "reason": str(exc)})
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "archive_root": str(archive_root),
        "archive_active": True,
        "record_count": len(index_records),
        "archive_size_bytes": _archive_size_bytes(archive_root),
        "checksum_manifest_path": str(archive_root / "checksum_manifest.json"),
        "missing_payload_snapshot_ids": missing,
        "corrupt_snapshot_records": corrupt,
        "archive_integrity_status": "OK" if not missing and not corrupt else "CORRUPT_OR_MISSING_PAYLOADS",
    }


def build_reference_retention_status(
    *,
    root: Path | None = None,
    referenced_snapshot_ids: Iterable[Any] = (),
) -> dict[str, Any]:
    archive_root = root or default_archive_root()
    referenced = sorted({str(item) for item in referenced_snapshot_ids if item not in (None, "")})
    present = []
    missing = []
    for snapshot_id in referenced:
        try:
            if load_snapshot(snapshot_id, root=archive_root) is None:
                missing.append(snapshot_id)
            else:
                present.append(snapshot_id)
        except SnapshotArchiveError:
            missing.append(snapshot_id)
    return {
        "schema_version": "snapshot_reference_retention_status_v1",
        "generated_utc": utc_now(),
        "archive_root": str(archive_root),
        "referenced_snapshot_ids": referenced,
        "referenced_snapshot_count": len(referenced),
        "referenced_snapshot_present_count": len(present),
        "referenced_snapshot_missing_count": len(missing),
        "missing_referenced_snapshot_ids": missing,
        "referenced_snapshot_not_deleted": not missing,
    }


def publish_status_artifacts(
    *,
    output_dir: Path,
    root: Path | None = None,
    referenced_snapshot_ids: Iterable[Any] = (),
    rollover_status: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "durable_feature_snapshot_archive_status.json": build_archive_status(root=root),
        "snapshot_reference_retention_status.json": build_reference_retention_status(
            root=root,
            referenced_snapshot_ids=referenced_snapshot_ids,
        ),
        "snapshot_archive_rollover_status.json": dict(
            rollover_status
            or rollover_archive(root=root, referenced_snapshot_ids=referenced_snapshot_ids)
        ),
    }
    for name, payload in payloads.items():
        _write_json_atomic(output_dir / name, payload)
    return payloads
