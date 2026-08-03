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
    publish_token_map,
    read_metadata_validation_tokens,
    read_pollable_tokens,
)
from app.services.smart_money_wallets.wallet_watchlist import (
    read_wallet_watchlist,
    refresh_candidate_wallet_watchlist,
)
from app.cli.v2_moralis_token_metadata_validate import validate_token_map

SCHEDULER_STATUS_KEY = MORALIS_SCHEDULER_STATUS_KEY
LEGACY_ROTATION_CURSOR_KEY = "v2:provider:moralis:rotation_cursor:{chain}"
ROTATION_CURSOR_KEY = "v2:provider:moralis:rotation_cursor_v2:{chain}"
ROTATION_ORDER_POLICY = "TIER_FIRST_INTERLEAVED_ENDPOINTS_V1"
SCHEDULER_LEASE_KEY = "v2:provider:moralis:scheduler_lease:{chain}"
CADENCE_CLAIM_KEY = "v2:provider:moralis:cadence_claim:{chain}:{job_digest}"
PACED_CU_ADMISSION_WINDOW_PREFIX = (
    "v2:provider:moralis:cu_admission_credit"
)
PACED_CU_RESERVATION_KEY_PREFIX = (
    "v2:provider:moralis:cu_admission_reservation"
)
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

_FENCED_PACED_CU_CLAIM_SCRIPT = """
-- MORALIS_FENCED_PACED_CU_CLAIM_V3
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return {-1, '0', 0, ''}
end
local now = redis.call('TIME')
local now_seconds = tonumber(now[1])
local interval = tonumber(ARGV[2])
local window_id = math.floor(now_seconds / interval)
local cost = tonumber(ARGV[3])
local remaining_today = tonumber(ARGV[4])
local remaining_month = tonumber(ARGV[5])
local day_opportunities = tonumber(ARGV[6])
local month_opportunities = tonumber(ARGV[7])
local day_reset = tonumber(ARGV[8])
local month_reset = tonumber(ARGV[9])
local reservation_id = ARGV[10]
if now_seconds >= day_reset or now_seconds >= month_reset then
  return {-4, '0', window_id, ''}
end
if redis.call('EXISTS', KEYS[3]) == 1 then
  return {-5, '0', window_id, ''}
end
local state = redis.call(
  'HMGET', KEYS[2],
  'window_id', 'credit_cu', 'interval_seconds',
  'day_reset_epoch', 'month_reset_epoch', 'earned_per_window_cu'
)
local reset = state[1] == false
if not reset then
  local stored_day_reset = tonumber(state[4])
  local stored_month_reset = tonumber(state[5])
  reset = now_seconds >= stored_day_reset
    or now_seconds >= stored_month_reset
    or stored_day_reset ~= day_reset
    or stored_month_reset ~= month_reset
end
local previous_window = window_id - 1
local credit = 0.0
local daily_earn = remaining_today / day_opportunities
local monthly_earn = remaining_month / month_opportunities
local earned_per_window = math.min(daily_earn, monthly_earn)
local earned_for_elapsed = earned_per_window
if not reset then
  local stored_interval = tonumber(state[3])
  if stored_interval ~= interval then
    return {-2, tostring(tonumber(state[2]) or 0), window_id, ''}
  end
  previous_window = tonumber(state[1])
  credit = tonumber(state[2]) or 0.0
  earned_for_elapsed = math.min(
    tonumber(state[6]) or earned_per_window,
    earned_per_window
  )
  if window_id < previous_window then
    return {-3, tostring(credit), window_id, ''}
  end
end
local elapsed_windows = window_id - previous_window
local authority_bound = math.min(remaining_today, remaining_month)
credit = math.min(authority_bound, credit + elapsed_windows * earned_for_elapsed)
local expires_at = math.min(day_reset, month_reset) + interval * 2
local function persist(value)
  redis.call(
    'HSET', KEYS[2],
    'window_id', tostring(window_id),
    'credit_cu', tostring(value),
    'interval_seconds', tostring(interval),
    'day_reset_epoch', tostring(day_reset),
    'month_reset_epoch', tostring(month_reset),
    'authority_bound_cu', tostring(authority_bound),
    'earned_per_window_cu', tostring(earned_per_window)
  )
  redis.call('EXPIREAT', KEYS[2], expires_at)
end
if credit + 0.000000001 < cost then
  persist(credit)
  return {0, tostring(credit), window_id, ''}
end
credit = credit - cost
persist(credit)
redis.call(
  'HSET', KEYS[3],
  'reservation_id', reservation_id,
  'lease_key', KEYS[1],
  'lease_token', ARGV[1],
  'window_id', tostring(window_id),
  'cost_cu', tostring(cost),
  'credit_key', KEYS[2],
  'day_reset_epoch', tostring(day_reset),
  'month_reset_epoch', tostring(month_reset),
  'created_at_epoch', tostring(now_seconds)
)
redis.call('EXPIREAT', KEYS[3], expires_at)
return {1, tostring(credit), window_id, reservation_id}
"""

_FENCED_PACED_CU_RELEASE_SCRIPT = """
-- MORALIS_FENCED_PACED_CU_RELEASE_V3
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return 0
end
local reservation = redis.call(
  'HMGET', KEYS[3],
  'reservation_id', 'lease_key', 'lease_token',
  'window_id', 'cost_cu', 'credit_key',
  'day_reset_epoch', 'month_reset_epoch'
)
if reservation[1] == false
  or reservation[1] ~= ARGV[2]
  or reservation[2] ~= KEYS[1]
  or reservation[3] ~= ARGV[1]
  or reservation[6] ~= KEYS[2]
then
  return 0
end
local expected_window = tonumber(ARGV[3])
local expected_cost = tonumber(ARGV[4])
if tonumber(reservation[4]) ~= expected_window
  or tonumber(reservation[5]) ~= expected_cost
then
  return 0
end
local current_window = tonumber(redis.call('HGET', KEYS[2], 'window_id'))
local current_day_reset = redis.call('HGET', KEYS[2], 'day_reset_epoch')
local current_month_reset = redis.call('HGET', KEYS[2], 'month_reset_epoch')
if current_window == nil
  or current_window ~= expected_window
  or reservation[7] ~= current_day_reset
  or reservation[8] ~= current_month_reset
then
  return 0
end
local current_raw = redis.call('HGET', KEYS[2], 'credit_cu')
local bound_raw = redis.call('HGET', KEYS[2], 'authority_bound_cu')
if current_raw == false or bound_raw == false then
  return 0
end
local current = tonumber(current_raw)
local bound = tonumber(bound_raw)
if current == nil
  or bound == nil
  or current < 0
  or bound < 0
  or current > bound + 0.000000001
then
  return 0
end
redis.call(
  'HSET', KEYS[2],
  'credit_cu', tostring(math.min(bound, current + expected_cost))
)
redis.call('DEL', KEYS[3])
return 1
"""

