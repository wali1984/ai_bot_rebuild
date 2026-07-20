from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
import shutil
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_hermetic_replay_policy_v4 as policy_module,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    MAX_SOURCE_PAYLOAD_BYTES as MAX_ATOMIC_SOURCE_PAYLOAD_BYTES,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_policy_v4 import (
    CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4,
    PROJECT_CODE_CLOSURE_V4,
    CanonicalOhlcvHermeticReplayPolicyV4Error,
    validate_canonical_ohlcv_hermetic_replay_policy_v4,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
)

_REGISTRY_ID = "native-trainer-hermetic-replay-policy-registry"
_REGISTRY_VERSION = "registry-v4.1"
_POLICY_ID = "canonical-binance-ohlcv-hermetic-replay"
_POLICY_REVISION = 1
_REPOSITORY_ROOT = Path(__file__).resolve().parents[6]

_CANONICAL_PROFILE = {
    "profile_id": "canonical_binance_closed_ohlcv_profile_v4",
    "adapter_id": "canonical-ohlcv-closed-adapter-v4",
    "branch_identity": "canonical-ohlcv-atomic-adapter-v4",
    "evidence_kind": "POSITIVE_SOURCE_READ",
    "evidence_class": "EXACT_ATOMIC_CANONICAL_BINANCE_CLOSED_OHLCV",
    "upstream_producer_identity_claim": "binance-public-market-data",
    "finality_kind": "CLOSED_INTERVAL",
    "row_payload_type": "EXACT_CANONICAL_CLOSED_OHLCV_ROW_BYTES",
}
_ACCEPTED_SCHEMAS = {
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
    "hermetic_replay_protocol_contract": ("canonical_ohlcv_hermetic_replay_protocol_contract_v4"),
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
_WORKER = {
    "relative_path": CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    "entrypoint": "main",
    "invocation_mode": "ABSOLUTE_PINNED_PYTHON_ISOLATED_FRESH_PROCESS",
}
_WORKER_PROTOCOL = {
    "request_schema_version": "canonical_ohlcv_hermetic_replay_request_v4",
    "result_schema_version": "canonical_ohlcv_hermetic_replay_result_v4",
    "request_material": [
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
    ],
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
_RESOURCE_CEILINGS = {
    "max_policy_document_bytes": 128 * 1024,
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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _policy_digest(policy: object) -> str:
    return hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR + _canonical(policy)
    ).hexdigest()


def _python_identity_digest(runtime: dict[str, object]) -> str:
    material = {key: value for key, value in runtime.items() if key != "identity_sha256"}
    return hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR + _canonical(material)
    ).hexdigest()


def _build_policy(tmp_path: Path) -> dict[str, object]:
    project_root = tmp_path / "project root"
    code_closure: list[dict[str, object]] = []
    for ordinal, (role, relative_path) in enumerate(PROJECT_CODE_CLOSURE_V4):
        path = project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if role in policy_module._PINNED_CODE_SHA256_BY_ROLE:
            payload = (_REPOSITORY_ROOT / relative_path).read_bytes()
            assert (
                hashlib.sha256(payload).hexdigest()
                == (policy_module._PINNED_CODE_SHA256_BY_ROLE[role])
            )
        else:
            payload = f"# fixture {ordinal}: {role}\n".encode()
        path.write_bytes(payload)
        path.chmod(0o644)
        code_closure.append(
            {
                "ordinal": ordinal,
                "role": role,
                "relative_path": relative_path,
                "byte_count": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    project_root.chmod(0o755)
    for directory in (path for path in project_root.rglob("*") if path.is_dir()):
        directory.chmod(0o755)

    python_path = tmp_path / "runtime" / "python3.12"
    python_path.parent.mkdir(parents=True)
    python_payload = b"fixture-cpython-executable-v4\n"
    python_path.write_bytes(python_payload)
    python_path.chmod(0o500)
    python_runtime: dict[str, object] = {
        "identity_schema_version": "canonical_ohlcv_hermetic_python_identity_v4",
        "absolute_path": str(python_path),
        "implementation": "CPython",
        "version": "3.12.4",
        "isolated_flags": ["-I", "-S", "-B"],
        "owner_uid": os.geteuid(),
        "mode_octal": "0500",
        "executable_byte_count": len(python_payload),
        "executable_sha256": hashlib.sha256(python_payload).hexdigest(),
        "identity_sha256": "",
    }
    python_runtime["identity_sha256"] = _python_identity_digest(python_runtime)

    cas_root = tmp_path / "ledger" / "source-cas"
    cas_root.mkdir(parents=True)
    cas_root.chmod(0o700)

    return {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REVISION,
        "registry_id": _REGISTRY_ID,
        "registry_version": _REGISTRY_VERSION,
        "project_root": str(project_root),
        "project_owner_uid": os.geteuid(),
        "python_runtime": python_runtime,
        "ledger_owned_cas_root": {
            "absolute_path": str(cas_root),
            "owner_uid": os.geteuid(),
            "required_mode_octal": "0700",
            "namespace": "sha256",
            "ownership_model": "SOURCE_PROVENANCE_LEDGER_OWNED_IMMUTABLE_CAS_V1",
            "access_mode": "READ_ONLY_HERMETIC_REPLAY",
            "request_selectable": False,
        },
        "canonical_profile": copy.deepcopy(_CANONICAL_PROFILE),
        "accepted_schemas": copy.deepcopy(_ACCEPTED_SCHEMAS),
        "worker": copy.deepcopy(_WORKER),
        "code_closure": code_closure,
        "resource_ceilings": copy.deepcopy(_RESOURCE_CEILINGS),
        "worker_protocol": copy.deepcopy(_WORKER_PROTOCOL),
        "authority_policy": {field: False for field in _FALSE_AUTHORITY_FIELDS},
        "audit_only": True,
    }


def _validate(
    policy: dict[str, object],
    *,
    expected_digest: str | None = None,
    registry_id: object = _REGISTRY_ID,
    registry_version: object = _REGISTRY_VERSION,
    policy_id: object = _POLICY_ID,
    policy_revision: object = _POLICY_REVISION,
) -> MappingProxyType[str, object]:
    return validate_canonical_ohlcv_hermetic_replay_policy_v4(
        _canonical(policy),
        expected_policy_sha256=(expected_digest or _policy_digest(policy)),
        expected_registry_id=registry_id,
        expected_registry_version=registry_version,
        expected_policy_id=policy_id,
        expected_policy_revision=policy_revision,
    )


def test_valid_policy_reopens_every_identity_and_returns_only_immutable_scalars(
    tmp_path: Path,
) -> None:
    policy = _build_policy(tmp_path)

    result = _validate(policy)

    assert type(result) is type(MappingProxyType({}))
    assert result["schema_version"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_RESULT_SCHEMA_VERSION
    )
    assert result["policy_sha256"] == _policy_digest(policy)
    assert result["policy_byte_count"] == len(_canonical(policy))
    assert result["code_closure_entry_count"] == len(PROJECT_CODE_CLOSURE_V4)
    entries = policy["code_closure"]
    assert type(entries) is list
    expected_total_bytes = 0
    for raw_entry in entries:
        assert type(raw_entry) is dict
        byte_count = raw_entry["byte_count"]
        assert type(byte_count) is int
        expected_total_bytes += byte_count
    worker_entries = [
        entry
        for entry in entries
        if type(entry) is dict and entry.get("role") == "canonical_ohlcv_hermetic_replay_worker_v4"
    ]
    assert len(worker_entries) == 1
    assert result["code_closure_total_bytes"] == expected_total_bytes
    assert all(type(value) in {str, int, bool} for value in result.values())
    assert result["expected_policy_digest_matched_at_validation"] is True
    assert result["expected_registry_coordinates_matched_at_validation"] is True
    assert result["python_executable_bytes_and_metadata_verified_at_validation"] is True
    assert result["ledger_cas_root_path_metadata_verified_at_validation"] is True
    assert result["project_root_path_metadata_verified_at_validation"] is True
    assert result["ordered_code_files_verified_at_validation"] is True
    assert result["worker_code_file_verified_at_validation"] is True
    assert result["frozen_protocol_code_file_verified_at_validation"] is True
    assert result["two_local_filesystem_verification_passes_matched_at_validation"] is True
    assert result["local_filesystem_verification_pass_count"] == 2
    assert {
        "registry_binding_verified",
        "python_identity_sha256",
        "python_identity_verified",
        "ledger_cas_identity_verified",
        "ordered_code_closure_verified",
        "worker_expected_sha256",
        "supervisor_policy_digest_matched",
        "registry_coordinates_verified_at_validation",
    }.isdisjoint(result)
    assert len(cast(str, result["declared_python_identity_sha256"])) == 64
    assert result["project_root"] == policy["project_root"]
    assert result["project_owner_uid"] == policy["project_owner_uid"]
    assert result["worker_relative_path"] == CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
    assert result["worker_entrypoint"] == "main"
    assert result["worker_invocation_mode"] == ("ABSOLUTE_PINNED_PYTHON_ISOLATED_FRESH_PROCESS")
    assert result["worker_policy_closure_sha256"] == worker_entries[0]["sha256"]
    assert result["hermetic_replay_protocol_relative_path"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
    )
    assert result["hermetic_replay_protocol_sha256"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
    )
    assert result["runtime_network_disable_required"] is True
    assert result["runtime_filesystem_write_disable_required"] is True
    assert result["runtime_sandbox_enforced"] is False
    assert result["request_policy_selection_allowed"] is False
    assert result["audit_only"] is True
    for field in _FALSE_AUTHORITY_FIELDS:
        assert result[field] is False
    with pytest.raises(TypeError):
        cast(dict[str, object], result)["trainer_admission_authorized"] = True


@pytest.mark.parametrize("document", [bytearray(b"{}"), memoryview(b"{}"), "{}"])
def test_policy_requires_exact_builtin_bytes(document: object) -> None:
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="exact_bytes_required",
    ):
        validate_canonical_ohlcv_hermetic_replay_policy_v4(
            document,
            expected_policy_sha256="0" * 64,
            expected_registry_id=_REGISTRY_ID,
            expected_registry_version=_REGISTRY_VERSION,
            expected_policy_id=_POLICY_ID,
            expected_policy_revision=1,
        )


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        (b'{"schema_version":"x","schema_version":"y"}', "duplicate_json_key"),
        (b'{"x":1.0}', "json_float_forbidden"),
        (b'{"x":NaN}', "json_constant_forbidden"),
        (b'{"x":9223372036854775808}', "json_integer_out_of_range"),
        (b'{"x":"\xc3\xa9"}', "non_ascii_text_forbidden"),
        (b"[]", "object_required"),
    ],
)
def test_parser_rejects_ambiguous_or_nonprimitive_json(document: bytes, reason: str) -> None:
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match=reason):
        validate_canonical_ohlcv_hermetic_replay_policy_v4(
            document,
            expected_policy_sha256="0" * 64,
            expected_registry_id=_REGISTRY_ID,
            expected_registry_version=_REGISTRY_VERSION,
            expected_policy_id=_POLICY_ID,
            expected_policy_revision=1,
        )


