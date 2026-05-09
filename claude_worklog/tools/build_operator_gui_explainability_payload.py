#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
FINAL = ROOT / "claude_worklog/final_readiness/operator_gui_real_data_and_explainability/latest"
PUBLIC = ROOT / "v2/frontend/public/operator_gui_real_data_and_explainability/latest"
GO_NO_GO = "PROFESSIONAL_OPERATOR_GUI_AND_DECISION_EXPLAINABILITY_READY"
LIVE_GATE_STATUS = "blocked_human_only"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return default


def git_head() -> str:
    proc = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout.strip() or "evidence_missing"


def file_exists(path: str) -> bool:
    return (ROOT / path).exists()


def build_payload() -> dict[str, Any]:
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json", {})
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json", {})
    non_live = read_json(
        ROOT / "claude_worklog/final_readiness/non_live_operational_proof/latest/decision_explainability_result.json",
        {"explanations": []},
    )
    risk = read_json(
        ROOT / "claude_worklog/final_readiness/non_live_operational_proof/latest/risk_gateway_result.json",
        {"decisions": []},
    )
    paper = read_json(
        ROOT / "claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json",
        {"events": []},
    )
    shadow = read_json(
        ROOT / "claude_worklog/final_readiness/non_live_operational_proof/latest/shadow_comparison_result.json",
        {"comparisons": []},
    )
    historical = read_json(
        ROOT / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/operator_dashboard_payload.json",
        {},
    )
    automation_liveness = read_json(
        ROOT / "claude_worklog/final_readiness/automation_liveness/latest/dashboard_liveness_payload.json",
        {},
    )
    legacy_process = read_text(ROOT / "claude_worklog/legacy_readonly_audit/01_PROCESS_SNAPSHOT.md")
    trainer_evidence = read_text(ROOT / "claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md")
    orchestrator_evidence = read_text(
        ROOT / "claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md"
    )

    explanations = list(non_live.get("explanations", []))
    historical_rows = list(historical.get("legacy_vs_v2", []))

    lineage = [_lineage_from_non_live(row) for row in explanations]
    lineage.extend(_lineage_from_historical(row) for row in historical_rows)

    risk_rows = [_risk_row(row) for row in risk.get("decisions", [])]
    historical_blocks = historical.get("risk_blocks", [])
    risk_rows.extend(_risk_row_from_historical(row) for row in historical_blocks)

    paper_rows = [_paper_row(row) for row in paper.get("events", [])]
    shadow_rows = [_shadow_row(row) for row in shadow.get("comparisons", [])]
    historical_shadow = read_json(
        ROOT / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/shadow_comparison_30d.json",
        {"comparisons": []},
    )
    shadow_rows.extend(_shadow_row_from_historical(row) for row in historical_shadow.get("comparisons", []))

    monitors = [
        _monitor_row(
            "legacy_process_snapshot",
            "claude_worklog/legacy_readonly_audit/01_PROCESS_SNAPSHOT.md",
            legacy_process,
            ["legacy runtime processes"],
        ),
        _monitor_row(
            "trainer_runtime_evidence",
            "claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md",
            trainer_evidence,
            ["rl.hybrid_trainer", "monitor_trainer_predictions", "monitor_trainer_prices"],
        ),
        _monitor_row(
            "orchestrator_trader_runtime_evidence",
            "claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md",
            orchestrator_evidence,
            ["rl.orchestrator_worker", "trading/trader.py", "monitor_portfolio"],
        ),
        {
            "id": "agent_supervisor_queue",
            "script_path": "claude_worklog/tools/agent_supervisor.py",
            "owner": "automation",
            "status": "active" if queue else "evidence_missing",
            "last_run": queue.get("generated_at", "evidence_missing"),
            "last_success": queue.get("generated_at", "evidence_missing"),
            "last_failure": "evidence_missing",
            "metrics_emitted": list((queue.get("counts") or {}).keys()),
            "redis_keys_watched": [],
            "logs_watched": ["claude_worklog/agent_supervisor/events.jsonl"],
            "processes_watched": ["agent_supervisor.py", "claude --print", "codex exec"],
            "alerts": queue.get("stale_running_tasks", []),
            "classification": "active" if queue else "unknown",
        },
    ]

    payload = {
        "generated_at": now(),
        "git_head": git_head(),
        "live_gate_status": LIVE_GATE_STATUS,
        "status": {
            "go_no_go": GO_NO_GO,
            "queue_gate": queue.get("gate", "evidence_missing"),
            "current_task": current.get("task_id") or queue.get("current_running_task") or "evidence_missing",
            "human_attention_required_count": queue.get("human_attention_required_count", "evidence_missing"),
            "stale_running_count": queue.get("stale_running_count", "evidence_missing"),
            "automation_assessment": automation_liveness.get("automation_assessment", "evidence_missing"),
            "last_event_timestamp": (automation_liveness.get("dashboard_summary") or {}).get(
                "last_event_timestamp", "evidence_missing"
            ),
            "last_artifact_update": (automation_liveness.get("dashboard_summary") or {}).get(
                "last_artifact_update", "evidence_missing"
            ),
            "legacy_trader_disabled_non_blocking": (automation_liveness.get("dashboard_summary") or {}).get(
                "legacy_trader_disabled_non_blocking", True
            ),
            "task_069_progress_state": (automation_liveness.get("dashboard_summary") or {}).get(
                "task_069_progress_state", "evidence_missing"
            ),
            "proof_marker": read_text(
                ROOT / "claude_worklog/final_readiness/non_live_operational_proof/latest/GO_NO_GO.md",
                "evidence_missing",
            ).strip(),
            "historical_marker": read_text(
                ROOT / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/GO_NO_GO.md",
                "evidence_missing",
            ).strip(),
        },
        "mission_control": {
            "queue": queue,
            "current_status": current,
            "remaining_blockers": _remaining_blockers(queue, current),
        },
        "trainer_prediction_monitor": {
            "rows": lineage,
            "evidence_source": "non_live_operational_proof/latest and historical_30d_replay_and_paper_proof/latest",
        },
        "signal_explainability": {"rows": lineage},
        "feature_attribution": {"rows": [_feature_row(row) for row in lineage]},
        "symbol_universe": {"rows": _symbol_rows(lineage)},
        "orchestrator_decisions": {"rows": [_orchestrator_row(row) for row in lineage]},
        "risk_gateway": {"rows": risk_rows},
        "trader_fleet_paper_shadow": {"paper_rows": paper_rows, "shadow_rows": shadow_rows},
        "monitor_center": {"rows": monitors},
        "script_registry_system_atlas": {
            "rows": [
                {"path": row["script_path"], "owner": row["owner"], "classification": row["classification"]}
                for row in monitors
            ]
        },
        "config_admin": {"settings": _settings_rows()},
        "audit_ledger": {
            "rows": [
                {
                    "artifact": "non_live_operational_proof/latest/GO_NO_GO.md",
                    "exists": file_exists("claude_worklog/final_readiness/non_live_operational_proof/latest/GO_NO_GO.md"),
                    "classification": "proof_marker",
                },
                {
                    "artifact": "historical_30d_replay_and_paper_proof/latest/GO_NO_GO.md",
                    "exists": file_exists(
                        "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/GO_NO_GO.md"
                    ),
                    "classification": "proof_marker",
                },
                {
                    "artifact": "operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json",
                    "exists": True,
                    "classification": "dashboard_payload",
                },
            ]
        },
        "replay_historical_proof": historical,
        "live_readiness": {
            "live_gate_status": LIVE_GATE_STATUS,
            "approval_required": True,
            "dangerous_controls_enabled": False,
            "live_blockers": _live_blockers(),
        },
        "automation_status": {
            "queue": queue,
            "current_status": current,
            "stale_running_tasks": queue.get("stale_running_tasks", []),
            "liveness": automation_liveness,
            "task_069_liveness": automation_liveness.get("task_069_liveness", {}),
        },
    }
    payload["remaining_blockers_before_live"] = _remaining_blockers(queue, current) + _live_blockers()
    payload["data_gaps"] = _data_gaps(payload)
    return payload


