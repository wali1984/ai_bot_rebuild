"""Dormant fixed-policy validation for future canonical OHLCV replay.

This module validates one canonical-JSON policy document.
The policy fixes the Python executable, ledger-owned immutable-CAS root,
worker protocol, canonical source profile, accepted schemas, complete ordered
project-code closure, and process resource ceilings.  A caller must also
provide expected policy and registry coordinates through a channel separate
from replay request JSON.  Replay requests must never be allowed to populate
those arguments.  This module does not authenticate that separate channel.

Validation performs and compares two complete reopen passes over the Python
executable, CAS root, project root, descendant code directories, and ordered
code files.  Each pass avoids symlink traversal, hashes regular files from
stable descriptors, and checks trusted ownership plus non-writable-by-group-or-
other modes where required.  It imports no project module while doing so.  A
successful result only establishes two matching validation-time snapshots of
this dormant policy and its local filesystem inputs.  It does not establish a
durable identity, a runtime import closure, or sandbox enforcement; validate
source bytes or semantics; authenticate an upstream producer; admit trainer
data; or authorize paper or live trading.  Every authority field is fixed
false in both the policy and the detached scalar-only result.

The numeric limits below are parser, isolation, and allocation ceilings.  They
are not market, feature-quality, leverage, margin, sizing, or risk thresholds.
This module invokes no explicit filesystem write syscall, process launch,
network access, Redis access, trainer invocation, or trading action.  Its
read-only opens may update filesystem access-time metadata on filesystems that
do not suppress atime updates.

The worker path and role are fixed, but its digest is deliberately not
hardcoded before that separate slice is frozen.  Its exact digest is declared
inside the policy's ordered code closure, is transitively bound by the
separately supplied expected policy digest, and must match the worker file in
both reopen passes.  The already-frozen protocol dependency is pinned here
exactly.  These are validation-time file facts only; no runtime service or
sandbox enforcement may be inferred.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn, TypeAlias, cast

CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_contract_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_validation_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN = (
    "v2/native-trainer/canonical-ohlcv-hermetic-replay-policy/v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR = (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN.encode("ascii") + b"\0"
)
CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-python-identity/v4\0"
)
CANONICAL_OHLCV_HERMETIC_CODE_CLOSURE_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-code-closure/v4\0"
)
CANONICAL_OHLCV_HERMETIC_RESOURCE_POLICY_V4_DOMAIN_SEPARATOR = (
    b"v2/native-trainer/canonical-ohlcv-hermetic-resource-policy/v4\0"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_protocol_v4.py"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256 = (
    "055794d2fc9d1ce6c2c5383a6f73a24ca403abb47cbbcb14d252b62a108fdee9"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_worker_v4.py"
)

MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4 = 128 * 1024
MAX_HERMETIC_POLICY_JSON_DEPTH_V4 = 8
MAX_HERMETIC_POLICY_JSON_NODES_V4 = 1024
MAX_HERMETIC_POLICY_CONTAINER_ITEMS_V4 = 128
MAX_HERMETIC_POLICY_TEXT_BYTES_V4 = 64 * 1024
MAX_HERMETIC_POLICY_STRING_BYTES_V4 = 4096
MAX_HERMETIC_POLICY_PATH_BYTES_V4 = 4096
MIN_HERMETIC_POLICY_INTEGER_V4 = -(2**63)
MAX_HERMETIC_POLICY_INTEGER_V4 = 2**63 - 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$", re.ASCII)
_MODE_RE = re.compile(r"^0[0-7]{3}$", re.ASCII)

_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "contract_version",
        "policy_id",
        "policy_revision",
        "registry_id",
        "registry_version",
        "project_root",
        "project_owner_uid",
        "python_runtime",
        "ledger_owned_cas_root",
        "canonical_profile",
        "accepted_schemas",
        "worker",
        "code_closure",
        "resource_ceilings",
        "worker_protocol",
        "authority_policy",
        "audit_only",
    }
)
_PYTHON_RUNTIME_FIELDS = frozenset(
    {
        "identity_schema_version",
        "absolute_path",
        "implementation",
        "version",
        "isolated_flags",
        "owner_uid",
        "mode_octal",
        "executable_byte_count",
        "executable_sha256",
        "identity_sha256",
    }
)
_CAS_ROOT_FIELDS = frozenset(
    {
        "absolute_path",
        "owner_uid",
        "required_mode_octal",
        "namespace",
        "ownership_model",
        "access_mode",
        "request_selectable",
    }
)
_WORKER_FIELDS = frozenset(
    {
        "relative_path",
        "entrypoint",
        "invocation_mode",
    }
)
_CODE_CLOSURE_ENTRY_FIELDS = frozenset({"ordinal", "role", "relative_path", "byte_count", "sha256"})

_CANONICAL_PROFILE: MappingProxyType[str, object] = MappingProxyType(
    {
        "profile_id": "canonical_binance_closed_ohlcv_profile_v4",
        "adapter_id": "canonical-ohlcv-closed-adapter-v4",
        "branch_identity": "canonical-ohlcv-atomic-adapter-v4",
        "evidence_kind": "POSITIVE_SOURCE_READ",
        "evidence_class": "EXACT_ATOMIC_CANONICAL_BINANCE_CLOSED_OHLCV",
        "upstream_producer_identity_claim": "binance-public-market-data",
        "finality_kind": "CLOSED_INTERVAL",
        "row_payload_type": "EXACT_CANONICAL_CLOSED_OHLCV_ROW_BYTES",
    }
)
_ACCEPTED_SCHEMAS: MappingProxyType[str, object] = MappingProxyType(
    {
        "atomic_redis_source_read": "trainer_atomic_redis_source_read_v2",
        "atomic_redis_source_result": "trainer_atomic_redis_source_result_v2",
        "source_payload_store": "immutable_source_payload_store_v1",
        "source_payload_address": "source_payload_content_address_v1",
        "ohlcv_closed_window": "trainer_ohlcv_closed_window_v1",
        "canonical_atomic_capture": "canonical_ohlcv_atomic_capture_v1",
        "canonical_suffix_manifest": "canonical_ohlcv_suffix_manifest_v1",
        "canonical_suffix_digest": "canonical_ohlcv_suffix_digest_v1",
        "manifest_semantic_replay": "canonical_ohlcv_manifest_semantic_replay_v4",
        "selected_row_binding": "canonical_ohlcv_selected_row_binding_v4",
        "hermetic_replay_protocol_contract": (
            "canonical_ohlcv_hermetic_replay_protocol_contract_v4"
        ),
        "hermetic_replay_request": "canonical_ohlcv_hermetic_replay_request_v4",
        "hermetic_replay_policy_channel": "canonical_ohlcv_hermetic_replay_policy_channel_v4",
        "source_read_receipt": "feature_source_consumer_read_receipt_v4",
        "source_read_evidence": "feature_source_exact_read_evidence_v4",
        "source_finality_evidence": "feature_source_finality_evidence_v4",
        "source_read_locator": "feature_source_read_locator_v4",
        "feature_window_contract": "trainer_core_ta_minimum_coverage_v1",
        "contiguous_suffix_inspection": "trainer_contiguous_suffix_inspection_v1",
        "full_contiguous_input_binding": "trainer_full_contiguous_core_input_v1",
        "candle_id_chain": "trainer_candle_id_chain_v1",
    }
)
_WORKER_POLICY: MappingProxyType[str, object] = MappingProxyType(
    {
        "relative_path": CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        "entrypoint": "main",
        "invocation_mode": "ABSOLUTE_PINNED_PYTHON_ISOLATED_FRESH_PROCESS",
    }
)
_REQUEST_MATERIAL_FIELD_ORDER = (
    "schema_version",
    "contract_version",
    "request_nonce",
    "run_id",
    "cycle_id",
    "decision_id",
    "manifest_address",
    "selected_row_address",
    "symbol",
    "timeframe",
    "decision_time",
)
_WORKER_PROTOCOL: MappingProxyType[str, object] = MappingProxyType(
    {
        "request_schema_version": "canonical_ohlcv_hermetic_replay_request_v4",
        "result_schema_version": "canonical_ohlcv_hermetic_replay_result_v4",
        "request_material": list(_REQUEST_MATERIAL_FIELD_ORDER),
        "request_transport": "BOUNDED_CANONICAL_JSON_STDIN",
        "result_transport": "BOUNDED_CANONICAL_JSON_STDOUT",
        "policy_transport": "SUPERVISOR_OWNED_SEPARATE_READ_ONLY_CHANNEL",
        "policy_in_request": False,
        "python_path_in_request": False,
        "cas_root_in_request": False,
        "worker_path_in_request": False,
        "code_closure_in_request": False,
        "resource_ceilings_in_request": False,
        "authority_in_request": False,
        "fresh_process_required": True,
        "isolated_python_required": True,
        "site_packages_disabled": True,
        "bytecode_writes_disabled": True,
        "runtime_network_disable_required": True,
        "runtime_filesystem_write_disable_required": True,
        "request_nonce_required": True,
        "request_digest_required": True,
        "result_digest_required": True,
    }
)

# The order is part of the policy contract.  It covers the import-package
# chain and every project module in the planned worker/replay dependency graph.
PROJECT_CODE_CLOSURE_V4: tuple[tuple[str, str], ...] = (
    ("v2_package_init", "v2/__init__.py"),
    ("backend_package_init", "v2/backend/__init__.py"),
    ("app_package_init", "v2/backend/app/__init__.py"),
    ("services_package_init", "v2/backend/app/services/__init__.py"),
    (
        "native_trainer_package_init",
        "v2/backend/app/services/native_trainer/__init__.py",
    ),
    (
        "ohlcv_closed_window_validator",
        "v2/backend/app/services/native_trainer/ohlcv_closed_window_schema.py",
    ),
    (
        "feature_window_dependency_contract",
        "v2/backend/app/services/native_trainer/feature_window_dependency_contract.py",
    ),
    (
        "source_read_receipt_v4",
        "v2/backend/app/services/native_trainer/source_read_receipt_v4.py",
    ),
    (
        "immutable_source_payload_store",
        "v2/backend/app/services/native_trainer/immutable_source_payload_store.py",
    ),
    (
        "immutable_source_payload_reader_v4",
        "v2/backend/app/services/native_trainer/immutable_source_payload_reader_v4.py",
    ),
    (
        "atomic_redis_source_reader",
        "v2/backend/app/services/native_trainer/atomic_redis_source_reader.py",
    ),
    (
        "canonical_ohlcv_atomic_receipt_adapter",
        "v2/backend/app/services/native_trainer/canonical_ohlcv_atomic_receipt_adapter.py",
    ),
    (
        "canonical_ohlcv_manifest_semantic_replay_v4",
        "v2/backend/app/services/native_trainer/canonical_ohlcv_manifest_semantic_replay_v4.py",
    ),
    (
        "canonical_ohlcv_hermetic_replay_protocol_v4",
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
    ),
    (
        "canonical_ohlcv_hermetic_replay_policy_v4",
        "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_policy_v4.py",
    ),
    (
        "canonical_ohlcv_hermetic_replay_worker_v4",
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    ),
)

_PINNED_CODE_SHA256_BY_ROLE: MappingProxyType[str, str] = MappingProxyType(
    {
        "canonical_ohlcv_hermetic_replay_protocol_v4": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
        )
    }
)

_RESOURCE_CEILINGS: MappingProxyType[str, int] = MappingProxyType(
    {
        "max_policy_document_bytes": MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4,
        "max_request_bytes": 64 * 1024,
        "max_result_bytes": 64 * 1024,
        "max_manifest_bytes": 8 * 1024 * 1024,
        "max_source_payload_bytes": 1 * 1024 * 1024,
        "max_row_payload_bytes": 64 * 1024,
        "max_selected_rows": 1500,
        "max_code_file_bytes": 2 * 1024 * 1024,
        "max_code_closure_bytes": 32 * 1024 * 1024,
        "max_python_executable_bytes": 64 * 1024 * 1024,
        "read_chunk_bytes": 1024 * 1024,
        "cpu_time_seconds": 30,
        "wall_time_milliseconds": 45 * 1000,
        "address_space_bytes": 2 * 1024 * 1024 * 1024,
        "open_file_descriptors": 32,
        "process_count": 1,
        "max_stdout_bytes": 64 * 1024,
        "max_stderr_bytes": 64 * 1024,
        "max_file_write_bytes": 0,
        "max_network_sockets": 0,
    }
)

_FALSE_AUTHORITY_FIELDS = (
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
)
_AUTHORITY_POLICY: MappingProxyType[str, bool] = MappingProxyType(
    {field: False for field in _FALSE_AUTHORITY_FIELDS}
)

_FileFingerprint: TypeAlias = tuple[int, int, int, int, int, int, int, int]
_DirectoryFingerprint: TypeAlias = tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _PythonFilesystemVerification:
    absolute_path: str
    executable_sha256: str
    declared_identity_sha256: str
    fingerprint: _FileFingerprint


@dataclass(frozen=True, slots=True)
class _CasRootFilesystemVerification:
    absolute_path: str
    fingerprint: _DirectoryFingerprint


@dataclass(frozen=True, slots=True)
class _CodeClosureFilesystemVerification:
    closure_sha256: str
    worker_policy_closure_sha256: str
    total_bytes: int
    project_root_fingerprint: _DirectoryFingerprint
    ordered_code_files: tuple[tuple[str, str, _FileFingerprint], ...]
    ordered_code_directories: tuple[tuple[str, _DirectoryFingerprint], ...]


@dataclass(frozen=True, slots=True)
class _LocalIdentityVerificationPass:
    python: _PythonFilesystemVerification
    cas_root: _CasRootFilesystemVerification
    code_closure: _CodeClosureFilesystemVerification


class CanonicalOhlcvHermeticReplayPolicyV4Error(RuntimeError):
    """A bounded policy or its pinned local identity failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(reason: str) -> NoReturn:
    raise CanonicalOhlcvHermeticReplayPolicyV4Error(reason) from None


