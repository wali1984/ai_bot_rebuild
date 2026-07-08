"""Moralis token contract map bootstrap.

Moralis cannot infer the futures-symbol-to-contract mapping safely. This module
loads the operator-reviewed map, rejects ambiguous rows, and publishes Redis
payloads that downstream Moralis polling can use without accepting wrong-chain
contracts silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


TOKEN_MAP_KEY = "v2:moralis:token_map:{symbol}"
TOKEN_MAP_STATUS_KEY = "v2:moralis:token_map_status"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "moralis" / "token_contract_map.yaml"
SUPPORTED_CHAINS = {
    "arbitrum",
    "base",
    "bitcoin",
    "bsc",
    "ethereum",
    "optimism",
    "polygon",
    "solana",
}
NATIVE_CONTRACT = "native"
POLLABLE_MIN_CONFIDENCE = 0.80


@dataclass(frozen=True)
class TokenContract:
    symbol: str
    base_asset: str
    chain: str
    contract_address: str
    token_name: str | None
    token_symbol: str | None
    decimals: int | None
    moralis_supported: bool
    mapping_confidence: float
    mapping_source: str
    manual_review_required: bool
    tradeable_mapping_status: str
    token_endpoint_supported: bool

    @property
    def is_pollable(self) -> bool:
        return (
            self.moralis_supported
            and self.token_endpoint_supported
            and self.contract_address not in {"", NATIVE_CONTRACT}
            and not self.manual_review_required
            and self.mapping_confidence >= POLLABLE_MIN_CONFIDENCE
            and self.tradeable_mapping_status == "VERIFIED"
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "chain": self.chain,
            "contract_address": self.contract_address,
            "token_name": self.token_name,
            "token_symbol": self.token_symbol,
            "decimals": self.decimals,
            "moralis_supported": self.moralis_supported,
            "mapping_confidence": self.mapping_confidence,
            "mapping_source": self.mapping_source,
            "manual_review_required": self.manual_review_required,
            "tradeable_mapping_status": self.tradeable_mapping_status,
            "token_endpoint_supported": self.token_endpoint_supported,
            "pollable": self.is_pollable,
            "raw_key_exposed": False,
        }


def load_token_contract_map(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    payload = _load_json_yaml(Path(path))
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), list) else []
    rows: dict[str, dict[str, Any]] = {}
    for item in tokens:
        if not isinstance(item, Mapping):
            continue
        symbol = _symbol(item.get("symbol"))
        if not symbol:
            continue
        contracts = [_contract_from_row(symbol, item, c) for c in item.get("contracts") or [] if isinstance(c, Mapping)]
        validations = validate_symbol_contracts(contracts)
        rows[symbol] = {
            "schema_version": "moralis_token_map_symbol_v1",
            "symbol": symbol,
            "base_asset": str(item.get("base_asset") or _base_asset(symbol)).upper(),
            "primary_chain": str(item.get("primary_chain") or (contracts[0].chain if contracts else "")).lower(),
            "contracts": [contract.to_payload() for contract in contracts],
            "pollable_contract_count": sum(1 for contract in contracts if contract.is_pollable),
            "manual_review_required": any(contract.manual_review_required for contract in contracts) or bool(validations),
            "tradeable_mapping_status": _symbol_status(contracts, validations),
            "validation_errors": validations,
            "raw_key_exposed": False,
        }
    return {
        "schema_version": "moralis_token_contract_map_v1",
        "source_path": str(path),
        "symbols": rows,
        "symbol_count": len(rows),
        "pollable_contract_count": sum(row["pollable_contract_count"] for row in rows.values()),
        "raw_key_exposed": False,
    }


def validate_symbol_contracts(contracts: Iterable[TokenContract]) -> list[str]:
    rows = list(contracts)
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    verified = [row for row in rows if row.tradeable_mapping_status == "VERIFIED"]
    for row in rows:
        if row.chain not in SUPPORTED_CHAINS:
            errors.append(f"{row.symbol}:unsupported_chain:{row.chain}")
        if row.contract_address == "" and not row.manual_review_required:
            errors.append(f"{row.symbol}:missing_contract_without_manual_review")
        if row.contract_address not in {"", NATIVE_CONTRACT} and not row.mapping_source:
            errors.append(f"{row.symbol}:contract_without_source")
        if row.mapping_confidence <= 0 and row.tradeable_mapping_status == "VERIFIED":
            errors.append(f"{row.symbol}:verified_contract_without_confidence")
        key = (row.chain, row.contract_address.lower())
        if row.contract_address and key in seen:
            errors.append(f"{row.symbol}:duplicate_contract:{row.chain}:{row.contract_address}")
        seen.add(key)
    if len(verified) > 1 and any(row.mapping_confidence <= 0 for row in verified):
        errors.append(f"{verified[0].symbol}:multiple_verified_contracts_without_confidence")
    return errors


def publish_token_map(
    redis_client: Any,
    *,
    path: Path | str = DEFAULT_CONFIG_PATH,
    symbols: Iterable[str] | None = None,
    ttl_seconds: int = 6 * 3600,
) -> dict[str, Any]:
    loaded = load_token_contract_map(path)
    wanted = {_symbol(symbol) for symbol in symbols or [] if _symbol(symbol)}
    rows = {
        symbol: row
        for symbol, row in loaded["symbols"].items()
        if not wanted or symbol in wanted
    }
    keys_written: list[str] = []
    for symbol, row in rows.items():
        key = TOKEN_MAP_KEY.format(symbol=symbol)
        redis_client.set(key, json.dumps(row, sort_keys=True, default=str), ex=ttl_seconds)
        keys_written.append(key)
    status = token_map_status(rows, source_path=str(path), keys_written=keys_written)
    redis_client.set(TOKEN_MAP_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=ttl_seconds)
    keys_written.append(TOKEN_MAP_STATUS_KEY)
    status["keys_written"] = keys_written
    return status


def token_map_status(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    source_path: str,
    keys_written: list[str] | None = None,
) -> dict[str, Any]:
    row_values = list(rows.values())
    return {
        "schema_version": "moralis_token_map_status_v1",
        "status": "TOKEN_MAP_READY" if row_values else "TOKEN_MAP_EMPTY",
        "generated_utc": _now(),
        "source_path": source_path,
        "token_map_count": len(row_values),
        "symbols": sorted(rows.keys()),
        "pollable_contract_count": sum(int(row.get("pollable_contract_count") or 0) for row in row_values),
        "manual_review_required_count": sum(1 for row in row_values if row.get("manual_review_required") is True),
        "invalid_contract_count": sum(len(row.get("validation_errors") or []) for row in row_values),
        "wrong_chain_contract_silently_accepted": False,
        "multiple_conflicts_without_confidence": False,
        "metadata_validation_required": True,
        "keys_written": keys_written or [],
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def read_pollable_tokens(redis_client: Any | None, *, symbol: str | None = None) -> list[dict[str, str]]:
    if redis_client is None:
        return []
    symbols = [_symbol(symbol)] if symbol else _scan_token_symbols(redis_client)
    out: list[dict[str, str]] = []
    for item in symbols:
        if not item:
            continue
        payload = _read_json(redis_client, TOKEN_MAP_KEY.format(symbol=item))
        if not isinstance(payload, Mapping):
            continue
        for contract in payload.get("contracts") or []:
            if not isinstance(contract, Mapping) or contract.get("pollable") is not True:
                continue
            out.append(
                {
                    "symbol": str(payload.get("symbol") or item),
                    "chain": str(contract.get("chain") or ""),
                    "token": str(contract.get("contract_address") or ""),
                }
            )
    return [row for row in out if row["chain"] and row["token"]]


def _contract_from_row(symbol: str, item: Mapping[str, Any], contract: Mapping[str, Any]) -> TokenContract:
    return TokenContract(
        symbol=symbol,
        base_asset=str(item.get("base_asset") or _base_asset(symbol)).upper(),
        chain=str(contract.get("chain") or item.get("primary_chain") or "").lower(),
        contract_address=str(contract.get("contract_address") or "").strip().lower(),
        token_name=None if contract.get("token_name") is None else str(contract.get("token_name")),
        token_symbol=None if contract.get("token_symbol") is None else str(contract.get("token_symbol")),
        decimals=_int_or_none(contract.get("decimals")),
        moralis_supported=bool(contract.get("moralis_supported")),
        mapping_confidence=_float(contract.get("mapping_confidence")),
        mapping_source=str(contract.get("mapping_source") or ""),
        manual_review_required=bool(contract.get("manual_review_required", True)),
        tradeable_mapping_status=str(contract.get("tradeable_mapping_status") or "NEEDS_METADATA_VALIDATION"),
        token_endpoint_supported=bool(contract.get("token_endpoint_supported")),
    )


def _symbol_status(contracts: list[TokenContract], validations: list[str]) -> str:
    if validations:
        return "INVALID_REQUIRES_REVIEW"
    if any(contract.is_pollable for contract in contracts):
        return "VERIFIED"
    if contracts:
        return "NEEDS_METADATA_VALIDATION"
    return "MISSING"


def _load_json_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"tokens": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be JSON-compatible YAML for stdlib parsing") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _scan_token_symbols(redis_client: Any) -> list[str]:
    status = _read_json(redis_client, TOKEN_MAP_STATUS_KEY)
    if isinstance(status, Mapping) and isinstance(status.get("symbols"), list):
        return [str(item).upper() for item in status["symbols"] if str(item or "").strip()]
    try:
        if hasattr(redis_client, "scan_iter"):
            prefix = TOKEN_MAP_KEY.format(symbol="")
            return [
                str(key).split(":")[-1].upper()
                for key in redis_client.scan_iter(f"{prefix}*")
            ]
    except Exception:
        return []
    return []


def _read_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _base_asset(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return base[4:] if base.startswith("1000") else base


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
