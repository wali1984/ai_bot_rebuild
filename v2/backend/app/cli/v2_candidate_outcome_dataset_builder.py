"""Build an enlarged serving-compatible dataset from matured paper candidates.

The command fully verifies the signed candidate archive, loads every referenced
feature snapshot with ``verify=True``, combines eligible rows with the frozen
generation-5 dataset, and writes immutable evidence artifacts.  It has no
model-registry, Redis, paper-loop, or exchange authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_serving_dataset_v2 import (
    build_adaptive_serving_dataset_v2,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)

SCHEMA_VERSION = "candidate_outcome_dataset_build_receipt_v2"
DEFAULT_WRITER_ID = "candidate-outcome-writer-v2"
DEFAULT_BASE_DATASET = Path(
    "/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/evidence/"
    "serving_compatible_dataset_gen5.json"
)
DEFAULT_CANDIDATE_ARCHIVE = Path(
    "/home/wali/ai_bot_local_data/candidate_outcomes_v2/"
    "candidate_decision_outcomes_v2.jsonl"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v2"
)


class CandidateOutcomeDatasetBuilderError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_bytes(value: object, *, pretty: bool = False) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=None if pretty else (",", ":"),
                indent=2 if pretty else None,
                ensure_ascii=True,
                allow_nan=False,
            )
            + ("\n" if pretty else "")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomeDatasetBuilderError("STRICT_JSON_REQUIRED") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_object(path: Path, field: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise CandidateOutcomeDatasetBuilderError(f"{field}:REGULAR_FILE_REQUIRED")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateOutcomeDatasetBuilderError(f"{field}:INVALID_JSON") from exc
    if type(value) is not dict:
        raise CandidateOutcomeDatasetBuilderError(f"{field}:OBJECT_REQUIRED")
    return value


def _write_atomic(path: Path, value: object) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and (path.is_symlink() or not path.is_file())):
        raise CandidateOutcomeDatasetBuilderError(f"output_path:UNSAFE:{path}")
    data = _canonical_bytes(value, pretty=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _sha256_bytes(data)


def _archive_reader(path: Path) -> CandidateOutcomeArchiveV2:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:REGULAR_FILE_REQUIRED")
    with path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
    try:
        first = json.loads(first_line)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:INVALID_FIRST_ROW") from exc
    if type(first) is not dict:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:INVALID_FIRST_ROW")
    writer_id = first.get("writer_id")
    public_key = first.get("writer_public_key_hex")
    if writer_id != DEFAULT_WRITER_ID:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:WRITER_ID_UNTRUSTED")
    if type(public_key) is not str:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:PUBLIC_KEY_MISSING")
    return CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id=writer_id,
        writer_public_key_hex=public_key,
        signer=None,
    )


def build_once(
    *,
    base_dataset_path: Path,
    candidate_archive_path: Path,
    feature_archive_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_dataset = _read_object(base_dataset_path, "base_dataset")
    reader = _archive_reader(candidate_archive_path)
    verification, records = reader.read_verified_records_with_verification(
        latest_only=True
    )
    if verification.verified is not True:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:VERIFICATION_FAILED")
    if (
        verification.paper_only is not True
        or verification.live_gate != "blocked_human_only"
        or verification.routes_to_live is not False
        or verification.places_real_order is not False
        or verification.exchange_action_taken is not False
    ):
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:UNSAFE_AUTHORITY")
    feature_root = feature_archive_root.resolve()
    if not feature_root.is_dir() or feature_root.is_symlink():
        raise CandidateOutcomeDatasetBuilderError("feature_archive:SAFE_DIRECTORY_REQUIRED")

    def snapshot_loader(snapshot_id: str):
        return load_snapshot(snapshot_id, root=feature_root, verify=True)

    dataset, manifest, parity = build_adaptive_serving_dataset_v2(
        base_dataset=base_dataset,
        candidate_records=records,
        snapshot_loader=snapshot_loader,
        source_archive_chain_sha256=verification.terminal_chain_sha256,
    )
    high_water = manifest["source_high_watermark"]
    expected = {
        "candidate_archive_candidate_count": verification.candidate_count,
        "candidate_archive_decision_revision_count": verification.decision_revision_count,
        "candidate_archive_matured_revision_count": verification.matured_revision_count,
    }
    actual = {key: high_water.get(key) for key in expected}
    if actual != expected:
        raise CandidateOutcomeDatasetBuilderError(
            f"candidate_archive:VERIFICATION_COUNT_MISMATCH:{actual!r}!={expected!r}"
        )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "PASS",
        "base_dataset_path": str(base_dataset_path.resolve()),
        "base_dataset_file_sha256": _sha256_bytes(base_dataset_path.read_bytes()),
        "candidate_archive_verification": asdict(verification),
        "feature_archive_root": str(feature_root),
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset["dataset_sha256"],
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "training_rows": manifest["training_rows"],
        "validation_rows": manifest["validation_rows"],
        "holdout_rows": manifest["holdout_rows"],
        "candidate_exclusion_reasons": manifest["candidate_exclusion_reasons"],
        "candidate_records_fully_accounted": manifest[
            "candidate_records_fully_accounted"
        ],
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return dataset, manifest, parity, receipt


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dataset", type=Path, default=DEFAULT_BASE_DATASET)
    parser.add_argument("--candidate-archive", type=Path, default=DEFAULT_CANDIDATE_ARCHIVE)
    parser.add_argument(
        "--feature-archive-root",
        type=Path,
        default=repo_root / ".local_data/v2_native_trainer/durable_feature_snapshot_archive",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset, manifest, parity, receipt = build_once(
        base_dataset_path=args.base_dataset,
        candidate_archive_path=args.candidate_archive,
        feature_archive_root=args.feature_archive_root,
    )
    if not args.verify_only:
        root = args.output_root.resolve()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise CandidateOutcomeDatasetBuilderError("output_root:SAFE_DIRECTORY_REQUIRED")
        artifact_hashes = {
            "adaptive_serving_compatible_dataset_v2.json": _write_atomic(
                root / "adaptive_serving_compatible_dataset_v2.json", dataset
            ),
            "adaptive_serving_compatible_dataset_manifest_v2.json": _write_atomic(
                root / "adaptive_serving_compatible_dataset_manifest_v2.json", manifest
            ),
            "adaptive_train_serve_feature_parity_report_v2.json": _write_atomic(
                root / "adaptive_train_serve_feature_parity_report_v2.json", parity
            ),
        }
        receipt["artifact_file_sha256s"] = artifact_hashes
        _write_atomic(root / "candidate_outcome_dataset_build_receipt_v2.json", receipt)
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
