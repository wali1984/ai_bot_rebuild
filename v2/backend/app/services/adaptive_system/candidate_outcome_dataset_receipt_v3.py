"""Authenticated release receipt for continuously rebuilt training datasets.

The candidate archive is append-only and Ed25519-authenticated.  Dataset builds
derived from it need the same durable trust property without pinning one receipt
file forever.  This contract signs a compact, domain-separated receipt whose
payload binds the exact dataset, manifest, parity and source high-water evidence.
It conveys no registry, execution or live authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA_VERSION = "candidate_outcome_dataset_build_receipt_v3"
SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_DOMAIN_NAME = (
    "v2/adaptive-system/candidate-outcome-dataset-build-receipt/v3"
)
SIGNATURE_DOMAIN = SIGNATURE_DOMAIN_NAME.encode("ascii") + b"\0"
ARTIFACT_FILENAMES = frozenset(
    {
        "adaptive_serving_compatible_dataset_v2.json",
        "adaptive_serving_compatible_dataset_manifest_v2.json",
        "adaptive_train_serve_feature_parity_report_v2.json",
    }
)
SIGNATURE_FIELDS = frozenset(
    {
        "receipt_writer_id",
        "receipt_writer_public_key_hex",
        "receipt_signature_algorithm",
        "receipt_signature_domain",
        "receipt_payload_sha256",
        "receipt_signature_hex",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")


class CandidateOutcomeDatasetReceiptError(ValueError):
    """Raised when a build receipt is unsigned, forged or structurally unsafe."""


def _fail(reason: str, field: str) -> None:
    raise CandidateOutcomeDatasetReceiptError(f"{field}:{reason}")


def canonical_receipt_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("STRICT_JSON_REQUIRED", "receipt")
        raise AssertionError("unreachable") from exc


def receipt_unsigned_material(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_payload_sha256", "receipt_signature_hex"}
    }


def finalize_signed_build_receipt(
    receipt: Mapping[str, Any],
    *,
    artifact_file_sha256s: Mapping[str, str],
    signer: Callable[[bytes], bytes],
    writer_id: str,
    writer_public_key_hex: str,
) -> dict[str, Any]:
    """Return an immediately self-verified signed release receipt."""

    if not callable(signer):
        _fail("CALLABLE_REQUIRED", "receipt_signer")
    if (
        type(writer_id) is not str
        or not writer_id
        or writer_id.strip() != writer_id
        or any(character.isspace() for character in writer_id)
    ):
        _fail("IDENTIFIER_REQUIRED", "receipt_writer_id")
    if type(writer_public_key_hex) is not str or _PUBLIC_KEY_RE.fullmatch(
        writer_public_key_hex
    ) is None:
        _fail("ED25519_PUBLIC_KEY_REQUIRED", "receipt_writer_public_key_hex")
    if (
        type(artifact_file_sha256s) is not dict
        or set(artifact_file_sha256s) != ARTIFACT_FILENAMES
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in artifact_file_sha256s.values()
        )
    ):
        _fail("EXACT_SHA256_MAP_REQUIRED", "artifact_file_sha256s")
    finalized = dict(receipt)
    if finalized.get("schema_version") != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_REQUIRED", "receipt")
    if SIGNATURE_FIELDS.intersection(finalized):
        _fail("ALREADY_FINALIZED", "receipt")
    finalized.update(
        {
            "artifact_file_sha256s": dict(artifact_file_sha256s),
            "receipt_writer_id": writer_id,
            "receipt_writer_public_key_hex": writer_public_key_hex,
            "receipt_signature_algorithm": SIGNATURE_ALGORITHM,
            "receipt_signature_domain": SIGNATURE_DOMAIN_NAME,
        }
    )
    unsigned_bytes = canonical_receipt_bytes(receipt_unsigned_material(finalized))
    finalized["receipt_payload_sha256"] = hashlib.sha256(unsigned_bytes).hexdigest()
    signature = signer(SIGNATURE_DOMAIN + unsigned_bytes)
    if type(signature) is not bytes or len(signature) != 64:
        _fail("ED25519_SIGNATURE_REQUIRED", "receipt_signer")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(writer_public_key_hex)).verify(
            signature,
            SIGNATURE_DOMAIN + unsigned_bytes,
        )
    except (InvalidSignature, ValueError) as exc:
        _fail("SIGNATURE_DOES_NOT_MATCH_DECLARED_KEY", "receipt_signer")
        raise AssertionError("unreachable") from exc
    finalized["receipt_signature_hex"] = signature.hex()
    return finalized


def verify_signed_build_receipt(
    receipt: Mapping[str, Any],
    *,
    pinned_writer_id: str,
    pinned_writer_public_key_hex: str,
) -> None:
    """Verify a signed receipt against code-pinned writer identity and key."""

    if type(receipt) is not dict or receipt.get("schema_version") != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_REQUIRED", "receipt")
    if receipt.get("receipt_writer_id") != pinned_writer_id:
        _fail("PINNED_WRITER_REQUIRED", "receipt_writer_id")
    if receipt.get("receipt_writer_public_key_hex") != pinned_writer_public_key_hex:
        _fail("PINNED_PUBLIC_KEY_REQUIRED", "receipt_writer_public_key_hex")
    if receipt.get("receipt_signature_algorithm") != SIGNATURE_ALGORITHM:
        _fail("ALGORITHM_MISMATCH", "receipt_signature_algorithm")
    if receipt.get("receipt_signature_domain") != SIGNATURE_DOMAIN_NAME:
        _fail("DOMAIN_MISMATCH", "receipt_signature_domain")
    payload_sha256 = receipt.get("receipt_payload_sha256")
    signature_hex = receipt.get("receipt_signature_hex")
    if type(payload_sha256) is not str or _SHA256_RE.fullmatch(payload_sha256) is None:
        _fail("LOWERCASE_SHA256_REQUIRED", "receipt_payload_sha256")
    if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
        _fail("ED25519_SIGNATURE_REQUIRED", "receipt_signature_hex")
    artifact_hashes = receipt.get("artifact_file_sha256s")
    if (
        type(artifact_hashes) is not dict
        or set(artifact_hashes) != ARTIFACT_FILENAMES
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in artifact_hashes.values()
        )
    ):
        _fail("EXACT_SHA256_MAP_REQUIRED", "artifact_file_sha256s")
    unsigned_bytes = canonical_receipt_bytes(receipt_unsigned_material(receipt))
    actual_payload_sha256 = hashlib.sha256(unsigned_bytes).hexdigest()
    if not hmac.compare_digest(payload_sha256, actual_payload_sha256):
        _fail("PAYLOAD_SHA256_MISMATCH", "receipt_payload_sha256")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(pinned_writer_public_key_hex)
        )
        public_key.verify(bytes.fromhex(signature_hex), SIGNATURE_DOMAIN + unsigned_bytes)
    except (InvalidSignature, ValueError) as exc:
        _fail("SIGNATURE_INVALID", "receipt_signature_hex")
        raise AssertionError("unreachable") from exc


__all__ = [
    "ARTIFACT_FILENAMES",
    "CandidateOutcomeDatasetReceiptError",
    "SCHEMA_VERSION",
    "SIGNATURE_ALGORITHM",
    "SIGNATURE_DOMAIN",
    "SIGNATURE_DOMAIN_NAME",
    "SIGNATURE_FIELDS",
    "canonical_receipt_bytes",
    "finalize_signed_build_receipt",
    "receipt_unsigned_material",
    "verify_signed_build_receipt",
]
