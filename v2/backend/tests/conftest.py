"""Pytest path bootstrap for repository-root imports.

The V2 pytest rootdir resolves to ``v2`` because ``v2/pyproject.toml`` owns the
pytest configuration.  Many existing tests import through ``v2.backend.*``, so
the repository root must be present on ``sys.path`` during collection.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
