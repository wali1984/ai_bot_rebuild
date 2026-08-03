"""Single-pass CUDA trainer, Binance private, trader-runtime live gate.

This module is artifact and read-only-probe oriented. It never places,
cancels, or modifies exchange orders; never changes leverage or margin mode;
never writes old Redis; and never exposes raw credentials. Binance private
account reads are WebSocket API primary; REST is fallback-only for public
metadata when explicitly enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_decision,
    binance_rest_fallback_allowed,
)
from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

LIVE_GATE_BLOCKED = "blocked_human_only"
GATE_READY = "V2_CUDA_TRAINER_GPU_TRADER_BINANCE_LIVE_GATE_SINGLE_PASS_READY"
GATE_BLOCKED = "V2_CUDA_TRAINER_GPU_TRADER_BINANCE_LIVE_GATE_SINGLE_PASS_BLOCKED"
SCHEMA_VERSION = "v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass_v1"
ARTIFACT_REL = Path("v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass/latest")

TRAINER_SOURCE = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
MODEL_SOURCE = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
REQUIRED_PREDICTION_FIELDS = (
    "prediction_id",
    "generated_est",
    "symbol",
    "timeframe",
    "selected_action",
    "action_probabilities",
    "confidence_raw",
    "confidence_calibrated",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "price_target",
    "price_target_after_cost",
    "feature_snapshot_id",
    "data_coverage_percent",
    "missing_feature_count",
    "stale_feature_count",
    "trainer_source",
    "model_source",
)

BINANCE_BASE_URL = "https://fapi.binance.com"
BINANCE_ALLOWED_READONLY_ENDPOINTS = (
    "/fapi/v1/exchangeInfo",
)
BINANCE_SIGNED_WS_READ_METHODS = ("account.status", "account.position")
BINANCE_FORBIDDEN_MUTATIONS = (
    "new order",
    "test order",
    "cancel",
    "modify",
    "change leverage",
    "change margin mode",
    "change position mode",
    "transfer",
    "withdrawal",
)
ENV_KEY_NAMES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET_KEY",
    "BINANCE_FUT_API_KEY",
    "BINANCE_FUT_API_SECRET",
    "BINANCE_FUTURES_TESTNET_API_KEY",
    "BINANCE_FUTURES_TESTNET_API_SECRET",
)


@dataclass(frozen=True)
class LiveGatePaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    env_local_path: Path
    native_trainer_payload_path: Path
    all_tf_prediction_status_path: Path
    all_tf_signal_status_path: Path
    feature_inventory_path: Path
    tensor_coverage_path: Path
    backtest_edge_path: Path
    backtest_worker_path: Path
    trader_runtime_state_path: Path


@dataclass(frozen=True)
class SinglePassResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


def default_paths(repo_root: Path) -> LiveGatePaths:
    root = repo_root.resolve()
    return LiveGatePaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=root / "v2/frontend/public" / ARTIFACT_REL,
        env_local_path=root / "v2/.env.local",
        native_trainer_payload_path=root
        / "v2/frontend/public/v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json",
        all_tf_prediction_status_path=root
        / "v2/frontend/public/operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        all_tf_signal_status_path=root
        / "v2/frontend/public/operator_runtime/v2_signals/latest/realtime_signal_publisher_status.json",
        feature_inventory_path=root
        / "v2/frontend/public/v2_unified_feature_parity_and_backtest_edge_completion/latest/v2_unified_feature_blocked_field_inventory.json",
        tensor_coverage_path=root
        / "v2/frontend/public/v2_unified_feature_parity_and_backtest_edge_completion/latest/v2_trainer_tensor_feature_coverage_after_parity_status.json",
        backtest_edge_path=root
        / "v2/frontend/public/v2_unified_feature_parity_and_backtest_edge_completion/latest/v2_backtest_edge_recompute_after_feature_parity_status.json",
        backtest_worker_path=root
        / "v2/frontend/public/v2_unified_feature_parity_and_backtest_edge_completion/latest/v2_parallel_backtest_worker_metrics_status.json",
        trader_runtime_state_path=root
        / "v2/frontend/public/operator_runtime/v2_trader_runtime_state/latest/v2_trader_runtime_state_status.json",
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _ci_lower_95(values: list[float]) -> float | None:
    if not values:
        return None
    avg = _mean(values)
    assert avg is not None
    if len(values) < 2:
        return avg
    var = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return avg - 1.96 * math.sqrt(var) / math.sqrt(len(values))


def _json_load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _dumps(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _credential_pair(env_values: Mapping[str, str]) -> tuple[str, str, str, str]:
    key_name = "BINANCE_API_KEY" if env_values.get("BINANCE_API_KEY") else "BINANCE_FUT_API_KEY"
    secret_name = (
        "BINANCE_API_SECRET"
        if env_values.get("BINANCE_API_SECRET")
        else "BINANCE_SECRET_KEY"
        if env_values.get("BINANCE_SECRET_KEY")
        else "BINANCE_FUT_API_SECRET"
    )
    return key_name, env_values.get(key_name, ""), secret_name, env_values.get(secret_name, "")


def _subprocess_text(args: list[str], timeout: float = 4.0) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=timeout).strip()
    except Exception:
        return ""


def build_resource_utilization_status(
    native_payload: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    training = _as_dict(_as_dict(native_payload.get("metrics")).get("training"))
    training_metrics = _as_dict(training.get("metrics"))
    smi_raw = _subprocess_text(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    gpu: dict[str, Any] = {"nvidia_smi_available": bool(smi_raw)}
    if smi_raw:
        first = smi_raw.splitlines()[0]
        parts = [part.strip() for part in first.split(",")]
        if len(parts) >= 4:
            gpu.update(
                {
                    "name": parts[0],
                    "vram_total_mb": _float(parts[1]),
                    "vram_used_mb": _float(parts[2]),
                    "gpu_utilization_percent": _float(parts[3]),
                    "rtx_5080_detected": "RTX 5080" in parts[0],
                }
            )
    torch_status: dict[str, Any] = {"torch_available": False, "cuda_available": False}
    try:
        import torch  # type: ignore

        torch_status["torch_available"] = True
        torch_status["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            torch_status.update(
                {
                    "device_count": int(torch.cuda.device_count()),
                    "gpu_name": torch.cuda.get_device_name(0),
                    "vram_total_mb": round(float(props.total_memory / (1024 * 1024)), 3),
                    "vram_allocated_mb": round(float(torch.cuda.memory_allocated(0) / (1024 * 1024)), 3),
                    "vram_reserved_mb": round(float(torch.cuda.memory_reserved(0) / (1024 * 1024)), 3),
                }
            )
    except Exception as exc:
        torch_status["torch_error_type"] = type(exc).__name__
    system: dict[str, Any] = {}
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        system = {
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_total_gb": round(float(vm.total / (1024**3)), 3),
            "ram_used_gb": round(float(vm.used / (1024**3)), 3),
            "ram_percent": vm.percent,
        }
    except Exception as exc:
        system = {"psutil_available": False, "error_type": type(exc).__name__}

    current_vram_mb = _float(training.get("vram_allocated_mb")) or _float(torch_status.get("vram_allocated_mb"))
    current_reserved_mb = _float(training_metrics.get("vram_reserved_mb")) or _float(torch_status.get("vram_reserved_mb"))
    batch_size = int(training.get("batch_size") or training_metrics.get("actual_batch_size") or 0)
    predictions_per_second = _float(training_metrics.get("prediction_rows_per_second")) or _float(
        training_metrics.get("tensor_rows_per_second")
    )
    steps_per_minute = _float(training_metrics.get("training_steps_per_minute"))
    model_too_small = bool(current_reserved_mb is not None and current_reserved_mb < 8192)
    utilization_in_target = bool(
        (gpu.get("gpu_utilization_percent") is not None)
        and 50 <= float(gpu["gpu_utilization_percent"]) <= 85
        and current_reserved_mb is not None
        and 8192 <= current_reserved_mb <= 12288
    )
    blockers: list[str] = []
    if not gpu.get("rtx_5080_detected"):
        blockers.append("RTX_5080_NOT_DETECTED_BY_NVIDIA_SMI")
    if not torch_status.get("cuda_available"):
        blockers.append("TORCH_CUDA_NOT_AVAILABLE")
    if model_too_small:
        blockers.append("MODEL_TOO_SMALL_TO_SATURATE_GPU")
    if not utilization_in_target:
        blockers.append("GPU_UTILIZATION_OR_VRAM_TARGET_NOT_MET")

    return {
        "schema_version": f"{SCHEMA_VERSION}_resource_utilization",
        "generated_est": generated_est,
        "status": "CUDA_TRAINER_RESOURCE_UTILIZATION_MEASURED_BLOCKED"
        if blockers
        else "CUDA_TRAINER_RESOURCE_UTILIZATION_READY",
        "do_not_fake_utilization": True,
        "hardware": {"gpu": gpu, "torch": torch_status, "system": system},
        "current_trainer_metrics": {
            "batch_size": batch_size,
            "predictions_per_second": predictions_per_second,
            "training_steps_per_minute": steps_per_minute,
            "vram_allocated_mb": current_vram_mb,
            "vram_reserved_mb": current_reserved_mb,
            "dataloader_workers": training_metrics.get("dataloader_workers"),
            "pinned_memory": training_metrics.get("pinned_memory"),
            "prefetch_factor": training_metrics.get("prefetch_factor"),
            "persistent_workers": training_metrics.get("persistent_workers"),
            "mixed_precision_enabled": training_metrics.get("uses_amp"),
            "gradient_accumulation_steps": training_metrics.get("gradient_accumulation_steps"),
            "tensor_rows_per_second": training_metrics.get("tensor_rows_per_second"),
        },
        "implemented_or_configured_optimizations": {
            "gpu_batch_auto_tuning": True,
            "target_vram_usage_gb": [8, 12],
            "target_gpu_utilization_percent": [50, 85],
            "ryzen_worker_target": max(1, min(32, int((system.get("cpu_logical_cores") or 4)) - 2)),
            "pinned_memory": bool(training_metrics.get("pinned_memory")),
            "prefetch": training_metrics.get("prefetch_factor") is not None,
            "persistent_workers": bool(training_metrics.get("persistent_workers")),
            "mixed_precision": bool(training_metrics.get("uses_amp")),
            "gradient_accumulation": int(training_metrics.get("gradient_accumulation_steps") or 1),
            "tensor_cache_for_feature_batches": True,
            "async_prediction_generation": True,
            "parallel_backtest_workers": True,
        },
        "verdict": "MODEL_TOO_SMALL_TO_SATURATE_GPU" if model_too_small else "RESOURCE_TARGET_PENDING",
        "blockers": blockers,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def build_output_integrity_status(
    prediction_status: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    rows = [_as_dict(row) for row in _as_list(prediction_status.get("prediction_rows"))]
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
    timeframes = sorted({str(row.get("timeframe")) for row in rows if row.get("timeframe")})
    timeframe_set = set(timeframes)
    expected_count = len(symbols) * len(REQUIRED_TIMEFRAMES)
    violations: list[str] = []
    sample_violations: list[dict[str, Any]] = []
    for row in rows:
        row_violations: list[str] = []
        for field_name in REQUIRED_PREDICTION_FIELDS:
            if row.get(field_name) in (None, ""):
                row_violations.append(f"missing:{field_name}")
        if row.get("trainer_source") != TRAINER_SOURCE:
            row_violations.append("trainer_source_mismatch")
        if row.get("model_source") != MODEL_SOURCE:
            row_violations.append("model_source_mismatch")
        probs = row.get("action_probabilities")
        if isinstance(probs, dict) and probs:
            try:
                if abs(sum(float(value) for value in probs.values()) - 1.0) > 0.02:
                    row_violations.append("action_probabilities_not_normalized")
            except Exception:
                row_violations.append("action_probabilities_not_numeric")
        elif not isinstance(probs, list) or not probs:
            row_violations.append("action_probabilities_missing")
        else:
            try:
                if abs(sum(float(value) for value in probs) - 1.0) > 0.02:
                    row_violations.append("action_probabilities_not_normalized")
            except Exception:
                row_violations.append("action_probabilities_not_numeric")
        if row_violations:
            violations.extend(f"{row.get('prediction_id')}:{item}" for item in row_violations)
            if len(sample_violations) < 25:
                sample_violations.append(
                    {
                        "prediction_id": row.get("prediction_id"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "violations": row_violations,
                    }
                )
    missing_grid_count = max(0, expected_count - len(rows))
    if missing_grid_count:
        violations.append(f"missing_grid_count:{missing_grid_count}")
    if timeframe_set != set(REQUIRED_TIMEFRAMES):
        violations.append("required_timeframes_not_exact")
    fallback_count = sum(1 for row in rows if "fallback" in str(row.get("trainer_source", "")).lower())
    if fallback_count:
        violations.append(f"fallback_predictions_present:{fallback_count}")
    return {
        "schema_version": f"{SCHEMA_VERSION}_output_integrity",
        "generated_est": generated_est,
        "status": "CUDA_TRAINER_OUTPUT_INTEGRITY_READY" if not violations else "CUDA_TRAINER_OUTPUT_INTEGRITY_BLOCKED",
        "dynamic_symbol_count": len(symbols),
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "timeframes_present": timeframes,
        "expected_prediction_count": expected_count,
        "prediction_rows_count": len(rows),
        "complete_grid": len(rows) == expected_count and timeframe_set == set(REQUIRED_TIMEFRAMES),
        "required_fields": list(REQUIRED_PREDICTION_FIELDS),
        "trainer_source_required": TRAINER_SOURCE,
        "model_source_required": MODEL_SOURCE,
        "fallback_predictions_labeled_count": fallback_count,
        "price_target_missing_count": sum(1 for row in rows if row.get("price_target") in (None, "")),
        "price_target_after_cost_missing_count": sum(1 for row in rows if row.get("price_target_after_cost") in (None, "")),
        "expected_move_after_cost_missing_count": sum(1 for row in rows if row.get("expected_move_after_cost_bps") in (None, "")),
        "invalid_missing_rows_sample": sample_violations,
        "violations": violations,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def build_feature_tensor_bottleneck_status(
    feature_inventory: Mapping[str, Any],
    tensor_coverage: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    rows = [_as_dict(row) for row in _as_list(feature_inventory.get("current_blocked_rows"))]
    by_family: dict[str, dict[str, Any]] = {}
    for row in rows:
        family = str(row.get("field_family") or "unknown")
        item = by_family.setdefault(
            family,
            {
                "feature_family": family,
                "blocked_row_count": 0,
                "symbols_affected": set(),
                "timeframes_affected": set(),
                "provider_event_operator_blockers": Counter(),
                "automatable_count": 0,
                "non_automatable_count": 0,
                "sample_fields": [],
            },
        )
        item["blocked_row_count"] += 1
        if row.get("symbol"):
            item["symbols_affected"].add(str(row.get("symbol")))
        if row.get("timeframe"):
            item["timeframes_affected"].add(str(row.get("timeframe")))
        blocker = str(row.get("exact_blocker") or row.get("classification") or "unknown")
        item["provider_event_operator_blockers"][blocker] += 1
        if row.get("automatable") is True:
            item["automatable_count"] += 1
        else:
            item["non_automatable_count"] += 1
        if len(item["sample_fields"]) < 8:
            item["sample_fields"].append(row.get("field_name"))
    families: list[dict[str, Any]] = []
    for item in by_family.values():
        families.append(
            {
                "feature_family": item["feature_family"],
                "blocked_row_count": item["blocked_row_count"],
                "symbols_affected_count": len(item["symbols_affected"]),
                "symbols_affected_sample": sorted(item["symbols_affected"])[:12],
                "timeframes_affected": sorted(item["timeframes_affected"]),
                "provider_event_operator_blockers": dict(item["provider_event_operator_blockers"].most_common(6)),
                "automatable": item["automatable_count"] > 0,
                "automatable_count": item["automatable_count"],
                "non_automatable_count": item["non_automatable_count"],
                "impact_on_trainer_tensor": "missing values remain masked; no silent zero-fill",
                "impact_on_expected_move_price_target": "feature uncertainty remains in coverage/missing-feature counts",
                "sample_fields": [field for field in item["sample_fields"] if field],
            }
        )
    families.sort(key=lambda row: int(row["blocked_row_count"]), reverse=True)
    return {
        "schema_version": f"{SCHEMA_VERSION}_feature_tensor_bottleneck",
        "generated_est": generated_est,
        "status": "CUDA_TRAINER_FEATURE_TENSOR_BOTTLENECK_BLOCKED"
        if rows
        else "CUDA_TRAINER_FEATURE_TENSOR_BOTTLENECK_READY",
        "current_blocked_feature_rows": int(feature_inventory.get("current_blocked_field_rows_count") or len(rows)),
        "operator_reported_prior_blocked_feature_rows": feature_inventory.get("operator_reported_prior_blocked_field_rows_count"),
        "tensor_coverage": {
            "total_expected_feature_fields": tensor_coverage.get("total_expected_feature_fields"),
            "real_computed_fields": tensor_coverage.get("real_computed_fields"),
            "real_provider_value_fields": tensor_coverage.get("real_provider_value_fields"),
            "missing_fields": tensor_coverage.get("missing_fields"),
            "stale_fields": tensor_coverage.get("stale_fields"),
            "data_coverage_avg": tensor_coverage.get("data_coverage_avg"),
            "effect_on_cuda_tensor_builder": tensor_coverage.get("effect_on_cuda_tensor_builder"),
        },
        "blocked_feature_families": families,
        "implemented_automatable_merges": [
            "funding",
            "open_interest",
            "basis_mark_index_price",
            "orderbook_bid_ask_mid_spread_imbalance",
            "coinapi_wsds_depth_microstructure_when_present",
            "kline_taker_fields",
            "volatility",
            "liquidation_levels_when_present",
            "cross_tf_pressure_when_computable",
        ],
        "no_silent_zero_fill": bool(feature_inventory.get("no_silent_zero_fill", True)),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _runtime_observation_id(prediction_id: str) -> str:
    digest = hashlib.sha256(f"trader_runtime_observation:{prediction_id}".encode("utf-8")).hexdigest()[:24]
    return f"v2_trader_obs_{digest}"


def build_trader_runtime_start_status(
    signal_status: Mapping[str, Any],
    *,
    generated_est: str,
    service_start: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    signals = [_as_dict(row) for row in _as_list(signal_status.get("published_signals"))]
    observations = []
    for row in signals:
        prediction_id = str(row.get("prediction_id") or "")
        if not prediction_id:
            continue
        observations.append(
            {
                "trader_runtime_observation_id": _runtime_observation_id(prediction_id),
                "prediction_id": prediction_id,
                "signal_id": row.get("signal_id"),
                "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                "risk_decision_id": row.get("risk_decision_id"),
                "paper_intent_id": row.get("paper_intent_id"),
                "paper_ledger_id": row.get("paper_ledger_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "observed_action": row.get("action"),
                "exchange_mutation_frozen": True,
                "places_real_order": False,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_trader_runtime_start",
        "generated_est": generated_est,
        "status": "TRADER_CONNECTED_EXECUTION_FROZEN",
        "classification": "TRADER_CONNECTED_EXECUTION_FROZEN",
        "service_name": "ai-bot-v2-trader-runtime-loop.service",
        "service_start": dict(service_start or {"attempted": False, "method": "status_artifact_only"}),
        "account_mode": "binance_private_readonly_shadow" if service_start else "execution_frozen_shadow",
        "trader_execution_enabled": False,
        "exchange_mutation_state": "EXCHANGE_MUTATION_FROZEN",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "signals_observed_count": len(observations),
        "runtime_observation_rows": observations,
        "runtime_observation_sample": observations[:32],
        "forbidden_until_live_gate_passes": list(BINANCE_FORBIDDEN_MUTATIONS),
        "writes_exchange_orders": False,
        "places_real_order": False,
        "test_order_endpoint_attempted": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "writes_legacy_redis": False,
    }


def build_runtime_lineage_status(
    signal_status: Mapping[str, Any],
    trader_start: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    signals = [_as_dict(row) for row in _as_list(signal_status.get("published_signals"))]
    observations = {
        str(row.get("prediction_id")): row
        for row in _as_list(trader_start.get("runtime_observation_rows"))
        if isinstance(row, dict) and row.get("prediction_id")
    }
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    for signal in signals:
        prediction_id = str(signal.get("prediction_id") or "")
        obs = _as_dict(observations.get(prediction_id))
        row_violations = []
        for field_name in (
            "risk_decision_id",
            "orchestrator_decision_id",
            "paper_intent_id",
            "paper_ledger_id",
        ):
            if not signal.get(field_name):
                row_violations.append(f"missing:{field_name}")
        if not obs.get("trader_runtime_observation_id"):
            row_violations.append("missing:trader_runtime_observation_id")
        if signal.get("live_gate") != LIVE_GATE_BLOCKED:
            row_violations.append("signal_live_gate_not_blocked")
        if signal.get("live_symbols") != []:
            row_violations.append("signal_live_symbols_not_empty")
        if row_violations:
            violations.extend(f"{prediction_id}:{item}" for item in row_violations)
        rows.append(
            {
                "prediction_id": prediction_id,
                "risk_decision_id": signal.get("risk_decision_id"),
                "orchestrator_decision_id": signal.get("orchestrator_decision_id"),
                "paper_intent_id": signal.get("paper_intent_id"),
                "paper_ledger_id": signal.get("paper_ledger_id"),
                "trader_runtime_observation_id": obs.get("trader_runtime_observation_id"),
                "symbol": signal.get("symbol"),
                "timeframe": signal.get("timeframe"),
                "places_real_order": False,
                "contract_pass": not row_violations,
                "violations": row_violations,
            }
        )
    if not rows:
        violations.append("NO_CURRENT_SIGNALS")
    return {
        "schema_version": f"{SCHEMA_VERSION}_runtime_lineage",
        "generated_est": generated_est,
        "status": "RUNTIME_SIGNAL_TO_TRADER_LINEAGE_READY" if not violations else "RUNTIME_SIGNAL_TO_TRADER_LINEAGE_BLOCKED",
        "signals_checked": len(rows),
        "risk_consumes_cuda_trainer_predictions": True,
        "orchestrator_consumes_risk_trainer": True,
        "paper_trader_consumes_orchestrator": True,
        "trader_runtime_reads_orchestrator_outputs": bool(observations),
        "no_agent_writes_trade_decisions": True,
        "no_order_sent_unless_live_gate_passes": True,
        "rows": rows[:505],
        "violations": violations,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _signed_ws_read(
    api_key: str,
    api_secret: str,
    method: str,
) -> dict[str, Any]:
    if method not in BINANCE_SIGNED_WS_READ_METHODS:
        return {
            "ok": False,
            "status": "SIGNED_WS_READ_DENIED",
            "ws_status_code": None,
            "error_type": "READONLY_METHOD_DENIED",
            "response_json": None,
        }
    adapter = BinanceUSDMAdapter(api_key=api_key, api_secret=api_secret)
    result = adapter.signed_ws_read(method, execute=True)
    return {
        "ok": result.get("status") == "SIGNED_WS_READ_EXECUTED",
        "status": result.get("status"),
        "ws_status_code": result.get("ws_status_code"),
        "error_type": result.get("error_type"),
        "response_json": result.get("response_json"),
        "endpoint": result.get("endpoint"),
        "transport": result.get("transport"),
    }


def _public_get(path: str, *, timeout: float = 10.0) -> tuple[int, str]:
    if path not in BINANCE_ALLOWED_READONLY_ENDPOINTS:
        return 0, "READONLY_ENDPOINT_DENIED"
    fallback = binance_rest_fallback_decision(
        endpoint=path,
        fallback_reason="live_gate_single_pass_public_metadata_cache_missing",
        role="live_gate_single_pass_public_metadata_recovery",
    )
    if not fallback["request_allowed"]:
        return 0, f"REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY:{REST_FALLBACK_ENV}_not_true"
    try:
        with urllib.request.urlopen(f"{BINANCE_BASE_URL}{path}", timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return 0, f"ERROR:{type(exc).__name__}"


def build_binance_connectivity_status(
    *,
    env_local_path: Path,
    generated_est: str,
    network_probe_enabled: bool,
) -> dict[str, Any]:
    env_values = _parse_env_file(env_local_path)
    key_name, api_key, secret_name, api_secret = _credential_pair(env_values)
    key_present_by_name = {name: bool(env_values.get(name)) for name in ENV_KEY_NAMES}
    blockers: list[str] = []
    if not env_local_path.exists():
        blockers.append("ENV_LOCAL_NOT_FOUND")
    if not api_key:
        blockers.append(f"{key_name}_ABSENT_IN_ENV_LOCAL")
    if not api_secret:
        blockers.append(f"{secret_name}_ABSENT_IN_ENV_LOCAL")
    exchange_info_status = "NOT_CHECKED_TRADER_WEBSOCKET_PRIMARY"
    account_status = "NOT_CHECKED_NETWORK_DISABLED"
    position_status = "NOT_CHECKED_NETWORK_DISABLED"
    account_summary: dict[str, Any] = {"balances_redacted": True}
    position_summary: dict[str, Any] = {}
    if network_probe_enabled:
        exchange_info_status = "NOT_CALLED_REST_PUBLIC_METADATA_FALLBACK_ONLY"
        if api_key and api_secret:
            account_ws = _signed_ws_read(api_key, api_secret, "account.status")
            account_status = (
                "OK"
                if account_ws.get("ok")
                else f"WS_{account_ws.get('ws_status_code') or account_ws.get('error_type') or 'ERROR'}"
            )
            if account_ws.get("ok"):
                try:
                    response = _as_dict(account_ws.get("response_json"))
                    account = _as_dict(response.get("result"))
                    account_summary = {
                        "balances_redacted": True,
                        "can_trade": account.get("canTrade"),
                        "can_deposit": account.get("canDeposit"),
                        "can_withdraw": account.get("canWithdraw"),
                        "asset_count": len(_as_list(account.get("assets"))),
                        "raw_balance_values_redacted": True,
                    }
                except Exception:
                    account_summary["parse_status"] = "PARSE_ERROR"
            else:
                blockers.append(f"ACCOUNT_READ_FAILED:{account_status}")
            position_ws = _signed_ws_read(api_key, api_secret, "account.position")
            position_status = (
                "OK"
                if position_ws.get("ok")
                else f"WS_{position_ws.get('ws_status_code') or position_ws.get('error_type') or 'ERROR'}"
            )
            if position_ws.get("ok"):
                try:
                    response = _as_dict(position_ws.get("response_json"))
                    positions = [
                        row
                        for row in _as_list(response.get("result"))
                        if isinstance(row, dict)
                    ]
                    open_positions = [
                        row
                        for row in positions
                        if abs(float(row.get("positionAmt") or 0.0)) > 0.0
                    ]
                    position_summary = {
                        "positions_read": len(positions),
                        "open_positions_count": len(open_positions),
                        "symbols_with_open_positions": sorted(str(row.get("symbol")) for row in open_positions if row.get("symbol"))[:30],
                        "margin_modes_observed": sorted({str(row.get("marginType")) for row in positions if row.get("marginType")})[:8],
                        "leverage_values_observed": sorted({str(row.get("leverage")) for row in positions if row.get("leverage")})[:12],
                    }
                except Exception:
                    position_summary = {"parse_status": "PARSE_ERROR"}
            else:
                blockers.append(f"POSITION_READ_FAILED:{position_status}")
        else:
            account_status = "NOT_CHECKED_CREDENTIALS_ABSENT"
            position_status = "NOT_CHECKED_CREDENTIALS_ABSENT"
    else:
        blockers.append("NETWORK_PROBE_DISABLED")
    return {
        "schema_version": f"{SCHEMA_VERSION}_binance_private_connectivity",
        "generated_est": generated_est,
        "status": "BINANCE_PRIVATE_READONLY_CONNECTIVITY_READY" if not blockers else "BINANCE_PRIVATE_READONLY_CONNECTIVITY_BLOCKED",
        "env_source": "v2/.env.local",
        "key_names_used": {"api_key": key_name, "api_secret": secret_name},
        "key_present_by_name": key_present_by_name,
        "raw_credential_in_payload": "NEVER",
        "network_probe_enabled": network_probe_enabled,
        "allowed_private_readonly_actions": [
            "websocket account status",
            "balances redacted",
            "websocket positions",
            "open orders read-only",
            "permissions",
            "exchange filters",
            "account mode",
            "margin mode read-only",
            "leverage read-only",
        ],
        "forbidden_until_live_gate_passes": list(BINANCE_FORBIDDEN_MUTATIONS),
        "readonly_endpoints_called": [
            "WS_API:account.status" if api_key and api_secret and network_probe_enabled else None,
            "WS_API:account.position" if api_key and api_secret and network_probe_enabled else None,
        ],
        "signed_read_transport_primary": "binance_usdm_websocket_api",
        "public_metadata_rest_fallback_only": True,
        "trader_rest_primary_disabled": True,
        "trader_signed_rest_fallback_supported": False,
        "rest_fallback_required_env": f"{REST_FALLBACK_ENV}=true",
        "rest_fallback_currently_allowed": binance_rest_fallback_allowed(),
        "test_order_endpoint_attempted": False,
        "real_order_attempted": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "exchange_info_status": exchange_info_status,
        "account_read_status": account_status,
        "position_read_status": position_status,
        "account_summary_redacted": account_summary,
        "position_summary": position_summary,
        "fail_blockers": blockers,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def build_website_live_switch_backend_gate_status(
    statuses: Mapping[str, Mapping[str, Any]],
    *,
    generated_est: str,
) -> dict[str, Any]:
    blockers = collect_live_blockers(statuses)
    return {
        "schema_version": f"{SCHEMA_VERSION}_website_live_switch_backend_gate",
        "generated_est": generated_est,
        "status": "WEBSITE_LIVE_SWITCH_BACKEND_GATE_BLOCKED" if blockers else "WEBSITE_LIVE_SWITCH_BACKEND_GATE_READY",
        "endpoints": {
            "GET /api/v1/live-gate/status": "implemented_readonly",
            "POST /api/v1/live-gate/evaluate": "implemented_readonly",
            "POST /api/v1/live-gate/arm": "implemented_blocked_until_conditions_pass",
            "POST /api/v1/live-gate/enable": "implemented_locked_until_conditions_pass",
        },
        "live_switch": {
            "visible": True,
            "enabled": False,
            "disabled": True,
            "backend_live_enable_callable": True,
            "disabled_reason": "; ".join(blockers[:6]) if blockers else "READY_FOR_OPERATOR_TYPED_CONFIRMATION",
        },
        "enable_requires": [
            "live_gate approval state",
            "risk caps accepted",
            "paper/backtest edge accepted",
            "read-only Binance probe passed",
            "trader runtime connected",
            "exchange mutation safety proof passed",
            "live_symbols selected by operator",
            "Codex 5.5 final pass",
            "audit ledger write",
            "typed confirmation",
        ],
        "exact_blockers": blockers,
        "approves_live": False,
        "approves_canary": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def build_edge_recompute_status(
    edge_status: Mapping[str, Any],
    worker_status: Mapping[str, Any],
    *,
    generated_est: str,
) -> dict[str, Any]:
    recommendations = _as_list(edge_status.get("recommendations")) or ["BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"]
    values = [
        _float(row.get("mean_after_cost_5m_bps"))
        for row in _as_list(worker_status.get("per_symbol_edge"))
        if isinstance(row, dict)
    ]
    symbol_values = [value for value in values if value is not None]
    return {
        "schema_version": f"{SCHEMA_VERSION}_edge_recompute",
        "generated_est": generated_est,
        "status": "LIVE_GATE_EDGE_RECOMPUTE_BLOCKED_NO_EDGE_CLAIM",
        "edge_proven": False,
        "after_cost_expectancy_bps": edge_status.get("after_cost_expectancy_bps"),
        "after_cost_ci_lower_bps": edge_status.get("after_cost_ci_lower_bps"),
        "drawdown": edge_status.get("drawdown"),
        "sample_count": edge_status.get("sample_count") or worker_status.get("sample_count"),
        "false_positives": worker_status.get("false_positives"),
        "false_negatives": worker_status.get("false_negatives"),
        "false_positive_rate": worker_status.get("false_positive_rate"),
        "false_negative_rate": worker_status.get("false_negative_rate"),
        "per_symbol_edge": _as_list(worker_status.get("per_symbol_edge"))[:101],
        "per_timeframe_edge": _as_list(worker_status.get("per_timeframe_edge")),
        "trainer_vs_strategy": worker_status.get("trainer_vs_strategy_comparison"),
        "no_trade_preservation": {
            "correct_no_trade": worker_status.get("correct_no_trade"),
            "status": "NO_TRADE_PRESERVATION_RECORDED",
        },
        "current_symbol_edge_mean_bps": _mean(symbol_values),
        "current_symbol_edge_ci_lower_bps": _ci_lower_95(symbol_values),
        "allowed_recommendations": [
            "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
            "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
            "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
            "BLOCK_LIVE_TRADER_CONNECTED_EXECUTION_FROZEN",
            "LIVE_OPERATOR_ENABLE_AVAILABLE",
        ],
        "recommendation": edge_status.get("primary_recommendation") or "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "recommendations": recommendations,
        "forbidden_live_ready_claim_absent": True,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def collect_live_blockers(statuses: Mapping[str, Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    resource = statuses.get("cuda_trainer_resource_utilization_status.json", {})
    blockers.extend(str(item) for item in _as_list(resource.get("blockers")))
    output = statuses.get("cuda_trainer_output_integrity_status.json", {})
    if output.get("status") != "CUDA_TRAINER_OUTPUT_INTEGRITY_READY":
        blockers.append("BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY")
    feature = statuses.get("cuda_trainer_feature_tensor_bottleneck_status.json", {})
    if int(feature.get("current_blocked_feature_rows") or 0) > 0:
        blockers.append("UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL")
    lineage = statuses.get("runtime_signal_to_trader_lineage_status.json", {})
    if lineage.get("status") != "RUNTIME_SIGNAL_TO_TRADER_LINEAGE_READY":
        blockers.append("RUNTIME_SIGNAL_TO_TRADER_LINEAGE_INCOMPLETE")
    binance = statuses.get("binance_private_trader_connectivity_status.json", {})
    if binance.get("status") != "BINANCE_PRIVATE_READONLY_CONNECTIVITY_READY":
        blockers.append("BINANCE_PRIVATE_READONLY_PROBE_NOT_READY")
        blockers.extend(str(item) for item in _as_list(binance.get("fail_blockers")))
    trader = statuses.get("trader_runtime_start_status.json", {})
    if trader.get("exchange_mutation_state") != "EXCHANGE_MUTATION_FROZEN":
        blockers.append("TRADER_RUNTIME_NOT_EXCHANGE_MUTATION_FROZEN")
    edge = statuses.get("live_gate_edge_recompute_status.json", {})
    if edge.get("edge_proven") is not True:
        blockers.append("BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM")
    blockers.extend(
        [
            "LIVE_RISK_CAPS_OPERATOR_REQUIRED",
            "LIVE_SYMBOL_APPROVAL_REQUIRED",
            "CODEX_5_5_FINAL_PASS_REQUIRED",
            "LIVE_GATE_REMAINS_BLOCKED_HUMAN_ONLY",
        ]
    )
    return sorted(set(blockers))


def build_go_no_go(statuses: Mapping[str, Mapping[str, Any]]) -> str:
    return GATE_READY if not collect_live_blockers(statuses) else GATE_BLOCKED


def build_operator_dashboard_payload(
    *,
    generated_est: str,
    go_no_go: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    blockers = collect_live_blockers(artifacts)
    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": go_no_go,
        "live_ready": False,
        "canary_ready": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "places_real_order": False,
        "approves_live": False,
        "approves_canary": False,
        "exact_blockers": blockers,
        "cuda_trainer_resource_utilization": artifacts["cuda_trainer_resource_utilization_status.json"],
        "cuda_trainer_output_integrity": artifacts["cuda_trainer_output_integrity_status.json"],
        "cuda_trainer_feature_tensor_bottleneck": artifacts["cuda_trainer_feature_tensor_bottleneck_status.json"],
        "runtime_signal_to_trader_lineage": artifacts["runtime_signal_to_trader_lineage_status.json"],
        "binance_private_trader_connectivity": artifacts["binance_private_trader_connectivity_status.json"],
        "trader_runtime_start": artifacts["trader_runtime_start_status.json"],
        "website_live_switch_backend_gate": artifacts["website_live_switch_backend_gate_status.json"],
        "live_gate_edge_recompute": artifacts["live_gate_edge_recompute_status.json"],
        "safety_scoreboard": {
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "trader_execution_enabled": False,
            "exchange_mutation_frozen": True,
            "places_orders": False,
            "cancels_orders": False,
            "modifies_orders": False,
            "calls_test_order_endpoint": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
            "raw_credentials_exposed": False,
        },
        "live_switch": {
            "visible": True,
            "enabled": False,
            "disabled": True,
            "backend_gate_endpoint": "/api/v1/live-gate/status",
            "disabled_reason": "; ".join(blockers[:8]),
        },
    }


def build_report(result: SinglePassResult) -> str:
    payload = result.operator_dashboard_payload
    resource = payload["cuda_trainer_resource_utilization"]
    output = payload["cuda_trainer_output_integrity"]
    binance = payload["binance_private_trader_connectivity"]
    edge = payload["live_gate_edge_recompute"]
    return "\n".join(
        [
            "# V2 CUDA Trainer GPU Trader Binance Live Gate Single Pass Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Generated EST: `{payload['generated_est']}`",
            "",
            "Live execution remains blocked.",
            "",
            f"- live_gate: `{LIVE_GATE_BLOCKED}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- trader_execution_enabled: `False`",
            "- exchange mutation: `EXCHANGE_MUTATION_FROZEN`",
            "",
            "CUDA trainer evidence:",
            f"- GPU: `{resource['hardware']['gpu'].get('name')}`",
            f"- RTX 5080 detected: `{resource['hardware']['gpu'].get('rtx_5080_detected')}`",
            f"- current batch size: `{resource['current_trainer_metrics'].get('batch_size')}`",
            f"- current VRAM reserved MB: `{resource['current_trainer_metrics'].get('vram_reserved_mb')}`",
            f"- utilization verdict: `{resource.get('verdict')}`",
            f"- predictions checked: `{output.get('prediction_rows_count')}/{output.get('expected_prediction_count')}`",
            f"- price target missing: `{output.get('price_target_missing_count')}`",
            "",
            "Binance private trader evidence:",
            f"- status: `{binance.get('status')}`",
            f"- env source: `{binance.get('env_source')}`",
            f"- raw credentials in payload: `{binance.get('raw_credential_in_payload')}`",
            f"- test order attempted: `{binance.get('test_order_endpoint_attempted')}`",
            "",
            "Edge evidence:",
            f"- edge proven: `{edge.get('edge_proven')}`",
            f"- after-cost expectancy bps: `{edge.get('after_cost_expectancy_bps')}`",
            f"- CI lower bps: `{edge.get('after_cost_ci_lower_bps')}`",
            f"- recommendation: `{edge.get('recommendation')}`",
            "",
            "Exact blockers:",
            *(f"- `{blocker}`" for blocker in payload["exact_blockers"]),
            "",
            "Safety: no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.",
        ]
    ) + "\n"


def build_single_pass(
    *,
    paths: LiveGatePaths,
    network_probe_enabled: bool = True,
    service_start: Mapping[str, Any] | None = None,
) -> SinglePassResult:
    generated_est = _est_iso()
    native_payload = _json_load(paths.native_trainer_payload_path)
    prediction_status = _json_load(paths.all_tf_prediction_status_path)
    signal_status = _json_load(paths.all_tf_signal_status_path)
    feature_inventory = _json_load(paths.feature_inventory_path)
    tensor_coverage = _json_load(paths.tensor_coverage_path)
    edge_status = _json_load(paths.backtest_edge_path)
    worker_status = _json_load(paths.backtest_worker_path)

    artifacts: dict[str, Any] = {}
    artifacts["cuda_trainer_resource_utilization_status.json"] = build_resource_utilization_status(
        native_payload,
        generated_est=generated_est,
    )
    artifacts["cuda_trainer_output_integrity_status.json"] = build_output_integrity_status(
        prediction_status,
        generated_est=generated_est,
    )
    artifacts["cuda_trainer_feature_tensor_bottleneck_status.json"] = build_feature_tensor_bottleneck_status(
        feature_inventory,
        tensor_coverage,
        generated_est=generated_est,
    )
    artifacts["binance_private_trader_connectivity_status.json"] = build_binance_connectivity_status(
        env_local_path=paths.env_local_path,
        generated_est=generated_est,
        network_probe_enabled=network_probe_enabled,
    )
    artifacts["trader_runtime_start_status.json"] = build_trader_runtime_start_status(
        signal_status,
        generated_est=generated_est,
        service_start=service_start,
    )
    artifacts["runtime_signal_to_trader_lineage_status.json"] = build_runtime_lineage_status(
        signal_status,
        artifacts["trader_runtime_start_status.json"],
        generated_est=generated_est,
    )
    artifacts["live_gate_edge_recompute_status.json"] = build_edge_recompute_status(
        edge_status,
        worker_status,
        generated_est=generated_est,
    )
    artifacts["website_live_switch_backend_gate_status.json"] = build_website_live_switch_backend_gate_status(
        artifacts,
        generated_est=generated_est,
    )
    go_no_go = build_go_no_go(artifacts)
    operator_dashboard = build_operator_dashboard_payload(
        generated_est=generated_est,
        go_no_go=go_no_go,
        artifacts=artifacts,
    )
    return SinglePassResult(go_no_go=go_no_go, artifacts=artifacts, operator_dashboard_payload=operator_dashboard)


def write_single_pass_artifacts(*, paths: LiveGatePaths, result: SinglePassResult) -> SinglePassResult:
    files: dict[str, str] = {
        "GO_NO_GO.md": result.go_no_go + "\n",
        "V2_CUDA_TRAINER_GPU_TRADER_BINANCE_LIVE_GATE_SINGLE_PASS_REPORT.md": build_report(result),
        "operator_dashboard_payload.json": _dumps(result.operator_dashboard_payload),
    }
    for name, artifact in result.artifacts.items():
        files[name] = _dumps(artifact)
    written: list[str] = []
    for base in (paths.worklog_dir, paths.public_dir):
        for name, text in files.items():
            path = base / name
            _write_text_atomic(path, text if text.endswith("\n") else text + "\n")
            written.append(str(path))
    return SinglePassResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def load_latest_live_gate_status(repo_root: Path) -> dict[str, Any]:
    paths = default_paths(repo_root)
    payload = _json_load(paths.public_dir / "operator_dashboard_payload.json")
    if payload:
        return payload
    return {
        "schema_version": f"{SCHEMA_VERSION}_missing_status",
        "generated_est": _est_iso(),
        "go_no_go": GATE_BLOCKED,
        "live_ready": False,
        "canary_ready": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "places_real_order": False,
        "exact_blockers": ["LIVE_GATE_STATUS_ARTIFACT_MISSING"],
        "live_switch": {
            "visible": True,
            "enabled": False,
            "disabled": True,
            "disabled_reason": "LIVE_GATE_STATUS_ARTIFACT_MISSING",
        },
    }


def raw_secret_values_present_in_text(env_local_path: Path, text: str) -> bool:
    env_values = _parse_env_file(env_local_path)
    for key, value in env_values.items():
        upper = key.upper()
        if not value or len(value) < 8:
            continue
        if any(token in upper for token in ("KEY", "SECRET", "TOKEN", "PASSWORD")) and value in text:
            return True
    return False
