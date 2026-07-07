from __future__ import annotations

from v2.backend.app.services.a_plus_trade_gate.service import _quarantine_check


BLOCKED = {
    "status": "ACTIVE",
    "quarantine_active": True,
    "blocked_bucket_keys": [
        "side_timeframe:short|1h",
        "strategy_side_timeframe:reduce_only_recovery|short|1h",
        "strategy_regime:reduce_only_recovery|TREND",
        "timeframe:5m",
    ],
}


def test_candidate_in_quarantined_bucket_fails() -> None:
    result = _quarantine_check(
        BLOCKED, symbol="WLDUSDT", timeframe="1h", side="short", strategy_id="trend_mode"
    )
    assert result["passed"] is False  # side_timeframe:short|1h


def test_candidate_in_clean_bucket_passes() -> None:
    result = _quarantine_check(
        BLOCKED, symbol="BTCUSDT", timeframe="15m", side="long", strategy_id="trend_mode"
    )
    assert result["passed"] is True


def test_regime_bucket_match_fails() -> None:
    result = _quarantine_check(
        BLOCKED,
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        strategy_id="reduce_only_recovery",
        regime_label="TREND",
    )
    assert result["passed"] is False  # strategy_regime:reduce_only_recovery|TREND


def test_active_quarantine_without_keys_fails_closed() -> None:
    payload = {"status": "ACTIVE", "quarantine_active": True}
    result = _quarantine_check(
        payload, symbol="BTCUSDT", timeframe="15m", side="long", strategy_id="trend_mode"
    )
    assert result["passed"] is False


def test_inactive_quarantine_passes() -> None:
    payload = {"status": "CLEAR", "quarantine_active": False}
    result = _quarantine_check(
        payload, symbol="BTCUSDT", timeframe="15m", side="long", strategy_id="trend_mode"
    )
    assert result["passed"] is True
