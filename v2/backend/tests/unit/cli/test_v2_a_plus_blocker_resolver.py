from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_a_plus_blocker_resolver import resolve_blocker


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_resolver_selects_one_highest_volume_blocker_action(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_rejection_matrix.json",
        {
            "blocker_class_counts": {
                "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER": 7,
                "EXPECTED_NET_EDGE_BLOCKER": 3,
            },
            "total_candidate_count": 10,
        },
    )
    _write_json(tmp_path / "candidate_inventory_summary.json", {"total_candidate_count": 10})

    status = resolve_blocker(inventory_dir=tmp_path, output_dir=tmp_path)

    assert status["status"] == "BLOCKER_ACTION_SELECTED"
    assert status["selected_blocker_class"] == "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER"
    assert status["action"]["one_action_only"] is True
    assert status["action"]["forbidden_repair"] == "lowering loss-probability threshold"
    assert status["order_submitted"] is False
    assert (tmp_path / "blocker_resolution_status.json").exists()
    assert (tmp_path / "a_plus_repair_actions.jsonl").exists()


def test_resolver_generates_near_edge_candidate_action(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_rejection_matrix.json",
        {
            "blocker_class_counts": {"EXPECTED_NET_EDGE_BLOCKER": 2},
            "total_candidate_count": 2,
        },
    )
    _write_json(tmp_path / "candidate_inventory_summary.json", {"total_candidate_count": 2})
    _write_jsonl(
        tmp_path / "near_a_plus_candidate_rows.jsonl",
        [{"candidate_id": "near-1"}, {"candidate_id": "near-2"}],
    )

    status = resolve_blocker(inventory_dir=tmp_path, output_dir=tmp_path)

    assert status["action"]["action_name"] == "GENERATE_TOP_50_NEAR_A_PLUS_EDGE_CANDIDATES"
    assert status["action"]["top_50_near_a_plus_edge_candidate_count"] == 2


def test_resolver_stops_for_signed_read_operator_blocker(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_rejection_matrix.json",
        {
            "blocker_class_counts": {"SIGNED_READ_OPERATOR_BLOCKER": 1},
            "total_candidate_count": 1,
        },
    )
    _write_json(tmp_path / "candidate_inventory_summary.json", {"total_candidate_count": 1})

    status = resolve_blocker(inventory_dir=tmp_path, output_dir=tmp_path)

    assert status["action"]["action_name"] == "STOP_FOR_SIGNED_READ_OPERATOR_KEY"
    assert status["action"]["primary_blocker"] == "SIGNED_READ_OPERATOR_KEY_REQUIRED"
    assert status["action"]["rerun_inventory_required"] is False


def test_resolver_reports_exact_allocator_next_patch_after_simulation(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_rejection_matrix.json",
        {
            "blocker_class_counts": {"ALLOCATOR_BLOCKER": 3},
            "rejection_reason_counts": {
                "ALLOCATOR_INPUT_CURRENT_PRICE_MISSING": 3,
                "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE": 3,
            },
            "total_candidate_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_inventory_summary.json",
        {
            "total_candidate_count": 3,
            "allocator_decision_missing_count": 0,
            "allocator_decision_pass_count": 0,
            "allocator_decision_reject_count": 3,
        },
    )

    status = resolve_blocker(inventory_dir=tmp_path, output_dir=tmp_path)

    assert status["selected_blocker_class"] == "ALLOCATOR_BLOCKER"
    assert status["action"]["action_name"] == "WIRE_CURRENT_PRICE_INTO_ALLOCATOR_INPUT_FROM_FINAL_CANDLE_OR_MARK_PRICE"
    assert status["action"]["allocator_simulation_executed"] is True
    assert status["action"]["allocator_missing_count"] == 0
    assert status["action"]["primary_allocator_reject_reason"] == "ALLOCATOR_INPUT_CURRENT_PRICE_MISSING"
    assert status["action"]["exact_function"] == "v2.backend.app.services.allocator.simulation.build_allocator_simulation"
    assert status["action"]["exact_next_patch"] == "WIRE_CURRENT_PRICE_INTO_ALLOCATOR_INPUT_FROM_FINAL_CANDLE_OR_MARK_PRICE"


def test_resolver_writes_phase0_truth_and_phase1_failure_decomposition(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_rejection_matrix.json",
        {
            "blocker_class_counts": {"ALLOCATOR_BLOCKER": 1},
            "rejection_reason_counts": {"ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE": 1},
            "total_candidate_count": 1,
        },
    )
    _write_json(
        tmp_path / "candidate_inventory_summary.json",
        {
            "total_candidate_count": 1,
            "allocator_decision_pass_count": 0,
            "allocator_decision_reject_count": 1,
            "allocator_decision_status_counts": {"REJECT": 1},
            "hard_fail": False,
            "hard_failures": {},
        },
    )
    _write_jsonl(
        tmp_path / "candidate_inventory.jsonl",
        [
            {
                "candidate_id": "cand-1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "side": None,
                "no_side_reason": "MODEL_HOLD_OR_NO_TRADE_ACTION",
                "current_price": 65000.0,
                "expected_move": -1.0,
                "expected_gross_pnl_usd": 0.0,
                "fees_usd": 0.1,
                "slippage_usd": 0.1,
                "funding_usd": 0.0,
                "latency_reserve_usd": 0.0,
                "liquidation_risk_reserve_usd": 0.0,
                "exit_failure_reserve_usd": 0.0,
                "expected_cost_usd": 0.2,
                "expected_net_pnl_usd": -0.2,
                "expected_max_loss_usd": 1.0,
                "pre_trade_loss_probability": 0.9,
                "confidence_raw": 0.9,
                "confidence_calibrated": 0.4,
                "feature_vector_hash": "hash",
                "feature_cutoff": "2026-07-08T20:59:00Z",
                "decision_time": "2026-07-08T21:00:00Z",
                "preemptive_decision_id": "pec",
                "allocator_decision_id": "alloc",
                "allocator_decision": "REJECT",
                "block_reasons": ["TRAINER_SIDE_MISSING_OR_HOLD", "EXPECTED_NET_EDGE_NON_POSITIVE"],
                "allocator_block_reasons": ["ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE"],
            }
        ],
    )

    resolve_blocker(inventory_dir=tmp_path, output_dir=tmp_path)

    phase0 = json.loads((tmp_path / "phase0_current_edge_blocker_truth.json").read_text(encoding="utf-8"))
    phase1 = json.loads((tmp_path / "phase1_edge_failure_decomposition.json").read_text(encoding="utf-8"))
    phase4_root = json.loads((tmp_path / "phase4_expected_move_root_cause.json").read_text(encoding="utf-8"))
    phase4_lab = json.loads((tmp_path / "phase4_strategy_edge_lab_results.json").read_text(encoding="utf-8"))
    rows = (tmp_path / "phase1_candidate_failure_matrix.jsonl").read_text(encoding="utf-8").splitlines()
    first_row = json.loads(rows[0])

    assert phase0["total_candidates"] == 1
    assert phase0["expected_net_pnl_usd_distribution"]["negative_count"] == 1
    assert phase1["unknown_count"] == 0
    assert phase1["generic_allocator_only_without_exact_economics_count"] == 0
    assert phase1["primary_cause_counts"]["EXPECTED_MOVE_NON_POSITIVE"] == 1
    assert first_row["primary_cause"] == "EXPECTED_MOVE_NON_POSITIVE"
    assert first_row["formula_expected_net_pnl_usd"] == -0.2
    assert phase4_root["positive_expected_net_pnl_usd_count"] == 0
    assert phase4_lab["promotion_summary"]["promoted_strategy_count"] == 0
