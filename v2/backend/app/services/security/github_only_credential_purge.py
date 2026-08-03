"""V2 GitHub-only credential purge audit (read-only file path reporter).

Scope:

  * Scan ONLY git-tracked files for high-confidence secret patterns.
  * Report file paths (and line numbers) of findings — NEVER values.
  * Verify ``.gitignore`` protects sensitive paths.
  * Emit ``OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE`` if findings
    exist (planner will not auto-rewrite git history).
  * Do NOT touch ``.local_secrets/``, ``.local_models/``, ``.env*``, or
    any other local runtime credential vault.
  * Do NOT delete or edit anything from this module — auto-remediation
    is operator-gated.

Per CLAUDE.md the planner cannot edit ``.env`` files or secrets
directories. This audit produces a remediation **plan** that the
operator can execute (or ask the planner to execute under a separate
explicit instruction).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "v2_github_only_credential_purge_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

# Paths we MUST NOT touch even read-only beyond a stat.
LOCAL_RUNTIME_VAULT_PATHS = (
    ".local_secrets",
    ".local_models",
)
LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED = (
    ".local_secrets/",
    ".local_models/",
    "v2/.env.local",
    "v2/secrets/",
)


# Public-style high-confidence secret regex patterns. Each entry is a
# (name, compiled_regex). The regexes are matched against tracked file
# CONTENT but the value itself is NEVER stored on the result — only the
# pattern name + file path + line number.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "binance_api_secret_64_alphanumeric",
        re.compile(r"\b[A-Za-z0-9]{64}\b"),
    ),
    (
        "telegram_bot_token_dotted",
        # Telegram format: <bot_id>:AA<35-base64-ish>
        re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "uuid_v4_like_api_key",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
    (
        "hex_32_api_key_after_assignment",
        re.compile(r"=\s*['\"]?[0-9a-fA-F]{32}['\"]?"),
    ),
    (
        "tokenmetrics_prefix",
        re.compile(r"\btm-[0-9a-fA-F-]{30,}\b"),
    ),
    (
        "nansen_prefix",
        re.compile(r"\bnsn_[0-9a-fA-F]{20,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "pem_private_key_header",
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    ),
    (
        "bearer_token_assignment",
        re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-]{20,}"),
    ),
)


# Files we know are intentionally documenting these patterns (themselves
# safe). Excluded so they don't show as findings.
_DOCUMENTED_PATTERN_FILES = (
    "v2/backend/app/services/security/github_only_credential_purge.py",
    "v2/backend/app/services/security/local_credentials_env_presence.py",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_cmd(cmd: list[str], *, cwd: Path, timeout: float = 30.0) -> str | None:
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd), check=False, capture_output=True,
            text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _git_tracked_files(repo_root: Path) -> list[str]:
    text = _safe_cmd(["git", "ls-files"], cwd=repo_root)
    if not text:
        return []
    return [line for line in text.splitlines() if line.strip()]


def _is_under_local_vault(rel_path: str) -> bool:
    for vault in LOCAL_RUNTIME_VAULT_PATHS:
        if rel_path == vault or rel_path.startswith(vault + "/"):
            return True
    return False


def _is_documentation_file(rel_path: str) -> bool:
    return rel_path in _DOCUMENTED_PATTERN_FILES


def _scan_file_for_patterns(
    path: Path, rel_path: str
) -> list[dict[str, Any]]:
    """Return per-line findings. NEVER includes the matched value."""
    findings: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "file": rel_path,
                    "line": lineno,
                    "pattern_name": name,
                    "value_recorded": False,
                })
                # One pattern per line is enough to flag the file.
                break
    return findings


def scan_git_tracked_files_for_secrets(repo_root: Path) -> dict[str, Any]:
    """Scan ONLY git-tracked files for high-confidence secret patterns."""
    tracked = _git_tracked_files(repo_root)
    files_scanned = 0
    files_skipped_local_vault = 0
    files_skipped_documentation = 0
    findings: list[dict[str, Any]] = []
    files_with_findings: set[str] = set()

    for rel in tracked:
        if _is_under_local_vault(rel):
            files_skipped_local_vault += 1
            continue
        if _is_documentation_file(rel):
            files_skipped_documentation += 1
            continue
        full = repo_root / rel
        if not full.exists() or full.is_dir():
            continue
        files_scanned += 1
        file_findings = _scan_file_for_patterns(full, rel)
        if file_findings:
            findings.extend(file_findings)
            files_with_findings.add(rel)

    return {
        "schema_version": SCHEMA_VERSION + "_git_tracked_scan",
        "generated_utc": _utc_now_iso(),
        "files_scanned": files_scanned,
        "files_skipped_local_vault": files_skipped_local_vault,
        "files_skipped_documentation": files_skipped_documentation,
        "files_with_findings_count": len(files_with_findings),
        "files_with_findings": sorted(files_with_findings),
        "findings_count": len(findings),
        "findings": findings,
        "raw_secret_value_recorded": False,
        "local_runtime_vault_paths_left_untouched": list(LOCAL_RUNTIME_VAULT_PATHS),
    }


def scan_public_payloads_for_secrets(repo_root: Path) -> dict[str, Any]:
    """Scan v2/frontend/public/** for secret patterns (read-only)."""
    public_root = repo_root / "v2/frontend/public"
    files_scanned = 0
    findings: list[dict[str, Any]] = []
    files_with_findings: set[str] = set()
    if public_root.exists():
        for path in public_root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(repo_root))
            if _is_documentation_file(rel):
                continue
            files_scanned += 1
            file_findings = _scan_file_for_patterns(path, rel)
            if file_findings:
                findings.extend(file_findings)
                files_with_findings.add(rel)
    return {
        "schema_version": SCHEMA_VERSION + "_public_payload_scan",
        "generated_utc": _utc_now_iso(),
        "files_scanned": files_scanned,
        "files_with_findings_count": len(files_with_findings),
        "files_with_findings": sorted(files_with_findings),
        "findings_count": len(findings),
        "findings": findings,
        "raw_secret_value_recorded": False,
    }


def scan_worklog_artifacts_for_secrets(repo_root: Path) -> dict[str, Any]:
    """Scan claude_worklog/final_readiness/** for secret patterns."""
    worklog_root = repo_root / "claude_worklog/final_readiness"
    files_scanned = 0
    findings: list[dict[str, Any]] = []
    files_with_findings: set[str] = set()
    if worklog_root.exists():
        for path in worklog_root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(repo_root))
            if _is_documentation_file(rel):
                continue
            files_scanned += 1
            file_findings = _scan_file_for_patterns(path, rel)
            if file_findings:
                findings.extend(file_findings)
                files_with_findings.add(rel)
    return {
        "schema_version": SCHEMA_VERSION + "_worklog_scan",
        "generated_utc": _utc_now_iso(),
        "files_scanned": files_scanned,
        "files_with_findings_count": len(files_with_findings),
        "files_with_findings": sorted(files_with_findings),
        "findings_count": len(findings),
        "findings": findings,
        "raw_secret_value_recorded": False,
    }


def verify_gitignore_protects_sensitive_paths(repo_root: Path) -> dict[str, Any]:
    gi_path = repo_root / ".gitignore"
    text = ""
    if gi_path.exists():
        try:
            text = gi_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
    lines = {line.strip() for line in text.splitlines()}
    protected = {}
    for required in LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED:
        protected[required] = required in lines
    missing = [r for r, ok in protected.items() if not ok]
    return {
        "schema_version": SCHEMA_VERSION + "_gitignore_verify",
        "generated_utc": _utc_now_iso(),
        "gitignore_present": gi_path.exists(),
        "required_entries": list(LOCAL_RUNTIME_VAULT_GITIGNORE_REQUIRED),
        "protected_entries": protected,
        "missing_entries": missing,
        "all_required_protected": not missing,
    }


def build_purge_status(
    repo_root: Path,
    *,
    tracked_scan: dict[str, Any],
    public_scan: dict[str, Any],
    worklog_scan: dict[str, Any],
    gitignore_check: dict[str, Any],
) -> dict[str, Any]:
    history_rewrite_required = tracked_scan["findings_count"] > 0
    return {
        "schema_version": SCHEMA_VERSION + "_github_credential_purge_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_delete_local_secrets": True,
        "did_not_delete_local_runtime_credential_vault": True,
        "did_not_modify_legacy_tree": True,
        "did_not_print_raw_secret_value": True,
        "did_not_edit_any_tracked_file_in_this_audit": True,
        "did_not_rewrite_git_history": True,
        "local_runtime_credentials_untouched": True,
        "tracked_secret_findings_count": tracked_scan["findings_count"],
        "public_payload_secret_findings_count": public_scan["findings_count"],
        "worklog_secret_findings_count": worklog_scan["findings_count"],
        "files_remediated": 0,
        "git_history_rewrite_required": history_rewrite_required,
        "git_history_rewrite_status": (
            "OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE"
            if history_rewrite_required
            else "NOT_REQUIRED"
        ),
        "gitignore_check": gitignore_check,
        "tracked_files_with_findings": tracked_scan["files_with_findings"],
        "public_files_with_findings": public_scan["files_with_findings"],
        "worklog_files_with_findings": worklog_scan["files_with_findings"],
        "remediation_plan_actions": [
            (
                "redact_tracked_files_replacing_values_with_env_var_names"
                "_or_placeholders_OPERATOR_DECISION"
            ),
            (
                "git_filter_repo_history_rewrite_OPERATOR_DECISION"
            ),
            (
                "rotate_every_leaked_credential_at_provider_dashboard"
                "_OPERATOR_MUST_DO_THIS"
            ),
            (
                "verify_gitignore_entries_already_protect_local_runtime"
                "_vaults_listed_above"
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class PurgePaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> PurgePaths:
    return PurgePaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_github_only_credential_purge/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_github_only_credential_purge/latest",
    )


@dataclass
class PurgeRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def _atomic_write_json(path: Path, payload: Any) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def build_operator_dashboard_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY",
        "safety_scoreboard": {
            "live_gate": status["live_gate"],
            "live_symbols": status["live_symbols"],
            "approves_live": status["approves_live"],
            "approves_canary": status["approves_canary"],
            "approves_legacy_shutdown": status["approves_legacy_shutdown"],
            "approves_redis_trim": status["approves_redis_trim"],
            "local_runtime_credentials_untouched": status[
                "local_runtime_credentials_untouched"
            ],
            "did_not_delete_local_secrets": status["did_not_delete_local_secrets"],
            "did_not_print_raw_secret_value": status[
                "did_not_print_raw_secret_value"
            ],
            "did_not_edit_any_tracked_file_in_this_audit": status[
                "did_not_edit_any_tracked_file_in_this_audit"
            ],
            "did_not_rewrite_git_history": status["did_not_rewrite_git_history"],
        },
        "summary": {
            "tracked_secret_findings_count": status[
                "tracked_secret_findings_count"
            ],
            "public_payload_secret_findings_count": status[
                "public_payload_secret_findings_count"
            ],
            "worklog_secret_findings_count": status[
                "worklog_secret_findings_count"
            ],
            "files_remediated": status["files_remediated"],
            "git_history_rewrite_required": status[
                "git_history_rewrite_required"
            ],
            "git_history_rewrite_status": status["git_history_rewrite_status"],
            "gitignore_all_required_protected": status["gitignore_check"][
                "all_required_protected"
            ],
        },
        "controls_present": False,
        "fake_readiness": False,
    }


def run_purge_packet(paths: PurgePaths) -> PurgeRunResult:
    tracked_scan = scan_git_tracked_files_for_secrets(paths.repo_root)
    public_scan = scan_public_payloads_for_secrets(paths.repo_root)
    worklog_scan = scan_worklog_artifacts_for_secrets(paths.repo_root)
    gitignore_check = verify_gitignore_protects_sensitive_paths(paths.repo_root)
    status = build_purge_status(
        paths.repo_root,
        tracked_scan=tracked_scan,
        public_scan=public_scan,
        worklog_scan=worklog_scan,
        gitignore_check=gitignore_check,
    )
    dashboard = build_operator_dashboard_payload(status)

    _atomic_write_json(
        paths.packet_dir / "github_credential_purge_status.json", status
    )
    _atomic_write_json(
        paths.packet_dir / "tracked_files_scan.json", tracked_scan
    )
    _atomic_write_json(
        paths.packet_dir / "public_payload_scan.json", public_scan
    )
    _atomic_write_json(
        paths.packet_dir / "worklog_scan.json", worklog_scan
    )
    _atomic_write_json(
        paths.packet_dir / "gitignore_verify.json", gitignore_check
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "github_credential_purge_status.json", status
    )

    report = _render_report(status, gitignore_check)
    _atomic_write_text(
        paths.packet_dir / "V2_GITHUB_ONLY_CREDENTIAL_PURGE_REPORT.md", report
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY\n",
    )

    return PurgeRunResult(
        go_no_go="V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir / "V2_GITHUB_ONLY_CREDENTIAL_PURGE_REPORT.md",
            paths.packet_dir / "github_credential_purge_status.json",
            paths.packet_dir / "tracked_files_scan.json",
            paths.packet_dir / "public_payload_scan.json",
            paths.packet_dir / "worklog_scan.json",
            paths.packet_dir / "gitignore_verify.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "github_credential_purge_status.json",
        ],
    )


def _render_report(status: dict[str, Any], gitignore_check: dict[str, Any]) -> str:
    lines = []
    lines.append("# V2 GitHub-Only Credential Purge Audit Report\n\n")
    lines.append("GO/NO-GO: V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " local_runtime_credentials_untouched=true.\n\n"
    )
    lines.append("## Scope\n")
    lines.append(
        "Read-only audit. Reports FILE PATHS + LINE NUMBERS only. NEVER"
        " reads or emits a credential value. Does NOT touch"
        " `.local_secrets/`, `.local_models/`, `*.env*`, or any local"
        " runtime credential vault. Does NOT auto-edit any tracked"
        " file. Does NOT auto-rewrite git history.\n\n"
    )
    lines.append("## Findings\n")
    lines.append(
        f"- tracked_secret_findings_count: {status['tracked_secret_findings_count']}\n"
        f"- public_payload_secret_findings_count: {status['public_payload_secret_findings_count']}\n"
        f"- worklog_secret_findings_count: {status['worklog_secret_findings_count']}\n"
        f"- files_remediated: {status['files_remediated']}\n"
        f"- git_history_rewrite_required: {status['git_history_rewrite_required']}\n"
        f"- git_history_rewrite_status: {status['git_history_rewrite_status']}\n\n"
    )
    if status["tracked_files_with_findings"]:
        lines.append("## Git-tracked files with findings (file paths only)\n")
        for f in status["tracked_files_with_findings"]:
            lines.append(f"- {f}\n")
        lines.append("\n")
    if status["public_files_with_findings"]:
        lines.append("## Public payload files with findings\n")
        for f in status["public_files_with_findings"]:
            lines.append(f"- {f}\n")
        lines.append("\n")
    if status["worklog_files_with_findings"]:
        lines.append("## Worklog files with findings\n")
        for f in status["worklog_files_with_findings"]:
            lines.append(f"- {f}\n")
        lines.append("\n")
    lines.append("## .gitignore verify\n")
    for req in gitignore_check["required_entries"]:
        ok = gitignore_check["protected_entries"][req]
        lines.append(f"- {req}: {'protected' if ok else 'MISSING'}\n")
    lines.append("\n")
    lines.append("## Remediation plan (operator-gated)\n")
    for action in status["remediation_plan_actions"]:
        lines.append(f"- {action}\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not delete `.local_secrets/` or any local runtime vault.\n"
        "- Did not delete or modify any `.env*` file.\n"
        "- Did not print any raw credential value (file paths + line"
        " numbers + pattern names only).\n"
        "- Did not edit any tracked file in this audit run.\n"
        "- Did not auto-rewrite git history; that is operator-gated.\n"
        "- Did not stop V2 runtime, legacy, report center, replay miner,"
        " or Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable live, canary, or shutdown.\n"
    )
    return "".join(lines)
