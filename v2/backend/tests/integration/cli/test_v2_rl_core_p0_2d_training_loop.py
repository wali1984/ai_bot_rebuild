"""P0.2D integration tests: tiny CPU PPO update loop."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def _snapshot_fixture() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "worker_id": "v2_feature_pipeline_native",
        "feature_snapshot_id": "v2_fsnap_p0_2d_test",
        "generated_at": "2026-05-16T00:00:00+00:00",
        "symbol": "BTCUSDT", "timeframe": "1m",
        "features": {
            "ret_pct": 0.001, "log_return": 0.00099, "range_pct": 0.005,
            "body_pct": 0.0008, "true_range_pct": 0.006, "gap_pct": 0.0,
            "ema_12": 100.4, "ema_26": 100.2, "rsi_14": 55.0,
            "macd": 0.05, "macd_signal": 0.04, "macd_hist": 0.01,
            "bb_width_pct": 0.012, "htf_ret_pct": 0.002, "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 5.0, "depth_imbalance": 0.1, "micro_price": 100.0,
            "toxicity_proxy": 0.2, "funding_rate": 0.0001, "oi_change_pct": 0.01,
            "last_liq_bps_24h": 5.0, "paper_position_present": 0,
        },
        "feature_count": 23,
        "categories_present": [
            "ohlcv_derived","ta_indicators","multi_timeframe","microstructure",
            "funding_oi_liquidation","portfolio_aware","freshness",
        ],
        "missing_feature_flags": [], "stale_feature_flags": [],
        "feature_freshness_state": "CURRENT", "trainer_consumable": True,
        "live_gate": "blocked_human_only", "live_symbols": [],
    }


def test_tiny_cpu_training_reduces_loss() -> None:
    from v2.backend.app.services.rl_core.training_loop import run_tiny_cpu_training_loop

    res = run_tiny_cpu_training_loop(_snapshot_fixture(), steps=8, lr=0.05)
    assert res.steps >= 1
    assert res.policy_update_applied is True
    assert res.loss_after <= res.loss_before + 1e-6
    assert res.training_run_id.startswith("v2_native_cpu_train_")


def test_tiny_cpu_training_does_not_write_model_artifact_by_default() -> None:
    from v2.backend.app.services.rl_core.training_loop import run_tiny_cpu_training_loop

    res = run_tiny_cpu_training_loop(_snapshot_fixture(), steps=4)
    assert res.model_artifact_written is False


def test_tiny_cpu_training_outputs_reward_components_and_safety_flags() -> None:
    from v2.backend.app.services.rl_core.training_loop import run_tiny_cpu_training_loop

    res = run_tiny_cpu_training_loop(_snapshot_fixture(), steps=4)
    for key in ("base_pnl_reward_bps", "fee_aware_reward_bps",
                "constrained_safety_penalty_bps", "hedge_reward_bps"):
        assert key in res.reward_components_sum
    for flag in ("paper_only", "no_torch", "no_gpu", "no_redis_writes",
                 "no_exchange_mutation", "no_live_approval"):
        assert flag in res.safety_flags


def test_training_loop_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.training_loop import training_loop_invariants_snapshot

    s = training_loop_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["imports_torch"] is False
    assert s["uses_gpu"] is False
    assert s["writes_model_artifact_by_default"] is False


def test_p0_2d_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/rl_core/training_loop.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import stable_baselines3", "from stable_baselines3",
        "import gymnasium", "from gymnasium",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"training_loop.py contains forbidden: {forbidden}"
