from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from v2.backend.app.cli.v2_trainer_fit_confidence_calibration import run_fit
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import ppo_trainer as ppo_module
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
    fit_temperature,
    profitability_target_from_trust_row,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    U53_DENOMINATOR,
    build_exact_cost_provenance,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    build_prediction_payload,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


def _tensor(index: int) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_confidence_{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"snapshot_confidence_{index}",
        values=(float(index) / 100.0,),
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


def _identifiable_calibration_state() -> dict[str, object]:
    return fit_temperature(
        [0.8, 0.8, 0.8, 0.2, 0.2, 0.2],
        [1, 1, 0, 1, 0, 0],
        row_ids=[f"fit-{index}" for index in range(6)],
        action_labels=["long", "short", "long", "short", "long", "short"],
    )


def _rebind_manifest_to_current_weight_sha256(
    manifest: CheckpointManifest,
) -> None:
    """Let a test reach structural checks after proving byte-identity fencing."""
    weight_path = Path(str(manifest.weight_file_path))
    manifest_path = Path(str(manifest.path))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["weight_file_sha256"] = hashlib.sha256(weight_path.read_bytes()).hexdigest()
    payload["weight_file_size_bytes"] = weight_path.stat().st_size
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _exact_cost_provenance() -> dict[str, object]:
    orderbook_payload: dict[str, object] = {
        "schema_version": "v2_orderbook_features_v1",
        "symbol": "BTCUSDT",
        "event_time": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:01Z",
        "generated_at": "2026-07-18T00:00:02Z",
        "spread_bps": 0.5,
        "depth_5_bid_usd": 1_000.0,
        "depth_5_ask_usd": 1_200.0,
        "sequence_gap_flag": 0,
    }
    fee_evidence: dict[str, object] = {
        "schema_version": "paper_cost_fee_schedule_evidence_v1",
        "configuration_kind": "CONFIGURED_TAKER_FEE_BPS_PER_SIDE",
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit_test_exchange_taker_schedule",
    }
    notional_evidence: dict[str, object] = {
        "schema_version": "paper_cost_notional_configuration_evidence_v1",
        "configuration_kind": "COST_MODEL_REFERENCE_NOTIONAL_USD",
        "notional_usd": 1_000.0,
        "notional_source": "UNIT_EXPLICIT_COST_MODEL_NOTIONAL_USD",
    }
    source_payload: dict[str, object] = {
        "symbol": "BTCUSDT",
        "estimator_version": "adaptive_cost_model_v1",
        "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
        "freshness_status": "FRESH_ORDERBOOK",
        "conservative_floor_applied": False,
        "spread_source": "orderbook_features_binance_live_spread_bps",
        "impact_source": "notional_over_top5_depth_times_half_spread",
        "orderbook_key": "v2:orderbook:features:binance:BTCUSDT",
        "computed_utc": "2026-07-18T00:00:40Z",
        "available_at": "2026-07-18T00:00:40Z",
        "spread_age_seconds": 39.0,
        "orderbook_schema_version": "v2_orderbook_features_v1",
        "orderbook_source_payload_sha256": hashlib.sha256(
            json.dumps(
                orderbook_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "orderbook_source_payload": orderbook_payload,
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
        "taker_fee_bps_per_side": 0.5,
        "fee_source": "unit_test_exchange_taker_schedule",
        "fee_schedule_evidence": fee_evidence,
        "fee_schedule_evidence_sha256": hashlib.sha256(
            json.dumps(
                fee_evidence,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "spread_bps": 0.5,
        "impact_per_side_bps": 0.25,
        "depth_used_usd": 1_000.0,
        "notional_usd_assumed": 1_000.0,
        "notional_configuration_evidence": notional_evidence,
        "notional_configuration_evidence_sha256": hashlib.sha256(
            json.dumps(
                notional_evidence,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "round_trip_cost_bps": 2.0,
    }
    return build_exact_cost_provenance(
        source_key="v2:costs:round_trip_bps:BTCUSDT",
        source_payload=source_payload,
        consumer_observed_at="2026-07-18T00:00:50Z",
    )


def _trust(
    index: int,
    *,
    profitable: bool,
    action: str = "long",
    decision_time: str = "2026-07-18T00:01:00Z",
    exit_time: str = "2026-07-18T00:06:00Z",
) -> dict[str, object]:
    pnl_bps = 12.0 if profitable else -8.0
    pnl_notional_usd = 1_000.0
    net_pnl_usd = pnl_bps / 10_000.0 * pnl_notional_usd
    fees_usd = 0.04
    slippage_usd = 0.02
    funding_pnl_usd = 0.0
    gross_pnl_usd = net_pnl_usd + fees_usd + slippage_usd - funding_pnl_usd
    entry_price = 100.0
    closed_quantity = pnl_notional_usd / entry_price
    exit_price = (
        entry_price + gross_pnl_usd / closed_quantity
        if action == "long"
        else entry_price - gross_pnl_usd / closed_quantity
    )
    return {
        "accepted_for_training": True,
        "valid_for_training": True,
        "trainer_consumable": True,
        "candle_closed_confirmed": True,
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "masa_feature_cutoff": "2026-07-18T00:00:00Z",
        "ppo_feature_cutoff": "2026-07-18T00:00:00Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "decision_time": decision_time,
        "exit_time": exit_time,
        "label_available_at": exit_time,
        "feature_snapshot_id": f"snapshot_confidence_{index}",
        "feature_vector_hash": f"tensor_confidence_{index}",
        "trainer_feedback_id": f"feedback_confidence_{index}",
        "selected_action": action,
        "side": action,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "closed_quantity": closed_quantity,
        "realized_net_pnl_bps": pnl_bps,
        "realized_net_pnl_usd": net_pnl_usd,
        "realized_gross_pnl_usd": gross_pnl_usd,
        "realized_pnl_usd": gross_pnl_usd,
        "closed_entry_notional_usd": pnl_notional_usd,
        "closed_exit_notional_usd": exit_price * closed_quantity,
        "gross_notional_usd": pnl_notional_usd,
        "entry_fee_usd": fees_usd / 2.0,
        "exit_fee_usd": fees_usd / 2.0,
        "total_fees_usd": fees_usd,
        "fees": fees_usd,
        "fees_usd": fees_usd,
        "entry_slippage_usd": slippage_usd / 2.0,
        "exit_slippage_usd": slippage_usd / 2.0,
        "total_slippage_usd": slippage_usd,
        "total_execution_costs_usd": fees_usd + slippage_usd,
        "slippage": slippage_usd,
        "slippage_usd": slippage_usd,
        "funding": funding_pnl_usd,
        "funding_pnl_usd": funding_pnl_usd,
        "funding_usd": funding_pnl_usd,
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
        "entry_cost_basis_status": (
            "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
        ),
        "entry_fee_source": "UNIT_ENTRY_FEE_USD",
        "entry_fee_fallback": False,
        "entry_fee_bps_per_side": fees_usd / 2.0 / pnl_notional_usd * 10_000.0,
        "entry_slippage_source": "UNIT_ENTRY_SLIPPAGE_USD",
        "entry_slippage_fallback": False,
        "entry_slippage_bps_per_side": (
            slippage_usd / 2.0 / pnl_notional_usd * 10_000.0
        ),
        "exit_fee_source": "UNIT_ENTRY_BOUND_EXIT_FEE_RATE",
        "exit_fee_fallback": False,
        "exit_fee_rate_basis": (
            "ENTRY_BOUND_PER_SIDE_FEE_RATE_REUSED_FOR_PAPER_EXIT"
        ),
        "exit_fee_bps_per_side": (
            fees_usd / 2.0 / (exit_price * closed_quantity) * 10_000.0
        ),
        "exit_slippage_source": "UNIT_CAUSAL_EXIT_SPREAD",
        "exit_slippage_available_at": exit_time,
        "exit_slippage_fallback": False,
        "exit_slippage_provenance_status": (
            "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME"
        ),
        "exit_slippage_bps_per_side": (
            slippage_usd / 2.0 / (exit_price * closed_quantity) * 10_000.0
        ),
        "realized_after_cost_reward": pnl_bps / 100.0,
        "uses_expected_move_as_realized_reward": False,
        "outcome_targets": {
            "realized_net_pnl_bps": pnl_bps,
            "realized_net_pnl_usd": net_pnl_usd,
            "realized_gross_pnl_usd": gross_pnl_usd,
            "closed_entry_notional_usd": pnl_notional_usd,
            "directional_outcome": "UP" if action == "long" else "DOWN",
            "trade_outcome": "WIN" if profitable else "LOSS",
            "selected_action": action,
            "action_was_profitable": profitable,
            "holding_period": 300,
            "fees": fees_usd,
            "fees_usd": fees_usd,
            "slippage": slippage_usd,
            "slippage_usd": slippage_usd,
            "funding": funding_pnl_usd,
            "funding_pnl_usd": funding_pnl_usd,
        },
    }


def _example(index: int, *, profitable: bool, action: str = "long") -> TrainingExample:
    trust = _trust(index, profitable=profitable, action=action)
    expected = 12.0 if action == "long" else -12.0
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(index),
        label_action_index=1 if action == "long" else 2 if action == "short" else 0,
        label_expected_move_after_cost_bps=expected,
        payload_keys=(f"row:{index}",),
        row_classification="TRAINABLE",
        trust_row=trust,
        decision_time=str(trust["decision_time"]),
        label_available_at=str(trust["label_available_at"]),
    )


def test_profitability_target_requires_pit_clocks_and_closed_candle_finality() -> None:
    valid = _trust(1, profitable=True)
    result = profitability_target_from_trust_row(valid)
    assert result["eligible"] is True
    assert result["target"] == 1
    assert result["label_semantics"] == CONFIDENCE_LABEL_SEMANTICS

    future_available = dict(valid)
    future_available["available_at"] = "2026-07-18T00:02:00Z"
    assert profitability_target_from_trust_row(future_available)["reason"] == (
        "CONFIDENCE_TARGET_AVAILABLE_AT_AFTER_DECISION"
    )

    simultaneous_available = dict(valid)
    simultaneous_available["available_at"] = str(valid["decision_time"])
    assert profitability_target_from_trust_row(simultaneous_available)["reason"] == (
        "CONFIDENCE_TARGET_AVAILABLE_AT_NOT_STRICTLY_BEFORE_DECISION"
    )

    unfinished = dict(valid)
    unfinished["candle_closed_confirmed"] = False
    assert profitability_target_from_trust_row(unfinished)["reason"] == (
        "CONFIDENCE_TARGET_CANDLE_FINALITY_UNPROVEN"
    )

    noncausal = dict(valid)
    noncausal["exit_time"] = str(valid["decision_time"])
    noncausal["label_available_at"] = str(valid["decision_time"])
    assert profitability_target_from_trust_row(noncausal)["reason"] == (
        "CONFIDENCE_TARGET_EXIT_NOT_STRICTLY_AFTER_DECISION"
    )

    exit_before_decision = dict(valid)
    exit_before_decision["exit_time"] = "2026-07-18T00:00:45Z"
    exit_before_decision["label_available_at"] = "2026-07-18T00:06:00Z"
    assert profitability_target_from_trust_row(exit_before_decision)["reason"] == (
        "CONFIDENCE_TARGET_EXIT_NOT_STRICTLY_AFTER_DECISION"
    )

    fallback_close = dict(valid)
    fallback_close["round_trip_cost_fallback_used"] = True
    assert profitability_target_from_trust_row(fallback_close)["reason"] == (
        "CONFIDENCE_TARGET_ROUND_TRIP_COST_FALLBACK_USED_NOT_FALSE"
    )


def test_hold_is_never_relabeled_as_profitable_confidence_target() -> None:
    hold = _trust(2, profitable=True, action="hold")
    result = profitability_target_from_trust_row(hold)
    assert result["eligible"] is False
    assert result["reason"] == "CONFIDENCE_TARGET_HOLD_OR_INVALID_ACTION_EXCLUDED"


def test_opposing_long_short_outcomes_bind_to_distinct_directional_heads() -> None:
    long_win = profitability_target_from_trust_row(
        _trust(20, profitable=True, action="long")
    )
    short_loss = profitability_target_from_trust_row(
        _trust(21, profitable=False, action="short")
    )
    assert long_win["target"] == 1
    assert long_win["confidence_head_action_index"] == 0
    assert short_loss["target"] == 0
    assert short_loss["confidence_head_action_index"] == 1

    batch = V2HybridPPOTrainer._confidence_target_batch(  # noqa: SLF001
        [
            _example(20, profitable=True, action="long"),
            _example(21, profitable=False, action="short"),
        ]
    )
    targets, mask, head_action_indices, row_ids, metrics = batch
    assert targets == [1.0, 0.0]
    assert mask == [True, True]
    assert head_action_indices == [0, 1]
    assert row_ids == ["feedback_confidence_20", "feedback_confidence_21"]
    assert metrics["confidence_target_action_conditioned"] is True


def test_inference_selects_matching_directional_confidence_and_excludes_hold() -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(22).model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    torch = model.torch
    net = model.net
    assert torch is not None and net is not None
    fitted = _identifiable_calibration_state()
    model.set_confidence_calibration_state(fitted)
    with torch.no_grad():
        net.policy_head.weight.zero_()
        net.expected_move_head.weight.zero_()
        net.confidence_head.weight.zero_()
        net.confidence_head.bias[0] = math.log(0.85 / 0.15)
        net.confidence_head.bias[1] = math.log(0.15 / 0.85)

        net.policy_head.bias.fill_(-10.0)
        net.policy_head.bias[1] = 10.0
        net.expected_move_head.bias.fill_(math.atanh(20.0 / 120.0))
    long_output = model.forward(_tensor(22))
    assert long_output.selected_action == "long"
    assert long_output.confidence_raw == pytest.approx(0.85, abs=1e-5)
    assert long_output.calibration["confidence_head_action_index"] == 0

    with torch.no_grad():
        net.policy_head.bias.fill_(-10.0)
        net.policy_head.bias[2] = 10.0
        net.expected_move_head.bias.fill_(math.atanh(-20.0 / 120.0))
    short_output = model.forward(_tensor(22))
    assert short_output.selected_action == "short"
    assert short_output.confidence_raw == pytest.approx(0.15, abs=1e-5)
    assert short_output.calibration["confidence_head_action_index"] == 1

    with torch.no_grad():
        net.policy_head.bias.fill_(-10.0)
        net.policy_head.bias[0] = 10.0
        net.expected_move_head.bias.zero_()
    hold_output = model.forward(_tensor(22))
    assert hold_output.selected_action == "hold"
    assert hold_output.confidence_raw == 0.0
    assert hold_output.confidence_calibrated == 0.0
    assert hold_output.calibration["probability_semantics_valid"] is False
    assert hold_output.calibration["calibration_reason"] == (
        "SELECTED_ACTION_NOT_DIRECTIONAL_CONFIDENCE_UNDEFINED"
    )


def test_missing_explicit_cost_component_fails_closed() -> None:
    row = _trust(3, profitable=True)
    targets = dict(row["outcome_targets"])
    targets.pop("slippage")
    targets.pop("slippage_usd")
    row["outcome_targets"] = targets
    result = profitability_target_from_trust_row(row)
    assert result["eligible"] is False
    assert result["reason"] == "CONFIDENCE_TARGET_EXPLICIT_SLIPPAGE_USD_MISSING"

    synthesized_net = _trust(30, profitable=False)
    synthesized_net.pop("realized_net_pnl_bps")
    result = profitability_target_from_trust_row(synthesized_net)
    assert result["eligible"] is False
    assert result["reason"] == "CONFIDENCE_TARGET_REALIZED_NET_PNL_BPS_MISSING"

    conflicting_cost = _trust(31, profitable=True)
    conflicting_cost["fees"] = 0.05
    result = profitability_target_from_trust_row(conflicting_cost)
    assert result["eligible"] is False
    assert result["reason"] == "CONFIDENCE_TARGET_EXPLICIT_FEES_USD_CONFLICT"


def test_profitability_target_recomputes_net_usd_and_bps_from_economics() -> None:
    row = _trust(32, profitable=True)

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is True
    assert result["target"] == 1
    assert result["realized_gross_pnl_usd"] == pytest.approx(1.26)
    assert result["realized_net_pnl_usd"] == pytest.approx(1.2)
    assert result["realized_net_pnl_bps"] == pytest.approx(12.0)
    assert result["realized_pnl_notional_usd"] == pytest.approx(1_000.0)
    assert result["explicit_cost_units"] == "USD"
    assert result["economics_formula"] == (
        "gross_pnl_usd-fees_usd-slippage_usd+funding_pnl_usd"
    )


def test_ambiguous_cost_names_without_usd_provenance_fail_closed() -> None:
    row = _trust(41, profitable=True)
    row.pop("fees_usd")
    targets = dict(row["outcome_targets"])
    targets.pop("fees_usd")
    row["outcome_targets"] = targets

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is False
    assert result["reason"] == "CONFIDENCE_TARGET_EXPLICIT_FEES_USD_MISSING"


def test_data_loader_preserves_exact_economics_in_derived_outcome_targets() -> None:
    row = _trust(42, profitable=True)
    targets = V2HybridTrainerDataLoader._outcome_targets_from_row(row)  # noqa: SLF001

    assert targets["realized_gross_pnl_usd"] == pytest.approx(1.26)
    assert targets["closed_entry_notional_usd"] == pytest.approx(1_000.0)
    assert targets["fees_usd"] == pytest.approx(0.04)
    assert targets["slippage_usd"] == pytest.approx(0.02)
    assert targets["funding_pnl_usd"] == pytest.approx(0.0)

    row["outcome_targets"] = targets
    result = profitability_target_from_trust_row(row)
    assert result["eligible"] is True
    assert result["target"] == 1


def test_forged_positive_net_cannot_override_negative_gross_and_costs() -> None:
    row = _trust(33, profitable=True)
    row.update(
        {
            "realized_gross_pnl_usd": -1.0,
            "realized_pnl_usd": -1.0,
            "realized_net_pnl_usd": 10.0,
            "realized_net_pnl_bps": 100.0,
            "fees": 100.0,
            "fees_usd": 100.0,
            "slippage": 50.0,
            "slippage_usd": 50.0,
            "funding": 0.0,
            "funding_pnl_usd": 0.0,
            "action_was_profitable": True,
            "trade_outcome": "WIN",
        }
    )
    row["outcome_targets"] = {
        **dict(row["outcome_targets"]),
        "realized_gross_pnl_usd": -1.0,
        "realized_net_pnl_usd": 10.0,
        "realized_net_pnl_bps": 100.0,
        "fees": 100.0,
        "fees_usd": 100.0,
        "slippage": 50.0,
        "slippage_usd": 50.0,
        "funding": 0.0,
        "funding_pnl_usd": 0.0,
        "action_was_profitable": True,
        "trade_outcome": "WIN",
    }

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is False
    assert result["reason"] == (
        "CONFIDENCE_TARGET_GROSS_PNL_PRICE_RECOMPUTATION_CONFLICT"
    )


@pytest.mark.parametrize("notional", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_missing_nonpositive_or_nonfinite_notional_fails_closed(
    notional: float | None,
) -> None:
    row = _trust(34, profitable=True)
    targets = dict(row["outcome_targets"])
    if notional is None:
        row.pop("gross_notional_usd")
        row.pop("closed_entry_notional_usd")
        targets.pop("closed_entry_notional_usd")
    else:
        row["gross_notional_usd"] = notional
        row["closed_entry_notional_usd"] = notional
        targets["closed_entry_notional_usd"] = notional
    row["outcome_targets"] = targets

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is False
    if notional is None:
        assert result["reason"] == (
            "CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_MISSING"
        )
    elif math.isfinite(notional):
        assert result["reason"] == (
            "CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_NOT_POSITIVE"
        )
    else:
        assert result["reason"] == (
            "CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_INVALID"
        )


def test_partial_close_uses_close_notional_not_full_position_notional() -> None:
    row = _trust(43, profitable=True)
    row["gross_notional_usd"] = 5_000.0

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is True
    assert result["realized_pnl_notional_usd"] == pytest.approx(1_000.0)
    assert result["realized_net_pnl_bps"] == pytest.approx(12.0)

    conflicting_target = dict(row)
    conflicting_target["outcome_targets"] = {
        **dict(row["outcome_targets"]),
        "closed_entry_notional_usd": 900.0,
    }
    rejected = profitability_target_from_trust_row(conflicting_target)
    assert rejected["eligible"] is False
    assert rejected["reason"] == (
        "CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_CONFLICT"
    )


def test_missing_nonfinite_or_contradictory_gross_pnl_fails_closed() -> None:
    missing = _trust(35, profitable=True)
    missing.pop("realized_gross_pnl_usd")
    missing.pop("realized_pnl_usd")
    missing_targets = dict(missing["outcome_targets"])
    missing_targets.pop("realized_gross_pnl_usd")
    missing["outcome_targets"] = missing_targets
    assert profitability_target_from_trust_row(missing)["reason"] == (
        "CONFIDENCE_TARGET_REALIZED_GROSS_PNL_USD_MISSING"
    )

    nonfinite = _trust(36, profitable=True)
    nonfinite["realized_gross_pnl_usd"] = float("nan")
    assert profitability_target_from_trust_row(nonfinite)["reason"] == (
        "CONFIDENCE_TARGET_REALIZED_GROSS_PNL_USD_INVALID"
    )

    contradictory = _trust(37, profitable=True)
    contradictory["realized_gross_pnl_usd"] = 2.0
    assert profitability_target_from_trust_row(contradictory)["reason"] == (
        "CONFIDENCE_TARGET_REALIZED_GROSS_PNL_USD_CONFLICT"
    )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("fees", float("nan")),
        ("slippage", float("inf")),
        ("funding", float("-inf")),
    ],
)
def test_nonfinite_cost_provenance_fails_closed(field: str, invalid: float) -> None:
    row = _trust(38, profitable=True)
    usd_field = {
        "fees": "fees_usd",
        "slippage": "slippage_usd",
        "funding": "funding_pnl_usd",
    }[field]
    row[field] = invalid
    row[usd_field] = invalid
    row["outcome_targets"] = {
        **dict(row["outcome_targets"]),
        field: invalid,
        usd_field: invalid,
    }

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is False
    assert result["reason"] == (
        f"CONFIDENCE_TARGET_EXPLICIT_{field.upper()}_USD_INVALID"
    )


def test_claimed_net_bps_must_equal_recomputed_net_bps() -> None:
    row = _trust(39, profitable=True)
    row["realized_net_pnl_bps"] = 13.0
    row["outcome_targets"] = {
        **dict(row["outcome_targets"]),
        "realized_net_pnl_bps": 13.0,
    }

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is False
    assert result["reason"] == (
        "CONFIDENCE_TARGET_REALIZED_NET_PNL_BPS_RECOMPUTATION_CONFLICT"
    )


def test_signed_funding_pnl_is_applied_to_recomputed_net() -> None:
    row = _trust(40, profitable=True)
    funding_credit_usd = 0.5
    expected_net_usd = 1.26 - 0.04 - 0.02 + funding_credit_usd
    expected_net_bps = expected_net_usd / 1_000.0 * 10_000.0
    row.update(
        {
            "funding": funding_credit_usd,
            "funding_pnl_usd": funding_credit_usd,
            "funding_usd": funding_credit_usd,
            "realized_net_pnl_usd": expected_net_usd,
            "realized_net_pnl_bps": expected_net_bps,
        }
    )
    row["outcome_targets"] = {
        **dict(row["outcome_targets"]),
            "funding": funding_credit_usd,
            "funding_pnl_usd": funding_credit_usd,
            "funding_usd": funding_credit_usd,
        "realized_net_pnl_usd": expected_net_usd,
        "realized_net_pnl_bps": expected_net_bps,
    }

    result = profitability_target_from_trust_row(row)

    assert result["eligible"] is True
    assert result["target"] == 1
    assert result["realized_net_pnl_usd"] == pytest.approx(expected_net_usd)
    assert result["realized_net_pnl_bps"] == pytest.approx(expected_net_bps)


def test_model_confidence_does_not_take_max_with_policy_probability() -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(4).model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    torch = model.torch
    net = model.net
    assert torch is not None and net is not None
    with torch.no_grad():
        net.policy_head.weight.zero_()
        net.policy_head.bias.fill_(-10.0)
        net.policy_head.bias[1] = 10.0
        net.expected_move_head.weight.zero_()
        net.expected_move_head.bias.fill_(math.atanh(20.0 / 120.0))
        net.confidence_head.weight.zero_()
        net.confidence_head.bias.fill_(math.log(0.2 / 0.8))
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )

    output = model.forward(_tensor(4))

    assert output.selected_action == "long"
    assert output.action_probabilities[output.selected_action_index] > 0.9
    assert output.confidence_raw == pytest.approx(0.2, abs=1e-5)
    assert output.confidence_raw < output.action_probabilities[output.selected_action_index]


def test_fresh_unfitted_model_is_honest_and_publisher_blocks() -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(5).model_vector))
    output = model.forward(_tensor(5))
    assert output.calibration["calibration_fitted"] is False
    assert output.confidence_calibrated == 0.0
    assert output.calibration["probability_semantics_valid"] is False

    directional = replace(
        output,
        selected_action="long",
        selected_action_index=1,
        expected_move_bps=20.0,
        confidence_raw=0.99,
        confidence_calibrated=0.99,
    )
    example = _example(5, profitable=True)
    payload = build_prediction_payload(
        example=example,
        model_output=directional,
        checkpoint=None,
        round_trip_cost_bps=4.0,
        min_data_coverage_percent=0.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=0.0,
    )
    assert payload["paper_fill_allowed"] is False
    assert payload["confidence_calibration_fitted"] is False
    assert payload["confidence_source"] == "UNFITTED_MODEL_CONFIDENCE_BLOCKED"
    assert "confidence_calibration_unfitted_or_semantics_invalid" in payload[
        "paper_fill_gate_block_reasons"
    ]


def test_sampled_direction_uses_its_own_confidence_not_deterministic_hold(
    tmp_path: Path,
) -> None:
    example = _example(23, profitable=True, action="long")
    model = V2HybridPolicyModel(input_dim=len(example.tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    torch = model.torch
    net = model.net
    assert torch is not None and net is not None
    with torch.no_grad():
        net.policy_head.weight.zero_()
        net.policy_head.bias.fill_(-10.0)
        net.policy_head.bias[0] = 10.0
        net.policy_head.bias[1] = 3.0
        net.expected_move_head.weight.zero_()
        net.expected_move_head.bias.fill_(math.atanh(20.0 / 120.0))
        net.confidence_head.weight.zero_()
        net.confidence_head.bias[0] = math.log(0.83 / 0.17)
        net.confidence_head.bias[1] = math.log(0.17 / 0.83)
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )
    deterministic = model.forward(example.tensor)
    assert deterministic.selected_action == "hold"
    assert deterministic.confidence_calibrated == 0.0
    long_record = deterministic.calibration[
        "confidence_calibration_by_direction"
    ]["long"]
    manager = V2HybridCheckpointManager(
        tmp_path / ".local_models" / "sampled_direction"
    )
    checkpoint = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    checkpoint_load = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=model.input_dim)
    )
    assert checkpoint_load["checkpoint_identity_verified"] is True

    payload = build_prediction_payload(
        example=example,
        model_output=deterministic,
        checkpoint=checkpoint,
        round_trip_cost_bps=2.0,
        min_data_coverage_percent=0.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=0.0,
        served_policy_fingerprint=checkpoint.model_parameter_fingerprint,
        checkpoint_weight_sha256=checkpoint.weight_file_sha256,
        checkpoint_evidence_digest=checkpoint.checkpoint_evidence_digest,
        checkpoint_evidence_verified=bool(
            checkpoint_load["checkpoint_evidence_verified"]
        ),
        checkpoint_identity_verified=bool(
            checkpoint_load["checkpoint_identity_verified"]
        ),
        cost_provenance=_exact_cost_provenance(),
        behavior_sample_draw_u53=U53_DENOMINATOR - 1,
        on_policy_sampling_selected=True,
        on_policy_sampling_plan={"plan_hash": "a" * 64, "input_hash": "b" * 64},
        decision_time_utc="2026-07-18T00:01:00Z",
    )

    assert payload["on_policy_action_receipt_valid"] is True, payload[
        "on_policy_behavior_receipt_rejection_reasons"
    ]
    assert payload["selected_action"] == "long"
    assert payload["confidence_raw"] == pytest.approx(long_record["confidence_raw"])
    assert payload["confidence_calibrated"] == pytest.approx(
        long_record["confidence_calibrated"]
    )
    assert payload["confidence_calibration_fitted"] is True
    assert payload["confidence_calibration"]["selected_action"] == "long"


def test_checkpoint_round_trip_binds_calibration_to_weight_blob(tmp_path: Path) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(6).model_vector))
    fitted = _identifiable_calibration_state()
    model.set_confidence_calibration_state(fitted)
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "confidence")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    restored = V2HybridPolicyModel(input_dim=model.input_dim)
    load = manager.load_latest_weights(restored)

    assert manifest.confidence_calibration_fitted is True
    assert manifest.confidence_calibration_validation_rows_used == 0
    assert manifest.confidence_head_schema_version == CONFIDENCE_HEAD_SCHEMA_VERSION
    assert manifest.confidence_head_actions == CONFIDENCE_HEAD_ACTIONS
    assert manifest.confidence_calibration_long_sample == 3
    assert manifest.confidence_calibration_short_sample == 3
    assert len(
        str(manifest.confidence_calibration_model_parameter_fingerprint)
    ) == 64
    assert load["confidence_calibration_fitted"] is True
    assert restored.confidence_calibration_state["row_digest"] == fitted["row_digest"]
    assert restored.confidence_calibration_state[
        "model_parameter_fingerprint"
    ] == manifest.confidence_calibration_model_parameter_fingerprint


