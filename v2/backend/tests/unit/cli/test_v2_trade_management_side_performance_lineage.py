"""Point-in-time lineage tests for in-process A+ side-performance derivation."""

from __future__ import annotations

import json
from typing import Any

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


class _RedisReads:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str) -> Any:
        return self.values.get(key)


def test_side_performance_generation_clock_is_after_derivation(
    monkeypatch,
) -> None:
    source_observed = "2026-07-17T12:00:01Z"
    derivation_started = "2026-07-17T12:00:02Z"
    derivation_completed = "2026-07-17T12:00:05Z"
    derived_observed = "2026-07-17T12:00:06Z"
    clock = {"now": source_observed, "calls": 0, "build_completed": False}

    feedback_rows = [
        {
            "paper_session_id": "paper-clock-session",
            "trainer_consumable": True,
            "side": "LONG",
            "realized_net_pnl_bps": 1.25,
            "trainer_feedback_id": "feedback-clock-1",
        }
    ]
    redis = _RedisReads(
        {
            "v2:trainer:feedback:outcomes": json.dumps(feedback_rows),
            "v2:trainer:hybrid_cuda:metrics": json.dumps({}),
            "v2:context:cross_asset": json.dumps({}),
        }
    )

    real_build = paper_loop.build_side_performance

    def delayed_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert clock["now"] == derivation_started
        assert kwargs["generated_utc"] is None
        result = real_build(*args, **kwargs)
        clock["now"] = derivation_completed
        clock["build_completed"] = True
        return result

    def utc_iso() -> str:
        clock["calls"] += 1
        if clock["calls"] == 1:
            clock["now"] = source_observed
        elif clock["calls"] == 2:
            clock["now"] = derivation_started
        elif clock["calls"] == 3:
            assert clock["build_completed"] is True
            assert clock["now"] == derivation_completed
        elif clock["calls"] == 4:
            clock["now"] = derived_observed
        else:  # pragma: no cover - an unexpected clock read is a contract change
            raise AssertionError("unexpected A+ shared-snapshot clock read")
        return str(clock["now"])

    monkeypatch.setattr(paper_loop, "build_side_performance", delayed_build)
    monkeypatch.setattr(paper_loop, "_utc_iso", utc_iso)

    context, lineage = paper_loop._read_a_plus_shared_context_snapshot(  # noqa: SLF001
        redis,
        paper_session_id="paper-clock-session",
    )

    feedback_receipt = next(
        receipt for receipt in lineage if receipt["role"] == "feedback_rows"
    )
    derived_receipt = next(
        receipt
        for receipt in lineage
        if receipt["role"] == "derived_side_performance"
    )
    assert context["side_performance"]["generated_utc"] == derivation_completed
    assert derived_receipt["source_observed_at"] == source_observed
    assert derived_receipt["derivation_started_at"] == derivation_started
    assert derived_receipt["generated_at"] == derivation_completed
    assert derived_receipt["available_at"] == derivation_completed
    assert derived_receipt["observed_at"] == derived_observed
    assert derived_receipt["source_payload_hash"] == feedback_receipt["payload_hash"]
    assert derived_receipt["payload_hash"] == paper_loop._altdata_feature_hash(  # noqa: SLF001
        context["side_performance"]
    )
