"""Immutable, authority-free hypothesis binding for profiled local research.

The factory joins one authenticated raw-inference V2 receipt to one exact
paper/research causal-cost artifact.  The decision reference is the
decision-time order-book mid rederived by the cost factory; no candle close,
mutable current price, fallback cost, or caller-supplied price is accepted.

This artifact is research evidence only.  It grants no trainer, calibration,
checkpoint, model, prediction, serving, PAPER, live, exchange, deployment,
order, execution, or runtime authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import struct
from dataclasses import dataclass, field
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.locally_authenticated_profiled_research_inference_v1 import (  # noqa: E501
    LocallyAuthenticatedProfiledResearchInferenceV1Error,
    LocallyAuthenticatedProfiledResearchRawInferenceV2,
    revalidate_locally_authenticated_profiled_research_raw_inference_v2,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_evidence_v1 import (  # noqa: E501
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
    PaperResearchCausalCostEvidenceV1Error,
    PaperResearchCausalCostEvidenceV1Result,
)

PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_v1"
)
PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION: Final = (
    "LOCAL_PROFILED_RESEARCH_IMMUTABLE_COST_BOUND_HYPOTHESIS_NO_AUTHORITY_V1"
)
PROFILED_RESEARCH_DECISION_REFERENCE_V1_SCHEMA_VERSION: Final = (
    "profiled_research_authenticated_decision_reference_v1"
)
PROFILED_RESEARCH_COST_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_research_causal_cost_binding_v1"
)
PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE: Final = (
    "AUTHENTICATED_CAUSAL_COST_ORDERBOOK_DEPTH_CAS_MID"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
# Serialization resource bound only; not a market or admission threshold.
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024

_AUTHORIZATION: Final = {
    "consumer_eligible": False,
    "trainer_admission_authorized": False,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}

_DURABILITY_STATUS: Final = {
    "status": (
        "QUARANTINED_DURABLE_COMMITMENT_AND_PORTABLE_SOURCE_CLOSURE_REQUIRED"
    ),
    "durable_ex_ante_commit_receipt_present": False,
    "pending_hypothesis_index_registered": False,
    "portable_cost_source_closure_complete": False,
    "restart_reopen_supported": False,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
}

_COST_AUTHORIZATION: Final = {
    "trainer_admission_authorized": False,
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}


class ProfiledResearchShadowHypothesisV1Error(RuntimeError):
    """Stable, payload-safe base error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProfiledResearchShadowHypothesisV1ValidationError(
    ProfiledResearchShadowHypothesisV1Error
):
    """Supplied inference, cost, store, or identity is invalid."""


class ProfiledResearchShadowHypothesisV1IntegrityError(
    ProfiledResearchShadowHypothesisV1Error
):
    """Factory result or retained immutable evidence failed revalidation."""


def _validation(reason: str) -> NoReturn:
    raise ProfiledResearchShadowHypothesisV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise ProfiledResearchShadowHypothesisV1IntegrityError(reason) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation(reason)
    if not encoded or len(encoded) > _MAX_ARTIFACT_BYTES:
        _validation(reason)
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            value,
            reason="PROFILED_RESEARCH_HYPOTHESIS_CANONICAL_JSON_INVALID",
        )
    ).hexdigest()


