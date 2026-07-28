"""Automatic paper-only adaptation escalation over authenticated runtime evidence.

This coordinator closes the operational gap between the pure escalation planner
and the signed candidate-outcome dataset/training workers.  It authenticates the
current policy, outcome, and economic-failure status, refreshes the immutable
dataset release only after the predeclared information-gain threshold is met,
reconstructs completed ladder steps from content-addressed dispatch receipts,
and executes a bounded sequence of paper-only workers against one frozen signed
release per invocation.  This prevents a continuously growing corpus from
starving every rung behind incremental training.

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
from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import (
    LADDER,
    TRIGGER_CONDITIONS,
)

SCHEMA_VERSION = "adaptive_escalation_runtime_v1"
NOVELTY_MANIFEST_SCHEMA_VERSION = "adaptive_evidence_novelty_trigger_v1"
ACTION_AWAIT_NOVEL_EVIDENCE = "AWAITING_NOVEL_AUTHENTICATED_EVIDENCE"
PERFORMANCE_STATUS_KEY = "v2:paper:performance_governor_status"
ACTIVE_REGISTRY_KEY = "v2:model_registry:paper:active"
CANDIDATE_REGISTRY_KEY = "v2:model_registry:paper:candidate"
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
DEFAULT_MIN_CHRONOLOGICAL_EXPANSION_SECONDS = 86_400.0
DEFAULT_MIN_NEW_SCOPE_ROWS = 25
DEFAULT_MAX_DISPATCHES_PER_RUN = 4
LEGACY_FAILURE_RECEIPT_MIGRATION_CUTOFF = datetime(
    2026,
    7,
    28,
    16,
    15,
    tzinfo=UTC,
)

INCREMENTAL_STEP = "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES"
RECALIBRATION_STEP = "RECALIBRATE_CURRENT_MODELS"
PRE_PROMOTION_LADDER = tuple(
    step for step in LADDER if step != "PROMOTE_SUPERIOR_CHALLENGER"
)
BASELINE_ADVANCING_STEPS = frozenset({RECALIBRATION_STEP, INCREMENTAL_STEP})
RELEASE_REUSABLE_INFORMATION_STEPS = frozenset(
    supervisor.INFO_DEPENDENT_STEPS - {INCREMENTAL_STEP}
)


class AdaptiveEscalationRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseEvidence:
    root: Path
    projection: Mapping[str, Any]
    source_matured_revision_count: int
    source_decision_revision_count: int
    source_terminal_chain_sha256: str


@dataclass(frozen=True)
class CompletedDispatch:
    step: str
    release: ReleaseEvidence
    receipt: Mapping[str, Any]


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
        or (
            "live_gate" in payload
            and payload.get("live_gate") != "blocked_human_only"
        )
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
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = _get_required_json(client, supervisor.POLICY_AUTHORITY_STATUS_KEY)
    outcomes = _get_required_json(client, supervisor.CANDIDATE_OUTCOMES_STATUS_KEY)
    performance = _get_required_json(client, PERFORMANCE_STATUS_KEY)
    registry = _get_required_json(client, ACTIVE_REGISTRY_KEY)

    if authority.get("schema_version") != "adaptive_paper_policy_runtime_status_v2":
        raise AdaptiveEscalationRuntimeError("policy_authority:SCHEMA_INVALID")
    if authority.get("status") != "PASS_AUTHORITATIVE_PAPER_POLICY":
        raise AdaptiveEscalationRuntimeError("policy_authority:STATUS_INVALID")
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
    if outcomes.get("status") != "PASS":
        raise AdaptiveEscalationRuntimeError("candidate_outcomes:STATUS_INVALID")
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
    _safe_paper_authority(maturation, "candidate_outcomes.maturation")
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
        or maturation.get("status") != "PASS"
        or outcomes.get("candidate_outcome_maturer_runtime_integrated") is not True
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
    state = performance.get("state")
    status = performance.get("status")
    if (
        status != state
        or status not in {"HALTED_PERFORMANCE", "ACTIVE", "ACTIVE_CALIBRATION"}
        or performance.get("enabled") is not True
        or performance.get("allow_feedback_recording") is not True
        or (
            status == "HALTED_PERFORMANCE"
            and performance.get("new_entries_allowed") is not False
        )
        or (
            status in {"ACTIVE", "ACTIVE_CALIBRATION"}
            and performance.get("new_entries_allowed") is not True
        )
    ):
        raise AdaptiveEscalationRuntimeError(
            "performance_status:STATE_INCOHERENT"
        )
    if registry.get("schema_version") != "model_registry_active_v2":
        raise AdaptiveEscalationRuntimeError("active_registry:SCHEMA_INVALID")
    if (
        registry.get("lane") != "paper"
        or registry.get("paper_only") is not True
        or registry.get("live_eligible") is not False
        or registry.get("registry_generation")
        != authority.get("checkpoint_generation")
        or registry.get("checkpoint_id") != authority.get("checkpoint_id")
    ):
        raise AdaptiveEscalationRuntimeError("active_registry:AUTHORITY_MISMATCH")
    activated_at = _parse_utc(registry.get("activated_at"), "active_registry.activated_at")
    if activated_at > now:
        raise AdaptiveEscalationRuntimeError("active_registry:FUTURE_ACTIVATION")
    bundle_sha = registry.get("checkpoint_bundle_sha256")
    if type(bundle_sha) is not str or len(bundle_sha) != 64:
        raise AdaptiveEscalationRuntimeError("active_registry:BUNDLE_SHA_INVALID")
    performance = dict(performance)
    performance["source_payload_sha256"] = _sha256_bytes(_canonical_bytes(performance))
    registry = dict(registry)
    registry["source_payload_sha256"] = _sha256_bytes(_canonical_bytes(registry))
    return dict(authority), dict(outcomes), performance, registry


def _validated_release(root: Path) -> ReleaseEvidence:
    try:
        projection, source = supervisor._authenticated_dataset_release_evidence(  # noqa: SLF001
            root
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AdaptiveEscalationRuntimeError("dataset_release:AUTHENTICATION_FAILED") from exc
    matured = source.get("matured_revision_count")
    decisions = source.get("decision_revision_count")
    terminal = source.get("terminal_chain_sha256")
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
) -> tuple[ReleaseEvidence, bool, ReleaseEvidence | None]:
    latest = select_latest_release(parent)
    if latest is not None:
        delta = current_matured_revision_count - latest.source_matured_revision_count
        if delta < 0:
            raise AdaptiveEscalationRuntimeError("candidate_outcomes:SOURCE_REGRESSION")
        if delta < min_new_matured_outcomes:
            return latest, False, latest
    built = build_signed_release(
        parent,
        feature_archive_root=feature_archive_root,
        timeout_seconds=build_timeout_seconds,
    )
    if built.source_matured_revision_count < current_matured_revision_count:
        raise AdaptiveEscalationRuntimeError(
            "dataset_release:REBUILT_SOURCE_WATERMARK_BEHIND_TRIGGER"
        )
    return built, True, latest


def discover_completed_dispatches(
    release: ReleaseEvidence,
    *,
    dispatch_root: Path,
) -> tuple[CompletedDispatch, ...]:
    root = _safe_directory(dispatch_root, "dispatch_root", create=True)
    completed: list[CompletedDispatch] = []
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
            trigger = receipt.get("trigger")
            if (
                type(trigger) is not list
                or not trigger
                or any(
                    type(item) is not str
                    or item not in TRIGGER_CONDITIONS
                    for item in trigger
                )
                or receipt.get("dataset_release") != release.projection
                or receipt.get("input_manifest_sha")
                != release.projection["dataset_sha256"]
            ):
                continue
            material = {
                "schema_version": supervisor.DISPATCH_SCHEMA_VERSION,
                "selected_step": step,
                "trigger": trigger,
                "input_manifest_sha": release.projection["dataset_sha256"],
                "worker_scope": worker["scope"],
                "worker_entrypoint": worker["entrypoint"],
                "worker_entrypoint_file_sha256": supervisor._worker_code_sha256(  # noqa: SLF001
                    worker
                ),
                "worker_argv_template": worker["argv"],
                "dataset_release": release.projection,
            }
            receipt_failure_cycle_id = receipt.get("failure_cycle_id")
            if receipt_failure_cycle_id is not None:
                if (
                    type(receipt_failure_cycle_id) is not str
                    or not receipt_failure_cycle_id.startswith(
                        "adaptive_failure_cycle_"
                    )
                    or len(receipt_failure_cycle_id)
                    != len("adaptive_failure_cycle_") + 32
                ):
                    continue
                material["failure_cycle_id"] = receipt_failure_cycle_id
            dispatch_id = "adaptive_dispatch_" + _sha256_bytes(
                _canonical_bytes(material)
            )[:32]
            if receipt.get("dispatch_id") != dispatch_id or run_root.name != dispatch_id:
                continue
            material["argv"] = supervisor._resolved_worker_argv(  # noqa: SLF001
                worker,
                dataset_release_root=release.root,
                dispatch_run_root=run_root,
            )
            material["dispatch_id"] = dispatch_id
            replay = supervisor._replay_terminal_receipt(  # noqa: SLF001
                terminal_path,
                dispatch_material=material,
            )
            if replay is not None:
                completed.append(CompletedDispatch(step, release, replay))
        except (AdaptiveEscalationRuntimeError, KeyError, TypeError, ValueError):
            continue
    return tuple(completed)


def discover_completed_steps(
    release: ReleaseEvidence,
    *,
    dispatch_root: Path,
) -> frozenset[str]:
    completed = {
        evidence.step
        for evidence in discover_completed_dispatches(
            release,
            dispatch_root=dispatch_root,
        )
    }
    if INCREMENTAL_STEP in completed:
        completed.add(RECALIBRATION_STEP)
    return frozenset(completed)


def discover_historical_completed_dispatches(
    release_parent: Path,
    *,
    dispatch_root: Path,
) -> tuple[CompletedDispatch, ...]:
    """Authenticate successful negative-edge work across immutable releases.

    A receipt is accepted only by ``discover_completed_steps`` against the exact
    signed release projection embedded in that receipt.  Iterating independently
    authenticated releases allows non-information rungs to survive a corpus
    refresh without permitting a receipt forged for one release to complete work
    for another.
    """

    parent = _safe_directory(release_parent, "release_parent", create=True)
    completed: list[CompletedDispatch] = []
    for path in sorted(parent.glob("release_*")):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            release = _validated_release(path)
            release_dispatches = discover_completed_dispatches(
                release,
                dispatch_root=dispatch_root,
            )
        except AdaptiveEscalationRuntimeError:
            continue
        completed.extend(release_dispatches)
    return tuple(completed)


def discover_historical_completed_steps(
    release_parent: Path,
    *,
    dispatch_root: Path,
) -> frozenset[str]:
    completed = {
        evidence.step
        for evidence in discover_historical_completed_dispatches(
            release_parent,
            dispatch_root=dispatch_root,
        )
    }
    if INCREMENTAL_STEP in completed:
        completed.add(RECALIBRATION_STEP)
    return frozenset(completed)


def _authenticated_training_baseline(
    dispatches: tuple[CompletedDispatch, ...],
) -> dict[str, Any] | None:
    latest = _latest_authenticated_training_dispatch(dispatches)
    if latest is None:
        return None
    effective_n = supervisor.load_gen5_corpus_effective_n(
        Path(latest.release.projection["paths"]["dataset"])
    )[0]
    return {
        "matured_outcome_count": latest.release.source_matured_revision_count,
        "effective_n": effective_n,
        "dataset_sha256": latest.release.projection["dataset_sha256"],
        "source_terminal_chain_sha256": (
            latest.release.source_terminal_chain_sha256
        ),
        "launched_step": latest.step,
        "dispatch_id": latest.receipt.get("dispatch_id"),
        "recorded_utc": latest.receipt.get("completed_utc"),
        "derived_from_authenticated_terminal_receipt": True,
    }


def _latest_authenticated_training_dispatch(
    dispatches: tuple[CompletedDispatch, ...],
) -> CompletedDispatch | None:
    eligible = [
        evidence
        for evidence in dispatches
        if evidence.step in BASELINE_ADVANCING_STEPS
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            row.release.source_matured_revision_count,
            row.release.source_decision_revision_count,
            row.release.projection["dataset_sha256"],
        ),
    )


def _redis_value_present(client: Any, key: str) -> bool:
    try:
        return bool(client.get(key))
    except Exception as exc:
        raise AdaptiveEscalationRuntimeError(f"redis:{key}:READ_FAILED") from exc


def _release_manifest_summary(release: ReleaseEvidence) -> dict[str, Any]:
    manifest = _read_json(
        Path(release.projection["paths"]["manifest"]),
        "novelty.manifest",
    )
    if (
        manifest.get("schema_version")
        != "adaptive_serving_compatible_dataset_manifest_v2"
        or manifest.get("manifest_sha256")
        != release.projection.get("manifest_sha256")
    ):
        raise AdaptiveEscalationRuntimeError("novelty.manifest:IDENTITY_MISMATCH")
    earliest = _parse_utc(
        manifest.get("earliest_decision_time"),
        "novelty.manifest.earliest_decision_time",
    )
    latest = _parse_utc(
        manifest.get("latest_decision_time"),
        "novelty.manifest.latest_decision_time",
    )
    if earliest > latest:
        raise AdaptiveEscalationRuntimeError("novelty.manifest:TIME_RANGE_INVALID")
    total_rows = sum(
        int(release.projection[field])
        for field in ("training_rows", "validation_rows", "holdout_rows")
    )

    def counts(field: str) -> dict[str, int]:
        value = manifest.get(field)
        if (
            type(value) is not dict
            or not value
            or any(
                type(key) is not str
                or not key
                or type(count) is not int
                or count < 0
                for key, count in value.items()
            )
            or sum(value.values()) != total_rows
        ):
            raise AdaptiveEscalationRuntimeError(
                f"novelty.manifest.{field}:COUNTS_INVALID"
            )
        return dict(sorted(value.items()))

    watermark = manifest.get("source_high_watermark")
    if (
        type(watermark) is not dict
        or watermark.get("candidate_archive_matured_revision_count")
        != release.source_matured_revision_count
        or watermark.get("candidate_archive_decision_revision_count")
        != release.source_decision_revision_count
        or watermark.get("candidate_archive_terminal_chain_sha256")
        != release.source_terminal_chain_sha256
    ):
        raise AdaptiveEscalationRuntimeError(
            "novelty.manifest:SOURCE_HIGH_WATERMARK_MISMATCH"
        )
    return {
        "dataset_sha256": release.projection["dataset_sha256"],
        "manifest_sha256": release.projection["manifest_sha256"],
        "source_terminal_chain_sha256": release.source_terminal_chain_sha256,
        "source_matured_revision_count": release.source_matured_revision_count,
        "source_decision_revision_count": release.source_decision_revision_count,
        "total_rows": total_rows,
        "earliest_decision_time": earliest.isoformat().replace("+00:00", "Z"),
        "latest_decision_time": latest.isoformat().replace("+00:00", "Z"),
        "symbol_counts": counts("symbol_counts"),
        "timeframe_counts": counts("timeframe_counts"),
        "target_action_counts": counts("target_action_counts"),
    }


def build_evidence_novelty_manifest(
    *,
    baseline_dispatch: CompletedDispatch,
    candidate_release: ReleaseEvidence,
    baseline_effective_n: float,
    candidate_effective_n: float,
    failure_cycle: Mapping[str, Any],
    completed_steps: set[str],
    current_matured_revision_count: int,
    min_new_matured_outcomes: int,
    min_new_effective_n: float,
    min_chronological_expansion_seconds: float,
    min_new_scope_rows: int,
    generated_utc: str,
) -> dict[str, Any]:
    baseline = _release_manifest_summary(baseline_dispatch.release)
    candidate = _release_manifest_summary(candidate_release)
    baseline_earliest = _parse_utc(
        baseline["earliest_decision_time"], "novelty.baseline.earliest_decision_time"
    )
    baseline_latest = _parse_utc(
        baseline["latest_decision_time"], "novelty.baseline.latest_decision_time"
    )
    candidate_earliest = _parse_utc(
        candidate["earliest_decision_time"], "novelty.candidate.earliest_decision_time"
    )
    candidate_latest = _parse_utc(
        candidate["latest_decision_time"], "novelty.candidate.latest_decision_time"
    )
    chronological_expansion = max(
        0.0, (baseline_earliest - candidate_earliest).total_seconds()
    ) + max(0.0, (candidate_latest - baseline_latest).total_seconds())
    effective_n_delta = round(candidate_effective_n - baseline_effective_n, 10)

    def newly_covered(field: str) -> list[dict[str, Any]]:
        baseline_counts = baseline[field]
        candidate_counts = candidate[field]
        return [
            {"name": name, "authenticated_rows": count}
            for name, count in candidate_counts.items()
            if name not in baseline_counts and count >= min_new_scope_rows
        ]

    new_symbols = newly_covered("symbol_counts")
    new_timeframes = newly_covered("timeframe_counts")
    current_cycle_id = failure_cycle.get("failure_cycle_id")
    baseline_cycle_id = baseline_dispatch.receipt.get("failure_cycle_id")
    new_failure_cycle = (
        type(baseline_cycle_id) is str and baseline_cycle_id != current_cycle_id
    )
    unevaluated_families = [
        step for step in PRE_PROMOTION_LADDER if step not in completed_steps
    ]
    predicates = {
        "effective_independent_sample_size": {
            "evidence_available": True,
            "baseline": baseline_effective_n,
            "candidate": candidate_effective_n,
            "actual_increase": effective_n_delta,
            "required_increase": min_new_effective_n,
            "passed": effective_n_delta >= min_new_effective_n,
        },
        "chronological_coverage": {
            "evidence_available": True,
            "actual_expansion_seconds": chronological_expansion,
            "required_expansion_seconds": min_chronological_expansion_seconds,
            "passed": (
                chronological_expansion >= min_chronological_expansion_seconds
            ),
        },
        "volatility_trend_range_regime": {
            "evidence_available": False,
            "passed": False,
            "reason": "SIGNED_RELEASE_DOES_NOT_DECLARE_REGIME_MEMBERSHIP",
        },
        "symbol_timeframe_coverage": {
            "evidence_available": True,
            "minimum_rows_per_new_scope": min_new_scope_rows,
            "new_symbols": new_symbols,
            "new_timeframes": new_timeframes,
            "passed": bool(new_symbols or new_timeframes),
        },
        "underrepresented_policy_actions": {
            "evidence_available": False,
            "passed": False,
            "reason": "SIGNED_RELEASE_TARGET_ACTION_IS_NOT_POLICY_ACTION_AUTHORITY",
        },
        "calibration_drift": {
            "evidence_available": False,
            "passed": False,
            "reason": "SIGNED_RELEASE_DOES_NOT_DECLARE_CALIBRATION_DRIFT",
        },
        "counterfactual_opportunity_cost": {
            "evidence_available": False,
            "passed": False,
            "reason": "SIGNED_RELEASE_DOES_NOT_DECLARE_AGGREGATED_OPPORTUNITY_COST_DRIFT",
        },
        "checkpoint_or_cohort_generation": {
            "evidence_available": type(baseline_cycle_id) is str,
            "baseline_failure_cycle": baseline_cycle_id,
            "active_failure_cycle": current_cycle_id,
            "passed": new_failure_cycle,
        },
        "unevaluated_challenger_family": {
            "evidence_available": True,
            "unevaluated_families": unevaluated_families,
            "passed": bool(unevaluated_families),
        },
        "raw_archive_revision_growth": {
            "evidence_available": True,
            "baseline": baseline["source_matured_revision_count"],
            "current": current_matured_revision_count,
            "actual_increase": (
                current_matured_revision_count
                - baseline["source_matured_revision_count"]
            ),
            "legacy_count_threshold": min_new_matured_outcomes,
            "threshold_crossed": (
                current_matured_revision_count
                - baseline["source_matured_revision_count"]
                >= min_new_matured_outcomes
            ),
            "authorizes_training": False,
        },
    }
    authorizing_predicates = [
        name
        for name, evidence in predicates.items()
        if name != "raw_archive_revision_growth" and evidence.get("passed") is True
    ]
    material = {
        "schema_version": NOVELTY_MANIFEST_SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "active_failure_cycle": current_cycle_id,
        "checkpoint_generation": failure_cycle["checkpoint_binding"][
            "checkpoint_generation"
        ],
        "checkpoint_id": failure_cycle["checkpoint_binding"]["checkpoint_id"],
        "completed_pre_promotion_rungs": "all_9",
        "baseline": baseline,
        "candidate": candidate,
        "predicates": predicates,
        "authorizing_predicates": authorizing_predicates,
        "material_novelty_detected": bool(authorizing_predicates),
        "raw_revision_growth_alone_authorizes_training": False,
        "authenticated_sources": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    material["manifest_sha256"] = _sha256_bytes(_canonical_bytes(material))
    return material


def _failure_cycle(
    authority: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    edge_bps: float,
    performance_sha256: str,
) -> dict[str, Any]:
    material = {
        "checkpoint_generation": registry["registry_generation"],
        "checkpoint_id": registry["checkpoint_id"],
        "checkpoint_bundle_sha256": registry["checkpoint_bundle_sha256"],
        "activated_at": registry["activated_at"],
    }
    if (
        authority.get("checkpoint_generation") != material["checkpoint_generation"]
        or authority.get("checkpoint_id") != material["checkpoint_id"]
    ):
        raise AdaptiveEscalationRuntimeError("failure_cycle:AUTHORITY_MISMATCH")
    cycle_id = "adaptive_failure_cycle_" + _sha256_bytes(
        _canonical_bytes(material)
    )[:32]
    if edge_bps >= 0.0:
        return {
            "active": False,
            "classification": "AFTER_COST_EDGE_NONNEGATIVE",
            "failure_cycle_id": cycle_id,
            "started_utc": registry["activated_at"],
            "checkpoint_binding": material,
            "performance_status_sha256": performance_sha256,
        }
    return {
            "active": True,
            "classification": "UNRESOLVED_NEGATIVE_AFTER_COST_EDGE",
            "failure_cycle_id": cycle_id,
            "started_utc": registry["activated_at"],
            "last_negative_edge_bps": edge_bps,
            "checkpoint_binding": material,
            "performance_status_sha256": performance_sha256,
        }


def _dispatch_matches_failure_cycle(
    evidence: CompletedDispatch,
    failure_cycle: Mapping[str, Any],
) -> bool:
    receipt = evidence.receipt
    receipt_cycle = receipt.get("failure_cycle_id")
    if receipt_cycle is not None:
        return receipt_cycle == failure_cycle.get("failure_cycle_id")
    trigger = receipt.get("trigger")
    if not isinstance(trigger, list) or "negative_after_cost_edge" not in trigger:
        return False
    try:
        completed = _parse_utc(
            receipt.get("completed_utc"),
            "dispatch_terminal.completed_utc",
        )
        started = _parse_utc(
            failure_cycle.get("started_utc"),
            "failure_cycle.started_utc",
        )
    except AdaptiveEscalationRuntimeError:
        return False
    return started <= completed <= LEGACY_FAILURE_RECEIPT_MIGRATION_CUTOFF


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


def _validate_runtime_configuration(
    *,
    max_status_age_seconds: float,
    min_new_matured_outcomes: int,
    min_new_effective_n: float,
    build_timeout_seconds: int,
    dispatch_timeout_seconds: int | float,
    max_dispatches_per_run: int = 1,
    min_chronological_expansion_seconds: float = (
        DEFAULT_MIN_CHRONOLOGICAL_EXPANSION_SECONDS
    ),
    min_new_scope_rows: int = DEFAULT_MIN_NEW_SCOPE_ROWS,
) -> None:
    numeric = {
        "max_status_age_seconds": max_status_age_seconds,
        "min_new_effective_n": min_new_effective_n,
        "dispatch_timeout_seconds": dispatch_timeout_seconds,
        "min_chronological_expansion_seconds": (
            min_chronological_expansion_seconds
        ),
    }
    for field, value in numeric.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0.0
        ):
            raise AdaptiveEscalationRuntimeError(f"{field}:POSITIVE_FINITE_REQUIRED")
    for field, value in {
        "min_new_matured_outcomes": min_new_matured_outcomes,
        "build_timeout_seconds": build_timeout_seconds,
        "max_dispatches_per_run": max_dispatches_per_run,
        "min_new_scope_rows": min_new_scope_rows,
    }.items():
        if type(value) is not int or value <= 0:
            raise AdaptiveEscalationRuntimeError(f"{field}:POSITIVE_INTEGER_REQUIRED")
    if max_dispatches_per_run > len(LADDER):
        raise AdaptiveEscalationRuntimeError(
            "max_dispatches_per_run:LADDER_BOUND_EXCEEDED"
        )


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
    min_chronological_expansion_seconds: float = (
        DEFAULT_MIN_CHRONOLOGICAL_EXPANSION_SECONDS
    ),
    min_new_scope_rows: int = DEFAULT_MIN_NEW_SCOPE_ROWS,
    build_timeout_seconds: int = 900,
    dispatch_timeout_seconds: int = supervisor.DISPATCH_TIMEOUT_SECONDS,
    max_dispatches_per_run: int = 1,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    _validate_runtime_configuration(
        max_status_age_seconds=max_status_age_seconds,
        min_new_matured_outcomes=min_new_matured_outcomes,
        min_new_effective_n=min_new_effective_n,
        build_timeout_seconds=build_timeout_seconds,
        dispatch_timeout_seconds=dispatch_timeout_seconds,
        max_dispatches_per_run=max_dispatches_per_run,
        min_chronological_expansion_seconds=(
            min_chronological_expansion_seconds
        ),
        min_new_scope_rows=min_new_scope_rows,
    )
    authority, outcomes, performance, registry = authenticate_runtime_inputs(
        client,
        now=now,
        max_age_seconds=max_status_age_seconds,
    )
    archive = outcomes["archive"]
    current_matured = int(archive["matured_revision_count"])
    prior = _load_prior_state(client, state_path)
    release, rebuilt, previous_release = resolve_release(
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
    effective_n = supervisor.load_gen5_corpus_effective_n(dataset_path)[0]
    edge_bps = float(performance["notional_weighted_expectancy_bps"])
    failure_cycle = _failure_cycle(
        authority,
        registry,
        edge_bps=edge_bps,
        performance_sha256=str(performance["source_payload_sha256"]),
    )
    historical_dispatches = discover_historical_completed_dispatches(
        release_parent,
        dispatch_root=dispatch_root,
    )
    cycle_dispatches = tuple(
        evidence
        for evidence in historical_dispatches
        if _dispatch_matches_failure_cycle(evidence, failure_cycle)
    )
    exact_release_steps = {
        evidence.step
        for evidence in cycle_dispatches
        if evidence.release.projection == release.projection
    }
    completed_for_release = set(exact_release_steps)
    if INCREMENTAL_STEP in completed_for_release:
        completed_for_release.add(RECALIBRATION_STEP)
    completed: set[str] = set()
    if failure_cycle["active"]:
        # Runtime state is advisory only. A rung is complete solely when a full
        # canonical terminal-receipt replay succeeds against its exact signed
        # release, so a recomputed plain state hash cannot claim work.
        completed.update(evidence.step for evidence in cycle_dispatches)
        if INCREMENTAL_STEP in completed:
            completed.add(RECALIBRATION_STEP)
    all_pre_promotion_rungs_completed = set(PRE_PROMOTION_LADDER).issubset(
        completed
    )
    latest_training_dispatch = _latest_authenticated_training_dispatch(
        cycle_dispatches
    )
    candidate_registry_present = _redis_value_present(
        client, CANDIDATE_REGISTRY_KEY
    )

    authenticated_baseline = _authenticated_training_baseline(cycle_dispatches)
    if authenticated_baseline is not None:
        baseline = authenticated_baseline
    elif rebuilt and previous_release is not None:
        previous_effective_n = supervisor.load_gen5_corpus_effective_n(
            Path(previous_release.projection["paths"]["dataset"])
        )[0]
        baseline = {
            "matured_outcome_count": previous_release.source_matured_revision_count,
            "effective_n": previous_effective_n,
            "dataset_sha256": previous_release.projection["dataset_sha256"],
            "source_terminal_chain_sha256": (
                previous_release.source_terminal_chain_sha256
            ),
        }
    else:
        baseline = {
            "matured_outcome_count": release.source_matured_revision_count,
            "effective_n": effective_n,
            "dataset_sha256": release.projection["dataset_sha256"],
            "source_terminal_chain_sha256": release.source_terminal_chain_sha256,
        }

    novelty_manifest: dict[str, Any] | None = None
    novelty_gate_active = False
    if (
        failure_cycle["active"]
        and all_pre_promotion_rungs_completed
        and latest_training_dispatch is not None
        and not candidate_registry_present
    ):
        novelty_manifest = build_evidence_novelty_manifest(
            baseline_dispatch=latest_training_dispatch,
            candidate_release=release,
            baseline_effective_n=float(baseline["effective_n"]),
            candidate_effective_n=effective_n,
            failure_cycle=failure_cycle,
            completed_steps=completed,
            current_matured_revision_count=current_matured,
            min_new_matured_outcomes=min_new_matured_outcomes,
            min_new_effective_n=min_new_effective_n,
            min_chronological_expansion_seconds=(
                min_chronological_expansion_seconds
            ),
            min_new_scope_rows=min_new_scope_rows,
            generated_utc=now.isoformat().replace("+00:00", "Z"),
        )
        novelty_gate_active = not novelty_manifest["material_novelty_detected"]

    if (
        rebuilt
        and INCREMENTAL_STEP not in exact_release_steps
        and not novelty_gate_active
    ):
        # New labels must be consumed by a new incremental fit.  Other successful
        # rungs remain completed for the same unresolved economic-failure cycle.
        completed.discard(INCREMENTAL_STEP)

    inputs = replace(
        base_inputs,
        matured_outcome_count=current_matured,
        effective_n=effective_n,
        baseline_matured_outcome_count=int(baseline["matured_outcome_count"]),
        baseline_effective_n=float(baseline["effective_n"]),
        min_new_matured_outcomes=min_new_matured_outcomes,
        min_new_effective_n=min_new_effective_n,
        after_cost_edge_bps=edge_bps,
        exhausted_steps=frozenset(completed),
        release_scoped_information_steps=RELEASE_REUSABLE_INFORMATION_STEPS,
        input_manifest_sha=str(release.projection["dataset_sha256"]),
    )
    plan = replace(
        supervisor.plan_escalation(inputs),
        failure_cycle_id=str(failure_cycle["failure_cycle_id"]),
    )
    reported_plan = plan
    dispatch_results: list[dict[str, Any]] = []
    executed_steps: list[str] = []
    while (
        execute_worker
        and not novelty_gate_active
        and plan.action == supervisor.ACTION_LAUNCH
        and len(dispatch_results) < max_dispatches_per_run
    ):
        reported_plan = plan
        dispatch_result = supervisor.dispatch_worker(
            plan,
            dataset_release_root=release.root,
            dispatch_root=dispatch_root,
            state_path=dispatch_state_path,
            lock_path=dispatch_lock_path,
            timeout_seconds=dispatch_timeout_seconds,
        )
        dispatch_results.append(dispatch_result)
        selected_step = str(plan.selected_step)
        executed_steps.append(selected_step)
        if dispatch_result.get("launch_baseline_success") is not True:
            break
        completed.add(selected_step)
        completed_for_release.add(selected_step)
        if selected_step == INCREMENTAL_STEP:
            completed.add(RECALIBRATION_STEP)
            completed_for_release.add(RECALIBRATION_STEP)
        if selected_step in BASELINE_ADVANCING_STEPS:
            baseline = {
                "matured_outcome_count": release.source_matured_revision_count,
                "effective_n": effective_n,
                "dataset_sha256": release.projection["dataset_sha256"],
                "source_terminal_chain_sha256": (
                    release.source_terminal_chain_sha256
                ),
                "launched_step": selected_step,
                "dispatch_id": dispatch_result.get("dispatch_id"),
                "recorded_utc": now.isoformat().replace("+00:00", "Z"),
            }
        inputs = replace(
            inputs,
            baseline_matured_outcome_count=int(baseline["matured_outcome_count"]),
            baseline_effective_n=float(baseline["effective_n"]),
            exhausted_steps=frozenset(completed),
        )
        plan = replace(
            supervisor.plan_escalation(inputs),
            failure_cycle_id=str(failure_cycle["failure_cycle_id"]),
        )

    dispatch_result = dispatch_results[-1] if dispatch_results else None
    continuation_plan = {
        "action": plan.action,
        "selected_step": plan.selected_step,
        "next_step": plan.next_step,
        "exact_trigger_condition": plan.exact_trigger_condition,
    }
    dispatch_limit_reached = (
        len(dispatch_results) == max_dispatches_per_run
        and plan.action == supervisor.ACTION_LAUNCH
    )

    prior_history = prior.get("directional_history")
    history = [int(v) for v in prior_history] if isinstance(prior_history, list) else []
    history = (history + [inputs.directional_authorized_count])[-20:]
    payload = reported_plan.to_dict()
    if novelty_gate_active:
        payload.update(
            {
                "action": ACTION_AWAIT_NOVEL_EVIDENCE,
                "selected_step": None,
                "next_step": INCREMENTAL_STEP,
                "worker_command": None,
                "exact_trigger_condition": (
                    "next_trigger_manifest.material_novelty_detected == true"
                ),
                "rationale": (
                    "All nine pre-promotion rungs completed for the active "
                    "failure cycle. Raw archive growth is recorded but cannot "
                    "authorize another challenger without authenticated material "
                    "novelty."
                ),
                "validation_errors": [],
            }
        )
        continuation_plan = {
            "action": ACTION_AWAIT_NOVEL_EVIDENCE,
            "selected_step": None,
            "next_step": INCREMENTAL_STEP,
            "exact_trigger_condition": (
                "next_trigger_manifest.material_novelty_detected == true"
            ),
        }
    payload.update(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": now.isoformat().replace("+00:00", "Z"),
            "worker_execution_enabled": execute_worker,
            "dispatch_result": dispatch_result,
            "dispatch_results": dispatch_results,
            "executed_steps_this_run": executed_steps,
            "max_dispatches_per_run": max_dispatches_per_run,
            "dispatch_limit_reached": dispatch_limit_reached,
            "continuation_plan": continuation_plan,
            "active_failure_cycle": failure_cycle["failure_cycle_id"],
            "completed_pre_promotion_rungs": (
                "all_9" if all_pre_promotion_rungs_completed else "incomplete"
            ),
            "active_checkpoint_generation": failure_cycle["checkpoint_binding"][
                "checkpoint_generation"
            ],
            "candidate_registry_write_attempted": candidate_registry_present,
            "next_trigger_manifest": novelty_manifest,
            "failure_cycle": failure_cycle,
            "prior_runtime_state_advisory_only": True,
            "completion_authority": "FULLY_REPLAYED_IMMUTABLE_DISPATCH_RECEIPTS",
            "completed_steps_for_failure_cycle": [
                step for step in LADDER if step in completed
            ],
            "completed_steps_for_input_manifest": [
                step for step in LADDER if step in completed_for_release
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
                "active_registry_key": ACTIVE_REGISTRY_KEY,
                "active_registry_sha256": registry["source_payload_sha256"],
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
    parser.add_argument(
        "--min-chronological-expansion-seconds",
        type=float,
        default=DEFAULT_MIN_CHRONOLOGICAL_EXPANSION_SECONDS,
    )
    parser.add_argument(
        "--min-new-scope-rows", type=int, default=DEFAULT_MIN_NEW_SCOPE_ROWS
    )
    parser.add_argument("--build-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--dispatch-timeout-seconds",
        type=int,
        default=supervisor.DISPATCH_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-dispatches-per-run",
        type=int,
        default=DEFAULT_MAX_DISPATCHES_PER_RUN,
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
            min_chronological_expansion_seconds=(
                args.min_chronological_expansion_seconds
            ),
            min_new_scope_rows=args.min_new_scope_rows,
            build_timeout_seconds=args.build_timeout_seconds,
            dispatch_timeout_seconds=args.dispatch_timeout_seconds,
            max_dispatches_per_run=args.max_dispatches_per_run,
        )
    print(json.dumps(payload, sort_keys=True, allow_nan=False))
    return 0 if not payload.get("validation_errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
