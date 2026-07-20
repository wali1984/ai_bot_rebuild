"""Moralis wallet watchlist bootstrap and Redis contract."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.smart_money_wallets.address_classifier import classify_address
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_EVM_CHAIN_ALIASES,
    MORALIS_EVM_CHAIN_PARAMS,
)

WALLET_WATCHLIST_KEY = "v2:moralis:wallet_watchlist"
WALLET_WATCHLIST_STATUS_KEY = "v2:moralis:wallet_watchlist_status"
WALLET_PROFILE_KEY = "v2:moralis:wallet_profile:{chain}:{address}"
WALLET_ACTIVITY_KEY = "v2:moralis:wallet_activity:{chain}:{address}"
DEFAULT_SEED_PATH = Path(__file__).resolve().parents[4] / "config" / "moralis" / "wallet_watchlist_seed.yaml"
TIER_LIMITS = {"T0": 50, "T1": 250}
_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}")


def load_wallet_watchlist_seed(path: Path | str = DEFAULT_SEED_PATH) -> list[dict[str, Any]]:
    payload = _load_json_yaml(Path(path))
    rows = []
    for row in payload.get("wallets") or []:
        if not isinstance(row, Mapping):
            continue
        chain = str(row.get("chain") or "").lower()
        address = str(row.get("address") or "").lower()
        tier = str(row.get("tier") or "T2").upper()
        source = str(row.get("source") or "").strip()
        if not chain or not address or not source:
            continue
        classification = classify_address(chain=chain, address=address, metadata=row.get("metadata") or {})
        if classification.get("smart_wallet_eligible") is not True:
            continue
        rows.append(
            {
                "chain": chain,
                "address": address,
                "tier": tier if tier in {"T0", "T1", "T2"} else "T2",
                "source": source,
                "label": row.get("label"),
                "bootstrap_status": "SEEDED_NOT_VERIFIED",
                "classification": classification,
                "raw_key_exposed": False,
            }
        )
    return _apply_tier_limits(rows)


def publish_wallet_watchlist(
    redis_client: Any,
    *,
    path: Path | str = DEFAULT_SEED_PATH,
    ttl_seconds: int = 6 * 3600,
) -> dict[str, Any]:
    rows = load_wallet_watchlist_seed(path)
    status = wallet_watchlist_status(rows, source_path=str(path))
    payload = {
        "schema_version": "moralis_wallet_watchlist_v1",
        "generated_utc": _now(),
        "rows": rows,
        **{k: v for k, v in status.items() if k not in {"schema_version", "rows"}},
    }
    redis_client.set(WALLET_WATCHLIST_KEY, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
    redis_client.set(WALLET_WATCHLIST_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=ttl_seconds)
    status["keys_written"] = [WALLET_WATCHLIST_KEY, WALLET_WATCHLIST_STATUS_KEY]
    return status


def wallet_watchlist_status(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_path: str,
) -> dict[str, Any]:
    counts = {tier: sum(1 for row in rows if row.get("tier") == tier) for tier in ("T0", "T1", "T2")}
    total = len(rows)
    return {
        "schema_version": "moralis_wallet_watchlist_status_v1",
        "status": "WATCHLIST_READY" if total else "CONFIGURED_NO_WATCHLIST",
        "dashboard_color": "YELLOW" if total else "GRAY",
        "generated_utc": _now(),
        "source_path": source_path,
        "wallet_watchlist_count": total,
        "tier_counts": counts,
        "t0_max_wallets": TIER_LIMITS["T0"],
        "t1_max_wallets": TIER_LIMITS["T1"],
        "empty_wallet_list_marked_green": False,
        "wallets_added_without_source": False,
        "starter_budget_supported": total <= (TIER_LIMITS["T0"] + TIER_LIMITS["T1"]),
        "unknown_wallet_called_smart_money": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def read_wallet_watchlist(
    redis_client: Any | None,
    *,
    path: Path | str = DEFAULT_SEED_PATH,
) -> list[dict[str, str]]:
    if redis_client is None:
        return []
    payload = _read_json(redis_client, WALLET_WATCHLIST_KEY)
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "moralis_wallet_watchlist_v1"
        or payload.get("status") != "WATCHLIST_READY"
    ):
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    try:
        expected_path = Path(path).resolve(strict=False)
        published_path = Path(str(payload.get("source_path") or "")).resolve(
            strict=False
        )
        authoritative_rows = load_wallet_watchlist_seed(expected_path)
    except (OSError, RuntimeError, ValueError):
        return []
    if published_path != expected_path:
        return []
    authoritative_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for seed_row in authoritative_rows:
        identity = (
            _evm_chain(seed_row.get("chain")),
            str(seed_row.get("address") or "").strip().lower(),
        )
        if identity in authoritative_by_identity:
            return []
        authoritative_by_identity[identity] = seed_row
    if (
        type(payload.get("wallet_watchlist_count")) is not int
        or payload.get("wallet_watchlist_count") != len(authoritative_rows)
        or len(rows) != len(authoritative_rows)
    ):
        return []
    out: list[dict[str, str]] = []
    seen_identities: set[tuple[str, str]] = set()
    for row in rows or []:
        if not isinstance(row, Mapping):
            return []
        chain = _evm_chain(row.get("chain"))
        address = str(row.get("address") or "").strip().lower()
        identity = (chain, address)
        tier = str(row.get("tier") or "T2").upper()
        source = str(row.get("source") or "").strip()
        classification = row.get("classification")
        expected_row = authoritative_by_identity.get(identity)
        if (
            chain not in MORALIS_EVM_CHAIN_PARAMS
            or _EVM_ADDRESS.fullmatch(address) is None
            or identity in seen_identities
            or tier not in {"T0", "T1", "T2"}
            or not source
            or expected_row is None
            or dict(row) != expected_row
            or row.get("bootstrap_status") != "SEEDED_NOT_VERIFIED"
            or not isinstance(classification, Mapping)
            or classification.get("schema_version") != "moralis_address_classification_v1"
            or _evm_chain(classification.get("chain")) != chain
            or str(classification.get("address") or "").strip().lower() != address
            or classification.get("smart_wallet_eligible") is not True
            or classification.get("counts_as_smart_money") is not False
            or not str(classification.get("source") or "").strip()
        ):
            return []
        seen_identities.add(identity)
        out.append(
            {
                "chain": chain,
                "address": address,
                "tier": tier,
                "source": source,
            }
        )
    if seen_identities != set(authoritative_by_identity):
        return []
    return out


def watchlist_counts(redis_client: Any | None) -> dict[str, Any]:
    payload = _read_json(redis_client, WALLET_WATCHLIST_STATUS_KEY) if redis_client is not None else None
    if isinstance(payload, Mapping):
        return {
            "status": payload.get("status") or "CONFIGURED_NO_WATCHLIST",
            "wallet_watchlist_count": int(payload.get("wallet_watchlist_count") or 0),
            "tier_counts": payload.get("tier_counts") or {},
        }
    return {
        "status": "CONFIGURED_NO_WATCHLIST",
        "wallet_watchlist_count": 0,
        "tier_counts": {"T0": 0, "T1": 0, "T2": 0},
    }


def _apply_tier_limits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = {"T0": 0, "T1": 0, "T2": 0}
    for row in rows:
        tier = str(row.get("tier") or "T2").upper()
        limit = TIER_LIMITS.get(tier)
        if limit is not None and counts[tier] >= limit:
            continue
        counts[tier] += 1
        out.append(row)
    return out


def _load_json_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"wallets": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be JSON-compatible YAML for stdlib parsing") from exc
    return payload if isinstance(payload, dict) else {"wallets": []}


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _evm_chain(value: object) -> str:
    raw = str(value or "").strip().lower()
    return MORALIS_EVM_CHAIN_ALIASES.get(raw, raw)
