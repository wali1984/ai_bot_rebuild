"""Rebuild exact per-sequence rejection evidence for the frozen gen-5 corpus.

The original bounded importer persisted an aggregate reason histogram but did
not retain the source sequence attached to each rejected row.  This module
does not infer that identity from the aggregate.  It reopens the authenticated
fixed-observation feature ledger, re-evaluates only the source rows absent
from the immutable challenger archive against the frozen canonical label
archive, and emits one deterministic primary reason per missing sequence.

It has no training, prediction, paper-trading, live, or exchange authority.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.gen5_snapshot_backfill_v1 import (
    Gen5BackfillConfig,
    validate_existing_fixed_snapshot,
)
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    _reconstructed_record_from_verified_label_binding,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    ProfiledTrainingLedgerExclusionV1,
    ProfiledTrainingLedgerSampleV1,
    load_profiled_training_ledger_fixed_observation_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    build_finalized_label_binding_v1,
    derive_label_archive_fixed_observation_proof_v1,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import _build_row

SCHEMA_VERSION = "gen5_rejection_sequence_evidence_v1"
_UNEXPLAINED_REASON = "UNEXPLAINED_IMPORT_DROP"


class Gen5RejectionReconciliationError(RuntimeError):
    """Raised when exact rejection identity cannot be proved."""


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _observation(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise Gen5RejectionReconciliationError("TRAINING_OBSERVATION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Gen5RejectionReconciliationError("TRAINING_OBSERVATION_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Gen5RejectionReconciliationError("TRAINING_OBSERVATION_TIME_INVALID")
    return parsed.astimezone(UTC)


def _imported_sequences(config: Gen5BackfillConfig) -> tuple[int, ...]:
    manifest_path = config.challenger_archive_root / "manifest.jsonl"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise Gen5RejectionReconciliationError("CHALLENGER_MANIFEST_PATH_UNSAFE")
    sequences: set[int] = set()
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                identity = json.loads(line)
            except json.JSONDecodeError as exc:
                raise Gen5RejectionReconciliationError(
                    f"CHALLENGER_MANIFEST_INVALID_ROW:{line_number}"
                ) from exc
            if not isinstance(identity, dict):
                raise Gen5RejectionReconciliationError(
                    f"CHALLENGER_MANIFEST_ROW_NOT_OBJECT:{line_number}"
                )
            snapshot_id = identity.get("snapshot_id")
            if not isinstance(snapshot_id, str) or not snapshot_id:
                raise Gen5RejectionReconciliationError(
                    f"CHALLENGER_SNAPSHOT_ID_INVALID:{line_number}"
                )
            record = load_snapshot(
                snapshot_id,
                root=config.challenger_archive_root,
                verify=True,
            )
            if not isinstance(record, Mapping):
                raise Gen5RejectionReconciliationError(f"CHALLENGER_RECORD_MISSING:{line_number}")
            sequence = record.get("profiled_ledger_sequence")
            if type(sequence) is not int or sequence < 1 or sequence in sequences:
                raise Gen5RejectionReconciliationError(
                    f"CHALLENGER_SEQUENCE_IDENTITY_INVALID:{line_number}"
                )
            sequences.add(sequence)
    return tuple(sorted(sequences))


def _primary_reason(reasons: tuple[str, ...]) -> str:
    normalized = tuple(sorted({str(reason) for reason in reasons if str(reason)}))
    if not normalized:
        return _UNEXPLAINED_REASON
    return normalized[0]


def build_gen5_rejection_sequence_evidence(
    config: Gen5BackfillConfig,
) -> dict[str, Any]:
    """Return independently recomputed one-row/one-reason rejection evidence."""

    manifest = validate_existing_fixed_snapshot(config)
    imported_sequences = _imported_sequences(config)
    imported_set = frozenset(imported_sequences)
    observation = _observation(manifest.get("training_observed_at"))
    ledger = DurableFeatureSnapshotLedger(config.snapshot_ledger_path)
    label_archive = DurableCanonical5mLabelArchive(config.snapshot_label_archive_path)
    label_integrity, label_high_water = derive_label_archive_fixed_observation_proof_v1(
        archive=label_archive,
        observation=observation,
    )
    if label_integrity is None or label_high_water is None:
        raise Gen5RejectionReconciliationError("LABEL_ARCHIVE_FIXED_PROOF_UNAVAILABLE")

    source_sequences: set[int] = set()
    rejected: dict[int, dict[str, Any]] = {}
    source_high_water: dict[str, Any] | None = None

    def observe_high_water(value: Mapping[str, Any]) -> None:
        nonlocal source_high_water
        source_high_water = dict(value)

    def record_rejection(
        *,
        sequence: int,
        durable_snapshot_id: str,
        reasons: tuple[str, ...],
    ) -> None:
        normalized = tuple(sorted({str(reason) for reason in reasons if str(reason)}))
        primary = _primary_reason(normalized)
        if sequence in rejected:
            raise Gen5RejectionReconciliationError(f"DUPLICATE_REJECTION_SEQUENCE:{sequence}")
        rejected[sequence] = {
            "sequence": sequence,
            "durable_snapshot_id": durable_snapshot_id,
            "primary_reason": primary,
            "supporting_reasons": list(normalized or (primary,)),
        }

    def consume_page(
        samples: tuple[ProfiledTrainingLedgerSampleV1, ...],
        exclusions: tuple[ProfiledTrainingLedgerExclusionV1, ...],
    ) -> None:
        for exclusion in exclusions:
            source_sequences.add(exclusion.sequence)
            if exclusion.sequence not in imported_set:
                record_rejection(
                    sequence=exclusion.sequence,
                    durable_snapshot_id=exclusion.durable_snapshot_id,
                    reasons=(exclusion.reason,),
                )
        for sample in samples:
            source_sequences.add(sample.sequence)
            if sample.sequence in imported_set:
                continue
            try:
                label_binding, label_reasons = build_finalized_label_binding_v1(
                    sample=sample,
                    archive=label_archive,
                    observation=observation,
                    archive_integrity=label_integrity,
                    archive_high_water=label_high_water,
                )
                if label_binding is None:
                    record_rejection(
                        sequence=sample.sequence,
                        durable_snapshot_id=sample.durable_snapshot_id,
                        reasons=tuple(
                            str(reason)
                            for reason in label_reasons or ("CANONICAL_LABEL_PATH_UNVERIFIED",)
                        ),
                    )
                    continue
                record = _reconstructed_record_from_verified_label_binding(
                    sample=sample,
                    label_binding=label_binding,
                )
                _build_row(
                    {
                        "row_identity": f"gen5-rejection-check:{sample.durable_snapshot_id}",
                        "snapshot_id": str(record["snapshot_id"]),
                        "content_sha256": str(record["content_sha256"]),
                    },
                    record,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                record_rejection(
                    sequence=sample.sequence,
                    durable_snapshot_id=sample.durable_snapshot_id,
                    reasons=(str(exc) or type(exc).__name__,),
                )
                continue
            record_rejection(
                sequence=sample.sequence,
                durable_snapshot_id=sample.durable_snapshot_id,
                reasons=(_UNEXPLAINED_REASON,),
            )

    scan = load_profiled_training_ledger_fixed_observation_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=config.cost_store_root.resolve(),
        training_observed_at=str(manifest["training_observed_at"]),
        observation_consumer=observe_high_water,
        page_consumer=consume_page,
    )
    if source_high_water is None:
        raise Gen5RejectionReconciliationError("SOURCE_HIGH_WATER_MISSING")
    missing_sequences = tuple(sorted(source_sequences - imported_set))
    unexpected_imported = tuple(sorted(imported_set - source_sequences))
    if tuple(sorted(rejected)) != missing_sequences:
        raise Gen5RejectionReconciliationError("REJECTION_SEQUENCE_COVERAGE_MISMATCH")
    histogram = Counter(str(rejected[sequence]["primary_reason"]) for sequence in missing_sequences)
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "snapshot_id": manifest["snapshot_id"],
        "snapshot_manifest_sha256": manifest["manifest_sha256"],
        "training_observed_at": manifest["training_observed_at"],
        "source_high_water_sha256": source_high_water.get("high_water_sha256"),
        "source_scan_high_water_sha256": scan.high_water_sha256,
        "label_archive_chain_sha256": label_integrity.get("archive_chain_sha256"),
        "label_archive_receipt_sha256": label_high_water.get("receipt_sha256"),
        "source_strict_eligible_count": len(source_sequences),
        "imported_sequence_count": len(imported_sequences),
        "rejected_sequence_count": len(missing_sequences),
        "imported_sequences_sha256": _canonical_sha256(imported_sequences),
        "rejected_sequences_sha256": _canonical_sha256(missing_sequences),
        "rejected_sequence_reasons": [rejected[sequence] for sequence in missing_sequences],
        "rejections_by_primary_reason": dict(sorted(histogram.items())),
        "unexpected_imported_sequences": list(unexpected_imported),
        "all_source_sequences_accounted": not unexpected_imported
        and len(source_sequences) == len(imported_sequences) + len(missing_sequences),
        "one_primary_reason_per_rejected_sequence": all(
            row["primary_reason"] != _UNEXPLAINED_REASON for row in rejected.values()
        ),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    material = dict(evidence)
    evidence["evidence_sha256"] = _canonical_sha256(material)
    return evidence


__all__ = [
    "Gen5RejectionReconciliationError",
    "SCHEMA_VERSION",
    "build_gen5_rejection_sequence_evidence",
]
