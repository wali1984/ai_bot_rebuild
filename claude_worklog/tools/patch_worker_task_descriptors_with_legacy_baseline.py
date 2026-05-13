#!/usr/bin/env python3
"""Patch every claude_port_v2_* and codex_review_v2_* descriptor with the
legacy-baseline enforcement contract.

Every Claude worker task descriptor gains:
  - `required_legacy_baseline_files`: explicit list with the two required
    pre-implementation deliverables
  - `required_output_files`: legacy baseline files appended (if missing)
  - `forbidden`: greenfield-without-justification, dropping legacy behavior
    silently, ignoring legacy Redis/config/stream contracts without reason
  - `prompt`: a legacy-first preamble describing the mandate

Every Codex review descriptor gains:
  - `fail_conditions`: missing legacy baseline / missing behavior mapping /
    greenfield-without-justification / legacy features dropped silently /
    behavior changed without explanation
  - `required_input_files`: legacy baseline files (so Codex must read them)

Idempotent: re-running the script on an already-patched descriptor is a
no-op (each field is checked for presence before append).

Usage:
    python3 claude_worklog/tools/patch_worker_task_descriptors_with_legacy_baseline.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"

# Strict worker sequence (must match orchestrator).
WORKERS = [
    "v2_feature_snapshot_builder",
    "v2_risk_gateway_runtime_worker",
    "v2_paper_execution_worker",
    "v2_execution_ledger_worker",
    "v2_signal_lineage_worker",
    "v2_account_position_monitor",
    "v2_market_ingestor",
    "v2_coinank_liquidation_bridge",
    "v2_trainer_bridge",
    "v2_orchestrator_adapter",
    "v2_signal_publisher",
    "v2_replay_worker",
    "v2_script_monitor",
    "v2_config_admin_manager",
    "v2_p2_default_blocked_execution_adapter_stub",
    "v2_p2_binance_usdm_adapter_stub",
    "v2_p2_deployment_helpers",
]

WORKER_REPORT_ROOT = "claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers"

LEGACY_BASELINE_FORBIDDEN_ITEMS = [
    "greenfield_without_legacy_baseline",
    "dropping_legacy_behavior_silently",
    "ignoring_legacy_redis_or_config_or_stream_contracts_without_reason",
    "behavior_change_without_explanation",
]

LEGACY_BASELINE_PROMPT_PREAMBLE = (
    "LEGACY-FIRST MANDATE. This is not a greenfield build. Before writing any V2 "
    "implementation code, you MUST read the relevant files under legacy_reference/, "
    "identify the exact legacy source paths/functions/classes that own this "
    "responsibility today, and produce TWO required files:\n"
    "  1. claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/<worker_id>_LEGACY_BASELINE_ANALYSIS.md\n"
    "  2. claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/<worker_id>_legacy_behavior_mapping.json\n"
    "The analysis must list: legacy_source_paths, legacy_functions_preserved, "
    "legacy_inputs, legacy_outputs, legacy_redis_keys (read-only references; never "
    "writers), legacy_config_dependencies, legacy_edge_cases, legacy_failure_modes, "
    "legacy_tests_or_expected_behavior, V2_mapping, intentional_changes, and any "
    "removed/deprecated behavior with reason. The mapping JSON must be a structured "
    "version of the same. If legacy_reference has no equivalent, justify the "
    "greenfield decision in writing with citations. Codex will fail the review "
    "if either file is missing, vague, or silently drops legacy behavior.\n\n"
    "Only after both baseline files exist may you implement the worker.\n\n"
)

LEGACY_CODEX_FAIL_CONDITIONS = [
    "legacy_baseline_analysis_md_missing",
    "legacy_behavior_mapping_json_missing",
    "greenfield_implementation_without_documented_justification",
    "legacy_features_dropped_silently",
    "legacy_redis_or_config_or_stream_contracts_ignored_without_reason",
    "behavior_changed_without_explanation_in_mapping",
    "tests_do_not_cover_legacy_equivalent_behavior",
    "worker_claims_migrated_while_only_newly_scaffolded",
]


def patch_claude_port(descriptor: Dict[str, Any], worker_id: str) -> bool:
    """Return True if descriptor was modified."""
    modified = False
    baseline_md = f"{WORKER_REPORT_ROOT}/{worker_id}_LEGACY_BASELINE_ANALYSIS.md"
    mapping_json = f"{WORKER_REPORT_ROOT}/{worker_id}_legacy_behavior_mapping.json"

    required_legacy = descriptor.setdefault("required_legacy_baseline_files", [])
    for f in (baseline_md, mapping_json):
        if f not in required_legacy:
            required_legacy.append(f)
            modified = True

    required_outputs = descriptor.setdefault("required_output_files", [])
    for f in (baseline_md, mapping_json):
        if f not in required_outputs:
            required_outputs.append(f)
            modified = True

    forbidden = descriptor.setdefault("forbidden", [])
    for f in LEGACY_BASELINE_FORBIDDEN_ITEMS:
        if f not in forbidden:
            forbidden.append(f)
            modified = True

    prompt = descriptor.get("prompt") or ""
    if "LEGACY-FIRST MANDATE" not in prompt:
        descriptor["prompt"] = LEGACY_BASELINE_PROMPT_PREAMBLE + prompt
        modified = True

    if not descriptor.get("legacy_baseline_required"):
        descriptor["legacy_baseline_required"] = True
        modified = True

    return modified


def patch_codex_review(descriptor: Dict[str, Any], worker_id: str) -> bool:
    modified = False
    baseline_md = f"{WORKER_REPORT_ROOT}/{worker_id}_LEGACY_BASELINE_ANALYSIS.md"
    mapping_json = f"{WORKER_REPORT_ROOT}/{worker_id}_legacy_behavior_mapping.json"

    required_inputs = descriptor.setdefault("required_input_files", [])
    for f in (baseline_md, mapping_json):
        if f not in required_inputs:
            required_inputs.append(f)
            modified = True

    fail_conditions = descriptor.setdefault("fail_conditions", [])
    for f in LEGACY_CODEX_FAIL_CONDITIONS:
        if f not in fail_conditions:
            fail_conditions.append(f)
            modified = True

    prompt = descriptor.get("prompt") or ""
    legacy_note = (
        " LEGACY-BASELINE GATE: this review must FAIL if "
        f"{baseline_md} or {mapping_json} is missing, if the worker silently drops "
        "documented legacy behavior, or if tests do not cover the legacy-equivalent "
        "behavior named in the mapping."
    )
    if "LEGACY-BASELINE GATE" not in prompt:
        descriptor["prompt"] = prompt + legacy_note
        modified = True

    return modified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary: List[Dict[str, Any]] = []
    overall_modified = 0
    for worker_id in WORKERS:
        for kind, path in (
            ("claude_port", TASKS_DIR / f"claude_port_{worker_id}.json"),
            ("codex_review", TASKS_DIR / f"codex_review_{worker_id}.json"),
        ):
            if not path.exists():
                summary.append({"kind": kind, "worker": worker_id, "result": "MISSING"})
                continue
            try:
                data = json.loads(path.read_text())
            except Exception as exc:
                summary.append({"kind": kind, "worker": worker_id, "result": f"PARSE_ERROR: {exc}"})
                continue
            if kind == "claude_port":
                changed = patch_claude_port(data, worker_id)
            else:
                changed = patch_codex_review(data, worker_id)
            if changed:
                overall_modified += 1
                if not args.dry_run:
                    path.write_text(json.dumps(data, indent=2, sort_keys=False))
                summary.append({"kind": kind, "worker": worker_id, "result": "PATCHED"})
            else:
                summary.append({"kind": kind, "worker": worker_id, "result": "ALREADY_PATCHED"})

    for row in summary:
        print(f"{row['result']:18}  {row['kind']:14}  {row['worker']}")
    print(f"\n{overall_modified} descriptors modified ({'dry-run' if args.dry_run else 'written'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
