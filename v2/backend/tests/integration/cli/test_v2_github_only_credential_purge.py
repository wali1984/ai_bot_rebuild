"""Tests for the V2 GitHub-only credential purge audit."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from v2.backend.app.services.security.github_only_credential_purge import (
    LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED,
    LOCAL_RUNTIME_VAULT_PATHS,
    build_purge_status,
    default_paths,
    run_purge_packet,
    scan_git_tracked_files_for_secrets,
    scan_public_payloads_for_secrets,
    scan_worklog_artifacts_for_secrets,
    verify_gitignore_protects_sensitive_paths,
)


def _init_tiny_git_repo(tmp_path: Path) -> Path:
    """Create a small git repo with one tracked clean file."""
    subprocess.run(
        ["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    clean = tmp_path / "clean.py"
    clean.write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "clean.py"], cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


def test_scanner_skips_local_secrets_vault(tmp_path: Path):
    _init_tiny_git_repo(tmp_path)
    # Place a .local_secrets file (NOT git-tracked) with a fake secret-shaped
    # string. Scanner must not record any value or even open it via git-tracked
    # iteration.
    vault = tmp_path / ".local_secrets" / "live_credentials.env"
    vault.parent.mkdir(parents=True, exist_ok=True)
    vault.write_text(
        "FAKE_KEY=" + ("a" * 64) + "\n", encoding="utf-8",
    )
    result = scan_git_tracked_files_for_secrets(tmp_path)
    # No tracked file contains secrets in this minimal repo.
    assert result["findings_count"] == 0
    assert result["files_with_findings"] == []
    # Vault path is documented in safety pin list.
    assert ".local_secrets" in result["local_runtime_vault_paths_left_untouched"]


def test_scanner_detects_high_confidence_pattern_in_tracked_file(tmp_path: Path):
    _init_tiny_git_repo(tmp_path)
    # Add a tracked file containing a fake AWS-shaped key pattern.
    bad = tmp_path / "leak.py"
    bad.write_text("AWS_KEY = 'AKIA" + "0123456789ABCDEF" + "'\n", encoding="utf-8")
    subprocess.run(["git", "add", "leak.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "leak"], cwd=tmp_path, check=True, capture_output=True)
    result = scan_git_tracked_files_for_secrets(tmp_path)
    assert result["findings_count"] >= 1
    assert "leak.py" in result["files_with_findings"]
    # The recorded findings never include the actual value.
    blob = json.dumps(result)
    assert result["raw_secret_value_recorded"] is False
    # The literal AWS key value MUST NOT be in the scan result blob.
    assert "AKIA" + "0123456789ABCDEF" not in blob


def test_gitignore_verify_reports_missing_entries(tmp_path: Path):
    # Empty gitignore -> all required entries missing.
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    result = verify_gitignore_protects_sensitive_paths(tmp_path)
    assert result["gitignore_present"] is True
    assert result["all_required_protected"] is False
    assert set(result["missing_entries"]) == set(LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED)


def test_gitignore_verify_passes_when_all_required_present(tmp_path: Path):
    gi = tmp_path / ".gitignore"
    gi.write_text(
        "\n".join(LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED) + "\n",
        encoding="utf-8",
    )
    result = verify_gitignore_protects_sensitive_paths(tmp_path)
    assert result["all_required_protected"] is True
    assert result["missing_entries"] == []


def test_purge_status_emits_git_history_rewrite_required_when_findings_exist(
    tmp_path: Path,
):
    _init_tiny_git_repo(tmp_path)
    bad = tmp_path / "leak.py"
    bad.write_text("AWS_KEY = 'AKIA" + "0123456789ABCDEF" + "'\n", encoding="utf-8")
    subprocess.run(["git", "add", "leak.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "leak"], cwd=tmp_path, check=True, capture_output=True)

    tracked = scan_git_tracked_files_for_secrets(tmp_path)
    public = scan_public_payloads_for_secrets(tmp_path)
    worklog = scan_worklog_artifacts_for_secrets(tmp_path)
    gitignore = verify_gitignore_protects_sensitive_paths(tmp_path)
    status = build_purge_status(
        tmp_path,
        tracked_scan=tracked,
        public_scan=public,
        worklog_scan=worklog,
        gitignore_check=gitignore,
    )
    assert status["git_history_rewrite_required"] is True
    assert status["git_history_rewrite_status"] == (
        "OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE"
    )
    assert status["files_remediated"] == 0
    assert status["did_not_edit_any_tracked_file_in_this_audit"] is True
    assert status["did_not_rewrite_git_history"] is True
    assert status["did_not_delete_local_secrets"] is True
    assert status["local_runtime_credentials_untouched"] is True


def test_purge_status_no_history_rewrite_when_no_findings(tmp_path: Path):
    _init_tiny_git_repo(tmp_path)
    tracked = scan_git_tracked_files_for_secrets(tmp_path)
    public = scan_public_payloads_for_secrets(tmp_path)
    worklog = scan_worklog_artifacts_for_secrets(tmp_path)
    gitignore = verify_gitignore_protects_sensitive_paths(tmp_path)
    status = build_purge_status(
        tmp_path,
        tracked_scan=tracked,
        public_scan=public,
        worklog_scan=worklog,
        gitignore_check=gitignore,
    )
    assert status["git_history_rewrite_required"] is False
    assert status["git_history_rewrite_status"] == "NOT_REQUIRED"


def test_run_purge_packet_emits_all_required_artifacts(tmp_path: Path):
    _init_tiny_git_repo(tmp_path)
    paths = default_paths(tmp_path)
    result = run_purge_packet(paths)
    assert result.go_no_go == "V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY"
    for required in [
        "GO_NO_GO.md",
        "V2_GITHUB_ONLY_CREDENTIAL_PURGE_REPORT.md",
        "github_credential_purge_status.json",
        "tracked_files_scan.json",
        "public_payload_scan.json",
        "worklog_scan.json",
        "gitignore_verify.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    for public_required in [
        "operator_dashboard_payload.json",
        "github_credential_purge_status.json",
    ]:
        assert (paths.public_dir / public_required).exists(), public_required


def test_emitted_artifacts_do_not_contain_actual_secret_substrings(tmp_path: Path):
    _init_tiny_git_repo(tmp_path)
    # Write a tracked file with a high-confidence pattern.
    bad = tmp_path / "leak.py"
    fake_key = "AKIA" + "0123456789ABCDEF"
    bad.write_text(f"AWS_KEY = '{fake_key}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "leak.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "leak"], cwd=tmp_path, check=True, capture_output=True)
    paths = default_paths(tmp_path)
    run_purge_packet(paths)
    # The actual key value must NOT appear in any emitted artifact.
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        assert fake_key not in text, f"raw key leaked into {f}"
    # And the forbidden-token contract.
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"local_runtime_credentials_untouched": false',
        '"did_not_delete_local_secrets": false',
        '"did_not_print_raw_secret_value": false',
        '"did_not_edit_any_tracked_file_in_this_audit": false',
        '"did_not_rewrite_git_history": false',
        '"raw_secret_value_recorded": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
