"""Read-only Binance USD-M futures user-data (account) WebSocket stream client.

Consumes the Binance USER DATA STREAM (listenKey push) and maintains a live,
read-only mirror of the account: balances, positions, open orders, margin calls,
and leverage/margin-mode config changes.

SAFETY (enforced, not aspirational):
  * The ONLY outbound HTTP this client performs is listenKey stream management
    (POST/PUT/DELETE /fapi/v1/listenKey) — creating, keeping alive, and closing
    the inbound data stream. A user-data stream is inbound-only; you CANNOT place,
    cancel, or modify an order, change leverage, or change margin mode through it.
  * ``_ALLOWED_HTTP_PATHS`` is a hard allowlist of exactly one path. Any other
    path raises. There is no order-submit code path in this module.
  * Uses the read-only credential binding (credential_ref must contain READONLY,
    live_trading_enabled must be False) via BinanceUSDMAdapter.from_env().
  * ``PLACES_REAL_ORDER`` is False and ``READ_ONLY`` is True — module invariants.

Order EXECUTION stays behind the existing risk gateway + superadmin live-gate
approval flow (api/v1/live_gate.py). This module is the account-visibility half of
the gated live adapter and is safe to run against a $0, read-only account.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from v2.backend.app.services.execution.binance_usdm_adapter import (
    DEFAULT_BASE_URL,
    TESTNET_BASE_URL,
    BinanceUSDMAdapter,
)

READ_ONLY: bool = True
PLACES_REAL_ORDER: bool = False

SCHEMA_VERSION = "binance_user_data_stream_v1"

# The single permitted outbound HTTP path. Stream management only — never trading.
_LISTEN_KEY_PATH = "/fapi/v1/listenKey"
_ALLOWED_HTTP_PATHS: frozenset[str] = frozenset({_LISTEN_KEY_PATH})

# Binance expires an unused listenKey after 60 min; refresh well inside that.
LISTEN_KEY_KEEPALIVE_SECONDS = 30 * 60

# Redis keys (v2 namespace, read-only mirror).
REDIS_SNAPSHOT_KEY = "v2:live:account:snapshot"
REDIS_POSITIONS_KEY = "v2:live:account:positions"
REDIS_ORDERS_KEY = "v2:live:account:open_orders"
REDIS_STATUS_KEY = "v2:live:account_stream:status"


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_user_data_ws_base(rest_base_url: str) -> str:
    """Map a REST base URL to the user-data WS base (production or testnet)."""
    base = (rest_base_url or DEFAULT_BASE_URL).rstrip("/")
    if "testnet" in base:
        return "wss://stream.binancefuture.com"
    return "wss://fstream.binance.com"


# ── Event normalizers (pure; no network — the testable core) ──────────────────

def normalize_account_update(event: Mapping[str, Any]) -> dict[str, Any]:
    """ACCOUNT_UPDATE → normalized balances + positions delta."""
    account = event.get("a") if isinstance(event.get("a"), Mapping) else {}
    balances = []
    for b in account.get("B") or []:
        if not isinstance(b, Mapping):
            continue
        balances.append({
            "asset": b.get("a"),
            "wallet_balance": _f(b.get("wb")),
            "cross_wallet_balance": _f(b.get("cw")),
            "balance_change": _f(b.get("bc")),
        })
    positions = []
    for p in account.get("P") or []:
        if not isinstance(p, Mapping):
            continue
        positions.append({
            "symbol": p.get("s"),
            "position_amount": _f(p.get("pa")),
            "entry_price": _f(p.get("ep")),
            "accumulated_realized": _f(p.get("cr")),
            "unrealized_pnl": _f(p.get("up")),
            "margin_type": p.get("mt"),
            "isolated_wallet": _f(p.get("iw")),
            "position_side": p.get("ps"),
        })
    return {
        "event": "ACCOUNT_UPDATE",
        "event_time_ms": event.get("E"),
        "transaction_time_ms": event.get("T"),
        "reason": account.get("m"),
        "balances": balances,
        "positions": positions,
    }


def normalize_order_trade_update(event: Mapping[str, Any]) -> dict[str, Any]:
    """ORDER_TRADE_UPDATE → normalized order/fill state."""
    o = event.get("o") if isinstance(event.get("o"), Mapping) else {}
    return {
        "event": "ORDER_TRADE_UPDATE",
        "event_time_ms": event.get("E"),
        "symbol": o.get("s"),
        "client_order_id": o.get("c"),
        "side": o.get("S"),
        "order_type": o.get("o"),
        "time_in_force": o.get("f"),
        "orig_qty": _f(o.get("q")),
        "price": _f(o.get("p")),
        "avg_price": _f(o.get("ap")),
        "stop_price": _f(o.get("sp")),
        "exec_type": o.get("x"),
        "order_status": o.get("X"),
        "order_id": o.get("i"),
        "last_filled_qty": _f(o.get("l")),
        "cum_filled_qty": _f(o.get("z")),
        "last_filled_price": _f(o.get("L")),
        "commission": _f(o.get("n")),
        "commission_asset": o.get("N"),
        "trade_time_ms": o.get("T"),
        "trade_id": o.get("t"),
        "realized_profit": _f(o.get("rp")),
        "position_side": o.get("ps"),
        "reduce_only": o.get("R"),
    }


def normalize_margin_call(event: Mapping[str, Any]) -> dict[str, Any]:
    """MARGIN_CALL → normalized at-risk positions (liquidation warning)."""
    positions = []
    for p in event.get("p") or []:
        if not isinstance(p, Mapping):
            continue
        positions.append({
            "symbol": p.get("s"),
            "position_side": p.get("ps"),
            "position_amount": _f(p.get("pa")),
            "margin_type": p.get("mt"),
            "isolated_wallet": _f(p.get("iw")),
            "mark_price": _f(p.get("mp")),
            "unrealized_pnl": _f(p.get("up")),
            "maintenance_margin": _f(p.get("mm")),
        })
    return {
        "event": "MARGIN_CALL",
        "event_time_ms": event.get("E"),
        "cross_wallet_balance": _f(event.get("cw")),
        "positions": positions,
    }


def normalize_account_config_update(event: Mapping[str, Any]) -> dict[str, Any]:
    """ACCOUNT_CONFIG_UPDATE → leverage / multi-assets-mode change."""
    ac = event.get("ac") if isinstance(event.get("ac"), Mapping) else {}
    ai = event.get("ai") if isinstance(event.get("ai"), Mapping) else {}
    return {
        "event": "ACCOUNT_CONFIG_UPDATE",
        "event_time_ms": event.get("E"),
        "symbol": ac.get("s"),
        "leverage": ac.get("l"),
        "multi_assets_mode": ai.get("j"),
    }


# ── Live read-only account mirror ─────────────────────────────────────────────

@dataclass
class UserDataAccountModel:
    """Accumulates the latest read-only account state from stream events."""

    balances: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    open_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    leverage_by_symbol: dict[str, Any] = field(default_factory=dict)
    margin_call: dict[str, Any] | None = None
    last_event: str | None = None
    last_event_time_ms: int | None = None
    events_applied: int = 0

    # Order statuses that mean the order is no longer open/working.
    _TERMINAL_ORDER_STATUS = frozenset({"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"})

    def apply(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        """Apply one raw Binance event; returns the normalized event (or None)."""
        etype = event.get("e")
        if etype == "ACCOUNT_UPDATE":
            norm = normalize_account_update(event)
            for b in norm["balances"]:
                if b.get("asset"):
                    self.balances[b["asset"]] = b
            for p in norm["positions"]:
                sym = p.get("symbol")
                if not sym:
                    continue
                # A flat position (amount 0) is dropped from the live map.
                if (p.get("position_amount") or 0.0) == 0.0:
                    self.positions.pop(sym, None)
                else:
                    self.positions[sym] = p
        elif etype == "ORDER_TRADE_UPDATE":
            norm = normalize_order_trade_update(event)
            oid = norm.get("order_id")
            if oid is not None:
                if norm.get("order_status") in self._TERMINAL_ORDER_STATUS:
                    self.open_orders.pop(oid, None)
                else:
                    self.open_orders[oid] = norm
        elif etype == "MARGIN_CALL":
            norm = normalize_margin_call(event)
            self.margin_call = norm
        elif etype == "ACCOUNT_CONFIG_UPDATE":
            norm = normalize_account_config_update(event)
            if norm.get("symbol") and norm.get("leverage") is not None:
                self.leverage_by_symbol[norm["symbol"]] = norm["leverage"]
        else:
            return None
        self.last_event = etype
        self.last_event_time_ms = event.get("E")
        self.events_applied += 1
        return norm

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "read_only": READ_ONLY,
            "places_real_order": PLACES_REAL_ORDER,
            "balances": list(self.balances.values()),
            "positions": list(self.positions.values()),
            "open_orders": list(self.open_orders.values()),
            "leverage_by_symbol": dict(self.leverage_by_symbol),
            "margin_call": self.margin_call,
            "open_position_count": len(self.positions),
            "open_order_count": len(self.open_orders),
            "last_event": self.last_event,
            "last_event_time_ms": self.last_event_time_ms,
            "events_applied": self.events_applied,
        }


# ── Stream status ─────────────────────────────────────────────────────────────

@dataclass
class UserDataStreamStatus:
    state: str = "INITIALIZING"
    detail: str | None = None
    has_credentials: bool = False
    listen_key_present: bool = False
    ws_connected: bool = False
    reconnect_count: int = 0
    last_keepalive_ms: int | None = None
    updated_ms: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": self.state,
            "detail": self.detail,
            "read_only": READ_ONLY,
            "places_real_order": PLACES_REAL_ORDER,
            "has_credentials": self.has_credentials,
            "listen_key_present": self.listen_key_present,
            "ws_connected": self.ws_connected,
            "reconnect_count": self.reconnect_count,
            "last_keepalive_ms": self.last_keepalive_ms,
            "updated_ms": self.updated_ms,
        }


# Injectable I/O signatures (default implementations use aiohttp/websockets/redis).
HttpSender = Callable[[str, str, Mapping[str, str], str | None], Awaitable[dict[str, Any]]]
WsConnect = Callable[[str], Awaitable[Any]]
Publisher = Callable[[str, str], None]


class BinanceUserDataStreamClient:
    """Read-only user-data stream client. Never submits/cancels/modifies orders."""

    def __init__(
        self,
        *,
        adapter: BinanceUSDMAdapter | None = None,
        http_sender: HttpSender | None = None,
        ws_connect: WsConnect | None = None,
        publisher: Publisher | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._adapter = adapter or BinanceUSDMAdapter.from_env()
        self._http = http_sender
        self._ws_connect = ws_connect
        self._publish = publisher
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.model = UserDataAccountModel()
        self.status = UserDataStreamStatus(has_credentials=self._adapter.has_credentials)
        self._listen_key: str | None = None

    # -- stream management (the only outbound calls; not trading) --------------

    async def _http_call(self, method: str, path: str, *, body: str | None = None) -> dict[str, Any]:
        if path not in _ALLOWED_HTTP_PATHS:
            # Hard guard: this client may ONLY manage the listenKey stream.
            raise ValueError(f"binance_user_data_stream_disallowed_path:{path}")
        if not self._adapter.has_credentials:
            return {"ok": False, "status": "MISSING_CREDENTIALS"}
        headers = {"X-MBX-APIKEY": self._adapter.api_key or ""}
        url = f"{self._adapter.base_url}{path}"
        sender = self._http or _default_http_sender
        return await sender(method, url, headers, body)

    async def create_listen_key(self) -> str | None:
        result = await self._http_call("POST", _LISTEN_KEY_PATH)
        key = (result.get("json") or {}).get("listenKey") if isinstance(result.get("json"), Mapping) else None
        self._listen_key = key
        self.status.listen_key_present = bool(key)
        return key

    async def keepalive_listen_key(self) -> bool:
        result = await self._http_call("PUT", _LISTEN_KEY_PATH)
        ok = bool(result.get("ok"))
        if ok:
            self.status.last_keepalive_ms = self._now_ms()
        return ok

    async def close_listen_key(self) -> bool:
        result = await self._http_call("DELETE", _LISTEN_KEY_PATH)
        self._listen_key = None
        self.status.listen_key_present = False
        return bool(result.get("ok"))

    def ws_url(self) -> str | None:
        if not self._listen_key:
            return None
        return f"{derive_user_data_ws_base(self._adapter.base_url)}/ws/{self._listen_key}"

    # -- publishing -----------------------------------------------------------

    def _emit(self) -> None:
        if not self._publish:
            return
        self.status.updated_ms = self._now_ms()
        try:
            self._publish(REDIS_STATUS_KEY, json.dumps(self.status.payload()))
            snap = self.model.snapshot()
            self._publish(REDIS_SNAPSHOT_KEY, json.dumps(snap))
            self._publish(REDIS_POSITIONS_KEY, json.dumps(snap["positions"]))
            self._publish(REDIS_ORDERS_KEY, json.dumps(snap["open_orders"]))
        except Exception:  # noqa: BLE001 - publishing must never crash the stream
            pass

    def _set_state(self, state: str, detail: str | None = None) -> None:
        self.status.state = state
        self.status.detail = detail
        self._emit()

    def apply_raw(self, raw: str | Mapping[str, Any]) -> dict[str, Any] | None:
        """Apply one raw WS message (str or dict); publishes on change."""
        try:
            event = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return None
        if not isinstance(event, Mapping):
            return None
        if event.get("e") == "listenKeyExpired":
            self.status.listen_key_present = False
            self._set_state("LISTEN_KEY_EXPIRED", "listenKey expired; reconnecting")
            return {"event": "listenKeyExpired"}
        norm = self.model.apply(event)
        if norm is not None:
            self._emit()
        return norm

    # -- run loop -------------------------------------------------------------

    async def run(self, *, stop: Callable[[], bool] | None = None) -> None:
        """Persistent read-only run loop: listenKey -> WS consume -> keepalive."""
        stop = stop or (lambda: False)
        if not self._adapter.has_credentials:
            self._set_state(
                "AWAITING_READONLY_CREDENTIALS",
                "No read-only Binance API credentials bound (account credential_source_pending). "
                "Provide the READONLY key/secret to begin the read-only account stream.",
            )
            return
        while not stop():
            try:
                key = await self.create_listen_key()
                if not key:
                    self._set_state("LISTEN_KEY_UNAVAILABLE", "Could not create listenKey")
                    await asyncio.sleep(5)
                    continue
                url = self.ws_url()
                connect = self._ws_connect or _default_ws_connect
                conn = await connect(url)
                self.status.ws_connected = True
                self._set_state("STREAMING", "Read-only account stream connected")
                last_keepalive = self._now_ms()
                try:
                    async for message in conn:
                        result = self.apply_raw(message)
                        if result is not None and result.get("event") == "listenKeyExpired":
                            break
                        if self._now_ms() - last_keepalive >= LISTEN_KEY_KEEPALIVE_SECONDS * 1000:
                            await self.keepalive_listen_key()
                            last_keepalive = self._now_ms()
                        if stop():
                            break
                finally:
                    self.status.ws_connected = False
                    close = getattr(conn, "close", None)
                    if close:
                        maybe = close()
                        if asyncio.iscoroutine(maybe):
                            await maybe
            except Exception as exc:  # noqa: BLE001 - reconnect on any transport error
                self.status.reconnect_count += 1
                self._set_state("RECONNECTING", f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(min(30, 1 + self.status.reconnect_count))


# ── Default I/O implementations (thin; used only in the live runtime) ─────────

async def _default_http_sender(
    method: str, url: str, headers: Mapping[str, str], body: str | None
) -> dict[str, Any]:  # pragma: no cover - network
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=dict(headers), data=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text()
            try:
                payload = json.loads(text) if text else {}
            except ValueError:
                payload = {}
            return {"ok": 200 <= resp.status < 300, "status_code": resp.status, "json": payload}


async def _default_ws_connect(url: str):  # pragma: no cover - network
    import websockets

    return await websockets.connect(url, ping_interval=180, ping_timeout=600)
