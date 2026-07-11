"""Realtime backtest + replay-feedback results contract (/api/v2/replay/backtest).

Surfaces the trainer's in-cycle policy backtest, the out-of-sample generalization
signal (validation loss + overfit gap), and the continuous replay -> trainer
feedback, so web + iOS can display whether backtest edge holds up out-of-sample.
Backtest is explicitly NOT A+/live evidence.
"""
from __future__ import annotations

import asyncio
import json

from app.api.v2 import replay as v2_replay


class _FakeRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self._d = data

    def get(self, key: str):
        return self._d.get(key)


def _run(coro):
    return asyncio.run(coro)


def test_backtest_results_surfaces_policy_backtest_generalization_and_replay(monkeypatch) -> None:
    trainer_status = {
        "generated_utc": "2026-07-11T21:00:00Z",
        "effective_trainer_mode": "REPLAY_AND_ONLINE_LEARNING",
        "trusted_replay_examples_built": 1328,
        "cuda_cpu_resource_utilization": {
            "policy_backtest": {
                "win_rate": 0.9895,
                "profit_factor_proxy": 209.29,
                "expectancy_after_cost_bps": 54.49,
                "rows_evaluated": 16384,
                "status": "OK",
                "evidence_class": "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE",
            }
        },
        "learning_metrics": {
            "validation_supervised_loss": 7.63,
            "validation_rows_evaluated": 3276,
            "train_val_generalization_gap": 3.98,
            "overfit_gap_warning": True,
            "loss_before": 87.2,
            "loss_after": 3.65,
        },
    }
    cf = {
        "existing_counterfactual_rows": 3198,
        "new_matured_rows": 173,
        "pending_rows": 1522,
        "trainer_loader_consumes_counterfactual_key": True,
    }
    ef = {"status": "ACTIVE", "generated_utc": "2026-07-11T21:00:00Z", "replay_windows_processed": 42}
    fake = _FakeRedis(
        {
            "v2:trainer:hybrid_cuda:status": json.dumps(trainer_status),
            "v2:trainer:feedback:counterfactual_status": json.dumps(cf),
            "v2:edge_factory:replay_status": json.dumps(ef),
        }
    )
    monkeypatch.setattr(v2_replay, "get_redis", lambda: fake)

    out = _run(v2_replay.get_backtest_results())

    assert out["available"] is True
    assert out["policy_backtest"]["win_rate"] == 0.9895
    assert out["policy_backtest"]["profit_factor_proxy"] == 209.29
    assert out["policy_backtest"]["evidence_class"] == "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE"
    # generalization: the out-of-sample overfit signal must be surfaced honestly
    assert out["generalization"]["overfit_gap_warning"] is True
    assert out["generalization"]["train_val_generalization_gap"] == 3.98
    assert out["generalization"]["validation_rows_evaluated"] == 3276
    # replay -> trainer feedback continuity
    assert out["replay_feedback"]["existing_counterfactual_rows"] == 3198
    assert out["replay_feedback"]["trainer_loader_consumes"] is True
    assert out["continuous_replay_active"] is True
    assert out["effective_trainer_mode"] == "REPLAY_AND_ONLINE_LEARNING"
    # never overclaim: backtest is not A+/live evidence
    assert out["backtest_is_a_plus_evidence"] is False


def test_backtest_results_degrades_gracefully_without_redis(monkeypatch) -> None:
    monkeypatch.setattr(v2_replay, "get_redis", lambda: None)
    out = _run(v2_replay.get_backtest_results())
    assert out["available"] is False
    assert out["backtest_is_a_plus_evidence"] is False
    assert out["policy_backtest"] is None


def test_backtest_results_available_false_when_no_policy_backtest(monkeypatch) -> None:
    fake = _FakeRedis({"v2:trainer:hybrid_cuda:status": json.dumps({"generated_utc": "x"})})
    monkeypatch.setattr(v2_replay, "get_redis", lambda: fake)
    out = _run(v2_replay.get_backtest_results())
    assert out["available"] is False
    assert out["generalization"] is None
