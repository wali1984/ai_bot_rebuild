"""V2 Autonomous Production-Equivalence Burndown Controller.

Selects the next exact-source V2_BUILDABLE_NOW field group from the
remediated remaining-dim execution queue and emits a paired
Claude / Codex task descriptor under
``claude_worklog/agent_supervisor/tasks/`` so the supervisor can run
the next implementation step without operator hand-feeding.

This controller is **safe by construction**:

- read-only with respect to legacy code (/home/wali/Desktop/AI BOT).
- never starts policy architecture, checkpoint compatibility, live, canary,
  shutdown acceptance, paid alt-data, or Redis migration / trimming.
- never writes old Redis keys, never calls the exchange.
- only writes inside this repository under
  ``claude_worklog/`` and ``v2/frontend/public/``.

Modes:

  --once     : one selection cycle (default).
  --loop     : keep selecting until the queue is exhausted, a Codex FAIL
               requires operator handling, runtime preflight fails, or the
               next item is a hard-gated category.
  --status   : print current controller status JSON.
  --dry-run  : log what would be selected without writing any task file.

The controller refuses to mark a task buildable if:

- the queue file is not the remediated one
  (`go_no_go != V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`).
- the task carries any generic source hint or empty source list.
- the task category is anything other than ``V2_BUILDABLE_NOW``.
- the task field group is the broad ``portfolio_state`` parent bucket.
- a duplicate `claude_fix_v2_full_observation_<group>` task already
  exists with status ``pending`` or ``in_progress``.
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
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
QUEUE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_full_observation_remaining_dim_execution_queue"
    / "latest"
)
NEXT_10_PATH = QUEUE_DIR / "next_10_feature_tasks.json"
QUEUE_PATH = QUEUE_DIR / "remaining_dim_execution_queue.json"
QUEUE_CODEX_GO_NO_GO_PATH = QUEUE_DIR / "codex_review" / "CODEX_GO_NO_GO.md"
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_production_equivalence_burndown"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_production_equivalence_burndown"
    / "latest"
)

REQUIRED_QUEUE_GO = (
    "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY"
)
REQUIRED_QUEUE_CODEX_GO = (
    "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_CODEX_PASS"
)

# Categories that the controller refuses to drive autonomously. Any task in
# one of these categories must be handled by the operator.
HARD_GATED_CATEGORIES: tuple[str, ...] = (
    "POLICY_ARCHITECTURE_BLOCKED",
    "CHECKPOINT_ARTIFACT_BLOCKED",
    "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH",
    "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV",
    "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR",
    "V2_EVENT_DEPENDENT_LIQUIDATION_WSS",
    "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "LEGACY_V3_EXTRA_NO_V2_SOURCE",
    "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH",
)

GENERIC_SOURCE_PATTERNS: tuple[str, ...] = (
    "review builder code for exact source",
    "v2:*",
)

FORBIDDEN_ACTIONS = [
    "modify /home/wali/Desktop/AI BOT",
    "place or cancel or modify exchange orders",
    "change leverage or margin",
    "enable live trading",
    "create live/canary/shutdown/Redis-trim approval tokens",
    "create paper-only shutdown acceptance file",
    "expose raw API keys",
    "deserialize checkpoint blobs",
    "write old (legacy) Redis keys",
    "claim checkpoint compatibility",
    "claim policy architecture parity",
    "zero-fill unknown values",
    "stop V2 runtime, remediation governor, legacy log observer,"
    " V2-vs-legacy comparator, or liquidation WSS daemon",
]

REQUIRED_V2_HEARTBEAT_KEYS = (
    "v2:trainer:heartbeat",
    "v2:paper:position_history:heartbeat",
    "v2:market:liquidations:heartbeat",
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _slugify(group: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", group.lower()).strip("_")


def _marker_stem_for_slug(slug: str) -> str:
    stem = slug.upper()
    if stem.startswith("PORTFOLIO_STATE_PORTFOLIO_"):
        stem = "PORTFOLIO_STATE_" + stem[len("PORTFOLIO_STATE_PORTFOLIO_"):]
    return f"V2_FULL_OBSERVATION_{stem}"


def _safe_redis_check() -> dict[str, Any]:
    """Read-only Redis liveness probe. Returns dict; never raises."""
    out: dict[str, Any] = {
        "redis_reachable": False,
        "v2_namespaces_non_empty": False,
        "heartbeats_present": {},
        "live_gate": None,
        "live_symbols": None,
    }
    try:
        import redis  # type: ignore
    except Exception as exc:  # noqa: BLE001
        out["redis_import_error"] = str(exc)
        return out
    try:
        r = redis.Redis(decode_responses=True, socket_connect_timeout=2)
        r.ping()
        out["redis_reachable"] = True
        # SCAN may return an empty batch on the first cursor — iterate
        # until we either find a v2:* key or exhaust the cursor.
        non_empty = False
        cur = 0
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
        # live gate / live symbols intentionally read; absence is OK (config)
        out["live_gate"] = r.get("v2:live:gate")
        out["live_symbols"] = r.get("v2:live:symbols")
    except Exception as exc:  # noqa: BLE001
        out["redis_error"] = str(exc)
    return out


def runtime_preflight() -> dict[str, Any]:
    """Phase 0 — runtime preservation preflight. Read-only."""
    result: dict[str, Any] = {
        "ok": False,
        "timestamp_utc": _utc_iso(),
        "checks": {},
    }
    redis_state = _safe_redis_check()
    result["checks"]["redis"] = redis_state

    hb_ok = redis_state.get("redis_reachable") and all(
        redis_state.get("heartbeats_present", {}).values()
    )
    result["checks"]["heartbeats_ok"] = bool(hb_ok)

    # live_gate / live_symbols safety. We allow absence (config-only).
    live_gate = redis_state.get("live_gate")
    live_symbols = redis_state.get("live_symbols")
    live_safe = True
    if live_gate not in (None, "blocked_human_only"):
        live_safe = False
    if live_symbols is not None and live_symbols.strip() not in ("", "[]"):
        live_safe = False
    result["checks"]["live_safe"] = live_safe

    queue_ok = QUEUE_PATH.exists() and NEXT_10_PATH.exists()
    result["checks"]["queue_artifacts_present"] = queue_ok

    queue_go = None
    queue_codex_go = None
    if queue_ok:
        try:
            queue_doc = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
            queue_go = queue_doc.get("go_no_go")
        except Exception as exc:  # noqa: BLE001
            result["checks"]["queue_read_error"] = str(exc)
    try:
        queue_codex_go = QUEUE_CODEX_GO_NO_GO_PATH.read_text(
            encoding="utf-8"
        ).strip()
    except Exception as exc:  # noqa: BLE001
        result["checks"]["queue_codex_read_error"] = str(exc)
    result["checks"]["queue_go_no_go"] = queue_go
    result["checks"]["queue_codex_go_no_go"] = queue_codex_go
    queue_remediated = queue_go == REQUIRED_QUEUE_GO
    queue_codex_passed = queue_codex_go == REQUIRED_QUEUE_CODEX_GO
    result["checks"]["queue_remediated"] = queue_remediated
    result["checks"]["queue_codex_passed"] = queue_codex_passed

    result["ok"] = bool(
        redis_state.get("redis_reachable")
        and redis_state.get("v2_namespaces_non_empty")
        and hb_ok
        and live_safe
        and queue_ok
        and queue_remediated
        and queue_codex_passed
    )
    return result


def load_next_10() -> list[dict[str, Any]]:
    doc = json.loads(NEXT_10_PATH.read_text(encoding="utf-8"))
    return list(doc.get("tasks") or [])


def task_is_safe_to_drive(task: dict[str, Any]) -> tuple[bool, str]:
    cat = task.get("category")
    if cat != "V2_BUILDABLE_NOW":
        return False, f"category {cat!r} is not V2_BUILDABLE_NOW"
    if task.get("blocked_on_external_source"):
        return False, "blocked_on_external_source"
    if task.get("blocked_on_operator_decision"):
        return False, "blocked_on_operator_decision"
    if task.get("blocked_on_policy_architecture"):
        return False, "blocked_on_policy_architecture"
    if task.get("blocked_on_checkpoint_artifact"):
        return False, "blocked_on_checkpoint_artifact"
    if task.get("blocked_on_field_spec"):
        return False, "blocked_on_field_spec"
    sources = task.get("v2_source_keys_to_consume") or []
    if not sources:
        return False, "no exact v2 source key listed"
    for src in sources:
        for pat in GENERIC_SOURCE_PATTERNS:
            if pat in src:
                return False, f"generic source hint detected: {src!r}"
    group = task.get("task_field_group") or ""
    if group == "portfolio_state":
        return False, "broad portfolio_state parent bucket — needs sub-field"
    if not task.get("field_metadata"):
        return False, "no field_metadata block — strict-source contract failed"
    return True, "ok"


def existing_task_suppression_for(group: str) -> tuple[str | None, str | None]:
    """Return (path, kind) for completed or in-flight task suppression."""
    slug = _slugify(group)
    marker_stem = _marker_stem_for_slug(slug)
    codex_go_no_go = (
        WORKLOG_DIR.parent / "per_task" / slug / "codex_review" / "CODEX_GO_NO_GO.md"
    )
    expected_pass_markers = {
        f"{marker_stem}_CODEX_PASS",
        f"{marker_stem}_BURNDOWN_CODEX_PASS",
        f"V2_FULL_OBSERVATION_{slug.upper()}_CODEX_PASS",
        f"V2_FULL_OBSERVATION_{slug.upper()}_BURNDOWN_CODEX_PASS",
    }
    if codex_go_no_go.exists():
        marker = codex_go_no_go.read_text(encoding="utf-8").strip()
        if marker in expected_pass_markers:
            return str(codex_go_no_go), "completed"
    fname_re = re.compile(
        rf"^\d+_(?:claude_fix|codex_review)_v2_full_observation_{re.escape(slug)}\.json$"
    )
    if not TASKS_DIR.exists():
        return None
    for f in sorted(TASKS_DIR.iterdir()):
        if not fname_re.match(f.name):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("status") in ("pending", "in_progress"):
            return str(f), "in-flight"
    return None, None


def next_task_id() -> int:
    if not TASKS_DIR.exists():
        return 1
    max_id = 0
    for f in TASKS_DIR.iterdir():
        m = re.match(r"^(\d+)_", f.name)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1


def select_next_task(tasks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (selected_task | None, list_of_skip_records)."""
    skipped: list[dict[str, Any]] = []
    for t in tasks:
        ok, reason = task_is_safe_to_drive(t)
        if not ok:
            skipped.append({
                "task_field_group": t.get("task_field_group"),
                "category": t.get("category"),
                "reason_skipped": reason,
            })
            continue
        group = t.get("task_field_group") or ""
        suppressed_path, suppressed_kind = existing_task_suppression_for(group)
        if suppressed_path:
            if suppressed_kind == "completed":
                reason = f"completed Codex PASS marker: {suppressed_path}"
            else:
                reason = f"duplicate in-flight task: {suppressed_path}"
            skipped.append({
                "task_field_group": group,
                "category": t.get("category"),
                "reason_skipped": reason,
            })
            continue
        return t, skipped
    return None, skipped


