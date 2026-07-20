"""Validate token-map contracts from the canonical Moralis metadata cache.

Reads every ``v2:moralis:token_map:{symbol}`` row that still carries
``NEEDS_METADATA_VALIDATION``, reads the canonical scheduler's CU-accounted
metadata envelope, and only marks a contract
VERIFIED (and therefore pollable) when the on-chain symbol and decimals
match the mapping. Mismatches become INVALID_METADATA_MISMATCH — never
silently accepted. Non-EVM chains (solana, native BTC/XRP) are marked
explicitly unsupported for this validation path rather than faked.

Read-only against exchanges; writes only V2 Redis token-map keys.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.smart_money_wallets.canonical_cache import read_canonical_records
from app.services.smart_money_wallets.endpoint_registry import MORALIS_EVM_CHAIN_ALIASES
from app.services.smart_money_wallets.token_contract_mapper import (
    read_metadata_validation_tokens,
)

TOKEN_MAP_KEY = "v2:moralis:token_map:{symbol}"  # noqa: S105 - Redis key template
TOKEN_MAP_STATUS_KEY = "v2:moralis:token_map_status"  # noqa: S105 - Redis key name
_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_token_metadata_validate")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import (  # type: ignore[import-untyped]
            bootstrap_process_env,
        )

        bootstrap_process_env(apply=True)
    except Exception:  # noqa: S110 - optional environment bootstrap
        pass
    r = _redis_client(args.redis_url)
    report = validate_token_map(r)
    if args.output_dir:
        from pathlib import Path

        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "token_metadata_validation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    summary_keys = (
        "verified_count",
        "mismatch_count",
        "unsupported_count",
        "pollable_count",
    )
    print(json.dumps({key: report[key] for key in summary_keys}, sort_keys=True))
    return 0


def validate_token_map(r: Any, *, api_key: str = "") -> dict[str, Any]:
    # Retained only for backwards-compatible callers.  This workflow owns no
    # transport; the canonical scheduler is the sole API-key/CU/RPS authority.
    del api_key
    now = _now()
    unsupported: list[dict[str, Any]] = []
    cache_pending: list[dict[str, Any]] = []
    verified = mismatched = 0
    rows_by_key: dict[str, dict[str, Any]] = {}
    source_bound_candidates = {
        (
            str(candidate.get("symbol") or "").strip().upper(),
            str(candidate.get("chain") or "").strip().lower(),
            str(candidate.get("token") or "").strip().lower(),
        )
        for candidate in read_metadata_validation_tokens(r)
    }
    for raw_key in r.scan_iter("v2:moralis:token_map:*", count=500):
        key = _text(raw_key)
        if key.endswith("_status"):
            continue
        row = _jget(r, key)
        if not isinstance(row, dict):
            continue
        rows_by_key[key] = row
        for contract in row.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            contract_status = str(contract.get("tradeable_mapping_status") or "")
            chain = str(contract.get("chain") or "").lower()
            address = str(contract.get("contract_address") or "").lower()
            if (
                contract.get("moralis_supported") is not True
                or contract.get("token_endpoint_supported") is not True
                or _EVM_ADDRESS.fullmatch(address) is None
            ):
                contract["pollable"] = False
                continue
            if contract_status in {
                "INVALID_METADATA_MISMATCH",
                "METADATA_VALIDATION_UNSUPPORTED_CHAIN",
            } or not address:
                continue
            chain_param = MORALIS_EVM_CHAIN_ALIASES.get(chain)
            if chain_param is None:
                contract["tradeable_mapping_status"] = "METADATA_VALIDATION_UNSUPPORTED_CHAIN"
                contract["metadata_verified"] = False
                contract["pollable"] = False
                unsupported.append({"symbol": row.get("symbol"), "chain": chain})
                continue
            source_identity = (
                str(row.get("symbol") or "").strip().upper(),
                chain_param,
                address,
            )
            if source_identity not in source_bound_candidates:
                # Redis is a cache, not token-map authority. A row that cannot
                # be re-derived from the reviewed repository map must not be
                # promoted merely because it points at a plausible cache row.
                contract["pollable"] = False
                continue
            cache = read_canonical_records(
                r,
                endpoint_id="token_metadata",
                chain=chain_param,
                token=address,
            )
            if not cache.ready:
                cache_pending.append(
                    {
                        "symbol": row.get("symbol"),
                        "chain": chain_param,
                        "reason": cache.reason,
                    }
                )
                contract["pollable"] = False
                continue
            meta = next(
                (
                    item
                    for item in cache.records
                    if str(item.get("address") or "").lower() == address
                ),
                None,
            )
            if meta is None:
                cache_pending.append(
                    {
                        "symbol": row.get("symbol"),
                        "chain": chain_param,
                        "reason": "CACHE_METADATA_ADDRESS_MISSING",
                    }
                )
                contract["pollable"] = False
                continue
            symbol_ok = str(meta.get("symbol") or "").upper() == str(
                contract.get("token_symbol") or ""
            ).upper()
            metadata_decimals = _token_decimals(meta.get("decimals"))
            expected_decimals = _token_decimals(contract.get("decimals"))
            confidence = _finite_float(contract.get("mapping_confidence"))
            confidence_ok = confidence is not None and confidence >= 0.8
            decimals_ok = metadata_decimals is not None and (
                contract.get("decimals") is None
                or (
                    expected_decimals is not None
                    and metadata_decimals == expected_decimals
                )
            )
            if symbol_ok and decimals_ok and confidence_ok:
                contract["tradeable_mapping_status"] = "VERIFIED"
                contract["metadata_verified"] = True
                contract["manual_review_required"] = False
                source = str(contract.get("mapping_source") or "")
                if not source.endswith("+moralis_metadata_verified"):
                    source += "+moralis_metadata_verified"
                contract["mapping_source"] = source
                contract["token_name"] = meta.get("name") or contract.get("token_name")
                contract["decimals"] = metadata_decimals
                contract["metadata_evidence_key"] = cache.key
                contract["metadata_evidence_available_at"] = cache.available_at
                contract["metadata_evidence_expires_at"] = cache.expires_at
                contract["metadata_evidence_sha256"] = cache.envelope_sha256
                contract["pollable"] = (
                    bool(contract.get("moralis_supported"))
                    and bool(contract.get("token_endpoint_supported"))
                    and confidence_ok
                )
                verified += 1
            elif symbol_ok and decimals_ok:
                contract["tradeable_mapping_status"] = "INVALID_MAPPING_CONFIDENCE"
                contract["metadata_verified"] = False
                contract["manual_review_required"] = True
                contract["pollable"] = False
            else:
                contract["tradeable_mapping_status"] = "INVALID_METADATA_MISMATCH"
                contract["metadata_verified"] = False
                contract["pollable"] = False
                mismatched += 1

    # Re-publish updated rows with row-level claims re-derived from contracts.
    pollable = 0
    manual_review_required_count = 0
    metadata_validation_required = False
    for key, row in rows_by_key.items():
        contracts = [item for item in row.get("contracts") or [] if isinstance(item, dict)]
        row_pollable = sum(1 for item in contracts if item.get("pollable") is True)
        row["pollable_contract_count"] = row_pollable
        row["manual_review_required"] = any(
            item.get("manual_review_required") is True for item in contracts
        ) or bool(row.get("validation_errors"))
        row["tradeable_mapping_status"] = (
            "VERIFIED"
            if row_pollable > 0 and not row["manual_review_required"]
            else "NEEDS_METADATA_VALIDATION"
        )
        row["metadata_validated_utc"] = now
        r.set(key, json.dumps(row, sort_keys=True, default=str), ex=7 * 86400)
        pollable += row_pollable
        manual_review_required_count += int(row["manual_review_required"] is True)
        metadata_validation_required = metadata_validation_required or any(
            item.get("tradeable_mapping_status") == "NEEDS_METADATA_VALIDATION"
            for item in contracts
        )

    loaded_status = _jget(r, TOKEN_MAP_STATUS_KEY)
    status_payload: dict[str, Any] = (
        dict(loaded_status) if isinstance(loaded_status, Mapping) else {}
    )
    status_payload.update(
        {
            "metadata_validated_utc": now,
            "metadata_verified_count": verified,
            "metadata_mismatch_count": mismatched,
            "metadata_unsupported_chain_count": len(unsupported),
            "metadata_cache_pending_count": len(cache_pending),
            "pollable_token_count": pollable,
            # Replace bootstrap-era counts atomically with the claims derived
            # from the exact canonical metadata cache read above.  Leaving the
            # old zeros/manual-review flags in place makes an operationally
            # verified map contradict its own status payload.
            "pollable_contract_count": pollable,
            "manual_review_required_count": manual_review_required_count,
            "metadata_validation_required": metadata_validation_required,
        }
    )
    r.set(
        TOKEN_MAP_STATUS_KEY,
        json.dumps(status_payload, sort_keys=True, default=str),
        ex=7 * 86400,
    )
    return {
        "schema_version": "moralis_token_metadata_validation_v1",
        "generated_utc": now,
        "verified_count": verified,
        "mismatch_count": mismatched,
        "unsupported_count": len(unsupported),
        "unsupported": unsupported,
        "cache_pending_count": len(cache_pending),
        "cache_pending": cache_pending,
        "pollable_count": pollable,
        "transport_owner": "CANONICAL_PROVIDER_SCHEDULER",
        "http_request_count": 0,
        "compute_units_spent": 0,
        "raw_key_exposed": False,
    }


def _jget(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _token_decimals(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        return None
    return parsed if 0 <= parsed <= 255 else None


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _redis_client(redis_url: str) -> Any:
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
