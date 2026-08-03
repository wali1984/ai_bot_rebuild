"""Synthetic A+ evaluator contract tests with no paper or runtime authority."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.a_plus_trade_gate.service import CHECKS, evaluate_a_plus_candidate

GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
EVIDENCE_SCOPE = "SYNTHETIC_CONTRACT_TEST_ONLY"
CONTRACT_TEST_PASSED = "CONTRACT_TEST_PASSED_NON_RUNTIME"
CONTRACT_TEST_FAILED = "CONTRACT_TEST_FAILED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _non_runtime_evidence_boundary(generated_utc: str) -> dict[str, Any]:
    return {
        "evidence_scope": EVIDENCE_SCOPE,
        "contract_test_only": True,
        "canonical_current_cycle_contract_consumed": False,
        "canonical_current_cycle_contract_verified": False,
        "canonical_runtime_ready": False,
        "serving_authorized": False,
        "a_plus_authorized": False,
        "paper_authorized": False,
        "live_authorized": False,
        "live_execution_authorized": False,
        "routes_to_paper": False,
        "routes_to_live": False,
        "paper_only": True,
        "producer_clock_field": "generated_utc",
        "artifact_generated_at": generated_utc,
        "artifact_persistence": "OVERWRITTEN_NON_EXPIRING_JSON_SNAPSHOT",
        "artifact_ttl_enforced": False,
        "artifact_expires_at": None,
        "artifact_freshness_authoritative": False,
        "runtime_authority_block_reason": (
            "SYNTHETIC_CANDIDATE_MATRIX_DOES_NOT_AUTHORIZE_A_PLUS_OR_RUNTIME"
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _baseline(now: str) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "strategy_id": "trend_mode",
        "confidence_calibrated": 0.82,
        "atr_bps": 22.0,
        "entry_timeframe_trend": "UP",
        "prediction_row": {
            "expected_move_after_cost_bps": 18.0,
            "missing_feature_count": 0,
            "stale_feature_count": 0,
            "feature_freshness_state": "CURRENT",
        },
        "intent": {
            "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
            "production_grade_cost_flag": True,
        },
        "risk_result": {"allowed": True, "reasons": []},
        "allocation": {"approved_notional_usd": 25.0, "allocator_decision": "APPROVE"},
        "bucket_quarantine_status": {"status": "CLEAR", "quarantine_active": False},
        "context": {
            "trainer_metrics": {
                "training": {
                    "metrics": {
                        "online_learning_status": "ACTIVE",
                        "trusted_rows_loaded": 4096,
                        "last_successful_weight_update_at": now,
                    }
                }
            },
            "side_performance": {
                "sides": {
                    "LONG": {"trade_count": 3, "expectancy_bps": 12.0, "brier_score": 0.10},
                    "SHORT": {"trade_count": 3, "expectancy_bps": 10.0, "brier_score": 0.10},
                }
            },
            "regime_decision": {
                "generated_utc": now,
                "regime": "TRENDING_UP",
                "confidence": 0.88,
                "fail_closed": False,
            },
            "htf_context": {
                "generated_utc": now,
                "htf_4h_trend": "UP",
                "htf_4h_macd_state": "BULLISH",
                "htf_1d_ema_direction": "UP",
                "htf_4h_rsi_zone": "BULLISH",
            },
            "cross_asset": {"btc_direction_4h": "UP", "risk_off_proxy": False},
            "trade_tape": {
                "generated_utc": now,
                "trade_tape_confirmation_state": "TAPE_DATA_OK",
                "trade_tape_confirmation_score": 0.82,
            },
            "microstructure_trust": {
                "composite_microstructure_trust_score": 0.82,
                "microstructure_trust_score": 0.82,
                "orderbook_trust_tier": "FINAL_A_PLUS_ELIGIBLE",
                "microstructure_action": "ALLOW",
                "public_book_can_approve_trade_alone": False,
                "public_orderbook_can_produce_final_a_plus": False,
                "bootstrap_reduced_size_paper_only": False,
                "reduced_size_counts_as_final_a_plus": False,
                "feed_integrity_pass": True,
                "sequence_gap_free": True,
                "latency_within_bound": True,
                "trade_tape_confirmation_pass": True,
                "cross_venue_confirmation_pass": True,
                "liquidation_sweep_risk_acceptable": True,
                "oi_funding_long_short_confirmation_pass": True,
                "real_spread_depth_cost_evidence_pass": True,
            },
            "feedback_rows": [],
        },
    }


def _copy_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(candidate))


def _evaluate(label: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
    result = evaluate_a_plus_candidate(**candidate)
    return {
        "evidence_scope": EVIDENCE_SCOPE,
        "synthetic_fixture": True,
        "eligible_as_runtime_candidate": False,
        "canonical_a_plus_authorized": False,
        "paper_authorized": False,
        "live_authorized": False,
        "label": label,
        "symbol": result["symbol"],
        "timeframe": result["timeframe"],
        "side": result["side"],
        "strategy_id": result["strategy_id"],
        "contract_evaluator_a_plus": result["a_plus"],
        "contract_evaluator_paper_tradeable": result["paper_tradeable"],
        "contract_evaluator_live_candidate_eligible": result["live_candidate_eligible"],
        "failed_checks": result["failed_checks"],
        "missing_evidence_checks": result["missing_evidence_checks"],
        "passed_check_count": result["passed_check_count"],
        "check_count": result["check_count"],
        "checks": result["checks"],
        "fail_closed": result["fail_closed"],
        "live_gate": result["live_gate"],
        "places_real_order": result["places_real_order"],
        "writes_legacy_redis": result["writes_legacy_redis"],
    }


def _rejection_cases(base: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []

    def add(check: str, label: str, mutate) -> None:
        candidate = _copy_candidate(base)
        mutate(candidate)
        cases.append((check, label, candidate))

    add(
        "trainer_online_learning_active",
        "trainer_learning_missing",
        lambda c: c["context"].pop("trainer_metrics"),
    )
    add(
        "side_bucket_positive",
        "side_expectancy_non_positive",
        lambda c: c["context"]["side_performance"]["sides"]["LONG"].update({"trade_count": 8, "expectancy_bps": -1.0}),
    )
    add(
        "regime_aligned",
        "trend_long_blocked_in_ranging",
        lambda c: c["context"]["regime_decision"].update({"regime": "RANGING"}),
    )
    add(
        "htf_aligned",
        "htf_bearish_for_long",
        lambda c: c["context"]["htf_context"].update(
            {"htf_4h_trend": "DOWN", "htf_4h_macd_state": "BEARISH", "htf_1d_ema_direction": "DOWN"}
        ),
    )
    add(
        "trade_tape_confirms",
        "trade_tape_contradicts_long",
        lambda c: c["context"]["trade_tape"].update({"trade_tape_confirmation_score": 0.18}),
    )
    add(
        "microstructure_trust_confirms",
        "microstructure_trust_below_floor",
        lambda c: c["context"]["microstructure_trust"].update(
            {"composite_microstructure_trust_score": 0.30, "microstructure_trust_score": 0.30}
        ),
    )
    add("risk_allows", "risk_blocks", lambda c: c.update({"risk_result": {"allowed": False, "reasons": ["risk_block"]}}))
    add(
        "allocator_allows",
        "allocator_blocks",
        lambda c: c.update({"allocation": {"blocked": True, "block_reason": "allocator_block"}}),
    )
    add("exit_plan_valid", "atr_missing_exit_plan", lambda c: c.update({"atr_bps": None}))
    add("cost_evidence_production_grade", "cost_evidence_missing", lambda c: c.update({"intent": {}}))
    add(
        "no_quarantine_bucket",
        "candidate_bucket_quarantined",
        lambda c: c.update(
            {
                "bucket_quarantine_status": {
                    "status": "ACTIVE",
                    "quarantine_active": True,
                    "blocked_bucket_keys": ["side_timeframe:long|1m"],
                }
            }
        ),
    )
    add(
        "no_stale_or_missing_critical_feature",
        "missing_critical_feature",
        lambda c: c["prediction_row"].update({"missing_feature_count": 1, "missing_feature_names": ["close"]}),
    )
    add(
        "no_recent_high_confidence_loss_in_bucket",
        "recent_high_confidence_loss",
        lambda c: c["context"].update(
            {
                "feedback_rows": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "action": "long",
                        "strategy_id": "trend_mode",
                        "confidence_calibrated": 0.91,
                        "realized_pnl_bps": -12.0,
                        "exit_time": c["context"]["regime_decision"]["generated_utc"],
                    }
                ]
            }
        ),
    )
    return cases


def build_phase8_a_plus_gate_artifacts() -> dict[str, Any]:
    now = _utc_now()
    base = _baseline(now)
    accepted = _evaluate("synthetic_a_plus_candidate", base)
    rejected: list[dict[str, Any]] = []
    for expected_check, label, candidate in _rejection_cases(base):
        row = _evaluate(label, candidate)
        row["expected_failed_check"] = expected_check
        row["expected_failed_check_present"] = expected_check in set(row["failed_checks"])
        rejected.append(row)
    reject_counter: Counter[str] = Counter()
    for row in rejected:
        reject_counter.update(str(check) for check in row["failed_checks"])
    no_non_a_plus_live = all(
        row["contract_evaluator_live_candidate_eligible"] is False for row in rejected
    )
    rejection_proofs_passed = all(
        row["contract_evaluator_a_plus"] is False
        and row["expected_failed_check_present"]
        for row in rejected
    )
    accepted_passed = (
        accepted["contract_evaluator_a_plus"] is True
        and accepted["contract_evaluator_paper_tradeable"] is True
    )
    contract_test_conditions = {
        "a_plus_candidate_positive_path_exists": accepted_passed,
        "all_required_checks_present": set(CHECKS) == set(accepted["checks"]),
        "all_required_checks_can_fail_closed": rejection_proofs_passed,
        "no_non_a_plus_row_can_be_live": no_non_a_plus_live,
        "live_gate_blocked_human_only": accepted["live_gate"] == "blocked_human_only",
        "places_real_order_false": accepted["places_real_order"] is False and all(row["places_real_order"] is False for row in rejected),
        "writes_legacy_redis_false": accepted["writes_legacy_redis"] is False and all(row["writes_legacy_redis"] is False for row in rejected),
    }
    contract_tests_passed = all(contract_test_conditions.values())
    boundary = _non_runtime_evidence_boundary(now)
    status = {
        "schema_version": "a_plus_trade_gate_contract_status_v2",
        "goal_id": GOAL_ID,
        "generated_utc": now,
        **boundary,
        "status": CONTRACT_TEST_PASSED if contract_tests_passed else CONTRACT_TEST_FAILED,
        "contract_tests_passed": contract_tests_passed,
        "required_checks": list(CHECKS),
        "synthetic_contract_acceptance_count": 1 if accepted_passed else 0,
        "canonical_a_plus_candidate_count": 0,
        "rejected_case_count": len(rejected),
        "contract_test_conditions": contract_test_conditions,
        "production_gate_evaluated": False,
        "contract_under_test": "evaluate_a_plus_candidate",
        "contract_gate_semantics_fail_closed": True,
        "fail_closed": True,
        "contract_paper_tradeable_requires_a_plus": True,
        "contract_live_candidate_requires_a_plus": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
    }
    return {
        "status": status,
        "candidate_matrix": {
            "schema_version": "a_plus_synthetic_contract_candidate_matrix_v2",
            "goal_id": GOAL_ID,
            "generated_utc": now,
            **boundary,
            "accepted_candidates": [accepted],
            "rejected_candidates": rejected,
            "canonical_a_plus_candidate_count": 0,
            "live_gate": "blocked_human_only",
            "places_real_order": False,
            "writes_legacy_redis": False,
        },
        "rejected_reason_matrix": {
            "schema_version": "a_plus_synthetic_rejected_reason_matrix_v2",
            "goal_id": GOAL_ID,
            "generated_utc": now,
            **boundary,
            "rejected_reason_counts": dict(sorted(reject_counter.items())),
            "rejected_case_count": len(rejected),
            "all_rejections_fail_closed": rejection_proofs_passed and no_non_a_plus_live,
            "live_gate": "blocked_human_only",
            "places_real_order": False,
            "writes_legacy_redis": False,
        },
    }


def write_phase8_a_plus_gate_artifacts(*, goal_dir: Path, public_dir: Path | None = None) -> dict[str, Any]:
    artifacts = build_phase8_a_plus_gate_artifacts()
    files = {
        "a_plus_trade_gate_status.json": artifacts["status"],
        "a_plus_candidate_matrix.json": artifacts["candidate_matrix"],
        "a_plus_rejected_reason_matrix.json": artifacts["rejected_reason_matrix"],
    }
    for name, payload in files.items():
        _write_json(goal_dir / name, payload)
        if public_dir is not None:
            _write_json(public_dir / name, payload)
    return artifacts["status"]
