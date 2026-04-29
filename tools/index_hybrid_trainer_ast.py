#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from common_audit import resolve_path, read_text_safely, write_json, verification_command


def ast_index(text: str):
    funcs, classes, imports = [], [], []
    tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append({"name": n.name, "line_start": n.lineno, "line_end": getattr(n, "end_lineno", n.lineno)})
        elif isinstance(n, ast.ClassDef):
            classes.append({"name": n.name, "line_start": n.lineno, "line_end": getattr(n, "end_lineno", n.lineno)})
        elif isinstance(n, ast.Import):
            for a in n.names:
                imports.append({"module": a.name, "line": n.lineno})
        elif isinstance(n, ast.ImportFrom):
            imports.append({"module": n.module, "names": [a.name for a in n.names], "line": n.lineno})
    return funcs, classes, imports


def regex_index(text: str):
    funcs, classes, imports = [], [], []
    for i, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if m:
            funcs.append({"name": m.group(1), "line_start": i, "line_end": i})
        m = re.match(r"\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if m:
            classes.append({"name": m.group(1), "line_start": i, "line_end": i})
        m = re.match(r"\s*import\s+(.+)", line)
        if m:
            imports.append({"module": m.group(1).strip(), "line": i})
        m = re.match(r"\s*from\s+([\w\.]+)\s+import\s+(.+)", line)
        if m:
            imports.append({"module": m.group(1), "names": [x.strip() for x in m.group(2).split(',')], "line": i})
    return funcs, classes, imports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainer-file", required=True)
    ap.add_argument("--out-dir", default="./claude_worklog/trainer_atlas")
    args = ap.parse_args()

    trainer = resolve_path(args.trainer_file, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    text = read_text_safely(trainer, max_bytes=200_000_000)
    mode = "ast"
    fallback_reason = ""
    try:
        funcs, classes, imports = ast_index(text)
    except Exception as e:
        mode = "regex_fallback"
        fallback_reason = str(e)
        funcs, classes, imports = regex_index(text)

    for x in funcs:
        x["verification_command"] = verification_command(str(trainer), x["line_start"], x["line_end"])
    for x in classes:
        x["verification_command"] = verification_command(str(trainer), x["line_start"], x["line_end"])
    for x in imports:
        x["verification_command"] = verification_command(str(trainer), x["line"], x["line"] + 1)

    write_json(out / "HYBRID_TRAINER_FUNCTION_INDEX.json", {"mode": mode, "fallback_reason": fallback_reason, "functions": funcs})
    write_json(out / "HYBRID_TRAINER_CLASS_INDEX.json", {"mode": mode, "fallback_reason": fallback_reason, "classes": classes})
    write_json(out / "HYBRID_TRAINER_IMPORT_GRAPH.json", {"mode": mode, "fallback_reason": fallback_reason, "imports": imports})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
