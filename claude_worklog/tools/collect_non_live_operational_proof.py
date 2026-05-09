#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
PROOF_DIR = ROOT / "claude_worklog/final_readiness/non_live_operational_proof"
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"

SECRET_PATTERN = re.compile(
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----|"
    r"xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[0-9A-Za-z_-]{20,}|AIza[0-9A-Za-z_-]{35}"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        shell=isinstance(cmd, str),
        text=True,
        capture_output=True,
        check=False,
    )


def write(rel: str, text: str) -> None:
    path = PROOF_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def shell_output(cmd: str) -> str:
    proc = run(cmd)
    parts = []
    if proc.stdout:
        parts.append(proc.stdout.rstrip())
    if proc.stderr:
        parts.append(proc.stderr.rstrip())
    parts.append(f"EXIT={proc.returncode}")
    return "\n".join(parts)


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)

    write(
        "00_PROOF_RUN_SCOPE.md",
        """# Non-Live Operational Proof Run

## Objective

Collect evidence that V2 non-live replay/backtest, paper mode, and shadow-readiness surfaces are usable.

## Hard safety

This proof run must not:
- modify /home/wali/Desktop/AI BOT
- write Redis
- delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- expose secrets

## Expected outcome

Evidence for:
- replay/backtest runner
- paper mode
- shadow readiness
- risk gateway default-deny behavior
- paper ledger
- explainability lineage
- live gate blocked

NON_LIVE_OPERATIONAL_PROOF_SCOPE_READY
""",
    )

    marker_cmd = (
        'grep -RInE "V2_BACKTEST_AND_PAPER_MVP_READY|V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS|'
        'PHASE2I_.*CODEX_PASS|PHASE2J_.*CODEX_PASS|PHASE2K_.*CODEX_PASS" '
        "claude_worklog/phase2_core_rebuild claude_worklog/final_readiness 2>/dev/null || true"
    )
    write(
        "01_FINAL_MVP_MARKERS.md",
        f"# Final MVP Marker Inventory\n\nGenerated: {now()}\n\n```text\n{shell_output(marker_cmd)}\n```",
    )

    surfaces_cmd = (
        "find v2 -type f | "
        'grep -E "replay|backtest|paper|shadow|risk_gateway|orchestrator|trainer_prediction|ledger|v2ctl|cli|api" | '
        "grep -v __pycache__ | sort"
    )
    write(
        "02_RUNNABLE_SURFACES.md",
        f"# Runnable Surface Inventory\n\nGenerated: {now()}\n\n"
        f"## CLI / API / Composition / Domain / Frontend surfaces\n\n```text\n{shell_output(surfaces_cmd)}\n```",
    )

    cli_parts = [
        "## v2ctl path",
        shell_output("ls -lh v2/backend/app/cli/v2ctl.py 2>/dev/null || true"),
        "## v2ctl help attempts",
        "### direct",
        shell_output("PYTHONPATH=. python3 v2/backend/app/cli/v2ctl.py --help 2>&1 || true"),
        "### module",
        shell_output("PYTHONPATH=. python3 -m v2.backend.app.cli.v2ctl --help 2>&1 || true"),
    ]
    write("03_CLI_HELP_INSPECTION.md", f"# CLI Help Inspection\n\nGenerated: {now()}\n\n" + "\n\n".join(cli_parts))

    validation_parts = [
        "## compile",
        shell_output("python3 -m compileall -q v2/backend/app v2/backend/tests 2>&1"),
        "## replay/backtest tests",
        shell_output('PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit -k "replay or backtest" 2>&1 || true'),
        "## paper mode / paper ledger tests",
        shell_output('PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit -k "paper or ledger" 2>&1 || true'),
        "## shadow readiness tests",
        shell_output('PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit -k "shadow" 2>&1 || true'),
        "## risk gateway tests",
        shell_output('PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit -k "risk_gateway or risk or default_deny" 2>&1 || true'),
        "## orchestrator / trainer prediction tests",
        shell_output(
            'PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit -k "orchestrator or trainer_prediction or prediction" 2>&1 || true'
        ),
    ]
    write("04_LOCAL_VALIDATION_OUTPUT.md", f"# Local Validation Output\n\nGenerated: {now()}\n\n" + "\n\n".join(validation_parts))

    harness_cmd = (
        "find claude_worklog/phase2_core_rebuild v2 -type f 2>/dev/null | "
        'grep -E "replay|backtest|pnl|drawdown|result|harness|ledger|paper|shadow" | '
        "grep -v __pycache__ | sort"
    )
    go_cmd = (
        'grep -RInE "REPLAY|BACKTEST|PAPER|SHADOW|PNL|DRAWDOWN|GO_NO_GO|CODEX_PASS|READY" '
        "claude_worklog/phase2_core_rebuild claude_worklog/final_readiness 2>/dev/null | tail -240 || true"
    )
    write(
        "05_EXISTING_HARNESS_OUTPUTS.md",
        f"# Existing Harness Output Inventory\n\nGenerated: {now()}\n\n"
        f"## Replay/backtest artifacts\n\n```text\n{shell_output(harness_cmd)}\n```\n\n"
        f"## Existing GO/NO-GO markers\n\n```text\n{shell_output(go_cmd)}\n```",
    )

    legacy = (ROOT / "claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md").read_text(errors="replace") if (
        ROOT / "claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md"
    ).exists() else ""
    historical = (ROOT / "claude_worklog/historical_pnl_audit/10_GO_NO_GO.md").read_text(errors="replace") if (
        ROOT / "claude_worklog/historical_pnl_audit/10_GO_NO_GO.md"
    ).exists() else ""
    historical_status = (
        ROOT / "claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md"
    ).read_text(errors="replace") if (ROOT / "claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md").exists() else ""
    write(
        "06_LEGACY_AND_HISTORICAL_AUDIT_STATUS.md",
        f"# Legacy and Historical Audit Status\n\nGenerated: {now()}\n\n"
        f"## Legacy read-only audit\n\n```text\n{legacy.strip()}\n```\n\n"
        f"## Historical PnL audit\n\n```text\n{historical.strip()}\n```\n\n"
        f"## Historical PnL data-source status\n\n{historical_status}",
    )

    live_scan_cmd = (
        'grep -RInE "redis-cli|XADD|XDEL|FLUSHDB|FLUSHALL|create_order|cancel_order|change_leverage|'
        'change_margin|/home/wali/Desktop/AI BOT|systemctl restart|sudo systemctl|enable live trading|LIVE_TRADING_ENABLED" '
        "v2/backend/app v2/backend/tests claude_worklog/phase2_core_rebuild --exclude='*.pyc' || true"
    )
    write("07_NO_LIVE_SIDE_EFFECT_SCAN.md", f"# No Live Side Effect Scan\n\nGenerated: {now()}\n\n```text\n{shell_output(live_scan_cmd)}\n```")

    secret_scan_paths = [PROOF_DIR, ROOT / "v2/backend/app", ROOT / "v2/backend/tests"]
    secret_hits: list[str] = []
    for base in secret_scan_paths:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix != ".pyc":
                try:
                    text = path.read_text(errors="replace")
                except Exception:
                    continue
                for match in SECRET_PATTERN.finditer(text):
                    secret_hits.append(f"{path.relative_to(ROOT)}:{match.start()}: {match.group(0)[:24]}")
    write("08_SECRET_SCAN.txt", "\n".join(secret_hits))
    if secret_hits:
        print("SECRET_SCAN_FAILED")
        print("\n".join(secret_hits[:160]))
        return 2

    write(
        "09_NON_LIVE_OPERATIONAL_PROOF_SUMMARY.md",
        """# Non-Live Operational Proof Summary

## Status

The V2 non-live MVP markers exist. This proof package collects runnable surfaces, tests, audit status, and safety scans.

## Required review questions

1. Can replay/backtest surfaces be invoked safely?
2. Can paper-mode surfaces be invoked safely?
3. Can shadow-readiness surfaces be invoked safely?
4. Do tests pass for replay/backtest, paper, shadow, risk, orchestrator, trainer prediction?
5. Does the proof package show live gate remains blocked?
6. Does historical/legacy audit evidence exist?
7. Are there missing executable harness commands?

## Live status

Live trading remains blocked and human-only.

NON_LIVE_OPERATIONAL_PROOF_SUMMARY_READY
""",
    )

    task = {
        "task_id": "182_codex_review_non_live_operational_proof",
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "allowed_output_prefixes": ["claude_worklog/final_readiness/non_live_operational_proof/"],
        "required_output_files": [
            "claude_worklog/final_readiness/non_live_operational_proof/10_CODEX_REVIEW.md",
            "claude_worklog/final_readiness/non_live_operational_proof/11_CODEX_GO_NO_GO.md",
        ],
        "prompt": (
            "You are local Codex CLI in /home/wali/Desktop/AI BOT REBUILD. Review the non-live operational proof package under "
            "claude_worklog/final_readiness/non_live_operational_proof. Do not touch /home/wali/Desktop/AI BOT. Do not write Redis. "
            "Do not restart live services. Do not place/cancel orders. Do not enable live trading. Determine whether the V2 non-live "
            "MVP is ready for actual operator inspection of replay/backtest, paper mode, and shadow readiness evidence. Identify missing "
            "executable harnesses or proof gaps. Output exactly two BEGIN_FILE blocks. The GO/NO-GO file must contain one line: "
            "NON_LIVE_OPERATIONAL_PROOF_CODEX_PASS or NON_LIVE_OPERATIONAL_PROOF_CODEX_FAIL."
        ),
        "lane": "codex_watchdog",
        "mvp_relevance": "Reviews whether V2_BACKTEST_AND_PAPER_MVP_READY has sufficient operational proof for human inspection.",
        "blocked_by": [],
        "next_gate": "NON_LIVE_OPERATIONAL_PROOF_CODEX_PASS",
        "legacy_evidence_consulted": ["legacy_readonly_audit", "historical_pnl_audit", "final MVP markers"],
        "legacy_failure_addressed": ["paper/backtest readiness uncertainty", "lack of operator-visible proof package"],
    }
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    (TASKS_DIR / "182_codex_review_non_live_operational_proof.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")

    print("NON_LIVE_OPERATIONAL_PROOF_PACKAGE_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
