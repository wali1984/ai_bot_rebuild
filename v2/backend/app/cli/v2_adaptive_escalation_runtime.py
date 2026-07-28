"""Automatic paper-only adaptation escalation over authenticated runtime evidence.

This coordinator closes the operational gap between the pure escalation planner
and the signed candidate-outcome dataset/training workers.  It authenticates the
current policy, outcome, and economic-failure status, refreshes the immutable
dataset release only after the predeclared information-gain threshold is met,
reconstructs completed ladder steps from content-addressed dispatch receipts,
and executes at most one paper-only worker per invocation.

It has no model-registry, paper-fill, order, or live authority.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor
from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import LADDER

SCHEMA_VERSION = "adaptive_escalation_runtime_v1"
PERFORMANCE_STATUS_KEY = "v2:paper:performance_governor_status"
DEFAULT_RELEASE_PARENT = Path(
    "/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v3"
)
DEFAULT_RUNTIME_STATE_PATH = DEFAULT_RELEASE_PARENT / "escalation_runtime_state_v1.json"
DEFAULT_RUNTIME_LOCK_PATH = Path(
    "/run/user/1000/ai-bot-v2-adaptive-escalation-runtime.lock"
)
DEFAULT_FEATURE_ARCHIVE_ROOT = Path(
    "/home/wali/Desktop/AI BOT REBUILD/.local_data/v2_native_trainer/"
    "durable_feature_snapshot_archive"
)
DEFAULT_MAX_STATUS_AGE_SECONDS = 600.0
DEFAULT_MIN_NEW_MATURED_OUTCOMES = 250
DEFAULT_MIN_NEW_EFFECTIVE_N = 25.0


class AdaptiveEscalationRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseEvidence:
    root: Path
    projection: Mapping[str, Any]
    source_matured_revision_count: int
    source_decision_revision_count: int
    source_terminal_chain_sha256: str


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdaptiveEscalationRuntimeError("STRICT_JSON_REQUIRED") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_bytes(path: Path, field: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise AdaptiveEscalationRuntimeError(f"{field}:REGULAR_FILE_REQUIRED") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise AdaptiveEscalationRuntimeError(f"{field}:REGULAR_FILE_REQUIRED")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular_bytes(path, field))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdaptiveEscalationRuntimeError(f"{field}:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        raise AdaptiveEscalationRuntimeError(f"{field}:OBJECT_REQUIRED")
    return value


def _safe_directory(path: Path, field: str, *, create: bool) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise AdaptiveEscalationRuntimeError(f"{field}:SAFE_DIRECTORY_REQUIRED") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AdaptiveEscalationRuntimeError(f"{field}:SAFE_DIRECTORY_REQUIRED")
    return path.absolute()


@contextmanager
def _single_run_lock(path: Path) -> Iterator[None]:
    parent = _safe_directory(path.parent, "runtime_lock_parent", create=True)
    try:
        descriptor = os.open(
            parent / path.name,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise AdaptiveEscalationRuntimeError(
            "runtime_lock:REGULAR_FILE_REQUIRED"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise AdaptiveEscalationRuntimeError("runtime_lock:REGULAR_FILE_REQUIRED")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AdaptiveEscalationRuntimeError("runtime_lock:CONTENDED") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _parse_utc(value: object, field: str) -> datetime:
    if type(value) is not str:
        raise AdaptiveEscalationRuntimeError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdaptiveEscalationRuntimeError(f"{field}:UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise AdaptiveEscalationRuntimeError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    return parsed


def _require_fresh(
    payload: Mapping[str, Any],
    *,
    timestamp_field: str,
    now: datetime,
    max_age_seconds: float,
    field: str,
) -> datetime:
    generated = _parse_utc(payload.get(timestamp_field), f"{field}.{timestamp_field}")
    age = (now - generated).total_seconds()
    if age < 0.0 or age > max_age_seconds:
        raise AdaptiveEscalationRuntimeError(f"{field}:STALE_OR_FUTURE")
    return generated


def _safe_paper_authority(payload: Mapping[str, Any], field: str) -> None:
    if (
        payload.get("paper_only") is not True
        or payload.get("routes_to_live") is not False
        or payload.get("places_real_order") is not False
        or payload.get("exchange_action_taken") is not False
    ):
        raise AdaptiveEscalationRuntimeError(f"{field}:UNSAFE_AUTHORITY")


def _get_required_json(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception as exc:
        raise AdaptiveEscalationRuntimeError(f"redis:{key}:READ_FAILED") from exc
    if not raw:
        raise AdaptiveEscalationRuntimeError(f"redis:{key}:MISSING")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "strict")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise AdaptiveEscalationRuntimeError(f"redis:{key}:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        raise AdaptiveEscalationRuntimeError(f"redis:{key}:OBJECT_REQUIRED")
    return value


def authenticate_runtime_inputs(
    client: Any,
    *,
    now: datetime,
    max_age_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = _get_required_json(client, supervisor.POLICY_AUTHORITY_STATUS_KEY)
    outcomes = _get_required_json(client, supervisor.CANDIDATE_OUTCOMES_STATUS_KEY)
    performance = _get_required_json(client, PERFORMANCE_STATUS_KEY)

    if authority.get("schema_version") != "adaptive_paper_policy_runtime_status_v2":
        raise AdaptiveEscalationRuntimeError("policy_authority:SCHEMA_INVALID")
    _require_fresh(
        authority,
        timestamp_field="generated_utc",
        now=now,
        max_age_seconds=max_age_seconds,
        field="policy_authority",
    )
    _safe_paper_authority(authority, "policy_authority")
    if authority.get("live_gate") != "blocked_human_only":
        raise AdaptiveEscalationRuntimeError("policy_authority:LIVE_GATE_BLOCK_REQUIRED")

    if outcomes.get("schema_version") != "candidate_outcome_publisher_runtime_v2":
        raise AdaptiveEscalationRuntimeError("candidate_outcomes:SCHEMA_INVALID")
    _require_fresh(
        outcomes,
        timestamp_field="generated_at",
        now=now,
        max_age_seconds=max_age_seconds,
        field="candidate_outcomes",
    )
    _safe_paper_authority(outcomes, "candidate_outcomes")
    archive = outcomes.get("archive")
    maturation = outcomes.get("maturation")
    if type(archive) is not dict or type(maturation) is not dict:
        raise AdaptiveEscalationRuntimeError("candidate_outcomes:ARCHIVE_AND_MATURATION_REQUIRED")
    _safe_paper_authority(archive, "candidate_outcomes.archive")
    if (
        archive.get("verified") is not True
        or archive.get("invalid_row_count") != 0
        or archive.get("duplicate_archive_record_count") != 0
        or outcomes.get("candidate_recording_coverage") != 1.0
        or outcomes.get("unexplained_candidate_drops") != 0
        or maturation.get("eligible_matured_label_coverage") != 1.0
        or maturation.get("unexplained_maturation_drops") != 0
        or maturation.get("matured_revision_count")
        != archive.get("matured_revision_count")
    ):
        raise AdaptiveEscalationRuntimeError("candidate_outcomes:INTEGRITY_INVALID")

    if performance.get("schema_version") != "paper_performance_governor_status_v2":
        raise AdaptiveEscalationRuntimeError("performance_status:SCHEMA_INVALID")
    _require_fresh(
        performance,
        timestamp_field="generated_utc",
        now=now,
        max_age_seconds=max_age_seconds,
        field="performance_status",
    )
    _safe_paper_authority(performance, "performance_status")
    edge = performance.get("notional_weighted_expectancy_bps")
    if isinstance(edge, bool) or not isinstance(edge, int | float) or not math.isfinite(edge):
        raise AdaptiveEscalationRuntimeError("performance_status:FINITE_EDGE_REQUIRED")
    closed = performance.get("closed_outcome_count")
    governed = performance.get("governed_closed_rows")
    if type(closed) is not int or closed <= 0 or closed != governed:
        raise AdaptiveEscalationRuntimeError("performance_status:COHERENT_CLOSED_COUNT_REQUIRED")
    performance = dict(performance)
    performance["source_payload_sha256"] = _sha256_bytes(_canonical_bytes(performance))
    return dict(authority), dict(outcomes), performance


def _validated_release(root: Path) -> ReleaseEvidence:
    try:
        projection = supervisor._authenticated_dataset_release(root)  # noqa: SLF001
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AdaptiveEscalationRuntimeError("dataset_release:AUTHENTICATION_FAILED") from exc
    receipt = _read_json(
        root / "candidate_outcome_dataset_build_receipt_v3.json",
        "dataset_release.build_receipt",
    )
    archive = receipt.get("candidate_archive_verification")
    if type(archive) is not dict:
        raise AdaptiveEscalationRuntimeError("dataset_release:ARCHIVE_VERIFICATION_REQUIRED")
    matured = archive.get("matured_revision_count")
    decisions = archive.get("decision_revision_count")
    terminal = archive.get("terminal_chain_sha256")
    if type(matured) is not int or matured < 0 or type(decisions) is not int or decisions < matured:
        raise AdaptiveEscalationRuntimeError("dataset_release:SOURCE_COUNTS_INVALID")
    if type(terminal) is not str or len(terminal) != 64:
        raise AdaptiveEscalationRuntimeError("dataset_release:TERMINAL_CHAIN_INVALID")
    if projection.get("source_terminal_chain_sha256") != terminal:
        raise AdaptiveEscalationRuntimeError("dataset_release:TERMINAL_CHAIN_MISMATCH")
    return ReleaseEvidence(
        root=root.absolute(),
        projection=projection,
        source_matured_revision_count=matured,
        source_decision_revision_count=decisions,
        source_terminal_chain_sha256=terminal,
    )


def select_latest_release(parent: Path) -> ReleaseEvidence | None:
    parent = _safe_directory(parent, "release_parent", create=True)
    releases: list[ReleaseEvidence] = []
    for path in sorted(parent.glob("release_*")):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            releases.append(_validated_release(path))
        except AdaptiveEscalationRuntimeError:
            continue
    if not releases:
        return None
    return max(
        releases,
        key=lambda row: (
            row.source_matured_revision_count,
            row.source_decision_revision_count,
            row.projection["dataset_sha256"],
        ),
    )


def build_signed_release(
    parent: Path,
    *,
    feature_archive_root: Path,
    timeout_seconds: int,
) -> ReleaseEvidence:
    parent = _safe_directory(parent, "release_parent", create=True)
    temporary = Path(tempfile.mkdtemp(prefix=".release_build_", dir=parent))
    os.chmod(temporary, 0o700)
    command = [
        sys.executable,
        "-P",
        "-B",
        "-m",
        "v2.backend.app.cli.v2_candidate_outcome_dataset_builder",
        "--feature-archive-root",
        str(feature_archive_root),
        "--output-root",
        str(temporary),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - exact argv, no shell
            command,
            cwd=Path(__file__).resolve().parents[4],
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            shell=False,
        )
        if result.returncode != 0:
            raise AdaptiveEscalationRuntimeError(
                f"dataset_release:BUILDER_EXIT_{result.returncode}"
            )
        release = _validated_release(temporary)
        generated = _read_json(
            temporary / "candidate_outcome_dataset_build_receipt_v3.json",
            "dataset_release.build_receipt",
        ).get("generated_at")
        timestamp = _parse_utc(generated, "dataset_release.generated_at").strftime(
            "%Y%m%dT%H%M%SZ"
        )
        final = parent / (
            f"release_{release.projection['dataset_sha256'][:8]}_{timestamp}"
        )
        if final.exists():
            existing = _validated_release(final)
            if existing.projection != release.projection:
                raise AdaptiveEscalationRuntimeError("dataset_release:IMMUTABLE_COLLISION")
            shutil.rmtree(temporary)
            return existing
        os.rename(temporary, final)
        temporary = final
        return _validated_release(final)
    finally:
        if temporary.exists() and temporary.name.startswith(".release_build_"):
            shutil.rmtree(temporary)


def resolve_release(
    parent: Path,
    *,
    current_matured_revision_count: int,
    feature_archive_root: Path,
    min_new_matured_outcomes: int,
    build_timeout_seconds: int,
) -> tuple[ReleaseEvidence, bool]:
    latest = select_latest_release(parent)
    if latest is not None:
        delta = current_matured_revision_count - latest.source_matured_revision_count
        if delta < 0:
            raise AdaptiveEscalationRuntimeError("candidate_outcomes:SOURCE_REGRESSION")
        if delta < min_new_matured_outcomes:
            return latest, False
    return (
        build_signed_release(
            parent,
            feature_archive_root=feature_archive_root,
            timeout_seconds=build_timeout_seconds,
        ),
        True,
    )


def discover_completed_steps(
    release: ReleaseEvidence,
    *,
    dispatch_root: Path,
) -> frozenset[str]:
    root = _safe_directory(dispatch_root, "dispatch_root", create=True)
    completed: set[str] = set()
    for run_root in sorted(root.glob("adaptive_dispatch_*")):
        if run_root.is_symlink() or not run_root.is_dir():
            continue
        terminal_path = run_root / "dispatch_terminal_v1.json"
        if not terminal_path.is_file() or terminal_path.is_symlink():
            continue
        try:
            receipt = _read_json(terminal_path, "dispatch_terminal")
            step = receipt.get("selected_step")
            if type(step) is not str or step not in supervisor.WORKER_COMMANDS:
                continue
            worker = supervisor.WORKER_COMMANDS[step]
            if (
                receipt.get("schema_version") != supervisor.DISPATCH_SCHEMA_VERSION
                or receipt.get("status") != "COMPLETED"
                or receipt.get("returncode") != 0
                or receipt.get("timed_out") is not False
                or receipt.get("launch_baseline_success") is not True
                or receipt.get("dataset_release") != release.projection
                or receipt.get("input_manifest_sha")
                != release.projection["dataset_sha256"]
                or receipt.get("worker_scope") != worker["scope"]
                or receipt.get("worker_entrypoint") != worker["entrypoint"]
                or receipt.get("worker_argv_template") != worker["argv"]
                or receipt.get("worker_entrypoint_file_sha256")
                != supervisor._worker_code_sha256(worker)  # noqa: SLF001
            ):
                continue
            _safe_paper_authority(receipt, "dispatch_terminal")
            material = {
                "schema_version": supervisor.DISPATCH_SCHEMA_VERSION,
                "selected_step": step,
                "trigger": receipt.get("trigger"),
                "input_manifest_sha": receipt.get("input_manifest_sha"),
                "worker_scope": worker["scope"],
                "worker_entrypoint": worker["entrypoint"],
                "worker_entrypoint_file_sha256": receipt[
                    "worker_entrypoint_file_sha256"
                ],
                "worker_argv_template": worker["argv"],
                "dataset_release": release.projection,
            }
            dispatch_id = "adaptive_dispatch_" + _sha256_bytes(
                _canonical_bytes(material)
            )[:32]
            if receipt.get("dispatch_id") != dispatch_id or run_root.name != dispatch_id:
                continue
            expected_argv = supervisor._resolved_worker_argv(  # noqa: SLF001
                worker,
                dataset_release_root=release.root,
                dispatch_run_root=run_root,
            )
            if receipt.get("argv") != expected_argv:
                continue
            for stream in ("stdout", "stderr"):
                data = _read_regular_bytes(run_root / f"{stream}.bin", stream)
                if receipt.get(f"{stream}_sha256") != _sha256_bytes(data):
                    raise AdaptiveEscalationRuntimeError(
                        f"dispatch_terminal:{stream.upper()}_HASH_MISMATCH"
                    )
            completed.add(step)
        except (AdaptiveEscalationRuntimeError, KeyError, TypeError, ValueError):
            continue
    if "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES" in completed:
        completed.add("RECALIBRATE_CURRENT_MODELS")
    return frozenset(completed)


def _load_prior_state(client: Any, state_path: Path) -> dict[str, Any]:
    try:
        prior = supervisor._get_json(client, supervisor.STATUS_REDIS_KEY)  # noqa: SLF001
    except Exception:
        prior = None
    if isinstance(prior, dict) and _valid_prior_state(prior):
        return prior
    if state_path.exists() and not state_path.is_symlink():
        durable = _read_json(state_path, "runtime_state")
        if _valid_prior_state(durable):
            return durable
    return {}


def _valid_prior_state(value: Mapping[str, Any]) -> bool:
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("paper_only") is not True
        or value.get("live_gate") != "blocked_human_only"
        or value.get("routes_to_live") is not False
        or value.get("places_real_order") is not False
        or value.get("exchange_action_taken") is not False
    ):
        return False
    claimed = value.get("payload_sha256")
    if type(claimed) is not str or len(claimed) != 64:
        return False
    unsigned = dict(value)
    unsigned.pop("payload_sha256", None)
    return claimed == _sha256_bytes(_canonical_bytes(unsigned))


def _persist_state(client: Any, state_path: Path, payload: Mapping[str, Any]) -> None:
    supervisor._write_atomic_private_json(state_path, payload)  # noqa: SLF001
    client.set(supervisor.STATUS_REDIS_KEY, json.dumps(payload, sort_keys=True))


def run_once(
    client: Any,
    *,
    release_parent: Path = DEFAULT_RELEASE_PARENT,
    state_path: Path = DEFAULT_RUNTIME_STATE_PATH,
    feature_archive_root: Path = DEFAULT_FEATURE_ARCHIVE_ROOT,
    dispatch_root: Path = supervisor.DEFAULT_DISPATCH_ROOT,
    dispatch_state_path: Path = supervisor.DEFAULT_DISPATCH_STATE_PATH,
    dispatch_lock_path: Path = supervisor.DEFAULT_DISPATCH_LOCK_PATH,
    execute_worker: bool = False,
    now: datetime | None = None,
    max_status_age_seconds: float = DEFAULT_MAX_STATUS_AGE_SECONDS,
    min_new_matured_outcomes: int = DEFAULT_MIN_NEW_MATURED_OUTCOMES,
    min_new_effective_n: float = DEFAULT_MIN_NEW_EFFECTIVE_N,
    build_timeout_seconds: int = 900,
    dispatch_timeout_seconds: int = supervisor.DISPATCH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    authority, outcomes, performance = authenticate_runtime_inputs(
        client,
        now=now,
        max_age_seconds=max_status_age_seconds,
    )
    archive = outcomes["archive"]
    current_matured = int(archive["matured_revision_count"])
    release, rebuilt = resolve_release(
        release_parent,
        current_matured_revision_count=current_matured,
        feature_archive_root=feature_archive_root,
        min_new_matured_outcomes=min_new_matured_outcomes,
        build_timeout_seconds=build_timeout_seconds,
    )
    dataset_path = Path(release.projection["paths"]["dataset"])
    base_inputs = supervisor.build_inputs_from_redis(
        client,
        dataset_path=dataset_path,
        min_new_matured_outcomes=min_new_matured_outcomes,
        min_new_effective_n=min_new_effective_n,
    )
    prior = _load_prior_state(client, state_path)
    completed = set(discover_completed_steps(release, dispatch_root=dispatch_root))
    if prior.get("input_manifest_sha") == release.projection["dataset_sha256"]:
        prior_steps = prior.get("completed_steps_for_input_manifest")
        if isinstance(prior_steps, list) and all(
            type(step) is str and step in LADDER for step in prior_steps
        ):
            completed.update(prior_steps)

    effective_n = supervisor.load_gen5_corpus_effective_n(dataset_path)[0]
    prior_baseline = prior.get("launch_baseline")
    if (
        prior.get("input_manifest_sha") == release.projection["dataset_sha256"]
        and isinstance(prior_baseline, dict)
    ):
        baseline_matured = prior_baseline.get("matured_outcome_count")
        baseline_effective_n = prior_baseline.get("effective_n")
    else:
        baseline_matured = release.source_matured_revision_count
        baseline_effective_n = effective_n

    inputs = replace(
        base_inputs,
        matured_outcome_count=current_matured,
        effective_n=effective_n,
        baseline_matured_outcome_count=int(baseline_matured),
        baseline_effective_n=float(baseline_effective_n),
        min_new_matured_outcomes=min_new_matured_outcomes,
        min_new_effective_n=min_new_effective_n,
        after_cost_edge_bps=float(performance["notional_weighted_expectancy_bps"]),
        exhausted_steps=frozenset(completed),
        input_manifest_sha=str(release.projection["dataset_sha256"]),
    )
    plan = supervisor.plan_escalation(inputs)
    dispatch_result: dict[str, Any] | None = None
    if execute_worker and plan.action == supervisor.ACTION_LAUNCH:
        dispatch_result = supervisor.dispatch_worker(
            plan,
            dataset_release_root=release.root,
            dispatch_root=dispatch_root,
            state_path=dispatch_state_path,
            lock_path=dispatch_lock_path,
            timeout_seconds=dispatch_timeout_seconds,
        )
        if dispatch_result.get("launch_baseline_success") is True:
            completed.add(str(plan.selected_step))

    prior_history = prior.get("directional_history")
    history = [int(v) for v in prior_history] if isinstance(prior_history, list) else []
    history = (history + [inputs.directional_authorized_count])[-20:]
    baseline = {
        "matured_outcome_count": release.source_matured_revision_count,
        "effective_n": effective_n,
        "dataset_sha256": release.projection["dataset_sha256"],
        "source_terminal_chain_sha256": release.source_terminal_chain_sha256,
    }
    payload = plan.to_dict()
    payload.update(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": now.isoformat().replace("+00:00", "Z"),
            "worker_execution_enabled": execute_worker,
            "dispatch_result": dispatch_result,
            "completed_steps_for_input_manifest": [
                step for step in LADDER if step in completed
            ],
            "directional_history": history,
            "launch_baseline": baseline,
            "dataset_release_rebuilt": rebuilt,
            "dataset_release": dict(release.projection),
            "source_matured_revision_count": release.source_matured_revision_count,
            "current_matured_revision_count": current_matured,
            "runtime_input_evidence": {
                "policy_authority_sha256": _sha256_bytes(
                    _canonical_bytes(authority)
                ),
                "candidate_outcomes_sha256": _sha256_bytes(
                    _canonical_bytes(outcomes)
                ),
                "performance_status_key": PERFORMANCE_STATUS_KEY,
                "performance_status_sha256": performance["source_payload_sha256"],
                "after_cost_edge_bps": performance[
                    "notional_weighted_expectancy_bps"
                ],
                "closed_outcome_count": performance["closed_outcome_count"],
            },
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
    )
    unsigned = dict(payload)
    payload["payload_sha256"] = _sha256_bytes(_canonical_bytes(unsigned))
    _persist_state(client, state_path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument("--release-parent", type=Path, default=DEFAULT_RELEASE_PARENT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_RUNTIME_STATE_PATH)
    parser.add_argument("--runtime-lock", type=Path, default=DEFAULT_RUNTIME_LOCK_PATH)
    parser.add_argument(
        "--feature-archive-root", type=Path, default=DEFAULT_FEATURE_ARCHIVE_ROOT
    )
    parser.add_argument("--dispatch-root", type=Path, default=supervisor.DEFAULT_DISPATCH_ROOT)
    parser.add_argument(
        "--dispatch-state", type=Path, default=supervisor.DEFAULT_DISPATCH_STATE_PATH
    )
    parser.add_argument(
        "--dispatch-lock", type=Path, default=supervisor.DEFAULT_DISPATCH_LOCK_PATH
    )
    parser.add_argument("--execute-worker", action="store_true")
    parser.add_argument(
        "--max-status-age-seconds",
        type=float,
        default=DEFAULT_MAX_STATUS_AGE_SECONDS,
    )
    parser.add_argument(
        "--min-new-matured-outcomes",
        type=int,
        default=DEFAULT_MIN_NEW_MATURED_OUTCOMES,
    )
    parser.add_argument(
        "--min-new-effective-n", type=float, default=DEFAULT_MIN_NEW_EFFECTIVE_N
    )
    parser.add_argument("--build-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--dispatch-timeout-seconds",
        type=int,
        default=supervisor.DISPATCH_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = supervisor._build_redis_client(args.redis_url)  # noqa: SLF001
    with _single_run_lock(args.runtime_lock):
        payload = run_once(
            client,
            release_parent=args.release_parent,
            state_path=args.state_path,
            feature_archive_root=args.feature_archive_root,
            dispatch_root=args.dispatch_root,
            dispatch_state_path=args.dispatch_state,
            dispatch_lock_path=args.dispatch_lock,
            execute_worker=args.execute_worker,
            max_status_age_seconds=args.max_status_age_seconds,
            min_new_matured_outcomes=args.min_new_matured_outcomes,
            min_new_effective_n=args.min_new_effective_n,
            build_timeout_seconds=args.build_timeout_seconds,
            dispatch_timeout_seconds=args.dispatch_timeout_seconds,
        )
    print(json.dumps(payload, sort_keys=True, allow_nan=False))
    return 0 if not payload.get("validation_errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
