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
    """Get (date_name, mtime, path) for date dirs across ALL exchanges, oldest first.

    Real layout is orderbook_replay/{exchange}/{symbol}/{date}/. The previous
    version only walked binance/ (whose symbols are empty) and never touched
    kucoin/ — where ~all the data lives — so it deleted nothing while over cap.

    Never returns the current UTC day so active writes are not disrupted; FIFO
    deletes the oldest calendar day first across every exchange/symbol.
    """
    date_dirs = []
    if not ORDERBOOK_REPLAY_PATH.exists():
        return date_dirs

    today = datetime.utcnow().strftime("%Y-%m-%d")
    for exchange_dir in ORDERBOOK_REPLAY_PATH.iterdir():
        if not exchange_dir.is_dir():
            continue
        for symbol_dir in exchange_dir.iterdir():
            if not symbol_dir.is_dir():
                continue
            for date_dir in symbol_dir.iterdir():
                if not date_dir.is_dir() or date_dir.name >= today:
                    continue
                try:
                    mtime = date_dir.stat().st_mtime
                    # Sort by date-dir NAME (YYYY-MM-DD) so the oldest calendar
                    # day is purged first across all symbols, mtime as tiebreak.
                    date_dirs.append((date_dir.name, mtime, date_dir))
                except (OSError, PermissionError):
                    pass

    return sorted(date_dirs)  # oldest date-name first

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

    for date_name, mtime, date_dir in date_dirs:
        if current_size <= MAX_SIZE_BYTES:
            break

        try:
            size_before = get_directory_size(date_dir)
            shutil.rmtree(date_dir)
            freed = size_before
            freed_bytes += freed
            current_size -= freed
            deleted_count += 1

            print(f"Deleted {date_dir.relative_to(ORDERBOOK_REPLAY_PATH)} ({freed / 1024**3:.1f}GB) [{date_name}]")
        except (OSError, PermissionError) as e:
            print(f"Failed to delete {date_dir}: {e}")

    final_size = get_directory_size(ORDERBOOK_REPLAY_PATH)
    print(f"\nFinal size: {final_size / 1024**3:.1f}GB (freed {freed_bytes / 1024**3:.1f}GB, deleted {deleted_count} date dirs)")

if __name__ == "__main__":
    rollover()
