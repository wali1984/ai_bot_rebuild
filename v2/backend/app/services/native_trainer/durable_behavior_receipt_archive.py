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
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    U53_DENOMINATOR,
    AdaptiveSamplingPlanContractError,
    adaptive_on_policy_lane_plan_rejection_reasons,
    verify_authenticated_sampling_plan_envelope,
)

ARCHIVE_SCHEMA_VERSION = "v2_durable_behavior_receipt_archive_v1"
LIFECYCLE_EVENT_SCHEMA_VERSION = "v2_behavior_receipt_lifecycle_event_v1"
SAMPLING_PLAN_ENVELOPE_ARCHIVE_SCHEMA_VERSION = (
    "v2_authenticated_sampling_plan_envelope_archive_v1"
)
SAMPLING_COHORT_MANIFEST_SCHEMA_VERSION = (
    "v2_on_policy_sampling_cohort_manifest_authenticated_plan_v2"
)
SAMPLING_COHORT_MANIFEST_ARCHIVE_SCHEMA_VERSION = (
    "v2_on_policy_sampling_cohort_manifest_archive_authenticated_plan_v2"
)
SAMPLING_COHORT_COMPLETENESS_SCHEMA_VERSION = (
    "v2_on_policy_sampling_cohort_completeness_authenticated_manifest_v2"
)
SAMPLING_COHORT_COMPLETENESS_ARCHIVE_SCHEMA_VERSION = (
    "v2_on_policy_sampling_cohort_completeness_archive_authenticated_manifest_v2"
)
DEFAULT_ARCHIVE_REL = Path(
    ".local_data/v2_native_trainer/durable_behavior_receipt_archive"
)
RECEIPT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
UPDATE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLING_PLAN_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
NO_ENTRY_REASON_RE = re.compile(r"^[A-Z0-9][A-Z0-9_:.\-/]{0,159}$")
NO_ENTRY_PREDICTION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:@/\-]{0,255}$"
)
MAX_NO_ENTRY_REASON_CODES = 128
SAMPLING_COHORT_TERMINAL_DISPOSITIONS = frozenset(
    {
        "ENTRY_OUTCOME_FINALIZED",
        "SAMPLED_HOLD_FINALIZED",
    }
)
SAMPLING_COHORT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "cohort_id",
        "sampling_plan_envelope_id",
        "sampling_plan_envelope_auth_tag",
        "sampling_plan_cycle_binding_id",
        "sampling_plan_auth_key_id",
        "sampling_plan_hash",
        "sampling_plan_input_hash",
        "parent_policy_fingerprint",
        "checkpoint_id",
        "checkpoint_weight_sha256",
        "sampling_plan",
        "members",
        "sampled_receipt_hashes",
        "sampled_receipt_count",
        "generated_at",
        "pre_admission_manifest",
        "paper_only",
        "routes_to_live",
        "places_real_order",
        "manifest_digest",
    }
)

EVENT_PUBLISHED = "PUBLISHED"
EVENT_NO_ENTRY_FINALIZED = "NO_ENTRY_FINALIZED"
EVENT_ENTRY_ACCEPTED = "ENTRY_ACCEPTED"
EVENT_OUTCOME_FINALIZED = "OUTCOME_FINALIZED"
EVENT_TRAINER_CONSUMED = "TRAINER_CONSUMED"
EVENT_ORDER = (
    EVENT_PUBLISHED,
    EVENT_NO_ENTRY_FINALIZED,
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_TRAINER_CONSUMED,
)
EVENT_PREREQUISITES = {
    EVENT_PUBLISHED: frozenset(),
    EVENT_NO_ENTRY_FINALIZED: frozenset({EVENT_PUBLISHED}),
    EVENT_ENTRY_ACCEPTED: frozenset({EVENT_PUBLISHED}),
    EVENT_OUTCOME_FINALIZED: frozenset(
        {EVENT_PUBLISHED, EVENT_ENTRY_ACCEPTED}
    ),
    EVENT_TRAINER_CONSUMED: frozenset(
        {
            EVENT_PUBLISHED,
            EVENT_ENTRY_ACCEPTED,
            EVENT_OUTCOME_FINALIZED,
        }
    ),
}
EVENT_SEMANTIC_TIME_FIELDS = {
    EVENT_PUBLISHED: ("decision_time",),
    EVENT_NO_ENTRY_FINALIZED: (
        "decision_time",
        "disposition_available_at",
    ),
    EVENT_ENTRY_ACCEPTED: ("decision_time", "entry_time"),
    EVENT_OUTCOME_FINALIZED: ("outcome_available_at",),
    EVENT_TRAINER_CONSUMED: ("ledger_recorded_utc",),
}
NO_ENTRY_TERMINAL_DISPOSITIONS = frozenset(
    {"SAMPLED_HOLD_FINALIZED"}
)
NO_ENTRY_REASON_DIGEST_SCHEMA_VERSION = (
    "v2_behavior_receipt_no_entry_reason_digest_v1"
)
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


@dataclass(frozen=True)
class SamplingCohortArchiveWrite:
    cohort_digest: str
    manifest_digest: str
    archive_content_sha256: str
    proof_path: Path
    already_present: bool


@dataclass(frozen=True)
class SamplingPlanEnvelopeArchiveWrite:
    plan_instance_id: str
    cycle_binding_id: str
    archive_content_sha256: str
    envelope_path: Path
    already_present: bool


@dataclass(frozen=True)
class SamplingCohortManifestArchiveWrite:
    plan_instance_id: str
    manifest_digest: str
    archive_content_sha256: str
    manifest_path: Path
    already_present: bool


SamplingPlanKeyResolver = Callable[
    [str], bytes | bytearray | memoryview
]


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


def _same_strict_utc(left: Any, right: Any) -> bool:
    left_time = _strict_utc(left)
    right_time = _strict_utc(right)
    return left_time is not None and left_time == right_time


def _normalized_no_entry_reason_codes(value: Any) -> list[str]:
    if (
        type(value) is not list
        or not value
        or len(value) > MAX_NO_ENTRY_REASON_CODES
        or any(
            type(reason) is not str
            or not NO_ENTRY_REASON_RE.fullmatch(reason)
            for reason in value
        )
        or value != sorted(set(value))
    ):
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_REASON_CODES_INVALID"
        )
    return list(value)


def _no_entry_reason_codes_sha256(
    *,
    prediction_id: str,
    terminal_disposition: str,
    reason_codes: list[str],
) -> str:
    return canonical_sha256(
        {
            "schema_version": NO_ENTRY_REASON_DIGEST_SCHEMA_VERSION,
            "prediction_id": prediction_id,
            "terminal_disposition": terminal_disposition,
            "reason_codes": reason_codes,
        }
    )


