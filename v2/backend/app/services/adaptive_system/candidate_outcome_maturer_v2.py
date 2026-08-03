"""Point-in-time maturation of signed candidate decisions from finalized 5m facts.

This module has no Redis or execution dependency.  It accepts one verified
decision revision and one complete range returned by
``DurableCanonical5mLabelArchive.verified_range``.  Rejected and infeasible
candidates become learning labels, never realized paper profit.  Executed
decisions remain pending until an exact reconciled paper-close outcome is
provided.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    COUNTERFACTUAL_ARM_SCHEMA_VERSION,
    COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION,
    HORIZON_LABEL_SCHEMA_VERSION,
    LIVE_GATE_BLOCKED_HUMAN_ONLY,
    MATURED_LABELS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ActualPaperExecutionOutcomeV2,
    CandidateDecisionOutcomeV2,
    CandidateHorizonLabelV2,
    CounterfactualArmOutcomeV2,
    CounterfactualScenarioV2,
    MaturedLabelsV2,
    counterfactual_universe_sha256,
)

LABEL_SLOT_MILLISECONDS = 300_000
LABELER_ID = "canonical-finalized-5m-candidate-labeler-v2"
LABELER_SEMANTICS = {
    "schema_version": "candidate_outcome_labeler_semantics_v2",
    "entry": "decision_time_executable_touch_then_decision_mark_fallback",
    "horizon_price": "first_finalized_5m_close_at_or_after_exact_horizon_end",
    "mfe_mae": "side_oriented_high_low_over_complete_declared_horizon",
    "volatility": "population_stddev_log_returns_bps",
    "cost": "2x_fee_per_side+spread+2x_slippage_per_side+funding+2x_impact_per_side",
    "counterfactual_unhedged": "selected_side_return",
    "counterfactual_hedged": "fully_delta_neutral_zero_gross_return_double_execution_drag",
    "counterfactual_alternative_side": "opposite_side_return_and_opposite_funding",
    "counterfactual_alternative_size": "per_notional_bps_invariant_at_decision_impact",
    "counterfactual_alternative_leverage": "per_notional_bps_invariant_before_margin_return",
    "counterfactual_alternative_entry": "decision_mark_entry",
    "counterfactual_alternative_exit": "maximum_favorable_finalized_5m_extreme",
    "counterfactual_accounting": "never_realized_paper_profit",
    "flat_candidate_learning": (
        "hold_is_zero_realized_exposure;horizon_mfe_mae_use_sha256_balanced_"
        "pre_outcome_reference_side;alternative_side_records_missed_edge"
    ),
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


LABELER_VERSION_SHA256 = _sha256(LABELER_SEMANTICS)


class CandidateOutcomeMaturationError(ValueError):
    """Permanent malformed or contradictory maturation evidence."""


class CandidateOutcomeMaturationPending(RuntimeError):
    """Exact reason why an otherwise valid decision is not mature yet."""


def _fail(reason: str, field: str) -> None:
    raise CandidateOutcomeMaturationError(f"{field}:{reason}")


def _pending(reason: str, field: str) -> None:
    raise CandidateOutcomeMaturationPending(f"{field}:{reason}")


def _finite(value: object, field: str, *, nonnegative: bool = False) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail("finite_number_required", field)
    result = float(value)
    if not math.isfinite(result):
        _fail("finite_number_required", field)
    if nonnegative and result < 0.0:
        _fail("nonnegative_required", field)
    return result


def _positive(value: object, field: str) -> float:
    result = _finite(value, field)
    if result <= 0.0:
        _fail("positive_number_required", field)
    return result


def _positive_ms(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        _fail("positive_int_required", field)
    return value


def _payload(record: CandidateDecisionOutcomeV2, evidence_name: str) -> dict[str, Any]:
    evidence = getattr(record.decision, evidence_name)
    try:
        value = json.loads(evidence.payload_json)
    except json.JSONDecodeError as exc:  # Defensive: the contract normally prevents this.
        raise CandidateOutcomeMaturationError(
            f"decision.{evidence_name}:invalid_payload_json"
        ) from exc
    if type(value) is not dict:
        _fail("object_required", f"decision.{evidence_name}")
    return value


def first_label_close_at_or_after(epoch_ms: int) -> int:
    """Map an arbitrary instant to the first finalized 5m close at/after it."""

    _positive_ms(epoch_ms, "epoch_ms")
    return ((epoch_ms + 1 + LABEL_SLOT_MILLISECONDS - 1) // LABEL_SLOT_MILLISECONDS) * (
        LABEL_SLOT_MILLISECONDS
    ) - 1


def required_label_range(record: CandidateDecisionOutcomeV2) -> tuple[int, int, int]:
    if type(record) is not CandidateDecisionOutcomeV2:
        _fail("CandidateDecisionOutcomeV2_required", "record")
    if record.archive_sequence != 1 or record.matured_labels is not None:
        _fail("unmatured_revision_one_required", "record")
    decision = record.decision
    start = first_label_close_at_or_after(decision.decision_time_ms)
    final_horizon_end = decision.decision_time_ms + max(
        decision.supported_horizon_seconds
    ) * 1_000
    end = first_label_close_at_or_after(final_horizon_end)
    expected_rows = (end - start) // LABEL_SLOT_MILLISECONDS + 1
    return start, end, expected_rows


def counterfactual_reference_side(candidate_id: str) -> str:
    """Choose a balanced reference side without using any future outcome."""

    if type(candidate_id) is not str or not candidate_id:
        _fail("nonempty_string_required", "candidate_id")
    digest = _sha256(
        {
            "schema_version": "candidate_flat_reference_side_v2",
            "candidate_id": candidate_id,
        }
    )
    return "LONG" if int(digest[0], 16) % 2 == 0 else "SHORT"


@dataclass(frozen=True, slots=True)
class VerifiedLabelPathV2:
    rows: tuple[dict[str, Any], ...]
    range_sha256: str
    receipt_sha256s: tuple[str, ...]
    maximum_available_at_ms: int


def _verified_label_path(
    record: CandidateDecisionOutcomeV2,
    *,
    rows: Sequence[Mapping[str, Any]],
    proof: Mapping[str, Any],
) -> VerifiedLabelPathV2:
    start, end, expected_rows = required_label_range(record)
    if proof.get("status") != "VERIFIED_CANONICAL_5M_LABEL_RANGE":
        reasons = proof.get("rejection_reasons")
        _pending(
            "verified_complete_range_required:"
            + ",".join(str(reason) for reason in reasons or [proof.get("status")]),
            "proof",
        )
    exact_proof = {
        "symbol": record.decision.symbol,
        "start_close_time_ms": start,
        "end_close_time_ms": end,
        "expected_rows": expected_rows,
        "loaded_rows": expected_rows,
    }
    for field, expected in exact_proof.items():
        if proof.get(field) != expected or type(proof.get(field)) is not type(expected):
            _fail("exact_range_binding_mismatch", f"proof.{field}")
    for field in (
        "canonical_payloads_verified",
        "content_sha256_verified",
        "append_transaction_precommit_receipts_verified",
        "postcommit_readback_receipts_verified",
        "record_chain_formula_verified",
        "pit_available_at_verified",
        "contiguous_path_verified",
        "transaction_snapshot_verified",
    ):
        if proof.get(field) is not True:
            _fail("must_be_true", f"proof.{field}")
    observed_at_ms = _positive_ms(
        proof.get("training_observed_at_ms"),
        "proof.training_observed_at_ms",
    )
    range_sha256 = proof.get("range_sha256")
    if type(range_sha256) is not str or len(range_sha256) != 64:
        _fail("sha256_required", "proof.range_sha256")
    if len(rows) != expected_rows:
        _fail("exact_row_count_required", "rows")

    normalized: list[dict[str, Any]] = []
    receipts: set[str] = {range_sha256}
    for field in ("append_receipt_sha256", "postcommit_readback_receipt_sha256"):
        values = proof.get(field)
        if type(values) is not list or not values:
            _fail("nonempty_receipt_array_required", f"proof.{field}")
        for index, value in enumerate(values):
            if type(value) is not str or len(value) != 64:
                _fail("sha256_required", f"proof.{field}[{index}]")
            receipts.add(value)

    prior_close: int | None = None
    maximum_available = 0
    for index, source in enumerate(rows):
        if not isinstance(source, Mapping):
            _fail("object_required", f"rows[{index}]")
        row = dict(source)
        close_ms = _positive_ms(row.get("candle_close_time"), f"rows[{index}].candle_close_time")
        event_ms = _positive_ms(row.get("event_time"), f"rows[{index}].event_time")
        ingested_ms = _positive_ms(row.get("ingested_at"), f"rows[{index}].ingested_at")
        available_ms = _positive_ms(row.get("available_at"), f"rows[{index}].available_at")
        expected_close = start + index * LABEL_SLOT_MILLISECONDS
        if close_ms != expected_close:
            _fail("contiguous_close_time_mismatch", f"rows[{index}].candle_close_time")
        if prior_close is not None and close_ms - prior_close != LABEL_SLOT_MILLISECONDS:
            _fail("label_path_gap", f"rows[{index}].candle_close_time")
        prior_close = close_ms
        if row.get("symbol") != record.decision.symbol or row.get("timeframe") != "5m":
            _fail("candidate_symbol_or_label_timeframe_mismatch", f"rows[{index}]")
        if row.get("is_closed") is not True or row.get("candle_closed_confirmed") is not True:
            _fail("finalized_candle_required", f"rows[{index}]")
        if row.get("feature_eligible") is not True:
            _fail("feature_eligible_required", f"rows[{index}]")
        if not close_ms <= event_ms <= available_ms or not close_ms <= ingested_ms <= available_ms:
            _fail("canonical_clock_order_invalid", f"rows[{index}]")
        if available_ms > observed_at_ms:
            _fail("row_available_after_observation", f"rows[{index}].available_at")
        for price in ("open", "high", "low", "close"):
            _positive(row.get(price), f"rows[{index}].{price}")
        maximum_available = max(maximum_available, available_ms)
        receipts.add(_sha256(row))
        normalized.append(row)
    return VerifiedLabelPathV2(
        rows=tuple(normalized),
        range_sha256=range_sha256,
        receipt_sha256s=tuple(sorted(receipts)),
        maximum_available_at_ms=maximum_available,
    )


def _side_and_prices(
    record: CandidateDecisionOutcomeV2,
) -> tuple[
    str,
    bool,
    float,
    float,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    proposed = _payload(record, "proposed_action")
    execution = _payload(record, "execution_state")
    components = _payload(record, "component_estimates")
    proposed_action = str(
        proposed.get("proposed_action")
        or proposed.get("side")
        or proposed.get("selected_action")
        or ""
    ).upper()
    flat_candidate = proposed_action == "HOLD"
    side = (
        counterfactual_reference_side(record.decision.candidate_id)
        if flat_candidate
        else proposed_action
    )
    if side not in {"LONG", "SHORT"}:
        _fail("directional_proposed_action_required", "decision.proposed_action")
    mark = _positive(
        execution.get("paper_execution_mark_price") or proposed.get("entry_price"),
        "decision.execution_state.paper_execution_mark_price",
    )
    touch_field = "observed_ask" if side == "LONG" else "observed_bid"
    entry = _positive(
        execution.get(touch_field) or proposed.get("entry_price") or mark,
        f"decision.execution_state.{touch_field}",
    )
    return side, flat_candidate, entry, mark, proposed, execution, components


def _side_return_bps(side: str, entry: float, exit_price: float) -> float:
    raw = (exit_price / entry - 1.0) * 10_000.0
    return raw if side == "LONG" else -raw


def _source_row_at_or_after(
    rows: tuple[dict[str, Any], ...],
    horizon_end_ms: int,
) -> dict[str, Any]:
    for row in rows:
        if int(row["candle_close_time"]) >= horizon_end_ms:
            return row
    _pending("finalized_horizon_row_not_available", "rows")


def _costs(
    execution: Mapping[str, Any],
    components: Mapping[str, Any],
) -> tuple[float, float, float, float, float]:
    fee_per_side = _finite(execution.get("fee_bps"), "fee_bps", nonnegative=True)
    spread = _finite(
        execution.get("observed_spread_bps")
        if execution.get("observed_spread_bps") is not None
        else components.get("observed_spread_bps"),
        "observed_spread_bps",
        nonnegative=True,
    )
    slippage_per_side = _finite(
        execution.get("expected_slippage_bps")
        if execution.get("expected_slippage_bps") is not None
        else components.get("expected_slippage_bps"),
        "expected_slippage_bps",
        nonnegative=True,
    )
    funding = _finite(
        execution.get("expected_funding_bps")
        if execution.get("expected_funding_bps") is not None
        else components.get("expected_funding_bps"),
        "expected_funding_bps",
    )
    impact_per_side = _finite(
        components.get("depth_derived_price_impact_bps"),
        "depth_derived_price_impact_bps",
        nonnegative=True,
    )
    return (
        2.0 * fee_per_side,
        spread,
        2.0 * slippage_per_side,
        funding,
        2.0 * impact_per_side,
    )


def mature_candidate(
    record: CandidateDecisionOutcomeV2,
    *,
    rows: Sequence[Mapping[str, Any]],
    proof: Mapping[str, Any],
    label_generated_at_ms: int,
    actual_paper_outcome: ActualPaperExecutionOutcomeV2 | None = None,
) -> CandidateDecisionOutcomeV2:
    """Produce the immutable revision-two record or an exact pending reason."""

    if type(record) is not CandidateDecisionOutcomeV2:
        _fail("CandidateDecisionOutcomeV2_required", "record")
    label_generated_at_ms = _positive_ms(label_generated_at_ms, "label_generated_at_ms")
    path = _verified_label_path(record, rows=rows, proof=proof)
    if label_generated_at_ms < path.maximum_available_at_ms:
        _fail("generated_before_label_source_available", "label_generated_at_ms")
    decision = record.decision
    if decision.decision_disposition in {
        "SELECTED_TRADE",
        "SELECTED_RISK_REDUCED",
        "SELECTED_HEDGED",
    } and actual_paper_outcome is None:
        _pending("reconciled_actual_paper_close_required", "actual_paper_outcome")
    if actual_paper_outcome is not None and type(actual_paper_outcome) is not (
        ActualPaperExecutionOutcomeV2
    ):
        _fail("ActualPaperExecutionOutcomeV2_required", "actual_paper_outcome")

    (
        side,
        flat_candidate,
        entry,
        mark,
        proposed,
        execution,
        components,
    ) = _side_and_prices(record)
    fee_bps, spread_bps, slippage_bps, funding_bps, impact_bps = _costs(
        execution,
        components,
    )
    final_row = path.rows[-1]
    final_close = _positive(final_row.get("close"), "rows[-1].close")
    final_close_ms = _positive_ms(final_row.get("candle_close_time"), "rows[-1].close_time")
    final_event_ms = _positive_ms(final_row.get("event_time"), "rows[-1].event_time")
    final_available_ms = _positive_ms(final_row.get("available_at"), "rows[-1].available_at")

    horizon_labels: list[CandidateHorizonLabelV2] = []
    for horizon in decision.supported_horizon_seconds:
        horizon_end_ms = decision.decision_time_ms + horizon * 1_000
        row = _source_row_at_or_after(path.rows, horizon_end_ms)
        source_close_ms = _positive_ms(row.get("candle_close_time"), "horizon.close_time")
        source_event_ms = _positive_ms(row.get("event_time"), "horizon.event_time")
        source_available_ms = _positive_ms(row.get("available_at"), "horizon.available_at")
        source_receipt = _sha256(
            {
                "schema_version": "candidate_horizon_label_source_receipt_v2",
                "candidate_id": decision.candidate_id,
                "horizon_seconds": horizon,
                "range_sha256": path.range_sha256,
                "canonical_row_sha256": _sha256(row),
            }
        )
        horizon_labels.append(
            CandidateHorizonLabelV2(
                schema_version=HORIZON_LABEL_SCHEMA_VERSION,
                horizon_seconds=horizon,
                horizon_end_ms=horizon_end_ms,
                future_return_bps=float(
                    _side_return_bps(side, entry, _positive(row.get("close"), "horizon.close"))
                ),
                source_event_time_ms=source_close_ms,
                producer_generated_at_ms=source_event_ms,
                record_available_at_ms=source_available_ms,
                source_receipt_sha256=source_receipt,
                finality_proven=True,
            )
        )

    highs = [_positive(row.get("high"), "row.high") for row in path.rows]
    lows = [_positive(row.get("low"), "row.low") for row in path.rows]
    favorable_price = max(highs) if side == "LONG" else min(lows)
    adverse_price = min(lows) if side == "LONG" else max(highs)
    mfe_bps = max(0.0, _side_return_bps(side, entry, favorable_price))
    mae_bps = min(0.0, _side_return_bps(side, entry, adverse_price))
    close_path = [entry, *[_positive(row.get("close"), "row.close") for row in path.rows]]
    log_returns = [
        math.log(current / prior) * 10_000.0
        for prior, current in zip(close_path, close_path[1:], strict=False)
    ]
    volatility_bps = statistics.pstdev(log_returns) if len(log_returns) > 1 else 0.0
    gross_final_bps = _side_return_bps(side, entry, final_close)
    alternative_entry_bps = _side_return_bps(side, mark, final_close)
    alternative_exit_bps = _side_return_bps(side, entry, favorable_price)

    source_receipts = path.receipt_sha256s
    scenario_by_arm: dict[str, tuple[float, float, float, float, float, float]] = {
        "unhedged": (
            0.0 if flat_candidate else gross_final_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            funding_bps,
            impact_bps,
        ),
        "hedged": (
            0.0,
            2.0 * fee_bps,
            2.0 * spread_bps,
            2.0 * slippage_bps,
            0.0,
            2.0 * impact_bps,
        ),
        "alternative_side": (
            gross_final_bps if flat_candidate else -gross_final_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            -funding_bps,
            impact_bps,
        ),
        "alternative_size": (
            gross_final_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            funding_bps,
            impact_bps,
        ),
        "alternative_leverage": (
            gross_final_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            funding_bps,
            impact_bps,
        ),
        "alternative_entry": (
            alternative_entry_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            funding_bps,
            impact_bps,
        ),
        "alternative_exit": (
            alternative_exit_bps,
            fee_bps,
            spread_bps,
            slippage_bps,
            funding_bps,
            impact_bps,
        ),
    }
    counterfactual_outcomes: list[CounterfactualArmOutcomeV2] = []
    for plan_arm in decision.counterfactual_evaluation_plan.arms:
        base_gross, fees, spread, slippage, funding, impact = scenario_by_arm[
            plan_arm.arm_name
        ]
        scenarios_list: list[CounterfactualScenarioV2] = []
        for planned in plan_arm.scenarios:
            gross = base_gross
            scenario_funding = funding
            if flat_candidate and plan_arm.arm_name == "alternative_side":
                planned_side = (
                    "LONG"
                    if planned.scenario_id.endswith("-LONG")
                    else "SHORT"
                    if planned.scenario_id.endswith("-SHORT")
                    else side
                )
                gross = _side_return_bps(planned_side, entry, final_close)
                scenario_funding = funding if planned_side == side else -funding
            scenarios_list.append(
                CounterfactualScenarioV2(
                schema_version=COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION,
                scenario_id=planned.scenario_id,
                action_sha256=planned.action_sha256,
                gross_pnl_bps=float(gross),
                fees_bps=float(fees),
                spread_bps=float(spread),
                slippage_bps=float(slippage),
                funding_bps=float(scenario_funding),
                market_impact_bps=float(impact),
                after_cost_pnl_bps=float(
                    gross
                    - fees
                    - spread
                    - slippage
                    - scenario_funding
                    - impact
                ),
                source_event_time_ms=final_close_ms,
                producer_generated_at_ms=final_event_ms,
                record_available_at_ms=final_available_ms,
                source_receipt_sha256s=source_receipts,
                finality_proven=True,
                counts_as_paper_profit=False,
                actual_accounting_effect=False,
            )
            )
        scenarios = tuple(scenarios_list)
        universe = counterfactual_universe_sha256(
            arm_name=plan_arm.arm_name,
            scenarios=scenarios,
            eligible_scenario_count=len(scenarios),
            excluded_scenario_count=0,
            exclusion_receipt_sha256=None,
        )
        counterfactual_outcomes.append(
            CounterfactualArmOutcomeV2(
                schema_version=COUNTERFACTUAL_ARM_SCHEMA_VERSION,
                arm_name=plan_arm.arm_name,
                scenario_universe_sha256=universe,
                scenarios=scenarios,
                eligible_scenario_count=len(scenarios),
                excluded_scenario_count=0,
                exclusion_receipt_sha256=None,
                complete=True,
            )
        )

    eventual_by_decision = {
        "REJECTED": "REJECTED",
        "INFEASIBLE": "INFEASIBLE",
        "SELECTED_FLAT": "FLAT",
        "SELECTED_TRADE": "TRADED",
        "SELECTED_RISK_REDUCED": "RISK_REDUCED",
        "SELECTED_HEDGED": "HEDGED",
    }
    stop_distance = proposed.get("stop_distance_bps")
    stop_result = (
        "TARGET_UNDECLARED"
        if stop_distance is None
        else "HIT"
        if mae_bps <= -_finite(stop_distance, "stop_distance_bps", nonnegative=True)
        else "NOT_HIT"
    )
    profit_target = proposed.get("expected_move_after_cost_bps")
    profit_result = (
        "TARGET_UNDECLARED"
        if profit_target is None or _finite(profit_target, "expected_move_after_cost_bps") <= 0.0
        else "HIT"
        if mfe_bps >= float(profit_target)
        else "NOT_HIT"
    )
    summary_material = {
        "schema_version": "candidate_matured_label_summary_receipt_v2",
        "candidate_id": decision.candidate_id,
        "decision_snapshot_sha256": decision.content_sha256(),
        "range_sha256": path.range_sha256,
        "labeler_version_sha256": LABELER_VERSION_SHA256,
        "horizon_label_receipts": [label.source_receipt_sha256 for label in horizon_labels],
        "mfe_bps": mfe_bps,
        "mae_bps": mae_bps,
        "volatility_bps": volatility_bps,
        "final_close_time_ms": final_close_ms,
        "proposed_action": proposed.get("proposed_action"),
        "counterfactual_reference_side": side if flat_candidate else None,
    }
    summary_receipt = _sha256(summary_material)
    label_source_receipts = tuple(sorted({*source_receipts, summary_receipt}))
    labels = MaturedLabelsV2(
        schema_version=MATURED_LABELS_SCHEMA_VERSION,
        candidate_id=decision.candidate_id,
        decision_snapshot_sha256=decision.content_sha256(),
        counterfactual_plan_sha256=decision.counterfactual_evaluation_plan.content_sha256(),
        eventual_disposition=eventual_by_decision[decision.decision_disposition],
        supported_horizon_seconds=decision.supported_horizon_seconds,
        horizon_labels=tuple(horizon_labels),
        max_favorable_excursion_bps=float(mfe_bps),
        max_adverse_excursion_bps=float(mae_bps),
        realized_volatility_bps=float(volatility_bps),
        estimated_executable_entry=float(entry),
        estimated_executable_exit=float(final_close),
        fees_bps=float(fee_bps),
        spread_bps=float(spread_bps),
        slippage_bps=float(slippage_bps),
        funding_bps=float(funding_bps),
        market_impact_bps=float(impact_bps),
        stop_result=stop_result,
        time_exit_result=f"HORIZON_{max(decision.supported_horizon_seconds)}_FINALIZED",
        profit_exit_result=profit_result,
        counterfactual_outcomes=tuple(counterfactual_outcomes),
        actual_paper_outcome=actual_paper_outcome,
        labeler_id=LABELER_ID,
        labeler_version_sha256=LABELER_VERSION_SHA256,
        label_source_receipt_sha256s=label_source_receipts,
        summary_source_event_time_ms=final_close_ms,
        summary_producer_generated_at_ms=final_event_ms,
        summary_record_available_at_ms=final_available_ms,
        summary_receipt_sha256=summary_receipt,
        summary_finality_proven=True,
        label_generated_at_ms=label_generated_at_ms,
        record_available_at_ms=label_generated_at_ms,
        matured=True,
        complete=True,
        counts_as_paper_profit=actual_paper_outcome is not None,
    )
    archive_identity = _sha256(
        {
            "candidate_id": decision.candidate_id,
            "previous_archive_record_sha256": record.content_sha256(),
            "summary_receipt_sha256": summary_receipt,
        }
    )
    return CandidateDecisionOutcomeV2(
        schema_version=SCHEMA_VERSION,
        archive_record_id=f"{decision.candidate_id}-matured-{archive_identity[:24]}",
        archive_sequence=2,
        decision=decision,
        matured_labels=labels,
        previous_archive_record_sha256=record.content_sha256(),
        record_generated_at_ms=label_generated_at_ms,
        record_available_at_ms=label_generated_at_ms,
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


__all__ = [
    "LABELER_ID",
    "LABELER_SEMANTICS",
    "LABELER_VERSION_SHA256",
    "CandidateOutcomeMaturationError",
    "CandidateOutcomeMaturationPending",
    "VerifiedLabelPathV2",
    "first_label_close_at_or_after",
    "required_label_range",
    "mature_candidate",
]