def test_parser_resource_bounds_fail_before_material_validation() -> None:
    oversized = b" " * (MAX_HERMETIC_POLICY_DOCUMENT_BYTES_V4 + 1)
    too_deep = b'{"a":{"b":{"c":{"d":{"e":{"f":{"g":{"h":{}}}}}}}}}'
    for document, reason in (
        (oversized, "document_size_invalid"),
        (too_deep, "json_depth_limit_exceeded"),
    ):
        with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match=reason):
            validate_canonical_ohlcv_hermetic_replay_policy_v4(
                document,
                expected_policy_sha256="0" * 64,
                expected_registry_id=_REGISTRY_ID,
                expected_registry_version=_REGISTRY_VERSION,
                expected_policy_id=_POLICY_ID,
                expected_policy_revision=1,
            )


def test_source_payload_ceiling_matches_both_committed_source_contracts() -> None:
    configured = policy_module._RESOURCE_CEILINGS["max_source_payload_bytes"]

    assert configured == MAX_ATOMIC_SOURCE_PAYLOAD_BYTES
    assert configured == MAX_OHLCV_CLOSED_PAYLOAD_BYTES


def test_noncanonical_json_is_rejected_before_any_filesystem_identity(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    noncanonical = json.dumps(policy, indent=2, sort_keys=False).encode()
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match="noncanonical_json"):
        validate_canonical_ohlcv_hermetic_replay_policy_v4(
            noncanonical,
            expected_policy_sha256="0" * 64,
            expected_registry_id=_REGISTRY_ID,
            expected_registry_version=_REGISTRY_VERSION,
            expected_policy_id=_POLICY_ID,
            expected_policy_revision=1,
        )


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_exact_top_level_fields_are_required(tmp_path: Path, mutation: str) -> None:
    policy = _build_policy(tmp_path)
    if mutation == "missing":
        del policy["accepted_schemas"]
    else:
        policy["request_selected_override"] = False
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match="fields_invalid"):
        _validate(policy)


