"""V2 Native Edge-Proof — replay evaluator.

Pure functions that consume a sequence of ``ReplayBundle`` objects
and produce the canonical edge-proof metric summary required by
``V2_NATIVE_EDGE_PROOF_SPEC_AND_REPLAY_EVALUATOR_READY``.

The evaluator is deliberately conservative:

- it never claims edge unless every operator-set threshold is satisfied;
- when thresholds are still ``OPERATOR_DECISION_REQUIRED`` (the default
  state of this packet), the verdict is always
  ``EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED``;
- no live / canary / shutdown action is implied by any metric;
- no Redis write, no exchange call, no approval marker.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .replay_schema import (
    DEFAULT_THRESHOLDS,
    OUTCOME_WINDOWS_SECONDS,
    ReplayBundle,
    ReplayLabel,
)


PRIMARY_OUTCOME_WINDOW_ID = "5m"


@dataclass(frozen=True)
class MetricSummary:
    """Canonical metric summary the evaluator emits."""

    sample_count: int
    minimum_sample_satisfied: bool

    # After-cost edge metrics
    after_cost_pnl_delta: float | None
    expected_move_after_cost_bps: float | None
    after_cost_ci_lower_bps: float | None
    after_cost_ci_upper_bps: float | None
    fee_drag_bps: float | None
    slippage_estimate_bps: float | None

    # Classification metrics
    false_positive_rate: float | None
    false_negative_rate: float | None
    no_trade_correct_count: int
    false_block_count: int

    # Downside / cascade
    downside_pre_cascade_recall: float | None
    downside_pre_cascade_precision: float | None

    # Latency / gate behavior
    average_latency_to_signal_seconds: float | None
    gate_block_reason_distribution: dict[str, int]

    # Comparator
    v2_vs_legacy_action_match_rate: float | None
    v2_hold_due_checkpoint_count: int
    v2_hold_due_strict_gate_count: int

    # Drawdown (worst observed across all bundles' all windows)
    max_drawdown_bps_observed: float | None

    # Verdict
    verdict: str
    verdict_reason: str
    thresholds_used: Mapping[str, Any]
    thresholds_satisfied: dict[str, bool | str]
    threshold_evidence: list[dict[str, Any]]

    # Safety
    live_gate: str = "blocked_human_only"
    live_symbols: tuple[str, ...] = field(default_factory=tuple)
    approves_live: bool = False
    approves_canary: bool = False
    approves_legacy_shutdown: bool = False
    approves_redis_trim: bool = False


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _bootstrap_mean_ci(
    values: Sequence[float], iters: int = 2000, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Return (mean, lower_ci, upper_ci) via percentile bootstrap.

    Pure / deterministic-ish: uses ``statistics.fmean`` on bootstrap
    resamples drawn from ``values`` with replacement. Falls back to
    point estimates when ``values`` is too small.
    """
    if not values:
        return (0.0, 0.0, 0.0)
    if len(values) < 5:
        m = statistics.fmean(values)
        return (m, m, m)
    # Deterministic seeded resampling to keep CI reproducible for tests.
    import random
    rng = random.Random(0xED6E_5EED)  # spelled out: "edge seed"
    n = len(values)
    means: list[float] = []
    for _ in range(iters):
        sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(statistics.fmean(sample))
    means.sort()
    lo_idx = int(iters * (alpha / 2))
    hi_idx = int(iters * (1 - alpha / 2))
    return (
        statistics.fmean(values),
        means[max(0, min(lo_idx, iters - 1))],
        means[max(0, min(hi_idx, iters - 1))],
    )


def _is_trade(bundle: ReplayBundle) -> bool:
    """A bundle counts as a "would-be trade" if the paper gate or the
    paper intent indicates the trade would have been taken.
    """
    intent = bundle.paper_intent or {}
    decision = (intent.get("decision") or "").upper()
    if decision in ("ACCEPTED_PAPER_FILL",):
        return True
    gate = bundle.paper_gate_decision or {}
    return bool(gate.get("paper_fill_allowed"))


