"""Observable resident service wrapper for authenticated profiled publication.

Without an independent witness verification bundle this module remains alive,
writes a truthful waiting status, and never imports the optimizer runtime.  A
complete verifier bundle permits one bounded resident cycle at a time.  Every
returned capability flag remains non-reusable and all serving/trading/order
authority remains false in the underlying resident result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn

from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
    AuthenticatedProfiledResidentRuntimeCredentialsV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (  # noqa: E501
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
)

AUTHENTICATED_PROFILED_RESIDENT_SERVICE_STATUS_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_resident_service_status_v1"
)
PROFILED_RESIDENT_SERVICE_WAITING_WITNESS: Final = (
    "WAITING_EXTERNAL_WITNESS_CONFIGURATION"
)
PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING: Final = "AUTHENTICATED_PROFILED_CYCLE_RUNNING"
PROFILED_RESIDENT_SERVICE_FAIL_CLOSED: Final = "FAIL_CLOSED"
MAX_PROFILED_RESIDENT_SERVICE_STATUS_BYTES: Final = 256 * 1024

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_PUBLIC_ERROR_TYPES: Final = frozenset(
    {
        "AuthenticatedProfiledResidentRuntimeV1Error",
        "AuthenticatedProfiledResidentServiceV1Error",
        "FileNotFoundError",
        "OSError",
        "PermissionError",
        "RuntimeError",
        "TypeError",
        "ValueError",
    }
)
_PUBLIC_REASON_CODES: Final = frozenset(
    {
        "PROFILED_RESIDENT_ACTIVE_SERVING_BASE_BINDING_INVALID",
        "PROFILED_RESIDENT_ACTIVE_SERVING_BASE_NOT_EXACTLY_RESOLVED",
        "PROFILED_RESIDENT_AUTHORIZATION_IDENTITY_INVALID",
        "PROFILED_RESIDENT_AUTHORIZATION_JOURNAL_INVALID",
        "PROFILED_RESIDENT_AUTHORIZATION_MOVED_DURING_MATERIALIZATION",
        "PROFILED_RESIDENT_COMPLETION_IDENTITY_INVALID",
        "PROFILED_RESIDENT_COMPLETION_REOPEN_FAILED",
        "PROFILED_RESIDENT_COMPLETION_STATE_BINDING_INVALID",
        "PROFILED_RESIDENT_CONFIG_EXACT_TYPE_REQUIRED",
        "PROFILED_RESIDENT_CONFIG_INVALID",
        "PROFILED_RESIDENT_COORDINATOR_STATE_MOVED_DURING_MATERIALIZATION",
        "PROFILED_RESIDENT_EMPTY_STATE_INTEGRITY_CONFLICT",
        "PROFILED_RESIDENT_INDEPENDENT_ADMISSION_MATERIALIZATION_INVALID",
        "PROFILED_RESIDENT_MODEL_DIR_INVALID",
        "PROFILED_RESIDENT_RESULT_IDENTITY_INVALID",
        "PROFILED_RESIDENT_RESULT_INVALID",
        "PROFILED_RESIDENT_SERVICE_AUTHORIZATION_CAS_INVALID",
        "PROFILED_RESIDENT_SERVICE_CLASSIFICATION_INVALID",
        "PROFILED_RESIDENT_SERVICE_CONFIG_EXACT_TYPE_REQUIRED",
        "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID",
        "PROFILED_RESIDENT_SERVICE_COORDINATOR_ROOT_INVALID",
        "PROFILED_RESIDENT_SERVICE_COORDINATOR_ROOT_SECURITY_INVALID",
        "PROFILED_RESIDENT_SERVICE_COST_STORE_ROOT_INVALID",
        "PROFILED_RESIDENT_SERVICE_CREDENTIALS_EXACT_TYPE_REQUIRED",
        "PROFILED_RESIDENT_SERVICE_LEDGER_PATH_INVALID",
        "PROFILED_RESIDENT_SERVICE_MODEL_DIR_INVALID",
        "PROFILED_RESIDENT_SERVICE_ONCE_INVALID",
        "PROFILED_RESIDENT_SERVICE_REPO_ROOT_INVALID",
        "PROFILED_RESIDENT_SERVICE_REPO_ROOT_SECURITY_INVALID",
        "PROFILED_RESIDENT_SERVICE_RESULT_CLASSIFICATION_MISMATCH",
        "PROFILED_RESIDENT_SERVICE_RESULT_EXACT_TYPE_REQUIRED",
        "PROFILED_RESIDENT_SERVICE_RESULT_FIELDS_INVALID",
        "PROFILED_RESIDENT_SERVICE_STAGING_CAS_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATE_CAS_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATUS_JSON_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATUS_PARENT_SECURITY_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATUS_PATH_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATUS_TARGET_INVALID",
        "PROFILED_RESIDENT_SERVICE_STATUS_WRITE_FAILED",
        "PROFILED_RESIDENT_SERVICE_WITNESS_VERIFIER_REQUIRED",
        "PROFILED_RESIDENT_SERVING_ACTIVATION_MANIFEST_INVALID",
        "PROFILED_RESIDENT_SERVING_ACTIVATION_PATH_INVALID",
        "PROFILED_RESIDENT_SERVING_BASE_SCAN_FAILED",
        "PROFILED_RESIDENT_SERVING_BASE_WITHOUT_ACTIVATION",
        "PROFILED_RESIDENT_STATE_INTEGRITY_INVALID",
        "PROFILED_RESIDENT_TRAINING_NOT_AFTER_WITNESS_ACCEPTANCE",
        "PROFILED_RESIDENT_TRAINING_OBSERVATION_CLOCK_INVALID",
        "PROFILED_RESIDENT_WITNESS_ACCEPTED_CLOCK_INVALID",
    }
)
_RESULT_BOOLEAN_FIELDS: Final = frozenset(
    {
        "optimizer_execution_completed",
        "checkpoint_publication_completed",
        "already_published",
        "checkpoint_artifact_verified",
        "resident_runtime_active",
        "checkpoint_write_authorized",
        "prediction_authorized",
        "serving_authorized",
        "serving_activation_authorized",
        "serving_promotion_authorized",
        "trading_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "exchange_access_authorized",
        "deployment_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    }
)
_RESULT_INTEGER_FIELDS: Final = frozenset(
    {
        "admitted_example_count",
        "candidate_checkpoint_generation",
    }
)
_RESULT_FIELDS: Final = (
    "schema_version",
    "classification",
    "cycle_id",
    "state_event_sha256",
    "manifest_id",
    "completion_event_sha256",
    "external_authorization_envelope_sha256",
    "witness_namespace",
    "admitted_example_count",
    "base_checkpoint_id",
    "candidate_checkpoint_id",
    "candidate_checkpoint_generation",
    *_RESULT_BOOLEAN_FIELDS,
)


class AuthenticatedProfiledResidentServiceV1Error(RuntimeError):
    """The resident service wrapper failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledResidentServiceV1Error(*reasons) from None


