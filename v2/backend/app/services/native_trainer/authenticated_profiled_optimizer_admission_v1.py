"""Fail-closed admission seam for externally witnessed profiled samples.

This module is deliberately a validator, not a trainer.  It reauthenticates a
fixed observation manifest, reopens the exact local full-consumption receipt,
verifies an independently signed Ed25519 completion authorization, and then
reopens one exact sample/label/tensor tuple from the manifest and its durable
stores.  The result is an outcome-supervised optimizer *input candidate*.

No signing key, signing helper, optimizer, checkpoint writer, model publisher,
prediction path, or trading path exists here.  A local completion candidate,
local HMAC, caller boolean, or caller-created dataclass can never authorize the
adapter: the exact completion and manifest bindings must carry a signature from
the independently configured witness public key.

The profiled manifest's historical ``trust_row.available_at`` field means
``trainer_sample_available_at`` (ledger postcommit readback).  It is never
interpreted as feature availability here.  The decision-time feature vector is
reopened from its exact parent record.  Source ``available_at``, transform
``available_at``, feature ``generated_at``, enrichment ``generated_at``, and
sample postcommit clocks remain distinct.  The adapter requires::

    model_feature_cutoff <= source_feature_available_at
                         <= decision_feature_available_at
                         <= feature_generated_at
                         <= training_record_generated_at
                         <= decision_time
                          < trainer_sample_available_at < observation_time

The finalized outcome label must become available strictly after the decision
and strictly before the fixed observation.  PPO behavior-policy terms remain
disabled because this lane has no genuine behavior receipt contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_PROFILE_SELECTION_MASK,
    LOGICAL_PROFILE_SELECTION_MASK_SHA256,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY,
    PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    LocalProfiledTrainingObservationCompletionCandidateV1,
    LocalProfiledTrainingObservationPageReceiptV1,
    ProfiledTrainingObservationManifestHeadV1Error,
    read_local_profiled_training_observation_completion_candidate_v1,
    read_local_profiled_training_observation_page_receipt_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION,
    AuthenticatedProfiledTrainingObservationManifestV1,
    ProfiledTrainingObservationExampleV1,
    ProfiledTrainingObservationManifestV1Error,
    authenticate_profiled_training_observation_manifest_v1,
    read_profiled_training_observation_page_v1,
)

AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_optimizer_admission_v1"
)
AUTHENTICATED_PROFILED_OUTCOME_TARGET_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_outcome_supervised_target_v1"
)
PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_external_completion_authorization_v1"
)
PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_ALGORITHM: Final = "Ed25519"
PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN: Final = (
    "v2/native-trainer/profiled-optimizer-external-completion-authorization/v1"
)
PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR: Final = (
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN.encode("ascii") + b"\0"
)
PROFILED_OPTIMIZER_ADMISSION_SCOPE: Final = "EXACT_PROFILED_OUTCOME_SUPERVISED_INPUT_ADMISSION_ONLY"
PROFILED_OPTIMIZER_OBJECTIVE_LANE: Final = "PROFILED_OUTCOME_SUPERVISED_NO_BEHAVIOR_POLICY_TERMS"

# Cryptographic/parser bounds only.  These are not market, sample-selection,
# risk, leverage, margin, performance, or optimizer thresholds.
ED25519_PUBLIC_KEY_BYTES: Final = 32
ED25519_SIGNATURE_BYTES: Final = 64
MIN_EXTERNAL_CHALLENGE_BYTES: Final = 32
MAX_EXTERNAL_CHALLENGE_BYTES: Final = 4_096
MAX_EXTERNAL_AUTHORIZATION_BYTES: Final = 128 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_ADMISSION_TOKEN = object()
_TARGET_TOKEN = object()
_VERIFIED_AUTHORIZATION_TOKEN = object()
_FACTORY_SEAL_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
_TARGET_FACTORY_SEAL_DOMAIN = b"authenticated_profiled_outcome_target_factory_seal_v1"
_ADMISSION_FACTORY_SEAL_DOMAIN = b"authenticated_profiled_optimizer_admission_factory_seal_v1"
_MODEL_VECTOR_DOMAIN = b"authenticated_profiled_optimizer_model_input_float64_v1\0"
_LOGICAL_MODEL_VECTOR_DOMAIN = b"canonical_feature_model_vector_v3\0"
_LABEL_VALUE_DOMAIN = b"profiled_training_after_cost_label_float64_v1\0"

_DOWNSTREAM_FALSE = {
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}


class AuthenticatedProfiledOptimizerAdmissionV1Error(RuntimeError):
    """A profiled candidate, witness authorization, or causal clock failed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledOptimizerAdmissionV1Error(*reasons) from None


class _FactorySeal:
    """One-time factory seal that cannot be carried onto changed material."""

    __slots__ = ("_digest", "_domain")

    def __init__(self, *, domain: bytes, construction_token: object) -> None:
        if construction_token is not _FACTORY_SEAL_TOKEN or type(domain) is not bytes:
            _fail("PROFILED_OPTIMIZER_FACTORY_SEAL_CONSTRUCTION_FORBIDDEN")
        object.__setattr__(self, "_domain", bytes(domain))
        object.__setattr__(self, "_digest", None)

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        _fail("PROFILED_OPTIMIZER_FACTORY_SEAL_IMMUTABLE")

    def validate_or_bind(self, *, domain: bytes, material: object, reason: str) -> None:
        if self._domain != domain:
            _fail(reason)
        expected = hmac.digest(
            _FACTORY_SEAL_KEY,
            domain
            + b"\0"
            + _canonical_json_bytes(
                material,
                reason=reason,
            ),
            "sha256",
        )
        current = self._digest
        if current is None:
            object.__setattr__(self, "_digest", expected)
        elif type(current) is not bytes or not hmac.compare_digest(current, expected):
            _fail(reason)


def _require_factory_seal(
    value: object,
    *,
    domain: bytes,
    material: object,
    reason: str,
) -> None:
    if type(value) is not _FactorySeal:
        _fail(reason)
    cast(_FactorySeal, value).validate_or_bind(
        domain=domain,
        material=material,
        reason=reason,
    )


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return normalized


def _canonical_json_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(reason) from exc
    if not encoded or len(encoded) > MAX_EXTERNAL_AUTHORIZATION_BYTES:
        _fail(reason)
    return encoded


def _parse_exact_authorization(value: object) -> dict[str, Any]:
    if type(value) is not bytes or not value or len(value) > MAX_EXTERNAL_AUTHORIZATION_BYTES:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BYTES_INVALID")
    raw = bytes(value)

    def reject_constant(_value: str) -> NoReturn:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_NONFINITE_FORBIDDEN")

    def reject_float(_value: str) -> NoReturn:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_FLOAT_FORBIDDEN")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_DUPLICATE_KEY")
            result[key] = item
        return result

    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
            parse_float=reject_float,
        )
    except AuthenticatedProfiledOptimizerAdmissionV1Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            "PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_JSON_INVALID"
        ) from exc
    if type(parsed) is not dict:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_OBJECT_REQUIRED")
    material = cast(dict[str, Any], parsed)
    if not hmac.compare_digest(
        _canonical_json_bytes(
            material,
            reason="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_JSON_INVALID",
        ),
        raw,
    ):
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_NOT_CANONICAL")
    return material


def _challenge(value: object) -> bytes:
    if not isinstance(value, bytes | bytearray | memoryview):
        _fail("PROFILED_OPTIMIZER_EXTERNAL_CHALLENGE_BYTES_REQUIRED")
    result = bytes(value)
    if not MIN_EXTERNAL_CHALLENGE_BYTES <= len(result) <= MAX_EXTERNAL_CHALLENGE_BYTES:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_CHALLENGE_SIZE_INVALID")
    return result


def _public_key(value: object, *, expected_sha256: object) -> tuple[bytes, str]:
    if type(value) is not bytes or len(value) != ED25519_PUBLIC_KEY_BYTES:
        _fail("PROFILED_OPTIMIZER_WITNESS_PUBLIC_KEY_INVALID")
    key = bytes(value)
    if not _valid_sha256(expected_sha256):
        _fail("PROFILED_OPTIMIZER_WITNESS_PUBLIC_KEY_FINGERPRINT_INVALID")
    digest = hashlib.sha256(key).hexdigest()
    if not hmac.compare_digest(digest, cast(str, expected_sha256)):
        _fail("PROFILED_OPTIMIZER_WITNESS_PUBLIC_KEY_FINGERPRINT_MISMATCH")
    return key, digest


