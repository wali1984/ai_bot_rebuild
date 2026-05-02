"""Orphan path check.

Verifies the materialized tree is internally consistent:
  - every directory under v2/backend/app and v2/backend/tests has either an
    __init__.py or a .gitkeep sentinel (no orphan dirs)
  - no compiled bytecode (__pycache__, *.pyc) is committed
  - no editor backup files (*.bak, *.swp, *.orig) under v2/

This is intentionally conservative — it catches obvious materialization
artifacts (committed __pycache__, missing __init__.py) without forcing every
stub to be imported by app.main yet.

Advisory until milestone C; promote to FAIL with `ORPHAN_MANDATORY=1`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
MANDATORY = os.environ.get("ORPHAN_MANDATORY", "0") == "1"


def _check_python_tree(root: Path, errors: list[str]) -> None:
    if not root.exists():
        return
    for entry in root.rglob("*"):
        rel = entry.relative_to(V2_ROOT).as_posix()
        if entry.is_dir():
            if entry.name == "__pycache__":
                errors.append(f"committed __pycache__: {rel}")
                continue
            if entry == root:
                continue
            init = entry / "__init__.py"
            keep = entry / ".gitkeep"
            has_py_files = any(child.suffix == ".py" for child in entry.iterdir() if child.is_file())
            if has_py_files and not init.exists():
                errors.append(f"directory missing __init__.py: {rel}")
            elif not has_py_files and not init.exists() and not keep.exists():
                # Empty directories should at least carry .gitkeep so git tracks them.
                errors.append(f"empty package missing .gitkeep or __init__.py: {rel}")
        elif entry.is_file():
            if entry.suffix == ".pyc":
                errors.append(f"committed .pyc: {rel}")


def _check_no_backups(root: Path, errors: list[str]) -> None:
    if not root.exists():
        return
    for entry in root.rglob("*"):
        if entry.is_file() and entry.suffix in (".bak", ".swp", ".orig"):
            errors.append(f"editor backup committed: {entry.relative_to(V2_ROOT).as_posix()}")


def main() -> int:
    errors: list[str] = []
    _check_python_tree(V2_ROOT / "backend" / "app", errors)
    _check_python_tree(V2_ROOT / "backend" / "tests", errors)
    _check_no_backups(V2_ROOT / "frontend" / "src", errors)
    _check_no_backups(V2_ROOT / "backend", errors)

    if errors:
        level = "FAIL" if MANDATORY else "WARN"
        for e in errors:
            print(f"[orphan-path] {level}: {e}", file=sys.stderr)
        return 1 if MANDATORY else 0
    print("[orphan-path] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
