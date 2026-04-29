#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, evidence_record, redact_text

TOKENS = [
    "redis", "Redis", "xadd", "xread", "xrevrange", "xlen", "hgetall", "hset", "set(", "get(",
    "publish", "subscribe", "signals:trading", "executed_signals", "positions:", "portfolio:",
    "trainer", "heartbeat", "risk", "halt",
]
WRITE_HINTS = ["xadd", "hset", "set(", "publish", "delete", "xdel", "xtrim", "lpush", "rpush", "sadd", "zadd"]
READ_HINTS = ["xread", "xrevrange", "xlen", "hgetall", "get(", "subscribe"]


def classify(line: str) -> str:
    l = line.lower()
    if any(t in l for t in WRITE_HINTS):
        return "redis_write"
    if any(t in l for t in READ_HINTS):
        return "redis_read"
    return "redis_unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    token_rx = re.compile("|".join(re.escape(t) for t in TOKENS), re.IGNORECASE)
    matches = []
    per_file = {}

    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        if f.suffix.lower() not in {".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".md", ".toml", ".ini", ".cfg"}:
            continue
        try:
            text = read_text_safely(f)
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if token_rx.search(line):
                c = classify(line)
                item = {
                    "file": rel,
                    "line": i,
                    "classification": c,
                    "text": (redact_text(line.strip()[:500]) or ""),
                    "evidence": evidence_record(f"./legacy_reference/{rel}", i, line.strip()[:400], c, "redis token match"),
                }
                matches.append(item)
                per_file.setdefault(rel, {"redis_read": 0, "redis_write": 0, "redis_unknown": 0})
                per_file[rel][c] += 1

    data = {
        "matches": matches,
        "files": [{"file": k, **v} for k, v in sorted(per_file.items())],
        "writer_files": [k for k, v in per_file.items() if v.get("redis_write", 0) > 0],
    }
    write_json(out / "REDIS_USAGE_MAP.json", data)

    md = ["# Redis Key/Stream Usage Map", "", f"Total matches: {len(matches)}", f"Writer files: {len(data['writer_files'])}", "", "| file | read | write | unknown |", "|---|---:|---:|---:|"]
    for f, v in sorted(per_file.items()):
        md.append(f"| {f} | {v.get('redis_read',0)} | {v.get('redis_write',0)} | {v.get('redis_unknown',0)} |")
    write_markdown(out / "REDIS_KEY_STREAM_MAP.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