def _reject_json_constant(_value: str) -> NoReturn:
    _fail("hermetic_replay_policy_json_constant_forbidden")


def _reject_json_float(_value: str) -> NoReturn:
    _fail("hermetic_replay_policy_json_float_forbidden")


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        _fail("hermetic_replay_policy_json_integer_out_of_range")
    try:
        parsed = int(value)
    except ValueError:
        _fail("hermetic_replay_policy_json_integer_out_of_range")
    if not MIN_HERMETIC_POLICY_INTEGER_V4 <= parsed <= MAX_HERMETIC_POLICY_INTEGER_V4:
        _fail("hermetic_replay_policy_json_integer_out_of_range")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("hermetic_replay_policy_duplicate_json_key")
        result[key] = value
    return result


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
            if depth > MAX_HERMETIC_POLICY_JSON_DEPTH_V4:
                _fail("hermetic_replay_policy_json_depth_limit_exceeded")
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("hermetic_replay_policy_json_invalid")


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
        _fail("hermetic_replay_policy_canonicalization_failed")


def _bounded_json_tree(value: object) -> None:
    nodes = 0
    total_text_bytes = 0

    def inspect(item: object, *, depth: int) -> None:
        nonlocal nodes, total_text_bytes
        nodes += 1
        if nodes > MAX_HERMETIC_POLICY_JSON_NODES_V4:
            _fail("hermetic_replay_policy_json_node_limit_exceeded")
        if depth > MAX_HERMETIC_POLICY_JSON_DEPTH_V4:
            _fail("hermetic_replay_policy_json_depth_limit_exceeded")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > MAX_HERMETIC_POLICY_CONTAINER_ITEMS_V4:
                _fail("hermetic_replay_policy_json_container_limit_exceeded")
            for key, child in mapping.items():
                if type(key) is not str:
                    _fail("hermetic_replay_policy_json_key_invalid")
                try:
                    encoded = key.encode("ascii", errors="strict")
                except UnicodeEncodeError:
                    _fail("hermetic_replay_policy_non_ascii_text_forbidden")
                if not encoded or len(encoded) > MAX_HERMETIC_POLICY_STRING_BYTES_V4:
                    _fail("hermetic_replay_policy_json_key_invalid")
                total_text_bytes += len(encoded)
                if total_text_bytes > MAX_HERMETIC_POLICY_TEXT_BYTES_V4:
                    _fail("hermetic_replay_policy_json_text_limit_exceeded")
                inspect(child, depth=depth + 1)
            return
        if type(item) is list:
            sequence = cast(list[object], item)
            if len(sequence) > MAX_HERMETIC_POLICY_CONTAINER_ITEMS_V4:
                _fail("hermetic_replay_policy_json_container_limit_exceeded")
            for child in sequence:
                inspect(child, depth=depth + 1)
            return
        if type(item) is str:
            try:
                encoded = item.encode("ascii", errors="strict")
            except UnicodeEncodeError:
                _fail("hermetic_replay_policy_non_ascii_text_forbidden")
            if len(encoded) > MAX_HERMETIC_POLICY_STRING_BYTES_V4:
                _fail("hermetic_replay_policy_json_string_limit_exceeded")
            total_text_bytes += len(encoded)
            if total_text_bytes > MAX_HERMETIC_POLICY_TEXT_BYTES_V4:
                _fail("hermetic_replay_policy_json_text_limit_exceeded")
        elif type(item) is int:
            if not MIN_HERMETIC_POLICY_INTEGER_V4 <= item <= MAX_HERMETIC_POLICY_INTEGER_V4:
                _fail("hermetic_replay_policy_json_integer_out_of_range")
        elif type(item) is bool or item is None:
            pass
        else:
            _fail("hermetic_replay_policy_json_primitive_type_invalid")
        if total_text_bytes > MAX_HERMETIC_POLICY_TEXT_BYTES_V4:
            _fail("hermetic_replay_policy_json_text_limit_exceeded")

    inspect(value, depth=1)


