"""Audited live-gate endpoints.

The route prefix is ``/live-gate`` rather than ``/live`` so operators can
inspect gate state while the default-deny ``/api/v1/live/**`` guard remains
intact. These handlers do not contact exchanges, write Redis, or place orders.
They persist operator acceptance/audit artifacts and fail closed unless the
current gate plus all acceptance records are valid.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException
from app.auth.security import require_superadmin

from app.services.live_gate.single_pass import GATE_BLOCKED, LIVE_GATE_BLOCKED, load_latest_live_gate_status
from app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
    write_runtime_execution_state,
)

public_status_router = APIRouter(prefix="/live-gate", tags=["live-gate"])
router = APIRouter(prefix="/live-gate", tags=["live-gate"], dependencies=[Depends(require_superadmin)])

ROUTE_METADATA: dict[str, Any] = {
    "group": "live_gate",
    "prefix": "/live-gate",
    "endpoints": (
        "/status",
        "/evaluate",
        "/arm",
        "/accept-risk-profile",
        "/accept-live-symbols",
        "/final-approval",
        "/enable",
        "/accept-failover-exchange",
        "/accept-failover-symbols",
        "/failover-final-approval",
    ),
    "rbac": "live_admin",
    "default_deny_execution": True,
}

_REPO_ROOT_ENV = "V2_REPO_ROOT"
_TYPED_CONFIRMATION = "ENABLE V2 LIVE EXECUTION"
_RISK_CONFIRMATION = "ACCEPT V2 LIVE RISK PROFILE"
_SYMBOL_CONFIRMATION = "ACCEPT V2 LIVE SYMBOLS"
_FINAL_CONFIRMATION = "APPROVE V2 LIVE EXECUTION FINAL GATE"
_FAILOVER_EXCHANGE_CONFIRMATION = "ACCEPT V2 LIVE FAILOVER EXCHANGE"
_FAILOVER_SYMBOLS_CONFIRMATION = "ACCEPT V2 LIVE FAILOVER SYMBOLS"
_FAILOVER_FINAL_CONFIRMATION = "APPROVE V2 LIVE FAILOVER FINAL GATE"
_SERVICE_ID = "v2_audited_operator_live_acceptance_and_enable_flow"
_FAILOVER_SERVICE_ID = "v2_audited_exchange_failover_selection_and_transport_implementation"
_READY_MARKER = "V2_AUDITED_OPERATOR_LIVE_ACCEPTANCE_AND_ENABLE_FLOW_READY"
_BLOCKED_MARKER = "V2_AUDITED_OPERATOR_LIVE_ACCEPTANCE_AND_ENABLE_FLOW_BLOCKED"
_EST = ZoneInfo("America/New_York")
_PAPER_FILL_GATE_PACKET_REL = Path(
    "v2/frontend/public/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready/latest/operator_dashboard_payload.json"
)
_PAPER_FILL_GATE_DIR_REL = Path(
    "v2/frontend/public/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready/latest"
)
_FLOW_PUBLIC_REL = Path("v2/frontend/public") / _SERVICE_ID / "latest"
_FLOW_WORKLOG_REL = Path("claude_worklog/final_readiness") / _SERVICE_ID / "latest"
_FAILOVER_FLOW_PUBLIC_REL = Path("v2/frontend/public") / _FAILOVER_SERVICE_ID / "latest"
_FAILOVER_FLOW_WORKLOG_REL = Path("claude_worklog/final_readiness") / _FAILOVER_SERVICE_ID / "latest"
_EXCHANGE_FILTER_ALIGNMENT_REL = Path(
    "v2/frontend/public/v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest"
)
_EXCHANGE_FILTER_PROFILE_PROPOSAL_FILE = "executable_minimum_conservative_risk_profile_proposal.json"
_ALLOWED_RUNTIME_RISK_PROFILE_NAMES = frozenset({"conservative", "conservative_min_executable"})

_RISK_STATUS_FILE = "risk_profile_acceptance_status.json"
_SYMBOL_STATUS_FILE = "live_symbol_acceptance_status.json"
_FINAL_STATUS_FILE = "final_operator_live_approval_status.json"
_AUDIT_STATUS_FILE = "live_gate_audit_record_status.json"
_ENABLE_STATUS_FILE = "live_enable_re_evaluation_status.json"
_FAILOVER_EXCHANGE_STATUS_FILE = "failover_exchange_acceptance_status.json"
_FAILOVER_SYMBOL_STATUS_FILE = "failover_symbol_acceptance_status.json"
_FAILOVER_FINAL_STATUS_FILE = "failover_final_operator_approval_status.json"
_FAILOVER_AUDIT_STATUS_FILE = "failover_gate_audit_record_status.json"
_REQUIRED_RUNTIME_RISK_FIELDS = (
    "max_notional_per_trade",
    "max_symbol_exposure",
    "max_total_exposure",
    "max_daily_loss",
    "max_drawdown",
    "max_open_positions",
    "max_leverage",
    "min_expected_move_after_cost_bps",
    "min_confidence_calibrated",
    "max_spread_bps",
    "max_slippage_bps",
    "cooldown_seconds",
    "kill_switch_conditions",
)


def _json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _repo_root() -> Path:
    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()


def _est_now() -> str:
    return datetime.now(tz=_EST).isoformat(timespec="seconds")


def _hash_confirmation(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _actor(body: dict[str, Any]) -> str:
    return str(body.get("operator_id") or body.get("actor") or "unknown")


def _role(body: dict[str, Any]) -> str:
    return str(body.get("operator_role") or body.get("role") or "operator")


def _artifact_path(filename: str, *, worklog: bool = False) -> Path:
    rel = _FLOW_WORKLOG_REL if worklog else _FLOW_PUBLIC_REL
    return _repo_root() / rel / filename


def _failover_artifact_path(filename: str, *, worklog: bool = False) -> Path:
    rel = _FAILOVER_FLOW_WORKLOG_REL if worklog else _FAILOVER_FLOW_PUBLIC_REL
    return _repo_root() / rel / filename


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_artifact(filename: str, payload: dict[str, Any]) -> None:
    _write_json(_artifact_path(filename), payload)
    _write_json(_artifact_path(filename, worklog=True), payload)


def _write_failover_artifact(filename: str, payload: dict[str, Any]) -> None:
    _write_json(_failover_artifact_path(filename), payload)
    _write_json(_failover_artifact_path(filename, worklog=True), payload)


def _write_text_artifact(filename: str, text: str) -> None:
    _write_text(_artifact_path(filename), text)
    _write_text(_artifact_path(filename, worklog=True), text)


def _base_status() -> dict[str, Any]:
    repo_root = _repo_root()
    payload = _json_load(repo_root / _PAPER_FILL_GATE_PACKET_REL) or load_latest_live_gate_status(repo_root)
    if "exact_blockers" not in payload:
        blockers = payload.get("live_enable_blockers")
        if isinstance(blockers, list):
            payload["exact_blockers"] = [str(item) for item in blockers]
        else:
            final_gate = payload.get("final_live_gate")
            if isinstance(final_gate, dict) and isinstance(final_gate.get("exact_remaining_blockers"), list):
                payload["exact_blockers"] = [str(item) for item in final_gate.get("exact_remaining_blockers")]
    payload.setdefault("live_gate", LIVE_GATE_BLOCKED)
    payload.setdefault("live_symbols", [])
    payload.setdefault("execution_live_symbols", [])
    payload.setdefault("trader_execution_enabled", False)
    payload.setdefault("places_real_order", False)
    payload.setdefault("go_no_go", GATE_BLOCKED)
    return payload


def _read_flow_artifact(filename: str) -> dict[str, Any]:
    return _json_load(_artifact_path(filename))


def _read_failover_artifact(filename: str) -> dict[str, Any]:
    return _json_load(_failover_artifact_path(filename))


def _paper_fill_artifact(filename: str) -> dict[str, Any]:
    return _json_load(_repo_root() / _PAPER_FILL_GATE_DIR_REL / filename)


def _risk_proposal() -> dict[str, Any]:
    proposal = dict(_paper_fill_artifact("live_gate_risk_cap_proposal_after_paper_fill.json"))
    profiles = proposal.get("profiles") if isinstance(proposal.get("profiles"), dict) else {}
    merged_profiles = dict(profiles)
    exchange_filter_proposal = _json_load(
        _repo_root() / _EXCHANGE_FILTER_ALIGNMENT_REL / _EXCHANGE_FILTER_PROFILE_PROPOSAL_FILE
    )
    profile_payload = exchange_filter_proposal.get("profile")
    if isinstance(profile_payload, dict):
        profile_name = str(
            profile_payload.get("profile_name") or profile_payload.get("profile_id") or "conservative_min_executable"
        )
        fields = profile_payload.get("risk_fields") if isinstance(profile_payload.get("risk_fields"), dict) else None
        if profile_name and isinstance(fields, dict):
            merged_profiles[profile_name] = fields
    extra_profiles = exchange_filter_proposal.get("profiles")
    if isinstance(extra_profiles, dict):
        for name, fields in extra_profiles.items():
            if isinstance(fields, dict):
                merged_profiles[str(name)] = fields
    proposal["profiles"] = merged_profiles
    proposal["merged_exchange_filter_profile_proposal"] = bool(exchange_filter_proposal)
    proposal["exchange_filter_profile_proposal_source"] = str(
        _EXCHANGE_FILTER_ALIGNMENT_REL / _EXCHANGE_FILTER_PROFILE_PROPOSAL_FILE
    )
    return proposal


def _symbol_proposal() -> dict[str, Any]:
    return _paper_fill_artifact("live_symbol_candidate_proposal_after_paper_fill.json")


def _inventory() -> dict[str, Any]:
    return _paper_fill_artifact("paper_fill_gate_block_reason_inventory.json")


def _audit_status() -> dict[str, Any]:
    payload = _read_flow_artifact(_AUDIT_STATUS_FILE)
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": "live_gate_audit_record_status_v1",
        "service_id": _SERVICE_ID,
        "records": records,
        "record_count": len(records),
        "latest_audit_id": records[-1].get("audit_id") if records and isinstance(records[-1], dict) else None,
        "website_enable_flow_writes_audit_record": len(records) > 0,
    }


def _failover_audit_status() -> dict[str, Any]:
    payload = _read_failover_artifact(_FAILOVER_AUDIT_STATUS_FILE)
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": "failover_gate_audit_record_status_v1",
        "service_id": _FAILOVER_SERVICE_ID,
        "records": records,
        "record_count": len(records),
        "latest_audit_id": records[-1].get("audit_id") if records and isinstance(records[-1], dict) else None,
        "website_enable_flow_writes_audit_record": len(records) > 0,
        "failover_live_enabled": False,
        "order_submission_allowed": False,
    }


def _source_payload_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("source_payload_id")
        or f"{payload.get('service_id') or 'live_gate_source'}:{payload.get('generated_est') or 'missing_generated_est'}"
    )


def _require_confirmation(body: dict[str, Any], expected: str) -> None:
    if body.get("operator_confirmation_text") != expected:
        raise HTTPException(
            status_code=400,
            detail={
                "accepted": False,
                "reason": "OPERATOR_CONFIRMATION_TEXT_REQUIRED",
                "operator_confirmation_text_required": expected,
            },
        )


def _require_reason_and_source(body: dict[str, Any]) -> tuple[str, str]:
    reason = str(body.get("operator_reason") or "").strip()
    source_payload_id = str(body.get("source_payload_id") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": "OPERATOR_REASON_REQUIRED"})
    if not source_payload_id:
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": "SOURCE_PAYLOAD_ID_REQUIRED"})
    return reason, source_payload_id


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _paper_signal_evidence_by_symbol() -> dict[str, dict[str, Any]]:
    inventory = _inventory()
    rows = inventory.get("paper_signal_rows")
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        out[symbol] = {
            "symbol": symbol,
            "prediction_id": row.get("prediction_id"),
            "orchestrator_decision_id": row.get("winner_proposal_id"),
            "paper_fill_allowed": row.get("paper_fill_allowed") is True,
            "paper_fill_gate_status": row.get("paper_fill_gate_status"),
            "feature_freshness_state": row.get("feature_freshness_state"),
            "model_version": row.get("model_version"),
            "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
            "confidence_calibrated": row.get("confidence_calibrated"),
            "live_gate": row.get("live_gate"),
            "places_real_order": row.get("places_real_order"),
        }
    return out


def _validate_risk_acceptance(record: dict[str, Any], proposal: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    profiles = proposal.get("profiles") if isinstance(proposal.get("profiles"), dict) else {}
    profile_name = str(record.get("accepted_profile_name") or record.get("profile_name") or "")
    proposed_fields = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if record.get("risk_profile_operator_accepted") is not True:
        blockers.append("risk_profile_operator_accepted")
    if not profile_name or not isinstance(proposed_fields, dict):
        blockers.append("accepted_risk_profile_not_in_current_proposal")
    if not record.get("audit_id"):
        blockers.append("risk_profile_acceptance_audit_id_missing")
    if isinstance(proposed_fields, dict) and _canonical(record.get("accepted_profile_fields")) != _canonical(proposed_fields):
        blockers.append("accepted_risk_profile_fields_do_not_match_current_proposal")
    return not blockers, blockers


def _validate_symbol_acceptance(record: dict[str, Any], proposal: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    blockers: list[str] = []
    proposed = {str(symbol) for symbol in (proposal.get("proposed_live_symbols") or []) if str(symbol)}
    accepted = [str(symbol) for symbol in (record.get("accepted_live_symbols") or []) if str(symbol)]
    evidence = _paper_signal_evidence_by_symbol()
    per_symbol: dict[str, Any] = {}
    if record.get("live_symbol_operator_accepted") is not True:
        blockers.append("live_symbol_operator_accepted")
    if not accepted:
        blockers.append("accepted_live_symbols_empty")
    if not record.get("audit_id"):
        blockers.append("live_symbol_acceptance_audit_id_missing")
    outside = sorted(set(accepted) - proposed)
    if outside:
        blockers.append("accepted_live_symbols_not_subset_of_current_proposal")
    for symbol in accepted:
        row = evidence.get(symbol, {})
        row_blockers: list[str] = []
        if not row.get("prediction_id"):
            row_blockers.append("current_prediction_missing")
        if not row.get("orchestrator_decision_id"):
            row_blockers.append("orchestrator_winner_missing")
        if row.get("paper_fill_allowed") is not True:
            row_blockers.append("paper_fill_allowed_not_true")
        if row.get("paper_fill_gate_status") != "PAPER_FILL_ALLOWED_BY_ORCHESTRATOR_GATE":
            row_blockers.append("paper_fill_gate_not_allowed")
        if row.get("feature_freshness_state") != "CURRENT":
            row_blockers.append("feature_freshness_not_current")
        if row.get("live_gate") != LIVE_GATE_BLOCKED:
            row_blockers.append("source_live_gate_not_blocked")
        if row.get("places_real_order") is not False:
            row_blockers.append("source_places_real_order_not_false")
        per_symbol[symbol] = {"evidence": row, "blockers": row_blockers, "valid": not row_blockers}
    if any(not item.get("valid") for item in per_symbol.values()):
        blockers.append("accepted_live_symbol_current_evidence_failed")
    return not blockers, blockers, per_symbol


def _validate_final_approval(
    record: dict[str, Any],
    risk_record: dict[str, Any],
    symbol_record: dict[str, Any],
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if record.get("operator_final_live_approval_present") is not True:
        blockers.append("operator_final_live_approval_present")
    if not record.get("audit_id"):
        blockers.append("final_operator_approval_audit_id_missing")
    if record.get("accepted_risk_audit_id") != risk_record.get("audit_id"):
        blockers.append("final_approval_risk_audit_id_mismatch")
    if record.get("accepted_symbols_audit_id") != symbol_record.get("audit_id"):
        blockers.append("final_approval_symbol_audit_id_mismatch")
    return not blockers, blockers


def _required_audit_actions_present(audit: dict[str, Any], risk_ok: bool, symbols_ok: bool, final_ok: bool) -> bool:
    records = [row for row in audit.get("records", []) if isinstance(row, dict)]
    actions = {str(row.get("action")) for row in records if row.get("result") in ("ACCEPTED", "APPROVED")}
    return (
        risk_ok
        and symbols_ok
        and final_ok
        and {"accept-risk-profile", "accept-live-symbols", "final-approval"}.issubset(actions)
    )


def _build_acceptance_state() -> dict[str, Any]:
    repo_root = _repo_root()
    base = _base_status()
    risk_proposal = _risk_proposal()
    symbol_proposal = _symbol_proposal()
    inventory = _inventory()
    risk_record = _read_flow_artifact(_RISK_STATUS_FILE)
    symbol_record = _read_flow_artifact(_SYMBOL_STATUS_FILE)
    final_record = _read_flow_artifact(_FINAL_STATUS_FILE)
    audit = _audit_status()

    risk_ok, risk_blockers = _validate_risk_acceptance(risk_record, risk_proposal)
    symbols_ok, symbol_blockers, per_symbol_evidence = _validate_symbol_acceptance(symbol_record, symbol_proposal)
    final_ok, final_blockers = _validate_final_approval(final_record, risk_record, symbol_record)
    audit_ok = _required_audit_actions_present(audit, risk_ok, symbols_ok, final_ok)

    final_gate = base.get("final_live_gate") if isinstance(base.get("final_live_gate"), dict) else {}
    base_requirements = final_gate.get("requirements") if isinstance(final_gate.get("requirements"), dict) else {}
    requirements = {
        "paper_fill_gate_accepts_fills": bool(base_requirements.get("paper_fill_gate_accepts_fills", False)),
        "paper_edge_backtest_not_critically_negative": bool(base_requirements.get("paper_edge_backtest_not_critically_negative", False)),
        "risk_profile_proposed": bool((risk_proposal.get("profiles") or {})),
        "risk_profile_operator_accepted": risk_ok,
        "live_symbol_proposal_present": bool(symbol_proposal.get("proposed_live_symbols")),
        "live_symbol_operator_accepted": symbols_ok,
        "binance_trader_connected": bool(base_requirements.get("binance_trader_connected", False)),
        "exchange_mutation_safety_passed": bool(base_requirements.get("exchange_mutation_safety_passed", False)),
        "codex_final_live_pass_exists": bool(base_requirements.get("codex_final_live_pass_exists", False)),
        "operator_final_live_approval_present": final_ok,
        "website_enable_flow_writes_audit_record": audit_ok,
        "live_symbols_remain_empty_until_operator_acceptance": bool(
            base_requirements.get("live_symbols_remain_empty_until_operator_acceptance", True)
        ),
        "no_unresolved_critical_data_blocker": bool(base_requirements.get("no_unresolved_critical_data_blocker", False)),
    }
    exact_blockers = sorted([key for key, value in requirements.items() if not value])
    if risk_blockers:
        exact_blockers.extend(sorted(set(risk_blockers)))
    if symbol_blockers:
        exact_blockers.extend(sorted(set(symbol_blockers)))
    if final_blockers:
        exact_blockers.extend(sorted(set(final_blockers)))
    exact_blockers = sorted(set(exact_blockers))
    live_enable_available = not exact_blockers
    verdict = "LIVE_OPERATOR_ENABLE_AVAILABLE" if live_enable_available else "LIVE_GATE_BLOCKED_AUDITED_ACCEPTANCE_REQUIRED"
    go_no_go = _READY_MARKER if live_enable_available else _BLOCKED_MARKER
    source_payload_id = _source_payload_id(base)
    runtime_read = read_runtime_execution_state(repo_root=repo_root)
    runtime_payload = runtime_read.get("payload") if isinstance(runtime_read.get("payload"), dict) else {}
    runtime_validation = runtime_read.get("validation") if isinstance(runtime_read.get("validation"), dict) else {}
    runtime_enabled = bool(runtime_validation.get("valid"))
    active_live_gate = str(runtime_payload.get("live_gate") or LIVE_GATE_BLOCKED) if runtime_enabled else LIVE_GATE_BLOCKED
    active_live_symbols = list(runtime_payload.get("live_symbols") or []) if runtime_enabled else []
    active_execution_live_symbols = list(runtime_payload.get("execution_live_symbols") or []) if runtime_enabled else []
    active_trader_execution_enabled = bool(runtime_payload.get("trader_execution_enabled")) if runtime_enabled else False

    source_reconciliation = {
        "schema_version": "live_gate_source_reconciliation_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "authoritative_source": str(_PAPER_FILL_GATE_PACKET_REL),
        "current_source_payload_id": source_payload_id,
        "current_go_no_go": base.get("go_no_go"),
        "current_verdict": base.get("verdict"),
        "current_backend_live_enable_callable": bool(base.get("backend_live_enable_callable")),
        "current_live_gate": base.get("live_gate", LIVE_GATE_BLOCKED),
        "current_live_symbols": base.get("live_symbols", []),
        "current_execution_live_symbols": base.get("execution_live_symbols", []),
        "missing_acceptance_fields": exact_blockers,
        "proposed_risk_profiles": sorted((risk_proposal.get("profiles") or {}).keys()),
        "proposed_live_symbols": symbol_proposal.get("proposed_live_symbols", []),
        "trader_runtime_state": base.get("trader_runtime", {}),
        "binance_read_only_state": {
            "trader_connected": requirements["binance_trader_connected"],
            "exchange_mutation_safety_passed": requirements["exchange_mutation_safety_passed"],
        },
        "stale_callable_true_payload_marked": bool(base.get("backend_live_enable_callable")) and bool(exact_blockers),
        "runtime_execution_state": {
            "loaded": bool(runtime_read.get("loaded")),
            "source": runtime_read.get("source"),
            "validation": runtime_validation,
        },
    }

    risk_status = {
        "schema_version": "risk_profile_acceptance_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "risk_profile_operator_accepted": risk_ok,
        "current_validation_blockers": risk_blockers,
        "accepted_profile_id": risk_record.get("accepted_profile_id"),
        "accepted_profile_name": risk_record.get("accepted_profile_name"),
        "accepted_profile_fields": risk_record.get("accepted_profile_fields"),
        "accepted_at_est": risk_record.get("accepted_at_est"),
        "audit_id": risk_record.get("audit_id"),
        "source_payload_id": risk_record.get("source_payload_id"),
        "operator_acceptance_required": True,
        "accepted_record_present": bool(risk_record.get("audit_id")),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }
    symbol_status = {
        "schema_version": "live_symbol_acceptance_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "live_symbol_operator_accepted": symbols_ok,
        "current_validation_blockers": symbol_blockers,
        "accepted_live_symbols": symbol_record.get("accepted_live_symbols", []),
        "accepted_at_est": symbol_record.get("accepted_at_est"),
        "audit_id": symbol_record.get("audit_id"),
        "source_payload_id": symbol_record.get("source_payload_id"),
        "per_symbol_evidence": per_symbol_evidence,
        "operator_acceptance_required": True,
        "accepted_record_present": bool(symbol_record.get("audit_id")),
        "live_symbols_written": [],
        "execution_live_symbols_written": [],
        "live_gate": LIVE_GATE_BLOCKED,
    }
    final_status = {
        "schema_version": "final_operator_live_approval_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "operator_final_live_approval_present": final_ok,
        "current_validation_blockers": final_blockers,
        "final_approval_at_est": final_record.get("final_approval_at_est"),
        "audit_id": final_record.get("audit_id"),
        "accepted_risk_audit_id": final_record.get("accepted_risk_audit_id"),
        "accepted_symbols_audit_id": final_record.get("accepted_symbols_audit_id"),
        "source_payload_id": final_record.get("source_payload_id"),
        "operator_acceptance_required": True,
        "accepted_record_present": bool(final_record.get("audit_id")),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }
    enable_status = {
        "schema_version": "live_enable_re_evaluation_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "verdict": verdict,
        "go_no_go": go_no_go,
        "requirements": requirements,
        "exact_blockers": exact_blockers,
        "backend_live_enable_callable": live_enable_available,
        "enabled": runtime_enabled,
        "runtime_mutation_executed": runtime_enabled,
        "accepted_live_symbols_for_final_enable": symbol_status["accepted_live_symbols"] if live_enable_available else [],
        "live_gate": active_live_gate,
        "live_symbols": active_live_symbols,
        "execution_live_symbols": active_execution_live_symbols,
        "runtime_execution_state": {
            "loaded": bool(runtime_read.get("loaded")),
            "source": runtime_read.get("source"),
            "validation": runtime_validation,
        },
    }
    dashboard = {
        "schema_version": "audited_operator_live_acceptance_operator_dashboard_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "go_no_go": go_no_go,
        "verdict": verdict,
        "backend_live_enable_callable": live_enable_available,
        "live_gate": active_live_gate,
        "live_symbols": active_live_symbols,
        "execution_live_symbols": active_execution_live_symbols,
        "trader_execution_enabled": active_trader_execution_enabled,
        "places_real_order": False,
        "source_reconciliation": source_reconciliation,
        "acceptance_requirements": requirements,
        "exact_blockers": exact_blockers,
        "risk_profile_acceptance": risk_status,
        "live_symbol_acceptance": symbol_status,
        "final_operator_approval": final_status,
        "audit_record_status": {
            **audit,
            "website_enable_flow_writes_audit_record": audit_ok,
        },
        "current_proposals": {
            "risk_profiles": risk_proposal.get("profiles", {}),
            "live_symbols": symbol_proposal.get("proposed_live_symbols", []),
            "paper_signal_count": inventory.get("paper_signals"),
            "accepted_paper_fills": inventory.get("accepted_paper_fills"),
            "held_by_paper_fill_gate": inventory.get("held_by_paper_fill_gate"),
        },
        "endpoint_contracts": {
            "accept_risk_profile": {
                "method": "POST",
                "path": "/api/v1/live-gate/accept-risk-profile",
                "operator_confirmation_text_required": _RISK_CONFIRMATION,
            },
            "accept_live_symbols": {
                "method": "POST",
                "path": "/api/v1/live-gate/accept-live-symbols",
                "operator_confirmation_text_required": _SYMBOL_CONFIRMATION,
            },
            "final_approval": {
                "method": "POST",
                "path": "/api/v1/live-gate/final-approval",
                "operator_confirmation_text_required": _FINAL_CONFIRMATION,
            },
            "enable": {
                "method": "POST",
                "path": "/api/v1/live-gate/enable",
                "typed_confirmation_required": _TYPED_CONFIRMATION,
            },
        },
        "live_enable_re_evaluation": enable_status,
        "runtime_execution_state": {
            "loaded": bool(runtime_read.get("loaded")),
            "source": runtime_read.get("source"),
            "validation": runtime_validation,
        },
    }
    return {
        "source_reconciliation": source_reconciliation,
        "risk_status": risk_status,
        "symbol_status": symbol_status,
        "final_status": final_status,
        "audit_status": {**audit, "website_enable_flow_writes_audit_record": audit_ok},
        "enable_status": enable_status,
        "dashboard": dashboard,
        "base_status": base,
        "risk_proposal": risk_proposal,
        "symbol_proposal": symbol_proposal,
        "requirements": requirements,
        "exact_blockers": exact_blockers,
        "live_enable_available": live_enable_available,
        "go_no_go": go_no_go,
        "verdict": verdict,
    }


def _build_report(state: dict[str, Any]) -> str:
    dashboard = state["dashboard"]
    blockers = dashboard.get("exact_blockers") or []
    lines = [
        "# V2 Audited Operator Live Acceptance And Enable Flow Report",
        "",
        f"Generated EST: `{dashboard.get('generated_est')}`",
        f"Gate: `{dashboard.get('go_no_go')}`",
        f"Verdict: `{dashboard.get('verdict')}`",
        f"Backend live enable callable: `{dashboard.get('backend_live_enable_callable')}`",
        f"Live gate: `{dashboard.get('live_gate')}`",
        f"Live symbols: `{dashboard.get('live_symbols')}`",
        "",
        "## Acceptance State",
        f"- risk_profile_operator_accepted: `{dashboard['acceptance_requirements']['risk_profile_operator_accepted']}`",
        f"- live_symbol_operator_accepted: `{dashboard['acceptance_requirements']['live_symbol_operator_accepted']}`",
        f"- operator_final_live_approval_present: `{dashboard['acceptance_requirements']['operator_final_live_approval_present']}`",
        f"- website_enable_flow_writes_audit_record: `{dashboard['acceptance_requirements']['website_enable_flow_writes_audit_record']}`",
        "",
        "## Remaining Blockers",
    ]
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(
        [
            "",
            "## Safety",
            "- No exchange order/test-order/cancel/modify performed by this flow.",
            "- No leverage or margin mutation.",
            "- No old Redis write, Redis trim, or legacy restart.",
            "- No raw credential payload fields are written.",
            "- If enabled, only V2 runtime execution state is written; this API still does not submit exchange orders.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_flow_outputs(state: dict[str, Any]) -> None:
    _write_artifact("live_gate_source_reconciliation_status.json", state["source_reconciliation"])
    _write_artifact(_RISK_STATUS_FILE, state["risk_status"])
    _write_artifact(_SYMBOL_STATUS_FILE, state["symbol_status"])
    _write_artifact(_FINAL_STATUS_FILE, state["final_status"])
    _write_artifact(_AUDIT_STATUS_FILE, state["audit_status"])
    _write_artifact(_ENABLE_STATUS_FILE, state["enable_status"])
    _write_artifact("operator_dashboard_payload.json", state["dashboard"])
    _write_text_artifact("GO_NO_GO.md", state["go_no_go"] + "\n")
    _write_text_artifact("V2_AUDITED_OPERATOR_LIVE_ACCEPTANCE_AND_ENABLE_FLOW_REPORT.md", _build_report(state))


def _status() -> dict[str, Any]:
    state = _build_acceptance_state()
    payload = dict(state["dashboard"])
    payload["final_live_gate"] = {
        "verdict": state["verdict"],
        "requirements": state["requirements"],
        "exact_remaining_blockers": state["exact_blockers"],
        "live_enable_available_through_backend_gate": state["live_enable_available"],
    }
    payload["live_enable_blockers"] = state["exact_blockers"]
    return payload


def _blockers(payload: dict[str, Any]) -> list[str]:
    blockers = payload.get("exact_blockers")
    if isinstance(blockers, list):
        return [str(item) for item in blockers]
    return ["LIVE_GATE_BLOCKERS_UNKNOWN_FAIL_CLOSED"]


def _live_enable_available(payload: dict[str, Any], blockers: list[str]) -> bool:
    if blockers:
        return False
    final_gate = payload.get("final_live_gate")
    if isinstance(final_gate, dict) and final_gate.get("verdict") == "LIVE_OPERATOR_ENABLE_AVAILABLE":
        return True
    if payload.get("verdict") == "LIVE_OPERATOR_ENABLE_AVAILABLE":
        return True
    return bool(payload.get("backend_live_enable_callable"))


def _audit_record(
    *,
    audit_id: str,
    action: str,
    body: dict[str, Any],
    result: str,
    before: dict[str, Any],
    after: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "timestamp_est": _est_now(),
        "actor": _actor(body),
        "role": _role(body),
        "action": action,
        "confirmation_text_hash": _hash_confirmation(body.get("operator_confirmation_text") or body.get("typed_confirmation")),
        "operator_reason": body.get("operator_reason"),
        "source_payload_ids": [body.get("source_payload_id")] if body.get("source_payload_id") else [],
        "selected_risk_profile": body.get("profile_name") or body.get("profile_id"),
        "selected_symbols": body.get("symbols") or [],
        "result": result,
        "before_gate_state": {
            "verdict": before.get("verdict"),
            "backend_live_enable_callable": before.get("live_enable_available"),
            "exact_blockers": before.get("exact_blockers"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
        },
        "after_gate_state": {
            "verdict": after.get("verdict"),
            "backend_live_enable_callable": after.get("live_enable_available"),
            "exact_blockers": after.get("exact_blockers"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
        },
        "details": details or {},
    }


def _append_audit(record: dict[str, Any]) -> dict[str, Any]:
    audit = _audit_status()
    records = [row for row in audit.get("records", []) if isinstance(row, dict)]
    records.append(record)
    payload = {
        "schema_version": "live_gate_audit_record_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "record_count": len(records),
        "latest_audit_id": record.get("audit_id"),
        "website_enable_flow_writes_audit_record": True,
        "records": records[-250:],
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }
    _write_artifact(_AUDIT_STATUS_FILE, payload)
    return payload


def _failover_candidate_matrix() -> dict[str, Any]:
    return _read_failover_artifact("audited_exchange_failover_candidate_matrix.json")


def _failover_selection_proposal() -> dict[str, Any]:
    return _read_failover_artifact("audited_exchange_failover_selection_proposal.json")


def _failover_candidate(exchange: str) -> dict[str, Any] | None:
    matrix = _failover_candidate_matrix()
    for row in matrix.get("candidates") or []:
        if isinstance(row, dict) and str(row.get("exchange") or "").lower() == exchange.lower():
            return row
    return None


def _failover_proposed_symbols() -> set[str]:
    proposal = _failover_selection_proposal()
    return {str(symbol).upper() for symbol in (proposal.get("proposed_symbols") or []) if str(symbol).strip()}


def _failover_audit_record(
    *,
    audit_id: str,
    action: str,
    body: dict[str, Any],
    result: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recovery_payload = _read_failover_artifact("operator_dashboard_payload.json")
    return {
        "audit_id": audit_id,
        "timestamp_est": _est_now(),
        "actor": _actor(body),
        "role": _role(body),
        "action": action,
        "confirmation_text_hash": _hash_confirmation(body.get("operator_confirmation_text")),
        "operator_reason": body.get("operator_reason"),
        "source_payload_ids": [body.get("source_payload_id")] if body.get("source_payload_id") else [],
        "selected_failover_exchange": body.get("exchange"),
        "selected_symbols": body.get("symbols") or [],
        "result": result,
        "before_gate_state": {
            "binance_private_execution_status": recovery_payload.get("binance_private_execution_status"),
            "failover_live_enabled": False,
            "order_submission_allowed": False,
            "automatic_live_failover_allowed": False,
        },
        "after_gate_state": {
            "failover_live_enabled": False,
            "order_submission_allowed": False,
            "automatic_live_failover_allowed": False,
        },
        "details": details or {},
        "raw_credentials_exposed": False,
    }


def _append_failover_audit(record: dict[str, Any]) -> dict[str, Any]:
    audit = _failover_audit_status()
    records = [row for row in audit.get("records", []) if isinstance(row, dict)]
    records.append(record)
    payload = {
        "schema_version": "failover_gate_audit_record_status_v1",
        "generated_est": _est_now(),
        "service_id": _FAILOVER_SERVICE_ID,
        "record_count": len(records),
        "latest_audit_id": record.get("audit_id"),
        "website_enable_flow_writes_audit_record": True,
        "records": records[-250:],
        "failover_live_enabled": False,
        "order_submission_allowed": False,
        "automatic_live_failover_allowed": False,
        "raw_credentials_exposed": False,
    }
    _write_failover_artifact(_FAILOVER_AUDIT_STATUS_FILE, payload)
    return payload


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA


@public_status_router.get("/status")
async def get_live_gate_status() -> dict[str, Any]:
    return _status()


@router.post("/evaluate")
async def evaluate_live_gate() -> dict[str, Any]:
    state = _build_acceptance_state()
    _write_flow_outputs(state)
    payload = _status()
    blockers = _blockers(payload)
    available = _live_enable_available(payload, blockers)
    payload["evaluation"] = {
        "performed": True,
        "result": "LIVE_OPERATOR_ENABLE_AVAILABLE" if available else "BLOCKED",
        "backend_live_enable_path_available": available,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }
    return payload


@router.post("/arm")
async def arm_live_gate(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    payload = _status()
    blockers = _blockers(payload)
    available = _live_enable_available(payload, blockers)
    return {
        "schema_version": "v2_live_gate_arm_response_v1",
        "armed": bool(available),
        "requested_by": body.get("operator_id") or body.get("actor") or "unknown",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "backend_live_enable_path_available": available,
        "exact_blockers": blockers,
        "typed_confirmation_required_for_enable": _TYPED_CONFIRMATION,
    }


@router.post("/accept-risk-profile")
async def accept_risk_profile(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _RISK_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    before = _build_acceptance_state()
    proposal = before["risk_proposal"]
    profiles = proposal.get("profiles") if isinstance(proposal.get("profiles"), dict) else {}
    profile_name = str(body.get("profile_name") or body.get("profile_id") or "")
    profile_id = str(body.get("profile_id") or profile_name)
    if not profile_name or profile_name not in profiles:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "RISK_PROFILE_NOT_IN_CURRENT_PROPOSAL",
                "proposed_profiles": sorted(profiles.keys()),
            },
        )
    proposed_fields = profiles[profile_name]
    risk_fields = body.get("risk_fields")
    if not isinstance(risk_fields, dict) or _canonical(risk_fields) != _canonical(proposed_fields):
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "RISK_FIELDS_MUST_MATCH_CURRENT_PROPOSAL",
                "profile_name": profile_name,
                "source_payload_id": source_payload_id,
            },
        )
    audit_id = f"live_gate_risk_{uuid4().hex}"
    status = {
        "schema_version": "risk_profile_acceptance_record_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "risk_profile_operator_accepted": True,
        "accepted_profile_id": profile_id,
        "accepted_profile_name": profile_name,
        "accepted_profile_fields": proposed_fields,
        "accepted_at_est": _est_now(),
        "audit_id": audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "enabled_live": False,
    }
    _write_artifact(_RISK_STATUS_FILE, status)
    after = _build_acceptance_state()
    _append_audit(
        _audit_record(
            audit_id=audit_id,
            action="accept-risk-profile",
            body=body,
            result="ACCEPTED",
            before=before,
            after=after,
            details={
                "accepted_profile_name": profile_name,
                "accepted_profile_fields": proposed_fields,
            },
        )
    )
    final_state = _build_acceptance_state()
    _write_flow_outputs(final_state)
    return final_state["risk_status"]


@router.post("/accept-live-symbols")
async def accept_live_symbols(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _SYMBOL_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    before = _build_acceptance_state()
    proposal = before["symbol_proposal"]
    proposed = {str(symbol) for symbol in (proposal.get("proposed_live_symbols") or []) if str(symbol)}
    symbols = [str(symbol).upper() for symbol in (body.get("symbols") or []) if str(symbol).strip()]
    if not symbols:
        raise HTTPException(status_code=422, detail={"accepted": False, "reason": "SYMBOLS_REQUIRED"})
    outside = sorted(set(symbols) - proposed)
    if outside:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "SYMBOLS_NOT_SUBSET_OF_CURRENT_PROPOSAL",
                "invalid_symbols": outside,
                "proposed_live_symbols": sorted(proposed),
            },
        )

    paper_evidence = _paper_signal_evidence_by_symbol()
    invalid: dict[str, Any] = {}
    for symbol in symbols:
        row = paper_evidence.get(symbol, {})
        blockers: list[str] = []
        if not row.get("prediction_id"):
            blockers.append("current_prediction_missing")
        if not row.get("orchestrator_decision_id"):
            blockers.append("orchestrator_winner_missing")
        if row.get("paper_fill_allowed") is not True:
            blockers.append("paper_fill_allowed_not_true")
        if row.get("paper_fill_gate_status") != "PAPER_FILL_ALLOWED_BY_ORCHESTRATOR_GATE":
            blockers.append("paper_fill_gate_not_allowed")
        if row.get("feature_freshness_state") != "CURRENT":
            blockers.append("feature_freshness_not_current")
        if row.get("live_gate") != LIVE_GATE_BLOCKED:
            blockers.append("source_live_gate_not_blocked")
        if row.get("places_real_order") is not False:
            blockers.append("source_places_real_order_not_false")
        if blockers:
            invalid[symbol] = {"blockers": blockers, "evidence": row}
    if invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "SYMBOL_CURRENT_EVIDENCE_FAILED",
                "invalid_symbols": invalid,
            },
        )

    audit_id = f"live_gate_symbols_{uuid4().hex}"
    status = {
        "schema_version": "live_symbol_acceptance_record_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "live_symbol_operator_accepted": True,
        "accepted_live_symbols": symbols,
        "accepted_at_est": _est_now(),
        "audit_id": audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "live_symbols_written": [],
        "execution_live_symbols_written": [],
        "enabled_live": False,
        "live_gate": LIVE_GATE_BLOCKED,
    }
    _write_artifact(_SYMBOL_STATUS_FILE, status)
    after = _build_acceptance_state()
    _append_audit(
        _audit_record(
            audit_id=audit_id,
            action="accept-live-symbols",
            body=body,
            result="ACCEPTED",
            before=before,
            after=after,
            details={"accepted_live_symbols": symbols},
        )
    )
    final_state = _build_acceptance_state()
    _write_flow_outputs(final_state)
    return final_state["symbol_status"]


@router.post("/final-approval")
async def final_operator_approval(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _FINAL_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    before = _build_acceptance_state()
    risk_status = before["risk_status"]
    symbol_status = before["symbol_status"]
    if risk_status.get("risk_profile_operator_accepted") is not True:
        raise HTTPException(status_code=423, detail={"approved": False, "reason": "RISK_PROFILE_ACCEPTANCE_REQUIRED"})
    if symbol_status.get("live_symbol_operator_accepted") is not True:
        raise HTTPException(status_code=423, detail={"approved": False, "reason": "LIVE_SYMBOL_ACCEPTANCE_REQUIRED"})
    accepted_risk_audit_id = str(body.get("accepted_risk_audit_id") or "")
    accepted_symbols_audit_id = str(body.get("accepted_symbols_audit_id") or "")
    if accepted_risk_audit_id != risk_status.get("audit_id"):
        raise HTTPException(status_code=422, detail={"approved": False, "reason": "RISK_AUDIT_ID_MISMATCH"})
    if accepted_symbols_audit_id != symbol_status.get("audit_id"):
        raise HTTPException(status_code=422, detail={"approved": False, "reason": "SYMBOL_AUDIT_ID_MISMATCH"})

    audit_id = f"live_gate_final_{uuid4().hex}"
    status = {
        "schema_version": "final_operator_live_approval_record_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "operator_final_live_approval_present": True,
        "final_approval_at_est": _est_now(),
        "audit_id": audit_id,
        "accepted_risk_audit_id": accepted_risk_audit_id,
        "accepted_symbols_audit_id": accepted_symbols_audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "enabled_live": False,
    }
    _write_artifact(_FINAL_STATUS_FILE, status)
    after = _build_acceptance_state()
    _append_audit(
        _audit_record(
            audit_id=audit_id,
            action="final-approval",
            body=body,
            result="APPROVED",
            before=before,
            after=after,
            details={
                "accepted_risk_audit_id": accepted_risk_audit_id,
                "accepted_symbols_audit_id": accepted_symbols_audit_id,
            },
        )
    )
    final_state = _build_acceptance_state()
    _write_flow_outputs(final_state)
    return final_state["final_status"]


@router.post("/accept-failover-exchange")
async def accept_failover_exchange(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _FAILOVER_EXCHANGE_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    exchange = str(body.get("exchange") or "").strip()
    if not exchange:
        raise HTTPException(status_code=422, detail={"accepted": False, "reason": "FAILOVER_EXCHANGE_REQUIRED"})
    candidate = _failover_candidate(exchange)
    if not candidate:
        matrix = _failover_candidate_matrix()
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "FAILOVER_EXCHANGE_NOT_IN_CURRENT_MATRIX",
                "candidate_exchanges": [
                    row.get("exchange") for row in matrix.get("candidates") or [] if isinstance(row, dict)
                ],
            },
        )
    if candidate.get("operator_approval_required") is not True and exchange.lower() != "paper-only fallback":
        raise HTTPException(
            status_code=422,
            detail={"accepted": False, "reason": "FAILOVER_EXCHANGE_OPERATOR_APPROVAL_CONTRACT_MISSING"},
        )
    if candidate.get("legal_operator_approval_required") is True and body.get("operator_legal_access_attested") is not True:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "OPERATOR_LEGAL_ACCESS_ATTESTATION_REQUIRED",
                "operator_legal_access_attested_required": True,
            },
        )

    audit_id = f"live_gate_failover_exchange_{uuid4().hex}"
    status = {
        "schema_version": "failover_exchange_acceptance_record_v1",
        "generated_est": _est_now(),
        "service_id": _FAILOVER_SERVICE_ID,
        "failover_exchange_operator_accepted": True,
        "accepted_exchange": candidate.get("exchange"),
        "accepted_at_est": _est_now(),
        "audit_id": audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "operator_legal_access_attested": body.get("operator_legal_access_attested") is True,
        "candidate_snapshot": candidate,
        "failover_live_enabled": False,
        "order_submission_allowed": False,
        "automatic_live_failover_allowed": False,
        "raw_credentials_exposed": False,
    }
    _write_failover_artifact(_FAILOVER_EXCHANGE_STATUS_FILE, status)
    _append_failover_audit(
        _failover_audit_record(
            audit_id=audit_id,
            action="accept-failover-exchange",
            body=body,
            result="ACCEPTED",
            details={"accepted_exchange": candidate.get("exchange"), "candidate_snapshot": candidate},
        )
    )
    return status


@router.post("/accept-failover-symbols")
async def accept_failover_symbols(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _FAILOVER_SYMBOLS_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    exchange_status = _read_failover_artifact(_FAILOVER_EXCHANGE_STATUS_FILE)
    if exchange_status.get("failover_exchange_operator_accepted") is not True:
        raise HTTPException(
            status_code=423,
            detail={"accepted": False, "reason": "FAILOVER_EXCHANGE_ACCEPTANCE_REQUIRED"},
        )
    proposed = _failover_proposed_symbols()
    symbols = [str(symbol).upper() for symbol in (body.get("symbols") or []) if str(symbol).strip()]
    if not symbols:
        raise HTTPException(status_code=422, detail={"accepted": False, "reason": "FAILOVER_SYMBOLS_REQUIRED"})
    outside = sorted(set(symbols) - proposed)
    if outside:
        raise HTTPException(
            status_code=422,
            detail={
                "accepted": False,
                "reason": "FAILOVER_SYMBOLS_NOT_SUBSET_OF_CURRENT_PROPOSAL",
                "invalid_symbols": outside,
                "proposed_symbols": sorted(proposed),
            },
        )
    audit_id = f"live_gate_failover_symbols_{uuid4().hex}"
    status = {
        "schema_version": "failover_symbol_acceptance_record_v1",
        "generated_est": _est_now(),
        "service_id": _FAILOVER_SERVICE_ID,
        "failover_symbol_operator_accepted": True,
        "accepted_exchange": exchange_status.get("accepted_exchange"),
        "accepted_failover_symbols": symbols,
        "accepted_at_est": _est_now(),
        "audit_id": audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "accepted_exchange_audit_id": exchange_status.get("audit_id"),
        "failover_live_enabled": False,
        "order_submission_allowed": False,
        "automatic_live_failover_allowed": False,
        "raw_credentials_exposed": False,
    }
    _write_failover_artifact(_FAILOVER_SYMBOL_STATUS_FILE, status)
    _append_failover_audit(
        _failover_audit_record(
            audit_id=audit_id,
            action="accept-failover-symbols",
            body=body,
            result="ACCEPTED",
            details={"accepted_exchange": exchange_status.get("accepted_exchange"), "accepted_failover_symbols": symbols},
        )
    )
    return status


@router.post("/failover-final-approval")
async def failover_final_approval(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_confirmation(body, _FAILOVER_FINAL_CONFIRMATION)
    operator_reason, source_payload_id = _require_reason_and_source(body)
    exchange_status = _read_failover_artifact(_FAILOVER_EXCHANGE_STATUS_FILE)
    symbol_status = _read_failover_artifact(_FAILOVER_SYMBOL_STATUS_FILE)
    if exchange_status.get("failover_exchange_operator_accepted") is not True:
        raise HTTPException(
            status_code=423,
            detail={"approved": False, "reason": "FAILOVER_EXCHANGE_ACCEPTANCE_REQUIRED"},
        )
    if symbol_status.get("failover_symbol_operator_accepted") is not True:
        raise HTTPException(
            status_code=423,
            detail={"approved": False, "reason": "FAILOVER_SYMBOL_ACCEPTANCE_REQUIRED"},
        )
    accepted_exchange_audit_id = str(body.get("accepted_failover_exchange_audit_id") or "")
    accepted_symbols_audit_id = str(body.get("accepted_failover_symbols_audit_id") or "")
    if accepted_exchange_audit_id != exchange_status.get("audit_id"):
        raise HTTPException(status_code=422, detail={"approved": False, "reason": "FAILOVER_EXCHANGE_AUDIT_ID_MISMATCH"})
    if accepted_symbols_audit_id != symbol_status.get("audit_id"):
        raise HTTPException(status_code=422, detail={"approved": False, "reason": "FAILOVER_SYMBOLS_AUDIT_ID_MISMATCH"})
    audit_id = f"live_gate_failover_final_{uuid4().hex}"
    status = {
        "schema_version": "failover_final_operator_approval_record_v1",
        "generated_est": _est_now(),
        "service_id": _FAILOVER_SERVICE_ID,
        "failover_final_operator_approval_present": True,
        "accepted_exchange": exchange_status.get("accepted_exchange"),
        "accepted_failover_symbols": symbol_status.get("accepted_failover_symbols", []),
        "final_approval_at_est": _est_now(),
        "audit_id": audit_id,
        "accepted_failover_exchange_audit_id": accepted_exchange_audit_id,
        "accepted_failover_symbols_audit_id": accepted_symbols_audit_id,
        "source_payload_id": source_payload_id,
        "operator_reason": operator_reason,
        "failover_live_enabled": False,
        "order_submission_allowed": False,
        "automatic_live_failover_allowed": False,
        "read_only_probe_required_before_transport_enable": True,
        "raw_credentials_exposed": False,
    }
    _write_failover_artifact(_FAILOVER_FINAL_STATUS_FILE, status)
    _append_failover_audit(
        _failover_audit_record(
            audit_id=audit_id,
            action="failover-final-approval",
            body=body,
            result="APPROVED",
            details={
                "accepted_exchange": exchange_status.get("accepted_exchange"),
                "accepted_failover_symbols": symbol_status.get("accepted_failover_symbols", []),
                "read_only_probe_required_before_transport_enable": True,
            },
        )
    )
    return status


@router.post("/enable")
async def enable_live_gate(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    before = _build_acceptance_state()
    payload = _status()
    blockers = _blockers(payload)
    available = _live_enable_available(payload, blockers)
    confirmation = body.get("typed_confirmation") or body.get("operator_confirmation_text")
    if confirmation != _TYPED_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail={
                "enabled": False,
                "reason": "TYPED_CONFIRMATION_REQUIRED",
                "typed_confirmation_required": _TYPED_CONFIRMATION,
            },
        )
    if blockers:
        audit_id = f"live_gate_enable_blocked_{uuid4().hex}"
        _append_audit(
            _audit_record(
                audit_id=audit_id,
                action="enable",
                body=body,
                result="LIVE_GATE_BLOCKED",
                before=before,
                after=before,
                details={"exact_blockers": blockers},
            )
        )
        _write_flow_outputs(_build_acceptance_state())
        raise HTTPException(
            status_code=423,
            detail={
                "enabled": False,
                "reason": "LIVE_GATE_BLOCKED",
                "exact_blockers": blockers,
                "audit_id": audit_id,
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    if not available:
        raise HTTPException(
            status_code=423,
            detail={
                "enabled": False,
                "reason": "LIVE_ENABLE_PATH_NOT_AVAILABLE",
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    accepted_symbols = payload.get("live_symbol_acceptance", {}).get("accepted_live_symbols", [])
    risk_status = payload.get("risk_profile_acceptance") if isinstance(payload.get("risk_profile_acceptance"), dict) else {}
    symbol_status = payload.get("live_symbol_acceptance") if isinstance(payload.get("live_symbol_acceptance"), dict) else {}
    final_status = payload.get("final_operator_approval") if isinstance(payload.get("final_operator_approval"), dict) else {}
    audit_id_mismatches: list[str] = []
    if body.get("accepted_risk_audit_id") and body.get("accepted_risk_audit_id") != risk_status.get("audit_id"):
        audit_id_mismatches.append("accepted_risk_audit_id")
    if body.get("accepted_symbols_audit_id") and body.get("accepted_symbols_audit_id") != symbol_status.get("audit_id"):
        audit_id_mismatches.append("accepted_symbols_audit_id")
    if body.get("final_approval_audit_id") and body.get("final_approval_audit_id") != final_status.get("audit_id"):
        audit_id_mismatches.append("final_approval_audit_id")
    missing_audit_ids = [
        field_name
        for field_name in ("accepted_risk_audit_id", "accepted_symbols_audit_id", "final_approval_audit_id")
        if not body.get(field_name)
    ]
    if missing_audit_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "enabled": False,
                "reason": "ENABLE_AUDIT_IDS_REQUIRED",
                "missing_fields": missing_audit_ids,
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    if audit_id_mismatches:
        raise HTTPException(
            status_code=422,
            detail={
                "enabled": False,
                "reason": "ENABLE_AUDIT_ID_MISMATCH",
                "mismatched_fields": audit_id_mismatches,
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    runtime_acceptance_blockers: list[str] = []
    risk_fields = risk_status.get("accepted_profile_fields")
    if risk_status.get("accepted_profile_name") not in _ALLOWED_RUNTIME_RISK_PROFILE_NAMES:
        runtime_acceptance_blockers.append("ACCEPTED_RISK_PROFILE_NOT_APPROVED_CONSERVATIVE_FAMILY")
    if not isinstance(risk_fields, dict):
        runtime_acceptance_blockers.append("ACCEPTED_RISK_FIELDS_MISSING")
        risk_fields = {}
    missing_risk_fields = [field for field in _REQUIRED_RUNTIME_RISK_FIELDS if field not in risk_fields]
    if missing_risk_fields:
        runtime_acceptance_blockers.extend(f"ACCEPTED_RISK_FIELD_MISSING:{field}" for field in missing_risk_fields)
    if risk_fields.get("max_leverage") != 1.0:
        runtime_acceptance_blockers.append("ACCEPTED_RISK_PROFILE_MAX_LEVERAGE_NOT_ONE")
    if sorted(str(symbol) for symbol in accepted_symbols) != sorted(
        str(symbol) for symbol in symbol_status.get("accepted_live_symbols", [])
    ):
        runtime_acceptance_blockers.append("ACCEPTED_SYMBOL_SET_MISMATCH")
    if runtime_acceptance_blockers:
        raise HTTPException(
            status_code=423,
            detail={
                "enabled": False,
                "reason": "RUNTIME_ENABLE_ACCEPTANCE_GUARDS_FAILED",
                "exact_blockers": sorted(set(runtime_acceptance_blockers)),
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    audit_id = f"live_gate_enable_{uuid4().hex}"
    source_payload_ids: list[str] = []
    for status_row in (risk_status, symbol_status, final_status):
        source_payload_id = status_row.get("source_payload_id") if isinstance(status_row, dict) else None
        if source_payload_id:
            source_payload_ids.append(str(source_payload_id))
    runtime_write = write_runtime_execution_state(
        repo_root=_repo_root(),
        accepted_symbols=[str(symbol) for symbol in accepted_symbols],
        risk_record=risk_status,
        symbol_record=symbol_status,
        final_record=final_status,
        enable_audit_id=audit_id,
        enabled_by=_actor(body),
        source_payload_ids=source_payload_ids,
    )
    if runtime_write.get("ok") is not True:
        _append_audit(
            _audit_record(
                audit_id=audit_id,
                action="enable",
                body=body,
                result="RUNTIME_MUTATION_FAILED",
                before=before,
                after=before,
                details={"runtime_write": runtime_write},
            )
        )
        enable_status_failed = {
            "schema_version": "live_enable_re_evaluation_status_v1",
            "generated_est": _est_now(),
            "service_id": _SERVICE_ID,
            "verdict": "LIVE_OPERATOR_ENABLE_RUNTIME_WRITE_FAILED",
            "go_no_go": _BLOCKED_MARKER,
            "requirements": payload.get("acceptance_requirements", {}),
            "exact_blockers": ["RUNTIME_EXECUTION_STATE_WRITE_FAILED"],
            "backend_live_enable_callable": True,
            "enabled": False,
            "reason": "RUNTIME_EXECUTION_STATE_WRITE_FAILED",
            "accepted_live_symbols_for_final_enable": accepted_symbols,
            "runtime_mutation_executed": False,
            "runtime_write": runtime_write,
            "audit_id": audit_id,
            "accepted_risk_audit_id": risk_status.get("audit_id"),
            "accepted_symbols_audit_id": symbol_status.get("audit_id"),
            "final_approval_audit_id": final_status.get("audit_id"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
        }
        _write_artifact(_ENABLE_STATUS_FILE, enable_status_failed)
        _write_flow_outputs(_build_acceptance_state())
        raise HTTPException(
            status_code=500,
            detail={
                "enabled": False,
                "reason": "RUNTIME_EXECUTION_STATE_WRITE_FAILED",
                "runtime_write": runtime_write,
                "audit_id": audit_id,
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
        )
    enable_status = {
        "schema_version": "live_enable_re_evaluation_status_v1",
        "generated_est": _est_now(),
        "service_id": _SERVICE_ID,
        "verdict": "LIVE_OPERATOR_ENABLE_AVAILABLE",
        "go_no_go": _READY_MARKER,
        "requirements": payload.get("acceptance_requirements", {}),
        "exact_blockers": [],
        "backend_live_enable_callable": True,
        "enabled": True,
        "reason": "LIVE_OPERATOR_ENABLE_RUNTIME_STATE_APPLIED",
        "accepted_live_symbols_for_final_enable": accepted_symbols,
        "runtime_mutation_executed": True,
        "requires_separate_runtime_execution_contract": False,
        "runtime_write": runtime_write,
        "audit_id": audit_id,
        "accepted_risk_audit_id": risk_status.get("audit_id"),
        "accepted_symbols_audit_id": symbol_status.get("audit_id"),
        "final_approval_audit_id": final_status.get("audit_id"),
        "live_gate": LIVE_GATE_ENABLED,
        "live_symbols": accepted_symbols,
        "execution_live_symbols": accepted_symbols,
        "trader_execution_enabled": True,
    }
    _write_artifact(_ENABLE_STATUS_FILE, enable_status)
    after = _build_acceptance_state()
    _append_audit(
        _audit_record(
            audit_id=audit_id,
                action="enable",
                body=body,
                result="LIVE_OPERATOR_ENABLE_RUNTIME_STATE_APPLIED",
                before=before,
                after=after,
                details={"accepted_live_symbols_for_final_enable": accepted_symbols, "runtime_write": runtime_write},
            )
    )
    _write_flow_outputs(_build_acceptance_state())
    return {
        "enabled": True,
        "reason": "LIVE_OPERATOR_ENABLE_RUNTIME_STATE_APPLIED",
        "backend_live_enable_path_available": True,
        "runtime_mutation_executed": True,
        "requires_separate_runtime_execution_contract": False,
        "audit_id": audit_id,
        "accepted_risk_audit_id": risk_status.get("audit_id"),
        "accepted_symbols_audit_id": symbol_status.get("audit_id"),
        "final_approval_audit_id": final_status.get("audit_id"),
        "accepted_live_symbols_for_final_enable": accepted_symbols,
        "runtime_write": runtime_write,
        "live_gate": LIVE_GATE_ENABLED,
        "live_symbols": accepted_symbols,
        "execution_live_symbols": accepted_symbols,
        "trader_execution_enabled": True,
    }
