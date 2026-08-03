"""V2 checkpoint weight burndown focused tests.

Verifies the burndown's contract surface:

- V2 control plane never loads torch weights, even when a candidate
  exists.
- V2 policy shape contract advertised in the burndown matches the
  module truth (observation dim, hidden dim, action count).
- The strict paper-fill gate is not loosened by this packet.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
BURNDOWN_STATUS = (
    REPO
    / "claude_worklog/final_readiness/v2_checkpoint_weight_burndown/latest/checkpoint_weight_burndown_status.json"
)


def test_burndown_status_file_exists_and_says_operator_required() -> None:
    assert BURNDOWN_STATUS.exists(), f"missing {BURNDOWN_STATUS}"
    payload = json.loads(BURNDOWN_STATUS.read_text())
    assert payload["go_no_go"] == "V2_CHECKPOINT_WEIGHT_BURNDOWN_OPERATOR_REQUIRED"
    assert payload["checkpoint_weight_classification"] == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert payload["model_shape_status"] == "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH_LOAD_IN_V2"


def test_burndown_policy_shape_contract_matches_module_truth() -> None:
    from v2.backend.app.services.rl_core.policy import (
        ACTION_COUNT, POLICY_HIDDEN_DIM, POLICY_OBSERVATION_DIM,
    )
    payload = json.loads(BURNDOWN_STATUS.read_text())
    sc = payload["v2_policy_shape_contract"]
    assert sc["policy_observation_dim"] == POLICY_OBSERVATION_DIM
    assert sc["policy_hidden_dim"] == POLICY_HIDDEN_DIM
    assert sc["action_count"] == ACTION_COUNT


def test_checkpoint_safe_load_still_refuses_torch_load_even_when_candidates(tmp_path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import (
        inventory_checkpoints, safe_load_checkpoint,
    )
    # Plant a fake .pt to ensure the inventory has a candidate.
    (tmp_path / "ppo_masa_ckpt_1700000000_v1.pt").write_bytes(b"FAKE")
    inv = inventory_checkpoints([tmp_path])
    assert inv.candidate_count == 1
    res = safe_load_checkpoint(inv)
    assert res.weight_loading_status == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert res.model_shape_status == "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH"
    assert res.checkpoint_id is not None  # parsed metadata yields an id
    assert "v2_control_plane_does_not_load_torch_weights" in res.missing_checkpoint_blockers


def test_burndown_packet_does_not_loosen_paper_fill_gate() -> None:
    """Sanity: the burndown packet must not flip any safety invariant."""
    payload = json.loads(BURNDOWN_STATUS.read_text())
    s = payload["safety_state"]
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["approves_canary"] is False
    assert s["approves_legacy_shutdown"] is False
    assert s["approves_redis_trim"] is False
    assert s["torch_weights_loaded_into_v2_process"] is False
    assert s["checkpoint_blob_committed_to_git"] is False


def test_burndown_packet_does_not_claim_positive_paper_edge() -> None:
    payload = json.loads(BURNDOWN_STATUS.read_text())
    # The packet enumerates mismatches caused by deterministic-init weights;
    # it must not claim positive paper edge.
    expl = payload["v2_vs_legacy_mismatch_explained_by_weight_state"]
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in expl
    # No claim of "positive_paper_edge" anywhere in the payload.
    body = json.dumps(payload)
    assert "positive_paper_edge" not in body.lower()
    assert "edge_proven_positive" not in body.lower()


def test_burndown_packet_does_not_commit_blob_to_git() -> None:
    payload = json.loads(BURNDOWN_STATUS.read_text())
    assert payload["operator_action_required"]["option_1_provide_approved_blob"]["do_not_commit_blob_to_git"] is True


def test_checkpoint_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/rl_core/checkpoints.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"checkpoints.py contains forbidden: {forbidden}"
