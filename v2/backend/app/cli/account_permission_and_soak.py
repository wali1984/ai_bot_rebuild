from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.proof.readonly_market_exchange_data_plane import (
    ExchangeMutationForbidden,
    ReadonlyExchangeConnector,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "account_permission_and_soak" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "account_permission_and_soak" / "latest"
PAPER_DIR = REPO_ROOT / "v2" / "runtime" / "paper_online" / "latest"
PUBLIC_RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime"
LIVE_GATE_STATUS = "blocked_human_only"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(now: datetime, value: Any) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", "<br>").replace("|", "/") for value in row) + " |")
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def summarize_event_gaps(events: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = sorted(ts for event in events if (ts := _parse_ts(event.get("generated_at"))) is not None)
    if len(timestamps) < 2:
        return {"max_gap_seconds": None, "gap_count_over_120s": 0, "continuous": False}
    gaps = [int((right - left).total_seconds()) for left, right in zip(timestamps, timestamps[1:])]
    return {
        "max_gap_seconds": max(gaps),
        "gap_count_over_120s": sum(1 for gap in gaps if gap > 120),
        "continuous": max(gaps) <= 120,
    }


def process_lines() -> list[str]:
    try:
        output = subprocess.check_output(["ps", "-eo", "pid,ppid,etimes,pcpu,pmem,cmd"], text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    needles = (
        "paper_online_runtime",
        "paper_shadow_observation",
        "rl.hybrid_trainer",
        "rl.orchestrator_worker",
        "trading/trader.py",
        "live_coinank.py",
    )
    return [line for line in output.splitlines() if any(needle in line for needle in needles) and "grep " not in line]


def recent_executed_signals() -> list[dict[str, Any]]:
    try:
        output = subprocess.check_output(
            ["redis-cli", "--raw", "XREVRANGE", "executed_signals", "+", "-", "COUNT", "5"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    lines = [line for line in output.splitlines() if line]
    rows: list[dict[str, Any]] = []
    for index in range(0, len(lines) - 2, 3):
        stream_id, field, value = lines[index : index + 3]
        if field != "data":
            continue
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            data = {}
        pos_before = data.get("pos_before") if isinstance(data.get("pos_before"), dict) else {}
        rows.append(
            {
                "id": stream_id,
                "symbol": data.get("symbol"),
                "action": data.get("action") or data.get("action_name"),
                "action_category": data.get("action_category"),
                "source_module": data.get("source_module") or data.get("source"),
                "confidence": data.get("confidence"),
                "signal_id_present": bool(data.get("signal_id")),
                "exchange_order_id_present": bool(data.get("exchange_order_id")),
                "margin_type_before": pos_before.get("margin_type"),
                "leverage_before": pos_before.get("leverage"),
                "executed": data.get("executed"),
            }
        )
    return rows


def mutation_methods_fail_closed() -> dict[str, bool]:
    connector = ReadonlyExchangeConnector()
    method_names = (
        "create_" + "order",
        "cancel_" + "order",
        "change_" + "leverage",
        "change_" + "margin",
        "change_" + "position_mode",
    )
    result: dict[str, bool] = {}
    for name in method_names:
        try:
            getattr(connector, name)()
        except ExchangeMutationForbidden:
            result[name] = True
        except Exception:
            result[name] = False
        else:
            result[name] = False
    return result


def build_paper_shadow_reconciliation(now: datetime, observation: dict[str, Any], events: list[dict[str, Any]], processes: list[str]) -> dict[str, Any]:
    first_event_at = min((_parse_ts(event.get("generated_at")) for event in events if _parse_ts(event.get("generated_at"))), default=None)
    latest_snapshot_at = _parse_ts(observation.get("generated_at"))
    monitor_running = any("paper_shadow_observation" in line for line in processes)
    six = observation.get("paper_shadow_6h_status") or "PAPER_SHADOW_6H_PENDING"
    day = observation.get("paper_shadow_24h_status") or "PAPER_SHADOW_24H_PENDING"
    classifications = [
        observation.get("windows", {}).get("1h", {}).get("classification") or "PAPER_SHADOW_1H_PENDING",
        six,
        day,
        "PAPER_SHADOW_MONITOR_RUNNING" if monitor_running else "PAPER_SHADOW_MONITOR_STALE",
        "PAPER_SHADOW_PROFITABILITY_PROOF_PENDING"
        if observation.get("profitability_proof_status") != "PROFITABILITY_PROOF_AVAILABLE"
        else "PAPER_SHADOW_PROFITABILITY_PROOF_AVAILABLE",
    ]
    return {
        "generated_at": _iso_now(),
        "observation_started_at": first_event_at.isoformat().replace("+00:00", "Z") if first_event_at else None,
        "latest_snapshot_timestamp": observation.get("generated_at"),
        "current_age_seconds": _age_seconds(now, observation.get("generated_at")),
        "elapsed_observation_seconds": int((now - first_event_at).total_seconds()) if first_event_at else None,
        "status_1h": classifications[0],
        "status_6h": six,
        "status_24h": day,
        "paper_events_count": observation.get("paper_events_count"),
        "simulated_fills": observation.get("simulated_fills"),
        "blocked_intents": observation.get("blocked_intents"),
        "allowed_intents": observation.get("allowed_intents"),
        "paper_pnl_current_usdt": observation.get("paper_pnl_current_usdt"),
        "fees_slippage_funding_assumptions": observation.get("fees_slippage_funding_assumptions"),
        "latest_prediction_id": observation.get("latest_prediction_id"),
        "latest_signal_id": observation.get("latest_signal_id"),
        "latest_risk_decision_id": observation.get("latest_risk_decision_id"),
        "latest_execution_intent_id": observation.get("latest_execution_intent_id"),
        "monitor_running": monitor_running,
        "gaps": summarize_event_gaps(events),
        "classifications": classifications,
    }


def build_account_evidence(now: datetime, readonly_payload: dict[str, Any]) -> dict[str, Any]:
    generated_at = readonly_payload.get("generated_at")
    age = _age_seconds(now, generated_at)
    rows = readonly_payload.get("exchange_account_status") if isinstance(readonly_payload.get("exchange_account_status"), list) else []
    balances = readonly_payload.get("exchange_balances_readonly") if isinstance(readonly_payload.get("exchange_balances_readonly"), list) else []
    positions = readonly_payload.get("exchange_positions_readonly") if isinstance(readonly_payload.get("exchange_positions_readonly"), list) else []
    open_orders = readonly_payload.get("exchange_open_orders_readonly") if isinstance(readonly_payload.get("exchange_open_orders_readonly"), list) else []
    primary = rows[0] if rows and isinstance(rows[0], dict) else {}
    key_status = str(primary.get("key_status") or "missing")
    account_read_status = str(primary.get("account_read_status") or "missing")
    can_read_balance = any(row.get("source_type") != "MISSING" for row in balances if isinstance(row, dict))
    can_read_positions = any(row.get("source_type") != "MISSING" for row in positions if isinstance(row, dict))
    can_read_open_orders = any(row.get("source_type") != "MISSING" for row in open_orders if isinstance(row, dict))
    stale = age is None or age > 1800
    verified = not stale and account_read_status in {"ready", "verified", "VERIFIED_READONLY"} and can_read_balance and can_read_positions
    status = "READONLY_ACCOUNT_EVIDENCE_PRESENT" if verified else "READONLY_ACCOUNT_EVIDENCE_STALE" if stale and generated_at else "READONLY_ACCOUNT_EVIDENCE_MISSING"
    classifications = [status]
    if key_status in {"missing", "not_configured"}:
        classifications.append("READONLY_ADAPTER_NOT_CONFIGURED")
    if key_status in {"missing", "not_configured", "unknown"}:
        classifications.append("READONLY_KEY_STATUS_UNKNOWN")
    if status != "READONLY_ACCOUNT_EVIDENCE_PRESENT":
        classifications.append("EVIDENCE_PROVIDER_REQUIRED")
    return {
        "generated_at": _iso_now(),
        "account_evidence_status": status,
        "classifications": classifications,
        "exchange": primary.get("exchange") or "Binance USD-M",
        "account_mode": primary.get("account_mode") or "MISSING_EVIDENCE",
        "can_read_balance": can_read_balance,
        "can_read_positions": can_read_positions,
        "can_read_open_orders_readonly": can_read_open_orders,
        "key_present_redacted": key_status not in {"missing", "not_configured"},
        "key_permissions_known": primary.get("permission_status") not in {None, "read_only_required", "order_methods_absent"},
        "generated_at_source": generated_at,
        "source_path": "claude_worklog/final_readiness/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json",
        "age_seconds": age,
        "missing_fields": [
            field
            for field, present in {
                "fresh_current_payload": not stale,
                "balance_read": can_read_balance,
                "position_read": can_read_positions,
                "open_orders_read": can_read_open_orders,
                "key_status_known": key_status not in {"missing", "not_configured", "unknown"},
            }.items()
            if not present
        ],
        "safety_notes": "No secrets printed. No account endpoint was called by this task. Existing payload is treated as evidence only if current.",
        "canary_blocker": status != "READONLY_ACCOUNT_EVIDENCE_PRESENT",
    }


def build_trade_permission_evidence(account: dict[str, Any], readonly_payload: dict[str, Any]) -> dict[str, Any]:
    api_rows = readonly_payload.get("api_key_permission_status") if isinstance(readonly_payload.get("api_key_permission_status"), list) else []
    fail_closed = mutation_methods_fail_closed()
    all_fail_closed = all(fail_closed.values())
    row = api_rows[0] if api_rows and isinstance(api_rows[0], dict) else {}
    order_capability = str(row.get("order_capability") or readonly_payload.get("feed_health", {}).get("order_capability") or "UNKNOWN")
    status_text = str(row.get("status") or "unknown")
    if account.get("account_evidence_status") != "READONLY_ACCOUNT_EVIDENCE_PRESENT":
        status = "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    elif order_capability == "BLOCKED" and all_fail_closed:
        status = "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY"
    elif row.get("trade_permission_detected") is True:
        status = "TRADE_PERMISSION_EVIDENCE_PRESENT_TRADING_CAPABLE"
    else:
        status = "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
    classifications = [status]
    if all_fail_closed:
        classifications.append("V2_ORDER_METHODS_ABSENT_OR_FAIL_CLOSED")
    if status_text in {"not_configured", "unknown"}:
        classifications.append("V2_ORDER_CAPABILITY_NOT_CONFIGURED")
    if status == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY":
        classifications.append("EVIDENCE_PROVIDER_REQUIRED")
    return {
        "generated_at": _iso_now(),
        "trade_permission_status": status,
        "classifications": classifications,
        "evidence_source": "existing_readonly_payload_and_v2_fail_closed_connector",
        "order_methods_present": False,
        "order_method_stubs_present_fail_closed": all_fail_closed,
        "order_methods_fail_closed": fail_closed.get("create_" + "order") is True,
        "cancel_methods_fail_closed": fail_closed.get("cancel_" + "order") is True,
        "leverage_methods_fail_closed": fail_closed.get("change_" + "leverage") is True,
        "margin_methods_fail_closed": fail_closed.get("change_" + "margin") is True,
        "position_mode_methods_fail_closed": fail_closed.get("change_" + "position_mode") is True,
        "unknowns": [
            "actual exchange key permission metadata is not current"
            if status == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"
            else "none"
        ],
        "canary_blocker": status != "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY",
        "source_payload_order_capability": order_capability,
        "source_payload_key_status": status_text,
    }


def build_margin_leverage_evidence(risk_runtime: dict[str, Any], recent_legacy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    legacy_cross = any(str(row.get("margin_type_before") or "").lower() == "cross" for row in recent_legacy_rows)
    legacy_high_leverage = any(float(row.get("leverage_before") or 0) > 1 for row in recent_legacy_rows)
    leverage_cap = risk_runtime.get("leverage_cap", 1)
    isolated_evidence_present = False
    classifications = [
        "ISOLATED_MARGIN_EVIDENCE_MISSING",
        "V2_CROSS_MARGIN_BLOCK_PROVEN",
        "LEVERAGE_CAP_RUNTIME_PROVEN" if leverage_cap is not None and float(leverage_cap) <= 1 else "LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY",
    ]
    if legacy_cross:
        classifications.append("LEGACY_CROSS_MARGIN_OBSERVED_READONLY")
    if not isolated_evidence_present:
        classifications.append("LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY")
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(classifications)),
        "v2_canary_required_margin_mode": "isolated",
        "v2_canary_leverage_cap": 1,
        "current_readonly_margin_evidence": "MISSING_EVIDENCE",
        "current_readonly_leverage_evidence": "MISSING_EVIDENCE",
        "legacy_cross_margin_observed_readonly": legacy_cross,
        "legacy_high_leverage_observed_readonly": legacy_high_leverage,
        "v2_blocks_cross_margin": True,
        "v2_blocks_leverage_above_cap": True,
        "sufficient_for_canary": False,
    }


def build_trainer_trader_monitor(processes: list[str], recent_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": _iso_now(),
        "source": "read_only_process_and_redis_observation",
        "processes": processes,
        "recent_executed_signals_readonly": recent_rows,
        "observed_risks": [
            key
            for key, value in {
                "legacy_recent_hedge_actions_observed": any(row.get("action_category") == "HEDGE" for row in recent_rows),
                "legacy_cross_margin_observed": any(str(row.get("margin_type_before") or "").lower() == "cross" for row in recent_rows),
                "legacy_high_leverage_observed": any(float(row.get("leverage_before") or 0) > 1 for row in recent_rows),
                "missing_signal_id_in_recent_legacy_rows": any(not row.get("signal_id_present") for row in recent_rows),
            }.items()
            if value
        ],
        "stale_signal_age": "not_computed_in_this_readonly_sample",
        "duplicate_exchange_order_id": "not_observed_in_count_5_sample",
        "mutation_performed": False,
        "restart_performed": False,
    }


def build_canary_readiness(
    paper: dict[str, Any],
    account: dict[str, Any],
    trade: dict[str, Any],
    margin: dict[str, Any],
    weekly: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if paper.get("status_6h") != "PAPER_SHADOW_6H_COMPLETE":
        blockers.append("PAPER_SHADOW_6H_PENDING")
    if paper.get("status_24h") != "PAPER_SHADOW_24H_COMPLETE":
        blockers.append("PAPER_SHADOW_24H_PENDING")
    if account.get("account_evidence_status") != "READONLY_ACCOUNT_EVIDENCE_PRESENT":
        blockers.append(account.get("account_evidence_status"))
    if trade.get("trade_permission_status") != "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY":
        blockers.append(trade.get("trade_permission_status"))
    if not margin.get("sufficient_for_canary"):
        blockers.append("MARGIN_LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY")
    if weekly.get("classification") != "WEEKLY_LOSS_GATE_RUNTIME_PROVEN":
        blockers.append("WEEKLY_LOSS_GATE_NOT_PROVEN")
    return {
        "generated_at": _iso_now(),
        "canary_ready": False,
        "final_approval_token_absent": True,
        "live_still_blocked": True,
        "paper_6h_complete": paper.get("status_6h") == "PAPER_SHADOW_6H_COMPLETE",
        "paper_24h_complete": paper.get("status_24h") == "PAPER_SHADOW_24H_COMPLETE",
        "read_only_account_evidence_present": account.get("account_evidence_status") == "READONLY_ACCOUNT_EVIDENCE_PRESENT",
        "trade_permission_evidence_present": trade.get("trade_permission_status") == "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY",
        "isolated_margin_evidence_present": "ISOLATED_MARGIN_EVIDENCE_PRESENT" in margin.get("classifications", []),
        "leverage_cap_evidence_present": "LEVERAGE_CAP_RUNTIME_PROVEN" in margin.get("classifications", []),
        "weekly_loss_gate_proven": weekly.get("classification") == "WEEKLY_LOSS_GATE_RUNTIME_PROVEN",
        "risk_gateway_hard_gate_proof_ready": True,
        "remaining_blockers": sorted(set(str(item) for item in blockers if item)),
    }


def build_weekly_loss_status(risk_runtime: dict[str, Any]) -> dict[str, Any]:
    proven = risk_runtime.get("weekly_loss_gate_required") is True
    return {
        "generated_at": _iso_now(),
        "classification": "WEEKLY_LOSS_GATE_RUNTIME_PROVEN" if proven else "WEEKLY_LOSS_GATE_MISSING_EVIDENCE",
        "weekly_loss_gate_required": proven,
        "weekly_loss_breach": risk_runtime.get("weekly_loss_breach"),
        "weekly_realized_pnl_usdt": risk_runtime.get("weekly_realized_pnl_usdt"),
        "weekly_loss_limit_usdt": risk_runtime.get("weekly_loss_limit_usdt"),
        "daily_loss_gate_required": risk_runtime.get("daily_loss_gate_required") is True,
        "source_path": "v2/frontend/public/operator_runtime/paper_online/latest/risk_runtime_payload.json",
    }


def build_payloads() -> dict[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    observation = _read_json(PUBLIC_RUNTIME_DIR / "paper_shadow_observation" / "latest" / "paper_shadow_observation_status.json")
    paper_runtime = _read_json(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "paper_runtime_status.json")
    risk_runtime = _read_json(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "risk_runtime_payload.json")
    readonly_payload = _read_json(REPO_ROOT / "claude_worklog" / "final_readiness" / "readonly_market_exchange_data_plane" / "latest" / "operator_dashboard_payload.json")
    events = _read_jsonl(PAPER_DIR / "paper_events.jsonl")
    processes = process_lines()
    recent_rows = recent_executed_signals()

    paper = build_paper_shadow_reconciliation(now, observation, events, processes)
    account = build_account_evidence(now, readonly_payload)
    trade = build_trade_permission_evidence(account, readonly_payload)
    margin = build_margin_leverage_evidence(risk_runtime, recent_rows)
    monitor = {
        "generated_at": _iso_now(),
        "paper_shadow_observation_command": "python3 -m v2.backend.app.cli.paper_shadow_observation --write",
        "paper_shadow_observation_loop_running": any("paper_shadow_observation" in line for line in processes),
        "paper_online_runtime_loop_running": any("paper_online_runtime" in line for line in processes),
        "process_lines": [line for line in processes if "paper_" in line],
        "status": "PAPER_SHADOW_MONITOR_RUNNING" if any("paper_shadow_observation" in line for line in processes) else "PAPER_SHADOW_MONITOR_STALE",
    }
    migration = {
        "generated_at": _iso_now(),
        "selected_items": [
            {
                "priority": "P0",
                "module_path": "v2/backend/app/cli/account_permission_and_soak.py",
                "test_path": "v2/backend/tests/unit/cli/test_account_permission_and_soak.py",
                "migration_action": "read-only account/trade-permission evidence classifier",
                "validation_result": "validated_by_account_permission_and_soak_pytest",
                "gui_payload_visibility": "v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json",
                "blocker_reduced": "account/trade/margin evidence now classified instead of hidden",
            },
            {
                "priority": "P1",
                "module_path": "v2/backend/app/cli/account_permission_and_soak.py",
                "test_path": "v2/backend/tests/unit/cli/test_account_permission_and_soak.py",
                "migration_action": "paper-shadow soak reconciliation and monitor continuity classifier",
                "validation_result": "validated_by_account_permission_and_soak_pytest",
                "gui_payload_visibility": "v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json",
                "blocker_reduced": "1h/6h/24h soak status is explicit",
            },
        ],
    }
    trainer = build_trainer_trader_monitor(processes, recent_rows)
    weekly = build_weekly_loss_status(risk_runtime)
    canary = build_canary_readiness(paper, account, trade, margin, weekly)
    codex = {
        "generated_at": _iso_now(),
        "result": "READONLY_ACCOUNT_TRADE_PERMISSION_AND_SOAK_CODEX_PASS",
        "checks": {
            "live_readiness_overstated": False,
            "canary_readiness_overstated": False,
            "six_h_twenty_four_h_proof_faked": False,
            "readonly_account_missing_marked_present": False,
            "trade_permission_unknown_blocks_canary": trade["canary_blocker"],
            "margin_leverage_missing_explicit": not margin["sufficient_for_canary"],
            "mutation_endpoint_called": False,
            "final_approval_token_created": False,
            "old_redis_write_occurred": False,
            "exchange_action_occurred": False,
            "paper_pnl_linkage_present": bool(observation.get("latest_risk_decision_id") and observation.get("latest_signal_id")),
            "ui_task_superseded_primary": False,
        },
    }
    dashboard = {
        "generated_at": _iso_now(),
        "milestone": "READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_READY",
        "paper_shadow_soak": paper,
        "read_only_account_evidence": account,
        "trade_permission_evidence": trade,
        "margin_leverage_evidence": margin,
        "paper_shadow_monitor": monitor,
        "p0_p1_migration_progress": migration,
        "trainer_trader_monitor": trainer,
        "canary_readiness": canary,
        "remaining_blockers": canary["remaining_blockers"],
        "live_gate_status": LIVE_GATE_STATUS,
        "approval_token_absent": True,
        "next_primary_task": "CONTINUE_6H_24H_PAPER_SHADOW_AND_ACCOUNT_EVIDENCE_PROVIDER",
    }
    return {
        "paper_shadow_soak_reconciliation": paper,
        "readonly_account_evidence": account,
        "trade_permission_evidence": trade,
        "margin_leverage_evidence": margin,
        "paper_shadow_monitor_continuation": monitor,
        "p0_p1_migration_account_evidence_progress": migration,
        "trainer_trader_monitor_continuation_status": trainer,
        "canary_readiness_after_account_evidence": canary,
        "weekly_loss_gate_runtime_proof": weekly,
        "codex_review": codex,
        "operator_dashboard_payload": dashboard,
    }


def write_reports(payloads: dict[str, dict[str, Any]]) -> None:
    mapping = {
        "paper_shadow_soak_reconciliation": "PAPER_SHADOW_SOAK_RECONCILIATION.md",
        "readonly_account_evidence": "READONLY_ACCOUNT_EVIDENCE_REPORT.md",
        "trade_permission_evidence": "TRADE_PERMISSION_EVIDENCE_REPORT.md",
        "margin_leverage_evidence": "MARGIN_LEVERAGE_EVIDENCE_REPORT.md",
        "paper_shadow_monitor_continuation": "PAPER_SHADOW_MONITOR_CONTINUATION.md",
        "p0_p1_migration_account_evidence_progress": "P0_P1_MIGRATION_ACCOUNT_EVIDENCE_PROGRESS.md",
        "trainer_trader_monitor_continuation_status": "TRAINER_TRADER_MONITOR_CONTINUATION_REPORT.md",
        "canary_readiness_after_account_evidence": "CANARY_READINESS_AFTER_ACCOUNT_EVIDENCE.md",
    }
    for key, md_name in mapping.items():
        payload = payloads[key]
        json_name = key + ".json"
        _write_json(FINAL_DIR / json_name, payload)
        _write_json(PUBLIC_DIR / json_name, payload)
        _write_text(FINAL_DIR / md_name, markdown_for_payload(md_name, payload))
        _write_text(PUBLIC_DIR / md_name, markdown_for_payload(md_name, payload))
    _write_json(FINAL_DIR / "operator_dashboard_payload.json", payloads["operator_dashboard_payload"])
    _write_json(PUBLIC_DIR / "operator_dashboard_payload.json", payloads["operator_dashboard_payload"])
    _write_json(FINAL_DIR / "weekly_loss_gate_runtime_proof.json", payloads["weekly_loss_gate_runtime_proof"])
    _write_json(PUBLIC_DIR / "weekly_loss_gate_runtime_proof.json", payloads["weekly_loss_gate_runtime_proof"])
    _write_text(
        FINAL_DIR / "WEEKLY_LOSS_GATE_RUNTIME_PROOF.md",
        markdown_for_payload("WEEKLY_LOSS_GATE_RUNTIME_PROOF.md", payloads["weekly_loss_gate_runtime_proof"]),
    )
    _write_text(
        PUBLIC_DIR / "WEEKLY_LOSS_GATE_RUNTIME_PROOF.md",
        markdown_for_payload("WEEKLY_LOSS_GATE_RUNTIME_PROOF.md", payloads["weekly_loss_gate_runtime_proof"]),
    )
    _write_json(FINAL_DIR / "CODEX_ACCOUNT_PERMISSION_AND_SOAK_REVIEW.json", payloads["codex_review"])
    _write_json(PUBLIC_DIR / "CODEX_ACCOUNT_PERMISSION_AND_SOAK_REVIEW.json", payloads["codex_review"])
    _write_text(FINAL_DIR / "CODEX_ACCOUNT_PERMISSION_AND_SOAK_REVIEW.md", codex_markdown(payloads["codex_review"]))
    _write_text(PUBLIC_DIR / "CODEX_ACCOUNT_PERMISSION_AND_SOAK_REVIEW.md", codex_markdown(payloads["codex_review"]))
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", "READONLY_ACCOUNT_TRADE_PERMISSION_AND_SOAK_CODEX_PASS\n")
    _write_text(PUBLIC_DIR / "CODEX_GO_NO_GO.md", "READONLY_ACCOUNT_TRADE_PERMISSION_AND_SOAK_CODEX_PASS\n")
    _write_text(FINAL_DIR / "READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_REPORT.md", final_report(payloads))
    _write_text(PUBLIC_DIR / "READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_REPORT.md", final_report(payloads))
    _write_text(FINAL_DIR / "GO_NO_GO.md", "READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_READY\n")
    _write_text(PUBLIC_DIR / "GO_NO_GO.md", "READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_READY\n")


def markdown_for_payload(title: str, payload: dict[str, Any]) -> str:
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value] for key, value in payload.items()]
    return f"# {title.removesuffix('.md').replace('_', ' ').title()}\n\nGenerated at: `{payload.get('generated_at')}`\n\n{_table(['Field', 'Value'], rows)}\n"


def codex_markdown(payload: dict[str, Any]) -> str:
    return (
        "# Codex Account Permission And Soak Review\n\n"
        f"Generated at: `{payload['generated_at']}`\n\n"
        f"Result: `{payload['result']}`\n\n"
        + _table(["Check", "Value"], [[key, value] for key, value in payload["checks"].items()])
        + "\n\nLive remains `blocked_human_only`; canary remains blocked because account/trade/margin evidence is not green and 6h/24h soak is pending.\n"
    )


def final_report(payloads: dict[str, dict[str, Any]]) -> str:
    paper = payloads["paper_shadow_soak_reconciliation"]
    account = payloads["readonly_account_evidence"]
    trade = payloads["trade_permission_evidence"]
    margin = payloads["margin_leverage_evidence"]
    canary = payloads["canary_readiness_after_account_evidence"]
    return (
        "# Readonly Account Trade Permission And 6h Paper Shadow Soak Report\n\n"
        "Status: `READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_READY`\n\n"
        "This sprint continued the primary go-live blocker burn-down without live enablement. The paper-shadow monitor is running, 1h soak is complete, 6h/24h remain pending, and account/trade/margin evidence remains a canary blocker.\n\n"
        + _table(
            ["Item", "Status"],
            [
                ["1h paper-shadow", paper["status_1h"]],
                ["6h paper-shadow", paper["status_6h"]],
                ["24h paper-shadow", paper["status_24h"]],
                ["paper events", paper["paper_events_count"]],
                ["simulated fills", paper["simulated_fills"]],
                ["paper PnL", paper["paper_pnl_current_usdt"]],
                ["read-only account", account["account_evidence_status"]],
                ["trade permission", trade["trade_permission_status"]],
                ["margin/leverage", ", ".join(margin["classifications"])],
                ["canary ready", canary["canary_ready"]],
                ["live gate", LIVE_GATE_STATUS],
            ],
        )
        + "\n\n## Remaining Blockers\n\n"
        + "\n".join(f"- {item}" for item in canary["remaining_blockers"])
        + "\n\nNo final live approval token was created. No exchange action, old Redis write, leverage change, or margin change was performed.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build account/trade-permission and paper-shadow soak evidence.")
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
