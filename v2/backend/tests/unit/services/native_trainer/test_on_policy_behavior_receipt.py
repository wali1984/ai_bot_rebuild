from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.current_cycle_evidence import (
    process_instance_id,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    EVENT_TRAINER_CONSUMED,
    append_lifecycle_event,
    archive_behavior_receipt,
    receipt_lifecycle_status,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    ppo_trainer as ppo_trainer_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    publisher as publisher_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    ModelForwardResult,
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    U53_DENOMINATOR,
    adaptive_on_policy_lane_plan,
    behavior_receipt_rejection_reasons,
    build_exact_cost_provenance,
    build_finalized_outcome_binding,
    build_positive_edge_behavior_receipt,
    build_ppo_consumption_update_key,
    canonical_sha256,
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    PPO_INCOMPLETE_SAMPLED_COHORT_REASON,
    PPO_SAMPLING_COHORT_KEY_RESOLVER_MISSING_REASON,
    PPO_SAMPLING_COHORT_PROOF_AFTER_TRAINING_OBSERVED_REASON,
    PPO_SAMPLING_COHORT_PROOF_BINDING_MISMATCH_REASON,
    PPO_SAMPLING_COHORT_PROOF_INVALID_REASON,
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    V2HybridPredictionPublisher,
    build_prediction_payload,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _effective_paper_entry_gate_from_heartbeat,
    _optimizer_parameter_fingerprints_bound,
    _paper_margin_status_from_heartbeat,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.ordinary_paper_admission import (
    build_microstructure_trust_evidence,
)
from v2.backend.app.services.paper_trade_management import (
    lifecycle as paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.outcomes import (
    build_close_event,
    capture_close_outcome_availability,
)
from v2.backend.app.services.paper_trade_management.position_state import (
    PaperNetPosition,
    position_from_fill,
)
from v2.backend.tests.unit.services.native_trainer._authenticated_cohort_fixture import (
    archive_single_member_pre_admission_cohort,
    archive_single_member_terminalized_cohort,
    build_single_member_sampling_plan,
    sampling_plan_key_resolver,
)

CHECKPOINT_ID = "v2_hybrid_ckpt_deadbeef_0123456789abcdef_abcdef012345"
CHECKPOINT_EVIDENCE_DIGEST = "e" * 64


def _orderbook_source_payload(symbol: str = "BTCUSDT") -> dict[str, object]:
    return {
        "schema_version": "v2_orderbook_features_v1",
        "symbol": symbol,
        "event_time": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:01Z",
        "generated_at": "2026-07-18T00:00:02Z",
        "spread_bps": 0.5,
        "depth_5_bid_usd": 100.0,
        "depth_5_ask_usd": 120.0,
        "sequence_gap_flag": 0,
    }


def _cost_source_payload(symbol: str = "BTCUSDT") -> dict[str, object]:
    orderbook = _orderbook_source_payload(symbol)
    fee_evidence = {
        "schema_version": "paper_cost_fee_schedule_evidence_v1",
        "configuration_kind": "CONFIGURED_TAKER_FEE_BPS_PER_SIDE",
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit:paper_fee_schedule",
    }
    notional_evidence = {
        "schema_version": "paper_cost_notional_configuration_evidence_v1",
        "configuration_kind": "COST_MODEL_REFERENCE_NOTIONAL_USD",
        "notional_usd": 100.0,
        "notional_source": "UNIT_EXPLICIT_COST_MODEL_NOTIONAL_USD",
    }
    return {
        "symbol": symbol,
        "round_trip_cost_bps": 2.0,
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit:paper_fee_schedule",
        "fee_schedule_evidence": fee_evidence,
        "fee_schedule_evidence_sha256": canonical_sha256(fee_evidence),
        "spread_bps": 0.5,
        "spread_source": "orderbook_features_binance_live_spread_bps",
        "spread_age_seconds": 39.0,
        "impact_per_side_bps": 0.25,
        "impact_source": "notional_over_top5_depth_times_half_spread",
        "depth_used_usd": 100.0,
        "notional_usd_assumed": 100.0,
        "notional_configuration_evidence": notional_evidence,
        "notional_configuration_evidence_sha256": canonical_sha256(
            notional_evidence
        ),
        "freshness_status": "FRESH_ORDERBOOK",
        "conservative_floor_applied": False,
        "flat_baseline_round_trip_bps": 12.0,
        "orderbook_key": f"v2:orderbook:features:binance:{symbol}",
        "computed_utc": "2026-07-18T00:00:40Z",
        "available_at": "2026-07-18T00:00:40Z",
        "orderbook_schema_version": "v2_orderbook_features_v1",
        "orderbook_source_payload_sha256": canonical_sha256(orderbook),
        "orderbook_source_payload": orderbook,
        "orderbook_observed_at": "2026-07-18T00:00:00Z",
        "orderbook_available_at": "2026-07-18T00:00:01Z",
        "orderbook_generated_at": "2026-07-18T00:00:02Z",
        "orderbook_source_clock_field": "available_at",
        "orderbook_sequence_gap_flag": False,
        "source_future_clock_invalid": False,
        "adaptive_max_age_seconds": 120.0,
        "adaptive_freshness_sample_count": 3,
        "adaptive_freshness_method": (
            "RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"
        ),
        "adaptive_freshness_proven": True,
        "expires_at": "2026-07-18T00:02:01Z",
        "publication_ttl_seconds": 81,
        "estimator_version": "adaptive_cost_model_v1",
        "notes": [],
        "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
    }


def _cost_provenance(symbol: str = "BTCUSDT") -> dict[str, object]:
    return build_exact_cost_provenance(
        source_key=f"v2:costs:round_trip_bps:{symbol}",
        source_payload=_cost_source_payload(symbol),
        consumer_observed_at="2026-07-18T00:00:50Z",
    )


@pytest.mark.parametrize(
    ("mutations", "reason"),
    (
        (
            {"spread_bps": 0.4, "round_trip_cost_bps": 1.9},
            "exact_cost_spread_component_source_mismatch",
        ),
        (
            {"impact_per_side_bps": 0.2, "round_trip_cost_bps": 1.9},
            "exact_cost_impact_component_source_mismatch",
        ),
        (
            {"depth_used_usd": 80.0},
            "exact_cost_depth_used_source_mismatch",
        ),
        (
            {"taker_fee_bps_per_side": 0.4, "round_trip_cost_bps": 1.8},
            "exact_cost_fee_schedule_evidence_invalid",
        ),
        (
            {
                "notional_usd_assumed": 200.0,
                "impact_per_side_bps": 0.5,
                "round_trip_cost_bps": 2.5,
            },
            "exact_cost_notional_configuration_evidence_invalid",
        ),
    ),
)
def test_exact_cost_recomputes_components_from_bound_source_evidence(
    mutations: dict[str, object],
    reason: str,
) -> None:
    payload = _cost_source_payload()
    payload.update(mutations)

    with pytest.raises(ValueError, match=f"^{reason}$"):
        build_exact_cost_provenance(
            source_key="v2:costs:round_trip_bps:BTCUSDT",
            source_payload=payload,
            consumer_observed_at="2026-07-18T00:00:50Z",
        )


def _checkpoint() -> CheckpointManifest:
    return CheckpointManifest(
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_source="V2_LOCAL_TRAINED_CHECKPOINT",
        path=f".local_models/{CHECKPOINT_ID}.json",
        generated_utc="2026-07-18T00:00:45Z",
        model_id="unit_exact_behavior_model",
        input_dim=len(_tensor().model_vector),
        device="cpu",
        cuda_active=False,
        weight_blob_written=True,
        weight_file_path=f".local_models/{CHECKPOINT_ID}.weights.npz",
        weight_file_format="npz",
        weight_file_size_bytes=1,
        model_parameter_fingerprint="d" * 64,
        weight_file_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
    )


def _softmax(logits: tuple[float, ...]) -> tuple[float, ...]:
    maximum = max(logits)
    weights = tuple(math.exp(value - maximum) for value in logits)
    total = sum(weights)
    return tuple(value / total for value in weights)


def _model_output(*, selected_action: str = "short") -> ModelForwardResult:
    logits = (0.0, 3.0, -3.0, -8.0, -8.0, -8.0, -8.0)
    selected_index = 2 if selected_action == "short" else 1
    calibration_by_direction = {
        "long": {
            "confidence_raw": 0.8,
            "confidence_calibrated": 0.75,
            "calibration_fitted": True,
            "probability_semantics_valid": True,
            "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
            "selected_action": "long",
        },
        "short": {
            "confidence_raw": 0.2,
            "confidence_calibrated": 0.25,
            "calibration_fitted": True,
            "probability_semantics_valid": True,
            "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
            "selected_action": "short",
        },
    }
    for action, calibration in calibration_by_direction.items():
        calibration.update(
            {
                "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
                "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
                "model_parameter_fingerprint": "d" * 64,
                "selected_action_is_directional": True,
                "selected_action": action,
            }
        )
    selected_calibration = dict(calibration_by_direction[selected_action])
    selected_calibration.update(
        {
            "confidence_raw_by_direction": {"long": 0.8, "short": 0.2},
            "confidence_calibrated_by_direction": {
                "long": 0.75,
                "short": 0.25,
            },
            "confidence_calibration_by_direction": calibration_by_direction,
            "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
            "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
            "model_parameter_fingerprint": "d" * 64,
            "selected_action_is_directional": True,
        }
    )
    return ModelForwardResult(
        model_id="unit_exact_behavior_model",
        model_source="V2_LOCAL_TRAINED",
        action_logits=logits,
        action_probabilities=_softmax(logits),
        selected_action_index=selected_index,
        selected_action=selected_action,
        expected_move_bps=12.0,
        confidence_raw=float(selected_calibration["confidence_raw"]),
        confidence_calibrated=float(selected_calibration["confidence_calibrated"]),
        policy_value=0.125,
        masa_signal=0.0,
        calibration=selected_calibration,
        device="cpu",
        cuda_active=False,
        model_tensors_device_verified=True,
    )


def _tensor(index: int = 1) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_exact_behavior_{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"snapshot_exact_behavior_{index}",
        values=(0.01 * index,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
        decision_time="2026-07-18T00:00:45Z",
        source_lineage_hash="e" * 64,
    )


def _example() -> TrainingExample:
    tensor = _tensor()
    trust = {
        "accepted_for_training": True,
        "valid_for_training": True,
        "trainer_consumable": True,
        "reject_reasons": [],
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "decision_time": "2026-07-18T00:01:00Z",
        "feature_vector_hash": tensor.tensor_id,
        "selected_action": "short",
        "source_hashes": {"feature_vector_hash": tensor.tensor_id},
    }
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=2,
        label_expected_move_after_cost_bps=-8.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row=trust,
        decision_time=str(trust["decision_time"]),
    )


def _adaptive_example() -> TrainingExample:
    base = _example()
    trust = {
        **dict(base.trust_row or {}),
        "generated_at": "2026-07-18T00:00:30Z",
        "source_event_time": "2026-07-18T00:00:00Z",
        "source_event_time_est": "2026-07-18T00:00:00Z",
        "source_received_time_est": "2026-07-18T00:00:20Z",
        "source_available_time": "2026-07-18T00:00:30Z",
        "candle_open_time": "2026-07-17T23:59:00Z",
        "all_tf_candle_timestamps": ["2026-07-18T00:00:00Z"],
        "all_source_event_times": ["2026-07-18T00:00:00Z"],
        "mtf_snapshot_id": "mtf_exact_adaptive_1",
        "mtf_snapshot_valid": True,
        "decision_id": "decision_exact_adaptive_1",
        "feature_freshness_state": "CURRENT",
        "freshness_state": "FRESH",
        "source_mode": "paper",
    }
    microstructure_source = {
        "schema_version": "microstructure_trust_score_v2",
        "symbol": base.symbol,
        "timeframe": base.timeframe,
        "available_at": "2026-07-18T00:00:20Z",
        "decision_time": "2026-07-18T00:00:30Z",
        "generated_at": "2026-07-18T00:00:31Z",
        "microstructure_trust_score": 0.5,
        "composite_microstructure_trust_score": 0.5,
        "microstructure_action": "REDUCE_SIZE",
        "sweep_risk": 0.2,
        "sweep_risk_score": 0.2,
        "book_sequence_gap": False,
        "sequence_gap_flag": 0,
        "feed_integrity_pass": True,
        "latency_within_bound": True,
        "sequence_gap_free": True,
        "sweep_direction_uncertain": False,
        "missing_components": [],
    }
    microstructure_evidence = build_microstructure_trust_evidence(
        source_payload=microstructure_source,
        source_payload_readback=microstructure_source,
        source_key="v2:microstructure:trust_score:BTCUSDT:1m",
        source_observed_ttl_seconds=60,
        tensor_id=base.tensor.tensor_id,
        feature_snapshot_id=base.tensor.feature_snapshot_id,
        tensor_source_lineage_hash=base.tensor.source_lineage_hash,
        tensor_decision_time=base.tensor.decision_time,
        symbol=base.symbol,
        timeframe=base.timeframe,
    )
    trust["microstructure_trust_evidence"] = microstructure_evidence
    trust["microstructure_trust_evidence_sha256"] = microstructure_evidence[
        "evidence_sha256"
    ]
    return replace(
        base,
        trust_row=trust,
    )


def _plan_hashes() -> dict[str, Any]:
    candidate = {
        **_lane_candidate(),
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_tensor_id": "tensor_exact_behavior_1",
    }
    return adaptive_on_policy_lane_plan(
        [candidate],
        paper_margin_status=_margin_status(),
        paper_entry_freeze=_clear_freeze(),
        carry_in=1.0,
        single_candidate_ordinary_credit_in=1,
    )


def _receipt() -> dict[str, object]:
    return build_positive_edge_behavior_receipt(
        prediction_id="prediction_exact_1",
        model_output=_model_output(),
        symbol="BTCUSDT",
        timeframe="1m",
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        served_policy_fingerprint="d" * 64,
        feature_tensor_id="tensor_exact_behavior_1",
        feature_vector_hash="tensor_exact_behavior_1",
        feature_cutoff="2026-07-18T00:00:00Z",
        available_at="2026-07-18T00:00:30Z",
        candle_close_time="2026-07-18T00:00:00Z",
        decision_time="2026-07-18T00:01:00Z",
        candle_closed_confirmed=True,
        round_trip_cost_bps=2.0,
        cost_provenance=_cost_provenance(),
        draw_u53=U53_DENOMINATOR - 1,
        sampling_plan_hash="a" * 64,
        sampling_plan_input_hash="b" * 64,
    )


def _exact_ppo_example(
    *,
    index: int,
    model: V2HybridPolicyModel,
    policy_fingerprint: str,
    archive_root: Path | None = None,
    outcome_available_at: str | None = None,
) -> TrainingExample:
    tensor = _tensor(index)
    decision_time = f"2026-07-18T00:0{index}:00Z"
    exit_time = f"2026-07-18T00:0{index + 5}:00Z"
    forward = model.forward(tensor)
    cost_provenance = _cost_provenance()
    sampling_plan = build_single_member_sampling_plan(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_tensor_id=tensor.tensor_id,
        feature_cutoff="2026-07-18T00:00:00Z",
        available_at="2026-07-18T00:00:30Z",
        candle_close_time="2026-07-18T00:00:00Z",
        decision_time=decision_time,
        raw_action_logits=forward.action_logits,
        expected_move_bps=forward.expected_move_bps,
        exact_cost_payload_hash=str(cost_provenance["source_payload_sha256"]),
        parent_policy_fingerprint=policy_fingerprint,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
    )
    plan_hash = str(sampling_plan["plan_hash"])
    plan_input_hash = str(sampling_plan["input_hash"])
    receipt = build_positive_edge_behavior_receipt(
        prediction_id=f"prediction_optimizer_{index}",
        model_output=forward,
        symbol="BTCUSDT",
        timeframe="1m",
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        served_policy_fingerprint=policy_fingerprint,
        feature_tensor_id=tensor.tensor_id,
        feature_vector_hash=tensor.tensor_id,
        feature_cutoff="2026-07-18T00:00:00Z",
        available_at="2026-07-18T00:00:30Z",
        candle_close_time="2026-07-18T00:00:00Z",
        decision_time=decision_time,
        candle_closed_confirmed=True,
        round_trip_cost_bps=2.0,
        cost_provenance=cost_provenance,
        draw_u53=U53_DENOMINATOR - 1,
        sampling_plan_hash=plan_hash,
        sampling_plan_input_hash=plan_input_hash,
    )
    reward = 0.4 + (0.1 * index)
    gross_pnl_usd = reward + 0.02
    entry_price = 100.0
    exit_price = (
        entry_price + gross_pnl_usd
        if receipt["selected_action"] == "long"
        else entry_price - gross_pnl_usd
    )
    entry_fee_usd = 0.005
    exit_fee_usd = 0.005
    entry_slippage_usd = 0.005
    exit_slippage_usd = 0.005
    trust = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "accepted_for_training": True,
        "valid_for_training": True,
        "trainer_consumable": True,
        "reject_reasons": [],
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "mtf_snapshot_id": f"mtf_optimizer_{index}",
        "mtf_snapshot_valid": True,
        "replay_snapshot_id": f"replay_optimizer_{index}",
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "feature_freshness_state": "CURRENT",
        "freshness_state": "CURRENT",
        "latency_ms": 30,
        "candle_open_time": "2026-07-17T23:59:00Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "source_event_time": "2026-07-18T00:00:00Z",
        "source_event_time_est": "2026-07-18T00:00:00Z",
        "source_received_time_est": "2026-07-18T00:00:30Z",
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "decision_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "source_available_time": "2026-07-18T00:00:30Z",
        "decision_time": decision_time,
        "decision_time_est": decision_time,
        "masa_feature_cutoff": "2026-07-18T00:00:00Z",
        "ppo_feature_cutoff": "2026-07-18T00:00:00Z",
        "exit_time": exit_time,
        "label_available_at": exit_time,
        "close_id": f"close_optimizer_{index}",
        "position_id": f"position_optimizer_{index}",
        "close_event_time": exit_time,
        "outcome_generated_at": f"2026-07-18T00:0{index + 5}:01Z",
        "outcome_available_at": outcome_available_at
        or f"2026-07-18T00:0{index + 5}:02Z",
        "outcome_availability_status": "READY",
        "entry_price": entry_price,
        "exit_price": exit_price,
        "side": receipt["selected_action"],
        "closed_quantity": 1.0,
        "gross_realized_pnl_usd": gross_pnl_usd,
        "realized_gross_pnl_usd": gross_pnl_usd,
        "realized_net_pnl_usd": reward,
        "realized_net_pnl_bps": reward * 100.0,
        "closed_entry_notional_usd": entry_price,
        "closed_exit_notional_usd": exit_price,
        "entry_fee_usd": entry_fee_usd,
        "exit_fee_usd": exit_fee_usd,
        "total_fees_usd": entry_fee_usd + exit_fee_usd,
        "fees_usd": 0.01,
        "fees": 0.01,
        "entry_slippage_usd": entry_slippage_usd,
        "exit_slippage_usd": exit_slippage_usd,
        "total_slippage_usd": entry_slippage_usd + exit_slippage_usd,
        "slippage_usd": 0.01,
        "slippage": 0.01,
        "total_execution_costs_usd": 0.02,
        "funding_usd": 0.0,
        "funding_pnl_usd": 0.0,
        "funding": 0.0,
        "outcome_cost_unit": "USD",
        "paper_round_trip_cost_accounting_version": (
            "PAPER_ROUND_TRIP_CLOSE_COST_V1"
        ),
        "paper_cost_rate_scope": (
            "PER_SIDE_BPS_APPLIED_TO_CORRESPONDING_NOTIONAL"
        ),
        "paper_net_pnl_formula": (
            "realized_gross_pnl_usd - entry_fee_usd - exit_fee_usd - "
            "entry_slippage_usd - exit_slippage_usd + funding_pnl_usd"
        ),
        "round_trip_cost_fallback_used": False,
        "round_trip_cost_provenance_status": (
            "COMPLETE_ENTRY_AND_EXIT_COST_PROVENANCE"
        ),
        "entry_cost_accounting_version": "PAPER_ENTRY_COST_BASIS_V1",
        "entry_cost_allocation_method": (
            "PRO_RATA_BY_CLOSED_QUANTITY_WITH_FINAL_CLOSE_REMAINDER"
        ),
        "entry_cost_allocation_fraction_of_pre_close_position": 1.0,
        "entry_cost_pre_close_quantity": 1.0,
        "entry_cost_closed_quantity": 1.0,
        "entry_cost_is_final_close": True,
        "entry_fee_source": "UNIT_ENTRY_FEE_USD",
        "entry_fee_fallback": False,
        "entry_fee_fallback_bps_per_side": None,
        "entry_fee_bps_per_side": entry_fee_usd / entry_price * 10_000.0,
        "entry_slippage_source": "UNIT_ENTRY_SLIPPAGE_USD",
        "entry_slippage_fallback": False,
        "entry_slippage_fallback_bps_per_side": None,
        "entry_slippage_bps_per_side": (
            entry_slippage_usd / entry_price * 10_000.0
        ),
        "entry_cost_basis_status": (
            "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
        ),
        "exit_fee_source": "UNIT_ENTRY_BOUND_EXIT_FEE_RATE",
        "exit_fee_fallback": False,
        "exit_fee_rate_basis": (
            "ENTRY_BOUND_PER_SIDE_FEE_RATE_REUSED_FOR_PAPER_EXIT"
        ),
        "exit_fee_bps_per_side": exit_fee_usd / exit_price * 10_000.0,
        "exit_slippage_source": "UNIT_EXIT_SPREAD",
        "exit_slippage_available_at": exit_time,
        "exit_slippage_fallback": False,
        "exit_slippage_provenance_status": (
            "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME"
        ),
        "exit_slippage_bps_per_side": (
            exit_slippage_usd / exit_price * 10_000.0
        ),
        "features": {"ret_pct": 0.01 * index},
        "prediction_id": receipt["prediction_id"],
        "selected_action": receipt["selected_action"],
        "selected_action_index": receipt["selected_action_index"],
        "model_version": forward.model_id,
        "checkpoint_id": receipt["checkpoint_id"],
        "feature_tensor_id": tensor.tensor_id,
        "feature_vector_hash": tensor.tensor_id,
        "source_hashes": {"feature_vector_hash": tensor.tensor_id},
        "outcome_targets": {
            "realized_net_pnl_bps": reward * 100.0,
            "realized_net_pnl_usd": reward,
            "directional_outcome": "UP",
            "trade_outcome": "WIN",
            "selected_action": "long",
            "action_was_profitable": True,
            "holding_period": 300,
            "fees": 0.01,
            "slippage": 0.01,
            "funding": 0.0,
            "MFE": reward * 100.0,
            "MAE": 1.0,
            "exit_reason": "unit",
        },
        "realized_after_cost_reward": reward,
        "value_baseline": receipt["policy_value"],
        "advantage": reward - float(receipt["policy_value"]),
        "advantage_source": "realized_after_cost_reward_minus_value_baseline",
        "realized_reward_source": "realized_net_pnl_bps_after_cost",
        "uses_expected_move_as_realized_reward": False,
        "old_log_prob": receipt["selected_action_log_prob"],
        "old_value": receipt["policy_value"],
        "reward": reward,
        "done": True,
        "rollout_id": f"rollout_optimizer_{index}",
        "trajectory_index": index - 1,
        "behavior_action_index": receipt["selected_action_index"],
        "behavior_action": receipt["selected_action"],
        "behavior_action_mask": list(receipt["behavior_action_mask"]),
        "behavior_action_source": receipt["behavior_action_source"],
        "behavior_policy_sampling_mode": receipt["behavior_policy_sampling_mode"],
        "behavior_policy_distribution_contract": receipt["behavior_policy_distribution_contract"],
        "behavior_policy_fingerprint": receipt["served_policy_fingerprint"],
        "behavior_policy_checkpoint_hash": receipt["checkpoint_weight_sha256"],
        "behavior_policy_receipt": receipt,
        "behavior_policy_receipt_hash": receipt["receipt_hash"],
        "behavior_policy_receipt_key": (
            "v2:trainer:hybrid_cuda:on_policy_receipt:" f"{receipt['receipt_hash']}"
        ),
        "behavior_policy_receipt_write_success": True,
        "on_policy_action_receipt_valid": True,
        "action_labels": list(receipt["action_labels"]),
        "raw_action_logits": list(receipt["raw_action_logits"]),
        "raw_action_probabilities": list(receipt["raw_action_probabilities"]),
        "action_probabilities": list(receipt["action_probabilities"]),
        "selected_action_probability": receipt["selected_action_probability"],
        "selected_action_log_prob": receipt["selected_action_log_prob"],
        "policy_value": receipt["policy_value"],
        "on_policy_sampling_selected": True,
        "on_policy_sampling_requested": True,
        "on_policy_sampling_plan_hash": plan_hash,
        "on_policy_sampling_plan_input_hash": plan_input_hash,
        "on_policy_sampling_lane": "ADAPTIVE_BOUNDED_PAPER_EXPLORATION",
        "on_policy_sampling_evidence_class": "PAPER_EXPLORATION_LEARNING_ONLY",
        "on_policy_sampling_counts_as_a_plus_evidence": False,
        "on_policy_sampling_routes_to_live": False,
        "ppo_on_policy_entry_fields_present": True,
        "entry_policy_fields_source": "V2_NATIVE_CUDA_TRAINER_ENTRY_FORWARD_PASS",
        "strategy_supply_hypothesis": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    finalized = build_finalized_outcome_binding(trust)
    trust.update(finalized)
    trust["ppo_consumption_update_key"] = build_ppo_consumption_update_key(
        behavior_policy_receipt_hash=receipt["receipt_hash"],
        finalized_outcome_digest=finalized["finalized_outcome_digest"],
        parent_behavior_fingerprint=policy_fingerprint,
    )
    trust["ppo_consumption_ledger_eligible"] = True
    if archive_root is not None:
        archived, cohort_manifest = archive_single_member_pre_admission_cohort(
            root=archive_root,
            sampling_plan=sampling_plan,
            receipt=receipt,
            parent_policy_fingerprint=policy_fingerprint,
            checkpoint_id=CHECKPOINT_ID,
            checkpoint_weight_sha256="c" * 64,
        )
        published = append_lifecycle_event(
            receipt_hash=str(receipt["receipt_hash"]),
            event_type=EVENT_PUBLISHED,
            binding={
                "prediction_id": receipt["prediction_id"],
                "symbol": receipt["symbol"],
                "timeframe": receipt["timeframe"],
                "checkpoint_id": receipt["checkpoint_id"],
                "decision_time": decision_time,
                "archive_content_sha256": archived.archive_content_sha256,
            },
            root=archive_root,
            recorded_at=decision_time,
        )
        entry = append_lifecycle_event(
            receipt_hash=str(receipt["receipt_hash"]),
            event_type=EVENT_ENTRY_ACCEPTED,
            binding={
                "paper_fill_id": f"fill_optimizer_{index}",
                "prediction_id": receipt["prediction_id"],
                "symbol": receipt["symbol"],
                "timeframe": receipt["timeframe"],
                "decision_time": decision_time,
                "entry_time": decision_time,
                "entry_fee_schedule_evidence_sha256": receipt[
                    "cost_provenance"
                ]["source_payload"]["fee_schedule_evidence_sha256"],
            },
            root=archive_root,
            recorded_at=decision_time,
        )
        finalized_event = append_lifecycle_event(
            receipt_hash=str(receipt["receipt_hash"]),
            event_type=EVENT_OUTCOME_FINALIZED,
            binding={
                "finalized_outcome_id": trust["finalized_outcome_id"],
                "finalized_outcome_digest": trust["finalized_outcome_digest"],
                "ppo_consumption_update_key": trust[
                    "ppo_consumption_update_key"
                ],
                "outcome_available_at": trust["outcome_available_at"],
            },
            root=archive_root,
            recorded_at=str(trust["outcome_available_at"]),
        )
        cohort_proof = archive_single_member_terminalized_cohort(
            root=archive_root,
            manifest=cohort_manifest,
            receipt_hash=str(receipt["receipt_hash"]),
            generated_at=str(trust["outcome_available_at"]),
        )
        trust.update(
            {
                "behavior_policy_receipt_archive_write_success": True,
                "behavior_policy_receipt_archive_content_sha256": (
                    archived.archive_content_sha256
                ),
                "behavior_policy_receipt_archive_published_event_hash": (
                    published.event_hash
                ),
                "behavior_policy_receipt_archive_entry_event_hash": (
                    entry.event_hash
                ),
                "behavior_policy_receipt_archive_finalized": True,
                "behavior_policy_receipt_archive_finalization_event_hash": (
                    finalized_event.event_hash
                ),
                "behavior_policy_receipt_archive_retention_required_until_trainer_consumption": (
                    True
                ),
                "on_policy_sampling_cohort_completeness_proof": cohort_proof,
                "on_policy_sampling_cohort_completeness_verified": True,
                "on_policy_sampling_cohort_receipt_membership_verified": True,
                "on_policy_sampling_cohort_completeness_digest": cohort_proof[
                    "cohort_digest"
                ],
            }
        )
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=1,
        label_expected_move_after_cost_bps=10.0,
        payload_keys=(f"optimizer:{index}",),
        row_classification="TRAINABLE",
        trust_row=trust,
        decision_time=decision_time,
        label_available_at=exit_time,
    )


def _lane_candidate(index: int = 0) -> dict[str, object]:
    return {
        "symbol": f"COIN{index}USDT",
        "timeframe": "1m",
        "feature_tensor_id": f"tensor_{index}",
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "candle_closed_confirmed": True,
        "decision_time": "2026-07-18T00:01:00Z",
        "row_classification": "TRAINABLE",
        "raw_action_logits": [0.0] * 7,
        "confidence_calibrated": 0.5,
        "confidence_calibration_fitted": True,
        "expected_move_bps": 12.0,
        "round_trip_cost_bps": 2.0,
        "exact_cost_provenance_valid": True,
        "exact_cost_payload_hash": _cost_provenance()[
            "source_payload_sha256"
        ],
        "served_policy_fingerprint_available": True,
        "served_policy_fingerprint": "d" * 64,
        "confidence_candidate_action": "long",
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_weight_sha256": "c" * 64,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
    }


def _margin_status() -> dict[str, object]:
    return {
        "schema_version": "paper_account_margin_v1",
        "status": "PASS",
        "invariant_holds": True,
        "margin_base_usd": 100.0,
        "free_margin_after_buffer_usd": 100.0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _clear_freeze() -> dict[str, object]:
    return {
        "schema_version": "paper_entry_freeze_v1",
        "paper_new_entries_halted": False,
        "new_entries_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _ordinary_scale_free_output(
    *,
    confidence: float = 0.75,
    expected_move_bps: float = 12.0,
    calibration_fitted: bool = True,
) -> ModelForwardResult:
    output = _model_output(selected_action="long")
    calibration = deepcopy(output.calibration)
    calibration.update(
        {
            "confidence_raw": confidence,
            "confidence_calibrated": confidence,
            "calibration_fitted": calibration_fitted,
            "probability_semantics_valid": calibration_fitted,
        }
    )
    return replace(
        output,
        expected_move_bps=expected_move_bps,
        confidence_raw=confidence,
        confidence_calibrated=confidence,
        calibration=calibration,
    )


def _ordinary_scale_free_example(
    *,
    coverage_percent: float = 100.0,
    dirty: bool = False,
    future: bool = False,
) -> TrainingExample:
    example = _adaptive_example()
    tensor = replace(
        example.tensor,
        data_coverage_percent=coverage_percent,
        missing_mask=(1,) if dirty else (0,),
        missing_feature_names=("ret_pct",) if dirty else (),
    )
    trust = dict(example.trust_row or {})
    if dirty:
        trust.update(
            {
                "missing_feature_count": 1,
                "missing_feature_names": ["ret_pct"],
            }
        )
    if future:
        trust.update(
            {
                "available_at": "2026-07-18T00:02:00Z",
                "source_available_time": "2026-07-18T00:02:00Z",
                "source_received_time_est": "2026-07-18T00:02:00Z",
                "all_source_event_times": ["2026-07-18T00:02:00Z"],
            }
        )
    return replace(example, tensor=tensor, trust_row=trust)


def _ordinary_scale_free_payload(
    *,
    example: TrainingExample | None = None,
    model_output: ModelForwardResult | None = None,
    cost_provenance: dict[str, object] | None | object = ...,
    cycle_identity: bool = False,
) -> dict[str, Any]:
    provenance = _cost_provenance() if cost_provenance is ... else cost_provenance
    return build_prediction_payload(
        example=example or _ordinary_scale_free_example(),
        model_output=model_output or _ordinary_scale_free_output(),
        checkpoint=_checkpoint(),
        round_trip_cost_bps=2.0,
        min_data_coverage_percent=99.999999,
        min_confidence_calibrated=0.999999,
        min_edge_after_cost_bps=1_000_000.0,
        cost_provenance=provenance,
        decision_time_utc="2026-07-18T00:01:00Z",
        cycle_id="v2_cycle_ordinary_scale_free" if cycle_identity else None,
        process_instance_id=process_instance_id() if cycle_identity else None,
        candidate_policy_fingerprint="d" * 64 if cycle_identity else None,
    )


class _ExactMicrostructurePipeline:
    def __init__(self, raw: str, ttl_seconds: int) -> None:
        self.raw = raw
        self.ttl_seconds = ttl_seconds

    def get(self, _key: str) -> "_ExactMicrostructurePipeline":
        return self

    def ttl(self, _key: str) -> "_ExactMicrostructurePipeline":
        return self

    def execute(self) -> list[object]:
        return [self.raw, self.ttl_seconds]


class _ExactMicrostructureRedis:
    def __init__(self, payload: dict[str, Any], ttl_seconds: int = 60) -> None:
        self.raw = json.dumps(payload, sort_keys=True)
        self.ttl_seconds = ttl_seconds

    def pipeline(self, *, transaction: bool) -> _ExactMicrostructurePipeline:
        assert transaction is True
        return _ExactMicrostructurePipeline(self.raw, self.ttl_seconds)


def test_data_loader_exact_microstructure_readback_is_accepted_by_publisher() -> None:
    example = _ordinary_scale_free_example()
    source = deepcopy(
        (example.trust_row or {})["microstructure_trust_evidence"]["source_payload"]
    )
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(client=_ExactMicrostructureRedis(source))
    )
    trust_row = loader._build_trust_row(
        symbol=example.symbol,
        timeframe=example.timeframe,
        payloads={
            "_keys": {
                "microstructure_trust": (
                    "v2:microstructure:trust_score:BTCUSDT:1m"
                )
            },
            "microstructure_trust": source,
            "features_latest": {
                "decision_time": "2026-07-18T00:01:00Z",
                "feature_freshness_state": "CURRENT",
            },
            "prediction": {"decision_time": "2026-07-18T00:01:00Z"},
        },
        tensor=example.tensor,
        classification="TRAINABLE",
    )
    evidence = trust_row["microstructure_trust_evidence"]
    assert evidence["evidence_valid"] is True
    assert evidence["source_payload"] == source
    assert evidence["source_payload_loaded_sha256"] == evidence[
        "source_payload_sha256"
    ]
    assert evidence["source_observed_ttl_seconds"] == 60

    publisher_trust = dict(example.trust_row or {})
    publisher_trust["microstructure_trust_evidence"] = evidence
    publisher_trust["microstructure_trust_evidence_sha256"] = evidence[
        "evidence_sha256"
    ]
    payload = _ordinary_scale_free_payload(
        example=replace(example, trust_row=publisher_trust)
    )

    assert payload["ordinary_paper_fill_allowed"] is True
    assert payload["microstructure_trust_evidence"] == evidence
    assert payload["source_hashes"]["microstructure_trust_evidence_sha256"] == (
        evidence["evidence_sha256"]
    )


@pytest.mark.parametrize("positive_edge_bps", (1e-12, 1e-8, 0.01, 10.0, 1e6))
def test_ordinary_paper_admits_every_positive_edge_without_legacy_cliff(
    positive_edge_bps: float,
) -> None:
    payload = _ordinary_scale_free_payload(
        example=_ordinary_scale_free_example(coverage_percent=1e-9),
        model_output=_ordinary_scale_free_output(
            confidence=1e-9,
            expected_move_bps=2.0 + positive_edge_bps,
        ),
    )

    assert payload["ordinary_paper_fill_allowed"] is True
    assert payload["paper_fill_allowed"] is True
    assert payload["routes_to_orchestrator"] is True
    assert payload["paper_quality_sizing_weight"] > 0.0
    assert payload["legacy_static_thresholds_telemetry_only"][
        "legacy_would_allow"
    ] is False
    assert payload["legacy_static_thresholds_telemetry_only"][
        "controls_ordinary_paper_fill"
    ] is False


def test_ordinary_paper_quality_is_continuous_and_common_scale_invariant() -> None:
    weights: list[float] = []
    for scale in (1e-12, 1e-6, 1.0, 1e6, 1e12):
        evidence, reasons = publisher_module._ordinary_paper_quality_evidence(
            data_coverage_percent=37.0,
            confidence_probability=0.23,
            expected_after_cost_bps=3.0 * scale,
            round_trip_cost_bps=2.0 * scale,
            selected_action="long",
        )
        assert reasons == []
        weights.append(float(evidence["paper_quality_sizing_weight"]))

    assert weights == pytest.approx([weights[0]] * len(weights), rel=1e-12)


def test_ordinary_paper_blocks_structural_zero_nonfinite_dirty_future_and_unfitted() -> None:
    cases = (
        (
            "zero_coverage",
            {"example": _ordinary_scale_free_example(coverage_percent=0.0)},
            "ordinary_paper_coverage_outside_positive_percent_range",
        ),
        (
            "nonfinite_coverage",
            {"example": _ordinary_scale_free_example(coverage_percent=math.inf)},
            "ordinary_paper_coverage_nonfinite_or_missing",
        ),
        (
            "zero_probability",
            {"model_output": _ordinary_scale_free_output(confidence=0.0)},
            "ordinary_paper_probability_outside_positive_unit_interval",
        ),
        (
            "nonfinite_probability",
            {"model_output": _ordinary_scale_free_output(confidence=math.inf)},
            "ordinary_paper_probability_nonfinite_or_missing",
        ),
        (
            "zero_edge",
            {"model_output": _ordinary_scale_free_output(expected_move_bps=2.0)},
            "ordinary_paper_after_cost_edge_zero",
        ),
        (
            "nonfinite_edge",
            {"model_output": _ordinary_scale_free_output(expected_move_bps=math.inf)},
            "ordinary_paper_after_cost_edge_nonfinite_or_missing",
        ),
        (
            "sign_mismatch",
            {"model_output": _ordinary_scale_free_output(expected_move_bps=1.0)},
            "ordinary_paper_after_cost_edge_direction_mismatch",
        ),
        (
            "unfitted",
            {
                "model_output": _ordinary_scale_free_output(
                    calibration_fitted=False
                )
            },
            "ordinary_paper_confidence_calibration_unfitted_or_semantics_invalid",
        ),
        (
            "dirty",
            {"example": _ordinary_scale_free_example(dirty=True)},
            "ordinary_paper_row_integrity:adaptive_row_missing_features",
        ),
        (
            "future",
            {"example": _ordinary_scale_free_example(future=True)},
            "ordinary_paper_row_integrity:adaptive_row_source_clock_after_decision",
        ),
        (
            "cost_missing",
            {"cost_provenance": None},
            "ordinary_paper_exact_cost:behavior_receipt_exact_cost_provenance_missing",
        ),
    )
    for name, overrides, expected_reason in cases:
        payload = _ordinary_scale_free_payload(**overrides)
        assert payload["ordinary_paper_fill_allowed"] is False, name
        assert payload["paper_fill_allowed"] is False, name
        assert payload["routes_to_orchestrator"] is False, name
        assert expected_reason in json.dumps(payload, sort_keys=True), name


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    (
        (
            "available_at",
            "2026-07-17T23:59:59Z",
            "ordinary_paper_feature_cutoff_after_available_at",
        ),
        (
            "available_at",
            "2026-07-18T00:01:00Z",
            "ordinary_paper_available_at_not_before_decision",
        ),
        (
            "candle_close_time",
            "2026-07-18T00:00:01Z",
            "ordinary_paper_candle_close_after_feature_cutoff",
        ),
        (
            "all_tf_candle_timestamps",
            ["2026-07-18T00:00:01Z"],
            "ordinary_paper_all_tf_candle_timestamps_after_feature_cutoff",
        ),
        (
            "all_source_event_times",
            ["2026-07-18T00:00:31Z"],
            "ordinary_paper_all_source_event_times_after_available_at",
        ),
    ),
)
def test_ordinary_paper_revalidation_rejects_inverted_clock_lineage(
    field: str,
    value: Any,
    expected_reason: str,
) -> None:
    payload = _ordinary_scale_free_payload()
    payload[field] = value

    reasons = publisher_module._ordinary_scale_free_payload_rejection_reasons(
        payload,
        require_replay_write=False,
    )

    assert expected_reason in reasons


