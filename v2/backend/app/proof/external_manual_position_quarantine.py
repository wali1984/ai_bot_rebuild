from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GO_NO_GO_MARKER = "2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_READY"
LIVE_GATE_STATUS = "blocked_human_only"
GENERATED_AT = "2026-05-09T00:00:00Z"

REQUIRED_ARTIFACTS = (
    "2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_REPORT.md",
    "GO_NO_GO.md",
    "ownership_classification_schema.json",
    "manual_external_positions.json",
    "quarantined_positions.json",
    "unattributed_executions.json",
    "duplicate_accounting_candidates.json",
    "risk_gateway_quarantine_rules.md",
    "operator_dashboard_payload.json",
    "evidence_manifest.json",
    "data_gaps.md",
)

DEFAULT_ALLOWED_OUTPUT_PREFIXES = (
    "claude_worklog/final_readiness/external_manual_position_quarantine/",
    "v2/frontend/public/external_manual_position_quarantine/",
)

REQUIRED_ATTRIBUTION_FIELDS = (
    "account_id",
    "symbol",
    "side_action",
    "source_module",
    "timestamp",
)

MODEL_DERIVED_REQUIRED_FIELDS = (
    "signal_id",
    "decision_id",
    "risk_decision_id",
    "execution_intent_id",
)


@dataclass(frozen=True, slots=True)
class PositionExecutionEvidence:
    evidence_id: str
    account_id: str | None
    symbol: str | None
    side_action: str | None
    source_module: str | None
    timestamp: str | None
    signal_id: str | None = None
    decision_id: str | None = None
    risk_decision_id: str | None = None
    execution_intent_id: str | None = None
    exchange_order_id: str | None = None
    position_size: str = "0"
    evidence_source: str = "deterministic_fixture"


def deterministic_quarantine_fixtures() -> tuple[PositionExecutionEvidence, ...]:
    return (
        PositionExecutionEvidence(
            evidence_id="v2_paper_btc_allow_001",
            account_id="paper_account_v2",
            symbol="BTCUSDT",
            side_action="open_long",
            source_module="v2.paper_trader",
            timestamp="2026-05-09T00:01:00Z",
            signal_id="sig_btc_001",
            decision_id="dec_btc_001",
            risk_decision_id="risk_btc_001",
            execution_intent_id="intent_btc_001",
            exchange_order_id="paper_order_btc_001",
            position_size="0.010",
            evidence_source="claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json",
        ),
        PositionExecutionEvidence(
            evidence_id="legacy_eth_close_002",
            account_id="legacy_account_primary",
            symbol="ETHUSDT",
            side_action="close_long",
            source_module="legacy.trading.trader",
            timestamp="2026-05-09T00:02:00Z",
            signal_id="legacy_sig_eth_002",
            exchange_order_id="legacy_order_eth_002",
            position_size="0.250",
            evidence_source="claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md",
        ),
        PositionExecutionEvidence(
            evidence_id="operator_manual_lab_short_003",
            account_id="primary_exchange_account",
            symbol="LABUSDT",
            side_action="manual_open_short",
            source_module="operator_manual",
            timestamp="2026-05-09T00:03:00Z",
            exchange_order_id="manual_lab_003",
            position_size="-1200",
            evidence_source="operator_note_manual_position_fixture",
        ),
        PositionExecutionEvidence(
            evidence_id="exchange_protective_lab_long_004",
            account_id="primary_exchange_account",
            symbol="LABUSDT",
            side_action="protective_long",
            source_module="exchange_side_protective",
            timestamp="2026-05-09T00:04:00Z",
            exchange_order_id="protective_lab_004",
            position_size="900",
            evidence_source="claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md",
        ),
        PositionExecutionEvidence(
            evidence_id="unknown_sol_fill_005",
            account_id="primary_exchange_account",
            symbol="SOLUSDT",
            side_action="open_short",
            source_module=None,
            timestamp="2026-05-09T00:05:00Z",
            exchange_order_id="unknown_sol_005",
            position_size="-12",
            evidence_source="read_only_exchange_snapshot_unavailable_fixture",
        ),
        PositionExecutionEvidence(
            evidence_id="duplicate_bnb_a_006",
            account_id="paper_account_v2",
            symbol="BNBUSDT",
            side_action="reduce_long",
            source_module="v2.paper_trader",
            timestamp="2026-05-09T00:06:00Z",
            signal_id="sig_bnb_006",
            decision_id="dec_bnb_006",
            risk_decision_id="risk_bnb_006",
            execution_intent_id="intent_bnb_006",
            exchange_order_id="dup_order_bnb_006",
            position_size="-0.50",
            evidence_source="claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/paper_ledger_30d.json",
        ),
        PositionExecutionEvidence(
            evidence_id="duplicate_bnb_b_007",
            account_id="paper_account_v2",
            symbol="BNBUSDT",
            side_action="reduce_long",
            source_module="v2.paper_ledger_replay",
            timestamp="2026-05-09T00:06:01Z",
            signal_id="sig_bnb_006",
            decision_id="dec_bnb_006",
            risk_decision_id="risk_bnb_006",
            execution_intent_id="intent_bnb_006",
            exchange_order_id="dup_order_bnb_006",
            position_size="-0.50",
            evidence_source="claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/paper_ledger_30d.json",
        ),
    )


