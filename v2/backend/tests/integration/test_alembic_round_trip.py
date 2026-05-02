"""Alembic harness round-trip integration test.

Boots an ephemeral PostgreSQL container via ``testcontainers`` and
asserts:

1. ``alembic upgrade head`` exits 0 against an empty schema.
2. ``alembic downgrade base`` exits 0 against the same database.

With zero version scripts checked in, both commands resolve to no-ops;
the assertion is that the harness (env.py + alembic.ini + Base) is
syntactically valid and self-consistent against a real Postgres
backend.

Boundary policy:
- No legacy or production database is touched. The container is
  destroyed when the test exits regardless of outcome.
- Skipped automatically when Docker is unavailable or when the
  ``testcontainers`` / ``psycopg`` packages are not installed; the
  test is therefore safe to ship in environments without Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

V2_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = V2_ROOT / "alembic.ini"
BACKEND_PATH = V2_ROOT / "backend"

postgres_module = pytest.importorskip("testcontainers.postgres")
pytest.importorskip("psycopg")
pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker is required to launch the ephemeral postgres container",
)


def _run_alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{BACKEND_PATH}{os.pathsep}{existing_pp}"
        if existing_pp
        else str(BACKEND_PATH)
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=str(V2_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_alembic_upgrade_head_then_downgrade_base_round_trip() -> None:
    """Harness must round-trip cleanly with zero migration versions."""
    PostgresContainer = postgres_module.PostgresContainer  # noqa: N806
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        db_url = pg.get_connection_url()

        upgrade = _run_alembic(["upgrade", "head"], db_url)
        assert upgrade.returncode == 0, (
            f"alembic upgrade head failed (rc={upgrade.returncode})\n"
            f"STDOUT:\n{upgrade.stdout}\nSTDERR:\n{upgrade.stderr}"
        )

        downgrade = _run_alembic(["downgrade", "base"], db_url)
        assert downgrade.returncode == 0, (
            f"alembic downgrade base failed (rc={downgrade.returncode})\n"
            f"STDOUT:\n{downgrade.stdout}\nSTDERR:\n{downgrade.stderr}"
        )
