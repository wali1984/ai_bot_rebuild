from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Iterator, Mapping, Sequence
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from typing import Any

import pytest

from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    PAPER_ALLOCATOR_ARITHMETIC_FORMULA,
    PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY,
    PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION,
    PAPER_ALLOCATOR_ARITHMETIC_VERSION,
    PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY,
    PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY,
    allocate_paper_candidate,
    allocation_input_material,
    build_paper_liquidation_atr_evidence,
    canonical_allocation_input_hash,
)
from v2.backend.app.services.adaptive_capital_allocator.contracts import (
    AllocationInput,
    RiskEnvelope,
)
from v2.backend.app.services.paper_trade_management import (
    cycle_reservation as cycle_reservation_module,
)
from v2.backend.app.services.paper_trade_management.cycle_reservation import (
    CYCLE_RESERVATION_LINEAGE_KEY,
    CycleReservationError,
    build_candidate_commit_receipt,
    build_cycle_reservation_snapshot,
    candidate_commit_receipt_rejection_reasons,
    cycle_reservation_persisted_row_projection,
    cycle_reservation_snapshot_rejection_reasons,
    intrinsic_candidate_commit_receipt_rejection_reasons,
    validate_candidate_commit_receipt,
    validate_intrinsic_candidate_commit_receipt,
)
from v2.backend.tests.unit.services.adaptive_capital_allocator.growth_receipt_test_utils import (
    allocate_authorized_growth,
)


def _hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decision_record_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _allocator_arithmetic_receipt(
    *,
    raw_quantity: float,
    input_price: float,
    raw_notional: float,
    selected_leverage: float,
) -> dict[str, str]:
    material = {
        "schema_version": PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION,
        "arithmetic_version": PAPER_ALLOCATOR_ARITHMETIC_VERSION,
        "formula": PAPER_ALLOCATOR_ARITHMETIC_FORMULA,
        "raw_post_step_quantity_binary64_hex": raw_quantity.hex(),
        "input_price_binary64_hex": input_price.hex(),
        "raw_post_step_notional_binary64_hex": raw_notional.hex(),
        "selected_leverage_binary64_hex": selected_leverage.hex(),
    }
    return {**material, "receipt_sha256": _hash(material)}


def _allocation(
    symbol: str,
    *,
    notional: float,
    margin: float,
    max_loss: float,
    leverage: float | None = None,
    price: float = 100.0,
    timeframe: str = "1m",
    action: str = "long",
    snapshot_hash: str | None = None,
    suffix: str = "candidate",
) -> dict[str, Any]:
    lineage = {
        "intent_id": f"intent-{suffix}",
        "signal_id": f"signal-{suffix}",
        "prediction_id": f"prediction-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "orchestrator_decision_id": f"orchestrator-{suffix}",
    }
    if snapshot_hash is not None:
        lineage[CYCLE_RESERVATION_LINEAGE_KEY] = snapshot_hash
    selected_leverage = leverage if leverage is not None else notional / margin
    material = {
        "schema_version": "adaptive_capital_allocation_input_v1",
        "mode": "paper",
        "allocation_input": {
            "symbol": symbol,
            "timeframe": timeframe,
            "action": action,
            "price": price,
            "permitted_leverage_values": (selected_leverage,),
            "lineage_ids": copy.deepcopy(lineage),
        },
        "risk_envelope": {"fixture": suffix},
    }
    input_hash = _hash(material)
    quantity = notional / price
    raw_notional = abs(quantity * price)
    arithmetic_receipt = _allocator_arithmetic_receipt(
        raw_quantity=quantity,
        input_price=price,
        raw_notional=raw_notional,
        selected_leverage=selected_leverage,
    )
    return {
        "allocation_id": f"alloc_{input_hash[:24]}",
        "allocation_input_schema_version": "adaptive_capital_allocation_input_v1",
        "allocation_input_hash": input_hash,
        "allocation_input_hash_algorithm": "sha256(canonical-json-v1)",
        "allocation_input_material": material,
        "model_inputs": {
            "allocation_input_schema_version": "adaptive_capital_allocation_input_v1",
            "allocation_input_hash": input_hash,
            "allocation_input_hash_algorithm": "sha256(canonical-json-v1)",
            "paper_post_quantization_exchange_filter_status": "PASS",
            "paper_margin_configuration_uses_post_quantization_notional": True,
            "paper_target_quantity_after_step_quantization": quantity,
            "paper_target_notional_after_step_quantization_usd": notional,
            "max_loss_usd": max_loss,
            "paper_modeled_loss_bps": max_loss / notional * 10_000.0,
            "selected_leverage": selected_leverage,
            "selected_allocated_margin_usd": margin,
            PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY: arithmetic_receipt,
        },
        "allocator_decision": "ALLOW_WITH_SIZE",
        "symbol": symbol,
        "timeframe": timeframe,
        "action": action,
        "target_quantity": quantity,
        "target_notional_usdt": notional,
        "target_notional_usd": notional,
        "gross_notional_usd": notional,
        "recommended_leverage": selected_leverage,
        "effective_leverage": selected_leverage,
        "allocated_margin_usd": margin,
        "margin_mode": "isolated_paper_simulated",
        "recommended_margin_mode": "isolated_paper_simulated",
        "max_loss_if_stop_hit": max_loss,
        "max_loss_usd": max_loss,
        "lineage_ids": copy.deepcopy(lineage),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    }


def _tuning_semantic_receipt(
    *,
    session_id: str,
    state_payload_hash: str,
    observed_at: str,
) -> dict[str, Any]:
    material = {
        "schema_version": "paper_adaptive_tuning_semantic_validation_v1",
        "status": "PASS",
        "canonical_redis_key": "v2:orchestrator:adaptive_gate_tuning_state",
        "state_payload_hash": state_payload_hash,
        "current_paper_session_id": session_id,
        "state_paper_session_id": session_id,
        "policy_id": "fixture-adaptive-policy",
        "producer": "fixture-adaptive-tuning-producer",
        "available_at": "2026-07-17T11:59:50Z",
        "observed_at": observed_at,
        "expires_at": "2026-07-17T12:05:00Z",
        "rejection_reasons": [],
    }
    return {**material, "receipt_hash": _hash(material)}


def _revocable_receipt(*, suffix: str) -> dict[str, Any]:
    session_id = f"paper-session-{suffix}"
    source_receipts: dict[str, dict[str, Any]] = {}
    for role, keys in cycle_reservation_module._REVOCABLE_SOURCE_KEYS_BY_ROLE.items():
        source_hash = _hash({"role": role, "suffix": suffix})
        source_receipts[role] = {
            "source_kind": "REDIS_EXACT_KEY",
            "source_key": sorted(keys)[0],
            "read_status": "READY",
            "present": True,
            "frozen_hash": source_hash,
            "current_hash": source_hash,
            "exact_match": True,
            "source_label_match": True,
        }
    source_receipts["paper_session_source"].update(
        {
            "resolved_paper_session_id": session_id,
            "semantic_status": "PASS",
            "semantic_rejection_reasons": [],
        }
    )
    tuning_state_hash = _hash({"source": "adaptive-tuning-state", "suffix": suffix})
    initial_tuning = _tuning_semantic_receipt(
        session_id=session_id,
        state_payload_hash=tuning_state_hash,
        observed_at="2026-07-17T11:59:59.250000Z",
    )
    commit_tuning = _tuning_semantic_receipt(
        session_id=session_id,
        state_payload_hash=tuning_state_hash,
        observed_at="2026-07-17T12:00:00Z",
    )
    source_receipts["adaptive_tuning_source"].update(
        {
            "semantic_validation": initial_tuning,
            "semantic_validation_status": "PASS",
            "semantic_validation_receipt_hash": initial_tuning["receipt_hash"],
            "commit_clock_semantic_validation": commit_tuning,
            "commit_clock_semantic_validation_status": "PASS",
            "commit_clock_semantic_validation_receipt_hash": commit_tuning["receipt_hash"],
        }
    )
    freeze_hash = _hash({"source": "effective-freeze", "suffix": suffix})
    risk_hash = _hash({"source": "risk-state", "suffix": suffix})
    owner_projection = {
        "schema_version": "paper_runtime_owner_minimal_projection_v1",
        "status": "PASS_ACTIVE_RUNTIME_OWNER_VALIDATION",
        "active_new_entry_owner": "v2_trade_management_paper_loop",
        "canonical_paper_writer_count": 1,
        "canonical_service_scope_writer_count": 1,
        "forbidden_entry_process_count": 0,
        "duplicate_paper_writer_count": 0,
        "current_process_is_only_canonical_writer": True,
        "paper_online_runtime_active": False,
        "paper_online_runtime_enabled": False,
        "canonical_paper_runtime_enabled": True,
        "toy_momentum_entry_writer_active": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "pass_conditions": {
            condition: True
            for condition in cycle_reservation_module._RUNTIME_OWNER_REQUIRED_PASS_CONDITIONS
        },
    }
    owner_hash = _hash(owner_projection)
    material = {
        "schema_version": "paper_revocable_control_commit_revalidation_v1",
        "status": "PASS",
        "validation_started_at": "2026-07-17T11:59:59Z",
        "checked_at": "2026-07-17T12:00:00Z",
        "source_revalidation": source_receipts,
        "guardian": {
            "currently_allows_execution_tier": True,
            "ttl_remaining_seconds": 120,
            "ttl_required_range_seconds": [1, 180],
            "ttl_valid": True,
        },
        "effective_entry_freeze": {
            "frozen_hash": freeze_hash,
            "current_hash": freeze_hash,
            "exact_match": True,
            "paper_new_entries_halted": False,
            "nonoverridable": False,
            "tier_override_allowed": False,
        },
        "current_risk_state": {
            "frozen_hash": risk_hash,
            "current_hash": risk_hash,
            "exact_match": True,
        },
        "runtime_owner": {
            "frozen_hash": owner_hash,
            "current_hash": owner_hash,
            "exact_match": True,
            "current_projection": owner_projection,
            "current_projection_allows": True,
        },
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "cross_process_atomic": False,
        "residual_toctou_risk": (
            "CONTROL_OR_OWNER_CAN_CHANGE_AFTER_FINAL_REREAD_BEFORE_IN_PROCESS_LIST_APPEND"
        ),
        "rejection_reasons": [],
    }
    return {**material, "receipt_hash": _hash(material)}


