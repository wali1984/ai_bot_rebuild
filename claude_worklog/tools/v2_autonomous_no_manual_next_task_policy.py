"""Install/enforce the V2 autonomous no-manual-next-task policy.

The policy closes the gap where Report Center can show unresolved work while
the operator still has to hand-write the next implementation/review prompt.
It classifies current Report Center actions, seeds paired Spark tasks only for
safe automatable work, and keeps true operator/event/external blockers visible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.closed_loop.lane_registry import (  # noqa: E402
    codex_review_lane_for_claude,
    get_group_for_mission_category,
)
from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore  # noqa: E402

LANE_ID = "v2_autonomous_no_manual_next_task_policy"
GO_READY = "V2_AUTONOMOUS_NO_MANUAL_NEXT_TASK_POLICY_READY"
GO_BLOCKED = "V2_AUTONOMOUS_NO_MANUAL_NEXT_TASK_POLICY_BLOCKED"

WORKLOG_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / LANE_ID / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / LANE_ID / "latest"
REPORT_INDEX = REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json"
TASK_MIRROR_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution"
    / "latest"
    / "tasks"
)

SAFE_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
}

CLASS_AUTOMATABLE = "AUTOMATABLE_NOW"
CLASS_OPERATOR = "OPERATOR_DECISION_REQUIRED"
CLASS_EXTERNAL = "EXTERNAL_SOURCE_REQUIRED"
CLASS_EVENT = "EVENT_DEPENDENT"
CLASS_POSITION = "POSITION_DEPENDENT"
CLASS_UNSAFE = "UNSAFE_TO_AUTOMATE"

CLASS_OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
CLASS_EXTERNAL_REQUIRED = "EXTERNAL_REQUIRED"
PROTOCOL_CLASSIFICATIONS = (
    CLASS_AUTOMATABLE,
    CLASS_OPERATOR_REQUIRED,
    CLASS_EXTERNAL_REQUIRED,
    CLASS_UNSAFE,
)
ALLOWED_CLASSES = {
    CLASS_AUTOMATABLE,
    CLASS_OPERATOR,
    CLASS_EXTERNAL,
    CLASS_EVENT,
    CLASS_POSITION,
    CLASS_UNSAFE,
}

MISSION_CATEGORIES = (
    "runtime stability",
    "observation completeness",
    "model/policy readiness",
    "checkpoint readiness",
    "decision match",
    "paper edge",
    "risk control",
    "symbol selection",
    "live-readiness gate",
)


@dataclass(frozen=True)
class ActionItem:
    source: str
    report_id: str
    title: str
    status: str
    owner: str
    next_action: str | None
    current_blockers: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def source_key(self) -> str:
        return _slug(f"{self.source}:{self.report_id}:{self.status}:{self.title}")[:96]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "item"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _mirror_public(name: str, payload: dict[str, Any]) -> None:
    _write_json(WORKLOG_DIR / name, payload)
    _write_json(PUBLIC_DIR / name, payload)


def _load_report_index() -> dict[str, Any]:
    return _read_json(REPORT_INDEX, {})


def _load_context_payloads() -> dict[str, Any]:
    base = REPO_ROOT / "claude_worklog" / "final_readiness"
    return {
        "operator_decision_center": _read_json(
            base
            / "v2_final_operator_decision_and_event_watcher_execution"
            / "latest"
            / "final_operator_decision_center.json",
            {},
        ),
        "external_source": _read_json(
            base
            / "v2_final_operator_decision_and_event_watcher_execution"
            / "latest"
            / "external_source_decision_execution_status.json",
            {},
        ),
        "event_watchers": _read_json(
            base
            / "v2_final_operator_decision_and_event_watcher_execution"
            / "latest"
            / "event_dependent_watcher_runtime_status.json",
            {},
        ),
        "selected_backlog": _read_json(
            base
            / "v2_operator_selected_required_implementation_backlog_execution"
            / "latest"
            / "selected_backlog_execution_status.json",
            {},
        ),
    }


def collect_report_center_actions(report: dict[str, Any]) -> list[ActionItem]:
    rows: list[ActionItem] = []
    seen: set[str] = set()

    def add(source: str, item: dict[str, Any]) -> None:
        report_id = str(item.get("report_id") or item.get("lane_id") or item.get("id") or "")
        title = str(item.get("title") or report_id)
        status = str(item.get("status") or item.get("go_no_go") or "UNKNOWN")
        key = f"{source}:{report_id}:{status}:{title}"
        if not report_id or key in seen:
            return
        seen.add(key)
        blockers = item.get("current_blockers") or []
        if not isinstance(blockers, list):
            blockers = [str(blockers)]
        rows.append(
            ActionItem(
                source=source,
                report_id=report_id,
                title=title,
                status=status,
                owner=str(item.get("owner") or "UNKNOWN"),
                next_action=item.get("next_action"),
                current_blockers=tuple(str(v) for v in blockers),
                raw=item,
            )
        )

    for item in report.get("top_blockers") or []:
        if isinstance(item, dict):
            add("top_blockers", item)
    for item in report.get("next_automatable_actions") or []:
        if isinstance(item, dict):
            add("next_automatable_actions", item)
    for item in report.get("next_operator_decisions") or []:
        if isinstance(item, dict):
            add("next_operator_decisions", item)
    return rows


def _context_blocker_ids(context: dict[str, Any]) -> dict[str, set[str]]:
    operator_ids = {
        str(item.get("blocker_id"))
        for item in (context.get("operator_decision_center", {}).get("decisions") or [])
        if item.get("blocker_id")
    }
    external_ids = {
        str(item.get("blocker_id"))
        for item in (context.get("external_source", {}).get("items") or [])
        if item.get("blocker_id")
    }
    event_ids = {
        str(item.get("blocker_id"))
        for item in (context.get("event_watchers", {}).get("watchers") or [])
        if item.get("blocker_id")
    }
    return {"operator": operator_ids, "external": external_ids, "event": event_ids}


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _protocol_classification(classification: str) -> str:
    if classification in {CLASS_OPERATOR, CLASS_EXTERNAL}:
        return CLASS_OPERATOR_REQUIRED if classification == CLASS_OPERATOR else CLASS_EXTERNAL_REQUIRED
    if classification == CLASS_EVENT or classification == CLASS_POSITION:
        return CLASS_OPERATOR_REQUIRED
    if classification == CLASS_UNSAFE:
        return CLASS_UNSAFE
    return CLASS_AUTOMATABLE


def classify_action(item: ActionItem, context: dict[str, Any]) -> dict[str, Any]:
    blocker_ids = _context_blocker_ids(context)
    rendered = json.dumps(item.raw, sort_keys=True).lower()
    text = " ".join(
        [
            item.report_id.lower(),
            item.title.lower(),
            item.status.lower(),
            str(item.next_action or "").lower(),
            " ".join(v.lower() for v in item.current_blockers),
            rendered,
        ]
    )

    reason = "CURRENT_BLOCKING_WORK_IS_SAFE_TO_AUTOMATE"
    classification = CLASS_AUTOMATABLE

    unsafe_tokens = (
        "enable_live",
        "enable live",
        "live approval",
        "canary approval",
        "shutdown approval",
        "safe_to_shutdown",
        "redis trim",
        "old redis write",
        "exchange mutation",
        "place order",
        "cancel order",
        "modify order",
        "change leverage",
        "margin mode",
        "checkpoint deserialization",
        "deserialize pickle",
        "load pickle",
        "load weights",
        "paid feed activation",
    )
    external_tokens = (
        "external_source",
        "external source",
        "source_missing_key",
        "missing_key",
        "api key",
        "paid tier",
        "paid feed",
        "tokenmetrics",
        "onchain",
        "glassnode",
        "cryptoquant",
        "santiment",
    )
    event_tokens = (
        "event_dependent",
        "event dependent",
        "liquidation",
        "waiting_for_real",
        "paper_edge_not_proven",
        "edge proof",
        "edge_not_claimed",
    )
    position_tokens = (
        "position_dependent",
        "position dependent",
        "open paper position",
        "position history",
        "paper position",
    )
    operator_tokens = (
        "operator_decision_required",
        "operator required",
        "operator decision",
        "operator threshold",
        "checkpoint_promotion",
        "risk_caps",
        "capital_recovery",
        "legacy_shutdown",
        "paper-only shutdown",
    )

    if (
        item.report_id == "full_observation_builder"
        and context.get("external_source", {}).get("external_source_blocker_count", 0) > 0
    ):
        classification = CLASS_EXTERNAL
        reason = "FULL_OBSERVATION_BLOCKED_BY_EXTERNAL_SOURCE_DECISION_AND_EVENT_WATCHERS"
    elif item.status.upper() == "INFO":
        classification = CLASS_UNSAFE
        reason = "INFO_OR_REPORT_ONLY_ROW_NOT_COUNTED_AS_MIGRATION_WORK"
    elif item.report_id in blocker_ids["external"] or _contains_any(text, external_tokens):
        classification = CLASS_EXTERNAL
        reason = "EXTERNAL_SOURCE_OR_KEY_TIER_DECISION_REQUIRED"
    elif item.report_id in blocker_ids["event"] or _contains_any(text, event_tokens):
        classification = CLASS_EVENT
        reason = "REAL_EVENT_OR_EDGE_EVIDENCE_REQUIRED_DO_NOT_FABRICATE"
    elif _contains_any(text, position_tokens):
        classification = CLASS_POSITION
        reason = "POSITION_OR_POSITION_HISTORY_REQUIRED"
    elif item.report_id in blocker_ids["operator"] or _contains_any(text, operator_tokens):
        classification = CLASS_OPERATOR
        reason = "OPERATOR_DECISION_REQUIRED_NO_AUTOMATION"
    elif _contains_any(text, unsafe_tokens):
        classification = CLASS_UNSAFE
        reason = "UNSAFE_OPERATION_REFUSED_BY_POLICY"
    elif item.status.upper() in {"BLOCKED", "FAIL", "FAILED", "STALE", "MISSING_PAYLOAD"}:
        classification = CLASS_AUTOMATABLE
        reason = "CURRENT_BLOCKING_WORK_IS_SAFE_TO_AUTOMATE"

    mission_category = infer_mission_category(item)
    if classification == CLASS_AUTOMATABLE and mission_category is None:
        classification = CLASS_UNSAFE
        reason = "NO_SAFE_MISSION_CATEGORY_FOR_AUTOMATION"

    return {
        "source": item.source,
        "report_id": item.report_id,
        "title": item.title,
        "status": item.status,
        "owner": item.owner,
        "next_action": item.next_action,
        "current_blockers": list(item.current_blockers),
        "classification": classification,
        "classification_protocol": _protocol_classification(classification),
        "classification_reason": reason,
        "mission_category": mission_category,
        "source_key": item.source_key,
        "allowed_classification": classification in ALLOWED_CLASSES,
    }


def infer_mission_category(item: ActionItem) -> str | None:
    text = " ".join(
        [
            item.report_id.lower(),
            item.title.lower(),
            item.status.lower(),
            str(item.next_action or "").lower(),
            " ".join(v.lower() for v in item.current_blockers),
        ]
    )
    if any(t in text for t in ("paper_edge", "paper edge", "edge", "replay", "outcome")):
        return "paper_edge"
    if any(t in text for t in ("full_observation", "observation", "feature", "liquidation")):
        return "observation_completeness"
    if any(t in text for t in ("checkpoint", "model", "policy", "trainer")):
        return "model_policy_readiness"
    if "risk" in text or "capital" in text:
        return "risk_control"
    if any(t in text for t in ("decision", "comparator", "legacy-vs-v2", "v2_vs_legacy")):
        return "decision_match"
    if any(t in text for t in ("symbol", "universe")):
        return "symbol_selection"
    if any(t in text for t in ("live", "canary", "gate")):
        return "live_readiness_gate"
    if any(t in text for t in ("runtime", "worker", "spark", "burndown", "watchdog", "stale")):
        return "runtime_stability"
    return "runtime_stability"


def _task_exists_for_source(store: SQLiteLeaseStore, source_key: str) -> dict[str, Any] | None:
    rows = store._conn.execute(  # noqa: SLF001 - policy tooling needs queue introspection.
        """
        SELECT * FROM tasks
        WHERE json_extract(payload_json, '$.policy_source_key') = ?
          AND status IN ('pending','ready','leased','running','completed')
        ORDER BY CASE WHEN agent='claude' THEN 0 ELSE 1 END, created_at DESC
        LIMIT 1
        """,
        (source_key,),
    ).fetchall()
    if not rows:
        return None
    return store._row_to_dict(rows[0])  # noqa: SLF001


def _write_task_mirror(task: dict[str, Any]) -> None:
    TASK_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    (TASK_MIRROR_DIR / f"{task['task_id']}.json").write_text(
        json.dumps(task, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _descriptor(
    *,
    task_id: str,
    task_type: str,
    mission_category: str,
    lane_group: str,
    owner: str,
    agent: str,
    file_lock_group: str,
    prompt: str,
    policy_source_key: str,
    depends_on_task_id: str | None = None,
    paired_task_id: str | None = None,
    source_classification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "lane_type": task_type,
        "mission_category": mission_category,
        "lane_group": lane_group,
        "owner": owner,
        "agent": agent,
        "status": "pending",
        "file_lock_group": file_lock_group,
        "paired_task_id": paired_task_id,
        "depends_on_task_id": depends_on_task_id,
        "safe_envelope": SAFE_ENVELOPE.copy(),
        "policy_source": LANE_ID,
        "policy_source_key": policy_source_key,
        "source_classification": source_classification,
        "prompt": prompt,
        "scope_paths": [
            "v2/backend/app",
            "claude_worklog/tools",
            "claude_worklog/final_readiness",
        ],
        "report_only_work_forbidden": True,
        "descriptor_only_progress_forbidden": True,
    }


def seed_automatable_tasks(
    classifications: list[dict[str, Any]],
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    generated: list[dict[str, Any]] = []
    referenced: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    try:
        for row in classifications:
            if row["classification"] != CLASS_AUTOMATABLE:
                continue
            source_key = row["source_key"]
            existing = _task_exists_for_source(store, source_key)
            if existing is not None:
                referenced.append(
                    {
                        "source_key": source_key,
                        "implementation_task_id": existing["task_id"],
                        "implementation_task_status": existing["status"],
                        "status": "DUPLICATE_SUPPRESSED_EXISTING_TASK_REFERENCED",
                    }
                )
                continue
            mission_category = str(row["mission_category"] or "runtime_stability")
            lane_group = get_group_for_mission_category(mission_category)
            if lane_group is None:
                blocked.append(
                    {
                        "source_key": source_key,
                        "report_id": row["report_id"],
                        "blocker": "NO_SAFE_SPARK_LANE_FOR_MISSION_CATEGORY",
                    }
                )
                continue
            review_lane = codex_review_lane_for_claude(lane_group)
            if review_lane is None:
                blocked.append(
                    {
                        "source_key": source_key,
                        "report_id": row["report_id"],
                        "blocker": "NO_CODEX_REVIEW_LANE_FOR_CLAUDE_LANE",
                    }
                )
                continue
            stamp = _utc_now().strftime("%Y%m%d%H%M%S")
            base = _slug(f"no_manual_{row['report_id']}_{row['source_key']}_{stamp}")[:110]
            implementation_id = f"{base}_implementation"
            codex_id = f"codex_review_{base}"
            lock_group = f"no_manual_policy_{source_key}"
            prompt = (
                "Implement or remediate the current Report Center blocker "
                f"{row['report_id']} under V2 autonomous no-manual-next-task policy. "
                "This must be real implementation/remediation work, not report-only progress. "
                "Do not stop legacy or V2 runtime. Do not enable live/canary/shutdown/Redis trim. "
                "Do not write old Redis. Do not call exchange mutation. "
                "Keep live_gate=blocked_human_only and live_symbols=[]. "
                f"Source status={row['status']}; blocker details={row['current_blockers']}."
            )
            review_prompt = (
                f"Review implementation task {implementation_id}. Verify it resolves or honestly "
                "classifies the blocker without report-only drift, old Redis writes, exchange mutation, "
                "live/canary/shutdown approvals, or fake readiness. "
                "GO/NO-GO must be PASS or FAIL, and FAIL must map to remediation/operator/unsafe."
            )
            impl_task = _descriptor(
                task_id=implementation_id,
                task_type="CLAUDE_IMPLEMENTATION",
                mission_category=mission_category,
                lane_group=lane_group,
                owner="CLAUDE",
                agent="claude",
                file_lock_group=lock_group,
                prompt=prompt,
                policy_source_key=source_key,
                paired_task_id=codex_id,
                source_classification=row,
            )
            codex_task = _descriptor(
                task_id=codex_id,
                task_type="CODEX_REVIEW",
                mission_category=mission_category,
                lane_group=review_lane,
                owner="CODEX",
                agent="codex",
                file_lock_group=lock_group,
                prompt=review_prompt,
                policy_source_key=source_key,
                depends_on_task_id=implementation_id,
                paired_task_id=implementation_id,
                source_classification=row,
            )
            store.create_task(impl_task, status="pending")
            store.create_task(codex_task, status="pending")
            _write_task_mirror(impl_task)
            _write_task_mirror(codex_task)
            generated.append(
                {
                    "source_key": source_key,
                    "report_id": row["report_id"],
                    "implementation_task_id": implementation_id,
                    "codex_review_task_id": codex_id,
                    "mission_category": mission_category,
                    "lane_group": lane_group,
                    "codex_lane_group": review_lane,
                }
            )
    finally:
        store.close()
    return {
        "generated_pairs": generated,
        "duplicate_suppressed_existing_tasks": referenced,
        "blocked_automatable_seed_items": blocked,
        "generated_pair_count": len(generated),
        "duplicate_suppressed_count": len(referenced),
        "blocked_seed_count": len(blocked),
    }


def apply_existing_fail_mappings(
    classifications: list[dict[str, Any]],
    *,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    store = SQLiteLeaseStore(db_path=db_path)
    try:
        for row in classifications:
            if row["classification"] != CLASS_AUTOMATABLE:
                continue
            mapped = store._conn.execute(  # noqa: SLF001
                """
                SELECT c.classification, c.operator_required, c.unsafe_to_fix,
                       c.remediation_task_id, c.payload_json
                FROM tasks t
                JOIN codex_fail_map c ON c.codex_task_id = t.task_id
                WHERE json_extract(t.payload_json, '$.policy_source_key') = ?
                ORDER BY c.created_at DESC
                LIMIT 1
                """,
                (row["source_key"],),
            ).fetchone()
            if mapped is None:
                continue
            if int(mapped["operator_required"] or 0):
                row["classification"] = CLASS_OPERATOR
                row["classification_reason"] = "PRIOR_CODEX_FAIL_MAPPED_TO_OPERATOR_REQUIRED"
            elif int(mapped["unsafe_to_fix"] or 0):
                row["classification"] = CLASS_UNSAFE
                row["classification_reason"] = "PRIOR_CODEX_FAIL_MAPPED_TO_UNSAFE_TO_AUTOMATE"
        return classifications
    finally:
        store.close()


def _event_counts_last_hour(store: SQLiteLeaseStore) -> dict[str, int]:
    cutoff = (_utc_now() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    rows = store._conn.execute(  # noqa: SLF001
        """
        SELECT e.event_type, t.task_type, COUNT(*) AS c
        FROM events e
        LEFT JOIN tasks t ON t.task_id = e.task_id
        WHERE e.created_at >= ?
        GROUP BY e.event_type, t.task_type
        """,
        (cutoff,),
    ).fetchall()
    completed = 0
    implementation = 0
    codex_reviews = 0
    codex_pass = 0
    codex_fail = 0
    for row in rows:
        count = int(row["c"] or 0)
        if row["event_type"] == "task_completed":
            completed += count
            if row["task_type"] in {"CLAUDE_IMPLEMENTATION", "CLAUDE_REMEDIATION"}:
                implementation += count
            if row["task_type"] == "CODEX_REVIEW":
                codex_reviews += count
                codex_pass += count
        if row["event_type"] == "task_failed" and row["task_type"] == "CODEX_REVIEW":
            codex_fail += count
            codex_reviews += count
    remediations = store._conn.execute(  # noqa: SLF001
        """
        SELECT COUNT(*) FROM tasks
        WHERE task_type='CLAUDE_REMEDIATION' AND created_at >= ?
        """
        ,
        (cutoff,),
    ).fetchone()[0]
    return {
        "tasks_completed_last_hour": completed,
        "implementation_tasks_completed_last_hour": implementation,
        "Codex_reviews_completed_last_hour": codex_reviews,
        "Codex_PASS_count_last_hour": codex_pass,
        "Codex_FAIL_count_last_hour": codex_fail,
        "remediations_created_last_hour": int(remediations or 0),
    }


def worker_execution_status(*, db_path: str | None = None) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    try:
        metrics = store.metrics_snapshot()
        reconcile = store.reconcile()
        counts = _event_counts_last_hour(store)
        fresh_cutoff = (_utc_now() - timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
        active_leases = [
            row
            for row in (store.list_leases(status="active") + store.list_leases(status="running"))
            if str(row.get("heartbeat_at") or "") >= fresh_cutoff
        ]
        eligible_tasks = int(
            store._conn.execute(  # noqa: SLF001
                "SELECT COUNT(*) FROM tasks WHERE status IN ('pending','ready')"
            ).fetchone()[0]
            or 0
        )
        busy_workers = int(
            store._conn.execute(  # noqa: SLF001
                """
                SELECT COUNT(*) FROM workers
                WHERE json_extract(payload_json, '$.state')='busy'
                  AND status='active'
                  AND heartbeat_at >= ?
                """,
                (fresh_cutoff,),
            ).fetchone()[0]
            or 0
        )
        idle_workers = int(
            store._conn.execute(  # noqa: SLF001
                """
                SELECT COUNT(*) FROM workers
                WHERE json_extract(payload_json, '$.state')='idle_ready'
                  AND heartbeat_at >= ?
                """,
                (fresh_cutoff,),
            ).fetchone()[0]
            or 0
        )
        active_lease_count = len(active_leases)
        unmapped_fail_count = store._conn.execute(  # noqa: SLF001
            """
            SELECT COUNT(*) FROM codex_fail_map
            WHERE remediation_task_id IS NULL AND operator_required=0 AND unsafe_to_fix=0
            """
        ).fetchone()[0]
        return {
            "automation_executing": active_lease_count > 0,
            "active_leases": active_lease_count,
            "busy_workers": busy_workers,
            "idle_workers": idle_workers,
            "queued_automatable_tasks": eligible_tasks,
            "active_lease_rows": [
                {
                    "lease_id": row["lease_id"],
                    "task_id": row["task_id"],
                    "worker_id": row["worker_id"],
                    "lane_group": row["lane_group"],
                    "heartbeat_at": row["heartbeat_at"],
                }
                for row in active_leases[:20]
            ],
            "unmapped_codex_fail_count": int(unmapped_fail_count or 0),
            "reconcile": reconcile,
            "metrics": metrics,
            **counts,
        }
    finally:
        store.close()


def _systemd_is_active(unit: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return (proc.stdout or "").strip() or f"exit_{proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        return f"unknown:{type(exc).__name__}"


def protected_worker_status() -> dict[str, Any]:
    units = {
        "report_center": "ai-bot-v2-report-center-indexer.timer",
        "replay_miner": "ai-bot-v2-post-hoc-replay-outcome-miner.timer",
        "spark_worker_pool": "ai-bot-v2-closed-loop-worker-pool.timer",
        "codex_runtime_soak_governor": "ai-bot-codex-runtime-soak-production-equivalence-governor.timer",
        "v2_paper_runtime": "ai-bot-v2-paper-online-runtime.service",
        "event_watchers": "ai-bot-v2-final-operator-decision-event-watcher.timer",
    }
    statuses = {name: _systemd_is_active(unit) for name, unit in units.items()}
    return {
        "protected_units": statuses,
        "protected_unit_count": len(statuses),
        "stopped_or_failed_units": {
            name: status for name, status in statuses.items() if status not in {"active", "activating"}
        },
        "workers_must_not_stop_policy": True,
    }


def build_policy_status(
    *,
    db_path: str | None = None,
    seed_tasks: bool = True,
) -> dict[str, Any]:
    report = _load_report_index()
    context = _load_context_payloads()
    actions = collect_report_center_actions(report)
    classifications = apply_existing_fail_mappings(
        [classify_action(item, context) for item in actions],
        db_path=db_path,
    )
    seed_status = seed_automatable_tasks(classifications, db_path=db_path) if seed_tasks else {
        "generated_pairs": [],
        "duplicate_suppressed_existing_tasks": [],
        "blocked_automatable_seed_items": [],
        "generated_pair_count": 0,
        "duplicate_suppressed_count": 0,
        "blocked_seed_count": 0,
    }
    worker_status = worker_execution_status(db_path=db_path)
    protected_status = protected_worker_status()

    classification_counts = {name: 0 for name in sorted(ALLOWED_CLASSES)}
    for row in classifications:
        classification_counts[row["classification"]] = classification_counts.get(row["classification"], 0) + 1
    protocol_classification_counts = {name: 0 for name in PROTOCOL_CLASSIFICATIONS}
    for row in classifications:
        protocol = row.get("classification_protocol")
        if protocol in protocol_classification_counts:
            protocol_classification_counts[protocol] = protocol_classification_counts.get(protocol, 0) + 1

    automatable_count = classification_counts.get(CLASS_AUTOMATABLE, 0)
    mission_blockers_remain = bool(report.get("top_blockers")) or bool(report.get("blocked_count"))
    exact_empty_queue_reason = None
    if automatable_count == 0 and mission_blockers_remain:
        exact_empty_queue_reason = (
            "ALL_REMAINING_REPORT_CENTER_ACTIONS_ARE_OPERATOR_EVENT_EXTERNAL_POSITION_OR_UNSAFE"
        )

    blockers: list[str] = []
    if not actions:
        blockers.append("NO_REPORT_CENTER_ACTIONS_AVAILABLE")
    if any(not row["allowed_classification"] for row in classifications):
        blockers.append("UNCLASSIFIED_REPORT_CENTER_ACTION")
    if automatable_count > 0:
        seeded_or_existing = seed_status["generated_pair_count"] + seed_status["duplicate_suppressed_count"]
        if seeded_or_existing < automatable_count:
            blockers.append("AUTOMATABLE_ACTION_WITHOUT_TASK_PAIR")
        if (
            worker_status["active_leases"] == 0
            and worker_status["queued_automatable_tasks"] > 0
            and worker_status["idle_workers"] > 0
            and worker_status["implementation_tasks_completed_last_hour"] == 0
        ):
            blockers.append("ELIGIBLE_AUTOMATABLE_WORK_NOT_LEASED_BY_IDLE_WORKERS")
    elif mission_blockers_remain and not exact_empty_queue_reason:
        blockers.append("EMPTY_QUEUE_WITH_MISSION_BLOCKERS_AND_NO_EXACT_REASON")
    if worker_status["unmapped_codex_fail_count"] > 0:
        blockers.append("UNMAPPED_CODEX_FAIL_PRESENT")
    if seed_status["blocked_seed_count"] > 0:
        blockers.append("AUTOMATABLE_SEED_BLOCKED")
    if protected_status["stopped_or_failed_units"]:
        blockers.append("PROTECTED_AUTOMATION_UNIT_NOT_ACTIVE")

    go_no_go = GO_READY if not blockers else GO_BLOCKED
    next_auto = next((row for row in classifications if row["classification"] == CLASS_AUTOMATABLE), None)
    next_operator = next(
        (
            row
            for row in classifications
            if row["classification"] in {CLASS_OPERATOR, CLASS_EXTERNAL, CLASS_EVENT, CLASS_POSITION}
        ),
        None,
    )
    status = {
        "schema_version": "v2_autonomous_no_manual_next_task_policy_v1",
        "generated_utc": _utc_iso(),
        "lane_id": LANE_ID,
        "go_no_go": go_no_go,
        "ready": go_no_go == GO_READY,
        "blockers": blockers,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "creates_approval_tokens": False,
        "writes_old_redis": False,
        "calls_exchange_mutation": False,
        "checkpoint_deserialization_requires_operator_approval": True,
        "paid_feed_activation_requires_operator_approval": True,
        "report_center_generated_at": report.get("generated_at"),
        "report_center_action_count": len(actions),
        "classification_counts": classification_counts,
        "protocol_classification_counts": protocol_classification_counts,
        "automatable_now_count": automatable_count,
        "remaining_operator_decisions": classification_counts.get(CLASS_OPERATOR, 0) + classification_counts.get(CLASS_EVENT, 0) + classification_counts.get(CLASS_POSITION, 0),
        "remaining_external_source_required": classification_counts.get(CLASS_EXTERNAL, 0),
        "remaining_event_dependent": classification_counts.get(CLASS_EVENT, 0),
        "remaining_position_dependent": classification_counts.get(CLASS_POSITION, 0),
        "unsafe_to_automate_count": classification_counts.get(CLASS_UNSAFE, 0),
        "queue_empty_with_blockers_reason": exact_empty_queue_reason,
        "next_automatic_action": next_auto,
        "next_operator_only_action": next_operator,
        "seed_status": seed_status,
        "worker_execution_status": worker_status,
        "protected_worker_status": protected_status,
        "mission_categories_supported": list(MISSION_CATEGORIES),
        "report_only_progress_counted": False,
        "descriptor_only_progress_counted": False,
        "worker_heartbeat_counted_as_progress": False,
    }
    return status | {
        "classification_rows": classifications,
    }


def write_outputs(status_with_rows: dict[str, Any]) -> None:
    rows = status_with_rows.pop("classification_rows")
    seed_status = status_with_rows["seed_status"]
    worker_status = status_with_rows["worker_execution_status"]
    operator_status = {
        "remaining_operator_decisions": status_with_rows["remaining_operator_decisions"],
        "next_operator_only_action": status_with_rows["next_operator_only_action"],
        "protocol_classification_counts": status_with_rows.get("protocol_classification_counts", {}),
        "operator_decisions_not_auto_accepted": True,
        "approval_artifact_created": False,
    }
    report = build_report(status_with_rows, rows)
    worklog_payloads = {
        "GO_NO_GO.md": status_with_rows["go_no_go"] + "\n",
        "V2_AUTONOMOUS_NO_MANUAL_NEXT_TASK_POLICY_REPORT.md": report,
    }
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in worklog_payloads.items():
        (WORKLOG_DIR / name).write_text(text, encoding="utf-8")
        (PUBLIC_DIR / name).write_text(text, encoding="utf-8")
    _mirror_public("autonomous_no_manual_next_task_policy_status.json", status_with_rows)
    _mirror_public(
        "report_center_next_action_classification.json",
        {
            "schema_version": "v2_report_center_next_action_classification_v1",
            "generated_utc": status_with_rows["generated_utc"],
            "classification_count": len(rows),
            "classification_counts": status_with_rows["classification_counts"],
            "protocol_classification_counts": status_with_rows.get(
                "protocol_classification_counts",
                {},
            ),
            "rows": rows,
        },
    )
    _mirror_public("automatic_task_seed_status.json", seed_status)
    _mirror_public("worker_execution_policy_status.json", worker_status)
    _mirror_public("operator_only_action_status.json", operator_status)
    _mirror_public(
        "operator_dashboard_payload.json",
        {
            "schema_version": "v2_autonomous_no_manual_next_task_policy_operator_dashboard_v1",
            "generated_utc": status_with_rows["generated_utc"],
            "lane_id": LANE_ID,
            "go_no_go": status_with_rows["go_no_go"],
            "ready": status_with_rows["ready"],
            "blockers": status_with_rows["blockers"],
            "automation_executing": worker_status["automation_executing"],
            "active_leases": worker_status["active_leases"],
            "busy_workers": worker_status["busy_workers"],
            "queued_automatable_tasks": worker_status["queued_automatable_tasks"],
            "completed_implementation_tasks_last_hour": worker_status[
                "implementation_tasks_completed_last_hour"
            ],
            "Codex_reviews_last_hour": worker_status["Codex_reviews_completed_last_hour"],
            "blockers_burned_down": 0,
            "remaining_operator_decisions": status_with_rows["remaining_operator_decisions"],
            "remaining_operator_required_count": status_with_rows.get(
                "protocol_classification_counts",
                {},
            ).get(CLASS_OPERATOR_REQUIRED, 0),
            "remaining_external_required_count": status_with_rows.get(
                "protocol_classification_counts",
                {},
            ).get(CLASS_EXTERNAL_REQUIRED, 0),
            "remaining_unsafe_to_automate_count": status_with_rows.get(
                "protocol_classification_counts",
                {},
            ).get(CLASS_UNSAFE, 0),
            "next_automatic_action": status_with_rows["next_automatic_action"],
            "next_operator_only_action": status_with_rows["next_operator_only_action"],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "shutdown_safe": False,
            "live_ready": False,
            "canary_ready": False,
        },
    )


def build_report(status: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = status["classification_counts"]
    return "\n".join(
        [
            "# V2 Autonomous No-Manual Next-Task Policy",
            "",
            f"Generated: {status['generated_utc']}",
            f"Lane: `{LANE_ID}`",
            f"GO/NO-GO: `{status['go_no_go']}`",
            "",
            "This policy prevents the operator from having to name the next safe technical task.",
            "It classifies Report Center action rows, seeds paired Claude/Codex Spark tasks for",
            "safe automatable work, and keeps true operator/event/external/position blockers visible.",
            "",
            "## Classification",
            "",
            *(f"- `{key}`: {value}" for key, value in counts.items()),
            "",
            "## Execution State",
            "",
            f"- automation executing: `{status['worker_execution_status']['automation_executing']}`",
            f"- active leases: `{status['worker_execution_status']['active_leases']}`",
            f"- busy workers: `{status['worker_execution_status']['busy_workers']}`",
            f"- queued automatable tasks: `{status['worker_execution_status']['queued_automatable_tasks']}`",
            f"- implementation tasks completed last hour: `{status['worker_execution_status']['implementation_tasks_completed_last_hour']}`",
            f"- Codex reviews completed last hour: `{status['worker_execution_status']['Codex_reviews_completed_last_hour']}`",
            f"- unmapped Codex FAIL count: `{status['worker_execution_status']['unmapped_codex_fail_count']}`",
            "",
            "## Next Actions",
            "",
            f"- next automatic action: `{_format_action(status['next_automatic_action'])}`",
            f"- next operator-only action: `{_format_action(status['next_operator_only_action'])}`",
            f"- empty queue reason: `{status['queue_empty_with_blockers_reason']}`",
            "",
            "## Safety",
            "",
            "- `live_gate=blocked_human_only`",
            "- `live_symbols=[]`",
            "- No live/canary/shutdown/Redis-trim approval is created.",
            "- Old Redis writes and exchange mutation are refused.",
            "- Checkpoint deserialization and paid feed activation require operator approval.",
            "",
            "## Sample Classifications",
            "",
            *(
                f"- `{row['report_id']}` -> `{row['classification']}` ({row['classification_reason']})"
                for row in rows[:20]
            ),
            "",
        ]
    )


def _format_action(action: dict[str, Any] | None) -> str:
    if not action:
        return "none"
    return f"{action.get('report_id')}:{action.get('classification')}"


def run_once(*, db_path: str | None = None, seed_tasks: bool = True) -> dict[str, Any]:
    status = build_policy_status(db_path=db_path, seed_tasks=seed_tasks)
    write_outputs(dict(status))
    return {k: v for k, v in status.items() if k != "classification_rows"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-seed", action="store_true")
    args = parser.parse_args(argv)
    result = run_once(db_path=args.db_path, seed_tasks=not args.no_seed)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["go_no_go"] == GO_READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
