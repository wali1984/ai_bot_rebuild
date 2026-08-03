"""Read-only policy-architecture compatibility analysis.

Compares V2's current paper policy (26-dim observation, 16-dim hidden,
5-action MLP) against the legacy production architecture
(LSTM + multi-head attention + MoE + CNN, 1911-dim observation, 3^10
joint action space). Static analysis only — no torch import, no pickle
load.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.legacy_observation_contract import (
    build_legacy_observation_contract,
    gap_vs_v2_compact,
)

V2_POLICY_FACTS: dict[str, Any] = {
    "module": "v2.backend.app.services.rl_core.policy",
    "obs_dim": 26,
    "hidden_dim": 16,
    "action_count": 5,
    "action_labels": ["hold", "long", "short", "close", "hedge"],
    "has_lstm": False,
    "has_attention": False,
    "has_regime_head": False,
    "has_moe": False,
    "has_cnn": False,
    "value_head": True,
    "expected_move_head": True,
    "deterministic_init": True,
    "torch_loaded_in_v2_process": False,
}

CLASSIFICATION_COMPATIBLE = "COMPATIBLE_WITH_CURRENT_V2_POLICY"
CLASSIFICATION_REQUIRES_POLICY_PORT = "REQUIRES_V2_POLICY_ARCHITECTURE_PORT"
CLASSIFICATION_REQUIRES_OBS_EXPANSION = "REQUIRES_OBSERVATION_VECTOR_EXPANSION"
CLASSIFICATION_UNKNOWN_METADATA = "UNKNOWN_METADATA_REQUIRED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def analyze_compatibility() -> dict[str, Any]:
    contract = build_legacy_observation_contract()
    gap = gap_vs_v2_compact(contract)
    legacy_arch = contract.get("legacy_architecture") or {}
    legacy_action_size = (contract.get("legacy_action_space") or {}).get(
        "action_space_size_resolved"
    )
    legacy_largest = contract.get("legacy_observation_largest_dim")
    classifications: list[str] = []
    if legacy_largest and legacy_largest > V2_POLICY_FACTS["obs_dim"]:
        classifications.append(CLASSIFICATION_REQUIRES_OBS_EXPANSION)
    if (
        legacy_arch.get("has_lstm")
        or legacy_arch.get("has_attention")
        or legacy_arch.get("has_moe")
        or legacy_arch.get("has_cnn")
    ):
        classifications.append(CLASSIFICATION_REQUIRES_POLICY_PORT)
    if (
        legacy_action_size is not None
        and legacy_action_size != V2_POLICY_FACTS["action_count"]
    ):
        classifications.append(CLASSIFICATION_REQUIRES_POLICY_PORT)
    if not classifications:
        classifications.append(CLASSIFICATION_UNKNOWN_METADATA)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for c in classifications:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    overall = (
        CLASSIFICATION_REQUIRES_POLICY_PORT
        if CLASSIFICATION_REQUIRES_POLICY_PORT in deduped
        else (
            CLASSIFICATION_REQUIRES_OBS_EXPANSION
            if CLASSIFICATION_REQUIRES_OBS_EXPANSION in deduped
            else CLASSIFICATION_UNKNOWN_METADATA
        )
    )
    return {
        "schema_version": "v2_policy_architecture_compatibility_v1",
        "generated_utc": _utc_iso(),
        "v2_policy_facts": V2_POLICY_FACTS,
        "legacy_architecture_facts": legacy_arch,
        "legacy_action_space_size_resolved": legacy_action_size,
        "legacy_largest_observation_dim": legacy_largest,
        "observation_dim_gap_legacy_minus_v2": gap.get(
            "observation_dim_gap_legacy_minus_v2"
        ),
        "classifications": deduped,
        "overall_classification": overall,
        "narrow_remediation_tasks_required": [
            "claude_fix_v2_gap_policy_architecture_shape_contract",
            "claude_fix_v2_gap_full_observation_vector_builder",
        ]
        if overall != CLASSIFICATION_COMPATIBLE
        else [],
        "paired_codex_review_task_ids_required": [
            "codex_review_fix_v2_gap_policy_architecture_shape_contract",
            "codex_review_fix_v2_gap_full_observation_vector_builder",
        ]
        if overall != CLASSIFICATION_COMPATIBLE
        else [],
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_compatibility_status(
    worklog_path: Path, public_path: Path
) -> dict[str, Any]:
    payload = analyze_compatibility()
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.write_text(body, encoding="utf-8")
    public_path.write_text(body, encoding="utf-8")
    return payload
