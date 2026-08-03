from __future__ import annotations

import math
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    append_lifecycle_event,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    U53_DENOMINATOR,
    build_exact_cost_provenance,
    build_finalized_outcome_binding,
    build_positive_edge_behavior_receipt,
    build_ppo_consumption_update_key,
    canonical_sha256,
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.tests.unit.services.native_trainer._authenticated_cohort_fixture import (
    archive_single_member_pre_admission_cohort,
    archive_single_member_terminalized_cohort,
    build_single_member_sampling_plan,
    sampling_plan_key_resolver,
)

CHECKPOINT_ID = "v2_hybrid_ckpt_deadbeef_0123456789abcdef_abcdef012345"
CHECKPOINT_WEIGHT_SHA256 = "c" * 64
CHECKPOINT_EVIDENCE_DIGEST = "e" * 64


def _cost_provenance() -> dict[str, object]:
    orderbook = {
        "schema_version": "v2_orderbook_features_v1",
        "symbol": "BTCUSDT",
        "event_time": "2026-06-19T00:00:00Z",
        "available_at": "2026-06-19T00:00:01Z",
        "generated_at": "2026-06-19T00:00:02Z",
        "spread_bps": 0.5,
        "depth_5_bid_usd": 100.0,
        "depth_5_ask_usd": 120.0,
        "sequence_gap_flag": 0,
    }
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
    return build_exact_cost_provenance(
        source_key="v2:costs:round_trip_bps:BTCUSDT",
        source_payload={
            "symbol": "BTCUSDT",
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
            "orderbook_key": "v2:orderbook:features:binance:BTCUSDT",
            "computed_utc": "2026-06-19T00:00:40Z",
            "available_at": "2026-06-19T00:00:40Z",
            "orderbook_schema_version": "v2_orderbook_features_v1",
            "orderbook_source_payload_sha256": canonical_sha256(orderbook),
            "orderbook_source_payload": orderbook,
            "orderbook_observed_at": "2026-06-19T00:00:00Z",
            "orderbook_available_at": "2026-06-19T00:00:01Z",
            "orderbook_generated_at": "2026-06-19T00:00:02Z",
            "orderbook_source_clock_field": "available_at",
            "orderbook_sequence_gap_flag": False,
            "source_future_clock_invalid": False,
            "adaptive_max_age_seconds": 120.0,
            "adaptive_freshness_sample_count": 3,
            "adaptive_freshness_method": (
                "RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"
            ),
            "adaptive_freshness_proven": True,
            "expires_at": "2026-06-19T00:02:01Z",
            "publication_ttl_seconds": 81,
            "estimator_version": "adaptive_cost_model_v1",
            "notes": [],
            "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
        },
        consumer_observed_at="2026-06-19T00:00:50Z",
    )


def _tensor(index: int, value: float | None = None) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"feat_{index}",
        values=(float(index) if value is None else float(value),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def _example(
    index: int,
    action_index: int,
    *,
    value: float | None = None,
    expected: float | None = None,
    trust_overrides: dict[str, object] | None = None,
) -> TrainingExample:
    expected_bps = (
        float(expected)
        if expected is not None
        else 12.0 if action_index == 1 else (-12.0 if action_index == 2 else 0.0)
    )
    selected_action = ("hold", "long", "short")[action_index]
    directional_outcome = "UP" if expected_bps > 0 else "DOWN" if expected_bps < 0 else "FLAT"
    trade_outcome = "WIN" if action_index in (1, 2) and abs(expected_bps) > 0 else "BREAKEVEN"
    trust_row: dict[str, object] = {
        "accepted_for_training": True,
        "reject_reasons": [],
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "mtf_snapshot_id": f"mtf_{index}",
        "mtf_snapshot_valid": True,
        "replay_snapshot_id": f"replay_{index}",
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "feature_freshness_state": "CURRENT",
        "freshness_state": "CURRENT",
        "latency_ms": 100,
        "candle_open_time": "2026-06-18T23:59:00Z",
        "candle_close_time": "2026-06-19T00:00:00Z",
        "source_event_time": "2026-06-19T00:00:00Z",
        "source_event_time_est": "2026-06-19T00:00:00Z",
        "source_received_time_est": "2026-06-19T00:00:00Z",
        "feature_cutoff": "2026-06-19T00:00:00Z",
        "decision_cutoff": "2026-06-19T00:00:00Z",
        "available_at": "2026-06-19T00:00:00Z",
        "source_available_time": "2026-06-19T00:00:00Z",
        "decision_time": "2026-06-19T00:01:00Z",
        "decision_time_est": "2026-06-19T00:01:00Z",
        "features": {"ret_pct": 0.0},
        "selected_action": selected_action,
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_unit",
        "source_hashes": {"feature_vector_hash": f"tensor_{index}"},
        "outcome_targets": {
            "realized_net_pnl_bps": expected_bps,
            "realized_net_pnl_usd": expected_bps / 10.0,
            "directional_outcome": directional_outcome,
            "trade_outcome": trade_outcome,
            "selected_action": selected_action,
            "action_was_profitable": trade_outcome == "WIN",
            "holding_period": 300,
            "fees": 0.01,
            "slippage": 0.01,
            "funding": 0.0,
            "MFE": max(0.0, abs(expected_bps)),
            "MAE": 0.0,
            "exit_reason": "unit",
        },
        "realized_after_cost_reward": expected_bps / 100.0,
        "value_baseline": 0.0,
        "advantage": expected_bps / 100.0,
        "advantage_source": "realized_after_cost_reward_minus_value_baseline",
        "uses_expected_move_as_realized_reward": False,
    }
    trust_row.update(trust_overrides or {})
    if trust_row.get("old_log_prob") not in (None, ""):
        trust_row.setdefault("behavior_policy_sampling_mode", "CATEGORICAL_SAMPLE")
        trust_row.setdefault(
            "behavior_policy_distribution_contract",
            "RAW_LOGITS_SOFTMAX_V1",
        )
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(index, value=value),
        label_action_index=action_index,
        label_expected_move_after_cost_bps=expected_bps,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row=trust_row,
    )