def _final_admitted_row(
    symbol: str,
    *,
    notional: float,
    margin: float,
    max_loss: float,
    suffix: str,
    prior_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    accepted_prefix = prior_rows or []
    cycle_snapshot = build_cycle_reservation_snapshot(
        cycle_identity=f"paper-prior-cycle-{suffix}",
        candidate_symbol=symbol,
        base_resource_evidence_hash=_hash({"source": "prior-portfolio", "suffix": suffix}),
        precycle_exposure_snapshot_hash=_hash({"source": "prior-current-marks", "suffix": suffix}),
        dynamic_envelope_evidence_hash=_hash(
            {"source": "prior-dynamic-envelope", "suffix": suffix}
        ),
        base_equity_usd=100_000.0,
        base_available_margin_usd=100_000.0,
        realized_drawdown_fraction_of_equity=0.0,
        precycle_total_notional_usd=0.0,
        precycle_symbol_current_mark_notional_usd=0.0,
        precycle_open_projected_max_loss_usd=0.0,
        max_total_portfolio_risk_pct=10.0,
        max_single_symbol_exposure_pct=10.0,
        min_available_margin_buffer_pct=0.0,
        max_daily_drawdown_pct=10.0,
        max_loss_per_trade_pct=10.0,
        emergency_absolute_cap_usdt=None,
        prior_accepted_rows=accepted_prefix,
    )
    allocation = _allocation(
        symbol,
        notional=notional,
        margin=margin,
        max_loss=max_loss,
        snapshot_hash=cycle_snapshot["snapshot_hash"],
        suffix=suffix,
    )
    cycle_commit = build_candidate_commit_receipt(
        snapshot=cycle_snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=accepted_prefix,
    )
    revocable_receipt = _revocable_receipt(suffix=suffix)
    allocation_hash = _hash(allocation)
    cycle_contract = {
        "paper_cycle_reservation_snapshot": copy.deepcopy(cycle_snapshot),
        "paper_cycle_reservation_snapshot_hash": cycle_snapshot["snapshot_hash"],
        "paper_cycle_reservation_commit_receipt": copy.deepcopy(cycle_commit),
        "paper_cycle_reservation_commit_receipt_hash": cycle_commit["receipt_hash"],
        "paper_cycle_reservation_commit_status": "PASS",
        "cycle_identity": cycle_snapshot["cycle_identity"],
    }
    price = 100.0
    quantity = notional / price
    leverage = notional / margin
    row: dict[str, Any] = {
        "intent_id": f"intent-{suffix}",
        "signal_id": f"signal-{suffix}",
        "prediction_id": f"prediction-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "orchestrator_decision_id": f"orchestrator-{suffix}",
        "allocation_id": allocation["allocation_id"],
        "preemptive_decision_id": f"preemptive-{suffix}",
        "symbol": symbol,
        "timeframe": "1m",
        "side": "long",
        "paper_opportunity_tier": "A_GRADE_EXECUTION_PAPER",
        "paper_opportunity_tier_reason": "STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED",
        "paper_fill_allowed_source": "STRICT_UPSTREAM_PAPER_FILL_GATE",
        "decision": "ACCEPTED_PAPER_FILL",
        "paper_fill_allowed": True,
        "valid_for_paper": True,
        "risk_controller_decision": "allow",
        "orchestrator_decision": "proceed_long",
        "paper_precycle_exposure_snapshot_started_at": "2026-07-17T11:59:55Z",
        "paper_precycle_exposure_snapshot_completed_at": "2026-07-17T11:59:57Z",
        "paper_allocation_decision_time": "2026-07-17T11:59:58Z",
        "quantity": quantity,
        "target_quantity": quantity,
        "fill_price": price,
        "entry_price": price,
        "notional": notional,
        "target_notional_usd": notional,
        "target_notional_usdt": notional,
        "gross_notional_usd": notional,
        "recommended_leverage": leverage,
        "effective_leverage": leverage,
        "allocated_margin_usd": margin,
        "margin_mode_simulated": "isolated_paper_simulated",
        "recommended_margin_mode": "isolated_paper_simulated",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "adaptive_allocation": allocation,
        "paper_cycle_reservation_snapshot": copy.deepcopy(cycle_snapshot),
        "paper_cycle_reservation_snapshot_hash": cycle_snapshot["snapshot_hash"],
        "paper_cycle_reservation_status": "PASS",
        "paper_cycle_reservation_commit_receipt": copy.deepcopy(cycle_commit),
        "paper_cycle_reservation_commit_receipt_hash": cycle_commit["receipt_hash"],
        "paper_cycle_reservation_commit_status": "PASS",
        "paper_revocable_control_commit_revalidation": copy.deepcopy(revocable_receipt),
        "paper_revocable_control_commit_revalidation_receipt_hash": (
            revocable_receipt["receipt_hash"]
        ),
        "paper_revocable_control_commit_revalidation_status": "PASS",
    }
    risk_key = f"v2:decision:risk:{row['risk_decision_id']}"
    orchestrator_key = f"v2:decision:orchestrator:{row['orchestrator_decision_id']}"
    shared_decision_identity = {
        "symbol": symbol,
        "timeframe": "1m",
        "side": "long",
        "prediction_id": row["prediction_id"],
        "signal_id": row["signal_id"],
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": "BLOCKED",
    }
    risk_record = {
        "schema_version": "v2_per_id_risk_decision_record_v1",
        "producer": "v2_risk_gateway_live_loop",
        "_decision_record_key": risk_key,
        "_decision_record_store": "PER_ID_DECISION_RECORD",
        "risk_decision_id": row["risk_decision_id"],
        "orchestrator_decision_id": row["orchestrator_decision_id"],
        "risk_action": "allow",
        **shared_decision_identity,
    }
    orchestrator_record = {
        "schema_version": "v2_per_id_orchestrator_decision_record_v1",
        "producer": "v2_orchestrator_arbitration_loop",
        "_decision_record_key": orchestrator_key,
        "_decision_record_store": "PER_ID_DECISION_RECORD",
        "orchestrator_decision_id": row["orchestrator_decision_id"],
        "orchestrator_action": "proceed_long",
        **shared_decision_identity,
    }
    risk_record_hash = _decision_record_hash(risk_record)
    orchestrator_record_hash = _decision_record_hash(orchestrator_record)
    preemptive_input_material = {
        "schema_version": "preemptive_edge_control_input_v2",
        "candidate": {
            "symbol": symbol,
            "timeframe": "1m",
            "side": "long",
            "prediction_id": row["prediction_id"],
            "signal_id": row["signal_id"],
            "risk_decision_id": row["risk_decision_id"],
            "orchestrator_decision_id": row["orchestrator_decision_id"],
        },
    }
    preemptive_input_hash = _hash(preemptive_input_material)
    preemptive_receipt = {
        "preemptive_decision_id": row["preemptive_decision_id"],
        "preemptive_input_hash": preemptive_input_hash,
        "preemptive_input_material": preemptive_input_material,
    }
    row.update(
        {
            "risk_decision_record": risk_record,
            "risk_decision_record_hash": risk_record_hash,
            "risk_decision_record_key": risk_key,
            "risk_decision_record_resolved": True,
            "risk_decision_source": "PER_ID_DECISION_RECORD",
            "orchestrator_decision_record": orchestrator_record,
            "orchestrator_decision_record_hash": orchestrator_record_hash,
            "orchestrator_decision_record_key": orchestrator_key,
            "orchestrator_decision_record_resolved": True,
            "orchestrator_decision_source": "PER_ID_DECISION_RECORD",
            "preemptive_input_hash": preemptive_input_hash,
            "preemptive_edge_control": preemptive_receipt,
        }
    )
    decision_record_revalidation = {
        "risk": {
            "source_key": risk_key,
            "record_hash": risk_record_hash,
            "observed_at": "2026-07-17T11:59:59.500000Z",
            "exact_match": True,
        },
        "orchestrator": {
            "source_key": orchestrator_key,
            "record_hash": orchestrator_record_hash,
            "observed_at": "2026-07-17T11:59:59.500000Z",
            "exact_match": True,
        },
    }
    preemptive_revalidation = {
        "status": "PASS",
        "mismatch_fields": [],
        "replay_projection_hash": _hash({"source": "preemptive-semantic-replay", "suffix": suffix}),
    }
    bound_material = {
        "final_decision_time": "2026-07-17T12:00:00Z",
        "identity": {
            field: row.get(field)
            for field in (
                "intent_id",
                "signal_id",
                "prediction_id",
                "risk_decision_id",
                "orchestrator_decision_id",
                "allocation_id",
                "preemptive_decision_id",
                "symbol",
                "timeframe",
                "side",
            )
        },
        "component_times": {
            field: row.get(field)
            for field in cycle_reservation_module._PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
        },
        "tier_contract": {
            field: row.get(field) for field in cycle_reservation_module._FINAL_TIER_CONTRACT_FIELDS
        },
        "allocator_contract": {
            "allocation_hash": allocation_hash,
            "allocation_id": allocation["allocation_id"],
            "allocation_input_hash": allocation["allocation_input_hash"],
            "allocation_input_material": allocation["allocation_input_material"],
        },
        "canonical_decision_contract": {
            "risk_decision_id": row["risk_decision_id"],
            "risk_decision_record_hash": risk_record_hash,
            "risk_action": "allow",
            "orchestrator_decision_id": row["orchestrator_decision_id"],
            "orchestrator_decision_record_hash": orchestrator_record_hash,
            "orchestrator_action": "proceed_long",
            "final_reread": copy.deepcopy(decision_record_revalidation),
        },
        "preemptive_contract": copy.deepcopy(preemptive_receipt),
        "preemptive_semantic_revalidation": copy.deepcopy(preemptive_revalidation),
        "adaptive_allocation_hash": allocation_hash,
        "cycle_reservation_contract": cycle_contract,
        "revocable_control_commit_revalidation": copy.deepcopy(revocable_receipt),
        "sizing": {
            "quantity": quantity,
            "fill_price": price,
            "notional": notional,
            "effective_leverage": leverage,
            "allocated_margin_usd": margin,
            "margin_mode": "isolated_paper_simulated",
        },
        "safety_contract": {
            "intent": {
                field: row.get(field) for field in cycle_reservation_module._FINAL_ROW_SAFETY_FIELDS
            },
            "allocator": {
                field: allocation.get(field)
                for field in cycle_reservation_module._FINAL_ALLOCATION_SAFETY_FIELDS
            },
        },
    }
    persisted_projection = cycle_reservation_persisted_row_projection(row)
    bound_material["persisted_row_projection"] = persisted_projection
    bound_material["persisted_row_projection_hash"] = _hash(persisted_projection)
    bound_hash = _hash(bound_material)
    contract_material = {
        "schema_version": "paper_final_admission_contract_v3",
        "status": "PASS",
        "validation_started_at": "2026-07-17T11:59:59Z",
        "final_decision_time": "2026-07-17T12:00:00Z",
        "component_time_fields_checked": list(
            cycle_reservation_module._PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
        ),
        "observed_component_times": {},
        "canonical_decision_record_revalidation": copy.deepcopy(decision_record_revalidation),
        "preemptive_semantic_revalidation": copy.deepcopy(preemptive_revalidation),
        "bound_material_hash": bound_hash,
        "bound_material": bound_material,
        "revocable_control_commit_revalidation": copy.deepcopy(revocable_receipt),
        "rejection_reasons": [],
    }
    receipt_hash = _hash(contract_material)
    contract = {**contract_material, "receipt_hash": receipt_hash}
    row["paper_final_admission_contract"] = contract
    row["paper_final_admission_status"] = "PASS"
    row["paper_final_admission_decision_time"] = "2026-07-17T12:00:00Z"
    row["paper_final_admission_bound_material_hash"] = bound_hash
    row["paper_final_admission_receipt_hash"] = receipt_hash
    return row


def _rehash_receipt(receipt: dict[str, Any]) -> None:
    material = dict(receipt)
    material.pop("receipt_hash", None)
    receipt["receipt_hash"] = _hash(material)


def _rehash_allocator_arithmetic_receipt(allocation: dict[str, Any]) -> None:
    receipt = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(receipt, dict)
    material = dict(receipt)
    material.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = _hash(material)


def _reseal_allocation_input_identity(allocation: dict[str, Any]) -> None:
    input_hash = _hash(allocation["allocation_input_material"])
    allocation["allocation_input_hash"] = input_hash
    allocation["allocation_id"] = f"alloc_{input_hash[:24]}"
    allocation["model_inputs"]["allocation_input_hash"] = input_hash


def _reseal_final_contract(row: dict[str, Any]) -> None:
    contract = row["paper_final_admission_contract"]
    bound_material = contract["bound_material"]
    projection = cycle_reservation_persisted_row_projection(row)
    bound_material["persisted_row_projection"] = projection
    bound_material["persisted_row_projection_hash"] = _hash(projection)
    bound_hash = _hash(bound_material)
    contract["bound_material_hash"] = bound_hash
    row["paper_final_admission_bound_material_hash"] = bound_hash
    _rehash_receipt(contract)
    row["paper_final_admission_receipt_hash"] = contract["receipt_hash"]


def _sync_cycle_contract_from_row(row: dict[str, Any]) -> None:
    snapshot = row["paper_cycle_reservation_snapshot"]
    row["paper_final_admission_contract"]["bound_material"]["cycle_reservation_contract"] = {
        "paper_cycle_reservation_snapshot": copy.deepcopy(snapshot),
        "paper_cycle_reservation_snapshot_hash": row["paper_cycle_reservation_snapshot_hash"],
        "paper_cycle_reservation_commit_receipt": copy.deepcopy(
            row["paper_cycle_reservation_commit_receipt"]
        ),
        "paper_cycle_reservation_commit_receipt_hash": row[
            "paper_cycle_reservation_commit_receipt_hash"
        ],
        "paper_cycle_reservation_commit_status": row["paper_cycle_reservation_commit_status"],
        "cycle_identity": snapshot["cycle_identity"],
    }
    _reseal_final_contract(row)


def _sync_revocable_contract_from_row(row: dict[str, Any]) -> None:
    receipt = row["paper_revocable_control_commit_revalidation"]
    contract = row["paper_final_admission_contract"]
    contract["revocable_control_commit_revalidation"] = copy.deepcopy(receipt)
    contract["bound_material"]["revocable_control_commit_revalidation"] = copy.deepcopy(receipt)
    _reseal_final_contract(row)


def _reseal_revocable_after_mutation(row: dict[str, Any]) -> None:
    receipt = row["paper_revocable_control_commit_revalidation"]
    _rehash_receipt(receipt)
    row["paper_revocable_control_commit_revalidation_receipt_hash"] = receipt["receipt_hash"]
    _sync_revocable_contract_from_row(row)


def _snapshot(
    *,
    cycle_identity: str = "paper-cycle-20260717-120000",
    symbol: str = "BTCUSDT",
    prior_rows: Sequence[Mapping[str, Any]] | None = None,
    equity: float = 1_000.0,
    available_margin: float = 500.0,
    realized_drawdown: float = 0.02,
    precycle_total: float = 100.0,
    precycle_symbol: float = 20.0,
    precycle_open_max_loss: float = 0.0,
    max_total: float = 0.60,
    max_symbol: float = 0.30,
    margin_buffer: float = 0.10,
    max_drawdown: float = 0.20,
    max_loss: float = 0.05,
    emergency_cap: float | None = None,
) -> dict[str, Any]:
    return build_cycle_reservation_snapshot(
        cycle_identity=cycle_identity,
        candidate_symbol=symbol,
        base_resource_evidence_hash=_hash({"source": "portfolio"}),
        precycle_exposure_snapshot_hash=_hash({"source": "current-marks"}),
        dynamic_envelope_evidence_hash=_hash({"source": "dynamic-envelope"}),
        base_equity_usd=equity,
        base_available_margin_usd=available_margin,
        realized_drawdown_fraction_of_equity=realized_drawdown,
        precycle_total_notional_usd=precycle_total,
        precycle_symbol_current_mark_notional_usd=precycle_symbol,
        precycle_open_projected_max_loss_usd=precycle_open_max_loss,
        max_total_portfolio_risk_pct=max_total,
        max_single_symbol_exposure_pct=max_symbol,
        min_available_margin_buffer_pct=margin_buffer,
        max_daily_drawdown_pct=max_drawdown,
        max_loss_per_trade_pct=max_loss,
        emergency_absolute_cap_usdt=emergency_cap,
        prior_accepted_rows=prior_rows if prior_rows is not None else [],
    )


def _candidate_for_snapshot(
    snapshot: dict[str, Any],
    *,
    notional: float,
    margin: float,
    max_loss: float,
    leverage: float | None = None,
    suffix: str = "candidate",
) -> dict[str, Any]:
    return _allocation(
        snapshot["candidate_symbol"],
        notional=notional,
        margin=margin,
        max_loss=max_loss,
        leverage=leverage,
        snapshot_hash=snapshot["snapshot_hash"],
        suffix=suffix,
    )


def _authentic_growth_allocator_payload(
    snapshot: Mapping[str, Any],
    *,
    price: float,
    step_size: float,
    suffix: str,
) -> dict[str, Any]:
    lineage = {
        "intent_id": f"intent-{suffix}",
        "signal_id": f"signal-{suffix}",
        "prediction_id": f"prediction-{suffix}",
        "risk_decision_id": f"risk-{suffix}",
        "orchestrator_decision_id": f"orchestrator-{suffix}",
        CYCLE_RESERVATION_LINEAGE_KEY: snapshot["snapshot_hash"],
    }
    atr_evidence, atr_reasons = build_paper_liquidation_atr_evidence(
        feature_snapshot={
            "feature_snapshot_id": f"feature-{suffix}",
            "symbol": snapshot["candidate_symbol"],
            "timeframe": "1m",
            "feature_freshness_state": "CURRENT",
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "candle_close_time": "2026-07-19T11:59:00Z",
            "feature_cutoff": "2026-07-19T11:59:30Z",
            "available_at": "2026-07-19T11:59:40Z",
            "generated_at": "2026-07-19T11:59:45Z",
            "features": {"atr_bps": 15.0},
        },
        symbol=str(snapshot["candidate_symbol"]),
        timeframe="1m",
        entry_price=price,
        allocation_decision_time="2026-07-19T12:00:01Z",
    )
    assert not atr_reasons
    assert atr_evidence is not None
    lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = atr_evidence
    lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY] = atr_evidence["evidence_sha256"]
    result = allocate_authorized_growth(
        AllocationInput(
            symbol=str(snapshot["candidate_symbol"]),
            timeframe="1m",
            action="long",
            price=price,
            equity=10_000.0,
            available_margin=10_000.0,
            wallet_balance=10_000.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            market_state_integrity_score=95.0,
            volatility_bps=15.0,
            liquidity_score=1.0,
            spread_bps=2.0,
            slippage_bps=2.0,
            maintenance_margin_rate=0.005,
            stop_distance_bps=80.0,
            entry_atr_bps=15.0,
            regime_score=1.0,
            permitted_leverage_values=(1.0, 2.0, 3.0, 4.0, 5.0),
            step_size=step_size,
            min_qty=None,
            min_notional=0.0,
            lineage_ids=lineage,
        ),
    )
    payload: dict[str, Any] = result.to_payload()
    payload.update(
        {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_order": False,
            "test_order": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
        }
    )
    return payload