def _is_blocked(bundle: ReplayBundle) -> bool:
    """The bundle is "blocked" only with explicit block evidence:
    paper-intent decision in (HELD_BY_PAPER_FILL_GATE, BLOCKED), OR
    paper_fill_allowed is False with at least one block_reason.

    ``paper_fill_allowed=False`` with no block reasons is treated as
    "model held / no trade" (not a gate block) so the bundle is not
    misclassified as FALSE_BLOCK when the truth is FALSE_NEGATIVE /
    CORRECT_NO_TRADE.
    """
    intent = bundle.paper_intent or {}
    decision = (intent.get("decision") or "").upper()
    if decision in ("HELD_BY_PAPER_FILL_GATE", "BLOCKED"):
        return True
    gate = bundle.paper_gate_decision or {}
    if gate.get("paper_fill_allowed") is False:
        reasons = gate.get("paper_fill_gate_block_reasons") or []
        if reasons:
            return True
    return False


def _block_reasons(bundle: ReplayBundle) -> list[str]:
    gate = bundle.paper_gate_decision or {}
    intent = bundle.paper_intent or {}
    reasons: list[str] = []
    for source in (gate.get("paper_fill_gate_block_reasons"), intent.get("paper_fill_gate_block_reasons")):
        if isinstance(source, list):
            reasons.extend(str(r) for r in source)
    return reasons


def _legacy_action(bundle: ReplayBundle) -> str | None:
    ref = bundle.legacy_reference_action or {}
    action = ref.get("action") or ref.get("selected_action")
    if isinstance(action, str):
        return action.lower()
    return None


def _v2_action(bundle: ReplayBundle) -> str:
    trainer = bundle.trainer_output or {}
    selected = trainer.get("selected_action")
    if isinstance(selected, str):
        return selected.lower()
    return "hold" if not _is_trade(bundle) else "long_or_short"


def _v2_hold_reasons(bundle: ReplayBundle) -> tuple[bool, bool]:
    """(checkpoint_hold, strict_gate_hold) — paper-fill block reasons."""
    reasons = _block_reasons(bundle)
    checkpoint = any("checkpoint" in r.lower() for r in reasons)
    strict_gate = any(
        any(token in r.lower() for token in (
            "strict_gate", "fee_gate", "churn", "feature_freshness",
            "edge_below_threshold", "negative_expected_move_after_cost",
        ))
        for r in reasons
    )
    return checkpoint, strict_gate


def _classify(bundle: ReplayBundle, outcome_window: str) -> ReplayLabel:
    """Recompute the objective label from the realized after-cost
    outcome in ``outcome_window``. If the bundle already carries a
    non-INSUFFICIENT_EVIDENCE label we trust that; otherwise we
    classify against the realized after-cost return sign.
    """
    if bundle.label != ReplayLabel.INSUFFICIENT_EVIDENCE:
        return bundle.label
    outcome = bundle.future_outcomes.get(outcome_window)
    after_cost = outcome.after_cost_return_bps if outcome else None
    if after_cost is None:
        return ReplayLabel.INSUFFICIENT_EVIDENCE
    traded = _is_trade(bundle)
    blocked = _is_blocked(bundle)
    if traded and after_cost > 0:
        return ReplayLabel.CORRECT_TRADE
    if traded and after_cost <= 0:
        return ReplayLabel.FALSE_POSITIVE
    if not traded and not blocked and after_cost <= 0:
        return ReplayLabel.CORRECT_NO_TRADE
    if not traded and not blocked and after_cost > 0:
        return ReplayLabel.FALSE_NEGATIVE
    if blocked and after_cost > 0:
        return ReplayLabel.FALSE_BLOCK
    if blocked and after_cost <= 0:
        return ReplayLabel.CORRECT_NO_TRADE
    return ReplayLabel.INSUFFICIENT_EVIDENCE


def _is_pre_cascade(bundle: ReplayBundle) -> bool:
    """A bundle is a pre-cascade-shock instance if the future outcome
    crosses a liquidation/stop level or drops more than 200 bps after
    cost in the primary window.
    """
    outcome = bundle.future_outcomes.get(PRIMARY_OUTCOME_WINDOW_ID)
    if outcome is None:
        return False
    if outcome.stop_hit:
        return True
    if outcome.after_cost_return_bps is not None and outcome.after_cost_return_bps <= -200:
        return True
    return False


def _v2_warning(bundle: ReplayBundle) -> bool:
    """V2 issued a downside warning if it blocked the trade or if
    its trainer output's expected_move_after_cost_bps is negative.
    """
    if _is_blocked(bundle):
        return True
    trainer = bundle.trainer_output or {}
    em_after = _coerce_float(trainer.get("expected_move_after_cost_bps"))
    return em_after is not None and em_after < 0


