#!/usr/bin/env python3
"""Compatibility entry point for the durable gen-5 snapshot backfill service.

The implementation lives in the tested native-trainer service module. Keeping
this entry point preserves the deployed unit name while eliminating the older
mutable, non-fsynced runner implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_gen5_snapshot_backfill import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
