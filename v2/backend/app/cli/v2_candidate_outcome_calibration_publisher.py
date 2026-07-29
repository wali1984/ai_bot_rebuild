"""Fit and publish paper-only calibration from authenticated candidate outcomes."""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    PINNED_PRODUCTION_WRITER_ID,
    PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    CandidateOutcomeCalibrationError,
    extract_calibration_observation,
    fit_candidate_outcome_calibration_v2,
)

SCHEMA_VERSION = "candidate_outcome_calibration_publisher_v2"
CALIBRATION_KEY = "v2:adaptive_system:candidate_calibration:v2"
STATUS_KEY = "v2:adaptive_system:candidate_calibration:status"
ACTIVE_REGISTRY_KEY = "v2:model_registry:paper:active"
DEFAULT_WRITER_ID = PINNED_PRODUCTION_WRITER_ID


class CandidateCalibrationPublisherError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _now_ms() -> int:
    return int(time.time() * 1_000)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _strict_object(raw: object, field: str) -> dict[str, Any]:
    if type(raw) is not str or not raw:
        raise CandidateCalibrationPublisherError(f"{field}:missing")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateCalibrationPublisherError(f"{field}:invalid_json") from exc
    if type(payload) is not dict:
        raise CandidateCalibrationPublisherError(f"{field}:object_required")
    return payload


def _archive_reader(
    path: Path,
) -> CandidateOutcomeArchiveV2:
    if path.is_symlink() or not path.is_file():
        raise CandidateCalibrationPublisherError("candidate_archive:regular_file_required")
    with path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
    first = _strict_object(first_line, "candidate_archive.first_row")
    writer_id = first.get("writer_id")
    public_key = first.get("writer_public_key_hex")
    if (
        type(writer_id) is not str
        or writer_id != DEFAULT_WRITER_ID
        or writer_id != PINNED_PRODUCTION_WRITER_ID
    ):
        raise CandidateCalibrationPublisherError("candidate_archive:writer_id_untrusted")
    if public_key != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX:
        raise CandidateCalibrationPublisherError("candidate_archive:public_key_untrusted")
    return CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id=PINNED_PRODUCTION_WRITER_ID,
        writer_public_key_hex=PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
        signer=None,
    )


def fit_active_candidate_calibration(
    records: Sequence[CandidateDecisionOutcomeV2],
    *,
    active_registry: Mapping[str, Any],
    source_archive_chain_sha256: str,
    generated_at_ms: int,
) -> dict[str, Any]:
    generation, checkpoint_id, bundle_sha = _active_registry_identity(active_registry)

    active_records = [
        record
        for record in records
        if record.archive_sequence == 2
        and record.matured_labels is not None
        and record.decision.checkpoint_generation == generation
        and record.decision.checkpoint_id == checkpoint_id
        and record.decision.checkpoint_sha256 == bundle_sha
    ]
    observations = [
        extract_calibration_observation(record) for record in active_records
    ]
    return fit_candidate_outcome_calibration_v2(
        observations,
        generated_at_ms=generated_at_ms,
        source_archive_chain_sha256=source_archive_chain_sha256,
    )


def _active_registry_identity(
    active_registry: Mapping[str, Any],
) -> tuple[int, str, str]:
    generation = active_registry.get("registry_generation")
    checkpoint_id = active_registry.get("checkpoint_id")
    bundle_sha = active_registry.get("checkpoint_bundle_sha256")
    if type(generation) is not int or generation < 1:
        raise CandidateCalibrationPublisherError("active_registry:generation_invalid")
    if type(checkpoint_id) is not str or not checkpoint_id:
        raise CandidateCalibrationPublisherError("active_registry:checkpoint_id_invalid")
    if type(bundle_sha) is not str or len(bundle_sha) != 64:
        raise CandidateCalibrationPublisherError("active_registry:checkpoint_sha_invalid")
    if active_registry.get("paper_only") is not True:
        raise CandidateCalibrationPublisherError("active_registry:paper_only_required")
    if active_registry.get("live_eligible") is not False:
        raise CandidateCalibrationPublisherError("active_registry:live_eligible_forbidden")
    return generation, checkpoint_id, bundle_sha


@contextmanager
def _private_archive_snapshot_reader(
    *,
    archive_path: Path,
    state_root: Path,
):
    source = _archive_reader(archive_path)
    snapshot_root = state_root / "archive_snapshots"
    snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot_path = snapshot_root / (
        f"candidate_decision_outcomes_v2.{os.getpid()}.{time.time_ns()}.jsonl"
    )
    snapshot_receipt = source.copy_locked_snapshot(snapshot_path)
    try:
        yield _archive_reader(snapshot_path), snapshot_receipt
    finally:
        snapshot_path.with_suffix(f"{snapshot_path.suffix}.lock").unlink(
            missing_ok=True
        )
        snapshot_path.unlink(missing_ok=True)


