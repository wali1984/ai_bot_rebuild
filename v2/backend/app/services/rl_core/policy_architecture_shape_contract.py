"""Legacy policy-architecture shape contract — extraction only.

Extracts the exact legacy policy-architecture shape contract from the
V2-owned legacy mirror so the future policy-port lane has a stable,
auditable target. **This module does NOT implement the port. It does
NOT load torch. It does NOT deserialize any checkpoint.** It only
reads source files in `v2/legacy_owned_runtime/rl/` via static
parsing.
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.legacy_observation_contract import (
    LEGACY_RL_DIR,
    build_legacy_observation_contract,
)

ENHANCED_ARCH = LEGACY_RL_DIR / "enhanced_architectures.py"
GPU_CNN_POLICY = LEGACY_RL_DIR / "gpu_cnn_policy.py"
MOE_ROUTER = LEGACY_RL_DIR / "moe_router.py"
GYMNASIUM_WRAPPER = LEGACY_RL_DIR / "gymnasium_wrapper.py"
ENVIRONMENT = LEGACY_RL_DIR / "environment.py"
TRAINER_OUTPUT_V2 = Path("v2/backend/app/services/rl_core/trainer_output.py")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _arch_components_present(text: str) -> dict[str, bool]:
    return {
        "lstm": "nn.LSTM" in text or "self.lstm" in text or "lstm_hidden_size" in text,
        "multihead_attention": "MultiheadAttention" in text or "embed_dim=" in text,
        "feed_forward_network": "Linear(lstm_hidden_size" in text or "Linear(hidden_dim" in text,
        "layer_norm": "LayerNorm" in text,
        "regime_head": "regime_head" in text,
        "value_head": "value" in text and "Linear(" in text,
        "policy_head": "policy" in text or "ActorCriticPolicy" in text,
        "expected_move_head": "expected_move" in text,
    }


def _action_space_facts() -> dict[str, Any]:
    env_text = _read(ENVIRONMENT)
    expr_m = re.search(r"self\.action_space_size\s*=\s*([^\n#]+)", env_text)
    resolved_m = re.search(r"=\s*([0-9_,]+)\s*possible actions", env_text)
    n_symbols_m = re.search(r"self\.n_symbols\s*=\s*([^\n#]+)", env_text)
    per_symbol = None
    expr = expr_m.group(1).strip() if expr_m else None
    if expr and "3 ** len(SYMBOLS)" in expr:
        per_symbol = 3
    resolved: int | None = None
    if resolved_m:
        try:
            resolved = int(resolved_m.group(1).replace("_", "").replace(",", ""))
        except ValueError:
            resolved = None
    return {
        "source_file": str(ENVIRONMENT),
        "action_space_size_expr": expr,
        "action_space_size_resolved": resolved,
        "n_symbols_expr": n_symbols_m.group(1).strip() if n_symbols_m else None,
        "per_symbol_actions": per_symbol,
        "joint_action_decomposition": (
            "joint_action_id = sum(action_for_symbol[i] * (3 ** i) for i in range(N))"
            if per_symbol == 3
            else "MISSING_EVIDENCE"
        ),
        "per_symbol_action_labels_hint": (
            ["hold", "long", "short"] if per_symbol == 3 else []
        ),
    }


def _enhanced_arch_facts(text: str) -> dict[str, Any]:
    lstm_hidden = None
    lstm_layers = None
    embed_dim = None
    m = re.search(r"lstm_hidden_size\s*[:=]\s*(\d+)", text)
    if m:
        try:
            lstm_hidden = int(m.group(1))
        except ValueError:
            pass
    m = re.search(r"lstm_num_layers\s*[:=]\s*(\d+)", text)
    if m:
        try:
            lstm_layers = int(m.group(1))
        except ValueError:
            pass
    m = re.search(r"embed_dim\s*=\s*([^,)\n]+)", text)
    if m:
        embed_dim = m.group(1).strip()
    features_dim_m = re.search(r"features_dim\s*[:=]\s*(\d+)", text)
    features_dim = int(features_dim_m.group(1)) if features_dim_m else None
    regime_classes_m = re.search(r"regime_head\s*=\s*nn\.Linear\([^,]+,\s*(\d+)", text)
    regime_classes = int(regime_classes_m.group(1)) if regime_classes_m else None
    return {
        "lstm_hidden_size_default": lstm_hidden,
        "lstm_num_layers_default": lstm_layers,
        "multihead_attention_embed_dim_expr": embed_dim,
        "features_dim_default": features_dim,
        "regime_head_class_count": regime_classes,
        "uses_ActorCriticPolicy": "ActorCriticPolicy" in text,
    }


def _moe_facts(text: str) -> dict[str, Any]:
    return {
        "has_moe_router": "moe_router" in text or "class MoE" in text,
    }


def _cnn_facts(text: str) -> dict[str, Any]:
    return {
        "has_conv1d": "Conv1d" in text,
        "has_conv2d": "Conv2d" in text,
    }


def _v2_trainer_output_contract() -> dict[str, Any]:
    """Re-export the fields the V2 trainer-output contract already
    publishes (paper-only). Useful for the future port to keep the
    P0.2F paper-fill gate semantics intact.
    """
    text = _read(TRAINER_OUTPUT_V2)
    # Look for both quoted dict-key style and bare dataclass-field style.
    # Trainer fields are typically declared via dataclass: ``name: T`` and
    # also referenced as quoted dict keys in the gate dict.
    needles = (
        "paper_fill_allowed",
        "paper_fill_gate_status",
        "paper_fill_gate_block_reasons",
        "expected_move_after_cost_bps",
        "expected_move_bps",
        "confidence_calibrated",
        "confidence_raw",
        "selected_action",
        "selected_action_index",
        "policy_action_probabilities",
        "hedge_action_classification",
        "feature_freshness_state",
        "trainer_source",
        "prediction_id",
        "feature_snapshot_id",
        "checkpoint_id",
        "checkpoint_blocker",
        "generated_utc",
        "live_gate",
        "live_symbols",
    )
    fields_found: list[str] = []
    for name in needles:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
            fields_found.append(name)
    return {
        "source_file": str(TRAINER_OUTPUT_V2),
        "v2_trainer_output_fields": sorted(set(fields_found)),
        "note": (
            "Any future V2 policy port must continue to emit these "
            "fields so the P0.2F strict paper-fill gate and downstream "
            "comparator passthrough remain intact."
        ),
    }


def build_policy_architecture_shape_contract() -> dict[str, Any]:
    obs_contract = build_legacy_observation_contract()
    arch_text = _read(ENHANCED_ARCH)
    cnn_text = _read(GPU_CNN_POLICY)
    moe_text = _read(MOE_ROUTER)
    components = _arch_components_present(arch_text)
    components.update(
        {
            "moe": _moe_facts(moe_text)["has_moe_router"],
            "cnn": _cnn_facts(cnn_text)["has_conv1d"] or _cnn_facts(cnn_text)["has_conv2d"],
        }
    )
    arch_facts = _enhanced_arch_facts(arch_text)
    action_facts = _action_space_facts()
    v2_trainer_contract = _v2_trainer_output_contract()
    return {
        "schema_version": "v2_policy_architecture_shape_contract_v1",
        "generated_utc": _utc_iso(),
        "source_files": {
            "enhanced_architectures": str(ENHANCED_ARCH),
            "gpu_cnn_policy": str(GPU_CNN_POLICY),
            "moe_router": str(MOE_ROUTER),
            "gymnasium_wrapper": str(GYMNASIUM_WRAPPER),
            "environment": str(ENVIRONMENT),
            "v2_trainer_output": str(TRAINER_OUTPUT_V2),
        },
        "input_observation": {
            "target_dim": obs_contract.get("legacy_observation_largest_dim"),
            "schema_version": "V3" if obs_contract.get("legacy_observation_largest_dim") == 1911 else "unknown",
            "slices": obs_contract.get("legacy_observation_slices_by_version", {}).get("V3", []),
        },
        "action_space": {
            "joint_action_count": action_facts.get("action_space_size_resolved"),
            "joint_action_count_expr": action_facts.get("action_space_size_expr"),
            "per_symbol_actions": action_facts.get("per_symbol_actions"),
            "per_symbol_action_labels_hint": action_facts.get(
                "per_symbol_action_labels_hint"
            ),
            "n_symbols_expr": action_facts.get("n_symbols_expr"),
            "joint_action_decomposition": action_facts.get(
                "joint_action_decomposition"
            ),
        },
        "architecture_components_present": components,
        "architecture_defaults": arch_facts,
        "v2_trainer_output_contract": v2_trainer_contract,
        "policy_port_implementation_claimed": False,
        "checkpoint_compatibility_claimed": False,
        "operator_decision_required_to_implement_port": True,
        "next_required_step": (
            "Codex review of the full observation builder must pass first; "
            "only then is the policy architecture port a parity candidate."
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
    }
