"""Run the V2 continuous paper/replay A-grade edge guardian."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2.backend.app.services.continuous_edge_guardian.guardian import (
    REPO_ROOT,
    run_forever,
    run_once,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args(argv)
    if args.once:
        status = run_once(
            repo_root=args.repo_root.resolve(),
            publish_redis=not args.no_redis,
        )
        print(json.dumps(status, indent=2, sort_keys=True, default=str))
        return 0 if status.get("overall_status") == "READY" else 2
    run_forever(
        repo_root=args.repo_root.resolve(),
        interval_seconds=args.interval_seconds,
        publish_redis=not args.no_redis,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
