"""Integration tests for the V2 Native Edge-Proof evaluator.

Verifies:
- replay bundle schema emission and label values;
- evaluator is conservative when operator thresholds are unset;
- evaluator computes correct classification metrics on a synthetic bundle set;
- evaluator never claims edge unless every operator-set numeric threshold is satisfied;
- evaluator preserves the safety invariants
  (live_gate=blocked_human_only, live_symbols=[], approves_*=False).
"""
from __future__ import annotations

from typing import Any

import pytest

from v2.backend.app.services.edge_proof.evaluator import (
    PRIMARY_OUTCOME_WINDOW_ID,
    evaluate,
    summary_to_dict,
)
from v2.backend.app.services.edge_proof.replay_schema import (
    DEFAULT_THRESHOLDS,
    OUTCOME_WINDOWS_SECONDS,
    OutcomeWindow,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    ReplayBundle,
    ReplayLabel,
    emit_canonical_schema,
)


def _outcomes(
    after_cost_5m: float | None,
    stop_hit: bool = False,
    drawdown_5m: float | None = 30.0,
) -> dict[str, OutcomeWindow]:
    out: dict[str, OutcomeWindow] = {}
    for wid, secs in OUTCOME_WINDOWS_SECONDS:
        is_primary = wid == PRIMARY_OUTCOME_WINDOW_ID
        out[wid] = OutcomeWindow(
            window_id=wid,
            window_seconds=secs,
            return_bps=after_cost_5m if is_primary else None,
            after_cost_return_bps=after_cost_5m if is_primary else None,
            drawdown_bps=drawdown_5m if is_primary else None,
            stop_hit=stop_hit if is_primary else False,
            samples=1 if is_primary else 0,
        )
    return out


def _bundle(
    *,
    symbol: str = "BTCUSDT",
    paper_fill_allowed: bool = False,
    paper_intent_decision: str | None = None,
    after_cost_5m: float | None = None,
    block_reasons: list[str] | None = None,
    legacy_action: str | None = None,
    v2_action: str = "hold",
    expected_move_after_cost_bps: float | None = None,
    stop_hit: bool = False,
    label: ReplayLabel = ReplayLabel.INSUFFICIENT_EVIDENCE,
    fee_bps: float | None = 5.0,
    slippage_bps: float | None = 2.0,
    latency_seconds: float | None = 0.1,
    drawdown_5m: float | None = 30.0,
) -> ReplayBundle:
    return ReplayBundle(
        feature_snapshot_id=f"{symbol}:1m:test",
        prediction_id=f"{symbol}:test",
        symbol=symbol,
        timeframe="1m",
        generated_at="2026-05-23T03:00:00Z",
        features_hash="deadbeef",
        market_snapshot={
            "price": 100.0,
            "fee_bps": fee_bps,
            "slippage_estimate_bps": slippage_bps,
        },
        altdata_snapshot=None,
        risk_decision=None,
        trainer_output={
            "selected_action": v2_action,
            "expected_move_after_cost_bps": expected_move_after_cost_bps,
        },
        paper_gate_decision={
            "paper_fill_allowed": paper_fill_allowed,
            "paper_fill_gate_block_reasons": block_reasons or [],
            "latency_seconds": latency_seconds,
        },
        orchestrator_decision={},
        paper_intent={"symbol": symbol, "decision": paper_intent_decision} if paper_intent_decision else None,
        legacy_reference_action={"action": legacy_action} if legacy_action else None,
        future_outcomes=_outcomes(after_cost_5m, stop_hit=stop_hit, drawdown_5m=drawdown_5m),
        outcome_after_cost=after_cost_5m,
        label=label,
    )


def test_canonical_schema_lists_all_required_fields_and_labels() -> None:
    schema = emit_canonical_schema()
    assert schema["schema_version"] == REPLAY_BUNDLE_SCHEMA_VERSION
    required_fields = {
        "feature_snapshot_id",
        "prediction_id",
        "symbol",
        "timeframe",
        "generated_at",
        "features_hash",
        "market_snapshot",
        "altdata_snapshot",
        "risk_decision",
        "trainer_output",
        "paper_gate_decision",
        "orchestrator_decision",
        "paper_intent",
        "legacy_reference_action",
        "future_outcomes",
        "outcome_after_cost",
        "label",
    }
    assert required_fields.issubset(schema["bundle_fields"])
    assert {"correct_trade", "correct_no_trade", "false_positive", "false_negative", "false_block", "insufficient_evidence"} == set(schema["labels"])
    window_ids = {w["window_id"] for w in schema["future_outcomes_windows"]}
    assert {"1m", "5m", "15m", "1h"} == window_ids
    assert schema["live_gate"] == "blocked_human_only"
    assert schema["live_symbols"] == []
    assert schema["approves_live"] is False
    assert schema["approves_canary"] is False
    assert schema["approves_legacy_shutdown"] is False
    assert schema["approves_redis_trim"] is False
    assert schema["default_thresholds"]["preliminary_only_for_analysis"] is True
    assert schema["default_thresholds"]["no_live_approval_implied"] is True