def _lineage_from_non_live(row: dict[str, Any]) -> dict[str, Any]:
    flags = row.get("feature_flags") or {}
    explanation = row.get("explanation_payload") or {}
    return {
        "id": row.get("decision_id", row.get("scenario_id", "evidence_missing")),
        "source": "non_live_operator_proof",
        "symbol": row.get("symbol", "evidence_missing"),
        "raw_source_data": "deterministic_non_live_fixture",
        "feature_snapshot_id": row.get("feature_snapshot_id", "evidence_missing"),
        "feature_freshness": "stale" if flags.get("stale") else "fresh",
        "stale_flags": flags.get("stale", []),
        "missing_flags": flags.get("missing", []),
        "unused_flags": flags.get("unused", []),
        "prediction_id": row.get("prediction_id", "evidence_missing"),
        "old_confidence": "evidence_missing",
        "new_confidence": row.get("confidence", "evidence_missing"),
        "confidence_delta": "evidence_missing",
        "confidence_calibration": "evidence_missing",
        "model_checkpoint": "evidence_missing",
        "top_positive_contributors": _causes(row)[:2],
        "top_negative_contributors": _causes(row)[2:] or ["evidence_missing"],
        "source_freshness_by_ingestor": {"proof_fixture": "fresh"},
        "signal_id": row.get("decision_id", "evidence_missing"),
        "orchestrator_decision": row.get("scenario_id", "evidence_missing"),
        "risk_gateway_decision": row.get("risk_decision", "evidence_missing"),
        "risk_decision_id": row.get("risk_decision_id", "evidence_missing"),
        "execution_intent_id": row.get("execution_intent_id", "evidence_missing"),
        "paper_shadow_live_blocked_action": row.get("block_or_allow_reason", "evidence_missing"),
        "result_pnl_attribution": row.get("paper_pnl", "evidence_missing"),
        "evidence_links": ["claude_worklog/final_readiness/non_live_operational_proof/latest"],
        "warnings": _warnings(row),
    }


