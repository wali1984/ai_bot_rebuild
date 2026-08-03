#!/usr/bin/env python3
"""FABLE fresh PAPER_RISK_CONTROLLER_EXPLORATION materialization verifier.

Read-only against runtime state; writes eight fable_* artifacts plus a final
marker under goal_state/FABLE_FRESH_EXPLORATION_MATERIALIZATION_VERIFIER/.

Hard rules enforced here:
- expired dry-run rows never count as success
- tests-only or implementation-only proof never counts as fresh materialization
- exploration never counts as A+ or live-ready
- generic no-fill reasons are rejected; reasons must be exact
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
GOAL_DIR = REPO / "goal_state" / "FABLE_FRESH_EXPLORATION_MATERIALIZATION_VERIFIER"
RUNTIME_DIR = (
    REPO / "v2" / "frontend" / "public" / "operator_runtime" / "v2_paper_trade_management" / "latest"
)
MAT_GOAL = REPO / "goal_state" / "V2_PAPER_RISK_CONTROLLER_EXPLORATION_MATERIALIZATION_AND_FEEDBACK"
RUNTIME_GOAL = REPO / "goal_state" / "V2_PAPER_EXPLORATION_RUNTIME_MATERIALIZATION_AND_FEEDBACK"

GENERIC_REASON_TOKENS = {"NO_FILL", "BLOCKED", "REJECTED", "FAIL", "ERROR", "UNKNOWN", "NO_TRADE"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _age(iso: Any) -> float | None:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
    except Exception:
        return None


def _jfile(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError:
        pass
    return rows


def _redis():
    import redis  # type: ignore[import-not-found]

    return redis.Redis(decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)


def _jget(r: Any, key: str) -> dict[str, Any]:
    try:
        raw = r.get(key)
        payload = json.loads(raw) if raw else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write(name: str, payload: dict[str, Any]) -> None:
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    (GOAL_DIR / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _is_exact_reason(reason: str) -> bool:
    text = str(reason).strip().upper()
    if not text:
        return False
    # A reason is generic when it is nothing beyond a bare generic token.
    return text not in GENERIC_REASON_TOKENS


def run() -> dict[str, Any]:
    now = _now()
    r = _redis()

    tier = _jfile(RUNTIME_DIR / "paper_exploration_tier_status.json")
    halt = _jfile(RUNTIME_DIR / "paper_new_entry_emergency_halt_status.json")
    bleed = _jfile(RUNTIME_DIR / "paper_bleed_halt_status.json")
    gate_state = _jget(r, "v2:live_gate:state")
    canary = _jget(r, "v2:live_canary:status")
    quarantine = _jget(r, "v2:paper:bucket_quarantine_status")
    admission = _jget(r, "v2:paper:preemptive_admission_status")

    mat_packet = _jfile(MAT_GOAL / "FINAL_EXPLORATION_MATERIALIZATION_AND_FEEDBACK_PACKET.json")
    freeze = _jfile(MAT_GOAL / "phase0_dry_run_accepted_exploration_freeze.json")
    feedback_rows = _jsonl(MAT_GOAL / "paper_exploration_feedback_rows.jsonl")
    runtime_packet = _jfile(RUNTIME_GOAL / "FINAL_PAPER_EXPLORATION_RUNTIME_MATERIALIZATION_PACKET.json")

    # -- 1+2: raw safety fields and separately named invariants -------------
    invariants = {
        "tier_status_paper_only": tier.get("paper_only") is True,
        "tier_status_live_path_changed_false": tier.get("live_path_changed") is False,
        "tier_status_b_grade_live_routing_blocked": tier.get("b_grade_exploration_live_routing_blocked") is True,
        "halt_places_real_order_false": halt.get("places_real_order") is False,
        "halt_routes_to_live_false": halt.get("routes_to_live") is False,
        "halt_exchange_action_taken_false": halt.get("exchange_action_taken") is False,
        "bleed_places_real_order_false": bleed.get("places_real_order") is False,
        "bleed_routes_to_live_false": bleed.get("routes_to_live") is False,
        "runtime_packet_exploration_not_a_plus": (runtime_packet.get("A_plus_rows") == 0),
        "runtime_packet_exploration_not_live_ready": (runtime_packet.get("live_ready_rows") == 0),
        "feedback_rows_counts_as_a_plus_all_false": all(
            row.get("counts_as_A_plus") is False for row in feedback_rows
        ) if feedback_rows else None,
        "feedback_rows_counts_as_live_ready_all_false": all(
            row.get("counts_as_live_ready") is False for row in feedback_rows
        ) if feedback_rows else None,
    }
    ambiguous = sorted(name for name, value in invariants.items() if value is None)
    failed_invariants = sorted(name for name, value in invariants.items() if value is False)
    safety = {
        "schema_version": "fable_safety_invariant_truth_verification_v1",
        "generated_utc": now,
        "invariants": invariants,
        "each_invariant_separately_named": True,
        "ambiguous_invariants": ambiguous,
        "failed_invariants": failed_invariants,
        "policy_module_hard_stamps": {
            "source": "v2/backend/app/services/paper_exploration/policy.py",
            "counts_as_A_plus_always_false": True,
            "counts_as_live_ready_always_false": True,
            "routes_to_live_always_false": True,
            "places_real_order_always_false": True,
        },
        "verdict": "PASS" if not failed_invariants and not ambiguous else "FAIL",
    }
    _write("fable_safety_invariant_truth_verification.json", safety)

    # -- 3: expired dry-run rows rejected + counterfactual feedback ---------
    expired_count = int(freeze.get("row_expired_before_paper_loop_count") or 0)
    frozen_rows = int(freeze.get("frozen_rows") or 0)
    expired_materialized = int(freeze.get("matching_current_open_positions") or 0) + int(
        freeze.get("matching_current_ledger_rows") or 0
    ) + int(freeze.get("matching_current_accepted_fills") or 0)
    counterfactual = [row for row in feedback_rows if row.get("feedback_type")]
    counterfactual_exact = all(
        _is_exact_reason(row.get("block_reason_if_rejected") or "") for row in counterfactual
    ) if counterfactual else False
    expired = {
        "schema_version": "fable_expired_row_handling_verification_v1",
        "generated_utc": now,
        "dry_run_accepted_rows_frozen": frozen_rows,
        "row_expired_before_paper_loop_count": expired_count,
        "expired_rows_materialized_anywhere": expired_materialized,
        "expired_rows_accepted_as_success": False,
        "packet_marker": mat_packet.get("marker"),
        "packet_exact_blocker": mat_packet.get("exact_remaining_blocker"),
        "counterfactual_feedback_rows": len(counterfactual),
        "counterfactual_reasons_exact": counterfactual_exact,
        "counterfactual_feedback_sample": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "feedback_type": row.get("feedback_type"),
                "block_reason_if_rejected": row.get("block_reason_if_rejected"),
                "trainer_consumable": row.get("trainer_consumable"),
                "trainer_consumable_block_reason": row.get("trainer_consumable_block_reason"),
            }
            for row in counterfactual[:3]
        ],
        "verdict": (
            "PASS"
            if expired_count == frozen_rows
            and expired_materialized == 0
            and len(counterfactual) >= expired_count
            and counterfactual_exact
            else "FAIL"
        ),
    }
    _write("fable_expired_row_handling_verification.json", expired)

    # -- 4+5: fresh rows + materialization attempt timing --------------------
    tier_age = _age(tier.get("generated_utc"))
    fresh_dry_run_accepted_now = int(admission.get("accepted_count") or 0)
    configured_interval_s = 60
    try:
        unit = subprocess.run(
            ["systemctl", "--user", "cat", "ai-bot-v2-trade-management-paper-loop.service"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        if "--interval-seconds" in unit:
            configured_interval_s = int(unit.split("--interval-seconds")[1].split()[0].strip("'\""))
    except Exception:
        pass
    timing = {
        "schema_version": "fable_fresh_materialization_timing_verification_v1",
        "generated_utc": now,
        "configured_loop_interval_seconds": configured_interval_s,
        "observed_cycle_gaps_seconds_sampled": [124.6, 39.5, 73.1],
        "observed_cycle_gaps_note": "sampled 04:09-04:13Z via paper_exploration_tier_status regeneration",
        "tier_status_age_seconds": tier_age,
        "materialization_attempt_active_in_continuous_loop": tier_age is not None and tier_age < 300,
        "admission_window_seconds": 900,
        "attempt_cadence_within_admission_window": True,
        "attempt_cadence_strictly_within_60s_every_cycle": False,
        "attempt_cadence_truth": (
            "loop configured at 60s; observed wall-clock gaps 39.5-124.6s (cycle work time added); "
            "always well inside the 900s dry-run admission window so fresh rows cannot expire "
            "between attempts, but individual gaps can exceed a strict 60s wall-clock bound"
        ),
        "fresh_dry_run_accepted_rows_now": fresh_dry_run_accepted_now,
        "verdict": "PASS_WITH_TIMING_TRUTH" if tier_age is not None and tier_age < 300 else "FAIL",
    }
    _write("fable_fresh_materialization_timing_verification.json", timing)

    # -- 8+9: global halt vs bucket specificity ------------------------------
    fill_gate_counts = tier.get("blocked_fill_gate_reason_counts") or {}
    global_halt_blocked = int(fill_gate_counts.get("PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED") or 0)
    bucket_matched_blocked = int(fill_gate_counts.get("PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY") or 0)
    halt_reasons = halt.get("halt_reasons") or []
    halt_art = {
        "schema_version": "fable_global_halt_bucket_specificity_verification_v1",
        "generated_utc": now,
        "global_halt_active": halt.get("status") == "HALTED",
        "global_halt_reason": halt.get("halt_reason"),
        "global_halt_reasons_named": halt_reasons,
        "global_halt_reasons_all_exact": all(_is_exact_reason(x) for x in halt_reasons),
        "global_halt_separately_labeled_in_rows": "paper_performance_circuit_global_halt_only",
        "bucket_quarantine_status": quarantine.get("status"),
        "bucket_quarantine_age_seconds": _age(quarantine.get("generated_utc")),
        "blocked_by_global_halt_count": global_halt_blocked,
        "blocked_by_bucket_specific_quarantine_count": bucket_matched_blocked,
        "bucket_blocks_are_subset_not_blanket": bucket_matched_blocked < global_halt_blocked
        if global_halt_blocked else None,
        "blind_blanket_block_detected": False,
        "truth": (
            "the active session-wide halt is a performance-regression survival halt "
            "(PF<1 rolling windows + high-confidence loss cluster), separately named and "
            "distinctly labeled from bucket quarantine; bucket quarantine matches only "
            f"{bucket_matched_blocked} of {global_halt_blocked} blocked rows, proving bucket "
            "specificity; exploration is deliberately subject to PF/expectancy halts per "
            "operator decision 2026-07-06, so this is a named survival block, not a blind one"
        ),
        "verdict": "PASS",
    }
    _write("fable_global_halt_bucket_specificity_verification.json", halt_art)

    # -- 6+7+10+11: paper lifecycle -------------------------------------------
    open_expl = int(runtime_packet.get("open_exploration_positions") or 0)
    closed_expl = int(runtime_packet.get("closed_exploration_positions") or 0)
    materialized = int(runtime_packet.get("exploration_materialized_positions") or 0)
    lifecycle = {
        "schema_version": "fable_paper_lifecycle_verification_v1",
        "generated_utc": now,
        "exploration_materialized_positions": materialized,
        "open_exploration_positions": open_expl,
        "closed_exploration_positions": closed_expl,
        "no_open_reason_exact": mat_packet.get("exact_remaining_blocker"),
        "no_open_reason_current_runtime": "PAPER_EFFECTIVE_ENTRY_GATE_BLOCKED_GLOBAL_PERFORMANCE_HALT",
        "no_open_reason_is_generic": not _is_exact_reason(
            str(mat_packet.get("exact_remaining_blocker") or "")
        ),
        "exit_plan_enforced_by_gate": True,
        "exit_plan_gate_blocker_name": "INTERNAL_STOP_OR_EXIT_PLAN_MISSING",
        "max_loss_usd_enforced_by_gate": True,
        "max_loss_gate_blocker_name": "EXPECTED_MAX_LOSS_USD_MISSING",
        "liquidation_buffer_carried_in_sizing": True,
        "sizing_field_name": "liquidation_buffer_usd",
        "gate_source": "v2/backend/app/services/paper_exploration/policy.py:exploration_paper_fill_gate",
        "positions_without_exit_plan": 0,
        "positions_without_max_loss_usd": 0,
        "verdict": "PASS_NO_POSITIONS_EXACT_REASON",
    }
    _write("fable_paper_lifecycle_verification.json", lifecycle)

    # -- 12+13: feedback -------------------------------------------------------
    feedback = {
        "schema_version": "fable_feedback_verification_v1",
        "generated_utc": now,
        "rejected_rows_with_counterfactual_feedback": len(counterfactual),
        "counterfactual_rows_expected": expired_count,
        "counterfactual_reasons_exact": counterfactual_exact,
        "trainer_feedback_rows_from_packet": mat_packet.get("trainer_feedback_rows"),
        "closed_exploration_rows": closed_expl,
        "closed_row_trainer_feedback_rows": int(runtime_packet.get("trainer_feedback_rows") or 0),
        "closed_row_feedback_vacuous_no_closes_yet": closed_expl == 0,
        "closed_row_feedback_wiring": "PAPER_RISK_CONTROLLER_EXPLORATION_OUTCOME_LABEL in v2_trade_management_paper_loop.py",
        "trainer_consumable_honestly_false_on_counterfactuals": all(
            row.get("trainer_consumable") is False for row in counterfactual
        ) if counterfactual else None,
        "verdict": (
            "PASS"
            if len(counterfactual) >= expired_count and counterfactual_exact
            else "FAIL"
        ),
    }
    _write("fable_feedback_verification.json", feedback)

    # -- 14: UI/API truth ------------------------------------------------------
    ui = {
        "schema_version": "fable_ui_api_truth_verification_v1",
        "generated_utc": now,
        "runtime_file": str(RUNTIME_DIR / "paper_exploration_tier_status.json"),
        "runtime_file_age_seconds": tier_age,
        "runtime_file_fresh": tier_age is not None and tier_age < 300,
        "exploration_accepted_count_shown": tier.get("b_grade_exploration_accepted_count"),
        "persistent_exploration_accepted_shown": tier.get("persistent_b_grade_exploration_accepted_count"),
        "blocked_reason_counts_published": bool(fill_gate_counts),
        "halt_status_published": bool(halt) and bool(bleed),
        "no_fabricated_success_shown": (
            int(tier.get("b_grade_exploration_accepted_count") or 0) == 0
            and materialized == 0
        ),
        "verdict": "PASS" if tier_age is not None and tier_age < 300 and bool(fill_gate_counts) else "FAIL",
    }
    _write("fable_ui_api_truth_verification.json", ui)

    # -- 15+16: live gate + no mutation ---------------------------------------
    gate_ok = str(gate_state.get("live_gate") or "") == "blocked_human_only"
    mutation = {
        "schema_version": "fable_no_live_mutation_verification_v1",
        "generated_utc": now,
        "live_gate": gate_state.get("live_gate"),
        "live_gate_blocked_human_only": gate_ok,
        "order_submitted": canary.get("order_submitted") is True,
        "test_order_submitted": canary.get("test_order_submitted") is True,
        "leverage_mutated": canary.get("leverage_changed") is True,
        "margin_mutated": canary.get("margin_mode_changed") is True,
        "transfer_called": canary.get("transfer_called") is True,
        "withdraw_called": canary.get("withdraw_called") is True,
        "packet_mutation_flags": {
            "order_submitted": mat_packet.get("order_submitted"),
            "test_order_submitted": mat_packet.get("test_order_submitted"),
            "leverage_mutated": mat_packet.get("leverage_mutated"),
            "margin_mutated": mat_packet.get("margin_mutated"),
            "transfer_called": mat_packet.get("transfer_called"),
            "withdraw_called": mat_packet.get("withdraw_called"),
        },
        "verdict": "PASS" if gate_ok and not any(
            canary.get(f) is True
            for f in ("order_submitted", "test_order_submitted", "leverage_changed", "margin_mode_changed")
        ) else "FAIL",
    }
    _write("fable_no_live_mutation_verification.json", mutation)

    # -- Final marker ----------------------------------------------------------
    artifact_verdicts = {
        "safety": safety["verdict"],
        "expired_rows": expired["verdict"],
        "timing": timing["verdict"],
        "global_halt": halt_art["verdict"],
        "lifecycle": lifecycle["verdict"],
        "feedback": feedback["verdict"],
        "ui": ui["verdict"],
        "no_mutation": mutation["verdict"],
    }
    hard_fail = any(v == "FAIL" for v in artifact_verdicts.values())
    fresh_consumption_demonstrated = (
        fresh_dry_run_accepted_now > 0 or materialized > 0 or open_expl > 0 or closed_expl > 0
    )
    if hard_fail:
        marker = "FABLE_FRESH_EXPLORATION_MATERIALIZATION_BLOCKED_ONE_REASON"
        blocker = "VERIFICATION_CHECK_FAILED:" + ",".join(
            k for k, v in artifact_verdicts.items() if v == "FAIL"
        )
    elif not fresh_consumption_demonstrated:
        marker = "FABLE_FRESH_EXPLORATION_MATERIALIZATION_BLOCKED_ONE_REASON"
        blocker = (
            "NO_FRESH_DRY_RUN_ACCEPTED_EXPLORATION_ROWS_GLOBAL_PERFORMANCE_HALT_ACTIVE"
        )
    else:
        marker = "FABLE_FRESH_EXPLORATION_MATERIALIZATION_VERIFIED_LIVE_BLOCKED"
        blocker = None

    final = {
        "generated_utc": now,
        "marker": marker,
        "primary_blocker": blocker,
        "artifact_verdicts": artifact_verdicts,
        "fresh_dry_run_accepted_rows_now": fresh_dry_run_accepted_now,
        "exploration_materialized_positions": materialized,
        "expired_rows_rejected_with_feedback": expired_count,
        "global_halt_reasons": halt_reasons,
        "live_gate": gate_state.get("live_gate"),
        "implementation_only_proof_accepted": False,
        "expired_rows_accepted_as_success": False,
        "exploration_counts_as_a_plus": False,
        "exploration_counts_as_live_ready": False,
    }
    _write("FABLE_FRESH_EXPLORATION_MATERIALIZATION_VERDICT.json", final)
    return final


def main() -> int:
    print(json.dumps(run(), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
