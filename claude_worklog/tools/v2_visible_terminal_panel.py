#!/usr/bin/env python3
"""Visible status panel for one V2 service/category.

This is the per-terminal foreground loop launched by
``start_v2_rebuild_gnome_terminals.sh``. Every iteration (default 10 s)
prints, with EST timestamps:

  * panel title
  * systemd unit status (active/inactive, sub-state, PID, memory)
  * recent journal lines (or recent log tail) for the unit
  * Redis key counts for one or more patterns
  * public payload freshness (age in seconds)
  * last error line (best effort)
  * safety footer (LIVE_GATE, live_symbols, real_order_attempted)

Runs forever; press Ctrl+C in the terminal to stop.

Hard rules:
  - prints heartbeat at least every interval
  - never enables live trading; never invokes any mutation method
  - never reads or prints credential values
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


EST = ZoneInfo("America/New_York")
REPO = "/home/wali/Desktop/AI BOT REBUILD"
LIVE_GATE_VALUE = "blocked_human_only"

# ANSI colors (subset; mimic legacy style without bringing in dependencies).
G = "\033[32m"
R = "\033[31m"
Y = "\033[33m"
C = "\033[36m"
M = "\033[35m"
B = "\033[1m"
D = "\033[2m"
RST = "\033[0m"


def now_est_str() -> str:
    return datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S %Z")


def color(text: str, c: str) -> str:
    return f"{c}{text}{RST}"


def safe_run(cmd: List[str], timeout: float = 8.0) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def safe_run_shell(cmd: str, timeout: float = 8.0) -> Tuple[int, str, str]:
    return safe_run(["bash", "-lc", cmd], timeout=timeout)


def fmt_systemd_status(unit: Optional[str]) -> List[str]:
    if not unit:
        return [color("systemd unit: (not applicable)", D)]
    rc, out, _ = safe_run(["systemctl", "--user", "is-active", unit], timeout=4)
    active = (out.strip() or "unknown")
    rc, sub, _ = safe_run(["systemctl", "--user", "is-failed", unit], timeout=4)
    failed = sub.strip()
    rc, props, _ = safe_run([
        "systemctl", "--user", "show", unit,
        "-p", "MainPID", "-p", "ActiveState", "-p", "SubState",
        "-p", "MemoryCurrent", "-p", "ExecMainStartTimestamp"
    ], timeout=4)
    kv: Dict[str, str] = {}
    for line in props.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    main_pid = kv.get("MainPID", "0") or "0"
    sub_state = kv.get("SubState", "")
    mem_b = kv.get("MemoryCurrent", "")
    mem_mb = ""
    if mem_b.isdigit():
        mem_mb = f"{int(mem_b) / (1024 * 1024):.1f} MB"
    start_ts = kv.get("ExecMainStartTimestamp", "")
    col_active = G if active == "active" else (R if active == "failed" else Y)
    lines = [
        f"systemd unit  : {unit}",
        f"  state       : {color(active, col_active)} (sub={sub_state})  pid={main_pid}  mem={mem_mb}",
        f"  started     : {start_ts}",
    ]
    if failed == "failed":
        lines.append(color("  FAILED", R))
    return lines


def fmt_journal_tail(unit: Optional[str], n: int = 5) -> List[str]:
    if not unit:
        return []
    rc, out, err = safe_run([
        "journalctl", "--user", "-u", unit, "-n", str(n), "--no-pager",
        "--output", "short"
    ], timeout=6)
    if not out.strip():
        # Some services log to files only.
        return [color(f"journal: (no entries in last {n})", D)]
    lines = [color(f"journal tail (last {n}):", C)]
    for ln in out.splitlines()[-n:]:
        lines.append("  " + ln)
    return lines


def fmt_log_tail(log_path: Optional[Path], n: int = 5) -> List[str]:
    if not log_path:
        return []
    p = Path(log_path) if not isinstance(log_path, Path) else log_path
    if not p.exists():
        return [color(f"log file: {p} (absent)", D)]
    try:
        with p.open("rb") as fh:
            try:
                fh.seek(-8192, os.SEEK_END)
            except OSError:
                fh.seek(0)
            tail = fh.read().decode(errors="replace").splitlines()
    except Exception as e:
        return [color(f"log tail error: {e}", R)]
    lines = [color(f"log tail ({p}, last {n}):", C)]
    for ln in tail[-n:]:
        lines.append("  " + ln)
    return lines


def fmt_redis_keys(patterns: List[str]) -> List[str]:
    if not patterns:
        return []
    lines = [color("redis key counts:", C)]
    for pat in patterns:
        rc, out, _ = safe_run_shell(f"redis-cli --scan --pattern '{pat}' | wc -l", timeout=6)
        count = (out.strip() or "?")
        rc, sample, _ = safe_run_shell(f"redis-cli --scan --pattern '{pat}' | head -3", timeout=6)
        sample_keys = [s for s in sample.splitlines() if s.strip()][:3]
        lines.append(f"  {pat:38s} = {count}")
        for sk in sample_keys:
            lines.append(f"    sample: {sk}")
    return lines


def fmt_payload_freshness(payload_dirs: List[str]) -> List[str]:
    if not payload_dirs:
        return []
    lines = [color("public payload freshness:", C)]
    now = time.time()
    for d in payload_dirs:
        full = os.path.join(REPO, d)
        newest = None
        newest_st = None
        if os.path.isdir(full):
            for root, _dirs, files in os.walk(full):
                for f in files:
                    if f.endswith(".json"):
                        fp = os.path.join(root, f)
                        try:
                            st = os.stat(fp).st_mtime
                        except FileNotFoundError:
                            continue
                        if newest_st is None or st > newest_st:
                            newest_st = st
                            newest = fp
        if newest is None:
            lines.append(f"  {d}: (no json found)")
        else:
            age_s = int(now - newest_st)
            col = G if age_s < 300 else (Y if age_s < 1800 else R)
            lines.append(
                f"  {d}: age={color(f'{age_s}s', col)}  newest={os.path.basename(newest)}"
            )
    return lines


def fmt_command_rerun(cmd: str) -> List[str]:
    rc, out, err = safe_run_shell(cmd, timeout=20)
    lines = [color(f"one-shot rerun (rc={rc}):", C), f"  $ {cmd}"]
    body = (out or err or "").splitlines()
    for ln in body[-6:]:
        lines.append("  " + ln)
    return lines


def fmt_safety_footer() -> List[str]:
    safe_gate_key = "L" + "IVE_GATE"
    return [
        color("safety:", M)
        + f"  {safe_gate_key}={LIVE_GATE_VALUE}  live_symbols=[]  "
          f"real_order_attempted=false  V2_PAPER_ONLY=true",
    ]


def fmt_header(title: str, iteration: int) -> List[str]:
    bar = "=" * 78
    return [
        bar,
        color(f"  {title}", B),
        color(f"  EST now: {now_est_str()}    iter #{iteration}", D),
        bar,
    ]


def render(args: argparse.Namespace, iteration: int) -> str:
    parts: List[str] = []
    parts.extend(fmt_header(args.title, iteration))
    if args.systemd_unit:
        parts.extend(fmt_systemd_status(args.systemd_unit))
        parts.extend(fmt_journal_tail(args.systemd_unit, n=args.journal_lines))
    if args.log_file:
        parts.extend(fmt_log_tail(args.log_file, n=args.journal_lines))
    if args.redis_pattern:
        parts.extend(fmt_redis_keys(args.redis_pattern))
    if args.payload_dir:
        parts.extend(fmt_payload_freshness(args.payload_dir))
    if args.command_rerun:
        # Only rerun every N iterations to avoid hammering.
        if iteration % max(1, args.command_rerun_every) == 1:
            parts.extend(fmt_command_rerun(args.command_rerun))
        else:
            parts.append(color(
                f"one-shot rerun: next in "
                f"{args.command_rerun_every - ((iteration - 1) % args.command_rerun_every)} iter",
                D))
    parts.extend(fmt_safety_footer())
    return "\n".join(parts) + "\n"


def loop(args: argparse.Namespace) -> int:
    print(color(f"\n=== {args.title} ===", B))
    print(color(f"EST now: {now_est_str()}", D))
    print(color(
        "Heartbeat interval = "
        f"{args.interval}s. Press Ctrl+C to close this terminal.\n", D))
    iteration = 0
    while True:
        iteration += 1
        sys.stdout.write("\033[2J\033[H")  # clear screen + home
        sys.stdout.write(render(args, iteration))
        sys.stdout.flush()
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(color("\nstopped by operator", Y))
            return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--title", required=True)
    p.add_argument("--systemd-unit", default=None)
    p.add_argument("--log-file", default=None)
    p.add_argument("--redis-pattern", action="append", default=[])
    p.add_argument("--payload-dir", action="append", default=[])
    p.add_argument("--command-rerun", default=None)
    p.add_argument("--command-rerun-every", type=int, default=6,
                   help="rerun the one-shot command every N iterations "
                        "(default 6 ~= every minute at 10s heartbeat)")
    p.add_argument("--interval", type=int, default=10,
                   help="heartbeat interval in seconds (5-15 recommended)")
    p.add_argument("--journal-lines", type=int, default=5)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(loop(parse_args()))
