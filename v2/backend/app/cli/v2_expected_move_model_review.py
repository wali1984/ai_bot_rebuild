"""V2 expected-move model review CLI.

Analysis-only. Loads existing review artifacts, applies the migration
contract's safety invariants, and prints a summary or exits non-zero if
the review payload is missing, malformed, or violates a safety invariant.

This CLI does not authorize fills, loosen the global paper gate, restart
legacy services, or place exchange orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.expected_move_model_review.service import (
    ExpectedMoveModelReviewService,
    REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND,
    REVIEW_GO_NO_GO_BLOCKED_INSUFFICIENT_SAMPLE,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2 expected-move model review (analysis only)")
    p.add_argument(
        "--payload",
        type=Path,
        default=None,
        help="Optional override path for the review operator dashboard payload.",
    )
    p.add_argument(
        "--false-block-audit",
        type=Path,
        default=None,
        help="Optional override path for false_block_audit.json.",
    )
    p.add_argument(
        "--threshold-replay",
        type=Path,
        default=None,
        help="Optional override path for threshold_replay_results.json.",
    )
    p.add_argument(
        "--require-safe",
        action="store_true",
        help="Exit non-zero if safety invariants are violated.",
    )
    args = p.parse_args(argv)

    service = ExpectedMoveModelReviewService(
        payload_path=args.payload,
        false_block_audit_path=args.false_block_audit,
        threshold_replay_path=args.threshold_replay,
    )
    summary = service.summarize()
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.require_safe and not summary["safety"]["safe"]:
        return 2
    if summary["go_no_go"] in (
        REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND,
        REVIEW_GO_NO_GO_BLOCKED_INSUFFICIENT_SAMPLE,
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
