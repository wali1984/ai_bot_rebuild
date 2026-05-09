from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from v2.backend.app.proof.historical_30d_replay_and_paper_proof import (
    GO_NO_GO_MARKER,
    REQUIRED_ARTIFACTS,
    build_historical_30d_proof,
    validate_output_dir,
    write_historical_30d_proof,
)


def test_historical_30d_proof_emits_all_required_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest"

    write_historical_30d_proof(output, workspace=tmp_path)

    missing = [artifact for artifact in REQUIRED_ARTIFACTS if not (output / artifact).exists()]
    assert missing == []
    assert (output / "GO_NO_GO.md").read_text().strip() == GO_NO_GO_MARKER


def test_historical_30d_output_prefix_validation_rejects_bad_path(tmp_path: Path) -> None:
    bad = tmp_path / "claude_worklog/final_readiness/non_live_operational_proof/latest"

    with pytest.raises(ValueError, match="outside allowed prefixes"):
        validate_output_dir(bad, workspace=tmp_path)

    assert not bad.exists()


def test_historical_30d_cli_runs_and_mirrors_public_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest"
    public = tmp_path / "v2/frontend/public/historical_30d_replay_and_paper_proof/latest"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "v2.backend.app.cli.historical_30d_replay_and_paper_proof",
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


def test_historical_30d_blocks_lab_hedge_unwind_and_stale_data() -> None:
    proof = build_historical_30d_proof()
    blocks = proof["v2_risk_blocks"]["risk_blocks"]

    reasons = {row["reason"] for row in blocks}
    assert "stale_feature_snapshot" in reasons
    assert "short_squeeze_and_hedge_unwind_residual_exposure" in reasons
    assert any(row["symbol"] == "LABUSDT" for row in blocks)


def test_historical_30d_preserves_winners_and_reduces_losers(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest"
    write_historical_30d_proof(output, workspace=tmp_path)

    winners = json.loads((output / "v2_preserved_winners.json").read_text())
    reduced = json.loads((output / "v2_reduced_or_rejected_trades.json").read_text())
    paper = json.loads((output / "paper_ledger_30d.json").read_text())
    shadow = json.loads((output / "shadow_comparison_30d.json").read_text())

    assert len(winners["preserved_winners"]) >= 2
    assert len(reduced["reduced_or_rejected_trades"]) >= 3
    assert paper["summary"]["blocked_or_reduced_events"] >= 3
    assert any(row["diverged"] for row in shadow["comparisons"])
    assert all(row["live_gate_status"] == "blocked_human_only" for row in shadow["comparisons"])


def test_historical_30d_dashboard_payload_has_required_sections(tmp_path: Path) -> None:
    output = tmp_path / "claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest"
    write_historical_30d_proof(output, workspace=tmp_path)
    payload = json.loads((output / "operator_dashboard_payload.json").read_text())

    assert payload["go_no_go"] == GO_NO_GO_MARKER
    assert payload["live_gate_status"] == "blocked_human_only"
    assert payload["risk_blocks"]
    assert payload["preserved_winners"]
    assert payload["reduced_or_rejected"]
    assert payload["paper_ledger_summary"]["event_count"] >= 5
    assert payload["shadow_summary"]["divergence_count"] >= 1


def test_historical_30d_proof_code_has_no_live_side_effect_terms() -> None:
    text = Path("v2/backend/app/proof/historical_30d_replay_and_paper_proof.py").read_text()
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
