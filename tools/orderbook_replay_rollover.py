#!/usr/bin/env python3
"""Orderbook replay data rollover - maintains 100GB cap with FIFO deletion of oldest data."""

import os
import shutil
import sys
from pathlib import Path
from datetime import datetime

ORDERBOOK_REPLAY_PATH = Path("/home/wali/Desktop/AI BOT REBUILD/v2/runtime/orderbook_replay")
MAX_SIZE_GB = 100
MAX_SIZE_BYTES = MAX_SIZE_GB * 1024**3

def get_directory_size(path: Path) -> int:
    """Recursively calculate directory size in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except (OSError, PermissionError):
        pass
    return total

def get_oldest_date_dirs():
    """Get list of (mtime, path) for date directories, oldest first."""
    date_dirs = []
    binance_path = ORDERBOOK_REPLAY_PATH / "binance"
    if not binance_path.exists():
        return date_dirs

    for symbol_dir in binance_path.iterdir():
        if not symbol_dir.is_dir():
            continue
        for date_dir in symbol_dir.iterdir():
            if not date_dir.is_dir():
                continue
            try:
                mtime = date_dir.stat().st_mtime
                date_dirs.append((mtime, date_dir))
            except (OSError, PermissionError):
                pass

    return sorted(date_dirs)  # oldest first

def rollover():
    """Delete oldest data until orderbook_replay is <= 100GB."""
    if not ORDERBOOK_REPLAY_PATH.exists():
        print("orderbook_replay not found")
        return

    current_size = get_directory_size(ORDERBOOK_REPLAY_PATH)
    print(f"Current size: {current_size / 1024**3:.1f}GB")

    if current_size <= MAX_SIZE_BYTES:
        print(f"Size OK (under {MAX_SIZE_GB}GB limit)")
        return

    print(f"Over limit! Need to free {(current_size - MAX_SIZE_BYTES) / 1024**3:.1f}GB")

    date_dirs = get_oldest_date_dirs()
    deleted_count = 0
    freed_bytes = 0

    for mtime, date_dir in date_dirs:
        if current_size <= MAX_SIZE_BYTES:
            break

        try:
            size_before = get_directory_size(date_dir)
            shutil.rmtree(date_dir)
            freed = size_before
            freed_bytes += freed
            current_size -= freed
            deleted_count += 1

            mtime_str = datetime.fromtimestamp(mtime).isoformat()
            print(f"Deleted {date_dir.relative_to(ORDERBOOK_REPLAY_PATH)} ({freed / 1024**3:.1f}GB) from {mtime_str}")
        except (OSError, PermissionError) as e:
            print(f"Failed to delete {date_dir}: {e}")

    final_size = get_directory_size(ORDERBOOK_REPLAY_PATH)
    print(f"\nFinal size: {final_size / 1024**3:.1f}GB (freed {freed_bytes / 1024**3:.1f}GB, deleted {deleted_count} date dirs)")

if __name__ == "__main__":
    rollover()
