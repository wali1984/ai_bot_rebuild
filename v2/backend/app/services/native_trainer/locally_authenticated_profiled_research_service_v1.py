"""Resident local-only profiled research optimizer and checkpoint publisher.

This lane exists so a missing independent witness cannot prevent useful local
research.  It does not weaken the external-witness boundary: artifacts are
written only under ``local_profiled_research_candidates`` with a distinct
lineage, and every serving, prediction, paper, live, exchange, deployment, and
order authority remains false.

The lane chooses one completed base-publisher cycle, builds a deterministic
retrospective observation manifest at that cycle's completion time, fully
authenticates and reopens every admitted row, validates direct parent lineage
and all point-in-time clocks, authorizes the complete corpus with a dedicated
HMAC role, performs exactly one isolated outcome-supervised step, reopens the
complete corpus again, then writes and verifies one safe NPZ checkpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    validate_profiled_observation_example_for_local_research_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
    AuthenticatedProfiledResidentRuntimeCredentialsV1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (
    capture_active_or_genesis_profiled_base_lineage_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_supervised_optimizer_execution_v1 import (  # noqa: E501
    LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN,
    execute_locally_authenticated_profiled_research_optimizer_v1,
    revalidate_locally_authenticated_profiled_research_publication_boundary_v1,
    validate_locally_authenticated_profiled_research_execution_owner_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
    checkpoint_lifecycle_lease,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.profiled_base_publisher_cycle_status_v1 import (
    VerifiedProfiledBasePublisherCycleStatusV1,
    read_verified_profiled_base_publisher_cycle_status_v1,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    MAX_PROFILED_TRAINING_SCAN_ROWS,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
    AuthenticatedProfiledTrainingObservationManifestV1,
    ProfiledTrainingObservationExampleV1,
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
    read_profiled_training_observation_page_v1,
)

LOCAL_PROFILED_RESEARCH_SERVICE_STATUS_V1_SCHEMA_VERSION: Final = (
    "locally_authenticated_profiled_research_service_status_v1"
)
LOCAL_PROFILED_RESEARCH_CHECKPOINT_CONTRACT_V1_SCHEMA_VERSION: Final = (
    "locally_authenticated_profiled_research_checkpoint_contract_v1"
)
LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE: Final = (
    "LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_NON_PROMOTABLE_CANDIDATE"
)
LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY: Final = (
    "local_profiled_research_candidates"
)
LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING: Final = "LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING"
LOCAL_PROFILED_RESEARCH_NO_EXAMPLES: Final = "LOCAL_PROFILED_RESEARCH_NO_ADMITTED_EXAMPLES"
LOCAL_PROFILED_RESEARCH_ALREADY_PUBLISHED: Final = (
    "LOCAL_PROFILED_RESEARCH_CORPUS_ALREADY_PUBLISHED"
)
LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED: Final = (
    "LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED"
)
LOCAL_PROFILED_RESEARCH_FAIL_CLOSED: Final = "LOCAL_PROFILED_RESEARCH_FAIL_CLOSED"

MAX_LOCAL_PROFILED_RESEARCH_STATUS_BYTES: Final = 512 * 1024
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_DOWNSTREAM_FALSE: Final = {
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}
_SAFE_STATUS_REASON_PREFIXES: Final = (
    "LOCAL_PROFILED_RESEARCH_",
    "PROFILED_LOCAL_RESEARCH_",
    "PROFILED_OBSERVATION_",
)


class LocallyAuthenticatedProfiledResearchServiceV1Error(RuntimeError):
    """Stable fail-closed error without secret or payload rendering."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise LocallyAuthenticatedProfiledResearchServiceV1Error(*reasons) from None


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
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(reason) from exc
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
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(reason) from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_uid != os.geteuid()
    ):
        _fail(reason)


def _clock(value: datetime | str, *, reason: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value and value == value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (OverflowError, ValueError):
            _fail(reason)
    else:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    return parsed.astimezone(UTC)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, TypeError, UnicodeError, ValueError) as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            "LOCAL_PROFILED_RESEARCH_CANONICAL_JSON_INVALID"
        ) from exc
    if not encoded or len(encoded) > MAX_LOCAL_PROFILED_RESEARCH_STATUS_BYTES:
        _fail("LOCAL_PROFILED_RESEARCH_CANONICAL_JSON_INVALID")
    return encoded


