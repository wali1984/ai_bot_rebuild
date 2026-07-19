"""Moralis provider loop with compute-unit and cadence limits."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from app.services.smart_money_wallets.client import MoralisClient
from app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
    moralis_endpoint_registry,
    registry_payload,
)
from app.services.smart_money_wallets.publisher import publish_moralis_result
from app.services.smart_money_wallets.rate_limit import MoralisRateLimiter
from app.services.smart_money_wallets.health import build_moralis_health
from app.services.smart_money_wallets.moralis_feature_bridge import publish_moralis_feature_payload
from app.services.smart_money_wallets.token_contract_mapper import (
    read_pollable_tokens,
)
from app.services.smart_money_wallets.wallet_watchlist import (
    read_wallet_watchlist,
    watchlist_counts,
)


SCHEDULER_STATUS_KEY = "v2:provider:moralis:scheduler_status"

# Canonical token-map chain name -> Moralis EVM chain param. The token map stores
# "ethereum"/"bsc"; Moralis endpoints take "eth"/"bsc". Kept in sync with
# EVM_CHAIN_PARAM in v2_moralis_token_metadata_validate.
_EVM_CHAIN_PARAM = {
    "ethereum": "eth", "eth": "eth",
    "bsc": "bsc", "binance-smart-chain": "bsc",
    "polygon": "polygon", "arbitrum": "arbitrum",
    "optimism": "optimism", "base": "base", "avalanche": "avalanche",
}


def _norm_chain(value: Any) -> str:
    v = str(value or "").strip().lower()
    return _EVM_CHAIN_PARAM.get(v, v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_provider_loop")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--chain", default=os.environ.get("MORALIS_CHAIN", "eth"))
    parser.add_argument("--wallets", default=os.environ.get("MORALIS_WALLETS", ""))
    parser.add_argument("--tokens", default=os.environ.get("MORALIS_TOKENS", ""))
    parser.add_argument("--symbol", default=os.environ.get("MORALIS_SYMBOL", "BTCUSDT"))
    parser.add_argument("--timeframe", default=os.environ.get("MORALIS_TIMEFRAME", "1m"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import bootstrap_process_env

        bootstrap_process_env(apply=True)
    except Exception:
        pass  # fall back to whatever the process env already carries
    redis_client = _redis_client(args.redis_url)
    wallets = _csv(args.wallets)
    tokens = _csv(args.tokens)
    client = MoralisClient(limiter=MoralisRateLimiter())
    scheduler_state: dict[str, float] = {}
    while True:
        report = run_once(
            redis_client,
            client=client,
            chain=args.chain,
            wallets=wallets,
            tokens=tokens,
            symbol=args.symbol.upper(),
            timeframe=args.timeframe,
            scheduler_state=scheduler_state,
            force=args.once,
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        if args.once:
            return 0
        time.sleep(max(60.0, args.sleep_seconds))


def run_once(
    redis_client: Any | None,
    *,
    client: MoralisClient,
    chain: str,
    wallets: list[str],
    tokens: list[str],
    symbol: str,
    timeframe: str = "1m",
    scheduler_state: dict[str, float] | None = None,
    force: bool = True,
    now_monotonic: float | None = None,
) -> dict[str, Any]:
    bootstrap = _resolve_bootstrap_inputs(
        redis_client,
        chain=chain,
        symbol=symbol,
        wallets=wallets,
        tokens=tokens,
    )
    wallets = bootstrap["wallets"]
    tokens = bootstrap["tokens"]
    plan = moralis_scheduler_plan(wallets=wallets, tokens=tokens)
    if bootstrap["status"] == "CONFIGURED_NO_WATCHLIST":
        status = _no_watchlist_status(
            redis_client,
            chain=chain,
            symbol=symbol,
            timeframe=timeframe,
            plan=plan,
            bootstrap=bootstrap,
            limiter=client.limiter,
        )
        return status
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    published_symbols: set[str] = set()
    contract_symbol_map = bootstrap.get("contract_symbol_map") or {}
    now_value = time.monotonic() if now_monotonic is None else float(now_monotonic)
    for spec in moralis_endpoint_registry():
        if spec.stream_based:
            continue
        targets = _targets_for_spec(spec, wallets=wallets, tokens=tokens)
        for target_index, (wallet, token) in enumerate(targets):
            cadence_seconds = _cadence_seconds_for_target(spec, target_index=target_index)
            target_id = wallet or token or symbol
            state_key = f"{spec.endpoint_id}:{chain}:{target_id}"
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
                        "target": target_id,
                        "cadence_seconds": cadence_seconds,
                        "seconds_until_due": max(0.0, cadence_seconds - (now_value - float(last_polled))),
                    }
                )
                continue
            response = client.get(
                spec,
                chain=chain,
                wallet=wallet,
                token=token,
                symbol=symbol,
            )
            if scheduler_state is not None:
                scheduler_state[state_key] = now_value
            # IDENTITY: attribute a token endpoint to that token's OWN verified
            # trading symbol, never the fixed context symbol (which merged
            # LINK/UNI/WBTC/PEPE/SHIB/CRV flow into a single BTCUSDT bucket).
            # Wallet/global targets and contracts with no verified symbol mapping
            # get symbol=None: their raw contract-addressed data is still stored,
            # but no per-symbol feature/aggregate/score is fabricated.
            publish_symbol: str | None = None
            if token:
                resolved = contract_symbol_map.get(str(token).strip().lower())
                if resolved and resolved.get("chain") == _norm_chain(chain) and resolved.get("symbol"):
                    publish_symbol = str(resolved["symbol"])
                else:
                    quarantined.append(
                        {
                            "contract": token,
                            "chain": _norm_chain(chain),
                            "endpoint_id": spec.endpoint_id,
                            "reason": "NO_VERIFIED_SYMBOL_MAPPING",
                        }
                    )
            result = publish_moralis_result(
                redis_client,
                env=os.environ,
                spec=spec,
                chain=chain,
                symbol=publish_symbol,
                wallet=wallet,
                token=token,
                http_status=response.http_status,
                payload=response.payload,
                budget_status=client.limiter.as_dict(),
                error_class=response.error_class,
                timeframe=timeframe,
                token_map_count=int(bootstrap.get("token_map_count") or 0),
                wallet_watchlist_count=int(bootstrap.get("wallet_watchlist_count") or 0),
            )
            if publish_symbol:
                published_symbols.add(publish_symbol)
            results.append(result)
    # Keep the (masked) global feature-bridge status fresh even when every polled
    # contract quarantined for lack of a verified symbol, so it never goes stale.
    if redis_client is not None and not published_symbols:
        publish_moralis_feature_payload(
            redis_client,
            symbol=symbol,
            timeframe=timeframe,
            features={},
            token_map_count=int(bootstrap.get("token_map_count") or 0),
            wallet_watchlist_count=int(bootstrap.get("wallet_watchlist_count") or 0),
            actual_payload_present=False,
            ttl_seconds=3600,
            stale_after=3600,
            compute_unit_status=client.limiter.as_dict(),
        )
    status = {
        "schema_version": "moralis_provider_scheduler_status_v1",
        "provider": "moralis",
        "generated_utc": _now(),
        "chain": chain,
        "wallet_count": len(wallets),
        "token_count": len(tokens),
        "token_map_count": bootstrap["token_map_count"],
        "wallet_watchlist_count": bootstrap["wallet_watchlist_count"],
        "bootstrap_status": bootstrap["status"],
        "symbol": symbol,
        "timeframe": timeframe,
        "registry": registry_payload(),
        "schedule_plan": plan,
        "result_count": len(results),
        "request_count": len(results),
        "skipped_not_due_count": len(skipped),
        "skipped_not_due": skipped[:50],
        "resolved_symbols": sorted(published_symbols),
        "resolved_symbol_count": len(published_symbols),
        "quarantined_contract_count": len(quarantined),
        "quarantined_contracts": quarantined[:50],
        "context_symbol_attribution_disabled": True,
        "actual_payload_results": sum(1 for row in results if row.get("actual_payload_present")),
        "does_not_poll_every_symbol_every_minute": True,
        "stream_endpoints_are_webhook_only": True,
        "heartbeat_only_green_allowed": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    if redis_client is not None:
        redis_client.set(SCHEDULER_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=300)
    return status


def moralis_scheduler_plan(*, wallets: list[str], tokens: list[str]) -> dict[str, Any]:
    endpoint_rows = []
    estimated_cu = 0
    for spec in moralis_endpoint_registry():
        target_count = len(_targets_for_spec(spec, wallets=wallets, tokens=tokens))
        endpoint_cu = target_count * spec.cu_cost
        estimated_cu += endpoint_cu
        endpoint_rows.append(
            {
                "endpoint_id": spec.endpoint_id,
                "group": spec.group,
                "cadence_seconds_tier0": spec.cadence_seconds_tier0,
                "cadence_seconds_tier1": spec.cadence_seconds_tier1,
                "cadence_seconds_full_watchlist": spec.cadence_seconds_full_watchlist,
                "compute_unit_cost": spec.cu_cost,
                "target_count": target_count,
                "estimated_compute_units_per_cycle": endpoint_cu,
                "stream_based": spec.stream_based,
                "feature_outputs": list(spec.feature_outputs),
            }
        )
    return {
        "schema_version": "moralis_scheduler_plan_v1",
        "daily_compute_unit_budget": 55_000,
        "daily_compute_unit_reserve": 10_000,
        "estimated_compute_units_per_cycle": estimated_cu,
        "normal_rps": 5,
        "catchup_rps": 10,
        "hard_rps": 30,
        "does_not_poll_every_symbol_every_minute": True,
        "configured_no_watchlist_is_green": False,
        "endpoints": endpoint_rows,
    }


def _targets_for_spec(
    spec: MoralisEndpointSpec,
    *,
    wallets: list[str],
    tokens: list[str],
) -> list[tuple[str | None, str | None]]:
    if spec.stream_based:
        return []
    if spec.requires_wallet:
        return [(wallet, None) for wallet in wallets[:3]]
    if spec.requires_token:
        return [(None, token) for token in tokens[:3]]
    return [(None, None)]


def _resolve_bootstrap_inputs(
    redis_client: Any | None,
    *,
    chain: str,
    symbol: str,
    wallets: list[str],
    tokens: list[str],
) -> dict[str, Any]:
    explicit_wallets = bool(wallets)
    explicit_tokens = bool(tokens)
    if not wallets:
        wallets = [
            row["address"]
            for row in read_wallet_watchlist(redis_client)
            if row.get("chain") == str(chain).lower()
        ]
    token_map_tokens = read_pollable_tokens(redis_client, symbol=symbol)
    if not any(_norm_chain(row.get("chain")) == _norm_chain(chain) for row in token_map_tokens):
        # The default context symbol (e.g. BTCUSDT) has no ERC-20 pollable
        # contracts, so per-symbol scoping yields zero token whale-flow features.
        # Fall back to every pollable token in the map so whale-flow / exchange-flow
        # features populate across the tracked universe (LINK, CRV, AAVE, ...).
        token_map_tokens = read_pollable_tokens(redis_client, symbol=None)
    if not tokens:
        # The token map stores the canonical chain name ("ethereum") while the loop
        # runs with the Moralis chain param ("eth"); normalize both before matching
        # so verified ERC-20 tokens are actually selected for whale-flow polling.
        tokens = [
            row["token"]
            for row in token_map_tokens
            if _norm_chain(row.get("chain")) == _norm_chain(chain)
        ]
    # Reverse identity map: contract address -> its OWN verified trading symbol.
    # Because token-map native perps (BTCUSDT/ETHUSDT -> contract "native") are
    # non-pollable, they never appear here, so an ERC-20 (e.g. WBTC) can never be
    # attributed to BTCUSDT. This replaces the old fixed-context-symbol attribution.
    contract_symbol_map = {
        str(row.get("token") or "").strip().lower(): {
            "symbol": str(row.get("symbol") or "").upper(),
            "chain": _norm_chain(row.get("chain")),
        }
        for row in token_map_tokens
        if str(row.get("token") or "").strip() and str(row.get("symbol") or "").strip()
    }
    counts = watchlist_counts(redis_client)
    token_map_count = _token_map_count(redis_client)
    wallet_count = int(counts.get("wallet_watchlist_count") or 0)
    has_operator_inputs = explicit_wallets or explicit_tokens
    if not has_operator_inputs and wallet_count <= 0:
        status = "CONFIGURED_NO_WATCHLIST"
    elif not has_operator_inputs and token_map_count <= 0:
        status = "CONFIGURED_NO_TOKEN_MAP"
    else:
        status = "WATCHLIST_READY"
    return {
        "status": status,
        "wallets": wallets,
        "tokens": tokens,
        "token_map_count": token_map_count,
        "wallet_watchlist_count": wallet_count if not explicit_wallets else len(wallets),
        "operator_supplied_wallets": explicit_wallets,
        "operator_supplied_tokens": explicit_tokens,
        "pollable_token_count": len(token_map_tokens),
        "contract_symbol_map": contract_symbol_map,
    }


def _no_watchlist_status(
    redis_client: Any | None,
    *,
    chain: str,
    symbol: str,
    timeframe: str,
    plan: dict[str, Any],
    bootstrap: dict[str, Any],
    limiter: MoralisRateLimiter,
) -> dict[str, Any]:
    health = build_moralis_health(
        os.environ,
        token_map_count=int(bootstrap.get("token_map_count") or 0),
        wallet_watchlist_count=int(bootstrap.get("wallet_watchlist_count") or 0),
        actual_payload_count_1h=0,
    )
    usage = limiter.as_dict()
    endpoint_status = {
        "schema_version": "moralis_endpoint_status_v1",
        "provider": "moralis",
        "generated_utc": _now(),
        "endpoints": {},
        "actual_payload_endpoint_count": 0,
        "heartbeat_only_green_allowed": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }
    status = {
        "schema_version": "moralis_provider_scheduler_status_v1",
        "provider": "moralis",
        "status": health["status"],
        "generated_utc": _now(),
        "chain": chain,
        "wallet_count": 0,
        "token_count": 0,
        "token_map_count": bootstrap.get("token_map_count", 0),
        "wallet_watchlist_count": bootstrap.get("wallet_watchlist_count", 0),
        "symbol": symbol,
        "timeframe": timeframe,
        "registry": registry_payload(),
        "schedule_plan": plan,
        "result_count": 0,
        "request_count": 0,
        "skipped_not_due_count": 0,
        "skipped_not_due": [],
        "actual_payload_results": 0,
        "does_not_poll_every_symbol_every_minute": True,
        "stream_endpoints_are_webhook_only": True,
        "heartbeat_only_green_allowed": False,
        "configured_no_watchlist_is_green": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    if redis_client is not None:
        bridge_payload = publish_moralis_feature_payload(
            redis_client,
            symbol=symbol,
            timeframe=timeframe,
            features={},
            token_map_count=int(bootstrap.get("token_map_count") or 0),
            wallet_watchlist_count=int(bootstrap.get("wallet_watchlist_count") or 0),
            actual_payload_present=False,
            ttl_seconds=3600,
            stale_after=3600,
            compute_unit_status=usage,
        )
        health.update(
            {
                "feature_bridge_ready": bridge_payload.get("feature_bridge_ready"),
                "feature_count": bridge_payload.get("feature_count"),
                "required_feature_count": bridge_payload.get("required_feature_count"),
                "missing_feature_flags": bridge_payload.get("missing_feature_flags"),
                "stale_feature_flags": bridge_payload.get("stale_feature_flags"),
                "missing_mask": bridge_payload.get("missing_mask"),
                "missing_mask_true": bridge_payload.get("missing_mask_true"),
                "stale_mask": bridge_payload.get("stale_mask"),
                "stale_mask_true": bridge_payload.get("stale_mask_true"),
                "actual_payload_present": bridge_payload.get("actual_payload_present"),
                "heartbeat_only": bridge_payload.get("heartbeat_only"),
                "heartbeat_only_green_allowed": False,
                "decision_time_safe": bridge_payload.get("decision_time_safe"),
            }
        )
        redis_client.set("v2:provider:moralis:health", json.dumps(health, sort_keys=True, default=str), ex=3600)
        redis_client.set("v2:provider:moralis:usage", json.dumps(usage, sort_keys=True, default=str), ex=3600)
        redis_client.set("v2:provider:moralis:endpoint_status", json.dumps(endpoint_status, sort_keys=True, default=str), ex=3600)
        redis_client.set(SCHEDULER_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=300)
    return status


def _token_map_count(redis_client: Any | None) -> int:
    if redis_client is None:
        return 0
    try:
        raw = redis_client.get("v2:moralis:token_map_status")
    except Exception:
        return 0
    if raw is None:
        return 0
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    return int(payload.get("token_map_count") or 0)


def _cadence_seconds_for_target(spec: MoralisEndpointSpec, *, target_index: int) -> int:
    if target_index < 3:
        return spec.cadence_seconds_tier0
    if target_index < 10:
        return spec.cadence_seconds_tier1
    return spec.cadence_seconds_full_watchlist


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
