"""CoinGlass provider loop with endpoint registry and token-bucket limits."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from app.services.coinglass_provider.client import CoinGlassClient
from app.services.coinglass_provider.endpoint_registry import (
    CoinGlassEndpointSpec,
    coinglass_endpoint_registry,
    registry_payload,
)
from app.services.coinglass_provider.publisher import publish_coinglass_result
from app.services.coinglass_provider.rate_limit import (
    COINGLASS_NORMAL_LIMIT_PER_MINUTE,
    CoinGlassRateLimiter,
)

SCHEDULER_STATUS_KEY = "v2:provider:coinglass:scheduler_status"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_coinglass_provider_loop")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )
    parser.add_argument(
        "--symbols",
        default=os.environ.get(
            "COINGLASS_SYMBOLS",
            "BTCUSDT,ETHUSDT,SOLUSDT",
        ),
    )
    parser.add_argument("--timeframe", default=os.environ.get("COINGLASS_TIMEFRAME", "1m"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import bootstrap_process_env

        bootstrap_process_env(apply=True)
    except Exception:  # noqa: S110 - preserve startup fallback to process env
        pass  # fall back to whatever the process env already carries
    redis_client = _redis_client(args.redis_url)
    symbols = _symbols(args.symbols)
    client = CoinGlassClient(limiter=CoinGlassRateLimiter())
    scheduler_state: dict[str, float] = {}
    while True:
        report = run_once(
            redis_client,
            client=client,
            symbols=symbols,
            timeframe=args.timeframe,
            scheduler_state=scheduler_state,
            force=args.once,
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        if args.once:
            return 0
        time.sleep(max(1.0, args.sleep_seconds))


def run_once(
    redis_client: Any | None,
    *,
    client: CoinGlassClient,
    symbols: list[str],
    timeframe: str = "1m",
    scheduler_state: dict[str, float] | None = None,
    force: bool = True,
    now_monotonic: float | None = None,
    disabled_endpoints: frozenset[str] | None = None,
) -> dict[str, Any]:
    plan = coinglass_scheduler_plan(symbols)
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    request_count = 0
    disabled = (
        disabled_endpoints
        if disabled_endpoints is not None
        else _disabled_endpoints_from_env()
    )
    now_value = time.monotonic() if now_monotonic is None else float(now_monotonic)
    for spec in coinglass_endpoint_registry():
        if spec.group == "exchange_metadata":
            continue
        if spec.endpoint_id in disabled:
            continue
        due_symbols: list[tuple[str, str]] = []
        for symbol in symbols[: _max_symbols_for_endpoint(spec, symbols)]:
            cadence_seconds = _cadence_seconds_for_symbol(spec, symbols=symbols, symbol=symbol)
            state_key = f"{spec.endpoint_id}:{symbol}"
            last_polled = scheduler_state.get(state_key) if scheduler_state is not None else None
            if (
                scheduler_state is not None
                and not force
                and last_polled is not None
                and now_value - float(last_polled) < cadence_seconds
            ):
                skipped.append(
                    {
                        "endpoint_id": spec.endpoint_id,
                        "symbol": symbol,
                        "cadence_seconds": cadence_seconds,
                        "seconds_until_due": max(
                            0.0,
                            cadence_seconds - (now_value - float(last_polled)),
                        ),
                    }
                )
                continue
            due_symbols.append((symbol, state_key))

        if not due_symbols:
            continue
        if spec.response_scope == "all_symbols":
            response = client.get(spec, symbol=None)
            request_count += 1
            for symbol, state_key in due_symbols:
                if scheduler_state is not None:
                    scheduler_state[state_key] = now_value
                result = publish_coinglass_result(
                    redis_client,
                    env=os.environ,
                    spec=spec,
                    symbol=symbol,
                    http_status=response.http_status,
                    payload=response.payload,
                    rate_limit_status=client.limiter.as_dict(),
                    error_class=response.error_class,
                    timeframe=timeframe,
                )
                results.append(result)
            continue

        for symbol, state_key in due_symbols:
            response = client.get(spec, symbol=symbol)
            request_count += 1
            if scheduler_state is not None:
                scheduler_state[state_key] = now_value
            result = publish_coinglass_result(
                redis_client,
                env=os.environ,
                spec=spec,
                symbol=symbol,
                http_status=response.http_status,
                payload=response.payload,
                rate_limit_status=client.limiter.as_dict(),
                error_class=response.error_class,
                timeframe=timeframe,
            )
            results.append(result)
    status = {
        "schema_version": "coinglass_provider_scheduler_status_v1",
        "provider": "coinglass",
        "generated_utc": _now(),
        "symbols": symbols,
        "timeframe": timeframe,
        "registry": registry_payload(),
        "schedule_plan": plan,
        "result_count": len(results),
        "request_count": request_count,
        "disabled_endpoints": sorted(disabled),
        "skipped_not_due_count": len(skipped),
        "skipped_not_due": skipped[:50],
        "actual_payload_results": sum(1 for row in results if row.get("actual_payload_present")),
        "heartbeat_only_green_allowed": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    if redis_client is not None:
        redis_client.set(
            SCHEDULER_STATUS_KEY,
            json.dumps(status, sort_keys=True, default=str),
            ex=300,
        )
    return status


def coinglass_scheduler_plan(symbols: list[str]) -> dict[str, Any]:
    endpoint_rows = []
    total_budget = 0
    for spec in coinglass_endpoint_registry():
        symbols_per_cycle = _max_symbols_for_endpoint(spec, symbols)
        scheduled_symbol_count = max(0, len(symbols[:symbols_per_cycle]))
        if spec.response_scope == "all_symbols":
            endpoint_budget = min(spec.rate_budget_per_minute, int(scheduled_symbol_count > 0))
        else:
            endpoint_budget = min(spec.rate_budget_per_minute, scheduled_symbol_count)
        total_budget += endpoint_budget
        endpoint_rows.append(
            {
                "endpoint_id": spec.endpoint_id,
                "group": spec.group,
                "cadence_seconds_top_symbols": spec.cadence_seconds_top_symbols,
                "cadence_seconds_active_symbols": spec.cadence_seconds_active_symbols,
                "cadence_seconds_full_universe": spec.cadence_seconds_full_universe,
                "request_budget_per_minute": spec.rate_budget_per_minute,
                "response_scope": spec.response_scope,
                "scheduled_symbols_per_cycle": symbols_per_cycle,
                "estimated_requests_per_cycle": endpoint_budget,
                "feature_outputs": list(spec.feature_outputs),
            }
        )
    return {
        "schema_version": "coinglass_scheduler_plan_v1",
        "public_limit_per_minute": 300,
        "normal_limit_per_minute": COINGLASS_NORMAL_LIMIT_PER_MINUTE,
        "scheduled_request_budget_per_minute": min(total_budget, COINGLASS_NORMAL_LIMIT_PER_MINUTE),
        "never_exceeds_public_limit": min(total_budget, COINGLASS_NORMAL_LIMIT_PER_MINUTE) <= 285,
        "manual_reserve_per_minute": 15,
        "health_reserve_per_minute": 5,
        "endpoints": endpoint_rows,
    }


def _max_symbols_for_endpoint(spec: CoinGlassEndpointSpec, symbols: list[str]) -> int:
    if spec.supports_batch:
        return min(len(symbols), 5)
    if spec.cadence_seconds_top_symbols <= 30:
        return min(len(symbols), 3)
    return min(len(symbols), 5)


def _cadence_seconds_for_symbol(
    spec: CoinGlassEndpointSpec,
    *,
    symbols: list[str],
    symbol: str,
) -> int:
    try:
        index = [str(item).upper() for item in symbols].index(str(symbol).upper())
    except ValueError:
        index = len(symbols)
    if index < 5:
        return spec.cadence_seconds_top_symbols
    if index < 25:
        return spec.cadence_seconds_active_symbols
    return spec.cadence_seconds_full_universe


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _disabled_endpoints_from_env() -> frozenset[str]:
    raw = os.environ.get("COINGLASS_DISABLED_ENDPOINTS", "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def _symbols(raw: str) -> list[str]:
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
