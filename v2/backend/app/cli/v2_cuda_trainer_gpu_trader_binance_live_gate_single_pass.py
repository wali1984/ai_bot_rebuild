"""Generate V2 CUDA trainer GPU/trader/Binance live-gate artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.live_gate.single_pass import (  # noqa: E402
    default_paths,
    raw_secret_values_present_in_text,
    build_single_pass,
    write_single_pass_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the mutation-frozen V2 CUDA trainer GPU/trader/Binance live-gate single pass."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--network-probe", action="store_true", default=False)
    parser.add_argument("--service-start-method", default="not_started_by_cli")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    service_start = {
        "attempted": args.service_start_method != "not_started_by_cli",
        "method": args.service_start_method,
    }
    result = build_single_pass(
        paths=paths,
        network_probe_enabled=bool(args.network_probe),
        service_start=service_start,
    )
    result = write_single_pass_artifacts(paths=paths, result=result)
    serialized = json.dumps(result.operator_dashboard_payload, sort_keys=True)
    raw_secret_scan_passed = not raw_secret_values_present_in_text(paths.env_local_path, serialized)
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "paths_written": list(result.paths_written),
                "live_gate": result.operator_dashboard_payload["live_gate"],
                "live_symbols": result.operator_dashboard_payload["live_symbols"],
                "execution_live_symbols": result.operator_dashboard_payload["execution_live_symbols"],
                "trader_execution_enabled": result.operator_dashboard_payload["trader_execution_enabled"],
                "raw_secret_scan_passed": raw_secret_scan_passed,
                "exact_blockers": result.operator_dashboard_payload["exact_blockers"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if raw_secret_scan_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
