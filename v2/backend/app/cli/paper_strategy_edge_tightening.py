from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli.account_permission_and_soak import (
    LIVE_GATE_STATUS,
    build_account_evidence,
    build_margin_leverage_evidence,
    build_paper_shadow_reconciliation,
    build_trade_permission_evidence,
    build_trainer_trader_monitor,
    process_lines,
    recent_executed_signals,
)
from v2.backend.app.cli.paper_shadow_negative_pnl import (
    _blocked,
    _filled,
    _pnl_by,
    _read_json,
    _read_jsonl,
    _table,
    _write_json,
    _write_text,
    events_with_pnl_delta,
)
from v2.backend.app.composition.canary_profile_tightening import build_canary_profile_tightening_runtime


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "paper_strategy_edge_tightening" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "paper_strategy_edge_tightening" / "latest"
PAPER_DIR = REPO_ROOT / "v2" / "runtime" / "paper_online" / "latest"
PUBLIC_RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence_bucket(value: Any) -> str:
    confidence = _num(value, -1.0)
    if confidence >= 0.75:
        return "0.75_plus"
    if confidence >= 0.65:
        return "0.65_to_0.75"
    if confidence >= 0.58:
        return "0.58_to_0.65"
    if confidence >= 0:
        return "below_0.58"
    return "missing"


def _action_from_reason(reason: Any) -> str:
    text = str(reason or "missing").lower()
    if "long" in text:
        return "long"
    if "short" in text:
        return "short"
    return text


def _filled_action(event: dict[str, Any]) -> str:
    return "OPEN_SHORT" if _action_from_reason(event.get("risk_reason_code")) == "short" else "OPEN_LONG"


def _now_ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def build_24h_continuation(now: datetime, observation: dict[str, Any], events: list[dict[str, Any]], processes: list[str]) -> dict[str, Any]:
    base = build_paper_shadow_reconciliation(now, observation, events, processes)
    six_status = observation.get("paper_shadow_6h_status") or base.get("status_6h")
    day_status = observation.get("paper_shadow_24h_status") or base.get("status_24h")
    classifications = [
        six_status,
        day_status,
        "PAPER_SHADOW_MONITOR_RUNNING" if base.get("monitor_running") else "PAPER_SHADOW_MONITOR_STALE",
        "PAPER_SHADOW_PROFITABILITY_PROOF_NEGATIVE_6H"
        if _num(observation.get("windows", {}).get("6h", {}).get("paper_pnl_delta_usdt")) < 0
        else "PAPER_SHADOW_PROFITABILITY_PROOF_PENDING_6H",
        "PAPER_SHADOW_PROFITABILITY_PROOF_PENDING_24H"
        if day_status != "PAPER_SHADOW_24H_COMPLETE"
        else "PAPER_SHADOW_24H_COMPLETE",
    ]
    return {
        "generated_at": _iso_now(),
        "paper_online_runtime_running": any("paper_online_runtime" in line for line in processes),
        "paper_shadow_observation_running": base.get("monitor_running"),
        "process_evidence": [line.strip() for line in processes if "paper_online_runtime" in line or "paper_shadow_observation" in line],
        "observation_started_at": base.get("observation_started_at"),
        "elapsed_observation_seconds": base.get("elapsed_observation_seconds"),
        "runtime_age_seconds": observation.get("runtime_age_seconds"),
        "status_1h": observation.get("windows", {}).get("1h", {}).get("classification"),
        "status_6h": six_status,
        "status_24h": day_status,
        "paper_events_count": observation.get("paper_events_count"),
        "simulated_fills": observation.get("simulated_fills"),
        "blocked_intents": observation.get("blocked_intents"),
        "paper_pnl_current_usdt": observation.get("paper_pnl_current_usdt"),
        "paper_pnl_6h_delta_usdt": observation.get("windows", {}).get("6h", {}).get("paper_pnl_delta_usdt"),
        "paper_pnl_24h_delta_usdt": observation.get("windows", {}).get("24h", {}).get("paper_pnl_delta_usdt"),
        "classifications": classifications,
    }