@pytest.mark.parametrize(
    ("argument", "replacement", "reason"),
    [
        ("digest", "f" * 64, "digest_mismatch"),
        ("registry_id", "other-registry", "registry_id_mismatch"),
        ("registry_version", "registry-v5", "registry_version_mismatch"),
        ("policy_id", "other-policy", "policy_id_mismatch"),
        ("policy_revision", 2, "revision_mismatch"),
    ],
)
def test_separate_expected_policy_and_registry_coordinates_are_exactly_matched(
    tmp_path: Path,
    argument: str,
    replacement: object,
    reason: str,
) -> None:
    policy = _build_policy(tmp_path)
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match=reason):
        _validate(
            policy,
            expected_digest=(cast(str, replacement) if argument == "digest" else None),
            registry_id=(replacement if argument == "registry_id" else _REGISTRY_ID),
            registry_version=(replacement if argument == "registry_version" else _REGISTRY_VERSION),
            policy_id=(replacement if argument == "policy_id" else _POLICY_ID),
            policy_revision=(replacement if argument == "policy_revision" else _POLICY_REVISION),
        )


@pytest.mark.parametrize("field", _FALSE_AUTHORITY_FIELDS)
def test_every_caller_authority_escalation_is_rejected(tmp_path: Path, field: str) -> None:
    policy = _build_policy(tmp_path)
    authority = policy["authority_policy"]
    assert type(authority) is dict
    authority[field] = True
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="authority_escalation_forbidden",
    ):
        _validate(policy)


