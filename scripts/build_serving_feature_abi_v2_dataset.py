#!/usr/bin/env python3
"""Materialize ServingFeatureABIV2 and its reproducible paper dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (  # noqa: E402
    build_serving_dataset_v2,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (  # noqa: E402
    canonical_abi_json,
    feature_abi_sha256,
)

DEFAULT_OUTPUT = REPO_ROOT / "goal_state/PERMANENT_SYSTEM_RECOVERY"
DEFAULT_IDENTITY = (
    REPO_ROOT / ".local_models/paper_provisional/admitted_114_identity.json"
)
DEFAULT_ARCHIVE = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_archive"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--identity-manifest", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset, manifest, parity = build_serving_dataset_v2(
        identity_manifest_path=args.identity_manifest.resolve(),
        archive_root=args.archive_root.resolve(),
    )
    (args.output_dir / "ServingFeatureABIV2.json").write_text(canonical_abi_json())
    (args.output_dir / "ServingFeatureABIV2.sha256").write_text(
        feature_abi_sha256() + "\n"
    )
    (args.output_dir / "serving_compatible_dataset_v2.json").write_text(
        json.dumps(dataset, indent=2, sort_keys=True) + "\n"
    )
    (args.output_dir / "serving_compatible_dataset_manifest_v2.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (args.output_dir / "train_serve_feature_parity_report.json").write_text(
        json.dumps(parity, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "feature_abi_sha256": feature_abi_sha256(),
                "manifest_id": manifest["manifest_id"],
                "manifest_sha256": manifest["manifest_sha256"],
                "training_rows": manifest["training_rows"],
                "validation_rows": manifest["validation_rows"],
                "holdout_rows": manifest["holdout_rows"],
                "duplicate_rows": manifest["duplicate_rows"],
                "future_time_rejections": manifest["future_time_rejections"],
                "finality_unproven": manifest["finality_unproven"],
                "missing_cost_evidence": manifest["missing_cost_evidence"],
                "missing_label_evidence": manifest["missing_label_evidence"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