def _attach_exact_behavior_receipt(
    row: TrainingExample,
    model: V2HybridPolicyModel,
    *,
    expected_move_bps: float,
    archive_root: Path,
) -> dict[str, object]:
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(
            math.atanh(expected_move_bps / 120.0)
        )
    forward = model.forward(row.tensor)
    fingerprint = model_parameter_fingerprint(model)
    trust = row.trust_row
    assert trust is not None
    prediction_id = f"prediction_exact_{row.tensor.tensor_id}"
    cost_provenance = _cost_provenance()
    sampling_plan = build_single_member_sampling_plan(
        symbol=row.symbol,
        timeframe=row.timeframe,
        feature_tensor_id=row.tensor.tensor_id,
        feature_cutoff=str(trust["feature_cutoff"]),
        available_at=str(trust["available_at"]),
        candle_close_time=str(trust["candle_close_time"]),
        decision_time=str(trust["decision_time"]),
        raw_action_logits=forward.action_logits,
        expected_move_bps=forward.expected_move_bps,
        exact_cost_payload_hash=str(cost_provenance["source_payload_sha256"]),
        parent_policy_fingerprint=fingerprint,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_WEIGHT_SHA256,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
    )
    plan_hash = str(sampling_plan["plan_hash"])
    plan_input_hash = str(sampling_plan["input_hash"])
    receipt = build_positive_edge_behavior_receipt(
        prediction_id=prediction_id,
        model_output=forward,
        symbol=row.symbol,
        timeframe=row.timeframe,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_WEIGHT_SHA256,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        served_policy_fingerprint=fingerprint,
        feature_tensor_id=row.tensor.tensor_id,
        feature_vector_hash=row.tensor.tensor_id,
        feature_cutoff=trust["feature_cutoff"],
        available_at=trust["available_at"],
        candle_close_time=trust["candle_close_time"],
        decision_time=trust["decision_time"],
        candle_closed_confirmed=True,
        round_trip_cost_bps=2.0,
        cost_provenance=cost_provenance,
        draw_u53=U53_DENOMINATOR - 1,
        sampling_plan_hash=plan_hash,
        sampling_plan_input_hash=plan_input_hash,
    )
    trust.update(
        {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "prediction_id": prediction_id,
            "checkpoint_id": CHECKPOINT_ID,
            "feature_tensor_id": row.tensor.tensor_id,
            "feature_vector_hash": row.tensor.tensor_id,
            "selected_action": receipt["selected_action"],
            "selected_action_index": receipt["selected_action_index"],
            "behavior_action_index": receipt["selected_action_index"],
            "behavior_action": receipt["selected_action"],
            "behavior_action_mask": list(receipt["behavior_action_mask"]),
            "behavior_action_source": receipt["behavior_action_source"],
            "behavior_policy_sampling_mode": receipt[
                "behavior_policy_sampling_mode"
            ],
            "behavior_policy_distribution_contract": receipt[
                "behavior_policy_distribution_contract"
            ],
            "behavior_policy_fingerprint": fingerprint,
            "behavior_policy_checkpoint_hash": CHECKPOINT_WEIGHT_SHA256,
            "behavior_policy_receipt": receipt,
            "behavior_policy_receipt_hash": receipt["receipt_hash"],
            "behavior_policy_receipt_key": (
                "v2:trainer:hybrid_cuda:on_policy_receipt:"
                f"{receipt['receipt_hash']}"
            ),
            "behavior_policy_receipt_write_success": True,
            "on_policy_action_receipt_valid": True,
            "action_labels": list(receipt["action_labels"]),
            "raw_action_logits": list(receipt["raw_action_logits"]),
            "raw_action_probabilities": list(receipt["raw_action_probabilities"]),
            "action_probabilities": list(receipt["action_probabilities"]),
            "selected_action_probability": receipt[
                "selected_action_probability"
            ],
            "selected_action_log_prob": receipt[
                "selected_action_log_prob"
            ],
            "policy_value": receipt["policy_value"],
            "old_log_prob": receipt["selected_action_log_prob"],
            "old_value": receipt["policy_value"],
            "on_policy_sampling_selected": True,
            "on_policy_sampling_plan_hash": plan_hash,
            "on_policy_sampling_plan_input_hash": plan_input_hash,
            "on_policy_sampling_lane": "ADAPTIVE_BOUNDED_PAPER_EXPLORATION",
            "on_policy_sampling_counts_as_a_plus_evidence": False,
            "on_policy_sampling_routes_to_live": False,
            "ppo_on_policy_entry_fields_present": True,
            "strategy_supply_hypothesis": False,
        }
    )
    reward = float(trust["reward"])
    gross_pnl_usd = reward + 0.02
    entry_price = 100.0
    exit_price = (
        entry_price + gross_pnl_usd
        if trust["selected_action"] == "long"
        else entry_price - gross_pnl_usd
    )
    entry_fee_usd = exit_fee_usd = 0.005
    entry_slippage_usd = exit_slippage_usd = 0.005
    trust.update(
        {
            "close_id": f"close_{row.tensor.tensor_id}",
            "position_id": f"position_{row.tensor.tensor_id}",
            "close_event_time": "2026-06-19T00:06:00Z",
            "exit_time": "2026-06-19T00:06:00Z",
            "outcome_generated_at": "2026-06-19T00:06:01Z",
            "outcome_available_at": "2026-06-19T00:06:02Z",
            "outcome_availability_status": "READY",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "side": trust["selected_action"],
            "closed_quantity": 1.0,
            "gross_realized_pnl_usd": gross_pnl_usd,
            "realized_gross_pnl_usd": gross_pnl_usd,
            "realized_net_pnl_usd": reward,
            "realized_net_pnl_bps": reward * 100.0,
            "closed_entry_notional_usd": entry_price,
            "closed_exit_notional_usd": exit_price,
            "entry_fee_usd": entry_fee_usd,
            "exit_fee_usd": exit_fee_usd,
            "total_fees_usd": 0.01,
            "fees_usd": 0.01,
            "fees": 0.01,
            "entry_slippage_usd": entry_slippage_usd,
            "exit_slippage_usd": exit_slippage_usd,
            "total_slippage_usd": 0.01,
            "slippage_usd": 0.01,
            "slippage": 0.01,
            "total_execution_costs_usd": 0.02,
            "funding_usd": 0.0,
            "funding_pnl_usd": 0.0,
            "funding": 0.0,
            "outcome_cost_unit": "USD",
            "paper_round_trip_cost_accounting_version": "PAPER_ROUND_TRIP_CLOSE_COST_V1",
            "paper_cost_rate_scope": "PER_SIDE_BPS_APPLIED_TO_CORRESPONDING_NOTIONAL",
            "paper_net_pnl_formula": (
                "realized_gross_pnl_usd - entry_fee_usd - exit_fee_usd - "
                "entry_slippage_usd - exit_slippage_usd + funding_pnl_usd"
            ),
            "round_trip_cost_fallback_used": False,
            "round_trip_cost_provenance_status": "COMPLETE_ENTRY_AND_EXIT_COST_PROVENANCE",
            "entry_cost_accounting_version": "PAPER_ENTRY_COST_BASIS_V1",
            "entry_cost_allocation_method": "PRO_RATA_BY_CLOSED_QUANTITY_WITH_FINAL_CLOSE_REMAINDER",
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
            "entry_slippage_bps_per_side": entry_slippage_usd / entry_price * 10_000.0,
            "entry_cost_basis_status": "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS",
            "exit_fee_source": "UNIT_ENTRY_BOUND_EXIT_FEE_RATE",
            "exit_fee_fallback": False,
            "exit_fee_rate_basis": "ENTRY_BOUND_PER_SIDE_FEE_RATE_REUSED_FOR_PAPER_EXIT",
            "exit_fee_bps_per_side": exit_fee_usd / exit_price * 10_000.0,
            "exit_slippage_source": "UNIT_EXIT_SPREAD",
            "exit_slippage_available_at": "2026-06-19T00:06:00Z",
            "exit_slippage_fallback": False,
            "exit_slippage_provenance_status": "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME",
            "exit_slippage_bps_per_side": exit_slippage_usd / exit_price * 10_000.0,
            "realized_after_cost_reward": reward,
        }
    )
    finalized = build_finalized_outcome_binding(trust)
    trust.update(finalized)
    trust["ppo_consumption_update_key"] = build_ppo_consumption_update_key(
        behavior_policy_receipt_hash=str(receipt["receipt_hash"]),
        finalized_outcome_digest=str(finalized["finalized_outcome_digest"]),
        parent_behavior_fingerprint=fingerprint,
    )
    trust["ppo_consumption_ledger_eligible"] = True
    archived, cohort_manifest = archive_single_member_pre_admission_cohort(
        root=archive_root,
        sampling_plan=sampling_plan,
        receipt=receipt,
        parent_policy_fingerprint=fingerprint,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_WEIGHT_SHA256,
    )
    published = append_lifecycle_event(
        receipt_hash=str(receipt["receipt_hash"]),
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": receipt["prediction_id"],
            "symbol": receipt["symbol"],
            "timeframe": receipt["timeframe"],
            "checkpoint_id": receipt["checkpoint_id"],
            "decision_time": trust["decision_time"],
            "archive_content_sha256": archived.archive_content_sha256,
        },
        root=archive_root,
        recorded_at=str(trust["decision_time"]),
    )
    entry = append_lifecycle_event(
        receipt_hash=str(receipt["receipt_hash"]),
        event_type=EVENT_ENTRY_ACCEPTED,
        binding={
            "paper_fill_id": f"fill_{row.tensor.tensor_id}",
            "prediction_id": receipt["prediction_id"],
            "symbol": receipt["symbol"],
            "timeframe": receipt["timeframe"],
            "decision_time": trust["decision_time"],
            "entry_time": trust["decision_time"],
            "entry_fee_schedule_evidence_sha256": receipt["cost_provenance"][
                "source_payload"
            ]["fee_schedule_evidence_sha256"],
        },
        root=archive_root,
        recorded_at=str(trust["decision_time"]),
    )
    finalized_event = append_lifecycle_event(
        receipt_hash=str(receipt["receipt_hash"]),
        event_type=EVENT_OUTCOME_FINALIZED,
        binding={
            "finalized_outcome_id": trust["finalized_outcome_id"],
            "finalized_outcome_digest": trust["finalized_outcome_digest"],
            "ppo_consumption_update_key": trust["ppo_consumption_update_key"],
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
            "behavior_policy_receipt_archive_entry_event_hash": entry.event_hash,
            "behavior_policy_receipt_archive_finalized": True,
            "behavior_policy_receipt_archive_finalization_event_hash": (
                finalized_event.event_hash
            ),
            "behavior_policy_receipt_archive_retention_required_until_trainer_consumption": True,
            "on_policy_sampling_cohort_completeness_proof": cohort_proof,
            "on_policy_sampling_cohort_completeness_verified": True,
            "on_policy_sampling_cohort_receipt_membership_verified": True,
            "on_policy_sampling_cohort_completeness_digest": cohort_proof[
                "cohort_digest"
            ],
        }
    )
    return receipt


