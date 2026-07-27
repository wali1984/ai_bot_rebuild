"""Publish every finalized paper candidate to the authenticated outcome archive.

This runtime has evidence authority only.  It reads one atomic Redis projection
of the finalized paper cycle, dereferences each immutable feature snapshot with
verification enabled, builds revision-one ``CandidateDecisionOutcomeV2``
records, and appends the complete cycle under one signed archive transaction.
It has no exchange credentials and cannot authorize or submit an order.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_publisher_v2 import (
    PublisherCycleV2,
    build_publisher_cycle,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)

RUNTIME_SCHEMA_VERSION = "candidate_outcome_publisher_runtime_v2"
CYCLE_RECEIPT_SCHEMA_VERSION = "candidate_outcome_publisher_cycle_receipt_v2"
TERMINAL_RECEIPT_SCHEMA_VERSION = "candidate_outcome_publisher_terminal_receipt_v2"
WRITER_ID = "candidate-outcome-writer-v2"
SIGNING_CREDENTIAL_NAME = "candidate_outcome_ed25519_seed"
PAPER_STATUS_KEY = "v2:paper:trade_management:status"
PAPER_INTENTS_KEY = "v2:paper:intents"
PAPER_REGISTRY_KEY = "v2:model_registry:paper:active"
RUNTIME_STATUS_KEY = "v2:adaptive_system:candidate_outcomes:status"
SAFE_RESUME_COMMAND = (
    ".venv/bin/python -P -B -m "
    "v2.backend.app.cli.v2_candidate_outcome_publisher --loop"
)


class CandidateOutcomeRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1_000)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomeRuntimeError("payload_not_strict_json") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
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


def _strict_json_object(raw: object, field: str) -> dict[str, Any]:
    if type(raw) is not str or not raw:
        raise CandidateOutcomeRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not dict:
        raise CandidateOutcomeRuntimeError(f"{field}:object_required")
    return value


def _strict_json_array(raw: object, field: str) -> list[dict[str, Any]]:
    if type(raw) is not str or not raw:
        raise CandidateOutcomeRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise CandidateOutcomeRuntimeError(f"{field}:object_array_required")
    return value


def _read_cycle_projection(
    client: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    raw_status, raw_intents, raw_registry = client.mget(
        (PAPER_STATUS_KEY, PAPER_INTENTS_KEY, PAPER_REGISTRY_KEY)
    )
    return (
        _strict_json_object(raw_status, PAPER_STATUS_KEY),
        _strict_json_array(raw_intents, PAPER_INTENTS_KEY),
        _strict_json_object(raw_registry, PAPER_REGISTRY_KEY),
    )


def _paper_status_marker(client: Any) -> str:
    return _sha256(_strict_json_object(client.get(PAPER_STATUS_KEY), PAPER_STATUS_KEY))


def _snapshot_id(intent: Mapping[str, Any]) -> str:
    prediction = intent.get("entry_prediction_snapshot")
    prediction = prediction if isinstance(prediction, Mapping) else {}
    value = (
        intent.get("entry_feature_snapshot_id")
        or intent.get("feature_snapshot_id")
        or prediction.get("feature_snapshot_id")
    )
    if type(value) is not str or not value or value.strip() != value:
        raise CandidateOutcomeRuntimeError("intent:feature_snapshot_id_required")
    return value


def _load_feature_snapshots(
    intents: list[dict[str, Any]], archive_root: Path
) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for snapshot_id in sorted({_snapshot_id(intent) for intent in intents}):
        snapshot = load_snapshot(snapshot_id, root=archive_root, verify=True)
        if snapshot is None:
            raise CandidateOutcomeRuntimeError(
                f"feature_snapshot:{snapshot_id}:missing_from_verified_archive"
            )
        snapshots[snapshot_id] = snapshot
    return snapshots


def _cycle_id(cycle: PublisherCycleV2) -> str:
    material = {
        "schema_version": CYCLE_RECEIPT_SCHEMA_VERSION,
        "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
        "matrix_generated_at_ms": cycle.matrix_generated_at_ms,
        "source_candidate_count": cycle.source_candidate_count,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "record_content_sha256s": [
            record.content_sha256() for record in cycle.decision_records
        ],
    }
    return f"candidate_cycle_{_sha256(material)}"


def _existing_cycle_receipt(path: Path, cycle: PublisherCycleV2, cycle_id: str) -> bool:
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise CandidateOutcomeRuntimeError("cycle_receipt:regular_file_required")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateOutcomeRuntimeError("cycle_receipt:invalid") from exc
    expected = {
        "cycle_id": cycle_id,
        "source_candidate_count": cycle.source_candidate_count,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "record_content_sha256s": [
            record.content_sha256() for record in cycle.decision_records
        ],
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise CandidateOutcomeRuntimeError(f"cycle_receipt:{field}:mismatch")
    if receipt.get("completed") is not True:
        raise CandidateOutcomeRuntimeError("cycle_receipt:completion_unproven")
    return True


def process_cycle(
    *,
    client: Any,
    archive: CandidateOutcomeArchiveV2,
    state_root: Path,
    feature_archive_root: Path,
    signed_at_ms: int,
) -> dict[str, Any]:
    paper_status, intents, registry = _read_cycle_projection(client)
    snapshots = _load_feature_snapshots(intents, feature_archive_root)
    cycle = build_publisher_cycle(
        paper_status=paper_status,
        intents=intents,
        registry_payload=registry,
        feature_snapshots_by_id=snapshots,
    )
    cycle_id = _cycle_id(cycle)
    receipt_path = state_root / "cycle_receipts" / f"{cycle_id}.json"
    already_complete = _existing_cycle_receipt(receipt_path, cycle, cycle_id)

    if already_complete:
        append_receipts = ()
        verification = archive.verify()
    else:
        append_receipts = (
            archive.append_many(cycle.decision_records, signed_at_ms=signed_at_ms)
            if cycle.decision_records
            else ()
        )
        verification = archive.verify()
        cycle_receipt = {
            "schema_version": CYCLE_RECEIPT_SCHEMA_VERSION,
            "cycle_id": cycle_id,
            "generated_at": _utc_now(),
            "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
            "matrix_generated_at_ms": cycle.matrix_generated_at_ms,
            "source_candidate_count": cycle.source_candidate_count,
            "recorded_candidate_count": len(cycle.decision_records),
            "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
            "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
            "record_content_sha256s": [
                record.content_sha256() for record in cycle.decision_records
            ],
            "archive_receipt_ids": [receipt.receipt_id for receipt in append_receipts],
            "archive_terminal_chain_sha256": verification.terminal_chain_sha256,
            "candidate_recording_coverage": cycle.candidate_recording_coverage,
            "unexplained_candidate_drops": cycle.unexplained_candidate_drops,
            "completed": True,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_json_atomic(receipt_path, cycle_receipt)

    status = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "PASS",
        "scope": "paper_loop_finalized_candidate_universe",
        "cycle_id": cycle_id,
        "source_paper_status_sha256": _sha256(paper_status),
        "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
        "source_candidate_count": cycle.source_candidate_count,
        "recorded_candidate_count": len(cycle.decision_records),
        "candidate_recording_coverage": cycle.candidate_recording_coverage,
        "candidate_recording_coverage_100_percent": (
            cycle.candidate_recording_coverage == 1.0
        ),
        "unexplained_candidate_drops": cycle.unexplained_candidate_drops,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "cycle_idempotent_replay": already_complete,
        "archive_batch_append_count": len(append_receipts),
        "archive_idempotent_append_count": sum(
            receipt.idempotent_replay for receipt in append_receipts
        ),
        "archive": asdict(verification),
        "feature_snapshot_archive_root": str(feature_archive_root),
        "writer_id": archive.writer_id,
        "writer_public_key_hex": archive.writer_public_key_hex,
        "signing_private_key_exported": False,
        "single_policy_writer_claimed": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "status.json", status)
    client.set(RUNTIME_STATUS_KEY, _canonical_json(status))
    return status


def _load_signing_key() -> tuple[Ed25519PrivateKey, str]:
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not credentials_directory:
        raise CandidateOutcomeRuntimeError("CREDENTIALS_DIRECTORY:missing")
    path = Path(credentials_directory) / SIGNING_CREDENTIAL_NAME
    if path.is_symlink() or not path.is_file():
        raise CandidateOutcomeRuntimeError("signing_credential:regular_file_required")
    seed = path.read_bytes()
    if len(seed) != 32:
        raise CandidateOutcomeRuntimeError("signing_credential:exactly_32_bytes_required")
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return private_key, public_key_hex


def _acquire_single_writer_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _terminal_receipt(
    state_root: Path,
    *,
    reason: str,
    signal_number: int | None,
    exception: BaseException | None,
) -> None:
    payload = {
        "schema_version": TERMINAL_RECEIPT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "exit_reason": reason,
        "signal_number": signal_number,
        "exception_type": type(exception).__name__ if exception else None,
        "exception_message": str(exception)[:2_048] if exception else None,
        "safe_resume_command": SAFE_RESUME_COMMAND,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "terminal_receipt.json", payload)


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[4]
    local_data_root = Path(
        os.environ.get("AI_BOT_LOCAL_DATA_ROOT", str(Path.home() / "ai_bot_local_data"))
    )
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument(
        "--state-root",
        type=Path,
        default=local_data_root / "candidate_outcomes_v2",
    )
    parser.add_argument(
        "--feature-archive-root",
        type=Path,
        default=repo_root / ".local_data/v2_native_trainer/durable_feature_snapshot_archive",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(
            os.environ.get(
                "V2_CANDIDATE_OUTCOME_PUBLISHER_LOCK_PATH",
                f"/run/user/{os.getuid()}/ai-bot-v2-candidate-outcome-publisher/writer.lock",
            )
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_descriptor = _acquire_single_writer_lock(args.lock_path)
    private_key, public_key_hex = _load_signing_key()
    archive = CandidateOutcomeArchiveV2(
        archive_path=args.state_root / "candidate_decision_outcomes_v2.jsonl",
        writer_id=WRITER_ID,
        writer_public_key_hex=public_key_hex,
        signer=private_key.sign,
    )
    client = redis.Redis.from_url(
        args.redis_url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )
    stopping = False
    received_signal: int | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stopping, received_signal
        stopping = True
        received_signal = signum

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    failure: BaseException | None = None
    last_status_marker: str | None = None
    try:
        while not stopping:
            current_marker = _paper_status_marker(client)
            if current_marker != last_status_marker:
                status = process_cycle(
                    client=client,
                    archive=archive,
                    state_root=args.state_root,
                    feature_archive_root=args.feature_archive_root,
                    signed_at_ms=_now_ms(),
                )
                last_status_marker = status["source_paper_status_sha256"]
            if args.once:
                break
            deadline = time.monotonic() + args.interval_seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    except BaseException as exc:
        failure = exc
        _terminal_receipt(
            args.state_root,
            reason="EXCEPTION",
            signal_number=received_signal,
            exception=exc,
        )
        print(f"candidate outcome publisher failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock_descriptor)

    _terminal_receipt(
        args.state_root,
        reason="SIGNAL" if received_signal is not None else "ONCE_COMPLETE",
        signal_number=received_signal,
        exception=failure,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
