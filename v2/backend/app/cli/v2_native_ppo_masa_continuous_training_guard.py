"""Keep the native PPO/MASA CUDA trainer fresh.

This guard is intentionally operational, not a trading shortcut. It keeps the
V2 trainer timer and live training loop active, retriggers a paper/shadow CUDA
cycle when evidence goes stale, and publishes an operator payload. It never
places orders, never calls test-order, never changes leverage or margin, and
never writes old Redis keys.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
EST = ZoneInfo("America/New_York")

PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_native_ppo_masa_continuous_training_guard"
    / "latest"
)
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_native_ppo_masa_continuous_training_guard"
    / "latest"
)

TRAINER_TIMER = "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer"
TRAINER_ONESHOT = "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.service"
PERSISTENT_TRAINER = "ai-bot-v2-native-cuda-trainer-persistent.service"
TRAINING_LIVE_LOOP = "ai-bot-v2-trainer-training-live-loop.service"
RUNTIME_TRUTH_PUBLISHER = "v2.backend.app.cli.v2_realtime_runtime_truth_publisher"

TRAINER_DASHBOARD = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_native_rl_masa_ppo_cuda_trainer_implementation"
    / "latest"
    / "operator_dashboard_payload.json"
)
NATIVE_TRAINER_RUNTIME = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_native_trainer"
    / "latest"
    / "native_trainer_runtime_status.json"
)
RUNTIME_TRUTH = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_runtime_truth"
    / "latest"
    / "operator_runtime_truth.json"
)
TRAINING_LIVE_STATUS = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_trainer_training_live_loop"
    / "latest"
    / "v2_trainer_training_live_loop_status.json"
)


def est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text[:-1] + "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=EST)
        return parsed
    except ValueError:
        return None


def generated_age_seconds(path: Path, payload: dict[str, Any]) -> float | None:
    candidates = [
        payload.get("generated_est"),
        payload.get("generated_utc"),
        payload.get("finished_at"),
        payload.get("started_at"),
    ]
    nested_trainer = payload.get("trainer")
    if isinstance(nested_trainer, dict):
        candidates.extend(
            [
                nested_trainer.get("generated_est"),
                nested_trainer.get("generated_utc"),
            ]
        )
    for candidate in candidates:
        parsed = parse_time(candidate)
        if parsed is not None:
            return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def systemctl(*args: str, timeout: int = 30) -> dict[str, Any]:
    cmd = ["systemctl", "--user", *args]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": "timeout",
        }


def unit_state(unit: str) -> dict[str, str]:
    result = systemctl(
        "show",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "Result",
        "-p",
        "NRestarts",
        unit,
    )
    fields: dict[str, str] = {"unit": unit, "query_returncode": str(result["returncode"])}
    for line in str(result.get("stdout") or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


def active(unit: str) -> bool:
    state = unit_state(unit)
    return state.get("ActiveState") in {"active", "activating"}


def run_python_module(module: str, *args: str, timeout: int = 120) -> dict[str, Any]:
    cmd = [sys.executable, "-m", module, *args]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-1000:],
            "stderr": completed.stderr.strip()[-1000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": 124,
            "stdout": str(exc.stdout or "")[-1000:],
            "stderr": "timeout",
        }


def exploration_status(trainer_payload: dict[str, Any]) -> dict[str, Any]:
    trainer = trainer_payload.get("trainer") if isinstance(trainer_payload.get("trainer"), dict) else {}
    rollout = trainer.get("parallel_environment_rollout") if isinstance(trainer.get("parallel_environment_rollout"), dict) else {}
    architecture = trainer.get("model_architecture") if isinstance(trainer.get("model_architecture"), dict) else {}
    metrics = trainer_payload.get("metrics") if isinstance(trainer_payload.get("metrics"), dict) else {}
    reward_stack = metrics.get("reward_stack") if isinstance(metrics.get("reward_stack"), dict) else {}
    return {
        "status": "PAPER_SHADOW_EXPLORATION_ACTIVE",
        "scope": "training_and_paper_shadow_only",
        "live_exploration_allowed": False,
        "action_contract": rollout.get("action_contract") or [],
        "configured_parallel_envs": rollout.get("configured_n_envs"),
        "rollout_n_steps": rollout.get("rollout_n_steps"),
        "reward_avg_bps": rollout.get("reward_avg_bps"),
        "reward_max_bps": rollout.get("reward_max_bps"),
        "reward_min_bps": rollout.get("reward_min_bps"),
        "ppo_policy_head": bool(architecture.get("ppo_policy_head")),
        "ppo_value_head": bool(architecture.get("value_head")),
        "masa_auxiliary_head": bool(architecture.get("masa_auxiliary_head")),
        "masa_adapter_blend": bool(architecture.get("masa_adapter_blend")),
        "reward_stack": {
            "after_cost_return": bool(reward_stack.get("after_cost_return")),
            "false_positive_penalty": bool(reward_stack.get("false_positive_penalty")),
            "false_negative_penalty": bool(reward_stack.get("false_negative_penalty")),
            "drawdown_penalty": bool(reward_stack.get("drawdown_penalty")),
            "liquidation_regime_awareness": bool(reward_stack.get("liquidation_regime_awareness")),
        },
        "profitability_policy": "optimize paper/shadow outcomes; do not claim or force profitability; live uses risk/live-gate constraints",
    }


def build_payload(
    *,
    max_trainer_age_seconds: int,
    max_training_loop_age_seconds: int,
    trigger_stale: bool,
    dry_run: bool,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []

    timer_state_before = unit_state(TRAINER_TIMER)
    trainer_service_state_before = unit_state(TRAINER_ONESHOT)
    persistent_state_before = unit_state(PERSISTENT_TRAINER)
    training_loop_state_before = unit_state(TRAINING_LIVE_LOOP)
    persistent_active_before = active(PERSISTENT_TRAINER)

    if not persistent_active_before and not active(TRAINER_TIMER):
        action = {"action": "start_timer", "unit": TRAINER_TIMER, "dry_run": dry_run}
        if not dry_run:
            action["result"] = systemctl("enable", "--now", TRAINER_TIMER)
        actions.append(action)

    # The persistent CUDA trainer is the sole online trainer in the current
    # topology; the legacy training-live-loop is superseded and deliberately
    # disabled. Only fall back to it when the persistent trainer is NOT active,
    # otherwise starting it would spawn a second, conflicting online trainer.
    if not persistent_active_before and not active(TRAINING_LIVE_LOOP):
        action = {"action": "start_service", "unit": TRAINING_LIVE_LOOP, "dry_run": dry_run}
        if not dry_run:
            action["result"] = systemctl("start", TRAINING_LIVE_LOOP)
        actions.append(action)
    elif persistent_active_before:
        actions.append(
            {
                "action": "skip_start_training_live_loop_persistent_is_owner",
                "unit": TRAINING_LIVE_LOOP,
                "persistent_active": True,
            }
        )

    trainer_payload = read_json(NATIVE_TRAINER_RUNTIME) or read_json(TRAINER_DASHBOARD)
    runtime_truth = read_json(RUNTIME_TRUTH)
    training_live_payload = read_json(TRAINING_LIVE_STATUS)
    trainer_age = generated_age_seconds(NATIVE_TRAINER_RUNTIME, trainer_payload)
    training_loop_age = generated_age_seconds(TRAINING_LIVE_STATUS, training_live_payload)

    trainer_stale = trainer_age is None or trainer_age > max_trainer_age_seconds
    training_live_stale = training_loop_age is None or training_loop_age > max_training_loop_age_seconds
    trainer_running = active(TRAINER_ONESHOT) or active(PERSISTENT_TRAINER)

    if trigger_stale and trainer_stale and not trainer_running:
        action = {
            "action": "trigger_native_cuda_trainer_cycle",
            "unit": TRAINER_ONESHOT,
            "reason": "trainer_evidence_stale",
            "trainer_age_seconds": trainer_age,
            "dry_run": dry_run,
        }
        if not dry_run:
            action["result"] = systemctl("start", TRAINER_ONESHOT, timeout=240)
            trainer_payload = read_json(TRAINER_DASHBOARD)
            trainer_age = generated_age_seconds(TRAINER_DASHBOARD, trainer_payload)
            trainer_stale = trainer_age is None or trainer_age > max_trainer_age_seconds
        actions.append(action)

    refresh_truth = run_python_module(RUNTIME_TRUTH_PUBLISHER, "--once", timeout=60) if not dry_run else {"dry_run": True}
    runtime_truth_after = read_json(RUNTIME_TRUTH)

    timer_state_after = unit_state(TRAINER_TIMER)
    trainer_service_state_after = unit_state(TRAINER_ONESHOT)
    persistent_state_after = unit_state(PERSISTENT_TRAINER)
    training_loop_state_after = unit_state(TRAINING_LIVE_LOOP)
    persistent_active_after = persistent_state_after.get("ActiveState") == "active"

    blockers: list[str] = []
    if not persistent_active_after and timer_state_after.get("ActiveState") != "active":
        blockers.append("NATIVE_PPO_MASA_TRAINER_TIMER_NOT_ACTIVE")
    if training_loop_state_after.get("ActiveState") != "active":
        blockers.append("TRAINER_TRAINING_LIVE_LOOP_NOT_ACTIVE")
    if trainer_stale:
        blockers.append("NATIVE_PPO_MASA_TRAINER_EVIDENCE_STALE")
    if training_live_stale:
        blockers.append("TRAINER_TRAINING_LIVE_LOOP_STATUS_STALE")
    if runtime_truth_after.get("live_order_submit_allowed") is True:
        blockers.append("UNEXPECTED_LIVE_SUBMIT_ALLOWED_DURING_TRAINER_GUARD")

    trainer = trainer_payload.get("trainer") if isinstance(trainer_payload.get("trainer"), dict) else {}
    metrics = trainer_payload.get("metrics") if isinstance(trainer_payload.get("metrics"), dict) else {}
    training_metrics = metrics.get("training") if isinstance(metrics.get("training"), dict) else {}
    training_inner_metrics = (
        training_metrics.get("metrics") if isinstance(training_metrics.get("metrics"), dict) else {}
    )
    prediction_count = trainer_payload.get("prediction_count")
    if prediction_count is None:
        prediction_count = metrics.get("prediction_count")
    if prediction_count is None:
        prediction_count = len(trainer_payload.get("predictions") or [])
    lineage_count = trainer_payload.get("lineage_count")
    if lineage_count is None:
        lineage_count = metrics.get("lineage_count")
    if lineage_count is None:
        lineage_count = len(trainer_payload.get("lineages") or [])

    return {
        "schema_version": "v2_native_ppo_masa_continuous_training_guard_v1",
        "generated_est": est_now(),
        "generated_utc": utc_now(),
        "gate": (
            "V2_NATIVE_PPO_MASA_CONTINUOUS_TRAINING_AND_EXPLORATION_GUARD_READY"
            if not blockers
            else "V2_NATIVE_PPO_MASA_CONTINUOUS_TRAINING_AND_EXPLORATION_GUARD_BLOCKED"
        ),
        "blockers": blockers,
        "actions": actions,
        "units_before": {
            PERSISTENT_TRAINER: persistent_state_before,
            TRAINER_TIMER: timer_state_before,
            TRAINER_ONESHOT: trainer_service_state_before,
            TRAINING_LIVE_LOOP: training_loop_state_before,
        },
        "units_after": {
            PERSISTENT_TRAINER: persistent_state_after,
            TRAINER_TIMER: timer_state_after,
            TRAINER_ONESHOT: trainer_service_state_after,
            TRAINING_LIVE_LOOP: training_loop_state_after,
        },
        "freshness": {
            "trainer_dashboard_age_seconds": trainer_age,
            "trainer_dashboard_max_age_seconds": max_trainer_age_seconds,
            "trainer_dashboard_stale": trainer_stale,
            "training_live_loop_status_age_seconds": training_loop_age,
            "training_live_loop_max_age_seconds": max_training_loop_age_seconds,
            "training_live_loop_status_stale": training_live_stale,
        },
        "trainer": {
            "trainer_source": trainer.get("trainer_source") or runtime_truth_after.get("trainer_status"),
            "model_source": trainer.get("model_source"),
            "checkpoint_id": trainer.get("checkpoint_id"),
            "cuda_active": bool(trainer.get("cuda_active") or trainer_payload.get("cuda_active")),
            "model_device": trainer.get("model_device"),
            "examples_built": trainer.get("examples_built") or trainer_payload.get("train_rows"),
            "input_dim": trainer.get("input_dim"),
            "training_rows": runtime_truth_after.get("training_rows"),
            "predictions": prediction_count or trainer_payload.get("prediction_grid_rows"),
            "lineages": lineage_count,
            "actual_batch_size": training_inner_metrics.get("actual_batch_size"),
            "selected_examples": training_inner_metrics.get("selected_examples"),
            "training_steps_per_minute": training_inner_metrics.get("training_steps_per_minute")
            or trainer_payload.get("training_steps_per_minute"),
            "persistent_trainer_active": persistent_active_after,
            "persistent_training_steps_last_hour": trainer_payload.get("training_steps_last_hour"),
        },
        "exploration": exploration_status(trainer_payload),
        "live_constraints": {
            "live_gate": runtime_truth_after.get("live_gate"),
            "trader_state": runtime_truth_after.get("trader_state"),
            "live_order_submit_allowed": runtime_truth_after.get("live_order_submit_allowed"),
            "live_order_submit_blocker": runtime_truth_after.get("live_order_submit_blocker"),
            "live_training_exploration_executes_orders": False,
        },
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_or_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
        },
        "runtime_truth_refresh": refresh_truth,
    }


def write_outputs(payload: dict[str, Any]) -> None:
    report_lines = [
        "# V2 Native PPO/MASA Continuous Training And Exploration Guard Report",
        "",
        f"Gate: `{payload['gate']}`",
        f"Generated EST: `{payload['generated_est']}`",
        f"Persistent trainer: `{payload['units_after'][PERSISTENT_TRAINER].get('ActiveState')}/{payload['units_after'][PERSISTENT_TRAINER].get('SubState')}`",
        f"Trainer timer: `{payload['units_after'][TRAINER_TIMER].get('ActiveState')}/{payload['units_after'][TRAINER_TIMER].get('SubState')}`",
        f"Training live loop: `{payload['units_after'][TRAINING_LIVE_LOOP].get('ActiveState')}/{payload['units_after'][TRAINING_LIVE_LOOP].get('SubState')}`",
        f"Native CUDA trainer evidence stale: `{payload['freshness']['trainer_dashboard_stale']}`",
        f"CUDA active: `{payload['trainer']['cuda_active']}`",
        f"Examples built: `{payload['trainer']['examples_built']}`",
        f"Training rows: `{payload['trainer']['training_rows']}`",
        f"Predictions/lineages: `{payload['trainer']['predictions']}/{payload['trainer']['lineages']}`",
        f"Exploration scope: `{payload['exploration']['scope']}`",
        f"Live submit allowed: `{payload['live_constraints']['live_order_submit_allowed']}`",
        f"Live submit blocker: `{payload['live_constraints']['live_order_submit_blocker']}`",
        "",
        "The guard keeps PPO/MASA learning and exploration alive in paper/shadow mode. It does not force live trades and does not claim guaranteed profitability. Live execution remains controlled by the live gate, account balance, accepted symbols, risk caps, and lineage checks.",
        "",
        "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.",
    ]
    files = {
        "GO_NO_GO.md": payload["gate"] + "\n",
        "native_ppo_masa_continuous_training_guard_status.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "operator_dashboard_payload.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "V2_NATIVE_PPO_MASA_CONTINUOUS_TRAINING_AND_EXPLORATION_GUARD_REPORT.md": "\n".join(report_lines) + "\n",
    }
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            (base / name).write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_ppo_masa_continuous_training_guard")
    parser.add_argument("--once", action="store_true", help="Run one guard pass.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-trainer-age-seconds", type=int, default=420)
    parser.add_argument("--max-training-loop-age-seconds", type=int, default=900)
    parser.add_argument("--no-trigger-stale", action="store_true")
    args = parser.parse_args(argv)
    payload = build_payload(
        max_trainer_age_seconds=args.max_trainer_age_seconds,
        max_training_loop_age_seconds=args.max_training_loop_age_seconds,
        trigger_stale=not args.no_trigger_stale,
        dry_run=bool(args.dry_run),
    )
    write_outputs(payload)
    print(
        json.dumps(
            {
                "gate": payload["gate"],
                "blockers": payload["blockers"],
                "actions": [a.get("action") for a in payload["actions"]],
                "trainer_stale": payload["freshness"]["trainer_dashboard_stale"],
                "live_submit_allowed": payload["live_constraints"]["live_order_submit_allowed"],
            },
            sort_keys=True,
        )
    )
    return 0 if not payload["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
