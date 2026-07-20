"""Dormant, audit-only process boundary for canonical OHLCV replay.

This file is an absolute-path script, not an importable trainer service.  Its
bootstrap imports only the standard library.  Before any project package can
be imported it requires CPython ``-I -S -B``, derives the repository root from
its exact absolute ``__file__``, descriptor-reads the frozen protocol and
policy sources, verifies their compiled-in digests, and executes those exact
captured bytes as private importlib modules without importing package init
files.

The separately supplied policy channel must be a read-only Linux memfd with
all immutable seals (WRITE, GROW, SHRINK, and SEAL).  Sealing establishes only
stable bytes for this process.  It does not authenticate who created those
bytes or the policy they contain.  The replay request is separately read from
stdin.  Both transports are bounded before their strict canonical validators
run.

Only after the frozen policy validator has reopened and verified its complete
declared project-code closure does this worker descriptor-capture every
declared source.  Package initializers are verified but never executed;
synthetic package shells and a strict meta-path finder execute only the exact
captured dependency bytes and reject every undeclared ``v2.*`` import.  The
project root is never added to ``sys.path``.  A separate standard-library-only
oracle reopens the manifest and requested row CAS objects and binds the
selected result to their exact semantics and point-in-time clocks.

Success emits one bounded canonical scalar JSON result.  It remains audit-only
and grants no feature, trainer, prediction, paper-trading, or live-execution
authority.  This worker does not claim a complete runtime dependency closure,
network or filesystem sandbox, systemd enforcement, durable policy
provenance, or runtime wiring.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import importlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, ModuleType
from typing import Any, NoReturn, cast

CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_result_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_ERROR_V4_SCHEMA_VERSION = "canonical_ohlcv_hermetic_replay_error_v4"
CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION = (
    "canonical_ohlcv_hermetic_replay_protocol_contract_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_request_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_channel_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_v4"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_VALIDATION_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_hermetic_replay_policy_validation_v4"
)
CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_SCHEMA_VERSION = "canonical_ohlcv_selected_row_binding_v4"
CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_HASH_DOMAIN = (
    "canonical_ohlcv_selected_row_binding_v4/result_sha256/v1"
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
CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_DOMAIN_SEPARATOR = (
    CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_HASH_DOMAIN.encode("ascii") + b"\0"
)

CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_protocol_v4.py"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256 = (
    "055794d2fc9d1ce6c2c5383a6f73a24ca403abb47cbbcb14d252b62a108fdee9"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_policy_v4.py"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256 = (
    "e75b3a9c17980d4d04ab7b0e3fd675ae5d73da19e73e9421fd684bd7a4a54a7e"
)
CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_worker_v4.py"
)
CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_manifest_semantic_replay_v4.py"
)

MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4 = 192 * 1024
MAX_HERMETIC_REPLAY_RESULT_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_ERROR_BYTES_V4 = 2048
MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4 = 8 * 1024 * 1024
MAX_HERMETIC_REPLAY_FULL_SOURCE_BYTES_V4 = 1 * 1024 * 1024
MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4 = 64 * 1024
MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4 = 2 * 1024 * 1024
MAX_HERMETIC_REPLAY_PYTHON_EXECUTABLE_BYTES_V4 = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.ASCII)
_REASON_RE = re.compile(r"^[a-z0-9_]{1,192}$", re.ASCII)
_FileFingerprint = tuple[int, int, int, int, int, int, int, int]

_SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION = "source_payload_content_address_v1"
_SELECTED_ROW_EVIDENCE_CLASSIFICATION = (
    "UNIQUE_MANIFEST_MEMBER_SELECTED_ROW_CAS_SEMANTIC_AUDIT_ONLY"
)
_SELECTED_ROW_DOWNSTREAM_STATUS = (
    "NO_FACTORY_UPSTREAM_TRANSPORT_LEDGER_DEPENDENCY_FEATURE_TRAINER_OR_EXECUTION_AUTHORITY"
)
_BASE_REPLAY_SCHEMA_VERSION = "canonical_ohlcv_manifest_semantic_replay_v4"
_BASE_REPLAY_EVIDENCE_CLASSIFICATION = "CAS_REOPENED_CANONICAL_OHLCV_MANIFEST_SEMANTIC_AUDIT_ONLY"
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SIGNED_64 = (1 << 63) - 1
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 250_000
_MAX_JSON_CONTAINER_ITEMS = 4096
_MAX_JSON_TEXT_BYTES = MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4
_TIMEFRAME_DURATION_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}

_MANIFEST_SCHEMA_VERSION = "canonical_ohlcv_suffix_manifest_v1"
_MANIFEST_EVIDENCE_CLASSIFICATION = (
    "ATOMIC_EXACT_CANONICAL_OHLCV_SELECTED_SUFFIX_CAS_V4_RECEIPTS_UNWIRED"
)
_MANIFEST_DOWNSTREAM_STATUS = (
    "NO_LEDGER_APPEND_FEATURE_PUBLICATION_TRAINER_OR_EXECUTION_AUTHORIZATION"
)
_SOURCE_RECEIPT_SCHEMA_VERSION = "feature_source_consumer_read_receipt_v4"
_SOURCE_RECEIPT_EVIDENCE_CLASSIFICATION = (
    "TRUTHFUL_CLOSED_INTERVAL_SOURCE_RECEIPT_V4_STANDALONE_UNWIRED"
)
_SOURCE_RECEIPT_DOWNSTREAM_STATUS = (
    "NO_LEDGER_APPEND_FEATURE_PUBLICATION_TRAINER_OR_EXECUTION_AUTHORIZATION"
)
_SOURCE_READ_EVIDENCE_SCHEMA_VERSION = "feature_source_exact_read_evidence_v4"
_SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION = "feature_source_finality_evidence_v4"
_SOURCE_READ_LOCATOR_SCHEMA_VERSION = "feature_source_read_locator_v4"
_SOURCE_PAYLOAD_TYPE = "EXACT_CANONICAL_CLOSED_OHLCV_ROW_BYTES"
_SOURCE_FINALITY_VERIFIER = "trainer-canonical-ohlcv-atomic-adapter-v1"

_OHLCV_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)
_OHLCV_ROW_FIELDS = frozenset(
    {
        "symbol",
        "exchange",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "event_time",
        "ingested_at",
        "available_at",
        "is_closed",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "ohlcv",
        "is_backfilled",
        "feature_eligible",
        "candle_id",
        "open_time",
        "close_time",
        "ts",
        "closed_candle",
        "candle_closed_confirmed",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)
_MANIFEST_SELECTED_ROW_FIELDS = frozenset(
    {
        "selected_ordinal",
        "source_index",
        "byte_start",
        "byte_end_exclusive",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "source_payload_cas_address",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "producer_event_time_ms",
        "ingested_at_ms",
        "available_at_ms",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "is_backfilled",
        "source_read_receipt_v4",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "source_key",
        "source_key_sha256",
        "source_key_version",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "atomic_batch_material_json",
        "atomic_server_time_seconds",
        "atomic_server_time_microseconds",
        "atomic_server_observed_at",
        "source_pttl_ms",
        "consumer_observed_at",
        "consumer_observed_at_ms",
        "full_source_payload_cas_address",
        "raw_row_count",
        "source_gap_indices",
        "source_gap_missing_interval_counts",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_row_count",
        "excluded_prefix_row_count",
        "excluded_prefix_gap_indices",
        "excluded_prefix_gap_missing_interval_counts",
        "selected_internal_gap_indices",
        "tail_missing_interval_count",
        "latest_candle_matches_expected_cutoff",
        "binding_selection_sha256",
        "selected_candle_id_chain_sha256",
        "suffix_digest_material_json",
        "suffix_digest_sha256",
        "selected_rows",
        "durable_ledger_appended",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    }
)
_SOURCE_RECEIPT_FALSE_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_SOURCE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "receipt_kind",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "read_evidence",
        "read_evidence_sha256",
        "read_locator_sha256",
        "finality_evidence",
        "finality_evidence_sha256",
        *_SOURCE_RECEIPT_FALSE_FIELDS,
        "receipt_sha256",
    }
)
_READ_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "read_locator_type",
        "read_locator",
        "read_locator_version",
        "read_locator_sha256",
        "read_completed_at",
    }
)
_FINALITY_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "read_evidence_sha256",
        "read_locator_sha256",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "finality_type",
        "event_final",
        "finality_cutoff",
        "finality_verified_at",
        "verifier",
    }
)

_POLICY_FALSE_FIELDS = (
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
_SEMANTIC_FALSE_FIELDS = (
    "factory_capture_authenticated",
    "factory_receipt_authenticated",
    "factory_authorized",
    "upstream_producer_authenticated",
    "atomic_transport_authenticated",
    "transport_authenticated",
    "transport_authenticity_attested",
    "source_attestation_authenticated",
    "ledger_authorized",
    "ledger_receipt_emitted",
    "durable_ledger_appended",
    "durable_ledger_membership_verified",
    "dependency_authorized",
    "dependency_manifest_bound",
    "dependency_complete",
    "per_field_receipt_bound",
    "source_scope_complete",
    "feature_authorized",
    "feature_snapshot_authorized",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)
_WORKER_FALSE_FIELDS = tuple(
    dict.fromkeys(
        (
            *_POLICY_FALSE_FIELDS,
            *_SEMANTIC_FALSE_FIELDS,
            "runtime_network_disabled",
            "runtime_filesystem_write_disabled",
            "systemd_unit_verified",
            "systemd_sandbox_enforced",
        )
    )
)
_SEMANTIC_TRUE_FIELDS = (
    "base_manifest_semantic_replay_verified",
    "manifest_independently_reopened",
    "selected_row_manifest_membership_unique",
    "selected_row_cas_reopened",
    "selected_row_payload_schema_replayed",
    "selected_row_identity_bound",
    "selected_row_source_read_receipt_revalidated",
    "decision_context_bound",
)
_BASE_REPLAY_TRUE_FIELDS = (
    "manifest_cas_reopened",
    "full_source_payload_cas_reopened",
    "every_selected_row_cas_reopened",
    "manifest_exact_canonical_json_verified",
    "content_addresses_recomputed",
    "exact_row_spans_recomputed",
    "committed_ohlcv_30_field_schema_replayed",
    "complete_contiguous_suffix_recomputed",
    "every_source_read_receipt_revalidated",
    "source_clocks_and_finality_recomputed",
    "decision_context_bound",
)

_BASE_REPLAY_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "manifest_sha256",
        "manifest_byte_count",
        "full_source_payload_sha256",
        "full_source_payload_byte_count",
        "source_key",
        "source_key_version",
        "symbol",
        "timeframe",
        "consumer_observed_at",
        "decision_time",
        "feature_cutoff",
        "generated_at",
        "execution_time",
        "raw_row_count",
        "selected_row_count",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "binding_selection_sha256",
        "decision_binding_selection_sha256",
        "selected_candle_id_chain_sha256",
        "suffix_digest_sha256",
        "source_read_receipt_chain_sha256",
        *_BASE_REPLAY_TRUE_FIELDS,
        *_SEMANTIC_FALSE_FIELDS,
        "audit_only",
        "semantic_replay_sha256",
    }
)

_SELECTED_ROW_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "base_replay_schema_version",
        "base_replay_sha256",
        "selected_row_binding_hash_domain",
        "manifest_sha256",
        "manifest_byte_count",
        "requested_selected_row_address_schema_version",
        "requested_selected_row_payload_sha256",
        "requested_selected_row_payload_byte_count",
        "requested_selected_row_cas_relative_path",
        "matched_selected_row_address_schema_version",
        "matched_selected_row_payload_sha256",
        "matched_selected_row_payload_byte_count",
        "matched_selected_row_cas_relative_path",
        "symbol",
        "timeframe",
        "matched_selected_ordinal",
        "matched_source_index",
        "matched_byte_start",
        "matched_byte_end_exclusive",
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
        *_SEMANTIC_TRUE_FIELDS,
        *_SEMANTIC_FALSE_FIELDS,
        "audit_only",
        "selected_row_binding_sha256",
    }
)


class CanonicalOhlcvHermeticReplayWorkerV4Error(RuntimeError):
    """A stable, fail-closed worker boundary failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    if _REASON_RE.fullmatch(reason) is None:
        reason = "hermetic_replay_worker_internal_failure"
    raise CanonicalOhlcvHermeticReplayWorkerV4Error(reason) from None


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
        _fail("hermetic_replay_worker_canonicalization_failed")


