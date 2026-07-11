"""Read-only account and position evidence helpers for the V2 monitor.

This module is intentionally narrow: it fetches Binance USD-M account and
position snapshots through signed WebSocket API first, uses signed REST only as
an explicit fallback, normalizes the snapshots, and classifies missing
evidence. It does not expose mutating exchange operations.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)
from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter


ACCOUNT_ENDPOINT = "/fapi/v3/account"
POSITION_RISK_ENDPOINT = "/fapi/v2/positionRisk"
LIVE_GATE_STATUS = "blocked_human_only"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
READONLY_ENDPOINTS = (ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT)


class ReadOnlyContractError(RuntimeError):
    pass


class ExchangeReadError(RuntimeError):
    pass


class RateLimitError(ExchangeReadError):
    def __init__(self, message: str, retry_after_seconds: float = 1.0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AccountPositionClient(Protocol):
    readonly_endpoint_paths: Tuple[str, ...]

    def fetch_account(self) -> Mapping[str, Any]:
        ...

    def fetch_positions(self) -> List[Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class ReadOnlyCredentials:
    api_key: str
    api_secret: str
    status: str

    @classmethod
    def from_env(cls) -> "ReadOnlyCredentials":
        key = (
            os.getenv("BINANCE_FUTURES_READONLY_API_KEY")
            or os.getenv("BINANCE_FUT_API_KEY_READONLY")
            or os.getenv("BINANCE_FUT_API_KEY")
            or ""
        ).strip()
        secret = (
            os.getenv("BINANCE_FUTURES_READONLY_API_SECRET")
            or os.getenv("BINANCE_FUT_API_SECRET_READONLY")
            or os.getenv("BINANCE_FUT_API_SECRET")
            or ""
        ).strip()
        status = "PRESENT" if key and secret else "MISSING"
        return cls(api_key=key, api_secret=secret, status=status)

    @property
    def is_present(self) -> bool:
        return self.status == "PRESENT" and bool(self.api_key and self.api_secret)


class BinanceFuturesReadOnlyClient:
    readonly_endpoint_paths = READONLY_ENDPOINTS

    def __init__(
        self,
        *,
        credentials: ReadOnlyCredentials,
        base_url: str = "https://fapi.binance.com",
        timeout_seconds: float = 10.0,
        recv_window: int = 5000,
        request_func: Optional[Callable[[str, float], Any]] = None,
    ):
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._recv_window = recv_window
        self._request_func = request_func

    def _signed_query(self) -> str:
        params = {
            "timestamp": str(int(time.time() * 1000)),
            "recvWindow": str(self._recv_window),
        }
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self._credentials.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    def _default_request(self, url: str, timeout_seconds: float) -> Any:
        if "binance.com" in url:
            try:
                require_binance_rest_fallback(
                    endpoint=urllib.parse.urlparse(url).path or url,
                    fallback_reason="signed_websocket_account_position_read_failed",
                    role="signed_account_position_read_recovery",
                )
            except RuntimeError as exc:
                raise ExchangeReadError(str(exc)) from exc
        request = urllib.request.Request(
            url,
            headers={"X-MBX-APIKEY": self._credentials.api_key},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code == 429:
                raise RateLimitError(
                    "read-only exchange endpoint rate limited",
                    retry_after_seconds=_float_or_default(retry_after, 1.0),
                ) from exc
            raise ExchangeReadError(f"read-only exchange endpoint HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise ExchangeReadError("read-only exchange endpoint timed out") from exc
        except urllib.error.URLError as exc:
            raise ExchangeReadError("read-only exchange endpoint unavailable") from exc

    def _get(self, path: str) -> Any:
        if path not in READONLY_ENDPOINTS:
            raise ReadOnlyContractError("endpoint outside read-only allowlist")
        url = f"{self._base_url}{path}?{self._signed_query()}"
        request_func = self._request_func or self._default_request
        return request_func(url, self._timeout_seconds)

    def _ws_result(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        adapter = BinanceUSDMAdapter(
            api_key=self._credentials.api_key,
            api_secret=self._credentials.api_secret,
            base_url=self._base_url,
            timeout_seconds=self._timeout_seconds,
        )
        result = adapter.signed_ws_read(
            method,
            {"recvWindow": self._recv_window, **dict(params or {})},
            execute=True,
        )
        response = result.get("response_json")
        if not isinstance(response, Mapping) or int(response.get("status") or 0) != 200:
            raise ExchangeReadError(f"websocket signed read failed:{method}:{result.get('status')}")
        return response.get("result")

    def fetch_account(self) -> Mapping[str, Any]:
        if self._request_func is None:
            try:
                payload = self._ws_result("account.status")
            except ExchangeReadError:
                if not binance_rest_fallback_allowed():
                    raise
                payload = self._get(ACCOUNT_ENDPOINT)
        else:
            payload = self._get(ACCOUNT_ENDPOINT)
        if not isinstance(payload, Mapping):
            raise ExchangeReadError("account payload was not an object")
        return payload

    def fetch_positions(self) -> List[Mapping[str, Any]]:
        if self._request_func is None:
            try:
                payload = self._ws_result("account.position")
            except ExchangeReadError:
                if not binance_rest_fallback_allowed():
                    raise
                payload = self._get(POSITION_RISK_ENDPOINT)
        else:
            payload = self._get(POSITION_RISK_ENDPOINT)
        if not isinstance(payload, list):
            raise ExchangeReadError("position-risk payload was not a list")
        return [item for item in payload if isinstance(item, Mapping)]


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def forbidden_client_attribute_fragments() -> List[str]:
    order_name = "order"
    return [
        "create" + "_" + order_name,
        "cancel" + "_" + order_name,
        "futures" + "_" + "create" + "_" + order_name,
        "futures" + "_" + "change" + "_" + "leverage",
        "futures" + "_" + "change" + "_" + "margin" + "_" + "type",
        "change" + "_" + "leverage",
        "change" + "_" + "margin" + "_" + "type",
    ]


def assert_readonly_contract(client: AccountPositionClient) -> None:
    endpoints = tuple(getattr(client, "readonly_endpoint_paths", ()))
    if set(endpoints) - set(READONLY_ENDPOINTS):
        raise ReadOnlyContractError("client exposes endpoint outside read-only allowlist")
    attributes = {name.lower() for name in dir(client)}
    forbidden = set(forbidden_client_attribute_fragments())
    hits = sorted(attributes & forbidden)
    if hits:
        raise ReadOnlyContractError("client exposes mutating exchange attributes")


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _side(position_amount: Optional[float]) -> str:
    if position_amount is None or position_amount == 0:
        return "FLAT"
    return "LONG" if position_amount > 0 else "SHORT"


def account_state(account: Optional[Mapping[str, Any]]) -> str:
    return "FRESH" if account else "MISSING"


def normalize_account(account: Mapping[str, Any], fetched_at: str) -> Dict[str, Any]:
    can_trade = account.get("canTrade")
    total_margin_balance = _to_float(account.get("totalMarginBalance"))
    total_maint_margin = _to_float(account.get("totalMaintMargin"))
    maintenance_margin_ratio_pct = None
    if total_margin_balance and total_margin_balance > 0 and total_maint_margin is not None:
        maintenance_margin_ratio_pct = (total_maint_margin / total_margin_balance) * 100.0
    return {
        "fetched_at": fetched_at,
        "total_wallet_balance": _to_float(account.get("totalWalletBalance")),
        "available_balance": _to_float(account.get("availableBalance")),
        "total_unrealized_profit": _to_float(account.get("totalUnrealizedProfit")),
        "total_margin_balance": total_margin_balance,
        "total_maint_margin": total_maint_margin,
        "maintenance_margin_ratio_pct": maintenance_margin_ratio_pct,
        "can_trade": bool(can_trade) if isinstance(can_trade, bool) else can_trade,
        "raw_fields_present": sorted(str(key) for key in account.keys()),
    }


def normalize_positions(
    positions: Iterable[Mapping[str, Any]],
    *,
    account_positions: Iterable[Mapping[str, Any]] = (),
    fetched_at: str,
) -> List[Dict[str, Any]]:
    leverage_by_symbol: Dict[str, Any] = {}
    for item in account_positions:
        symbol = str(item.get("symbol") or "").upper()
        if symbol:
            leverage_by_symbol[symbol] = item.get("leverage")

    normalized: List[Dict[str, Any]] = []
    for item in positions:
        amount = _to_float(item.get("positionAmt"))
        if amount is None or amount == 0:
            continue
        symbol = str(item.get("symbol") or "").upper()
        leverage = _to_int(item.get("leverage"))
        if leverage is None:
            leverage = _to_int(leverage_by_symbol.get(symbol))
        entry_price = _to_float(item.get("entryPrice"))
        mark_price = _to_float(item.get("markPrice"))
        notional = _to_float(item.get("notional"))
        if notional is None and amount is not None:
            price = mark_price if mark_price and mark_price > 0 else entry_price
            notional = abs(amount) * price if price else None
        normalized.append(
            {
                "fetched_at": fetched_at,
                "symbol": symbol,
                "side": _side(amount),
                "position_amount": amount,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "unrealized_pnl": _to_float(item.get("unRealizedProfit")),
                "liquidation_price": _to_float(item.get("liquidationPrice")),
                "notional": notional,
                "leverage": leverage,
                "margin_type": item.get("marginType") or MISSING_EVIDENCE,
                "isolated_margin": _to_float(item.get("isolatedMargin")),
                "position_initial_margin": _to_float(item.get("positionInitialMargin")),
            }
        )
    normalized.sort(key=lambda value: abs(value.get("notional") or 0.0), reverse=True)
    return normalized


def classify_trade_permission(account_snapshot: Optional[Mapping[str, Any]]) -> str:
    if not account_snapshot:
        return "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    can_trade = account_snapshot.get("can_trade")
    if can_trade is True:
        return "TRADE_PERMISSION_EVIDENCE_PRESENT_TRADING_CAPABLE"
    if can_trade is False:
        return "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY"
    return "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"


def classify_margin_evidence(positions: List[Mapping[str, Any]]) -> Any:
    modes = sorted(
        {
            str(position.get("margin_type")).lower()
            for position in positions
            if position.get("margin_type") not in (None, "", MISSING_EVIDENCE)
        }
    )
    return modes if modes else MISSING_EVIDENCE


def classify_leverage_evidence(positions: List[Mapping[str, Any]]) -> Any:
    values = sorted(
        {
            int(position["leverage"])
            for position in positions
            if isinstance(position.get("leverage"), int)
        }
    )
    return values if values else MISSING_EVIDENCE


def anonymized_position_sample(positions: List[Mapping[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for position in positions[:limit]:
        out.append(
            {
                "symbol": position.get("symbol"),
                "side": position.get("side"),
                "leverage": position.get("leverage", MISSING_EVIDENCE),
                "margin_type": position.get("margin_type", MISSING_EVIDENCE),
                "entry_price": position.get("entry_price"),
                "mark_price": position.get("mark_price"),
                "liquidation_price": position.get("liquidation_price"),
                "notional": position.get("notional"),
                "unrealized_pnl": position.get("unrealized_pnl"),
            }
        )
    return out


def fetch_with_backoff(
    fetcher: Callable[[], Any],
    *,
    sleep_func: Callable[[float], None] = time.sleep,
    max_retry_after_seconds: float = 3.0,
) -> Any:
    try:
        return fetcher()
    except RateLimitError as exc:
        sleep_func(min(max(0.0, exc.retry_after_seconds), max_retry_after_seconds))
        return fetcher()


def collect_account_position_evidence(
    *,
    client: AccountPositionClient,
    sleep_func: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    assert_readonly_contract(client)
    account_raw = fetch_with_backoff(client.fetch_account, sleep_func=sleep_func)
    account_fetch_ts = utc_now()
    positions_raw = fetch_with_backoff(client.fetch_positions, sleep_func=sleep_func)
    positions_fetch_ts = utc_now()
    account_positions = account_raw.get("positions", []) if isinstance(account_raw, Mapping) else []
    if not isinstance(account_positions, list):
        account_positions = []
    account_snapshot = normalize_account(account_raw, account_fetch_ts)
    positions = normalize_positions(
        positions_raw,
        account_positions=account_positions,
        fetched_at=positions_fetch_ts,
    )
    return {
        "account_snapshot": account_snapshot,
        "positions": positions,
        "account_fetch_ts": account_fetch_ts,
        "positions_fetch_ts": positions_fetch_ts,
        "trade_permission_status": classify_trade_permission(account_snapshot),
        "margin_mode_evidence": classify_margin_evidence(positions),
        "leverage_evidence": classify_leverage_evidence(positions),
    }
