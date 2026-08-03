"""Controlled paper-only exploration policy.

This module is intentionally pure: it reads candidate dictionaries and returns
policy metadata. It never writes Redis and never touches exchange adapters.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

PAPER_RISK_CONTROLLER_EXPLORATION_TIER = "PAPER_RISK_CONTROLLER_EXPLORATION"
FLOOR_RANGE = {"min": 0.58, "max": 0.88}

# Cold-start bootstrap exploration.
#
# An untrained/early model assigns high loss-probability (and therefore low
# confidence) to almost every candidate, which trips the dynamic confidence
# floor and blocks exploration. That is circular: the model's own unreliable
# estimate vetoes the paper trades that would generate the outcome data needed
# to train the model. The bootstrap lane lets a candidate be exploration-fill
# eligible even below the confidence floor, but ONLY when every HARD safety
# and integrity blocker is clear. It exists purely to escape the cold start;
# it is paper-only, tiny-size, never A+, never live, and never overrides risk,
# market-integrity, look-ahead, loss-cluster quarantine, positive-net-USD, or
# bounded-max-loss gates.
BOOTSTRAP_EXPLORATION_ENABLED = (
    os.getenv("PAPER_BOOTSTRAP_EXPLORATION_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on", "enabled"}
)
# The only blockers the bootstrap lane is permitted to override — all are the
# untrained model's confidence estimate, which is unreliable by construction.
BOOTSTRAP_OVERRIDABLE_BLOCKERS = frozenset(
    {
        "CONFIDENCE_EXECUTABLE_TRADE_BELOW_DYNAMIC_EXPLORATION_FLOOR",
        "CONFIDENCE_EXECUTABLE_TRADE_MISSING",
        # The allocator's low-confidence hard block is the SAME untrained-model
        # confidence signal expressed through a second gate (allocator:
        # confidence_calibrated < 0.50 -> BLOCK_LOW_CONFIDENCE). With honest
        # outcome-fit temperature calibration the cold-start model's calibrated
        # confidence sits ~0.43-0.59, so without this the bootstrap lane can
        # never fill and the confidence circularity this lever exists to break
        # stays locked. Every OTHER allocator block (BLOCK_NO_EDGE,
        # BLOCK_BAD_MARKET_STATE, BLOCK_EXPOSURE_BUDGET, liquidity, circuit
        # breaker) remains a hard blocker for the bootstrap lane.
        "ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE",
    }
)
DYNAMIC_EXPLORATION_FLOOR_FORMULA = (
    "clamp(0.58 + low_evidence_penalty + microstructure_trust_penalty + "
    "provider_confluence_penalty + spread_slippage_funding_penalty + "
    "volatility_regime_penalty + drawdown_state_penalty + "
    "loss_cluster_quarantine_penalty - matured_positive_bucket_bonus - "
    "trusted_provider_bonus, 0.58, 0.88)"
)

_HARD_MARKET_BLOCK_TOKENS = (
    "MARKET_STATE_INTEGRITY",
    "MICROSTRUCTURE_TRUST_FAIL",
    "PUBLIC_BOOK_UNTRUSTED",
    "ORDERBOOK_UNTRUSTED",
    "LIQUIDITY_DEPTH_INSUFFICIENT",
)
_STALE_FEATURE_TOKENS = (
    "STALE",
    "FRESHNESS",
    "MISSING_CRITICAL_FEATURE",
    "FEATURE_COVERAGE",
)
_LOSS_CLUSTER_TOKENS = (
    "LOSS_CLUSTER",
    "QUARANTINE",
    "HIGH_CONFIDENCE_LOSS",
    "ATR_STOP_CLUSTER",
)
_HARD_DECISION_TOKENS = (
    "BLOCK",
    "REJECT",
    "DENY",
    "NO_TRADE",
    "SHADOW_ONLY",
    "FAIL",
)
_RISK_ALLOW_VALUES = {
    "PASS",
    "ALLOW",
    "ALLOWED",
    "APPROVE",
    "APPROVED",
    "REDUCE_SIZE",
    "HEDGE_REQUIRED",
    "ALLOW_WITH_SIZE",
}
_ORCH_ALLOW_VALUES = _RISK_ALLOW_VALUES | {"OPEN_LONG", "OPEN_SHORT"}
_ALLOCATOR_ALLOW_VALUES = _RISK_ALLOW_VALUES | {"ALLOW_WITH_SIZE"}

_DANGEROUS_RAW_BOOLEAN_FIELDS = (
    "routes_to_live",
    "places_real_order",
    "test_order",
    "live_order",
    "counts_as_A_plus",
    "counts_as_final_A_plus",
    "counts_as_live_ready",
    "order_submitted",
    "test_order_submitted",
    "leverage_mutated",
    "margin_mutated",
)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def paper_exploration_raw_safety_fields(row: Mapping[str, Any]) -> dict[str, bool | None]:
    """Return raw safety flags without mixing them with pass/fail checks."""

    counts_as_final_a_plus = _first_present(
        row.get("counts_as_final_A_plus"),
        row.get("counts_as_final_a_plus"),
    )
    return {
        "paper_only": _bool(row.get("paper_only")),
        "routes_to_live": _bool(row.get("routes_to_live")),
        "places_real_order": _bool(row.get("places_real_order")),
        "test_order": _bool(row.get("test_order")),
        "live_order": _bool(row.get("live_order")),
        "counts_as_A_plus": _bool(row.get("counts_as_A_plus")),
        "counts_as_final_A_plus": _bool(counts_as_final_a_plus),
        "counts_as_live_ready": _bool(row.get("counts_as_live_ready")),
        "order_submitted": _bool(row.get("order_submitted")),
        "test_order_submitted": _bool(row.get("test_order_submitted")),
        "leverage_mutated": _bool(row.get("leverage_mutated")),
        "margin_mutated": _bool(row.get("margin_mutated")),
    }


def paper_exploration_invariant_checks(
    raw_fields: Mapping[str, Any],
) -> dict[str, bool]:
    """Return unambiguous invariant checks for paper-only exploration rows."""

    return {
        "paper_only_is_true": raw_fields.get("paper_only") is True,
        "routes_to_live_is_false": raw_fields.get("routes_to_live") is False,
        "places_real_order_is_false": raw_fields.get("places_real_order") is False,
        "test_order_is_false": raw_fields.get("test_order") is False,
        "live_order_is_false": raw_fields.get("live_order") is False,
        "counts_as_A_plus_is_false": raw_fields.get("counts_as_A_plus") is False,
        "counts_as_final_A_plus_is_false": (
            raw_fields.get("counts_as_final_A_plus") is False
        ),
        "counts_as_live_ready_is_false": (
            raw_fields.get("counts_as_live_ready") is False
        ),
        "order_submitted_is_false": raw_fields.get("order_submitted") is False,
        "test_order_submitted_is_false": (
            raw_fields.get("test_order_submitted") is False
        ),
        "leverage_mutated_is_false": raw_fields.get("leverage_mutated") is False,
        "margin_mutated_is_false": raw_fields.get("margin_mutated") is False,
    }


def build_paper_exploration_safety_truth(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build explicit raw safety fields and separately named pass checks."""

    raw_fields = paper_exploration_raw_safety_fields(row)
    invariant_checks = paper_exploration_invariant_checks(raw_fields)
    hard_fail_reasons = [
        f"RAW_{field.upper()}_TRUE"
        for field in _DANGEROUS_RAW_BOOLEAN_FIELDS
        if raw_fields.get(field) is True
    ]
    if raw_fields.get("paper_only") is not True:
        hard_fail_reasons.append("RAW_PAPER_ONLY_NOT_TRUE")
    flat_truth: dict[str, Any] = {
        "raw_paper_only": raw_fields.get("paper_only"),
        "raw_routes_to_live": raw_fields.get("routes_to_live"),
        "raw_places_real_order": raw_fields.get("places_real_order"),
        "raw_test_order": raw_fields.get("test_order"),
        "raw_live_order": raw_fields.get("live_order"),
        "raw_counts_as_A_plus": raw_fields.get("counts_as_A_plus"),
        "raw_counts_as_final_A_plus": raw_fields.get("counts_as_final_A_plus"),
        "raw_counts_as_live_ready": raw_fields.get("counts_as_live_ready"),
        "raw_order_submitted": raw_fields.get("order_submitted"),
        "raw_test_order_submitted": raw_fields.get("test_order_submitted"),
        "raw_leverage_mutated": raw_fields.get("leverage_mutated"),
        "raw_margin_mutated": raw_fields.get("margin_mutated"),
        "paper_only_true": invariant_checks["paper_only_is_true"],
        "routes_to_live_false": invariant_checks["routes_to_live_is_false"],
        "places_real_order_false": invariant_checks["places_real_order_is_false"],
        "test_order_false": invariant_checks["test_order_is_false"],
        "live_order_false": invariant_checks["live_order_is_false"],
        "counts_as_A_plus_false": invariant_checks["counts_as_A_plus_is_false"],
        "counts_as_final_A_plus_false": (
            invariant_checks["counts_as_final_A_plus_is_false"]
        ),
        "counts_as_live_ready_false": (
            invariant_checks["counts_as_live_ready_is_false"]
        ),
        "order_submitted_false": invariant_checks["order_submitted_is_false"],
        "test_order_submitted_false": (
            invariant_checks["test_order_submitted_is_false"]
        ),
        "leverage_mutated_false": invariant_checks["leverage_mutated_is_false"],
        "margin_mutated_false": invariant_checks["margin_mutated_is_false"],
    }
    return {
        "raw_fields": raw_fields,
        "invariant_checks": invariant_checks,
        **flat_truth,
        "hard_fail": bool(hard_fail_reasons),
        "hard_fail_reasons": hard_fail_reasons,
    }