def _parse_policy_document(policy_document: object) -> tuple[dict[str, object], bytes]:
    if type(policy_document) is not bytes:
        _fail("hermetic_replay_policy_exact_bytes_required")
    document = policy_document
    if not 1 <= len(document) <= MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4:
        _fail("hermetic_replay_policy_document_size_invalid")
    _preflight_json_depth(document)
    try:
        parsed = json.loads(
            document,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except CanonicalOhlcvHermeticReplayPolicyV4Error:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, ValueError):
        _fail("hermetic_replay_policy_json_invalid")
    _bounded_json_tree(parsed)
    if type(parsed) is not dict:
        _fail("hermetic_replay_policy_object_required")
    canonical = _canonical_json_bytes(parsed)
    if not hmac.compare_digest(canonical, document):
        _fail("hermetic_replay_policy_noncanonical_json")
    return cast(dict[str, object], parsed), canonical


def _require_fields(value: object, expected: frozenset[str], *, reason: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[str, object], value)
    if frozenset(mapping) != expected:
        _fail(reason)
    return mapping


def _require_exact(value: object, expected: object, *, reason: str) -> None:
    def exact_equal(candidate: object, required: object) -> bool:
        if type(candidate) is not type(required):
            return False
        if type(candidate) is dict:
            candidate_mapping = cast(dict[object, object], candidate)
            required_mapping = cast(dict[object, object], required)
            return candidate_mapping.keys() == required_mapping.keys() and all(
                exact_equal(candidate_mapping[key], required_mapping[key])
                for key in required_mapping
            )
        if type(candidate) is list:
            candidate_list = cast(list[object], candidate)
            required_list = cast(list[object], required)
            return len(candidate_list) == len(required_list) and all(
                exact_equal(left, right)
                for left, right in zip(candidate_list, required_list, strict=True)
            )
        return candidate == required

    if not exact_equal(value, expected):
        _fail(reason)


