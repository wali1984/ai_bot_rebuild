"""P0.2G integration tests: trainer algorithm completion."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


# ---------- PPO clipped surrogate objective ----------


def test_ppo_ratio_matches_exp_of_logprob_diff() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import ratio

    r = ratio(new_log_prob=math.log(0.6), old_log_prob=math.log(0.3))
    assert math.isclose(r, 2.0, rel_tol=1e-9)


def test_ppo_policy_loss_clipped_when_ratio_above_one_plus_eps() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import (
        clipped_policy_loss_per_sample,
    )

    # Ratio 1.5 with eps 0.2 should clip to 1.2; advantage positive => loss = -1.2*A.
    loss, clipped = clipped_policy_loss_per_sample(r=1.5, advantage=2.0, clip_epsilon=0.2)
    assert clipped is True
    assert math.isclose(loss, -(1.2 * 2.0), rel_tol=1e-9)


def test_ppo_policy_loss_unclipped_when_ratio_within_band() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import (
        clipped_policy_loss_per_sample,
    )

    loss, clipped = clipped_policy_loss_per_sample(r=1.05, advantage=3.0, clip_epsilon=0.2)
    assert clipped is False
    assert math.isclose(loss, -(1.05 * 3.0), rel_tol=1e-9)


def test_ppo_value_loss_is_mean_squared_error() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import (
        mean_squared_value_loss,
    )

    v = mean_squared_value_loss(values_pred=[1.0, 2.0, 3.0], returns=[1.0, 0.0, 5.0])
    # ((0)^2 + (2)^2 + (-2)^2) / 3 = (0 + 4 + 4) / 3
    assert math.isclose(v, 8.0 / 3.0, rel_tol=1e-9)


def test_ppo_entropy_is_zero_for_one_hot_distribution() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import (
        discrete_entropy_per_sample,
    )

    assert discrete_entropy_per_sample([1.0, 0.0, 0.0, 0.0, 0.0]) == 0.0


def test_ppo_compute_ppo_loss_returns_breakdown_with_all_components() -> None:
    from v2.backend.app.services.rl_core.ppo_objective import compute_ppo_loss

    out = compute_ppo_loss(
        new_log_probs=[math.log(0.5), math.log(0.4)],
        old_log_probs=[math.log(0.5), math.log(0.5)],
        advantages=[1.0, -1.0],
        values_pred=[0.5, 0.7],
        returns=[1.0, 0.0],
        action_prob_rows=[[0.5, 0.5], [0.4, 0.6]],
        safety_penalties_bps=[0.0, -50.0],
        clip_epsilon=0.2,
    )
    assert out.sample_count == 2
    assert 0.0 <= out.ratio_clipped_fraction <= 1.0
    assert isinstance(out.policy_loss, float)
    assert isinstance(out.value_loss, float)
    assert isinstance(out.entropy_bonus, float)
    assert isinstance(out.safety_penalty, float)


# ---------- GAE ----------


def test_gae_matches_hand_calculated_example_no_dones() -> None:
    from v2.backend.app.services.rl_core.gae import compute_gae

    # rewards=[1,1,1], values=[0,0,0], dones=[0,0,0], last_value=0,
    # gamma=1.0, lam=1.0 -> A_t = sum(rewards from t to end) - V_t
    out = compute_gae(
        rewards=[1.0, 1.0, 1.0],
        values=[0.0, 0.0, 0.0],
        dones=[0, 0, 0],
        last_value=0.0,
        gamma=1.0,
        lam=1.0,
        normalize_advantages=False,
    )
    assert out.advantages == (3.0, 2.0, 1.0)
    assert out.returns == (3.0, 2.0, 1.0)


def test_gae_done_mask_truncates_propagation() -> None:
    from v2.backend.app.services.rl_core.gae import compute_gae

    # done at t=1 should zero out the propagation from A_{t+1}.
    out = compute_gae(
        rewards=[1.0, 1.0, 1.0],
        values=[0.0, 0.0, 0.0],
        dones=[0, 1, 0],
        last_value=0.0,
        gamma=1.0,
        lam=1.0,
        normalize_advantages=False,
    )
    # A_2 = 1 + 1*0*0 - 0 = 1
    # A_1 = 1 + 1*0*0 - 0 (done propagation zeroed; bootstrap also zeroed) = 1
    # A_0 = 1 + 1*0*0 - 0 = ... wait, done_0 is 0 so propagation is on.
    # delta_0 = r_0 + gamma*V_1*(1-done_0) - V_0 = 1 + 1*0*1 - 0 = 1
    # A_0 = delta_0 + gamma*lam*(1-done_0)*A_1 = 1 + 1*1*1*1 = 2
    assert out.advantages == (2.0, 1.0, 1.0)


def test_gae_normalize_advantages_yields_zero_mean_unit_std() -> None:
    from v2.backend.app.services.rl_core.gae import compute_gae

    out = compute_gae(
        rewards=[1.0, -1.0, 2.0, 0.0],
        values=[0.0, 0.0, 0.0, 0.0],
        dones=[0, 0, 0, 0],
        last_value=0.0,
        gamma=0.99,
        lam=0.95,
        normalize_advantages=True,
    )
    assert out.normalized is True
    mean = sum(out.advantages) / len(out.advantages)
    assert abs(mean) < 1e-6


def test_gae_validates_input_lengths() -> None:
    from v2.backend.app.services.rl_core.gae import compute_gae

    with pytest.raises(ValueError):
        compute_gae(
            rewards=[1.0, 2.0],
            values=[0.0],
            dones=[0, 0],
        )


# ---------- AdamW optimizer state ----------


def test_adamw_step_changes_state_and_parameter() -> None:
    from v2.backend.app.services.rl_core.optimizer_state import (
        AdamWState,
        adamw_step,
    )

    p = [1.0, -2.0, 0.5]
    grad = [0.1, -0.2, 0.3]
    s = AdamWState(name="w", length=3, lr=0.1)
    p_before = list(p)
    adamw_step(s, parameter=p, gradient=grad)
    assert s.step == 1
    assert p != p_before
    # m should not be all zero after one step
    assert any(abs(x) > 0 for x in s.m)
    assert any(abs(x) > 0 for x in s.v)


def test_adamw_repeated_steps_increment_step_and_change_moments() -> None:
    from v2.backend.app.services.rl_core.optimizer_state import (
        AdamWState,
        adamw_step,
    )

    p = [0.0, 0.0]
    s = AdamWState(name="b", length=2, lr=0.05)
    for _ in range(3):
        adamw_step(s, parameter=p, gradient=[1.0, -1.0])
    assert s.step == 3
    # After 3 steps with consistent gradient direction, parameter should have moved.
    assert p[0] < 0
    assert p[1] > 0


def test_adamw_invalid_length_raises() -> None:
    from v2.backend.app.services.rl_core.optimizer_state import (
        AdamWState,
        adamw_step,
    )

    s = AdamWState(name="x", length=3)
    with pytest.raises(ValueError):
        adamw_step(s, parameter=[0.0, 0.0], gradient=[1.0, 1.0])


# ---------- Trainer algo completion status ----------


def test_trainer_algo_completion_status_paper_only_ready() -> None:
    from v2.backend.app.services.rl_core.trainer_algo_status import (
        compute_trainer_algo_completion_status,
    )

    s = compute_trainer_algo_completion_status()
    assert s.ppo_clip_status == "PPO_CLIP_LOSS_READY_PAPER_ONLY"
    assert s.gae_status == "GAE_ADVANTAGE_ESTIMATION_READY_PAPER_ONLY"
    assert s.optimizer_state_status == "ADAMW_OPTIMIZER_STATE_READY_PAPER_ONLY"
    assert s.checkpoint_weight_status == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert s.hedge_status.startswith("HEDGE_FAIL_CLOSED")
    assert "P0_4_paper_hedge_engine" in s.hedge_block_reason
    assert s.migration_classification == "PAPER_ONLY_TRAINER_ALGO_READY_P0_2G"


def test_trainer_algo_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.trainer_algo_status import (
        trainer_algo_invariants_snapshot,
    )

    s = trainer_algo_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["imports_torch"] is False
    assert s["approves_live"] is False
    assert s["approves_legacy_shutdown"] is False


# ---------- Forbidden imports ----------


@pytest.mark.parametrize("rel", [
    "v2/backend/app/services/rl_core/ppo_objective.py",
    "v2/backend/app/services/rl_core/gae.py",
    "v2/backend/app/services/rl_core/optimizer_state.py",
    "v2/backend/app/services/rl_core/trainer_algo_status.py",
])
def test_p0_2g_modules_have_no_forbidden_imports(rel: str) -> None:
    text = (REPO / rel).read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import stable_baselines3", "from stable_baselines3",
        "import gymnasium", "from gymnasium",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"{rel} contains forbidden: {forbidden}"
