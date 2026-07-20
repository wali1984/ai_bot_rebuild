from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import py_compile
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_hermetic_replay_policy_v4 as policy_module,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_hermetic_replay_protocol_v4 as protocol_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_policy_v4 import (
    CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
    PROJECT_CODE_CLOSURE_V4,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_protocol_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION,
    MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4,
    MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4,
    encode_canonical_ohlcv_hermetic_replay_policy_channel_v4,
    encode_canonical_ohlcv_hermetic_replay_request_v4,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_atomic_receipt_adapter as capture_support,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
_WORKER_SOURCE = _REPOSITORY_ROOT / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
_POLICY_SOURCE_RELATIVE_PATH = (
    "v2/backend/app/services/native_trainer/canonical_ohlcv_hermetic_replay_policy_v4.py"
)
_POLICY_SOURCE_SHA256 = "e75b3a9c17980d4d04ab7b0e3fd675ae5d73da19e73e9421fd684bd7a4a54a7e"
_RESULT_DOMAIN_SEPARATOR = b"canonical_ohlcv_hermetic_replay_result_v4/result_sha256/v1\0"
_REGISTRY_ID = "native-trainer-hermetic-replay-policy-registry"
_REGISTRY_VERSION = "registry-v4.1"
_POLICY_ID = "canonical-binance-ohlcv-hermetic-replay"
_POLICY_REVISION = 1


@dataclass(frozen=True, slots=True)
class _WorkerFixture:
    worker_path: Path
    python_path: Path
    channel: bytes
    request: bytes
    expected_request_sha256: str
    expected_policy_sha256: str
    expected_manifest_sha256: str
    expected_selected_row_sha256: str
    project_root: Path
    policy_project_root: Path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _domain_hash(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical(value)).hexdigest()


def _plain_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _rehash_source_receipt(receipt: dict[str, object]) -> None:
    read_evidence = cast(dict[str, object], receipt["read_evidence"])
    finality_evidence = cast(dict[str, object], receipt["finality_evidence"])
    read_sha256 = _plain_hash(read_evidence)
    receipt["read_evidence_sha256"] = read_sha256
    finality_evidence["read_evidence_sha256"] = read_sha256
    receipt["finality_evidence_sha256"] = _plain_hash(finality_evidence)
    receipt_material = dict(receipt)
    receipt_material.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = _plain_hash(receipt_material)


def _address_material(address: object) -> dict[str, object]:
    address_value = cast(Any, address)
    return {
        "schema_version": address_value.schema_version,
        "payload_sha256": address_value.payload_sha256,
        "payload_byte_count": address_value.payload_byte_count,
        "relative_path": address_value.relative_path,
    }


def _decision_time(consumer_observed_at: str) -> str:
    observed = datetime.strptime(consumer_observed_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return (
        (observed + timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _tamper_selected_result_after_its_digest(source: bytes) -> bytes:
    needle = b"    return MappingProxyType(detached_result)\n\n\n__all__ = ["
    replacement = (
        b'    detached_result["matched_candle_id"] = "tampered-after-digest"\n'
        b"    return MappingProxyType(detached_result)\n\n\n__all__ = ["
    )
    assert source.count(needle) == 1
    return source.replace(needle, replacement)


def _fabricate_self_digested_selected_result(source: bytes) -> bytes:
    needle = b"        result = _validate_selected_row_binding(raw_result, oracle=binding_oracle)\n"
    replacement = (
        b"        fabricated_result = dict(raw_result)\n"
        b'        fabricated_result["matched_candle_id"] = "ffffffffffffffffffffffff"\n'
        b'        del fabricated_result["selected_row_binding_sha256"]\n'
        b'        fabricated_result["selected_row_binding_sha256"] = _domain_hash(\n'
        b"            CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_DOMAIN_SEPARATOR,\n"
        b"            fabricated_result,\n"
        b"        )\n"
        b"        raw_result = MappingProxyType(fabricated_result)\n"
        b"        result = _validate_selected_row_binding(raw_result, oracle=binding_oracle)\n"
    )
    assert source.count(needle) == 1
    return source.replace(needle, replacement)


def _fabricate_self_digested_base_replay_sha256(source: bytes) -> bytes:
    needle = b"        result = _validate_selected_row_binding(raw_result, oracle=binding_oracle)\n"
    replacement = (
        b"        fabricated_result = dict(raw_result)\n"
        b'        fabricated_result["base_replay_sha256"] = "0" * 64\n'
        b'        del fabricated_result["selected_row_binding_sha256"]\n'
        b'        fabricated_result["selected_row_binding_sha256"] = _domain_hash(\n'
        b"            CANONICAL_OHLCV_SELECTED_ROW_BINDING_V4_DOMAIN_SEPARATOR,\n"
        b"            fabricated_result,\n"
        b"        )\n"
        b"        raw_result = MappingProxyType(fabricated_result)\n"
        b"        result = _validate_selected_row_binding(raw_result, oracle=binding_oracle)\n"
    )
    assert source.count(needle) == 1
    return source.replace(needle, replacement)


def _copy_policy_project(
    destination: Path,
    *,
    tamper_semantic_result: bool = False,
    tamper_bootstrap_role: str | None = None,
    fabricate_worker_result: bool = False,
    fabricate_base_replay_sha256: bool = False,
    install_unchecked_semantic_pyc: bool = False,
) -> None:
    semantic_role = "canonical_ohlcv_manifest_semantic_replay_v4"
    for role, relative_path in PROJECT_CODE_CLOSURE_V4:
        source = _REPOSITORY_ROOT / relative_path
        payload = source.read_bytes()
        if tamper_semantic_result and role == semantic_role:
            payload = _tamper_selected_result_after_its_digest(payload)
        if tamper_bootstrap_role == role:
            payload += b"\n# bootstrap digest tamper\n"
        if fabricate_worker_result and role == "canonical_ohlcv_hermetic_replay_worker_v4":
            payload = _fabricate_self_digested_selected_result(payload)
        if fabricate_base_replay_sha256 and role == "canonical_ohlcv_hermetic_replay_worker_v4":
            payload = _fabricate_self_digested_base_replay_sha256(payload)
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        target.chmod(0o644)
    destination.chmod(0o755)
    for path in destination.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
    if install_unchecked_semantic_pyc:
        semantic_path = destination / next(
            relative_path
            for role, relative_path in PROJECT_CODE_CLOSURE_V4
            if role == semantic_role
        )
        malicious_source = destination / "malicious_unchecked_semantic.py"
        malicious_source.write_text(
            'raise RuntimeError("unchecked pyc executed")\n',
            encoding="utf-8",
        )
        pyc_path = (
            semantic_path.parent
            / "__pycache__"
            / f"{semantic_path.stem}.{sys.implementation.cache_tag}.pyc"
        )
        pyc_path.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(
            str(malicious_source),
            cfile=str(pyc_path),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        malicious_source.unlink()


def _python_runtime(python_path: Path) -> dict[str, object]:
    payload = python_path.read_bytes()
    metadata = python_path.stat()
    mode = f"0{stat.S_IMODE(metadata.st_mode):03o}"
    runtime: dict[str, object] = {
        "identity_schema_version": "canonical_ohlcv_hermetic_python_identity_v4",
        "absolute_path": str(python_path),
        "implementation": "CPython",
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "isolated_flags": ["-I", "-S", "-B"],
        "owner_uid": metadata.st_uid,
        "mode_octal": mode,
        "executable_byte_count": len(payload),
        "executable_sha256": hashlib.sha256(payload).hexdigest(),
        "identity_sha256": "",
    }
    material = {key: value for key, value in runtime.items() if key != "identity_sha256"}
    runtime["identity_sha256"] = _domain_hash(
        CANONICAL_OHLCV_HERMETIC_PYTHON_IDENTITY_V4_DOMAIN_SEPARATOR,
        material,
    )
    return runtime


def _code_closure(project_root: Path) -> list[dict[str, object]]:
    closure: list[dict[str, object]] = []
    for ordinal, (role, relative_path) in enumerate(PROJECT_CODE_CLOSURE_V4):
        payload = (project_root / relative_path).read_bytes()
        closure.append(
            {
                "ordinal": ordinal,
                "role": role,
                "relative_path": relative_path,
                "byte_count": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return closure


def _policy_document(
    *,
    project_root: Path,
    cas_root: Path,
    python_path: Path,
) -> tuple[bytes, str]:
    cas_root.chmod(0o700)
    policy: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
        "contract_version": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REVISION,
        "registry_id": _REGISTRY_ID,
        "registry_version": _REGISTRY_VERSION,
        "project_root": str(project_root),
        "project_owner_uid": os.geteuid(),
        "python_runtime": _python_runtime(python_path),
        "ledger_owned_cas_root": {
            "absolute_path": str(cas_root),
            "owner_uid": os.geteuid(),
            "required_mode_octal": "0700",
            "namespace": "sha256",
            "ownership_model": "SOURCE_PROVENANCE_LEDGER_OWNED_IMMUTABLE_CAS_V1",
            "access_mode": "READ_ONLY_HERMETIC_REPLAY",
            "request_selectable": False,
        },
        "canonical_profile": dict(policy_module._CANONICAL_PROFILE),
        "accepted_schemas": dict(policy_module._ACCEPTED_SCHEMAS),
        "worker": dict(policy_module._WORKER_POLICY),
        "code_closure": _code_closure(project_root),
        "resource_ceilings": dict(policy_module._RESOURCE_CEILINGS),
        "worker_protocol": dict(policy_module._WORKER_PROTOCOL),
        "authority_policy": dict(policy_module._AUTHORITY_POLICY),
        "audit_only": True,
    }
    document = _canonical(policy)
    digest = hashlib.sha256(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_DOMAIN_SEPARATOR + document
    ).hexdigest()
    return document, digest


def _build_worker_fixture(
    tmp_path: Path,
    *,
    alternate_policy_root: bool = False,
    tamper_semantic_result: bool = False,
    fabricate_worker_result: bool = False,
    fabricate_base_replay_sha256: bool = False,
    install_unchecked_semantic_pyc: bool = False,
    tamper_full_source_span: bool = False,
    tamper_manifest_consumer_ms_type: bool = False,
    tamper_receipt_nested_type: str | None = None,
    tamper_selected_open_time_type: bool = False,
) -> _WorkerFixture:
    capture_root = tmp_path / "capture"
    capture_root.mkdir(parents=True)
    capture, _, store = capture_support._capture(capture_root)
    cas_root = Path(store.root_path)
    cas_root.chmod(0o700)
    manifest_address = capture.suffix_manifest_address
    selected = capture.selected_candles[-1]
    selected_address = selected.source_payload_address
    if (
        tamper_full_source_span
        or tamper_manifest_consumer_ms_type
        or tamper_receipt_nested_type is not None
        or tamper_selected_open_time_type
    ):
        manifest_payload = store.get(
            manifest_address.payload_sha256,
            expected_byte_count=manifest_address.payload_byte_count,
        )
        manifest = cast(dict[str, object], json.loads(manifest_payload))
        if tamper_full_source_span:
            full_source_address = cast(
                dict[str, object],
                manifest["full_source_payload_cas_address"],
            )
            full_source_count = cast(int, full_source_address["payload_byte_count"])
            replacement_address = store.put(b"!" * full_source_count)
            manifest["full_source_payload_cas_address"] = _address_material(replacement_address)
        if tamper_manifest_consumer_ms_type:
            manifest["consumer_observed_at_ms"] = float(
                cast(int, manifest["consumer_observed_at_ms"])
            )
        if tamper_receipt_nested_type is not None:
            selected_rows = cast(list[object], manifest["selected_rows"])
            selected_manifest_row = cast(dict[str, object], selected_rows[-1])
            receipt = cast(
                dict[str, object],
                selected_manifest_row["source_read_receipt_v4"],
            )
            if tamper_receipt_nested_type == "float_payload_byte_count":
                read_evidence = cast(dict[str, object], receipt["read_evidence"])
                read_evidence["payload_byte_count"] = float(
                    cast(int, read_evidence["payload_byte_count"])
                )
            elif tamper_receipt_nested_type == "int_event_final":
                finality_evidence = cast(
                    dict[str, object],
                    receipt["finality_evidence"],
                )
                finality_evidence["event_final"] = 1
            else:
                raise AssertionError("unsupported receipt type tamper")
            _rehash_source_receipt(receipt)
        if tamper_selected_open_time_type:
            selected_rows = cast(list[object], manifest["selected_rows"])
            selected_manifest_row = cast(dict[str, object], selected_rows[-1])
            original_row_payload = store.get(
                selected_address.payload_sha256,
                expected_byte_count=selected_address.payload_byte_count,
            )
            selected_row = cast(dict[str, object], json.loads(original_row_payload))
            selected_row["open_time"] = float(cast(int, selected_row["open_time"]))
            replacement_row_payload = _canonical(selected_row)
            replacement_row_address = store.put(replacement_row_payload)
            full_source_address = cast(
                dict[str, object],
                manifest["full_source_payload_cas_address"],
            )
            original_full_source = store.get(
                cast(str, full_source_address["payload_sha256"]),
                expected_byte_count=cast(int, full_source_address["payload_byte_count"]),
            )
            byte_start = cast(int, selected_manifest_row["byte_start"])
            original_byte_end = cast(int, selected_manifest_row["byte_end_exclusive"])
            replacement_full_source = (
                original_full_source[:byte_start]
                + replacement_row_payload
                + original_full_source[original_byte_end:]
            )
            replacement_full_address = store.put(replacement_full_source)
            manifest["full_source_payload_cas_address"] = _address_material(
                replacement_full_address
            )
            selected_manifest_row["byte_end_exclusive"] = byte_start + len(replacement_row_payload)
            selected_manifest_row["exact_payload_sha256"] = replacement_row_address.payload_sha256
            selected_manifest_row["exact_payload_byte_count"] = (
                replacement_row_address.payload_byte_count
            )
            selected_manifest_row["source_payload_cas_address"] = _address_material(
                replacement_row_address
            )
            selected_address = replacement_row_address
        manifest_address = store.put(_canonical(manifest))
    execution_root = tmp_path / "execution root"
    _copy_policy_project(
        execution_root,
        tamper_semantic_result=tamper_semantic_result,
        fabricate_worker_result=fabricate_worker_result,
        fabricate_base_replay_sha256=fabricate_base_replay_sha256,
        install_unchecked_semantic_pyc=install_unchecked_semantic_pyc,
    )
    policy_root = execution_root
    if alternate_policy_root:
        policy_root = tmp_path / "policy root"
        _copy_policy_project(policy_root)

    python_path = Path(sys.executable).resolve(strict=True)
    policy_document, policy_sha256 = _policy_document(
        project_root=policy_root,
        cas_root=cas_root,
        python_path=python_path,
    )
    channel = encode_canonical_ohlcv_hermetic_replay_policy_channel_v4(
        expected_policy_sha256=policy_sha256,
        expected_registry_id=_REGISTRY_ID,
        expected_registry_version=_REGISTRY_VERSION,
        expected_policy_id=_POLICY_ID,
        expected_policy_revision=_POLICY_REVISION,
        policy_document=policy_document,
    )
    request = encode_canonical_ohlcv_hermetic_replay_request_v4(
        request_nonce="a" * 64,
        run_id="run-hermetic-v4",
        cycle_id="cycle-hermetic-v4",
        decision_id="decision-hermetic-v4",
        manifest_address=_address_material(manifest_address),
        selected_row_address=_address_material(selected_address),
        symbol=capture_support.SYMBOL,
        timeframe=capture_support.TIMEFRAME,
        decision_time=_decision_time(capture.consumer_observed_at),
    )
    validated_request = protocol_module.validate_canonical_ohlcv_hermetic_replay_request_v4(request)
    return _WorkerFixture(
        worker_path=execution_root / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        python_path=python_path,
        channel=channel,
        request=request,
        expected_request_sha256=cast(str, validated_request["request_sha256"]),
        expected_policy_sha256=policy_sha256,
        expected_manifest_sha256=manifest_address.payload_sha256,
        expected_selected_row_sha256=selected_address.payload_sha256,
        project_root=execution_root,
        policy_project_root=policy_root,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        assert written > 0
        offset += written


def _memfd(payload: bytes, *, sealed: bool, read_only: bool) -> int:
    descriptor = os.memfd_create("canonical-ohlcv-policy-v4", os.MFD_ALLOW_SEALING)
    _write_all(descriptor, payload)
    if sealed:
        seal_mask = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seal_mask)
    if not read_only:
        return descriptor
    read_descriptor = os.open(f"/proc/self/fd/{descriptor}", os.O_RDONLY | os.O_CLOEXEC)
    os.close(descriptor)
    return read_descriptor


def _invoke(
    *,
    worker_path: Path,
    python_path: Path,
    request: bytes,
    channel: bytes,
    sealed: bool = True,
    read_only: bool = True,
    isolated: bool = True,
    optimize: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    descriptor = _memfd(channel, sealed=sealed, read_only=read_only)
    flags = ["-I", "-S", "-B"] if isolated else []
    if optimize:
        flags.append("-O")
    try:
        return subprocess.run(  # noqa: S603 - exact pinned interpreter and fixture worker
            [
                str(python_path),
                *flags,
                str(worker_path),
                "--policy-fd",
                str(descriptor),
            ],
            input=request,
            capture_output=True,
            check=False,
            pass_fds=(descriptor,),
            timeout=60,
        )
    finally:
        os.close(descriptor)


def _assert_error(
    process: subprocess.CompletedProcess[bytes],
    reason: str,
) -> dict[str, object]:
    assert process.returncode == 2
    assert process.stdout == b""
    assert b"Traceback" not in process.stderr
    assert 1 <= len(process.stderr) <= 2048
    parsed = cast(dict[str, object], json.loads(process.stderr))
    assert process.stderr == _canonical(parsed)
    assert parsed == {
        "schema_version": "canonical_ohlcv_hermetic_replay_error_v4",
        "reason": reason,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "audit_only": True,
    }
    return parsed


def test_worker_source_bootstrap_is_stdlib_only_and_frozen_inputs_match() -> None:
    source = _WORKER_SOURCE.read_bytes()
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {
        "__future__",
        "fcntl",
        "hashlib",
        "hmac",
        "importlib",
        "json",
        "math",
        "os",
        "re",
        "stat",
        "sys",
        "types",
        "typing",
        "datetime",
    }
    assert not any(root == "v2" for root in imported_roots)
    assert (
        hashlib.sha256(
            (
                _REPOSITORY_ROOT / CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_RELATIVE_PATH
            ).read_bytes()
        ).hexdigest()
        == CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256
    )
    assert (
        hashlib.sha256((_REPOSITORY_ROOT / _POLICY_SOURCE_RELATIVE_PATH).read_bytes()).hexdigest()
        == _POLICY_SOURCE_SHA256
    )


def test_nonisolated_process_and_direct_module_call_fail_before_bootstrap() -> None:
    python_path = Path(sys.executable).resolve(strict=True)
    nonisolated = subprocess.run(  # noqa: S603 - exact resolved interpreter and worker
        [str(python_path), str(_WORKER_SOURCE), "--policy-fd", "3"],
        input=b"{}",
        capture_output=True,
        check=False,
        timeout=15,
    )
    _assert_error(nonisolated, "hermetic_replay_worker_isolated_python_flags_required")

    direct_code = "\n".join(
        (
            "import importlib.util, sys",
            "path = sys.argv[1]",
            "spec = importlib.util.spec_from_file_location('_direct_worker_probe', path)",
            "module = importlib.util.module_from_spec(spec)",
            "sys.modules[spec.name] = module",
            "spec.loader.exec_module(module)",
            "raise SystemExit(module.main())",
        )
    )
    direct = subprocess.run(  # noqa: S603 - exact resolved interpreter and fixed probe
        [str(python_path), "-I", "-S", "-B", "-c", direct_code, str(_WORKER_SOURCE)],
        capture_output=True,
        check=False,
        timeout=15,
    )
    _assert_error(direct, "hermetic_replay_worker_direct_script_invocation_required")


def test_optimized_interpreter_flags_are_rejected(tmp_path: Path) -> None:
    fixture = _build_worker_fixture(tmp_path)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
        optimize=True,
    )
    _assert_error(process, "hermetic_replay_worker_isolated_python_flags_required")


@pytest.mark.parametrize(
    ("sealed", "read_only", "reason"),
    [
        (False, True, "hermetic_replay_worker_policy_fd_immutable_seals_required"),
        (True, False, "hermetic_replay_worker_policy_fd_read_only_required"),
    ],
)
def test_policy_fd_requires_all_memfd_seals_and_read_only_access(
    tmp_path: Path,
    sealed: bool,
    read_only: bool,
    reason: str,
) -> None:
    project_root = tmp_path / "project"
    _copy_policy_project(project_root)
    process = _invoke(
        worker_path=project_root / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        python_path=Path(sys.executable).resolve(strict=True),
        request=b"{}",
        channel=b"{}",
        sealed=sealed,
        read_only=read_only,
    )
    _assert_error(process, reason)


def test_named_regular_file_cannot_impersonate_sealed_policy_memfd(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _copy_policy_project(project_root)
    with tempfile.TemporaryFile() as policy_file:
        policy_file.write(b"{}")
        policy_file.flush()
        policy_file.seek(0)
        read_descriptor = os.open(
            f"/proc/self/fd/{policy_file.fileno()}",
            os.O_RDONLY | os.O_CLOEXEC,
        )
        try:
            process = subprocess.run(  # noqa: S603 - exact interpreter and fixture worker
                [
                    str(Path(sys.executable).resolve(strict=True)),
                    "-I",
                    "-S",
                    "-B",
                    str(project_root / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH),
                    "--policy-fd",
                    str(read_descriptor),
                ],
                input=b"{}",
                capture_output=True,
                check=False,
                pass_fds=(read_descriptor,),
                timeout=15,
            )
        finally:
            os.close(read_descriptor)
    _assert_error(process, "hermetic_replay_worker_policy_fd_memfd_identity_invalid")


def test_policy_channel_oversize_malformed_and_trailing_frames_fail_closed(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _copy_policy_project(project_root)
    worker_path = project_root / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH
    python_path = Path(sys.executable).resolve(strict=True)
    oversized = _invoke(
        worker_path=worker_path,
        python_path=python_path,
        request=b"{}",
        channel=b"x" * (MAX_HERMETIC_REPLAY_POLICY_CHANNEL_BYTES_V4 + 1),
    )
    _assert_error(oversized, "hermetic_replay_worker_policy_channel_size_invalid")
    malformed = _invoke(
        worker_path=worker_path,
        python_path=python_path,
        request=b"{}",
        channel=b"{}",
    )
    _assert_error(malformed, "hermetic_replay_worker_policy_channel_invalid")

    fixture = _build_worker_fixture(tmp_path / "trailing")
    trailing = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel + b"\n",
    )
    _assert_error(trailing, "hermetic_replay_worker_policy_channel_invalid")


@pytest.mark.parametrize(
    ("request_mutator", "reason"),
    [
        (
            lambda request: b"x" * (MAX_HERMETIC_REPLAY_REQUEST_BYTES_V4 + 1),
            "hermetic_replay_worker_request_size_exceeded",
        ),
        (lambda request: b"{}", "hermetic_replay_worker_request_invalid"),
        (lambda request: request + b"\n", "hermetic_replay_worker_request_invalid"),
        (
            lambda request: request.replace(b'"symbol":"BTCUSDT"', b'"symbol":"ETHUSDT"'),
            "hermetic_replay_worker_request_invalid",
        ),
    ],
)
def test_request_oversize_malformed_trailing_and_digest_tamper_fail_closed(
    tmp_path: Path,
    request_mutator: Any,
    reason: str,
) -> None:
    fixture = _build_worker_fixture(tmp_path)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=cast(Any, request_mutator)(fixture.request),
        channel=fixture.channel,
    )
    _assert_error(process, reason)


def test_success_is_deterministic_bounded_scalar_and_source_path_hash_bound(
    tmp_path: Path,
) -> None:
    fixture = _build_worker_fixture(tmp_path)
    first = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    second = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout
    assert 1 <= len(first.stdout) <= 64 * 1024
    result = cast(dict[str, object], json.loads(first.stdout))
    assert first.stdout == _canonical(result)
    assert all(type(value) in {str, int, bool} or value is None for value in result.values())
    assert result["schema_version"] == "canonical_ohlcv_hermetic_replay_result_v4"
    assert result["contract_version"] == (
        CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_CONTRACT_VERSION
    )
    assert result["request_sha256"] == fixture.expected_request_sha256
    assert result["policy_sha256"] == fixture.expected_policy_sha256
    assert result["manifest_sha256"] == fixture.expected_manifest_sha256
    assert result["selected_row_payload_sha256"] == fixture.expected_selected_row_sha256
    assert result["project_root"] == str(fixture.project_root)
    assert result["policy_channel_sealing_verified"] is True
    assert result["policy_channel_immutability_verified"] is True
    assert result["worker_source_path_hash_matched_at_validation"] is True
    assert result["executing_interpreter_inode_and_hash_matched_at_validation"] is True
    assert result["frozen_sources_reverified_at_validation"] is True
    assert result["loaded_project_modules_sourced_only_from_captured_bytes_at_validation"] is True
    assert result["package_initializer_sources_executed_at_validation"] is False
    assert result["project_root_added_to_sys_path_at_validation"] is False
    assert result["selected_row_binding_replayed"] is True
    assert result["runtime_network_disable_required"] is True
    assert result["runtime_filesystem_write_disable_required"] is True
    assert result["generated_at"] is None
    assert result["execution_time"] is None
    for field in (
        "policy_source_authenticated",
        "runtime_dependency_closure_verified",
        "runtime_sandbox_enforced",
        "runtime_network_disabled",
        "runtime_filesystem_write_disabled",
        "systemd_unit_verified",
        "systemd_sandbox_enforced",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_wired",
    ):
        assert result[field] is False
    assert result["audit_only"] is True
    supplied_digest = cast(str, result.pop("result_sha256"))
    assert supplied_digest == _domain_hash(_RESULT_DOMAIN_SEPARATOR, result)

    tampered = dict(result)
    tampered["matched_candle_id"] = "tampered"
    assert supplied_digest != _domain_hash(_RESULT_DOMAIN_SEPARATOR, tampered)


@pytest.mark.parametrize(
    ("role", "reason"),
    [
        (
            "canonical_ohlcv_hermetic_replay_protocol_v4",
            "hermetic_replay_worker_protocol_source_digest_mismatch",
        ),
        (
            "canonical_ohlcv_hermetic_replay_policy_v4",
            "hermetic_replay_worker_policy_source_digest_mismatch",
        ),
    ],
)
def test_frozen_bootstrap_source_hash_mismatch_fails_before_channel_trust(
    tmp_path: Path,
    role: str,
    reason: str,
) -> None:
    project_root = tmp_path / "project"
    _copy_policy_project(project_root, tamper_bootstrap_role=role)
    process = _invoke(
        worker_path=project_root / CANONICAL_OHLCV_HERMETIC_REPLAY_WORKER_V4_RELATIVE_PATH,
        python_path=Path(sys.executable).resolve(strict=True),
        request=b"{}",
        channel=b"{}",
    )
    _assert_error(process, reason)


def test_policy_validated_alternate_project_root_cannot_redirect_worker(tmp_path: Path) -> None:
    fixture = _build_worker_fixture(tmp_path, alternate_policy_root=True)
    assert fixture.project_root != fixture.policy_project_root
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_policy_runtime_coordinate_mismatch")


def test_policy_pinned_semantic_dependency_mutation_is_rejected(tmp_path: Path) -> None:
    fixture = _build_worker_fixture(tmp_path, tamper_semantic_result=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_policy_invalid")


def test_self_digested_fabricated_selected_result_is_rejected_by_cas_oracle(
    tmp_path: Path,
) -> None:
    fixture = _build_worker_fixture(tmp_path, fabricate_worker_result=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_binding_invalid")


def test_self_digested_fabricated_base_replay_sha256_is_rejected(
    tmp_path: Path,
) -> None:
    fixture = _build_worker_fixture(tmp_path, fabricate_base_replay_sha256=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_binding_invalid")


def test_full_source_cas_span_must_equal_selected_row_cas_bytes(tmp_path: Path) -> None:
    fixture = _build_worker_fixture(tmp_path, tamper_full_source_span=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_oracle_span_invalid")


def test_manifest_consumer_observed_milliseconds_requires_exact_integer_type(
    tmp_path: Path,
) -> None:
    fixture = _build_worker_fixture(tmp_path, tamper_manifest_consumer_ms_type=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_oracle_invalid")


@pytest.mark.parametrize(
    "type_tamper",
    ["float_payload_byte_count", "int_event_final"],
)
def test_nested_receipt_requires_recursive_exact_types_with_recomputed_digests(
    tmp_path: Path,
    type_tamper: str,
) -> None:
    fixture = _build_worker_fixture(
        tmp_path,
        tamper_receipt_nested_type=type_tamper,
    )
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_oracle_receipt_invalid")


def test_selected_row_time_alias_requires_exact_integer_with_recomputed_cas(
    tmp_path: Path,
) -> None:
    fixture = _build_worker_fixture(tmp_path, tamper_selected_open_time_type=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    _assert_error(process, "hermetic_replay_worker_selected_row_oracle_invalid")


def test_unchecked_semantic_pyc_is_never_loaded(tmp_path: Path) -> None:
    fixture = _build_worker_fixture(tmp_path, install_unchecked_semantic_pyc=True)
    process = _invoke(
        worker_path=fixture.worker_path,
        python_path=fixture.python_path,
        request=fixture.request,
        channel=fixture.channel,
    )
    assert process.returncode == 0
    assert process.stderr == b""
    parsed = cast(dict[str, object], json.loads(process.stdout))
    assert parsed["selected_row_binding_replayed"] is True
    assert parsed["loaded_project_modules_sourced_only_from_captured_bytes_at_validation"] is True