def build_no_entry_terminal_binding(
    *,
    prediction_id: str,
    decision_time: str,
    disposition_available_at: str,
    terminal_disposition: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    """Build exact evidence for one sampled action that created no entry."""

    normalized_prediction_id = str(prediction_id or "")
    if not NO_ENTRY_PREDICTION_ID_RE.fullmatch(normalized_prediction_id):
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_PREDICTION_ID_INVALID"
        )
    if terminal_disposition not in NO_ENTRY_TERMINAL_DISPOSITIONS:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_DISPOSITION_INVALID"
        )
    normalized_reasons = _normalized_no_entry_reason_codes(reason_codes)
    if normalized_reasons != ["SAMPLED_HOLD"]:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_HOLD_REASONS_INVALID"
        )
    decision = _strict_utc(decision_time)
    available = _strict_utc(disposition_available_at)
    if decision is None or available is None or decision > available:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_TIME_INVALID"
        )
    binding = {
        "prediction_id": normalized_prediction_id,
        "decision_time": decision_time,
        "disposition_available_at": disposition_available_at,
        "terminal_disposition": terminal_disposition,
        "reason_codes": normalized_reasons,
    }
    return {
        **binding,
        "reason_codes_sha256": _no_entry_reason_codes_sha256(
            prediction_id=normalized_prediction_id,
            terminal_disposition=terminal_disposition,
            reason_codes=normalized_reasons,
        ),
    }


def _validate_no_entry_terminal_binding(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    if set(binding) != {
        "prediction_id",
        "decision_time",
        "disposition_available_at",
        "terminal_disposition",
        "reason_codes",
        "reason_codes_sha256",
    }:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_BINDING_SHAPE_INVALID"
        )
    reason_codes = binding.get("reason_codes")
    if type(reason_codes) is not list:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_REASON_CODES_INVALID"
        )
    validated = build_no_entry_terminal_binding(
        prediction_id=str(binding.get("prediction_id") or ""),
        decision_time=str(binding.get("decision_time") or ""),
        disposition_available_at=str(
            binding.get("disposition_available_at") or ""
        ),
        terminal_disposition=str(
            binding.get("terminal_disposition") or ""
        ),
        reason_codes=cast(list[str], reason_codes),
    )
    if dict(binding) != validated:
        raise BehaviorReceiptArchiveError(
            "NO_ENTRY_TERMINAL_BINDING_DIGEST_INVALID"
        )
    return validated


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

    if event_type == EVENT_NO_ENTRY_FINALIZED:
        _validate_no_entry_terminal_binding(binding)
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
    no_entry = times_by_type.get(EVENT_NO_ENTRY_FINALIZED)
    entry = times_by_type.get(EVENT_ENTRY_ACCEPTED)
    outcome = times_by_type.get(EVENT_OUTCOME_FINALIZED)
    consumed = times_by_type.get(EVENT_TRAINER_CONSUMED)
    if no_entry is not None and entry is not None:
        raise BehaviorReceiptArchiveError(
            "LIFECYCLE_TERMINAL_PATH_CONFLICT"
        )
    if published is not None and no_entry is not None:
        if no_entry["decision_time"] != published["decision_time"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_NO_ENTRY_DECISION_TIME_BINDING_MISMATCH"
            )
        if no_entry["decision_time"] > no_entry["disposition_available_at"]:
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID"
            )
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


def _validate_lifecycle_receipt_binding(
    *,
    receipt: Mapping[str, Any],
    events_by_type: Mapping[str, Mapping[str, Any]],
) -> None:
    receipt_prediction_id = receipt.get("prediction_id")
    receipt_decision_time = receipt.get("decision_time")
    receipt_action = receipt.get("selected_action")
    published = events_by_type.get(EVENT_PUBLISHED)
    if published is not None:
        binding = published.get("binding")
        if not isinstance(binding, Mapping):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_BINDING_INVALID"
            )
        if (
            receipt_prediction_id not in (None, "")
            and binding.get("prediction_id") != receipt_prediction_id
        ) or (
            receipt_decision_time not in (None, "")
            and not _same_strict_utc(
                binding.get("decision_time"), receipt_decision_time
            )
        ):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_PUBLISHED_RECEIPT_BINDING_MISMATCH"
            )
    no_entry = events_by_type.get(EVENT_NO_ENTRY_FINALIZED)
    if no_entry is not None:
        binding = no_entry.get("binding")
        if not isinstance(binding, Mapping):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_BINDING_INVALID"
            )
        validated = _validate_no_entry_terminal_binding(binding)
        if (
            validated["prediction_id"] != receipt_prediction_id
            or not _same_strict_utc(
                validated["decision_time"], receipt_decision_time
            )
            or receipt_action != "hold"
        ):
            raise BehaviorReceiptArchiveError(
                "NO_ENTRY_TERMINAL_RECEIPT_BINDING_INVALID"
            )
    entry = events_by_type.get(EVENT_ENTRY_ACCEPTED)
    if entry is not None:
        binding = entry.get("binding")
        if not isinstance(binding, Mapping):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_EVENT_BINDING_INVALID"
            )
        if (
            receipt_action not in (None, "", "long", "short")
            or (
                receipt_decision_time not in (None, "")
                and not _same_strict_utc(
                    binding.get("decision_time"), receipt_decision_time
                )
            )
        ):
            raise BehaviorReceiptArchiveError(
                "LIFECYCLE_ENTRY_RECEIPT_BINDING_MISMATCH"
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


def _sampling_plan_envelope_path(root: Path, plan_instance_id: str) -> Path:
    return (
        root
        / "sampling_plan_envelopes"
        / plan_instance_id[:2]
        / f"{plan_instance_id}.json"
    )


def _sampling_cohort_manifest_path(root: Path, plan_instance_id: str) -> Path:
    return (
        root
        / "sampling_cohort_manifests"
        / plan_instance_id[:2]
        / f"{plan_instance_id}.json"
    )


def _sampling_cohort_proof_path(root: Path, cohort_digest: str) -> Path:
    return (
        root
        / "sampling_cohort_completeness"
        / cohort_digest[:2]
        / f"{cohort_digest}.json"
    )


def _required_sha256(value: Any, reason: str) -> str:
    normalized = str(value or "")
    if not RECEIPT_HASH_RE.fullmatch(normalized):
        raise BehaviorReceiptArchiveError(reason)
    return normalized


def _verified_sampling_plan_envelope(
    envelope: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    expected_plan_instance_id: str | None = None,
) -> dict[str, Any]:
    if not callable(key_resolver):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_KEY_RESOLVER_REQUIRED"
        )
    key_id = str(envelope.get("auth_key_id") or "")
    if not SAMPLING_PLAN_AUTH_KEY_ID_RE.fullmatch(key_id):
        raise BehaviorReceiptArchiveError("SAMPLING_PLAN_AUTH_KEY_ID_INVALID")
    try:
        hmac_key = key_resolver(key_id)
    except Exception as exc:  # noqa: BLE001
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_KEY_RESOLUTION_FAILED"
        ) from exc
    try:
        return verify_authenticated_sampling_plan_envelope(
            envelope,
            hmac_key=hmac_key,
            expected_auth_key_id=key_id,
            expected_plan_instance_id=expected_plan_instance_id,
        )
    except AdaptiveSamplingPlanContractError as exc:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_AUTHENTICATION_INVALID"
        ) from exc


