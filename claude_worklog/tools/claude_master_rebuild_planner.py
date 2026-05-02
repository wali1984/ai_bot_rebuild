#!/usr/bin/env python3
"""Claude Master Rebuild Planner.

Scans the requirements inbox, builds a bounded Claude planning prompt from repo
evidence, and optionally runs one Claude planning cycle. The daemon mode keeps
the requirement intake/status loop alive; it does not grant live permissions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import time
from typing import Any, Dict, List, Tuple


WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
INBOX = WORKSPACE / "claude_worklog/requirements_inbox"
PROCESSED = WORKSPACE / "claude_worklog/agent_supervisor/runtime/master_planner/processed_requirements.json"
STATUS = WORKSPACE / "claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json"
PROMPT_OUT = WORKSPACE / "claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt"

EVIDENCE_ROOTS = [
    "claude_worklog/requirements_inbox",
    "claude_worklog/v2_requirements",
    "claude_worklog/v2_architecture",
    "claude_worklog/legacy_preservation",
    "claude_worklog/phase2_core_rebuild",
    "claude_worklog/legacy_runtime_audit",
    "claude_worklog/secret_migration",
    "v2",
    "legacy_reference",
]

ALLOWED_MATERIALIZE_PREFIXES = (
    "claude_worklog/agent_supervisor/tasks/",
    "claude_worklog/phase2_core_rebuild/",
    "claude_worklog/v2_scaffold_reviews/",
    "claude_worklog/security/",
    "claude_worklog/autonomous_control_plane/",
    "v2/",
)

FORBIDDEN_TEXT = (
    "redis-cli",
    "XADD",
    "XDEL",
    "FLUSHDB",
    "FLUSHALL",
    "create_order",
    "cancel_order",
    "change_leverage",
    "change_margin",
    "enable_live_trading",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_text(path: pathlib.Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def append_event(event: str, **payload: Any) -> None:
    path = WORKSPACE / "claude_worklog/agent_supervisor/events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"event": event, "ts": now_iso(), **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def git_last_commit() -> str:
    cp = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(WORKSPACE), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return cp.stdout.strip()


def git_status_short() -> str:
    cp = subprocess.run(["git", "status", "--short"], cwd=str(WORKSPACE), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return cp.stdout.strip()


def inbox_requirements() -> List[Dict[str, str]]:
    INBOX.mkdir(parents=True, exist_ok=True)
    reqs: List[Dict[str, str]] = []
    for path in sorted(INBOX.glob("*.md")):
        if path.name == "README.md":
            continue
        reqs.append({"name": path.name, "path": str(path.relative_to(WORKSPACE)), "text": read_text(path)})
    return reqs


def processed_requirements() -> Dict[str, Any]:
    return read_json(PROCESSED) or {"processed": {}}


def evidence_satisfied_requirements() -> Dict[str, str]:
    satisfied: Dict[str, str] = {}

    usdm_codex = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/symbol_universe/12_CODEX_GO_NO_GO_USDM_CORRECTION.md", 2000)
    if "PHASE2_SYMBOL_UNIVERSE_USDM_CORRECTION_CODEX_PASS" in usdm_codex:
        satisfied["REQ_0001_BINANCE_USDM_PRIMARY.md"] = "phase2_usdm_correction_codex_pass"

    coinank_policy = read_text(WORKSPACE / "claude_worklog/legacy_preservation/05_INGESTOR_AND_FEATURE_PIPELINE_PRESERVATION_MATRIX.md", 20000)
    ingestor_go = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/ingestors/04_GO_NO_GO.md", 2000)
    if "INGESTOR_AND_FEATURE_PIPELINE_PRESERVATION_MATRIX_READY" in coinank_policy and "PHASE2_INGESTOR_PRESERVATION_READY" in ingestor_go:
        satisfied["REQ_0003_LIVE_COINANK_COPY_AS_IS.md"] = "phase2_ingestor_preservation_ready"

    service_map_codex = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/legacy_service_map/13_CODEX_GO_NO_GO.md", 2000)
    if "PHASE2_LEGACY_SERVICE_MAP_CODEX_PASS" in service_map_codex:
        satisfied["REQ_0005_STARTUP_SCRIPT_RUNTIME_MAP_SOURCE_OF_TRUTH.md"] = "legacy_service_map_codex_pass"

    return satisfied


def effective_processed_requirements() -> Dict[str, Any]:
    processed = dict(processed_requirements().get("processed") or {})
    for name, reason in evidence_satisfied_requirements().items():
        processed.setdefault(name, {"source": "existing_evidence", "reason": reason})
    return processed


def unprocessed_requirements() -> List[Dict[str, str]]:
    processed = effective_processed_requirements()
    return [req for req in inbox_requirements() if req["name"] not in processed]


def context_summary() -> str:
    markers = [
        "claude_worklog/phase2_core_rebuild/symbol_universe/12_CODEX_GO_NO_GO_USDM_CORRECTION.md",
        "claude_worklog/phase2_core_rebuild/feature_snapshots/07_CODEX_GO_NO_GO.md",
        "claude_worklog/phase2_core_rebuild/legacy_service_map/13_CODEX_GO_NO_GO.md",
        "claude_worklog/phase2_core_rebuild/ingestors/04_GO_NO_GO.md",
        "claude_worklog/final_readiness/04_GO_NO_GO.md",
    ]
    lines = []
    for rel in markers:
        marker = read_text(WORKSPACE / rel, 1000).strip().splitlines()
        if marker:
            lines.append(f"- {rel}: {marker[0]}")
    return "\n".join(lines)


def choose_active_requirement(reqs: List[Dict[str, str]]) -> Dict[str, str] | None:
    return reqs[0] if reqs else None


def planned_task_for_requirement(requirement_name: str | None) -> str | None:
    if requirement_name == "REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md":
        return "042_coinank_uploaded_symbol_alias_fixture"
    if requirement_name == "REQ_0004_TRAINER_GPU_PARITY.md":
        return "050_trainer_gpu_parity_rebuild_plan"
    return None


def parse_begin_file_blocks(text: str) -> List[Tuple[str, str]]:
    blocks: List[Tuple[str, str]] = []
    strict = re.findall(r"^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$", text, re.S | re.M)
    for rel, content in strict:
        blocks.append((rel.strip(), content.strip()))
    if blocks:
        return blocks

    markers = list(re.finditer(r"^BEGIN_FILE:?\s*(.+)$", text, re.M))
    for i, marker in enumerate(markers):
        rel = marker.group(1).strip()
        start = marker.end() + 1
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        content = text[start:end].strip()
        if content.endswith("END_FILE"):
            content = content[: -len("END_FILE")].strip()
        blocks.append((rel, content))
    return blocks


def sanitize_emitted_file_content(rel_path: str, content: str) -> Tuple[str, bool]:
    source_suffixes = (".py", ".toml", ".json", ".yaml", ".yml", ".ts", ".tsx", ".js", ".jsx", ".sh", ".css", ".html")
    if not rel_path.endswith(source_suffixes):
        return content.rstrip() + "\n", False
    lines = content.splitlines()
    changed = False
    cleaned: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "```" or re.fullmatch(r"```(python|toml|json|bash|sh|typescript|tsx|javascript|jsx|yaml|yml|css|html)?", stripped):
            changed = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned).rstrip() + "\n", changed


def safe_materialize_blocks(stdout: str) -> Tuple[List[str], List[str]]:
    materialized: List[str] = []
    refused: List[str] = []
    for rel, content in parse_begin_file_blocks(stdout):
        rel = rel.strip()
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            refused.append(rel or "<empty>")
            continue
        if not any(rel.startswith(prefix) for prefix in ALLOWED_MATERIALIZE_PREFIXES):
            refused.append(rel)
            continue
        if any(forbidden in content for forbidden in FORBIDDEN_TEXT):
            refused.append(rel)
            append_event("master_planner_refused_forbidden_content", path=rel)
            continue
        clean, changed = sanitize_emitted_file_content(rel, content)
        target = WORKSPACE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(clean, encoding="utf-8")
        materialized.append(rel)
        append_event("master_planner_materialized_file", path=rel)
        if changed:
            append_event("materialized_content_sanitized", path=rel, reason="removed_outer_markdown_fence")
    return materialized, refused


def generated_task_ids(materialized: List[str]) -> List[str]:
    task_ids: List[str] = []
    for rel in materialized:
        if not rel.startswith("claude_worklog/agent_supervisor/tasks/") or not rel.endswith(".json"):
            continue
        data = read_json(WORKSPACE / rel)
        task_id = str(data.get("task_id") or pathlib.Path(rel).stem)
        risk = str(data.get("risk_level") or "L1").upper()
        if data.get("status") == "pending" and risk in {"L1", "L2", "L3"}:
            task_ids.append(task_id)
    return task_ids


def run_generated_tasks(task_ids: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for task_id in task_ids[:1]:
        append_event("master_planner_supervisor_task_started", task_id=task_id)
        cp = subprocess.run(
            ["python3", "claude_worklog/tools/agent_supervisor.py", "--task-id", task_id],
            cwd=str(WORKSPACE),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=7200,
        )
        results.append({"task_id": task_id, "returncode": cp.returncode, "stdout_chars": len(cp.stdout), "stderr_chars": len(cp.stderr)})
        append_event("master_planner_supervisor_task_completed", task_id=task_id, returncode=cp.returncode)
        out_dir = WORKSPACE / "claude_worklog/agent_supervisor/runtime/master_planner"
        (out_dir / f"{task_id}_supervisor_stdout.txt").write_text(cp.stdout, encoding="utf-8")
        (out_dir / f"{task_id}_supervisor_stderr.txt").write_text(cp.stderr, encoding="utf-8")
        if cp.returncode != 0:
            break
    return results


def build_prompt() -> str:
    reqs = unprocessed_requirements()
    active = choose_active_requirement(reqs)
    req_block = "\n\n".join(f"## {req['name']}\n{req['text']}" for req in reqs) or "No unprocessed requirements."
    return f"""You are Claude Code running as the Master Non-Live V2 Rebuild Planner.

