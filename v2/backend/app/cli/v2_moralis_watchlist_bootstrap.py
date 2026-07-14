"""Bootstrap Moralis wallet watchlist from A+ candidate inventory.

This script populates the Moralis wallet watchlist to enable feature bridge
from candidate symbols, enabling smart money feature consumption for A-grade
candidate evaluation.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis

logger = logging.getLogger(__name__)

MORALIS_WATCHLIST_KEY = "v2:provider:moralis:wallet_watchlist"
MORALIS_TOKEN_MAP_KEY = "v2:provider:moralis:token_map"
A_PLUS_INVENTORY_KEY = "v2:orchestrator:a_plus_candidate_inventory"


def load_a_plus_candidates(redis_client: redis.Redis) -> list[str]:
    """Load A+ candidate symbols from orchestrator inventory."""
    try:
        payload = redis_client.get(A_PLUS_INVENTORY_KEY)
        if not payload:
            logger.warning(f"No A+ candidate inventory at {A_PLUS_INVENTORY_KEY}")
            return []
        data = json.loads(payload)
        symbols = data.get("symbols", []) or []
        return [str(s).upper() for s in symbols if s]
    except Exception as e:
        logger.error(f"Failed to load A+ candidates: {e}")
        return []


def load_stable_wallets(redis_client: redis.Redis) -> dict[str, list[str]]:
    """Load known stable whale wallets per symbol from local config."""
    config_path = os.path.join(
        os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"),
        "v2", "config", "moralis", "wallet_watchlist_seed.yaml"
    )
    try:
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("wallets_by_symbol", {})
    except Exception as e:
        logger.warning(f"Failed to load wallet config: {e}")
        return {}


def load_token_addresses(redis_client: redis.Redis) -> dict[str, str]:
    """Load token contract addresses for Moralis lookups."""
    try:
        payload = redis_client.get(MORALIS_TOKEN_MAP_KEY)
        if not payload:
            logger.warning(f"No token map at {MORALIS_TOKEN_MAP_KEY}")
            return {}
        data = json.loads(payload)
        return data.get("token_addresses", {}) or {}
    except Exception as e:
        logger.error(f"Failed to load token map: {e}")
        return {}


def bootstrap_moralis_watchlist(
    redis_client: redis.Redis,
    *,
    force: bool = False,
    max_wallets_per_symbol: int = 10,
) -> dict[str, Any]:
    """Bootstrap Moralis watchlist from A+ candidates and stable wallets."""
    # Check if already bootstrapped
    existing = redis_client.get(MORALIS_WATCHLIST_KEY)
    if existing and not force:
        try:
            data = json.loads(existing)
            logger.info(f"Watchlist already populated: {len(data.get('wallet_addresses', []))} wallets")
            return {"status": "already_bootstrapped", "watchlist": data}
        except Exception:
            pass

    # Load candidates and wallets
    candidates = load_a_plus_candidates(redis_client)
    stable_wallets = load_stable_wallets(redis_client)
    token_addresses = load_token_addresses(redis_client)

    if not candidates:
        logger.warning("No A+ candidates; using default major symbols")
        candidates = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

    # Build watchlist
    watchlist: dict[str, list[str]] = {}
    all_wallets: set[str] = set()

    for symbol in candidates:
        symbol_clean = symbol.replace("USDT", "")
        # Get from config
        wallets = stable_wallets.get(symbol, []) or []
        watchlist[symbol] = wallets[:max_wallets_per_symbol]
        all_wallets.update(wallets)

    payload = {
        "schema_version": "moralis_watchlist_v1",
        "generated_at": _now(),
        "symbols": candidates,
        "watchlist_by_symbol": watchlist,
        "wallet_addresses": list(all_wallets),
        "total_wallets": len(all_wallets),
        "total_symbols": len(candidates),
        "max_wallets_per_symbol": max_wallets_per_symbol,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }

    # Publish
    redis_client.set(
        MORALIS_WATCHLIST_KEY,
        json.dumps(payload, sort_keys=True, default=str),
        ex=86400,  # 24h TTL
    )

    logger.info(f"Bootstrapped Moralis watchlist: {len(candidate)} symbols, {len(all_wallets)} wallets")
    return {"status": "bootstrapped", "watchlist": payload}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    import sys
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    client = redis.from_url(redis_url)
    result = bootstrap_moralis_watchlist(client, force=bool("--force" in sys.argv))
    print(json.dumps(result, indent=2, default=str))