def _absolute_lexical(path: Path, *, reason: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or "\x00" in str(path):
        _fail(reason)
    normalized = Path(os.path.normpath(str(path)))
    if normalized != path or ".." in path.parts:
        _fail(reason)
    return path


def _private_directory(path: Path, *, reason: str) -> None:
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise AuthenticatedProfiledResidentServiceV1Error(reason) from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or stat.S_IMODE(observed.st_mode) != 0o700
    ):
        _fail(reason)


def _owned_directory(path: Path, *, reason: str) -> None:
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise AuthenticatedProfiledResidentServiceV1Error(reason) from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_uid != os.geteuid()
    ):
        _fail(reason)


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentServiceConfigV1:
    repo_root: Path
    coordinator_runtime_root: Path
    feature_ledger_path: Path
    trusted_immutable_cost_store_root: Path
    model_dir: Path
    status_path: Path
    namespace: str
    consumer_lane: str
    state_auth_key_id: str
    manifest_auth_key_id: str
    head_auth_key_id: str
    epoch_auth_key_id: str
    page_limit: int
    validation_fraction: float
    optimizer_input_byte_budget: int
    state_resource_budget_bytes: int
    checkpoint_serialization_byte_budget: int
    interval_seconds: float

    def __post_init__(self) -> None:
        for path, reason in (
            (self.repo_root, "PROFILED_RESIDENT_SERVICE_REPO_ROOT_INVALID"),
            (
                self.coordinator_runtime_root,
                "PROFILED_RESIDENT_SERVICE_COORDINATOR_ROOT_INVALID",
            ),
            (
                self.feature_ledger_path,
                "PROFILED_RESIDENT_SERVICE_LEDGER_PATH_INVALID",
            ),
            (
                self.trusted_immutable_cost_store_root,
                "PROFILED_RESIDENT_SERVICE_COST_STORE_ROOT_INVALID",
            ),
            (self.model_dir, "PROFILED_RESIDENT_SERVICE_MODEL_DIR_INVALID"),
            (self.status_path, "PROFILED_RESIDENT_SERVICE_STATUS_PATH_INVALID"),
        ):
            _absolute_lexical(path, reason=reason)
        identifiers = (
            self.namespace,
            self.consumer_lane,
            self.state_auth_key_id,
            self.manifest_auth_key_id,
            self.head_auth_key_id,
            self.epoch_auth_key_id,
        )
        if (
            any(
                type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None
                for value in identifiers
            )
            or len(set(identifiers[2:])) != 4
            or type(self.page_limit) is not int
            or not 0 < self.page_limit <= MAX_PROFILED_OBSERVATION_PAGE_ROWS
            or type(self.validation_fraction) is not float
            or not math.isfinite(self.validation_fraction)
            or not 0.0 <= self.validation_fraction < 1.0
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.optimizer_input_byte_budget,
                    self.state_resource_budget_bytes,
                    self.checkpoint_serialization_byte_budget,
                )
            )
            or type(self.interval_seconds) not in {int, float}
            or isinstance(self.interval_seconds, bool)
            or not math.isfinite(float(self.interval_seconds))
            or self.interval_seconds <= 0
        ):
            _fail("PROFILED_RESIDENT_SERVICE_CONFIG_INVALID")
        _owned_directory(
            self.repo_root,
            reason="PROFILED_RESIDENT_SERVICE_REPO_ROOT_SECURITY_INVALID",
        )
        _private_directory(
            self.status_path.parent,
            reason="PROFILED_RESIDENT_SERVICE_STATUS_PARENT_SECURITY_INVALID",
        )