def _timeframe_max_hold_seconds(timeframe: Any) -> int:
    text = str(timeframe or "").strip().lower()
    units = {"m": 60, "h": 60 * 60, "d": 24 * 60 * 60}
    if len(text) >= 2 and text[-1] in units:
        try:
            count = max(1, int(text[:-1]))
        except ValueError:
            count = 15
        return int(min(max(count * units[text[-1]] * 3, 15 * 60), 24 * 60 * 60))
    return 3 * 60 * 60


def build_paper_exploration_exit_plan(
    row: Mapping[str, Any],
    *,
    generated_utc: Any | None = None,
) -> dict[str, Any] | None:
    """Build an internal paper-only stop/time exit plan from bounded-loss inputs."""

    existing = _as_dict(row.get("exit_plan"))
    if existing:
        return dict(existing)

    side = str(
        _first_present(row.get("side"), row.get("selected_action"), row.get("action"))
        or ""
    ).strip().lower()
    if side not in {"long", "short"}:
        return None
    current_price = _float(
        _first_present(row.get("current_price"), row.get("entry_price"), row.get("fill_price"))
    )
    notional_usd = _float(
        _first_present(
            row.get("recommended_notional_usd"),
            row.get("gross_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
            row.get("order_size_usd"),
        )
    )
    max_loss_usd = _float(
        _first_present(
            row.get("expected_max_loss_usd"),
            row.get("max_loss_usd"),
            row.get("max_loss_if_stop_hit"),
        )
    )
    stop_distance_bps = _float(row.get("stop_distance_bps"))
    if max_loss_usd is None and stop_distance_bps is not None and notional_usd is not None:
        max_loss_usd = abs(notional_usd) * abs(stop_distance_bps) / 10_000.0
    if (
        current_price is None
        or current_price <= 0.0
        or max_loss_usd is None
        or max_loss_usd <= 0.0
        or notional_usd is None
        or notional_usd <= 0.0
    ):
        return None

    stop_distance = current_price * min(0.95, max_loss_usd / notional_usd)
    if stop_distance <= 0.0:
        return None
    stop_loss_price = (
        max(0.0, current_price - stop_distance)
        if side == "long"
        else current_price + stop_distance
    )
    if stop_loss_price <= 0.0:
        return None

    expected_net_usd = max(0.0, _float(row.get("expected_net_pnl_usd")) or 0.0)
    reward_usd = max(expected_net_usd, max_loss_usd * 1.1)
    take_profit_distance = current_price * min(1.0, reward_usd / notional_usd)
    take_profit_price = (
        current_price + take_profit_distance
        if side == "long"
        else max(0.0, current_price - take_profit_distance)
    )
    max_hold_seconds = _timeframe_max_hold_seconds(row.get("timeframe"))
    generated_at = _parse_time(
        _first_present(
            generated_utc,
            row.get("accepted_at"),
            row.get("generated_utc"),
            row.get("decision_time"),
        )
    )
    time_exit_at = (
        _format_time(generated_at + timedelta(seconds=max_hold_seconds))
        if generated_at is not None
        else None
    )
    return {
        "status": "INTERNAL_PAPER_EXIT_PLAN_ACTIVE",
        "source": "DERIVED_FROM_EXPECTED_MAX_LOSS_AND_CURRENT_PRICE",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "side": side,
        "current_price": round(current_price, 12),
        "gross_notional_usd": round(notional_usd, 8),
        "expected_max_loss_usd": round(max_loss_usd, 8),
        "max_loss_usd": round(max_loss_usd, 8),
        "stop_loss_price": round(stop_loss_price, 12),
        "take_profit_price": round(take_profit_price, 12),
        "max_hold_seconds": max_hold_seconds,
        "time_exit_at": time_exit_at,
        "exit_triggers": [
            "stop_loss_price",
            "take_profit_price",
            "max_hold_seconds",
            "risk_or_thesis_invalidated",
        ],
        "order_path": "paper_internal_lifecycle_only",
    }


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _delta_ms(later: datetime | None, earlier: datetime | None) -> int | None:
    if later is None or earlier is None:
        return None
    return int(round((later - earlier).total_seconds() * 1000.0))


def _resolve_feature_available_at(
    row: Mapping[str, Any],
) -> tuple[datetime | None, str | None, str | None]:
    """Resolve one feature clock without falling through malformed claims."""

    fields = (
        "feature_available_at",
        "entry_feature_available_at",
        "source_available_at",
        "available_at",
    )
    for field in fields:
        if field not in row:
            continue
        parsed = _parse_time(row.get(field))
        if parsed is None:
            return None, field, f"{field.upper()}_INVALID"
        return parsed, field, None
    return None, None, None


def _score_0_1(value: Any) -> float | None:
    numeric = _float(value)
    if numeric is None:
        return None
    if numeric > 1.0 and numeric <= 100.0:
        numeric /= 100.0
    return _clamp(numeric, 0.0, 1.0)


def _reason_text(row: Mapping[str, Any]) -> str:
    reasons: list[str] = []
    for key in (
        "block_reasons",
        "allocator_block_reasons",
        "risk_controller_block_reasons",
        "risk_block_reasons",
        "orchestrator_block_reasons",
        "preemptive_block_reasons",
        "paper_fill_gate_block_reasons",
        "local_block_reasons",
    ):
        reasons.extend(str(item) for item in _as_list(row.get(key)))
    for key in (
        "paper_opportunity_tier_reason",
        "paper_fill_block_reason",
        "allocator_decision",
        "risk_decision",
        "orchestrator_decision",
        "preemptive_action",
        "preemptive_decision",
        "strategy_supply_stage_rejected_reason",
    ):
        value = row.get(key)
        if value not in (None, ""):
            reasons.append(str(value))
    return " ".join(reasons).upper()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _is_paper_risk_controller_exploration_row(row: Mapping[str, Any]) -> bool:
    tier = str(
        _first_present(
            row.get("paper_opportunity_tier"),
            row.get("tier"),
            row.get("exploration_tier"),
            row.get("paper_exploration_tier"),
        )
        or ""
    ).strip().upper()
    return (
        tier == PAPER_RISK_CONTROLLER_EXPLORATION_TIER
        or row.get("paper_risk_controller_exploration") is True
        or row.get("allow_paper_risk_controller_exploration") is True
    )


def _specific_quarantine_key(value: Any) -> bool:
    normalized = str(value or "")
    return bool(normalized) and not normalized.startswith(("side:", "timeframe:", "regime:"))


def _specific_loss_cluster_key(value: Any) -> bool:
    normalized = str(value or "")
    return bool(normalized) and not normalized.startswith(
        ("loss_cluster_side:", "loss_cluster_timeframe:")
    )


def _has_specific_quarantine_match(row: Mapping[str, Any]) -> bool:
    return any(
        _specific_quarantine_key(key)
        for key in _as_list(row.get("paper_performance_circuit_breaker_matched_blocked_bucket_keys"))
    ) or any(
        _specific_loss_cluster_key(key)
        for key in _as_list(row.get("paper_performance_circuit_breaker_matched_loss_cluster_keys"))
    )


def _advisory_only_quarantine_context(row: Mapping[str, Any]) -> bool:
    if not _is_paper_risk_controller_exploration_row(row):
        return False
    if row.get("paper_only") is not True:
        return False
    if any(
        row.get(field) is True
        for field in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "test_order",
            "order_submitted",
            "test_order_submitted",
            "leverage_mutated",
            "margin_mutated",
            "counts_as_A_plus",
            "counts_as_final_A_plus",
            "counts_as_final_a_plus",
            "counts_as_live_ready",
        )
    ):
        return False
    if _has_specific_quarantine_match(row):
        return False
    advisory_keys = (
        _as_list(row.get("paper_performance_circuit_breaker_advisory_bucket_keys"))
        + _as_list(row.get("paper_performance_circuit_breaker_advisory_loss_cluster_keys"))
    )
    router_reason = str(row.get("strategy_router_block_reason") or "").upper()
    return (
        row.get("paper_performance_circuit_global_halt_only") is True
        and bool(advisory_keys or router_reason == "PAPER_LOSS_BUCKET_QUARANTINE")
    )


