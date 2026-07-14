"""HTF + cross-asset + regime-gate context publisher (Phases 3 & 4).

Per symbol, computes:
    v2:context:htf:{symbol}                  >= 20 HTF fields from closed 4h/derived-1D candles
    v2:regime:gate:{symbol}:{timeframe}      one of the 7 regimes, fail-closed
Shared:
    v2:context:cross_asset                   BTC/ETH market regime + risk-off proxy

Artifacts (goal_state + operator_runtime):
    htf_feature_expansion_status.json
    multi_timeframe_alignment_status.json
    cross_asset_context_status.json
    adaptive_regime_gate_status.json
    strategy_regime_permission_matrix.json

Reads only already-ingested closed candles and feature snapshots. Public data
only; never mutates exchange state or legacy Redis.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_regime_gate.classifier import (
    REGIMES,
    REGIME_GATE_REDIS_KEY_TEMPLATE,
    classify_regime,
    regime_classifier_behavioral_proofs,
)
from v2.backend.app.services.adaptive_regime_gate.permission_matrix import (
    permission_matrix_status,
)
from v2.backend.app.services.htf_context.service import (
    CROSS_ASSET_CONTEXT_REDIS_KEY,
    HTF_CONTEXT_REDIS_KEY_TEMPLATE,
    build_cross_asset_context,
    build_htf_context,
    multi_timeframe_alignment_score,
)
from v2.backend.app.services.trade_tape.service import TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
GOAL_STATE_DIR = REPO_ROOT / "goal_state" / GOAL_ID
OPERATOR_RUNTIME_DIR = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_a_plus_context/latest"
V2_REDIS_PREFIX = "v2:"
REDIS_TTL_SECONDS = 900
# 2026-07-14: extended to the fast timeframes the trainer actually trades.
# The regime math reads closed candles per TF (TF-agnostic); leaving 1m/5m out
# meant HALF the traded grid had no regime gate -- regime one-hot features
# missing on every 1m/5m candidate and no regime-aware gating on the most
# active lanes.
REGIME_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")

REQUIRED_HTF_FEATURE_FIELDS = (
    "htf_4h_ema50_delta_pct",
    "htf_4h_rsi_zone",
    "htf_4h_macd_state",
    "htf_1d_ema_direction",
    "htf_1d_rsi_zone",
    "htf_4h_support_distance_bps",
    "htf_4h_resistance_distance_bps",
    "htf_1d_support_distance_bps",
    "htf_1d_resistance_distance_bps",
    "htf_volume_poc_distance_bps",
)
REQUIRED_HTF_TENSOR_FIELDS = (
    "htf_4h_ema50_delta_pct",
    "htf_4h_rsi_14",
    "htf_4h_macd_hist",
    "htf_4h_ret_pct",
    "htf_4h_support_distance_bps",
    "htf_4h_resistance_distance_bps",
    "htf_4h_trend_code",
    "htf_4h_rsi_zone_code",
    "htf_4h_macd_state_code",
    "htf_1d_ret_pct",
    "htf_1d_rsi_14",
    "htf_1d_rsi_zone_code",
    "htf_1d_ema_direction_code",
    "htf_1d_support_distance_bps",
    "htf_1d_resistance_distance_bps",
    "htf_1d_realized_vol_pct",
    "htf_volume_poc_distance_bps",
)
REQUIRED_REGIME_TENSOR_FIELDS = (
    "regime_trending_up",
    "regime_trending_down",
    "regime_ranging",
    "regime_volatile_expansion",
    "regime_liquidity_sweep",
    "regime_fakeout_risk",
    "regime_no_trade",
    "regime_confidence",
)
REQUIRED_CROSS_ASSET_FIELDS = (
    "btc_direction_1h",
    "btc_direction_4h",
    "eth_btc_direction_4h",
    "risk_off_proxy",
    "market_risk_state",
)
REQUIRED_CROSS_ASSET_TENSOR_FIELDS = (
    "cross_btc_rsi_4h",
    "cross_btc_ret_4h_pct",
    "cross_btc_direction_1h_code",
    "cross_btc_direction_4h_code",
    "cross_eth_btc_direction_4h_code",
    "cross_risk_off_proxy",
)


def _tensor_field_status(required_fields: tuple[str, ...]) -> dict[str, Any]:
    tensor_fields = _tensor_feature_fields()
    missing = [name for name in required_fields if name not in tensor_fields]
    return {
        "required_fields": list(required_fields),
        "missing_tensor_fields": missing,
        "trainer_tensor_consumes_all_required_fields": not missing,
    }


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


def _klines(client: Any, symbol: str, timeframe: str) -> list[Any]:
    payload = _safe_get_json(client, f"v2:market:ohlcv:binance:{symbol}:{timeframe}")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ("klines", "candles", "rows"):
            rows = payload.get(field)
            if isinstance(rows, list):
                return rows
    return []


def _snapshot_features(client: Any, symbol: str, timeframe: str) -> dict[str, Any]:
    snapshot = _safe_get_json(client, f"v2:features:latest:{symbol}:{timeframe}")
    if isinstance(snapshot, dict):
        features = snapshot.get("features")
        if isinstance(features, dict):
            return features
    return {}


def run_cycle(client: Any, *, max_symbols: int) -> dict[str, Any]:
    generated = _utc_now()
    universe = resolve_symbols()
    symbols = universe[:max_symbols] if max_symbols else universe

    cross_asset = build_cross_asset_context(
        btc_klines_1h=_klines(client, "BTCUSDT", "1h"),
        btc_klines_4h=_klines(client, "BTCUSDT", "4h"),
        eth_klines_4h=_klines(client, "ETHUSDT", "4h"),
    )
    cross_asset["generated_utc"] = generated
    cross_asset_written = _safe_set_json(client, CROSS_ASSET_CONTEXT_REDIS_KEY, cross_asset)

    htf_ok = 0
    htf_field_counts: list[int] = []
    regime_counter: Counter[str] = Counter()
    fail_closed_count = 0
    alignment_samples: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    for symbol in symbols:
        klines_4h = _klines(client, symbol, "4h")
        row: dict[str, Any] = {"symbol": symbol}
        if len(klines_4h) < 40:
            row["status"] = f"INSUFFICIENT_4H_CANDLES:{len(klines_4h)}"
            per_symbol.append(row)
            continue
        htf = build_htf_context(symbol, klines_4h)
        htf["generated_utc"] = generated
        _safe_set_json(client, HTF_CONTEXT_REDIS_KEY_TEMPLATE.format(symbol=symbol), htf)
        htf_ok += 1
        htf_field_counts.append(int(htf.get("htf_feature_count") or 0))

        tape = _safe_get_json(client, TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE.format(symbol=symbol))
        regimes_for_symbol: dict[str, str] = {}
        for timeframe in REGIME_TIMEFRAMES:
            features = _snapshot_features(client, symbol, timeframe)
            if not features:
                continue
            decision = classify_regime(
                symbol=symbol,
                timeframe=timeframe,
                features=features,
                htf_context=htf,
                cross_asset=cross_asset,
                trade_tape=tape if isinstance(tape, dict) else None,
            )
            decision["generated_utc"] = generated
            _safe_set_json(
                client,
                REGIME_GATE_REDIS_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe),
                decision,
            )
            regime_counter[decision["regime"]] += 1
            if decision.get("fail_closed"):
                fail_closed_count += 1
            regimes_for_symbol[timeframe] = decision["regime"]
        row.update({"status": "OK", "htf_feature_count": htf.get("htf_feature_count"), "regimes": regimes_for_symbol})
        per_symbol.append(row)

        if len(alignment_samples) < 10:
            for side in ("long", "short"):
                alignment = multi_timeframe_alignment_score(
                    side=side,
                    entry_timeframe_trend=regimes_for_symbol.get("1h"),
                    htf_context=htf,
                    cross_asset=cross_asset,
                )
                alignment_samples.append({"symbol": symbol, "side": side, **alignment})

    min_htf_fields = min(htf_field_counts) if htf_field_counts else 0
    status = {
        "schema_version": "a_plus_context_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": generated,
        "worker_id": "v2_a_plus_context_loop",
        "universe_size": len(universe),
        "symbols_processed": len(symbols),
        "htf_context_ok": htf_ok,
        "htf_feature_count_min": min_htf_fields,
        "htf_feature_count_pass": min_htf_fields >= 20,
        "cross_asset_context_written": cross_asset_written,
        "cross_asset_context": cross_asset,
        "regime_distribution": dict(regime_counter),
        "regime_fail_closed_count": fail_closed_count,
        "regime_timeframes": list(REGIME_TIMEFRAMES),
        "alignment_samples": alignment_samples,
        "per_symbol": per_symbol,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = full universe")
    parser.add_argument("--max-cycles", type=int, default=0)
    args = parser.parse_args()

    client = _redis_client()
    cycle = 0
    while True:
        cycle += 1
        if client is None:
            # F015: reconnect each cycle — at boot this unit can start before
            # Redis accepts connections and a one-shot connect would leave the
            # loop publishing nothing for its whole lifetime.
            client = _redis_client()
        status = run_cycle(client, max_symbols=args.max_symbols)
        htf_tensor_status = _tensor_field_status(REQUIRED_HTF_TENSOR_FIELDS)
        regime_tensor_status = _tensor_field_status(REQUIRED_REGIME_TENSOR_FIELDS)
        cross_asset_tensor_status = _tensor_field_status(REQUIRED_CROSS_ASSET_TENSOR_FIELDS)
        _write_artifact(GOAL_STATE_DIR / "htf_feature_expansion_status.json", {
            "schema_version": "htf_feature_expansion_status_v1",
            "goal_id": GOAL_ID,
            "generated_utc": status["generated_utc"],
            "htf_context_ok": status["htf_context_ok"],
            "htf_feature_count_min": status["htf_feature_count_min"],
            "pass_condition_htf_feature_count_gte_20": status["htf_feature_count_pass"],
            "required_htf_context_fields": list(REQUIRED_HTF_FEATURE_FIELDS),
            "required_htf_tensor_fields": list(REQUIRED_HTF_TENSOR_FIELDS),
            "required_regime_tensor_fields": list(REQUIRED_REGIME_TENSOR_FIELDS),
            "htf_tensor_status": htf_tensor_status,
            "regime_tensor_status": regime_tensor_status,
            "trainer_tensor_consumes_htf_fields": htf_tensor_status[
                "trainer_tensor_consumes_all_required_fields"
            ],
            "trainer_tensor_consumes_regime_fields": regime_tensor_status[
                "trainer_tensor_consumes_all_required_fields"
            ],
            "feature_pipeline_context_merge": "v2_feature_pipeline_native_loop._merge_a_plus_context_features merges v2:context:htf and v2:regime:gate into decision-time snapshots",
            "redis_key_template": HTF_CONTEXT_REDIS_KEY_TEMPLATE,
            "symbols_processed": status["symbols_processed"],
            "places_real_order": False,
            "test_order_submitted": False,
            "exchange_leverage_mutated": False,
            "exchange_margin_mutated": False,
            "writes_legacy_redis": False,
            "live_gate": "blocked_human_only",
        })
        _write_artifact(GOAL_STATE_DIR / "multi_timeframe_alignment_status.json", {
            "schema_version": "multi_timeframe_alignment_status_v1",
            "goal_id": GOAL_ID,
            "generated_utc": status["generated_utc"],
            "alignment_samples": status["alignment_samples"],
            "misaligned_trades_blockable": True,
            "blocking_code_path": "a_plus_trade_gate.service._htf_check -> multi_timeframe_alignment_score",
            "a_plus_min_htf_alignment_score": 0.25,
            "sample_misaligned_count": sum(1 for row in status["alignment_samples"] if row.get("misaligned")),
            "risk_orchestrator_can_block_misaligned_trades": True,
            "places_real_order": False,
            "test_order_submitted": False,
            "exchange_leverage_mutated": False,
            "exchange_margin_mutated": False,
            "writes_legacy_redis": False,
            "live_gate": "blocked_human_only",
        })
        _write_artifact(GOAL_STATE_DIR / "cross_asset_context_status.json", {
            "schema_version": "cross_asset_context_status_v1",
            "goal_id": GOAL_ID,
            "generated_utc": status["generated_utc"],
            "cross_asset_context": status["cross_asset_context"],
            "cross_asset_context_written": status["cross_asset_context_written"],
            "required_cross_asset_fields": list(REQUIRED_CROSS_ASSET_FIELDS),
            "cross_asset_required_fields_present": all(
                key in status["cross_asset_context"] for key in REQUIRED_CROSS_ASSET_FIELDS
            ),
            "required_cross_asset_tensor_fields": list(REQUIRED_CROSS_ASSET_TENSOR_FIELDS),
            "cross_asset_tensor_status": cross_asset_tensor_status,
            "trainer_tensor_consumes_cross_asset_fields": cross_asset_tensor_status[
                "trainer_tensor_consumes_all_required_fields"
            ],
            "redis_key": CROSS_ASSET_CONTEXT_REDIS_KEY,
            "places_real_order": False,
            "test_order_submitted": False,
            "exchange_leverage_mutated": False,
            "exchange_margin_mutated": False,
            "writes_legacy_redis": False,
            "live_gate": "blocked_human_only",
        })
        regime_behavioral_proofs = regime_classifier_behavioral_proofs()
        _write_artifact(GOAL_STATE_DIR / "adaptive_regime_gate_status.json", {
            "schema_version": "adaptive_regime_gate_status_v1",
            "goal_id": GOAL_ID,
            "generated_utc": status["generated_utc"],
            "required_regimes": list(REGIMES),
            "required_input_families": regime_behavioral_proofs["required_input_families"],
            "regime_distribution": status["regime_distribution"],
            "regime_fail_closed_count": status["regime_fail_closed_count"],
            "regime_timeframes": status["regime_timeframes"],
            "redis_key_template": REGIME_GATE_REDIS_KEY_TEMPLATE,
            "fail_closed_on_missing_inputs": True,
            "behavioral_proofs": regime_behavioral_proofs["proofs"],
            "all_required_regime_outputs_proven": regime_behavioral_proofs[
                "all_required_regime_outputs_proven"
            ],
            "all_behavioral_proofs_passed": regime_behavioral_proofs["all_proofs_passed"],
            "places_real_order": False,
            "test_order_submitted": False,
            "exchange_leverage_mutated": False,
            "exchange_margin_mutated": False,
            "writes_legacy_redis": False,
            "live_gate": "blocked_human_only",
        })
        _write_artifact(GOAL_STATE_DIR / "strategy_regime_permission_matrix.json", {
            "goal_id": GOAL_ID,
            "generated_utc": status["generated_utc"],
            "live_gate": "blocked_human_only",
            "places_real_order": False,
            "test_order_submitted": False,
            "exchange_leverage_mutated": False,
            "exchange_margin_mutated": False,
            "writes_legacy_redis": False,
            **permission_matrix_status(),
        })
        _write_artifact(OPERATOR_RUNTIME_DIR / "a_plus_context_status.json", status)
        print(
            json.dumps(
                {
                    "cycle": cycle,
                    "generated_utc": status["generated_utc"],
                    "htf_ok": status["htf_context_ok"],
                    "regimes": status["regime_distribution"],
                    "fail_closed": status["regime_fail_closed_count"],
                }
            ),
            flush=True,
        )
        if not args.loop or (args.max_cycles and cycle >= args.max_cycles):
            return 0
        time.sleep(max(30, args.interval_seconds))


if __name__ == "__main__":
    sys.exit(main())
