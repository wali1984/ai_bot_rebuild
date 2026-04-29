#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common_audit import ensure_allowed_file, read_text_safely, resolve_path, sha256_text, redact_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    args = ap.parse_args()

    p = resolve_path(args.file, Path.cwd())
    ensure_allowed_file(p, resolve_path("./legacy_reference", Path.cwd()))
    if args.start < 1 or args.end < args.start:
        raise SystemExit("Invalid range")

    text = read_text_safely(p)
    lines = text.splitlines()
    start = min(args.start, len(lines) if lines else 1)
    end = min(args.end, len(lines)) if lines else 0
    segment = lines[start - 1:end] if end >= start else []

    print(f"file: {p}")
    print(f"range: {start}-{end}")
    print(f"line_count: {len(segment)}")
    print(f"range_sha256: {sha256_text(chr(10).join(segment))}")
    print("verification: deterministic read-only")
    for i, line in enumerate(segment, start=start):
        print(f"{i:>8}: {redact_text(line) or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