def _domain_hash(domain_separator: bytes, material: object) -> str:
    return hashlib.sha256(domain_separator + _canonical_json_bytes(material)).hexdigest()


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


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if not nofollow or not directory or not cloexec:
        _fail("hermetic_replay_worker_platform_path_guards_unavailable")
    return os.O_RDONLY | nofollow | directory | cloexec


def _file_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not cloexec or not nonblock:
        _fail("hermetic_replay_worker_platform_path_guards_unavailable")
    return os.O_RDONLY | nofollow | cloexec | nonblock


def _close_descriptor(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        _fail("hermetic_replay_worker_descriptor_close_failed")


def _open_directory_chain(absolute_path: str) -> int:
    if (
        type(absolute_path) is not str
        or not absolute_path.startswith("/")
        or os.path.normpath(absolute_path) != absolute_path
        or absolute_path.endswith("/")
    ):
        _fail("hermetic_replay_worker_bootstrap_path_invalid")
    descriptor = -1
    try:
        descriptor = os.open("/", _directory_flags())
        for component in absolute_path.split("/")[1:]:
            if component in {"", ".", ".."}:
                _fail("hermetic_replay_worker_bootstrap_path_invalid")
            next_descriptor = -1
            try:
                path_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                next_descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
                opened_stat = os.fstat(next_descriptor)
            except OSError:
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_worker_bootstrap_path_identity_invalid")
            if (
                not stat.S_ISDIR(path_stat.st_mode)
                or not stat.S_ISDIR(opened_stat.st_mode)
                or _file_fingerprint(path_stat) != _file_fingerprint(opened_stat)
            ):
                _close_descriptor(next_descriptor)
                _fail("hermetic_replay_worker_bootstrap_path_identity_invalid")
            _close_descriptor(descriptor)
            descriptor = next_descriptor
        return descriptor
    except CanonicalOhlcvHermeticReplayWorkerV4Error:
        if descriptor >= 0:
            _close_descriptor(descriptor)
        raise


def _read_stable_relative_file(
    project_root: str,
    relative_path: str,
    *,
    maximum_byte_count: int,
    reason_prefix: str,
) -> tuple[bytes, str, _FileFingerprint]:
    components = relative_path.split("/")
    if (
        type(relative_path) is not str
        or relative_path.startswith("/")
        or not components
        or any(component in {"", ".", ".."} for component in components)
        or os.path.normpath(relative_path) != relative_path
    ):
        _fail(f"{reason_prefix}_path_invalid")
    descriptor = _open_directory_chain(project_root)
    try:
        for component in components[:-1]:
            next_descriptor = -1
            try:
                path_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                next_descriptor = os.open(component, _directory_flags(), dir_fd=descriptor)
                opened_stat = os.fstat(next_descriptor)
            except OSError:
                _close_descriptor(next_descriptor)
                _fail(f"{reason_prefix}_path_identity_invalid")
            if (
                not stat.S_ISDIR(path_stat.st_mode)
                or not stat.S_ISDIR(opened_stat.st_mode)
                or _file_fingerprint(path_stat) != _file_fingerprint(opened_stat)
            ):
                _close_descriptor(next_descriptor)
                _fail(f"{reason_prefix}_path_identity_invalid")
            _close_descriptor(descriptor)
            descriptor = next_descriptor

        file_descriptor = -1
        try:
            filename = components[-1]
            path_stat = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            file_descriptor = os.open(filename, _file_flags(), dir_fd=descriptor)
            initial_stat = os.fstat(file_descriptor)
            initial = _file_fingerprint(initial_stat)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or not stat.S_ISREG(initial_stat.st_mode)
                or _file_fingerprint(path_stat) != initial
                or int(initial_stat.st_nlink) != 1
                or not 0 <= int(initial_stat.st_size) <= maximum_byte_count
            ):
                _fail(f"{reason_prefix}_identity_invalid")
            chunks: list[bytes] = []
            offset = 0
            remaining = int(initial_stat.st_size)
            while remaining:
                try:
                    chunk = os.pread(file_descriptor, min(remaining, _READ_CHUNK_BYTES), offset)
                except OSError:
                    _fail(f"{reason_prefix}_read_failed")
                if not chunk:
                    _fail(f"{reason_prefix}_read_failed")
                chunks.append(chunk)
                offset += len(chunk)
                remaining -= len(chunk)
            try:
                overflow = os.pread(file_descriptor, 1, offset)
                final_stat = os.fstat(file_descriptor)
                final_path_stat = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                _fail(f"{reason_prefix}_changed_during_read")
            final = _file_fingerprint(final_stat)
            if overflow or initial != final or _file_fingerprint(final_path_stat) != final:
                _fail(f"{reason_prefix}_changed_during_read")
            payload = b"".join(chunks)
            return payload, hashlib.sha256(payload).hexdigest(), final
        except OSError:
            _fail(f"{reason_prefix}_identity_invalid")
        finally:
            _close_descriptor(file_descriptor)
    finally:
        _close_descriptor(descriptor)


def _read_stable_absolute_file(
    absolute_path: str,
    *,
    maximum_byte_count: int,
    reason_prefix: str,
) -> tuple[bytes, str, _FileFingerprint]:
    if (
        type(absolute_path) is not str
        or not absolute_path.startswith("/")
        or os.path.normpath(absolute_path) != absolute_path
        or absolute_path.endswith("/")
    ):
        _fail(f"{reason_prefix}_path_invalid")
    parent, filename = absolute_path.rsplit("/", 1)
    if not parent:
        parent = "/"
    return _read_stable_relative_file(
        parent,
        filename,
        maximum_byte_count=maximum_byte_count,
        reason_prefix=reason_prefix,
    )