def archive_authenticated_sampling_plan_envelope(
    envelope: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> SamplingPlanEnvelopeArchiveWrite:
    """Persist one authenticated plan without persisting its HMAC secret."""

    if not isinstance(envelope, Mapping):
        raise BehaviorReceiptArchiveError("SAMPLING_PLAN_ENVELOPE_MISSING")
    verified = _verified_sampling_plan_envelope(
        envelope,
        key_resolver=key_resolver,
    )
    plan_instance_id = _required_sha256(
        verified.get("plan_instance_id"),
        "SAMPLING_PLAN_INSTANCE_ID_INVALID",
    )
    cycle_binding_id = _required_sha256(
        verified.get("cycle_binding_id"),
        "SAMPLING_PLAN_CYCLE_BINDING_ID_INVALID",
    )
    record_without_hash = {
        "schema_version": SAMPLING_PLAN_ENVELOPE_ARCHIVE_SCHEMA_VERSION,
        "plan_instance_id": plan_instance_id,
        "cycle_binding_id": cycle_binding_id,
        "sampling_plan_hash": verified["sampling_plan_hash"],
        "auth_key_id": verified["auth_key_id"],
        "auth_tag": verified["auth_tag"],
        "envelope": verified,
    }
    archive_hash = canonical_sha256(record_without_hash)
    record = {**record_without_hash, "archive_content_sha256": archive_hash}
    archive_root = root or default_archive_root()
    path = _sampling_plan_envelope_path(archive_root, plan_instance_id)
    try:
        already_present = _write_json_create_or_identical(path, record)
    except BehaviorReceiptArchiveError as exc:
        if str(exc) == "ARCHIVE_IMMUTABLE_CONFLICT":
            raise BehaviorReceiptArchiveError(
                "SAMPLING_PLAN_ENVELOPE_INSTANCE_CONFLICT"
            ) from exc
        raise
    loaded = load_authenticated_sampling_plan_envelope(
        plan_instance_id,
        key_resolver=key_resolver,
        root=archive_root,
    )
    if loaded != verified:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_READ_AFTER_WRITE_MISMATCH"
        )
    return SamplingPlanEnvelopeArchiveWrite(
        plan_instance_id=plan_instance_id,
        cycle_binding_id=cycle_binding_id,
        archive_content_sha256=archive_hash,
        envelope_path=path,
        already_present=already_present,
    )


def load_authenticated_sampling_plan_envelope(
    plan_instance_id: Any,
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> dict[str, Any]:
    """Read and re-authenticate the exact envelope on every access."""

    instance_id = _required_sha256(
        plan_instance_id,
        "SAMPLING_PLAN_INSTANCE_ID_INVALID",
    )
    archive_root = root or default_archive_root()
    path = _sampling_plan_envelope_path(archive_root, instance_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_ARCHIVE_UNREADABLE"
        ) from exc
    if not isinstance(record, dict):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_ARCHIVE_INVALID"
        )
    archive_hash = str(record.pop("archive_content_sha256", ""))
    envelope = record.get("envelope")
    if (
        set(record)
        != {
            "schema_version",
            "plan_instance_id",
            "cycle_binding_id",
            "sampling_plan_hash",
            "auth_key_id",
            "auth_tag",
            "envelope",
        }
        or not RECEIPT_HASH_RE.fullmatch(archive_hash)
        or canonical_sha256(record) != archive_hash
        or record.get("schema_version")
        != SAMPLING_PLAN_ENVELOPE_ARCHIVE_SCHEMA_VERSION
        or record.get("plan_instance_id") != instance_id
        or not isinstance(envelope, Mapping)
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_ARCHIVE_INTEGRITY_INVALID"
        )
    verified = _verified_sampling_plan_envelope(
        envelope,
        key_resolver=key_resolver,
        expected_plan_instance_id=instance_id,
    )
    if (
        record.get("cycle_binding_id") != verified.get("cycle_binding_id")
        or record.get("sampling_plan_hash")
        != verified.get("sampling_plan_hash")
        or record.get("auth_key_id") != verified.get("auth_key_id")
        or record.get("auth_tag") != verified.get("auth_tag")
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_ARCHIVE_BINDING_INVALID"
        )
    return verified


def verify_archived_authenticated_sampling_plan_envelope(
    envelope: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> dict[str, Any]:
    verified = _verified_sampling_plan_envelope(
        envelope,
        key_resolver=key_resolver,
    )
    archived = load_authenticated_sampling_plan_envelope(
        verified["plan_instance_id"],
        key_resolver=key_resolver,
        root=root,
    )
    if archived != verified:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_PLAN_ENVELOPE_ARCHIVE_PAYLOAD_MISMATCH"
        )
    return archived


