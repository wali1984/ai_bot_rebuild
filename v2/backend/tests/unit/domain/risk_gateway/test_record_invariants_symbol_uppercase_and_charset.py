import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_symbol_rejects_invalid_charset_length_and_case() -> None:
    def build(value: object) -> None:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol=value,
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_ALLOW,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )

    for value, reason in (
        (42, "must_be_str"),
        ("", "must_be_non_empty"),
        ("BTC USDT", "must_not_have_whitespace"),
        ("A" * 33, "must_be_at_most_32_chars"),
        ("btcusdt", "must_be_uppercase"),
    ):
        with pytest.raises(RiskGatewayDomainError) as exc_info:
            build(value)
        assert exc_info.value.field == "symbol"
        assert exc_info.value.reason == reason