def build_claude_task(task_id: int, source_task: dict[str, Any]) -> dict[str, Any]:
    group = source_task["task_field_group"]
    slug = _slugify(group)
    marker_stem = _marker_stem_for_slug(slug)
    md = source_task.get("field_metadata") or {}
    sources = source_task.get("v2_source_keys_to_consume") or []
    field_id = md.get("field_id") or slug
    scope = md.get("scope") or "global"
    target_function = md.get("implementation_target_function") or ""
    tests = md.get("tests_required") or []
    expected_field = md.get("expected_payload_field") or ""
    stale = md.get("stale_or_missing_behavior") or ""
    dim_gap = source_task.get("aggregate_dim_gap", 0)

    prompt_lines = [
        f"# Burndown task: V2 full-observation field group `{group}`",
        "",
        "This is an autonomous burndown task driven by",
        "`claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py`.",
        "",
        "## Field spec (from remediated remaining-dim queue)",
        f"- field_id: `{field_id}`",
        f"- scope: `{scope}`",
        f"- aggregate_dim_gap: {dim_gap}",
        f"- exact V2 source key(s): {sources}",
        f"- expected payload field: `{expected_field}`",
        f"- stale_or_missing_behavior: {stale}",
        f"- implementation target function: `{target_function}`",
        f"- tests required: {tests}",
        "",
        "## Hard constraints",
        "- Do NOT consume legacy Redis keys.",
        "- Consume ONLY the exact V2 source key(s) listed above.",
        "- If the source payload is absent, emit the explicit MISSING source",
        "  label (see `SOURCE_TO_CATEGORY`). Do NOT zero-fill unknown values.",
        "- Do NOT change `checkpoint_compatibility_claimed` from false.",
        "- Do NOT change `policy_architecture_parity_claimed` from false.",
        "- Keep `zero_filled_field_count == 0`.",
        "- Do NOT start policy architecture or checkpoint loading.",
        "- Do NOT touch the legacy bot at /home/wali/Desktop/AI BOT.",
        "- Do NOT place / cancel / modify any exchange order.",
        "- Do NOT create live/canary/shutdown/Redis-trim approval tokens.",
        "",
        "## Required output",
        f"- modify only V2 files (primary edit in `{target_function}`).",
        f"- add the required tests: {tests}.",
        "- refresh `full_observation_builder_status` and any affected V2",
        "  public payloads.",
        f"- write implementation report under",
        f"  `claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/"
        f"per_task/{slug}/IMPLEMENTATION_REPORT.md`.",
        "- final GO_NO_GO marker:",
        f"  `{marker_stem}_BURNDOWN_READY_PARTIAL_PROGRESS`",
        "  or",
        f"  `{marker_stem}_BURNDOWN_BLOCKED`.",
        "",
        "When complete, the paired Codex review task",
        f"`codex_review_v2_full_observation_{slug}.json` will verify exact-source",
        "consumption, real generated-dim increase, no zero-fill, no claim drift,",
        "and runtime/live safety.",
    ]
    prompt = "\n".join(prompt_lines)

    return {
        "task_id": f"{task_id:03d}_claude_fix_v2_full_observation_{slug}",
        "agent": "claude",
        "risk_level": "L1",
        "status": "pending",
        "depends_on": [],
        "predecessor_task_ids": [],
        "predecessor_required_marker": REQUIRED_QUEUE_GO,
        "predecessor_required_marker_file": (
            "claude_worklog/final_readiness/"
            "v2_full_observation_remaining_dim_execution_queue/latest/GO_NO_GO.md"
        ),
        "cwd": str(REPO_ROOT),
        "task_granularity_mode": "consolidated_default",
        "requires_clean_worktree": False,
        "lane": "production_equivalence",
        "secondary_lane": "paper_backtest_mvp",
        "next_gate": (
            f"{marker_stem}_BURNDOWN_READY_PARTIAL_PROGRESS"
        ),
        "queue_source_task": {
            "task_field_group": group,
            "aggregate_dim_gap": dim_gap,
            "exact_v2_source_keys": sources,
            "field_metadata": md,
        },
        "allowed_output_prefixes": [
            "v2/backend/",
            "v2/frontend/public/",
            "claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/",
            "claude_worklog/agent_supervisor/tasks/",
        ],
        "forbidden_output_paths": [
            "/home/wali/Desktop/AI BOT",
            "/home/wali/Desktop/AI BOT REBUILD/legacy_reference",
        ],
        "required_output_files": [
            (
                f"claude_worklog/final_readiness/"
                f"v2_autonomous_production_equivalence_burndown/per_task/{slug}/"
                f"IMPLEMENTATION_REPORT.md"
            ),
        ],
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "controller_metadata": {
            "controller": "v2_autonomous_production_equivalence_burndown_controller",
            "selected_at_utc": _utc_iso(),
            "queue_path": str(QUEUE_PATH.relative_to(REPO_ROOT)),
            "next_10_path": str(NEXT_10_PATH.relative_to(REPO_ROOT)),
            "field_group": group,
            "slug": slug,
        },
        "prompt": prompt,
    }


