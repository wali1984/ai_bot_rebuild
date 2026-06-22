"""Build V2 realtime signal visibility artifacts.

This is a read-only/public-artifact builder. It reads existing V2 public
runtime payloads, derives all-timeframe prediction/price-target status,
and writes browser-consumable JSON under ``operator_runtime/v2_signals``.

Safety invariants:
- no exchange calls
- no Redis writes
- no live/canary approval
- live/order mutation remains blocked; live gate state is displayed from current runtime truth
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


WORKER_ID = "v2_realtime_signal_visibility"
SERVICE_ID = "v2_signals_public_visibility_builder"
DEFAULT_LIVE_GATE = "blocked_human_only"
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
DEFAULT_STALE_SECONDS = 120
EST = ZoneInfo("America/New_York")

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_ROOT = V2_ROOT / "frontend" / "public"
PUBLIC_OUT = PUBLIC_ROOT / "operator_runtime" / "v2_signals" / "latest"
LOCAL_OUT = V2_ROOT / "runtime" / "v2_signals" / "latest"

PATHS = {
    "paper_runtime": PUBLIC_ROOT / "operator_runtime/paper_online/latest/paper_runtime_status.json",
    "current_signal_lineage": PUBLIC_ROOT / "operator_runtime/paper_online/latest/current_signal_lineage.json",
    "trainer_prediction_record": PUBLIC_ROOT / "operator_runtime/paper_online/latest/trainer_prediction_current_record.json",
    "current_risk_decisions": PUBLIC_ROOT / "operator_runtime/paper_online/latest/current_risk_decisions.json",
    "paper_ledger_tail": PUBLIC_ROOT / "operator_runtime/paper_online/latest/paper_ledger_tail.json",
    "native_cuda_trainer": PUBLIC_ROOT
    / "v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json",
    "runtime_truth": PUBLIC_ROOT / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
    "balance_hold": PUBLIC_ROOT
    / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest/operator_dashboard_payload.json",
    "cuda_trainer_gate": PUBLIC_ROOT / "v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest/operator_dashboard_payload.json",
    "cuda_actionability": PUBLIC_ROOT / "v2_cuda_trainer_false_negative_reduction_and_actionability/latest/operator_dashboard_payload.json",
    "signal_publisher": PUBLIC_ROOT / "operator_runtime/v2_signal_publisher/latest/v2_signal_publisher_status.json",
    "signal_lineage_worker": PUBLIC_ROOT / "operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json",
    "orchestrator": PUBLIC_ROOT / "operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json",
    "risk_worker": PUBLIC_ROOT / "operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json",
    "trade_management": PUBLIC_ROOT / "operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json",
    "market_ingestor": PUBLIC_ROOT / "operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json",
    "feature_snapshot": PUBLIC_ROOT / "operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json",
    "feature_pipeline": PUBLIC_ROOT / "operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json",
    "technical_analysis": PUBLIC_ROOT / "operator_runtime/v2_technical_analysis_status/latest/v2_technical_analysis_status.json",
    "strategy_fallback": PUBLIC_ROOT / "operator_runtime/v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/v2_strategy_fallback_edge_comparison_status.json",
    "symbol_universe": PUBLIC_ROOT / "operator_runtime/symbol_universe/latest/symbol_universe_status.json",
    "dynamic_symbol_discovery": PUBLIC_ROOT / "operator_runtime/v2_dynamic_symbol_discovery/latest/dynamic_symbol_discovery_status.json",
}


def est_now() -> str:
    return dt.datetime.now(tz=EST).isoformat(timespec="seconds")


def parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def to_est(value: Any) -> str | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return parsed.astimezone(EST).isoformat(timespec="seconds")


def freshness_seconds(value: Any) -> int | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def strings(value: Any) -> list[str]:
    values: Iterable[Any]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    out: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("symbol") or item.get("canonical_symbol_id") or item.get("legacy_symbol")
        text = str(item or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def live_runtime_context(payloads: Mapping[str, Any]) -> dict[str, Any]:
    truth = as_dict(payloads.get("runtime_truth"))
    balance_hold = as_dict(payloads.get("balance_hold"))
    live_symbols = strings(truth.get("live_symbols")) or strings(balance_hold.get("accepted_symbols"))
    return {
        "live_gate": str(truth.get("live_gate") or balance_hold.get("live_gate") or DEFAULT_LIVE_GATE),
        "live_symbols": live_symbols,
        "execution_live_symbols": strings(truth.get("execution_live_symbols")) or live_symbols,
    }


def apply_live_runtime_context(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in context:
                value[key] = context[key]
            else:
                value[key] = apply_live_runtime_context(item, context)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = apply_live_runtime_context(item, context)
    return value


def timeframe_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def ordered_timeframes(values: Iterable[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for tf in list(REQUIRED_TIMEFRAMES) + list(values):
        if tf not in seen:
            seen.add(tf)
            ordered.append(tf)
    return ordered


def generated_field(payload: Mapping[str, Any]) -> Any:
    return (
        payload.get("generated_at")
        or payload.get("generated_utc")
        or payload.get("last_run_ts")
        or payload.get("heartbeat_at")
        or payload.get("last_prediction_ts")
    )


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def action_from_prediction(prediction: Mapping[str, Any], signal: Mapping[str, Any]) -> str:
    raw = as_dict(prediction.get("raw_output"))
    side = str(first_present(signal.get("side"), raw.get("side"), signal.get("proposed_action"), "hold")).lower()
    if "short" in side:
        return "short"
    if "long" in side or "buy" in side:
        return "long"
    return "hold"


def action_index(action: str) -> int:
    return {"hold": 0, "long": 1, "short": 2}.get(action, 0)


def action_probs(action: str, confidence: float | None) -> dict[str, float] | None:
    if confidence is None:
        return None
    conf = max(0.0, min(1.0, confidence))
    remainder = max(0.0, 1.0 - conf)
    if action == "long":
        return {"hold": round(remainder / 2, 6), "long": round(conf, 6), "short": round(remainder / 2, 6)}
    if action == "short":
        return {"hold": round(remainder / 2, 6), "long": round(remainder / 2, 6), "short": round(conf, 6)}
    return {"hold": round(conf, 6), "long": round(remainder / 2, 6), "short": round(remainder / 2, 6)}


def prediction_key(symbol: str, timeframe: str) -> str:
    return f"v2:prediction:{symbol}:{timeframe}"


def expected_move_lineage(
    *,
    row_status: str,
    trainer: Mapping[str, Any],
    risk: Mapping[str, Any],
    expected_move: float | None,
    expected_after_cost: float | None,
) -> dict[str, Any]:
    coverage = as_dict(risk.get("expected_move_coverage"))
    source = first_present(
        trainer.get("expected_move_source"),
        risk.get("expected_move_source"),
        coverage.get("expected_move_source"),
    )
    runtime_status = first_present(
        trainer.get("expected_move_runtime_status"),
        trainer.get("trainer_runtime_status"),
        risk.get("expected_move_coverage_status"),
        coverage.get("expected_move_coverage_status"),
    )
    if row_status == "MISSING_TF_PREDICTION":
        blocker = "MISSING_TF_PREDICTION"
    elif expected_move is None:
        blocker = str(runtime_status or "EXPECTED_MOVE_TELEMETRY_MISSING")
    elif expected_after_cost is None:
        blocker = "EXPECTED_MOVE_AFTER_COST_TELEMETRY_MISSING"
    else:
        blocker = None
    if expected_move is None:
        source_status = "MISSING_EXPECTED_MOVE_SOURCE"
    elif str(source or "").lower() in ("", "missing", "none", "null"):
        source_status = "EXPECTED_MOVE_PRESENT_SOURCE_LABEL_MISSING"
    else:
        source_status = "EXPECTED_MOVE_PRESENT"
    return {
        "expected_move_source": source or "missing",
        "expected_move_source_status": source_status,
        "expected_move_runtime_status": runtime_status or None,
        "expected_move_bps_source_field": "trainer_prediction.expected_move_bps or risk_decision.expected_move_bps",
        "expected_move_after_cost_bps_source_field": "trainer_prediction.expected_move_after_cost_bps or risk_decision.expected_move_after_cost_bps",
        "exact_blocker": blocker,
    }


def price_targets(last_price: float | None, expected_move: float | None, expected_after_cost: float | None, action: str) -> dict[str, Any]:
    formula = "price_target = last_price * (1 + expected_move_bps / 10000)"
    if last_price is None:
        return {
            "price_target": None,
            "price_target_after_cost": None,
            "price_target_low": None,
            "price_target_high": None,
            "formula": formula,
            "validation_status": "MISSING_LAST_PRICE",
        }
    if action == "hold":
        return {
            "price_target": None,
            "price_target_after_cost": None,
            "price_target_low": last_price,
            "price_target_high": last_price,
            "formula": formula,
            "validation_status": "HOLD_REFERENCE_ONLY",
        }
    if expected_move is None:
        return {
            "price_target": None,
            "price_target_after_cost": None,
            "price_target_low": None,
            "price_target_high": None,
            "formula": formula,
            "validation_status": "MISSING_EXPECTED_MOVE_BPS",
        }
    target = last_price * (1 + expected_move / 10000)
    after_cost_target = None if expected_after_cost is None else last_price * (1 + expected_after_cost / 10000)
    side_valid = (action == "long" and target >= last_price) or (action == "short" and target <= last_price)
    low = min(last_price, target)
    high = max(last_price, target)
    return {
        "price_target": round(target, 12),
        "price_target_after_cost": None if after_cost_target is None else round(after_cost_target, 12),
        "price_target_low": round(low, 12),
        "price_target_high": round(high, 12),
        "formula": formula,
        "validation_status": "VALID" if side_valid else "TARGET_SIDE_MISMATCH",
    }


def surface_inventory_row(
    *,
    surface_id: str,
    source_redis_key: str,
    publisher: str,
    path: Path,
    payload: Any,
    symbols: list[str],
    timeframes: list[str],
    stale_threshold: int,
    missing_reason: str = "",
) -> dict[str, Any]:
    body = as_dict(payload)
    ts = generated_field(body)
    age = freshness_seconds(ts)
    missing = missing_reason
    if payload is None:
        missing = "MISSING_PAYLOAD"
    elif age is None:
        missing = "MISSING_TIMESTAMP"
    elif age > stale_threshold:
        missing = f"STALE_GT_{stale_threshold}s"
    return {
        "surface_id": surface_id,
        "source_redis_key": source_redis_key,
        "publisher_process_service": publisher,
        "payload_path": rel(path),
        "freshness_seconds": age,
        "symbols_covered": symbols,
        "timeframes_covered": timeframes,
        "missing_stale_reason": missing or None,
        "source_type": body.get("source_type") or body.get("runtime_evidence_status") or body.get("classification") or "PUBLIC_RUNTIME_PAYLOAD",
        "generated_est": to_est(ts),
    }


def build_runtime_inventory(payloads: Mapping[str, Any], symbols: list[str], timeframes: list[str], stale_threshold: int) -> dict[str, Any]:
    active_symbol = symbols[:1]
    rows = [
        surface_inventory_row(
            surface_id="trainer_training_status",
            source_redis_key="v2:trainer:training:status",
            publisher="v2_trainer_training_live_loop",
            path=PATHS["native_cuda_trainer"],
            payload=payloads.get("native_cuda_trainer"),
            symbols=active_symbol,
            timeframes=timeframes,
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="cuda_trainer_status",
            source_redis_key="v2:cuda_trainer:status",
            publisher="v2_native_cuda_trainer_edge_calibration_outcome_burn_in",
            path=PATHS["cuda_trainer_gate"],
            payload=payloads.get("cuda_trainer_gate"),
            symbols=symbols,
            timeframes=timeframes,
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="trainer_predictions",
            source_redis_key="v2:prediction:{symbol}:{timeframe}",
            publisher="paper_online_runtime / native_cuda_trainer",
            path=PATHS["trainer_prediction_record"],
            payload=payloads.get("trainer_prediction_record"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="prediction_price_targets",
            source_redis_key="v2:prediction_targets:{symbol}:{timeframe}",
            publisher=SERVICE_ID,
            path=PUBLIC_OUT / "price_target_generation_status.json",
            payload={"generated_at": est_now()},
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
            missing_reason="EXPECTED_MOVE_MISSING" if as_dict(payloads.get("trainer_prediction_record")).get("expected_move_bps") is None else "",
        ),
        surface_inventory_row(
            surface_id="signal_publisher",
            source_redis_key="v2:signals:paper:{symbol}:{timeframe}; v2:signals:latest:{symbol}",
            publisher="v2_signal_publisher",
            path=PATHS["current_signal_lineage"],
            payload=payloads.get("current_signal_lineage"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="risk_decisions",
            source_redis_key="v2:risk:decisions",
            publisher="v2_risk_gateway_runtime_worker / paper_online_runtime",
            path=PATHS["current_risk_decisions"],
            payload=payloads.get("current_risk_decisions"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="orchestrator_decisions",
            source_redis_key="v2:orchestrator:decisions",
            publisher="v2_orchestrator_arbitration / paper_online_runtime",
            path=PATHS["orchestrator"],
            payload=payloads.get("orchestrator"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="paper_intents",
            source_redis_key="v2:paper:intents",
            publisher="paper_online_runtime",
            path=PATHS["current_signal_lineage"],
            payload=payloads.get("current_signal_lineage"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="paper_ledger",
            source_redis_key="v2:paper:ledger",
            publisher="paper_online_runtime",
            path=PATHS["paper_ledger_tail"],
            payload=payloads.get("paper_ledger_tail"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="signal_lineage",
            source_redis_key="v2:signal_lineage:{symbol}",
            publisher="v2_signal_lineage_worker / paper_online_runtime",
            path=PATHS["current_signal_lineage"],
            payload=payloads.get("current_signal_lineage"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="market_prices",
            source_redis_key="v2:market:prices:{symbol}",
            publisher="paper_online_runtime market_feed",
            path=PATHS["paper_runtime"],
            payload=payloads.get("paper_runtime"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="ohlcv",
            source_redis_key="v2:market:ohlcv:{symbol}:{timeframe}",
            publisher="paper_online_runtime market_feed / v2_market_ingestor",
            path=PATHS["paper_runtime"],
            payload=payloads.get("paper_runtime"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="ta",
            source_redis_key="v2:ta:{symbol}:{timeframe}",
            publisher="v2_technical_analysis_status / v2_feature_pipeline_native",
            path=PATHS["technical_analysis"],
            payload=payloads.get("technical_analysis"),
            symbols=active_symbol,
            timeframes=["1m"],
            stale_threshold=stale_threshold,
            missing_reason="MISSING_TA_PAYLOAD" if payloads.get("technical_analysis") is None else "",
        ),
        surface_inventory_row(
            surface_id="feature_snapshots",
            source_redis_key="v2:features:snapshot:{symbol}:{timeframe}",
            publisher="v2_feature_pipeline_native / paper_online_runtime",
            path=PATHS["feature_snapshot"],
            payload=payloads.get("feature_snapshot"),
            symbols=strings(as_dict(payloads.get("feature_snapshot")).get("symbol")) or active_symbol,
            timeframes=timeframe_values(as_dict(payloads.get("feature_snapshot")).get("timeframe")) or ["1m"],
            stale_threshold=stale_threshold,
        ),
        surface_inventory_row(
            surface_id="strategy_fallback_signals",
            source_redis_key="v2:strategy:fallback_signals:{symbol}:{timeframe}",
            publisher="v2_strategy_fallback_edge_comparison_status",
            path=PATHS["strategy_fallback"],
            payload=payloads.get("strategy_fallback"),
            symbols=symbols,
            timeframes=timeframes,
            stale_threshold=stale_threshold,
            missing_reason="MISSING_STRATEGY_FALLBACK_STATUS" if payloads.get("strategy_fallback") is None else "",
        ),
        surface_inventory_row(
            surface_id="dynamic_symbol_discovery",
            source_redis_key="v2:symbols:dynamic",
            publisher="v2_dynamic_symbol_discovery",
            path=PATHS["dynamic_symbol_discovery"],
            payload=payloads.get("dynamic_symbol_discovery"),
            symbols=strings(as_dict(payloads.get("dynamic_symbol_discovery")).get("dynamic_discovered_symbols")) or symbols,
            timeframes=timeframes,
            stale_threshold=stale_threshold,
            missing_reason="MISSING_DYNAMIC_SYMBOL_DISCOVERY_STATUS" if payloads.get("dynamic_symbol_discovery") is None else "",
        ),
    ]
    return {
        "schema_version": "v2_realtime_signal_runtime_source_inventory_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "surfaces": rows,
        "missing_or_stale_count": sum(1 for row in rows if row["missing_stale_reason"]),
    }


def covered_symbols(payloads: Mapping[str, Any]) -> list[str]:
    paper = as_dict(payloads.get("paper_runtime"))
    trainer = as_dict(payloads.get("trainer_prediction_record")) or as_dict(paper.get("trainer_prediction"))
    signal = as_dict(as_dict(as_dict(payloads.get("current_signal_lineage")).get("signal")))
    market = as_dict(paper.get("market_feed"))
    universe = as_dict(payloads.get("symbol_universe"))
    dynamic = as_dict(payloads.get("dynamic_symbol_discovery"))
    active = strings(
        [
            market.get("symbol"),
            trainer.get("symbol"),
            signal.get("symbol"),
        ]
    )
    universe_symbols = strings(
        universe.get("paper_symbols")
        or universe.get("training_symbols")
        or universe.get("dynamic_discovered_symbols")
        or universe.get("symbols")
        or dynamic.get("paper_symbols")
        or dynamic.get("training_symbols")
        or dynamic.get("dynamic_discovered_symbols")
        or dynamic.get("symbols")
    )
    return sorted(set(active + universe_symbols)) or ["missing source"]


def build_prediction_rows(payloads: Mapping[str, Any], symbols: list[str], timeframes: list[str]) -> list[dict[str, Any]]:
    paper = as_dict(payloads.get("paper_runtime"))
    lineage = as_dict(payloads.get("current_signal_lineage") or paper.get("current_signal_lineage"))
    trainer = as_dict(payloads.get("trainer_prediction_record") or paper.get("trainer_prediction"))
    risk = as_dict(as_dict(lineage.get("risk_decision")) or paper.get("current_risk_decision"))
    signal = as_dict(lineage.get("signal"))
    feature = as_dict(lineage.get("feature_snapshot") or paper.get("feature_snapshot"))
    market = as_dict(paper.get("market_feed"))
    trainer_symbol = str(first_present(trainer.get("symbol"), market.get("symbol"), signal.get("symbol"), "")).upper()
    trainer_tf = str(first_present(trainer.get("timeframe"), "1m"))
    confidence_calibrated = to_float(first_present(trainer.get("confidence_calibrated"), signal.get("confidence_calibrated")))
    confidence_raw = to_float(trainer.get("confidence_raw"))
    expected_move = to_float(first_present(trainer.get("expected_move_bps"), risk.get("expected_move_bps")))
    expected_after_cost = to_float(first_present(trainer.get("expected_move_after_cost_bps"), risk.get("expected_move_after_cost_bps")))
    last_price = to_float(market.get("price")) if str(market.get("symbol", "")).upper() == trainer_symbol else None
    action = action_from_prediction(trainer, signal)
    targets = price_targets(last_price, expected_move, expected_after_cost, action)
    generated = first_present(trainer.get("generated_at"), signal.get("generated_at"), paper.get("generated_at"))
    missing_feature_flags = as_list(first_present(feature.get("missing_feature_flags"), trainer.get("missing_feature_flags"), []))
    stale_feature_flags = as_list(first_present(feature.get("stale_feature_flags"), trainer.get("stale_feature_flags"), []))
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for tf in timeframes:
            is_current = symbol == trainer_symbol and tf == trainer_tf and bool(trainer.get("prediction_id"))
            if is_current:
                source_lineage = {
                    "prediction_redis_key": prediction_key(symbol, tf),
                    "prediction_source_path": rel(PATHS["trainer_prediction_record"]),
                    "paper_runtime_source_path": rel(PATHS["paper_runtime"]),
                    "risk_source_path": rel(PATHS["current_risk_decisions"]),
                    "feature_snapshot_source_path": rel(PATHS["feature_snapshot"]),
                    "lineage_source_path": rel(PATHS["current_signal_lineage"]),
                    "trainer_prediction_id": trainer.get("prediction_id"),
                    "risk_decision_id": risk.get("risk_decision_id"),
                    "orchestrator_decision_id": as_dict(lineage.get("orchestrator_decision")).get("orchestrator_decision_id"),
                    "paper_intent_id": as_dict(lineage.get("execution_intent")).get("execution_intent_id"),
                    "paper_ledger_id": first_present(
                        as_dict((as_list(paper.get("paper_ledger_tail")) or [{}])[0]).get("paper_ledger_entry_id"),
                        None,
                    ),
                    **expected_move_lineage(
                        row_status="PRESENT_CURRENT",
                        trainer=trainer,
                        risk=risk,
                        expected_move=expected_move,
                        expected_after_cost=expected_after_cost,
                    ),
                }
                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": tf,
                        "prediction_redis_key": prediction_key(symbol, tf),
                        "status": "PRESENT_CURRENT",
                        "generated_est": to_est(generated),
                        "trainer_source": trainer.get("trainer_source") or trainer.get("source_type") or "missing source",
                        "model_source": trainer.get("model_checkpoint") or trainer.get("model_version") or "missing source",
                        "selected_action": action,
                        "selected_action_index": action_index(action),
                        "action_probabilities": action_probs(action, confidence_calibrated),
                        "confidence_raw": confidence_raw,
                        "confidence_calibrated": confidence_calibrated,
                        "expected_move_bps": expected_move,
                        "expected_move_after_cost_bps": expected_after_cost,
                        "last_price": last_price,
                        "price_target": targets["price_target"],
                        "price_target_low": targets["price_target_low"],
                        "price_target_high": targets["price_target_high"],
                        "stop_reference": None,
                        "take_profit_reference": targets["price_target_after_cost"],
                        "feature_snapshot_id": trainer.get("feature_snapshot_id") or feature.get("feature_snapshot_id"),
                        "data_coverage_percent": 100.0 if not missing_feature_flags else max(0.0, 100.0 - len(missing_feature_flags)),
                        "missing_feature_count": len(missing_feature_flags),
                        "stale_feature_count": len(stale_feature_flags),
                        "prediction_id": trainer.get("prediction_id"),
                        "freshness_seconds": freshness_seconds(generated),
                        "missing_stale_reason": None,
                        "implementation_task": None,
                        "source_lineage": source_lineage,
                        "live_gate": DEFAULT_LIVE_GATE,
                        "live_symbols": [],
                        "execution_live_symbols": [],
                    }
                )
            else:
                source_lineage = {
                    "prediction_redis_key": prediction_key(symbol, tf),
                    "prediction_source_path": rel(PATHS["trainer_prediction_record"]),
                    "paper_runtime_source_path": rel(PATHS["paper_runtime"]),
                    "required_source_key": prediction_key(symbol, tf),
                    **expected_move_lineage(
                        row_status="MISSING_TF_PREDICTION",
                        trainer={},
                        risk={},
                        expected_move=None,
                        expected_after_cost=None,
                    ),
                }
                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": tf,
                        "prediction_redis_key": prediction_key(symbol, tf),
                        "status": "MISSING_TF_PREDICTION",
                        "generated_est": est_now(),
                        "trainer_source": "missing source",
                        "model_source": "missing source",
                        "selected_action": None,
                        "selected_action_index": None,
                        "action_probabilities": None,
                        "confidence_raw": None,
                        "confidence_calibrated": None,
                        "expected_move_bps": None,
                        "expected_move_after_cost_bps": None,
                        "last_price": to_float(market.get("price")) if str(market.get("symbol", "")).upper() == symbol else None,
                        "price_target": None,
                        "price_target_low": None,
                        "price_target_high": None,
                        "stop_reference": None,
                        "take_profit_reference": None,
                        "feature_snapshot_id": None,
                        "data_coverage_percent": 0.0,
                        "missing_feature_count": None,
                        "stale_feature_count": None,
                        "prediction_id": None,
                        "freshness_seconds": None,
                        "missing_stale_reason": "MISSING_TF_PREDICTION",
                        "implementation_task": f"Produce trainer prediction contract for {symbol} {tf} with prediction_id, feature_snapshot_id, calibrated confidence, expected_move_bps, and price target.",
                        "source_lineage": source_lineage,
                        "live_gate": DEFAULT_LIVE_GATE,
                        "live_symbols": [],
                        "execution_live_symbols": [],
                    }
                )
    return rows


def build_prediction_status(rows: list[dict[str, Any]], symbols: list[str], timeframes: list[str]) -> dict[str, Any]:
    missing = [row for row in rows if row["status"] == "MISSING_TF_PREDICTION"]
    present = [row for row in rows if row["status"] != "MISSING_TF_PREDICTION"]
    return {
        "schema_version": "v2_realtime_prediction_all_tf_contract_status_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "timeframes_covered": timeframes,
        "symbols_covered": symbols,
        "prediction_rows": rows,
        "present_prediction_count": len(present),
        "missing_prediction_count": len(missing),
        "status": "MISSING_TF_PREDICTION" if missing else "ALL_TF_PREDICTIONS_PRESENT",
        "implementation_tasks": sorted({row["implementation_task"] for row in missing if row.get("implementation_task")}),
    }


def build_price_target_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_rows = []
    for row in rows:
        source_price_key = f"v2:market:prices:{row['symbol']}"
        source_prediction_key = f"v2:prediction:{row['symbol']}:{row['timeframe']}"
        targets = price_targets(
            to_float(row.get("last_price")),
            to_float(row.get("expected_move_bps")),
            to_float(row.get("expected_move_after_cost_bps")),
            str(row.get("selected_action") or "hold"),
        )
        target_rows.append(
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "source_price_key": source_price_key,
                "source_prediction_key": source_prediction_key,
                "generated_est": row.get("generated_est") or est_now(),
                "formula": targets["formula"],
                "selected_action": row.get("selected_action"),
                "last_price": row.get("last_price"),
                "expected_move_bps": row.get("expected_move_bps"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "price_target": targets["price_target"],
                "price_target_after_cost": targets["price_target_after_cost"],
                "validation_status": "MISSING_TF_PREDICTION" if row["status"] == "MISSING_TF_PREDICTION" else targets["validation_status"],
            }
        )
    invalid = [row for row in target_rows if row["validation_status"] != "VALID"]
    return {
        "schema_version": "v2_price_target_generation_status_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "formula": "price_target = last_price * (1 + expected_move_bps / 10000); price_target_after_cost = last_price * (1 + expected_move_after_cost_bps / 10000)",
        "target_rows": target_rows,
        "validation_status": "PRICE_TARGETS_BLOCKED_OR_PARTIAL" if invalid else "PRICE_TARGETS_VALID",
        "invalid_or_missing_count": len(invalid),
    }


def active_signal(payloads: Mapping[str, Any], prediction_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    paper = as_dict(payloads.get("paper_runtime"))
    lineage = as_dict(payloads.get("current_signal_lineage") or paper.get("current_signal_lineage"))
    ids = as_dict(lineage.get("lineage_ids"))
    signal = as_dict(lineage.get("signal"))
    risk = as_dict(lineage.get("risk_decision") or paper.get("current_risk_decision"))
    orch = as_dict(lineage.get("orchestrator_decision"))
    intent = as_dict(lineage.get("execution_intent"))
    ledger = as_list(paper.get("paper_ledger_tail") or as_dict(payloads.get("paper_ledger_tail")).get("entries"))
    row = next((item for item in prediction_rows if item["status"] == "PRESENT_CURRENT"), None)
    if row is None and not signal:
        return None
    ledger_entry = as_dict(ledger[0] if ledger else {})
    symbol = str(first_present(row and row.get("symbol"), signal.get("symbol"), intent.get("symbol"), "")).upper()
    timeframe = str(first_present(row and row.get("timeframe"), "1m"))
    risk_state = str(first_present(risk.get("risk_result"), risk.get("risk_action"), "missing telemetry field"))
    blocked_reason = None
    if "BLOCK" in risk_state.upper() or str(risk.get("risk_action")).lower() == "deny":
        blocked_reason = first_present(risk.get("risk_reason_code"), ledger_entry.get("paper_result"), "risk/orchestrator/paper blocker missing")
    return {
        "signal_id": first_present(signal.get("signal_id"), ids.get("signal_id"), ledger_entry.get("signal_id"), "missing telemetry field"),
        "prediction_id": first_present(signal.get("prediction_id"), ids.get("prediction_id"), row and row.get("prediction_id"), "missing telemetry field"),
        "risk_decision_id": first_present(risk.get("risk_decision_id"), ids.get("risk_decision_id"), ledger_entry.get("risk_decision_id"), "missing telemetry field"),
        "orchestrator_decision_id": first_present(orch.get("orchestrator_decision_id"), ids.get("orchestrator_decision_id"), "missing telemetry field"),
        "symbol": symbol or "missing telemetry field",
        "timeframe": timeframe,
        "action": first_present(signal.get("proposed_action"), row and row.get("selected_action"), "missing telemetry field"),
        "price_target": row.get("price_target") if row else None,
        "confidence": first_present(signal.get("confidence_calibrated"), row and row.get("confidence_calibrated"), None),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps") if row else None,
        "risk_state": risk_state,
        "orchestrator_state": first_present(orch.get("decision_action"), orch.get("decision_reason"), "missing telemetry field"),
        "paper_state": first_present(ledger_entry.get("paper_result"), ledger_entry.get("ledger_action"), intent.get("intent_action"), "missing telemetry field"),
        "reason": first_present(signal.get("explanation"), risk.get("risk_reason_code"), "missing telemetry field"),
        "blocked_reason": blocked_reason,
        "generated_est": to_est(first_present(signal.get("generated_at"), risk.get("generated_at"), paper.get("generated_at"))) or est_now(),
        "lineage_ids": {
            "trainer_prediction_id": first_present(ids.get("prediction_id"), row and row.get("prediction_id")),
            "risk_decision_id": first_present(ids.get("risk_decision_id"), risk.get("risk_decision_id")),
            "orchestrator_decision_id": first_present(ids.get("orchestrator_decision_id"), orch.get("orchestrator_decision_id")),
            "paper_intent_id": first_present(ids.get("execution_intent_id"), intent.get("execution_intent_id")),
            "paper_ledger_id": first_present(ids.get("paper_ledger_entry_id"), ledger_entry.get("paper_ledger_entry_id")),
        },
    }


def build_signal_publisher_status(payloads: Mapping[str, Any], prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    signal = active_signal(payloads, prediction_rows)
    intended_keys: list[str] = []
    if signal:
        intended_keys = [
            f"v2:signals:paper:{signal['symbol']}:{signal['timeframe']}",
            f"v2:signals:latest:{signal['symbol']}",
        ]
    return {
        "schema_version": "v2_realtime_signal_publisher_status_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "publish_contract": {
            "redis_writes_performed": False,
            "old_redis_writes_performed": False,
            "no_live_order_keys": True,
            "intended_v2_redis_keys": intended_keys,
            "public_payload": "operator_runtime/v2_signals/latest/signals_payload.json",
        },
        "published_signals": [signal] if signal else [],
        "signal_count": 1 if signal else 0,
        "missing_timeframe_prediction_count": sum(1 for row in prediction_rows if row["status"] == "MISSING_TF_PREDICTION"),
        "status": "PUBLIC_SIGNAL_PAYLOAD_READY" if signal else "NO_ACTIVE_SIGNAL_VISIBLE",
    }


def build_lineage_status(payloads: Mapping[str, Any], signal_status: Mapping[str, Any]) -> dict[str, Any]:
    signals = as_list(signal_status.get("published_signals"))
    rows: list[dict[str, Any]] = []
    for signal in signals:
        item = as_dict(signal)
        ids = as_dict(item.get("lineage_ids"))
        checks = {
            "trainer_prediction_exists": bool(ids.get("trainer_prediction_id")),
            "risk_decision_exists": bool(ids.get("risk_decision_id")),
            "orchestrator_decision_exists": bool(ids.get("orchestrator_decision_id")),
            "paper_intent_exists": bool(ids.get("paper_intent_id")),
            "paper_ledger_exists": bool(ids.get("paper_ledger_id")),
        }
        blockers = [
            name.replace("_exists", "_missing").upper()
            for name, ok in checks.items()
            if not ok
        ]
        rows.append(
            {
                "signal_id": item.get("signal_id"),
                "symbol": item.get("symbol"),
                "timeframe": item.get("timeframe"),
                **checks,
                "lineage_ids": ids,
                "required_lineage": "trainer_prediction_id -> risk_decision_id -> orchestrator_decision_id -> paper_intent_id -> paper_ledger_id",
                "exact_blocker": blockers[0] if blockers else None,
                "implementation_task": None if not blockers else f"Repair active signal lineage links: {', '.join(blockers)}",
            }
        )
    return {
        "schema_version": "v2_realtime_signal_lineage_status_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "lineage_rows": rows,
        "chain_complete_count": sum(1 for row in rows if not row.get("exact_blocker")),
        "missing_lineage_count": sum(1 for row in rows if row.get("exact_blocker")),
        "status": "LINEAGE_VISIBLE" if rows else "NO_ACTIVE_SIGNAL_VISIBLE",
    }


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def local_bundle_hash() -> tuple[str | None, list[str]]:
    assets = sorted((V2_ROOT / "frontend" / "dist" / "assets").glob("*")) if (V2_ROOT / "frontend" / "dist" / "assets").exists() else []
    hashes = [sha256_file(path) for path in assets if path.is_file()]
    hashes = [value for value in hashes if value]
    if not hashes:
        return None, []
    joined = "\n".join(hashes).encode("utf-8")
    return hashlib.sha256(joined).hexdigest(), [rel(path) for path in assets[:20]]


def fetch_route_hash(base_url: str, route: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{route}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "v2-realtime-signal-visibility/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read(2_000_000)
            return {
                "route": route,
                "url": url,
                "http_status": getattr(response, "status", None),
                "content_hash": hashlib.sha256(body).hexdigest(),
                "content_length": len(body),
                "error": None,
            }
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"route": route, "url": url, "http_status": None, "content_hash": None, "content_length": None, "error": str(exc)}


def build_deployment_truth(routes: list[str], production_base_url: str) -> dict[str, Any]:
    bundle_hash, bundle_assets = local_bundle_hash()
    production_rows = [fetch_route_hash(production_base_url, route) for route in routes]
    public_payload_hash = sha256_file(PUBLIC_OUT / "signals_payload.json")
    production_fetch_errors = [row for row in production_rows if row.get("error")]
    status = "PRODUCTION_FETCH_UNAVAILABLE" if production_fetch_errors else "PRODUCTION_HASH_CAPTURED"
    if bundle_hash and production_rows and not production_fetch_errors:
        status = "DEPLOYMENT_STALE_REQUIRES_ROUTE_VERIFICATION"
    return {
        "schema_version": "v2_website_deployment_truth_status_v1",
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": DEFAULT_LIVE_GATE,
        "local_dev_server_bundle_hash": bundle_hash,
        "local_bundle_assets_sample": bundle_assets,
        "production_base_url": production_base_url,
        "production_route_hashes": production_rows,
        "public_payload_path": rel(PUBLIC_OUT / "signals_payload.json"),
        "public_payload_hash": public_payload_hash,
        "route_screenshots_available": False,
        "status": status,
        "deploy_build_command_path": "cd v2/frontend && npm run build:realtime-signals && npm run build; deploy the generated v2/frontend/dist bundle to dashboard.wajidali.us; then run PRODUCTION_CRAWL_BASE_URL=https://dashboard.wajidali.us npm run crawl:production-website",
        "claim_scope": "local artifacts ready; production fixed only after dashboard.wajidali.us serves matching updated routes",
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    payloads = {name: read_json(path) for name, path in PATHS.items()}
    live_context = live_runtime_context(payloads)
    symbols = covered_symbols(payloads)
    timeframes = ordered_timeframes(REQUIRED_TIMEFRAMES)
    prediction_rows = build_prediction_rows(payloads, symbols, timeframes)
    inventory = build_runtime_inventory(payloads, symbols, timeframes, int(args.stale_threshold_seconds))
    prediction_status = build_prediction_status(prediction_rows, symbols, timeframes)
    price_status = build_price_target_status(prediction_rows)
    publisher_status = build_signal_publisher_status(payloads, prediction_rows)
    lineage_status = build_lineage_status(payloads, publisher_status)
    deployment_truth = build_deployment_truth(list(args.routes), str(args.production_base_url))
    safety = {
        "live_gate": DEFAULT_LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "writes_exchange_orders": False,
        "writes_legacy_redis": False,
        "redis_trim_performed": False,
        "test_order_endpoint_called": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "raw_credentials_exposed": False,
    }
    result = {
        "schema_version": "v2_realtime_trainer_signal_price_target_all_tf_visibility_v1",
        "worker_id": WORKER_ID,
        "service_id": SERVICE_ID,
        "generated_at": est_now(),
        "generated_est": est_now(),
        "safety": safety,
        "runtime_source_inventory": inventory,
        "prediction_contract": prediction_status,
        "price_target_generation": price_status,
        "signal_publisher": publisher_status,
        "signal_lineage": lineage_status,
        "website_deployment_truth": deployment_truth,
        "summary": {
            "symbols_count": len(symbols),
            "timeframes_count": len(timeframes),
            "prediction_rows_count": len(prediction_rows),
            "present_prediction_count": prediction_status["present_prediction_count"],
            "missing_prediction_count": prediction_status["missing_prediction_count"],
            "active_signal_count": publisher_status["signal_count"],
            "live_gate": DEFAULT_LIVE_GATE,
        },
    }
    return apply_live_runtime_context(result, live_context)


def write_outputs(payload: Mapping[str, Any]) -> None:
    files = {
        "signals_payload.json": payload,
        "realtime_signal_runtime_source_inventory.json": payload["runtime_source_inventory"],
        "realtime_prediction_all_tf_contract_status.json": payload["prediction_contract"],
        "price_target_generation_status.json": payload["price_target_generation"],
        "realtime_signal_publisher_status.json": payload["signal_publisher"],
        "realtime_signal_lineage_status.json": payload["signal_lineage"],
        "website_deployment_truth_status.json": payload["website_deployment_truth"],
    }
    for base in (PUBLIC_OUT, LOCAL_OUT):
        for filename, body in files.items():
            write_json(base / filename, body)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--stale-threshold-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--production-base-url", default="https://dashboard.wajidali.us")
    parser.add_argument(
        "--routes",
        nargs="*",
        default=[
            "/ai-predictions",
            "/signals",
            "/trade",
            "/derivatives",
            "/backtests",
            "/system/trainer",
            "/system/orchestrator",
            "/system/risk-controllers",
            "/system/execution",
            "/system/readiness",
        ],
    )
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(args)
    if not args.no_write:
        write_outputs(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
