#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Dict, List

from common_audit import resolve_path, write_json, write_markdown, redact_text


def run_cmd(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    except Exception as e:
        return f"ERROR: {e}"


def proc_meta(pid: int) -> Dict[str, str]:
    d: Dict[str, str] = {}
    try:
        d["executable"] = str(Path(f"/proc/{pid}/exe").resolve())
    except Exception:
        d["executable"] = ""
    try:
        d["cwd"] = str(Path(f"/proc/{pid}/cwd").resolve())
    except Exception:
        d["cwd"] = ""
    try:
        d["cmdline"] = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except Exception:
        d["cmdline"] = ""
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()

    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    legacy_bot_root = str((Path.home() / "Desktop" / "AI BOT").resolve())

    command_outputs = {
        "ps_aux": run_cmd(["ps", "aux"]),
        "pgrep_python": run_cmd(["pgrep", "-af", "python"]),
        "pgrep_node": run_cmd(["pgrep", "-af", "node"]),
        "pgrep_redis": run_cmd(["pgrep", "-af", "redis"]),
        "tmux_ls": run_cmd(["tmux", "ls"]),
        "docker_ps": run_cmd(["docker", "ps"]),
        "systemctl_user": run_cmd(["systemctl", "--user", "list-units"]),
        "crontab_l": run_cmd(["crontab", "-l"]),
    }

    ps_lines = run_cmd(["ps", "-eo", "pid=,args="]).splitlines()
    procs: List[Dict[str, str]] = []
    unmapped_bot_like = []
    for ln in ps_lines:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(maxsplit=1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        safe_cmd = redact_text(cmd) or ""
        if not any(k in cmd.lower() for k in ["python", "node", "redis", "trainer", "trader", "orchestrator", "uvicorn"]):
            continue
        meta = proc_meta(pid)
        bot_looking = any(k in cmd.lower() for k in ["trainer", "trader", "ingest", "orchestrator", "live_"])
        mapped_legacy = ""
        if legacy_bot_root in cmd:
            mapped_legacy = legacy_bot_root
        elif "Desktop/AI BOT" in cmd and (meta.get("cwd") or "").startswith(str(Path.home())):
            mapped_legacy = str((Path(meta.get("cwd") or str(Path.home())) / "Desktop/AI BOT").resolve())
        elif legacy_bot_root and legacy_bot_root in (meta.get("cwd") or ""):
            mapped_legacy = legacy_bot_root
        status = "not_bot_related"
        reason = "no legacy bot indicators"
        if mapped_legacy:
            status = "mapped"
            reason = "command/cwd maps to legacy bot root"
        elif bot_looking:
            status = "unmapped"
            reason = "bot-like command without legacy root mapping"
            unmapped_bot_like.append({"pid": pid, "command": cmd, "cwd": meta.get("cwd", "")})
        procs.append({
            "pid": pid,
            "command": safe_cmd,
            "executable": meta.get("executable", ""),
            "cwd": meta.get("cwd", ""),
            "cmdline": redact_text(meta.get("cmdline", "")) or "",
            "mapped_legacy_path": mapped_legacy,
            "mapped_status": status,
            "classification_reason": reason,
            "evidence": {
                "source_file": "process_table",
                "line": None,
                "matched_text": safe_cmd[:400],
                "kind": "runtime_process",
                "classification_reason": reason,
                "verification_command": f"ps -p {pid} -o pid,cmd && readlink -f /proc/{pid}/exe && readlink -f /proc/{pid}/cwd",
            },
        })

    data = {
        "legacy_bot_root": legacy_bot_root,
        "commands": command_outputs,
        "processes": procs,
        "unmapped_bot_like_processes": unmapped_bot_like,
    }
    write_json(out / "RUNTIME_PROCESS_MAP.json", data)

    md = ["# Runtime Process Map", "", f"Processes tracked: {len(procs)}", f"Unmapped bot-looking: {len(unmapped_bot_like)}", "", "| pid | status | cwd | command |", "|---:|---|---|---|"]
    for p in procs[:500]:
        md.append(f"| {p['pid']} | {p['mapped_status']} | {str(p['cwd']).replace('|','/')} | {p['command'][:120].replace('|','/')} |")
    write_markdown(out / "RUNTIME_PROCESS_MAP.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
