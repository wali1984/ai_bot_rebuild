"""Read-only contract for canonical Moralis endpoint cache projections.

Only the canonical provider scheduler may populate these keys.  Secondary
workflows consume the bounded projections from the published envelope instead
of issuing duplicate HTTP requests or spending compute units independently.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.smart_money_wallets.endpoint_registry import MORALIS_EVM_CHAIN_ALIASES

_CACHE_KEYS = {
    "token_holders": "v2:moralis:token_holders:{chain}:{token}",
}
_TOKEN_METADATA_INDEX_TEMPLATE = "v2:moralis:index:v2:token_metadata:{chain}:{token}"  # noqa: S105 - Redis key template
_TOKEN_METADATA_MANIFEST_PREFIX = "v2:moralis:manifest:v2:token_metadata"  # noqa: S105 - Redis key prefix
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
_SAFE_KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CACHE_BYTES = 4_194_304
_MAX_JSON_DEPTH = 16
_MAX_JSON_LIST_ITEMS = 1000
_MAX_JSON_OBJECT_FIELDS = 512
_MAX_JSON_STRING_BYTES = 16_384
_MAX_JSON_TOTAL_NODES = 20_000


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
    template = (
        _TOKEN_METADATA_INDEX_TEMPLATE
        if endpoint_id == "token_metadata"
        else _CACHE_KEYS.get(endpoint_id)
    )
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
    if endpoint_id == "token_metadata":
        if not _SAFE_KEY_SEGMENT_RE.fullmatch(normalized_chain) or not _EVM_ADDRESS_RE.fullmatch(
            normalized_token
        ):
            return _result("CACHE_IDENTITY_INVALID")
        return _read_token_metadata_v2(
            redis_client,
            chain=normalized_chain,
            token=normalized_token,
            key=key,
            observed_at=observed_at,
            result_factory=_result,
        )
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
    elif isinstance(raw, str):
        raw_text = raw
        raw_bytes = raw_text.encode("utf-8")
    else:
        return _result("CACHE_TYPE_INVALID")
    if len(raw_bytes) > _MAX_CACHE_BYTES:
        return _result("CACHE_BYTE_LIMIT_EXCEEDED")
    try:
        envelope = json.loads(raw_text)
        _validate_closed_json(envelope)
    except (TypeError, ValueError, UnicodeError):
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


def _read_token_metadata_v2(
    redis_client: Any,
    *,
    chain: str,
    token: str,
    key: str,
    observed_at: datetime | None,
    result_factory: Callable[..., CanonicalCacheRead],
) -> CanonicalCacheRead:
    index_bytes, index, reason = _read_canonical_mapping(redis_client, key)
    if reason is not None:
        return result_factory(reason)
    index_sha256 = hashlib.sha256(index_bytes).hexdigest()
    if (
        index.get("schema_version") != "moralis_token_metadata_index_v2"
        or index.get("provider") != "moralis"
        or index.get("endpoint_id") != "token_metadata"
        or index.get("chain") != chain
        or index.get("token") != token
    ):
        return result_factory("CACHE_IDENTITY_MISMATCH", envelope_sha256=index_sha256)
    if not _all_authority_false(index):
        return result_factory("CACHE_AUTHORITY_SCOPE_INVALID", envelope_sha256=index_sha256)
    generated = _utc(index.get("generated_at"))
    expires = _utc(index.get("expires_at"))
    source_expires = _utc(index.get("source_artifact_expires_at"))
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    if generated is None or expires is None or source_expires is None:
        return result_factory("CACHE_TEMPORAL_CONTRACT_INVALID", envelope_sha256=index_sha256)
    if generated > now or expires > source_expires:
        return result_factory("CACHE_TEMPORAL_ORDER_INVALID", envelope_sha256=index_sha256)
    expires_text = expires.isoformat().replace("+00:00", "Z")
    if now >= expires:
        return result_factory(
            "CACHE_STALE",
            expires_at=expires_text,
            envelope_sha256=index_sha256,
        )
    manifest_key = index.get("manifest_key")
    manifest_sha256 = index.get("manifest_sha256")
    source_key = index.get("source_key")
    source_sha256 = index.get("source_payload_sha256")
    if not all(
        isinstance(value, str) and value
        for value in (manifest_key, manifest_sha256, source_key, source_sha256)
    ):
        return result_factory("CACHE_RECEIPT_BINDING_INVALID", envelope_sha256=index_sha256)
    if (
        not _redis_key_valid(str(manifest_key))
        or not _redis_key_valid(str(source_key))
        or not _SHA256_RE.fullmatch(str(manifest_sha256))
        or not _SHA256_RE.fullmatch(str(source_sha256))
        or manifest_key != f"{_TOKEN_METADATA_MANIFEST_PREFIX}:{source_sha256}"
    ):
        return result_factory("CACHE_RECEIPT_BINDING_INVALID", envelope_sha256=index_sha256)
    receipt = index.get("cache_receipt")
    if not isinstance(receipt, Mapping) or dict(receipt) != {
        "schema_version": "moralis_metadata_cache_receipt_v1",
        "scope": "NON_AUTHORITATIVE_METADATA_CACHE_ONLY",
        "source_exact_readback_verified": True,
        "manifest_exact_readback_verified": True,
        "source_key": source_key,
        "source_payload_sha256": source_sha256,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha256,
        "receipt_observed_at": index.get("generated_at"),
        "available_at": None,
        "publication_authority": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }:
        return result_factory("CACHE_RECEIPT_INVALID", envelope_sha256=index_sha256)
    manifest_bytes, manifest, reason = _read_canonical_mapping(redis_client, str(manifest_key))
    if reason is not None:
        return result_factory(f"MANIFEST_{reason}", envelope_sha256=index_sha256)
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        return result_factory("MANIFEST_SHA256_MISMATCH", envelope_sha256=index_sha256)
    if (
        manifest.get("schema_version") != "moralis_token_metadata_manifest_v2"
        or manifest.get("provider") != "moralis"
        or manifest.get("endpoint_id") != "token_metadata"
        or manifest.get("chain") != chain
        or manifest.get("token") != token
        or manifest.get("source_key") != source_key
        or manifest.get("source_payload_sha256") != source_sha256
        or not _all_authority_false(manifest)
    ):
        return result_factory("MANIFEST_IDENTITY_MISMATCH", envelope_sha256=index_sha256)
    source_bytes, source, reason = _read_canonical_mapping(redis_client, str(source_key))
    if reason is not None:
        return result_factory(f"SOURCE_{reason}", envelope_sha256=index_sha256)
    if hashlib.sha256(source_bytes).hexdigest() != source_sha256:
        return result_factory("SOURCE_SHA256_MISMATCH", envelope_sha256=index_sha256)
    if (
        source.get("schema_version") != "moralis_normalized_payload_v2"
        or source.get("provider") != "moralis"
        or source.get("endpoint_id") != "token_metadata"
        or _chain(source.get("chain")) != chain
        or str(source.get("token") or "").strip().lower() != token
        or not _all_authority_false(source)
    ):
        return result_factory("SOURCE_IDENTITY_MISMATCH", envelope_sha256=index_sha256)
    source_identity_material = {
        "schema_version": "moralis_source_identity_material_v2",
        "endpoint_id": "token_metadata",
        "group": "token_metadata",
        "chain": chain,
        "identity_kind": "token",
        "identity_value": token,
        "symbol": str(source.get("symbol") or "").strip().upper(),
    }
    source_identity = (
        "token_metadata:" + hashlib.sha256(_canonical_bytes(source_identity_material)).hexdigest()
    )
    expected_source_key = f"v2:moralis:raw:v2:{source_identity}:{source_sha256}"
    if source_key != expected_source_key:
        return result_factory("SOURCE_KEY_IDENTITY_MISMATCH", envelope_sha256=index_sha256)
    records = manifest.get("canonical_records")
    source_records = source.get("canonical_records")
    count = manifest.get("canonical_record_count")
    records_sha256 = manifest.get("canonical_records_sha256")
    if (
        not isinstance(records, list)
        or not records
        or len(records) > 250
        or any(not isinstance(row, Mapping) for row in records)
        or records != source_records
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(records)
        or not isinstance(records_sha256, str)
        or hashlib.sha256(_canonical_bytes(records)).hexdigest() != records_sha256
    ):
        return result_factory("CACHE_RECORDS_INVALID", envelope_sha256=index_sha256)
    try:
        index_ttl = redis_client.ttl(key)
        source_ttl = redis_client.ttl(str(source_key))
        manifest_ttl = redis_client.ttl(str(manifest_key))
    except Exception:
        return result_factory("CACHE_PROVENANCE_TTL_READ_FAILED", envelope_sha256=index_sha256)
    if not isinstance(index_ttl, int) or isinstance(index_ttl, bool) or index_ttl <= 0:
        return result_factory("CACHE_INDEX_EXPIRED", envelope_sha256=index_sha256)
    if any(
        not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0
        for ttl in (source_ttl, manifest_ttl)
    ):
        return result_factory("CACHE_PROVENANCE_EXPIRED", envelope_sha256=index_sha256)
    required_ttl = max(1, math.ceil((expires - now).total_seconds()))
    if any(ttl < required_ttl for ttl in (source_ttl, manifest_ttl)):
        return result_factory(
            "CACHE_PROVENANCE_TTL_SHORTER_THAN_INDEX_LIFETIME",
            envelope_sha256=index_sha256,
        )
    if index_ttl < required_ttl:
        return result_factory(
            "CACHE_INDEX_TTL_SHORTER_THAN_DECLARED_LIFETIME",
            envelope_sha256=index_sha256,
        )
    return result_factory(
        "READY",
        ready=True,
        records=tuple(dict(row) for row in records),
        available_at=None,
        expires_at=expires_text,
        envelope_sha256=index_sha256,
    )


def _read_canonical_mapping(
    redis_client: Any,
    key: str,
) -> tuple[bytes, dict[str, Any], str | None]:
    try:
        raw = redis_client.get(key)
    except Exception:
        return b"", {}, "CACHE_READ_FAILED"
    if raw is None:
        return b"", {}, "CACHE_MISSING"
    if isinstance(raw, bytes):
        raw_bytes = bytes(raw)
        try:
            raw_text = raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return b"", {}, "CACHE_UTF8_INVALID"
    elif isinstance(raw, str):
        raw_text = raw
        raw_bytes = raw.encode("utf-8")
    else:
        return b"", {}, "CACHE_TYPE_INVALID"
    if len(raw_bytes) > _MAX_CACHE_BYTES:
        return b"", {}, "CACHE_BYTE_LIMIT_EXCEEDED"
    try:
        parsed = json.loads(raw_text)
        canonical = _canonical_bytes(parsed)
    except (TypeError, ValueError, UnicodeError):
        return b"", {}, "CACHE_JSON_INVALID"
    if not isinstance(parsed, Mapping):
        return b"", {}, "CACHE_ENVELOPE_INVALID"
    if canonical != raw_bytes:
        return b"", {}, "CACHE_NOT_CANONICAL"
    return raw_bytes, dict(parsed), None


def _canonical_bytes(value: Any) -> bytes:
    _validate_closed_json(value)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_CACHE_BYTES:
        raise ValueError("cache byte limit exceeded")
    return encoded


def _validate_closed_json(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    node_budget: list[int] | None = None,
) -> None:
    if node_budget is None:
        node_budget = [_MAX_JSON_TOTAL_NODES]
    node_budget[0] -= 1
    if node_budget[0] < 0 or depth > _MAX_JSON_DEPTH:
        raise ValueError(f"{path}: cache JSON bound exceeded")
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite number")
        return
    if isinstance(value, str):
        if len(value.encode("utf-8", errors="strict")) > _MAX_JSON_STRING_BYTES:
            raise ValueError(f"{path}: string byte limit exceeded")
        if unicodedata.normalize("NFC", value) != value or any(
            unicodedata.category(char).startswith("C") for char in value
        ):
            raise ValueError(f"{path}: unsafe Unicode")
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_LIST_ITEMS:
            raise ValueError(f"{path}: list cardinality exceeded")
        for index, item in enumerate(value):
            _validate_closed_json(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    if isinstance(value, dict):
        if len(value) > _MAX_JSON_OBJECT_FIELDS:
            raise ValueError(f"{path}: object cardinality exceeded")
        for name, item in value.items():
            if not isinstance(name, str) or not name:
                raise TypeError(f"{path}: invalid object key")
            if len(name.encode("utf-8", errors="strict")) > _MAX_JSON_STRING_BYTES:
                raise ValueError(f"{path}: object key byte limit exceeded")
            if unicodedata.normalize("NFC", name) != name or any(
                unicodedata.category(char).startswith("C") for char in name
            ):
                raise ValueError(f"{path}: unsafe Unicode object key")
            _validate_closed_json(
                item,
                path=f"{path}.{name}",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    raise TypeError(f"{path}: unsupported cache JSON type")


def _all_authority_false(value: Mapping[str, Any]) -> bool:
    optional_false_claims = (
        "actual_consumption",
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_consumption",
        "orchestrator_consumption",
        "allocator_consumption",
        "paper_consumption",
        "live_dryrun_consumption",
        "feedback_attribution",
        "trainer_consumption_prerequisites_bound",
        "consumer_receipts_bound",
        "publication_atomic",
        "publication_committed",
        "consumer_eligible",
        "trainer_consumable",
        "trainer_admission_granted",
        "admitted_ready",
        "feature_bridge_ready",
        "provider_ready",
        "source_ready",
        "moralis_can_approve_trade_alone",
        "single_provider_can_approve",
        "provider_data_can_approve_trade_alone",
        "can_boost_confidence_modestly",
        "can_block_reduce_size_or_require_hedge",
        "live_execution_authorized",
        "exchange_action_taken",
        "places_real_order",
        "writes_exchange_orders",
        "valid_for_trainer",
        "valid_for_prediction",
        "valid_for_risk",
        "valid_for_orchestrator",
        "valid_for_allocator",
        "valid_for_paper",
        "valid_for_live",
    )
    return (
        all(
            value.get(name) is False
            for name in (
                "publication_authority",
                "trainer_authority",
                "prediction_authority",
                "risk_authority",
                "orchestrator_authority",
                "allocator_authority",
                "paper_authority",
                "live_authority",
            )
        )
        and value.get("postcommit_receipt_bound") is False
        and type(value.get("admitted_feature_count")) is int
        and value.get("admitted_feature_count") == 0
        and value.get("available_at") is None
        and all(name not in value or value.get(name) is False for name in optional_false_claims)
    )


def _redis_key_valid(value: str) -> bool:
    if len(value) > 512 or len(value.encode("ascii", errors="ignore")) != len(value):
        return False
    return all(_SAFE_KEY_SEGMENT_RE.fullmatch(segment) for segment in value.split(":"))


def _chain(value: object) -> str:
    raw = str(value or "").strip().lower()
    return str(MORALIS_EVM_CHAIN_ALIASES.get(raw, raw))


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
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
