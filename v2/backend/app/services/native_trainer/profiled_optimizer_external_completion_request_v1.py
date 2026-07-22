"""Purpose-specific external completion-authorization wire contract.

The profiled head witness proves an append-only manifest history, but it does
not authorize optimizer admission.  This module freezes the distinct request
that asks the independent witness to acknowledge one exact locally consumed
manifest.  The request binds:

* one already durably anchored manifest-head event;
* the exact authenticated manifest/full-consumption bindings used by the
  optimizer admission verifier;
* the exact local final-page and completion event bytes;
* one 256-bit caller challenge; and
* a caller-pinned authorization-chain sequence and predecessor.

The prepared object contains exact canonical replay bytes and an idempotency
key.  It performs no network I/O and grants no optimizer, checkpoint, model,
prediction, paper, live, order, execution, or runtime authority.  A separate
append-only journal must persist the prepared object before a later transport
may dispatch it.  The response verifier accepts only the purpose-specific
Ed25519 envelope already consumed by
``authenticated_profiled_optimizer_admission_v1``; it has no signing helper or
private-key input.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    PROFILED_OPTIMIZER_ADMISSION_SCOPE,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_ALGORITHM,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION,
    profiled_optimizer_external_completion_claim_template_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeResultV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    LocalProfiledTrainingObservationCompletionCandidateV1,
    LocalProfiledTrainingObservationPageReceiptV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    AuthenticatedProfiledTrainingObservationManifestV1,
)

PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_external_completion_authorization_request_v1"
)
PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN: Final = (
    "v2/native-trainer/profiled-optimizer-external-completion-authorization-request/v1"
)
PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_external_completion_authorization_prepared_request_v1"
)
PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_external_completion_manifest_head_binding_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256: Final = hashlib.sha256(
    b"v2/native-trainer/profiled-optimizer-external-completion-authorization-genesis/v1"
).hexdigest()

# Cryptographic and parser limits only.  These do not select markets, samples,
# labels, regimes, leverage, margin, risk, or optimizer parameters.
PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES: Final = 32
MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES: Final = 512 * 1024
MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES: Final = 128 * 1024
MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_DEPTH: Final = 16
MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_NODES: Final = 32_768
MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES: Final = 256 * 1024
ED25519_PUBLIC_KEY_BYTES: Final = 32

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_PREPARED_TOKEN = object()
_VERIFIED_TOKEN = object()

_DOWNSTREAM_AUTHORITY_FIELDS: Final = (
    "optimizer_execution_authorized",
    "checkpoint_write_authorized",
    "model_write_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)
_REQUEST_AUTHORITY_FIELDS: Final = (
    "external_monotonic_manifest_head_verified",
    "full_consumption_external_ack_verified",
    "profiled_optimizer_admission_authorized",
    *_DOWNSTREAM_AUTHORITY_FIELDS,
)
_LOCAL_EVENT_AUTHORITY_FIELDS: Final = (
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
)
_REQUEST_FIELDS: Final = {
    "schema_version",
    "request_domain",
    "witness_id",
    "witness_public_key_sha256",
    "authorization_namespace",
    "expected_authorization_sequence",
    "expected_previous_authorization_event_sha256",
    "manifest_head_binding",
    "authorization_challenge_sha256",
    "authorization_challenge_byte_count",
    "authorization_challenge_base64",
    "authorization_claim_template_sha256",
    "authorization_claim_template_byte_count",
    "authorization_claim_template_base64",
    "completion_event_sha256",
    "completion_event_byte_count",
    "completion_event_base64",
    "final_page_receipt_event_sha256",
    "final_page_receipt_event_byte_count",
    "final_page_receipt_event_base64",
    "authorization_scope",
    "outcome_supervised_objective_only",
    "behavior_policy_terms_authorized",
    "full_consumption_locally_verified",
    "idempotency_key",
    *_REQUEST_AUTHORITY_FIELDS,
}
_HEAD_BINDING_FIELDS: Final = {
    "schema_version",
    "witness_id",
    "witness_public_key_sha256",
    "namespace",
    "sequence",
    "event_sha256",
    "operation_id",
    "signed_head_durably_anchored",
}
_MANIFEST_BINDING_FIELDS: Final = {
    "schema_version",
    "manifest_id",
    "metadata_sha256",
    "metadata_auth_tag",
    "auth_key_id",
    "observation_time",
    "observation_context_sha256",
    "feature_ledger_high_water_sha256",
    "feature_ledger_archive_chain_sha256",
    "feature_ledger_ordered_receipts_sha256",
    "label_archive_high_water_sha256",
    "label_archive_archive_chain_sha256",
    "label_archive_ordered_receipts_sha256",
    "entry_chain_head_sha256",
    "ordered_entry_identities_sha256",
    "total_profiled_samples",
    "admitted_example_count",
    "label_unavailable_count",
    "ledger_exclusion_count",
    "ledger_exclusion_inventory_sha256",
}
_COMPLETION_BINDING_FIELDS: Final = {
    "schema_version",
    "completion_event_sha256",
    "completion_event_byte_count",
    "completion_id",
    "epoch_id",
    "consumer_lane",
    "head_candidate_event_sha256",
    "head_revision",
    "manifest_id",
    "page_count",
    "consumed_entry_count",
    "admitted_entry_count",
    "label_unavailable_count",
    "terminal_entry_chain_sha256",
    "final_page_receipt_event_sha256",
    "final_page_transition_sha256",
    "ordered_page_root_sha256",
    "final_page_verified_at",
    "full_consumption_locally_verified",
}
_AUTHORIZATION_FIELDS: Final = {
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
    *_DOWNSTREAM_AUTHORITY_FIELDS,
    "signature_hex",
}
_CLAIM_TEMPLATE_FIELDS: Final = _AUTHORIZATION_FIELDS - {"accepted_at", "signature_hex"}


class ProfiledOptimizerExternalCompletionRequestV1Error(RuntimeError):
    """The purpose-specific request or signed response failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledOptimizerExternalCompletionRequestV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _valid_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER_RE.fullmatch(value) is not None


def _identifier(value: object, *, reason: str) -> str:
    if not _valid_identifier(value):
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
    canonical = parsed.astimezone(UTC)
    if canonical.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return canonical


