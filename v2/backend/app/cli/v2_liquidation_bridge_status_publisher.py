"""V2 liquidation bridge status publisher — reads live liquidation Redis keys
and unified_features liquidation fields, writes a public JSON payload.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_liquidation_bridge_status/latest/v2_liquidation_bridge_status.json"
)


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


def run_once() -> dict:
    r = _connect_redis()

    liq_events_xlen = 0
    liquidation_keys: list[str] = []
    levels_symbols: list[str] = []
    btc_levels: dict = {}

    if r:
        try:
            liq_events_xlen = r.xlen(f"{V2_REDIS_PREFIX}liquidations:events")
        except Exception:
            liq_events_xlen = 0

        try:
            liquidation_keys = r.keys(f"{V2_REDIS_PREFIX}market:liquidations:*")
        except Exception:
            liquidation_keys = []

        # Read liquidation levels from unified_features hash for BTC
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            key = f"{V2_REDIS_PREFIX}unified_features:{sym}:1m"
            try:
                t = r.type(key)
                if t == "hash":
                    h = r.hgetall(key)
                    if h.get("liquidation_long_level"):
                        levels_symbols.append(sym)
                        if sym == "BTCUSDT":
                            try:
                                btc_levels = {
                                    "long_level": float(h.get("liquidation_long_level") or 0),
                                    "short_level": float(h.get("liquidation_short_level") or 0),
                                    "long_distance_pct": float(h.get("liquidation_long_distance_pct") or 0),
                                    "short_distance_pct": float(h.get("liquidation_short_distance_pct") or 0),
                                    "long_strength": float(h.get("liquidation_long_strength") or 0),
                                    "short_strength": float(h.get("liquidation_short_strength") or 0),
                                }
                            except (TypeError, ValueError):
                                btc_levels = {}
            except Exception:
                continue

    # Count which liquidation services are systemd-active (infer from key presence)
    wss_active = 1 if r and r.exists(f"{V2_REDIS_PREFIX}liquidations:events") else 0
    bridge_active = 1 if levels_symbols else 0

    classification = "LIQUIDATION_BRIDGE_OK" if (wss_active or bridge_active) else "LIQUIDATION_BRIDGE_DEGRADED"

    payload: dict = {
        "schema_version": "v2_liquidation_bridge_status_v1",
        "worker_id": "v2_liquidation_bridge_status_publisher",
        "generated_utc": _utc_iso(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "classification": classification,
        "liquidation_keys_total": len(liquidation_keys),
        "liquidation_events_xlen": liq_events_xlen,
        "wss_services_active": wss_active,
        "bridge_services_active": bridge_active,
        "levels_symbols_covered": len(levels_symbols),
        "levels_symbols": levels_symbols,
        "note": (
            "Zero events is expected when no Binance forceOrder events have arrived. "
            "Services remain active and will capture events as they occur."
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
    parser = argparse.ArgumentParser(prog="v2_liquidation_bridge_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(json.dumps({"classification": payload["classification"], "levels_symbols": payload["levels_symbols"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
