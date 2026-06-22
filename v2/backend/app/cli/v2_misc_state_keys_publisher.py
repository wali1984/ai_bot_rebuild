"""Publish V2 replacements for legacy misc/state Redis keys.

Legacy row covered:

- ``config:symbols`` -> ``v2:symbol_universe:contract``
- ``market:state`` -> ``v2:market:state``
- ``market:{SYMBOL}`` -> ``v2:market:state:{symbol}``

This worker reads and writes only ``v2:`` Redis keys, never calls exchange
endpoints, never imports exchange SDKs, and cannot enable live/canary.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_misc_state_keys/latest/v2_misc_state_keys_status.json"
)
V2_REDIS_PREFIX = "v2:"
LIVE_GATE = "blocked_human_only"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        factory = getattr(redis, "Redis")
        client = factory(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _get_json(redis_client: Any, key: str) -> Any | None:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _set_json(redis_client: Any, key: str, payload: Any, *, ex: int = 600) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    setter = getattr(redis_client, "set")
    setter(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
    return True


def _extract_price(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    ticker = payload.get("ticker_24hr")
    if isinstance(ticker, dict):
        value = ticker.get("lastPrice") or ticker.get("last")
    else:
        value = payload.get("price") or payload.get("last")
    try:
        return float(value)
    except Exception:
        return None


def _symbol_state(redis_client: Any, symbol: str) -> dict[str, Any]:
    price_payload = _get_json(redis_client, f"v2:market:prices:{symbol}")
    funding_payload = _get_json(redis_client, f"v2:market:funding:{symbol}")
    oi_payload = _get_json(redis_client, f"v2:market:open_interest:{symbol}")
    kucoin_payload = _get_json(redis_client, f"v2:market:kucoin:latest:{symbol}")
    sources = []
    if price_payload is not None:
        sources.append("v2:market:prices")
    if funding_payload is not None:
        sources.append("v2:market:funding")
    if oi_payload is not None:
        sources.append("v2:market:open_interest")
    if kucoin_payload is not None:
        sources.append("v2:market:kucoin")
    return {
        "symbol": symbol,
        "price": _extract_price(price_payload) or _extract_price(kucoin_payload),
        "has_price": price_payload is not None or kucoin_payload is not None,
        "has_funding": funding_payload is not None,
        "has_open_interest": oi_payload is not None,
        "has_kucoin_backup": kucoin_payload is not None,
        "source_key_families": sources,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
    }


def build_payload(
    *,
    symbols: list[str],
    redis_client: Any,
    write_v2_redis: bool,
    ttl_seconds: int,
) -> dict[str, Any]:
    generated_utc = _utc_iso()
    per_symbol = [_symbol_state(redis_client, symbol) for symbol in symbols]
    symbol_contract = {
        "schema_version": "v2_symbol_universe_contract_v1",
        "generated_utc": generated_utc,
        "source": "v2_misc_state_keys_publisher",
        "legacy_replacement_for": "config:symbols",
        "symbols": symbols,
        "symbol_count": len(symbols),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "trade_all_symbols_automatically": False,
    }
    market_state = {
        "schema_version": "v2_market_state_v1",
        "generated_utc": generated_utc,
        "source": "v2_misc_state_keys_publisher",
        "legacy_replacement_for": "market:state",
        "symbol_count": len(symbols),
        "symbols_with_price": sum(1 for row in per_symbol if row["has_price"]),
        "symbols_with_funding": sum(1 for row in per_symbol if row["has_funding"]),
        "symbols_with_open_interest": sum(1 for row in per_symbol if row["has_open_interest"]),
        "symbols_with_kucoin_backup": sum(1 for row in per_symbol if row["has_kucoin_backup"]),
        "symbols": symbols,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
    }
    keys_written: list[str] = []
    redis_ok = redis_client is not None
    if write_v2_redis:
        if _set_json(redis_client, "v2:symbol_universe:contract", symbol_contract, ex=ttl_seconds):
            keys_written.append("v2:symbol_universe:contract")
        if _set_json(redis_client, "v2:market:state", market_state, ex=ttl_seconds):
            keys_written.append("v2:market:state")
        for row in per_symbol:
            key = f"v2:market:state:{row['symbol']}"
            if _set_json(redis_client, key, row, ex=ttl_seconds):
                keys_written.append(key)
    return {
        "schema_version": "v2_misc_state_keys_status_v1",
        "generated_utc": generated_utc,
        "worker_id": "v2_misc_state_keys_publisher",
        "classification": "V2_MISC_STATE_KEYS_PUBLISHED" if keys_written else "V2_MISC_STATE_KEYS_DRY_RUN",
        "symbol_universe_contract": symbol_contract,
        "market_state": market_state,
        "per_symbol_state_sample": per_symbol[:10],
        "redis_ok": redis_ok,
        "write_v2_redis": bool(write_v2_redis),
        "v2_keys_written": keys_written,
        "v2_keys_written_count": len(keys_written),
        "writes_legacy_redis": False,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_misc_state_keys_publisher")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=600)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--out", type=Path, default=PUBLIC_STATUS_PATH)
    args = parser.parse_args(argv)

    symbols = resolve_symbols(
        explicit=args.symbols,
        smoke_test=bool(args.smoke_test),
        include_baseline=True,
    )
    redis_client = _connect_redis()
    payload = build_payload(
        symbols=symbols,
        redis_client=redis_client,
        write_v2_redis=bool(args.write_v2_redis),
        ttl_seconds=max(60, int(args.v2_redis_ttl_seconds)),
    )
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.write_evidence:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    sys.stdout.write(
        json.dumps(
            {
                "classification": payload["classification"],
                "v2_keys_written_count": payload["v2_keys_written_count"],
                "redis_ok": payload["redis_ok"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if payload["redis_ok"] or not args.write_v2_redis else 1


if __name__ == "__main__":
    raise SystemExit(main())