def _bounded_json_tree(value: object, *, reason: str) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    text_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if (
            nodes > MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_NODES
            or depth > MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_DEPTH
        ):
            _fail(reason)
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            for key, child in mapping.items():
                if type(key) is not str or not key or not key.isascii():
                    _fail(reason)
                text_bytes += len(key.encode("ascii"))
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast(list[object], item))
        elif type(item) is str:
            if not item.isascii():
                _fail(reason)
            text_bytes += len(item.encode("ascii"))
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if not -(2**63) <= item <= 2**63 - 1:
                _fail(reason)
        else:
            _fail(reason)
        if text_bytes > MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES:
            _fail(reason)


def _preflight_json(payload: bytes, *, reason: str) -> None:
    depth = 0
    nodes = 1
    in_string = False
    escaped = False
    for byte in payload:
        if byte > 0x7F:
            _fail(reason)
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
        elif byte in {0x7B, 0x5B}:
            depth += 1
            nodes += 1
            if depth > MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_DEPTH:
                _fail(reason)
        elif byte in {0x7D, 0x5D}:
            depth -= 1
            if depth < 0:
                _fail(reason)
        elif byte in {0x2C, 0x3A}:
            nodes += 1
        if nodes > MAX_PROFILED_OPTIMIZER_COMPLETION_JSON_NODES:
            _fail(reason)
    if in_string or escaped or depth != 0:
        _fail(reason)


def _canonical_json_bytes(
    value: object,
    *,
    reason: str,
    maximum_bytes: int = MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES,
) -> bytes:
    _bounded_json_tree(value, reason=reason)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledOptimizerExternalCompletionRequestV1Error(reason) from exc
    if not encoded or len(encoded) > maximum_bytes:
        _fail(reason)
    _preflight_json(encoded, reason=reason)
    return encoded


def _parse_exact_json(
    value: object,
    *,
    reason: str,
    maximum_bytes: int = MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES,
) -> dict[str, Any]:
    if type(value) is not bytes or not value or len(value) > maximum_bytes:
        _fail(reason)
    raw = bytes(value)
    _preflight_json(raw, reason=reason)

    def reject_constant(_value: str) -> NoReturn:
        _fail(reason)

    def reject_float(_value: str) -> NoReturn:
        _fail(reason)

    def parse_integer(value_text: str) -> int:
        digits = value_text[1:] if value_text.startswith("-") else value_text
        if not digits or len(digits) > 19:
            _fail(reason)
        try:
            result = int(value_text)
        except ValueError:
            _fail(reason)
        if not -(2**63) <= result <= 2**63 - 1:
            _fail(reason)
        return result

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if type(key) is not str or key in result:
                _fail(reason)
            result[key] = item
        return result

    try:
        parsed = json.loads(
            raw.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
            parse_float=reject_float,
            parse_int=parse_integer,
        )
    except ProfiledOptimizerExternalCompletionRequestV1Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledOptimizerExternalCompletionRequestV1Error(reason) from exc
    if type(parsed) is not dict:
        _fail(reason)
    material = cast(dict[str, Any], parsed)
    if not hmac.compare_digest(
        _canonical_json_bytes(material, reason=reason, maximum_bytes=maximum_bytes),
        raw,
    ):
        _fail(reason)
    return material


