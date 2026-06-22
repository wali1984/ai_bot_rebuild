"""P0.2E integration tests: GPU training parity or blocker."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def _snapshot_fixture() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "worker_id": "v2_feature_pipeline_native",
        "feature_snapshot_id": "v2_fsnap_p0_2e_test",
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


def test_gpu_training_module_has_no_module_level_torch_import() -> None:
    text = (REPO / "v2/backend/app/services/rl_core/gpu_training.py").read_text()
    # Module-level "import torch" or "from torch ... import" must be absent.
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith(" ")]
    for line in lines:
        if line.startswith("import torch") or line.startswith("from torch"):
            raise AssertionError(f"gpu_training.py imports torch at module level: {line!r}")


def test_gpu_training_runs_or_returns_explicit_blocker() -> None:
    from v2.backend.app.services.rl_core.gpu_training import (
        run_gpu_training_or_classify_blocker,
    )

    res = run_gpu_training_or_classify_blocker(_snapshot_fixture(), steps=2, lr=0.05)
    assert res.status in (
        "GPU_TRAINING_TINY_PAPER_STEP_RAN",
        "GPU_TRAINING_BLOCKED_TORCH_UNAVAILABLE",
        "GPU_TRAINING_BLOCKED_CUDA_UNAVAILABLE",
        "GPU_TRAINING_BLOCKED_GPU_RUNTIME_ERROR",
    )
    assert res.weight_artifact_written is False
    assert res.observation_dim == 26
    assert res.action_count == 5
    if res.status == "GPU_TRAINING_TINY_PAPER_STEP_RAN":
        assert res.gpu_visible is True
        assert res.device_count >= 1
        assert res.device_name is not None
        assert res.loss_before is not None
        assert res.loss_after is not None


def test_gpu_training_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.gpu_training import (
        gpu_training_invariants_snapshot,
    )

    s = gpu_training_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["imports_torch_at_module_level"] is False
    assert s["writes_model_artifact_by_default"] is False
