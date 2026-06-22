"""V2 Autonomous Full-Rebuild Self-Healing — Issue Classifier.

Read-only scanner that walks the V2 rebuild surface and emits a typed
list of issues. Each issue is mapped to exactly one root-cause category
so the self-healing controller can decide whether to dispatch a Claude
fix task, a Codex review task, or surface it as an operator decision.

The classifier never writes Redis keys, never calls the exchange,
never touches the legacy bot, and never starts any approval action.
It writes only JSON artifacts under
``claude_worklog/final_readiness/v2_autonomous_full_rebuild_self_healing/latest/``
and ``v2/frontend/public/v2_autonomous_full_rebuild_self_healing/latest/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"

CATEGORIES: tuple[str, ...] = (
    "RUNTIME_PROCESS_DOWN",
    "PAYLOAD_STALE",
    "REDIS_NAMESPACE_EMPTY",
    "FRONTEND_TRUTH_MISMATCH",
    "CODEX_REVIEW_FAIL",
    "CLAUDE_TASK_STALLED",
    "CODEX_TASK_STALLED",
    "EXACT_SOURCE_IMPLEMENTATION_GAP",
    "MISSING_RUNTIME_PAYLOAD_FIELD",
    "SCHEMA_MISMATCH",
    "TEST_FAILURE",
    "SECRET_LEAK_RISK",
    "OLD_REDIS_WRITE_RISK",
    "EXCHANGE_MUTATION_RISK",
    "LIVE_GATE_DRIFT",
    "SYMBOL_UNIVERSE_MUTATION_RISK",
    "CHECKPOINT_ARTIFACT_REQUIRED",
    "POLICY_ARCHITECTURE_GATE_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED",
    "OPERATOR_DECISION_REQUIRED",
    "EVENT_DEPENDENT",
    "POSITION_DEPENDENT",
    "NO_AUTOMATABLE_WORK_REMAINING",
)

OPERATOR_OWNED = {
    "OPERATOR_DECISION_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED",
    "CHECKPOINT_ARTIFACT_REQUIRED",
    "POLICY_ARCHITECTURE_GATE_REQUIRED",
    "EVENT_DEPENDENT",
    "POSITION_DEPENDENT",
    "SYMBOL_UNIVERSE_MUTATION_RISK",
    "LIVE_GATE_DRIFT",
    "SECRET_LEAK_RISK",
    "OLD_REDIS_WRITE_RISK",
    "EXCHANGE_MUTATION_RISK",
}

REQUIRED_V2_HEARTBEAT_KEYS = (
    "v2:trainer:heartbeat",
    "v2:paper:position_history:heartbeat",
    "v2:market:liquidations:heartbeat",
)

STALE_PAYLOAD_AGE_SECONDS_DEFAULT = 15 * 60


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _duplicate_key(*parts: Any) -> str:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:16]


def _safe_redis_probe() -> dict[str, Any]:
    out: dict[str, Any] = {
        "reachable": False,
        "v2_namespaces_non_empty": False,
        "heartbeats_present": {},
        "live_gate": None,
        "live_symbols": None,
    }
    try:
        import redis  # type: ignore
        r = redis.Redis(decode_responses=True, socket_connect_timeout=2)
        r.ping()
        out["reachable"] = True
        cur = 0
        non_empty = False
        for _ in range(64):
            cur, batch = r.scan(cursor=cur, match="v2:*", count=500)
            if batch:
                non_empty = True
                break
            if cur == 0:
                break
        out["v2_namespaces_non_empty"] = non_empty
        for k in REQUIRED_V2_HEARTBEAT_KEYS:
            out["heartbeats_present"][k] = bool(r.exists(k))
        out["live_gate"] = r.get("v2:live:gate")
        out["live_symbols"] = r.get("v2:live:symbols")
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _payload_age_seconds(path: Path) -> float | None:
    try:
        mtime = path.stat().st_mtime
        return max(0.0, time.time() - mtime)
    except Exception:  # noqa: BLE001
        return None


def _scan_pending_tasks() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (pending_claude, pending_codex_review) task descriptors."""
    pending_claude: list[dict[str, Any]] = []
    pending_codex: list[dict[str, Any]] = []
    if not TASKS_DIR.exists():
        return pending_claude, pending_codex
    for f in sorted(TASKS_DIR.iterdir()):
        if not f.name.endswith(".json"):
            continue
        d = _read_json(f)
        if not isinstance(d, dict):
            continue
        status = d.get("status")
        if status not in ("pending", "in_progress"):
            continue
        if "claude_fix_" in f.name:
            pending_claude.append({"path": str(f), "task_id": d.get("task_id"), "age_seconds": _payload_age_seconds(f)})
        elif "codex_review_" in f.name or "codex_review" in d.get("agent", ""):
            pending_codex.append({"path": str(f), "task_id": d.get("task_id"), "age_seconds": _payload_age_seconds(f)})
    return pending_claude, pending_codex