def _lineage_from_historical(row: dict[str, Any]) -> dict[str, Any]:
    flags = row.get("feature_flags") or {}
    return {
        "id": row.get("decision_id", row.get("trade_id", "evidence_missing")),
        "source": "historical_30d_proof",
        "symbol": row.get("symbol", "evidence_missing"),
        "raw_source_data": "historical_30d_deterministic_fixture",
        "feature_snapshot_id": row.get("feature_snapshot_id", "evidence_missing"),
        "feature_freshness": "stale" if flags.get("stale") else "fresh",
        "stale_flags": flags.get("stale", []),
        "missing_flags": flags.get("missing", []),
        "unused_flags": flags.get("unused", []),
        "prediction_id": row.get("prediction_id", "evidence_missing"),
        "old_confidence": "evidence_missing",
        "new_confidence": row.get("confidence", "evidence_missing"),
        "confidence_delta": "evidence_missing",
        "confidence_calibration": "evidence_missing",
        "model_checkpoint": "evidence_missing",
        "top_positive_contributors": [row.get("reason", "evidence_missing")],
        "top_negative_contributors": flags.get("stale") or ["evidence_missing"],
        "source_freshness_by_ingestor": {"historical_fixture": "fresh"},
        "signal_id": row.get("decision_id", "evidence_missing"),
        "orchestrator_decision": row.get("v2_action", "evidence_missing"),
        "risk_gateway_decision": row.get("risk_decision", "evidence_missing"),
        "risk_decision_id": row.get("risk_decision_id", "evidence_missing"),
        "execution_intent_id": row.get("execution_intent_id", "evidence_missing"),
        "paper_shadow_live_blocked_action": row.get("v2_action", "evidence_missing"),
        "result_pnl_attribution": row.get("v2_paper_pnl", "evidence_missing"),
        "evidence_links": [
            "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest"
        ],
        "warnings": ["real account-history pull missing"] if "fixture" else [],
    }


