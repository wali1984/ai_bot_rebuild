"""Moralis smart-money poller, CU-budget-guarded.

Polls ERC20 token transfer flow (whale flow proxy) for a configurable
watchlist of tokens we trade as perps, and publishes V2 keys. Every call is
priced from the LIVE endpoint-weight table and charged against the monthly
2,000,000 CU budget BEFORE the request is made; if the day's allowance is
exhausted the poll is skipped with an honest status (never silently).

Published keys:
  v2:market:moralis:token_transfers:{SYMBOL}
  v2:market:moralis:whale_flow:{SYMBOL}
  meta:moralis:last_update (ms epoch, matches CoinAnk convention)
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.services.smart_money_wallets.cu_budget import MoralisCuBudget

BASE = "https://deep-index.moralis.io/api/v2.2"
USER_AGENT = "aibot-v2-moralis-client/1.0 (+python-urllib)"
WEIGHTS_KEY = "v2:provider:moralis:endpoint_weights"
WEIGHTS_TTL = 24 * 3600

# Operator-verifiable ERC20 mainnet watchlist (symbol -> contract).
# Extend via v2:provider:moralis:watchlist Redis key (JSON object).
DEFAULT_WATCHLIST: dict[str, str] = {
    "LINKUSDT": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "UNIUSDT": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "AAVEUSDT": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
    "1000PEPEUSDT": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
    "1000SHIBUSDT": "0x95aD61b0a150d79219dCCf929D40Bd2CbeA1e18b",
    "CRVUSDT": "0xD533a949740bb3306d119CC777fa900bA034cd52",
}

FALLBACK_WEIGHTS = {"getTokenAddressTransfers": 50, "getTokenTransfers": 50}
LARGE_TRANSFER_USD_HINT = 100_000  # classification hint only; value-based when price known


def _call(key: str, path: str) -> tuple[int | None, Any]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"X-API-Key": key, "accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__


def load_endpoint_weights(r: Any, key: str) -> dict[str, int]:
    cached = r.get(WEIGHTS_KEY)
    if cached:
        try:
            return {str(k): int(v) for k, v in json.loads(cached).items()}
        except Exception:  # noqa: BLE001
            pass
    status, payload = _call(key, "/info/endpointWeights")
    if status == 200 and isinstance(payload, list):
        weights = {
            str(row.get("endpoint")): int(row.get("rateLimitCost") or 0)
            for row in payload
            if row.get("endpoint")
        }
        r.set(WEIGHTS_KEY, json.dumps(weights), ex=WEIGHTS_TTL)
        return weights
    return dict(FALLBACK_WEIGHTS)


def poll_token_transfers(
    r: Any,
    api_key: str,
    *,
    watchlist: dict[str, str] | None = None,
    ttl_seconds: int = 4 * 3600,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    budget = MoralisCuBudget(r)
    weights = load_endpoint_weights(r, api_key)
    cost_per_token = int(weights.get("getTokenAddressTransfers") or 50)
    wl_raw = r.get("v2:provider:moralis:watchlist")
    try:
        watch = watchlist or (json.loads(wl_raw) if wl_raw else None) or DEFAULT_WATCHLIST
    except Exception:  # noqa: BLE001
        watch = DEFAULT_WATCHLIST

    results: list[dict[str, Any]] = []
    spent = 0
    skipped_budget = 0
    for symbol, contract in watch.items():
        if not budget.can_spend(cost_per_token):
            skipped_budget += 1
            continue
        budget.charge(cost_per_token, endpoint="getTokenAddressTransfers")
        spent += cost_per_token
        status, payload = _call(
            api_key, f"/erc20/{contract}/transfers?chain=eth&limit=25&order=DESC"
        )
        row: dict[str, Any] = {
            "symbol": symbol, "contract": contract, "http_status": status,
            "generated_utc": now, "cu_cost": cost_per_token,
        }
        if status == 200 and isinstance(payload, dict):
            transfers = payload.get("result") or []
            values = []
            for t in transfers:
                try:
                    values.append(float(t.get("value_decimal") or 0))
                except (TypeError, ValueError):
                    continue
            row.update({
                "transfer_count_25": len(transfers),
                "newest_block_timestamp": (
                    transfers[0].get("block_timestamp") if transfers else None
                ),
                "sum_value_tokens": sum(values),
                "max_value_tokens": max(values) if values else None,
            })
            r.set(
                f"v2:market:moralis:token_transfers:{symbol}",
                json.dumps({"schema_version": "moralis_token_transfers_v1", **row,
                            "transfers_sample": transfers[:5]}, default=str),
                ex=ttl_seconds,
            )
            r.set(
                f"v2:market:moralis:whale_flow:{symbol}",
                json.dumps({
                    "schema_version": "moralis_whale_flow_v1",
                    "symbol": symbol, "generated_utc": now,
                    "recent_transfer_count": len(transfers),
                    "max_single_transfer_tokens": row["max_value_tokens"],
                    "flow_basis": "top-25 latest ERC20 transfers (mainnet)",
                }, default=str),
                ex=ttl_seconds,
            )
        results.append(row)
    r.set("meta:moralis:last_update", str(int(time.time() * 1000)))
    status = budget.publish_status(extra={
        "last_poll_utc": now,
        "tokens_polled": len(results),
        "tokens_skipped_budget": skipped_budget,
        "cu_spent_this_poll": spent,
        "cost_per_token_cu": cost_per_token,
    })
    return {"generated_utc": now, "results": results, "budget": status}
