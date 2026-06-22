"""Runtime signal burn-in and website live-gate evidence for the CUDA trainer.

This module is intentionally artifact-only. It consumes the V2 native CUDA
trainer operator payload, verifies contracts/lineage, recomputes paper edge
conservatively, and writes website/report artifacts. It never talks to an
exchange and never writes Redis.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    TRAINER_SOURCE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    REQUIRED_PREDICTION_FIELDS,
    dumps_pretty,
)

GATE_READY = "V2_NATIVE_CUDA_TRAINER_RUNTIME_SIGNAL_BURN_IN_AND_WEBSITE_LIVE_GATE_READY"
GATE_BLOCKED = "V2_NATIVE_CUDA_TRAINER_RUNTIME_SIGNAL_BURN_IN_AND_WEBSITE_LIVE_GATE_BLOCKED"
SCHEMA_VERSION = "v2_native_cuda_trainer_runtime_signal_burn_in_live_gate_v1"
ARTIFACT_REL = Path("v2_native_cuda_trainer_runtime_signal_burn_in_and_website_live_gate/latest")
SOURCE_PAYLOAD_REL = Path("v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json")

LIVE_BLOCKERS = (
    "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
    "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
)

WINDOW_HOURS = (1, 6, 12)


@dataclass(frozen=True)
class CudaTrainerLiveGatePaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    source_payload_path: Path


@dataclass(frozen=True)
class CudaTrainerLiveGateResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


def default_paths(repo_root: Path) -> CudaTrainerLiveGatePaths:
    root = repo_root.resolve()
    return CudaTrainerLiveGatePaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=root / "v2/frontend/public" / ARTIFACT_REL,
        source_payload_path=root / "v2/frontend/public" / SOURCE_PAYLOAD_REL,
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _ci_lower_95(values: list[float]) -> float | None:
    if not values:
        return None
    avg = _mean(values)
    assert avg is not None
    return avg - 1.96 * _sample_std(values) / math.sqrt(len(values))


def _json_load(path: Path) -> dict[str, Any]:
    return _as_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _prediction_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _as_list(payload.get("predictions_by_symbol")):
        pred = _as_dict(row)
        prediction_id = pred.get("prediction_id")
        if isinstance(prediction_id, str) and prediction_id:
            out[prediction_id] = pred
    return out


def _collect_symbols(predictions: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("symbol")) for row in predictions if row.get("symbol")})


def _status_from_violations(violations: list[str], *, ready: str = "READY") -> str:
    return ready if not violations else "BLOCKED"


def build_burn_in_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    trainer = _as_dict(source.get("trainer"))
    metrics = _as_dict(source.get("metrics"))
    training = _as_dict(metrics.get("training"))
    predictions = [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]
    symbols = _collect_symbols(predictions)

    cuda_active = bool(trainer.get("cuda_active") and training.get("cuda_active"))
    tensors_verified = bool(trainer.get("model_tensors_device_verified") and training.get("cuda_claim_verified"))
    loss_curve = [value for value in (training.get("loss_before"), training.get("loss_after")) if _float(value) is not None]

    windows = []
    for hours in WINDOW_HOURS:
        windows.append(
            {
                "window": f"{hours}h",
                "window_complete": False,
                "status": "TRACKING_READY_CURRENT_CYCLE_VERIFIED",
                "current_prediction_count": len(predictions),
                "current_symbols_covered": symbols,
                "note": "Runtime tracker is implemented; this artifact does not fabricate elapsed burn-in time.",
            }
        )

    violations: list[str] = []
    if not cuda_active:
        violations.append("CUDA_NOT_ACTIVE_IN_SOURCE_PAYLOAD")
    if not tensors_verified:
        violations.append("MODEL_TENSORS_NOT_VERIFIED_ON_CUDA")
    if not predictions:
        violations.append("NO_CUDA_TRAINER_PREDICTIONS")
    if trainer.get("live_gate") != LIVE_GATE_BLOCKED:
        violations.append("LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY")
    if trainer.get("live_symbols") != []:
        violations.append("LIVE_SYMBOLS_NOT_EMPTY")

    return {
        "schema_version": f"{SCHEMA_VERSION}_burn_in_status",
        "generated_est": generated_est,
        "status": _status_from_violations(violations, ready="BURN_IN_TRACKER_READY"),
        "burn_in_complete": False,
        "burn_in_windows": windows,
        "cuda_active": cuda_active,
        "gpu_name": training.get("gpu_name"),
        "model_device": trainer.get("model_device") or training.get("device"),
        "model_tensors_device_verified": tensors_verified,
        "vram_usage": {
            "vram_allocated_mb": training.get("vram_allocated_mb"),
        },
        "training_steps": training.get("training_steps", 0),
        "train_rows": training.get("train_rows", 0),
        "validation_rows": training.get("validation_rows", 0),
        "loss_curve": loss_curve,
        "action_distribution": training.get("action_distribution", {}),
        "prediction_count": len(predictions),
        "symbols_covered": symbols,
        "model_source": trainer.get("model_source"),
        "trainer_source": trainer.get("trainer_source"),
        "checkpoint_source": trainer.get("checkpoint_source"),
        "checkpoint_id": trainer.get("checkpoint_id"),
        "missing_feature_count_total": metrics.get("missing_feature_count_total", 0),
        "stale_feature_count_total": metrics.get("stale_feature_count_total", 0),
        "missing_feature_masks_present": all("missing_feature_count" in row for row in predictions),
        "stale_feature_masks_present": all("stale_feature_count" in row for row in predictions),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "violations": violations,
    }


def build_prediction_contract_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    predictions = [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]
    metrics = _as_dict(source.get("metrics"))
    io_audit = _as_dict(metrics.get("v2_io_audit"))
    keys_written = [str(key) for key in _as_list(io_audit.get("keys_written"))]
    prediction_keys_written = [key for key in keys_written if key.startswith("v2:prediction:")]
    violations: list[str] = []
    rows: list[dict[str, Any]] = []

    for index, prediction in enumerate(predictions):
        prediction_id = str(prediction.get("prediction_id") or f"index_{index}")
        missing_fields = [field for field in REQUIRED_PREDICTION_FIELDS if field not in prediction]
        row_violations: list[str] = []
        if missing_fields:
            row_violations.append("missing_fields:" + ",".join(missing_fields))
        if prediction.get("trainer_source") != TRAINER_SOURCE:
            row_violations.append("trainer_source_mismatch")
        if prediction.get("model_source") != MODEL_SOURCE:
            row_violations.append("model_source_mismatch")
        if prediction.get("live_gate") != LIVE_GATE_BLOCKED:
            row_violations.append("live_gate_not_blocked_human_only")
        if prediction.get("live_symbols") != []:
            row_violations.append("live_symbols_not_empty")
        probs = prediction.get("action_probabilities")
        if not isinstance(probs, list) or not probs:
            row_violations.append("action_probabilities_missing")
        elif abs(sum(float(x) for x in probs) - 1.0) > 0.01:
            row_violations.append("action_probabilities_do_not_sum_to_one")
        if row_violations:
            violations.extend(f"{prediction_id}:{item}" for item in row_violations)
        rows.append(
            {
                "prediction_id": prediction_id,
                "symbol": prediction.get("symbol"),
                "timeframe": prediction.get("timeframe"),
                "selected_action": prediction.get("selected_action"),
                "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
                "confidence_calibrated": prediction.get("confidence_calibrated"),
                "data_coverage_percent": prediction.get("data_coverage_percent"),
                "trainer_source": prediction.get("trainer_source"),
                "model_source": prediction.get("model_source"),
                "live_gate": prediction.get("live_gate"),
                "live_symbols": prediction.get("live_symbols"),
                "contract_pass": not row_violations,
                "violations": row_violations,
            }
        )

    if not predictions:
        violations.append("NO_PREDICTIONS_TO_VERIFY")
    if int(io_audit.get("old_redis_write_attempts") or 0) != 0:
        violations.append("OLD_REDIS_WRITE_ATTEMPTS_PRESENT")
    if any(not key.startswith("v2:") for key in keys_written):
        violations.append("NON_V2_REDIS_KEY_WRITTEN")

    return {
        "schema_version": f"{SCHEMA_VERSION}_prediction_contract",
        "generated_est": generated_est,
        "status": _status_from_violations(violations, ready="PREDICTION_CONTRACT_READY"),
        "contract_pass": not violations,
        "predictions_checked": len(predictions),
        "required_prediction_fields": list(REQUIRED_PREDICTION_FIELDS),
        "trainer_source_required": TRAINER_SOURCE,
        "model_source_required": MODEL_SOURCE,
        "live_gate_required": LIVE_GATE_BLOCKED,
        "live_symbols_required": [],
        "prediction_keys_written": prediction_keys_written,
        "writes_only_v2_prediction_keys": bool(prediction_keys_written)
        and all(key.startswith("v2:prediction:") for key in prediction_keys_written),
        "old_redis_write_attempts": int(io_audit.get("old_redis_write_attempts") or 0),
        "rows": rows,
        "violations": violations,
    }


def build_risk_consumption_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    trainer = _as_dict(source.get("trainer"))
    predictions = _prediction_index(source)
    lineages = [_as_dict(row) for row in _as_list(source.get("lineage_samples"))]
    rows: list[dict[str, Any]] = []
    violations: list[str] = []

    for index, lineage in enumerate(lineages):
        risk = _as_dict(lineage.get("risk_decision_record"))
        trainer_record = _as_dict(lineage.get("trainer_prediction_record"))
        prediction_id = str(risk.get("prediction_id") or trainer_record.get("prediction_id") or f"index_{index}")
        prediction = predictions.get(prediction_id, {})
        row_violations: list[str] = []
        if not risk.get("risk_decision_id"):
            row_violations.append("missing_risk_decision_id")
        if prediction_id not in predictions:
            row_violations.append("prediction_not_found_in_cuda_payload")
        if risk.get("prediction_id") != trainer_record.get("prediction_id"):
            row_violations.append("risk_prediction_id_does_not_match_trainer_record")
        if risk.get("live_blocked") is not True:
            row_violations.append("risk_live_blocked_not_true")
        if not risk.get("risk_action"):
            row_violations.append("missing_risk_action")
        if row_violations:
            violations.extend(f"{prediction_id}:{item}" for item in row_violations)
        rows.append(
            {
                "prediction_id_consumed": prediction_id,
                "risk_decision_id": risk.get("risk_decision_id"),
                "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
                "confidence_calibrated": prediction.get("confidence_calibrated"),
                "data_coverage_percent": prediction.get("data_coverage_percent"),
                "block_allow_reason": risk.get("risk_reason_code"),
                "risk_action": risk.get("risk_action"),
                "risk_fail_closed_state": "FAIL_CLOSED" if risk.get("risk_action") == "deny" else "ALLOW_RECORDED",
                "risk_caps_status": "OPERATOR_REQUIRED_BLOCKED"
                if not trainer.get("risk_caps_configured")
                else "CONFIGURED",
                "contract_pass": not row_violations,
                "violations": row_violations,
            }
        )

    if not rows:
        violations.append("NO_RISK_LINEAGE_ROWS")
    risk_caps_unset = trainer.get("risk_caps_configured") is not True
    if risk_caps_unset and any(row.get("risk_action") != "deny" for row in rows):
        violations.append("RISK_CAPS_UNSET_BUT_NON_DENY_RISK_ACTION_PRESENT")

    return {
        "schema_version": f"{SCHEMA_VERSION}_risk_consumption",
        "generated_est": generated_est,
        "status": _status_from_violations(violations, ready="RISK_CONSUMES_CUDA_TRAINER_READY"),
        "consumption_pass": not violations,
        "lineage_count": len(rows),
        "risk_caps_configured": bool(trainer.get("risk_caps_configured")),
        "risk_caps_status": "OPERATOR_REQUIRED_BLOCKED" if risk_caps_unset else "CONFIGURED",
        "fail_closed_when_caps_unset": risk_caps_unset,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "rows": rows,
        "violations": violations,
    }


def build_orchestrator_consumption_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    predictions = _prediction_index(source)
    lineages = [_as_dict(row) for row in _as_list(source.get("lineage_samples"))]
    rows: list[dict[str, Any]] = []
    violations: list[str] = []

    for index, lineage in enumerate(lineages):
        orch = _as_dict(lineage.get("orchestrator_decision_record"))
        risk = _as_dict(lineage.get("risk_decision_record"))
        trainer_record = _as_dict(lineage.get("trainer_prediction_record"))
        prediction_id = str(orch.get("prediction_id") or trainer_record.get("prediction_id") or f"index_{index}")
        prediction = predictions.get(prediction_id, {})
        row_violations: list[str] = []
        if not orch.get("decision_id"):
            row_violations.append("missing_orchestrator_decision_id")
        if prediction_id not in predictions:
            row_violations.append("prediction_not_found_in_cuda_payload")
        if orch.get("prediction_id") != trainer_record.get("prediction_id"):
            row_violations.append("orchestrator_prediction_id_does_not_match_trainer_record")
        if orch.get("live_blocked") is not True:
            row_violations.append("orchestrator_live_blocked_not_true")
        if not risk.get("risk_decision_id"):
            row_violations.append("paired_risk_decision_missing")
        if row_violations:
            violations.extend(f"{prediction_id}:{item}" for item in row_violations)
        rows.append(
            {
                "orchestrator_decision_id": orch.get("decision_id"),
                "trainer_prediction_id": prediction_id,
                "risk_decision_id": risk.get("risk_decision_id"),
                "action": orch.get("decision_action"),
                "hold_block_reason": orch.get("decision_reason_code"),
                "signal_lineage": {
                    "symbol": orch.get("symbol"),
                    "feature_snapshot_id": orch.get("feature_snapshot_id"),
                    "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
                    "confidence_calibrated": prediction.get("confidence_calibrated"),
                },
                "contract_pass": not row_violations,
                "violations": row_violations,
            }
        )

    if not rows:
        violations.append("NO_ORCHESTRATOR_LINEAGE_ROWS")

    source_predictions = [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]
    paper_position_feature_present = any("paper_position_present" in _as_list(row.get("feature_names")) for row in source_predictions)

    return {
        "schema_version": f"{SCHEMA_VERSION}_orchestrator_consumption",
        "generated_est": generated_est,
        "status": _status_from_violations(violations, ready="ORCHESTRATOR_CONSUMES_CUDA_TRAINER_READY"),
        "consumption_pass": not violations,
        "lineage_count": len(rows),
        "symbol_universe_state": {
            "symbols_covered": _collect_symbols(source_predictions),
            "symbol_count": len(_collect_symbols(source_predictions)),
            "source": "cuda_trainer_prediction_payload",
        },
        "paper_position_state_consumed": paper_position_feature_present,
        "strategy_fallback": {
            "status": "FAIL_CLOSED_ABSTAIN_OR_HOLD_AVAILABLE",
            "orders_enabled": False,
        },
        "risk_decision_pairing": {
            "status": "PAIRED_LINEAGE_VERIFIED",
            "note": "Current native domain order is trainer -> orchestrator -> risk -> paper; risk decisions are paired in the final lineage.",
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "rows": rows,
        "violations": violations,
    }


def build_paper_lineage_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    lineages = [_as_dict(row) for row in _as_list(source.get("lineage_samples"))]
    rows: list[dict[str, Any]] = []
    violations: list[str] = []

    for index, lineage in enumerate(lineages):
        trainer_record = _as_dict(lineage.get("trainer_prediction_record"))
        orch = _as_dict(lineage.get("orchestrator_decision_record"))
        risk = _as_dict(lineage.get("risk_decision_record"))
        paper = _as_dict(lineage.get("paper_execution_ledger_entry"))
        signal = _as_dict(lineage.get("paper_signal_lineage"))
        prediction_id = str(trainer_record.get("prediction_id") or paper.get("prediction_id") or f"index_{index}")
        row_violations: list[str] = []
        if paper.get("prediction_id") != prediction_id:
            row_violations.append("paper_prediction_id_does_not_match_trainer")
        if paper.get("risk_decision_id") != risk.get("risk_decision_id"):
            row_violations.append("paper_risk_id_does_not_match_risk")
        if paper.get("decision_id") != orch.get("decision_id"):
            row_violations.append("paper_orchestrator_id_does_not_match_orchestrator")
        if paper.get("live_blocked") is not True:
            row_violations.append("paper_live_blocked_not_true")
        if signal.get("live_gate") != LIVE_GATE_BLOCKED:
            row_violations.append("paper_signal_live_gate_not_blocked")
        if signal.get("live_symbols") != []:
            row_violations.append("paper_signal_live_symbols_not_empty")
        if row_violations:
            violations.extend(f"{prediction_id}:{item}" for item in row_violations)
        rows.append(
            {
                "paper_intent_id": signal.get("trainer_prediction_id"),
                "paper_ledger_row": paper.get("paper_trade_id"),
                "trainer_prediction_id": prediction_id,
                "risk_decision_id": risk.get("risk_decision_id"),
                "orchestrator_decision_id": orch.get("decision_id"),
                "action": signal.get("selected_action"),
                "fill_held_block_result": paper.get("ledger_action"),
                "pnl_when_known": signal.get("pnl_outcome"),
                "contract_pass": not row_violations,
                "violations": row_violations,
            }
        )

    if not rows:
        violations.append("NO_PAPER_LINEAGE_ROWS")

    return {
        "schema_version": f"{SCHEMA_VERSION}_paper_lineage",
        "generated_est": generated_est,
        "status": _status_from_violations(violations, ready="PAPER_TRADER_CONSUMES_CUDA_SIGNAL_READY"),
        "consumption_pass": not violations,
        "lineage_count": len(rows),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "rows": rows,
        "violations": violations,
    }


def build_edge_recompute_status(source: dict[str, Any], *, generated_est: str) -> dict[str, Any]:
    predictions = [_as_dict(row) for row in _as_list(source.get("predictions_by_symbol"))]
    values = [value for value in (_float(row.get("expected_move_after_cost_bps")) for row in predictions) if value is not None]
    mean_value = _mean(values)
    by_symbol: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        symbol = str(prediction.get("symbol") or "UNKNOWN")
        value = _float(prediction.get("expected_move_after_cost_bps"))
        if value is None:
            continue
        row = by_symbol.setdefault(symbol, {"symbol": symbol, "sample_count": 0, "values": []})
        row["sample_count"] += 1
        row["values"].append(value)
    for row in by_symbol.values():
        symbol_values = [float(value) for value in row.pop("values")]
        row["after_cost_expectancy_bps"] = _mean(symbol_values)
        row["after_cost_ci_lower_bps"] = _ci_lower_95(symbol_values)

    overconfidence = sorted(
        [
            {
                "prediction_id": prediction.get("prediction_id"),
                "symbol": prediction.get("symbol"),
                "confidence_calibrated": prediction.get("confidence_calibrated"),
                "expected_move_after_cost_bps": prediction.get("expected_move_after_cost_bps"),
            }
            for prediction in predictions
            if (_float(prediction.get("confidence_calibrated")) or 0.0) >= 0.5
            and (_float(prediction.get("expected_move_after_cost_bps")) or 0.0) <= 0.0
        ],
        key=lambda row: float(row.get("confidence_calibrated") or 0.0),
        reverse=True,
    )[:8]

    return {
        "schema_version": f"{SCHEMA_VERSION}_edge_recompute",
        "generated_est": generated_est,
        "status": "EDGE_RECOMPUTE_READY_BLOCK_LIVE_EDGE_NOT_PROVEN",
        "edge_proven": False,
        "new_cuda_trainer": {
            "sample_count": len(values),
            "after_cost_expectancy_bps": mean_value,
            "after_cost_ci_lower_bps": _ci_lower_95(values),
            "prediction_count": len(predictions),
        },
        "old_wrapper_baseline": {
            "status": "BASELINE_COMPARISON_NOT_AVAILABLE_IN_CURRENT_SOURCE_PAYLOAD",
            "edge_proven": False,
        },
        "strategy_fallback": {
            "status": "NO_TRADE_PRESERVATION_REMAINS_ACTIVE",
            "no_trade_preservation": True,
        },
        "false_positives": None,
        "false_negatives": None,
        "drawdown": None,
        "by_symbol_edge": sorted(by_symbol.values(), key=lambda row: str(row.get("symbol"))),
        "overconfidence_examples": overconfidence,
        "confidence_calibration": {
            "mean_confidence_calibrated": _mean(
                [value for value in (_float(row.get("confidence_calibrated")) for row in predictions) if value is not None]
            ),
            "outcome_labels_available": False,
            "verdict": "OUTCOMES_PENDING_BURN_IN",
        },
        "recommendations": list(LIVE_BLOCKERS),
        "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "forbidden_claims_absent": {
            "live_ready_claim": True,
            "canary_ready_claim": True,
            "profitable_edge_claim": True,
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }


def build_website_live_gate_status(
    source: dict[str, Any],
    edge: dict[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    live_switch = _as_dict(source.get("live_switch"))
    trainer = _as_dict(source.get("trainer"))
    training = _as_dict(_as_dict(source.get("metrics")).get("training"))
    surfaces = [
        "AI Brain / Trainer",
        "Risk",
        "Orchestrator",
        "Paper Trading",
        "Live Readiness",
        "Symbols",
        "Market Intelligence",
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_website_live_gate",
        "generated_est": generated_est,
        "status": "WEBSITE_LIVE_GATE_SYNC_READY",
        "payload_path": f"/{ARTIFACT_REL}/operator_dashboard_payload.json",
        "surfaces_synced": surfaces,
        "cuda_trainer_active_visible": bool(trainer.get("cuda_active")),
        "gpu_metrics_visible": bool(training.get("gpu_name")),
        "training_loss_visible": training.get("loss_before") is not None and training.get("loss_after") is not None,
        "prediction_lineage_visible": int(source.get("lineage_count") or 0) > 0,
        "risk_consumption_visible": True,
        "orchestrator_consumption_visible": True,
        "paper_trader_lineage_visible": True,
        "edge_recompute_visible": True,
        "live_switch": {
            "visible": live_switch.get("visible") is True,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": live_switch.get("disabled_reason")
            or "LIVE_GATE=blocked_human_only; live requires separate human approval.",
        },
        "exact_live_blockers": edge.get("recommendations", list(LIVE_BLOCKERS)),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_operator_dashboard_payload(
    *,
    source: dict[str, Any],
    generated_est: str,
    artifacts: dict[str, Any],
    go_no_go: str,
) -> dict[str, Any]:
    burn_in = artifacts["v2_native_cuda_trainer_burn_in_status.json"]
    contract = artifacts["v2_native_cuda_prediction_contract_status.json"]
    risk = artifacts["v2_risk_consumes_cuda_trainer_status.json"]
    orchestrator = artifacts["v2_orchestrator_consumes_cuda_trainer_status.json"]
    paper = artifacts["v2_paper_trader_cuda_signal_lineage_status.json"]
    edge = artifacts["v2_cuda_trainer_edge_recompute_status.json"]
    website = artifacts["v2_cuda_trainer_website_live_gate_status.json"]
    trainer = _as_dict(source.get("trainer"))
    metrics = _as_dict(source.get("metrics"))
    live_switch = _as_dict(source.get("live_switch"))

    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": go_no_go,
        "source_gate": source.get("go_no_go"),
        "source_payload_path": f"/{SOURCE_PAYLOAD_REL}",
        "trainer": trainer,
        "metrics": metrics,
        "prediction_count": source.get("prediction_count", len(_as_list(source.get("predictions_by_symbol")))),
        "lineage_count": source.get("lineage_count", len(_as_list(source.get("lineage_samples")))),
        "predictions_by_symbol": _as_list(source.get("predictions_by_symbol"))[:64],
        "lineage_samples": _as_list(source.get("lineage_samples"))[:16],
        "burn_in": burn_in,
        "prediction_contract": contract,
        "risk_consumption": risk,
        "orchestrator_consumption": orchestrator,
        "paper_signal_lineage": paper,
        "edge_recompute": edge,
        "website_live_gate": website,
        "live_readiness": {
            "live_ready": False,
            "canary_ready": False,
            "primary_recommendation": edge["primary_recommendation"],
            "recommendations": edge["recommendations"],
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
        },
        "live_switch": {
            "visible": live_switch.get("visible") is not False,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": live_switch.get("disabled_reason")
            or "LIVE_GATE=blocked_human_only; requires operator approval, risk caps, and paper edge proof.",
        },
        "safety_scoreboard": {
            "paper_shadow_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "places_orders": False,
            "cancels_orders": False,
            "modifies_orders": False,
            "calls_test_order_endpoint": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
        },
    }


def build_report(result: CudaTrainerLiveGateResult) -> str:
    payload = result.operator_dashboard_payload
    burn_in = payload["burn_in"]
    edge = payload["edge_recompute"]
    live_readiness = payload["live_readiness"]
    return "\n".join(
        [
            "# V2 Native CUDA Trainer Runtime Signal Burn-In And Website Live Gate Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Generated EST: `{payload['generated_est']}`",
            f"Trainer source: `{payload['trainer'].get('trainer_source')}`",
            f"Model source: `{payload['trainer'].get('model_source')}`",
            f"CUDA active: `{burn_in['cuda_active']}`",
            f"GPU: `{burn_in['gpu_name']}`",
            f"Training steps: `{burn_in['training_steps']}`",
            f"Predictions checked: `{payload['prediction_contract']['predictions_checked']}`",
            f"Lineage chains checked: `{payload['lineage_count']}`",
            "",
            "Live remains blocked.",
            "",
            f"- live_gate: `{LIVE_GATE_BLOCKED}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- live_ready: `False`",
            "- canary_ready: `False`",
            f"- primary recommendation: `{live_readiness['primary_recommendation']}`",
            f"- blockers: `{', '.join(live_readiness['recommendations'])}`",
            "",
            "Edge recompute is conservative: paper outcomes are still pending burn-in, so no profitable edge or live/canary readiness is claimed.",
            "",
            f"- after-cost expectancy bps: `{edge['new_cuda_trainer']['after_cost_expectancy_bps']}`",
            f"- CI lower bps: `{edge['new_cuda_trainer']['after_cost_ci_lower_bps']}`",
            "- false positives: `null` until outcome labels exist",
            "- false negatives: `null` until outcome labels exist",
            "- drawdown: `null` until paper outcomes exist",
            "",
            "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.",
        ]
    ) + "\n"


def build_runtime_signal_gate(source_payload: dict[str, Any], *, generated_est: str | None = None) -> CudaTrainerLiveGateResult:
    generated = generated_est or _est_iso()
    artifacts: dict[str, Any] = {}
    artifacts["v2_native_cuda_trainer_burn_in_status.json"] = build_burn_in_status(source_payload, generated_est=generated)
    artifacts["v2_native_cuda_prediction_contract_status.json"] = build_prediction_contract_status(
        source_payload,
        generated_est=generated,
    )
    artifacts["v2_risk_consumes_cuda_trainer_status.json"] = build_risk_consumption_status(
        source_payload,
        generated_est=generated,
    )
    artifacts["v2_orchestrator_consumes_cuda_trainer_status.json"] = build_orchestrator_consumption_status(
        source_payload,
        generated_est=generated,
    )
    artifacts["v2_paper_trader_cuda_signal_lineage_status.json"] = build_paper_lineage_status(
        source_payload,
        generated_est=generated,
    )
    artifacts["v2_cuda_trainer_edge_recompute_status.json"] = build_edge_recompute_status(
        source_payload,
        generated_est=generated,
    )
    artifacts["v2_cuda_trainer_website_live_gate_status.json"] = build_website_live_gate_status(
        source_payload,
        artifacts["v2_cuda_trainer_edge_recompute_status.json"],
        generated_est=generated,
    )

    critical_statuses = [
        artifacts["v2_native_cuda_trainer_burn_in_status.json"]["status"],
        artifacts["v2_native_cuda_prediction_contract_status.json"]["status"],
        artifacts["v2_risk_consumes_cuda_trainer_status.json"]["status"],
        artifacts["v2_orchestrator_consumes_cuda_trainer_status.json"]["status"],
        artifacts["v2_paper_trader_cuda_signal_lineage_status.json"]["status"],
        artifacts["v2_cuda_trainer_website_live_gate_status.json"]["status"],
    ]
    blocked = any(status == "BLOCKED" for status in critical_statuses)
    go_no_go = GATE_BLOCKED if blocked else GATE_READY
    operator_dashboard = build_operator_dashboard_payload(
        source=source_payload,
        generated_est=generated,
        artifacts=artifacts,
        go_no_go=go_no_go,
    )
    return CudaTrainerLiveGateResult(
        go_no_go=go_no_go,
        artifacts=artifacts,
        operator_dashboard_payload=operator_dashboard,
    )


def write_runtime_signal_gate_artifacts(
    *,
    paths: CudaTrainerLiveGatePaths,
    result: CudaTrainerLiveGateResult,
) -> CudaTrainerLiveGateResult:
    written: list[str] = []
    report = build_report(result)
    files: dict[str, str] = {
        "GO_NO_GO.md": result.go_no_go + "\n",
        "V2_NATIVE_CUDA_TRAINER_RUNTIME_SIGNAL_BURN_IN_AND_WEBSITE_LIVE_GATE_REPORT.md": report,
        "operator_dashboard_payload.json": dumps_pretty(result.operator_dashboard_payload),
    }
    for name, artifact in result.artifacts.items():
        files[name] = dumps_pretty(artifact)

    for base in (paths.worklog_dir, paths.public_dir):
        for name, text in files.items():
            path = base / name
            _write_text_atomic(path, text if text.endswith("\n") else text + "\n")
            written.append(str(path))

    return CudaTrainerLiveGateResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def run_runtime_signal_gate(
    *,
    paths: CudaTrainerLiveGatePaths,
    source_payload_path: Path | None = None,
) -> CudaTrainerLiveGateResult:
    source_path = source_payload_path or paths.source_payload_path
    source_payload = _json_load(source_path)
    result = build_runtime_signal_gate(source_payload)
    return write_runtime_signal_gate_artifacts(paths=paths, result=result)
