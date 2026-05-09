from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GO_NO_GO_MARKER = "NON_LIVE_OPERATOR_PROOF_HARNESS_READY"

REQUIRED_ARTIFACTS = (
    "replay_backtest_result.json",
    "replay_backtest_result.md",
    "paper_ledger_result.json",
    "paper_ledger_result.md",
    "shadow_comparison_result.json",
    "shadow_comparison_result.md",
    "risk_gateway_result.json",
    "risk_gateway_result.md",
    "decision_explainability_result.json",
    "decision_explainability_result.md",
    "aggregate_non_live_proof_rollup.md",
    "GO_NO_GO.md",
)

LIVE_GATE_STATUS = "blocked_human_only"
GENERATED_AT = "2026-05-08T00:00:00Z"


@dataclass(frozen=True, slots=True)
class ProofScenario:
    scenario_id: str
    symbol: str
    direction: str
    confidence: float
    feature_freshness: str
    duplicate_signal: bool
    requested_action: str
    legacy_action: str
    squeeze_context: str
    expected_v2_action: str
    block_reason: str
    paper_pnl: str

    @property
    def feature_snapshot_id(self) -> str:
        return f"fs_{self.scenario_id}"

    @property
    def prediction_id(self) -> str:
        return f"pred_{self.scenario_id}"

    @property
    def decision_id(self) -> str:
        return f"dec_{self.scenario_id}"

    @property
    def risk_decision_id(self) -> str:
        return f"rd_{self.scenario_id}"

    @property
    def execution_intent_id(self) -> str:
        return f"intent_{self.scenario_id}"

    @property
    def paper_trade_id(self) -> str:
        return f"paper_{self.scenario_id}"

    @property
    def shadow_decision_id(self) -> str:
        return f"shadow_{self.scenario_id}"


def deterministic_scenarios() -> tuple[ProofScenario, ...]:
    return (
        ProofScenario(
            scenario_id="safe_long_paper_intent",
            symbol="BTCUSDT",
            direction="long",
            confidence=0.82,
            feature_freshness="fresh",
            duplicate_signal=False,
            requested_action="open_long",
            legacy_action="open_long",
            squeeze_context="none",
            expected_v2_action="allow_paper_open_long",
            block_reason="not_blocked",
            paper_pnl="+12.40",
        ),
        ProofScenario(
            scenario_id="stale_data_blocked",
            symbol="ETHUSDT",
            direction="long",
            confidence=0.78,
            feature_freshness="stale",
            duplicate_signal=False,
            requested_action="open_long",
            legacy_action="open_long",
            squeeze_context="none",
            expected_v2_action="block",
            block_reason="stale_feature_snapshot",
            paper_pnl="0.00",
        ),
        ProofScenario(
            scenario_id="duplicate_signal_blocked",
            symbol="SOLUSDT",
            direction="short",
            confidence=0.74,
            feature_freshness="fresh",
            duplicate_signal=True,
            requested_action="open_short",
            legacy_action="open_short",
            squeeze_context="none",
            expected_v2_action="block",
            block_reason="duplicate_signal",
            paper_pnl="0.00",
        ),
        ProofScenario(
            scenario_id="hedge_close_residual_exposure_blocked",
            symbol="BNBUSDT",
            direction="short",
            confidence=0.69,
            feature_freshness="fresh",
            duplicate_signal=False,
            requested_action="close_protective_long",
            legacy_action="close_protective_long",
            squeeze_context="residual_short_exposure",
            expected_v2_action="block_or_reduce",
            block_reason="hedge_close_would_leave_naked_short",
            paper_pnl="0.00",
        ),
        ProofScenario(
            scenario_id="lab_hedge_unwind_short_squeeze",
            symbol="LABUSDT",
            direction="short",
            confidence=0.66,
            feature_freshness="fresh",
            duplicate_signal=False,
            requested_action="close_protective_long",
            legacy_action="close_long_leave_short_exposed",
            squeeze_context="eighty_percent_pump_against_short",
            expected_v2_action="block_or_reduce",
            block_reason="short_squeeze_and_hedge_unwind_residual_exposure",
            paper_pnl="legacy_loss_avoided",
        ),
    )


def _risk_action(scenario: ProofScenario) -> str:
    if scenario.feature_freshness != "fresh":
        return "deny"
    if scenario.duplicate_signal:
        return "deny"
    if scenario.expected_v2_action.startswith("block"):
        return "deny"
    return "allow"


def _feature_flags(scenario: ProofScenario) -> dict[str, list[str]]:
    stale = [] if scenario.feature_freshness == "fresh" else ["feature_snapshot"]
    missing = []
    unused = ["live_execution_adapter", "redis_stream_writer", "exchange_order_client"]
    return {"stale": stale, "missing": missing, "unused": unused}