def test_action_class_weights_upweight_scarce_long_without_forcing_ratio() -> None:
    rows = [_example(i, 2) for i in range(8)]
    rows.append(_example(100, 1))
    rows.append(_example(101, 0))

    weights = V2HybridPPOTrainer._python_action_class_weights(rows)  # noqa: SLF001
    metrics = V2HybridPPOTrainer._action_balance_metrics(rows)  # noqa: SLF001

    assert weights[1] > weights[2]
    assert weights[0] > 0.0
    assert metrics["target_label_distribution_directional"] == {
        "hold": 1,
        "long": 1,
        "short": 8,
    }
    assert metrics["long_label_present"] is True
    assert metrics["short_label_present"] is True
    assert metrics["hold_label_present"] is True


def test_policy_bias_nudge_upweights_scarce_present_labels_without_reinforcing_majority() -> None:
    rows = [_example(i, 2) for i in range(8)]
    rows.append(_example(100, 1))
    rows.append(_example(101, 0))

    nudge = V2HybridPPOTrainer._python_action_bias_nudge(rows)  # noqa: SLF001

    assert nudge[1] > 0.0
    assert nudge[0] > 0.0
    assert nudge[2] < 0.0
    assert nudge[3:] == [0.0, 0.0, 0.0, 0.0]


