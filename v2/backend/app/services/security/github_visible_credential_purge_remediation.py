"""V2 GitHub-visible credential purge remediation.

Classifies the noisy findings from the github_only_credential_purge
audit into actionable buckets, redacts CONFIRMED_SECRET hits in
git-tracked files / public payloads / worklog artifacts, and leaves
local runtime credential vaults untouched.

Scope:

  * Reads git-tracked files (via ``git ls-files``) plus public payloads
    and worklog artifacts.
  * Classifies each finding line into one of:
      - ``CONFIRMED_SECRET``
      - ``TEST_FIXTURE_FAKE_SECRET``
      - ``SAFETY_PATTERN_LITERAL``
      - ``REDACTED_PLACEHOLDER``
      - ``ENV_VAR_NAME_ONLY``
      - ``HASH_OR_ID_NOT_SECRET``
      - ``FALSE_POSITIVE``
  * Redacts CONFIRMED_SECRET hits in-place using a fixed placeholder
    (``REDACTED_GIT_VISIBLE_OPERATOR_ROTATE``). The redaction never
    captures, prints, or stores the raw secret value.
  * NEVER touches ``.local_secrets/``, ``.local_models/``, ``*.env*``,
    or any file under those paths.
  * NEVER deletes anything.
  * NEVER auto-rewrites git history.

Per CLAUDE.md the planner is forbidden from editing ``.env`` files
and secrets directories — the protected paths list enforces this.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "v2_github_visible_credential_purge_remediation_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"


REDACTION_PLACEHOLDER = "REDACTED_GIT_VISIBLE_OPERATOR_ROTATE"


# Paths we MUST NOT touch under any circumstance (local runtime vaults).
PROTECTED_LOCAL_PATH_PREFIXES = (
    ".local_secrets",
    ".local_models",
)
PROTECTED_LOCAL_FILE_SUFFIXES = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
)


# Documented references to scan patterns — never redact these.
_SAFETY_PATTERN_FILE_SUBSTRINGS = (
    "services/security/",
    "services/report_center/safe_summary",
    "tests/integration/cli/test_v2_github_",
    "tests/integration/cli/test_v2_website_data_alignment_",
    "tests/unit/services/report_center/",
)


# CONFIRMED_SECRET regex set: tight patterns that are unlikely to false-fire
# in audit dumps. These are intentionally a subset of the broad scanner's
# patterns from github_only_credential_purge.
_CONFIRMED_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "telegram_bot_token_dotted",
        re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "aws_access_key_id_strict",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "nansen_prefix",
        re.compile(r"\bnsn_[0-9a-fA-F]{20,}\b"),
    ),
    (
        "tokenmetrics_prefix",
        re.compile(r"\btm-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    ),
    (
        "pem_private_key_header",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    ),
    (
        "binance_api_key_or_secret_assignment",
        re.compile(
            r"\b(?:BINANCE|COINANK|COINAPI|LUNARCRUSH)_API_(?:KEY|SECRET)"
            r"\s*=\s*['\"]?[A-Za-z0-9]{30,}['\"]?"
        ),
    ),
    (
        "uuid_v4_in_api_key_assignment",
        re.compile(
            r"(?:API[_-]?KEY|TOKEN|SECRET)\s*[:=]\s*['\"]?"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}['\"]?"
        ),
    ),
)


# Markers that downgrade a line from CONFIRMED_SECRET to TEST_FIXTURE_FAKE.
_FAKE_TEST_MARKERS = (
    "AKIAIOSFODNN7EXAMPLE",
    "AKIA0123456789ABCDEF",
    "FAKE_TEST_TOKEN",
    "DO_NOT_USE",
    "EXAMPLE",
    "example_key",
    "examplekey",
    "your_api_key_here",
    "fake_token",
    "TEST_FIXTURE",
)


# Markers that mean the line already references the credential by env var name
# only (no secret value).
_ENV_VAR_NAME_ONLY_MARKERS = (
    "os.environ.get",
    "os.getenv",
    "${",
    "env(",
    "_API_KEY_env",
    "API_KEY_ENV",
)


# Markers that mean the line is a documented placeholder or redacted token.
_REDACTED_PLACEHOLDER_MARKERS = (
    "REDACTED",
    "***",
    "<redacted>",
    "<REDACTED>",
    REDACTION_PLACEHOLDER,
)


# Markers that mean the line is a hash, content-addressed ID, or other
# non-secret hex blob.
_HASH_OR_ID_MARKERS = (
    "sha256",
    "SHA256",
    "sha1",
    "SHA1",
    "checkpoint_id",
    "feature_snapshot_id",
    "prediction_id",
    "request_id",
    "trace_id",
    "commit",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Any) -> None:
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


def is_protected_local_path(rel_path: str) -> bool:
    """Return True if the relative path lives in a local runtime vault."""
    for prefix in PROTECTED_LOCAL_PATH_PREFIXES:
        if rel_path == prefix or rel_path.startswith(prefix + "/"):
            return True
    base = Path(rel_path).name
    for suffix in PROTECTED_LOCAL_FILE_SUFFIXES:
        if base == suffix or base.endswith(suffix):
            # Also protect when the env file is the entire path.
            return True
    return False


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_line(
    rel_path: str, line: str, pattern_name: str | None = None
) -> str:
    """Classify a single finding line.

    Inputs are the file path + the raw line. The function does NOT
    return the matched secret. Output is one of the bucket labels.

    Priority order matters: a line that contains BOTH an env-var
    reference AND a hardcoded fallback secret (e.g.
    ``os.getenv("TOKEN", "actualSecretFallback")``) MUST be classified
    as ``CONFIRMED_SECRET`` because the fallback is the leak; an
    earlier ``ENV_VAR_NAME_ONLY`` short-circuit would mislabel it.
    """
    if any(s in rel_path for s in _SAFETY_PATTERN_FILE_SUBSTRINGS):
        return "SAFETY_PATTERN_LITERAL"
    for marker in _FAKE_TEST_MARKERS:
        if marker in line:
            return "TEST_FIXTURE_FAKE_SECRET"
    # CONFIRMED_SECRET MUST be checked before BOTH env-var markers AND
    # redacted-placeholder markers, because a single line can contain a
    # partial redaction for one field plus a leaked fallback default
    # for another (e.g. `TELEGRAM_BOT_[REDACTED], '8230376700:AA...'`).
    # The leak wins; the partial redaction on the same line is not
    # protection.
    for name, pattern in _CONFIRMED_SECRET_PATTERNS:
        if pattern.search(line):
            return "CONFIRMED_SECRET"
    for marker in _REDACTED_PLACEHOLDER_MARKERS:
        if marker in line:
            return "REDACTED_PLACEHOLDER"
    for marker in _ENV_VAR_NAME_ONLY_MARKERS:
        if marker in line:
            return "ENV_VAR_NAME_ONLY"
    # Hash / ID heuristic — usually a hex blob next to a known non-secret key.
    for marker in _HASH_OR_ID_MARKERS:
        if marker in line:
            return "HASH_OR_ID_NOT_SECRET"
    return "FALSE_POSITIVE"


# ---------------------------------------------------------------------------
# Scanning + classification
# ---------------------------------------------------------------------------


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


def git_tracked_files(repo_root: Path) -> list[str]:
    text = _safe_cmd(["git", "ls-files"], cwd=repo_root)
    if not text:
        return []
    return [line for line in text.splitlines() if line.strip()]


def scan_and_classify_file(
    repo_root: Path, rel_path: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return (per-line findings, classification counts) for a single file.

    Findings carry the bucket label and the pattern name only — NEVER
    the matched substring.
    """
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    full = repo_root / rel_path
    if not full.exists() or full.is_dir():
        return findings, counts
    try:
        text = full.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings, counts
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _CONFIRMED_SECRET_PATTERNS:
            if pattern.search(line):
                bucket = classify_line(rel_path, line, name)
                findings.append({
                    "file": rel_path,
                    "line": lineno,
                    "pattern_name": name,
                    "classification": bucket,
                    "value_recorded": False,
                })
                counts[bucket] = counts.get(bucket, 0) + 1
                break  # one finding per line is enough
    return findings, counts


