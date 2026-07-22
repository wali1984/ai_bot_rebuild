"""Resident CLI for the fail-closed profiled observation coordinator.

This process turns one verified publisher status into a crash-resumable local
manifest/head/page evidence chain.  Without a complete independent-witness
bundle it deliberately parks at ``HEAD_STAGED`` while remaining observable as
an active service.  It has no optimizer, checkpoint, prediction, trading,
order, leverage, margin, or exchange-credential path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import stat
import sys
import time
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn

from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_runtime_credentials_v1 as credential_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_state_v1 as state_module,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveError,
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_base_publisher_cycle_status_v1 import (
    ProfiledBasePublisherCycleStatusV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessClientV1Error,
    ProfiledTrainingExternalWitnessHttpsTransportV1,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_journal_v1 import (
    ProfiledTrainingExternalWitnessJournalV1,
    ProfiledTrainingExternalWitnessJournalV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeV1,
    ProfiledTrainingExternalWitnessRuntimeV1Error,
    restore_pinned_profiled_training_external_witness_client_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_coordinator_v1 import (
    PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS,
    ProfiledTrainingObservationCoordinatorResultV1,
    ProfiledTrainingObservationCoordinatorV1,
    ProfiledTrainingObservationCoordinatorV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
    ProfiledTrainingObservationManifestV1Error,
)

CLI_STATUS_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_cli_status_v1"
)
CLI_SUMMARY_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_cli_summary_v1"
)
CLI_ERROR_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_cli_error_v1"
)
DEFAULT_RUNTIME_ROOT: Final = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "profiled_training_observation_coordinator_v1"
)
DEFAULT_PUBLISHER_STATUS_PATH: Final = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled_base_publisher_status_v1.json"
)
DEFAULT_FEATURE_LEDGER_PATH: Final = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "durable_feature_snapshot_ledger.sqlite3"
)
DEFAULT_LABEL_ARCHIVE_PATH: Final = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/"
    "canonical_finalized_5m_label_archive.sqlite3"
)
DEFAULT_TRUSTED_COST_STORE_ROOT: Final = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
DEFAULT_NAMESPACE: Final = "ai-bot-v2-profiled-observation-v1"
DEFAULT_CONSUMER_LANE: Final = "persistent-native-cuda-trainer-v1"
DEFAULT_STATE_AUTH_KEY_ID: Final = "profiled-observation-state-v1"
DEFAULT_MANIFEST_AUTH_KEY_ID: Final = "profiled-observation-manifest-v1"
DEFAULT_HEAD_AUTH_KEY_ID: Final = "profiled-observation-head-v1"
DEFAULT_EPOCH_AUTH_KEY_ID: Final = "profiled-observation-epoch-v1"
DEFAULT_PAGE_SIZE: Final = 256
DEFAULT_CYCLE_SECONDS: Final = 30.0
CONFIG_EXIT_STATUS: Final = 78
MAX_STATUS_BYTES: Final = 256 * 1024

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_STOP = False

ProfiledObservationCoordinatorCredentialError = (
    credential_module.ProfiledObservationCoordinatorCredentialError
)
ProfiledObservationCoordinatorRuntimeCredentialsV1 = (
    credential_module.ProfiledObservationCoordinatorRuntimeCredentialsV1
)
load_profiled_observation_coordinator_runtime_credentials_v1 = (
    credential_module.load_profiled_observation_coordinator_runtime_credentials_v1
)
ProfiledTrainingObservationCoordinatorStateStoreV1 = (
    state_module.ProfiledTrainingObservationCoordinatorStateStoreV1
)
ProfiledTrainingObservationCoordinatorStateV1Error = (
    state_module.ProfiledTrainingObservationCoordinatorStateV1Error
)


class ProfiledObservationCoordinatorCliError(RuntimeError):
    """Stable CLI configuration/runtime packaging error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(slots=True)