_FENCED_PACED_CU_FINALIZE_SCRIPT = """
-- MORALIS_FENCED_PACED_CU_FINALIZE_V1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return 0
end
local reservation = redis.call(
  'HMGET', KEYS[3],
  'reservation_id', 'lease_key', 'lease_token',
  'window_id', 'cost_cu', 'credit_key',
  'day_reset_epoch', 'month_reset_epoch'
)
if reservation[1] == false
  or reservation[1] ~= ARGV[2]
  or reservation[2] ~= KEYS[1]
  or reservation[3] ~= ARGV[1]
  or reservation[6] ~= KEYS[2]
  or tonumber(reservation[4]) ~= tonumber(ARGV[3])
  or tonumber(reservation[5]) ~= tonumber(ARGV[4])
then
  return 0
end
if reservation[7] ~= redis.call('HGET', KEYS[2], 'day_reset_epoch')
  or reservation[8] ~= redis.call('HGET', KEYS[2], 'month_reset_epoch')
then
  return 0
end
redis.call('DEL', KEYS[3])
return 1
"""


def _norm_chain(value: Any) -> str:
    v = str(value or "").strip().lower()
    return str(MORALIS_EVM_CHAIN_ALIASES.get(v, v))


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
            maintain_candidate_watchlist=True,
            scheduler_interval_seconds=max(60.0, float(args.sleep_seconds)),
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
        "status_scope": report.get("status_scope"),
        "bootstrap_status": report.get("bootstrap_status"),
        "chain": report.get("chain"),
        "token_count": report.get("token_count"),
        "token_map_count": report.get("token_map_count"),
        "wallet_watchlist_count": report.get("wallet_watchlist_count"),
        "candidate_wallet_count": report.get("candidate_wallet_count"),
        "chain_candidate_wallet_count": report.get("chain_candidate_wallet_count"),
        "active_candidate_chain": report.get("active_candidate_chain"),
        "active_candidate_wallet_count": report.get("active_candidate_wallet_count"),
        "queued_candidate_wallet_count": report.get("queued_candidate_wallet_count"),
        "queued_candidate_wallet_chain_counts": report.get(
            "queued_candidate_wallet_chain_counts"
        ),
        "verified_smart_wallet_count": report.get("verified_smart_wallet_count"),
        "watchlist_refresh_action": report.get("watchlist_refresh_action"),
        "watchlist_refresh_succeeded": report.get("watchlist_refresh_succeeded"),
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
    maintain_candidate_watchlist: bool = False,
    scheduler_interval_seconds: float = 300.0,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    bootstrap_recovery = (
        _ensure_bootstrap_state(redis_client)
        if maintain_candidate_watchlist
        else {
            "schema_version": "moralis_bootstrap_recovery_v1",
            "status": "NOT_REQUESTED",
            "core_system_blocked": False,
            "raw_key_exposed": False,
        }
    )
    watchlist_refresh = (
        refresh_candidate_wallet_watchlist(redis_client)
        if maintain_candidate_watchlist
        else None
    )
    bootstrap = _resolve_bootstrap_inputs(
        redis_client,
        chain=chain,
        symbol=symbol,
        wallets=wallets,
        tokens=tokens,
    )
    bootstrap["watchlist_refresh"] = watchlist_refresh
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
        wallet_tiers=bootstrap["wallet_tiers"],
        scheduler_interval_seconds=scheduler_interval_seconds,
        now_utc=now_utc,
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
    durable_cadence_claim_ttl_max_seconds = 0
    paced_cu_admission_state_available = redis_client is not None
    paced_cu_admission_claim_count = 0
    paced_cu_admission_denied_count = 0
    paced_cu_admission_release_count = 0
    paced_cu_admission_release_failure_count = 0
    paced_cu_reservation_created_count = 0
    paced_cu_reservation_finalize_count = 0
    paced_cu_reservation_finalize_failure_count = 0
    paced_cu_admission_window_id: int | None = None
    paced_cu_admission_credit_balance_cu: float | None = None
    contract_symbol_map = bootstrap.get("contract_symbol_map") or {}
    ambiguous_contract_keys = set(bootstrap.get("ambiguous_contract_keys") or ())
    now_value = time.monotonic() if now_monotonic is None else float(now_monotonic)
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

    # Initial recovery is tier-first across endpoint families, not
    # endpoint-first across the entire watchlist.  This preserves source-tier
    # freshness intent: every T0 candidate becomes observable across the
    # configured wallet endpoints before the T1 backlog can dominate days of
    # earned-CU rotation.  Stable sorting retains registry order within a
    # wallet/tier and durable job IDs/cursor semantics remain unchanged.
    poll_jobs.sort(
        key=lambda job: _poll_job_priority_key(
            job,
            wallet_tiers=bootstrap["wallet_tiers"],
        )
    )

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
    poll_jobs, rotation_state_available, rotation_universe_digest = _rotate_poll_jobs(
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
            target_tier=(
                bootstrap["wallet_tiers"].get(str(identity.wallet or "").lower())
                if identity.wallet
                else None
            ),
        )
        # Source/tier cadence is the per-target no-sooner-than constraint.  The
        # adaptive UTC fair-share CU window plus durable cursor paces aggregate
        # overload; multiplying this cadence by backlog demand can strand every
        # target for years after one cursor wrap.
        cadence_seconds = configured_cadence_seconds
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
            # The base source cadence is the durable no-sooner-than boundary.
            # Backlog overload remains telemetry only; provider-wide durable
            # earned credit and UTC fair rotation pace aggregate CU without
            # poisoning a target with a historical multi-year cadence TTL.
            cadence_seconds=configured_cadence_seconds,
            lease_token=scheduler_lease_token,
        )
        durable_cadence_claim_ttl_max_seconds = max(
            durable_cadence_claim_ttl_max_seconds,
            configured_cadence_seconds,
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
        (
            paced_cu_admitted,
            paced_state_available,
            paced_credit_balance_cu,
            paced_window_id,
            paced_reservation_id,
        ) = _claim_paced_compute_units(
            redis_client,
            chain=request_chain,
            lease_token=scheduler_lease_token,
            scheduler_interval_seconds=_status_int(
                plan.get("scheduler_interval_seconds")
            ),
            cost_cu=int(spec.cu_cost),
            remaining_today_cu=_status_int(
                plan.get("remaining_today_compute_units")
            ),
            remaining_month_cu=_status_int(
                plan.get("remaining_month_compute_units")
            ),
            daily_admission_opportunities=_status_int(
                plan.get("daily_admission_opportunity_count")
            ),
            monthly_admission_opportunities=_status_int(
                plan.get("monthly_admission_opportunity_count")
            ),
            utc_day_reset_epoch_seconds=_status_int(
                plan.get("utc_day_reset_epoch_seconds")
            ),
            utc_month_reset_epoch_seconds=_status_int(
                plan.get("utc_month_reset_epoch_seconds")
            ),
        )
        paced_cu_admission_state_available = (
            paced_cu_admission_state_available and paced_state_available
        )
        if paced_window_id is not None:
            paced_cu_admission_window_id = paced_window_id
        paced_cu_admission_credit_balance_cu = paced_credit_balance_cu
        if not paced_cu_admitted:
            paced_cu_admission_denied_count += 1
            if cadence_claim_key is not None and cadence_claim_value is not None:
                claim_released = _release_cadence_claim(
                    redis_client,
                    key=cadence_claim_key,
                    value=cadence_claim_value,
                )
                if not claim_released:
                    durable_cadence_release_failure_count += 1
                    durable_cadence_state_available = False
            if not paced_state_available:
                scheduler_run_suppressed_reason = "PACED_CU_ADMISSION_STATE_UNAVAILABLE"
                break
            skipped.append(
                {
                    "endpoint_id": spec.endpoint_id,
                    "target_fingerprint": _target_fingerprint(target_id),
                    "reason": "PACED_CU_CREDIT_ACCUMULATING_FOR_NEXT_DUE_JOB",
                    "compute_unit_cost": int(spec.cu_cost),
                    "paced_credit_balance_compute_units": paced_credit_balance_cu,
                    "earned_compute_units_per_window": plan.get(
                        "earned_compute_units_per_window"
                    ),
                }
            )
            scheduler_run_suppressed_reason = (
                "PACED_CU_CREDIT_ACCUMULATING_FOR_NEXT_DUE_JOB"
            )
            break
        paced_cu_admission_claim_count += 1
        paced_cu_reservation_created_count += 1
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
            reservation_finalized = _finalize_paced_compute_units(
                redis_client,
                chain=request_chain,
                lease_token=scheduler_lease_token,
                window_id=paced_window_id,
                cost_cu=int(spec.cu_cost),
                reservation_id=paced_reservation_id,
            )
            if reservation_finalized:
                paced_cu_reservation_finalize_count += 1
            else:
                # The request is already dispatched and therefore remains
                # conservatively charged.  Stop admitting further work until
                # the reservation lifecycle is healthy again.
                paced_cu_reservation_finalize_failure_count += 1
                paced_cu_admission_state_available = False
                scheduler_run_suppressed_reason = (
                    "PACED_CU_RESERVATION_FINALIZE_FAILED"
                )
                stop_after_current_result = True
            if scheduler_state is not None:
                scheduler_state[state_key] = now_value
            cursor_written = _write_rotation_cursor(
                redis_client,
                chain=request_chain,
                job_id=state_key,
                rotation_universe_digest=rotation_universe_digest,
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
            paced_released = _release_paced_compute_units(
                redis_client,
                chain=request_chain,
                lease_token=scheduler_lease_token,
                window_id=paced_window_id,
                cost_cu=int(spec.cu_cost),
                reservation_id=paced_reservation_id,
            )
            if paced_released:
                paced_cu_admission_release_count += 1
            else:
                # Ambiguous/non-dispatched reservations remain conservatively
                # charged to this pacing window.  The durable provider CU
                # ledger remains the final spend authority.
                paced_cu_admission_release_failure_count += 1
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
            raw_response_bytes=response.raw_response_bytes,
            raw_response_sha256=response.raw_response_sha256,
            raw_response_byte_count=response.raw_response_byte_count,
            raw_response_bytes_scope=response.raw_response_bytes_scope,
            transport_started_at=response.transport_started_at,
            observed_at=response.observed_at,
            ingested_at=response.ingested_at,
            generated_at=_precise_now(),
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
    metadata_validation_report = _validate_cached_metadata(redis_client)
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
        wallet_tiers=bootstrap["wallet_tiers"],
        scheduler_interval_seconds=scheduler_interval_seconds,
        now_utc=now_utc,
        durable_rotation_available=(
            redis_client is not None
            and rotation_state_available
            and durable_cadence_state_available
            and paced_cu_admission_state_available
            and scheduler_lease_released
        ),
    )
    status = {
        "schema_version": "moralis_provider_scheduler_status_v1",
        "provider": "moralis",
        "status": scheduler_run_suppressed_reason or "READY",
        "status_scope": "SCHEDULER_RUN_CONTROL_STATE",
        "generated_utc": _now(),
        "chain": chain,
        "wallet_count": len(wallets),
        "token_count": len(tokens),
        "metadata_validation_token_count": len(metadata_tokens),
        "token_map_count": bootstrap["token_map_count"],
        "wallet_watchlist_count": bootstrap["wallet_watchlist_count"],
        "candidate_wallet_count": bootstrap["candidate_wallet_count"],
        "chain_candidate_wallet_count": bootstrap["chain_candidate_wallet_count"],
        "candidate_wallet_chain_counts": bootstrap["candidate_wallet_chain_counts"],
        "active_candidate_chain": bootstrap["active_candidate_chain"],
        "active_candidate_wallet_count": bootstrap[
            "active_candidate_wallet_count"
        ],
        "queued_candidate_wallet_count": bootstrap[
            "queued_candidate_wallet_count"
        ],
        "queued_candidate_wallet_chain_counts": bootstrap[
            "queued_candidate_wallet_chain_counts"
        ],
        "queued_candidate_wallet_polling_status": (
            "QUEUED_NOT_POLLED_BY_THIS_CHAIN_LOOP"
            if bootstrap["queued_candidate_wallet_count"]
            else "NO_QUEUED_CANDIDATES"
        ),
        "candidate_chain_activation_policy": (
            "SINGLE_RUNTIME_CHAIN_FAIR_PACED_CU_SCOPE_V1"
        ),
        "cross_chain_runtime_services_started_by_this_change": 0,
        "all_candidate_chains_runtime_active": (
            bootstrap["queued_candidate_wallet_count"] == 0
        ),
        "verified_smart_wallet_count": 0,
        "wallet_watchlist_semantics": "CANDIDATE_OBSERVATION_TARGETS_ONLY",
        "watchlist_refresh_action": (
            watchlist_refresh.get("refresh_action")
            if isinstance(watchlist_refresh, Mapping)
            else "NOT_REQUESTED"
        ),
        "watchlist_refresh_succeeded": (
            watchlist_refresh.get("refresh_succeeded") is True
            if isinstance(watchlist_refresh, Mapping)
            else None
        ),
        "watchlist_refresh_compute_units_reserved": (
            int(watchlist_refresh.get("compute_units_reserved") or 0)
            if isinstance(watchlist_refresh, Mapping)
            else 0
        ),
        "watchlist_refresh_moralis_request_count": (
            int(watchlist_refresh.get("moralis_request_count") or 0)
            if isinstance(watchlist_refresh, Mapping)
            else 0
        ),
        "bootstrap_recovery": bootstrap_recovery,
        "metadata_validation_report": metadata_validation_report,
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
        "current_run_compute_unit_budget_is_floor_of_new_credit_earned": True,
        "current_run_compute_unit_budget_is_hard_spend_cap": False,
        "durable_credit_balance_is_dispatch_authority": True,
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
        "rotation_cursor_schema_version": "moralis_rotation_cursor_v2",
        "rotation_order_policy": ROTATION_ORDER_POLICY,
        "rotation_universe_digest": rotation_universe_digest,
        "rotation_cursor_bound_to_exact_ordered_job_universe": True,
        "legacy_rotation_cursor_ignored": True,
        "legacy_rotation_cursor_key": LEGACY_ROTATION_CURSOR_KEY.format(
            chain=_safe_chain_key_component(chain)
        ),
        "durable_cadence_state_available": durable_cadence_state_available,
        "durable_cadence_claim_count": durable_cadence_claim_count,
        "durable_cadence_suppressed_count": durable_cadence_suppressed_count,
        "durable_cadence_release_failure_count": (
            durable_cadence_release_failure_count
        ),
        "durable_cadence_claim_ttl_max_seconds": (
            durable_cadence_claim_ttl_max_seconds
        ),
        "durable_cadence_claim_ttl_policy": (
            "CONFIGURED_SOURCE_CADENCE_PACED_BY_FAIR_CU_ADMISSION"
        ),
        "adaptive_cadence_scale_persisted_in_claim_ttl": False,
        "adaptive_overload_ratio_applied_to_in_memory_cadence": False,
        "paced_cu_admission_state_available": paced_cu_admission_state_available,
        "paced_cu_admission_claim_count": paced_cu_admission_claim_count,
        "paced_cu_admission_denied_count": paced_cu_admission_denied_count,
        "paced_cu_admission_release_count": paced_cu_admission_release_count,
        "paced_cu_admission_release_failure_count": (
            paced_cu_admission_release_failure_count
        ),
        "paced_cu_reservation_created_count": paced_cu_reservation_created_count,
        "paced_cu_reservation_finalize_count": (
            paced_cu_reservation_finalize_count
        ),
        "paced_cu_reservation_finalize_failure_count": (
            paced_cu_reservation_finalize_failure_count
        ),
        "paced_cu_reservation_tokens_exposed": False,
        "paced_cu_release_exact_once": True,
        "paced_cu_ambiguous_or_crashed_claim_remains_charged": True,
        "paced_cu_admission_window_id": paced_cu_admission_window_id,
        "paced_cu_admission_credit_balance_cu": (
            paced_cu_admission_credit_balance_cu
        ),
        "paced_cu_admission_window_prefix": _paced_cu_admission_window_prefix(
            chain
        ),
        "paced_cu_admission_window_shared_across_chains": True,
        "paced_cu_admission_scope": "PROVIDER_WIDE_DURABLE_EARNED_CREDIT",
        "paced_cu_admission_interval_mismatch_fails_closed": True,
        "cross_chain_paced_admission_activation_authorized": False,
        "paced_cu_admission_uses_redis_time": True,
        "paced_cu_admission_survives_process_restart": True,
        "scheduler_lease_state_available": scheduler_lease_state_available,
        "scheduler_lease_acquired": scheduler_lease_acquired,
        "scheduler_lease_released": scheduler_lease_released,
        "scheduler_run_suppressed_reason": scheduler_run_suppressed_reason,
        "actual_payload_results": sum(1 for row in results if row.get("actual_payload_present")),
        "does_not_poll_every_symbol_every_minute": True,
        "poll_job_order_policy": "TIER_FIRST_INTERLEAVED_ENDPOINTS_V1",
        "t0_wallet_endpoints_ordered_before_t1_backlog": True,
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
    wallet_tiers: Mapping[str, str] | None = None,
    scheduler_interval_seconds: float = 300.0,
) -> dict[str, Any]:
    authority = _budget_plan_view(budget_status)
    normalized_wallet_tiers = _normalized_wallet_tiers(wallet_tiers)
    observed_at = now_utc or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    observed_at = observed_at.astimezone(UTC)
    day_reset_at, month_reset_at = _utc_reset_boundaries(observed_at)
    seconds_until_day_reset, seconds_until_month_reset = _utc_reset_windows(
        observed_at
    )
    scheduler_interval = _normalized_scheduler_interval_seconds(
        scheduler_interval_seconds
    )
    day_admission_opportunities = _admission_opportunities(
        seconds_until_reset=seconds_until_day_reset,
        scheduler_interval_seconds=scheduler_interval,
    )
    month_admission_opportunities = _admission_opportunities(
        seconds_until_reset=seconds_until_month_reset,
        scheduler_interval_seconds=scheduler_interval,
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
                cadence_seconds=_cadence_seconds_for_target(
                    spec,
                    target_index=index,
                    target_tier=_wallet_target_tier(
                        wallet,
                        wallet_tiers=normalized_wallet_tiers,
                    ),
                ),
            )
            for index, (wallet, _token) in enumerate(targets)
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
    adaptive_overload_ratio = _adaptive_cadence_scale(
        configured_daily_cu=configured_daily_cu,
        configured_cycle_cu=estimated_cu,
        effective_daily_limit=current_window_daily_allowance,
        authority_available=bool(authority["budget_authority_available"]),
        provider_polling_blocked=provider_polling_blocked,
    )
    steady_state_overload_ratio = _adaptive_cadence_scale(
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
        base_cadences = [
            _cadence_seconds_for_target(
                spec,
                target_index=index,
                target_tier=_wallet_target_tier(
                    wallet,
                    wallet_tiers=normalized_wallet_tiers,
                ),
            )
            for index, (wallet, _token) in enumerate(targets)
        ]
        endpoint_daily_cu = (
            sum(
                _conservative_daily_cu(
                    cost=spec.cu_cost,
                    cadence_seconds=cadence_seconds,
                )
                for cadence_seconds in base_cadences
            )
            if adaptive_overload_ratio is not None
            else 0
        )
        estimated_daily_cu += endpoint_daily_cu
        steady_state_daily_cu = (
            sum(
                _conservative_daily_cu(
                    cost=spec.cu_cost,
                    cadence_seconds=cadence_seconds,
                )
                for cadence_seconds in base_cadences
            )
            if steady_state_overload_ratio is not None
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
                "effective_cadence_seconds_tier0": _base_cadence_or_none(
                    spec.cadence_seconds_tier0,
                    authority_available=adaptive_overload_ratio is not None,
                ),
                "effective_cadence_seconds_tier1": _base_cadence_or_none(
                    spec.cadence_seconds_tier1,
                    authority_available=adaptive_overload_ratio is not None,
                ),
                "effective_cadence_seconds_full_watchlist": _base_cadence_or_none(
                    spec.cadence_seconds_full_watchlist,
                    authority_available=adaptive_overload_ratio is not None,
                ),
                "compute_unit_cost": spec.cu_cost,
                "configured_target_count": spec_configured_target_count,
                "target_count": target_count,
                "identity_rejected_target_count": (
                    spec_configured_target_count - target_count
                ),
                "declared_wallet_tier_counts": {
                    tier: sum(
                        1
                        for wallet, _token in targets
                        if _wallet_target_tier(
                            wallet,
                            wallet_tiers=normalized_wallet_tiers,
                        )
                        == tier
                    )
                    for tier in ("T0", "T1", "T2")
                },
                "undeclared_wallet_tier_count": sum(
                    1
                    for wallet, _token in targets
                    if wallet is not None
                    and _wallet_target_tier(
                        wallet,
                        wallet_tiers=normalized_wallet_tiers,
                    )
                    is None
                ),
                "estimated_compute_units_per_cycle": endpoint_cu,
                "estimated_compute_units_per_day": endpoint_daily_cu,
                "estimated_compute_units_per_day_is_pre_aggregate_pacing": True,
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
    daily_paced_run_allowance = remaining_today // day_admission_opportunities
    monthly_paced_run_allowance = remaining_month // month_admission_opportunities
    daily_earned_cu_per_window = remaining_today / day_admission_opportunities
    monthly_earned_cu_per_window = (
        remaining_month / month_admission_opportunities
    )
    earned_cu_per_window = min(
        daily_earned_cu_per_window,
        monthly_earned_cu_per_window,
    )
    current_run_compute_unit_budget = (
        min(
            remaining_window_cu,
            estimated_cu,
            daily_paced_run_allowance,
            monthly_paced_run_allowance,
        )
        if not provider_polling_blocked
        else 0
    )
    pre_aggregate_pacing_estimated_daily_cu = estimated_daily_cu
    pre_aggregate_pacing_steady_state_daily_cu = steady_state_estimated_daily_cu
    estimated_daily_cu = min(estimated_daily_cu, current_window_daily_allowance)
    steady_state_estimated_daily_cu = min(
        steady_state_estimated_daily_cu,
        effective_daily_limit,
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
        "utc_day_reset_epoch_seconds": int(day_reset_at.timestamp()),
        "utc_month_reset_epoch_seconds": int(month_reset_at.timestamp()),
        "scheduler_interval_seconds": scheduler_interval,
        "daily_admission_opportunity_count": day_admission_opportunities,
        "monthly_admission_opportunity_count": month_admission_opportunities,
        "daily_paced_run_compute_unit_allowance": daily_paced_run_allowance,
        "monthly_paced_run_compute_unit_allowance": monthly_paced_run_allowance,
        "daily_earned_compute_units_per_window": daily_earned_cu_per_window,
        "monthly_earned_compute_units_per_window": monthly_earned_cu_per_window,
        "earned_compute_units_per_window": earned_cu_per_window,
        "unused_earned_compute_units_carry_forward": True,
        "earned_compute_unit_credit_durable": True,
        "earned_compute_unit_credit_resets_at_utc_day_or_month": True,
        "current_run_budget_policy": (
            "UTC_REMAINING_AUTHORITY_EARNED_CREDIT_CARRY_V2"
        ),
        "current_run_compute_unit_budget_is_floor_of_new_credit_earned": True,
        "current_run_compute_unit_budget_is_hard_spend_cap": False,
        "durable_credit_balance_is_dispatch_authority": True,
        "remaining_authority_frontload_allowed": False,
        "fixed_wallet_admission_count": None,
        "fixed_per_run_compute_unit_threshold": None,
        "current_window_daily_compute_unit_allowance": (
            current_window_daily_allowance
        ),
        "minimum_planned_request_compute_units": minimum_planned_request_cu,
        "current_run_compute_unit_budget": current_run_compute_unit_budget,
        "estimated_compute_units_per_cycle": estimated_cu,
        "configured_estimated_compute_units_per_day": configured_daily_cu,
        "pre_aggregate_pacing_estimated_compute_units_per_day": (
            pre_aggregate_pacing_estimated_daily_cu
        ),
        "pre_aggregate_pacing_steady_state_compute_units_per_day": (
            pre_aggregate_pacing_steady_state_daily_cu
        ),
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
        # Compatibility aliases: these are dimensionless overload telemetry,
        # never multipliers for the target's in-memory or durable cadence.
        "adaptive_cadence_scale": adaptive_overload_ratio,
        "steady_state_adaptive_cadence_scale": steady_state_overload_ratio,
        "adaptive_overload_ratio": adaptive_overload_ratio,
        "steady_state_adaptive_overload_ratio": steady_state_overload_ratio,
        "adaptive_overload_ratio_applied_to_target_cadence": False,
        "target_cadence_policy": "SOURCE_TIER_BASE_PLUS_DURABLE_FAIR_PACED_CU_V1",
        "aggregate_pacing_is_adaptive_to_remaining_utc_authority": True,
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


def _poll_job_priority_key(
    job: PollJob,
    *,
    wallet_tiers: Mapping[str, str],
) -> tuple[int, int]:
    _spec, target_index, wallet, _token = job
    if wallet is None:
        # Keep non-wallet bootstrap/identity work between the explicitly
        # urgent T0 observation tier and the larger T1/T2 candidate backlog.
        return (1, target_index)
    declared_tier = _wallet_target_tier(wallet, wallet_tiers=wallet_tiers)
    if declared_tier == "T0" or (declared_tier is None and target_index < 3):
        return (0, target_index)
    if declared_tier == "T1" or (declared_tier is None and target_index < 10):
        return (2, target_index)
    return (3, target_index)


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
    next_day, next_month = _utc_reset_boundaries(now)
    return (
        max(1, int(math.ceil((next_day - now).total_seconds()))),
        max(1, int(math.ceil((next_month - now).total_seconds()))),
    )


def _utc_reset_boundaries(observed_at: datetime) -> tuple[datetime, datetime]:
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
    return next_day, next_month


def _remaining_daily_equivalent(remaining_cu: int, seconds_to_reset: int) -> int:
    if remaining_cu <= 0 or seconds_to_reset <= 0:
        return 0
    return max(0, int((int(remaining_cu) * 86_400) // int(seconds_to_reset)))


def _normalized_scheduler_interval_seconds(value: object) -> int:
    if isinstance(value, bool):
        return 300
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 300
    if not math.isfinite(parsed) or parsed <= 0.0:
        return 300
    return max(1, int(math.ceil(parsed)))


def _admission_opportunities(
    *,
    seconds_until_reset: int,
    scheduler_interval_seconds: int,
) -> int:
    seconds = max(1, int(seconds_until_reset))
    interval = max(1, int(scheduler_interval_seconds))
    return max(1, int(math.ceil(seconds / interval)))


def _adaptive_cadence_scale(
    *,
    configured_daily_cu: int,
    configured_cycle_cu: int,
    effective_daily_limit: int,
    authority_available: bool,
    provider_polling_blocked: bool,
) -> float | None:
    del configured_cycle_cu
    if (
        not authority_available
        or provider_polling_blocked
        or effective_daily_limit <= 0
    ):
        return None
    if configured_daily_cu <= 0:
        return 1.0
    return max(1.0, configured_daily_cu / effective_daily_limit)


def _base_cadence_or_none(
    cadence_seconds: int,
    *,
    authority_available: bool,
) -> int | None:
    if not authority_available:
        return None
    return max(1, int(cadence_seconds))


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


def _claim_paced_compute_units(
    redis_client: Any | None,
    *,
    chain: str,
    lease_token: str | None,
    scheduler_interval_seconds: int,
    cost_cu: int,
    remaining_today_cu: int,
    remaining_month_cu: int,
    daily_admission_opportunities: int,
    monthly_admission_opportunities: int,
    utc_day_reset_epoch_seconds: int,
    utc_month_reset_epoch_seconds: int,
) -> tuple[bool, bool, float, int | None, str | None]:
    if redis_client is None or not lease_token:
        return False, False, 0.0, None, None
    interval = max(1, int(scheduler_interval_seconds))
    cost = max(0, int(cost_cu))
    remaining_today = max(0, int(remaining_today_cu))
    remaining_month = max(0, int(remaining_month_cu))
    day_opportunities = max(1, int(daily_admission_opportunities))
    month_opportunities = max(1, int(monthly_admission_opportunities))
    day_reset_epoch = max(1, int(utc_day_reset_epoch_seconds))
    month_reset_epoch = max(1, int(utc_month_reset_epoch_seconds))
    if cost <= 0 or remaining_today <= 0 or remaining_month <= 0:
        return False, True, 0.0, None, None
    reservation_id = uuid.uuid4().hex
    reservation_key = _paced_cu_reservation_key(reservation_id)
    try:
        raw = redis_client.eval(
            _FENCED_PACED_CU_CLAIM_SCRIPT,
            3,
            _scheduler_lease_key(chain),
            _paced_cu_admission_window_prefix(chain),
            reservation_key,
            lease_token,
            interval,
            cost,
            remaining_today,
            remaining_month,
            day_opportunities,
            month_opportunities,
            day_reset_epoch,
            month_reset_epoch,
            reservation_id,
        )
    except Exception:
        return False, False, 0.0, None, None
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        return False, False, 0.0, None, None
    try:
        decision = int(raw[0])
        credit_balance = max(0.0, float(raw[1]))
        window_id = int(raw[2])
        returned_reservation_id = _decode_redis_text(raw[3])
    except (TypeError, ValueError, OverflowError):
        return False, False, 0.0, None, None
    if decision < 0:
        return False, False, credit_balance, window_id, None
    if decision == 1:
        if returned_reservation_id != reservation_id:
            # Debit may already be durable; an untrusted/malformed receipt can
            # never authorize a synthesized refund.  Leave it charged.
            return False, False, credit_balance, window_id, None
        return True, True, credit_balance, window_id, reservation_id
    if returned_reservation_id:
        return False, False, credit_balance, window_id, None
    return False, True, credit_balance, window_id, None


def _release_paced_compute_units(
    redis_client: Any | None,
    *,
    chain: str,
    lease_token: str | None,
    window_id: int | None,
    cost_cu: int,
    reservation_id: str | None,
) -> bool:
    if (
        redis_client is None
        or not lease_token
        or window_id is None
        or reservation_id is None
    ):
        return False
    try:
        reservation_key = _paced_cu_reservation_key(reservation_id)
    except ValueError:
        return False
    try:
        return bool(
            redis_client.eval(
                _FENCED_PACED_CU_RELEASE_SCRIPT,
                3,
                _scheduler_lease_key(chain),
                _paced_cu_admission_window_prefix(chain),
                reservation_key,
                lease_token,
                reservation_id,
                int(window_id),
                max(0, int(cost_cu)),
            )
        )
    except Exception:
        return False


def _finalize_paced_compute_units(
    redis_client: Any | None,
    *,
    chain: str,
    lease_token: str | None,
    window_id: int | None,
    cost_cu: int,
    reservation_id: str | None,
) -> bool:
    if (
        redis_client is None
        or not lease_token
        or window_id is None
        or reservation_id is None
    ):
        return False
    try:
        reservation_key = _paced_cu_reservation_key(reservation_id)
    except ValueError:
        return False
    try:
        return bool(
            redis_client.eval(
                _FENCED_PACED_CU_FINALIZE_SCRIPT,
                3,
                _scheduler_lease_key(chain),
                _paced_cu_admission_window_prefix(chain),
                reservation_key,
                lease_token,
                reservation_id,
                int(window_id),
                max(0, int(cost_cu)),
            )
        )
    except Exception:
        return False


def _paced_cu_reservation_key(reservation_id: str) -> str:
    raw = str(reservation_id or "").strip()
    try:
        normalized = uuid.UUID(hex=raw).hex
    except (AttributeError, ValueError) as exc:
        raise ValueError("PACED_CU_RESERVATION_ID_INVALID") from exc
    if normalized != raw:
        raise ValueError("PACED_CU_RESERVATION_ID_INVALID")
    return f"{PACED_CU_RESERVATION_KEY_PREFIX}:{normalized}"


def _decode_redis_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value or "")


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


def _paced_cu_admission_window_prefix(chain: str) -> str:
    del chain
    return PACED_CU_ADMISSION_WINDOW_PREFIX


def _safe_chain_key_component(chain: str) -> str:
    normalized_chain = _norm_chain(chain)
    return normalized_chain if normalized_chain in MORALIS_EVM_CHAIN_PARAMS else "invalid"


def _rotate_poll_jobs(
    redis_client: Any | None,
    *,
    chain: str,
    jobs: list[PollJob],
    context_symbol: str,
) -> tuple[list[PollJob], bool, str]:
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
    universe_digest = _rotation_universe_digest(chain=chain, job_ids=job_ids)
    if redis_client is None:
        return jobs, False, universe_digest
    cursor_key = _rotation_cursor_key(chain)
    try:
        raw_cursor = redis_client.get(cursor_key)
    except Exception:
        return jobs, False, universe_digest
    if raw_cursor is None or not jobs:
        return jobs, True, universe_digest
    if isinstance(raw_cursor, bytes):
        raw_cursor = raw_cursor.decode("utf-8", errors="replace")
    encoded_cursor = str(raw_cursor)
    expected_prefix = f"{universe_digest}:"
    if not encoded_cursor.startswith(expected_prefix):
        # A material target-set/order change starts deterministically at the
        # new tier-first head.  It must never inherit a semantically stale
        # position that can postpone T0 behind a multi-day legacy cycle.
        return jobs, True, universe_digest
    cursor = encoded_cursor[len(expected_prefix) :]
    try:
        start = (job_ids.index(cursor) + 1) % len(jobs)
    except ValueError:
        start = 0
    return [*jobs[start:], *jobs[:start]], True, universe_digest


def _write_rotation_cursor(
    redis_client: Any | None,
    *,
    chain: str,
    job_id: str,
    rotation_universe_digest: str,
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
                f"{rotation_universe_digest}:{job_id}",
            )
        )
    except Exception:
        return False


def _rotation_cursor_key(chain: str) -> str:
    return ROTATION_CURSOR_KEY.format(chain=_safe_chain_key_component(chain))


def _rotation_universe_digest(*, chain: str, job_ids: list[str]) -> str:
    payload = {
        "schema_version": "moralis_rotation_universe_v2",
        "order_policy": ROTATION_ORDER_POLICY,
        "chain": _safe_chain_key_component(chain),
        "ordered_job_ids": job_ids,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _ensure_bootstrap_state(redis_client: Any | None) -> dict[str, Any]:
    """Restore local Redis bootstrap state from reviewed repository sources.

    Redis is a cache, while the token map and wallet-watchlist authorities are
    reviewed repository files.  If Redis loses those keys, the provider loop can
    keep running with API auth READY but no feature path.  This recovery never
    calls Moralis, never changes CU ledger state, and never grants trainer
    authority; it only republishes the prerequisite local control-plane rows.
    """

    status = {
        "schema_version": "moralis_bootstrap_recovery_v1",
        "token_map_recovery_attempted": False,
        "token_map_recovery_succeeded": False,
        "wallet_watchlist_recovery_attempted": False,
        "wallet_watchlist_recovery_succeeded": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }
    if redis_client is None:
        status["status"] = "REDIS_UNAVAILABLE"
        return status
    try:
        if _token_map_count(redis_client) <= 0:
            status["token_map_recovery_attempted"] = True
            token_status = publish_token_map(redis_client)
            status["token_map_recovery_succeeded"] = (
                int(token_status.get("token_map_count") or 0) > 0
            )
            status["token_map_count"] = int(token_status.get("token_map_count") or 0)
    except Exception as exc:
        status["token_map_recovery_error"] = type(exc).__name__
    try:
        if not read_wallet_watchlist(redis_client):
            status["wallet_watchlist_recovery_attempted"] = True
            watch_status = refresh_candidate_wallet_watchlist(redis_client)
            status["wallet_watchlist_recovery_succeeded"] = (
                bool(watch_status.get("refresh_succeeded") is True)
                and int(watch_status.get("wallet_watchlist_count") or 0) > 0
            )
            status["wallet_watchlist_count"] = int(
                watch_status.get("wallet_watchlist_count") or 0
            )
    except Exception as exc:
        status["wallet_watchlist_recovery_error"] = type(exc).__name__
    status["status"] = (
        "RECOVERY_APPLIED"
        if status["token_map_recovery_succeeded"]
        or status["wallet_watchlist_recovery_succeeded"]
        else "NO_RECOVERY_NEEDED_OR_FAILED"
    )
    return status


def _validate_cached_metadata(redis_client: Any | None) -> dict[str, Any]:
    """Promote token-map rows only from already cached canonical metadata."""

    if redis_client is None:
        return {"status": "REDIS_UNAVAILABLE"}
    try:
        report = validate_token_map(redis_client)
    except Exception as exc:
        return {
            "status": "CACHE_METADATA_VALIDATION_FAILED",
            "error_class": type(exc).__name__,
        }
    return {
        "status": "CACHE_METADATA_VALIDATION_ATTEMPTED",
        "verified_count": int(report.get("verified_count") or 0),
        "pollable_count": int(report.get("pollable_count") or 0),
        "mismatch_count": int(report.get("mismatch_count") or 0),
        "unsupported_count": int(report.get("unsupported_count") or 0),
        "metadata_cache_pending_count": int(report.get("cache_pending_count") or 0),
    }


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
    candidate_wallet_rows = read_wallet_watchlist(redis_client)
    scoped_candidate_wallet_rows = [
        row
        for row in candidate_wallet_rows
        if _norm_chain(row.get("chain")) == _norm_chain(chain)
    ]
    if not wallets:
        wallets = [row["address"] for row in scoped_candidate_wallet_rows]
    wallet_tiers = (
        {
            str(row["address"]).strip().lower(): str(row.get("tier") or "").upper()
            for row in scoped_candidate_wallet_rows
        }
        if not explicit_wallets
        else {}
    )
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
    wallet_count = len(candidate_wallet_rows)
    active_candidate_chain = _norm_chain(chain)
    candidate_wallet_chain_counts: dict[str, int] = {}
    for row in candidate_wallet_rows:
        row_chain = _norm_chain(row.get("chain"))
        candidate_wallet_chain_counts[row_chain] = (
            candidate_wallet_chain_counts.get(row_chain, 0) + 1
        )
    queued_candidate_wallet_chain_counts = {
        row_chain: count
        for row_chain, count in sorted(candidate_wallet_chain_counts.items())
        if row_chain != active_candidate_chain and count > 0
    }
    queued_candidate_wallet_count = sum(
        queued_candidate_wallet_chain_counts.values()
    )
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
        "candidate_wallet_count": wallet_count,
        "chain_candidate_wallet_count": len(scoped_candidate_wallet_rows),
        "candidate_wallet_chain_counts": dict(
            sorted(candidate_wallet_chain_counts.items())
        ),
        "active_candidate_chain": active_candidate_chain,
        "active_candidate_wallet_count": len(scoped_candidate_wallet_rows),
        "queued_candidate_wallet_count": queued_candidate_wallet_count,
        "queued_candidate_wallet_chain_counts": (
            queued_candidate_wallet_chain_counts
        ),
        "wallet_tiers": _normalized_wallet_tiers(wallet_tiers),
        "verified_smart_wallet_count": 0,
        "wallet_watchlist_semantics": "CANDIDATE_OBSERVATION_TARGETS_ONLY",
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
        "status_scope": "PROVIDER_CONFIGURATION_HEALTH",
        "generated_utc": _now(),
        "chain": chain,
        "wallet_count": 0,
        "token_count": 0,
        "token_map_count": bootstrap.get("token_map_count", 0),
        "wallet_watchlist_count": bootstrap.get("wallet_watchlist_count", 0),
        "candidate_wallet_count": bootstrap.get("candidate_wallet_count", 0),
        "chain_candidate_wallet_count": bootstrap.get("chain_candidate_wallet_count", 0),
        "candidate_wallet_chain_counts": bootstrap.get(
            "candidate_wallet_chain_counts", {}
        ),
        "active_candidate_chain": bootstrap.get("active_candidate_chain"),
        "active_candidate_wallet_count": bootstrap.get(
            "active_candidate_wallet_count", 0
        ),
        "queued_candidate_wallet_count": bootstrap.get(
            "queued_candidate_wallet_count", 0
        ),
        "queued_candidate_wallet_chain_counts": bootstrap.get(
            "queued_candidate_wallet_chain_counts", {}
        ),
        "queued_candidate_wallet_polling_status": (
            "QUEUED_NOT_POLLED_BY_THIS_CHAIN_LOOP"
            if int(bootstrap.get("queued_candidate_wallet_count") or 0) > 0
            else "NO_QUEUED_CANDIDATES"
        ),
        "candidate_chain_activation_policy": (
            "SINGLE_RUNTIME_CHAIN_FAIR_PACED_CU_SCOPE_V1"
        ),
        "cross_chain_runtime_services_started_by_this_change": 0,
        "all_candidate_chains_runtime_active": (
            int(bootstrap.get("queued_candidate_wallet_count") or 0) == 0
        ),
        "verified_smart_wallet_count": 0,
        "wallet_watchlist_semantics": "CANDIDATE_OBSERVATION_TARGETS_ONLY",
        "watchlist_refresh_action": (
            bootstrap["watchlist_refresh"].get("refresh_action")
            if isinstance(bootstrap.get("watchlist_refresh"), Mapping)
            else "NOT_REQUESTED"
        ),
        "watchlist_refresh_succeeded": (
            bootstrap["watchlist_refresh"].get("refresh_succeeded") is True
            if isinstance(bootstrap.get("watchlist_refresh"), Mapping)
            else None
        ),
        "watchlist_refresh_compute_units_reserved": (
            int(bootstrap["watchlist_refresh"].get("compute_units_reserved") or 0)
            if isinstance(bootstrap.get("watchlist_refresh"), Mapping)
            else 0
        ),
        "watchlist_refresh_moralis_request_count": (
            int(bootstrap["watchlist_refresh"].get("moralis_request_count") or 0)
            if isinstance(bootstrap.get("watchlist_refresh"), Mapping)
            else 0
        ),
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


def _normalized_wallet_tiers(
    wallet_tiers: Mapping[str, str] | None,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_address, raw_tier in dict(wallet_tiers or {}).items():
        address = str(raw_address or "").strip().lower()
        tier = str(raw_tier or "").strip().upper()
        if address and tier in {"T0", "T1", "T2"}:
            normalized[address] = tier
    return normalized


def _wallet_target_tier(
    wallet: object | None,
    *,
    wallet_tiers: Mapping[str, str],
) -> str | None:
    if wallet is None:
        return None
    return wallet_tiers.get(str(wallet).strip().lower())


def _cadence_seconds_for_target(
    spec: MoralisEndpointSpec,
    *,
    target_index: int,
    target_tier: str | None = None,
) -> int:
    if target_tier == "T0":
        return int(spec.cadence_seconds_tier0)
    if target_tier == "T1":
        return int(spec.cadence_seconds_tier1)
    if target_tier == "T2":
        return int(spec.cadence_seconds_full_watchlist)
    if target_index < 3:
        return int(spec.cadence_seconds_tier0)
    if target_index < 10:
        return int(spec.cadence_seconds_tier1)
    return int(spec.cadence_seconds_full_watchlist)


def _redis_client(redis_url: str) -> Any:
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _precise_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