def _manifest_binding(
    manifest: AuthenticatedProfiledTrainingObservationManifestV1,
) -> dict[str, Any]:
    if type(manifest) is not AuthenticatedProfiledTrainingObservationManifestV1:
        _fail("PROFILED_OPTIMIZER_AUTHENTICATED_MANIFEST_EXACT_TYPE_REQUIRED")
    if (
        manifest.full_manifest_authentication_verified is not True
        or manifest.full_entry_inventory_verified is not True
        or any(
            value is not False
            for value in (
                manifest.external_monotonic_manifest_head_verified,
                manifest.full_consumption_external_ack_verified,
                manifest.optimizer_admission_authorized,
                manifest.checkpoint_write_authorized,
                manifest.model_write_authorized,
                manifest.prediction_authorized,
                manifest.paper_trading_authorized,
                manifest.live_execution_authorized,
                manifest.execution_authorized,
                manifest.runtime_wired,
            )
        )
    ):
        _fail("PROFILED_OPTIMIZER_AUTHENTICATED_MANIFEST_AUTHORITY_INVALID")
    return {
        "schema_version": "profiled_optimizer_manifest_binding_v1",
        "manifest_id": manifest.manifest_id,
        "metadata_sha256": manifest.metadata_sha256,
        "metadata_auth_tag": manifest.metadata_auth_tag,
        "auth_key_id": manifest.auth_key_id,
        "observation_time": manifest.observation_time,
        "observation_context_sha256": manifest.observation_context_sha256,
        "feature_ledger_high_water_sha256": manifest.feature_ledger_high_water_sha256,
        "feature_ledger_archive_chain_sha256": (manifest.feature_ledger_archive_chain_sha256),
        "feature_ledger_ordered_receipts_sha256": (manifest.feature_ledger_ordered_receipts_sha256),
        "label_archive_high_water_sha256": manifest.label_archive_high_water_sha256,
        "label_archive_archive_chain_sha256": manifest.label_archive_archive_chain_sha256,
        "label_archive_ordered_receipts_sha256": (manifest.label_archive_ordered_receipts_sha256),
        "entry_chain_head_sha256": manifest.entry_chain_head_sha256,
        "ordered_entry_identities_sha256": manifest.ordered_entry_identities_sha256,
        "total_profiled_samples": manifest.total_profiled_samples,
        "admitted_example_count": manifest.admitted_example_count,
        "label_unavailable_count": manifest.label_unavailable_count,
        "ledger_exclusion_count": manifest.ledger_exclusion_count,
        "ledger_exclusion_inventory_sha256": manifest.ledger_exclusion_inventory_sha256,
    }


def _completion_binding(
    completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    final_page: LocalProfiledTrainingObservationPageReceiptV1,
) -> dict[str, Any]:
    if type(completion) is not LocalProfiledTrainingObservationCompletionCandidateV1:
        _fail("PROFILED_OPTIMIZER_LOCAL_COMPLETION_EXACT_TYPE_REQUIRED")
    if type(final_page) is not LocalProfiledTrainingObservationPageReceiptV1:
        _fail("PROFILED_OPTIMIZER_FINAL_PAGE_EXACT_TYPE_REQUIRED")
    final_page_event = completion._material.get("final_page_receipt_event_sha256")
    if (
        final_page_event != final_page.page_receipt_event_sha256
        or final_page.epoch_id != completion.epoch_id
        or final_page.page_sequence != completion.page_count
        or final_page.has_more_manifest_entries is not False
        or final_page.cumulative_scanned_entry_count != completion.consumed_entry_count
        or final_page.cumulative_admitted_entry_count != completion.admitted_entry_count
        or final_page.cumulative_label_unavailable_count != completion.label_unavailable_count
        or final_page.page_end_entry_chain_sha256 != completion.terminal_entry_chain_sha256
        or final_page.page_transition_sha256 != completion.final_page_transition_sha256
        or final_page.ordered_page_root_sha256 != completion.ordered_page_root_sha256
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_FINAL_PAGE_BINDING_INVALID")
    return {
        "schema_version": "profiled_optimizer_full_consumption_binding_v1",
        "completion_event_sha256": completion.completion_event_sha256,
        "completion_event_byte_count": completion.completion_event_byte_count,
        "completion_id": completion.completion_id,
        "epoch_id": completion.epoch_id,
        "consumer_lane": completion.consumer_lane,
        "head_candidate_event_sha256": completion.head_candidate_event_sha256,
        "head_revision": completion.head_revision,
        "manifest_id": completion.manifest_id,
        "page_count": completion.page_count,
        "consumed_entry_count": completion.consumed_entry_count,
        "admitted_entry_count": completion.admitted_entry_count,
        "label_unavailable_count": completion.label_unavailable_count,
        "terminal_entry_chain_sha256": completion.terminal_entry_chain_sha256,
        "final_page_receipt_event_sha256": final_page.page_receipt_event_sha256,
        "final_page_transition_sha256": completion.final_page_transition_sha256,
        "ordered_page_root_sha256": completion.ordered_page_root_sha256,
        "final_page_verified_at": final_page.verified_at,
        "full_consumption_locally_verified": True,
    }


def _authorization_unsigned_material(
    *,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    final_page: LocalProfiledTrainingObservationPageReceiptV1,
    witness_id: str,
    namespace: str,
    witness_public_key_sha256: str,
    authorization_sequence: int,
    previous_authorization_event_sha256: str,
    authorization_challenge: bytes,
    accepted_at: str,
) -> dict[str, Any]:
    witness = _identifier(witness_id, reason="PROFILED_OPTIMIZER_WITNESS_ID_INVALID")
    witness_namespace = _identifier(
        namespace,
        reason="PROFILED_OPTIMIZER_WITNESS_NAMESPACE_INVALID",
    )
    if not _valid_sha256(witness_public_key_sha256):
        _fail("PROFILED_OPTIMIZER_WITNESS_PUBLIC_KEY_FINGERPRINT_INVALID")
    if type(authorization_sequence) is not int or authorization_sequence <= 0:
        _fail("PROFILED_OPTIMIZER_WITNESS_SEQUENCE_INVALID")
    if not _valid_sha256(previous_authorization_event_sha256):
        _fail("PROFILED_OPTIMIZER_WITNESS_PREVIOUS_EVENT_INVALID")
    challenge = _challenge(authorization_challenge)
    accepted = _clock(
        accepted_at,
        reason="PROFILED_OPTIMIZER_WITNESS_ACCEPTED_AT_INVALID",
    )
    observation = _clock(
        authenticated_manifest.observation_time,
        reason="PROFILED_OPTIMIZER_MANIFEST_OBSERVATION_TIME_INVALID",
    )
    final_page_verified = _clock(
        final_page.verified_at,
        reason="PROFILED_OPTIMIZER_FINAL_PAGE_VERIFIED_AT_INVALID",
    )
    if accepted <= max(observation, final_page_verified):
        _fail("PROFILED_OPTIMIZER_WITNESS_ACCEPTED_BEFORE_FULL_CONSUMPTION")
    return {
        "schema_version": (PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION),
        "signature_algorithm": (PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_ALGORITHM),
        "signature_domain": PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN,
        "witness_id": witness,
        "namespace": witness_namespace,
        "declared_witness_public_key_sha256": witness_public_key_sha256,
        "authorization_sequence": authorization_sequence,
        "previous_authorization_event_sha256": previous_authorization_event_sha256,
        "authorization_challenge_sha256": hashlib.sha256(challenge).hexdigest(),
        "authorization_challenge_byte_count": len(challenge),
        "accepted_at": accepted_at,
        "authorization_scope": PROFILED_OPTIMIZER_ADMISSION_SCOPE,
        "manifest_binding": _manifest_binding(authenticated_manifest),
        "full_consumption_binding": _completion_binding(completion, final_page),
        "external_monotonic_manifest_head_verified": True,
        "full_consumption_external_ack_verified": True,
        "profiled_optimizer_admission_authorized": True,
        "outcome_supervised_objective_only": True,
        "behavior_policy_terms_authorized": False,
        **_DOWNSTREAM_FALSE,
    }


def profiled_optimizer_external_completion_signing_payload_v1(
    *,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    final_page: LocalProfiledTrainingObservationPageReceiptV1,
    witness_id: str,
    namespace: str,
    witness_public_key_sha256: str,
    authorization_sequence: int,
    previous_authorization_event_sha256: str,
    authorization_challenge: bytes | bytearray | memoryview,
    accepted_at: str,
) -> bytes:
    """Return exact bytes an independent witness must sign.

    This is a schema encoder only.  It never accepts a private key and cannot
    produce an authorization envelope or an admitted optimizer candidate.
    """

    unsigned = _authorization_unsigned_material(
        authenticated_manifest=authenticated_manifest,
        completion=completion,
        final_page=final_page,
        witness_id=witness_id,
        namespace=namespace,
        witness_public_key_sha256=witness_public_key_sha256,
        authorization_sequence=authorization_sequence,
        previous_authorization_event_sha256=previous_authorization_event_sha256,
        authorization_challenge=_challenge(authorization_challenge),
        accepted_at=accepted_at,
    )
    return PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR + (
        _canonical_json_bytes(
            unsigned,
            reason="PROFILED_OPTIMIZER_EXTERNAL_SIGNING_PAYLOAD_INVALID",
        )
    )


@dataclass(frozen=True, slots=True)
class VerifiedProfiledOptimizerExternalCompletionAuthorizationV1:
    witness_id: str
    namespace: str
    witness_public_key_sha256: str
    authorization_sequence: int
    previous_authorization_event_sha256: str
    accepted_at: str
    authorization_envelope_sha256: str
    manifest_id: str
    completion_event_sha256: str
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    profiled_optimizer_admission_authorized: bool
    optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _authorization_envelope: bytes = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _VERIFIED_AUTHORIZATION_TOKEN
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or _IDENTIFIER_RE.fullmatch(self.namespace) is None
            or self.authorization_sequence <= 0
            or not all(
                _valid_sha256(value)
                for value in (
                    self.witness_public_key_sha256,
                    self.previous_authorization_event_sha256,
                    self.authorization_envelope_sha256,
                    self.manifest_id,
                    self.completion_event_sha256,
                )
            )
            or self.external_monotonic_manifest_head_verified is not True
            or self.full_consumption_external_ack_verified is not True
            or self.profiled_optimizer_admission_authorized is not True
            or any(
                value is not False
                for value in (
                    self.optimizer_execution_authorized,
                    self.checkpoint_write_authorized,
                    self.model_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.order_submission_authorized,
                    self.execution_authorized,
                    self.runtime_wired,
                )
            )
            or hashlib.sha256(self._authorization_envelope).hexdigest()
            != self.authorization_envelope_sha256
        ):
            _fail("PROFILED_OPTIMIZER_VERIFIED_EXTERNAL_AUTHORIZATION_INVALID")
        _clock(
            self.accepted_at,
            reason="PROFILED_OPTIMIZER_VERIFIED_AUTHORIZATION_CLOCK_INVALID",
        )


