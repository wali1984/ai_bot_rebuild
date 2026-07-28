#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v3 import (  # noqa: E402
    train_serving_checkpoint_v3,
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_regular_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"EVIDENCE_REGULAR_FILE_REQUIRED:{path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable_json(path: Path, value: object) -> str:
    data = _json_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        owned_descriptor = descriptor
        descriptor = -1
        with os.fdopen(owned_descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            if _read_regular_bytes(path) != data:
                raise ValueError(
                    f"EVIDENCE_COLLISION_WITH_DIFFERENT_BYTES:{path}"
                ) from exc
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _prepare_evidence_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("EVIDENCE_DIR_SAFE_DIRECTORY_REQUIRED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    bundle, report, _ = train_serving_checkpoint_v3(
        dataset_path=args.dataset.resolve(),
        manifest_path=args.manifest.resolve(),
        parity_path=args.parity.resolve(),
        build_receipt_path=args.build_receipt.resolve(),
        output_dir=args.model_dir.resolve(),
    )
    evidence_dir = args.evidence_dir.resolve()
    _prepare_evidence_directory(evidence_dir)
    bundle_sha256 = _write_immutable_json(
        evidence_dir / "serving_profitability_checkpoint_bundle_v3.json",
        bundle.to_dict(),
    )
    report_sha256 = _write_immutable_json(
        evidence_dir / "serving_profitability_checkpoint_training_report_v3.json",
        report,
    )
    print(
        json.dumps(
            {
                "checkpoint_id": bundle.checkpoint_id,
                "model_architecture": bundle.model_architecture,
                "training_rows": bundle.training_rows,
                "validation_rows": bundle.validation_rows,
                "holdout_rows": bundle.holdout_rows,
                "decision_group_balance": bundle.training_metrics[
                    "decision_group_balance"
                ],
                "validation": bundle.training_metrics["validation"],
                "holdout": bundle.training_metrics["holdout"],
                "activation_eligible": False,
                "bundle_file_sha256": bundle_sha256,
                "report_file_sha256": report_sha256,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