def _commit(
    snapshot: dict[str, Any],
    allocation: dict[str, Any],
    *,
    prior_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_candidate_commit_receipt(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=prior_rows if prior_rows is not None else [],
    )


def test_different_symbol_prior_consumes_total_margin_and_stress_not_symbol() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=200.0,
        margin=100.0,
        max_loss=20.0,
        suffix="eth",
    )

    snapshot = _snapshot(prior_rows=[prior])

    derived = snapshot["derived"]
    assert derived["prior_reserved_total_notional_usd"] == 200.0
    assert derived["prior_reserved_same_symbol_notional_usd"] == 0.0
    assert derived["prior_reserved_other_symbol_notional_usd"] == 200.0
    assert derived["effective_total_notional_before_candidate_usd"] == 300.0
    assert derived["effective_symbol_notional_before_candidate_usd"] == 20.0
    assert derived["remaining_margin_after_buffer_usd"] == 350.0
    assert derived["realized_drawdown_usd"] == 20.0
    assert derived["projected_stress_drawdown_before_candidate_usd"] == 40.0
    assert derived["remaining_per_candidate_risk_budget_fraction_of_equity"] == 0.05
    assert derived["remaining_candidate_risk_fraction_of_per_trade_limit"] == 1.0
    assert derived["allocator_available_margin_input_usd"] == pytest.approx(350.0 / 0.90)
    assert derived["allocator_available_margin_input_usd"] * (1.0 - 0.10) == pytest.approx(
        derived["remaining_margin_after_buffer_usd"]
    )
    assert cycle_reservation_snapshot_rejection_reasons(snapshot) == ()


def test_sequential_candidates_cannot_jointly_exceed_contracted_total_cap() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=200.0,
        margin=50.0,
        max_loss=5.0,
        suffix="eth-total",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_total=0.30,
        max_symbol=0.50,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=150.0,
        margin=50.0,
        max_loss=5.0,
    )

    receipt = _commit(snapshot, allocation, prior_rows=[prior])

    assert receipt["status"] == "BLOCKED"
    assert "CYCLE_RESERVATION_TOTAL_NOTIONAL_LIMIT_EXCEEDED" in receipt["rejection_reasons"]
    assert receipt["invariant_checks"]["adaptive_symbol_notional_limit_holds"] is True


def test_prior_margin_is_subtracted_before_candidate_buffer_check() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=100.0,
        max_loss=5.0,
        suffix="eth-margin",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        available_margin=200.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        margin_buffer=0.25,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=60.0,
        margin=60.0,
        max_loss=5.0,
    )

    receipt = _commit(snapshot, allocation, prior_rows=[prior])

    assert snapshot["derived"]["margin_buffer_usd"] == 50.0
    assert snapshot["derived"]["remaining_margin_after_buffer_usd"] == 50.0
    assert snapshot["derived"]["allocator_available_margin_input_usd"] == pytest.approx(50.0 / 0.75)
    assert receipt["status"] == "BLOCKED"
    assert "CYCLE_RESERVATION_MARGIN_BUFFER_LIMIT_EXCEEDED" in receipt["rejection_reasons"]


def test_realized_and_projected_stress_drawdown_are_separate_and_jointly_bind() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=50.0,
        margin=10.0,
        max_loss=10.0,
        suffix="eth-stress",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        realized_drawdown=0.08,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_drawdown=0.10,
        max_loss=0.05,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=50.0,
        margin=10.0,
        max_loss=15.0,
    )

    receipt = _commit(snapshot, allocation, prior_rows=[prior])

    assert snapshot["derived"]["realized_drawdown_usd"] == 80.0
    assert snapshot["derived"]["prior_reserved_max_loss_usd"] == 10.0
    assert snapshot["derived"]["projected_stress_drawdown_before_candidate_usd"] == 90.0
    assert snapshot["derived"]["remaining_per_candidate_risk_budget_usd"] == 10.0
    assert snapshot["derived"][
        "remaining_candidate_risk_fraction_of_per_trade_limit"
    ] == pytest.approx(0.20)
    assert receipt["status"] == "BLOCKED"
    assert "CYCLE_RESERVATION_CANDIDATE_RISK_BUDGET_EXCEEDED" in receipt["rejection_reasons"]
    assert (
        "CYCLE_RESERVATION_PROJECTED_STRESS_DRAWDOWN_LIMIT_EXCEEDED" in receipt["rejection_reasons"]
    )


def test_precycle_open_projected_loss_consumes_stress_capacity_once() -> None:
    snapshot = _snapshot(
        realized_drawdown=0.02,
        precycle_open_max_loss=60.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_drawdown=0.10,
        max_loss=0.05,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=50.0,
        margin=10.0,
        max_loss=25.0,
    )

    receipt = _commit(snapshot, allocation)

    assert snapshot["derived"]["realized_drawdown_usd"] == 20.0
    assert snapshot["inputs"]["precycle_open_projected_max_loss_usd"] == 60.0
    assert snapshot["derived"]["projected_stress_drawdown_before_candidate_usd"] == 80.0
    assert snapshot["derived"]["remaining_per_candidate_risk_budget_usd"] == 20.0
    assert receipt["status"] == "BLOCKED"
    assert "CYCLE_RESERVATION_CANDIDATE_RISK_BUDGET_EXCEEDED" in receipt["rejection_reasons"]


def test_emergency_absolute_cap_contracts_symbol_limit() -> None:
    snapshot = _snapshot(
        precycle_total=40.0,
        precycle_symbol=40.0,
        max_symbol=0.50,
        emergency_cap=100.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=70.0,
        margin=20.0,
        max_loss=5.0,
    )

    receipt = _commit(snapshot, allocation)

    assert snapshot["derived"]["percentage_symbol_notional_limit_usd"] == 500.0
    assert snapshot["derived"]["symbol_notional_limit_usd"] == 100.0
    assert receipt["status"] == "BLOCKED"
    assert "CYCLE_RESERVATION_SYMBOL_NOTIONAL_LIMIT_EXCEEDED" in receipt["rejection_reasons"]


def test_same_symbol_current_mark_exposure_is_not_double_counted_in_total() -> None:
    btc = _final_admitted_row(
        "BTCUSDT",
        notional=30.0,
        margin=10.0,
        max_loss=2.0,
        suffix="btc-same",
    )
    eth = _final_admitted_row(
        "ETHUSDT",
        notional=20.0,
        margin=5.0,
        max_loss=1.0,
        suffix="eth-other",
        prior_rows=[btc],
    )

    snapshot = _snapshot(prior_rows=[btc, eth], precycle_total=100.0, precycle_symbol=40.0)

    derived = snapshot["derived"]
    assert derived["effective_total_notional_before_candidate_usd"] == 150.0
    assert derived["effective_symbol_notional_before_candidate_usd"] == 70.0
    assert derived["prior_reserved_same_symbol_notional_usd"] == 30.0
    assert derived["prior_reserved_other_symbol_notional_usd"] == 20.0
    assert snapshot["accounting_semantics"]["precycle_total_includes_precycle_symbol"] is True
    assert snapshot["accounting_semantics"]["precycle_total_valuation_basis"] == (
        "CURRENT_MARK_GROSS_NOTIONAL"
    )


def test_valid_candidate_receipt_binds_allocation_snapshot_and_replays() -> None:
    snapshot = _snapshot(precycle_total=50.0, precycle_symbol=10.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=20.0,
    )

    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "PASS"
    assert receipt["cycle_reservation_snapshot_hash"] == snapshot["snapshot_hash"]
    assert receipt["adaptive_allocation_hash"] == _hash(allocation)
    assert (
        candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
            receipt=receipt,
        )
        == ()
    )
    assert (
        validate_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
            receipt=receipt,
        )
        is True
    )


def test_caller_supplied_ratio_above_one_is_not_replaced_by_static_service_cap() -> None:
    snapshot = _snapshot(
        equity=1_000.0,
        available_margin=1_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_total=1.50,
        max_symbol=1.25,
        margin_buffer=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=1_100.0,
        margin=550.0,
        max_loss=20.0,
    )

    receipt = _commit(snapshot, allocation)

    assert snapshot["derived"]["total_notional_limit_usd"] == 1_500.0
    assert snapshot["derived"]["symbol_notional_limit_usd"] == 1_250.0
    assert receipt["status"] == "PASS"


def test_high_precision_inputs_retain_canonical_decimal_authority_for_replay() -> None:
    snapshot = build_cycle_reservation_snapshot(
        cycle_identity="high-precision-cycle",
        candidate_symbol="BTCUSDT",
        base_resource_evidence_hash=_hash({"source": "portfolio"}),
        precycle_exposure_snapshot_hash=_hash({"source": "current-marks"}),
        dynamic_envelope_evidence_hash=_hash({"source": "dynamic-envelope"}),
        base_equity_usd="1000.123456789123456789",
        base_available_margin_usd="500.123456789123456789",
        realized_drawdown_fraction_of_equity="0.0123456789123456789",
        precycle_total_notional_usd="100.123456789123456789",
        precycle_symbol_current_mark_notional_usd="20.123456789123456789",
        precycle_open_projected_max_loss_usd="10.123456789123456789",
        max_total_portfolio_risk_pct="0.6123456789123456789",
        max_single_symbol_exposure_pct="0.3123456789123456789",
        min_available_margin_buffer_pct="0.1123456789123456789",
        max_daily_drawdown_pct="0.2123456789123456789",
        max_loss_per_trade_pct="0.05123456789123456789",
        emergency_absolute_cap_usdt=None,
        prior_accepted_rows=[],
    )

    assert cycle_reservation_snapshot_rejection_reasons(snapshot) == ()
    assert snapshot["inputs"]["numeric_aliases_are_non_authoritative"] is True
    assert Decimal(snapshot["inputs"]["exact_decimal_material"]["base_equity_usd"]) == Decimal(
        "1000.123456789123456789"
    )
    assert Decimal(
        snapshot["inputs"]["dynamic_envelope_limits"]["exact_decimal_material"][
            "max_loss_per_trade_pct"
        ]
    ) == Decimal("0.05123456789123456789")


def test_zero_per_trade_limit_and_full_margin_buffer_produce_zero_allocator_inputs() -> None:
    snapshot = _snapshot(
        margin_buffer=1.0,
        max_loss=0.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
    )

    assert snapshot["derived"]["remaining_margin_after_buffer_usd"] == 0.0
    assert snapshot["derived"]["allocator_available_margin_input_usd"] == 0.0
    assert snapshot["derived"]["per_candidate_max_loss_limit_usd"] == 0.0
    assert snapshot["derived"]["remaining_per_candidate_risk_budget_usd"] == 0.0
    assert snapshot["derived"]["remaining_candidate_risk_fraction_of_per_trade_limit"] == 0.0
    assert cycle_reservation_snapshot_rejection_reasons(snapshot) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_equity_usd", float("nan")),
        ("base_available_margin_usd", float("inf")),
        ("realized_drawdown_fraction_of_equity", -0.01),
    ],
)
def test_nonfinite_or_invalid_base_evidence_fails_closed(field: str, value: float) -> None:
    kwargs: dict[str, Any] = {
        "cycle_identity": "cycle-invalid",
        "candidate_symbol": "BTCUSDT",
        "base_resource_evidence_hash": _hash({"source": "portfolio"}),
        "precycle_exposure_snapshot_hash": _hash({"source": "current-marks"}),
        "dynamic_envelope_evidence_hash": _hash({"source": "dynamic-envelope"}),
        "base_equity_usd": 1_000.0,
        "base_available_margin_usd": 500.0,
        "realized_drawdown_fraction_of_equity": 0.0,
        "precycle_total_notional_usd": 0.0,
        "precycle_symbol_current_mark_notional_usd": 0.0,
        "precycle_open_projected_max_loss_usd": 0.0,
        "max_total_portfolio_risk_pct": 0.5,
        "max_single_symbol_exposure_pct": 0.2,
        "min_available_margin_buffer_pct": 0.1,
        "max_daily_drawdown_pct": 0.1,
        "max_loss_per_trade_pct": 0.01,
        "emergency_absolute_cap_usdt": None,
        "prior_accepted_rows": [],
    }
    kwargs[field] = value

    with pytest.raises(CycleReservationError):
        build_cycle_reservation_snapshot(**kwargs)


def test_tampered_prior_final_receipt_or_allocation_fails_closed() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="tampered-prior",
    )
    prior["adaptive_allocation"]["max_loss_usd"] = 4.0

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert any("MAX_LOSS_ALIAS_MISMATCH" in reason for reason in exc_info.value.reasons)


def test_legacy_v2_or_tampered_v3_prior_final_receipt_fails_closed() -> None:
    legacy = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="legacy-final",
    )
    legacy["paper_final_admission_contract"]["schema_version"] = "paper_final_admission_contract_v2"
    tampered = _final_admitted_row(
        "SOLUSDT",
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
        suffix="tampered-final-hash",
    )
    tampered["paper_final_admission_receipt_hash"] = "0" * 64

    for invalid_prior in (legacy, tampered):
        with pytest.raises(CycleReservationError) as exc_info:
            _snapshot(prior_rows=[invalid_prior])
        assert "CYCLE_RESERVATION_PRIOR_FINAL_RECEIPT_INVALID" in (exc_info.value.reasons)


