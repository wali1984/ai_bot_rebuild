import sys

import pytest

from v2.backend.app.composition.execution_attribution_normalizer import (
    ExecutionAttributionNormalizerCompositionError,
    build_execution_attribution_normalizer_runtime,
)


def test_runtime_does_not_invoke_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 1

    build_execution_attribution_normalizer_runtime(now_ms_clock=clock)
    assert calls == 0


def test_normalizer_marks_current_paper_attribution() -> None:
    runtime = build_execution_attribution_normalizer_runtime(now_ms_clock=lambda: 1_700_000_060_000)

    record = runtime.normalize_now(
        paper_execution={
            "signal_id": "sig_paper_tick_1",
            "prediction_id": "pred_paper_tick_1",
            "feature_snapshot_id": "fs_paper_tick_1",
            "risk_decision_id": "risk_paper_tick_1",
            "execution_intent_id": "pei_paper_tick_1",
            "paper_ledger_entry_id": "pledger_paper_tick_1",
            "generated_at_ms": 1_700_000_000_000,
        }
    )

    assert record["classification"] == "P0_EXECUTION_ATTRIBUTION_CURRENT"
    assert record["lineage"]["signal_id"] == "sig_paper_tick_1"
    assert record["safe_for_live"] is False
    assert record["live_gate_status"] == "blocked_human_only"


def test_normalizer_blocks_missing_duplicate_and_stale_attribution() -> None:
    runtime = build_execution_attribution_normalizer_runtime(now_ms_clock=lambda: 1_700_001_000_000)

    record = runtime.normalize_now(
        paper_execution={
            "signal_id": "sig_paper_tick_2",
            "exchange_order_id": "binance-order-1",
            "generated_at_ms": 1_700_000_000_000,
        },
        seen_exchange_order_ids=["binance-order-1"],
    )

    assert record["classification"] == "P0_EXECUTION_ATTRIBUTION_BLOCKED"
    assert record["duplicate_exchange_order_id"] is True
    assert record["stale_signal"] is True
    assert "missing_execution_attribution" in record["blockers"]


def test_runtime_rejects_bad_clock() -> None:
    with pytest.raises(ExecutionAttributionNormalizerCompositionError):
        build_execution_attribution_normalizer_runtime(now_ms_clock=1)  # type: ignore[arg-type]


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.composition.execution_attribution_normalizer.runtime")
    assert "redis" not in sys.modules
