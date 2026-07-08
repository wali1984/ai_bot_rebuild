"""
Disk retention janitor — enforces bounded disk usage for V2 runtime data.

Non-live, deletes only machine-generated capture/cache data under the repo:
  1. orderbook_replay day-directories older than KEEP_DAYS (never today's).
  2. Extra day-directories (oldest first) when root-fs free space is below
     FLOOR_FREE_GB, until TARGET_FREE_GB is reached.
  3. Unbounded append-only JSONL feeds: atomically keep the newest tail once
     a file exceeds its cap.
  4. Held-open .out logs: truncate in place (safe with O_APPEND writers).

Runs as a systemd user timer (ai-bot-v2-disk-retention-janitor.timer).
Writes a status JSON for the GUI/system-health surfaces and prints one
compact summary line per run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REPLAY_ROOT = REPO_ROOT / "v2" / "runtime" / "orderbook_replay"
KEEP_DAYS = 5  # keep today + previous KEEP_DAYS-1 day dirs per symbol
MAX_REPLAY_TOTAL_GB = 500.0  # hard cap; prune oldest symbol-days over this

FLOOR_FREE_GB = 150.0   # below this, prune extra oldest day dirs
TARGET_FREE_GB = 250.0  # prune until at least this much is free

# Append-only feeds that grow without bound: (glob-root, pattern, cap, keep-tail)
GB = 1024 ** 3
TAIL_CAP_TARGETS: list[tuple[Path, str, int, int]] = [
    (
        REPO_ROOT / "v2" / "legacy_owned_runtime" / "data" / "live" / "general",
        "*.jsonl",
        4 * GB,
        1 * GB,
    ),
    (
        REPO_ROOT / "v2" / "backend",
        "market_stream_alert_history.jsonl",
        2 * GB,
        512 * 1024 * 1024,
    ),
]

# Long-running process logs held open with O_APPEND: truncate to zero over cap.
TRUNCATE_TARGETS: list[tuple[Path, str, int]] = [
    (
        REPO_ROOT / "v2" / "runtime" / "microstructure_runtime_supervisor",
        "*.out",
        1 * GB,
    ),
]

STATUS_DIR = REPO_ROOT / "claude_worklog" / "disk_janitor"
STATUS_PATH = STATUS_DIR / "disk_janitor_status.json"

DAY_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def free_gb(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / GB


def _day_dirs() -> list[tuple[date, Path]]:
    """All (date, path) day-directories under REPLAY_ROOT/<exchange>/<symbol>/."""
    found: list[tuple[date, Path]] = []
    if not REPLAY_ROOT.is_dir():
        return found
    for exchange in REPLAY_ROOT.iterdir():
        if not exchange.is_dir() or exchange.is_symlink():
            continue
        for symbol in exchange.iterdir():
            if not symbol.is_dir() or symbol.is_symlink():
                continue
            for day in symbol.iterdir():
                if not day.is_dir() or day.is_symlink():
                    continue
                if not DAY_DIR_RE.match(day.name):
                    continue
                try:
                    parsed = datetime.strptime(day.name, "%Y-%m-%d").date()
                except ValueError:
                    continue
                found.append((parsed, day))
    return found


def _rmtree(path: Path, dry_run: bool) -> int:
    size = 0
    for f in path.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                size += f.lstat().st_size
        except OSError:
            continue
    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)
    return size


def prune_by_age(dry_run: bool) -> tuple[int, int]:
    cutoff = date.today() - timedelta(days=KEEP_DAYS - 1)
    deleted = 0
    freed = 0
    for parsed, day_path in _day_dirs():
        if parsed < cutoff:
            freed += _rmtree(day_path, dry_run)
            deleted += 1
    return deleted, freed


def _dir_size(path: Path) -> int:
    size = 0
    for f in path.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                size += f.lstat().st_size
        except OSError:
            continue
    return size


def prune_for_total_cap(dry_run: bool) -> tuple[int, int]:
    """Keep the whole replay store under MAX_REPLAY_TOTAL_GB (oldest first)."""
    deleted = 0
    freed = 0
    today = date.today()
    sized = [
        (parsed, path, _dir_size(path))
        for parsed, path in _day_dirs()
    ]
    total = sum(size for _, _, size in sized)
    cap_bytes = int(MAX_REPLAY_TOTAL_GB * GB)
    if total <= cap_bytes:
        return deleted, freed
    for parsed, path, size in sorted(sized, key=lambda item: item[0]):
        if parsed >= today or total <= cap_bytes:
            continue
        if not dry_run:
            shutil.rmtree(path, ignore_errors=True)
        total -= size
        freed += size
        deleted += 1
    return deleted, freed


def prune_for_floor(dry_run: bool) -> tuple[int, int]:
    deleted = 0
    freed = 0
    if free_gb(REPO_ROOT) >= FLOOR_FREE_GB:
        return deleted, freed
    today = date.today()
    candidates = sorted(
        (item for item in _day_dirs() if item[0] < today),
        key=lambda item: item[0],
    )
    for _, day_path in candidates:
        if free_gb(REPO_ROOT) >= TARGET_FREE_GB:
            break
        freed += _rmtree(day_path, dry_run)
        deleted += 1
    return deleted, freed


def tail_cap_file(path: Path, keep_bytes: int, dry_run: bool) -> int:
    """Atomically replace an oversized JSONL with its newest tail."""
    size = path.lstat().st_size
    if dry_run:
        return size - keep_bytes
    with path.open("rb") as src:
        src.seek(max(0, size - keep_bytes))
        chunk = src.read(1024 * 1024)
        newline = chunk.find(b"\n")
        skip = newline + 1 if newline >= 0 else 0
        src.seek(max(0, size - keep_bytes) + skip)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
        try:
            with os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    return size - path.lstat().st_size


def run_tail_caps(dry_run: bool) -> tuple[int, int]:
    capped = 0
    freed = 0
    for root, pattern, cap, keep in TAIL_CAP_TARGETS:
        if not root.is_dir():
            continue
        for path in root.glob(pattern):
            if not path.is_file() or path.is_symlink():
                continue
            if path.lstat().st_size > cap:
                freed += max(0, tail_cap_file(path, keep, dry_run))
                capped += 1
    return capped, freed


def run_truncations(dry_run: bool) -> tuple[int, int]:
    truncated = 0
    freed = 0
    for root, pattern, cap in TRUNCATE_TARGETS:
        if not root.is_dir():
            continue
        for path in root.glob(pattern):
            if not path.is_file() or path.is_symlink():
                continue
            size = path.lstat().st_size
            if size > cap:
                if not dry_run:
                    os.truncate(path, 0)
                freed += size
                truncated += 1
    return truncated, freed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    started = time.time()
    free_before = free_gb(REPO_ROOT)

    aged_dirs, aged_bytes = prune_by_age(args.dry_run)
    cap_dirs, cap_bytes = prune_for_total_cap(args.dry_run)
    floor_dirs, floor_bytes = prune_for_floor(args.dry_run)
    capped_files, capped_bytes = run_tail_caps(args.dry_run)
    truncated_files, truncated_bytes = run_truncations(args.dry_run)

    status = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "free_gb_before": round(free_before, 1),
        "free_gb_after": round(free_gb(REPO_ROOT), 1),
        "replay_day_dirs_deleted_by_age": aged_dirs,
        "replay_day_dirs_deleted_for_total_cap": cap_dirs,
        "replay_day_dirs_deleted_for_floor": floor_dirs,
        "jsonl_files_tail_capped": capped_files,
        "out_files_truncated": truncated_files,
        "bytes_reclaimed": aged_bytes + cap_bytes + floor_bytes + capped_bytes + truncated_bytes,
        "duration_seconds": round(time.time() - started, 1),
        "config": {
            "keep_days": KEEP_DAYS,
            "max_replay_total_gb": MAX_REPLAY_TOTAL_GB,
            "floor_free_gb": FLOOR_FREE_GB,
            "target_free_gb": TARGET_FREE_GB,
        },
    }

    if not args.dry_run:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(status, indent=2))

    print(json.dumps(status, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
