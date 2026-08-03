"""P0.2B integration tests: CPU forward-pass policy + adapters."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


def _snapshot_fixture() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "worker_id": "v2_feature_pipeline_native",
        "feature_snapshot_id": "v2_fsnap_p0_2b_test",
        "generated_at": "2026-05-16T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
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
            "ohlcv_derived","ta_indicators","multi_timeframe",
            "microstructure","funding_oi_liquidation","portfolio_aware","freshness",
        ],
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "market_state_envelope": {
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "decision_time": "2026-05-16T00:00:00+00:00",
            "event_time": "2026-05-16T00:00:00+00:00",
            "available_at": "2026-05-16T00:00:00+00:00",
            "ingested_at": "2026-05-16T00:00:00+00:00",
            "timeframe_cutoffs": {"1m": "2026-05-16T00:00:00+00:00"},
            "feature_cutoff": "2026-05-16T00:00:00+00:00",
            "feature_version": "v2_native_feature_snapshot_v1",
            "feature_hash": "fixture_hash_p0_2b",
            "data_quality_score": 0.99,
            "data_quality_flags": [],
            "is_backfilled": False,
            "is_final_candle": True,
            "missing_candle_count": 0,
            "duplicate_event_count": 0,
            "out_of_order_event_count": 0,
            "source_disagreement_score": 0.0,
            "latency_ms": 0,
            "decision_id": "dec_p0_2b_fixture",
        },
    }


def test_policy_forward_produces_logits_and_probs() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )
    from v2.backend.app.services.rl_core.policy import (
        ACTION_COUNT,
        ACTION_LABELS,
        V2NativeCPUPolicy,
    )
    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    pol = V2NativeCPUPolicy()
    r = pol.forward(obs.tensor, feature_snapshot_id=obs.feature_snapshot_id)
    assert len(r.action_logits) == ACTION_COUNT
    assert len(r.action_probabilities) == ACTION_COUNT
    assert r.action_labels == ACTION_LABELS
    s = sum(r.action_probabilities)
    assert 0.999 <= s <= 1.001
    assert r.selected_action in ACTION_LABELS
    assert r.observation_feature_snapshot_id == obs.feature_snapshot_id
    assert r.model_source_classification == "V2_NATIVE_CPU_DETERMINISTIC_INIT_NO_CHECKPOINT"


def test_policy_forward_is_deterministic_for_same_seed() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )
    from v2.backend.app.services.rl_core.policy import V2NativeCPUPolicy

    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    a = V2NativeCPUPolicy(seed=42).forward(obs.tensor)
    b = V2NativeCPUPolicy(seed=42).forward(obs.tensor)
    assert a.action_logits == b.action_logits
    assert a.action_probabilities == b.action_probabilities
    assert a.policy_id == b.policy_id


def test_policy_hedge_action_is_masked_when_mask_hedge_true() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )
    from v2.backend.app.services.rl_core.policy import (
        HEDGE_ACTION_INDEX,
        V2NativeCPUPolicy,
    )

    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    masked = V2NativeCPUPolicy(mask_hedge=True).forward(obs.tensor)
    unmasked = V2NativeCPUPolicy(mask_hedge=False).forward(obs.tensor)
    assert masked.action_probabilities[HEDGE_ACTION_INDEX] < 1e-6
    assert unmasked.action_probabilities[HEDGE_ACTION_INDEX] > 0.0
    assert masked.selected_action != "hedge"


def test_policy_rejects_wrong_dim_observation() -> None:
    from v2.backend.app.services.rl_core.policy import V2NativeCPUPolicy

    pol = V2NativeCPUPolicy()
    with pytest.raises(ValueError):
        pol.forward([0.0] * 10)


def test_masa_adapter_returns_action_and_value_shape() -> None:
    from v2.backend.app.services.rl_core.masa_adapter import V2MASAAdapter
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )

    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    a = V2MASAAdapter()
    res = a.get_action_and_value(
        obs.tensor,
        feature_snapshot_id=obs.feature_snapshot_id,
        observation_contract=obs,
    )
    assert res.is_finite is True
    assert res.selected_action in ("hold", "long", "short", "close", "hedge")
    assert res.feature_snapshot_id == obs.feature_snapshot_id
    assert res.hedge_action_classification == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"
    assert isinstance(res.value_estimate_bps, float)


def test_ppo_predict_returns_log_prob_for_selected_action() -> None:
    import math
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )
    from v2.backend.app.services.rl_core.ppo_policy import V2NativePPOPolicy

    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    p = V2NativePPOPolicy().predict(obs.tensor, feature_snapshot_id=obs.feature_snapshot_id)
    p_sel = p.action_probabilities[p.selected_action_index]
    assert math.isclose(p.log_prob_selected, math.log(max(p_sel, 1e-12)), rel_tol=1e-6, abs_tol=1e-9)
    assert p.deterministic is True


@pytest.mark.parametrize("rel", [
    "v2/backend/app/services/rl_core/policy.py",
    "v2/backend/app/services/rl_core/masa_adapter.py",
    "v2/backend/app/services/rl_core/ppo_policy.py",
])
def test_p0_2b_modules_have_no_forbidden_imports(rel: str) -> None:
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


def test_p0_2b_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.policy import policy_invariants_snapshot
    from v2.backend.app.services.rl_core.masa_adapter import masa_invariants_snapshot
    from v2.backend.app.services.rl_core.ppo_policy import ppo_invariants_snapshot

    for snap in (policy_invariants_snapshot(), masa_invariants_snapshot(), ppo_invariants_snapshot()):
        assert snap["live_gate"] == "blocked_human_only"
        assert snap["live_symbols"] == []
        assert snap["imports_torch"] is False
        assert snap["loads_checkpoint_weights"] is False
        assert snap["hedge_action_classification"] == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"