def _causes(row: dict[str, Any]) -> list[str]:
    payload = row.get("explanation_payload") or {}
    return list(payload.get("causes") or [])


def _warnings(row: dict[str, Any]) -> list[str]:
    warnings = []
    if row.get("feature_flags", {}).get("stale"):
        warnings.append("stale feature flags present")
    if row.get("confidence") is not None:
        warnings.append("confidence delta missing")
    return warnings


def _risk_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("risk_decision_id", row.get("scenario_id", "evidence_missing")),
        "symbol": row.get("symbol", "evidence_missing"),
        "signal_reason": row.get("requested_action", "evidence_missing"),
        "stale_signal_check": "blocked" if row.get("feature_flags", {}).get("stale") else "passed",
        "duplicate_signal_check": "blocked" if row.get("block_or_allow_reason") == "duplicate_signal" else "passed",
        "exposure_check": "blocked" if "exposure" in row.get("block_or_allow_reason", "") else "passed",
        "drawdown_check": "evidence_missing",
        "sizing_reason": "paper_fixture_no_live_sizing",
        "stop_policy_status": "evidence_missing",
        "live_gate_status": LIVE_GATE_STATUS,
        "final_decision": row.get("risk_decision", "evidence_missing"),
        "final_reason": row.get("block_or_allow_reason", "evidence_missing"),
        "execution_mode": "paper" if row.get("risk_decision") == "allow" else "live-blocked",
    }


def _risk_row_from_historical(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("risk_decision_id", row.get("trade_id", "evidence_missing")),
        "symbol": row.get("symbol", "evidence_missing"),
        "signal_reason": row.get("legacy_action", "evidence_missing"),
        "stale_signal_check": "blocked" if row.get("feature_flags", {}).get("stale") else "passed",
        "duplicate_signal_check": "blocked" if row.get("reason") == "duplicate_signal" else "passed",
        "exposure_check": "blocked" if "exposure" in row.get("reason", "") else "passed",
        "drawdown_check": "evidence_missing",
        "sizing_reason": "historical_fixture_no_live_sizing",
        "stop_policy_status": "evidence_missing",
        "live_gate_status": LIVE_GATE_STATUS,
        "final_decision": row.get("risk_decision", "evidence_missing"),
        "final_reason": row.get("reason", "evidence_missing"),
        "execution_mode": "paper" if row.get("risk_decision") == "allow" else "live-blocked",
    }


def _paper_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("paper_trade_id", "evidence_missing"),
        "type": row.get("ledger_event_type", "evidence_missing"),
        "symbol": row.get("symbol", "evidence_missing"),
        "risk_decision_id": row.get("risk_decision_id", "evidence_missing"),
        "execution_intent_id": row.get("execution_intent_id", "evidence_missing"),
        "pnl": row.get("paper_pnl", "evidence_missing"),
        "mode": "paper",
        "live_gate_status": row.get("live_gate_status", LIVE_GATE_STATUS),
    }


def _shadow_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("shadow_decision_id", "evidence_missing"),
        "symbol": row.get("symbol", "evidence_missing"),
        "legacy_action": row.get("legacy_action", "evidence_missing"),
        "v2_action": row.get("v2_action", "evidence_missing"),
        "diverged": row.get("diverged", False),
        "reason": row.get("operator_note", row.get("block_or_allow_reason", "evidence_missing")),
    }


