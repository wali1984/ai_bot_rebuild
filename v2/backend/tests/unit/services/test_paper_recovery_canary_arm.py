from __future__ import annotations

from datetime import UTC, datetime, timedelta

from v2.backend.app.services.paper_recovery.canary_arm_v1 import (
    BYPASSABLE_ECONOMIC_BLOCK_REASONS,
    apply_economic_control_exception,
    consume_canary_arm,
    create_canary_arm,
    validate_canary_arm,
)

NOW = datetime(2026, 7, 25, 1, 30, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def set(self, k, v, ex=None, nx=False):  # noqa: ANN001
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True

    def get(self, k):  # noqa: ANN001
        return self.d.get(k)


def _armed_intent(**overrides):
    intent = {
        "engineering_canary": True,
        "paper_recovery_only": True,
        "live_gate": "blocked_human_only",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "prediction_id": "recovery_pred_x",
        "orchestrator_decision_id": "dec_recovery_pred_x",
        "risk_decision_id": "rd_dec_recovery_pred_x",
        "live_eligible": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    intent.update(overrides)
    return intent


def _arm(r):
    return create_canary_arm(
        r,
        arm_id="arm1",
        symbol="BTCUSDT",
        timeframe="5m",
        prediction_id="recovery_pred_x",
        orchestrator_decision_id="dec_recovery_pred_x",
        risk_decision_id="rd_dec_recovery_pred_x",
        now=NOW,
    )


def test_valid_armed_canary_accepted():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_canary_arm(_armed_intent(), redis_client=r, now=NOW)
    assert reject is None and arm is not None


def test_unarmed_canary_cannot_bypass():
    r = FakeRedis()  # no arm created
    arm, reject = validate_canary_arm(_armed_intent(), redis_client=r, now=NOW)
    assert arm is None and reject == "CANARY_ARM_ABSENT_OR_EXPIRED"


def test_expired_arm_rejected():
    r = FakeRedis()
    _arm(r)
    later = NOW + timedelta(seconds=1000)
    arm, reject = validate_canary_arm(_armed_intent(), redis_client=r, now=later)
    assert arm is None and reject == "CANARY_ARM_EXPIRED"


def test_wrong_symbol_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_canary_arm(_armed_intent(symbol="ETHUSDT"), redis_client=r, now=NOW)
    assert arm is None and reject == "CANARY_ARM_SYMBOL_MISMATCH"


def test_wrong_risk_id_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_canary_arm(
        _armed_intent(risk_decision_id="rd_dec_other"), redis_client=r, now=NOW
    )
    assert arm is None and reject == "CANARY_ARM_RISK_MISMATCH"


def test_live_marker_rejected():
    r = FakeRedis()
    _arm(r)
    markers = ({"live_eligible": True}, {"routes_to_live": True}, {"places_real_order": True})
    for override in markers:
        arm, reject = validate_canary_arm(_armed_intent(**override), redis_client=r, now=NOW)
        assert arm is None and reject == "CANARY_ARM_LIVE_MARKER_PRESENT"


def test_used_arm_rejected():
    r = FakeRedis()
    _arm(r)
    assert consume_canary_arm(r, prediction_id="recovery_pred_x", arm_id="arm1") is True
    assert consume_canary_arm(r, prediction_id="recovery_pred_x", arm_id="arm1") is False
    arm, reject = validate_canary_arm(_armed_intent(), redis_client=r, now=NOW)
    assert arm is None and reject == "CANARY_ARM_ALREADY_CONSUMED"


def test_non_canary_intent_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_canary_arm(
        _armed_intent(engineering_canary=False), redis_client=r, now=NOW
    )
    assert arm is None and reject == "CANARY_ARM_INTENT_NOT_ENGINEERING_CANARY"


def test_exception_removes_only_economic_controls():
    blocks = [
        "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED",
        "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY",
        "PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY",
        "INVALID_LIQUIDATION_BUFFER",
        "MISSING_ENTRY_FEATURE_AVAILABLE_AT",
        "EXPOSURE_CAP_EXCEEDED",
    ]
    remaining, removed = apply_economic_control_exception(blocks, armed=True)
    assert set(removed) == {
        "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED",
        "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY",
        "PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY",
    }
    # every hard control is preserved
    assert "INVALID_LIQUIDATION_BUFFER" in remaining
    assert "MISSING_ENTRY_FEATURE_AVAILABLE_AT" in remaining
    assert "EXPOSURE_CAP_EXCEEDED" in remaining


def test_exception_noop_when_unarmed():
    blocks = ["PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED"]
    remaining, removed = apply_economic_control_exception(blocks, armed=False)
    assert remaining == blocks and removed == []


def test_bypassable_set_is_exactly_the_three_economic_controls():
    assert "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED" in BYPASSABLE_ECONOMIC_BLOCK_REASONS
    assert "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY" in BYPASSABLE_ECONOMIC_BLOCK_REASONS
    assert "PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY" in BYPASSABLE_ECONOMIC_BLOCK_REASONS
    # hard controls must never be in the bypassable set
    for hard in (
        "INVALID_LIQUIDATION_BUFFER",
        "EXPOSURE_CAP_EXCEEDED",
        "MISSING_STOP",
        "INSUFFICIENT_FREE_MARGIN",
        "DUPLICATE_POSITION",
    ):
        assert hard not in BYPASSABLE_ECONOMIC_BLOCK_REASONS
