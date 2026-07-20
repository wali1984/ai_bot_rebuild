"""Dormant supervisor boundary for one audit-only OHLCV replay process.

The caller supplies two already-canonical byte documents and a separate,
operator-pinned coordinate object.  Replay request JSON cannot select the
policy, registry, project root, CAS root, interpreter, worker, or process
resource ceilings.  This module validates those coordinates in the parent,
places the exact policy-channel bytes in a sealed Linux memfd, reopens that
memfd read-only, and launches exactly the policy-pinned CPython worker with
``-I -S -B``.  The interpreter is executed through its retained verified file
descriptor, and the worker runs from a sealed immutable source memfd while a
separate nominal absolute path remains bound to the policy closure.

The child has a new process group, an explicit minimal environment, a root
working directory, bounded nonblocking standard streams, and a monotonic wall
deadline covering identity capture, launch, and I/O.  The fresh worker applies
and verifies fixed or tighter POSIX limits immediately after CPython bootstrap;
the boundary makes no pre-exec resource-limit claim.  Any timeout,
stream flood, transport failure, non-zero exit, stderr byte, partial result,
trailing byte, schema mismatch, digest mismatch, or coordinate mismatch kills
and reaps the process group and fails closed.

These controls do not constitute a network namespace, filesystem sandbox,
authenticated policy registry, systemd unit, or runtime dependency closure.
Accordingly the accepted worker result must keep every such claim and all
trainer, prediction, paper-trading, and live-execution authority false.  This
module is dormant: it performs no service wiring, Redis operation, durable
write, trainer admission, prediction, or trading action.  Numeric limits are
process and parser resource ceilings, never market, leverage, margin, sizing,
feature-quality, or risk thresholds.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_policy_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    validate_canonical_ohlcv_hermetic_replay_policy_v4,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_protocol_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION,
    MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4,
    MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4,
    validate_canonical_ohlcv_hermetic_replay_policy_channel_v4,
    validate_canonical_ohlcv_hermetic_replay_request_v4,
)

CANONICAL_OHLCV_HERMETIC_REPLAY_BOUNDARY_V4_CONTRACT_VERSION = (
    "canonical_ohlcv_hermetic_replay_boundary_contract_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_result_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_HASH_DOMAIN = (
    "canonical_ohlcv_hermetic_replay_result_v4/result_sha256/v1"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_DOMAIN_SEPARATOR = (
    CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_HASH_DOMAIN.encode("ascii") + b"\0"
)
CANONICAL_OHLCV_HERMETIC_POLICY_VALIDATION_RESULT_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-policy-validation-result/v4\0"
)
CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_SCHEMA_VERSION = "canonical_ohlcv_selected_row_binding_v4"
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_policy_v4.py"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256 = (
    "e75b3a9c17980d4d04ab7b0e3fd675ae5d73da19e73e9421fd684bd7a4a54a7e"
)

MAX_HERMETIC_REPLAY_BOUNDARY_RESULT_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_BOUNDARY_STDERR_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_BOUNDARY_WALL_MILLISECONDS_V4 = 45 * 1000
MAX_HERMETIC_REPLAY_BOUNDARY_JSON_DEPTH_V4 = 4
MAX_HERMETIC_REPLAY_BOUNDARY_JSON_NODES_V4 = 256
MAX_HERMETIC_REPLAY_BOUNDARY_TEXT_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_BOUNDARY_STRING_BYTES_V4 = 4096
MAX_HERMETIC_REPLAY_BOUNDARY_WORKER_SOURCE_BYTES_V4 = 2 * 1024 * 1024
MAX_HERMETIC_REPLAY_BOUNDARY_PYTHON_EXECUTABLE_BYTES_V4 = 64 * 1024 * 1024

_MAX_SIGNED_64 = (1 << 63) - 1
_READ_CHUNK_BYTES = 64 * 1024
_SELECT_TIMEOUT_SECONDS = 0.1
_REAP_TIMEOUT_SECONDS = 5.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$", re.ASCII)
_CLOCK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", re.ASCII)
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.ASCII)

_MINIMAL_CHILD_ENVIRONMENT: MappingProxyType[str, str] = MappingProxyType(
    {"LANG": "C", "LC_ALL": "C"}
)
_CHILD_ARGUMENT_PREFIX = ("-I", "-S", "-B")

# These are the exact fixed resource policy values validated by the frozen
# policy module.  Supervisor-selected stream/deadline ceilings may only be
# equal or tighter; they can never expand this envelope.
_POLICY_RESOURCE_CEILINGS: MappingProxyType[str, int] = MappingProxyType(
    {
        "cpu_time_seconds": 30,
        "wall_time_milliseconds": MAX_HERMETIC_REPLAY_BOUNDARY_WALL_MILLISECONDS_V4,
        "address_space_bytes": 2 * 1024 * 1024 * 1024,
        "open_file_descriptors": 32,
        "process_count": 1,
        "max_stdout_bytes": MAX_HERMETIC_REPLAY_BOUNDARY_RESULT_BYTES_V4,
        "max_stderr_bytes": MAX_HERMETIC_REPLAY_BOUNDARY_STDERR_BYTES_V4,
        "max_file_write_bytes": 0,
    }
)

_RESULT_TRUE_FIELDS = frozenset(
    {
        "request_validated",
        "sealed_policy_channel_validated",
        "policy_and_code_closure_validated_at_validation",
        "worker_source_path_hash_matched_at_validation",
        "executing_interpreter_inode_and_hash_matched_at_validation",
        "frozen_sources_reverified_at_validation",
        "loaded_project_modules_sourced_only_from_captured_bytes_at_validation",
        "selected_row_binding_replayed",
        "runtime_network_disable_required",
        "runtime_filesystem_write_disable_required",
        "process_resource_limits_applied_after_interpreter_bootstrap",
        "process_resource_limits_verified_at_validation",
        "audit_only",
    }
)
_RESULT_FALSE_FIELDS = frozenset(
    {
        "package_initializer_sources_executed_at_validation",
        "project_root_added_to_sys_path_at_validation",
        "policy_source_authenticated",
        "factory_capture_authenticated",
        "atomic_transport_authenticated",
        "upstream_producer_authenticated",
        "source_payload_authenticated",
        "source_payload_semantics_verified",
        "source_finality_recomputed",
        "source_scope_complete",
        "dependency_manifest_bound",
        "per_field_receipt_bound",
        "durable_ledger_membership_verified",
        "feature_snapshot_published",
        "consumer_eligible",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_dependency_closure_verified",
        "runtime_sandbox_enforced",
        "runtime_wired",
        "factory_receipt_authenticated",
        "factory_authorized",
        "transport_authenticated",
        "transport_authenticity_attested",
        "source_attestation_authenticated",
        "ledger_authorized",
        "ledger_receipt_emitted",
        "durable_ledger_appended",
        "dependency_authorized",
        "dependency_complete",
        "feature_authorized",
        "feature_snapshot_authorized",
        "feature_publication_receipt_emitted",
        "trainer_admission_granted",
        "runtime_network_disabled",
        "runtime_filesystem_write_disabled",
        "systemd_unit_verified",
        "systemd_sandbox_enforced",
        "process_resource_limits_enforced_before_interpreter_bootstrap",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "contract_version",
        "result_hash_domain",
        "request_schema_version",
        "request_sha256",
        "request_nonce",
        "run_id",
        "cycle_id",
        "decision_id",
        "policy_channel_schema_version",
        "policy_channel_sha256",
        "policy_channel_sealing_verified",
        "policy_channel_immutability_verified",
        "policy_schema_version",
        "policy_sha256",
        "policy_document_byte_count",
        "policy_validation_schema_version",
        "policy_validation_result_sha256",
        "policy_id",
        "policy_revision",
        "registry_id",
        "registry_version",
        "project_root",
        "project_owner_uid",
        "python_absolute_path",
        "python_executable_sha256",
        "declared_python_identity_sha256",
        "ledger_owned_cas_root",
        "worker_relative_path",
        "worker_entrypoint",
        "worker_invocation_mode",
        "worker_policy_closure_sha256",
        "hermetic_replay_protocol_relative_path",
        "hermetic_replay_protocol_sha256",
        "hermetic_replay_policy_relative_path",
        "hermetic_replay_policy_source_sha256",
        "code_closure_sha256",
        "resource_policy_sha256",
        "manifest_sha256",
        "manifest_byte_count",
        "selected_row_binding_schema_version",
        "selected_row_binding_sha256",
        "base_replay_sha256",
        "selected_row_payload_sha256",
        "selected_row_payload_byte_count",
        "selected_row_cas_relative_path",
        "symbol",
        "timeframe",
        "matched_selected_ordinal",
        "matched_source_index",
        "matched_candle_id",
        "matched_candle_open_time_ms",
        "matched_candle_close_time_ms",
        "matched_producer_event_time_ms",
        "matched_ingested_at_ms",
        "matched_available_at_ms",
        "matched_source",
        "matched_source_sequence_id",
        "matched_raw_payload_hash",
        "matched_is_backfilled",
        "selected_row_source_read_receipt_sha256",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
        "generated_at",
        "execution_time",
        "process_core_limit_bytes",
        "process_cpu_time_limit_seconds",
        "process_address_space_limit_bytes",
        "process_open_file_descriptor_limit",
        "process_count_limit",
        "process_file_write_limit_bytes",
        "result_sha256",
        *_RESULT_TRUE_FIELDS,
        *_RESULT_FALSE_FIELDS,
    }
)


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4:
    """Supervisor-owned identity and tighter-or-equal process ceilings."""

    expected_policy_sha256: str
    expected_registry_id: str
    expected_registry_version: str
    expected_policy_id: str
    expected_policy_revision: int
    project_root: str
    project_owner_uid: int
    ledger_owned_cas_root: str
    python_absolute_path: str
    python_executable_sha256: str
    worker_absolute_path: str
    worker_sha256: str
    wall_time_milliseconds: int = MAX_HERMETIC_REPLAY_BOUNDARY_WALL_MILLISECONDS_V4
    max_stdout_bytes: int = MAX_HERMETIC_REPLAY_BOUNDARY_RESULT_BYTES_V4
    max_stderr_bytes: int = MAX_HERMETIC_REPLAY_BOUNDARY_STDERR_BYTES_V4


class CanonicalOhlcvHermeticReplayBoundaryV4Error(RuntimeError):
    """A stable, non-authorizing supervisor-boundary failure."""

    def __init__(self, reason: str, *, cleanup_unconfirmed: bool = False) -> None:
        self.reason = reason
        self.cleanup_unconfirmed = cleanup_unconfirmed
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class _ValidatedLaunch:
    request: dict[str, object]
    channel: dict[str, object]
    policy: dict[str, object]
    policy_channel_document: bytes
    policy_document: bytes
    coordinates: CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4
    python_owner_uid: int


@dataclass(frozen=True, slots=True)
class _ProcessCapture:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class _LaunchIdentityDescriptors:
    python_descriptor: int
    worker_source_descriptor: int


_FileFingerprint = tuple[int, int, int, int, int, int, int, int]


class _StrictJsonFailure(ValueError):
    """Internal marker for exact result JSON rejection."""


def _fail(reason: str, *, cleanup_unconfirmed: bool = False) -> NoReturn:
    raise CanonicalOhlcvHermeticReplayBoundaryV4Error(
        reason,
        cleanup_unconfirmed=cleanup_unconfirmed,
    ) from None


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("hermetic_replay_boundary_canonicalization_failed")


def _domain_hash(domain_separator: bytes, value: object) -> str:
    return hashlib.sha256(domain_separator + _canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _require_token(value: object, *, version: bool, reason: str) -> str:
    pattern = _VERSION_RE if version else _TOKEN_RE
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(reason)
    return value


def _require_nonnegative_int(value: object, *, reason: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SIGNED_64:
        _fail(reason)
    return value


def _require_positive_ceiling(value: object, *, maximum: int, reason: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        _fail(reason)
    return value


def _require_absolute_path(value: object, *, reason: str) -> str:
    if type(value) is not str:
        _fail(reason)
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(reason)
    if (
        not encoded
        or len(encoded) > 4096
        or "\0" in value
        or not value.startswith("/")
        or value == "/"
        or value.endswith("/")
        or os.path.normpath(value) != value
        or any(component in {"", ".", ".."} for component in value.split("/")[1:])
    ):
        _fail(reason)
    return value


def _validate_coordinates(
    coordinates: object,
) -> CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4:
    if type(coordinates) is not CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4:
        _fail("hermetic_replay_boundary_supervisor_coordinates_exact_type_required")
    # Launch from a detached scalar snapshot.  The caller retains no object
    # whose later mutation could change already-validated process arguments.
    validated = CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4(
        expected_policy_sha256=coordinates.expected_policy_sha256,
        expected_registry_id=coordinates.expected_registry_id,
        expected_registry_version=coordinates.expected_registry_version,
        expected_policy_id=coordinates.expected_policy_id,
        expected_policy_revision=coordinates.expected_policy_revision,
        project_root=coordinates.project_root,
        project_owner_uid=coordinates.project_owner_uid,
        ledger_owned_cas_root=coordinates.ledger_owned_cas_root,
        python_absolute_path=coordinates.python_absolute_path,
        python_executable_sha256=coordinates.python_executable_sha256,
        worker_absolute_path=coordinates.worker_absolute_path,
        worker_sha256=coordinates.worker_sha256,
        wall_time_milliseconds=coordinates.wall_time_milliseconds,
        max_stdout_bytes=coordinates.max_stdout_bytes,
        max_stderr_bytes=coordinates.max_stderr_bytes,
    )
    _require_sha256(
        validated.expected_policy_sha256,
        reason="hermetic_replay_boundary_expected_policy_digest_invalid",
    )
    _require_token(
        validated.expected_registry_id,
        version=False,
        reason="hermetic_replay_boundary_expected_registry_id_invalid",
    )
    _require_token(
        validated.expected_registry_version,
        version=True,
        reason="hermetic_replay_boundary_expected_registry_version_invalid",
    )
    _require_token(
        validated.expected_policy_id,
        version=False,
        reason="hermetic_replay_boundary_expected_policy_id_invalid",
    )
    if (
        type(validated.expected_policy_revision) is not int
        or not 1 <= validated.expected_policy_revision <= _MAX_SIGNED_64
    ):
        _fail("hermetic_replay_boundary_expected_policy_revision_invalid")
    _require_absolute_path(
        validated.project_root,
        reason="hermetic_replay_boundary_project_root_invalid",
    )
    _require_nonnegative_int(
        validated.project_owner_uid,
        reason="hermetic_replay_boundary_project_owner_uid_invalid",
    )
    _require_absolute_path(
        validated.ledger_owned_cas_root,
        reason="hermetic_replay_boundary_cas_root_invalid",
    )
    _require_absolute_path(
        validated.python_absolute_path,
        reason="hermetic_replay_boundary_python_path_invalid",
    )
    _require_sha256(
        validated.python_executable_sha256,
        reason="hermetic_replay_boundary_python_digest_invalid",
    )
    worker_path = _require_absolute_path(
        validated.worker_absolute_path,
        reason="hermetic_replay_boundary_worker_path_invalid",
    )
    expected_worker_path = os.path.join(
        validated.project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    )
    if worker_path != expected_worker_path:
        _fail("hermetic_replay_boundary_worker_path_not_policy_fixed")
    _require_sha256(
        validated.worker_sha256,
        reason="hermetic_replay_boundary_worker_digest_invalid",
    )
    _require_positive_ceiling(
        validated.wall_time_milliseconds,
        maximum=_POLICY_RESOURCE_CEILINGS["wall_time_milliseconds"],
        reason="hermetic_replay_boundary_wall_ceiling_invalid",
    )
    _require_positive_ceiling(
        validated.max_stdout_bytes,
        maximum=_POLICY_RESOURCE_CEILINGS["max_stdout_bytes"],
        reason="hermetic_replay_boundary_stdout_ceiling_invalid",
    )
    _require_positive_ceiling(
        validated.max_stderr_bytes,
        maximum=_POLICY_RESOURCE_CEILINGS["max_stderr_bytes"],
        reason="hermetic_replay_boundary_stderr_ceiling_invalid",
    )
    return validated


def _validate_parent_inputs(
    *,
    request_document: object,
    policy_channel_document: object,
    supervisor_coordinates: object,
) -> _ValidatedLaunch:
    coordinates = _validate_coordinates(supervisor_coordinates)
    if type(request_document) is not bytes:
        _fail("hermetic_replay_boundary_request_exact_bytes_required")
    if not 1 <= len(request_document) <= MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4:
        _fail("hermetic_replay_boundary_request_size_invalid")
    if type(policy_channel_document) is not bytes:
        _fail("hermetic_replay_boundary_policy_channel_exact_bytes_required")
    if not 1 <= len(policy_channel_document) <= MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4:
        _fail("hermetic_replay_boundary_policy_channel_size_invalid")
    try:
        request_raw = validate_canonical_ohlcv_hermetic_replay_request_v4(request_document)
    except BaseException:
        _fail("hermetic_replay_boundary_request_invalid")
    try:
        channel_raw = validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
            policy_channel_document
        )
    except BaseException:
        _fail("hermetic_replay_boundary_policy_channel_invalid")
    request = dict(request_raw)
    channel = dict(channel_raw)
    expected_channel_coordinates = (
        (channel.get("expected_policy_sha256"), coordinates.expected_policy_sha256),
        (channel.get("expected_registry_id"), coordinates.expected_registry_id),
        (channel.get("expected_registry_version"), coordinates.expected_registry_version),
        (channel.get("expected_policy_id"), coordinates.expected_policy_id),
        (channel.get("expected_policy_revision"), coordinates.expected_policy_revision),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in expected_channel_coordinates
    ):
        _fail("hermetic_replay_boundary_policy_channel_supervisor_coordinate_mismatch")
    policy_document = channel.get("policy_document")
    if type(policy_document) is not bytes:
        _fail("hermetic_replay_boundary_policy_channel_invalid")
    try:
        policy_raw = validate_canonical_ohlcv_hermetic_replay_policy_v4(
            policy_document,
            expected_policy_sha256=coordinates.expected_policy_sha256,
            expected_registry_id=coordinates.expected_registry_id,
            expected_registry_version=coordinates.expected_registry_version,
            expected_policy_id=coordinates.expected_policy_id,
            expected_policy_revision=coordinates.expected_policy_revision,
        )
    except BaseException:
        _fail("hermetic_replay_boundary_policy_invalid")
    policy = dict(policy_raw)
    expected_policy_coordinates = (
        (policy.get("project_root"), coordinates.project_root),
        (policy.get("project_owner_uid"), coordinates.project_owner_uid),
        (policy.get("ledger_owned_cas_root"), coordinates.ledger_owned_cas_root),
        (policy.get("python_absolute_path"), coordinates.python_absolute_path),
        (
            policy.get("python_executable_sha256"),
            coordinates.python_executable_sha256,
        ),
        (
            policy.get("worker_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        ),
        (policy.get("worker_policy_closure_sha256"), coordinates.worker_sha256),
        (
            policy.get("hermetic_replay_protocol_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
        ),
        (
            policy.get("hermetic_replay_protocol_sha256"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
        ),
        (policy.get("policy_sha256"), coordinates.expected_policy_sha256),
        (policy.get("registry_id"), coordinates.expected_registry_id),
        (policy.get("registry_version"), coordinates.expected_registry_version),
        (policy.get("policy_id"), coordinates.expected_policy_id),
        (policy.get("policy_revision"), coordinates.expected_policy_revision),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in expected_policy_coordinates
    ):
        _fail("hermetic_replay_boundary_policy_supervisor_coordinate_mismatch")
    try:
        parsed_policy = cast(dict[str, object], json.loads(policy_document))
        python_runtime = cast(dict[str, object], parsed_policy["python_runtime"])
        python_owner_uid = python_runtime["owner_uid"]
    except (KeyError, TypeError, json.JSONDecodeError):
        _fail("hermetic_replay_boundary_validated_policy_detach_failed")
    if type(python_owner_uid) is not int or python_owner_uid < 0:
        _fail("hermetic_replay_boundary_validated_policy_detach_failed")
    return _ValidatedLaunch(
        request=request,
        channel=channel,
        policy=policy,
        policy_channel_document=policy_channel_document,
        policy_document=policy_document,
        coordinates=coordinates,
        python_owner_uid=python_owner_uid,
    )


def _required_memfd_seal_mask() -> int:
    names = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
    if not hasattr(os, "memfd_create") or not hasattr(os, "MFD_ALLOW_SEALING"):
        _fail("hermetic_replay_boundary_memfd_unavailable")
    if not all(hasattr(fcntl, name) for name in (*names, "F_ADD_SEALS", "F_GET_SEALS")):
        _fail("hermetic_replay_boundary_memfd_seals_unavailable")
    return sum(cast(int, getattr(fcntl, name)) for name in names)


def _write_all(descriptor: int, payload: bytes, *, reason: str) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(descriptor, payload[offset:])
        except OSError:
            _fail(reason)
        if written <= 0:
            _fail(reason)
        offset += written


def _sealed_read_only_memfd(
    payload: bytes,
    *,
    name: str,
    reason_prefix: str,
) -> int:
    seal_mask = _required_memfd_seal_mask()
    writable_descriptor = -1
    read_descriptor = -1
    try:
        flags = os.MFD_ALLOW_SEALING | cast(int, getattr(os, "MFD_CLOEXEC", 0))
        writable_descriptor = os.memfd_create(name, flags)
        _write_all(
            writable_descriptor,
            payload,
            reason=f"{reason_prefix}_write_failed",
        )
        os.lseek(writable_descriptor, 0, os.SEEK_SET)
        fcntl.fcntl(writable_descriptor, fcntl.F_ADD_SEALS, seal_mask)
        if fcntl.fcntl(writable_descriptor, fcntl.F_GET_SEALS) & seal_mask != seal_mask:
            _fail(f"{reason_prefix}_seal_failed")
        read_descriptor = os.open(
            f"/proc/self/fd/{writable_descriptor}",
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
        )
        writable_stat = os.fstat(writable_descriptor)
        read_stat = os.fstat(read_descriptor)
        if (
            (writable_stat.st_dev, writable_stat.st_ino) != (read_stat.st_dev, read_stat.st_ino)
            or fcntl.fcntl(read_descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
            or fcntl.fcntl(read_descriptor, fcntl.F_GET_SEALS) & seal_mask != seal_mask
        ):
            _fail(f"{reason_prefix}_read_only_reopen_failed")
        os.close(writable_descriptor)
        writable_descriptor = -1
        return read_descriptor
    except CanonicalOhlcvHermeticReplayBoundaryV4Error:
        raise
    except (OSError, ValueError):
        _fail(f"{reason_prefix}_creation_failed")
    finally:
        if writable_descriptor >= 0:
            try:
                os.close(writable_descriptor)
            except OSError:
                pass
        if read_descriptor >= 0 and writable_descriptor >= 0:
            try:
                os.close(read_descriptor)
            except OSError:
                pass


def _sealed_read_only_policy_memfd(payload: bytes) -> int:
    return _sealed_read_only_memfd(
        payload,
        name="canonical-ohlcv-policy-v4",
        reason_prefix="hermetic_replay_boundary_policy_memfd",
    )


def _file_fingerprint(value: os.stat_result) -> _FileFingerprint:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_nlink),
    )


def _launch_file_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not cloexec or not nonblock:
        _fail("hermetic_replay_boundary_launch_identity_guards_unavailable")
    return os.O_RDONLY | nofollow | cloexec | nonblock


def _capture_verified_launch_file(
    absolute_path: str,
    *,
    expected_sha256: str,
    expected_owner_uid: int,
    maximum_bytes: int,
    executable_required: bool,
    retain_payload: bool,
    reason_prefix: str,
) -> tuple[int, bytes]:
    descriptor = -1
    retained = False
    try:
        path_stat = os.stat(absolute_path, follow_symlinks=False)
        descriptor = os.open(absolute_path, _launch_file_flags())
        opened_stat = os.fstat(descriptor)
        mode = opened_stat.st_mode
        if (
            _file_fingerprint(path_stat) != _file_fingerprint(opened_stat)
            or not stat.S_ISREG(mode)
            or int(opened_stat.st_uid) != expected_owner_uid
            or int(opened_stat.st_nlink) < 1
            or mode & 0o022 != 0
            or executable_required
            and mode & 0o111 == 0
            or not 1 <= int(opened_stat.st_size) <= maximum_bytes
        ):
            _fail(f"{reason_prefix}_identity_invalid")
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        offset = 0
        remaining = int(opened_stat.st_size)
        while remaining:
            chunk = os.pread(descriptor, min(remaining, _READ_CHUNK_BYTES), offset)
            if not chunk:
                _fail(f"{reason_prefix}_read_failed")
            if retain_payload:
                chunks.append(chunk)
            digest.update(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
        overflow = os.pread(descriptor, 1, offset)
        final_stat = os.fstat(descriptor)
        if (
            overflow
            or _file_fingerprint(final_stat) != _file_fingerprint(opened_stat)
            or not hmac.compare_digest(digest.hexdigest(), expected_sha256)
        ):
            _fail(f"{reason_prefix}_identity_mismatch")
        retained = True
        return descriptor, b"".join(chunks)
    except CanonicalOhlcvHermeticReplayBoundaryV4Error:
        raise
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        _fail(f"{reason_prefix}_capture_failed")
    finally:
        if descriptor >= 0 and not retained:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _capture_launch_identities(validated: _ValidatedLaunch) -> _LaunchIdentityDescriptors:
    python_descriptor = -1
    worker_path_descriptor = -1
    worker_source_descriptor = -1
    retained = False
    try:
        python_descriptor, _ = _capture_verified_launch_file(
            validated.coordinates.python_absolute_path,
            expected_sha256=validated.coordinates.python_executable_sha256,
            expected_owner_uid=validated.python_owner_uid,
            maximum_bytes=MAX_HERMETIC_REPLAY_BOUNDARY_PYTHON_EXECUTABLE_BYTES_V4,
            executable_required=True,
            retain_payload=False,
            reason_prefix="hermetic_replay_boundary_python_launch",
        )
        worker_path_descriptor, worker_source = _capture_verified_launch_file(
            validated.coordinates.worker_absolute_path,
            expected_sha256=validated.coordinates.worker_sha256,
            expected_owner_uid=validated.coordinates.project_owner_uid,
            maximum_bytes=MAX_HERMETIC_REPLAY_BOUNDARY_WORKER_SOURCE_BYTES_V4,
            executable_required=False,
            retain_payload=True,
            reason_prefix="hermetic_replay_boundary_worker_launch",
        )
        worker_source_descriptor = _sealed_read_only_memfd(
            worker_source,
            name="canonical-ohlcv-worker-v4",
            reason_prefix="hermetic_replay_boundary_worker_source_memfd",
        )
        try:
            os.close(worker_path_descriptor)
        except OSError:
            _fail("hermetic_replay_boundary_worker_launch_identity_close_failed")
        worker_path_descriptor = -1
        retained = True
        return _LaunchIdentityDescriptors(
            python_descriptor=python_descriptor,
            worker_source_descriptor=worker_source_descriptor,
        )
    except CanonicalOhlcvHermeticReplayBoundaryV4Error:
        raise
    finally:
        descriptors: tuple[int, ...] = (worker_path_descriptor,)
        if not retained:
            descriptors = (
                worker_path_descriptor,
                worker_source_descriptor,
                python_descriptor,
            )
        for descriptor in descriptors:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _close_pipe(pipe: Any) -> None:
    if pipe is None:
        return
    try:
        pipe.close()
    except OSError:
        pass


def _kill_process_group_and_reap(process: subprocess.Popen[bytes]) -> bool:
    # Attempt the process group even when the leader already exited: an
    # adversarial descendant may still hold a captured pipe open.
    process_group_cleanup_confirmed = True
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        process_group_cleanup_confirmed = False
        try:
            process.kill()
        except OSError:
            pass
    reaped = False
    for _ in range(2):
        try:
            process.wait(timeout=_REAP_TIMEOUT_SECONDS)
            reaped = True
            break
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        except (ChildProcessError, OSError):
            break
    _close_pipe(process.stdin)
    _close_pipe(process.stdout)
    _close_pipe(process.stderr)
    return reaped and process_group_cleanup_confirmed


def _cleanup_or_fail(process: subprocess.Popen[bytes]) -> None:
    if not _kill_process_group_and_reap(process):
        _fail(
            "hermetic_replay_boundary_cleanup_unconfirmed",
            cleanup_unconfirmed=True,
        )


def _selector_unregister_and_close(
    selector: selectors.BaseSelector,
    pipe: Any,
) -> None:
    if pipe is None:
        return
    try:
        selector.unregister(pipe)
    except (KeyError, ValueError):
        pass
    _close_pipe(pipe)


def _capture_process(
    process: subprocess.Popen[bytes],
    *,
    request_document: bytes,
    deadline_ns: int,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> _ProcessCapture:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _fail("hermetic_replay_boundary_process_pipe_setup_failed")
    stdin = process.stdin
    stdout = process.stdout
    stderr = process.stderr
    try:
        for pipe in (stdin, stdout, stderr):
            os.set_blocking(pipe.fileno(), False)
        selector = selectors.DefaultSelector()
    except (OSError, ValueError):
        _fail("hermetic_replay_boundary_process_pipe_setup_failed")
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    request_offset = 0
    stdin_open = True
    stdout_eof = False
    stderr_eof = False
    try:
        try:
            selector.register(stdin, selectors.EVENT_WRITE, "stdin")
            selector.register(stdout, selectors.EVENT_READ, "stdout")
            selector.register(stderr, selectors.EVENT_READ, "stderr")
        except (KeyError, OSError, ValueError):
            _fail("hermetic_replay_boundary_process_pipe_setup_failed")
        while process.poll() is None or not stdout_eof or not stderr_eof:
            remaining_ns = deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                _fail("hermetic_replay_boundary_wall_timeout")
            timeout = min(_SELECT_TIMEOUT_SECONDS, remaining_ns / 1_000_000_000)
            try:
                events = selector.select(timeout)
            except OSError:
                _fail("hermetic_replay_boundary_selector_failed")
            for key, _ in events:
                kind = cast(str, key.data)
                selected_pipe = key.fileobj
                if kind == "stdin":
                    try:
                        written = os.write(
                            cast(Any, selected_pipe).fileno(),
                            request_document[request_offset:],
                        )
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        _selector_unregister_and_close(selector, selected_pipe)
                        stdin_open = False
                        if request_offset != len(request_document):
                            _fail("hermetic_replay_boundary_request_transport_incomplete")
                        continue
                    except OSError:
                        _fail("hermetic_replay_boundary_request_transport_failed")
                    if written <= 0:
                        _fail("hermetic_replay_boundary_request_transport_failed")
                    request_offset += written
                    if request_offset == len(request_document):
                        _selector_unregister_and_close(selector, selected_pipe)
                        stdin_open = False
                else:
                    buffer = stdout_buffer if kind == "stdout" else stderr_buffer
                    limit = max_stdout_bytes if kind == "stdout" else max_stderr_bytes
                    try:
                        chunk = os.read(
                            cast(Any, selected_pipe).fileno(),
                            min(_READ_CHUNK_BYTES, limit - len(buffer) + 1),
                        )
                    except BlockingIOError:
                        continue
                    except OSError:
                        _fail(f"hermetic_replay_boundary_{kind}_transport_failed")
                    if not chunk:
                        _selector_unregister_and_close(selector, selected_pipe)
                        if kind == "stdout":
                            stdout_eof = True
                        else:
                            stderr_eof = True
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > limit:
                        _fail(f"hermetic_replay_boundary_{kind}_limit_exceeded")
            if process.poll() is not None and stdin_open:
                _selector_unregister_and_close(selector, stdin)
                stdin_open = False
                if request_offset != len(request_document):
                    _fail("hermetic_replay_boundary_request_transport_incomplete")
        remaining_seconds = max(0.001, (deadline_ns - time.monotonic_ns()) / 1_000_000_000)
        try:
            returncode = process.wait(timeout=remaining_seconds)
        except subprocess.TimeoutExpired:
            _fail("hermetic_replay_boundary_wall_timeout")
        return _ProcessCapture(
            returncode=returncode,
            stdout=bytes(stdout_buffer),
            stderr=bytes(stderr_buffer),
        )
    finally:
        selector.close()


def _launch_and_capture(
    validated: _ValidatedLaunch,
    request_document: bytes,
) -> MappingProxyType[str, object]:
    deadline_ns = time.monotonic_ns() + validated.coordinates.wall_time_milliseconds * 1_000_000
    policy_descriptor = -1
    python_descriptor = -1
    worker_source_descriptor = -1
    process: subprocess.Popen[bytes] | None = None
    try:
        policy_descriptor = _sealed_read_only_policy_memfd(validated.policy_channel_document)
        identities = _capture_launch_identities(validated)
        python_descriptor = identities.python_descriptor
        worker_source_descriptor = identities.worker_source_descriptor
        if time.monotonic_ns() >= deadline_ns:
            _fail("hermetic_replay_boundary_wall_timeout")
        python_descriptor_path = f"/proc/self/fd/{python_descriptor}"
        worker_descriptor_path = f"/proc/self/fd/{worker_source_descriptor}"
        command = [
            validated.coordinates.python_absolute_path,
            *_CHILD_ARGUMENT_PREFIX,
            worker_descriptor_path,
            "--policy-fd",
            str(policy_descriptor),
            "--worker-path",
            validated.coordinates.worker_absolute_path,
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - retained, hash-bound executable descriptor
                command,
                executable=python_descriptor_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                cwd="/",
                env=dict(_MINIMAL_CHILD_ENVIRONMENT),
                close_fds=True,
                pass_fds=(
                    policy_descriptor,
                    python_descriptor,
                    worker_source_descriptor,
                ),
                start_new_session=True,
                bufsize=0,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            _fail("hermetic_replay_boundary_process_launch_failed")
        try:
            if time.monotonic_ns() >= deadline_ns:
                _fail("hermetic_replay_boundary_wall_timeout")
            capture = _capture_process(
                process,
                request_document=request_document,
                deadline_ns=deadline_ns,
                max_stdout_bytes=validated.coordinates.max_stdout_bytes,
                max_stderr_bytes=validated.coordinates.max_stderr_bytes,
            )
            if capture.returncode != 0:
                _fail("hermetic_replay_boundary_worker_nonzero_exit")
            if capture.stderr:
                _fail("hermetic_replay_boundary_worker_stderr_forbidden")
            result = _validate_result(capture.stdout, validated=validated)
        except CanonicalOhlcvHermeticReplayBoundaryV4Error:
            _cleanup_or_fail(process)
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            _cleanup_or_fail(process)
            _fail("hermetic_replay_boundary_process_transport_failed")
        except BaseException:
            _cleanup_or_fail(process)
            raise
        _close_pipe(process.stdin)
        _close_pipe(process.stdout)
        _close_pipe(process.stderr)
        return result
    finally:
        for descriptor in (
            policy_descriptor,
            python_descriptor,
            worker_source_descriptor,
        ):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonFailure
        result[key] = value
    return result


def _reject_json_float(_value: str) -> NoReturn:
    raise _StrictJsonFailure


def _reject_json_constant(_value: str) -> NoReturn:
    raise _StrictJsonFailure


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        raise _StrictJsonFailure
    parsed = int(value)
    if not -(1 << 63) <= parsed <= _MAX_SIGNED_64:
        raise _StrictJsonFailure
    return parsed


def _preflight_json_depth(document: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in document:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > MAX_HERMETIC_REPLAY_BOUNDARY_JSON_DEPTH_V4:
                raise _StrictJsonFailure
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                raise _StrictJsonFailure


def _parse_exact_result(document: bytes) -> dict[str, object]:
    if not 1 <= len(document) <= MAX_HERMETIC_REPLAY_BOUNDARY_RESULT_BYTES_V4:
        _fail("hermetic_replay_boundary_result_size_invalid")
    try:
        _preflight_json_depth(document)
        parsed = json.loads(
            document.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _fail("hermetic_replay_boundary_result_json_invalid")
    if type(parsed) is not dict:
        _fail("hermetic_replay_boundary_result_object_required")
    result = cast(dict[str, object], parsed)
    if len(result) > MAX_HERMETIC_REPLAY_BOUNDARY_JSON_NODES_V4:
        _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
    text_bytes = 0
    for key, value in result.items():
        try:
            key_bytes = key.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
        text_bytes += len(key_bytes)
        if not 1 <= len(key_bytes) <= MAX_HERMETIC_REPLAY_BOUNDARY_STRING_BYTES_V4:
            _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
        if type(value) is str:
            try:
                value_bytes = value.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
            text_bytes += len(value_bytes)
            if len(value_bytes) > MAX_HERMETIC_REPLAY_BOUNDARY_STRING_BYTES_V4:
                _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
        elif type(value) not in {int, bool} and value is not None:
            _fail("hermetic_replay_boundary_result_scalar_contract_invalid")
    if text_bytes > MAX_HERMETIC_REPLAY_BOUNDARY_TEXT_BYTES_V4:
        _fail("hermetic_replay_boundary_result_resource_limit_exceeded")
    if not hmac.compare_digest(_canonical_json_bytes(result), document):
        _fail("hermetic_replay_boundary_result_noncanonical_json")
    return result


def _address_mapping(value: object) -> dict[str, object]:
    if not hasattr(value, "items"):
        _fail("hermetic_replay_boundary_validated_request_address_invalid")
    return dict(cast(Any, value))


def _validate_result(
    document: bytes,
    *,
    validated: _ValidatedLaunch,
) -> MappingProxyType[str, object]:
    result = _parse_exact_result(document)
    if frozenset(result) != _RESULT_FIELDS:
        _fail("hermetic_replay_boundary_result_fields_invalid")
    for field in _RESULT_TRUE_FIELDS:
        if result.get(field) is not True:
            _fail("hermetic_replay_boundary_result_required_true_claim_invalid")
    for field in _RESULT_FALSE_FIELDS:
        if result.get(field) is not False:
            _fail("hermetic_replay_boundary_result_authority_or_sandbox_claim_invalid")
    if result.get("generated_at") is not None or result.get("execution_time") is not None:
        _fail("hermetic_replay_boundary_result_execution_clock_claim_forbidden")
    resource_result_ceilings = {
        "process_core_limit_bytes": 0,
        "process_cpu_time_limit_seconds": _POLICY_RESOURCE_CEILINGS["cpu_time_seconds"],
        "process_address_space_limit_bytes": _POLICY_RESOURCE_CEILINGS["address_space_bytes"],
        "process_open_file_descriptor_limit": _POLICY_RESOURCE_CEILINGS["open_file_descriptors"],
        "process_count_limit": _POLICY_RESOURCE_CEILINGS["process_count"],
        "process_file_write_limit_bytes": _POLICY_RESOURCE_CEILINGS["max_file_write_bytes"],
    }
    for field, ceiling in resource_result_ceilings.items():
        value = result.get(field)
        if type(value) is not int or not 0 <= value <= ceiling:
            _fail("hermetic_replay_boundary_result_resource_limit_claim_invalid")

    request = validated.request
    channel = validated.channel
    policy = validated.policy
    manifest_address = _address_mapping(request["manifest_address"])
    selected_address = _address_mapping(request["selected_row_address"])
    expected_worker_values: tuple[tuple[object, object], ...] = (
        (result.get("schema_version"), CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_SCHEMA_VERSION),
        (
            result.get("contract_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
        ),
        (result.get("result_hash_domain"), CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_HASH_DOMAIN),
        (
            result.get("request_schema_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION,
        ),
        (result.get("request_sha256"), request["request_sha256"]),
        (result.get("request_nonce"), request["request_nonce"]),
        (result.get("run_id"), request["run_id"]),
        (result.get("cycle_id"), request["cycle_id"]),
        (result.get("decision_id"), request["decision_id"]),
        (
            result.get("policy_channel_schema_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION,
        ),
        (result.get("policy_channel_sha256"), channel["policy_channel_sha256"]),
        (
            result.get("policy_schema_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
        ),
        (result.get("policy_sha256"), policy["policy_sha256"]),
        (result.get("policy_document_byte_count"), len(validated.policy_document)),
        (
            result.get("policy_validation_schema_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION,
        ),
        (result.get("policy_id"), policy["policy_id"]),
        (result.get("policy_revision"), policy["policy_revision"]),
        (result.get("registry_id"), policy["registry_id"]),
        (result.get("registry_version"), policy["registry_version"]),
        (result.get("project_root"), policy["project_root"]),
        (result.get("project_owner_uid"), policy["project_owner_uid"]),
        (result.get("python_absolute_path"), policy["python_absolute_path"]),
        (result.get("python_executable_sha256"), policy["python_executable_sha256"]),
        (
            result.get("declared_python_identity_sha256"),
            policy["declared_python_identity_sha256"],
        ),
        (result.get("ledger_owned_cas_root"), policy["ledger_owned_cas_root"]),
        (result.get("worker_relative_path"), policy["worker_relative_path"]),
        (result.get("worker_entrypoint"), "main"),
        (
            result.get("worker_invocation_mode"),
            "ABSOLUTE_PINNED_PYTHON_ISOLATED_FRESH_PROCESS",
        ),
        (
            result.get("worker_policy_closure_sha256"),
            validated.coordinates.worker_sha256,
        ),
        (
            result.get("hermetic_replay_protocol_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
        ),
        (
            result.get("hermetic_replay_protocol_sha256"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
        ),
        (
            result.get("hermetic_replay_policy_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH,
        ),
        (
            result.get("hermetic_replay_policy_source_sha256"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256,
        ),
        (result.get("code_closure_sha256"), policy["code_closure_sha256"]),
        (result.get("resource_policy_sha256"), policy["resource_policy_sha256"]),
        (result.get("manifest_sha256"), manifest_address["payload_sha256"]),
        (result.get("manifest_byte_count"), manifest_address["payload_byte_count"]),
        (
            result.get("selected_row_binding_schema_version"),
            CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_SCHEMA_VERSION,
        ),
        (result.get("selected_row_payload_sha256"), selected_address["payload_sha256"]),
        (
            result.get("selected_row_payload_byte_count"),
            selected_address["payload_byte_count"],
        ),
        (result.get("selected_row_cas_relative_path"), selected_address["relative_path"]),
        (result.get("symbol"), request["symbol"]),
        (result.get("timeframe"), request["timeframe"]),
        (result.get("decision_time"), request["decision_time"]),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in expected_worker_values
    ):
        _fail("hermetic_replay_boundary_result_request_policy_coordinate_mismatch")

    expected_policy_validation_sha256 = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_POLICY_VALIDATION_RESULT_V4_DOMAIN_SEPARATOR,
        policy,
    )
    if not hmac.compare_digest(
        _require_sha256(
            result.get("policy_validation_result_sha256"),
            reason="hermetic_replay_boundary_result_policy_digest_invalid",
        ),
        expected_policy_validation_sha256,
    ):
        _fail("hermetic_replay_boundary_result_policy_digest_mismatch")

    for field in (
        "selected_row_binding_sha256",
        "base_replay_sha256",
        "selected_row_source_read_receipt_sha256",
        "matched_raw_payload_hash",
    ):
        _require_sha256(
            result.get(field),
            reason="hermetic_replay_boundary_result_semantic_digest_invalid",
        )
    for field in (
        "matched_selected_ordinal",
        "matched_source_index",
        "matched_candle_open_time_ms",
        "matched_candle_close_time_ms",
        "matched_producer_event_time_ms",
        "matched_ingested_at_ms",
        "matched_available_at_ms",
    ):
        _require_nonnegative_int(
            result.get(field),
            reason="hermetic_replay_boundary_result_semantic_integer_invalid",
        )
    if (
        type(result.get("matched_candle_id")) is not str
        or _CANDLE_ID_RE.fullmatch(cast(str, result["matched_candle_id"])) is None
        or type(result.get("matched_source")) is not str
        or type(result.get("matched_source_sequence_id")) is not str
        or type(result.get("matched_is_backfilled")) is not bool
    ):
        _fail("hermetic_replay_boundary_result_semantic_identity_invalid")
    for field in (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
    ):
        value = result.get(field)
        if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
            _fail("hermetic_replay_boundary_result_semantic_clock_invalid")

    supplied_digest = _require_sha256(
        result.get("result_sha256"),
        reason="hermetic_replay_boundary_result_digest_invalid",
    )
    digest_material = dict(result)
    del digest_material["result_sha256"]
    expected_digest = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_DOMAIN_SEPARATOR,
        digest_material,
    )
    if not hmac.compare_digest(supplied_digest, expected_digest):
        _fail("hermetic_replay_boundary_result_digest_mismatch")
    return MappingProxyType(dict(result))


def run_canonical_ohlcv_hermetic_replay_boundary_v4(
    *,
    request_document: object,
    policy_channel_document: object,
    supervisor_coordinates: object,
) -> MappingProxyType[str, object]:
    """Run one policy-pinned audit replay and return a detached exact result."""

    validated = _validate_parent_inputs(
        request_document=request_document,
        policy_channel_document=policy_channel_document,
        supervisor_coordinates=supervisor_coordinates,
    )
    return _launch_and_capture(validated, cast(bytes, request_document))


__all__ = [
    "CANONICAL_OHLCV_HERMETIC_REPLAY_BOUNDARY_V4_CONTRACT_VERSION",
    "CanonicalOhlcvHermeticReplayBoundaryV4Error",
    "CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4",
    "MAX_HERMETIC_REPLAY_BOUNDARY_RESULT_BYTES_V4",
    "MAX_HERMETIC_REPLAY_BOUNDARY_STDERR_BYTES_V4",
    "MAX_HERMETIC_REPLAY_BOUNDARY_WALL_MILLISECONDS_V4",
    "run_canonical_ohlcv_hermetic_replay_boundary_v4",
]