def evaluate(
    bundles: Sequence[ReplayBundle],
    *,
    thresholds: Mapping[str, Any] | None = None,
    outcome_window: str = PRIMARY_OUTCOME_WINDOW_ID,
) -> MetricSummary:
    """Compute the canonical metric summary over ``bundles``.

    The verdict is always conservative: it can only become
    ``EDGE_PROVISIONAL_PAPER_PASS`` when every threshold is a concrete
    numeric and every check passes. While any threshold remains
    ``OPERATOR_DECISION_REQUIRED`` the verdict is
    ``EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED``.
    """
    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        thr.update(thresholds)

    sample_count = len(bundles)
    min_sample = thr.get("min_sample_count")
    min_sample_satisfied = isinstance(min_sample, int) and sample_count >= min_sample

    after_cost_returns: list[float] = []
    fee_estimates: list[float] = []
    slippage_estimates: list[float] = []
    latencies: list[float] = []
    classified: list[ReplayLabel] = []
    pre_cascade_total = 0
    pre_cascade_v2_warned = 0
    v2_warning_total = 0
    pre_cascade_with_warning = 0
    legacy_match = 0
    legacy_compared = 0
    hold_checkpoint = 0
    hold_strict = 0
    block_reasons_counter: Counter[str] = Counter()

    for b in bundles:
        # After-cost return on the primary window.
        outcome = b.future_outcomes.get(outcome_window)
        if outcome and outcome.after_cost_return_bps is not None:
            after_cost_returns.append(float(outcome.after_cost_return_bps))

        # Fee and slippage estimates from market snapshot if present.
        m = b.market_snapshot or {}
        fee = _coerce_float(m.get("fee_bps"))
        if fee is not None:
            fee_estimates.append(fee)
        slip = _coerce_float(m.get("slippage_estimate_bps"))
        if slip is not None:
            slippage_estimates.append(slip)

        # Latency from prediction generation to paper-fill-gate decision.
        gate = b.paper_gate_decision or {}
        latency = _coerce_float(gate.get("latency_seconds"))
        if latency is not None:
            latencies.append(latency)

        # Classification + block reasons.
        label = _classify(b, outcome_window)
        classified.append(label)
        if _is_blocked(b):
            for r in _block_reasons(b):
                block_reasons_counter[r] += 1
        ck, st = _v2_hold_reasons(b)
        if ck:
            hold_checkpoint += 1
        if st:
            hold_strict += 1

        # Pre-cascade recall / precision.
        is_pc = _is_pre_cascade(b)
        warned = _v2_warning(b)
        if is_pc:
            pre_cascade_total += 1
            if warned:
                pre_cascade_v2_warned += 1
        if warned:
            v2_warning_total += 1
            if is_pc:
                pre_cascade_with_warning += 1

        # V2-vs-legacy comparator.
        legacy = _legacy_action(b)
        if legacy is not None:
            legacy_compared += 1
            if legacy == _v2_action(b):
                legacy_match += 1

    label_counts = Counter(label.value for label in classified)
    correct_trade = label_counts.get(ReplayLabel.CORRECT_TRADE.value, 0)
    correct_no_trade = label_counts.get(ReplayLabel.CORRECT_NO_TRADE.value, 0)
    false_positive = label_counts.get(ReplayLabel.FALSE_POSITIVE.value, 0)
    false_negative = label_counts.get(ReplayLabel.FALSE_NEGATIVE.value, 0)
    false_block = label_counts.get(ReplayLabel.FALSE_BLOCK.value, 0)
    insufficient = label_counts.get(ReplayLabel.INSUFFICIENT_EVIDENCE.value, 0)

    classified_total = correct_trade + correct_no_trade + false_positive + false_negative + false_block
    pos_predicted = correct_trade + false_positive
    neg_predicted = correct_no_trade + false_negative + false_block
    false_positive_rate = (
        false_positive / pos_predicted if pos_predicted > 0 else None
    )
    false_negative_rate = (
        false_negative / neg_predicted if neg_predicted > 0 else None
    )

    after_cost_pnl_delta = (
        statistics.fmean(after_cost_returns) if after_cost_returns else None
    )
    expected_move_after_cost_bps = after_cost_pnl_delta
    fee_drag = (
        statistics.fmean(fee_estimates) if fee_estimates else None
    )
    slip_drag = (
        statistics.fmean(slippage_estimates) if slippage_estimates else None
    )
    if after_cost_returns:
        _mean, ci_lo, ci_hi = _bootstrap_mean_ci(after_cost_returns)
    else:
        ci_lo = None  # type: ignore[assignment]
        ci_hi = None  # type: ignore[assignment]

    downside_recall = (
        pre_cascade_v2_warned / pre_cascade_total
        if pre_cascade_total > 0
        else None
    )
    downside_precision = (
        pre_cascade_with_warning / v2_warning_total
        if v2_warning_total > 0
        else None
    )
    avg_latency = (
        statistics.fmean(latencies) if latencies else None
    )
    legacy_match_rate = (
        legacy_match / legacy_compared if legacy_compared > 0 else None
    )

    # Worst observed drawdown across every bundle's every outcome window.
    # ``drawdown_bps`` is the positive magnitude of the most adverse
    # excursion inside a window. None means the miner could not derive
    # a drawdown for that window (typically insufficient evidence).
    observed_drawdowns: list[float] = []
    for b in bundles:
        for outcome in b.future_outcomes.values():
            dd = _coerce_float(getattr(outcome, "drawdown_bps", None))
            if dd is not None:
                observed_drawdowns.append(abs(dd))
    max_drawdown_bps_observed = (
        max(observed_drawdowns) if observed_drawdowns else None
    )

    # Threshold satisfaction checks. Any required threshold still
    # OPERATOR_DECISION_REQUIRED / missing / invalid means we cannot
    # claim edge. The verdict can only become EDGE_PROVISIONAL_PAPER_PASS
    # when every required threshold is a finite numeric and every
    # corresponding numeric check passes against real observed evidence.

    REQUIRED_THRESHOLDS: tuple[str, ...] = (
        "min_sample_count",
        "min_after_cost_expectancy_bps",
        "min_after_cost_lower_ci_bps",
        "max_drawdown_bps_rolling",
        "min_downside_pre_cascade_recall",
        "max_false_positive_rate",
        "max_false_negative_rate",
    )

    # Rate-style thresholds are vacuously satisfied when there is no
    # data to evaluate (e.g. zero negative-class predictions). Hard
    # safety thresholds (expectancy / CI / drawdown / sample count)
    # are NEVER vacuously satisfied — missing data fails them and
    # marks evidence INSUFFICIENT_EVIDENCE.
    VACUOUS_ON_NONE = {
        "max_false_positive_rate",
        "max_false_negative_rate",
        "min_downside_pre_cascade_recall",
        "min_v2_vs_legacy_action_match_rate",
    }

    def _threshold_evidence(
        name: str,
        observed: float | int | None,
        comparator: str,
    ) -> dict[str, Any]:
        target = thr.get(name)
        # Operator pending (literal string OPERATOR_DECISION_REQUIRED or
        # any non-numeric string).
        if isinstance(target, str):
            return {
                "threshold_name": name,
                "threshold_value": target,
                "observed_value": observed,
                "passed": False,
                "evidence_state": "OPERATOR_DECISION_REQUIRED",
            }
        # Numeric guard: None / NaN / non-finite / non-numeric all
        # invalidate the threshold.
        target_num = _coerce_float(target)
        if target_num is None or math.isnan(target_num) or math.isinf(target_num):
            return {
                "threshold_name": name,
                "threshold_value": target,
                "observed_value": observed,
                "passed": False,
                "evidence_state": "INVALID_THRESHOLD",
            }
        if observed is None:
            if name in VACUOUS_ON_NONE:
                return {
                    "threshold_name": name,
                    "threshold_value": target_num,
                    "observed_value": None,
                    "passed": True,
                    "evidence_state": "NUMERIC_CHECK_PASSED",
                }
            return {
                "threshold_name": name,
                "threshold_value": target_num,
                "observed_value": None,
                "passed": False,
                "evidence_state": "INSUFFICIENT_EVIDENCE",
            }
        ok = (
            observed >= target_num if comparator == ">=" else observed <= target_num
        )
        return {
            "threshold_name": name,
            "threshold_value": target_num,
            "observed_value": observed,
            "passed": bool(ok),
            "evidence_state": (
                "NUMERIC_CHECK_PASSED" if ok else "NUMERIC_CHECK_FAILED"
            ),
        }

    threshold_evidence: list[dict[str, Any]] = []
    # 1. sample count
    sc_target = thr.get("min_sample_count")
    if isinstance(sc_target, str):
        threshold_evidence.append({
            "threshold_name": "min_sample_count",
            "threshold_value": sc_target,
            "observed_value": sample_count,
            "passed": False,
            "evidence_state": "OPERATOR_DECISION_REQUIRED",
        })
    else:
        sc_num = _coerce_float(sc_target)
        if sc_num is None or math.isnan(sc_num) or math.isinf(sc_num):
            threshold_evidence.append({
                "threshold_name": "min_sample_count",
                "threshold_value": sc_target,
                "observed_value": sample_count,
                "passed": False,
                "evidence_state": "INVALID_THRESHOLD",
            })
        else:
            ok = sample_count >= int(sc_num)
            threshold_evidence.append({
                "threshold_name": "min_sample_count",
                "threshold_value": int(sc_num),
                "observed_value": sample_count,
                "passed": ok,
                "evidence_state": (
                    "NUMERIC_CHECK_PASSED" if ok else "NUMERIC_CHECK_FAILED"
                ),
            })
    # 2. after-cost expectancy + lower CI
    threshold_evidence.append(_threshold_evidence(
        "min_after_cost_expectancy_bps",
        expected_move_after_cost_bps,
        ">=",
    ))
    threshold_evidence.append(_threshold_evidence(
        "min_after_cost_lower_ci_bps",
        ci_lo if after_cost_returns else None,
        ">=",
    ))
    # 3. drawdown — observed must NOT exceed the cap; missing observed
    #    when threshold is numeric is INSUFFICIENT_EVIDENCE.
    threshold_evidence.append(_threshold_evidence(
        "max_drawdown_bps_rolling",
        max_drawdown_bps_observed,
        "<=",
    ))
    # 4. downside pre-cascade recall + classification rates
    threshold_evidence.append(_threshold_evidence(
        "min_downside_pre_cascade_recall",
        downside_recall,
        ">=",
    ))
    threshold_evidence.append(_threshold_evidence(
        "max_false_positive_rate",
        false_positive_rate,
        "<=",
    ))
    threshold_evidence.append(_threshold_evidence(
        "max_false_negative_rate",
        false_negative_rate,
        "<=",
    ))

    # Compact mirror for legacy consumers — still distinguishes between
    # operator-pending, insufficient evidence, invalid, and concrete
    # pass/fail.
    thresholds_satisfied: dict[str, bool | str] = {}
    for ev in threshold_evidence:
        if ev["evidence_state"] == "NUMERIC_CHECK_PASSED":
            thresholds_satisfied[ev["threshold_name"]] = True
        elif ev["evidence_state"] == "NUMERIC_CHECK_FAILED":
            thresholds_satisfied[ev["threshold_name"]] = False
        else:
            thresholds_satisfied[ev["threshold_name"]] = ev["evidence_state"]
    # Informational comparator only — never gates the verdict.
    thresholds_satisfied["min_v2_vs_legacy_action_match_rate"] = (
        "INFORMATIONAL_ONLY"
    )

    by_name = {ev["threshold_name"]: ev for ev in threshold_evidence}
    any_operator_pending = any(
        by_name[n]["evidence_state"] == "OPERATOR_DECISION_REQUIRED"
        for n in REQUIRED_THRESHOLDS
    )
    any_invalid = any(
        by_name[n]["evidence_state"] == "INVALID_THRESHOLD"
        for n in REQUIRED_THRESHOLDS
    )
    any_insufficient = any(
        by_name[n]["evidence_state"] == "INSUFFICIENT_EVIDENCE"
        for n in REQUIRED_THRESHOLDS
    )
    all_required_passed = all(
        by_name[n]["evidence_state"] == "NUMERIC_CHECK_PASSED"
        for n in REQUIRED_THRESHOLDS
    )
    sample_passed = by_name["min_sample_count"]["evidence_state"] == "NUMERIC_CHECK_PASSED"

    if any_operator_pending:
        verdict = "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
        verdict_reason = (
            "one or more required thresholds are still OPERATOR_DECISION_REQUIRED;"
            " no edge claim is permitted until the operator sets concrete numerics"
        )
    elif any_invalid:
        verdict = "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
        verdict_reason = (
            "one or more required thresholds carry a non-finite or"
            " non-numeric value; treating as operator decision required"
        )
    elif not sample_passed:
        verdict = "EDGE_NOT_PROVEN_INSUFFICIENT_SAMPLES"
        verdict_reason = "sample count below operator-set minimum"
    elif any_insufficient:
        verdict = "EDGE_NOT_PROVEN"
        verdict_reason = (
            "one or more required thresholds have no observed evidence yet"
        )
    elif not all_required_passed:
        verdict = "EDGE_NOT_PROVEN"
        verdict_reason = "at least one required numeric threshold failed; edge not proven"
    else:
        verdict = "EDGE_PROVISIONAL_PAPER_PASS"
        verdict_reason = (
            "every operator-set required threshold is satisfied in paper/shadow;"
            " this is NOT a live or canary approval"
        )

    return MetricSummary(
        sample_count=sample_count,
        minimum_sample_satisfied=bool(min_sample_satisfied),
        after_cost_pnl_delta=after_cost_pnl_delta,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        after_cost_ci_lower_bps=ci_lo if after_cost_returns else None,
        after_cost_ci_upper_bps=ci_hi if after_cost_returns else None,
        fee_drag_bps=fee_drag,
        slippage_estimate_bps=slip_drag,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        no_trade_correct_count=correct_no_trade,
        false_block_count=false_block,
        downside_pre_cascade_recall=downside_recall,
        downside_pre_cascade_precision=downside_precision,
        average_latency_to_signal_seconds=avg_latency,
        gate_block_reason_distribution=dict(block_reasons_counter),
        v2_vs_legacy_action_match_rate=legacy_match_rate,
        v2_hold_due_checkpoint_count=hold_checkpoint,
        v2_hold_due_strict_gate_count=hold_strict,
        max_drawdown_bps_observed=max_drawdown_bps_observed,
        verdict=verdict,
        verdict_reason=verdict_reason,
        thresholds_used=dict(thr),
        thresholds_satisfied=thresholds_satisfied,
        threshold_evidence=threshold_evidence,
    )