def _loss_cluster_or_quarantine_active(row: Mapping[str, Any], reason_text: str) -> bool:
    # This function only feeds the paper EXPLORATION eligibility verdict, so
    # quarantine is evaluated bucket-specifically for every row: a candidate
    # whose own buckets match an active quarantine is blocked; a candidate in
    # a healthy bucket is not blocked by global halt text leaking through
    # reason strings (operator rule: exploration blocked only by
    # bucket-specific/current risk reasons). Explicit per-row cluster flags
    # still block unconditionally (fail-closed).
    is_exploration = _is_paper_risk_controller_exploration_row(row)
    # Operator policy 2026-07-10: when the paper loop has split matched
    # quarantine buckets into exact-hard vs immature-regime-advisory, only the
    # exact list hard-blocks the paper exploration lane. Advisory regime
    # buckets shrink/caution instead (A+/live lanes unaffected — they never
    # read this function). Broad per-row cluster booleans are also advisory in
    # this context; exact/specific matches above remain hard fail-closed.
    if (
        "paper_exploration_exact_blocked_bucket_keys" in row
        or "paper_exploration_regime_advisory_buckets" in row
    ) and bool(row.get("paper_exploration_exact_blocked_bucket_keys")):
        return True
    if _has_specific_quarantine_match(row):
        return True
    advisory_only_context = is_exploration and _advisory_only_quarantine_context(row)
    if advisory_only_context:
        return False
    if row.get("loss_cluster_detected") is True or row.get("atr_stop_cluster_active") is True:
        return True
    if (
        row.get("high_confidence_loss_cluster_active") is True
        and not advisory_only_context
    ):
        return True
    if row.get("paper_performance_circuit_breaker_matched_blocked_bucket_keys"):
        return True
    if row.get("paper_performance_circuit_global_halt_only") is True:
        return False
    return _contains_any(reason_text, _LOSS_CLUSTER_TOKENS) or row.get(
        "bucket_quarantine_active"
    ) is True


