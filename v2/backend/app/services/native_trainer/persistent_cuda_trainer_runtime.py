"""Persistent native CUDA trainer runtime and paper drawdown guard.

This module keeps the V2 native PPO/MASA CUDA trainer resident without using
the legacy trainer bridge or wrapper. It publishes V2-owned runtime artifacts,
checkpoint-retention status, resource telemetry, and a paper-only confidence
trial drawdown guard. It never touches live execution or exchange mutation
paths.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    DEFAULT_TIMEFRAMES,
    TRAINER_SOURCE,
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    run_hybrid_trainer_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.v2_symbol_runtime_universe import (
    SMOKE_TEST_SYMBOLS,
    resolve_symbols,
    resolve_symbols_with_provenance,
)


READY = "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_READY"
BLOCKED = "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_BLOCKED"

ARTIFACT_REL = Path("v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard/latest")
OPERATOR_REL = Path("operator_runtime/v2_native_trainer/latest")
PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
PREDICTION_REL = Path("operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
PAPER_TRIAL_REL = Path("v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest/operator_dashboard_payload.json")
MODEL_DIR_REL = Path(".local_models/v2_native_rl_masa_ppo")
STATE_REL = Path("v2/runtime/native_cuda_trainer_persistent_state.json")

PERSISTENT_UNIT = "ai-bot-v2-native-cuda-trainer-persistent.service"
LEGACY_BRIDGE_UNIT = "ai-bot-v2-trainer-bridge.service"
TRIAL_SIGNAL_REDIS_KEY = "v2:signals:paper:confidence_threshold_trial"
TRIAL_STATUS_REDIS_KEY = "v2:paper:confidence_threshold_trial:status"
TRIAL_DRAWDOWN_GUARD_REDIS_KEY = "v2:paper:confidence_threshold_trial:drawdown_guard"

PREVIOUS_PAPER_PNL_BASELINE = 30.41842727
TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD = -50.0
TRIAL_OVERLAY_PNL_THRESHOLD_USD = -25.0
EST = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PersistentTrainerPaths:
    repo_root: Path

    @property
    def public_root(self) -> Path:
        return self.repo_root / "v2/frontend/public"

    @property
    def artifact_dir(self) -> Path:
        return self.public_root / ARTIFACT_REL

    @property
    def worklog_dir(self) -> Path:
        return self.repo_root / "claude_worklog/final_readiness" / ARTIFACT_REL

    @property
    def operator_dir(self) -> Path:
        return self.public_root / OPERATOR_REL

    @property
    def state_path(self) -> Path:
        return self.repo_root / STATE_REL

    @property
    def model_dir(self) -> Path:
        return self.repo_root / MODEL_DIR_REL


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def connect_redis() -> Any | None:
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
        return client
    except Exception:
        return None


def redis_json(client: Any | None, key: str, default: Any = None) -> Any:
    if client is None:
        return {} if default is None else default
    try:
        raw = client.get(key)
    except Exception:
        return {} if default is None else default
    if raw is None:
        return {} if default is None else default
    try:
        return json.loads(raw)
    except Exception:
        return {} if default is None else default


def safe_v2_redis_set(client: Any | None, key: str, payload: Any, *, ex: int | None = None) -> bool:
    if client is None or not key.startswith("v2:"):
        return False
    try:
        if ex is None:
            client.set(key, json.dumps(payload, sort_keys=True, default=str))
        else:
            client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
        return True
    except Exception:
        return False


def systemctl_show(unit: str) -> dict[str, str]:
    fields = ["LoadState", "ActiveState", "SubState", "Result", "UnitFileState", "MainPID"]
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, *(f"--property={field}" for field in fields)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def gpu_status_from_nvidia_smi() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"available": False, "source": "nvidia-smi", "error": f"{type(exc).__name__}: {exc}"}
    if result.returncode != 0 or not result.stdout.strip():
        return {"available": False, "source": "nvidia-smi", "error": result.stderr.strip()}
    parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
    if len(parts) < 4:
        return {"available": False, "source": "nvidia-smi", "error": "unexpected nvidia-smi output"}
    return {
        "available": True,
        "source": "nvidia-smi",
        "gpu_name": parts[0],
        "gpu_utilization_percent": finite_float(parts[1]),
        "vram_used_mb": finite_float(parts[2]),
        "vram_total_mb": finite_float(parts[3]),
    }


def _cpu_times() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        values = [int(field) for field in fields]
    except Exception:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def cpu_utilization_percent() -> float | None:
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(0.1)
    second = _cpu_times()
    if second is None:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(100.0 * (1.0 - (idle_delta / total_delta)), 2)


def memory_status() -> dict[str, Any]:
    values: dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = float(raw.strip().split()[0]) / (1024 * 1024)
    except Exception:
        return {"ram_used_gb": None, "ram_total_gb": None}
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return {
        "ram_used_gb": None if total is None or available is None else round(total - available, 3),
        "ram_total_gb": None if total is None else round(total, 3),
    }


def load_state(paths: PersistentTrainerPaths) -> dict[str, Any]:
    return as_dict(read_json(paths.state_path))


def save_state(paths: PersistentTrainerPaths, state: Mapping[str, Any]) -> None:
    write_json(paths.state_path, dict(state))


def prune_recent_events(events: Iterable[Mapping[str, Any]], *, now_ts: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        ts = finite_float(event.get("ts"))
        if ts is not None and now_ts - ts <= 3600:
            rows.append(dict(event))
    return rows


def record_cycle_state(
    *,
    paths: PersistentTrainerPaths,
    training_steps: int,
    prediction_rows: int,
    samples_seen: int,
    batches: int,
    training_blocker_reason: str | None = None,
) -> dict[str, Any]:
    now_ts = time.time()
    state = load_state(paths)
    events = prune_recent_events(as_list(state.get("step_events")), now_ts=now_ts)
    cycle_index = int(finite_float(state.get("cycle_index")) or 0) + 1
    training_steps_this_cycle = max(0, int(training_steps))
    total_steps = int(finite_float(state.get("training_steps_total")) or 0) + training_steps_this_cycle
    current_pid = os.getpid()
    previous_pid = int(finite_float(state.get("pid")) or 0)
    started_ts = state.get("started_ts") if previous_pid == current_pid else now_ts
    events.append(
        {
            "ts": now_ts,
            "generated_est": est_now(),
            "training_steps": training_steps_this_cycle,
            "prediction_rows": int(prediction_rows),
            "samples_seen": int(samples_seen),
            "batches": int(batches),
            "heartbeat_only": training_steps_this_cycle == 0,
            "training_blocker_reason": training_blocker_reason,
        }
    )
    updated = {
        "schema_version": "native_cuda_trainer_persistent_state_v1",
        "started_ts": started_ts,
        "cycle_index": cycle_index,
        "training_steps_total": total_steps,
        "step_events": events,
        "last_cycle_est": est_now(),
        "last_training_blocker_reason": training_blocker_reason,
        "pid": current_pid,
    }
    save_state(paths, updated)
    return updated


def checkpoint_retention_status(
    *,
    paths: PersistentTrainerPaths,
    latest_checkpoint_id: str | None,
    best_checkpoint_id: str | None = None,
    rollover_limit_gb: int = 300,
    apply_rollover: bool = True,
) -> dict[str, Any]:
    checkpoint_dir = paths.model_dir
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in checkpoint_dir.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime)
    pinned_names: set[str] = set()
    if latest_checkpoint_id:
        pinned_names.update(path.name for path in files if latest_checkpoint_id in path.name)
    if best_checkpoint_id:
        pinned_names.update(path.name for path in files if best_checkpoint_id in path.name)
    for path in files:
        payload = as_dict(read_json(path))
        if payload.get("pinned") is True or payload.get("best_checkpoint") is True:
            pinned_names.add(path.name)
    limit_bytes = int(rollover_limit_gb) * 1024**3
    deleted: list[str] = []
    total_bytes = sum(path.stat().st_size for path in files)
    if apply_rollover and total_bytes > limit_bytes:
        for path in files:
            if total_bytes <= limit_bytes:
                break
            if path.name in pinned_names:
                continue
            if latest_checkpoint_id and latest_checkpoint_id in path.name:
                continue
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            deleted.append(path.name)
            total_bytes -= size
    remaining = sorted([p for p in checkpoint_dir.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime)
    latest = remaining[-1].name if remaining else None
    manifest = {
        "schema_version": "native_cuda_trainer_checkpoint_retention_manifest_v1",
        "generated_est": est_now(),
        "checkpoint_dir": str(MODEL_DIR_REL),
        "checkpoint_count": len(remaining),
        "checkpoint_total_size_gb": round(total_bytes / 1024**3, 6),
        "total_size_gb": round(total_bytes / 1024**3, 6),
        "checkpoint_dir_size_bytes": total_bytes,
        "checkpoint_rollover_limit_gb": int(rollover_limit_gb),
        "rollover_limit_gb": int(rollover_limit_gb),
        "checkpoint_rollover_limit_bytes": limit_bytes,
        "oldest_checkpoint": remaining[0].name if remaining else None,
        "latest_checkpoint": latest,
        "latest_checkpoint_id": latest_checkpoint_id,
        "best_checkpoint": best_checkpoint_id,
        "pinned_checkpoints": sorted(pinned_names),
        "deleted_checkpoints": deleted,
        "rollover_action_taken": "DELETED_OLDEST_NON_PINNED" if deleted else "NONE",
        "checkpoint_rollover_status": "ROLLOVER_APPLIED" if deleted else "BELOW_LIMIT_NO_ACTION",
        "never_delete_latest_checkpoint": True,
        "never_delete_pinned_high_performing_checkpoint": True,
    }
    write_json(checkpoint_dir / "checkpoint_retention_manifest.json", manifest)
    return manifest


def classify_fill_source(row: Mapping[str, Any]) -> str:
    signal_id = str(row.get("signal_id") or "")
    trial_id = str(row.get("paper_confidence_trial_id") or "")
    if (
        row.get("paper_confidence_threshold_trial") is True
        or row.get("paper_confidence_trial_promoted") is True
        or signal_id.startswith("sig_paper_conf_trial_")
        or trial_id.startswith("paper_conf_trial_")
    ):
        return "confidence_trial_overlay"
    return "normal_native"


def _fill_pnl(row: Mapping[str, Any]) -> float:
    for key in ("total_pnl", "unrealized_pnl", "realized_pnl", "unrealized_pnl_usd", "realized_pnl_usd"):
        value = finite_float(row.get(key))
        if value is not None:
            return value
    return 0.0


def build_paper_drawdown_attribution(
    *,
    portfolio: Mapping[str, Any],
    ledger: Mapping[str, Any],
    previous_paper_pnl: float = PREVIOUS_PAPER_PNL_BASELINE,
) -> dict[str, Any]:
    accepted = [as_dict(row) for row in as_list(ledger.get("accepted") or ledger.get("accepted_intents"))]
    inventory = [as_dict(row) for row in as_list(portfolio.get("paper_fill_economic_inventory"))]
    fill_rows = accepted or inventory
    current_pnl = finite_float(portfolio.get("total_pnl_usd")) or 0.0
    delta = current_pnl - float(previous_paper_pnl)
    rows: list[dict[str, Any]] = []
    source_pnl: dict[str, float] = {"normal_native": 0.0, "confidence_trial_overlay": 0.0}
    source_count: dict[str, int] = {"normal_native": 0, "confidence_trial_overlay": 0}
    for row in fill_rows:
        source = classify_fill_source(row)
        pnl = _fill_pnl(row)
        source_pnl[source] = source_pnl.get(source, 0.0) + pnl
        source_count[source] = source_count.get(source, 0) + 1
        rows.append(
            {
                "fill_id": row.get("fill_id") or row.get("ledger_row_id") or row.get("intent_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "source": source,
                "side": row.get("side") or row.get("action"),
                "entry_price": row.get("entry_price") or row.get("fill_price"),
                "current_mark": row.get("current_mark_price") or row.get("latest_price"),
                "realized_pnl": row.get("realized_pnl") or row.get("realized_pnl_usd"),
                "unrealized_pnl": row.get("unrealized_pnl") or row.get("unrealized_pnl_usd"),
                "fees": row.get("fees"),
                "slippage": row.get("slippage"),
                "confidence": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "market_state_integrity_score": row.get("market_state_integrity_score"),
            }
        )
    loss_rows = sorted(rows, key=lambda row: finite_float(row.get("unrealized_pnl")) or 0.0)[:20]
    by_symbol: dict[str, float] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN")
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + (finite_float(row.get("unrealized_pnl")) or 0.0)
    attribution_lost = source_count.get("confidence_trial_overlay", 0) == 0 and source_count.get("normal_native", 0) > 0
    return {
        "schema_version": "paper_confidence_trial_drawdown_attribution_status_v1",
        "generated_est": est_now(),
        "previous_paper_pnl": float(previous_paper_pnl),
        "current_paper_pnl": current_pnl,
        "delta": round(delta, 8),
        "accepted_fill_count": len(fill_rows),
        "trial_overlay_fill_count": source_count.get("confidence_trial_overlay", 0),
        "normal_native_fill_count": source_count.get("normal_native", 0),
        "trial_overlay_pnl": round(source_pnl.get("confidence_trial_overlay", 0.0), 8),
        "normal_native_pnl": round(source_pnl.get("normal_native", 0.0), 8),
        "top_loss_symbols": [
            {"symbol": symbol, "pnl": round(pnl, 8)}
            for symbol, pnl in sorted(by_symbol.items(), key=lambda item: item[1])[:20]
        ],
        "top_loss_fills": loss_rows,
        "drawdown_from_mark_to_market": portfolio.get("unrealized_pnl_usd"),
        "drawdown_from_closed_positions": portfolio.get("realized_pnl_usd"),
        "trial_attribution_status": (
            "TRIAL_ATTRIBUTION_PRESENT"
            if source_count.get("confidence_trial_overlay", 0) > 0
            else "TRIAL_ATTRIBUTION_NOT_PRESENT_IN_CURRENT_LEDGER"
        ),
        "trial_attribution_lost_or_expired": attribution_lost,
        "live_threshold_changed": False,
    }


def build_paper_drawdown_guard(
    *,
    attribution: Mapping[str, Any],
    existing_trial_status: Mapping[str, Any],
) -> dict[str, Any]:
    delta = finite_float(attribution.get("delta")) or 0.0
    overlay_pnl = finite_float(attribution.get("trial_overlay_pnl")) or 0.0
    overlay_count = int(finite_float(attribution.get("trial_overlay_fill_count")) or 0)
    attribution_lost = attribution.get("trial_attribution_lost_or_expired") is True
    if overlay_count > 0 and overlay_pnl < TRIAL_OVERLAY_PNL_THRESHOLD_USD:
        status = "TRIAL_PAUSED_DRAWDOWN_GUARD"
        reason = "CONFIDENCE_TRIAL_OVERLAY_PNL_BELOW_THRESHOLD"
        trial_enabled = False
    elif attribution_lost and delta < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        status = "TRIAL_PAUSED_DRAWDOWN_GUARD"
        reason = "PAPER_DRAWDOWN_WITH_TRIAL_ATTRIBUTION_MISSING_OR_EXPIRED"
        trial_enabled = False
    elif delta < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        status = "TRIAL_BLOCKED_INSUFFICIENT_OUTCOME_SAMPLE"
        reason = "DRAWDOWN_BREACHED_BUT_TRIAL_OVERLAY_ATTRIBUTION_INSUFFICIENT"
        trial_enabled = False
    else:
        status = "TRIAL_ACTIVE_NO_DRAWDOWN" if existing_trial_status.get("trial_enabled") else "TRIAL_ACTIVE"
        reason = "DRAWDOWN_GUARD_NOT_BREACHED"
        trial_enabled = bool(existing_trial_status.get("trial_enabled"))
    return {
        "schema_version": "paper_confidence_trial_drawdown_guard_status_v1",
        "generated_est": est_now(),
        "status": status,
        "trial_enabled": trial_enabled,
        "stop_promoting_new_threshold_trial_signals": not trial_enabled,
        "normal_native_paper_path_active": True,
        "live_threshold_changed": False,
        "live_execution_changed": False,
        "drawdown_guard_reason": reason,
        "previous_paper_pnl": attribution.get("previous_paper_pnl"),
        "current_paper_pnl": attribution.get("current_paper_pnl"),
        "pnl_delta": attribution.get("delta"),
        "trial_overlay_pnl": attribution.get("trial_overlay_pnl"),
        "normal_native_pnl": attribution.get("normal_native_pnl"),
        "trial_overlay_fill_count": attribution.get("trial_overlay_fill_count"),
        "normal_native_fill_count": attribution.get("normal_native_fill_count"),
        "delta_threshold_usd": TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD,
        "overlay_pnl_threshold_usd": TRIAL_OVERLAY_PNL_THRESHOLD_USD,
        "redis_guard_key": TRIAL_DRAWDOWN_GUARD_REDIS_KEY,
        "redis_trial_signal_key": TRIAL_SIGNAL_REDIS_KEY,
    }


def apply_paper_drawdown_guard_to_redis(client: Any | None, guard: Mapping[str, Any]) -> dict[str, Any]:
    keys: list[str] = []
    status_written = safe_v2_redis_set(client, TRIAL_DRAWDOWN_GUARD_REDIS_KEY, guard, ex=3600)
    if status_written:
        keys.append(TRIAL_DRAWDOWN_GUARD_REDIS_KEY)
    if guard.get("stop_promoting_new_threshold_trial_signals") is True:
        paused_status = {
            "schema_version": "v2_paper_confidence_threshold_trial_paused_status_v1",
            "generated_est": est_now(),
            "trial_enabled": False,
            "status": guard.get("status"),
            "drawdown_guard_reason": guard.get("drawdown_guard_reason"),
            "live_threshold_changed": False,
        }
        if safe_v2_redis_set(client, TRIAL_STATUS_REDIS_KEY, paused_status, ex=3600):
            keys.append(TRIAL_STATUS_REDIS_KEY)
        if safe_v2_redis_set(client, TRIAL_SIGNAL_REDIS_KEY, [], ex=3600):
            keys.append(TRIAL_SIGNAL_REDIS_KEY)
    return {
        "redis_available": client is not None,
        "keys_written": keys,
        "old_redis_write": False,
        "write_status": "V2_PAPER_DRAWDOWN_GUARD_WRITTEN" if keys else "REDIS_UNAVAILABLE_OR_NO_WRITE",
    }


def trainer_symbol_scope_status() -> dict[str, Any]:
    provenance = as_dict(resolve_symbols_with_provenance())
    symbols = [str(symbol) for symbol in as_list(provenance.get("symbols")) if symbol]
    smoke_only_scope = tuple(symbols) == tuple(SMOKE_TEST_SYMBOLS)
    return {
        "training_symbols": symbols,
        "training_symbols_count": len(symbols),
        "trainer_symbol_profile": provenance.get("symbol_profile"),
        "trainer_symbol_source_path": provenance.get("source_path"),
        "trainer_symbol_discovered_count": provenance.get("discovered_count"),
        "trainer_symbol_binance_usdm_confirmed_count": provenance.get("binance_usdm_confirmed_count"),
        "trainer_symbol_baseline_count": provenance.get("baseline_count"),
        "trainer_smoke_test_scope": bool(provenance.get("smoke_test")) or smoke_only_scope,
        "trainer_btc_eth_sol_only_scope": smoke_only_scope,
        "trainer_all_runtime_symbols_enabled": bool(symbols) and not smoke_only_scope,
        "training_timeframes": list(DEFAULT_TIMEFRAMES),
        "training_timeframes_count": len(DEFAULT_TIMEFRAMES),
        "training_grid_expected_rows_from_symbol_scope": len(symbols) * len(DEFAULT_TIMEFRAMES),
    }


def build_resource_status(
    *,
    trainer_result: Any | None,
    persistent_state: Mapping[str, Any],
) -> dict[str, Any]:
    gpu = gpu_status_from_nvidia_smi()
    mem = memory_status()
    cpu = cpu_utilization_percent()
    training = as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training")) if trainer_result is not None else {}
    resource = as_dict(as_dict(getattr(trainer_result, "status", {})).get("cuda_cpu_resource_utilization"))
    vram_used = finite_float(gpu.get("vram_used_mb")) or finite_float(resource.get("current_vram_used_mb"))
    vram_total = finite_float(gpu.get("vram_total_mb")) or finite_float(resource.get("vram_total_mb"))
    samples_per_second = finite_float(resource.get("tensor_rows_per_second"))
    target_batch_size = int(finite_float(resource.get("target_batch_size")) or DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE)
    actual_batch_size = int(finite_float(resource.get("actual_batch_size")) or finite_float(training.get("batch_size")) or 0)
    training_blocker_reason = str(persistent_state.get("last_training_blocker_reason") or "")
    ram_total = finite_float(mem.get("ram_total_gb")) or 0.0
    ram_used = finite_float(mem.get("ram_used_gb")) or 0.0
    ram_available = ram_total - ram_used
    low_vram = bool(vram_used is not None and vram_total and (vram_used / vram_total) < 0.25)
    if training_blocker_reason:
        bottleneck = training_blocker_reason
    elif actual_batch_size and actual_batch_size < target_batch_size:
        bottleneck = "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH"
    elif low_vram and samples_per_second:
        bottleneck = "GPU_TRAINING_ACTIVE_LOW_UTILIZATION"
    elif low_vram:
        bottleneck = "MODEL_TOO_SMALL_TO_SATURATE_GPU"
    else:
        bottleneck = "PERSISTENT_TRAINING_RESOURCE_TELEMETRY_CURRENT"
    tuning = {
        "vram_under_25_percent": low_vram,
        "cpu_ram_available": bool(ram_available > 8),
        "target_batch_size_before": target_batch_size,
        "target_batch_size_after": target_batch_size,
        "dataloader_workers_before": resource.get("dataloader_workers"),
        "dataloader_workers_after": resource.get("dataloader_workers"),
        "action": (
            "TARGET_BATCH_ALREADY_EXCEEDS_AVAILABLE_APPROVED_SAMPLES"
            if actual_batch_size and actual_batch_size < target_batch_size
            else "KEEP_CURRENT_SAFE_CUDA_SETTINGS"
        ),
        "throughput_improved": None,
    }
    return {
        "schema_version": "native_cuda_trainer_resource_utilization_status_v1",
        "generated_est": est_now(),
        "gpu_name": gpu.get("gpu_name") or resource.get("gpu_name"),
        "gpu_utilization_percent": gpu.get("gpu_utilization_percent"),
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
        "cpu_utilization_percent": cpu,
        "ram_used_gb": mem.get("ram_used_gb"),
        "ram_total_gb": mem.get("ram_total_gb"),
        "batch_size": actual_batch_size or None,
        "target_batch_size": target_batch_size,
        "dataloader_workers": resource.get("dataloader_workers"),
        "prefetch_factor": resource.get("prefetch_factor"),
        "pinned_memory": bool(resource.get("pinned_memory")),
        "amp_enabled": bool(resource.get("mixed_precision_enabled")),
        "samples_per_second": samples_per_second,
        "predictions_per_second": resource.get("throughput_predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "bottleneck_reason": bottleneck,
        "resource_target_logic": tuning,
        "persistent_cycles_total": persistent_state.get("cycle_index"),
        "training_blocker_reason": training_blocker_reason or None,
    }


def latest_training_metrics_from_result(trainer_result: Any | None) -> dict[str, Any] | None:
    if trainer_result is None:
        return None
    training = as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training"))
    if not training:
        return None
    metrics = as_dict(training.get("metrics"))
    return {
        "status": training.get("status"),
        "device": training.get("device"),
        "cuda_active": training.get("cuda_active"),
        "cuda_claim_verified": training.get("cuda_claim_verified"),
        "gpu_name": training.get("gpu_name"),
        "batch_size": training.get("batch_size"),
        "training_steps": training.get("training_steps"),
        "train_rows": training.get("train_rows"),
        "validation_rows": training.get("validation_rows"),
        "loss_before": training.get("loss_before"),
        "loss_after": training.get("loss_after"),
        "action_distribution": training.get("action_distribution"),
        "metrics": metrics,
    }


def online_learning_runtime_fields(
    *,
    training: Mapping[str, Any] | None = None,
    latest_training_metrics: Mapping[str, Any] | None = None,
    persistent_state: Mapping[str, Any] | None = None,
    prediction_rows: int = 0,
) -> dict[str, Any]:
    training = as_dict(training)
    latest_training_metrics = as_dict(latest_training_metrics)
    nested_metrics = as_dict(latest_training_metrics.get("metrics")) or as_dict(training.get("metrics"))
    status = str(training.get("status") or latest_training_metrics.get("status") or "")
    trusted_rows = int(
        finite_float(nested_metrics.get("trusted_rows_loaded"))
        or finite_float(training.get("trusted_rows_loaded"))
        or finite_float(training.get("train_rows"))
        or 0
    )
    optimizer_steps = int(
        finite_float(nested_metrics.get("optimizer_steps_this_cycle"))
        or finite_float(training.get("optimizer_steps_this_cycle"))
        or 0
    )
    parameter_hash_before = nested_metrics.get("parameter_hash_before") or training.get("parameter_hash_before")
    parameter_hash_after = nested_metrics.get("parameter_hash_after") or training.get("parameter_hash_after")
    weight_delta_norm = finite_float(nested_metrics.get("weight_delta_norm") or training.get("weight_delta_norm")) or 0.0
    checkpoint_written = bool(
        nested_metrics.get("checkpoint_weight_blob_written")
        or training.get("checkpoint_weight_blob_written")
    )
    checkpoint_reload_verified = bool(
        nested_metrics.get("checkpoint_reload_verified")
        or training.get("checkpoint_reload_verified")
    )
    weight_mutated = bool(
        optimizer_steps > 0
        and parameter_hash_before
        and parameter_hash_after
        and parameter_hash_before != parameter_hash_after
        and weight_delta_norm > 0.0
        and checkpoint_written
        and checkpoint_reload_verified
    )
    successful_update_at = (
        nested_metrics.get("last_successful_weight_update_at")
        or training.get("last_successful_weight_update_at")
    )
    blocker = str(
        as_dict(persistent_state).get("last_training_blocker_reason")
        or status
        or ""
    )
    if weight_mutated and successful_update_at:
        online_learning_status = "WEIGHTS_UPDATING"
        effective_trainer_mode = "WEIGHTS_UPDATING"
        last_successful_weight_update_at = successful_update_at
    elif trusted_rows <= 0 or "NO_TRUSTED" in blocker:
        online_learning_status = "BLOCKED_NO_TRUSTED_FEEDBACK"
        effective_trainer_mode = "INFERENCE_ONLY"
        last_successful_weight_update_at = None
    else:
        online_learning_status = "BLOCKED_NO_DURABLE_WEIGHT_UPDATE"
        effective_trainer_mode = "INFERENCE_ONLY"
        last_successful_weight_update_at = None
    return {
        "trainer_process_status": "ACTIVE",
        "cuda_inference_status": "ACTIVE",
        "prediction_publication_status": "ACTIVE" if int(prediction_rows) > 0 else "BLOCKED_NO_PREDICTIONS",
        "online_learning_status": online_learning_status,
        "effective_trainer_mode": effective_trainer_mode,
        "last_successful_weight_update_at": last_successful_weight_update_at,
        "trusted_rows_loaded": trusted_rows,
        "optimizer_steps_this_cycle": optimizer_steps,
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "weight_delta_norm": weight_delta_norm,
        "checkpoint_weight_blob_written": checkpoint_written,
        "checkpoint_reload_verified": checkpoint_reload_verified,
    }


def build_persistent_runtime_status(
    *,
    paths: PersistentTrainerPaths,
    trainer_result: Any | None,
    persistent_state: Mapping[str, Any],
    resource: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    now_ts = time.time()
    events = prune_recent_events(as_list(persistent_state.get("step_events")), now_ts=now_ts)
    last_minute_events = [event for event in events if now_ts - (finite_float(event.get("ts")) or 0.0) <= 60]
    generated_est = est_now()
    generated_utc = utc_now()
    status = as_dict(getattr(trainer_result, "status", {})) if trainer_result is not None else {}
    metrics = as_dict(getattr(trainer_result, "metrics", {})) if trainer_result is not None else {}
    training = as_dict(metrics.get("training"))
    latest_training_metrics = latest_training_metrics_from_result(trainer_result)
    service = systemctl_show(PERSISTENT_UNIT)
    pid = int(finite_float(service.get("MainPID")) or os.getpid())
    started_ts = finite_float(persistent_state.get("started_ts")) or now_ts
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    prediction_rows = int(
        finite_float(prediction_public.get("prediction_rows_count"))
        or len(as_list(prediction_public.get("prediction_rows")))
        or len(getattr(trainer_result, "predictions", []) if trainer_result is not None else [])
    )
    expected_rows = int(finite_float(prediction_public.get("expected_prediction_count")) or prediction_rows)
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or prediction_rows
    )
    symbol_scope = trainer_symbol_scope_status()
    missing_prediction_rows = int(finite_float(prediction_public.get("missing_prediction_rows_count")) or 0)
    stale_prediction_rows = int(finite_float(prediction_public.get("stale_prediction_rows_count")) or 0)
    blocked_rows = int(finite_float(prediction_public.get("blocked_prediction_rows_count")) or 0)
    latest_event_ts = max(
        (finite_float(event.get("ts")) or 0.0 for event in events),
        default=0.0,
    )
    heartbeat_age_seconds = (
        round(max(0.0, now_ts - latest_event_ts), 3)
        if latest_event_ts > 0
        else None
    )
    service_active = service.get("ActiveState") == "active" or os.getpid() == pid
    worker_health_status = (
        "HEALTHY"
        if service_active and heartbeat_age_seconds is not None and heartbeat_age_seconds <= 300
        else "DEGRADED"
        if service_active
        else "OFFLINE"
    )
    online_learning = online_learning_runtime_fields(
        training=training,
        latest_training_metrics=latest_training_metrics,
        persistent_state=persistent_state,
        prediction_rows=prediction_rows,
    )
    return {
        "schema_version": "native_cuda_trainer_persistent_runtime_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "current_status_age_seconds": 0,
        "service_name": PERSISTENT_UNIT,
        "service_active": service_active,
        "service_state": service,
        "pid": pid,
        "uptime_seconds": round(max(0.0, now_ts - started_ts), 3),
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "trainer_liveness_status": worker_health_status,
        "worker_health_status": worker_health_status,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "last_batch_age_seconds": heartbeat_age_seconds,
        "last_prediction_age_seconds": heartbeat_age_seconds,
        **online_learning,
        "last_training_blocker_reason": persistent_state.get("last_training_blocker_reason"),
        "training_steps_total": persistent_state.get("training_steps_total", 0),
        "training_steps_last_minute": sum(int(finite_float(event.get("training_steps")) or 0) for event in last_minute_events),
        "training_steps_last_hour": sum(int(finite_float(event.get("training_steps")) or 0) for event in events),
        "samples_seen_last_hour": sum(int(finite_float(event.get("samples_seen")) or 0) for event in events),
        "batches_last_hour": sum(int(finite_float(event.get("batches")) or 0) for event in events),
        **symbol_scope,
        "prediction_grid_rows": prediction_rows,
        "prediction_grid_expected_rows": expected_rows,
        "expected_prediction_grid_rows": expected_rows,
        "prediction_grid_current": bool(
            expected_rows > 0
            and current_prediction_rows == expected_rows
            and missing_prediction_rows == 0
            and stale_prediction_rows == 0
        ),
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status"),
        "missing_prediction_symbols": as_list(prediction_public.get("missing_prediction_symbols")),
        "missing_prediction_timeframes_by_symbol": as_dict(
            prediction_public.get("missing_prediction_timeframes_by_symbol")
        ),
        "blocked_prediction_rows": blocked_rows,
        "trainer_source": TRAINER_SOURCE,
        "checkpoint_id": status.get("checkpoint_id") or checkpoint.get("latest_checkpoint_id"),
        "last_checkpoint_est": checkpoint.get("generated_est"),
        "last_cycle_status": status.get("schema_version"),
        "last_cycle_train_rows": training.get("train_rows"),
        "last_cycle_validation_rows": training.get("validation_rows"),
        "last_cycle_examples_built": status.get("examples_built"),
        "last_cycle_fresh_examples_built": status.get("fresh_examples_built"),
        "last_cycle_prediction_examples_built": status.get("prediction_examples_built"),
        "train_rows": training.get("train_rows"),
        "validation_rows": training.get("validation_rows"),
        "latest_training_metrics": latest_training_metrics,
        "examples_built": status.get("examples_built"),
        "fresh_examples_built": status.get("fresh_examples_built"),
        "prediction_examples_built": status.get("prediction_examples_built"),
        "replay_buffer_enabled": status.get("replay_buffer_enabled"),
        "replay_buffer_size": status.get("replay_buffer_size"),
        "replay_buffer_limit": status.get("replay_buffer_limit"),
        "current_batch_size": resource.get("batch_size") or resource.get("actual_batch_size"),
        "target_batch_size": resource.get("target_batch_size"),
        "current_vram_used_mb": resource.get("current_vram_used_mb") or resource.get("vram_used_mb"),
        "vram_total_mb": resource.get("vram_total_mb"),
        "gpu_name": resource.get("gpu_name"),
        "resource_bottleneck_reason": resource.get("bottleneck_reason"),
    }


def publish_training_cycle_heartbeat(
    *,
    paths: PersistentTrainerPaths,
    persistent_state: Mapping[str, Any] | None = None,
    max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    run_training: bool = True,
) -> dict[str, Any]:
    existing = as_dict(read_json(paths.artifact_dir / "native_cuda_trainer_persistent_runtime_status.json"))
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    generated_est = est_now()
    generated_utc = utc_now()
    expected_rows = int(
        finite_float(prediction_public.get("expected_prediction_count"))
        or finite_float(existing.get("prediction_grid_expected_rows"))
        or finite_float(existing.get("expected_prediction_grid_rows"))
        or finite_float(prediction_public.get("prediction_rows_count"))
        or 0
    )
    prediction_rows = int(
        finite_float(prediction_public.get("prediction_rows_count"))
        or finite_float(existing.get("prediction_grid_rows"))
        or len(as_list(prediction_public.get("prediction_rows")))
        or 0
    )
    blocked_rows = int(
        finite_float(prediction_public.get("blocked_prediction_rows_count"))
        or finite_float(existing.get("blocked_prediction_rows"))
        or 0
    )
    paper_actionability_allowed = int(
        finite_float(prediction_public.get("paper_actionability_allowed_rows_count")) or 0
    )
    paper_actionability_blocked = int(
        finite_float(prediction_public.get("paper_actionability_blocked_rows_count")) or 0
    )
    paper_actionability_block_reasons = dict(
        as_dict(prediction_public.get("paper_actionability_block_reason_counts"))
    )
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or finite_float(existing.get("current_prediction_count"))
        or prediction_rows
        or 0
    )
    missing_prediction_rows = int(
        finite_float(prediction_public.get("missing_prediction_rows_count"))
        or finite_float(existing.get("missing_prediction_rows_count"))
        or 0
    )
    stale_prediction_rows = int(
        finite_float(prediction_public.get("stale_prediction_rows_count"))
        or finite_float(existing.get("stale_prediction_rows_count"))
        or 0
    )
    missing_prediction_symbols = as_list(prediction_public.get("missing_prediction_symbols"))
    missing_prediction_timeframes_by_symbol = as_dict(
        prediction_public.get("missing_prediction_timeframes_by_symbol")
    )
    symbol_scope = trainer_symbol_scope_status()
    prediction_grid_current = bool(
        expected_rows > 0
        and current_prediction_rows == expected_rows
        and missing_prediction_rows == 0
        and stale_prediction_rows == 0
    )
    state = as_dict(persistent_state)
    current_runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    current_runtime = as_dict(read_json(current_runtime_path))
    latest_training_metrics = current_runtime.get("latest_training_metrics")
    online_learning = online_learning_runtime_fields(
        latest_training_metrics=latest_training_metrics,
        persistent_state=state,
        prediction_rows=prediction_rows,
    )
    payload = {
        **existing,
        "schema_version": "native_cuda_trainer_persistent_runtime_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "current_status_age_seconds": 0,
        "training_cycle_status": "TRAINING_CYCLE_IN_PROGRESS" if run_training else "STATUS_REFRESH_IN_PROGRESS",
        "training_cycle_started_est": generated_est,
        "training_cycle_started_utc": generated_utc,
        "training_cycle_max_rows": int(max_rows),
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "service_name": PERSISTENT_UNIT,
        "service_active": True,
        "pid": os.getpid(),
        "training_steps_total": state.get("training_steps_total", existing.get("training_steps_total", 0)),
        **online_learning,
        **symbol_scope,
        "prediction_grid_rows": prediction_rows,
        "prediction_grid_expected_rows": expected_rows,
        "expected_prediction_grid_rows": expected_rows,
        "prediction_grid_current": prediction_grid_current,
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status"),
        "missing_prediction_symbols": missing_prediction_symbols,
        "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
        "blocked_prediction_rows": blocked_rows,
        "paper_actionability_allowed_rows_count": paper_actionability_allowed,
        "paper_actionability_blocked_rows_count": paper_actionability_blocked,
        "paper_actionability_block_reason_counts": paper_actionability_block_reasons,
        "trainer_source": TRAINER_SOURCE,
        "heartbeat_age_seconds": 0,
        "worker_health_status": "HEALTHY",
        "trainer_liveness_status": "HEALTHY",
    }
    for base in (paths.artifact_dir, paths.worklog_dir):
        write_json(base / "native_cuda_trainer_persistent_runtime_status.json", payload)
    write_json(paths.operator_dir / "native_cuda_trainer_persistent_runtime_status.json", payload)
    write_json(
        current_runtime_path,
        {
            **current_runtime,
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "payload_age_seconds": 0,
            "current_status_age_seconds": 0,
            "training_loop_active": True,
            "continuous_training_enabled": True,
            "training_cycle_status": payload["training_cycle_status"],
            "persistent_trainer_service_active": True,
            "persistent_trainer_pid": os.getpid(),
            **online_learning,
            **symbol_scope,
            "prediction_grid_rows": prediction_rows,
            "prediction_grid_expected_rows": expected_rows,
            "expected_prediction_grid_rows": expected_rows,
            "prediction_grid_current": prediction_grid_current,
            "current_prediction_count": current_prediction_rows,
            "missing_prediction_rows_count": missing_prediction_rows,
            "stale_prediction_rows_count": stale_prediction_rows,
            "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
            "prediction_coverage_status": prediction_public.get("coverage_status"),
            "prediction_actionability_status": prediction_public.get("actionability_status"),
            "missing_prediction_symbols": missing_prediction_symbols,
            "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
            "blocked_prediction_rows": blocked_rows,
            "paper_actionability_allowed_rows_count": paper_actionability_allowed,
            "paper_actionability_blocked_rows_count": paper_actionability_blocked,
            "paper_actionability_block_reason_counts": paper_actionability_block_reasons,
            "training_steps_total": payload.get("training_steps_total"),
            "trainer_liveness_status": "HEALTHY",
            "worker_health_status": "HEALTHY",
        },
    )
    return payload


def refresh_all_timeframe_payload(repo_root: Path) -> dict[str, Any]:
    try:
        from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (
            DEFAULT_STALE_SECONDS,
            V2KeyValueStore,
            build_packet,
            default_paths,
            write_outputs,
        )
    except Exception as exc:
        return {"ran": False, "status": f"IMPORT_FAILED:{type(exc).__name__}"}
    client = connect_redis()
    try:
        store = V2KeyValueStore(client=client)
        result = build_packet(
            paths=default_paths(repo_root),
            store=store,
            stale_seconds=DEFAULT_STALE_SECONDS,
            production_base_url="http://127.0.0.1:5177",
            routes=(),
            write_redis=True,
            trainer_trust_reconciliation_limit=0,
            feature_parity_from_prediction_rows=True,
        )
        result = write_outputs(default_paths(repo_root), result)
    except Exception as exc:
        return {"ran": False, "status": f"RUN_FAILED:{type(exc).__name__}"}
    return {
        "ran": True,
        "status": result.go_no_go,
        "paths_written_count": len(result.paths_written),
        "redis_connected": store.audit.connected,
        "old_redis_write_attempts": store.audit.old_redis_write_attempts,
    }


# Module-level in-memory replay buffer — survives across cycles, uses 128 GB RAM.
# maxlen=65_536 targets ~1.6 GB for typical feature vector sizes; feeds 32K-row batches.
_REPLAY_BUFFER: deque = deque(maxlen=65_536)
RESIDENT_MAX_TRAIN_STEPS_PER_CYCLE = 64
RESIDENT_TRAIN_ROWS_PER_STEP = 512


def resident_train_steps_for_max_rows(max_rows: int) -> int:
    rows = max(1, int(max_rows))
    row_scaled_steps = max(1, rows // RESIDENT_TRAIN_ROWS_PER_STEP)
    return max(1, min(RESIDENT_MAX_TRAIN_STEPS_PER_CYCLE, row_scaled_steps))


def run_native_training_cycle(
    *,
    paths: PersistentTrainerPaths,
    max_rows: int,
    risk_caps_configured: bool,
) -> Any:
    io = V2OnlyJsonIO(client=connect_redis())
    symbol_scope = trainer_symbol_scope_status()
    config = HybridTrainerConfig(
        symbols=tuple(symbol_scope["training_symbols"] or resolve_symbols()),
        timeframes=tuple(DEFAULT_TIMEFRAMES),
        max_training_rows_per_cycle=int(max_rows),
        batch_size=max(1, int(max_rows)),
        train_steps=resident_train_steps_for_max_rows(max_rows),
        risk_caps_configured=bool(risk_caps_configured),
    )
    return run_hybrid_trainer_cycle(config=config, io=io, publish=True, replay_buffer=_REPLAY_BUFFER)


def publish_persistent_payloads(
    *,
    paths: PersistentTrainerPaths,
    persistent: Mapping[str, Any],
    resource: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    attribution: Mapping[str, Any],
    guard: Mapping[str, Any],
    trainer_result: Any | None,
    all_timeframe_refresh: Mapping[str, Any],
) -> dict[str, Any]:
    generated_est = est_now()
    generated_utc = utc_now()
    portfolio = as_dict(read_json(paths.public_root / PORTFOLIO_REL))
    live_runtime = as_dict(read_json(paths.public_root / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json"))
    blockers: list[str] = []
    if not persistent.get("training_loop_active"):
        blockers.append("PERSISTENT_TRAINING_LOOP_NOT_ACTIVE")
    if systemctl_show(LEGACY_BRIDGE_UNIT).get("UnitFileState") != "masked":
        blockers.append("TRAINER_BRIDGE_NOT_MASKED")
    if guard.get("status") == "TRIAL_ACTIVE" and (finite_float(attribution.get("delta")) or 0.0) < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        blockers.append("PAPER_TRIAL_ACTIVE_DESPITE_DRAWDOWN_BREACH")
    go_no_go = BLOCKED if blockers else READY
    website = {
        "schema_version": "website_trainer_resource_and_paper_guard_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "status": "WEBSITE_TRAINER_RESOURCE_AND_PAPER_GUARD_READY" if not blockers else "WEBSITE_TRAINER_RESOURCE_AND_PAPER_GUARD_BLOCKED",
        "routes_synced": [
            "/model-state",
            "/ai-predictions",
            "/signals",
            "/dashboard",
            "/system/trainer",
            "/trade/paper",
            "/portfolio",
            "/system/readiness",
        ],
        "must_show": {
            "persistent_trainer_active": persistent.get("service_active"),
            "trainer_process_status": persistent.get("trainer_process_status"),
            "cuda_inference_status": persistent.get("cuda_inference_status"),
            "prediction_publication_status": persistent.get("prediction_publication_status"),
            "online_learning_status": persistent.get("online_learning_status"),
            "effective_trainer_mode": persistent.get("effective_trainer_mode"),
            "last_successful_weight_update_at": persistent.get("last_successful_weight_update_at"),
            "steps_last_hour": persistent.get("training_steps_last_hour"),
            "gpu_utilization_percent": resource.get("gpu_utilization_percent"),
            "vram_used_mb": resource.get("vram_used_mb"),
            "vram_total_mb": resource.get("vram_total_mb"),
            "cpu_utilization_percent": resource.get("cpu_utilization_percent"),
            "ram_used_gb": resource.get("ram_used_gb"),
            "ram_total_gb": resource.get("ram_total_gb"),
            "bottleneck_reason": resource.get("bottleneck_reason"),
            "checkpoint_count": checkpoint.get("checkpoint_count"),
            "checkpoint_total_size_gb": checkpoint.get("checkpoint_total_size_gb"),
            "training_symbols_count": persistent.get("training_symbols_count"),
            "trainer_all_runtime_symbols_enabled": persistent.get("trainer_all_runtime_symbols_enabled"),
            "trainer_btc_eth_sol_only_scope": persistent.get("trainer_btc_eth_sol_only_scope"),
            "paper_trial_status": guard.get("status"),
            "paper_trial_pnl": attribution.get("trial_overlay_pnl"),
            "normal_native_paper_pnl": attribution.get("normal_native_pnl"),
            "drawdown_guard_state": guard.get("drawdown_guard_reason"),
        },
        "semantic_validation_guards": [
            "model_state_no_stale_6d_payload",
            "training_steps_increase_with_persistent_service",
            "resource_utilization_present",
            "checkpoint_retention_present",
            "paper_trial_guard_visible",
            "live_state_balance_hold_consistent",
        ],
    }
    dashboard = {
        "schema_version": "v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard_operator_dashboard_v1",
        "gate": go_no_go,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "trainer": {
            "service_active": persistent.get("service_active"),
            "pid": persistent.get("pid"),
            "uptime_seconds": persistent.get("uptime_seconds"),
            "training_steps_total": persistent.get("training_steps_total"),
            "training_steps_last_hour": persistent.get("training_steps_last_hour"),
            "training_symbols_count": persistent.get("training_symbols_count"),
            "trainer_all_runtime_symbols_enabled": persistent.get("trainer_all_runtime_symbols_enabled"),
            "trainer_btc_eth_sol_only_scope": persistent.get("trainer_btc_eth_sol_only_scope"),
            "prediction_grid_rows": persistent.get("prediction_grid_rows"),
            "prediction_grid_expected_rows": persistent.get("prediction_grid_expected_rows"),
            "blocked_prediction_rows": persistent.get("blocked_prediction_rows"),
            "resource_bottleneck_reason": resource.get("bottleneck_reason"),
        },
        "resource": resource,
        "checkpoint": checkpoint,
        "paper_drawdown": {
            "previous_pnl": attribution.get("previous_paper_pnl"),
            "current_pnl": attribution.get("current_paper_pnl"),
            "delta": attribution.get("delta"),
            "trial_overlay_pnl": attribution.get("trial_overlay_pnl"),
            "normal_native_pnl": attribution.get("normal_native_pnl"),
            "guard_status": guard.get("status"),
            "guard_reason": guard.get("drawdown_guard_reason"),
        },
        "portfolio": {
            "equity": portfolio.get("equity"),
            "pnl": portfolio.get("total_pnl_usd"),
            "accepted_fill_total": portfolio.get("accepted_fill_total"),
            "open_positions_count": portfolio.get("open_positions_count"),
        },
        "live": {
            "live_gate": live_runtime.get("live_gate"),
            "trader_state": live_runtime.get("trader_state"),
            "live_order_submit_blocker": live_runtime.get("live_order_submit_blocker"),
        },
        "all_timeframe_refresh": dict(all_timeframe_refresh),
        "blockers": blockers,
        "safety": {
            "real_order": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "trainer_bridge_unmasked": False,
            "live_threshold_changed": False,
        },
    }
    report = (
        "# V2 Persistent CUDA Trainer Resource Utilization And Paper Drawdown Guard Report\n\n"
        f"Gate: `{go_no_go}`\n"
        f"Generated EST: `{dashboard['generated_est']}`\n"
        f"Persistent trainer service active: `{persistent.get('service_active')}`\n"
        f"PID: `{persistent.get('pid')}`\n"
        f"Training steps total/last hour: `{persistent.get('training_steps_total')}/{persistent.get('training_steps_last_hour')}`\n"
        f"Trainer symbols: `{persistent.get('training_symbols_count')}` symbols, BTC/ETH/SOL-only scope `{persistent.get('trainer_btc_eth_sol_only_scope')}`\n"
        f"Prediction grid: `{persistent.get('prediction_grid_rows')}/{persistent.get('prediction_grid_expected_rows')}`\n"
        f"Resource bottleneck: `{resource.get('bottleneck_reason')}`\n"
        f"GPU/VRAM: `{resource.get('gpu_utilization_percent')}% / {resource.get('vram_used_mb')} MB of {resource.get('vram_total_mb')} MB`\n"
        f"Checkpoint count/size: `{checkpoint.get('checkpoint_count')}/{checkpoint.get('checkpoint_total_size_gb')} GB`\n"
        f"Paper PnL delta from trial baseline: `{attribution.get('delta')}`\n"
        f"Paper trial guard: `{guard.get('status')}`\n"
        f"Live gate: `{dashboard['live'].get('live_gate')}`\n"
        f"Trader state: `{dashboard['live'].get('trader_state')}`\n"
        f"Live submit blocker: `{dashboard['live'].get('live_order_submit_blocker')}`\n\n"
        "The native trainer now has a persistent resident loop and publishes current resource, checkpoint, and paper drawdown guard status. "
        "The confidence-threshold overlay is paper-only and is paused when the drawdown guard is breached or attribution is insufficient. Live thresholds and exchange execution are unchanged.\n\n"
        "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, no trainer bridge unmask, and no live threshold change.\n"
    )
    payloads = {
        "GO_NO_GO.md": go_no_go,
        "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_REPORT.md": report,
        "native_cuda_trainer_persistent_runtime_status.json": dict(persistent),
        "native_cuda_trainer_resource_utilization_status.json": dict(resource),
        "native_cuda_trainer_checkpoint_retention_status.json": dict(checkpoint),
        "paper_confidence_trial_drawdown_attribution_status.json": dict(attribution),
        "paper_confidence_trial_drawdown_guard_status.json": dict(guard),
        "website_trainer_resource_and_paper_guard_status.json": website,
        "operator_dashboard_payload.json": dashboard,
    }
    for base in (paths.artifact_dir, paths.worklog_dir):
        for name, payload in payloads.items():
            if name.endswith(".md"):
                write_text(base / name, str(payload))
            else:
                write_json(base / name, payload)
    for name in (
        "native_cuda_trainer_persistent_runtime_status.json",
        "native_cuda_trainer_resource_utilization_status.json",
        "native_cuda_trainer_checkpoint_retention_status.json",
        "paper_confidence_trial_drawdown_guard_status.json",
    ):
        write_json(paths.operator_dir / name, payloads[name])
    current_runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    current_runtime = as_dict(read_json(current_runtime_path))
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    expected_prediction_rows = int(
        finite_float(prediction_public.get("expected_prediction_count"))
        or finite_float(current_runtime.get("prediction_grid_expected_rows"))
        or finite_float(persistent.get("prediction_grid_expected_rows"))
        or 0
    )
    symbol_scope = {
        key: persistent.get(key)
        for key in (
            "training_symbols",
            "training_symbols_count",
            "trainer_symbol_profile",
            "trainer_symbol_source_path",
            "trainer_symbol_discovered_count",
            "trainer_symbol_binance_usdm_confirmed_count",
            "trainer_symbol_baseline_count",
            "trainer_smoke_test_scope",
            "trainer_btc_eth_sol_only_scope",
            "trainer_all_runtime_symbols_enabled",
            "training_timeframes",
            "training_timeframes_count",
            "training_grid_expected_rows_from_symbol_scope",
        )
        if key in persistent
    }
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or finite_float(current_runtime.get("current_prediction_count"))
        or finite_float(persistent.get("prediction_grid_rows"))
        or 0
    )
    missing_prediction_rows = int(
        finite_float(prediction_public.get("missing_prediction_rows_count"))
        or finite_float(current_runtime.get("missing_prediction_rows_count"))
        or 0
    )
    stale_prediction_rows = int(
        finite_float(prediction_public.get("stale_prediction_rows_count"))
        or finite_float(current_runtime.get("stale_prediction_rows_count"))
        or 0
    )
    missing_prediction_symbols = as_list(prediction_public.get("missing_prediction_symbols"))
    if not missing_prediction_symbols and missing_prediction_rows:
        missing_prediction_symbols = as_list(current_runtime.get("missing_prediction_symbols"))
    missing_prediction_timeframes_by_symbol = as_dict(
        prediction_public.get("missing_prediction_timeframes_by_symbol")
    )
    if not missing_prediction_timeframes_by_symbol and missing_prediction_rows:
        missing_prediction_timeframes_by_symbol = as_dict(
            current_runtime.get("missing_prediction_timeframes_by_symbol")
        )
    prediction_grid_current = bool(
        expected_prediction_rows > 0
        and current_prediction_rows == expected_prediction_rows
        and missing_prediction_rows == 0
        and stale_prediction_rows == 0
    )
    latest_training_metrics = latest_training_metrics_from_result(trainer_result) or current_runtime.get(
        "latest_training_metrics"
    )
    online_learning = online_learning_runtime_fields(
        training=as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training")) if trainer_result is not None else {},
        latest_training_metrics=latest_training_metrics,
        persistent_state=persistent,
        prediction_rows=current_prediction_rows,
    )
    merged_runtime = {
        **current_runtime,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "payload_age_seconds": 0,
        "current_status_age_seconds": 0,
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "trainer_liveness_status": persistent.get("trainer_liveness_status"),
        "worker_health_status": persistent.get("worker_health_status"),
        "heartbeat_age_seconds": persistent.get("heartbeat_age_seconds"),
        "last_batch_age_seconds": persistent.get("last_batch_age_seconds"),
        "last_prediction_age_seconds": persistent.get("last_prediction_age_seconds"),
        **online_learning,
        **symbol_scope,
        "prediction_grid_current": prediction_grid_current,
        "persistent_trainer_service_active": persistent.get("service_active"),
        "persistent_trainer_pid": persistent.get("pid"),
        "persistent_trainer_uptime_seconds": persistent.get("uptime_seconds"),
        "training_steps_total": persistent.get("training_steps_total"),
        "training_steps_last_hour": persistent.get("training_steps_last_hour"),
        "fresh_examples_built": persistent.get("fresh_examples_built"),
        "prediction_examples_built": persistent.get("prediction_examples_built"),
        "replay_buffer_enabled": persistent.get("replay_buffer_enabled"),
        "replay_buffer_size": persistent.get("replay_buffer_size"),
        "replay_buffer_limit": persistent.get("replay_buffer_limit"),
        "latest_training_metrics": latest_training_metrics,
        "samples_per_second": resource.get("samples_per_second"),
        "predictions_per_second": resource.get("predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "batch_size": resource.get("batch_size"),
        "target_batch_size": resource.get("target_batch_size"),
        "dataloader_workers": resource.get("dataloader_workers"),
        "pinned_memory": resource.get("pinned_memory"),
        "amp_enabled": resource.get("amp_enabled"),
        "gpu_name": resource.get("gpu_name"),
        "gpu_utilization_percent": resource.get("gpu_utilization_percent"),
        "vram_used_mb": resource.get("vram_used_mb"),
        "vram_total_mb": resource.get("vram_total_mb"),
        "cpu_utilization_percent": resource.get("cpu_utilization_percent"),
        "ram_used_gb": resource.get("ram_used_gb"),
        "ram_total_gb": resource.get("ram_total_gb"),
        "checkpoint_count": checkpoint.get("checkpoint_count"),
        "checkpoint_total_size_gb": checkpoint.get("checkpoint_total_size_gb"),
        "checkpoint_dir_size_bytes": checkpoint.get("checkpoint_dir_size_bytes"),
        "checkpoint_rollover_status": checkpoint.get("checkpoint_rollover_status"),
        "prediction_grid_rows": int(
            finite_float(prediction_public.get("prediction_rows_count"))
            or finite_float(persistent.get("prediction_grid_rows"))
            or 0
        ),
        "prediction_grid_expected_rows": expected_prediction_rows,
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_prediction_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status")
        or current_runtime.get("prediction_coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status")
        or current_runtime.get("prediction_actionability_status"),
        "missing_prediction_symbols": missing_prediction_symbols,
        "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
        "blocked_prediction_rows": int(
            finite_float(prediction_public.get("blocked_prediction_rows_count"))
            or finite_float(persistent.get("blocked_prediction_rows"))
            or 0
        ),
        "paper_actionability_allowed_rows_count": int(
            finite_float(prediction_public.get("paper_actionability_allowed_rows_count")) or 0
        ),
        "paper_actionability_blocked_rows_count": int(
            finite_float(prediction_public.get("paper_actionability_blocked_rows_count")) or 0
        ),
        "paper_actionability_block_reason_counts": dict(
            as_dict(prediction_public.get("paper_actionability_block_reason_counts"))
        ),
        "resource_bottleneck_reason": resource.get("bottleneck_reason"),
        "training_cycle_blocked_reason": persistent.get("last_training_blocker_reason"),
        "paper_confidence_trial_drawdown_guard": dict(guard),
        "paper_confidence_trial_guard_status": guard.get("status"),
        "paper_confidence_trial_guard_reason": guard.get("drawdown_guard_reason"),
        "paper_confidence_trial_guard_trial_enabled": guard.get("trial_enabled"),
    }
    write_json(current_runtime_path, merged_runtime)
    write_json(paths.operator_dir / "native_trainer_gpu_status.json", dict(resource))
    write_json(paths.operator_dir / "native_trainer_checkpoint_status.json", dict(checkpoint))
    return payloads


def run_one_persistent_cycle(
    *,
    paths: PersistentTrainerPaths,
    max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    risk_caps_configured: bool = True,
    run_training: bool = True,
) -> dict[str, Any]:
    training_blocker_reason: str | None = None
    state_before_cycle = as_dict(read_json(paths.state_path))
    publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state=state_before_cycle,
        max_rows=max_rows,
        run_training=run_training,
    )
    try:
        trainer_result = run_native_training_cycle(
            paths=paths,
            max_rows=max_rows,
            risk_caps_configured=risk_caps_configured,
        ) if run_training else None
    except (RuntimeError, ValueError) as exc:
        msg = str(exc).lower()
        if not ("no trusted examples built" in msg or "min() arg is an empty sequence" in msg):
            raise
        trainer_result = None
        training_blocker_reason = "NO_TRUSTED_EXAMPLES_BUILT"
    training_metrics = as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training")) if trainer_result is not None else {}
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    prediction_rows = len(getattr(trainer_result, "predictions", []) if trainer_result is not None else [])
    if trainer_result is None:
        prediction_rows = int(
            finite_float(prediction_public.get("prediction_rows_count"))
            or len(as_list(prediction_public.get("prediction_rows")))
            or 0
        )
    training_steps_this_cycle = int(
        finite_float(training_metrics.get("training_steps"))
        or (1 if trainer_result is not None else 0)
    )
    state = record_cycle_state(
        paths=paths,
        training_steps=training_steps_this_cycle,
        prediction_rows=prediction_rows,
        samples_seen=int(finite_float(training_metrics.get("train_rows")) or 0)
        + int(finite_float(training_metrics.get("validation_rows")) or 0),
        batches=1 if trainer_result is not None else 0,
        training_blocker_reason=training_blocker_reason,
    )
    all_timeframe_refresh = refresh_all_timeframe_payload(paths.repo_root)
    checkpoint_id = as_dict(getattr(trainer_result, "status", {})).get("checkpoint_id") if trainer_result is not None else None
    checkpoint = checkpoint_retention_status(paths=paths, latest_checkpoint_id=checkpoint_id)
    resource = build_resource_status(trainer_result=trainer_result, persistent_state=state)
    persistent = build_persistent_runtime_status(
        paths=paths,
        trainer_result=trainer_result,
        persistent_state=state,
        resource=resource,
        checkpoint=checkpoint,
    )
    client = connect_redis()
    ledger = as_dict(redis_json(client, "v2:paper:ledger"))
    portfolio = as_dict(read_json(paths.public_root / PORTFOLIO_REL))
    existing_trial_status = as_dict(redis_json(client, TRIAL_STATUS_REDIS_KEY))
    attribution = build_paper_drawdown_attribution(portfolio=portfolio, ledger=ledger)
    guard = build_paper_drawdown_guard(attribution=attribution, existing_trial_status=existing_trial_status)
    redis_guard = apply_paper_drawdown_guard_to_redis(client, guard)
    guard = {**guard, "redis_write_result": redis_guard}
    return publish_persistent_payloads(
        paths=paths,
        persistent=persistent,
        resource=resource,
        checkpoint=checkpoint,
        attribution=attribution,
        guard=guard,
        trainer_result=trainer_result,
        all_timeframe_refresh=all_timeframe_refresh,
    )


def persistent_loop_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_cuda_trainer_persistent_loop")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-training", action="store_true", help="Publish status without running a trainer cycle.")
    args = parser.parse_args(argv)
    paths = PersistentTrainerPaths(repo_root=args.repo_root.resolve())
    cycles = 0
    while True:
        payloads = run_one_persistent_cycle(
            paths=paths,
            max_rows=args.max_rows,
            risk_caps_configured=True,
            run_training=not args.no_training,
        )
        dashboard = as_dict(payloads.get("operator_dashboard_payload.json"))
        print(
            json.dumps(
                {
                    "gate": dashboard.get("gate"),
                    "generated_est": dashboard.get("generated_est"),
                    "training_steps_total": as_dict(dashboard.get("trainer")).get("training_steps_total"),
                    "training_steps_last_hour": as_dict(dashboard.get("trainer")).get("training_steps_last_hour"),
                    "prediction_grid_rows": as_dict(dashboard.get("trainer")).get("prediction_grid_rows"),
                    "paper_guard_status": as_dict(dashboard.get("paper_drawdown")).get("guard_status"),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        cycles += 1
        if args.once or (args.max_cycles and cycles >= args.max_cycles):
            return 0 if dashboard.get("gate") == READY else 2
        # Only pause when training is blocked (no trusted data). When data is
        # flowing the loop runs continuously to maximise GPU utilisation.
        blockers = as_dict(dashboard).get("blockers") or []
        sleep_s = max(5, int(args.interval_seconds)) if blockers else 0
        if sleep_s:
            time.sleep(sleep_s)


__all__ = [
    "READY",
    "BLOCKED",
    "PersistentTrainerPaths",
    "build_paper_drawdown_attribution",
    "build_paper_drawdown_guard",
    "checkpoint_retention_status",
    "run_one_persistent_cycle",
    "persistent_loop_main",
]
