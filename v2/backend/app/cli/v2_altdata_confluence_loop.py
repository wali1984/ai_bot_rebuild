"""Alt-data confluence publisher loop.

Reads CoinGlass/Santiment/Moralis payloads from Redis (read-only against
providers), computes confluence scores, and publishes:

  v2:altdata:confluence:{symbol}:{timeframe}
  v2:altdata:provider_consumption_status

Never places orders, never approves trades, never mutates provider state.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from app.services.altdata.altdata_confluence_engine import build_confluence
from app.services.altdata.provider_consumption_status import (
    publish_provider_consumption_status,
)
from app.services.altdata.provider_feature_bridge import (
    load_coinank_input,
    load_coinglass_input,
    load_moralis_input,
    load_santiment_input,
)
from app.services.alternative_data.santiment_client import (
    KEY_FEATURE_BRIDGE_STATUS as SANTIMENT_FEATURE_BRIDGE_STATUS_KEY,
    KEY_FEATURE_TEMPLATE as SANTIMENT_FEATURE_TEMPLATE,
    build_santiment_feature_payload,
    _santiment_feature_bridge_status,
)

CONFLUENCE_KEY = "v2:altdata:confluence:{symbol}:{timeframe}"
CONFLUENCE_TTL_SECONDS = 900
COINGLASS_FEATURE_KEY = "v2:features:coinglass:{symbol}:{timeframe}"
MORALIS_FEATURE_KEY = "v2:features:moralis:{symbol}:{timeframe}"
COINGLASS_FEATURE_BRIDGE_STATUS_KEY = "v2:provider:coinglass:feature_bridge_status"
MORALIS_FEATURE_BRIDGE_STATUS_KEY = "v2:provider:moralis:feature_bridge_status"
PREEMPTIVE_MATRIX_KEY = "v2:paper:preemptive_candidate_decision_matrix"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _candidate_symbol_timeframe_pairs(
    redis_client: Any,
    *,
    limit: int,
) -> list[tuple[str, str]]:
    if redis_client is None:
        return []
    try:
        raw = redis_client.get(PREEMPTIVE_MATRIX_KEY)
    except Exception:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not raw:
        return []
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or row.get("thesis_timeframe") or "").lower()
        if not symbol or not timeframe:
            continue
        pair = (symbol, timeframe)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
        if len(pairs) >= max(0, int(limit)):
            break
    return pairs


def _symbol_timeframe_pairs(
    redis_client: Any,
    *,
    symbols: list[str],
    timeframe: str,
    include_current_candidates: bool,
    max_candidate_pairs: int,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    base_pairs = {
        (str(symbol or "").upper(), str(timeframe or "1m").lower())
        for symbol in symbols
        if str(symbol or "").strip()
    }
    candidate_pairs = (
        _candidate_symbol_timeframe_pairs(redis_client, limit=max_candidate_pairs)
        if include_current_candidates
        else []
    )
    pairs = set(base_pairs)
    pairs.update(candidate_pairs)
    return sorted(pairs), candidate_pairs


def run_once(
    redis_client: Any,
    *,
    symbols: list[str],
    timeframe: str = "1m",
    include_current_candidates: bool = False,
    max_candidate_pairs: int = 250,
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    pairs, candidate_pairs = _symbol_timeframe_pairs(
        redis_client,
        symbols=symbols,
        timeframe=timeframe,
        include_current_candidates=include_current_candidates,
        max_candidate_pairs=max_candidate_pairs,
    )
    for symbol, pair_timeframe in pairs:
        payload = build_confluence(
            symbol=symbol,
            timeframe=pair_timeframe,
            coinglass=load_coinglass_input(redis_client, symbol, pair_timeframe),
            santiment=load_santiment_input(redis_client, symbol),
            moralis=load_moralis_input(redis_client, symbol, pair_timeframe),
            coinank=load_coinank_input(redis_client, symbol, pair_timeframe),
            generated_utc=generated,
        )
        if redis_client is not None:
            key = CONFLUENCE_KEY.format(symbol=symbol, timeframe=pair_timeframe)
            redis_client.set(
                key,
                json.dumps(payload, sort_keys=True, default=str),
                ex=CONFLUENCE_TTL_SECONDS,
            )
            _publish_provider_bridge_aliases(
                redis_client,
                symbol=symbol,
                timeframe=pair_timeframe,
                generated_utc=generated,
            )
        rows.append(
            {
                "symbol": symbol,
                "timeframe": pair_timeframe,
                "providers_present": payload["providers_present"],
                "actual_payload_present": payload["actual_payload_present"],
                "missing_feature_count": len(payload["missing_feature_flags"]),
            }
        )
    consumption = publish_provider_consumption_status(redis_client) if redis_client is not None else {}
    return {
        "schema_version": "altdata_confluence_loop_status_v1",
        "generated_utc": generated,
        "timeframe": timeframe,
        "symbol_count": len(symbols),
        "pair_count": len(pairs),
        "include_current_candidates": bool(include_current_candidates),
        "dynamic_candidate_pair_count": len(candidate_pairs),
        "max_candidate_pairs": int(max_candidate_pairs),
        "rows": rows,
        "confluence_key_count": consumption.get("confluence_key_count"),
        "places_real_order": False,
        "approves_live": False,
        "raw_key_exposed": False,
    }


def _load_json(redis_client: Any, key: str) -> dict[str, Any]:
    try:
        raw = redis_client.get(key)
    except Exception:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _bridge_status(
    provider: str,
    payload: dict[str, Any],
    *,
    generated_utc: str,
) -> dict[str, Any]:
    features = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    feature_count = int(payload.get("feature_count") or len(features))
    actual = bool(payload.get("actual_payload_present")) and feature_count > 0
    status = payload.get("status") or payload.get("subscription_status") or (
        "READY" if actual else "PAYLOADS_PENDING"
    )
    return {
        "schema_version": f"{provider}_feature_bridge_status_v1",
        "provider": provider,
        "generated_utc": payload.get("generated_utc") or payload.get("generated_at") or generated_utc,
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "status": status,
        "feature_bridge_ready": bool(payload.get("feature_bridge_ready", actual)),
        "feature_count": feature_count,
        "missing_feature_flags": payload.get("missing_feature_flags") or [],
        "stale_feature_flags": payload.get("stale_feature_flags") or [],
        "missing_mask": payload.get("missing_mask") or {},
        "missing_mask_true": bool(payload.get("missing_feature_flags")),
        "stale_mask": payload.get("stale_mask") or {},
        "stale_mask_true": bool(payload.get("stale_feature_flags")),
        "actual_payload_present": actual,
        "heartbeat_only": not actual,
        "trainer_consumption": True,
        "provider_tensor_consumption": True,
        "ppo_consumption": True,
        "masa_consumption": True,
        "risk_consumption": True,
        "orchestrator_consumption": True,
        "allocator_consumption": True,
        "paper_consumption": True,
        "live_dryrun_consumption": True,
        "feedback_attribution": True,
        "single_provider_can_approve": False,
        "provider_data_can_approve_trade_alone": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _set_json(redis_client: Any, key: str, payload: dict[str, Any], *, ex: int) -> None:
    redis_client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=max(1, int(ex)))


def _publish_provider_bridge_aliases(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
    generated_utc: str,
) -> None:
    coinglass = _load_json(
        redis_client,
        COINGLASS_FEATURE_KEY.format(symbol=symbol, timeframe=timeframe),
    )
    if coinglass:
        _set_json(
            redis_client,
            COINGLASS_FEATURE_BRIDGE_STATUS_KEY,
            _bridge_status("coinglass", coinglass, generated_utc=generated_utc),
            ex=3600,
        )
    moralis = _load_json(
        redis_client,
        MORALIS_FEATURE_KEY.format(symbol=symbol, timeframe=timeframe),
    )
    if moralis:
        _set_json(
            redis_client,
            MORALIS_FEATURE_BRIDGE_STATUS_KEY,
            _bridge_status("moralis", moralis, generated_utc=generated_utc),
            ex=3600,
        )
    santiment = _load_json(redis_client, f"v2:altdata:santiment:symbol:{symbol}")
    if santiment:
        santiment_feature = build_santiment_feature_payload(santiment, timeframe="1h")
        _set_json(
            redis_client,
            SANTIMENT_FEATURE_TEMPLATE.format(symbol=symbol, timeframe="1h"),
            santiment_feature,
            ex=28800,
        )
        _set_json(
            redis_client,
            SANTIMENT_FEATURE_BRIDGE_STATUS_KEY,
            _santiment_feature_bridge_status(santiment_feature),
            ex=28800,
        )


def _symbols(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


# Sentinel accepted in --symbols / ALTDATA_CONFLUENCE_SYMBOLS meaning
# "resolve the full runtime symbol universe each cycle" (symbol-universe
# policy: no static symbol lists).
UNIVERSE_SENTINEL = "UNIVERSE"


def _universe_symbols() -> list[str]:
    """Resolve the current runtime symbol universe (re-read every cycle so
    discovery changes propagate without a restart)."""
    try:
        from app.services.v2_symbol_runtime_universe import resolve_symbols

        return [str(s).upper() for s in resolve_symbols()]
    except Exception:
        return []


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Per-minute stdout goes to an append-only unit log; summarize the
    per-pair rows so a full-universe run does not grow the log ~150 bytes
    per symbol per cycle."""
    rows = report.get("rows") or []
    compact = {k: v for k, v in report.items() if k != "rows"}
    compact["row_count"] = len(rows)
    compact["actual_payload_present_count"] = sum(
        1 for row in rows if row.get("actual_payload_present")
    )
    providers_hist: dict[str, int] = {}
    for row in rows:
        for provider in row.get("providers_present") or ():
            providers_hist[str(provider)] = providers_hist.get(str(provider), 0) + 1
    compact["providers_present_counts"] = providers_hist
    return compact


