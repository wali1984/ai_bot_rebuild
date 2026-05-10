#!/usr/bin/env python3
"""Codex acting-governor status and task selection.

This deterministic helper runs only inside AI BOT REBUILD and does not execute
live, Redis, legacy, or exchange mutations. It gives the scheduler a concrete
Codex lane decision while Claude is rate-limited.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/claude_codex_rate_limit_handoff/latest"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main() -> int:
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
    selection = {
        "generated_at": now(),
        "mode": "codex_acting_governor",
        "claude_rate_limited": scheduler.get("claude_rate_limited", True),
        "selected_task": scheduler.get("next_safe_codex_task") or queue.get("next_pending_task") or "safe_non_live_backlog_review",
        "can_codex_execute_now": True,
        "can_codex_review_now": True,
        "can_ollama_prepare_evidence": True,
        "requires_claude_after_reset": bool(queue.get("next_pending_task")),
        "final_live_gate_required": False,
        "live_gate_status": "blocked_human_only",
        "forbidden_actions": [
            "legacy mutation",
            "Redis mutation without exact approval",
            "real exchange action",
            "live leverage/margin/position-mode changes",
            "live trading enablement",
            "secret exposure",
        ],
    }
    write_json(OUT / "codex_acting_governor_selection.json", selection)
    with (OUT / "codex_takeover_task_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), "event": "codex_acting_governor_selection", **selection}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
