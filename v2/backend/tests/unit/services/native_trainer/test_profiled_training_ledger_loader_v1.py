from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as feature_ledger_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_ledger_loader_v1 as loader_v1,
)
from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
    PROVENANCE_CANONICAL_V3,
    PROVENANCE_LEGACY_V1_IMPORT,
    DurableFeatureSnapshotLedger,
    FixedCutoffFeatureSnapshot,
    build_feature_snapshot_record,
    build_source_read_receipt,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)

BASE = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
CUTOFF = BASE
AVAILABLE = BASE + timedelta(seconds=1)
OBSERVED = BASE + timedelta(seconds=2)
TRANSFORM_AVAILABLE = BASE + timedelta(seconds=3)
GENERATED = BASE + timedelta(seconds=4)
COST_SOURCE_AVAILABLE = BASE + timedelta(seconds=4, milliseconds=500)
COST_SOURCE_OBSERVED = BASE + timedelta(seconds=5)
COST_CAPTURE_AVAILABLE = BASE + timedelta(seconds=6)
AUXILIARY_AVAILABLE = BASE + timedelta(seconds=7)
CHILD_GENERATED = BASE + timedelta(seconds=7, milliseconds=500)
DECISION = BASE + timedelta(seconds=8)


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _derivation(label: str) -> dict[str, Any]:
    return {
        "schema_version": FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
        "producer_id": "profiled-training-loader-test",
        "producer_version": "v1",
        "transform_sha256": _digest(f"transform:{label}"),
        "configuration_sha256": _digest(f"configuration:{label}"),
    }


def _receipt(
    *,
    label: str,
    payload: bytes,
    available: datetime = AVAILABLE,
    observed: datetime = OBSERVED,
    event: datetime = CUTOFF,
    feature_cutoff: datetime | None = None,
    locator_type: str = "FILE_CONTENT_ADDRESS",
    payload_type: str = "UNIT_TEST_IMMUTABLE_EVIDENCE",
    finality_type: str = "VERSIONED_SNAPSHOT",
    kind: str = "DIRECT_READ",
    children: list[dict[str, str]] | None = None,
    store: ImmutableSourcePayloadStore | None = None,
) -> dict[str, Any]:
    address = store.put(payload) if store is not None else None
    return build_source_read_receipt(
        source_label=label,
        payload_type=payload_type,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_byte_count=len(payload),
        event_time=_utc(event),
        available_at=_utc(available),
        consumer_observed_at=_utc(observed),
        feature_cutoff=_utc(feature_cutoff or event),
        read_locator_type=locator_type,
        read_locator=(
            address.relative_path
            if address is not None
            else f"objects/{hashlib.sha256(payload).hexdigest()}"
        ),
        read_locator_version=hashlib.sha256(payload).hexdigest(),
        finality_type=finality_type,
        finality_cutoff=_utc(available),
        finality_verified_at=_utc(available),
        finality_verifier="profiled-training-loader-test",
        receipt_kind=kind,
        child_read_bindings=children or (),
        derivation_material=_derivation(label) if kind == "COMPOSITE_DERIVATION" else None,
    )


def _parent_binding(parent: dict[str, Any]) -> dict[str, Any]:
    dummy = FixedCutoffFeatureSnapshot(
        sequence=1,
        record=parent,
        append_transaction_id="feature_snapshot_append_" + "a" * 64,
        append_receipt_sha256="b" * 64,
        postcommit_receipt_sha256="c" * 64,
        postcommit_readback_at=_utc(CHILD_GENERATED),
    )
    return loader_v1._validate_parent_model_record(dummy)["binding"]