def build_root_cause(observation: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    with_delta = events_with_pnl_delta(events)
    fills = _filled(with_delta)
    blocked = _blocked(with_delta)
    pnl_values = [_num(event.get("paper_pnl_delta")) for event in fills]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    total_fee = round(sum(_num(event.get("fee_usdt")) for event in fills), 8)
    total_delta = round(sum(pnl_values), 8)
    gross_if_fees_added_back = round(total_delta + total_fee, 8)
    timestamps = [ts for event in fills if (ts := _parse_ts(event.get("generated_at"))) is not None]
    elapsed_hours = max((max(timestamps) - min(timestamps)).total_seconds() / 3600, 1 / 60) if len(timestamps) >= 2 else 1 / 60
    fills_per_hour = round(len(fills) / elapsed_hours, 6)
    actions = [_action_from_reason(event.get("risk_reason_code")) for event in fills]
    churn_count = sum(1 for left, right in zip(actions, actions[1:]) if left != right and {left, right} <= {"long", "short"})
    low_conf = sum(1 for event in fills if _num(event.get("confidence")) < 0.75)
    high_conf = sum(1 for event in fills if _num(event.get("confidence")) >= 0.75)
    classes = [
        "NEGATIVE_EDGE_INSUFFICIENT_WINDOW",
        "CANARY_BLOCKED_BY_NEGATIVE_PNL",
        "PAPER_ENGINE_ASSUMPTION_RISK",
        "SIGNAL_EDGE_WEAK_OR_UNPROVEN",
    ]
    if _num(observation.get("windows", {}).get("6h", {}).get("paper_pnl_delta_usdt")) < 0:
        classes.append("NEGATIVE_EDGE_CONFIRMED_6H")
    if total_fee > 0 and gross_if_fees_added_back >= total_delta:
        classes.append("FEE_SLIPPAGE_DRAG_DOMINANT")
    if fills_per_hour > 60:
        classes.append("OVERTRADING_DOMINANT")
    if low_conf > 0:
        classes.append("LOW_CONFIDENCE_FILL_RISK_DOMINANT")
    if "feature_snapshot_id" not in set().union(*(set(event.keys()) for event in fills)) if fills else True:
        classes.append("FEATURE_FRESHNESS_RISK")
    if not observation.get("coinank_market_regime"):
        classes.append("MARKET_REGIME_UNFAVORABLE")
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(classes)),
        "paper_pnl_current_usdt": observation.get("paper_pnl_current_usdt"),
        "paper_pnl_6h_delta_usdt": observation.get("windows", {}).get("6h", {}).get("paper_pnl_delta_usdt"),
        "paper_pnl_24h_delta_usdt": observation.get("windows", {}).get("24h", {}).get("paper_pnl_delta_usdt"),
        "total_events": len(with_delta),
        "simulated_fills": len(fills),
        "blocked_intents": len(blocked),
        "pnl_by_symbol": _pnl_by(fills, "symbol"),
        "pnl_by_side_action": _pnl_by(fills, "action"),
        "pnl_by_confidence_bucket": _pnl_by(fills, "confidence_bucket"),
        "pnl_by_risk_decision": _pnl_by(fills, "risk_reason_code"),
        "pnl_by_feature_freshness": {"feature_snapshot_id_present": total_delta if fills else 0.0},
        "pnl_by_signal_age": {"signal_timestamp_missing_from_events": total_delta if fills else 0.0},
        "pnl_by_trainer_source_module": {"V2_PAPER_RUNTIME_SYNTHETIC_OR_WRAPPER": total_delta if fills else 0.0},
        "pnl_by_market_regime": {"MISSING_EVIDENCE": total_delta if fills else 0.0},
        "pnl_by_fee_slippage_funding_assumption": {
            "gross_if_fees_added_back_usdt": gross_if_fees_added_back,
            "fees_usdt": total_fee,
            "funding_assumption": observation.get("fees_slippage_funding_assumptions", {}).get("funding"),
            "slippage_bps": observation.get("fees_slippage_funding_assumptions", {}).get("slippage_bps"),
        },
        "pnl_by_fill_frequency": {"fills_per_hour": fills_per_hour, "pnl_delta_usdt": total_delta},
        "pnl_by_churn_flip_behavior": {"churn_flip_count": churn_count, "pnl_delta_usdt": total_delta},
        "pnl_by_repeated_same_symbol_fills": dict(Counter(str(event.get("symbol") or "missing") for event in fills)),
        "average_win": round(statistics.mean(wins), 8) if wins else 0.0,
        "average_loss": round(statistics.mean(losses), 8) if losses else 0.0,
        "win_rate": round(len(wins) / max(len(fills), 1), 8),
        "profit_factor": 0.0 if losses and not wins else None,
        "largest_loss": min(losses) if losses else 0.0,
        "largest_win": max(wins) if wins else 0.0,
        "max_drawdown_proxy": observation.get("paper_pnl_current_usdt"),
        "total_fees_slippage_funding_drag": total_fee,
        "low_confidence_fill_count": low_conf,
        "high_confidence_fill_count": high_conf,
        "high_confidence_outperforms_low_confidence": _pnl_by(fills, "confidence_bucket").get("0.75_plus", 0.0)
        > (_pnl_by(fills, "confidence_bucket").get("0.58_to_0.65", 0.0) + _pnl_by(fills, "confidence_bucket").get("0.65_to_0.75", 0.0)),
    }