def _verify_external_authorization(
    *,
    authorization_envelope: bytes,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    final_page: LocalProfiledTrainingObservationPageReceiptV1,
    expected_witness_id: str,
    expected_namespace: str,
    witness_public_key_bytes: bytes,
    expected_witness_public_key_sha256: str,
    expected_authorization_sequence: int,
    expected_previous_authorization_event_sha256: str,
    authorization_challenge: bytes,
) -> VerifiedProfiledOptimizerExternalCompletionAuthorizationV1:
    parsed = _parse_exact_authorization(authorization_envelope)
    if set(parsed) != {
        "schema_version",
        "signature_algorithm",
        "signature_domain",
        "witness_id",
        "namespace",
        "declared_witness_public_key_sha256",
        "authorization_sequence",
        "previous_authorization_event_sha256",
        "authorization_challenge_sha256",
        "authorization_challenge_byte_count",
        "accepted_at",
        "authorization_scope",
        "manifest_binding",
        "full_consumption_binding",
        "external_monotonic_manifest_head_verified",
        "full_consumption_external_ack_verified",
        "profiled_optimizer_admission_authorized",
        "outcome_supervised_objective_only",
        "behavior_policy_terms_authorized",
        *_DOWNSTREAM_FALSE,
        "signature_hex",
    }:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_FIELD_SET_INVALID")
    signature_hex = parsed.get("signature_hex")
    if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_SIGNATURE_INVALID")
    unsigned = {key: value for key, value in parsed.items() if key != "signature_hex"}
    expected = _authorization_unsigned_material(
        authenticated_manifest=authenticated_manifest,
        completion=completion,
        final_page=final_page,
        witness_id=expected_witness_id,
        namespace=expected_namespace,
        witness_public_key_sha256=expected_witness_public_key_sha256,
        authorization_sequence=expected_authorization_sequence,
        previous_authorization_event_sha256=(expected_previous_authorization_event_sha256),
        authorization_challenge=authorization_challenge,
        accepted_at=cast(str, parsed.get("accepted_at")),
    )
    if unsigned != expected:
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BINDING_MISMATCH")
    public_key_bytes, public_key_sha256 = _public_key(
        witness_public_key_bytes,
        expected_sha256=expected_witness_public_key_sha256,
    )
    try:
        verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        verifier.verify(
            bytes.fromhex(signature_hex),
            PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR
            + _canonical_json_bytes(
                unsigned,
                reason="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_JSON_INVALID",
            ),
        )
    except (InvalidSignature, TypeError, ValueError):
        _fail("PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_SIGNATURE_UNVERIFIED")
    envelope = bytes(authorization_envelope)
    return VerifiedProfiledOptimizerExternalCompletionAuthorizationV1(
        witness_id=expected_witness_id,
        namespace=expected_namespace,
        witness_public_key_sha256=public_key_sha256,
        authorization_sequence=expected_authorization_sequence,
        previous_authorization_event_sha256=(expected_previous_authorization_event_sha256),
        accepted_at=cast(str, expected["accepted_at"]),
        authorization_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        manifest_id=authenticated_manifest.manifest_id,
        completion_event_sha256=completion.completion_event_sha256,
        external_monotonic_manifest_head_verified=True,
        full_consumption_external_ack_verified=True,
        profiled_optimizer_admission_authorized=True,
        optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _authorization_envelope=envelope,
        _construction_token=_VERIFIED_AUTHORIZATION_TOKEN,
    )


def _float64_sha256(value: object, *, reason: str) -> str:
    if type(value) not in {int, float}:
        _fail(reason)
    try:
        numeric = float(cast(int | float, value))
        encoded = struct.pack(">d", numeric)
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail(reason)
    if not math.isfinite(numeric):
        _fail(reason)
    return hashlib.sha256(_LABEL_VALUE_DOMAIN + encoded).hexdigest()


def _model_vector_sha256(values: Sequence[float]) -> str:
    if len(values) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_OPTIMIZER_MODEL_INPUT_COUNT_INVALID")
    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_DOMAIN)
    for value in values:
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_OPTIMIZER_MODEL_INPUT_NONFINITE")
        digest.update(struct.pack(">d", value))
    return digest.hexdigest()


def _logical_model_vector_sha256(values: Sequence[float]) -> str:
    """Reproduce the authenticated projection's float32 model-vector hash."""

    if len(values) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_OPTIMIZER_LOGICAL_MODEL_INPUT_COUNT_INVALID")
    digest = hashlib.sha256()
    digest.update(_LOGICAL_MODEL_VECTOR_DOMAIN)
    digest.update(bytes.fromhex(FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256))
    digest.update(struct.pack(">I", LOGICAL_MODEL_FEATURE_COUNT))
    for value in values:
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_OPTIMIZER_LOGICAL_MODEL_INPUT_NONFINITE")
        try:
            encoded = struct.pack(">f", value)
            canonical = struct.unpack(">f", encoded)[0]
        except (OverflowError, struct.error):
            _fail("PROFILED_OPTIMIZER_LOGICAL_MODEL_INPUT_INVALID")
        if canonical != value:
            _fail("PROFILED_OPTIMIZER_LOGICAL_MODEL_INPUT_NOT_FLOAT32_CANONICAL")
        digest.update(encoded)
    return digest.hexdigest()


