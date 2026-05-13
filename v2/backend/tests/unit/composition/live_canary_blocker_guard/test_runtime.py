import sys

import pytest

from v2.backend.app.composition.live_canary_blocker_guard import (
    LiveCanaryBlockerGuardCompositionError,
    build_live_canary_blocker_guard_runtime,
)


def _paper_payload() -> dict[str, object]:
    return {
        "generated_at": "2026-05-13T05:30:00Z",
        "runtime_state": "PAPER_RUNTIME_ONLINE_ACTIVE",
        "live_gate_status": "blocked_human_only",
        "legacy_redis_writes": False,
        "exchange_orders": False,
        "current_risk_decision": {
            "required_blocks_checked": [
                "missing_stop_policy",
                "disabled_kill_switch",
                "daily_loss_breach",
            ]
        },
    }


def test_runtime_does_not_invoke_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 1

    build_live_canary_blocker_guard_runtime(now_ms_clock=clock)
    assert calls == 0


def test_guard_blocks_without_human_approval_and_missing_account_evidence() -> None:
    runtime = build_live_canary_blocker_guard_runtime(now_ms_clock=lambda: 1_778_650_210_000)

    record = runtime.evaluate_now(paper_runtime_payload=_paper_payload())

    assert record["classification"] == "LIVE_CANARY_BLOCKED"
    assert "human_final_approval_token_present" in record["blockers"]
    assert "read_only_account_verified" in record["blockers"]
    assert record["safe_for_live"] is False
    assert record["automation_can_enable_live"] is False


def test_guard_only_allows_human_consideration_when_all_gates_pass() -> None:
    runtime = build_live_canary_blocker_guard_runtime(now_ms_clock=lambda: 1_778_650_210_000)

    record = runtime.evaluate_now(
        paper_runtime_payload=_paper_payload(),
        exchange_account_payload={
            "read_only_account_status": "VERIFIED_READONLY",
            "trade_permission_status": "DISABLED",
            "margin_mode": "isolated",
            "leverage_cap": 1,
        },
        risk_runtime_payload={
            "weekly_loss_gate_required": True,
        },
        approval_token_present=True,
    )

    assert record["classification"] == "LIVE_CANARY_CAN_BE_CONSIDERED_BY_HUMAN_ONLY"
    assert record["blockers"] == []
    assert record["safe_for_live"] is False
    assert record["automation_can_enable_live"] is False


def test_runtime_rejects_bad_inputs() -> None:
    with pytest.raises(LiveCanaryBlockerGuardCompositionError):
        build_live_canary_blocker_guard_runtime(now_ms_clock=1)  # type: ignore[arg-type]

    runtime = build_live_canary_blocker_guard_runtime(now_ms_clock=lambda: 1)
    with pytest.raises(LiveCanaryBlockerGuardCompositionError):
        runtime.evaluate_now(paper_runtime_payload=object())  # type: ignore[arg-type]


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.composition.live_canary_blocker_guard.runtime")
    assert "redis" not in sys.modules
