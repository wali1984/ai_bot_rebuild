"""Fit and publish paper-only calibration from authenticated candidate outcomes."""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
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
DEFAULT_WRITER_ID = "candidate-outcome-writer-v2"


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


def _archive_reader(path: Path) -> CandidateOutcomeArchiveV2:
    if path.is_symlink() or not path.is_file():
        raise CandidateCalibrationPublisherError("candidate_archive:regular_file_required")
    with path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
    first = _strict_object(first_line, "candidate_archive.first_row")
    writer_id = first.get("writer_id")
    public_key = first.get("writer_public_key_hex")
    if type(writer_id) is not str or writer_id != DEFAULT_WRITER_ID:
        raise CandidateCalibrationPublisherError("candidate_archive:writer_id_untrusted")
    if type(public_key) is not str:
        raise CandidateCalibrationPublisherError("candidate_archive:public_key_missing")
    return CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id=writer_id,
        writer_public_key_hex=public_key,
        signer=None,
    )


def fit_active_candidate_calibration(
    records: Sequence[CandidateDecisionOutcomeV2],
    *,
    active_registry: Mapping[str, Any],
    source_archive_chain_sha256: str,
    generated_at_ms: int,
) -> dict[str, Any]:
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


def process_once(
    *,
    client: Any,
    archive_path: Path,
    state_root: Path,
    generated_at_ms: int,
) -> dict[str, Any]:
    reader = _archive_reader(archive_path)
    verification = reader.verify()
    if verification.verified is not True:
        raise CandidateCalibrationPublisherError("candidate_archive:verification_failed")
    registry = _strict_object(client.get(ACTIVE_REGISTRY_KEY), ACTIVE_REGISTRY_KEY)
    try:
        calibration = fit_active_candidate_calibration(
            reader.read_verified_records(),
            active_registry=registry,
            source_archive_chain_sha256=verification.terminal_chain_sha256,
            generated_at_ms=generated_at_ms,
        )
    except CandidateOutcomeCalibrationError as exc:
        status = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "status": "BLOCKED_INSUFFICIENT_OR_INVALID_MATURED_EVIDENCE",
            "exact_blocker": str(exc),
            "source_archive_chain_sha256": verification.terminal_chain_sha256,
            "source_matured_revision_count": verification.matured_revision_count,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_json_atomic(state_root / "status.json", status)
        client.set(STATUS_KEY, json.dumps(status, sort_keys=True, allow_nan=False))
        return status

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
