"""GPU-starvation fix: closed-trade example memo cache.

The resident runtime rebuilds a fresh loader every cycle and re-derived ALL
closed-trade feedback examples each time -- ~12k rows, each a Redis feature-
snapshot GET + tensor build -- which idled the GPU ~48s/cycle. These tests prove
the module-level memo cache makes a warm cycle skip the per-row snapshot GET
while returning identical examples, and that the env kill-switch disables it.
"""
from __future__ import annotations

import importlib

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import data_loader as dl
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)

from tests.unit.services.native_trainer.test_hybrid_trainer_feedback_labels import (
    _FakeTensorBuilder,
    _paper_exploration_feedback,
    _paper_exploration_snapshot,
)

SNAPSHOT_KEY = "v2:features:snapshot:paper-explore-feat"
SOURCE_KEY = "v2:trainer:paper_exploration_materialization_counterfactual_feedback"


class _CountingIO:
    """Fake IO that counts get_json calls per key."""

    def __init__(self, payloads: dict[str, object]):
        self.payloads = payloads
        self.get_calls: dict[str, int] = {}

    def get_json(self, key: str):
        self.get_calls[key] = self.get_calls.get(key, 0) + 1
        return self.payloads.get(key)


def _tensor() -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id="tensor", symbol="ORDIUSDT", timeframe="15m",
        feature_snapshot_id="paper-explore-feat",
        values=(0.0,), missing_mask=(0,), stale_mask=(0,), source_availability=(1,),
        feature_names=("ema_12",), source_labels=("test",),
        missing_feature_names=(), stale_feature_names=(),
        data_coverage_percent=100.0, source_availability_vector=(1,),
    )


def _loader(io: _CountingIO) -> V2HybridTrainerDataLoader:
    return V2HybridTrainerDataLoader(io=io, tensor_builder=_FakeTensorBuilder())


def _payloads() -> dict[str, object]:
    return {
        "v2:trainer:feedback:outcomes": [],
        "v2:trainer:feedback:counterfactuals": [],
        SOURCE_KEY: [_paper_exploration_feedback()],
        SNAPSHOT_KEY: _paper_exploration_snapshot(),
    }


def _load(io: _CountingIO):
    return _loader(io).load_training_examples(
        symbols=["ORDIUSDT"], timeframes=["15m"],
        trusted_only=True, closed_trade_only=True,
    )


def _reset_cache() -> None:
    with dl._CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
        dl._CLOSED_TRADE_EXAMPLE_CACHE.clear()
        dl._CLOSED_TRADE_EXAMPLE_CACHE_STATS.update({"hits": 0, "misses": 0})


def test_warm_cycle_reuses_cached_example_without_resnapshot_get(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "1")
    _reset_cache()

    io1 = _CountingIO(_payloads())
    first = _load(io1)
    assert len(first) == 1
    # Cold cycle: the per-row feature-snapshot GET happened.
    assert io1.get_calls.get(SNAPSHOT_KEY, 0) == 1
    assert dl._CLOSED_TRADE_EXAMPLE_CACHE_STATS["misses"] == 1

    # Warm cycle: a brand-new loader instance (as the runtime rebuilds each
    # cycle) must hit the module-level cache and NOT re-GET the snapshot.
    io2 = _CountingIO(_payloads())
    second = _load(io2)
    assert len(second) == 1
    assert io2.get_calls.get(SNAPSHOT_KEY, 0) == 0
    assert dl._CLOSED_TRADE_EXAMPLE_CACHE_STATS["hits"] == 1
    # Identical example object is served (deterministic build).
    assert second[0] is first[0]


def test_changed_row_rebuilds_and_does_not_serve_stale(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "1")
    _reset_cache()

    _load(_CountingIO(_payloads()))
    # A row with a different realized outcome hashes differently -> rebuild.
    changed = dict(_paper_exploration_feedback())
    changed["realized_net_pnl_bps"] = 999.0
    payloads = _payloads()
    payloads[SOURCE_KEY] = [changed]
    io = _CountingIO(payloads)
    _load(io)
    # The changed row is a cache miss -> the snapshot GET happens again.
    assert io.get_calls.get(SNAPSHOT_KEY, 0) == 1
    assert dl._CLOSED_TRADE_EXAMPLE_CACHE_STATS["misses"] == 2


def test_kill_switch_disables_cache(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "0")
    _reset_cache()

    io1 = _CountingIO(_payloads())
    _load(io1)
    io2 = _CountingIO(_payloads())
    _load(io2)
    # Disabled: every cycle re-GETs the snapshot; cache stays empty.
    assert io1.get_calls.get(SNAPSHOT_KEY, 0) == 1
    assert io2.get_calls.get(SNAPSHOT_KEY, 0) == 1
    assert len(dl._CLOSED_TRADE_EXAMPLE_CACHE) == 0
