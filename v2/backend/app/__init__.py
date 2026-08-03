"""Backend application package bootstrap.

The public website backend is launched with ``PYTHONPATH`` pointed at
``v2/backend`` so imports like ``app.main`` work. Some shared runtime modules
still import through the repository package path, ``v2.backend.app``. Add the
repo root to ``sys.path`` during package import so both established import
styles resolve in the production service.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_repo_root_str = str(_REPO_ROOT)
if _repo_root_str not in sys.path:
    sys.path.insert(0, _repo_root_str)