@pytest.mark.parametrize(
    ("section", "field", "replacement", "reason"),
    [
        ("resource_ceilings", "cpu_time_seconds", 31, "resource_ceilings_invalid"),
        ("resource_ceilings", "process_count", True, "resource_ceilings_invalid"),
        ("worker_protocol", "policy_in_request", True, "worker_protocol_invalid"),
        ("worker_protocol", "cas_root_in_request", True, "worker_protocol_invalid"),
        ("worker_protocol", "authority_in_request", True, "worker_protocol_invalid"),
        (
            "worker_protocol",
            "runtime_network_disable_required",
            False,
            "worker_protocol_invalid",
        ),
        (
            "worker_protocol",
            "request_material",
            ["manifest_address"],
            "worker_protocol_invalid",
        ),
        ("worker", "relative_path", "../worker.py", "worker_invalid"),
        ("canonical_profile", "profile_id", "caller-profile", "canonical_profile_invalid"),
        ("accepted_schemas", "ohlcv_closed_window", "v999", "accepted_schemas_invalid"),
    ],
)
def test_fixed_policy_sections_cannot_be_relaxed(
    tmp_path: Path,
    section: str,
    field: str,
    replacement: object,
    reason: str,
) -> None:
    policy = _build_policy(tmp_path)
    nested = policy[section]
    assert type(nested) is dict
    nested[field] = replacement
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match=reason):
        _validate(policy)


def test_worker_protocol_exactly_names_request_material_and_unenforced_sandbox_requirements(
    tmp_path: Path,
) -> None:
    policy = _build_policy(tmp_path)
    protocol = policy["worker_protocol"]
    assert type(protocol) is dict

    assert protocol["request_material"] == [
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
    ]
    assert protocol["runtime_network_disable_required"] is True
    assert protocol["runtime_filesystem_write_disable_required"] is True
    assert "network_disabled" not in protocol
    assert "filesystem_writes_disabled" not in protocol

    result = _validate(policy)

    assert result["runtime_network_disable_required"] is True
    assert result["runtime_filesystem_write_disable_required"] is True
    assert result["runtime_sandbox_enforced"] is False


@pytest.mark.parametrize(
    "path_value",
    ["relative/project", "/srv/../escape", "/", "/srv/project/", "/srv//project"],
)
def test_project_root_must_be_normalized_absolute_without_traversal(
    tmp_path: Path, path_value: str
) -> None:
    policy = _build_policy(tmp_path)
    policy["project_root"] = path_value
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="project_root_path_invalid",
    ):
        _validate(policy)


@pytest.mark.parametrize("mutation", ["order", "missing", "extra", "role", "path"])
def test_code_closure_is_complete_and_exactly_ordered(tmp_path: Path, mutation: str) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    if mutation == "order":
        entries[0], entries[1] = entries[1], entries[0]
    elif mutation == "missing":
        entries.pop()
    elif mutation == "extra":
        entries.append(copy.deepcopy(entries[-1]))
    elif mutation == "role":
        entries[0]["role"] = "request_selected_role"
    else:
        entries[0]["relative_path"] = "../outside.py"
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match="code_closure"):
        _validate(policy)