Read the repo evidence roots:
{chr(10).join(f"- {root}" for root in EVIDENCE_ROOTS)}

Current gate markers:
{context_summary() or "- none"}

Unprocessed requirements inbox:
{req_block}

Active requirement:
{active['name'] if active else '-'}

Objective:
- Map requirements against legacy_reference, service map, preservation policies, V2 code, and current Phase 2 artifacts.
- Decide the next safest non-live rebuild milestone yourself.
- Generate task definitions, implementation outputs, validation reports, Codex review tasks, and remediation tasks as needed.
- Execute through agent_supervisor where appropriate.
- Validate, commit, push, request Codex review, remediate safe findings, and continue until a real safety gate.

Required planner knowledge:
- Binance USD-M is primary; `/fapi/v1/exchangeInfo`; BTCUSDT-style symbols are primary.
- COIN-M is optional/future adapter support only and must not collapse with USD-M.
- Uploaded CoinAnk symbol list is discovery/alias evidence, not directly tradable universe.
- `live_coinank.py` is copy-as-is and must not be changed.
- `feature_pipeline.py` is parity-critical.
- Trainer/GPU behavior must be parity-rebuilt, not replaced with a basic trainer.
- Legacy config.py 25 symbols are active subset only, not full universe.

Hard stops:
- Do not modify /home/wali/Desktop/AI BOT.
- Do not write/delete Redis.
- Do not restart live services.
- Do not place/cancel exchange orders.
- Do not change leverage/margin.
- Do not enable live trading.
- Do not deploy.
- Do not run production migrations.
- Do not expose or commit secrets.
- Stop on L4/L5, live/legacy/Redis/exchange/deploy/secrets, or Codex hard fail with no safe remediation.

