"""Tests for the V2 policy-architecture shape-contract prep packet.

Paper-only. No torch import. No port implementation. Extraction only.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _mod():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.policy_architecture_shape_contract"
    )


def test_extracts_input_observation_v3_target_1911() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    assert c["input_observation"]["target_dim"] == 1911
    assert c["input_observation"]["schema_version"] == "V3"
    assert any(
        s.get("name") == "unified_features" for s in c["input_observation"]["slices"]
    )


def test_extracts_action_space_59049_per_symbol_3() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    assert c["action_space"]["joint_action_count"] == 59049
    assert c["action_space"]["per_symbol_actions"] == 3
    assert c["action_space"]["per_symbol_action_labels_hint"] == [
        "hold", "long", "short"
    ]
    # The joint mapping must be documented, not invented at runtime.
    assert "3 ** i" in c["action_space"]["joint_action_decomposition"]


def test_architecture_components_present_lstm_attention_moe_cnn_regime() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    comps = c["architecture_components_present"]
    assert comps["lstm"] is True
    assert comps["multihead_attention"] is True
    assert comps["regime_head"] is True
    assert comps["moe"] is True
    assert comps["cnn"] is True


def test_does_not_claim_port_complete() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    assert c["policy_port_implementation_claimed"] is False
    assert c["checkpoint_compatibility_claimed"] is False
    assert c["operator_decision_required_to_implement_port"] is True


def test_v2_trainer_output_fields_documented() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    fields = c["v2_trainer_output_contract"]["v2_trainer_output_fields"]
    # The P0.2F gate fields the future port must preserve.
    must_have = {
        "paper_fill_allowed",
        "paper_fill_gate_status",
        "paper_fill_gate_block_reasons",
        "selected_action",
        "expected_move_after_cost_bps",
        "confidence_calibrated",
    }
    fields_set = set(fields)
    missing = must_have - fields_set
    # Some of these are reachable only via prefix patterns; tolerate
    # partial-prefix matches by checking any field starts with name.
    for needle in list(missing):
        if any(f.startswith(needle) or needle in f for f in fields):
            missing.discard(needle)
    assert not missing, f"trainer output contract missing: {missing}"


def test_safety_invariants_in_payload() -> None:
    mod = _mod()
    c = mod.build_policy_architecture_shape_contract()
    assert c["live_gate"] == "blocked_human_only"
    assert c["live_symbols"] == []
    assert c["approves_live"] is False
    assert c["approves_canary"] is False
    assert c["approves_legacy_shutdown"] is False
    assert c["approves_redis_trim"] is False


def test_cli_writes_payload(tmp_path: Path, monkeypatch) -> None:
    cli = importlib.import_module(
        "v2.backend.app.cli.v2_policy_architecture_shape_contract_status"
    )
    worklog = tmp_path / "wl/policy_shape.json"
    dash = tmp_path / "dash/op.json"
    monkeypatch.setattr(cli, "WORKLOG_STATUS", worklog)
    monkeypatch.setattr(cli, "PUBLIC_DASHBOARD", dash)
    rc = cli.main(["--once"])
    assert rc == 0
    a = json.loads(worklog.read_text())
    b = json.loads(dash.read_text())
    assert a == b
    assert a["go_no_go"] == "V2_POLICY_ARCHITECTURE_SHAPE_CONTRACT_PREP_READY"


def test_no_torch_imported() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.policy_architecture_shape_contract"
    )
    importlib.import_module(
        "v2.backend.app.cli.v2_policy_architecture_shape_contract_status"
    )
    assert "torch" not in sys.modules