def build_codex_task(task_id: int, claude_task: dict[str, Any], source_task: dict[str, Any]) -> dict[str, Any]:
    group = source_task["task_field_group"]
    slug = _slugify(group)
    marker_stem = _marker_stem_for_slug(slug)
    sources = source_task.get("v2_source_keys_to_consume") or []
    md = source_task.get("field_metadata") or {}
    field_id = md.get("field_id") or slug
    tests = md.get("tests_required") or []

    prompt = "\n".join([
        f"# Codex review: V2 full-observation field group `{group}`",
        "",
        "Review Claude's implementation produced by task",
        f"`{claude_task['task_id']}`.",
        "",
        "## Verify",
        f"- only the exact V2 source key(s) {sources} were consumed.",
        "- no generic `v2:*` placeholder source remained in the changeset.",
        "- no field that lacks an exact runtime source was treated as buildable.",
        "- `generated_full_observation_dim` actually increased (real, not synthetic).",
        f"- missing-source labels remain explicit (for field `{field_id}` when payload absent).",
        "- `zero_filled_field_count == 0` after the change.",
        "- `checkpoint_compatibility_claimed` remains false.",
        "- `policy_architecture_parity_claimed` remains false.",
        "- no old Redis writes; no exchange mutation; no approvals; no live ramp.",
        "- live_gate=blocked_human_only and live_symbols=[].",
        f"- the required tests run and pass: {tests}.",
        "",
        "## Decision strings (exact)",
        f"PASS: `{marker_stem}_CODEX_PASS`",
        f"FAIL: `{marker_stem}_CODEX_FAIL`",
        "",
        "On FAIL: emit a precise fail-blocker string in the review markdown so",
        "the controller can generate a focused remediation task next cycle.",
    ])

    return {
        "task_id": f"{task_id:03d}_codex_review_v2_full_observation_{slug}",
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "depends_on": [claude_task["task_id"]],
        "predecessor_task_ids": [claude_task["task_id"]],
        "predecessor_required_marker": claude_task["next_gate"],
        "predecessor_required_marker_file": claude_task["required_output_files"][0],
        "cwd": str(REPO_ROOT),
        "lane": "production_equivalence",
        "secondary_lane": "paper_backtest_mvp",
        "next_gate": (
            f"{marker_stem}_CODEX_PASS"
        ),
        "controller_metadata": {
            "controller": "v2_autonomous_production_equivalence_burndown_controller",
            "selected_at_utc": _utc_iso(),
            "field_group": group,
            "slug": slug,
        },
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "prompt": prompt,
    }