def _example_fingerprint(candidate: ProfiledTrainingObservationExampleV1) -> str:
    if type(candidate) is not ProfiledTrainingObservationExampleV1:
        _fail("PROFILED_OPTIMIZER_EXAMPLE_EXACT_TYPE_REQUIRED")
    example = candidate.training_example
    tensor = example.tensor
    trust_row = example.trust_row
    if (
        type(example) is not TrainingExample
        or type(tensor) is not FeatureTensorRecord
        or type(trust_row) is not dict
    ):
        _fail("PROFILED_OPTIMIZER_TRUST_ROW_EXACT_DICT_REQUIRED")
    material = {
        "ordinal": candidate.ordinal,
        "sample_identity_sha256": candidate.sample_identity_sha256,
        "label_binding_sha256": candidate.label_binding_sha256,
        "tensor_binding_sha256": candidate.tensor_binding_sha256,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "label_action_index": example.label_action_index,
        "label_expected_move_after_cost_bps_float64_sha256": _float64_sha256(
            example.label_expected_move_after_cost_bps,
            reason="PROFILED_OPTIMIZER_LABEL_VALUE_INVALID",
        ),
        "payload_keys": list(example.payload_keys),
        "row_classification": example.row_classification,
        "trust_row": trust_row,
        "decision_time": example.decision_time,
        "label_available_at": example.label_available_at,
        "label_timing_source": example.label_timing_source,
        "label_timing_valid": example.label_timing_valid,
        "label_timing_error": example.label_timing_error,
        "behavior_action_index": example.behavior_action_index,
        "behavior_action": example.behavior_action,
        "tensor": {
            "tensor_id": tensor.tensor_id,
            "symbol": tensor.symbol,
            "timeframe": tensor.timeframe,
            "feature_snapshot_id": tensor.feature_snapshot_id,
            "values": list(tensor.values),
            "missing_mask": list(tensor.missing_mask),
            "stale_mask": list(tensor.stale_mask),
            "source_availability": list(tensor.source_availability),
            "feature_names": list(tensor.feature_names),
            "source_labels": list(tensor.source_labels),
            "missing_feature_names": list(tensor.missing_feature_names),
            "stale_feature_names": list(tensor.stale_feature_names),
            "data_coverage_percent": tensor.data_coverage_percent,
            "source_availability_vector": list(tensor.source_availability_vector),
            "decision_time": tensor.decision_time,
            "source_lineage_hash": tensor.source_lineage_hash,
            "temporal_rejection_reasons": list(tensor.temporal_rejection_reasons),
            "adapter_model_input_float64_sha256": _model_vector_sha256(tensor.model_vector),
        },
    }
    return hashlib.sha256(
        _canonical_json_bytes(
            material,
            reason="PROFILED_OPTIMIZER_EXAMPLE_FINGERPRINT_INVALID",
        )
    ).hexdigest()


def _direct_decision_feature_clocks(
    *,
    ledger: DurableFeatureSnapshotLedger,
    candidate: ProfiledTrainingObservationExampleV1,
) -> tuple[str, str, str, str, str, str]:
    """Reopen parent projection lineage and return its clocks and hashes."""

    example = candidate.training_example
    if (
        type(example.payload_keys) is not tuple
        or len(example.payload_keys) != 2
        or type(example.payload_keys[0]) is not str
        or not example.payload_keys[0].startswith("profiled_ledger:")
    ):
        _fail("PROFILED_OPTIMIZER_DURABLE_SAMPLE_LOCATOR_INVALID")
    child_id = example.payload_keys[0].removeprefix("profiled_ledger:")
    if not child_id:
        _fail("PROFILED_OPTIMIZER_DURABLE_SAMPLE_LOCATOR_INVALID")
    try:
        child = ledger.get_snapshot(child_id)
    except FeatureSnapshotLedgerError as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            "PROFILED_OPTIMIZER_CHILD_RECORD_REOPEN_FAILED"
        ) from exc
    if child is None or type(child.record) is not dict:
        _fail("PROFILED_OPTIMIZER_CHILD_RECORD_MISSING")
    child_envelope = child.record.get("frozen_envelope")
    if type(child_envelope) is not dict:
        _fail("PROFILED_OPTIMIZER_CHILD_ENVELOPE_INVALID")
    child_lineage = child_envelope.get("source_lineage_material")
    if type(child_lineage) is not dict:
        _fail("PROFILED_OPTIMIZER_CHILD_LINEAGE_INVALID")
    enrichment = child_lineage.get(PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY)
    if type(enrichment) is not dict:
        _fail("PROFILED_OPTIMIZER_CHILD_ENRICHMENT_BINDING_MISSING")
    if (
        enrichment.get("logical_profile_selection_mask_sha256")
        != LOGICAL_PROFILE_SELECTION_MASK_SHA256
        or enrichment.get("projection_schema_version")
        != PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION
        or enrichment.get("projection_implementation_sha256")
        != PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
        or enrichment.get("projection_configuration_sha256")
        != PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
    ):
        _fail("PROFILED_OPTIMIZER_CHILD_PROJECTION_CONTRACT_INVALID")
    parent_binding = enrichment.get("parent_model_record_binding")
    if type(parent_binding) is not dict:
        _fail("PROFILED_OPTIMIZER_PARENT_BINDING_INVALID")
    parent_id = parent_binding.get("durable_snapshot_id")
    if type(parent_id) is not str or not parent_id:
        _fail("PROFILED_OPTIMIZER_PARENT_ID_INVALID")
    try:
        parent = ledger.get_snapshot(parent_id)
    except FeatureSnapshotLedgerError as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            "PROFILED_OPTIMIZER_PARENT_RECORD_REOPEN_FAILED"
        ) from exc
    if parent is None or type(parent.record) is not dict:
        _fail("PROFILED_OPTIMIZER_PARENT_RECORD_MISSING")
    parent_envelope = parent.record.get("frozen_envelope")
    if type(parent_envelope) is not dict:
        _fail("PROFILED_OPTIMIZER_PARENT_ENVELOPE_INVALID")
    if (
        parent.record.get("durable_snapshot_id") != parent_id
        or parent.record.get("record_sha256") != parent_binding.get("record_sha256")
        or parent_envelope.get("feature_snapshot_id") != parent_binding.get("feature_snapshot_id")
        or parent_envelope.get("feature_cutoff") != parent_binding.get("feature_cutoff")
        or parent_envelope.get("tensor_decision_time") != parent_binding.get("decision_time")
        or parent_envelope.get("generated_at") != parent_binding.get("generated_at")
        or parent_envelope.get("tensor_decision_time") != example.decision_time
    ):
        _fail("PROFILED_OPTIMIZER_PARENT_DIRECT_IDENTITY_MISMATCH")
    logical_model_vector_sha256 = parent_binding.get("logical_model_vector_sha256")
    logical_projection_sha256 = parent_binding.get("logical_projection_sha256")
    if (
        parent_binding.get("logical_profile_selection_mask_sha256")
        != LOGICAL_PROFILE_SELECTION_MASK_SHA256
        or not _valid_sha256(logical_model_vector_sha256)
        or not _valid_sha256(logical_projection_sha256)
    ):
        _fail("PROFILED_OPTIMIZER_PARENT_PROJECTION_BINDING_INVALID")
    parent_lineage = parent_envelope.get("source_lineage_material")
    if type(parent_lineage) is not dict:
        _fail("PROFILED_OPTIMIZER_PARENT_LINEAGE_INVALID")
    capture_timestamps = parent_lineage.get("capture_timestamps")
    if type(capture_timestamps) is not dict:
        _fail("PROFILED_OPTIMIZER_PARENT_CAPTURE_TIMESTAMPS_INVALID")
    model_feature_cutoff = parent_envelope.get("feature_cutoff")
    source_feature_available_at = capture_timestamps.get("available_at")
    decision_feature_available_at = parent_lineage.get("transform_available_at")
    feature_generated_at = parent_envelope.get("generated_at")
    model_cutoff = _clock(
        model_feature_cutoff,
        reason="PROFILED_OPTIMIZER_MODEL_FEATURE_CUTOFF_INVALID",
    )
    source_available = _clock(
        source_feature_available_at,
        reason="PROFILED_OPTIMIZER_SOURCE_FEATURE_AVAILABLE_AT_INVALID",
    )
    transform_available = _clock(
        decision_feature_available_at,
        reason="PROFILED_OPTIMIZER_TRANSFORM_AVAILABLE_AT_INVALID",
    )
    feature_generated = _clock(
        feature_generated_at,
        reason="PROFILED_OPTIMIZER_FEATURE_GENERATED_AT_INVALID",
    )
    if not model_cutoff <= source_available <= transform_available <= feature_generated:
        _fail("PROFILED_OPTIMIZER_DECISION_FEATURE_CLOCK_ORDER_INVALID")
    return (
        cast(str, model_feature_cutoff),
        cast(str, source_feature_available_at),
        cast(str, decision_feature_available_at),
        cast(str, feature_generated_at),
        cast(str, logical_model_vector_sha256),
        cast(str, logical_projection_sha256),
    )