def _validated_sampling_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    rejection_reasons = adaptive_on_policy_lane_plan_rejection_reasons(plan)
    if rejection_reasons:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_PLAN_SEMANTICS_INVALID:"
            + ",".join(rejection_reasons)
        )
    row = dict(plan)
    supplied_hash = _required_sha256(
        row.pop("plan_hash", ""),
        "SAMPLING_COHORT_PLAN_HASH_INVALID",
    )
    if canonical_sha256(row) != supplied_hash:
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_HASH_MISMATCH")
    input_hash = _required_sha256(
        row.get("input_hash"),
        "SAMPLING_COHORT_PLAN_INPUT_HASH_INVALID",
    )
    selected = row.get("selected_indices")
    audit = row.get("candidate_audit")
    candidate_count = row.get("candidate_count")
    if (
        not isinstance(selected, list)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in selected)
        or selected != sorted(set(selected))
        or any(value < 0 for value in selected)
    ):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_SELECTION_INVALID")
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
        or not isinstance(audit, list)
        or len(audit) != candidate_count
        or row.get("selected_sample_count") != len(selected)
        or any(value >= candidate_count for value in selected)
    ):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_COUNTS_INVALID")
    audit_indices = [
        item.get("index") if isinstance(item, Mapping) else None for item in audit
    ]
    if audit_indices != list(range(candidate_count)):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_AUDIT_INVALID")
    input_material = {
        "schema_version": row.get("schema_version"),
        "formula": row.get("formula"),
        "carry_in": row.get("carry_in"),
        "single_candidate_ordinary_credit_in": row.get(
            "single_candidate_ordinary_credit_in"
        ),
        "paper_margin_inputs": row.get("paper_margin_inputs"),
        "paper_entry_freeze_inputs": row.get("paper_entry_freeze_inputs"),
        "candidate_audit": audit,
    }
    if canonical_sha256(input_material) != input_hash:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_PLAN_INPUT_BINDING_MISMATCH"
        )
    if (
        row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_SAFETY_INVALID")
    return {**row, "plan_hash": supplied_hash}


def _validate_receipt_against_sampling_plan(
    receipt: Mapping[str, Any],
    *,
    selected_index: int,
    sampling_plan: Mapping[str, Any],
    parent_policy_fingerprint: str,
    expected_draw_u53: int | None = None,
) -> str:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
        behavior_receipt_rejection_reasons,
    )

    receipt_hash = _receipt_hash(receipt)
    audit = sampling_plan["candidate_audit"][selected_index]
    if not isinstance(audit, Mapping):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_AUDIT_INVALID")
    expected_fields = {
        "symbol": audit.get("symbol"),
        "timeframe": audit.get("timeframe"),
        "feature_tensor_id": audit.get("feature_tensor_id"),
        "checkpoint_id": audit.get("checkpoint_id"),
        "checkpoint_weight_sha256": audit.get("checkpoint_weight_sha256"),
        "checkpoint_evidence_digest": audit.get("checkpoint_evidence_digest"),
        "cost_source_payload_sha256": audit.get("exact_cost_payload_hash"),
    }
    if any(receipt.get(field) != expected for field, expected in expected_fields.items()):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_PLAN_MEMBER_MISMATCH"
        )
    for field in ("feature_cutoff", "available_at", "candle_close_time"):
        if not _same_strict_utc(receipt.get(field), audit.get(field)):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_RECEIPT_PLAN_CLOCK_MISMATCH"
            )
    audit_decision = _strict_utc(audit.get("decision_time"))
    receipt_decision = _strict_utc(receipt.get("decision_time"))
    if (
        audit_decision is None
        or receipt_decision is None
        or receipt_decision != audit_decision
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_PLAN_DECISION_TIME_INVALID"
        )
    if (
        receipt.get("on_policy_sampling_selected") is not True
        or receipt.get("candle_closed_confirmed") is not True
        or audit.get("candle_closed_confirmed") is not True
        or audit.get("eligible") is not True
        or receipt.get("on_policy_sampling_plan_hash") != sampling_plan["plan_hash"]
        or receipt.get("on_policy_sampling_plan_input_hash")
        != sampling_plan["input_hash"]
        or receipt.get("served_policy_fingerprint") != parent_policy_fingerprint
        or audit.get("served_policy_fingerprint")
        != parent_policy_fingerprint
        or canonical_sha256(
            {"raw_action_logits": receipt.get("raw_action_logits")}
        )
        != audit.get("raw_policy_logits_hash")
        or (
            expected_draw_u53 is not None
            and (
                receipt.get("sample_draw_u53") != expected_draw_u53
                or receipt.get("sample_draw_denominator") != U53_DENOMINATOR
            )
        )
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_PLAN_BINDING_INVALID"
        )
    if str(receipt.get("selected_action") or "").lower() not in {
        "hold",
        "long",
        "short",
    }:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_ACTION_INVALID"
        )
    rejection_reasons = behavior_receipt_rejection_reasons(
        receipt,
        expected_symbol=audit.get("symbol"),
        expected_timeframe=audit.get("timeframe"),
        expected_checkpoint_id=audit.get("checkpoint_id"),
        expected_checkpoint_weight_sha256=audit.get(
            "checkpoint_weight_sha256"
        ),
        expected_feature_tensor_id=audit.get("feature_tensor_id"),
        expected_feature_cutoff=receipt.get("feature_cutoff"),
        expected_available_at=receipt.get("available_at"),
        expected_decision_time=receipt.get("decision_time"),
        expected_policy_fingerprint=parent_policy_fingerprint,
        expected_sampling_plan_hash=sampling_plan["plan_hash"],
        expected_sampling_plan_input_hash=sampling_plan["input_hash"],
    )
    if rejection_reasons:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_INVALID:"
            + ",".join(rejection_reasons)
        )
    return receipt_hash


def _sampling_plan_draws_by_index(
    envelope: Mapping[str, Any],
) -> dict[int, int]:
    return {
        int(record["selected_index"]): int(record["draw_u53"])
        for record in envelope["selected_index_draws"]
    }


def _validate_manifest_member_receipt_identity(
    *,
    member: Mapping[str, Any],
    receipt: Mapping[str, Any],
    observed_receipt_hash: str,
) -> None:
    if (
        member.get("receipt_hash") != observed_receipt_hash
        or member.get("prediction_id") != receipt.get("prediction_id")
        or member.get("selected_action") != receipt.get("selected_action")
        or member.get("sample_draw_u53") != receipt.get("sample_draw_u53")
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_RECEIPT_IDENTITY_MISMATCH"
        )