def test_duplicate_code_path_is_rejected_explicitly(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    entries[1]["relative_path"] = entries[0]["relative_path"]
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="code_closure_duplicate_path",
    ):
        _validate(policy)


@pytest.mark.parametrize("field", ["sha256", "byte_count"])
def test_malformed_code_identity_is_rejected(tmp_path: Path, field: str) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    entries[0][field] = "ABC" if field == "sha256" else -1
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match="code_closure"):
        _validate(policy)


def test_changed_code_bytes_fail_the_pinned_digest(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    target = next(entry for entry in entries if int(entry["byte_count"]) > 0)
    path = Path(str(policy["project_root"])) / str(target["relative_path"])
    changed = b"# changed but same byte count\n"
    original_count = int(target["byte_count"])
    path.write_bytes(changed[:original_count].ljust(original_count, b"x"))
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error, match="code_file_digest_mismatch"
    ):
        _validate(policy)


def test_final_code_symlink_is_rejected_even_when_target_bytes_match(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    first = entries[0]
    path = Path(str(policy["project_root"])) / str(first["relative_path"])
    target = tmp_path / "matching-target.py"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error, match="code_file_identity_invalid"
    ):
        _validate(policy)


def test_intermediate_code_directory_symlink_is_rejected(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    root = Path(str(policy["project_root"]))
    native = root / "v2/backend/app/services/native_trainer"
    real_native = root / "native-trainer-real"
    native.rename(real_native)
    native.symlink_to(real_native, target_is_directory=True)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="code_path_identity_invalid",
    ):
        _validate(policy)


def test_project_root_symlink_is_rejected(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    project = Path(str(policy["project_root"]))
    real_project = tmp_path / "real-project"
    project.rename(real_project)
    project.symlink_to(real_project, target_is_directory=True)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="directory_identity_invalid",
    ):
        _validate(policy)


@pytest.mark.parametrize(
    ("target", "unsafe_mode", "reason"),
    [
        ("project_root", 0o775, "project_root_identity_invalid"),
        ("project_root", 0o757, "project_root_identity_invalid"),
        ("descendant_directory", 0o775, "code_directory_identity_invalid"),
        ("descendant_directory", 0o757, "code_directory_identity_invalid"),
        ("code_file", 0o664, "code_file_identity_invalid"),
        ("code_file", 0o646, "code_file_identity_invalid"),
    ],
)
def test_project_code_directories_and_files_reject_group_or_other_write_modes(
    tmp_path: Path,
    target: str,
    unsafe_mode: int,
    reason: str,
) -> None:
    policy = _build_policy(tmp_path)
    project_root = Path(str(policy["project_root"]))
    if target == "project_root":
        selected = project_root
    elif target == "descendant_directory":
        selected = project_root / "v2/backend/app/services/native_trainer"
    else:
        entries = policy["code_closure"]
        assert type(entries) is list
        selected = project_root / str(entries[0]["relative_path"])
    selected.chmod(unsafe_mode)

    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match=reason):
        _validate(policy)


@pytest.mark.parametrize("unsafe_mode", [0o520, 0o502])
def test_python_policy_and_executable_reject_group_or_other_write_modes(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    policy = _build_policy(tmp_path)
    runtime = policy["python_runtime"]
    assert type(runtime) is dict
    python_path = Path(str(runtime["absolute_path"]))
    python_path.chmod(unsafe_mode)
    runtime["mode_octal"] = f"0{unsafe_mode:03o}"
    runtime["identity_sha256"] = _python_identity_digest(runtime)

    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="python_mode_invalid",
    ):
        _validate(policy)


def test_python_path_symlink_is_rejected_even_when_target_identity_matches(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    runtime = policy["python_runtime"]
    assert type(runtime) is dict
    python_path = Path(str(runtime["absolute_path"]))
    target = python_path.with_name("python-real")
    python_path.rename(target)
    python_path.symlink_to(target)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="python_executable_identity_invalid",
    ):
        _validate(policy)