def _validate_candidate_semantics(
    candidate: ProfiledTrainingObservationExampleV1,
    *,
    observation_time: str,
) -> tuple[str, str, str, str, str, str, int]:
    example = candidate.training_example
    trust = example.trust_row
    if (
        type(example) is not TrainingExample
        or type(example.tensor) is not FeatureTensorRecord
        or type(trust) is not dict
    ):
        _fail("PROFILED_OPTIMIZER_TRUST_ROW_EXACT_DICT_REQUIRED")
    if (
        trust.get("training_example_adapter_contract_version")
        != PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION
        or trust.get("row_source") != "profiled_training_fixed_observation_manifest_v1"
        or trust.get("learning_mode") != "outcome_supervised"
        or trust.get("future_labels_not_in_feature_tensor") is not True
        or trust.get("candle_closed_confirmed") is not True
        or trust.get("optimizer_admission_authorized") is not False
        or trust.get("checkpoint_write_authorized") is not False
        or trust.get("prediction_authorized") is not False
        or trust.get("paper_trading_authorized") is not False
        or trust.get("live_execution_authorized") is not False
        or trust.get("runtime_wired") is not False
    ):
        _fail("PROFILED_OPTIMIZER_TRUST_ROW_CONTRACT_INVALID")
    if (
        trust.get("profiled_sample_identity_sha256") != candidate.sample_identity_sha256
        or trust.get("profiled_label_binding_sha256") != candidate.label_binding_sha256
        or trust.get("profiled_tensor_binding_sha256") != candidate.tensor_binding_sha256
    ):
        _fail("PROFILED_OPTIMIZER_EXAMPLE_IDENTITY_BINDING_INVALID")
    if (
        example.behavior_action_index is not None
        or example.behavior_action is not None
        or any(
            trust.get(name) not in (None, "")
            for name in (
                "behavior_action_index",
                "behavior_action",
                "behavior_receipt_sha256",
                "behavior_policy_receipt_sha256",
            )
        )
    ):
        _fail("PROFILED_OPTIMIZER_GENUINE_BEHAVIOR_RECEIPT_CONTRACT_UNIMPLEMENTED")
    if example.label_timing_valid is not True or example.label_timing_error is not None:
        _fail("PROFILED_OPTIMIZER_LABEL_TIMING_INVALID")

    record_wide_cutoff_text = cast(str, trust.get("feature_cutoff"))
    training_record_generated_text = cast(str, trust.get("record_generated_at"))
    decision_text = cast(str, trust.get("decision_time"))
    sample_available_text = cast(str, trust.get("trainer_sample_available_at"))
    postcommit_text = cast(str, trust.get("postcommit_readback_at"))
    label_available_text = cast(str, trust.get("label_available_at"))
    record_wide_cutoff = _clock(
        record_wide_cutoff_text,
        reason="PROFILED_OPTIMIZER_RECORD_WIDE_CUTOFF_INVALID",
    )
    training_record_generated = _clock(
        training_record_generated_text,
        reason="PROFILED_OPTIMIZER_TRAINING_RECORD_GENERATED_AT_INVALID",
    )
    decision = _clock(decision_text, reason="PROFILED_OPTIMIZER_DECISION_TIME_INVALID")
    sample_available = _clock(
        sample_available_text,
        reason="PROFILED_OPTIMIZER_TRAINER_SAMPLE_AVAILABLE_AT_INVALID",
    )
    postcommit = _clock(
        postcommit_text,
        reason="PROFILED_OPTIMIZER_POSTCOMMIT_READBACK_AT_INVALID",
    )
    label_available = _clock(
        label_available_text,
        reason="PROFILED_OPTIMIZER_LABEL_AVAILABLE_AT_INVALID",
    )
    observation = _clock(
        observation_time,
        reason="PROFILED_OPTIMIZER_OBSERVATION_TIME_INVALID",
    )
    if (
        trust.get("available_at") != sample_available_text
        or trust.get("available_at_semantics")
        != "TRAINER_SAMPLE_DURABLY_AVAILABLE_AT_LEDGER_POSTCOMMIT_READBACK"
    ):
        _fail("PROFILED_OPTIMIZER_LEGACY_AVAILABLE_AT_SEMANTICS_INVALID")
    if sample_available != postcommit:
        _fail("PROFILED_OPTIMIZER_SAMPLE_POSTCOMMIT_CLOCK_MISMATCH")
    if not record_wide_cutoff <= decision or training_record_generated > decision:
        _fail("PROFILED_OPTIMIZER_TRAINING_RECORD_AFTER_DECISION")
    if not decision < sample_available < observation:
        _fail("PROFILED_OPTIMIZER_SAMPLE_AVAILABILITY_ORDER_INVALID")
    if not decision < label_available < observation:
        _fail("PROFILED_OPTIMIZER_LABEL_AVAILABILITY_ORDER_INVALID")
    if training_record_generated == sample_available:
        _fail("PROFILED_OPTIMIZER_GENERATED_AND_SAMPLE_CLOCK_COLLISION")
    if (
        example.decision_time != decision_text
        or example.tensor.decision_time != decision_text
        or example.label_available_at != label_available_text
    ):
        _fail("PROFILED_OPTIMIZER_EXAMPLE_CLOCK_BINDING_INVALID")
    horizon = trust.get("label_horizon_seconds")
    if type(horizon) is not int or horizon <= 0 or trust.get("outcome_horizon_seconds") != horizon:
        _fail("PROFILED_OPTIMIZER_LABEL_HORIZON_INVALID")
    return (
        record_wide_cutoff_text,
        training_record_generated_text,
        decision_text,
        sample_available_text,
        label_available_text,
        observation_time,
        horizon,
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledOutcomeSupervisedTargetV1:
    schema_version: str
    label_binding_sha256: str
    action_index: int
    target_action: str
    signed_expected_move_after_cost_bps: float
    label_value_float64_sha256: str
    label_available_at: str
    horizon_seconds: int
    target_sha256: str
    canonical_finalized_label_bound: bool
    future_labels_excluded_from_feature_tensor: bool
    static_action_threshold_used: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = {
            "schema_version": self.schema_version,
            "label_binding_sha256": self.label_binding_sha256,
            "action_index": self.action_index,
            "target_action": self.target_action,
            "signed_expected_move_after_cost_bps": (self.signed_expected_move_after_cost_bps),
            "label_value_float64_sha256": self.label_value_float64_sha256,
            "label_available_at": self.label_available_at,
            "horizon_seconds": self.horizon_seconds,
            "canonical_finalized_label_bound": self.canonical_finalized_label_bound,
            "future_labels_excluded_from_feature_tensor": (
                self.future_labels_excluded_from_feature_tensor
            ),
            "static_action_threshold_used": self.static_action_threshold_used,
        }
        if (
            self._construction_token is not _TARGET_TOKEN
            or self.schema_version != AUTHENTICATED_PROFILED_OUTCOME_TARGET_V1_SCHEMA_VERSION
            or not _valid_sha256(self.label_binding_sha256)
            or type(self.action_index) is not int
            or self.action_index not in {0, 1, 2}
            or type(self.target_action) is not str
            or self.target_action != {0: "hold", 1: "long", 2: "short"}[self.action_index]
            or type(self.signed_expected_move_after_cost_bps) is not float
            or not math.isfinite(self.signed_expected_move_after_cost_bps)
            or self.label_value_float64_sha256
            != _float64_sha256(
                self.signed_expected_move_after_cost_bps,
                reason="PROFILED_OPTIMIZER_TARGET_VALUE_INVALID",
            )
            or type(self.horizon_seconds) is not int
            or self.horizon_seconds <= 0
            or self.target_sha256 != stable_sha256(material)
            or self.canonical_finalized_label_bound is not True
            or self.future_labels_excluded_from_feature_tensor is not True
            or self.static_action_threshold_used is not False
        ):
            _fail("PROFILED_OPTIMIZER_OUTCOME_TARGET_INVALID")
        _clock(
            self.label_available_at,
            reason="PROFILED_OPTIMIZER_TARGET_LABEL_AVAILABLE_AT_INVALID",
        )
        _require_factory_seal(
            self._factory_seal,
            domain=_TARGET_FACTORY_SEAL_DOMAIN,
            material=material,
            reason="PROFILED_OPTIMIZER_OUTCOME_TARGET_FACTORY_SEAL_INVALID",
        )


def _outcome_target(
    candidate: ProfiledTrainingObservationExampleV1,
    *,
    label_available_at: str,
    horizon_seconds: int,
) -> AuthenticatedProfiledOutcomeSupervisedTargetV1:
    example = candidate.training_example
    action_index = example.label_action_index
    value = example.label_expected_move_after_cost_bps
    if type(action_index) is not int or action_index not in {0, 1, 2}:
        _fail("PROFILED_OPTIMIZER_LABEL_ACTION_INDEX_INVALID")
    if type(value) is not float or not math.isfinite(value):
        _fail("PROFILED_OPTIMIZER_LABEL_VALUE_INVALID")
    value_sha256 = _float64_sha256(value, reason="PROFILED_OPTIMIZER_LABEL_VALUE_INVALID")
    material = {
        "schema_version": AUTHENTICATED_PROFILED_OUTCOME_TARGET_V1_SCHEMA_VERSION,
        "label_binding_sha256": candidate.label_binding_sha256,
        "action_index": action_index,
        "target_action": {0: "hold", 1: "long", 2: "short"}[action_index],
        "signed_expected_move_after_cost_bps": value,
        "label_value_float64_sha256": value_sha256,
        "label_available_at": label_available_at,
        "horizon_seconds": horizon_seconds,
        "canonical_finalized_label_bound": True,
        "future_labels_excluded_from_feature_tensor": True,
        "static_action_threshold_used": False,
    }
    return AuthenticatedProfiledOutcomeSupervisedTargetV1(
        **material,
        target_sha256=stable_sha256(material),
        _factory_seal=_FactorySeal(
            domain=_TARGET_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_TARGET_TOKEN,
    )


def _admission_factory_seal_value(value: object) -> object:
    if type(value) is AuthenticatedProfiledOutcomeSupervisedTargetV1:
        return {
            "target_sha256": cast(
                AuthenticatedProfiledOutcomeSupervisedTargetV1,
                value,
            ).target_sha256
        }
    if type(value) is tuple:
        return [_admission_factory_seal_value(item) for item in cast(tuple[object, ...], value)]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _fail("PROFILED_OPTIMIZER_ADMISSION_FACTORY_SEAL_MATERIAL_INVALID")


def _admission_factory_seal_material(
    admission: AuthenticatedProfiledOptimizerAdmissionV1,
) -> dict[str, object]:
    return {
        item.name: _admission_factory_seal_value(getattr(admission, item.name))
        for item in dataclass_fields(admission)
        if not item.name.startswith("_")
    }


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledOptimizerAdmissionV1:
    schema_version: str
    manifest_id: str
    manifest_metadata_sha256: str
    manifest_observation_context_sha256: str
    manifest_entry_chain_head_sha256: str
    manifest_ordered_entry_identities_sha256: str
    manifest_total_profiled_samples: int
    manifest_admitted_example_count: int
    manifest_label_unavailable_count: int
    completion_event_sha256: str
    completion_ordered_page_root_sha256: str
    completion_page_count: int
    completion_consumed_entry_count: int
    completion_admitted_entry_count: int
    completion_label_unavailable_count: int
    external_authorization_envelope_sha256: str
    witness_id: str
    witness_namespace: str
    witness_public_key_sha256: str
    witness_sequence: int
    witness_previous_event_sha256: str
    witness_accepted_at: str
    ordinal: int
    symbol: str
    timeframe: str
    sample_identity_sha256: str
    label_binding_sha256: str
    tensor_binding_sha256: str
    feature_registry_sha256: str
    feature_registry_abi_sha256: str
    logical_profile_selection_mask: tuple[int, ...] = field(repr=False)
    logical_profile_selection_mask_sha256: str
    projection_schema_version: str
    projection_implementation_sha256: str
    projection_configuration_sha256: str
    logical_model_vector_sha256: str
    logical_projection_sha256: str
    model_feature_cutoff: str
    record_wide_evidence_cutoff: str
    source_feature_available_at: str
    decision_feature_available_at: str
    feature_generated_at: str
    training_record_generated_at: str
    decision_time: str
    trainer_sample_available_at: str
    label_available_at: str
    observation_time: str
    model_input: tuple[float, ...] = field(repr=False)
    model_input_float64_sha256: str
    supervised_target: AuthenticatedProfiledOutcomeSupervisedTargetV1
    profiled_optimizer_admission_validated: bool
    outcome_supervised_objective_eligible: bool
    behavior_receipt_bound: bool
    ppo_behavior_policy_terms_enabled: bool
    optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.supervised_target) is not AuthenticatedProfiledOutcomeSupervisedTargetV1:
            _fail("PROFILED_OPTIMIZER_ADMISSION_TARGET_EXACT_TYPE_REQUIRED")
        self.supervised_target.__post_init__()
        if (
            self._construction_token is not _ADMISSION_TOKEN
            or self.schema_version != AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION
            or not all(
                _valid_sha256(value)
                for value in (
                    self.manifest_id,
                    self.manifest_metadata_sha256,
                    self.manifest_observation_context_sha256,
                    self.manifest_entry_chain_head_sha256,
                    self.manifest_ordered_entry_identities_sha256,
                    self.completion_event_sha256,
                    self.completion_ordered_page_root_sha256,
                    self.external_authorization_envelope_sha256,
                    self.witness_public_key_sha256,
                    self.witness_previous_event_sha256,
                    self.sample_identity_sha256,
                    self.label_binding_sha256,
                    self.tensor_binding_sha256,
                    self.feature_registry_sha256,
                    self.feature_registry_abi_sha256,
                    self.logical_profile_selection_mask_sha256,
                    self.projection_implementation_sha256,
                    self.projection_configuration_sha256,
                    self.logical_model_vector_sha256,
                    self.logical_projection_sha256,
                    self.model_input_float64_sha256,
                )
            )
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.manifest_total_profiled_samples,
                    self.manifest_admitted_example_count,
                    self.manifest_label_unavailable_count,
                    self.completion_page_count,
                    self.completion_consumed_entry_count,
                    self.completion_admitted_entry_count,
                    self.completion_label_unavailable_count,
                )
            )
            or self.manifest_total_profiled_samples
            != self.manifest_admitted_example_count + self.manifest_label_unavailable_count
            or self.manifest_admitted_example_count <= 0
            or self.completion_page_count <= 0
            or self.completion_consumed_entry_count != self.manifest_total_profiled_samples
            or self.completion_admitted_entry_count != self.manifest_admitted_example_count
            or self.completion_label_unavailable_count != self.manifest_label_unavailable_count
            or type(self.ordinal) is not int
            or self.ordinal <= 0
            or self.ordinal > self.manifest_total_profiled_samples
            or type(self.symbol) is not str
            or not self.symbol
            or type(self.timeframe) is not str
            or not self.timeframe
            or type(self.witness_sequence) is not int
            or self.witness_sequence <= 0
            or type(self.witness_id) is not str
            or type(self.witness_namespace) is not str
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or _IDENTIFIER_RE.fullmatch(self.witness_namespace) is None
            or type(self.logical_profile_selection_mask) is not tuple
            or self.logical_profile_selection_mask != LOGICAL_PROFILE_SELECTION_MASK
            or self.logical_profile_selection_mask_sha256 != LOGICAL_PROFILE_SELECTION_MASK_SHA256
            or stable_sha256(list(self.logical_profile_selection_mask))
            != self.logical_profile_selection_mask_sha256
            or self.projection_schema_version != PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION
            or self.projection_implementation_sha256
            != PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
            or self.projection_configuration_sha256
            != PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
            or self.feature_registry_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256
            or self.feature_registry_abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
            or type(self.model_input) is not tuple
            or self.model_input_float64_sha256 != _model_vector_sha256(self.model_input)
            or self.logical_model_vector_sha256 != _logical_model_vector_sha256(self.model_input)
            or self.supervised_target.label_binding_sha256 != self.label_binding_sha256
            or self.supervised_target.label_available_at != self.label_available_at
            or self.profiled_optimizer_admission_validated is not True
            or self.outcome_supervised_objective_eligible is not True
            or self.behavior_receipt_bound is not False
            or self.ppo_behavior_policy_terms_enabled is not False
            or any(
                value is not False
                for value in (
                    self.optimizer_execution_authorized,
                    self.checkpoint_write_authorized,
                    self.model_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.order_submission_authorized,
                    self.execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_OPTIMIZER_ADMISSION_RESULT_INVALID")
        witness_accepted = _clock(
            self.witness_accepted_at,
            reason="PROFILED_OPTIMIZER_RESULT_WITNESS_ACCEPTED_AT_INVALID",
        )
        model_cutoff = _clock(
            self.model_feature_cutoff,
            reason="PROFILED_OPTIMIZER_RESULT_MODEL_FEATURE_CUTOFF_INVALID",
        )
        record_wide_cutoff = _clock(
            self.record_wide_evidence_cutoff,
            reason="PROFILED_OPTIMIZER_RESULT_RECORD_WIDE_CUTOFF_INVALID",
        )
        source_available = _clock(
            self.source_feature_available_at,
            reason="PROFILED_OPTIMIZER_RESULT_SOURCE_AVAILABLE_AT_INVALID",
        )
        transform_available = _clock(
            self.decision_feature_available_at,
            reason="PROFILED_OPTIMIZER_RESULT_TRANSFORM_AVAILABLE_AT_INVALID",
        )
        feature_generated = _clock(
            self.feature_generated_at,
            reason="PROFILED_OPTIMIZER_RESULT_FEATURE_GENERATED_AT_INVALID",
        )
        training_generated = _clock(
            self.training_record_generated_at,
            reason="PROFILED_OPTIMIZER_RESULT_TRAINING_GENERATED_AT_INVALID",
        )
        decision = _clock(
            self.decision_time,
            reason="PROFILED_OPTIMIZER_RESULT_DECISION_TIME_INVALID",
        )
        sample_available = _clock(
            self.trainer_sample_available_at,
            reason="PROFILED_OPTIMIZER_RESULT_SAMPLE_AVAILABLE_AT_INVALID",
        )
        label_available = _clock(
            self.label_available_at,
            reason="PROFILED_OPTIMIZER_RESULT_LABEL_AVAILABLE_AT_INVALID",
        )
        observation = _clock(
            self.observation_time,
            reason="PROFILED_OPTIMIZER_RESULT_OBSERVATION_TIME_INVALID",
        )
        if not (
            model_cutoff <= source_available <= transform_available <= feature_generated
            and model_cutoff <= record_wide_cutoff <= decision
            and feature_generated <= training_generated <= decision < sample_available
            and decision < label_available < observation
            and sample_available < observation
            and observation < witness_accepted
        ):
            _fail("PROFILED_OPTIMIZER_ADMISSION_RESULT_CLOCK_ORDER_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_ADMISSION_FACTORY_SEAL_DOMAIN,
            material=_admission_factory_seal_material(self),
            reason="PROFILED_OPTIMIZER_ADMISSION_FACTORY_SEAL_INVALID",
        )


def admit_authenticated_profiled_optimizer_candidate_v1(
    *,
    candidate: ProfiledTrainingObservationExampleV1,
    manifest_path: Path,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    expected_manifest_id: str,
    expected_observation_time: str,
    local_completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    completion_staging_store: ImmutableSourcePayloadStore,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
    external_authorization_envelope: bytes,
    expected_witness_id: str,
    expected_witness_namespace: str,
    witness_public_key_bytes: bytes,
    expected_witness_public_key_sha256: str,
    expected_witness_sequence: int,
    expected_previous_witness_event_sha256: str,
    authorization_challenge: bytes | bytearray | memoryview,
) -> AuthenticatedProfiledOptimizerAdmissionV1:
    """Reauthenticate and admit one externally witnessed supervised candidate.

    The return value is data-only and cannot run an optimizer or write any
    model/checkpoint/runtime state.
    """

    if type(candidate) is not ProfiledTrainingObservationExampleV1:
        _fail("PROFILED_OPTIMIZER_EXAMPLE_EXACT_TYPE_REQUIRED")
    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_OPTIMIZER_LEDGER_EXACT_TYPE_REQUIRED")
    if type(completion_staging_store) is not ImmutableSourcePayloadStore:
        _fail("PROFILED_OPTIMIZER_COMPLETION_STORE_EXACT_TYPE_REQUIRED")
    if type(local_completion) is not LocalProfiledTrainingObservationCompletionCandidateV1:
        _fail("PROFILED_OPTIMIZER_LOCAL_COMPLETION_EXACT_TYPE_REQUIRED")
    challenge = _challenge(authorization_challenge)

    # Reject semantic clock/behavior collisions in the supplied object before
    # comparing it to the independently reopened manifest entry.
    supplied_clocks = _validate_candidate_semantics(
        candidate,
        observation_time=expected_observation_time,
    )
    supplied_fingerprint = _example_fingerprint(candidate)

    try:
        manifest_before = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=manifest_path,
            hmac_key=manifest_hmac_key,
            expected_auth_key_id=manifest_auth_key_id,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
        )
        completion = read_local_profiled_training_observation_completion_candidate_v1(
            staging_store=completion_staging_store,
            completion_event_sha256=local_completion.completion_event_sha256,
            completion_event_byte_count=local_completion.completion_event_byte_count,
            epoch_hmac_key=epoch_hmac_key,
            epoch_auth_key_id=epoch_auth_key_id,
        )
    except (
        ProfiledTrainingObservationManifestV1Error,
        ProfiledTrainingObservationManifestHeadV1Error,
    ) as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            f"PROFILED_OPTIMIZER_UPSTREAM_AUTHENTICATION_FAILED:{type(exc).__name__}"
        ) from exc
    if (
        completion.manifest_id != manifest_before.manifest_id
        or completion.consumed_entry_count != manifest_before.total_profiled_samples
        or completion.admitted_entry_count != manifest_before.admitted_example_count
        or completion.label_unavailable_count != manifest_before.label_unavailable_count
        or completion.terminal_entry_chain_sha256 != manifest_before.entry_chain_head_sha256
        or completion.page_count <= 0
        or completion.admitted_entry_count <= 0
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_MANIFEST_BINDING_INVALID")
    final_page_sha = completion._material.get("final_page_receipt_event_sha256")
    if not _valid_sha256(final_page_sha):
        _fail("PROFILED_OPTIMIZER_FINAL_PAGE_RECEIPT_ADDRESS_INVALID")
    try:
        final_page_bytes = completion_staging_store.get(cast(str, final_page_sha))
        final_page = read_local_profiled_training_observation_page_receipt_v1(
            staging_store=completion_staging_store,
            page_receipt_event_sha256=cast(str, final_page_sha),
            page_receipt_event_byte_count=len(final_page_bytes),
            epoch_hmac_key=epoch_hmac_key,
            epoch_auth_key_id=epoch_auth_key_id,
        )
    except (SourcePayloadStoreError, ProfiledTrainingObservationManifestHeadV1Error) as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            f"PROFILED_OPTIMIZER_FINAL_PAGE_REOPEN_FAILED:{type(exc).__name__}"
        ) from exc
    _completion_binding(completion, final_page)

    verified_external = _verify_external_authorization(
        authorization_envelope=external_authorization_envelope,
        authenticated_manifest=manifest_before,
        completion=completion,
        final_page=final_page,
        expected_witness_id=expected_witness_id,
        expected_namespace=expected_witness_namespace,
        witness_public_key_bytes=witness_public_key_bytes,
        expected_witness_public_key_sha256=expected_witness_public_key_sha256,
        expected_authorization_sequence=expected_witness_sequence,
        expected_previous_authorization_event_sha256=(expected_previous_witness_event_sha256),
        authorization_challenge=challenge,
    )

    try:
        reopened_page = read_profiled_training_observation_page_v1(
            manifest_path=manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
            hmac_key=manifest_hmac_key,
            expected_auth_key_id=manifest_auth_key_id,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
            after_ordinal=candidate.ordinal - 1,
            limit=1,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            f"PROFILED_OPTIMIZER_SAMPLE_REOPEN_FAILED:{type(exc).__name__}"
        ) from exc
    if (
        reopened_page.scanned_entry_count != 1
        or reopened_page.label_unavailable_scanned != 0
        or len(reopened_page.examples) != 1
        or reopened_page.examples[0].ordinal != candidate.ordinal
    ):
        _fail("PROFILED_OPTIMIZER_SAMPLE_ORDINAL_NOT_ADMITTED")
    reopened = reopened_page.examples[0]
    reopened_clocks = _validate_candidate_semantics(
        reopened,
        observation_time=manifest_before.observation_time,
    )
    if supplied_clocks != reopened_clocks:
        _fail("PROFILED_OPTIMIZER_CANDIDATE_CLOCK_BINDING_MISMATCH")
    if (
        candidate.sample_identity_sha256 != reopened.sample_identity_sha256
        or candidate.label_binding_sha256 != reopened.label_binding_sha256
        or candidate.tensor_binding_sha256 != reopened.tensor_binding_sha256
        or supplied_fingerprint != _example_fingerprint(reopened)
    ):
        _fail("PROFILED_OPTIMIZER_CANDIDATE_DIRECT_IDENTITY_MISMATCH")
    (
        model_feature_cutoff,
        source_feature_available_at,
        decision_feature_available_at,
        feature_generated_at,
        logical_model_vector_sha256,
        logical_projection_sha256,
    ) = _direct_decision_feature_clocks(
        ledger=ledger,
        candidate=reopened,
    )

    try:
        manifest_after = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=manifest_path,
            hmac_key=manifest_hmac_key,
            expected_auth_key_id=manifest_auth_key_id,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise AuthenticatedProfiledOptimizerAdmissionV1Error(
            f"PROFILED_OPTIMIZER_MANIFEST_REAUTHENTICATION_FAILED:{type(exc).__name__}"
        ) from exc
    if _manifest_binding(manifest_before) != _manifest_binding(manifest_after):
        _fail("PROFILED_OPTIMIZER_MANIFEST_MOVED_DURING_ADMISSION")

    (
        record_wide_evidence_cutoff,
        training_record_generated_at,
        decision_time,
        trainer_sample_available_at,
        label_available_at,
        observation_time,
        horizon_seconds,
    ) = reopened_clocks
    if not (
        _clock(
            feature_generated_at,
            reason="PROFILED_OPTIMIZER_FEATURE_GENERATED_AT_INVALID",
        )
        <= _clock(
            training_record_generated_at,
            reason="PROFILED_OPTIMIZER_TRAINING_RECORD_GENERATED_AT_INVALID",
        )
        <= _clock(decision_time, reason="PROFILED_OPTIMIZER_DECISION_TIME_INVALID")
        and _clock(
            model_feature_cutoff,
            reason="PROFILED_OPTIMIZER_MODEL_FEATURE_CUTOFF_INVALID",
        )
        <= _clock(
            record_wide_evidence_cutoff,
            reason="PROFILED_OPTIMIZER_RECORD_WIDE_CUTOFF_INVALID",
        )
    ):
        _fail("PROFILED_OPTIMIZER_MODEL_AND_TRAINING_CLOCK_ORDER_INVALID")
    target = _outcome_target(
        reopened,
        label_available_at=label_available_at,
        horizon_seconds=horizon_seconds,
    )
    model_input = tuple(reopened.training_example.tensor.model_vector)
    if logical_model_vector_sha256 != _logical_model_vector_sha256(model_input):
        _fail("PROFILED_OPTIMIZER_LOGICAL_MODEL_VECTOR_DIRECT_BINDING_MISMATCH")
    return AuthenticatedProfiledOptimizerAdmissionV1(
        schema_version=AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION,
        manifest_id=manifest_before.manifest_id,
        manifest_metadata_sha256=manifest_before.metadata_sha256,
        manifest_observation_context_sha256=manifest_before.observation_context_sha256,
        manifest_entry_chain_head_sha256=manifest_before.entry_chain_head_sha256,
        manifest_ordered_entry_identities_sha256=(manifest_before.ordered_entry_identities_sha256),
        manifest_total_profiled_samples=manifest_before.total_profiled_samples,
        manifest_admitted_example_count=manifest_before.admitted_example_count,
        manifest_label_unavailable_count=manifest_before.label_unavailable_count,
        completion_event_sha256=completion.completion_event_sha256,
        completion_ordered_page_root_sha256=completion.ordered_page_root_sha256,
        completion_page_count=completion.page_count,
        completion_consumed_entry_count=completion.consumed_entry_count,
        completion_admitted_entry_count=completion.admitted_entry_count,
        completion_label_unavailable_count=completion.label_unavailable_count,
        external_authorization_envelope_sha256=(verified_external.authorization_envelope_sha256),
        witness_id=verified_external.witness_id,
        witness_namespace=verified_external.namespace,
        witness_public_key_sha256=verified_external.witness_public_key_sha256,
        witness_sequence=verified_external.authorization_sequence,
        witness_previous_event_sha256=(verified_external.previous_authorization_event_sha256),
        witness_accepted_at=verified_external.accepted_at,
        ordinal=reopened.ordinal,
        symbol=reopened.training_example.symbol,
        timeframe=reopened.training_example.timeframe,
        sample_identity_sha256=reopened.sample_identity_sha256,
        label_binding_sha256=reopened.label_binding_sha256,
        tensor_binding_sha256=reopened.tensor_binding_sha256,
        feature_registry_sha256=FEATURE_SOURCE_REGISTRY_V4_SHA256,
        feature_registry_abi_sha256=FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        logical_profile_selection_mask=LOGICAL_PROFILE_SELECTION_MASK,
        logical_profile_selection_mask_sha256=LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        projection_schema_version=PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
        projection_implementation_sha256=(PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256),
        projection_configuration_sha256=(PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256),
        logical_model_vector_sha256=logical_model_vector_sha256,
        logical_projection_sha256=logical_projection_sha256,
        model_feature_cutoff=model_feature_cutoff,
        record_wide_evidence_cutoff=record_wide_evidence_cutoff,
        source_feature_available_at=source_feature_available_at,
        decision_feature_available_at=decision_feature_available_at,
        feature_generated_at=feature_generated_at,
        training_record_generated_at=training_record_generated_at,
        decision_time=decision_time,
        trainer_sample_available_at=trainer_sample_available_at,
        label_available_at=label_available_at,
        observation_time=observation_time,
        model_input=model_input,
        model_input_float64_sha256=_model_vector_sha256(model_input),
        supervised_target=target,
        profiled_optimizer_admission_validated=True,
        outcome_supervised_objective_eligible=True,
        behavior_receipt_bound=False,
        ppo_behavior_policy_terms_enabled=False,
        optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _factory_seal=_FactorySeal(
            domain=_ADMISSION_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_ADMISSION_TOKEN,
    )


__all__ = (
    "AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_OUTCOME_TARGET_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_ALGORITHM",
    "PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN",
    "PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR",
    "PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_OBJECTIVE_LANE",
    "AuthenticatedProfiledOptimizerAdmissionV1",
    "AuthenticatedProfiledOptimizerAdmissionV1Error",
    "AuthenticatedProfiledOutcomeSupervisedTargetV1",
    "VerifiedProfiledOptimizerExternalCompletionAuthorizationV1",
    "admit_authenticated_profiled_optimizer_candidate_v1",
    "profiled_optimizer_external_completion_signing_payload_v1",
)