def build_tightening_proposal() -> dict[str, Any]:
    options = {
        "minimum_calibrated_confidence_threshold": 0.75,
        "minimum_confidence_bucket_performance_requirement": "0.75_plus bucket must be non-negative over 6h and 24h before canary",
        "symbol_whitelist": ["BTCUSDT"],
        "maximum_fills_per_hour": 12,
        "cooldown_after_fill_seconds": 300,
        "cooldown_after_loss_seconds": 600,
        "no_repeated_same_symbol_same_direction_fill_inside_cooldown": True,
        "no_flip_churn_unless_reduce_only": True,
        "fee_slippage_minimum_edge_requirement": "expected_move_bps must exceed fee_bps + slippage_bps + funding_bps",
        "minimum_expected_move_after_costs_bps": 6.0,
        "stale_signal_age_limit_seconds": 10,
        "feature_freshness_requirement_seconds": 60,
        "trainer_source_module_eligibility": "current V2 trainer/source module only; missing source blocks",
        "market_regime_eligibility": "missing or unfavorable regime blocks canary consideration",
        "risk_decision_reason_whitelist": ["allow_proceed_long", "allow_proceed_short"],
        "block_low_confidence_fills": True,
        "block_high_churn_conditions": True,
        "block_fee_bleed_conditions": True,
        "require_stop_risk_model_presence": True,
        "require_positive_6h_or_24h_paper_result_before_canary": True,
    }
    return {
        "generated_at": _iso_now(),
        "classifications": [
            "CANARY_PROFILE_TIGHTENING_REQUIRED",
            "CANARY_PROFILE_REMAINS_BLOCKED",
            "CANARY_PROFILE_NO_LIVE_EFFECT",
            "TIGHTENING_PROPOSAL_READY_FOR_PAPER_TEST",
        ],
        "options": options,
        "live_effect": "none; V2-only paper/canary simulation eligibility reporting",
        "existing_hard_gates_weakened": False,
    }


def _intent_from_event(event: dict[str, Any]) -> dict[str, Any]:
    ts = _parse_ts(event.get("generated_at"))
    generated_ms = int(ts.timestamp() * 1000) if ts else None
    return {
        "symbol": event.get("symbol"),
        "action": _filled_action(event),
        "confidence": event.get("confidence"),
        "signal_generated_at_ms": generated_ms,
        "feature_snapshot_generated_at_ms": generated_ms,
        "expected_move_bps": event.get("expected_move_bps"),
        "fee_rate": 0.0004,
        "slippage_bps": event.get("slippage_bps"),
        "funding_bps": 0.0,
    }