def test_snapshot_semantic_mutation_is_rejected_even_when_rehashed() -> None:
    snapshot = _snapshot()
    snapshot["derived"]["remaining_total_notional_usd"] += 100.0
    material = dict(snapshot)
    material.pop("snapshot_hash")
    snapshot["snapshot_hash"] = _hash(material)

    reasons = cycle_reservation_snapshot_rejection_reasons(snapshot)

    assert "CYCLE_RESERVATION_SNAPSHOT_SEMANTIC_REPLAY_MISMATCH" in reasons


def test_missing_or_tampered_allocation_snapshot_lineage_fails_closed() -> None:
    snapshot = _snapshot()
    allocation = _allocation(
        "BTCUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        snapshot_hash=None,
    )

    with pytest.raises(CycleReservationError) as exc_info:
        build_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
        )

    assert "CYCLE_RESERVATION_ALLOCATION_SNAPSHOT_LINEAGE_MISMATCH" in (exc_info.value.reasons)


def test_nonfinite_candidate_resource_fails_closed() -> None:
    snapshot = _snapshot()
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=float("nan"),
    )

    with pytest.raises(CycleReservationError) as exc_info:
        build_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
        )

    assert any("NUMERIC_INVALID" in reason for reason in exc_info.value.reasons)


def test_receipt_tamper_is_detected_and_no_longer_validates() -> None:
    snapshot = _snapshot()
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    receipt = _commit(snapshot, allocation)
    receipt["candidate_resources"]["allocated_margin_usd"] = 1.0

    reasons = candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=[],
        receipt=receipt,
    )

    assert "CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID" in reasons
    assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in reasons
    assert (
        validate_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
            receipt=receipt,
        )
        is False
    )


@pytest.mark.parametrize(
    ("field", "replacement", "expected_reason"),
    [
        (
            "allocator_arithmetic_formula",
            "round(Decimal(gross_notional_usd) / Decimal(effective_leverage), 8)",
            "CYCLE_RESERVATION_COMMIT_ALLOCATOR_ARITHMETIC_FORMULA_INVALID",
        ),
        (
            "allocator_arithmetic_version",
            "adaptive_capital_allocator_margin_replay_v2",
            "CYCLE_RESERVATION_COMMIT_ALLOCATOR_ARITHMETIC_VERSION_INVALID",
        ),
        (
            "allocator_arithmetic_receipt_schema_version",
            "paper_allocator_arithmetic_receipt_v2",
            "CYCLE_RESERVATION_COMMIT_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION_INVALID",
        ),
    ],
)
def test_resealed_commit_rejects_mutated_allocator_arithmetic_contract(
    field: str,
    replacement: str,
    expected_reason: str,
) -> None:
    snapshot = _snapshot()
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    receipt = _commit(snapshot, allocation)
    receipt["candidate_resources"][field] = replacement
    _rehash_receipt(receipt)

    intrinsic_reasons = intrinsic_candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        receipt=receipt,
    )
    prefix_bound_reasons = candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=[],
        receipt=receipt,
    )

    for reasons in (intrinsic_reasons, prefix_bound_reasons):
        assert expected_reason in reasons
        assert "CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID" not in reasons
        assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in reasons


def test_coherently_rehashed_commit_cannot_rebind_embedded_arithmetic_receipt() -> None:
    snapshot = _snapshot()
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
    )
    receipt = _commit(snapshot, allocation)
    resources = receipt["candidate_resources"]
    exact = resources["exact_decimal_material"]
    mutated_formula = "raw_notional=lossy_published_quantity*published_price"
    resources["allocator_arithmetic_formula"] = mutated_formula
    exact["allocator_arithmetic_formula"] = mutated_formula
    exact["allocator_arithmetic_identity"] = (
        f"{exact['allocator_arithmetic_receipt_schema_version']}:"
        f"{exact['allocator_arithmetic_version']}:{mutated_formula}"
    )
    embedded_material = {
        "schema_version": exact["allocator_arithmetic_receipt_schema_version"],
        "arithmetic_version": exact["allocator_arithmetic_version"],
        "formula": exact["allocator_arithmetic_formula"],
        "raw_post_step_quantity_binary64_hex": exact["raw_post_step_quantity_binary64_hex"],
        "input_price_binary64_hex": exact["input_price_binary64_hex"],
        "raw_post_step_notional_binary64_hex": exact["raw_post_step_notional_binary64_hex"],
        "selected_leverage_binary64_hex": exact["selected_leverage_binary64_hex"],
    }
    embedded_hash = _hash(embedded_material)
    exact["allocator_arithmetic_receipt_sha256"] = embedded_hash
    resources["allocator_arithmetic_receipt_sha256"] = embedded_hash
    _rehash_receipt(receipt)

    for reasons in (
        intrinsic_candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=receipt,
        ),
        candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            prior_accepted_rows=[],
            receipt=receipt,
        ),
    ):
        assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA_INVALID" in reasons
        assert "CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID" not in reasons
        assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in reasons


def test_blocked_commit_does_not_mutate_snapshot_or_allocation() -> None:
    snapshot = _snapshot(max_total=0.10, precycle_total=90.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=20.0,
        margin=10.0,
        max_loss=5.0,
    )
    snapshot_before = copy.deepcopy(snapshot)
    allocation_before = copy.deepcopy(allocation)

    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "BLOCKED"
    assert snapshot == snapshot_before
    assert allocation == allocation_before


def test_duplicate_prior_row_cannot_be_counted_twice() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="duplicate",
    )

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior, prior])

    assert "CYCLE_RESERVATION_DUPLICATE_PRIOR_FINAL_RECEIPT" in exc_info.value.reasons


def test_commit_rejects_accepted_prefix_changed_after_snapshot() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="prefix",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        precycle_total=0.0,
        precycle_symbol=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
    )

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation, prior_rows=[])

    assert "CYCLE_RESERVATION_ACCEPTED_PREFIX_CHANGED_AFTER_SNAPSHOT" in exc_info.value.reasons


def test_intrinsic_commit_replay_is_independent_of_mutable_accepted_prefix() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="intrinsic-prefix",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        precycle_total=0.0,
        precycle_symbol=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
    )
    receipt = _commit(snapshot, allocation, prior_rows=[prior])

    assert (
        intrinsic_candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=receipt,
        )
        == ()
    )
    assert (
        validate_intrinsic_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=receipt,
        )
        is True
    )
    assert candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=[],
        receipt=receipt,
    ) == ("CYCLE_RESERVATION_ACCEPTED_PREFIX_CHANGED_AFTER_SNAPSHOT",)


def test_intrinsic_commit_detects_unsealed_and_coherently_rehashed_mutations() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    receipt = _commit(snapshot, allocation)

    unsealed = copy.deepcopy(receipt)
    unsealed["candidate_resources"]["allocated_margin_usd"] = 49.0
    unsealed_reasons = intrinsic_candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        receipt=unsealed,
    )
    assert "CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID" in unsealed_reasons
    assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in unsealed_reasons

    resealed = copy.deepcopy(receipt)
    resealed["candidate_resources"]["allocated_margin_usd"] = 49.0
    _rehash_receipt(resealed)
    resealed_reasons = intrinsic_candidate_commit_receipt_rejection_reasons(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        receipt=resealed,
    )
    assert "CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID" not in resealed_reasons
    assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in resealed_reasons
    assert (
        validate_intrinsic_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=resealed,
        )
        is False
    )


def test_intrinsic_blocked_commit_is_replayable_but_not_valid_for_admission() -> None:
    snapshot = _snapshot(max_total=0.10, precycle_total=90.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=20.0,
        margin=10.0,
        max_loss=5.0,
    )
    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "BLOCKED"
    assert (
        intrinsic_candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=receipt,
        )
        == ()
    )
    assert (
        validate_intrinsic_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=allocation,
            receipt=receipt,
        )
        is False
    )


def test_allocation_aliases_use_exact_decimal_equality() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    allocation["target_notional_usdt"] = "100.0000000000000000001"

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert (
        "CYCLE_RESERVATION_ALLOCATION_NOTIONAL_ALIAS_MISMATCH:target_notional_usdt"
        in exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("boundary", "exact_value", "numeric_field"),
    [
        (
            "notional",
            "100.0000000000000000001",
            "gross_notional_usd",
        ),
        (
            "margin",
            "50.0000000000000000001",
            "allocated_margin_usd",
        ),
        (
            "max_loss",
            "10.0000000000000000001",
            "max_loss_if_stop_hit",
        ),
    ],
)
def test_candidate_resource_boundaries_reject_non_allocator_numeric_types(
    boundary: str,
    exact_value: str,
    numeric_field: str,
) -> None:
    snapshot = _snapshot(
        equity=1_000.0,
        available_margin=50.0 if boundary == "margin" else 1_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_total=0.10 if boundary == "notional" else 1.0,
        max_symbol=1.0,
        margin_buffer=0.0,
        max_drawdown=1.0,
        max_loss=0.01 if boundary == "max_loss" else 1.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0 if boundary == "notional" else 20.0,
        margin=50.0 if boundary == "margin" else 10.0,
        max_loss=10.0 if boundary == "max_loss" else 1.0,
    )
    if boundary == "notional":
        for field in (
            "gross_notional_usd",
            "target_notional_usd",
            "target_notional_usdt",
        ):
            allocation[field] = exact_value
    elif boundary == "margin":
        allocation["allocated_margin_usd"] = exact_value
    else:
        allocation["max_loss_if_stop_hit"] = exact_value
        allocation["max_loss_usd"] = exact_value

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert (
        "CYCLE_RESERVATION_ALLOCATION_OUTPUT_NUMERIC_TYPE_INVALID:"
        f"adaptive_allocation.{numeric_field}"
    ) in exc_info.value.reasons


@pytest.mark.parametrize("boundary", ["notional", "margin", "max_loss"])
def test_candidate_resource_underflow_string_fails_closed_at_allocator_abi(
    boundary: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    if boundary == "notional":
        for field in (
            "gross_notional_usd",
            "target_notional_usd",
            "target_notional_usdt",
        ):
            allocation[field] = "1E-400"
        numeric_field = "gross_notional_usd"
    elif boundary == "margin":
        allocation["allocated_margin_usd"] = "1E-400"
        numeric_field = "allocated_margin_usd"
    else:
        allocation["max_loss_if_stop_hit"] = "1E-400"
        allocation["max_loss_usd"] = "1E-400"
        numeric_field = "max_loss_if_stop_hit"

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert (
        "CYCLE_RESERVATION_ALLOCATION_OUTPUT_NUMERIC_TYPE_INVALID:"
        f"adaptive_allocation.{numeric_field}"
    ) in exc_info.value.reasons


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    [
        (
            "paper_cycle_reservation_snapshot",
            "CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_MISSING",
        ),
        (
            "paper_cycle_reservation_snapshot_hash",
            "CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_HASH_MISMATCH",
        ),
        (
            "paper_cycle_reservation_commit_receipt",
            "CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_MISSING",
        ),
        (
            "paper_cycle_reservation_commit_receipt_hash",
            "CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_HASH_MISMATCH",
        ),
        (
            "paper_cycle_reservation_commit_status",
            "CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_STATUS_INVALID",
        ),
        (
            "paper_revocable_control_commit_revalidation",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RECEIPT_MISSING",
        ),
        (
            "paper_revocable_control_commit_revalidation_receipt_hash",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RECEIPT_HASH_MISMATCH",
        ),
        (
            "paper_revocable_control_commit_revalidation_status",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_STATUS_MISMATCH",
        ),
    ],
)
def test_missing_top_level_prior_proof_alias_fails_closed(
    field: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"missing-{field}",
    )
    prior.pop(field)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize("mutation", ["missing", "extra", "identity"])
def test_bound_cycle_contract_requires_exact_six_key_projection(
    mutation: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"cycle-bound-{mutation}",
    )
    bound = prior["paper_final_admission_contract"]["bound_material"]
    if mutation == "missing":
        bound.pop("cycle_reservation_contract")
    elif mutation == "extra":
        bound["cycle_reservation_contract"]["unexpected"] = True
    else:
        bound["cycle_reservation_contract"]["cycle_identity"] = "other-cycle"
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_CYCLE_BOUND_MATERIAL_MISMATCH" in exc_info.value.reasons