@dataclass(frozen=True, slots=True)
class LocallyAuthenticatedProfiledResearchServiceConfigV1:
    repo_root: Path
    publisher_status_path: Path
    feature_ledger_path: Path
    label_archive_path: Path
    trusted_immutable_cost_store_root: Path
    runtime_root: Path
    model_dir: Path
    status_path: Path
    manifest_auth_key_id: str
    local_research_auth_key_id: str
    page_limit: int
    scan_limit: int
    validation_fraction: float
    optimizer_input_byte_budget: int
    state_resource_budget_bytes: int
    checkpoint_serialization_byte_budget: int
    interval_seconds: float

    def __post_init__(self) -> None:
        for path, reason in (
            (self.repo_root, "LOCAL_PROFILED_RESEARCH_REPO_ROOT_INVALID"),
            (
                self.publisher_status_path,
                "LOCAL_PROFILED_RESEARCH_PUBLISHER_STATUS_PATH_INVALID",
            ),
            (self.feature_ledger_path, "LOCAL_PROFILED_RESEARCH_LEDGER_PATH_INVALID"),
            (self.label_archive_path, "LOCAL_PROFILED_RESEARCH_LABEL_ARCHIVE_PATH_INVALID"),
            (
                self.trusted_immutable_cost_store_root,
                "LOCAL_PROFILED_RESEARCH_COST_STORE_ROOT_INVALID",
            ),
            (self.runtime_root, "LOCAL_PROFILED_RESEARCH_RUNTIME_ROOT_INVALID"),
            (self.model_dir, "LOCAL_PROFILED_RESEARCH_MODEL_DIR_INVALID"),
            (self.status_path, "LOCAL_PROFILED_RESEARCH_STATUS_PATH_INVALID"),
        ):
            _absolute_lexical(path, reason=reason)
        if (
            self.status_path.parent != self.runtime_root
            or any(
                _IDENTIFIER_RE.fullmatch(value) is None
                for value in (
                    self.manifest_auth_key_id,
                    self.local_research_auth_key_id,
                )
            )
            or self.manifest_auth_key_id == self.local_research_auth_key_id
            or type(self.page_limit) is not int
            or not 0 < self.page_limit <= MAX_PROFILED_OBSERVATION_PAGE_ROWS
            or type(self.scan_limit) is not int
            or not 0 < self.scan_limit <= MAX_PROFILED_TRAINING_SCAN_ROWS
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
            _fail("LOCAL_PROFILED_RESEARCH_CONFIG_INVALID")
        _owned_directory(
            self.repo_root,
            reason="LOCAL_PROFILED_RESEARCH_REPO_ROOT_SECURITY_INVALID",
        )
        _private_directory(
            self.runtime_root,
            reason="LOCAL_PROFILED_RESEARCH_RUNTIME_ROOT_SECURITY_INVALID",
        )

    @property
    def manifest_root(self) -> Path:
        return self.runtime_root / "manifests"

    @property
    def candidate_model_dir(self) -> Path:
        return self.model_dir / LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY


@dataclass(frozen=True, slots=True)
class LocallyAuthenticatedProfiledResearchCycleResultV1:
    classification: str
    publisher_status_sha256: str
    publisher_cycle_completed_at: str
    publisher_discovered_symbol_count: int
    publisher_eligible_symbol_count: int
    publisher_published_symbol_count: int
    manifest_id: str
    manifest_observation_time: str
    manifest_total_profiled_samples: int
    manifest_admitted_example_count: int
    manifest_label_unavailable_count: int
    manifest_ordered_entry_identities_sha256: str
    corpus_contract_sha256: str | None
    authorization_receipt_sha256: str | None
    base_checkpoint_id: str | None
    candidate_checkpoint_id: str | None
    candidate_checkpoint_generation: int | None
    candidate_source_manifest_id: str | None
    candidate_source_manifest_observation_time: str | None
    candidate_source_manifest_exact_match: bool
    candidate_source_corpus_entry_identity_equivalent: bool
    optimizer_execution_completed: bool
    checkpoint_publication_completed: bool
    already_published: bool
    checkpoint_artifact_verified: bool
    local_research_non_promotable: bool
    external_witness_verified: bool
    checkpoint_write_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    serving_activation_authorized: bool
    serving_promotion_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool

    def __post_init__(self) -> None:
        hashes = (
            self.publisher_status_sha256,
            self.manifest_id,
            self.manifest_ordered_entry_identities_sha256,
        )
        optional_hashes = (self.corpus_contract_sha256, self.authorization_receipt_sha256)
        authority = tuple(getattr(self, name) for name in _DOWNSTREAM_FALSE)
        source_manifest_present = self.candidate_source_manifest_id is not None
        if (
            not self.classification
            or not all(_SHA256_RE.fullmatch(value) is not None for value in hashes)
            or any(
                value is not None and _SHA256_RE.fullmatch(value) is None
                for value in optional_hashes
            )
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.publisher_discovered_symbol_count,
                    self.publisher_eligible_symbol_count,
                    self.publisher_published_symbol_count,
                    self.manifest_total_profiled_samples,
                    self.manifest_admitted_example_count,
                    self.manifest_label_unavailable_count,
                )
            )
            or self.manifest_total_profiled_samples
            != self.manifest_admitted_example_count
            + self.manifest_label_unavailable_count
            or source_manifest_present
            is not (self.candidate_source_manifest_observation_time is not None)
            or (
                self.candidate_source_manifest_id is not None
                and _SHA256_RE.fullmatch(self.candidate_source_manifest_id) is None
            )
            or type(self.candidate_source_manifest_exact_match) is not bool
            or type(self.candidate_source_corpus_entry_identity_equivalent) is not bool
            or self.candidate_source_corpus_entry_identity_equivalent
            is not source_manifest_present
            or self.candidate_source_manifest_exact_match
            and not self.candidate_source_corpus_entry_identity_equivalent
            or self.candidate_source_manifest_exact_match
            and (
                self.candidate_source_manifest_id != self.manifest_id
                or self.candidate_source_manifest_observation_time
                != self.manifest_observation_time
            )
            or self.checkpoint_artifact_verified is not source_manifest_present
            or self.local_research_non_promotable is not True
            or self.external_witness_verified is not False
            or self.checkpoint_write_authorized is not False
            or any(value is not False for value in authority)
        ):
            _fail("LOCAL_PROFILED_RESEARCH_CYCLE_RESULT_INVALID")
        _clock(
            self.publisher_cycle_completed_at,
            reason="LOCAL_PROFILED_RESEARCH_PUBLISHER_CLOCK_INVALID",
        )
        _clock(
            self.manifest_observation_time,
            reason="LOCAL_PROFILED_RESEARCH_MANIFEST_CLOCK_INVALID",
        )
        if self.candidate_source_manifest_observation_time is not None:
            _clock(
                self.candidate_source_manifest_observation_time,
                reason="LOCAL_PROFILED_RESEARCH_SOURCE_MANIFEST_CLOCK_INVALID",
            )


def _read_publisher_status(
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
) -> VerifiedProfiledBasePublisherCycleStatusV1:
    try:
        return read_verified_profiled_base_publisher_cycle_status_v1(
            status_path=config.publisher_status_path
        )
    except Exception as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            f"LOCAL_PROFILED_RESEARCH_PUBLISHER_STATUS_INVALID:{type(exc).__name__}"
        ) from exc


