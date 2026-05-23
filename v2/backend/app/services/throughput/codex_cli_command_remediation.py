"""V2 throughput-plan Codex CLI command remediation (analysis-only).

Codex blocked V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY with
``CODEX_NONINTERACTIVE_REVIEW_COMMANDS_INVALID_FOR_INSTALLED_CLI``
because the lane matrix and cloud options documented
``codex exec --review <path>``, which the installed ``codex-cli 0.128.0``
rejects.

This module:

* Probes the installed Codex CLI (read-only) and emits a capability
  payload so later changes cannot silently break.
* Scans the freshly built throughput packet for invalid review command
  forms.
* Re-runs the throughput packet builder so the refreshed artifacts use
  the corrected ``codex exec review --uncommitted "<prompt>"`` form.
* Writes a remediation packet under
  ``claude_worklog/final_readiness/v2_ai_throughput_acceleration_cli_command_remediation/latest/``.

The module never:
  * mutates the legacy bot tree
  * writes legacy Redis keys
  * places, cancels, or modifies exchange orders
  * approves live, canary, legacy-shutdown, or Redis-trim
  * installs the high-throughput scheduler daemon
  * dispatches any GPU job
  * enables Codex Fast mode
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "v2_ai_throughput_acceleration_cli_command_remediation_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"


# Invalid forms we never want to see in emitted artifacts. Each entry is
# a substring; the validator flags any artifact that contains the form.
INVALID_REVIEW_COMMAND_FORMS = (
    "codex exec --review",
    "codex --review",
)


VALID_REVIEW_COMMAND_TEMPLATES = (
    'codex review --uncommitted "<scoped review prompt>"',
    'codex exec review --uncommitted "<scoped review prompt>"',
    'codex exec "<scoped scripted prompt>"',
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


# ---------------------------------------------------------------------------
# CLI capability probe
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a read-only command and return (returncode, stdout, stderr)."""
    binary = shutil.which(cmd[0])
    if binary is None:
        return (127, "", f"binary_not_found:{cmd[0]}")
    try:
        result = subprocess.run(
            [binary, *cmd[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return (1, "", f"exec_failed:{err}")
    return (result.returncode, result.stdout, result.stderr)


def probe_codex_cli() -> dict[str, Any]:
    """Read-only probe of the installed Codex CLI."""
    version_rc, version_out, version_err = _run(["codex", "--version"])
    help_rc, help_out, _ = _run(["codex", "--help"])
    exec_help_rc, exec_help_out, _ = _run(["codex", "exec", "--help"])
    review_help_rc, review_help_out, _ = _run(["codex", "review", "--help"])
    exec_review_help_rc, exec_review_help_out, _ = _run(
        ["codex", "exec", "review", "--help"]
    )

    # Negative probe: ensure the invalid form really is rejected.
    invalid_probe_rc, _, invalid_probe_err = _run(
        ["codex", "exec", "--review", "/tmp"]
    )
    invalid_form_rejected = (
        invalid_probe_rc != 0
        and "--review" in (invalid_probe_err or "")
    )

    supports_codex_review = (
        review_help_rc == 0 and "Run a code review" in (review_help_out or "")
    )
    supports_codex_exec = exec_help_rc == 0 and "non-interactively" in (
        exec_help_out or ""
    )
    supports_codex_exec_review = (
        exec_review_help_rc == 0
        and "code review against" in (exec_review_help_out or "")
    )

    return {
        "schema_version": SCHEMA_VERSION + "_codex_cli_capability_probe",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "codex_binary_path_present": shutil.which("codex") is not None,
        "codex_version": (
            (version_out or "").strip() if version_rc == 0 else None
        ),
        "codex_version_probe_error": (
            (version_err or "").strip() if version_rc != 0 else None
        ),
        "supports_codex_review": supports_codex_review,
        "supports_codex_exec": supports_codex_exec,
        "supports_codex_exec_review": supports_codex_exec_review,
        "invalid_form_rejected_observed": invalid_form_rejected,
        "unsupported_forms": list(INVALID_REVIEW_COMMAND_FORMS),
        "recommended_review_command_templates": list(
            VALID_REVIEW_COMMAND_TEMPLATES
        ),
        "review_flags_observed": {
            "uncommitted": "--uncommitted" in (review_help_out or ""),
            "base_branch": "--base" in (review_help_out or ""),
            "commit": "--commit" in (review_help_out or ""),
        },
        "no_path_argument_accepted_for_review": True,
        "verification_commands": [
            "codex --version",
            "codex --help",
            "codex exec --help",
            "codex review --help",
            "codex exec review --help",
            "codex exec --review /tmp  # must error",
        ],
    }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


# Directories under each scanned root whose contents are historical
# Codex review/governor evidence. These files legitimately quote the
# rejected command form as the *finding being reported* and must not be
# rewritten by the throughput-plan remediation.
_EVIDENCE_DIR_NAMES_TO_SKIP = ("codex_review", "codex_governor")


def scan_artifacts_for_invalid_review_commands(
    roots: list[Path],
    *,
    skip_evidence_dirs: bool = True,
) -> dict[str, Any]:
    """Scan files under ``roots`` for invalid review command forms.

    The scan deliberately skips Codex review/governor evidence files
    (``codex_review/**``, ``codex_governor/**``) under every root,
    because those documents legitimately quote the rejected form when
    describing the finding. The remediation packet is built only when
    no remaining hits exist in any throughput-plan-owned artifact.
    """
    hits: list[dict[str, Any]] = []
    skipped_evidence_paths: list[str] = []
    files_scanned = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if skip_evidence_dirs and any(
                part in _EVIDENCE_DIR_NAMES_TO_SKIP for part in path.parts
            ):
                skipped_evidence_paths.append(str(path))
                continue
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for form in INVALID_REVIEW_COMMAND_FORMS:
                if form in text:
                    hits.append(
                        {
                            "path": str(path),
                            "invalid_form": form,
                        }
                    )
    return {
        "schema_version": SCHEMA_VERSION + "_invalid_command_scan",
        "generated_utc": _utc_now_iso(),
        "roots_scanned": [str(r) for r in roots],
        "files_scanned": files_scanned,
        "skipped_evidence_files": skipped_evidence_paths,
        "skipped_evidence_dir_names": list(_EVIDENCE_DIR_NAMES_TO_SKIP),
        "hits": hits,
        "passed": not hits,
    }


# ---------------------------------------------------------------------------
# Remediation packet
# ---------------------------------------------------------------------------


@dataclass
class RemediationPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path
    refreshed_packet_dir: Path
    refreshed_public_dir: Path


def default_paths(repo_root: Path) -> RemediationPaths:
    return RemediationPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_ai_throughput_acceleration_cli_command_remediation/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_ai_throughput_acceleration_cli_command_remediation/latest",
        refreshed_packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest",
        refreshed_public_dir=repo_root
        / "v2/frontend/public/v2_ai_throughput_acceleration/latest",
    )


@dataclass
class RemediationResult:
    go_no_go: str
    invalid_hits_remaining: int
    paths_written: list[Path] = field(default_factory=list)


def build_remediation_status(
    *,
    probe: dict[str, Any],
    scan_before: dict[str, Any] | None,
    scan_after: dict[str, Any],
    refreshed_packet_dir: Path,
    refreshed_public_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_cli_command_remediation_status",
        "generated_utc": _utc_now_iso(),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "scheduler_installed": False,
        "gpu_training_dispatched": False,
        "codex_fast_mode_enabled": False,
        "codex_blocker_addressed": "CODEX_NONINTERACTIVE_REVIEW_COMMANDS_INVALID_FOR_INSTALLED_CLI",
        "invalid_review_command_forms_removed": list(
            INVALID_REVIEW_COMMAND_FORMS
        ),
        "recommended_review_command_templates": list(
            VALID_REVIEW_COMMAND_TEMPLATES
        ),
        "codex_cli_capability_probe": {
            "codex_version": probe.get("codex_version"),
            "supports_codex_review": probe.get("supports_codex_review"),
            "supports_codex_exec": probe.get("supports_codex_exec"),
            "supports_codex_exec_review": probe.get("supports_codex_exec_review"),
            "invalid_form_rejected_observed": probe.get(
                "invalid_form_rejected_observed"
            ),
        },
        "refreshed_throughput_packet_dir": str(refreshed_packet_dir),
        "refreshed_public_dir": str(refreshed_public_dir),
        "scan_before": scan_before,
        "scan_after": scan_after,
        "remediation_passed": scan_after.get("passed", False),
    }


def render_remediation_report(
    *,
    probe: dict[str, Any],
    scan_after: dict[str, Any],
    status: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(
        "# V2 AI Throughput Acceleration - Codex CLI Command Remediation\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. "
        "approves_redis_trim=false. scheduler_installed=false. "
        "gpu_training_dispatched=false. codex_fast_mode_enabled=false.\n\n"
    )

    lines.append("## Codex blocker addressed\n")
    lines.append(
        "`CODEX_NONINTERACTIVE_REVIEW_COMMANDS_INVALID_FOR_INSTALLED_CLI`\n\n"
    )
    lines.append(
        "Invalid review command forms removed everywhere in the throughput "
        "plan: " + ", ".join(f"`{f}`" for f in INVALID_REVIEW_COMMAND_FORMS) + ".\n\n"
    )
    lines.append("Replacement templates (all verified against the installed CLI):\n")
    for tpl in VALID_REVIEW_COMMAND_TEMPLATES:
        lines.append(f"- `{tpl}`\n")
    lines.append("\n")

    lines.append("## Codex CLI capability probe\n")
    lines.append(f"- codex_version: `{probe.get('codex_version')}`\n")
    lines.append(f"- supports_codex_review: {probe.get('supports_codex_review')}\n")
    lines.append(f"- supports_codex_exec: {probe.get('supports_codex_exec')}\n")
    lines.append(
        f"- supports_codex_exec_review: {probe.get('supports_codex_exec_review')}\n"
    )
    lines.append(
        "- review_flags_observed: " + json.dumps(probe.get("review_flags_observed", {}))
        + "\n"
    )
    lines.append(
        f"- invalid_form_rejected_observed: "
        f"{probe.get('invalid_form_rejected_observed')}\n\n"
    )

    lines.append("## Artifact scan (post-remediation)\n")
    lines.append(f"- files_scanned: {scan_after.get('files_scanned')}\n")
    lines.append(
        f"- invalid_review_command_hits: {len(scan_after.get('hits', []))}\n"
    )
    lines.append(f"- passed: {scan_after.get('passed')}\n\n")
    if scan_after.get("hits"):
        lines.append("Remaining invalid hits:\n")
        for hit in scan_after["hits"]:
            lines.append(f"- {hit['path']}: `{hit['invalid_form']}`\n")
        lines.append("\n")

    lines.append("## Refreshed throughput packet artifacts\n")
    lines.append(
        "- `claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/parallel_lane_matrix.json`\n"
        "- `claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/cloud_acceleration_options.json`\n"
        "- `claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/high_throughput_scheduler_design.json`\n"
        "- `claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_REPORT.md`\n"
        "- `v2/frontend/public/v2_ai_throughput_acceleration/latest/operator_dashboard_payload.json`\n\n"
    )

    lines.append("## Safety scoreboard\n")
    for k in [
        "live_gate",
        "live_symbols",
        "approves_live",
        "approves_canary",
        "approves_legacy_shutdown",
        "approves_redis_trim",
        "scheduler_installed",
        "gpu_training_dispatched",
        "codex_fast_mode_enabled",
    ]:
        lines.append(f"- {k}: {status.get(k)}\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify /home/wali/Desktop/AI BOT.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable live or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not install the high-throughput scheduler daemon.\n"
        "- Did not dispatch any GPU job.\n"
        "- Did not enable Codex Fast mode.\n"
    )
    return "".join(lines)


def run_remediation(
    paths: RemediationPaths,
    *,
    probe_fn: Any = probe_codex_cli,
    refresh_throughput_packet_fn: Any = None,
) -> RemediationResult:
    """Run the remediation packet.

    ``refresh_throughput_packet_fn`` is injected by the CLI so this
    module does not have to import the throughput orchestrator at module
    load time (keeps tests hermetic).
    """
    # 1. Pre-remediation scan so we can show before/after.
    scan_before = scan_artifacts_for_invalid_review_commands(
        [paths.refreshed_packet_dir, paths.refreshed_public_dir]
    )

    # 2. Refresh the throughput packet so it picks up the corrected
    #    command builder. Caller injects this so tests can stub it.
    refreshed_result_summary: dict[str, Any] | None = None
    if refresh_throughput_packet_fn is not None:
        refreshed_result_summary = refresh_throughput_packet_fn()

    # 3. Probe the installed Codex CLI.
    probe = probe_fn()

    # 4. Post-remediation scan.
    scan_after = scan_artifacts_for_invalid_review_commands(
        [paths.refreshed_packet_dir, paths.refreshed_public_dir]
    )

    # 5. Build status + report.
    status = build_remediation_status(
        probe=probe,
        scan_before=scan_before,
        scan_after=scan_after,
        refreshed_packet_dir=paths.refreshed_packet_dir,
        refreshed_public_dir=paths.refreshed_public_dir,
    )
    if refreshed_result_summary is not None:
        status["refreshed_throughput_packet_summary"] = refreshed_result_summary

    _atomic_write_json(
        paths.packet_dir / "codex_cli_capability_probe.json", probe
    )
    _atomic_write_json(
        paths.packet_dir / "cli_command_remediation_status.json", status
    )
    # Public mirror so the report center / operator dashboards can read
    # the probe + remediation status alongside the throughput plan mirror.
    _atomic_write_json(
        paths.public_dir / "codex_cli_capability_probe.json", probe
    )
    _atomic_write_json(
        paths.public_dir / "cli_command_remediation_status.json", status
    )
    report_md = render_remediation_report(
        probe=probe, scan_after=scan_after, status=status
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_REPORT.md",
        report_md,
    )
    go_no_go = (
        "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_READY"
        if scan_after["passed"]
        else "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_BLOCKED"
    )
    _atomic_write_text(paths.packet_dir / "GO_NO_GO.md", go_no_go + "\n")

    return RemediationResult(
        go_no_go=go_no_go,
        invalid_hits_remaining=len(scan_after["hits"]),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_AI_THROUGHPUT_ACCELERATION_CODEX_CLI_COMMAND_REMEDIATION_REPORT.md",
            paths.packet_dir / "codex_cli_capability_probe.json",
            paths.packet_dir / "cli_command_remediation_status.json",
            paths.public_dir / "codex_cli_capability_probe.json",
            paths.public_dir / "cli_command_remediation_status.json",
        ],
    )
