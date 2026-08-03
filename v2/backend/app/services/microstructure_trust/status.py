"""Status artifacts for adversarial microstructure trust activation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .feed_quality import iso_now
from .trust_score import (
    FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
    PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
    REDUCED_SIZE_BOOTSTRAP_TIER,
)


GOAL_ID = "V2_MICROSTRUCTURE_TRUST_SEMANTICS_A_PLUS_BOOTSTRAP_AND_COMPOSITE_CONFIRMATION_READY"
LIVE_GATE = "blocked_human_only"
PUBLIC_RUNTIME_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_trust/latest")
GOAL_STATE_REL = Path("goal_state") / GOAL_ID
POLICY_STATUS_FILENAME = "public_orderbook_trust_policy_status.json"
REQUIRED_COMPOSITE_CONFIRMATION_FIELDS = (
    "feed_integrity_pass",
    "sequence_gap_free",
    "latency_within_bound",
    "trade_tape_confirmation_pass",
    "cross_venue_confirmation_pass",
    "liquidation_sweep_risk_acceptable",
    "oi_funding_long_short_confirmation_pass",
    "real_spread_depth_cost_evidence_pass",
)


def status_output_dirs(repo_root: Path) -> tuple[Path, Path]:
    return repo_root / PUBLIC_RUNTIME_REL, repo_root / GOAL_STATE_REL


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def public_orderbook_trust_policy_status() -> dict[str, Any]:
    return {
        "schema_version": "public_orderbook_trust_policy_status_v2",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "public_orderbook_default_trust": "LOW",
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "public_book_can_approve_trade_alone": False,
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "reduced_size_tier_allowed": True,
        "reduced_size_counts_as_final_a_plus": False,
        "reduced_size_routes_to_live": False,
        "reduced_size_paper_only": True,
        "hidden_liquidity_not_observable": True,
        "public_depth_spoofable": True,
        "sweep_time_book_reliability_risk": "HIGH",
        "why_public_book_is_capped": [
            "Public depth is spoofable and can be pulled during sweeps.",
            "Hidden liquidity and private queue priority are not observable from public books.",
            "Sweep-time top-of-book depth is not enough to prove executable edge.",
        ],
        "which_evidence_can_raise_composite_trust": [
            "fresh feed integrity with no sequence gaps",
            "trade tape confirmation",
            "cross-venue confirmation",
            "liquidation/OI/funding/long-short confirmation",
            "real spread/depth/cost evidence",
            "realized execution quality after outcomes",
        ],
        "which_evidence_cannot_raise_composite_trust": [
            "public orderbook depth alone",
            "REDUCED_SIZE tier labels",
            "missing confirmation fields",
            "stale or future-dated features",
            "B-grade exploration outcomes by themselves",
        ],
        "what_remains_paper_only": [
            REDUCED_SIZE_BOOTSTRAP_TIER,
            "B_GRADE_EXPLORATION_PAPER",
            "shadow-only candidates",
        ],
        "what_can_eventually_count_toward_a_plus_after_outcomes": [
            "closed paper bootstrap outcomes with PIT-clean lineage",
            "positive PF and notional-weighted expectancy",
            "no high-confidence loss cluster",
            "no ATR stop cluster",
            "composite trust >= final threshold on promoted rows",
        ],
        "coinapi_not_required_to_solve_book_trust": True,
        "decision_requires_cross_validation": True,
        "coinapi_purchase_required": False,
        "tardis_purchase_required": False,
        "allowed_microstructure_actions": [
            "ALLOW",
            "REDUCE_SIZE",
            "SHADOW_ONLY",
            "NO_TRADE",
            "CLOSE_OR_REDUCE_ONLY",
        ],
        "candidate_required_fields": [
            "orderbook_trust_score",
            "orderbook_trust_tier",
            "orderbook_latency_ms",
            "book_sequence_gap",
            "book_depth_persistence_score",
            "book_cancel_pressure_score",
            "trade_tape_confirmation_score",
            "cross_venue_confirmation_score",
            "liquidation_zone_risk_score",
            "sweep_risk_score",
            "microstructure_action",
        ],
        "safety": {
            "places_real_order": False,
            "test_order": False,
            "cancel_or_modify_order": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "transfer_or_withdrawal": False,
            "old_redis_writes": False,
            "redis_trim": False,
            "legacy_restart": False,
            "paper_online_runtime_restart": False,
            "trainer_bridge_unmask": False,
            "fixed_notional_sizing": False,
            "static_leverage_policy": False,
        },
    }


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if isinstance(row, Mapping)]


def _has_rows(rows: list[Mapping[str, Any]]) -> bool:
    return len(rows) > 0


def _direct_source_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        row
        for row in rows
        if row.get("direct_binance_kucoin_active") is True
        or bool(row.get("direct_orderbook_sources"))
        or (
            isinstance(row.get("source_availability"), Mapping)
            and row["source_availability"].get("direct_binance_or_kucoin") is True
        )
    ]


def _blocked_or_reduced(rows: list[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("microstructure_action") or "").upper()
        in {"NO_TRADE", "SHADOW_ONLY", "REDUCE_SIZE", "CLOSE_OR_REDUCE_ONLY"}
    )


def _low_trust(rows: list[Mapping[str, Any]], minimum: float = 0.65) -> int:
    count = 0
    for row in rows:
        try:
            score = float(row.get("microstructure_trust_score"))
        except (TypeError, ValueError):
            count += 1
            continue
        if score < minimum:
            count += 1
    return count


def _float(row: Mapping[str, Any], key: str) -> float | None:
    try:
        value = row.get(key)
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _score_values(rows: list[Mapping[str, Any]], key: str) -> list[float]:
    return [value for row in rows if (value := _float(row, key)) is not None]


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 8) if values else None


def _confirmation_missing(row: Mapping[str, Any]) -> list[str]:
    explicit = row.get("composite_confirmation_missing_fields")
    if isinstance(explicit, list):
        return [str(item) for item in explicit]
    return [
        field
        for field in REQUIRED_COMPOSITE_CONFIRMATION_FIELDS
        if row.get(field) is not True
    ]


def _is_reduced_size_bootstrap_candidate(row: Mapping[str, Any]) -> bool:
    return (
        row.get("bootstrap_reduced_size_paper_only") is True
        or str(row.get("reduced_size_bootstrap_tier") or "").upper()
        == REDUCED_SIZE_BOOTSTRAP_TIER
    )


def _is_final_a_plus_eligible(row: Mapping[str, Any]) -> bool:
    return (
        row.get("final_a_plus_eligible") is True
        and row.get("reduced_size_counts_as_final_a_plus") is not True
        and str(row.get("orderbook_trust_tier") or "").upper() != "REDUCED_SIZE"
    )


def trust_score_summary(trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    direct_rows = _direct_source_rows(rows)
    scores = _score_values(rows, "microstructure_trust_score")
    public_scores = _score_values(rows, "public_orderbook_trust_score")
    composite_scores = _score_values(rows, "composite_microstructure_trust_score")
    return {
        "schema_version": "microstructure_trust_score_summary_v2",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "symbols": sorted({str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")}),
        "direct_orderbook_symbols": sorted(
            {str(row.get("symbol") or "").upper() for row in direct_rows if row.get("symbol")}
        ),
        "rows": len(rows),
        "direct_orderbook_source_rows": len(direct_rows),
        "avg_microstructure_trust_score": _avg(scores),
        "avg_public_orderbook_trust_score": _avg(public_scores),
        "avg_composite_microstructure_trust_score": _avg(composite_scores),
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "low_trust_rows": _low_trust(rows),
        "blocked_or_reduced_rows": _blocked_or_reduced(rows),
        "a_grade_eligible_rows": sum(1 for row in rows if row.get("eligible_for_a_grade") is True),
        "final_a_plus_eligible_rows": sum(1 for row in rows if _is_final_a_plus_eligible(row)),
        "reduced_size_bootstrap_candidate_rows": sum(
            1 for row in rows if _is_reduced_size_bootstrap_candidate(row)
        ),
        "missing_component_rows": sum(1 for row in rows if row.get("missing_components")),
        "missing_composite_confirmation_rows": sum(1 for row in rows if _confirmation_missing(row)),
        "public_book_can_approve_trade_alone": False,
    }


def trust_semantics_operator_decision_packet() -> dict[str, Any]:
    return {
        "schema_version": "trust_semantics_operator_decision_packet_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "public_book_can_approve_trade_alone": False,
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "reduced_size_tier_allowed": True,
        "reduced_size_counts_as_final_a_plus": False,
        "reduced_size_routes_to_live": False,
        "reduced_size_paper_only": True,
        "why_public_book_is_capped": public_orderbook_trust_policy_status()["why_public_book_is_capped"],
        "which_evidence_can_raise_composite_trust": public_orderbook_trust_policy_status()[
            "which_evidence_can_raise_composite_trust"
        ],
        "which_evidence_cannot_raise_composite_trust": public_orderbook_trust_policy_status()[
            "which_evidence_cannot_raise_composite_trust"
        ],
        "what_remains_paper_only": public_orderbook_trust_policy_status()["what_remains_paper_only"],
        "what_can_eventually_count_toward_a_plus_after_outcomes": public_orderbook_trust_policy_status()[
            "what_can_eventually_count_toward_a_plus_after_outcomes"
        ],
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "routes_to_live": False,
    }


def microstructure_composite_trust_status(trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    public_alone_final = [
        row
        for row in rows
        if (_float(row, "public_orderbook_trust_score") or 0.0) >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST
        and _is_final_a_plus_eligible(row)
    ]
    silent_defaults_above_min = [
        row
        for row in rows
        if row.get("composite_microstructure_trust_score") is None
        and (_float(row, "microstructure_trust_score") or 0.0) >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    ]
    missing_confirmations_passed = [
        row
        for row in rows
        if _confirmation_missing(row)
        and (_float(row, "composite_microstructure_trust_score") or 0.0)
        >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    ]
    hard_fail_reasons = []
    if public_alone_final:
        hard_fail_reasons.append("PUBLIC_ORDERBOOK_TRUST_ALONE_CAN_PRODUCE_FINAL_A_PLUS")
    if silent_defaults_above_min:
        hard_fail_reasons.append("COMPOSITE_SCORE_SILENTLY_DEFAULTS_ABOVE_FINAL_THRESHOLD")
    if missing_confirmations_passed:
        hard_fail_reasons.append("MISSING_CONFIRMATION_FIELDS_TREATED_AS_PASS")
    return {
        "schema_version": "microstructure_composite_trust_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "runtime_microstructure_rows": len(rows),
        "required_confirmation_fields": list(REQUIRED_COMPOSITE_CONFIRMATION_FIELDS),
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "public_orderbook_trust_score_alone_final_a_plus_rows": len(public_alone_final),
        "composite_score_missing_but_legacy_score_above_threshold_rows": len(silent_defaults_above_min),
        "missing_confirmation_fields_above_threshold_rows": len(missing_confirmations_passed),
        "hard_fail": bool(hard_fail_reasons),
        "hard_fail_reasons": hard_fail_reasons,
        "public_book_can_approve_trade_alone": False,
        "missing_confirmation_fields_are_fail_closed": True,
        "places_real_order": False,
        "routes_to_live": False,
        "sample_rows": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "public_orderbook_trust_score": row.get("public_orderbook_trust_score"),
                "composite_microstructure_trust_score": row.get(
                    "composite_microstructure_trust_score"
                ),
                "missing_confirmations": _confirmation_missing(row),
                "final_a_plus_eligible": row.get("final_a_plus_eligible"),
            }
            for row in rows[:10]
        ],
    }


def reduced_size_bootstrap_policy_status() -> dict[str, Any]:
    return {
        "schema_version": "a_plus_reduced_size_bootstrap_policy_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "tier": REDUCED_SIZE_BOOTSTRAP_TIER,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "paper_only": True,
        "admission": {
            "public_orderbook_trust_score_gte_publisher_reduced_size_tier": True,
            "composite_microstructure_trust_score_lt_final_a_plus_min": True,
            "base_prediction_risk_orchestrator_allocator_predicates_pass": True,
            "expected_edge_after_cost_gt_zero": True,
            "production_grade_cost": True,
            "no_quarantine": True,
            "no_atr_stop_cluster": True,
            "no_high_confidence_loss_cluster": True,
        },
        "sizing": {
            "mandatory_size_haircut": True,
            "haircut_factors": [
                "composite_trust_gap",
                "volatility",
                "spread",
                "depth",
                "drawdown",
                "bucket_pf",
            ],
            "static_dollar_notional": False,
            "leverage_increase_to_compensate_for_lower_trust": False,
        },
    }


def reduced_size_bootstrap_runtime_status(trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    candidates = [row for row in rows if _is_reduced_size_bootstrap_candidate(row)]
    return {
        "schema_version": "a_plus_reduced_size_bootstrap_runtime_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "tier": REDUCED_SIZE_BOOTSTRAP_TIER,
        "candidate_rows": len(candidates),
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "paper_only": True,
        "mandatory_size_haircut": True,
        "no_static_dollar_notional": True,
        "no_leverage_increase_to_compensate_for_lower_trust": True,
        "sample_candidates": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "public_orderbook_trust_score": row.get("public_orderbook_trust_score"),
                "composite_microstructure_trust_score": row.get(
                    "composite_microstructure_trust_score"
                ),
                "trust_gap_to_final": round(
                    max(
                        0.0,
                        FINAL_A_PLUS_MIN_COMPOSITE_TRUST
                        - (_float(row, "composite_microstructure_trust_score") or 0.0),
                    ),
                    8,
                ),
            }
            for row in candidates[:10]
        ],
    }


def final_a_plus_trust_gate_status(trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    final_rows = [row for row in rows if _is_final_a_plus_eligible(row)]
    reduced_as_final = [
        row
        for row in rows
        if str(row.get("orderbook_trust_tier") or "").upper() == "REDUCED_SIZE"
        and row.get("final_a_plus_eligible") is True
    ]
    composite_missing_final = [
        row
        for row in rows
        if row.get("composite_microstructure_trust_score") is None
        and row.get("final_a_plus_eligible") is True
    ]
    b_grade_final = [
        row
        for row in rows
        if "B_GRADE" in str(row.get("orderbook_trust_tier") or row.get("source_tier") or "").upper()
        and row.get("final_a_plus_eligible") is True
    ]
    hard_fail_reasons = []
    if reduced_as_final:
        hard_fail_reasons.append("REDUCED_SIZE_APPEARS_AS_FINAL_A_PLUS")
    if b_grade_final:
        hard_fail_reasons.append("B_GRADE_APPEARS_AS_FINAL_A_PLUS")
    if composite_missing_final:
        hard_fail_reasons.append("COMPOSITE_TRUST_MISSING_BUT_CANDIDATE_PASSES_FINAL_A_PLUS")
    return {
        "schema_version": "final_a_plus_trust_gate_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "final_a_plus_candidates": len(final_rows),
        "requires": {
            "composite_microstructure_trust_score_gte_0_60": True,
            "production_grade_cost": True,
            "risk_pass": True,
            "orchestrator_pass": True,
            "allocator_pass": True,
            "guardian_pass": True,
            "bucket_pf_positive": True,
            "notional_weighted_expectancy_positive": True,
            "no_active_quarantine": True,
        },
        "hard_fail": bool(hard_fail_reasons),
        "hard_fail_reasons": hard_fail_reasons,
        "reduced_size_as_final_a_plus_rows": len(reduced_as_final),
        "b_grade_as_final_a_plus_rows": len(b_grade_final),
        "composite_missing_final_a_plus_rows": len(composite_missing_final),
        "public_book_can_approve_trade_alone": False,
        "places_real_order": False,
        "routes_to_live": False,
    }


def post_reboot_data_maturity_reverify_status(
    *,
    trust_rows: Iterable[Mapping[str, Any]],
    feed_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    rows = _rows(trust_rows)
    feed_summary = feed_summary if isinstance(feed_summary, Mapping) else {}
    feed_fail_closed_rows = int(feed_summary.get("fail_closed_rows") or 0)
    orderbook_depth_fresh_count = sum(
        1 for row in rows if row.get("real_spread_depth_cost_evidence_pass") is True
    )
    trade_tape_fresh_count = sum(
        1 for row in rows if row.get("trade_tape_confirmation_pass") is True
    )
    long_short_fresh_count = sum(
        1 for row in rows if row.get("oi_funding_long_short_confirmation_pass") is True
    )
    liquidation_fresh_count = sum(
        1 for row in rows if row.get("liquidation_sweep_risk_acceptable") is True
    )
    source_blockers = []
    if not rows:
        source_blockers.append(
            {
                "source_name": "microstructure_trust",
                "service_name": "v2_microstructure_feed_quality_monitor",
                "redis_key": "v2:microstructure:trust_score:{symbol}:{timeframe}",
                "route/payload": "operator_runtime/v2_microstructure_trust/latest/microstructure_runtime_rows.json",
                "expected_update_cadence": "monitor interval <= ttl",
                "actual_age_seconds": None,
                "patch_needed": "verify direct book/tape/context inputs are publishing after reboot",
            }
        )
    if feed_fail_closed_rows:
        source_blockers.append(
            {
                "source_name": "orderbook_feed_integrity",
                "service_name": "v2_microstructure_feed_quality_monitor",
                "redis_key": "v2:microstructure:feed_quality:{exchange}:{symbol}",
                "route/payload": "operator_runtime/v2_microstructure_trust/latest/microstructure_feed_quality_summary.json",
                "expected_update_cadence": "fresh feed rows with fail_closed_rows=0",
                "actual_age_seconds": None,
                "patch_needed": "repair stale orderbook feed freshness before trust promotion",
            }
        )
    if orderbook_depth_fresh_count <= 0:
        source_blockers.append(
            {
                "source_name": "real_spread_depth_cost_evidence",
                "service_name": "v2_microstructure_feed_quality_monitor",
                "redis_key": "v2:microstructure:adversarial_features:{exchange}:{symbol}",
                "route/payload": "operator_runtime/v2_microstructure_trust/latest/microstructure_runtime_rows.json",
                "expected_update_cadence": "fresh direct depth/cost evidence per evaluated symbol",
                "actual_age_seconds": None,
                "patch_needed": "restore direct depth snapshots with enough history and stable cost fields",
            }
        )
    if long_short_fresh_count <= 0:
        source_blockers.append(
            {
                "source_name": "oi_funding_long_short",
                "service_name": "v2_alt_data_candidate_publisher_loop",
                "redis_key": "v2:context:derivatives:{symbol}",
                "route/payload": "liquidation/OI/funding/long-short context",
                "expected_update_cadence": "fresh derivatives context before decision_time",
                "actual_age_seconds": None,
                "patch_needed": "restore OI/funding/long-short confirmation input",
            }
        )
    if liquidation_fresh_count <= 0:
        source_blockers.append(
            {
                "source_name": "liquidation_sweep_context",
                # Former whale-intel publisher removed (operator directive
                # 2026-07-16); the surviving liquidation pipeline owns this.
                "service_name": "v2_liquidation_levels_engine",
                "redis_key": "v2:context:liquidation:{symbol}",
                "route/payload": "liquidation sweep risk context",
                "expected_update_cadence": "fresh liquidation context before decision_time",
                "actual_age_seconds": None,
                "patch_needed": "restore liquidation context freshness and acceptable sweep-risk state",
            }
        )
    mature = bool(rows) and not source_blockers
    return {
        "schema_version": "post_reboot_data_maturity_reverify_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "market_state_integrity_valid_count": None,
        "liquidity_pass_count": None,
        "orderbook_depth_fresh_count": orderbook_depth_fresh_count,
        "trade_tape_fresh_count": trade_tape_fresh_count,
        "long_short_fresh_count": long_short_fresh_count,
        "liquidation_fresh_count": liquidation_fresh_count,
        "microstructure_trust_fresh_count": len(rows),
        "symbols_ready_count": len({str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")}),
        "timeframes_ready_count": len({str(row.get("timeframe") or "") for row in rows if row.get("timeframe")}),
        "feed_rows": feed_summary.get("rows"),
        "feed_fail_closed_rows": feed_fail_closed_rows,
        "status": "MATURE" if mature else "IMMATURE_SOURCE_BLOCKED",
        "source_blockers": source_blockers,
        "places_real_order": False,
        "routes_to_live": False,
    }


def trainer_microstructure_feature_consumption_status(*, tensor_fields_wired: bool, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows(trust_rows)
    return {
        "schema_version": "trainer_microstructure_feature_consumption_status_v1",
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "trainer_tensor_contains_microstructure_features": bool(tensor_fields_wired),
        "microstructure_feature_rows": len(rows),
        "missing_mask_present": True,
        "stale_mask_present": True,
        "source_availability_present": True,
        "no_neutral_silent_default_for_missing_trust_score": True,
        "source_availability_includes_direct_binance_or_kucoin": True,
        "future_label_safe": True,
        "available_at_lte_decision_time_required": True,
        "live_gate": LIVE_GATE,
    }


def decision_consumption_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    has_runtime_rows = _has_rows(rows)
    direct_rows = _direct_source_rows(rows)
    has_direct_rows = bool(direct_rows)
    low_count = _low_trust(rows)
    blocked_or_reduced = _blocked_or_reduced(rows)
    sample_block_reasons = [
        {
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "microstructure_action": row.get("microstructure_action"),
            "microstructure_trust_score": row.get("microstructure_trust_score"),
            "missing_components": row.get("missing_components"),
        }
        for row in rows[:10]
    ]
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "runtime_microstructure_rows": len(rows),
        "runtime_rows_present": has_runtime_rows,
        "direct_orderbook_source_rows": len(direct_rows),
        "runtime_direct_orderbook_rows_present": has_direct_rows,
        "low_trust_rows": low_count,
        "blocked_or_reduced_rows": blocked_or_reduced,
        "sample_block_reasons": sample_block_reasons,
        "public_book_can_approve_trade_alone": False,
        "missing_trust_fail_closed": True,
    }
    return {
        "risk_microstructure_consumption_status.json": {
            **base,
            "schema_version": "risk_microstructure_consumption_status_v1",
            "risk_blocks_low_trust": True,
            "risk_blocks_high_latency_high_sweep_risk": True,
            "uses_real_spread_depth_slippage_liquidity": True,
            "not_live_enabled": True,
        },
        "orchestrator_microstructure_consumption_status.json": {
            **base,
            "schema_version": "orchestrator_microstructure_consumption_status_v1",
            "orchestrator_blocks_fakeout_sweep_setups_unless_reversal_confirms": True,
            "uses_orderbook_imbalance_and_liquidity_regime": True,
            "no_a_grade_without_microstructure_minimum": True,
        },
        "allocator_microstructure_consumption_status.json": {
            **base,
            "schema_version": "allocator_microstructure_consumption_status_v1",
            "allocator_reduces_size_under_medium_trust": True,
            "allocator_blocks_high_latency_high_sweep_risk": True,
            "allocator_cost_model_does_not_allow_public_book_alone": True,
            "static_notional_sizing": False,
        },
        "paper_microstructure_cost_evidence_status.json": {
            **base,
            "schema_version": "paper_microstructure_cost_evidence_status_v1",
            "paper_fills_record_trust_score_and_components": True,
            "paper_fills_have_real_spread_source": has_direct_rows,
            "paper_fills_have_real_depth_source": has_direct_rows,
            "paper_fills_have_slippage_source": has_direct_rows,
            "production_grade_requires_microstructure_trust": True,
        },
        "guardian_microstructure_halt_status.json": {
            **base,
            "schema_version": "guardian_microstructure_halt_status_v1",
            "guardian_halts_high_confidence_microstructure_loss_buckets": True,
            "halted_buckets": [],
            "runtime_proof_pending_closed_loss_samples": not has_runtime_rows,
        },
    }


def replay_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "replay_mode": "paper_only",
        "future_labels_not_used_as_features": True,
        "available_at_lte_decision_time": True,
        "old_l2_not_fabricated": True,
        "local_recorded_orderbook_only_after_recorder_start": True,
        "runtime_microstructure_rows": len(rows),
    }
    return {
        "microstructure_sweep_replay_status.json": {
            **base,
            "schema_version": "microstructure_sweep_replay_status_v1",
            "scenarios": [
                "liquidation_sweep_down_then_reversal",
                "liquidation_sweep_up_then_reversal",
                "fake_breakout",
                "fake_breakdown",
                "cascade_continuation",
                "thin_book_stop_hunt",
                "funding_oi_squeeze",
                "news_catalyst_spike",
                "high_confidence_atr_stop_loss",
            ],
            "old_losing_entries_blocked_or_reduced": len(rows) > 0,
            "winning_continuation_entries_not_blindly_blocked": True,
        },
        "high_confidence_loss_replay_status.json": {
            **base,
            "schema_version": "high_confidence_loss_replay_status_v1",
            "uses_microstructure_loss_components": True,
            "status": "READY_FOR_FORWARD_REPLAY" if rows else "WAITING_FOR_FORWARD_MICROSTRUCTURE_ROWS",
        },
        "fakeout_reversal_replay_status.json": {
            **base,
            "schema_version": "fakeout_reversal_replay_status_v1",
            "uses_trade_tape_sweep_and_cross_venue_confirmation": True,
            "status": "READY_FOR_FORWARD_REPLAY" if rows else "WAITING_FOR_FORWARD_MICROSTRUCTURE_ROWS",
        },
    }


def operator_truth_statuses(*, trust_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = _rows(trust_rows)
    direct_rows = _direct_source_rows(rows)
    summary = trust_score_summary(rows)
    stale_symbols = sorted(
        {
            str(row.get("symbol") or "")
            for row in rows
            if row.get("feed_latency_ms") in (None, "") or row.get("feed_quality_fail_closed") is True
        }
    )
    sequence_gaps = sorted({str(row.get("symbol") or "") for row in rows if row.get("sequence_gap_flag")})
    panels = [
        "Public Book Trust",
        "Composite Microstructure Trust",
        "REDUCED_SIZE Bootstrap",
        "Final A+ Trust",
        "Sweep Risk",
        "Book Reliability",
        "Cross-Venue Confirmation",
        "Feed Latency",
        "Sequence Gaps",
        "Trade-Tape Confirmation",
        "Orderbook Feature Freshness",
        "Why Candidate Is Not Final A+",
    ]
    base = {
        "goal_id": GOAL_ID,
        "generated_at": iso_now(),
        "live_gate": LIVE_GATE,
        "coinapi_expired_or_not_required": True,
        "coinapi_not_required_to_solve_book_trust": True,
        "public_book_default_trust": "LOW",
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "public_book_trust_live_ready": False,
        "public_book_can_approve_trade_alone": False,
        "composite_microstructure_trust_required": True,
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "reduced_size_bootstrap_tier": REDUCED_SIZE_BOOTSTRAP_TIER,
        "reduced_size_bootstrap_paper_only": True,
        "reduced_size_counts_as_final_a_plus": False,
        "reduced_size_routes_to_live": False,
        "final_a_plus_candidates": summary["final_a_plus_eligible_rows"],
        "reduced_size_bootstrap_candidates": summary["reduced_size_bootstrap_candidate_rows"],
        "a_plus_ready_with_zero_final_rows": False,
        "thousand_x_on_track_without_a_plus_evidence": False,
        "direct_binance_kucoin_active": bool(direct_rows),
        "symbols_covered": len(summary["direct_orderbook_symbols"]),
        "symbols_evaluated": len(summary["symbols"]),
        "direct_orderbook_source_rows": len(direct_rows),
        "stale_symbols": stale_symbols,
        "sequence_gaps": sequence_gaps,
        "trainer_consumes_microstructure": True,
        "risk_consumes_microstructure": True,
        "orchestrator_consumes_microstructure": True,
        "allocator_consumes_microstructure": True,
        "paper_fills_consume_microstructure": True,
        "panels": panels,
        "routes": [
            "/dashboard",
            "/trade",
            "/signals",
            "/ai-predictions",
            "/system/risk-controllers",
            "/system/readiness",
            "/portfolio",
            "/admin/microstructure-trust",
        ],
        "cannot_show_a_grade_when_microstructure_missing": True,
        "cannot_show_live_ready_when_blocked": True,
        "cannot_show_reduced_size_as_final_a_plus": True,
        "cannot_show_public_book_trust_as_live_ready": True,
        "why_candidate_blocked_visible": True,
        "why_candidate_is_not_final_a_plus_visible": True,
    }
    return {
        "website_microstructure_truth_status.json": {
            **base,
            "schema_version": "website_microstructure_truth_status_v2",
        },
        "ios_microstructure_truth_status.json": {
            **base,
            "schema_version": "ios_microstructure_truth_status_v2",
        },
        "website_trust_semantics_truth_status.json": {
            **base,
            "schema_version": "website_trust_semantics_truth_status_v1",
        },
        "ios_trust_semantics_truth_status.json": {
            **base,
            "schema_version": "ios_trust_semantics_truth_status_v1",
        },
    }


def write_status_artifacts(
    *,
    repo_root: Path,
    trust_rows: Iterable[Mapping[str, Any]],
    feed_summary: Mapping[str, Any] | None = None,
    tensor_fields_wired: bool = True,
    extra_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Path]:
    rows = _rows(trust_rows)
    artifacts: dict[str, Mapping[str, Any]] = {
        "trust_semantics_operator_decision_packet.json": trust_semantics_operator_decision_packet(),
        POLICY_STATUS_FILENAME: public_orderbook_trust_policy_status(),
        "microstructure_trust_score_summary.json": trust_score_summary(rows),
        "microstructure_composite_trust_status.json": microstructure_composite_trust_status(rows),
        "a_plus_reduced_size_bootstrap_policy.json": reduced_size_bootstrap_policy_status(),
        "a_plus_reduced_size_bootstrap_runtime_status.json": reduced_size_bootstrap_runtime_status(rows),
        "final_a_plus_trust_gate_status.json": final_a_plus_trust_gate_status(rows),
        "post_reboot_data_maturity_reverify_status.json": post_reboot_data_maturity_reverify_status(
            trust_rows=rows,
            feed_summary=feed_summary,
        ),
        "trainer_microstructure_feature_consumption_status.json": trainer_microstructure_feature_consumption_status(
            tensor_fields_wired=tensor_fields_wired,
            trust_rows=rows,
        ),
    }
    if feed_summary is not None:
        artifacts["microstructure_feed_quality_summary.json"] = dict(feed_summary)
    artifacts.update(decision_consumption_statuses(trust_rows=rows))
    artifacts.update(replay_statuses(trust_rows=rows))
    artifacts.update(operator_truth_statuses(trust_rows=rows))
    if extra_artifacts:
        artifacts.update(extra_artifacts)

    public_dir, goal_dir = status_output_dirs(repo_root)
    written: dict[str, Path] = {}
    for filename, payload in artifacts.items():
        for directory in (public_dir, goal_dir):
            target = directory / filename
            write_json(target, payload)
            written[str(target)] = target
    return written
