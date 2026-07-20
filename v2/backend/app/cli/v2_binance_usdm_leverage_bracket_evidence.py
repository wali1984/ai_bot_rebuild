"""Fetch and cache read-only Binance USD-M leverage-bracket evidence.

This command only calls signed USER_DATA ``GET /fapi/v1/leverageBracket`` via
the existing adapter.  It never submits/cancels/modifies an order and never
changes leverage or margin mode.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from collections.abc import Callable, Iterable
from typing import Any

from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_FRESHNESS_SECONDS,
    STATUS_SCHEMA_VERSION,
    EvidenceSecurityContext,
    LeverageBracketEvidenceError,
    evidence_security_context_for_adapter,
    fetch_and_cache_leverage_brackets,
)
from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

DEFAULT_INTERVAL_SECONDS = 300


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis
    except Exception:
        return None
    url = (
        redis_url
        or os.environ.get("V2_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0"
    )
    try:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=5.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _parse_symbols(values: Iterable[str]) -> tuple[str, ...]:
    symbols: list[str] = []
    for value in values:
        symbols.extend(item.strip() for item in str(value).split(",") if item.strip())
    return tuple(symbols)


def public_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Return safe binding identifiers while excluding all secret material."""

    return {
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "adapter_status": payload.get("adapter_status"),
        "source_endpoint": payload.get("source_endpoint"),
        "security_type": payload.get("security_type"),
        "exchange_environment": payload.get("exchange_environment"),
        "credential_binding_id": payload.get("credential_binding_id"),
        "trader_id": payload.get("trader_id"),
        "credential_ref": payload.get("credential_ref"),
        "evidence_auth_algorithm": payload.get("evidence_auth_algorithm"),
        "evidence_auth_key_id": payload.get("evidence_auth_key_id"),
        "fetched_at": payload.get("fetched_at"),
        "generated_at": payload.get("generated_at"),
        "available_at": payload.get("available_at"),
        "symbols_requested": payload.get("symbols_requested", []),
        "symbols_received": payload.get("symbols_received", []),
        "symbols_published": payload.get("symbols_published", []),
        "missing_symbols": payload.get("missing_symbols", []),
        "invalid_symbols": payload.get("invalid_symbols", []),
        "redis_write_failed_symbols": payload.get("redis_write_failed_symbols", []),
        "read_only": True,
        "safe_binding_identifiers_exposed": True,
        "credential_fields_exposed": False,
        "credential_fields_exposed_semantics": (
            "NO_EXCHANGE_API_KEY_SECRET_OR_SIGNED_REQUEST_FIELDS;"
            "SAFE_BINDING_IDENTIFIERS_ARE_EXPOSED"
        ),
        "evidence_auth_key_exposed": False,
        "exchange_api_secret_exposed": False,
        "raw_response_exposed": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def run_once(
    *,
    adapter: Any,
    redis_client: Any,
    security_context: EvidenceSecurityContext | None,
    symbols: Iterable[str] = (),
    execute: bool = True,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    return fetch_and_cache_leverage_brackets(
        adapter=adapter,
        redis_client=redis_client,
        security_context=security_context,
        symbols=symbols,
        execute=execute,
        freshness_seconds=freshness_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def run_loop(
    *,
    adapter: Any,
    redis_client: Any,
    security_context: EvidenceSecurityContext | None,
    symbols: Iterable[str] = (),
    execute: bool = True,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if interval_seconds <= 0:
        raise ValueError("INTERVAL_SECONDS_MUST_BE_POSITIVE")
    stopper = stop_event or threading.Event()
    cycles = 0
    latest: dict[str, Any] = {}
    while not stopper.is_set():
        latest = run_once(
            adapter=adapter,
            redis_client=redis_client,
            security_context=security_context,
            symbols=symbols,
            execute=execute,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        cycles += 1
        if on_result is not None:
            on_result(latest)
        if max_cycles is not None and cycles >= max_cycles:
            break
        stopper.wait(interval_seconds)
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one cycle (default)")
    mode.add_argument("--loop", action="store_true", help="poll until interrupted")
    parser.add_argument(
        "--symbols",
        action="append",
        default=[],
        help="comma-separated symbols; omitted requests the account's full bracket list",
    )
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--freshness-seconds", type=int, default=DEFAULT_FRESHNESS_SECONDS)
    parser.add_argument("--cache-ttl-seconds", type=int, default=DEFAULT_CACHE_TTL_SECONDS)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="build the signed adapter contract without making the read-only GET",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    symbols = _parse_symbols(args.symbols)

    def emit(payload: dict[str, Any]) -> None:
        view = public_status(payload)
        print(json.dumps(view, indent=2 if args.json else None, sort_keys=True))

    adapter = BinanceUSDMAdapter.from_env()
    try:
        security_context = evidence_security_context_for_adapter(adapter)
    except LeverageBracketEvidenceError as exc:
        emit(
            {
                "schema_version": STATUS_SCHEMA_VERSION,
                "status": "BLOCKED",
                "reason": str(exc),
                "source_endpoint": "/fapi/v1/leverageBracket",
                "security_type": "USER_DATA",
                "symbols_requested": list(symbols),
                "symbols_received": [],
                "symbols_published": [],
                "missing_symbols": [],
                "invalid_symbols": [],
                "redis_write_failed_symbols": [],
            }
        )
        return 2
    redis_client = _redis_client(args.redis_url)

    if args.loop:
        try:
            payload = run_loop(
                adapter=adapter,
                redis_client=redis_client,
                security_context=security_context,
                symbols=symbols,
                execute=not args.no_execute,
                freshness_seconds=args.freshness_seconds,
                cache_ttl_seconds=args.cache_ttl_seconds,
                interval_seconds=args.interval_seconds,
                on_result=emit,
            )
        except KeyboardInterrupt:
            return 130
    else:
        payload = run_once(
            adapter=adapter,
            redis_client=redis_client,
            security_context=security_context,
            symbols=symbols,
            execute=not args.no_execute,
            freshness_seconds=args.freshness_seconds,
            cache_ttl_seconds=args.cache_ttl_seconds,
        )
        emit(payload)
    return 0 if payload.get("status") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
