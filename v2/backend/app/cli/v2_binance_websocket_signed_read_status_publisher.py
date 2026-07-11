"""Publish Binance WebSocket API signed-read status for live dry-runs.

This CLI performs read-only Binance USD-M WebSocket API calls through the
existing adapter and writes the redacted status contract consumed by
``v2_live_canary_dry_run``. It never calls order/test-order/cancel/modify,
leverage, margin, transfer, or withdrawal endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

REDIS_STATUS_KEY = "v2:binance:websocket_signed_read_status"
SCHEMA_VERSION = "binance_websocket_signed_read_status_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _response_result(result: Mapping[str, Any]) -> Any:
    response = _as_dict(result.get("response_json"))
    return response.get("result")


def _account_status_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    body = _response_result(result)
    account = _as_dict(body)
    assets = _as_list(account.get("assets"))
    positions = _as_list(account.get("positions"))
    return {
        "canTrade": account.get("canTrade"),
        "canDeposit": account.get("canDeposit"),
        "canWithdraw": account.get("canWithdraw"),
        "feeTier": account.get("feeTier"),
        "accountType": account.get("accountType"),
        "availableBalance": account.get("availableBalance"),
        "totalWalletBalance": account.get("totalWalletBalance"),
        "totalMarginBalance": account.get("totalMarginBalance"),
        "totalUnrealizedProfit": account.get("totalUnrealizedProfit"),
        "totalInitialMargin": account.get("totalInitialMargin"),
        "totalMaintMargin": account.get("totalMaintMargin"),
        "dualSidePosition": account.get("dualSidePosition"),
        "multiAssetsMargin": account.get("multiAssetsMargin"),
        "assets_present_count": len(assets),
        "positions_present_count": len(positions),
        "balances_redacted": False,
        "raw_account_payload_stored": False,
    }


def _position_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    body = _response_result(result)
    rows = [row for row in _as_list(body) if isinstance(row, Mapping)]
    open_rows = [
        row
        for row in rows
        if abs(float(row.get("positionAmt") or row.get("positionAmt".lower()) or 0.0)) > 0.0
    ]
    return {
        "positions_present_count": len(rows),
        "open_positions_count": len(open_rows),
        "position_sides_present": sorted(
            {
                str(row.get("positionSide") or "").upper()
                for row in rows
                if row.get("positionSide")
            }
        ),
        "raw_position_payload_stored": False,
    }


def _balance_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    body = _response_result(result)
    rows = [row for row in _as_list(body) if isinstance(row, Mapping)]
    assets = sorted(
        {str(row.get("asset") or "").upper() for row in rows if row.get("asset")}
    )
    by_asset = {
        str(row.get("asset") or "").upper(): row
        for row in rows
        if row.get("asset")
    }
    usdt = _as_dict(by_asset.get("USDT"))

    def _sum(field: str) -> float | None:
        values = [_float(row.get(field)) for row in rows]
        clean = [value for value in values if value is not None]
        return round(sum(clean), 8) if clean else None

    return {
        "assets_present_count": len(rows),
        "assets_present_sample": assets[:20],
        "usdt_balance": usdt.get("balance"),
        "usdt_cross_wallet_balance": usdt.get("crossWalletBalance"),
        "usdt_cross_unrealized_pnl": usdt.get("crossUnPnl"),
        "usdt_available_balance": usdt.get("availableBalance"),
        "total_balance_usd_equivalent": _sum("balance"),
        "total_cross_wallet_balance_usd_equivalent": _sum("crossWalletBalance"),
        "total_cross_unrealized_pnl_usd_equivalent": _sum("crossUnPnl"),
        "total_available_balance_usd_equivalent": _sum("availableBalance"),
        "raw_balance_payload_stored": False,
    }


def _result_contract(method: str, result: Mapping[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    summary = (
        _account_status_summary(result)
        if method == "account.status"
        else _position_summary(result)
        if method == "account.position"
        else _balance_summary(result)
        if method == "account.balance"
        else {}
    )
    return {
        "method": method,
        "status": status,
        "ws_status_code": result.get("ws_status_code"),
        "error_type": result.get("error_type"),
        "endpoint": result.get("endpoint"),
        "transport": "websocket_api_primary",
        "ok": status == "SIGNED_WS_READ_EXECUTED",
        "response_summary": summary,
        "api_key_exposed": False,
        "api_secret_exposed": False,
        "raw_response_stored": False,
        "places_real_order": False,
    }


def build_status(*, execute: bool = True) -> dict[str, Any]:
    adapter = BinanceUSDMAdapter.from_env()
    results: dict[str, dict[str, Any]] = {}
    for method in ("account.status", "account.balance", "account.position"):
        if not adapter.has_credentials:
            raw: dict[str, Any] = {
                "status": "SIGNED_WS_READ_BLOCKED_MISSING_ENV",
                "ws_status_code": None,
                "error_type": "MISSING_CREDENTIALS",
                "endpoint": None,
            }
        else:
            raw = adapter.signed_ws_read(method, execute=execute)
        results[method] = _result_contract(method, raw)
    ready = all(row.get("ok") is True for row in results.values())
    generated = _utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "signed_read_overall_status": (
            "WEBSOCKET_PRIMARY_READY" if ready else "WEBSOCKET_PRIMARY_BLOCKED_OR_ERROR"
        ),
        "signed_ws_read_results": results,
        "has_credentials": adapter.has_credentials,
        "transport": "websocket_api_primary",
        "execute": bool(execute),
        "redis_key": REDIS_STATUS_KEY,
        "raw_credentials_exposed": False,
        "api_key_exposed": False,
        "api_secret_exposed": False,
        "places_real_order": False,
        "test_order_submitted": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "transfer_or_withdrawal": False,
    }


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = redis_url or os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def publish_status(payload: Mapping[str, Any], *, redis_url: str | None = None, ttl_seconds: int = 900) -> bool:
    client = _redis_client(redis_url)
    if client is None:
        return False
    try:
        client.set(REDIS_STATUS_KEY, json.dumps(payload, sort_keys=True, default=str), ex=int(ttl_seconds))
        return True
    except Exception:
        return False


def _public_view(payload: Mapping[str, Any], *, published: bool) -> dict[str, Any]:
    results = _as_dict(payload.get("signed_ws_read_results"))
    return {
        "schema_version": payload.get("schema_version"),
        "generated_utc": payload.get("generated_utc"),
        "signed_read_overall_status": payload.get("signed_read_overall_status"),
        "methods": {
            method: {
                "status": _as_dict(row).get("status"),
                "ws_status_code": _as_dict(row).get("ws_status_code"),
                "error_type": _as_dict(row).get("error_type"),
                "transport": _as_dict(row).get("transport"),
            }
            for method, row in results.items()
        },
        "has_credentials": payload.get("has_credentials"),
        "redis_published": published,
        "redis_key": REDIS_STATUS_KEY,
        "raw_credentials_exposed": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-execute", action="store_true", help="build contracts without executing WebSocket reads")
    parser.add_argument("--write-redis", action="store_true", help=f"write {REDIS_STATUS_KEY}")
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--ttl-seconds", type=int, default=900)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = build_status(execute=not args.no_execute)
    published = publish_status(payload, redis_url=args.redis_url, ttl_seconds=args.ttl_seconds) if args.write_redis else False
    view = _public_view(payload, published=published)
    if args.json:
        print(json.dumps(view, indent=2, sort_keys=True))
    else:
        print(json.dumps(view, sort_keys=True))
    return 0 if payload.get("signed_read_overall_status") == "WEBSOCKET_PRIMARY_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