def _check_runtime_processes() -> dict[str, Any]:
    """pgrep-based discovery of expected long-running V2 processes.

    Keep this list to real daemons/loops. One-shot timer jobs such as
    Codex review governors and autonomous burndown controllers are
    freshness-checked through their payloads elsewhere; requiring a
    persistent process for those creates false RUNTIME_PROCESS_DOWN
    tasks.
    """
    expected = {
        "v2_production_replacement_runtime_guard": (
            "v2_production_replacement_runtime_guard"
        ),
        "continuous_legacy_log_remediation": (
            "v2_continuous_legacy_log_to_rebuild_remediation"
        ),
        "legacy_log_observer": "v2_legacy_log_intelligence_observer",
        "v2_legacy_v2_production_comparator": "v2_legacy_v2_production_comparator",
        "production_equivalence_comparator": "v2_production_equivalence_comparator",
        "liquidation_wss_daemon": "v2_liquidation_wss_loop",
        "position_history_tracker": "v2_position_history_persistent_tracker",
    }
    out: dict[str, Any] = {}
    for name, pattern in expected.items():
        try:
            res = subprocess.run(
                ["pgrep", "-af", pattern],
                capture_output=True, text=True, timeout=5,
            )
            running = bool(res.stdout.strip())
        except Exception:  # noqa: BLE001
            running = False
        out[name] = {"pattern": pattern, "running": running}
    return out


def _check_remaining_dim_queue() -> dict[str, Any]:
    queue_path = (
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_full_observation_remaining_dim_execution_queue"
        / "latest"
        / "remaining_dim_execution_queue.json"
    )
    doc = _read_json(queue_path) or {}
    next_10_path = queue_path.with_name("next_10_feature_tasks.json")
    next_doc = _read_json(next_10_path) or {}
    return {
        "queue_path": str(queue_path),
        "queue_go_no_go": doc.get("go_no_go"),
        "aggregate_category_counts": doc.get("aggregate_category_counts", {}),
        "aggregate_total_observed": doc.get("aggregate_total_observed"),
        "aggregate_total_check": doc.get("aggregate_total_check"),
        "strict_source_contract_pass": doc.get("strict_source_contract_pass"),
        "generic_source_hint_hits": doc.get("generic_source_hint_hits"),
        "next_10_count": len(next_doc.get("tasks") or []),
    }


def _active_codex_failure_marker(marker: str) -> bool:
    marker = marker.strip().strip("`").strip()
    if not marker:
        return False
    if marker.endswith("_CODEX_FAIL"):
        return True
    # Codex-owned governors use BLOCKED rather than CODEX_FAIL. Treat
    # those as current review failures only when the active GO/NO-GO
    # marker itself is blocked; do not infer failure from historical
    # prose such as "addresses_codex_fail".
    return marker.startswith("CODEX_") and marker.endswith("_BLOCKED")


def _extract_markdown_go_no_go(text: str) -> str | None:
    for raw in text.splitlines()[:80]:
        line = raw.strip()
        if not line.startswith("GO/NO-GO:"):
            continue
        value = line.split(":", 1)[1].strip()
        return value.strip("`").strip()
    return None