def test_prior_cycle_commit_requires_exact_intrinsic_semantic_replay() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="commit-semantic-replay",
    )
    commit = prior["paper_cycle_reservation_commit_receipt"]
    commit["candidate_resources"]["gross_notional_usd"] = 99.0
    _rehash_receipt(commit)
    prior["paper_cycle_reservation_commit_receipt_hash"] = commit["receipt_hash"]
    _sync_cycle_contract_from_row(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_REPLAY_INVALID" in (exc_info.value.reasons)
    assert "CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH" in (exc_info.value.reasons)


def test_prior_rebind_cannot_hide_coherently_rehashed_allocator_arithmetic_lie() -> None:
    prior = _final_admitted_row(
        "BTCUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix="prior-arithmetic-rebind",
    )
    allocation = prior["adaptive_allocation"]
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    arithmetic["formula"] = "raw_notional=lossy_published_quantity*published_price"
    _rehash_allocator_arithmetic_receipt(allocation)
    allocation_hash = _hash(allocation)
    bound = prior["paper_final_admission_contract"]["bound_material"]
    bound["adaptive_allocation_hash"] = allocation_hash
    bound["allocator_contract"]["allocation_hash"] = allocation_hash
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA_INVALID" in (exc_info.value.reasons)


def test_coherently_rehashed_prior_projection_keeps_selected_leverage_bound() -> None:
    prior = _final_admitted_row(
        "BTCUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix="prior-selected-leverage-binding",
    )
    snapshot = _snapshot(prior_rows=[prior])
    exact = snapshot["prior_reservations"][0]["resource_exact_decimal_material"]
    exact["permitted_leverage_values_binary64_hex"] = [(3.0).hex()]
    snapshot_material = dict(snapshot)
    snapshot_material.pop("snapshot_hash")
    snapshot["snapshot_hash"] = _hash(snapshot_material)

    reasons = cycle_reservation_snapshot_rejection_reasons(snapshot)

    assert "CYCLE_RESERVATION_PRIOR_ALLOCATOR_SELECTED_LEVERAGE_NOT_PERMITTED" in reasons


def test_prior_cycle_snapshot_requires_semantic_replay_after_coherent_rehash() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="snapshot-semantic-replay",
    )
    snapshot = prior["paper_cycle_reservation_snapshot"]
    snapshot["derived"]["remaining_total_notional_usd"] += 1.0
    material = dict(snapshot)
    material.pop("snapshot_hash")
    snapshot["snapshot_hash"] = _hash(material)
    prior["paper_cycle_reservation_snapshot_hash"] = snapshot["snapshot_hash"]
    _sync_cycle_contract_from_row(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_INVALID" in (exc_info.value.reasons)
    assert "CYCLE_RESERVATION_SNAPSHOT_SEMANTIC_REPLAY_MISMATCH" in (exc_info.value.reasons)


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        (
            "schema_version",
            "paper_revocable_control_commit_revalidation_v2",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_SCHEMA_INVALID",
        ),
        (
            "paper_only",
            False,
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_SAFETY_FLAGS_INVALID",
        ),
        (
            "cross_process_atomic",
            True,
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_SAFETY_FLAGS_INVALID",
        ),
        (
            "residual_toctou_risk",
            "",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RESIDUAL_RISK_MISSING",
        ),
        (
            "guardian",
            None,
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_FIELD_MISSING:guardian",
        ),
        (
            "rejection_reasons",
            ["MUTATED"],
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_STATUS_INVALID",
        ),
    ],
)
def test_coherently_rehashed_revocable_safety_mutation_fails_closed(
    field: str,
    value: Any,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"revocable-{field}",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    receipt[field] = value
    _rehash_receipt(receipt)
    prior["paper_revocable_control_commit_revalidation_receipt_hash"] = receipt["receipt_hash"]
    _sync_revocable_contract_from_row(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize(
    ("proof", "expected_reason"),
    [
        (
            "cycle",
            "CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_STATUS_INVALID",
        ),
        (
            "revocable",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_STATUS_MISMATCH",
        ),
    ],
)
def test_prior_reservation_requires_pass_commit_receipts(
    proof: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"blocked-{proof}",
    )
    if proof == "cycle":
        receipt = prior["paper_cycle_reservation_commit_receipt"]
        receipt["status"] = "BLOCKED"
        receipt["rejection_reasons"] = ["MUTATED_BLOCK"]
        _rehash_receipt(receipt)
        prior["paper_cycle_reservation_commit_receipt_hash"] = receipt["receipt_hash"]
        prior["paper_cycle_reservation_commit_status"] = "BLOCKED"
        _sync_cycle_contract_from_row(prior)
    else:
        receipt = prior["paper_revocable_control_commit_revalidation"]
        receipt["status"] = "BLOCKED"
        receipt["rejection_reasons"] = ["MUTATED_BLOCK"]
        _rehash_receipt(receipt)
        prior["paper_revocable_control_commit_revalidation_receipt_hash"] = receipt["receipt_hash"]
        prior["paper_revocable_control_commit_revalidation_status"] = "BLOCKED"
        _sync_revocable_contract_from_row(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize("location", ["contract", "bound"])
def test_revocable_receipt_must_match_final_contract_and_bound_material(
    location: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"revocable-copy-{location}",
    )
    contract = prior["paper_final_admission_contract"]
    if location == "contract":
        receipt = contract["revocable_control_commit_revalidation"]
    else:
        receipt = contract["bound_material"]["revocable_control_commit_revalidation"]
    receipt["checked_at"] = "2026-07-17T12:00:01Z"
    _rehash_receipt(receipt)
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_REVOCABLE_BOUND_MATERIAL_MISMATCH" in exc_info.value.reasons


def test_prior_final_sizing_uses_exact_decimal_equality() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="exact-final-sizing",
    )
    prior["paper_final_admission_contract"]["bound_material"]["sizing"]["notional"] = (
        "100.0000000000000000001"
    )
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_FINAL_NOTIONAL_MISMATCH" in (exc_info.value.reasons)


@pytest.mark.parametrize(
    ("location", "field", "value", "expected_reason"),
    [
        (
            "row",
            "quantity",
            "1.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:quantity",
        ),
        (
            "row",
            "notional",
            "100.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:notional",
        ),
        (
            "row",
            "effective_leverage",
            "2.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:effective_leverage",
        ),
        (
            "row",
            "allocated_margin_usd",
            "50.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:allocated_margin_usd",
        ),
        (
            "sizing",
            "quantity",
            "1.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_FINAL_SIZING_ALIAS_MISMATCH:quantity",
        ),
        (
            "sizing",
            "effective_leverage",
            "2.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_FINAL_SIZING_ALIAS_MISMATCH:effective_leverage",
        ),
        (
            "sizing",
            "allocated_margin_usd",
            "50.0000000000000000001",
            "CYCLE_RESERVATION_PRIOR_FINAL_SIZING_ALIAS_MISMATCH:allocated_margin_usd",
        ),
    ],
)
def test_prior_economic_alias_tiny_decimal_delta_cannot_hide_in_tolerance(
    location: str,
    field: str,
    value: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"exact-alias-{location}-{field}",
    )
    if location == "row":
        prior[field] = value
    else:
        prior["paper_final_admission_contract"]["bound_material"]["sizing"][field] = value
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            "guardian_blocked",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_BLOCKED",
        ),
        (
            "guardian_ttl_expired",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID",
        ),
        (
            "guardian_ttl_range_widened",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID",
        ),
        (
            "guardian_ttl_flag_false",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID",
        ),
        (
            "nonoverridable_freeze",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_NONOVERRIDABLE_FREEZE_ACTIVE",
        ),
        (
            "risk_changed",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RISK_EXACT_MATCH_INVALID",
        ),
        (
            "runtime_changed",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RUNTIME_EXACT_MATCH_INVALID",
        ),
        (
            "runtime_blocked",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_RUNTIME_EXACT_MATCH_INVALID",
        ),
    ],
)
def test_coherently_rehashed_revocable_semantic_lie_fails_closed(
    mutation: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"semantic-{mutation}",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    if mutation == "guardian_blocked":
        receipt["guardian"]["currently_allows_execution_tier"] = False
    elif mutation == "guardian_ttl_expired":
        receipt["guardian"]["ttl_remaining_seconds"] = 0
    elif mutation == "guardian_ttl_range_widened":
        receipt["guardian"]["ttl_required_range_seconds"] = [1, 3600]
    elif mutation == "guardian_ttl_flag_false":
        receipt["guardian"]["ttl_valid"] = False
    elif mutation == "nonoverridable_freeze":
        receipt["effective_entry_freeze"].update(
            {
                "paper_new_entries_halted": True,
                "nonoverridable": True,
                "tier_override_allowed": True,
            }
        )
    elif mutation == "risk_changed":
        receipt["current_risk_state"]["exact_match"] = False
    elif mutation == "runtime_changed":
        receipt["runtime_owner"]["exact_match"] = False
    else:
        receipt["runtime_owner"]["current_projection_allows"] = False
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            "naive_start",
            "CYCLE_RESERVATION_TIME_NOT_AWARE:validation_started_at",
        ),
        (
            "backwards",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_CLOCK_ORDER_INVALID",
        ),
        (
            "after_final_decision",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_CLOCK_ORDER_INVALID",
        ),
    ],
)
def test_coherently_rehashed_revocable_clock_lie_fails_closed(
    mutation: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"clock-{mutation}",
    )
    contract = prior["paper_final_admission_contract"]
    receipt = prior["paper_revocable_control_commit_revalidation"]
    if mutation == "naive_start":
        receipt["validation_started_at"] = "2026-07-17T11:59:59"
        contract["validation_started_at"] = "2026-07-17T11:59:59"
    elif mutation == "backwards":
        receipt["validation_started_at"] = "2026-07-17T12:00:01Z"
        contract["validation_started_at"] = "2026-07-17T12:00:01Z"
    else:
        receipt["checked_at"] = "2026-07-17T12:00:01Z"
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


def test_coherently_rehashed_top_level_intent_mutation_fails_closed() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="intent-alias",
    )
    prior["intent_id"] = "intent-mutated-after-seal"
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_FINAL_IDENTITY_MISMATCH" in (exc_info.value.reasons)
    assert "CYCLE_RESERVATION_PRIOR_INTENT_LINEAGE_MISMATCH" in (exc_info.value.reasons)


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        (
            "signal_id",
            "signal-coherently-resealed",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_LINEAGE_ID_MISMATCH:signal_id",
        ),
        (
            "prediction_id",
            "prediction-coherently-resealed",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_LINEAGE_ID_MISMATCH:prediction_id",
        ),
        (
            "risk_decision_id",
            "risk-coherently-resealed",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_LINEAGE_ID_MISMATCH:risk_decision_id",
        ),
        (
            "orchestrator_decision_id",
            "orchestrator-coherently-resealed",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_LINEAGE_ID_MISMATCH:orchestrator_decision_id",
        ),
        (
            "timeframe",
            "5m",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_CANDIDATE_IDENTITY_MISMATCH",
        ),
        (
            "side",
            "short",
            "CYCLE_RESERVATION_PRIOR_ALLOCATION_CANDIDATE_IDENTITY_MISMATCH",
        ),
        (
            "preemptive_decision_id",
            "preemptive-coherently-resealed",
            "CYCLE_RESERVATION_PRIOR_PREEMPTIVE_RECEIPT_IDENTITY_INVALID",
        ),
    ],
)
def test_final_identity_reseal_cannot_escape_independent_authority_cross_bindings(
    field: str,
    value: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"identity-cross-bind-{field}",
    )
    prior[field] = value
    prior["paper_final_admission_contract"]["bound_material"]["identity"][field] = value
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


def test_missing_authoritative_per_id_decision_record_fails_closed() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="missing-authoritative-risk-record",
    )
    prior.pop("risk_decision_record")
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_RISK_DECISION_RECORD_MISSING" in (exc_info.value.reasons)


def test_coherently_rehashed_decision_record_still_binds_candidate_identity() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="decision-record-cross-bind",
    )
    record = prior["risk_decision_record"]
    record["prediction_id"] = "prediction-different-candidate"
    record_hash = _decision_record_hash(record)
    prior["risk_decision_record_hash"] = record_hash
    canonical = prior["paper_final_admission_contract"]["bound_material"][
        "canonical_decision_contract"
    ]
    canonical["risk_decision_record_hash"] = record_hash
    canonical["final_reread"]["risk"]["record_hash"] = record_hash
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_RISK_DECISION_RECORD_IDENTITY_MISMATCH" in (
        exc_info.value.reasons
    )


def test_coherently_rehashed_preemptive_material_still_binds_candidate_identity() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="preemptive-cross-bind",
    )
    receipt = prior["preemptive_edge_control"]
    receipt["preemptive_input_material"]["candidate"]["prediction_id"] = (
        "prediction-different-candidate"
    )
    receipt["preemptive_input_hash"] = _hash(receipt["preemptive_input_material"])
    prior["preemptive_input_hash"] = receipt["preemptive_input_hash"]
    prior["paper_final_admission_contract"]["bound_material"]["preemptive_contract"] = (
        copy.deepcopy(receipt)
    )
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_PREEMPTIVE_CANDIDATE_IDENTITY_MISMATCH" in (
        exc_info.value.reasons
    )


def test_snapshot_explicitly_disclaims_plain_sha_source_authentication() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="integrity-scope",
    )

    snapshot = _snapshot(prior_rows=[prior])

    semantics = snapshot["accounting_semantics"]
    projection = snapshot["prior_reservations"][0]
    assert semantics["persisted_hashes_authenticate_source_provenance"] is False
    assert semantics["coherent_pre_snapshot_nested_reseal_detectable"] is False
    assert "CANNOT_BE_DETECTED_HERE" in semantics["coherent_pre_snapshot_nested_reseal_limitation"]
    assert projection["coherent_pre_snapshot_reseal_detectable"] is False
    assert projection["persisted_integrity_scope"] == (
        "SEMANTIC_REPLAY_AND_CROSS_BOUND_PLAIN_SHA256;NOT_SOURCE_AUTHENTICATION"
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("quantity", 0.5, "quantity"),
        ("target_quantity", 0.5, "target_quantity"),
        ("fill_price", 90.0, "fill_price"),
        ("entry_price", 90.0, "entry_price"),
        ("notional", 90.0, "notional"),
        ("target_notional_usd", 90.0, "target_notional_usd"),
        ("target_notional_usdt", 90.0, "target_notional_usdt"),
        ("gross_notional_usd", 90.0, "gross_notional_usd"),
        ("recommended_leverage", 1.5, "recommended_leverage"),
        ("effective_leverage", 1.5, "effective_leverage"),
        ("allocated_margin_usd", 40.0, "allocated_margin_usd"),
    ],
)
def test_coherently_rehashed_top_level_economic_alias_mutation_fails_closed(
    field: str,
    value: float,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"economic-{field}",
    )
    prior[field] = value
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert (
        f"CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:{expected_reason}"
        in exc_info.value.reasons
    )


@pytest.mark.parametrize(
    "field",
    ["margin_mode_simulated", "recommended_margin_mode"],
)
def test_coherently_rehashed_top_level_margin_mode_alias_mutation_fails_closed(
    field: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"margin-mode-{field}",
    )
    prior[field] = "cross"
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_ROW_MARGIN_MODE_ALIAS_MISMATCH" in (exc_info.value.reasons)


def test_canonical_projection_detects_unsealed_nested_row_mutation() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="nested-projection",
    )
    prior["paper_exchange_filter_snapshot"] = {"mutated": True}

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_PERSISTED_ROW_PROJECTION_INVALID" in (exc_info.value.reasons)


def test_coherently_rehashed_post_snapshot_nested_mutation_changes_prefix() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="post-snapshot-projection",
    )
    snapshot = _snapshot(
        prior_rows=[prior],
        precycle_total=0.0,
        precycle_symbol=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
    )
    prior["paper_exchange_filter_snapshot"] = {"coherently_mutated": True}
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation, prior_rows=[prior])

    assert "CYCLE_RESERVATION_ACCEPTED_PREFIX_CHANGED_AFTER_SNAPSHOT" in (exc_info.value.reasons)