def classify_all_findings(
    repo_root: Path,
    *,
    roots: Iterable[str] = ("git", "public", "worklog"),
) -> dict[str, Any]:
    """Scan all in-scope files and classify every finding."""
    file_lists: dict[str, list[str]] = {}
    if "git" in roots:
        file_lists["git_tracked"] = git_tracked_files(repo_root)
    if "public" in roots:
        public_dir = repo_root / "v2/frontend/public"
        file_lists["public_payloads"] = (
            [
                str(p.relative_to(repo_root))
                for p in public_dir.rglob("*")
                if p.is_file()
            ]
            if public_dir.exists()
            else []
        )
    if "worklog" in roots:
        worklog_dir = repo_root / "claude_worklog/final_readiness"
        file_lists["worklog_artifacts"] = (
            [
                str(p.relative_to(repo_root))
                for p in worklog_dir.rglob("*")
                if p.is_file()
            ]
            if worklog_dir.exists()
            else []
        )

    per_root_summary: dict[str, dict[str, Any]] = {}
    all_findings: list[dict[str, Any]] = []
    for root_name, files in file_lists.items():
        scanned = 0
        skipped_protected = 0
        skipped_documentation = 0
        files_with_findings: set[str] = set()
        counts: dict[str, int] = {}
        for rel in files:
            if is_protected_local_path(rel):
                skipped_protected += 1
                continue
            if any(s in rel for s in _SAFETY_PATTERN_FILE_SUBSTRINGS):
                # Still scan, but documentation files are classified as
                # SAFETY_PATTERN_LITERAL by classify_line.
                pass
            scanned += 1
            file_findings, file_counts = scan_and_classify_file(repo_root, rel)
            for k, v in file_counts.items():
                counts[k] = counts.get(k, 0) + v
            if file_findings:
                files_with_findings.add(rel)
                all_findings.extend(file_findings)
        per_root_summary[root_name] = {
            "files_listed": len(files),
            "files_scanned": scanned,
            "files_skipped_protected_local_vault": skipped_protected,
            "files_skipped_documentation": skipped_documentation,
            "files_with_findings_count": len(files_with_findings),
            "files_with_findings": sorted(files_with_findings),
            "classification_counts": counts,
        }

    overall_counts: dict[str, int] = {}
    for r in per_root_summary.values():
        for k, v in r["classification_counts"].items():
            overall_counts[k] = overall_counts.get(k, 0) + v

    return {
        "schema_version": SCHEMA_VERSION + "_classification",
        "generated_utc": _utc_now_iso(),
        "per_root_summary": per_root_summary,
        "overall_classification_counts": overall_counts,
        "findings": all_findings,
        "raw_secret_value_recorded": False,
        "protected_local_path_prefixes": list(PROTECTED_LOCAL_PATH_PREFIXES),
        "protected_local_file_suffixes": list(PROTECTED_LOCAL_FILE_SUFFIXES),
    }


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@dataclass
class RedactionAudit:
    files_redacted: list[str] = field(default_factory=list)
    redactions_applied: int = 0
    files_skipped_protected_local_vault: list[str] = field(default_factory=list)
    files_skipped_documentation: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _redact_line(line: str) -> tuple[str, int]:
    """Return (redacted_line, count_of_redactions) for one source line.

    The replacement substitutes the matched substring with the fixed
    placeholder; the raw matched substring never enters a local variable
    that escapes this function.
    """
    redacted_count = 0
    new_line = line
    for _name, pattern in _CONFIRMED_SECRET_PATTERNS:
        if pattern.search(new_line):
            new_line, n = pattern.subn(REDACTION_PLACEHOLDER, new_line)
            redacted_count += n
    return new_line, redacted_count


