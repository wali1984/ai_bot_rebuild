"""Factory-only authenticated 35+4 profiled training evidence.

This module converts one freshly revalidated, quarantined 35-slot profiled
model record and one exact :class:`CausalCostEvidenceV1Result` into a strict
39-slot ledger-v3 training candidate.  It is deliberately unwired: it does
not run a trainer, publish a prediction, trade, or grant execution authority.

The 35-slot parent and 39-slot child are a single append unit.  The append
helper holds the durable ledger's writer lease across the absence check and
the one ``append_snapshots([parent, child])`` call.  A parent that was already
committed alone therefore fails closed instead of being retrospectively
paired with evidence from another transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256,
    AuthenticatedOhlcvProfileTransformV1Result,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
    CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
    CausalCostEvidenceV1Error,
    CausalCostEvidenceV1Result,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotAppendResult,
    FeatureSnapshotLedgerError,
    FeatureSnapshotValidationError,
    FeatureSnapshotWriterLease,
    build_feature_snapshot_record,
    build_source_read_receipt,
    canonical_json,
    stable_sha256,
    validate_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
    LOGICAL_PROFILE_SELECTION_MASK_SHA256,
    ProfiledModelFeatureSnapshotRecordV1Error,
    validate_profiled_model_feature_snapshot_record_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    AUXILIARY_LABEL_ONLY_FEATURE_NAMES,
    PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION,
    PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES,
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION,
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY,
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION,
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS,
    PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT,
    PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES,
    PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256,
    PROFILED_TRAINING_PPO_CUTOFF_SEMANTICS,
    PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
)

PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION: Final = (
    "profiled_training_enrichment_record_v1"
)
PROFILED_TRAINING_ENRICHMENT_APPEND_V1_SCHEMA_VERSION: Final = (
    "profiled_training_enrichment_atomic_append_v1"
)
PROFILED_TRAINING_ENRICHMENT_RUNTIME_STATUS: Final = (
    "FACTORY_ONLY_UNWIRED_NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)

_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:" r"[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_AUXILIARY_VECTOR_HASH_DOMAIN = b"profiled_training_auxiliary_float32_v1\0"
_PAIR_TOKEN = object()
_APPEND_TOKEN = object()
_AUTHORIZATION = {
    "trainer_admission_authorized": True,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}


class ProfiledTrainingEnrichmentRecordV1Error(RuntimeError):
    """An enrichment input, immutable object, or atomic append failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingEnrichmentRecordV1Error(*reasons) from None


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return canonical, parsed