def build_sampling_cohort_manifest(
    *,
    sampling_plan_envelope: Mapping[str, Any],
    receipts_by_selected_index: Mapping[int, Mapping[str, Any]],
    key_resolver: SamplingPlanKeyResolver,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Bind every sampled receipt to one authenticated pre-admission plan."""

    envelope = _verified_sampling_plan_envelope(
        sampling_plan_envelope,
        key_resolver=key_resolver,
    )
    plan = _validated_sampling_plan(envelope["sampling_plan"])
    parent = envelope["parent_policy_fingerprint"]
    draws_by_index = _sampling_plan_draws_by_index(envelope)
    normalized: dict[int, Mapping[str, Any]] = {}
    for raw_index, receipt in receipts_by_selected_index.items():
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_RECEIPT_INDEX_INVALID"
            )
        if raw_index in normalized or not isinstance(receipt, Mapping):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_RECEIPT_INDEX_INVALID"
            )
        normalized[raw_index] = receipt
    selected = list(plan["selected_indices"])
    if not selected or sorted(normalized) != selected:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_NOT_COMPLETE"
        )
    members: list[dict[str, Any]] = []
    decision_times: list[datetime] = []
    for selected_index in selected:
        receipt = normalized[selected_index]
        receipt_hash = _validate_receipt_against_sampling_plan(
            receipt,
            selected_index=selected_index,
            sampling_plan=plan,
            parent_policy_fingerprint=parent,
            expected_draw_u53=draws_by_index[selected_index],
        )
        decision = _strict_utc(receipt.get("decision_time"))
        if decision is None:
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_RECEIPT_DECISION_TIME_INVALID"
            )
        decision_times.append(decision)
        members.append(
            {
                "selected_index": selected_index,
                "receipt_hash": receipt_hash,
                "prediction_id": str(receipt.get("prediction_id") or ""),
                "selected_action": str(receipt.get("selected_action") or "").lower(),
                "sample_draw_u53": draws_by_index[selected_index],
            }
        )
    if len({member["receipt_hash"] for member in members}) != len(members):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_DUPLICATE_RECEIPT")
    if len({member["prediction_id"] for member in members}) != len(members):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_DUPLICATE_PREDICTION")
    timestamp = generated_at or utc_now()
    generated_time = _strict_utc(timestamp)
    sealed_time = _strict_utc(envelope["sealed_at"])
    if (
        generated_time is None
        or sealed_time is None
        or generated_time < max([*decision_times, sealed_time])
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_TIME_INVALID"
        )
    identity = {
        "sampling_plan_envelope_id": envelope["plan_instance_id"],
        "sampling_plan_envelope_auth_tag": envelope["auth_tag"],
        "sampling_plan_cycle_binding_id": envelope["cycle_binding_id"],
        "sampling_plan_hash": plan["plan_hash"],
        "sampling_plan_input_hash": plan["input_hash"],
        "parent_policy_fingerprint": parent,
        "members": members,
    }
    material = {
        "schema_version": SAMPLING_COHORT_MANIFEST_SCHEMA_VERSION,
        "cohort_id": canonical_sha256(identity),
        "sampling_plan_envelope_id": envelope["plan_instance_id"],
        "sampling_plan_envelope_auth_tag": envelope["auth_tag"],
        "sampling_plan_cycle_binding_id": envelope["cycle_binding_id"],
        "sampling_plan_auth_key_id": envelope["auth_key_id"],
        "sampling_plan_hash": plan["plan_hash"],
        "sampling_plan_input_hash": plan["input_hash"],
        "parent_policy_fingerprint": parent,
        "checkpoint_id": envelope["checkpoint_id"],
        "checkpoint_weight_sha256": envelope["checkpoint_weight_sha256"],
        "sampling_plan": plan,
        "members": members,
        "sampled_receipt_hashes": [member["receipt_hash"] for member in members],
        "sampled_receipt_count": len(members),
        "generated_at": timestamp,
        "pre_admission_manifest": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {**material, "manifest_digest": canonical_sha256(material)}


def _validated_sampling_cohort_manifest(
    manifest: Mapping[str, Any],
    *,
    sampling_plan_envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = dict(manifest)
    if set(row) != SAMPLING_COHORT_MANIFEST_FIELDS:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_SHAPE_INVALID"
        )
    supplied_digest = _required_sha256(
        row.pop("manifest_digest", ""),
        "SAMPLING_COHORT_MANIFEST_DIGEST_INVALID",
    )
    if canonical_sha256(row) != supplied_digest:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_DIGEST_MISMATCH"
        )
    if row.get("schema_version") != SAMPLING_COHORT_MANIFEST_SCHEMA_VERSION:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_SCHEMA_INVALID"
        )
    plan_instance_id = _required_sha256(
        row.get("sampling_plan_envelope_id"),
        "SAMPLING_COHORT_PLAN_INSTANCE_ID_INVALID",
    )
    envelope_auth_tag = _required_sha256(
        row.get("sampling_plan_envelope_auth_tag"),
        "SAMPLING_COHORT_PLAN_AUTH_TAG_INVALID",
    )
    cycle_binding_id = _required_sha256(
        row.get("sampling_plan_cycle_binding_id"),
        "SAMPLING_COHORT_PLAN_CYCLE_BINDING_INVALID",
    )
    if not str(row.get("sampling_plan_auth_key_id") or ""):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_PLAN_AUTH_KEY_ID_INVALID"
        )
    plan_raw = row.get("sampling_plan")
    if not isinstance(plan_raw, Mapping):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PLAN_MISSING")
    plan = _validated_sampling_plan(plan_raw)
    parent = _required_sha256(
        row.get("parent_policy_fingerprint"),
        "SAMPLING_COHORT_PARENT_POLICY_INVALID",
    )
    _required_sha256(
        row.get("checkpoint_weight_sha256"),
        "SAMPLING_COHORT_CHECKPOINT_HASH_INVALID",
    )
    if not str(row.get("checkpoint_id") or ""):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_CHECKPOINT_ID_INVALID"
        )
    if (
        row.get("sampling_plan_hash") != plan["plan_hash"]
        or row.get("sampling_plan_input_hash") != plan["input_hash"]
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_PLAN_BINDING_INVALID"
        )
    members = row.get("members")
    if not isinstance(members, list) or not members:
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_MANIFEST_EMPTY")
    indices: list[int] = []
    hashes: list[str] = []
    draws: list[int] = []
    for member in members:
        if not isinstance(member, Mapping):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_MEMBER_INVALID"
            )
        if set(member) != {
            "selected_index",
            "receipt_hash",
            "prediction_id",
            "selected_action",
            "sample_draw_u53",
        }:
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_MEMBER_INVALID"
            )
        index = member.get("selected_index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_MEMBER_INVALID"
            )
        indices.append(index)
        hashes.append(
            _required_sha256(
                member.get("receipt_hash"),
                "SAMPLING_COHORT_RECEIPT_HASH_INVALID",
            )
        )
        draw = member.get("sample_draw_u53")
        if (
            isinstance(draw, bool)
            or not isinstance(draw, int)
            or not 0 <= draw < U53_DENOMINATOR
        ):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_DRAW_INVALID"
            )
        draws.append(draw)
        if (
            not isinstance(member.get("prediction_id"), str)
            or not member["prediction_id"]
            or member.get("selected_action") not in {"hold", "long", "short"}
        ):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_MEMBER_INVALID"
            )
    if (
        indices != list(plan["selected_indices"])
        or len(set(hashes)) != len(hashes)
        or len({str(member["prediction_id"]) for member in members})
        != len(members)
        or row.get("sampled_receipt_hashes") != hashes
        or row.get("sampled_receipt_count") != len(members)
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_MEMBERSHIP_INVALID"
        )
    identity = {
        "sampling_plan_envelope_id": plan_instance_id,
        "sampling_plan_envelope_auth_tag": envelope_auth_tag,
        "sampling_plan_cycle_binding_id": cycle_binding_id,
        "sampling_plan_hash": plan["plan_hash"],
        "sampling_plan_input_hash": plan["input_hash"],
        "parent_policy_fingerprint": parent,
        "members": [dict(member) for member in members],
    }
    if row.get("cohort_id") != canonical_sha256(identity):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_IDENTITY_INVALID"
        )
    generated = _strict_utc(row.get("generated_at"))
    if generated is None:
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_MANIFEST_TIME_INVALID")
    if (
        row.get("pre_admission_manifest") is not True
        or row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_SAFETY_INVALID"
        )
    validated = {
        **row,
        "sampling_plan": plan,
        "manifest_digest": supplied_digest,
    }
    if sampling_plan_envelope is not None:
        envelope = dict(sampling_plan_envelope)
        envelope_draws = _sampling_plan_draws_by_index(envelope)
        if (
            plan_instance_id != envelope.get("plan_instance_id")
            or envelope_auth_tag != envelope.get("auth_tag")
            or cycle_binding_id != envelope.get("cycle_binding_id")
            or validated.get("sampling_plan_auth_key_id")
            != envelope.get("auth_key_id")
            or validated.get("sampling_plan_hash")
            != envelope.get("sampling_plan_hash")
            or validated.get("sampling_plan_input_hash")
            != envelope.get("sampling_plan_input_hash")
            or parent != envelope.get("parent_policy_fingerprint")
            or validated.get("checkpoint_id") != envelope.get("checkpoint_id")
            or validated.get("checkpoint_weight_sha256")
            != envelope.get("checkpoint_weight_sha256")
            or plan != envelope.get("sampling_plan")
            or list(zip(indices, draws, strict=True))
            != list(envelope_draws.items())
        ):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_ENVELOPE_BINDING_INVALID"
            )
        generated_time = _strict_utc(validated.get("generated_at"))
        sealed_time = _strict_utc(envelope.get("sealed_at"))
        if (
            generated_time is None
            or sealed_time is None
            or generated_time < sealed_time
        ):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_TIME_INVALID"
            )
    return validated


@contextmanager
def _locked_receipt_lifecycles(
    *,
    receipt_hashes: list[str],
    root: Path,
) -> Iterator[None]:
    """Exclude lifecycle admission while a first manifest is committed."""

    with ExitStack() as stack:
        for receipt_hash in sorted(set(receipt_hashes)):
            lock_path = (
                root / "locks" / receipt_hash[:2] / f"{receipt_hash}.lock"
            )
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_handle = stack.enter_context(lock_path.open("a+b"))
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            stack.callback(fcntl.flock, lock_handle.fileno(), fcntl.LOCK_UN)
        yield


def archive_sampling_cohort_manifest(
    manifest: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> SamplingCohortManifestArchiveWrite:
    structurally_validated = _validated_sampling_cohort_manifest(manifest)
    archive_root = root or default_archive_root()
    plan_instance_id = structurally_validated["sampling_plan_envelope_id"]
    envelope = load_authenticated_sampling_plan_envelope(
        plan_instance_id,
        key_resolver=key_resolver,
        root=archive_root,
    )
    validated = _validated_sampling_cohort_manifest(
        structurally_validated,
        sampling_plan_envelope=envelope,
    )
    draws_by_index = _sampling_plan_draws_by_index(envelope)
    record_without_hash = {
        "schema_version": SAMPLING_COHORT_MANIFEST_ARCHIVE_SCHEMA_VERSION,
        "plan_instance_id": plan_instance_id,
        "manifest_digest": validated["manifest_digest"],
        "manifest": validated,
    }
    archive_hash = canonical_sha256(record_without_hash)
    record = {**record_without_hash, "archive_content_sha256": archive_hash}
    path = _sampling_cohort_manifest_path(archive_root, plan_instance_id)
    receipt_hashes = list(validated["sampled_receipt_hashes"])
    with _locked_receipt_lifecycles(
        receipt_hashes=receipt_hashes,
        root=archive_root,
    ):
        if path.exists():
            archived = load_sampling_cohort_manifest(
                plan_instance_id,
                key_resolver=key_resolver,
                root=archive_root,
            )
            if archived != validated:
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MANIFEST_INSTANCE_CONFLICT"
                )
            already_present = True
        else:
            for member in validated["members"]:
                receipt = load_behavior_receipt(
                    member["receipt_hash"], root=archive_root
                )
                if lifecycle_events(member["receipt_hash"], root=archive_root):
                    raise BehaviorReceiptArchiveError(
                        "SAMPLING_COHORT_MANIFEST_NOT_PRE_ADMISSION"
                    )
                observed = _validate_receipt_against_sampling_plan(
                    receipt,
                    selected_index=member["selected_index"],
                    sampling_plan=validated["sampling_plan"],
                    parent_policy_fingerprint=validated[
                        "parent_policy_fingerprint"
                    ],
                    expected_draw_u53=draws_by_index[
                        member["selected_index"]
                    ],
                )
                if observed != member["receipt_hash"]:
                    raise BehaviorReceiptArchiveError(
                        "SAMPLING_COHORT_MANIFEST_RECEIPT_BINDING_INVALID"
                    )
                _validate_manifest_member_receipt_identity(
                    member=member,
                    receipt=receipt,
                    observed_receipt_hash=observed,
                )
            try:
                already_present = _write_json_create_or_identical(path, record)
            except BehaviorReceiptArchiveError as exc:
                if str(exc) == "ARCHIVE_IMMUTABLE_CONFLICT":
                    raise BehaviorReceiptArchiveError(
                        "SAMPLING_COHORT_MANIFEST_INSTANCE_CONFLICT"
                    ) from exc
                raise
            archived = load_sampling_cohort_manifest(
                plan_instance_id,
                key_resolver=key_resolver,
                root=archive_root,
            )
            if archived != validated:
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MANIFEST_READ_AFTER_WRITE_MISMATCH"
                )
    return SamplingCohortManifestArchiveWrite(
        plan_instance_id=plan_instance_id,
        manifest_digest=validated["manifest_digest"],
        archive_content_sha256=archive_hash,
        manifest_path=path,
        already_present=already_present,
    )


def load_sampling_cohort_manifest(
    plan_instance_id: Any,
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> dict[str, Any]:
    instance_id = _required_sha256(
        plan_instance_id,
        "SAMPLING_COHORT_PLAN_INSTANCE_ID_INVALID",
    )
    archive_root = root or default_archive_root()
    path = _sampling_cohort_manifest_path(archive_root, instance_id)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_ARCHIVE_UNREADABLE"
        ) from exc
    if not isinstance(record, dict):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_ARCHIVE_INVALID"
        )
    archive_hash = str(record.pop("archive_content_sha256", ""))
    manifest = record.get("manifest")
    if (
        set(record)
        != {
            "schema_version",
            "plan_instance_id",
            "manifest_digest",
            "manifest",
        }
        or not RECEIPT_HASH_RE.fullmatch(archive_hash)
        or canonical_sha256(record) != archive_hash
        or record.get("schema_version")
        != SAMPLING_COHORT_MANIFEST_ARCHIVE_SCHEMA_VERSION
        or record.get("plan_instance_id") != instance_id
        or not isinstance(manifest, Mapping)
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_ARCHIVE_INTEGRITY_INVALID"
        )
    envelope = load_authenticated_sampling_plan_envelope(
        instance_id,
        key_resolver=key_resolver,
        root=archive_root,
    )
    validated = _validated_sampling_cohort_manifest(
        manifest,
        sampling_plan_envelope=envelope,
    )
    if (
        validated["manifest_digest"] != record.get("manifest_digest")
        or validated["sampling_plan_envelope_id"] != instance_id
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_ARCHIVE_BINDING_INVALID"
        )
    draws_by_index = _sampling_plan_draws_by_index(envelope)
    for member in validated["members"]:
        receipt = load_behavior_receipt(
            member["receipt_hash"], root=archive_root
        )
        observed = _validate_receipt_against_sampling_plan(
            receipt,
            selected_index=member["selected_index"],
            sampling_plan=validated["sampling_plan"],
            parent_policy_fingerprint=validated[
                "parent_policy_fingerprint"
            ],
            expected_draw_u53=draws_by_index[member["selected_index"]],
        )
        if observed != member["receipt_hash"]:
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MANIFEST_RECEIPT_BINDING_INVALID"
            )
        _validate_manifest_member_receipt_identity(
            member=member,
            receipt=receipt,
            observed_receipt_hash=observed,
        )
    return validated


def verify_archived_sampling_cohort_manifest(
    manifest: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> dict[str, Any]:
    validated = _validated_sampling_cohort_manifest(manifest)
    archived = load_sampling_cohort_manifest(
        validated["sampling_plan_envelope_id"],
        key_resolver=key_resolver,
        root=root,
    )
    if archived != validated:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_MANIFEST_ARCHIVE_PAYLOAD_MISMATCH"
        )
    return validated


def build_sampling_cohort_completeness_proof(
    *,
    manifest: Mapping[str, Any],
    terminal_dispositions: Mapping[str, str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Bind terminal outcomes to the exact immutable pre-admission manifest."""

    validated_manifest = _validated_sampling_cohort_manifest(manifest)
    normalized_dispositions = {
        str(receipt_hash): str(disposition)
        for receipt_hash, disposition in terminal_dispositions.items()
    }
    sampled = list(validated_manifest["sampled_receipt_hashes"])
    if set(normalized_dispositions) != set(sampled):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_NOT_FULLY_TERMINALIZED"
        )
    if any(
        disposition not in SAMPLING_COHORT_TERMINAL_DISPOSITIONS
        for disposition in normalized_dispositions.values()
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_TERMINAL_DISPOSITION_INVALID"
        )
    timestamp = generated_at or utc_now()
    generated = _strict_utc(timestamp)
    manifest_time = _strict_utc(validated_manifest["generated_at"])
    if generated is None or manifest_time is None or generated < manifest_time:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_TIME_INVALID"
        )
    material = {
        "schema_version": SAMPLING_COHORT_COMPLETENESS_SCHEMA_VERSION,
        "sampling_plan_envelope_id": validated_manifest[
            "sampling_plan_envelope_id"
        ],
        "manifest_digest": validated_manifest["manifest_digest"],
        "cohort_id": validated_manifest["cohort_id"],
        "sampling_plan_hash": validated_manifest["sampling_plan_hash"],
        "sampling_plan_input_hash": validated_manifest["sampling_plan_input_hash"],
        "parent_policy_fingerprint": validated_manifest[
            "parent_policy_fingerprint"
        ],
        "sampled_receipt_hashes": sampled,
        "terminalized_receipt_hashes": sampled,
        "terminal_dispositions": {
            receipt_hash: normalized_dispositions[receipt_hash]
            for receipt_hash in sampled
        },
        "sampled_receipt_count": len(sampled),
        "terminalized_receipt_count": len(sampled),
        "generated_at": timestamp,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {**material, "cohort_digest": canonical_sha256(material)}


def _validated_sampling_cohort_proof(
    proof: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(proof)
    supplied_digest = _required_sha256(
        row.pop("cohort_digest", ""),
        "SAMPLING_COHORT_DIGEST_INVALID",
    )
    if canonical_sha256(row) != supplied_digest:
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_DIGEST_MISMATCH")
    if row.get("schema_version") != SAMPLING_COHORT_COMPLETENESS_SCHEMA_VERSION:
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_SCHEMA_VERSION_INVALID")
    for field in (
        "sampling_plan_envelope_id",
        "manifest_digest",
        "cohort_id",
        "sampling_plan_hash",
        "sampling_plan_input_hash",
        "parent_policy_fingerprint",
    ):
        _required_sha256(
            row.get(field), f"SAMPLING_COHORT_{field.upper()}_INVALID"
        )
    sampled = row.get("sampled_receipt_hashes")
    terminalized = row.get("terminalized_receipt_hashes")
    dispositions = row.get("terminal_dispositions")
    if (
        not isinstance(sampled, list)
        or not sampled
        or any(not RECEIPT_HASH_RE.fullmatch(str(value)) for value in sampled)
        or len(set(sampled)) != len(sampled)
        or terminalized != sampled
        or not isinstance(dispositions, Mapping)
        or set(dispositions) != set(sampled)
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_MEMBERSHIP_INVALID"
        )
    if any(
        disposition not in SAMPLING_COHORT_TERMINAL_DISPOSITIONS
        for disposition in dispositions.values()
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_TERMINAL_DISPOSITION_INVALID"
        )
    if (
        row.get("sampled_receipt_count") != len(sampled)
        or row.get("terminalized_receipt_count") != len(sampled)
        or _strict_utc(row.get("generated_at")) is None
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_COUNTS_OR_TIME_INVALID"
        )
    if (
        row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_PAPER_SAFETY_INVALID")
    return {**row, "cohort_digest": supplied_digest}


def _verify_sampling_cohort_terminal_lifecycle(
    *,
    proof: Mapping[str, Any],
    manifest: Mapping[str, Any],
    root: Path,
) -> None:
    proof_time = _strict_utc(proof.get("generated_at"))
    manifest_time = _strict_utc(manifest.get("generated_at"))
    if (
        proof_time is None
        or manifest_time is None
        or proof_time < manifest_time
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_TIME_INVALID"
        )
    members_by_hash = {
        member["receipt_hash"]: member for member in manifest["members"]
    }
    for receipt_hash in proof["sampled_receipt_hashes"]:
        receipt = load_behavior_receipt(receipt_hash, root=root)
        disposition = proof["terminal_dispositions"][receipt_hash]
        member = members_by_hash[receipt_hash]
        status = receipt_lifecycle_status(receipt_hash, root=root)
        event_bindings = status.get("event_bindings")
        if not isinstance(event_bindings, Mapping):
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_MEMBER_NOT_DURABLY_TERMINALIZED"
            )
        if disposition == "ENTRY_OUTCOME_FINALIZED":
            if (
                member["selected_action"] not in {"long", "short"}
                or status.get("no_entry_finalized_durable") is True
                or status.get("entry_accepted_durable") is not True
                or status.get("outcome_finalized_durable") is not True
            ):
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MEMBER_NOT_DURABLY_TERMINALIZED"
                )
            outcome_binding = event_bindings.get(EVENT_OUTCOME_FINALIZED)
            if not isinstance(outcome_binding, Mapping):
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MEMBER_NOT_DURABLY_TERMINALIZED"
                )
            terminal_time = _strict_utc(
                outcome_binding.get("outcome_available_at")
            )
        else:
            no_entry_binding = event_bindings.get(EVENT_NO_ENTRY_FINALIZED)
            if not isinstance(no_entry_binding, Mapping):
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MEMBER_NOT_DURABLY_TERMINALIZED"
                )
            validated_no_entry = _validate_no_entry_terminal_binding(
                no_entry_binding
            )
            selected_action = member["selected_action"]
            if (
                status.get("no_entry_finalized_durable") is not True
                or status.get("entry_accepted_durable") is True
                or validated_no_entry["terminal_disposition"] != disposition
                or validated_no_entry["prediction_id"]
                != member["prediction_id"]
                or validated_no_entry["prediction_id"]
                != receipt.get("prediction_id")
                or not _same_strict_utc(
                    validated_no_entry["decision_time"],
                    receipt.get("decision_time"),
                )
                or (
                    disposition == "SAMPLED_HOLD_FINALIZED"
                    and selected_action != "hold"
                )
            ):
                raise BehaviorReceiptArchiveError(
                    "SAMPLING_COHORT_MEMBER_NOT_DURABLY_TERMINALIZED"
                )
            terminal_time = _strict_utc(
                validated_no_entry["disposition_available_at"]
            )
        if terminal_time is None or terminal_time > proof_time:
            raise BehaviorReceiptArchiveError(
                "SAMPLING_COHORT_TERMINAL_TIME_INVALID"
            )