def test_evaluator_default_thresholds_never_claim_edge() -> None:
    bundles = [_bundle(after_cost_5m=10.0, paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL") for _ in range(50)]
    summary = evaluate(bundles)
    assert summary.verdict == "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
    assert "OPERATOR_DECISION_REQUIRED" in summary.verdict_reason
    out = summary_to_dict(summary)
    assert out["approves_live"] is False
    assert out["approves_canary"] is False
    assert out["approves_legacy_shutdown"] is False
    assert out["approves_redis_trim"] is False
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []


def test_evaluator_with_numeric_thresholds_still_blocked_if_threshold_fails() -> None:
    bundles = [_bundle(after_cost_5m=-10.0, paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL") for _ in range(50)]
    thresholds = {
        "min_sample_count": 30,
        "min_after_cost_expectancy_bps": 5.0,
        "min_after_cost_lower_ci_bps": 0.0,
        "max_drawdown_bps_rolling": 500.0,
        "min_downside_pre_cascade_recall": 0.5,
        "max_false_positive_rate": 0.2,
        "max_false_negative_rate": 0.2,
        "min_v2_vs_legacy_action_match_rate": 0.5,
    }
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_NOT_PROVEN"


def test_evaluator_classifies_labels_correctly() -> None:
    # 10 correct trades, 5 false positives, 5 correct no-trade,
    # 3 false negatives, 2 false blocks.
    bundles: list[ReplayBundle] = []
    bundles += [
        _bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL",
                after_cost_5m=20.0) for _ in range(10)
    ]
    bundles += [
        _bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL",
                after_cost_5m=-10.0) for _ in range(5)
    ]
    bundles += [
        _bundle(paper_fill_allowed=False, after_cost_5m=-15.0) for _ in range(5)
    ]
    bundles += [
        _bundle(paper_fill_allowed=False, after_cost_5m=12.0) for _ in range(3)
    ]
    bundles += [
        _bundle(paper_fill_allowed=False, paper_intent_decision="HELD_BY_PAPER_FILL_GATE",
                block_reasons=["FEE_GATE_BLOCKED"], after_cost_5m=18.0) for _ in range(2)
    ]
    summary = evaluate(bundles)
    # Conservative verdict still holds because thresholds are operator-pending.
    assert summary.verdict == "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
    assert summary.no_trade_correct_count == 5
    assert summary.false_block_count == 2
    # FP rate = false_positive / (correct_trade + false_positive) = 5 / 15
    assert summary.false_positive_rate == pytest.approx(5 / 15, rel=1e-6)
    # FN rate = false_negative / (correct_no_trade + false_negative + false_block) = 3 / (5+3+2) = 0.3
    assert summary.false_negative_rate == pytest.approx(0.3, rel=1e-6)


def test_evaluator_pre_cascade_recall_when_v2_warns_on_shock() -> None:
    bundles: list[ReplayBundle] = []
    # 4 pre-cascade events, V2 warns on 3 of them (one via block, two via
    # negative expected-move-after-cost).
    bundles.append(_bundle(paper_fill_allowed=False, paper_intent_decision="HELD_BY_PAPER_FILL_GATE", block_reasons=["NEGATIVE_EXPECTED_MOVE_AFTER_COST"], after_cost_5m=-300.0, stop_hit=True))
    bundles.append(_bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL", expected_move_after_cost_bps=-12.0, after_cost_5m=-250.0))
    bundles.append(_bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL", expected_move_after_cost_bps=-3.0, after_cost_5m=-220.0))
    # one pre-cascade NOT warned (false negative for warning)
    bundles.append(_bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL", expected_move_after_cost_bps=5.0, after_cost_5m=-260.0))
    # 2 non-events V2 did warn on (false positives for warning) — block
    # reasons required because the evaluator only treats explicit gate
    # blocks as warnings, not "paper_fill_allowed=False with no reason".
    bundles.append(_bundle(paper_fill_allowed=False, after_cost_5m=10.0, block_reasons=["FEE_GATE_BLOCKED"]))
    bundles.append(_bundle(paper_fill_allowed=False, after_cost_5m=4.0, block_reasons=["CHURN_BLOCKED"]))
    summary = evaluate(bundles)
    # recall = warned-pre-cascade / total-pre-cascade = 3/4 = 0.75
    assert summary.downside_pre_cascade_recall == pytest.approx(0.75, rel=1e-6)
    # precision = warned-pre-cascade / total-warnings = 3 / (3 warnings + 2 false-warning) = 3/5 = 0.6
    assert summary.downside_pre_cascade_precision == pytest.approx(0.6, rel=1e-6)


def test_evaluator_v2_vs_legacy_match_rate_when_legacy_reference_present() -> None:
    bundles = [
        _bundle(v2_action="long", legacy_action="long"),
        _bundle(v2_action="hold", legacy_action="long"),
        _bundle(v2_action="hold", legacy_action="hold"),
        _bundle(v2_action="long", legacy_action="long"),
    ]
    summary = evaluate(bundles)
    # 3 matches out of 4 comparisons.
    assert summary.v2_vs_legacy_action_match_rate == pytest.approx(0.75, rel=1e-6)


def test_evaluator_hold_due_checkpoint_and_strict_gate_counts() -> None:
    bundles = [
        _bundle(paper_fill_allowed=False, paper_intent_decision="HELD_BY_PAPER_FILL_GATE",
                block_reasons=["CHECKPOINT_REQUIRED"]),
        _bundle(paper_fill_allowed=False, paper_intent_decision="HELD_BY_PAPER_FILL_GATE",
                block_reasons=["STRICT_GATE_BLOCKED"]),
        _bundle(paper_fill_allowed=False, paper_intent_decision="HELD_BY_PAPER_FILL_GATE",
                block_reasons=["FEE_GATE_BLOCKED", "CHURN_BLOCKED"]),
        _bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL"),
    ]
    summary = evaluate(bundles)
    assert summary.v2_hold_due_checkpoint_count == 1
    assert summary.v2_hold_due_strict_gate_count == 2


def test_evaluator_full_pass_only_when_every_numeric_threshold_satisfied() -> None:
    # 50 winning trades, every threshold easy to satisfy.
    bundles = [
        _bundle(paper_fill_allowed=True, paper_intent_decision="ACCEPTED_PAPER_FILL", after_cost_5m=25.0, v2_action="long", legacy_action="long")
        for _ in range(50)
    ]
    thresholds = {
        "min_sample_count": 30,
        "min_after_cost_expectancy_bps": 10.0,
        "min_after_cost_lower_ci_bps": 0.0,
        "max_drawdown_bps_rolling": 1000.0,
        "min_downside_pre_cascade_recall": 0.0,  # no pre-cascade events
        "max_false_positive_rate": 0.5,
        "max_false_negative_rate": 0.5,
        "min_v2_vs_legacy_action_match_rate": 0.5,
    }
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_PROVISIONAL_PAPER_PASS"
    assert "every operator-set" in summary.verdict_reason
    out = summary_to_dict(summary)
    # Even on PASS, the evaluator never approves live / canary / shutdown.
    assert out["approves_live"] is False
    assert out["approves_canary"] is False
    assert out["approves_legacy_shutdown"] is False
    assert out["approves_redis_trim"] is False
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []


def test_default_thresholds_are_operator_decision_required() -> None:
    for key in (
        "min_sample_count",
        "min_after_cost_expectancy_bps",
        "min_after_cost_lower_ci_bps",
        "max_drawdown_bps_rolling",
        "min_downside_pre_cascade_recall",
        "max_false_positive_rate",
        "max_false_negative_rate",
    ):
        assert DEFAULT_THRESHOLDS[key] == "OPERATOR_DECISION_REQUIRED", key
    assert DEFAULT_THRESHOLDS["preliminary_only_for_analysis"] is True
    assert DEFAULT_THRESHOLDS["no_live_approval_implied"] is True


# ─────────────────────────────────────────────────────────────────────
# Codex remediation: max_drawdown_bps_rolling enforcement + structured
# threshold_evidence per evaluator threshold enforcement remediation.
# ─────────────────────────────────────────────────────────────────────

_BASE_NUMERIC_THRESHOLDS = {
    "min_sample_count": 30,
    "min_after_cost_expectancy_bps": 10.0,
    "min_after_cost_lower_ci_bps": 0.0,
    "min_downside_pre_cascade_recall": 0.0,
    "max_false_positive_rate": 0.5,
    "max_false_negative_rate": 0.5,
    "min_v2_vs_legacy_action_match_rate": 0.5,
}


def _winning_bundles(n: int = 50, drawdown_5m: float | None = 30.0):
    return [
        _bundle(
            paper_fill_allowed=True,
            paper_intent_decision="ACCEPTED_PAPER_FILL",
            after_cost_5m=25.0,
            v2_action="long",
            legacy_action="long",
            drawdown_5m=drawdown_5m,
        )
        for _ in range(n)
    ]


def test_drawdown_threshold_operator_pending_blocks_provisional_pass() -> None:
    bundles = _winning_bundles()
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS)
    # max_drawdown_bps_rolling left at default OPERATOR_DECISION_REQUIRED
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
    by_name = {ev["threshold_name"]: ev for ev in summary.threshold_evidence}
    assert by_name["max_drawdown_bps_rolling"]["evidence_state"] == "OPERATOR_DECISION_REQUIRED"


def test_drawdown_threshold_missing_observation_blocks_provisional_pass() -> None:
    # Drawdown numeric, but every bundle has drawdown_bps=None -> no
    # observed evidence -> INSUFFICIENT_EVIDENCE -> not provisional pass.
    bundles = _winning_bundles(drawdown_5m=None)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=1000.0)
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_NOT_PROVEN"
    by_name = {ev["threshold_name"]: ev for ev in summary.threshold_evidence}
    assert by_name["max_drawdown_bps_rolling"]["evidence_state"] == "INSUFFICIENT_EVIDENCE"
    assert by_name["max_drawdown_bps_rolling"]["passed"] is False


def test_drawdown_threshold_numeric_observed_exceeds_cap_blocks_provisional_pass() -> None:
    bundles = _winning_bundles(drawdown_5m=500.0)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=200.0)
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_NOT_PROVEN"
    by_name = {ev["threshold_name"]: ev for ev in summary.threshold_evidence}
    assert by_name["max_drawdown_bps_rolling"]["evidence_state"] == "NUMERIC_CHECK_FAILED"
    assert by_name["max_drawdown_bps_rolling"]["passed"] is False
    assert summary.max_drawdown_bps_observed == pytest.approx(500.0, rel=1e-6)


def test_provisional_pass_only_when_all_seven_required_thresholds_pass_numerically() -> None:
    bundles = _winning_bundles(drawdown_5m=30.0)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=200.0)
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_PROVISIONAL_PAPER_PASS"
    required = (
        "min_sample_count",
        "min_after_cost_expectancy_bps",
        "min_after_cost_lower_ci_bps",
        "max_drawdown_bps_rolling",
        "min_downside_pre_cascade_recall",
        "max_false_positive_rate",
        "max_false_negative_rate",
    )
    by_name = {ev["threshold_name"]: ev for ev in summary.threshold_evidence}
    for n in required:
        assert by_name[n]["evidence_state"] == "NUMERIC_CHECK_PASSED", n
        assert by_name[n]["passed"] is True, n


def test_invalid_threshold_value_blocks_provisional_pass() -> None:
    bundles = _winning_bundles(drawdown_5m=30.0)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=float("nan"))
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
    by_name = {ev["threshold_name"]: ev for ev in summary.threshold_evidence}
    assert by_name["max_drawdown_bps_rolling"]["evidence_state"] == "INVALID_THRESHOLD"


