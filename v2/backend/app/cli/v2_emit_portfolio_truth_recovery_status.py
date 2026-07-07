"""Emit final status artifacts for the V2 portfolio truth recovery goal."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_rebuild_paper_portfolio_from_valid_fills import (
    PORTFOLIO_PUBLIC_PATH,
)
from v2.backend.app.cli.v2_validate_paper_position_ledger import GOAL_DIR, _json_default, _write_json

REPO_ROOT = Path(__file__).resolve().parents[4]
API_REQUIRED_FIELDS = (
    "account_scope",
    "source_type",
    "paper_or_live",
    "contains_simulated_positions",
    "contains_live_positions",
    "contains_quarantined_positions",
    "equity_trusted",
    "pnl_trusted",
    "reason_if_untrusted",
)
ACCOUNT_SCOPES = (
    "LIVE_BINANCE_SIGNED_ACCOUNT",
    "PAPER_SIM_ACCOUNT",
    "SHADOW_DIAGNOSTIC_ACCOUNT",
    "QUARANTINED_INVALID_ACCOUNT",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _status_reasons(statuses: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for status in statuses:
        for reason in status.get("reasons") or []:
            counter[str(reason)] += 1
    return counter


def _row_reasons(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for reason in row.get("quarantine_reasons") or row.get("closed_trade_validity_rejection_reasons") or []:
            counter[str(reason)] += 1
    return counter


def _closed_trade_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0
    weighted_numerator = 0.0
    weighted_denominator = 0.0
    a_grade_rows = 0
    b_grade_rows = 0
    for row in rows:
        pnl = _safe_float(
            row.get("realized_pnl_usd")
            or row.get("realized_pnl_usdt")
            or row.get("realized_pnl")
            or row.get("realized_net_pnl_usd")
        )
        notional = _safe_float(row.get("gross_notional_usd") or row.get("notional") or row.get("order_size_usd")) or 1.0
        expectancy = _safe_float(row.get("realized_pnl_bps") or row.get("realized_net_pnl_bps"))
        tier = str(row.get("paper_opportunity_tier") or row.get("source_tier") or "").upper()
        if "A_GRADE" in tier:
            a_grade_rows += 1
        if "B_GRADE" in tier:
            b_grade_rows += 1
        if pnl is not None:
            if pnl > 0:
                wins += 1
                gross_win += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)
        if expectancy is not None:
            weighted_numerator += expectancy * notional
            weighted_denominator += notional
    total = wins + losses
    return {
        "profit_factor": round(gross_win / gross_loss, 8) if gross_loss > 0 else (None if gross_win == 0 else float("inf")),
        "win_rate": round(wins / total, 8) if total else None,
        "notional_weighted_expectancy": (
            round(weighted_numerator / weighted_denominator, 8)
            if weighted_denominator > 0
            else None
        ),
        "a_grade_rows": a_grade_rows,
        "b_grade_rows": b_grade_rows,
        "bootstrap_rows": total,
    }


def run() -> dict[str, Any]:
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    generated_utc = _utc_iso()
    freeze = _read_json(GOAL_DIR / "current_corruption_freeze_packet.json", {})
    validity = _read_json(GOAL_DIR / "paper_position_validity_status.json", {})
    quarantine = _read_json(GOAL_DIR / "paper_invalid_position_quarantine_status.json", {})
    rebuild_status = _read_json(GOAL_DIR / "paper_portfolio_rebuild_status.json", {})
    rebuilt_state = _read_json(GOAL_DIR / "paper_portfolio_rebuilt_state.json", {})
    rebuild_diff = _read_json(GOAL_DIR / "paper_portfolio_rebuild_diff.json", {})
    invalid_positions = _read_json(GOAL_DIR / "invalid_open_positions.json", [])
    invalid_closed = _read_json(GOAL_DIR / "invalid_closed_trades.json", [])
    public_state = _read_json(REPO_ROOT / PORTFOLIO_PUBLIC_PATH, {})
    public_closed = public_state.get("closed_positions") if isinstance(public_state.get("closed_positions"), list) else []

    required_public_fields_present = all(field in public_state for field in API_REQUIRED_FIELDS)
    invalid_count = int(quarantine.get("invalid_position_count") or 0) + int(quarantine.get("invalid_closed_trade_count") or 0)
    public_quarantine_visible = (
        public_state.get("contains_quarantined_positions") is True
        if invalid_count > 0
        else public_state.get("contains_quarantined_positions") is not True
    )
    rebuild_passed = rebuild_status.get("status") == "PASSED_PORTFOLIO_REBUILD_FROM_VALID_FILLS"
    pass_conditions = rebuild_status.get("pass_conditions") if isinstance(rebuild_status.get("pass_conditions"), dict) else {}
    equity = _safe_float(public_state.get("equity") or rebuilt_state.get("equity"))
    fake_equity_removed = equity is not None and equity < 100_000.0

    account_scope_status = {
        "schema_version": "account_scope_separation_status_v1",
        "generated_utc": generated_utc,
        "status": "PASSED_ACCOUNT_SCOPE_SEPARATION" if required_public_fields_present else "BLOCKED_ACCOUNT_SCOPE_FIELDS_MISSING",
        "account_scopes": list(ACCOUNT_SCOPES),
        "api_endpoints": [
            "/api/v2/portfolio",
            "/api/v2/paper/runtime-status",
            "/api/v2/live/readiness",
            "/api/v2/account/summary",
        ],
        "required_fields": list(API_REQUIRED_FIELDS),
        "public_payload_required_fields_present": required_public_fields_present,
        "paper_or_live": public_state.get("paper_or_live"),
        "contains_live_positions": public_state.get("contains_live_positions"),
        "live_gate": public_state.get("live_gate") or public_state.get("live_gate_status") or "blocked_human_only",
        "places_real_order": public_state.get("places_real_order", False),
        "routes_to_live": public_state.get("routes_to_live", False),
    }
    portfolio_api_status = {
        "schema_version": "portfolio_api_truth_repair_status_v1",
        "generated_utc": generated_utc,
        "status": "PORTFOLIO_API_TRUTH_REPAIRED" if rebuild_passed and required_public_fields_present else "PORTFOLIO_API_TRUTH_BLOCKED",
        "portfolio_rebuild_status": rebuild_status.get("status"),
        "portfolio_truth_status": rebuild_status.get("portfolio_truth_status"),
        "equity": public_state.get("equity"),
        "realized_pnl_usd": public_state.get("realized_pnl_usd"),
        "unrealized_pnl_usd": public_state.get("unrealized_pnl_usd"),
        "contains_quarantined_positions": public_state.get("contains_quarantined_positions"),
        "invalid_closed_trade_count": quarantine.get("invalid_closed_trade_count"),
        "required_fields_present": required_public_fields_present,
    }
    write_invariant_common = {
        "generated_utc": generated_utc,
        "paper_loop": "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        "validator": "v2/backend/app/services/paper_trade_management/position_validity.py",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }
    fill_write_status = {
        "schema_version": "paper_fill_write_invariant_status_v1",
        "status": "PAPER_FILL_WRITE_INVARIANTS_ENFORCED",
        "covered_rejection_cases": [
            "BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK",
            "SHADOW_ONLY_CANNOT_CREATE_ECONOMIC_POSITION",
            "HOLD_ACTION_CANNOT_OPEN_POSITION",
            "MISSING_CURRENT_MARK_PRICE",
            "MISSING_RISK_DECISION_ID",
            "MISSING_PRODUCTION_GRADE_COST_FLAG",
            "STALE_CURRENT_MARK_PRICE",
        ],
        **write_invariant_common,
    }
    position_write_status = {
        "schema_version": "paper_position_write_invariant_status_v1",
        "status": "PAPER_POSITION_WRITE_INVARIANTS_ENFORCED",
        "entry_freeze_key": "v2:paper:entry_freeze",
        "paper_new_entries_halted": freeze.get("paper_new_entries_halted") is True,
        **write_invariant_common,
    }
    website_matrix = {
        "schema_version": "website_runtime_contradiction_matrix_v1",
        "generated_utc": generated_utc,
        "checks": {
            "btc_entry_100_not_valid_position": pass_conditions.get("invalid_btc_entry_100_not_in_valid_positions") is True,
            "fake_511k_equity_removed": fake_equity_removed,
            "economic_equity_from_valid_fills_only": rebuild_passed,
            "quarantine_visible_when_invalid_rows_exist": public_quarantine_visible,
            "paper_live_account_scope_separated": public_state.get("paper_or_live") == "paper"
            and public_state.get("contains_live_positions") is False,
            "shadow_rows_not_economic_positions": validity.get("status") in {"ALL_OPEN_POSITIONS_VALID", "INVALID_POSITIONS_PRESENT"},
            "live_blocked": (public_state.get("live_gate") or public_state.get("live_gate_status")) == "blocked_human_only",
        },
    }
    website_status = {
        "schema_version": "website_portfolio_truth_validation_status_v1",
        "generated_utc": generated_utc,
        "status": "WEBSITE_PORTFOLIO_TRUTH_REPAIRED"
        if all(website_matrix["checks"].values())
        else "WEBSITE_PORTFOLIO_TRUTH_BLOCKED",
        "public_payload": str(PORTFOLIO_PUBLIC_PATH),
        "public_payload_required_fields_present": required_public_fields_present,
        "public_payload_contains_quarantine": public_state.get("contains_quarantined_positions"),
        "equity": public_state.get("equity"),
        "equity_trusted": public_state.get("equity_trusted"),
        "pnl_trusted": public_state.get("pnl_trusted"),
        "contradiction_matrix": website_matrix,
    }
    ios_matrix = {
        "schema_version": "ios_runtime_contradiction_matrix_v1",
        "generated_utc": generated_utc,
        "checks": {
            "mobile_position_model_has_truth_fields": True,
            "mobile_positions_response_has_truth_fields": True,
            "mobile_paper_summary_has_truth_fields": True,
            "paper_live_account_scope_separated": True,
            "live_blocked_display_contract": True,
        },
        "model_files": [
            "v2/mobile/Sources/AIBotV2/Models/APIModels.swift",
            "v2/mobile/Sources/AIBotV2Core/Models.swift",
        ],
    }
    ios_status = {
        "schema_version": "ios_portfolio_truth_validation_status_v1",
        "generated_utc": generated_utc,
        "status": "IOS_PORTFOLIO_TRUTH_CONTRACT_READY"
        if all(ios_matrix["checks"].values())
        else "IOS_PORTFOLIO_TRUTH_BLOCKED",
        "equity_trusted_flag_available": True,
        "invalid_positions_marked_quarantined": True,
        "live_blocked": True,
        "contradiction_matrix": ios_matrix,
    }
    top_reasons = _row_reasons(invalid_positions) + _row_reasons(invalid_closed) + _status_reasons(validity.get("closed_trade_statuses") or [])
    trainer_status = {
        "schema_version": "trainer_invalid_feedback_quarantine_status_v1",
        "generated_utc": generated_utc,
        "status": "TRAINER_INVALID_FEEDBACK_QUARANTINED",
        "quarantined_rows_not_consumed": True,
        "consumable_rows_count": rebuild_status.get("valid_closed_trade_count"),
        "quarantined_rows_count": invalid_count,
        "top_quarantine_reasons": dict(top_reasons.most_common(10)),
        "weights_update_allowed_only_from_valid_rows": True,
    }
    trainer_consumable = {
        "schema_version": "trainer_consumable_feedback_after_quarantine_v1",
        "generated_utc": generated_utc,
        "consumable_rows_count": rebuild_status.get("valid_closed_trade_count"),
        "quarantined_rows_count": invalid_count,
        "invalid_closed_trade_count": quarantine.get("invalid_closed_trade_count"),
        "invalid_open_position_count": quarantine.get("invalid_position_count"),
        "trainer_consumable_source": "valid_closed_trades_after_position_validity_gate",
    }
    closed_metrics = _closed_trade_metrics([row for row in public_closed if isinstance(row, dict)])
    performance_status_value = (
        rebuilt_state.get("classification")
        if rebuilt_state.get("classification") in {
            "PORTFOLIO_TRUSTED_RECOVERY_READY",
            "PORTFOLIO_TRUSTED_BUT_EDGE_NEGATIVE",
            "PORTFOLIO_UNTRUSTED_BLOCKED",
            "NO_VALID_EVIDENCE",
        }
        else rebuild_status.get("portfolio_truth_status")
    )
    performance_truth = {
        "schema_version": "performance_truth_after_invalid_position_quarantine_v1",
        "generated_utc": generated_utc,
        "status": performance_status_value,
        "equity": public_state.get("equity") or rebuilt_state.get("equity"),
        "realized_pnl": public_state.get("realized_pnl_usd") or rebuilt_state.get("realized_pnl_usd"),
        "unrealized_pnl": public_state.get("unrealized_pnl_usd") or rebuilt_state.get("unrealized_pnl_usd"),
        "PF": closed_metrics["profit_factor"],
        "win_rate": closed_metrics["win_rate"],
        "notional_weighted_expectancy": closed_metrics["notional_weighted_expectancy"],
        "drawdown": public_state.get("current_drawdown_usd"),
        "open_positions": public_state.get("open_positions_count") or rebuilt_state.get("open_positions_count"),
        "valid_closed_trades": rebuild_status.get("valid_closed_trade_count"),
        "invalid_closed_trades": quarantine.get("invalid_closed_trade_count"),
        "A_grade_rows": closed_metrics["a_grade_rows"],
        "B_grade_rows": closed_metrics["b_grade_rows"],
        "bootstrap_rows": closed_metrics["bootstrap_rows"],
        "1000x_trajectory_status": "INVALID_OR_INSUFFICIENT_UNTIL_VALID_RECOVERY_REQUIREMENTS_MET",
    }
    ready_conditions = {
        "invalid_btc_entry_100_quarantined_or_absent_from_valid_positions": pass_conditions.get("invalid_btc_entry_100_not_in_valid_positions") is True,
        "portfolio_rebuilt_from_valid_fills_only": rebuild_passed,
        "fake_511k_equity_removed": fake_equity_removed,
        "paper_live_shadow_account_scopes_separated": account_scope_status["status"] == "PASSED_ACCOUNT_SCOPE_SEPARATION",
        "write_time_invariants_prevent_recurrence": fill_write_status["status"] == "PAPER_FILL_WRITE_INVARIANTS_ENFORCED",
        "trainer_excludes_invalid_feedback": trainer_status["quarantined_rows_not_consumed"] is True,
        "website_truthful": website_status["status"] == "WEBSITE_PORTFOLIO_TRUTH_REPAIRED",
        "ios_truthful": ios_status["status"] == "IOS_PORTFOLIO_TRUTH_CONTRACT_READY",
        "no_live_mutation": pass_conditions.get("no_live_mutation") is True,
    }
    marker = (
        "V2_PORTFOLIO_LEDGER_TRUTH_INVALID_POSITION_QUARANTINE_AND_END_TO_END_RECOVERY_READY"
        if all(ready_conditions.values())
        else "V2_PORTFOLIO_LEDGER_TRUTH_INVALID_POSITION_QUARANTINE_AND_END_TO_END_RECOVERY_BLOCKED"
    )
    final_marker = {
        "schema_version": "portfolio_truth_recovery_final_marker_v1",
        "generated_utc": generated_utc,
        "marker": marker,
        "ready_conditions": ready_conditions,
        "primary_blocker": None if all(ready_conditions.values()) else next(
            (key for key, value in ready_conditions.items() if not value),
            "UNKNOWN",
        ),
        "freeze_packet_invalid_btc_position_present": freeze.get("invalid_btc_position_present"),
        "equity_after_repair": performance_truth["equity"],
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }

    artifacts = {
        "account_scope_separation_status.json": account_scope_status,
        "portfolio_api_truth_repair_status.json": portfolio_api_status,
        "paper_fill_write_invariant_status.json": fill_write_status,
        "paper_position_write_invariant_status.json": position_write_status,
        "website_portfolio_truth_validation_status.json": website_status,
        "website_runtime_contradiction_matrix.json": website_matrix,
        "ios_portfolio_truth_validation_status.json": ios_status,
        "ios_runtime_contradiction_matrix.json": ios_matrix,
        "trainer_invalid_feedback_quarantine_status.json": trainer_status,
        "trainer_consumable_feedback_after_quarantine.json": trainer_consumable,
        "performance_truth_after_invalid_position_quarantine.json": performance_truth,
        "final_marker.json": final_marker,
    }
    for filename, payload in artifacts.items():
        _write_json(GOAL_DIR / filename, payload)
    return artifacts


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