def _manifest_bound_to_proof(
    proof: Mapping[str, Any], manifest: Mapping[str, Any]
) -> bool:
    return all(
        proof.get(field) == manifest.get(field)
        for field in (
            "sampling_plan_envelope_id",
            "manifest_digest",
            "cohort_id",
            "sampling_plan_hash",
            "sampling_plan_input_hash",
            "parent_policy_fingerprint",
            "sampled_receipt_hashes",
            "sampled_receipt_count",
        )
    )


def archive_sampling_cohort_completeness_proof(
    proof: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
) -> SamplingCohortArchiveWrite:
    validated = _validated_sampling_cohort_proof(proof)
    archive_root = root or default_archive_root()
    manifest = load_sampling_cohort_manifest(
        validated["sampling_plan_envelope_id"],
        key_resolver=key_resolver,
        root=archive_root,
    )
    if not _manifest_bound_to_proof(validated, manifest):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_MANIFEST_MISMATCH"
        )
    _verify_sampling_cohort_terminal_lifecycle(
        proof=validated, manifest=manifest, root=archive_root
    )
    record_without_hash = {
        "schema_version": SAMPLING_COHORT_COMPLETENESS_ARCHIVE_SCHEMA_VERSION,
        "cohort_digest": validated["cohort_digest"],
        "proof": validated,
    }
    archive_hash = canonical_sha256(record_without_hash)
    record = {**record_without_hash, "archive_content_sha256": archive_hash}
    path = _sampling_cohort_proof_path(archive_root, validated["cohort_digest"])
    already_present = _write_json_create_or_identical(path, record)
    verify_archived_sampling_cohort_completeness_proof(
        validated,
        key_resolver=key_resolver,
        root=archive_root,
    )
    return SamplingCohortArchiveWrite(
        cohort_digest=validated["cohort_digest"],
        manifest_digest=validated["manifest_digest"],
        archive_content_sha256=archive_hash,
        proof_path=path,
        already_present=already_present,
    )