def _runtime_paths(root: Path) -> dict[str, Path]:
    return {
        "state_pointer": root / "state" / "current.json",
        "state_cas": root / "state-cas",
        "staging_cas": root / "staging-cas",
        "authorization_journal": root / "completion-authorization" / "journal.sqlite3",
        "authorization_cas": root / "completion-authorization-cas",
    }


def _require_immutable_store(path: Path, *, reason: str) -> None:
    _private_directory(path, reason=reason)
    _private_directory(path / "sha256", reason=reason)


def build_authenticated_profiled_resident_runtime_config_v1(
    *,
    config: AuthenticatedProfiledResidentServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
) -> object:
    """Construct the optimizer runtime only with a complete verifier bundle."""

    if type(config) is not AuthenticatedProfiledResidentServiceConfigV1:
        _fail("PROFILED_RESIDENT_SERVICE_CONFIG_EXACT_TYPE_REQUIRED")
    if type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1:
        _fail("PROFILED_RESIDENT_SERVICE_CREDENTIALS_EXACT_TYPE_REQUIRED")
    config.__post_init__()
    verifier = credentials.witness_verifier
    if verifier is None:
        _fail("PROFILED_RESIDENT_SERVICE_WITNESS_VERIFIER_REQUIRED")

    # Imports remain behind the verifier gate so witness-absent mode cannot
    # import CUDA/model/optimizer components or touch coordinator artifacts.
    from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (  # noqa: E501
        AuthenticatedProfiledResidentRuntimeConfigV1,
    )
    from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (  # noqa: E501
        DurableFeatureSnapshotLedger,
    )
    from v2.backend.app.services.native_trainer.immutable_source_payload_store import (  # noqa: E501
        ImmutableSourcePayloadStore,
    )
    from v2.backend.app.services.native_trainer.profiled_optimizer_external_completion_authorization_journal_v1 import (  # noqa: E501
        ProfiledOptimizerCompletionAuthorizationJournalV1,
    )
    from v2.backend.app.services.native_trainer.profiled_training_observation_coordinator_state_v1 import (  # noqa: E501
        ProfiledTrainingObservationCoordinatorStateStoreV1,
    )

    paths = _runtime_paths(config.coordinator_runtime_root)
    _private_directory(
        config.coordinator_runtime_root,
        reason="PROFILED_RESIDENT_SERVICE_COORDINATOR_ROOT_SECURITY_INVALID",
    )
    _require_immutable_store(
        paths["state_cas"],
        reason="PROFILED_RESIDENT_SERVICE_STATE_CAS_INVALID",
    )
    _require_immutable_store(
        paths["staging_cas"],
        reason="PROFILED_RESIDENT_SERVICE_STAGING_CAS_INVALID",
    )
    _require_immutable_store(
        paths["authorization_cas"],
        reason="PROFILED_RESIDENT_SERVICE_AUTHORIZATION_CAS_INVALID",
    )
    local = credentials.local_roles
    state_store = ProfiledTrainingObservationCoordinatorStateStoreV1(
        pointer_path=paths["state_pointer"],
        immutable_store=ImmutableSourcePayloadStore(paths["state_cas"]),
        namespace=config.namespace,
        consumer_lane=config.consumer_lane,
        state_auth_key_id=config.state_auth_key_id,
        state_hmac_key=local.state_hmac_key,
        manifest_auth_key_id=config.manifest_auth_key_id,
        manifest_hmac_key=local.manifest_hmac_key,
        head_auth_key_id=config.head_auth_key_id,
        head_hmac_key=local.head_hmac_key,
        epoch_auth_key_id=config.epoch_auth_key_id,
        epoch_hmac_key=local.epoch_hmac_key,
    )
    authorization_journal = ProfiledOptimizerCompletionAuthorizationJournalV1(
        paths["authorization_journal"],
        immutable_store=ImmutableSourcePayloadStore(paths["authorization_cas"]),
    )
    return AuthenticatedProfiledResidentRuntimeConfigV1(
        state_store=state_store,
        completion_authorization_journal=authorization_journal,
        feature_ledger=DurableFeatureSnapshotLedger(config.feature_ledger_path),
        completion_staging_store=ImmutableSourcePayloadStore(paths["staging_cas"]),
        trusted_immutable_cost_store_root=config.trusted_immutable_cost_store_root,
        repo_root=config.repo_root,
        model_dir=config.model_dir,
        namespace=config.namespace,
        consumer_lane=config.consumer_lane,
        manifest_auth_key_id=config.manifest_auth_key_id,
        manifest_hmac_key=local.manifest_hmac_key,
        head_auth_key_id=config.head_auth_key_id,
        head_hmac_key=local.head_hmac_key,
        epoch_auth_key_id=config.epoch_auth_key_id,
        epoch_hmac_key=local.epoch_hmac_key,
        witness_id=verifier.witness_id,
        witness_namespace=config.namespace,
        witness_public_key_bytes=verifier.public_key_bytes,
        expected_witness_public_key_sha256=verifier.expected_public_key_sha256,
        page_limit=config.page_limit,
        validation_fraction=config.validation_fraction,
        optimizer_input_byte_budget=config.optimizer_input_byte_budget,
        state_resource_budget_bytes=config.state_resource_budget_bytes,
        checkpoint_serialization_byte_budget=(
            config.checkpoint_serialization_byte_budget
        ),
    )


