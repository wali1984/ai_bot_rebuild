#!/usr/bin/env python3
"""
Trim VSCode global state.vscdb to prevent RangeError crashes.

Root cause: VSCode serializes all extension state as a single string on every
write. When openai.chatgpt prompt-history grows past ~1MB, the JS engine throws
RangeError: Invalid string length, crashing the Codex extension and losing
the ability to load chat history.

This script trims the oversized keys in place and VACUUMs the DB to reclaim
disk space. SQLite WAL mode makes it safe to run while VSCode is open.

Run via systemd timer: vscode-codex-state-trimmer.timer (every 6h + at boot).
"""

import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".local/share/vscode-codex-state-trimmer"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "trim.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)

STATE_DB = Path.home() / ".config/Code/User/globalStorage/state.vscdb"
BACKUP_SUFFIX = ".pre-auto-trim.bak"

# Thresholds
MAX_PROMPT_HISTORY_PROMPTS = 10   # per session key
MAX_PROMPT_TEXT_LEN = 500         # chars per individual prompt
MAX_KEY_SIZE_KB = 200             # keys larger than this get trimmed
CRITICAL_SIZE_KB = 800            # alarm level — extension WILL crash above ~1MB


def get_key_size(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute(
        "SELECT LENGTH(value) FROM ItemTable WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else 0


def trim_prompt_history(state: dict) -> dict:
    ph = state.get("prompt-history", {})
    if not ph:
        return state
    trimmed = {}
    for session_key, prompts in ph.items():
        if isinstance(prompts, list):
            trimmed[session_key] = [str(p)[:MAX_PROMPT_TEXT_LEN] for p in prompts[-MAX_PROMPT_HISTORY_PROMPTS:]]
        else:
            trimmed[session_key] = prompts
    state["prompt-history"] = trimmed
    return state


def trim_key(conn: sqlite3.Connection, key: str) -> tuple[int, int]:
    """Return (before_bytes, after_bytes). Returns (0, 0) if key not found."""
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    if not row:
        return 0, 0
    before = len(row[0])
    try:
        state = json.loads(row[0])
    except Exception:
        log.warning("key=%s: value is not JSON — skipping", key)
        return before, before

    state = trim_prompt_history(state)

    new_value = json.dumps(state, separators=(",", ":"))
    after = len(new_value)
    if after < before:
        conn.execute("UPDATE ItemTable SET value=? WHERE key=?", (new_value, key))
    return before, after


def run_trim() -> None:
    if not STATE_DB.exists():
        log.error("state.vscdb not found at %s — skipping", STATE_DB)
        return

    file_size_before = STATE_DB.stat().st_size

    # Backup only if file is large (>5MB) to avoid backup churn
    if file_size_before > 5 * 1024 * 1024:
        bak = STATE_DB.with_suffix(".vscdb" + BACKUP_SUFFIX)
        shutil.copy2(STATE_DB, bak)
        log.info("backup written to %s", bak)

    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    # Find all keys and their sizes
    all_keys = conn.execute(
        "SELECT key, LENGTH(value) FROM ItemTable ORDER BY LENGTH(value) DESC LIMIT 20"
    ).fetchall()

    log.info("top 5 largest keys before trim:")
    for k, sz in all_keys[:5]:
        log.info("  %-50s %6.1f KB", k, sz / 1024)

    trimmed_keys = []
    total_saved = 0

    for key, size in all_keys:
        if size > MAX_KEY_SIZE_KB * 1024:
            before, after = trim_key(conn, key)
            saved = before - after
            if saved > 0:
                total_saved += saved
                trimmed_keys.append((key, before, after))
                log.info("trimmed %-50s %6.1f KB → %5.1f KB (saved %5.1f KB)",
                         key, before / 1024, after / 1024, saved / 1024)
            # Always check if openai.chatgpt is approaching critical size
            if key == "openai.chatgpt":
                after_size = get_key_size(conn, key)
                if after_size > CRITICAL_SIZE_KB * 1024:
                    log.error(
                        "CRITICAL: openai.chatgpt state still %d KB after trim — extension may crash",
                        after_size // 1024,
                    )

    conn.commit()

    # Also specifically check openai.chatgpt even if under threshold
    oai_size = get_key_size(conn, "openai.chatgpt")
    if oai_size > 100 * 1024:  # over 100KB — trim it proactively
        before, after = trim_key(conn, "openai.chatgpt")
        saved = before - after
        if saved > 0:
            total_saved += saved
            trimmed_keys.append(("openai.chatgpt", before, after))
            log.info("proactive openai.chatgpt trim: %d KB → %d KB", before // 1024, after // 1024)
        conn.commit()

    log.info("running VACUUM to reclaim freed space...")
    conn.execute("VACUUM")
    conn.close()

    file_size_after = STATE_DB.stat().st_size
    log.info(
        "done. file: %d KB → %d KB | content saved: %d KB | keys trimmed: %d",
        file_size_before // 1024,
        file_size_after // 1024,
        total_saved // 1024,
        len(trimmed_keys),
    )

    # Write last-run stamp
    stamp_file = LOG_DIR / "last_run.txt"
    stamp_file.write_text(
        f"{datetime.utcnow().isoformat()}Z | "
        f"file {file_size_before//1024}KB→{file_size_after//1024}KB | "
        f"saved {total_saved//1024}KB\n"
    )


if __name__ == "__main__":
    log.info("VSCode state.vscdb trimmer starting — %s", datetime.utcnow().isoformat())
    try:
        run_trim()
    except Exception as exc:
        log.exception("trim failed: %s", exc)
        sys.exit(1)
