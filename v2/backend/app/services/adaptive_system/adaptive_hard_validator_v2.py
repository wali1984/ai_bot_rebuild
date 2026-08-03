"""Canonical paper-only hard-constraint receipt signer for adaptive actions.

The signer is deliberately narrow: callers must provide the exact evidence
digests for every required hard check and every check must already have passed.
It cannot create an action, change a size, route to live, or submit an order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256,
    CANONICAL_HARD_VALIDATOR_ID,
    CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX,
    CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS,
    HARD_VALIDATION_CHECK_SCHEMA_VERSION,
    HARD_VALIDATION_SCHEMA_VERSION,
    HARD_VALIDATION_SIGNATURE_ALGORITHM,
    HARD_VALIDATION_SIGNATURE_DOMAIN,
    HardConstraintCheckEvidenceV2,
    HardConstraintValidationReceiptV2,
)


class AdaptiveHardValidatorError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _private_key(seed: bytes) -> Ed25519PrivateKey:
    if type(seed) is not bytes or len(seed) != 32:
        raise AdaptiveHardValidatorError("validator_seed:exactly_32_bytes_required")
    key = Ed25519PrivateKey.from_private_bytes(seed)
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if public.hex() != CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX:
        raise AdaptiveHardValidatorError("validator_seed:canonical_public_key_mismatch")
    return key


def sign_hard_constraint_validation_receipt(
    *,
    validator_seed: bytes,
    action_sha256: str,
    state_id: str,
    state_sha256: str,
    checkpoint_generation: int,
    checkpoint_id: str,
    checkpoint_sha256: str,
    decision_time_ms: int,
    evaluated_at_ms: int,
    validator_generated_at_ms: int,
    record_available_at_ms: int,
    check_input_evidence_sha256s: Mapping[str, tuple[str, ...]],
) -> HardConstraintValidationReceiptV2:
    """Sign a complete PASS receipt from independently supplied check proofs."""

    expected = frozenset(CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS)
    if frozenset(check_input_evidence_sha256s) != expected:
        missing = sorted(expected - frozenset(check_input_evidence_sha256s))
        extra = sorted(frozenset(check_input_evidence_sha256s) - expected)
        raise AdaptiveHardValidatorError(
            f"check_evidence:exact_set_required:missing={missing}:extra={extra}"
        )
    check_evidence: list[HardConstraintCheckEvidenceV2] = []
    for check_name in sorted(expected):
        inputs = check_input_evidence_sha256s[check_name]
        if type(inputs) is not tuple or inputs != tuple(sorted(set(inputs))) or not inputs:
            raise AdaptiveHardValidatorError(
                f"check_evidence.{check_name}:sorted_unique_nonempty_tuple_required"
            )
        material = {
            "schema_version": HARD_VALIDATION_CHECK_SCHEMA_VERSION,
            "check_name": check_name,
            "input_evidence_sha256s": inputs,
            "passed": True,
        }
        check_evidence.append(
            HardConstraintCheckEvidenceV2(
                **material,
                check_result_sha256=_canonical_sha256(material),
            )
        )
    key = _private_key(validator_seed)
    public = bytes.fromhex(CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX)
    unsigned = {
        "schema_version": HARD_VALIDATION_SCHEMA_VERSION,
        "validator_id": CANONICAL_HARD_VALIDATOR_ID,
        "validator_fingerprint_sha256": CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256,
        "declared_public_key_sha256": hashlib.sha256(public).hexdigest(),
        "signature_algorithm": HARD_VALIDATION_SIGNATURE_ALGORITHM,
        "check_evidence": tuple(check_evidence),
        "action_sha256": action_sha256,
        "state_id": state_id,
        "state_sha256": state_sha256,
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha256,
        "decision_time_ms": decision_time_ms,
        "evaluated_at_ms": evaluated_at_ms,
        "validator_generated_at_ms": validator_generated_at_ms,
        "record_available_at_ms": record_available_at_ms,
        "passed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    signature_payload = HARD_VALIDATION_SIGNATURE_DOMAIN + json.dumps(
        {
            **unsigned,
            "check_evidence": [asdict(item) for item in check_evidence],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    values = {**unsigned, "signature_hex": key.sign(signature_payload).hex()}
    receipt_material = {
        **values,
        "check_evidence": [asdict(item) for item in check_evidence],
    }
    return HardConstraintValidationReceiptV2(
        receipt_sha256=_canonical_sha256(receipt_material),
        **values,
    )


__all__ = (
    "AdaptiveHardValidatorError",
    "sign_hard_constraint_validation_receipt",
)
