from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.proof import (
    GO_NO_GO_MARKER,
    REQUIRED_ARTIFACTS,
    build_non_live_proof,
    write_non_live_proof,
)
from v2.backend.app.proof.non_live_operational_proof import (
    SCENARIO_FIXTURE_PATH,
    deterministic_scenarios,
)


def test_go_no_go_marker_is_codex_review_marker() -> None:
    assert GO_NO_GO_MARKER == "NON_LIVE_OPERATOR_PROOF_HARNESS_READY_FOR_CODEX_REVIEW"


def test_scenarios_are_loaded_from_local_fixture() -> None:
    assert SCENARIO_FIXTURE_PATH.exists()

    scenarios = deterministic_scenarios()
    lab = next(item for item in scenarios if item.symbol == "LABUSDT")

    assert lab.scenario_id == "lab_hedge_unwind_short_squeeze"
    assert lab.expected_v2_action == "block_or_reduce"


def test_write_non_live_proof_emits_all_required_artifacts(tmp_path: Path) -> None:
    write_non_live_proof(tmp_path)

    missing = [name for name in REQUIRED_ARTIFACTS if not (tmp_path / name).exists()]

    assert missing == []
    assert (tmp_path / "GO_NO_GO.md").read_text() == GO_NO_GO_MARKER


def test_risk_gateway_blocks_stale_data(tmp_path: Path) -> None:
    write_non_live_proof(tmp_path)
    payload = json.loads((tmp_path / "risk_gateway_result.json").read_text())
    stale = next(
        item for item in payload["decisions"] if item["scenario_id"] == "stale_data_blocked"
    )

    assert stale["risk_decision"] == "deny"
    assert stale["block_or_allow_reason"] == "stale_feature_snapshot"
    assert stale["feature_flags"]["stale"] == ["feature_snapshot"]


def test_lab_hedge_unwind_case_is_blocked_or_reduced(tmp_path: Path) -> None:
    write_non_live_proof(tmp_path)
    payload = json.loads((tmp_path / "shadow_comparison_result.json").read_text())
    lab = next(item for item in payload["comparisons"] if item["symbol"] == "LABUSDT")

    assert lab["risk_decision"] == "deny"
    assert lab["v2_action"] == "block_or_reduce"
    assert lab["diverged"] is True
    assert "short_squeeze" in lab["block_or_allow_reason"]


def test_paper_ledger_records_non_live_events(tmp_path: Path) -> None:
    write_non_live_proof(tmp_path)
    payload = json.loads((tmp_path / "paper_ledger_result.json").read_text())
    event_types = {event["ledger_event_type"] for event in payload["events"]}

    assert {"open", "close", "reduce", "block"}.issubset(event_types)
    assert all(event["non_live_only"] is True for event in payload["events"])
    assert all(event["live_gate_status"] == "blocked_human_only" for event in payload["events"])


def test_shadow_comparison_emits_legacy_vs_v2_difference() -> None:
    proof = build_non_live_proof()
    comparisons = proof["shadow_comparison_result"]["comparisons"]

    assert any(item["diverged"] for item in comparisons)
    assert all("legacy_action" in item and "v2_action" in item for item in comparisons)


def test_required_lineage_fields_are_present(tmp_path: Path) -> None:
    write_non_live_proof(tmp_path)
    payload = json.loads((tmp_path / "replay_backtest_result.json").read_text())
    required = {
        "feature_snapshot_id",
        "prediction_id",
        "decision_id",
        "risk_decision_id",
        "execution_intent_id",
        "paper_trade_id",
        "shadow_decision_id",
        "symbol",
        "side",
        "direction",
        "confidence",
        "risk_decision",
        "block_or_allow_reason",
        "paper_pnl",
        "explanation_payload",
        "feature_flags",
        "live_gate_status",
        "model_version",
        "checkpoint_id",
        "confidence_raw",
        "confidence_calibrated",
        "trainer_worker_liveness",
    }

    for scenario in payload["scenarios"]:
        assert required.issubset(scenario)


def test_harness_does_not_use_live_side_effect_terms() -> None:
    root = Path("v2/backend/app/proof")
    text = "\n".join(path.read_text() for path in root.rglob("*.py"))

    forbidden = [
        "redis" + "-cli",
        "XA" + "DD",
        "XD" + "EL",
        "FLUSH" + "DB",
        "FLUSH" + "ALL",
        "create" + "_order",
        "cancel" + "_order",
        "change" + "_leverage",
        "change" + "_margin",
        "systemctl" + " restart",
        "LIVE_TRADING" + "_ENABLED",
    ]
    assert [token for token in forbidden if token in text] == []
