"""V2 feature intelligence worker CLI.

Paper/shadow only. Writes a public status JSON describing the service's
current scope, components ported, components missing, and the legacy
sha256 citations. Does NOT connect to Redis, exchanges, or live services.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.feature_intelligence.service import (
    FeatureIntelligenceService,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_feature_intelligence/latest/v2_feature_intelligence_status.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2 feature intelligence worker (paper/shadow only)")
    parser.add_argument("--write-evidence", action="store_true", help="Write status payload to public dir.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload to stdout.")
    parser.add_argument("--out", type=Path, default=PUBLIC_STATUS_PATH, help="Output path override.")
    args = parser.parse_args(argv)

    svc = FeatureIntelligenceService()
    status = svc.current_paper_only_status()

    text = json.dumps(status, indent=2, sort_keys=True) + "\n"

    if args.dry_run:
        sys.stdout.write(text)
        return 0

    if args.write_evidence:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"v2_feature_intelligence_status_written path={args.out} live_gate={status['live_gate']}")
        return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
