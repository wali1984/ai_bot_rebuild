from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
LOCAL_PAPER_DIR = V2_ROOT / "runtime" / "paper_online" / "latest"
LOCAL_OUTPUT_DIR = V2_ROOT / "runtime" / "paper_shadow_observation" / "latest"
PUBLIC_OUTPUT_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_shadow_observation" / "latest"
PUBLIC_PAPER_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
LIVE_GATE_STATUS = "blocked_human_only"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _read_text_action_log(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return events
    for index, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        action = parts[2]
        events.append(
            {
                "generated_at": parts[0],
                "tick_id": f"text_log_{index}",
                "ledger_action": action,
                "paper_result": "FILLED_PAPER_ONLY" if action == "PAPER_FILL_SIMULATED" else "NO_FILL_RISK_BLOCKED",
                "risk_action": "allow" if action == "PAPER_FILL_SIMULATED" else "deny",
                "risk_reason_code": "text_log_action_only",
                "source_type": "V2_PAPER_RUNTIME_TEXT_LOG_FALLBACK",
            }
        )
    return events


def _event_time(event: dict[str, Any]) -> datetime | None:
    return _parse_iso(event.get("generated_at"))


def _confidence_bucket(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "missing"
    if confidence >= 0.75:
        return "0.75_plus"
    if confidence >= 0.65:
        return "0.65_to_0.75"
    if confidence >= 0.58:
        return "0.58_to_0.65"
    return "below_0.58"


def _window_summary(events: list[dict[str, Any]], *, hours: int, now: datetime) -> dict[str, Any]:
    cutoff = now.timestamp() - hours * 3600
    window_events = [
        event
        for event in events
        if (event_time := _event_time(event)) is not None and event_time.timestamp() >= cutoff
    ]
    first_event_at = min((_event_time(event) for event in events if _event_time(event) is not None), default=None)
    window_complete = first_event_at is not None and first_event_at.timestamp() <= cutoff
    fills = [event for event in window_events if event.get("paper_result") == "FILLED_PAPER_ONLY" or event.get("ledger_action") == "PAPER_FILL_SIMULATED"]
    blocked = [event for event in window_events if event.get("risk_action") == "deny" or event.get("paper_result") == "NO_FILL_RISK_BLOCKED"]
    pnl_values = [
        float(event["paper_realized_pnl"])
        for event in window_events
        if isinstance(event.get("paper_realized_pnl"), int | float)
    ]
    pnl_delta = round(pnl_values[-1] - pnl_values[0], 6) if len(pnl_values) >= 2 else None
    reason_counts = Counter(str(event.get("risk_reason_code") or "missing") for event in window_events)
    confidence_counts = Counter(_confidence_bucket(event.get("confidence")) for event in window_events)
    symbol_counts = Counter(str(event.get("symbol") or "missing") for event in window_events)
    return {
        "hours": hours,
        "classification": f"PAPER_SHADOW_{hours}H_COMPLETE" if window_complete else f"PAPER_SHADOW_{hours}H_PENDING",
        "window_complete": window_complete,
        "event_count": len(window_events),
        "allowed_intents": sum(1 for event in window_events if event.get("risk_action") == "allow"),
        "blocked_intents": len(blocked),
        "simulated_fills": len(fills),
        "paper_pnl_delta_usdt": pnl_delta,
        "paper_pnl_delta_status": "CURRENT_WINDOW_PNL_AVAILABLE" if pnl_delta is not None else "PNL_WINDOW_PENDING",
        "reason_distribution": dict(reason_counts),
        "confidence_bucket_distribution": dict(confidence_counts),
        "symbol_distribution": dict(symbol_counts),
    }


def build_observation_status(
    *,
    paper_dir: Path = LOCAL_PAPER_DIR,
    public_paper_dir: Path = PUBLIC_PAPER_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    runtime = _read_json(paper_dir / "paper_runtime_status.json") or _read_json(public_paper_dir / "paper_runtime_status.json")
    events = _read_jsonl(paper_dir / "paper_events.jsonl")
    source = "V2_PAPER_RUNTIME_JSONL_EVENT"
    if not events:
        events = _read_text_action_log(paper_dir / "paper_online_runtime.log")
        source = "V2_PAPER_RUNTIME_TEXT_LOG_FALLBACK"
    latest_lineage = runtime.get("current_signal_lineage", {}).get("lineage_ids", {})
    latest_ledger = (runtime.get("paper_ledger_tail") or [{}])[0]
    windows = {
        "1h": _window_summary(events, hours=1, now=now),
        "6h": _window_summary(events, hours=6, now=now),
        "24h": _window_summary(events, hours=24, now=now),
    }
    fill_events = [
        event
        for event in events
        if event.get("paper_result") == "FILLED_PAPER_ONLY" or event.get("ledger_action") == "PAPER_FILL_SIMULATED"
    ]
    blocked_events = [
        event
        for event in events
        if event.get("risk_action") == "deny" or event.get("paper_result") == "NO_FILL_RISK_BLOCKED"
    ]
    return {
        "generated_at": _iso_now(),
        "source": source,
        "live_gate_status": LIVE_GATE_STATUS,
        "runtime_state": runtime.get("runtime_state", "MISSING_EVIDENCE"),
        "runtime_age_seconds": runtime.get("freshness", {}).get("runtime_age_seconds"),
        "latest_prediction_id": latest_lineage.get("prediction_id") or runtime.get("trainer_prediction", {}).get("prediction_id"),
        "latest_signal_id": latest_lineage.get("signal_id"),
        "latest_risk_decision_id": latest_lineage.get("risk_decision_id"),
        "latest_execution_intent_id": latest_lineage.get("execution_intent_id") or latest_ledger.get("execution_intent_id"),
        "latest_paper_fill_id": latest_ledger.get("paper_ledger_entry_id") if latest_ledger.get("paper_result") == "FILLED_PAPER_ONLY" else None,
        "latest_paper_ledger_entry_id": latest_ledger.get("paper_ledger_entry_id"),
        "paper_events_count": len(events),
        "allowed_intents": sum(1 for event in events if event.get("risk_action") == "allow"),
        "blocked_intents": len(blocked_events),
        "simulated_fills": len(fill_events),
        "paper_pnl_current_usdt": runtime.get("paper_account", {}).get("realized_pnl"),
        "fees_slippage_funding_assumptions": {
            "fee_rate": latest_ledger.get("fee_rate"),
            "slippage_bps": latest_ledger.get("slippage_bps"),
            "funding": latest_ledger.get("funding_assumption", "zero_until_funding_feed_adapter_current"),
        },
        "windows": windows,
        "paper_shadow_6h_status": windows["6h"]["classification"],
        "paper_shadow_24h_status": windows["24h"]["classification"],
        "profitability_proof_status": "PROFITABILITY_PROOF_AVAILABLE" if windows["6h"]["window_complete"] and windows["24h"]["window_complete"] else "PROFITABILITY_PROOF_PENDING",
        "legacy_vs_v2_comparison": "MISSING_EVIDENCE_UNTIL_RECENT_LEGACY_EXECUTION_IMPORT_WINDOW",
        "safety": {
            "old_redis_write": False,
            "exchange_order": False,
            "leverage_change": False,
            "margin_mode_change": False,
            "final_live_approval_token": False,
        },
    }


def write_observation_status(status: dict[str, Any]) -> None:
    for root in (LOCAL_OUTPUT_DIR, PUBLIC_OUTPUT_DIR):
        _write_json(root / "paper_shadow_observation_status.json", status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V2 paper-shadow observation summary from local V2 evidence.")
    parser.add_argument("--write", action="store_true", help="Write local and public observation payloads.")
    args = parser.parse_args()
    status = build_observation_status()
    if args.write:
        write_observation_status(status)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
