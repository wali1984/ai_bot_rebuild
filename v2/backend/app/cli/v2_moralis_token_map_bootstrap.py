"""Bootstrap Moralis token map, exclusions, and wallet-watchlist status.

This command is read-only toward Moralis. It writes Redis/bootstrap artifacts
only and never prints API keys.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.smart_money_wallets.address_classifier import publish_excluded_addresses
from app.services.smart_money_wallets.health import build_moralis_health
from app.services.smart_money_wallets.smart_wallet_scorer import SMART_WALLET_CANDIDATES_KEY
from app.services.smart_money_wallets.streams_registry import build_streams_registry
from app.services.smart_money_wallets.token_contract_mapper import publish_token_map
from app.services.smart_money_wallets.wallet_watchlist import publish_wallet_watchlist


PHASE0_FILENAME = "phase0_moralis_current_state.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_moralis_token_map_bootstrap")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--symbols", default=os.environ.get("MORALIS_BOOTSTRAP_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,PYTHUSDT,1000FLOKIUSDT,JSTUSDT,AUCTIONUSDT"))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--phase0-output", default="")
    args = parser.parse_args(argv)
    redis_client = _redis_client(args.redis_url)
    phase0 = build_phase0_state(redis_client, env=os.environ)
    phase0_path = _write_phase0(args.phase0_output, args.output_dir, phase0)
    token_map = publish_token_map(redis_client, symbols=_csv(args.symbols, upper=True))
    exclusions = publish_excluded_addresses(redis_client)
    watchlist = publish_wallet_watchlist(redis_client)
    symbols = _csv(args.symbols, upper=True)
    streams = build_streams_registry(redis_client, env=os.environ, symbol=symbols[0] if symbols else None)
    summary = {
        "schema_version": "moralis_bootstrap_summary_v1",
        "status": "CONFIGURED_NO_WATCHLIST" if watchlist["wallet_watchlist_count"] == 0 else "WATCHLIST_BUILDING",
        "generated_utc": _now(),
        "phase0_output": str(phase0_path) if phase0_path else None,
        "token_map": token_map,
        "exclusions": {
            "excluded_count": exclusions.get("excluded_count"),
            "exchange_wallet_count": exclusions.get("exchange_wallet_count"),
        },
        "watchlist": watchlist,
        "streams": streams,
        "moralis_green_from_api_key": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


def build_phase0_state(redis_client: Any | None, *, env: dict[str, str]) -> dict[str, Any]:
    health = _read_json(redis_client, "v2:provider:moralis:health") if redis_client is not None else None
    if not isinstance(health, dict):
        health = build_moralis_health(env)
    streams = build_streams_registry(
        redis_client,
        env=env,
        symbol=str(env.get("MORALIS_SYMBOL") or "BTCUSDT").upper(),
    )
    return {
        "schema_version": "phase0_moralis_current_state_v1",
        "generated_utc": _now(),
        "moralis_api_key_present": bool(str(env.get("MORALIS_API_KEY") or env.get("MORALIS_WEB3_API_KEY") or "").strip()),
        "moralis_subscription_status": health.get("subscription_status") or health.get("status"),
        "moralis_health_key_exists": _exists(redis_client, "v2:provider:moralis:health"),
        "moralis_token_map_count": _count(redis_client, "v2:moralis:token_map_status", "token_map_count"),
        "moralis_wallet_watchlist_count": _count(redis_client, "v2:moralis:wallet_watchlist_status", "wallet_watchlist_count"),
        "moralis_smart_wallet_candidate_count": _count(redis_client, SMART_WALLET_CANDIDATES_KEY, "candidate_count"),
        "moralis_stream_configured": streams.get("streams_configured") is True,
        "moralis_actual_payload_count_1h": int(health.get("actual_payload_count_1h") or 0),
        "dashboard_color": health.get("dashboard_color") or "GRAY",
        "core_system_blocked": bool(health.get("core_system_blocked") is True),
        "raw_key_exposed": False,
    }


def _write_phase0(phase0_output: str, output_dir: str, payload: dict[str, Any]) -> Path | None:
    if phase0_output:
        path = Path(phase0_output)
    elif output_dir:
        path = Path(output_dir) / PHASE0_FILENAME
    else:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _read_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _exists(redis_client: Any | None, key: str) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(redis_client.exists(key))
    except Exception:
        return False


def _count(redis_client: Any | None, key: str, field: str) -> int:
    payload = _read_json(redis_client, key) if redis_client is not None else None
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def _csv(raw: str, *, upper: bool = False) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return [value.upper() for value in values] if upper else values


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
