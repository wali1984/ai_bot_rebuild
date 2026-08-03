"""V2 model-parity sprint orchestrator (paper-only, read-only).

Wires together:
  - LANE 1 checkpoint candidate inventory
  - LANE 2 legacy observation contract + gap matrix
  - LANE 3 V2 full observation builder status
  - LANE 4 policy architecture compatibility
  - LANE 5 decision-match shadow metrics

Emits the model-parity-sprint status, GO/NO-GO, public operator dashboard,
and updates downstream narrow remediation tasks. Never imports torch.
Never deserializes checkpoint blobs. Never mutates legacy.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.checkpoint_inventory import build_inventory
from v2.backend.app.services.rl_core.decision_match_shadow import (
    compute_shadow_metrics,
    write_shadow_metrics,
)
from v2.backend.app.services.rl_core.full_observation_builder import (
    build_full_observation_status,
    write_full_observation_status,
)
from v2.backend.app.services.rl_core.legacy_observation_contract import (
    build_legacy_observation_contract,
    gap_vs_v2_compact,
)
from v2.backend.app.services.rl_core.policy_architecture_compatibility import (
    analyze_compatibility,
    write_compatibility_status,
)

WORKLOG_DIR = Path(
    "claude_worklog/final_readiness/v2_model_parity_sprint/latest"
)
PUBLIC_DIR = Path("v2/frontend/public/v2_model_parity_sprint/latest")
RL_CORE_PUBLIC_DIR = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/latest"
)

GO_FOR_CHECKPOINT = "V2_MODEL_PARITY_SPRINT_READY_FOR_OPERATOR_CHECKPOINT_ARTIFACT"
GO_FOR_FULL_OBS = "V2_MODEL_PARITY_SPRINT_READY_FOR_FULL_OBSERVATION_BUILDER_IMPLEMENTATION"
GO_FOR_POLICY_PORT = "V2_MODEL_PARITY_SPRINT_READY_FOR_POLICY_ARCHITECTURE_PORT"
GO_BLOCKED = "V2_MODEL_PARITY_SPRINT_BLOCKED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _decide_go_no_go(
    inventory: dict[str, Any],
    compat: dict[str, Any],
    full_obs: dict[str, Any],
) -> str:
    has_approved = inventory.get("candidate_count_approved_local", 0) > 0
    overall_cls = compat.get("overall_classification")
    if has_approved and overall_cls == "COMPATIBLE_WITH_CURRENT_V2_POLICY":
        return GO_FOR_CHECKPOINT
    if overall_cls == "REQUIRES_V2_POLICY_ARCHITECTURE_PORT":
        return GO_FOR_POLICY_PORT
    if overall_cls == "REQUIRES_OBSERVATION_VECTOR_EXPANSION":
        return GO_FOR_FULL_OBS
    if full_obs.get("state") == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS":
        return GO_FOR_FULL_OBS
    return GO_BLOCKED


def run_once() -> dict[str, Any]:
    inventory = build_inventory()
    contract = build_legacy_observation_contract()
    obs_gap = gap_vs_v2_compact(contract)
    full_obs = write_full_observation_status(
        WORKLOG_DIR / "full_observation_builder_status.json",
        RL_CORE_PUBLIC_DIR / "full_observation_builder_status.json",
    )
    # also publish to the model-parity public dir for the panel
    _write_json(
        PUBLIC_DIR / "full_observation_builder_status.json", full_obs
    )
    compat = write_compatibility_status(
        WORKLOG_DIR / "policy_architecture_compatibility.json",
        PUBLIC_DIR / "policy_architecture_compatibility.json",
    )
    shadow = write_shadow_metrics(
        WORKLOG_DIR / "model_decision_match_shadow_metrics.json",
        PUBLIC_DIR / "model_decision_match_shadow_metrics.json",
    )
    _write_json(WORKLOG_DIR / "checkpoint_candidate_inventory.json", inventory)
    _write_json(PUBLIC_DIR / "checkpoint_candidate_inventory.json", inventory)
    _write_json(WORKLOG_DIR / "legacy_observation_shape_contract.json", contract)
    _write_json(PUBLIC_DIR / "legacy_observation_shape_contract.json", contract)
    _write_json(WORKLOG_DIR / "v2_vs_legacy_observation_gap_matrix.json", obs_gap)
    _write_json(PUBLIC_DIR / "v2_vs_legacy_observation_gap_matrix.json", obs_gap)
    go_no_go = _decide_go_no_go(inventory, compat, full_obs)
    status = {
        "schema_version": "v2_model_parity_sprint_status_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": go_no_go,
        "checkpoint_inventory_summary": {
            "approved_local": inventory.get("candidate_count_approved_local"),
            "legacy_reference_total_in_inventory_cap": inventory.get(
                "candidate_count_legacy_reference"
            ),
            "extension_counts_legacy_exhaustive": inventory.get(
                "extension_counts_exhaustive_legacy"
            ),
            "extension_counts_approved_exhaustive": inventory.get(
                "extension_counts_exhaustive_approved"
            ),
            "source_classification_counts": inventory.get(
                "source_classification_counts"
            ),
        },
        "legacy_observation_summary": {
            "schema_versions": contract.get("legacy_observation_schema_versions"),
            "total_dim_by_version": contract.get(
                "legacy_observation_total_dim_by_version"
            ),
            "largest_observation_dim": contract.get(
                "legacy_observation_largest_dim"
            ),
            "action_space_size_resolved": (
                contract.get("legacy_action_space") or {}
            ).get("action_space_size_resolved"),
        },
        "observation_gap": {
            "v2_compact_dim": obs_gap.get("v2_native_compact_observation_dim"),
            "legacy_largest_dim": obs_gap.get("legacy_largest_observation_dim"),
            "dim_gap": obs_gap.get("observation_dim_gap_legacy_minus_v2"),
            "observation_compatibility": obs_gap.get("observation_compatibility"),
            "action_space_compatibility": obs_gap.get(
                "action_space_compatibility"
            ),
        },
        "full_observation_builder_state": full_obs.get("state"),
        "full_observation_builder_missing_categories": full_obs.get(
            "full_observation_v1", {}
        ).get("missing_observation_categories"),
        "full_observation_builder_partial_categories": full_obs.get(
            "full_observation_v1", {}
        ).get("partial_observation_categories"),
        "policy_architecture_classifications": compat.get("classifications"),
        "policy_architecture_overall_classification": compat.get(
            "overall_classification"
        ),
        "decision_match_shadow": {
            "symbols_total": shadow.get("symbols_total"),
            "action_match_count": shadow.get("action_match_count"),
            "action_match_rate": shadow.get("action_match_rate"),
            "v2_hold_due_checkpoint_count": shadow.get(
                "v2_hold_due_checkpoint_count"
            ),
            "v2_hold_due_strict_gate_count": shadow.get(
                "v2_hold_due_strict_gate_count"
            ),
            "no_action_safe_block_count": shadow.get("no_action_safe_block_count"),
            "next_required_by_symbol": shadow.get("next_required_by_symbol"),
        },
        "narrow_remediation_tasks_required": compat.get(
            "narrow_remediation_tasks_required"
        ),
        "paired_codex_review_task_ids_required": compat.get(
            "paired_codex_review_task_ids_required"
        ),
        "soak_runtime_unaffected": True,
        "legacy_runtime_unaffected": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "no_checkpoint_blob_committed_to_git": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_json(WORKLOG_DIR / "model_parity_sprint_status.json", status)
    _write_json(PUBLIC_DIR / "operator_dashboard_payload.json", status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_model_parity_sprint_status")
    parser.add_argument("--once", action="store_true")
    parser.parse_args(argv or [])
    status = run_once()
    print(
        json.dumps(
            {
                "go_no_go": status["go_no_go"],
                "observation_gap": status["observation_gap"],
                "full_observation_state": status["full_observation_builder_state"],
                "policy_classifications": status[
                    "policy_architecture_classifications"
                ],
                "decision_match": status["decision_match_shadow"],
            },
            indent=None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