def test_ordinary_lineage_and_risk_recompute_quality_and_ignore_legacy_floors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publisher_module,
        "append_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            snapshot_id="snapshot_ordinary_scale_free",
            content_sha256="f" * 64,
            blob_path=tmp_path / "snapshot.json",
        ),
    )
    payload = _ordinary_scale_free_payload(
        example=_ordinary_scale_free_example(coverage_percent=1e-8),
        model_output=_ordinary_scale_free_output(
            confidence=1e-8,
            expected_move_bps=2.0 + 1e-8,
        ),
        cycle_identity=True,
    )
    redis = _FakeNxRedis()
    publisher = V2HybridPredictionPublisher(
        io=V2OnlyJsonIO(redis),
        current_cycle_publication_ttl_seconds=60,
    )
    assert publisher.publish_prediction(payload) is True
    lineage = publisher.publish_lineage(
        prediction_payload=payload,
        min_confidence_calibrated=1.0,
        min_data_coverage_percent=100.0,
        risk_caps_configured=True,
    )
    assert lineage["orchestrator_decision_record"]["decision_action"] == "open_long"
    assert lineage["risk_decision_record"]["risk_action"] == "allow"
    assert lineage["paper_execution_ledger_entry"]["ledger_action"] == "record_allow"
    assert lineage["risk_decision_record"][
        "ordinary_scale_free_paper_admission_revalidated"
    ] is True
    assert lineage["paper_signal_lineage"]["paper_quality_sizing_weight"] == (
        payload["paper_quality_sizing_weight"]
    )

    tampered = deepcopy(payload)
    tampered["paper_quality_sizing_weight"] = 1.0
    tampered_lineage = publisher.publish_lineage(
        prediction_payload=tampered,
        min_confidence_calibrated=0.0,
        min_data_coverage_percent=0.0,
        risk_caps_configured=True,
    )
    assert tampered_lineage["risk_decision_record"]["risk_action"] == "deny"
    assert tampered_lineage["risk_decision_record"][
        "ordinary_scale_free_paper_admission_revalidated"
    ] is False
    assert "ordinary_paper_quality_weight_binding_invalid" in (
        tampered_lineage["risk_decision_record"][
            "ordinary_scale_free_paper_admission_rejection_reasons"
        ]
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("side", "short", "finalized_outcome_side_action_mismatch"),
        (
            "exit_price",
            102.0,
            "finalized_outcome_gross_pnl_price_arithmetic_mismatch",
        ),
        (
            "round_trip_cost_fallback_used",
            True,
            "finalized_outcome_round_trip_cost_fallback_used",
        ),
        (
            "entry_fee_usd",
            0.006,
            "finalized_outcome_fee_component_arithmetic_mismatch",
        ),
        (
            "exit_slippage_available_at",
            "2026-07-18T00:09:00Z",
            "finalized_outcome_exit_slippage_temporal_order_invalid",
        ),
    ),
)
def test_finalized_outcome_recomputes_round_trip_and_rejects_fallback_or_tamper(
    field: str,
    value: object,
    reason: str,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=23)
    if not model.torch_available:
        pytest.skip("exact finalized outcome proof requires torch")
    example = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=model_parameter_fingerprint(model),
    )
    assert example.trust_row is not None
    tampered = deepcopy(example.trust_row)
    tampered[field] = value

    with pytest.raises(ValueError, match=f"^{reason}$"):
        build_finalized_outcome_binding(tampered)