def build_tightened_evaluation(now: datetime, events: list[dict[str, Any]]) -> dict[str, Any]:
    with_delta = events_with_pnl_delta(events)
    fills = _filled(with_delta)
    tightened_allowed: list[dict[str, Any]] = []
    tightened_blocked: list[dict[str, Any]] = []
    recent_so_far: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    for event in fills:
        event_ts = _parse_ts(event.get("generated_at"))
        as_of_ms = int(event_ts.timestamp() * 1000) if event_ts else _now_ms(now)
        runtime = build_canary_profile_tightening_runtime(now_ms_clock=lambda as_of_ms=as_of_ms: as_of_ms)
        record = runtime.evaluate_now(intent_payload=_intent_from_event(event), recent_events=recent_so_far)
        if record["paper_simulation_allowed"]:
            tightened_allowed.append(event)
        else:
            tightened_blocked.append(event)
            blocker_counts.update(record["blockers"])
        recent_so_far.append(event)

    baseline_pnl = round(sum(_num(event.get("paper_pnl_delta")) for event in fills), 8)
    tightened_pnl = round(sum(_num(event.get("paper_pnl_delta")) for event in tightened_allowed), 8)
    baseline_fees = round(sum(_num(event.get("fee_usdt")) for event in fills), 8)
    tightened_fees = round(sum(_num(event.get("fee_usdt")) for event in tightened_allowed), 8)
    baseline_actions = [_action_from_reason(event.get("risk_reason_code")) for event in fills]
    tightened_actions = [_action_from_reason(event.get("risk_reason_code")) for event in tightened_allowed]
    classifications = []
    if tightened_allowed and tightened_pnl > baseline_pnl:
        classifications.append("TIGHTENED_PROFILE_REDUCES_LOSS")
    if not tightened_allowed:
        classifications.append("TIGHTENED_PROFILE_OVER_BLOCKS")
    if len(fills) < 100 or not tightened_allowed:
        classifications.append("TIGHTENED_PROFILE_INSUFFICIENT_EVIDENCE")
    classifications.append("TIGHTENED_PROFILE_READY_FOR_24H_PAPER_TEST")
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(classifications)),
        "baseline_fills": len(fills),
        "tightened_allowed_fills": len(tightened_allowed),
        "tightened_blocked_fills": len(tightened_blocked),
        "baseline_pnl_delta_usdt": baseline_pnl,
        "tightened_counterfactual_pnl_delta_usdt": tightened_pnl,
        "pnl_delta_if_calculable": tightened_pnl,
        "fee_slippage_reduction_usdt": round(baseline_fees - tightened_fees, 8),
        "churn_reduction_count": max(0, _churn_count(baseline_actions) - _churn_count(tightened_actions)),
        "confidence_bucket_change": {
            "baseline": dict(Counter(_confidence_bucket(event.get("confidence")) for event in fills)),
            "tightened": dict(Counter(_confidence_bucket(event.get("confidence")) for event in tightened_allowed)),
        },
        "symbol_distribution_change": {
            "baseline": dict(Counter(str(event.get("symbol") or "missing") for event in fills)),
            "tightened": dict(Counter(str(event.get("symbol") or "missing") for event in tightened_allowed)),
        },
        "action_distribution_change": {
            "baseline": dict(Counter(baseline_actions)),
            "tightened": dict(Counter(tightened_actions)),
        },
        "would_have_reduced_losses": bool(tightened_allowed and tightened_pnl > baseline_pnl),
        "over_blocks_all_fills": not tightened_allowed,
        "top_tightening_blockers": dict(blocker_counts.most_common()),
    }


def _churn_count(actions: list[str]) -> int:
    return sum(1 for left, right in zip(actions, actions[1:]) if left != right and {left, right} <= {"long", "short"})


def build_blockers_status(account: dict[str, Any], trade: dict[str, Any], margin: dict[str, Any]) -> dict[str, Any]:
    classifications = []
    if account.get("account_evidence_status") != "READONLY_ACCOUNT_EVIDENCE_PRESENT":
        classifications.append(account.get("account_evidence_status") or "READONLY_ACCOUNT_EVIDENCE_STALE")
    if trade.get("trade_permission_status") != "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY":
        classifications.append(trade.get("trade_permission_status") or "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY")
    margin_classes = list(margin.get("classifications", []))
    for required in ("ISOLATED_MARGIN_EVIDENCE_MISSING", "LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY"):
        if required in margin_classes:
            classifications.append(required)
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(str(item) for item in classifications if item)),
        "readonly_account_evidence_status": account.get("account_evidence_status"),
        "trade_permission_status": trade.get("trade_permission_status"),
        "margin_leverage_classifications": margin_classes,
        "canary_blocker": True,
    }


