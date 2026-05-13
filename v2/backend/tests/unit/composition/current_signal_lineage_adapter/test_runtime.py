import sys

import pytest

from v2.backend.app.composition.current_signal_lineage_adapter import (
    CurrentSignalLineageAdapterCompositionError,
    build_current_signal_lineage_adapter_runtime,
)


def _paper_payload() -> dict[str, object]:
    return {
        "generated_at": "2026-05-13T04:54:09Z",
        "live_gate_status": "blocked_human_only",
        "trainer_prediction": {
            "prediction_id": "pred_paper_tick_1",
            "feature_snapshot_id": "fs_paper_tick_1",
            "trainer_state": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        },
        "current_signal_lineage": {
            "lineage_ids": {
                "prediction_id": "pred_paper_tick_1",
                "feature_snapshot_id": "fs_paper_tick_1",
                "signal_id": "sig_paper_tick_1",
                "risk_decision_id": "risk_paper_tick_1",
                "execution_intent_id": "pei_paper_tick_1",
            },
            "signal": {
                "signal_id": "sig_paper_tick_1",
                "proposed_action": "open_short",
            },
            "execution_intent": {
                "execution_intent_id": "pei_paper_tick_1",
                "paper_only": True,
            },
        },
        "current_risk_decision": {
            "risk_decision_id": "risk_paper_tick_1",
            "risk_result": "APPROVED_FOR_PAPER_ONLY",
        },
    }


def test_runtime_does_not_invoke_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 1

    build_current_signal_lineage_adapter_runtime(now_ms_clock=clock)
    assert calls == 0


def test_adapter_builds_current_lineage_record() -> None:
    runtime = build_current_signal_lineage_adapter_runtime(
        now_ms_clock=lambda: 1_778_648_100_000,
        max_runtime_age_seconds=600,
    )

    record = runtime.build_now(
        paper_runtime_payload=_paper_payload(),
        legacy_bridge_payload={"status": "LEGACY_BRIDGE_READONLY"},
        coinank_payload={"availability": {"indicator_smc": True}},
    )

    assert record["classification"] == "CURRENT_V2_PAPER_LINEAGE"
    assert record["lineage_ids"]["signal_id"] == "sig_paper_tick_1"
    assert record["paper_only"] is True
    assert record["legacy_bridge_status"] == "LEGACY_BRIDGE_READONLY"
    assert record["safe_for_live"] is False


def test_adapter_blocks_missing_and_stale_lineage() -> None:
    runtime = build_current_signal_lineage_adapter_runtime(now_ms_clock=lambda: 1_778_700_000_000)
    payload = _paper_payload()
    payload["current_signal_lineage"] = {"lineage_ids": {"signal_id": "sig_paper_tick_1"}}

    record = runtime.build_now(paper_runtime_payload=payload)

    assert record["classification"] == "CURRENT_V2_PAPER_LINEAGE_BLOCKED"
    assert "current_lineage_ids_missing" in record["blockers"]
    assert "paper_runtime_stale_or_missing_generated_at" in record["blockers"]


def test_runtime_rejects_bad_clock() -> None:
    with pytest.raises(CurrentSignalLineageAdapterCompositionError):
        build_current_signal_lineage_adapter_runtime(now_ms_clock=1)  # type: ignore[arg-type]


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.composition.current_signal_lineage_adapter.runtime")
    assert "redis" not in sys.modules