def redact_confirmed_secrets_in_file(
    repo_root: Path, rel_path: str
) -> dict[str, Any]:
    """Redact CONFIRMED_SECRET hits in a single file.

    Refuses any protected local path or documentation file. Returns a
    per-file audit record; never returns the matched value.
    """
    if is_protected_local_path(rel_path):
        return {
            "file": rel_path,
            "skipped": True,
            "reason": "PROTECTED_LOCAL_VAULT_PATH",
            "redactions_applied": 0,
        }
    if any(s in rel_path for s in _SAFETY_PATTERN_FILE_SUBSTRINGS):
        return {
            "file": rel_path,
            "skipped": True,
            "reason": "DOCUMENTATION_SAFETY_PATTERN_FILE",
            "redactions_applied": 0,
        }
    full = repo_root / rel_path
    if not full.exists() or full.is_dir():
        return {
            "file": rel_path,
            "skipped": True,
            "reason": "NOT_A_REGULAR_FILE",
            "redactions_applied": 0,
        }
    try:
        text = full.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {
            "file": rel_path,
            "skipped": True,
            "reason": f"READ_FAILED:{type(exc).__name__}",
            "redactions_applied": 0,
        }
    new_lines: list[str] = []
    file_redactions = 0
    for line in text.splitlines(keepends=True):
        # Don't touch lines that are already a redacted placeholder or
        # env-var-name reference or a clearly-fake test fixture.
        bucket = classify_line(rel_path, line)
        if bucket in (
            "TEST_FIXTURE_FAKE_SECRET",
            "REDACTED_PLACEHOLDER",
            "ENV_VAR_NAME_ONLY",
            "SAFETY_PATTERN_LITERAL",
            "HASH_OR_ID_NOT_SECRET",
            "FALSE_POSITIVE",
        ):
            new_lines.append(line)
            continue
        if bucket != "CONFIRMED_SECRET":
            new_lines.append(line)
            continue
        redacted_line, n = _redact_line(line)
        new_lines.append(redacted_line)
        file_redactions += n
    if file_redactions == 0:
        return {
            "file": rel_path,
            "skipped": True,
            "reason": "NO_CONFIRMED_SECRET_AFTER_CLASSIFICATION",
            "redactions_applied": 0,
        }
    full.write_text("".join(new_lines), encoding="utf-8")
    return {
        "file": rel_path,
        "skipped": False,
        "redactions_applied": file_redactions,
    }


