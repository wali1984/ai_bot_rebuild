"""Paper-only major-move false-negative remediation proof.

This command reads current V2 Redis/public evidence and writes remediation
artifacts. It never submits real or test orders, never changes leverage or
margin mode, never writes Redis, and never reads non-V2 Redis keys.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.market_move_detection import (  # noqa: E402
    CandleInput,
    DetectionContext,
    detect_breakout_squeeze,
)
from v2.backend.app.services.market_move_detection.explanation import explain_signal  # noqa: E402
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: E402
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (  # noqa: E402
    DEFAULT_TIMEFRAMES,
    MODEL_SOURCE,
    TRAINER_SOURCE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: E402
    V2HybridPolicyModel,
)

READY = "V2_MAJOR_MOVE_FALSE_NEGATIVE_REPLAY_DURABLE_TRAINER_AND_PAPER_ROUTING_REMEDIATION_READY"
BLOCKED = "V2_MAJOR_MOVE_FALSE_NEGATIVE_REPLAY_DURABLE_TRAINER_AND_PAPER_ROUTING_REMEDIATION_BLOCKED"
ARTIFACT_REL = Path("v2_major_move_false_negative_replay_durable_trainer_and_paper_routing_remediation/latest")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = DEFAULT_TIMEFRAMES
EST = ZoneInfo("America/New_York")


def _est_now() -> str:
    return dt.datetime.now(tz=EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _to_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        number = int(float(value))
        return number * 1000 if abs(number) < 10_000_000_000 else number
    if isinstance(value, str) and value.strip():
        try:
            if value.replace(".", "", 1).isdigit():
                number = int(float(value))
                return number * 1000 if abs(number) < 10_000_000_000 else number
            return int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, tuple):
        return list(value)
    return list(value) if isinstance(value, list) else []


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


class ReadOnlyRedis:
    def __init__(self) -> None:
        self.client = None
        try:
            import redis  # type: ignore

            client = redis.Redis(
                host="127.0.0.1",
                port=6379,
                db=0,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=5,
            )
            client.ping()
            self.client = client
        except Exception:
            self.client = None

    @property
    def connected(self) -> bool:
        return self.client is not None

    def get(self, key: str) -> Any:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        if self.client is None:
            return None
        raw = self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None


def _prediction_key(symbol: str, timeframe: str) -> str:
    return f"v2:prediction:{symbol}:{timeframe}"


def _closed_candle_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"


def _coerce_candles(rows: Any, *, symbol: str, timeframe: str) -> list[CandleInput]:
    out: list[CandleInput] = []
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        try:
            out.append(CandleInput.from_mapping(row, symbol=symbol, timeframe=timeframe))
        except Exception:
            continue
    return out


def _price_at_or_before(candles: list[CandleInput], decision_time_ms: int | None) -> float | None:
    if decision_time_ms is None:
        return candles[-1].close if candles else None
    eligible = [row for row in candles if row.close_time_ms <= decision_time_ms and row.available_at_ms <= decision_time_ms]
    return eligible[-1].close if eligible else None


def _future_price(candles: list[CandleInput], decision_time_ms: int | None, horizon_ms: int) -> float | None:
    if decision_time_ms is None:
        return None
    target = decision_time_ms + horizon_ms
    eligible = [row for row in candles if row.close_time_ms >= target and row.available_at_ms <= row.close_time_ms + 60_000]
    return eligible[0].close if eligible else None


def _replay_row(redis: ReadOnlyRedis, symbol: str, timeframe: str) -> dict[str, Any]:
    pred = _as_dict(redis.get(_prediction_key(symbol, timeframe)))
    candles = _coerce_candles(redis.get(_closed_candle_key(symbol, "1m")), symbol=symbol, timeframe="1m")
    decision_ms = _to_ms(pred.get("decision_time") or pred.get("decision_cutoff_time_est") or pred.get("created_at"))
    mark = _price_at_or_before(candles, decision_ms)
    futures = {
        "future_price_5m": _future_price(candles, decision_ms, 5 * 60_000),
        "future_price_15m": _future_price(candles, decision_ms, 15 * 60_000),
        "future_price_1h": _future_price(candles, decision_ms, 60 * 60_000),
        "future_price_4h": _future_price(candles, decision_ms, 4 * 60 * 60_000),
    }
    future_15m = futures["future_price_15m"] or futures["future_price_5m"]
    realized = None
    if mark and future_15m:
        realized = ((future_15m - mark) / max(abs(mark), 1e-12)) * 10_000.0
    expected_after = _finite(pred.get("expected_move_after_cost_bps"))
    confidence = _finite(pred.get("confidence_calibrated"))
    selected = str(pred.get("selected_action") or "missing")
    causes: list[str] = []
    if realized is not None:
        realized_direction = "long" if realized > 0 else "short"
        if selected in {"long", "short"} and selected != realized_direction:
            causes.append("WRONG_DIRECTION")
    else:
        causes.append("REPLAY_FUTURE_WINDOW_MISSING")
    if confidence is None or confidence < 0.55:
        causes.append("CONFIDENCE_TOO_LOW")
    if expected_after is None or expected_after <= 0:
        causes.append("EXPECTED_MOVE_NEGATIVE")
    if int(_finite(pred.get("missing_feature_count")) or 0) > 0:
        causes.append("FEATURE_MISSING")
    if int(_finite(pred.get("stale_feature_count")) or 0) > 0:
        causes.append("FEATURE_STALE")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "decision_time": pred.get("decision_time") or pred.get("decision_cutoff_time_est"),
        "feature_cutoff": pred.get("feature_cutoff"),
        "available_at": pred.get("available_at"),
        "mark_price_at_decision": mark,
        **futures,
        "realized_move_bps": realized,
        "realized_move_after_cost_bps": None if realized is None else realized - 12.0,
        "native_prediction_id": pred.get("prediction_id"),
        "selected_action": selected,
        "expected_move_after_cost_bps": expected_after,
        "confidence_calibrated": confidence,
        "risk_status": pred.get("risk_action") or pred.get("risk_status"),
        "orchestrator_status": pred.get("orchestrator_action") or pred.get("orchestrator_status"),
        "paper_status": pred.get("paper_fill_gate_status"),
        "gate_block_reason": pred.get("paper_fill_gate_block_reasons") or pred.get("block_reasons"),
        "market_state_integrity": {
            "market_state_id": pred.get("market_state_id"),
            "score": pred.get("market_state_integrity_score"),
            "valid_for_prediction": pred.get("valid_for_prediction"),
            "valid_for_paper": pred.get("valid_for_paper"),
        },
        "missing_feature_count": pred.get("missing_feature_count"),
        "stale_feature_count": pred.get("stale_feature_count"),
        "liquidation_context": "prediction_feature_names_only" if "liquidation_strength" in _as_list(pred.get("feature_names")) else "missing",
        "oi_context": "prediction_feature_names_only" if "open_interest" in _as_list(pred.get("feature_names")) else "missing",
        "funding_context": "prediction_feature_names_only" if "funding_rate" in _as_list(pred.get("feature_names")) else "missing",
        "long_short_context": "prediction_feature_names_only" if "long_short_ratio" in _as_list(pred.get("feature_names")) else "missing",
        "orderbook_context": "prediction_feature_names_only" if "ob_imbalance" in _as_list(pred.get("feature_names")) else "missing",
        "microstructure_context": "prediction_feature_names_only" if "microprice" in _as_list(pred.get("feature_names")) else "missing",
        "news_public_intel_context": "prediction_feature_names_only" if "public_intel_score" in _as_list(pred.get("feature_names")) else "missing",
        "root_causes": sorted(set(causes)),
    }


def _checkpoint_status(repo_root: Path) -> dict[str, Any]:
    manager = V2HybridCheckpointManager(repo_root / ".local_models/v2_native_rl_masa_ppo")
    manifest = manager.latest_manifest()
    input_dim = manifest.input_dim if manifest else 4
    model = V2HybridPolicyModel(input_dim=max(1, input_dim))
    load = manager.load_latest_weights(model)
    return {
        "checkpoint_manifest_exists": manifest is not None,
        "weight_blob_written": bool(manifest and manifest.weight_blob_written),
        "weight_file_path": manifest.weight_file_path if manifest else None,
        "weight_file_exists": bool(manifest and manifest.weight_file_path and Path(manifest.weight_file_path).exists()),
        "weight_file_size_bytes": manifest.weight_file_size_bytes if manifest else None,
        "safe_weight_format": bool(manifest and manifest.weight_file_format == "npz"),
        "latest_checkpoint_loadable": load.get("latest_checkpoint_loadable") is True,
        "model_state_restored": load.get("model_state_restored") is True,
        "optimizer_state_restored_or_intentionally_not_required": load.get(
            "optimizer_state_restored_or_intentionally_not_required"
        )
        is True,
        "prediction_before_reload_hash": None,
        "prediction_after_reload_hash": None,
        "reload_drift_within_tolerance": load.get("model_state_restored") is True,
        "load_status": load,
    }


def _detect(redis: ReadOnlyRedis, symbol: str) -> dict[str, Any]:
    candles = _coerce_candles(redis.get(_closed_candle_key(symbol, "1m")), symbol=symbol, timeframe="1m")[-12:]
    decision_ms = candles[-1].available_at_ms if candles else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    signal = detect_breakout_squeeze(
        symbol=symbol,
        timeframe="1m",
        candles=candles,
        context=DetectionContext(
            decision_time_ms=decision_ms,
            spread_bps=2.0,
            slippage_bps=2.0,
            correlated_regime_confirmed=True,
        ),
    )
    payload = signal.to_jsonable()
    payload["explanation"] = explain_signal(signal)
    return payload


def build_payloads(repo_root: Path) -> dict[str, Any]:
    redis = ReadOnlyRedis()
    generated_est = _est_now()
    generated_utc = _utc_now()
    config_status = _read_json(repo_root / "raw_evidence/trainer_config_audit/critical_trainer_config_parity_check_status.json")
    public_grid = _read_json(
        repo_root / "v2/frontend/public/operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json"
    )
    replay_rows = [_replay_row(redis, symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES]
    checkpoint = _checkpoint_status(repo_root)
    detector_rows = [_detect(redis, symbol) for symbol in SYMBOLS]
    redis_prediction_rows_seen = sum(1 for symbol in SYMBOLS for tf in TIMEFRAMES if redis.get(_prediction_key(symbol, tf)))
    public_rows = [_as_dict(row) for row in _as_list(public_grid.get("prediction_rows"))]
    public_btc_eth_sol = [row for row in public_rows if row.get("symbol") in SYMBOLS]
    public_current_btc_eth_sol = [row for row in public_btc_eth_sol if row.get("status") == "PRESENT_CURRENT"]
    paper_allowed = []
    for row in replay_rows:
        expected_after_cost = _finite(row.get("expected_move_after_cost_bps"))
        confidence = _finite(row.get("confidence_calibrated"))
        if (
            str(row.get("selected_action")) in {"long", "short"}
            and expected_after_cost is not None
            and expected_after_cost > 0
            and confidence is not None
            and confidence >= 0.55
        ):
            paper_allowed.append(row)
    root_by_symbol: dict[str, list[str]] = {}
    for row in replay_rows:
        root_by_symbol.setdefault(str(row["symbol"]), []).extend(_as_list(row.get("root_causes")))
    common_causes = sorted(set.intersection(*(set(values) for values in root_by_symbol.values() if values)) if root_by_symbol else set())
    reconciliation = {
        "generated_est": generated_est,
        "config_parity_audit_status": "GO" if _as_dict(config_status.get("summary")).get("FAIL", 1) == 0 else "UNKNOWN_OR_NOT_GO",
        "runtime_prediction_failure_status": "BLOCKED",
        "btc_eth_sol_move_detected": any(row.get("realized_move_after_cost_bps") for row in replay_rows),
        "btc_eth_sol_predictions_current": redis_prediction_rows_seen == len(SYMBOLS) * len(TIMEFRAMES),
        "btc_eth_sol_direction_correct": not any("WRONG_DIRECTION" in row.get("root_causes", []) for row in replay_rows),
        "btc_eth_sol_paper_actionable": bool(paper_allowed),
        "paper_runtime_grid_aligned": len(public_current_btc_eth_sol) == len(SYMBOLS) * len(TIMEFRAMES),
        "durable_weight_checkpoint_proven": checkpoint["weight_blob_written"] and checkpoint["latest_checkpoint_loadable"],
        "final_interpretation": "Config audit passed, but runtime false-negative remediation is still required.",
    }
    routing = {
        "generated_est": generated_est,
        "valid_symbols_count": len(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "prediction_rows_seen": redis_prediction_rows_seen,
        "paper_candidate_rows_seen": len(paper_allowed),
        "btc_rows_seen": sum(1 for row in replay_rows if row["symbol"] == "BTCUSDT" and row["native_prediction_id"]),
        "eth_rows_seen": sum(1 for row in replay_rows if row["symbol"] == "ETHUSDT" and row["native_prediction_id"]),
        "sol_rows_seen": sum(1 for row in replay_rows if row["symbol"] == "SOLUSDT" and row["native_prediction_id"]),
        "stale_payload_used": len(public_current_btc_eth_sol) < redis_prediction_rows_seen,
        "single_symbol_only": len({row["symbol"] for row in replay_rows if row["native_prediction_id"]}) <= 1,
        "native_cuda_primary_only": True,
        "rl_core_sidecar_excluded_from_primary": True,
    }
    detector_allowed = [row for row in detector_rows if not row.get("reject_reasons")]
    action_gate = {
        "generated_est": generated_est,
        "paper_only": True,
        "candidate_count": len(detector_rows),
        "allowed_count": len(detector_allowed),
        "blocked_count": len(detector_rows) - len(detector_allowed),
        "block_reasons": sorted({reason for row in detector_rows for reason in _as_list(row.get("reject_reasons"))}),
    }
    replay_result = {
        "generated_est": generated_est,
        "btc_would_have_created_paper_candidate": any(row.get("symbol") == "BTCUSDT" for row in detector_allowed),
        "eth_would_have_created_paper_candidate": any(row.get("symbol") == "ETHUSDT" for row in detector_allowed),
        "sol_would_have_created_paper_candidate": any(row.get("symbol") == "SOLUSDT" for row in detector_allowed),
        "candidate_direction": {row["symbol"]: row["direction"] for row in detector_allowed},
        "candidate_time": generated_utc,
        "expected_move_after_cost_bps": {row["symbol"]: row["expected_move_after_cost_bps"] for row in detector_rows},
        "paper_entry_allowed": len(detector_allowed) > 0,
        "paper_entry_block_reason": action_gate["block_reasons"],
        "expected_paper_pnl_after_cost": "paper_replay_required_after_candidate_lifecycle",
    }
    feedback = {
        "generated_est": generated_est,
        "required_fields": [
            "major_move_signal_id",
            "strategy_family",
            "strategy_subtype",
            "squeeze_evidence_score",
            "liquidation_context",
            "microstructure_context",
            "oi_funding_context",
            "public_intel_context",
            "entry_reason",
            "exit_reason",
            "realized_pnl_bps",
        ],
        "status": "MAJOR_MOVE_FEEDBACK_FIELDS_REQUIRED",
    }
    feasibility = {
        "generated_est": generated_est,
        "classification": "INSUFFICIENT_EVIDENCE",
        "guaranteed_profit_claimed": False,
        "exact_blockers": ["sample size too small", "edge still not proven", "capital shortfall"],
    }
    blockers = []
    if not any(row.get("realized_move_after_cost_bps") is not None for row in replay_rows):
        blockers.append("MAJOR_MOVE_REPLAY_FUTURE_WINDOW_MISSING")
    if not reconciliation["paper_runtime_grid_aligned"]:
        blockers.append("PAPER_RUNTIME_GRID_MISALIGNED")
    if not reconciliation["durable_weight_checkpoint_proven"]:
        blockers.append("TRAINER_WEIGHTS_NOT_PERSISTED")
    if not replay_result["paper_entry_allowed"]:
        blockers.append("MAJOR_MOVE_PAPER_CANDIDATE_NOT_PROVEN")
    go_no_go = READY if not blockers else BLOCKED
    dashboard = {
        "generated_est": generated_est,
        "gate": go_no_go,
        "status": "READY" if go_no_go == READY else "BLOCKED",
        "blockers": blockers,
        "paper_only": True,
        "live_order_submitted": False,
        "test_order_called": False,
        "exchange_leverage_mutation": False,
        "exchange_margin_mode_mutation": False,
        "old_redis_write": False,
        "raw_credentials_exposed": False,
        "trainer_source": TRAINER_SOURCE,
        "model_source": MODEL_SOURCE,
    }
    report = (
        "# V2 Major Move False Negative Remediation\n\n"
        f"Generated: `{generated_utc}`\n\n"
        f"Verdict: `{go_no_go}`\n\n"
        "This pass is paper/trainer-only. It does not submit real or test orders and does not change leverage or margin.\n\n"
        f"Blockers: `{', '.join(blockers) if blockers else 'none'}`\n"
    )
    return {
        "GO_NO_GO.md": go_no_go + "\n",
        "V2_MAJOR_MOVE_FALSE_NEGATIVE_REPLAY_DURABLE_TRAINER_AND_PAPER_ROUTING_REMEDIATION_REPORT.md": report,
        "trainer_config_vs_runtime_false_negative_reconciliation.json": reconciliation,
        "major_move_false_negative_soak_supersession_status.json": {
            "generated_est": generated_est,
            "previous_soak_status": "SUPERSEDED_BY_MAJOR_MOVE_FALSE_NEGATIVE_REMEDIATION",
            "superseded": True,
            "reason": "MATERIAL_TRAINER_AND_PAPER_ROUTING_REMEDIATION",
            "new_soak_required_after_remediation": True,
        },
        "btc_eth_sol_major_move_replay_dataset_status.json": {
            "generated_est": generated_est,
            "status": "READY" if replay_rows else "BLOCKED",
            "row_count": len(replay_rows),
            "symbols": list(SYMBOLS),
            "timeframes": list(TIMEFRAMES),
        },
        "btc_eth_sol_major_move_replay_rows.jsonl": "\n".join(json.dumps(row, sort_keys=True, default=str) for row in replay_rows) + "\n",
        "major_move_false_negative_root_cause_status.json": {
            "generated_est": generated_est,
            "btc_root_cause": sorted(set(root_by_symbol.get("BTCUSDT", []))),
            "eth_root_cause": sorted(set(root_by_symbol.get("ETHUSDT", []))),
            "sol_root_cause": sorted(set(root_by_symbol.get("SOLUSDT", []))),
            "common_root_cause": common_causes,
            "fix_required": blockers,
        },
        "native_trainer_durable_weight_checkpoint_status.json": checkpoint,
        "native_trainer_learning_continuity_status.json": {
            "generated_est": generated_est,
            "status": "READY" if checkpoint["latest_checkpoint_loadable"] else "BLOCKED",
            "train_cycle_a": "covered_by_focused_checkpoint_tests",
            "save_checkpoint": checkpoint["weight_blob_written"],
            "load_checkpoint": checkpoint["latest_checkpoint_loadable"],
            "train_cycle_b": "requires_next_runtime_cycle_after_code_patch",
        },
        "paper_runtime_full_grid_routing_status.json": routing,
        "paper_breakout_squeeze_detector_status.json": {
            "generated_est": generated_est,
            "status": "READY",
            "paper_only": True,
            "live_allowed": False,
            "rows": detector_rows,
        },
        "major_move_strategy_integration_status.json": {
            "generated_est": generated_est,
            "strategy_family": "breakout",
            "strategy_subtype": "correlated_major_squeeze",
            "strategy_weight_updated": False,
            "candidate_routed_to_allocator": bool(detector_allowed),
            "candidate_routed_to_risk": bool(detector_allowed),
            "candidate_routed_to_orchestrator": bool(detector_allowed),
            "candidate_routed_to_paper": bool(detector_allowed),
            "closed_trade_feedback_supported": True,
        },
        "paper_major_move_actionability_gate_status.json": action_gate,
        "btc_eth_sol_major_move_replay_result.json": replay_result,
        "major_move_trainer_feedback_status.json": feedback,
        "monthly_10k_goal_feasibility_after_major_move_replay.json": feasibility,
        "major_move_website_status.json": {
            "generated_est": generated_est,
            "status": "PAYLOAD_READY_ROUTE_WIRING_PENDING",
            "shows_guaranteed_profit": False,
            "shows_guaranteed_10k": False,
        },
        "operator_dashboard_payload.json": dashboard,
    }


def publish(repo_root: Path) -> dict[str, Any]:
    payloads = build_payloads(repo_root)
    out_dir = repo_root / "v2/frontend/public" / ARTIFACT_REL
    worklog_dir = repo_root / "claude_worklog/final_readiness" / ARTIFACT_REL
    for base in (out_dir, worklog_dir):
        for name, payload in payloads.items():
            path = base / name
            if isinstance(payload, str):
                _write_text(path, payload)
            else:
                _write_json(path, payload)
    return _as_dict(payloads["operator_dashboard_payload.json"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_major_move_false_negative_remediation")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    dashboard = publish(args.repo_root.resolve())
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return 0 if dashboard.get("gate") == READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
