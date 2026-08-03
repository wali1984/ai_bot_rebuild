"""Legacy execution-packet diagnostic with no runtime or order authority."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.a_plus_trade_gate.service import A_PLUS_GATE_STATUS_REDIS_KEY

GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
PAPER_INTENTS_REDIS_KEY = "v2:paper:intents"
EVIDENCE_SCOPE = "LEGACY_NON_CANONICAL_DIAGNOSTIC"
DIAGNOSTIC_PACKET_COMPLETE = (
    "DIAGNOSTIC_PACKET_COMPLETE_CANONICAL_RUNTIME_CONTRACT_NOT_CONSUMED"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _non_runtime_evidence_boundary(generated_utc: str) -> dict[str, Any]:
    return {
        "evidence_scope": EVIDENCE_SCOPE,
        "contract_test_only": False,
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
            "CANONICAL_IDENTITY_BOUND_CURRENT_CYCLE_RUNTIME_CONTRACT_NOT_CONSUMED"
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _nested_first(row: Mapping[str, Any], *fields: str) -> Any:
    allocation = _as_mapping(row.get("adaptive_allocation"))
    model_inputs = _as_mapping(allocation.get("model_inputs"))
    for field in fields:
        value = _first_present(row.get(field), allocation.get(field), model_inputs.get(field))
        if value not in (None, ""):
            return value
    return None


def _runtime_a_plus_rows(runtime_status: Any) -> list[Mapping[str, Any]]:
    if not isinstance(runtime_status, Mapping):
        return []
    rows = runtime_status.get("candidate_matrix")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping) and row.get("a_plus") is True]


def _intent_matches_status_row(intent: Mapping[str, Any], status_row: Mapping[str, Any]) -> bool:
    def norm(value: Any) -> str:
        return str(value or "").strip().lower()

    intent_gate = _as_mapping(intent.get("a_plus_gate"))
    return (
        intent_gate.get("a_plus") is True
        and norm(intent.get("symbol")) == norm(status_row.get("symbol"))
        and norm(intent.get("timeframe")) == norm(status_row.get("timeframe"))
        and norm(_first_present(intent.get("side"), intent.get("action"))) == norm(status_row.get("side"))
        and norm(_first_present(intent.get("strategy_selected_mode"), intent.get("strategy_id")))
        == norm(status_row.get("strategy_id"))
    )


def _matching_full_candidate(
    *,
    status_row: Mapping[str, Any],
    intents_payload: Any,
) -> tuple[Mapping[str, Any], str]:
    if isinstance(intents_payload, list):
        for intent in intents_payload:
            if isinstance(intent, Mapping) and _intent_matches_status_row(intent, status_row):
                return intent, PAPER_INTENTS_REDIS_KEY
    return status_row, A_PLUS_GATE_STATUS_REDIS_KEY


def _extract_candidate_fields(candidate: Mapping[str, Any]) -> dict[str, Any]:
    qty = _positive(_nested_first(candidate, "quantity", "qty", "target_quantity"))
    notional = _positive(
        _nested_first(
            candidate,
            "notional",
            "notional_usd",
            "target_notional_usdt",
            "target_notional_usd",
            "gross_notional_usd",
        )
    )
    margin = _positive(_nested_first(candidate, "margin", "allocated_margin_usd", "selected_allocated_margin_usd"))
    leverage = _positive(_nested_first(candidate, "recommended_leverage", "effective_leverage", "leverage"))
    liquidation_buffer_bps = _positive(_nested_first(candidate, "liquidation_buffer_bps"))
    max_loss = _positive(
        _nested_first(candidate, "max_loss", "max_loss_if_stop_hit", "max_loss_budget_usd", "risk_budget_usd")
    )
    recommended_margin_mode = _first_present(
        _nested_first(candidate, "recommended_margin_mode", "margin_mode", "selected_margin_mode")
    )
    side = str(_first_present(candidate.get("side"), candidate.get("action")) or "").lower() or None
    symbol = str(candidate.get("symbol") or "").upper() or None
    stop_distance_bps = _positive(_nested_first(candidate, "stop_distance_bps", "stop_loss_bps", "atr_stop_bps"))
    take_profit_bps = _positive(_nested_first(candidate, "take_profit_bps", "profit_target_bps"))
    stop_plan = {
        "status": (
            "DIAGNOSTIC_FIELDS_COMPLETE"
            if stop_distance_bps is not None
            else "MISSING_STOP_DISTANCE"
        ),
        "stop_distance_bps": stop_distance_bps,
        "stop_loss_bps": _positive(_nested_first(candidate, "stop_loss_bps")),
        "stop_price": _positive(_nested_first(candidate, "stop_price", "stop_loss_price")),
        "trailing_stop_bps": _positive(_nested_first(candidate, "trailing_stop_bps")),
        "source": "runtime_candidate",
    }
    take_profit_reduce_plan = {
        "status": (
            "DIAGNOSTIC_FIELDS_COMPLETE"
            if take_profit_bps is not None
            or _positive(_nested_first(candidate, "take_profit_price")) is not None
            else "MISSING_TAKE_PROFIT"
        ),
        "take_profit_bps": take_profit_bps,
        "take_profit_price": _positive(_nested_first(candidate, "take_profit_price", "take_profit_reference")),
        "take_profit_structure": _first_present(_nested_first(candidate, "take_profit_structure")),
        "reduce_plan": "reduce_or_close_only_after_trigger",
        "source": "runtime_candidate",
    }
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "notional": notional,
        "margin": margin,
        "recommended_leverage": leverage,
        "recommended_margin_mode": recommended_margin_mode,
        "liquidation_buffer": {
            "liquidation_buffer_bps": liquidation_buffer_bps,
            "liquidation_price_estimate": _positive(_nested_first(candidate, "liquidation_price_estimate")),
        },
        "max_loss": max_loss,
        "stop_plan": stop_plan,
        "take_profit_reduce_plan": take_profit_reduce_plan,
    }


def _missing_required_fields(fields: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for name in (
        "symbol",
        "side",
        "qty",
        "notional",
        "margin",
        "recommended_leverage",
        "recommended_margin_mode",
        "max_loss",
    ):
        if fields.get(name) in (None, ""):
            missing.append(name)
    if _as_mapping(fields.get("liquidation_buffer")).get("liquidation_buffer_bps") is None:
        missing.append("liquidation_buffer.liquidation_buffer_bps")
    if _as_mapping(fields.get("stop_plan")).get("status") != "DIAGNOSTIC_FIELDS_COMPLETE":
        missing.append("stop_plan")
    if (
        _as_mapping(fields.get("take_profit_reduce_plan")).get("status")
        != "DIAGNOSTIC_FIELDS_COMPLETE"
    ):
        missing.append("take_profit_reduce_plan")
    return missing


def _base_packet(now: str) -> dict[str, Any]:
    return {
        "schema_version": "legacy_execution_packet_diagnostic_v3",
        "goal_id": GOAL_ID,
        "generated_utc": now,
        **_non_runtime_evidence_boundary(now),
        "live_gate": "blocked_human_only",
        "operator_flip_required": True,
        "operator_flip_sufficient": False,
        "selected_A_plus_candidate": None,
        "selected_A_plus_candidate_source": None,
        "symbol": None,
        "side": None,
        "qty": None,
        "notional": None,
        "margin": None,
        "recommended_leverage": None,
        "recommended_margin_mode": None,
        "liquidation_buffer": None,
        "max_loss": None,
        "stop_plan": None,
        "take_profit_reduce_plan": None,
        "kill_switch": {
            "required": True,
            "checked_before_submit": True,
            "active_blocks_submit": True,
            "missing_or_unhealthy_blocks_submit": True,
            "source_keys": ["v2:live_canary:kill_switch", "runtime_execution_state.kill_switch"],
        },
        "reduce_only_recovery_plan": {
            "required": True,
            "allowed_actions": ["reduce", "close", "emergency_de_risk"],
            "new_exposure_allowed": False,
            "orders_must_be_reduce_only": True,
        },
        "why_allowed": [],
        "diagnostic_observations": [],
        "why_not_authorized": [
            "canonical identity-bound current-cycle runtime contract is not consumed",
            "legacy A+ status and paper intents are diagnostic inputs only",
            "live_gate is blocked_human_only",
            "operator flip alone is insufficient to authorize execution",
            "agents may not submit real or test orders",
            "agents may not mutate exchange leverage or margin mode",
        ],
        "order_submitted": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "routes_to_live": False,
        "paper_only": True,
    }


def build_phase9_one_flip_readiness_packet(
    *,
    redis_client: Any = None,
    phase8_candidate_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    runtime_status = _read_json(redis_client, A_PLUS_GATE_STATUS_REDIS_KEY)
    intents_payload = _read_json(redis_client, PAPER_INTENTS_REDIS_KEY)
    packet = _base_packet(now)
    packet["runtime_a_plus_gate_status"] = {
        "source_key": A_PLUS_GATE_STATUS_REDIS_KEY,
        "available": isinstance(runtime_status, Mapping),
        "source_contract_authoritative": False,
        "canonical_current_cycle_contract_consumed": False,
        "generated_utc": runtime_status.get("generated_utc") if isinstance(runtime_status, Mapping) else None,
        "evaluated_candidates": runtime_status.get("evaluated_candidates") if isinstance(runtime_status, Mapping) else None,
        "a_plus_candidates": runtime_status.get("a_plus_candidates") if isinstance(runtime_status, Mapping) else None,
        "fail_closed": runtime_status.get("fail_closed") if isinstance(runtime_status, Mapping) else None,
    }
    synthetic_count = 0
    if isinstance(phase8_candidate_matrix, Mapping):
        accepted = phase8_candidate_matrix.get("accepted_candidates")
        synthetic_count = len(accepted) if isinstance(accepted, list) else 0
    packet["phase8_synthetic_candidate_reference"] = {
        "available": isinstance(phase8_candidate_matrix, Mapping),
        "evidence_scope": (
            phase8_candidate_matrix.get("evidence_scope")
            if isinstance(phase8_candidate_matrix, Mapping)
            else None
        ),
        "contract_test_only": True,
        "accepted_candidate_count": synthetic_count,
        "used_as_real_live_candidate": False,
    }

    runtime_rows = _runtime_a_plus_rows(runtime_status)
    if not isinstance(runtime_status, Mapping):
        packet["status"] = "BLOCKED_A_PLUS_RUNTIME_STATUS_UNAVAILABLE"
        packet["why_no_candidate"] = "runtime A+ gate status is unavailable"
        packet["missing_required_fields"] = ["runtime_a_plus_gate_status"]
    elif not runtime_rows:
        packet["status"] = "BLOCKED_NO_CURRENT_REAL_A_PLUS_CANDIDATE"
        packet["why_no_candidate"] = "runtime A+ gate has zero real A+ candidates"
        packet["missing_required_fields"] = ["selected_A_plus_candidate"]
    else:
        status_row = runtime_rows[0]
        candidate, source = _matching_full_candidate(status_row=status_row, intents_payload=intents_payload)
        fields = _extract_candidate_fields(candidate)
        missing = _missing_required_fields(fields)
        packet.update(fields)
        packet["selected_A_plus_candidate"] = {
            "symbol": fields["symbol"] or status_row.get("symbol"),
            "timeframe": candidate.get("timeframe") or status_row.get("timeframe"),
            "side": fields["side"] or status_row.get("side"),
            "strategy_id": _first_present(
                candidate.get("strategy_id"),
                candidate.get("strategy_selected_mode"),
                status_row.get("strategy_id"),
            ),
            "bucket_key": status_row.get("bucket_key"),
            "legacy_gate_a_plus_observation": True,
            "canonical_a_plus_authorized": False,
            "eligible_as_runtime_candidate": False,
            "failed_checks": list(status_row.get("failed_checks") or []),
            "missing_evidence_checks": list(status_row.get("missing_evidence_checks") or []),
            "passed_check_count": status_row.get("passed_check_count"),
            "check_count": status_row.get("check_count"),
        }
        packet["selected_A_plus_candidate_source"] = source
        packet["missing_required_fields"] = missing
        if missing:
            packet["status"] = "BLOCKED_A_PLUS_CANDIDATE_MISSING_EXECUTION_SIZING_OR_EXIT_PLAN"
            packet["why_no_candidate"] = None
        else:
            packet["status"] = DIAGNOSTIC_PACKET_COMPLETE
            packet["diagnostic_observations"] = [
                "legacy runtime candidate reports all A+ gate checks passed",
                "diagnostic execution sizing fields are present",
                "diagnostic stop and take-profit/reduce plans are present",
            ]
            packet["why_no_candidate"] = None

    packet["diagnostic_conditions"] = {
        "legacy_runtime_a_plus_candidate_observed": bool(runtime_rows),
        "selected_candidate_matches_legacy_runtime_a_plus_observation": packet[
            "selected_A_plus_candidate_source"
        ]
        in {A_PLUS_GATE_STATUS_REDIS_KEY, PAPER_INTENTS_REDIS_KEY},
        "phase8_synthetic_not_used_as_live_candidate": packet["phase8_synthetic_candidate_reference"][
            "used_as_real_live_candidate"
        ]
        is False,
        "execution_and_exit_fields_complete": not packet.get("missing_required_fields"),
        "operator_flip_required": packet["operator_flip_required"] is True,
        "operator_flip_sufficient_false": packet["operator_flip_sufficient"] is False,
        "canonical_current_cycle_contract_consumed_false": packet[
            "canonical_current_cycle_contract_consumed"
        ]
        is False,
        "canonical_runtime_ready_false": packet["canonical_runtime_ready"] is False,
        "serving_authorized_false": packet["serving_authorized"] is False,
        "a_plus_authorized_false": packet["a_plus_authorized"] is False,
        "paper_authorized_false": packet["paper_authorized"] is False,
        "live_authorized_false": packet["live_authorized"] is False,
        "live_gate_blocked_human_only": packet["live_gate"] == "blocked_human_only",
        "order_submitted_false": packet["order_submitted"] is False,
        "test_order_submitted_false": packet["test_order_submitted"] is False,
        "exchange_leverage_mutated_false": packet["exchange_leverage_mutated"] is False,
        "exchange_margin_mutated_false": packet["exchange_margin_mutated"] is False,
        "places_real_order_false": packet["places_real_order"] is False,
        "writes_legacy_redis_false": packet["writes_legacy_redis"] is False,
    }
    return packet


def write_phase9_one_flip_readiness_packet(
    *,
    goal_dir: Path,
    public_dir: Path | None = None,
    redis_client: Any = None,
    phase8_candidate_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet = build_phase9_one_flip_readiness_packet(
        redis_client=redis_client,
        phase8_candidate_matrix=phase8_candidate_matrix,
    )
    for directory in (goal_dir, public_dir):
        if directory is not None:
            _write_json(directory / "real_trader_one_flip_readiness_packet.json", packet)
    return packet