def _require_token(value: object, *, version: bool, reason: str) -> str:
    pattern = _VERSION_RE if version else _TOKEN_RE
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(reason)
    return value


def _require_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _require_nonnegative_int(value: object, *, reason: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_HERMETIC_POLICY_INTEGER_V4:
        _fail(reason)
    return value


def _validated_absolute_path(value: object, *, reason: str) -> str:
    if type(value) is not str:
        _fail(reason)
    raw = value
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(reason)
    if (
        not encoded
        or len(encoded) > MAX_HERMETIC_POLICY_PATH_BYTES_V4
        or "\x00" in raw
        or not raw.startswith("/")
        or raw == "/"
        or raw.endswith("/")
    ):
        _fail(reason)
    components = raw.split("/")[1:]
    if not components or any(component in {"", ".", ".."} for component in components):
        _fail(reason)
    if os.path.normpath(raw) != raw:
        _fail(reason)
    return raw


def _mode_text(mode: int) -> str:
    return f"0{stat.S_IMODE(mode):03o}"


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


def _directory_fingerprint(value: os.stat_result) -> _DirectoryFingerprint:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_nlink),
    )


def _secure_directory_fingerprint(
    value: os.stat_result,
    *,
    expected_owner_uid: int,
    required_mode_octal: str | None,
    reason: str,
) -> _DirectoryFingerprint:
    mode = stat.S_IMODE(value.st_mode)
    if (
        not stat.S_ISDIR(value.st_mode)
        or int(value.st_uid) != expected_owner_uid
        or mode & 0o022 != 0
        or required_mode_octal is not None
        and _mode_text(value.st_mode) != required_mode_octal
    ):
        _fail(reason)
    return _directory_fingerprint(value)


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if not nofollow or not directory or not cloexec:
        _fail("hermetic_replay_policy_platform_path_guards_unavailable")
    return os.O_RDONLY | nofollow | directory | cloexec


def _file_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not cloexec or not nonblock:
        _fail("hermetic_replay_policy_platform_path_guards_unavailable")
    return os.O_RDONLY | nofollow | cloexec | nonblock


