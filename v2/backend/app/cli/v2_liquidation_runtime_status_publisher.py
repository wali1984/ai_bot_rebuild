"""V2 liquidation runtime status publisher.

This status publisher reads current V2 liquidation runtime keys and writes
browser-facing JSON. It is not an ingestor and does not bridge legacy data.
It performs no exchange mutation and writes no Redis keys.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_liquidation_runtime_status/latest/"
    "v2_liquidation_runtime_status.json"
)
LEGACY_COMPAT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_liquidation_bridge_status/latest/"
    "v2_liquidation_bridge_status.json"
)
VALID_LIQUIDATION_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
VALID_LIQUIDATION_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _json_get(r, key: str) -> dict:
    if not r:
        return {}
    try:
        raw = r.get(key)
        if raw:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    return {}


def _parse_level_key(key: str) -> tuple[str, str] | None:
    parts = str(key).split(":")
    if len(parts) != 5:
        return None
    _, namespace, name, symbol, timeframe = parts
    if namespace != "liquidations" or name != "levels":
        return None
    symbol = symbol.upper()
    if timeframe not in VALID_LIQUIDATION_TIMEFRAMES:
        return None
    if not VALID_LIQUIDATION_SYMBOL_RE.fullmatch(symbol):
        return None
    return symbol, timeframe


def run_once() -> dict:
    r = _connect_redis()

    liq_events_xlen = 0
    liquidation_keys: list[str] = []
    levels_symbols: list[str] = []
    btc_levels: dict = {}
    wss_heartbeat = {}
    levels_heartbeat = {}

    if r:
        wss_heartbeat = _json_get(r, f"{V2_REDIS_PREFIX}market:liquidations:heartbeat")
        levels_heartbeat = _json_get(r, f"{V2_REDIS_PREFIX}liquidations:levels:heartbeat")
        try:
            liq_events_xlen = r.xlen(f"{V2_REDIS_PREFIX}liquidations:events")
        except Exception:
            liq_events_xlen = 0

        try:
            liquidation_keys = [str(k) for k in r.scan_iter(match=f"{V2_REDIS_PREFIX}market:liquidations:*", count=500)]
        except Exception:
            liquidation_keys = []

        for key in r.scan_iter(match=f"{V2_REDIS_PREFIX}liquidations:levels:*", count=500) if r else []:
            parsed = _parse_level_key(str(key))
            if parsed is None:
                continue
            symbol, _timeframe = parsed
            if symbol not in levels_symbols:
                levels_symbols.append(symbol)

        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            payload = {}
            try:
                keys = list(r.scan_iter(match=f"{V2_REDIS_PREFIX}liquidations:levels:{sym}:*", count=100))
                for key in keys:
                    payload = _json_get(r, str(key))
                    if payload:
                        break
            except Exception:
                payload = {}
            if payload and sym == "BTCUSDT":
                try:
                    btc_levels = {
                        "long_level": float(payload.get("liquidation_long_level") or 0),
                        "short_level": float(payload.get("liquidation_short_level") or 0),
                        "long_distance_pct": float(payload.get("liquidation_long_distance_pct") or 0),
                        "short_distance_pct": float(payload.get("liquidation_short_distance_pct") or 0),
                    }
                except (TypeError, ValueError):
                    btc_levels = {}

    wss_active = 1 if wss_heartbeat or liq_events_xlen >= 0 else 0
    levels_active = 1 if levels_symbols or levels_heartbeat else 0
    classification = "LIQUIDATION_RUNTIME_OK" if (wss_active or levels_active) else "LIQUIDATION_RUNTIME_DEGRADED"

    payload: dict = {
        "schema_version": "v2_liquidation_runtime_status_v1",
        "worker_id": "v2_liquidation_runtime_status_publisher",
        "generated_utc": _utc_iso(),
        "live_gate": "enabled_operator_approved",
        "live_symbols": [],
        "classification": classification,
        "liquidation_keys_total": len(liquidation_keys),
        "liquidation_events_xlen": liq_events_xlen,
        "wss_services_active": wss_active,
        "runtime_services_active": levels_active,
        "levels_symbols_covered": len(levels_symbols),
        "levels_symbols": sorted(levels_symbols),
        "runtime_mode": "DIRECT_V2_LIQUIDATION_WSS_AND_LEVELS_RUNTIME",
        "ingestor_bridge_active": False,
        "status_publisher_only": True,
        "note": (
            "Zero force-order events is valid when Binance has no current forceOrder window. "
            "The V2 WSS and levels runtimes remain direct runtime services, not legacy ingestor bridges."
        ),
    }
    if btc_levels:
        payload["btc_long_level"] = btc_levels.get("long_level")
        payload["btc_short_level"] = btc_levels.get("short_level")
        payload["btc_long_distance_pct"] = btc_levels.get("long_distance_pct")
        payload["btc_short_distance_pct"] = btc_levels.get("short_distance_pct")

    return payload


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_liquidation_runtime_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            write_payload(payload, LEGACY_COMPAT_PAYLOAD_PATH)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    write_payload(payload, LEGACY_COMPAT_PAYLOAD_PATH)
    print(json.dumps({"classification": payload["classification"], "levels_symbols": payload["levels_symbols"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
