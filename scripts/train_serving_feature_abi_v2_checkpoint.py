#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v2 import (  # noqa: E402
    train_serving_checkpoint_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_compatible_dataset_v2.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT
        / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_compatible_dataset_manifest_v2.json",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=REPO_ROOT / ".local_models/permanent_recovery_v2",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=REPO_ROOT / "goal_state/PERMANENT_SYSTEM_RECOVERY",
    )
    args = parser.parse_args()
    bundle, report, _ = train_serving_checkpoint_v2(
        dataset_path=args.dataset.resolve(),
        manifest_path=args.manifest.resolve(),
        output_dir=args.model_dir.resolve(),
    )
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "serving_checkpoint_bundle_v2.json").write_text(
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n"
    )
    (args.evidence_dir / "serving_checkpoint_training_report_v2.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "checkpoint_id": bundle.checkpoint_id,
                "checkpoint_path": bundle.weight_file_path,
                "optimizer_steps": bundle.optimizer_steps,
                "finite_loss": bundle.training_metrics["finite_loss"],
                "validation": bundle.training_metrics["validation"],
                "holdout": bundle.training_metrics["holdout"],
                "calibration": bundle.calibration_state,
                "activation_eligible": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