def test_zero_scale_calibration_round_trips_without_fake_temperature(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(32).model_vector))
    zero_scale = fit_temperature(
        [0.9, 0.1],
        [0, 1],
        row_ids=["anti-long", "anti-short"],
        action_labels=["long", "short"],
    )
    assert zero_scale["fitted"] is True
    model.set_confidence_calibration_state(zero_scale)
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "zero_scale")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    restored = V2HybridPolicyModel(input_dim=model.input_dim)
    load = manager.load_latest_weights(restored)

    assert manifest.confidence_calibration_fitted is True
    assert manifest.confidence_calibration_temperature is None
    assert manifest.confidence_calibration_logit_scale == 0.0
    assert load["latest_checkpoint_loadable"] is True
    assert restored.confidence_calibration_state["temperature"] is None
    assert restored.confidence_calibration_state["logit_scale"] == 0.0


def test_legacy_scalar_confidence_checkpoint_refuses_load_without_mutation(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(7).model_vector))
    fitted = _identifiable_calibration_state()
    model.set_confidence_calibration_state(fitted)
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "legacy_scalar")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    weight_path = Path(str(manifest.weight_file_path))
    with np.load(weight_path, allow_pickle=False) as archive:
        legacy_payload = {key: archive[key].copy() for key in archive.files}
    legacy_payload.pop("__confidence_head_schema_version")
    legacy_payload.pop("__confidence_head_actions_json")
    if "torch::confidence_head.weight" in legacy_payload:
        legacy_payload["torch::confidence_head.weight"] = legacy_payload[
            "torch::confidence_head.weight"
        ][:1]
        legacy_payload["torch::confidence_head.bias"] = legacy_payload[
            "torch::confidence_head.bias"
        ][:1]
    np.savez_compressed(weight_path, **legacy_payload)

    restored = V2HybridPolicyModel(input_dim=model.input_dim)
    restored.set_confidence_calibration_state(fitted)
    calibration_before = restored.confidence_calibration_state
    tensor_before = (
        restored.net.confidence_head.weight.detach().clone()
        if restored.net is not None
        else None
    )
    sha_rejection = manager.load_latest_weights(restored)

    assert sha_rejection["latest_checkpoint_loadable"] is False
    assert sha_rejection["model_state_restored"] is False
    assert sha_rejection["weight_file_sha256_verified"] is False
    assert sha_rejection["load_status"] == "WEIGHT_BLOB_SHA256_MISMATCH"
    assert restored.confidence_calibration_state == calibration_before
    if tensor_before is not None and restored.net is not None:
        assert tensor_before.equal(restored.net.confidence_head.weight)

    _rebind_manifest_to_current_weight_sha256(manifest)
    load = manager.load_latest_weights(restored)

    assert load["latest_checkpoint_loadable"] is False
    assert load["model_state_restored"] is False
    assert load["checkpoint_confidence_head_compatible"] is False
    assert load["confidence_calibration_reason"] == (
        "CHECKPOINT_CONFIDENCE_HEAD_INCOMPATIBLE"
    )
    assert load["load_error_reason"] == (
        "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
    )
    assert restored.confidence_calibration_state == calibration_before
    if tensor_before is not None and restored.net is not None:
        assert tensor_before.equal(restored.net.confidence_head.weight)