def _empty_result() -> dict[str, Any]:
    return {
        name: (
            False
            if name in _RESULT_BOOLEAN_FIELDS
            else 0
            if name == "admitted_example_count"
            else None
        )
        for name in _RESULT_FIELDS
    }


def _result_material(result: object) -> dict[str, Any]:
    from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (  # noqa: E501
        AuthenticatedProfiledResidentRuntimeResultV1,
    )

    if type(result) is not AuthenticatedProfiledResidentRuntimeResultV1:
        _fail("PROFILED_RESIDENT_SERVICE_RESULT_EXACT_TYPE_REQUIRED")
    result.__post_init__()
    material = {
        descriptor.name: getattr(result, descriptor.name)
        for descriptor in fields(result)
        if not descriptor.name.startswith("_")
    }
    if set(material) != set(_RESULT_FIELDS):
        _fail("PROFILED_RESIDENT_SERVICE_RESULT_FIELDS_INVALID")
    return material


def _canonical_bytes(value: object) -> bytes:
    try:
        raw = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise AuthenticatedProfiledResidentServiceV1Error(
            "PROFILED_RESIDENT_SERVICE_STATUS_JSON_INVALID"
        ) from exc
    if not raw or len(raw) > MAX_PROFILED_RESIDENT_SERVICE_STATUS_BYTES:
        _fail("PROFILED_RESIDENT_SERVICE_STATUS_JSON_INVALID")
    return raw