def _cost_evidence(
    auxiliary_values: list[float],
    *,
    cost_store: ImmutableSourcePayloadStore,
    feature_snapshot_identity: str,
    symbol: str = "BTCUSDT",
    decision: datetime = DECISION,
    feature_cutoff: datetime = CUTOFF,
    parent_model_cutoff: datetime | None = None,
    source_available: datetime = COST_SOURCE_AVAILABLE,
    source_observed: datetime = COST_SOURCE_OBSERVED,
    capture_available: datetime = COST_CAPTURE_AVAILABLE,
    auxiliary_available: datetime = AUXILIARY_AVAILABLE,
    auxiliary_locator_type: str = "FILE_CONTENT_ADDRESS",
    holding_horizon_seconds: int = 900,
    direct_receipt_mutator: Any | None = None,
    corrupt_direct_receipt_self_hash_role: str | None = None,
    compact_orderbook_payload_clocks: bool = False,
    orderbook_payload_event_offset: timedelta | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, Any]]:
    orderbook_mid = 100.0
    orderbook_best_bid = 99.9875
    orderbook_best_ask = 100.0125
    orderbook_clocks = {
        "event_time": _utc(feature_cutoff),
        "received_at": _utc(source_available),
        "available_at": _utc(source_available),
        "generated_at": _utc(source_available),
    }
    orderbook_payload_clocks = dict(orderbook_clocks)
    if orderbook_payload_event_offset is not None:
        orderbook_payload_clocks["event_time"] = _utc(
            feature_cutoff + orderbook_payload_event_offset
        )
    if compact_orderbook_payload_clocks:
        orderbook_payload_clocks = {
            name: value[:-1].rstrip("0").rstrip(".") + "Z"
            for name, value in orderbook_payload_clocks.items()
        }
    orderbook_depth_payload = json.dumps(
        {
            "ask_levels": 1,
            "asks": [{"price": orderbook_best_ask, "quantity": 100.0}],
            "best_ask": orderbook_best_ask,
            "best_bid": orderbook_best_bid,
            "bid_ask_mid": orderbook_mid,
            "bid_levels": 1,
            "bids": [{"price": orderbook_best_bid, "quantity": 100.0}],
            "exchange": "binance",
            "event_time": orderbook_payload_clocks["event_time"],
            "generated_at": orderbook_payload_clocks["generated_at"],
            "mid": orderbook_mid,
            "received_at": orderbook_payload_clocks["received_at"],
            "schema_version": "direct_orderbook_depth_v1",
            "sequence_gap": False,
            "sequence_gap_flag": 0,
            "sequence_id": 123456,
            "source": "direct_binance",
            "spread_bps": 2.5,
            "symbol": symbol,
            "available_at": orderbook_payload_clocks["available_at"],
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    source_payloads = {
        role: (
            orderbook_depth_payload
            if role == "orderbook_depth"
            else f"source:{role}".encode()
        )
        for role in loader_v1.PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES
    }
    source_receipts: dict[str, dict[str, Any]] = {}
    for role in loader_v1.PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES:
        source_receipts[role] = _receipt(
            label=f"causal_cost:{role}",
            payload=source_payloads[role],
            available=source_available,
            observed=source_observed,
            event=feature_cutoff,
            store=cost_store,
        )

    def address_mapping(payload: bytes) -> dict[str, Any]:
        address = cost_store.put(payload)
        return {
            "schema_version": address.schema_version,
            "payload_sha256": address.payload_sha256,
            "payload_byte_count": address.payload_byte_count,
            "relative_path": address.relative_path,
        }

    def receipt_payload_address(role: str) -> dict[str, Any]:
        receipt = source_receipts[role]
        address = cost_store.verify(
            receipt["payload_sha256"],
            expected_byte_count=receipt["read_evidence"]["payload_byte_count"],
        )
        return {
            "schema_version": address.schema_version,
            "payload_sha256": address.payload_sha256,
            "payload_byte_count": address.payload_byte_count,
            "relative_path": address.relative_path,
        }

    market_sources: dict[str, dict[str, Any]] = {}
    for role in ("mark_price", "orderbook_depth", "orderbook_features"):
        receipt = source_receipts[role]
        source_key = f"unit-test:{role}:{symbol}"
        market_sources[role] = {
            "source_key": source_key,
            "source_key_sha256": hashlib.sha256(source_key.encode("ascii")).hexdigest(),
            "payload_sha256": receipt["payload_sha256"],
            "payload_byte_count": receipt["read_evidence"]["payload_byte_count"],
            "payload_cas_address": receipt_payload_address(role),
            "source_schema_version": (
                "direct_orderbook_depth_v1"
                if role == "orderbook_depth"
                else f"unit_{role}_v1"
            ),
            "source_transport": "UNIT_TEST_CONTENT_ADDRESS",
            "atomic_batch_id": f"unit-atomic-batch:{symbol}",
            "atomic_batch_material_sha256": hashlib.sha256(
                f"unit-atomic-batch:{symbol}".encode("ascii")
            ).hexdigest(),
            "source_sequence_id": 123456,
            "source_sequence_gap": False,
            "atomic_server_observed_at": _utc(source_observed),
            "redis_pttl_ms": 60_000,
            "redis_pttl_expiry_projection_at": _utc(
                source_observed + timedelta(seconds=60)
            ),
            "expiry_evidence_kind": "REDIS_PTTL_AT_ATOMIC_READ",
            "clocks": dict(orderbook_clocks),
        }
        direct_material = {
            "schema_version": loader_v1.CAUSAL_COST_SOURCE_RECEIPT_V1_SCHEMA_VERSION,
            "receipt_kind": "DIRECT_READ",
            "source_role": role,
            "source_key": market_sources[role]["source_key"],
            "source_key_sha256": market_sources[role]["source_key_sha256"],
            "source_schema_version": market_sources[role]["source_schema_version"],
            "source_transport": market_sources[role]["source_transport"],
            "symbol": symbol,
            "feature_snapshot_identity": feature_snapshot_identity,
            "payload_sha256": market_sources[role]["payload_sha256"],
            "payload_byte_count": market_sources[role]["payload_byte_count"],
            "payload_cas_address": market_sources[role]["payload_cas_address"],
            "atomic_batch_id": market_sources[role]["atomic_batch_id"],
            "atomic_batch_material_sha256": market_sources[role][
                "atomic_batch_material_sha256"
            ],
            "atomic_server_observed_at": market_sources[role][
                "atomic_server_observed_at"
            ],
            "redis_pttl_ms": market_sources[role]["redis_pttl_ms"],
            "redis_pttl_expiry_projection_at": market_sources[role][
                "redis_pttl_expiry_projection_at"
            ],
            "expiry_evidence_kind": market_sources[role]["expiry_evidence_kind"],
            "consumer_static_age_threshold_applied": False,
            "source_sequence_id": market_sources[role]["source_sequence_id"],
            "source_sequence_gap": False,
            **orderbook_clocks,
            "decision_time": _utc(decision),
            "available_at_not_after_decision": True,
            "producer_schema_semantics_rederived": True,
            "upstream_transport_cryptographic_authenticity_attested": False,
            "authorization": dict(loader_v1._MARKET_DIRECT_READ_AUTHORIZATION),
        }
        if direct_receipt_mutator is not None:
            direct_receipt_mutator(role, direct_material)
        direct_receipt = {
            **direct_material,
            "receipt_sha256": stable_sha256(direct_material),
        }
        if role == corrupt_direct_receipt_self_hash_role:
            direct_receipt["receipt_sha256"] = "f" * 64
        direct_receipt_bytes = json.dumps(
            direct_receipt,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        market_sources[role]["direct_read_receipt_sha256"] = direct_receipt[
            "receipt_sha256"
        ]
        market_sources[role]["direct_read_receipt_cas_address"] = address_mapping(
            direct_receipt_bytes
        )
    fee_source = {
        "artifact_cas_address": receipt_payload_address("authoritative_fee_schedule"),
        "input_receipt_cas_address": address_mapping(b"original-fee-receipt"),
        "raw_response_cas_address": address_mapping(b"raw-fee-response"),
    }
    notional_source = {
        "artifact_cas_address": receipt_payload_address("expected_notional_policy"),
        "input_receipt_cas_address": address_mapping(b"original-notional-receipt"),
    }
    artifact = json.dumps(
        {
            "counterfactual_holding_horizon_seconds": holding_horizon_seconds,
            "counterfactual_horizon_end": _utc(
                decision + timedelta(seconds=holding_horizon_seconds)
            ),
            "decision_time": _utc(decision),
            "fee_source": fee_source,
            "implementation_id": loader_v1.CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (
                loader_v1.CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
            ),
            "market_sources": market_sources,
            "notional_source": notional_source,
            "schema_version": loader_v1.CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
            "symbol": symbol,
            "feature_snapshot_identity": feature_snapshot_identity,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    children = [
        {
            "input_role": role,
            "receipt_sha256": source_receipts[role]["receipt_sha256"],
        }
        for role in loader_v1.PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES
    ]
    cost_receipt = _receipt(
        label="causal_cost:capture",
        payload=artifact,
        available=capture_available,
        observed=capture_available,
        event=feature_cutoff,
        kind="COMPOSITE_DERIVATION",
        children=children,
        store=cost_store,
    )
    labels: list[str] = []
    roots: list[str] = []
    auxiliary_receipts: list[dict[str, Any]] = []
    for name, value in zip(
        loader_v1.AUXILIARY_LABEL_ONLY_FEATURE_NAMES,
        auxiliary_values,
        strict=True,
    ):
        label = f"causal_cost:auxiliary:{name}"
        receipt = _receipt(
            label=label,
            payload=struct.pack(">f", value),
            available=auxiliary_available,
            observed=auxiliary_available,
            event=feature_cutoff,
            locator_type=auxiliary_locator_type,
            kind="COMPOSITE_DERIVATION",
            children=[
                {
                    "input_role": "causal_cost_capture_artifact",
                    "receipt_sha256": cost_receipt["receipt_sha256"],
                }
            ],
            store=cost_store,
        )
        labels.append(label)
        roots.append(receipt["receipt_sha256"])
        auxiliary_receipts.append(receipt)
    binding = {
        "schema_version": loader_v1.PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION,
        "cost_capture_schema_version": loader_v1.CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
        "cost_capture_implementation_id": (loader_v1.CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID),
        "cost_capture_implementation_sha256": (
            loader_v1.CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        ),
        "symbol": symbol,
        "decision_time": _utc(decision),
        "feature_cutoff": _utc(feature_cutoff),
        "parent_model_feature_cutoff": _utc(parent_model_cutoff or feature_cutoff),
        "ppo_feature_cutoff_semantics": loader_v1.PROFILED_TRAINING_PPO_CUTOFF_SEMANTICS,
        "available_at": _utc(auxiliary_available),
        "expected_holding_horizon_seconds": holding_horizon_seconds,
        "cost_capture_artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "cost_capture_artifact_byte_count": len(artifact),
        "cost_capture_receipt_sha256": cost_receipt["receipt_sha256"],
        "authoritative_fee_schedule_sha256": source_receipts["authoritative_fee_schedule"][
            "payload_sha256"
        ],
        "expected_notional_policy_sha256": source_receipts["expected_notional_policy"][
            "payload_sha256"
        ],
        "fee_schedule_receipt_sha256": source_receipts["authoritative_fee_schedule"][
            "receipt_sha256"
        ],
        "notional_policy_receipt_sha256": source_receipts["expected_notional_policy"][
            "receipt_sha256"
        ],
        "orderbook_depth_receipt_sha256": source_receipts["orderbook_depth"]["receipt_sha256"],
        "orderbook_features_receipt_sha256": source_receipts["orderbook_features"][
            "receipt_sha256"
        ],
        "mark_price_receipt_sha256": source_receipts["mark_price"]["receipt_sha256"],
        "auxiliary_feature_names": list(loader_v1.AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
        "auxiliary_source_labels": labels,
        "auxiliary_feature_receipt_sha256s": roots,
        "auxiliary_values_float32_sha256": loader_v1._auxiliary_values_sha256(auxiliary_values),
        "immutable_cost_store_root": str(cost_store.root_path),
        "immutable_cost_store_root_sha256": hashlib.sha256(
            str(cost_store.root_path).encode("utf-8")
        ).hexdigest(),
        "immutable_cost_object_inventory": [
            {
                "payload_sha256": digest,
                "payload_byte_count": count,
            }
            for digest, count in sorted(
                {
                    address.payload_sha256: address.payload_byte_count
                    for address in (
                        *(
                            cost_store.verify(
                                receipt["payload_sha256"],
                                expected_byte_count=receipt["read_evidence"]["payload_byte_count"],
                            )
                            for receipt in (
                                *source_receipts.values(),
                                cost_receipt,
                                *auxiliary_receipts,
                            )
                        ),
                        *(
                            cost_store.verify(
                                value["payload_sha256"],
                                expected_byte_count=value["payload_byte_count"],
                            )
                            for value in (
                                *(item["payload_cas_address"] for item in market_sources.values()),
                                *(
                                    item["direct_read_receipt_cas_address"]
                                    for item in market_sources.values()
                                ),
                                *fee_source.values(),
                                *notional_source.values(),
                            )
                        ),
                    )
                }.items()
            )
        ],
    }
    return (
        [*source_receipts.values(), cost_receipt, *auxiliary_receipts],
        labels,
        roots,
        binding,
    )


def _child_record(
    parent: dict[str, Any],
    *,
    cost_store_root: Path,
    parent_claim_mutator: Any | None = None,
    cost_binding_mutator: Any | None = None,
    attestation_mutator: Any | None = None,
    auxiliary_locator_type: str = "FILE_CONTENT_ADDRESS",
    holding_horizon_seconds: int = 900,
    direct_receipt_mutator: Any | None = None,
    corrupt_direct_receipt_self_hash_role: str | None = None,
    compact_orderbook_payload_clocks: bool = False,
    orderbook_payload_event_offset: timedelta | None = None,
) -> dict[str, Any]:
    parent_envelope = parent["frozen_envelope"]
    parent_decision = _parse(parent_envelope["tensor_decision_time"])
    parent_generated = _parse(parent_envelope["generated_at"])
    parent_cutoff = _parse(parent_envelope["feature_cutoff"])
    source_available = parent_generated
    source_observed = parent_generated
    capture_available = parent_generated + timedelta(microseconds=10)
    auxiliary_available = parent_generated + timedelta(microseconds=20)
    child_generated = parent_generated + timedelta(microseconds=30)
    if child_generated > parent_decision:
        raise AssertionError("parent fixture lacks causal enrichment clock budget")
    auxiliary_values = [1.5, 2.5, 3.5, -0.25]
    cost_store = ImmutableSourcePayloadStore(cost_store_root)
    cost_receipts, cost_labels, cost_roots, cost_binding = _cost_evidence(
        auxiliary_values,
        cost_store=cost_store,
        feature_snapshot_identity=parent["durable_snapshot_id"],
        symbol=parent_envelope["symbol"],
        decision=parent_decision,
        feature_cutoff=parent_cutoff,
        parent_model_cutoff=parent_cutoff,
        source_available=source_available,
        source_observed=source_observed,
        capture_available=capture_available,
        auxiliary_available=auxiliary_available,
        auxiliary_locator_type=auxiliary_locator_type,
        holding_horizon_seconds=holding_horizon_seconds,
        direct_receipt_mutator=direct_receipt_mutator,
        corrupt_direct_receipt_self_hash_role=(
            corrupt_direct_receipt_self_hash_role
        ),
        compact_orderbook_payload_clocks=compact_orderbook_payload_clocks,
        orderbook_payload_event_offset=orderbook_payload_event_offset,
    )
    parent_claim = _parent_binding(parent)
    if parent_claim_mutator is not None:
        parent_claim_mutator(parent_claim)
    if cost_binding_mutator is not None:
        cost_binding_mutator(cost_binding)
    attestation = {
        "schema_version": loader_v1.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION,
        "classification": loader_v1.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION,
        "status": loader_v1.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS,
        "profile_id": loader_v1.ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": loader_v1.ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        "base_registry_sha256": loader_v1.FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "base_abi_sha256": loader_v1.FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "logical_profile_selection_mask_sha256": (loader_v1.LOGICAL_PROFILE_SELECTION_MASK_SHA256),
        "logical_enabled_slot_ordinals_sha256": (loader_v1.LOGICAL_ENABLED_SLOT_ORDINALS_SHA256),
        "transform_implementation_id": (
            loader_v1.AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID
        ),
        "transform_implementation_sha256": (
            loader_v1.AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        ),
        "transform_configuration_sha256": (
            loader_v1.AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        ),
        "projection_schema_version": (loader_v1.PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION),
        "projection_implementation_sha256": (
            loader_v1.PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
        ),
        "projection_configuration_sha256": (
            loader_v1.PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
        ),
        "physical_feature_count": 39,
        "physical_ordered_feature_names_sha256": (
            loader_v1.PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256
        ),
        "parent_model_record_binding": parent_claim,
        "cost_capture_binding": cost_binding,
        "authorization": dict(loader_v1._EXPECTED_AUTHORIZATION),
    }
    if attestation_mutator is not None:
        attestation_mutator(attestation)
    parent_receipts = parent_envelope["source_read_receipts"]
    return build_feature_snapshot_record(
        provenance_classification=PROVENANCE_CANONICAL_V3,
        legacy_v1_snapshot_id=None,
        symbol=parent_envelope["symbol"],
        timeframe=parent_envelope["timeframe"],
        feature_snapshot_id="authenticated-profile-training-enrichment",
        tensor_decision_time=parent_envelope["tensor_decision_time"],
        temporal_rejection_reasons=[],
        ordered_feature_names=(loader_v1.PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES),
        feature_values=[*parent_envelope["feature_values"], *auxiliary_values],
        missing_mask=[0] * 39,
        stale_mask=[0] * 39,
        source_availability_mask=[1] * 39,
        ordered_feature_source_labels=[
            *parent_envelope["ordered_feature_source_labels"],
            *cost_labels,
        ],
        feature_source_receipt_sha256s=[
            *parent_envelope["feature_source_receipt_sha256s"],
            *cost_roots,
        ],
        source_read_receipts=[*parent_receipts, *cost_receipts],
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"] * 39,
        original_tensor_id="profiled-training-enrichment-tensor",
        source_lineage_material={
            loader_v1.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY: attestation
        },
        feature_cutoff=cost_binding["feature_cutoff"],
        masa_feature_cutoff=parent_envelope["masa_feature_cutoff"],
        ppo_feature_cutoff=cost_binding["feature_cutoff"],
        ppo_decision_time=parent_envelope["ppo_decision_time"],
        generated_at=_utc(child_generated),
    )


def _observation() -> str:
    return _utc(
        max(
            datetime.now(tz=UTC) + timedelta(seconds=10),
            datetime(2026, 7, 22, tzinfo=UTC),
        )
    )


def _append_after_latest_decision(
    ledger: DurableFeatureSnapshotLedger,
    records: list[dict[str, Any]],
) -> Any:
    latest_decision = max(
        _parse(record["frozen_envelope"]["ppo_decision_time"]) for record in records
    )
    commit_clock = _utc(
        max(
            latest_decision + timedelta(seconds=1),
            datetime.now(tz=UTC) + timedelta(seconds=1),
        )
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(feature_ledger_module, "utc_now", lambda: commit_clock)
        return ledger.append_snapshots(records)


@pytest.fixture(scope="module")
def authenticated_base_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    from v2.backend.tests.unit.services.native_trainer import (
        test_profiled_model_feature_snapshot_record_v1 as base_support,
    )

    return base_support._build_evidence(tmp_path_factory.mktemp("loader-authenticated-base"))


def _ledger_with_pair(
    tmp_path: Path,
    parent: dict[str, Any],
    **child_kwargs: Any,
) -> tuple[DurableFeatureSnapshotLedger, dict[str, Any], dict[str, Any]]:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    child = _child_record(
        parent,
        cost_store_root=tmp_path / "cost-cas",
        **child_kwargs,
    )
    result = _append_after_latest_decision(ledger, [parent, child])
    assert result.inserted_rows == 2
    return ledger, parent, child


def _generic_same_width_record(*, suffix: str = "") -> dict[str, Any]:
    identity_suffix = f"-{suffix}" if suffix else ""
    receipts = [
        _receipt(
            label=f"generic{identity_suffix}:{index}",
            payload=f"generic{identity_suffix}:{index}".encode(),
        )
        for index in range(39)
    ]
    return build_feature_snapshot_record(
        provenance_classification=PROVENANCE_CANONICAL_V3,
        legacy_v1_snapshot_id=None,
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id=f"generic-same-width{identity_suffix}",
        tensor_decision_time=_utc(DECISION),
        temporal_rejection_reasons=[],
        ordered_feature_names=[f"generic_feature_{index}" for index in range(39)],
        feature_values=[float(index) for index in range(39)],
        missing_mask=[0] * 39,
        stale_mask=[0] * 39,
        source_availability_mask=[1] * 39,
        ordered_feature_source_labels=[receipt["source_label"] for receipt in receipts],
        feature_source_receipt_sha256s=[receipt["receipt_sha256"] for receipt in receipts],
        source_read_receipts=receipts,
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"] * 39,
        original_tensor_id=f"generic-same-width-tensor{identity_suffix}",
        source_lineage_material={"schema_version": "generic_same_width_v1"},
        feature_cutoff=_utc(CUTOFF),
        masa_feature_cutoff=_utc(CUTOFF),
        ppo_feature_cutoff=_utc(CUTOFF),
        ppo_decision_time=_utc(DECISION),
        generated_at=_utc(GENERATED),
    )


def test_loads_only_atomic_authenticated_39_and_reconstructs_exact_446_1784(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    parent = authenticated_base_evidence.record
    ledger, parent, child = _ledger_with_pair(tmp_path, parent)

    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
        training_observed_at=_observation(),
    )

    assert len(batch.samples) == 1
    assert batch.exclusions == ()
    sample = batch.samples[0]
    assert sample.durable_snapshot_id == child["durable_snapshot_id"]
    assert sample.parent_durable_snapshot_id == parent["durable_snapshot_id"]
    assert len(sample.physical_feature_values) == 39
    assert len(sample.logical_feature_values) == 446
    assert len(sample.logical_model_vector) == 1784
    assert sum(sample.logical_profile_selection_mask) == 35
    assert sample.logical_enabled_slot_ordinals == tuple(
        index
        for index, selected in enumerate(sample.logical_profile_selection_mask)
        if selected == 1
    )
    assert sample.logical_source_availability_mask == sample.logical_profile_selection_mask
    assert sample.logical_missing_mask == (0,) * 446
    assert sample.logical_stale_mask == (0,) * 446
    assert sample.logical_model_vector_sha256 == loader_v1._model_vector_sha256(
        sample.logical_model_vector
    )
    assert sample.append_transaction_id.startswith("feature_snapshot_append_")
    assert sample.ledger_high_water_sha256 == batch.high_water_sha256
    assert batch.authenticated_prefix_record_count == 2
    assert batch.append_postcommit_high_water_verified is True
    assert batch.page_integrity_semantics == loader_v1.PROFILED_TRAINING_PAGE_INTEGRITY_SEMANTICS
    assert (
        batch.runtime_scalability_status == loader_v1.PROFILED_TRAINING_RUNTIME_SCALABILITY_STATUS
    )
    assert batch.runtime_wired is False
    assert sample.trainer_admission_authorized is True
    assert sample.prediction_authorized is False
    assert sample.live_execution_authorized is False


def test_accepts_producer_clock_precision_after_authenticated_normalization(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        compact_orderbook_payload_clocks=True,
    )

    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
        training_observed_at=_observation(),
    )

    assert [sample.durable_snapshot_id for sample in batch.samples] == [
        child["durable_snapshot_id"]
    ]


def test_rejects_orderbook_payload_clock_instant_substitution(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        compact_orderbook_payload_clocks=True,
        orderbook_payload_event_offset=timedelta(microseconds=1),
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_ORDERBOOK_CLOCK_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_nonadjacent_parent_child_in_same_transaction_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    parent = authenticated_base_evidence.record
    child = _child_record(
        parent,
        cost_store_root=tmp_path / "nonadjacent-cost-cas",
    )
    generic = _generic_same_width_record(suffix="between-parent-and-child")

    result = _append_after_latest_decision(ledger, [parent, generic, child])

    assert result.inserted_rows == 3
    committed = [
        ledger.get_snapshot(record["durable_snapshot_id"]) for record in (parent, generic, child)
    ]
    assert all(item is not None for item in committed)
    assert [item.sequence for item in committed if item is not None] == [1, 2, 3]
    assert len({item.append_transaction_id for item in committed if item is not None}) == 1
    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_PARENT_ATOMIC_APPEND_OR_CLOCK_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "nonadjacent-cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_same_width_generic_record_is_explicitly_excluded(tmp_path: Path) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    record = _generic_same_width_record()
    ledger.append_snapshot(record)

    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
        training_observed_at=_observation(),
    )

    assert batch.samples == ()
    assert len(batch.exclusions) == 1
    assert batch.exclusions[0].reason == ("NOT_AUTHENTICATED_PROFILED_TRAINING_ENRICHMENT")


def test_fixed_observation_pages_are_disjoint_and_cross_small_page_limit(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    generic = _generic_same_width_record(suffix="page-prefix")
    ledger.append_snapshot(generic)
    parent = authenticated_base_evidence.record
    child = _child_record(parent, cost_store_root=tmp_path / "page-cost-cas")
    appended = _append_after_latest_decision(ledger, [parent, child])
    assert appended.inserted_rows == 2
    observation = _observation()

    first = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "page-cost-cas").absolute(),
        training_observed_at=observation,
        scan_limit=1,
    )
    second = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "page-cost-cas").absolute(),
        training_observed_at=observation,
        scan_limit=1,
        after_sequence=first.next_after_sequence,
        page_cursor=first.next_cursor,
    )

    assert first.authenticated_prefix_record_count == 3
    assert "FULL_LEDGER" in first.page_integrity_semantics
    assert "O_TOTAL_LEDGER_PER_PAGE" in first.runtime_scalability_status
    assert first.runtime_wired is False
    assert first.requested_after_sequence == 0
    assert first.scanned_start_sequence == first.scanned_end_sequence == 1
    assert first.scanned_record_count == 1
    assert first.scan_truncated is True
    assert first.has_remaining_strict_rows is True
    assert first.next_after_sequence == 1
    assert first.next_cursor is not None
    assert first.samples == ()
    assert len(first.exclusions) == 1
    assert second.requested_after_sequence == first.next_after_sequence
    assert second.requested_cursor_sha256 == json.loads(first.next_cursor)["cursor_sha256"]
    assert second.scanned_start_sequence == second.scanned_end_sequence == 3
    assert second.scanned_record_count == 1
    assert second.scan_truncated is False
    assert second.has_remaining_strict_rows is False
    assert second.next_cursor is None
    assert len(second.samples) == 1
    assert second.samples[0].durable_snapshot_id == child["durable_snapshot_id"]
    assert {
        *(item.sequence for item in first.exclusions),
        *(item.sequence for item in second.samples),
    } == {1, 3}


def test_page_cursor_tamper_fails_closed(tmp_path: Path) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    records = [
        _generic_same_width_record(suffix="cursor-a"),
        _generic_same_width_record(suffix="cursor-b"),
    ]
    appended = ledger.append_snapshots(records)
    assert appended.inserted_rows == 2
    observation = _observation()
    first = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
        training_observed_at=observation,
        scan_limit=1,
    )
    assert first.next_cursor is not None
    tampered = json.loads(first.next_cursor)
    tampered["next_after_sequence"] += 1
    tampered_cursor = json.dumps(
        tampered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_PAGE_CURSOR_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
            training_observed_at=observation,
            scan_limit=1,
            after_sequence=first.next_after_sequence,
            page_cursor=tampered_cursor,
        )


def test_concurrent_visible_append_cannot_cross_fixed_page_high_water(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    ledger.append_snapshot(_generic_same_width_record(suffix="concurrent-before"))
    concurrent = _generic_same_width_record(suffix="concurrent-after")
    real = loader_v1.feature_ledger_fixed_observation_high_water
    calls = 0

    def append_after_first_high_water(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        material = real(**kwargs)
        if calls == 1:
            result = ledger.append_snapshot(concurrent)
            assert result.inserted_rows == 1
        return material

    monkeypatch.setattr(
        loader_v1,
        "feature_ledger_fixed_observation_high_water",
        append_after_first_high_water,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_PAGE_EXCEEDED_FIXED_HIGH_WATER",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
            training_observed_at=_observation(),
            scan_limit=2,
        )


def test_legacy_record_can_never_enter_profiled_training_query(tmp_path: Path) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    receipt = _receipt(label="legacy:source", payload=b"legacy-source")
    legacy = build_feature_snapshot_record(
        provenance_classification=PROVENANCE_LEGACY_V1_IMPORT,
        legacy_v1_snapshot_id="legacy-profile-width-record",
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id="legacy-profile-width-record",
        tensor_decision_time=_utc(DECISION),
        temporal_rejection_reasons=[],
        ordered_feature_names=["legacy_feature"],
        feature_values=[1.0],
        missing_mask=[0],
        stale_mask=[0],
        source_availability_mask=[1],
        ordered_feature_source_labels=[receipt["source_label"]],
        feature_source_receipt_sha256s=[receipt["receipt_sha256"]],
        source_read_receipts=[receipt],
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"],
        original_tensor_id="legacy-profile-width-tensor",
        source_lineage_material={"schema_version": "legacy_import_v1"},
        feature_cutoff=_utc(CUTOFF),
        masa_feature_cutoff=_utc(CUTOFF),
        ppo_feature_cutoff=_utc(CUTOFF),
        ppo_decision_time=_utc(DECISION),
        generated_at=_utc(GENERATED),
    )
    ledger.append_snapshot(legacy)

    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
        training_observed_at=_observation(),
    )

    assert batch.samples == ()
    assert batch.exclusions == ()
    assert batch.authenticated_prefix_record_count == 1


def test_parent_hash_mismatch_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    def mutate_parent(claim: dict[str, Any]) -> None:
        claim["record_sha256"] = "f" * 64

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        parent_claim_mutator=mutate_parent,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_PARENT_BINDING_MISMATCH",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_mutable_auxiliary_receipt_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        auxiliary_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_AUXILIARY_NOT_CAUSAL_IMMUTABLE",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_late_cost_binding_claim_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    def make_late(binding: dict[str, Any]) -> None:
        binding["available_at"] = _utc(_parse(binding["decision_time"]) + timedelta(microseconds=1))

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        cost_binding_mutator=make_late,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_cost_store_record_path_redirection_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    attacker_store = ImmutableSourcePayloadStore(tmp_path / "attacker-cost-cas")

    def redirect_store(binding: dict[str, Any]) -> None:
        attacker_root = str(attacker_store.root_path)
        binding["immutable_cost_store_root"] = attacker_root
        binding["immutable_cost_store_root_sha256"] = hashlib.sha256(
            attacker_root.encode("utf-8")
        ).hexdigest()

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        cost_binding_mutator=redirect_store,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_STORE_TRUST_ROOT_MISMATCH",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_orderbook_features_cost_root_omission_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    def omit_features(binding: dict[str, Any]) -> None:
        binding.pop("orderbook_features_receipt_sha256")

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        cost_binding_mutator=omit_features,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_BINDING_FIELDS_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_orderbook_features_cost_root_substitution_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    def substitute_depth(binding: dict[str, Any]) -> None:
        binding["orderbook_features_receipt_sha256"] = binding["orderbook_depth_receipt_sha256"]

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        cost_binding_mutator=substitute_depth,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_CAPTURE_RECEIPT_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_pinned_cost_implementation_rejects_unversioned_horizon_change(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        holding_horizon_seconds=(
            loader_v1.CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS + 1
        ),
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_market_direct_receipt_payload_substitution_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    def substitute_depth_payload(role: str, direct: dict[str, Any]) -> None:
        if role == "orderbook_depth":
            direct["payload_sha256"] = "0" * 64

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        direct_receipt_mutator=substitute_depth_payload,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_DIRECT_RECEIPT_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_market_direct_receipt_self_hash_substitution_fails_closed(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        corrupt_direct_receipt_self_hash_role="orderbook_depth",
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_DIRECT_RECEIPT_BINDING_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_direct_reopen_rejects_ledger_rollback_below_signed_frontier(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
    )
    rolled_path = tmp_path / "rolled-feature-ledger.sqlite3"
    shutil.copy2(ledger.path, rolled_path)
    rolled_ledger = DurableFeatureSnapshotLedger(rolled_path)
    suffix = _generic_same_width_record(suffix="signed-frontier-suffix")
    result = _append_after_latest_decision(ledger, [suffix])
    assert result.inserted_rows == 1
    observation = _observation()
    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
        training_observed_at=observation,
    )
    sample = next(
        item
        for item in batch.samples
        if item.durable_snapshot_id == child["durable_snapshot_id"]
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_DIRECT_REOPEN_LEDGER_READ_FAILED",
    ):
        loader_v1.reopen_profiled_training_ledger_sample_v1(
            ledger=rolled_ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            fixed_observation_high_water=batch.high_water,
            training_observed_at=observation,
            durable_snapshot_id=sample.durable_snapshot_id,
            expected_sequence=sample.sequence,
            expected_record_sha256=sample.record_sha256,
        )


def test_quarantined_caller_scalar_projection_digest_is_rejected(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    from v2.backend.app.services.native_trainer.profiled_feature_snapshot_projection_v1 import (
        PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256,
    )

    def substitute_unsafe_projection(attestation: dict[str, Any]) -> None:
        attestation["projection_implementation_sha256"] = (
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
        )

    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
        attestation_mutator=substitute_unsafe_projection,
    )

    assert (
        PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
        != loader_v1.PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
    )
    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_ENRICHMENT_ATTESTATION_INVALID",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_authenticated_high_water_movement_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_base_evidence: Any,
) -> None:
    ledger, _parent, _child = _ledger_with_pair(
        tmp_path,
        authenticated_base_evidence.record,
    )
    real = loader_v1.feature_ledger_fixed_observation_high_water
    calls = 0

    def moving_high_water(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        material = real(**kwargs)
        if calls == 2:
            material = copy.deepcopy(material)
            material["ordered_projection_receipts_sha256"] = "0" * 64
            unsigned = {key: value for key, value in material.items() if key != "high_water_sha256"}
            material["high_water_sha256"] = stable_sha256(unsigned)
        return material

    monkeypatch.setattr(
        loader_v1,
        "feature_ledger_fixed_observation_high_water",
        moving_high_water,
    )

    with pytest.raises(
        loader_v1.ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_AUTHENTICATED_HIGH_WATER_MOVED_DURING_LOAD",
    ):
        loader_v1.load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
            training_observed_at=_observation(),
        )


def test_parent_35_is_never_returned_as_training_candidate(
    tmp_path: Path,
    authenticated_base_evidence: Any,
) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    parent = authenticated_base_evidence.record
    result = _append_after_latest_decision(ledger, [parent])
    assert result.inserted_rows == 1

    batch = loader_v1.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=(tmp_path / "unused-cost-cas").absolute(),
        training_observed_at=_observation(),
    )

    assert batch.samples == ()
    assert batch.exclusions == ()
    assert batch.authenticated_prefix_record_count == 1


def test_profile_contract_retains_true_1h_and_no_proxy_semantics() -> None:
    families = {
        family.physical_timeframe: family
        for family in (
            ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.timeframe_finality_transform_contracts
        )
    }
    assert set(families) == {"5m", "1h"}
    assert families["1h"].proxy_higher_timeframe_allowed is False
    assert families["1h"].unfinished_candles_allowed is False


def test_loader_parent_verifier_matches_real_authenticated_base_builder(
    authenticated_base_evidence: Any,
) -> None:
    from v2.backend.tests.unit.services.native_trainer import (
        test_profiled_model_feature_snapshot_record_v1 as base_support,
    )

    evidence = authenticated_base_evidence
    exact_validation = base_support._validate(evidence)
    item = FixedCutoffFeatureSnapshot(
        sequence=1,
        record=evidence.record,
        append_transaction_id="feature_snapshot_append_" + "1" * 64,
        append_receipt_sha256="2" * 64,
        postcommit_receipt_sha256="3" * 64,
        postcommit_readback_at="2026-07-21T12:00:01.000000Z",
    )

    loader_validation = loader_v1._validate_parent_model_record(item)

    assert loader_validation["binding"] == exact_validation.lineage_binding
    assert len(loader_validation["model_vector"]) == 1784