def _authenticate_manifest(
    *,
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    manifest_path: Path,
    manifest_id: str,
    observation_time: str,
) -> AuthenticatedProfiledTrainingObservationManifestV1:
    try:
        return authenticate_profiled_training_observation_manifest_v1(
            manifest_path=manifest_path,
            hmac_key=credentials.local_roles.manifest_hmac_key,
            expected_auth_key_id=config.manifest_auth_key_id,
            expected_manifest_id=manifest_id,
            expected_observation_time=observation_time,
        )
    except Exception as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            f"LOCAL_PROFILED_RESEARCH_MANIFEST_AUTHENTICATION_FAILED:{type(exc).__name__}"
        ) from exc


def _materialize_complete_corpus(
    *,
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    ledger: DurableFeatureSnapshotLedger,
    manifest: AuthenticatedProfiledTrainingObservationManifestV1,
) -> tuple[ProfiledTrainingObservationExampleV1, ...]:
    cursor = 0
    scanned = 0
    unavailable = 0
    candidates: list[ProfiledTrainingObservationExampleV1] = []
    while cursor < manifest.total_profiled_samples:
        try:
            page = read_profiled_training_observation_page_v1(
                manifest_path=manifest.manifest_path,
                ledger=ledger,
                trusted_immutable_cost_store_root=(
                    config.trusted_immutable_cost_store_root
                ),
                hmac_key=credentials.local_roles.manifest_hmac_key,
                expected_auth_key_id=config.manifest_auth_key_id,
                expected_manifest_id=manifest.manifest_id,
                expected_observation_time=manifest.observation_time,
                after_ordinal=cursor,
                limit=config.page_limit,
            )
        except Exception as exc:
            raise LocallyAuthenticatedProfiledResearchServiceV1Error(
                f"LOCAL_PROFILED_RESEARCH_PAGE_REOPEN_FAILED:{type(exc).__name__}"
            ) from exc
        expected_scanned = min(
            config.page_limit,
            manifest.total_profiled_samples - cursor,
        )
        if (
            page.manifest_id != manifest.manifest_id
            or page.observation_time != manifest.observation_time
            or page.requested_after_ordinal != cursor
            or page.scanned_entry_count != expected_scanned
            or page.next_after_ordinal != cursor + expected_scanned
            or page.has_more_manifest_entries
            is not (page.next_after_ordinal < manifest.total_profiled_samples)
        ):
            _fail("LOCAL_PROFILED_RESEARCH_PAGE_INVENTORY_INVALID")
        candidates.extend(page.examples)
        scanned += page.scanned_entry_count
        unavailable += page.label_unavailable_scanned
        cursor = page.next_after_ordinal
    if (
        scanned != manifest.total_profiled_samples
        or unavailable != manifest.label_unavailable_count
        or len(candidates) != manifest.admitted_example_count
        or tuple(item.ordinal for item in candidates)
        != tuple(sorted(item.ordinal for item in candidates))
    ):
        _fail("LOCAL_PROFILED_RESEARCH_COMPLETE_CORPUS_INVENTORY_INVALID")
    return tuple(candidates)


def _checkpoint_contract(manifest: CheckpointManifest) -> dict[str, Any] | None:
    contract = manifest.checkpoint_evidence.get("local_profiled_research_contract")
    return dict(contract) if type(contract) is dict else None


def _verify_local_research_authorization_contract(
    contract: Mapping[str, Any],
    *,
    expected_auth_key_id: str,
    authorization_hmac_key: bytes,
) -> None:
    """Recompute the exact local corpus authorization and receipt."""

    authorization_material = {
        "domain": LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN,
        "schema_version": "local_profiled_research_optimizer_authorization_v1",
        "authorization_key_id": contract.get("local_research_auth_key_id"),
        "corpus_contract_sha256": contract.get("corpus_contract_sha256"),
        "ordered_example_fingerprints_sha256": contract.get(
            "ordered_example_fingerprints_sha256"
        ),
        "manifest_id": contract.get("manifest_id"),
        "manifest_observation_time": contract.get("manifest_observation_time"),
        "admitted_example_count": contract.get("manifest_admitted_example_count"),
        "local_research_non_promotable": contract.get(
            "local_research_non_promotable"
        ),
        "external_witness_verified": contract.get("external_witness_verified"),
    }
    hash_fields = (
        authorization_material["corpus_contract_sha256"],
        authorization_material["ordered_example_fingerprints_sha256"],
        authorization_material["manifest_id"],
        contract.get("authorization_tag"),
        contract.get("authorization_receipt_sha256"),
    )
    if (
        authorization_material["authorization_key_id"] != expected_auth_key_id
        or not all(
            type(value) is str and _SHA256_RE.fullmatch(value) is not None
            for value in hash_fields
        )
        or type(authorization_material["admitted_example_count"]) is not int
        or authorization_material["admitted_example_count"] <= 0
        or authorization_material["local_research_non_promotable"] is not True
        or authorization_material["external_witness_verified"] is not False
        or type(authorization_material["manifest_observation_time"]) is not str
    ):
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CONTRACT_INVALID")
    _clock(
        cast(str, authorization_material["manifest_observation_time"]),
        reason="LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CLOCK_INVALID",
    )
    expected_tag = hmac.new(
        authorization_hmac_key,
        LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical_bytes(authorization_material),
        hashlib.sha256,
    ).hexdigest()
    expected_receipt = stable_sha256(
        {**authorization_material, "authorization_tag": expected_tag}
    )
    if not hmac.compare_digest(
        cast(str, contract.get("authorization_tag")),
        expected_tag,
    ) or not hmac.compare_digest(
        cast(str, contract.get("authorization_receipt_sha256")),
        expected_receipt,
    ):
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CONTRACT_INVALID")


