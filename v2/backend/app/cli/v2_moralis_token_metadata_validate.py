"""Validate token-map contracts against live Moralis ERC20 metadata.

Reads every ``v2:moralis:token_map:{symbol}`` row that still carries
``NEEDS_METADATA_VALIDATION``, fetches the real token metadata from the
Moralis deep-index API (cheap batched call), and only marks a contract
VERIFIED (and therefore pollable) when the on-chain symbol and decimals
match the mapping. Mismatches become INVALID_METADATA_MISMATCH — never
silently accepted. Non-EVM chains (solana, native BTC/XRP) are marked
explicitly unsupported for this validation path rather than faked.

Read-only against exchanges; writes only V2 Redis token-map keys.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASE = "https://deep-index.moralis.io/api/v2.2"
USER_AGENT = "aibot-v2-moralis-client/1.0 (+python-urllib)"
EVM_CHAIN_PARAM = {"ethereum": "eth", "eth": "eth", "bsc": "bsc", "binance-smart-chain": "bsc",
                   "polygon": "polygon", "arbitrum": "arbitrum", "optimism": "optimism",
                   "base": "base", "avalanche": "avalanche"}
TOKEN_MAP_KEY = "v2:moralis:token_map:{symbol}"
TOKEN_MAP_STATUS_KEY = "v2:moralis:token_map_status"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_token_metadata_validate")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import bootstrap_process_env

        bootstrap_process_env(apply=True)
    except Exception:
        pass
    api_key = os.environ.get("MORALIS_API_KEY", "")
    if not api_key:
        print(json.dumps({"status": "BLOCKED", "reason": "MORALIS_API_KEY_ABSENT"}))
        return 2
    r = _redis_client(args.redis_url)
    report = validate_token_map(r, api_key=api_key)
    if args.output_dir:
        from pathlib import Path

        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "token_metadata_validation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: report[k] for k in ("verified_count", "mismatch_count", "unsupported_count", "pollable_count")}, sort_keys=True))
    return 0


def validate_token_map(r: Any, *, api_key: str) -> dict[str, Any]:
    now = _now()
    symbols = []
    by_chain: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    unsupported: list[dict[str, Any]] = []
    for key in r.scan_iter("v2:moralis:token_map:*", count=500):
        if key.endswith("_status"):
            continue
        row = _jget(r, key)
        if not isinstance(row, dict):
            continue
        symbols.append(row.get("symbol"))
        for contract in row.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            status = str(contract.get("tradeable_mapping_status") or "")
            chain = str(contract.get("chain") or "").lower()
            address = str(contract.get("contract_address") or "").lower()
            if status != "NEEDS_METADATA_VALIDATION" or not address:
                continue
            chain_param = EVM_CHAIN_PARAM.get(chain)
            if chain_param is None:
                contract["tradeable_mapping_status"] = "METADATA_VALIDATION_UNSUPPORTED_CHAIN"
                contract["metadata_verified"] = False
                unsupported.append({"symbol": row.get("symbol"), "chain": chain})
                continue
            by_chain.setdefault(chain_param, []).append((address, contract, row))

    verified = mismatched = 0
    for chain_param, entries in by_chain.items():
        addresses = [address for address, _, _ in entries]
        metadata = _fetch_metadata(api_key, chain=chain_param, addresses=addresses)
        for address, contract, row in entries:
            meta = metadata.get(address)
            if not meta:
                contract["tradeable_mapping_status"] = "METADATA_NOT_FOUND_ON_CHAIN"
                contract["metadata_verified"] = False
                mismatched += 1
                continue
            symbol_ok = str(meta.get("symbol") or "").upper() == str(contract.get("token_symbol") or "").upper()
            decimals_ok = (
                contract.get("decimals") is None
                or str(meta.get("decimals")) == str(contract.get("decimals"))
            )
            if symbol_ok and decimals_ok:
                contract["tradeable_mapping_status"] = "VERIFIED"
                contract["metadata_verified"] = True
                contract["manual_review_required"] = False
                contract["mapping_source"] = str(contract.get("mapping_source") or "") + "+moralis_metadata_verified"
                contract["token_name"] = meta.get("name") or contract.get("token_name")
                contract["decimals"] = int(meta.get("decimals")) if meta.get("decimals") is not None else contract.get("decimals")
                contract["pollable"] = (
                    bool(contract.get("moralis_supported"))
                    and bool(contract.get("token_endpoint_supported"))
                    and float(contract.get("mapping_confidence") or 0) >= 0.8
                )
                verified += 1
            else:
                contract["tradeable_mapping_status"] = "INVALID_METADATA_MISMATCH"
                contract["metadata_verified"] = False
                contract["pollable"] = False
                mismatched += 1

    # Re-publish updated rows
    pollable = 0
    for key in r.scan_iter("v2:moralis:token_map:*", count=500):
        if key.endswith("_status"):
            continue
        row = _jget(r, key)
        if not isinstance(row, dict):
            continue
        updated = False
        for chain_param, entries in by_chain.items():
            for address, contract, source_row in entries:
                if source_row.get("symbol") == row.get("symbol"):
                    row["contracts"] = source_row.get("contracts")
                    row["metadata_validated_utc"] = now
                    updated = True
        if updated:
            r.set(key, json.dumps(row, sort_keys=True, default=str), ex=7 * 86400)
        pollable += sum(1 for c in (row.get("contracts") or []) if isinstance(c, dict) and c.get("pollable"))

    status = _jget(r, TOKEN_MAP_STATUS_KEY) or {}
    status.update({
        "metadata_validated_utc": now,
        "metadata_verified_count": verified,
        "metadata_mismatch_count": mismatched,
        "metadata_unsupported_chain_count": len(unsupported),
        "pollable_token_count": pollable,
    })
    r.set(TOKEN_MAP_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=7 * 86400)
    return {
        "schema_version": "moralis_token_metadata_validation_v1",
        "generated_utc": now,
        "verified_count": verified,
        "mismatch_count": mismatched,
        "unsupported_count": len(unsupported),
        "unsupported": unsupported,
        "pollable_count": pollable,
        "raw_key_exposed": False,
    }


def _fetch_metadata(api_key: str, *, chain: str, addresses: list[str]) -> dict[str, dict[str, Any]]:
    if not addresses:
        return {}
    query = urllib.parse.urlencode([("chain", chain)] + [("addresses[]", a) for a in addresses[:25]])
    req = urllib.request.Request(
        f"{BASE}/erc20/metadata?{query}",
        headers={"X-API-Key": api_key, "accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload if isinstance(payload, list) else []:
        if isinstance(row, dict) and row.get("address"):
            out[str(row["address"]).lower()] = row
    return out


def _jget(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
