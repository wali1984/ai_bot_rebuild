"""V2 full observation missing-feature source-map CLI (paper-only).

Reads legacy observation contract + V2 native source registry and emits
the worklog status + public operator dashboard payload. Creates exactly
one narrow Claude+Codex task pair per missing source family (no
duplicates if the task already exists).

Never imports torch. Never deserializes any blob.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.rl_core.missing_feature_source_map import (
    build_missing_feature_source_map,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_full_observation_missing_feature_source_map/latest/missing_feature_source_map_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_full_observation_missing_feature_source_map/latest/operator_dashboard_payload.json"
)
TASKS_DIR = Path("claude_worklog/agent_supervisor/tasks")

CLAUDE_FORBIDDEN_ACTIONS = (
    "modify /home/wali/Desktop/AI BOT",
    "stop or restart legacy",
    "write old Redis keys",
    "place or cancel exchange orders",
    "change leverage or margin",
    "enable live",
    "create approval token",
    "execute legacy monitor scripts",
    "load torch weights into V2 process",
    "commit checkpoint blobs to Git",
    "fabricate missing observation dimensions",
)

CODEX_FAIL_CONDITIONS = (
    "approve loading legacy pickle into V2 process",
    "approve any live or canary or shutdown or redis trim action",
    "approve broad audit loop",
    "claim policy architecture port complete",
    "claim checkpoint compatibility",
    "approve zero-fill of missing observation dimensions",
    "approve creating paper-only shutdown acceptance file",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ensure_task_pair(
    *,
    claude_task_id: str,
    codex_task_id: str,
    family_id: str,
    severity: str,
    v2_source_status: str,
    rationale: str,
    legacy_size_per_source: int,
) -> dict[str, object]:
    """Idempotent task-pair writer. Preserves any status/result/codex_decision
    fields already on disk.
    """
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    claude_path = TASKS_DIR / f"{claude_task_id}.json"
    codex_path = TASKS_DIR / f"{codex_task_id}.json"
    existed_claude = claude_path.exists()
    existed_codex = codex_path.exists()
    now = _utc_iso()
    base_claude = {
        "task_id": claude_task_id,
        "kind": "claude_narrow_remediation",
        "gap_id": f"full_observation_source_{family_id}",
        "family_id": family_id,
        "severity": severity,
        "auto_apply_allowed_by_this_loop": False,
        "v2_source_status": v2_source_status,
        "rationale": rationale,
        "legacy_size_per_source": legacy_size_per_source,
        "paired_codex_review_task_id": codex_task_id,
        "forbidden_actions": list(CLAUDE_FORBIDDEN_ACTIONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "created_utc": now,
        "updated_utc": now,
    }
    base_codex = {
        "task_id": codex_task_id,
        "kind": "codex_review",
        "paired_claude_task_id": claude_task_id,
        "gap_id": f"full_observation_source_{family_id}",
        "family_id": family_id,
        "severity": severity,
        "fail_conditions": list(CODEX_FAIL_CONDITIONS),
        "created_utc": now,
        "updated_utc": now,
    }
    if existed_claude:
        prev = _read_json(claude_path) or {}
        preserved = {
            k: prev[k] for k in ("status", "completed_utc", "result", "codex_decision")
            if k in prev
        }
        merged = {**prev, **base_claude, **preserved, "updated_utc": now}
        merged["created_utc"] = prev.get("created_utc", now)
        _write_json(claude_path, merged)
    else:
        _write_json(claude_path, base_claude)
    if existed_codex:
        prev = _read_json(codex_path) or {}
        preserved = {
            k: prev[k] for k in ("status", "completed_utc", "result", "codex_decision")
            if k in prev
        }
        merged = {**prev, **base_codex, **preserved, "updated_utc": now}
        merged["created_utc"] = prev.get("created_utc", now)
        _write_json(codex_path, merged)
    else:
        _write_json(codex_path, base_codex)
    return {
        "family_id": family_id,
        "claude_task_path": str(claude_path),
        "codex_task_path": str(codex_path),
        "claude_existed_before": existed_claude,
        "codex_existed_before": existed_codex,
        "severity": severity,
        "v2_source_status": v2_source_status,
    }


def run_once() -> dict:
    payload = build_missing_feature_source_map()
    pairs_written: list[dict[str, object]] = []
    for t in payload.get("narrow_tasks_required", []):
        pairs_written.append(
            _ensure_task_pair(
                claude_task_id=t["task_id"],
                codex_task_id=t["paired_codex_review_task_id"],
                family_id=t["family_id"],
                severity=t["severity"],
                v2_source_status=t["v2_source_status"],
                rationale=t["rationale"],
                legacy_size_per_source=int(t["legacy_size_per_source"]),
            )
        )
    payload["task_pairs_written_or_existing"] = pairs_written
    payload["narrow_tasks_created_count"] = sum(
        1 for p in pairs_written if not p["claude_existed_before"]
    )
    payload["narrow_tasks_existing_count"] = sum(
        1 for p in pairs_written if p["claude_existed_before"]
    )
    payload["go_no_go"] = "V2_FULL_OBSERVATION_MISSING_FEATURE_SOURCE_MAP_READY"
    _write_json(WORKLOG_STATUS, payload)
    _write_json(PUBLIC_DASHBOARD, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_full_observation_missing_feature_source_map_status"
    )
    parser.add_argument("--once", action="store_true")
    parser.parse_args(argv or [])
    payload = run_once()
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "status_counts": payload["status_counts"],
                "narrow_tasks_required_count": payload["narrow_tasks_required_count"],
                "narrow_tasks_created_count": payload["narrow_tasks_created_count"],
                "narrow_tasks_existing_count": payload["narrow_tasks_existing_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
