"""Current-cycle identity and independently revalidated trainer evidence.

The helpers in this module intentionally do not infer readiness from historical
counts or cached ``READY`` labels.  Every payload is bound to one collision-
resistant cycle identity and one concrete process-lifetime identity.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

CURRENT_PREDICTION_PUBLICATION_SCHEMA = (
    "v2_native_trainer_current_cycle_prediction_publication_v1"
)
CURRENT_RESOURCE_EVIDENCE_SCHEMA = (
    "v2_native_trainer_current_cycle_cuda_resource_evidence_v1"
)
CURRENT_PARITY_EVIDENCE_SCHEMA = (
    "v2_native_trainer_current_cycle_source_parity_attestation_v1"
)
EXACT_PARITY_MATRIX_SCHEMA = "v2_native_hybrid_exact_method_parity_attestation_v2"
EXECUTED_CONTRACT_RECEIPT_SCHEMA = "v2_executed_contract_test_receipt_v1"
ALLOWED_TRAINER_SERVICE_UNITS = (
    "ai-bot-v2-native-cuda-trainer-persistent.service",
    "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.service",
)
_PROCESS_INSTANCE_NONCE = uuid.uuid4().hex


def utc_now_microseconds() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def process_instance_id(*, hostname: str | None = None, pid: int | None = None) -> str:
    resolved_pid = os.getpid() if pid is None else int(pid)
    if resolved_pid <= 0:
        raise ValueError("process_instance_pid_must_be_positive")
    resolved_hostname = str(hostname or socket.gethostname()).strip()
    if not resolved_hostname:
        raise ValueError("process_instance_hostname_missing")
    # PIDs are reusable.  The import-time nonce is stable for this process but
    # changes after every restart, preventing a stale heartbeat from binding to
    # a different process that inherited the same hostname/PID pair.
    return f"{resolved_hostname}:{resolved_pid}:{_PROCESS_INSTANCE_NONCE}"


def capture_cycle_identity() -> dict[str, Any]:
    """Capture one collision-resistant identity before a trainer cycle starts."""

    generated_utc = utc_now_microseconds()
    instance_id = process_instance_id()
    cycle_id = "v2_cycle_" + uuid.uuid4().hex
    return {
        "cycle_id": cycle_id,
        "process_instance_id": instance_id,
        "process_id": os.getpid(),
        "cycle_started_utc": generated_utc,
    }


def _systemctl_show(unit: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "--property=LoadState,ActiveState,SubState,MainPID",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return {}
    if result.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def current_process_service_evidence(
    *,
    expected_process_instance_id: str,
    units: Iterable[str] = ALLOWED_TRAINER_SERVICE_UNITS,
) -> dict[str, Any]:
    """Return evidence only when exactly one allowed active unit owns this PID."""

    pid = os.getpid()
    expected = process_instance_id(pid=pid)
    if expected_process_instance_id != expected:
        return {}
    matches: list[tuple[str, dict[str, str]]] = []
    for unit in units:
        state = _systemctl_show(str(unit))
        try:
            main_pid = int(state.get("MainPID") or 0)
        except (TypeError, ValueError):
            main_pid = 0
        if (
            state.get("LoadState") == "loaded"
            and state.get("ActiveState") == "active"
            and state.get("SubState") == "running"
            and main_pid == pid
        ):
            matches.append((str(unit), state))
    if len(matches) != 1:
        return {}
    unit, state = matches[0]
    return {
        "service_active": True,
        "service_unit": unit,
        "service_substate": state.get("SubState"),
        "process_id": pid,
        "process_instance_id": expected,
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_hybrid_methods(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "HybridTrainer":
            return [
                {
                    "method": child.name,
                    "lineno": child.lineno,
                    "end_lineno": getattr(child, "end_lineno", None),
                }
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    raise ValueError("legacy_hybrid_trainer_class_missing")


def _qualified_symbol_exists(path: Path, qualified_name: str) -> bool:
    parts = [part for part in str(qualified_name).split(".") if part]
    if not parts:
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: list[ast.AST] = list(tree.body)
    for index, part in enumerate(parts):
        matches = [
            node
            for node in nodes
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            )
            and node.name == part
        ]
        if len(matches) != 1:
            return False
        selected = matches[0]
        if index == len(parts) - 1:
            return True
        nodes = list(getattr(selected, "body", ()))
    return False


def _resolved_attested_source(
    *,
    repo_root: Path,
    attestation: Mapping[str, Any],
    required_prefix: str,
) -> tuple[Path, str] | None:
    relative = str(attestation.get("path") or "")
    expected_hash = str(attestation.get("source_sha256") or "")
    qualified_name = str(attestation.get("qualified_name") or "")
    if (
        not relative.startswith(required_prefix)
        or not relative.endswith(".py")
        or len(expected_hash) != 64
        or not qualified_name
    ):
        return None
    try:
        candidate = (repo_root / relative).resolve(strict=True)
        candidate.relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if _sha256_path(candidate) != expected_hash:
        return None
    try:
        symbol_exists = _qualified_symbol_exists(candidate, qualified_name)
    except (OSError, SyntaxError, TypeError, ValueError):
        return None
    return (candidate, qualified_name) if symbol_exists else None


def _executed_contract_receipt_valid(
    *,
    receipt: Mapping[str, Any],
    expected_test_path: str,
    expected_test_name: str,
    expected_test_source_sha256: str,
    expected_production_source_digest: str,
    expected_cycle_id: str,
    expected_process_instance_id: str,
    observed_at: datetime,
) -> bool:
    payload = dict(receipt)
    claimed_digest = str(payload.pop("receipt_sha256", ""))
    executed_utc = str(payload.get("executed_utc") or "")
    try:
        parsed = datetime.fromisoformat(executed_utc.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    parsed = parsed.astimezone(timezone.utc)
    return bool(
        parsed <= observed_at
        and receipt.get("schema_version") == EXECUTED_CONTRACT_RECEIPT_SCHEMA
        and receipt.get("cycle_id") == expected_cycle_id
        and receipt.get("process_instance_id")
        == expected_process_instance_id
        and receipt.get("pytest_nodeid")
        == f"{expected_test_path}::{expected_test_name}"
        and receipt.get("outcome") == "PASSED"
        and receipt.get("exit_code") == 0
        and receipt.get("test_source_sha256") == expected_test_source_sha256
        and receipt.get("production_source_set_digest")
        == expected_production_source_digest
        and len(str(receipt.get("runner_command_sha256") or "")) == 64
        and claimed_digest == canonical_sha256(payload)
    )


def build_current_cycle_parity_attestation(
    *,
    repo_root: Path,
    cycle_id: str,
    process_instance_id: str,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Revalidate the durable method-parity matrix against current source.

    A prior ``READY`` label is never copied.  The current legacy AST inventory,
    every durable matrix row, and every native trainer Python source are read and
    parsed again.  Missing/corrupt sources produce a present-cycle BLOCKED
    attestation rather than an invented parity claim.
    """

    observed_utc = generated_utc or utc_now_microseconds()
    try:
        observed_at = datetime.fromisoformat(
            observed_utc.replace("Z", "+00:00")
        )
    except ValueError:
        observed_at = None
    observed_at_valid = bool(
        observed_at is not None
        and observed_at.tzinfo is not None
        and observed_at.utcoffset() is not None
    )
    if not observed_at_valid:
        observed_at = datetime.min.replace(tzinfo=timezone.utc)
    legacy_path = repo_root / "v2/legacy_owned_runtime/rl/hybrid_trainer.py"
    native_root = repo_root / "v2/backend/app/services/native_trainer/hybrid_cuda_trainer"
    matrix_path = repo_root / (
        "v2/frontend/public/"
        "v2_native_hybrid_trainer_full_function_parity_and_paper_reverify/"
        "latest/hybrid_trainer_324_method_parity_matrix.json"
    )
    reasons: list[str] = []
    if not observed_at_valid:
        reasons.append("CURRENT_PARITY_GENERATED_AT_NOT_STRICT_UTC")
    legacy_methods: list[dict[str, Any]] = []
    matrix: dict[str, Any] = {}
    matrix_hash: str | None = None
    legacy_hash: str | None = None
    native_hashes: dict[str, str] = {}
    try:
        legacy_methods = _legacy_hybrid_methods(legacy_path)
        legacy_hash = _sha256_path(legacy_path)
    except (OSError, SyntaxError, TypeError, ValueError):
        reasons.append("LEGACY_HYBRID_SOURCE_REVALIDATION_FAILED")
    try:
        loaded = json.loads(matrix_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("matrix_not_mapping")
        matrix = loaded
        matrix_hash = _sha256_path(matrix_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        reasons.append("DURABLE_PARITY_MATRIX_REVALIDATION_FAILED")

    native_paths = sorted(native_root.glob("*.py"))
    if not native_paths:
        reasons.append("NATIVE_TRAINER_SOURCE_SET_MISSING")
    for path in native_paths:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            native_hashes[path.name] = _sha256_path(path)
        except (OSError, SyntaxError, TypeError, ValueError):
            reasons.append(f"NATIVE_TRAINER_SOURCE_REVALIDATION_FAILED:{path.name}")

    matrix_rows = matrix.get("methods")
    if not isinstance(matrix_rows, list):
        matrix_rows = []
        reasons.append("DURABLE_PARITY_MATRIX_METHOD_ROWS_MISSING")
    normalized_rows: list[dict[str, Any]] = []
    for row in matrix_rows:
        if not isinstance(row, Mapping):
            reasons.append("DURABLE_PARITY_MATRIX_ROW_INVALID")
            continue
        normalized_rows.append(
            {
                "method": row.get("method"),
                "lineno": row.get("lineno"),
                "end_lineno": row.get("end_lineno"),
            }
        )
        if row.get("required_for_full_v2_parity") is True and (
            str(row.get("classification") or "").startswith("MISSING")
            or not str(row.get("native_replacement") or "").strip()
        ):
            reasons.append(
                "DURABLE_PARITY_REQUIRED_METHOD_UNRESOLVED:"
                + str(row.get("method") or "UNKNOWN")
            )
    if legacy_methods and normalized_rows != legacy_methods:
        reasons.append("DURABLE_PARITY_MATRIX_LEGACY_AST_IDENTITY_MISMATCH")
    if legacy_methods and matrix.get("legacy_method_count") != len(legacy_methods):
        reasons.append("DURABLE_PARITY_MATRIX_METHOD_COUNT_MISMATCH")
    if matrix.get("required_missing_count") != 0:
        reasons.append("DURABLE_PARITY_MATRIX_REQUIRED_MISSING_NONZERO")

    exact_mapping_schema = matrix.get("schema_version") == EXACT_PARITY_MATRIX_SCHEMA
    if not exact_mapping_schema:
        reasons.append(
            "DECLARATIVE_PARITY_MATRIX_LACKS_EXACT_SOURCE_AND_EXECUTED_TEST_ATTESTATIONS"
        )
    elif normalized_rows == legacy_methods:
        for row in matrix_rows:
            if not isinstance(row, Mapping) or row.get(
                "required_for_full_v2_parity"
            ) is not True:
                continue
            native_attestations = row.get("native_symbol_attestations")
            contract_attestations = row.get("contract_test_attestations")
            if not isinstance(native_attestations, list) or not native_attestations:
                reasons.append(
                    "EXACT_PARITY_NATIVE_SYMBOL_ATTESTATION_MISSING:"
                    + str(row.get("method") or "UNKNOWN")
                )
                continue
            resolved_native = [
                _resolved_attested_source(
                    repo_root=repo_root,
                    attestation=attestation,
                    required_prefix="v2/backend/app/",
                )
                for attestation in native_attestations
                if isinstance(attestation, Mapping)
            ]
            if len(resolved_native) != len(native_attestations) or any(
                item is None for item in resolved_native
            ):
                reasons.append(
                    "EXACT_PARITY_NATIVE_SYMBOL_ATTESTATION_INVALID:"
                    + str(row.get("method") or "UNKNOWN")
                )
                continue
            production_source_digest = canonical_sha256(
                sorted(
                    {
                        str(attestation.get("path")): str(
                            attestation.get("source_sha256")
                        )
                        for attestation in native_attestations
                        if isinstance(attestation, Mapping)
                    }.items()
                )
            )
            if not isinstance(contract_attestations, list) or not contract_attestations:
                reasons.append(
                    "EXACT_PARITY_EXECUTED_CONTRACT_ATTESTATION_MISSING:"
                    + str(row.get("method") or "UNKNOWN")
                )
                continue
            contract_valid = True
            for attestation in contract_attestations:
                if not isinstance(attestation, Mapping):
                    contract_valid = False
                    break
                resolved_test = _resolved_attested_source(
                    repo_root=repo_root,
                    attestation=attestation,
                    required_prefix="v2/backend/tests/",
                )
                receipt = attestation.get("executed_contract_receipt")
                if (
                    resolved_test is None
                    or not isinstance(receipt, Mapping)
                    or not _executed_contract_receipt_valid(
                        receipt=receipt,
                        expected_test_path=str(attestation.get("path") or ""),
                        expected_test_name=str(
                            attestation.get("qualified_name") or ""
                        ),
                        expected_test_source_sha256=str(
                            attestation.get("source_sha256") or ""
                        ),
                        expected_production_source_digest=(
                            production_source_digest
                        ),
                        expected_cycle_id=str(cycle_id),
                        expected_process_instance_id=str(process_instance_id),
                        observed_at=observed_at.astimezone(timezone.utc),
                    )
                ):
                    contract_valid = False
                    break
            if not contract_valid:
                reasons.append(
                    "EXACT_PARITY_EXECUTED_CONTRACT_ATTESTATION_INVALID:"
                    + str(row.get("method") or "UNKNOWN")
                )

    reasons = list(dict.fromkeys(reasons))
    parity_complete = not reasons
    source_digest: str | None = None
    if legacy_hash and matrix_hash and native_hashes:
        source_digest = canonical_sha256(
            {
                "legacy_hybrid_sha256": legacy_hash,
                "durable_matrix_sha256": matrix_hash,
                "native_source_sha256": native_hashes,
            }
        )
    return {
        "schema_version": CURRENT_PARITY_EVIDENCE_SCHEMA,
        "generated_utc": observed_utc,
        "cycle_id": str(cycle_id),
        "process_instance_id": str(process_instance_id),
        "parity_complete": parity_complete,
        "required_missing_parity_methods": 0 if parity_complete else len(reasons),
        "method_count": len(legacy_methods),
        "status": (
            "FULL_FUNCTION_PARITY_VERIFIED"
            if parity_complete
            else "FULL_FUNCTION_PARITY_BLOCKED"
        ),
        "revalidated_this_cycle": True,
        "parity_evidence_class": (
            "EXACT_SOURCE_AND_EXECUTED_CONTRACT_TEST_ATTESTATION"
            if parity_complete
            else "DECLARATIVE_OR_INCOMPLETE_PARITY_NONCANONICAL"
        ),
        "counts_as_canonical_learning_readiness": parity_complete,
        "revalidation_rejection_reasons": reasons,
        "legacy_hybrid_sha256": legacy_hash,
        "durable_parity_matrix_sha256": matrix_hash,
        "native_source_set_sha256": (
            canonical_sha256(native_hashes) if native_hashes else None
        ),
        "source_attestation_digest": source_digest,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_current_cycle_prediction_publication_evidence(
    *,
    rows: Iterable[Mapping[str, Any]],
    expected_prediction_count: int,
    lineages_published: int,
    cycle_id: str,
    process_instance_id: str,
    checkpoint_id: str,
    candidate_policy_fingerprint: str,
    generated_utc: str,
    publication_attempted: bool,
) -> dict[str, Any]:
    """Build complete-grid evidence; mixed/legacy row identity fails closed."""

    materialized = [dict(row) for row in rows]
    expected = int(expected_prediction_count)
    lineages = int(lineages_published)
    compact_rows = [
        {
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "status": row.get("status"),
            "cycle_id": row.get("cycle_id"),
            "process_instance_id": row.get("process_instance_id"),
            "checkpoint_id": row.get("checkpoint_id"),
            "candidate_policy_fingerprint": row.get(
                "candidate_policy_fingerprint"
            ),
        }
        for row in materialized
    ]
    current_rows = [row for row in compact_rows if row.get("status") == "PRESENT_CURRENT"]
    stale_rows = [
        row
        for row in compact_rows
        if str(row.get("status") or "").startswith("STALE")
    ]
    scope_rows = [
        (str(row.get("symbol") or ""), str(row.get("timeframe") or ""))
        for row in compact_rows
    ]
    identity_bound = bool(
        compact_rows
        and all(
            row.get("cycle_id") == cycle_id
            and row.get("process_instance_id") == process_instance_id
            and row.get("checkpoint_id") == checkpoint_id
            and row.get("candidate_policy_fingerprint")
            == candidate_policy_fingerprint
            for row in compact_rows
        )
    )
    unique_complete_scope = bool(
        scope_rows
        and all(symbol and timeframe for symbol, timeframe in scope_rows)
        and len(scope_rows) == len(set(scope_rows))
    )
    missing_count = max(0, expected - len(current_rows))
    reasons: list[str] = []
    if not publication_attempted:
        reasons.append("PREDICTION_PUBLICATION_NOT_ATTEMPTED")
    if expected <= 0:
        reasons.append("EXPECTED_PREDICTION_GRID_EMPTY")
    if len(materialized) != expected:
        reasons.append("PREDICTION_ROW_COUNT_MISMATCH")
    if len(current_rows) != expected:
        reasons.append("PREDICTION_GRID_NOT_ALL_CURRENT")
    if lineages != expected:
        reasons.append("PREDICTION_LINEAGE_COUNT_MISMATCH")
    if not identity_bound:
        reasons.append("PREDICTION_GRID_IDENTITY_MIXED_OR_LEGACY")
    if not unique_complete_scope:
        reasons.append("PREDICTION_GRID_SCOPE_DUPLICATE_OR_MISSING")
    reasons = list(dict.fromkeys(reasons))
    return {
        "schema_version": CURRENT_PREDICTION_PUBLICATION_SCHEMA,
        "generated_utc": generated_utc,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "checkpoint_id": checkpoint_id,
        "candidate_policy_fingerprint": candidate_policy_fingerprint,
        "publication_complete": not reasons,
        "expected_prediction_count": expected,
        "prediction_rows_count": len(materialized),
        "current_prediction_count": len(current_rows),
        "missing_prediction_rows_count": missing_count,
        "stale_prediction_rows_count": len(stale_rows),
        "lineages_published": lineages,
        "prediction_rows": compact_rows,
        "identity_bound_row_count": len(compact_rows) if identity_bound else 0,
        "publication_rejection_reasons": reasons,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


__all__ = [
    "ALLOWED_TRAINER_SERVICE_UNITS",
    "CURRENT_PARITY_EVIDENCE_SCHEMA",
    "CURRENT_PREDICTION_PUBLICATION_SCHEMA",
    "CURRENT_RESOURCE_EVIDENCE_SCHEMA",
    "build_current_cycle_parity_attestation",
    "build_current_cycle_prediction_publication_evidence",
    "canonical_sha256",
    "capture_cycle_identity",
    "current_process_service_evidence",
    "process_instance_id",
    "utc_now_microseconds",
]
