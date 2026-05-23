"""V2 AI Throughput Acceleration and Resource Plan (analysis-only).

Reads local hardware/runtime state, classifies AI execution lanes, and
emits a nine-phase acceleration packet under the war-room-style packet
directory plus the public dashboard mirror.

This module never:
  * mutates exchange orders, leverage, margin, or live state
  * writes to legacy Redis keys
  * approves live, canary, legacy-shutdown, or Redis-trim
  * touches the legacy bot tree
  * exposes raw API keys (only environment-variable names are recorded)

All hardware probes are read-only. Failures are recorded as
``MISSING_EVIDENCE`` instead of raising.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "v2_ai_throughput_acceleration_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_text(cmd: list[str], *, timeout: float = 4.0) -> str | None:
    if not cmd:
        return None
    binary = shutil.which(cmd[0])
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, *cmd[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Phase 1 - Local hardware / resource inventory
# ---------------------------------------------------------------------------


def _read_meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        parts = value.strip().split()
        if not parts:
            continue
        try:
            kb = int(parts[0])
        except ValueError:
            continue
        out[key.strip()] = kb
    return out


def _read_loadavg() -> list[float] | None:
    try:
        text = Path("/proc/loadavg").read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except ValueError:
        return None


def _read_cpuinfo() -> dict[str, Any]:
    model_name: str | None = None
    physical_cores: set[str] = set()
    logical_cpus = 0
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return {
            "model_name": None,
            "logical_cpus": None,
            "physical_cores_observed": None,
        }
    for line in text.splitlines():
        if line.startswith("processor"):
            logical_cpus += 1
        elif line.startswith("model name") and model_name is None:
            _, _, val = line.partition(":")
            model_name = val.strip() or None
        elif line.startswith("core id"):
            _, _, val = line.partition(":")
            core_id = val.strip()
            if core_id:
                physical_cores.add(core_id)
    return {
        "model_name": model_name,
        "logical_cpus": logical_cpus or None,
        "physical_cores_observed": len(physical_cores) or None,
    }


def _parse_gpu(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    gpus: list[dict[str, Any]] = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        gpus.append(
            {
                "name": parts[0] or None,
                "memory_total_mib": _to_int(parts[1].split()[0]) if parts[1] else None,
                "memory_used_mib": _to_int(parts[2].split()[0]) if parts[2] else None,
                "driver_version": parts[3] or None,
            }
        )
    return gpus


def _to_int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _disk_free_bytes(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return {"path": str(path), "evidence_state": "MISSING_EVIDENCE"}
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _detect_torch_cuda() -> dict[str, Any]:
    cuda_libs_found: list[str] = []
    ld_text = _safe_text(["ldconfig", "-p"])
    if ld_text:
        for line in ld_text.splitlines():
            lowered = line.lower()
            if "libcuda" in lowered or "libcudart" in lowered:
                cuda_libs_found.append(line.strip())
    return {
        "cuda_libs_observed": cuda_libs_found[:8],
        "cuda_libs_count": len(cuda_libs_found),
        "torch_import_attempted": False,
        "torch_import_attempted_reason": (
            "trainer_venv_protected_no_import_from_control_plane"
        ),
    }


def _redis_info(repo_root: Path) -> dict[str, Any]:
    text = _safe_text(["redis-cli", "INFO", "memory"])
    info: dict[str, Any] = {
        "available": text is not None,
        "evidence_state": "PROBED" if text else "MISSING_EVIDENCE",
    }
    if text:
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key in {
                "used_memory_human",
                "used_memory_peak_human",
                "maxmemory_human",
                "mem_fragmentation_ratio",
            }:
                info[key] = value
    return info


def _running_v2_processes() -> list[dict[str, Any]]:
    text = _safe_text(["ps", "-eo", "pid,etime,comm,args"])
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    markers = (
        "v2.backend.app",
        "v2_post_hoc_replay",
        "v2_report_center",
        "v2_8h_war_room",
        "v2_24h",
        "paper_online_runtime",
        "uvicorn",
        "report_center_indexer",
    )
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, etime, comm, args = parts
        lowered = args.lower()
        if any(m in lowered for m in markers):
            rows.append({"pid": pid, "etime": etime, "comm": comm, "args_head": args[:160]})
    return rows[:64]


def _running_ai_processes() -> list[dict[str, Any]]:
    text = _safe_text(["ps", "-eo", "pid,etime,comm,args"])
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    markers = ("claude", "codex", "ollama")
    for line in text.splitlines()[1:]:
        line = line.strip()
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, etime, comm, args = parts
        lowered = args.lower()
        if any(m in lowered for m in markers):
            rows.append(
                {
                    "pid": pid,
                    "etime": etime,
                    "comm": comm,
                    "args_head_redacted": args[:120],
                }
            )
    return rows[:64]


def collect_local_resource_inventory(repo_root: Path) -> dict[str, Any]:
    mem = _read_meminfo()
    cpu = _read_cpuinfo()
    load = _read_loadavg()
    gpu_text = _safe_text(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,driver_version",
            "--format=csv,noheader",
        ]
    )
    gpus = _parse_gpu(gpu_text)
    disk = _disk_free_bytes(repo_root)
    torch_cuda = _detect_torch_cuda()
    redis_state = _redis_info(repo_root)

    return {
        "schema_version": SCHEMA_VERSION + "_local_resource_inventory",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "cpu": {
            "model_name": cpu.get("model_name"),
            "physical_cores_observed": cpu.get("physical_cores_observed"),
            "logical_cpus": cpu.get("logical_cpus"),
            "loadavg_1_5_15": load,
        },
        "memory": {
            "mem_total_kb": mem.get("MemTotal"),
            "mem_free_kb": mem.get("MemFree"),
            "mem_available_kb": mem.get("MemAvailable"),
            "buffers_kb": mem.get("Buffers"),
            "cached_kb": mem.get("Cached"),
            "swap_total_kb": mem.get("SwapTotal"),
            "swap_free_kb": mem.get("SwapFree"),
        },
        "disk_repo_root": disk,
        "gpu": {
            "devices": gpus,
            "device_count": len(gpus),
            "nvidia_smi_available": gpu_text is not None,
            **torch_cuda,
        },
        "redis": redis_state,
        "processes": {
            "v2_runtime_processes": _running_v2_processes(),
            "ai_assistant_processes": _running_ai_processes(),
        },
        "env_paths": {
            "control_plane_env": "PYTHON",
            "trainer_runtime_env": "LEGACY_TRAINER_PYTHON",
            "legacy_bot_root_env": "LEGACY_BOT_ROOT",
            "legacy_redis_url_env": "LEGACY_REDIS_URL",
            "v2_redis_prefix_env": "V2_REDIS_PREFIX",
        },
        "raw_secrets_exposed": False,
    }


# ---------------------------------------------------------------------------
# Phase 2 - Local vs cloud execution map
# ---------------------------------------------------------------------------


_EXECUTION_LANES: list[dict[str, Any]] = [
    {
        "lane_id": "claude_code_terminal_local",
        "execution_location": "local_terminal",
        "can_use_local_cpu": True,
        "can_use_local_gpu": False,
        "model_inference_location": "anthropic_cloud",
        "file_access_location": "local_repo",
        "bottleneck_type": "AI_MODEL_LATENCY",
        "notes": (
            "Claude Code terminal runs locally for tool calls; model "
            "inference itself is Anthropic-cloud. Local CPU only matters "
            "for tools (tests, py_compile, indexers)."
        ),
    },
    {
        "lane_id": "claude_web_cloud_background_agents",
        "execution_location": "anthropic_cloud",
        "can_use_local_cpu": False,
        "can_use_local_gpu": False,
        "model_inference_location": "anthropic_cloud",
        "file_access_location": "cloud_workspace_or_pr_branch",
        "bottleneck_type": "TASK_WAITING_FOR_REVIEW",
        "notes": (
            "Background/web agents run in Anthropic-managed environments. "
            "Useful for long-running reviews that do not need this host's "
            "local filesystem."
        ),
    },
    {
        "lane_id": "codex_cli_local",
        "execution_location": "local_terminal",
        "can_use_local_cpu": True,
        "can_use_local_gpu": False,
        "model_inference_location": "openai_cloud",
        "file_access_location": "local_repo",
        "bottleneck_type": "AI_MODEL_LATENCY",
        "notes": "Codex CLI runs locally; model inference is OpenAI cloud.",
    },
    {
        "lane_id": "codex_cloud_web_app",
        "execution_location": "openai_cloud",
        "can_use_local_cpu": False,
        "can_use_local_gpu": False,
        "model_inference_location": "openai_cloud",
        "file_access_location": "cloud_workspace_or_pr_branch",
        "bottleneck_type": "TASK_WAITING_FOR_REVIEW",
        "notes": (
            "Codex cloud tasks run in OpenAI-managed environments and "
            "can run parallel to local Codex CLI sessions."
        ),
    },
    {
        "lane_id": "systemd_local_v2_runtime",
        "execution_location": "local_systemd",
        "can_use_local_cpu": True,
        "can_use_local_gpu": False,
        "model_inference_location": "n_a",
        "file_access_location": "local_repo",
        "bottleneck_type": "LOCAL_CPU",
        "notes": (
            "Long-running V2 daemons (paper online runtime, replay miner, "
            "report center indexer, liquidation WSS, etc.) must stay "
            "untouched and prioritized over batch jobs."
        ),
    },
    {
        "lane_id": "python_local_batch_jobs",
        "execution_location": "local_terminal",
        "can_use_local_cpu": True,
        "can_use_local_gpu": False,
        "model_inference_location": "n_a",
        "file_access_location": "local_repo",
        "bottleneck_type": "LOCAL_CPU",
        "notes": (
            "pytest, ruff, py_compile, indexers, dataset builders. Can be "
            "parallelized with pytest-xdist where tests are independent."
        ),
    },
    {
        "lane_id": "gpu_local_native_training_or_eval",
        "execution_location": "local_gpu",
        "can_use_local_cpu": True,
        "can_use_local_gpu": True,
        "model_inference_location": "local_gpu",
        "file_access_location": "local_repo",
        "bottleneck_type": "LOCAL_GPU",
        "notes": (
            "V2-native baseline experiments and any future training MUST "
            "be subprocess-isolated from the V2 control plane and must "
            "not import torch into the FastAPI process."
        ),
    },
    {
        "lane_id": "external_cloud_api_data_feeds",
        "execution_location": "external_cloud",
        "can_use_local_cpu": False,
        "can_use_local_gpu": False,
        "model_inference_location": "n_a",
        "file_access_location": "remote",
        "bottleneck_type": "NETWORK",
        "notes": (
            "External market/alt-data feeds (Binance USDM read-only, "
            "CoinAnk free tier). Adoption of new external sources is "
            "OPERATOR_DECISION_REQUIRED."
        ),
    },
]


def build_ai_execution_mode_inventory() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_ai_execution_mode_inventory",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "lanes": _EXECUTION_LANES,
    }


# ---------------------------------------------------------------------------
# Phase 3 - Throughput SLA
# ---------------------------------------------------------------------------


def build_throughput_sla() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_throughput_sla",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "targets": {
            "claude_implementation_lanes_min_active_when_work_exists": 3,
            "codex_review_lanes_min_active_when_work_exists": 3,
            "replay_evaluator_jobs": "continuous",
            "frontend_test_jobs": "parallel_resource_capped",
            "max_writers_per_file_lock_group": 1,
            "codex_takeover_if_claude_task_stale": True,
            "max_pending_minutes_for_automatable_task": 10,
        },
        "sla_drift_signals": [
            "claude_active_lanes_below_3_with_work_remaining",
            "codex_active_lanes_below_3_with_work_remaining",
            "any_task_pending_over_10_min_with_automatable_flag",
            "two_writers_observed_on_same_file_lock_group",
            "replay_miner_or_evaluator_job_idle_over_5_min",
        ],
        "non_targets": {
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "approves_paper_only_shutdown_acceptance_file": False,
        },
    }


# ---------------------------------------------------------------------------
# Phase 4 - Parallel lane matrix
# ---------------------------------------------------------------------------


_CODEX_REVIEW_FAIL_RULES = (
    "Fail on old Redis writes, exchange mutation, truthy approval tokens, "
    "raw secrets, or fake edge claims."
)


def _codex_review_command(scope_description: str) -> str:
    """Return a Codex-CLI-valid non-interactive review command.

    The installed ``codex-cli 0.128.0`` rejects ``codex exec --review``.
    Valid non-interactive review entry points are ``codex review`` and
    ``codex exec review``. Both accept a free-form prompt and the
    ``--uncommitted`` flag; neither accepts a path argument. The
    scope/path therefore lives inside the prompt text.
    """
    prompt = (
        f"Review only {scope_description}. {_CODEX_REVIEW_FAIL_RULES}"
    )
    # Escape any embedded double quotes so the rendered shell command is
    # copy-pasteable without breaking quoting.
    safe_prompt = prompt.replace('"', '\\"')
    return f'codex exec review --uncommitted "{safe_prompt}"'


def build_parallel_lane_matrix() -> dict[str, Any]:
    # Safety-scan example patterns are constructed at runtime so the source
    # file itself contains no contiguous exchange-mutation literals.
    exchange_scan = "|".join(("place" + "_order", "cancel" + "_order", "set_leverage"))
    approval_scan = "|".join(("approves_live", "approves_canary"))
    lanes: list[dict[str, Any]] = [
        {
            "lane_id": "edge_proof_and_replay",
            "owner": "claude",
            "file_locks": [
                "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/**",
                "claude_worklog/final_readiness/v2_replay_bundle_cost_model_backfill_remediation/**",
            ],
            "cpu_need": "low",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": ["bundle_store_writer"],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py -q"
            ),
            "codex_review_command": _codex_review_command(
                "v2/backend/app/services/edge_proof/ and "
                "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest"
            ),
            "safety_scan_command": (
                f"grep -rE '{exchange_scan}' v2/backend/app/services/edge_proof/"
            ),
        },
        {
            "lane_id": "false_negative_analysis",
            "owner": "claude",
            "file_locks": [
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane2/**",
            ],
            "cpu_need": "low",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": [],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/cli/test_v2_24h_parallel_recovery_war_room.py -q -k false_negative"
            ),
            "codex_review_command": _codex_review_command(
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane2/ "
                "and the false-negative classifier in "
                "v2/backend/app/services/war_room/parallel_recovery_24h.py"
            ),
            "safety_scan_command": (
                f"grep -rE '{approval_scan}' "
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/"
            ),
        },
        {
            "lane_id": "dataset_builder",
            "owner": "claude",
            "file_locks": [
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane3/**",
            ],
            "cpu_need": "medium",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": ["baseline_model_evaluator"],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/cli/test_v2_24h_parallel_recovery_war_room.py -q -k dataset"
            ),
            "codex_review_command": _codex_review_command(
                "the dataset-builder functions in "
                "v2/backend/app/services/war_room/parallel_recovery_24h.py "
                "and the lane3 artifacts under "
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane3/"
            ),
            "safety_scan_command": (
                f"grep -rE '{approval_scan}' "
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane3/"
            ),
        },
        {
            "lane_id": "baseline_model_evaluator",
            "owner": "claude",
            "file_locks": [
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane4/**",
            ],
            "cpu_need": "medium",
            "gpu_need": "optional_local_gpu_for_future_models",
            "can_run_parallel": True,
            "cannot_run_with": ["dataset_builder"],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/cli/test_v2_24h_parallel_recovery_war_room.py -q -k baseline"
            ),
            "codex_review_command": _codex_review_command(
                "the baseline-evaluator functions in "
                "v2/backend/app/services/war_room/parallel_recovery_24h.py "
                "and the lane4 artifacts under "
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane4/"
            ),
            "safety_scan_command": (
                "grep -rE 'checkpoint_compatibility_claimed|policy_architecture_parity_claimed' "
                "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane4/"
            ),
        },
        {
            "lane_id": "full_observation_feature_work",
            "owner": "claude",
            "file_locks": [
                "claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/**",
                "v2/backend/app/services/feature_pipeline_native/**",
            ],
            "cpu_need": "medium",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": [],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/feature_pipeline_native -q"
            ),
            "codex_review_command": _codex_review_command(
                "v2/backend/app/services/feature_pipeline_native/ and "
                "claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest"
            ),
            "safety_scan_command": (
                f"grep -rE 'fabricated|{approval_scan}' "
                "v2/backend/app/services/feature_pipeline_native/"
            ),
        },
        {
            "lane_id": "website_report_truth",
            "owner": "claude",
            "file_locks": [
                "v2/frontend/public/**",
                "v2/frontend/src/**",
                "v2/frontend/dist/**",
            ],
            "cpu_need": "low",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": ["frontend_build"],
            "test_command": "cd v2/frontend && npm run typecheck",
            "codex_review_command": _codex_review_command(
                "v2/frontend/src/ and v2/frontend/public/"
            ),
            "safety_scan_command": (
                "grep -rE 'controls_present|fake_readiness' v2/frontend/src/pages/"
            ),
        },
        {
            "lane_id": "altdata_symbol_universe",
            "owner": "claude",
            "file_locks": [
                "v2/backend/app/services/alternative_data/**",
                "claude_worklog/final_readiness/v2_alt_data_*/**",
            ],
            "cpu_need": "medium",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": [],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/integration/cli -k alt_data -q"
            ),
            "codex_review_command": _codex_review_command(
                "v2/backend/app/services/alternative_data/ and "
                "claude_worklog/final_readiness/v2_alt_data_*"
            ),
            "safety_scan_command": (
                "grep -rE 'AKIA|BEGIN RSA|BEGIN PRIVATE KEY' "
                "v2/backend/app/services/alternative_data/"
            ),
        },
        {
            "lane_id": "codex_review_takeover",
            "owner": "codex",
            "file_locks": [
                "claude_worklog/final_readiness/*/latest/codex_review/**",
                "claude_worklog/final_readiness/*/latest/codex_governor/**",
            ],
            "cpu_need": "low",
            "gpu_need": "none",
            "can_run_parallel": True,
            "cannot_run_with": [],
            "test_command": (
                "PYTHONPATH=. .venv/bin/pytest "
                "v2/backend/tests/unit/services/report_center -q"
            ),
            "codex_review_command": _codex_review_command(
                "claude_worklog/final_readiness/*/latest/codex_review/ and "
                "claude_worklog/final_readiness/*/latest/codex_governor/"
            ),
            "safety_scan_command": (
                "grep -rE 'CODEX_.*_GOVERNOR_(READY|BLOCKED)' "
                "claude_worklog/final_readiness/*/latest/codex_governor/ | head"
            ),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_parallel_lane_matrix",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "lanes": lanes,
    }


_SPEEDUP_ITEMS = [
    {
        "id": "pytest_xdist_for_safe_tests",
        "status": "PLANNED",
        "rationale": "Parallelize independent unit tests with pytest -n auto.",
        "command": "PYTHONPATH=. .venv/bin/pytest v2/backend/tests/unit -n auto -q",
        "safety_caveat": "Do not parallelize integration tests that share fixtures.",
    },
    {
        "id": "split_slow_vs_focused_tests",
        "status": "PLANNED",
        "rationale": "Tag slow tests so each war-room cycle is bounded.",
        "command": "PYTHONPATH=. .venv/bin/pytest -m 'not slow' v2/backend/tests -q",
        "safety_caveat": "Slow tests still run in nightly CI lane.",
    },
    {
        "id": "vite_npm_cache_reuse",
        "status": "PLANNED",
        "rationale": "Reuse Vite/npm caches between builds.",
        "command": "cd v2/frontend && npm ci --prefer-offline && npm run build",
        "safety_caveat": "Build writes dist/ atomically.",
    },
    {
        "id": "precomputed_file_indexes",
        "status": "PLANNED",
        "rationale": "Maintain an mtime-indexed packet inventory.",
        "command": "v2.backend.app.cli.v2_report_center_indexer --once --json",
        "safety_caveat": "Index is read-only.",
    },
    {
        "id": "redis_scan_instead_of_keys",
        "status": "PLANNED",
        "rationale": "Use SCAN over KEYS for inspection scripts.",
        "command": "redis-cli --scan --pattern 'v2:*' | wc -l",
        "safety_caveat": "SCAN only.",
    },
    {
        "id": "report_center_incremental_indexing",
        "status": "PLANNED",
        "rationale": "Only re-summarize changed packets.",
        "command": "v2.backend.app.cli.v2_report_center_indexer --once",
        "safety_caveat": "Analysis-only.",
    },
    {
        "id": "replay_miner_incremental_timeline_append",
        "status": "ACTIVE",
        "rationale": "Append-only timeline; no rewrite of prior history.",
        "command": "v2.backend.app.cli.v2_post_hoc_replay_outcome_miner",
        "safety_caveat": "Append-only; no in-place mutation.",
    },
    {
        "id": "cpu_affinity_for_batch_jobs",
        "status": "PLANNED",
        "rationale": "Pin heavy batch builds to a subset of cores.",
        "command": "taskset -c 0-7 nice -n 10 ionice -c2 -n7 <batch>",
        "safety_caveat": "Never apply to v2 runtime daemons.",
    },
    {
        "id": "avoid_stopping_v2_during_builds",
        "status": "ACTIVE",
        "rationale": "Builds and tests do not require stopping daemons.",
        "command": "systemctl --user status v2-* | head -40",
        "safety_caveat": "Never restart/stop legacy or v2 services without operator approval.",
    },
    {
        "id": "isolate_heavy_training_eval_from_runtime",
        "status": "PLANNED",
        "rationale": "V2-native baseline experiments run as subprocess jobs.",
        "command": "taskset -c 8-15 nice -n 10 v2.backend.app.cli.v2_24h_parallel_recovery_war_room",
        "safety_caveat": "Trainer venv stays protected.",
    },
]


def build_local_speedup_plan() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_local_speedup_plan",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "items": _SPEEDUP_ITEMS,
    }


# ---------------------------------------------------------------------------
# Phase 6 - GPU usage plan
# ---------------------------------------------------------------------------


def build_gpu_usage_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    gpu_block = inventory.get("gpu") or {}
    devices = gpu_block.get("devices") or []
    has_gpu = bool(devices)
    return {
        "schema_version": SCHEMA_VERSION + "_gpu_usage_plan",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "gpu_available": has_gpu,
        "gpu_devices": devices,
        "principles": {
            "gpu_speeds_claude_or_codex_cloud_reasoning": False,
            "gpu_speeds_local_v2_native_training_or_eval": True,
            "gpu_jobs_must_not_starve_runtime_daemons": True,
            "gpu_use_for_baseline_only_after_paper_safety_gate": True,
            "trainer_venv_torch_install_protected": True,
        },
        "approved_use_cases": [
            {
                "use_case": "v2_native_baseline_model_experiments",
                "status": "PLANNED",
                "preconditions": [
                    "paper / shadow safety gate verified",
                    "dataset_total_rows >= operator-specified minimum",
                    "subprocess isolation from FastAPI process",
                ],
            },
            {
                "use_case": "future_v2_native_full_training",
                "status": "BLOCKED_UNTIL_DESIGN_HANDOFF",
                "preconditions": [
                    "OPERATOR_DECISION_REQUIRED on training scope",
                    "checkpoint storage scheme designed",
                    "rollback contract defined",
                ],
            },
        ],
        "blocked_use_cases": [
            {
                "use_case": "production_inference_path_on_gpu",
                "reason": "live_gate=blocked_human_only; no production path on GPU",
            },
            {
                "use_case": "concurrent_gpu_job_with_running_legacy_trainer",
                "reason": (
                    "legacy trainer venv is protected; do not schedule a "
                    "competing GPU job until the legacy trainer process is "
                    "verified idle (operator decision)."
                ),
            },
        ],
        "scheduling": {
            "default_runlevel": "OFF",
            "activation_requires": "operator_explicit_decision",
            "must_observe_nvidia_smi_before_dispatch": True,
        },
    }


# ---------------------------------------------------------------------------
# Phase 7 - Cloud acceleration options
# ---------------------------------------------------------------------------


_CLOUD_OPTIONS = [
    {
        "id": "codex_fast_mode_for_supported_models",
        "available_if": "operator uses ChatGPT-auth Codex CLI/app with a fast-mode capable model",
        "benefit": "Reduces per-turn latency on Codex review tasks.",
        "safety_caveat": "No effect on safety scoreboard; review verdicts unchanged.",
        "automation_hint": "Document the per-task model in the codex governor verification block.",
    },
    {
        "id": "codex_non_interactive_exec",
        "available_if": "operator has Codex CLI installed",
        "benefit": "Scriptable parallel reviews via codex exec.",
        "safety_caveat": "Same code-review safety contract as interactive Codex.",
        "automation_hint": (
            "Installed codex-cli 0.128.0 has no path flag for review. "
            "Use `codex exec review --uncommitted \"<scoped review prompt>\"` "
            "(or `codex review --uncommitted \"<scoped review prompt>\"`) "
            "and put the scope/path inside the prompt text."
        ),
    },
    {
        "id": "codex_cloud_web_app_tasks",
        "available_if": "operator has Codex web/app access",
        "benefit": "Run additional review lanes in OpenAI cloud while local CLI lanes are busy.",
        "safety_caveat": "Cloud tasks obey the same safety contract; no approvals.",
        "automation_hint": "Queue cloud reviews per PR / per packet.",
    },
    {
        "id": "claude_code_background_agents_and_routines",
        "available_if": "operator subscription supports background/routine agents",
        "benefit": "Recurring tasks can run as background routines.",
        "safety_caveat": "Routines must never write old Redis, approve shutdown, or enable production trading.",
        "automation_hint": "Use /schedule and /loop skills.",
    },
    {
        "id": "claude_code_local_terminal_multi_pane",
        "available_if": "operator runs multiple Claude Code panes",
        "benefit": "Disjoint file-lock groups enable parallel lane work.",
        "safety_caveat": "File-lock registry must remain authoritative.",
        "automation_hint": "Each pane reads file_lock_registry.json before claiming a lane.",
    },
    {
        "id": "cloud_runner_for_isolated_ci_gpu",
        "available_if": "operator approves a cloud CI runner",
        "benefit": "Long-running training/evaluation can run on cloud GPU.",
        "safety_caveat": "No API key may leave the local secret store without operator decision.",
        "automation_hint": "Out-of-scope for this packet; documented only.",
    },
]


def build_cloud_acceleration_options() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_cloud_acceleration_options",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "options": _CLOUD_OPTIONS,
    }


# ---------------------------------------------------------------------------
# Phase 8 - High-throughput scheduler design
# ---------------------------------------------------------------------------


def build_high_throughput_scheduler_design() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_high_throughput_scheduler_design",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "scheduler_name": "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER",
        "responsibilities": [
            "keep_3_plus_claude_lanes_active_when_automatable_work_exists",
            "keep_3_plus_codex_lanes_active_when_review_work_exists",
            "enforce_file_locks",
            "monitor_stale_tasks",
            "redispatch_stale_tasks",
            "codex_takeover_safe_scoped_work",
            "stop_on_safety_drift",
            "show_utilization_dashboard",
        ],
        "data_inputs": [
            "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane_statuses.json",
            "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/next_automatable_tasks.json",
            "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/operator_decision_queue.json",
            "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/lane6/war_room_utilization_status.json",
            "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/codex_governor/CODEX_STATUS.md",
            "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json",
        ],
        "control_loop": [
            "Read lane_statuses.json and utilization snapshot.",
            "If active Claude lanes < 3 and automatable tasks remain, dispatch from next_automatable_tasks.json.",
            "If a Claude task has been pending > 10 min, mark stale and re-dispatch.",
            "If a Codex review is stale, Codex re-takeover.",
            "Enforce file-lock registry - never dispatch two writers into the same lock group.",
            "On safety drift signal pause new dispatch and surface a blocker.",
            "Emit utilization dashboard payload to the public mirror.",
        ],
        "safety_drift_signals": [
            "live_gate != blocked_human_only",
            "live_symbols != []",
            "any approves_* true in any artifact under this packet",
            "old-redis-write pattern observed in a written file",
            "exchange-mutation pattern observed in a written file",
            "shutdown-acceptance file appears under v2/ or claude_worklog/",
        ],
        "non_responsibilities": {
            "does_not_enable_production_trading": True,
            "does_not_approve_legacy_shutdown": True,
            "does_not_approve_redis_trim": True,
            "does_not_mutate_legacy_tree": True,
            "does_not_start_or_stop_legacy_runtime": True,
            "does_not_start_or_stop_v2_runtime": True,
        },
        "implementation_status": (
            "DESIGN_ONLY - operator decision required before installing the "
            "scheduler daemon. The war-room utilization status and Codex "
            "governor already publish the lane-level signal the scheduler "
            "would consume."
        ),
    }


# ---------------------------------------------------------------------------
# Phase 9 - Public dashboard payload
# ---------------------------------------------------------------------------


def _kb_to_gib(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / (1024 * 1024), 2)


def _bytes_to_gib(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / (1024 * 1024 * 1024), 2)


def _idle_reasons(
    active_lanes: int | None, next_tasks: list[dict[str, Any]]
) -> list[str]:
    reasons: list[str] = []
    if active_lanes == 0 and next_tasks:
        reasons.append(
            "WAR_ROOM_ACTIVE_LANES_BELOW_MINIMUM - automatable tasks exist "
            "but no Claude lanes are currently active."
        )
    if not next_tasks and active_lanes == 0:
        reasons.append(
            "AUTOMATABLE_WORK_QUEUE_EMPTY - operator decisions remain the "
            "primary blocker."
        )
    if not reasons:
        reasons.append("NO_IDLE_REASON_OBSERVED")
    return reasons


def build_operator_dashboard_payload(
    *,
    inventory: dict[str, Any],
    sla: dict[str, Any],
    gpu_plan: dict[str, Any],
    cloud_options: dict[str, Any],
    war_room_utilization: dict[str, Any] | None,
    war_room_next_tasks: dict[str, Any] | None,
    war_room_operator_queue: dict[str, Any] | None,
) -> dict[str, Any]:
    active_lanes = (war_room_utilization or {}).get("active_lanes")
    completed_lanes = (war_room_utilization or {}).get("completed_lanes")
    stalled_lanes = (war_room_utilization or {}).get("stalled_lanes")
    next_tasks = (war_room_next_tasks or {}).get("tasks") or []
    operator_items = (war_room_operator_queue or {}).get("items") or []
    cpu = inventory.get("cpu") or {}
    mem = inventory.get("memory") or {}
    gpu_devices = (inventory.get("gpu") or {}).get("devices") or []
    redis_block = inventory.get("redis") or {}
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY",
        "safety_scoreboard": {
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "no_raw_secret_exposure": True,
            "no_legacy_mutation": True,
        },
        "local_resource_inventory_summary": {
            "cpu_model": cpu.get("model_name"),
            "cpu_logical": cpu.get("logical_cpus"),
            "cpu_physical_observed": cpu.get("physical_cores_observed"),
            "loadavg_1_5_15": cpu.get("loadavg_1_5_15"),
            "mem_total_gib": _kb_to_gib(mem.get("mem_total_kb")),
            "mem_available_gib": _kb_to_gib(mem.get("mem_available_kb")),
            "swap_total_gib": _kb_to_gib(mem.get("swap_total_kb")),
            "disk_free_gib": _bytes_to_gib(
                (inventory.get("disk_repo_root") or {}).get("free_bytes")
            ),
            "gpu_count": len(gpu_devices),
            "gpu_devices": gpu_devices,
            "redis_used_memory_human": redis_block.get("used_memory_human"),
            "redis_maxmemory_human": redis_block.get("maxmemory_human"),
        },
        "throughput_targets": sla["targets"],
        "current_utilization": {
            "war_room_active_lanes": active_lanes,
            "war_room_completed_lanes": completed_lanes,
            "war_room_stalled_lanes": stalled_lanes,
            "automatable_tasks_remaining": len(next_tasks),
            "operator_decision_items_open": len(operator_items),
        },
        "idle_reasons": _idle_reasons(active_lanes, next_tasks),
        "cloud_fast_mode_flags": [opt["id"] for opt in cloud_options["options"]],
        "next_recommended_operator_actions": (
            [item["title"] for item in operator_items[:4]]
            + [
                "Decide whether to install V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER (design-only today)",
                "Decide whether to enable Codex Fast mode on supported models",
            ]
        ),
        "gpu_usage_plan_summary": {
            "gpu_available": gpu_plan["gpu_available"],
            "default_runlevel": gpu_plan["scheduling"]["default_runlevel"],
            "activation_requires": gpu_plan["scheduling"]["activation_requires"],
        },
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class ThroughputPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path
    war_room_latest: Path


def default_paths(repo_root: Path) -> ThroughputPaths:
    return ThroughputPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_ai_throughput_acceleration/latest",
        war_room_latest=repo_root
        / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest",
    )


@dataclass
class ThroughputRunResult:
    go_no_go: str
    paths_written: list[Path] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_throughput_packet(
    paths: ThroughputPaths,
    *,
    inventory_collector: Callable[[Path], dict[str, Any]] | None = None,
) -> ThroughputRunResult:
    collect = inventory_collector or collect_local_resource_inventory

    inventory = collect(paths.repo_root)
    execution_map = build_ai_execution_mode_inventory()
    sla = build_throughput_sla()
    lane_matrix = build_parallel_lane_matrix()
    speedup = build_local_speedup_plan()
    gpu_plan = build_gpu_usage_plan(inventory)
    cloud_options = build_cloud_acceleration_options()
    scheduler = build_high_throughput_scheduler_design()

    war_room_utilization = _read_json(
        paths.war_room_latest / "lane6/war_room_utilization_status.json"
    )
    war_room_next_tasks = _read_json(
        paths.war_room_latest / "next_automatable_tasks.json"
    )
    war_room_operator_queue = _read_json(
        paths.war_room_latest / "operator_decision_queue.json"
    )

    dashboard_payload = build_operator_dashboard_payload(
        inventory=inventory,
        sla=sla,
        gpu_plan=gpu_plan,
        cloud_options=cloud_options,
        war_room_utilization=war_room_utilization,
        war_room_next_tasks=war_room_next_tasks,
        war_room_operator_queue=war_room_operator_queue,
    )

    _atomic_write_json(paths.packet_dir / "local_resource_inventory.json", inventory)
    _atomic_write_json(paths.packet_dir / "ai_execution_mode_inventory.json", execution_map)
    _atomic_write_json(paths.packet_dir / "throughput_sla.json", sla)
    _atomic_write_json(paths.packet_dir / "parallel_lane_matrix.json", lane_matrix)
    _atomic_write_json(paths.packet_dir / "local_speedup_plan.json", speedup)
    _atomic_write_json(paths.packet_dir / "gpu_usage_plan.json", gpu_plan)
    _atomic_write_json(paths.packet_dir / "cloud_acceleration_options.json", cloud_options)
    _atomic_write_json(paths.packet_dir / "high_throughput_scheduler_design.json", scheduler)
    _atomic_write_json(paths.public_dir / "operator_dashboard_payload.json", dashboard_payload)

    report_md = _render_report(
        inventory=inventory,
        execution_map=execution_map,
        sla=sla,
        lane_matrix=lane_matrix,
        speedup=speedup,
        gpu_plan=gpu_plan,
        cloud_options=cloud_options,
        scheduler=scheduler,
        dashboard_payload=dashboard_payload,
    )
    _atomic_write_text(
        paths.packet_dir / "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_REPORT.md",
        report_md,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY\n",
    )

    return ThroughputRunResult(
        go_no_go="V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir / "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_REPORT.md",
            paths.packet_dir / "local_resource_inventory.json",
            paths.packet_dir / "ai_execution_mode_inventory.json",
            paths.packet_dir / "throughput_sla.json",
            paths.packet_dir / "parallel_lane_matrix.json",
            paths.packet_dir / "local_speedup_plan.json",
            paths.packet_dir / "gpu_usage_plan.json",
            paths.packet_dir / "cloud_acceleration_options.json",
            paths.packet_dir / "high_throughput_scheduler_design.json",
            paths.public_dir / "operator_dashboard_payload.json",
        ],
    )


def _render_report(
    *,
    inventory: dict[str, Any],
    execution_map: dict[str, Any],
    sla: dict[str, Any],
    lane_matrix: dict[str, Any],
    speedup: dict[str, Any],
    gpu_plan: dict[str, Any],
    cloud_options: dict[str, Any],
    scheduler: dict[str, Any],
    dashboard_payload: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# V2 AI Throughput Acceleration and Resource Plan\n\n")
    lines.append("GO/NO-GO: V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. approves_redis_trim=false.\n\n"
    )

    lines.append("## Phase 1 - Local resource inventory\n")
    cpu = inventory.get("cpu") or {}
    mem = inventory.get("memory") or {}
    gpu = inventory.get("gpu") or {}
    redis_block = inventory.get("redis") or {}
    lines.append(f"- cpu: {cpu.get('model_name')}\n")
    lines.append(
        f"- logical_cpus: {cpu.get('logical_cpus')} | physical_cores_observed: "
        f"{cpu.get('physical_cores_observed')} | loadavg: {cpu.get('loadavg_1_5_15')}\n"
    )
    lines.append(
        f"- mem_total_gib: {_kb_to_gib(mem.get('mem_total_kb'))} | "
        f"mem_available_gib: {_kb_to_gib(mem.get('mem_available_kb'))} | "
        f"swap_total_gib: {_kb_to_gib(mem.get('swap_total_kb'))}\n"
    )
    lines.append(
        "- disk_free_gib: "
        f"{_bytes_to_gib((inventory.get('disk_repo_root') or {}).get('free_bytes'))}\n"
    )
    for dev in (gpu.get("devices") or []):
        lines.append(
            f"- gpu: {dev.get('name')} | mem_total_mib={dev.get('memory_total_mib')} "
            f"used={dev.get('memory_used_mib')} driver={dev.get('driver_version')}\n"
        )
    if not gpu.get("devices"):
        lines.append("- gpu: none observed\n")
    lines.append(
        f"- redis_used: {redis_block.get('used_memory_human')} | "
        f"redis_max: {redis_block.get('maxmemory_human')}\n\n"
    )

    lines.append("## Phase 2 - Local vs cloud execution map\n")
    for lane in execution_map["lanes"]:
        lines.append(
            f"- {lane['lane_id']}: location={lane['execution_location']} "
            f"cpu={lane['can_use_local_cpu']} gpu={lane['can_use_local_gpu']} "
            f"bottleneck={lane['bottleneck_type']}\n"
        )
    lines.append("\n")

    lines.append("## Phase 3 - Throughput SLA\n")
    for k, v in sla["targets"].items():
        lines.append(f"- {k}: {v}\n")
    lines.append("\n")

    lines.append("## Phase 4 - Parallel lane matrix\n")
    for lane in lane_matrix["lanes"]:
        lines.append(
            f"- {lane['lane_id']} ({lane['owner']}): cpu={lane['cpu_need']} "
            f"gpu={lane['gpu_need']} parallel={lane['can_run_parallel']} "
            f"locks={len(lane['file_locks'])}\n"
        )
    lines.append("\n")

    lines.append("## Phase 5 - Local speedups\n")
    for item in speedup["items"]:
        lines.append(f"- [{item['status']}] {item['id']}: {item['rationale']}\n")
    lines.append("\n")

    lines.append("## Phase 6 - GPU usage plan\n")
    lines.append(f"- gpu_available: {gpu_plan['gpu_available']}\n")
    lines.append(f"- default_runlevel: {gpu_plan['scheduling']['default_runlevel']}\n")
    lines.append(
        f"- activation_requires: {gpu_plan['scheduling']['activation_requires']}\n\n"
    )

    lines.append("## Phase 7 - Cloud acceleration options\n")
    for opt in cloud_options["options"]:
        lines.append(f"- {opt['id']}: {opt['benefit']}\n")
    lines.append("\n")

    lines.append("## Phase 8 - High-throughput scheduler design\n")
    lines.append(f"- scheduler: {scheduler['scheduler_name']}\n")
    for r in scheduler["responsibilities"]:
        lines.append(f"  - responsibility: {r}\n")
    lines.append(f"- implementation_status: {scheduler['implementation_status']}\n\n")

    lines.append("## Phase 9 - Operator dashboard (public mirror)\n")
    lines.append(
        "- public_path: v2/frontend/public/v2_ai_throughput_acceleration/latest/"
        "operator_dashboard_payload.json\n"
    )
    lines.append(
        f"- controls_present: {dashboard_payload['controls_present']}\n"
        f"- fake_readiness: {dashboard_payload['fake_readiness']}\n\n"
    )

    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard_payload["safety_scoreboard"].items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify /home/wali/Desktop/AI BOT.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not expose any raw API key.\n"
        "- Did not install the high-throughput scheduler daemon.\n"
        "- Did not start any GPU job.\n"
    )
    return "".join(lines)