def process_once(
    *,
    client: Any,
    archive_path: Path,
    state_root: Path,
    generated_at_ms: int,
) -> dict[str, Any]:
    registry = _strict_object(client.get(ACTIVE_REGISTRY_KEY), ACTIVE_REGISTRY_KEY)
    generation, checkpoint_id, bundle_sha = _active_registry_identity(registry)

    def active_observation(record: CandidateDecisionOutcomeV2):
        if (
            record.archive_sequence != 2
            or record.matured_labels is None
            or record.decision.checkpoint_generation != generation
            or record.decision.checkpoint_id != checkpoint_id
            or record.decision.checkpoint_sha256 != bundle_sha
        ):
            return None
        observation = extract_calibration_observation(record)
        actual_outcome = record.matured_labels.actual_paper_outcome
        try:
            selected_payload = json.loads(
                record.decision.selected_action.payload_json
            )
        except json.JSONDecodeError as exc:  # pragma: no cover - contract defensive
            raise CandidateCalibrationPublisherError(
                "selected_action:invalid_json"
            ) from exc
        exploration = (
            selected_payload.get("adaptive_policy_action_policy_mode")
            == "bounded_information_seeking_exploration"
        )
        return (observation, actual_outcome is not None, exploration)

    with _private_archive_snapshot_reader(
        archive_path=archive_path,
        state_root=state_root,
    ) as (reader, snapshot_receipt):
        (
            verification,
            observation_projections,
        ) = reader.read_verified_projections_by_sequence_with_verification(
            archive_sequences=(2,),
            projector=active_observation,
            expected_snapshot_sha256=snapshot_receipt["snapshot_sha256"],
            expected_snapshot_size_bytes=snapshot_receipt["source_size_bytes"],
        )
    if verification.verified is not True:
        raise CandidateCalibrationPublisherError("candidate_archive:verification_failed")
    observations = tuple(item[0] for item in observation_projections)
    actual_paper_outcome_count = sum(item[1] for item in observation_projections)
    exploration_outcome_count = sum(
        item[1] and item[2] for item in observation_projections
    )
    calibration_error: CandidateOutcomeCalibrationError | None = None
    try:
        calibration = fit_candidate_outcome_calibration_v2(
            observations,
            source_archive_chain_sha256=verification.terminal_chain_sha256,
            generated_at_ms=generated_at_ms,
        )
    except CandidateOutcomeCalibrationError as exc:
        calibration_error = exc
        calibration = None

    registry_readback = _strict_object(
        client.get(ACTIVE_REGISTRY_KEY),
        f"{ACTIVE_REGISTRY_KEY}.readback",
    )
    if registry_readback != registry:
        raise CandidateCalibrationPublisherError(
            "active_registry:changed_during_calibration"
        )

    if calibration_error is not None:
        status = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "status": "BLOCKED_INSUFFICIENT_OR_INVALID_MATURED_EVIDENCE",
            "exact_blocker": str(calibration_error),
            "source_archive_chain_sha256": verification.terminal_chain_sha256,
            "source_matured_revision_count": verification.matured_revision_count,
            "source_snapshot": snapshot_receipt,
            "source_lock_scope": "BYTE_COPY_ONLY_VERIFICATION_OUTSIDE_SOURCE_LOCK",
            "actual_paper_outcomes_consumed_by_training": actual_paper_outcome_count,
            "bounded_exploration_outcomes_consumed_by_training": (
                exploration_outcome_count
            ),
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_json_atomic(state_root / "status.json", status)
        client.set(STATUS_KEY, json.dumps(status, sort_keys=True, allow_nan=False))
        return status

    if calibration is None:  # pragma: no cover - defensive type narrowing
        raise CandidateCalibrationPublisherError("calibration:missing_result")

    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "PASS",
        "calibration_sha256": calibration["calibration_sha256"],
        "checkpoint_generation": calibration["checkpoint_generation"],
        "checkpoint_id": calibration["checkpoint_id"],
        "fit_sample_count": calibration["fit_sample_count"],
        "validation_sample_count": calibration["validation_sample_count"],
        "source_archive_chain_sha256": verification.terminal_chain_sha256,
        "source_matured_revision_count": verification.matured_revision_count,
        "source_snapshot": snapshot_receipt,
        "source_lock_scope": "BYTE_COPY_ONLY_VERIFICATION_OUTSIDE_SOURCE_LOCK",
        "actual_paper_outcomes_consumed_by_training": actual_paper_outcome_count,
        "bounded_exploration_outcomes_consumed_by_training": (
            exploration_outcome_count
        ),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "calibration.json", calibration)
    _write_json_atomic(state_root / "status.json", status)
    pipeline = client.pipeline(transaction=True)
    pipeline.set(
        CALIBRATION_KEY,
        json.dumps(calibration, sort_keys=True, allow_nan=False),
    )
    pipeline.set(STATUS_KEY, json.dumps(status, sort_keys=True, allow_nan=False))
    pipeline.execute()
    return status


def _parser() -> argparse.ArgumentParser:
    local_root = Path(
        os.environ.get("AI_BOT_LOCAL_DATA_ROOT", str(Path.home() / "ai_bot_local_data"))
    )
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=local_root
        / "candidate_outcomes_v2/candidate_decision_outcomes_v2.jsonl",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=local_root / "adaptive_policy_v2/calibration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.interval_seconds <= 0.0:
        raise SystemExit("--interval-seconds must be positive")
    client = redis.Redis.from_url(
        args.redis_url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_marker: tuple[int, int] | None = None
    while not stopping:
        stat = args.archive_path.stat()
        marker = (stat.st_size, stat.st_mtime_ns)
        if marker != last_marker:
            process_once(
                client=client,
                archive_path=args.archive_path,
                state_root=args.state_root,
                generated_at_ms=_now_ms(),
            )
            last_marker = marker
        if args.once:
            break
        deadline = time.monotonic() + args.interval_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
