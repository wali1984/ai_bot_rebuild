"""Generate CUDA trainer edge calibration and outcome burn-in artifacts.

Read-only runtime behavior:
- reads the V2 CUDA trainer operator payload;
- optionally reads V2 Redis OHLCV keys for outcome windows;
- writes JSON/Markdown artifacts under worklog and frontend public paths;
- never enables live/canary and never mutates exchange/Redis state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.cuda_trainer_edge_burn_in import (  # noqa: E402
    default_paths,
    redis_timeline_provider,
    run_edge_burn_in,
)


def _try_redis_client():
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        return client
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build V2 CUDA trainer edge calibration and outcome burn-in artifacts."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--source-payload", default="")
    parser.add_argument("--no-redis", action="store_true", help="Do not read Redis OHLCV timelines; outcomes remain pending.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    source = Path(args.source_payload).resolve() if args.source_payload else None
    redis_client = None if args.no_redis else _try_redis_client()
    result = run_edge_burn_in(
        paths=paths,
        source_payload_path=source,
        timeline_provider=redis_timeline_provider(redis_client),
    )
    edge = result.operator_dashboard_payload["edge_recompute"]
    outcome = result.operator_dashboard_payload["outcome_mining"]
    calibration = result.operator_dashboard_payload["confidence_calibration"]
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "paths_written": list(result.paths_written),
                "outcome_sample_count": outcome.get("outcome_sample_count"),
                "after_cost_expectancy_bps": edge["new_cuda_trainer"].get("after_cost_expectancy_bps"),
                "after_cost_ci_lower_bps": edge["new_cuda_trainer"].get("after_cost_ci_lower_bps"),
                "false_positive_count": edge.get("false_positive_count"),
                "false_negative_count": edge.get("false_negative_count"),
                "confidence_calibration": calibration.get("status"),
                "primary_recommendation": edge.get("primary_recommendation"),
                "live_gate": result.operator_dashboard_payload["live_gate"],
                "live_symbols": result.operator_dashboard_payload["live_symbols"],
                "execution_live_symbols": result.operator_dashboard_payload["execution_live_symbols"],
                "approves_live": result.operator_dashboard_payload["approves_live"],
                "approves_canary": result.operator_dashboard_payload["approves_canary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