def test_individually_valid_rows_without_sequential_prefix_fail_closed() -> None:
    first = _final_admitted_row(
        "BTCUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="append-chain-first",
    )
    second = _final_admitted_row(
        "ETHUSDT",
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
        suffix="append-chain-second",
    )

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[first, second])

    assert "CYCLE_RESERVATION_PRIOR_APPEND_CHAIN_PREFIX_MISMATCH:1" in (exc_info.value.reasons)


def test_sequential_prefix_with_backdated_append_time_fails_closed() -> None:
    first = _final_admitted_row(
        "BTCUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="append-time-first",
    )
    second = _final_admitted_row(
        "ETHUSDT",
        notional=50.0,
        margin=25.0,
        max_loss=2.0,
        suffix="append-time-second",
        prior_rows=[first],
    )
    contract = second["paper_final_admission_contract"]
    receipt = second["paper_revocable_control_commit_revalidation"]
    receipt["validation_started_at"] = "2026-07-17T10:59:59Z"
    receipt["checked_at"] = "2026-07-17T11:00:00Z"
    contract["validation_started_at"] = "2026-07-17T10:59:59Z"
    contract["final_decision_time"] = "2026-07-17T11:00:00Z"
    contract["bound_material"]["final_decision_time"] = "2026-07-17T11:00:00Z"
    second["paper_precycle_exposure_snapshot_started_at"] = "2026-07-17T10:59:55Z"
    second["paper_precycle_exposure_snapshot_completed_at"] = "2026-07-17T10:59:57Z"
    second["paper_allocation_decision_time"] = "2026-07-17T10:59:58Z"
    contract["bound_material"]["component_times"] = {
        field: second.get(field)
        for field in cycle_reservation_module._PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
    }
    for reread in contract["bound_material"]["canonical_decision_contract"][
        "final_reread"
    ].values():
        reread["observed_at"] = "2026-07-17T10:59:59.500000Z"
    contract["canonical_decision_record_revalidation"] = copy.deepcopy(
        contract["bound_material"]["canonical_decision_contract"]["final_reread"]
    )
    tuning_source = receipt["source_revalidation"]["adaptive_tuning_source"]
    for field, observed_at in (
        ("semantic_validation", "2026-07-17T10:59:59.250000Z"),
        ("commit_clock_semantic_validation", "2026-07-17T11:00:00Z"),
    ):
        semantic = tuning_source[field]
        semantic["available_at"] = "2026-07-17T10:59:50Z"
        semantic["observed_at"] = observed_at
        semantic["expires_at"] = "2026-07-17T11:05:00Z"
        _rehash_receipt(semantic)
    tuning_source["semantic_validation_receipt_hash"] = tuning_source["semantic_validation"][
        "receipt_hash"
    ]
    tuning_source["commit_clock_semantic_validation_receipt_hash"] = tuning_source[
        "commit_clock_semantic_validation"
    ]["receipt_hash"]
    second["paper_final_admission_decision_time"] = "2026-07-17T11:00:00Z"
    _reseal_revocable_after_mutation(second)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[first, second])

    assert "CYCLE_RESERVATION_PRIOR_APPEND_CHAIN_TIME_ORDER_INVALID:1" in (exc_info.value.reasons)


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    [
        ("sequence_index", "CYCLE_RESERVATION_PRIOR_SEQUENCE_INVALID"),
        ("prior_accepted_count", "CYCLE_RESERVATION_PRIOR_COUNT_MISMATCH"),
    ],
)
def test_boolean_cannot_impersonate_sequential_integer_after_rehash(
    field: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"boolean-sequence-{field}",
    )
    snapshot = _snapshot(prior_rows=[prior])
    if field == "sequence_index":
        snapshot["prior_reservations"][0]["sequence_index"] = False
    else:
        snapshot["prior_accepted_count"] = True
    material = dict(snapshot)
    material.pop("snapshot_hash")
    snapshot["snapshot_hash"] = _hash(material)

    reasons = cycle_reservation_snapshot_rejection_reasons(snapshot)

    assert expected_reason in reasons


def test_strict_json_hashes_preserve_valid_external_contracts() -> None:
    material = {
        "alpha": [None, True, False, 1, -2, 3.25, "text"],
        "nested": {"key": "value"},
    }

    assert cycle_reservation_module._canonical_sha256(material) == _hash(material)
    assert cycle_reservation_module._decision_record_sha256(material) == _decision_record_hash(
        material
    )


def test_real_allocator_tuple_material_preserves_allocation_digest_and_commits() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    fixture_allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    lineage = dict(fixture_allocation["lineage_ids"])
    real_input = AllocationInput(
        symbol=snapshot["candidate_symbol"],
        timeframe="1m",
        action="long",
        price=100.0,
        equity=1_000.0,
        available_margin=500.0,
        wallet_balance=1_000.0,
        confidence_calibrated=0.8,
        expected_move_after_cost_bps=80.0,
        market_state_integrity_score=1.0,
        maintenance_margin_rate=0.005,
        permitted_leverage_values=(1.0, 2.0, 3.0),
        lineage_ids=lineage,
    )
    material = allocation_input_material(real_input, RiskEnvelope(), mode="paper")
    permitted = material["allocation_input"]["permitted_leverage_values"]
    assert isinstance(permitted, tuple)
    allocator_digest = canonical_allocation_input_hash(material)
    assert cycle_reservation_module._canonical_sha256(material) == allocator_digest
    allocation = allocate_paper_candidate(real_input, RiskEnvelope()).to_payload()
    allocation.update(
        {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_order": False,
            "test_order": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
        }
    )
    assert allocation["allocator_decision"] in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert allocation["allocation_input_hash"] == allocator_digest
    assert allocation["allocation_input_material"] == material

    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "PASS"


@pytest.mark.parametrize(
    ("hostile", "equivalent_json", "expected_reason"),
    [
        (
            {1: "same-value"},
            {"1": "same-value"},
            "CYCLE_RESERVATION_JSON_OBJECT_KEY_INVALID",
        ),
        (
            {"value": Decimal("1.00")},
            {"value": "1.00"},
            "CYCLE_RESERVATION_CANONICAL_JSON_TYPE_INVALID",
        ),
    ],
)
def test_non_json_type_collisions_fail_before_allocation_hash_admission(
    hostile: dict[Any, Any],
    equivalent_json: dict[str, Any],
    expected_reason: str,
) -> None:
    # This proves the legacy default=str serializer was non-injective for the
    # hostile pair; the cycle boundary must reject it instead of trusting that
    # unchanged digest as immutable allocation identity.
    assert _hash(hostile) == _hash(equivalent_json)
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
    )
    material = allocation["allocation_input_material"]
    material["risk_envelope"] = hostile
    colliding_hash = _hash(material)
    allocation["allocation_input_hash"] = colliding_hash
    allocation["allocation_id"] = f"alloc_{colliding_hash[:24]}"

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize(
    "value",
    [
        "1E+1000000",
        Decimal("1E+1000000"),
        "1." + ("0" * (cycle_reservation_module.MAX_CYCLE_RESERVATION_DECIMAL_INPUT_BYTES + 1)),
    ],
)
def test_extreme_decimal_resources_raise_only_cycle_reservation_error(
    value: Any,
) -> None:
    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(equity=value)

    assert any("RESOURCE_LIMIT_EXCEEDED" in reason for reason in exc_info.value.reasons)


def test_json_depth_and_size_limits_raise_only_cycle_reservation_error() -> None:
    nested: dict[str, Any] = {"leaf": 1}
    for _ in range(cycle_reservation_module.MAX_CYCLE_RESERVATION_JSON_DEPTH + 1):
        nested = {"next": nested}

    with pytest.raises(CycleReservationError) as depth_error:
        cycle_reservation_module._canonical_sha256(nested)
    assert depth_error.value.reasons == ("CYCLE_RESERVATION_JSON_DEPTH_LIMIT_EXCEEDED",)

    oversized_text = "x" * (cycle_reservation_module.MAX_CYCLE_RESERVATION_TEXT_BYTES + 1)
    with pytest.raises(CycleReservationError) as size_error:
        _snapshot(cycle_identity=oversized_text)
    assert size_error.value.reasons == (
        "CYCLE_RESERVATION_TEXT_RESOURCE_LIMIT_EXCEEDED:cycle_identity",
    )


def test_json_node_and_canonical_byte_limits_fail_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_reservation_module, "MAX_CYCLE_RESERVATION_JSON_NODES", 4)
    with pytest.raises(CycleReservationError) as node_error:
        cycle_reservation_module._canonical_sha256([None, None, None, None])
    assert node_error.value.reasons == ("CYCLE_RESERVATION_JSON_NODE_LIMIT_EXCEEDED",)

    monkeypatch.setattr(
        cycle_reservation_module,
        "MAX_CYCLE_RESERVATION_CANONICAL_JSON_BYTES",
        32,
    )
    with pytest.raises(CycleReservationError) as byte_error:
        cycle_reservation_module._canonical_sha256({"payload": "x" * 32})
    assert byte_error.value.reasons == ("CYCLE_RESERVATION_CANONICAL_JSON_SIZE_LIMIT_EXCEEDED",)


def test_prior_row_limit_fails_before_any_prior_receipt_replay() -> None:
    hostile_prefix: list[dict[str, Any]] = [
        {} for _ in range(cycle_reservation_module.MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS + 1)
    ]

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=hostile_prefix)

    assert exc_info.value.reasons == ("CYCLE_RESERVATION_PRIOR_ROW_LIMIT_EXCEEDED",)


def test_underreported_prior_sequence_enforces_actual_iteration_limit() -> None:
    class UnderreportedPriorRows(list[dict[str, Any]]):
        def __len__(self) -> int:
            return 0

    hostile_prefix = UnderreportedPriorRows(
        {} for _ in range(cycle_reservation_module.MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS + 1)
    )

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=hostile_prefix)

    assert exc_info.value.reasons == ("CYCLE_RESERVATION_PRIOR_ROW_LIMIT_EXCEEDED",)


def test_prior_rows_are_materialized_once_then_replayed_from_same_copy() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="single-pass-prefix",
    )

    class SinglePassPriorRows(list[dict[str, Any]]):
        iterations = 0

        def __iter__(self) -> Iterator[dict[str, Any]]:
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("caller replayed the mutable source collection")
            return super().__iter__()

    snapshot_prefix = SinglePassPriorRows([prior])
    snapshot = _snapshot(prior_rows=snapshot_prefix)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="single-pass-candidate",
    )
    commit_prefix = SinglePassPriorRows([prior])

    receipt = _commit(snapshot, allocation, prior_rows=commit_prefix)

    assert snapshot["prior_accepted_count"] == 1
    assert receipt["status"] == "PASS"
    assert snapshot_prefix.iterations == 1
    assert commit_prefix.iterations == 1


def test_decimal_replay_is_independent_of_ambient_context() -> None:
    snapshot_kwargs: dict[str, Any] = {
        "equity": 3.0,
        "available_margin": 500.0,
        "realized_drawdown": 0.0,
        "precycle_total": 0.0,
        "precycle_symbol": 0.0,
        "max_total": 10.0,
        "max_symbol": 10.0,
        "margin_buffer": 0.1,
        "max_drawdown": 10.0,
        "max_loss": 10.0,
    }
    baseline_snapshot = _snapshot(**snapshot_kwargs)
    baseline_allocation = _candidate_for_snapshot(
        baseline_snapshot,
        notional=1.0,
        margin=1.0,
        max_loss=1.0,
    )
    baseline_receipt = _commit(baseline_snapshot, baseline_allocation)

    with localcontext() as hostile_context:
        hostile_context.prec = 2
        hostile_context.rounding = ROUND_DOWN
        hostile_context.Emin = -9
        hostile_context.Emax = 9
        hostile_context.traps[Inexact] = True
        hostile_context.traps[Rounded] = True
        replayed_snapshot = _snapshot(**snapshot_kwargs)
        replayed_allocation = _candidate_for_snapshot(
            replayed_snapshot,
            notional=1.0,
            margin=1.0,
            max_loss=1.0,
        )
        replayed_receipt = _commit(replayed_snapshot, replayed_allocation)

    assert replayed_snapshot == baseline_snapshot
    assert replayed_receipt == baseline_receipt


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("paper_only", False),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("live_order", True),
        ("test_order", True),
        ("leverage_mutation", True),
        ("margin_mode_mutation", True),
    ],
)
def test_allocator_paper_safety_flags_are_each_type_exact(
    field: str,
    unsafe_value: bool,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix=f"allocator-safety-{field}",
    )
    allocation[field] = unsafe_value

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert "CYCLE_RESERVATION_ALLOCATION_PAPER_SAFETY_FLAGS_INVALID" in (exc_info.value.reasons)