def _close_descriptor(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        _fail("hermetic_replay_policy_descriptor_close_failed")


def _open_directory_chain(absolute_path: str) -> int:
    descriptor = -1
    try:
        descriptor = os.open("/", _directory_flags())
        if absolute_path == "/":
            return descriptor
        for component in absolute_path.split("/")[1:]:
            next_descriptor = -1
            try:
                path_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                next_descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
                opened_stat = os.fstat(next_descriptor)
            except (FileNotFoundError, NotADirectoryError, OSError):
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_policy_directory_identity_invalid")
            if (
                not stat.S_ISDIR(path_stat.st_mode)
                or not stat.S_ISDIR(opened_stat.st_mode)
                or _directory_fingerprint(path_stat) != _directory_fingerprint(opened_stat)
            ):
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_policy_directory_identity_invalid")
            _close_descriptor(descriptor)
            descriptor = next_descriptor
        return descriptor
    except CanonicalOhlcvHermeticReplayPolicyV4Error:
        if descriptor >= 0:
            _close_descriptor(descriptor)
        raise


def _open_relative_parent(
    root_descriptor: int,
    relative_path: str,
    *,
    expected_owner_uid: int,
) -> tuple[int, str, tuple[tuple[str, _DirectoryFingerprint], ...]]:
    components = relative_path.split("/")
    if not components or any(component in {"", ".", ".."} for component in components):
        _fail("hermetic_replay_policy_code_path_invalid")
    try:
        descriptor = os.dup(root_descriptor)
    except OSError:
        _fail("hermetic_replay_policy_descriptor_dup_failed")
    traversed: list[tuple[str, _DirectoryFingerprint]] = []
    traversed_components: list[str] = []
    try:
        for component in components[:-1]:
            next_descriptor = -1
            try:
                path_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                next_descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
                opened_stat = os.fstat(next_descriptor)
            except (FileNotFoundError, NotADirectoryError, OSError):
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_policy_code_path_identity_invalid")
            try:
                path_fingerprint = _secure_directory_fingerprint(
                    path_stat,
                    expected_owner_uid=expected_owner_uid,
                    required_mode_octal=None,
                    reason="hermetic_replay_policy_code_directory_identity_invalid",
                )
                opened_fingerprint = _secure_directory_fingerprint(
                    opened_stat,
                    expected_owner_uid=expected_owner_uid,
                    required_mode_octal=None,
                    reason="hermetic_replay_policy_code_directory_identity_invalid",
                )
            except CanonicalOhlcvHermeticReplayPolicyV4Error:
                _close_descriptor(next_descriptor)
                raise
            if path_fingerprint != opened_fingerprint:
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_policy_code_path_identity_invalid")
            traversed_components.append(component)
            traversed.append(("/".join(traversed_components), opened_fingerprint))
            _close_descriptor(descriptor)
            descriptor = next_descriptor
        return descriptor, components[-1], tuple(traversed)
    except CanonicalOhlcvHermeticReplayPolicyV4Error:
        _close_descriptor(descriptor)
        raise


def _open_absolute_file_parent(absolute_path: str) -> tuple[int, str]:
    parent, filename = absolute_path.rsplit("/", 1)
    if not filename:
        _fail("hermetic_replay_policy_python_path_invalid")
    if not parent:
        parent = "/"
    return _open_directory_chain(parent), filename


def _hash_stable_regular_file(
    parent_descriptor: int,
    filename: str,
    *,
    expected_byte_count: int,
    maximum_byte_count: int,
    expected_owner_uid: int,
    expected_mode_octal: str | None,
    reason_prefix: str,
) -> tuple[str, _FileFingerprint]:
    descriptor = -1
    try:
        try:
            path_stat = os.stat(filename, dir_fd=parent_descriptor, follow_symlinks=False)
            descriptor = os.open(filename, _file_flags(), dir_fd=parent_descriptor)
            initial = os.fstat(descriptor)
        except (FileNotFoundError, NotADirectoryError, OSError):
            _fail(f"{reason_prefix}_identity_invalid")
        path_fingerprint = _file_fingerprint(path_stat)
        initial_fingerprint = _file_fingerprint(initial)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(initial.st_mode)
            or int(initial.st_nlink) != 1
            or int(initial.st_uid) != expected_owner_uid
            or stat.S_IMODE(initial.st_mode) & 0o022 != 0
            or path_fingerprint != initial_fingerprint
            or int(initial.st_size) != expected_byte_count
            or not 0 <= expected_byte_count <= maximum_byte_count
        ):
            _fail(f"{reason_prefix}_identity_invalid")
        if expected_mode_octal is not None and _mode_text(initial.st_mode) != expected_mode_octal:
            _fail(f"{reason_prefix}_identity_invalid")

        hasher = hashlib.sha256()
        remaining = expected_byte_count
        offset = 0
        chunk_ceiling = _RESOURCE_CEILINGS["read_chunk_bytes"]
        while remaining:
            try:
                chunk = os.pread(descriptor, min(remaining, chunk_ceiling), offset)
            except OSError:
                _fail(f"{reason_prefix}_read_failed")
            if not chunk:
                _fail(f"{reason_prefix}_read_failed")
            hasher.update(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
        try:
            if os.pread(descriptor, 1, expected_byte_count):
                _fail(f"{reason_prefix}_changed_during_read")
            final = os.fstat(descriptor)
            final_path = os.stat(filename, dir_fd=parent_descriptor, follow_symlinks=False)
        except OSError:
            _fail(f"{reason_prefix}_changed_during_read")
        final_fingerprint = _file_fingerprint(final)
        final_path_fingerprint = _file_fingerprint(final_path)
        if initial_fingerprint != final_fingerprint or final_path_fingerprint != final_fingerprint:
            _fail(f"{reason_prefix}_changed_during_read")
        return hasher.hexdigest(), final_fingerprint
    finally:
        _close_descriptor(descriptor)


def _domain_hash(domain: bytes, material: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(material)).hexdigest()


def _validate_python_runtime(
    value: object,
    *,
    max_executable_bytes: int,
) -> _PythonFilesystemVerification:
    runtime = _require_fields(
        value,
        _PYTHON_RUNTIME_FIELDS,
        reason="hermetic_replay_policy_python_runtime_fields_invalid",
    )
    _require_exact(
        runtime["identity_schema_version"],
        "canonical_ohlcv_hermetic_python_identity_v4",
        reason="hermetic_replay_policy_python_identity_schema_invalid",
    )
    absolute_path = _validated_absolute_path(
        runtime["absolute_path"], reason="hermetic_replay_policy_python_path_invalid"
    )
    _require_exact(
        runtime["implementation"],
        "CPython",
        reason="hermetic_replay_policy_python_implementation_invalid",
    )
    _require_token(
        runtime["version"],
        version=True,
        reason="hermetic_replay_policy_python_version_invalid",
    )
    _require_exact(
        runtime["isolated_flags"],
        ["-I", "-S", "-B"],
        reason="hermetic_replay_policy_python_flags_invalid",
    )
    owner_uid = _require_nonnegative_int(
        runtime["owner_uid"], reason="hermetic_replay_policy_python_owner_invalid"
    )
    mode_octal = runtime["mode_octal"]
    if type(mode_octal) is not str or _MODE_RE.fullmatch(mode_octal) is None:
        _fail("hermetic_replay_policy_python_mode_invalid")
    parsed_mode = int(mode_octal, 8)
    if parsed_mode & 0o111 == 0 or parsed_mode & 0o022 != 0:
        _fail("hermetic_replay_policy_python_mode_invalid")
    byte_count = _require_nonnegative_int(
        runtime["executable_byte_count"],
        reason="hermetic_replay_policy_python_byte_count_invalid",
    )
    if not 1 <= byte_count <= max_executable_bytes:
        _fail("hermetic_replay_policy_python_byte_count_invalid")
    expected_executable_sha256 = _require_sha256(
        runtime["executable_sha256"],
        reason="hermetic_replay_policy_python_digest_invalid",
    )
    expected_identity_sha256 = _require_sha256(
        runtime["identity_sha256"],
        reason="hermetic_replay_policy_python_identity_digest_invalid",
    )
    identity_material = {
        "absolute_path": absolute_path,
        "executable_byte_count": byte_count,
        "executable_sha256": expected_executable_sha256,
        "identity_schema_version": runtime["identity_schema_version"],
        "implementation": runtime["implementation"],
        "isolated_flags": runtime["isolated_flags"],
        "mode_octal": mode_octal,
        "owner_uid": owner_uid,
        "version": runtime["version"],
    }
    computed_identity_sha256 = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR,
        identity_material,
    )
    if not hmac.compare_digest(computed_identity_sha256, expected_identity_sha256):
        _fail("hermetic_replay_policy_python_identity_digest_mismatch")

    parent_descriptor, filename = _open_absolute_file_parent(absolute_path)
    try:
        actual_digest, fingerprint = _hash_stable_regular_file(
            parent_descriptor,
            filename,
            expected_byte_count=byte_count,
            maximum_byte_count=max_executable_bytes,
            expected_owner_uid=owner_uid,
            expected_mode_octal=mode_octal,
            reason_prefix="hermetic_replay_policy_python_executable",
        )
    finally:
        _close_descriptor(parent_descriptor)
    if not hmac.compare_digest(actual_digest, expected_executable_sha256):
        _fail("hermetic_replay_policy_python_executable_digest_mismatch")
    return _PythonFilesystemVerification(
        absolute_path=absolute_path,
        executable_sha256=actual_digest,
        declared_identity_sha256=computed_identity_sha256,
        fingerprint=fingerprint,
    )


