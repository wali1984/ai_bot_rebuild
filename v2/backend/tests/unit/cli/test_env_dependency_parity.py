from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli.env_dependency_parity import (
    build_env_dependency_parity,
    parse_requirement_name,
    read_v2_pyproject,
)


def _write(path: Path, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _make_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path / "v2/pyproject.toml",
        """
        [project]
        dependencies = ["fastapi==0.115.0", "redis==5.0.8"]

        [project.optional-dependencies]
        dev = ["pytest==8.3.3"]
        """,
    )
    _write(tmp_path / "legacy_reference/requirements.txt", "requests>=2.31.0\nccxt>=4.4.0\n")
    _write(tmp_path / "legacy_reference/requirements_ubuntu.txt", "TA-Lib>=0.4.0\npytest>=7.4.0\n")
    _write(tmp_path / ".venv/bin/python3")
    _write(tmp_path / ".venv/bin/pytest")
    return tmp_path


def test_parse_requirement_name_handles_versions_extras_and_comments() -> None:
    assert parse_requirement_name("pydantic-settings==2.5.2") == "pydantic-settings"
    assert parse_requirement_name("psycopg[binary]>=3.2.1  # comment") == "psycopg"
    assert parse_requirement_name("--index-url https://example.invalid") is None


def test_v2_pyproject_dependencies_are_loaded(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = read_v2_pyproject(root / "v2/pyproject.toml")

    assert result["runtime"] == ["fastapi", "redis"]
    assert result["dev"] == ["pytest"]


def test_dependency_mismatch_is_reported_not_hidden(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    installed = {"fastapi": "0.115.0", "redis": "5.0.8", "pytest": "8.3.3", "requests": "2.31.0"}

    result = build_env_dependency_parity(root, installed=installed, current_python=str(root / ".venv/bin/python3"))

    assert result["result"] == "PASS"
    assert result["dependency_mismatch_hidden"] is False
    assert result["legacy_reference_requirements"]["parity_status"] == "MISMATCH_REPORTED"
    assert "ccxt" in result["legacy_reference_requirements"]["missing_dependencies"]
    assert "ta-lib" in result["legacy_reference_requirements"]["missing_dependencies"]


def test_system_python_without_repo_pytest_is_not_valid_test_env(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / ".venv/bin/pytest").unlink()

    result = build_env_dependency_parity(
        root,
        installed={"fastapi": "0.115.0"},
        current_python="/usr/bin/python3",
    )

    assert result["result"] == "FAIL"
    assert result["environment_tooling"]["test_env_valid"] is False
    assert result["system_python_used_as_valid_test_env_without_pytest"] is True
