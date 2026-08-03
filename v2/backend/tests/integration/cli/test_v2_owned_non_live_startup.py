"""Integration tests for v2_owned_non_live_startup."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


def test_build_payload_emits_components() -> None:
    from v2.backend.app.cli.v2_owned_non_live_startup import build_payload

    p = build_payload()
    assert p["worker_id"] == "v2_owned_non_live_startup"
    assert p["live_gate"] == "blocked_human_only"
    assert p["live_symbols"] == []
    assert p["approves_live"] is False
    assert p["go_no_go"] in (
        "V2_OWNED_NON_LIVE_STARTUP_READY",
        "V2_OWNED_NON_LIVE_STARTUP_BLOCKED",
    )
    components = {c["component"] for c in p["components"]}
    for required in (
        "native_ingestors",
        "native_feature_pipeline_snapshot",
        "native_rl_core_trainer_output",
        "orchestrator_arbitration",
        "trade_management_paper",
        "risk_gateway",
        "paper_execution",
        "shadow_outcome_observer",
        "rl_core_status_public_payload",
    ):
        assert required in components


def test_cli_writes_status_payload(tmp_path: Path) -> None:
    out = tmp_path / "v2_owned_non_live_startup_status.json"
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_owned_non_live_startup",
        "--write-evidence",
        "--out",
        str(out),
    ]
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    body = json.loads(out.read_text())
    assert body["live_gate"] == "blocked_human_only"
    assert body["approves_live"] is False
    assert body["any_unsafe_live_field"] is False


def test_cli_require_paper_only_passes_when_safe() -> None:
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_owned_non_live_startup",
        "--dry-run",
        "--require-paper-only",
    ]
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