def test_allocator_lineage_bool_int_collision_fails_type_exact_replay() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix="allocator-lineage-bool-int",
    )
    allocation["lineage_ids"]["signal_id"] = True
    allocation["allocation_input_material"]["allocation_input"]["lineage_ids"]["signal_id"] = 1
    _reseal_allocation_input_identity(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert "CYCLE_RESERVATION_ALLOCATION_LINEAGE_MISMATCH" in exc_info.value.reasons


@pytest.mark.parametrize(
    ("field", "input_value"),
    [("symbol", "ETHUSDT"), ("timeframe", "5m"), ("action", "short")],
)
def test_allocator_output_identity_must_exactly_bind_canonical_input(
    field: str,
    input_value: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix=f"allocator-input-{field}",
    )
    allocation["allocation_input_material"]["allocation_input"][field] = input_value
    _reseal_allocation_input_identity(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert f"CYCLE_RESERVATION_ALLOCATION_INPUT_{field.upper()}_MISMATCH" in (
        exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("ttl_range_bool", "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID"),
        ("ttl_valid_int", "CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID"),
        (
            "source_error",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_STATUS_INVALID:continuous_edge_guardian",
        ),
        (
            "source_not_exact",
            "CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_EXACT_MATCH_INVALID:continuous_edge_guardian",
        ),
    ],
)
def test_revocable_provenance_rejects_type_and_source_semantic_lies(
    mutation: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"revocable-provenance-{mutation}",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    if mutation == "ttl_range_bool":
        receipt["guardian"]["ttl_required_range_seconds"] = [True, 180]
    elif mutation == "ttl_valid_int":
        receipt["guardian"]["ttl_valid"] = 1
    else:
        source = receipt["source_revalidation"]["continuous_edge_guardian"]
        if mutation == "source_error":
            source["read_status"] = "ERROR"
            source["present"] = False
        else:
            source["exact_match"] = False
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


def test_revocable_rejects_coherently_rehashed_blocked_tuning_receipt() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="revocable-tuning-blocked",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    tuning = receipt["source_revalidation"]["adaptive_tuning_source"]
    semantic = tuning["semantic_validation"]
    semantic["status"] = "BLOCKED"
    semantic["rejection_reasons"] = ["FIXTURE_SEMANTIC_BLOCK"]
    _rehash_receipt(semantic)
    tuning["semantic_validation_status"] = "BLOCKED"
    tuning["semantic_validation_receipt_hash"] = semantic["receipt_hash"]
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert (
        "CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_SEMANTIC_INVALID:semantic_validation"
        in exc_info.value.reasons
    )


def test_revocable_rejects_rehashed_runtime_owner_safety_contradiction() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="revocable-owner-live-route",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    owner = receipt["runtime_owner"]
    owner["current_projection"]["routes_to_live"] = True
    owner_hash = _hash(owner["current_projection"])
    owner["frozen_hash"] = owner_hash
    owner["current_hash"] = owner_hash
    owner["exact_match"] = True
    owner["current_projection_allows"] = True
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_REVOCABLE_RUNTIME_EXACT_MATCH_INVALID" in (
        exc_info.value.reasons
    )


def test_revocable_rejects_freeze_override_for_non_override_tier() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="revocable-unauthorized-freeze-override",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    receipt["effective_entry_freeze"].update(
        {
            "paper_new_entries_halted": True,
            "nonoverridable": False,
            "tier_override_allowed": True,
        }
    )
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_TIER_UNAUTHORIZED" in (exc_info.value.reasons)


@pytest.mark.parametrize(
    "tier",
    [
        "A_GRADE_EXECUTION_PAPER",
        "A_PLUS_BOOTSTRAP_REDUCED_SIZE_PAPER_ONLY",
        "B_GRADE_EXPLORATION_PAPER",
        "POSITIVE_EDGE_PROBATION_PAPER",
        "PAPER_RISK_CONTROLLER_EXPLORATION",
    ],
)
def test_final_v3_accepts_every_producer_executable_tier_name(tier: str) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"executable-tier-{tier}",
    )
    prior["paper_opportunity_tier"] = tier
    prior["paper_final_admission_contract"]["bound_material"]["tier_contract"][
        "paper_opportunity_tier"
    ] = tier
    _reseal_final_contract(prior)

    snapshot = _snapshot(prior_rows=[prior])

    assert snapshot["prior_accepted_count"] == 1


@pytest.mark.parametrize(
    "tier",
    [
        "B_GRADE_EXPLORATION_PAPER",
        "POSITIVE_EDGE_PROBATION_PAPER",
        "PAPER_RISK_CONTROLLER_EXPLORATION",
    ],
)
def test_exploration_tiers_do_not_require_a_grade_guardian_allow(tier: str) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"guardian-not-required-{tier}",
    )
    prior["paper_opportunity_tier"] = tier
    contract = prior["paper_final_admission_contract"]
    contract["bound_material"]["tier_contract"]["paper_opportunity_tier"] = tier
    receipt = prior["paper_revocable_control_commit_revalidation"]
    receipt["guardian"]["currently_allows_execution_tier"] = False
    _reseal_revocable_after_mutation(prior)

    snapshot = _snapshot(prior_rows=[prior])

    assert snapshot["prior_accepted_count"] == 1


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        (
            "decision",
            "BLOCKED",
            "CYCLE_RESERVATION_PRIOR_FINAL_EXECUTABLE_DECISION_INVALID",
        ),
        (
            "paper_fill_allowed",
            False,
            "CYCLE_RESERVATION_PRIOR_FINAL_PAPER_FILL_ALLOWED_NOT_TRUE",
        ),
        (
            "valid_for_paper",
            False,
            "CYCLE_RESERVATION_PRIOR_FINAL_VALID_FOR_PAPER_NOT_TRUE",
        ),
    ],
)
def test_final_v3_rejects_coherent_non_executable_semantics(
    field: str,
    value: Any,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"final-semantic-{field}",
    )
    prior[field] = value
    prior["paper_final_admission_contract"]["bound_material"]["tier_contract"][field] = value
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize("label", ["risk", "orchestrator"])
def test_final_v3_rejects_coherently_rehashed_non_allow_canonical_action(
    label: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"final-action-{label}",
    )
    bad_action = "deny"
    action_field = "risk_action" if label == "risk" else "orchestrator_action"
    top_field = "risk_controller_decision" if label == "risk" else "orchestrator_decision"
    record = prior[f"{label}_decision_record"]
    record[action_field] = bad_action
    record_hash = _decision_record_hash(record)
    prior[f"{label}_decision_record_hash"] = record_hash
    prior[top_field] = bad_action
    contract = prior["paper_final_admission_contract"]
    canonical = contract["bound_material"]["canonical_decision_contract"]
    canonical[action_field] = bad_action
    canonical[f"{label}_decision_record_hash"] = record_hash
    canonical["final_reread"][label]["record_hash"] = record_hash
    contract["canonical_decision_record_revalidation"] = copy.deepcopy(canonical["final_reread"])
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert f"CYCLE_RESERVATION_PRIOR_FINAL_{label.upper()}_ACTION_INVALID" in (
        exc_info.value.reasons
    )


def test_final_v3_top_level_pass_aliases_preserve_producer_allow_semantics() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="final-top-action-pass-alias",
    )
    prior["risk_controller_decision"] = "PASS"
    prior["orchestrator_decision"] = "PASS"
    _reseal_final_contract(prior)

    snapshot = _snapshot(prior_rows=[prior])

    assert snapshot["prior_accepted_count"] == 1


def test_final_v3_rejects_coherently_rehashed_blocked_preemptive_replay() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="final-preemptive-blocked",
    )
    contract = prior["paper_final_admission_contract"]
    revalidation = contract["preemptive_semantic_revalidation"]
    revalidation["status"] = "BLOCKED"
    revalidation["mismatch_fields"] = ["candidate.side"]
    contract["bound_material"]["preemptive_semantic_revalidation"] = copy.deepcopy(revalidation)
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_PREEMPTIVE_SEMANTIC_REVALIDATION_INVALID" in (
        exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            "precycle_order",
            "CYCLE_RESERVATION_PRIOR_FINAL_PRE_CYCLE_CLOCK_ORDER_INVALID",
        ),
        (
            "future_available",
            "CYCLE_RESERVATION_PRIOR_FINAL_COMPONENT_AFTER_DECISION:advanced_indicator_available_at",
        ),
        (
            "early_decision_reread",
            "CYCLE_RESERVATION_PRIOR_FINAL_REREAD_CLOCK_INVALID:canonical_decision_record_revalidation.risk.observed_at",
        ),
    ],
)
def test_final_v3_point_in_time_ordering_rejects_coherently_resealed_rows(
    mutation: str,
    expected_reason: str,
) -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix=f"final-pit-{mutation}",
    )
    contract = prior["paper_final_admission_contract"]
    bound = contract["bound_material"]
    if mutation == "precycle_order":
        prior["paper_precycle_exposure_snapshot_started_at"] = "2026-07-17T11:59:58Z"
        bound["component_times"] = {
            field: prior.get(field)
            for field in cycle_reservation_module._PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
        }
    elif mutation == "future_available":
        prior["advanced_indicator_available_at"] = "2026-07-17T12:00:01Z"
        bound["component_times"] = {
            field: prior.get(field)
            for field in cycle_reservation_module._PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
        }
    else:
        bound["canonical_decision_contract"]["final_reread"]["risk"]["observed_at"] = (
            "2026-07-17T11:59:58Z"
        )
        contract["canonical_decision_record_revalidation"] = copy.deepcopy(
            bound["canonical_decision_contract"]["final_reread"]
        )
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert expected_reason in exc_info.value.reasons


def test_final_v3_rejects_tuning_reread_before_validation_start() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="final-pit-tuning-reread",
    )
    receipt = prior["paper_revocable_control_commit_revalidation"]
    tuning = receipt["source_revalidation"]["adaptive_tuning_source"]
    semantic = tuning["semantic_validation"]
    semantic["observed_at"] = "2026-07-17T11:59:58Z"
    _rehash_receipt(semantic)
    tuning["semantic_validation_receipt_hash"] = semantic["receipt_hash"]
    _reseal_revocable_after_mutation(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert (
        "CYCLE_RESERVATION_PRIOR_FINAL_REREAD_CLOCK_INVALID:revocable_control.adaptive_tuning_source.semantic_validation.observed_at"
        in exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("price", "step_size", "quantity", "notional", "margin"),
    [
        (100.123456789, 3.0, 6.0, 600.74074073, 300.37037037),
        (100.12345679, 0.01, 7.99, 799.98641975, 399.99320988),
        (50000.12345678, 5e-13, 0.015999960493, 799.99999998, 399.99999999),
    ],
)
def test_authentic_allocator_raw_arithmetic_receipt_accepts_lossy_publications(
    price: float,
    step_size: float,
    quantity: float,
    notional: float,
    margin: float,
) -> None:
    snapshot = _snapshot(
        equity=10_000.0,
        available_margin=10_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_total=1.0,
        max_symbol=1.0,
        margin_buffer=0.0,
        max_drawdown=1.0,
        max_loss=1.0,
    )
    allocation = _authentic_growth_allocator_payload(
        snapshot,
        price=price,
        step_size=step_size,
        suffix=f"authentic-arithmetic-{price}-{step_size}",
    )

    assert allocation["target_quantity"] == quantity
    assert allocation["gross_notional_usd"] == notional
    assert allocation["effective_leverage"] == 2.0
    assert allocation["allocated_margin_usd"] == margin
    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "PASS"
    assert validate_candidate_commit_receipt(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        prior_accepted_rows=[],
        receipt=receipt,
    )
    assert validate_intrinsic_candidate_commit_receipt(
        snapshot=snapshot,
        adaptive_allocation=allocation,
        receipt=receipt,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            "wrong_type",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_TYPE_INVALID",
        ),
        (
            "extra_field",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_FIELDS_INVALID",
        ),
        (
            "missing_field",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_FIELDS_INVALID",
        ),
        (
            "wrong_hash_type",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID",
        ),
        (
            "hash_bit",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID",
        ),
    ],
)
def test_allocator_arithmetic_receipt_requires_exact_type_and_field_set(
    mutation: str,
    expected_reason: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix=f"arithmetic-structure-{mutation}",
    )
    if mutation == "wrong_type":
        allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY] = []
    else:
        arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
        assert isinstance(arithmetic, dict)
        if mutation == "extra_field":
            arithmetic["unexpected"] = True
        elif mutation == "missing_field":
            arithmetic.pop("formula")
        elif mutation == "wrong_hash_type":
            arithmetic["receipt_sha256"] = True
        else:
            receipt_hash = arithmetic["receipt_sha256"]
            assert isinstance(receipt_hash, str)
            arithmetic["receipt_sha256"] = ("0" if receipt_hash[0] != "0" else "1") + receipt_hash[
                1:
            ]

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize(
    ("field", "replacement", "expected_reason"),
    [
        (
            "schema_version",
            "paper_allocator_arithmetic_receipt_v2",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_INVALID",
        ),
        (
            "arithmetic_version",
            "adaptive_capital_allocator_binary64_arithmetic_v2",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION_INVALID",
        ),
        (
            "formula",
            "raw_notional=published_quantity*published_price",
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA_INVALID",
        ),
    ],
)
def test_coherently_rehashed_allocator_arithmetic_identity_mutation_rejects(
    field: str,
    replacement: str,
    expected_reason: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix=f"arithmetic-identity-{field}",
    )
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(arithmetic, dict)
    arithmetic[field] = replacement
    _rehash_allocator_arithmetic_receipt(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons
    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID" not in (
        exc_info.value.reasons
    )


@pytest.mark.parametrize(
    "value",
    [
        "nan",
        "inf",
        "-inf",
        "0x0.0p+0",
        "-0x1.0000000000000p+0",
        "0x1p+0",
        1,
        True,
    ],
)
def test_allocator_arithmetic_receipt_rejects_invalid_hex_domains(value: object) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix=f"arithmetic-invalid-hex-{value}",
    )
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(arithmetic, dict)
    arithmetic["raw_post_step_quantity_binary64_hex"] = value
    _rehash_allocator_arithmetic_receipt(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert any(
        reason.startswith("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_BINARY64_HEX_INVALID:")
        for reason in exc_info.value.reasons
    )


def test_allocator_arithmetic_receipt_one_bit_mutation_rejects() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix="arithmetic-one-bit",
    )
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(arithmetic, dict)
    raw_quantity = float.fromhex(arithmetic["raw_post_step_quantity_binary64_hex"])
    arithmetic["raw_post_step_quantity_binary64_hex"] = math.nextafter(
        raw_quantity,
        math.inf,
    ).hex()
    _rehash_allocator_arithmetic_receipt(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RAW_NOTIONAL_MISMATCH" in (
        exc_info.value.reasons
    )
    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID" not in (
        exc_info.value.reasons
    )


