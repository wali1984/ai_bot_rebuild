"""Legacy Moralis smart-money compatibility publisher.

The canonical provider scheduler owns ERC20 transfer polling.  This module is
still imported by the native feature loop, so ``poll_token_transfers`` remains
as a no-HTTP compatibility shim.  Keeping the retirement unconditional avoids
startup, status-TTL, and concurrent-worker windows in which both paths could
spend compute units for the same transport.

Published keys:
  v2:market:moralis:token_transfers:{SYMBOL}
  v2:market:moralis:whale_flow:{SYMBOL}
  meta:moralis:last_update (ms epoch, matches CoinAnk convention)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from app.services.smart_money_wallets.budgeted_http import (
    MoralisBudgetedHttpResult,
    budgeted_moralis_get_json,
)
from app.services.smart_money_wallets.cu_budget import MoralisCuBudget
from app.services.smart_money_wallets.endpoint_registry import moralis_endpoint_registry
from app.services.smart_money_wallets.rate_limit import MoralisRateLimiter

BASE = "https://deep-index.moralis.io/api/v2.2"
WEIGHTS_KEY = "v2:provider:moralis:endpoint_weights"
WEIGHTS_TTL = 24 * 3600
_ENDPOINT_COSTS = {spec.endpoint_id: int(spec.cu_cost) for spec in moralis_endpoint_registry()}
_TOKEN_TRANSFER_CU = _ENDPOINT_COSTS["token_transfers"]
ENDPOINT_WEIGHTS_CU = _TOKEN_TRANSFER_CU

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

FALLBACK_WEIGHTS = {
    "getTokenAddressTransfers": _TOKEN_TRANSFER_CU,
    "getTokenTransfers": _TOKEN_TRANSFER_CU,
}
LARGE_TRANSFER_USD_HINT = 100_000  # classification hint only; value-based when price known


def load_endpoint_weights(
    r: Any,
    key: str,
    *,
    limiter: MoralisRateLimiter | None = None,
    http_client: Any | None = None,
) -> dict[str, int]:
    weights, _outcome = _load_endpoint_weights(
        r,
        key,
        limiter=limiter or MoralisRateLimiter(redis_client=r),
        http_client=http_client,
    )
    return weights


def _load_endpoint_weights(
    r: Any,
    key: str,
    *,
    limiter: MoralisRateLimiter,
    http_client: Any | None,
) -> tuple[dict[str, int], MoralisBudgetedHttpResult | None]:
    cached = r.get(WEIGHTS_KEY)
    if cached:
        try:
            return {str(k): int(v) for k, v in json.loads(cached).items()}, None
        except Exception:  # noqa: BLE001
            pass
    outcome = budgeted_moralis_get_json(
        api_key=key,
        endpoint_id="endpoint_weights",
        path="/info/endpointWeights",
        estimated_cu=ENDPOINT_WEIGHTS_CU,
        limiter=limiter,
        base_url=BASE,
        timeout_seconds=12.0,
        http_client=http_client,
    )
    if outcome.ok and isinstance(outcome.payload, list):
        weights = {
            str(row.get("endpoint")): int(row.get("rateLimitCost") or 0)
            for row in outcome.payload
            if row.get("endpoint")
        }
        r.set(WEIGHTS_KEY, json.dumps(weights), ex=WEIGHTS_TTL)
        return weights, outcome
    return dict(FALLBACK_WEIGHTS), outcome


def poll_token_transfers(
    r: Any,
    api_key: str,
    *,
    watchlist: dict[str, str] | None = None,
    ttl_seconds: int = 4 * 3600,
    limiter: MoralisRateLimiter | None = None,
    http_client: Any | None = None,
) -> dict[str, Any]:
    """Publish an honest retirement heartbeat without issuing provider I/O."""

    del api_key, watchlist, ttl_seconds, limiter, http_client
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    budget = MoralisCuBudget(r)
    r.set("meta:moralis:last_update", str(int(time.time() * 1000)))
    status = budget.publish_status(extra={
        "last_poll_utc": now,
        "tokens_polled": 0,
        "tokens_skipped_budget": 0,
        "cu_spent_this_poll": 0,
        "cost_per_token_cu": _TOKEN_TRANSFER_CU,
        "canonical_provider_transport_owner": True,
        "legacy_transport_retired": True,
        "poll_suppressed_reason": "LEGACY_TRANSPORT_RETIRED_CANONICAL_ONLY",
    })
    return {
        "generated_utc": now,
        "results": [],
        "budget": status,
        "request_count": 0,
        "canonical_provider_transport_owner": True,
        "legacy_transport_retired": True,
    }
