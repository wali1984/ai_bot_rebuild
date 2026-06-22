#!/usr/bin/env python3
"""Run the persistent V2 native CUDA trainer loop.

This is a resident V2-native trainer process. It does not unmask the legacy
trainer bridge, does not run ``hybrid_trainer.py`` as a wrapper, and never
touches live exchange mutation paths.
"""
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime import (  # noqa: E402
    persistent_loop_main,
)


if __name__ == "__main__":
    raise SystemExit(persistent_loop_main())
