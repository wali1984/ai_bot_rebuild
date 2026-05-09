from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from v2.backend.app.proof.external_manual_position_quarantine import (
    GO_NO_GO_MARKER,
    REQUIRED_ARTIFACTS,
    PositionExecutionEvidence,
    build_external_manual_position_quarantine_proof,
    classify_ownership,
    validate_output_dir,
    write_external_manual_position_quarantine_proof,
)


def test_quarantine_proof_emits_all_required_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/external_manual_position_quarantine/latest"

    write_external_manual_position_quarantine_proof(output, workspace=tmp_path)

    missing = [artifact for artifact in REQUIRED_ARTIFACTS if not (output / artifact).exists()]
    assert missing == []
    assert (output / "GO_NO_GO.md").read_text().strip() == GO_NO_GO_MARKER


def test_output_prefix_validation_rejects_bad_path(tmp_path: Path) -> None:
    bad = tmp_path / "claude_worklog/final_readiness/non_live_operational_proof/latest"

    with pytest.raises(ValueError, match="outside allowed prefixes"):
        validate_output_dir(bad, workspace=tmp_path)

    assert not bad.exists()


def test_cli_runs_and_mirrors_public_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/external_manual_position_quarantine/latest"
    public = tmp_path / "v2/frontend/public/external_manual_position_quarantine/latest"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "v2.backend.app.cli.external_manual_position_quarantine",
            "--output-dir",
            str(output),
            "--public-output-dir",
            str(public),
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env={"PYTHONPATH": str(Path.cwd())},
    )

    assert result.returncode == 0, result.stderr
    assert GO_NO_GO_MARKER in result.stdout
    assert [artifact for artifact in REQUIRED_ARTIFACTS if not (output / artifact).exists()] == []
    assert [artifact for artifact in REQUIRED_ARTIFACTS if not (public / artifact).exists()] == []


def test_missing_attribution_quarantines_unknown_execution() -> None:
    row = classify_ownership(
        PositionExecutionEvidence(
            evidence_id="missing_source",
            account_id="acct",
            symbol="SOLUSDT",
            side_action="open_short",
            source_module=None,
            timestamp="2026-05-09T00:00:00Z",
            exchange_order_id="order_missing_source",
        )
    )

    assert row["ownership_classification"] == "unknown_unattributed"
    assert row["quarantined"] is True
    assert "source_module" in row["missing_attribution_fields"]
    assert "trainer_reward_attribution" in row["blocked_actions"]


def test_duplicate_exchange_order_id_is_accounting_candidate() -> None:
    proof = build_external_manual_position_quarantine_proof()
    candidates = proof["duplicate_accounting_candidates"]["candidates"]

    assert candidates
    assert {row["exchange_order_id"] for row in candidates} == {"dup_order_bnb_006"}
    assert all(row["quarantined"] for row in candidates)


def test_risk_add_block_on_quarantined_symbol_account() -> None:
    proof = build_external_manual_position_quarantine_proof()
    quarantined = proof["quarantined_positions"]["positions"]

    assert any(row["symbol"] == "LABUSDT" for row in quarantined)
    assert all("risk_add" in row["blocked_actions"] for row in quarantined)
    assert all(row["allowed_actions"] == ["monitor_only"] for row in quarantined)


def test_dashboard_payload_exposes_quarantine_state(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/external_manual_position_quarantine/latest"
    write_external_manual_position_quarantine_proof(output, workspace=tmp_path)
    payload = json.loads((output / "operator_dashboard_payload.json").read_text())

    assert payload["go_no_go"] == GO_NO_GO_MARKER
    assert payload["live_gate_status"] == "blocked_human_only"
    assert payload["summary"]["quarantined_count"] >= 4
    assert payload["manual_external_positions"]
    assert payload["duplicate_accounting_candidates"]


def test_quarantine_code_has_no_live_side_effect_terms() -> None:
    text = Path("v2/backend/app/proof/external_manual_position_quarantine.py").read_text()
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