def _manifest_contract_match(
    *,
    contract: Mapping[str, Any],
    manifest: AuthenticatedProfiledTrainingObservationManifestV1,
) -> tuple[bool, bool]:
    """Return exact-manifest and exact-entry-corpus equivalence separately."""

    entry_equivalent = (
        contract.get("manifest_ordered_entry_identities_sha256")
        == manifest.ordered_entry_identities_sha256
        and contract.get("manifest_total_profiled_samples")
        == manifest.total_profiled_samples
        and contract.get("manifest_admitted_example_count")
        == manifest.admitted_example_count
        and contract.get("manifest_label_unavailable_count")
        == manifest.label_unavailable_count
    )
    exact = entry_equivalent and all(
        contract.get(field_name) == observed
        for field_name, observed in (
            ("manifest_path", str(manifest.manifest_path)),
            ("manifest_id", manifest.manifest_id),
            ("manifest_metadata_sha256", manifest.metadata_sha256),
            (
                "manifest_observation_context_sha256",
                manifest.observation_context_sha256,
            ),
            ("manifest_entry_chain_head_sha256", manifest.entry_chain_head_sha256),
            (
                "manifest_feature_ledger_high_water_sha256",
                manifest.feature_ledger_high_water_sha256,
            ),
            (
                "manifest_label_archive_high_water_sha256",
                manifest.label_archive_high_water_sha256,
            ),
            ("manifest_observation_time", manifest.observation_time),
        )
    )
    return exact, entry_equivalent


def _verify_local_candidate_manifest(
    *,
    manager: V2HybridCheckpointManager,
    manifest: CheckpointManifest,
    expected_auth_key_id: str,
    authorization_hmac_key: bytes,
) -> dict[str, Any]:
    contract = _checkpoint_contract(manifest)
    if (
        manifest.lineage_kind != LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE
        or contract is None
        or contract.get("schema_version")
        != LOCAL_PROFILED_RESEARCH_CHECKPOINT_CONTRACT_V1_SCHEMA_VERSION
        or contract.get("local_research_auth_key_id") != expected_auth_key_id
        or contract.get("local_research_non_promotable") is not True
        or contract.get("external_witness_verified") is not False
        or contract.get("checkpoint_directory")
        != LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY
        or manifest.checkpoint_evidence.get("checkpoint_role")
        != LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE
        or manifest.checkpoint_causal_store
        != LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY
        or manifest.training_partition_digest
        != contract.get("corpus_contract_sha256")
        or manifest.parent_checkpoint_id != contract.get("base_checkpoint_id")
        or manifest.parent_policy_fingerprint
        != contract.get("base_policy_fingerprint")
        or manifest.model_parameter_fingerprint
        != contract.get("candidate_policy_fingerprint")
        or manifest.consumed_ppo_update_keys != ()
        or any(
            contract.get(name) is not True
            for name in (
                "full_manifest_authentication_verified",
                "full_entry_inventory_verified",
                "complete_corpus_reopened_after_optimizer",
                "optimizer_execution_completed",
                "checkpoint_write_scope_local_research_only",
            )
        )
        or _SHA1_RE.fullmatch(str(contract.get("code_release_sha", ""))) is None
        or any(
            _SHA256_RE.fullmatch(str(contract.get(name, ""))) is None
            for name in (
                "optimizer_implementation_artifact_sha256",
                "optimizer_training_result_artifact_sha256",
                "publisher_status_sha256",
                "manifest_metadata_sha256",
                "manifest_observation_context_sha256",
                "manifest_entry_chain_head_sha256",
                "manifest_ordered_entry_identities_sha256",
                "manifest_feature_ledger_high_water_sha256",
                "manifest_label_archive_high_water_sha256",
            )
        )
        or any(contract.get(name) is not False for name in _DOWNSTREAM_FALSE)
    ):
        _fail("LOCAL_PROFILED_RESEARCH_EXISTING_CHECKPOINT_CONTRACT_INVALID")
    _verify_local_research_authorization_contract(
        contract,
        expected_auth_key_id=expected_auth_key_id,
        authorization_hmac_key=authorization_hmac_key,
    )
    verification = manager.verify_manifest_artifact(manifest)
    if (
        verification.get("checkpoint_artifact_verified") is not True
        or verification.get("checkpoint_identity_verified") is not True
        or verification.get("checkpoint_evidence_verified") is not True
        or verification.get("weight_file_sha256_verified") is not True
        or verification.get("model_parameter_fingerprint_verified") is not True
    ):
        _fail("LOCAL_PROFILED_RESEARCH_EXISTING_CHECKPOINT_VERIFICATION_FAILED")
    return contract


def _matching_existing_candidate(
    *,
    manager: V2HybridCheckpointManager,
    manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    expected_auth_key_id: str,
    authorization_hmac_key: bytes,
) -> tuple[
    CheckpointManifest | None,
    bool,
    tuple[CheckpointManifest, ...],
]:
    try:
        existing = manager.manifests(
            input_dim=LOGICAL_MODEL_INPUT_COUNT,
            allowed_lineage_kinds=frozenset({LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE}),
            require_weight_blob=True,
        )
    except Exception as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            "LOCAL_PROFILED_RESEARCH_EXISTING_CHECKPOINT_SCAN_FAILED"
        ) from exc
    matching: CheckpointManifest | None = None
    matching_is_exact = False
    for candidate in existing:
        contract = _verify_local_candidate_manifest(
            manager=manager,
            manifest=candidate,
            expected_auth_key_id=expected_auth_key_id,
            authorization_hmac_key=authorization_hmac_key,
        )
        exact, entry_equivalent = _manifest_contract_match(
            contract=contract,
            manifest=manifest,
        )
        if exact:
            matching = candidate
            matching_is_exact = True
            break
        if matching is None and entry_equivalent:
            matching = candidate
    return matching, matching_is_exact, existing


