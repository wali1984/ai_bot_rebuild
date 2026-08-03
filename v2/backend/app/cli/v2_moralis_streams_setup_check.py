"""Publish Moralis Streams setup readiness without creating streams."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from app.services.smart_money_wallets.streams_registry import publish_streams_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_streams_setup_check")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--symbol", default=os.environ.get("MORALIS_SYMBOL", "BTCUSDT"))
    args = parser.parse_args(argv)
    redis_client = _redis_client(args.redis_url)
    payload = publish_streams_registry(redis_client, env=os.environ, symbol=args.symbol.upper())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


if __name__ == "__main__":
    raise SystemExit(main())
