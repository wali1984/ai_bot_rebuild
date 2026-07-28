from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    counterfactual_universe_sha256,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    counterfactual_reference_side,
    mature_candidate,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_publisher_v2 import (
    build_publisher_cycle,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_serving_dataset_v2 import (
    CandidateOutcomeDatasetError,
    build_adaptive_serving_dataset_v2,
    build_candidate_outcome_row,
    candidate_directional_edges,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_maturer_v2 import (
    _rows_and_proof,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_publisher_v2 import (
    _inputs,
    _registry,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _features() -> dict[str, float]:
    return {
        "expected_funding_bps": 0.1,
        "expected_slippage_bps": 0.5,
        "fee_bps": 1.0,
        "spread_bps": 1.5,
        "bb_width_pct": 0.02,
        "body_pct": 0.01,
        "close": 100.0,
        "ema_12": 99.8,
        "ema_26": 99.5,
        "high": 101.0,
        "log_return": 0.001,
        "low": 99.0,
        "macd": 0.2,
        "macd_hist": 0.1,
        "macd_signal": 0.1,
        "num_trades": 100.0,
        "open": 99.7,
        "quote_volume": 10_000.0,
        "range_pct": 0.02,
        "ret_pct": 0.003,
        "rsi_14": 55.0,
        "taker_buy_base_vol": 50.0,
        "taker_buy_quote_vol": 5_000.0,
        "taker_buy_ratio": 0.5,
        "taker_sell_base_vol": 50.0,
        "taker_sell_quote_vol": 5_000.0,
        "taker_sell_ratio": 0.5,
        "true_range_pct": 0.02,
        "volume": 100.0,
    }


def _matured_record(*, hold: bool = False):
    status, intents, _ = _inputs(1)
    registry = deepcopy(_registry())
    registry["feature_abi_sha256"] = feature_abi_sha256()
    intent = intents[0]
    intent["feature_abi_sha256"] = feature_abi_sha256()
    intent.update(
        {
            "entry_price": 100.1,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
            "stop_distance_bps": 100.0,
            "expected_move_after_cost_bps": 80.0,
        }
    )
    if hold:
        intent.update(
            {
                "side": "HOLD",
                "selected_action": "HOLD",
                "allocator_decision": "BLOCK_POLICY_SELECTED_FLAT",
                "expected_move_after_cost_bps": 0.0,
            }
        )
    snapshot = build_archive_record(
        snapshot_id="snapshot-0",
        symbol="BTCUSDT",
        timeframe="5m",
        feature_cutoff="2026-07-27T20:00:00.000Z",
        decision_time="2026-07-27T20:00:10.000642Z",
        available_at="2026-07-27T20:00:02.000Z",
        mtf_snapshot_id="mtf-0",
        features=_features(),
        missing_mask={name: False for name in ORDERED_FEATURE_NAMES},
        stale_mask={name: False for name in ORDERED_FEATURE_NAMES},
        source_availability={name: "2026-07-27T20:00:01.000Z" for name in ORDERED_FEATURE_NAMES},
        source_hashes={"feature_vector_hash": "6" * 64},
        created_at="2026-07-27T20:00:10Z",
        extra={
            "checkpoint_id": registry["checkpoint_id"],
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_V1",
            "latest_unclosed_exclusion_decision_time_ms": 1_785_182_401_000,
            "latest_closed_kline_close_time_ms": 1_785_182_400_000,
        },
    )
    cycle = build_publisher_cycle(
        paper_status=status,
        intents=intents,
        registry_payload=registry,
        feature_snapshots_by_id={"snapshot-0": snapshot},
    )
    decision = cycle.decision_records[0]
    rows, proof = _rows_and_proof(decision)
    matured = mature_candidate(
        decision,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )
    return matured, snapshot


def _base_dataset(template: dict[str, object], count: int = 120) -> dict[str, object]:
    # Span both sides of the candidate decision so the combined chronological
    # fixture proves the new source can be admitted to training without crossing
    # either validation boundary.
    start = datetime(2026, 7, 23, tzinfo=UTC)
    rows = []
    for index in range(count):
        decision = start + timedelta(hours=index * 2)
        label = decision + timedelta(hours=1)
        row = deepcopy(template)
        row.update(
            {
                "row_id": f"base-row-{index:03d}",
                "snapshot_id": f"base-snapshot-{index:03d}",
                "decision_time": decision.isoformat().replace("+00:00", "Z"),
                "label_available_at": label.isoformat().replace("+00:00", "Z"),
            }
        )
        for field in (
            "feature_group_id",
            "source_kind",
            "candidate_id",
            "prediction_id",
            "checkpoint_generation",
            "checkpoint_id",
            "decision_disposition",
            "eventual_disposition",
            "directional_label_derivation",
            "counterfactual_counts_as_realized_paper_profit",
            "actual_paper_outcome_present",
            "split",
        ):
            row.pop(field, None)
        rows.append(row)
    material = {
        "schema_version": "serving_compatible_dataset_v2",
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "action_labels": ["long", "short", "hold"],
        "rows": rows,
    }
    sha = _digest(material)
    return {
        **material,
        "dataset_id": f"fixture-{sha[:12]}",
        "dataset_sha256": sha,
    }


def _legacy_single_side_flat(record):
    assert record.matured_labels is not None
    decision = record.decision
    plan = decision.counterfactual_evaluation_plan
    reference = counterfactual_reference_side(decision.candidate_id)
    arm_index = next(index for index, arm in enumerate(plan.arms) if arm.arm_name == "alternative_side")
    plan_arm = plan.arms[arm_index]
    plan_scenario = next(
        scenario for scenario in plan_arm.scenarios if scenario.scenario_id.endswith(reference)
    )
    new_plan_arm = replace(plan_arm, scenarios=(plan_scenario,))
    new_plan_arms = list(plan.arms)
    new_plan_arms[arm_index] = new_plan_arm
    new_plan = replace(plan, arms=tuple(new_plan_arms))
    new_decision = replace(decision, counterfactual_evaluation_plan=new_plan)

    labels = record.matured_labels
    outcome_index = next(
        index
        for index, arm in enumerate(labels.counterfactual_outcomes)
        if arm.arm_name == "alternative_side"
    )
    outcome_arm = labels.counterfactual_outcomes[outcome_index]
    outcome_scenario = next(
        scenario
        for scenario in outcome_arm.scenarios
        if scenario.scenario_id.endswith(reference)
    )
    scenarios = (outcome_scenario,)
    new_outcome_arm = replace(
        outcome_arm,
        scenarios=scenarios,
        eligible_scenario_count=1,
        scenario_universe_sha256=counterfactual_universe_sha256(
            arm_name="alternative_side",
            scenarios=scenarios,
            eligible_scenario_count=1,
            excluded_scenario_count=0,
            exclusion_receipt_sha256=None,
        ),
    )
    new_outcomes = list(labels.counterfactual_outcomes)
    new_outcomes[outcome_index] = new_outcome_arm
    new_labels = replace(
        labels,
        decision_snapshot_sha256=new_decision.content_sha256(),
        counterfactual_plan_sha256=new_plan.content_sha256(),
        counterfactual_outcomes=tuple(new_outcomes),
    )
    return replace(record, decision=new_decision, matured_labels=new_labels)


def test_candidate_row_uses_shared_builder_and_never_counts_counterfactual_profit() -> None:
    matured, snapshot = _matured_record()

    row = build_candidate_outcome_row(
        matured,
        snapshot_loader=lambda snapshot_id: snapshot if snapshot_id == "snapshot-0" else None,
        source_archive_chain_sha256="a" * 64,
    )

    assert row["feature_abi_sha256"] == feature_abi_sha256()
    assert row["feature_builder_sha256"] == feature_builder_sha256()
    assert len(row["feature_values"]) == len(ORDERED_FEATURE_NAMES)
    assert row["missing_mask"] == [0] * len(ORDERED_FEATURE_NAMES)
    assert row["label_available_at"] > row["decision_time"]
    assert row["target_action"] in {"long", "short", "hold"}
    assert row["counterfactual_counts_as_realized_paper_profit"] is False
    assert row["actual_paper_outcome_present"] is False


def test_flat_labels_cover_balanced_and_legacy_predeclared_reference_contracts() -> None:
    matured, _ = _matured_record(hold=True)
    long_net, short_net, target, receipt = candidate_directional_edges(matured)
    assert math_is_finite(long_net, short_net)
    assert target in {"long", "short", "hold"}
    assert receipt["derivation_method"] == (
        "PREDECLARED_BALANCED_LONG_SHORT_ALTERNATIVE_SIDE"
    )

    legacy = _legacy_single_side_flat(matured)
    legacy_long, legacy_short, legacy_target, legacy_receipt = candidate_directional_edges(
        legacy
    )
    assert legacy_long == pytest.approx(long_net)
    assert legacy_short == pytest.approx(short_net)
    assert legacy_target == target
    assert legacy_receipt["derivation_method"] == (
        "LEGACY_PREDECLARED_REFERENCE_SIDE_ACCOUNTING_INVERSION"
    )


def math_is_finite(*values: float) -> bool:
    return all(value == value and abs(value) != float("inf") for value in values)


def test_combined_dataset_resplits_without_label_overlap_and_accounts_every_candidate() -> None:
    matured, snapshot = _matured_record()
    candidate_template = build_candidate_outcome_row(
        matured,
        snapshot_loader=lambda _snapshot_id: snapshot,
        source_archive_chain_sha256="a" * 64,
    )
    base = _base_dataset(candidate_template)

    dataset, manifest, parity = build_adaptive_serving_dataset_v2(
        base_dataset=base,
        candidate_records=(matured,),
        snapshot_loader=lambda snapshot_id: snapshot if snapshot_id == "snapshot-0" else None,
        source_archive_chain_sha256="a" * 64,
    )

    assert manifest["candidate_records_fully_accounted"] is True
    assert manifest["candidate_rows_before_split_purge"] == 1
    assert manifest["duplicate_rows"] == 0
    assert manifest["future_time_rejections"] == 0
    assert manifest["counterfactual_counts_as_realized_paper_profit"] is False
    train = [row for row in dataset["rows"] if row["split"] == "train"]
    validation = [row for row in dataset["rows"] if row["split"] == "validation"]
    holdout = [row for row in dataset["rows"] if row["split"] == "holdout"]
    assert max(row["label_available_at"] for row in train) < min(
        row["decision_time"] for row in validation
    )
    assert max(row["label_available_at"] for row in validation) < min(
        row["decision_time"] for row in holdout
    )
    split_by_group: dict[str, set[str]] = {}
    for row in dataset["rows"]:
        split_by_group.setdefault(row["feature_group_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in split_by_group.values())
    assert parity["builder_match"] is True
    assert parity["activation_eligible"] is False


def test_tampered_base_dataset_and_missing_snapshot_fail_closed() -> None:
    matured, snapshot = _matured_record()
    template = build_candidate_outcome_row(
        matured,
        snapshot_loader=lambda _snapshot_id: snapshot,
        source_archive_chain_sha256="a" * 64,
    )
    base = _base_dataset(template)
    base["rows"][0]["target_action"] = "tampered"
    with pytest.raises(CandidateOutcomeDatasetError, match="CONTENT_SHA256_MISMATCH"):
        build_adaptive_serving_dataset_v2(
            base_dataset=base,
            candidate_records=(matured,),
            snapshot_loader=lambda _snapshot_id: snapshot,
            source_archive_chain_sha256="a" * 64,
        )

    with pytest.raises(CandidateOutcomeDatasetError, match="VERIFIED_SNAPSHOT_MISSING"):
        build_candidate_outcome_row(
            matured,
            snapshot_loader=lambda _snapshot_id: None,
            source_archive_chain_sha256="a" * 64,
        )