class _CoordinatorRuntime:
    coordinator: ProfiledTrainingObservationCoordinatorV1
    witness_client: PinnedProfiledTrainingExternalWitnessClientV1 | None

    def close(self) -> None:
        if self.witness_client is not None:
            self.witness_client.close()


def _fail(reason: str) -> NoReturn:
    raise ProfiledObservationCoordinatorCliError(reason) from None


def _request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _page_size(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive page size") from exc
    if not 0 < parsed <= MAX_PROFILED_OBSERVATION_PAGE_ROWS:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_PROFILED_OBSERVATION_PAGE_ROWS}"
        )
    return parsed


def _environment_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and crash-resume the authenticated profiled observation inventory. "
            "The process parks fail-closed when an independent witness is absent and "
            "never grants optimizer, model, prediction, paper, live, order, or execution "
            "authority."
        )
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=_environment_path(
            "PROFILED_OBSERVATION_COORDINATOR_RUNTIME_ROOT", DEFAULT_RUNTIME_ROOT
        ),
    )
    parser.add_argument(
        "--publisher-status-path",
        type=Path,
        default=_environment_path(
            "PROFILED_BASE_PUBLISHER_STATUS_PATH", DEFAULT_PUBLISHER_STATUS_PATH
        ),
    )
    parser.add_argument(
        "--feature-ledger-path",
        type=Path,
        default=_environment_path(
            "PROFILED_BASE_FEATURE_LEDGER_PATH", DEFAULT_FEATURE_LEDGER_PATH
        ),
    )
    parser.add_argument(
        "--label-archive-path",
        type=Path,
        default=_environment_path(
            "PROFILED_OBSERVATION_COORDINATOR_LABEL_ARCHIVE_PATH",
            DEFAULT_LABEL_ARCHIVE_PATH,
        ),
    )
    parser.add_argument(
        "--trusted-cost-store-root",
        type=Path,
        default=_environment_path(
            "PROFILED_OBSERVATION_COORDINATOR_TRUSTED_COST_STORE_ROOT",
            DEFAULT_TRUSTED_COST_STORE_ROOT,
        ),
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_NAMESPACE", DEFAULT_NAMESPACE
        ),
    )
    parser.add_argument(
        "--consumer-lane",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_CONSUMER_LANE",
            DEFAULT_CONSUMER_LANE,
        ),
    )
    parser.add_argument(
        "--state-auth-key-id",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_STATE_AUTH_KEY_ID",
            DEFAULT_STATE_AUTH_KEY_ID,
        ),
    )
    parser.add_argument(
        "--manifest-auth-key-id",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_MANIFEST_AUTH_KEY_ID",
            DEFAULT_MANIFEST_AUTH_KEY_ID,
        ),
    )
    parser.add_argument(
        "--head-auth-key-id",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_HEAD_AUTH_KEY_ID",
            DEFAULT_HEAD_AUTH_KEY_ID,
        ),
    )
    parser.add_argument(
        "--epoch-auth-key-id",
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_EPOCH_AUTH_KEY_ID",
            DEFAULT_EPOCH_AUTH_KEY_ID,
        ),
    )
    parser.add_argument(
        "--page-size",
        type=_page_size,
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_PAGE_SIZE", str(DEFAULT_PAGE_SIZE)
        ),
        help=(
            "bounded inventory receipt page size; this is a memory/I/O resource bound, "
            "not a market, sample-quality, risk, leverage, or model threshold"
        ),
    )
    parser.add_argument(
        "--cycle-seconds",
        type=_positive_float,
        default=os.environ.get(
            "PROFILED_OBSERVATION_COORDINATOR_CYCLE_SECONDS",
            str(DEFAULT_CYCLE_SECONDS),
        ),
        help="resident observation cadence; operational only and never market-semantic",
    )
    parser.add_argument("--once", action="store_true")
    return parser


