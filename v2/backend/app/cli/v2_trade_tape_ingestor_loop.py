"""Free Binance aggTrades trade-tape ingestor loop (Phase 5).

Writes only:
    v2:market:agg_trades:{symbol}            raw recent aggTrades (bounded)
    v2:market:trade_tape_features:{symbol}   computed order-flow features
    goal_state/.../trade_tape_feature_status.json (+ order_flow_confirmation_status.json)

Public market data only. Never places/cancels orders, never touches leverage,
margin, live gates, or legacy Redis keys. Request budget is capped per cycle
to stay far below Binance's 2400 weight/min IP limit (aggTrades weight = 20).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.trade_tape.service import (
    AGG_TRADES_REQUEST_WEIGHT,
    AGG_TRADES_REDIS_KEY_TEMPLATE,
    TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE,
    compute_trade_tape_features,
    fetch_binance_agg_trades,
    order_flow_confirms_side,
    trade_tape_blocks_breakout,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
GOAL_STATE_DIR = REPO_ROOT / "goal_state" / GOAL_ID
OPERATOR_RUNTIME_DIR = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_trade_tape/latest"
V2_REDIS_PREFIX = "v2:"
REDIS_TTL_SECONDS = 900
RAW_TRADES_KEPT = 1000
MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_MAX_SYMBOLS_PER_CYCLE = 40
WEIGHT_BUDGET_PER_CYCLE = DEFAULT_MAX_SYMBOLS_PER_CYCLE * AGG_TRADES_REQUEST_WEIGHT
REQUIRED_TRADE_TAPE_FIELDS = (
    "taker_buy_pct_1m",
    "delta_1m",
    "cumulative_delta_trend_5m",
    "large_trade_flag",
    "aggressive_buy_volume",
    "aggressive_sell_volume",
    "volume_acceleration",
    "trade_tape_confirmation_score",
)
REQUIRED_TRADE_TAPE_TENSOR_FIELDS = (
    "taker_buy_pct_1m",
    "tape_delta_1m_usd",
    "tape_cumulative_delta_trend_code",
    "tape_large_trade_flag",
    "aggressive_buy_volume",
    "aggressive_sell_volume",
    "tape_volume_acceleration",
    "trade_tape_confirmation_score",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redis_client() -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        url = os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _safe_get_json(client: Any, key: str) -> Any:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _safe_set_json(client: Any, key: str, payload: Any, ttl: int = REDIS_TTL_SECONDS) -> bool:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        client.set(key, json.dumps(payload, separators=(",", ":")), ex=ttl)
        return True
    except Exception:
        return False


def _write_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _tensor_feature_fields() -> set[str]:
    source_path = (
        REPO_ROOT
        / "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py"
    )
    try:
        module = ast.parse(source_path.read_text(encoding="utf-8"))
    except OSError:
        return set()
    for node in module.body:
        value_node = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FEATURE_SPEC" for target in node.targets
        ):
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "FEATURE_SPEC":
            value_node = node.value
        if value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (SyntaxError, ValueError):
            return set()
        return {str(item[0]) for item in value if isinstance(item, tuple) and item}
    return set()


def _tensor_field_status() -> dict[str, Any]:
    fields = _tensor_feature_fields()
    missing = [field for field in REQUIRED_TRADE_TAPE_TENSOR_FIELDS if field not in fields]
    return {
        "required_tensor_fields": list(REQUIRED_TRADE_TAPE_TENSOR_FIELDS),
        "missing_tensor_fields": missing,
        "trainer_tensor_consumes_trade_tape_fields": not missing,
    }


def _order_flow_behavioral_proofs() -> dict[str, Any]:
    buy_pressure = {
        "trade_tape_confirmation_state": "TAPE_DATA_OK",
        "trade_tape_confirmation_score": 0.85,
        "volume_acceleration": 1.4,
    }
    sell_pressure = {
        "trade_tape_confirmation_state": "TAPE_DATA_OK",
        "trade_tape_confirmation_score": 0.15,
        "volume_acceleration": 1.4,
    }
    missing = {"trade_tape_confirmation_state": "INSUFFICIENT_TAPE_DATA"}
    cases = [
        {
            "name": "long_breakout_allowed_when_tape_confirms",
            "expected_blocked": False,
            "features": buy_pressure,
            "side": "long",
        },
        {
            "name": "long_breakout_blocked_when_tape_contradicts",
            "expected_blocked": True,
            "features": sell_pressure,
            "side": "long",
        },
        {
            "name": "short_breakout_blocked_when_tape_contradicts",
            "expected_blocked": True,
            "features": buy_pressure,
            "side": "short",
        },
        {
            "name": "breakout_blocks_when_tape_missing",
            "expected_blocked": True,
            "features": missing,
            "side": "long",
        },
    ]
    proofs: list[dict[str, Any]] = []
    for case in cases:
        blocked, reason = trade_tape_blocks_breakout(case["features"], str(case["side"]))
        proofs.append(
            {
                "name": case["name"],
                "side": case["side"],
                "expected_blocked": case["expected_blocked"],
                "actual_blocked": blocked,
                "passed": blocked is case["expected_blocked"],
                "reason": reason,
            }
        )
    return {"proofs": proofs, "all_proofs_passed": all(row["passed"] for row in proofs)}


def _priority_symbols(client: Any, universe: list[str], rotation_offset: int, cap: int) -> list[str]:
    """Open-position symbols first, then majors, then a rotating universe slice."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(symbol: str) -> None:
        text = str(symbol or "").upper()
        if text and text in universe_set and text not in seen:
            seen.add(text)
            ordered.append(text)

    universe_set = set(universe)
    positions = _safe_get_json(client, "v2:paper:positions")
    if isinstance(positions, list):
        for row in positions:
            if isinstance(row, dict):
                _add(row.get("symbol"))
    for symbol in MAJOR_SYMBOLS:
        _add(symbol)
    if universe:
        for index in range(len(universe)):
            if len(ordered) >= cap:
                break
            _add(universe[(rotation_offset + index) % len(universe)])
    return ordered[:cap]