def _load_local_research_base(
    *,
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    base_model: V2HybridPolicyModel,
    base_manager: V2HybridCheckpointManager,
    candidate_manager: V2HybridCheckpointManager,
    existing_local_candidates: tuple[CheckpointManifest, ...],
) -> tuple[str, str]:
    if not existing_local_candidates:
        lineage = capture_active_or_genesis_profiled_base_lineage_v1(
            repo_root=config.repo_root,
            base_model=base_model,
            base_manager=base_manager,
        )
        return lineage.checkpoint_id, lineage.model_parameter_fingerprint
    manifest = existing_local_candidates[0]
    try:
        load = candidate_manager.load_latest_weights(
            base_model,
            allowed_lineage_kinds=frozenset(
                {LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE}
            ),
            expected_checkpoint_id=manifest.checkpoint_id,
        )
    except Exception as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            "LOCAL_PROFILED_RESEARCH_BASE_LOAD_FAILED"
        ) from exc
    if (
        load.get("checkpoint_id") != manifest.checkpoint_id
        or load.get("latest_checkpoint_loadable") is not True
        or load.get("model_state_restored") is not True
        or load.get("checkpoint_evidence_verified") is not True
        or load.get("checkpoint_identity_verified") is not True
        or load.get("model_parameter_fingerprint_verified") is not True
        or model_parameter_fingerprint(base_model)
        != manifest.model_parameter_fingerprint
    ):
        _fail("LOCAL_PROFILED_RESEARCH_BASE_LOAD_IDENTITY_INVALID")
    return manifest.checkpoint_id, cast(str, manifest.model_parameter_fingerprint)


def _result(
    *,
    classification: str,
    publisher: VerifiedProfiledBasePublisherCycleStatusV1,
    manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    corpus_contract_sha256: str | None = None,
    authorization_receipt_sha256: str | None = None,
    base_checkpoint_id: str | None = None,
    candidate_checkpoint_id: str | None = None,
    candidate_checkpoint_generation: int | None = None,
    candidate_source_manifest_id: str | None = None,
    candidate_source_manifest_observation_time: str | None = None,
    candidate_source_manifest_exact_match: bool = False,
) -> LocallyAuthenticatedProfiledResearchCycleResultV1:
    published = classification == LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED
    recovered = classification == LOCAL_PROFILED_RESEARCH_ALREADY_PUBLISHED
    if published:
        candidate_source_manifest_id = manifest.manifest_id
        candidate_source_manifest_observation_time = manifest.observation_time
        candidate_source_manifest_exact_match = True
    return LocallyAuthenticatedProfiledResearchCycleResultV1(
        classification=classification,
        publisher_status_sha256=publisher.status_sha256,
        publisher_cycle_completed_at=publisher.cycle_completed_at,
        publisher_discovered_symbol_count=publisher.discovered_symbol_count,
        publisher_eligible_symbol_count=publisher.eligible_symbol_count,
        publisher_published_symbol_count=publisher.published_symbol_count,
        manifest_id=manifest.manifest_id,
        manifest_observation_time=manifest.observation_time,
        manifest_total_profiled_samples=manifest.total_profiled_samples,
        manifest_admitted_example_count=manifest.admitted_example_count,
        manifest_label_unavailable_count=manifest.label_unavailable_count,
        manifest_ordered_entry_identities_sha256=(
            manifest.ordered_entry_identities_sha256
        ),
        corpus_contract_sha256=corpus_contract_sha256,
        authorization_receipt_sha256=authorization_receipt_sha256,
        base_checkpoint_id=base_checkpoint_id,
        candidate_checkpoint_id=candidate_checkpoint_id,
        candidate_checkpoint_generation=candidate_checkpoint_generation,
        candidate_source_manifest_id=candidate_source_manifest_id,
        candidate_source_manifest_observation_time=(
            candidate_source_manifest_observation_time
        ),
        candidate_source_manifest_exact_match=(
            candidate_source_manifest_exact_match
        ),
        candidate_source_corpus_entry_identity_equivalent=published or recovered,
        optimizer_execution_completed=published,
        checkpoint_publication_completed=published,
        already_published=recovered,
        checkpoint_artifact_verified=published or recovered,
        local_research_non_promotable=True,
        external_witness_verified=False,
        checkpoint_write_authorized=False,
        **_DOWNSTREAM_FALSE,
    )


