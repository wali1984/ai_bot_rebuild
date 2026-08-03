from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.e2e_verification import (
    DEFAULT_OUTPUT_DIR,
    run_e2e_verification_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_e2e_verification",
        description="Run the synthetic end-to-end verification harness for the trading bot.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSON/text verification reports and replay snapshots.",
    )
    args = parser.parse_args(argv)
    report, exit_code = run_e2e_verification_report(output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "scenario_count": report.summary["scenario_count"],
                "passed_count": report.summary["passed_count"],
                "failed_count": report.summary["failed_count"],
                "critical_failures": report.summary["critical_failures"],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