def classify_timestamp_integrity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Separate true lookahead from decision timestamp plumbing.

    A valid feature cutoff can still arrive after an incorrectly stamped
    decision time. That candidate is requeued for a later paper-only decision
    cycle; the decision time is never backdated.
    """

    provider_event_time = _parse_time(
        _first_present(
            row.get("provider_event_time"),
            row.get("event_time"),
            row.get("price_event_time"),
            row.get("kline_close_time"),
        )
    )
    feature_cutoff = _parse_time(
        _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff"))
    )
    feature_available_at, feature_available_at_source, availability_error = (
        _resolve_feature_available_at(row)
    )
    snapshot_generated_at = _parse_time(
        _first_present(row.get("snapshot_generated_at"), row.get("feature_snapshot_generated_at"))
    )
    prediction_generated_at = _parse_time(
        _first_present(row.get("prediction_generated_at"), row.get("generated_at"), row.get("generated_utc"))
    )
    signal_generated_at = _parse_time(
        _first_present(row.get("signal_generated_at"), row.get("signal_generated_utc"))
    )
    risk_decision_time = _parse_time(
        _first_present(row.get("risk_decision_time"), _as_dict(row.get("risk_decision_record")).get("risk_decision_time"))
    )
    orchestrator_decision_time = _parse_time(
        _first_present(
            row.get("orchestrator_decision_time"),
            _as_dict(row.get("orchestrator_decision_record")).get("decision_ts"),
        )
    )
    allocator_decision_time = _parse_time(
        _first_present(row.get("allocator_decision_time"), _as_dict(row.get("allocator_packet")).get("generated_utc"))
    )
    paper_decision_time = _parse_time(row.get("paper_decision_time"))
    candidate_decision_time = _parse_time(
        _first_present(row.get("candidate_decision_time"), row.get("decision_time"))
    )
    # ``available_at`` is the feature-availability clock in this policy. If an
    # explicit feature clock exists it must win over any legacy generic field,
    # which may have been populated from an unrelated price observation.
    available_at = feature_available_at
    decision_time = _parse_time(
        _first_present(row.get("decision_time"), row.get("source_decision_time"))
    )

    reasons: list[str] = []
    status = "PASS"
    timestamp_integrity_block = False
    real_lookahead_block = False
    requeue_for_next_cycle = False
    earliest_eligible = None

    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
        timestamp_integrity_block = True
    if available_at is None:
        reasons.append(availability_error or "AVAILABLE_AT_MISSING")
        timestamp_integrity_block = True
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING")
        timestamp_integrity_block = True
    if timestamp_integrity_block:
        status = "TIMESTAMP_INTEGRITY_BLOCK"

    if row.get("future_leakage_detected") is True:
        status = "REAL_LOOKAHEAD_BLOCK"
        timestamp_integrity_block = True
        real_lookahead_block = True
        reasons.append("FUTURE_LEAKAGE_DETECTED")
    if feature_cutoff and feature_available_at and feature_cutoff > feature_available_at:
        status = "REAL_LOOKAHEAD_BLOCK"
        timestamp_integrity_block = True
        real_lookahead_block = True
        reasons.append("FEATURE_CUTOFF_AFTER_AVAILABLE_AT_INVALID_LINEAGE")
    if feature_cutoff and decision_time and feature_cutoff > decision_time:
        status = "REAL_LOOKAHEAD_BLOCK"
        timestamp_integrity_block = True
        real_lookahead_block = True
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME_LOOKAHEAD")
    elif (
        not timestamp_integrity_block
        and available_at
        and decision_time
        and available_at > decision_time
    ):
        if feature_cutoff and feature_cutoff <= decision_time:
            status = "TIMESTAMP_PLUMBING_REQUEUE"
            requeue_for_next_cycle = True
            earliest_eligible = available_at
            reasons.append("TIMESTAMP_PLUMBING_REQUEUE_NEXT_CYCLE")
        else:
            status = "REAL_LOOKAHEAD_BLOCK"
            timestamp_integrity_block = True
            real_lookahead_block = True
            reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME_WITHOUT_VALID_FEATURE_CUTOFF")

    return {
        "timestamp_integrity_status": status,
        "timestamp_integrity_reasons": sorted(set(reasons)),
        "provider_event_time": _format_time(provider_event_time),
        "feature_cutoff": _format_time(feature_cutoff),
        "feature_available_at": _format_time(feature_available_at),
        "feature_available_at_source": feature_available_at_source,
        "snapshot_generated_at": _format_time(snapshot_generated_at),
        "prediction_generated_at": _format_time(prediction_generated_at),
        "signal_generated_at": _format_time(signal_generated_at),
        "risk_decision_time": _format_time(risk_decision_time),
        "orchestrator_decision_time": _format_time(orchestrator_decision_time),
        "allocator_decision_time": _format_time(allocator_decision_time),
        "paper_decision_time": _format_time(paper_decision_time),
        "candidate_decision_time": _format_time(candidate_decision_time),
        "available_at": _format_time(available_at),
        "decision_time": _format_time(decision_time),
        "available_at_minus_decision_ms": _delta_ms(available_at, decision_time),
        "feature_cutoff_minus_decision_ms": _delta_ms(feature_cutoff, decision_time),
        "earliest_eligible_decision_time": _format_time(earliest_eligible),
        "requeue_for_next_cycle": requeue_for_next_cycle,
        "timestamp_integrity_block": timestamp_integrity_block,
        "real_lookahead_block": real_lookahead_block,
        "decision_time_backdated": False,
    }


def classify_market_integrity_failure(row: Mapping[str, Any]) -> dict[str, Any]:
    """Decompose generic market integrity blocks into actionable categories."""

    reason_text = _reason_text(row)
    exact: list[str] = []
    repair_actions: list[str] = []
    current_price = _float(row.get("current_price"))
    provider_hashes = _as_dict(
        _first_present(row.get("provider_hashes"), row.get("provider_feature_hashes"), row.get("source_hashes"))
    )
    trust = _score_0_1(
        _first_present(
            row.get("composite_microstructure_trust_score"),
            row.get("microstructure_trust_score"),
            row.get("public_orderbook_trust_score"),
        )
    )

    if current_price is None or current_price <= 0.0 or "CURRENT_PRICE_MISSING" in reason_text:
        exact.append("PRICE_MISSING")
        repair_actions.append("PATCH_CURRENT_PRICE_RESOLVER_OR_EXCLUDE_SYMBOL")
    if "PRICE_STALE" in reason_text or "CURRENT_PRICE_STALE" in reason_text:
        exact.append("PRICE_STALE")
        repair_actions.append("REFRESH_PRICE_RESOLVER_CACHE_BEFORE_DECISION")
    if "ORDERBOOK" in reason_text or "PUBLIC_BOOK_UNTRUSTED" in reason_text:
        exact.append("ORDERBOOK_MISSING")
        repair_actions.append("REQUIRE_FRESH_ORDERBOOK_OR_BLOCK")
    if "MARK_PRICE" in reason_text:
        exact.append("MARK_PRICE_MISSING")
        repair_actions.append("PATCH_MARK_PRICE_BRIDGE_OR_BLOCK")
    if "KLINE" in reason_text:
        exact.append("KLINE_MISSING")
        repair_actions.append("REQUIRE_CLOSED_KLINE_BEFORE_DECISION")
    if not _feature_hash_present(row) or "FEATURE_SNAPSHOT_MISSING" in reason_text:
        exact.append("FEATURE_SNAPSHOT_MISSING")
        repair_actions.append("PATCH_FEATURE_SNAPSHOT_LINEAGE_BRIDGE")
    if "FEATURE_SNAPSHOT_STALE" in reason_text or "FRESHNESS" in reason_text or "STALE" in reason_text:
        exact.append("FEATURE_SNAPSHOT_STALE")
        repair_actions.append("REFRESH_FEATURE_SNAPSHOT_OR_REQUEUE")
    if "CANDLE_COMPLETION" in reason_text or "UNFINISHED_CANDLE" in reason_text:
        exact.append("CANDLE_COMPLETION_UNKNOWN")
        repair_actions.append("PATCH_CLOSED_CANDLE_COMPLETION_DETECTOR")
    if not provider_hashes and not _as_list(row.get("provider_features_used")):
        exact.append("PROVIDER_HASH_MISSING")
        repair_actions.append("PATCH_PROVIDER_LINEAGE_BRIDGE")
    if trust is None and ("MICROSTRUCTURE" in reason_text or "MARKET_STATE_INTEGRITY" in reason_text):
        exact.append("MICROSTRUCTURE_TRUST_MISSING")
        repair_actions.append("PATCH_MICROSTRUCTURE_TRUST_PAYLOAD")
    if trust is not None and trust < 0.65 and (
        "MICROSTRUCTURE_TRUST_FAIL" in reason_text
        or "WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST" in reason_text
    ):
        exact.append("ALT_DATA_CONFLICT")
        repair_actions.append("KEEP_BLOCKED_UNTIL_MICROSTRUCTURE_TRUST_RECOVERS")
    if "ALT_DATA" in reason_text or "FALLING_CVD" in reason_text or "TAPE_CONFIRMATION" in reason_text:
        exact.append("ALT_DATA_CONFLICT")
        repair_actions.append("KEEP_BLOCKED_UNTIL_PROVIDER_CONFLICT_CLEARS")
    if "SYMBOL_NOT_TRADABLE" in reason_text:
        exact.append("SYMBOL_NOT_TRADABLE")
        repair_actions.append("EXCLUDE_FROM_ACTIVE_TRADE_UNIVERSE")
    if "EXCHANGE_MARKET_NOT_FOUND" in reason_text:
        exact.append("EXCHANGE_MARKET_NOT_FOUND")
        repair_actions.append("PATCH_EXCHANGE_MARKET_METADATA_OR_EXCLUDE")

    exact = sorted(set(exact))
    repair_actions = sorted(set(repair_actions))
    hard_generic_present = "HARD_MARKET_INTEGRITY_FAILURE" in reason_text or _contains_any(
        reason_text,
        _HARD_MARKET_BLOCK_TOKENS,
    )
    irreparable = any(
        item in exact for item in ("SYMBOL_NOT_TRADABLE", "EXCHANGE_MARKET_NOT_FOUND")
    )
    return {
        "market_integrity_status": (
            "HARD_FAIL_EXACT"
            if exact
            else ("NO_HARD_MARKET_INTEGRITY_FAILURE" if not hard_generic_present else "HARD_FAIL_UNCLASSIFIED")
        ),
        "market_integrity_reasons": exact,
        "market_integrity_result": (
            "IRREPARABLE_MARKET_INTEGRITY_BLOCK_BEFORE_RISK"
            if irreparable
            else (
                "REPAIRABLE_OR_TRUE_MARKET_INTEGRITY_BLOCK"
                if exact
                else ("PASS" if not hard_generic_present else "HARD_MARKET_INTEGRITY_FAILURE_NEEDS_MAPPING")
            )
        ),
        "exact_repair_action": repair_actions or ["NO_MARKET_INTEGRITY_REPAIR_REQUIRED"],
        "generic_hard_market_integrity_present": hard_generic_present,
        "current_price": current_price,
        "price_source": _first_present(row.get("current_price_source"), row.get("price_source")),
        "price_age_ms": _float(_first_present(row.get("price_age_ms"), row.get("current_price_staleness_seconds"))),
        "orderbook_age_ms": _float(row.get("orderbook_age_ms")),
        "kline_age_ms": _float(row.get("kline_age_ms")),
        "feature_snapshot_age_ms": _float(row.get("feature_snapshot_age_ms")),
        "provider_hashes_present": bool(provider_hashes),
        "tradable_on_binance": _bool(row.get("tradable_on_binance")),
        "tradable_on_kucoin": _bool(row.get("tradable_on_kucoin")),
    }


def classify_quarantine_specificity(row: Mapping[str, Any]) -> dict[str, Any]:
    reason_text = _reason_text(row)
    reasons = _as_list(row.get("block_reasons")) + _as_list(row.get("preemptive_block_reasons"))
    active = (
        "BUCKET_QUARANTINE_MATCH" in {str(reason).upper() for reason in reasons}
        or _loss_cluster_or_quarantine_active(row, reason_text)
    )
    strategy_family = str(
        _first_present(row.get("strategy_family"), row.get("strategy_id"), row.get("strategy_selected_mode"), "unknown")
    )
    confidence = _float(row.get("confidence_executable_trade"))
    confidence_bucket = (
        "gte_0_95"
        if confidence is not None and confidence >= 0.95
        else ("gte_floor" if confidence is not None else "missing")
    )
    confluence = _provider_confluence_score(row)
    provider_confluence_bucket = "gte_0_70" if confluence >= 0.70 else "lt_0_70"
    key = _first_present(
        row.get("quarantine_bucket_key"),
        row.get("quarantine_bucket"),
        f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side')}|{strategy_family}|{confidence_bucket}",
    )
    observed_at = _first_present(
        row.get("quarantine_created_at"),
        row.get("quarantine_observed_at"),
        row.get("generated_utc"),
        row.get("decision_time"),
    )
    source_trades = row.get("quarantine_source_trades") or []
    if active and not source_trades:
        source_trades = ["CURRENT_PREEMPTIVE_BUCKET_QUARANTINE_MATCH"]
    return {
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": row.get("side"),
        "strategy_family": strategy_family,
        "confidence_bucket": confidence_bucket,
        "provider_confluence_bucket": provider_confluence_bucket,
        "quarantine_status": "ACTIVE_BUCKET_QUARANTINE" if active else "CLEAR",
        "quarantine_bucket_key": key,
        "quarantine_created_at": observed_at,
        "quarantine_observed_at": observed_at,
        "quarantine_reason": _first_present(row.get("quarantine_reason"), "BUCKET_QUARANTINE_MATCH" if active else None),
        "quarantine_source_trades": source_trades,
        "loss_cluster_rows": row.get("loss_cluster_rows"),
        "loss_cluster_net_usd": row.get("loss_cluster_net_usd"),
        "loss_cluster_latest_trade_time": row.get("loss_cluster_latest_trade_time"),
        "repair_epoch": row.get("repair_epoch"),
        "repair_epoch_applied": bool(row.get("repair_epoch_applied")),
        "is_global_quarantine": bool(row.get("is_global_quarantine")),
        "is_bucket_specific": bool(active and key),
        "should_block_this_row": bool(active),
        "proof_status": (
            "BUCKET_SPECIFIC_CURRENT_MATCH"
            if active and key
            else "NO_ACTIVE_QUARANTINE_FOR_ROW"
        ),
    }


def decompose_risk_blocked_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    risk_decision = _decision(row, "risk_controller_decision", "risk_decision", "risk_action")
    reasons = _as_list(
        _first_present(
            row.get("risk_controller_block_reasons"),
            row.get("risk_block_reasons"),
            _as_dict(row.get("risk_decision_record")).get("risk_block_reasons"),
        )
    )
    text = " ".join(str(reason).upper() for reason in reasons)
    exact: list[str] = []
    expected_max_loss = _float(_first_present(row.get("expected_max_loss_usd"), row.get("max_loss_usd")))
    liquidation_buffer = _float(
        _first_present(row.get("expected_liquidation_buffer_usd"), row.get("liquidation_buffer_usd"))
    )
    if expected_max_loss is None or "MAX_LOSS" in text:
        exact.append("max_loss_unknown" if expected_max_loss is None else "max_loss_too_large")
    if liquidation_buffer is None or "LIQUIDATION_BUFFER" in text:
        exact.append("liquidation_buffer_unknown" if liquidation_buffer is None else "liquidation_buffer_too_small")
    if "CROSS_MARGIN" in text:
        exact.append("portfolio_cross_margin_risk_too_high")
    if "CORRELATION" in text:
        exact.append("correlation_too_high")
    if "DAILY_LOSS" in text:
        exact.append("daily_loss_limit")
    if "DRAWDOWN" in text:
        exact.append("drawdown_limit")
    if "MARKET_INTEGRITY" in text or "MICROSTRUCTURE" in text:
        exact.append("market_integrity")
    if "PROVIDER" in text or "ALT_DATA" in text:
        exact.append("provider_conflict")
    if "HEDGE" in text:
        exact.append("hedge_required_but_unavailable")
    if "STOP" in text or "EXIT" in text:
        exact.append("stop_or_exit_plan_missing")
    if risk_decision in {"BLOCKED", "BLOCK", "DENY", "DENIED", "FAIL", "FAILED"} and not exact:
        exact.append("market_integrity")
    return {
        "risk_decision": risk_decision or None,
        "exact_reason": sorted(set(exact)),
        "is_true_risk": bool(exact),
        "is_false_negative": bool(risk_decision in {"BLOCKED", "BLOCK"} and not exact),
        "repair_action": (
            "PATCH_MISSING_USD_RISK_INPUTS"
            if any(item.endswith("unknown") for item in exact)
            else ("KEEP_RISK_BLOCKED" if exact else "NO_RISK_BLOCK")
        ),
        "paper_only_reduced_size_possible": expected_max_loss is not None and liquidation_buffer is not None,
        "hedge_required_possible": bool(row.get("hedge_required") or row.get("hedge_plan")),
    }


def build_paper_exploration_row_resolution(row: Mapping[str, Any]) -> dict[str, Any]:
    timestamp = classify_timestamp_integrity(row)
    market = classify_market_integrity_failure(row)
    quarantine = classify_quarantine_specificity(row)
    risk = decompose_risk_blocked_decision(row)
    blockers = []
    blockers.extend(timestamp["timestamp_integrity_reasons"])
    blockers.extend(market["market_integrity_reasons"])
    if quarantine["should_block_this_row"]:
        blockers.append("ACTIVE_BUCKET_QUARANTINE")
    blockers.extend(risk["exact_reason"])
    blockers.extend(str(reason) for reason in _as_list(row.get("paper_fill_gate_block_reasons")))
    blockers = sorted(set(str(item) for item in blockers if item))

    allowed_no_decision_reason = None
    if timestamp["real_lookahead_block"]:
        allowed_no_decision_reason = "REAL_LOOKAHEAD_BLOCK_BEFORE_RISK"
    elif market["market_integrity_result"] == "IRREPARABLE_MARKET_INTEGRITY_BLOCK_BEFORE_RISK":
        allowed_no_decision_reason = "IRREPARABLE_MARKET_INTEGRITY_BLOCK_BEFORE_RISK"
    elif quarantine["should_block_this_row"]:
        allowed_no_decision_reason = "ACTIVE_QUARANTINE_BLOCK_BEFORE_RISK"

    current_blocker = None
    if timestamp["timestamp_integrity_status"] == "TIMESTAMP_PLUMBING_REQUEUE":
        current_blocker = "TIMESTAMP_PLUMBING_REQUEUE_NEXT_CYCLE"
    elif allowed_no_decision_reason:
        current_blocker = allowed_no_decision_reason
    elif market["market_integrity_reasons"]:
        current_blocker = f"TRUE_MARKET_INTEGRITY_FAIL:{market['market_integrity_reasons'][0]}"
    elif risk["exact_reason"]:
        current_blocker = f"TRUE_RISK_BLOCK:{risk['exact_reason'][0]}"
    elif blockers:
        current_blocker = blockers[0]
    else:
        current_blocker = "PAPER_FILL_ELIGIBLE_PENDING_FILL_GATE"

    return {
        "timestamp_integrity": timestamp,
        "market_integrity": market,
        "quarantine": quarantine,
        "risk_block_resolution": risk,
        "row_blockers": blockers,
        "allowed_no_decision_reason": allowed_no_decision_reason,
        "current_blocker": current_blocker,
        "unknown": False,
    }


def _provider_confluence_score(row: Mapping[str, Any]) -> float:
    explicit = _score_0_1(
        _first_present(
            row.get("provider_confluence_score"),
            row.get("altdata_confluence_score"),
            row.get("advanced_indicator_confluence_score"),
        )
    )
    if explicit is not None:
        return explicit
    provider_hashes = _as_dict(
        _first_present(row.get("provider_hashes"), row.get("provider_feature_hashes"), row.get("source_hashes"))
    )
    provider_features = _as_list(row.get("provider_features_used"))
    confluence_flags = [
        row.get("Glassnode_features_present"),
        row.get("CryptoQuant_features_present"),
        # removed provider flag dropped (operator directive 2026-07-16); its
        # keys are deleted so the flag was permanently falsy — divisor below
        # is unchanged, preserving surviving-provider scoring exactly.
        row.get("CoinAnk_features_present"),
        row.get("microstructure_features_present"),
        bool(provider_hashes),
        bool(provider_features),
    ]
    present = sum(1 for item in confluence_flags if bool(item))
    return _clamp(present / 5.0, 0.0, 1.0)


def _cost_pressure_bps(row: Mapping[str, Any]) -> float:
    explicit = _float(
        _first_present(
            row.get("spread_slippage_funding_cost_bps"),
            row.get("total_expected_cost_bps"),
            row.get("expected_cost_bps"),
            row.get("debug_cost_bps"),
        )
    )
    if explicit is not None:
        return abs(explicit)
    parts = [
        _float(_first_present(row.get("actual_observed_spread_entry_bps"), row.get("observed_spread_bps"), row.get("spread_bps"))),
        _float(_first_present(row.get("expected_slippage_bps"), row.get("slippage_bps"))),
        _float(_first_present(row.get("fee_bps"), row.get("expected_fee_bps"))),
        _float(_first_present(row.get("expected_funding_bps"), row.get("funding_bps"))),
    ]
    summed = sum(value for value in parts if value is not None)
    if summed > 0.0:
        return summed
    expected_cost = _float(row.get("expected_cost_usd"))
    expected_gross = _float(row.get("expected_gross_pnl_usd"))
    if expected_cost is not None and expected_gross and expected_gross > 0.0:
        return abs(expected_cost / expected_gross) * 100.0
    return 0.0


def _evidence_count(row: Mapping[str, Any]) -> float:
    return _float(
        _first_present(
            row.get("symbol_timeframe_evidence_count"),
            row.get("bucket_evidence_count"),
            row.get("paper_bucket_closed_count"),
            row.get("closed_economic_outcome_count"),
            row.get("bucket_closed_count"),
            row.get("sample_count"),
        )
    ) or 0.0


def _risk_pressure_drawdown_bps(row: Mapping[str, Any]) -> float:
    return max(
        0.0,
        _float(
            _first_present(
                row.get("portfolio_drawdown_bps"),
                row.get("current_drawdown_bps"),
                row.get("drawdown_bps"),
                row.get("daily_open_equity_drawdown_bps"),
            )
        )
        or 0.0,
    )


def compute_dynamic_exploration_floor(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the evidence-aware confidence floor for paper exploration."""

    evidence_count = _evidence_count(row)
    microstructure_trust = _score_0_1(
        _first_present(
            row.get("composite_microstructure_trust_score"),
            row.get("microstructure_trust_score"),
            row.get("public_orderbook_trust_score"),
        )
    )
    provider_confluence = _provider_confluence_score(row)
    cost_pressure_bps = _cost_pressure_bps(row)
    volatility_bps = max(
        0.0,
        _float(
            _first_present(
                row.get("volatility_bps"),
                row.get("atr_bps"),
                row.get("debug_atr_bps"),
                _as_dict(row.get("ta_context")).get("atr_bps"),
                row.get("realized_volatility_bps"),
            )
        )
        or 0.0,
    )
    drawdown_bps = _risk_pressure_drawdown_bps(row)
    profit_factor = _float(
        _first_present(
            row.get("bucket_profit_factor"),
            row.get("recent_bucket_profit_factor"),
            row.get("paper_bucket_profit_factor"),
            row.get("profit_factor"),
        )
    )
    reason_text = _reason_text(row)
    loss_cluster_quarantine = _loss_cluster_or_quarantine_active(row, reason_text)

    low_evidence_penalty = min(0.08, max(0.0, 20.0 - evidence_count) * 0.004)
    microstructure_trust_penalty = (
        0.10
        if microstructure_trust is None
        else max(0.0, 0.65 - microstructure_trust) * 0.20
    )
    provider_confluence_penalty = max(0.0, 0.60 - provider_confluence) * 0.10
    cost_penalty = min(0.07, max(0.0, cost_pressure_bps - 8.0) * 0.002)
    volatility_penalty = min(0.05, volatility_bps / 10000.0)
    drawdown_penalty = min(0.08, drawdown_bps * 0.00004)
    loss_cluster_penalty = 0.22 if loss_cluster_quarantine else 0.0
    # Immature regime-wide quarantine buckets add caution without pinning the
    # floor at max (operator policy 2026-07-10): +0.04 per advisory bucket,
    # capped at 0.08, and only when no exact hard block already applies.
    regime_advisory_buckets = row.get("paper_exploration_regime_advisory_buckets") or []
    regime_advisory_penalty = (
        min(0.08, 0.04 * len(regime_advisory_buckets))
        if regime_advisory_buckets and not loss_cluster_quarantine
        else 0.0
    )
    matured_positive_bucket_bonus = (
        min(0.06, max(0.0, (profit_factor or 0.0) - 1.0) * 0.03)
        if evidence_count >= 20.0 and profit_factor is not None
        else 0.0
    )
    trusted_provider_bonus = (
        0.03
        if microstructure_trust is not None
        and microstructure_trust >= 0.80
        and provider_confluence >= 0.70
        else 0.0
    )

    floor = _clamp(
        0.58
        + low_evidence_penalty
        + microstructure_trust_penalty
        + provider_confluence_penalty
        + cost_penalty
        + volatility_penalty
        + drawdown_penalty
        + loss_cluster_penalty
        + regime_advisory_penalty
        - matured_positive_bucket_bonus
        - trusted_provider_bonus,
        FLOOR_RANGE["min"],
        FLOOR_RANGE["max"],
    )
    inputs = {
        "recent_bucket_performance": {
            "profit_factor": profit_factor,
            "matured_positive_bucket_bonus": round(matured_positive_bucket_bonus, 8),
        },
        "symbol_timeframe_evidence_count": evidence_count,
        "microstructure_trust": microstructure_trust,
        "provider_confluence": provider_confluence,
        "spread_slippage_funding_pressure_bps": cost_pressure_bps,
        "volatility_regime_bps": volatility_bps,
        "drawdown_state_bps": drawdown_bps,
        "loss_cluster_quarantine": loss_cluster_quarantine,
    }
    penalties = {
        "low_evidence_penalty": round(low_evidence_penalty, 8),
        "microstructure_trust_penalty": round(microstructure_trust_penalty, 8),
        "provider_confluence_penalty": round(provider_confluence_penalty, 8),
        "spread_slippage_funding_penalty": round(cost_penalty, 8),
        "volatility_regime_penalty": round(volatility_penalty, 8),
        "drawdown_state_penalty": round(drawdown_penalty, 8),
        "loss_cluster_quarantine_penalty": round(loss_cluster_penalty, 8),
        "immature_regime_bucket_advisory_penalty": round(regime_advisory_penalty, 8),
    }
    reason_counts = {
        name: int(value > 0.0)
        for name, value in penalties.items()
    }
    reason_counts["matured_positive_bucket_bonus"] = int(
        matured_positive_bucket_bonus > 0.0
    )
    reason_counts["trusted_provider_bonus"] = int(trusted_provider_bonus > 0.0)
    return {
        "dynamic_exploration_floor": round(floor, 8),
        "dynamic_exploration_floor_formula": DYNAMIC_EXPLORATION_FLOOR_FORMULA,
        "floor_inputs": inputs,
        "floor_range": dict(FLOOR_RANGE),
        "floor_penalties": penalties,
        "floor_bonuses": {
            "matured_positive_bucket_bonus": round(matured_positive_bucket_bonus, 8),
            "trusted_provider_bonus": round(trusted_provider_bonus, 8),
        },
        "reason_counts": reason_counts,
    }