def _trade_tape_symbol_count(client: Any, universe: list[str], current_ok_count: int) -> int:
    if client is None:
        return int(current_ok_count)
    count = 0
    for symbol in universe:
        payload = _safe_get_json(client, TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE.format(symbol=symbol))
        if isinstance(payload, dict):
            count += 1
    return count


def run_cycle(client: Any, *, rotation_offset: int, max_symbols: int) -> dict[str, Any]:
    universe = resolve_symbols()
    symbols = _priority_symbols(client, universe, rotation_offset, max_symbols)
    generated = _utc_now()
    per_symbol: list[dict[str, Any]] = []
    ok_count = 0
    non_neutral = 0
    for symbol in symbols:
        row: dict[str, Any] = {"symbol": symbol}
        try:
            trades = fetch_binance_agg_trades(symbol, limit=1000)
            features = compute_trade_tape_features(trades)
            features["symbol"] = symbol
            features["generated_utc"] = generated
            raw_payload = {
                "schema_version": "v2_agg_trades_raw_v1",
                "symbol": symbol,
                "generated_utc": generated,
                "source": "binance_fapi_public_agg_trades",
                "trades": trades[-RAW_TRADES_KEPT:],
            }
            wrote_raw = _safe_set_json(client, AGG_TRADES_REDIS_KEY_TEMPLATE.format(symbol=symbol), raw_payload)
            wrote_features = _safe_set_json(
                client, TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE.format(symbol=symbol), features
            )
            row.update(
                {
                    "status": "OK",
                    "trade_count_5m": features.get("trade_count_5m"),
                    "trade_tape_confirmation_score": features.get("trade_tape_confirmation_score"),
                    "trade_tape_confirmation_state": features.get("trade_tape_confirmation_state"),
                    "taker_buy_pct_1m": features.get("taker_buy_pct_1m"),
                    "cumulative_delta_trend_5m": features.get("cumulative_delta_trend_5m"),
                    "large_trade_flag": features.get("large_trade_flag"),
                    "wrote_raw_key": wrote_raw,
                    "wrote_features_key": wrote_features,
                }
            )
            ok_count += 1
            score = features.get("trade_tape_confirmation_score")
            if isinstance(score, (int, float)) and abs(score - 0.5) > 1e-9:
                non_neutral += 1
        except Exception as exc:  # noqa: BLE001 — per-symbol isolation, loop must survive
            row.update({"status": "FETCH_FAILED", "error": f"{type(exc).__name__}:{exc}"})
        per_symbol.append(row)
        time.sleep(0.15)  # spread requests inside the cycle

    long_probe, long_reason = (None, "NO_DATA")
    short_probe, short_reason = (None, "NO_DATA")
    btc_features = _safe_get_json(client, TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE.format(symbol="BTCUSDT"))
    if isinstance(btc_features, dict):
        long_probe, long_reason = order_flow_confirms_side(btc_features, "long")
        short_probe, short_reason = order_flow_confirms_side(btc_features, "short")
    trade_tape_symbols = _trade_tape_symbol_count(client, universe, ok_count)
    coverage_pct = trade_tape_symbols / len(universe) if universe else 0.0

    return {
        "schema_version": "trade_tape_feature_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": generated,
        "worker_id": "v2_trade_tape_ingestor_loop",
        "source": "binance_fapi_public_agg_trades",
        "request_weight_per_symbol": AGG_TRADES_REQUEST_WEIGHT,
        "request_weight_budget_per_cycle": WEIGHT_BUDGET_PER_CYCLE,
        "universe_size": len(universe),
        "symbols_polled": len(symbols),
        "symbols_ok": ok_count,
        "signal_universe_symbols": len(universe),
        "trade_tape_symbols": trade_tape_symbols,
        "trade_tape_coverage_pct": coverage_pct,
        "ttl_seconds": REDIS_TTL_SECONDS,
        "symbols_per_cycle": max_symbols,
        "symbols_with_non_neutral_tape": non_neutral,
        "rotation_offset": rotation_offset,
        "btc_order_flow_probe": {
            "long": {"confirms": long_probe, "reason": long_reason},
            "short": {"confirms": short_probe, "reason": short_reason},
        },
        "per_symbol": per_symbol,
        "required_fields": list(REQUIRED_TRADE_TAPE_FIELDS),
        "tensor_field_status": _tensor_field_status(),
        "feature_pipeline_context_merge": "v2_feature_pipeline_native_loop._merge_a_plus_context_features maps v2:market:trade_tape_features into decision-time snapshots",
        "hard_rules": [
            "NO_BREAKOUT_OR_SQUEEZE_TRADE_WITHOUT_TAPE_CONFIRMATION",
            "NO_HIGH_CONFIDENCE_TRADE_WHEN_ORDER_FLOW_CONTRADICTS_SIDE",
        ],
        "behavioral_proofs": _order_flow_behavioral_proofs()["proofs"],
        "all_behavioral_proofs_passed": _order_flow_behavioral_proofs()["all_proofs_passed"],
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }


def _build_order_flow_confirmation_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "order_flow_confirmation_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": status["generated_utc"],
        "confirmation_source": "v2:market:trade_tape_features:{symbol}",
        "fail_closed_when_tape_missing": True,
        "btc_order_flow_probe": status["btc_order_flow_probe"],
        "symbols_with_non_neutral_tape": status["symbols_with_non_neutral_tape"],
        "symbols_ok": status["symbols_ok"],
        "hard_rules": status["hard_rules"],
        "behavioral_proofs": status["behavioral_proofs"],
        "all_behavioral_proofs_passed": status["all_behavioral_proofs_passed"],
        "tensor_field_status": status["tensor_field_status"],
        "trainer_tensor_consumes_trade_tape_fields": status["tensor_field_status"][
            "trainer_tensor_consumes_trade_tape_fields"
        ],
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }


def _build_trade_tape_coverage_status(status: dict[str, Any]) -> dict[str, Any]:
    universe_count = int(status.get("signal_universe_symbols") or status.get("universe_size") or 0)
    trade_tape_symbols = int(status.get("trade_tape_symbols") or 0)
    coverage_pct = float(status.get("trade_tape_coverage_pct") or 0.0)
    ttl_seconds = int(status.get("ttl_seconds") or REDIS_TTL_SECONDS)
    symbols_per_cycle = int(status.get("symbols_per_cycle") or 0)
    pass_conditions = {
        "signal_universe_at_least_105": universe_count >= 105,
        "trade_tape_symbols_at_least_105": trade_tape_symbols >= 105,
        "coverage_at_least_95pct": coverage_pct >= 0.95,
        "ttl_seconds_is_900": ttl_seconds == 900,
        "symbols_per_cycle_is_40": symbols_per_cycle == 40,
    }
    passed = all(pass_conditions.values())
    blocker = None
    if not passed:
        blocker = "TRADE_TAPE_COVERAGE_INCOMPLETE"
        if 60 <= trade_tape_symbols <= 75 and universe_count >= 105:
            blocker = "STALE_SYSTEMD_UNIT_OR_RUNNING_PROCESS"
    return {
        "schema_version": "trade_tape_coverage_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": status.get("generated_utc"),
        "status": (
            "PASSED_TRADE_TAPE_LIVE_UNIVERSE_COVERAGE"
            if passed
            else "BLOCKED_TRADE_TAPE_COVERAGE_INCOMPLETE"
        ),
        "blocker": blocker,
        "signal_universe_symbols": universe_count,
        "trade_tape_symbols": trade_tape_symbols,
        "coverage_pct": coverage_pct,
        "ttl_seconds": ttl_seconds,
        "symbols_per_cycle": symbols_per_cycle,
        "pass_conditions": pass_conditions,
        "required": {
            "signal_universe_symbols_min": 105,
            "trade_tape_symbols_min": 105,
            "coverage_pct_min": 0.95,
            "ttl_seconds": 900,
            "symbols_per_cycle": 40,
        },
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-symbols-per-cycle", type=int, default=DEFAULT_MAX_SYMBOLS_PER_CYCLE)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 = unbounded when --loop")
    args = parser.parse_args()

    client = _redis_client()
    rotation_offset = 0
    cycle = 0
    while True:
        cycle += 1
        status = run_cycle(client, rotation_offset=rotation_offset, max_symbols=args.max_symbols_per_cycle)
        rotation_offset = (rotation_offset + args.max_symbols_per_cycle) % max(1, status["universe_size"])
        _write_artifact(GOAL_STATE_DIR / "trade_tape_feature_status.json", status)
        confirmation_status = _build_order_flow_confirmation_status(status)
        coverage_status = _build_trade_tape_coverage_status(status)
        _write_artifact(GOAL_STATE_DIR / "order_flow_confirmation_status.json", confirmation_status)
        _write_artifact(GOAL_STATE_DIR / "trade_tape_coverage_status.json", coverage_status)
        _write_artifact(OPERATOR_RUNTIME_DIR / "trade_tape_feature_status.json", status)
        _write_artifact(OPERATOR_RUNTIME_DIR / "order_flow_confirmation_status.json", confirmation_status)
        _write_artifact(OPERATOR_RUNTIME_DIR / "trade_tape_coverage_status.json", coverage_status)
        _safe_set_json(client, "v2:market:trade_tape_features:summary", {
            "generated_utc": status["generated_utc"],
            "symbols_ok": status["symbols_ok"],
            "symbols_polled": status["symbols_polled"],
            "trade_tape_symbols": status["trade_tape_symbols"],
            "coverage_pct": status["trade_tape_coverage_pct"],
            "symbols_with_non_neutral_tape": status["symbols_with_non_neutral_tape"],
            "universe_size": status["universe_size"],
            "rotation_offset": status["rotation_offset"],
        })
        _safe_set_json(client, "v2:market:trade_tape_coverage_status", coverage_status)
        print(
            json.dumps(
                {
                    "cycle": cycle,
                    "generated_utc": status["generated_utc"],
                    "symbols_ok": status["symbols_ok"],
                    "symbols_polled": status["symbols_polled"],
                    "non_neutral": status["symbols_with_non_neutral_tape"],
                }
            ),
            flush=True,
        )
        if not args.loop or (args.max_cycles and cycle >= args.max_cycles):
            return 0
        time.sleep(max(10, args.interval_seconds))


if __name__ == "__main__":
    sys.exit(main())