def test_calibration_fingerprint_mismatch_rejects_content_addressed_checkpoint(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(8).model_vector))
    if not model.torch_available:
        pytest.skip("parameter-bound confidence requires torch head")
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "mismatch")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    weight_path = Path(str(manifest.weight_file_path))
    with np.load(weight_path, allow_pickle=False) as archive:
        payload = {key: archive[key].copy() for key in archive.files}
    calibration = json.loads(str(payload["__confidence_calibration_state_json"][0]))
    actual_fingerprint = str(calibration["model_parameter_fingerprint"])
    calibration["model_parameter_fingerprint"] = (
        "a" * 64 if actual_fingerprint != "a" * 64 else "b" * 64
    )
    payload["__confidence_calibration_state_json"] = np.array(
        [json.dumps(calibration, sort_keys=True, separators=(",", ":"))]
    )
    np.savez_compressed(weight_path, **payload)

    restored = V2HybridPolicyModel(input_dim=model.input_dim)
    sha_rejection = manager.load_latest_weights(restored)

    assert sha_rejection["latest_checkpoint_loadable"] is False
    assert sha_rejection["model_state_restored"] is False
    assert sha_rejection["weight_file_sha256_verified"] is False
    assert sha_rejection["load_status"] == "WEIGHT_BLOB_SHA256_MISMATCH"

    _rebind_manifest_to_current_weight_sha256(manifest)
    load = manager.load_latest_weights(restored)

    assert load["latest_checkpoint_loadable"] is False
    assert load["model_state_restored"] is False
    assert load["checkpoint_identity_verified"] is False
    assert load["load_status"] == "CHECKPOINT_CONTENT_IDENTITY_MISMATCH"