def _selected_action(row: Mapping[str, Any]) -> str:
    return str(
        _first_present(row.get("selected_action"), row.get("action"), row.get("side"))
        or ""
    ).strip().lower()


def _side(row: Mapping[str, Any]) -> str:
    return str(_first_present(row.get("side"), row.get("selected_action"), row.get("action")) or "").strip().lower()


def _decision(row: Mapping[str, Any], *fields: str) -> str:
    return str(_first_present(*(row.get(field) for field in fields)) or "").strip().upper()


def _is_hard_block_decision(value: str) -> bool:
    return any(token in value for token in _HARD_DECISION_TOKENS)


def evaluate_paper_risk_controller_exploration(row: Mapping[str, Any]) -> dict[str, Any]:
    floor_info = compute_dynamic_exploration_floor(row)
    floor = floor_info["dynamic_exploration_floor"]
    # CUDA-policy signal rows publish calibrated confidence but not the
    # post-cost confidence_executable_trade field the strategy-supply lane
    # computes; falling back to calibrated confidence keeps the same 0.58-0.88
    # dynamic floor applied fail-closed (missing both still blocks). Price
    # falls back to the loop-resolved live entry/latest price fields — never a
    # synthesized value.
    confidence = _float(
        _first_present(
            row.get("confidence_executable_trade"),
            row.get("confidence_calibrated"),
        )
    )
    current_price = _float(
        _first_present(
            row.get("current_price"),
            row.get("entry_price"),
            row.get("fill_price"),
            row.get("latest_price"),
        )
    )
    expected_net = _float(row.get("expected_net_pnl_usd"))
    expected_max_loss = _float(
        _first_present(row.get("expected_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))
    )
    selected_action = _selected_action(row)
    side = _side(row)
    # USD conversion for CUDA-policy intents: under a performance halt the A+
    # allocator zeroes notional, which zeroes expected_net_pnl_usd even when a
    # real bps edge exists. The exploration lane prices such rows at its own
    # tiny reference notional (never the allocator's) so USD stays the primary
    # economics; a genuinely negative edge still rejects honestly. The actual
    # fill size still comes from exploration sizing controls.
    usd_conversion_source = None
    _usd_side = side if side in {"long", "short"} else selected_action
    _edge_bps = _float(row.get("expected_move_after_cost_bps"))
    _has_real_notional = any(
        (_float(row.get(field)) or 0.0) > 0.0
        for field in (
            "allocator_notional_usd",
            "target_notional_usd",
            "gross_notional_usd",
            "notional_usd",
            "recommended_notional_usd",
        )
    )
    _reference_notional = _float(
        row.get("paper_exploration_reference_notional_usd")
    ) or 200.0
    if (
        (expected_net is None or (expected_net == 0.0 and not _has_real_notional))
        and _edge_bps is not None
        and _usd_side in {"long", "short"}
    ):
        _side_edge_bps = _edge_bps if _usd_side == "long" else -_edge_bps
        expected_net = _reference_notional * _side_edge_bps / 10000.0
        usd_conversion_source = "EXPLORATION_REFERENCE_NOTIONAL_FROM_EDGE_BPS"
    _stop_bps = _float(
        _first_present(
            row.get("stop_distance_bps"),
            row.get("atr_bps"),
            row.get("debug_atr_bps"),
        )
    )
    if (
        (expected_max_loss is None or (expected_max_loss == 0.0 and not _has_real_notional))
        and _stop_bps is not None
        and _stop_bps > 0.0
    ):
        expected_max_loss = _reference_notional * _stop_bps / 10000.0
        usd_conversion_source = usd_conversion_source or (
            "EXPLORATION_REFERENCE_NOTIONAL_FROM_STOP_BPS"
        )
    timestamp_integrity = classify_timestamp_integrity(row)
    feature_cutoff = _parse_time(
        _first_present(
            row.get("feature_cutoff"),
            row.get("entry_feature_cutoff"),
        )
    )
    available_at, _availability_source, _availability_error = (
        _resolve_feature_available_at(row)
    )
    decision_time = _parse_time(
        _first_present(row.get("decision_time"), row.get("source_decision_time"))
    )
    reason_text = _reason_text(row)
    risk_decision = _decision(row, "risk_controller_decision", "risk_decision", "risk_action")
    orchestrator_decision = _decision(row, "orchestrator_decision", "orchestrator_action")
    allocator_decision = _decision(row, "allocator_decision")

    blockers: list[str] = []
    if selected_action not in {"long", "short"}:
        blockers.append("SELECTED_ACTION_NOT_DIRECTIONAL")
    if side not in {"long", "short"}:
        blockers.append("SIDE_NOT_DIRECTIONAL")
    if confidence is None:
        blockers.append("CONFIDENCE_EXECUTABLE_TRADE_MISSING")
    elif confidence < floor:
        blockers.append("CONFIDENCE_EXECUTABLE_TRADE_BELOW_DYNAMIC_EXPLORATION_FLOOR")
    if current_price is None or current_price <= 0.0:
        blockers.append("CURRENT_PRICE_MISSING_OR_INVALID")
    if expected_net is None:
        blockers.append("EXPECTED_NET_PNL_USD_MISSING")
    elif expected_net <= 0.0:
        blockers.append("EXPECTED_NET_PNL_USD_NON_POSITIVE")
    if expected_max_loss is None:
        blockers.append("EXPECTED_MAX_LOSS_USD_MISSING")
    elif expected_max_loss <= 0.0:
        blockers.append("EXPECTED_MAX_LOSS_USD_NON_POSITIVE")
    if feature_cutoff is None:
        blockers.append("FEATURE_CUTOFF_MISSING")
    if available_at is None:
        blockers.append("AVAILABLE_AT_MISSING")
    if decision_time is None:
        blockers.append("DECISION_TIME_MISSING")
    if timestamp_integrity["timestamp_integrity_block"]:
        blockers.extend(timestamp_integrity["timestamp_integrity_reasons"])
    elif timestamp_integrity["requeue_for_next_cycle"]:
        blockers.append("TIMESTAMP_PLUMBING_REQUEUE_NEXT_CYCLE")
    if _contains_any(reason_text, _STALE_FEATURE_TOKENS):
        blockers.append("STALE_OR_MISSING_CRITICAL_FEATURE_FAMILY")
    if _contains_any(reason_text, _HARD_MARKET_BLOCK_TOKENS):
        blockers.append("HARD_MARKET_INTEGRITY_FAILURE")
    if _loss_cluster_or_quarantine_active(row, reason_text):
        blockers.append("LOSS_CLUSTER_OR_QUARANTINE_ACTIVE")
    if any(row.get(field) is True for field in ("routes_to_live", "places_real_order", "exchange_mutation_path", "test_order_submitted")):
        blockers.append("EXCHANGE_MUTATION_PATH_PRESENT")
    if row.get("counts_as_A_plus") is True or row.get("counts_as_final_a_plus") is True:
        blockers.append("COUNTS_AS_A_PLUS_NOT_EXPLORATION")
    if row.get("counts_as_live_ready") is True or row.get("live_ready_candidate") is True:
        blockers.append("COUNTS_AS_LIVE_READY_NOT_EXPLORATION")
    if risk_decision and _is_hard_block_decision(risk_decision):
        blockers.append(f"RISK_CONTROLLER_HARD_BLOCK:{risk_decision}")
    if orchestrator_decision and _is_hard_block_decision(orchestrator_decision):
        blockers.append(f"ORCHESTRATOR_HARD_BLOCK:{orchestrator_decision}")
    if allocator_decision and _is_hard_block_decision(allocator_decision):
        # The circuit-breaker allocator block is the same quarantine signal
        # already scoped above: when the paper loop split matched buckets and
        # found only immature-regime ADVISORY matches (empty exact list), the
        # circuit-derived allocator block must not re-impose the hard block on
        # the exploration lane. Any other allocator hard block always stands.
        circuit_only_advisory = (
            str(allocator_decision) == "BLOCK_PAPER_PERFORMANCE_CIRCUIT_BREAKER"
            and (
                "paper_exploration_exact_blocked_bucket_keys" in row
                or "paper_exploration_regime_advisory_buckets" in row
            )
            and not row.get("paper_exploration_exact_blocked_bucket_keys")
        )
        if not circuit_only_advisory:
            blockers.append(f"ALLOCATOR_HARD_BLOCK:{allocator_decision}")

    eligible = not blockers

    # Cold-start bootstrap lane: if the ONLY thing blocking this candidate is
    # the untrained model's confidence estimate (below-floor or missing), and
    # every hard safety/integrity/economics gate is clear, allow it as a
    # paper-only bootstrap exploration fill to generate outcome data. Positive
    # net USD and a bounded max loss are still required (they are hard blockers
    # above), so this never explores into negative-expectancy or unbounded-loss
    # setups — only into plausible-edge setups the untrained model underrates.
    residual_after_confidence = [b for b in blockers if b not in BOOTSTRAP_OVERRIDABLE_BLOCKERS]
    bootstrap_confidence_only_block = (
        not eligible
        and not residual_after_confidence
        and any(b in BOOTSTRAP_OVERRIDABLE_BLOCKERS for b in blockers)
    )
    bootstrap_exploration = bool(
        BOOTSTRAP_EXPLORATION_ENABLED and bootstrap_confidence_only_block
    )
    if bootstrap_exploration:
        eligible = True
    return {
        **floor_info,
        "tier": PAPER_RISK_CONTROLLER_EXPLORATION_TIER,
        "eligible": eligible,
        "bootstrap_exploration": bootstrap_exploration,
        "bootstrap_exploration_enabled": BOOTSTRAP_EXPLORATION_ENABLED,
        "bootstrap_overridden_blockers": sorted(
            b for b in blockers if b in BOOTSTRAP_OVERRIDABLE_BLOCKERS
        ) if bootstrap_exploration else [],
        "above_dynamic_floor": confidence is not None and confidence >= floor,
        "confidence_executable_trade": confidence,
        "expected_net_pnl_usd_evaluated": expected_net,
        "expected_max_loss_usd_evaluated": expected_max_loss,
        "usd_conversion_source": usd_conversion_source,
        "dynamic_exploration_floor": floor,
        "timestamp_integrity": timestamp_integrity,
        "timestamp_integrity_status": timestamp_integrity["timestamp_integrity_status"],
        "earliest_eligible_decision_time": timestamp_integrity["earliest_eligible_decision_time"],
        "requeue_for_next_cycle": timestamp_integrity["requeue_for_next_cycle"],
        "real_lookahead_block": timestamp_integrity["real_lookahead_block"],
        "eligibility_reasons": (
            ["BOOTSTRAP_EXPLORATION_CONFIDENCE_FLOOR_OVERRIDDEN"]
            if bootstrap_exploration
            else (["ELIGIBLE"] if eligible else [])
        ),
        "eligibility_block_reasons": sorted(
            {b for b in blockers if not (bootstrap_exploration and b in BOOTSTRAP_OVERRIDABLE_BLOCKERS)}
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
        "risk_controller_seen": bool(
            _first_present(row.get("risk_decision_id"), row.get("risk_decision_record"), row.get("risk_decision"))
        ),
        "orchestrator_seen": bool(
            _first_present(row.get("orchestrator_decision_id"), row.get("orchestrator_decision_record"), row.get("orchestrator_decision"))
        ),
        "allocator_seen": bool(
            _first_present(row.get("allocator_decision_id"), row.get("allocator_packet"), row.get("allocator_decision"))
        ),
    }


def _lineage_present(row: Mapping[str, Any]) -> bool:
    provider_hashes = _as_dict(
        _first_present(row.get("provider_hashes"), row.get("provider_feature_hashes"), row.get("source_hashes"))
    )
    return bool(provider_hashes or _as_list(row.get("provider_features_used")))


def _feature_hash_present(row: Mapping[str, Any]) -> bool:
    return bool(_first_present(row.get("feature_vector_hash"), row.get("feature_snapshot_id"), row.get("entry_feature_snapshot_id")))


def _preemptive_present(row: Mapping[str, Any]) -> bool:
    return bool(_first_present(row.get("preemptive_decision_id"), row.get("preemptive_decision"), row.get("preemptive_action")))


def _exit_plan_present(row: Mapping[str, Any]) -> bool:
    if _float(_first_present(row.get("stop_loss_price"), row.get("internal_stop_loss_price"))) is not None:
        return True
    if _as_dict(row.get("exit_plan")) or _as_dict(row.get("hedge_plan")):
        return True
    if _float(_first_present(row.get("expected_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))) is not None and (
        _bool(row.get("exit_feasible")) is True
        or _float(row.get("exit_feasibility_score")) is not None
        or _float(_first_present(row.get("expected_liquidation_buffer_usd"), row.get("liquidation_buffer_usd"))) is not None
    ):
        return True
    return False


def exploration_paper_fill_gate(row: Mapping[str, Any]) -> dict[str, Any]:
    evaluation = evaluate_paper_risk_controller_exploration(row)
    risk_decision = _decision(row, "risk_controller_decision", "risk_decision", "risk_action")
    orchestrator_decision = _decision(row, "orchestrator_decision", "orchestrator_action")
    allocator_decision = _decision(row, "allocator_decision")
    blockers: list[str] = []
    if not evaluation["eligible"]:
        blockers.extend(evaluation["eligibility_block_reasons"])
    if risk_decision not in _RISK_ALLOW_VALUES:
        blockers.append(f"RISK_CONTROLLER_DECISION_NOT_FILL_ELIGIBLE:{risk_decision or 'MISSING'}")
    if orchestrator_decision not in _ORCH_ALLOW_VALUES:
        blockers.append(f"ORCHESTRATOR_DECISION_NOT_FILL_ELIGIBLE:{orchestrator_decision or 'MISSING'}")
    if allocator_decision not in _ALLOCATOR_ALLOW_VALUES:
        blockers.append(f"ALLOCATOR_DECISION_NOT_FILL_ELIGIBLE:{allocator_decision or 'MISSING'}")
    if _float(_first_present(row.get("expected_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))) is None:
        blockers.append("EXPECTED_MAX_LOSS_USD_MISSING")
    if not _exit_plan_present(row):
        blockers.append("INTERNAL_STOP_OR_EXIT_PLAN_MISSING")
    if not _lineage_present(row):
        blockers.append("PROVIDER_LINEAGE_MISSING")
    if not _feature_hash_present(row):
        blockers.append("FEATURE_HASH_MISSING")
    if not _preemptive_present(row):
        blockers.append("PREEMPTIVE_DECISION_MISSING")
    return {
        "paper_fill_allowed": not blockers,
        "paper_fill_block_reasons": sorted(set(blockers)),
        "risk_controller_decision": risk_decision or None,
        "orchestrator_decision": orchestrator_decision or None,
        "allocator_decision": allocator_decision or None,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
    }


def exploration_sizing_controls(row: Mapping[str, Any]) -> dict[str, Any]:
    paper_equity = _float(
        _first_present(
            row.get("paper_equity_usd"),
            row.get("available_paper_equity_usd"),
            row.get("equity_usd"),
            row.get("daily_open_equity_usd"),
            1000.0,
        )
    ) or 1000.0
    candidate_max_loss = _float(
        _first_present(row.get("expected_max_loss_usd"), row.get("max_loss_usd"), row.get("max_loss_if_stop_hit"))
    )
    confidence = _float(row.get("confidence_executable_trade")) or 0.0
    trust = _score_0_1(
        _first_present(
            row.get("composite_microstructure_trust_score"),
            row.get("microstructure_trust_score"),
            row.get("public_orderbook_trust_score"),
        )
    )
    provider_confluence = _provider_confluence_score(row)
    evidence_count = _evidence_count(row)
    recent_loss = max(0.0, _float(_first_present(row.get("recent_realized_loss_usd"), row.get("recent_loss_usd"))) or 0.0)
    volatility_bps = max(
        0.0,
        _float(
            _first_present(
                row.get("volatility_bps"),
                row.get("atr_bps"),
                row.get("debug_atr_bps"),
                _as_dict(row.get("ta_context")).get("atr_bps"),
            )
        )
        or 0.0,
    )
    drawdown_bps = _risk_pressure_drawdown_bps(row)
    normal_notional = _float(
        _first_present(row.get("target_notional_usd"), row.get("target_notional_usdt"), row.get("gross_notional_usd"), row.get("per_side_usd_notional"))
    )
    trust_factor = 0.35 if trust is None else _clamp(0.25 + trust, 0.25, 1.0)
    confidence_factor = _clamp(confidence, 0.25, 1.0)
    evidence_factor = _clamp(evidence_count / 50.0, 0.20, 1.0)
    provider_factor = _clamp(0.35 + provider_confluence, 0.35, 1.0)
    volatility_factor = _clamp(1.0 - min(0.60, volatility_bps / 1000.0), 0.25, 1.0)
    drawdown_factor = _clamp(1.0 - min(0.70, drawdown_bps / 2500.0), 0.20, 1.0)
    loss_factor = _clamp(1.0 - min(0.80, recent_loss / max(1.0, paper_equity * 0.01)), 0.20, 1.0)
    adaptive_factor = (
        trust_factor
        * confidence_factor
        * evidence_factor
        * provider_factor
        * volatility_factor
        * drawdown_factor
        * loss_factor
    )
    risk_budget_usd = round(max(0.0, paper_equity * 0.001 * adaptive_factor), 8)
    if candidate_max_loss is not None:
        risk_budget_usd = round(min(risk_budget_usd, candidate_max_loss, paper_equity * 0.002), 8)
    recommended_notional = None
    if normal_notional is not None and normal_notional > 0.0:
        shrink = adaptive_factor
        if candidate_max_loss and candidate_max_loss > 0.0:
            shrink = min(shrink, risk_budget_usd / candidate_max_loss)
        recommended_notional = round(max(0.0, normal_notional * _clamp(shrink, 0.0, 1.0)), 8)
    leverage_seed = _float(row.get("recommended_leverage"))
    if recommended_notional is not None and paper_equity > 0.0:
        derived_leverage = _clamp(recommended_notional / paper_equity, 0.01, 1.0)
    else:
        derived_leverage = _clamp((leverage_seed or 1.0) * adaptive_factor, 0.01, max(1.0, leverage_seed or 1.0))
    return {
        "paper_equity_usd": round(paper_equity, 8),
        "candidate_max_loss_usd": candidate_max_loss,
        "risk_budget_usd": risk_budget_usd,
        "recommended_notional_usd": recommended_notional,
        "recommended_leverage": round(derived_leverage, 8),
        "recommended_margin_mode": _first_present(row.get("recommended_margin_mode"), "isolated_paper"),
        "liquidation_buffer_usd": _float(
            _first_present(row.get("expected_liquidation_buffer_usd"), row.get("liquidation_buffer_usd"))
        ),
        "portfolio_liquidation_distance_usd": _float(
            _first_present(row.get("portfolio_liquidation_distance_usd"), row.get("distance_to_liquidation_usd"))
        ),
        "why_size_selected": (
            "adaptive tiny paper budget from equity, max loss, confidence, evidence maturity, "
            "microstructure trust, provider confluence, volatility, drawdown, and recent loss"
        ),
        "sizing_inputs": {
            "available_paper_equity_usd": paper_equity,
            "daily_open_equity_drawdown_bps": drawdown_bps,
            "recent_realized_loss_usd": recent_loss,
            "symbol_volatility_bps": volatility_bps,
            "expected_max_loss_usd": candidate_max_loss,
            "microstructure_trust": trust,
            "provider_confluence": provider_confluence,
            "confidence_executable_trade": confidence,
            "bucket_maturity_evidence_count": evidence_count,
        },
        "adaptive_factor": round(adaptive_factor, 8),
        "fixed_notional": False,
        "static_leverage": False,
        "martingale": False,
    }
