"""Guard tests for the orchestrator + risk paper-recovery admission waivers.

These lock in that the recovery waivers admit ONLY paper-only, recovery-tagged
artifacts when recovery mode is enabled, and fail closed on anything that could
route to real execution.
"""

from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_orchestrator_arbitration_loop import (
    _paper_recovery_market_state_waiver,
)
from v2.backend.app.cli.v2_risk_gateway_live_loop import (
    _risk_paper_recovery_trust_gate_admits,
)

ENABLED = {"PAPER_RECOVERY_MODE_ENABLED": "true", "PAPER_RECOVERY_ALLOWED_SYMBOLS": "BTCUSDT"}


def _recovery_prediction(**overrides):
    p = {
        "prediction_id": "recovery_pred_abc123",
        "symbol": "BTCUSDT",
        "paper_recovery_only": True,
        "pit_waiver": True,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "live_eligible": False,
    }
    p.update(overrides)
    return p


def _enable(monkeypatch):
    for k, v in ENABLED.items():
        monkeypatch.setenv(k, v)


def test_orchestrator_waiver_admits_recovery_when_enabled(monkeypatch) -> None:
    _enable(monkeypatch)
    assert _paper_recovery_market_state_waiver(_recovery_prediction()) is True


def test_orchestrator_waiver_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PAPER_RECOVERY_MODE_ENABLED", raising=False)
    assert _paper_recovery_market_state_waiver(_recovery_prediction()) is False


def test_orchestrator_waiver_rejects_non_recovery(monkeypatch) -> None:
    _enable(monkeypatch)
    p = _recovery_prediction()
    p.pop("paper_recovery_only")
    assert _paper_recovery_market_state_waiver(p) is False


@pytest.mark.parametrize(
    "override",
    [
        {"live_gate": "enabled_operator_approved"},
        {"places_real_order": True},
        {"routes_to_live": True},
        {"live_eligible": True},
        {"symbol": "ETHUSDT"},
    ],
)
def test_orchestrator_waiver_fails_closed_on_unsafe(monkeypatch, override) -> None:
    _enable(monkeypatch)
    assert _paper_recovery_market_state_waiver(_recovery_prediction(**override)) is False


def test_risk_waiver_admits_recovery_when_enabled(monkeypatch) -> None:
    _enable(monkeypatch)
    winner = {
        "prediction_id": "recovery_pred_abc123",
        "symbol": "BTCUSDT",
        "places_real_order": False,
        "routes_to_live": False,
    }
    assert _risk_paper_recovery_trust_gate_admits(winner) is True


def test_risk_waiver_rejects_non_recovery_prediction_id(monkeypatch) -> None:
    _enable(monkeypatch)
    assert _risk_paper_recovery_trust_gate_admits({"prediction_id": "hybrid_pred_x"}) is False


def test_risk_waiver_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PAPER_RECOVERY_MODE_ENABLED", raising=False)
    winner = {"prediction_id": "recovery_pred_abc123", "symbol": "BTCUSDT"}
    assert _risk_paper_recovery_trust_gate_admits(winner) is False


@pytest.mark.parametrize("override", [{"places_real_order": True}, {"routes_to_live": True}])
def test_risk_waiver_fails_closed_on_live_marker(monkeypatch, override) -> None:
    _enable(monkeypatch)
    winner = {"prediction_id": "recovery_pred_abc123", "symbol": "BTCUSDT", **override}
    assert _risk_paper_recovery_trust_gate_admits(winner) is False