def _strict_json_copy(value: object, *, reason: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    try:
        encoded = canonical_json(value)
        parsed = json.loads(encoded)
    except (FeatureSnapshotValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(reason) from exc
    if type(parsed) is not dict:
        _fail(reason)
    return cast(dict[str, Any], parsed)


def _mapping(value: object, *, reason: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    return cast(dict[str, Any], value)


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _address(value: object, *, reason: str) -> dict[str, Any]:
    address = _mapping(value, reason=reason)
    if (
        set(address) != {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
        or not _valid_sha256(address.get("payload_sha256"))
        or type(address.get("payload_byte_count")) is not int
        or address["payload_byte_count"] <= 0
        or type(address.get("relative_path")) is not str
        or not address["relative_path"]
    ):
        _fail(reason)
    return address


def _derivation(*, producer: str, material: object) -> dict[str, Any]:
    material_sha = stable_sha256(material)
    return {
        "schema_version": FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
        "producer_id": producer,
        "producer_version": PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION,
        "transform_sha256": material_sha,
        "configuration_sha256": stable_sha256(
            {
                "schema_version": PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION,
                "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
                "causal_cost_implementation_sha256": (
                    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
                ),
            }
        ),
    }


def _materialize(
    store: object,
    payload: bytes,
    *,
    publish: bool,
    reason: str,
) -> SourcePayloadAddress:
    if type(store) is not ImmutableSourcePayloadStore or type(payload) is not bytes or not payload:
        _fail(reason)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        typed_store = cast(ImmutableSourcePayloadStore, store)
        address = (
            typed_store.put(
                payload,
                expected_sha256=digest,
                expected_byte_count=len(payload),
            )
            if publish
            else typed_store.verify(digest, expected_byte_count=len(payload))
        )
        readback = typed_store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(reason) from exc
    if not hmac.compare_digest(readback, payload):
        _fail(reason)
    return address


def _copy_materialized_payload(
    *,
    source_store: object,
    target_store: object,
    source_address: Mapping[str, Any],
    publish: bool,
    reason: str,
) -> SourcePayloadAddress:
    if type(source_store) is not ImmutableSourcePayloadStore:
        _fail(reason)
    digest = source_address.get("payload_sha256")
    byte_count = source_address.get("payload_byte_count")
    if not _valid_sha256(digest) or type(byte_count) is not int or byte_count <= 0:
        _fail(reason)
    try:
        payload = cast(ImmutableSourcePayloadStore, source_store).get(
            cast(str, digest),
            expected_byte_count=byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(reason) from exc
    if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != digest:
        _fail(reason)
    return _materialize(target_store, payload, publish=publish, reason=reason)


def _auxiliary_values_sha256(values: tuple[float, ...]) -> str:
    if len(values) != len(AUXILIARY_LABEL_ONLY_FEATURE_NAMES):
        _fail("PROFILED_TRAINING_ENRICHMENT_AUXILIARY_COUNT_INVALID")
    digest = hashlib.sha256()
    digest.update(_AUXILIARY_VECTOR_HASH_DOMAIN)
    for name, value in zip(AUXILIARY_LABEL_ONLY_FEATURE_NAMES, values, strict=True):
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_TRAINING_ENRICHMENT_AUXILIARY_VALUE_INVALID")
        encoded_name = name.encode("ascii", errors="strict")
        digest.update(struct.pack(">H", len(encoded_name)))
        digest.update(encoded_name)
        digest.update(struct.pack(">f", value))
    return digest.hexdigest()


def _causal_contract(result: object) -> dict[str, Any]:
    if type(result) is not CausalCostEvidenceV1Result:
        _fail("PROFILED_TRAINING_ENRICHMENT_EXACT_COST_FACTORY_RESULT_REQUIRED")
    try:
        contract = cast(CausalCostEvidenceV1Result, result).contract
    except CausalCostEvidenceV1Error as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_COST_RESULT_INTEGRITY_INVALID"
        ) from exc
    if type(contract) is not dict:
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_CONTRACT_INVALID")
    return contract


def _source_clocks(
    contract: Mapping[str, Any],
    *,
    decision: datetime,
) -> tuple[datetime, dict[str, tuple[str, str, str, str]]]:
    fee = _mapping(
        contract.get("fee_source"), reason="PROFILED_TRAINING_ENRICHMENT_FEE_SOURCE_INVALID"
    )
    notional = _mapping(
        contract.get("notional_source"),
        reason="PROFILED_TRAINING_ENRICHMENT_NOTIONAL_SOURCE_INVALID",
    )
    markets = _mapping(
        contract.get("market_sources"),
        reason="PROFILED_TRAINING_ENRICHMENT_MARKET_SOURCES_INVALID",
    )
    direct: dict[str, tuple[str, str, str, str]] = {}
    observed: list[datetime] = []

    fee_effective, fee_effective_at = _clock(
        fee.get("effective_at"), reason="PROFILED_TRAINING_ENRICHMENT_FEE_EFFECTIVE_AT_INVALID"
    )
    fee_available, fee_available_at = _clock(
        fee.get("available_at"), reason="PROFILED_TRAINING_ENRICHMENT_FEE_AVAILABLE_AT_INVALID"
    )
    fee_observed, fee_observed_at = _clock(
        fee.get("response_observed_at"),
        reason="PROFILED_TRAINING_ENRICHMENT_FEE_OBSERVED_AT_INVALID",
    )
    direct["authoritative_fee_schedule"] = (
        fee_effective,
        fee_available,
        max((fee_available_at, fee_observed_at))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        fee_effective,
    )
    observed.extend((fee_effective_at, fee_available_at, fee_observed_at))

    notional_effective, notional_effective_at = _clock(
        notional.get("effective_at"),
        reason="PROFILED_TRAINING_ENRICHMENT_NOTIONAL_EFFECTIVE_AT_INVALID",
    )
    notional_available, notional_available_at = _clock(
        notional.get("available_at"),
        reason="PROFILED_TRAINING_ENRICHMENT_NOTIONAL_AVAILABLE_AT_INVALID",
    )
    direct["expected_notional_policy"] = (
        notional_effective,
        notional_available,
        notional_available,
        notional_effective,
    )
    observed.extend((notional_effective_at, notional_available_at))

    for role in ("mark_price", "orderbook_depth", "orderbook_features"):
        source = _mapping(
            markets.get(role),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_SOURCE_INVALID",
        )
        clocks = _mapping(
            source.get("clocks"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_CLOCKS_INVALID",
        )
        event_text, event_at = _clock(
            clocks.get("event_time"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_EVENT_TIME_INVALID",
        )
        available_text, available_at = _clock(
            clocks.get("available_at"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_AVAILABLE_AT_INVALID",
        )
        _received_text, received_at = _clock(
            clocks.get("received_at"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_RECEIVED_AT_INVALID",
        )
        _generated_text, generated_at = _clock(
            clocks.get("generated_at"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_GENERATED_AT_INVALID",
        )
        atomic_text, atomic_at = _clock(
            source.get("atomic_server_observed_at"),
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_ATOMIC_OBSERVED_AT_INVALID",
        )
        direct[role] = (event_text, available_text, atomic_text, event_text)
        observed.extend((event_at, available_at, received_at, generated_at, atomic_at))

    if not observed or max(observed) > decision:
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_SOURCE_AFTER_PARENT_DECISION")
    return max(observed), direct


def _direct_receipts(
    *,
    contract: Mapping[str, Any],
    symbol: str,
    clocks: Mapping[str, tuple[str, str, str, str]],
    source_store: ImmutableSourcePayloadStore,
    target_store: ImmutableSourcePayloadStore,
    publish_artifacts: bool,
) -> dict[str, dict[str, Any]]:
    fee = _mapping(
        contract.get("fee_source"), reason="PROFILED_TRAINING_ENRICHMENT_FEE_SOURCE_INVALID"
    )
    notional = _mapping(
        contract.get("notional_source"),
        reason="PROFILED_TRAINING_ENRICHMENT_NOTIONAL_SOURCE_INVALID",
    )
    markets = _mapping(
        contract.get("market_sources"), reason="PROFILED_TRAINING_ENRICHMENT_MARKET_SOURCES_INVALID"
    )
    specs: dict[str, tuple[str, int, dict[str, Any], str]] = {
        "authoritative_fee_schedule": (
            cast(str, fee.get("artifact_payload_sha256")),
            cast(int, fee.get("artifact_payload_byte_count")),
            _address(
                fee.get("artifact_cas_address"),
                reason="PROFILED_TRAINING_ENRICHMENT_FEE_CAS_ADDRESS_INVALID",
            ),
            "CAUSAL_COST_AUTHORITATIVE_FEE_SCHEDULE_ARTIFACT_V1",
        ),
        "expected_notional_policy": (
            cast(str, notional.get("artifact_payload_sha256")),
            cast(int, notional.get("artifact_payload_byte_count")),
            _address(
                notional.get("artifact_cas_address"),
                reason="PROFILED_TRAINING_ENRICHMENT_NOTIONAL_CAS_ADDRESS_INVALID",
            ),
            "CAUSAL_COST_EXPECTED_NOTIONAL_POLICY_ARTIFACT_V1",
        ),
    }
    for role in ("mark_price", "orderbook_depth", "orderbook_features"):
        source = _mapping(
            markets.get(role), reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_SOURCE_INVALID"
        )
        specs[role] = (
            cast(str, source.get("payload_sha256")),
            cast(int, source.get("payload_byte_count")),
            _address(
                source.get("payload_cas_address"),
                reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_CAS_ADDRESS_INVALID",
            ),
            f"CAUSAL_COST_{role.upper()}_SOURCE_PAYLOAD",
        )
    receipts: dict[str, dict[str, Any]] = {}
    for role in PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES:
        payload_sha, payload_count, address, payload_type = specs[role]
        if (
            not _valid_sha256(payload_sha)
            or type(payload_count) is not int
            or payload_count <= 0
            or address["payload_sha256"] != payload_sha
            or address["payload_byte_count"] != payload_count
        ):
            _fail(f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_PAYLOAD_BINDING_INVALID")
        copied_address = _copy_materialized_payload(
            source_store=source_store,
            target_store=target_store,
            source_address=address,
            publish=publish_artifacts,
            reason=f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_CAS_COPY_INVALID",
        )
        event, available, observed, cutoff = clocks[role]
        try:
            receipts[role] = build_source_read_receipt(
                source_label=f"causal_cost:source:{symbol}:{role}",
                payload_type=payload_type,
                payload_sha256=payload_sha,
                payload_byte_count=payload_count,
                event_time=event,
                available_at=available,
                consumer_observed_at=observed,
                feature_cutoff=cutoff,
                read_locator_type="FILE_CONTENT_ADDRESS",
                read_locator=copied_address.relative_path,
                read_locator_version=payload_sha,
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=available,
                finality_verified_at=observed,
                finality_verifier=f"profiled_training_enrichment_{role}_v1",
            )
        except FeatureSnapshotValidationError as exc:
            raise ProfiledTrainingEnrichmentRecordV1Error(
                f"PROFILED_TRAINING_ENRICHMENT_{role.upper()}_LEDGER_RECEIPT_INVALID",
                *exc.reasons,
            ) from exc
    if len({item["receipt_sha256"] for item in receipts.values()}) != len(receipts):
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_SOURCE_RECEIPTS_NOT_DISTINCT")
    return receipts


def _build_child_record(
    *,
    parent_record: dict[str, Any],
    parent_binding: dict[str, Any],
    cost_evidence: CausalCostEvidenceV1Result,
    enrichment_store: ImmutableSourcePayloadStore,
    cost_artifact_available_at: str,
    enrichment_available_at: str,
    generated_at: str,
    publish_artifacts: bool,
) -> tuple[dict[str, Any], tuple[SourcePayloadAddress, ...]]:
    parent_envelope = _mapping(
        parent_record.get("frozen_envelope"),
        reason="PROFILED_TRAINING_ENRICHMENT_PARENT_ENVELOPE_INVALID",
    )
    decision_text, decision = _clock(
        parent_envelope.get("tensor_decision_time"),
        reason="PROFILED_TRAINING_ENRICHMENT_PARENT_DECISION_TIME_INVALID",
    )
    parent_generated_text, parent_generated = _clock(
        parent_envelope.get("generated_at"),
        reason="PROFILED_TRAINING_ENRICHMENT_PARENT_GENERATED_AT_INVALID",
    )
    cost_available_text, cost_available = _clock(
        cost_artifact_available_at,
        reason="PROFILED_TRAINING_ENRICHMENT_COST_AVAILABLE_AT_INVALID",
    )
    enrichment_available_text, enrichment_available = _clock(
        enrichment_available_at,
        reason="PROFILED_TRAINING_ENRICHMENT_AVAILABLE_AT_INVALID",
    )
    generated_text, generated = _clock(
        generated_at,
        reason="PROFILED_TRAINING_ENRICHMENT_GENERATED_AT_INVALID",
    )
    contract = _causal_contract(cost_evidence)
    if (
        contract.get("schema_version") != CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION
        or contract.get("implementation_id") != CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID
        or contract.get("implementation_sha256") != CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        or contract.get("symbol") != parent_envelope.get("symbol")
        or contract.get("feature_snapshot_identity") != parent_record.get("durable_snapshot_id")
        or contract.get("decision_time") != decision_text
        or contract.get("counterfactual_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_PARENT_IDENTITY_INVALID")
    source_max, source_clocks = _source_clocks(contract, decision=decision)
    if not (
        source_max <= cost_available <= enrichment_available <= generated <= decision
        and parent_generated <= generated
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_PUBLICATION_CLOCK_ORDER_INVALID")

    cost_exact_addresses: list[SourcePayloadAddress] = []
    if type(cost_evidence._exact_objects) is not tuple or not cost_evidence._exact_objects:
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_OBJECT_INVENTORY_INVALID")
    for source_address, payload in cost_evidence._exact_objects:
        if (
            type(source_address) is not SourcePayloadAddress
            or type(payload) is not bytes
            or source_address.payload_sha256 != hashlib.sha256(payload).hexdigest()
            or source_address.payload_byte_count != len(payload)
        ):
            _fail("PROFILED_TRAINING_ENRICHMENT_COST_OBJECT_INVENTORY_INVALID")
        cost_exact_addresses.append(
            _materialize(
                enrichment_store,
                payload,
                publish=publish_artifacts,
                reason="PROFILED_TRAINING_ENRICHMENT_COST_OBJECT_CAS_COPY_INVALID",
            )
        )

    artifact_bytes = cost_evidence.artifact_json.encode("ascii", errors="strict")
    artifact_address = _materialize(
        enrichment_store,
        artifact_bytes,
        publish=publish_artifacts,
        reason="PROFILED_TRAINING_ENRICHMENT_COST_ARTIFACT_CAS_INVALID",
    )
    if (
        artifact_address.payload_sha256 != cost_evidence.artifact_sha256
        or artifact_address.payload_byte_count != len(artifact_bytes)
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_COST_ARTIFACT_BINDING_INVALID")

    direct = _direct_receipts(
        contract=contract,
        symbol=cast(str, parent_envelope["symbol"]),
        clocks=source_clocks,
        source_store=cost_evidence._store,
        target_store=enrichment_store,
        publish_artifacts=publish_artifacts,
    )
    source_event_times = [
        _clock(values[0], reason="PROFILED_TRAINING_ENRICHMENT_SOURCE_EVENT_TIME_INVALID")[1]
        for values in source_clocks.values()
    ]
    _parent_cutoff_text, parent_cutoff = _clock(
        parent_envelope.get("feature_cutoff"),
        reason="PROFILED_TRAINING_ENRICHMENT_PARENT_FEATURE_CUTOFF_INVALID",
    )
    # This global evidence cutoff covers both inventories.  MASA/PPO model
    # cutoffs remain parent-bound below because the four costs are label-only.
    cost_cutoff = max(parent_cutoff, *source_event_times)
    cost_cutoff_text = cost_cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
    cost_children = [
        {"input_role": role, "receipt_sha256": direct[role]["receipt_sha256"]}
        for role in PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES
    ]
    try:
        cost_receipt = build_source_read_receipt(
            source_label=f"causal_cost:capture:{parent_envelope['symbol']}",
            payload_type="CAUSAL_COST_EVIDENCE_V1_ARTIFACT",
            payload_sha256=cost_evidence.artifact_sha256,
            payload_byte_count=len(artifact_bytes),
            event_time=cost_cutoff_text,
            available_at=cost_available_text,
            consumer_observed_at=cost_available_text,
            feature_cutoff=cost_cutoff_text,
            read_locator_type="FILE_CONTENT_ADDRESS",
            read_locator=artifact_address.relative_path,
            read_locator_version=cost_evidence.artifact_sha256,
            finality_type="VERSIONED_SNAPSHOT",
            finality_cutoff=cost_available_text,
            finality_verified_at=cost_available_text,
            finality_verifier="profiled_training_enrichment_cost_capture_v1",
            receipt_kind="COMPOSITE_DERIVATION",
            child_read_bindings=cost_children,
            derivation_material=_derivation(
                producer="profiled_training_enrichment_cost_capture_v1",
                material={
                    "artifact_sha256": cost_evidence.artifact_sha256,
                    "child_read_bindings": cost_children,
                },
            ),
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_COST_CAPTURE_RECEIPT_INVALID",
            *exc.reasons,
        ) from exc

    values = tuple(cost_evidence.ordered_values)
    if len(values) != len(AUXILIARY_LABEL_ONLY_FEATURE_NAMES):
        _fail("PROFILED_TRAINING_ENRICHMENT_AUXILIARY_COUNT_INVALID")
    auxiliary_receipts: list[dict[str, Any]] = []
    auxiliary_addresses: list[SourcePayloadAddress] = []
    auxiliary_labels: list[str] = []
    for name, value in zip(AUXILIARY_LABEL_ONLY_FEATURE_NAMES, values, strict=True):
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_TRAINING_ENRICHMENT_AUXILIARY_VALUE_INVALID")
        scalar_bytes = struct.pack(">f", value)
        address = _materialize(
            enrichment_store,
            scalar_bytes,
            publish=publish_artifacts,
            reason=f"PROFILED_TRAINING_ENRICHMENT_{name.upper()}_CAS_INVALID",
        )
        auxiliary_addresses.append(address)
        source_label = f"causal_cost:auxiliary:{name}"
        try:
            receipt = build_source_read_receipt(
                source_label=source_label,
                payload_type="IEEE754_BINARY32_CAUSAL_COST_SCALAR",
                payload_sha256=address.payload_sha256,
                payload_byte_count=address.payload_byte_count,
                event_time=cost_cutoff_text,
                available_at=enrichment_available_text,
                consumer_observed_at=enrichment_available_text,
                feature_cutoff=cost_cutoff_text,
                read_locator_type="FILE_CONTENT_ADDRESS",
                read_locator=address.relative_path,
                read_locator_version=address.payload_sha256,
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=enrichment_available_text,
                finality_verified_at=enrichment_available_text,
                finality_verifier=f"profiled_training_enrichment_{name}_v1",
                receipt_kind="COMPOSITE_DERIVATION",
                child_read_bindings=[
                    {
                        "input_role": "causal_cost_capture_artifact",
                        "receipt_sha256": cost_receipt["receipt_sha256"],
                    }
                ],
                derivation_material=_derivation(
                    producer="profiled_training_enrichment_scalar_v1",
                    material={
                        "feature_name": name,
                        "source_cost_receipt_sha256": cost_evidence.ordered_receipt_sha256s[
                            len(auxiliary_receipts)
                        ],
                        "cost_capture_receipt_sha256": cost_receipt["receipt_sha256"],
                        "scalar_payload_sha256": address.payload_sha256,
                    },
                ),
            )
        except FeatureSnapshotValidationError as exc:
            raise ProfiledTrainingEnrichmentRecordV1Error(
                f"PROFILED_TRAINING_ENRICHMENT_{name.upper()}_RECEIPT_INVALID",
                *exc.reasons,
            ) from exc
        auxiliary_labels.append(source_label)
        auxiliary_receipts.append(receipt)

    auxiliary_roots = [item["receipt_sha256"] for item in auxiliary_receipts]
    inventory_by_sha = {
        address.payload_sha256: {
            "payload_sha256": address.payload_sha256,
            "payload_byte_count": address.payload_byte_count,
        }
        for address in (*cost_exact_addresses, *auxiliary_addresses)
    }
    cost_binding = {
        "schema_version": PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION,
        "cost_capture_schema_version": CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
        "cost_capture_implementation_id": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
        "cost_capture_implementation_sha256": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
        "symbol": parent_envelope["symbol"],
        "decision_time": decision_text,
        "feature_cutoff": cost_cutoff_text,
        "parent_model_feature_cutoff": parent_envelope["feature_cutoff"],
        "ppo_feature_cutoff_semantics": PROFILED_TRAINING_PPO_CUTOFF_SEMANTICS,
        "available_at": enrichment_available_text,
        "expected_holding_horizon_seconds": CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
        "cost_capture_artifact_sha256": cost_evidence.artifact_sha256,
        "cost_capture_artifact_byte_count": len(artifact_bytes),
        "cost_capture_receipt_sha256": cost_receipt["receipt_sha256"],
        "authoritative_fee_schedule_sha256": direct["authoritative_fee_schedule"]["payload_sha256"],
        "expected_notional_policy_sha256": direct["expected_notional_policy"]["payload_sha256"],
        "fee_schedule_receipt_sha256": direct["authoritative_fee_schedule"]["receipt_sha256"],
        "notional_policy_receipt_sha256": direct["expected_notional_policy"]["receipt_sha256"],
        "orderbook_depth_receipt_sha256": direct["orderbook_depth"]["receipt_sha256"],
        "orderbook_features_receipt_sha256": direct["orderbook_features"]["receipt_sha256"],
        "mark_price_receipt_sha256": direct["mark_price"]["receipt_sha256"],
        "auxiliary_feature_names": list(AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
        "auxiliary_source_labels": auxiliary_labels,
        "auxiliary_feature_receipt_sha256s": auxiliary_roots,
        "auxiliary_values_float32_sha256": _auxiliary_values_sha256(values),
        "immutable_cost_store_root": str(enrichment_store.root_path),
        "immutable_cost_store_root_sha256": hashlib.sha256(
            str(enrichment_store.root_path).encode("utf-8")
        ).hexdigest(),
        "immutable_cost_object_inventory": [
            inventory_by_sha[digest] for digest in sorted(inventory_by_sha)
        ],
    }
    attestation = {
        "schema_version": PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION,
        "classification": PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION,
        "status": PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS,
        "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "logical_profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        "logical_enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
        "transform_implementation_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
        "transform_implementation_sha256": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        ),
        "transform_configuration_sha256": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        ),
        "projection_schema_version": PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
        "projection_implementation_sha256": PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
        "projection_configuration_sha256": PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
        "physical_feature_count": PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT,
        "physical_ordered_feature_names_sha256": (
            PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256
        ),
        "parent_model_record_binding": parent_binding,
        "cost_capture_binding": cost_binding,
        "authorization": dict(_AUTHORIZATION),
    }
    parent_receipts = parent_envelope.get("source_read_receipts")
    if type(parent_receipts) is not list:
        _fail("PROFILED_TRAINING_ENRICHMENT_PARENT_RECEIPT_GRAPH_INVALID")
    identity_sha = stable_sha256(
        {
            "schema_version": PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION,
            "parent_durable_snapshot_id": parent_record["durable_snapshot_id"],
            "cost_capture_artifact_sha256": cost_evidence.artifact_sha256,
            "cost_artifact_available_at": cost_available_text,
            "enrichment_available_at": enrichment_available_text,
            "generated_at": generated_text,
        }
    )
    try:
        child = build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol=cast(str, parent_envelope["symbol"]),
            timeframe=cast(str, parent_envelope["timeframe"]),
            feature_snapshot_id=f"profiled_training_enrichment_{identity_sha}",
            tensor_decision_time=decision_text,
            temporal_rejection_reasons=[],
            ordered_feature_names=PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES,
            feature_values=[*parent_envelope["feature_values"], *values],
            missing_mask=[*parent_envelope["missing_mask"], *([0] * len(values))],
            stale_mask=[*parent_envelope["stale_mask"], *([0] * len(values))],
            source_availability_mask=[
                *parent_envelope["source_availability_mask"],
                *([1] * len(values)),
            ],
            ordered_feature_source_labels=[
                *parent_envelope["ordered_feature_source_labels"],
                *auxiliary_labels,
            ],
            feature_source_receipt_sha256s=[
                *parent_envelope["feature_source_receipt_sha256s"],
                *auxiliary_roots,
            ],
            source_read_receipts=[
                *parent_receipts,
                *direct.values(),
                cost_receipt,
                *auxiliary_receipts,
            ],
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=["REQUIRED"]
            * PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT,
            original_tensor_id=f"profiled_training_enrichment_tensor_{identity_sha}",
            source_lineage_material={PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY: attestation},
            feature_cutoff=cost_cutoff_text,
            masa_feature_cutoff=cast(str, parent_envelope["masa_feature_cutoff"]),
            ppo_feature_cutoff=cost_cutoff_text,
            ppo_decision_time=cast(str, parent_envelope["ppo_decision_time"]),
            generated_at=generated_text,
        )
        validate_feature_snapshot_record(child)
    except FeatureSnapshotValidationError as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_LEDGER_RECORD_INVALID",
            *exc.reasons,
        ) from exc
    return child, (artifact_address, *auxiliary_addresses)


@dataclass(frozen=True, slots=True)
class ProfiledTrainingEnrichmentPairV1:
    """Opaque validated parent/child append unit with fresh-validation inputs."""

    schema_version: str
    parent_durable_snapshot_id: str
    child_durable_snapshot_id: str
    parent_record_sha256: str
    child_record_sha256: str
    cost_capture_artifact_sha256: str
    cost_artifact_available_at: str
    enrichment_available_at: str
    generated_at: str
    runtime_status: str
    trainer_candidate_in_lineage: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    _parent_record_json: str = field(repr=False, compare=False)
    _child_record_json: str = field(repr=False, compare=False)
    _transform_result: AuthenticatedOhlcvProfileTransformV1Result = field(repr=False, compare=False)
    _capture_contract_json: str = field(repr=False, compare=False)
    _capture_set_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _parent_artifact_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _source_provenance_ledger: TrainerSourceProvenanceLedgerV4 = field(repr=False, compare=False)
    _source_provenance_entries: tuple[
        TrainerSourceProvenanceLedgerEntryV4,
        TrainerSourceProvenanceLedgerEntryV4,
    ] = field(repr=False, compare=False)
    _cost_evidence: CausalCostEvidenceV1Result = field(repr=False, compare=False)
    _enrichment_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PAIR_TOKEN
            or self.schema_version != PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION
            or self.runtime_status != PROFILED_TRAINING_ENRICHMENT_RUNTIME_STATUS
            or self.trainer_candidate_in_lineage is not True
            or any(
                value is not False
                for value in (
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_TRAINING_ENRICHMENT_PAIR_FACTORY_INVARIANT_INVALID")

    @property
    def parent_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._parent_record_json))

    @property
    def child_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._child_record_json))


def build_profiled_training_enrichment_pair_v1(
    *,
    parent_record: Mapping[str, Any],
    transform_result: AuthenticatedOhlcvProfileTransformV1Result,
    capture_set_contract: Mapping[str, Any],
    capture_set_store: ImmutableSourcePayloadStore,
    parent_artifact_store: ImmutableSourcePayloadStore,
    source_provenance_ledger: TrainerSourceProvenanceLedgerV4,
    source_provenance_entries: tuple[
        TrainerSourceProvenanceLedgerEntryV4,
        TrainerSourceProvenanceLedgerEntryV4,
    ],
    cost_evidence: CausalCostEvidenceV1Result,
    enrichment_store: ImmutableSourcePayloadStore,
    cost_artifact_available_at: str,
    enrichment_available_at: str,
    generated_at: str,
) -> ProfiledTrainingEnrichmentPairV1:
    """Build a still-unappended parent/child unit from exact factory products."""

    if type(parent_record) is not dict:
        _fail("PROFILED_TRAINING_ENRICHMENT_EXACT_PARENT_RECORD_REQUIRED")
    parent = _strict_json_copy(
        parent_record, reason="PROFILED_TRAINING_ENRICHMENT_PARENT_JSON_INVALID"
    )
    capture_contract = _strict_json_copy(
        capture_set_contract,
        reason="PROFILED_TRAINING_ENRICHMENT_CAPTURE_CONTRACT_INVALID",
    )
    try:
        parent_validation = validate_profiled_model_feature_snapshot_record_v1(
            parent,
            transform_result=transform_result,
            capture_set_contract=capture_contract,
            capture_set_store=capture_set_store,
            artifact_store=parent_artifact_store,
            source_provenance_ledger=source_provenance_ledger,
            source_provenance_entries=source_provenance_entries,
        )
    except ProfiledModelFeatureSnapshotRecordV1Error as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_PARENT_REVALIDATION_FAILED",
            *exc.reasons,
        ) from exc
    child, _addresses = _build_child_record(
        parent_record=parent,
        parent_binding=parent_validation.lineage_binding,
        cost_evidence=cost_evidence,
        enrichment_store=enrichment_store,
        cost_artifact_available_at=cost_artifact_available_at,
        enrichment_available_at=enrichment_available_at,
        generated_at=generated_at,
        publish_artifacts=True,
    )
    parent_json = canonical_json(parent)
    child_json = canonical_json(child)
    pair = ProfiledTrainingEnrichmentPairV1(
        schema_version=PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION,
        parent_durable_snapshot_id=cast(str, parent["durable_snapshot_id"]),
        child_durable_snapshot_id=cast(str, child["durable_snapshot_id"]),
        parent_record_sha256=cast(str, parent["record_sha256"]),
        child_record_sha256=cast(str, child["record_sha256"]),
        cost_capture_artifact_sha256=cost_evidence.artifact_sha256,
        cost_artifact_available_at=cost_artifact_available_at,
        enrichment_available_at=enrichment_available_at,
        generated_at=generated_at,
        runtime_status=PROFILED_TRAINING_ENRICHMENT_RUNTIME_STATUS,
        trainer_candidate_in_lineage=True,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        _parent_record_json=parent_json,
        _child_record_json=child_json,
        _transform_result=transform_result,
        _capture_contract_json=canonical_json(capture_contract),
        _capture_set_store=capture_set_store,
        _parent_artifact_store=parent_artifact_store,
        _source_provenance_ledger=source_provenance_ledger,
        _source_provenance_entries=source_provenance_entries,
        _cost_evidence=cost_evidence,
        _enrichment_store=enrichment_store,
        _construction_token=_PAIR_TOKEN,
    )
    _validated_pair_records(pair)
    return pair


def _validated_pair_records(
    pair: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(pair) is not ProfiledTrainingEnrichmentPairV1
        or pair._construction_token is not _PAIR_TOKEN
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_EXACT_PAIR_REQUIRED")
    typed = cast(ProfiledTrainingEnrichmentPairV1, pair)
    parent = typed.parent_record
    child = typed.child_record
    if (
        parent.get("durable_snapshot_id") != typed.parent_durable_snapshot_id
        or child.get("durable_snapshot_id") != typed.child_durable_snapshot_id
        or parent.get("record_sha256") != typed.parent_record_sha256
        or child.get("record_sha256") != typed.child_record_sha256
        or canonical_json(parent) != typed._parent_record_json
        or canonical_json(child) != typed._child_record_json
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_PAIR_RECORD_BINDING_INVALID")
    capture_contract = cast(dict[str, Any], json.loads(typed._capture_contract_json))
    try:
        parent_validation = validate_profiled_model_feature_snapshot_record_v1(
            parent,
            transform_result=typed._transform_result,
            capture_set_contract=capture_contract,
            capture_set_store=typed._capture_set_store,
            artifact_store=typed._parent_artifact_store,
            source_provenance_ledger=typed._source_provenance_ledger,
            source_provenance_entries=typed._source_provenance_entries,
        )
    except ProfiledModelFeatureSnapshotRecordV1Error as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_PARENT_REVALIDATION_FAILED",
            *exc.reasons,
        ) from exc
    rebuilt, _addresses = _build_child_record(
        parent_record=parent,
        parent_binding=parent_validation.lineage_binding,
        cost_evidence=typed._cost_evidence,
        enrichment_store=typed._enrichment_store,
        cost_artifact_available_at=typed.cost_artifact_available_at,
        enrichment_available_at=typed.enrichment_available_at,
        generated_at=typed.generated_at,
        publish_artifacts=False,
    )
    if rebuilt != child:
        _fail("PROFILED_TRAINING_ENRICHMENT_CHILD_FULL_RECOMPUTE_MISMATCH")
    return parent, child


@dataclass(frozen=True, slots=True)
class ProfiledTrainingEnrichmentAppendV1:
    """Receipt-backed proof that the parent and child share one append."""

    schema_version: str
    transaction_id: str
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str
    parent_sequence: int
    child_sequence: int
    parent_durable_snapshot_id: str
    child_durable_snapshot_id: str
    transaction_committed: bool
    transaction_readback_verified: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _APPEND_TOKEN
            or self.schema_version != PROFILED_TRAINING_ENRICHMENT_APPEND_V1_SCHEMA_VERSION
            or self.transaction_committed is not True
            or self.transaction_readback_verified is not True
            or self.child_sequence != self.parent_sequence + 1
            or self.runtime_wired is not False
        ):
            _fail("PROFILED_TRAINING_ENRICHMENT_APPEND_RESULT_INVARIANT_INVALID")


def append_profiled_training_enrichment_pair_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    pair: ProfiledTrainingEnrichmentPairV1,
    writer_lease: FeatureSnapshotWriterLease | None = None,
) -> ProfiledTrainingEnrichmentAppendV1:
    """Append exactly ``[parent, child]`` after an atomic absence precheck."""

    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_TRAINING_ENRICHMENT_EXACT_LEDGER_REQUIRED")
    parent, child = _validated_pair_records(pair)
    try:
        with ledger.writer_lease(writer_lease) as held:
            if ledger.path.exists():
                existing_parent = ledger.get_snapshot(pair.parent_durable_snapshot_id)
                existing_child = ledger.get_snapshot(pair.child_durable_snapshot_id)
                if existing_parent is not None:
                    _fail("PROFILED_TRAINING_ENRICHMENT_PARENT_ALREADY_COMMITTED")
                if existing_child is not None:
                    _fail("PROFILED_TRAINING_ENRICHMENT_CHILD_ALREADY_COMMITTED")
            append_result: FeatureSnapshotAppendResult = ledger.append_snapshots(
                [parent, child], writer_lease=held
            )
            if (
                append_result.attempted_rows != 2
                or append_result.inserted_rows != 2
                or append_result.duplicate_rows != 0
                or append_result.transaction_committed is not True
                or append_result.transaction_readback_verified is not True
            ):
                _fail("PROFILED_TRAINING_ENRICHMENT_ATOMIC_APPEND_DISPOSITION_INVALID")
            committed_parent = ledger.get_snapshot(pair.parent_durable_snapshot_id)
            committed_child = ledger.get_snapshot(pair.child_durable_snapshot_id)
    except ProfiledTrainingEnrichmentRecordV1Error:
        raise
    except FeatureSnapshotLedgerError as exc:
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_ENRICHMENT_LEDGER_APPEND_FAILED"
        ) from exc
    if committed_parent is None or committed_child is None:
        _fail("PROFILED_TRAINING_ENRICHMENT_POSTCOMMIT_RECORD_MISSING")
    if (
        committed_parent.sequence + 1 != committed_child.sequence
        or committed_parent.append_transaction_id != append_result.transaction_id
        or committed_child.append_transaction_id != append_result.transaction_id
        or committed_parent.append_receipt_sha256 != append_result.append_receipt_sha256
        or committed_child.append_receipt_sha256 != append_result.append_receipt_sha256
        or committed_parent.postcommit_receipt_sha256 != append_result.postcommit_receipt_sha256
        or committed_child.postcommit_receipt_sha256 != append_result.postcommit_receipt_sha256
        or committed_parent.postcommit_readback_at != append_result.postcommit_readback_at
        or committed_child.postcommit_readback_at != append_result.postcommit_readback_at
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_POSTCOMMIT_SHARED_RECEIPT_INVALID")
    return ProfiledTrainingEnrichmentAppendV1(
        schema_version=PROFILED_TRAINING_ENRICHMENT_APPEND_V1_SCHEMA_VERSION,
        transaction_id=append_result.transaction_id,
        append_receipt_sha256=append_result.append_receipt_sha256,
        postcommit_receipt_sha256=append_result.postcommit_receipt_sha256,
        postcommit_readback_at=append_result.postcommit_readback_at,
        parent_sequence=committed_parent.sequence,
        child_sequence=committed_child.sequence,
        parent_durable_snapshot_id=pair.parent_durable_snapshot_id,
        child_durable_snapshot_id=pair.child_durable_snapshot_id,
        transaction_committed=True,
        transaction_readback_verified=True,
        runtime_wired=False,
        _construction_token=_APPEND_TOKEN,
    )


__all__ = [
    "PROFILED_TRAINING_ENRICHMENT_APPEND_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_ENRICHMENT_RECORD_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_ENRICHMENT_RUNTIME_STATUS",
    "ProfiledTrainingEnrichmentAppendV1",
    "ProfiledTrainingEnrichmentPairV1",
    "ProfiledTrainingEnrichmentRecordV1Error",
    "append_profiled_training_enrichment_pair_v1",
    "build_profiled_training_enrichment_pair_v1",
]