def _clock() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _code_sha() -> str:
    value = os.environ.get("AI_BOT_CODE_SHA", "")
    return value if _SHA1_RE.fullmatch(value) is not None else "UNPINNED"


def _safe_error(exc: BaseException) -> dict[str, Any]:
    raw_reasons = getattr(exc, "reasons", ())
    reasons: list[str] = []
    if isinstance(raw_reasons, tuple | list):
        for value in raw_reasons[:32]:
            if type(value) is str and value in _PUBLIC_REASON_CODES:
                reasons.append(value)
    error_type = type(exc).__name__
    return {
        "error_type": (
            error_type if error_type in _PUBLIC_ERROR_TYPES else "UnexpectedRuntimeError"
        ),
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def build_authenticated_profiled_resident_service_status_v1(
    *,
    config: AuthenticatedProfiledResidentServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    classification: str,
    result: object | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    if type(config) is not AuthenticatedProfiledResidentServiceConfigV1:
        _fail("PROFILED_RESIDENT_SERVICE_CONFIG_EXACT_TYPE_REQUIRED")
    if type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1:
        _fail("PROFILED_RESIDENT_SERVICE_CREDENTIALS_EXACT_TYPE_REQUIRED")
    if type(classification) is not str or not classification:
        _fail("PROFILED_RESIDENT_SERVICE_CLASSIFICATION_INVALID")
    result_material = _empty_result() if result is None else _result_material(result)
    if result is not None and result_material["classification"] != classification:
        _fail("PROFILED_RESIDENT_SERVICE_RESULT_CLASSIFICATION_MISMATCH")
    unsigned = {
        "schema_version": AUTHENTICATED_PROFILED_RESIDENT_SERVICE_STATUS_V1_SCHEMA_VERSION,
        "status_generated_at": _clock(),
        "code_sha": _code_sha(),
        "status_path": str(config.status_path),
        "local_status_integrity_only": True,
        "classification": classification,
        "service_process_active": True,
        "cycle_in_progress": classification == PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING,
        "local_role_credentials_loaded": True,
        "witness_verifier_configured": credentials.witness_verifier is not None,
        "resident_runtime_import_authorized": credentials.witness_verifier is not None,
        "resident_result": result_material,
        "error": None if error is None else _safe_error(error),
        "live_gate": "blocked_human_only",
        "side_effect_contract": {
            "coordinator_root_access": "DESCRIPTOR_SNAPSHOT_READ_ONLY",
            "feature_ledger_access": "POINT_IN_TIME_READ_ONLY",
            "checkpoint_write_scope": str(config.model_dir),
            "status_write_scope": str(config.status_path),
            "network_access_authorized": False,
            "witness_bearer_loaded": False,
            "exchange_credentials_loaded": False,
            "prediction_or_serving_activation_authorized": False,
            "paper_or_live_trading_authorized": False,
            "order_submission_authorized": False,
        },
    }
    return {
        **unsigned,
        "status_sha256": hashlib.sha256(_canonical_bytes(unsigned)).hexdigest(),
    }


def write_authenticated_profiled_resident_service_status_v1(
    config: AuthenticatedProfiledResidentServiceConfigV1,
    payload: Mapping[str, Any],
) -> None:
    path = config.status_path
    parent = path.parent
    _private_directory(
        parent,
        reason="PROFILED_RESIDENT_SERVICE_STATUS_PARENT_SECURITY_INVALID",
    )
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise AuthenticatedProfiledResidentServiceV1Error(
            "PROFILED_RESIDENT_SERVICE_STATUS_TARGET_INVALID"
        ) from exc
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or stat.S_ISLNK(existing.st_mode)
        or existing.st_uid != os.geteuid()
        or existing.st_nlink != 1
        or stat.S_IMODE(existing.st_mode) & 0o022
    ):
        _fail("PROFILED_RESIDENT_SERVICE_STATUS_TARGET_INVALID")
    encoded = _canonical_bytes(dict(payload)) + b"\n"
    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary_path, path)
        temporary_path = None
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise AuthenticatedProfiledResidentServiceV1Error(
            "PROFILED_RESIDENT_SERVICE_STATUS_WRITE_FAILED"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _emit_summary(payload: Mapping[str, Any]) -> None:
    summary = {
        "schema_version": "authenticated_profiled_resident_service_summary_v1",
        "classification": payload.get("classification"),
        "status_generated_at": payload.get("status_generated_at"),
        "status_sha256": payload.get("status_sha256"),
        "code_sha": payload.get("code_sha"),
    }
    print(_canonical_bytes(summary).decode("ascii"), flush=True)


def _run_resident_cycle(runtime_config: object) -> object:
    from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (  # noqa: E501
        run_authenticated_profiled_resident_cycle_v1,
    )

    return run_authenticated_profiled_resident_cycle_v1(runtime_config)  # type: ignore[arg-type]


def run_authenticated_profiled_resident_service_v1(
    config: AuthenticatedProfiledResidentServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    *,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    runtime_builder: Callable[..., object] = (
        build_authenticated_profiled_resident_runtime_config_v1
    ),
    cycle_runner: Callable[[object], object] = _run_resident_cycle,
    writer: Callable[
        [AuthenticatedProfiledResidentServiceConfigV1, Mapping[str, Any]], None
    ] = write_authenticated_profiled_resident_service_status_v1,
    emit: Callable[[Mapping[str, Any]], None] = _emit_summary,
) -> int:
    """Run authenticated cycles or remain observable in verifier-wait mode."""

    if type(config) is not AuthenticatedProfiledResidentServiceConfigV1:
        _fail("PROFILED_RESIDENT_SERVICE_CONFIG_EXACT_TYPE_REQUIRED")
    if type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1:
        _fail("PROFILED_RESIDENT_SERVICE_CREDENTIALS_EXACT_TYPE_REQUIRED")
    if type(once) is not bool:
        _fail("PROFILED_RESIDENT_SERVICE_ONCE_INVALID")
    runtime_config: object | None = None
    while True:
        failed = False
        if credentials.witness_verifier is None:
            payload = build_authenticated_profiled_resident_service_status_v1(
                config=config,
                credentials=credentials,
                classification=PROFILED_RESIDENT_SERVICE_WAITING_WITNESS,
            )
        else:
            try:
                running = build_authenticated_profiled_resident_service_status_v1(
                    config=config,
                    credentials=credentials,
                    classification=PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING,
                )
                writer(config, running)
                emit(running)
                if runtime_config is None:
                    runtime_config = runtime_builder(
                        config=config,
                        credentials=credentials,
                    )
                result = cycle_runner(runtime_config)
                classification = getattr(result, "classification", None)
                payload = build_authenticated_profiled_resident_service_status_v1(
                    config=config,
                    credentials=credentials,
                    classification=classification,
                    result=result,
                )
            except Exception as exc:  # Remain observable and retry fail-closed.
                failed = True
                payload = build_authenticated_profiled_resident_service_status_v1(
                    config=config,
                    credentials=credentials,
                    classification=PROFILED_RESIDENT_SERVICE_FAIL_CLOSED,
                    error=exc,
                )
        writer(config, payload)
        emit(payload)
        if once:
            return 1 if failed else 0
        try:
            sleep(float(config.interval_seconds))
        except KeyboardInterrupt:
            return 0


__all__ = (
    "AUTHENTICATED_PROFILED_RESIDENT_SERVICE_STATUS_V1_SCHEMA_VERSION",
    "MAX_PROFILED_RESIDENT_SERVICE_STATUS_BYTES",
    "PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING",
    "PROFILED_RESIDENT_SERVICE_FAIL_CLOSED",
    "PROFILED_RESIDENT_SERVICE_WAITING_WITNESS",
    "AuthenticatedProfiledResidentServiceConfigV1",
    "AuthenticatedProfiledResidentServiceV1Error",
    "build_authenticated_profiled_resident_runtime_config_v1",
    "build_authenticated_profiled_resident_service_status_v1",
    "run_authenticated_profiled_resident_service_v1",
    "write_authenticated_profiled_resident_service_status_v1",
)
