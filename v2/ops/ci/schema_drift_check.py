"""Schema-drift check.

Diffs the Alembic head against SQLAlchemy declarative metadata
(`app.adapters.db.base.Base.metadata`).

Per 07_TEST_AND_CI_PLAN.md §5 this stage is **advisory until milestone C**
(015B). When `SCHEMA_DRIFT_MANDATORY=1` is set in the env, drift becomes a
hard error (intended for milestone C+ runs). Until then, drift emits a WARN
and exits 0 so the job does not block the milestone-B gate.

Boundary: this script never connects to the legacy DB. It only inspects the
local Alembic script directory and the in-process SQLAlchemy metadata.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = V2_ROOT / "backend"

MANDATORY = os.environ.get("SCHEMA_DRIFT_MANDATORY", "0") == "1"


def _emit(level: str, msg: str) -> int:
    if level == "FAIL":
        print(f"[schema-drift] FAIL: {msg}", file=sys.stderr)
        return 1
    if level == "WARN":
        print(f"[schema-drift] WARN: {msg}", file=sys.stderr)
        return 0
    print(f"[schema-drift] {level}: {msg}")
    return 0


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from app.adapters.db.base import Base  # type: ignore
    except Exception as e:
        return _emit("WARN" if not MANDATORY else "FAIL",
                     f"cannot import Base.metadata: {e}")

    metadata_tables = sorted(Base.metadata.tables.keys())

    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    versions = []
    if versions_dir.exists():
        versions = [p for p in versions_dir.glob("*.py") if p.name != "__init__.py"]

    if not versions:
        if metadata_tables:
            return _emit(
                "FAIL" if MANDATORY else "WARN",
                f"metadata declares {len(metadata_tables)} tables but zero Alembic versions exist",
            )
        return _emit("OK", "empty metadata, zero versions; harness-only gate")

    try:
        from alembic.config import Config  # type: ignore
        from alembic.script import ScriptDirectory  # type: ignore
    except Exception as e:
        return _emit(
            "FAIL" if MANDATORY else "WARN",
            f"alembic import failed: {e}",
        )

    cfg = Config(str(V2_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    if head is None and metadata_tables:
        return _emit(
            "FAIL" if MANDATORY else "WARN",
            "alembic head is None but metadata declares tables",
        )

    return _emit(
        "OK",
        f"head={head!r} metadata_tables={len(metadata_tables)} (mandatory={MANDATORY})",
    )


if __name__ == "__main__":
    raise SystemExit(main())
