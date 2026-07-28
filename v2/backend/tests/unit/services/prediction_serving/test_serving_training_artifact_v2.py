from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.contracts.runtime_v2.contracts import canonical_sha256
from v2.backend.app.services.adaptive_system.candidate_outcome_dataset_receipt_v3 import (
    SCHEMA_VERSION as SIGNED_RECEIPT_SCHEMA_VERSION,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_dataset_receipt_v3 import (
    SIGNATURE_FIELDS,
    canonical_receipt_bytes,
    finalize_signed_build_receipt,
    receipt_unsigned_material,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_serving_dataset_v2 import (
    build_adaptive_serving_dataset_v2,
    build_candidate_outcome_row,
)
from v2.backend.app.services.prediction_serving import serving_training_artifact_v2
from v2.backend.app.services.prediction_serving.serving_training_artifact_v2 import (
    ServingTrainingArtifactError,
    load_validated_training_artifacts,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_serving_dataset_v2 import (
    _base_dataset,
    _matured_record,
    _source_verification,
)


def _bytes(value: object) -> bytes:
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


def _rehash_dataset(dataset: dict[str, Any]) -> None:
    material = {
        key: value
        for key, value in dataset.items()
        if key not in {"dataset_id", "dataset_sha256"}
    }
    digest = canonical_sha256(material)
    dataset["dataset_sha256"] = digest
    dataset["dataset_id"] = f"adaptive_serving_dataset_v2_{digest[:24]}"


def _rehash_manifest(manifest: dict[str, Any]) -> None:
    material = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifest_id", "manifest_sha256"}
    }
    digest = canonical_sha256(material)
    manifest["manifest_sha256"] = digest
    manifest["manifest_id"] = f"adaptive_serving_manifest_v2_{digest[:24]}"


class ArtifactFixture:
    def __init__(
        self,
        *,
        root: Path,
        dataset: dict[str, Any],
        base_dataset: dict[str, Any],
        manifest: dict[str, Any],
        parity: dict[str, Any],
        receipt: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self.root = root
        self.dataset = dataset
        self.base_dataset = base_dataset
        self.manifest = manifest
        self.parity = parity
        self.receipt = receipt
        self.monkeypatch = monkeypatch
        self.dataset_path = root / "adaptive_serving_compatible_dataset_v2.json"
        self.base_dataset_path = root / "serving_compatible_dataset_gen5.json"
        self.manifest_path = (
            root / "adaptive_serving_compatible_dataset_manifest_v2.json"
        )
        self.parity_path = root / "adaptive_train_serve_feature_parity_report_v2.json"
        self.receipt_path = root / "candidate_outcome_dataset_build_receipt_v2.json"

    def write(self, *, repin_receipt: bool = True) -> None:
        base_bytes = _bytes(self.base_dataset)
        self.base_dataset_path.write_bytes(base_bytes)
        base_file_sha = hashlib.sha256(base_bytes).hexdigest()
        self.monkeypatch.setattr(
            serving_training_artifact_v2,
            "PINNED_BASE_DATASET_FILE_SHA256",
            base_file_sha,
        )
        self.receipt.update(
            {
                "base_dataset_path": str(self.base_dataset_path),
                "base_dataset_file_sha256": base_file_sha,
                "trusted_base_dataset_file_sha256": base_file_sha,
            }
        )
        _rehash_dataset(self.dataset)
        self.manifest["dataset_id"] = self.dataset["dataset_id"]
        self.manifest["dataset_sha256"] = self.dataset["dataset_sha256"]
        _rehash_manifest(self.manifest)
        self.receipt.update(
            {
                "dataset_id": self.dataset["dataset_id"],
                "dataset_sha256": self.dataset["dataset_sha256"],
                "manifest_id": self.manifest["manifest_id"],
                "manifest_sha256": self.manifest["manifest_sha256"],
                "training_rows": self.manifest["training_rows"],
                "validation_rows": self.manifest["validation_rows"],
                "holdout_rows": self.manifest["holdout_rows"],
                "candidate_exclusion_reasons": self.manifest[
                    "candidate_exclusion_reasons"
                ],
            }
        )
        artifact_values = {
            self.dataset_path: self.dataset,
            self.manifest_path: self.manifest,
            self.parity_path: self.parity,
        }
        artifact_bytes = {path: _bytes(value) for path, value in artifact_values.items()}
        self.receipt["artifact_file_sha256s"] = {
            path.name: hashlib.sha256(data).hexdigest()
            for path, data in artifact_bytes.items()
        }
        for path, data in artifact_bytes.items():
            path.write_bytes(data)
        receipt_bytes = _bytes(self.receipt)
        self.receipt_path.write_bytes(receipt_bytes)
        if repin_receipt:
            self.monkeypatch.setattr(
                serving_training_artifact_v2,
                "PINNED_BUILD_RECEIPT_FILE_SHA256",
                hashlib.sha256(receipt_bytes).hexdigest(),
            )

    def load(self) -> tuple[dict[str, Any], ...]:
        return load_validated_training_artifacts(
            dataset_path=self.dataset_path,
            manifest_path=self.manifest_path,
            parity_path=self.parity_path,
            build_receipt_path=self.receipt_path,
        )


def _build_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ArtifactFixture:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    matured, snapshot = _matured_record()
    template = build_candidate_outcome_row(
        matured,
        snapshot_loader=lambda _snapshot_id: snapshot,
        source_archive_chain_sha256="a" * 64,
    )
    base_dataset = _base_dataset(template)
    for sequence, row in enumerate(base_dataset["rows"], start=1):
        decision_time = serving_training_artifact_v2._utc(
            row["decision_time"], "fixture.decision_time"
        )
        feature_cutoff = decision_time - timedelta(minutes=2)
        record_available_at = decision_time - timedelta(minutes=1)
        row.update(
            {
                "discovery_inventory_content_matches_current": True,
                "discovery_inventory_content_sha256": "b" * 64,
                "profiled_ledger_sequence": sequence,
                "feature_cutoff": feature_cutoff.isoformat().replace("+00:00", "Z"),
                "record_available_at": record_available_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "latest_closed_kline_close_time_ms": int(
                    feature_cutoff.timestamp() * 1_000
                ),
                "latest_unclosed_exclusion_decision_time_ms": int(
                    decision_time.timestamp() * 1_000
                ),
                "source_hashes": {
                    "canonical_label_binding_sha256": row[
                        "label_binding_sha256"
                    ],
                    "cost_capture_artifact_sha256": "1" * 64,
                    "cost_capture_binding_sha256": "2" * 64,
                    "cost_capture_receipt_sha256": "3" * 64,
                    "cost_cas_object_inventory_sha256": "4" * 64,
                    "mtf_binding_sha256": "5" * 64,
                    "parent_lineage_binding_sha256": "6" * 64,
                    "parent_record_sha256": "7" * 64,
                    "profiled_ledger_high_water_sha256": "8" * 64,
                    "profiled_ledger_record_sha256": "9" * 64,
                },
            }
        )
        action_offset = (sequence - 1) % 3
        if action_offset == 0:
            long_net_bps, short_net_bps, action, action_index = 20.0, -20.0, "long", 0
            row["feature_values"][0:3] = [10.0, -10.0, 1.0]
        elif action_offset == 1:
            long_net_bps, short_net_bps, action, action_index = -20.0, 20.0, "short", 1
            row["feature_values"][0:3] = [-10.0, 10.0, 1.0]
        else:
            long_net_bps, short_net_bps, action, action_index = -5.0, -5.0, "hold", 2
            row["feature_values"][0:3] = [0.0, 0.0, -1.0]
        row.update(
            {
                "long_net_bps": long_net_bps,
                "short_net_bps": short_net_bps,
                "target_action": action,
                "target_action_index": action_index,
            }
        )
    base_material = {
        key: value
        for key, value in base_dataset.items()
        if key not in {"dataset_id", "dataset_sha256"}
    }
    base_dataset["dataset_sha256"] = canonical_sha256(base_material)
    base_dataset["dataset_id"] = (
        f"serving_dataset_v2_{base_dataset['dataset_sha256'][:24]}"
    )
    dataset, manifest, parity = build_adaptive_serving_dataset_v2(
        base_dataset=deepcopy(base_dataset),
        candidate_records=(matured,),
        snapshot_loader=lambda _snapshot_id: snapshot,
        source_archive_chain_sha256="a" * 64,
        source_archive_verification=_source_verification(),
    )
    receipt: dict[str, Any] = {
        "schema_version": "candidate_outcome_dataset_build_receipt_v2",
        "generated_at": "2027-01-01T00:00:00.000Z",
        "status": "PASS",
        "base_dataset_path": "/authenticated/serving_compatible_dataset_gen5.json",
        "base_dataset_file_sha256": (
            serving_training_artifact_v2.PINNED_BASE_DATASET_FILE_SHA256
        ),
        "trusted_base_dataset_file_sha256": (
            serving_training_artifact_v2.PINNED_BASE_DATASET_FILE_SHA256
        ),
        "trusted_writer_id": "candidate-outcome-writer-v2",
        "trusted_writer_public_key_hex": (
            "bbff6e85cd6954ae5aff4ee2ec5d2078de96bf8f8750aaa889d2ea4712c5b4d9"
        ),
        "candidate_archive_verification": _source_verification(),
        "feature_archive_root": "/authenticated/durable-feature-snapshots",
        "dataset_id": "pending",
        "dataset_sha256": "0" * 64,
        "manifest_id": "pending",
        "manifest_sha256": "0" * 64,
        "training_rows": 0,
        "validation_rows": 0,
        "holdout_rows": 0,
        "candidate_exclusion_reasons": {},
        "candidate_records_fully_accounted": True,
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "artifact_file_sha256s": {},
    }
    fixture = ArtifactFixture(
        root=tmp_path,
        dataset=dataset,
        base_dataset=base_dataset,
        manifest=manifest,
        parity=parity,
        receipt=receipt,
        monkeypatch=monkeypatch,
    )
    fixture.write()
    return fixture


@pytest.fixture
def artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactFixture:
    return _build_artifacts(tmp_path, monkeypatch)


def test_exact_authenticated_artifacts_load(artifacts: ArtifactFixture) -> None:
    dataset, manifest, parity, receipt = artifacts.load()

    assert len(dataset["rows"]) == sum(
        manifest[field] for field in ("training_rows", "validation_rows", "holdout_rows")
    )
    assert parity["builder_match"] is True
    assert receipt["candidate_records_fully_accounted"] is True


def _upgrade_to_signed_v3(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> Ed25519PrivateKey:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    monkeypatch.setattr(
        serving_training_artifact_v2,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        public_key_hex,
    )
    artifacts.receipt["trusted_writer_public_key_hex"] = public_key_hex
    artifacts.receipt["candidate_archive_verification"][
        "writer_public_key_hex"
    ] = public_key_hex
    artifacts.manifest["source_high_watermark"][
        "candidate_archive_writer_public_key_hex"
    ] = public_key_hex
    artifacts.write(repin_receipt=False)
    unsigned = {**artifacts.receipt, "schema_version": SIGNED_RECEIPT_SCHEMA_VERSION}
    signed = finalize_signed_build_receipt(
        unsigned,
        artifact_file_sha256s=unsigned["artifact_file_sha256s"],
        signer=private_key.sign,
        writer_id=serving_training_artifact_v2.PINNED_PRODUCTION_WRITER_ID,
        writer_public_key_hex=public_key_hex,
    )
    artifacts.receipt.clear()
    artifacts.receipt.update(signed)
    artifacts.receipt_path.write_bytes(_bytes(signed))
    monkeypatch.setattr(
        serving_training_artifact_v2,
        "PINNED_BUILD_RECEIPT_FILE_SHA256",
        "0" * 64,
    )
    return private_key


def _write_receipt(artifacts: ArtifactFixture) -> None:
    artifacts.receipt_path.write_bytes(_bytes(artifacts.receipt))


def _publicly_rehash_receipt(artifacts: ArtifactFixture) -> None:
    unsigned_bytes = canonical_receipt_bytes(
        receipt_unsigned_material(artifacts.receipt)
    )
    artifacts.receipt["receipt_payload_sha256"] = hashlib.sha256(
        unsigned_bytes
    ).hexdigest()
    _write_receipt(artifacts)


def _resign_receipt(
    artifacts: ArtifactFixture,
    private_key: Ed25519PrivateKey,
) -> None:
    unsigned = {
        key: value
        for key, value in artifacts.receipt.items()
        if key not in SIGNATURE_FIELDS
    }
    signed = finalize_signed_build_receipt(
        unsigned,
        artifact_file_sha256s=unsigned["artifact_file_sha256s"],
        signer=private_key.sign,
        writer_id=artifacts.receipt["receipt_writer_id"],
        writer_public_key_hex=artifacts.receipt["receipt_writer_public_key_hex"],
    )
    artifacts.receipt.clear()
    artifacts.receipt.update(signed)
    _write_receipt(artifacts)


def test_valid_signed_v3_receipt_loads_without_raw_file_pin(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)

    dataset, manifest, parity, receipt = artifacts.load()

    assert dataset["dataset_sha256"] == receipt["dataset_sha256"]
    assert manifest["manifest_sha256"] == receipt["manifest_sha256"]
    assert parity["paper_only"] is True
    assert receipt["schema_version"] == SIGNED_RECEIPT_SCHEMA_VERSION
    assert receipt["paper_only"] is True
    assert receipt["live_gate"] == "blocked_human_only"
    assert receipt["routes_to_live"] is False
    assert receipt["places_real_order"] is False
    assert receipt["exchange_action_taken"] is False


def test_unsigned_v3_receipt_is_rejected(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)
    for field in SIGNATURE_FIELDS:
        artifacts.receipt.pop(field)
    _write_receipt(artifacts)

    with pytest.raises(ServingTrainingArtifactError, match="build_receipt:SCHEMA_MISMATCH"):
        artifacts.load()


def test_public_receipt_rehash_and_raw_repin_cannot_replace_signature(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)
    artifacts.receipt["status"] = "PUBLICLY_REHASHED"
    _publicly_rehash_receipt(artifacts)
    monkeypatch.setattr(
        serving_training_artifact_v2,
        "PINNED_BUILD_RECEIPT_FILE_SHA256",
        hashlib.sha256(artifacts.receipt_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ServingTrainingArtifactError, match="SIGNATURE_INVALID"):
        artifacts.load()


def test_alternate_self_signed_v3_key_is_rejected(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)
    alternate = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    alternate_public_hex = (
        alternate.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    unsigned = {
        key: value
        for key, value in artifacts.receipt.items()
        if key not in SIGNATURE_FIELDS
    }
    signed = finalize_signed_build_receipt(
        unsigned,
        artifact_file_sha256s=unsigned["artifact_file_sha256s"],
        signer=alternate.sign,
        writer_id=artifacts.receipt["receipt_writer_id"],
        writer_public_key_hex=alternate_public_hex,
    )
    artifacts.receipt.clear()
    artifacts.receipt.update(signed)
    _write_receipt(artifacts)

    with pytest.raises(ServingTrainingArtifactError, match="PINNED_PUBLIC_KEY_REQUIRED"):
        artifacts.load()


@pytest.mark.parametrize(
    ("field", "invalid", "reason"),
    [
        ("receipt_signature_hex", "c" * 128, "SIGNATURE_INVALID"),
        ("receipt_payload_sha256", "c" * 64, "PAYLOAD_SHA256_MISMATCH"),
        ("receipt_signature_domain", "wrong-domain", "DOMAIN_MISMATCH"),
        ("receipt_signature_algorithm", "not-ed25519", "ALGORITHM_MISMATCH"),
        ("receipt_writer_id", "alternate-writer", "PINNED_WRITER_REQUIRED"),
    ],
)
def test_signed_v3_envelope_tampering_is_rejected(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: str,
    reason: str,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)
    artifacts.receipt[field] = invalid
    _write_receipt(artifacts)

    with pytest.raises(ServingTrainingArtifactError, match=reason):
        artifacts.load()


@pytest.mark.parametrize("artifact", ["dataset", "manifest", "parity"])
def test_public_artifact_rehashes_cannot_replace_private_receipt_signature(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    _upgrade_to_signed_v3(artifacts, monkeypatch)
    if artifact == "dataset":
        artifacts.dataset["rows"][0]["feature_values"][0] += 0.125
    elif artifact == "manifest":
        artifacts.manifest["symbol_count"] += 1
    else:
        artifacts.parity["activation_block_reason"] = "PUBLIC_MUTATION"
    artifacts.write(repin_receipt=True)
    _publicly_rehash_receipt(artifacts)
    monkeypatch.setattr(
        serving_training_artifact_v2,
        "PINNED_BUILD_RECEIPT_FILE_SHA256",
        hashlib.sha256(artifacts.receipt_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ServingTrainingArtifactError, match="SIGNATURE_INVALID"):
        artifacts.load()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("paper_only", False),
        ("live_gate", "open"),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("exchange_action_taken", True),
    ],
)
def test_even_trusted_signed_v3_receipt_requires_exact_paper_only_authority(
    artifacts: ArtifactFixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: object,
) -> None:
    private_key = _upgrade_to_signed_v3(artifacts, monkeypatch)
    artifacts.receipt[field] = invalid
    _resign_receipt(artifacts, private_key)

    with pytest.raises(
        ServingTrainingArtifactError,
        match="UNTRUSTED_OR_UNSAFE_BUILD_RECEIPT",
    ):
        artifacts.load()


def test_historical_exact_v2_receipt_still_loads(
    artifacts: ArtifactFixture,
) -> None:
    assert artifacts.receipt["schema_version"] == "candidate_outcome_dataset_build_receipt_v2"
    artifacts.load()


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row.__setitem__("split", "unknown"), "KNOWN_SPLIT_REQUIRED"),
        (
            lambda row: row.__setitem__("target_action_index", 99),
            "ACTION_INDEX_MISMATCH",
        ),
        (lambda row: row["feature_values"].pop(), "FEATURE_WIDTH_MISMATCH"),
        (lambda row: row["missing_mask"].__setitem__(0, 1), "REQUIRED_FEATURE_MISSING"),
        (
            lambda row: row.__setitem__("record_available_at", "2099-01-01T00:00:00Z"),
            "POINT_IN_TIME_CLOCK_ORDER_INVALID",
        ),
        (
            lambda row: row.__setitem__("label_available_at", row["decision_time"]),
            "POINT_IN_TIME_CLOCK_ORDER_INVALID",
        ),
        (
            lambda row: row.__setitem__("latest_unclosed_kline_excluded", False),
            "LATEST_UNCLOSED_KLINE_EXCLUSION_REQUIRED",
        ),
        (
            lambda row: row.__setitem__("cost_evidence_sha256", None),
            "LOWERCASE_SHA256_REQUIRED",
        ),
        (
            lambda row: row.__setitem__(
                "counterfactual_counts_as_realized_paper_profit", True
            ),
            "COUNTERFACTUAL_REALIZED_PROFIT_FORBIDDEN",
        ),
    ],
)
def test_coherently_rehashed_unsafe_row_is_rejected(
    artifacts: ArtifactFixture,
    mutate: Callable[[dict[str, Any]], None],
    reason: str,
) -> None:
    mutate(artifacts.dataset["rows"][0])
    artifacts.write()

    with pytest.raises(ServingTrainingArtifactError, match=reason):
        artifacts.load()


def test_duplicate_row_id_is_rejected(artifacts: ArtifactFixture) -> None:
    artifacts.dataset["rows"].append(deepcopy(artifacts.dataset["rows"][0]))
    artifacts.write()

    with pytest.raises(ServingTrainingArtifactError, match="DUPLICATE_ROW_ID"):
        artifacts.load()


@pytest.mark.parametrize("invalid", [False, 0.5, "0"])
def test_zero_admission_counters_require_exact_integer_zero(
    artifacts: ArtifactFixture, invalid: object
) -> None:
    artifacts.manifest["future_time_rejections"] = invalid
    artifacts.write()

    with pytest.raises(ServingTrainingArtifactError, match="NONNEGATIVE_INT_REQUIRED"):
        artifacts.load()


def test_coherently_rehashed_substitute_receipt_is_not_the_pinned_receipt(
    artifacts: ArtifactFixture,
) -> None:
    artifacts.dataset["rows"][0]["feature_values"][0] += 0.25
    artifacts.write(repin_receipt=False)

    with pytest.raises(ServingTrainingArtifactError, match="build_receipt:SCHEMA_MISMATCH"):
        artifacts.load()


def test_artifact_file_hash_mismatch_is_rejected(artifacts: ArtifactFixture) -> None:
    artifacts.dataset_path.write_bytes(artifacts.dataset_path.read_bytes() + b" ")

    with pytest.raises(
        ServingTrainingArtifactError, match="ARTIFACT_FILE_SHA256_BINDING_MISMATCH"
    ):
        artifacts.load()


def test_nonfinite_json_and_duplicate_json_keys_are_rejected(
    artifacts: ArtifactFixture,
) -> None:
    dataset_bytes = artifacts.dataset_path.read_bytes()
    artifacts.dataset_path.write_bytes(dataset_bytes.replace(b'"rows": [', b'"x": NaN, "rows": [', 1))
    with pytest.raises(ServingTrainingArtifactError, match="STRICT_JSON_REQUIRED"):
        artifacts.load()

    artifacts.write()
    dataset_bytes = artifacts.dataset_path.read_bytes()
    artifacts.dataset_path.write_bytes(
        dataset_bytes.replace(
            b'"schema_version":',
            b'"schema_version": "duplicate", "schema_version":',
            1,
        )
    )
    with pytest.raises(ServingTrainingArtifactError, match="STRICT_JSON_REQUIRED"):
        artifacts.load()


def test_symlinked_artifact_is_rejected(
    artifacts: ArtifactFixture, tmp_path: Path
) -> None:
    target = tmp_path / "receipt-target.json"
    artifacts.receipt_path.replace(target)
    os.symlink(target, artifacts.receipt_path)

    with pytest.raises(ServingTrainingArtifactError, match="REGULAR_FILE_REQUIRED"):
        artifacts.load()


def _candidate_row(artifacts: ArtifactFixture) -> dict[str, Any]:
    return next(
        row
        for row in artifacts.dataset["rows"]
        if row["source_kind"] == "CANDIDATE_DECISION_OUTCOME_V2"
    )


def _gen5_row(artifacts: ArtifactFixture) -> dict[str, Any]:
    return next(
        row
        for row in artifacts.dataset["rows"]
        if row["source_kind"] == "GEN5_AUTHENTICATED_PROFILED_OBSERVATION"
    )


def _rehash_candidate_lineage(row: dict[str, Any]) -> None:
    derivation = row["directional_label_derivation"]
    derivation_material = {
        key: value for key, value in derivation.items() if key != "derivation_sha256"
    }
    derivation_sha = canonical_sha256(derivation_material)
    derivation["derivation_sha256"] = derivation_sha
    row["cost_evidence_sha256"] = derivation_sha
    label_at = datetime.fromisoformat(row["label_available_at"].replace("Z", "+00:00"))
    source_hashes = row["source_hashes"]
    hedge = row.get("hedge_label_derivation")
    hedge_sha: str | None = None
    if isinstance(hedge, dict):
        hedge_material = {
            key: value for key, value in hedge.items() if key != "derivation_sha256"
        }
        hedge_sha = canonical_sha256(hedge_material)
        hedge["derivation_sha256"] = hedge_sha
    label_material = {
        "schema_version": (
            "candidate_outcome_training_label_binding_v3"
            if hedge_sha is not None
            else "candidate_outcome_training_label_binding_v2"
        ),
        "candidate_id": row["candidate_id"],
        "decision_snapshot_sha256": source_hashes["decision_snapshot_sha256"],
        "matured_labels_sha256": source_hashes["matured_labels_sha256"],
        "label_record_available_at_ms": int(label_at.timestamp() * 1_000),
        "directional_label_derivation_sha256": derivation_sha,
        "label_source_receipt_sha256s": row["source_receipt_sha256s"],
        "future_labels_not_in_feature_tensor": True,
        "counterfactual_counts_as_realized_paper_profit": False,
    }
    if hedge_sha is not None:
        label_material["hedge_label_derivation_sha256"] = hedge_sha
    label_sha = canonical_sha256(label_material)
    row["label_binding_sha256"] = label_sha
    source_hashes["label_binding_sha256"] = label_sha


def test_historical_candidate_row_without_hedge_binding_remains_loadable(
    artifacts: ArtifactFixture,
) -> None:
    row = _candidate_row(artifacts)
    row.pop("hedge_label_derivation")
    _rehash_candidate_lineage(row)
    artifacts.write(repin_receipt=True)

    dataset, *_ = artifacts.load()

    loaded = next(
        item
        for item in dataset["rows"]
        if item["source_kind"] == "CANDIDATE_DECISION_OUTCOME_V2"
    )
    assert "hedge_label_derivation" not in loaded


@pytest.mark.parametrize(
    "mutation",
    (
        "contract",
        "advantage",
        "target",
        "scenario_identity",
        "unhedged_directional_identity",
        "coherent_pnl_shift",
        "cross_sectional_claim",
        "accounting_claim",
    ),
)
def test_coherently_rehashed_hedge_semantic_forgery_is_rejected(
    artifacts: ArtifactFixture,
    mutation: str,
) -> None:
    row = _candidate_row(artifacts)
    hedge = row["hedge_label_derivation"]
    if mutation == "contract":
        hedge["hedge_contract"] = "UNDECLARED_DYNAMIC_HEDGE"
    elif mutation == "advantage":
        hedge["hedge_advantage_bps"] += 1.0
    elif mutation == "target":
        hedge["target_hedge_vs_unhedged"] = not hedge[
            "target_hedge_vs_unhedged"
        ]
    elif mutation == "scenario_identity":
        hedge["hedged_scenario_sha256"] = hedge["unhedged_scenario_sha256"]
    elif mutation == "unhedged_directional_identity":
        hedge["unhedged_scenario_sha256"] = "d" * 64
    elif mutation == "coherent_pnl_shift":
        hedge["unhedged_after_cost_pnl_bps"] += 100.0
        hedge["hedged_after_cost_pnl_bps"] += 100.0
        hedge["hedge_advantage_bps"] = (
            hedge["hedged_after_cost_pnl_bps"]
            - hedge["unhedged_after_cost_pnl_bps"]
        )
        hedge["target_hedge_vs_unhedged"] = hedge["hedge_advantage_bps"] > 0.0
        hedge["hedged_after_cost_positive"] = (
            hedge["hedged_after_cost_pnl_bps"] > 0.0
        )
    elif mutation == "cross_sectional_claim":
        hedge["cross_sectional_relative_value_label_present"] = True
    else:
        hedge["actual_accounting_effect"] = True
    _rehash_candidate_lineage(row)
    artifacts.write(repin_receipt=True)

    with pytest.raises(
        ServingTrainingArtifactError,
        match="HEDGE_LABEL_DERIVATION_MISMATCH",
    ):
        artifacts.load()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.__setitem__("label_binding_sha256", "c" * 64),
        lambda row: row["source_hashes"].__setitem__(
            "label_binding_sha256", "c" * 64
        ),
        lambda row: row["source_hashes"].__setitem__(
            "candidate_archive_terminal_chain_sha256", "c" * 64
        ),
        lambda row: (
            row.__setitem__("cost_evidence_sha256", "c" * 64),
            row["directional_label_derivation"].__setitem__(
                "derivation_sha256", "c" * 64
            ),
        ),
        lambda row: row.__setitem__("source_hashes", {"x": "c" * 64}),
    ],
)
def test_rotated_receipt_cannot_authenticate_forged_candidate_lineage(
    artifacts: ArtifactFixture,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    mutate(_candidate_row(artifacts))
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError):
        artifacts.load()


@pytest.mark.parametrize("mutation", ["action_method_mismatch", "scenario_cardinality"])
def test_rotated_receipt_cannot_authenticate_derivation_semantic_mismatch(
    artifacts: ArtifactFixture,
    mutation: str,
) -> None:
    row = _candidate_row(artifacts)
    derivation = row["directional_label_derivation"]
    if mutation == "action_method_mismatch":
        derivation["proposed_action"] = "HOLD"
    else:
        derivation["unhedged_scenario_sha256s"].append("c" * 64)
    _rehash_candidate_lineage(row)
    artifacts.write(repin_receipt=True)

    with pytest.raises(
        ServingTrainingArtifactError,
        match="DIRECTIONAL_LABEL_DERIVATION_SEMANTICS_MISMATCH",
    ):
        artifacts.load()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("feature_group_count", False),
        ("feature_group_count", 999_999),
        ("reused_feature_group_count", 999_999),
        ("maximum_rows_per_feature_group", 999_999),
        ("embargo_groups", 999_999),
        ("candidate_rejection_count", False),
    ],
)
def test_rotated_receipt_cannot_authenticate_forged_manifest_counters(
    artifacts: ArtifactFixture,
    field: str,
    invalid: object,
) -> None:
    artifacts.manifest[field] = invalid
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError):
        artifacts.load()