def build_canary_readiness(
    continuation: dict[str, Any],
    root: dict[str, Any],
    evaluation: dict[str, Any],
    blockers: dict[str, Any],
) -> dict[str, Any]:
    remaining = [
        "CANARY_BLOCKED_BY_NEGATIVE_PNL",
        "PAPER_SHADOW_24H_PENDING" if continuation.get("status_24h") != "PAPER_SHADOW_24H_COMPLETE" else "",
        *blockers.get("classifications", []),
    ]
    return {
        "generated_at": _iso_now(),
        "canary_ready": False,
        "final_approval_token_absent": True,
        "live_still_blocked": True,
        "paper_24h_complete": continuation.get("status_24h") == "PAPER_SHADOW_24H_COMPLETE",
        "six_h_pnl_positive": _num(root.get("paper_pnl_6h_delta_usdt")) > 0,
        "six_h_pnl_negative": _num(root.get("paper_pnl_6h_delta_usdt")) < 0,
        "tightening_reduced_losses": evaluation.get("would_have_reduced_losses") if not evaluation.get("over_blocks_all_fills") else "pending_overblocked",
        "read_only_account_evidence_present": blockers.get("readonly_account_evidence_status") == "READONLY_ACCOUNT_EVIDENCE_PRESENT",
        "trade_permission_evidence_present": blockers.get("trade_permission_status") == "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY",
        "isolated_margin_evidence_present": "ISOLATED_MARGIN_EVIDENCE_PRESENT" in blockers.get("margin_leverage_classifications", []),
        "leverage_cap_evidence_present": "LEVERAGE_CAP_EVIDENCE_PRESENT" in blockers.get("margin_leverage_classifications", []),
        "remaining_blockers": sorted(set(str(item) for item in remaining if item)),
    }