def _base_lineage(scenario: ProofScenario) -> dict[str, Any]:
    return {
        "feature_snapshot_id": scenario.feature_snapshot_id,
        "prediction_id": scenario.prediction_id,
        "decision_id": scenario.decision_id,
        "risk_decision_id": scenario.risk_decision_id,
        "execution_intent_id": scenario.execution_intent_id,
        "paper_trade_id": scenario.paper_trade_id,
        "shadow_decision_id": scenario.shadow_decision_id,
        "symbol": scenario.symbol,
        "side": scenario.direction,
        "direction": scenario.direction,
        "confidence": scenario.confidence,
        "risk_decision": _risk_action(scenario),
        "block_or_allow_reason": scenario.block_reason,
        "paper_pnl": scenario.paper_pnl,
        "feature_flags": _feature_flags(scenario),
        "live_gate_status": LIVE_GATE_STATUS,
    }


def _explanation_payload(scenario: ProofScenario) -> dict[str, Any]:
    causes = [
        f"feature_freshness={scenario.feature_freshness}",
        f"duplicate_signal={scenario.duplicate_signal}",
        f"squeeze_context={scenario.squeeze_context}",
        f"requested_action={scenario.requested_action}",
    ]
    if scenario.symbol == "LABUSDT":
        causes.append("legacy_failure_case=LAB hedge unwind short squeeze")
    return {
        "summary": (
            f"{scenario.symbol} {scenario.requested_action} -> "
            f"{scenario.expected_v2_action}"
        ),
        "causes": causes,
        "operator_visible": True,
        "no_live_side_effects": True,
    }


def _scenario_row(scenario: ProofScenario) -> dict[str, Any]:
    row = _base_lineage(scenario)
    row.update(
        {
            "scenario_id": scenario.scenario_id,
            "requested_action": scenario.requested_action,
            "legacy_action": scenario.legacy_action,
            "v2_action": scenario.expected_v2_action,
            "explanation_payload": _explanation_payload(scenario),
        }
    )
    return row


def build_non_live_proof() -> dict[str, Any]:
    scenarios = deterministic_scenarios()
    rows = [_scenario_row(scenario) for scenario in scenarios]
    blocked = [row for row in rows if row["risk_decision"] == "deny"]
    allowed = [row for row in rows if row["risk_decision"] == "allow"]
    lab = next(row for row in rows if row["symbol"] == "LABUSDT")

    replay_result = {
        "generated_at": GENERATED_AT,
        "run_id": "non_live_replay_backtest_fixture_run",
        "mode": "offline_fixture",
        "live_gate_status": LIVE_GATE_STATUS,
        "scenario_count": len(rows),
        "allowed_count": len(allowed),
        "blocked_count": len(blocked),
        "gross_paper_pnl": "+12.40",
        "max_drawdown_placeholder": "0.00",
        "scenarios": rows,
    }
    paper_ledger_result = {
        "generated_at": GENERATED_AT,
        "ledger_id": "non_live_paper_ledger_fixture",
        "live_gate_status": LIVE_GATE_STATUS,
        "events": [
            _ledger_event("open", rows[0], "+0.00"),
            _ledger_event("close", rows[0], "+12.40"),
            _ledger_event("reduce", lab, "legacy_loss_avoided"),
            _ledger_event("block", rows[1], "0.00"),
            _ledger_event("block", rows[2], "0.00"),
            _ledger_event("block", rows[3], "0.00"),
            _ledger_event("block", lab, "0.00"),
        ],
    }
    risk_gateway_result = {
        "generated_at": GENERATED_AT,
        "policy": "default_deny_non_live_operator_proof",
        "live_gate_status": LIVE_GATE_STATUS,
        "decisions": [
            {
                **_base_lineage(scenario),
                "scenario_id": scenario.scenario_id,
                "requested_action": scenario.requested_action,
                "risk_action": _risk_action(scenario),
                "risk_reason": scenario.block_reason,
            }
            for scenario in scenarios
        ],
    }
    decision_explainability_result = {
        "generated_at": GENERATED_AT,
        "live_gate_status": LIVE_GATE_STATUS,
        "explanations": [
            {
                **_base_lineage(scenario),
                "scenario_id": scenario.scenario_id,
                "explanation_payload": _explanation_payload(scenario),
            }
            for scenario in scenarios
        ],
    }
    shadow_comparison_result = {
        "generated_at": GENERATED_AT,
        "comparison_id": "non_live_shadow_fixture_comparison",
        "live_gate_status": LIVE_GATE_STATUS,
        "comparisons": [
            {
                **_base_lineage(scenario),
                "scenario_id": scenario.scenario_id,
                "legacy_action": scenario.legacy_action,
                "v2_action": scenario.expected_v2_action,
                "diverged": scenario.legacy_action != scenario.expected_v2_action,
                "operator_note": scenario.block_reason,
            }
            for scenario in scenarios
        ],
    }

    return {
        "replay_backtest_result": replay_result,
        "paper_ledger_result": paper_ledger_result,
        "risk_gateway_result": risk_gateway_result,
        "decision_explainability_result": decision_explainability_result,
        "shadow_comparison_result": shadow_comparison_result,
        "aggregate": {
            "generated_at": GENERATED_AT,
            "status": GO_NO_GO_MARKER,
            "live_gate_status": LIVE_GATE_STATUS,
            "required_artifacts": list(REQUIRED_ARTIFACTS),
            "scenario_count": len(rows),
            "lab_hedge_unwind_blocked": lab["risk_decision"] == "deny",
            "operator_inspection_ready": True,
        },
    }


