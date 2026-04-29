#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path
from common_audit import resolve_path, read_text_safely, write_json, verification_command


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainer-file", required=True)
    ap.add_argument("--out-dir", default="./claude_worklog/trainer_atlas")
    args = ap.parse_args()
    t = resolve_path(args.trainer_file, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    text = read_text_safely(t, max_bytes=200_000_000)
    imports = []
    try:
        tree = ast.parse(text)
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imports.append({"module": a.name, "line": n.lineno, "verification_command": verification_command(str(t), n.lineno, n.lineno+1)})
            elif isinstance(n, ast.ImportFrom):
                imports.append({"module": n.module, "names": [a.name for a in n.names], "line": n.lineno, "verification_command": verification_command(str(t), n.lineno, n.lineno+1)})
    except Exception as e:
        imports.append({"error": str(e)})
    write_json(out / "HYBRID_TRAINER_IMPORT_GRAPH.json", {"imports": imports})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
