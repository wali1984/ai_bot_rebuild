from __future__ import annotations

from v2.backend.app.services.adaptive_system.data_utilization_funnel_v2 import (
    STAGES,
    build_funnel,
)


def _counts(**overrides):
    base = {s: 100 for s in STAGES}
    base.update(overrides)
    return base


def test_consistent_funnel_with_reconciled_reasons():
    counts = _counts()
    # one drop between feature_snapshots(100) -> finality_proven_snapshots(90)
    counts["finality_proven_snapshots"] = 90
    for s in STAGES[STAGES.index("finality_proven_snapshots"):]:
        counts[s] = 90
    f = build_funnel(counts, {"feature_snapshots": {"NOT_FINALITY_PROVEN": 10}})
    assert f.consistent is True
    assert f.inconsistencies == []
    assert f.overall_utilization_rate == 0.9


def test_non_monotonic_stage_flagged():
    counts = _counts()
    counts["labeled_snapshots"] = 200  # larger than previous stage
    f = build_funnel(counts)
    assert f.consistent is False
    assert any(x.startswith("STAGE_NOT_MONOTONIC") for x in f.inconsistencies)


def test_unexplained_drop_fails_closed():
    counts = _counts()
    for s in STAGES[STAGES.index("cost_complete_snapshots"):]:
        counts[s] = 40  # drop from 100 -> 40 with no reasons
    f = build_funnel(counts)  # no exclusions supplied
    assert f.consistent is False
    assert any(x.startswith("UNEXPLAINED_DROP") for x in f.inconsistencies)


def test_reasons_must_reconcile_to_drop():
    counts = _counts()
    for s in STAGES[STAGES.index("finality_proven_snapshots"):]:
        counts[s] = 80  # drop of 20
    f = build_funnel(counts, {"feature_snapshots": {"NOT_FINALITY_PROVEN": 5}})  # only explains 5 of 20
    assert f.consistent is False
    assert any(x.startswith("DROP_REASONS_DO_NOT_RECONCILE") for x in f.inconsistencies)


def test_invalid_count_flagged():
    counts = _counts()
    counts["training_eligible_rows"] = -3
    f = build_funnel(counts)
    assert any(x.startswith("STAGE_COUNT_INVALID") for x in f.inconsistencies)


def test_to_dict_has_all_stages_and_redis_key():
    f = build_funnel(_counts())
    d = f.to_dict()
    assert d["redis_key"] == "v2:training:data_utilization_funnel"
    assert set(d["stage_counts"].keys()) == set(STAGES)