Output policy:
- Print BEGIN_FILE / END_FILE blocks only.
- Keep every output inside AI BOT REBUILD.
- Do not print secret values.
"""


def status_payload(mode: str, blocked_reason: str | None = None) -> Dict[str, Any]:
    reqs = unprocessed_requirements()
    active = choose_active_requirement(reqs)
    payload = {
        "generated_at": now_iso(),
        "mode": mode,
        "active_requirement": active["name"] if active else None,
        "unprocessed_requirements": [req["name"] for req in reqs],
        "processed_requirements": sorted(effective_processed_requirements().keys()),
        "evidence_satisfied_requirements": sorted(evidence_satisfied_requirements().keys()),
        "active_milestone": "master_planner_requirement_intake" if active else "idle",
        "active_task": planned_task_for_requirement(active["name"] if active else None),
        "current_phase": "phase2_core_rebuild",
        "codex_gate": "required_after_each_milestone",
        "last_commit": git_last_commit(),
        "blocked_reason": blocked_reason,
        "human_attention_required": bool(blocked_reason),
        "next_action": "run Claude planner for active requirement" if active else "wait for requirements",
        "final_live_gate_status": "blocked_human_only",
        "git_status": git_status_short(),
    }
    write_json(STATUS, payload)
    return payload


def run_once(dry_run: bool = False) -> Dict[str, Any]:
    prompt = build_prompt()
    PROMPT_OUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_OUT.write_text(prompt, encoding="utf-8")
    payload = status_payload("dry-run" if dry_run else "run-once")
    payload["prompt_path"] = str(PROMPT_OUT.relative_to(WORKSPACE))
    if dry_run or not payload["active_requirement"]:
        write_json(STATUS, payload)
        return payload
    cp = subprocess.run(
        ["claude", "--print", prompt, "--output-format", "text"],
        cwd=str(WORKSPACE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=3600,
    )
    out_dir = WORKSPACE / "claude_worklog/agent_supervisor/runtime/master_planner"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_stdout.txt").write_text(cp.stdout, encoding="utf-8")
    (out_dir / "last_stderr.txt").write_text(cp.stderr, encoding="utf-8")
    payload.update({"returncode": cp.returncode, "stdout_chars": len(cp.stdout), "stderr_chars": len(cp.stderr)})
    if cp.returncode != 0:
        payload["blocked_reason"] = "claude_master_planner_invocation_failed"
        payload["human_attention_required"] = True
    else:
        materialized, refused = safe_materialize_blocks(cp.stdout)
        task_ids = generated_task_ids(materialized)
        task_results = run_generated_tasks(task_ids)
        payload.update({
            "materialized_files": materialized,
            "refused_files": refused,
            "generated_task_ids": task_ids,
            "supervisor_task_results": task_results,
        })
        if refused:
            payload["blocked_reason"] = "master_planner_refused_unsafe_or_unexpected_file"
            payload["human_attention_required"] = True
        elif any(result.get("returncode") not in {0, None} for result in task_results):
            payload["blocked_reason"] = "generated_supervisor_task_failed"
            payload["human_attention_required"] = True
    write_json(STATUS, payload)
    return payload


def daemon(poll_seconds: int) -> int:
    while True:
        try:
            run_once(dry_run=False)
        except Exception as exc:
            write_json(STATUS, status_payload("daemon", blocked_reason=f"planner_exception:{exc}"))
        time.sleep(max(30, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=120)
    args = parser.parse_args()

    if args.daemon:
        return daemon(args.poll_seconds)
    if args.run_once:
        payload = run_once(dry_run=False)
    elif args.dry_run:
        payload = run_once(dry_run=True)
    else:
        payload = status_payload("status")
    print(json.dumps(payload, indent=2))
    return 2 if payload.get("human_attention_required") else 0


if __name__ == "__main__":
    raise SystemExit(main())
