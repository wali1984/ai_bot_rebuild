"""Exchange fail-closed adapter.

Policy:
- Public market-data calls are allowed (ticker, depth, klines).
- Account read-only calls are allowed only through the account monitor.
- All other method lookups raise BlockedGateNotApproved.

This module does NOT enumerate the forbidden method names. The default
behavior is: only the explicitly allow-listed methods on this adapter
exist. Anything else raises. This is the contract for fail-closed
mutation isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BLOCKED_GATE_REASON = "BLOCKED_GATE_NOT_APPROVED"


class BlockedGateNotApproved(Exception):
    """Raised on any exchange mutation attempt from V2-owned runtime."""


_ALLOW_LISTED_PUBLIC_METHODS = frozenset({
    "public_ticker",
    "public_depth",
    "public_klines",
    "account_snapshot",
})


@dataclass
class ExchangeFailClosedAdapter:
    """A defensive adapter that exposes only read-only public calls."""

    public_client: Any = None
    readonly_account_client: Any = None

    def public_ticker(self, symbol: str) -> Any:
        if self.public_client is None:
            return None
        return self.public_client.ticker(symbol)

    def public_depth(self, symbol: str, limit: int = 50) -> Any:
        if self.public_client is None:
            return None
        return self.public_client.depth(symbol, limit=limit)

    def public_klines(self, symbol: str, interval: str, limit: int = 100) -> Any:
        if self.public_client is None:
            return None
        return self.public_client.klines(symbol=symbol, interval=interval, limit=limit)

    def account_snapshot(self) -> Any:
        if self.readonly_account_client is None:
            return None
        return self.readonly_account_client.account_snapshot()

    def __getattr__(self, name: str) -> Any:
        if name in _ALLOW_LISTED_PUBLIC_METHODS:
            return object.__getattribute__(self, name)
        raise BlockedGateNotApproved(
            f"{BLOCKED_GATE_REASON}: method={name} not in allow-list"
        )


def exchange_invariants_snapshot() -> dict:
    return {
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "blocked_gate_reason": BLOCKED_GATE_REASON,
        "exchange_mutation_reachable": False,
        "public_market_data_reachable": True,
        "readonly_account_reachable_via_account_monitor": True,
    }