class _ExactCapturedSourceLoader:
    """Loader that executes one already descriptor-verified source snapshot."""

    def __init__(self, source: bytes, path: str) -> None:
        self._source = source
        self._path = path

    def create_module(self, _spec: object) -> None:
        return None

    def get_filename(self, _fullname: str) -> str:
        return self._path

    def is_package(self, _fullname: str) -> bool:
        return False

    def exec_module(self, module: ModuleType) -> None:
        code = compile(self._source, self._path, "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102 - exact descriptor-verified frozen source


class _SyntheticPackageLoader:
    """Create an inert package shell without executing its captured initializer."""

    def __init__(self, fullname: str) -> None:
        self._fullname = fullname

    def create_module(self, _spec: object) -> None:
        return None

    def is_package(self, fullname: str) -> bool:
        return fullname == self._fullname

    def exec_module(self, module: ModuleType) -> None:
        if module.__name__ != self._fullname:
            _fail("hermetic_replay_worker_synthetic_package_identity_invalid")
        module.__path__ = []


class _ExactProjectClosureFinder:
    """Resolve only captured ``v2`` dependencies and reject every other one."""

    def __init__(
        self,
        *,
        sources: dict[str, tuple[bytes, str]],
        packages: set[str],
    ) -> None:
        self._sources = sources
        self._packages = packages
        self._loaders: dict[str, object] = {}

    @property
    def allowed_module_names(self) -> frozenset[str]:
        return frozenset((*self._sources, *self._packages))

    def find_spec(
        self,
        fullname: str,
        _path: object = None,
        _target: object = None,
    ) -> object:
        if fullname != "v2" and not fullname.startswith("v2."):
            return None
        if fullname in self._packages:
            package_loader = _SyntheticPackageLoader(fullname)
            self._loaders[fullname] = package_loader
            spec = importlib.util.spec_from_loader(
                fullname,
                cast(Any, package_loader),
                origin=f"hermetic-synthetic-package:{fullname}",
                is_package=True,
            )
            if spec is None:
                _fail("hermetic_replay_worker_project_module_spec_invalid")
            spec.submodule_search_locations = []
            return spec
        captured = self._sources.get(fullname)
        if captured is None:
            _fail("hermetic_replay_worker_undeclared_project_import_forbidden")
        source, path = captured
        source_loader = _ExactCapturedSourceLoader(source, path)
        self._loaders[fullname] = source_loader
        spec = importlib.util.spec_from_loader(
            fullname,
            cast(Any, source_loader),
            origin=path,
            is_package=False,
        )
        if spec is None:
            _fail("hermetic_replay_worker_project_module_spec_invalid")
        spec.has_location = True
        return spec

    def verify_loaded_modules(self) -> None:
        allowed = self.allowed_module_names
        loaded_names = {name for name in sys.modules if name == "v2" or name.startswith("v2.")}
        if not loaded_names.issubset(allowed):
            _fail("hermetic_replay_worker_undeclared_project_module_loaded")
        for name in loaded_names:
            module = sys.modules.get(name)
            if type(module) is not ModuleType or getattr(module, "__loader__", None) is not (
                self._loaders.get(name)
            ):
                _fail("hermetic_replay_worker_project_module_loader_identity_invalid")
            if name in self._sources:
                expected_path = self._sources[name][1]
                if getattr(module, "__file__", None) != expected_path:
                    _fail("hermetic_replay_worker_project_module_path_invalid")
            elif list(cast(Any, getattr(module, "__path__", None))) != []:
                _fail("hermetic_replay_worker_synthetic_package_path_invalid")


def _load_private_exact_module(*, name: str, path: str, source: bytes) -> ModuleType:
    if name in sys.modules:
        _fail("hermetic_replay_worker_private_module_collision")
    loader = _ExactCapturedSourceLoader(source, path)
    spec = importlib.util.spec_from_loader(name, cast(Any, loader), origin=path)
    if spec is None:
        _fail("hermetic_replay_worker_private_module_spec_invalid")
    module = importlib.util.module_from_spec(spec)
    module.__file__ = path
    sys.modules[name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        _fail("hermetic_replay_worker_frozen_module_load_failed")
    if module.__file__ != path or module.__package__ not in {None, ""}:
        _fail("hermetic_replay_worker_private_module_identity_invalid")
    return module


def _require_exact(value: object, expected: object, *, reason: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(reason)


def _require_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _verify_direct_isolated_invocation() -> tuple[str, str, int]:
    if __name__ != "__main__" or __package__ not in {None, ""} or __spec__ is not None:
        _fail("hermetic_replay_worker_direct_script_invocation_required")
    if (
        sys.flags.isolated != 1
        or sys.flags.no_site != 1
        or sys.flags.dont_write_bytecode != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_user_site != 1
        or sys.flags.safe_path is not True
        or sys.flags.optimize != 0
        or sys.flags.debug != 0
        or sys.flags.verbose != 0
        or sys.flags.inspect != 0
        or sys.flags.interactive != 0
        or sys.flags.bytes_warning != 0
        or sys.flags.quiet != 0
        or sys.dont_write_bytecode is not True
        or bool(sys._xoptions)
        or bool(sys.warnoptions)
    ):
        _fail("hermetic_replay_worker_isolated_python_flags_required")
    if len(sys.argv) != 3 or sys.argv[1] != "--policy-fd":
        _fail("hermetic_replay_worker_arguments_invalid")
    descriptor_text = sys.argv[2]
    if (
        not descriptor_text.isascii()
        or not descriptor_text.isdecimal()
        or descriptor_text.startswith("0")
    ):
        _fail("hermetic_replay_worker_policy_fd_invalid")
    policy_fd = int(descriptor_text)
    if policy_fd < 3 or str(policy_fd) != descriptor_text:
        _fail("hermetic_replay_worker_policy_fd_invalid")

    source_path = globals().get("__file__")
    if (
        type(source_path) is not str
        or not source_path.startswith("/")
        or os.path.normpath(source_path) != source_path
        or sys.argv[0] != source_path
    ):
        _fail("hermetic_replay_worker_absolute_script_path_required")
    suffix = "/" + CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
    if not source_path.endswith(suffix):
        _fail("hermetic_replay_worker_repository_layout_invalid")
    project_root = source_path[: -len(suffix)]
    if not project_root or project_root == "/" or os.path.normpath(project_root) != project_root:
        _fail("hermetic_replay_worker_repository_layout_invalid")
    if project_root in {entry for entry in sys.path if type(entry) is str}:
        _fail("hermetic_replay_worker_project_root_preloaded")
    if any(name == "v2" or name.startswith("v2.") for name in sys.modules):
        _fail("hermetic_replay_worker_project_import_preloaded")
    return project_root, source_path, policy_fd


def _required_seal_mask() -> int:
    names = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
    values = tuple(getattr(fcntl, name, 0) for name in names)
    if any(type(value) is not int or value <= 0 for value in values):
        _fail("hermetic_replay_worker_linux_seals_unavailable")
    mask = 0
    for value in values:
        mask |= value
    return mask


def _read_sealed_policy_channel(policy_fd: int) -> bytes:
    if sys.platform != "linux" or not hasattr(fcntl, "F_GET_SEALS"):
        _fail("hermetic_replay_worker_linux_memfd_required")
    try:
        access_flags = fcntl.fcntl(policy_fd, fcntl.F_GETFL)
    except OSError:
        _fail("hermetic_replay_worker_policy_fd_invalid")
    if access_flags & os.O_ACCMODE != os.O_RDONLY:
        _fail("hermetic_replay_worker_policy_fd_read_only_required")
    try:
        link_target = os.readlink(f"/proc/self/fd/{policy_fd}")
    except OSError:
        _fail("hermetic_replay_worker_policy_fd_memfd_identity_invalid")
    if not link_target.startswith("/memfd:") or not link_target.endswith(" (deleted)"):
        _fail("hermetic_replay_worker_policy_fd_memfd_identity_invalid")

    required_seals = _required_seal_mask()
    try:
        initial_seals = fcntl.fcntl(policy_fd, fcntl.F_GET_SEALS)
        initial_stat = os.fstat(policy_fd)
    except OSError:
        _fail("hermetic_replay_worker_policy_fd_identity_invalid")
    initial = _file_fingerprint(initial_stat)
    if (
        initial_seals & required_seals != required_seals
        or not stat.S_ISREG(initial_stat.st_mode)
        or int(initial_stat.st_nlink) != 0
    ):
        _fail("hermetic_replay_worker_policy_fd_immutable_seals_required")
    if not 1 <= int(initial_stat.st_size) <= MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4:
        _fail("hermetic_replay_worker_policy_channel_size_invalid")

    chunks: list[bytes] = []
    offset = 0
    remaining = int(initial_stat.st_size)
    while remaining:
        try:
            chunk = os.pread(policy_fd, min(remaining, _READ_CHUNK_BYTES), offset)
        except OSError:
            _fail("hermetic_replay_worker_policy_channel_read_failed")
        if not chunk:
            _fail("hermetic_replay_worker_policy_channel_read_failed")
        chunks.append(chunk)
        offset += len(chunk)
        remaining -= len(chunk)
    try:
        overflow = os.pread(policy_fd, 1, offset)
        final_stat = os.fstat(policy_fd)
        final_seals = fcntl.fcntl(policy_fd, fcntl.F_GET_SEALS)
    except OSError:
        _fail("hermetic_replay_worker_policy_channel_changed_during_read")
    if (
        overflow
        or _file_fingerprint(final_stat) != initial
        or final_seals != initial_seals
        or final_seals & required_seals != required_seals
    ):
        _fail("hermetic_replay_worker_policy_channel_changed_during_read")
    return b"".join(chunks)


def _read_bounded_stdin() -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4:
        try:
            chunk = os.read(
                0,
                min(
                    _READ_CHUNK_BYTES,
                    MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 + 1 - total,
                ),
            )
        except OSError:
            _fail("hermetic_replay_worker_request_read_failed")
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4:
            _fail("hermetic_replay_worker_request_size_exceeded")
    document = b"".join(chunks)
    if not document:
        _fail("hermetic_replay_worker_request_empty")
    return document


def _verify_frozen_module_contracts(protocol: ModuleType, policy: ModuleType) -> None:
    protocol_expectations = {
        "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_CHANNEL_V4_SCHEMA_VERSION
        ),
        "MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4": MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4,
        "MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4": (
            MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4
        ),
    }
    policy_expectations = {
        "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_VALIDATION_V4_SCHEMA_VERSION
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
        ),
        "CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
        ),
    }
    for name, expected in protocol_expectations.items():
        _require_exact(
            getattr(protocol, name, None),
            expected,
            reason="hermetic_replay_worker_protocol_contract_mismatch",
        )
    for name, expected in policy_expectations.items():
        _require_exact(
            getattr(policy, name, None),
            expected,
            reason="hermetic_replay_worker_policy_contract_mismatch",
        )
    for module, name in (
        (protocol, "validate_canonical_ohlcv_hermetic_replay_policy_channel_v4"),
        (protocol, "validate_canonical_ohlcv_hermetic_replay_request_v4"),
        (policy, "validate_canonical_ohlcv_hermetic_replay_policy_v4"),
    ):
        if not callable(getattr(module, name, None)):
            _fail("hermetic_replay_worker_frozen_callable_missing")


def _module_name_from_relative_path(relative_path: str) -> tuple[str, bool]:
    if not relative_path.endswith(".py"):
        _fail("hermetic_replay_worker_project_closure_python_path_invalid")
    if relative_path.endswith("/__init__.py"):
        return relative_path[: -len("/__init__.py")].replace("/", "."), True
    return relative_path[:-3].replace("/", "."), False


