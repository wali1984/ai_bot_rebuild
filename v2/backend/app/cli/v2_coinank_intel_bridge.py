"""Bridge fresh legacy CoinAnk intelligence into the V2 namespace.

The legacy CoinAnk runtime (live_coinank.py + live_coinank_global_aggregator.py)
publishes rich, real-time market intelligence onto NON-``v2:``-prefixed keys
(``features:global_coinank:*``, ``latest:coinank:{family}:{symbol}:{tf}``). The
V2 trainer / strategy-supply / confluence consumers only read ``v2:`` keys, so
that intelligence — funding, OI, long/short, liquidations, global regime — was
stranded even though it was fresh. This read-only bridge mirrors it into the
``v2:coinank:*`` and ``v2:features:coinank:*`` keys those consumers scan.

Safety: reads legacy keys, writes only ``v2:`` keys, never touches orders,
leverage, margin, or the live gate.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any, Mapping

V2_PREFIX = "v2:"
GLOBAL_SNAPSHOT_KEY = "v2:coinank:global:latest"
GLOBAL_MEMBER_KEY = "v2:coinank:global:{name}:latest"
SYMBOL_KEY = "v2:coinank:symbol:{symbol}"
FEATURE_KEY = "v2:features:coinank:{symbol}:{timeframe}"
PROVIDER_HEALTH_KEY = "v2:provider:coinank:health"
PROVIDER_FEATURE_BRIDGE_KEY = "v2:provider:coinank:feature_bridge_status"
STATUS_KEY = "v2:coinank:intel_bridge_status"

TTL_SECONDS = 900
SCAN_CAP = 4000
SCAN_BUDGET_SECONDS = 4.0
GLOBAL_MAX_AGE_SECONDS = 900

GLOBAL_NAMES = (
    "total_oi", "total_volume", "total_liquidations", "long_short_ratio",
    "funding_rate_avg", "btc_dominance", "eth_dominance", "alt_season_index",
    "fear_greed", "market_sentiment", "volatility_index",
)
FAMILIES = ("funding", "long_short", "open_interest", "liquidations", "market_order_flow")
LEGACY_LATEST = "latest:coinank:{family}:{symbol}:{timeframe}"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _get_json(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _set_json(client: Any, key: str, payload: Any, ex: int = TTL_SECONDS) -> bool:
    if not key.startswith(V2_PREFIX):
        return False
    try:
        client.set(key, json.dumps(payload, default=str), ex=ex)
        return True
    except Exception:
        return False


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def _series(payload: Mapping[str, Any]) -> list[Any]:
    """Return the CoinAnk time-series list from a latest:coinank:* payload."""
    data = payload.get("data")
    if isinstance(data, Mapping):
        inner = data.get("data")
        if isinstance(inner, list):
            return inner
        if isinstance(inner, Mapping):
            return [inner]
    if isinstance(data, list):
        return data
    return []


def _last_num(rows: list[Any], *fields: str) -> float | None:
    for row in reversed(rows):
        if isinstance(row, Mapping):
            for field in fields:
                v = _f(row.get(field))
                if v is not None:
                    return v
    return None


def _tail_list(inner: Any, *fields: str) -> float | None:
    """Long/short payloads store parallel arrays; return the last element."""
    if isinstance(inner, Mapping):
        for field in fields:
            arr = inner.get(field)
            if isinstance(arr, list) and arr:
                v = _f(arr[-1])
                if v is not None:
                    return v
    return None


def build_global_snapshot(client: Any) -> dict[str, Any]:
    now_ms = time.time() * 1000.0
    members: dict[str, Any] = {}
    ages: list[float] = []
    present = 0
    for name in GLOBAL_NAMES:
        payload = _get_json(client, f"features:global_coinank:{name}:latest")
        if not isinstance(payload, Mapping):
            members[name] = None
            continue
        value = _f(payload.get("value"))
        ts = _f(payload.get("timestamp"))
        age = round((now_ms - ts) / 1000.0, 1) if ts else None
        if age is not None:
            ages.append(age)
        members[name] = {"value": value, "age_seconds": age, "n": payload.get("n")}
        if value is not None:
            present += 1
        _set_json(client, GLOBAL_MEMBER_KEY.format(name=name),
                  {"name": name, "value": value, "age_seconds": age,
                   "source": "coinank_global", "generated_utc": _utc_iso()})
    freshest = min(ages) if ages else None
    snapshot = {
        "schema_version": "v2_coinank_global_snapshot_v1",
        "generated_utc": _utc_iso(),
        "source": "legacy_features_global_coinank",
        "members": members,
        "present_member_count": present,
        "freshest_member_age_seconds": freshest,
        "is_fresh": freshest is not None and freshest <= GLOBAL_MAX_AGE_SECONDS,
        "market_regime_context": {
            "total_open_interest_usd": (members.get("total_oi") or {}).get("value"),
            "aggregate_long_short_ratio": (members.get("long_short_ratio") or {}).get("value"),
            "avg_funding_rate": (members.get("funding_rate_avg") or {}).get("value"),
            "total_liquidations_usd": (members.get("total_liquidations") or {}).get("value"),
            "market_sentiment": (members.get("market_sentiment") or {}).get("value"),
            "fear_greed": (members.get("fear_greed") or {}).get("value"),
            "alt_season_index": (members.get("alt_season_index") or {}).get("value"),
        },
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }
    _set_json(client, GLOBAL_SNAPSHOT_KEY, snapshot)
    return snapshot


def _discover_symbol_tf(client: Any) -> dict[str, set[str]]:
    """Bounded scan of latest:coinank:* to find fresh (symbol, timeframe) pairs."""
    out: dict[str, set[str]] = {}
    n = 0
    t0 = time.time()
    try:
        for key in client.scan_iter(match="latest:coinank:*", count=1000):
            n += 1
            parts = key.split(":")
            # latest:coinank:{family}:{SYMBOL}:{tf}
            if len(parts) >= 5:
                symbol, tf = parts[-2].upper(), parts[-1]
                if symbol.endswith("USDT"):
                    out.setdefault(symbol, set()).add(tf)
            if n >= SCAN_CAP or time.time() - t0 > SCAN_BUDGET_SECONDS:
                break
    except Exception:
        pass
    return out


def _extract_symbol_features(client: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    now_ms = time.time() * 1000.0
    feats: dict[str, Any] = {}
    freshest_age: float | None = None
    families_seen = 0
    for family in FAMILIES:
        payload = _get_json(client, LEGACY_LATEST.format(
            family=family, symbol=symbol, timeframe=timeframe))
        if not isinstance(payload, Mapping):
            continue
        families_seen += 1
        ts = _f(payload.get("ts_ms") or payload.get("timestamp"))
        if ts:
            age = (now_ms - ts) / 1000.0
            freshest_age = age if freshest_age is None else min(freshest_age, age)
        rows = _series(payload)
        inner = payload.get("data", {}).get("data") if isinstance(payload.get("data"), Mapping) else None
        if family == "funding":
            feats["coinank_funding_rate"] = _last_num(rows, "fundingRate", "fr")
        elif family == "long_short":
            feats["coinank_long_short_ratio"] = _tail_list(
                inner, "longShortRatios", "longShortRatio", "ratios", "values")
        elif family == "open_interest":
            feats["coinank_open_interest"] = _last_num(
                rows, "openInterest", "coinvalue", "coinValue", "value")
        elif family == "liquidations":
            lt = _last_num(rows, "longTurnover")
            st = _last_num(rows, "shortTurnover")
            if lt is not None or st is not None:
                feats["coinank_liquidation_long_turnover"] = lt or 0.0
                feats["coinank_liquidation_short_turnover"] = st or 0.0
                feats["coinank_liquidation_imbalance_usd"] = (lt or 0.0) - (st or 0.0)
        elif family == "market_order_flow":
            feats["coinank_taker_buy"] = _last_num(rows, "buy", "buyVol", "takerBuy")
            feats["coinank_taker_sell"] = _last_num(rows, "sell", "sellVol", "takerSell")
    if families_seen == 0:
        return None
    # Derived directional sub-score in [-1, 1]: positive funding + long-heavy
    # long/short + long-liquidation dominance => crowded-long risk (bearish
    # squeeze context). Paper/analysis only; never an approval.
    fr = feats.get("coinank_funding_rate")
    ls = feats.get("coinank_long_short_ratio")
    imb = feats.get("coinank_liquidation_imbalance_usd")
    parts, weights = [], []
    if fr is not None:
        parts.append(max(-1.0, min(1.0, fr * 2000.0))); weights.append(1.0)
    if ls is not None:
        parts.append(max(-1.0, min(1.0, (ls - 1.0)))); weights.append(1.0)
    if imb is not None:
        parts.append(max(-1.0, min(1.0, imb / 1_000_000.0))); weights.append(0.5)
    score = round(sum(p * w for p, w in zip(parts, weights)) / sum(weights), 6) if weights else None
    feats["coinank_derivatives_score"] = score
    return {
        "schema_version": "v2_coinank_symbol_feature_v1",
        "provider": "coinank",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_utc": _utc_iso(),
        "source_freshness_seconds": round(freshest_age, 1) if freshest_age is not None else None,
        "families_present": families_seen,
        "features": feats,
        "coinank_derivatives_score": score,
        "actual_payload_present": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }


def run_once(client: Any = None, *, max_symbols: int = 200) -> dict[str, Any]:
    client = client if client is not None else _connect_redis()
    if client is None:
        return {"status": "NO_REDIS", "written": 0}
    global_snapshot = build_global_snapshot(client)
    discovered = _discover_symbol_tf(client)
    symbol_written = 0
    feature_written = 0
    symbols_covered: list[str] = []
    for symbol in sorted(discovered)[:max_symbols]:
        best_payload = None
        for tf in sorted(discovered[symbol]):
            payload = _extract_symbol_features(client, symbol, tf)
            if payload is None:
                continue
            if _set_json(client, FEATURE_KEY.format(symbol=symbol, timeframe=tf), payload):
                feature_written += 1
            if best_payload is None or (payload.get("features") and
                                        len(payload["features"]) > len(best_payload.get("features") or {})):
                best_payload = payload
        if best_payload is not None:
            consolidated = {**best_payload, "schema_version": "v2_coinank_symbol_intel_v1"}
            if _set_json(client, SYMBOL_KEY.format(symbol=symbol), consolidated):
                symbol_written += 1
                symbols_covered.append(symbol)
    health = {
        "schema_version": "v2_coinank_intel_bridge_health_v1",
        "provider": "coinank",
        "generated_utc": _utc_iso(),
        "status": "ACTIVE" if global_snapshot.get("is_fresh") else "STALE",
        "dashboard_color": "green" if global_snapshot.get("is_fresh") else "yellow",
        "dashboard_color_reason": "coinank_intel_bridge",
        "actual_payload_count": symbol_written + global_snapshot.get("present_member_count", 0),
        "actual_payload_present": symbol_written > 0,
        "feature_count": feature_written,
        "consumer_roles": ["trainer", "strategy_supply", "risk", "confluence", "squeeze_context"],
        "consumer_count": 5,
        "symbols_covered": symbols_covered[:20],
        "global_present_members": global_snapshot.get("present_member_count"),
        "global_freshest_age_seconds": global_snapshot.get("freshest_member_age_seconds"),
        "heartbeat_only": False,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
    _set_json(client, PROVIDER_HEALTH_KEY, health, ex=300)
    _set_json(client, PROVIDER_FEATURE_BRIDGE_KEY, {
        **health, "schema_version": "v2_coinank_feature_bridge_status_v1",
        "feature_key_template": FEATURE_KEY,
    }, ex=300)
    status = {
        "schema_version": "v2_coinank_intel_bridge_status_v1",
        "generated_utc": _utc_iso(),
        "global_present_members": global_snapshot.get("present_member_count"),
        "global_is_fresh": global_snapshot.get("is_fresh"),
        "symbols_discovered": len(discovered),
        "symbol_intel_written": symbol_written,
        "feature_payloads_written": feature_written,
        "written": symbol_written + feature_written + 1,
    }
    _set_json(client, STATUS_KEY, status, ex=300)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-symbols", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    while True:
        result = run_once(max_symbols=args.max_symbols)
        if args.json:
            print(json.dumps(result, default=str))
        if not args.loop:
            return 0 if result.get("written", 0) > 0 else 1
        time.sleep(max(15, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
