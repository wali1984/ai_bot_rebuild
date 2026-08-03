"""Publish real, per-lane trainer health so the GUI can show visible truth.

Why this exists
---------------
The AI-predictions "Trainer deep telemetry" panel reads
``v2:trainer:hybrid_cuda:status``.  That key is written by exactly one
producer -- ``run_hybrid_trainer_cycle`` -- and that cycle is not running, so
every field sourced from it renders an empty dash.  Meanwhile the lane that IS
running (the continuous offline GPU trainer) publishes nothing to Redis at all,
so a stalled or crashed trainer is invisible in the UI.

This publisher closes that gap **without fabricating trainer telemetry**.  It
does not write ``v2:trainer:hybrid_cuda:*`` -- the paper loop consumes those
keys for promoted-checkpoint decisions, so synthesising them would alter
trading behaviour.  Instead it publishes a separate, clearly-named lane-health
document assembled only from independently checkable evidence:

  * systemd unit state (ActiveState/SubState/Result/NRestarts/ExecMainStatus)
  * whether the lane's process is actually resident, and for how long
  * the age of the lane's newest durable artifact (report / checkpoint / key)
  * whether the lane's Redis evidence key exists at all

Every lane reports a ``health`` verdict, a plain reason, the evidence pointer
that justifies it, and the threshold that was applied -- so the GUI can render
a banner that names the real problem instead of a silent blank cell.

Read-only: places no order, mutates no trainer, touches no live gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "trainer_lane_health_v1"
LANE_HEALTH_KEY = "v2:trainer:lane_health:status"
HYBRID_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
HYBRID_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
# The resident research lane writes this signed status file every cycle but
# performs no Redis I/O, so it is the only evidence of its true runtime state.
RESEARCH_LANE_STATUS_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json"
)
# .../<repo>/v2/backend/app/cli/<this file> -> parents[4] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]

# Health verdicts, ordered worst-first for banner severity resolution.
HEALTH_FAILED = "FAILED"
HEALTH_STOPPED = "STOPPED"
HEALTH_STALLED = "STALLED"
HEALTH_NOT_PUBLISHING = "NOT_PUBLISHING"
HEALTH_HELD = "HELD"
# A lane running a deliberate, self-declared non-promotable observer cycle: it
# emits no promotable checkpoint and allocates no GPU BY DESIGN, so its stale
# artifact / zero-GPU counters are the designed steady state, not a fault.
HEALTH_OBSERVER = "OBSERVER"
HEALTH_OK = "OK"
HEALTH_UNKNOWN = "UNKNOWN"

SEVERITY_BY_HEALTH = {
    HEALTH_FAILED: "error",
    HEALTH_STOPPED: "error",
    HEALTH_STALLED: "error",
    HEALTH_NOT_PUBLISHING: "warn",
    # A lane that is idle between timer firings, or deliberately parked, is
    # operating as expected -- a genuinely overdue timer lane still escalates to
    # STALLED via the artifact-age check below, so HELD itself is not a fault.
    HEALTH_HELD: "ok",
    HEALTH_OBSERVER: "ok",
    HEALTH_UNKNOWN: "warn",
    HEALTH_OK: "ok",
}
SEVERITY_RANK = {"ok": 0, "warn": 1, "error": 2}


@dataclass(frozen=True)
class LaneSpec:
    """Declarative description of one trainer lane and how to verify it."""

    lane_id: str
    label: str
    unit: str | None = None
    # Substring matched against the full process command line.
    process_match: str | None = None
    # Newest file under any of these globs is the lane's durable artifact.
    artifact_globs: tuple[str, ...] = ()
    # Redis key the lane is expected to publish (absence => NOT_PUBLISHING).
    redis_key: str | None = None
    # Artifact older than this => STALLED.
    max_artifact_age_seconds: float | None = None
    # A lane that is expected to be idle between timer firings.
    timer_driven: bool = False
    # A lane deliberately held (drop-in neutered / disabled by an operator).
    expected_inactive: bool = False
    notes: str = ""


LANE_SPECS: tuple[LaneSpec, ...] = (
    LaneSpec(
        lane_id="continuous_offline",
        label="Continuous offline GPU trainer",
        unit="ai-bot-v2-continuous-offline-gpu-trainer.service",
        process_match="v2_trainer_offline_batch_train",
        artifact_globs=(
            "claude_worklog/trainer_atlas/continuous_offline_last_report.json",
            ".local_models/v2_native_rl_masa_ppo_offline/*.weights.npz",
        ),
        max_artifact_age_seconds=45 * 60,
        notes="Trains offline candidates; publishes no Redis trainer status.",
    ),
    LaneSpec(
        lane_id="hybrid_online",
        label="Persistent CUDA trainer (hybrid/online lane)",
        unit="ai-bot-v2-native-cuda-trainer-persistent.service",
        process_match="v2_native_cuda_trainer_persistent_loop",
        redis_key=HYBRID_STATUS_KEY,
        # The resident research lane writes candidate checkpoints, not a Redis
        # status. Verifying those artifacts is what catches a lane that reports
        # "cycle running" while producing nothing.
        artifact_globs=(
            ".local_models/v2_native_rl_masa_ppo/local_profiled_research_candidates/*.weights.npz",
        ),
        max_artifact_age_seconds=6 * 60 * 60,
        notes=(
            "Sole publisher of v2:trainer:hybrid_cuda:status. Runs in "
            "locally-authenticated-profiled-research mode, which is "
            "non-promotable and emits no training telemetry, so the deep "
            "telemetry blocks sourced from that key stay unpublished."
        ),
    ),
    LaneSpec(
        lane_id="scheduled_pretrain",
        label="Scheduled offline pretrain + H2L diagnostic",
        unit="ai-bot-v2-trainer-scheduled-pretrain.service",
        process_match="v2_trainer_scheduled_pretrain",
        artifact_globs=("claude_worklog/trainer_atlas/scheduled_pretrain_*.json",),
        max_artifact_age_seconds=6 * 60 * 60,
        timer_driven=True,
    ),
    LaneSpec(
        lane_id="training_live_loop",
        label="Trainer training live loop",
        unit="ai-bot-v2-trainer-training-live-loop.service",
    ),
    LaneSpec(
        lane_id="checkpoint_evidence",
        label="Trainer checkpoint evidence publisher",
        unit="ai-bot-v2-trainer-checkpoint-evidence.service",
    ),
    LaneSpec(
        lane_id="profiled_base_features",
        label="Profiled base feature publisher",
        unit="ai-bot-v2-profiled-base-feature-publisher.service",
    ),
    LaneSpec(
        lane_id="prediction_serving",
        label="Canonical prediction serving",
        unit="ai-bot-v2-canonical-prediction-serving.service",
        process_match="v2_canonical_prediction_serving_runtime",
    ),
    LaneSpec(
        lane_id="ppo_masa_guard",
        label="PPO/MASA continuous training guard",
        unit="ai-bot-v2-native-ppo-masa-continuous-training-guard.service",
        timer_driven=True,
        expected_inactive=True,
        notes="Timer-driven supervisor; idle between firings.",
    ),
    LaneSpec(
        lane_id="champion_challenger",
        label="Champion/challenger publisher",
        unit="ai-bot-v2-champion-challenger-publisher.service",
        timer_driven=True,
        expected_inactive=True,
    ),
)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _systemctl_show(unit: str) -> dict[str, str]:
    """Return systemd properties for a unit, or {} when unavailable."""
    if not shutil.which("systemctl"):
        return {}
    try:
        completed = subprocess.run(
            [
                "systemctl", "--user", "show", unit,
                "-p", "ActiveState", "-p", "SubState", "-p", "Result",
                "-p", "NRestarts", "-p", "ExecMainStatus", "-p", "LoadState",
                "-p", "ActiveEnterTimestampMonotonic",
            ],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    properties: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            properties[key.strip()] = value.strip()
    return properties


def _process_evidence(match: str) -> dict[str, Any]:
    """Find a resident process whose command line contains ``match``."""
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid,etimes,pcpu,args", "--no-headers"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"process_running": None}
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4 or match not in parts[3]:
            continue
        try:
            return {
                "process_running": True,
                "process_pid": int(parts[0]),
                "process_elapsed_seconds": float(parts[1]),
                "process_cpu_percent": float(parts[2]),
            }
        except ValueError:
            continue
    return {"process_running": False}


def _newest_artifact(globs: Sequence[str], repo_root: Path) -> dict[str, Any]:
    newest_path: Path | None = None
    newest_mtime = 0.0
    for pattern in globs:
        for candidate in repo_root.glob(pattern):
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime, newest_path = mtime, candidate
    if newest_path is None:
        return {"last_artifact_path": None, "last_artifact_age_seconds": None}
    return {
        "last_artifact_path": str(newest_path.relative_to(repo_root)),
        "last_artifact_utc": datetime.fromtimestamp(newest_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "last_artifact_age_seconds": round(max(0.0, time.time() - newest_mtime), 3),
    }


def _gpu_evidence() -> dict[str, Any]:
    if not shutil.which("nvidia-smi"):
        return {"gpu_query_available": False}
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        row = completed.stdout.strip().splitlines()[0]
        used, total = row.split(",")[1:3]
        return {
            "gpu_query_available": True,
            "gpu_utilization_percent": float(row.split(",")[0]),
            "gpu_memory_used_mb": float(used),
            "gpu_memory_total_mb": float(total),
        }
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return {"gpu_query_available": False}


def evaluate_lane(
    spec: LaneSpec,
    *,
    unit_properties: dict[str, str],
    process: dict[str, Any],
    artifact: dict[str, Any],
    redis_key_present: bool | None,
    observer_mode: bool = False,
) -> dict[str, Any]:
    """Derive one lane's health verdict from independently checkable evidence.

    ``observer_mode`` is set only when the lane's own signed status file declares
    it a non-promotable observer with no training runtime wired.  In that state
    the lane emits no promotable checkpoint and allocates no GPU by design, so
    the artifact-staleness and missing-telemetry demotions below are suppressed
    in favour of the benign OBSERVER verdict.  A genuine failure (unit failed /
    stopped) still outranks it, and the moment the lane's status stops declaring
    the observer state the normal STALLED/NOT_PUBLISHING checks apply again.
    """
    active_state = unit_properties.get("ActiveState")
    sub_state = unit_properties.get("SubState")
    result = unit_properties.get("Result")
    load_state = unit_properties.get("LoadState")

    health = HEALTH_UNKNOWN
    reason = "No systemd evidence available for this lane."

    if spec.unit and load_state in {"not-found", "masked"}:
        health, reason = HEALTH_STOPPED, f"Unit {spec.unit} is {load_state}."
    elif active_state == "failed" or (result and result not in {"success", ""}):
        health = HEALTH_FAILED
        reason = f"Unit {spec.unit} failed (Result={result}, ExecMainStatus={unit_properties.get('ExecMainStatus')})."
    elif active_state == "active":
        health, reason = HEALTH_OK, f"Unit {spec.unit} is active ({sub_state})."
    elif active_state == "activating":
        health = HEALTH_OK
        reason = f"Unit {spec.unit} is starting ({sub_state})."
    elif active_state == "inactive":
        if spec.expected_inactive or spec.timer_driven:
            health = HEALTH_HELD
            reason = f"Unit {spec.unit} is idle between timer firings."
        else:
            health, reason = HEALTH_STOPPED, f"Unit {spec.unit} is inactive."

    # A lane whose own signed status declares it a non-promotable observer with
    # no training runtime wired is in its designed steady state: no promotable
    # checkpoint, no GPU allocation. Report that honestly as OBSERVER rather than
    # letting the staleness / missing-telemetry checks flag the designed state as
    # a fault. A failed/stopped unit still outranks this.
    if observer_mode and health in {HEALTH_OK, HEALTH_HELD, HEALTH_UNKNOWN}:
        health = HEALTH_OBSERVER
        reason = (
            f"Unit {spec.unit} is running a deliberate non-promotable research "
            "observer cycle with no training runtime wired: it emits no "
            "promotable checkpoint and allocates no GPU by design, and will "
            "leave this state only once authenticated training samples arrive."
        )

    # Artifact staleness outranks a merely-"active" unit: a resident process
    # that has produced nothing for hours is stalled, not healthy. It also
    # outranks UNKNOWN -- a stale artifact is positive evidence of a stall even
    # when systemd evidence is unavailable. (Skipped for a declared observer,
    # whose stale artifact is the designed steady state.)
    age = artifact.get("last_artifact_age_seconds")
    threshold = spec.max_artifact_age_seconds
    if threshold is not None and health in {HEALTH_OK, HEALTH_HELD, HEALTH_UNKNOWN}:
        if age is None:
            health = HEALTH_STALLED
            reason = "Lane has never produced its durable artifact."
        elif age > threshold:
            health = HEALTH_STALLED
            reason = (
                f"No new artifact for {int(age // 60)} min "
                f"(threshold {int(threshold // 60)} min); "
                f"newest is {artifact.get('last_artifact_path')}."
            )
            if process.get("process_running") and process.get("process_elapsed_seconds"):
                reason += (
                    f" A process has been resident {int(process['process_elapsed_seconds'] // 60)}"
                    " min without completing a cycle."
                )

    # A lane whose declared Redis evidence key is absent cannot populate the UI
    # blocks that read it, even when its unit is nominally healthy. (A declared
    # observer emits no telemetry by design, so this is not counted against it.)
    if spec.redis_key and redis_key_present is False and health == HEALTH_OK:
        health = HEALTH_NOT_PUBLISHING
        reason = (
            f"Unit is active but its evidence key {spec.redis_key} does not exist, "
            "so every GUI field sourced from it renders empty."
        )

    return {
        "lane_id": spec.lane_id,
        "label": spec.label,
        "unit": spec.unit,
        "unit_load_state": load_state,
        "unit_active_state": active_state,
        "unit_sub_state": sub_state,
        "unit_result": result,
        "unit_restart_count": unit_properties.get("NRestarts"),
        "unit_exec_main_status": unit_properties.get("ExecMainStatus"),
        "redis_key": spec.redis_key,
        "redis_key_present": redis_key_present,
        "expected_max_artifact_age_seconds": threshold,
        "timer_driven": spec.timer_driven,
        "health": health,
        "severity": SEVERITY_BY_HEALTH.get(health, "warn"),
        "reason": reason,
        "notes": spec.notes or None,
        **process,
        **artifact,
    }


def _research_lane_runtime() -> dict[str, Any]:
    """Bridge the resident research lane's real on-disk status into the payload.

    The lane writes a signed status file every cycle but performs no Redis I/O
    at all, so its genuine runtime state is invisible to the GUI.  This copies
    the observed fields verbatim -- it never synthesises training telemetry the
    lane does not emit.
    """
    out: dict[str, Any] = {
        "status_path": str(RESEARCH_LANE_STATUS_PATH),
        "status_present": False,
    }
    try:
        raw = json.loads(RESEARCH_LANE_STATUS_PATH.read_text())
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    cuda = raw.get("cuda_runtime") if isinstance(raw.get("cuda_runtime"), dict) else {}
    out.update(
        {
            "status_present": True,
            "classification": raw.get("classification"),
            "cycle_in_progress": raw.get("cycle_in_progress"),
            "cycle_result": raw.get("cycle_result"),
            "runtime_wired": raw.get("runtime_wired"),
            "non_promotable": raw.get("local_research_non_promotable"),
            "service_process_active": raw.get("service_process_active"),
            "error": raw.get("error"),
            "code_sha": raw.get("code_sha"),
            "status_generated_at": raw.get("status_generated_at"),
            "gpu_name": cuda.get("gpu_name"),
            "cuda_available": cuda.get("cuda_available"),
            "memory_allocated_bytes": cuda.get("memory_allocated_bytes"),
            "peak_memory_allocated_bytes": cuda.get("peak_memory_allocated_bytes"),
            "prediction_authorized": raw.get("prediction_authorized"),
            "serving_promotion_authorized": raw.get("serving_promotion_authorized"),
            "paper_trading_authorized": raw.get("paper_trading_authorized"),
        }
    )
    return out


def _idle_gpu_alert(research: Mapping[str, Any]) -> dict[str, Any] | None:
    """Catch a lane that reports a running cycle while doing no GPU work.

    A resident trainer can report ``cycle_in_progress`` indefinitely while never
    allocating a single byte of device memory.  Unit state alone reads healthy,
    so this compares the lane's own claim against its own CUDA counters.
    """
    if research.get("status_present") is not True:
        return None
    # A deliberate non-promotable observer with no training runtime wired
    # allocates no device memory BY DESIGN -- that is its designed steady state,
    # not a lane that claimed to train and then didn't. Only a lane that is
    # supposed to be training (runtime wired) yet shows zero GPU is a fault.
    if research.get("non_promotable") is True and research.get("runtime_wired") is not True:
        return None
    if research.get("cycle_in_progress") is not True:
        return None
    peak = research.get("peak_memory_allocated_bytes")
    allocated = research.get("memory_allocated_bytes")
    if not (isinstance(peak, (int, float)) and isinstance(allocated, (int, float))):
        return None
    if peak > 0 or allocated > 0:
        return None
    return {
        "severity": "error",
        "lane_id": "hybrid_online",
        "label": "Persistent CUDA trainer (hybrid/online lane)",
        "code": "TRAINER_LANE_CYCLE_CLAIMED_BUT_GPU_NEVER_ALLOCATED",
        "message": (
            "Persistent CUDA trainer reports a research cycle in progress on "
            f"{research.get('gpu_name') or 'the GPU'} but has never allocated "
            "device memory (peak allocated is 0 bytes), so no training work is "
            "actually running."
        ),
        "evidence_pointer": str(RESEARCH_LANE_STATUS_PATH),
    }


def build_lane_health(
    *,
    repo_root: Path = REPO_ROOT,
    redis_client: Any | None = None,
    specs: Sequence[LaneSpec] = LANE_SPECS,
) -> dict[str, Any]:
    # Resolve the resident research lane's real state up front: it is the signal
    # that tells the hybrid/online lane apart from a genuine stall -- a declared
    # non-promotable observer with no runtime wired is healthy-idle by design.
    research = _research_lane_runtime()
    observer_declared = (
        research.get("status_present") is True
        and research.get("non_promotable") is True
        and research.get("runtime_wired") is not True
    )

    lanes: list[dict[str, Any]] = []
    for spec in specs:
        unit_properties = _systemctl_show(spec.unit) if spec.unit else {}
        process = _process_evidence(spec.process_match) if spec.process_match else {}
        artifact = _newest_artifact(spec.artifact_globs, repo_root) if spec.artifact_globs else {}
        redis_key_present: bool | None = None
        if spec.redis_key and redis_client is not None:
            try:
                redis_key_present = bool(redis_client.exists(spec.redis_key))
            except Exception:  # noqa: BLE001 - evidence unavailable, stay honest
                redis_key_present = None
        lanes.append(
            evaluate_lane(
                spec,
                unit_properties=unit_properties,
                process=process,
                artifact=artifact,
                redis_key_present=redis_key_present,
                observer_mode=observer_declared and spec.lane_id == "hybrid_online",
            )
        )

    alerts = [
        {
            "severity": lane["severity"],
            "lane_id": lane["lane_id"],
            "label": lane["label"],
            "code": f"TRAINER_LANE_{lane['health']}",
            "message": f"{lane['label']}: {lane['reason']}",
            "evidence_pointer": lane.get("unit") or lane.get("redis_key"),
        }
        for lane in lanes
        if lane["severity"] != "ok"
    ]
    idle_gpu = _idle_gpu_alert(research)
    if idle_gpu is not None:
        alerts.append(idle_gpu)
    alerts.sort(key=lambda a: -SEVERITY_RANK.get(a["severity"], 0))
    worst = max((SEVERITY_RANK.get(a["severity"], 0) for a in alerts), default=0)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_now(),
        "source": f"redis:{LANE_HEALTH_KEY}",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "lanes": lanes,
        "alerts": alerts,
        "alert_count": len(alerts),
        "worst_severity": {0: "ok", 1: "warn", 2: "error"}[worst],
        "healthy_lane_count": sum(1 for lane in lanes if lane["severity"] == "ok"),
        "total_lane_count": len(lanes),
        "hybrid_status_key_present": any(
            lane.get("redis_key") == HYBRID_STATUS_KEY and lane.get("redis_key_present") is True
            for lane in lanes
        ),
        "gpu_runtime_observed": _gpu_evidence(),
        "research_lane_runtime": research,
    }


def publish(client: Any, payload: dict[str, Any], *, ttl_seconds: int) -> None:
    client.set(LANE_HEALTH_KEY, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish real per-lane trainer health.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--ttl-seconds", type=int, default=120)
    parser.add_argument(
        "--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    parser.add_argument("--no-publish", action="store_true", help="print only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    import redis

    client = redis.Redis.from_url(
        arguments.redis_url, decode_responses=True, socket_connect_timeout=3
    )
    while True:
        payload = build_lane_health(redis_client=client)
        if not arguments.no_publish:
            publish(client, payload, ttl_seconds=arguments.ttl_seconds)
        if arguments.once:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str), flush=True)
            return 0
        time.sleep(max(1.0, arguments.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
