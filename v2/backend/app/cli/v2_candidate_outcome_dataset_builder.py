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
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    PINNED_PRODUCTION_WRITER_ID,
    PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_dataset_receipt_v3 import (
    SCHEMA_VERSION,
    CandidateOutcomeDatasetReceiptError,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_dataset_receipt_v3 import (
    finalize_signed_build_receipt as _finalize_signed_build_receipt,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_serving_dataset_v2 import (
    build_adaptive_serving_dataset_v2,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)

RECEIPT_SIGNING_CREDENTIAL_NAME = "candidate_outcome_ed25519_seed"
DEFAULT_WRITER_ID = PINNED_PRODUCTION_WRITER_ID
PINNED_BASE_DATASET_FILE_SHA256 = (
    "416a25c61e147af30b2ab45fb8c8e08d6348467a42045d0944cf6f1a0d785156"
)
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


def finalize_signed_build_receipt(
    receipt: Mapping[str, Any],
    *,
    artifact_file_sha256s: Mapping[str, str],
    signer: Callable[[bytes], bytes],
    writer_public_key_hex: str,
) -> dict[str, Any]:
    """Finalize against the production writer trust anchor used by this CLI."""

    if writer_public_key_hex != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX:
        raise CandidateOutcomeDatasetBuilderError(
            "receipt_writer_public_key:PINNED_KEY_REQUIRED"
        )
    try:
        return _finalize_signed_build_receipt(
            receipt,
            artifact_file_sha256s=artifact_file_sha256s,
            signer=signer,
            writer_id=PINNED_PRODUCTION_WRITER_ID,
            writer_public_key_hex=writer_public_key_hex,
        )
    except CandidateOutcomeDatasetReceiptError as exc:
        if "SIGNATURE_DOES_NOT_MATCH_DECLARED_KEY" in str(exc):
            raise CandidateOutcomeDatasetBuilderError(
                "receipt_signer:SIGNATURE_DOES_NOT_MATCH_PINNED_KEY"
            ) from exc
        raise CandidateOutcomeDatasetBuilderError(str(exc)) from exc


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


def _deterministic_receipt_generated_at(dataset: Mapping[str, Any]) -> str:
    """Use the latest authenticated label clock, never the wall clock.

    An unchanged source high-water must reproduce identical dataset-release
    bytes.  Every admitted row has already passed the point-in-time validator;
    binding this clock to its latest label availability also prevents a replay
    from pretending to be a newer release merely by rerunning the command.
    """

    rows = dataset.get("rows")
    if type(rows) is not list or not rows:
        raise CandidateOutcomeDatasetBuilderError("dataset:NONEMPTY_ROWS_REQUIRED")
    clocks: list[datetime] = []
    for index, row in enumerate(rows):
        if type(row) is not dict or type(row.get("label_available_at")) is not str:
            raise CandidateOutcomeDatasetBuilderError(
                f"dataset.rows[{index}].label_available_at:UTC_TIMESTAMP_REQUIRED"
            )
        try:
            parsed = datetime.fromisoformat(
                row["label_available_at"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise CandidateOutcomeDatasetBuilderError(
                f"dataset.rows[{index}].label_available_at:UTC_TIMESTAMP_REQUIRED"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise CandidateOutcomeDatasetBuilderError(
                f"dataset.rows[{index}].label_available_at:UTC_TIMESTAMP_REQUIRED"
            )
        clocks.append(parsed)
    return max(clocks).isoformat().replace("+00:00", "Z")


def _load_receipt_signing_key() -> tuple[Ed25519PrivateKey, str]:
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not credentials_directory:
        raise CandidateOutcomeDatasetBuilderError("CREDENTIALS_DIRECTORY:MISSING")
    path = Path(credentials_directory) / RECEIPT_SIGNING_CREDENTIAL_NAME
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CandidateOutcomeDatasetBuilderError(
            "receipt_signing_credential:REGULAR_FILE_REQUIRED"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CandidateOutcomeDatasetBuilderError(
                "receipt_signing_credential:REGULAR_FILE_REQUIRED"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            seed = handle.read()
    finally:
        os.close(descriptor)
    if len(seed) != 32:
        raise CandidateOutcomeDatasetBuilderError(
            "receipt_signing_credential:EXACTLY_32_BYTES_REQUIRED"
        )
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    if public_key_hex != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX:
        raise CandidateOutcomeDatasetBuilderError(
            "receipt_signing_credential:PINNED_PUBLIC_KEY_MISMATCH"
        )
    return private_key, public_key_hex


def _read_pinned_object(
    path: Path,
    field: str,
    *,
    trusted_file_sha256: str,
) -> tuple[dict[str, Any], str]:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise CandidateOutcomeDatasetBuilderError(
            f"{field}:REGULAR_FILE_REQUIRED"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CandidateOutcomeDatasetBuilderError(
                f"{field}:REGULAR_FILE_REQUIRED"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
    finally:
        os.close(descriptor)
    actual_sha256 = _sha256_bytes(data)
    if actual_sha256 != trusted_file_sha256:
        raise CandidateOutcomeDatasetBuilderError(f"{field}:FILE_SHA256_UNTRUSTED")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateOutcomeDatasetBuilderError(f"{field}:INVALID_JSON") from exc
    if type(value) is not dict:
        raise CandidateOutcomeDatasetBuilderError(f"{field}:OBJECT_REQUIRED")
    return value, actual_sha256


def _write_immutable(path: Path, value: object) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise CandidateOutcomeDatasetBuilderError(f"output_path:UNSAFE:{path}")
    data = _canonical_bytes(value, pretty=True)
    digest = _sha256_bytes(data)
    if path.exists():
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise CandidateOutcomeDatasetBuilderError(
                f"output_path:UNSAFE:{path}"
            ) from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise CandidateOutcomeDatasetBuilderError(f"output_path:UNSAFE:{path}")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                current = handle.read()
        finally:
            os.close(descriptor)
        if current != data:
            raise CandidateOutcomeDatasetBuilderError(
                f"output_path:IMMUTABLE_COLLISION:{path}"
            )
        return digest
    if path.is_symlink():
        raise CandidateOutcomeDatasetBuilderError(f"output_path:UNSAFE:{path}")
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
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            try:
                existing_descriptor = os.open(
                    path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                )
            except OSError as exc:
                raise CandidateOutcomeDatasetBuilderError(
                    f"output_path:UNSAFE:{path}"
                ) from exc
            try:
                if not stat.S_ISREG(os.fstat(existing_descriptor).st_mode):
                    raise CandidateOutcomeDatasetBuilderError(
                        f"output_path:UNSAFE:{path}"
                    )
                with os.fdopen(
                    existing_descriptor, "rb", closefd=False
                ) as handle:
                    current = handle.read()
            finally:
                os.close(existing_descriptor)
            if current != data:
                raise CandidateOutcomeDatasetBuilderError(
                    f"output_path:IMMUTABLE_COLLISION:{path}"
                ) from None
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest


def _archive_reader(
    path: Path,
) -> CandidateOutcomeArchiveV2:
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
    if writer_id != PINNED_PRODUCTION_WRITER_ID or writer_id != DEFAULT_WRITER_ID:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:WRITER_ID_UNTRUSTED")
    if public_key != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX:
        raise CandidateOutcomeDatasetBuilderError("candidate_archive:PUBLIC_KEY_UNTRUSTED")
    return CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id=PINNED_PRODUCTION_WRITER_ID,
        writer_public_key_hex=PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
        signer=None,
    )


def build_once(
    *,
    base_dataset_path: Path,
    candidate_archive_path: Path,
    feature_archive_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_dataset, base_dataset_file_sha256 = _read_pinned_object(
        base_dataset_path,
        "base_dataset",
        trusted_file_sha256=PINNED_BASE_DATASET_FILE_SHA256,
    )
    reader = _archive_reader(candidate_archive_path)
    verification, records = (
        reader.read_verified_records_by_sequence_with_verification(
            archive_sequences=(2,),
        )
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
        source_archive_verification=asdict(verification),
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
        "generated_at": _deterministic_receipt_generated_at(dataset),
        "status": "PASS",
        "base_dataset_path": str(base_dataset_path.resolve()),
        "base_dataset_file_sha256": base_dataset_file_sha256,
        "trusted_base_dataset_file_sha256": PINNED_BASE_DATASET_FILE_SHA256,
        "trusted_writer_id": PINNED_PRODUCTION_WRITER_ID,
        "trusted_writer_public_key_hex": PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
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
    private_key, public_key_hex = _load_receipt_signing_key()
    artifact_values = {
        "adaptive_serving_compatible_dataset_v2.json": dataset,
        "adaptive_serving_compatible_dataset_manifest_v2.json": manifest,
        "adaptive_train_serve_feature_parity_report_v2.json": parity,
    }
    artifact_hashes = {
        name: _sha256_bytes(_canonical_bytes(value, pretty=True))
        for name, value in artifact_values.items()
    }
    signed_receipt = finalize_signed_build_receipt(
        receipt,
        artifact_file_sha256s=artifact_hashes,
        signer=private_key.sign,
        writer_public_key_hex=public_key_hex,
    )
    if not args.verify_only:
        root = args.output_root.resolve()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise CandidateOutcomeDatasetBuilderError("output_root:SAFE_DIRECTORY_REQUIRED")
        for name, value in artifact_values.items():
            actual = _write_immutable(root / name, value)
            if actual != artifact_hashes[name]:
                raise CandidateOutcomeDatasetBuilderError(
                    f"artifact_file_sha256s:WRITE_READBACK_MISMATCH:{name}"
                )
        _write_immutable(
            root / "candidate_outcome_dataset_build_receipt_v3.json",
            signed_receipt,
        )
    print(json.dumps(signed_receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