def _redis_client(redis_url: str) -> Any:
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_altdata_confluence_loop")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument(
        "--symbols",
        default=os.environ.get("ALTDATA_CONFLUENCE_SYMBOLS", UNIVERSE_SENTINEL),
        help=(
            "CSV symbol list, or 'UNIVERSE' (default) to resolve the full "
            "runtime symbol universe every cycle"
        ),
    )
    parser.add_argument("--timeframe", default=os.environ.get("ALTDATA_CONFLUENCE_TIMEFRAME", "1m"))
    parser.add_argument(
        "--include-current-candidates",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("ALTDATA_CONFLUENCE_INCLUDE_CURRENT_CANDIDATES", True),
        help=(
            "also publish confluence for current preemptive matrix symbol/timeframe pairs; "
            "use --no-include-current-candidates or ALTDATA_CONFLUENCE_INCLUDE_CURRENT_CANDIDATES=0 to disable"
        ),
    )
    parser.add_argument(
        "--max-candidate-pairs",
        type=int,
        default=int(os.environ.get("ALTDATA_CONFLUENCE_MAX_CANDIDATE_PAIRS", "250") or 250),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)

    redis_client = _redis_client(args.redis_url)
    explicit_symbols = _symbols(args.symbols)
    universe_mode = explicit_symbols == [UNIVERSE_SENTINEL] or not explicit_symbols
    while True:
        if universe_mode:
            symbols = _universe_symbols()
            if not symbols:
                # Universe payload unreadable this cycle: publish nothing new
                # rather than silently shrinking to a static list.
                symbols = []
        else:
            symbols = explicit_symbols
        report = run_once(
            redis_client,
            symbols=symbols,
            timeframe=args.timeframe,
            include_current_candidates=bool(args.include_current_candidates),
            max_candidate_pairs=max(0, int(args.max_candidate_pairs)),
        )
        report["universe_mode"] = universe_mode
        print(
            json.dumps(_compact_report(report), indent=2, sort_keys=True, default=str),
            flush=True,
        )
        if args.once:
            return 0
        time.sleep(max(5.0, args.sleep_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
