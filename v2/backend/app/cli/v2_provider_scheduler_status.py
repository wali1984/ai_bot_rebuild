"""Provider scheduler status without making provider network calls."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from app.cli.v2_coinglass_provider_loop import coinglass_scheduler_plan
from app.cli.v2_moralis_provider_loop import moralis_scheduler_plan
from app.services.coinglass_provider.endpoint_registry import registry_payload as coinglass_registry
from app.services.provider_features import endpoint_to_feature_mapping, provider_redis_key_contract
from app.services.smart_money_wallets.endpoint_registry import registry_payload as moralis_registry


STATUS_KEY = "v2:provider:scheduler_status"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_provider_scheduler_status")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    parser.add_argument("--symbols", default=os.environ.get("COINGLASS_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"))
    parser.add_argument("--wallets", default=os.environ.get("MORALIS_WALLETS", ""))
    parser.add_argument("--tokens", default=os.environ.get("MORALIS_TOKENS", ""))
    args = parser.parse_args(argv)
    status = build_status(
        symbols=_csv(args.symbols, upper=True),
        wallets=_csv(args.wallets),
        tokens=_csv(args.tokens),
    )
    if args.redis_url:
        r = _redis_client(args.redis_url)
        r.set(STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=300)
    print(json.dumps(status, indent=2, sort_keys=True, default=str))
    return 0


def build_status(*, symbols: list[str], wallets: list[str], tokens: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "provider_scheduler_status_v1",
        "status": "PROVIDER_SCHEDULER_RATE_LIMIT_CONTRACT_ACTIVE",
        "generated_utc": _now(),
        "coinglass_registry": coinglass_registry(),
        "moralis_registry": moralis_registry(),
        "coinglass_schedule_plan": coinglass_scheduler_plan(symbols),
        "moralis_schedule_plan": moralis_scheduler_plan(wallets=wallets, tokens=tokens),
        "redis_key_contract": provider_redis_key_contract(),
        "endpoint_to_feature_mapping": endpoint_to_feature_mapping(),
        "do_not_only_publish_health_keys": True,
        "heartbeat_only_green_allowed": False,
        "moralis_every_symbol_every_minute_allowed": False,
        "coinglass_public_limit_exceeded": False,
        "raw_key_exposed": False,
        "optional_provider_failures_core_blocking": False,
    }


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _csv(raw: str, *, upper: bool = False) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return [value.upper() for value in values] if upper else values


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