def test_coherently_rehashed_one_bit_selected_leverage_mutation_rejects() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix="arithmetic-one-bit-leverage",
    )
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(arithmetic, dict)
    raw_leverage = float.fromhex(arithmetic["selected_leverage_binary64_hex"])
    arithmetic["selected_leverage_binary64_hex"] = math.nextafter(
        raw_leverage,
        math.inf,
    ).hex()
    _rehash_allocator_arithmetic_receipt(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_SELECTED_LEVERAGE_NOT_PERMITTED" in (
        exc_info.value.reasons
    )
    assert "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID" not in (
        exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("field", "replacement", "expected_reason"),
    [
        (
            "raw_post_step_quantity_binary64_hex",
            2.0,
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RAW_NOTIONAL_MISMATCH",
        ),
        (
            "input_price_binary64_hex",
            101.0,
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_INPUT_PRICE_MISMATCH",
        ),
        (
            "raw_post_step_notional_binary64_hex",
            101.0,
            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RAW_NOTIONAL_MISMATCH",
        ),
        (
            "selected_leverage_binary64_hex",
            3.0,
            "CYCLE_RESERVATION_ALLOCATION_LEVERAGE_RECEIPT_MISMATCH:effective_leverage",
        ),
    ],
)
def test_coherently_rehashed_raw_operand_mismatch_rejects(
    field: str,
    replacement: float,
    expected_reason: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix=f"arithmetic-raw-mismatch-{field}",
    )
    arithmetic = allocation["model_inputs"][PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert isinstance(arithmetic, dict)
    arithmetic[field] = replacement.hex()
    _rehash_allocator_arithmetic_receipt(allocation)

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons


@pytest.mark.parametrize("publication", ["quantity", "notional", "leverage", "margin"])
def test_published_one_quantum_mutation_rejects_exact_receipt_replay(
    publication: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        leverage=2.0,
        suffix=f"arithmetic-published-quantum-{publication}",
    )
    if publication == "quantity":
        allocation["target_quantity"] += 1e-12
        allocation["model_inputs"]["paper_target_quantity_after_step_quantization"] += 1e-12
    elif publication == "notional":
        for field in ("gross_notional_usd", "target_notional_usdt", "target_notional_usd"):
            allocation[field] += 1e-8
        allocation["model_inputs"]["paper_target_notional_after_step_quantization_usd"] += 1e-8
    elif publication == "leverage":
        allocation["effective_leverage"] += 1e-8
        allocation["recommended_leverage"] += 1e-8
        allocation["model_inputs"]["selected_leverage"] += 1e-8
    else:
        allocation["allocated_margin_usd"] += 1e-8
        allocation["model_inputs"]["selected_allocated_margin_usd"] += 1e-8

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert any("RECEIPT_MISMATCH" in reason for reason in exc_info.value.reasons)


@pytest.mark.parametrize(
    ("notional", "leverage", "margin"),
    [
        (100.0, 2.0, 50.0),
        (100.0, 3.0, 33.33333333),
        (11_113.81949381, 2.0, 5_556.90974691),
    ],
)
def test_allocator_receipt_replays_producer_binary64_division_and_rounding(
    notional: float,
    leverage: float,
    margin: float,
) -> None:
    snapshot = _snapshot(
        equity=100_000.0,
        available_margin=100_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=notional,
        margin=margin,
        max_loss=10.0,
        leverage=leverage,
        suffix=f"margin-division-{leverage}",
    )

    receipt = _commit(snapshot, allocation)

    assert receipt["status"] == "PASS"
    assert receipt["candidate_resources"]["allocator_arithmetic_formula"] == (
        PAPER_ALLOCATOR_ARITHMETIC_FORMULA
    )
    assert receipt["candidate_resources"]["allocator_arithmetic_version"] == (
        PAPER_ALLOCATOR_ARITHMETIC_VERSION
    )
    assert receipt["candidate_resources"]["allocator_arithmetic_receipt_schema_version"] == (
        PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION
    )
    assert (
        receipt["candidate_resources"]["exact_decimal_material"]["allocator_arithmetic_identity"]
        == cycle_reservation_module.CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY
    )


def test_authentic_binary64_half_quantum_margin_rejects_decimal_half_even_result() -> None:
    snapshot = _snapshot(
        equity=100_000.0,
        available_margin=100_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
    )
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=11_113.81949381,
        margin=5_556.90974690,
        max_loss=10.0,
        leverage=2.0,
        suffix="binary64-half-quantum-decimal-half-even-rejected",
    )

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert any(
        reason.startswith("CYCLE_RESERVATION_ALLOCATION_MARGIN_RECEIPT_MISMATCH")
        for reason in exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("notional", "expected_margin"),
    [
        (11_113.81949380, Decimal("5556.90974690")),
        (11_113.81949381, Decimal("5556.90974691")),
        (11_113.81949382, Decimal("5556.90974691")),
    ],
)
def test_allocator_receipt_rounding_preserves_binary64_half_quantum_neighbors(
    notional: float,
    expected_margin: Decimal,
) -> None:
    replayed = cycle_reservation_module._allocator_binary64_round_decimal(
        notional / 2.0,
        8,
        "test_margin",
    )

    assert replayed == expected_margin


@pytest.mark.parametrize(
    ("notional", "leverage", "expected_margin"),
    [
        (0.125, 2.0, Decimal("0.0625")),
        (1.23456789, 4.0, Decimal("0.30864197")),
        (100.0, 3.0, Decimal("33.33333333")),
        (987.654321, 7.0, Decimal("141.09347443")),
    ],
)
def test_allocator_receipt_rounding_matches_bounded_producer_table(
    notional: float,
    leverage: float,
    expected_margin: Decimal,
) -> None:
    replayed = cycle_reservation_module._allocator_binary64_round_decimal(
        notional / leverage,
        8,
        "test_margin",
    )

    assert replayed == expected_margin


@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        1.0,
        Decimal("1"),
        "",
        "nan",
        "inf",
        "-inf",
        "0x0.0p+0",
        "-0x1.0000000000000p+0",
        "0X1.0000000000000P+0",
        "0x1p+0",
        " 0x1.0000000000000p+0",
        "0x1.0000000000000p+" + ("0" * 33),
    ],
    ids=(
        "bool",
        "integer",
        "float",
        "decimal",
        "empty",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "zero",
        "negative",
        "uppercase",
        "short-form",
        "leading-space",
        "oversized",
    ),
)
def test_allocator_receipt_rejects_noncanonical_or_nonpositive_binary64_hex(
    value: object,
) -> None:
    with pytest.raises(CycleReservationError):
        cycle_reservation_module._canonical_positive_binary64_hex(
            value,
            "test_operand",
        )


def test_allocator_margin_one_quantum_mutation_fails_exact_division_replay() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=33.33333333,
        max_loss=10.0,
        leverage=3.0,
        suffix="margin-division-one-quantum",
    )
    allocation["allocated_margin_usd"] = 33.33333334
    allocation["model_inputs"]["selected_allocated_margin_usd"] = 33.33333334

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert any(
        reason.startswith("CYCLE_RESERVATION_ALLOCATION_MARGIN_RECEIPT_MISMATCH")
        for reason in exc_info.value.reasons
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        (
            "selected_leverage",
            2.0,
            "CYCLE_RESERVATION_ALLOCATION_UPSTREAM_SELECTED_LEVERAGE_MISMATCH",
        ),
        (
            "selected_allocated_margin_usd",
            33.33333334,
            "CYCLE_RESERVATION_ALLOCATION_UPSTREAM_SELECTED_MARGIN_MISMATCH",
        ),
    ],
)
def test_allocator_selected_leverage_and_margin_must_bind_outputs_exactly(
    field: str,
    value: float,
    expected_reason: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=33.33333333,
        max_loss=10.0,
        leverage=3.0,
        suffix=f"selected-binding-{field}",
    )
    allocation["model_inputs"][field] = value

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons


def test_real_growth_authorized_allocator_three_x_payload_commits() -> None:
    snapshot = _snapshot(
        equity=10_000.0,
        available_margin=10_000.0,
        precycle_total=0.0,
        precycle_symbol=0.0,
        max_total=1.0,
        max_symbol=1.0,
        margin_buffer=0.0,
        max_drawdown=1.0,
        max_loss=1.0,
    )
    lineage = {
        "intent_id": "intent-real-growth-three-x",
        "signal_id": "signal-real-growth-three-x",
        "prediction_id": "prediction-real-growth-three-x",
        "risk_decision_id": "risk-real-growth-three-x",
        "orchestrator_decision_id": "orchestrator-real-growth-three-x",
        CYCLE_RESERVATION_LINEAGE_KEY: snapshot["snapshot_hash"],
    }
    atr_evidence, atr_reasons = build_paper_liquidation_atr_evidence(
        feature_snapshot={
            "feature_snapshot_id": "cycle-reservation-three-x-feature",
            "symbol": snapshot["candidate_symbol"],
            "timeframe": "1m",
            "feature_freshness_state": "CURRENT",
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "candle_close_time": "2026-07-19T11:59:00Z",
            "feature_cutoff": "2026-07-19T11:59:30Z",
            "available_at": "2026-07-19T11:59:40Z",
            "generated_at": "2026-07-19T11:59:45Z",
            "features": {"atr_bps": 1.0},
        },
        symbol=snapshot["candidate_symbol"],
        timeframe="1m",
        entry_price=100.0,
        allocation_decision_time="2026-07-19T12:00:01Z",
    )
    assert not atr_reasons
    assert atr_evidence is not None
    lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = atr_evidence
    lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY] = atr_evidence["evidence_sha256"]
    allocation_input = AllocationInput(
        symbol=snapshot["candidate_symbol"],
        timeframe="1m",
        action="long",
        price=100.0,
        equity=10_000.0,
        available_margin=10_000.0,
        wallet_balance=10_000.0,
        confidence_calibrated=0.95,
        expected_move_after_cost_bps=250.0,
        market_state_integrity_score=95.0,
        volatility_bps=1.0,
        liquidity_score=1.0,
        spread_bps=2.0,
        slippage_bps=2.0,
        maintenance_margin_rate=0.005,
        stop_distance_bps=80.0,
        entry_atr_bps=1.0,
        regime_score=1.0,
        permitted_leverage_values=(1.0, 2.0, 3.0, 4.0, 5.0),
        lineage_ids=lineage,
    )
    allocation = allocate_authorized_growth(
        allocation_input,
        RiskEnvelope(
            max_effective_leverage=5.0,
            max_total_portfolio_risk_pct=1.0,
            max_single_symbol_exposure_pct=1.0,
        ),
    ).to_payload()
    allocation.update(
        {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_order": False,
            "test_order": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
        }
    )

    assert allocation["effective_leverage"] == 3.0
    assert allocation["model_inputs"]["selected_leverage"] == 3.0
    assert allocation["allocated_margin_usd"] == 3333.33333333
    assert allocation["model_inputs"]["selected_allocated_margin_usd"] == (3333.33333333)
    receipt = _commit(snapshot, allocation)
    assert receipt["status"] == "PASS"


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            "quantity_price",
            "CYCLE_RESERVATION_ALLOCATION_QUANTITY_RECEIPT_MISMATCH:target_quantity",
        ),
        (
            "leverage_margin",
            "CYCLE_RESERVATION_ALLOCATION_UPSTREAM_SELECTED_MARGIN_MISMATCH",
        ),
        (
            "max_loss_authority",
            "CYCLE_RESERVATION_ALLOCATION_MAX_LOSS_AUTHORITY_INVALID",
        ),
    ],
)
def test_allocator_exact_equations_reject_sub_tolerance_economic_lies(
    mutation: str,
    expected_reason: str,
) -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix=f"allocator-equation-{mutation}",
    )
    if mutation == "quantity_price":
        allocation["target_quantity"] = 0.9999999999
        allocation["model_inputs"]["paper_target_quantity_after_step_quantization"] = 0.9999999999
    elif mutation == "leverage_margin":
        allocation["allocated_margin_usd"] = 49.99999999
    else:
        allocation["max_loss_if_stop_hit"] = 10.00000001
        allocation["max_loss_usd"] = 10.00000001
        allocation["model_inputs"]["max_loss_usd"] = 10.00000001

    with pytest.raises(CycleReservationError) as exc_info:
        _commit(snapshot, allocation)

    assert expected_reason in exc_info.value.reasons


def test_type_exact_final_identity_rejects_bool_int_collision_after_reseal() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="final-identity-bool-int",
    )
    prior["signal_id"] = True
    prior["paper_final_admission_contract"]["bound_material"]["identity"]["signal_id"] = 1
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_FINAL_IDENTITY_MISMATCH" in exc_info.value.reasons


def test_type_exact_revocable_copy_rejects_bool_int_collision_after_reseal() -> None:
    prior = _final_admitted_row(
        "ETHUSDT",
        notional=100.0,
        margin=50.0,
        max_loss=5.0,
        suffix="revocable-copy-bool-int",
    )
    contract = prior["paper_final_admission_contract"]
    contract_copy = contract["revocable_control_commit_revalidation"]
    contract_copy["guardian"]["ttl_valid"] = 1
    _rehash_receipt(contract_copy)
    _reseal_final_contract(prior)

    with pytest.raises(CycleReservationError) as exc_info:
        _snapshot(prior_rows=[prior])

    assert "CYCLE_RESERVATION_PRIOR_REVOCABLE_BOUND_MATERIAL_MISMATCH" in (exc_info.value.reasons)


def test_commit_receipt_does_not_alias_snapshot_dynamic_envelope_limits() -> None:
    snapshot = _snapshot(precycle_total=0.0, precycle_symbol=0.0)
    allocation = _candidate_for_snapshot(
        snapshot,
        notional=100.0,
        margin=50.0,
        max_loss=10.0,
        suffix="commit-no-envelope-alias",
    )
    receipt = _commit(snapshot, allocation)
    sealed_limits = copy.deepcopy(receipt["dynamic_envelope_limits"])
    snapshot["inputs"]["dynamic_envelope_limits"]["exact_decimal_material"][
        "max_total_portfolio_risk_pct"
    ] = "999"

    assert receipt["dynamic_envelope_limits"] == sealed_limits
    assert (
        receipt["dynamic_envelope_limits"]["exact_decimal_material"]
        is not snapshot["inputs"]["dynamic_envelope_limits"]["exact_decimal_material"]
    )
    receipt_material = dict(receipt)
    receipt_hash = receipt_material.pop("receipt_hash")
    assert receipt_hash == _hash(receipt_material)


def test_resource_bound_classification_is_not_market_policy() -> None:
    classifications = cycle_reservation_module.CYCLE_RESERVATION_IMMUTABLE_BOUND_CLASSIFICATION

    assert classifications
    assert all(
        classification.endswith("NOT_MARKET_POLICY") for classification in classifications.values()
    )