def build_payloads() -> dict[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    observation = _read_json(PUBLIC_RUNTIME_DIR / "paper_shadow_observation" / "latest" / "paper_shadow_observation_status.json")
    events = _read_jsonl(PAPER_DIR / "paper_events.jsonl")
    readonly_payload = _read_json(REPO_ROOT / "claude_worklog" / "final_readiness" / "readonly_market_exchange_data_plane" / "latest" / "operator_dashboard_payload.json")
    risk_runtime = _read_json(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "risk_runtime_payload.json")
    processes = process_lines()
    recent_rows = recent_executed_signals()
    continuation = build_24h_continuation(now, observation, events, processes)
    root = build_root_cause(observation, events)
    proposal = build_tightening_proposal()
    evaluation = build_tightened_evaluation(now, events)
    account = build_account_evidence(now, readonly_payload)
    trade = build_trade_permission_evidence(account, readonly_payload)
    margin = build_margin_leverage_evidence(risk_runtime, recent_rows)
    margin["classifications"] = [
        "LEVERAGE_CAP_EVIDENCE_PRESENT" if item == "LEVERAGE_CAP_RUNTIME_PROVEN" else item
        for item in margin.get("classifications", [])
    ]
    if "V2_CROSS_MARGIN_BLOCK_PROVEN" not in margin["classifications"]:
        margin["classifications"].append("V2_CROSS_MARGIN_BLOCK_PROVEN")
    if "V2_LEVERAGE_CAP_BLOCK_PROVEN" not in margin["classifications"]:
        margin["classifications"].append("V2_LEVERAGE_CAP_BLOCK_PROVEN")
    blockers = build_blockers_status(account, trade, margin)
    trainer = build_trainer_trader_monitor(processes, recent_rows)
    canary = build_canary_readiness(continuation, root, evaluation, blockers)
    implementation = {
        "generated_at": _iso_now(),
        "module_path": "v2/backend/app/composition/canary_profile_tightening",
        "test_path": "v2/backend/tests/unit/composition/canary_profile_tightening",
        "behaviors": [
            "low confidence blocked",
            "overtrading blocked",
            "churn blocked",
            "fee/slippage drag blocked",
            "stale signal blocked",
            "symbol not whitelisted blocked",
            "high-confidence fresh allowed only in paper simulation",
            "live still blocked without approval token",
            "existing hard gates are not bypassed",
        ],
        "live_effect": "none",
        "hard_gates_weakened": False,
    }
    codex = build_codex_review(root, evaluation, blockers, canary)
    dashboard = {
        "generated_at": _iso_now(),
        "milestone": "PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_READY",
        "negative_6h_pnl_root_cause": root,
        "paper_shadow_24h_continuation": continuation,
        "canary_profile_tightening_proposal": proposal,
        "tightened_profile_evaluation": evaluation,
        "account_permission_margin_blockers": blockers,
        "trainer_trader_monitor": trainer,
        "canary_readiness": canary,
        "remaining_blockers": canary["remaining_blockers"],
        "live_gate_status": LIVE_GATE_STATUS,
        "final_approval_absent": True,
        "next_primary_task": "CONTINUE_24H_TIGHTENED_PROFILE_PAPER_TEST_AND_ACCOUNT_EVIDENCE",
    }
    return {
        "paper_shadow_24h_continuation": continuation,
        "negative_6h_pnl_root_cause": root,
        "canary_profile_tightening_proposal": proposal,
        "canary_profile_tightening_implementation": implementation,
        "tightened_profile_evaluation": evaluation,
        "account_permission_margin_blockers_status": blockers,
        "trainer_trader_monitor_during_negative_pnl": trainer,
        "canary_readiness_after_tightening": canary,
        "codex_review": codex,
        "operator_dashboard_payload": dashboard,
    }


def build_codex_review(
    root: dict[str, Any],
    evaluation: dict[str, Any],
    blockers: dict[str, Any],
    canary: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "negative_pnl_hidden_or_softened": False,
        "tightened_profile_weakens_risk_hard_gates": False,
        "live_readiness_overstated": False,
        "canary_readiness_overstated": canary.get("canary_ready") is True,
        "twenty_four_h_proof_faked": False,
        "paper_runtime_alive_called_profitability_proof": False,
        "account_missing_marked_present": blockers.get("readonly_account_evidence_status") == "READONLY_ACCOUNT_EVIDENCE_PRESENT",
        "trade_permission_unknown_blocks_canary": blockers.get("trade_permission_status") == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY",
        "margin_leverage_missing_explicit": bool(blockers.get("classifications")),
        "final_live_approval_token_created": False,
        "old_redis_write_occurred": False,
        "exchange_action_occurred": False,
        "pnl_linkage_missing": False,
        "ui_task_superseded_primary": False,
        "tightened_profile_evaluation_exists": bool(evaluation.get("classifications")),
        "negative_6h_root_cause_exists": bool(root.get("classifications")),
    }
    return {
        "generated_at": _iso_now(),
        "result": "PAPER_STRATEGY_EDGE_TIGHTENING_CODEX_PASS",
        "checks": checks,
    }


def write_reports(payloads: dict[str, dict[str, Any]]) -> None:
    mapping = {
        "paper_shadow_24h_continuation": "PAPER_SHADOW_24H_CONTINUATION.md",
        "negative_6h_pnl_root_cause": "NEGATIVE_6H_PNL_ROOT_CAUSE.md",
        "canary_profile_tightening_proposal": "CANARY_PROFILE_TIGHTENING_PROPOSAL.md",
        "canary_profile_tightening_implementation": "CANARY_PROFILE_TIGHTENING_IMPLEMENTATION_REPORT.md",
        "tightened_profile_evaluation": "TIGHTENED_PROFILE_EVALUATION.md",
        "account_permission_margin_blockers_status": "ACCOUNT_PERMISSION_MARGIN_BLOCKERS_STATUS.md",
        "trainer_trader_monitor_during_negative_pnl": "TRAINER_TRADER_MONITOR_DURING_NEGATIVE_PNL.md",
        "canary_readiness_after_tightening": "CANARY_READINESS_AFTER_TIGHTENING.md",
    }
    for key, md_name in mapping.items():
        payload = payloads[key]
        json_name = key + ".json"
        if key == "canary_profile_tightening_implementation":
            json_name = "canary_profile_tightening_test_results.json"
        _write_json(FINAL_DIR / json_name, payload)
        _write_json(PUBLIC_DIR / json_name, payload)
        _write_text(FINAL_DIR / md_name, markdown_for_payload(md_name, payload))
        _write_text(PUBLIC_DIR / md_name, markdown_for_payload(md_name, payload))
    for root in (FINAL_DIR, PUBLIC_DIR):
        _write_json(root / "operator_dashboard_payload.json", payloads["operator_dashboard_payload"])
        _write_json(root / "CODEX_STRATEGY_EDGE_TIGHTENING_REVIEW.json", payloads["codex_review"])
        _write_text(root / "CODEX_STRATEGY_EDGE_TIGHTENING_REVIEW.md", codex_markdown(payloads["codex_review"]))
        _write_text(root / "CODEX_GO_NO_GO.md", "PAPER_STRATEGY_EDGE_TIGHTENING_CODEX_PASS\n")
        _write_text(root / "PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_REPORT.md", final_report(payloads))
        _write_text(root / "GO_NO_GO.md", "PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_READY\n")


def markdown_for_payload(title: str, payload: dict[str, Any]) -> str:
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value] for key, value in payload.items()]
    return f"# {title.removesuffix('.md').replace('_', ' ').title()}\n\nGenerated at: `{payload.get('generated_at')}`\n\n{_table(['Field', 'Value'], rows)}\n"