def test_python_binary_digest_and_structured_identity_are_both_bound(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    runtime = policy["python_runtime"]
    assert type(runtime) is dict
    runtime["identity_sha256"] = "f" * 64
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="python_identity_digest_mismatch",
    ):
        _validate(policy)

    policy = _build_policy(tmp_path / "second")
    runtime = policy["python_runtime"]
    assert type(runtime) is dict
    path = Path(str(runtime["absolute_path"]))
    original = path.read_bytes()
    path.chmod(0o700)
    path.write_bytes(b"x" * len(original))
    path.chmod(0o500)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="python_executable_digest_mismatch",
    ):
        _validate(policy)


@pytest.mark.parametrize("field", ["executable_sha256", "identity_sha256"])
def test_malformed_python_identity_hashes_are_rejected(tmp_path: Path, field: str) -> None:
    policy = _build_policy(tmp_path)
    runtime = policy["python_runtime"]
    assert type(runtime) is dict
    runtime[field] = "ABC"
    with pytest.raises(CanonicalOhlcvHermeticReplayPolicyV4Error, match="digest_invalid"):
        _validate(policy)


def test_ledger_owned_cas_root_mode_and_symlink_identity_fail_closed(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    cas = policy["ledger_owned_cas_root"]
    assert type(cas) is dict
    cas_path = Path(str(cas["absolute_path"]))
    cas_path.chmod(0o755)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error, match="cas_root_identity_invalid"
    ):
        _validate(policy)

    policy = _build_policy(tmp_path / "second")
    cas = policy["ledger_owned_cas_root"]
    assert type(cas) is dict
    cas_path = Path(str(cas["absolute_path"]))
    target = cas_path.with_name("source-cas-real")
    cas_path.rename(target)
    cas_path.symlink_to(target, target_is_directory=True)
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="directory_identity_invalid",
    ):
        _validate(policy)


def test_validation_performs_two_complete_local_filesystem_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _build_policy(tmp_path)
    pass_calls = 0
    hashed_reason_prefixes: list[str] = []
    original_pass = policy_module._verify_local_identity_pass
    original_hash = policy_module._hash_stable_regular_file

    def recording_pass(*args: Any, **kwargs: Any) -> Any:
        nonlocal pass_calls
        pass_calls += 1
        return original_pass(*args, **kwargs)

    def recording_hash(*args: Any, **kwargs: Any) -> Any:
        hashed_reason_prefixes.append(cast(str, kwargs["reason_prefix"]))
        return original_hash(*args, **kwargs)

    monkeypatch.setattr(policy_module, "_verify_local_identity_pass", recording_pass)
    monkeypatch.setattr(policy_module, "_hash_stable_regular_file", recording_hash)

    result = _validate(policy)

    assert pass_calls == 2
    assert hashed_reason_prefixes.count("hermetic_replay_policy_python_executable") == 2
    assert hashed_reason_prefixes.count("hermetic_replay_policy_code_file") == (
        2 * len(PROJECT_CODE_CLOSURE_V4)
    )
    assert len(hashed_reason_prefixes) == 2 * (len(PROJECT_CODE_CLOSURE_V4) + 1)
    assert result["local_filesystem_verification_pass_count"] == 2


@pytest.mark.parametrize(
    "replacement_target",
    ["python_executable", "cas_root", "project_root", "code_file"],
)
def test_path_or_root_replacement_between_complete_passes_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_target: str,
) -> None:
    policy = _build_policy(tmp_path)
    original_pass = policy_module._verify_local_identity_pass
    pass_calls = 0

    def replace_identity() -> None:
        if replacement_target == "python_executable":
            runtime = policy["python_runtime"]
            assert type(runtime) is dict
            path = Path(str(runtime["absolute_path"]))
            payload = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
            path.rename(path.with_name("python-pass-one"))
            path.write_bytes(payload)
            path.chmod(mode)
        elif replacement_target == "cas_root":
            cas = policy["ledger_owned_cas_root"]
            assert type(cas) is dict
            path = Path(str(cas["absolute_path"]))
            path.rename(path.with_name("source-cas-pass-one"))
            path.mkdir()
            path.chmod(0o700)
        elif replacement_target == "project_root":
            path = Path(str(policy["project_root"]))
            prior = path.with_name("project-root-pass-one")
            path.rename(prior)
            shutil.copytree(prior, path, copy_function=shutil.copy2)
        else:
            entries = policy["code_closure"]
            assert type(entries) is list
            path = Path(str(policy["project_root"])) / str(entries[0]["relative_path"])
            payload = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
            replacement = path.with_name(f"{path.name}.pass-two")
            replacement.write_bytes(payload)
            replacement.chmod(mode)
            os.replace(replacement, path)

    def replacing_pass(*args: Any, **kwargs: Any) -> Any:
        nonlocal pass_calls
        result = original_pass(*args, **kwargs)
        pass_calls += 1
        if pass_calls == 1:
            replace_identity()
        return result

    monkeypatch.setattr(policy_module, "_verify_local_identity_pass", replacing_pass)

    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="local_identity_changed_between_verification_passes",
    ):
        _validate(policy)
    assert pass_calls == 2