def test_runtime_requires_the_composed_paper_entry_gate() -> None:
    active = {
        **_clear_freeze(),
        "schema_version": "paper_effective_entry_gate_status_v1",
        "status": "ACTIVE",
    }

    assert (
        _effective_paper_entry_gate_from_heartbeat({"paper_effective_entry_gate_status": active})
        == active
    )
    assert _effective_paper_entry_gate_from_heartbeat({"paper_entry_freeze": active}) == active
    assert _effective_paper_entry_gate_from_heartbeat({}) is None
    assert (
        _effective_paper_entry_gate_from_heartbeat({"paper_entry_freeze": _clear_freeze()}) is None
    )

    assert (
        _paper_margin_status_from_heartbeat({"paper_account_margin_status": _margin_status()})
        == _margin_status()
    )
    invalid_margin = dict(_margin_status())
    invalid_margin["routes_to_live"] = True
    assert (
        _paper_margin_status_from_heartbeat({"paper_account_margin_status": invalid_margin}) is None
    )


def test_receipt_binds_exact_sample_mask_policy_and_pit_clocks() -> None:
    receipt = _receipt()

    assert behavior_receipt_rejection_reasons(receipt) == []
    assert receipt["selected_action"] == "long"
    assert receipt["selected_action_index"] == 1
    assert receipt["behavior_action_mask"] == [True, True, False, False, False, False, False]
    assert receipt["paper_only"] is True
    assert receipt["routes_to_live"] is False
    assert receipt["on_policy_sampling_counts_as_a_plus_evidence"] is False


