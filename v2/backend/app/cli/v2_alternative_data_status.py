"""V2 alternative-data scaffold status CLI.

Emits redacted provider presence, free-tier rate-limit/cache
contracts, dry-run symbol score placeholders, and dashboard payloads.
Provider clients are not implemented and no provider API is called.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.alternative_data.cache import (
    ALLOWED_PROVIDER_STATUS_KEY,
    SYMBOL_UNIVERSE_KEY,
    build_cache_contracts,
    safe_redis_set,
)
from v2.backend.app.services.alternative_data.provider_registry import (
    dashboard_contracts,
    provider_registry_payload,
    utc_iso,
)
from v2.backend.app.services.alternative_data.rate_limits import (
    build_dry_run_schedule,
    build_rate_limit_contract,
)
from v2.backend.app.services.alternative_data.symbol_scoring_contract import (
    build_symbol_score_payload,
    build_symbol_universe_candidates,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/alt_data_status.json"
)
WORKLOG_GO_NO_GO = Path(
    "claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/GO_NO_GO.md"
)
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_alternative_data/latest/v2_alternative_data_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/operator_dashboard_payload.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def build_status_payload(
    *,
    symbols: tuple[str, ...],
    vault_path: Path = Path(".local_secrets/alternative_data.env"),
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    registry = provider_registry_payload(vault_path=vault_path, env=env)
    rate_limits = build_rate_limit_contract()
    cache_contracts = build_cache_contracts(symbols)
    symbol_scores = {
        symbol: build_symbol_score_payload(symbol)
        for symbol in symbols
    }
    symbol_universe = build_symbol_universe_candidates(symbols)
    panels = list(dashboard_contracts())
    return {
        "schema_version": "v2_alternative_data_status_scaffold_v1",
        "generated_utc": utc_iso(),
        "go_no_go": "V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_READY",
    "implementation_state": "STATUS_REGISTRY_ONLY_PROVIDER_CLIENTS_AND_SCORES_OWNED_BY_RUNTIME_WORKERS",
        "provider_registry": registry,
        "rate_limit_contract": rate_limits,
        "cache_contracts": cache_contracts,
        "dry_run_schedule": build_dry_run_schedule(symbols),
        "symbol_scores": symbol_scores,
        "symbol_universe_candidates": symbol_universe,
        "dashboard_contracts": {
            "panel_count": len(panels),
            "panels": panels,
            "binance_dashboard_panel_ids": [
                "binance_12h_volume_leaders",
                "binance_12h_most_traded",
                "binance_12h_volatility_leaders",
            ],
        },
        "allowed_redis_writes": [
            "v2:altdata:provider_status",
        ],
        "placeholder_score_redis_writes_disabled": True,
        "score_key_owner": "v2_alt_data_symbol_universe_scoring",
        "candidate_key_owner": "v2_alt_data_symbol_candidate_publisher",
        "raw_values_exposed": False,
        "provider_network_calls_attempted": False,
        "dry_run_only": True,
        "paid_tier_enabled": False,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "paper_shadow_only": True,
        "may_not_override_strict_paper_fill_gate": True,
        "writes_old_redis": False,
        "exchange_mutation": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_redis_status(redis_client: Any, payload: dict[str, Any]) -> dict[str, bool | str]:
    results: dict[str, bool] = {}
    provider_payload = {
        "schema_version": "v2_alternative_data_provider_status_v1",
        "generated_utc": payload["generated_utc"],
        "provider_ids": payload["provider_registry"]["provider_ids"],
        "raw_values_exposed": False,
        "provider_network_calls_attempted": False,
        "paid_tier_enabled": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    results[ALLOWED_PROVIDER_STATUS_KEY] = safe_redis_set(
        redis_client, ALLOWED_PROVIDER_STATUS_KEY, provider_payload
    )
    results["v2:altdata:symbol_score:{symbol}"] = "SKIPPED_PLACEHOLDER_WRITE_REAL_SCORER_OWNER"
    results[SYMBOL_UNIVERSE_KEY] = "SKIPPED_PLACEHOLDER_WRITE_REAL_CANDIDATE_PUBLISHER_OWNER"
    return results


def run_once(
    *,
    symbols: tuple[str, ...] | None = None,
    redis_client_override=None,
    write_redis: bool = True,
    worklog_path: Path = WORKLOG_STATUS,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_DASHBOARD),
    vault_path: Path = Path(".local_secrets/alternative_data.env"),
    env: dict[str, str] | None = None,
    smoke_test: bool = False,
) -> dict[str, Any]:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
    resolved_symbols = tuple(resolve_symbols(explicit=symbols, smoke_test=smoke_test))
    payload = build_status_payload(symbols=resolved_symbols, vault_path=vault_path, env=env)
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    if write_redis and redis_client is not None:
        payload["redis_write_results"] = write_redis_status(redis_client, payload)
    else:
        payload["redis_write_results"] = {}
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    worklog_path.write_text(body, encoding="utf-8")
    WORKLOG_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_GO_NO_GO.write_text(payload["go_no_go"] + "\n", encoding="utf-8")
    for path in public_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_alternative_data_status")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols. Default uses the dynamic universe "
            "resolver (25-symbol baseline + published universe)."
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set (test only).",
    )
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args(argv)
    payload = run_once(
        symbols=args.symbols,
        smoke_test=args.smoke_test,
        write_redis=not args.no_redis,
    )
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "provider_count": len(payload["provider_registry"]["provider_ids"]),
                "raw_values_exposed": payload["raw_values_exposed"],
                "provider_network_calls_attempted": payload[
                    "provider_network_calls_attempted"
                ],
                "paid_tier_enabled": payload["paid_tier_enabled"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