def _decode_base64(
    value: object,
    *,
    expected_count: object,
    maximum_bytes: int,
    reason: str,
) -> bytes:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or type(expected_count) is not int
        or expected_count <= 0
        or expected_count > maximum_bytes
    ):
        _fail(reason)
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (TypeError, ValueError):
        _fail(reason)
    if (
        len(decoded) != expected_count
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        _fail(reason)
    return decoded


def _claim_template_material(template_bytes: bytes) -> dict[str, Any]:
    material = _parse_exact_json(
        template_bytes,
        reason="PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_INVALID",
        maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
    )
    if set(material) != _CLAIM_TEMPLATE_FIELDS:
        _fail("PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_FIELD_SET_INVALID")
    manifest = material.get("manifest_binding")
    completion = material.get("full_consumption_binding")
    if (
        material.get("schema_version")
        != PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION
        or material.get("signature_algorithm")
        != PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_ALGORITHM
        or material.get("signature_domain")
        != PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_DOMAIN
        or not _valid_identifier(material.get("witness_id"))
        or not _valid_identifier(material.get("namespace"))
        or not _valid_sha256(material.get("declared_witness_public_key_sha256"))
        or type(material.get("authorization_sequence")) is not int
        or not 1 <= cast(int, material["authorization_sequence"]) <= 2**63 - 1
        or not _valid_sha256(material.get("previous_authorization_event_sha256"))
        or not _valid_sha256(material.get("authorization_challenge_sha256"))
        or material.get("authorization_challenge_byte_count")
        != PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES
        or material.get("authorization_scope") != PROFILED_OPTIMIZER_ADMISSION_SCOPE
        or material.get("outcome_supervised_objective_only") is not True
        or material.get("behavior_policy_terms_authorized") is not False
        or material.get("external_monotonic_manifest_head_verified") is not True
        or material.get("full_consumption_external_ack_verified") is not True
        or material.get("profiled_optimizer_admission_authorized") is not True
        or any(material.get(name) is not False for name in _DOWNSTREAM_AUTHORITY_FIELDS)
        or type(manifest) is not dict
        or set(manifest) != _MANIFEST_BINDING_FIELDS
        or type(completion) is not dict
        or set(completion) != _COMPLETION_BINDING_FIELDS
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_CONTRACT_INVALID")
    manifest_map = cast(dict[str, Any], manifest)
    completion_map = cast(dict[str, Any], completion)
    manifest_hash_fields = _MANIFEST_BINDING_FIELDS - {
        "schema_version",
        "auth_key_id",
        "observation_time",
        "total_profiled_samples",
        "admitted_example_count",
        "label_unavailable_count",
        "ledger_exclusion_count",
    }
    manifest_counts = tuple(
        manifest_map.get(name)
        for name in (
            "total_profiled_samples",
            "admitted_example_count",
            "label_unavailable_count",
            "ledger_exclusion_count",
        )
    )
    if (
        manifest_map.get("schema_version") != "profiled_optimizer_manifest_binding_v1"
        or any(not _valid_sha256(manifest_map.get(name)) for name in manifest_hash_fields)
        or not _valid_identifier(manifest_map.get("auth_key_id"))
        or any(type(value) is not int or value < 0 for value in manifest_counts)
        or manifest_counts[0] != manifest_counts[1] + manifest_counts[2]
        or manifest_counts[1] <= 0
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_MANIFEST_BINDING_INVALID")
    _clock(
        manifest_map.get("observation_time"),
        reason="PROFILED_OPTIMIZER_COMPLETION_MANIFEST_CLOCK_INVALID",
    )
    completion_hash_fields = {
        "completion_event_sha256",
        "completion_id",
        "epoch_id",
        "head_candidate_event_sha256",
        "manifest_id",
        "terminal_entry_chain_sha256",
        "final_page_receipt_event_sha256",
        "final_page_transition_sha256",
        "ordered_page_root_sha256",
    }
    completion_counts = tuple(
        completion_map.get(name)
        for name in (
            "completion_event_byte_count",
            "head_revision",
            "page_count",
            "consumed_entry_count",
            "admitted_entry_count",
            "label_unavailable_count",
        )
    )
    if (
        completion_map.get("schema_version")
        != "profiled_optimizer_full_consumption_binding_v1"
        or any(not _valid_sha256(completion_map.get(name)) for name in completion_hash_fields)
        or not _valid_identifier(completion_map.get("consumer_lane"))
        or any(type(value) is not int or value < 0 for value in completion_counts)
        or completion_counts[0] <= 0
        or completion_counts[1] <= 0
        or completion_counts[2] <= 0
        or completion_counts[4] <= 0
        or completion_counts[3] != completion_counts[4] + completion_counts[5]
        or completion_map.get("full_consumption_locally_verified") is not True
        or completion_map.get("manifest_id") != manifest_map.get("manifest_id")
        or completion_counts[3] != manifest_counts[0]
        or completion_counts[4] != manifest_counts[1]
        or completion_counts[5] != manifest_counts[2]
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_FULL_CONSUMPTION_BINDING_INVALID")
    _clock(
        completion_map.get("final_page_verified_at"),
        reason="PROFILED_OPTIMIZER_COMPLETION_FINAL_PAGE_CLOCK_INVALID",
    )
    return material


def _head_binding(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _HEAD_BINDING_FIELDS:
        _fail("PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_INVALID")
    material = cast(dict[str, Any], value)
    if (
        material.get("schema_version")
        != PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_V1_SCHEMA_VERSION
        or not _valid_identifier(material.get("witness_id"))
        or not _valid_sha256(material.get("witness_public_key_sha256"))
        or not _valid_identifier(material.get("namespace"))
        or type(material.get("sequence")) is not int
        or cast(int, material["sequence"]) <= 0
        or not _valid_sha256(material.get("event_sha256"))
        or not _valid_sha256(material.get("operation_id"))
        or material.get("signed_head_durably_anchored") is not True
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_INVALID")
    return material


def _validate_local_event_material(
    *,
    completion_bytes: bytes,
    final_page_bytes: bytes,
    claim_template: dict[str, Any],
) -> None:
    completion_event = _parse_exact_json(
        completion_bytes,
        reason="PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES_INVALID",
        maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES,
    )
    final_page_event = _parse_exact_json(
        final_page_bytes,
        reason="PROFILED_OPTIMIZER_FINAL_PAGE_EVENT_BYTES_INVALID",
        maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES,
    )
    expected_completion = cast(dict[str, Any], claim_template["full_consumption_binding"])
    completion_integer_fields = (
        "head_revision",
        "page_count",
        "consumed_entry_count",
        "admitted_entry_count",
        "label_unavailable_count",
    )
    final_page_integer_fields = (
        "page_sequence",
        "cumulative_scanned_entry_count",
        "cumulative_admitted_entry_count",
        "cumulative_label_unavailable_count",
    )
    if (
        any(type(completion_event.get(name)) is not int for name in completion_integer_fields)
        or any(type(final_page_event.get(name)) is not int for name in final_page_integer_fields)
        or any(
            not _valid_sha256(completion_event.get(name))
            for name in (
                "completion_id",
                "epoch_id",
                "manifest_id",
                "head_candidate_event_sha256",
                "terminal_entry_chain_sha256",
                "final_page_receipt_event_sha256",
                "final_page_transition_sha256",
                "ordered_page_root_sha256",
            )
        )
        or not _valid_identifier(completion_event.get("consumer_lane"))
        or any(
            not _valid_sha256(final_page_event.get(name))
            for name in (
                "epoch_id",
                "page_end_entry_chain_sha256",
                "page_transition_sha256",
                "ordered_page_root_sha256",
            )
        )
        or completion_event.get("full_consumption_locally_verified") is not True
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_LOCAL_EVENT_CONTRACT_INVALID")
    _clock(
        final_page_event.get("verified_at"),
        reason="PROFILED_OPTIMIZER_FINAL_PAGE_EVENT_CLOCK_INVALID",
    )
    completion_pairs = {
        "completion_id": "completion_id",
        "epoch_id": "epoch_id",
        "consumer_lane": "consumer_lane",
        "manifest_id": "manifest_id",
        "head_candidate_event_sha256": "head_candidate_event_sha256",
        "head_revision": "head_revision",
        "page_count": "page_count",
        "consumed_entry_count": "consumed_entry_count",
        "admitted_entry_count": "admitted_entry_count",
        "label_unavailable_count": "label_unavailable_count",
        "terminal_entry_chain_sha256": "terminal_entry_chain_sha256",
        "final_page_receipt_event_sha256": "final_page_receipt_event_sha256",
        "final_page_transition_sha256": "final_page_transition_sha256",
        "ordered_page_root_sha256": "ordered_page_root_sha256",
    }
    if (
        any(
            completion_event.get(event_name) != expected_completion.get(binding_name)
            for event_name, binding_name in completion_pairs.items()
        )
        or any(completion_event.get(name) is not False for name in _LOCAL_EVENT_AUTHORITY_FIELDS)
        or any(final_page_event.get(name) is not False for name in _LOCAL_EVENT_AUTHORITY_FIELDS)
        or final_page_event.get("epoch_id") != expected_completion.get("epoch_id")
        or final_page_event.get("page_sequence") != expected_completion.get("page_count")
        or final_page_event.get("cumulative_scanned_entry_count")
        != expected_completion.get("consumed_entry_count")
        or final_page_event.get("cumulative_admitted_entry_count")
        != expected_completion.get("admitted_entry_count")
        or final_page_event.get("cumulative_label_unavailable_count")
        != expected_completion.get("label_unavailable_count")
        or final_page_event.get("page_end_entry_chain_sha256")
        != expected_completion.get("terminal_entry_chain_sha256")
        or final_page_event.get("page_transition_sha256")
        != expected_completion.get("final_page_transition_sha256")
        or final_page_event.get("ordered_page_root_sha256")
        != expected_completion.get("ordered_page_root_sha256")
        or final_page_event.get("verified_at")
        != expected_completion.get("final_page_verified_at")
        or final_page_event.get("has_more_manifest_entries") is not False
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_LOCAL_EVENT_BINDING_INVALID")


def _base_request(
    *,
    witness_id: str,
    witness_public_key_sha256: str,
    authorization_namespace: str,
    expected_authorization_sequence: int,
    expected_previous_authorization_event_sha256: str,
    manifest_head_binding: dict[str, Any],
    authorization_challenge: bytes,
    authorization_claim_template: bytes,
    completion_event_bytes: bytes,
    final_page_event_bytes: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION,
        "request_domain": PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN,
        "witness_id": witness_id,
        "witness_public_key_sha256": witness_public_key_sha256,
        "authorization_namespace": authorization_namespace,
        "expected_authorization_sequence": expected_authorization_sequence,
        "expected_previous_authorization_event_sha256": (
            expected_previous_authorization_event_sha256
        ),
        "manifest_head_binding": manifest_head_binding,
        "authorization_challenge_sha256": hashlib.sha256(authorization_challenge).hexdigest(),
        "authorization_challenge_byte_count": len(authorization_challenge),
        "authorization_challenge_base64": base64.b64encode(authorization_challenge).decode(
            "ascii"
        ),
        "authorization_claim_template_sha256": hashlib.sha256(
            authorization_claim_template
        ).hexdigest(),
        "authorization_claim_template_byte_count": len(authorization_claim_template),
        "authorization_claim_template_base64": base64.b64encode(
            authorization_claim_template
        ).decode("ascii"),
        "completion_event_sha256": hashlib.sha256(completion_event_bytes).hexdigest(),
        "completion_event_byte_count": len(completion_event_bytes),
        "completion_event_base64": base64.b64encode(completion_event_bytes).decode("ascii"),
        "final_page_receipt_event_sha256": hashlib.sha256(final_page_event_bytes).hexdigest(),
        "final_page_receipt_event_byte_count": len(final_page_event_bytes),
        "final_page_receipt_event_base64": base64.b64encode(final_page_event_bytes).decode(
            "ascii"
        ),
        "authorization_scope": PROFILED_OPTIMIZER_ADMISSION_SCOPE,
        "outcome_supervised_objective_only": True,
        "behavior_policy_terms_authorized": False,
        "full_consumption_locally_verified": True,
        **{name: False for name in _REQUEST_AUTHORITY_FIELDS},
    }


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerExternalCompletionPreparedRequestV1:
    """Exact replay material that must be durably stored before dispatch."""

    schema_version: str
    witness_id: str
    witness_public_key_sha256: str
    authorization_namespace: str
    expected_authorization_sequence: int
    expected_previous_authorization_event_sha256: str
    manifest_id: str
    completion_event_sha256: str
    completion_event_byte_count: int
    completion_event_bytes: bytes = field(repr=False)
    final_page_receipt_event_sha256: str
    final_page_receipt_event_byte_count: int
    final_page_receipt_event_bytes: bytes = field(repr=False)
    manifest_head_namespace: str
    manifest_head_sequence: int
    manifest_head_event_sha256: str
    manifest_head_operation_id: str
    authorization_challenge: bytes = field(repr=False)
    authorization_challenge_sha256: str
    authorization_claim_template: bytes = field(repr=False)
    authorization_claim_template_sha256: str
    idempotency_key: str
    request_sha256: str
    request_byte_count: int
    request_bytes: bytes = field(repr=False)
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
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PREPARED_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION
            or not _valid_identifier(self.witness_id)
            or not _valid_sha256(self.witness_public_key_sha256)
            or not _valid_identifier(self.authorization_namespace)
            or type(self.expected_authorization_sequence) is not int
            or not 0 <= self.expected_authorization_sequence <= 2**63 - 2
            or not _valid_sha256(self.expected_previous_authorization_event_sha256)
            or (
                self.expected_authorization_sequence == 0
                and self.expected_previous_authorization_event_sha256
                != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            )
            or (
                self.expected_authorization_sequence > 0
                and self.expected_previous_authorization_event_sha256
                == PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            )
            or not all(
                _valid_sha256(value)
                for value in (
                    self.manifest_id,
                    self.completion_event_sha256,
                    self.final_page_receipt_event_sha256,
                    self.manifest_head_event_sha256,
                    self.manifest_head_operation_id,
                    self.authorization_challenge_sha256,
                    self.authorization_claim_template_sha256,
                    self.idempotency_key,
                    self.request_sha256,
                )
            )
            or type(self.completion_event_byte_count) is not int
            or self.completion_event_byte_count <= 0
            or self.completion_event_byte_count > MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES
            or type(self.completion_event_bytes) is not bytes
            or len(self.completion_event_bytes) != self.completion_event_byte_count
            or hashlib.sha256(self.completion_event_bytes).hexdigest()
            != self.completion_event_sha256
            or type(self.final_page_receipt_event_byte_count) is not int
            or self.final_page_receipt_event_byte_count <= 0
            or self.final_page_receipt_event_byte_count
            > MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES
            or type(self.final_page_receipt_event_bytes) is not bytes
            or len(self.final_page_receipt_event_bytes)
            != self.final_page_receipt_event_byte_count
            or hashlib.sha256(self.final_page_receipt_event_bytes).hexdigest()
            != self.final_page_receipt_event_sha256
            or not _valid_identifier(self.manifest_head_namespace)
            or type(self.manifest_head_sequence) is not int
            or self.manifest_head_sequence <= 0
            or type(self.authorization_challenge) is not bytes
            or len(self.authorization_challenge) != PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES
            or hashlib.sha256(self.authorization_challenge).hexdigest()
            != self.authorization_challenge_sha256
            or type(self.authorization_claim_template) is not bytes
            or hashlib.sha256(self.authorization_claim_template).hexdigest()
            != self.authorization_claim_template_sha256
            or type(self.request_byte_count) is not int
            or self.request_byte_count <= 0
            or self.request_byte_count > MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES
            or type(self.request_bytes) is not bytes
            or len(self.request_bytes) != self.request_byte_count
            or hashlib.sha256(self.request_bytes).hexdigest() != self.request_sha256
            or any(
                type(value) is not bool or value
                for value in (
                    self.external_monotonic_manifest_head_verified,
                    self.full_consumption_external_ack_verified,
                    self.profiled_optimizer_admission_authorized,
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
            _fail("PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_INVALID")
        material = _parse_exact_json(
            self.request_bytes,
            reason="PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_BYTES_INVALID",
        )
        if set(material) != _REQUEST_FIELDS:
            _fail("PROFILED_OPTIMIZER_COMPLETION_REQUEST_FIELD_SET_INVALID")
        claim_template_bytes = _decode_base64(
            material.get("authorization_claim_template_base64"),
            expected_count=material.get("authorization_claim_template_byte_count"),
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
            reason="PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_INVALID",
        )
        completion_bytes = _decode_base64(
            material.get("completion_event_base64"),
            expected_count=material.get("completion_event_byte_count"),
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES,
            reason="PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES_INVALID",
        )
        final_page_bytes = _decode_base64(
            material.get("final_page_receipt_event_base64"),
            expected_count=material.get("final_page_receipt_event_byte_count"),
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES,
            reason="PROFILED_OPTIMIZER_FINAL_PAGE_EVENT_BYTES_INVALID",
        )
        challenge = _decode_base64(
            material.get("authorization_challenge_base64"),
            expected_count=material.get("authorization_challenge_byte_count"),
            maximum_bytes=PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES,
            reason="PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_INVALID",
        )
        claim_template = _claim_template_material(claim_template_bytes)
        head = _head_binding(material.get("manifest_head_binding"))
        _validate_local_event_material(
            completion_bytes=completion_bytes,
            final_page_bytes=final_page_bytes,
            claim_template=claim_template,
        )
        manifest_binding = cast(dict[str, Any], claim_template["manifest_binding"])
        completion_binding = cast(dict[str, Any], claim_template["full_consumption_binding"])
        base = {name: value for name, value in material.items() if name != "idempotency_key"}
        derived_idempotency_key = hashlib.sha256(
            PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
            + b"\0"
            + _canonical_json_bytes(
                base,
                reason="PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES_INVALID",
            )
        ).hexdigest()
        if (
            material.get("schema_version")
            != PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION
            or material.get("request_domain") != PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN
            or material.get("witness_id") != self.witness_id
            or material.get("witness_public_key_sha256") != self.witness_public_key_sha256
            or material.get("authorization_namespace") != self.authorization_namespace
            or type(material.get("expected_authorization_sequence")) is not int
            or material.get("expected_authorization_sequence")
            != self.expected_authorization_sequence
            or material.get("expected_previous_authorization_event_sha256")
            != self.expected_previous_authorization_event_sha256
            or material.get("authorization_challenge_sha256")
            != self.authorization_challenge_sha256
            or not hmac.compare_digest(challenge, self.authorization_challenge)
            or material.get("authorization_claim_template_sha256")
            != self.authorization_claim_template_sha256
            or not hmac.compare_digest(
                claim_template_bytes,
                self.authorization_claim_template,
            )
            or material.get("completion_event_sha256") != self.completion_event_sha256
            or not hmac.compare_digest(completion_bytes, self.completion_event_bytes)
            or material.get("final_page_receipt_event_sha256")
            != self.final_page_receipt_event_sha256
            or not hmac.compare_digest(final_page_bytes, self.final_page_receipt_event_bytes)
            or head.get("witness_id") != self.witness_id
            or head.get("witness_public_key_sha256") != self.witness_public_key_sha256
            or head.get("namespace") != self.manifest_head_namespace
            or self.authorization_namespace != self.manifest_head_namespace
            or head.get("sequence") != self.manifest_head_sequence
            or head.get("event_sha256") != self.manifest_head_event_sha256
            or head.get("operation_id") != self.manifest_head_operation_id
            or claim_template.get("witness_id") != self.witness_id
            or claim_template.get("declared_witness_public_key_sha256")
            != self.witness_public_key_sha256
            or claim_template.get("namespace") != self.authorization_namespace
            or claim_template.get("authorization_sequence")
            != self.expected_authorization_sequence + 1
            or claim_template.get("previous_authorization_event_sha256")
            != self.expected_previous_authorization_event_sha256
            or claim_template.get("authorization_challenge_sha256")
            != self.authorization_challenge_sha256
            or completion_binding.get("head_candidate_event_sha256")
            != self.manifest_head_event_sha256
            or completion_binding.get("head_revision") != self.manifest_head_sequence
            or completion_binding.get("manifest_id") != self.manifest_id
            or manifest_binding.get("manifest_id") != self.manifest_id
            or completion_binding.get("completion_event_sha256")
            != self.completion_event_sha256
            or completion_binding.get("completion_event_byte_count")
            != self.completion_event_byte_count
            or completion_binding.get("final_page_receipt_event_sha256")
            != self.final_page_receipt_event_sha256
            or material.get("authorization_scope") != PROFILED_OPTIMIZER_ADMISSION_SCOPE
            or material.get("outcome_supervised_objective_only") is not True
            or material.get("behavior_policy_terms_authorized") is not False
            or material.get("full_consumption_locally_verified") is not True
            or any(material.get(name) is not False for name in _REQUEST_AUTHORITY_FIELDS)
            or material.get("idempotency_key") != self.idempotency_key
            or derived_idempotency_key != self.idempotency_key
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class VerifiedProfiledOptimizerExternalCompletionResponseV1:
    schema_version: str
    request_sha256: str
    idempotency_key: str
    witness_id: str
    witness_public_key_sha256: str
    namespace: str
    authorization_sequence: int
    previous_authorization_event_sha256: str
    authorization_challenge_sha256: str
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
    authorization_envelope_bytes: bytes = field(repr=False)
    _prepared_request: ProfiledOptimizerExternalCompletionPreparedRequestV1 = field(
        repr=False,
        compare=False,
    )
    _witness_public_key_bytes: bytes = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _VERIFIED_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION
            or not all(
                _valid_sha256(value)
                for value in (
                    self.request_sha256,
                    self.idempotency_key,
                    self.witness_public_key_sha256,
                    self.previous_authorization_event_sha256,
                    self.authorization_challenge_sha256,
                    self.authorization_envelope_sha256,
                    self.manifest_id,
                    self.completion_event_sha256,
                )
            )
            or not _valid_identifier(self.witness_id)
            or not _valid_identifier(self.namespace)
            or type(self.authorization_sequence) is not int
            or self.authorization_sequence <= 0
            or self.external_monotonic_manifest_head_verified is not True
            or self.full_consumption_external_ack_verified is not True
            or self.profiled_optimizer_admission_authorized is not True
            or any(
                type(value) is not bool or value
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
            or type(self.authorization_envelope_bytes) is not bytes
            or not self.authorization_envelope_bytes
            or hashlib.sha256(self.authorization_envelope_bytes).hexdigest()
            != self.authorization_envelope_sha256
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_INVALID")
        if type(self._prepared_request) is not ProfiledOptimizerExternalCompletionPreparedRequestV1:
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_PREPARED_INVALID")
        self._prepared_request.__post_init__()
        if (
            type(self._witness_public_key_bytes) is not bytes
            or len(self._witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
            or hashlib.sha256(self._witness_public_key_bytes).hexdigest()
            != self.witness_public_key_sha256
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_KEY_INVALID")
        envelope = _parse_exact_json(
            self.authorization_envelope_bytes,
            reason="PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_ENVELOPE_INVALID",
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
        )
        if set(envelope) != _AUTHORIZATION_FIELDS:
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_ENVELOPE_INVALID")
        signature_hex = envelope.get("signature_hex")
        if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_SIGNATURE_INVALID")
        claim_template = {
            name: value
            for name, value in envelope.items()
            if name not in {"accepted_at", "signature_hex"}
        }
        claim_template_bytes = _canonical_json_bytes(
            claim_template,
            reason="PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_CLAIM_INVALID",
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
        )
        claim = _claim_template_material(claim_template_bytes)
        manifest = cast(dict[str, Any], claim["manifest_binding"])
        completion = cast(dict[str, Any], claim["full_consumption_binding"])
        accepted = _clock(
            self.accepted_at,
            reason="PROFILED_OPTIMIZER_COMPLETION_RESPONSE_CLOCK_INVALID",
        )
        prepared = self._prepared_request
        if (
            self.request_sha256 != prepared.request_sha256
            or self.idempotency_key != prepared.idempotency_key
            or self.witness_id != prepared.witness_id
            or self.witness_public_key_sha256 != prepared.witness_public_key_sha256
            or self.namespace != prepared.authorization_namespace
            or self.authorization_sequence != prepared.expected_authorization_sequence + 1
            or self.previous_authorization_event_sha256
            != prepared.expected_previous_authorization_event_sha256
            or self.authorization_challenge_sha256 != prepared.authorization_challenge_sha256
            or self.manifest_id != prepared.manifest_id
            or self.completion_event_sha256 != prepared.completion_event_sha256
            or not hmac.compare_digest(
                claim_template_bytes,
                prepared.authorization_claim_template,
            )
            or envelope.get("accepted_at") != self.accepted_at
            or manifest.get("manifest_id") != self.manifest_id
            or completion.get("completion_event_sha256") != self.completion_event_sha256
            or accepted
            <= max(
                _clock(
                    manifest.get("observation_time"),
                    reason="PROFILED_OPTIMIZER_COMPLETION_MANIFEST_CLOCK_INVALID",
                ),
                _clock(
                    completion.get("final_page_verified_at"),
                    reason="PROFILED_OPTIMIZER_COMPLETION_FINAL_PAGE_CLOCK_INVALID",
                ),
            )
        ):
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_BINDING_INVALID")
        unsigned = {name: value for name, value in envelope.items() if name != "signature_hex"}
        try:
            Ed25519PublicKey.from_public_bytes(self._witness_public_key_bytes).verify(
                bytes.fromhex(signature_hex),
                PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR
                + _canonical_json_bytes(
                    unsigned,
                    reason="PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_ENVELOPE_INVALID",
                    maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
                ),
            )
        except (InvalidSignature, TypeError, ValueError):
            _fail("PROFILED_OPTIMIZER_COMPLETION_VERIFIED_RESPONSE_SIGNATURE_UNVERIFIED")


def prepare_profiled_optimizer_external_completion_request_v1(
    *,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    completion: LocalProfiledTrainingObservationCompletionCandidateV1,
    final_page: LocalProfiledTrainingObservationPageReceiptV1,
    completion_staging_store: ImmutableSourcePayloadStore,
    manifest_head_anchor: ProfiledTrainingExternalWitnessRuntimeResultV1,
    authorization_namespace: str,
    expected_authorization_sequence: int,
    expected_previous_authorization_event_sha256: str,
    authorization_challenge: bytes,
) -> ProfiledOptimizerExternalCompletionPreparedRequestV1:
    """Freeze one exact, non-authorizing completion request before dispatch."""

    if type(authenticated_manifest) is not AuthenticatedProfiledTrainingObservationManifestV1:
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHENTICATED_MANIFEST_EXACT_TYPE_REQUIRED")
    if type(completion) is not LocalProfiledTrainingObservationCompletionCandidateV1:
        _fail("PROFILED_OPTIMIZER_COMPLETION_CANDIDATE_EXACT_TYPE_REQUIRED")
    if type(final_page) is not LocalProfiledTrainingObservationPageReceiptV1:
        _fail("PROFILED_OPTIMIZER_COMPLETION_FINAL_PAGE_EXACT_TYPE_REQUIRED")
    if type(completion_staging_store) is not ImmutableSourcePayloadStore:
        _fail("PROFILED_OPTIMIZER_COMPLETION_STAGING_STORE_EXACT_TYPE_REQUIRED")
    if type(manifest_head_anchor) is not ProfiledTrainingExternalWitnessRuntimeResultV1:
        _fail("PROFILED_OPTIMIZER_COMPLETION_HEAD_ANCHOR_EXACT_TYPE_REQUIRED")
    authenticated_manifest.__post_init__()
    completion.__post_init__()
    final_page.__post_init__()
    manifest_head_anchor.__post_init__()
    namespace = _identifier(
        authorization_namespace,
        reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_NAMESPACE_INVALID",
    )
    if (
        type(expected_authorization_sequence) is not int
        or not 0 <= expected_authorization_sequence <= 2**63 - 2
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_EXPECTED_SEQUENCE_INVALID")
    if not _valid_sha256(expected_previous_authorization_event_sha256):
        _fail("PROFILED_OPTIMIZER_COMPLETION_EXPECTED_PREDECESSOR_INVALID")
    if (
        expected_authorization_sequence == 0
        and expected_previous_authorization_event_sha256
        != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_GENESIS_PREDECESSOR_INVALID")
    if (
        expected_authorization_sequence > 0
        and expected_previous_authorization_event_sha256
        == PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_SUCCESSOR_PREDECESSOR_INVALID")
    if (
        type(authorization_challenge) is not bytes
        or len(authorization_challenge) != PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_INVALID")
    if authenticated_manifest.admitted_example_count <= 0:
        _fail("PROFILED_OPTIMIZER_COMPLETION_ZERO_ADMITTED_INVENTORY_FORBIDDEN")
    if (
        completion_staging_store.root_path != completion.staging_store_root
        or completion_staging_store.root_path != final_page.staging_store_root
        or completion.manifest_id != authenticated_manifest.manifest_id
        or completion.head_candidate_event_sha256 != manifest_head_anchor.event_sha256
        or completion.head_revision != manifest_head_anchor.anchored_sequence
        or namespace != manifest_head_anchor.namespace
        or manifest_head_anchor.signed_head_durably_anchored is not True
        or manifest_head_anchor.journal_pending_count != 0
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_HEAD_OR_STAGING_BINDING_INVALID")
    try:
        completion_event_bytes = completion_staging_store.get(
            completion.completion_event_sha256,
            expected_byte_count=completion.completion_event_byte_count,
        )
        final_page_event_bytes = completion_staging_store.get(
            final_page.page_receipt_event_sha256,
            expected_byte_count=final_page.page_receipt_event_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledOptimizerExternalCompletionRequestV1Error(
            "PROFILED_OPTIMIZER_COMPLETION_STAGING_EVENT_REOPEN_FAILED"
        ) from exc
    claim_template = profiled_optimizer_external_completion_claim_template_v1(
        authenticated_manifest=authenticated_manifest,
        completion=completion,
        final_page=final_page,
        witness_id=manifest_head_anchor.witness_id,
        namespace=namespace,
        witness_public_key_sha256=manifest_head_anchor.witness_public_key_sha256,
        authorization_sequence=expected_authorization_sequence + 1,
        previous_authorization_event_sha256=(
            expected_previous_authorization_event_sha256
        ),
        authorization_challenge=authorization_challenge,
    )
    claim_material = _claim_template_material(claim_template)
    _validate_local_event_material(
        completion_bytes=completion_event_bytes,
        final_page_bytes=final_page_event_bytes,
        claim_template=claim_material,
    )
    head_binding = {
        "schema_version": PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_V1_SCHEMA_VERSION,
        "witness_id": manifest_head_anchor.witness_id,
        "witness_public_key_sha256": manifest_head_anchor.witness_public_key_sha256,
        "namespace": manifest_head_anchor.namespace,
        "sequence": manifest_head_anchor.anchored_sequence,
        "event_sha256": manifest_head_anchor.event_sha256,
        "operation_id": manifest_head_anchor.operation_id,
        "signed_head_durably_anchored": True,
    }
    base_request = _base_request(
        witness_id=manifest_head_anchor.witness_id,
        witness_public_key_sha256=manifest_head_anchor.witness_public_key_sha256,
        authorization_namespace=namespace,
        expected_authorization_sequence=expected_authorization_sequence,
        expected_previous_authorization_event_sha256=(
            expected_previous_authorization_event_sha256
        ),
        manifest_head_binding=head_binding,
        authorization_challenge=authorization_challenge,
        authorization_claim_template=claim_template,
        completion_event_bytes=completion_event_bytes,
        final_page_event_bytes=final_page_event_bytes,
    )
    idempotency_key = hashlib.sha256(
        PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical_json_bytes(
            base_request,
            reason="PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES_INVALID",
        )
    ).hexdigest()
    request_bytes = _canonical_json_bytes(
        {**base_request, "idempotency_key": idempotency_key},
        reason="PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES_INVALID",
    )
    return ProfiledOptimizerExternalCompletionPreparedRequestV1(
        schema_version=PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION,
        witness_id=manifest_head_anchor.witness_id,
        witness_public_key_sha256=manifest_head_anchor.witness_public_key_sha256,
        authorization_namespace=namespace,
        expected_authorization_sequence=expected_authorization_sequence,
        expected_previous_authorization_event_sha256=(
            expected_previous_authorization_event_sha256
        ),
        manifest_id=authenticated_manifest.manifest_id,
        completion_event_sha256=completion.completion_event_sha256,
        completion_event_byte_count=completion.completion_event_byte_count,
        completion_event_bytes=completion_event_bytes,
        final_page_receipt_event_sha256=final_page.page_receipt_event_sha256,
        final_page_receipt_event_byte_count=final_page.page_receipt_event_byte_count,
        final_page_receipt_event_bytes=final_page_event_bytes,
        manifest_head_namespace=manifest_head_anchor.namespace,
        manifest_head_sequence=manifest_head_anchor.anchored_sequence,
        manifest_head_event_sha256=manifest_head_anchor.event_sha256,
        manifest_head_operation_id=manifest_head_anchor.operation_id,
        authorization_challenge=bytes(authorization_challenge),
        authorization_challenge_sha256=hashlib.sha256(authorization_challenge).hexdigest(),
        authorization_claim_template=claim_template,
        authorization_claim_template_sha256=hashlib.sha256(claim_template).hexdigest(),
        idempotency_key=idempotency_key,
        request_sha256=hashlib.sha256(request_bytes).hexdigest(),
        request_byte_count=len(request_bytes),
        request_bytes=request_bytes,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        profiled_optimizer_admission_authorized=False,
        optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _construction_token=_PREPARED_TOKEN,
    )


def verify_profiled_optimizer_external_completion_response_v1(
    *,
    prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
    authorization_envelope_bytes: bytes,
    witness_public_key_bytes: bytes,
) -> VerifiedProfiledOptimizerExternalCompletionResponseV1:
    """Verify one signed response against exact pre-dispatch request bytes."""

    if type(prepared) is not ProfiledOptimizerExternalCompletionPreparedRequestV1:
        _fail("PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_EXACT_TYPE_REQUIRED")
    prepared.__post_init__()
    if (
        type(witness_public_key_bytes) is not bytes
        or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_WITNESS_PUBLIC_KEY_INVALID")
    if hashlib.sha256(witness_public_key_bytes).hexdigest() != prepared.witness_public_key_sha256:
        _fail("PROFILED_OPTIMIZER_COMPLETION_WITNESS_PUBLIC_KEY_FINGERPRINT_MISMATCH")
    envelope = _parse_exact_json(
        authorization_envelope_bytes,
        reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ENVELOPE_INVALID",
        maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
    )
    if set(envelope) != _AUTHORIZATION_FIELDS:
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_FIELD_SET_INVALID")
    signature_hex = envelope.get("signature_hex")
    if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_SIGNATURE_INVALID")
    request = _parse_exact_json(
        prepared.request_bytes,
        reason="PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_BYTES_INVALID",
    )
    claim_template_bytes = _decode_base64(
        request.get("authorization_claim_template_base64"),
        expected_count=request.get("authorization_claim_template_byte_count"),
        maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
        reason="PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_INVALID",
    )
    claim_template = _claim_template_material(claim_template_bytes)
    if not hmac.compare_digest(claim_template_bytes, prepared.authorization_claim_template):
        _fail("PROFILED_OPTIMIZER_COMPLETION_CLAIM_TEMPLATE_MISMATCH")
    manifest_binding = cast(dict[str, Any], claim_template["manifest_binding"])
    completion_binding = cast(dict[str, Any], claim_template["full_consumption_binding"])
    accepted_at = envelope.get("accepted_at")
    accepted = _clock(
        accepted_at,
        reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ACCEPTED_AT_INVALID",
    )
    if accepted <= max(
        _clock(
            manifest_binding.get("observation_time"),
            reason="PROFILED_OPTIMIZER_COMPLETION_MANIFEST_CLOCK_INVALID",
        ),
        _clock(
            completion_binding.get("final_page_verified_at"),
            reason="PROFILED_OPTIMIZER_COMPLETION_FINAL_PAGE_CLOCK_INVALID",
        ),
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_PRECEDES_FULL_CONSUMPTION")
    expected_unsigned = {**claim_template, "accepted_at": accepted_at}
    unsigned = {name: value for name, value in envelope.items() if name != "signature_hex"}
    if not hmac.compare_digest(
        _canonical_json_bytes(
            unsigned,
            reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ENVELOPE_INVALID",
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
        ),
        _canonical_json_bytes(
            expected_unsigned,
            reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ENVELOPE_INVALID",
            maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
        ),
    ):
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BINDING_MISMATCH")
    try:
        Ed25519PublicKey.from_public_bytes(witness_public_key_bytes).verify(
            bytes.fromhex(signature_hex),
            PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR
            + _canonical_json_bytes(
                unsigned,
                reason="PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_ENVELOPE_INVALID",
                maximum_bytes=MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES,
            ),
        )
    except (InvalidSignature, TypeError, ValueError):
        _fail("PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_SIGNATURE_UNVERIFIED")
    envelope_bytes = bytes(authorization_envelope_bytes)
    return VerifiedProfiledOptimizerExternalCompletionResponseV1(
        schema_version=PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_V1_SCHEMA_VERSION,
        request_sha256=prepared.request_sha256,
        idempotency_key=prepared.idempotency_key,
        witness_id=prepared.witness_id,
        witness_public_key_sha256=prepared.witness_public_key_sha256,
        namespace=prepared.authorization_namespace,
        authorization_sequence=prepared.expected_authorization_sequence + 1,
        previous_authorization_event_sha256=(
            prepared.expected_previous_authorization_event_sha256
        ),
        authorization_challenge_sha256=prepared.authorization_challenge_sha256,
        accepted_at=cast(str, accepted_at),
        authorization_envelope_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
        manifest_id=prepared.manifest_id,
        completion_event_sha256=prepared.completion_event_sha256,
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
        authorization_envelope_bytes=envelope_bytes,
        _prepared_request=prepared,
        _witness_public_key_bytes=bytes(witness_public_key_bytes),
        _construction_token=_VERIFIED_TOKEN,
    )


__all__ = (
    "MAX_PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_BYTES",
    "MAX_PROFILED_OPTIMIZER_COMPLETION_EVENT_BYTES",
    "MAX_PROFILED_OPTIMIZER_COMPLETION_REQUEST_BYTES",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256",
    "PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES",
    "PROFILED_OPTIMIZER_COMPLETION_HEAD_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN",
    "PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION",
    "ProfiledOptimizerExternalCompletionPreparedRequestV1",
    "ProfiledOptimizerExternalCompletionRequestV1Error",
    "VerifiedProfiledOptimizerExternalCompletionResponseV1",
    "prepare_profiled_optimizer_external_completion_request_v1",
    "verify_profiled_optimizer_external_completion_response_v1",
)