def test_empty_relevant_init_files_are_valid_code_closure_members(tmp_path: Path) -> None:
    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    first = entries[0]
    path = Path(str(policy["project_root"])) / str(first["relative_path"])
    path.write_bytes(b"")
    first["byte_count"] = 0
    first["sha256"] = hashlib.sha256(b"").hexdigest()

    result = _validate(policy)

    assert result["ordered_code_files_verified_at_validation"] is True


def test_module_imports_only_stdlib_and_has_no_explicit_write_or_process_calls() -> None:
    source = inspect.getsource(policy_module)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)
    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "hashlib",
        "hmac",
        "json",
        "os",
        "re",
        "stat",
        "types",
        "typing",
    }
    assert called_attributes.isdisjoint(
        {
            "chmod",
            "chown",
            "mkdir",
            "makedirs",
            "remove",
            "rename",
            "replace",
            "rmdir",
            "spawn",
            "symlink",
            "truncate",
            "unlink",
            "write",
        }
    )
    assert "performs no filesystem mutation" not in source
    assert "invokes no explicit filesystem write syscall" in source
    assert "may update filesystem access-time metadata" in source


def test_final_file_open_flags_are_nonblocking_nofollow_and_close_on_exec() -> None:
    flags = policy_module._file_flags()
    assert flags & os.O_NONBLOCK
    assert flags & os.O_NOFOLLOW
    assert flags & os.O_CLOEXEC


def test_manifest_names_every_required_replay_dependency_and_package_init() -> None:
    paths = tuple(path for _role, path in PROJECT_CODE_CLOSURE_V4)
    assert paths[:5] == (
        "v2/__init__.py",
        "v2/backend/__init__.py",
        "v2/backend/app/__init__.py",
        "v2/backend/app/services/__init__.py",
        "v2/backend/app/services/native_trainer/__init__.py",
    )
    required_filenames = {
        "canonical_ohlcv_hermetic_replay_protocol_v4.py",
        "canonical_ohlcv_hermetic_replay_worker_v4.py",
        "canonical_ohlcv_hermetic_replay_policy_v4.py",
        "canonical_ohlcv_manifest_semantic_replay_v4.py",
        "immutable_source_payload_reader_v4.py",
        "immutable_source_payload_store.py",
        "ohlcv_closed_window_schema.py",
        "feature_window_dependency_contract.py",
        "source_read_receipt_v4.py",
        "canonical_ohlcv_atomic_receipt_adapter.py",
        "atomic_redis_source_reader.py",
    }
    assert required_filenames <= {Path(path).name for path in paths}
    assert "canonical_ohlcv_positive_semantic_replay_v4.py" not in {
        Path(path).name for path in paths
    }
    assert len(paths) == len(set(paths))


