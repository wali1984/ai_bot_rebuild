"""Versioned canonical runtime contracts (V2 convergence).

One schema per artifact class, deterministic canonical hashing, and explicit
temporal contracts. These are the single source of truth shared by producers,
the model registry, the canonical serving runtime, and the paper loop — so no
lane maintains a private/reduced schema.

Only the contracts required by the model registry + canonical serving runtime are
implemented here first (CheckpointBundleV2, ModelActivationReceiptV2, and the
PredictionRecordV2 policy-field set). The evidence-envelope contracts
(Feature/Cost/Microstructure) are enforced today by the existing canonical
builders (score_market_state, build_exact_cost_provenance,
build_microstructure_trust_evidence) and are formalized here incrementally.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

RUNTIME_CONTRACTS_SCHEMA_NAMESPACE = "v2_runtime_contracts"


def canonical_sha256(payload: Any) -> str:
    """Deterministic content hash: sorted keys, compact separators, no NaN."""
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


# Supported checkpoint classifications. All share the SAME serving runtime and
# PredictionRecordV2 schema; only policy fields (below) differ.
CHECKPOINT_CLASSIFICATIONS = (
    "PAPER_PROVISIONAL",
    "PAPER_APPROVED",
    "STRICT_CANDIDATE",
    "STRICT_CHAMPION",
)

# Policy field defaults per classification. Never-live is invariant for paper.
CLASSIFICATION_POLICY: dict[str, dict[str, Any]] = {
    "PAPER_PROVISIONAL": {
        "paper_eligible": True, "strict_eligible": False,
        "checkpoint_promotable": False, "live_eligible": False,
    },
    "PAPER_APPROVED": {
        "paper_eligible": True, "strict_eligible": False,
        "checkpoint_promotable": False, "live_eligible": False,
    },
    "STRICT_CANDIDATE": {
        "paper_eligible": True, "strict_eligible": True,
        "checkpoint_promotable": True, "live_eligible": False,
    },
    "STRICT_CHAMPION": {
        "paper_eligible": True, "strict_eligible": True,
        "checkpoint_promotable": True, "live_eligible": False,
    },
}


@dataclass(frozen=True)
class CheckpointBundleV2:
    """Immutable, self-describing checkpoint bundle — the only unit the registry
    activates and the serving runtime loads."""

    checkpoint_id: str
    checkpoint_classification: str
    model_architecture: str
    model_source: str
    training_manifest_id: str
    training_manifest_sha256: str
    feature_abi_sha256: str
    ordered_feature_names: tuple[str, ...]
    input_width: int
    action_labels: tuple[str, ...]
    weight_file_path: str
    weight_sha256: str
    model_parameter_fingerprint: str
    calibration_state: dict[str, Any]
    calibration_state_sha256: str
    training_rows: int
    validation_rows: int
    holdout_rows: int
    optimizer_steps: int
    training_metrics: dict[str, Any]
    generated_at: str
    serving_feature_builder_sha: str = ""
    training_feature_builder_sha: str = ""
    schema_version: str = "checkpoint_bundle_v2"

    @property
    def paper_eligible(self) -> bool:
        return bool(CLASSIFICATION_POLICY.get(self.checkpoint_classification, {}).get("paper_eligible"))

    @property
    def strict_eligible(self) -> bool:
        return bool(CLASSIFICATION_POLICY.get(self.checkpoint_classification, {}).get("strict_eligible"))

    @property
    def checkpoint_promotable(self) -> bool:
        return bool(
            CLASSIFICATION_POLICY.get(self.checkpoint_classification, {}).get("checkpoint_promotable")
        )

    @property
    def live_eligible(self) -> bool:
        return False  # invariant: no bundle is live-eligible in this pass

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ordered_feature_names"] = list(self.ordered_feature_names)
        d["action_labels"] = list(self.action_labels)
        d["paper_eligible"] = self.paper_eligible
        d["strict_eligible"] = self.strict_eligible
        d["checkpoint_promotable"] = self.checkpoint_promotable
        d["live_eligible"] = self.live_eligible
        d["content_sha256"] = self.content_sha256()
        return d

    def content_sha256(self) -> str:
        material = asdict(self)
        material["ordered_feature_names"] = list(self.ordered_feature_names)
        material["action_labels"] = list(self.action_labels)
        return canonical_sha256(material)

    def validate(self) -> list[str]:
        reasons: list[str] = []
        if self.checkpoint_classification not in CHECKPOINT_CLASSIFICATIONS:
            reasons.append("CHECKPOINT_CLASSIFICATION_INVALID")
        if len(self.ordered_feature_names) != self.input_width:
            reasons.append("INPUT_WIDTH_FEATURE_COUNT_MISMATCH")
        if not (len(self.weight_sha256) == 64 and self.weight_sha256.isalnum()):
            reasons.append("WEIGHT_SHA256_INVALID")
        if self.calibration_state.get("fitted") is not True:
            reasons.append("CALIBRATION_NOT_FITTED")
        if canonical_sha256(self.calibration_state) != self.calibration_state_sha256:
            reasons.append("CALIBRATION_STATE_SHA_MISMATCH")
        if self.training_rows < 80 or self.validation_rows < 10 or self.holdout_rows < 10:
            reasons.append("SPLIT_SIZE_BELOW_MINIMUM")
        if self.optimizer_steps < 100:
            reasons.append("OPTIMIZER_STEPS_BELOW_MINIMUM")
        return reasons


@dataclass(frozen=True)
class ModelActivationReceiptV2:
    """Immutable receipt for a single atomic model-registry activation."""

    receipt_id: str
    registry_key: str
    registry_generation: int
    previous_generation: int
    checkpoint_id: str
    checkpoint_bundle_sha256: str
    feature_abi_sha256: str
    activated_at: str
    activated_by: str
    activation_reason: str
    previous_checkpoint_id: str | None
    rollback_checkpoint_id: str | None
    serving_smoke_result: dict[str, Any]
    health_state: str
    paper_only: bool = True
    live_eligible: bool = False
    schema_version: str = "model_activation_receipt_v2"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["content_sha256"] = canonical_sha256(asdict(self))
        return d


# PredictionRecordV2 policy/lineage field set every serving publication must carry
# (in addition to the canonical build_prediction_payload output). No reduced schema.
PREDICTION_RECORD_V2_REQUIRED_POLICY_FIELDS = (
    "serving_runtime_release_sha",
    "active_model_registry_generation",
    "checkpoint_classification",
    "paper_strategy_cohort_id",
    "feature_evidence_sha256",
    "cost_evidence_sha256",
    "microstructure_evidence_sha256",
)


def prediction_record_v2_policy_fields_present(payload: Mapping[str, Any]) -> list[str]:
    """Return the required PredictionRecordV2 policy fields missing from a payload."""
    return [f for f in PREDICTION_RECORD_V2_REQUIRED_POLICY_FIELDS if payload.get(f) in (None, "")]
