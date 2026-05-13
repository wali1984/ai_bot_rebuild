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


def _passing_account_payload() -> dict[str, object]:
    return {
        "read_only_account_status": "VERIFIED_READONLY",
        "trade_permission_status": "DISABLED",
        "margin_mode": "isolated",
        "leverage_cap": 1,
    }


def _passing_risk_payload() -> dict[str, object]:
    return {
        "daily_loss_gate_required": True,
        "kill_switch_required": True,
        "leverage_cap": 1,
        "max_risk_add_signal_age_seconds": 10,
        "required_margin_mode": "isolated",
        "risk_config_version": "risk_canary_v1",
        "stop_policy_required": True,
        "weekly_loss_gate_required": True,
    }


def _valid_intent() -> dict[str, object]:
    return {
        "action": "OPEN",
        "confidence": 0.71,
        "daily_loss_gate_present": True,
        "execution_intent_id": "intent_1",
        "feature_snapshot_current": True,
        "feature_snapshot_id": "feature_1",
        "kill_switch_healthy": True,
        "leverage": 1,
        "leverage_cap": 1,
        "margin_mode": "isolated",
        "market_feed_current": True,
        "prediction_id": "prediction_1",
        "risk_config_version": "risk_canary_v1",
        "signal_generated_at": "2026-05-13T05:30:09Z",
        "signal_id": "signal_1",
        "source_module": "v2.paper_shadow",
        "stop_policy_present": True,
        "weekly_loss_gate_present": True,
    }


def _evaluate_intent(intent: dict[str, object]) -> dict[str, object]:
    runtime = build_live_canary_blocker_guard_runtime(now_ms_clock=lambda: 1_778_650_210_000)
    return runtime.evaluate_now(
        paper_runtime_payload=_paper_payload(),
        exchange_account_payload=_passing_account_payload(),
        risk_runtime_payload=_passing_risk_payload(),
        intent_payload=intent,
        approval_token_present=True,
    )


def test_valid_hypothetical_canary_intent_still_never_marks_automation_live_safe() -> None:
    record = _evaluate_intent(_valid_intent())

    assert record["classification"] == "LIVE_CANARY_CAN_BE_CONSIDERED_BY_HUMAN_ONLY"
    assert record["intent_blockers"] == []
    assert record["safe_for_live"] is False
    assert record["automation_can_enable_live"] is False


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("signal_id", "missing_signal_id"),
        ("prediction_id", "missing_prediction_id"),
        ("feature_snapshot_id", "missing_feature_snapshot_id"),
        ("confidence", "missing_confidence"),
        ("source_module", "missing_source_module"),
    ],
)
def test_missing_attribution_fields_block_risk_add_intent(field: str, reason: str) -> None:
    intent = _valid_intent()
    intent.pop(field)

    record = _evaluate_intent(intent)

    assert record["classification"] == "LIVE_CANARY_BLOCKED"
    assert reason in record["intent_blockers"]


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"signal_generated_at": "2026-05-13T05:29:49Z"}, "stale_risk_add_signal"),
        ({"exchange_order_id": "order_1", "seen_exchange_order_ids": ["order_1"]}, "duplicate_exchange_order_id"),
        ({"execution_intent_id": "intent_1", "seen_execution_intent_ids": ["intent_1"]}, "duplicate_execution_intent_id"),
        ({"signal_id": "signal_1", "seen_signal_ids": ["signal_1"]}, "duplicate_signal_id"),
        ({"margin_mode": "cross"}, "cross_margin_blocked_for_canary"),
        ({"margin_mode": "unknown"}, "isolated_margin_not_verified"),
        ({"leverage_cap": None}, "leverage_cap_unknown"),
        ({"leverage": 2}, "leverage_above_cap"),
        ({"action": "ADJUST_LEVERAGE"}, "adjust_leverage_disabled_by_default"),
        ({"action": "ADJUST_LEVERAGE_AND_POSITION"}, "adjust_leverage_and_position_disabled_by_default"),
        ({"action": "HEDGE"}, "hedge_dca_disabled_initially"),
        ({"action": "DCA"}, "hedge_dca_disabled_initially"),
        ({"stop_policy_present": False}, "missing_stop_policy"),
        ({"kill_switch_healthy": False}, "kill_switch_unhealthy"),
        ({"daily_loss_gate_present": False}, "daily_loss_gate_missing"),
        ({"weekly_loss_gate_present": False}, "weekly_loss_gate_missing"),
        ({"market_feed_current": False}, "market_feed_stale_or_missing"),
        ({"feature_snapshot_current": False}, "feature_snapshot_stale_or_missing"),
        ({"risk_config_version": None}, "missing_risk_config_version"),
    ],
)
def test_unsafe_canary_intent_variants_block_with_specific_reason(
    patch: dict[str, object],
    reason: str,
) -> None:
    intent = _valid_intent() | patch

    record = _evaluate_intent(intent)

    assert record["classification"] == "LIVE_CANARY_BLOCKED"
    assert reason in record["intent_blockers"]


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
