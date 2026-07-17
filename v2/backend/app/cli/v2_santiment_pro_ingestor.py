"""V2 Santiment Pro background ingestor CLI.

Writes only V2-prefixed Santiment alt-data keys:

- ``v2:altdata:santiment:status``
- ``v2:altdata:santiment:state``
- ``v2:altdata:santiment:symbol:{symbol}``

The worker is paper/shadow only. It never places, cancels, or modifies
orders and never changes leverage, margin, transfers, or live gates.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.alternative_data.santiment_client import (
    DEFAULT_EXECUTION_INTERVAL_SECONDS,
    DEFAULT_INTERVAL,
    DEFAULT_LOOKBACK,
    DEFAULT_METRICS,
    DEFAULT_REDIS_STATUS_TTL_SECONDS,
    DEFAULT_TO,
    KEY_STATUS,
    SANTIMENT_API_KEY_NAMES,
    SantimentProClient,
    build_key_missing_status,
    fetch_normalize_publish_once,
    resolve_api_key,
    safe_redis_set,
    sanitize_metrics,
    utc_iso,
)
from v2.backend.app.services.safe_env_loader import (
    KEY_PRESENT,
    bootstrap_process_env,
)

GO_READY = "V2_SANTIMENT_PRO_INGESTOR_READY"
GO_BLOCKED = "V2_SANTIMENT_PRO_INGESTOR_BLOCKED"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_santiment_pro_ingestor/latest/v2_santiment_pro_ingestor_status.json"
)
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_santiment_pro_ingestor/latest/v2_santiment_pro_ingestor_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_santiment_pro_ingestor/latest/operator_dashboard_payload.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _write_status_files(payload: dict[str, Any], paths: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def _parse_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


async def run_once_async(
    *,
    symbols: tuple[str, ...],
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    redis_client=None,
    dry_run: bool = False,
    interval: str = DEFAULT_INTERVAL,
    from_expr: str = DEFAULT_LOOKBACK,
    to_expr: str = DEFAULT_TO,
    http_post=None,
    out_paths: tuple[Path, ...] = (
        WORKLOG_STATUS,
        PUBLIC_OPERATOR_RUNTIME,
        PUBLIC_DASHBOARD,
    ),
) -> dict[str, Any]:
    env_report = bootstrap_process_env(names=SANTIMENT_API_KEY_NAMES)
    key_present = any(
        env_report.get("keys", {}).get(name) == KEY_PRESENT
        for name in SANTIMENT_API_KEY_NAMES
    )
    redis_write_results: dict[str, bool] = {}
    clean_metrics = sanitize_metrics(metrics)
    if dry_run or not key_present:
        status = build_key_missing_status(
            generated_utc=utc_iso(),
            symbol_count=len(symbols),
            redis_write_results=redis_write_results,
        )
        status["go_no_go"] = GO_READY
        status["dry_run"] = bool(dry_run)
        status["key_present"] = bool(key_present)
        if dry_run:
            status["source_status_counts"] = {
                "DRY_RUN_NO_NETWORK": len(symbols),
            }
            status["rate_limit_state"]["last_response_status"] = "DRY_RUN_NO_NETWORK"
        status["env_loader_report"] = {
            "keys": env_report.get("keys", {}),
            "bound_names": env_report.get("bound_names", []),
            "absent_names": env_report.get("absent_names", []),
            "source_paths_existing": env_report.get("source_paths_existing", []),
            "values_exposed": False,
        }
        redis_write_results[KEY_STATUS] = safe_redis_set(
            redis_client,
            KEY_STATUS,
            status,
            ex=DEFAULT_REDIS_STATUS_TTL_SECONDS,
        )
        status["redis_write_results"] = redis_write_results
        _write_status_files(status, out_paths)
        return {"status_payload": status, "symbol_payloads": {}}

    api_key = resolve_api_key()
    if not api_key:
        status = build_key_missing_status(
            generated_utc=utc_iso(),
            symbol_count=len(symbols),
            redis_write_results=redis_write_results,
        )
        status["go_no_go"] = GO_BLOCKED
        status["blocked_reason"] = "KEY_PRESENT_BY_NAME_BUT_VALUE_NOT_RESOLVED"
        _write_status_files(status, out_paths)
        return {"status_payload": status, "symbol_payloads": {}}

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if http_post is not None:
        client_kwargs["http_post"] = http_post
    client = SantimentProClient(**client_kwargs)
    result = await fetch_normalize_publish_once(
        client=client,
        redis_client=redis_client,
        symbols=symbols,
        metrics=clean_metrics,
        interval=interval,
        from_expr=from_expr,
        to_expr=to_expr,
    )
    status = result["status_payload"]
    status["env_loader_report"] = {
        "keys": env_report.get("keys", {}),
        "bound_names": env_report.get("bound_names", []),
        "absent_names": env_report.get("absent_names", []),
        "source_paths_existing": env_report.get("source_paths_existing", []),
        "values_exposed": False,
    }
    _write_status_files(status, out_paths)
    return result


def run_once(
    *,
    symbols: tuple[str, ...],
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    redis_client=None,
    dry_run: bool = False,
    interval: str = DEFAULT_INTERVAL,
    from_expr: str = DEFAULT_LOOKBACK,
    to_expr: str = DEFAULT_TO,
    http_post=None,
    out_paths: tuple[Path, ...] = (
        WORKLOG_STATUS,
        PUBLIC_OPERATOR_RUNTIME,
        PUBLIC_DASHBOARD,
    ),
) -> dict[str, Any]:
    return asyncio.run(
        run_once_async(
            symbols=symbols,
            metrics=metrics,
            redis_client=redis_client,
            dry_run=dry_run,
            interval=interval,
            from_expr=from_expr,
            to_expr=to_expr,
            http_post=http_post,
            out_paths=out_paths,
        )
    )


# Tier policy (operator alt-data directive): majors + active trade symbols get
# the full expanded metric set; the long tail keeps the core-6 so the expanded
# set cannot exhaust the month budget. The header-based throttle in the client
# remains the hard governor either way.
TIER_A_SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "XRP", "LINK", "UNI", "AAVE")
CORE_METRICS = (
    "social_volume_total",
    "sentiment_positive_total",
    "sentiment_negative_total",
    "whale_transaction_count_100k_usd_to_inf",
    "exchange_inflow",
    "percent_of_total_supply_on_exchanges",
)


_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "USD")


def _base_asset(symbol: str) -> str:
    """Normalize a runtime pair symbol (BTCUSDT, 1000PEPEUSDT) to its base
    asset so tier matching works against the runtime universe, which carries
    full pair symbols rather than bare assets."""
    base = str(symbol or "").upper()
    for quote in _QUOTE_SUFFIXES:
        if base.endswith(quote) and len(base) > len(quote):
            base = base[: -len(quote)]
            break
    if base.startswith("1000") and len(base) > 4:
        base = base[4:]
    return base


def split_symbols_by_tier(symbols: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tier_a = tuple(s for s in symbols if _base_asset(s) in TIER_A_SYMBOLS)
    tier_b = tuple(s for s in symbols if _base_asset(s) not in TIER_A_SYMBOLS)
    return tier_a, tier_b


# A cycle where every symbol failed at the network layer (e.g. host offline
# at boot) retries on this shorter interval instead of waiting the full
# 6h cadence. Rate-limit/authorization failures keep the normal cadence so
# the retry can never burn API budget (network-failed calls cost nothing).
NETWORK_ERROR_RETRY_SECONDS = 900


def _all_network_error(results: list[dict[str, Any]]) -> bool:
    """True when at least one run attempted symbols and every attempted
    symbol across all runs failed with API_NETWORK_ERROR."""
    saw_symbols = False
    for result in results:
        status = result.get("status_payload") or {}
        counts = status.get("source_status_counts") or {}
        symbol_count = int(status.get("symbol_count") or 0)
        if symbol_count <= 0:
            continue
        saw_symbols = True
        if int(status.get("successful_symbol_count") or 0) > 0:
            return False
        network_errors = int(counts.get("API_NETWORK_ERROR") or 0)
        if network_errors < symbol_count:
            return False
    return saw_symbols


async def run_loop_async(
    *,
    symbols: tuple[str, ...],
    metrics: tuple[str, ...],
    redis_client,
    interval: str,
    from_expr: str,
    to_expr: str,
    execution_interval_seconds: int,
) -> None:
    tier_a, tier_b = split_symbols_by_tier(symbols)
    while True:
        started = asyncio.get_running_loop().time()
        # Reconnect guard: a client that was unavailable at process start
        # (Redis restarting / MISCONF at boot) must not condemn every later
        # cycle to file-only writes for the life of the process.
        if redis_client is not None:
            try:
                redis_client.ping()
            except Exception:
                redis_client = None
        if redis_client is None:
            redis_client = _connect_redis()
        cycle_results: list[dict[str, Any]] = []
        if tier_a:
            cycle_results.append(
                await run_once_async(
                    symbols=tier_a,
                    metrics=metrics,
                    redis_client=redis_client,
                    interval=interval,
                    from_expr=from_expr,
                    to_expr=to_expr,
                )
            )
        if tier_b:
            cycle_results.append(
                await run_once_async(
                    symbols=tier_b,
                    metrics=CORE_METRICS,
                    redis_client=redis_client,
                    interval=interval,
                    from_expr=from_expr,
                    to_expr=to_expr,
                )
            )
        elapsed = asyncio.get_running_loop().time() - started
        sleep_budget = float(execution_interval_seconds)
        if _all_network_error(cycle_results):
            sleep_budget = min(sleep_budget, float(NETWORK_ERROR_RETRY_SECONDS))
        await asyncio.sleep(max(0.0, sleep_budget - elapsed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_santiment_pro_ingestor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check key presence and write status without Santiment network calls.",
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--metrics", default=",".join(DEFAULT_METRICS))
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--from-expr", default=DEFAULT_LOOKBACK)
    parser.add_argument("--to-expr", default=DEFAULT_TO)
    parser.add_argument(
        "--execution-interval-seconds",
        type=int,
        default=DEFAULT_EXECUTION_INTERVAL_SECONDS,
    )
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_OPERATOR_RUNTIME)
    parser.add_argument("--out-public-secondary", type=Path, default=PUBLIC_DASHBOARD)
    args = parser.parse_args(argv)

    if args.loop and args.dry_run:
        parser.error("--loop cannot be combined with --dry-run")
    if not args.once and not args.loop:
        parser.error("choose --once or --loop")

    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    symbols = tuple(resolve_symbols(explicit=_parse_csv(args.symbols)))
    metrics = sanitize_metrics(tuple(args.metrics.split(",")))
    redis_client = _connect_redis()
    out_paths = (args.out_worklog, args.out_public, args.out_public_secondary)
    if args.loop:
        asyncio.run(
            run_loop_async(
                symbols=symbols,
                metrics=metrics,
                redis_client=redis_client,
                interval=args.interval,
                from_expr=args.from_expr,
                to_expr=args.to_expr,
                execution_interval_seconds=args.execution_interval_seconds,
            )
        )
        return 0

    result = run_once(
        symbols=symbols,
        metrics=metrics,
        redis_client=redis_client,
        dry_run=args.dry_run,
        interval=args.interval,
        from_expr=args.from_expr,
        to_expr=args.to_expr,
        out_paths=out_paths,
    )
    payload = result["status_payload"]
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "provider": payload["provider"],
                "key_present": payload["key_present"],
                "dry_run": payload.get("dry_run", False),
                "provider_network_calls_attempted": payload[
                    "provider_network_calls_attempted"
                ],
                "successful_symbol_count": payload["successful_symbol_count"],
                "live_gate": payload["live_gate"],
                "places_real_order": payload["places_real_order"],
                "writes_old_redis": payload["writes_old_redis"],
                "exchange_mutation": payload["exchange_mutation"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