def test_threshold_evidence_records_expected_fields_per_row() -> None:
    bundles = _winning_bundles(drawdown_5m=30.0)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=200.0)
    summary = evaluate(bundles, thresholds=thresholds)
    for ev in summary.threshold_evidence:
        for k in ("threshold_name", "threshold_value", "observed_value", "passed", "evidence_state"):
            assert k in ev, (ev, k)
        assert ev["evidence_state"] in {
            "NUMERIC_CHECK_PASSED",
            "NUMERIC_CHECK_FAILED",
            "OPERATOR_DECISION_REQUIRED",
            "INSUFFICIENT_EVIDENCE",
            "INVALID_THRESHOLD",
        }


def test_evaluator_approvals_remain_false_on_provisional_paper_pass() -> None:
    bundles = _winning_bundles(drawdown_5m=30.0)
    thresholds = dict(_BASE_NUMERIC_THRESHOLDS, max_drawdown_bps_rolling=200.0)
    summary = evaluate(bundles, thresholds=thresholds)
    assert summary.verdict == "EDGE_PROVISIONAL_PAPER_PASS"
    out = summary_to_dict(summary)
    assert out["approves_live"] is False
    assert out["approves_canary"] is False
    assert out["approves_legacy_shutdown"] is False
    assert out["approves_redis_trim"] is False
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []


def test_default_cost_model_contains_operator_decision_required_literal() -> None:
    from v2.backend.app.services.edge_proof.replay_schema import emit_canonical_schema as _emit
    schema = _emit()
    cost = schema.get("default_cost_model") or {}
    assert "OPERATOR_DECISION_REQUIRED" in cost.get("cost_model_source", "")
    assert cost.get("operator_override_required") is True
    assert cost.get("operator_decision_required") is True
    assert cost.get("fee_drag_bps", 0) > 0
    assert cost.get("slippage_estimate_bps", -1) >= 0
