#!/usr/bin/env python3
"""Dispatch the persistent native-trainer service in an explicit safe mode.

Argument validation intentionally completes before a runtime module is
imported.  The only currently authorized resident mode observes integrity and
profiled-child readiness and waits for a separate operator promotion; it has
no training, prediction, paper, live, or execution authority.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))


class NativeTrainerResidentMode(str, Enum):
    """Resident modes that are explicitly authorized by this entrypoint."""

    WAITING_FOR_AUTHENTICATED_SAMPLES = "waiting-for-authenticated-samples"


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        type=NativeTrainerResidentMode,
        choices=tuple(NativeTrainerResidentMode),
        required=True,
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--ledger-path", type=Path, required=True)
    parser.add_argument("--trusted-cost-store-root", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, required=True)
    parser.add_argument("--max-rows", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    if args.mode is not NativeTrainerResidentMode.WAITING_FOR_AUTHENTICATED_SAMPLES:
        # The enum currently makes this unreachable.  Keep the dispatch guard
        # explicit so a future enum member cannot silently gain runtime power.
        raise RuntimeError("native_trainer_resident_mode_not_implemented")

    # This lazy import is the safety boundary: invalid/missing modes cannot
    # import the waiting observer or the legacy CUDA trainer runtime.
    from v2.backend.app.services.native_trainer.profiled_training_waiting_runtime_v1 import (
        ProfiledTrainingWaitingConfigV1,
        run_profiled_training_waiting_loop_v1,
    )

    config = ProfiledTrainingWaitingConfigV1(
        repo_root=args.repo_root,
        ledger_path=args.ledger_path,
        trusted_cost_store_root=args.trusted_cost_store_root,
        interval_seconds=args.interval_seconds,
        scan_limit=args.max_rows,
    )
    return run_profiled_training_waiting_loop_v1(config)


if __name__ == "__main__":
    raise SystemExit(main())
