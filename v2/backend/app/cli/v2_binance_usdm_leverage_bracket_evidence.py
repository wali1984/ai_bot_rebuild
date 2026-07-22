"""Fetch authenticated read-only Binance USD-M account evidence.

The base command calls signed USER_DATA ``GET /fapi/v1/leverageBracket`` via
the existing adapter.  When an explicit commission CAS root is supplied, its
loop interleaves one adaptively paced ``GET /fapi/v1/commissionRate`` at a
time.  It never submits/cancels/modifies an order and never changes leverage
or margin mode.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from v2.backend.app.services import (
    binance_usdm_leverage_bracket_runtime_credentials as runtime_credentials,
)
from v2.backend.app.services.binance_usdm_commission_evidence_broker import (
    CommissionEvidenceBrokerError,
    adaptive_commission_request_pacing_ms,
    capture_and_publish_next_commission_evidence,
    default_commission_broker_store,
    read_adaptive_commission_rotation_universe,
)
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
SYSTEMD_CREDENTIALS_DIRECTORY_ENV = runtime_credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV
TRADER_ID_ENV = runtime_credentials.TRADER_ID_ENV
CREDENTIAL_REF_ENV = runtime_credentials.CREDENTIAL_REF_ENV
BASE_URL_ENV = runtime_credentials.BASE_URL_ENV
EVIDENCE_AUTH_KEY_ID_ENV = runtime_credentials.EVIDENCE_AUTH_KEY_ID_ENV
EVIDENCE_HMAC_SYSTEMD_CREDENTIAL = runtime_credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL
MAX_SYSTEMD_CREDENTIAL_BYTES = runtime_credentials.MAX_SYSTEMD_CREDENTIAL_BYTES
_adapter_and_security_context_from_systemd_credentials = (
    runtime_credentials.adapter_and_security_context_from_systemd_credentials
)


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
        "credential_ref_read_only_assertion": payload.get("credential_ref_read_only_assertion"),
        "credential_ref_read_only_assertion_semantics": payload.get(
            "credential_ref_read_only_assertion_semantics"
        ),
        "exchange_key_permissions_proven_by_connector": payload.get(
            "exchange_key_permissions_proven_by_connector"
        ),
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
    commission_runner: Callable[[tuple[str, ...]], dict[str, Any]] | None = None,
    on_commission_result: Callable[[dict[str, Any]], None] | None = None,
    monotonic_fn: Callable[[], float] = time.monotonic,
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
        latest_commission: dict[str, Any] | None = None
        if commission_runner is not None:
            published = tuple(str(item) for item in latest.get("symbols_published", ()))
            if published:
                latest_commission = commission_runner(published)
                if on_commission_result is not None:
                    on_commission_result(latest_commission)
        if max_cycles is not None and cycles >= max_cycles:
            break
        if commission_runner is None:
            stopper.wait(interval_seconds)
            continue
        bracket_due = monotonic_fn() + interval_seconds
        while not stopper.is_set():
            if latest_commission is None:
                wait_seconds = max(0.0, bracket_due - monotonic_fn())
            elif latest_commission.get("status") == "READY":
                wait_seconds = float(latest_commission.get("pacing_ms", 0)) / 1_000.0
            elif latest_commission.get("status") == "DEFERRED":
                wait_seconds = float(latest_commission.get("claim_ttl_ms", 0)) / 1_000.0
            else:
                raise RuntimeError("COMMISSION_BROKER_LOOP_RESULT_INVALID")
            remaining = bracket_due - monotonic_fn()
            if remaining <= 0:
                break
            if not 0 < wait_seconds <= remaining:
                wait_seconds = remaining
            if stopper.wait(wait_seconds):
                break
            if monotonic_fn() >= bracket_due:
                break
            published = tuple(str(item) for item in latest.get("symbols_published", ()))
            latest_commission = commission_runner(published)
            if on_commission_result is not None:
                on_commission_result(latest_commission)
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
        "--commission-broker-data-root",
        type=Path,
        default=None,
        help=(
            "absolute durable CAS root; when supplied, interleave one adaptive "
            "commission GET at a time between bracket refreshes"
        ),
    )
    parser.add_argument(
        "--commission-priority-symbol",
        action="append",
        default=[],
        help="optional currently demanded symbol; never expands the bracket-authenticated universe",
    )
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

    try:
        if SYSTEMD_CREDENTIALS_DIRECTORY_ENV in os.environ:
            adapter, security_context = _adapter_and_security_context_from_systemd_credentials()
        else:
            adapter = BinanceUSDMAdapter.from_env()
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
    commission_runner: Callable[[tuple[str, ...]], dict[str, Any]] | None = None
    if args.commission_broker_data_root is not None:
        data_root = args.commission_broker_data_root
        if not data_root.is_absolute():
            parser.error("--commission-broker-data-root must be absolute")
        commission_store = default_commission_broker_store(data_root)

        def commission_runner(published_symbols: tuple[str, ...]) -> dict[str, Any]:
            pacing_ms = adaptive_commission_request_pacing_ms(os.environ)
            universe = read_adaptive_commission_rotation_universe(redis_client)
            if universe.get("status") != "READY":
                return {
                    "status": "DEFERRED",
                    "reason": universe.get("status"),
                    "claim_ttl_ms": pacing_ms,
                    "request_executed": False,
                    "request_count": 0,
                }
            authenticated = set(published_symbols)
            selected = tuple(
                symbol for symbol in universe["symbols"] if symbol in authenticated
            )
            if not selected:
                return {
                    "status": "DEFERRED",
                    "reason": "DYNAMIC_COMMISSION_UNIVERSE_NOT_BRACKET_AUTHENTICATED",
                    "claim_ttl_ms": pacing_ms,
                    "request_executed": False,
                    "request_count": 0,
                }
            try:
                return capture_and_publish_next_commission_evidence(
                    adapter=adapter,
                    redis_client=redis_client,
                    store=commission_store,
                    security_context=security_context,
                    symbols=selected,
                    priority_symbols=args.commission_priority_symbol,
                    environ=os.environ,
                )
            except Exception as exc:  # noqa: BLE001 - isolate bracket service
                reason = (
                    exc.reason
                    if isinstance(exc, CommissionEvidenceBrokerError)
                    else f"COMMISSION_BROKER_TURN_EXCEPTION_{type(exc).__name__.upper()}"
                )
                return {
                    "status": "DEFERRED",
                    "reason": reason,
                    "claim_ttl_ms": pacing_ms,
                }

    def emit_commission(payload: dict[str, Any]) -> None:
        safe = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "evidence",
                "raw_response_bytes",
                "fee_artifact_bytes",
                "fee_schedule_receipt",
            }
        }
        print(json.dumps(safe, indent=2 if args.json else None, sort_keys=True))

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
                commission_runner=commission_runner,
                on_commission_result=emit_commission,
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
        if commission_runner is not None and payload.get("symbols_published"):
            emit_commission(
                commission_runner(tuple(str(item) for item in payload["symbols_published"]))
            )
    return 0 if payload.get("status") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
