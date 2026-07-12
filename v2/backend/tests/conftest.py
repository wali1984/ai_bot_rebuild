"""Pytest path bootstrap for repository-root imports.

The V2 pytest rootdir resolves to ``v2`` because ``v2/pyproject.toml`` owns the
pytest configuration.  Many existing tests import through ``v2.backend.*``, so
the repository root must be present on ``sys.path`` during collection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _reset_closed_trade_example_cache():
    """Isolate the trainer's module-level closed-trade example memo cache.

    In production a feature_snapshot_id maps to exactly one immutable snapshot,
    so caching built examples by row-content hash is coherent. Tests, however,
    legitimately reuse the same row id with different snapshot payloads across
    cases, so the shared cache must be cleared between tests to keep them
    order-independent.
    """
    try:
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
            data_loader as _dl,
        )
    except Exception:
        yield
        return
    with _dl._CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
        _dl._CLOSED_TRADE_EXAMPLE_CACHE.clear()
        _dl._CLOSED_TRADE_EXAMPLE_CACHE_STATS.update({"hits": 0, "misses": 0})
    yield