def test_static_replay_dependencies_are_exactly_pinned_in_code_closure(
    tmp_path: Path,
) -> None:
    protocol_path = _REPOSITORY_ROOT / CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
    assert hashlib.sha256(protocol_path.read_bytes()).hexdigest() == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
    )
    pinned = dict(policy_module._PINNED_CODE_SHA256_BY_ROLE)
    assert set(pinned) == {
        role
        for role, _relative_path in PROJECT_CODE_CLOSURE_V4
        if role
        not in {
            "canonical_ohlcv_hermetic_replay_policy_v4",
            "canonical_ohlcv_hermetic_replay_worker_v4",
        }
    }
    for role, relative_path in PROJECT_CODE_CLOSURE_V4:
        if role in pinned:
            assert (
                hashlib.sha256((_REPOSITORY_ROOT / relative_path).read_bytes()).hexdigest()
                == (pinned[role])
            )
    assert pinned["canonical_ohlcv_hermetic_replay_protocol_v4"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
    )
    assert _ACCEPTED_SCHEMAS["hermetic_replay_protocol_contract"] == (
        "canonical_ohlcv_hermetic_replay_protocol_contract_v4"
    )
    assert _ACCEPTED_SCHEMAS["hermetic_replay_request"] == (
        "canonical_ohlcv_hermetic_replay_request_v4"
    )
    assert _ACCEPTED_SCHEMAS["hermetic_replay_policy_channel"] == (
        "canonical_ohlcv_hermetic_replay_policy_channel_v4"
    )
    assert _ACCEPTED_SCHEMAS["selected_row_binding"] == ("canonical_ohlcv_selected_row_binding_v4")

    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    protocol_entries = [
        entry
        for entry in entries
        if type(entry) is dict
        and entry.get("role") == "canonical_ohlcv_hermetic_replay_protocol_v4"
    ]
    assert len(protocol_entries) == 1
    protocol_entry = protocol_entries[0]
    assert protocol_entry["relative_path"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
    )
    assert protocol_entry["sha256"] == CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256

    fixture_protocol_path = Path(str(policy["project_root"])) / str(protocol_entry["relative_path"])
    forged = b"x" * int(protocol_entry["byte_count"])
    fixture_protocol_path.write_bytes(forged)
    protocol_entry["sha256"] = hashlib.sha256(forged).hexdigest()
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="pinned_code_digest_mismatch",
    ):
        _validate(policy)

    policy = _build_policy(tmp_path / "semantic")
    entries = policy["code_closure"]
    assert type(entries) is list
    semantic_entry = next(
        entry
        for entry in entries
        if type(entry) is dict
        and entry.get("role") == "canonical_ohlcv_manifest_semantic_replay_v4"
    )
    semantic_path = Path(str(policy["project_root"])) / str(semantic_entry["relative_path"])
    forged_semantic = semantic_path.read_bytes() + b"\n# alternate semantic implementation\n"
    semantic_path.write_bytes(forged_semantic)
    semantic_entry["byte_count"] = len(forged_semantic)
    semantic_entry["sha256"] = hashlib.sha256(forged_semantic).hexdigest()
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="pinned_code_digest_mismatch",
    ):
        _validate(policy)


def test_worker_path_is_fixed_and_digest_is_policy_bound_not_hardcoded(
    tmp_path: Path,
) -> None:
    assert (
        "expected_worker_sha256"
        not in inspect.signature(validate_canonical_ohlcv_hermetic_replay_policy_v4).parameters
    )

    policy = _build_policy(tmp_path)
    entries = policy["code_closure"]
    assert type(entries) is list
    worker_entries = [
        entry
        for entry in entries
        if type(entry) is dict and entry.get("role") == "canonical_ohlcv_hermetic_replay_worker_v4"
    ]

    assert len(worker_entries) == 1
    assert worker_entries[0]["relative_path"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
    )
    assert "canonical_ohlcv_hermetic_replay_worker_v4" not in (
        policy_module._PINNED_CODE_SHA256_BY_ROLE
    )

    # A changed worker digest can only be accepted as part of a policy whose
    # whole-document digest matches the separately supplied expected digest.
    original_policy_digest = _policy_digest(policy)
    worker_entry = worker_entries[0]
    worker_path = Path(str(policy["project_root"])) / str(worker_entry["relative_path"])
    replacement = b"x" * int(worker_entry["byte_count"])
    worker_path.write_bytes(replacement)
    worker_entry["sha256"] = hashlib.sha256(replacement).hexdigest()
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="policy_digest_mismatch",
    ):
        _validate(policy, expected_digest=original_policy_digest)

    policy = _build_policy(tmp_path / "file-mismatch")
    entries = policy["code_closure"]
    assert type(entries) is list
    worker_entry = next(
        entry
        for entry in entries
        if type(entry) is dict and entry.get("role") == "canonical_ohlcv_hermetic_replay_worker_v4"
    )
    worker_path = Path(str(policy["project_root"])) / str(worker_entry["relative_path"])
    worker_path.write_bytes(b"x" * int(worker_entry["byte_count"]))
    with pytest.raises(
        CanonicalOhlcvHermeticReplayPolicyV4Error,
        match="code_file_digest_mismatch",
    ):
        _validate(policy)


def test_mode_rendering_used_by_fixture_matches_real_stat_contract(tmp_path: Path) -> None:
    path = tmp_path / "executable"
    path.write_bytes(b"x")
    path.chmod(0o500)
    assert f"0{stat.S_IMODE(path.stat().st_mode):03o}" == "0500"
