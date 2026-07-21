"""Domain-separated HMAC authentication for local paper evidence.

The SHA-256 fields used by the paper risk path are content identities, not
authentication controls: any Redis writer can recompute them.  This module
adds a local producer-to-consumer trust boundary without reading environment
variables, credential files, Redis, or exchange configuration.  Callers must
provide the exact signing key or retained verification keyring explicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

AUTH_ALGORITHM = "HMAC-SHA256"
AUTH_ALGORITHM_FIELD = "evidence_auth_algorithm"
AUTH_KEY_ID_FIELD = "evidence_auth_key_id"
AUTH_TRUST_DOMAIN_FIELD = "evidence_auth_trust_domain"
AUTH_TAG_FIELD = "evidence_hmac_sha256"
AUTH_FIELDS = frozenset(
    {
        AUTH_ALGORITHM_FIELD,
        AUTH_KEY_ID_FIELD,
        AUTH_TRUST_DOMAIN_FIELD,
        AUTH_TAG_FIELD,
    }
)
MIN_AUTHENTICATION_KEY_BYTES = 32

MARK_RECEIPT_TRUST_DOMAIN = "v2.local.binance-mark-receipt.hmac-sha256.v1"
PAPER_AUTHORITY_TRUST_DOMAIN = "v2.paper.adaptive-risk-authority.hmac-sha256.v1"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LocalEvidenceAuthenticationError(ValueError):
    """Raised when local evidence cannot be authenticated canonically."""


def _safe_identity(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise LocalEvidenceAuthenticationError(f"{field}_MISSING_OR_INVALID")
    return value


def _authentication_key(value: Any) -> bytes:
    if isinstance(value, bytes):
        key = value
    elif isinstance(value, bytearray):
        key = bytes(value)
    else:
        key = b""
    if len(key) < MIN_AUTHENTICATION_KEY_BYTES:
        raise LocalEvidenceAuthenticationError(
            "EVIDENCE_AUTHENTICATION_KEY_MISSING_OR_TOO_SHORT"
        )
    return key


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return one unambiguous JSON representation or fail closed."""

    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise LocalEvidenceAuthenticationError(
            "EVIDENCE_AUTHENTICATION_MATERIAL_NOT_STRING_KEYED_MAPPING"
        )
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LocalEvidenceAuthenticationError(
            "EVIDENCE_AUTHENTICATION_MATERIAL_NOT_CANONICAL_JSON"
        ) from exc


def _tag_material(payload: Mapping[str, Any], *, trust_domain: str) -> bytes:
    material = {
        key: value for key, value in dict(payload).items() if key != AUTH_TAG_FIELD
    }
    return (
        b"AI_BOT_V2_LOCAL_EVIDENCE\x00"
        + trust_domain.encode("ascii")
        + b"\x00"
        + canonical_json_bytes(material)
    )


def seal_hmac_sha256(
    material: Mapping[str, Any],
    *,
    trust_domain: str,
    authentication_key_id: str,
    authentication_key: bytes | bytearray,
) -> dict[str, Any]:
    """Authenticate one exact canonical mapping in one trust domain."""

    domain = _safe_identity(trust_domain, field="EVIDENCE_AUTH_TRUST_DOMAIN")
    key_id = _safe_identity(
        authentication_key_id,
        field="EVIDENCE_AUTH_KEY_ID",
    )
    key = _authentication_key(authentication_key)
    payload = dict(material)
    if AUTH_FIELDS.intersection(payload):
        raise LocalEvidenceAuthenticationError(
            "EVIDENCE_AUTHENTICATION_FIELDS_ALREADY_PRESENT"
        )
    payload.update(
        {
            AUTH_ALGORITHM_FIELD: AUTH_ALGORITHM,
            AUTH_KEY_ID_FIELD: key_id,
            AUTH_TRUST_DOMAIN_FIELD: domain,
        }
    )
    payload[AUTH_TAG_FIELD] = hmac.new(
        key,
        _tag_material(payload, trust_domain=domain),
        hashlib.sha256,
    ).hexdigest()
    return payload