def _absolute_lexical(path: Path, *, reason: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or "\x00" in str(path):
        _fail(reason)
    normalized = Path(os.path.normpath(str(path)))
    if normalized != path or ".." in path.parts:
        _fail(reason)
    return path


def _runtime_paths(runtime_root: Path) -> dict[str, Path]:
    root = _absolute_lexical(
        runtime_root,
        reason="PROFILED_COORDINATOR_CLI_RUNTIME_ROOT_INVALID",
    )
    return {
        "root": root,
        "manifest_root": root / "manifests",
        "staging_root": root / "staging-cas",
        "state_cas_root": root / "state-cas",
        "state_pointer_path": root / "state" / "current.json",
        "witness_cas_root": root / "witness-cas",
        "witness_journal_path": root / "witness" / "journal.sqlite3",
        "status_path": root / "coordinator_status_v1.json",
    }


def _ensure_private_runtime_root(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = os.lstat(path)
    except OSError as exc:
        raise ProfiledObservationCoordinatorCliError(
            "PROFILED_COORDINATOR_CLI_RUNTIME_ROOT_UNAVAILABLE"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        _fail("PROFILED_COORDINATOR_CLI_RUNTIME_ROOT_SECURITY_INVALID")


def _build_runtime(
    *,
    args: argparse.Namespace,
    credentials: ProfiledObservationCoordinatorRuntimeCredentialsV1,
) -> tuple[_CoordinatorRuntime, Path]:
    paths = _runtime_paths(args.runtime_root)
    _ensure_private_runtime_root(paths["root"])
    publisher_status_path = _absolute_lexical(
        args.publisher_status_path,
        reason="PROFILED_COORDINATOR_CLI_PUBLISHER_STATUS_PATH_INVALID",
    )
    feature_ledger_path = _absolute_lexical(
        args.feature_ledger_path,
        reason="PROFILED_COORDINATOR_CLI_FEATURE_LEDGER_PATH_INVALID",
    )
    label_archive_path = _absolute_lexical(
        args.label_archive_path,
        reason="PROFILED_COORDINATOR_CLI_LABEL_ARCHIVE_PATH_INVALID",
    )
    trusted_cost_store_root = _absolute_lexical(
        args.trusted_cost_store_root,
        reason="PROFILED_COORDINATOR_CLI_TRUSTED_COST_STORE_ROOT_INVALID",
    )
    local = credentials.local_roles
    state_store = ProfiledTrainingObservationCoordinatorStateStoreV1(
        pointer_path=paths["state_pointer_path"],
        immutable_store=ImmutableSourcePayloadStore(paths["state_cas_root"]),
        namespace=args.namespace,
        consumer_lane=args.consumer_lane,
        state_auth_key_id=args.state_auth_key_id,
        state_hmac_key=local.state_hmac_key,
        manifest_auth_key_id=args.manifest_auth_key_id,
        manifest_hmac_key=local.manifest_hmac_key,
        head_auth_key_id=args.head_auth_key_id,
        head_hmac_key=local.head_hmac_key,
        epoch_auth_key_id=args.epoch_auth_key_id,
        epoch_hmac_key=local.epoch_hmac_key,
    )
    witness_client: PinnedProfiledTrainingExternalWitnessClientV1 | None = None
    witness_runtime: ProfiledTrainingExternalWitnessRuntimeV1 | None = None
    unowned_transport: ProfiledTrainingExternalWitnessHttpsTransportV1 | None = None
    try:
        external = credentials.external_witness
        if external is not None:
            unowned_transport = ProfiledTrainingExternalWitnessHttpsTransportV1(
                base_url=external.base_url,
                bearer_token=external.bearer_token,
                timeout_seconds=external.timeout_seconds,
            )
            journal = ProfiledTrainingExternalWitnessJournalV1(
                paths["witness_journal_path"],
                immutable_store=ImmutableSourcePayloadStore(
                    paths["witness_cas_root"]
                ),
            )
            witness_client = (
                restore_pinned_profiled_training_external_witness_client_v1(
                    journal=journal,
                    transport=unowned_transport,
                    witness_id=external.witness_id,
                    witness_public_key_bytes=external.public_key_bytes,
                    expected_witness_public_key_sha256=(
                        external.expected_public_key_sha256
                    ),
                    close_transport_on_close=True,
                )
            )
            # Ownership transferred to the pinned client only after restore.
            unowned_transport = None
            witness_runtime = ProfiledTrainingExternalWitnessRuntimeV1(
                journal=journal,
                client=witness_client,
            )
        coordinator = ProfiledTrainingObservationCoordinatorV1(
            state_store=state_store,
            status_path=publisher_status_path,
            feature_ledger=DurableFeatureSnapshotLedger(feature_ledger_path),
            label_archive=DurableCanonical5mLabelArchive(label_archive_path),
            trusted_immutable_cost_store_root=trusted_cost_store_root,
            manifest_root=paths["manifest_root"],
            staging_store=ImmutableSourcePayloadStore(paths["staging_root"]),
            namespace=args.namespace,
            consumer_lane=args.consumer_lane,
            manifest_auth_key_id=args.manifest_auth_key_id,
            manifest_hmac_key=local.manifest_hmac_key,
            head_auth_key_id=args.head_auth_key_id,
            head_hmac_key=local.head_hmac_key,
            epoch_auth_key_id=args.epoch_auth_key_id,
            epoch_hmac_key=local.epoch_hmac_key,
            page_size=args.page_size,
            witness_runtime=witness_runtime,
        )
    except Exception:
        if witness_client is not None:
            witness_client.close()
        elif unowned_transport is not None:
            unowned_transport.close()
        raise
    return _CoordinatorRuntime(coordinator, witness_client), paths["status_path"]


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledObservationCoordinatorCliError(
            "PROFILED_COORDINATOR_CLI_STATUS_JSON_INVALID"
        ) from exc
    if not encoded or len(encoded) > MAX_STATUS_BYTES:
        _fail("PROFILED_COORDINATOR_CLI_STATUS_JSON_INVALID")
    return encoded


def _canonical_clock() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _code_sha() -> str:
    value = os.environ.get("AI_BOT_CODE_SHA", "")
    return value if _SHA1_RE.fullmatch(value) is not None else "UNPINNED"


def _result_material(
    result: ProfiledTrainingObservationCoordinatorResultV1,
) -> dict[str, Any]:
    if type(result) is not ProfiledTrainingObservationCoordinatorResultV1:
        _fail("PROFILED_COORDINATOR_CLI_RESULT_EXACT_TYPE_REQUIRED")
    result.__post_init__()
    return {
        descriptor.name: getattr(result, descriptor.name)
        for descriptor in fields(result)
        if not descriptor.name.startswith("_")
    }


def _status_payload(
    result: ProfiledTrainingObservationCoordinatorResultV1,
    *,
    status_path: Path,
) -> dict[str, Any]:
    result_material = _result_material(result)
    result_schema_version = result_material.pop("schema_version")
    unsigned = {
        "schema_version": CLI_STATUS_SCHEMA_VERSION,
        "coordinator_result_schema_version": result_schema_version,
        "status_generated_at": _canonical_clock(),
        "code_sha": _code_sha(),
        "status_path": str(status_path),
        "local_status_integrity_only": True,
        **result_material,
    }
    return {
        **unsigned,
        "status_sha256": hashlib.sha256(_canonical_bytes(unsigned)).hexdigest(),
    }


def _error_payload(*, reason: str, status_path: Path) -> dict[str, Any]:
    unsigned = {
        "schema_version": CLI_ERROR_SCHEMA_VERSION,
        "classification": "FAIL_CLOSED",
        "reason": reason,
        "status_generated_at": _canonical_clock(),
        "code_sha": _code_sha(),
        "status_path": str(status_path),
        "local_status_integrity_only": True,
        "external_monotonic_manifest_head_verified": False,
        "full_consumption_external_ack_verified": False,
        "optimizer_admission_authorized": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }
    return {
        **unsigned,
        "status_sha256": hashlib.sha256(_canonical_bytes(unsigned)).hexdigest(),
    }


def _atomic_write_status(path: Path, payload: dict[str, Any]) -> None:
    framed = _canonical_bytes(payload) + b"\n"
    temporary: Path | None = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = os.lstat(path.parent)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_ISLNK(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            _fail("PROFILED_COORDINATOR_CLI_STATUS_PARENT_SECURITY_INVALID")
        if path.is_symlink():
            _fail("PROFILED_COORDINATOR_CLI_STATUS_SYMLINK_FORBIDDEN")
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            offset = 0
            while offset < len(framed):
                offset += os.write(descriptor, framed[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        temporary = None
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        observed = os.lstat(path)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != 0o600
            or path.read_bytes() != framed
        ):
            _fail("PROFILED_COORDINATOR_CLI_STATUS_POSTCOMMIT_INVALID")
    except ProfiledObservationCoordinatorCliError:
        raise
    except OSError as exc:
        raise ProfiledObservationCoordinatorCliError(
            "PROFILED_COORDINATOR_CLI_STATUS_WRITE_FAILED"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "classification",
        "cycle_id",
        "publisher_status_sha256",
        "observation_time",
        "phase",
        "transition_sequence",
        "state_transitions_committed",
        "witness_runtime_configured",
        "witness_operations_recovered",
        "witness_network_append_attempts",
        "page_receipts_staged_this_invocation",
        "manifest_id",
        "total_profiled_samples",
        "admitted_example_count",
        "label_unavailable_count",
        "head_revision",
        "signed_head_durably_anchored",
        "full_consumption_locally_verified",
        "complete_state_chain_verified",
        "external_monotonic_manifest_head_verified",
        "full_consumption_external_ack_verified",
        "optimizer_admission_authorized",
        "checkpoint_write_authorized",
        "model_write_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
        "status_sha256",
        "status_path",
    )
    return {
        "schema_version": CLI_SUMMARY_SCHEMA_VERSION,
        **{key: payload[key] for key in keys if key in payload},
    }


def _print_payload(payload: dict[str, Any], *, error: bool = False) -> None:
    print(
        _canonical_bytes(payload).decode("ascii"),
        file=sys.stderr if error else sys.stdout,
        flush=True,
    )


def _wait(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not _STOP:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))


def _park_without_witness() -> None:
    while not _STOP:
        time.sleep(1.0)


def _run_loop(
    *,
    args: argparse.Namespace,
    runtime: _CoordinatorRuntime,
    status_path: Path,
) -> int:
    consecutive_runtime_failures = 0
    while not _STOP:
        started = time.monotonic()
        try:
            result = runtime.coordinator.run_once()
        except _RUNTIME_ERRORS as exc:
            consecutive_runtime_failures += 1
            payload = _error_payload(
                reason=_reason(exc),
                status_path=status_path,
            )
            _atomic_write_status(status_path, payload)
            _print_payload(payload, error=True)
            if args.once:
                return 1
            _wait(
                _adaptive_retry_seconds(
                    cycle_seconds=float(args.cycle_seconds),
                    consecutive_failures=consecutive_runtime_failures,
                )
            )
            continue
        consecutive_runtime_failures = 0
        payload = _status_payload(result, status_path=status_path)
        _atomic_write_status(status_path, payload)
        _print_payload(_summary(payload))
        if args.once:
            return 0
        if (
            result.classification == PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS
            and not result.witness_runtime_configured
        ):
            _park_without_witness()
            return 0
        _wait(max(0.0, float(args.cycle_seconds) - (time.monotonic() - started)))
    return 0


def _adaptive_retry_seconds(
    *,
    cycle_seconds: float,
    consecutive_failures: int,
) -> float:
    """Return bounded operational backoff with no market semantics."""

    if (
        type(cycle_seconds) not in {int, float}
        or not math.isfinite(float(cycle_seconds))
        or float(cycle_seconds) <= 0
        or type(consecutive_failures) is not int
        or consecutive_failures <= 0
    ):
        _fail("PROFILED_COORDINATOR_CLI_RETRY_ARGUMENT_INVALID")
    # Exponent work is bounded before evaluation.  The ceiling limits error
    # pressure only; it never admits or rejects a market/sample/model action.
    exponent = min(consecutive_failures - 1, 5)
    return min(float(cycle_seconds) * float(2**exponent), 15 * 60.0)


_CONFIG_ERRORS = (
    ProfiledObservationCoordinatorCliError,
    ProfiledObservationCoordinatorCredentialError,
)
_RUNTIME_ERRORS = (
    Canonical5mArchiveError,
    FeatureSnapshotLedgerError,
    ProfiledBasePublisherCycleStatusV1Error,
    ProfiledTrainingExternalWitnessClientV1Error,
    ProfiledTrainingExternalWitnessJournalV1Error,
    ProfiledTrainingExternalWitnessRuntimeV1Error,
    ProfiledTrainingObservationCoordinatorStateV1Error,
    ProfiledTrainingObservationCoordinatorV1Error,
    ProfiledTrainingObservationManifestV1Error,
    SourcePayloadStoreError,
)
_HANDLED_ERRORS = _CONFIG_ERRORS + _RUNTIME_ERRORS


def _reason(exc: BaseException) -> str:
    if isinstance(exc, ProfiledObservationCoordinatorCliError):
        return exc.reason
    if isinstance(exc, ProfiledObservationCoordinatorCredentialError):
        return exc.reason
    reasons = getattr(exc, "reasons", None)
    if isinstance(reasons, tuple) and reasons and all(type(value) is str for value in reasons):
        return ";".join(reasons)
    return type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    global _STOP
    _STOP = False
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code in {None, 0}:
            return 0
        runtime_root = _environment_path(
            "PROFILED_OBSERVATION_COORDINATOR_RUNTIME_ROOT",
            DEFAULT_RUNTIME_ROOT,
        )
        status_path = runtime_root / "coordinator_status_v1.json"
        payload = _error_payload(
            reason="PROFILED_COORDINATOR_CLI_ARGUMENTS_INVALID",
            status_path=status_path,
        )
        if runtime_root.is_absolute():
            try:
                exact_root = _absolute_lexical(
                    runtime_root,
                    reason="PROFILED_COORDINATOR_CLI_RUNTIME_ROOT_INVALID",
                )
                _ensure_private_runtime_root(exact_root)
                _atomic_write_status(
                    exact_root / "coordinator_status_v1.json",
                    payload,
                )
            except ProfiledObservationCoordinatorCliError:
                pass
        _print_payload(payload, error=True)
        return CONFIG_EXIT_STATUS
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    status_path = args.runtime_root / "coordinator_status_v1.json"
    runtime: _CoordinatorRuntime | None = None
    try:
        status_path = _runtime_paths(args.runtime_root)["status_path"]
        runtime_credentials = (
            load_profiled_observation_coordinator_runtime_credentials_v1()
        )
        runtime, status_path = _build_runtime(
            args=args,
            credentials=runtime_credentials,
        )
        return _run_loop(args=args, runtime=runtime, status_path=status_path)
    except _HANDLED_ERRORS as exc:
        reason = _reason(exc)
        payload = _error_payload(reason=reason, status_path=status_path)
        if status_path.is_absolute():
            try:
                _ensure_private_runtime_root(status_path.parent)
                _atomic_write_status(status_path, payload)
            except ProfiledObservationCoordinatorCliError:
                pass
        _print_payload(payload, error=True)
        return CONFIG_EXIT_STATUS if isinstance(exc, _CONFIG_ERRORS) else 1
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
