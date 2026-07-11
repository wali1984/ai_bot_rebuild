"""AI prediction missing-feature alert contract.

The prediction is always produced (absent features are masked, not zero-filled),
so the system stays operational end to end. `_build_explanation` must attach a
structured `missing_feature_alert` the web + iOS AI prediction pages can render:
severity scales with data coverage, and it always reports that the prediction was
still produced.
"""
from __future__ import annotations

from app.api.v2.market_contracts import _build_explanation


def _pred(coverage: float | None, missing_count: int, missing_names: list[str], stale: int = 0) -> dict:
    return {
        "selected_action": "long",
        "action_labels": ["hold", "long", "short"],
        "action_probabilities": [0.2, 0.6, 0.2],
        "confidence_calibrated": 0.7,
        "data_coverage_percent": coverage,
        "market_state_integrity_score": 80.0,
        "missing_feature_count": missing_count,
        "missing_feature_names": missing_names,
        "stale_feature_count": stale,
    }


def test_missing_feature_alert_present_and_operational_under_degraded_coverage() -> None:
    out = _build_explanation(
        _pred(53.8, 144, ["coinglass_funding_rate", "liquidation_intensity", "htf_rsi_14"], stale=3),
        None,
    )
    alert = out["missing_feature_alert"]
    assert alert["active"] is True
    assert alert["severity"] == "critical"  # coverage < 60%
    assert alert["operational"] is True
    assert alert["prediction_still_produced"] is True
    assert alert["data_coverage_pct"] == 53.8
    assert alert["missing_feature_count"] == 144
    assert alert["stale_feature_count"] == 3
    assert isinstance(alert["missing_by_category"], dict) and alert["missing_by_category"]
    assert "coverage" in alert["message"].lower()


def test_missing_feature_alert_severity_bands() -> None:
    assert _build_explanation(_pred(85.0, 5, ["x_feature"]), None)["missing_feature_alert"]["severity"] == "info"
    assert _build_explanation(_pred(70.0, 20, ["x_feature"]), None)["missing_feature_alert"]["severity"] == "warn"
    assert _build_explanation(_pred(40.0, 60, ["x_feature"]), None)["missing_feature_alert"]["severity"] == "critical"


def test_missing_feature_alert_none_when_full_coverage() -> None:
    alert = _build_explanation(_pred(100.0, 0, []), None)["missing_feature_alert"]
    assert alert["severity"] == "none"
    assert alert["active"] is False
    assert alert["operational"] is True
    assert alert["missing_by_category"] == {}


def test_missing_feature_alert_unknown_when_coverage_missing() -> None:
    alert = _build_explanation(_pred(None, 0, []), None)["missing_feature_alert"]
    assert alert["severity"] == "unknown"
    assert alert["active"] is False
    # even with unknown coverage the prediction is still produced
    assert alert["prediction_still_produced"] is True