def verify_archived_sampling_cohort_completeness_proof(
    proof: Mapping[str, Any],
    *,
    key_resolver: SamplingPlanKeyResolver,
    root: Path | None = None,
    expected_receipt_hash: str | None = None,
    expected_sampling_plan_hash: str | None = None,
    expected_sampling_plan_input_hash: str | None = None,
    expected_parent_policy_fingerprint: str | None = None,
) -> dict[str, Any]:
    validated = _validated_sampling_cohort_proof(proof)
    for observed, expected, reason in (
        (
            validated["sampling_plan_hash"],
            expected_sampling_plan_hash,
            "SAMPLING_COHORT_PLAN_HASH_MISMATCH",
        ),
        (
            validated["sampling_plan_input_hash"],
            expected_sampling_plan_input_hash,
            "SAMPLING_COHORT_PLAN_INPUT_HASH_MISMATCH",
        ),
        (
            validated["parent_policy_fingerprint"],
            expected_parent_policy_fingerprint,
            "SAMPLING_COHORT_PARENT_POLICY_MISMATCH",
        ),
    ):
        if expected is not None and observed != expected:
            raise BehaviorReceiptArchiveError(reason)
    if expected_receipt_hash is not None and expected_receipt_hash not in validated[
        "sampled_receipt_hashes"
    ]:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_RECEIPT_MEMBERSHIP_MISSING"
        )
    archive_root = root or default_archive_root()
    manifest = load_sampling_cohort_manifest(
        validated["sampling_plan_envelope_id"],
        key_resolver=key_resolver,
        root=archive_root,
    )
    if not _manifest_bound_to_proof(validated, manifest):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_COMPLETENESS_MANIFEST_MISMATCH"
        )
    path = _sampling_cohort_proof_path(archive_root, validated["cohort_digest"])
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_ARCHIVE_UNREADABLE"
        ) from exc
    if not isinstance(record, dict):
        raise BehaviorReceiptArchiveError("SAMPLING_COHORT_ARCHIVE_RECORD_INVALID")
    archive_hash = str(record.pop("archive_content_sha256", ""))
    if (
        not RECEIPT_HASH_RE.fullmatch(archive_hash)
        or canonical_sha256(record) != archive_hash
        or record.get("schema_version")
        != SAMPLING_COHORT_COMPLETENESS_ARCHIVE_SCHEMA_VERSION
        or record.get("cohort_digest") != validated["cohort_digest"]
        or record.get("proof") != validated
    ):
        raise BehaviorReceiptArchiveError(
            "SAMPLING_COHORT_ARCHIVE_INTEGRITY_INVALID"
        )
    _verify_sampling_cohort_terminal_lifecycle(
        proof=validated, manifest=manifest, root=archive_root
    )
    return {
        "cohort_verified": True,
        "cohort_digest": validated["cohort_digest"],
        "manifest_digest": validated["manifest_digest"],
        "cohort_id": validated["cohort_id"],
        "sampled_receipt_count": len(validated["sampled_receipt_hashes"]),
        "terminalized_receipt_count": len(validated["terminalized_receipt_hashes"]),
        "receipt_membership_verified": expected_receipt_hash is not None,
        "generated_at": validated["generated_at"],
        "archive_content_sha256": archive_hash,
        "proof_path": str(path),
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
    receipt = load_behavior_receipt(value, root=archive_root)
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
    if (
        EVENT_NO_ENTRY_FINALIZED in present_types
        and EVENT_ENTRY_ACCEPTED in present_types
    ):
        raise BehaviorReceiptArchiveError(
            "LIFECYCLE_TERMINAL_PATH_CONFLICT"
        )
    for event_type in event_types:
        if not EVENT_PREREQUISITES[event_type].issubset(present_types):
            raise BehaviorReceiptArchiveError("LIFECYCLE_PREREQUISITE_MISSING")
    events_by_type = {
        str(event["event_type"]): event
        for event in events
    }
    _validate_lifecycle_semantic_order(events_by_type)
    _validate_lifecycle_receipt_binding(
        receipt=receipt,
        events_by_type=events_by_type,
    )
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
    receipt = load_behavior_receipt(value, root=archive_root)
    existing = lifecycle_events(value, root=archive_root)
    existing_types = {str(row.get("event_type")) for row in existing}
    if not EVENT_PREREQUISITES[event_type].issubset(existing_types):
        raise BehaviorReceiptArchiveError("LIFECYCLE_PREREQUISITE_MISSING")
    if (
        event_type == EVENT_NO_ENTRY_FINALIZED
        and EVENT_ENTRY_ACCEPTED in existing_types
    ) or (
        event_type == EVENT_ENTRY_ACCEPTED
        and EVENT_NO_ENTRY_FINALIZED in existing_types
    ):
        raise BehaviorReceiptArchiveError(
            "LIFECYCLE_TERMINAL_PATH_CONFLICT"
        )
    if event_type == EVENT_TRAINER_CONSUMED:
        update_key = str(binding.get("ppo_consumption_update_key") or "")
        if not UPDATE_KEY_RE.fullmatch(update_key):
            raise BehaviorReceiptArchiveError("TRAINER_CONSUMPTION_UPDATE_KEY_INVALID")
    identity_fields = {
        EVENT_PUBLISHED: ("prediction_id",),
        EVENT_NO_ENTRY_FINALIZED: (
            "prediction_id",
            "terminal_disposition",
        ),
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
    _validate_lifecycle_receipt_binding(
        receipt=receipt,
        events_by_type=prospective_events,
    )
    prior_recorded_times = [
        _strict_utc(event.get("recorded_at"))
        for event in existing
        if str(event.get("event_type"))
        in EVENT_PREREQUISITES[event_type]
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
        "no_entry_finalized_durable": EVENT_NO_ENTRY_FINALIZED in types,
        "entry_accepted_durable": EVENT_ENTRY_ACCEPTED in types,
        "outcome_finalized_durable": EVENT_OUTCOME_FINALIZED in types,
        "trainer_consumed_durable": EVENT_TRAINER_CONSUMED in types,
        "retention_required": EVENT_TRAINER_CONSUMED not in types,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