def test_receipt_rejects_naive_clock_and_semantic_tamper_even_after_rehash() -> None:
    with pytest.raises(ValueError, match="strict_utc"):
        build_positive_edge_behavior_receipt(
            prediction_id="prediction_exact_1",
            model_output=_model_output(),
            symbol="BTCUSDT",
            timeframe="1m",
            checkpoint_id=CHECKPOINT_ID,
            checkpoint_weight_sha256="c" * 64,
            checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
            checkpoint_evidence_verified=True,
            checkpoint_identity_verified=True,
            served_policy_fingerprint="d" * 64,
            feature_tensor_id="tensor_exact_behavior_1",
            feature_vector_hash="tensor_exact_behavior_1",
            feature_cutoff="2026-07-18T00:00:00",
            available_at="2026-07-18T00:00:30Z",
            candle_close_time="2026-07-18T00:00:00Z",
            decision_time="2026-07-18T00:01:00Z",
            candle_closed_confirmed=True,
            round_trip_cost_bps=2.0,
            cost_provenance=_cost_provenance(),
            draw_u53=1,
            sampling_plan_hash="a" * 64,
            sampling_plan_input_hash="b" * 64,
        )

    tampered = deepcopy(_receipt())
    tampered["raw_action_logits"][1] = 30.0
    unsigned = dict(tampered)
    unsigned.pop("receipt_hash")
    tampered["receipt_hash"] = canonical_sha256(unsigned)

    reasons = behavior_receipt_rejection_reasons(tampered)
    assert "behavior_receipt_raw_probabilities_mismatch" in reasons
    assert "behavior_receipt_action_probabilities_mismatch" in reasons