def test_calibration_missing_fingerprint_rejects_content_addressed_checkpoint(
    tmp_path: Path,
) -> None:
    model = V2HybridPolicyModel(input_dim=len(_tensor(26).model_vector))
    if not model.torch_available:
        pytest.skip("parameter-bound confidence requires torch head")
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )
    manager = V2HybridCheckpointManager(
        tmp_path / ".local_models" / "missing_fingerprint"
    )
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    weight_path = Path(str(manifest.weight_file_path))
    with np.load(weight_path, allow_pickle=False) as archive:
        payload = {key: archive[key].copy() for key in archive.files}
    calibration = json.loads(str(payload["__confidence_calibration_state_json"][0]))
    calibration.pop("model_parameter_fingerprint")
    payload["__confidence_calibration_state_json"] = np.array(
        [json.dumps(calibration, sort_keys=True, separators=(",", ":"))]
    )
    np.savez_compressed(weight_path, **payload)

    restored = V2HybridPolicyModel(input_dim=model.input_dim)
    sha_rejection = manager.load_latest_weights(restored)

    assert sha_rejection["latest_checkpoint_loadable"] is False
    assert sha_rejection["model_state_restored"] is False
    assert sha_rejection["weight_file_sha256_verified"] is False
    assert sha_rejection["load_status"] == "WEIGHT_BLOB_SHA256_MISMATCH"

    _rebind_manifest_to_current_weight_sha256(manifest)
    load = manager.load_latest_weights(restored)

    assert load["latest_checkpoint_loadable"] is False
    assert load["model_state_restored"] is False
    assert load["checkpoint_identity_verified"] is False
    assert load["load_status"] == "CHECKPOINT_CONTENT_IDENTITY_MISMATCH"


