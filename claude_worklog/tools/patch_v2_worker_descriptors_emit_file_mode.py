#!/usr/bin/env python3
"""Patch V2 Claude worker descriptors for supervisor file materialization.

The agent supervisor only writes files from Claude stdout when descriptors set
emit_files=true and the prompt asks for BEGIN_FILE blocks. Without that contract
Claude can return a prose summary while required_output_files remain missing.
This patch is idempotent and touches task descriptors only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
FINAL_APPROVAL_TOKEN = (
    REPO_ROOT / "claude_worklog" / "approvals" / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
)
REDIS_TRIM_APPROVAL = (
    REPO_ROOT
    / "claude_worklog"
    / "approvals"
    / "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
)


def normalize_relpath(value: Any) -> str:
    return str(value).strip().replace("\\", "/").lstrip("/")


def prefix_for_output(rel_path: str) -> str:
    parent = str(Path(rel_path).parent).replace("\\", "/")
    if parent in {"", "."}:
        return ""
    return parent.rstrip("/") + "/"


def emit_prompt_prefix(required_outputs: list[str]) -> str:
    required = "\n".join(f"- {path}" for path in required_outputs)
    return (
        "EMIT-FILE MODE - DO NOT USE INTERACTIVE WRITE/EDIT TOOLS. "
        "The supervisor will materialize files from stdout. Output BEGIN_FILE "
        "blocks only for the required files. Use exactly this format, repeated "
        "once per file:\n"
        "BEGIN_FILE: relative/path/from/repo/root\n"
        "<complete file contents>\n"
        "END_FILE\n\n"
        "Required files to emit exactly:\n"
        f"{required}\n\n"
        "Do not ask for permission to write files. Do not say files are drafted. "
        "Do not output a summary instead of file blocks. If you cannot complete "
        "all implementation files in one pass, still emit the legacy baseline "
        "files first when required and emit a failing status/report explaining "
        "the blocker. Keep live blocked_human_only. Do not touch "
        "/home/wali/Desktop/AI BOT. Do not write old Redis. Do not call exchange "
        "mutation APIs. Do not change leverage or margin.\n\n"
    )


def patch_descriptor(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("agent") != "claude":
        return False
    if not str(data.get("task_id", "")).startswith("claude_port_v2"):
        return False

    required_outputs = [normalize_relpath(p) for p in data.get("required_output_files", [])]
    required_outputs = [p for p in required_outputs if p]
    if not required_outputs:
        return False

    changed = False
    if data.get("emit_files") is not True:
        data["emit_files"] = True
        changed = True

    prefixes = [p for p in data.get("allowed_output_prefixes", []) if str(p).strip()]
    for output in required_outputs:
        prefix = prefix_for_output(output)
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
            changed = True
    if prefixes and data.get("allowed_output_prefixes") != prefixes:
        data["allowed_output_prefixes"] = prefixes
        changed = True

    prompt = str(data.get("prompt") or "")
    if "EMIT-FILE MODE" not in prompt or "BEGIN_FILE" not in prompt:
        data["prompt"] = emit_prompt_prefix(required_outputs) + prompt
        changed = True

    try:
        max_attempts = int(data.get("max_attempts", 0) or 0)
    except Exception:
        max_attempts = 0
    if max_attempts < 5:
        data["max_attempts"] = 5
        changed = True

    try:
        timeout = int(data.get("task_timeout_seconds", 0) or 0)
    except Exception:
        timeout = 0
    if timeout < 2400:
        data["task_timeout_seconds"] = 2400
        changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    if FINAL_APPROVAL_TOKEN.exists():
        raise SystemExit(f"FINAL_APPROVAL_TOKEN_PRESENT: {FINAL_APPROVAL_TOKEN}")
    if REDIS_TRIM_APPROVAL.exists():
        raise SystemExit(f"REDIS_TRIM_APPROVAL_PRESENT: {REDIS_TRIM_APPROVAL}")

    changed_paths: list[str] = []
    for path in sorted(TASKS_DIR.glob("claude_port_v2*.json")):
        if patch_descriptor(path):
            changed_paths.append(str(path.relative_to(REPO_ROOT)))

    print(json.dumps({"changed": changed_paths, "changed_count": len(changed_paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