def test_adaptive_lane_is_reproducible_and_reserves_ordinary_predictions() -> None:
    candidates = [_lane_candidate(index) for index in range(4)]
    first = adaptive_on_policy_lane_plan(
        candidates,
        paper_margin_status=_margin_status(),
        paper_entry_freeze=_clear_freeze(),
    )
    second = adaptive_on_policy_lane_plan(
        candidates,
        paper_margin_status=_margin_status(),
        paper_entry_freeze=_clear_freeze(),
    )

    assert first == second
    assert 0 < first["selected_sample_count"] < len(candidates)
    assert first["ordinary_lane_reserved_count"] >= 1
    assert first["structural_ordinary_lane_reservation"] is True
    assert first["market_static_sampling_threshold_used"] is False
    assert len(first["input_hash"]) == 64
    assert len(first["plan_hash"]) == 64


def test_single_candidate_lane_accumulates_credit_without_starving_ordinary_lane() -> None:
    carry = 0.0
    ordinary_credit = 0
    sampled_counts: list[int] = []
    for _ in range(4):
        plan = adaptive_on_policy_lane_plan(
            [_lane_candidate()],
            paper_margin_status=_margin_status(),
            paper_entry_freeze=_clear_freeze(),
            carry_in=carry,
            single_candidate_ordinary_credit_in=ordinary_credit,
        )
        sampled_counts.append(int(plan["selected_sample_count"]))
        carry = float(plan["carry_out"])
        ordinary_credit = int(plan["single_candidate_ordinary_credit_out"])

    assert sampled_counts[0] == 0
    assert 1 in sampled_counts
    assert sampled_counts.count(0) >= sampled_counts.count(1)


def test_lane_safety_failure_samples_none_but_preserves_ordinary_supply() -> None:
    blocked_margin = dict(_margin_status())
    blocked_margin["invariant_holds"] = False
    plan = adaptive_on_policy_lane_plan(
        [_lane_candidate(index) for index in range(3)],
        paper_margin_status=blocked_margin,
        paper_entry_freeze=_clear_freeze(),
        carry_in=1.0,
    )

    assert plan["selected_sample_count"] == 0
    assert plan["ordinary_lane_reserved_count"] == 3
    assert plan["safety_gate_passed"] is False
    assert "paper_margin_invariant_not_proven" in plan["safety_rejection_reasons"]


@pytest.mark.parametrize(
    "classification",
    ["STALE_MASKED", "MISSING_MASKED", "MARKET_STATE_REJECTED"],
)
def test_lane_never_samples_dirty_or_rejected_rows(classification: str) -> None:
    candidate = _lane_candidate()
    candidate["row_classification"] = classification
    plan = adaptive_on_policy_lane_plan(
        [candidate],
        paper_margin_status=_margin_status(),
        paper_entry_freeze=_clear_freeze(),
        carry_in=1.0,
        single_candidate_ordinary_credit_in=1,
    )

    assert plan["selected_sample_count"] == 0
    assert plan["ordinary_lane_reserved_count"] == 1
    assert plan["candidate_audit"][0]["eligible"] is False
    assert "on_policy_learning_row_not_trainable" in plan["candidate_audit"][0]["rejection_reasons"]


def test_unselected_forward_remains_deterministic_and_selected_forward_gets_receipt() -> None:
    example = _example()
    output = _model_output(selected_action="short")
    common = {
        "example": example,
        "model_output": output,
        "checkpoint": _checkpoint(),
        "round_trip_cost_bps": 2.0,
        "min_data_coverage_percent": 0.0,
        "min_confidence_calibrated": 0.0,
        "min_edge_after_cost_bps": 0.0,
        "served_policy_fingerprint": "d" * 64,
        "checkpoint_weight_sha256": "c" * 64,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
        "cost_provenance": _cost_provenance(),
        "on_policy_sampling_plan": _plan_hashes(),
        "decision_time_utc": "2026-07-18T00:01:00Z",
    }
    ordinary = build_prediction_payload(
        **common,
        on_policy_sampling_selected=False,
    )
    sampled = build_prediction_payload(
        **common,
        on_policy_sampling_selected=True,
        behavior_sample_draw_u53=U53_DENOMINATOR - 1,
    )

    assert ordinary["selected_action"] == "short"
    assert ordinary["confidence_calibrated"] == pytest.approx(0.25)
    assert ordinary["on_policy_sampling_lane"] == "ORDINARY_DETERMINISTIC_NATIVE_POLICY"
    assert ordinary.get("behavior_policy_receipt") is None
    assert ordinary["paper_intent_consumable"] is True
    assert sampled["selected_action"] == "long"
    assert sampled["confidence_raw"] == pytest.approx(0.8)
    assert sampled["confidence_calibrated"] == pytest.approx(0.75)
    assert sampled["confidence_calibration"]["selected_action"] == "long"
    assert sampled["on_policy_action_receipt_valid"] is True
    assert sampled["behavior_policy_receipt"]["selected_action"] == "long"
    assert sampled["prediction_id"] != ordinary["prediction_id"]


def test_both_paper_lanes_ignore_legacy_static_floors_with_separate_receipts() -> None:
    valid_example = _adaptive_example()
    common = {
        "example": valid_example,
        "model_output": _model_output(selected_action="long"),
        "checkpoint": _checkpoint(),
        "round_trip_cost_bps": 2.0,
        "min_data_coverage_percent": 101.0,
        "min_confidence_calibrated": 0.99,
        "min_edge_after_cost_bps": 100.0,
        "served_policy_fingerprint": "d" * 64,
        "checkpoint_weight_sha256": "c" * 64,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
        "cost_provenance": _cost_provenance(),
        "on_policy_sampling_plan": _plan_hashes(),
        "decision_time_utc": "2026-07-18T00:01:00Z",
    }
    ordinary = build_prediction_payload(
        **common,
        on_policy_sampling_selected=False,
    )
    sampled = build_prediction_payload(
        **common,
        on_policy_sampling_selected=True,
        behavior_sample_draw_u53=U53_DENOMINATOR - 1,
    )

    assert ordinary["ordinary_paper_fill_allowed"] is True
    assert ordinary["paper_fill_allowed"] is True
    assert ordinary["routes_to_orchestrator"] is True
    assert ordinary["ordinary_paper_legacy_static_threshold_bypassed"] is True
    assert sampled["ordinary_paper_fill_allowed"] is False
    assert sampled["adaptive_paper_exploration_fill_allowed"] is True
    assert sampled["adaptive_paper_exploration_static_market_gate_bypassed"] is True
    assert sampled["paper_fill_allowed"] is True
    assert sampled["routes_to_orchestrator"] is True
    assert sampled["ordinary_paper_gate_block_reasons"] == [
        "ordinary_paper_lane_is_sampled_exploration"
    ]
    assert not set(sampled["paper_fill_gate_block_reasons"]) & {
        "data_coverage_below_threshold",
        "confidence_below_threshold",
        "expected_move_after_cost_below_threshold",
        "ordinary_paper_lane_is_sampled_exploration",
    }
    assert ordinary["legacy_static_thresholds_telemetry_only"] == (
        sampled["legacy_static_thresholds_telemetry_only"]
    )


def test_market_state_trainer_consumable_has_no_numeric_coverage_default() -> None:
    trusted = _example()
    tiny_coverage = replace(
        trusted,
        tensor=replace(trusted.tensor, data_coverage_percent=0.000001),
    )
    rejected = replace(
        trusted,
        trust_row={**dict(trusted.trust_row or {}), "trainer_consumable": False},
    )

    trusted_row = publisher_module._market_state_row_from_example(  # noqa: SLF001
        tiny_coverage,
        "prediction_tiny_coverage",
    )
    rejected_row = publisher_module._market_state_row_from_example(  # noqa: SLF001
        rejected,
        "prediction_rejected_high_coverage",
    )

    assert trusted_row["trainer_consumable"] is True
    assert trusted_row["trainer_consumable_evidence_source"] == (
        "EXPLICIT_TRAINABLE_ROW_AND_TRUST_FLAGS"
    )
    assert rejected.tensor.data_coverage_percent == 100.0
    assert rejected_row["trainer_consumable"] is False


