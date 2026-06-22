"""Tests for the V2 full-observation builder + model-parity sprint.

Paper-only. No torch import. No legacy mutation. No pickle load.
"""
from __future__ import annotations

import importlib
import sys


def test_contract_extracts_v1_v2_v3_total_dims() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.legacy_observation_contract"
    )
    c = mod.build_legacy_observation_contract()
    totals = c["legacy_observation_total_dim_by_version"]
    assert totals.get("V1") == 1053
    assert totals.get("V2") == 1061
    assert totals.get("V3") == 1911
    assert c["legacy_observation_largest_dim"] == 1911


def test_legacy_action_space_resolved_to_3_pow_10() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.legacy_observation_contract"
    )
    c = mod.build_legacy_observation_contract()
    # 3^10 = 59049 from the legacy environment.py inline comment.
    assert c["legacy_action_space"]["action_space_size_resolved"] == 59049
    assert c["legacy_action_space"]["per_symbol_actions"] == 3


def test_obs_gap_marks_incompatibility() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.legacy_observation_contract"
    )
    c = mod.build_legacy_observation_contract()
    g = mod.gap_vs_v2_compact(c)
    assert g["v2_native_compact_observation_dim"] == 26
    assert g["legacy_largest_observation_dim"] == 1911
    assert g["observation_dim_gap_legacy_minus_v2"] == 1885
    assert g["observation_compatibility"] == "INCOMPATIBLE_OBSERVATION_VECTOR_SHAPE_REQUIRES_PORT"
    assert g["action_space_compatibility"] == "INCOMPATIBLE_ACTION_SPACE_REQUIRES_PORT"


def test_full_observation_builder_reports_partial_with_missing_categories() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    s = mod.build_full_observation_status()
    assert s["state"] == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    assert s["operator_required"] is True
    # The V2 compact policy input is preserved.
    assert s["compact_observation_v1"]["dim"] == 26
    assert s["compact_observation_v1"]["kept_as_current_runtime_policy_input"] is True
    # The V3 target dim must be 1911 with named missing/partial slices.
    assert s["full_observation_v1"]["target_dim"] == 1911
    missing = set(s["full_observation_v1"]["missing_observation_categories"])
    partial = set(s["full_observation_v1"]["partial_observation_categories"])
    # onchain has no V2-native source today and must remain fully missing.
    assert {"onchain_btc", "onchain_eth"}.issubset(missing)
    # unified_features now gets 23-of-1430 V2 native dims so it lives in
    # partial rather than missing once the runtime builder is active.
    assert "unified_features" in (missing | partial)
    assert s["full_observation_v1"]["checkpoint_compatibility_claimed"] is False


def test_policy_architecture_classification_requires_port() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.policy_architecture_compatibility"
    )
    a = mod.analyze_compatibility()
    assert (
        a["overall_classification"]
        == "REQUIRES_V2_POLICY_ARCHITECTURE_PORT"
    )
    assert "claude_fix_v2_gap_policy_architecture_shape_contract" in (
        a["narrow_remediation_tasks_required"]
    )
    assert "codex_review_fix_v2_gap_full_observation_vector_builder" in (
        a["paired_codex_review_task_ids_required"]
    )
    assert a["v2_policy_facts"]["obs_dim"] == 26
    assert a["v2_policy_facts"]["action_count"] == 5


def test_decision_match_shadow_no_invented_outcomes() -> None:
    mod = importlib.import_module(
        "v2.backend.app.services.rl_core.decision_match_shadow"
    )
    m = mod.compute_shadow_metrics()
    assert m["no_invented_outcomes"] is True
    assert m["paper_edge_claimed"] is False
    assert m["live_gate"] == "blocked_human_only"
    assert m["live_symbols"] == []


def test_sprint_status_decides_policy_port() -> None:
    mod = importlib.import_module(
        "v2.backend.app.cli.v2_model_parity_sprint_status"
    )
    status = mod.run_once()
    assert status["go_no_go"] == "V2_MODEL_PARITY_SPRINT_READY_FOR_POLICY_ARCHITECTURE_PORT"
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["approves_legacy_shutdown"] is False


def test_no_torch_imported_anywhere_in_parity_modules() -> None:
    sys.modules.pop("torch", None)
    for name in (
        "v2.backend.app.services.rl_core.checkpoint_inventory",
        "v2.backend.app.services.rl_core.legacy_observation_contract",
        "v2.backend.app.services.rl_core.full_observation_builder",
        "v2.backend.app.services.rl_core.policy_architecture_compatibility",
        "v2.backend.app.services.rl_core.decision_match_shadow",
    ):
        importlib.import_module(name)
    assert "torch" not in sys.modules
