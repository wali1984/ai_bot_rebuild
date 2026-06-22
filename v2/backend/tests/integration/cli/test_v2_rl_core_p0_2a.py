"""P0.2A integration tests: native env + observation + reward suite.

Paper-only. No network IO. No Redis. No torch / SB3 / gymnasium imports.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.trust import TrustGateRejectedError

REPO = Path(__file__).resolve().parents[5]


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


# ----------------------------------------------------------- environment


def test_env_reset_returns_initial_state() -> None:
    from v2.backend.app.services.rl_core.environment import PaperOnlyEnv

    env = PaperOnlyEnv(max_steps=10)
    obs = env.reset()
    assert obs["step_index"] == 0
    assert obs["position_side"] == 0
    assert obs["realized_bps"] == 0.0
    assert obs["unrealized_bps"] == 0.0
    assert obs["done"] is False
    assert obs["live_gate"] == "blocked_human_only"
    assert obs["live_symbols"] == []


def test_env_step_hold_then_long_then_close_runs_paper_only() -> None:
    from v2.backend.app.services.rl_core.environment import (
        ACTION_CLOSE,
        ACTION_HOLD,
        ACTION_LONG,
        PaperOnlyEnv,
    )

    env = PaperOnlyEnv(max_steps=10)
    env.reset()
    obs, c = env.step(ACTION_HOLD)
    assert obs["position_side"] == 0
    obs, c = env.step(ACTION_LONG)
    assert obs["position_side"] == 1
    obs, c = env.step(ACTION_HOLD)
    assert obs["position_side"] == 1
    obs, c = env.step(ACTION_CLOSE)
    assert obs["position_side"] == 0
    # close emitted a realized_bps_delta (may be positive or negative depending on price wave)
    assert "realized_bps_delta" in c


def test_env_step_rejects_unknown_action() -> None:
    from v2.backend.app.services.rl_core.environment import PaperOnlyEnv

    env = PaperOnlyEnv(max_steps=5)
    env.reset()
    with pytest.raises(ValueError):
        env.step(99)


def test_env_reset_required_before_step() -> None:
    from v2.backend.app.services.rl_core.environment import (
        ACTION_HOLD,
        PaperOnlyEnv,
    )

    env = PaperOnlyEnv(max_steps=5)
    with pytest.raises(RuntimeError):
        env.step(ACTION_HOLD)


def test_env_invariants_snapshot_holds_safety_invariants() -> None:
    from v2.backend.app.services.rl_core.environment import (
        env_invariants_snapshot,
    )

    s = env_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["imports_torch"] is False
    assert s["imports_stable_baselines3"] is False
    assert s["imports_gymnasium"] is False
    assert s["imports_redis"] is False
    assert s["places_exchange_orders"] is False
    assert s["writes_legacy_redis"] is False


# ----------------------------------------------------------- observation


def _snapshot_fixture() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "worker_id": "v2_feature_pipeline_native",
        "feature_snapshot_id": "v2_fsnap_abc",
        "generated_at": "2026-05-16T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "features": {
            "ret_pct": 0.001,
            "log_return": 0.00099,
            "range_pct": 0.005,
            "body_pct": 0.0008,
            "true_range_pct": 0.006,
            "gap_pct": 0.0,
            "ema_12": 100.4,
            "ema_26": 100.2,
            "rsi_14": 55.0,
            "macd": 0.05,
            "macd_signal": 0.04,
            "macd_hist": 0.01,
            "bb_width_pct": 0.012,
            "htf_ret_pct": 0.002,
            "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 5.0,
            "depth_imbalance": 0.1,
            "micro_price": 100.0,
            "toxicity_proxy": 0.2,
            "funding_rate": 0.0001,
            "oi_change_pct": 0.01,
            "last_liq_bps_24h": 5.0,
            "paper_position_present": 0,
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
            "feature_hash": "fixture_hash_p0_2a",
            "data_quality_score": 0.99,
            "data_quality_flags": [],
            "is_backfilled": False,
            "is_final_candle": True,
            "missing_candle_count": 0,
            "duplicate_event_count": 0,
            "out_of_order_event_count": 0,
            "source_disagreement_score": 0.0,
            "latency_ms": 0,
            "decision_id": "dec_p0_2a_fixture",
        },
    }


def test_observation_tensor_shape_matches_feature_order() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        OBSERVATION_FEATURE_ORDER,
        build_observation_from_snapshot,
    )

    snap = _snapshot_fixture()
    obs = build_observation_from_snapshot(snap)
    assert obs.tensor_shape == (len(OBSERVATION_FEATURE_ORDER),)
    assert len(obs.tensor) == len(OBSERVATION_FEATURE_ORDER)
    assert obs.feature_snapshot_id == "v2_fsnap_abc"
    assert obs.feature_freshness_state == "CURRENT"


def test_observation_metadata_carries_required_fields() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        observation_metadata,
    )

    snap = _snapshot_fixture()
    meta = observation_metadata(snap)
    for key in (
        "schema_version", "feature_snapshot_id", "feature_count",
        "tensor_shape", "missing_feature_flags", "stale_feature_flags",
        "feature_freshness_state", "categories_present", "symbol",
        "timeframe", "generated_at", "legacy_behavior_mapping",
    ):
        assert key in meta
    assert meta["schema_version"] == "v2_native_observation_tensor_v1"
    assert isinstance(meta["tensor_shape"], list) and meta["tensor_shape"] == [26]


def test_observation_missing_feature_value_maps_to_zero_with_flag_preserved() -> None:
    from v2.backend.app.services.rl_core.observation_builder import (
        build_observation_from_snapshot,
    )

    snap = _snapshot_fixture()
    # Required observation features must now fail closed instead of being
    # silently zero-filled.
    snap["features"]["rsi_14"] = None
    snap["missing_feature_flags"] = ["rsi_14_missing_in_input"]
    with pytest.raises(TrustGateRejectedError) as excinfo:
        build_observation_from_snapshot(snap)
    assert "required_feature_missing:rsi_14" in excinfo.value.trust_gate_result.reject_reasons


# ----------------------------------------------------------- reward suite


def test_reward_suite_components_present_and_total_sum() -> None:
    from v2.backend.app.services.rl_core.rewards import (
        HEDGE_REWARD_CLASSIFICATION,
        compute_reward_suite,
    )

    r = compute_reward_suite(
        realized_bps=20.0,
        unrealized_bps=5.0,
        realized_bps_delta=20.0,
        position_just_closed=True,
        drawdown_bps_abs=0.0,
        time_in_trade_seconds=60,
        position_size_abs=1.0,
        fee_bps_per_side=5.0,
        slippage_bps_per_side=1.0,
        expected_move_after_cost_bps=50.0,
    )
    assert r.base_pnl_reward_bps == 20.0 + 5.0 * 0.5
    assert r.hedge_reward_classification == HEDGE_REWARD_CLASSIFICATION
    assert r.hedge_reward_bps == 0.0
    # Total within reasonable range and not clamped
    assert r.clamped is False


def test_reward_fee_aware_penalizes_high_fee_ratio() -> None:
    from v2.backend.app.services.rl_core.rewards import fee_aware_reward

    bad = fee_aware_reward(
        realized_bps_delta=0.0, fee_bps_per_side=5.0, slippage_bps_per_side=1.0,
        expected_move_after_cost_bps=2.0, position_just_closed=False,
    )
    ok = fee_aware_reward(
        realized_bps_delta=0.0, fee_bps_per_side=1.0, slippage_bps_per_side=0.0,
        expected_move_after_cost_bps=100.0, position_just_closed=False,
    )
    assert bad < ok


def test_reward_constrained_penalty_negative_for_violations() -> None:
    from v2.backend.app.services.rl_core.rewards import constrained_safety_penalty

    p = constrained_safety_penalty(
        drawdown_bps_abs=500.0, max_drawdown_bps=200.0,
        time_in_trade_seconds=7200, max_time_in_trade_seconds=3600,
        position_size_abs=2.0, max_position_size=1.0,
    )
    assert p < 0


def test_reward_hedge_placeholder_is_inert_and_classified_fail_closed() -> None:
    from v2.backend.app.services.rl_core.rewards import (
        HEDGE_REWARD_CLASSIFICATION,
        hedge_reward_placeholder,
    )

    bps, classification = hedge_reward_placeholder()
    assert bps == 0.0
    assert classification == HEDGE_REWARD_CLASSIFICATION
    assert classification == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"


def test_reward_invariants_snapshot_holds_safety_invariants() -> None:
    from v2.backend.app.services.rl_core.rewards import reward_invariants_snapshot

    s = reward_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["hedge_reward_classification"] == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"


# ----------------------------------------------------------- forbidden imports


@pytest.mark.parametrize("rel", [
    "v2/backend/app/services/rl_core/environment.py",
    "v2/backend/app/services/rl_core/observation_builder.py",
    "v2/backend/app/services/rl_core/rewards.py",
])
def test_p0_2a_modules_have_no_forbidden_imports(rel: str) -> None:
    text = (REPO / rel).read_text()
    for forbidden in (
        "import torch", "from torch",
        "import stable_baselines3", "from stable_baselines3",
        "import gymnasium", "from gymnasium",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"{rel} contains forbidden: {forbidden}"


# ----------------------------------------------------------- CLI


def test_cli_p0_2a_rollout_emits_rollout_payload(tmp_path: Path) -> None:
    out_path = tmp_path / "status.json"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot_fixture()))
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_rl_core_worker",
        "--p0-2a-rollout",
        "--rollout-steps",
        "8",
        "--snapshot-path",
        str(snapshot_path),
        "--write-evidence",
        "--output",
        str(out_path),
    ]
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    rollout = payload.get("p0_2a_rollout")
    assert rollout is not None
    assert rollout["migration_classification"] == "PARTIALLY_MIGRATED_P0_2A"
    assert rollout["hedge_reward_classification"] == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"
    assert rollout["rollout_steps_run"] >= 1
    assert rollout["observation_tensor_shape"][0] == 26
    om = rollout["observation_metadata"]
    for key in (
        "feature_snapshot_id", "feature_count", "tensor_shape",
        "missing_feature_flags", "stale_feature_flags",
        "feature_freshness_state",
    ):
        assert key in om
