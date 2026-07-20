"""Moralis provider loop with compute-unit and cadence limits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.smart_money_wallets.client import (
    MoralisClient,
    prepare_request_identity,
)
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_EVM_CHAIN_ALIASES,
    MORALIS_EVM_CHAIN_PARAMS,
    MORALIS_SCHEDULER_STATUS_KEY,
    MoralisEndpointSpec,
    moralis_endpoint_registry,
    registry_payload,
)
from app.services.smart_money_wallets.health import build_moralis_health
from app.services.smart_money_wallets.moralis_feature_bridge import publish_moralis_feature_payload
from app.services.smart_money_wallets.publisher import publish_moralis_result
from app.services.smart_money_wallets.rate_limit import (
    MORALIS_TIMEOUT_SECONDS,
    MoralisRateLimiter,
)
from app.services.smart_money_wallets.token_contract_mapper import (
    read_metadata_validation_tokens,
    read_pollable_tokens,
)
from app.services.smart_money_wallets.wallet_watchlist import (
    read_wallet_watchlist,
)

SCHEDULER_STATUS_KEY = MORALIS_SCHEDULER_STATUS_KEY
ROTATION_CURSOR_KEY = "v2:provider:moralis:rotation_cursor:{chain}"
SCHEDULER_LEASE_KEY = "v2:provider:moralis:scheduler_lease:{chain}"
CADENCE_CLAIM_KEY = "v2:provider:moralis:cadence_claim:{chain}:{job_digest}"
LOOP_LOG_SCHEMA_VERSION = "moralis_provider_loop_log_v1"
ContractIdentityKey = tuple[str, str]
PollJob = tuple[MoralisEndpointSpec, int, str | None, str | None]

_COMPARE_DELETE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_COMPARE_EXPIRE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_FENCED_CADENCE_CLAIM_SCRIPT = """
-- MORALIS_FENCED_CADENCE_CLAIM_V1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return {-1, 0}
end
local stored = redis.call('SET', KEYS[2], ARGV[2], 'NX', 'EX', ARGV[3])
if stored then
  return {1, 1}
end
return {0, 1}
"""

_FENCED_CURSOR_WRITE_SCRIPT = """
-- MORALIS_FENCED_CURSOR_WRITE_V1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""