def _check_codex_recent_fails() -> list[dict[str, Any]]:
    """Find active Codex failure markers under final_readiness.

    Earlier versions used a broad ``grep _CODEX_FAIL`` over every latest
    packet. That made the self-healing controller chase stale remediation
    reports that merely referenced old fail markers, for example
    ``addresses_codex_fail`` fields on already-ready implementation
    packets. This scanner only accepts active GO/NO-GO fields/markers.
    """
    report_center_failures = (
        REPO_ROOT
        / "v2"
        / "frontend"
        / "public"
        / "v2_report_center"
        / "latest"
        / "latest_codex_failures.json"
    )
    report_center_doc = _read_json(report_center_failures)
    if isinstance(report_center_doc, dict):
        active_failures = (
            report_center_doc.get("codex_failures")
            or report_center_doc.get("failures")
            or report_center_doc.get("entries")
            or []
        )
        # The report center is the reviewed current-truth index for active
        # lanes. If it is present, trust it over historical worklog packets.
        # A zero-count payload means no current active Codex failures.
        out: list[dict[str, Any]] = []
        for entry in active_failures:
            if not isinstance(entry, dict):
                continue
            marker = str(
                entry.get("go_no_go")
                or entry.get("go_no_go_marker")
                or entry.get("marker")
                or ""
            )
            if marker and not _active_codex_failure_marker(marker):
                continue
            source = (
                entry.get("source_path")
                or entry.get("public_payload_path")
                or entry.get("path")
                or entry.get("report_id")
                or str(report_center_failures)
            )
            out.append({
                "path": str(source),
                "age_seconds": _payload_age_seconds(report_center_failures),
                "go_no_go": marker or "CODEX_FAIL_FROM_REPORT_CENTER",
            })
        return out

    fails: list[dict[str, Any]] = []
    final = REPO_ROOT / "claude_worklog" / "final_readiness"
    if not final.exists():
        return fails
    seen: set[Path] = set()
    for p in sorted(final.rglob("*")):
        if not p.is_file() or "/latest/" not in str(p):
            continue
        marker: str | None = None
        try:
            if p.name == "CODEX_GO_NO_GO.md":
                marker = p.read_text(encoding="utf-8", errors="replace").strip()
            elif p.name in {"CODEX_REVIEW.md", "CODEX_STATUS.md", "CODEX_5M_STATUS.md"}:
                sibling_marker = p.with_name("CODEX_GO_NO_GO.md")
                if sibling_marker.exists():
                    # The marker file is authoritative for this review dir.
                    continue
                marker = _extract_markdown_go_no_go(
                    p.read_text(encoding="utf-8", errors="replace")
                )
            elif p.suffix == ".json":
                doc = _read_json(p)
                if isinstance(doc, dict):
                    raw = doc.get("go_no_go") or doc.get("go_no_go_marker")
                    marker = str(raw) if raw is not None else None
        except Exception:  # noqa: BLE001
            marker = None
        if marker is None or not _active_codex_failure_marker(marker):
            continue
        if p in seen:
            continue
        seen.add(p)
        fails.append({
            "path": str(p),
            "age_seconds": _payload_age_seconds(p),
            "go_no_go": marker.strip().strip("`").strip(),
        })
    return fails