def test_trainer_fits_only_train_rows_and_never_forward_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    train_rows = [
        _example(10, profitable=True, action="long"),
        _example(11, profitable=False, action="short"),
    ]
    validation_rows = [_example(99, profitable=True, action="long")]
    model = V2HybridPolicyModel(input_dim=len(train_rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    trainer = V2HybridPPOTrainer(model=model)
    captured: dict[str, object] = {}
    original = ppo_module.fit_temperature

    def recording_fit(raw_probs, outcomes, **kwargs):  # noqa: ANN001, ANN202
        captured["row_ids"] = list(kwargs.get("row_ids") or [])
        captured["validation_rows_used"] = kwargs.get("validation_rows_used")
        return original(raw_probs, outcomes, **kwargs)

    monkeypatch.setattr(ppo_module, "fit_temperature", recording_fit)
    result = trainer._train_torch(  # noqa: SLF001
        train_rows,
        validation_rows=validation_rows,
        steps=1,
        batch_size=2,
        target_batch_size=2,
        available_rows=3,
        selected_rows=3,
        learning_mode="outcome_supervised",
    )

    assert captured["row_ids"] == [
        "feedback_confidence_10",
        "feedback_confidence_11",
    ]
    assert "feedback_confidence_99" not in captured["row_ids"]
    assert captured["validation_rows_used"] == 0
    assert result.metrics["confidence_calibration_fit_partition"] == "PURGED_TRAIN_ONLY"
    assert result.metrics["confidence_calibration_validation_rows_used"] == 0
    assert result.metrics["validation_confidence_rows_used_for_fit"] == 0
    assert result.metrics["validation_confidence_partition_untouched"] is True


def test_validation_confidence_nonfinite_tensor_is_invalid_evidence() -> None:
    row = _example(30, profitable=True, action="long")
    invalid = replace(
        row,
        tensor=replace(row.tensor, values=(float("nan"),)),
    )
    model = V2HybridPolicyModel(input_dim=len(row.tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )

    metrics = V2HybridPPOTrainer(model=model)._validation_confidence_metrics(  # noqa: SLF001
        [invalid]
    )

    assert metrics["validation_confidence_status"] == (
        "NONFINITE_VALIDATION_CONFIDENCE_INPUT"
    )
    assert metrics["validation_confidence_nonfinite_input_value_count"] == 1
    assert metrics["validation_confidence_rows_evaluated"] == 0
    assert metrics["validation_confidence_brier"] is None


def test_validation_confidence_nonfinite_forward_output_is_invalid_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _example(31, profitable=False, action="short")
    model = V2HybridPolicyModel(input_dim=len(row.tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    assert model.net is not None
    model.set_confidence_calibration_state(
        _identifiable_calibration_state()
    )
    original_forward = model.net.forward

    def nonfinite_forward(batch):  # noqa: ANN001, ANN202
        outputs = dict(original_forward(batch))
        confidence = outputs["confidence_by_direction"].clone()
        confidence.reshape(-1)[0] = float("nan")
        outputs["confidence_by_direction"] = confidence
        return outputs

    monkeypatch.setattr(model.net, "forward", nonfinite_forward)

    metrics = V2HybridPPOTrainer(model=model)._validation_confidence_metrics(  # noqa: SLF001
        [row]
    )

    assert metrics["validation_confidence_status"] == (
        "NONFINITE_VALIDATION_CONFIDENCE_OUTPUT"
    )
    assert metrics["validation_confidence_nonfinite_output_value_count"] == 1
    assert metrics["validation_confidence_rows_evaluated"] == 0
    assert metrics["validation_confidence_brier"] is None


def test_deprecated_external_fitter_cannot_mutate_or_adopt_state(tmp_path: Path) -> None:
    state_path = tmp_path / "confidence_temperature.json"
    state_path.write_text('{"temperature": 99.0}\n', encoding="utf-8")

    report = run_fit(
        checkpoint_dir=".local_models/unit",
        rows=[object()],
        confirm=True,
        state_path=state_path,
    )

    assert report["decision"] == "BLOCKED_EXTERNAL_CALIBRATION_BYPASS_DEPRECATED"
    assert report["state_write_attempted"] is False
    assert report["state_mutated"] is False
    assert report["external_state_adopted_by_inference"] is False
    assert state_path.read_text(encoding="utf-8") == '{"temperature": 99.0}\n'