def test_adaptive_exact_lane_fails_closed_on_each_immutable_invariant() -> None:
    base = _adaptive_example()
    output = _model_output(selected_action="short")
    common: dict[str, Any] = {
        "example": base,
        "model_output": output,
        "checkpoint": _checkpoint(),
        "round_trip_cost_bps": 2.0,
        "min_data_coverage_percent": 101.0,
        "min_confidence_calibrated": 0.99,
        "min_edge_after_cost_bps": 100.0,
        "served_policy_fingerprint": "d" * 64,
        "checkpoint_weight_sha256": "c" * 64,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
        "cost_provenance": _cost_provenance(),
        "on_policy_sampling_selected": True,
        "behavior_sample_draw_u53": U53_DENOMINATOR - 1,
        "on_policy_sampling_plan": _plan_hashes(),
        "decision_time_utc": "2026-07-18T00:01:00Z",
    }

    stale = replace(
        base,
        tensor=replace(
            base.tensor,
            stale_mask=(1,),
            stale_feature_names=("ret_pct",),
        ),
    )
    missing = replace(
        base,
        tensor=replace(
            base.tensor,
            missing_mask=(1,),
            missing_feature_names=("ret_pct",),
        ),
    )
    pit_trust = dict(base.trust_row or {})
    pit_trust["available_at"] = "2026-07-18T00:01:01Z"
    pit_trust["source_available_time"] = "2026-07-18T00:01:01Z"
    pit_invalid = replace(base, trust_row=pit_trust)
    rejected_classification = replace(base, row_classification="MARKET_STATE_REJECTED")

    unfitted_calibration = deepcopy(output.calibration)
    by_direction = deepcopy(
        unfitted_calibration["confidence_calibration_by_direction"]
    )
    by_direction["long"]["calibration_fitted"] = False
    unfitted_calibration["confidence_calibration_by_direction"] = by_direction
    unfitted_output = replace(output, calibration=unfitted_calibration)

    blocked_margin = dict(_margin_status())
    blocked_margin["invariant_holds"] = False
    blocked_margin_plan = adaptive_on_policy_lane_plan(
        [
            {
                **_lane_candidate(),
                "symbol": "BTCUSDT",
                "feature_tensor_id": "tensor_exact_behavior_1",
            }
        ],
        paper_margin_status=blocked_margin,
        paper_entry_freeze=_clear_freeze(),
        carry_in=1.0,
        single_candidate_ordinary_credit_in=1,
    )

    cases = (
        ("stale", {"example": stale}, "adaptive_row_stale_features"),
        ("missing", {"example": missing}, "adaptive_row_missing_features"),
        (
            "pit",
            {"example": pit_invalid},
            "behavior_receipt_available_at_not_before_decision_time",
        ),
        (
            "row_integrity",
            {"example": rejected_classification},
            "adaptive_row_not_trainable",
        ),
        (
            "cost",
            {"cost_provenance": None},
            "behavior_receipt_exact_cost_invalid",
        ),
        (
            "margin",
            {"on_policy_sampling_plan": blocked_margin_plan},
            "adaptive_sampling_margin_invariant_not_proven",
        ),
        (
            "calibration",
            {"model_output": unfitted_output},
            "confidence_calibration_unfitted_or_semantics_invalid",
        ),
    )
    for name, overrides, expected_reason in cases:
        payload = build_prediction_payload(**{**common, **overrides})
        assert payload["adaptive_paper_exploration_fill_allowed"] is False, name
        assert payload["paper_fill_allowed"] is False, name
        assert payload["routes_to_orchestrator"] is False, name
        assert expected_reason in json.dumps(payload, sort_keys=True), name


def test_adaptive_exact_publisher_to_lineage_routes_with_impossible_legacy_scores_paper_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publisher_module,
        "_market_state_fields_from_example",
        lambda _example, _prediction_id: {
            "market_state_id": "market_state_low_legacy_score",
            "market_state_integrity_score": 0.0,
            "valid_for_training": False,
            "valid_for_prediction": False,
            "valid_for_risk": False,
            "valid_for_orchestrator": False,
            "valid_for_paper": False,
            "valid_for_live": False,
            "decision_cutoff_time_est": "2026-07-18T00:01:00Z",
            "market_state_reject_reasons": ["LATENCY_OR_PAYLOAD_AGE_MISSING"],
            "market_state_score_components": {},
            "market_state_source_lineage": {},
        },
    )
    monkeypatch.setattr(
        publisher_module,
        "append_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            snapshot_id="snapshot_exact_adaptive_archive",
            content_sha256="f" * 64,
            blob_path=tmp_path / "snapshot.json",
        ),
    )
    payload = build_prediction_payload(
        example=_adaptive_example(),
        model_output=_model_output(selected_action="short"),
        checkpoint=_checkpoint(),
        round_trip_cost_bps=2.0,
        min_data_coverage_percent=101.0,
        min_confidence_calibrated=0.99,
        min_edge_after_cost_bps=100.0,
        served_policy_fingerprint="d" * 64,
        checkpoint_weight_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        cost_provenance=_cost_provenance(),
        on_policy_sampling_selected=True,
        behavior_sample_draw_u53=U53_DENOMINATOR - 1,
        on_policy_sampling_plan=_plan_hashes(),
        decision_time_utc="2026-07-18T00:01:00Z",
        cycle_id="v2_cycle_canonical_lineage_test",
        process_instance_id=process_instance_id(),
        candidate_policy_fingerprint="d" * 64,
    )
    assert payload["ordinary_paper_fill_allowed"] is False
    assert payload["adaptive_paper_exploration_fill_allowed"] is True
    assert payload["adaptive_paper_exploration_legacy_integrity_score_bypassed"] is True
    assert payload["routes_to_orchestrator"] is True

    redis = _FakeNxRedis()
    publisher = V2HybridPredictionPublisher(
        io=V2OnlyJsonIO(redis),
        behavior_receipt_archive_root=tmp_path / "behavior_archive",
        current_cycle_publication_ttl_seconds=60,
    )
    assert publisher.publish_prediction(payload) is True
    lineage = publisher.publish_lineage(
        prediction_payload=payload,
        min_confidence_calibrated=0.99,
        min_data_coverage_percent=101.0,
        risk_caps_configured=True,
    )

    orchestrator = lineage["orchestrator_decision_record"]
    risk = lineage["risk_decision_record"]
    paper = lineage["paper_execution_ledger_entry"]
    signal = lineage["paper_signal_lineage"]
    assert orchestrator["decision_action"] == "open_long"
    assert risk["risk_action"] == "allow"
    assert paper["ledger_action"] == "record_allow"
    assert orchestrator["live_blocked"] is True
    assert risk["live_blocked"] is True
    assert paper["live_blocked"] is True
    assert signal["live_gate"] == "blocked_human_only"
    assert signal["live_symbols"] == []
    assert signal["on_policy_sampling_routes_to_live"] is False
    assert signal["authoritative_decision"] is False
    assert lineage["publication_receipt"]["publication_complete"] is True
    assert (
        lineage["publication_receipt"]["publication_scope"]
        == "TRAINER_NONAUTHORITATIVE_PROPOSALS_ONLY"
    )
    assert len(lineage["publication_receipt"]["component_receipts"]) == 9
    assert all(
        component["acknowledged"] is True
        and component["readback_verified"] is True
        for component in lineage["publication_receipt"]["component_receipts"]
    )
    assert (
        lineage["publication_receipt"][
            "counts_as_end_to_end_authoritative_lineage"
        ]
        is False
    )
    assert not any(key.startswith("v2:decision:") for key in redis.store)


class _FakeNxRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False):
        del ex
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key: str):
        return self.store.get(key)


class _ExpiringStatusRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key: str):
        return self.store.get(key)


class _UnacknowledgedExpiringStatusRedis(_ExpiringStatusRedis):
    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> None:
        super().set(key, value, ex=ex, nx=nx)
        return None


def test_immutable_json_write_is_create_or_identical_never_overwrite() -> None:
    redis = _FakeNxRedis()
    io = V2OnlyJsonIO(client=redis)
    key = "v2:trainer:hybrid_cuda:on_policy_receipt:" + "e" * 64

    assert io.set_json_immutable(key, {"proof": 1}, ex=60) is True
    assert io.set_json_immutable(key, {"proof": 1}, ex=60) is True
    assert io.set_json_immutable(key, {"proof": 2}, ex=60) is False
    assert json.loads(redis.store[key]) == {"proof": 1}
    assert any("immutable_content_conflict" in error for error in io.audit.errors)


def test_trainer_status_publication_has_cadence_derived_expiry_and_identity() -> None:
    redis = _ExpiringStatusRedis()
    instance_id = process_instance_id()
    envelope = {
        "cycle_id": "v2_cycle_status_publication_test",
        "process_instance_id": instance_id,
        "checkpoint_id": "checkpoint-test",
        "candidate_policy_fingerprint": "a" * 64,
    }
    status = {
        "feature_schema_status": "ALIGNED",
        "cycle_id": envelope["cycle_id"],
        "process_instance_id": instance_id,
        "current_cycle_learning_envelope": envelope,
    }
    publisher = V2HybridPredictionPublisher(io=V2OnlyJsonIO(client=redis))

    result = publisher.publish_status(
        status=status,
        metrics={"unit": True},
        expected_cycle_cadence_seconds=7,
    )

    assert result["publication_complete"] is True
    assert result["ttl_seconds"] == 21
    assert result["process_instance_id"]
    assert status["status_publication_status"] == "ACTIVE"
    assert status["status_payload_expires_at"] == result["expires_at"]
    assert set(redis.ttls.values()) == {21}
    heartbeat = json.loads(
        redis.store["v2:trainer:hybrid_cuda:heartbeat"]
    )
    assert heartbeat["expires_at"] == result["expires_at"]
    assert heartbeat["liveness_semantics"] == "ACTIVE_ONLY_UNTIL_EXPIRES_AT"


def test_trainer_status_publication_requires_expiring_write_acknowledgement() -> None:
    redis = _UnacknowledgedExpiringStatusRedis()
    status = {"feature_schema_status": "ALIGNED"}
    io = V2OnlyJsonIO(client=redis)
    publisher = V2HybridPredictionPublisher(io=io)

    result = publisher.publish_status(
        status=status,
        metrics={"unit": True},
        expected_cycle_cadence_seconds=7,
    )

    assert result["publication_complete"] is False
    assert status["status_publication_status"] == "FAILED"
    assert status["runtime_readiness_status"] == "BLOCKED"
    assert "STATUS_PUBLICATION_FAILED" in status["runtime_readiness_blockers"]
    assert any(
        error.startswith("expiring_set_not_acknowledged:")
        for error in io.audit.errors
    )


def test_behavior_receipt_is_persisted_without_fixed_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class RecordingIO:
        def __init__(self) -> None:
            self.immutable_expiries: list[int | None] = []

        def set_json_immutable(
            self,
            _key: str,
            _payload: object,
            *,
            ex: int | None = None,
        ) -> bool:
            self.immutable_expiries.append(ex)
            return True

        def set_json(
            self,
            _key: str,
            _payload: object,
            *,
            ex: int | None = None,
        ) -> bool:
            del ex
            return True

    monkeypatch.setattr(publisher_module, "is_publishable", lambda _payload: True)
    monkeypatch.setattr(
        publisher_module,
        "behavior_receipt_rejection_reasons",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        publisher_module,
        "build_archive_record_from_prediction_payload",
        lambda _payload: None,
    )
    io = RecordingIO()
    publisher = V2HybridPredictionPublisher(  # type: ignore[arg-type]
        io=io,
        behavior_receipt_archive_root=tmp_path,
    )
    receipt = {"schema_version": "unit_receipt_v1"}
    receipt["receipt_hash"] = canonical_sha256(receipt)
    payload = {
        "prediction_id": "prediction_retention_proof",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-07-18T00:01:00Z",
        "selected_action": "long",
        "selected_action_index": 1,
        "on_policy_action_receipt_valid": True,
        "paper_fill_allowed": True,
        "routes_to_orchestrator": True,
        "behavior_policy_receipt": receipt,
    }

    assert publisher.publish_prediction(payload) is True
    assert io.immutable_expiries == [None]
    assert payload["behavior_policy_receipt_write_success"] is True
    assert payload["behavior_policy_receipt_archive_write_success"] is True