def run_locally_authenticated_profiled_research_cycle_v1(
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
) -> LocallyAuthenticatedProfiledResearchCycleResultV1:
    """Run or recover one local research checkpoint cycle."""

    if type(config) is not LocallyAuthenticatedProfiledResearchServiceConfigV1:
        _fail("LOCAL_PROFILED_RESEARCH_CONFIG_EXACT_TYPE_REQUIRED")
    if type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1:
        _fail("LOCAL_PROFILED_RESEARCH_CREDENTIALS_EXACT_TYPE_REQUIRED")
    config.__post_init__()
    local_key = credentials.local_research_hmac_key
    if local_key is None:
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED")
    if any(
        hmac.compare_digest(local_key, role_key)
        for role_key in (
            credentials.local_roles.state_hmac_key,
            credentials.local_roles.manifest_hmac_key,
            credentials.local_roles.head_hmac_key,
            credentials.local_roles.epoch_hmac_key,
        )
    ):
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_ROLE_REUSE_FORBIDDEN")

    publisher_before = _read_publisher_status(config)
    completed_at = _clock(
        publisher_before.cycle_completed_at,
        reason="LOCAL_PROFILED_RESEARCH_PUBLISHER_CLOCK_INVALID",
    )
    if completed_at > datetime.now(UTC):
        _fail("LOCAL_PROFILED_RESEARCH_PUBLISHER_CLOCK_IN_FUTURE")
    ledger = DurableFeatureSnapshotLedger(config.feature_ledger_path)
    label_archive = DurableCanonical5mLabelArchive(config.label_archive_path)
    try:
        built = build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=config.trusted_immutable_cost_store_root,
            label_archive=label_archive,
            manifest_root=config.manifest_root,
            training_observed_at=publisher_before.cycle_completed_at,
            auth_key_id=config.manifest_auth_key_id,
            hmac_key=credentials.local_roles.manifest_hmac_key,
            scan_limit=config.scan_limit,
            prepared_factory_wall_clock_observed_at=(
                publisher_before.cycle_completed_at
            ),
        )
    except Exception as exc:
        safe_reasons = tuple(
            reason
            for reason in getattr(exc, "reasons", ())
            if type(reason) is str and reason.startswith("PROFILED_OBSERVATION_")
        )[:32]
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            f"LOCAL_PROFILED_RESEARCH_MANIFEST_BUILD_FAILED:{type(exc).__name__}",
            *safe_reasons,
        ) from exc
    publisher_after = _read_publisher_status(config)
    if publisher_after != publisher_before:
        _fail("LOCAL_PROFILED_RESEARCH_PUBLISHER_STATUS_MOVED_DURING_MANIFEST_BUILD")
    manifest_before = _authenticate_manifest(
        config=config,
        credentials=credentials,
        manifest_path=built.manifest_path,
        manifest_id=built.manifest_id,
        observation_time=built.observation_time,
    )
    if manifest_before.admitted_example_count == 0:
        return _result(
            classification=LOCAL_PROFILED_RESEARCH_NO_EXAMPLES,
            publisher=publisher_before,
            manifest=manifest_before,
        )
    first_candidates = _materialize_complete_corpus(
        config=config,
        credentials=credentials,
        ledger=ledger,
        manifest=manifest_before,
    )

    base_manager = V2HybridCheckpointManager(config.model_dir)
    candidate_manager = V2HybridCheckpointManager(config.candidate_model_dir)
    with checkpoint_lifecycle_lease(
        config.model_dir,
        owner_role=LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
    ):
        matching, matching_is_exact, existing_local = _matching_existing_candidate(
            manager=candidate_manager,
            manifest=manifest_before,
            expected_auth_key_id=config.local_research_auth_key_id,
            authorization_hmac_key=local_key,
        )
        if matching is not None:
            contract = cast(dict[str, Any], _checkpoint_contract(matching))
            return _result(
                classification=LOCAL_PROFILED_RESEARCH_ALREADY_PUBLISHED,
                publisher=publisher_before,
                manifest=manifest_before,
                corpus_contract_sha256=cast(
                    str | None,
                    contract.get("corpus_contract_sha256"),
                ),
                authorization_receipt_sha256=cast(
                    str | None,
                    contract.get("authorization_receipt_sha256"),
                ),
                base_checkpoint_id=matching.parent_checkpoint_id,
                candidate_checkpoint_id=matching.checkpoint_id,
                candidate_checkpoint_generation=matching.checkpoint_generation,
                candidate_source_manifest_id=cast(str, contract.get("manifest_id")),
                candidate_source_manifest_observation_time=cast(
                    str,
                    contract.get("manifest_observation_time"),
                ),
                candidate_source_manifest_exact_match=matching_is_exact,
            )
        base_model = V2HybridPolicyModel(
            input_dim=LOGICAL_MODEL_INPUT_COUNT,
            checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
        )
        base_checkpoint_id, base_policy_fingerprint = _load_local_research_base(
            config=config,
            base_model=base_model,
            base_manager=base_manager,
            candidate_manager=candidate_manager,
            existing_local_candidates=existing_local,
        )
        training_observed_at = _utc_iso()
        if _clock(
            training_observed_at,
            reason="LOCAL_PROFILED_RESEARCH_TRAINING_CLOCK_INVALID",
        ) <= _clock(
            manifest_before.observation_time,
            reason="LOCAL_PROFILED_RESEARCH_MANIFEST_CLOCK_INVALID",
        ):
            _fail("LOCAL_PROFILED_RESEARCH_TRAINING_CLOCK_INVALID")
        trainer = V2HybridPPOTrainer(
            model=base_model,
            training_observed_at=training_observed_at,
        )
        execution = execute_locally_authenticated_profiled_research_optimizer_v1(
            authenticated_manifest=manifest_before,
            candidates=first_candidates,
            ledger=ledger,
            base_model=base_model,
            trainer=trainer,
            authorization_key_id=config.local_research_auth_key_id,
            authorization_hmac_key=local_key,
            validation_fraction=config.validation_fraction,
            optimizer_input_byte_budget=config.optimizer_input_byte_budget,
            state_resource_budget_bytes=config.state_resource_budget_bytes,
            checkpoint_serialization_byte_budget=(
                config.checkpoint_serialization_byte_budget
            ),
        )
        candidate_model = execution.candidate_model
        validate_locally_authenticated_profiled_research_execution_owner_v1(
            execution=execution,
            candidate_model=candidate_model,
        )
        manifest_after = _authenticate_manifest(
            config=config,
            credentials=credentials,
            manifest_path=manifest_before.manifest_path,
            manifest_id=manifest_before.manifest_id,
            observation_time=manifest_before.observation_time,
        )
        if manifest_after != manifest_before:
            _fail("LOCAL_PROFILED_RESEARCH_MANIFEST_MOVED_DURING_OPTIMIZATION")
        second_candidates = _materialize_complete_corpus(
            config=config,
            credentials=credentials,
            ledger=ledger,
            manifest=manifest_after,
        )
        second_fingerprints = tuple(
            validate_profiled_observation_example_for_local_research_v1(
                ledger=ledger,
                candidate=candidate,
                observation_time=manifest_after.observation_time,
            ).example_fingerprint_sha256
            for candidate in second_candidates
        )
        if (
            stable_sha256(list(second_fingerprints))
            != execution.ordered_example_fingerprints_sha256
            or len(second_candidates) != execution.admitted_example_count
        ):
            _fail("LOCAL_PROFILED_RESEARCH_POST_OPTIMIZER_CORPUS_REOPEN_INVALID")
        revalidate_locally_authenticated_profiled_research_publication_boundary_v1(
            execution=execution,
            base_model=base_model,
            candidate_model=candidate_model,
        )

        checkpoint_contract = {
            "schema_version": (
                LOCAL_PROFILED_RESEARCH_CHECKPOINT_CONTRACT_V1_SCHEMA_VERSION
            ),
            "checkpoint_directory": LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY,
            "publisher_status_path": str(config.publisher_status_path),
            "publisher_status_sha256": publisher_before.status_sha256,
            "publisher_cycle_completed_at": publisher_before.cycle_completed_at,
            "publisher_discovered_symbol_count": (
                publisher_before.discovered_symbol_count
            ),
            "publisher_eligible_symbol_count": publisher_before.eligible_symbol_count,
            "publisher_published_symbol_count": publisher_before.published_symbol_count,
            "manifest_path": str(manifest_before.manifest_path),
            "manifest_id": manifest_before.manifest_id,
            "manifest_metadata_sha256": manifest_before.metadata_sha256,
            "manifest_observation_context_sha256": (
                manifest_before.observation_context_sha256
            ),
            "manifest_entry_chain_head_sha256": (
                manifest_before.entry_chain_head_sha256
            ),
            "manifest_ordered_entry_identities_sha256": (
                manifest_before.ordered_entry_identities_sha256
            ),
            "manifest_feature_ledger_high_water_sha256": (
                manifest_before.feature_ledger_high_water_sha256
            ),
            "manifest_label_archive_high_water_sha256": (
                manifest_before.label_archive_high_water_sha256
            ),
            "manifest_observation_time": manifest_before.observation_time,
            "manifest_total_profiled_samples": manifest_before.total_profiled_samples,
            "manifest_admitted_example_count": (
                manifest_before.admitted_example_count
            ),
            "manifest_label_unavailable_count": (
                manifest_before.label_unavailable_count
            ),
            "full_manifest_authentication_verified": True,
            "full_entry_inventory_verified": True,
            "complete_corpus_reopened_after_optimizer": True,
            "local_research_auth_key_id": config.local_research_auth_key_id,
            "authorization_tag": execution.authorization_tag,
            "authorization_receipt_sha256": (
                execution.authorization_receipt_sha256
            ),
            "corpus_contract_sha256": execution.corpus_contract_sha256,
            "ordered_example_fingerprints_sha256": (
                execution.ordered_example_fingerprints_sha256
            ),
            "optimizer_implementation_artifact_sha256": (
                execution.optimizer_implementation_artifact_sha256
            ),
            "optimizer_training_result_artifact_sha256": (
                execution.training_result_artifact_sha256
            ),
            "code_release_sha": execution.code_release_sha,
            "base_checkpoint_id": base_checkpoint_id,
            "base_policy_fingerprint": base_policy_fingerprint,
            "candidate_policy_fingerprint": (
                execution.candidate_model_parameter_fingerprint
            ),
            "optimizer_execution_completed": True,
            "checkpoint_write_scope_local_research_only": True,
            "local_research_non_promotable": True,
            "external_witness_verified": False,
            **_DOWNSTREAM_FALSE,
        }
        try:
            published = candidate_manager.write_checkpoint(
                model=candidate_model,
                input_dim=candidate_model.input_dim,
                device=candidate_model.device,
                cuda_active=candidate_model.cuda_active,
                lineage_kind=LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE,
                parent_checkpoint_id=base_checkpoint_id,
                parent_policy_fingerprint=base_policy_fingerprint,
                consumed_ppo_update_keys=(),
                training_partition_digest=execution.corpus_contract_sha256,
                checkpoint_evidence={
                    "checkpoint_role": LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE,
                    "local_profiled_research_contract": checkpoint_contract,
                },
            )
            verification = candidate_manager.verify_manifest_artifact(published)
        except Exception as exc:
            raise LocallyAuthenticatedProfiledResearchServiceV1Error(
                f"LOCAL_PROFILED_RESEARCH_CHECKPOINT_WRITE_FAILED:{type(exc).__name__}"
            ) from exc
        if (
            published.lineage_kind != LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE
            or published.parent_checkpoint_id != base_checkpoint_id
            or published.parent_policy_fingerprint != base_policy_fingerprint
            or published.training_partition_digest != execution.corpus_contract_sha256
            or published.model_parameter_fingerprint
            != execution.candidate_model_parameter_fingerprint
            or verification.get("checkpoint_artifact_verified") is not True
            or verification.get("checkpoint_identity_verified") is not True
            or verification.get("checkpoint_evidence_verified") is not True
            or verification.get("weight_file_sha256_verified") is not True
            or verification.get("model_parameter_fingerprint_verified") is not True
            or model_parameter_fingerprint(base_model)
            != execution.base_model_parameter_fingerprint
        ):
            _fail("LOCAL_PROFILED_RESEARCH_CHECKPOINT_POSTCOMMIT_INVALID")
        return _result(
            classification=LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED,
            publisher=publisher_before,
            manifest=manifest_after,
            corpus_contract_sha256=execution.corpus_contract_sha256,
            authorization_receipt_sha256=execution.authorization_receipt_sha256,
            base_checkpoint_id=base_checkpoint_id,
            candidate_checkpoint_id=published.checkpoint_id,
            candidate_checkpoint_generation=published.checkpoint_generation,
        )


