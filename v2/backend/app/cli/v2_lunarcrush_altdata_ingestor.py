"""V2 LunarCrush alternative-data ingestor CLI (paper/shadow only).

Bounded one-shot ingestor that calls the LunarCrush free-tier
paper/shadow client for a fixed symbol set and publishes results to
v2:altdata:lunarcrush:*. Without the LUNARCRUSH_API_KEY env var
present, this CLI emits a KEY_MISSING_NO_NETWORK status and exits
without opening any network connection.

NEVER places, cancels, or modifies any exchange entry. NEVER changes
leverage or margin. NEVER writes old Redis keys. NEVER calls paid
endpoints. NEVER logs or persists the raw API key. NEVER imports
torch. NEVER deserializes pickle.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.alternative_data.lunarcrush_client import (
    DEFAULT_VAULT_PATH,
    KEY_STATUS,
    LunarCrushClient,
    RateLimitState,
    SOURCE_STATUS_BUDGET_EXHAUSTED,
    SOURCE_STATUS_CACHE_HIT,
    SOURCE_STATUS_COOLDOWN,
    SOURCE_STATUS_KEY_MISSING,
    SOURCE_STATUS_OK,
    api_key_present,
    write_status_payload,
    write_symbol_payload,
)

GO_READY = "V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY"
GO_BLOCKED = "V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_BLOCKED"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json"
)
PUBLIC_DASHBOARD_SECONDARY = Path(
    "v2/frontend/public/v2_lunarcrush_altdata_client/latest/operator_dashboard_payload.json"
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _write_status_files(payload: dict, worklog: Path, publics: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    for p in publics:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def run_once(
    *,
    symbols: tuple[str, ...],
    redis_client,
    http_get=None,
    now_ms_func=None,
    daily_budget_internal: int | None = None,
    cache_ttl_seconds: int | None = None,
    per_symbol_cooldown_seconds: int | None = None,
    vault_path: Path = DEFAULT_VAULT_PATH,
) -> dict:
    if not api_key_present(vault_path=vault_path):
        rate_limit = RateLimitState(
            daily_budget_internal=daily_budget_internal or 0,
            daily_budget_remaining=daily_budget_internal or 0,
        )
        status = write_status_payload(
            redis_client,
            go_no_go=GO_READY,
            rate_limit_state=rate_limit,
            symbol_count=len(symbols),
            successful_symbol_count=0,
            source_status_counts={SOURCE_STATUS_KEY_MISSING: len(symbols)},
            key_present=False,
            network_call_attempted=False,
        )
        return {
            "status_payload": status,
            "results": [],
            "key_present": False,
            "network_call_attempted": False,
        }
    rate_limit = RateLimitState()
    if daily_budget_internal is not None:
        rate_limit = RateLimitState(
            daily_budget_internal=int(daily_budget_internal),
            daily_budget_remaining=int(daily_budget_internal),
        )
    client_kwargs: dict = {"rate_limit": rate_limit}
    if http_get is not None:
        client_kwargs["http_get"] = http_get
    if now_ms_func is not None:
        client_kwargs["now_ms_func"] = now_ms_func
    if cache_ttl_seconds is not None:
        client_kwargs["cache_ttl_seconds"] = int(cache_ttl_seconds)
    if per_symbol_cooldown_seconds is not None:
        client_kwargs["per_symbol_cooldown_seconds"] = int(per_symbol_cooldown_seconds)
    client_kwargs["vault_path"] = vault_path
    client = LunarCrushClient(**client_kwargs)
    results = []
    status_counter: Counter[str] = Counter()
    successful = 0
    for symbol in symbols:
        result = client.fetch_symbol(symbol)
        results.append(result)
        status_counter[result.source_status] += 1
        if result.source_status in (SOURCE_STATUS_OK, SOURCE_STATUS_CACHE_HIT):
            successful += 1
        write_symbol_payload(redis_client, result)
    network_call_attempted = client.rate_limit.last_request_ms is not None
    status = write_status_payload(
        redis_client,
        go_no_go=GO_READY,
        rate_limit_state=client.rate_limit,
        symbol_count=len(symbols),
        successful_symbol_count=successful,
        source_status_counts=dict(status_counter),
        key_present=True,
        network_call_attempted=network_call_attempted,
    )
    return {
        "status_payload": status,
        "results": [r.as_payload() for r in results],
        "key_present": True,
        "network_call_attempted": network_call_attempted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_lunarcrush_altdata_ingestor")
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols to score (uppercase). Default uses the "
            "dynamic universe resolver (25-symbol baseline + published universe)."
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set (test only).",
    )
    parser.add_argument(
        "--daily-budget-internal",
        type=int,
        default=None,
        help=(
            "Internal daily request budget. Must stay below the "
            "provider's free-tier limit. Defaults to the client default."
        ),
    )
    parser.add_argument(
        "--cache-ttl-seconds",
        type=int,
        default=None,
        help="Override cache TTL (seconds) for testing/dry-run paths.",
    )
    parser.add_argument(
        "--per-symbol-cooldown-seconds",
        type=int,
        default=None,
        help="Override per-symbol cooldown (seconds) for testing.",
    )
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_DASHBOARD)
    parser.add_argument(
        "--out-public-secondary", type=Path, default=PUBLIC_DASHBOARD_SECONDARY
    )
    parser.add_argument(
        "--vault-path",
        type=Path,
        default=DEFAULT_VAULT_PATH,
        help="Local key-custody env file. Raw values are never printed.",
    )
    args = parser.parse_args(argv)
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
    symbols = tuple(resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test))
    redis_client = _connect_redis()
    result = run_once(
        symbols=symbols,
        redis_client=redis_client,
        daily_budget_internal=args.daily_budget_internal,
        cache_ttl_seconds=args.cache_ttl_seconds,
        per_symbol_cooldown_seconds=args.per_symbol_cooldown_seconds,
        vault_path=args.vault_path,
    )
    _write_status_files(
        result["status_payload"],
        args.out_worklog,
        (args.out_public, args.out_public_secondary),
    )
    summary = {
        "go_no_go": result["status_payload"]["go_no_go"],
        "key_present": result["key_present"],
        "network_call_attempted": result["network_call_attempted"],
        "symbol_count": result["status_payload"]["symbol_count"],
        "successful_symbol_count": result["status_payload"]["successful_symbol_count"],
        "source_status_counts": result["status_payload"]["source_status_counts"],
        "credential_in_payload": "NEVER",
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