def verify_hmac_sha256(
    payload: Any,
    *,
    expected_trust_domain: str,
    authentication_keys: Mapping[str, bytes | bytearray] | None,
    reason_prefix: str,
) -> list[str]:
    """Verify a local evidence tag against an explicit retained keyring.

    No key is inferred from the payload, process environment, or a default.
    The payload selects only a key *identifier*; the caller-owned keyring is
    the trust anchor.  A missing/unknown/invalid key always fails closed.
    """

    prefix = _safe_identity(reason_prefix, field="REASON_PREFIX")
    try:
        domain = _safe_identity(
            expected_trust_domain,
            field="EVIDENCE_AUTH_TRUST_DOMAIN",
        )
    except LocalEvidenceAuthenticationError:
        return [f"{prefix}_AUTH_TRUST_DOMAIN_CONFIGURATION_INVALID"]
    if not isinstance(payload, Mapping):
        return [f"{prefix}_AUTH_PAYLOAD_NOT_A_MAPPING"]

    reasons: list[str] = []
    algorithm = payload.get(AUTH_ALGORITHM_FIELD)
    supplied_domain = payload.get(AUTH_TRUST_DOMAIN_FIELD)
    key_id = payload.get(AUTH_KEY_ID_FIELD)
    supplied_tag = payload.get(AUTH_TAG_FIELD)
    if algorithm != AUTH_ALGORITHM:
        reasons.append(f"{prefix}_AUTH_ALGORITHM_INVALID")
    if not isinstance(supplied_domain, str) or not hmac.compare_digest(
        supplied_domain,
        domain,
    ):
        reasons.append(f"{prefix}_AUTH_TRUST_DOMAIN_INVALID")
    if not isinstance(key_id, str) or _SAFE_ID_RE.fullmatch(key_id) is None:
        reasons.append(f"{prefix}_AUTH_KEY_ID_INVALID")
        key_id = ""
    if not isinstance(supplied_tag, str) or _HEX_SHA256_RE.fullmatch(
        supplied_tag
    ) is None:
        reasons.append(f"{prefix}_AUTH_TAG_INVALID")

    resolved_key: bytes | None = None
    if isinstance(authentication_keys, Mapping) and key_id:
        candidate = authentication_keys.get(key_id)
        try:
            resolved_key = _authentication_key(candidate)
        except LocalEvidenceAuthenticationError:
            resolved_key = None
    if resolved_key is None:
        reasons.append(f"{prefix}_AUTH_KEY_UNAVAILABLE")

    if resolved_key is not None and isinstance(supplied_tag, str):
        try:
            expected_tag = hmac.new(
                resolved_key,
                _tag_material(payload, trust_domain=domain),
                hashlib.sha256,
            ).hexdigest()
        except LocalEvidenceAuthenticationError:
            reasons.append(f"{prefix}_AUTH_CANONICAL_PAYLOAD_INVALID")
        else:
            if not hmac.compare_digest(supplied_tag, expected_tag):
                reasons.append(f"{prefix}_AUTH_TAG_MISMATCH")
    return list(dict.fromkeys(reasons))


def authentication_fields_removed(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return content material without local-authentication metadata."""

    return {key: value for key, value in dict(payload).items() if key not in AUTH_FIELDS}


def authentication_key_bytes(value: Any) -> bytes:
    """Validate key material for explicit runtime-boundary plumbing."""

    return _authentication_key(value)


__all__ = [
    "AUTH_ALGORITHM",
    "AUTH_FIELDS",
    "AUTH_KEY_ID_FIELD",
    "AUTH_TAG_FIELD",
    "AUTH_TRUST_DOMAIN_FIELD",
    "LocalEvidenceAuthenticationError",
    "MARK_RECEIPT_TRUST_DOMAIN",
    "MIN_AUTHENTICATION_KEY_BYTES",
    "PAPER_AUTHORITY_TRUST_DOMAIN",
    "authentication_fields_removed",
    "authentication_key_bytes",
    "canonical_json_bytes",
    "seal_hmac_sha256",
    "verify_hmac_sha256",
]