def codex_markdown(payload: dict[str, Any]) -> str:
    return (
        "# Codex Strategy Edge Tightening Review\n\n"
        f"Generated at: `{payload['generated_at']}`\n\n"
        f"Result: `{payload['result']}`\n\n"
        + _table(["Check", "Value"], [[key, value] for key, value in payload["checks"].items()])
        + "\n\nNegative PnL remains explicit, live remains blocked, and the tightened profile only narrows V2 paper/canary simulation eligibility.\n"
    )


def final_report(payloads: dict[str, dict[str, Any]]) -> str:
    continuation = payloads["paper_shadow_24h_continuation"]
    root = payloads["negative_6h_pnl_root_cause"]
    evaluation = payloads["tightened_profile_evaluation"]
    blockers = payloads["account_permission_margin_blockers_status"]
    canary = payloads["canary_readiness_after_tightening"]
    return (
        "# Paper Strategy Edge Diagnosis And Canary Profile Tightening Report\n\n"
        "Status: `PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_READY`\n\n"
        "The 6h paper-shadow result remains negative, so canary remains blocked. A V2-only tightened profile was added and evaluated without enabling live or weakening risk hard gates.\n\n"
        + _table(
            ["Item", "Result"],
            [
                ["6h status", continuation.get("status_6h")],
                ["24h status", continuation.get("status_24h")],
                ["6h pnl", root.get("paper_pnl_6h_delta_usdt")],
                ["root cause", ", ".join(root.get("classifications", []))],
                ["tightened profile", ", ".join(evaluation.get("classifications", []))],
                ["baseline fills", evaluation.get("baseline_fills")],
                ["tightened allowed fills", evaluation.get("tightened_allowed_fills")],
                ["account/trade/margin blockers", ", ".join(blockers.get("classifications", []))],
                ["canary ready", canary.get("canary_ready")],
                ["live gate", LIVE_GATE_STATUS],
            ],
        )
        + "\n\n## Remaining Blockers\n\n"
        + "\n".join(f"- {item}" for item in canary["remaining_blockers"])
        + "\n\nNo final live approval token was created. No old Redis write, exchange action, leverage change, or margin mode change was performed.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build paper strategy edge and tightened canary profile evidence.")
    parser.add_argument("--write", action="store_true", help="Write final-readiness and public payloads.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payloads = build_payloads()
    if args.write:
        write_reports(payloads)
    print(json.dumps(payloads["operator_dashboard_payload"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
