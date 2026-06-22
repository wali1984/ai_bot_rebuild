"""Spark canary rollback script.

Purpose
-------
Restore pre-Spark wrapper behaviour OR set LEASE_BACKEND=file so that
the closed-loop workers use the file-backed lease path instead of the
SQLite WAL store.

Safety constraints (hard-coded, cannot be overridden via CLI):
- Does NOT stop legacy AI BOT services.
- Does NOT stop V2 runtime services.
- Does NOT stop report-center / replay-miner.
- Does NOT stop existing persistent Claude/Codex workers.
- Does NOT touch exchange APIs or live orders.
- Does NOT write old Redis keys.
- Does NOT create approvals.
- Does NOT enable live trading.
- live_gate=blocked_human_only  live_symbols=[]  approves_live=False.
- Preserves Spark SQLite DB for audit (read-only rename, not deletion).
- Only disables Spark *canary-only* units when they exist.

Usage
-----
    python3 claude_worklog/tools/v2_codex_spark_rollback.py [--dry-run]
    python3 claude_worklog/tools/v2_codex_spark_rollback.py --mode=file-backend
    python3 claude_worklog/tools/v2_codex_spark_rollback.py --mode=disable-canary-units
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "claude_worklog/final_readiness/v2_codex_spark_backward_compatibility_canary_cutover/latest"

# Units that are exclusively Spark / canary staging.  These are safe to stop.
# Do NOT include: persistent claude/codex worker@, report-center, replay-miner, legacy units.
CANARY_ONLY_UNITS: list[str] = [
    "ai-bot-v2-closed-loop-worker-pool.service",
    "ai-bot-v2-closed-loop-worker-pool.timer",
    "ai-bot-v2-closed-loop-executor.service",
    "ai-bot-v2-closed-loop-executor.timer",
]

# Units that MUST NOT be stopped by rollback.
PROTECTED_UNITS: list[str] = [
    "ai-bot-v2-closed-loop-claude-worker@1.service",
    "ai-bot-v2-closed-loop-claude-worker@2.service",
    "ai-bot-v2-closed-loop-claude-worker@3.service",
    "ai-bot-v2-closed-loop-codex-worker@1.service",
    "ai-bot-v2-closed-loop-codex-worker@2.service",
    "ai-bot-v2-closed-loop-codex-worker@3.service",
    "ai-bot-v2-report-center-indexer.service",
    "ai-bot-v2-post-hoc-replay-outcome-miner.service",
    "ai-bot-v2-agent-supervisor.service",
    "ai-bot-v2-autonomous-mission-backlog.service",
    "ai-bot-v2-autonomous-mission-execution-burndown.service",
]

SAFE_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(cmd: list[str], dry_run: bool) -> tuple[int, str]:
    print(f"  {'[DRY-RUN] ' if dry_run else ''}$ {' '.join(cmd)}")
    if dry_run:
        return 0, ""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ↳ stderr: {r.stderr.strip()[:200]}")
    return r.returncode, r.stdout


def rollback_file_backend(dry_run: bool) -> dict:
    """Set LEASE_BACKEND=file override drop-in for canary units."""
    steps = []
    systemd_user = Path.home() / ".config/systemd/user"

    for unit in CANARY_ONLY_UNITS:
        if not unit.endswith(".service"):
            continue
        drop_in_dir = systemd_user / f"{unit}.d"
        drop_in = drop_in_dir / "50-lease-backend-file.conf"
        content = "[Service]\nEnvironment=LEASE_BACKEND=file\n"
        steps.append({"action": "write_drop_in", "path": str(drop_in), "content": content})
        if not dry_run:
            drop_in_dir.mkdir(parents=True, exist_ok=True)
            drop_in.write_text(content)

    # Reload systemd
    rc, _ = _run(["systemctl", "--user", "daemon-reload"], dry_run)
    steps.append({"action": "daemon_reload", "rc": rc})

    return {"mode": "file_backend", "dry_run": dry_run, "steps": steps}


def rollback_disable_canary_units(dry_run: bool) -> dict:
    """Stop and disable canary-only Spark units, leaving everything else running."""
    steps = []
    for unit in CANARY_ONLY_UNITS:
        # Safety guard — never stop protected units
        if unit in PROTECTED_UNITS:
            steps.append({"unit": unit, "action": "SKIP_PROTECTED"})
            continue
        rc, _ = _run(["systemctl", "--user", "stop", unit], dry_run)
        steps.append({"unit": unit, "action": "stop", "rc": rc})
        rc2, _ = _run(["systemctl", "--user", "disable", unit], dry_run)
        steps.append({"unit": unit, "action": "disable", "rc": rc2})

    rc, _ = _run(["systemctl", "--user", "daemon-reload"], dry_run)
    steps.append({"action": "daemon_reload", "rc": rc})

    return {"mode": "disable_canary_units", "dry_run": dry_run, "steps": steps}


def preserve_spark_db(dry_run: bool) -> dict:
    """Rename Spark SQLite DB to .audit-preserved (never delete)."""
    db_path = (
        REPO_ROOT
        / "claude_worklog/final_readiness/v2_closed_loop_spark/state/leases.db"
    )
    if not db_path.exists():
        return {"db_preserved": False, "reason": "db_not_found"}
    ts = int(time.time())
    dest = db_path.with_suffix(f".audit-preserved-{ts}.db")
    if not dry_run:
        shutil.copy2(db_path, dest)
    return {"db_preserved": True, "original": str(db_path), "copy": str(dest), "dry_run": dry_run}


def emit_proof(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    proof = {
        "generated_at": _utc_iso(),
        "schema_version": "1",
        "safe_envelope": SAFE_ENVELOPE,
        "rollback_result": result,
        "protected_units_untouched": PROTECTED_UNITS,
        "canary_only_units_targeted": CANARY_ONLY_UNITS,
        "legacy_untouched": True,
        "live_untouched": True,
        "report_center_untouched": True,
        "replay_miner_untouched": True,
    }
    path = out_dir / "spark_rollback_proof.json"
    path.write_text(json.dumps(proof, indent=2, sort_keys=True))
    print(f"✅ Rollback proof written → {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--mode",
        choices=("file-backend", "disable-canary-units"),
        default="file-backend",
        help="Rollback mode:\n"
             "  file-backend          – inject LEASE_BACKEND=file drop-in (default)\n"
             "  disable-canary-units  – stop+disable Spark-only timer/service units",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args(argv)

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Spark canary rollback — mode={args.mode}")
    print(f"  live_gate={SAFE_ENVELOPE['live_gate']}  live_symbols={SAFE_ENVELOPE['live_symbols']}")

    db_result = preserve_spark_db(args.dry_run)
    print(f"  Spark DB preserved: {db_result}")

    if args.mode == "file-backend":
        result = rollback_file_backend(args.dry_run)
    else:
        result = rollback_disable_canary_units(args.dry_run)

    result["db_preserve"] = db_result
    emit_proof(result, OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