@pytest.mark.parametrize("field", ["purge_policy", "split_boundaries"])
def test_rotated_receipt_requires_exact_purge_and_split_contract(
    artifacts: ArtifactFixture,
    field: str,
) -> None:
    artifacts.manifest[field] = {} if field == "split_boundaries" else ""
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError):
        artifacts.load()


def test_rotated_receipt_requires_exact_source_high_watermark(
    artifacts: ArtifactFixture,
) -> None:
    artifacts.manifest["source_high_watermark"][
        "candidate_archive_latest_decision_only_count"
    ] = 999_999
    artifacts.write(repin_receipt=True)
    with pytest.raises(ServingTrainingArtifactError, match="HIGH_WATERMARK"):
        artifacts.load()


def test_source_high_watermark_counters_reject_bool(
    artifacts: ArtifactFixture,
) -> None:
    artifacts.manifest["source_high_watermark"][
        "candidate_archive_latest_decision_only_count"
    ] = False
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError, match="NONNEGATIVE_INT_REQUIRED"):
        artifacts.load()

    artifacts.manifest["source_high_watermark"][
        "candidate_archive_latest_decision_only_count"
    ] = 0
    artifacts.manifest["source_high_watermark"]["base_dataset_sha256"] = "c" * 64
    artifacts.write(repin_receipt=True)
    with pytest.raises(ServingTrainingArtifactError, match="HIGH_WATERMARK"):
        artifacts.load()


def test_rotated_receipt_requires_exact_nested_archive_schema(
    artifacts: ArtifactFixture,
) -> None:
    artifacts.receipt["candidate_archive_verification"]["unexpected"] = True
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError, match="ARCHIVE_RECEIPT"):
        artifacts.load()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("required_feature_missing_rate", False),
        ("activation_block_reason", None),
    ],
)
def test_rotated_receipt_requires_exact_parity_semantics(
    artifacts: ArtifactFixture,
    field: str,
    invalid: object,
) -> None:
    artifacts.parity[field] = invalid
    artifacts.write(repin_receipt=True)

    with pytest.raises(ServingTrainingArtifactError, match="PARITY"):
        artifacts.load()


def test_gen5_rows_are_exactly_bound_to_the_pinned_base_dataset(
    artifacts: ArtifactFixture,
) -> None:
    _gen5_row(artifacts)["cost_evidence_sha256"] = "c" * 64
    artifacts.write(repin_receipt=True)

    with pytest.raises(
        ServingTrainingArtifactError, match="DIFFERS_FROM_PINNED_BASE_DATASET"
    ):
        artifacts.load()