def test_policy_bias_nudge_is_neutral_for_single_class_short_batch() -> None:
    rows = [_example(i, 2) for i in range(8)]

    nudge = V2HybridPPOTrainer._python_action_bias_nudge(rows)  # noqa: SLF001

    assert nudge == [0.0 for _ in nudge]


def test_policy_action_supervision_neutralizes_single_direction_short_batch_to_hold() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(8)]

    labels, metrics = V2HybridPPOTrainer._python_policy_action_supervision_labels(rows)  # noqa: SLF001

    assert labels == [0 for _ in rows]
    assert metrics["policy_action_supervision_strategy"] == "neutralize_single_directional_action_labels_to_hold"
    assert metrics["policy_action_single_direction_guard_active"] is True
    assert metrics["policy_action_single_direction_guard_side"] == "short"
    assert metrics["policy_action_labels_neutralized_count"] == len(rows)
    assert metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == len(rows)
    assert metrics["policy_action_supervision_target_distribution_by_action"]["short"] == 0


def test_ppo_behavior_short_is_not_replaced_by_neutralized_supervised_hold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    row = _example(
        1,
        2,
        expected=-12.0,
        trust_overrides={
            "old_log_prob": -0.7,
            "old_value": 0.05,
            "reward": 0.4,
            "done": True,
            "rollout_id": "rollout_short",
            "trajectory_index": 0,
            "behavior_action_index": 2,
            "behavior_action": "short",
        },
    )
    model = V2HybridPolicyModel(input_dim=len(row.tensor.model_vector), seed=7)
    if not model.torch_available:
        pytest.skip("exact PPO gather regression requires torch")
    receipt = _attach_exact_behavior_receipt(
        row,
        model,
        expected_move_bps=-12.0,
        archive_root=tmp_path,
    )
    logits = receipt["raw_action_logits"]
    log_normalizer = math.log(math.exp(logits[0]) + math.exp(logits[2]))
    short_log_prob = logits[2] - log_normalizer
    hold_log_prob = logits[0] - log_normalizer
    assert abs(short_log_prob - hold_log_prob) > 1e-3
    assert receipt["selected_action_log_prob"] == pytest.approx(short_log_prob)
    trainer = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    )

    result = trainer.train(
        [row],
        steps=1,
        batch_size=1,
        validation_fraction=0.0,
    )

    assert result.metrics["ppo_objective_used"] is True
    assert result.metrics["policy_action_single_direction_guard_active"] is True
    assert result.metrics["policy_action_labels_neutralized_count"] == 1
    assert result.metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == 1
    assert result.metrics["ppo_log_prob_action_source"] == "immutable_behavior_action_index"
    assert result.metrics["ppo_behavior_action_indices_used"] == [2]
    assert result.metrics["ppo_log_prob_action_indices_used"] == [2]
    assert result.metrics["ppo_behavior_action_distribution_by_action"]["short"] == 1
    assert result.metrics["ppo_behavior_action_distribution_by_action"]["hold"] == 0
    assert result.metrics["ppo_approx_kl_divergence"] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.parametrize(
    "identity_fields",
    (
        {},
        {"behavior_action_index": 2, "behavior_action": "long"},
    ),
)
def test_missing_or_mismatched_policy_sample_identity_is_excluded_from_all_lanes(
    identity_fields: dict[str, object],
) -> None:
    row = _example(
        1,
        2,
        expected=-12.0,
        trust_overrides={
            "old_log_prob": -0.7,
            "old_value": 0.05,
            "reward": 0.4,
            "done": True,
            "rollout_id": "rollout_unproven",
            "trajectory_index": 0,
            **identity_fields,
        },
    )
    trainer = V2HybridPPOTrainer(
        model=V2HybridPolicyModel(input_dim=len(row.tensor.model_vector), seed=7)
    )

    assert trainer._has_on_policy_ppo_fields(row) is False  # noqa: SLF001
    assert trainer._has_outcome_supervised_targets(row) is False  # noqa: SLF001
    result = trainer.train(
        [row],
        steps=1,
        batch_size=1,
        validation_fraction=0.0,
    )

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert result.metrics["learning_update_lane"] == "blocked"
    assert result.metrics["outcome_supervised_rows"] == 0


