"""Runtime alpha-remediated adaptive lifecycle 24h paper soak monitor.

This CLI is paper-only and observer-only. It reuses the existing adaptive
allocation/lifecycle soak collector, adds the runtime-alpha remediation fields,
and writes a fresh evidence namespace for the remediated 24h soak.

It never places orders, never calls test-order, never changes leverage/margin,
and never writes Redis.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_adaptive_allocation_trade_lifecycle_24h_paper_soak as base_soak
from v2.backend.app.services.profit_target_monitor.contracts import REQUIRED_TRAINER_FEEDBACK_FIELDS


REPO_ROOT = Path(__file__).resolve().parents[4]
SLUG = "v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak"
RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / SLUG / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / SLUG / "latest"
OBSERVATION_JSONL = "runtime_alpha_remediated_soak_observations.jsonl"
DEFAULT_REMEDIATION_ID = "runtime_alpha_decision_chain_remediation_20260614_050813"
DEFAULT_REQUIRED_SECONDS = 3600
DEFAULT_SOAK_WINDOW_HOURS = DEFAULT_REQUIRED_SECONDS / 3600.0

READY_GATE = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_1H_PAPER_SOAK_READY"
BLOCKED_GATE = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_1H_PAPER_SOAK_BLOCKED"
COMPLETE_READY_GATE = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_1H_PAPER_SOAK_COMPLETE_READY"
COMPLETE_BLOCKED_GATE = "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_1H_PAPER_SOAK_COMPLETE_BLOCKED"

OLD_SLUG = "v2_adaptive_allocation_and_trade_lifecycle_24h_paper_soak"


def _window_label(required_seconds: int) -> str:
    return base_soak.soak_window_label(required_seconds)


def _gate_suffix(required_seconds: int) -> str:
    return _window_label(required_seconds).upper()


def _ready_gate(required_seconds: int) -> str:
    return f"V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_{_gate_suffix(required_seconds)}_PAPER_SOAK_READY"


def _blocked_gate(required_seconds: int) -> str:
    return f"V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_{_gate_suffix(required_seconds)}_PAPER_SOAK_BLOCKED"


def _complete_ready_gate(required_seconds: int) -> str:
    return (
        f"V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_{_gate_suffix(required_seconds)}_"
        "PAPER_SOAK_COMPLETE_READY"
    )


def _complete_blocked_gate(required_seconds: int) -> str:
    return (
        f"V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_{_gate_suffix(required_seconds)}_"
        "PAPER_SOAK_COMPLETE_BLOCKED"
    )


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    return base_soak._read_json(path, fallback)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    base_soak._write_json(path, payload)


def _write_text(path: Path, body: str) -> None:
    base_soak._write_text(path, body)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    base_soak._append_jsonl(path, payload)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return base_soak._read_jsonl(path)


def _iso(dt: datetime | None = None) -> str:
    return base_soak._iso(dt)


def _num(value: Any) -> float | None:
    return base_soak._num(value)


def _runtime_dir(root: Path) -> Path:
    return root / RUNTIME_DIR.relative_to(REPO_ROOT)


def _public_dir(root: Path) -> Path:
    return root / PUBLIC_DIR.relative_to(REPO_ROOT)


def _old_dirs(root: Path) -> tuple[Path, Path]:
    return (
        root / "v2" / "frontend" / "public" / "operator_runtime" / OLD_SLUG / "latest",
        root / "v2" / "frontend" / "public" / OLD_SLUG / "latest",
    )


def archive_previous_soak(
    *,
    root: Path = REPO_ROOT,
    remediation_id: str = DEFAULT_REMEDIATION_ID,
    stopped_observer_status: str = "NO_PREVIOUS_OBSERVER_PROCESS_FOUND",
) -> dict[str, Any]:
    generated_utc = _iso()
    archive_payload = {
        "schema_version": "runtime_alpha_remediated_soak_supersession_v1",
        "generated_utc": generated_utc,
        "superseded": True,
        "superseded_slug": OLD_SLUG,
        "new_slug": SLUG,
        "remediation_id": remediation_id,
        "stopped_observer_status": stopped_observer_status,
        "reason": "runtime alpha decision-chain remediation changed paper trainer/lifecycle behavior; previous 24h soak cannot be reused",
    }
    for old_dir in _old_dirs(root):
        previous_status = _read_json(old_dir / "soak_status.json", {})
        payload = dict(archive_payload)
        payload["previous_gate"] = previous_status.get("gate")
        payload["previous_proof_status"] = previous_status.get("proof_status")
        payload["previous_completion_marker"] = previous_status.get("completion_marker")
        _write_json(old_dir / "SOAK_SUPERSEDED_BY_RUNTIME_ALPHA_REMEDIATION.json", payload)
    return archive_payload


def _alpha_payloads(root: Path) -> dict[str, Any]:
    return {
        "liquidity": _read_json(root / "liquidity_liquidation_decision_consumer_wiring_status.json", {}),
        "strategy": _read_json(root / "adaptive_strategy_weight_runtime_status.json", {}),
        "hedge": _read_json(root / "adaptive_hedging_runtime_status.json", {}),
        "hedge_cost_benefit": _read_json(root / "hedge_cost_benefit_status.json", {}),
        "exit": _read_json(root / "paper_exit_profit_protection_runtime_status.json", {}),
        "pnl": _read_json(root / "paper_pnl_reconciliation_runtime_status.json", {}),
        "feedback": _read_json(root / "trainer_strategy_hedge_exit_feedback_status.json", {}),
        "goal_10k": _read_json(root / "monthly_10k_goal_feasibility_after_alpha_remediation.json", {}),
    }


def _strategy_weight_update_status(strategy_status: dict[str, Any]) -> str:
    if not strategy_status:
        return "MISSING_STRATEGY_WEIGHT_STATUS"
    if not bool(strategy_status.get("adaptive_from_realized_outcomes")):
        return "BREACH_STATIC_STRATEGY_SELECTION"
    outcome_count = int(_num(strategy_status.get("outcome_count")) or 0)
    rows = strategy_status.get("strategy_runtime_rows")
    if outcome_count > 0 and isinstance(rows, list) and rows:
        return "ACTIVE"
    return "ACTIVE_OR_INSUFFICIENT_SAMPLE_EXPLAINED"


def _hedge_status(hedge_status: dict[str, Any]) -> str:
    if bool(hedge_status.get("same_symbol_accidental_hedge_detected")):
        return "ACCIDENTAL_HEDGE_DETECTED"
    if bool(hedge_status.get("hedge_allowed")) and hedge_status.get("hedge_type"):
        return "EXPLICIT_HEDGE_READY"
    return "NO_ACTIVE_HEDGE_INTENT"


def _exit_reason_distribution(observation: dict[str, Any], exit_status: dict[str, Any]) -> dict[str, int]:
    close_reason = exit_status.get("close_reason")
    if isinstance(close_reason, str) and close_reason:
        return {close_reason: 1}
    counts = observation.get("exit_reason_counts")
    return dict(counts) if isinstance(counts, dict) else {}


def _liquidity_consumer_status(liquidity_status: dict[str, Any]) -> str:
    if not liquidity_status:
        return "MISSING_LIQUIDITY_CONSUMER_STATUS"
    if not bool(liquidity_status.get("display_only", True)):
        risk = liquidity_status.get("risk_evaluator") if isinstance(liquidity_status.get("risk_evaluator"), dict) else {}
        if bool(liquidity_status.get("native_trainer_tensor")) and bool(risk.get("alpha_liquidity_context_used")):
            return "ACTIVE"
    return "NOT_ACTIVE"


def _current_trainer_feedback_status(redis_client: Any | None) -> dict[str, Any]:
    """Read current V2 trainer feedback evidence without writing Redis."""
    rows = base_soak._as_list(base_soak._read_v2_redis_json(redis_client, "v2:trainer:feedback:outcomes"))
    explicit_quarantine_rows = base_soak._as_list(
        base_soak._read_v2_redis_json(redis_client, "v2:trainer:feedback:outcomes:quarantine")
    )
    if not rows and not explicit_quarantine_rows:
        return {
            "source": "NO_CURRENT_REDIS_TRAINER_FEEDBACK",
            "trainer_feedback_rows": 0,
            "trainer_feedback_total_rows": 0,
            "complete_strategy_hedge_feedback_rows": 0,
            "incomplete_strategy_hedge_feedback_rows": 0,
            "dirty_consumable_feedback_rows": 0,
            "quarantined_incomplete_feedback_rows": 0,
            "current_feedback_fields_present": None,
            "trainer_feedback_readiness_status": "NO_CURRENT_REDIS_TRAINER_FEEDBACK",
            "trainer_feedback_readiness_summary": "No current Redis trainer feedback rows were found.",
            "missing_feedback_field_counts": [],
            "quarantined_feedback_example_rows": [],
            "missing_field_counts": {},
        }
    all_rows = rows + explicit_quarantine_rows
    missing_counts = {
        field: sum(1 for row in all_rows if row.get(field) in (None, ""))
        for field in REQUIRED_TRAINER_FEEDBACK_FIELDS
    }
    complete_rows = [
        row
        for row in rows
        if all(row.get(field) not in (None, "") for field in REQUIRED_TRAINER_FEEDBACK_FIELDS)
    ]
    incomplete_rows = [row for row in rows if row not in complete_rows]
    dirty_consumable_rows = [
        row
        for row in incomplete_rows
        if row.get("trainer_consumable") is True
        or not (
            row.get("trainer_consumable") is False
            or row.get("missing_feedback_fields")
            or row.get("feedback_schema_version")
        )
    ]
    quarantined_incomplete_rows = [
        row
        for row in incomplete_rows
        if row not in dirty_consumable_rows
    ] + explicit_quarantine_rows
    missing_feedback_counts: dict[str, int] = {}
    for row in all_rows:
        fields = row.get("missing_feedback_fields")
        if isinstance(fields, list):
            for field in fields:
                key = str(field or "missing")
                missing_feedback_counts[key] = missing_feedback_counts.get(key, 0) + 1
        else:
            for field in REQUIRED_TRAINER_FEEDBACK_FIELDS:
                if row.get(field) in (None, ""):
                    missing_feedback_counts[field] = missing_feedback_counts.get(field, 0) + 1
    missing_feedback_field_counts = [
        {"field": key, "count": count}
        for key, count in sorted(missing_feedback_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if dirty_consumable_rows:
        readiness_status = "DIRTY_CONSUMABLE_FEEDBACK_DETECTED"
    elif complete_rows:
        readiness_status = "COMPLETE_FEEDBACK_AVAILABLE"
    elif quarantined_incomplete_rows:
        readiness_status = "FEEDBACK_ROWS_QUARANTINED_MISSING_ALPHA_FIELDS"
    else:
        readiness_status = "NO_COMPLETE_FEEDBACK_ROWS"
    if readiness_status == "COMPLETE_FEEDBACK_AVAILABLE":
        readiness_summary = f"{len(complete_rows)}/{len(rows)} trainer feedback rows are complete and consumable."
    elif readiness_status == "FEEDBACK_ROWS_QUARANTINED_MISSING_ALPHA_FIELDS":
        top_missing = missing_feedback_field_counts[:4]
        missing_text = ", ".join(f"{row['field']}={row['count']}" for row in top_missing) or "unknown fields"
        readiness_summary = (
            f"{len(quarantined_incomplete_rows)}/{len(all_rows)} trainer feedback rows are quarantined; "
            f"{len(complete_rows)} complete rows; top missing fields: {missing_text}."
        )
    elif readiness_status == "DIRTY_CONSUMABLE_FEEDBACK_DETECTED":
        readiness_summary = (
            f"{len(dirty_consumable_rows)} incomplete trainer feedback rows are incorrectly marked consumable."
        )
    else:
        readiness_summary = f"0/{len(rows)} trainer feedback rows are complete."
    def example_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": row.get("symbol"),
            "generated_utc": row.get("generated_utc"),
            "closed_utc": row.get("closed_utc"),
            "trainer_consumable": row.get("trainer_consumable"),
            "feedback_schema_version": row.get("feedback_schema_version"),
            "missing_feedback_fields": row.get("missing_feedback_fields") or [],
        }
    return {
        "source": "redis:v2:trainer:feedback:outcomes"
        if rows
        else "redis:v2:trainer:feedback:outcomes:quarantine",
        "trainer_feedback_rows": len(complete_rows),
        "trainer_feedback_total_rows": len(all_rows),
        "complete_strategy_hedge_feedback_rows": len(complete_rows),
        "incomplete_strategy_hedge_feedback_rows": len(all_rows) - len(complete_rows),
        "dirty_consumable_feedback_rows": len(dirty_consumable_rows),
        "quarantined_incomplete_feedback_rows": len(quarantined_incomplete_rows),
        "current_feedback_fields_present": bool(complete_rows),
        "trainer_feedback_readiness_status": readiness_status,
        "trainer_feedback_readiness_summary": readiness_summary,
        "missing_feedback_field_counts": missing_feedback_field_counts,
        "quarantined_feedback_example_rows": [example_row(row) for row in quarantined_incomplete_rows[-5:]],
        "missing_field_counts": missing_counts,
    }


FORWARD_INTENT_CONTEXT_FIELDS = (
    "strategy_id",
    "strategy_family",
    "drawdown_at_entry",
    "market_regime_at_entry",
    "liquidity_zone_context",
    "liquidation_distance_context",
    "microstructure_context",
)


def _current_paper_intent_entry_context_status(redis_client: Any | None) -> dict[str, Any]:
    """Read current paper intent context needed for future trainer feedback."""
    rows = base_soak._as_list(base_soak._read_v2_redis_json(redis_client, "v2:paper:intents"))

    def sorted_counts(values: list[Any]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value or "missing")
            counts[key] = counts.get(key, 0) + 1
        return [
            {"reason": key, "count": count}
            for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def list_values(key: str) -> list[Any]:
        out: list[Any] = []
        for row in rows:
            values = row.get(key)
            if isinstance(values, list):
                out.extend(values)
            elif values not in (None, ""):
                out.append(values)
        return out

    def router_reason_codes() -> list[Any]:
        out: list[Any] = []
        for row in rows:
            router = row.get("strategy_router")
            router = router if isinstance(router, dict) else {}
            codes = router.get("reason_codes") or row.get("strategy_reason_codes") or []
            if isinstance(codes, list):
                out.extend(codes)
            elif codes not in (None, ""):
                out.append(codes)
        return out

    def selected_cutoff_rows() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            router = row.get("strategy_router")
            router = router if isinstance(router, dict) else {}
            explanation = router.get("explanation") if isinstance(router.get("explanation"), dict) else {}
            for key in ("lower_timeframe", "mid_timeframe", "higher_timeframe"):
                tf = explanation.get(key) if isinstance(explanation.get(key), dict) else {}
                cutoff = tf.get("feature_cutoff")
                if cutoff not in (None, ""):
                    out.append(
                        {
                            "symbol": row.get("symbol"),
                            "prediction_timeframe": row.get("timeframe"),
                            "generated_utc": row.get("generated_utc"),
                            "router_block_reason": router.get("block_reason"),
                            "router_reason_codes": router.get("reason_codes") or [],
                            "selected_timeframe_slot": key,
                            "selected_timeframe": tf.get("timeframe"),
                            "selected_direction": tf.get("direction"),
                            "selected_confidence": tf.get("confidence"),
                            "feature_cutoff": cutoff,
                        }
                    )
        return out

    def no_trade_example(row: dict[str, Any]) -> dict[str, Any]:
        strategy_router = row.get("strategy_router")
        strategy_router = strategy_router if isinstance(strategy_router, dict) else {}
        explanation = strategy_router.get("explanation")
        explanation = explanation if isinstance(explanation, dict) else {}
        higher = explanation.get("higher_timeframe") if isinstance(explanation.get("higher_timeframe"), dict) else {}
        mid = explanation.get("mid_timeframe") if isinstance(explanation.get("mid_timeframe"), dict) else {}
        lower = explanation.get("lower_timeframe") if isinstance(explanation.get("lower_timeframe"), dict) else {}
        return {
            "generated_utc": row.get("generated_utc"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "side": row.get("side"),
            "prediction_id": row.get("prediction_id"),
            "strategy_id": row.get("strategy_id"),
            "market_regime_at_entry": row.get("market_regime_at_entry"),
            "paper_fill_block_reason": row.get("paper_fill_block_reason"),
            "local_block_reasons": row.get("local_block_reasons") or [],
            "paper_fill_gate_block_reasons": row.get("paper_fill_gate_block_reasons") or [],
            "allocator_decision": row.get("allocator_decision"),
            "allocator_reason": row.get("allocator_reason"),
            "router_block_reason": strategy_router.get("block_reason"),
            "router_reason_codes": strategy_router.get("reason_codes") or [],
            "router_allowed_actions": strategy_router.get("allowed_actions") or [],
            "router_confidence": strategy_router.get("confidence"),
            "strategy_decision_time": row.get("strategy_decision_time"),
            "strategy_feature_cutoff": row.get("strategy_feature_cutoff"),
            "strategy_future_cutoff_offender_count": row.get("strategy_future_cutoff_offender_count"),
            "strategy_future_cutoff_offenders": row.get("strategy_future_cutoff_offenders") or [],
            "execution_success_probability": explanation.get("execution_success_probability"),
            "execution_success_metric_source": row.get("execution_success_metric_source"),
            "closed_trade_outcome_count": row.get("closed_trade_outcome_count"),
            "expected_move_bps": explanation.get("expected_move_bps"),
            "data_quality_score": explanation.get("data_quality_score"),
            "ppo_action": explanation.get("ppo_action"),
            "ppo_confidence": explanation.get("ppo_confidence"),
            "masa_confidence": explanation.get("masa_confidence"),
            "higher_timeframe": {
                "timeframe": higher.get("timeframe"),
                "direction": higher.get("direction"),
                "confidence": higher.get("confidence"),
                "feature_cutoff": higher.get("feature_cutoff"),
            },
            "mid_timeframe": {
                "timeframe": mid.get("timeframe"),
                "direction": mid.get("direction"),
                "confidence": mid.get("confidence"),
                "feature_cutoff": mid.get("feature_cutoff"),
            },
            "lower_timeframe": {
                "timeframe": lower.get("timeframe"),
                "direction": lower.get("direction"),
                "confidence": lower.get("confidence"),
                "feature_cutoff": lower.get("feature_cutoff"),
            },
        }

    if not rows:
        return {
            "source": "NO_CURRENT_REDIS_PAPER_INTENTS",
            "paper_intent_rows": 0,
            "symbol_count": 0,
            "timeframe_count": 0,
            "symbol_counts": [],
            "timeframe_counts": [],
            "entry_context_rows": 0,
            "entry_context_fields_present": None,
            "accepted_candidate_rows": 0,
            "accepted_candidate_context_rows": 0,
            "no_trade_context_rows": 0,
            "strategy_id_counts": [],
            "market_regime_counts": [],
            "paper_fill_block_reason_counts": [],
            "allocator_decision_counts": [],
            "allocator_reason_counts": [],
            "local_block_reason_counts": [],
            "paper_fill_gate_block_reason_counts": [],
            "router_reason_code_counts": [],
            "selected_timeframe_cutoff_examples": [],
            "no_trade_example_rows": [],
            "future_cutoff_offender_examples": [],
            "missing_field_counts": {},
        }
    missing_counts = {
        field: sum(1 for row in rows if row.get(field) in (None, ""))
        for field in FORWARD_INTENT_CONTEXT_FIELDS
    }
    context_rows = [
        row
        for row in rows
        if all(row.get(field) not in (None, "") for field in FORWARD_INTENT_CONTEXT_FIELDS)
    ]

    def is_executable_entry_candidate(row: dict[str, Any]) -> bool:
        if row.get("decision") == "ACCEPTED_PAPER_FILL":
            return True
        if row.get("economic_fill_candidate") is not True:
            return False
        return (
            row.get("paper_fill_allowed") is True
            and row.get("paper_sizing_complete") is True
            and row.get("paper_sizing_source") == "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR"
            and _num(row.get("quantity")) is not None
            and _num(row.get("notional_usdt") or row.get("notional")) is not None
            and _num(row.get("entry_price") or row.get("fill_price")) is not None
            and bool(row.get("risk_decision_id"))
            and bool(row.get("orchestrator_decision_id"))
            and bool(row.get("signal_id"))
        )

    accepted_candidates = [
        row
        for row in rows
        if is_executable_entry_candidate(row)
    ]
    accepted_context_rows = [
        row
        for row in accepted_candidates
        if all(row.get(field) not in (None, "") for field in FORWARD_INTENT_CONTEXT_FIELDS)
    ]
    no_trade_context_rows = [
        row
        for row in context_rows
        if str(row.get("strategy_id") or row.get("strategy_family") or "").lower() == "no_trade_mode"
    ]
    no_trade_examples = [
        no_trade_example(row)
        for row in no_trade_context_rows[-12:]
        if isinstance(row, dict)
    ]
    future_cutoff_offender_examples = [
        no_trade_example(row)
        for row in no_trade_context_rows
        if isinstance(row, dict) and int(_num(row.get("strategy_future_cutoff_offender_count")) or 0) > 0
    ][-12:]
    cutoff_examples = selected_cutoff_rows()[-12:]
    return {
        "source": "redis:v2:paper:intents",
        "paper_intent_rows": len(rows),
        "symbol_count": len({str(row.get("symbol") or "") for row in rows if row.get("symbol")}),
        "timeframe_count": len({str(row.get("timeframe") or "") for row in rows if row.get("timeframe")}),
        "symbol_counts": sorted_counts([row.get("symbol") for row in rows]),
        "timeframe_counts": sorted_counts([row.get("timeframe") for row in rows]),
        "entry_context_rows": len(context_rows),
        "entry_context_fields_present": len(context_rows) == len(rows),
        "accepted_candidate_rows": len(accepted_candidates),
        "accepted_candidate_context_rows": len(accepted_context_rows),
        "no_trade_context_rows": len(no_trade_context_rows),
        "strategy_id_counts": sorted_counts([row.get("strategy_id") for row in rows]),
        "market_regime_counts": sorted_counts([row.get("market_regime_at_entry") for row in rows]),
        "paper_fill_block_reason_counts": sorted_counts([row.get("paper_fill_block_reason") for row in rows]),
        "allocator_decision_counts": sorted_counts([row.get("allocator_decision") for row in rows]),
        "allocator_reason_counts": sorted_counts([row.get("allocator_reason") for row in rows]),
        "local_block_reason_counts": sorted_counts(list_values("local_block_reasons")),
        "paper_fill_gate_block_reason_counts": sorted_counts(list_values("paper_fill_gate_block_reasons")),
        "router_reason_code_counts": sorted_counts(router_reason_codes()),
        "selected_timeframe_cutoff_examples": cutoff_examples,
        "no_trade_example_rows": no_trade_examples,
        "future_cutoff_offender_examples": future_cutoff_offender_examples,
        "missing_field_counts": missing_counts,
    }


def _top_count(counts: Any) -> dict[str, Any] | None:
    if not isinstance(counts, list) or not counts:
        return None
    first = counts[0]
    return first if isinstance(first, dict) else None


def _count_for_reason(counts: Any, reason: str) -> int:
    if not isinstance(counts, list):
        return 0
    for row in counts:
        if isinstance(row, dict) and row.get("reason") == reason:
            return int(_num(row.get("count")) or 0)
    return 0


def _current_no_trade_root_cause_status(context: dict[str, Any]) -> dict[str, Any]:
    """Summarize why current paper intents are not executable."""
    local_counts = context.get("local_block_reason_counts")
    fill_counts = context.get("paper_fill_gate_block_reason_counts")
    allocator_counts = context.get("allocator_decision_counts")
    allocator_reason_counts = context.get("allocator_reason_counts")
    regime_counts = context.get("market_regime_counts")
    top_local = _top_count(local_counts)
    top_fill = _top_count(fill_counts)
    top_allocator = _top_count(allocator_counts)
    top_allocator_reason = _top_count(allocator_reason_counts)
    top_regime = _top_count(regime_counts)
    no_trade_rows = int(_num(context.get("no_trade_context_rows")) or 0)
    paper_intent_rows = int(_num(context.get("paper_intent_rows")) or 0)
    executable_rows = int(_num(context.get("accepted_candidate_rows")) or 0)
    execution_low_count = _count_for_reason(
        local_counts,
        "strategy_router:EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD",
    )
    router_reason_code_counts = context.get("router_reason_code_counts")
    top_router_reason_code = _top_count(router_reason_code_counts)
    masa_cutoff_count = _count_for_reason(local_counts, "strategy_router:MASA_FUTURE_CUTOFF_BLOCK")
    if masa_cutoff_count <= 0:
        masa_cutoff_count = _count_for_reason(router_reason_code_counts, "MASA_FUTURE_CUTOFF_BLOCK")
    confidence_low_count = _count_for_reason(fill_counts, "confidence_below_threshold")
    edge_low_count = _count_for_reason(fill_counts, "expected_move_after_cost_below_threshold")
    summary_parts = [
        f"{no_trade_rows}/{paper_intent_rows} current paper intents are no-trade",
        f"{executable_rows} executable candidates",
    ]
    if top_local:
        summary_parts.append(f"top router blocker is {top_local.get('reason')} ({top_local.get('count')})")
    if top_fill:
        summary_parts.append(f"top paper fill gate blocker is {top_fill.get('reason')} ({top_fill.get('count')})")
    if top_allocator:
        summary_parts.append(f"top allocator decision is {top_allocator.get('reason')} ({top_allocator.get('count')})")
    return {
        "source": "redis:v2:paper:intents",
        "redis_keys_used": [
            "v2:paper:intents",
            "v2:trainer:feedback:outcomes",
            "v2:paper:ledger",
        ],
        "paper_intent_rows": paper_intent_rows,
        "no_trade_context_rows": no_trade_rows,
        "accepted_candidate_rows": executable_rows,
        "primary_router_blocker": top_local,
        "primary_fill_gate_blocker": top_fill,
        "primary_allocator_decision": top_allocator,
        "primary_allocator_reason": top_allocator_reason,
        "primary_market_regime": top_regime,
        "primary_router_reason_code": top_router_reason_code,
        "execution_success_probability_below_threshold_count": execution_low_count,
        "masa_future_cutoff_block_count": masa_cutoff_count,
        "confidence_below_threshold_count": confidence_low_count,
        "expected_move_after_cost_below_threshold_count": edge_low_count,
        "natural_language_summary": "; ".join(summary_parts) + ".",
        "confidence_contributors": {
            "router_reason_codes": "see forward_paper_no_trade_example_rows[].router_reason_codes",
            "ppo_confidence": "see forward_paper_no_trade_example_rows[].ppo_confidence",
            "masa_confidence": "see forward_paper_no_trade_example_rows[].masa_confidence",
            "timeframe_confidence": "see lower_timeframe/mid_timeframe/higher_timeframe confidence fields",
            "expected_move_bps": "see forward_paper_no_trade_example_rows[].expected_move_bps",
            "execution_success_probability": "see forward_paper_no_trade_example_rows[].execution_success_probability",
            "execution_success_metric_source": "see forward_paper_no_trade_example_rows[].execution_success_metric_source",
            "future_cutoff_offenders": "see forward_paper_future_cutoff_offender_examples[].strategy_future_cutoff_offenders",
            "data_quality_score": "see forward_paper_no_trade_example_rows[].data_quality_score",
            "paper_fill_gate_blockers": "see paper_fill_gate_block_reason_counts",
        },
        "selected_timeframe_cutoff_examples": context.get("selected_timeframe_cutoff_examples") or [],
        "future_cutoff_offender_examples": context.get("future_cutoff_offender_examples") or [],
    }


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_paper_ledger_static_sizing_status(redis_client: Any | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Classify static accepted ledger rows without mutating historical evidence."""
    payload = base_soak._read_v2_redis_json(redis_client, "v2:paper:ledger")
    if not isinstance(payload, dict):
        return {
            "source": "NO_CURRENT_REDIS_PAPER_LEDGER",
            "accepted_ledger_rows": 0,
            "adaptive_accepted_ledger_rows": 0,
            "legacy_static_accepted_ledger_rows": 0,
            "current_cycle_static_accepted_ledger_rows": 0,
            "latest_legacy_static_accepted_generated_utc": None,
            "latest_legacy_static_accepted_age_seconds": None,
            "historical_static_ledger_status": "NO_LEDGER_ACCEPTED_ROWS",
            "legacy_static_examples": [],
            "current_cycle_static_examples": [],
        }
    accepted_rows = base_soak._as_list(payload.get("accepted_intents") or payload.get("accepted") or [])
    now_dt = now or datetime.now(timezone.utc)

    def sizing_source(row: dict[str, Any]) -> str:
        return str(row.get("paper_sizing_source") or row.get("sizing_source") or row.get("policy") or "")

    def is_static(row: dict[str, Any]) -> bool:
        source = sizing_source(row).upper()
        if not source:
            return False
        if "ADAPTIVE" in source:
            return False
        return "DEFAULT_NOTIONAL" in source or "STATIC" in source or "FIXED" in source

    def is_adaptive(row: dict[str, Any]) -> bool:
        return "ADAPTIVE" in sizing_source(row).upper()

    def is_historical_carry_forward(row: dict[str, Any]) -> bool:
        return (
            row.get("paper_fill_persistence_status") == "EXISTING_FILL_CARRIED_FORWARD"
            or row.get("paper_lifecycle_status") == "CLOSED_PREVIOUSLY"
            or row.get("lifecycle_status") == "CLOSED_PREVIOUSLY"
        )

    def example(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "generated_utc": row.get("generated_utc") or row.get("fill_generated_utc"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "side": row.get("side"),
            "paper_sizing_source": sizing_source(row) or None,
            "notional_usdt": row.get("notional_usdt") or row.get("notional"),
            "paper_fill_persistence_status": row.get("paper_fill_persistence_status"),
            "paper_lifecycle_status": row.get("paper_lifecycle_status") or row.get("lifecycle_status"),
        }

    static_rows = [row for row in accepted_rows if isinstance(row, dict) and is_static(row)]
    adaptive_rows = [row for row in accepted_rows if isinstance(row, dict) and is_adaptive(row)]
    current_cycle_static_rows = [row for row in static_rows if not is_historical_carry_forward(row)]
    legacy_static_rows = [row for row in static_rows if is_historical_carry_forward(row)]
    latest_static = max(
        (_parse_utc(row.get("generated_utc") or row.get("fill_generated_utc")) for row in legacy_static_rows),
        default=None,
    )
    status = "CLEAR"
    if current_cycle_static_rows:
        status = "CURRENT_CYCLE_STATIC_ACCEPTED_FILL"
    elif legacy_static_rows:
        status = "LEGACY_STATIC_ACCEPTED_ROWS_QUARANTINED"
    elif not accepted_rows:
        status = "NO_LEDGER_ACCEPTED_ROWS"
    return {
        "source": "redis:v2:paper:ledger",
        "accepted_ledger_rows": len(accepted_rows),
        "adaptive_accepted_ledger_rows": len(adaptive_rows),
        "legacy_static_accepted_ledger_rows": len(legacy_static_rows),
        "current_cycle_static_accepted_ledger_rows": len(current_cycle_static_rows),
        "latest_legacy_static_accepted_generated_utc": latest_static.isoformat().replace("+00:00", "Z")
        if latest_static
        else None,
        "latest_legacy_static_accepted_age_seconds": round((now_dt - latest_static).total_seconds(), 3)
        if latest_static
        else None,
        "historical_static_ledger_status": status,
        "legacy_static_examples": [example(row) for row in legacy_static_rows[-5:]],
        "current_cycle_static_examples": [example(row) for row in current_cycle_static_rows[-5:]],
    }


def collect_alpha_observation(
    *,
    root: Path = REPO_ROOT,
    redis_client: Any | None = None,
    now: datetime | None = None,
    remediation_id: str = DEFAULT_REMEDIATION_ID,
) -> dict[str, Any]:
    observation = base_soak.collect_observation(root=root, redis_client=redis_client, now=now)
    payloads = _alpha_payloads(root)
    liquidity = payloads["liquidity"]
    strategy = payloads["strategy"]
    hedge = payloads["hedge"]
    hedge_cost_benefit = payloads["hedge_cost_benefit"]
    exit_status = payloads["exit"]
    pnl = payloads["pnl"]
    feedback = payloads["feedback"]
    goal_10k = payloads["goal_10k"]
    current_feedback = _current_trainer_feedback_status(redis_client)
    current_forward_context = _current_paper_intent_entry_context_status(redis_client)
    current_no_trade_root_cause = _current_no_trade_root_cause_status(current_forward_context)
    current_ledger_static = _current_paper_ledger_static_sizing_status(redis_client, now=now)
    current_feedback_rows = int(_num(current_feedback.get("trainer_feedback_rows")) or 0)
    current_feedback_total_rows = int(_num(current_feedback.get("trainer_feedback_total_rows")) or 0)
    current_complete_feedback_rows = int(_num(current_feedback.get("complete_strategy_hedge_feedback_rows")) or 0)
    current_dirty_consumable_rows = int(_num(current_feedback.get("dirty_consumable_feedback_rows")) or 0)
    current_quarantined_feedback_rows = int(_num(current_feedback.get("quarantined_incomplete_feedback_rows")) or 0)
    observation_feedback_rows = int(_num(observation.get("trainer_feedback_rows_count")) or 0)
    static_feedback_rows = int(_num(feedback.get("trainer_feedback_rows")) or 0)
    has_current_feedback_evidence = current_feedback_total_rows > 0 or current_feedback.get("source") != "NO_CURRENT_REDIS_TRAINER_FEEDBACK"
    trainer_feedback_rows = (
        current_feedback_rows
        if has_current_feedback_evidence
        else observation_feedback_rows or static_feedback_rows
    )
    trainer_feedback_total_rows = (
        current_feedback_total_rows
        if has_current_feedback_evidence
        else trainer_feedback_rows
    )
    current_fields_present = current_feedback.get("current_feedback_fields_present")
    static_fields_present = bool(
        feedback.get("strategy_fields_present")
        and feedback.get("hedge_fields_present")
        and feedback.get("liquidity_fields_present")
        and feedback.get("microstructure_fields_present")
        and feedback.get("exit_fields_present")
    )
    trainer_feedback_alpha_fields_present = (
        bool(current_fields_present) if current_fields_present is not None else static_fields_present
    )
    trainer_feedback_alpha_status = {} if has_current_feedback_evidence else dict(feedback)
    trainer_feedback_alpha_status.update(
        {
            "current_feedback_source": current_feedback.get("source"),
            "current_trainer_feedback_rows": current_feedback_rows,
            "current_trainer_feedback_total_rows": current_feedback_total_rows,
            "current_complete_strategy_hedge_feedback_rows": current_feedback.get(
                "complete_strategy_hedge_feedback_rows"
            ),
            "current_incomplete_strategy_hedge_feedback_rows": current_feedback.get(
                "incomplete_strategy_hedge_feedback_rows"
            ),
            "current_dirty_consumable_feedback_rows": current_feedback.get("dirty_consumable_feedback_rows"),
            "current_quarantined_incomplete_feedback_rows": current_feedback.get(
                "quarantined_incomplete_feedback_rows"
            ),
            "current_missing_field_counts": current_feedback.get("missing_field_counts"),
            "current_feedback_fields_present": current_fields_present,
            "current_feedback_readiness_status": current_feedback.get("trainer_feedback_readiness_status"),
            "current_feedback_readiness_summary": current_feedback.get("trainer_feedback_readiness_summary"),
            "current_missing_feedback_field_counts": current_feedback.get("missing_feedback_field_counts"),
            "current_quarantined_feedback_example_rows": current_feedback.get("quarantined_feedback_example_rows"),
            "static_alpha_feedback_rows": static_feedback_rows,
            "trainer_feedback_rows": trainer_feedback_rows,
            "trainer_feedback_total_rows": trainer_feedback_total_rows,
            "trainer_feedback_quarantined_rows": current_quarantined_feedback_rows,
            "trainer_consumable_rows": current_feedback.get("complete_strategy_hedge_feedback_rows")
            if has_current_feedback_evidence
            else feedback.get("trainer_consumable_rows"),
        }
    )

    observation.update(
        {
            "schema_version": "runtime_alpha_remediated_soak_observation_v1",
            "soak_slug": SLUG,
            "remediation_id": remediation_id,
            "liquidity_decision_consumer_status": _liquidity_consumer_status(liquidity),
            "liquidity_consumer_hits": 1 if _liquidity_consumer_status(liquidity) == "ACTIVE" else 0,
            "liquidation_zone_tensor_field_presence": bool(liquidity.get("native_trainer_tensor")),
            "risk_liquidation_proximity_influence": bool(
                isinstance(liquidity.get("risk_evaluator"), dict)
                and liquidity["risk_evaluator"].get("alpha_liquidity_context_used")
            ),
            "orchestrator_liquidation_proximity_influence": bool(
                isinstance(liquidity.get("orchestrator"), dict)
                and "signal_adjustment" in liquidity["orchestrator"]
            ),
            "strategy_weight_update_status": _strategy_weight_update_status(strategy),
            "strategy_weights_by_family": strategy.get("strategy_runtime_rows") if isinstance(strategy, dict) else [],
            "strategy_outcome_count": int(_num(strategy.get("outcome_count")) or 0) if isinstance(strategy, dict) else 0,
            "hedge_status": _hedge_status(hedge),
            "hedge_intents": 1 if hedge.get("hedge_reason") else 0,
            "hedge_approvals": 1 if hedge.get("hedge_allowed") else 0,
            "hedge_blocks": len(hedge.get("hedge_blockers") or []) if isinstance(hedge.get("hedge_blockers"), list) else 0,
            "hedge_cost_benefit_tracked": bool(hedge_cost_benefit.get("hedge_cost_benefit_tracked")),
            "hedge_cost_benefit": hedge_cost_benefit,
            "exit_reason_distribution": _exit_reason_distribution(observation, exit_status),
            "exit_reason_count": len(_exit_reason_distribution(observation, exit_status)),
            "profit_lock_profit_bank_events": 1
            if str(exit_status.get("close_reason") or "").startswith(("TIER_", "PROFIT_", "PROFIT"))
            else 0,
            "paper_pnl_reconciliation_status": pnl.get("reconciliation_status") or "MISSING_PNL_RECONCILIATION_STATUS",
            "paper_pnl_reconciliation": pnl,
            "closed_positions_count": int(_num(pnl.get("closed_positions_count")) or observation.get("closed_trades_count") or 0),
            "trainer_feedback_alpha_fields_present": trainer_feedback_alpha_fields_present,
            "trainer_feedback_alpha_status": trainer_feedback_alpha_status,
            "trainer_feedback_row_count": trainer_feedback_rows,
            "trainer_feedback_rows_count": trainer_feedback_rows,
            "trainer_feedback_total_row_count": trainer_feedback_total_rows,
            "trainer_feedback_quarantined_row_count": current_quarantined_feedback_rows,
            "trainer_feedback_complete_row_count": current_complete_feedback_rows
            if has_current_feedback_evidence
            else int(_num(feedback.get("trainer_consumable_rows")) or 0),
            "trainer_feedback_dirty_consumable_row_count": current_dirty_consumable_rows,
            "trainer_feedback_readiness_status": current_feedback.get("trainer_feedback_readiness_status"),
            "trainer_feedback_readiness_summary": current_feedback.get("trainer_feedback_readiness_summary"),
            "trainer_feedback_missing_field_counts": current_feedback.get("missing_feedback_field_counts"),
            "trainer_feedback_quarantined_example_rows": current_feedback.get("quarantined_feedback_example_rows"),
            "forward_paper_intent_entry_context_status": current_forward_context,
            "forward_paper_intent_entry_context_fields_present": current_forward_context.get(
                "entry_context_fields_present"
            ),
            "forward_paper_intent_entry_context_rows": current_forward_context.get("entry_context_rows"),
            "forward_paper_intent_rows": current_forward_context.get("paper_intent_rows"),
            "forward_paper_symbol_count": current_forward_context.get("symbol_count"),
            "forward_paper_timeframe_count": current_forward_context.get("timeframe_count"),
            "forward_paper_symbol_counts": current_forward_context.get("symbol_counts"),
            "forward_paper_timeframe_counts": current_forward_context.get("timeframe_counts"),
            "forward_paper_accepted_candidate_rows": current_forward_context.get("accepted_candidate_rows"),
            "forward_paper_accepted_candidate_context_rows": current_forward_context.get(
                "accepted_candidate_context_rows"
            ),
            "forward_paper_no_trade_context_rows": current_forward_context.get("no_trade_context_rows"),
            "forward_paper_no_trade_reason_status": {
                "strategy_id_counts": current_forward_context.get("strategy_id_counts"),
                "symbol_counts": current_forward_context.get("symbol_counts"),
                "timeframe_counts": current_forward_context.get("timeframe_counts"),
                "market_regime_counts": current_forward_context.get("market_regime_counts"),
                "paper_fill_block_reason_counts": current_forward_context.get("paper_fill_block_reason_counts"),
                "allocator_decision_counts": current_forward_context.get("allocator_decision_counts"),
                "allocator_reason_counts": current_forward_context.get("allocator_reason_counts"),
                "local_block_reason_counts": current_forward_context.get("local_block_reason_counts"),
                "paper_fill_gate_block_reason_counts": current_forward_context.get(
                    "paper_fill_gate_block_reason_counts"
                ),
                "router_reason_code_counts": current_forward_context.get("router_reason_code_counts"),
                "selected_timeframe_cutoff_examples": current_forward_context.get(
                    "selected_timeframe_cutoff_examples"
                ),
                "no_trade_example_rows": current_forward_context.get("no_trade_example_rows"),
                "future_cutoff_offender_examples": current_forward_context.get(
                    "future_cutoff_offender_examples"
                ),
            },
            "forward_paper_no_trade_root_cause_status": current_no_trade_root_cause,
            "paper_ledger_static_sizing_status": current_ledger_static,
            "paper_ledger_static_sizing_regression_status": current_ledger_static.get(
                "historical_static_ledger_status"
            ),
            "paper_ledger_accepted_rows": current_ledger_static.get("accepted_ledger_rows"),
            "paper_ledger_adaptive_accepted_rows": current_ledger_static.get("adaptive_accepted_ledger_rows"),
            "paper_ledger_legacy_static_accepted_rows": current_ledger_static.get(
                "legacy_static_accepted_ledger_rows"
            ),
            "paper_ledger_current_cycle_static_accepted_rows": current_ledger_static.get(
                "current_cycle_static_accepted_ledger_rows"
            ),
            "monthly_10k_goal_feasibility_status": goal_10k.get("goal_status")
            or "INSUFFICIENT_SAMPLE_FOR_10K_TARGET",
            "monthly_10k_goal_feasibility": goal_10k,
            "live_unchanged_after_remediation": True,
            "places_real_order": False,
            "exchange_action_taken": False,
            "test_order_attempted": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
        }
    )
    return observation


def build_alpha_soak_status(
    observations: list[dict[str, Any]],
    *,
    generated_utc: str | None = None,
    required_seconds: int = DEFAULT_REQUIRED_SECONDS,
    interval_seconds: int = 300,
    remediation_id: str = DEFAULT_REMEDIATION_ID,
) -> dict[str, Any]:
    base_status = base_soak.build_soak_status(
        observations,
        generated_utc=generated_utc,
        required_seconds=required_seconds,
        interval_seconds=interval_seconds,
    )
    latest = observations[-1] if observations else {}

    def latest_non_empty(key: str) -> Any:
        for row in reversed(observations):
            value = row.get(key)
            if value not in (None, "", [], {}):
                return value
        return latest.get(key)

    max_closed = max((int(_num(row.get("closed_positions_count") or row.get("closed_trades_count")) or 0) for row in observations), default=0)
    max_outcomes = max((int(_num(row.get("outcome_labels_count") or row.get("outcome_label_count")) or 0) for row in observations), default=0)
    # Feedback contract quality is a current-state invariant. Do not use max()
    # across older observations, because earlier rows can predate quarantine
    # semantics and make incomplete feedback look consumable.
    current_feedback = int(_num(latest.get("trainer_feedback_rows_count") or latest.get("trainer_feedback_row_count")) or 0)
    current_total_feedback = int(_num(latest.get("trainer_feedback_total_row_count")) or 0)
    current_quarantined_feedback = int(_num(latest.get("trainer_feedback_quarantined_row_count")) or 0)
    current_complete_feedback = int(_num(latest.get("trainer_feedback_complete_row_count")) or 0)
    current_dirty_consumable_feedback = int(_num(latest.get("trainer_feedback_dirty_consumable_row_count")) or 0)
    max_exit_reasons = max((int(_num(row.get("exit_reason_count")) or 0) for row in observations), default=0)

    high_severity_alerts = list(base_status.get("high_severity_alerts") or [])
    if any(row.get("liquidity_decision_consumer_status") not in ("ACTIVE",) for row in observations):
        high_severity_alerts.append("LIQUIDITY_DECISION_CONSUMER_NOT_ACTIVE")
    if any(row.get("hedge_status") == "ACCIDENTAL_HEDGE_DETECTED" for row in observations):
        high_severity_alerts.append("ACCIDENTAL_HEDGE_DETECTED")
    if any(row.get("paper_pnl_reconciliation_status") not in ("RECONCILED",) for row in observations):
        high_severity_alerts.append("PAPER_PNL_NOT_RECONCILED")
    if current_dirty_consumable_feedback > 0:
        high_severity_alerts.append("DIRTY_TRAINER_FEEDBACK_MARKED_CONSUMABLE")
    if any(int(_num(row.get("paper_ledger_current_cycle_static_accepted_rows")) or 0) > 0 for row in observations):
        high_severity_alerts.append("CURRENT_CYCLE_STATIC_ACCEPTED_FILL")
    if current_total_feedback > 0 and current_quarantined_feedback > 0:
        high_severity_alerts = [
            alert
            for alert in high_severity_alerts
            if alert != "OUTCOME_LABELS_WITHOUT_TRAINER_FEEDBACK"
        ]
    high_severity_alerts = sorted(set(high_severity_alerts))

    criteria = dict(base_status.get("success_criteria") or {})
    criteria.update(
        {
            "elapsed_seconds_gte_required_window": int(base_status.get("completion_window_elapsed_seconds") or 0) >= required_seconds,
            "density_freshness_gates_active": bool(base_status.get("observation_density_status"))
            and bool(base_status.get("last_observation_freshness_status")),
            "high_alerts_empty": not high_severity_alerts,
            "fixed_sizing_clear": latest.get("static_sizing_regression_status") == "CLEAR",
            "same_symbol_stack_hedge_clear": latest.get("same_symbol_stack_status") == "CLEAR"
            and latest.get("same_symbol_hedge_status") == "CLEAR"
            and latest.get("hedge_status") != "ACCIDENTAL_HEDGE_DETECTED",
            "live_balance_hold_clear": latest.get("live_balance_hold_status") == "CLEAR",
            "closed_positions_gt_0": max_closed > 0,
            "outcome_label_count_gt_0": max_outcomes > 0,
            "trainer_feedback_rows_gt_0": current_feedback > 0,
            "trainer_feedback_row_count_gt_0": current_feedback > 0,
            "trainer_consumable_feedback_count_gt_0": current_complete_feedback > 0,
            "trainer_feedback_total_rows_gt_0": current_total_feedback > 0,
            "paper_pnl_reconciliation_reconciled": latest.get("paper_pnl_reconciliation_status") == "RECONCILED",
            "liquidity_decision_consumer_active": latest.get("liquidity_decision_consumer_status") == "ACTIVE",
            "strategy_weight_update_active_or_explained": latest.get("strategy_weight_update_status")
            in ("ACTIVE", "ACTIVE_OR_INSUFFICIENT_SAMPLE_EXPLAINED"),
            "hedge_status_not_accidental": latest.get("hedge_status") != "ACCIDENTAL_HEDGE_DETECTED",
            "exit_reason_count_gt_0": max_exit_reasons > 0,
            "trainer_feedback_alpha_fields_present": bool(latest.get("trainer_feedback_alpha_fields_present")),
            "current_cycle_static_accepted_ledger_rows_zero": int(
                _num(latest.get("paper_ledger_current_cycle_static_accepted_rows")) or 0
            )
            == 0,
        }
    )
    soak_complete = all(bool(value) for value in criteria.values()) and not high_severity_alerts
    soak_24h_complete = soak_complete and int(base_status.get("completion_window_elapsed_seconds") or 0) >= 24 * 3600
    window_label = _window_label(required_seconds)
    window_suffix = _gate_suffix(required_seconds)
    gate = _blocked_gate(required_seconds) if high_severity_alerts else _ready_gate(required_seconds)
    completion_marker = (
        _complete_blocked_gate(required_seconds)
        if high_severity_alerts
        else _complete_ready_gate(required_seconds)
        if soak_complete
        else None
    )
    proof_status = (
        f"SOAK_{window_suffix}_COMPLETE"
        if soak_complete
        else f"PENDING_{window_suffix}_OBSERVATION"
        if not high_severity_alerts
        else "BLOCKED_BY_SAFETY_INVARIANT"
    )

    latest_metrics = dict(base_status.get("latest_metrics") or {})
    latest_forward_reason_status = latest_non_empty("forward_paper_no_trade_reason_status")
    latest_forward_reason_status = (
        latest_forward_reason_status if isinstance(latest_forward_reason_status, dict) else {}
    )
    latest_metrics.update(
        {
            "paper_equity": latest_non_empty("paper_equity"),
            "paper_equity_source": latest_non_empty("paper_equity_source"),
            "liquidity_consumer_hits": latest.get("liquidity_consumer_hits"),
            "liquidity_decision_consumer_status": latest.get("liquidity_decision_consumer_status"),
            "liquidation_zone_tensor_field_presence": latest.get("liquidation_zone_tensor_field_presence"),
            "risk_liquidation_proximity_influence": latest.get("risk_liquidation_proximity_influence"),
            "orchestrator_liquidation_proximity_influence": latest.get("orchestrator_liquidation_proximity_influence"),
            "strategy_weight_update_status": latest.get("strategy_weight_update_status"),
            "strategy_weights_by_family": latest.get("strategy_weights_by_family"),
            "hedge_status": latest.get("hedge_status"),
            "hedge_intents": latest.get("hedge_intents"),
            "hedge_approvals": latest.get("hedge_approvals"),
            "hedge_blocks": latest.get("hedge_blocks"),
            "hedge_cost_benefit_tracked": latest.get("hedge_cost_benefit_tracked"),
            "exit_reason_distribution": latest.get("exit_reason_distribution"),
            "exit_reason_count": latest.get("exit_reason_count"),
            "profit_lock_profit_bank_events": latest.get("profit_lock_profit_bank_events"),
            "paper_pnl_reconciliation_status": latest.get("paper_pnl_reconciliation_status"),
            "closed_positions_count": max_closed,
            "trainer_feedback_alpha_fields_present": latest.get("trainer_feedback_alpha_fields_present"),
            "trainer_feedback_row_count": current_feedback,
            "trainer_feedback_rows_count": current_feedback,
            "trainer_feedback_total_row_count": current_total_feedback,
            "trainer_feedback_quarantined_row_count": current_quarantined_feedback,
            "trainer_feedback_complete_row_count": current_complete_feedback,
            "trainer_feedback_dirty_consumable_row_count": current_dirty_consumable_feedback,
            "trainer_feedback_readiness_status": latest.get("trainer_feedback_readiness_status"),
            "trainer_feedback_readiness_summary": latest.get("trainer_feedback_readiness_summary"),
            "trainer_feedback_missing_field_counts": latest.get("trainer_feedback_missing_field_counts"),
            "trainer_feedback_quarantined_example_rows": latest.get("trainer_feedback_quarantined_example_rows"),
            "forward_paper_intent_entry_context_fields_present": latest.get(
                "forward_paper_intent_entry_context_fields_present"
            ),
            "forward_paper_intent_entry_context_rows": latest_non_empty("forward_paper_intent_entry_context_rows"),
            "forward_paper_intent_rows": latest_non_empty("forward_paper_intent_rows"),
            "forward_paper_symbol_count": latest_non_empty("forward_paper_symbol_count"),
            "forward_paper_timeframe_count": latest_non_empty("forward_paper_timeframe_count"),
            "forward_paper_symbol_counts": latest_non_empty("forward_paper_symbol_counts"),
            "forward_paper_timeframe_counts": latest_non_empty("forward_paper_timeframe_counts"),
            "forward_paper_accepted_candidate_rows": latest_non_empty("forward_paper_accepted_candidate_rows"),
            "forward_paper_accepted_candidate_context_rows": latest_non_empty(
                "forward_paper_accepted_candidate_context_rows"
            ),
            "forward_paper_no_trade_context_rows": latest_non_empty("forward_paper_no_trade_context_rows"),
            "forward_paper_no_trade_reason_status": latest_forward_reason_status,
            "forward_paper_no_trade_root_cause_status": latest_non_empty(
                "forward_paper_no_trade_root_cause_status"
            ),
            "forward_paper_router_reason_code_counts": latest_forward_reason_status.get(
                "router_reason_code_counts"
            ),
            "forward_paper_selected_timeframe_cutoff_examples": latest_forward_reason_status.get(
                "selected_timeframe_cutoff_examples"
            ),
            "forward_paper_no_trade_example_rows": latest_forward_reason_status.get("no_trade_example_rows"),
            "forward_paper_future_cutoff_offender_examples": latest_forward_reason_status.get(
                "future_cutoff_offender_examples"
            ),
            "paper_ledger_static_sizing_status": latest.get("paper_ledger_static_sizing_status"),
            "paper_ledger_static_sizing_regression_status": latest.get(
                "paper_ledger_static_sizing_regression_status"
            ),
            "paper_ledger_accepted_rows": latest.get("paper_ledger_accepted_rows"),
            "paper_ledger_adaptive_accepted_rows": latest.get("paper_ledger_adaptive_accepted_rows"),
            "paper_ledger_legacy_static_accepted_rows": latest.get("paper_ledger_legacy_static_accepted_rows"),
            "paper_ledger_current_cycle_static_accepted_rows": latest.get(
                "paper_ledger_current_cycle_static_accepted_rows"
            ),
            "monthly_10k_goal_feasibility_status": latest.get("monthly_10k_goal_feasibility_status"),
        }
    )
    dashboard_alias_keys = (
        "paper_equity",
        "paper_equity_source",
        "realized_pnl_usd",
        "unrealized_pnl_usd",
        "accepted_allocation_count",
        "blocked_allocation_count",
        "paper_allocation_distribution",
        "position_source",
        "raw_redis_position_row_count",
        "canonical_redis_position_row_count",
        "portfolio_position_row_count",
        "canonical_portfolio_position_row_count",
        "open_positions",
        "open_positions_count",
        "exposure_by_symbol",
        "total_paper_exposure_usdt",
        "closed_positions_count",
        "outcome_label_count",
        "trainer_feedback_row_count",
        "trainer_feedback_rows_count",
        "trainer_feedback_total_row_count",
        "trainer_feedback_quarantined_row_count",
        "trainer_feedback_complete_row_count",
        "trainer_feedback_dirty_consumable_row_count",
        "trainer_feedback_readiness_status",
        "trainer_feedback_readiness_summary",
        "trainer_feedback_missing_field_counts",
        "trainer_feedback_quarantined_example_rows",
        "static_sizing_regression_status",
        "same_symbol_stack_status",
        "same_symbol_hedge_status",
        "live_balance_hold_status",
        "forward_paper_intent_rows",
        "forward_paper_symbol_count",
        "forward_paper_timeframe_count",
        "forward_paper_symbol_counts",
        "forward_paper_timeframe_counts",
        "forward_paper_accepted_candidate_rows",
        "forward_paper_accepted_candidate_context_rows",
        "forward_paper_no_trade_context_rows",
        "forward_paper_no_trade_reason_status",
        "forward_paper_no_trade_root_cause_status",
        "forward_paper_router_reason_code_counts",
        "forward_paper_selected_timeframe_cutoff_examples",
        "forward_paper_future_cutoff_offender_examples",
        "paper_ledger_static_sizing_regression_status",
        "paper_ledger_accepted_rows",
        "paper_ledger_adaptive_accepted_rows",
        "paper_ledger_legacy_static_accepted_rows",
        "paper_ledger_current_cycle_static_accepted_rows",
        "monthly_10k_goal_feasibility_status",
    )
    dashboard_aliases = {key: latest_metrics.get(key) for key in dashboard_alias_keys}
    no_trade_root_cause = latest_metrics.get("forward_paper_no_trade_root_cause_status")
    no_trade_root_cause = no_trade_root_cause if isinstance(no_trade_root_cause, dict) else {}
    primary_router_blocker = no_trade_root_cause.get("primary_router_blocker")
    primary_router_blocker = primary_router_blocker if isinstance(primary_router_blocker, dict) else {}
    primary_fill_gate_blocker = no_trade_root_cause.get("primary_fill_gate_blocker")
    primary_fill_gate_blocker = primary_fill_gate_blocker if isinstance(primary_fill_gate_blocker, dict) else {}
    primary_allocator_decision = no_trade_root_cause.get("primary_allocator_decision")
    primary_allocator_decision = (
        primary_allocator_decision if isinstance(primary_allocator_decision, dict) else {}
    )
    primary_router_reason_code = no_trade_root_cause.get("primary_router_reason_code")
    primary_router_reason_code = (
        primary_router_reason_code if isinstance(primary_router_reason_code, dict) else {}
    )
    dashboard_aliases.update(
        {
            "root_cause": no_trade_root_cause.get("natural_language_summary"),
            "forward_paper_no_trade_root_cause_summary": no_trade_root_cause.get(
                "natural_language_summary"
            ),
            "forward_paper_primary_router_blocker": primary_router_blocker.get("reason"),
            "forward_paper_primary_router_blocker_count": primary_router_blocker.get("count"),
            "forward_paper_primary_fill_gate_blocker": primary_fill_gate_blocker.get("reason"),
            "forward_paper_primary_fill_gate_blocker_count": primary_fill_gate_blocker.get("count"),
            "forward_paper_primary_allocator_decision": primary_allocator_decision.get("reason"),
            "forward_paper_primary_allocator_decision_count": primary_allocator_decision.get("count"),
            "forward_paper_primary_router_reason_code": primary_router_reason_code.get("reason"),
            "forward_paper_primary_router_reason_code_count": primary_router_reason_code.get("count"),
            "forward_paper_masa_future_cutoff_block_count": no_trade_root_cause.get(
                "masa_future_cutoff_block_count"
            ),
            "forward_paper_execution_success_probability_below_threshold_count": no_trade_root_cause.get(
                "execution_success_probability_below_threshold_count"
            ),
            "forward_paper_confidence_below_threshold_count": no_trade_root_cause.get(
                "confidence_below_threshold_count"
            ),
            "forward_paper_expected_move_after_cost_below_threshold_count": no_trade_root_cause.get(
                "expected_move_after_cost_below_threshold_count"
            ),
            "forward_paper_confidence_contributors": no_trade_root_cause.get(
                "confidence_contributors"
            ),
        }
    )
    status = dict(base_status)
    status.update(
        {
            "schema_version": "runtime_alpha_remediated_soak_status_v1",
            "gate": gate,
            "proof_status": proof_status,
            "completion_marker": completion_marker,
            "remediation_id": remediation_id,
            "soak_slug": SLUG,
            "observer_pid": os.getpid(),
            "soak_window_label": window_label,
            "soak_window_hours": round(required_seconds / 3600.0, 4),
            "soak_required_seconds": required_seconds,
            "completion_window_required_seconds": required_seconds,
            "latest_observation_age_seconds": base_status.get("last_observation_age_seconds"),
            "soak_complete": soak_complete,
            "soak_1h_complete": soak_complete if required_seconds == DEFAULT_REQUIRED_SECONDS else False,
            "soak_12h_complete": soak_complete if required_seconds == base_soak.DEFAULT_SOAK_REQUIRED_SECONDS else False,
            "soak_24h_complete": soak_24h_complete,
            "success_criteria": criteria,
            "dangerous_blockers": high_severity_alerts,
            "high_severity_alerts": high_severity_alerts,
            "latest_metrics": latest_metrics,
            "operator_dashboard_flattened_metrics_version": "runtime_alpha_soak_top_level_v1",
            **dashboard_aliases,
            "safety": {
                **dict(base_status.get("safety") or {}),
                "paper_only": True,
                "writes_redis": False,
                "writes_old_redis": False,
                "real_orders_submitted": False,
                "test_order_attempted": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
                "exchange_action_taken": False,
            },
        }
    )
    return status


def build_report(status: dict[str, Any]) -> str:
    latest = status.get("latest_metrics", {})
    criteria = status.get("success_criteria", {})
    alerts = status.get("high_severity_alerts") or []
    window_label = str(status.get("soak_window_label") or _window_label(DEFAULT_REQUIRED_SECONDS))
    no_trade_reasons = latest.get("forward_paper_no_trade_reason_status")
    no_trade_reasons = no_trade_reasons if isinstance(no_trade_reasons, dict) else {}
    no_trade_root_cause = latest.get("forward_paper_no_trade_root_cause_status")
    no_trade_root_cause = no_trade_root_cause if isinstance(no_trade_root_cause, dict) else {}
    cutoff_examples = no_trade_root_cause.get("selected_timeframe_cutoff_examples")
    cutoff_examples = cutoff_examples if isinstance(cutoff_examples, list) else []
    no_trade_examples = latest.get("forward_paper_no_trade_example_rows")
    no_trade_examples = no_trade_examples if isinstance(no_trade_examples, list) else []

    def format_reason_counts(title: str, key: str) -> list[str]:
        rows = no_trade_reasons.get(key)
        if not isinstance(rows, list) or not rows:
            return [f"- {title}: `none`"]
        top = rows[:5]
        return [f"- {title}: " + ", ".join(f"`{row.get('reason')}`={row.get('count')}" for row in top)]

    lines = [
        f"# V2 Runtime Alpha Remediated Adaptive Lifecycle {window_label} Paper Soak Report",
        "",
        f"Generated: `{status.get('generated_utc')}`",
        f"Remediation id: `{status.get('remediation_id')}`",
        "",
        "Gate:",
        "",
        "```text",
        str(status.get("gate")),
        "```",
        "",
        f"Proof status: `{status.get('proof_status')}`",
        f"Completion marker: `{status.get('completion_marker')}`",
        f"Soak window: `{status.get('soak_window_label')}`",
        f"Required seconds: `{status.get('soak_required_seconds')}`",
        f"Observed hours: `{status.get('elapsed_hours_observed')}`",
        f"Completion-window elapsed seconds: `{status.get('completion_window_elapsed_seconds')}`",
        f"Observation density status: `{status.get('observation_density_status')}`",
        f"Last observation freshness status: `{status.get('last_observation_freshness_status')}`",
        f"{window_label} complete: `{status.get('soak_complete')}`",
        f"1h complete: `{status.get('soak_1h_complete')}`",
        f"12h legacy alias complete: `{status.get('soak_12h_complete')}`",
        f"24h legacy alias complete: `{status.get('soak_24h_complete')}`",
        "",
        "Alpha-chain monitored metrics:",
        "",
        f"- Liquidity consumer hits: `{latest.get('liquidity_consumer_hits')}`",
        f"- Liquidity decision consumer status: `{latest.get('liquidity_decision_consumer_status')}`",
        f"- Liquidation zone tensor field presence: `{latest.get('liquidation_zone_tensor_field_presence')}`",
        f"- Risk liquidation proximity influence: `{latest.get('risk_liquidation_proximity_influence')}`",
        f"- Orchestrator liquidation proximity influence: `{latest.get('orchestrator_liquidation_proximity_influence')}`",
        f"- Strategy weight update status: `{latest.get('strategy_weight_update_status')}`",
        f"- Hedge status: `{latest.get('hedge_status')}`",
        f"- Hedge cost/benefit tracked: `{latest.get('hedge_cost_benefit_tracked')}`",
        f"- Exit reason count: `{latest.get('exit_reason_count')}`",
        f"- Paper PnL reconciliation status: `{latest.get('paper_pnl_reconciliation_status')}`",
        f"- Closed positions: `{latest.get('closed_positions_count')}`",
        f"- Trainer feedback alpha fields present: `{latest.get('trainer_feedback_alpha_fields_present')}`",
        f"- Trainer feedback rows: `{latest.get('trainer_feedback_rows_count')}`",
        f"- Trainer feedback complete rows: `{latest.get('trainer_feedback_complete_row_count')}`",
        f"- Trainer feedback dirty consumable rows: `{latest.get('trainer_feedback_dirty_consumable_row_count')}`",
        f"- Trainer feedback readiness status: `{latest.get('trainer_feedback_readiness_status')}`",
        f"- Trainer feedback readiness summary: `{latest.get('trainer_feedback_readiness_summary')}`",
        f"- Forward paper intent entry context fields present: `{latest.get('forward_paper_intent_entry_context_fields_present')}`",
        f"- Forward paper intent entry context rows: `{latest.get('forward_paper_intent_entry_context_rows')}` / `{latest.get('forward_paper_intent_rows')}`",
        f"- Forward paper symbol coverage: `{latest.get('forward_paper_symbol_count')}` symbols",
        f"- Forward paper timeframe coverage: `{latest.get('forward_paper_timeframe_count')}` timeframes",
        f"- Forward accepted candidate context rows: `{latest.get('forward_paper_accepted_candidate_context_rows')}` / `{latest.get('forward_paper_accepted_candidate_rows')}`",
        f"- Forward no-trade context rows: `{latest.get('forward_paper_no_trade_context_rows')}`",
        f"- Paper ledger static sizing status: `{latest.get('paper_ledger_static_sizing_regression_status')}`",
        f"- Paper ledger accepted rows: `{latest.get('paper_ledger_accepted_rows')}`",
        f"- Paper ledger adaptive accepted rows: `{latest.get('paper_ledger_adaptive_accepted_rows')}`",
        f"- Paper ledger legacy static accepted rows: `{latest.get('paper_ledger_legacy_static_accepted_rows')}`",
        f"- Paper ledger current-cycle static accepted rows: `{latest.get('paper_ledger_current_cycle_static_accepted_rows')}`",
        f"- 10k feasibility status: `{latest.get('monthly_10k_goal_feasibility_status')}`",
        "",
        "Current no-trade root cause:",
        "",
        f"- Summary: `{no_trade_root_cause.get('natural_language_summary') or 'none'}`",
        f"- Primary router blocker: `{(no_trade_root_cause.get('primary_router_blocker') or {}).get('reason')}`",
        f"- Primary router reason code: `{(no_trade_root_cause.get('primary_router_reason_code') or {}).get('reason')}`",
        f"- Primary fill gate blocker: `{(no_trade_root_cause.get('primary_fill_gate_blocker') or {}).get('reason')}`",
        f"- Primary allocator decision: `{(no_trade_root_cause.get('primary_allocator_decision') or {}).get('reason')}`",
        f"- Redis keys used: `{', '.join(no_trade_root_cause.get('redis_keys_used') or [])}`",
        "",
        "Current paper no-trade reason counts:",
        "",
    ]
    lines.extend(format_reason_counts("Strategy ids", "strategy_id_counts"))
    lines.extend(format_reason_counts("Market regimes", "market_regime_counts"))
    lines.extend(format_reason_counts("Paper fill blockers", "paper_fill_block_reason_counts"))
    lines.extend(format_reason_counts("Allocator decisions", "allocator_decision_counts"))
    lines.extend(format_reason_counts("Allocator reasons", "allocator_reason_counts"))
    lines.extend(format_reason_counts("Local blockers", "local_block_reason_counts"))
    lines.extend(format_reason_counts("Paper fill gate blockers", "paper_fill_gate_block_reason_counts"))
    lines.extend(format_reason_counts("Router reason codes", "router_reason_code_counts"))
    lines.extend(["", "Selected timeframe cutoff examples:", ""])
    if not cutoff_examples:
        lines.append("- `none`")
    for row in cutoff_examples[:5]:
        if not isinstance(row, dict):
            continue
        lines.append(
            "- "
            f"`{row.get('symbol')}` `{row.get('prediction_timeframe')}` "
            f"slot=`{row.get('selected_timeframe_slot')}` "
            f"tf=`{row.get('selected_timeframe')}` "
            f"cutoff=`{row.get('feature_cutoff')}` "
            f"generated=`{row.get('generated_utc')}`"
        )
    lines.extend(["", "Current no-trade examples:", ""])
    if not no_trade_examples:
        lines.append("- `none`")
    for row in no_trade_examples[:5]:
        if not isinstance(row, dict):
            continue
        lower = row.get("lower_timeframe") if isinstance(row.get("lower_timeframe"), dict) else {}
        mid = row.get("mid_timeframe") if isinstance(row.get("mid_timeframe"), dict) else {}
        higher = row.get("higher_timeframe") if isinstance(row.get("higher_timeframe"), dict) else {}
        lines.append(
            "- "
            f"`{row.get('symbol')}` `{row.get('timeframe')}` "
            f"block=`{row.get('router_block_reason') or row.get('paper_fill_block_reason')}` "
            f"exec_prob=`{row.get('execution_success_probability')}` "
            f"expected_move_bps=`{row.get('expected_move_bps')}` "
            f"ppo_conf=`{row.get('ppo_confidence')}` "
            f"masa_conf=`{row.get('masa_confidence')}` "
            f"cutoffs=`{lower.get('feature_cutoff')},{mid.get('feature_cutoff')},{higher.get('feature_cutoff')}`"
        )
    lines.extend(
        [
            "",
        "High-severity alerts:",
        "",
        ]
    )
    lines.extend(f"- `{alert}`" for alert in alerts)
    if not alerts:
        lines.append("- `none`")
    lines.extend(["", "Success criteria:", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in criteria.items())
    lines.extend(
        [
            "",
            "Safety boundary:",
            "",
            "- This monitor does not write Redis.",
            "- This monitor does not place real orders or call test-order.",
            "- This monitor does not change leverage or margin mode.",
            "- Live remains unchanged and balance-held.",
            "",
            "Interpretation:",
            "",
            f"READY means the remediated paper-only observer is wired and safe to run. It does not claim {window_label} proof until `soak_complete` is true.",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_payloads(status: dict[str, Any], observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = status.get("latest_metrics", {})
    base = {
        "generated_utc": status.get("generated_utc"),
        "gate": status.get("gate"),
        "proof_status": status.get("proof_status"),
        "completion_marker": status.get("completion_marker"),
        "remediation_id": status.get("remediation_id"),
        "soak_window_label": status.get("soak_window_label"),
        "soak_window_hours": status.get("soak_window_hours"),
        "soak_required_seconds": status.get("soak_required_seconds"),
        "soak_complete": status.get("soak_complete"),
        "soak_1h_complete": status.get("soak_1h_complete"),
        "soak_12h_complete": status.get("soak_12h_complete"),
        "soak_24h_complete": status.get("soak_24h_complete"),
        "completion_window_elapsed_seconds": status.get("completion_window_elapsed_seconds"),
        "observation_density_status": status.get("observation_density_status"),
        "last_observation_freshness_status": status.get("last_observation_freshness_status"),
        "high_severity_alerts": status.get("high_severity_alerts"),
        "observer_pid": status.get("observer_pid"),
    }
    return {
        "liquidity_consumer_24h_status.json": {
            **base,
            "liquidity_consumer_hits": latest.get("liquidity_consumer_hits"),
            "liquidity_decision_consumer_status": latest.get("liquidity_decision_consumer_status"),
            "liquidation_zone_tensor_field_presence": latest.get("liquidation_zone_tensor_field_presence"),
            "risk_liquidation_proximity_influence": latest.get("risk_liquidation_proximity_influence"),
            "orchestrator_liquidation_proximity_influence": latest.get("orchestrator_liquidation_proximity_influence"),
        },
        "strategy_weight_24h_status.json": {
            **base,
            "strategy_weight_update_status": latest.get("strategy_weight_update_status"),
            "strategy_weights_by_family": latest.get("strategy_weights_by_family"),
        },
        "hedge_cost_benefit_24h_status.json": {
            **base,
            "hedge_status": latest.get("hedge_status"),
            "hedge_intents": latest.get("hedge_intents"),
            "hedge_approvals": latest.get("hedge_approvals"),
            "hedge_blocks": latest.get("hedge_blocks"),
            "hedge_cost_benefit_tracked": latest.get("hedge_cost_benefit_tracked"),
            "hedge_cost_benefit": observation.get("hedge_cost_benefit"),
        },
        "exit_reason_24h_status.json": {
            **base,
            "exit_reason_distribution": latest.get("exit_reason_distribution"),
            "exit_reason_count": latest.get("exit_reason_count"),
            "profit_lock_profit_bank_events": latest.get("profit_lock_profit_bank_events"),
        },
        "paper_pnl_reconciliation_24h_status.json": {
            **base,
            "paper_pnl_reconciliation_status": latest.get("paper_pnl_reconciliation_status"),
            "paper_pnl_reconciliation": observation.get("paper_pnl_reconciliation"),
        },
        "trainer_feedback_alpha_24h_status.json": {
            **base,
            "trainer_feedback_alpha_fields_present": latest.get("trainer_feedback_alpha_fields_present"),
            "trainer_feedback_row_count": latest.get("trainer_feedback_row_count"),
            "trainer_feedback_rows_count": latest.get("trainer_feedback_rows_count"),
            "trainer_feedback_total_row_count": latest.get("trainer_feedback_total_row_count"),
            "trainer_feedback_quarantined_row_count": latest.get("trainer_feedback_quarantined_row_count"),
            "trainer_feedback_complete_row_count": latest.get("trainer_feedback_complete_row_count"),
            "trainer_feedback_dirty_consumable_row_count": latest.get("trainer_feedback_dirty_consumable_row_count"),
            "trainer_feedback_readiness_status": latest.get("trainer_feedback_readiness_status"),
            "trainer_feedback_readiness_summary": latest.get("trainer_feedback_readiness_summary"),
            "trainer_feedback_missing_field_counts": latest.get("trainer_feedback_missing_field_counts"),
            "trainer_feedback_quarantined_example_rows": latest.get("trainer_feedback_quarantined_example_rows"),
            "trainer_feedback_alpha_status": observation.get("trainer_feedback_alpha_status"),
            "forward_paper_intent_entry_context_status": observation.get(
                "forward_paper_intent_entry_context_status"
            ),
            "forward_paper_intent_entry_context_fields_present": latest.get(
                "forward_paper_intent_entry_context_fields_present"
            ),
            "forward_paper_intent_entry_context_rows": latest.get("forward_paper_intent_entry_context_rows"),
            "forward_paper_intent_rows": latest.get("forward_paper_intent_rows"),
            "forward_paper_symbol_count": latest.get("forward_paper_symbol_count"),
            "forward_paper_timeframe_count": latest.get("forward_paper_timeframe_count"),
            "forward_paper_symbol_counts": latest.get("forward_paper_symbol_counts"),
            "forward_paper_timeframe_counts": latest.get("forward_paper_timeframe_counts"),
            "forward_paper_accepted_candidate_rows": latest.get("forward_paper_accepted_candidate_rows"),
            "forward_paper_accepted_candidate_context_rows": latest.get(
                "forward_paper_accepted_candidate_context_rows"
            ),
            "forward_paper_no_trade_context_rows": latest.get("forward_paper_no_trade_context_rows"),
            "forward_paper_no_trade_reason_status": latest.get("forward_paper_no_trade_reason_status"),
            "forward_paper_no_trade_root_cause_status": latest.get(
                "forward_paper_no_trade_root_cause_status"
            ),
            "forward_paper_router_reason_code_counts": latest.get("forward_paper_router_reason_code_counts"),
            "forward_paper_selected_timeframe_cutoff_examples": latest.get(
                "forward_paper_selected_timeframe_cutoff_examples"
            ),
            "forward_paper_no_trade_example_rows": latest.get("forward_paper_no_trade_example_rows"),
            "forward_paper_future_cutoff_offender_examples": latest.get(
                "forward_paper_future_cutoff_offender_examples"
            ),
        },
        "paper_ledger_static_sizing_24h_status.json": {
            **base,
            "paper_ledger_static_sizing_regression_status": latest.get(
                "paper_ledger_static_sizing_regression_status"
            ),
            "paper_ledger_accepted_rows": latest.get("paper_ledger_accepted_rows"),
            "paper_ledger_adaptive_accepted_rows": latest.get("paper_ledger_adaptive_accepted_rows"),
            "paper_ledger_legacy_static_accepted_rows": latest.get("paper_ledger_legacy_static_accepted_rows"),
            "paper_ledger_current_cycle_static_accepted_rows": latest.get(
                "paper_ledger_current_cycle_static_accepted_rows"
            ),
            "paper_ledger_static_sizing_status": observation.get("paper_ledger_static_sizing_status"),
        },
        "monthly_10k_goal_feasibility_after_24h_soak.json": {
            **base,
            "monthly_10k_goal_feasibility_status": latest.get("monthly_10k_goal_feasibility_status"),
            "monthly_10k_goal_feasibility": observation.get("monthly_10k_goal_feasibility"),
        },
    }


def _mirror_artifacts(root: Path, status: dict[str, Any], observation: dict[str, Any]) -> None:
    runtime_dir = _runtime_dir(root)
    public_dir = _public_dir(root)
    window_suffix = _gate_suffix(int(status.get("soak_required_seconds") or DEFAULT_REQUIRED_SECONDS))
    for base in (runtime_dir, public_dir):
        _write_json(base / "runtime_alpha_remediated_soak_status.json", status)
        _write_json(base / "runtime_alpha_remediated_soak_observation_latest.json", observation)
        _write_json(base / "operator_dashboard_payload.json", status)
        _write_text(base / "observer.pid", str(status.get("observer_pid") or os.getpid()))
        for filename, payload in _artifact_payloads(status, observation).items():
            _write_json(base / filename, payload)
        _write_json(base / "runtime_alpha_remediated_1h_soak_status.json", status)
    _write_text(public_dir / "GO_NO_GO.md", str(status.get("completion_marker") or status["gate"]) + "\n")
    _write_text(public_dir / "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_24H_PAPER_SOAK_REPORT.md", build_report(status))
    _write_text(public_dir / "V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_12H_PAPER_SOAK_REPORT.md", build_report(status))
    _write_text(
        public_dir / f"V2_RUNTIME_ALPHA_REMEDIATED_ADAPTIVE_LIFECYCLE_{window_suffix}_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    legacy_alias_payload = {
        **status,
        "legacy_alias_superseded": True,
        "superseded_slug": OLD_SLUG,
        "superseded_by_slug": SLUG,
        "active_status_source": f"{SLUG}/latest/operator_dashboard_payload.json",
        "previous_24h_result_invalidated_by_remediation": True,
    }
    for old_dir in _old_dirs(root):
        _write_json(old_dir / "soak_status.json", legacy_alias_payload)
        _write_json(old_dir / "operator_dashboard_payload.json", legacy_alias_payload)
        _write_json(old_dir / "soak_24h_final_operator_dashboard_payload.json", legacy_alias_payload)


def run_once(
    *,
    root: Path = REPO_ROOT,
    redis_client: Any | None = None,
    append_observation: bool = True,
    now: datetime | None = None,
    interval_seconds: int = 300,
    required_seconds: int = DEFAULT_REQUIRED_SECONDS,
    remediation_id: str = DEFAULT_REMEDIATION_ID,
    archive_previous: bool = False,
    stopped_observer_status: str = "NO_PREVIOUS_OBSERVER_PROCESS_FOUND",
) -> dict[str, Any]:
    if archive_previous:
        archive_previous_soak(
            root=root,
            remediation_id=remediation_id,
            stopped_observer_status=stopped_observer_status,
        )
    effective_redis_client = redis_client if redis_client is not None else base_soak._connect_redis()
    observation = collect_alpha_observation(
        root=root,
        redis_client=effective_redis_client,
        now=now,
        remediation_id=remediation_id,
    )
    runtime_dir = _runtime_dir(root)
    public_dir = _public_dir(root)
    if append_observation:
        _append_jsonl(runtime_dir / OBSERVATION_JSONL, observation)
        _append_jsonl(public_dir / OBSERVATION_JSONL, observation)
    observations = [
        row
        for row in _read_jsonl(runtime_dir / OBSERVATION_JSONL)
        if base_soak._is_current_position_schema_observation(row)
        and row.get("remediation_id") == remediation_id
    ]
    if not observations:
        observations = [observation]
    status = build_alpha_soak_status(
        observations,
        generated_utc=observation["observed_utc"],
        interval_seconds=interval_seconds,
        required_seconds=required_seconds,
        remediation_id=remediation_id,
    )
    _mirror_artifacts(root, status, observation)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak")
    parser.add_argument("--once", action="store_true", help="collect one remediated observation and emit latest status")
    parser.add_argument("--loop", action="store_true", help="run until duration-hours elapses")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--duration-hours", type=float, default=DEFAULT_SOAK_WINDOW_HOURS)
    parser.add_argument("--required-hours", type=float, default=DEFAULT_SOAK_WINDOW_HOURS)
    parser.add_argument("--remediation-id", default=DEFAULT_REMEDIATION_ID)
    parser.add_argument("--archive-previous", action="store_true")
    parser.add_argument("--stopped-observer-status", default="NO_PREVIOUS_OBSERVER_PROCESS_FOUND")
    args = parser.parse_args(argv)
    required_seconds = max(1, int(float(args.required_hours) * 3600.0))

    if args.loop:
        started = time.monotonic()
        duration_seconds = max(0.0, float(args.duration_hours) * 3600.0)
        first = True
        while True:
            status = run_once(
                interval_seconds=args.interval_seconds,
                remediation_id=args.remediation_id,
                required_seconds=required_seconds,
                archive_previous=bool(args.archive_previous and first),
                stopped_observer_status=args.stopped_observer_status,
            )
            first = False
            print(
                json.dumps(
                    {
                        "gate": status["gate"],
                        "proof_status": status["proof_status"],
                        "completion_marker": status.get("completion_marker"),
                        "remediation_id": status.get("remediation_id"),
                        "density_window_elapsed_seconds": status.get("density_window_elapsed_seconds"),
                        "observation_density_status": status.get("observation_density_status"),
                        "last_observation_freshness_status": status.get("last_observation_freshness_status"),
                        "soak_window_label": status.get("soak_window_label"),
                        "soak_1h_complete": status.get("soak_1h_complete"),
                        "soak_12h_complete": status["soak_12h_complete"],
                        "soak_24h_complete": status["soak_24h_complete"],
                        "high_severity_alerts": status.get("high_severity_alerts", []),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if time.monotonic() - started >= duration_seconds:
                return 0
            time.sleep(max(30, int(args.interval_seconds)))

    status = run_once(
        interval_seconds=args.interval_seconds,
        required_seconds=required_seconds,
        remediation_id=args.remediation_id,
        archive_previous=args.archive_previous,
        stopped_observer_status=args.stopped_observer_status,
    )
    print(
        json.dumps(
            {
                "gate": status["gate"],
                "proof_status": status["proof_status"],
                "completion_marker": status.get("completion_marker"),
                "remediation_id": status.get("remediation_id"),
                "density_window_elapsed_seconds": status.get("density_window_elapsed_seconds"),
                "observation_density_status": status.get("observation_density_status"),
                "last_observation_freshness_status": status.get("last_observation_freshness_status"),
                "soak_window_label": status.get("soak_window_label"),
                "soak_1h_complete": status.get("soak_1h_complete"),
                "soak_12h_complete": status.get("soak_12h_complete"),
                "high_severity_alerts": status.get("high_severity_alerts", []),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