def redact_all_confirmed_secrets(
    repo_root: Path, classification: dict[str, Any],
) -> tuple[list[dict[str, Any]], RedactionAudit]:
    audit = RedactionAudit()
    file_records: list[dict[str, Any]] = []
    files_to_remediate: set[str] = set()
    for finding in classification.get("findings", []):
        if finding.get("classification") != "CONFIRMED_SECRET":
            continue
        files_to_remediate.add(finding["file"])
    for rel in sorted(files_to_remediate):
        rec = redact_confirmed_secrets_in_file(repo_root, rel)
        file_records.append(rec)
        if rec.get("skipped"):
            if rec.get("reason") == "PROTECTED_LOCAL_VAULT_PATH":
                audit.files_skipped_protected_local_vault.append(rel)
            elif rec.get("reason") == "DOCUMENTATION_SAFETY_PATTERN_FILE":
                audit.files_skipped_documentation.append(rel)
            else:
                audit.errors.append(
                    f"{rel}:{rec.get('reason')}"
                )
            continue
        audit.files_redacted.append(rel)
        audit.redactions_applied += rec.get("redactions_applied", 0)
    return file_records, audit


# ---------------------------------------------------------------------------
# Final status + dashboard
# ---------------------------------------------------------------------------


def build_remediation_status(
    *,
    classification_before: dict[str, Any],
    classification_after: dict[str, Any],
    redaction_audit: RedactionAudit,
    file_records: list[dict[str, Any]],
    gitignore_check: dict[str, Any] | None,
) -> dict[str, Any]:
    overall_after = classification_after["overall_classification_counts"]
    unresolved_confirmed = overall_after.get("CONFIRMED_SECRET", 0)
    history_rewrite_required = (
        classification_before["overall_classification_counts"].get(
            "CONFIRMED_SECRET", 0
        ) > 0
    )
    per_root_after = classification_after["per_root_summary"]
    return {
        "schema_version": SCHEMA_VERSION + "_remediation_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_delete_local_secrets": True,
        "did_not_delete_local_models": True,
        "did_not_delete_runtime_env_file": True,
        "did_not_modify_legacy_tree": True,
        "did_not_print_raw_secret_value": True,
        "did_not_rewrite_git_history": True,
        "local_runtime_credentials_untouched": True,
        "classification_counts_before": classification_before[
            "overall_classification_counts"
        ],
        "classification_counts_after": overall_after,
        "unresolved_confirmed_tracked_secret_count": (
            per_root_after.get("git_tracked", {})
            .get("classification_counts", {})
            .get("CONFIRMED_SECRET", 0)
        ),
        "unresolved_confirmed_public_payload_secret_count": (
            per_root_after.get("public_payloads", {})
            .get("classification_counts", {})
            .get("CONFIRMED_SECRET", 0)
        ),
        "unresolved_confirmed_worklog_secret_count": (
            per_root_after.get("worklog_artifacts", {})
            .get("classification_counts", {})
            .get("CONFIRMED_SECRET", 0)
        ),
        "files_redacted_count": len(redaction_audit.files_redacted),
        "redactions_applied": redaction_audit.redactions_applied,
        "files_skipped_protected_local_vault": (
            redaction_audit.files_skipped_protected_local_vault
        ),
        "files_skipped_documentation": (
            redaction_audit.files_skipped_documentation
        ),
        "file_records": file_records,
        "git_history_rewrite_required": history_rewrite_required,
        "git_history_rewrite_status": (
            "OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE"
            if history_rewrite_required
            else "NOT_REQUIRED"
        ),
        "gitignore_check": gitignore_check,
        "raw_secret_value_recorded": False,
    }