def _norm_chain(value: Any) -> str:
    v = str(value or "").strip().lower()
    return MORALIS_EVM_CHAIN_ALIASES.get(v, v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_provider_loop")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--chain", default=os.environ.get("MORALIS_CHAIN", "eth"))
    parser.add_argument("--wallets", default=os.environ.get("MORALIS_WALLETS", ""))
    parser.add_argument("--tokens", default=os.environ.get("MORALIS_TOKENS", ""))
    parser.add_argument("--symbol", default=os.environ.get("MORALIS_SYMBOL", "BTCUSDT"))
    parser.add_argument("--timeframe", default=os.environ.get("MORALIS_TIMEFRAME", "1m"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--full-loop-report",
        action="store_true",
        help="print the complete scheduler document on every loop iteration",
    )
    parser.add_argument("--sleep-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import (  # type: ignore[import-untyped]
            bootstrap_process_env,
        )

        bootstrap_process_env(apply=True)
    except Exception:  # noqa: S110 - optional environment bootstrap has an explicit fallback
        pass  # fall back to whatever the process env already carries
    redis_client = _redis_client(args.redis_url)
    wallets = _csv(args.wallets)
    tokens = _csv(args.tokens)
    # Give the limiter the Redis client so the CU ledger is persistent + atomic
    # across restarts (else it resets to a fresh 2M month on every bounce).
    client = MoralisClient(limiter=MoralisRateLimiter(redis_client=redis_client))
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
        printable = report if args.once or args.full_loop_report else _loop_log_report(report)
        print(
            json.dumps(
                printable,
                indent=2 if args.once or args.full_loop_report else None,
                sort_keys=True,
                separators=None if args.once or args.full_loop_report else (",", ":"),
                default=str,
            ),
            flush=True,
        )
        if args.once:
            return 0
        time.sleep(max(60.0, args.sleep_seconds))


def _loop_log_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project one bounded console heartbeat from the Redis-published report.

    The loop separately attempts to publish the complete scheduler document,
    endpoint registry, and skipped-job details to
    ``MORALIS_SCHEDULER_STATUS_KEY``.  Reprinting those multi-megabyte
    structures every five minutes adds no evidence and can grow the service log
    by gigabytes per day.
    """

    schedule = report.get("schedule_plan")
    schedule_plan = schedule if isinstance(schedule, Mapping) else {}
    return {
        "schema_version": LOOP_LOG_SCHEMA_VERSION,
        "provider": "moralis",
        "generated_utc": report.get("generated_utc"),
        "status": report.get("status"),
        "bootstrap_status": report.get("bootstrap_status"),
        "chain": report.get("chain"),
        "token_count": report.get("token_count"),
        "token_map_count": report.get("token_map_count"),
        "wallet_watchlist_count": report.get("wallet_watchlist_count"),
        "request_count": report.get("request_count"),
        "result_count": report.get("result_count"),
        "actual_payload_results": report.get("actual_payload_results"),
        "dispatched_request_count": report.get("dispatched_request_count"),
        "skipped_not_due_count": report.get("skipped_not_due_count"),
        "scheduler_run_suppressed_reason": report.get(
            "scheduler_run_suppressed_reason"
        ),
        "durable_cu_budget_status_published": report.get(
            "durable_cu_budget_status_published"
        ),
        "durable_fair_rotation": report.get("durable_fair_rotation"),
        "budget_authority": schedule_plan.get("budget_authority"),
        "budget_authority_available": schedule_plan.get(
            "budget_authority_available"
        ),
        "remaining_today_compute_units": schedule_plan.get(
            "remaining_today_compute_units"
        ),
        "estimated_compute_units_per_day": schedule_plan.get(
            "estimated_compute_units_per_day"
        ),
        "effective_daily_compute_unit_limit": schedule_plan.get(
            "effective_daily_compute_unit_limit"
        ),
        "full_scheduler_report_target_redis_key": SCHEDULER_STATUS_KEY,
        "full_scheduler_report_console_omitted": True,
        "raw_key_exposed": False,
        "places_real_order": False,
        "routes_to_live": False,
    }


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
    metadata_tokens = bootstrap["metadata_tokens"]
    budget_snapshot = client.limiter.as_dict()
    plan = moralis_scheduler_plan(
        wallets=wallets,
        tokens=tokens,
        budget_status=budget_snapshot,
        chain=chain,
        metadata_tokens=metadata_tokens,
    )
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
    unsupported_endpoint_contracts: list[dict[str, Any]] = []
    deduplicated_endpoint_contracts: list[dict[str, Any]] = []
    published_symbols: set[str] = set()
    dispatched_request_count = 0
    rotation_cursor_advanced_count = 0
    durable_cadence_claim_count = 0
    durable_cadence_suppressed_count = 0
    durable_cadence_release_failure_count = 0
    contract_symbol_map = bootstrap.get("contract_symbol_map") or {}
    ambiguous_contract_keys = set(bootstrap.get("ambiguous_contract_keys") or ())
    now_value = time.monotonic() if now_monotonic is None else float(now_monotonic)
    adaptive_cadence_scale = _status_float(plan.get("adaptive_cadence_scale"), default=1.0)
    current_run_compute_unit_budget = _status_int(
        plan.get("current_run_compute_unit_budget")
    )
    current_run_admitted_compute_units = 0
    poll_jobs: list[PollJob] = []
    for spec in moralis_endpoint_registry():
        if spec.stream_based:
            continue
        if spec.transport_alias_of is not None:
            deduplicated_endpoint_contracts.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "transport_alias_of": spec.transport_alias_of,
                    "reason": (
                        spec.polling_block_reason or "DUPLICATE_TRANSPORT_ALIAS_NOT_DIRECTLY_POLLED"
                    ),
                }
            )
            continue
        if not spec.polling_supported:
            unsupported_endpoint_contracts.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "http_method": spec.http_method,
                    "reason": (
                        spec.polling_block_reason or "ENDPOINT_REQUEST_CONTRACT_UNSUPPORTED"
                    ),
                }
            )
            continue
        valid_target_index = 0
        for wallet, token in _targets_for_spec(
            spec,
            wallets=wallets,
            tokens=tokens,
            metadata_tokens=metadata_tokens,
        ):
            identity = prepare_request_identity(
                spec,
                chain=chain,
                wallet=wallet,
                token=token,
            )
            if identity.error_class is not None:
                quarantined.append(
                    {
                        "endpoint_id": spec.endpoint_id,
                        "reason": identity.error_class,
                        "target_fingerprint": _target_fingerprint(wallet or token),
                    }
                )
                continue
            poll_jobs.append(
                (
                    spec,
                    valid_target_index,
                    identity.wallet,
                    identity.token,
                )
            )
            valid_target_index += 1

    scheduler_lease_token: str | None = None
    scheduler_lease_state_available = redis_client is None
    scheduler_lease_acquired = redis_client is None
    scheduler_run_suppressed_reason: str | None = None
    if plan["provider_polling_blocked"] or not plan["budget_authority_available"]:
        scheduler_run_suppressed_reason = "BUDGET_AUTHORITY_UNAVAILABLE"
        poll_jobs = []
    else:
        (
            scheduler_lease_token,
            scheduler_lease_state_available,
            scheduler_lease_acquired,
        ) = _acquire_scheduler_lease(redis_client, chain=chain)
        if not scheduler_lease_acquired:
            scheduler_run_suppressed_reason = (
                "CONCURRENT_SCHEDULER_RUN_ACTIVE"
                if scheduler_lease_state_available
                else "SCHEDULER_LEASE_UNAVAILABLE"
            )
            poll_jobs = []
    poll_jobs, rotation_state_available = _rotate_poll_jobs(
        redis_client,
        chain=chain,
        jobs=poll_jobs,
        context_symbol=symbol,
    )
    rotation_state_available = (
        rotation_state_available
        and scheduler_lease_state_available
        and scheduler_lease_acquired
    )
    if redis_client is not None and poll_jobs and not rotation_state_available:
        scheduler_run_suppressed_reason = "ROTATION_STATE_UNAVAILABLE"
        poll_jobs = []
    durable_cadence_state_available = redis_client is not None and rotation_state_available
    for spec, target_index, raw_wallet, raw_token in poll_jobs:
        stop_after_current_result = False
        identity = prepare_request_identity(
            spec,
            chain=chain,
            wallet=raw_wallet,
            token=raw_token,
        )
        if identity.error_class is not None:
            quarantined.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "reason": identity.error_class,
                    "target_fingerprint": _target_fingerprint(raw_wallet or raw_token),
                }
            )
            continue
        wallet = identity.wallet
        token = identity.token
        request_chain = identity.chain
        publish_symbol: str | None = None
        if token:
            identity_key = _contract_identity_key(chain=request_chain, token=token)
            resolved: Mapping[str, str] | None
            # Metadata polling is the bootstrap evidence path.  It may cache an
            # identity before (or for multiple futures aliases before) a unique
            # verified publication symbol exists.  Its raw canonical cache key
            # remains chain+contract bound and trainer-isolated.
            if spec.endpoint_id == "token_metadata":
                resolved = contract_symbol_map.get(identity_key)
                publish_symbol = str(resolved["symbol"]) if resolved else None
            elif identity_key in ambiguous_contract_keys:
                quarantined.append(
                    {
                        "contract": token,
                        "chain": identity_key[0],
                        "endpoint_id": spec.endpoint_id,
                        "reason": "AMBIGUOUS_VERIFIED_SYMBOL_MAPPING",
                    }
                )
                continue
            else:
                resolved = contract_symbol_map.get(identity_key)
            if spec.endpoint_id != "token_metadata" and (
                resolved is None or not resolved.get("symbol")
            ):
                quarantined.append(
                    {
                        "contract": token,
                        "chain": identity_key[0],
                        "endpoint_id": spec.endpoint_id,
                        "reason": "NO_VERIFIED_SYMBOL_MAPPING",
                    }
                )
                continue
            if spec.endpoint_id != "token_metadata":
                assert resolved is not None
                publish_symbol = str(resolved["symbol"])
        configured_cadence_seconds = _cadence_seconds_for_target(
            spec,
            target_index=target_index,
        )
        cadence_seconds = _adaptive_cadence_seconds(
            configured_cadence_seconds,
            scale=adaptive_cadence_scale,
        )
        target_id = wallet or token or symbol
        state_key = _poll_job_id(
            spec,
            chain=request_chain,
            wallet=wallet,
            token=token,
            context_symbol=symbol,
        )
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
                    "target_fingerprint": _target_fingerprint(target_id),
                    "configured_cadence_seconds": configured_cadence_seconds,
                    "cadence_seconds": cadence_seconds,
                    "seconds_until_due": max(
                        0.0,
                        cadence_seconds - (now_value - float(last_polled)),
                    ),
                }
            )
            continue
        if current_run_admitted_compute_units + int(spec.cu_cost) > (
            current_run_compute_unit_budget
        ):
            skipped.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "target_fingerprint": _target_fingerprint(target_id),
                    "reason": "CURRENT_RUN_CU_BUDGET_EXHAUSTED",
                    "compute_unit_cost": int(spec.cu_cost),
                    "current_run_compute_unit_budget": current_run_compute_unit_budget,
                    "current_run_admitted_compute_units": (
                        current_run_admitted_compute_units
                    ),
                }
            )
            continue
        if redis_client is not None and scheduler_lease_token is not None:
            lease_renewed = _renew_scheduler_lease(
                redis_client,
                chain=request_chain,
                lease_token=scheduler_lease_token,
            )
            if not lease_renewed:
                scheduler_lease_state_available = False
                durable_cadence_state_available = False
                rotation_state_available = False
                scheduler_run_suppressed_reason = "SCHEDULER_LEASE_LOST"
                break
        (
            cadence_claimed,
            cadence_state_available,
            cadence_claim_key,
            cadence_claim_value,
        ) = _claim_poll_job(
            redis_client,
            chain=request_chain,
            job_id=state_key,
            cadence_seconds=cadence_seconds,
            lease_token=scheduler_lease_token,
        )
        durable_cadence_state_available = (
            durable_cadence_state_available and cadence_state_available
        )
        if not cadence_claimed:
            durable_cadence_suppressed_count += 1
            if redis_client is not None and not cadence_state_available:
                scheduler_lease_state_available = False
                rotation_state_available = False
                scheduler_run_suppressed_reason = "SCHEDULER_LEASE_LOST"
                break
            skipped.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "target_fingerprint": _target_fingerprint(target_id),
                    "configured_cadence_seconds": configured_cadence_seconds,
                    "cadence_seconds": cadence_seconds,
                    "reason": (
                        "DURABLE_CADENCE_CLAIM_ACTIVE"
                        if cadence_state_available
                        else "DURABLE_CADENCE_STATE_UNAVAILABLE"
                    ),
                }
            )
            continue
        if cadence_state_available:
            durable_cadence_claim_count += 1
        response = client.get(
            spec,
            chain=request_chain,
            wallet=wallet,
            token=token,
            symbol=publish_symbol,
        )
        if response.request_dispatched:
            dispatched_request_count += 1
            current_run_admitted_compute_units += int(spec.cu_cost)
            if scheduler_state is not None:
                scheduler_state[state_key] = now_value
            cursor_written = _write_rotation_cursor(
                redis_client,
                chain=request_chain,
                job_id=state_key,
                lease_token=scheduler_lease_token,
            )
            if cursor_written:
                rotation_cursor_advanced_count += 1
            elif redis_client is not None:
                rotation_state_available = False
                scheduler_run_suppressed_reason = "ROTATION_CURSOR_WRITE_FAILED"
                stop_after_current_result = True
        elif cadence_claim_key is not None and cadence_claim_value is not None:
            claim_released = _release_cadence_claim(
                redis_client,
                key=cadence_claim_key,
                value=cadence_claim_value,
            )
            if not claim_released:
                durable_cadence_release_failure_count += 1
                durable_cadence_state_available = False
        # IDENTITY: attribute a token endpoint to that token's OWN verified
        # trading symbol, never the fixed context symbol (which merged
        # LINK/UNI/WBTC/PEPE/SHIB/CRV flow into a single BTCUSDT bucket).
        # Unmapped, ambiguous, or malformed identities are quarantined before
        # client.get, so they cannot reserve CU, issue HTTP, or form Redis keys.
        result = publish_moralis_result(
            redis_client,
            env=os.environ,
            spec=spec,
            chain=request_chain,
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
        if stop_after_current_result:
            break
    # Keep the (masked) global feature-bridge status fresh even when every polled
    # contract quarantined for lack of a verified symbol, so it never goes stale.
    if (
        redis_client is not None
        and not published_symbols
        and scheduler_lease_acquired
        and scheduler_run_suppressed_reason is None
    ):
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
    scheduler_lease_released = True
    if redis_client is not None and scheduler_lease_token is not None:
        scheduler_lease_released = _release_scheduler_lease(
            redis_client,
            chain=chain,
            lease_token=scheduler_lease_token,
        )
        if not scheduler_lease_released:
            scheduler_lease_state_available = False
            rotation_state_available = False
    cu_budget_status = _publish_persistent_cu_budget_status(client.limiter)
    plan = moralis_scheduler_plan(
        wallets=wallets,
        tokens=tokens,
        metadata_tokens=metadata_tokens,
        budget_status=client.limiter.as_dict(),
        chain=chain,
        durable_rotation_available=(
            redis_client is not None
            and rotation_state_available
            and durable_cadence_state_available
            and scheduler_lease_released
        ),
    )
    status = {
        "schema_version": "moralis_provider_scheduler_status_v1",
        "provider": "moralis",
        "generated_utc": _now(),
        "chain": chain,
        "wallet_count": len(wallets),
        "token_count": len(tokens),
        "metadata_validation_token_count": len(metadata_tokens),
        "token_map_count": bootstrap["token_map_count"],
        "wallet_watchlist_count": bootstrap["wallet_watchlist_count"],
        "bootstrap_status": bootstrap["status"],
        "symbol": symbol,
        "timeframe": timeframe,
        "registry": registry_payload(),
        "schedule_plan": plan,
        "result_count": len(results),
        "publication_count": len(results),
        "request_count": dispatched_request_count,
        "dispatched_request_count": dispatched_request_count,
        "current_run_compute_unit_budget": current_run_compute_unit_budget,
        "current_run_admitted_compute_units": current_run_admitted_compute_units,
        "pre_dispatch_denial_publication_count": len(results) - dispatched_request_count,
        "skipped_not_due_count": len(skipped),
        "skipped_not_due": skipped[:50],
        "resolved_symbols": sorted(published_symbols),
        "resolved_symbol_count": len(published_symbols),
        "quarantined_contract_count": len(quarantined),
        "quarantined_contracts": quarantined[:50],
        "unsupported_endpoint_contract_count": len(unsupported_endpoint_contracts),
        "unsupported_endpoint_contracts": unsupported_endpoint_contracts,
        "deduplicated_endpoint_contract_count": len(deduplicated_endpoint_contracts),
        "deduplicated_endpoint_contracts": deduplicated_endpoint_contracts,
        "ambiguous_contract_identity_count": len(ambiguous_contract_keys),
        "identity_rejected_request_count": len(quarantined),
        "context_symbol_attribution_disabled": True,
        "canonical_token_transfer_transport_owner": _canonical_token_transfer_owner(plan),
        "durable_fair_rotation": plan["durable_fair_rotation"],
        "rotation_state_available": rotation_state_available,
        "rotation_cursor_advanced_count": rotation_cursor_advanced_count,
        "durable_cadence_state_available": durable_cadence_state_available,
        "durable_cadence_claim_count": durable_cadence_claim_count,
        "durable_cadence_suppressed_count": durable_cadence_suppressed_count,
        "durable_cadence_release_failure_count": (
            durable_cadence_release_failure_count
        ),
        "scheduler_lease_state_available": scheduler_lease_state_available,
        "scheduler_lease_acquired": scheduler_lease_acquired,
        "scheduler_lease_released": scheduler_lease_released,
        "scheduler_run_suppressed_reason": scheduler_run_suppressed_reason,
        "actual_payload_results": sum(1 for row in results if row.get("actual_payload_present")),
        "does_not_poll_every_symbol_every_minute": True,
        "stream_endpoints_are_webhook_only": True,
        "heartbeat_only_green_allowed": False,
        "response_semantics_quarantined_from_trainer": True,
        "durable_cu_budget_status_key": "v2:provider:moralis:cu_budget_status",
        "durable_cu_budget_status_published": bool(
            cu_budget_status and cu_budget_status.get("status_publish_succeeded") is True
        ),
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


def moralis_scheduler_plan(
    *,
    wallets: list[str],
    tokens: list[str],
    budget_status: Mapping[str, Any] | None = None,
    chain: str = "eth",
    durable_rotation_available: bool = False,
    metadata_tokens: list[str] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    authority = _budget_plan_view(budget_status)
    observed_at = now_utc or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    observed_at = observed_at.astimezone(UTC)
    seconds_until_day_reset, seconds_until_month_reset = _utc_reset_windows(
        observed_at
    )
    planned_specs: list[
        tuple[MoralisEndpointSpec, list[tuple[str | None, str | None]], int]
    ] = []
    configured_target_count = 0
    rejected_target_count = 0
    estimated_cu = 0
    configured_daily_cu = 0
    minimum_planned_request_cu: int | None = None
    for spec in moralis_endpoint_registry():
        configured_targets = _targets_for_spec(
            spec,
            wallets=wallets,
            tokens=tokens,
            metadata_tokens=metadata_tokens,
        )
        configured_target_count += len(configured_targets)
        targets: list[tuple[str | None, str | None]] = []
        for wallet, token in configured_targets:
            identity = prepare_request_identity(
                spec,
                chain=chain,
                wallet=wallet,
                token=token,
            )
            if identity.error_class is not None:
                rejected_target_count += 1
                continue
            targets.append((identity.wallet, identity.token))
        target_count = len(targets)
        endpoint_cu = target_count * spec.cu_cost
        endpoint_configured_daily_cu = sum(
            _conservative_daily_cu(
                cost=spec.cu_cost,
                cadence_seconds=_cadence_seconds_for_target(spec, target_index=index),
            )
            for index, _target in enumerate(targets)
        )
        estimated_cu += endpoint_cu
        configured_daily_cu += endpoint_configured_daily_cu
        planned_specs.append((spec, targets, len(configured_targets)))
        if targets:
            minimum_planned_request_cu = (
                int(spec.cu_cost)
                if minimum_planned_request_cu is None
                else min(minimum_planned_request_cu, int(spec.cu_cost))
            )

    effective_daily_limit = int(authority["effective_daily_compute_unit_limit"] or 0)
    remaining_today = int(authority["remaining_today_compute_units"] or 0)
    remaining_month = int(authority["remaining_month_compute_units"] or 0)
    remaining_window_cu = min(remaining_today, remaining_month)
    current_window_daily_allowance = min(
        effective_daily_limit,
        _remaining_daily_equivalent(remaining_today, seconds_until_day_reset),
        _remaining_daily_equivalent(remaining_month, seconds_until_month_reset),
    )
    remaining_authority_below_minimum = bool(
        minimum_planned_request_cu is not None
        and remaining_window_cu < minimum_planned_request_cu
    )
    provider_polling_blocked = bool(
        authority["provider_polling_blocked"] or remaining_authority_below_minimum
    )
    adaptive_cadence_scale = _adaptive_cadence_scale(
        configured_daily_cu=configured_daily_cu,
        configured_cycle_cu=estimated_cu,
        effective_daily_limit=current_window_daily_allowance,
        authority_available=bool(authority["budget_authority_available"]),
        provider_polling_blocked=provider_polling_blocked,
    )
    steady_state_cadence_scale = _adaptive_cadence_scale(
        configured_daily_cu=configured_daily_cu,
        configured_cycle_cu=estimated_cu,
        effective_daily_limit=effective_daily_limit,
        authority_available=bool(authority["budget_authority_available"]),
        provider_polling_blocked=bool(authority["provider_polling_blocked"]),
    )
    endpoint_rows: list[dict[str, Any]] = []
    estimated_daily_cu = 0
    steady_state_estimated_daily_cu = 0
    for spec, targets, spec_configured_target_count in planned_specs:
        target_count = len(targets)
        endpoint_cu = target_count * spec.cu_cost
        effective_cadences = [
            _adaptive_cadence_seconds(
                _cadence_seconds_for_target(spec, target_index=index),
                scale=adaptive_cadence_scale,
            )
            for index, _target in enumerate(targets)
        ]
        endpoint_daily_cu = (
            sum(
                _conservative_daily_cu(
                    cost=spec.cu_cost,
                    cadence_seconds=cadence_seconds,
                )
                for cadence_seconds in effective_cadences
            )
            if adaptive_cadence_scale is not None
            else 0
        )
        estimated_daily_cu += endpoint_daily_cu
        steady_state_daily_cu = (
            sum(
                _conservative_daily_cu(
                    cost=spec.cu_cost,
                    cadence_seconds=_adaptive_cadence_seconds(
                        _cadence_seconds_for_target(spec, target_index=index),
                        scale=steady_state_cadence_scale,
                    ),
                )
                for index, _target in enumerate(targets)
            )
            if steady_state_cadence_scale is not None
            else 0
        )
        steady_state_estimated_daily_cu += steady_state_daily_cu
        endpoint_rows.append(
            {
                "endpoint_id": spec.endpoint_id,
                "group": spec.group,
                "cadence_seconds_tier0": spec.cadence_seconds_tier0,
                "cadence_seconds_tier1": spec.cadence_seconds_tier1,
                "cadence_seconds_full_watchlist": spec.cadence_seconds_full_watchlist,
                "effective_cadence_seconds_tier0": _scaled_cadence_or_none(
                    spec.cadence_seconds_tier0,
                    scale=adaptive_cadence_scale,
                ),
                "effective_cadence_seconds_tier1": _scaled_cadence_or_none(
                    spec.cadence_seconds_tier1,
                    scale=adaptive_cadence_scale,
                ),
                "effective_cadence_seconds_full_watchlist": _scaled_cadence_or_none(
                    spec.cadence_seconds_full_watchlist,
                    scale=adaptive_cadence_scale,
                ),
                "compute_unit_cost": spec.cu_cost,
                "configured_target_count": spec_configured_target_count,
                "target_count": target_count,
                "identity_rejected_target_count": (
                    spec_configured_target_count - target_count
                ),
                "estimated_compute_units_per_cycle": endpoint_cu,
                "estimated_compute_units_per_day": endpoint_daily_cu,
                "steady_state_estimated_compute_units_per_day": (
                    steady_state_daily_cu
                ),
                "stream_based": spec.stream_based,
                "polling_supported": spec.polling_supported,
                "polling_block_reason": spec.polling_block_reason,
                "transport_alias_of": spec.transport_alias_of,
                "feature_outputs": list(spec.feature_outputs),
            }
        )
    fair_rotation = bool(
        durable_rotation_available
        and authority["budget_authority_available"]
        and not provider_polling_blocked
    )
    current_run_compute_unit_budget = (
        min(remaining_window_cu, estimated_cu)
        if not provider_polling_blocked
        else 0
    )
    return {
        "schema_version": "moralis_scheduler_plan_v1",
        "budget_authority": authority["budget_authority"],
        "budget_authority_available": authority["budget_authority_available"],
        "persistent_budget_authority_required": authority[
            "persistent_budget_authority_required"
        ],
        "provider_polling_blocked": provider_polling_blocked,
        "provider_polling_block_reason": (
            "REMAINING_CU_BELOW_MINIMUM_ENDPOINT_COST"
            if remaining_authority_below_minimum
            else (
                "BUDGET_AUTHORITY_UNAVAILABLE"
                if authority["provider_polling_blocked"]
                else None
            )
        ),
        "daily_compute_unit_budget": authority["daily_compute_unit_budget"],
        "daily_compute_unit_reserve": authority["daily_compute_unit_reserve"],
        "effective_daily_compute_unit_limit": effective_daily_limit,
        "remaining_today_compute_units": authority["remaining_today_compute_units"],
        "monthly_compute_unit_budget": authority["monthly_compute_unit_budget"],
        "remaining_month_compute_units": authority["remaining_month_compute_units"],
        "remaining_window_compute_units": remaining_window_cu,
        "seconds_until_utc_day_reset": seconds_until_day_reset,
        "seconds_until_utc_month_reset": seconds_until_month_reset,
        "current_window_daily_compute_unit_allowance": (
            current_window_daily_allowance
        ),
        "minimum_planned_request_compute_units": minimum_planned_request_cu,
        "current_run_compute_unit_budget": current_run_compute_unit_budget,
        "estimated_compute_units_per_cycle": estimated_cu,
        "configured_estimated_compute_units_per_day": configured_daily_cu,
        "estimated_compute_units_per_day": estimated_daily_cu,
        "steady_state_estimated_compute_units_per_day": (
            steady_state_estimated_daily_cu
        ),
        "configured_daily_demand_to_limit_ratio": (
            round(configured_daily_cu / effective_daily_limit, 6)
            if effective_daily_limit > 0
            else None
        ),
        "estimated_daily_demand_to_limit_ratio": (
            round(estimated_daily_cu / current_window_daily_allowance, 6)
            if current_window_daily_allowance > 0
            else None
        ),
        "normal_rps": authority["normal_rps"],
        "catchup_rps": authority["catchup_rps"],
        "hard_rps": authority["hard_rps"],
        "current_rps": authority["current_rps"],
        "adaptive_cadence_scale": adaptive_cadence_scale,
        "steady_state_adaptive_cadence_scale": steady_state_cadence_scale,
        "configured_target_count": configured_target_count,
        "valid_target_count": configured_target_count - rejected_target_count,
        "identity_rejected_target_count": rejected_target_count,
        "identity_validation_applied": True,
        "durable_fair_rotation": fair_rotation,
        "all_valid_configured_targets_eventually_eligible": fair_rotation,
        "does_not_poll_every_symbol_every_minute": True,
        "configured_no_watchlist_is_green": False,
        "endpoints": endpoint_rows,
    }


def _targets_for_spec(
    spec: MoralisEndpointSpec,
    *,
    wallets: list[str],
    tokens: list[str],
    metadata_tokens: list[str] | None = None,
) -> list[tuple[str | None, str | None]]:
    if spec.stream_based or not spec.polling_supported or spec.transport_alias_of is not None:
        return []
    if spec.requires_wallet:
        return [(wallet, None) for wallet in _unique_targets(wallets)]
    if spec.requires_token:
        selected = (
            tokens if metadata_tokens is None else metadata_tokens
        ) if spec.endpoint_id == "token_metadata" else tokens
        return [(None, token) for token in _unique_targets(selected or [])]
    return [(None, None)]


def _unique_targets(values: list[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(str(value).strip())
    return selected


def _conservative_daily_cu(*, cost: int, cadence_seconds: int) -> int:
    if cost <= 0 or cadence_seconds <= 0:
        return 0
    return int(cost) * ((86_400 + int(cadence_seconds) - 1) // int(cadence_seconds))


def _utc_reset_windows(observed_at: datetime) -> tuple[int, int]:
    now = observed_at.astimezone(UTC)
    next_day = (now + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return (
        max(1, int(math.ceil((next_day - now).total_seconds()))),
        max(1, int(math.ceil((next_month - now).total_seconds()))),
    )


def _remaining_daily_equivalent(remaining_cu: int, seconds_to_reset: int) -> int:
    if remaining_cu <= 0 or seconds_to_reset <= 0:
        return 0
    return max(0, int((int(remaining_cu) * 86_400) // int(seconds_to_reset)))


def _adaptive_cadence_scale(
    *,
    configured_daily_cu: int,
    configured_cycle_cu: int,
    effective_daily_limit: int,
    authority_available: bool,
    provider_polling_blocked: bool,
) -> float | None:
    if (
        not authority_available
        or provider_polling_blocked
        or effective_daily_limit <= 0
    ):
        return None
    if configured_daily_cu <= 0:
        return 1.0
    # Reserve one complete valid-target cycle for cadence-rounding overhead.
    # The remainder is the sustainable recurring allowance; this makes the
    # scale derive from the live authority and configured workload rather than
    # a hard-coded target subset or polling cutoff.
    recurring_allowance = effective_daily_limit - max(0, configured_cycle_cu)
    if recurring_allowance <= 0:
        return float(configured_daily_cu)
    return max(1.0, configured_daily_cu / recurring_allowance)


def _adaptive_cadence_seconds(
    cadence_seconds: int,
    *,
    scale: float | None,
) -> int:
    base = max(1, int(cadence_seconds))
    if scale is None:
        return base
    return max(base, int(math.ceil(base * max(1.0, float(scale)))))


def _scaled_cadence_or_none(
    cadence_seconds: int,
    *,
    scale: float | None,
) -> int | None:
    if scale is None:
        return None
    return _adaptive_cadence_seconds(cadence_seconds, scale=scale)


def _budget_plan_view(budget_status: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = dict(budget_status or {})
    supplied_compute = supplied.get("compute_budget")
    compute = dict(supplied_compute) if isinstance(supplied_compute, Mapping) else {}
    persistent_raw = supplied.get("persistent_cu_ledger")
    persistent = dict(persistent_raw) if isinstance(persistent_raw, Mapping) else {}
    persistent_available = persistent.get("ledger_available") is True
    persistent_required = supplied.get("cu_ledger_required") is True
    daily_budget = _status_int(compute.get("daily_budget"))
    daily_reserve = _status_int(compute.get("daily_reserve"))
    monthly_budget = _status_int(compute.get("monthly_budget"))
    configured_available = (
        isinstance(supplied_compute, Mapping)
        and daily_budget > 0
        and monthly_budget > 0
    )
    configured_spendable = max(
        0,
        daily_budget - daily_reserve,
    )
    if persistent_available:
        effective_daily_limit = _status_int(persistent.get("daily_limit_cu"))
        remaining_today = _status_int(persistent.get("remaining_today_cu"))
        effective_monthly_budget = _status_int(persistent.get("monthly_limit_cu"))
        remaining_month = _status_int(persistent.get("remaining_month_cu"))
        authority_available = effective_daily_limit > 0 and effective_monthly_budget > 0
        authority = (
            "DURABLE_CU_LEDGER"
            if authority_available
            else "DURABLE_CU_LEDGER_INVALID"
        )
    elif persistent_required:
        authority = "DURABLE_CU_LEDGER_UNAVAILABLE"
        authority_available = False
        effective_daily_limit = 0
        remaining_today = 0
        effective_monthly_budget = (
            _status_int(persistent.get("monthly_limit_cu"))
            if "monthly_limit_cu" in persistent
            else monthly_budget
        )
        remaining_month = 0
    elif configured_available:
        authority = "CONFIGURED_LOCAL_VIEW"
        authority_available = True
        effective_daily_limit = configured_spendable
        remaining_today = _status_int(compute.get("remaining_today"))
        effective_monthly_budget = monthly_budget
        remaining_month = _status_int(compute.get("remaining_month"))
    else:
        authority = "RUNTIME_BUDGET_AUTHORITY_UNBOUND"
        authority_available = False
        effective_daily_limit = 0
        remaining_today = 0
        effective_monthly_budget = 0
        remaining_month = 0
    provider_polling_blocked = (
        supplied.get("provider_polling_blocked") is True
        or not authority_available
    )
    return {
        "budget_authority": authority,
        "budget_authority_available": authority_available,
        "persistent_budget_authority_required": persistent_required,
        "provider_polling_blocked": provider_polling_blocked,
        "daily_compute_unit_budget": daily_budget,
        "daily_compute_unit_reserve": daily_reserve,
        "effective_daily_compute_unit_limit": effective_daily_limit,
        "remaining_today_compute_units": remaining_today,
        "monthly_compute_unit_budget": effective_monthly_budget,
        "remaining_month_compute_units": remaining_month,
        "normal_rps": _status_int(supplied.get("normal_rps")),
        "catchup_rps": _status_int(supplied.get("catchup_rps")),
        "hard_rps": _status_int(supplied.get("hard_rps")),
        "current_rps": _status_int(supplied.get("current_rps")),
    }


def _status_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _status_float(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return float(default)
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return parsed if math.isfinite(parsed) and parsed > 0.0 else float(default)


def _acquire_scheduler_lease(
    redis_client: Any | None,
    *,
    chain: str,
) -> tuple[str | None, bool, bool]:
    if redis_client is None:
        return None, False, True
    lease_token = uuid.uuid4().hex
    try:
        acquired = bool(
            redis_client.set(
                _scheduler_lease_key(chain),
                lease_token,
                nx=True,
                ex=_scheduler_lease_ttl_seconds(),
            )
        )
    except Exception:
        return None, False, False
    return (lease_token if acquired else None), True, acquired


def _renew_scheduler_lease(
    redis_client: Any,
    *,
    chain: str,
    lease_token: str,
) -> bool:
    key = _scheduler_lease_key(chain)
    ttl_seconds = _scheduler_lease_ttl_seconds()
    try:
        return bool(
            redis_client.eval(
                _COMPARE_EXPIRE_SCRIPT,
                1,
                key,
                lease_token,
                ttl_seconds,
            )
        )
    except Exception:
        return False


def _release_scheduler_lease(
    redis_client: Any,
    *,
    chain: str,
    lease_token: str,
) -> bool:
    return _compare_delete(
        redis_client,
        key=_scheduler_lease_key(chain),
        expected_value=lease_token,
    )


def _claim_poll_job(
    redis_client: Any | None,
    *,
    chain: str,
    job_id: str,
    cadence_seconds: int,
    lease_token: str | None,
) -> tuple[bool, bool, str | None, str | None]:
    if redis_client is None:
        return True, False, None, None
    key = _cadence_claim_key(chain, job_id=job_id)
    if not lease_token:
        return False, False, key, None
    claim_value = uuid.uuid4().hex
    try:
        raw = redis_client.eval(
            _FENCED_CADENCE_CLAIM_SCRIPT,
            2,
            _scheduler_lease_key(chain),
            key,
            lease_token,
            claim_value,
            max(1, int(math.ceil(cadence_seconds))),
        )
    except Exception:
        return False, False, key, None
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        return False, False, key, None
    try:
        claimed = int(raw[0]) == 1
        state_available = int(raw[1]) == 1
    except (TypeError, ValueError, OverflowError):
        return False, False, key, None
    return claimed, state_available, key, claim_value if claimed else None


def _release_cadence_claim(
    redis_client: Any | None,
    *,
    key: str,
    value: str,
) -> bool:
    if redis_client is None:
        return True
    return _compare_delete(redis_client, key=key, expected_value=value)


def _compare_delete(
    redis_client: Any,
    *,
    key: str,
    expected_value: str,
) -> bool:
    try:
        return bool(
            redis_client.eval(
                _COMPARE_DELETE_SCRIPT,
                1,
                key,
                expected_value,
            )
        )
    except Exception:
        return False


def _scheduler_lease_ttl_seconds() -> int:
    return max(1, int(math.ceil(max(1.0, MORALIS_TIMEOUT_SECONDS) * 2.0)))


def _scheduler_lease_key(chain: str) -> str:
    normalized_chain = _safe_chain_key_component(chain)
    return SCHEDULER_LEASE_KEY.format(chain=normalized_chain)


def _cadence_claim_key(chain: str, *, job_id: str) -> str:
    normalized_chain = _safe_chain_key_component(chain)
    digest = hashlib.sha256(job_id.encode("utf-8", errors="replace")).hexdigest()
    return CADENCE_CLAIM_KEY.format(chain=normalized_chain, job_digest=digest)


def _safe_chain_key_component(chain: str) -> str:
    normalized_chain = _norm_chain(chain)
    return normalized_chain if normalized_chain in MORALIS_EVM_CHAIN_PARAMS else "invalid"


def _rotate_poll_jobs(
    redis_client: Any | None,
    *,
    chain: str,
    jobs: list[PollJob],
    context_symbol: str,
) -> tuple[list[PollJob], bool]:
    if redis_client is None:
        return jobs, False
    cursor_key = _rotation_cursor_key(chain)
    try:
        raw_cursor = redis_client.get(cursor_key)
    except Exception:
        return jobs, False
    if raw_cursor is None or not jobs:
        return jobs, True
    if isinstance(raw_cursor, bytes):
        raw_cursor = raw_cursor.decode("utf-8", errors="replace")
    cursor = str(raw_cursor)
    job_ids = [
        _poll_job_id(
            spec,
            chain=_norm_chain(chain),
            wallet=wallet,
            token=token,
            context_symbol=context_symbol,
        )
        for spec, _target_index, wallet, token in jobs
    ]
    try:
        start = (job_ids.index(cursor) + 1) % len(jobs)
    except ValueError:
        start = 0
    return [*jobs[start:], *jobs[:start]], True


def _write_rotation_cursor(
    redis_client: Any | None,
    *,
    chain: str,
    job_id: str,
    lease_token: str | None,
) -> bool:
    if redis_client is None or not lease_token:
        return False
    try:
        return bool(
            redis_client.eval(
                _FENCED_CURSOR_WRITE_SCRIPT,
                2,
                _scheduler_lease_key(chain),
                _rotation_cursor_key(chain),
                lease_token,
                job_id,
            )
        )
    except Exception:
        return False


def _rotation_cursor_key(chain: str) -> str:
    return ROTATION_CURSOR_KEY.format(chain=_safe_chain_key_component(chain))


def _poll_job_id(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
    context_symbol: str,
) -> str:
    target = str(wallet or token or context_symbol).strip().lower()
    target_digest = hashlib.sha256(
        target.encode("utf-8", errors="replace")
    ).hexdigest()
    return f"{spec.endpoint_id}:{_safe_chain_key_component(chain)}:{target_digest}"


def _target_fingerprint(value: object | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _canonical_token_transfer_owner(plan: Mapping[str, Any]) -> bool:
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list):
        return False
    return any(
        isinstance(row, Mapping)
        and row.get("endpoint_id") == "token_transfers"
        and _status_int(row.get("target_count")) > 0
        for row in endpoints
    )


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
    verified_wallet_rows = read_wallet_watchlist(redis_client)
    if not wallets:
        wallets = [
            row["address"]
            for row in verified_wallet_rows
            if _norm_chain(row.get("chain")) == _norm_chain(chain)
        ]
    scoped_token_map_tokens = read_pollable_tokens(redis_client, symbol=symbol)
    all_token_map_tokens = read_pollable_tokens(redis_client, symbol=None)
    all_metadata_validation_tokens = read_metadata_validation_tokens(
        redis_client,
        symbol=None,
    )
    identity_token_rows = all_token_map_tokens or scoped_token_map_tokens
    token_map_tokens = scoped_token_map_tokens
    if not any(_norm_chain(row.get("chain")) == _norm_chain(chain) for row in token_map_tokens):
        # The default context symbol (e.g. BTCUSDT) has no ERC-20 pollable
        # contracts, so per-symbol scoping yields zero token whale-flow features.
        # Fall back to every pollable token in the map so whale-flow / exchange-flow
        # features populate across the tracked universe (LINK, CRV, AAVE, ...).
        token_map_tokens = all_token_map_tokens
    if not tokens:
        # The token map stores the canonical chain name ("ethereum") while the loop
        # runs with the Moralis chain param ("eth"); normalize both before matching
        # so verified ERC-20 tokens are actually selected for whale-flow polling.
        tokens = [
            row["token"]
            for row in token_map_tokens
            if _norm_chain(row.get("chain")) == _norm_chain(chain)
        ]
    metadata_tokens = [
        row["token"]
        for row in all_metadata_validation_tokens
        if _norm_chain(row.get("chain")) == _norm_chain(chain)
    ]
    # Reverse identity map: (canonical chain, contract) -> its OWN verified
    # trading symbol. Identity is always indexed from the complete published map,
    # even when an operator supplies a token outside the context symbol's scope.
    # Because token-map native perps (BTCUSDT/ETHUSDT -> contract "native") are
    # non-pollable, they never appear here, so an ERC-20 (e.g. WBTC) can never be
    # attributed to BTCUSDT. This replaces the old fixed-context-symbol attribution.
    # Any repeated identity is omitted from the resolvable map and reported as
    # ambiguous; there is deliberately no first/last-writer-wins behavior.
    contract_symbol_map, ambiguous_contract_keys = _build_contract_symbol_map(identity_token_rows)
    token_map_count = _token_map_count(redis_client)
    wallet_count = len(verified_wallet_rows)
    has_operator_inputs = explicit_wallets or explicit_tokens
    has_valid_source_targets = bool(wallets or tokens or metadata_tokens)
    if not has_operator_inputs and not has_valid_source_targets and wallet_count <= 0:
        status = "CONFIGURED_NO_WATCHLIST"
    elif not has_operator_inputs and token_map_count <= 0:
        status = "CONFIGURED_NO_TOKEN_MAP"
    else:
        status = "WATCHLIST_READY"
    return {
        "status": status,
        "wallets": wallets,
        "tokens": tokens,
        "metadata_tokens": _unique_targets(metadata_tokens),
        "token_map_count": token_map_count,
        "wallet_watchlist_count": wallet_count if not explicit_wallets else len(wallets),
        "operator_supplied_wallets": explicit_wallets,
        "operator_supplied_tokens": explicit_tokens,
        "pollable_token_count": len(token_map_tokens),
        "metadata_validation_token_count": len(metadata_tokens),
        "contract_symbol_map": contract_symbol_map,
        "ambiguous_contract_keys": ambiguous_contract_keys,
    }


def _build_contract_symbol_map(
    token_rows: list[dict[str, str]],
) -> tuple[dict[ContractIdentityKey, dict[str, str]], set[ContractIdentityKey]]:
    candidates: dict[ContractIdentityKey, list[dict[str, str]]] = {}
    for row in token_rows:
        token = str(row.get("token") or "").strip().lower()
        symbol = str(row.get("symbol") or "").strip().upper()
        chain = _norm_chain(row.get("chain"))
        if not token or not symbol or not chain:
            continue
        identity_key = (chain, token)
        candidates.setdefault(identity_key, []).append(
            {"symbol": symbol, "chain": chain, "contract": token}
        )

    ambiguous = {identity_key for identity_key, rows in candidates.items() if len(rows) != 1}
    resolved = {
        identity_key: rows[0]
        for identity_key, rows in candidates.items()
        if identity_key not in ambiguous
    }
    return resolved, ambiguous


def _contract_identity_key(*, chain: Any, token: Any) -> ContractIdentityKey:
    return (_norm_chain(chain), str(token or "").strip().lower())


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
    cu_budget_status = _publish_persistent_cu_budget_status(limiter)
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
        "publication_count": 0,
        "request_count": 0,
        "dispatched_request_count": 0,
        "pre_dispatch_denial_publication_count": 0,
        "skipped_not_due_count": 0,
        "skipped_not_due": [],
        "actual_payload_results": 0,
        "does_not_poll_every_symbol_every_minute": True,
        "stream_endpoints_are_webhook_only": True,
        "heartbeat_only_green_allowed": False,
        "configured_no_watchlist_is_green": False,
        "canonical_token_transfer_transport_owner": False,
        "durable_fair_rotation": False,
        "rotation_state_available": False,
        "rotation_cursor_advanced_count": 0,
        "durable_cadence_state_available": False,
        "durable_cadence_claim_count": 0,
        "durable_cadence_suppressed_count": 0,
        "durable_cadence_release_failure_count": 0,
        "scheduler_lease_state_available": False,
        "scheduler_lease_acquired": False,
        "scheduler_lease_released": False,
        "scheduler_run_suppressed_reason": "CONFIGURED_NO_WATCHLIST",
        "response_semantics_quarantined_from_trainer": True,
        "durable_cu_budget_status_key": "v2:provider:moralis:cu_budget_status",
        "durable_cu_budget_status_published": bool(
            cu_budget_status and cu_budget_status.get("status_publish_succeeded") is True
        ),
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
        redis_client.set(
            "v2:provider:moralis:health",
            json.dumps(health, sort_keys=True, default=str),
            ex=3600,
        )
        redis_client.set(
            "v2:provider:moralis:usage",
            json.dumps(usage, sort_keys=True, default=str),
            ex=3600,
        )
        redis_client.set(
            "v2:provider:moralis:endpoint_status",
            json.dumps(endpoint_status, sort_keys=True, default=str),
            ex=3600,
        )
        redis_client.set(
            SCHEDULER_STATUS_KEY,
            json.dumps(status, sort_keys=True, default=str),
            ex=300,
        )
    return status


def _publish_persistent_cu_budget_status(
    limiter: MoralisRateLimiter,
) -> dict[str, Any] | None:
    """Refresh the bounded durable-CU status without changing authorization."""

    authority = getattr(limiter, "cu", None)
    publish_status = getattr(authority, "publish_status", None)
    if not callable(publish_status):
        return None
    try:
        usage = limiter.as_dict()
        published = publish_status(
            extra={
                "provider_polling_blocked": usage.get("provider_polling_blocked"),
                "distributed_rps_guard": usage.get("distributed_rps_guard"),
                "cu_ledger_required": usage.get("cu_ledger_required"),
                "status_key": "v2:provider:moralis:cu_budget_status",
            }
        )
    except Exception:
        return None
    return dict(published) if isinstance(published, Mapping) else None


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
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
