"""Unit tests for legacy_dependency_closure scanner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.cli.legacy_dependency_closure import (
    analyze,
    closure,
    _resolve_local_module,
)


def write(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_analyze_recognizes_external_imports(tmp_path: Path) -> None:
    write(tmp_path, "a.py", "import redis\nimport ccxt\nimport numpy as np\nimport json\n")
    fa = analyze(tmp_path, "a.py", known_local=set())
    assert "redis" in fa.external_imports
    assert "ccxt" in fa.external_imports
    assert "numpy" in fa.external_imports
    assert "json" in fa.stdlib_imports
    assert fa.redis_usage is True


def test_analyze_recognizes_local_module(tmp_path: Path) -> None:
    write(tmp_path, "helpers.py", "x = 1\n")
    write(tmp_path, "a.py", "import helpers\n")
    fa = analyze(tmp_path, "a.py", known_local={"helpers"})
    assert "helpers" in fa.local_imports
    assert "helpers" not in fa.external_imports


def test_resolve_local_module_finds_top_level_and_package(tmp_path: Path) -> None:
    write(tmp_path, "topmod.py", "")
    write(tmp_path, "pkg/__init__.py", "")
    assert _resolve_local_module(tmp_path, "topmod") == "topmod.py"
    assert _resolve_local_module(tmp_path, "pkg") == "pkg/__init__.py"
    assert _resolve_local_module(tmp_path, "nonexistent") is None


def test_closure_walks_local_dependency_tree(tmp_path: Path) -> None:
    write(tmp_path, "a.py", "import b\nimport redis\n")
    write(tmp_path, "b.py", "import c\n")
    write(tmp_path, "c.py", "import numpy\n")
    result = closure(tmp_path, ["a.py"])
    analyzed = set(result["analyses"].keys())
    assert "a.py" in analyzed
    assert "b.py" in analyzed
    assert "c.py" in analyzed
    assert result["totals"]["files_analyzed"] == 3
    assert result["totals"]["files_with_redis_usage"] == 1


def test_shell_script_extracts_py_refs(tmp_path: Path) -> None:
    write(tmp_path, "start.sh", "#!/bin/bash\npython3 worker.py\npython3 module/sub.py\n")
    write(tmp_path, "worker.py", "")
    write(tmp_path, "module/sub.py", "")
    result = closure(tmp_path, ["start.sh"])
    assert "worker.py" in result["analyses"]
    assert "module/sub.py" in result["analyses"]


def test_parse_error_recorded_not_raised(tmp_path: Path) -> None:
    write(tmp_path, "broken.py", "def foo(:\n")
    fa = analyze(tmp_path, "broken.py", known_local=set())
    assert fa.parse_error is not None
    assert "SyntaxError" in fa.parse_error


def test_exchange_api_usage_detected(tmp_path: Path) -> None:
    write(tmp_path, "x.py", "from binance.client import Client\n")
    fa = analyze(tmp_path, "x.py", known_local=set())
    assert fa.exchange_api_usage is True
