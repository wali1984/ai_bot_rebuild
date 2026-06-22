"""Audited V2 Binance live order transport.

The module contains the only V2 live-order transport binding. It is deliberately
fail-closed: current live-gate runtime state, accepted symbols, conservative
risk profile, lineage, risk evidence, read-only position evidence, Redis dedupe,
and the audited runtime write/submit guards must all pass before the signed
Binance order request is constructed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_ENABLED,
    live_submit_release_mode_approved,
    payload_arms_live_submit,
    read_runtime_execution_state,
    validate_runtime_execution_state,
)
from v2.backend.app.services.live_gate.live_position_state_machine import (
    LiveCanaryConfig,
    evaluate_live_canary_preflight,
)
from v2.backend.app.services.live_gate.exchange_filter_sizing import min_executable_order
from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    allocate_live_candidate,
)
from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_ws_api_url,
    build_signed_ws_api_request,
    default_ws_api_sender,
    redacted_json,
    resolve_binance_credential_binding,
    transport_policy_snapshot,
)

_EST = ZoneInfo("America/New_York")
_REPO_ROOT_ENV = "V2_REPO_ROOT"
_TRANSPORT_DISABLED_ENV = "V2_BINANCE_LIVE_ORDER_TRANSPORT_DISABLED"
_BINANCE_BASE_URL_ENV = "V2_BINANCE_USDM_BASE_URL"
_REDIS_REQUIRED_ENV = "V2_BINANCE_LIVE_ORDER_TRANSPORT_REDIS_REQUIRED"
_REST_ORDER_FALLBACK_ENABLED_ENV = "V2_BINANCE_REST_ORDER_FALLBACK_ENABLED"
_MAX_SIGNAL_AGE_SECONDS = 180

ARTIFACT_REL = Path("v2_binance_live_order_transport_binding_and_first_hour_monitoring/latest")
PUBLIC_ARTIFACT_REL = Path("v2/frontend/public") / ARTIFACT_REL
WORKLOG_ARTIFACT_REL = Path("claude_worklog/final_readiness") / ARTIFACT_REL

KEY_STATUS = "v2:live_order_transport:status"
KEY_AUDIT = "v2:live_order_transport:audit"
KEY_KILL_SWITCH = "v2:live_order_transport:kill_switch"
KEY_DEDUPE = "v2:live_order_transport:dedupe"
KEY_MONITOR = "v2:live_order_transport:first_hour_monitor"
ALLOWED_REDIS_KEYS = frozenset({KEY_STATUS, KEY_AUDIT, KEY_KILL_SWITCH, KEY_DEDUPE, KEY_MONITOR})

REQUIRED_LINEAGE_FIELDS = (
    "prediction_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "signal_id",
    "live_gate_audit_id",
    "risk_profile_audit_id",
    "symbols_audit_id",
)


def _repo_root(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return repo_root.resolve()
    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()


def est_now() -> str:
    return datetime.now(tz=_EST).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse_est(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_EST)
    return dt.astimezone(_EST)


def _age_seconds(value: Any) -> float | None:
    dt = _parse_est(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(tz=_EST) - dt).total_seconds())


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _redis_required() -> bool:
    return os.environ.get(_REDIS_REQUIRED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _safe_redis_set(redis_client: Any, key: str, payload: Any, *, ex: int | None = None) -> bool:
    if redis_client is None or key not in ALLOWED_REDIS_KEYS or not key.startswith("v2:"):
        return False
    try:
        value = json.dumps(payload, sort_keys=True, default=str)
        if ex is None:
            redis_client.set(key, value)
        else:
            redis_client.set(key, value, ex=int(ex))
        return True
    except Exception:
        return False


def _safe_redis_get_json(redis_client: Any, key: str) -> Any:
    if redis_client is None or key not in ALLOWED_REDIS_KEYS or not key.startswith("v2:"):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _read_risk_gateway_decisions(redis_client: Any) -> list[dict[str, Any]]:
    if redis_client is None:
        return []
    try:
        raw = redis_client.get("v2:risk:gateway:decisions")
    except Exception:
        return []
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _kill_switch_active(redis_client: Any, runtime_payload: Mapping[str, Any]) -> tuple[bool, str]:
    if runtime_payload.get("kill_switch_active") is True:
        return True, "runtime_state"
    raw = None
    if redis_client is not None:
        try:
            raw = redis_client.get(KEY_KILL_SWITCH)
        except Exception:
            return True, "redis_read_error"
    if raw is None:
        return False, "unset"
    text = str(raw).strip().lower()
    return text not in {"", "0", "false", "off", "disarmed"}, "redis"


@dataclass(frozen=True)
class LiveOrderCandidate:
    symbol: str
    side: str
    quantity: float
    requested_notional_usdt: float
    price_reference: float
    prediction_id: str
    risk_decision_id: str
    orchestrator_decision_id: str
    signal_id: str
    live_gate_audit_id: str
    risk_profile_audit_id: str
    symbols_audit_id: str
    final_approval_audit_id: str
    expected_move_after_cost_bps: float | None
    confidence: float | None
    source_generated_est: str | None
    position_side: str | None = None

    def lineage_payload(self) -> dict[str, str]:
        return {
            "prediction_id": self.prediction_id,
            "risk_decision_id": self.risk_decision_id,
            "orchestrator_decision_id": self.orchestrator_decision_id,
            "signal_id": self.signal_id,
            "live_gate_audit_id": self.live_gate_audit_id,
            "risk_profile_audit_id": self.risk_profile_audit_id,
            "symbols_audit_id": self.symbols_audit_id,
            "final_approval_audit_id": self.final_approval_audit_id,
        }


class BinanceUsdMLiveOrderTransport:
    """Single signed Binance USD-M order transport.

    No caller can use this class to alter leverage or margin mode; it only
    builds ``POST /fapi/v1/order`` MARKET orders after the guard returns an
    unblocked ``LiveOrderCandidate``.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        urlopen: Callable[..., Any] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(_BINANCE_BASE_URL_ENV) or "https://fapi.binance.com").rstrip("/")
        self._urlopen = urlopen or urllib.request.urlopen
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def submit_market_order(
        self,
        *,
        candidate: LiveOrderCandidate,
        api_key: str,
        api_secret: str,
    ) -> dict[str, Any]:
        if os.environ.get(_REST_ORDER_FALLBACK_ENABLED_ENV, "0").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return {
                "submitted": False,
                "status_code": None,
                "error_type": "REST_ORDER_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                "response_redacted": "",
                "endpoint": "POST /fapi/v1/order",
                "client_order_id": _client_order_id(candidate),
                "rest_fallback_disabled": True,
            }
        params = {
            "symbol": candidate.symbol,
            "side": candidate.side,
            "type": "MARKET",
            "quantity": _format_quantity(candidate.quantity),
            "newClientOrderId": _client_order_id(candidate),
            "timestamp": str(self._clock_ms()),
        }
        if candidate.position_side:
            params["positionSide"] = candidate.position_side
        body = urllib.parse.urlencode(params)
        signature = hmac.new(api_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            f"{self.base_url}/fapi/v1/order",
            data=f"{body}&signature={signature}".encode("utf-8"),
            headers={"X-MBX-APIKEY": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=8.0) as response:
                response_text = response.read().decode("utf-8", errors="replace")
                status_code = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            return {
                "submitted": False,
                "status_code": int(exc.code),
                "error_type": "HTTPError",
                "response_redacted": _redact_response(response_text),
            }
        except Exception as exc:
            return {
                "submitted": False,
                "status_code": None,
                "error_type": type(exc).__name__,
                "response_redacted": "",
            }
        return {
            "submitted": 200 <= status_code < 300,
            "status_code": status_code,
            "error_type": None,
            "response_redacted": _redact_response(response_text),
            "endpoint": "POST /fapi/v1/order",
            "client_order_id": params["newClientOrderId"],
        }

    def fetch_position_mode(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        params = {"timestamp": str(self._clock_ms())}
        body = urllib.parse.urlencode(params)
        signature = hmac.new(api_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            f"{self.base_url}/fapi/v1/positionSide/dual?{body}&signature={signature}",
            headers={"X-MBX-APIKEY": api_key, "User-Agent": "v2-live-order-transport/1.0"},
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
                status_code = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status_code": int(exc.code),
                "error_type": "HTTPError",
                "response_redacted": _redact_response(response_text),
                "endpoint": "GET /fapi/v1/positionSide/dual",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "error_type": type(exc).__name__,
                "endpoint": "GET /fapi/v1/positionSide/dual",
            }
        return {
            "ok": 200 <= status_code < 300 and isinstance(payload, dict),
            "status_code": status_code,
            "error_type": None,
            "dual_side_position": payload.get("dualSidePosition") is True if isinstance(payload, dict) else None,
            "endpoint": "GET /fapi/v1/positionSide/dual",
        }

    def fetch_account_margin_status(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        params = {"timestamp": str(self._clock_ms())}
        body = urllib.parse.urlencode(params)
        signature = hmac.new(api_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            f"{self.base_url}/fapi/v3/account?{body}&signature={signature}",
            headers={"X-MBX-APIKEY": api_key, "User-Agent": "v2-live-order-transport/1.0"},
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
                status_code = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status_code": int(exc.code),
                "error_type": "HTTPError",
                "response_redacted": _redact_response(response_text),
                "endpoint": "GET /fapi/v3/account",
                "balances_redacted": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "error_type": type(exc).__name__,
                "endpoint": "GET /fapi/v3/account",
                "balances_redacted": True,
            }
        available = None
        wallet_balance = None
        unrealized_pnl = None
        if isinstance(payload, dict):
            available = _as_float(payload.get("availableBalance"))
            wallet_balance = _as_float(payload.get("totalWalletBalance"))
            unrealized_pnl = _as_float(payload.get("totalUnrealizedProfit"))
            for asset in _as_list(payload.get("assets")):
                if not isinstance(asset, dict) or str(asset.get("asset") or "").upper() != "USDT":
                    continue
                available = _as_float(asset.get("availableBalance")) or available
                wallet_balance = _as_float(asset.get("walletBalance")) or wallet_balance
                unrealized_pnl = _as_float(asset.get("unrealizedProfit")) or unrealized_pnl
                break
        return {
            "ok": 200 <= status_code < 300 and isinstance(payload, dict),
            "status_code": status_code,
            "error_type": None,
            "can_trade": payload.get("canTrade") if isinstance(payload, dict) else None,
            "available_balance_checked": available is not None,
            "available_balance_redacted": True,
            "wallet_balance_checked": wallet_balance is not None,
            "wallet_balance_redacted": True,
            "unrealized_pnl_checked": unrealized_pnl is not None,
            "unrealized_pnl_redacted": True,
            "_available_balance_usdt": available,
            "_wallet_balance_usdt": wallet_balance,
            "_unrealized_pnl_usdt": unrealized_pnl,
            "endpoint": "GET /fapi/v3/account",
            "balances_redacted": True,
        }

    def fetch_symbol_filters(self, symbol: str) -> dict[str, Any]:
        url = f"{self.base_url}/fapi/v1/exchangeInfo?symbol={urllib.parse.quote(symbol)}"
        request = urllib.request.Request(url, headers={"User-Agent": "v2-live-order-transport/1.0"})
        try:
            with self._urlopen(request, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            return {
                "ok": False,
                "symbol": symbol,
                "error_type": type(exc).__name__,
                "endpoint": "GET /fapi/v1/exchangeInfo",
            }
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        row = symbols[0] if isinstance(symbols, list) and symbols and isinstance(symbols[0], dict) else {}
        filters = row.get("filters") if isinstance(row.get("filters"), list) else []
        by_type = {str(item.get("filterType")): item for item in filters if isinstance(item, dict)}
        lot = by_type.get("MARKET_LOT_SIZE") or by_type.get("LOT_SIZE") or {}
        price_filter = by_type.get("PRICE_FILTER") or {}
        min_notional = by_type.get("MIN_NOTIONAL") or {}
        return {
            "ok": bool(row),
            "symbol": symbol,
            "status": row.get("status"),
            "quantity_precision": row.get("quantityPrecision"),
            "price_precision": row.get("pricePrecision"),
            "min_qty": lot.get("minQty"),
            "max_qty": lot.get("maxQty"),
            "step_size": lot.get("stepSize"),
            "tick_size": price_filter.get("tickSize"),
            "min_price": price_filter.get("minPrice"),
            "max_price": price_filter.get("maxPrice"),
            "min_notional": min_notional.get("notional"),
            "endpoint": "GET /fapi/v1/exchangeInfo",
            "error_type": None if row else "SYMBOL_FILTERS_MISSING",
        }


class BinanceUsdMWebSocketPrimaryTransport:
    """Primary Binance USD-M transport for signed WebSocket API requests.

    This class does not change leverage, margin mode, or cancel/modify orders.
    It only sends ``order.place`` after the caller's live gates have produced a
    candidate. Signed account reads use WebSocket API methods where possible.
    """

    def __init__(
        self,
        *,
        ws_api_url: str | None = None,
        ws_sender: Callable[..., dict[str, Any]] | None = None,
        rest_metadata_transport: BinanceUsdMLiveOrderTransport | None = None,
        clock_ms: Callable[[], int] | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.ws_api_url = (ws_api_url or binance_ws_api_url()).rstrip("/")
        self._ws_sender = ws_sender or default_ws_api_sender
        self._rest_metadata_transport = rest_metadata_transport or BinanceUsdMLiveOrderTransport(clock_ms=clock_ms)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._timeout_seconds = timeout_seconds

    def _send_signed(
        self,
        *,
        method: str,
        params: Mapping[str, Any],
        api_key: str,
        api_secret: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        request_payload = build_signed_ws_api_request(
            method=method,
            params=params,
            api_key=api_key,
            api_secret=api_secret,
            request_id=request_id,
            clock_ms=self._clock_ms,
        )
        response = self._ws_sender(
            endpoint=self.ws_api_url,
            payload=request_payload,
            timeout=self._timeout_seconds,
        )
        response_payload = response.get("response") if isinstance(response, dict) else None
        return {
            "ok": bool(response.get("ok")) if isinstance(response, dict) else False,
            "status_code": response.get("status_code") if isinstance(response, dict) else None,
            "error_type": response.get("error_type") if isinstance(response, dict) else "WS_SEND_FAILED",
            "request_id": request_payload.get("id"),
            "method": method,
            "endpoint": f"WS {method}",
            "websocket_api_url": self.ws_api_url,
            "request_redacted": redacted_json(request_payload),
            "response": response_payload if isinstance(response_payload, dict) else {},
            "response_redacted": redacted_json(response_payload if response_payload is not None else {}),
        }

    def submit_market_order(
        self,
        *,
        candidate: LiveOrderCandidate,
        api_key: str,
        api_secret: str,
    ) -> dict[str, Any]:
        client_order_id = _client_order_id(candidate)
        params: dict[str, Any] = {
            "symbol": candidate.symbol,
            "side": candidate.side,
            "type": "MARKET",
            "quantity": _format_quantity(candidate.quantity),
            "newClientOrderId": client_order_id,
        }
        if candidate.position_side:
            params["positionSide"] = candidate.position_side
        result = self._send_signed(
            method="order.place",
            params=params,
            api_key=api_key,
            api_secret=api_secret,
            request_id=client_order_id,
        )
        response_payload = _as_dict(result.get("response"))
        response_result = _as_dict(response_payload.get("result"))
        status_code = result.get("status_code")
        return {
            "submitted": bool(result.get("ok")) and status_code == 200,
            "status_code": status_code,
            "error_type": result.get("error_type"),
            "response_redacted": result.get("response_redacted", ""),
            "endpoint": "WS order.place",
            "websocket_api_url": self.ws_api_url,
            "client_order_id": response_result.get("clientOrderId") or client_order_id,
            "request_redacted": result.get("request_redacted", ""),
            "rest_fallback_used": False,
        }

    def fetch_position_mode(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        result = self._send_signed(
            method="account.position",
            params={},
            api_key=api_key,
            api_secret=api_secret,
            request_id="v2_position_mode_read",
        )
        response_payload = _as_dict(result.get("response"))
        positions = _as_list(response_payload.get("result"))
        position_sides = {
            str(row.get("positionSide") or "").upper()
            for row in positions
            if isinstance(row, dict) and row.get("positionSide")
        }
        dual_side_position = (
            True
            if {"LONG", "SHORT"} & position_sides
            else False
            if "BOTH" in position_sides
            else None
        )
        return {
            "ok": bool(result.get("ok")),
            "status_code": result.get("status_code"),
            "error_type": result.get("error_type"),
            "dual_side_position": dual_side_position,
            "endpoint": "WS account.position",
            "websocket_api_url": self.ws_api_url,
            "source": "binance_ws_api_signed_readonly",
            "response_redacted": result.get("response_redacted", ""),
        }

    def fetch_account_margin_status(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        result = self._send_signed(
            method="account.status",
            params={},
            api_key=api_key,
            api_secret=api_secret,
            request_id="v2_account_status_read",
        )
        response_payload = _as_dict(result.get("response"))
        account = _as_dict(response_payload.get("result"))
        available = _as_float(account.get("availableBalance"))
        wallet_balance = _as_float(account.get("totalWalletBalance"))
        unrealized_pnl = _as_float(account.get("totalUnrealizedProfit"))
        for asset in _as_list(account.get("assets")):
            if not isinstance(asset, dict) or str(asset.get("asset") or "").upper() != "USDT":
                continue
            available = _as_float(asset.get("availableBalance")) or available
            wallet_balance = _as_float(asset.get("walletBalance")) or wallet_balance
            unrealized_pnl = _as_float(asset.get("unrealizedProfit")) or unrealized_pnl
            break
        return {
            "ok": bool(result.get("ok")) and isinstance(account, dict),
            "status_code": result.get("status_code"),
            "error_type": result.get("error_type"),
            "can_trade": account.get("canTrade"),
            "available_balance_checked": available is not None,
            "available_balance_redacted": True,
            "wallet_balance_checked": wallet_balance is not None,
            "wallet_balance_redacted": True,
            "unrealized_pnl_checked": unrealized_pnl is not None,
            "unrealized_pnl_redacted": True,
            "_available_balance_usdt": available,
            "_wallet_balance_usdt": wallet_balance,
            "_unrealized_pnl_usdt": unrealized_pnl,
            "endpoint": "WS account.status",
            "websocket_api_url": self.ws_api_url,
            "source": "binance_ws_api_signed_readonly",
            "balances_redacted": True,
            "response_redacted": result.get("response_redacted", ""),
        }

    def fetch_symbol_filters(self, symbol: str) -> dict[str, Any]:
        status = self._rest_metadata_transport.fetch_symbol_filters(symbol)
        status["source"] = "binance_public_rest_metadata_fallback"
        status["rest_fallback_reason"] = "exchangeInfo_symbol_filters_metadata"
        return status


def _client_order_id(candidate: LiveOrderCandidate) -> str:
    digest = hashlib.sha256(
        json.dumps(candidate.lineage_payload(), sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"v2live{digest}"[:36]


def _format_quantity(quantity: float) -> str:
    text = f"{quantity:.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed.is_finite() else None


def _quantize_quantity(quantity: float, step_size: Any) -> float:
    qty = _decimal_or_none(quantity)
    step = _decimal_or_none(step_size)
    if qty is None or step is None or step <= 0:
        return quantity
    units = (qty / step).to_integral_value(rounding=ROUND_DOWN)
    return float(units * step)


def _redact_response(text: str) -> str:
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return text[:1000]
    if isinstance(payload, dict):
        for key in list(payload.keys()):
            if "key" in str(key).lower() or "secret" in str(key).lower() or "signature" in str(key).lower():
                payload[key] = "[redacted]"
        return json.dumps(payload, sort_keys=True, default=str)[:2000]
    return text[:1000]


def _best_current_signal(signals: list[dict[str, Any]], accepted: set[str]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in signals:
        symbol = str(row.get("symbol") or "").upper()
        action = str(row.get("action") or row.get("observed_action") or "").lower()
        if symbol in accepted and action in {"long", "short"}:
            candidates.append(row)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            1 if row.get("source_runtime_lane") == "v2:signals:paper" else 0,
            1 if row.get("paper_state") == "ACCEPTED_PAPER_FILL" else 0,
            1 if row.get("live_gate") == LIVE_GATE_ENABLED else 0,
            _as_float(row.get("expected_move_after_cost_bps")) or -1e9,
            _as_float(row.get("confidence")) or -1e9,
        ),
        reverse=True,
    )[0]


def _lineage_from_signal(row: Mapping[str, Any], runtime_payload: Mapping[str, Any]) -> dict[str, Any]:
    lineage_ids = _as_dict(row.get("lineage_ids"))
    return {
        "prediction_id": row.get("prediction_id") or lineage_ids.get("trainer_prediction_id"),
        "risk_decision_id": row.get("risk_decision_id") or lineage_ids.get("risk_decision_id"),
        "orchestrator_decision_id": row.get("orchestrator_decision_id") or lineage_ids.get("orchestrator_decision_id"),
        "signal_id": row.get("signal_id"),
        "live_gate_audit_id": runtime_payload.get("enable_audit_id"),
        "risk_profile_audit_id": runtime_payload.get("accepted_risk_audit_id"),
        "symbols_audit_id": runtime_payload.get("accepted_symbols_audit_id"),
        "final_approval_audit_id": runtime_payload.get("final_approval_audit_id"),
    }


def _risk_record_for_signal(risk_records: list[dict[str, Any]], signal: Mapping[str, Any]) -> dict[str, Any]:
    symbol = str(signal.get("symbol") or "").upper()
    prediction_id = str(signal.get("prediction_id") or "")
    risk_decision_id = str(signal.get("risk_decision_id") or _as_dict(signal.get("lineage_ids")).get("risk_decision_id") or "")
    for row in reversed(risk_records):
        if risk_decision_id and str(row.get("risk_decision_id") or "") == risk_decision_id:
            return row
    for row in reversed(risk_records):
        if prediction_id and str(row.get("prediction_id") or "") == prediction_id:
            return row
    for row in reversed(risk_records):
        if str(row.get("symbol") or "").upper() == symbol:
            return row
    return {}


def _position_read_ready(connectivity: Mapping[str, Any]) -> bool:
    return connectivity.get("position_read_status") in {"HTTP_200", "OK", "READY"}


def _force_disabled_by_env() -> bool:
    return os.environ.get(_TRANSPORT_DISABLED_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def _exchange_credentials_status(
    repo_root: Path,
    *,
    trader_id: str | None = None,
    credential_ref: str | None = None,
) -> dict[str, Any]:
    binding = resolve_binance_credential_binding(
        repo_root=repo_root,
        trader_id=trader_id,
        credential_ref=credential_ref,
    )
    return {
        **binding.safe_status(),
        "_api_key": binding.api_key,
        "_api_secret": binding.api_secret,
    }


def evaluate_live_order_transport(
    *,
    repo_root: Path | None = None,
    signal_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
    runtime_read: Mapping[str, Any] | None = None,
    redis_client: Any | None = None,
    transport: Any | None = None,
    submit_enabled: bool | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = _repo_root(repo_root)
    generated_est = est_now()
    runtime = runtime_read if runtime_read is not None else read_runtime_execution_state(repo_root=root)
    runtime_payload = _as_dict(runtime.get("payload"))
    runtime_validation = _as_dict(runtime.get("validation")) or validate_runtime_execution_state(runtime_payload)
    client = redis_client if redis_client is not None else _connect_redis()
    kill_switch_active, kill_switch_source = _kill_switch_active(client, runtime_payload)
    accepted_symbols = {str(item).upper() for item in runtime_payload.get("accepted_live_symbols") or []}
    signals = [_as_dict(row) for row in _as_list(signal_status.get("published_signals"))]
    selected_signal = _best_current_signal(signals, accepted_symbols)
    risk_records = _read_risk_gateway_decisions(client)
    connectivity = _as_dict(trader_status.get("binance_private_readonly"))
    env_status = _exchange_credentials_status(
        root,
        trader_id=str(runtime_payload.get("trader_id") or "") or None,
        credential_ref=str(runtime_payload.get("credential_ref") or "") or None,
    )
    runtime_write_guard_enabled = runtime_payload.get("order_transport_write_guard_enabled") is True
    release_mode_approved = live_submit_release_mode_approved(runtime_payload.get("release_mode"))
    runtime_submit_enabled = (
        runtime_payload.get("order_transport_submit_enabled") is True and release_mode_approved
    )
    transport_submit_enabled = (
        runtime_submit_enabled if submit_enabled is None else bool(submit_enabled) and release_mode_approved
    )
    transport_force_disabled = _force_disabled_by_env()
    blockers = list(runtime_validation.get("blockers") or [])
    warnings: list[str] = []
    candidate_payload: dict[str, Any] | None = None
    submit_result: dict[str, Any] | None = None
    order_submitted = False
    risk_record: dict[str, Any] = {}
    live_canary_preflight: dict[str, Any] = {
        "submit_allowed": False,
        "reason_code": "NO_CANDIDATE_EVALUATED",
        "blockers": ["NO_CANDIDATE_EVALUATED"],
        "live_canary_enabled": False,
    }
    submitter = transport or BinanceUsdMWebSocketPrimaryTransport()
    position_mode_status: dict[str, Any] = {
        "ok": None,
        "dual_side_position": None,
        "endpoint": None,
        "source": "not_checked",
    }
    account_margin_status: dict[str, Any] = {
        "ok": None,
        "available_balance_checked": False,
        "available_balance_redacted": True,
        "endpoint": None,
        "source": "not_checked",
    }

    if runtime_payload.get("live_gate") != LIVE_GATE_ENABLED:
        blockers.append("LIVE_GATE_RUNTIME_NOT_ENABLED")
    if payload_arms_live_submit(runtime_payload) and not release_mode_approved:
        blockers.append("LIVE_ORDER_TRANSPORT_RELEASE_MODE_NOT_APPROVED")
    if kill_switch_active:
        blockers.append("LIVE_ORDER_TRANSPORT_KILL_SWITCH_ACTIVE")
    if not runtime_write_guard_enabled:
        blockers.append("LIVE_ORDER_TRANSPORT_WRITE_GUARD_NOT_ENABLED")
    if not transport_submit_enabled:
        blockers.append("LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED")
    if transport_force_disabled:
        blockers.append("LIVE_ORDER_TRANSPORT_FORCE_DISABLED")
    if not env_status["api_key_present"] or not env_status["api_secret_present"]:
        blockers.append("BINANCE_CREDENTIALS_MISSING")
    else:
        fetch_position_mode = getattr(submitter, "fetch_position_mode", None)
        if callable(fetch_position_mode):
            position_mode_status = fetch_position_mode(
                api_key=str(env_status["_api_key"]),
                api_secret=str(env_status["_api_secret"]),
            )
            position_mode_status.setdefault("source", "binance_signed_readonly")
            if position_mode_status.get("ok") is not True:
                blockers.append("BINANCE_POSITION_SIDE_MODE_READ_FAILED")
        else:
            position_mode_status = {
                "ok": True,
                "dual_side_position": False,
                "endpoint": None,
                "source": "transport_no_position_mode_reader",
            }
        fetch_account_margin = getattr(submitter, "fetch_account_margin_status", None)
        if callable(fetch_account_margin):
            account_margin_status = fetch_account_margin(
                api_key=str(env_status["_api_key"]),
                api_secret=str(env_status["_api_secret"]),
            )
            account_margin_status.setdefault("source", "binance_signed_readonly")
            if account_margin_status.get("ok") is not True:
                blockers.append("BINANCE_ACCOUNT_MARGIN_READ_FAILED")
        else:
            account_margin_status = {
                "ok": True,
                "available_balance_checked": False,
                "available_balance_redacted": True,
                "endpoint": None,
                "source": "transport_no_account_margin_reader",
            }
    if not _position_read_ready(connectivity):
        blockers.append("BINANCE_POSITION_READ_NOT_READY")
    if client is None and _redis_required():
        blockers.append("LIVE_ORDER_DEDUPE_REDIS_UNAVAILABLE")
    if selected_signal is None:
        blockers.append("NO_ACCEPTED_SYMBOL_SIGNAL_CANDIDATE")
    else:
        risk_record = _risk_record_for_signal(risk_records, selected_signal)
        lineage = _lineage_from_signal(selected_signal, runtime_payload)
        if (
            risk_record.get("risk_decision_id")
            and risk_record.get("prediction_id")
            and str(risk_record.get("prediction_id")) == str(lineage.get("prediction_id") or "")
        ):
            lineage["risk_decision_id"] = risk_record.get("risk_decision_id")
        missing_lineage = [field for field in REQUIRED_LINEAGE_FIELDS if not lineage.get(field)]
        blockers.extend(f"MISSING_LINEAGE:{field}" for field in missing_lineage)
        symbol = str(selected_signal.get("symbol") or "").upper()
        action = str(selected_signal.get("action") or "").lower()
        side = "BUY" if action == "long" else "SELL" if action == "short" else ""
        position_side = (
            "LONG"
            if position_mode_status.get("dual_side_position") is True and side == "BUY"
            else "SHORT"
            if position_mode_status.get("dual_side_position") is True and side == "SELL"
            else None
        )
        price = _as_float(selected_signal.get("price_target_after_cost")) or _as_float(selected_signal.get("price_target"))
        confidence = _as_float(selected_signal.get("confidence"))
        expected_move = _as_float(selected_signal.get("expected_move_after_cost_bps"))
        profile = _as_dict(runtime_payload.get("risk_profile"))
        fields = _as_dict(profile.get("fields"))
        max_leverage = _as_float(fields.get("max_leverage")) or 1.0
        min_confidence = _as_float(fields.get("min_confidence_calibrated"))
        min_expected = _as_float(fields.get("min_expected_move_after_cost_bps"))
        filter_status: dict[str, Any] = {}
        available_balance = _as_float(account_margin_status.get("_available_balance_usdt"))
        wallet_balance = _as_float(account_margin_status.get("_wallet_balance_usdt")) or available_balance or 0.0
        fetch_filters = getattr(submitter, "fetch_symbol_filters", None)
        if symbol and callable(fetch_filters):
            filter_status = fetch_filters(symbol)
        allocation = allocate_live_candidate(
            AllocationInput(
                symbol=symbol,
                timeframe=str(selected_signal.get("timeframe") or "1m"),
                action=str(action or "hold"),
                price=float(price or 0.0),
                equity=float(wallet_balance or available_balance or 0.0),
                available_margin=float(available_balance or 0.0),
                wallet_balance=float(wallet_balance or 0.0),
                confidence_calibrated=float(confidence or 0.0),
                expected_move_after_cost_bps=float(expected_move or 0.0),
                market_state_integrity_score=float(_as_float(selected_signal.get("market_state_integrity_score")) or 0.0),
                volatility_bps=float(_as_float(selected_signal.get("volatility_bps")) or 50.0),
                liquidity_score=float(_as_float(selected_signal.get("liquidity_score")) or 1.0),
                spread_bps=float(_as_float(selected_signal.get("bid_ask_spread_bps")) or 2.0),
                slippage_bps=float(_as_float(selected_signal.get("slippage_bps")) or 2.0),
                drawdown_bps=float(_as_float(fields.get("current_drawdown_bps")) or 0.0),
                symbol_exposure_usdt=float(_as_float(selected_signal.get("symbol_exposure_usdt")) or 0.0),
                total_exposure_usdt=float(_as_float(fields.get("total_exposure_usdt")) or 0.0),
                correlation_exposure_pct=float(_as_float(selected_signal.get("correlation_exposure_pct")) or 0.0),
                regime_score=float(_as_float(selected_signal.get("regime_score")) or 1.0),
                min_qty=_as_float(filter_status.get("min_qty")),
                step_size=_as_float(filter_status.get("step_size")),
                min_notional=_as_float(filter_status.get("min_notional")),
                lineage_ids={k: lineage.get(k) for k in REQUIRED_LINEAGE_FIELDS},
            )
        )
        allocation_payload = allocation.to_payload()
        notional = allocation.target_notional_usdt
        quantity = allocation.target_quantity
        age = _age_seconds(selected_signal.get("generated_est"))
        if symbol not in accepted_symbols:
            blockers.append("SYMBOL_NOT_ACCEPTED_FOR_LIVE_EXECUTION")
        if side not in {"BUY", "SELL"}:
            blockers.append("ORDER_SIDE_NOT_DERIVED_FROM_SIGNAL")
        if price is None or price <= 0:
            blockers.append("PRICE_REFERENCE_MISSING")
        if allocation.decision.startswith("BLOCK_"):
            blockers.append(f"ADAPTIVE_ALLOCATOR_{allocation.decision}")
            min_order_adjustment = _as_float(allocation_payload.get("exchange_min_order_adjustment")) or 0.0
            if allocation.decision in {"BLOCK_EXCHANGE_MIN_ORDER", "BLOCK_INSUFFICIENT_MARGIN"} and (
                available_balance is None or available_balance < min_order_adjustment
            ):
                blockers.append("INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER")
        required_initial_margin = notional / max(max_leverage, 1.0) if notional > 0 else 0.0
        account_margin_status["required_initial_margin_usdt"] = round(required_initial_margin, 8)
        account_margin_status["required_notional_usdt"] = round(notional, 8)
        if account_margin_status.get("ok") is True and account_margin_status.get("available_balance_checked") is True:
            account_margin_status["available_balance_sufficient"] = (
                available_balance is not None and available_balance >= required_initial_margin
            )
            if available_balance is None or available_balance < required_initial_margin:
                blockers.append("INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER")
        if quantity <= 0:
            blockers.append("ORDER_QUANTITY_NOT_POSITIVE")
        if quantity > 0:
            if filter_status:
                if filter_status.get("ok") is not True:
                    blockers.append("SYMBOL_FILTERS_NOT_VERIFIED")
                elif filter_status.get("status") not in {None, "TRADING"}:
                    blockers.append("SYMBOL_NOT_TRADING")
                else:
                    adjusted_quantity = _quantize_quantity(quantity, filter_status.get("step_size"))
                    min_qty = _as_float(filter_status.get("min_qty"))
                    min_notional = _as_float(filter_status.get("min_notional"))
                    sizing = min_executable_order(
                        mark_price=price,
                        min_notional=filter_status.get("min_notional"),
                        min_qty=filter_status.get("min_qty"),
                        step_size=filter_status.get("step_size"),
                    )
                    filter_status["min_executable_order"] = sizing
                    min_executable_notional = _as_float(sizing.get("min_executable_notional"))
                    min_executable_quantity = _as_float(sizing.get("min_executable_quantity"))
                    minimum_order_notional = min_executable_notional or max(
                        min_notional or 0.0,
                        (min_qty or 0.0) * (price or 0.0),
                    )
                    if minimum_order_notional > 0 and notional < minimum_order_notional:
                        blockers.append("ADAPTIVE_NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL")
                    if adjusted_quantity <= 0:
                        blockers.append("ORDER_QUANTITY_ROUNDS_TO_ZERO")
                    elif min_executable_quantity is not None and adjusted_quantity < min_executable_quantity:
                        blockers.append("ORDER_QUANTITY_BELOW_MIN_QTY")
                    elif min_qty is not None and adjusted_quantity < min_qty:
                        blockers.append("ORDER_QUANTITY_BELOW_MIN_QTY")
                    elif min_notional is not None and adjusted_quantity * (price or 0.0) < min_notional:
                        blockers.append("ORDER_NOTIONAL_BELOW_MIN_NOTIONAL")
                    else:
                        quantity = adjusted_quantity
            else:
                blockers.append("SYMBOL_FILTERS_NOT_VERIFIED")
        if confidence is None or min_confidence is None or confidence < min_confidence:
            blockers.append("CONFIDENCE_BELOW_ACTIVE_RISK_PROFILE")
        if expected_move is None or min_expected is None or expected_move < min_expected:
            blockers.append("EXPECTED_MOVE_BELOW_ACTIVE_RISK_PROFILE")
        if age is None:
            blockers.append("SIGNAL_TIMESTAMP_MISSING")
        elif age > _MAX_SIGNAL_AGE_SECONDS:
            blockers.append("SIGNAL_STALE")
        if selected_signal.get("paper_state") != "ACCEPTED_PAPER_FILL":
            blockers.append("PAPER_FILL_EVIDENCE_NOT_ACCEPTED")
        if not risk_record:
            blockers.append("RISK_GATEWAY_DECISION_MISSING")
        elif risk_record.get("risk_action") != "allow":
            blockers.append("RISK_GATEWAY_ACTION_NOT_ALLOW")
        elif str(risk_record.get("risk_decision_id") or "") != str(lineage.get("risk_decision_id") or ""):
            blockers.append("RISK_GATEWAY_DECISION_ID_MISMATCH")
        if risk_record.get("live_blocked") is True:
            warnings.append("RISK_GATEWAY_LEGACY_LIVE_BLOCKED_TRUE_PRESENT")
        if selected_signal.get("live_gate") != runtime_payload.get("live_gate"):
            warnings.append("SIGNAL_PAYLOAD_LIVE_GATE_DIFFERS_FROM_RUNTIME_STATE")
        dedupe = _safe_redis_get_json(client, KEY_DEDUPE)
        dedupe = dedupe if isinstance(dedupe, dict) else {}
        if lineage.get("signal_id") and str(lineage["signal_id"]) in dedupe:
            blockers.append("SIGNAL_ALREADY_SUBMITTED_DEDUPE_HIT")
        candidate_payload = {
            "symbol": symbol,
            "side": side,
            "position_side": position_side,
            "quantity": quantity,
            "requested_notional_usdt": notional,
            "price_reference": price,
            "lineage": {k: lineage.get(k) for k in REQUIRED_LINEAGE_FIELDS},
            "final_approval_audit_id": lineage.get("final_approval_audit_id"),
            "expected_move_after_cost_bps": expected_move,
            "confidence": confidence,
            "source_generated_est": selected_signal.get("generated_est"),
            "source_signal_live_gate": selected_signal.get("live_gate"),
            "source_signal_live_symbols": selected_signal.get("live_symbols"),
            "risk_gateway_record": {
                "risk_action": risk_record.get("risk_action"),
                "risk_reason_code": risk_record.get("risk_reason_code"),
                "live_blocked": risk_record.get("live_blocked"),
                "legacy_live_blocked_label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2"
                if risk_record.get("live_blocked") is True
                else None,
                "risk_decision_id": risk_record.get("risk_decision_id"),
            },
            "symbol_filter_status": filter_status,
            "account_margin_status": {k: v for k, v in account_margin_status.items() if not str(k).startswith("_")},
            "adaptive_allocation": allocation_payload,
        }
        live_canary_config = LiveCanaryConfig.from_mapping(
            runtime_payload.get("live_canary_config") or runtime_payload.get("live_canary") or {}
        )
        local_position = _as_dict(
            runtime_payload.get("local_position")
            or runtime_payload.get("current_position")
            or trader_status.get("local_position")
        )
        exchange_position = _as_dict(
            connectivity.get("exchange_position")
            or trader_status.get("exchange_position")
            or runtime_payload.get("exchange_position")
        )
        open_orders = _as_list(connectivity.get("open_orders") or trader_status.get("open_orders"))
        signed_read_ts_ms = (
            connectivity.get("signed_read_ts_ms")
            or connectivity.get("position_read_ts_ms")
            or connectivity.get("account_read_ts_ms")
            or account_margin_status.get("signed_read_ts_ms")
        )
        reduce_only = bool(selected_signal.get("reduce_only"))
        selected_signal_has_trust = selected_signal.get("trust_schema_version") == "pipeline_trust_v3"
        live_canary_preflight = evaluate_live_canary_preflight(
            config=live_canary_config,
            decision=selected_signal,
            replay_snapshot_exists=bool(selected_signal.get("replay_snapshot_id")),
            mtf_snapshot_exists=bool(selected_signal.get("mtf_snapshot_id")),
            strict_pipeline_trust_ok=selected_signal_has_trust,
            pass2a_trusted_decision_ok=selected_signal_has_trust,
            runtime_payload=runtime_payload,
            local_position=local_position,
            exchange_position=exchange_position,
            open_orders=[item for item in open_orders if isinstance(item, Mapping)],
            hedge_mode=position_mode_status.get("dual_side_position"),
            margin_mode=str(
                connectivity.get("margin_mode")
                or account_margin_status.get("margin_mode")
                or runtime_payload.get("margin_mode")
                or ""
            ),
            signed_read_ts_ms=_as_float(signed_read_ts_ms),
            requested_action=action,
            symbol=symbol,
            quantity=quantity,
            notional_usd=notional,
            reduce_only=reduce_only,
            open_positions_count=int(_as_float(runtime_payload.get("open_positions_count")) or 0),
            daily_order_count=int(_as_float(runtime_payload.get("daily_order_count")) or 0),
            daily_loss_usd=float(_as_float(runtime_payload.get("daily_loss_usd")) or 0.0),
            kill_switch_active=kill_switch_active,
            human_operator_armed=runtime_payload.get("live_canary_human_armed") is True,
            lifecycle_status=_as_dict(runtime_payload.get("order_lifecycle_status")),
            leverage_mutation_attempt=runtime_payload.get("leverage_mutation_requested") is True,
            margin_mode_mutation_attempt=runtime_payload.get("margin_mode_mutation_requested") is True,
        )
        candidate_payload["live_canary_preflight"] = live_canary_preflight
        if live_canary_preflight.get("submit_allowed") is not True:
            blockers.append("LIVE_CANARY_PREFLIGHT_BLOCKED")
            blockers.extend(f"LIVE_CANARY:{reason}" for reason in live_canary_preflight.get("blockers", []))
        if not blockers:
            candidate = LiveOrderCandidate(
                symbol=symbol,
                side=side,
                quantity=quantity,
                requested_notional_usdt=notional,
                price_reference=price or 0.0,
                prediction_id=str(lineage["prediction_id"]),
                risk_decision_id=str(lineage["risk_decision_id"]),
                orchestrator_decision_id=str(lineage["orchestrator_decision_id"]),
                signal_id=str(lineage["signal_id"]),
                live_gate_audit_id=str(lineage["live_gate_audit_id"]),
                risk_profile_audit_id=str(lineage["risk_profile_audit_id"]),
                symbols_audit_id=str(lineage["symbols_audit_id"]),
                final_approval_audit_id=str(lineage["final_approval_audit_id"]),
                expected_move_after_cost_bps=expected_move,
                confidence=confidence,
                source_generated_est=str(selected_signal.get("generated_est") or ""),
                position_side=position_side,
            )
            if dry_run:
                submit_result = {
                    "submitted": False,
                    "dry_run": True,
                    "would_submit": True,
                    "endpoint": "WS order.place",
                    "websocket_api_url": binance_ws_api_url(),
                    "client_order_id": _client_order_id(candidate),
                    "rest_fallback_used": False,
                }
            else:
                submit_result = submitter.submit_market_order(
                    candidate=candidate,
                    api_key=str(env_status["_api_key"]),
                    api_secret=str(env_status["_api_secret"]),
                )
                order_submitted = bool(submit_result.get("submitted"))
                if order_submitted and client is not None:
                    dedupe[str(candidate.signal_id)] = {
                        "submitted_at_est": generated_est,
                        "client_order_id": submit_result.get("client_order_id"),
                        "symbol": candidate.symbol,
                    }
                    _safe_redis_set(client, KEY_DEDUPE, dedupe, ex=86400 * 7)

    blockers = sorted(set(str(item) for item in blockers if str(item)))
    would_submit = bool(dry_run and candidate_payload and not blockers)
    if order_submitted:
        status_text = "LIVE_ORDER_TRANSPORT_SUBMITTED"
    elif would_submit:
        status_text = "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY"
    elif submit_result is not None and not submit_result.get("submitted") and not blockers:
        status_text = "LIVE_ORDER_TRANSPORT_SUBMIT_FAILED"
    else:
        status_text = "LIVE_ORDER_TRANSPORT_BLOCKED"
    status = {
        "schema_version": "v2_binance_live_order_transport_binding_v1",
        "generated_est": generated_est,
        "status": status_text,
        "live_order_transport_bound": bool(env_status["api_key_present"] and env_status["api_secret_present"]),
        "runtime_write_guard_enabled": runtime_write_guard_enabled,
        "runtime_submit_enabled": runtime_submit_enabled,
        "transport_submit_enabled": transport_submit_enabled,
        "release_mode": runtime_payload.get("release_mode"),
        "live_submit_release_mode_approved": release_mode_approved,
        "transport_force_disabled": transport_force_disabled,
        "dry_run": bool(dry_run),
        "would_submit": would_submit,
        "writes_exchange_orders": order_submitted,
        "places_real_order": order_submitted,
        "order_submitted": order_submitted,
        "real_order_endpoint": "WS order.place" if order_submitted else None,
        "binance_transport_policy": transport_policy_snapshot(),
        "test_order_endpoint_attempted": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "transfer_or_withdrawal_attempted": False,
        "writes_old_redis": False,
        "redis_trim_attempted": False,
        "legacy_restart_attempted": False,
        "raw_credentials_exposed": False,
        "required_lineage_fields": list(REQUIRED_LINEAGE_FIELDS),
        "accepted_symbols": sorted(accepted_symbols),
        "runtime_state_validation": runtime_validation,
        "runtime_state_source": runtime.get("source"),
        "kill_switch_active": kill_switch_active,
        "kill_switch_source": kill_switch_source,
        "credential_status": {k: v for k, v in env_status.items() if not k.startswith("_")},
        "position_read_status": connectivity.get("position_read_status"),
        "position_mode_status": position_mode_status,
        "account_margin_status": {k: v for k, v in account_margin_status.items() if not str(k).startswith("_")},
        "selected_candidate": candidate_payload,
        "live_canary_preflight": live_canary_preflight,
        "submit_result": submit_result,
        "warnings": sorted(set(warnings)),
        "blockers": blockers,
    }
    _persist_transport_status(root, status, redis_client=client)
    return status


def _persist_transport_status(repo_root: Path, status: Mapping[str, Any], *, redis_client: Any) -> None:
    _safe_redis_set(redis_client, KEY_STATUS, status, ex=300)
    audit_row = {
        "generated_est": status.get("generated_est"),
        "status": status.get("status"),
        "order_submitted": status.get("order_submitted"),
        "selected_candidate": status.get("selected_candidate"),
        "blockers": status.get("blockers"),
        "warnings": status.get("warnings"),
        "raw_credentials_exposed": False,
    }
    _safe_redis_set(redis_client, KEY_AUDIT, audit_row, ex=86400 * 7)
    for base in (repo_root / PUBLIC_ARTIFACT_REL, repo_root / WORKLOG_ARTIFACT_REL):
        _write_json_atomic(base / "binance_order_transport_binding_status.json", status)
        _write_json_atomic(base / "live_order_transport_audit_status.json", audit_row)
        _write_json_atomic(
            base / "live_order_transport_kill_switch_status.json",
            {
                "generated_est": status.get("generated_est"),
                "kill_switch_active": status.get("kill_switch_active"),
                "kill_switch_source": status.get("kill_switch_source"),
                "status": "KILL_SWITCH_CLEAR" if not status.get("kill_switch_active") else "KILL_SWITCH_ACTIVE",
            },
        )