def validate_output_dir(
    output_dir: str | Path,
    *,
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_OUTPUT_PREFIXES,
    workspace: str | Path | None = None,
) -> Path:
    root = Path(workspace or Path.cwd()).resolve()
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    try:
        rel = output.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"output directory is outside workspace: {output}") from exc

    normalized = rel.rstrip("/") + "/"
    if not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
        raise ValueError(
            "output directory is outside allowed prefixes: "
            f"{rel}; allowed={', '.join(allowed_prefixes)}"
        )
    return output


def classify_ownership(
    evidence: PositionExecutionEvidence,
    *,
    duplicate_exchange_order_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    missing = _missing_attribution_fields(evidence)
    duplicate_ids = duplicate_exchange_order_ids or frozenset()
    duplicate = bool(evidence.exchange_order_id and evidence.exchange_order_id in duplicate_ids)

    if duplicate:
        ownership = "duplicate_accounting"
        quarantine_reason = "duplicate_exchange_order_id"
    elif missing:
        ownership = "unknown_unattributed"
        quarantine_reason = "missing_required_attribution"
    elif evidence.source_module == "operator_manual":
        ownership = "manual_external"
        quarantine_reason = "operator_manual_source"
    elif evidence.source_module == "exchange_side_protective":
        ownership = "exchange_side_protective"
        quarantine_reason = "protective_exchange_side_position"
    elif evidence.source_module and evidence.source_module.startswith("v2."):
        missing_model_fields = [
            field
            for field in MODEL_DERIVED_REQUIRED_FIELDS
            if getattr(evidence, field) in (None, "")
        ]
        if missing_model_fields:
            ownership = "unknown_unattributed"
            quarantine_reason = "missing_v2_model_lineage"
            missing = [*missing, *missing_model_fields]
        else:
            ownership = "v2_owned"
            quarantine_reason = None
    elif evidence.source_module and evidence.source_module.startswith("legacy."):
        ownership = "legacy_owned"
        quarantine_reason = None
    else:
        ownership = "unknown_unattributed"
        quarantine_reason = "unknown_source_module"

    quarantined = ownership in {
        "manual_external",
        "exchange_side_protective",
        "unknown_unattributed",
        "duplicate_accounting",
    }
    return {
        "evidence_id": evidence.evidence_id,
        "account_id": evidence.account_id,
        "symbol": evidence.symbol,
        "side_action": evidence.side_action,
        "source_module": evidence.source_module,
        "signal_id": evidence.signal_id,
        "decision_id": evidence.decision_id,
        "risk_decision_id": evidence.risk_decision_id,
        "execution_intent_id": evidence.execution_intent_id,
        "exchange_order_id": evidence.exchange_order_id,
        "timestamp": evidence.timestamp,
        "position_size": evidence.position_size,
        "ownership_classification": ownership,
        "quarantined": quarantined,
        "quarantine_reason": quarantine_reason,
        "missing_attribution_fields": sorted(set(missing)),
        "source_confidence": _source_confidence(ownership, missing),
        "risk_impact": _risk_impact(ownership),
        "allowed_actions": ["monitor_only"] if quarantined else ["monitor_only", "paper_shadow_accounting"],
        "blocked_actions": _blocked_actions(ownership),
        "evidence_source": evidence.evidence_source,
        "live_gate_status": LIVE_GATE_STATUS,
    }


def build_external_manual_position_quarantine_proof() -> dict[str, Any]:
    fixtures = deterministic_quarantine_fixtures()
    duplicate_ids = _duplicate_exchange_order_ids(fixtures)
    classifications = [
        classify_ownership(item, duplicate_exchange_order_ids=duplicate_ids) for item in fixtures
    ]
    manual_external = [
        row for row in classifications if row["ownership_classification"] in {"manual_external", "exchange_side_protective"}
    ]
    quarantined = [row for row in classifications if row["quarantined"]]
    unattributed = [
        row for row in classifications if row["ownership_classification"] == "unknown_unattributed"
    ]
    duplicates = [
        row for row in classifications if row["ownership_classification"] == "duplicate_accounting"
    ]
    summary = {
        "generated_at": GENERATED_AT,
        "marker": GO_NO_GO_MARKER,
        "live_gate_status": LIVE_GATE_STATUS,
        "classification_count": len(classifications),
        "manual_external_count": len(manual_external),
        "quarantined_count": len(quarantined),
        "unattributed_execution_count": len(unattributed),
        "duplicate_accounting_candidate_count": len(duplicates),
        "v2_owned_count": sum(1 for row in classifications if row["ownership_classification"] == "v2_owned"),
        "legacy_owned_count": sum(1 for row in classifications if row["ownership_classification"] == "legacy_owned"),
        "risk_gateway_policy": "block_risk_add_on_quarantined_symbol_account",
        "trainer_reward_policy": "exclude_quarantined_executions_from_reward_attribution",
    }
    schema = {
        "generated_at": GENERATED_AT,
        "ownership_classes": [
            "v2_owned",
            "legacy_owned",
            "manual_external",
            "exchange_side_protective",
            "duplicate_accounting",
            "unknown_unattributed",
            "quarantined",
        ],
        "required_attribution": list(REQUIRED_ATTRIBUTION_FIELDS),
        "model_derived_required_attribution": list(MODEL_DERIVED_REQUIRED_FIELDS),
        "quarantine_rule": (
            "Any execution missing required attribution or using manual/external/protective/"
            "duplicate ownership is quarantined and monitor-only."
        ),
    }
    dashboard_payload = {
        "generated_at": GENERATED_AT,
        "go_no_go": GO_NO_GO_MARKER,
        "live_gate_status": LIVE_GATE_STATUS,
        "summary": summary,
        "ownership_rows": classifications,
        "manual_external_positions": manual_external,
        "quarantined_positions": quarantined,
        "unattributed_executions": unattributed,
        "duplicate_accounting_candidates": duplicates,
        "risk_gateway_rules": _risk_gateway_rules(),
        "data_gaps": _data_gaps(),
    }
    manifest = {
        "generated_at": GENERATED_AT,
        "marker": GO_NO_GO_MARKER,
        "live_gate_status": LIVE_GATE_STATUS,
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "allowed_output_prefixes": list(DEFAULT_ALLOWED_OUTPUT_PREFIXES),
        "evidence_sources": [
            "claude_worklog/final_readiness/non_live_operational_proof/latest/paper_ledger_result.json",
            "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/paper_ledger_30d.json",
            "claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md",
            "claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md",
        ],
        "operator_dashboard_static_path": "v2/frontend/public/external_manual_position_quarantine/latest/",
    }
    return {
        "summary": summary,
        "ownership_classification_schema": schema,
        "manual_external_positions": {"positions": manual_external},
        "quarantined_positions": {"positions": quarantined},
        "unattributed_executions": {"executions": unattributed},
        "duplicate_accounting_candidates": {"candidates": duplicates},
        "operator_dashboard_payload": dashboard_payload,
        "evidence_manifest": manifest,
        "data_gaps": _data_gaps(),
        "risk_gateway_rules": _risk_gateway_rules(),
    }


def write_external_manual_position_quarantine_proof(
    output_dir: str | Path,
    *,
    public_output_dir: str | Path | None = None,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    output = validate_output_dir(output_dir, workspace=workspace)
    output.mkdir(parents=True, exist_ok=True)
    proof = build_external_manual_position_quarantine_proof()

    _write_json(output / "ownership_classification_schema.json", proof["ownership_classification_schema"])
    _write_json(output / "manual_external_positions.json", proof["manual_external_positions"])
    _write_json(output / "quarantined_positions.json", proof["quarantined_positions"])
    _write_json(output / "unattributed_executions.json", proof["unattributed_executions"])
    _write_json(output / "duplicate_accounting_candidates.json", proof["duplicate_accounting_candidates"])
    _write_json(output / "operator_dashboard_payload.json", proof["operator_dashboard_payload"])
    _write_json(output / "evidence_manifest.json", proof["evidence_manifest"])
    _write_report(output / "2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_REPORT.md", proof)
    _write_risk_rules(output / "risk_gateway_quarantine_rules.md", proof["risk_gateway_rules"])
    _write_data_gaps(output / "data_gaps.md", proof["data_gaps"])
    (output / "GO_NO_GO.md").write_text(GO_NO_GO_MARKER + "\n", encoding="utf-8")

    if public_output_dir is not None:
        public_output = validate_output_dir(public_output_dir, workspace=workspace)
        public_output.mkdir(parents=True, exist_ok=True)
        for artifact in REQUIRED_ARTIFACTS:
            shutil.copy2(output / artifact, public_output / artifact)

    return proof


def _duplicate_exchange_order_ids(fixtures: tuple[PositionExecutionEvidence, ...]) -> frozenset[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in fixtures:
        if not item.exchange_order_id:
            continue
        if item.exchange_order_id in seen:
            duplicates.add(item.exchange_order_id)
        seen.add(item.exchange_order_id)
    return frozenset(duplicates)


def _missing_attribution_fields(evidence: PositionExecutionEvidence) -> list[str]:
    return [
        field
        for field in REQUIRED_ATTRIBUTION_FIELDS
        if getattr(evidence, field) in (None, "")
    ]


def _source_confidence(ownership: str, missing: list[str]) -> str:
    if missing:
        return "low_missing_attribution"
    if ownership in {"v2_owned", "legacy_owned"}:
        return "high"
    if ownership == "duplicate_accounting":
        return "high_duplicate_detected"
    return "medium_requires_human_reconciliation"


def _risk_impact(ownership: str) -> str:
    if ownership in {"manual_external", "exchange_side_protective"}:
        return "risk_add_blocked_until_human_reconciled"
    if ownership in {"unknown_unattributed", "duplicate_accounting"}:
        return "risk_limits_and_rewards_excluded_until_attributed"
    return "eligible_for_read_only_accounting"


def _blocked_actions(ownership: str) -> list[str]:
    if ownership == "v2_owned":
        return ["live_execution"]
    if ownership == "legacy_owned":
        return ["v2_ownership_assumption", "live_execution"]
    return [
        "risk_add",
        "hedge",
        "dca",
        "increase_position",
        "trainer_reward_attribution",
        "v2_ownership_assumption",
        "live_execution",
    ]


def _risk_gateway_rules() -> list[dict[str, str]]:
    return [
        {
            "rule": "deny_external_manual_position_quarantined",
            "effect": "block risk-add on quarantined symbol/account",
        },
        {
            "rule": "deny_manual_external_hedge_or_dca",
            "effect": "block hedge/DCA/increase on manual_external positions",
        },
        {
            "rule": "exclude_quarantined_reward_attribution",
            "effect": "block trainer reward/PnL attribution from quarantined executions",
        },
        {
            "rule": "allow_monitor_only_quarantine_state",
            "effect": "allow read-only dashboard monitoring without auto-close",
        },
    ]


def _data_gaps() -> list[str]:
    return [
        "Read-only exchange position/order/fill snapshots were not available to this deterministic run.",
        "Manual operator reconciliation workflow is intentionally not implemented in this non-live milestone.",
        "Quarantined positions are monitor-only; no auto-close or exchange-side remediation is allowed.",
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(path: Path, proof: dict[str, Any]) -> None:
    summary = proof["summary"]
    lines = [
        "# 2X External Manual Position Quarantine",
        "",
        f"- marker: `{GO_NO_GO_MARKER}`",
        f"- generated_at: `{summary['generated_at']}`",
        f"- live_gate_status: `{summary['live_gate_status']}`",
        f"- classification_count: {summary['classification_count']}",
        f"- manual_external_count: {summary['manual_external_count']}",
        f"- quarantined_count: {summary['quarantined_count']}",
        f"- unattributed_execution_count: {summary['unattributed_execution_count']}",
        f"- duplicate_accounting_candidate_count: {summary['duplicate_accounting_candidate_count']}",
        "",
        "## Operator Interpretation",
        "",
        "V2 must not assume ownership of manual, exchange-side protective, unknown, or",
        "duplicate-accounted positions. Those rows are quarantined and restricted to",
        "monitor-only state until explicit human reconciliation exists.",
        "",
        "## Required Artifacts",
        "",
    ]
    lines.extend(f"- `{artifact}`" for artifact in REQUIRED_ARTIFACTS)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_risk_rules(path: Path, rules: list[dict[str, str]]) -> None:
    lines = ["# Risk Gateway Quarantine Rules", ""]
    for rule in rules:
        lines.append(f"- `{rule['rule']}`: {rule['effect']}")
    lines.extend(
        [
            "",
            "The rules are non-live stubs. They add no exchange action path and do not",
            "auto-close or mutate any position.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_data_gaps(path: Path, gaps: list[str]) -> None:
    lines = ["# Data Gaps", ""]
    lines.extend(f"- {gap}" for gap in gaps)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