def test_deterministic_adjusted_policy_row_is_not_treated_as_on_policy_ppo() -> None:
    row = _example(
        1,
        2,
        expected=-12.0,
        trust_overrides={
            "old_log_prob": -0.7,
            "old_value": 0.05,
            "reward": 0.4,
            "done": True,
            "rollout_id": "rollout_deterministic",
            "trajectory_index": 0,
            "behavior_action_index": 2,
            "behavior_action": "short",
            "behavior_policy_sampling_mode": "DETERMINISTIC_ARGMAX_ALIGNMENT",
            "behavior_policy_distribution_contract": "EXPECTED_MOVE_ALIGNED_POLICY_V1",
            "exit_time": "2026-06-19T00:06:00Z",
        },
    )
    trainer = V2HybridPPOTrainer(
        model=V2HybridPolicyModel(input_dim=len(row.tensor.model_vector), seed=7)
    )

    assert trainer._ppo_ineligibility_reason(row) == (  # noqa: SLF001
        "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED"
    )
    result = trainer.train(
        [row],
        steps=1,
        batch_size=1,
        validation_fraction=0.0,
    )

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert result.metrics["learning_update_lane"] == "blocked"
    assert result.metrics["outcome_supervised_rows"] == 0
    assert result.metrics["ppo_rows_rejected_deterministic_behavior_policy"] == 1
    assert result.metrics["ppo_no_rows_exact_reason"] == (
        "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED"
    )
    assert result.metrics["ppo_rows_consumed"] == 0


def test_training_example_freezes_entry_selected_action_identity() -> None:
    row = _example(
        1,
        2,
        trust_overrides={"selected_action_index": 2},
    )

    assert row.behavior_action_index == 2
    assert row.behavior_action == "short"
    assert row.trust_row is not None
    row.trust_row["selected_action_index"] = 0
    row.trust_row["selected_action"] = "hold"
    assert row.behavior_action_index == 2
    assert row.behavior_action == "short"


def test_policy_action_supervision_preserves_balanced_directional_batch() -> None:
    rows = [_example(1, 2, expected=-12.0), _example(2, 1, expected=12.0)]

    labels, metrics = V2HybridPPOTrainer._python_policy_action_supervision_labels(rows)  # noqa: SLF001

    assert labels == [2, 1]
    assert metrics["policy_action_supervision_strategy"] == "raw_action_labels"
    assert metrics["policy_action_single_direction_guard_active"] is False
    assert metrics["policy_action_labels_neutralized_count"] == 0


