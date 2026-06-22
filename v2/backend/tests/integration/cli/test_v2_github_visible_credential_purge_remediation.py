"""Tests for V2 GitHub-visible credential purge remediation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from v2.backend.app.services.security.github_visible_credential_purge_remediation import (
    PROTECTED_LOCAL_FILE_SUFFIXES,
    PROTECTED_LOCAL_PATH_PREFIXES,
    REDACTION_PLACEHOLDER,
    classify_all_findings,
    classify_line,
    default_paths,
    is_protected_local_path,
    redact_all_confirmed_secrets,
    redact_confirmed_secrets_in_file,
    run_remediation_packet,
)


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _commit(tmp_path: Path, rel: str):
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)


def test_protected_local_path_includes_secrets_and_env_files():
    assert is_protected_local_path(".local_secrets/foo.env") is True
    assert is_protected_local_path(".local_models/checkpoint.bin") is True
    assert is_protected_local_path("v2/.env.local") is True
    assert is_protected_local_path("v2/secrets/whatever.py") is False
    assert is_protected_local_path("README.md") is False
    # Suffix coverage.
    for suffix in PROTECTED_LOCAL_FILE_SUFFIXES:
        assert is_protected_local_path(f"x/y/z{suffix}") is True


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def test_classifier_marks_fake_test_token_as_test_fixture():
    line = "AWS_KEY = 'AKIA0123456789ABCDEF'  # FAKE_TEST_TOKEN DO_NOT_USE"
    assert classify_line("v2/backend/tests/test_x.py", line) == "TEST_FIXTURE_FAKE_SECRET"


def test_classifier_marks_safety_pattern_file_as_safety_pattern_literal():
    line = "AKIAIOSFODNN7EXAMPLE"
    # Even with a real-looking key, files under services/security/ are doc.
    assert (
        classify_line(
            "v2/backend/app/services/security/github_only_credential_purge.py", line
        )
        == "SAFETY_PATTERN_LITERAL"
    )


def test_classifier_marks_env_var_name_only_as_env_var():
    assert (
        classify_line(
            "v2/backend/app/services/foo.py",
            "API_KEY = os.environ.get('BINANCE_API_KEY')",
        )
        == "ENV_VAR_NAME_ONLY"
    )


def test_classifier_marks_redacted_placeholder():
    line = f"BINANCE_API_SECRET = '{REDACTION_PLACEHOLDER}'"
    assert classify_line("v2/legacy_preserved/foo.py", line) == "REDACTED_PLACEHOLDER"


def test_classifier_marks_hash_id_lines_not_secret():
    line = '"feature_snapshot_id": "1a2b3c4d5e6f7890abcdef1234567890",'
    assert classify_line(
        "claude_worklog/foo.json", line
    ) == "HASH_OR_ID_NOT_SECRET"


def test_classifier_returns_confirmed_for_real_binance_assignment():
    # Length 64 alphanumeric AFTER a BINANCE_API_SECRET assignment.
    fake_secret = "A" * 30 + "b" * 30 + "Cc"
    line = f"BINANCE_API_SECRET = '{fake_secret}'"
    assert classify_line("v2/legacy_preserved/config.py", line) == "CONFIRMED_SECRET"


def test_classifier_marks_telegram_bot_token_as_confirmed():
    line = "TELEGRAM_BOT_TOKEN = '8230376700:AA" + "x" * 35 + "'"
    assert classify_line(
        "v2/legacy_preserved/full_runtime_closure/config.py", line
    ) == "CONFIRMED_SECRET"


def test_classifier_priority_confirmed_secret_beats_env_var_marker():
    """Env var reference with a hardcoded fallback default that matches a
    strict secret regex MUST be classified CONFIRMED_SECRET, not
    ENV_VAR_NAME_ONLY. Prevents the real-world miss where
    `os.getenv('TOKEN', '8230376700:AA...')` short-circuited as env-only.
    """
    fallback = "8230376700:AA" + "x" * 35
    line = f"TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN', '{fallback}'),"
    assert classify_line(
        "v2/legacy_preserved/full_runtime_closure/config.py", line
    ) == "CONFIRMED_SECRET"


def test_classifier_priority_confirmed_secret_beats_partial_redacted_placeholder():
    """A line with a partial-redaction for one field plus a leaked
    secret for another field MUST be CONFIRMED_SECRET, not
    REDACTED_PLACEHOLDER. Prevents the real-world miss where audit
    JSON dumps embedded `"text": "FIELD_[REDACTED], '8230376700:AA...'"`
    short-circuited as redacted.
    """
    fallback = "8230376700:AA" + "x" * 35
    line = f'"text": "TELEGRAM_BOT_[REDACTED], \'{fallback}\'"'
    assert classify_line(
        "claude_worklog/coverage/CONFIG_ENV_MAP.json", line
    ) == "CONFIRMED_SECRET"


# ---------------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------------


def test_redactor_refuses_protected_local_vault(tmp_path: Path):
    target = tmp_path / ".local_secrets" / "live_credentials.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("BINANCE_API_SECRET=" + "A" * 64 + "\n", encoding="utf-8")
    rec = redact_confirmed_secrets_in_file(
        tmp_path, ".local_secrets/live_credentials.env"
    )
    assert rec["skipped"] is True
    assert rec["reason"] == "PROTECTED_LOCAL_VAULT_PATH"
    assert rec["redactions_applied"] == 0
    # File content untouched.
    assert "A" * 64 in target.read_text(encoding="utf-8")


def test_redactor_refuses_documentation_files(tmp_path: Path):
    target = tmp_path / "v2/backend/app/services/security/whatever.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# AKIAIOSFODNN7EXAMPLE doc literal\n", encoding="utf-8")
    rec = redact_confirmed_secrets_in_file(
        tmp_path, "v2/backend/app/services/security/whatever.py"
    )
    assert rec["skipped"] is True
    assert rec["reason"] == "DOCUMENTATION_SAFETY_PATTERN_FILE"


def test_redactor_replaces_value_with_placeholder_in_tracked_config(tmp_path: Path):
    target = tmp_path / "v2/legacy_preserved/full_runtime_closure/config.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    fake_token = "8230376700:AA" + "x" * 35
    target.write_text(
        f"TELEGRAM_BOT_TOKEN = '{fake_token}'\nOTHER = 1\n",
        encoding="utf-8",
    )
    rec = redact_confirmed_secrets_in_file(
        tmp_path, "v2/legacy_preserved/full_runtime_closure/config.py"
    )
    assert rec["skipped"] is False
    assert rec["redactions_applied"] >= 1
    new = target.read_text(encoding="utf-8")
    assert fake_token not in new
    assert REDACTION_PLACEHOLDER in new
    assert "OTHER = 1" in new  # other lines preserved


def test_classify_all_findings_records_no_raw_values(tmp_path: Path):
    _init_repo(tmp_path)
    # Plant a secret-shaped line in a tracked file.
    target = tmp_path / "v2/legacy_preserved/full_runtime_closure/config.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    fake_token = "8230376700:AA" + "x" * 35
    target.write_text(f"TELEGRAM_BOT_TOKEN = '{fake_token}'\n", encoding="utf-8")
    _commit(tmp_path, "v2/legacy_preserved/full_runtime_closure/config.py")
    classification = classify_all_findings(tmp_path)
    blob = json.dumps(classification)
    assert fake_token not in blob
    assert classification["raw_secret_value_recorded"] is False
    git_root = classification["per_root_summary"]["git_tracked"]
    assert "v2/legacy_preserved/full_runtime_closure/config.py" in (
        git_root["files_with_findings"]
    )
    assert git_root["classification_counts"].get("CONFIRMED_SECRET", 0) >= 1


# ---------------------------------------------------------------------------
# End-to-end orchestrator
# ---------------------------------------------------------------------------


def test_run_remediation_packet_reduces_confirmed_to_zero(tmp_path: Path):
    _init_repo(tmp_path)
    # Two leaked tracked files.
    fake_token = "8230376700:AA" + "x" * 35
    aws_fake = "AKIA0987654321FEDCBA"  # NOT marked FAKE -> CONFIRMED_SECRET
    for rel, body in (
        (
            "v2/legacy_preserved/full_runtime_closure/config.py",
            f"TELEGRAM_BOT_TOKEN = '{fake_token}'\n",
        ),
        (
            "v2/legacy_preserved/startup_baseline/config.py",
            f"AWS_KEY = '{aws_fake}'\n",
        ),
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        _commit(tmp_path, rel)
    # Also plant a protected-local-vault file with a fake secret — must
    # remain UNTOUCHED.
    vault = tmp_path / ".local_secrets" / "live_credentials.env"
    vault.parent.mkdir(parents=True, exist_ok=True)
    vault_body = "BINANCE_API_SECRET=" + "Z" * 64 + "\n"
    vault.write_text(vault_body, encoding="utf-8")

    paths = default_paths(tmp_path)
    result = run_remediation_packet(paths)
    assert result.go_no_go == (
        "V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_READY"
    )

    status = json.loads(
        (paths.packet_dir / "github_visible_credential_purge_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["unresolved_confirmed_tracked_secret_count"] == 0
    assert status["unresolved_confirmed_public_payload_secret_count"] == 0
    assert status["unresolved_confirmed_worklog_secret_count"] == 0
    assert status["local_runtime_credentials_untouched"] is True
    assert status["did_not_rewrite_git_history"] is True
    assert status["git_history_rewrite_status"] == (
        "OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE"
    )
    # Vault file MUST still contain the original content (untouched).
    assert vault.read_text(encoding="utf-8") == vault_body
    # The two tracked files should now contain the placeholder.
    cfg_a = (tmp_path / "v2/legacy_preserved/full_runtime_closure/config.py").read_text(encoding="utf-8")
    cfg_b = (tmp_path / "v2/legacy_preserved/startup_baseline/config.py").read_text(encoding="utf-8")
    assert REDACTION_PLACEHOLDER in cfg_a
    assert REDACTION_PLACEHOLDER in cfg_b
    assert fake_token not in cfg_a
    assert aws_fake not in cfg_b


def test_emitted_artifacts_carry_no_raw_secret_values(tmp_path: Path):
    _init_repo(tmp_path)
    fake_token = "8230376700:AA" + "x" * 35
    rel = "v2/legacy_preserved/full_runtime_closure/config.py"
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"TELEGRAM_BOT_TOKEN = '{fake_token}'\n", encoding="utf-8")
    _commit(tmp_path, rel)

    paths = default_paths(tmp_path)
    run_remediation_packet(paths)
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        assert fake_token not in text, f"raw value leaked into {f}"
    # forbidden tokens.
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"local_runtime_credentials_untouched": false',
        '"did_not_delete_local_secrets": false',
        '"did_not_delete_local_models": false',
        '"did_not_delete_runtime_env_file": false',
        '"did_not_print_raw_secret_value": false',
        '"did_not_rewrite_git_history": false',
        '"raw_secret_value_recorded": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"


def test_dry_run_does_not_modify_any_file(tmp_path: Path):
    _init_repo(tmp_path)
    fake_token = "8230376700:AA" + "x" * 35
    rel = "v2/legacy_preserved/full_runtime_closure/config.py"
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = f"TELEGRAM_BOT_TOKEN = '{fake_token}'\n"
    p.write_text(body, encoding="utf-8")
    _commit(tmp_path, rel)

    paths = default_paths(tmp_path)
    run_remediation_packet(paths, apply_redactions=False)
    # File MUST be unchanged.
    assert p.read_text(encoding="utf-8") == body
