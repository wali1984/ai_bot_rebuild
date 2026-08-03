"""Cache and Redis write contracts for V2 alternative-data scaffold."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ALLOWED_PROVIDER_STATUS_KEY = "v2:altdata:provider_status"
SYMBOL_SCORE_PREFIX = "v2:altdata:symbol_score:"
SYMBOL_UNIVERSE_KEY = "v2:symbol_universe:altdata_candidates"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def allowed_altdata_write_key(key: str) -> bool:
    return (
        key == ALLOWED_PROVIDER_STATUS_KEY
        or key == SYMBOL_UNIVERSE_KEY
        or key.startswith(SYMBOL_SCORE_PREFIX)
    )


def safe_redis_set(redis_client: Any, key: str, payload: dict[str, Any], *, ex: int = 600) -> bool:
    if redis_client is None:
        return False
    if not allowed_altdata_write_key(key):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True), ex=ex)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class CacheContract:
    provider_id: str
    symbol: str | None
    key: str
    ttl_seconds: int | None
    missing_flag_required: bool = True
    stale_flag_required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "symbol": self.symbol,
            "key": self.key,
            "ttl_seconds": self.ttl_seconds,
            "missing_flag_required": self.missing_flag_required,
            "stale_flag_required": self.stale_flag_required,
        }


def build_cache_contracts(symbols: tuple[str, ...]) -> dict[str, Any]:
    rows: list[CacheContract] = [
        CacheContract("provider_status", None, ALLOWED_PROVIDER_STATUS_KEY, 600),
        CacheContract("symbol_universe", None, SYMBOL_UNIVERSE_KEY, 600),
    ]
    for symbol in symbols:
        rows.append(
            CacheContract(
                "symbol_score",
                symbol,
                f"{SYMBOL_SCORE_PREFIX}{symbol}",
                600,
            )
        )
    return {
        "schema_version": "v2_alternative_data_cache_contract_v1",
        "generated_utc": utc_iso(),
        "allowed_write_keys": [row.key for row in rows],
        "contracts": [row.as_dict() for row in rows],
        "writes_old_redis": False,
    }