def _validate_cas_root(value: object) -> _CasRootFilesystemVerification:
    cas = _require_fields(
        value,
        _CAS_ROOT_FIELDS,
        reason="hermetic_replay_policy_cas_root_fields_invalid",
    )
    absolute_path = _validated_absolute_path(
        cas["absolute_path"], reason="hermetic_replay_policy_cas_root_path_invalid"
    )
    owner_uid = _require_nonnegative_int(
        cas["owner_uid"], reason="hermetic_replay_policy_cas_root_owner_invalid"
    )
    _require_exact(
        cas["required_mode_octal"],
        "0700",
        reason="hermetic_replay_policy_cas_root_mode_invalid",
    )
    _require_exact(
        cas["namespace"],
        "sha256",
        reason="hermetic_replay_policy_cas_namespace_invalid",
    )
    _require_exact(
        cas["ownership_model"],
        "SOURCE_PROVENANCE_LEDGER_OWNED_IMMUTABLE_CAS_V1",
        reason="hermetic_replay_policy_cas_ownership_invalid",
    )
    _require_exact(
        cas["access_mode"],
        "READ_ONLY_HERMETIC_REPLAY",
        reason="hermetic_replay_policy_cas_access_invalid",
    )
    _require_exact(
        cas["request_selectable"],
        False,
        reason="hermetic_replay_policy_cas_request_selection_forbidden",
    )
    descriptor = _open_directory_chain(absolute_path)
    try:
        try:
            root_stat = os.fstat(descriptor)
        except OSError:
            _fail("hermetic_replay_policy_cas_root_identity_invalid")
        fingerprint = _secure_directory_fingerprint(
            root_stat,
            expected_owner_uid=owner_uid,
            required_mode_octal="0700",
            reason="hermetic_replay_policy_cas_root_identity_invalid",
        )
    finally:
        _close_descriptor(descriptor)
    return _CasRootFilesystemVerification(
        absolute_path=absolute_path,
        fingerprint=fingerprint,
    )