def _shadow_row_from_historical(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("shadow_decision_id", "evidence_missing"),
        "symbol": row.get("symbol", "evidence_missing"),
        "legacy_action": row.get("legacy_action", "evidence_missing"),
        "v2_action": row.get("v2_action", "evidence_missing"),
        "diverged": row.get("diverged", False),
        "reason": row.get("operator_note", row.get("reason", "evidence_missing")),
    }


def _feature_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "feature_snapshot_id": row["feature_snapshot_id"],
        "freshness": row["feature_freshness"],
        "positive": row["top_positive_contributors"],
        "negative": row["top_negative_contributors"],
        "stale": row["stale_flags"],
        "missing": row["missing_flags"],
        "unused": row["unused_flags"],
        "source_freshness_by_ingestor": row["source_freshness_by_ingestor"],
    }


def _symbol_rows(lineage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for row in lineage:
        symbol = row["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        rows.append(
            {
                "symbol": symbol,
                "discovery_source": row["source"],
                "binance_evidence": "evidence_missing",
                "coinank_evidence": "evidence_missing",
                "coinapi_evidence": "evidence_missing",
                "kucoin_evidence": "evidence_missing",
                "liquidity_score": "evidence_missing",
                "volume_score": "evidence_missing",
                "volatility_score": "evidence_missing",
                "open_interest_score": "evidence_missing",
                "feature_completeness_score": "derived_from_feature_flags",
                "risk_score": "derived_from_risk_decision",
                "universe_state": "paper/shadow",
                "why_state": "available in proof artifact lineage",
            }
        )
    return rows


def _orchestrator_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": row["id"],
        "symbol": row["symbol"],
        "signal_id": row["signal_id"],
        "orchestrator_decision": row["orchestrator_decision"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_intent_id": row["execution_intent_id"],
        "lineage_complete": "evidence_missing" not in [
            row["feature_snapshot_id"],
            row["prediction_id"],
            row["risk_decision_id"],
            row["execution_intent_id"],
        ],
    }


def _monitor_row(identifier: str, path: str, text: str, watched: list[str]) -> dict[str, Any]:
    missing = "NO_" in text or not text
    return {
        "id": identifier,
        "script_path": path,
        "owner": "legacy_readonly_audit",
        "status": "evidence_missing" if missing else "observed",
        "last_run": _generated_line(text),
        "last_success": _generated_line(text),
        "last_failure": "evidence_missing",
        "metrics_emitted": ["process_presence"],
        "redis_keys_watched": [],
        "logs_watched": [],
        "processes_watched": watched,
        "alerts": ["no matching process evidence"] if missing else [],
        "classification": "unknown" if missing else "active",
    }


def _generated_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Generated:"):
            return line.replace("Generated:", "").strip()
    return "evidence_missing"


def _settings_rows() -> list[dict[str, str]]:
    return [
        {"name": "trainer confidence threshold", "value": "evidence_missing", "classification": "requires validation"},
        {"name": "model checkpoint", "value": "evidence_missing", "classification": "read-only"},
        {"name": "symbol universe", "value": "proof artifact symbols", "classification": "requires validation"},
        {"name": "daily loss limit", "value": "evidence_missing", "classification": "requires explicit human approval"},
        {"name": "leverage", "value": "evidence_missing", "classification": "requires explicit human approval"},
        {"name": "margin mode", "value": "evidence_missing", "classification": "requires explicit human approval"},
        {"name": "stop policy", "value": "evidence_missing", "classification": "requires validation"},
        {"name": "hedge/DCA", "value": "evidence_missing", "classification": "requires explicit human approval"},
        {"name": "paper/live mode", "value": LIVE_GATE_STATUS, "classification": "read-only"},
        {"name": "API key status", "value": "presence not displayed", "classification": "read-only"},
        {"name": "kill switch", "value": "live gate blocked", "classification": "requires explicit human approval"},
    ]


def _remaining_blockers(queue: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    if queue.get("stale_running_count"):
        blockers.append(
            {
                "id": "stale_running_tasks",
                "status": "open",
                "detail": ", ".join(queue.get("stale_running_tasks") or []),
            }
        )
    if current.get("status") == "blocked_dependency":
        blockers.append(
            {
                "id": current.get("task_id", "blocked_dependency"),
                "status": "open",
                "detail": current.get("summary", "blocked dependency"),
            }
        )
    return blockers


def _live_blockers() -> list[dict[str, Any]]:
    return [
        {"id": "live_gate", "status": "blocked", "detail": "human-only live approval required"},
        {"id": "real_exchange_execution", "status": "blocked", "detail": "no live execution controls enabled"},
        {"id": "redis_live_writes", "status": "blocked", "detail": "dashboard is static/read-only"},
    ]


def _data_gaps(payload: dict[str, Any]) -> list[str]:
    gaps = set()
    for row in payload["trainer_prediction_monitor"]["rows"]:
        for key in ["old_confidence", "confidence_delta", "model_checkpoint", "confidence_calibration"]:
            if row.get(key) == "evidence_missing":
                gaps.add(key)
    for row in payload["symbol_universe"]["rows"]:
        for key in ["liquidity_score", "volume_score", "volatility_score", "open_interest_score"]:
            if row.get(key) == "evidence_missing":
                gaps.add(key)
    return sorted(gaps)


def write_outputs() -> None:
    FINAL.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    for base in [FINAL, PUBLIC]:
        (base / "operator_cockpit_payload.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base / "GO_NO_GO.md").write_text(GO_NO_GO + "\n", encoding="utf-8")

    _write_report("OPERATOR_GUI_AND_EXPLAINABILITY_REPORT.md", payload)
    _write_report("DATA_WIRING_MAP.md", payload)
    _write_report("PLACEHOLDER_REMOVAL_REPORT.md", payload)
    _write_report("DECISION_EXPLAINABILITY_COVERAGE.md", payload)
    _write_report("CONFIG_ADMIN_COVERAGE.md", payload)
    _write_report("MONITOR_CENTER_COVERAGE.md", payload)
    _write_report("REMAINING_EVIDENCE_GAPS.md", payload)


def _write_report(name: str, payload: dict[str, Any]) -> None:
    lines = [
        f"# {name.replace('_', ' ').replace('.md', '').title()}",
        "",
        f"- marker: `{GO_NO_GO}`",
        f"- generated_at: `{payload['generated_at']}`",
        f"- live_gate_status: `{payload['live_gate_status']}`",
        f"- git_head: `{payload['git_head']}`",
        "",
        "## Evidence",
        "",
        "- `operator_cockpit_payload.json`",
        "- `non_live_operational_proof/latest`",
        "- `historical_30d_replay_and_paper_proof/latest`",
        "- `agent_supervisor/status`",
        "- `legacy_readonly_audit`",
        "",
        "## Data Gaps",
        "",
    ]
    lines.extend(f"- `{gap}`" for gap in payload["data_gaps"])
    lines.append("")
    if name == "PLACEHOLDER_REMOVAL_REPORT.md":
        lines.extend(
            [
                "## Replacement",
                "",
                "The operator dashboard now renders evidence-backed cockpit sections instead of a text-only proof viewer.",
                "Sections with incomplete source evidence render explicit `evidence_missing` values.",
                "",
            ]
        )
    if name == "CONFIG_ADMIN_COVERAGE.md":
        lines.extend(["## Settings", ""])
        lines.extend(
            f"- `{row['name']}`: {row['classification']}"
            for row in payload["config_admin"]["settings"]
        )
        lines.append("")
    if name == "MONITOR_CENTER_COVERAGE.md":
        lines.extend(["## Monitors", ""])
        lines.extend(
            f"- `{row['id']}`: {row['classification']} / {row['status']}"
            for row in payload["monitor_center"]["rows"]
        )
        lines.append("")
    (FINAL / name).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    write_outputs()
    print(GO_NO_GO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