def summary_to_dict(summary: MetricSummary) -> dict[str, Any]:
    return {
        "sample_count": summary.sample_count,
        "minimum_sample_satisfied": summary.minimum_sample_satisfied,
        "after_cost_pnl_delta": summary.after_cost_pnl_delta,
        "expected_move_after_cost_bps": summary.expected_move_after_cost_bps,
        "after_cost_ci_lower_bps": summary.after_cost_ci_lower_bps,
        "after_cost_ci_upper_bps": summary.after_cost_ci_upper_bps,
        "fee_drag_bps": summary.fee_drag_bps,
        "slippage_estimate_bps": summary.slippage_estimate_bps,
        "false_positive_rate": summary.false_positive_rate,
        "false_negative_rate": summary.false_negative_rate,
        "no_trade_correct_count": summary.no_trade_correct_count,
        "false_block_count": summary.false_block_count,
        "downside_pre_cascade_recall": summary.downside_pre_cascade_recall,
        "downside_pre_cascade_precision": summary.downside_pre_cascade_precision,
        "average_latency_to_signal_seconds": summary.average_latency_to_signal_seconds,
        "gate_block_reason_distribution": dict(summary.gate_block_reason_distribution),
        "v2_vs_legacy_action_match_rate": summary.v2_vs_legacy_action_match_rate,
        "v2_hold_due_checkpoint_count": summary.v2_hold_due_checkpoint_count,
        "v2_hold_due_strict_gate_count": summary.v2_hold_due_strict_gate_count,
        "max_drawdown_bps_observed": summary.max_drawdown_bps_observed,
        "verdict": summary.verdict,
        "verdict_reason": summary.verdict_reason,
        "thresholds_used": dict(summary.thresholds_used),
        "thresholds_satisfied": dict(summary.thresholds_satisfied),
        "threshold_evidence": list(summary.threshold_evidence),
        "live_gate": summary.live_gate,
        "live_symbols": list(summary.live_symbols),
        "approves_live": summary.approves_live,
        "approves_canary": summary.approves_canary,
        "approves_legacy_shutdown": summary.approves_legacy_shutdown,
        "approves_redis_trim": summary.approves_redis_trim,
    }
