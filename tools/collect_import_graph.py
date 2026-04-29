#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from common_audit import iter_files, read_text_safely, relative_to, resolve_path, write_json, write_markdown, verification_command

JS_RE = [
    ("import", re.compile(r"\bimport\s+.+?from\s+['\"]([^'\"]+)['\"]")),
    ("require", re.compile(r"\brequire\(['\"]([^'\"]+)['\"]\)")),
    ("export", re.compile(r"\bexport\s+")),
]


def parse_python(path: Path, rel: str):
    text = read_text_safely(path)
    imports, from_imports, funcs, classes, exec_calls = [], [], [], [], []
    has_main = False
    argparse_use = click_use = typer_use = False
    try:
        tree = ast.parse(text)
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imports.append({"name": a.name, "line": n.lineno})
                    if a.name in {"argparse", "click", "typer"}:
                        argparse_use |= a.name == "argparse"
                        click_use |= a.name == "click"
                        typer_use |= a.name == "typer"
            elif isinstance(n, ast.ImportFrom):
                from_imports.append({"module": n.module, "names": [a.name for a in n.names], "line": n.lineno})
                if n.module in {"argparse", "click", "typer"}:
                    argparse_use |= n.module == "argparse"
                    click_use |= n.module == "click"
                    typer_use |= n.module == "typer"
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append({"name": n.name, "line_start": n.lineno, "line_end": getattr(n, "end_lineno", n.lineno)})
            elif isinstance(n, ast.ClassDef):
                classes.append({"name": n.name, "line_start": n.lineno, "line_end": getattr(n, "end_lineno", n.lineno)})
            elif isinstance(n, ast.Call):
                fn = ""
                if isinstance(n.func, ast.Attribute):
                    fn = f"{getattr(n.func.value,'id','')}.{n.func.attr}".strip(".")
                elif isinstance(n.func, ast.Name):
                    fn = n.func.id
                if fn in {"subprocess.run", "subprocess.Popen", "os.system", "system"}:
                    exec_calls.append({"call": fn, "line": n.lineno})
            elif isinstance(n, ast.If):
                try:
                    if (
                        isinstance(n.test, ast.Compare)
                        and isinstance(n.test.left, ast.Name)
                        and n.test.left.id == "__name__"
                        and any(isinstance(op, ast.Eq) for op in n.test.ops)
                        and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in n.test.comparators)
                    ):
                        has_main = True
                except Exception:
                    pass
    except Exception as e:
        return {"file": rel, "parse_error": str(e), "imports": [], "from_imports": [], "functions": [], "classes": [], "has_main_entrypoint": False, "argparse": False, "click": False, "typer": False, "exec_calls": []}

    return {
        "file": rel,
        "imports": imports,
        "from_imports": from_imports,
        "functions": funcs,
        "classes": classes,
        "has_main_entrypoint": has_main,
        "argparse": argparse_use,
        "click": click_use,
        "typer": typer_use,
        "exec_calls": exec_calls,
        "verification_command": verification_command(f"./legacy_reference/{rel}", 1, 50),
    }


def parse_js(path: Path, rel: str):
    text = read_text_safely(path)
    refs = []
    for i, line in enumerate(text.splitlines(), start=1):
        for kind, rx in JS_RE:
            m = rx.search(line)
            if m:
                refs.append({"line": i, "kind": kind, "text": line.strip()[:400]})
    return {"file": rel, "references": refs, "verification_command": verification_command(f"./legacy_reference/{rel}", 1, 40)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", default="./legacy_reference")
    ap.add_argument("--out-dir", default="./claude_worklog/coverage")
    args = ap.parse_args()
    legacy = resolve_path(args.legacy_root, Path.cwd())
    out = resolve_path(args.out_dir, Path.cwd())
    out.mkdir(parents=True, exist_ok=True)

    py, js = [], []
    for f in iter_files(legacy):
        rel = relative_to(legacy, f)
        if f.suffix.lower() == ".py":
            py.append(parse_python(f, rel))
        elif f.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            js.append(parse_js(f, rel))

    data = {"python_files": py, "js_ts_files": js}
    write_json(out / "IMPORT_GRAPH.json", data)

    md = ["# Import Graph", "", f"- python files: {len(py)}", f"- js/ts files: {len(js)}", "", "## Python summary", ""]
    for item in py[:150]:
        md.append(f"- {item['file']}: imports={len(item.get('imports',[]))}, from_imports={len(item.get('from_imports',[]))}, functions={len(item.get('functions',[]))}, classes={len(item.get('classes',[]))}, main={item.get('has_main_entrypoint',False)}")
    write_markdown(out / "IMPORT_GRAPH.md", "\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