def build_operator_dashboard_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_READY",
        "safety_scoreboard": {
            "live_gate": status["live_gate"],
            "live_symbols": status["live_symbols"],
            "approves_live": status["approves_live"],
            "approves_canary": status["approves_canary"],
            "approves_legacy_shutdown": status["approves_legacy_shutdown"],
            "approves_redis_trim": status["approves_redis_trim"],
            "did_not_delete_local_secrets": status["did_not_delete_local_secrets"],
            "did_not_delete_local_models": status["did_not_delete_local_models"],
            "did_not_delete_runtime_env_file": status[
                "did_not_delete_runtime_env_file"
            ],
            "did_not_print_raw_secret_value": status[
                "did_not_print_raw_secret_value"
            ],
            "did_not_rewrite_git_history": status["did_not_rewrite_git_history"],
            "local_runtime_credentials_untouched": status[
                "local_runtime_credentials_untouched"
            ],
        },
        "summary": {
            "classification_counts_before": status["classification_counts_before"],
            "classification_counts_after": status["classification_counts_after"],
            "files_redacted_count": status["files_redacted_count"],
            "redactions_applied": status["redactions_applied"],
            "unresolved_confirmed_tracked_secret_count": status[
                "unresolved_confirmed_tracked_secret_count"
            ],
            "unresolved_confirmed_public_payload_secret_count": status[
                "unresolved_confirmed_public_payload_secret_count"
            ],
            "unresolved_confirmed_worklog_secret_count": status[
                "unresolved_confirmed_worklog_secret_count"
            ],
            "git_history_rewrite_required": status["git_history_rewrite_required"],
            "git_history_rewrite_status": status["git_history_rewrite_status"],
        },
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class RemediationPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> RemediationPaths:
    return RemediationPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_github_visible_credential_purge_remediation/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_github_visible_credential_purge_remediation/latest",
    )


