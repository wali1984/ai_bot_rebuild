"""Tests for the V2 throughput-plan Codex CLI command remediation."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.throughput.ai_throughput_acceleration import (
    build_cloud_acceleration_options,
    build_parallel_lane_matrix,
)
from v2.backend.app.services.throughput.codex_cli_command_remediation import (
    INVALID_REVIEW_COMMAND_FORMS,
    VALID_REVIEW_COMMAND_TEMPLATES,
    build_remediation_status,
    default_paths,
    run_remediation,
    scan_artifacts_for_invalid_review_commands,
)


# ---------------------------------------------------------------------------
# Static checks on throughput-module command strings
# ---------------------------------------------------------------------------


def test_parallel_lane_matrix_has_no_invalid_codex_review_commands():
    matrix = build_parallel_lane_matrix()
    for lane in matrix["lanes"]:
        cmd = lane["codex_review_command"]
        for invalid in INVALID_REVIEW_COMMAND_FORMS:
            assert invalid not in cmd, (lane["lane_id"], cmd)
        assert "codex exec review --uncommitted" in cmd or "codex review --uncommitted" in cmd, (
            lane["lane_id"],
            cmd,
        )


def test_cloud_acceleration_options_text_uses_valid_command_templates_only():
    opts = build_cloud_acceleration_options()
    blob = json.dumps(opts)
    for invalid in INVALID_REVIEW_COMMAND_FORMS:
        assert invalid not in blob, invalid


def test_recommended_templates_are_valid_codex_subcommands():
    for tpl in VALID_REVIEW_COMMAND_TEMPLATES:
        head = tpl.split('"')[0].strip()
        assert head in {
            "codex review --uncommitted",
            "codex exec review --uncommitted",
            "codex exec",
        }, tpl


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def test_scanner_flags_invalid_form_in_synthetic_file(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"codex_review_command": "codex exec --review v2/"}),
        encoding="utf-8",
    )
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "codex_review_command": 'codex exec review --uncommitted "Review v2/."',
            }
        ),
        encoding="utf-8",
    )

    result = scan_artifacts_for_invalid_review_commands([tmp_path])
    assert result["passed"] is False
    paths_with_hit = {hit["path"] for hit in result["hits"]}
    assert str(bad) in paths_with_hit
    assert str(good) not in paths_with_hit


def test_scanner_passes_when_only_valid_forms_present(tmp_path: Path):
    f = tmp_path / "valid.json"
    f.write_text(
        json.dumps(
            {"command": 'codex exec review --uncommitted "Scoped prompt only."'}
        ),
        encoding="utf-8",
    )
    result = scan_artifacts_for_invalid_review_commands([tmp_path])
    assert result["passed"] is True
    assert result["hits"] == []


# ---------------------------------------------------------------------------
# Probe + remediation orchestrator
# ---------------------------------------------------------------------------


def _stub_probe() -> dict:
    return {
        "schema_version": "test_probe",
        "generated_utc": "2026-05-23T19:00:00Z",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "codex_binary_path_present": True,
        "codex_version": "codex-cli 0.128.0",
        "supports_codex_review": True,
        "supports_codex_exec": True,
        "supports_codex_exec_review": True,
        "invalid_form_rejected_observed": True,
        "unsupported_forms": list(INVALID_REVIEW_COMMAND_FORMS),
        "recommended_review_command_templates": list(VALID_REVIEW_COMMAND_TEMPLATES),
        "review_flags_observed": {"uncommitted": True, "base_branch": True, "commit": True},
        "no_path_argument_accepted_for_review": True,
        "verification_commands": [],
    }


def test_remediation_status_carries_safety_pins():
    status = build_remediation_status(
        probe=_stub_probe(),
        scan_before={"hits": [], "passed": True, "files_scanned": 0},
        scan_after={"hits": [], "passed": True, "files_scanned": 0},
        refreshed_packet_dir=Path("/tmp/refreshed"),
        refreshed_public_dir=Path("/tmp/public"),
    )
    for k in (
        "approves_live",
        "approves_canary",
        "approves_legacy_shutdown",
        "approves_redis_trim",
        "scheduler_installed",
        "gpu_training_dispatched",
        "codex_fast_mode_enabled",
    ):
        assert status[k] is False, k
    assert status["live_gate"] == "blocked_human_only"
    assert status["remediation_passed"] is True


def test_run_remediation_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    # Pre-seed a clean refreshed packet so the scan passes.
    paths.refreshed_packet_dir.mkdir(parents=True, exist_ok=True)
    paths.refreshed_public_dir.mkdir(parents=True, exist_ok=True)
    (paths.refreshed_packet_dir / "parallel_lane_matrix.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "lane_id": "demo",
                        "codex_review_command": 'codex exec review --uncommitted "Scoped."',
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    refresh_called: dict[str, bool] = {"called": False}

    def _refresh() -> dict:
        refresh_called["called"] = True
        return {"go_no_go": "refreshed"}

    result = run_remediation(
        paths,
        probe_fn=_stub_probe,
        refresh_throughput_packet_fn=_refresh,
    )

    assert refresh_called["called"] is True
    assert result.go_no_go == "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_READY"
    assert result.invalid_hits_remaining == 0
    for required in [
        "GO_NO_GO.md",
        "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_REPORT.md",
        "codex_cli_capability_probe.json",
        "cli_command_remediation_status.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go


def test_run_remediation_reports_blocked_when_invalid_form_persists(tmp_path: Path):
    paths = default_paths(tmp_path)
    paths.refreshed_packet_dir.mkdir(parents=True, exist_ok=True)
    (paths.refreshed_packet_dir / "stale.json").write_text(
        json.dumps({"command": "codex exec --review v2/"}),
        encoding="utf-8",
    )

    result = run_remediation(
        paths,
        probe_fn=_stub_probe,
        refresh_throughput_packet_fn=lambda: {"go_no_go": "stale"},
    )
    assert result.invalid_hits_remaining >= 1
    assert result.go_no_go.endswith("BLOCKED")
    go_no_go_text = (paths.packet_dir / "GO_NO_GO.md").read_text().strip()
    assert go_no_go_text.endswith("BLOCKED")
