#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, evidence_record, redact_text

REDIS_METHODS = [
    "xadd", "xread", "xrevrange", "xlen", "hgetall", "hset", "set", "get",
    "publish", "subscribe", "delete", "xdel", "xtrim", "lpush", "rpush", "sadd", "zadd",
    "expire", "hincrby", "exists", "setex", "incr", "decr", "smembers",
]
REDIS_KEY_HINTS = ["signals:trading", "executed_signals", "positions:", "portfolio:", "heartbeat:"]
REDIS_VAR_METHOD_RE = re.compile(
    r"\b(?:self\.)?[A-Za-z_][A-Za-z0-9_]*redis[A-Za-z0-9_]*\s*\.\s*(?:"
    + "|".join(REDIS_METHODS)
    + r")\s*\(",
    re.IGNORECASE,
)
REDIS_SHORT_VAR_RE = re.compile(
    r"\b(?:r|rc|pipe|pipeline)\s*\.\s*(?:"
    + "|".join(REDIS_METHODS)
    + r")\s*\(",
    re.IGNORECASE,
)

WRITE_HINTS = ["xadd", "hset", "set", "publish", "delete", "xdel", "xtrim", "lpush", "rpush", "sadd", "zadd", "expire", "hincrby", "setex", "incr", "decr"]
READ_HINTS = ["xread", "xrevrange", "xlen", "hgetall", "get", "subscribe", "exists", "smembers"]


def classify(line: str) -> str:
    l = line.lower()
    if any(f".{t}(" in l for t in WRITE_HINTS):
        return "redis_write"
    if any(f".{t}(" in l for t in READ_HINTS):
        return "redis_read"
    return "redis_unknown"


def is_redis_line(line: str) -> bool:
    if REDIS_VAR_METHOD_RE.search(line) or REDIS_SHORT_VAR_RE.search(line):
        return True
    line_l = line.lower()
    return any(k in line_l for k in REDIS_KEY_HINTS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

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
            if is_redis_line(line):
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