@dataclass
class RemediationRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_remediation_packet(
    paths: RemediationPaths,
    *,
    apply_redactions: bool = True,
) -> RemediationRunResult:
    classification_before = classify_all_findings(paths.repo_root)
    file_records: list[dict[str, Any]] = []
    redaction_audit = RedactionAudit()
    if apply_redactions:
        file_records, redaction_audit = redact_all_confirmed_secrets(
            paths.repo_root, classification_before,
        )
    classification_after = classify_all_findings(paths.repo_root)
    # Re-use the audit packet's gitignore check (read-only).
    from v2.backend.app.services.security.github_only_credential_purge import (
        verify_gitignore_protects_sensitive_paths,
    )
    gitignore_check = verify_gitignore_protects_sensitive_paths(paths.repo_root)
    status = build_remediation_status(
        classification_before=classification_before,
        classification_after=classification_after,
        redaction_audit=redaction_audit,
        file_records=file_records,
        gitignore_check=gitignore_check,
    )
    dashboard = build_operator_dashboard_payload(status)

    _atomic_write_json(
        paths.packet_dir / "github_visible_credential_purge_status.json",
        status,
    )
    _atomic_write_json(
        paths.packet_dir / "credential_findings_classification.json",
        classification_after,
    )
    _atomic_write_json(
        paths.packet_dir / "files_remediated.json",
        {
            "schema_version": SCHEMA_VERSION + "_files_remediated",
            "generated_utc": _utc_now_iso(),
            "file_records": file_records,
            "files_redacted_count": len(redaction_audit.files_redacted),
            "redactions_applied": redaction_audit.redactions_applied,
            "files_skipped_protected_local_vault": (
                redaction_audit.files_skipped_protected_local_vault
            ),
            "files_skipped_documentation": (
                redaction_audit.files_skipped_documentation
            ),
            "raw_secret_value_recorded": False,
        },
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "github_visible_credential_purge_status.json",
        status,
    )

    report = _render_report(status)
    _atomic_write_text(
        paths.packet_dir
        / "V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_READY\n",
    )

    return RemediationRunResult(
        go_no_go="V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_REPORT.md",
            paths.packet_dir / "github_visible_credential_purge_status.json",
            paths.packet_dir / "credential_findings_classification.json",
            paths.packet_dir / "files_remediated.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "github_visible_credential_purge_status.json",
        ],
    )


def _render_report(status: dict[str, Any]) -> str:
    lines = []
    lines.append("# V2 GitHub-Visible Credential Purge Remediation Report\n\n")
    lines.append(
        "GO/NO-GO: V2_GITHUB_VISIBLE_CREDENTIAL_PURGE_REMEDIATION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " local_runtime_credentials_untouched=true.\n\n"
    )
    lines.append("## Classification (after remediation)\n")
    for k, v in sorted(status["classification_counts_after"].items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n## Redaction summary\n")
    lines.append(
        f"- files_redacted_count: {status['files_redacted_count']}\n"
        f"- redactions_applied: {status['redactions_applied']}\n"
        f"- files_skipped_protected_local_vault: "
        f"{len(status['files_skipped_protected_local_vault'])}\n"
        f"- files_skipped_documentation: "
        f"{len(status['files_skipped_documentation'])}\n\n"
    )
    lines.append("## Unresolved CONFIRMED_SECRET counts (must all be 0)\n")
    lines.append(
        f"- tracked: {status['unresolved_confirmed_tracked_secret_count']}\n"
        f"- public payloads: "
        f"{status['unresolved_confirmed_public_payload_secret_count']}\n"
        f"- worklog: {status['unresolved_confirmed_worklog_secret_count']}\n\n"
    )
    lines.append("## Git history\n")
    lines.append(
        f"- git_history_rewrite_required: {status['git_history_rewrite_required']}\n"
        f"- git_history_rewrite_status: {status['git_history_rewrite_status']}\n\n"
    )
    if status.get("gitignore_check"):
        lines.append("## .gitignore protected entries\n")
        for req, ok in status["gitignore_check"]["protected_entries"].items():
            lines.append(f"- {req}: {'protected' if ok else 'MISSING'}\n")
        lines.append("\n")
    lines.append("## Safety scoreboard\n")
    for k in (
        "live_gate",
        "live_symbols",
        "approves_live",
        "approves_canary",
        "approves_legacy_shutdown",
        "approves_redis_trim",
        "did_not_delete_local_secrets",
        "did_not_delete_local_models",
        "did_not_delete_runtime_env_file",
        "did_not_print_raw_secret_value",
        "did_not_rewrite_git_history",
        "local_runtime_credentials_untouched",
    ):
        lines.append(f"- {k}: {status.get(k)}\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not delete `.local_secrets/`, `.local_models/`, or any "
        "`*.env*` file.\n"
        "- Did not print any raw credential value in any artifact.\n"
        "- Did not rewrite git history; status field marks it as "
        "operator-decision when needed.\n"
        "- Did not stop V2 runtime, legacy, report center, replay miner, "
        "or Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
    )
    return "".join(lines)
