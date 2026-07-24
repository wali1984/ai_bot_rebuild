#!/usr/bin/env python3
"""Non-invasive performance baseline for the native trainer cycle.

Captures the current genesis-rooted-manifest full-scan cost so the future
instant-shard (incremental manifest-head) migration can be proven equivalent AND
faster. Reads /proc for the trainer PID + the runtime status files + Redis; it
NEVER modifies the trainer, the archive, or any provenance path.

Metrics captured over a bounded observation window:
  * cycle wall time (scan time)   -- delta between trainer status_generated_at writes
  * rows scanned                  -- durable feature-snapshot ledger population +
                                     champion/challenger replay_snapshots_scanned
  * CPU% and RSS (RAM)            -- sampled from /proc/<pid>/{stat,status}
  * publication latency           -- base publisher cycle_elapsed_seconds

Usage:
  tools/trainer_cycle_perf_baseline.py [--window-seconds 180] [--interval 2]
                                       [--report-path <json>]
Exit 0 always (measurement only). Prints a JSON report and writes it to
claude_worklog/trainer_perf/ by default.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "ai-bot-v2-native-cuda-trainer-persistent.service"
TRAINER_STATUS = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json"
)
PUBLISHER_STATUS = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled_base_publisher_status_v1.json"
)
LEDGER = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3"
)
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _main_pid() -> int | None:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", SERVICE, "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=15,
        )
        pid = int(r.stdout.strip())
        return pid if pid > 0 else None
    except Exception:
        return None


def _proc_cpu_ticks_and_rss(pid: int) -> tuple[int, int] | None:
    """Return (utime+stime ticks, rss_bytes) for pid, or None if gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # fields after the (comm) which may contain spaces/parens
        rparen = stat.rfind(")")
        fields = stat[rparen + 2 :].split()
        utime = int(fields[11])  # field 14 overall (0-indexed after comm shift)
        stime = int(fields[12])
        rss_pages = int(fields[21])
        return utime + stime, rss_pages * PAGE_SIZE
    except Exception:
        return None


def _ledger_row_count() -> int | None:
    try:
        con = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=5)
        try:
            (n,) = con.execute("SELECT COUNT(*) FROM feature_snapshot_records").fetchone()
            return int(n)
        finally:
            con.close()
    except Exception:
        return None  # transient torn-read window; retried by caller


def _redis_scan_count() -> dict:
    try:
        import redis  # local import; absent-safe
        r = redis.Redis(decode_responses=True)
        cc = json.loads(r.get("v2:trainer:champion_challenger_status") or "{}")
        return {
            "replay_snapshots_scanned": cc.get("replay_snapshots_scanned"),
            "replay_windows_processed": cc.get("replay_windows_processed"),
            "champion_challenger_train_rows": (cc.get("backtests_processed") or {}).get("train_rows"),
        }
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window-seconds", type=float, default=180.0)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--report-path", type=Path, default=None)
    args = ap.parse_args()

    pid = _main_pid()
    if pid is None:
        print(json.dumps({"error": "trainer_service_not_running"}))
        return 0

    cmdline = ""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except Exception:
        pass
    release = next((p for p in cmdline.split() if "ai_bot_rebuild/" in p), "")

    # cycle-boundary + resource sampling loop
    cpu_pct_samples: list[float] = []
    rss_samples: list[int] = []
    status_write_times: list[float] = []  # monotonic times we saw a new status_generated_at
    seen_status_stamp: str | None = None
    ledger_counts: list[int] = []

    prev = _proc_cpu_ticks_and_rss(pid)
    prev_wall = time.monotonic()
    t_end = time.monotonic() + args.window_seconds
    while time.monotonic() < t_end:
        time.sleep(args.interval)
        cur = _proc_cpu_ticks_and_rss(pid)
        now = time.monotonic()
        if prev is not None and cur is not None:
            dticks = cur[0] - prev[0]
            dwall = now - prev_wall
            if dwall > 0:
                cpu_pct_samples.append(100.0 * (dticks / CLK_TCK) / dwall)
            rss_samples.append(cur[1])
        prev, prev_wall = cur, now

        st = _load_json(TRAINER_STATUS)
        stamp = st.get("status_generated_at")
        if stamp and stamp != seen_status_stamp:
            seen_status_stamp = stamp
            status_write_times.append(now)
        n = _ledger_row_count()
        if n is not None:
            ledger_counts.append(n)

    # derive cycle wall times from consecutive status writes
    cycle_wall_times = [
        round(status_write_times[i] - status_write_times[i - 1], 2)
        for i in range(1, len(status_write_times))
    ]

    pub = _load_json(PUBLISHER_STATUS)
    trainer = _load_json(TRAINER_STATUS)
    report = {
        "schema": "trainer_cycle_perf_baseline_v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "window_seconds": args.window_seconds,
        "trainer_pid": pid,
        "trainer_release": release,
        "trainer_classification": trainer.get("classification"),
        "cuda_runtime": trainer.get("cuda_runtime"),
        "scan_time": {
            "note": "wall time between consecutive trainer status writes (full-scan cadence)",
            "cycle_wall_times_seconds": cycle_wall_times,
            "median_cycle_seconds": round(statistics.median(cycle_wall_times), 2) if cycle_wall_times else None,
            "status_writes_observed": len(status_write_times),
        },
        "rows_scanned": {
            "durable_ledger_records": max(ledger_counts) if ledger_counts else None,
            "durable_ledger_samples": len(ledger_counts),
            **_redis_scan_count(),
        },
        "cpu": {
            "peak_pct": round(max(cpu_pct_samples), 1) if cpu_pct_samples else None,
            "mean_pct": round(statistics.mean(cpu_pct_samples), 1) if cpu_pct_samples else None,
            "samples": len(cpu_pct_samples),
        },
        "ram": {
            "peak_rss_mb": round(max(rss_samples) / 1e6, 1) if rss_samples else None,
            "mean_rss_mb": round(statistics.mean(rss_samples) / 1e6, 1) if rss_samples else None,
        },
        "publication_latency": {
            "base_publisher_cycle_elapsed_seconds": pub.get("cycle_elapsed_seconds"),
            "base_publisher_cycle_period_seconds": pub.get("cycle_period_seconds"),
            "base_publisher_published_symbol_count": pub.get("published_symbol_count"),
            "note": "published_symbol_count=0 while WSS window rebuilds; latency is publish-cycle wall time",
        },
    }

    out = args.report_path or Path(
        "/home/wali/Desktop/AI BOT REBUILD/claude_worklog/trainer_perf/"
        f"cycle_baseline_{int(status_write_times[0]) if status_write_times else 0}.json"
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        report["report_written_to"] = str(out)
    except Exception as exc:  # noqa: BLE001
        report["report_write_error"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
