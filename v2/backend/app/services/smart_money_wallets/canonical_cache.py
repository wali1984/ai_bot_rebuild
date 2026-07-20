"""Read-only contract for canonical Moralis endpoint cache projections.

Only the canonical provider scheduler may populate these keys.  Secondary
workflows consume the bounded projections from the published envelope instead
of issuing duplicate HTTP requests or spending compute units independently.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.smart_money_wallets.endpoint_registry import MORALIS_EVM_CHAIN_ALIASES

_CACHE_KEYS = {
    "token_holders": "v2:moralis:token_holders:{chain}:{token}",
    "token_metadata": "v2:moralis:token_metadata:{chain}:{token}",
}


@dataclass(frozen=True)
class CanonicalCacheRead:
    ready: bool
    reason: str
    endpoint_id: str
    chain: str
    token: str
    key: str
    records: tuple[dict[str, Any], ...] = ()
    available_at: str | None = None
    expires_at: str | None = None
    envelope_sha256: str | None = None


def read_canonical_records(
    redis_client: Any | None,
    *,
    endpoint_id: str,
    chain: object,
    token: object,
    observed_at: datetime | None = None,
) -> CanonicalCacheRead:
    """Return fresh, identity-bound records or a fail-closed reason."""

    normalized_chain = _chain(chain)
    normalized_token = str(token or "").strip().lower()
    template = _CACHE_KEYS.get(endpoint_id)
    key = (
        template.format(chain=normalized_chain, token=normalized_token)
        if template is not None
        else ""
    )
    def _result(
        reason: str,
        *,
        ready: bool = False,
        records: tuple[dict[str, Any], ...] = (),
        available_at: str | None = None,
        expires_at: str | None = None,
        envelope_sha256: str | None = None,
    ) -> CanonicalCacheRead:
        return CanonicalCacheRead(
            ready=ready,
            reason=reason,
            endpoint_id=endpoint_id,
            chain=normalized_chain,
            token=normalized_token,
            key=key,
            records=records,
            available_at=available_at,
            expires_at=expires_at,
            envelope_sha256=envelope_sha256,
        )

    if redis_client is None:
        return _result("REDIS_UNAVAILABLE")
    if template is None:
        return _result("ENDPOINT_CACHE_UNSUPPORTED")
    if not normalized_chain or not normalized_token:
        return _result("CACHE_IDENTITY_INVALID")
    try:
        raw = redis_client.get(key)
    except Exception:
        return _result("CACHE_READ_FAILED")
    if raw is None:
        return _result("CACHE_MISSING")
    if isinstance(raw, bytes):
        raw_bytes = bytes(raw)
        try:
            raw_text = raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _result("CACHE_UTF8_INVALID")
    else:
        raw_text = str(raw)
        raw_bytes = raw_text.encode("utf-8")
    try:
        envelope = json.loads(raw_text)
    except (TypeError, ValueError):
        return _result("CACHE_JSON_INVALID")
    if not isinstance(envelope, Mapping):
        return _result("CACHE_ENVELOPE_INVALID")
    if (
        envelope.get("schema_version") != "moralis_normalized_payload_v1"
        or envelope.get("provider") != "moralis"
        or envelope.get("endpoint_id") != endpoint_id
        or _chain(envelope.get("chain")) != normalized_chain
        or str(envelope.get("token") or "").strip().lower() != normalized_token
    ):
        return _result("CACHE_IDENTITY_MISMATCH")
    if (
        envelope.get("provider_ready") is not True
        or envelope.get("actual_payload_present") is not True
        or envelope.get("subscription_status") != "READY"
        or envelope.get("auth_status") != "READY"
    ):
        return _result("CACHE_PROVIDER_NOT_READY")

    available = _utc(envelope.get("available_at"))
    ingested = _utc(envelope.get("ingested_at"))
    generated = _utc(envelope.get("generated_at"))
    ttl_seconds = _positive_int(envelope.get("ttl_seconds"))
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    if available is None or ingested is None or generated is None or ttl_seconds is None:
        return _result("CACHE_TEMPORAL_CONTRACT_INVALID")
    if ingested > available or generated > available or available > now:
        return _result("CACHE_TEMPORAL_ORDER_INVALID")
    expires = available + timedelta(seconds=ttl_seconds)
    available_text = available.isoformat().replace("+00:00", "Z")
    expires_text = expires.isoformat().replace("+00:00", "Z")
    # Evidence must identify the exact Redis value. Replacement decoding can
    # collapse distinct invalid byte strings into the same apparent envelope.
    envelope_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if now >= expires:
        return _result(
            "CACHE_STALE",
            available_at=available_text,
            expires_at=expires_text,
            envelope_sha256=envelope_sha256,
        )
    records = envelope.get("canonical_records")
    if not isinstance(records, list) or not records:
        return _result(
            "CACHE_RECORDS_MISSING",
            available_at=available_text,
            expires_at=expires_text,
            envelope_sha256=envelope_sha256,
        )
    if len(records) > 250 or any(not isinstance(row, Mapping) for row in records):
        return _result(
            "CACHE_RECORDS_INVALID",
            available_at=available_text,
            expires_at=expires_text,
            envelope_sha256=envelope_sha256,
        )
    bounded = tuple(dict(row) for row in records)
    return _result(
        "READY",
        ready=True,
        records=bounded,
        available_at=available_text,
        expires_at=expires_text,
        envelope_sha256=envelope_sha256,
    )


def _chain(value: object) -> str:
    raw = str(value or "").strip().lower()
    return MORALIS_EVM_CHAIN_ALIASES.get(raw, raw)


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None