def test_expected_move_supervision_neutralizes_single_direction_short_batch() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(8)]

    labels, metrics = V2HybridPPOTrainer._python_expected_move_supervision_labels(rows)  # noqa: SLF001

    assert labels == [0.0 for _ in rows]
    assert metrics["expected_move_supervision_strategy"] == "neutralize_single_directional_expected_move_labels"
    assert metrics["expected_move_single_direction_guard_active"] is True
    assert metrics["expected_move_single_direction_guard_side"] == "short"
    assert metrics["expected_move_labels_neutralized_count"] == len(rows)
    assert metrics["expected_move_raw_target_mean_bps"] == -12.0
    assert metrics["expected_move_training_target_mean_bps"] == 0.0


def test_expected_move_supervision_preserves_balanced_directional_batch() -> None:
    rows = [_example(1, 2, expected=-12.0), _example(2, 1, expected=12.0)]

    labels, metrics = V2HybridPPOTrainer._python_expected_move_supervision_labels(rows)  # noqa: SLF001

    assert labels == [-12.0, 12.0]
    assert metrics["expected_move_supervision_strategy"] == "raw_expected_move_labels"
    assert metrics["expected_move_single_direction_guard_active"] is False
    assert metrics["expected_move_labels_neutralized_count"] == 0


def test_training_rejects_nonfinite_tensors_and_labels_before_optimizer_plan() -> None:
    rows = [
        _example(1, 2, value=math.nan, expected=math.inf),
        _example(2, 2, value=math.inf, expected=999.0),
        _example(3, 0, value=-math.inf, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    trainer = V2HybridPPOTrainer(model=model)
    parameter_hash_before = model_parameter_fingerprint(model)
    plan = trainer.plan_exact_ppo_optimizer_attempts(
        rows,
        batch_size=3,
        validation_fraction=0.0,
    )
    result = trainer.train(
        rows,
        steps=1,
        batch_size=3,
        validation_fraction=0.0,
    )

    assert plan["trusted_rows"] == []
    assert plan["optimizer_attempt_descriptors"] == []
    reasons = plan["rejection_metrics"]["training_rejection_reason_counts"]
    assert reasons["NONFINITE_TENSOR_VALUE"] == 3
    assert reasons["NONFINITE_EXPECTED_MOVE_AFTER_COST_LABEL"] == 1
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_training_rejects_nonfinite_required_outcome_target_before_split() -> None:
    row = _example(1, 1, expected=8.0)
    assert row.trust_row is not None
    outcome_targets = dict(row.trust_row["outcome_targets"])
    outcome_targets["realized_net_pnl_bps"] = math.nan
    row.trust_row["outcome_targets"] = outcome_targets
    model = V2HybridPolicyModel(input_dim=len(row.tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    parameter_hash_before = model_parameter_fingerprint(model)
    trainer = V2HybridPPOTrainer(model=model)
    plan = trainer.plan_exact_ppo_optimizer_attempts(
        [row],
        batch_size=1,
        validation_fraction=0.0,
    )

    assert plan["trusted_rows"] == []
    assert plan["optimizer_attempt_descriptors"] == []
    assert plan["train_rows"] == []
    assert plan["validation_rows"] == []
    assert plan["rejection_metrics"]["training_rejection_reason_counts"] == {
        "NONFINITE_OUTCOME_TARGET_REALIZED_NET_PNL_BPS": 1,
    }
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_torch_training_aborts_and_preserves_nonfinite_precycle_parameters() -> None:
    rows = [
        _example(1, 1, expected=8.0),
        _example(2, 2, expected=-8.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        first_parameter = next(model.net.parameters())
        flat = first_parameter.reshape(-1)
        flat[0] = float("nan")
        if flat.numel() > 1:
            flat[1] = float("inf")
    parameter_hash_before = model_parameter_fingerprint(model)

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    assert result.status == "V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK"
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["weight_delta_norm"] == 0.0
    assert result.metrics["training_cycle_rolled_back"] is True
    assert result.metrics["training_cycle_rollback_verified"] is True
    assert result.metrics["training_cycle_abort_reason"] == (
        "NONFINITE_PARAMETER_BEFORE_OPTIMIZER"
    )
    assert result.metrics["parameter_finite_guard_active"] is True
    assert result.metrics["non_finite_parameter_value_count_detected"] >= 1
    assert result.metrics["non_finite_parameter_value_count_sanitized"] == 0
    assert result.metrics["non_finite_parameter_sanitization_events"] == 0
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_torch_training_rolls_back_nonfinite_gradient_without_optimizer_receipt() -> None:
    rows = [
        _example(1, 1, expected=8.0),
        _example(2, 2, expected=-8.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    assert model.torch is not None and model.net is not None
    parameter = next(model.net.parameters())
    hook = parameter.register_hook(
        lambda gradient: model.torch.full_like(gradient, float("inf"))
    )
    parameter_hash_before = model_parameter_fingerprint(model)
    try:
        result = V2HybridPPOTrainer(model=model).train(
            rows,
            steps=2,
            batch_size=3,
            validation_fraction=0.0,
        )
    finally:
        hook.remove()

    assert result.status == "V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK"
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["weight_delta_norm"] == 0.0
    assert result.metrics["training_cycle_rolled_back"] is True
    assert result.metrics["training_cycle_rollback_verified"] is True
    assert result.metrics["training_cycle_abort_reason"] == (
        "NONFINITE_OPTIMIZER_GRADIENT"
    )
    assert result.metrics["non_finite_gradient_steps"] == 1
    assert result.metrics["non_finite_gradient_value_count"] > 0
    assert result.metrics["sanitized_gradient_steps"] == 0
    assert result.metrics["ppo_consumed_update_keys"] == []
    assert model_parameter_fingerprint(model) == parameter_hash_before


@pytest.mark.parametrize(
    "head_name",
    (
        "logits",
        "value",
        "expected_move",
        "confidence_by_direction",
        "masa",
    ),
)
def test_torch_training_rolls_back_injected_nonfinite_forward_head(
    monkeypatch: pytest.MonkeyPatch,
    head_name: str,
) -> None:
    rows = [
        _example(1, 1, expected=8.0),
        _example(2, 2, expected=-8.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    assert model.torch is not None and model.net is not None
    original_forward = model.net.forward

    def nonfinite_forward(batch):  # noqa: ANN001, ANN202
        outputs = dict(original_forward(batch))
        corrupted = outputs[head_name].clone()
        corrupted.reshape(-1)[0] = float("nan")
        outputs[head_name] = corrupted
        return outputs

    monkeypatch.setattr(model.net, "forward", nonfinite_forward)
    parameter_hash_before = model_parameter_fingerprint(model)

    result = V2HybridPPOTrainer(model=model).train(
        rows,
        steps=2,
        batch_size=3,
        validation_fraction=0.0,
    )

    assert result.status == "V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK"
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["weight_delta_norm"] == 0.0
    assert result.metrics["training_cycle_rolled_back"] is True
    assert result.metrics["training_cycle_rollback_verified"] is True
    assert result.metrics["training_cycle_abort_reason"] == (
        "NONFINITE_MODEL_OUTPUT_BEFORE_OPTIMIZER"
    )
    assert result.metrics["non_finite_model_output_value_count"] == 1
    assert result.metrics["non_finite_model_output_events"] == 1
    assert result.metrics["non_finite_model_output_head_counts"] == {
        head_name: 1
    }
    assert result.metrics["tensor_nan_inf_count"] == 1
    assert result.metrics["ppo_consumed_update_keys"] == []
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_torch_training_rolls_back_injected_nonfinite_ppo_ratio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _example(
        1,
        2,
        expected=-12.0,
        trust_overrides={
            "old_log_prob": -0.7,
            "old_value": 0.05,
            "reward": 0.4,
            "done": True,
            "rollout_id": "rollout_nonfinite_ratio",
            "trajectory_index": 0,
            "behavior_action_index": 2,
            "behavior_action": "short",
        },
    )
    model = V2HybridPolicyModel(input_dim=len(row.tensor.model_vector), seed=7)
    if not model.torch_available:
        pytest.skip("torch unavailable")
    assert model.torch is not None and model.net is not None
    _attach_exact_behavior_receipt(
        row,
        model,
        expected_move_bps=-12.0,
        archive_root=tmp_path,
    )
    original_exp = model.torch.exp

    def nonfinite_ratio_exp(value, *args, **kwargs):  # noqa: ANN001, ANN202
        result = original_exp(value, *args, **kwargs)
        if value.ndim == 1 and value.numel() == 1:
            return model.torch.full_like(result, float("nan"))
        return result

    monkeypatch.setattr(model.torch, "exp", nonfinite_ratio_exp)
    parameter_hash_before = model_parameter_fingerprint(model)

    result = V2HybridPPOTrainer(
        model=model,
        behavior_receipt_archive_root=tmp_path,
        sampling_plan_key_resolver=sampling_plan_key_resolver,
    ).train(
        [row],
        steps=1,
        batch_size=1,
        validation_fraction=0.0,
    )

    assert result.status == "V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK"
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["training_cycle_abort_reason"] == "NONFINITE_PPO_RATIO"
    assert result.metrics["non_finite_optimizer_ratio_value_count"] == 1
    assert result.metrics["non_finite_optimizer_ratio_events"] == 1
    assert result.metrics["ppo_consumed_update_keys"] == []
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_torch_training_rolls_back_prior_step_when_later_forward_is_nonfinite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _example(1, 1, expected=8.0),
        _example(2, 2, expected=-8.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    assert model.net is not None
    original_forward = model.net.forward
    forward_calls = 0

    def later_nonfinite_forward(batch):  # noqa: ANN001, ANN202
        nonlocal forward_calls
        forward_calls += 1
        outputs = dict(original_forward(batch))
        if forward_calls == 3:
            corrupted = outputs["value"].clone()
            corrupted.reshape(-1)[0] = float("inf")
            outputs["value"] = corrupted
        return outputs

    monkeypatch.setattr(model.net, "forward", later_nonfinite_forward)
    parameter_hash_before = model_parameter_fingerprint(model)

    result = V2HybridPPOTrainer(model=model).train(
        rows,
        steps=2,
        batch_size=3,
        validation_fraction=0.0,
    )

    assert forward_calls == 3
    assert result.status == "V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK"
    assert result.training_steps == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 0
    assert result.metrics["finite_gradient_clip_applied_steps"] == 1
    assert result.metrics["training_cycle_abort_reason"] == (
        "NONFINITE_MODEL_OUTPUT_DURING_OPTIMIZER"
    )
    assert result.metrics["training_cycle_rolled_back"] is True
    assert result.metrics["training_cycle_rollback_verified"] is True
    assert result.metrics["weight_delta_norm"] == 0.0
    assert result.metrics["non_finite_model_output_value_count"] == 1
    assert result.metrics["non_finite_model_output_events"] == 1
    assert model_parameter_fingerprint(model) == parameter_hash_before


def test_torch_training_neutralizes_single_direction_expected_move_targets() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(4)]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=4, validation_fraction=0.0)

    assert result.metrics["policy_action_supervision_strategy"] == "neutralize_single_directional_action_labels_to_hold"
    assert result.metrics["policy_action_single_direction_guard_active"] is True
    assert result.metrics["policy_action_single_direction_guard_side"] == "short"
    assert result.metrics["policy_action_labels_neutralized_count"] == result.train_rows
    assert result.metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == result.train_rows
    assert result.metrics["policy_action_supervision_target_distribution_by_action"]["short"] == 0
    assert result.metrics["expected_move_supervision_strategy"] == "neutralize_single_directional_expected_move_labels"
    assert result.metrics["expected_move_single_direction_guard_active"] is True
    assert result.metrics["expected_move_single_direction_guard_side"] == "short"
    assert result.metrics["expected_move_labels_neutralized_count"] == result.train_rows
    assert result.metrics["expected_move_raw_target_mean_bps"] == -12.0
    assert result.metrics["expected_move_training_target_mean_bps"] == 0.0
    assert result.metrics["optimizer_steps_this_cycle"] == 1
    assert result.metrics["finite_gradient_clip_applied_steps"] == 1
    assert result.metrics["sanitized_gradient_steps"] == 0
    assert result.metrics["anomaly_free_optimizer_cycle"] is True
    assert result.metrics["expected_move_head_saturation_recovery_applied"] is False
    assert result.metrics["expected_move_head_saturation_recovery_reason"] == "mixed_long_short_target_evidence_missing"


def test_torch_training_recovers_runaway_expected_move_bias_with_mixed_directional_targets() -> None:
    rows = [
        _example(1, 1, expected=12.0),
        _example(2, 2, expected=-12.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(-57.0)

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    metrics = result.metrics
    assert metrics["expected_move_head_saturation_recovery_applied"] is True
    assert metrics["expected_move_head_saturation_recovery_reason"] == (
        "mixed_directional_targets_recentered_runaway_expected_move_bias"
    )
    assert metrics["expected_move_head_target_long_count"] == 1
    assert metrics["expected_move_head_target_short_count"] == 1
    assert metrics["expected_move_head_bias_before_recovery"] < -EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT
    assert abs(metrics["expected_move_head_bias_after_recovery"]) <= EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT
    assert metrics["expected_move_head_batch_output_mean_bps_before_recovery"] <= -118.0
    assert abs(metrics["expected_move_head_batch_output_mean_bps_after_recovery"]) < 1.0
    assert abs(float(model.net.expected_move_head.bias.detach().cpu().item())) <= EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT


def test_torch_training_recenters_expected_move_head_when_output_mismatches_mixed_targets() -> None:
    rows = [
        _example(1, 1, expected=12.0),
        _example(2, 2, expected=-12.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(1.5)

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    metrics = result.metrics
    assert metrics["expected_move_head_saturation_recovery_applied"] is True
    assert "target_mismatch" in metrics["expected_move_head_saturation_recovery_causes"]
    assert abs(metrics["expected_move_head_batch_output_mean_bps_after_recovery"]) < 1.0
    assert abs(metrics["expected_move_head_batch_target_delta_bps_after_recovery"]) < 1.0


def test_checkpoint_load_rejects_non_finite_torch_tensors(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    model = V2HybridPolicyModel(input_dim=1)
    if not model.torch_available:
        pytest.skip("torch unavailable")
    payload = {
        "__format_version": np.array(["v2_hybrid_policy_npz_v2"]),
        "__input_dim": np.array([model.input_dim], dtype=np.int64),
        "__seed": np.array([model.seed], dtype=np.int64),
        "__torch_available": np.array([1], dtype=np.int64),
        "__confidence_head_schema_version": np.array(
            [CONFIDENCE_HEAD_SCHEMA_VERSION]
        ),
        "__confidence_head_actions_json": np.array(['["long","short"]']),
    }
    first_tensor = True
    for name, tensor in model.net.state_dict().items():
        array = tensor.detach().cpu().numpy()
        if first_tensor:
            array = array.copy()
            array.reshape(-1)[0] = np.nan
            first_tensor = False
        payload[f"torch::{name}"] = array
    path = tmp_path / "bad.weights.npz"
    np.savez_compressed(path, **payload)

    with pytest.raises(ValueError, match="non_finite_tensor_in_checkpoint"):
        model.load_weight_blob(path)