def test_model_parameter_fingerprint_changes_with_exact_in_memory_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=7)
    before = model_parameter_fingerprint(model)
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001
    after = model_parameter_fingerprint(model)

    assert before != after


def test_exact_ppo_admission_requires_direct_finalized_archive_evidence(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=31)
    fingerprint = model_parameter_fingerprint(model)
    example = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    assert trainer._ppo_ineligibility_reason(example) == (  # noqa: SLF001
        "BEHAVIOR_POLICY_DURABLE_ARCHIVE_INVALID"
    )


def test_exact_ppo_cohort_gate_reauthenticates_instead_of_trusting_markers(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=41)
    if not model.torch_available:
        pytest.skip("exact authenticated cohort regression requires torch")
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
    fingerprint = model_parameter_fingerprint(model)
    valid = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
        archive_root=tmp_path,
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )
    assert trainer._ppo_ineligibility_reason(valid) is None  # noqa: SLF001
    assert valid.trust_row is not None

    self_attested = deepcopy(valid.trust_row)
    self_attested.pop("on_policy_sampling_cohort_completeness_proof")
    self_attested["on_policy_sampling_cohort_completeness_verified"] = True
    self_attested[
        "on_policy_sampling_cohort_receipt_membership_verified"
    ] = True
    self_attested["on_policy_sampling_cohort_completeness_digest"] = "f" * 64
    assert trainer._ppo_ineligibility_reason(  # noqa: SLF001
        replace(valid, trust_row=self_attested)
    ) == PPO_INCOMPLETE_SAMPLED_COHORT_REASON

    no_resolver = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
    )
    assert no_resolver._ppo_ineligibility_reason(valid) == (  # noqa: SLF001
        PPO_SAMPLING_COHORT_KEY_RESOLVER_MISSING_REASON
    )

    forged_proof = deepcopy(valid.trust_row)
    forged_proof["on_policy_sampling_cohort_completeness_proof"][
        "cohort_digest"
    ] = "f" * 64
    forged_proof["on_policy_sampling_cohort_completeness_digest"] = "f" * 64
    assert trainer._ppo_ineligibility_reason(  # noqa: SLF001
        replace(valid, trust_row=forged_proof)
    ) == PPO_SAMPLING_COHORT_PROOF_INVALID_REASON

    mismatched_marker = deepcopy(valid.trust_row)
    mismatched_marker["on_policy_sampling_cohort_completeness_digest"] = (
        "f" * 64
    )
    assert trainer._ppo_ineligibility_reason(  # noqa: SLF001
        replace(valid, trust_row=mismatched_marker)
    ) == PPO_SAMPLING_COHORT_PROOF_BINDING_MISMATCH_REASON


def test_exact_ppo_rejects_archive_receipt_after_terminal_consumption(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=33)
    fingerprint = model_parameter_fingerprint(model)
    example = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
        archive_root=tmp_path,
    )
    row = dict(example.trust_row)
    ledger_recorded_utc = "2026-07-18T00:07:00Z"
    append_lifecycle_event(
        receipt_hash=str(row["behavior_policy_receipt_hash"]),
        event_type=EVENT_TRAINER_CONSUMED,
        binding={
            "ppo_consumption_update_key": row["ppo_consumption_update_key"],
            "ledger_sequence": 1,
            "ledger_chain_hash": "a" * 64,
            "ledger_disposition": "NON_SERVING_CANDIDATE_PERSISTED",
            "ledger_recorded_utc": ledger_recorded_utc,
            "checkpoint_id": "checkpoint-consumed-1",
            "child_policy_fingerprint": "b" * 64,
            "finalized_outcome_digest": row["finalized_outcome_digest"],
        },
        root=tmp_path,
        recorded_at=ledger_recorded_utc,
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    assert trainer._ppo_ineligibility_reason(example) == (  # noqa: SLF001
        "PPO_UPDATE_ALREADY_DURABLY_CONSUMED"
    )


def test_exact_ppo_rejects_2099_outcome_not_observed_by_training_cycle(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=37)
    fingerprint = model_parameter_fingerprint(model)
    example = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
        archive_root=tmp_path,
        outcome_available_at="2099-01-01T00:00:00Z",
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
        training_observed_at="2026-07-18T10:00:00Z",
    )

    assert trainer._ppo_ineligibility_reason(example) == (  # noqa: SLF001
        PPO_SAMPLING_COHORT_PROOF_AFTER_TRAINING_OBSERVED_REASON
    )

    class _ProofWithDivergentGet(Mapping[str, Any]):
        """Expose archived bytes to iteration while lying through ``get``."""

        def __init__(self, backing: Mapping[str, Any]) -> None:
            self._backing = dict(backing)

        def __getitem__(self, key: str) -> Any:
            return self._backing[key]

        def __iter__(self) -> Iterator[str]:
            return iter(self._backing)

        def __len__(self) -> int:
            return len(self._backing)

        def get(self, key: str, default: Any = None) -> Any:
            if key == "generated_at":
                return "2026-07-18T00:07:00Z"
            return self._backing.get(key, default)

    divergent_row = dict(example.trust_row or {})
    archived_proof = divergent_row[
        "on_policy_sampling_cohort_completeness_proof"
    ]
    assert isinstance(archived_proof, Mapping)
    divergent_proof = _ProofWithDivergentGet(archived_proof)
    assert divergent_proof.get("generated_at") == "2026-07-18T00:07:00Z"
    assert dict(divergent_proof)["generated_at"].startswith("2099-")
    divergent_row[
        "on_policy_sampling_cohort_completeness_proof"
    ] = divergent_proof
    assert trainer._ppo_ineligibility_reason(  # noqa: SLF001
        replace(example, trust_row=divergent_row)
    ) == PPO_SAMPLING_COHORT_PROOF_AFTER_TRAINING_OBSERVED_REASON

    plan = trainer.plan_exact_ppo_optimizer_attempts([example])

    assert plan["trusted_rows"] == []
    assert plan["optimizer_attempt_descriptors"] == []
    assert plan["rejection_metrics"]["training_rejection_reason_counts"] == {
        "LABEL_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT": 1,
        "OUTCOME_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT": 1,
    }


def test_exact_receipt_rows_drive_real_clipped_ppo_optimizer_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=17)
    if not model.torch_available:
        pytest.skip("real clipped PPO optimizer proof requires torch")
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.policy_head.weight.zero_()
        model.net.policy_head.bias.zero_()
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
    fingerprint = model_parameter_fingerprint(model)
    rows = [
        _exact_ppo_example(
            index=index,
            model=model,
            policy_fingerprint=fingerprint,
            archive_root=tmp_path,
        )
        for index in (1, 2)
    ]
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    assert all(trainer._has_on_policy_ppo_fields(row) for row in rows)  # noqa: SLF001
    result = trainer.train(
        rows,
        steps=1,
        batch_size=2,
        validation_fraction=0.0,
    )

    assert result.metrics["ppo_objective_used"] is True
    assert result.metrics["ppo_rows_consumed"] == 2
    assert result.metrics["ppo_clipped_surrogate_rows"] == 2
    assert result.metrics["optimizer_steps_this_cycle"] > 0
    assert result.metrics["parameter_hash_before"] == fingerprint
    assert result.metrics["parameter_hash_after"] == model_parameter_fingerprint(
        model
    )
    assert _optimizer_parameter_fingerprints_bound(
        parameter_hash_before=result.metrics["parameter_hash_before"],
        parameter_hash_after=result.metrics["parameter_hash_after"],
        training_parent_policy_fingerprint=fingerprint,
        candidate_policy_fingerprint=model_parameter_fingerprint(model),
    )
    assert result.metrics["parameter_hash_before"] != result.metrics["parameter_hash_after"]
    assert result.metrics["weight_delta_norm"] > 0.0
    assert result.metrics["ppo_behavior_action_indices_used"] == [1]


def test_public_optimizer_attempt_plan_matches_train_partition_and_stable_dedupe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=29)
    if not model.torch_available:
        pytest.skip("exact optimizer-attempt planner proof requires torch")
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
    fingerprint = model_parameter_fingerprint(model)
    rows = [
        _exact_ppo_example(
            index=index,
            model=model,
            policy_fingerprint=fingerprint,
            archive_root=tmp_path,
        )
        for index in (1, 2)
    ]
    supplied = [*rows, deepcopy(rows[0])]
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    plan = trainer.plan_exact_ppo_optimizer_attempts(
        supplied,
        batch_size=3,
        validation_fraction=0.0,
    )

    descriptors = plan["optimizer_attempt_descriptors"]
    assert plan["eligible_examples"] == rows
    assert [row["update_key"] for row in descriptors] == plan[
        "ordered_update_keys"
    ]
    assert plan["ordered_update_keys_complete"] is True
    assert plan["ordered_update_keys_unique"] is True
    assert plan["duplicate_update_keys"] == [descriptors[0]["update_key"]]
    assert all(
        descriptor["parent_policy_fingerprint"] == fingerprint
        for descriptor in descriptors
    )

    result = trainer.train(
        supplied,
        steps=1,
        batch_size=3,
        validation_fraction=0.0,
    )

    assert result.metrics["ppo_consumed_update_keys"] == plan["ordered_update_keys"]
    assert result.metrics["ppo_duplicate_update_key_rows_rejected"] == 1


def test_cpu_fallback_never_relabels_exact_rows_as_ppo_updates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=18)
    if not model.torch_available:
        pytest.skip("fixture needs a Torch forward pass before fallback simulation")
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
    fingerprint = model_parameter_fingerprint(model)
    exact = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
        archive_root=tmp_path,
    )
    assert exact.trust_row is not None
    pure_ppo_trust = deepcopy(exact.trust_row)
    pure_ppo_trust.pop("outcome_targets", None)
    pure_ppo = TrainingExample(
        symbol=exact.symbol,
        timeframe=exact.timeframe,
        tensor=exact.tensor,
        label_action_index=exact.label_action_index,
        label_expected_move_after_cost_bps=(exact.label_expected_move_after_cost_bps),
        payload_keys=("fallback-exact-ppo",),
        row_classification=exact.row_classification,
        trust_row=pure_ppo_trust,
        decision_time=exact.decision_time,
        label_available_at=exact.label_available_at,
    )
    monkeypatch.setattr(
        ppo_trainer_module,
        "model_parameter_fingerprint",
        lambda _model: fingerprint,
    )
    model._torch = None  # noqa: SLF001
    model._net = None  # noqa: SLF001
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    assert trainer._has_on_policy_ppo_fields(pure_ppo)  # noqa: SLF001
    result = trainer.train(
        [pure_ppo],
        steps=1,
        batch_size=1,
        validation_fraction=0.0,
    )

    assert result.status == ("V2_NATIVE_RL_MASA_NO_SUPPORTED_OBJECTIVE_CPU_FALLBACK_NO_UPDATE")
    assert result.training_steps == 0
    assert result.metrics["ppo_objective_used"] is False
    assert result.metrics["ppo_rows_consumed"] == 0
    assert result.metrics["ppo_rows_available_but_optimizer_unavailable"] == 1
    assert result.metrics["ppo_clipped_surrogate_rows"] == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["parameter_hash_before"] == result.metrics["parameter_hash_after"]
    assert result.metrics["weight_delta_norm"] == 0.0