def _validate_code_closure(
    value: object,
    *,
    project_root: str,
    project_owner_uid: int,
    max_code_file_bytes: int,
    max_code_closure_bytes: int,
) -> _CodeClosureFilesystemVerification:
    if type(value) is not list:
        _fail("hermetic_replay_policy_code_closure_list_required")
    entries = cast(list[object], value)
    if len(entries) != len(PROJECT_CODE_CLOSURE_V4):
        _fail("hermetic_replay_policy_code_closure_incomplete")

    normalized: list[dict[str, object]] = []
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    worker_policy_closure_sha256: str | None = None
    for ordinal, raw_entry in enumerate(entries):
        entry = _require_fields(
            raw_entry,
            _CODE_CLOSURE_ENTRY_FIELDS,
            reason="hermetic_replay_policy_code_closure_entry_fields_invalid",
        )
        role = entry["role"]
        relative_path = entry["relative_path"]
        if type(role) is not str or type(relative_path) is not str:
            _fail("hermetic_replay_policy_code_closure_entry_identity_invalid")
        if role in seen_roles:
            _fail("hermetic_replay_policy_code_closure_duplicate_role")
        if relative_path in seen_paths:
            _fail("hermetic_replay_policy_code_closure_duplicate_path")
        seen_roles.add(role)
        seen_paths.add(relative_path)
        expected_role, expected_path = PROJECT_CODE_CLOSURE_V4[ordinal]
        _require_exact(
            entry["ordinal"],
            ordinal,
            reason="hermetic_replay_policy_code_closure_order_invalid",
        )
        _require_exact(
            role,
            expected_role,
            reason="hermetic_replay_policy_code_closure_role_invalid",
        )
        _require_exact(
            relative_path,
            expected_path,
            reason="hermetic_replay_policy_code_closure_path_invalid",
        )
        byte_count = _require_nonnegative_int(
            entry["byte_count"],
            reason="hermetic_replay_policy_code_closure_byte_count_invalid",
        )
        if not 0 <= byte_count <= max_code_file_bytes:
            _fail("hermetic_replay_policy_code_closure_byte_count_invalid")
        entry_sha256 = _require_sha256(
            entry["sha256"], reason="hermetic_replay_policy_code_closure_digest_invalid"
        )
        pinned_sha256 = _PINNED_CODE_SHA256_BY_ROLE.get(role)
        if pinned_sha256 is not None and not hmac.compare_digest(
            entry_sha256,
            pinned_sha256,
        ):
            _fail("hermetic_replay_policy_pinned_code_digest_mismatch")
        if role == "canonical_ohlcv_hermetic_replay_worker_v4":
            worker_policy_closure_sha256 = entry_sha256
        normalized.append(entry)

    if worker_policy_closure_sha256 is None:
        _fail("hermetic_replay_policy_worker_closure_entry_missing")

    root_descriptor = _open_directory_chain(project_root)
    total_bytes = 0
    inode_identities: set[tuple[int, int]] = set()
    ordered_files: list[tuple[str, str, _FileFingerprint]] = []
    observed_directories: dict[str, _DirectoryFingerprint] = {}
    try:
        try:
            root_stat = os.fstat(root_descriptor)
        except OSError:
            _fail("hermetic_replay_policy_project_root_identity_invalid")
        project_root_fingerprint = _secure_directory_fingerprint(
            root_stat,
            expected_owner_uid=project_owner_uid,
            required_mode_octal=None,
            reason="hermetic_replay_policy_project_root_identity_invalid",
        )
        for entry in normalized:
            relative_path = cast(str, entry["relative_path"])
            parent_descriptor, filename, directory_fingerprints = _open_relative_parent(
                root_descriptor,
                relative_path,
                expected_owner_uid=project_owner_uid,
            )
            try:
                for directory_path, directory_fingerprint in directory_fingerprints:
                    if (
                        directory_path in observed_directories
                        and observed_directories[directory_path] != directory_fingerprint
                    ):
                        _fail("hermetic_replay_policy_code_directory_changed_during_verification")
                    observed_directories[directory_path] = directory_fingerprint
                digest, file_fingerprint = _hash_stable_regular_file(
                    parent_descriptor,
                    filename,
                    expected_byte_count=cast(int, entry["byte_count"]),
                    maximum_byte_count=max_code_file_bytes,
                    expected_owner_uid=project_owner_uid,
                    expected_mode_octal=None,
                    reason_prefix="hermetic_replay_policy_code_file",
                )
            finally:
                _close_descriptor(parent_descriptor)
            inode_identity = (file_fingerprint[0], file_fingerprint[1])
            if inode_identity in inode_identities:
                _fail("hermetic_replay_policy_code_closure_duplicate_inode")
            inode_identities.add(inode_identity)
            if not hmac.compare_digest(digest, cast(str, entry["sha256"])):
                _fail("hermetic_replay_policy_code_file_digest_mismatch")
            ordered_files.append((relative_path, digest, file_fingerprint))
            total_bytes += cast(int, entry["byte_count"])
            if total_bytes > max_code_closure_bytes:
                _fail("hermetic_replay_policy_code_closure_size_exceeded")
        try:
            final_root_stat = os.fstat(root_descriptor)
        except OSError:
            _fail("hermetic_replay_policy_project_root_identity_invalid")
        if _directory_fingerprint(final_root_stat) != project_root_fingerprint:
            _fail("hermetic_replay_policy_project_root_changed_during_verification")
    finally:
        _close_descriptor(root_descriptor)
    return _CodeClosureFilesystemVerification(
        closure_sha256=_domain_hash(
            CANONICAL_OHLCV_HERMETIC_CODE_CLOSURE_V4_DOMAIN_SEPARATOR,
            normalized,
        ),
        worker_policy_closure_sha256=worker_policy_closure_sha256,
        total_bytes=total_bytes,
        project_root_fingerprint=project_root_fingerprint,
        ordered_code_files=tuple(ordered_files),
        ordered_code_directories=tuple(observed_directories.items()),
    )


def _verify_local_identity_pass(
    *,
    python_runtime: object,
    ledger_owned_cas_root: object,
    code_closure: object,
    project_root: str,
    project_owner_uid: int,
) -> _LocalIdentityVerificationPass:
    """Perform one complete, descriptor-safe validation-time snapshot."""

    python = _validate_python_runtime(
        python_runtime,
        max_executable_bytes=_RESOURCE_CEILINGS["max_python_executable_bytes"],
    )
    cas_root = _validate_cas_root(ledger_owned_cas_root)
    closure = _validate_code_closure(
        code_closure,
        project_root=project_root,
        project_owner_uid=project_owner_uid,
        max_code_file_bytes=_RESOURCE_CEILINGS["max_code_file_bytes"],
        max_code_closure_bytes=_RESOURCE_CEILINGS["max_code_closure_bytes"],
    )
    return _LocalIdentityVerificationPass(
        python=python,
        cas_root=cas_root,
        code_closure=closure,
    )


