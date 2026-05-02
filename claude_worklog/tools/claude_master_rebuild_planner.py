#!/usr/bin/env python3
"""Claude Master Rebuild Planner entrypoint.

This script prepares a bounded prompt for Claude to choose the next non-live
rebuild milestone from repo evidence. It does not grant live permissions.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from typing import Dict


WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
STATUS = WORKSPACE / "claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_status.json"
PROMPT_OUT = WORKSPACE / "claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt"

EVIDENCE_ROOTS = [
    "legacy_reference",
    "v2",
    "claude_worklog/v2_requirements",
    "claude_worklog/v2_architecture",
    "claude_worklog/legacy_preservation",
    "claude_worklog/phase2_core_rebuild",
    "claude_worklog/legacy_runtime_audit",
]


def build_prompt() -> str:
    return """You are Claude Code running as the Master Non-Live V2 Rebuild Planner.

Read the repo evidence roots:
{roots}

Objective:
- Determine the next safest non-live rebuild milestone.
- Create task definitions, implementation outputs, validation reports, and Codex review tasks.
- Remediate Codex findings automatically when safe.
- Continue until final live gate.

Hard stops:
- Do not modify /home/wali/Desktop/AI BOT.
- Do not write/delete Redis.
- Do not restart live services.
- Do not place/cancel exchange orders.
- Do not change leverage/margin.
- Do not enable live trading.
- Do not deploy.
- Do not expose or commit secrets.
- Stop on L4/L5, live/legacy/Redis/exchange/deploy/secrets, or Codex hard fail with no safe remediation.

Preservation rules:
- live_coinank.py remains copied as-is; do not alter behavior.
- Other ingestors and feature_pipeline preserve behavior first; wrap/adapt before enhancement.
- Trainer rebuild must preserve GPU/hybrid tuned behavior, checkpoint behavior, proposal/confidence/reward logic, and worker liveness assumptions.
- Legacy config.py 25 symbols are active subset, not full V2 universe.

Output policy:
- Produce BEGIN_FILE blocks only when invoked through Claude.
- Keep every output inside AI BOT REBUILD.
""".format(roots="\n".join(f"- {root}" for root in EVIDENCE_ROOTS))


def write_status(payload: Dict[str, object]) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    prompt = build_prompt()
    PROMPT_OUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_OUT.write_text(prompt, encoding="utf-8")
    payload: Dict[str, object] = {
        "status": "ready",
        "mode": "status" if args.status else "dry-run" if args.dry_run else "run-once" if args.run_once else "status",
        "prompt_path": str(PROMPT_OUT.relative_to(WORKSPACE)),
        "evidence_roots": EVIDENCE_ROOTS,
        "live_gate": "blocked",
    }
    if args.run_once:
        cp = subprocess.run(
            ["claude", "--print", prompt, "--output-format", "text"],
            cwd=str(WORKSPACE),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=3600,
        )
        payload.update({"returncode": cp.returncode, "stdout_chars": len(cp.stdout), "stderr_chars": len(cp.stderr)})
        if cp.returncode != 0:
            payload["status"] = "human_attention_required"
    write_status(payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] != "human_attention_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())
