#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_paper_provisional_prediction_publisher import (  # noqa: E402
    redis_client,
    resolve_symbols,
)
from v2.backend.app.services.prediction_serving.serving_activation_v2 import (  # noqa: E402
    evaluate_current_universe,
    load_checkpoint_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_checkpoint_bundle_v2.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_compatible_dataset_manifest_v2.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/train_serve_feature_parity_report.json",
    )
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--timeframes", default="5m,15m,1h,4h")
    args = parser.parse_args()
    client = redis_client(args.redis_url)
    bundle = load_checkpoint_bundle(args.bundle)
    manifest = json.loads(args.manifest.read_text())
    report = evaluate_current_universe(
        client,
        bundle=bundle,
        manifest=manifest,
        symbols=resolve_symbols(client, None),
        timeframes=[
            value.strip() for value in args.timeframes.split(",") if value.strip()
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "checkpoint_id",
                    "universe_slots_evaluated",
                    "accepted_current_rows",
                    "prediction_distribution",
                    "serving_smoke_directional_rate",
                    "serving_smoke_positive_directional_edge_rate",
                    "excessive_drift_features",
                    "feature_distribution_drift_above_limit",
                    "activation_eligible",
                )
            },
            indent=2,
        )
    )
    return 0 if report["activation_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