def _cycle_result_material(
    result: LocallyAuthenticatedProfiledResearchCycleResultV1,
) -> dict[str, Any]:
    return {
        name: getattr(result, name)
        for name in result.__dataclass_fields__  # type: ignore[attr-defined]
    }


def _status_payload(
    *,
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    classification: str,
    result: LocallyAuthenticatedProfiledResearchCycleResultV1 | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    local_key = credentials.local_research_hmac_key
    if local_key is None:
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED")
    raw_reasons = getattr(error, "reasons", ()) if error is not None else ()
    reasons = [
        value
        for value in raw_reasons
        if type(value) is str and value.startswith(_SAFE_STATUS_REASON_PREFIXES)
    ][:32]
    unsigned = {
        "schema_version": LOCAL_PROFILED_RESEARCH_SERVICE_STATUS_V1_SCHEMA_VERSION,
        "status_generated_at": _utc_iso(),
        "code_sha": (
            os.environ.get("AI_BOT_CODE_SHA", "")
            if _SHA1_RE.fullmatch(os.environ.get("AI_BOT_CODE_SHA", "")) is not None
            else "UNPINNED"
        ),
        "classification": classification,
        "service_process_active": True,
        "cycle_in_progress": classification == LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING,
        "local_research_auth_key_id": config.local_research_auth_key_id,
        "local_research_authentication_configured": True,
        "external_witness_verified": False,
        "local_research_non_promotable": True,
        "candidate_directory": str(config.candidate_model_dir),
        "cycle_result": None if result is None else _cycle_result_material(result),
        "error": (
            None
            if error is None
            else {
                "error_type": type(error).__name__,
                "reason_codes": reasons,
            }
        ),
        "side_effect_contract": {
            "network_access_authorized": False,
            "exchange_credentials_loaded": False,
            "checkpoint_write_scope": str(config.candidate_model_dir),
            "prediction_or_serving_activation_authorized": False,
            "paper_or_live_trading_authorized": False,
            "order_submission_authorized": False,
        },
        **_DOWNSTREAM_FALSE,
    }
    unsigned_bytes = _canonical_bytes(unsigned)
    status_sha256 = hashlib.sha256(unsigned_bytes).hexdigest()
    auth_tag = hmac.new(
        local_key,
        b"v2/native-trainer/local-profiled-research-service-status/v1\0"
        + unsigned_bytes,
        hashlib.sha256,
    ).hexdigest()
    return {
        **unsigned,
        "status_sha256": status_sha256,
        "status_auth_tag": auth_tag,
        "status_local_hmac_verified_at_write": True,
    }


def write_locally_authenticated_profiled_research_status_v1(
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    payload: Mapping[str, Any],
) -> None:
    path = config.status_path
    _private_directory(
        path.parent,
        reason="LOCAL_PROFILED_RESEARCH_STATUS_PARENT_SECURITY_INVALID",
    )
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            "LOCAL_PROFILED_RESEARCH_STATUS_TARGET_INVALID"
        ) from exc
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or stat.S_ISLNK(existing.st_mode)
        or existing.st_uid != os.geteuid()
        or existing.st_nlink != 1
        or stat.S_IMODE(existing.st_mode) & 0o022
    ):
        _fail("LOCAL_PROFILED_RESEARCH_STATUS_TARGET_INVALID")
    encoded = _canonical_bytes(dict(payload)) + b"\n"
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        temporary = None
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as exc:
        raise LocallyAuthenticatedProfiledResearchServiceV1Error(
            "LOCAL_PROFILED_RESEARCH_STATUS_WRITE_FAILED"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _emit(payload: Mapping[str, Any]) -> None:
    summary = {
        "schema_version": "locally_authenticated_profiled_research_summary_v1",
        "classification": payload.get("classification"),
        "status_generated_at": payload.get("status_generated_at"),
        "status_sha256": payload.get("status_sha256"),
        "code_sha": payload.get("code_sha"),
    }
    print(_canonical_bytes(summary).decode("ascii"), flush=True)


def run_locally_authenticated_profiled_research_service_v1(
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    *,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    cycle_runner: Callable[
        [
            LocallyAuthenticatedProfiledResearchServiceConfigV1,
            AuthenticatedProfiledResidentRuntimeCredentialsV1,
        ],
        LocallyAuthenticatedProfiledResearchCycleResultV1,
    ] = run_locally_authenticated_profiled_research_cycle_v1,
    writer: Callable[
        [LocallyAuthenticatedProfiledResearchServiceConfigV1, Mapping[str, Any]],
        None,
    ] = write_locally_authenticated_profiled_research_status_v1,
    emit: Callable[[Mapping[str, Any]], None] = _emit,
) -> int:
    """Remain observable while running bounded local research cycles."""

    if type(config) is not LocallyAuthenticatedProfiledResearchServiceConfigV1:
        _fail("LOCAL_PROFILED_RESEARCH_CONFIG_EXACT_TYPE_REQUIRED")
    if type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1:
        _fail("LOCAL_PROFILED_RESEARCH_CREDENTIALS_EXACT_TYPE_REQUIRED")
    if type(once) is not bool:
        _fail("LOCAL_PROFILED_RESEARCH_ONCE_INVALID")
    if credentials.local_research_hmac_key is None:
        _fail("LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED")
    while True:
        running = _status_payload(
            config=config,
            credentials=credentials,
            classification=LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING,
        )
        writer(config, running)
        emit(running)
        failed = False
        try:
            result = cycle_runner(config, credentials)
            payload = _status_payload(
                config=config,
                credentials=credentials,
                classification=result.classification,
                result=result,
            )
        except Exception as exc:  # Remain observable; all authority stays false.
            failed = True
            payload = _status_payload(
                config=config,
                credentials=credentials,
                classification=LOCAL_PROFILED_RESEARCH_FAIL_CLOSED,
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
    "LOCAL_PROFILED_RESEARCH_ALREADY_PUBLISHED",
    "LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY",
    "LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE",
    "LOCAL_PROFILED_RESEARCH_CHECKPOINT_CONTRACT_V1_SCHEMA_VERSION",
    "LOCAL_PROFILED_RESEARCH_CHECKPOINT_PUBLISHED",
    "LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING",
    "LOCAL_PROFILED_RESEARCH_FAIL_CLOSED",
    "LOCAL_PROFILED_RESEARCH_NO_EXAMPLES",
    "LOCAL_PROFILED_RESEARCH_SERVICE_STATUS_V1_SCHEMA_VERSION",
    "LocallyAuthenticatedProfiledResearchCycleResultV1",
    "LocallyAuthenticatedProfiledResearchServiceConfigV1",
    "LocallyAuthenticatedProfiledResearchServiceV1Error",
    "run_locally_authenticated_profiled_research_cycle_v1",
    "run_locally_authenticated_profiled_research_service_v1",
    "write_locally_authenticated_profiled_research_status_v1",
)
