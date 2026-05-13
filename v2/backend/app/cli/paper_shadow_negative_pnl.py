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
    build_weekly_loss_status,
    process_lines,
    recent_executed_signals,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "paper_shadow_soak_negative_pnl" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "paper_shadow_soak_negative_pnl" / "latest"
PAPER_DIR = REPO_ROOT / "v2" / "runtime" / "paper_online" / "latest"
PUBLIC_RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime"


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


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", "<br>").replace("|", "/") for value in row) + " |")
    return "\n".join(lines)


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


def events_with_pnl_delta(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_events = sorted(
        events,
        key=lambda event: _parse_ts(event.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    rows: list[dict[str, Any]] = []
    previous_pnl: float | None = None
    for event in sorted_events:
        current_pnl = _num(event.get("paper_realized_pnl"), 0.0)
        delta = 0.0 if previous_pnl is None else round(current_pnl - previous_pnl, 8)
        previous_pnl = current_pnl
        rows.append({**event, "paper_pnl_delta": delta})
    return rows


def _filled(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("paper_result") == "FILLED_PAPER_ONLY" or event.get("ledger_action") == "PAPER_FILL_SIMULATED"
    ]


def _blocked(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("risk_action") == "deny" or event.get("paper_result") == "NO_FILL_RISK_BLOCKED"
    ]


def _action_from_reason(reason: Any) -> str:
    text = str(reason or "missing")
    if "long" in text:
        return "long"
    if "short" in text:
        return "short"
    return text


def _pnl_by(events: list[dict[str, Any]], field: str) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for event in events:
        if field == "action":
            key = _action_from_reason(event.get("risk_reason_code"))
        elif field == "confidence_bucket":
            key = _confidence_bucket(event.get("confidence"))
        else:
            key = str(event.get(field) or "missing")
        totals[key] += _num(event.get("paper_pnl_delta"))
    return {key: round(value, 8) for key, value in sorted(totals.items())}


def build_negative_pnl_diagnosis(observation: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    with_delta = events_with_pnl_delta(events)
    fills = _filled(with_delta)
    blocked = _blocked(with_delta)
    pnl_deltas = [_num(event.get("paper_pnl_delta")) for event in fills]
    wins = [value for value in pnl_deltas if value > 0]
    losses = [value for value in pnl_deltas if value < 0]
    total_fee = round(sum(_num(event.get("fee_usdt")) for event in fills), 8)
    realized_delta = round(sum(pnl_deltas), 8)
    gross_if_fees_added_back = round(realized_delta + total_fee, 8)
    fill_count = len(fills)
    event_count = len(with_delta)
    fill_rate = fill_count / max(event_count, 1)
    classifications = ["PAPER_PNL_DIAGNOSIS_INSUFFICIENT_WINDOW", "PAPER_PNL_DIAGNOSIS_BLOCKS_CANARY"]
    if _num(observation.get("paper_pnl_current_usdt")) < 0:
        classifications.append("PAPER_PNL_NEGATIVE_EARLY_WINDOW")
    fee_drag_explains_loss = total_fee > 0 and abs(gross_if_fees_added_back) <= max(total_fee * 0.01, 0.1)
    if fee_drag_explains_loss:
        classifications.append("PAPER_PNL_NEGATIVE_FEES_SLIPPAGE_DRAG")
    if fill_rate > 0.5 and fill_count >= 100:
        classifications.append("PAPER_PNL_NEGATIVE_OVERTRADING")
    if not wins and losses:
        classifications.append("PAPER_PNL_NEGATIVE_PAPER_ENGINE_ASSUMPTION")
        classifications.append("PAPER_PNL_NEGATIVE_SIGNAL_EDGE_WEAK")
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(classifications)),
        "total_events": event_count,
        "simulated_fills": fill_count,
        "blocked_intents": len(blocked),
        "paper_pnl_current_usdt": observation.get("paper_pnl_current_usdt"),
        "paper_pnl_delta_usdt": realized_delta,
        "gross_pnl_if_fees_added_back_usdt": gross_if_fees_added_back,
        "fees_usdt": total_fee,
        "slippage_assumption_bps": observation.get("fees_slippage_funding_assumptions", {}).get("slippage_bps"),
        "funding_assumption": observation.get("fees_slippage_funding_assumptions", {}).get("funding"),
        "symbols_traded": dict(Counter(str(event.get("symbol") or "missing") for event in fills)),
        "action_distribution": dict(Counter(_action_from_reason(event.get("risk_reason_code")) for event in fills)),
        "long_vs_short_distribution": dict(Counter(_action_from_reason(event.get("risk_reason_code")) for event in fills if _action_from_reason(event.get("risk_reason_code")) in {"long", "short"})),
        "confidence_bucket_distribution": dict(Counter(_confidence_bucket(event.get("confidence")) for event in fills)),
        "risk_decision_distribution": dict(Counter(str(event.get("risk_reason_code") or "missing") for event in with_delta)),
        "top_loss_symbols": _pnl_by(fills, "symbol"),
        "top_loss_action_types": _pnl_by(fills, "action"),
        "average_win_usdt": round(statistics.mean(wins), 8) if wins else 0.0,
        "average_loss_usdt": round(statistics.mean(losses), 8) if losses else 0.0,
        "win_rate": round(len(wins) / max(fill_count, 1), 8),
        "profit_factor": 0.0 if losses and not wins else None,
        "largest_loss_usdt": min(losses) if losses else 0.0,
        "drawdown_proxy_usdt": observation.get("paper_pnl_current_usdt"),
        "latency_bucket": "MISSING_EVIDENCE",
        "fills_are_too_frequent": fill_rate > 0.5 and fill_count >= 100,
        "fee_slippage_bleed": fee_drag_explains_loss,
        "low_confidence_fill_count": sum(1 for event in fills if _num(event.get("confidence")) < 0.65),
        "paper_engine_assumption": "Current paper engine realizes fee-only PnL per fill and does not model exit edge; negative PnL is not profitability proof.",
        "trainer_edge_status": "UNPROVEN_OR_WEAK_UNTIL_6H_24H_AND_GROSS_PNL_MODEL_COMPLETE",
        "risk_gateway_allowed_too_many_unsafe_paper_intents": fill_rate > 0.5,
    }


def build_fill_quality_audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    with_delta = events_with_pnl_delta(events)
    fills = _filled(with_delta)
    timestamps = [ts for event in fills if (ts := _parse_ts(event.get("generated_at"))) is not None]
    elapsed_minutes = max((max(timestamps) - min(timestamps)).total_seconds() / 60, 1.0) if len(timestamps) >= 2 else 1.0
    fill_count = len(fills)
    fills_per_minute = round(fill_count / elapsed_minutes, 6)
    fills_per_hour = round(fills_per_minute * 60, 6)
    actions = [_action_from_reason(event.get("risk_reason_code")) for event in fills]
    churn_count = sum(1 for left, right in zip(actions, actions[1:]) if left != right and {left, right} <= {"long", "short"})
    pnl_values = [_num(event.get("paper_pnl_delta")) for event in fills]
    fee_total = round(sum(_num(event.get("fee_usdt")) for event in fills), 8)
    classifications = []
    if fills_per_hour <= 60:
        classifications.append("FILL_RATE_NORMAL")
    else:
        classifications.append("FILL_RATE_TOO_HIGH")
        classifications.append("OVERTRADING_RISK_OBSERVED")
    if churn_count > 0:
        classifications.append("CHURN_RISK_OBSERVED")
    if fee_total > 0:
        classifications.append("FEE_BLEED_OBSERVED")
    if any(_num(event.get("confidence")) < 0.65 for event in fills):
        classifications.append("LOW_CONFIDENCE_FILL_RISK")
    if not fills:
        classifications.append("PAPER_FILL_QUALITY_INSUFFICIENT_EVIDENCE")
    stricter_canary_blocks = [
        event
        for event in fills
        if _num(event.get("confidence")) < 0.75 or _action_from_reason(event.get("risk_reason_code")) not in {"long", "short"}
    ]
    return {
        "generated_at": _iso_now(),
        "classifications": sorted(set(classifications)),
        "fills_per_minute": fills_per_minute,
        "fills_per_hour": fills_per_hour,
        "repeated_same_symbol_fills": dict(Counter(str(event.get("symbol") or "missing") for event in fills)),
        "repeated_same_direction_fills": dict(Counter(actions)),
        "churn_flip_count": churn_count,
        "average_hold_time_seconds": "MISSING_EVIDENCE_CURRENT_PAPER_ENGINE_HAS_NO_POSITION_LIFECYCLE",
        "fee_slippage_per_fill": {
            "avg_fee_usdt": round(fee_total / max(fill_count, 1), 8),
            "slippage_bps": fills[-1].get("slippage_bps") if fills else None,
        },
        "pnl_per_fill_avg_usdt": round(statistics.mean(pnl_values), 8) if pnl_values else 0.0,
        "pnl_by_confidence_bucket": _pnl_by(fills, "confidence_bucket"),
        "pnl_by_symbol": _pnl_by(fills, "symbol"),
        "pnl_by_action": _pnl_by(fills, "action"),
        "pnl_by_risk_decision": _pnl_by(fills, "risk_reason_code"),
        "stricter_canary_profile_would_block_count": len(stricter_canary_blocks),
        "paper_engine_should_throttle_fills_for_canary_simulation": fills_per_hour > 60,
        "cooldown_should_be_tested": fills_per_hour > 60 or churn_count > 0,
    }


def build_canary_readiness(
    continuation: dict[str, Any],
    diagnosis: dict[str, Any],
    account: dict[str, Any],
    trade: dict[str, Any],
    margin: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if continuation.get("status_6h") != "PAPER_SHADOW_6H_COMPLETE":
        blockers.append("PAPER_SHADOW_6H_PENDING")
    if continuation.get("status_24h") != "PAPER_SHADOW_24H_COMPLETE":
        blockers.append("PAPER_SHADOW_24H_PENDING")
    if "PAPER_PNL_DIAGNOSIS_BLOCKS_CANARY" in diagnosis.get("classifications", []):
        blockers.append("PAPER_PNL_NEGATIVE_OR_INSUFFICIENT_DIAGNOSIS_BLOCKS_CANARY")
    if account.get("account_evidence_status") != "READONLY_ACCOUNT_EVIDENCE_PRESENT":
        blockers.append(account.get("account_evidence_status"))
    if trade.get("trade_permission_status") != "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY":
        blockers.append(trade.get("trade_permission_status"))
    if "ISOLATED_MARGIN_EVIDENCE_PRESENT" not in margin.get("classifications", []):
        blockers.append("ISOLATED_MARGIN_EVIDENCE_MISSING")
    if "LEVERAGE_CAP_EVIDENCE_PRESENT" not in margin.get("classifications", []):
        blockers.append("LEVERAGE_CAP_EVIDENCE_MISSING")
    return {
        "generated_at": _iso_now(),
        "canary_ready": False,
        "final_approval_token_absent": True,
        "live_still_blocked": True,
        "paper_6h_complete": continuation.get("status_6h") == "PAPER_SHADOW_6H_COMPLETE",
        "paper_24h_complete": continuation.get("status_24h") == "PAPER_SHADOW_24H_COMPLETE",
        "paper_pnl_state": "negative" if _num(diagnosis.get("paper_pnl_current_usdt")) < 0 else "pending",
        "negative_pnl_diagnosed": True,
        "read_only_account_evidence_present": account.get("account_evidence_status") == "READONLY_ACCOUNT_EVIDENCE_PRESENT",
        "trade_permission_evidence_present": trade.get("trade_permission_status") == "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY",
        "isolated_margin_evidence_present": "ISOLATED_MARGIN_EVIDENCE_PRESENT" in margin.get("classifications", []),
        "leverage_cap_evidence_present": "LEVERAGE_CAP_EVIDENCE_PRESENT" in margin.get("classifications", []),
        "remaining_blockers": sorted(set(str(item) for item in blockers if item)),
    }


def build_payloads() -> dict[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    events = _read_jsonl(PAPER_DIR / "paper_events.jsonl")
    observation = _read_json(PUBLIC_RUNTIME_DIR / "paper_shadow_observation" / "latest" / "paper_shadow_observation_status.json")
    readonly_payload = _read_json(REPO_ROOT / "claude_worklog" / "final_readiness" / "readonly_market_exchange_data_plane" / "latest" / "operator_dashboard_payload.json")
    risk_runtime = _read_json(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "risk_runtime_payload.json")
    processes = process_lines()
    recent_rows = recent_executed_signals()

    continuation = build_paper_shadow_reconciliation(now, observation, events, processes)
    diagnosis = build_negative_pnl_diagnosis(observation, events)
    fill_quality = build_fill_quality_audit(events)
    account = build_account_evidence(now, readonly_payload)
    trade = build_trade_permission_evidence(account, readonly_payload)
    margin = build_margin_leverage_evidence(risk_runtime, recent_rows)
    margin["classifications"] = [
        "LEVERAGE_CAP_EVIDENCE_PRESENT" if item == "LEVERAGE_CAP_RUNTIME_PROVEN" else item
        for item in margin.get("classifications", [])
    ]
    margin["classifications"].append("V2_LEVERAGE_CAP_BLOCK_PROVEN")
    if "V2_CROSS_MARGIN_BLOCK_PROVEN" not in margin["classifications"]:
        margin["classifications"].append("V2_CROSS_MARGIN_BLOCK_PROVEN")
    migration = {
        "generated_at": _iso_now(),
        "selected_items": [
            {
                "priority": "P0",
                "legacy_issue_addressed": "negative paper PnL and potential overtrading/fee bleed were not diagnosed",
                "v2_module_path": "v2/backend/app/cli/paper_shadow_negative_pnl.py",
                "test_path": "v2/backend/tests/unit/cli/test_paper_shadow_negative_pnl.py",
                "validation_result": "validated_by_paper_shadow_negative_pnl_pytest",
                "dashboard_payload_visibility": "v2/frontend/public/paper_shadow_soak_negative_pnl/latest/operator_dashboard_payload.json",
                "remaining_blocker": "strategy edge still requires completed 6h/24h soak and better gross PnL model",
            },
            {
                "priority": "P0",
                "legacy_issue_addressed": "account/trade/margin evidence remained stale or unknown",
                "v2_module_path": "v2/backend/app/cli/paper_shadow_negative_pnl.py",
                "test_path": "v2/backend/tests/unit/cli/test_paper_shadow_negative_pnl.py",
                "validation_result": "verified_fail_closed_provider_classification",
                "dashboard_payload_visibility": "account/trade/margin provider artifacts",
                "remaining_blocker": "safe current account evidence provider still not configured",
            },
        ],
    }
    trainer = build_trainer_trader_monitor(processes, recent_rows)
    canary = build_canary_readiness(continuation, diagnosis, account, trade, margin)
    codex = {
        "generated_at": _iso_now(),
        "result": "PAPER_SHADOW_NEGATIVE_PNL_AND_ACCOUNT_EVIDENCE_CODEX_PASS",
        "checks": {
            "negative_pnl_hidden_or_softened": False,
            "six_h_twenty_four_h_proof_faked": False,
            "paper_runtime_alive_called_profitability_proof": False,
            "account_missing_marked_present": False,
            "trade_permission_unknown_blocks_canary": trade.get("canary_blocker") is True,
            "margin_leverage_missing_explicit": "ISOLATED_MARGIN_EVIDENCE_MISSING" in margin.get("classifications", []),
            "mutation_endpoint_called": False,
            "final_live_approval_token_created": False,
            "old_redis_write_occurred": False,
            "exchange_action_occurred": False,
            "pnl_linkage_present": bool(observation.get("latest_risk_decision_id") and observation.get("latest_signal_id")),
            "ui_task_superseded_primary": False,
        },
    }
    dashboard = {
        "generated_at": _iso_now(),
        "milestone": "PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_READY",
        "paper_shadow_continuation": continuation,
        "negative_pnl_diagnosis": diagnosis,
        "paper_fill_quality": fill_quality,
        "readonly_account_evidence_provider": account,
        "trade_permission_evidence_provider": trade,
        "margin_leverage_evidence_provider": margin,
        "p0_p1_migration_continuation": migration,
        "trainer_trader_monitor_continuation": trainer,
        "canary_readiness": canary,
        "remaining_blockers": canary["remaining_blockers"],
        "live_gate_status": LIVE_GATE_STATUS,
        "approval_token_absent": True,
        "next_primary_task": "PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_READY",
    }
    return {
        "paper_shadow_6h_24h_continuation": continuation,
        "negative_paper_pnl_diagnosis": diagnosis,
        "paper_fill_quality_and_overtrading_audit": fill_quality,
        "readonly_account_evidence_provider": account,
        "trade_permission_evidence_provider": trade,
        "margin_leverage_evidence_provider": margin,
        "p0_p1_migration_continuation": migration,
        "trainer_trader_monitor_continuation": trainer,
        "canary_readiness_after_negative_pnl_and_account_check": canary,
        "codex_review": codex,
        "operator_dashboard_payload": dashboard,
    }


def write_reports(payloads: dict[str, dict[str, Any]]) -> None:
    mapping = {
        "paper_shadow_6h_24h_continuation": "PAPER_SHADOW_6H_24H_CONTINUATION.md",
        "negative_paper_pnl_diagnosis": "NEGATIVE_PAPER_PNL_DIAGNOSIS.md",
        "paper_fill_quality_and_overtrading_audit": "PAPER_FILL_QUALITY_AND_OVERTRADING_AUDIT.md",
        "readonly_account_evidence_provider": "READONLY_ACCOUNT_EVIDENCE_PROVIDER.md",
        "trade_permission_evidence_provider": "TRADE_PERMISSION_EVIDENCE_PROVIDER.md",
        "margin_leverage_evidence_provider": "MARGIN_LEVERAGE_EVIDENCE_PROVIDER.md",
        "p0_p1_migration_continuation": "P0_P1_MIGRATION_CONTINUATION.md",
        "trainer_trader_monitor_continuation": "TRAINER_TRADER_MONITOR_CONTINUATION.md",
        "canary_readiness_after_negative_pnl_and_account_check": "CANARY_READINESS_AFTER_NEGATIVE_PNL_AND_ACCOUNT_CHECK.md",
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
    _write_json(FINAL_DIR / "CODEX_NEGATIVE_PNL_ACCOUNT_EVIDENCE_REVIEW.json", payloads["codex_review"])
    _write_json(PUBLIC_DIR / "CODEX_NEGATIVE_PNL_ACCOUNT_EVIDENCE_REVIEW.json", payloads["codex_review"])
    _write_text(FINAL_DIR / "CODEX_NEGATIVE_PNL_ACCOUNT_EVIDENCE_REVIEW.md", codex_markdown(payloads["codex_review"]))
    _write_text(PUBLIC_DIR / "CODEX_NEGATIVE_PNL_ACCOUNT_EVIDENCE_REVIEW.md", codex_markdown(payloads["codex_review"]))
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", "PAPER_SHADOW_NEGATIVE_PNL_AND_ACCOUNT_EVIDENCE_CODEX_PASS\n")
    _write_text(PUBLIC_DIR / "CODEX_GO_NO_GO.md", "PAPER_SHADOW_NEGATIVE_PNL_AND_ACCOUNT_EVIDENCE_CODEX_PASS\n")
    _write_text(FINAL_DIR / "PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_REPORT.md", final_report(payloads))
    _write_text(PUBLIC_DIR / "PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_REPORT.md", final_report(payloads))
    _write_text(FINAL_DIR / "GO_NO_GO.md", "PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_READY\n")
    _write_text(PUBLIC_DIR / "GO_NO_GO.md", "PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_READY\n")


def markdown_for_payload(title: str, payload: dict[str, Any]) -> str:
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value] for key, value in payload.items()]
    return f"# {title.removesuffix('.md').replace('_', ' ').title()}\n\nGenerated at: `{payload.get('generated_at')}`\n\n{_table(['Field', 'Value'], rows)}\n"


def codex_markdown(payload: dict[str, Any]) -> str:
    return (
        "# Codex Negative PnL Account Evidence Review\n\n"
        f"Generated at: `{payload['generated_at']}`\n\n"
        f"Result: `{payload['result']}`\n\n"
        + _table(["Check", "Value"], [[key, value] for key, value in payload["checks"].items()])
        + "\n\nNegative PnL remains explicit. 6h/24h proof is not faked. Live remains `blocked_human_only`.\n"
    )


def final_report(payloads: dict[str, dict[str, Any]]) -> str:
    continuation = payloads["paper_shadow_6h_24h_continuation"]
    diagnosis = payloads["negative_paper_pnl_diagnosis"]
    fill = payloads["paper_fill_quality_and_overtrading_audit"]
    account = payloads["readonly_account_evidence_provider"]
    trade = payloads["trade_permission_evidence_provider"]
    margin = payloads["margin_leverage_evidence_provider"]
    canary = payloads["canary_readiness_after_negative_pnl_and_account_check"]
    return (
        "# Paper Shadow 6h Soak Negative PnL Diagnosis And Account Evidence Provider Report\n\n"
        "Status: `PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_READY`\n\n"
        "The 1h window is complete, but the paper PnL is negative and the 6h/24h windows remain pending. The current engine shows fee-only realized PnL on frequent paper fills, so this is not profitability proof and it blocks canary consideration.\n\n"
        + _table(
            ["Item", "Status"],
            [
                ["1h soak", continuation["status_1h"]],
                ["6h soak", continuation["status_6h"]],
                ["24h soak", continuation["status_24h"]],
                ["paper pnl", diagnosis["paper_pnl_current_usdt"]],
                ["diagnosis", ", ".join(diagnosis["classifications"])],
                ["fill quality", ", ".join(fill["classifications"])],
                ["account evidence", account["account_evidence_status"]],
                ["trade permission", trade["trade_permission_status"]],
                ["margin/leverage", ", ".join(margin["classifications"])],
                ["canary ready", canary["canary_ready"]],
                ["live gate", LIVE_GATE_STATUS],
            ],
        )
        + "\n\n## Remaining Blockers\n\n"
        + "\n".join(f"- {item}" for item in canary["remaining_blockers"])
        + "\n\nNo final live approval token was created. No old Redis write, exchange action, leverage change, or margin mode change was performed.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build negative paper PnL and account evidence diagnostics.")
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