def validate_canonical_ohlcv_hermetic_replay_policy_v4(
    policy_document: object,
    *,
    expected_policy_sha256: object,
    expected_registry_id: object,
    expected_registry_version: object,
    expected_policy_id: object,
    expected_policy_revision: object,
) -> MappingProxyType[str, object]:
    """Validate one policy against separate expected values and local files.

    All ``expected_*`` values are verifier inputs that a future service must
    obtain outside replay request JSON.  The expected policy digest binds the
    worker digest declared by the policy closure.  This validator does not
    authenticate that external source or channel, is deliberately unwired,
    and grants no downstream authority.
    """

    expected_digest = _require_sha256(
        expected_policy_sha256, reason="hermetic_replay_policy_expected_digest_invalid"
    )
    expected_registry = _require_token(
        expected_registry_id,
        version=False,
        reason="hermetic_replay_policy_expected_registry_id_invalid",
    )
    expected_registry_ver = _require_token(
        expected_registry_version,
        version=True,
        reason="hermetic_replay_policy_expected_registry_version_invalid",
    )
    expected_id = _require_token(
        expected_policy_id,
        version=False,
        reason="hermetic_replay_policy_expected_policy_id_invalid",
    )
    if type(expected_policy_revision) is not int or expected_policy_revision < 1:
        _fail("hermetic_replay_policy_expected_revision_invalid")

    policy, canonical_document = _parse_policy_document(policy_document)
    _require_fields(
        policy,
        _POLICY_FIELDS,
        reason="hermetic_replay_policy_fields_invalid",
    )
    _require_exact(
        policy["schema_version"],
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
        reason="hermetic_replay_policy_schema_invalid",
    )
    _require_exact(
        policy["contract_version"],
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
        reason="hermetic_replay_policy_contract_invalid",
    )
    policy_id = _require_token(
        policy["policy_id"], version=False, reason="hermetic_replay_policy_id_invalid"
    )
    policy_revision = policy["policy_revision"]
    if type(policy_revision) is not int or policy_revision < 1:
        _fail("hermetic_replay_policy_revision_invalid")
    registry_id = _require_token(
        policy["registry_id"], version=False, reason="hermetic_replay_policy_registry_id_invalid"
    )
    registry_version = _require_token(
        policy["registry_version"],
        version=True,
        reason="hermetic_replay_policy_registry_version_invalid",
    )
    _require_exact(
        registry_id,
        expected_registry,
        reason="hermetic_replay_policy_registry_id_mismatch",
    )
    _require_exact(
        registry_version,
        expected_registry_ver,
        reason="hermetic_replay_policy_registry_version_mismatch",
    )
    _require_exact(policy_id, expected_id, reason="hermetic_replay_policy_id_mismatch")
    _require_exact(
        policy_revision,
        expected_policy_revision,
        reason="hermetic_replay_policy_revision_mismatch",
    )

    computed_policy_sha256 = hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR + canonical_document
    ).hexdigest()
    if not hmac.compare_digest(computed_policy_sha256, expected_digest):
        _fail("hermetic_replay_policy_digest_mismatch")

    _require_exact(
        policy["resource_ceilings"],
        dict(_RESOURCE_CEILINGS),
        reason="hermetic_replay_policy_resource_ceilings_invalid",
    )
    resource_sha256 = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_RESOURCE_POLICY_V4_DOMAIN_SEPARATOR,
        policy["resource_ceilings"],
    )
    _require_exact(
        policy["canonical_profile"],
        dict(_CANONICAL_PROFILE),
        reason="hermetic_replay_policy_canonical_profile_invalid",
    )
    _require_exact(
        policy["accepted_schemas"],
        dict(_ACCEPTED_SCHEMAS),
        reason="hermetic_replay_policy_accepted_schemas_invalid",
    )
    _require_exact(
        policy["worker"],
        dict(_WORKER_POLICY),
        reason="hermetic_replay_policy_worker_invalid",
    )
    _require_exact(
        policy["worker_protocol"],
        dict(_WORKER_PROTOCOL),
        reason="hermetic_replay_policy_worker_protocol_invalid",
    )
    _require_exact(
        policy["authority_policy"],
        dict(_AUTHORITY_POLICY),
        reason="hermetic_replay_policy_authority_escalation_forbidden",
    )
    _require_exact(policy["audit_only"], True, reason="hermetic_replay_policy_audit_only_required")

    project_root = _validated_absolute_path(
        policy["project_root"], reason="hermetic_replay_policy_project_root_path_invalid"
    )
    project_owner_uid = _require_nonnegative_int(
        policy["project_owner_uid"],
        reason="hermetic_replay_policy_project_owner_invalid",
    )
    first_pass = _verify_local_identity_pass(
        python_runtime=policy["python_runtime"],
        ledger_owned_cas_root=policy["ledger_owned_cas_root"],
        code_closure=policy["code_closure"],
        project_root=project_root,
        project_owner_uid=project_owner_uid,
    )
    second_pass = _verify_local_identity_pass(
        python_runtime=policy["python_runtime"],
        ledger_owned_cas_root=policy["ledger_owned_cas_root"],
        code_closure=policy["code_closure"],
        project_root=project_root,
        project_owner_uid=project_owner_uid,
    )
    if first_pass != second_pass:
        _fail("hermetic_replay_policy_local_identity_changed_between_verification_passes")

    result: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION,
        "policy_schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
        "policy_id": policy_id,
        "policy_revision": policy_revision,
        "registry_id": registry_id,
        "registry_version": registry_version,
        "policy_sha256": computed_policy_sha256,
        "policy_byte_count": len(canonical_document),
        "project_root": project_root,
        "project_owner_uid": project_owner_uid,
        "python_absolute_path": second_pass.python.absolute_path,
        "python_executable_sha256": second_pass.python.executable_sha256,
        "declared_python_identity_sha256": second_pass.python.declared_identity_sha256,
        "ledger_owned_cas_root": second_pass.cas_root.absolute_path,
        "canonical_profile_id": _CANONICAL_PROFILE["profile_id"],
        "worker_relative_path": _WORKER_POLICY["relative_path"],
        "worker_entrypoint": _WORKER_POLICY["entrypoint"],
        "worker_invocation_mode": _WORKER_POLICY["invocation_mode"],
        "worker_policy_closure_sha256": (second_pass.code_closure.worker_policy_closure_sha256),
        "hermetic_replay_protocol_relative_path": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
        ),
        "hermetic_replay_protocol_sha256": (CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256),
        "runtime_network_disable_required": True,
        "runtime_filesystem_write_disable_required": True,
        "code_closure_sha256": second_pass.code_closure.closure_sha256,
        "code_closure_entry_count": len(PROJECT_CODE_CLOSURE_V4),
        "code_closure_total_bytes": second_pass.code_closure.total_bytes,
        "resource_policy_sha256": resource_sha256,
        "expected_policy_digest_matched_at_validation": True,
        "expected_registry_coordinates_matched_at_validation": True,
        "python_executable_bytes_and_metadata_verified_at_validation": True,
        "ledger_cas_root_path_metadata_verified_at_validation": True,
        "project_root_path_metadata_verified_at_validation": True,
        "ordered_code_files_verified_at_validation": True,
        "worker_code_file_verified_at_validation": True,
        "frozen_protocol_code_file_verified_at_validation": True,
        "two_local_filesystem_verification_passes_matched_at_validation": True,
        "local_filesystem_verification_pass_count": 2,
        "request_policy_selection_allowed": False,
        "audit_only": True,
        **_AUTHORITY_POLICY,
    }
    if any(type(value) not in {str, int, bool} for value in result.values()):
        _fail("hermetic_replay_policy_result_scalar_contract_failed")
    return MappingProxyType(dict(result))


__all__ = [
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH",
    "CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR",
    "CanonicalOhlcvHermeticReplayPolicyV4Error",
    "MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4",
    "PROJECT_CODE_CLOSURE_V4",
    "validate_canonical_ohlcv_hermetic_replay_policy_v4",
]