def test_strategy_supply_and_receipt_tamper_are_never_ppo_eligible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=len(_tensor().model_vector), seed=19)
    if not model.torch_available:
        pytest.skip("exact receipt eligibility proof requires torch")
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(math.atanh(12.0 / 120.0))
    fingerprint = model_parameter_fingerprint(model)
    valid = _exact_ppo_example(
        index=1,
        model=model,
        policy_fingerprint=fingerprint,
        archive_root=tmp_path,
    )
    assert valid.trust_row is not None
    strategy_trust = deepcopy(valid.trust_row)
    strategy_trust["strategy_supply_hypothesis"] = True
    strategy = TrainingExample(
        symbol=valid.symbol,
        timeframe=valid.timeframe,
        tensor=valid.tensor,
        label_action_index=valid.label_action_index,
        label_expected_move_after_cost_bps=(valid.label_expected_move_after_cost_bps),
        payload_keys=("strategy-tamper",),
        row_classification=valid.row_classification,
        trust_row=strategy_trust,
        decision_time=valid.decision_time,
        label_available_at=valid.label_available_at,
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
    )

    assert trainer._ppo_ineligibility_reason(strategy) == (  # noqa: SLF001
        "STRATEGY_SUPPLY_ACTION_NOT_SAMPLED_FROM_CUDA_POLICY"
    )

    tampered_trust = deepcopy(valid.trust_row)
    tampered_receipt = deepcopy(tampered_trust["behavior_policy_receipt"])
    tampered_receipt["raw_action_logits"][1] += 0.5
    unsigned = dict(tampered_receipt)
    unsigned.pop("receipt_hash")
    tampered_receipt["receipt_hash"] = canonical_sha256(unsigned)
    tampered_trust["behavior_policy_receipt"] = tampered_receipt
    tampered_trust["behavior_policy_receipt_hash"] = tampered_receipt["receipt_hash"]
    tampered_trust["behavior_policy_receipt_key"] = (
        "v2:trainer:hybrid_cuda:on_policy_receipt:" f"{tampered_receipt['receipt_hash']}"
    )
    finalized = build_finalized_outcome_binding(tampered_trust)
    tampered_trust.update(finalized)
    tampered_trust["ppo_consumption_update_key"] = build_ppo_consumption_update_key(
        behavior_policy_receipt_hash=tampered_receipt["receipt_hash"],
        finalized_outcome_digest=finalized["finalized_outcome_digest"],
        parent_behavior_fingerprint=fingerprint,
    )
    tampered = TrainingExample(
        symbol=valid.symbol,
        timeframe=valid.timeframe,
        tensor=valid.tensor,
        label_action_index=valid.label_action_index,
        label_expected_move_after_cost_bps=(valid.label_expected_move_after_cost_bps),
        payload_keys=("receipt-tamper",),
        row_classification=valid.row_classification,
        trust_row=tampered_trust,
        decision_time=valid.decision_time,
        label_available_at=valid.label_available_at,
    )

    assert trainer._ppo_ineligibility_reason(tampered) == (  # noqa: SLF001
        "BEHAVIOR_POLICY_RECEIPT_INVALID"
    )


def _archived_exact_position(
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], PaperNetPosition]:
    payload = build_prediction_payload(
        example=_example(),
        model_output=_model_output(selected_action="short"),
        checkpoint=_checkpoint(),
        round_trip_cost_bps=2.0,
        min_data_coverage_percent=0.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=0.0,
        served_policy_fingerprint="d" * 64,
        checkpoint_weight_sha256="c" * 64,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        cost_provenance=_cost_provenance(),
        behavior_sample_draw_u53=U53_DENOMINATOR - 1,
        on_policy_sampling_selected=True,
        on_policy_sampling_plan=_plan_hashes(),
        decision_time_utc="2026-07-18T00:01:00Z",
    )
    receipt = payload["behavior_policy_receipt"]
    receipt_hash = receipt["receipt_hash"]
    fill = {
        **payload,
        "fill_time_est": "2026-07-18T00:01:01Z",
        "fill_price_utc": "2026-07-18T00:01:01Z",
        "symbol": "BTCUSDT",
        "side": "long",
        "selected_action": "long",
        "behavior_policy_receipt_key": (f"v2:trainer:hybrid_cuda:on_policy_receipt:{receipt_hash}"),
        "behavior_policy_receipt_write_success": True,
        "on_policy_action_receipt_valid": True,
        "old_log_prob": receipt["selected_action_log_prob"],
        "old_value": receipt["policy_value"],
        "rollout_id": "rollout_exact_1",
        "trajectory_index": 0,
        "ppo_on_policy_entry_fields_present": True,
        "fee_bps": 5.0,
        "fee_bps_source": "unit:paper_fee_schedule",
        "entry_fee_usd": 0.05,
        "entry_fee_source": "UNIT_ENTRY_FILL_FEE_USD",
        "entry_slippage_usd": 0.005,
        "entry_slippage_source": "UNIT_ENTRY_FILL_SPREAD_USD",
    }
    position = position_from_fill(
        fill,
        fill_id="fill_exact_1",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": payload["prediction_id"],
            "decision_time": payload["decision_time"],
        },
        root=tmp_path,
        recorded_at=str(payload["decision_time"]),
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding={
            "paper_fill_id": "fill_exact_1",
            "decision_time": payload["decision_time"],
            "entry_time": fill["fill_price_utc"],
            "entry_fee_schedule_evidence_sha256": receipt["cost_provenance"][
                "source_payload"
            ]["fee_schedule_evidence_sha256"],
        },
        root=tmp_path,
        recorded_at=str(fill["fill_price_utc"]),
    )
    return payload, receipt, position


def test_position_and_closed_outcome_preserve_immutable_receipt_lineage(
    tmp_path: Path,
) -> None:
    payload, receipt, position = _archived_exact_position(tmp_path)
    receipt_hash = receipt["receipt_hash"]
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=101.0,
        exit_time="2026-07-18T00:06:00Z",
        close_reason="unit",
        exit_spread_bps=1.0,
        exit_spread_source="UNIT_CAUSAL_EXIT_ORDERBOOK_SPREAD",
        exit_spread_available_at="2026-07-18T00:06:00Z",
    )
    close_event, outcome, availability_reasons = capture_close_outcome_availability(
        close_event,
        outcome,
        outcome_available_at=str(outcome["outcome_generated_at"]),
    )
    assert availability_reasons == []

    assert position.behavior_policy_receipt == receipt
    assert position.feature_tensor_id == "tensor_exact_behavior_1"
    for row in (
        position.to_payload(generated_utc="2026-07-18T00:02:00Z"),
        close_event,
        outcome,
    ):
        assert row["behavior_policy_receipt"] == receipt
        assert row["behavior_policy_receipt_hash"] == receipt_hash
        assert row["on_policy_sampling_plan_hash"] == payload[
            "on_policy_sampling_plan_hash"
        ]
        assert row["on_policy_sampling_routes_to_live"] is False

    feedback_rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={payload["prediction_id"]: payload},
        behavior_receipt_archive_root=tmp_path,
    )

    assert len(feedback_rows) == 1
    feedback = feedback_rows[0]
    assert feedback["behavior_policy_receipt"] == receipt
    assert feedback["old_log_prob"] == receipt["selected_action_log_prob"]
    assert feedback["old_value"] == receipt["policy_value"]
    assert feedback["ppo_on_policy_entry_fields_present"] is True
    assert feedback["paper_learning_lane"] == "PPO_ON_POLICY_PAPER_EXPLORATION"
    assert feedback["ppo_on_policy_receipt_rejection_reasons"] == []
    assert feedback["finalized_outcome_finality_proven"] is True
    assert len(feedback["finalized_outcome_digest"]) == 64
    assert len(feedback["ppo_consumption_update_key"]) == 64
    assert feedback["ppo_consumption_ledger_eligible"] is True
    assert feedback["on_policy_sampling_routes_to_live"] is False
    assert feedback["on_policy_sampling_counts_as_a_plus_evidence"] is False
    assert feedback["paper_only"] is True
    assert feedback["places_real_order"] is False


def test_partial_close_does_not_consume_outcome_archive_before_final_close(
    tmp_path: Path,
) -> None:
    payload, receipt, position = _archived_exact_position(tmp_path)
    receipt_hash = str(receipt["receipt_hash"])
    positions = {"BTCUSDT": position}

    partial_close, partial_outcome, partial_block = paper_lifecycle._close_position(  # noqa: SLF001
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=0.4,
        exit_price=101.0,
        exit_time="2026-07-18T00:06:00Z",
        close_reason="unit_partial",
        fee_bps=5.0,
        slippage_bps=1.0,
        exit_spread_bps=1.0,
        exit_spread_source="UNIT_CAUSAL_EXIT_ORDERBOOK_SPREAD",
        exit_spread_available_at="2026-07-18T00:06:00Z",
    )
    assert partial_block is None
    assert partial_close is not None and partial_outcome is not None
    assert partial_close["entry_cost_is_final_close"] is False

    partial_feedback = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[partial_close],
        outcome_labels=[partial_outcome],
        predictions_by_id={payload["prediction_id"]: payload},
        behavior_receipt_archive_root=tmp_path,
    )[0]

    assert partial_feedback["ppo_on_policy_entry_fields_present"] is False
    assert partial_feedback["ppo_on_policy_ineligible_reason"] == (
        "BEHAVIOR_POLICY_RECEIPT_INVALID"
    )
    assert partial_feedback["ppo_on_policy_receipt_rejection_reasons"] == [
        "finalized_outcome_partial_close_not_terminal"
    ]
    assert "finalized_outcome_digest" not in partial_feedback
    assert "ppo_consumption_update_key" not in partial_feedback

    partial_status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert partial_status["outcome_finalized_durable"] is False

    final_close, final_outcome, final_block = paper_lifecycle._close_position(  # noqa: SLF001
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=0.6,
        exit_price=102.0,
        exit_time="2026-07-18T00:07:00Z",
        close_reason="unit_final",
        fee_bps=5.0,
        slippage_bps=1.0,
        exit_spread_bps=1.0,
        exit_spread_source="UNIT_CAUSAL_EXIT_ORDERBOOK_SPREAD",
        exit_spread_available_at="2026-07-18T00:07:00Z",
    )
    assert final_block is None
    assert final_close is not None and final_outcome is not None
    assert final_close["entry_cost_is_final_close"] is True

    final_feedback = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[final_close],
        outcome_labels=[final_outcome],
        predictions_by_id={payload["prediction_id"]: payload},
        behavior_receipt_archive_root=tmp_path,
    )[0]

    assert final_feedback["ppo_on_policy_entry_fields_present"] is True
    assert final_feedback["done"] is True
    assert final_feedback["ppo_on_policy_receipt_rejection_reasons"] == []
    assert final_feedback["behavior_policy_receipt_archive_finalized"] is True
    assert final_feedback["ppo_consumption_ledger_eligible"] is True

    final_status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert final_status["outcome_finalized_durable"] is True
    assert final_status["event_types"].count(EVENT_OUTCOME_FINALIZED) == 1
