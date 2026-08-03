"""
Memory pressure watchdog — logs warnings and writes a status file.
Runs as a persistent service, checks every 30s.
Does NOT kill processes; raises alarms only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "v2_memory_watchdog" / "latest"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATUS_PATH = OUT_DIR / "memory_watchdog_status.json"

WARN_AVAILABLE_GB = 10.0
CRIT_AVAILABLE_GB = 5.0
CHECK_INTERVAL = 30


def read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            info[key] = int(parts[1])
    return info


def top_python_procs(n: int = 5) -> list[dict]:
    try:
        out = subprocess.check_output(
            ["ps", "aux", "--sort=-%mem"],
            text=True, timeout=5
        )
        rows = []
        for line in out.splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            cmd = parts[10]
            if "python" in cmd or "python3" in cmd:
                rows.append({
                    "pid": int(parts[1]),
                    "cpu_pct": float(parts[2]),
                    "mem_pct": float(parts[3]),
                    "rss_kb": int(parts[5]),
                    "cmd": cmd[:120],
                })
            if len(rows) >= n:
                break
        return rows
    except Exception:
        return []


def check_once() -> dict:
    mem = read_meminfo()
    total_kb = mem.get("MemTotal", 1)
    avail_kb = mem.get("MemAvailable", 0)
    swap_total_kb = mem.get("SwapTotal", 0)
    swap_free_kb = mem.get("SwapFree", 0)

    avail_gb = avail_kb / 1024 / 1024
    total_gb = total_kb / 1024 / 1024
    swap_used_gb = (swap_total_kb - swap_free_kb) / 1024 / 1024
    swap_total_gb = swap_total_kb / 1024 / 1024

    level = "ok"
    if avail_gb < CRIT_AVAILABLE_GB:
        level = "critical"
    elif avail_gb < WARN_AVAILABLE_GB:
        level = "warning"

    top = top_python_procs(5) if level != "ok" else []

    status = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "available_gb": round(avail_gb, 2),
        "total_gb": round(total_gb, 2),
        "swap_used_gb": round(swap_used_gb, 2),
        "swap_total_gb": round(swap_total_gb, 2),
        "top_python_procs": top,
    }

    STATUS_PATH.write_text(json.dumps(status, indent=2))

    if level == "critical":
        print(
            f"[CRITICAL] {datetime.now().isoformat()} "
            f"available={avail_gb:.1f}GB swap_used={swap_used_gb:.1f}GB",
            flush=True,
        )
        for p in top:
            print(
                f"  PID {p['pid']} mem={p['mem_pct']}% "
                f"rss={p['rss_kb']//1024}MB {p['cmd'][:80]}",
                flush=True,
            )
    elif level == "warning":
        print(
            f"[WARN] {datetime.now().isoformat()} "
            f"available={avail_gb:.1f}GB",
            flush=True,
        )

    return status


if __name__ == "__main__":
    print(f"Memory watchdog started (warn<{WARN_AVAILABLE_GB}GB crit<{CRIT_AVAILABLE_GB}GB)", flush=True)
    while True:
        try:
            check_once()
        except Exception as exc:
            print(f"[ERROR] watchdog check failed: {exc}", flush=True)
        time.sleep(CHECK_INTERVAL)
