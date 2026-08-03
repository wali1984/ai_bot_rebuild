"""Phase 1: checkpoint weight resolution payload emitter."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.rl_core.checkpoints import (
    checkpoints_invariants_snapshot,
    inventory_checkpoints,
)

ROOTS = [
    Path("v2/legacy_owned_runtime"),
    Path("v2/runtime"),
    Path(".local_secrets"),
    Path(".local_models"),
    Path("claude_worklog/final_readiness/full_legacy_root_filesystem_inventory/latest"),
]

TARGET_WORKLOG = Path(
    "claude_worklog/final_readiness/core_completion_blocker_burndown/latest/checkpoint_weight_resolution.json"
)
TARGET_PUBLIC = Path(
    "v2/frontend/public/core_completion_blocker_burndown/latest/checkpoint_weight_resolution.json"
)


def main() -> int:
    existing = [r for r in ROOTS if r.exists()]
    inv = inventory_checkpoints(existing, sha256_compute_max_bytes=5 * 1024 * 1024)
    ck_count = inv.candidate_count
    status = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    shape = "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH_LOAD_IN_V2"
    operator_request = {
        "expected_file_types": [".pt", ".pth", ".ckpt", ".zip"],
        "expected_legacy_filename_prefixes": [
            "legacy_live_checkpoint_<unix_ts>.zip",
            "hybrid_trainer_ckpt_<unix_ts>.zip",
            "ppo_masa_ckpt_<unix_ts>_<model_version>.zip",
            "enterprise_modules_<unix_ts>.pt",
        ],
        "candidate_paths_scanned": [str(r) for r in existing],
        "candidate_paths_found_count": ck_count,
        "next_action_required_from_operator": (
            "Either (a) provide an operator-approved checkpoint blob with sidecar "
            "metadata JSON AND authorize V2 to invoke a legacy-venv subprocess to "
            "inspect tensor shapes, OR (b) explicitly accept "
            "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED as a paper-only-shutdown "
            "limitation."
        ),
        "do_not_commit_blobs_to_git": True,
    }
    top = [
        {
            "path": c.path,
            "size_bytes": c.size_bytes,
            "mtime_utc": c.mtime_utc,
            "sha256_hex": c.sha256_hex,
            "extension": c.extension,
            "parsed_metadata": c.parsed_metadata.as_dict() if c.parsed_metadata else None,
        }
        for c in inv.candidates[:25]
    ]
    out = {
        "phase": "P1_CHECKPOINT_WEIGHT_BLOCKER",
        "generated_utc": "2026-05-16T22:25:00Z",
        "scanned_roots": [str(r) for r in existing],
        "candidate_count": ck_count,
        "top_candidates": top,
        "top_candidates_truncated": ck_count > 25,
        "checkpoint_weight_status": status,
        "model_shape_status": shape,
        "operator_request": operator_request,
        "invariants": checkpoints_invariants_snapshot(),
    }
    body = json.dumps(out, indent=2, sort_keys=True) + "\n"
    TARGET_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    TARGET_WORKLOG.write_text(body)
    TARGET_PUBLIC.write_text(body)
    print("candidate_count", ck_count, "status", status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