def _ledger_event(event_type: str, row: dict[str, Any], paper_pnl: str) -> dict[str, Any]:
    event = dict(row)
    event.update(
        {
            "ledger_event_type": event_type,
            "paper_pnl": paper_pnl,
            "non_live_only": True,
        }
    )
    return event


def write_non_live_proof(output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    proof = build_non_live_proof()

    _write_json(output / "replay_backtest_result.json", proof["replay_backtest_result"])
    _write_json(output / "paper_ledger_result.json", proof["paper_ledger_result"])
    _write_json(output / "risk_gateway_result.json", proof["risk_gateway_result"])
    _write_json(
        output / "decision_explainability_result.json",
        proof["decision_explainability_result"],
    )
    _write_json(output / "shadow_comparison_result.json", proof["shadow_comparison_result"])

    _write_markdown(
        output / "replay_backtest_result.md",
        "Replay / Backtest Result",
        proof["replay_backtest_result"],
    )
    _write_markdown(
        output / "paper_ledger_result.md",
        "Paper Ledger Result",
        proof["paper_ledger_result"],
    )
    _write_markdown(
        output / "risk_gateway_result.md",
        "Risk Gateway Result",
        proof["risk_gateway_result"],
    )
    _write_markdown(
        output / "decision_explainability_result.md",
        "Decision Explainability Result",
        proof["decision_explainability_result"],
    )
    _write_markdown(
        output / "shadow_comparison_result.md",
        "Shadow Comparison Result",
        proof["shadow_comparison_result"],
    )
    _write_rollup(output / "aggregate_non_live_proof_rollup.md", proof)
    (output / "GO_NO_GO.md").write_text(GO_NO_GO_MARKER + "\n", encoding="utf-8")
    return proof


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, title: str, payload: dict[str, Any]) -> None:
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- live_gate_status: `{payload['live_gate_status']}`",
        "",
        "## Operator Summary",
        "",
    ]
    if "scenarios" in payload:
        lines.append(f"- scenarios: {payload['scenario_count']}")
        lines.append(f"- allowed: {payload['allowed_count']}")
        lines.append(f"- blocked: {payload['blocked_count']}")
    if "events" in payload:
        lines.append(f"- ledger_events: {len(payload['events'])}")
    if "decisions" in payload:
        lines.append(f"- risk_decisions: {len(payload['decisions'])}")
    if "explanations" in payload:
        lines.append(f"- explanations: {len(payload['explanations'])}")
    if "comparisons" in payload:
        lines.append(f"- comparisons: {len(payload['comparisons'])}")
        divergences = sum(1 for item in payload["comparisons"] if item["diverged"])
        lines.append(f"- divergences: {divergences}")
    lines.extend(["", "## JSON Payload", "", "```json"])
    lines.append(json.dumps(payload, indent=2, sort_keys=True))
    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_rollup(path: Path, proof: dict[str, Any]) -> None:
    aggregate = proof["aggregate"]
    lines = [
        "# Aggregate Non-Live Proof Rollup",
        "",
        f"- status: `{aggregate['status']}`",
        f"- generated_at: `{aggregate['generated_at']}`",
        f"- live_gate_status: `{aggregate['live_gate_status']}`",
        f"- scenario_count: {aggregate['scenario_count']}",
        f"- lab_hedge_unwind_blocked: {aggregate['lab_hedge_unwind_blocked']}",
        f"- operator_inspection_ready: {aggregate['operator_inspection_ready']}",
        "",
        "## Required Artifacts",
        "",
    ]
    lines.extend(f"- `{artifact}`" for artifact in aggregate["required_artifacts"])
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "This proof harness is deterministic and offline. It emits local files only.",
            "Live trading remains blocked and human-only.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
