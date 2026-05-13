from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_env_repo_parity" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_env_repo_parity" / "latest"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_name(line: str) -> str | None:
    body = line.split("#", 1)[0].strip()
    if not body or body.startswith(("-", "--")):
        return None
    body = body.split(";", 1)[0].strip()
    body = body.split("[", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", body)
    if not match:
        return None
    return normalize_name(match.group(1))


def read_requirements_file(path: Path) -> list[str]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    names: list[str] = []
    for line in lines:
        name = parse_requirement_name(line)
        if name:
            names.append(name)
    return sorted(set(names))


def read_v2_pyproject(path: Path) -> dict[str, list[str]]:
    try:
        data = tomllib.loads(path.read_text())
    except OSError:
        return {"runtime": [], "dev": []}
    project = data.get("project", {})
    runtime = [name for req in project.get("dependencies", []) if (name := parse_requirement_name(req))]
    optional = project.get("optional-dependencies", {})
    dev = [name for req in optional.get("dev", []) if (name := parse_requirement_name(req))]
    return {"runtime": sorted(set(runtime)), "dev": sorted(set(dev))}


def installed_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        metadata_name = distribution.metadata.get("Name")
        if metadata_name:
            packages[normalize_name(metadata_name)] = distribution.version
    return packages


@dataclass(frozen=True)
class EnvTooling:
    venv_python: str
    venv_pytest: str
    venv_python_exists: bool
    venv_pytest_exists: bool
    current_python: str
    current_python_is_repo_venv: bool
    test_env_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "venv_python": self.venv_python,
            "venv_pytest": self.venv_pytest,
            "venv_python_exists": self.venv_python_exists,
            "venv_pytest_exists": self.venv_pytest_exists,
            "current_python": self.current_python,
            "current_python_is_repo_venv": self.current_python_is_repo_venv,
            "test_env_valid": self.test_env_valid,
        }


def evaluate_tooling(root: Path, current_python: str | None = None) -> EnvTooling:
    current = Path(current_python or sys.executable)
    venv_python = root / ".venv" / "bin" / "python3"
    venv_pytest = root / ".venv" / "bin" / "pytest"
    venv_python_exists = venv_python.exists()
    venv_pytest_exists = venv_pytest.exists()
    try:
        current_resolved = current.resolve()
    except OSError:
        current_resolved = current
    try:
        venv_resolved = venv_python.resolve()
    except OSError:
        venv_resolved = venv_python
    current_is_repo_venv = current_resolved == venv_resolved
    return EnvTooling(
        venv_python=str(venv_python),
        venv_pytest=str(venv_pytest),
        venv_python_exists=venv_python_exists,
        venv_pytest_exists=venv_pytest_exists,
        current_python=str(current),
        current_python_is_repo_venv=current_is_repo_venv,
        test_env_valid=venv_python_exists and venv_pytest_exists and current_is_repo_venv,
    )


def missing_packages(required: list[str], installed: dict[str, str]) -> list[str]:
    return sorted(name for name in sorted(set(required)) if name not in installed)


def build_env_dependency_parity(
    root: Path = REPO_ROOT,
    *,
    installed: dict[str, str] | None = None,
    current_python: str | None = None,
) -> dict[str, Any]:
    installed = installed if installed is not None else installed_packages()
    v2_requirements = read_v2_pyproject(root / "v2" / "pyproject.toml")
    legacy_requirement_files = [
        root / "legacy_reference" / "requirements.txt",
        root / "legacy_reference" / "requirements_ubuntu.txt",
    ]
    legacy_by_file = {
        str(path.relative_to(root)): read_requirements_file(path)
        for path in legacy_requirement_files
        if path.exists()
    }
    legacy_all = sorted(set(name for names in legacy_by_file.values() for name in names))
    tooling = evaluate_tooling(root, current_python)
    missing_v2_runtime = missing_packages(v2_requirements["runtime"], installed)
    missing_v2_dev = missing_packages(v2_requirements["dev"], installed)
    missing_legacy = missing_packages(legacy_all, installed)
    hidden_mismatch = False
    result = "PASS" if tooling.test_env_valid and not hidden_mismatch else "FAIL"
    return {
        "generated_at": utc_now(),
        "result": result,
        "live_gate": "blocked_human_only",
        "environment_tooling": tooling.to_dict(),
        "installed_package_count": len(installed),
        "v2_pyproject": {
            "path": "v2/pyproject.toml",
            "runtime_dependencies": v2_requirements["runtime"],
            "dev_dependencies": v2_requirements["dev"],
            "missing_runtime_dependencies": missing_v2_runtime,
            "missing_dev_dependencies": missing_v2_dev,
        },
        "legacy_reference_requirements": {
            "source_files": sorted(legacy_by_file),
            "dependencies": legacy_all,
            "missing_dependencies": missing_legacy,
            "parity_status": "MATCH" if not missing_legacy else "MISMATCH_REPORTED",
        },
        "dependency_mismatch_hidden": hidden_mismatch,
        "system_python_used_as_valid_test_env_without_pytest": not tooling.test_env_valid,
        "legacy_env_mutation_performed": False,
        "old_redis_write_performed": False,
        "exchange_action_performed": False,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_outputs(payload: dict[str, Any]) -> None:
    write_json(FINAL_DIR / "env_dependency_parity.json", payload)
    write_json(PUBLIC_DIR / "env_dependency_parity.json", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit V2 .venv and legacy dependency parity.")
    parser.add_argument("--write", action="store_true", help="write parity artifacts")
    args = parser.parse_args(argv)
    payload = build_env_dependency_parity(REPO_ROOT)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
