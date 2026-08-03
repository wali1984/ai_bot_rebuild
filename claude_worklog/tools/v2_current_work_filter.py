"""Current-work filter for the V2 closed-loop execution engine.

The engine's first real-mode pass must not dispatch hundreds of stale
historical descriptors that happen to still have ``status=pending`` on
disk. This module classifies each candidate descriptor as either
*current* (genuinely automatable now) or *historical noise*, and emits
two payloads:

* ``current_automatable_work_queue.json`` — the bounded queue the
  runners should consume.
* ``historical_task_noise_summary.json`` — counts and category
  rollups of the descriptors we excluded, so the operator can audit
  the filter decision.

Inclusion rules (any one suffices):

1. ``current_active: true`` on the descriptor.
2. Task id listed in the curated allowlist file
   ``current_work_allowlist.json``.
3. Descriptor created/updated within ``--active-window-hours``
   (default 24h).
4. Descriptor referenced by current report-center top blockers
   (``current_blockers`` / ``next_action`` fields in any operator
   payload published in the last 24h).
5. Descriptor referenced by a current Codex FAIL marker (any
   ``CODEX_GO_NO_GO.md`` in the last 24h whose verdict ends with
   ``_CODEX_FAIL``).

Exclusion rules (any one suffices, even if an inclusion rule matched):

* status in {``blocked_operator_required``, ``duplicate_suppressed``,
  ``completed``, ``stale``, ``failed``}.
* ``depends_on`` / ``predecessor_task_ids`` references a descriptor that
  has not completed yet.
* descriptor / filename mentions live, canary, shutdown, exchange
  mutation, kill-switch, redis trim, leverage, margin,
  checkpoint promotion, credential purge (operator-gated).
* descriptor has ``operator_required_reason`` set.
* ``superseded_by`` field is set.

The filter is read-only with respect to task descriptors — it never
edits a descriptor; it only emits the queue/summary payloads.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
REAL_MODE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution_real_mode_enablement"
    / "latest"
)
WORKLOG_FINAL_READINESS = REPO_ROOT / "claude_worklog" / "final_readiness"

DEFAULT_ACTIVE_WINDOW_HOURS = 24

EXCLUDE_KEYWORDS = (
    "live_trade",
    "live_trading",
    "live_canary",
    "canary_safety",
    "shutdown",
    "exchange_mutation",
    "exchange_order_dispatch",
    "kill_switch",
    "redis_trim",
    "redis_xtrim",
    "leverage",
    "margin_mode",
    "checkpoint_promotion",
    "credential_rotation",
    "credential_eviction",
    "paid_feed",
    "git_history_rewrite",
)

EXCLUDE_STATUSES = (
    "blocked_operator_required",
    "blocked_dependency",
    "duplicate_suppressed",
    "completed",
    "stale",
    "failed",
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _iso_to_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _load_allowlist() -> set[str]:
    p = REAL_MODE_DIR / "current_work_allowlist.json"
    if not p.exists():
        return set()
    data = _read_json(p)
    if not isinstance(data, dict):
        return set()
    raw = data.get("task_ids") or []
    return {str(t) for t in raw if isinstance(t, (str, int))}


def _gather_current_blocker_task_ids() -> set[str]:
    cutoff = time.time() - DEFAULT_ACTIVE_WINDOW_HOURS * 3600
    refs: set[str] = set()
    if not WORKLOG_FINAL_READINESS.exists():
        return refs
    for path in WORKLOG_FINAL_READINESS.rglob("operator_dashboard_payload.json"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        for key in ("current_blockers", "blockers", "next_action"):
            v = data.get(key)
            if isinstance(v, list):
                for s in v:
                    refs.update(_extract_task_ids(str(s)))
            elif isinstance(v, str):
                refs.update(_extract_task_ids(v))
    return refs


def _gather_recent_codex_fail_task_ids() -> set[str]:
    cutoff = time.time() - DEFAULT_ACTIVE_WINDOW_HOURS * 3600
    refs: set[str] = set()
    if not WORKLOG_FINAL_READINESS.exists():
        return refs
    for path in WORKLOG_FINAL_READINESS.rglob("CODEX_GO_NO_GO.md"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "_CODEX_FAIL" not in text:
            continue
        refs.add(path.parent.name)
        refs.update(_extract_task_ids(text))
    return refs


TASK_ID_RE = re.compile(r"\b([0-9]{2,4}[a-z]?_[a-z][a-z0-9_]+)\b")


def _extract_task_ids(text: str) -> set[str]:
    return {m for m in TASK_ID_RE.findall(text or "")}


def _descriptor_keyword_excluded(name: str, d: dict[str, Any]) -> str | None:
    haystack = " ".join(
        [
            name.lower(),
            str(d.get("task_id") or "").lower(),
            str(d.get("prompt") or "").lower()[:2000],
            str(d.get("next_action") or "").lower(),
        ]
    )
    for kw in EXCLUDE_KEYWORDS:
        if kw in haystack:
            return kw
    return None


def _dependency_pending(d: dict[str, Any]) -> str | None:
    deps = d.get("depends_on") or d.get("predecessor_task_ids") or []
    if isinstance(deps, str):
        deps = [deps]
    if not isinstance(deps, list):
        return None
    for dep in deps:
        dep_id = str(dep)
        dep_path = TASKS_DIR / f"{dep_id}.json"
        dep_raw = _read_json(dep_path)
        if not isinstance(dep_raw, dict):
            return dep_id
        if dep_raw.get("status") != "completed":
            return dep_id
    return None


def classify_descriptor(
    path: Path,
    d: dict[str, Any],
    *,
    allowlist: set[str],
    blocker_refs: set[str],
    fail_refs: set[str],
    active_window_hours: int,
) -> dict[str, Any]:
    task_id = d.get("task_id") or path.stem
    status = d.get("status") or "pending"

    excluded_reason: str | None = None
    if status in EXCLUDE_STATUSES:
        excluded_reason = f"status={status}"
    if not excluded_reason and d.get("operator_required_reason"):
        excluded_reason = f"operator_required_reason={d.get('operator_required_reason')}"
    if not excluded_reason and d.get("superseded_by"):
        excluded_reason = f"superseded_by={d.get('superseded_by')}"
    if not excluded_reason:
        pending_dep = _dependency_pending(d)
        if pending_dep:
            excluded_reason = f"dependency_pending={pending_dep}"
    if not excluded_reason:
        kw = _descriptor_keyword_excluded(path.name, d)
        if kw:
            excluded_reason = f"keyword={kw}"

    cutoff = time.time() - active_window_hours * 3600
    age_sources: list[tuple[str, float | None]] = []
    age_sources.append(("created_at", _iso_to_ts(d.get("created_at"))))
    age_sources.append(("updated_at", _iso_to_ts(d.get("updated_at"))))
    try:
        age_sources.append(("file_mtime", path.stat().st_mtime))
    except OSError:
        age_sources.append(("file_mtime", None))
    fresh_ts = max(
        (ts for _, ts in age_sources if isinstance(ts, (int, float))),
        default=None,
    )
    recent = bool(fresh_ts and fresh_ts >= cutoff)

    inclusion_reasons: list[str] = []
    if d.get("current_active") is True:
        inclusion_reasons.append("current_active_true")
    if str(task_id) in allowlist:
        inclusion_reasons.append("allowlist")
    if recent:
        inclusion_reasons.append("within_active_window")
    if str(task_id) in blocker_refs:
        inclusion_reasons.append("report_center_blocker_reference")
    if str(task_id) in fail_refs:
        inclusion_reasons.append("recent_codex_fail_reference")

    included = bool(inclusion_reasons) and excluded_reason is None
    return {
        "task_id": task_id,
        "path": str(path.relative_to(REPO_ROOT)),
        "status": status,
        "task_type": d.get("task_type"),
        "owner": d.get("owner"),
        "file_lock_group": d.get("file_lock_group"),
        "freshness_ts": fresh_ts,
        "recent": recent,
        "inclusion_reasons": inclusion_reasons,
        "excluded_reason": excluded_reason,
        "included": included,
    }


def iter_descriptors() -> Iterable[tuple[Path, dict[str, Any]]]:
    if not TASKS_DIR.exists():
        return []
    for f in sorted(TASKS_DIR.iterdir()):
        if f.suffix != ".json":
            continue
        raw = _read_json(f)
        if not isinstance(raw, dict):
            continue
        yield f, raw


def build_current_work_queue(
    *,
    active_window_hours: int = DEFAULT_ACTIVE_WINDOW_HOURS,
) -> dict[str, Any]:
    allowlist = _load_allowlist()
    blocker_refs = _gather_current_blocker_task_ids()
    fail_refs = _gather_recent_codex_fail_task_ids()

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    excluded_by_reason: dict[str, int] = {}

    for path, raw in iter_descriptors():
        verdict = classify_descriptor(
            path, raw,
            allowlist=allowlist,
            blocker_refs=blocker_refs,
            fail_refs=fail_refs,
            active_window_hours=active_window_hours,
        )
        if verdict["included"]:
            included.append(verdict)
        else:
            excluded.append(verdict)
            reason = verdict.get("excluded_reason") or "not_current_no_inclusion_reason"
            bucket = reason.split("=")[0] if "=" in reason else reason
            excluded_by_reason[bucket] = excluded_by_reason.get(bucket, 0) + 1

    queue = {
        "schema_version": "v2_closed_loop_current_work_queue_v1",
        "generated_utc": _utc_iso(),
        "active_window_hours": active_window_hours,
        "allowlist_size": len(allowlist),
        "report_center_blocker_refs_size": len(blocker_refs),
        "recent_codex_fail_refs_size": len(fail_refs),
        "current_automatable_count": len(included),
        "historical_excluded_count": len(excluded),
        "current": included,
        "safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
    }
    noise = {
        "schema_version": "v2_closed_loop_historical_task_noise_summary_v1",
        "generated_utc": _utc_iso(),
        "active_window_hours": active_window_hours,
        "historical_excluded_count": len(excluded),
        "excluded_by_reason": excluded_by_reason,
        "sample_excluded": excluded[:50],
    }
    return {"queue": queue, "noise": noise, "allowlist": sorted(allowlist)}


def write_outputs(result: dict[str, Any], *, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "current_automatable_work_queue.json").write_text(
        json.dumps(result["queue"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "historical_task_noise_summary.json").write_text(
        json.dumps(result["noise"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--active-window-hours", type=int, default=DEFAULT_ACTIVE_WINDOW_HOURS)
    p.add_argument("--out-dir", type=Path, default=REAL_MODE_DIR)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = build_current_work_queue(active_window_hours=args.active_window_hours)
    write_outputs(result, out_dir=args.out_dir)
    if args.json:
        print(json.dumps(result["queue"], indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": result["queue"]["generated_utc"],
            "current_automatable_count": result["queue"]["current_automatable_count"],
            "historical_excluded_count": result["queue"]["historical_excluded_count"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
