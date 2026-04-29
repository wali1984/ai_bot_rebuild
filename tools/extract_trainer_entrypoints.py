#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from common_audit import resolve_path, read_text_safely, write_json, evidence_record

REGEX_KEYS = [r'if\s+__name__\s*==\s*["\']__main__["\']', r'\bwhile\s+True\b']
SUBSTR_KEYS = ["argparse", "click", "typer", "main(", "train(", "run(", "loop"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainer-file", required=True)
    ap.add_argument("--out-dir", default="./claude_worklog/trainer_atlas")
    args = ap.parse_args()

    t = resolve_path(args.trainer_file, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    txt = read_text_safely(t, max_bytes=200_000_000)

    matches = []
    for i, line in enumerate(txt.splitlines(), start=1):
        hit = None
        for k in REGEX_KEYS:
            if re.search(k, line, re.I):
                hit = k
                break
        if hit is None:
            low = line.lower()
            for k in SUBSTR_KEYS:
                if k.lower() in low:
                    hit = k
                    break
        if hit is not None:
            matches.append({
                "line": i,
                "keyword": hit,
                "text": line.strip()[:500],
                "evidence": evidence_record(str(t), i, line.strip()[:300], "entrypoint", "trainer entrypoint keyword"),
            })

    write_json(out / "HYBRID_TRAINER_RUNTIME_ENTRYPOINTS.json", {"matches": matches})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
