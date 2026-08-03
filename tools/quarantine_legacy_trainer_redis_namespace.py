#!/usr/bin/env python3
"""Archive and remove only stable legacy trainer Redis records.

The default mode is a read-only dry run.  The apply path archives the entire
exact ``v2:trainer:hybrid_cuda:`` namespace, but deletes only known legacy keys
that are immortal in two observations.  Redis DUMP payloads are stored as
base64 so every supported value can be restored byte-for-byte without parsing
or normalising its logical representation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

NAMESPACE = b"v2:trainer:hybrid_cuda:"
SCAN_PATTERN = NAMESPACE + b"*"
SCHEMA_VERSION = "v2_legacy_trainer_redis_namespace_archive_v1"
SUPPORTED_REDIS_TYPES = frozenset({b"string", b"list", b"set", b"zset", b"hash", b"stream"})

PERSISTENT_TRAINER_UNIT = "ai-bot-v2-native-cuda-trainer-persistent.service"
CHECKPOINT_EVIDENCE_UNIT = "ai-bot-v2-trainer-checkpoint-evidence.service"
TRAINER_LIVE_LOOP_UNIT = "ai-bot-v2-trainer-training-live-loop.service"
TRAINING_GUARD_UNIT = "ai-bot-v2-native-ppo-masa-continuous-training-guard.service"
TRAINING_GUARD_TIMER = "ai-bot-v2-native-ppo-masa-continuous-training-guard.timer"
REQUIRED_INACTIVE_UNITS = (
    PERSISTENT_TRAINER_UNIT,
    CHECKPOINT_EVIDENCE_UNIT,
    TRAINER_LIVE_LOOP_UNIT,
    TRAINING_GUARD_UNIT,
    TRAINING_GUARD_TIMER,
)

# These are the legacy publisher's fixed records.  A positive TTL always wins
# over this allowlist and is preserved as a current-cycle record.
LEGACY_FIXED_KEYS = frozenset(
    NAMESPACE + suffix
    for suffix in (
        b"heartbeat",
        b"metrics",
        b"status",
        b"orchestrator_decision_preview",
        b"paper_block_reasons",
        b"paper_intent_preview",
        b"paper_ledger_preview",
        b"paper_positions_preview",
        b"paper_signal_lineage_preview",
        b"policy_backtest_report",
        b"risk_decision_preview",
    )
)
LEGACY_SIGNAL_PREFIX = NAMESPACE + b"signals:paper:"
ON_POLICY_RECEIPT_PREFIX = NAMESPACE + b"on_policy_receipt:"

APPLY_ACK = "--ack-legacy-immortal-trainer-redis-cleanup"
ROLLBACK_ACK = "--ack-legacy-immortal-trainer-redis-rollback"
DEFAULT_ARCHIVE_RELATIVE = Path(".local_models/quarantine/trainer_redis_namespace")
LOCAL_REDIS_TARGET = "redis://127.0.0.1:6379/0"

WRITER_INVENTORY = (
    {
        "unit": PERSISTENT_TRAINER_UNIT,
        "role": "direct namespace writer through hybrid trainer runtime/publisher",
        "must_be_loaded_and_inactive_for_apply": True,
    },
    {
        "unit": CHECKPOINT_EVIDENCE_UNIT,
        "role": "checkpoint-root observer; writes v2:trainer:checkpoint:* outside this prefix",
        "must_be_loaded_and_inactive_for_apply": True,
    },
    {
        "unit": TRAINER_LIVE_LOOP_UNIT,
        "role": "trainer adjunct; writes v2:trainer:training:* outside this prefix",
        "must_be_loaded_and_inactive_for_apply": True,
    },
    {
        "unit": TRAINING_GUARD_UNIT,
        "role": "trainer guard; can request trainer timer/service activation",
        "must_be_loaded_and_inactive_for_apply": True,
    },
    {
        "unit": TRAINING_GUARD_TIMER,
        "role": "trainer guard scheduler; must not activate the guard during maintenance",
        "must_be_loaded_and_inactive_for_apply": True,
    },
    {
        "unit": "ai-bot-v2-trade-management-paper-loop.service",
        "role": "receipt consumer/lifecycle writer; current on-policy Redis receipts are preserved",
        "must_be_loaded_and_inactive_for_apply": False,
    },
)

WRITER_PROCESS_MARKERS = (
    "v2_native_cuda_trainer_persistent_loop",
    "v2_native_rl_masa_ppo_cuda_trainer_loop",
    "run_trusted_prediction_publisher_once",
)


class QuarantineError(RuntimeError):
    """Fail-closed operator error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _as_bytes(value: Any, *, field: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    raise QuarantineError(f"UNSUPPORTED_{field.upper()}_REPRESENTATION:{type(value).__name__}")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str, *, field: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001 - convert malformed archive to fail-closed error
        raise QuarantineError(f"ARCHIVE_INVALID_BASE64:{field}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _display_key(key: bytes) -> str | None:
    try:
        return key.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None


def normalize_local_redis_target(value: str) -> str:
    """Accept only the loopback Redis DB governed by the local service gates."""

    try:
        parsed = urlsplit(value)
        port = parsed.port or 6379
    except (TypeError, ValueError) as exc:
        raise QuarantineError("REDIS_TARGET_INVALID") from exc
    path = parsed.path or "/0"
    if (
        parsed.scheme != "redis"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port != 6379
        or path not in {"", "/", "/0"}
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise QuarantineError("REDIS_TARGET_MUST_BE_LOCAL_DB_ZERO")
    return LOCAL_REDIS_TARGET


def _is_known_legacy_key(key: bytes) -> bool:
    return key in LEGACY_FIXED_KEYS or key.startswith(LEGACY_SIGNAL_PREFIX)


def _classification(key: bytes, pttl_ms: int, ttl_seconds: int | None = None) -> tuple[bool, str]:
    if key.startswith(ON_POLICY_RECEIPT_PREFIX):
        return False, "PRESERVE_ON_POLICY_BEHAVIOR_RECEIPT"
    if pttl_ms >= 0:
        return False, "PRESERVE_EXPIRING_CURRENT_RECORD"
    if pttl_ms != -1:
        raise QuarantineError(f"KEY_DISAPPEARED_DURING_SCAN:{_b64(key)}")
    if ttl_seconds is not None and ttl_seconds != -1:
        raise QuarantineError(f"IMMORTAL_TTL_OBSERVATION_INCONSISTENT:{_b64(key)}")
    if _is_known_legacy_key(key):
        return True, "CLEANUP_KNOWN_LEGACY_IMMORTAL_RECORD"
    return False, "PRESERVE_UNCLASSIFIED_IMMORTAL_RECORD"


@dataclass(frozen=True)
class NamespaceSnapshot:
    captured_at: str
    redis_server_epoch_seconds: int | None
    redis_server_microseconds: int | None
    records: tuple[dict[str, Any], ...]
    inventory_digest: str

    @property
    def candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(row for row in self.records if row["cleanup_eligible"] is True)


def _server_time(client: Any) -> tuple[int | None, int | None]:
    try:
        observed = client.time()
    except Exception:  # noqa: BLE001 - server TIME is provenance, Redis reads remain authoritative
        return None, None
    if isinstance(observed, (tuple, list)) and len(observed) == 2:
        return int(observed[0]), int(observed[1])
    return None, None


def capture_namespace(client: Any) -> NamespaceSnapshot:
    """Capture one lossless exact-prefix inventory using Redis DUMP payloads."""

    captured_at = _utc_now()
    server_seconds, server_microseconds = _server_time(client)
    discovered: dict[bytes, None] = {}
    try:
        iterator = client.scan_iter(match=SCAN_PATTERN, count=500)
        for raw_key in iterator:
            key = _as_bytes(raw_key, field="key")
            if not key.startswith(NAMESPACE):
                raise QuarantineError(f"SCAN_RETURNED_OUT_OF_PREFIX_KEY:{_b64(key)}")
            discovered[key] = None
    except QuarantineError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise QuarantineError(f"REDIS_SCAN_FAILED:{type(exc).__name__}") from exc

    records: list[dict[str, Any]] = []
    for key in sorted(discovered):
        try:
            redis_type = _as_bytes(client.type(key), field="redis_type").lower()
            dump = client.dump(key)
            pttl_ms = int(client.pttl(key))
            ttl_seconds = int(client.ttl(key))
        except QuarantineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QuarantineError(
                f"REDIS_READ_FAILED:{_b64(key)}:{type(exc).__name__}"
            ) from exc
        if redis_type == b"none" or dump is None or pttl_ms == -2 or ttl_seconds == -2:
            raise QuarantineError(f"KEY_DISAPPEARED_DURING_SCAN:{_b64(key)}")
        if redis_type not in SUPPORTED_REDIS_TYPES:
            display = _display_key(key) or _b64(key)
            raise QuarantineError(
                f"UNSUPPORTED_REDIS_TYPE:{display}:{redis_type.decode('ascii', errors='replace')}"
            )
        dump_bytes = _as_bytes(dump, field="redis_dump")
        eligible, reason = _classification(key, pttl_ms, ttl_seconds)
        records.append(
            {
                "key_b64": _b64(key),
                "key_utf8": _display_key(key),
                "redis_type": redis_type.decode("ascii"),
                "redis_dump_rdb_b64": _b64(dump_bytes),
                "content_sha256": _sha256(dump_bytes),
                "pttl_ms": pttl_ms,
                "ttl_seconds": ttl_seconds,
                "captured_at": captured_at,
                "cleanup_eligible": eligible,
                "cleanup_classification": reason,
            }
        )
    digest = _sha256(_canonical_bytes(records))
    return NamespaceSnapshot(
        captured_at=captured_at,
        redis_server_epoch_seconds=server_seconds,
        redis_server_microseconds=server_microseconds,
        records=tuple(records),
        inventory_digest=digest,
    )


def _record_by_key(snapshot: NamespaceSnapshot) -> dict[str, dict[str, Any]]:
    return {str(row["key_b64"]): row for row in snapshot.records}


def _candidate_material(snapshot: NamespaceSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "key_b64": row["key_b64"],
            "redis_type": row["redis_type"],
            "redis_dump_rdb_b64": row["redis_dump_rdb_b64"],
            "content_sha256": row["content_sha256"],
            "pttl_ms": row["pttl_ms"],
            "ttl_seconds": row["ttl_seconds"],
        }
        for row in snapshot.candidates
    ]


def candidate_digest(snapshot: NamespaceSnapshot) -> str:
    return _sha256(_canonical_bytes(_candidate_material(snapshot)))


def assert_candidate_stability(first: NamespaceSnapshot, second: NamespaceSnapshot) -> None:
    if _candidate_material(first) != _candidate_material(second):
        raise QuarantineError("LEGACY_IMMORTAL_CANDIDATE_SET_CHANGED_BETWEEN_SCANS")


def namespace_drift(first: NamespaceSnapshot, second: NamespaceSnapshot) -> dict[str, Any]:
    """Report noncandidate drift without treating current expiring keys as stale."""

    first_rows = _record_by_key(first)
    second_rows = _record_by_key(second)
    first_keys = set(first_rows)
    second_keys = set(second_rows)
    changed = sorted(
        key
        for key in first_keys & second_keys
        if (
            first_rows[key]["redis_type"],
            first_rows[key]["content_sha256"],
            first_rows[key]["cleanup_eligible"],
        )
        != (
            second_rows[key]["redis_type"],
            second_rows[key]["content_sha256"],
            second_rows[key]["cleanup_eligible"],
        )
    )
    return {
        "added_key_b64": sorted(second_keys - first_keys),
        "removed_key_b64": sorted(first_keys - second_keys),
        "content_type_or_classification_changed_key_b64": changed,
        "positive_ttl_decay_ignored": True,
    }


def observe_required_services() -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for unit in REQUIRED_INACTIVE_UNITS:
        try:
            result = subprocess.run(  # noqa: S603 - fixed systemctl argv, no shell
                [
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=LoadState",
                    "--property=ActiveState",
                    "--no-pager",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            observations.append(
                {
                    "unit": unit,
                    "load_state": None,
                    "active_state": None,
                    "safe": False,
                    "query_error": type(exc).__name__,
                }
            )
            continue
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                name, value = line.split("=", 1)
                fields[name] = value
        load_state = fields.get("LoadState")
        active_state = fields.get("ActiveState")
        observations.append(
            {
                "unit": unit,
                "load_state": load_state,
                "active_state": active_state,
                "safe": bool(
                    result.returncode == 0
                    and load_state == "loaded"
                    and active_state == "inactive"
                ),
                "query_error": None if result.returncode == 0 else f"exit_{result.returncode}",
            }
        )
    return observations


def observe_writer_processes() -> list[dict[str, Any]]:
    """Find un-gated manual trainer writers without shelling out to ps/pgrep."""

    matches: list[dict[str, Any]] = []
    proc = Path("/proc")
    own_pid = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        command = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        if not command:
            continue
        markers = [marker for marker in WRITER_PROCESS_MARKERS if marker in command]
        if markers:
            matches.append(
                {
                    "pid": int(entry.name),
                    "matched_markers": sorted(markers),
                    "command": command,
                }
            )
    return sorted(matches, key=lambda row: int(row["pid"]))


def service_gate_safe(observations: Sequence[Mapping[str, Any]]) -> bool:
    return len(observations) == len(REQUIRED_INACTIVE_UNITS) and all(
        row.get("safe") is True for row in observations
    )


def build_archive_payload(
    *,
    first: NamespaceSnapshot,
    second: NamespaceSnapshot,
    first_services: Sequence[Mapping[str, Any]],
    second_services: Sequence[Mapping[str, Any]],
    first_writer_processes: Sequence[Mapping[str, Any]],
    second_writer_processes: Sequence[Mapping[str, Any]],
    redis_target: str = LOCAL_REDIS_TARGET,
) -> dict[str, Any]:
    assert_candidate_stability(first, second)
    normalized_redis_target = normalize_local_redis_target(redis_target)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "namespace_utf8": NAMESPACE.decode("ascii"),
        "namespace_b64": _b64(NAMESPACE),
        "value_encoding": "base64_of_redis_DUMP_RDB_payload_lossless_for_RESTORE",
        "redis_target_contract": {
            "normalized_url": normalized_redis_target,
            "network_scope": "loopback_only",
            "database_index": 0,
            "tcp_port": 6379,
        },
        "selection_contract": {
            "archive_scope": "EVERY_SUPPORTED_KEY_IN_EXACT_PREFIX_SECOND_SCAN",
            "cleanup_scope": "KNOWN_LEGACY_KEY_AND_PTTL_EXACTLY_MINUS_ONE_IN_BOTH_SCANS",
            "positive_ttl_keys_preserved": True,
            "on_policy_behavior_receipts_preserved_even_when_immortal": True,
            "unclassified_immortal_keys_preserved": True,
        },
        "writer_inventory": list(WRITER_INVENTORY),
        "service_gate_observation_first": list(first_services),
        "service_gate_observation_second": list(second_services),
        "manual_writer_processes_first": list(first_writer_processes),
        "manual_writer_processes_second": list(second_writer_processes),
        "first_scan": {
            "captured_at": first.captured_at,
            "redis_server_epoch_seconds": first.redis_server_epoch_seconds,
            "redis_server_microseconds": first.redis_server_microseconds,
            "key_count": len(first.records),
            "inventory_digest": first.inventory_digest,
            "cleanup_candidate_count": len(first.candidates),
            "cleanup_candidate_digest": candidate_digest(first),
        },
        "second_scan": {
            "captured_at": second.captured_at,
            "redis_server_epoch_seconds": second.redis_server_epoch_seconds,
            "redis_server_microseconds": second.redis_server_microseconds,
            "key_count": len(second.records),
            "inventory_digest": second.inventory_digest,
            "cleanup_candidate_count": len(second.candidates),
            "cleanup_candidate_digest": candidate_digest(second),
        },
        "noncandidate_namespace_drift": namespace_drift(first, second),
        "inventory": list(second.records),
        "inventory_digest": second.inventory_digest,
        "cleanup_candidates": _candidate_material(second),
        "cleanup_candidate_digest": candidate_digest(second),
        "rollback_contract": "RESTORE_ONLY_CLEANUP_CANDIDATES_WITH_TTL_ZERO_AND_NO_OVERWRITE",
    }
    payload["archive_payload_sha256"] = _sha256(_canonical_bytes(payload))
    return payload


def _assert_under_repo(path: Path, repo_root: Path) -> Path:
    resolved_repo = repo_root.expanduser().resolve(strict=True)
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    resolved = Path(os.path.abspath(expanded))
    try:
        relative = resolved.relative_to(resolved_repo)
    except ValueError as exc:
        raise QuarantineError("ARCHIVE_PATH_MUST_BE_INSIDE_REPOSITORY") from exc
    cursor = resolved_repo
    for part in relative.parts:
        cursor /= part
        if cursor.exists() and cursor.is_symlink():
            raise QuarantineError("ARCHIVE_PATH_MUST_NOT_CONTAIN_SYMLINK")
    return resolved


def _assert_in_archive_directory(path: Path, repo_root: Path) -> Path:
    destination = _assert_under_repo(path, repo_root)
    expected_parent = Path(
        os.path.abspath(repo_root.expanduser().resolve(strict=True) / DEFAULT_ARCHIVE_RELATIVE)
    )
    if destination.parent != expected_parent:
        raise QuarantineError("ARCHIVE_PATH_MUST_USE_DEDICATED_QUARANTINE_DIRECTORY")
    return destination


def default_archive_path(repo_root: Path, *, generated_at: str) -> Path:
    timestamp = generated_at.replace("-", "").replace(":", "").replace(".", "")
    return repo_root / DEFAULT_ARCHIVE_RELATIVE / f"hybrid_cuda_legacy_{timestamp}.json"


def atomic_write_protected_json(path: Path, payload: Mapping[str, Any], repo_root: Path) -> None:
    destination = _assert_in_archive_directory(path, repo_root)
    parent = destination.parent
    if parent.exists() and parent.is_symlink():
        raise QuarantineError("ARCHIVE_DIRECTORY_MUST_NOT_BE_SYMLINK")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise QuarantineError("ARCHIVE_DIRECTORY_NOT_SECURE_DIRECTORY")
    os.chmod(parent, 0o700)
    if destination.exists() or destination.is_symlink():
        raise QuarantineError("ARCHIVE_DESTINATION_ALREADY_EXISTS")
    temporary = parent / f".{destination.name}.tmp.{os.getpid()}"
    body = _canonical_bytes(payload) + b"\n"
    fd: int | None = None
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def validate_archive_payload(
    payload: Mapping[str, Any], *, redis_target: str = LOCAL_REDIS_TARGET
) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QuarantineError("ARCHIVE_SCHEMA_UNSUPPORTED")
    if payload.get("namespace_b64") != _b64(NAMESPACE):
        raise QuarantineError("ARCHIVE_NAMESPACE_MISMATCH")
    if payload.get("namespace_utf8") != NAMESPACE.decode("ascii"):
        raise QuarantineError("ARCHIVE_NAMESPACE_DISPLAY_MISMATCH")
    normalized_redis_target = normalize_local_redis_target(redis_target)
    if payload.get("redis_target_contract") != {
        "normalized_url": normalized_redis_target,
        "network_scope": "loopback_only",
        "database_index": 0,
        "tcp_port": 6379,
    }:
        raise QuarantineError("ARCHIVE_REDIS_TARGET_MISMATCH")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        raise QuarantineError("ARCHIVE_GENERATED_AT_MISSING")
    expected_archive_digest = payload.get("archive_payload_sha256")
    material = dict(payload)
    material.pop("archive_payload_sha256", None)
    if expected_archive_digest != _sha256(_canonical_bytes(material)):
        raise QuarantineError("ARCHIVE_PAYLOAD_DIGEST_MISMATCH")
    inventory = payload.get("inventory")
    candidates = payload.get("cleanup_candidates")
    if not isinstance(inventory, list) or not isinstance(candidates, list):
        raise QuarantineError("ARCHIVE_INVENTORY_SHAPE_INVALID")
    if payload.get("inventory_digest") != _sha256(_canonical_bytes(inventory)):
        raise QuarantineError("ARCHIVE_INVENTORY_DIGEST_MISMATCH")
    if payload.get("cleanup_candidate_digest") != _sha256(_canonical_bytes(candidates)):
        raise QuarantineError("ARCHIVE_CANDIDATE_DIGEST_MISMATCH")
    inventory_by_key = {row.get("key_b64"): row for row in inventory if isinstance(row, dict)}
    if len(inventory_by_key) != len(inventory):
        raise QuarantineError("ARCHIVE_INVENTORY_DUPLICATE_OR_INVALID_KEY")
    expected_candidates: list[dict[str, Any]] = []
    for row in inventory:
        if not isinstance(row, dict):
            raise QuarantineError("ARCHIVE_INVENTORY_ROW_INVALID")
        key = _unb64(str(row.get("key_b64") or ""), field="inventory_key")
        dump = _unb64(str(row.get("redis_dump_rdb_b64") or ""), field="inventory_dump")
        if not key.startswith(NAMESPACE):
            raise QuarantineError("ARCHIVE_INVENTORY_KEY_OUTSIDE_PREFIX")
        redis_type = str(row.get("redis_type") or "").encode("ascii", errors="replace")
        if redis_type not in SUPPORTED_REDIS_TYPES:
            raise QuarantineError("ARCHIVE_INVENTORY_REDIS_TYPE_UNSUPPORTED")
        if row.get("content_sha256") != _sha256(dump):
            raise QuarantineError("ARCHIVE_INVENTORY_CONTENT_DIGEST_MISMATCH")
        try:
            pttl_ms = int(row["pttl_ms"])
            int(row["ttl_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QuarantineError("ARCHIVE_INVENTORY_TTL_INVALID") from exc
        if not isinstance(row.get("captured_at"), str) or not row.get("captured_at"):
            raise QuarantineError("ARCHIVE_INVENTORY_CAPTURED_AT_MISSING")
        expected_eligible, expected_classification = _classification(
            key,
            pttl_ms,
            int(row["ttl_seconds"]),
        )
        if (
            row.get("cleanup_eligible") is not expected_eligible
            or row.get("cleanup_classification") != expected_classification
        ):
            raise QuarantineError("ARCHIVE_INVENTORY_CLASSIFICATION_INVALID")
        if expected_eligible:
            expected_candidates.append(
                {
                    "key_b64": row["key_b64"],
                    "redis_type": row["redis_type"],
                    "redis_dump_rdb_b64": row["redis_dump_rdb_b64"],
                    "content_sha256": row["content_sha256"],
                    "pttl_ms": row["pttl_ms"],
                    "ttl_seconds": row["ttl_seconds"],
                }
            )
    if candidates != expected_candidates:
        raise QuarantineError("ARCHIVE_CANDIDATE_SET_NOT_EXACT_INVENTORY_SUBSET")
    for row in candidates:
        if not isinstance(row, dict):
            raise QuarantineError("ARCHIVE_CANDIDATE_SHAPE_INVALID")
        key = _unb64(str(row.get("key_b64") or ""), field="candidate_key")
        dump = _unb64(str(row.get("redis_dump_rdb_b64") or ""), field="candidate_dump")
        if not key.startswith(NAMESPACE) or not _is_known_legacy_key(key):
            raise QuarantineError("ARCHIVE_CANDIDATE_OUTSIDE_LEGACY_ALLOWLIST")
        if key.startswith(ON_POLICY_RECEIPT_PREFIX):
            raise QuarantineError("ARCHIVE_CANDIDATE_ON_POLICY_RECEIPT_FORBIDDEN")
        if row.get("pttl_ms") != -1 or row.get("ttl_seconds") != -1:
            raise QuarantineError("ARCHIVE_CANDIDATE_NOT_IMMORTAL")
        if row.get("content_sha256") != _sha256(dump):
            raise QuarantineError("ARCHIVE_CANDIDATE_CONTENT_DIGEST_MISMATCH")
        archived = inventory_by_key.get(row.get("key_b64"))
        if not isinstance(archived, dict) or any(
            row.get(field) != archived.get(field)
            for field in (
                "redis_type",
                "redis_dump_rdb_b64",
                "content_sha256",
                "pttl_ms",
                "ttl_seconds",
            )
        ):
            raise QuarantineError("ARCHIVE_CANDIDATE_NOT_BOUND_TO_INVENTORY")


def read_and_validate_archive(
    path: Path,
    repo_root: Path,
    *,
    redis_target: str = LOCAL_REDIS_TARGET,
) -> dict[str, Any]:
    archive_path = _assert_in_archive_directory(path, repo_root)
    if not archive_path.exists() or archive_path.is_symlink() or not archive_path.is_file():
        raise QuarantineError("ARCHIVE_MUST_BE_REGULAR_NON_SYMLINK_FILE")
    if archive_path.stat().st_uid != os.getuid():
        raise QuarantineError("ARCHIVE_MUST_BE_OWNED_BY_CURRENT_USER")
    if archive_path.stat().st_mode & 0o077:
        raise QuarantineError("ARCHIVE_PERMISSIONS_MUST_BE_0600_OR_STRICTER")
    try:
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuarantineError("ARCHIVE_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise QuarantineError("ARCHIVE_ROOT_MUST_BE_OBJECT")
    validate_archive_payload(payload, redis_target=redis_target)
    return payload


def write_and_validate_archive(
    path: Path,
    payload: Mapping[str, Any],
    repo_root: Path,
    *,
    redis_target: str = LOCAL_REDIS_TARGET,
) -> dict[str, Any]:
    """Persist, reopen, and byte-material-validate an archive before deletion."""

    atomic_write_protected_json(path, payload, repo_root)
    persisted = read_and_validate_archive(path, repo_root, redis_target=redis_target)
    if _canonical_bytes(persisted) != _canonical_bytes(payload):
        raise QuarantineError("ARCHIVE_READBACK_MATERIAL_MISMATCH")
    return persisted


def _watch_error(exc: BaseException) -> bool:
    return exc.__class__.__name__ == "WatchError"


def atomic_delete_candidates(client: Any, candidates: Sequence[Mapping[str, Any]]) -> int:
    if not candidates:
        raise QuarantineError("NO_STABLE_LEGACY_IMMORTAL_KEYS_TO_DELETE")
    keys = [_unb64(str(row["key_b64"]), field="candidate_key") for row in candidates]
    pipe = client.pipeline(transaction=True)
    try:
        pipe.watch(*keys)
        for key, expected in zip(keys, candidates, strict=True):
            observed_type = _as_bytes(pipe.type(key), field="redis_type").decode("ascii").lower()
            observed_dump_raw = pipe.dump(key)
            observed_pttl = int(pipe.pttl(key))
            observed_ttl = int(pipe.ttl(key))
            observed_dump = (
                _as_bytes(observed_dump_raw, field="redis_dump")
                if observed_dump_raw is not None
                else None
            )
            expected_dump = _unb64(str(expected["redis_dump_rdb_b64"]), field="candidate_dump")
            if (
                observed_type != expected.get("redis_type")
                or observed_dump != expected_dump
                or observed_pttl != -1
                or observed_ttl != -1
            ):
                raise QuarantineError(
                    f"COMPARE_BEFORE_DELETE_MISMATCH:{_b64(key)}"
                )
        pipe.multi()
        pipe.delete(*keys)
        responses = pipe.execute()
    except QuarantineError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _watch_error(exc):
            raise QuarantineError("COMPARE_BEFORE_DELETE_WATCH_CONFLICT") from exc
        raise QuarantineError(f"ATOMIC_DELETE_FAILED:{type(exc).__name__}") from exc
    finally:
        try:
            pipe.reset()
        except Exception:  # noqa: BLE001
            pass
    deleted = int(responses[0]) if responses else 0
    if deleted != len(keys):
        raise QuarantineError(f"ATOMIC_DELETE_COUNT_MISMATCH:{deleted}:{len(keys)}")
    try:
        still_present = [key for key in keys if int(client.exists(key)) != 0]
    except Exception as exc:  # noqa: BLE001 - deletion may have committed; report ambiguity
        raise QuarantineError("DELETE_POST_EXEC_VERIFICATION_UNAVAILABLE") from exc
    if still_present:
        raise QuarantineError(f"DELETE_VERIFICATION_FAILED:{len(still_present)}")
    return deleted


def atomic_restore_candidates(client: Any, candidates: Sequence[Mapping[str, Any]]) -> int:
    if not candidates:
        raise QuarantineError("ARCHIVE_HAS_NO_CLEANUP_CANDIDATES")
    keys = [_unb64(str(row["key_b64"]), field="candidate_key") for row in candidates]
    pipe = client.pipeline(transaction=True)
    try:
        pipe.watch(*keys)
        collisions = [key for key in keys if int(pipe.exists(key)) != 0]
        if collisions:
            raise QuarantineError(f"ROLLBACK_REFUSES_EXISTING_KEYS:{len(collisions)}")
        pipe.multi()
        for key, row in zip(keys, candidates, strict=True):
            dump = _unb64(str(row["redis_dump_rdb_b64"]), field="candidate_dump")
            pipe.restore(key, 0, dump, replace=False)
        responses = pipe.execute()
    except QuarantineError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _watch_error(exc):
            raise QuarantineError("ROLLBACK_WATCH_CONFLICT") from exc
        raise QuarantineError(f"ATOMIC_ROLLBACK_FAILED:{type(exc).__name__}") from exc
    finally:
        try:
            pipe.reset()
        except Exception:  # noqa: BLE001
            pass
    if len(responses) != len(keys) or any(response not in (b"OK", "OK", True) for response in responses):
        raise QuarantineError("ROLLBACK_RESPONSE_INVALID")
    for key, row in zip(keys, candidates, strict=True):
        observed_dump = client.dump(key)
        if (
            observed_dump is None
            or _as_bytes(client.type(key), field="redis_type").decode("ascii").lower()
            != row.get("redis_type")
            or _as_bytes(observed_dump, field="redis_dump")
            != _unb64(str(row["redis_dump_rdb_b64"]), field="candidate_dump")
            or int(client.pttl(key)) != -1
        ):
            raise QuarantineError(f"ROLLBACK_VERIFICATION_FAILED:{_b64(key)}")
    return len(keys)


def _connect_redis(redis_url: str) -> Any:
    normalized_redis_target = normalize_local_redis_target(redis_url)
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise QuarantineError("REDIS_PY_NOT_INSTALLED") from exc
    try:
        client = redis.Redis.from_url(
            normalized_redis_target,
            decode_responses=False,
            socket_connect_timeout=3.0,
            socket_timeout=10.0,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001
        raise QuarantineError(f"REDIS_CONNECTION_FAILED:{type(exc).__name__}") from exc
    return client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quarantine_legacy_trainer_redis_namespace",
        description=(
            "Dry-run by default. Archive the exact hybrid trainer namespace and "
            "delete only stable allowlisted immortal legacy records."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--redis-url", default=LOCAL_REDIS_TARGET)
    parser.add_argument("--stability-wait-ms", type=int, default=250)
    parser.add_argument("--archive-file", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(APPLY_ACK, action="store_true", dest="apply_ack")
    parser.add_argument("--rollback", type=Path, default=None, metavar="ARCHIVE_FILE")
    parser.add_argument(ROLLBACK_ACK, action="store_true", dest="rollback_ack")
    return parser


def _validate_mode(args: argparse.Namespace) -> str:
    if args.stability_wait_ms < 0 or args.stability_wait_ms > 60_000:
        raise QuarantineError("STABILITY_WAIT_MS_OUT_OF_RANGE")
    if args.apply and args.rollback is not None:
        raise QuarantineError("APPLY_AND_ROLLBACK_ARE_MUTUALLY_EXCLUSIVE")
    if args.apply and not args.apply_ack:
        raise QuarantineError(f"APPLY_REQUIRES_EXACT_ACK:{APPLY_ACK}")
    if not args.apply and args.apply_ack:
        raise QuarantineError("APPLY_ACK_WITHOUT_APPLY")
    if args.rollback is not None and not args.rollback_ack:
        raise QuarantineError(f"ROLLBACK_REQUIRES_EXACT_ACK:{ROLLBACK_ACK}")
    if args.rollback is None and args.rollback_ack:
        raise QuarantineError("ROLLBACK_ACK_WITHOUT_ROLLBACK")
    if args.archive_file is not None and not args.apply:
        raise QuarantineError("ARCHIVE_FILE_OVERRIDE_REQUIRES_APPLY")
    return "rollback" if args.rollback is not None else ("apply" if args.apply else "dry_run")


def _summary(
    *,
    mode: str,
    snapshot: NamespaceSnapshot | None = None,
    archive_path: Path | None = None,
    services: Sequence[Mapping[str, Any]] = (),
    processes: Sequence[Mapping[str, Any]] = (),
    changed_count: int = 0,
    redis_target: str = LOCAL_REDIS_TARGET,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": mode,
        "namespace": NAMESPACE.decode("ascii"),
        "redis_target": normalize_local_redis_target(redis_target),
        "dry_run_only": mode == "dry_run",
        "service_gate_ready": service_gate_safe(services),
        "manual_writer_process_count": len(processes),
        "archive_path": str(archive_path) if archive_path is not None else None,
        "changed_key_count": changed_count,
        "paper_loop_stop_required": False,
        "live_or_exchange_path_touched": False,
    }
    if snapshot is not None:
        counts: dict[str, int] = {}
        for row in snapshot.records:
            reason = str(row["cleanup_classification"])
            counts[reason] = counts.get(reason, 0) + 1
        result.update(
            {
                "key_count": len(snapshot.records),
                "inventory_digest": snapshot.inventory_digest,
                "cleanup_candidate_count": len(snapshot.candidates),
                "cleanup_candidate_digest": candidate_digest(snapshot),
                "classification_counts": counts,
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        mode = _validate_mode(args)
        repo_root = args.repo_root.expanduser().resolve(strict=True)
        if not repo_root.is_dir():
            raise QuarantineError("REPO_ROOT_NOT_DIRECTORY")
        redis_target = normalize_local_redis_target(str(args.redis_url))
        client = _connect_redis(redis_target)

        if mode == "rollback":
            first_services = observe_required_services()
            first_processes = observe_writer_processes()
            payload = read_and_validate_archive(
                args.rollback,
                repo_root,
                redis_target=redis_target,
            )
            if args.stability_wait_ms:
                time.sleep(args.stability_wait_ms / 1000.0)
            second_services = observe_required_services()
            second_processes = observe_writer_processes()
            if not service_gate_safe(first_services) or not service_gate_safe(second_services):
                raise QuarantineError("ROLLBACK_REQUIRES_REQUIRED_UNITS_LOADED_AND_INACTIVE_TWICE")
            if first_processes or second_processes:
                raise QuarantineError("ROLLBACK_REQUIRES_NO_MANUAL_TRAINER_WRITER_PROCESS")
            restored = atomic_restore_candidates(client, payload["cleanup_candidates"])
            print(
                json.dumps(
                    _summary(
                        mode=mode,
                        archive_path=args.rollback,
                        services=second_services,
                        processes=second_processes,
                        changed_count=restored,
                        redis_target=redis_target,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        first_services = observe_required_services()
        first_processes = observe_writer_processes()
        first = capture_namespace(client)
        if args.stability_wait_ms:
            time.sleep(args.stability_wait_ms / 1000.0)
        second = capture_namespace(client)
        assert_candidate_stability(first, second)
        second_services = observe_required_services()
        second_processes = observe_writer_processes()
        archive_payload = build_archive_payload(
            first=first,
            second=second,
            first_services=first_services,
            second_services=second_services,
            first_writer_processes=first_processes,
            second_writer_processes=second_processes,
            redis_target=redis_target,
        )
        proposed_archive = args.archive_file or default_archive_path(
            repo_root, generated_at=str(archive_payload["generated_at"])
        )

        if mode == "dry_run":
            print(
                json.dumps(
                    _summary(
                        mode=mode,
                        snapshot=second,
                        archive_path=proposed_archive,
                        services=second_services,
                        processes=second_processes,
                        redis_target=redis_target,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if not service_gate_safe(first_services) or not service_gate_safe(second_services):
            raise QuarantineError("APPLY_REQUIRES_REQUIRED_UNITS_LOADED_AND_INACTIVE_TWICE")
        if first_processes or second_processes:
            raise QuarantineError("APPLY_REQUIRES_NO_MANUAL_TRAINER_WRITER_PROCESS")
        persisted_archive = write_and_validate_archive(
            proposed_archive,
            archive_payload,
            repo_root,
            redis_target=redis_target,
        )
        deleted = atomic_delete_candidates(client, persisted_archive["cleanup_candidates"])
        print(
            json.dumps(
                _summary(
                    mode=mode,
                    snapshot=second,
                    archive_path=proposed_archive,
                    services=second_services,
                    processes=second_processes,
                    changed_count=deleted,
                    redis_target=redis_target,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, QuarantineError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
