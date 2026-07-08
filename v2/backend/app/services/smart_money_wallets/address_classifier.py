"""Address exclusion and classification for Moralis wallet bootstrap."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


EXCLUDED_ADDRESSES_KEY = "v2:moralis:excluded_addresses"
ADDRESS_CLASSIFICATION_KEY = "v2:moralis:address_classification:{chain}:{address}"
CONFIG_DIR = Path(__file__).resolve().parents[4] / "config" / "moralis"
DEFAULT_EXCLUDED_PATH = CONFIG_DIR / "excluded_addresses.yaml"
DEFAULT_EXCHANGE_PATH = CONFIG_DIR / "exchange_wallets.yaml"
SMART_BLOCKING_CATEGORIES = {
    "burn_address",
    "bridge",
    "deployer",
    "exchange_cold_wallet",
    "exchange_hot_wallet",
    "lp_contract",
    "router",
    "token_contract",
    "unknown_contract",
    "vesting_contract",
}


def classify_address(
    *,
    chain: str,
    address: str,
    metadata: Mapping[str, Any] | None = None,
    excluded_path: Path | str = DEFAULT_EXCLUDED_PATH,
    exchange_path: Path | str = DEFAULT_EXCHANGE_PATH,
) -> dict[str, Any]:
    normalized_chain = _chain(chain)
    normalized_address = _address(address)
    configured = _configured_addresses(excluded_path=Path(excluded_path), exchange_path=Path(exchange_path))
    row = configured.get((normalized_chain, normalized_address)) or configured.get(("*", normalized_address))
    if row:
        category = str(row.get("category") or "excluded")
        return _payload(
            chain=normalized_chain,
            address=normalized_address,
            category=category,
            label=row.get("label"),
            source=row.get("source"),
            smart_wallet_eligible=False,
        )
    if bool((metadata or {}).get("is_contract")):
        return _payload(
            chain=normalized_chain,
            address=normalized_address,
            category="unknown_contract",
            label=(metadata or {}).get("label"),
            source="metadata_is_contract",
            smart_wallet_eligible=False,
        )
    return _payload(
        chain=normalized_chain,
        address=normalized_address,
        category="unknown",
        label=(metadata or {}).get("label") if metadata else None,
        source="not_in_exclusion_lists",
        smart_wallet_eligible=True,
    )


def publish_excluded_addresses(
    redis_client: Any,
    *,
    excluded_path: Path | str = DEFAULT_EXCLUDED_PATH,
    exchange_path: Path | str = DEFAULT_EXCHANGE_PATH,
    ttl_seconds: int = 6 * 3600,
) -> dict[str, Any]:
    configured = _configured_addresses(excluded_path=Path(excluded_path), exchange_path=Path(exchange_path))
    rows = []
    keys_written = []
    for (chain, address), row in configured.items():
        payload = _payload(
            chain=chain,
            address=address,
            category=str(row.get("category") or "excluded"),
            label=row.get("label"),
            source=row.get("source"),
            smart_wallet_eligible=False,
        )
        key = ADDRESS_CLASSIFICATION_KEY.format(chain=chain, address=address)
        redis_client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
        keys_written.append(key)
        rows.append(payload)
    status = {
        "schema_version": "moralis_excluded_addresses_status_v1",
        "status": "EXCLUSION_LIST_READY",
        "generated_utc": _now(),
        "excluded_count": len(rows),
        "categories": sorted({row["category"] for row in rows}),
        "exchange_wallet_count": sum(1 for row in rows if str(row["category"]).startswith("exchange_")),
        "exchange_wallets_are_smart_money": False,
        "contract_wallets_are_smart_wallets": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
        "rows": rows,
    }
    redis_client.set(EXCLUDED_ADDRESSES_KEY, json.dumps(status, sort_keys=True, default=str), ex=ttl_seconds)
    status["keys_written"] = [*keys_written, EXCLUDED_ADDRESSES_KEY]
    return status


def _configured_addresses(*, excluded_path: Path, exchange_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for path, default_category in ((excluded_path, "excluded"), (exchange_path, "exchange_hot_wallet")):
        payload = _load_json_yaml(path)
        for row in payload.get("addresses") or []:
            if not isinstance(row, Mapping):
                continue
            chain = _chain(row.get("chain") or "*")
            address = _address(row.get("address"))
            if not address:
                continue
            out[(chain, address)] = {
                "category": row.get("category") or default_category,
                "label": row.get("label"),
                "source": row.get("source") or str(path),
            }
    return out


def _payload(
    *,
    chain: str,
    address: str,
    category: str,
    label: Any,
    source: Any,
    smart_wallet_eligible: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "moralis_address_classification_v1",
        "chain": chain,
        "address": address,
        "category": category,
        "label": None if label is None else str(label),
        "source": None if source is None else str(source),
        "smart_wallet_eligible": bool(smart_wallet_eligible and category not in SMART_BLOCKING_CATEGORIES),
        "counts_as_smart_money": bool(smart_wallet_eligible and category not in SMART_BLOCKING_CATEGORIES),
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _load_json_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"addresses": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be JSON-compatible YAML for stdlib parsing") from exc
    return payload if isinstance(payload, dict) else {"addresses": []}


def _chain(value: Any) -> str:
    return str(value or "").strip().lower()


def _address(value: Any) -> str:
    return str(value or "").strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