def _capture_validated_project_closure(
    policy: ModuleType,
    *,
    project_root: str,
    policy_document: bytes,
    worker_sha256: str,
    protocol_sha256: str,
) -> tuple[dict[str, tuple[bytes, str]], set[str]]:
    """Capture policy-validated project bytes without executing package init files."""

    declared_closure = getattr(policy, "PROJECT_CODE_CLOSURE_V4", None)
    pinned_by_role = getattr(policy, "_PINNED_CODE_SHA256_BY_ROLE", None)
    if type(declared_closure) is not tuple or type(pinned_by_role) is not MappingProxyType:
        _fail("hermetic_replay_worker_project_closure_contract_invalid")
    try:
        parsed = json.loads(policy_document.decode("ascii", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _fail("hermetic_replay_worker_project_closure_document_invalid")
    if type(parsed) is not dict or _canonical_json_bytes(parsed) != policy_document:
        _fail("hermetic_replay_worker_project_closure_document_invalid")
    entries = cast(dict[str, object], parsed).get("code_closure")
    if type(entries) is not list or len(entries) != len(declared_closure):
        _fail("hermetic_replay_worker_project_closure_document_invalid")

    runtime_sources: dict[str, tuple[bytes, str]] = {}
    package_names: set[str] = set()
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    non_runtime_roles = {
        "canonical_ohlcv_hermetic_replay_protocol_v4",
        "canonical_ohlcv_hermetic_replay_policy_v4",
        "canonical_ohlcv_hermetic_replay_worker_v4",
    }
    for ordinal, raw_entry in enumerate(entries):
        if type(raw_entry) is not dict:
            _fail("hermetic_replay_worker_project_closure_entry_invalid")
        entry = cast(dict[str, object], raw_entry)
        if set(entry) != {"ordinal", "role", "relative_path", "byte_count", "sha256"}:
            _fail("hermetic_replay_worker_project_closure_entry_invalid")
        expected_pair = cast(tuple[object, object], declared_closure[ordinal])
        if len(expected_pair) != 2:
            _fail("hermetic_replay_worker_project_closure_contract_invalid")
        expected_role, expected_path = expected_pair
        role = entry.get("role")
        relative_path = entry.get("relative_path")
        byte_count = entry.get("byte_count")
        digest = entry.get("sha256")
        if (
            type(expected_role) is not str
            or type(expected_path) is not str
            or type(role) is not str
            or type(relative_path) is not str
            or type(byte_count) is not int
            or byte_count < 0
            or byte_count > MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4
            or type(entry.get("ordinal")) is not int
            or entry["ordinal"] != ordinal
            or role != expected_role
            or relative_path != expected_path
            or role in seen_roles
            or relative_path in seen_paths
        ):
            _fail("hermetic_replay_worker_project_closure_entry_invalid")
        seen_roles.add(role)
        seen_paths.add(relative_path)
        entry_sha256 = _require_sha256(
            digest,
            reason="hermetic_replay_worker_project_closure_digest_invalid",
        )
        if role == "canonical_ohlcv_hermetic_replay_policy_v4":
            expected_sha256 = CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256
        elif role == "canonical_ohlcv_hermetic_replay_worker_v4":
            expected_sha256 = worker_sha256
        elif role == "canonical_ohlcv_hermetic_replay_protocol_v4":
            expected_sha256 = protocol_sha256
        else:
            expected_sha256 = cast(Any, pinned_by_role).get(role)
            if type(expected_sha256) is not str:
                _fail("hermetic_replay_worker_project_closure_pin_missing")
        if not hmac.compare_digest(entry_sha256, expected_sha256):
            _fail("hermetic_replay_worker_project_closure_pinned_digest_mismatch")

        source, observed_sha256, _ = _read_stable_relative_file(
            project_root,
            relative_path,
            maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
            reason_prefix="hermetic_replay_worker_project_closure_source",
        )
        if len(source) != byte_count or not hmac.compare_digest(
            observed_sha256,
            entry_sha256,
        ):
            _fail("hermetic_replay_worker_project_closure_capture_mismatch")
        module_name, is_package = _module_name_from_relative_path(relative_path)
        if module_name != "v2" and not module_name.startswith("v2."):
            _fail("hermetic_replay_worker_project_closure_module_invalid")
        if is_package:
            if module_name in package_names:
                _fail("hermetic_replay_worker_project_closure_module_invalid")
            package_names.add(module_name)
        elif role not in non_runtime_roles:
            if module_name in runtime_sources:
                _fail("hermetic_replay_worker_project_closure_module_invalid")
            runtime_sources[module_name] = (
                source,
                os.path.join(project_root, relative_path),
            )

    expected_packages = {
        "v2",
        "v2.backend",
        "v2.backend.app",
        "v2.backend.app.services",
        "v2.backend.app.services.native_trainer",
    }
    replay_name = (
        "v2.backend.app.services.native_trainer." "canonical_ohlcv_manifest_semantic_replay_v4"
    )
    if package_names != expected_packages or replay_name not in runtime_sources:
        _fail("hermetic_replay_worker_project_closure_runtime_graph_invalid")
    return runtime_sources, package_names


def _verify_executing_interpreter_identity(
    *,
    expected_path: str,
    expected_sha256: str,
    expected_fingerprint: _FileFingerprint,
) -> None:
    if sys.platform != "linux":
        _fail("hermetic_replay_worker_proc_exe_unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if not getattr(os, "O_CLOEXEC", 0):
        _fail("hermetic_replay_worker_proc_exe_unavailable")
    descriptor = -1
    try:
        try:
            link_target = os.readlink("/proc/self/exe")
            descriptor = os.open("/proc/self/exe", flags)
            initial_stat = os.fstat(descriptor)
        except OSError:
            _fail("hermetic_replay_worker_proc_exe_identity_invalid")
        initial = _file_fingerprint(initial_stat)
        if (
            link_target != expected_path
            or not stat.S_ISREG(initial_stat.st_mode)
            or not 1 <= int(initial_stat.st_size) <= MAX_HERMETIC_REPLAY_PYTHON_EXECUTABLE_BYTES_V4
            or initial != expected_fingerprint
        ):
            _fail("hermetic_replay_worker_proc_exe_identity_invalid")
        hasher = hashlib.sha256()
        offset = 0
        remaining = int(initial_stat.st_size)
        while remaining:
            try:
                chunk = os.pread(descriptor, min(remaining, _READ_CHUNK_BYTES), offset)
            except OSError:
                _fail("hermetic_replay_worker_proc_exe_read_failed")
            if not chunk:
                _fail("hermetic_replay_worker_proc_exe_read_failed")
            hasher.update(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
        try:
            overflow = os.pread(descriptor, 1, offset)
            final = _file_fingerprint(os.fstat(descriptor))
        except OSError:
            _fail("hermetic_replay_worker_proc_exe_changed_during_read")
        if (
            overflow
            or final != initial
            or not hmac.compare_digest(hasher.hexdigest(), expected_sha256)
        ):
            _fail("hermetic_replay_worker_proc_exe_changed_during_read")
    finally:
        _close_descriptor(descriptor)


def _validate_channel_and_policy(
    protocol: ModuleType,
    policy: ModuleType,
    *,
    channel_document: bytes,
) -> tuple[dict[str, object], dict[str, object], bytes]:
    try:
        channel_raw = protocol.validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(
            channel_document
        )
    except BaseException:
        _fail("hermetic_replay_worker_policy_channel_invalid")
    channel = dict(cast(Any, channel_raw))
    policy_document = channel.get("policy_document")
    if type(policy_document) is not bytes:
        _fail("hermetic_replay_worker_policy_channel_invalid")
    if (
        channel.get("policy_channel_sealing_verified") is not False
        or channel.get("policy_channel_immutability_verified") is not False
        or channel.get("policy_source_authenticated") is not False
        or channel.get("audit_only") is not True
    ):
        _fail("hermetic_replay_worker_policy_channel_authority_invalid")
    try:
        policy_raw = policy.validate_canonical_ohlcv_hermetic_replay_policy_v4(
            policy_document,
            expected_policy_sha256=channel.get("expected_policy_sha256"),
            expected_registry_id=channel.get("expected_registry_id"),
            expected_registry_version=channel.get("expected_registry_version"),
            expected_policy_id=channel.get("expected_policy_id"),
            expected_policy_revision=channel.get("expected_policy_revision"),
        )
    except BaseException:
        _fail("hermetic_replay_worker_policy_invalid")
    validated_policy = dict(cast(Any, policy_raw))
    return channel, validated_policy, policy_document


def _validate_policy_runtime_coordinates(
    validated_policy: dict[str, object],
    *,
    channel: dict[str, object],
    project_root: str,
    worker_path: str,
    worker_sha256: str,
    protocol_sha256: str,
    interpreter_sha256: str,
) -> None:
    expected_worker_path = os.path.join(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    )
    exact_values = (
        (
            validated_policy.get("schema_version"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_VALIDATION_V4_SCHEMA_VERSION,
        ),
        (validated_policy.get("project_root"), project_root),
        (validated_policy.get("python_absolute_path"), sys.executable),
        (validated_policy.get("python_executable_sha256"), interpreter_sha256),
        (
            validated_policy.get("worker_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        ),
        (validated_policy.get("worker_entrypoint"), "main"),
        (
            validated_policy.get("worker_invocation_mode"),
            "ABSOLUTE_PINNED_PYTHON_ISOLATED_FRESH_PROCESS",
        ),
        (validated_policy.get("worker_policy_closure_sha256"), worker_sha256),
        (
            validated_policy.get("hermetic_replay_protocol_relative_path"),
            CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
        ),
        (validated_policy.get("hermetic_replay_protocol_sha256"), protocol_sha256),
        (validated_policy.get("policy_sha256"), channel.get("expected_policy_sha256")),
        (validated_policy.get("policy_id"), channel.get("expected_policy_id")),
        (validated_policy.get("policy_revision"), channel.get("expected_policy_revision")),
        (validated_policy.get("registry_id"), channel.get("expected_registry_id")),
        (validated_policy.get("registry_version"), channel.get("expected_registry_version")),
    )
    if expected_worker_path != worker_path or any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in exact_values
    ):
        _fail("hermetic_replay_worker_policy_runtime_coordinate_mismatch")
    for field in (
        "expected_policy_digest_matched_at_validation",
        "expected_registry_coordinates_matched_at_validation",
        "python_executable_bytes_and_metadata_verified_at_validation",
        "ledger_cas_root_path_metadata_verified_at_validation",
        "project_root_path_metadata_verified_at_validation",
        "ordered_code_files_verified_at_validation",
        "worker_code_file_verified_at_validation",
        "frozen_protocol_code_file_verified_at_validation",
        "two_local_filesystem_verification_passes_matched_at_validation",
        "audit_only",
        "runtime_network_disable_required",
        "runtime_filesystem_write_disable_required",
    ):
        if validated_policy.get(field) is not True:
            _fail("hermetic_replay_worker_policy_validation_claim_invalid")
    if validated_policy.get("local_filesystem_verification_pass_count") != 2:
        _fail("hermetic_replay_worker_policy_validation_claim_invalid")
    for field in _POLICY_FALSE_FIELDS:
        if validated_policy.get(field) is not False:
            _fail("hermetic_replay_worker_policy_authority_invalid")


def _validate_request(protocol: ModuleType, document: bytes) -> dict[str, object]:
    try:
        request_raw = protocol.validate_canonical_ohlcv_hermetic_replay_request_v4(document)
    except BaseException:
        _fail("hermetic_replay_worker_request_invalid")
    request = dict(cast(Any, request_raw))
    if request.get("schema_version") != CANONICAL_OHLCV_HERMETIC_REPLAY_REQUEST_V4_SCHEMA_VERSION:
        _fail("hermetic_replay_worker_request_invalid")
    return request


class _StrictJsonFailure(ValueError):
    """Internal marker for non-canonical or unbounded CAS JSON."""


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonFailure("duplicate_key")
        result[key] = value
    return result


def _parse_bounded_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        raise _StrictJsonFailure("integer_out_of_range")
    parsed = int(value)
    if not -_MAX_SIGNED_64 - 1 <= parsed <= _MAX_SIGNED_64:
        raise _StrictJsonFailure("integer_out_of_range")
    return parsed


def _parse_bounded_json_float(value: str) -> float:
    if len(value) > 128:
        raise _StrictJsonFailure("float_out_of_range")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _StrictJsonFailure("float_out_of_range")
    return parsed


def _reject_json_constant(_value: str) -> NoReturn:
    raise _StrictJsonFailure("constant_forbidden")


def _validate_json_resource_shape(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise _StrictJsonFailure("json_resource_limit")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > _MAX_JSON_CONTAINER_ITEMS:
                raise _StrictJsonFailure("json_resource_limit")
            for key, child in mapping.items():
                if type(key) is not str:
                    raise _StrictJsonFailure("json_key_invalid")
                try:
                    if len(key.encode("ascii", errors="strict")) > 4096:
                        raise _StrictJsonFailure("json_key_invalid")
                except UnicodeEncodeError as exc:
                    raise _StrictJsonFailure("json_key_invalid") from exc
                stack.append((child, depth + 1))
        elif type(item) is list:
            sequence = cast(list[object], item)
            if len(sequence) > _MAX_JSON_CONTAINER_ITEMS:
                raise _StrictJsonFailure("json_resource_limit")
            stack.extend((child, depth + 1) for child in sequence)
        elif type(item) is str:
            try:
                if len(item.encode("ascii", errors="strict")) > _MAX_JSON_TEXT_BYTES:
                    raise _StrictJsonFailure("json_text_invalid")
            except UnicodeEncodeError as exc:
                raise _StrictJsonFailure("json_text_invalid") from exc
        elif type(item) is int:
            if not -_MAX_SIGNED_64 - 1 <= item <= _MAX_SIGNED_64:
                raise _StrictJsonFailure("json_integer_invalid")
        elif type(item) is float:
            if not math.isfinite(item):
                raise _StrictJsonFailure("json_float_invalid")
        elif type(item) not in {bool, type(None)}:
            raise _StrictJsonFailure("json_scalar_invalid")


def _parse_strict_json_object(
    payload: bytes,
    *,
    fields: frozenset[str],
    require_canonical_bytes: bool,
) -> dict[str, object]:
    try:
        decoded = json.loads(
            payload.decode("ascii", errors="strict"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_int=_parse_bounded_json_int,
            parse_float=_parse_bounded_json_float,
            parse_constant=_reject_json_constant,
        )
        _validate_json_resource_shape(decoded)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _StrictJsonFailure,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_json_invalid")
    if type(decoded) is not dict:
        _fail("hermetic_replay_worker_selected_row_oracle_json_invalid")
    result = cast(dict[str, object], decoded)
    if frozenset(result) != fields:
        _fail("hermetic_replay_worker_selected_row_oracle_json_invalid")
    if require_canonical_bytes and _canonical_json_bytes(result) != payload:
        _fail("hermetic_replay_worker_selected_row_oracle_json_invalid")
    return result


def _oracle_exact_int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_SIGNED_64:
        _fail("hermetic_replay_worker_selected_row_oracle_invalid")
    return value


def _oracle_exact_text(value: object, *, maximum_bytes: int = 4096) -> str:
    if type(value) is not str:
        _fail("hermetic_replay_worker_selected_row_oracle_invalid")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail("hermetic_replay_worker_selected_row_oracle_invalid")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("hermetic_replay_worker_selected_row_oracle_invalid")
    return value


def _oracle_clock(value: object) -> datetime:
    text = _oracle_exact_text(value, maximum_bytes=32)
    try:
        parsed = datetime.strptime(text, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail("hermetic_replay_worker_selected_row_oracle_clock_invalid")
    if parsed < _EPOCH or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        _fail("hermetic_replay_worker_selected_row_oracle_clock_invalid")
    return parsed


def _clock_to_exact_milliseconds(value: object) -> int:
    parsed = _oracle_clock(value)
    if parsed.microsecond % 1000 != 0:
        _fail("hermetic_replay_worker_selected_row_oracle_clock_invalid")
    delta = parsed - _EPOCH
    milliseconds = delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000
    if not 0 <= milliseconds <= _MAX_SIGNED_64:
        _fail("hermetic_replay_worker_selected_row_oracle_clock_invalid")
    return milliseconds


def _milliseconds_to_clock(value: int) -> str:
    _oracle_exact_int(value)
    try:
        parsed = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _fail("hermetic_replay_worker_selected_row_oracle_clock_invalid")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _oracle_address(value: object, *, maximum_byte_count: int) -> dict[str, object]:
    if type(value) not in {dict, MappingProxyType}:
        _fail("hermetic_replay_worker_selected_row_oracle_address_invalid")
    address = dict(cast(Any, value))
    if set(address) != {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}:
        _fail("hermetic_replay_worker_selected_row_oracle_address_invalid")
    digest = _require_sha256(
        address.get("payload_sha256"),
        reason="hermetic_replay_worker_selected_row_oracle_address_invalid",
    )
    byte_count = address.get("payload_byte_count")
    if type(byte_count) is not int or not 1 <= byte_count <= maximum_byte_count:
        _fail("hermetic_replay_worker_selected_row_oracle_address_invalid")
    exact = {
        "schema_version": _SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        "payload_sha256": digest,
        "payload_byte_count": byte_count,
        "relative_path": f"sha256/{digest[:2]}/{digest}",
    }
    if address != exact:
        _fail("hermetic_replay_worker_selected_row_oracle_address_invalid")
    return exact


def _exact_recursive_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        actual_mapping = cast(dict[object, object], actual)
        expected_mapping = cast(dict[object, object], expected)
        return set(actual_mapping) == set(expected_mapping) and all(
            _exact_recursive_equal(actual_mapping[key], expected_mapping[key])
            for key in actual_mapping
        )
    if type(actual) is list:
        actual_sequence = cast(list[object], actual)
        expected_sequence = cast(list[object], expected)
        return len(actual_sequence) == len(expected_sequence) and all(
            _exact_recursive_equal(left, right)
            for left, right in zip(actual_sequence, expected_sequence, strict=True)
        )
    return actual == expected


def _read_oracle_cas_payload(
    cas_root: str,
    address: dict[str, object],
    *,
    maximum_byte_count: int,
) -> bytes:
    payload, digest, _ = _read_stable_relative_file(
        cas_root,
        cast(str, address["relative_path"]),
        maximum_byte_count=maximum_byte_count,
        reason_prefix="hermetic_replay_worker_selected_row_oracle_cas",
    )
    if len(payload) != address["payload_byte_count"] or not hmac.compare_digest(
        digest, cast(str, address["payload_sha256"])
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_cas_mismatch")
    return payload


def _oracle_number(value: object, *, positive: bool) -> int | float:
    if type(value) not in {int, float}:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    number = cast(int | float, value)
    if type(number) is int and not -_MAX_SIGNED_64 - 1 <= number <= _MAX_SIGNED_64:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    if type(number) is float and not math.isfinite(number):
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    if (positive and number <= 0) or (not positive and number < 0):
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    return number


def _validate_oracle_ohlcv_row(
    row: dict[str, object],
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, object]:
    if frozenset(row) != _OHLCV_ROW_FIELDS:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    if (
        row.get("symbol") != symbol
        or row.get("exchange") != "binance"
        or row.get("timeframe") != timeframe
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    duration = _TIMEFRAME_DURATION_MS.get(timeframe)
    if type(duration) is not int:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    open_ms = _oracle_exact_int(row.get("candle_open_time"))
    close_ms = _oracle_exact_int(row.get("candle_close_time"))
    producer_ms = _oracle_exact_int(row.get("event_time"))
    ingested_ms = _oracle_exact_int(row.get("ingested_at"))
    available_ms = _oracle_exact_int(row.get("available_at"))
    open_alias_ms = _oracle_exact_int(row.get("open_time"))
    close_alias_ms = _oracle_exact_int(row.get("close_time"))
    timestamp_alias_ms = _oracle_exact_int(row.get("ts"))
    if (
        open_ms % duration != 0
        or close_ms != open_ms + duration - 1
        or open_alias_ms != open_ms
        or close_alias_ms != close_ms
        or timestamp_alias_ms != open_ms
        or row.get("is_closed") is not True
        or row.get("closed_candle") is not True
        or row.get("candle_closed_confirmed") is not True
        or row.get("feature_eligible") is not True
        or type(row.get("is_backfilled")) is not bool
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    source = _oracle_exact_text(row.get("source"), maximum_bytes=64)
    sequence_id = _oracle_exact_text(row.get("source_sequence_id"), maximum_bytes=128)
    is_backfilled = cast(bool, row["is_backfilled"])
    if source == "binance_wss":
        if (
            is_backfilled
            or not close_ms <= producer_ms <= ingested_ms <= available_ms
            or available_ms != max(close_ms, producer_ms, ingested_ms)
            or sequence_id != str(producer_ms)
        ):
            _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    elif source == "binance_rest":
        if (
            not is_backfilled
            or producer_ms != close_ms
            or not close_ms <= ingested_ms == available_ms
            or sequence_id != str(close_ms)
        ):
            _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    else:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    raw_payload_hash = _require_sha256(
        row.get("raw_payload_hash"),
        reason="hermetic_replay_worker_selected_row_oracle_ohlcv_invalid",
    )
    candle_id = row.get("candle_id")
    if type(candle_id) is not str or _CANDLE_ID_RE.fullmatch(candle_id) is None:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    candle_material = {
        "exchange": "binance",
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_open_time": open_ms,
        "candle_close_time": close_ms,
        "raw_payload_hash": raw_payload_hash,
    }
    encoded_candle = json.dumps(candle_material, sort_keys=True, default=str).encode("utf-8")
    if candle_id != hashlib.sha256(encoded_candle).hexdigest()[:24]:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    nested = row.get("ohlcv")
    if type(nested) is not dict or frozenset(nested) != _OHLCV_FIELDS:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    nested_row = cast(dict[str, object], nested)
    positive_fields = ("open", "high", "low", "close")
    nonnegative_fields = (
        "volume",
        "quote_volume",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    )
    for field in positive_fields:
        top = _oracle_number(row.get(field), positive=True)
        inside = _oracle_number(nested_row.get(field), positive=True)
        if type(top) is not type(inside) or top != inside:
            _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    for field in nonnegative_fields:
        top = _oracle_number(row.get(field), positive=False)
        inside = _oracle_number(nested_row.get(field), positive=False)
        if type(top) is not type(inside) or top != inside:
            _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    trades = _oracle_exact_int(row.get("num_trades"))
    nested_trades = _oracle_exact_int(nested_row.get("num_trades"))
    if trades != nested_trades:
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    open_price = cast(int | float, row["open"])
    high = cast(int | float, row["high"])
    low = cast(int | float, row["low"])
    close = cast(int | float, row["close"])
    if (
        high < max(open_price, close)
        or low > min(open_price, close)
        or low > high
        or cast(int | float, row["taker_buy_base_vol"]) > cast(int | float, row["volume"])
        or cast(int | float, row["taker_buy_quote_vol"]) > cast(int | float, row["quote_volume"])
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_ohlcv_invalid")
    return {
        "candle_id": candle_id,
        "open_ms": open_ms,
        "close_ms": close_ms,
        "producer_ms": producer_ms,
        "ingested_ms": ingested_ms,
        "available_ms": available_ms,
        "source": source,
        "source_sequence_id": sequence_id,
        "raw_payload_hash": raw_payload_hash,
        "is_backfilled": is_backfilled,
    }


def _plain_canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _validate_oracle_source_receipt(
    receipt: object,
    *,
    source_key: str,
    source_key_version: str,
    selected_address: dict[str, object],
    selected_metadata: dict[str, object],
    row_values: dict[str, object],
    consumer_observed_at: str,
) -> str:
    if type(receipt) is not dict or frozenset(receipt) != _SOURCE_RECEIPT_FIELDS:
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    root = cast(dict[str, object], receipt)
    candle_id = cast(str, row_values["candle_id"])
    source_label = (
        f"ohlcv_closed:binance:{source_key.split(':')[-2]}:"
        f"{source_key.split(':')[-1]}:{candle_id}"
    )
    expected_clocks = {
        "economic_event_time": _milliseconds_to_clock(cast(int, row_values["close_ms"])),
        "producer_event_time": _milliseconds_to_clock(cast(int, row_values["producer_ms"])),
        "ingested_at": _milliseconds_to_clock(cast(int, row_values["ingested_ms"])),
        "available_at": _milliseconds_to_clock(cast(int, row_values["available_ms"])),
        "consumer_observed_at": consumer_observed_at,
        "feature_cutoff": _milliseconds_to_clock(cast(int, row_values["close_ms"])),
    }
    exact_root_values: dict[str, object] = {
        "schema_version": _SOURCE_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": _SOURCE_RECEIPT_EVIDENCE_CLASSIFICATION,
        "downstream_status": _SOURCE_RECEIPT_DOWNSTREAM_STATUS,
        "receipt_kind": "DIRECT_READ",
        "source_label": source_label,
        "payload_type": _SOURCE_PAYLOAD_TYPE,
        "payload_sha256": selected_address["payload_sha256"],
        "payload_byte_count": selected_address["payload_byte_count"],
        **expected_clocks,
    }
    if any(
        type(root.get(field)) is not type(expected) or root.get(field) != expected
        for field, expected in exact_root_values.items()
    ) or any(root.get(field) is not False for field in _SOURCE_RECEIPT_FALSE_FIELDS):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")

    read_evidence = root.get("read_evidence")
    if type(read_evidence) is not dict or frozenset(read_evidence) != _READ_EVIDENCE_FIELDS:
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    read = cast(dict[str, object], read_evidence)
    locator = (
        f"{source_key}@bytes:{selected_metadata['byte_start']}-"
        f"{selected_metadata['byte_end_exclusive']}"
    )
    locator_material = {
        "schema_version": _SOURCE_READ_LOCATOR_SCHEMA_VERSION,
        "read_locator_type": "REDIS_VERSIONED_VALUE",
        "read_locator": locator,
        "read_locator_version": source_key_version,
    }
    locator_sha256 = _plain_canonical_sha256(locator_material)
    expected_read: dict[str, object] = {
        "schema_version": _SOURCE_READ_EVIDENCE_SCHEMA_VERSION,
        "source_label": source_label,
        "payload_type": _SOURCE_PAYLOAD_TYPE,
        "payload_sha256": selected_address["payload_sha256"],
        "payload_byte_count": selected_address["payload_byte_count"],
        "economic_event_time": expected_clocks["economic_event_time"],
        "producer_event_time": expected_clocks["producer_event_time"],
        "ingested_at": expected_clocks["ingested_at"],
        "available_at": expected_clocks["available_at"],
        "read_locator_type": "REDIS_VERSIONED_VALUE",
        "read_locator": locator,
        "read_locator_version": source_key_version,
        "read_locator_sha256": locator_sha256,
        "read_completed_at": consumer_observed_at,
    }
    if not _exact_recursive_equal(read, expected_read):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    read_sha256 = _plain_canonical_sha256(read)
    if (
        root.get("read_evidence_sha256") != read_sha256
        or root.get("read_locator_sha256") != locator_sha256
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")

    finality_evidence = root.get("finality_evidence")
    if (
        type(finality_evidence) is not dict
        or frozenset(finality_evidence) != _FINALITY_EVIDENCE_FIELDS
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    finality = cast(dict[str, object], finality_evidence)
    expected_finality: dict[str, object] = {
        "schema_version": _SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION,
        "source_label": source_label,
        "payload_type": _SOURCE_PAYLOAD_TYPE,
        "payload_sha256": selected_address["payload_sha256"],
        "payload_byte_count": selected_address["payload_byte_count"],
        "read_evidence_sha256": read_sha256,
        "read_locator_sha256": locator_sha256,
        "economic_event_time": expected_clocks["economic_event_time"],
        "producer_event_time": expected_clocks["producer_event_time"],
        "ingested_at": expected_clocks["ingested_at"],
        "available_at": expected_clocks["available_at"],
        "consumer_observed_at": consumer_observed_at,
        "finality_type": "CLOSED_INTERVAL",
        "event_final": True,
        "finality_cutoff": expected_clocks["economic_event_time"],
        "finality_verified_at": expected_clocks["available_at"],
        "verifier": _SOURCE_FINALITY_VERIFIER,
    }
    if not _exact_recursive_equal(finality, expected_finality):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    finality_sha256 = _plain_canonical_sha256(finality)
    if root.get("finality_evidence_sha256") != finality_sha256:
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    supplied_receipt_sha256 = _require_sha256(
        root.get("receipt_sha256"),
        reason="hermetic_replay_worker_selected_row_oracle_receipt_invalid",
    )
    receipt_material = dict(root)
    del receipt_material["receipt_sha256"]
    if not hmac.compare_digest(
        supplied_receipt_sha256,
        _plain_canonical_sha256(receipt_material),
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_receipt_invalid")
    return supplied_receipt_sha256


def _independent_selected_row_oracle(
    *,
    cas_root: object,
    request: dict[str, object],
) -> dict[str, object]:
    if (
        type(cas_root) is not str
        or not cas_root.startswith("/")
        or os.path.normpath(cas_root) != cas_root
    ):
        _fail("hermetic_replay_worker_cas_root_invalid")
    manifest_address = _oracle_address(
        request.get("manifest_address"),
        maximum_byte_count=MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4,
    )
    selected_address = _oracle_address(
        request.get("selected_row_address"),
        maximum_byte_count=MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4,
    )
    symbol = _oracle_exact_text(request.get("symbol"), maximum_bytes=32)
    timeframe = _oracle_exact_text(request.get("timeframe"), maximum_bytes=8)
    if timeframe not in _TIMEFRAME_DURATION_MS:
        _fail("hermetic_replay_worker_selected_row_oracle_invalid")
    decision_time = _oracle_exact_text(request.get("decision_time"), maximum_bytes=32)
    decision_clock = _oracle_clock(decision_time)

    manifest_payload = _read_oracle_cas_payload(
        cas_root,
        manifest_address,
        maximum_byte_count=MAX_HERMETIC_REPLAY_MANIFEST_BYTES_V4,
    )
    manifest = _parse_strict_json_object(
        manifest_payload,
        fields=_MANIFEST_FIELDS,
        require_canonical_bytes=True,
    )
    source_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
    source_key_version = _oracle_exact_text(
        manifest.get("source_key_version"),
        maximum_bytes=256,
    )
    consumer_observed_at = _oracle_exact_text(
        manifest.get("consumer_observed_at"),
        maximum_bytes=32,
    )
    consumer_observed_ms = _clock_to_exact_milliseconds(consumer_observed_at)
    declared_consumer_observed_ms = _oracle_exact_int(manifest.get("consumer_observed_at_ms"))
    full_source_address = _oracle_address(
        manifest.get("full_source_payload_cas_address"),
        maximum_byte_count=MAX_HERMETIC_REPLAY_FULL_SOURCE_BYTES_V4,
    )
    manifest_false_fields = (
        "durable_ledger_appended",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    )
    if (
        manifest.get("schema_version") != _MANIFEST_SCHEMA_VERSION
        or manifest.get("evidence_classification") != _MANIFEST_EVIDENCE_CLASSIFICATION
        or manifest.get("downstream_status") != _MANIFEST_DOWNSTREAM_STATUS
        or manifest.get("source_key") != source_key
        or manifest.get("source_key_sha256")
        != hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        or declared_consumer_observed_ms != consumer_observed_ms
        or manifest.get("latest_candle_matches_expected_cutoff") is not True
        or any(manifest.get(field) is not False for field in manifest_false_fields)
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_manifest_invalid")
    selected_rows = manifest.get("selected_rows")
    selected_count = manifest.get("selected_row_count")
    if (
        type(selected_rows) is not list
        or type(selected_count) is not int
        or not 1 <= selected_count <= 1500
        or len(selected_rows) != selected_count
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_manifest_invalid")

    matches: list[dict[str, object]] = []
    for ordinal, raw_selected in enumerate(selected_rows):
        if (
            type(raw_selected) is not dict
            or frozenset(raw_selected) != _MANIFEST_SELECTED_ROW_FIELDS
        ):
            _fail("hermetic_replay_worker_selected_row_oracle_manifest_invalid")
        selected = cast(dict[str, object], raw_selected)
        selected_ordinal = _oracle_exact_int(selected.get("selected_ordinal"))
        source_index = _oracle_exact_int(selected.get("source_index"))
        byte_start = _oracle_exact_int(selected.get("byte_start"))
        byte_end = _oracle_exact_int(selected.get("byte_end_exclusive"), minimum=1)
        exact_count = _oracle_exact_int(selected.get("exact_payload_byte_count"), minimum=1)
        exact_sha256 = _require_sha256(
            selected.get("exact_payload_sha256"),
            reason="hermetic_replay_worker_selected_row_oracle_manifest_invalid",
        )
        row_address = _oracle_address(
            selected.get("source_payload_cas_address"),
            maximum_byte_count=MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4,
        )
        if (
            selected_ordinal != ordinal
            or byte_end <= byte_start
            or byte_end - byte_start != exact_count
            or row_address["payload_sha256"] != exact_sha256
            or row_address["payload_byte_count"] != exact_count
            or type(selected.get("is_backfilled")) is not bool
            or type(selected.get("source_read_receipt_v4")) is not dict
        ):
            _fail("hermetic_replay_worker_selected_row_oracle_manifest_invalid")
        for field in (
            "candle_open_time_ms",
            "candle_close_time_ms",
            "producer_event_time_ms",
            "ingested_at_ms",
            "available_at_ms",
        ):
            _oracle_exact_int(selected.get(field))
        candle_id = selected.get("candle_id")
        if type(candle_id) is not str or _CANDLE_ID_RE.fullmatch(candle_id) is None:
            _fail("hermetic_replay_worker_selected_row_oracle_manifest_invalid")
        _oracle_exact_text(selected.get("source"), maximum_bytes=64)
        _oracle_exact_text(selected.get("source_sequence_id"), maximum_bytes=128)
        _require_sha256(
            selected.get("raw_payload_hash"),
            reason="hermetic_replay_worker_selected_row_oracle_manifest_invalid",
        )
        if row_address == selected_address:
            matches.append(
                {
                    **selected,
                    "selected_ordinal": selected_ordinal,
                    "source_index": source_index,
                    "byte_start": byte_start,
                    "byte_end_exclusive": byte_end,
                    "source_payload_cas_address": row_address,
                }
            )
    if len(matches) != 1:
        _fail("hermetic_replay_worker_selected_row_oracle_membership_invalid")
    selected_metadata = matches[0]

    selected_payload = _read_oracle_cas_payload(
        cas_root,
        selected_address,
        maximum_byte_count=MAX_HERMETIC_REPLAY_SELECTED_ROW_BYTES_V4,
    )
    full_source_payload = _read_oracle_cas_payload(
        cas_root,
        full_source_address,
        maximum_byte_count=MAX_HERMETIC_REPLAY_FULL_SOURCE_BYTES_V4,
    )
    selected_start = cast(int, selected_metadata["byte_start"])
    selected_end = cast(int, selected_metadata["byte_end_exclusive"])
    if (
        selected_end > len(full_source_payload)
        or full_source_payload[selected_start:selected_end] != selected_payload
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_span_invalid")
    selected_row = _parse_strict_json_object(
        selected_payload,
        fields=_OHLCV_ROW_FIELDS,
        require_canonical_bytes=False,
    )
    row_values = _validate_oracle_ohlcv_row(
        selected_row,
        symbol=symbol,
        timeframe=timeframe,
    )
    metadata_matches = {
        "candle_id": "candle_id",
        "candle_open_time_ms": "open_ms",
        "candle_close_time_ms": "close_ms",
        "producer_event_time_ms": "producer_ms",
        "ingested_at_ms": "ingested_ms",
        "available_at_ms": "available_ms",
        "source": "source",
        "source_sequence_id": "source_sequence_id",
        "raw_payload_hash": "raw_payload_hash",
        "is_backfilled": "is_backfilled",
    }
    if any(
        type(selected_metadata.get(metadata_field)) is not type(row_values[row_field])
        or selected_metadata.get(metadata_field) != row_values[row_field]
        for metadata_field, row_field in metadata_matches.items()
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_identity_invalid")
    receipt_sha256 = _validate_oracle_source_receipt(
        selected_metadata.get("source_read_receipt_v4"),
        source_key=source_key,
        source_key_version=source_key_version,
        selected_address=selected_address,
        selected_metadata=selected_metadata,
        row_values=row_values,
        consumer_observed_at=consumer_observed_at,
    )

    close_clock = _oracle_clock(_milliseconds_to_clock(cast(int, row_values["close_ms"])))
    producer_clock = _oracle_clock(_milliseconds_to_clock(cast(int, row_values["producer_ms"])))
    ingested_clock = _oracle_clock(_milliseconds_to_clock(cast(int, row_values["ingested_ms"])))
    available_clock = _oracle_clock(_milliseconds_to_clock(cast(int, row_values["available_ms"])))
    consumer_clock = _oracle_clock(consumer_observed_at)
    if (
        not close_clock
        <= producer_clock
        <= ingested_clock
        <= available_clock
        <= (consumer_clock)
        <= decision_clock
    ):
        _fail("hermetic_replay_worker_selected_row_oracle_point_in_time_invalid")

    return {
        "manifest_sha256": manifest_address["payload_sha256"],
        "manifest_byte_count": manifest_address["payload_byte_count"],
        "requested_selected_row_address_schema_version": selected_address["schema_version"],
        "requested_selected_row_payload_sha256": selected_address["payload_sha256"],
        "requested_selected_row_payload_byte_count": selected_address["payload_byte_count"],
        "requested_selected_row_cas_relative_path": selected_address["relative_path"],
        "matched_selected_row_address_schema_version": selected_address["schema_version"],
        "matched_selected_row_payload_sha256": selected_address["payload_sha256"],
        "matched_selected_row_payload_byte_count": selected_address["payload_byte_count"],
        "matched_selected_row_cas_relative_path": selected_address["relative_path"],
        "symbol": symbol,
        "timeframe": timeframe,
        "matched_selected_ordinal": selected_metadata["selected_ordinal"],
        "matched_source_index": selected_metadata["source_index"],
        "matched_byte_start": selected_metadata["byte_start"],
        "matched_byte_end_exclusive": selected_metadata["byte_end_exclusive"],
        "matched_candle_id": row_values["candle_id"],
        "matched_candle_open_time_ms": row_values["open_ms"],
        "matched_candle_close_time_ms": row_values["close_ms"],
        "matched_producer_event_time_ms": row_values["producer_ms"],
        "matched_ingested_at_ms": row_values["ingested_ms"],
        "matched_available_at_ms": row_values["available_ms"],
        "matched_source": row_values["source"],
        "matched_source_sequence_id": row_values["source_sequence_id"],
        "matched_raw_payload_hash": row_values["raw_payload_hash"],
        "matched_is_backfilled": row_values["is_backfilled"],
        "selected_row_source_read_receipt_sha256": receipt_sha256,
        "economic_event_time": _milliseconds_to_clock(cast(int, row_values["close_ms"])),
        "producer_event_time": _milliseconds_to_clock(cast(int, row_values["producer_ms"])),
        "ingested_at": _milliseconds_to_clock(cast(int, row_values["ingested_ms"])),
        "available_at": _milliseconds_to_clock(cast(int, row_values["available_ms"])),
        "consumer_observed_at": consumer_observed_at,
        "feature_cutoff": _milliseconds_to_clock(cast(int, row_values["close_ms"])),
        "decision_time": decision_time,
        "generated_at": None,
        "execution_time": None,
    }


def _address_from_request(address_type: type[Any], value: object) -> object:
    if type(value) is not MappingProxyType:
        _fail("hermetic_replay_worker_request_address_invalid")
    address = dict(cast(Any, value))
    expected_fields = {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }
    if set(address) != expected_fields:
        _fail("hermetic_replay_worker_request_address_invalid")
    try:
        return address_type(
            schema_version=address["schema_version"],
            payload_sha256=address["payload_sha256"],
            payload_byte_count=address["payload_byte_count"],
            relative_path=address["relative_path"],
        )
    except BaseException:
        _fail("hermetic_replay_worker_request_address_invalid")


def _validate_selected_row_binding(
    raw_result: object,
    *,
    oracle: dict[str, object],
) -> dict[str, object]:
    if type(raw_result) is not MappingProxyType:
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    result = dict(cast(Any, raw_result))
    if set(result) != _SELECTED_ROW_RESULT_FIELDS:
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    if any(type(value) not in {str, int, bool} and value is not None for value in result.values()):
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    supplied_digest = _require_sha256(
        result.get("selected_row_binding_sha256"),
        reason="hermetic_replay_worker_selected_row_binding_invalid",
    )
    digest_material = dict(result)
    del digest_material["selected_row_binding_sha256"]
    expected_digest = _domain_hash(
        CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_DOMAIN_SEPARATOR,
        digest_material,
    )
    if not hmac.compare_digest(supplied_digest, expected_digest):
        _fail("hermetic_replay_worker_selected_row_binding_invalid")

    exact_values = (
        (result.get("schema_version"), CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_SCHEMA_VERSION),
        (result.get("evidence_classification"), _SELECTED_ROW_EVIDENCE_CLASSIFICATION),
        (result.get("downstream_status"), _SELECTED_ROW_DOWNSTREAM_STATUS),
        (result.get("base_replay_schema_version"), _BASE_REPLAY_SCHEMA_VERSION),
        (
            result.get("selected_row_binding_hash_domain"),
            CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_HASH_DOMAIN,
        ),
        (result.get("audit_only"), True),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in exact_values
    ):
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    for field, expected in oracle.items():
        actual = result.get(field)
        if type(actual) is not type(expected) or actual != expected:
            _fail("hermetic_replay_worker_selected_row_binding_invalid")
    for field in (
        "base_replay_sha256",
        "manifest_sha256",
        "requested_selected_row_payload_sha256",
        "matched_selected_row_payload_sha256",
        "matched_raw_payload_hash",
        "selected_row_source_read_receipt_sha256",
        "selected_row_binding_sha256",
    ):
        _require_sha256(
            result.get(field),
            reason="hermetic_replay_worker_selected_row_binding_invalid",
        )
    candle_id = result.get("matched_candle_id")
    if type(candle_id) is not str or _CANDLE_ID_RE.fullmatch(candle_id) is None:
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    for field in (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
    ):
        _oracle_clock(result.get(field))
    if (
        _clock_to_exact_milliseconds(result.get("economic_event_time"))
        != result.get("matched_candle_close_time_ms")
        or _clock_to_exact_milliseconds(result.get("producer_event_time"))
        != result.get("matched_producer_event_time_ms")
        or _clock_to_exact_milliseconds(result.get("ingested_at"))
        != result.get("matched_ingested_at_ms")
        or _clock_to_exact_milliseconds(result.get("available_at"))
        != result.get("matched_available_at_ms")
        or result.get("feature_cutoff") != result.get("economic_event_time")
    ):
        _fail("hermetic_replay_worker_selected_row_binding_invalid")
    for field in _SEMANTIC_TRUE_FIELDS:
        if result.get(field) is not True:
            _fail("hermetic_replay_worker_selected_row_binding_invalid")
    for field in _SEMANTIC_FALSE_FIELDS:
        if result.get(field) is not False:
            _fail("hermetic_replay_worker_selected_row_binding_authority_invalid")
    return result


def _validate_independently_replayed_base(
    raw_result: object,
    *,
    request: dict[str, object],
    oracle: dict[str, object],
) -> str:
    if type(raw_result) is not MappingProxyType:
        _fail("hermetic_replay_worker_base_replay_invalid")
    result = dict(cast(Any, raw_result))
    if set(result) != _BASE_REPLAY_RESULT_FIELDS or any(
        type(value) not in {str, int, bool} and value is not None for value in result.values()
    ):
        _fail("hermetic_replay_worker_base_replay_invalid")
    supplied_sha256 = _require_sha256(
        result.get("semantic_replay_sha256"),
        reason="hermetic_replay_worker_base_replay_invalid",
    )
    digest_material = dict(result)
    del digest_material["semantic_replay_sha256"]
    if not hmac.compare_digest(
        supplied_sha256,
        _plain_canonical_sha256(digest_material),
    ):
        _fail("hermetic_replay_worker_base_replay_invalid")
    manifest_address = dict(cast(Any, request["manifest_address"]))
    symbol = request.get("symbol")
    timeframe = request.get("timeframe")
    exact_values = (
        (result.get("schema_version"), _BASE_REPLAY_SCHEMA_VERSION),
        (result.get("evidence_classification"), _BASE_REPLAY_EVIDENCE_CLASSIFICATION),
        (result.get("downstream_status"), _SELECTED_ROW_DOWNSTREAM_STATUS),
        (result.get("manifest_sha256"), manifest_address["payload_sha256"]),
        (result.get("manifest_byte_count"), manifest_address["payload_byte_count"]),
        (result.get("source_key"), f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"),
        (result.get("symbol"), symbol),
        (result.get("timeframe"), timeframe),
        (result.get("consumer_observed_at"), oracle["consumer_observed_at"]),
        (result.get("decision_time"), request.get("decision_time")),
        (result.get("generated_at"), None),
        (result.get("execution_time"), None),
        (result.get("audit_only"), True),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in exact_values
    ):
        _fail("hermetic_replay_worker_base_replay_invalid")
    for field in (
        "manifest_sha256",
        "full_source_payload_sha256",
        "binding_selection_sha256",
        "decision_binding_selection_sha256",
        "selected_candle_id_chain_sha256",
        "suffix_digest_sha256",
        "source_read_receipt_chain_sha256",
        "semantic_replay_sha256",
    ):
        _require_sha256(
            result.get(field),
            reason="hermetic_replay_worker_base_replay_invalid",
        )
    for field in (
        "manifest_byte_count",
        "full_source_payload_byte_count",
        "raw_row_count",
        "selected_row_count",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
    ):
        _oracle_exact_int(result.get(field))
    if (
        cast(int, result["full_source_payload_byte_count"]) < 1
        or cast(int, result["full_source_payload_byte_count"])
        > MAX_HERMETIC_REPLAY_FULL_SOURCE_BYTES_V4
        or cast(int, result["selected_row_count"]) < 1
        or cast(int, result["selected_source_end_index_exclusive"])
        <= cast(int, result["selected_source_start_index"])
        or cast(int, result["selected_source_end_index_exclusive"])
        - cast(int, result["selected_source_start_index"])
        != cast(int, result["selected_row_count"])
    ):
        _fail("hermetic_replay_worker_base_replay_invalid")
    _oracle_exact_text(result.get("source_key_version"), maximum_bytes=256)
    consumer_clock = _oracle_clock(result.get("consumer_observed_at"))
    cutoff_clock = _oracle_clock(result.get("feature_cutoff"))
    decision_clock = _oracle_clock(result.get("decision_time"))
    if cutoff_clock > consumer_clock or consumer_clock > decision_clock:
        _fail("hermetic_replay_worker_base_replay_invalid")
    for field in _BASE_REPLAY_TRUE_FIELDS:
        if result.get(field) is not True:
            _fail("hermetic_replay_worker_base_replay_invalid")
    for field in _SEMANTIC_FALSE_FIELDS:
        if result.get(field) is not False:
            _fail("hermetic_replay_worker_base_replay_authority_invalid")
    return supplied_sha256


def _import_and_bind_selected_row(
    *,
    project_root: str,
    cas_root: object,
    request: dict[str, object],
    captured_sources: dict[str, tuple[bytes, str]],
    package_names: set[str],
    oracle: dict[str, object],
) -> dict[str, object]:
    if type(cas_root) is not str:
        _fail("hermetic_replay_worker_cas_root_invalid")
    if project_root in sys.path or any(
        name == "v2" or name.startswith("v2.") for name in sys.modules
    ):
        _fail("hermetic_replay_worker_project_root_preloaded")
    path_snapshot = tuple(sys.path)
    meta_path_snapshot = tuple(sys.meta_path)
    finder = _ExactProjectClosureFinder(
        sources=captured_sources,
        packages=package_names,
    )
    sys.meta_path.insert(0, cast(Any, finder))
    try:
        try:
            replay_module = importlib.import_module(
                "v2.backend.app.services.native_trainer."
                "canonical_ohlcv_manifest_semantic_replay_v4"
            )
            store_module = importlib.import_module(
                "v2.backend.app.services.native_trainer.immutable_source_payload_store"
            )
        except CanonicalOhlcvHermeticReplayWorkerV4Error:
            raise
        except BaseException:
            _fail("hermetic_replay_worker_semantic_import_failed")
        expected_replay_path = os.path.join(
            project_root,
            CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_RELATIVE_PATH,
        )
        if getattr(replay_module, "__file__", None) != expected_replay_path:
            _fail("hermetic_replay_worker_semantic_import_path_mismatch")
        address_type = getattr(store_module, "SourcePayloadAddress", None)
        binder = getattr(replay_module, "bind_canonical_ohlcv_selected_row_v4", None)
        base_replayer = getattr(
            replay_module,
            "replay_canonical_ohlcv_manifest_semantics_v4",
            None,
        )
        if type(address_type) is not type or not callable(binder) or not callable(base_replayer):
            _fail("hermetic_replay_worker_semantic_api_invalid")
        manifest_address = _address_from_request(
            address_type,
            request.get("manifest_address"),
        )
        selected_row_address = _address_from_request(
            address_type,
            request.get("selected_row_address"),
        )
        try:
            raw_base_result = base_replayer(
                cas_root=cas_root,
                manifest_address=manifest_address,
                expected_symbol=request.get("symbol"),
                expected_timeframe=request.get("timeframe"),
                decision_time=request.get("decision_time"),
            )
        except CanonicalOhlcvHermeticReplayWorkerV4Error:
            raise
        except BaseException:
            _fail("hermetic_replay_worker_base_replay_failed")
        expected_base_sha256 = _validate_independently_replayed_base(
            raw_base_result,
            request=request,
            oracle=oracle,
        )
        try:
            raw_result = binder(
                cas_root=cas_root,
                manifest_address=manifest_address,
                selected_row_address=selected_row_address,
                expected_symbol=request.get("symbol"),
                expected_timeframe=request.get("timeframe"),
                decision_time=request.get("decision_time"),
            )
        except CanonicalOhlcvHermeticReplayWorkerV4Error:
            raise
        except BaseException:
            _fail("hermetic_replay_worker_selected_row_replay_failed")
        binding_oracle = dict(oracle)
        binding_oracle["base_replay_sha256"] = expected_base_sha256
        result = _validate_selected_row_binding(raw_result, oracle=binding_oracle)
        finder.verify_loaded_modules()
        return result
    finally:
        path_changed = tuple(sys.path) != path_snapshot or project_root in sys.path
        meta_path_changed = (
            not sys.meta_path
            or cast(object, sys.meta_path[0]) is not finder
            or tuple(sys.meta_path[1:]) != meta_path_snapshot
        )
        sys.path[:] = list(path_snapshot)
        sys.meta_path[:] = list(meta_path_snapshot)
        if path_changed:
            _fail("hermetic_replay_worker_sys_path_changed")
        if meta_path_changed:
            _fail("hermetic_replay_worker_meta_path_changed")


def _build_result(
    *,
    request: dict[str, object],
    channel: dict[str, object],
    validated_policy: dict[str, object],
    policy_document: bytes,
    selected: dict[str, object],
) -> bytes:
    manifest_address = dict(cast(Any, request["manifest_address"]))
    selected_address = dict(cast(Any, request["selected_row_address"]))
    policy_validation_sha256 = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_POLICY_VALIDATION_RESULT_V4_DOMAIN_SEPARATOR,
        validated_policy,
    )
    result: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
        "result_hash_domain": CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_HASH_DOMAIN,
        "request_schema_version": request["schema_version"],
        "request_sha256": request["request_sha256"],
        "request_nonce": request["request_nonce"],
        "run_id": request["run_id"],
        "cycle_id": request["cycle_id"],
        "decision_id": request["decision_id"],
        "policy_channel_schema_version": channel["schema_version"],
        "policy_channel_sha256": channel["policy_channel_sha256"],
        "policy_channel_sealing_verified": True,
        "policy_channel_immutability_verified": True,
        "policy_schema_version": validated_policy["policy_schema_version"],
        "policy_sha256": validated_policy["policy_sha256"],
        "policy_document_byte_count": len(policy_document),
        "policy_validation_schema_version": validated_policy["schema_version"],
        "policy_validation_result_sha256": policy_validation_sha256,
        "policy_id": validated_policy["policy_id"],
        "policy_revision": validated_policy["policy_revision"],
        "registry_id": validated_policy["registry_id"],
        "registry_version": validated_policy["registry_version"],
        "project_root": validated_policy["project_root"],
        "project_owner_uid": validated_policy["project_owner_uid"],
        "python_absolute_path": validated_policy["python_absolute_path"],
        "python_executable_sha256": validated_policy["python_executable_sha256"],
        "declared_python_identity_sha256": validated_policy["declared_python_identity_sha256"],
        "ledger_owned_cas_root": validated_policy["ledger_owned_cas_root"],
        "worker_relative_path": validated_policy["worker_relative_path"],
        "worker_entrypoint": validated_policy["worker_entrypoint"],
        "worker_invocation_mode": validated_policy["worker_invocation_mode"],
        "worker_policy_closure_sha256": validated_policy["worker_policy_closure_sha256"],
        "hermetic_replay_protocol_relative_path": validated_policy[
            "hermetic_replay_protocol_relative_path"
        ],
        "hermetic_replay_protocol_sha256": validated_policy["hermetic_replay_protocol_sha256"],
        "hermetic_replay_policy_relative_path": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH
        ),
        "hermetic_replay_policy_source_sha256": (
            CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256
        ),
        "code_closure_sha256": validated_policy["code_closure_sha256"],
        "resource_policy_sha256": validated_policy["resource_policy_sha256"],
        "manifest_sha256": manifest_address["payload_sha256"],
        "manifest_byte_count": manifest_address["payload_byte_count"],
        "selected_row_binding_schema_version": selected["schema_version"],
        "selected_row_binding_sha256": selected["selected_row_binding_sha256"],
        "base_replay_sha256": selected["base_replay_sha256"],
        "selected_row_payload_sha256": selected_address["payload_sha256"],
        "selected_row_payload_byte_count": selected_address["payload_byte_count"],
        "selected_row_cas_relative_path": selected_address["relative_path"],
        "symbol": request["symbol"],
        "timeframe": request["timeframe"],
        "matched_selected_ordinal": selected["matched_selected_ordinal"],
        "matched_source_index": selected["matched_source_index"],
        "matched_candle_id": selected["matched_candle_id"],
        "matched_candle_open_time_ms": selected["matched_candle_open_time_ms"],
        "matched_candle_close_time_ms": selected["matched_candle_close_time_ms"],
        "matched_producer_event_time_ms": selected["matched_producer_event_time_ms"],
        "matched_ingested_at_ms": selected["matched_ingested_at_ms"],
        "matched_available_at_ms": selected["matched_available_at_ms"],
        "matched_source": selected["matched_source"],
        "matched_source_sequence_id": selected["matched_source_sequence_id"],
        "matched_raw_payload_hash": selected["matched_raw_payload_hash"],
        "matched_is_backfilled": selected["matched_is_backfilled"],
        "selected_row_source_read_receipt_sha256": selected[
            "selected_row_source_read_receipt_sha256"
        ],
        "economic_event_time": selected["economic_event_time"],
        "producer_event_time": selected["producer_event_time"],
        "ingested_at": selected["ingested_at"],
        "available_at": selected["available_at"],
        "consumer_observed_at": selected["consumer_observed_at"],
        "feature_cutoff": selected["feature_cutoff"],
        "decision_time": request["decision_time"],
        "generated_at": None,
        "execution_time": None,
        "request_validated": True,
        "sealed_policy_channel_validated": True,
        "policy_and_code_closure_validated_at_validation": True,
        "worker_source_path_hash_matched_at_validation": True,
        "executing_interpreter_inode_and_hash_matched_at_validation": True,
        "frozen_sources_reverified_at_validation": True,
        "loaded_project_modules_sourced_only_from_captured_bytes_at_validation": True,
        "package_initializer_sources_executed_at_validation": False,
        "project_root_added_to_sys_path_at_validation": False,
        "selected_row_binding_replayed": True,
        "runtime_network_disable_required": True,
        "runtime_filesystem_write_disable_required": True,
        **{field: False for field in _WORKER_FALSE_FIELDS},
        "audit_only": True,
    }
    result["result_sha256"] = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_DOMAIN_SEPARATOR,
        result,
    )
    if any(type(value) not in {str, int, bool} and value is not None for value in result.values()):
        _fail("hermetic_replay_worker_result_scalar_contract_failed")
    encoded = _canonical_json_bytes(result)
    if not 1 <= len(encoded) <= MAX_HERMETIC_REPLAY_RESULT_BYTES_V4:
        _fail("hermetic_replay_worker_result_size_invalid")
    return encoded


def _execute() -> bytes:
    project_root, worker_path, policy_fd = _verify_direct_isolated_invocation()
    protocol_path = os.path.join(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
    )
    policy_path = os.path.join(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH,
    )
    protocol_bytes, protocol_sha256, protocol_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_protocol_source",
    )
    if not hmac.compare_digest(
        protocol_sha256,
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    ):
        _fail("hermetic_replay_worker_protocol_source_digest_mismatch")
    policy_bytes, policy_source_sha256, policy_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_policy_source",
    )
    if not hmac.compare_digest(
        policy_source_sha256,
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256,
    ):
        _fail("hermetic_replay_worker_policy_source_digest_mismatch")
    _, worker_sha256, worker_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_self_source",
    )

    protocol = _load_private_exact_module(
        name="_canonical_ohlcv_hermetic_replay_protocol_v4_bootstrap",
        path=protocol_path,
        source=protocol_bytes,
    )
    policy = _load_private_exact_module(
        name="_canonical_ohlcv_hermetic_replay_policy_v4_bootstrap",
        path=policy_path,
        source=policy_bytes,
    )
    _verify_frozen_module_contracts(protocol, policy)
    if any(name == "v2" or name.startswith("v2.") for name in sys.modules):
        _fail("hermetic_replay_worker_project_import_before_policy_forbidden")

    channel_document = _read_sealed_policy_channel(policy_fd)
    _close_descriptor(policy_fd)
    request_document = _read_bounded_stdin()
    channel, validated_policy, policy_document = _validate_channel_and_policy(
        protocol,
        policy,
        channel_document=channel_document,
    )
    request = _validate_request(protocol, request_document)

    executable_path = sys.executable
    if (
        type(executable_path) is not str
        or not executable_path.startswith("/")
        or os.path.normpath(executable_path) != executable_path
    ):
        _fail("hermetic_replay_worker_interpreter_path_invalid")
    _, interpreter_sha256, interpreter_fingerprint = _read_stable_absolute_file(
        executable_path,
        maximum_byte_count=MAX_HERMETIC_REPLAY_PYTHON_EXECUTABLE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_interpreter",
    )
    _verify_executing_interpreter_identity(
        expected_path=executable_path,
        expected_sha256=interpreter_sha256,
        expected_fingerprint=interpreter_fingerprint,
    )
    _validate_policy_runtime_coordinates(
        validated_policy,
        channel=channel,
        project_root=project_root,
        worker_path=worker_path,
        worker_sha256=worker_sha256,
        protocol_sha256=protocol_sha256,
        interpreter_sha256=interpreter_sha256,
    )

    _, final_protocol_sha256, final_protocol_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_protocol_source",
    )
    _, final_policy_sha256, final_policy_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_policy_source",
    )
    _, final_worker_sha256, final_worker_fingerprint = _read_stable_relative_file(
        project_root,
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        maximum_byte_count=MAX_HERMETIC_REPLAY_BOOTSTRAP_SOURCE_BYTES_V4,
        reason_prefix="hermetic_replay_worker_self_source",
    )
    if (
        final_protocol_sha256 != protocol_sha256
        or final_protocol_fingerprint != protocol_fingerprint
        or final_policy_sha256 != policy_source_sha256
        or final_policy_fingerprint != policy_fingerprint
        or final_worker_sha256 != worker_sha256
        or final_worker_fingerprint != worker_fingerprint
    ):
        _fail("hermetic_replay_worker_frozen_source_changed_during_validation")

    captured_sources, package_names = _capture_validated_project_closure(
        policy,
        project_root=project_root,
        policy_document=policy_document,
        worker_sha256=worker_sha256,
        protocol_sha256=protocol_sha256,
    )
    cas_root = validated_policy.get("ledger_owned_cas_root")
    oracle = _independent_selected_row_oracle(
        cas_root=cas_root,
        request=request,
    )

    selected = _import_and_bind_selected_row(
        project_root=project_root,
        cas_root=cas_root,
        request=request,
        captured_sources=captured_sources,
        package_names=package_names,
        oracle=oracle,
    )
    return _build_result(
        request=request,
        channel=channel,
        validated_policy=validated_policy,
        policy_document=policy_document,
        selected=selected,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(descriptor, payload[offset:])
        except OSError:
            _fail("hermetic_replay_worker_output_write_failed")
        if written <= 0:
            _fail("hermetic_replay_worker_output_write_failed")
        offset += written


def _error_document(reason: str) -> bytes:
    document: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_ERROR_V4_SCHEMA_VERSION,
        "reason": (
            reason
            if _REASON_RE.fullmatch(reason) is not None
            else "hermetic_replay_worker_internal_failure"
        ),
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "audit_only": True,
    }
    encoded = _canonical_json_bytes(document)
    if len(encoded) > MAX_HERMETIC_REPLAY_ERROR_BYTES_V4:
        return (
            b'{"audit_only":true,"live_execution_authorized":false,'
            b'"paper_trading_authorized":false,"prediction_authorized":false,'
            b'"reason":"hermetic_replay_worker_internal_failure",'
            b'"schema_version":"canonical_ohlcv_hermetic_replay_error_v4",'
            b'"trainer_admission_authorized":false}'
        )
    return encoded


def main() -> int:
    """Run one bounded request; never emit a traceback or partial success JSON."""

    try:
        result = _execute()
    except CanonicalOhlcvHermeticReplayWorkerV4Error as exc:
        try:
            _write_all(2, _error_document(exc.reason))
        except BaseException:
            return 2
        return 2
    except BaseException:
        try:
            _write_all(2, _error_document("hermetic_replay_worker_internal_failure"))
        except BaseException:
            return 2
        return 2
    try:
        _write_all(1, result)
    except BaseException:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL_OHLCV_HERMETIC_REPLAY_ERROR_V4_SCHEMA_VERSION",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_DOMAIN_SEPARATOR",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_HASH_DOMAIN",
    "CANONICAL_OHLCV_HERMETIC_REPLAY_RESULT_V4_SCHEMA_VERSION",
    "CanonicalOhlcvHermeticReplayWorkerV4Error",
    "MAX_HERMETIC_REPLAY_ERROR_BYTES_V4",
    "MAX_HERMETIC_REPLAY_RESULT_BYTES_V4",
    "main",
]
