"""V2 trade management paper worker CLI.

Paper/shadow only. Emits a public status JSON. Never places, cancels, or
modifies exchange instructions. Never changes leverage or margin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.trade_management_paper.service import (
    TradeManagementPaperService,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/v2_trade_management_paper_status.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2 trade management paper worker (paper/shadow only)")
    parser.add_argument("--write-evidence", action="store_true", help="Write status payload to public dir.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload to stdout.")
    parser.add_argument("--out", type=Path, default=PUBLIC_STATUS_PATH, help="Output path override.")
    args = parser.parse_args(argv)

    svc = TradeManagementPaperService()
    status = svc.current_paper_only_status()
    text = json.dumps(status, indent=2, sort_keys=True) + "\n"

    if args.dry_run:
        sys.stdout.write(text)
        return 0
    if args.write_evidence:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"v2_trade_management_paper_status_written path={args.out} live_gate={status['live_gate']}")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