def write_task(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def emit_status(state: dict[str, Any]) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WORKLOG_DIR / "autonomous_burndown_status.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "operator_dashboard_payload.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def cycle(args: argparse.Namespace) -> dict[str, Any]:
    state: dict[str, Any] = {
        "controller": "v2_autonomous_production_equivalence_burndown_controller",
        "timestamp_utc": _utc_iso(),
        "mode": args.mode,
        "dry_run": bool(args.dry_run),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    preflight = runtime_preflight()
    state["preflight"] = preflight
    if not preflight["ok"]:
        state["go_no_go"] = (
            "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_BLOCKED"
        )
        state["next_action"] = (
            "fix runtime preflight (redis, heartbeats, live-safety, queue"
            " remediation) before continuing feature work"
        )
        return state

    tasks = load_next_10()
    selected, skipped = select_next_task(tasks)
    state["queue_loaded_task_count"] = len(tasks)
    state["skipped_tasks_with_reasons"] = skipped
    state["duplicate_suppression_count"] = sum(
        1 for s in skipped if str(s.get("reason_skipped", "")).startswith("duplicate")
    )
    state["completed_suppression_count"] = sum(
        1 for s in skipped if str(s.get("reason_skipped", "")).startswith("completed")
    )

    if selected is None:
        has_inflight = any(
            str(s.get("reason_skipped", "")).startswith("duplicate")
            for s in skipped
        )
        has_only_completed_suppression = bool(skipped) and all(
            str(s.get("reason_skipped", "")).startswith("completed")
            for s in skipped
        )
        # Pending/in-progress descriptors mean the controller should wait.
        # Completed Codex PASS markers mean the buildable queue entry is done.
        if has_inflight:
            state["status"] = "WAITING_ON_INFLIGHT_TASKS"
            state["next_action"] = (
                "wait for in-flight claude_fix_v2_full_observation_* tasks"
                " to complete and Codex review"
            )
            state["go_no_go"] = (
                "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY"
            )
        else:
            state["status"] = "V2_OBSERVATION_BUILDABLE_QUEUE_EXHAUSTED_NEXT_GATE_READY"
            state["next_action"] = (
                "operator-approved next gate (policy architecture, checkpoint"
                " artifact, paid alt-data, or external sources)"
            )
            state["go_no_go"] = (
                "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY"
            )
            if has_only_completed_suppression:
                state["reason_exhausted"] = (
                    "all remaining exact-source queue entries already have"
                    " completed Codex PASS markers"
                )
        return state

    md = selected.get("field_metadata") or {}
    state["selected_task_id"] = None
    state["selected_field_group"] = selected.get("task_field_group")
    state["selected_dim_count"] = selected.get("aggregate_dim_gap")
    state["exact_source_keys"] = selected.get("v2_source_keys_to_consume")
    state["selected_field_metadata"] = md
    state["reason_selected"] = (
        "highest-ranked V2_BUILDABLE_NOW field group with exact source binding"
        " and no in-flight duplicate"
    )

    if args.dry_run:
        state["next_action"] = "dry-run only; no task descriptor written"
        state["go_no_go"] = (
            "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY"
        )
        return state

    claude_id = next_task_id()
    claude_task = build_claude_task(claude_id, selected)
    codex_id = claude_id + 1
    codex_task = build_codex_task(codex_id, claude_task, selected)
    claude_path = TASKS_DIR / f"{claude_task['task_id']}.json"
    codex_path = TASKS_DIR / f"{codex_task['task_id']}.json"
    write_task(claude_path, claude_task)
    write_task(codex_path, codex_task)

    state["selected_task_id"] = claude_task["task_id"]
    state["paired_codex_task_id"] = codex_task["task_id"]
    state["active_task_claude_path"] = str(claude_path.relative_to(REPO_ROOT))
    state["active_task_codex_path"] = str(codex_path.relative_to(REPO_ROOT))
    state["next_action"] = (
        "supervisor picks up the claude task, then codex review task"
    )
    state["go_no_go"] = (
        "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY"
    )
    return state


def cmd_status() -> dict[str, Any]:
    status_path = WORKLOG_DIR / "autonomous_burndown_status.json"
    if status_path.exists():
        return json.loads(status_path.read_text(encoding="utf-8"))
    return {
        "controller": "v2_autonomous_production_equivalence_burndown_controller",
        "status": "NEVER_RAN",
        "timestamp_utc": _utc_iso(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--once", dest="mode", action="store_const", const="once")
    g.add_argument("--loop", dest="mode", action="store_const", const="loop")
    g.add_argument("--status", dest="mode", action="store_const", const="status")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--loop-interval-seconds",
        type=int,
        default=180,
        help="sleep between cycles in --loop mode (clamped to >=60).",
    )
    p.add_argument(
        "--loop-max-cycles",
        type=int,
        default=1,
        help="safety cap on --loop cycles (default 1 — operator must"
        " explicitly raise to drive autonomously).",
    )
    args = p.parse_args()
    if args.mode is None:
        args.mode = "once"

    if args.mode == "status":
        print(json.dumps(cmd_status(), indent=2, sort_keys=True))
        return 0

    if args.mode == "once":
        state = cycle(args)
        if not args.dry_run:
            emit_status(state)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0 if state.get("go_no_go", "").endswith("READY") else 1

    # loop mode
    interval = max(60, int(args.loop_interval_seconds))
    cycles = max(1, int(args.loop_max_cycles))
    last_state: dict[str, Any] = {}
    for i in range(cycles):
        last_state = cycle(args)
        emit_status(last_state)
        # Stop conditions per Phase 5
        if last_state.get("go_no_go", "").endswith("BLOCKED"):
            break
        if last_state.get("status") in (
            "V2_OBSERVATION_BUILDABLE_QUEUE_EXHAUSTED_NEXT_GATE_READY",
            "WAITING_ON_INFLIGHT_TASKS",
        ):
            break
        if i < cycles - 1:
            time.sleep(interval)
    print(json.dumps(last_state, indent=2, sort_keys=True))
    return 0 if last_state.get("go_no_go", "").endswith("READY") else 1


if __name__ == "__main__":
    sys.exit(main())