def _parse_exact_object(payload: bytes, *, reason: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        _integrity(reason)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _integrity(reason)
            result[key] = value
        return result

    def reject_constant(_: str) -> NoReturn:
        _integrity(reason)

    try:
        parsed = json.loads(
            payload.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except ProfiledResearchShadowHypothesisV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _integrity(reason)
    if type(parsed) is not dict:
        _integrity(reason)
    parsed = cast(dict[str, Any], parsed)
    try:
        canonical = _canonical_bytes(parsed, reason=reason)
    except ProfiledResearchShadowHypothesisV1ValidationError as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(reason) from exc
    if not hmac.compare_digest(
        canonical,
        payload,
    ):
        _integrity(reason)
    return parsed


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _valid_address(address: object, *, sha256: str, byte_count: int) -> bool:
    return (
        type(address) is SourcePayloadAddress
        and address.schema_version == SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        and address.payload_sha256 == sha256
        and address.payload_byte_count == byte_count
        and type(address.relative_path) is str
        and address.relative_path.endswith(f"/{sha256[:2]}/{sha256}")
    )


def _finite(value: object, *, reason: str, positive: bool = False) -> float:
    if type(value) not in {int, float}:
        _validation(reason)
    parsed = float(cast(int | float, value))
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        _validation(reason)
    return parsed


def _float32(value: float) -> float:
    try:
        return float(struct.unpack("!f", struct.pack("!f", value))[0])
    except (OverflowError, struct.error):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_COST_FLOAT32_INVALID")


def _revalidated_raw_payload(
    raw_inference: LocallyAuthenticatedProfiledResearchRawInferenceV2,
) -> dict[str, Any]:
    try:
        return revalidate_locally_authenticated_profiled_research_raw_inference_v2(
            raw_inference
        )
    except LocallyAuthenticatedProfiledResearchInferenceV1Error as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_RAW_INFERENCE_REVALIDATION_FAILED:"
            f"{exc.reasons[0] if exc.reasons else 'UNKNOWN'}"
        ) from exc


def _revalidated_cost(
    cost_evidence: PaperResearchCausalCostEvidenceV1Result,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    try:
        contract = cost_evidence.contract
        receipts = cost_evidence.ordered_receipts
    except PaperResearchCausalCostEvidenceV1Error as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_COST_REVALIDATION_FAILED:"
            f"{exc.reason}"
        ) from exc
    return contract, receipts


def _cost_and_reference_bindings(
    *,
    raw_payload: dict[str, Any],
    cost_evidence: PaperResearchCausalCostEvidenceV1Result,
    cost_contract: dict[str, Any],
    receipts: tuple[dict[str, Any], ...],
    copied_cost_address: SourcePayloadAddress,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered_values = cost_evidence.ordered_values
    ordered_receipt_sha256s = cost_evidence.ordered_receipt_sha256s
    if (
        cost_contract.get("schema_version")
        != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION
        or cost_contract.get("evidence_classification")
        != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION
        or cost_contract.get("downstream_status")
        != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS
        or cost_contract.get("symbol") != raw_payload.get("symbol")
        or cost_contract.get("feature_snapshot_identity")
        != raw_payload.get("durable_snapshot_id")
        or cost_contract.get("decision_time")
        != raw_payload.get("source_decision_time")
        or cost_contract.get("counterfactual_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or cost_contract.get("ordered_feature_names")
        != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or tuple(cost_contract.get("ordered_values") or ()) != ordered_values
        or tuple(cost_contract.get("ordered_receipt_sha256s") or ())
        != ordered_receipt_sha256s
        or len(ordered_values) != 4
        or len(ordered_receipt_sha256s) != 4
        or len(receipts) != 4
        or cost_contract.get("authorization") != _COST_AUTHORIZATION
        or cost_contract.get("research_cost_components_complete") is not True
        or cost_contract.get("no_static_fallback_or_floor") is not True
        or cost_contract.get("account_specific_commission_authenticated") is not False
        or cost_contract.get("external_monotonic_fee_revision_verified") is not False
        or cost_contract.get("profiled_account_lane_compatible") is not False
        or cost_contract.get("optional_provider_dependencies") != []
    ):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_COST_SCOPE_OR_IDENTITY_INVALID")
    resolved_values = tuple(
        _finite(
            value,
            reason="PROFILED_RESEARCH_HYPOTHESIS_COST_VALUE_INVALID",
        )
        for value in ordered_values
    )
    if any(value < 0.0 for value in resolved_values[:3]):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_COST_VALUE_INVALID")
    if any(
        type(receipt) is not dict
        or receipt.get("feature_name") != CAUSAL_COST_ORDERED_FEATURE_NAMES[index]
        or receipt.get("receipt_sha256") != ordered_receipt_sha256s[index]
        or receipt.get("authorization") != _COST_AUTHORIZATION
        for index, receipt in enumerate(receipts)
    ):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_COST_RECEIPT_INVALID")

    spread_receipt = receipts[1]
    derivation_material = spread_receipt.get("derivation_material")
    exact_bindings = spread_receipt.get("exact_bindings")
    child_bindings = spread_receipt.get("child_read_bindings")
    if (
        type(derivation_material) is not dict
        or type(exact_bindings) is not dict
        or type(child_bindings) is not list
    ):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
    exact_rederivation = derivation_material.get("exact_rederivation")
    if type(exact_rederivation) is not dict:
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
    best_bid = _finite(
        exact_rederivation.get("best_bid"),
        reason="PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID",
        positive=True,
    )
    best_ask = _finite(
        exact_rederivation.get("best_ask"),
        reason="PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID",
        positive=True,
    )
    mid = _finite(
        exact_rederivation.get("mid"),
        reason="PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID",
        positive=True,
    )
    expected_notional = _finite(
        exact_rederivation.get("expected_notional_usd"),
        reason="PROFILED_RESEARCH_HYPOTHESIS_EXPECTED_NOTIONAL_INVALID",
        positive=True,
    )
    full_spread_hex = exact_rederivation.get("full_spread_bps_float64_hex")
    try:
        full_spread = float.fromhex(full_spread_hex)
    except (TypeError, ValueError):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
    expected_spread = (best_ask - best_bid) / mid * 10_000.0
    notional_source = cost_contract.get("notional_source")
    if (
        best_ask <= best_bid
        or mid != (best_bid + best_ask) / 2.0
        or full_spread != expected_spread
        or _float32(full_spread) != resolved_values[1]
        or type(notional_source) is not dict
        or notional_source.get("expected_notional_usd") != expected_notional
        or exact_bindings.get("symbol") != raw_payload.get("symbol")
        or exact_bindings.get("feature_snapshot_identity")
        != raw_payload.get("durable_snapshot_id")
        or exact_bindings.get("decision_time")
        != raw_payload.get("source_decision_time")
        or exact_bindings.get("counterfactual_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or exact_bindings.get("expected_notional_usd") != expected_notional
    ):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
    normalized_child_bindings: list[dict[str, str]] = []
    expected_child_roles = ("orderbook_depth", "orderbook_features")
    if len(child_bindings) != len(expected_child_roles):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
    for index, item in enumerate(child_bindings):
        if (
            type(item) is not dict
            or set(item) != {"input_role", "receipt_sha256"}
            or item.get("input_role") != expected_child_roles[index]
        ):
            _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")
        normalized_child_bindings.append(
            {
                "input_role": cast(str, item["input_role"]),
                "receipt_sha256": cast(str, item["receipt_sha256"]),
            }
        )
    child_receipt_sha256s = [
        item["receipt_sha256"] for item in normalized_child_bindings
    ]
    if (
        len(child_receipt_sha256s) != 2
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in child_receipt_sha256s
        )
    ):
        _validation("PROFILED_RESEARCH_HYPOTHESIS_DECISION_REFERENCE_INVALID")

    cost_binding = {
        "schema_version": PROFILED_RESEARCH_COST_BINDING_V1_SCHEMA_VERSION,
        "artifact_sha256": cost_evidence.artifact_sha256,
        "artifact_byte_count": len(cost_evidence.artifact_json.encode("ascii")),
        "artifact_cas_address": _address_mapping(copied_cost_address),
        "evidence_id": cost_contract["evidence_id"],
        "contract_material_sha256": cost_contract["contract_material_sha256"],
        "symbol": cost_contract["symbol"],
        "feature_snapshot_identity": cost_contract["feature_snapshot_identity"],
        "decision_time": cost_contract["decision_time"],
        "counterfactual_holding_horizon_seconds": (
            CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ),
        "ordered_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "ordered_values": list(resolved_values),
        "ordered_receipt_sha256s": list(ordered_receipt_sha256s),
        "fee_source_authenticity_status": cost_contract[
            "fee_source_authenticity_status"
        ],
        "market_source_authenticity_status": cost_contract[
            "market_source_authenticity_status"
        ],
        "account_specific_commission_authenticated": False,
        "research_only": True,
    }
    decision_reference = {
        "schema_version": (
            PROFILED_RESEARCH_DECISION_REFERENCE_V1_SCHEMA_VERSION
        ),
        "source": PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE,
        "symbol": raw_payload["symbol"],
        "feature_snapshot_identity": raw_payload["durable_snapshot_id"],
        "decision_time": raw_payload["source_decision_time"],
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "expected_notional_usd": expected_notional,
        "spread_receipt_sha256": spread_receipt["receipt_sha256"],
        "orderbook_child_read_bindings": normalized_child_bindings,
        "exact_rederivation_sha256": _sha256(exact_rederivation),
        "caller_supplied_price_used": False,
        "unfinished_candle_price_used": False,
    }
    return cost_binding, decision_reference


def _contract_material(
    *,
    raw_payload: dict[str, Any],
    cost_evidence: PaperResearchCausalCostEvidenceV1Result,
    cost_contract: dict[str, Any],
    receipts: tuple[dict[str, Any], ...],
    copied_cost_address: SourcePayloadAddress,
) -> dict[str, Any]:
    cost_binding, decision_reference = _cost_and_reference_bindings(
        raw_payload=raw_payload,
        cost_evidence=cost_evidence,
        cost_contract=cost_contract,
        receipts=receipts,
        copied_cost_address=copied_cost_address,
    )
    return {
        "schema_version": PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION,
        "raw_inference_payload": raw_payload,
        "raw_inference_binding_sha256": raw_payload["hypothesis_binding_sha256"],
        "cost_evidence_binding": cost_binding,
        "decision_reference_binding": decision_reference,
        "counterfactual_holding_horizon_seconds": (
            CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ),
        "durability_status": dict(_DURABILITY_STATUS),
        "authorization": dict(_AUTHORIZATION),
        "local_research_non_promotable": True,
    }


def _factory_seal(
    *,
    artifact_address: SourcePayloadAddress,
    artifact_bytes: bytes,
    copied_cost_address: SourcePayloadAddress,
    store: ImmutableSourcePayloadStore,
    raw_inference: LocallyAuthenticatedProfiledResearchRawInferenceV2,
    cost_evidence: PaperResearchCausalCostEvidenceV1Result,
) -> str:
    material = {
        "domain": "v2/native-trainer/profiled-research-shadow-hypothesis-result/v1",
        "artifact_address": _address_mapping(artifact_address),
        "artifact_retained_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "artifact_retained_byte_count": len(artifact_bytes),
        "copied_cost_address": _address_mapping(copied_cost_address),
        "store_process_identity": id(store),
        "raw_inference_process_identity": id(raw_inference),
        "cost_evidence_process_identity": id(cost_evidence),
    }
    return hmac.new(
        _FACTORY_SEAL_KEY,
        _canonical_bytes(
            material,
            reason="PROFILED_RESEARCH_HYPOTHESIS_FACTORY_SEAL_INVALID",
        ),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfiledResearchShadowHypothesisArtifactV1:
    """Factory-sealed CAS artifact with fresh upstream revalidation."""

    artifact_sha256: str
    artifact_byte_count: int
    artifact_json: str = field(repr=False)
    artifact_address: SourcePayloadAddress
    raw_inference_binding_sha256: str
    cost_evidence_artifact_sha256: str
    hypothesis_material_sha256: str
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _artifact_bytes: bytes = field(repr=False, compare=False)
    _copied_cost_address: SourcePayloadAddress = field(repr=False, compare=False)
    _raw_inference: LocallyAuthenticatedProfiledResearchRawInferenceV2 = field(
        repr=False,
        compare=False,
    )
    _cost_evidence: PaperResearchCausalCostEvidenceV1Result = field(
        repr=False,
        compare=False,
    )
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def contract(self) -> dict[str, Any]:
        return _validated_result(self)


def _validated_result(
    result: ProfiledResearchShadowHypothesisArtifactV1,
) -> dict[str, Any]:
    if (
        type(result) is not ProfiledResearchShadowHypothesisArtifactV1
        or result._construction_token is not _CONSTRUCTION_TOKEN
        or type(result._store) is not ImmutableSourcePayloadStore
        or type(result._artifact_bytes) is not bytes
        or type(result.artifact_address) is not SourcePayloadAddress
        or type(result._copied_cost_address) is not SourcePayloadAddress
        or type(result._raw_inference)
        is not LocallyAuthenticatedProfiledResearchRawInferenceV2
        or type(result._cost_evidence) is not PaperResearchCausalCostEvidenceV1Result
        or type(result._factory_seal) is not str
        or _SHA256_RE.fullmatch(result._factory_seal) is None
    ):
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_FACTORY_CONSTRUCTION_REQUIRED")
    expected_seal = _factory_seal(
        artifact_address=result.artifact_address,
        artifact_bytes=result._artifact_bytes,
        copied_cost_address=result._copied_cost_address,
        store=result._store,
        raw_inference=result._raw_inference,
        cost_evidence=result._cost_evidence,
    )
    if not hmac.compare_digest(result._factory_seal, expected_seal):
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_FACTORY_SEAL_INVALID")
    artifact_sha256 = hashlib.sha256(result._artifact_bytes).hexdigest()
    try:
        retained_json_bytes = result.artifact_json.encode("ascii", errors="strict")
    except (AttributeError, UnicodeError) as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_ARTIFACT_BINDING_INVALID"
        ) from exc
    if (
        artifact_sha256 != result.artifact_sha256
        or result.artifact_byte_count != len(result._artifact_bytes)
        or not _valid_address(
            result.artifact_address,
            sha256=artifact_sha256,
            byte_count=len(result._artifact_bytes),
        )
        or retained_json_bytes != result._artifact_bytes
    ):
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_ARTIFACT_BINDING_INVALID")
    try:
        artifact_readback = result._store.get(
            artifact_sha256,
            expected_byte_count=len(result._artifact_bytes),
        )
        cost_bytes = result._cost_evidence.artifact_json.encode("ascii")
        cost_readback = result._store.get(
            result._copied_cost_address.payload_sha256,
            expected_byte_count=result._copied_cost_address.payload_byte_count,
        )
    except (SourcePayloadStoreError, UnicodeError) as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_CAS_READBACK_FAILED"
        ) from exc
    if (
        not hmac.compare_digest(artifact_readback, result._artifact_bytes)
        or not hmac.compare_digest(cost_readback, cost_bytes)
        or not _valid_address(
            result._copied_cost_address,
            sha256=result._cost_evidence.artifact_sha256,
            byte_count=len(cost_bytes),
        )
    ):
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_CAS_READBACK_MISMATCH")

    raw_payload = _revalidated_raw_payload(result._raw_inference)
    cost_contract, receipts = _revalidated_cost(result._cost_evidence)
    try:
        expected_material = _contract_material(
            raw_payload=raw_payload,
            cost_evidence=result._cost_evidence,
            cost_contract=cost_contract,
            receipts=receipts,
            copied_cost_address=result._copied_cost_address,
        )
    except ProfiledResearchShadowHypothesisV1ValidationError as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_UPSTREAM_BINDING_INVALID"
        ) from exc
    expected_material_sha256 = _sha256(expected_material)
    expected_contract = {
        **expected_material,
        "hypothesis_material_sha256": expected_material_sha256,
    }
    contract = _parse_exact_object(
        result._artifact_bytes,
        reason="PROFILED_RESEARCH_HYPOTHESIS_ARTIFACT_JSON_INVALID",
    )
    if (
        contract != expected_contract
        or result.raw_inference_binding_sha256
        != raw_payload["hypothesis_binding_sha256"]
        or result.cost_evidence_artifact_sha256
        != result._cost_evidence.artifact_sha256
        or result.hypothesis_material_sha256 != expected_material_sha256
        or contract.get("durability_status") != _DURABILITY_STATUS
        or contract.get("authorization") != _AUTHORIZATION
        or contract.get("local_research_non_promotable") is not True
    ):
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_CONTRACT_BINDING_INVALID")
    return contract


def build_profiled_research_shadow_hypothesis_v1(
    *,
    raw_inference: object,
    cost_evidence: object,
    store: object,
) -> ProfiledResearchShadowHypothesisArtifactV1:
    """Join exact raw inference and decision-time cost evidence in immutable CAS."""

    if type(raw_inference) is not LocallyAuthenticatedProfiledResearchRawInferenceV2:
        _validation("PROFILED_RESEARCH_HYPOTHESIS_RAW_INFERENCE_V2_REQUIRED")
    if type(cost_evidence) is not PaperResearchCausalCostEvidenceV1Result:
        _validation("PROFILED_RESEARCH_HYPOTHESIS_PAPER_COST_RESULT_REQUIRED")
    if type(store) is not ImmutableSourcePayloadStore:
        _validation("PROFILED_RESEARCH_HYPOTHESIS_IMMUTABLE_STORE_REQUIRED")
    raw = cast(LocallyAuthenticatedProfiledResearchRawInferenceV2, raw_inference)
    cost = cast(PaperResearchCausalCostEvidenceV1Result, cost_evidence)
    target_store = cast(ImmutableSourcePayloadStore, store)
    raw_payload = _revalidated_raw_payload(raw)
    cost_contract, receipts = _revalidated_cost(cost)
    material = _contract_material(
        raw_payload=raw_payload,
        cost_evidence=cost,
        cost_contract=cost_contract,
        receipts=receipts,
        copied_cost_address=cost.artifact_address,
    )
    material_sha256 = _sha256(material)
    contract = {
        **material,
        "hypothesis_material_sha256": material_sha256,
    }
    artifact_bytes = _canonical_bytes(
        contract,
        reason="PROFILED_RESEARCH_HYPOTHESIS_ARTIFACT_JSON_INVALID",
    )
    try:
        cost_bytes = cost.artifact_json.encode("ascii", errors="strict")
    except UnicodeError:
        _validation("PROFILED_RESEARCH_HYPOTHESIS_COST_ARTIFACT_INVALID")
    try:
        copied_cost_address = target_store.put(
            cost_bytes,
            expected_sha256=cost.artifact_sha256,
            expected_byte_count=len(cost_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_COST_CAS_COPY_FAILED"
        ) from exc
    if copied_cost_address != cost.artifact_address:
        _integrity("PROFILED_RESEARCH_HYPOTHESIS_COST_CAS_ADDRESS_MISMATCH")
    try:
        artifact_address = target_store.put(
            artifact_bytes,
            expected_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
            expected_byte_count=len(artifact_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchShadowHypothesisV1IntegrityError(
            "PROFILED_RESEARCH_HYPOTHESIS_ARTIFACT_CAS_FAILED"
        ) from exc
    result = ProfiledResearchShadowHypothesisArtifactV1(
        artifact_sha256=artifact_address.payload_sha256,
        artifact_byte_count=artifact_address.payload_byte_count,
        artifact_json=artifact_bytes.decode("ascii"),
        artifact_address=artifact_address,
        raw_inference_binding_sha256=raw.hypothesis_binding_sha256,
        cost_evidence_artifact_sha256=cost.artifact_sha256,
        hypothesis_material_sha256=material_sha256,
        _store=target_store,
        _artifact_bytes=artifact_bytes,
        _copied_cost_address=copied_cost_address,
        _raw_inference=raw,
        _cost_evidence=cost,
        _factory_seal=_factory_seal(
            artifact_address=artifact_address,
            artifact_bytes=artifact_bytes,
            copied_cost_address=copied_cost_address,
            store=target_store,
            raw_inference=raw,
            cost_evidence=cost,
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validated_result(result)
    return result


__all__ = (
    "PROFILED_RESEARCH_COST_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE",
    "PROFILED_RESEARCH_DECISION_REFERENCE_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION",
    "PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION",
    "ProfiledResearchShadowHypothesisArtifactV1",
    "ProfiledResearchShadowHypothesisV1Error",
    "ProfiledResearchShadowHypothesisV1IntegrityError",
    "ProfiledResearchShadowHypothesisV1ValidationError",
    "build_profiled_research_shadow_hypothesis_v1",
)