def classify_issues(
    *,
    stale_payload_age_seconds: int = STALE_PAYLOAD_AGE_SECONDS_DEFAULT,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    now = _utc_iso()

    redis_state = _safe_redis_probe()
    if not redis_state.get("reachable"):
        issues.append({
            "category": "RUNTIME_PROCESS_DOWN",
            "severity": "P0",
            "source": "redis",
            "detected_at": now,
            "exact_evidence": redis_state,
            "exact_remediation_action": "verify Redis service running and reachable",
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("redis_unreachable"),
        })

    if redis_state.get("reachable") and not redis_state.get("v2_namespaces_non_empty"):
        issues.append({
            "category": "REDIS_NAMESPACE_EMPTY",
            "severity": "P0",
            "source": "redis:v2:*",
            "detected_at": now,
            "exact_evidence": redis_state,
            "exact_remediation_action": "investigate why no v2:* keys exist; start V2 publishers",
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("v2_namespace_empty"),
        })

    for k, present in (redis_state.get("heartbeats_present") or {}).items():
        if not present:
            issues.append({
                "category": "PAYLOAD_STALE",
                "severity": "P1",
                "source": k,
                "detected_at": now,
                "exact_evidence": {"redis_key_present": present},
                "exact_remediation_action": f"start/refresh publisher for {k}",
                "owner": "CLAUDE",
                "duplicate_key": _duplicate_key("heartbeat_missing", k),
            })

    live_gate = redis_state.get("live_gate")
    if live_gate not in (None, "blocked_human_only"):
        issues.append({
            "category": "LIVE_GATE_DRIFT",
            "severity": "P0",
            "source": "v2:live:gate",
            "detected_at": now,
            "exact_evidence": {"live_gate": live_gate},
            "exact_remediation_action": "investigate; live_gate must be blocked_human_only or unset",
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("live_gate_drift", live_gate),
        })

    live_symbols = redis_state.get("live_symbols")
    if isinstance(live_symbols, str) and live_symbols.strip() not in ("", "[]"):
        issues.append({
            "category": "LIVE_GATE_DRIFT",
            "severity": "P0",
            "source": "v2:live:symbols",
            "detected_at": now,
            "exact_evidence": {"live_symbols": live_symbols},
            "exact_remediation_action": "investigate; live_symbols must be [] or unset",
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("live_symbols_drift", live_symbols),
        })

    procs = _check_runtime_processes()
    monitor_only = {"legacy_log_observer", "v2_legacy_v2_production_comparator"}
    for name, info in procs.items():
        if info.get("running"):
            continue
        # autonomous_burndown_controller may be intentionally idle when
        # the queue is exhausted, so it's a P2 informational issue rather
        # than a hard runtime down event.
        severity = (
            "P2" if name == "autonomous_burndown_controller" else "P1"
        )
        owner = "OPERATOR" if name in monitor_only else "CLAUDE"
        issues.append({
            "category": "RUNTIME_PROCESS_DOWN",
            "severity": severity,
            "source": name,
            "detected_at": now,
            "exact_evidence": info,
            "exact_remediation_action": (
                "investigate or restart per its start script; do not stop legacy"
            ),
            "owner": owner,
            "duplicate_key": _duplicate_key("process_down", name),
        })

    pending_claude, pending_codex = _scan_pending_tasks()
    stale_threshold = stale_payload_age_seconds
    for t in pending_claude:
        if (t.get("age_seconds") or 0) > stale_threshold:
            issues.append({
                "category": "CLAUDE_TASK_STALLED",
                "severity": "P1",
                "source": t["path"],
                "detected_at": now,
                "exact_evidence": t,
                "exact_remediation_action": "watchdog will re-dispatch or escalate",
                "owner": "CLAUDE",
                "duplicate_key": _duplicate_key("claude_stall", t["path"]),
                "task_descriptor": t["path"],
            })
    for t in pending_codex:
        if (t.get("age_seconds") or 0) > stale_threshold:
            issues.append({
                "category": "CODEX_TASK_STALLED",
                "severity": "P1",
                "source": t["path"],
                "detected_at": now,
                "exact_evidence": t,
                "exact_remediation_action": "watchdog will re-dispatch or escalate",
                "owner": "CODEX",
                "duplicate_key": _duplicate_key("codex_stall", t["path"]),
                "codex_review_descriptor": t["path"],
            })

    codex_fails = _check_codex_recent_fails()
    for f in codex_fails:
        issues.append({
            "category": "CODEX_REVIEW_FAIL",
            "severity": "P1",
            "source": f["path"],
            "detected_at": now,
            "exact_evidence": f,
            "exact_remediation_action": (
                "parse fail-blocker text and create focused remediation task"
            ),
            "owner": "CLAUDE",
            "duplicate_key": _duplicate_key("codex_fail", f["path"]),
        })

    queue_info = _check_remaining_dim_queue()
    if queue_info.get("queue_go_no_go") not in (
        "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY",
        None,
    ):
        issues.append({
            "category": "EXACT_SOURCE_IMPLEMENTATION_GAP",
            "severity": "P1",
            "source": queue_info["queue_path"],
            "detected_at": now,
            "exact_evidence": queue_info,
            "exact_remediation_action": (
                "remediate remaining-dim queue (run classifier, satisfy strict source contract)"
            ),
            "owner": "CLAUDE",
            "duplicate_key": _duplicate_key("queue_not_remediated"),
        })
    elif queue_info.get("next_10_count") == 0 and not pending_claude and not pending_codex:
        # No buildable, no in-flight — automatable work is exhausted.
        issues.append({
            "category": "NO_AUTOMATABLE_WORK_REMAINING",
            "severity": "INFO",
            "source": queue_info["queue_path"],
            "detected_at": now,
            "exact_evidence": queue_info,
            "exact_remediation_action": (
                "await operator-approved next gate (policy architecture, checkpoint artifact, paid alt-data, external sources, event-dependent, position-dependent)"
            ),
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("no_automatable_work"),
        })

    # Categorize remaining queue dims by operator/external/event/position blockers.
    cat_counts = queue_info.get("aggregate_category_counts") or {}
    for cat, count in cat_counts.items():
        if count <= 0:
            continue
        if cat == "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS":
            iss_cat = "EXTERNAL_SOURCE_REQUIRED"
            severity = "P2"
        elif cat in ("EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC", "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH"):
            iss_cat = "EXTERNAL_SOURCE_REQUIRED"
            severity = "P2"
        elif cat == "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV":
            iss_cat = "OPERATOR_DECISION_REQUIRED"
            severity = "P2"
        elif cat == "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR":
            iss_cat = "OPERATOR_DECISION_REQUIRED"
            severity = "P2"
        elif cat == "V2_EVENT_DEPENDENT_LIQUIDATION_WSS":
            iss_cat = "EVENT_DEPENDENT"
            severity = "P2"
        elif cat == "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED":
            iss_cat = "POSITION_DEPENDENT"
            severity = "P2"
        elif cat == "POLICY_ARCHITECTURE_BLOCKED":
            iss_cat = "POLICY_ARCHITECTURE_GATE_REQUIRED"
            severity = "P2"
        elif cat == "CHECKPOINT_ARTIFACT_BLOCKED":
            iss_cat = "CHECKPOINT_ARTIFACT_REQUIRED"
            severity = "P2"
        else:
            continue
        issues.append({
            "category": iss_cat,
            "severity": severity,
            "source": f"remaining_dim_queue:{cat}",
            "detected_at": now,
            "exact_evidence": {"category": cat, "dim_count": count},
            "exact_remediation_action": "operator-approved gate or external feed required",
            "owner": "OPERATOR",
            "duplicate_key": _duplicate_key("blocker_category", cat),
        })

    summary_by_category: dict[str, int] = {}
    for it in issues:
        summary_by_category[it["category"]] = summary_by_category.get(it["category"], 0) + 1

    automatable_owners = sum(1 for it in issues if it["owner"] in ("CLAUDE", "CODEX"))
    operator_owners = sum(1 for it in issues if it["owner"] == "OPERATOR")

    return {
        "schema_version": "v2_autonomous_full_rebuild_self_healing_issues_v1",
        "generated_utc": now,
        "redis_state": redis_state,
        "runtime_processes": procs,
        "pending_claude_tasks": pending_claude,
        "pending_codex_tasks": pending_codex,
        "remaining_dim_queue": queue_info,
        "summary_by_category": summary_by_category,
        "automatable_issue_count": automatable_owners,
        "operator_owned_issue_count": operator_owners,
        "issues": issues,
    }


def write_artifacts(state: dict[str, Any]) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WORKLOG_DIR / "latest_issues.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "latest_issues.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stale-seconds", type=int, default=STALE_PAYLOAD_AGE_SECONDS_DEFAULT)
    p.add_argument("--json", action="store_true", help="print JSON only")
    args = p.parse_args()
    state = classify_issues(stale_payload_age_seconds=args.stale_seconds)
    write_artifacts(state)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state["generated_utc"],
            "summary_by_category": state["summary_by_category"],
            "automatable_issue_count": state["automatable_issue_count"],
            "operator_owned_issue_count": state["operator_owned_issue_count"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
