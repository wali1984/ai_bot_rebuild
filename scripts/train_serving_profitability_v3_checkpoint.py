#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v3 import (  # noqa: E402
    train_serving_checkpoint_v3,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    bundle, report, _ = train_serving_checkpoint_v3(
        dataset_path=args.dataset.resolve(),
        manifest_path=args.manifest.resolve(),
        output_dir=args.model_dir.resolve(),
    )
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "serving_profitability_checkpoint_bundle_v3.json").write_text(
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n"
    )
    (
        args.evidence_dir / "serving_profitability_checkpoint_training_report_v3.json"
    ).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "checkpoint_id": bundle.checkpoint_id,
                "model_architecture": bundle.model_architecture,
                "training_rows": bundle.training_rows,
                "validation_rows": bundle.validation_rows,
                "holdout_rows": bundle.holdout_rows,
                "decision_group_balance": bundle.training_metrics[
                    "decision_group_balance"
                ],
                "validation": bundle.training_metrics["validation"],
                "holdout": bundle.training_metrics["holdout"],
                "activation_eligible": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
